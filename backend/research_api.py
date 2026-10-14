import asyncio
import base64
import json
import mimetypes
import os
import re
import shutil
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from auth import get_current_user, get_db
from database import SessionLocal
from document_loader import DocumentLoader
from models import ResearchArtifact, ResearchProject, ResearchSource, User
from research_schemas import (
    ResearchArtifactResponse,
    ResearchAssistantRequest,
    ResearchProjectCreate,
    ResearchProjectListResponse,
    ResearchProjectResponse,
    ResearchRevisionRequest,
    ResearchRunRequest,
    ResearchRunResponse,
    ResearchSourceCreate,
    ResearchSourceResponse,
    ResearchUploadResponse,
)
from research_store import research_store
from research_workflow import (
    FIXED_AI_SEARCH_ENABLED,
    FIXED_GENERATE_PROPOSAL,
    FIXED_MAX_RESULTS_PER_QUERY,
    FIXED_MAX_SEARCH_ROUNDS,
    FIXED_MIN_SOURCES_PER_MODULE,
    _project_doc_title,
    research_workflow,
    WorkflowPaused,
)

router = APIRouter(prefix="/research", tags=["research"])

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "data" / "research_uploads"
loader = DocumentLoader()
RUNNING_PROJECT_IDS: set[int] = set()
PAUSE_REQUESTED_PROJECT_IDS: set[int] = set()
RUNNING_PROJECT_LOCK = threading.Lock()
RUNNING_PROJECT_EVENTS: dict[int, list[dict]] = {}
RUNNING_PROJECT_SUBSCRIBERS: dict[int, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}
RUNNING_EVENT_BUFFER_LIMIT = 500


def recover_stale_research_projects() -> int:
    """Make interrupted in-process workflows resumable after a backend restart."""
    stale_minutes = max(5, min(1440, int(os.getenv("RESEARCH_STALE_RUN_MINUTES", "15"))))
    cutoff = datetime.utcnow() - timedelta(minutes=stale_minutes)
    active_statuses = {
        "planning", "searching", "source_assessing", "cleaning", "risk_assessing",
        "report_generating", "proposal_generating", "pausing",
    }
    db = SessionLocal()
    try:
        stale = (
            db.query(ResearchProject)
            .filter(ResearchProject.status.in_(active_statuses), ResearchProject.updated_at < cutoff)
            .all()
        )
        for project in stale:
            project.status = "paused"
            project.updated_at = datetime.utcnow()
        if stale:
            db.commit()
        return len(stale)
    except Exception:
        db.rollback()
        return 0
    finally:
        db.close()


def _mark_project_running(project_id: int) -> bool:
    with RUNNING_PROJECT_LOCK:
        if project_id in RUNNING_PROJECT_IDS:
            return False
        RUNNING_PROJECT_IDS.add(project_id)
        PAUSE_REQUESTED_PROJECT_IDS.discard(project_id)
        RUNNING_PROJECT_EVENTS[project_id] = []
        return True


def _unmark_project_running(project_id: int) -> None:
    with RUNNING_PROJECT_LOCK:
        RUNNING_PROJECT_IDS.discard(project_id)


def _is_project_running(project_id: int) -> bool:
    with RUNNING_PROJECT_LOCK:
        return project_id in RUNNING_PROJECT_IDS


def _is_pause_requested(project_id: int) -> bool:
    with RUNNING_PROJECT_LOCK:
        return project_id in PAUSE_REQUESTED_PROJECT_IDS


@router.post("/projects/{project_id}/pause")
async def pause_research_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _get_project(db, project_id, current_user)
    if project.status in {"completed", "failed", "draft", "paused"}:
        if project.status == "paused":
            return {"status": "paused", "message": "任务已经暂停"}
        raise HTTPException(status_code=409, detail="当前任务状态不支持暂停")
    with RUNNING_PROJECT_LOCK:
        PAUSE_REQUESTED_PROJECT_IDS.add(project_id)
    project.status = "pausing" if _is_project_running(project_id) else "paused"
    project.updated_at = datetime.utcnow()
    db.commit()
    return {"status": project.status, "message": "已提交暂停请求；当前外部请求完成后将在安全检查点暂停"}


def _publish_running_event(project_id: int, event: dict) -> None:
    with RUNNING_PROJECT_LOCK:
        buffer = RUNNING_PROJECT_EVENTS.setdefault(project_id, [])
        buffer.append(event)
        if len(buffer) > RUNNING_EVENT_BUFFER_LIMIT:
            del buffer[: len(buffer) - RUNNING_EVENT_BUFFER_LIMIT]
        subscribers = list(RUNNING_PROJECT_SUBSCRIBERS.get(project_id, []))
    for loop, queue in subscribers:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, event)
        except RuntimeError:
            pass


def _running_event_snapshot(project_id: int) -> list[dict]:
    with RUNNING_PROJECT_LOCK:
        return list(RUNNING_PROJECT_EVENTS.get(project_id, []))


def _subscribe_running_project(project_id: int, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
    with RUNNING_PROJECT_LOCK:
        RUNNING_PROJECT_SUBSCRIBERS.setdefault(project_id, []).append((loop, queue))


def _unsubscribe_running_project(project_id: int, queue: asyncio.Queue) -> None:
    with RUNNING_PROJECT_LOCK:
        subscribers = RUNNING_PROJECT_SUBSCRIBERS.get(project_id, [])
        RUNNING_PROJECT_SUBSCRIBERS[project_id] = [(loop, item) for loop, item in subscribers if item is not queue]
        if not RUNNING_PROJECT_SUBSCRIBERS[project_id]:
            RUNNING_PROJECT_SUBSCRIBERS.pop(project_id, None)


def _locked_run_intake(request: ResearchRunRequest, target_type: str = "") -> dict:
    effective_type = request.target_type or target_type
    intake = request.model_dump(exclude_unset=effective_type == "industry")
    intake.update(
        {
            "max_results_per_query": FIXED_MAX_RESULTS_PER_QUERY,
            "generate_proposal": FIXED_GENERATE_PROPOSAL,
            "ai_search_enabled": FIXED_AI_SEARCH_ENABLED,
            "min_sources_per_module": FIXED_MIN_SOURCES_PER_MODULE,
            "max_search_rounds": FIXED_MAX_SEARCH_ROUNDS,
        }
    )
    if effective_type == "industry":
        intake["target_type"] = "industry"
        intake["ai_search_enabled"] = request.ai_search_enabled
        intake["max_search_rounds"] = min(3, max(1, request.max_search_rounds))
    return intake

def _clip_text(text: str, limit: int = 4000) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "\n...[truncated]"


def _artifact_store_key(artifact: ResearchArtifact) -> str:
    metadata = artifact.artifact_metadata or {}
    if artifact.artifact_type == "cleaned_facts" and metadata.get("markdown_object_key"):
        return metadata["markdown_object_key"]
    return artifact.object_key


def _read_store_text(key: str | None, fallback: str = "") -> str:
    if not key:
        return fallback or ""
    try:
        text = research_store.get_text(key)
        return text if text.strip() else (fallback or "")
    except Exception:
        return fallback or ""


def _safe_download_name(name: str, fallback: str = "artifact") -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', "_", (name or "").strip()).strip(" ._")
    return cleaned or fallback


def _download_headers(filename: str) -> dict[str, str]:
    ascii_fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._") or "download"
    return {"Content-Disposition": f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"}


def _assistant_project_ids(db: Session, current_user: User, project_id: int | None) -> list[int]:
    if project_id:
        project = _get_project(db, project_id, current_user)
        return [project.id]
    query = db.query(ResearchProject.id)
    if current_user.role != "admin":
        query = query.filter(ResearchProject.created_by_id == current_user.id)
    return [row[0] for row in query.all()]


def _is_project_list_question(question: str) -> bool:
    compact = re.sub(r"\s+", "", question or "")
    return any(token in compact for token in ("哪些项目", "项目列表", "做过什么项目", "做过哪些项目", "我的项目"))


def _is_assistant_greeting(question: str) -> bool:
    compact = re.sub(r"[\s!！。,.，?？~～]+", "", question or "").lower()
    return compact in {"你好", "您好", "hi", "hello", "hey", "哈喽", "在吗"}


def _format_user_project_list(db: Session, current_user: User) -> str:
    query = db.query(ResearchProject)
    if current_user.role != "admin":
        query = query.filter(ResearchProject.created_by_id == current_user.id)
    projects = query.order_by(ResearchProject.updated_at.desc()).limit(30).all()
    if not projects:
        return "当前账号下还没有可访问的研究项目。"
    lines = ["你当前可访问的研究项目如下：", ""]
    for item in projects:
        lines.append(
            f"- #{item.id} {item.title or item.target_name or '未命名项目'}"
            f"｜对象：{item.target_name or '-'}"
            f"｜类型：{item.target_type or '-'}"
            f"｜状态：{item.status or '-'}"
            f"｜更新时间：{item.updated_at.strftime('%Y-%m-%d %H:%M') if item.updated_at else '-'}"
        )
    return "\n".join(lines)


def _keyword_score(text: str, query: str) -> int:
    lowered = (text or "").lower()
    terms = [term for term in re.split(r"\s+", query.lower()) if term]
    return sum(lowered.count(term) for term in terms) + (1 if query.lower() in lowered else 0)


def _vector_context(project_ids: list[int], question: str, limit: int) -> list[dict]:
    try:
        from embedding import embedding_service
        from milvus_client import MilvusManager

        dense, sparse = embedding_service.get_all_embeddings([question])
        if not dense:
            return []
        artifact_types = '["cleaned_facts", "first_hand", "human_review_report", "human_review_proposal", "upload"]'
        if len(project_ids) == 1:
            filter_expr = f"project_id == {project_ids[0]} and artifact_type in {artifact_types}"
        else:
            filter_expr = f"project_id in {project_ids} and artifact_type in {artifact_types}"
        rows = MilvusManager().hybrid_retrieve(dense[0], sparse[0], top_k=limit, filter_expr=filter_expr)
        return [
            {
                "kind": "vector_cleaned_fact",
                "title": row.get("filename") or "清洗事实",
                "project_id": row.get("project_id", ""),
                "text": row.get("text", ""),
                "source": row.get("source_url") or row.get("file_path") or "cleaned_facts_vector",
            }
            for row in rows
            if row.get("text")
        ]
    except Exception:
        return []


def _project_store_context(db: Session, project_ids: list[int], question: str, limit: int) -> list[dict]:
    if not project_ids:
        return []
    rows: list[dict] = []
    sources = (
        db.query(ResearchSource)
        .filter(ResearchSource.project_id.in_(project_ids))
        .order_by(ResearchSource.credibility_score.desc(), ResearchSource.created_at.desc())
        .limit(200)
        .all()
    )
    for source in sources:
        text = _read_store_text(source.object_key, source.content or source.summary)
        score = _keyword_score(" ".join([source.title, source.url, source.summary, text[:2000]]), question)
        rows.append(
            {
                "kind": "source",
                "project_id": source.project_id,
                "title": source.title,
                "source": source.url or source.object_key,
                "text": text,
                "score": score + max(0, int(source.credibility_score or 0)) / 100,
            }
        )
    artifacts = (
        db.query(ResearchArtifact)
        .filter(ResearchArtifact.project_id.in_(project_ids))
        .order_by(ResearchArtifact.created_at.desc())
        .limit(200)
        .all()
    )
    for artifact in artifacts:
        key = _artifact_store_key(artifact)
        text = _read_store_text(key, artifact.content)
        score = _keyword_score(" ".join([artifact.title, artifact.artifact_type, text[:3000]]), question)
        rows.append(
            {
                "kind": f"artifact:{artifact.artifact_type}",
                "project_id": artifact.project_id,
                "title": artifact.title,
                "source": key,
                "text": text,
                "score": score + (2 if artifact.artifact_type == "cleaned_facts" else 0),
            }
        )
    rows.sort(key=lambda item: item.get("score", 0), reverse=True)
    return rows[:limit]


def _format_assistant_context(contexts: list[dict], limit_chars: int = 18000) -> str:
    blocks = []
    total = 0
    for index, item in enumerate(contexts, 1):
        text = _clip_text(item.get("text", ""), 2500)
        block = (
            f"[{index}] {item.get('title', '')}\n"
            f"类型：{item.get('kind', '')}\n"
            f"项目ID：{item.get('project_id', '')}\n"
            f"来源：{item.get('source', '')}\n"
            f"内容：{text}"
        )
        if total + len(block) > limit_chars:
            break
        blocks.append(block)
        total += len(block)
    return "\n\n---\n\n".join(blocks)


def _general_research_overview(question: str) -> str:
    """Return a clearly-labelled fallback for a small set of out-of-library topics.

    The assistant is primarily evidence-grounded.  These concise overviews keep
    the chat useful when a user asks about the two research topics promoted in
    the product, without presenting the content as project evidence.
    """
    normalized = re.sub(r"\s+", "", question or "").lower()
    if any(term in normalized for term in ("视频生成", "文生视频", "视频模型", "video generation")):
        return """根据内置研究资料，视频生成模型可从以下维度展开研究：

视频生成模型正从短片段的文生视频，演进到可控镜头、角色一致性、音画同步和面向生产流程的工作流能力。研究时建议从四条主线展开：

1. **技术路线**：扩散式视频生成仍是主流；重点比较时空一致性、长时序稳定性、运动质量、镜头控制和多模态输入能力。[1]
2. **产品与场景**：广告素材、短视频创作、影视预演、游戏资产、教育培训和企业营销，是当前最常见的落地场景；企业客户通常更看重可控性、版权与交付效率。[1]
3. **商业化判断**：可关注 API 调用、订阅制创作工具、行业工作流软件和定制服务四种模式，并核验单位生成成本、推理速度、留存率和付费转化。[2]
4. **主要风险**：训练数据与生成内容版权、肖像与深度伪造、内容安全、算力成本，以及不同地区的合规要求。[2]

若要形成深度报告，建议下一步补充：目标市场、重点公司名单、模型测评样本、价格与调用量数据，以及客户访谈或真实项目案例。

资料来源：

[1] 内置研究资料：视频生成模型技术与应用框架
[2] 内置研究资料：视频生成商业化与风险核查要点"""
    if any(term in normalized for term in ("脑机", "脑机接口", "bci", "brain-computer")):
        return """根据内置研究资料，脑机接口（BCI）行业可按“信号采集—解码算法—交互/治疗应用—临床与监管”来理解。当前行业仍以医疗康复和科研应用为主，同时在非侵入式消费级交互、睡眠与专注训练等方向探索商业化。

1. **技术分层**：非侵入式设备使用头戴式 EEG 等方案，易部署但信号分辨率有限；侵入式方案信号质量更高，但涉及手术、长期安全性和监管审批。[1]
2. **核心应用**：运动与语言障碍辅助、神经康复、假肢/外部设备控制、神经疾病研究，是价值和临床证据最集中的方向。[1]
3. **产业链与壁垒**：上游包括传感器、电极和硬件；中游是信号处理、算法和系统集成；下游是医院、康复机构与终端应用。临床证据、数据质量、算法泛化和监管能力是主要壁垒。[2]
4. **投资与风险观察**：重点核验临床试验进度、监管路径、真实患者使用数据、硬件可靠性、数据隐私与伦理治理；短期内不宜只用概念热度判断商业价值。[2]

若要形成可交付的深度研究，建议明确研究区域、侵入式或非侵入式范围、重点疾病/场景，并补充监管文件、临床论文、企业访谈和产品试用证据。

资料来源：

[1] 内置研究资料：脑机接口技术路线与应用场景
[2] 内置研究资料：脑机接口产业链、临床与合规框架"""
    return ""

def _delete_local_upload(path_value: str | None) -> None:
    if not path_value:
        return
    try:
        path = Path(path_value).resolve()
        root = UPLOAD_DIR.resolve()
        if root in path.parents and path.is_file():
            path.unlink(missing_ok=True)
    except Exception:
        pass


def _project_response(project: ResearchProject) -> ResearchProjectResponse:
    return ResearchProjectResponse(
        id=project.id,
        title=project.title,
        target_name=project.target_name,
        target_type=project.target_type,
        industry=project.industry,
        description=project.description,
        status=project.status,
        created_at=project.created_at.isoformat(),
        updated_at=project.updated_at.isoformat(),
    )


def _normalize_target_type(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if raw in {"person", "individual", "founder"} or "目标人" in raw:
        return "person"
    if raw in {"industry", "sector", "market"} or "目标行业" in raw:
        return "industry"
    if raw in {"company", "corp", "enterprise"} or "目标公司" in raw:
        return "company"
    return "company"


def _source_response(source: ResearchSource) -> ResearchSourceResponse:
    return ResearchSourceResponse(
        id=source.id,
        project_id=source.project_id,
        source_type=source.source_type,
        title=source.title,
        url=source.url,
        summary=source.summary,
        credibility_score=source.credibility_score,
        created_at=source.created_at.isoformat(),
    )


def _artifact_response(artifact: ResearchArtifact, include_content: bool = True) -> ResearchArtifactResponse:
    return ResearchArtifactResponse(
        id=artifact.id,
        project_id=artifact.project_id,
        artifact_type=artifact.artifact_type,
        title=artifact.title,
        version=artifact.version,
        # Report and cleaned-fact bodies can be very large.  List/detail views only
        # need their metadata; callers that explicitly need the body keep the
        # previous default behaviour.
        content=artifact.content if include_content else "",
        object_key=artifact.object_key,
        metadata=artifact.artifact_metadata or {},
        created_by=artifact.created_by,
        created_at=artifact.created_at.isoformat(),
    )


def _normalize_report_lookup_query(value: str) -> str:
    text = re.sub(r"\s+", "", value or "").lower()
    for token in ("的背景调查报告", "背景调查报告", "背调报告", "尽调报告", "人物报告", "公司报告", "行业报告", "报告"):
        text = text.replace(token, "")
    return text


def _source_library_name(source: ResearchSource) -> str:
    meta = source.source_metadata or {}
    for key in ("library", "provider", "platform", "search_provider", "tool", "source_library"):
        value = str(meta.get(key) or "").strip()
        if value:
            return value
    url = (source.url or "").lower()
    if url.startswith("structured://xiniu"):
        return "稀牛结构化库"
    if url.startswith("structured://qcc"):
        return "企查查结构化库"
    if "tianyancha" in url or "tianyancha.com" in url:
        return "天眼查公开库"
    if url.startswith(("http://", "https://")):
        return "公开网页检索库"
    return source.source_type or "项目来源库"


def _trace_summary_from_project(project: ResearchProject, sources: list[ResearchSource], artifacts: list[ResearchArtifact]) -> dict:
    library_counts: dict[str, int] = {}
    for source in sources:
        library = _source_library_name(source)
        library_counts[library] = library_counts.get(library, 0) + 1
    report_artifacts = [
        item for item in artifacts
        if item.artifact_type in {"report", "docx", "pdf"} or "报告" in item.title
    ]
    latest_report = max(report_artifacts, key=lambda item: item.created_at, default=None)
    return {
        "mock": False,
        "data_status": "database",
        "query_matched": True,
        "project": _project_response(project).model_dump(),
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
        "trace_libraries": [
            {"name": name, "source_count": count}
            for name, count in sorted(library_counts.items(), key=lambda item: item[1], reverse=True)
        ],
        "source_count": len(sources),
        "artifact_count": len(artifacts),
        "latest_report": _artifact_response(latest_report, include_content=False).model_dump() if latest_report else None,
        "sources": [_source_response(item).model_dump() for item in sources[:12]],
        "artifacts": [_artifact_response(item, include_content=False).model_dump() for item in artifacts[:8]],
        "timeline": [
            {"label": "项目创建", "time": project.created_at.isoformat()},
            {"label": "最近更新", "time": project.updated_at.isoformat()},
        ],
        "notes": ["该结果来自当前用户可访问的研究项目数据库。"],
    }


def _mock_mayun_trace_summary(query: str) -> dict:
    created_at = "2026-07-17T13:01:08"
    updated_at = "2026-07-21T15:01:59"
    return {
        "mock": True,
        "data_status": "static_demo",
        "query": query,
        "query_matched": True,
        "project": {
            "id": 680011,
            "title": "马云6.8背景调查报告",
            "target_name": "马云",
            "target_type": "person",
            "industry": "互联网 / 电子商务 / 科技投资",
            "description": "自动检索生成的二手公开信息人物背景研究底稿演示数据。",
            "status": "completed",
            "created_at": created_at,
            "updated_at": updated_at,
        },
        "created_at": created_at,
        "updated_at": updated_at,
        "trace_libraries": [
            {"name": "公开网页检索库", "source_count": 96, "examples": ["人物百科", "媒体报道", "公开访谈"]},
            {"name": "企业结构化库", "source_count": 48, "examples": ["企查查", "天眼查", "稀牛"]},
            {"name": "监管/司法公开库", "source_count": 31, "examples": ["法院公告", "交易所公告", "监管公示"]},
            {"name": "项目证据台账", "source_count": 47, "examples": ["清洗事实", "证据编号", "章节引用索引"]},
        ],
        "source_count": 222,
        "artifact_count": 5,
        "latest_report": {
            "id": 68001105,
            "project_id": 680011,
            "artifact_type": "report",
            "title": "马云6.8背景调查报告_v11",
            "version": 11,
            "content": "",
            "object_key": "demo/projects/680011/reports/mayun_v11.docx",
            "metadata": {"mock": True, "review_status": "auto_generated_draft"},
            "created_by": "agent",
            "created_at": updated_at,
        },
        "sources": [
            {
                "id": 1,
                "project_id": 680011,
                "source_type": "public_web",
                "title": "马云公开人物资料",
                "url": "https://zh.wikipedia.org/wiki/马云",
                "summary": "用于演示：包含出生、教育、职业履历等二手公开信息线索。",
                "credibility_score": 65,
                "created_at": "2026-07-17T13:08:00",
            },
            {
                "id": 2,
                "project_id": 680011,
                "source_type": "structured",
                "title": "稀牛-关联企业与团队人物结构化记录",
                "url": "structured://xiniu/person/mayun",
                "summary": "用于演示：关联企业、管理团队、工商关系等结构化线索。",
                "credibility_score": 78,
                "created_at": "2026-07-17T13:12:00",
            },
            {
                "id": 3,
                "project_id": 680011,
                "source_type": "regulatory",
                "title": "交易所/监管/司法公开检索结果",
                "url": "demo://authority-search/mayun",
                "summary": "用于演示：监管、司法、上市披露方向的公开检索入口汇总。",
                "credibility_score": 82,
                "created_at": "2026-07-17T13:18:00",
            },
        ],
        "artifacts": [
            {"artifact_type": "research_plan", "title": "检索计划", "created_at": "2026-07-17T13:03:00"},
            {"artifact_type": "source_quality", "title": "来源质量评估", "created_at": "2026-07-17T13:35:00"},
            {"artifact_type": "cleaned_facts", "title": "清洗事实库", "created_at": "2026-07-17T14:10:00"},
            {"artifact_type": "risk_assessment", "title": "风险研判", "created_at": "2026-07-17T14:35:00"},
            {"artifact_type": "report", "title": "马云6.8背景调查报告_v11", "created_at": updated_at},
        ],
        "timeline": [
            {"label": "项目创建", "time": created_at},
            {"label": "检索与来源评估", "time": "2026-07-17T13:35:00"},
            {"label": "清洗事实库生成", "time": "2026-07-17T14:10:00"},
            {"label": "最近报告生成", "time": updated_at},
        ],
        "notes": [
            "这是硬编码演示数据，用于前端效果和接口联调。",
            "真实数据库接入后，应以 mock=false 的查询结果为准。",
        ],
    }


def _format_mock_trace_summary(summary: dict) -> str:
    project = summary.get("project") or {}
    libraries = summary.get("trace_libraries") or []
    artifacts = summary.get("artifacts") or []
    timeline = summary.get("timeline") or []
    sources = summary.get("sources") or []
    lines = [
        f"已找到：{project.get('title') or '马云的背景调查报告'}",
        "",
        f"- 项目ID：{project.get('id')}",
        f"- 研究对象：{project.get('target_name')}",
        f"- 报告类型：{project.get('target_type')}",
        f"- 项目创建时间：{summary.get('created_at')}",
        f"- 最近更新时间：{summary.get('updated_at')}",
        f"- 溯源来源总数：{summary.get('source_count')}",
        f"- 产物数量：{summary.get('artifact_count')}",
        "",
        "溯源库来源：",
    ]
    for item in libraries:
        examples = "、".join(str(x) for x in item.get("examples", []) if x)
        suffix = f"（{examples}）" if examples else ""
        lines.append(f"- {item.get('name')}：{item.get('source_count')} 条{suffix}")
    lines.extend(["", "相关产物："])
    for item in artifacts:
        lines.append(f"- {item.get('title')}：{item.get('artifact_type')}，{item.get('created_at')}")
    lines.extend(["", "关键时间线："])
    for item in timeline:
        lines.append(f"- {item.get('label')}：{item.get('time')}")
    lines.extend(["", "代表性来源："])
    for item in sources:
        lines.append(f"- {item.get('title')}：{item.get('summary')} [{item.get('url')}]")
    lines.extend([
        "",
        "说明：这是当前用于前端演示的静态假数据，不读取真实数据库。",
    ])
    return "\n".join(lines)


def _is_report_trace_demo_question(question: str) -> bool:
    compact = re.sub(r"\s+", "", question or "")
    return "马云" in compact and any(token in compact for token in ("背景调查报告", "背调报告", "报告", "溯源", "来源"))


def _save_workflow_trace(db: Session, project: ResearchProject, events: list[dict]) -> None:
    if not events:
        return
    industry_trace_metadata = {}
    if project.target_type == "industry":
        from industry_research import trace_snapshot
        trimmed, industry_trace_metadata = trace_snapshot(events)
    else:
        trimmed = _compact_workflow_trace(events)
    content = json.dumps(trimmed, ensure_ascii=False, indent=2)
    latest_timestamp = max((str(event.get("timestamp") or "") for event in trimmed), default="")
    # Trace snapshots are persisted from worker threads. Locking the project row
    # prevents an older background snapshot from overwriting a newer one.
    db.query(ResearchProject).filter(ResearchProject.id == project.id).with_for_update().first()
    artifacts = (
        db.query(ResearchArtifact)
        .filter(ResearchArtifact.project_id == project.id, ResearchArtifact.artifact_type == "workflow_trace")
        .order_by(ResearchArtifact.id.asc())
        .all()
    )
    artifact = max(artifacts, key=_workflow_trace_sort_key, default=None)
    existing_timestamp = str((artifact.artifact_metadata or {}).get("last_event_timestamp") or "") if artifact else ""
    if artifact and existing_timestamp and latest_timestamp and latest_timestamp < existing_timestamp:
        return
    object_key = research_store.put_text(
        f"projects/{project.id}/workflow_trace/workflow_trace.json",
        content,
        "application/json; charset=utf-8",
    )
    if artifact:
        artifact.content = content
        artifact.object_key = object_key
        artifact.artifact_metadata = {
            **industry_trace_metadata,
            "event_count": len(trimmed),
            "last_event_timestamp": latest_timestamp,
            "last_status": str(trimmed[-1].get("status") or ""),
        }
        artifact.created_by = "workflow"
        for duplicate in artifacts:
            if duplicate.id != artifact.id:
                db.delete(duplicate)
    else:
        db.add(
            ResearchArtifact(
                project_id=project.id,
                artifact_type="workflow_trace",
                title="工作流详细记录",
                version=1,
                content=content,
                object_key=object_key,
                artifact_metadata={
                    **industry_trace_metadata,
                    "event_count": len(trimmed),
                    "last_event_timestamp": latest_timestamp,
                    "last_status": str(trimmed[-1].get("status") or ""),
                },
                created_by="workflow",
            )
        )
    db.commit()


def _latest_workflow_trace(artifacts: list[ResearchArtifact]) -> list[dict]:
    trace_artifacts = [artifact for artifact in artifacts if artifact.artifact_type == "workflow_trace"]
    for artifact in sorted(trace_artifacts, key=_workflow_trace_sort_key, reverse=True):
        try:
            parsed = json.loads(artifact.content or "[]")
            if isinstance(parsed, list):
                return parsed
        except Exception:
            continue
    return []


def _workflow_trace_sort_key(artifact: ResearchArtifact) -> tuple[str, int, int]:
    metadata = artifact.artifact_metadata or {}
    latest_timestamp = str(metadata.get("last_event_timestamp") or "")
    if not latest_timestamp:
        try:
            events = json.loads(artifact.content or "[]")
            if isinstance(events, list):
                latest_timestamp = max((str(event.get("timestamp") or "") for event in events if isinstance(event, dict)), default="")
        except Exception:
            pass
    return (latest_timestamp, int(metadata.get("event_count") or 0), int(artifact.id or 0))


def _compact_workflow_trace(events: list[dict], limit: int = 400) -> list[dict]:
    """Keep an auditable stage timeline without letting repeated heartbeats hide it."""
    if len(events) <= limit:
        return list(events)
    latest_by_kind: dict[tuple[str, str, str, str], dict] = {}
    heartbeats: list[dict] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("heartbeat"):
            heartbeats.append(event)
            continue
        key = (
            str(event.get("stage") or ""),
            str(event.get("agent") or ""),
            str(event.get("label") or ""),
            str(event.get("status") or ""),
        )
        latest_by_kind[key] = event
    selected = list(latest_by_kind.values()) + heartbeats[-60:] + [event for event in events[-120:] if isinstance(event, dict)]
    deduped: dict[tuple[str, str, str, str, str], dict] = {}
    for event in selected:
        key = (
            str(event.get("timestamp") or ""),
            str(event.get("stage") or ""),
            str(event.get("agent") or ""),
            str(event.get("label") or ""),
            str(event.get("detail") or ""),
        )
        deduped[key] = event
    compacted = sorted(deduped.values(), key=lambda event: str(event.get("timestamp") or ""))
    return compacted[-limit:]


def _workflow_failure_trace_event(exc: Exception) -> dict:
    return {
        "type": "trace_step",
        "stage": "workflow",
        "agent": "workflow",
        "label": "工作流执行失败",
        "detail": str(exc),
        "timestamp": datetime.utcnow().isoformat(),
        "status": "error",
    }


def _save_project_intake(db: Session, project: ResearchProject, metadata: dict | None) -> None:
    intake = dict(metadata or {})
    if project.target_type == "industry":
        saved = _project_intake(project)
        intake = {**saved, **intake}
        raw = {**saved, **intake}
        if not raw.get("industry_scope"):
            raw["industry_scope"] = saved.get("industry_scope") or {}
        normalized = research_workflow._normalize_intake(
            project, raw, raw.get("search_queries") or [], raw.get("focus_questions") or [],
        )
        intake["industry_scope"] = normalized["industry_scope"]
        intake["as_of_date"] = normalized["as_of_date"]
        intake["region"] = normalized["region"]
        if isinstance(metadata, dict):
            metadata.update(intake)
    intake.update(
        {
            "project_name": project.title,
            "target_name": project.target_name,
            "target_type": project.target_type,
            "industry": project.industry,
            "special_requirements": intake.get("special_requirements", project.description) if project.target_type == "industry" else project.description,
        }
    )
    content = json.dumps(intake, ensure_ascii=False, indent=2)
    object_key = research_store.put_text(
        f"projects/{project.id}/project_intake/project_intake_v1.json",
        content,
        "application/json; charset=utf-8",
    )
    artifact = (
        db.query(ResearchArtifact)
        .filter(ResearchArtifact.project_id == project.id, ResearchArtifact.artifact_type == "project_intake")
        .first()
    )
    if artifact:
        artifact.content = content
        artifact.object_key = object_key
        artifact.artifact_metadata = intake
        artifact.created_by = "system"
    else:
        db.add(
            ResearchArtifact(
                project_id=project.id,
                artifact_type="project_intake",
                title="项目参数",
                version=1,
                content=content,
                object_key=object_key,
                artifact_metadata=intake,
                created_by="system",
            )
        )
    project.updated_at = datetime.utcnow()
    db.commit()


def _source_text_chunks(text: str, chunk_size: int = 1200, overlap: int = 160) -> list[str]:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return []
    chunks = []
    start = 0
    while start < len(normalized):
        chunk = normalized[start:start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        if start + chunk_size >= len(normalized):
            break
        start += max(1, chunk_size - overlap)
    return chunks


def _index_source_for_rag(project: ResearchProject, source: ResearchSource) -> dict:
    if os.getenv("VECTOR_INDEX_UPLOADS", "true").strip().lower() not in {"1", "true", "yes", "on"}:
        return {"vector_indexed": False, "vector_index_status": "disabled"}
    text = (source.content or source.summary or "").strip()
    chunks = _source_text_chunks(text)
    if not chunks:
        return {"vector_indexed": False, "vector_index_status": "empty"}
    try:
        from milvus_writer import MilvusWriter

        docs = []
        for index, chunk in enumerate(chunks):
            docs.append(
                {
                    "text": chunk[:1800],
                    "filename": source.title or f"research_source_{source.id}",
                    "file_type": source.source_type or "research_source",
                    "file_path": source.object_key or source.url or "",
                    "page_number": 0,
                    "chunk_idx": index,
                    "chunk_id": f"research:{project.id}:source:{source.id}:{index}",
                    "parent_chunk_id": f"research:{project.id}:source:{source.id}",
                    "root_chunk_id": f"research:{project.id}",
                    "chunk_level": 3,
                    "project_id": project.id,
                    "artifact_type": source.source_type or "research_source",
                    "artifact_version": 1,
                    "target_name": project.target_name or "",
                    "target_type": project.target_type or "",
                    "industry": project.industry or "",
                    "source_title": source.title or "",
                    "source_url": source.url or source.object_key or "",
                    "confidence": min(0.99, max(0.1, float(source.credibility_score or 80) / 100)),
                }
            )
        MilvusWriter().write_documents(docs)
        return {"vector_indexed": True, "vector_index_status": "completed", "vector_indexed_count": len(docs)}
    except Exception as exc:
        return {"vector_indexed": False, "vector_index_status": "failed", "vector_index_error": str(exc)}


async def _store_uploaded_research_source(
    db: Session,
    project: ResearchProject,
    file: UploadFile,
    source_type: str,
    module: str,
    credibility_score: int,
    metadata: dict | None = None,
) -> ResearchSource:
    filename = Path(file.filename or "").name
    if not filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    allowed = (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
    if not filename.lower().endswith(allowed):
        raise HTTPException(status_code=400, detail="仅支持 PDF、Word、Excel、TXT、Markdown、图片文件")

    project_dir = UPLOAD_DIR / str(project.id)
    project_dir.mkdir(parents=True, exist_ok=True)
    file_path = project_dir / filename
    payload = await file.read()
    file_path.write_bytes(payload)
    original_object_key = research_store.put_bytes(
        f"projects/{project.id}/uploads/original/{filename}",
        payload,
        mimetypes.guess_type(filename)[0] or "application/octet-stream",
    )
    is_image = filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"))
    try:
        text = _lightweight_upload_text(file_path, filename, is_image)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"文档解析失败: {exc}") from exc
    if not text.strip():
        raise HTTPException(status_code=400, detail="未能从文件中提取文本")

    object_key = research_store.put_text(f"projects/{project.id}/uploads/{filename}.txt", text)
    extraction_failed = text.startswith("[解析失败") or text.startswith("[待解析")
    source_metadata = {
        "original_filename": filename,
        "local_path": str(file_path),
        "original_object_key": original_object_key,
        "module": module,
        "extraction_status": "failed" if extraction_failed else ("ocr_done" if is_image else "text_extracted"),
        **(metadata or {}),
    }
    if is_image:
        mime_type = mimetypes.guess_type(filename)[0] or "image/png"
        source_metadata.update(
            {
                "images": [{"url": f"local://{file_path}", "mime_type": mime_type}],
                "quality": {
                    "score": credibility_score,
                    "source_type": source_type,
                    "authority_score": credibility_score,
                    "relevance_score": 80,
                    "depth_score": 60,
                    "provider_score": credibility_score,
                    "needs_ocr": extraction_failed,
                    "host": "local_upload",
                },
            }
        )

    source = ResearchSource(
        project_id=project.id,
        source_type=source_type,
        title=filename,
        object_key=object_key,
        content=text,
        summary=text[:500],
        source_metadata=source_metadata,
        credibility_score=max(0, min(100, credibility_score)),
    )
    project.updated_at = datetime.utcnow()
    db.add(source)
    db.commit()
    db.refresh(source)
    identity_updates = _merge_upload_identity_into_intake(db, project, "" if extraction_failed else text)
    if identity_updates:
        source_metadata["intake_identity_updates"] = identity_updates
    index_result = _index_source_for_rag(project, source)
    source_metadata.update(index_result)
    source.source_metadata = source_metadata
    db.commit()
    db.refresh(source)
    return source


def _project_intake(project: ResearchProject) -> dict:
    for artifact in project.artifacts or []:
        if artifact.artifact_type == "project_intake":
            if artifact.artifact_metadata:
                return artifact.artifact_metadata
            try:
                return json.loads(artifact.content or "{}")
            except Exception:
                return {}
    return {
        "project_name": project.title,
        "target_name": project.target_name,
        "target_type": project.target_type,
        "industry": project.industry,
        "special_requirements": project.description,
    }


def _repository_source_item(source: ResearchSource, project_title: str) -> dict:
    metadata = source.source_metadata or {}
    text = _read_store_text(source.object_key, source.content or source.summary)
    normalized_text = re.sub(r"\s+", " ", text or "").strip()
    summary_text = re.sub(r"\s+", " ", source.summary or "").strip()
    content_kind = metadata.get("content_kind", "")
    if not content_kind and summary_text and normalized_text == summary_text:
        content_kind = "summary_only"
    if not content_kind and not normalized_text:
        content_kind = "empty_content"
    return {
        "kind": "source",
        "id": source.id,
        "project_id": source.project_id,
        "project_title": project_title,
        "title": source.title,
        "source_type": source.source_type,
        "url": source.url,
        "has_download": bool(metadata.get("original_object_key") or source.object_key),
        "download_url": f"/research/sources/{source.id}/download",
        "snippet": (source.summary or normalized_text or "")[:500],
        "content_chars": len(normalized_text),
        "extraction_status": metadata.get("extraction_status", ""),
        "content_kind": content_kind,
        "fetch_status": metadata.get("fetch_status", ""),
        "credibility_score": source.credibility_score,
        "created_at": source.created_at.isoformat(),
    }


def _repository_artifact_item(artifact: ResearchArtifact, project_title: str) -> dict:
    metadata = artifact.artifact_metadata or {}
    source_key = metadata.get("markdown_object_key") if artifact.artifact_type == "cleaned_facts" else artifact.object_key
    return {
        "kind": "artifact",
        "id": artifact.id,
        "project_id": artifact.project_id,
        "project_title": project_title,
        "artifact_type": artifact.artifact_type,
        "title": artifact.title,
        "version": artifact.version,
        "source_type": artifact.artifact_type,
        "url": source_key,
        "snippet": (artifact.content or "")[:500],
        "download_url": f"/research/artifacts/{artifact.id}/download",
        "created_at": artifact.created_at.isoformat(),
    }


def _get_project(db: Session, project_id: int, current_user: User) -> ResearchProject:
    project = db.query(ResearchProject).filter(ResearchProject.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="研究项目不存在")
    if current_user.role != "admin" and project.created_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问该研究项目")
    return project


def _extract_upload_text(file_path: Path, filename: str) -> str:
    file_lower = filename.lower()
    if file_lower.endswith(".txt") or file_lower.endswith(".md"):
        return file_path.read_text(encoding="utf-8", errors="ignore")
    if file_lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
        return f"Uploaded image file for visual research extraction: {filename}"
    docs = loader.load_document(str(file_path), filename)
    leaf_texts = [doc.get("text", "") for doc in docs if int(doc.get("chunk_level", 0) or 0) == 3]
    if not leaf_texts:
        leaf_texts = [doc.get("text", "") for doc in docs]
    return "\n\n".join(text for text in leaf_texts if text)


def _lightweight_upload_text(file_path: Path, filename: str, is_image: bool) -> str:
    try:
        text = _ocr_local_image_with_fallback(file_path) if is_image else _extract_upload_text(file_path, filename)
        return text.strip() or f"[待解析原始资料] {filename}"
    except Exception as exc:
        return f"[解析失败，原始文件已保留] {filename}\n{type(exc).__name__}: {exc}"


def _ocr_local_image_with_fallback(file_path: Path) -> str:
    providers = [item.strip().lower() for item in os.getenv("OCR_PROVIDER_ORDER", "tencent,baidu").split(",") if item.strip()]
    errors: list[str] = []
    for provider in providers:
        try:
            text = _tencent_ocr_local_image(file_path) if provider == "tencent" else _baidu_ocr_local_image(file_path) if provider == "baidu" else ""
            if text.strip():
                return text
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
    raise RuntimeError("; ".join(errors) or "未配置可用 OCR 提供商")


def _tencent_ocr_local_image(file_path: Path) -> str:
    secret_id = os.getenv("OCR_API_KEY", "").strip()
    secret_key = os.getenv("OCR_SECRET_KEY", "").strip()
    if not secret_id or not secret_key:
        return ""
    from tencentcloud.common import credential
    from tencentcloud.ocr.v20181119 import ocr_client, models

    cred = credential.Credential(secret_id, secret_key)
    client = ocr_client.OcrClient(cred, os.getenv("TENCENT_OCR_REGION", "ap-guangzhou").strip() or "ap-guangzhou")
    request = models.GeneralBasicOCRRequest()
    request.ImageBase64 = base64.b64encode(file_path.read_bytes()).decode("ascii")
    response = client.GeneralBasicOCR(request)
    return "\n".join(str(item.DetectedText or "").strip() for item in (response.TextDetections or []) if item.DetectedText)


def _baidu_ocr_local_image(file_path: Path) -> str:
    """OCR only for intake identity anchoring; deep document analysis stays downstream."""
    api_key = os.getenv("BAIDU_OCR_API_KEY", "").strip()
    secret_key = os.getenv("BAIDU_OCR_SECRET_KEY", "").strip()
    if not api_key or not secret_key:
        return ""
    token_response = requests.post(
        "https://aip.baidubce.com/oauth/2.0/token",
        data={"grant_type": "client_credentials", "client_id": api_key, "client_secret": secret_key},
        timeout=15,
    )
    token_response.raise_for_status()
    token = token_response.json().get("access_token", "")
    if not token:
        return ""
    image = base64.b64encode(file_path.read_bytes()).decode("ascii")
    endpoints = [item.strip() for item in os.getenv("BAIDU_OCR_ENDPOINTS", "general_basic,accurate_basic").split(",") if item.strip()]
    errors: list[str] = []
    for endpoint in endpoints:
        response = requests.post(
            f"https://aip.baidubce.com/rest/2.0/ocr/v1/{endpoint}",
            params={"access_token": token},
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            data={"image": image, "detect_direction": "true", "paragraph": "false"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error_code"):
            errors.append(f"{endpoint}: {payload.get('error_msg') or payload['error_code']}")
            continue
        text = "\n".join(str(item.get("words") or "").strip() for item in payload.get("words_result", []) if item.get("words"))
        if text.strip():
            return text
    raise RuntimeError("; ".join(errors) or "Baidu OCR 未返回文字")


def _identity_skeleton(text: str, target_type: str) -> dict[str, str]:
    sample = (text or "")[:30000]
    result: dict[str, str] = {}
    company_matches = re.findall(r"[\u4e00-\u9fffA-Za-z0-9（）()·]{2,50}(?:股份有限公司|有限责任公司|有限公司|集团)", sample)
    if company_matches:
        result["company_name"] = min(company_matches, key=len).strip("：:，,。 ")
    credit = re.search(r"(?<![0-9A-Z])[0-9A-Z]{18}(?![0-9A-Z])", sample)
    if credit:
        result["official_identifier"] = credit.group(0)
    industry = re.search(r"(?:所属行业|行业|赛道|主营领域)\s*[：:]\s*([^\n；;，,]{2,40})", sample)
    if industry:
        result["industry"] = industry.group(1).strip()
    if target_type == "person":
        name = re.search(r"(?:姓名|创始人|实际控制人|法定代表人)\s*[：:]\s*([\u4e00-\u9fff·]{2,12})", sample)
        role = re.search(r"(?:职位|职务|现任)\s*[：:]\s*([^\n；;]{2,40})", sample)
        bilingual_name = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s+([\u4e00-\u9fff]{2,4})\b", sample)
        executive_role = re.search(r"\b((?:Founding\s+)?(?:CEO|CFO|COO|CTO|President|Managing Director|Partner))\b", sample, flags=re.I)
        employer = re.search(r"(?im)^([^\n]{2,100}(?:BMW|ArcherMind|Technology|Technologies|Software|Capital|Group|Holdings)[^\n]*)$", sample)
        if name:
            result["target_name"] = name.group(1).strip()
        elif bilingual_name:
            result["target_name"] = f"{bilingual_name.group(1)} {bilingual_name.group(2)}"
        company_context = result.get("company_name", "") or (employer.group(1).strip() if employer else "")
        role_context = role.group(1).strip() if role else executive_role.group(1).strip() if executive_role else ""
        context = " / ".join(x for x in [company_context, role_context] if x)
        if context:
            result["affiliation"] = context
        anchors = []
        for label, pattern in [
            ("University of Oxford", r"University of Oxford"),
            ("CFA", r"CFA(?: Institute| Charter Holder)?"),
            ("University of Hong Kong", r"University of Hong Kong"),
            ("Chinese University of Hong Kong", r"Chinese University of Hong Kong"),
            ("PMP", r"Project Management Professional|\bPMP\b"),
        ]:
            if re.search(pattern, sample, flags=re.I):
                anchors.append(label)
        if anchors:
            for value in [company_context, role_context]:
                if value and value not in anchors:
                    anchors.append(value)
            result["identity_anchors"] = " / ".join(anchors)
        if not result.get("industry"):
            if re.search(r"digital car software|automotive software|BMW|汽车软件", sample, flags=re.I):
                result["industry"] = "汽车软件与数字化研发"
            elif re.search(r"high-tech industry|高科技", sample, flags=re.I):
                result["industry"] = "高科技"
    return result


def _merge_upload_identity_into_intake(db: Session, project: ResearchProject, text: str) -> dict[str, str]:
    skeleton = _identity_skeleton(text, project.target_type)
    if not skeleton:
        return {}
    current = _project_intake(project)
    changed: dict[str, str] = {}
    for key, value in skeleton.items():
        if value and not str(current.get(key) or "").strip():
            current[key] = value
            changed[key] = value
    if not changed:
        return {}
    if changed.get("target_name") and not project.target_name:
        project.target_name = changed["target_name"]
    if changed.get("company_name") and project.target_type == "company" and not project.target_name:
        project.target_name = changed["company_name"]
    if changed.get("industry") and not project.industry:
        project.industry = changed["industry"]
    _save_project_intake(db, project, current)
    return changed


def _refresh_failed_upload_ocr(db: Session, project: ResearchProject) -> dict[str, str]:
    """Retry failed uploaded images before resume so new identity anchors affect search."""
    merged: dict[str, str] = {}
    for source in project.sources or []:
        meta = dict(source.source_metadata or {})
        if str(meta.get("extraction_status") or "").lower() != "failed":
            continue
        local_path = Path(str(meta.get("local_path") or ""))
        if not local_path.exists() or local_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
            continue
        try:
            text = _ocr_local_image_with_fallback(local_path).strip()
        except Exception as exc:
            meta["ocr_retry_error"] = str(exc)[:500]
            source.source_metadata = meta
            continue
        if not text:
            continue
        source.content = text
        source.summary = text[:500]
        source.object_key = research_store.put_text(f"projects/{project.id}/uploads/{source.title}.txt", text)
        meta["extraction_status"] = "ocr_done"
        meta["ocr_retry_error"] = ""
        quality = dict(meta.get("quality") or {})
        quality["needs_ocr"] = False
        meta["quality"] = quality
        source.source_metadata = meta
        merged.update(_identity_skeleton(text, project.target_type))
    db.commit()
    return merged


@router.get("/reports/trace-summary")
async def get_report_trace_summary(
    query: str = Query(..., min_length=1),
):
    return _mock_mayun_trace_summary(query)


@router.post("/projects", response_model=ResearchProjectResponse)
async def create_project(
    request: ResearchProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="项目标题不能为空")
    project = ResearchProject(
        title=title,
        target_name=request.target_name.strip(),
        target_type=_normalize_target_type(request.target_type),
        industry=request.industry.strip(),
        description=request.description.strip(),
        created_by_id=current_user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    _save_project_intake(db, project, request.metadata)
    db.refresh(project)
    return _project_response(project)


@router.get("/projects", response_model=ResearchProjectListResponse)
async def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(ResearchProject)
    if current_user.role != "admin":
        query = query.filter(ResearchProject.created_by_id == current_user.id)
    projects = query.order_by(ResearchProject.updated_at.desc()).all()
    return ResearchProjectListResponse(projects=[_project_response(item) for item in projects])


@router.get("/projects/{project_id}", response_model=ResearchProjectResponse)
async def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _project_response(_get_project(db, project_id, current_user))


@router.get("/projects/{project_id}/detail")
async def get_project_detail(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _get_project(db, project_id, current_user)
    sources = (
        db.query(ResearchSource)
        .filter(ResearchSource.project_id == project.id)
        .order_by(ResearchSource.created_at.desc())
        .all()
    )
    artifacts = (
        db.query(ResearchArtifact)
        .filter(ResearchArtifact.project_id == project.id)
        .order_by(ResearchArtifact.created_at.desc())
        .all()
    )
    return {
        "project": _project_response(project).model_dump(),
        "intake": _project_intake(project),
        "source_count": len(sources),
        "artifact_count": len(artifacts),
        "artifacts": [_artifact_response(item, include_content=False).model_dump() for item in artifacts],
        "sources": [_source_response(item).model_dump() for item in sources],
        "trace": _latest_workflow_trace(artifacts),
    }


@router.get("/projects/{project_id}/run-intake")
async def get_project_run_intake(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return only the persisted inputs needed to start a re-run.

    This deliberately avoids loading sources, artifacts, and workflow traces.
    """
    project = _get_project(db, project_id, current_user)
    return {"intake": _project_intake(project)}


@router.get("/projects/{project_id}/progress")
async def get_project_progress(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return only the state needed by the live task-progress display."""
    project = _get_project(db, project_id, current_user)
    trace_artifacts = (
        db.query(ResearchArtifact)
        .filter(
            ResearchArtifact.project_id == project.id,
            ResearchArtifact.artifact_type == "workflow_trace",
        )
        .order_by(ResearchArtifact.created_at.desc())
        .all()
    )
    return {
        "project": _project_response(project).model_dump(),
        "trace": _latest_workflow_trace(trace_artifacts),
    }


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _get_project(db, project_id, current_user)
    if _is_project_running(project_id):
        raise HTTPException(status_code=409, detail="任务正在运行，请等待完成后再删除")
    sources = db.query(ResearchSource).filter(ResearchSource.project_id == project.id).all()
    artifacts = db.query(ResearchArtifact).filter(ResearchArtifact.project_id == project.id).all()
    for source in sources:
        metadata = source.source_metadata or {}
        _delete_local_upload(metadata.get("local_path"))
        for key in {source.object_key, metadata.get("original_object_key")}:
            try:
                research_store.delete_object(key)
            except Exception:
                pass
    for artifact in artifacts:
        metadata = artifact.artifact_metadata or {}
        for key in {
            artifact.object_key,
            metadata.get("docx_object_key"),
            metadata.get("markdown_object_key"),
            metadata.get("raw_markdown_object_key"),
        }:
            try:
                research_store.delete_object(key)
            except Exception:
                pass
    try:
        research_store.delete_prefix(f"projects/{project.id}")
    except Exception:
        pass
    upload_dir = (UPLOAD_DIR / str(project.id)).resolve()
    if UPLOAD_DIR.resolve() in upload_dir.parents and upload_dir.is_dir():
        shutil.rmtree(upload_dir, ignore_errors=True)
    db.delete(project)
    db.commit()
    return {"message": "research project deleted", "project_id": project_id}


@router.post("/projects/{project_id}/sources", response_model=ResearchSourceResponse)
async def add_manual_source(
    project_id: int,
    request: ResearchSourceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _get_project(db, project_id, current_user)
    content = request.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="来源内容不能为空")
    object_key = research_store.put_text(f"projects/{project.id}/manual/{datetime.utcnow().timestamp()}.txt", content)
    source = ResearchSource(
        project_id=project.id,
        source_type=request.source_type.strip() or "manual",
        title=request.title.strip() or "人工补充资料",
        url=request.url.strip(),
        object_key=object_key,
        content=content,
        summary=request.summary.strip(),
        source_metadata=request.metadata,
        credibility_score=max(0, min(100, request.credibility_score)),
    )
    project.updated_at = datetime.utcnow()
    db.add(source)
    db.commit()
    db.refresh(source)
    return _source_response(source)


@router.get("/projects/{project_id}/sources", response_model=list[ResearchSourceResponse])
async def list_sources(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _get_project(db, project_id, current_user)
    sources = (
        db.query(ResearchSource)
        .filter(ResearchSource.project_id == project.id)
        .order_by(ResearchSource.created_at.desc())
        .all()
    )
    return [_source_response(item) for item in sources]


@router.get("/sources/{source_id}/download")
async def download_source(
    source_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    source = db.query(ResearchSource).filter(ResearchSource.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="资料来源不存在")
    _get_project(db, source.project_id, current_user)
    metadata = source.source_metadata or {}
    object_key = metadata.get("original_object_key") or source.object_key
    if not object_key:
        raise HTTPException(status_code=404, detail="来源文件不存在")
    payload = research_store.get_bytes(object_key)
    if not payload.strip():
        fallback_text = "\n".join(
            part
            for part in [
                f"标题：{source.title}",
                f"URL：{source.url}",
                f"摘要：{source.summary}",
                source.content,
            ]
            if (part or "").strip()
        ).strip()
        payload = fallback_text.encode("utf-8")
    filename = metadata.get("original_filename") or Path(object_key).name or f"source_{source.id}.txt"
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return Response(
        content=payload,
        media_type=media_type,
        headers=_download_headers(filename),
    )


@router.delete("/sources/{source_id}")
async def delete_source(
    source_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    source = db.query(ResearchSource).filter(ResearchSource.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="资料来源不存在")
    _get_project(db, source.project_id, current_user)
    research_store.delete_object(source.object_key)
    metadata = source.source_metadata or {}
    research_store.delete_object(metadata.get("original_object_key"))
    _delete_local_upload(metadata.get("local_path"))
    db.delete(source)
    db.commit()
    return {"message": "research source deleted", "source_id": source_id}


@router.post("/projects/{project_id}/upload", response_model=ResearchUploadResponse)
async def upload_project_source(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _get_project(db, project_id, current_user)
    source = await _store_uploaded_research_source(
        db,
        project,
        file,
        source_type="upload",
        module="uploaded_material",
        credibility_score=80,
        metadata={"stage": "initial_upload"},
    )
    return ResearchUploadResponse(source=_source_response(source), message="上传资料已加入研究项目")


@router.post("/projects/{project_id}/field-sources", response_model=ResearchUploadResponse)
async def upload_field_source(
    project_id: int,
    file: UploadFile = File(...),
    module: str = Form("一手访谈/走访"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _get_project(db, project_id, current_user)
    source = await _store_uploaded_research_source(
        db,
        project,
        file,
        source_type="first_hand",
        module=module.strip() or "一手访谈/走访",
        credibility_score=95,
        metadata={"stage": "second_stage", "evidence_tier": "first_hand"},
    )
    return ResearchUploadResponse(source=_source_response(source), message="一手资料已入库并尝试写入向量库")


@router.post("/projects/{project_id}/artifacts/replace", response_model=ResearchArtifactResponse)
async def replace_project_artifact(
    project_id: int,
    artifact_type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _get_project(db, project_id, current_user)
    artifact_type = artifact_type.strip()
    if artifact_type not in {"desktop_report", "proposal"}:
        raise HTTPException(status_code=400, detail="仅支持覆盖桌面研究报告或建议书")
    source = await _store_uploaded_research_source(
        db,
        project,
        file,
        source_type="human_review_report" if artifact_type == "desktop_report" else "human_review_proposal",
        module="人工复核产物",
        credibility_score=98,
        metadata={"stage": "human_review", "artifact_type": artifact_type, "evidence_tier": "reviewed_secondary"},
    )
    title_suffix = "桌面研究报告" if artifact_type == "desktop_report" else "项目建议书"
    artifact = research_workflow.save_artifact(
        db,
        project,
        artifact_type,
        _project_doc_title(project, title_suffix),
        source.content,
        {
            "stage": "human_review",
            "source_id": source.id,
            "original_filename": (source.source_metadata or {}).get("original_filename", ""),
            "review_original_object_key": (source.source_metadata or {}).get("original_object_key", ""),
            "replacement_for": artifact_type,
        },
        created_by="human_review",
    )
    return _artifact_response(artifact)


@router.post("/projects/{project_id}/run", response_model=ResearchRunResponse)
async def run_research_project(
    project_id: int,
    request: ResearchRunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _get_project(db, project_id, current_user)
    if not _mark_project_running(project_id):
        raise HTTPException(status_code=409, detail="该项目已有工作流正在后台运行，请稍后查看进度")
    try:
        intake = _locked_run_intake(request, target_type=project.target_type)
        recovered_identity = _refresh_failed_upload_ocr(db, project)
        for key, value in recovered_identity.items():
            if value and not str(intake.get(key) or "").strip():
                intake[key] = value
        if recovered_identity:
            intake["force_refresh_from_upload_ocr"] = True
        _save_project_intake(db, project, intake)
        artifacts, sources_added = research_workflow.run_project(
            db,
            project,
            request.search_queries,
            request.focus_questions,
            FIXED_MAX_RESULTS_PER_QUERY,
            FIXED_GENERATE_PROPOSAL,
            intake=intake,
            pause_requested=lambda: _is_pause_requested(project_id),
        )
    except WorkflowPaused:
        project.status = "paused"
        project.updated_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=409, detail="任务已暂停，可稍后点击继续")
    except Exception as exc:
        project.status = "failed"
        project.updated_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=500, detail=f"研究工作流执行失败: {exc}") from exc
    finally:
        _unmark_project_running(project_id)
    return ResearchRunResponse(
        project=_project_response(project),
        artifacts=[_artifact_response(item) for item in artifacts],
        sources_added=sources_added,
    )


@router.post("/projects/{project_id}/run/stream")
async def run_research_project_stream(
    project_id: int,
    request: ResearchRunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_project(db, project_id, current_user)
    user_id = current_user.id
    is_admin = current_user.role == "admin"

    async def event_generator():
        if not _mark_project_running(project_id):
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue = asyncio.Queue()
            _subscribe_running_project(project_id, loop, queue)
            try:
                attached = {
                    "type": "trace_step",
                    "stage": "workflow",
                    "agent": "workflow",
                    "label": "已接入后台运行中的工作流",
                    "detail": "页面刷新后继续接收实时进度，后端不会重复启动任务",
                    "status": "running",
                    "timestamp": datetime.utcnow().isoformat(),
                }
                yield f"data: {json.dumps(attached, ensure_ascii=False)}\n\n"
                for event in _running_event_snapshot(project_id):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event.get("type") == "done":
                        return
                while _is_project_running(project_id):
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15)
                    except asyncio.TimeoutError:
                        heartbeat = {
                            "type": "trace_step",
                            "stage": "workflow",
                            "agent": "workflow",
                            "label": "后台工作流仍在运行",
                            "detail": "正在等待下一条后端进度事件",
                            "status": "running",
                            "timestamp": datetime.utcnow().isoformat(),
                        }
                        yield f"data: {json.dumps(heartbeat, ensure_ascii=False)}\n\n"
                        continue
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event.get("type") == "done":
                        return
                yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
            finally:
                _unsubscribe_running_project(project_id, queue)
            return
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        trace_events: list[dict] = []
        last_trace_persist_at = 0.0

        def persist_trace_snapshot(snapshot: list[dict]) -> None:
            worker_db = SessionLocal()
            try:
                project = worker_db.query(ResearchProject).filter(ResearchProject.id == project_id).first()
                if project:
                    _save_workflow_trace(worker_db, project, snapshot)
            finally:
                worker_db.close()

        def emit(event: dict):
            nonlocal last_trace_persist_at
            if event.get("type") == "trace_step":
                trace_events.append(event)
                now = time.monotonic()
                should_persist = (
                    bool(event.get("heartbeat"))
                    or len(trace_events) % 20 == 0
                    or now - last_trace_persist_at >= 15
                    or event.get("status") in {"done", "error", "fallback", "failed"}
                )
                if should_persist:
                    last_trace_persist_at = now
                    snapshot = list(trace_events)
                    try:
                        asyncio.run_coroutine_threadsafe(asyncio.to_thread(persist_trace_snapshot, snapshot), loop)
                    except RuntimeError:
                        try:
                            persist_trace_snapshot(snapshot)
                        except Exception:
                            pass
            _publish_running_event(project_id, event)
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError:
                pass

        def worker():
            worker_db = SessionLocal()
            try:
                project = worker_db.query(ResearchProject).filter(ResearchProject.id == project_id).first()
                if not project:
                    emit({"type": "error", "content": "研究项目不存在"})
                    return
                if not is_admin and project.created_by_id != user_id:
                    emit({"type": "error", "content": "无权访问该研究项目"})
                    return
                intake = _locked_run_intake(request, target_type=project.target_type)
                recovered_identity = _refresh_failed_upload_ocr(worker_db, project)
                for key, value in recovered_identity.items():
                    if value and not str(intake.get(key) or "").strip():
                        intake[key] = value
                if recovered_identity:
                    intake["force_refresh_from_upload_ocr"] = True
                _save_project_intake(worker_db, project, intake)
                artifacts, sources_added = research_workflow.run_project(
                    worker_db,
                    project,
                    request.search_queries,
                    request.focus_questions,
                    FIXED_MAX_RESULTS_PER_QUERY,
                    FIXED_GENERATE_PROPOSAL,
                    emit=emit,
                    intake=intake,
                    pause_requested=lambda: _is_pause_requested(project_id),
                )
                _save_workflow_trace(worker_db, project, trace_events)
                emit(
                    {
                        "type": "result",
                        "project": _project_response(project).model_dump(),
                        "artifacts": [_artifact_response(item, include_content=False).model_dump() for item in artifacts],
                        "sources_added": sources_added,
                    }
                )
            except WorkflowPaused:
                try:
                    project = worker_db.query(ResearchProject).filter(ResearchProject.id == project_id).first()
                    if project:
                        _save_workflow_trace(worker_db, project, trace_events)
                        project.status = "paused"
                        project.updated_at = datetime.utcnow()
                        worker_db.commit()
                    emit({"type": "paused", "content": "任务已暂停，可点击继续恢复"})
                except Exception:
                    pass
            except Exception as exc:
                try:
                    project = worker_db.query(ResearchProject).filter(ResearchProject.id == project_id).first()
                    if project:
                        trace_events.append(_workflow_failure_trace_event(exc))
                        _save_workflow_trace(worker_db, project, trace_events)
                        project.status = "failed"
                        project.updated_at = datetime.utcnow()
                        worker_db.commit()
                except Exception:
                    pass
                emit({"type": "error", "content": str(exc)})
            finally:
                worker_db.close()
                _unmark_project_running(project_id)
                emit({"type": "done"})

        task = asyncio.create_task(asyncio.to_thread(worker))
        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "trace_step" and len(trace_events) % 20 == 0:
                    asyncio.create_task(asyncio.to_thread(persist_trace_snapshot, list(trace_events)))
                if event.get("type") == "done":
                    break
        finally:
            # Keep the worker alive if the browser closes or refreshes.
            # The workflow persists its final trace/result from the worker thread.
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/projects/{project_id}/second-stage/run/stream")
async def run_second_stage_stream(
    project_id: int,
    request: ResearchRunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_project(db, project_id, current_user)
    user_id = current_user.id
    is_admin = current_user.role == "admin"

    async def event_generator():
        if not _mark_project_running(project_id):
            yield f"data: {json.dumps({'type': 'trace_step', 'stage': 'workflow', 'agent': 'workflow', 'label': '工作流已在后台运行', 'detail': '无需重复启动，刷新项目详情查看进度', 'status': 'skipped', 'timestamp': datetime.utcnow().isoformat()}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
            return
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        trace_events: list[dict] = []

        def emit(event: dict):
            if event.get("type") == "trace_step":
                trace_events.append(event)
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError:
                pass

        def worker():
            worker_db = SessionLocal()
            try:
                project = worker_db.query(ResearchProject).filter(ResearchProject.id == project_id).first()
                if not project:
                    emit({"type": "error", "content": "研究项目不存在"})
                    return
                if not is_admin and project.created_by_id != user_id:
                    emit({"type": "error", "content": "无权访问该研究项目"})
                    return
                intake = request.model_dump(exclude_unset=project.target_type == "industry")
                intake.update(
                    {
                        "ai_search_enabled": False,
                        "generate_proposal": True,
                        "stage": "second_stage",
                        "special_requirements": request.special_requirements
                        or "基于人工复核产物、专家访谈、走访记录和一手资料重新生成桌面研究报告与建议书。",
                    }
                )
                _save_project_intake(worker_db, project, intake)
                emit(
                    {
                        "type": "trace_step",
                        "stage": "second_stage",
                        "agent": "human_evidence_agent",
                        "label": "二阶段再生成启动",
                        "detail": "已关闭在线搜索，将优先利用人工复核产物和一手资料",
                        "status": "running",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                artifacts, sources_added = research_workflow.run_project(
                    worker_db,
                    project,
                    request.search_queries,
                    request.focus_questions,
                    FIXED_MAX_RESULTS_PER_QUERY,
                    True,
                    emit=emit,
                    intake=intake,
                )
                _save_workflow_trace(worker_db, project, trace_events)
                emit(
                    {
                        "type": "result",
                        "project": _project_response(project).model_dump(),
                        "artifacts": [_artifact_response(item).model_dump() for item in artifacts],
                        "sources_added": sources_added,
                    }
                )
            except Exception as exc:
                try:
                    project = worker_db.query(ResearchProject).filter(ResearchProject.id == project_id).first()
                    if project:
                        trace_events.append(_workflow_failure_trace_event(exc))
                        _save_workflow_trace(worker_db, project, trace_events)
                        project.status = "failed"
                        project.updated_at = datetime.utcnow()
                        worker_db.commit()
                except Exception:
                    pass
                emit({"type": "error", "content": str(exc)})
            finally:
                worker_db.close()
                _unmark_project_running(project_id)
                emit({"type": "done"})

        task = asyncio.create_task(asyncio.to_thread(worker))
        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "done":
                    break
        finally:
            # Keep the worker alive if the browser closes or refreshes.
            # The workflow persists its final trace/result from the worker thread.
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/projects/{project_id}/artifacts", response_model=list[ResearchArtifactResponse])
async def list_artifacts(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _get_project(db, project_id, current_user)
    artifacts = (
        db.query(ResearchArtifact)
        .filter(ResearchArtifact.project_id == project.id)
        .order_by(ResearchArtifact.created_at.desc())
        .all()
    )
    return [_artifact_response(item) for item in artifacts]


@router.delete("/artifacts/{artifact_id}")
async def delete_artifact(
    artifact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    artifact = db.query(ResearchArtifact).filter(ResearchArtifact.id == artifact_id).first()
    if not artifact:
        raise HTTPException(status_code=404, detail="产物不存在")
    _get_project(db, artifact.project_id, current_user)
    metadata = artifact.artifact_metadata or {}
    for key in {
        artifact.object_key,
        metadata.get("docx_object_key"),
        metadata.get("markdown_object_key"),
        metadata.get("raw_markdown_object_key"),
        metadata.get("review_original_object_key"),
    }:
        try:
            research_store.delete_object(key)
        except Exception:
            pass
    db.delete(artifact)
    db.commit()
    return {"message": "research artifact deleted", "artifact_id": artifact_id}


@router.post("/vector/reindex")
async def reindex_cleaned_facts(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project_query = db.query(ResearchProject)
    if project_id:
        project_query = project_query.filter(ResearchProject.id == project_id)
    if current_user.role != "admin":
        project_query = project_query.filter(ResearchProject.created_by_id == current_user.id)
    projects = project_query.all()
    if not projects:
        return {"projects": 0, "artifacts": 0, "indexed": 0, "errors": []}

    indexed = 0
    artifact_count = 0
    errors = []
    for project in projects:
        artifacts = (
            db.query(ResearchArtifact)
            .filter(ResearchArtifact.project_id == project.id, ResearchArtifact.artifact_type == "cleaned_facts")
            .order_by(ResearchArtifact.version.asc())
            .all()
        )
        for artifact in artifacts:
            artifact_count += 1
            metadata = dict(artifact.artifact_metadata or {})
            markdown_key = metadata.get("markdown_object_key") or artifact.object_key
            try:
                count = research_workflow._index_cleaned_facts(project, artifact.content, artifact.version, markdown_key)
                metadata["vector_indexed"] = True
                metadata["vector_index_status"] = "completed"
                metadata["vector_indexed_count"] = count
                metadata.pop("vector_index_error", None)
                artifact.artifact_metadata = metadata
                indexed += count
            except Exception as exc:
                metadata["vector_indexed"] = False
                metadata["vector_index_status"] = "failed"
                metadata["vector_index_error"] = str(exc)
                artifact.artifact_metadata = metadata
                errors.append({"project_id": project.id, "artifact_id": artifact.id, "error": str(exc)})
    db.commit()
    return {"projects": len(projects), "artifacts": artifact_count, "indexed": indexed, "errors": errors}



@router.post("/assistant/stream")
async def research_assistant_stream(
    request: ResearchAssistantRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    question = request.message.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")
    if _is_assistant_greeting(question):
        content = "你好，我在。你可以问我：你做过哪些项目、某个项目用了哪些来源、某份报告里的证据和结论是否闭环。"

        async def greeting_event_generator():
            yield f"data: {json.dumps({'type': 'content', 'content': content}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            greeting_event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    if _is_project_list_question(question):
        content = _format_user_project_list(db, current_user)

        async def project_list_event_generator():
            yield f"data: {json.dumps({'type': 'content', 'content': content}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            project_list_event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    if _is_report_trace_demo_question(question):
        summary = _mock_mayun_trace_summary(question)
        content = _format_mock_trace_summary(summary)

        async def demo_event_generator():
            yield f"data: {json.dumps({'type': 'content', 'content': content}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'sources', 'sources': summary.get('sources', [])}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            demo_event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    history_summary = _clip_text(request.history_summary or "", 8000)
    recent_messages = request.recent_messages[-20:] if request.recent_messages else []
    recent_context = "\n".join(
        f"{(item.get('role') or '').strip()}: {_clip_text(item.get('content') or '', 500)}"
        for item in recent_messages
        if isinstance(item, dict) and (item.get("content") or "").strip()
    )
    limit = max(1, min(20, int(request.limit or 8)))

    async def event_generator():
        yield f"data: {json.dumps({'type': 'status', 'content': '正在检索项目资料并生成回答...'}, ensure_ascii=False)}\n\n"
        project_ids = _assistant_project_ids(db, current_user, request.project_id)
        general_overview = _general_research_overview(question)
        vector_rows = _vector_context(project_ids, question, max(3, limit // 2)) if project_ids else []
        store_rows = _project_store_context(db, project_ids, question, limit) if project_ids else []
        # Hybrid retrieval can still return unrelated records for a new topic.  For
        # the built-in research overviews, only prefer project evidence when the
        # store has an actual keyword hit; otherwise don't disguise old reports as
        # support for the new subject.
        use_general_overview = bool(general_overview) and not any(
            item.get("score", 0) > 0 for item in store_rows
        )
        seen = set()
        contexts = []
        for item in vector_rows + store_rows:
            key = (item.get("kind"), item.get("project_id"), item.get("title"), item.get("source"), item.get("text", "")[:120])
            if key in seen:
                continue
            seen.add(key)
            contexts.append(item)
            if len(contexts) >= limit:
                break
        context_text = _format_assistant_context(contexts)
        if use_general_overview or not context_text.strip():
            if use_general_overview:
                yield f"data: {json.dumps({'type': 'content', 'content': general_overview}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'sources', 'sources': [{'kind': 'general_research_overview', 'title': '内置通用研究概览', 'source': '非项目资料库'}]}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return
            content = "当前可访问项目的 MinIO/对象存储资料中没有找到足够上下文，无法基于资料回答。"
            yield f"data: {json.dumps({'type': 'content', 'content': content}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return

        prompt = f"""
你是研究项目溯源库 AI 助手。必须严格根据下方项目资料回答问题。
规则：
1. 只能使用给定资料，不得使用外部常识补充事实。
2. 如果资料不足，明确说“资料中未找到”。
3. 回答中尽量标注引用编号，例如 [1]、[2]。
4. 区分已证实事实、待核验信息和推断。

用户问题：{question}

历史压缩摘要：
{history_summary or "无"}

最近对话：
{recent_context or "无"}

项目资料：
{context_text}
"""
        try:
            answer = await asyncio.wait_for(
                asyncio.to_thread(research_workflow._invoke, "研究溯源库 AI 助手", prompt),
                timeout=max(10, min(180, int(os.getenv("ASSISTANT_LLM_TIMEOUT_SECONDS", "90")))),
            )
        except asyncio.TimeoutError:
            answer = ""
            yield f"data: {json.dumps({'type': 'error', 'content': '模型响应超时，先返回已命中的项目资料摘要。'}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            answer = ""
            yield f"data: {json.dumps({'type': 'error', 'content': f'助手生成失败：{str(exc)[:300]}'}, ensure_ascii=False)}\n\n"
        if not answer.strip():
            answer = "模型暂不可用。以下是命中的项目资料摘要：\n\n" + "\n\n".join(
                f"[{idx}] {item.get('title')} - {item.get('source')}\n{_clip_text(item.get('text', ''), 600)}"
                for idx, item in enumerate(contexts, 1)
            )
        yield f"data: {json.dumps({'type': 'content', 'content': answer}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'sources', 'sources': [{k: v for k, v in item.items() if k != 'text'} for item in contexts]}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/repository")
async def list_research_repository(
    q: str = "",
    limit: int = Query(100, ge=1, le=300),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    keyword = (q or "").strip()
    project_query = db.query(ResearchProject)
    if current_user.role != "admin":
        project_query = project_query.filter(ResearchProject.created_by_id == current_user.id)
    projects = project_query.order_by(ResearchProject.updated_at.desc()).all()
    project_ids = [item.id for item in projects]
    project_titles = {item.id: item.title for item in projects}
    if not project_ids:
        return {"results": []}

    source_query = db.query(ResearchSource).filter(ResearchSource.project_id.in_(project_ids))
    artifact_query = db.query(ResearchArtifact).filter(
        ResearchArtifact.project_id.in_(project_ids),
        ResearchArtifact.artifact_type.notin_(["project_intake", "workflow_trace"]),
    )
    if keyword:
        like = f"%{keyword}%"
        source_query = source_query.filter(
            (ResearchSource.title.ilike(like)) | (ResearchSource.summary.ilike(like)) | (ResearchSource.content.ilike(like))
        )
        artifact_query = artifact_query.filter(
            (ResearchArtifact.title.ilike(like)) | (ResearchArtifact.content.ilike(like))
        )

    source_rows = source_query.order_by(ResearchSource.created_at.desc()).limit(limit).all()
    artifact_rows = artifact_query.order_by(ResearchArtifact.created_at.desc()).limit(limit).all()
    results = [_repository_source_item(item, project_titles.get(item.project_id, "")) for item in source_rows]
    results.extend(_repository_artifact_item(item, project_titles.get(item.project_id, "")) for item in artifact_rows)
    results.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return {"results": results[:limit]}


@router.get("/search")
async def search_research_knowledge(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    keyword = q.strip()
    project_query = db.query(ResearchProject.id)
    if current_user.role != "admin":
        project_query = project_query.filter(ResearchProject.created_by_id == current_user.id)
    project_ids = [row[0] for row in project_query.all()]
    if not project_ids:
        return {"results": []}

    like = f"%{keyword}%"
    source_rows = (
        db.query(ResearchSource)
        .filter(
            ResearchSource.project_id.in_(project_ids),
            (ResearchSource.title.ilike(like)) | (ResearchSource.summary.ilike(like)) | (ResearchSource.content.ilike(like)),
        )
        .order_by(ResearchSource.created_at.desc())
        .limit(limit)
        .all()
    )
    remaining = max(0, limit - len(source_rows))
    artifact_rows = []
    if remaining:
        artifact_rows = (
            db.query(ResearchArtifact)
            .filter(
                ResearchArtifact.project_id.in_(project_ids),
                (ResearchArtifact.title.ilike(like)) | (ResearchArtifact.content.ilike(like)),
            )
            .order_by(ResearchArtifact.created_at.desc())
            .limit(remaining)
            .all()
        )

    results = [
        {
            "kind": "source",
            "id": item.id,
            "project_id": item.project_id,
            "title": item.title,
            "source_type": item.source_type,
            "url": item.url,
            "snippet": (item.summary or item.content or "")[:500],
            "created_at": item.created_at.isoformat(),
        }
        for item in source_rows
    ]
    results.extend(
        {
            "kind": "artifact",
            "id": item.id,
            "project_id": item.project_id,
            "artifact_type": item.artifact_type,
            "title": item.title,
            "version": item.version,
            "snippet": (item.content or "")[:500],
            "download_url": f"/research/artifacts/{item.id}/download",
            "created_at": item.created_at.isoformat(),
        }
        for item in artifact_rows
    )
    return {"results": results}


@router.post("/projects/{project_id}/revise", response_model=ResearchArtifactResponse)
async def revise_artifact(
    project_id: int,
    request: ResearchRevisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _get_project(db, project_id, current_user)
    if not request.instructions.strip():
        raise HTTPException(status_code=400, detail="修改意见不能为空")
    base_artifact = None
    if request.base_artifact_id:
        base_artifact = (
            db.query(ResearchArtifact)
            .filter(ResearchArtifact.id == request.base_artifact_id, ResearchArtifact.project_id == project.id)
            .first()
        )
        if not base_artifact:
            raise HTTPException(status_code=404, detail="基础文档不存在")
    try:
        artifact = research_workflow.revise_artifact(
            db,
            project,
            request.artifact_type,
            request.instructions,
            base_artifact,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _artifact_response(artifact)


@router.get("/artifacts/{artifact_id}/download")
async def download_artifact(
    artifact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    artifact = db.query(ResearchArtifact).filter(ResearchArtifact.id == artifact_id).first()
    if not artifact:
        raise HTTPException(status_code=404, detail="文档不存在")
    _get_project(db, artifact.project_id, current_user)
    metadata = artifact.artifact_metadata or {}
    review_original_key = metadata.get("review_original_object_key")
    if artifact.created_by == "human_review" and review_original_key:
        try:
            payload = research_store.get_bytes(review_original_key)
            filename = metadata.get("original_filename") or f"{_safe_download_name(artifact.title, artifact.artifact_type)}_v{artifact.version}"
            return Response(
                content=payload,
                media_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
                headers=_download_headers(filename),
            )
        except Exception:
            pass
    docx_key = metadata.get("docx_object_key")
    if docx_key and artifact.artifact_type in {"desktop_report", "proposal"}:
        try:
            payload = research_store.get_bytes(docx_key)
            filename = f"{_safe_download_name(artifact.title, artifact.artifact_type)}_v{artifact.version}.docx"
            return Response(
                content=payload,
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers=_download_headers(filename),
            )
        except Exception:
            pass

    content = artifact.content
    if artifact.object_key:
        try:
            content = research_store.get_text(artifact.object_key)
        except Exception:
            content = artifact.content

    ext = "json" if artifact.artifact_type in {"research_plan", "source_quality", "cleaned_facts", "risk_assessment"} else "md"
    filename = f"{_safe_download_name(artifact.title, artifact.artifact_type)}_v{artifact.version}.{ext}"
    media_type = "application/json; charset=utf-8" if ext == "json" else "text/markdown; charset=utf-8"
    return Response(
        content=content,
        media_type=media_type,
        headers=_download_headers(filename),
    )




