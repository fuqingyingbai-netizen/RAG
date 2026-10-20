import json
import base64
import html
import math
import mimetypes
import os
import queue
import re
import shutil
import subprocess
import tempfile
import time
import threading
import hashlib
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlencode, urlparse
from pathlib import Path
from types import SimpleNamespace

import requests
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from sqlalchemy.orm import Session, object_session

try:
    from .person_retrieval import SearchSession as PersonSearchSession, coverage as person_retrieval_coverage
    from .person_identity import build_anchor as build_identity_anchor, affiliations as identity_affiliations
    from .person_evidence import VERSION as PERSON_TEMPLATE_VERSION, build_packages as build_person_packages, normalize_facts as normalize_person_facts, append_index as append_person_index, report_audit as audit_person_report, normalize_person_risk, name_in_text as person_name_in_text, matched_name_forms
    from .company_platform import CompanyPlatformAudit, restore_platform_audit, failure_kind as platform_failure_kind
    from .industry_research import normalize_scope, scope_fingerprint, source_in_current_run, normalize_risk as normalize_industry_risk, unknown_risk as unknown_industry_risk, annotate_fact as annotate_industry_fact, append_evidence_index as append_industry_index, delivery_errors as industry_delivery_errors, company_filing_source
    from .docx_exporter import markdown_to_docx_bytes
    from .models import ResearchArtifact, ResearchProject, ResearchSource
    from .report_agents import CompanyReportAgent, IndustryReportAgent, PersonReportAgent
    from .report_agents.report_prompts import PROPOSAL_PROMPT, _company_fact_has_trusted_target_anchor, classify_company_fact_scope, _focused_cleaned_json, build_section_prompt
    from .report_agents.report_style import REPORT_CHAPTER_HEADING_RE, normalize_report_headings, sanitize_nested_report_chapter_headings
    from .research_store import research_store
    from .research_strategies import get_research_strategy
    from .web_search import web_search_provider
except ImportError:
    from person_retrieval import SearchSession as PersonSearchSession, coverage as person_retrieval_coverage
    from person_identity import build_anchor as build_identity_anchor, affiliations as identity_affiliations
    from person_evidence import VERSION as PERSON_TEMPLATE_VERSION, build_packages as build_person_packages, normalize_facts as normalize_person_facts, append_index as append_person_index, report_audit as audit_person_report, normalize_person_risk, name_in_text as person_name_in_text, matched_name_forms
    from company_platform import CompanyPlatformAudit, restore_platform_audit, failure_kind as platform_failure_kind
    from industry_research import normalize_scope, scope_fingerprint, source_in_current_run, normalize_risk as normalize_industry_risk, unknown_risk as unknown_industry_risk, annotate_fact as annotate_industry_fact, append_evidence_index as append_industry_index, delivery_errors as industry_delivery_errors, company_filing_source
    from docx_exporter import markdown_to_docx_bytes
    from models import ResearchArtifact, ResearchProject, ResearchSource
    from report_agents import CompanyReportAgent, IndustryReportAgent, PersonReportAgent
    from report_agents.report_prompts import PROPOSAL_PROMPT, _company_fact_has_trusted_target_anchor, classify_company_fact_scope, _focused_cleaned_json, build_section_prompt
    from report_agents.report_style import REPORT_CHAPTER_HEADING_RE, normalize_report_headings, sanitize_nested_report_chapter_headings
    from research_store import research_store
    from research_strategies import get_research_strategy
    from web_search import web_search_provider

load_dotenv()

TraceEmitter = Callable[[dict[str, Any]], None]


class WorkflowPaused(Exception):
    """Cooperative stop requested by the project owner; completed work stays persisted."""


FIXED_MAX_RESULTS_PER_QUERY = 30
FIXED_MIN_SOURCES_PER_MODULE = 5
FIXED_MAX_SEARCH_ROUNDS = 3
FIXED_AI_SEARCH_ENABLED = True
FIXED_GENERATE_PROPOSAL = True
PERSON_IDENTITY_POLICY_VERSION = "person-identity-v4-context"

DEFAULT_RESEARCH_MODULES = [
    "公司背景",
    "诉讼/制裁",
    "负面新闻",
    "股东高管",
    "融资情报",
    "管理团队",
    "行业口碑、产品认可度与同业竞争地位研判",
    "主营业务真实经营情况核验",
    "企业司法负面核查",
    "风险核查",
    "长尾平台舆情",
    "行业平台舆情",
    "图片/图表 OCR",
]

AUTHORITY_DOMAINS = {
    "gov.cn": 95,
    "court.gov.cn": 95,
    "wenshu.court.gov.cn": 98,
    "zxgk.court.gov.cn": 98,
    "creditchina.gov.cn": 96,
    "pbc.gov.cn": 95,
    "csrc.gov.cn": 95,
    "nfra.gov.cn": 95,
    "samr.gov.cn": 95,
    "cnipa.gov.cn": 95,
    "stats.gov.cn": 95,
    "ndrc.gov.cn": 95,
    "miit.gov.cn": 95,
    "cninfo.com.cn": 90,
    "hkexnews.hk": 94,
    "sse.com.cn": 90,
    "szse.cn": 90,
    "neeq.com.cn": 90,
    "sec.gov": 90,
    "reuters.com": 82,
    "bloomberg.com": 82,
    "wsj.com": 82,
    "ft.com": 82,
    "36kr.com": 72,
    "caixin.com": 78,
}

LOW_VALUE_DOMAINS = {
    "zhihu.com",
    "baijiahao.baidu.com",
    "blog.csdn.net",
}

TECH_CONTENT_DOMAINS = {
    "blog.csdn.net",
    "deepseek.csdn.net",
    "gitcode.csdn.net",
    "wenku.csdn.net",
    "cloud.baidu.com",
    "developer.aliyun.com",
    "yunzhujiboshi.com",
    "cnblogs.com",
    "juejin.cn",
    "segmentfault.com",
    "51cto.com",
}

TECH_CONTENT_TERMS = [
    "rag", "llm", "token", "上下文", "知识图谱", "向量", "embedding", "微调",
    "推理", "prompt", "api", "部署", "代码", "教程", "模型", "大模型",
]

DUE_DILIGENCE_TERMS = [
    "工商", "股东", "高管", "融资", "投资方", "估值", "营收", "收入",
    "客户", "供应商", "合作伙伴", "诉讼", "处罚", "裁判", "监管", "招聘",
    "员工", "离职", "管理团队", "组织架构", "商业化", "市场份额", "竞品",
]

PERSON_REPORT_OUTLINE = [
    ("摘要", ["概述", "核心发现点"]),
    ("个人发展综述", ["基本信息", "社会关系", "发展历程"]),
    ("行事风格及人格特质", ["责任心", "表达能力", "风险偏好"]),
    ("行业经验与业务能力评估", ["战略能力", "执行能力", "资源整合能力"]),
    ("领导力及管理能力评估", ["团队搭建", "管理风格", "组织控制力"]),
    ("口碑道德评价", ["离职员工评价", "合作伙伴评价", "同行评价"]),
    ("关联产业及公司", ["关联公司", "关联交易", "同业竞争"]),
    ("诉讼及监管风险", ["诉讼", "监管", "舆情"]),
    ("专项调研", ["潜在风险", "精力分配", "股东关系"]),
    ("风险核查", ["风险点", "证据", "待核验事项"]),
    ("综合评估", ["总结打分"]),
    ("信息来源", ["核心来源及可信度"]),
    ("后续研究点", ["待补充", "待访谈", "待核验事项"]),
]

COMPANY_REPORT_OUTLINE = [
    ("摘要", ["报告概述", "核心发现点", "需关注信号", "竞争格局", "总体评估"]),
    ("主体工商基本信息核查股东关系与治理底盘", ["注册信息", "公司规模", "注册资本", "股权架构", "治理底盘"]),
    ("历史沿革与融资", ["工商变更", "业务发展历程", "融资情况", "上市规范性瑕疵"]),
    ("组织治理与运营管理评估", ["组织架构", "决策机制", "权责划分", "内部激励"]),
    ("行业口碑、产品认可度与同业竞争地位研判", ["员工评价", "竞品评价", "合作方评价", "行业地位"]),
    ("主营业务真实经营情况核验", ["核心业务", "客户", "收入", "研发", "招聘"]),
    ("核心管理团队（深度/基础）风险研判", ["管理层履历", "产业资源", "关联关系", "团队掌控力"]),
    ("企业文化及人员流失情况", ["文化价值观", "人才储备", "核心岗位流失"]),
    ("企业司法负面核查", ["诉讼", "处罚", "产品风险", "研发风险", "供应链风险"]),
    ("定向穿透专项尽职调查", ["融资", "资金使用", "业务真实性", "大额资金往来"]),
    ("风险核查", ["组织风险", "业务风险", "行业特殊风险"]),
    ("综合评价", ["总结打分"]),
    ("信息来源", ["信息点", "来源说明", "可信度", "支持章节"]),
    ("后续研究建议", ["待确认信息点", "深度研究方向", "优先级", "访谈对象"]),
]

INDUSTRY_REPORT_OUTLINE = [
    ("摘要", ["报告概述", "核心研究发现", "需关注信号", "总体评估"]),
    ("行业基础定义与产业链全景", ["行业定义", "产业链", "代表企业", "瓶颈环节"]),
    ("政策环境分析与近期政策摘录", ["国家政策", "地方政策", "监管风险"]),
    ("市场规模与增长预测", ["历史规模", "增长率", "未来预测", "增长驱动"]),
    ("行业热度形成", ["催化因素", "里程碑事件", "资本关注逻辑"]),
    ("竞争格局", ["玩家分层", "市场集中度", "核心竞争力"]),
    ("行业投融资全景", ["融资事件", "阶段分布", "IPO进度", "并购案例"]),
    ("二级市场情绪", ["交易热度", "资金流向", "卖方覆盖"]),
    ("投资机会", ["细分赛道", "筛选标准", "资本配置方向"]),
    ("前景展望", ["趋势", "关键变量", "情景路径"]),
    ("龙头公司与重点企业对标", ["代表企业选择口径", "业务结构", "收入与盈利模式", "行业格局影响"]),
    ("行业风险与不确定性", ["行业风险", "商业化风险", "技术替代风险", "合规风险", "数据口径缺口"]),
    ("行业判断与综合评估", ["行业吸引力评分", "增长确定性评分", "竞争强度评分", "商业化成熟度评分", "结论边界"]),
    ("信息来源", ["信息点", "来源说明", "可信度", "支持章节"]),
    ("后续研究点", ["待确认信息点", "研究方向", "优先级"]),
]
def _now_key() -> str:
    return datetime.utcnow().strftime("%Y%m%d%H%M%S")


def _clip(text: str, limit: int = 12000) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "\n...[truncated]"


def _clip_utf8_bytes(text: str, limit: int = 1900) -> str:
    """Milvus VARCHAR limits are byte-based for UTF-8 payloads."""
    payload = str(text or "").encode("utf-8")
    if len(payload) <= limit:
        return str(text or "")
    return payload[:limit].decode("utf-8", errors="ignore")


def _project_doc_title(project: ResearchProject, suffix: str) -> str:
    name = (project.title or project.target_name or "项目").strip()
    return f"{name}{suffix}"


def _plain_json(text: str, *, allow_preface: bool = True) -> Any:
    try:
        from .json_utils import parse_json_output
    except ImportError:
        from json_utils import parse_json_output
    parsed = parse_json_output(text)
    if parsed is not None or not allow_preface or not isinstance(text, str):
        return parsed
    # Preserve company/person replies with an introductory sentence. Industry
    # model outputs opt into strict parsing; stored JSON is always parsed first.
    for pattern in (r"```(?:json)?\s*(.*)```", r"```(?:json)?\s*(.*?)```"):
        wrapper = re.search(pattern, text, flags=re.S)
        if wrapper:
            parsed = parse_json_output(wrapper.group(1))
            if parsed is not None:
                return parsed
    return None


def _env_int(name: str, default: int, minimum: int = 1, maximum: int = 600) -> int:
    try:
        value = int(os.getenv(name, default))
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def _emit(
    emit: TraceEmitter | None,
    stage: str,
    agent: str,
    label: str,
    detail: str = "",
    **extra: Any,
) -> None:
    if not emit:
        return
    event = {
        "type": "trace_step",
        "stage": stage,
        "agent": agent,
        "label": label,
        "detail": detail,
        "timestamp": datetime.utcnow().isoformat(),
    }
    event.update(extra)
    emit(event)


def _error_json(stage: str, exc: Exception) -> str:
    return json.dumps(
        {
            "stage": stage,
            "error": str(exc),
            "information_gaps": [f"{stage} 阶段执行失败，已进入降级产物生成，需要人工复核。"],
        },
        ensure_ascii=False,
        indent=2,
    )


class ResearchWorkflow:
    def __init__(self):
        self._model = None
        self._person_report_editor_model = None
        self._person_report_section_model = None
        self._company_report_editor_model = None
        self._cleaning_fallback_model = None
        self._ocr_access_token = None
        self._ocr_token_expires_at = 0.0
        self._ocr_lock = threading.Lock()
        self._ocr_last_request_at = 0.0
        self._ocr_stop_reason = ""
        self._report_agents = {
            "person": PersonReportAgent(),
            "company": CompanyReportAgent(),
            "industry": IndustryReportAgent(),
        }

    def _get_model(self):
        if self._model is not None:
            return self._model
        api_key = os.getenv("ARK_API_KEY")
        model_name = os.getenv("MODEL")
        base_url = os.getenv("BASE_URL")
        if not api_key or not model_name:
            return None
        self._model = init_chat_model(
            model=model_name,
            model_provider="openai",
            api_key=api_key,
            base_url=base_url,
            temperature=0.2,
            stream_usage=True,
            timeout=_env_int("LLM_TIMEOUT_SECONDS", 120, 10, 600),
            max_retries=_env_int("LLM_MAX_RETRIES", 2, 0, 5),
        )
        return self._model

    def _invoke(self, role: str, prompt: str, emit: TraceEmitter | None = None) -> str:
        model = self._get_model()
        if not model:
            _emit(emit, "llm", "workflow", "大模型未配置，使用降级逻辑", "", status="fallback")
            return ""
        system = (
            "你是咨询公司的研究工作流 Agent。"
            f"当前角色：{role}。"
            "输出必须严谨、可审计、保留来源，不编造事实。"
        )
        try:
            _emit(emit, "llm", role, "正在调用大模型", role, status="running")
            result = model.invoke(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ]
            )
            content = str(result.content or "")
            _emit(emit, "llm", role, "大模型调用完成", f"chars={len(content)}", status="done")
            return content
        except Exception as exc:
            _emit(emit, "llm", role, "大模型调用失败，进入降级逻辑", str(exc), status="fallback")
            return ""

    def _get_person_report_editor_model(self):
        if self._person_report_editor_model is not None:
            return self._person_report_editor_model
        api_key = os.getenv("ARK_API_KEY")
        model_name = os.getenv("MODEL")
        base_url = os.getenv("BASE_URL")
        if not api_key or not model_name:
            return None
        self._person_report_editor_model = init_chat_model(
            model=model_name,
            model_provider="openai",
            api_key=api_key,
            base_url=base_url,
            temperature=0.1,
            stream_usage=True,
            timeout=_env_int("PERSON_REPORT_EDITOR_TIMEOUT_SECONDS", 90, 10, 600),
            max_retries=_env_int("PERSON_REPORT_EDITOR_MAX_RETRIES", 0, 0, 2),
        )
        return self._person_report_editor_model

    def _invoke_company_summary(self, role: str, prompt: str, emit: TraceEmitter | None = None) -> str:
        """One bounded request per summary attempt, with no hidden SDK retries."""
        if not os.getenv("ARK_API_KEY") or not os.getenv("MODEL"):
            return ""
        repair = "修订" in role
        try:
            model = init_chat_model(
                model=os.environ["MODEL"], model_provider="openai",
                api_key=os.environ["ARK_API_KEY"], base_url=os.getenv("BASE_URL"),
                temperature=0.1, max_tokens=2400, max_retries=0,
                timeout=_env_int("COMPANY_SUMMARY_REPAIR_TIMEOUT_SECONDS" if repair else "COMPANY_SUMMARY_TIMEOUT_SECONDS", 45 if repair else 75, 10, 180),
            )
            response = model.invoke([
                {"role": "system", "content": "只依据完整事实卡撰写中文公司摘要，保留主体、时间、数值单位和证据编号。"},
                {"role": "user", "content": prompt},
            ])
            return str(response.content or "")
        except Exception as exc:
            _emit(emit, "llm", role, "公司摘要模型调用失败", type(exc).__name__, status="fallback")
            return ""
    def _invoke_industry_report(self, role: str, prompt: str, emit: TraceEmitter | None = None) -> str:
        """Bound industry chapter requests; a local repair gets no SDK retries."""
        repair = '修复 Agent' in role
        attribute = '_industry_repair_model' if repair else '_industry_section_model'
        model = getattr(self, attribute, None)
        if model is None:
            if not os.getenv('ARK_API_KEY') or not os.getenv('MODEL'):
                _emit(emit, 'llm', role, '行业章节模型未配置，使用来源事实摘录', '', status='fallback')
                return ''
            model = init_chat_model(model=os.environ['MODEL'], model_provider='openai',
                api_key=os.environ['ARK_API_KEY'], base_url=os.getenv('BASE_URL'), temperature=0.1,
                timeout=_env_int('INDUSTRY_REPAIR_TIMEOUT_SECONDS' if repair else 'INDUSTRY_SECTION_TIMEOUT_SECONDS', 45 if repair else 90, 10, 180),
                max_retries=0, max_tokens=2500 if repair else 6000)
            setattr(self, attribute, model)
        started = time.monotonic()
        _emit(emit, 'llm', role, '正在调用行业章节模型', f'input_chars={len(prompt)}', input_chars=len(prompt), status='running')
        try:
            result = model.invoke([{'role':'system','content':'仅使用输入证据，保留事实编号和数值口径，不新增事实。'},
                                   {'role':'user','content':prompt}])
            content = str(result.content or '')
            _emit(emit, 'llm', role, '行业章节模型调用完成', f'chars={len(content)}',
                  duration_ms=int((time.monotonic()-started)*1000), status='done')
            return content
        except Exception as exc:
            _emit(emit, 'llm', role, '行业章节模型超时或失败，使用来源事实摘录', str(exc)[:800],
                  duration_ms=int((time.monotonic()-started)*1000), degraded=True, status='fallback')
            return ''

    def _invoke_industry_risk(self, role: str, prompt: str, emit=None, repair: bool = False) -> str:
        """Risk scoring and its one local repair never use hidden SDK retries."""
        if not os.getenv('ARK_API_KEY') or not os.getenv('MODEL'):
            return ''
        attribute = '_industry_risk_repair_model' if repair else '_industry_risk_model'
        model = getattr(self, attribute, None)
        if model is None:
            model = init_chat_model(model=os.environ['MODEL'], model_provider='openai',
                api_key=os.environ['ARK_API_KEY'], base_url=os.getenv('BASE_URL'), temperature=0.1,
                timeout=_env_int('INDUSTRY_RISK_REPAIR_TIMEOUT_SECONDS' if repair else 'INDUSTRY_RISK_TIMEOUT_SECONDS',
                                 45 if repair else 90, 10, 180), max_retries=0, max_tokens=2500 if repair else 4000)
            setattr(self, attribute, model)
        started = time.monotonic()
        _emit(emit, 'llm', role, '正在调用行业风险模型', f'input_chars={len(prompt)}', input_chars=len(prompt), status='running')
        try:
            result = model.invoke([{'role': 'system', 'content': '只用允许的证据与指标；评分理由简短，缺证返回unknown，输出完整JSON。'},
                                   {'role': 'user', 'content': prompt}])
            content = str(result.content or '')
            _emit(emit, 'llm', role, '行业风险模型调用完成', f'chars={len(content)}',
                  duration_ms=int((time.monotonic()-started)*1000), status='done')
            return content
        except Exception as exc:
            _emit(emit, 'llm', role, '行业风险模型超时或失败，保留待核验结果', str(exc)[:800],
                  duration_ms=int((time.monotonic()-started)*1000), status='fallback')
            return ''

    def _invoke_industry_cleaning(self, role: str, prompt: str, emit=None, timeout_seconds=60) -> str:
        """Industry enrichment gets a bounded request with no hidden SDK retries."""
        if not os.getenv('ARK_API_KEY') or not os.getenv('MODEL'):
            return ''
        started = time.monotonic()
        _emit(emit, 'llm', role, '正在调用行业清洗模型', f'timeout_seconds={timeout_seconds:.1f}',
              timeout_seconds=timeout_seconds, status='running')
        try:
            model = init_chat_model(model=os.environ['MODEL'], model_provider='openai',
                api_key=os.environ['ARK_API_KEY'], base_url=os.getenv('BASE_URL'), temperature=0.1,
                timeout=timeout_seconds, max_retries=0, max_tokens=2000)
            result = model.invoke([{'role': 'system', 'content': '只提取可核验事实，输出完整JSON并保留来源和统计口径。'},
                                   {'role': 'user', 'content': prompt}])
            content = str(result.content or '')
            _emit(emit, 'llm', role, '行业清洗模型调用完成', f'chars={len(content)}',
                  duration_ms=int((time.monotonic()-started)*1000), status='done')
            return content
        except Exception as exc:
            _emit(emit, 'llm', role, '行业清洗模型失败，保留规则事实', str(exc)[:800],
                  duration_ms=int((time.monotonic()-started)*1000), degraded=True, status='fallback')
            return ''

    def _get_person_report_section_model(self):
        if self._person_report_section_model is not None:
            return self._person_report_section_model
        api_key = os.getenv("ARK_API_KEY")
        model_name = os.getenv("MODEL")
        base_url = os.getenv("BASE_URL")
        if not api_key or not model_name:
            return None
        self._person_report_section_model = init_chat_model(
            model=model_name,
            model_provider="openai",
            api_key=api_key,
            base_url=base_url,
            temperature=0.2,
            stream_usage=True,
            timeout=_env_int("PERSON_REPORT_SECTION_TIMEOUT_SECONDS", 150, 30, 600),
            max_retries=_env_int("PERSON_REPORT_SECTION_MAX_RETRIES", 1, 0, 1),
        )
        return self._person_report_section_model

    def _invoke_person_report_section(self, role: str, prompt: str, emit: TraceEmitter | None = None) -> str:
        """Use the bounded chapter model; one provider retry is allowed for transient failures."""
        model = self._get_person_report_section_model()
        if not model:
            _emit(emit, "llm", role, "人物报告章节模型未配置，使用证据保底", "", status="fallback")
            raise RuntimeError("person_model_not_configured")
        try:
            started_at = time.monotonic()
            _emit(
                emit,
                "llm",
                role,
                "正在调用人物报告章节模型",
                f"input_chars={len(prompt)}",
                input_chars=len(prompt),
                status="running",
            )
            result = model.invoke([
                {"role": "system", "content": "你是咨询公司的尽调章节研究员。只使用给定证据，保留原始URL，不编造事实。"},
                {"role": "user", "content": prompt},
            ])
            content = str(result.content or "")
            duration_ms = int((time.monotonic() - started_at) * 1000)
            output_url_count = len(set(re.findall(r"https?://[^\s)\]|>]+", content)))
            _emit(
                emit,
                "llm",
                role,
                "人物报告章节模型调用完成",
                f"input_chars={len(prompt)}, output_chars={len(content)}, urls={output_url_count}, duration_ms={duration_ms}",
                input_chars=len(prompt),
                output_chars=len(content),
                output_url_count=output_url_count,
                duration_ms=duration_ms,
                status="done",
            )
            return content
        except Exception as exc:
            duration_ms = int((time.monotonic() - started_at) * 1000)
            error_text = str(exc)
            failure_kind = "timeout" if "timeout" in error_text.lower() or "timed out" in error_text.lower() else "provider_error"
            _emit(
                emit,
                "llm",
                role,
                "人物报告章节模型超时或失败，使用证据保底",
                error_text,
                input_chars=len(prompt),
                duration_ms=duration_ms,
                failure_kind=failure_kind,
                degraded=True,
                status="fallback",
            )
            raise

    def _invoke_person_report_editor(self, role: str, prompt: str, emit: TraceEmitter | None = None) -> str:
        """Use a short, non-retrying request for bounded person-report editing."""
        model = self._get_person_report_editor_model()
        if not model:
            _emit(emit, "llm", role, "人物报告总编模型未配置，保留章节草稿", "", status="fallback")
            return ""
        system = "你是咨询公司的报告总编。只做目录校验、去重和轻量润色，保留所有可审计事实与来源。"
        try:
            _emit(emit, "llm", role, "正在调用人物报告轻量总编", role, status="running")
            result = model.invoke([
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ])
            content = str(result.content or "")
            _emit(emit, "llm", role, "人物报告轻量总编完成", f"chars={len(content)}", status="done")
            return content
        except Exception as exc:
            _emit(emit, "llm", role, "人物报告轻量总编超时或失败，保留章节草稿", str(exc), status="fallback")
            return ""

    def _get_company_report_editor_model(self):
        if self._company_report_editor_model is not None:
            return self._company_report_editor_model
        api_key = os.getenv("ARK_API_KEY")
        model_name = os.getenv("MODEL")
        base_url = os.getenv("BASE_URL")
        if not api_key or not model_name:
            return None
        self._company_report_editor_model = init_chat_model(
            model=model_name,
            model_provider="openai",
            api_key=api_key,
            base_url=base_url,
            temperature=0.1,
            stream_usage=True,
            timeout=_env_int("COMPANY_REPORT_EDITOR_TIMEOUT_SECONDS", 150, 30, 600),
            max_retries=_env_int("COMPANY_REPORT_EDITOR_MAX_RETRIES", 1, 0, 1),
        )
        return self._company_report_editor_model

    def _invoke_company_report_editor(self, role: str, prompt: str, emit: TraceEmitter | None = None) -> str:
        """Use a dedicated, bounded editor request for company-report batches."""
        model = self._get_company_report_editor_model()
        if not model:
            _emit(emit, "llm", role, "公司报告分批主编模型未配置，保留章节草稿", "", status="fallback")
            return ""
        try:
            _emit(
                emit, "llm", role, "正在调用公司报告分批主编模型",
                f"input_chars={len(prompt)}", input_chars=len(prompt), status="running",
            )
            result = model.invoke([
                {"role": "system", "content": "你是咨询公司的公司尽调报告总编。仅校订给定章节，不得新增事实或来源。"},
                {"role": "user", "content": prompt},
            ])
            content = str(result.content or "")
            _emit(
                emit, "llm", role, "公司报告分批主编模型调用完成",
                f"chars={len(content)}", output_chars=len(content), status="done",
            )
            return content
        except Exception as exc:
            _emit(emit, "llm", role, "公司报告分批主编超时或失败，保留章节草稿", str(exc), status="fallback")
            return ""

    def _invoke_vision(
        self,
        role: str,
        image_urls: list[str],
        context: str,
        emit: TraceEmitter | None = None,
    ) -> str:
        api_key = os.getenv("VISION_API_KEY") or os.getenv("ARK_API_KEY")
        base_url = (os.getenv("VISION_BASE_URL") or os.getenv("BASE_URL") or "").rstrip("/")
        model_name = os.getenv("VISION_MODEL", "qwen-vl-plus")
        if not api_key or not base_url or not image_urls:
            _emit(emit, "vision", "workflow", "视觉模型未配置或无图片，跳过", "", status="skipped")
            return ""
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "你是咨询尽调视觉资料分析 Agent。请识别图片、网页截图或图表中的关键信息。"
                    "重点抽取公司/个人/行业事实、数据、趋势、图表结论、风险信号和需要人工复核的问题。"
                    "不要编造图片中不存在的信息。输出中文 Markdown，优先使用表格。"
                    "如果是企查查/天眼查/稀牛等专业平台截图，必须结构化输出："
                    "1）工商信息表；2）股东/实控人/关联方表；3）风险/诉讼/处罚表；"
                    "4）图谱节点与边表（主体A|关系|主体B|证据文字）；5）待核验字段。"
                    "无法识别的字段写“待查”，不要写成泛泛描述段落。"
                    f"\n\n资料上下文：\n{_clip(context, 3000)}"
                ),
            }
        ]
        max_images = _env_int("VISION_MAX_IMAGES_PER_SOURCE", 2, 1, 6)
        selected_urls = image_urls[:max_images]
        for url in selected_urls:
            content.append({"type": "image_url", "image_url": {"url": url}})
        timeout_seconds = _env_int("VISION_TIMEOUT_SECONDS", 180, 30, 600)
        max_retries = _env_int("VISION_MAX_RETRIES", 2, 0, 5)
        last_error = ""
        for attempt in range(max_retries + 1):
            try:
                _emit(
                    emit,
                    "vision",
                    role,
                    "正在调用 Qwen-VL 视觉模型",
                    f"images={len(selected_urls)}, attempt={attempt + 1}/{max_retries + 1}, timeout={timeout_seconds}s",
                    status="running",
                )
                resp = requests.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model_name,
                        "messages": [{"role": "user", "content": content}],
                        "temperature": 0.1,
                    },
                    timeout=(10, timeout_seconds),
                )
                resp.raise_for_status()
                answer = resp.json()["choices"][0]["message"]["content"]
                _emit(emit, "vision", "workflow", "视觉模型调用完成", "", status="done")
                return str(answer or "")
            except Exception as exc:
                last_error = str(exc)
                if attempt < max_retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
        _emit(emit, "vision", role, "视觉模型调用失败，保留人工复核标记", last_error, status="fallback")
        return ""

    def run_project(
        self,
        db: Session,
        project: ResearchProject,
        search_queries: list[str],
        focus_questions: list[str],
        max_results_per_query: int = FIXED_MAX_RESULTS_PER_QUERY,
        generate_proposal: bool = True,
        emit: TraceEmitter | None = None,
        intake: dict[str, Any] | None = None,
        pause_requested: Callable[[], bool] | None = None,
    ) -> tuple[list[ResearchArtifact], int]:
        def checkpoint(stage: str) -> None:
            if pause_requested and pause_requested():
                project.status = "paused"
                project.updated_at = datetime.utcnow()
                db.commit()
                _emit(emit, stage, "workflow", "任务已暂停", "当前已完成的数据和成果均已保存，可点击继续恢复", status="paused")
                raise WorkflowPaused("任务已暂停")

        _emit(emit, "init", "workflow", "工作流启动", "", status="running")
        max_results_per_query = FIXED_MAX_RESULTS_PER_QUERY
        generate_proposal = FIXED_GENERATE_PROPOSAL
        project.status = "collecting"
        project.updated_at = datetime.utcnow()
        db.commit()

        normalized_intake = self._normalize_intake(project, intake or {}, search_queries, focus_questions)
        standardized_type = normalized_intake["target_type"]
        if standardized_type == "person":
            project.person_research_intake = normalized_intake
            project.person_platform_query_keys = set()
            project.person_platform_attempts = []
            project.person_platform_identities = {}
            project.person_platform_core_pending = set()
            self._refresh_person_source_identities(project, normalized_intake)
            db.commit()
        cleaning_pipeline_version = (
            "person-evidence-v16-critical-platform-coverage"
            if standardized_type == "person"
            else "company-evidence-v11-vector-survey-charts"
            if standardized_type == "company"
            else "industry-evidence-v9-local-nature"
            if standardized_type == "industry"
            else "default-v4-auditable"
        )
        report_pipeline_version = {
            "person": "person-report-v9-review-markers",
            # v8 additionally indexes structured business records (QCC/Xiniu)
            # and uses evidence-density-aware company chapter writing. Do not
            # reuse a report produced before those delivery rules.
            # v12 keeps every cited E-ID in chapter 13 and strips model
            # placeholder URLs before validation/export.
            "company": "company-report-evidence-v37-column-notes",
            # v3 fixes the keyword-scoring bottleneck for industry chapters
            # (zero-score filter disabled for industry so chapters 10/13 are
            # not starved) and raises the model-call threshold from fact_count
            # == 0 to fact_count < 3.  Do not reuse a v2 industry report.
            # v4 also tightens the delivery DOCX outline and compresses the
            # chapter-14 source index; old v3 reports must be rebuilt so a
            # rerun is not just a stale Word re-export.
            # v5 demotes nested duplicate global chapter headings inside
            # sections, which previously polluted Word navigation under
            # chapters such as "10. 前景展望".
            "industry": "industry-report-evidence-v17-validated-fallback",
        }.get(standardized_type, "default-report-v1")
        if standardized_type == "industry":
            setattr(project, "industry_scope", normalized_intake.get("industry_scope") or {})
        if project.target_type != standardized_type:
            project.target_type = standardized_type
            db.commit()
        _emit(emit, "init", "workflow", "研究对象类型已标准化", standardized_type, target_type=standardized_type, status="done")
        checkpoint("init")

        resume_enabled = os.getenv("WORKFLOW_RESUME_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
        force_refresh = bool(normalized_intake.get("force_refresh_from_upload_ocr"))
        company_ocr_retry = standardized_type == 'company' and os.getenv('COMPANY_PDF_OCR_RETRY_PENDING','false').lower() in {'true','1','on'}
        company_chart_pending = bool(self._company_chart_refresh_candidates(project)) if standardized_type == 'company' else False
        intake_fingerprint = self._intake_evidence_fingerprint(normalized_intake)
        if standardized_type == "industry":
            setattr(project, "industry_scope_fingerprint", scope_fingerprint(normalized_intake, source_only=True))
        sources_match_intake = self._project_sources_match_intake(project, normalized_intake)
        existing_report = self._latest_artifact(project, "desktop_report")
        existing_proposal = self._latest_artifact(project, "proposal")
        existing_cleaned_for_reuse = self._latest_artifact(project, "cleaned_facts")
        existing_risk_for_reuse = self._latest_artifact(project, "risk_assessment")
        can_reuse_final_outputs = (
            resume_enabled
            and standardized_type not in {'industry', 'person'}  # Reexports must refresh actual citation/claim diagnostics.
            and not force_refresh
            and not company_ocr_retry
            and not company_chart_pending
            and len(getattr(project, "sources", []) or []) > 0
            and sources_match_intake
            and existing_cleaned_for_reuse is not None
            and (existing_cleaned_for_reuse.artifact_metadata or {}).get("pipeline_version") == cleaning_pipeline_version
            and (existing_cleaned_for_reuse.artifact_metadata or {}).get("intake_fingerprint") == intake_fingerprint
            and existing_risk_for_reuse is not None
            and existing_report is not None
            and (existing_report.artifact_metadata or {}).get("report_pipeline_version") == report_pipeline_version
            and not (existing_report.artifact_metadata or {}).get("quality_warning")
            and (not generate_proposal or existing_proposal is not None)
            and (
                not generate_proposal
                or not (existing_proposal.artifact_metadata or {}).get("quality_warning")
            )
        )
        if can_reuse_final_outputs:
            _emit(emit, "report", "desktop_report_agent", "复用已有桌面研究报告", f"from_artifact_id={existing_report.id}", status="skipped")
            report_artifact = self.save_artifact(
                db,
                project,
                "desktop_report",
                _project_doc_title(project, "行业研究报告" if standardized_type == "industry" else "背景调查报告"),
                existing_report.content,
                {
                    "agent": "report_writer",
                    "reused_from_artifact_id": existing_report.id,
                    "report_pipeline_version": report_pipeline_version,
                },
            )
            artifacts = [report_artifact]
            if generate_proposal and existing_proposal is not None:
                _emit(emit, "proposal", "proposal_agent", "复用已有项目建议书", f"from_artifact_id={existing_proposal.id}", status="skipped")
                proposal_artifact = self.save_artifact(
                    db,
                    project,
                    "proposal",
                    _project_doc_title(project, "项目建议书"),
                    existing_proposal.content,
                    {"agent": "proposal_writer", "reused_from_artifact_id": existing_proposal.id},
                )
                artifacts.append(proposal_artifact)
            project.status = "completed"
            project.updated_at = datetime.utcnow()
            db.commit()
            self._finalize_source_records(db, project, emit)
            _emit(emit, "done", "workflow", "已复用既有产物并完成", "", status="done")
            return artifacts, 0

        normalized_intake = self.resolve_business_entity(project, normalized_intake, emit=emit)
        _emit(emit, "planning", "research_planning_agent", "生成研究计划", "", status="running")
        plan = self.plan_research(project, normalized_intake, emit=emit)
        plan_artifact = self.save_artifact(
            db,
            project,
            "research_plan",
            _project_doc_title(project, "研究计划与检索策略"),
            json.dumps(plan, ensure_ascii=False, indent=2),
            {"agent": "research_planning"},
        )
        _emit(emit, "planning", "research_planning_agent", "研究计划已入库", f"artifact_id={plan_artifact.id}", artifact_id=plan_artifact.id, status="done")
        checkpoint("planning")

        sources_added = 0
        existing_source_count = len(getattr(project, "sources", []) or [])
        has_workflow_history = bool(getattr(project, "artifacts", []) or [])
        has_collected_sources = any(
            (source.source_type or "") != "upload"
            and (source.source_metadata or {}).get("stage") not in {"initial_upload", "human_review", "second_stage"}
            for source in (getattr(project, "sources", []) or [])
        )
        allow_archive_reuse = resume_enabled and (has_workflow_history or has_collected_sources) and standardized_type != "industry"
        required_modules = [
            str(item.get("name") or "")
            for item in (plan.get("modules") or [])
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        resume_min_per_module = int((plan.get("coverage_thresholds") or {}).get("min_sources_per_module") or FIXED_MIN_SOURCES_PER_MODULE)
        existing_module_counts = Counter(
            str((source.source_metadata or {}).get("module") or source.source_type or "unknown")
            for source in self._active_industry_sources(project)
            if (source.content or source.summary or "").strip()
            and not self._is_failed_extraction_source(source)
        )
        company_diligence_queries = []
        if standardized_type == "company":
            from report_agents.company_diligence import diligence_discovery_queries
            company_diligence_queries = diligence_discovery_queries(list(project.sources or []), str(project.target_name or ""))
            from report_agents.company_risk_register import recall_discovery_queries
            company_diligence_queries += recall_discovery_queries(list(project.sources or []), str(project.target_name or ""))
        skip_web_search = bool(
            resume_enabled
            and not force_refresh
            and sources_match_intake
            and required_modules
            and all(existing_module_counts.get(module, 0) >= resume_min_per_module for module in required_modules)
            and not company_diligence_queries
        )
        if standardized_type == "person":
            prior_retrieval = self._latest_artifact(project, "person_retrieval_audit")
            skip_web_search = bool(resume_enabled and not force_refresh and sources_match_intake
                                   and prior_retrieval and (prior_retrieval.artifact_metadata or {}).get("retrieval_version") == "person-retrieval-v2-budget-context"
                                   and (prior_retrieval.artifact_metadata or {}).get("intake_fingerprint") == intake_fingerprint)
        if standardized_type == 'industry' and plan.get('evidence_requirements'):
            evidence_gaps = self._industry_retrieval_gaps(project,plan)
            skip_web_search = skip_web_search and not evidence_gaps
        if skip_web_search:
            _emit(
                emit,
                "web_search",
                "online_search_agent",
                "既有来源已满足逐模块覆盖，跳过在线检索",
                f"modules={len(required_modules)}, min_per_module={resume_min_per_module}",
                status="skipped",
            )
        else:
            try:
                sources_added = self.collect_web_sources(
                    db,
                    project,
                    search_queries,
                    focus_questions,
                    max_results_per_query,
                    emit=emit,
                    plan=plan,
                    intake=normalized_intake,
                    reuse_archived=allow_archive_reuse,
                    pause_requested=pause_requested,
                )
                db.expire(project, ["sources"])
                normalized_intake = self.resolve_business_entity(project, normalized_intake, emit=emit)
            except WorkflowPaused:
                raise
            except Exception as exc:
                db.rollback()
                _emit(emit, "web_search", "online_search_agent", "在线检索失败，进入降级流程", str(exc), status="fallback")
        checkpoint("web_search")

        if standardized_type == "person":
            previous = self._latest_artifact(project, "person_retrieval_audit")
            if previous and not getattr(project, "person_retrieval_audit", None):
                try:
                    project.person_retrieval_audit = json.loads(previous.content or "{}")
                except (ValueError, TypeError):
                    pass
        has_structured_sources = self._project_has_structured_sources(project)
        if resume_enabled and has_structured_sources and standardized_type != "person":
            _emit(emit, "structured_data", "structured_data_agent", "已存在专业平台来源，跳过结构化采集", "", status="skipped")
        else:
            try:
                normalized_intake = self._prepare_structured_entity_intake(project, normalized_intake, emit=emit)
                structured_added = self.collect_structured_sources(db, project, normalized_intake, emit=emit)
                if structured_added:
                    sources_added += structured_added
                    db.expire(project, ["sources"])
                    _emit(emit, "structured_data", "structured_data_agent", "专业平台结构化采集完成", f"sources_added={structured_added}", status="done")
            except Exception as exc:
                db.rollback()
                _emit(emit, "structured_data", "structured_data_agent", "专业平台结构化采集失败，继续工作流", str(exc), status="fallback")

        # Run one bounded pass for direct affiliations confirmed during person
        # research. Relations returned by these platforms are evidence only and
        # are never used as seeds for another collection pass.
        try:
            affiliation_structured_added = self.collect_person_affiliation_structured_sources(
                db, project, normalized_intake, emit=emit
            )
            if affiliation_structured_added:
                sources_added += affiliation_structured_added
                db.expire(project, ["sources"])
        except Exception as exc:
            db.rollback()
            _emit(
                emit,
                "structured_data",
                "person_affiliation_structured_agent",
                "人物关联企业专业平台采集失败，继续工作流",
                str(exc),
                status="fallback",
            )

        if (
            os.getenv("STRUCTURED_SOURCE_REQUIRED", "false").strip().lower() in {"1", "true", "yes", "on"}
            and standardized_type == "company"
            and not self._project_has_structured_sources(project)
        ):
            message = "目标公司报告缺少企查查/天眼查/稀牛等专业数据库来源，已停止生成，避免输出缺少硬证据的报告。"
            _emit(emit, "structured_data", "structured_data_agent", "专业数据库来源缺失，质量闸门拦截", message, status="error")
            raise RuntimeError(message)

        ocr_count = 0
        try:
            ocr_count = self.enrich_ocr_sources(db, project, emit=emit)
            if ocr_count:
                db.expire(project, ["sources"])
                _emit(emit, "ocr", "ocr_extraction_agent", "OCR 提取完成", f"sources={ocr_count}", status="done")
        except Exception as exc:
            db.rollback()
            _emit(emit, "ocr", "ocr_extraction_agent", "OCR 提取失败，继续工作流", str(exc), status="fallback")

        chart_count = 0
        if standardized_type == 'company':
            try:
                chart_count = self.enrich_company_survey_charts(db, project, emit=emit)
                if chart_count:db.expire(project, ["sources"])
            except Exception as exc:
                db.rollback()
                _emit(emit, "charts", "company_chart_agent", "公司图表补取失败，保留原资料",
                      type(exc).__name__, status="warning")

        if not (getattr(project, "sources", []) or []):
            message = (
                "未采集到任何可用于报告的来源，已停止生成空报告。"
                "请检查目标人物姓名、所属机构或搜索服务配置后重试。"
            )
            _emit(emit, "quality", "source_quality_agent", "来源为空，质量闸门拦截", message, status="error")
            raise RuntimeError(message)

        try:
            quality = self.evaluate_source_quality(project, plan)
        except Exception as exc:
            db.rollback()
            _emit(emit, "quality", "source_quality_agent", "来源质量评估失败，使用降级结果", str(exc), status="fallback")
            quality = {
                "source_count": len(getattr(project, "sources", []) or []),
                "average_score": 0,
                "module_counts": {},
                "authoritative_counts": {},
                "information_gaps": [f"来源质量评估失败：{exc}"],
                "ocr_items": [],
                "sources": [],
            }
        quality = self._apply_authority_coverage_requirements(quality, standardized_type, getattr(project, "industry_scope", {}))
        if (
            os.getenv("AUTHORITY_COVERAGE_REQUIRED", "false").strip().lower() in {"1", "true", "yes", "on"}
            and quality.get("authority_coverage_passed") is False
        ):
            message = "权威来源覆盖闸门未通过：" + "；".join(quality.get("authority_coverage_gaps") or [])
            _emit(emit, "quality", "source_quality_agent", "权威来源覆盖不足，停止生成", message, status="error")
            raise RuntimeError(message)
        quality_artifact = self.save_artifact(
            db,
            project,
            "source_quality",
            _project_doc_title(project, "来源质量与覆盖率评估"),
            json.dumps(quality, ensure_ascii=False, indent=2),
            {"agent": "source_quality"},
        )
        _emit(emit, "quality", "source_quality_agent", "来源质量评估完成", "", status="done")
        checkpoint("quality")

        project.status = "cleaning"
        db.commit()
        existing_cleaned = self._latest_artifact(project, "cleaned_facts")
        # Bump the version whenever cleaning semantics change so a project with
        # a prior workflow_error can never be silently reused as fresh facts.
        use_existing_cleaned = (
            resume_enabled
            and not force_refresh
            and not (standardized_type == 'company' and (ocr_count or company_ocr_retry or chart_count or company_chart_pending))
            and sources_match_intake
            and existing_cleaned is not None
            and (existing_cleaned.artifact_metadata or {}).get("pipeline_version") == cleaning_pipeline_version
            and (existing_cleaned.artifact_metadata or {}).get("intake_fingerprint") == intake_fingerprint
        )
        industry_source_snapshot=None
        if standardized_type=='industry':
            try:
                from .industry_evidence import source_fingerprint
            except ImportError:
                from industry_evidence import source_fingerprint
            industry_source_snapshot=source_fingerprint(self._active_industry_sources(project))
            use_existing_cleaned=use_existing_cleaned and (existing_cleaned.artifact_metadata or {}).get('source_fingerprint')==industry_source_snapshot
        if use_existing_cleaned:
            cleaned_artifact = existing_cleaned
            cleaned = existing_cleaned.content
            _emit(emit, "cleaning", "data_cleaning_agent", "复用已有清洗事实库", "", status="skipped")
        else:
            _emit(emit, "cleaning", "data_cleaning_agent", "开始清洗事实", "", status="running")
            try:
                cleaned = self.clean_sources(project, emit=emit, plan=plan, quality=quality)
            except Exception as exc:
                db.rollback()
                if standardized_type == "person" and "人物报告事实质量闸门未通过" in str(exc):
                    _emit(emit, "cleaning", "data_cleaning_agent", "人物事实质量不足，停止生成", str(exc), status="error")
                    raise
                _emit(emit, "cleaning", "data_cleaning_agent", "事实清洗失败，使用降级清洗", str(exc), status="fallback")
                cleaned = json.dumps(self._fallback_clean(project) | {"workflow_error": _error_json("cleaning", exc)}, ensure_ascii=False, indent=2)
            if standardized_type == 'industry':
                cleaned = self._prepare_industry_evidence(project,cleaned,plan)
            prepared_payload=_plain_json(cleaned) if standardized_type=='industry' else {}
            cleaned_artifact = self.save_artifact(
                db,
                project,
                "cleaned_facts",
                _project_doc_title(project, "清洗事实库"),
                cleaned,
                {
                    "agent": "data_cleaning",
                    "source_count": len(project.sources),
                    "pipeline_version": cleaning_pipeline_version,
                    "intake_fingerprint": intake_fingerprint,
                    **({'source_fingerprint':industry_source_snapshot} if standardized_type=='industry' else {}),
                    **({'provenance_summary':prepared_payload.get('provenance_summary',{})}
                       if standardized_type=='industry' and isinstance(prepared_payload,dict) else {}),
                },
            )
            _emit(emit, "cleaning", "data_cleaning_agent", "清洗事实库已入库", f"artifact_id={cleaned_artifact.id}", artifact_id=cleaned_artifact.id, status="done")
        checkpoint("cleaning")
        if standardized_type=='industry':
            project.industry_evidence_payload=_plain_json(cleaned) or {}

        project.status = "risk_scoring"
        if standardized_type == "company":
            project.company_research_intake = dict(intake or {})
        db.commit()
        existing_risk = self._latest_artifact(project, "risk_assessment")
        industry_risk_inputs=({'cleaned_artifact_id':cleaned_artifact.id,
            'cleaned_sha256':hashlib.sha256(cleaned.encode()).hexdigest()} if standardized_type=='industry' else {})
        if standardized_type == 'industry':
            try:
                from .industry_research import INDUSTRY_RISK_VERSION
            except ImportError:
                from industry_research import INDUSTRY_RISK_VERSION
        # A risk assessment is derived from the cleaned facts. Never reuse it when
        # cleaning was invalidated or regenerated, otherwise the report mixes new
        # evidence with a stale score from the previous pipeline.
        use_existing_risk = resume_enabled and not force_refresh and use_existing_cleaned and existing_risk is not None
        if standardized_type == 'industry' and use_existing_risk:
            use_existing_risk = ((existing_risk.artifact_metadata or {}).get('risk_pipeline_version') == INDUSTRY_RISK_VERSION
                and all((existing_risk.artifact_metadata or {}).get(k)==v for k,v in industry_risk_inputs.items()))
        if use_existing_risk:
            risk_artifact = existing_risk
            risk = existing_risk.content
            _emit(emit, "risk", "risk_assessment_agent", "复用已有风险研判", "", status="skipped")
        else:
            _emit(emit, "risk", "risk_assessment_agent", "开始风险研判", "", status="running")
            try:
                risk = self.assess_risk(project, cleaned, emit=emit)
            except Exception as exc:
                db.rollback()
                _emit(emit, "risk", "risk_assessment_agent", "风险研判失败，使用降级评分", str(exc), status="fallback")
                fallback = ({"overall_score": None, "risk_level": "unknown", "dimensions": [],
                             "key_risks": [], "unknowns": ["公司原件风险登记失败，需复核；未回退到关键词评分。"]}
                            if standardized_type == "company" else unknown_industry_risk(scope=getattr(project, "industry_scope", {})) if standardized_type == "industry" else self._fallback_risk(cleaned))
                risk = json.dumps(fallback | {"workflow_error": _error_json("risk", exc)}, ensure_ascii=False, indent=2)
            risk_artifact = self.save_artifact(db, project, "risk_assessment", _project_doc_title(project, "风险研判"), risk,
                {"agent": "risk_assessment", **industry_risk_inputs,
                 **({'risk_pipeline_version': INDUSTRY_RISK_VERSION,
                     'risk_transparency': (_plain_json(risk) or {}).get('risk_transparency', {})} if standardized_type == 'industry' else {})})
            _emit(emit, "risk", "risk_assessment_agent", "风险研判完成", "", status="done")
        checkpoint("risk")
        industry_report_inputs=({**industry_risk_inputs,'risk_artifact_id':risk_artifact.id,
            'risk_sha256':hashlib.sha256(risk.encode()).hexdigest()} if standardized_type=='industry' else {})

        project.status = "report_generating"
        db.commit()
        existing_report = self._latest_artifact(project, "desktop_report")
        # Recheck the latest report, including its degradations. Never replace a
        # newer review draft with an older candidate simply because it had no warning.
        reusable_report = existing_report
        use_existing_report = (
            resume_enabled
            and use_existing_cleaned
            and use_existing_risk
            and reusable_report is not None
            and (
                (reusable_report.artifact_metadata or {}).get("report_pipeline_version") == report_pipeline_version
            )
            and (standardized_type == 'industry' or not (reusable_report.artifact_metadata or {}).get("quality_warning"))
        )
        if standardized_type=='industry' and use_existing_report:
            use_existing_report=all((reusable_report.artifact_metadata or {}).get(k)==v for k,v in industry_report_inputs.items())
        quality_diagnostic_artifact = None
        report_quality_warning = ''
        if use_existing_report:
            # A stage-level resume must not keep exporting an old report whose
            # model-written source list predates the deterministic audit index.
            report = self._prepend_industry_scope_card(project, reusable_report.content)
            report = self._normalize_report_placeholders(report)
            if standardized_type == "industry":
                agent = self._report_agents.get(standardized_type)
                if agent is not None:
                    expected = {idx: title for idx, (title, _) in enumerate(agent.outline, 1)}
                    report = normalize_report_headings(report, expected)
                    report = sanitize_nested_report_chapter_headings(report, expected)
            report = self._append_report_evidence_index(project, report, cleaned, emit=emit)
            report = self._normalize_report_date(report)
            reused_delivery_metadata = {}
            if standardized_type == 'industry':
                project.industry_report_degradations = list((reusable_report.artifact_metadata or {}).get('generation_degradations') or [])
                report, reused_delivery_metadata = self._prepare_industry_delivery(project, report, risk, emit=emit)
                report_quality_warning = reused_delivery_metadata.get('quality_warning', '')
            else:
                if standardized_type == "person":
                    project.person_delivery_diagnostic = (reusable_report.artifact_metadata or {}).get("person_delivery_diagnostic", {})
                    project.person_research_intake = normalized_intake
                    report = self._append_report_evidence_index(project, report, cleaned, emit=emit)
                self._validate_delivery_report(project, report)
            report_artifact = self.save_artifact(
                db,
                project,
                "desktop_report",
                _project_doc_title(project, "行业研究报告" if standardized_type == "industry" else "背景调查报告") + ('（待复核稿）' if report_quality_warning else ''),
                report,
                {"agent": "report_writer", "reexported_from_artifact_id": reusable_report.id, "report_pipeline_version": report_pipeline_version,
                 **industry_report_inputs,"delivery_status": "final_candidate", **reused_delivery_metadata},
            )
            _emit(emit, "report", "desktop_report_agent", "阶段级续跑：复用报告正文并重新检查交付状态、导出 Word", f"from_artifact_id={reusable_report.id}, new_artifact_id={report_artifact.id}", artifact_id=report_artifact.id, status="done")
        else:
            _emit(emit, "report", "desktop_report_agent", "开始生成桌面研究报告", "", status="running")
            if standardized_type == 'industry':
                project.industry_report_degradations = []
            try:
                report = self.generate_report(project, cleaned, risk, emit=emit, intake=normalized_intake)
            except Exception as exc:
                db.rollback()
                if os.getenv("REPORT_TEMPLATE_FALLBACK_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}:
                    _emit(emit, "report", "desktop_report_agent", "报告生成失败，使用模板降级生成", str(exc), status="fallback")
                    report = self._fallback_report(project, cleaned, risk)
                    if standardized_type == 'industry':
                        project.industry_report_degradations = list(getattr(project, 'industry_report_degradations', []) or []) + [
                            {'chapter': None, 'message': '报告生成异常，使用模板事实摘录；综合判断需人工复核。'}]
                else:
                    _emit(emit, "report", "desktop_report_agent", "报告生成失败", str(exc), status="error")
                    raise
            report = self._consolidate_report_verification_gaps(
                report,
                emit=emit,
                target_type=standardized_type,
            )
            report = self._prepend_industry_scope_card(project, report)
            report = self._append_professional_evidence_assets(project, report, cleaned, emit=emit)
            report = self._normalize_report_placeholders(report)
            # Normalize chapter heading format before evidence-index building and
            # quality-gate validation.  LLM section writers and batch editors can
            # produce ``# N.``, ``## N:``, ``## N -`` and other variants that
            # would silently break the downstream regex-based parsers.
            if standardized_type in {"company", "person", "industry"}:
                agent = self._report_agents.get(standardized_type)
                if agent is not None:
                    expected = {idx: title for idx, (title, _) in enumerate(agent.outline, 1)}
                    report = normalize_report_headings(report, expected)
                    report = sanitize_nested_report_chapter_headings(report, expected)
            report = self._append_report_evidence_index(project, report, cleaned, emit=emit)
            report = self._normalize_report_date(report)
            report_quality_warning = ""
            industry_delivery_metadata = {}
            if standardized_type == 'industry':
                report, industry_delivery_metadata = self._prepare_industry_delivery(project, report, risk, emit=emit)
                report_quality_warning = industry_delivery_metadata.get('quality_warning', '')
            else:
                try:
                    self._validate_delivery_report(project, report)
                except RuntimeError as exc:
                    if os.getenv("REPORT_SAVE_REVIEW_DRAFT_ON_GATE_FAIL", "true").strip().lower() not in {"1", "true", "yes", "on"}:
                        raise
                    report_quality_warning = str(exc)
                    _emit(emit, 'report', 'desktop_report_agent', '报告交付质量闸门未通过，已保存待复核稿', report_quality_warning, status='fallback')
                    report = self._prepend_review_draft_notice(report, report_quality_warning)
            report_artifact = self.save_artifact(
                db,
                project,
                "desktop_report",
                _project_doc_title(project, "行业研究报告" if standardized_type == "industry" else "背景调查报告") + ("（待复核稿）" if report_quality_warning else ""),
                report,
                {
                    "agent": "report_writer",
                    "report_pipeline_version": report_pipeline_version,
                    **({"person_template_version": PERSON_TEMPLATE_VERSION,
                        "person_delivery_diagnostic": getattr(project, "person_delivery_diagnostic", {}),
                        "person_platform_attempts": getattr(project, "person_platform_attempts", [])}
                       if standardized_type == "person" else {}),
                    **({"company_summary_diagnostic": getattr(project, "company_summary_diagnostic", {}),
                        "company_summary_evidence": getattr(project, "company_summary_package", {}),
                        "company_professional_platform_attempts": getattr(project, "company_professional_platform_attempts", [])}
                       if standardized_type == "company" else {}),
                    **({"company_governance_diagnostic": getattr(project, "company_governance_diagnostic", {})}
                       if standardized_type == "company" else {}),
                    **({"company_governance_evidence": getattr(project, "company_governance_package", {})}
                       if standardized_type == "company" else {}),
                    **({"company_history_diagnostic": getattr(project, "company_history_diagnostic", {}),
                        "company_history_evidence": getattr(project, "company_history_package", {})}
                       if standardized_type == "company" else {}),
                    **({"company_operations_diagnostic": getattr(project, "company_operations_diagnostic", {}),
                        "company_operations_evidence": getattr(project, "company_operations_package", {})}
                       if standardized_type == "company" else {}),
                    **({"company_reputation_diagnostic": getattr(project, "company_reputation_diagnostic", {}),
                        "company_reputation_evidence": getattr(project, "company_reputation_package", {})}
                       if standardized_type == "company" else {}),
                    **({"company_business_diagnostic": getattr(project, "company_business_diagnostic", {}),
                        "company_business_evidence": getattr(project, "company_business_package", {})}
                       if standardized_type == "company" else {}),
                    **({"company_management_diagnostic": getattr(project, "company_management_diagnostic", {}),
                        "company_management_evidence": getattr(project, "company_management_package", {})}
                       if standardized_type == "company" else {}),
                    **({"company_people_diagnostic": getattr(project, "company_people_diagnostic", {}),
                        "company_people_evidence": getattr(project, "company_people_package", {})}
                       if standardized_type == "company" else {}),
                    **({"company_judicial_diagnostic": getattr(project, "company_judicial_diagnostic", {}),
                        "company_judicial_evidence": getattr(project, "company_judicial_package", {})}
                       if standardized_type == "company" else {}),
                    **({"company_diligence_diagnostic": getattr(project, "company_diligence_diagnostic", {}),
                        "company_diligence_evidence": getattr(project, "company_diligence_package", {})}
                       if standardized_type == "company" else {}),
                    **({"company_risk_register_diagnostic": getattr(project, "company_risk_register_diagnostic", {}),
                        "company_risk_register_evidence": getattr(project, "company_risk_register_package", {})}
                       if standardized_type == "company" else {}),
                    **({"company_assessment_diagnostic": getattr(project, "company_assessment_diagnostic", {}),
                        "company_assessment_evidence": getattr(project, "company_assessment_package", {})}
                       if standardized_type == "company" else {}),
                    **industry_report_inputs,
                    **industry_delivery_metadata,
                    "delivery_status": "review_draft" if report_quality_warning else "final_candidate",
                    **({"quality_warning": report_quality_warning} if report_quality_warning else {}),
                },
            )
            _emit(emit, "report", "desktop_report_agent", "桌面研究报告已生成", "", status="done")
        if report_quality_warning:
            quality_diagnostic_artifact = self.save_artifact(
                db, project, 'report_quality_diagnostic', _project_doc_title(project, '报告质量诊断'),
                self._build_report_quality_diagnostic(project, report, report_quality_warning),
                {'agent': 'report_quality_gate', 'report_artifact_id': report_artifact.id, 'quality_warning': report_quality_warning,
                 **({'delivery_review_reasons': (report_artifact.artifact_metadata or {}).get('delivery_review_reasons', [])} if standardized_type == 'industry' else {})})
        claim_artifact=None
        if standardized_type=='industry':
            try:
                from .industry_evidence import claim_ledger, VERSION
            except ImportError:
                from industry_evidence import claim_ledger, VERSION
            payload=_plain_json(cleaned) or {}
            dependencies={'cleaned_artifact_id':cleaned_artifact.id,'risk_artifact_id':risk_artifact.id,
                'report_artifact_id':report_artifact.id,'intake_fingerprint':intake_fingerprint,
                'report_sha256':hashlib.sha256(report.encode()).hexdigest(),
                'cleaned_sha256':hashlib.sha256(cleaned.encode()).hexdigest(),
                'risk_sha256':hashlib.sha256(risk.encode()).hexdigest(),
                'cleaning_version':cleaning_pipeline_version,'report_version':report_pipeline_version}
            ledger=claim_ledger(report,payload.get('facts',[]),getattr(project,'industry_delivery_diagnostic',{}),
                payload.get('evidence_coverage') or {},dependencies)
            claim_artifact=self.save_artifact(db,project,'industry_claim_ledger',_project_doc_title(project,'结论证据台账'),
                json.dumps(ledger,ensure_ascii=False,indent=2),{'agent':'industry_evidence_audit',
                    'evidence_contract_version':VERSION,**dependencies,**ledger['summary']})
            report_artifact.artifact_metadata={**(report_artifact.artifact_metadata or {}),
                'claim_ledger_artifact_id':claim_artifact.id,'claim_reference_summary':ledger['summary']}
        if standardized_type == "person":
            diagnostic = getattr(project, "person_delivery_diagnostic", {}) or {}
            dependencies = {"cleaned_artifact_id": cleaned_artifact.id, "risk_artifact_id": risk_artifact.id,
                            "report_artifact_id": report_artifact.id, "template_version": PERSON_TEMPLATE_VERSION,
                            "report_sha256": hashlib.sha256(report.encode()).hexdigest()}
            contract = getattr(project, "person_evidence_contract", {}) or {}
            claim_artifact = self.save_artifact(db, project, "person_claim_ledger", _project_doc_title(project, "人物逐章证据与验收台账"),
                json.dumps({**dependencies, "diagnostic": diagnostic, "facts": contract.get("facts", []),
                            "rejected_facts": contract.get("rejected", []),
                            "platform_attempts": getattr(project, "person_platform_attempts", [])}, ensure_ascii=False, indent=2),
                dependencies)
            report_artifact.artifact_metadata = {**(report_artifact.artifact_metadata or {}),
                "person_claim_ledger_artifact_id": claim_artifact.id, "person_delivery_diagnostic": diagnostic}
        checkpoint("report")

        artifacts = [plan_artifact, quality_artifact, cleaned_artifact, risk_artifact, report_artifact]
        if claim_artifact is not None:
            artifacts.append(claim_artifact)
        if quality_diagnostic_artifact is not None:
            artifacts.append(quality_diagnostic_artifact)
        if generate_proposal:
            project.status = "proposal_generating"
            db.commit()
            existing_proposal = self._latest_artifact(project, "proposal")
            if resume_enabled and use_existing_report and existing_proposal is not None:
                proposal_artifact = self.save_artifact(
                    db,
                    project,
                    "proposal",
                    _project_doc_title(project, "项目建议书"),
                    existing_proposal.content,
                    {"agent": "proposal_writer", "reexported_from_artifact_id": existing_proposal.id},
                )
                _emit(emit, "proposal", "proposal_agent", "阶段级续跑：复用项目建议书并重新导出 Word", f"from_artifact_id={existing_proposal.id}, new_artifact_id={proposal_artifact.id}", artifact_id=proposal_artifact.id, status="done")
            else:
                _emit(emit, "proposal", "proposal_agent", "开始生成项目建议书", "", status="running")
                try:
                    proposal = self.generate_proposal(project, report, risk, emit=emit)
                except Exception as exc:
                    db.rollback()
                    _emit(emit, "proposal", "proposal_agent", "建议书生成失败，使用模板降级生成", str(exc), status="fallback")
                    proposal = self._fallback_proposal(project, report)
                proposal = self._normalize_proposal_placeholders(proposal)
                proposal_quality_warning = self._proposal_quality_warning(proposal, target_type=standardized_type)
                if proposal_quality_warning:
                    _emit(
                        emit,
                        "proposal",
                        "proposal_agent",
                        "建议书质量校验未通过，使用完整模板补齐",
                        proposal_quality_warning,
                        status="fallback",
                    )
                    proposal = self._fallback_proposal(project, report)
                proposal_artifact = self.save_artifact(
                    db,
                    project,
                    "proposal",
                    _project_doc_title(project, "背景调查建议书"),
                    proposal,
                    {"agent": "proposal_writer", "quality_warning": proposal_quality_warning} if proposal_quality_warning else {"agent": "proposal_writer"},
                )
                _emit(emit, "proposal", "proposal_agent", "项目建议书已生成", "", status="done")
            artifacts.append(proposal_artifact)

        project.status = "completed"
        project.updated_at = datetime.utcnow()
        db.commit()
        self._finalize_source_records(db, project, emit)
        _emit(emit, "done", "workflow", "工作流完成", "", status="done")
        return artifacts, sources_added

    def _finalize_source_records(self, db, project, emit=None):
        try:
            from source_retention import finalize_web_sources
            count = finalize_web_sources(db, project, research_store)
            _emit(emit, 'retention', 'source_records', '来源记录已保留，临时网页正文已清理',
                  f'count={count}', status='done')
        except Exception:
            db.rollback()
            _emit(emit, 'retention', 'source_records', '临时正文清理未完成，来源记录仍可用', '', status='warning')

    def _latest_artifact(self, project: ResearchProject, artifact_type: str) -> ResearchArtifact | None:
        session = object_session(project)
        if session is not None:
            return (
                session.query(ResearchArtifact)
                .filter(ResearchArtifact.project_id == project.id, ResearchArtifact.artifact_type == artifact_type)
                .order_by(ResearchArtifact.version.desc(), ResearchArtifact.created_at.desc())
                .first()
            )
        artifacts = [item for item in (project.artifacts or []) if item.artifact_type == artifact_type]
        if not artifacts:
            return None
        return sorted(artifacts, key=lambda item: (item.version or 0, item.created_at), reverse=True)[0]

    def _latest_quality_artifact(self, project: ResearchProject, artifact_type: str) -> ResearchArtifact | None:
        session = object_session(project)
        if session is not None:
            artifacts = (
                session.query(ResearchArtifact)
                .filter(ResearchArtifact.project_id == project.id, ResearchArtifact.artifact_type == artifact_type)
                .order_by(ResearchArtifact.version.desc(), ResearchArtifact.created_at.desc())
                .all()
            )
        else:
            artifacts = sorted(
                [item for item in (project.artifacts or []) if item.artifact_type == artifact_type],
                key=lambda item: (item.version or 0, item.created_at),
                reverse=True,
            )
        for artifact in artifacts:
            metadata = artifact.artifact_metadata or {}
            if not metadata.get("quality_warning"):
                return artifact
        return None

    def _project_has_structured_sources(self, project: ResearchProject) -> bool:
        for source in project.sources or []:
            if self._is_structured_professional_source(source) and self._structured_source_is_safe(source):
                return True
        return False

    def _structured_source_is_safe(self, source: ResearchSource) -> bool:
        """Keep historical mismatched platform rows out of a re-run's evidence set."""
        meta = source.source_metadata or {}
        if not self._is_structured_professional_source(source):
            return True
        if str(meta.get("entity_validation") or "").lower() == "rejected":
            return False
        if str(meta.get("entity_validation") or "").lower() == "related_entity_context":
            return True
        ok, _reason = self._structured_entity_matches_request(source.content or source.summary or "", meta, None)
        return ok

    def _is_structured_professional_source(self, source: ResearchSource) -> bool:
        meta = source.source_metadata or {}
        provider = str(meta.get("provider") or "").lower()
        content_kind = str(meta.get("content_kind") or "")
        url = str(source.url or "")
        if url.startswith("structured://"):
            return True
        if content_kind.startswith("structured_data") and provider in {"qcc", "qcc_company", "qcc_risk", "qcc_operation", "qcc_ipr", "tyc", "xiniu"}:
            return True
        return False

    def _normalize_intake(
        self,
        project: ResearchProject,
        intake: dict[str, Any],
        search_queries: list[str],
        focus_questions: list[str],
    ) -> dict[str, Any]:
        modules = intake.get("focus_modules") or []
        if isinstance(modules, str):
            modules = [item.strip() for item in re.split(r"[,锛孿n]", modules) if item.strip()]
        target_name = (intake.get("company_name") or intake.get("target_name") or project.target_name or project.title).strip()
        industry = (intake.get("industry") or project.industry or "").strip()
        industry_requested = str(intake.get("target_type") or project.target_type or "").lower() in {"industry", "sector", "market", "行业", "赛道", "目标行业"}
        if not industry_requested and self._looks_like_industry_name(target_name, industry):
            inferred_target = self._target_from_project_title(project.title)
            if inferred_target:
                target_name = inferred_target
        target_type = self._standardize_target_type(project, intake, target_name)
        strategy = get_research_strategy(target_type)
        modules = modules or strategy.default_modules or DEFAULT_RESEARCH_MODULES
        if target_type == "person":
            # Project copies are often suffixed with 1/2, but that version marker must not enter person queries.
            target_name = re.sub(r"(?<=[A-Za-z\u4e00-\u9fff])\d+$", "", target_name).strip()
            title_target = self._target_from_project_title(project.title)
            # Users sometimes prefix a well-known person's name with a company shorthand
            # (for example, "阿里马云").  The project title is the safer canonical name
            # when its cleaned value is contained in that form; otherwise every normal
            # page mentioning only "马云" is rejected by the identity gate.
            if (
                title_target
                and title_target != target_name
                and re.sub(r"\s+", "", title_target).lower() in re.sub(r"\s+", "", target_name).lower()
                and not any(term in title_target for term in ("人物", "个人", "尽调", "调查", "项目"))
            ):
                target_name = title_target
        normalized = {
            "project_title": project.title,
            "client_name": (intake.get("client_name") or "").strip(),
            "deadline": (intake.get("deadline") or "").strip(),
            "target_name": target_name,
            "target_type": target_type,
            "official_identifier": (intake.get("official_identifier") or "").strip(),
            "affiliation": (intake.get("affiliation") or "").strip(),
            "identity_anchors": (intake.get("identity_anchors") or "").strip(),
            "focus_entities": (intake.get("focus_entities") or "").strip(),
            "industry": industry,
            "region": (intake.get("region") or "").strip(),
            "research_type": (intake.get("research_type") or "鍟嗕笟灏借皟").strip(),
            "focus_modules": modules,
            "ai_search_enabled": bool(intake.get("ai_search_enabled", FIXED_AI_SEARCH_ENABLED)),
            "special_requirements": (intake.get("special_requirements") or project.description or "").strip(),
            "search_queries": [q.strip() for q in intake.get("search_queries", search_queries) if q.strip()],
            "focus_questions": [q.strip() for q in intake.get("focus_questions", focus_questions) if q.strip()],
            "min_sources_per_module": FIXED_MIN_SOURCES_PER_MODULE,
            "max_search_rounds": FIXED_MAX_SEARCH_ROUNDS,
            "force_refresh_from_upload_ocr": bool(intake.get("force_refresh_from_upload_ocr")),
        }
        if target_type == "person":
            normalized["person_aliases"] = [str(a).strip() for a in intake.get("person_aliases", []) if str(a).strip()][:12]
            normalized["as_of_date"] = str(intake.get("as_of_date") or "").strip()
            normalized["affiliation_raw"] = normalized["affiliation"]
            normalized["person_context"] = str(intake.get("person_context") or "").strip()
            normalized["uploaded_identity_clues"] = list(intake.get("uploaded_identity_clues") or [])
            normalized["affiliations"] = identity_affiliations(normalized["affiliation_raw"])
            if normalized["affiliations"]:
                # Keep each related entity as an independent structured-data
                # target.  Downstream collectors should see "阿里巴巴、蚂蚁集团、
                # 菜鸟网络" as three one-hop subjects, never as one company name.
                normalized["affiliation"] = "、".join(normalized["affiliations"])
            normalized["person_anchor"] = self._build_person_anchor(normalized)
        if target_type == "industry":
            try:
                from .research_strategies.industry import INDUSTRY_MODULE_ALIASES
            except ImportError:
                from research_strategies.industry import INDUSTRY_MODULE_ALIASES
            normalized["focus_modules"] = list(dict.fromkeys(INDUSTRY_MODULE_ALIASES.get(m, m) for m in modules))
            normalized.update({key: intake.get(key, default) for key, default in {"industry_focus": "", "industry_segments": [], "excluded_segments": [], "research_purpose": "", "include_capital_markets": None, "as_of_date": ""}.items()})
            normalized["industry_scope"] = self._resolve_industry_scope(project, normalized, intake)
            normalized["as_of_date"] = normalized["industry_scope"]["as_of_date"]
            normalized["region"] = normalized["industry_scope"]["geography"]
        return normalized

    def _build_person_anchor(self, intake: dict[str, Any]) -> dict[str, Any]:
        return build_identity_anchor(intake)

    def _refresh_person_source_identities(self, project, intake):
        """A changed employer or biography cannot inherit an old namesake match."""
        fingerprint = self._intake_evidence_fingerprint(intake)
        anchor = intake.get("person_anchor") or {}
        contextual = bool(anchor.get("known_affiliations") or anchor.get("identity_anchors"))
        for source in list(getattr(project, "sources", []) or []):
            meta = dict(source.source_metadata or {})
            previous = meta.get("person_intake_fingerprint")
            if previous == fingerprint:
                continue
            if (str(source.url or "").startswith(("http://", "https://")) or source.source_type in {"upload", "manual"}) and source.content and (previous or contextual):
                identity = self._person_source_identity_confidence(source.title or "", source.content, intake)
                meta.update(identity_confidence=identity["confidence"], identity_reason=identity["reason"],
                            identity_status="accepted" if identity["confidence"] in {"high", "medium"} else "quarantined",
                            identity_policy_version=PERSON_IDENTITY_POLICY_VERSION)
            elif (previous and previous != fingerprint) or (not previous and str(source.url or "").startswith("structured://")):
                meta.update(identity_confidence="low", identity_status="quarantined",
                            identity_reason="身份上下文已变更，旧记录需重新核对原件及人物归属")
            meta["person_intake_fingerprint"] = fingerprint
            source.source_metadata = meta

    def _intake_evidence_fingerprint(self, intake: dict[str, Any]) -> str:
        if str(intake.get("target_type") or "").lower() == "industry":
            return scope_fingerprint(intake)
        anchor = intake.get("person_anchor") if isinstance(intake.get("person_anchor"), dict) else {}
        payload = {
            "target_type": str(intake.get("target_type") or "").lower(),
            "target_name": re.sub(r"\s+", "", str(intake.get("target_name") or "")).lower(),
            "affiliations": [
                re.sub(r"\s+", "", str(item or "")).lower()
                for item in (
                    anchor.get("known_affiliations")
                    or intake.get("affiliations")
                    or self._person_affiliation_anchors(str(intake.get("affiliation") or ""))
                )
                if str(item or "").strip()
            ],
            "identity_policy": PERSON_IDENTITY_POLICY_VERSION
            if str(intake.get("target_type") or "").lower() == "person"
            else "",
            **({"person_aliases": anchor.get("aliases", []), "person_anchor": anchor, "as_of_date": intake.get("as_of_date", "")}
               if str(intake.get("target_type") or "").lower() == "person" else {}),
        }
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]

    def _active_industry_sources(self, project: ResearchProject) -> list[ResearchSource]:
        sources = list(getattr(project, "sources", []) or [])
        fingerprint = getattr(project, "industry_scope_fingerprint", "")
        if str(project.target_type or "").lower() == "industry" and fingerprint:
            return [s for s in sources if source_in_current_run(s, fingerprint)]
        return sources

    def _project_sources_match_intake(self, project: ResearchProject, intake: dict[str, Any]) -> bool:
        target_type = str(intake.get("target_type") or project.target_type or "").lower()
        sources = list(getattr(project, "sources", []) or [])
        if not sources or any((s.source_metadata or {}).get("retention_policy") == "record_only" for s in sources):
            return False
        if target_type == "industry":
            fingerprint = scope_fingerprint(intake, source_only=True)
            automated = [s for s in sources if s.source_type not in {"upload", "manual"}
                         and (s.source_metadata or {}).get("stage") not in {"initial_upload", "human_review", "second_stage"}]
            return any(source_in_current_run(s, fingerprint) for s in automated)
        if target_type != "person":
            return True
        target = re.sub(r"\s+", "", str(intake.get("target_name") or project.target_name or "")).lower()
        anchor = intake.get("person_anchor") if isinstance(intake.get("person_anchor"), dict) else {}
        affiliations = [
            re.sub(r"\s+", "", str(item or "")).lower()
            for item in (anchor.get("known_affiliations") or [])
            if str(item or "").strip()
        ]
        current_policy = 0
        target_hits = 0
        anchored_hits = 0
        for source in sources:
            meta = source.source_metadata or {}
            if meta.get("identity_policy_version") == PERSON_IDENTITY_POLICY_VERSION:
                current_policy += 1
            blob = re.sub(r"\s+", "", f"{source.title or ''} {source.summary or ''} {(source.content or '')[:2000]}").lower()
            if target and target in blob:
                target_hits += 1
                if not affiliations or any(anchor and anchor in blob for anchor in affiliations):
                    anchored_hits += 1
        return current_policy >= max(3, min(20, len(sources) // 10)) and target_hits >= 8 and anchored_hits >= 3

    def _resolve_industry_scope(self, project: ResearchProject, normalized: dict[str, Any], raw_intake: dict[str, Any]) -> dict[str, Any]:
        return normalize_scope(project, normalized, raw_intake)

    def _looks_like_industry_name(self, value: str, industry: str = "") -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        if industry and text == str(industry).strip():
            return True
        industry_terms = ["行业", "服务业", "制造业", "产业", "市场", "赛道", "领域"]
        company_terms = ["公司", "集团", "有限", "股份", "科技", "硅基流动", "SiliconFlow"]
        if any(term in text for term in company_terms) and not text.endswith("服务业"):
            return False
        return any(term in text for term in industry_terms)

    def _target_from_project_title(self, title: str) -> str:
        text = str(title or "").strip()
        text = re.sub(r"(背景调查|尽职调查|桌面研究|研究报告|报告|建议书)$", "", text).strip()
        text = re.sub(r"[\s_-]*(v?\d+(?:\.\d+)*)$", "", text, flags=re.I).strip()
        return text if len(text) >= 2 else ""

    def _prepare_structured_entity_intake(
        self,
        project: ResearchProject,
        intake: dict[str, Any],
        emit: TraceEmitter | None = None,
    ) -> dict[str, Any]:
        prepared = dict(intake or {})
        target_type = str(prepared.get("target_type") or project.target_type or "company").lower()
        target = str(prepared.get("target_name") or project.target_name or project.title or "").strip()
        if target_type == "industry":
            return prepared
        if target_type == "person":
            affiliation = str(prepared.get("affiliation") or "").strip()
            company_match = re.search(
                r"[\u4e00-\u9fffA-Za-z0-9（）()·]{2,60}(?:股份有限公司|有限责任公司|有限公司|集团)",
                affiliation,
            )
            # A person intake commonly contains a brand/short company name (for example
            # "阿里巴巴") rather than a registered legal name.  It is still an explicit
            # user-supplied search anchor and the professional platforms can resolve it.
            # Previously only names with a legal suffix were accepted, so the value the
            # user entered was silently discarded before structured collection.
            affiliation_anchors = self._person_affiliation_anchors(affiliation)
            associated_company = (
                company_match.group(0).strip()
                if company_match
                else (affiliation_anchors[0] if affiliation_anchors else "")
            )
            role_only_terms = {"创始人", "董事长", "董事", "总经理", "高管", "员工", "合伙人", "CEO", "COO", "CTO", "CFO"}
            if len(associated_company) < 2 or associated_company in role_only_terms:
                _emit(
                    emit,
                    "entity_resolution",
                    "business_entity_agent",
                    "人物关联企业未确认，跳过工商主体采集",
                    target,
                    status="skipped",
                )
                return prepared
            candidate_intake = dict(prepared)
            candidate_intake.update({"target_name": associated_company, "company_name": associated_company})
            candidates = self._structured_entity_candidates(project, candidate_intake, associated_company)
            person_key = re.sub(r"\s+", "", target)
            candidates = [item for item in candidates if re.sub(r"\s+", "", item) != person_key]
        else:
            associated_company = ""
            candidates = self._structured_entity_candidates(project, prepared, target)
        if candidates:
            prepared["structured_target_candidates"] = candidates
            prepared["structured_target"] = candidates[0]
            prepared["canonical_company_name"] = candidates[0]
            if target_type == "company":
                prepared["company_name"] = candidates[0]
                project.target_name = candidates[0]
            else:
                prepared["associated_company"] = candidates[0]
                prepared["person_affiliation_context"] = {
                    "person_name": target,
                    "affiliation_name": associated_company,
                    "canonical_company_name": candidates[0],
                    "relationship_type": "用户提供或检索确认的直接关联主体",
                    "relationship_evidence_source_ids": [],
                    "relationship_evidence_hosts": [],
                    "relationship_confidence": "medium",
                    "recursion_depth": 0,
                    "selection_rank": 0,
                    "selection_reason": "人物项目显式关联主体，用于专业平台结构化采集。",
                    "filtering_note": "关联企业层面事实只能作为人物报告间接证据，不得直接归因为个人信用、违法或操守结论。",
                }
            _emit(
                emit,
                "entity_resolution",
                "business_entity_agent",
                "企业主体锚定完成",
                "；".join(candidates[:5]),
                canonical_company_name=candidates[0],
                person_target=target if target_type == "person" else "",
                candidate_count=len(candidates),
                status="done",
            )
        return prepared

    def _structured_entity_candidates(self, project: ResearchProject, intake: dict[str, Any], target: str) -> list[str]:
        raw_values: list[str] = []
        for value in [
            intake.get("official_identifier"),
            intake.get("canonical_company_name"),
            intake.get("company_name"),
            intake.get("target_name"),
            project.target_name,
            target,
        ]:
            text = str(value or "").strip()
            if text:
                raw_values.append(text)

        haystacks: list[str] = []
        for source in list(getattr(project, "sources", []) or [])[:500]:
            meta = source.source_metadata or {}
            parts = [
                source.title or "",
                source.summary or "",
                source.content or "",
                str(meta.get("ocr_text") or ""),
                str(meta.get("vision_text") or ""),
            ]
            text = "\n".join(part[:8000] for part in parts if part)
            if text:
                haystacks.append(text)

        target_key = re.sub(r"[\s\d.。．_-]+", "", target or "")
        company_suffix = r"(?:有限责任公司|股份有限公司|有限公司|集团有限公司|科技股份有限公司|科技有限公司)"
        for text in haystacks:
            target_pattern = (
                r"[\u4e00-\u9fffA-Za-z0-9（）()·]{0,16}"
                + re.escape(target_key or target)
                + r"[\u4e00-\u9fffA-Za-z0-9（）()·]{0,24}"
                + company_suffix
            )
            for match in re.finditer(target_pattern, text):
                name = self._clean_company_candidate_name(match.group(0))
                if target_key and target_key not in re.sub(r"[\s\d.。．_-]+", "", name):
                    continue
                raw_values.append(name)
            for code in re.findall(r"\b[0-9A-Z]{18}\b", text):
                if re.search(r"[A-Z]", code) and re.search(r"\d", code):
                    raw_values.append(code)

        # Very common brand-name case: public sources often include the registered Beijing entity.
        if target_key == "硅基流动":
            raw_values.extend(["北京硅基流动科技股份有限公司", "北京硅基流动科技有限公司", "91110108MACUTWH50K"])

        def rank(value: str) -> tuple[int, int]:
            if value == "91110108MACUTWH50K":
                return (119, 0)
            if re.fullmatch(r"[0-9A-Z]{18}", value):
                return (95, 0)
            if value in {str(intake.get("canonical_company_name") or ""), "北京硅基流动科技股份有限公司"}:
                return (120, 0)
            if any(suffix in value for suffix in ["股份有限公司", "有限责任公司", "有限公司"]):
                return (100, -len(value))
            return (10, -len(value))

        seen: set[str] = set()
        cleaned: list[str] = []
        for value in sorted(raw_values, key=rank, reverse=True):
            text = re.sub(r"\s+", "", str(value or "").strip())
            if not text or text in seen:
                continue
            if not re.fullmatch(r"[0-9A-Z]{18}", text) and not self._is_usable_company_anchor(text):
                continue
            if self._looks_like_industry_name(text, str(intake.get("industry") or project.industry or "")):
                continue
            if len(text) < 2:
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned[:8]

    def _is_usable_company_anchor(self, value: str) -> bool:
        """Reject relation-parser fragments such as '管理有限公司'."""
        text = re.sub(r"\s+", "", str(value or "").strip())
        if len(text) < 2:
            return False
        bare = re.sub(r"(?:有限责任公司|股份有限公司|集团有限公司|有限公司)$", "", text)
        if len(bare) < 2:
            return False
        generic = {
            "公司", "企业", "集团", "控股", "投资", "资本", "基金", "管理", "咨询", "科技",
            "服务", "网络", "商业", "资产", "管理有限", "咨询有限", "投资有限", "科技有限",
        }
        return bare not in generic

    def _clean_company_candidate_name(self, value: str) -> str:
        text = re.sub(r"\s+", "", str(value or "").strip())
        location_match = re.search(
            r"(?:北京|上海|天津|重庆|深圳市|长沙|杭州|广州|南京|苏州|成都|武汉|西安)"
            r"[\u4e00-\u9fffA-Za-z0-9（）()·]{1,40}"
            r"(?:有限责任公司|股份有限公司|有限公司|集团有限公司|科技股份有限公司|科技有限公司)",
            text,
        )
        if location_match:
            text = location_match.group(0)
        for marker in ["更名为", "为您提供", "了解", "主体为", "公司为", "全称为", "查询", "是"]:
            if marker in text:
                text = text.split(marker)[-1]
        text = re.sub(r"^(成立仅?\d*个?月?的|成立于?\d*年?的|目标公司|公司主体|被投企业|简称|更好地对)", "", text)
        text = text.strip("：:，,。；;()（）[]【】")
        bad_connectors = ["与", "和", "及", "、", "以及", "联合"]
        if any(connector in text for connector in bad_connectors) or not self._is_usable_company_anchor(text):
            return ""
        return text

    def _invoke_cleaning_fallback_model(self, prompt: str, emit: TraceEmitter | None = None) -> str:
        """Optionally route blocked cleaning batches to a separately configured compliant model."""
        model_name = os.getenv("CLEANING_FALLBACK_MODEL", "").strip()
        api_key = os.getenv("CLEANING_FALLBACK_API_KEY", "").strip() or os.getenv("ARK_API_KEY", "").strip()
        base_url = os.getenv("CLEANING_FALLBACK_BASE_URL", "").strip() or os.getenv("BASE_URL", "").strip()
        if not model_name or not api_key:
            return ""
        if getattr(self, "_cleaning_fallback_model", None) is None:
            self._cleaning_fallback_model = init_chat_model(
                model=model_name,
                model_provider="openai",
                api_key=api_key,
                base_url=base_url,
                temperature=0.1,
                stream_usage=True,
                timeout=_env_int("LLM_TIMEOUT_SECONDS", 120, 10, 600),
                max_retries=1,
            )
        try:
            _emit(emit, "llm", "data_cleaning_fallback_agent", "切换备用清洗模型重试", model_name, status="running")
            result = self._cleaning_fallback_model.invoke(
                [
                    {"role": "system", "content": "你是合规尽调资料的信息抽取工具。客观抽取并保留来源，不作违法认定，不编造事实。"},
                    {"role": "user", "content": prompt},
                ]
            )
            content = str(result.content or "")
            _emit(emit, "llm", "data_cleaning_fallback_agent", "备用清洗模型调用完成", f"chars={len(content)}", status="done")
            return content
        except Exception as exc:
            _emit(emit, "llm", "data_cleaning_fallback_agent", "备用清洗模型调用失败", str(exc), status="fallback")
            return ""

    def _standardize_target_type(self, project: ResearchProject, intake: dict[str, Any], target_name: str = "") -> str:
        raw_type = str(intake.get("target_type") or project.target_type or "").strip().lower()
        research_type = str(intake.get("research_type") or "").strip().lower()
        company_name = str(intake.get("company_name") or "").strip()
        text = " ".join(
            str(value or "")
            for value in [raw_type, research_type, company_name, target_name, project.title, project.description, project.industry]
        ).lower()
        direct_map = {
            "person": "person", "individual": "person", "founder": "person", "people": "person", "个人": "person", "人物": "person", "目标人": "person", "创始人": "person",
            "company": "company", "corp": "company", "corporation": "company", "enterprise": "company", "公司": "company", "企业": "company", "目标公司": "company",
            "industry": "industry", "sector": "industry", "market": "industry", "行业": "industry", "赛道": "industry", "市场": "industry", "目标行业": "industry",
        }
        if raw_type in direct_map:
            return direct_map[raw_type]
        if any(key in text for key in ["industry research", "cdd", "行业", "赛道", "市场规模", "产业链"]):
            return "industry"
        if any(key in text for key in ["person", "individual", "founder", "人物", "个人", "目标人", "创始人", "高管"]):
            return "person"
        return "company"

    def resolve_business_entity(
        self,
        project: ResearchProject,
        intake: dict[str, Any],
        emit: TraceEmitter | None = None,
    ) -> dict[str, Any]:
        resolved = dict(intake or {})
        target_name = (
            str(resolved.get("target_name") or "").strip()
            or str(resolved.get("company_name") or "").strip()
            or (project.target_name or "").strip()
            or (project.title or "").strip()
        )
        industry = str(resolved.get("industry") or project.industry or "").strip()
        if self._standardize_target_type(project, resolved, target_name) == "industry":
            resolved.update(target_name=target_name, company_name="", target_type="industry", industry=industry or target_name)
            project.target_name = target_name
            project.target_type = "industry"
            project.industry = industry or target_name
            return resolved
        if self._looks_like_industry_name(target_name, industry):
            inferred_target = self._target_from_project_title(project.title)
            if inferred_target:
                target_name = inferred_target
        target_type = self._standardize_target_type(project, resolved, target_name)
        company_name = str(resolved.get("company_name") or target_name).strip()
        if target_type == "person":
            # The frontend historically sends the person's name in company_name. Keep it as
            # the person target; only affiliation/associated_company may drive company lookup.
            company_name = str(resolved.get("associated_company") or "").strip()
        if self._looks_like_industry_name(company_name, industry):
            company_name = target_name

        resolved.update(
            {
                "target_name": target_name,
                "company_name": company_name,
                "target_type": target_type,
                "industry": industry,
            }
        )
        project.target_name = target_name
        project.target_type = target_type
        if industry:
            project.industry = industry
        _emit(
            emit,
            "entity_resolution",
            "business_entity_agent",
            "研究对象已规范化",
            target_name,
            target_type=target_type,
            status="done",
        )
        return resolved

    def plan_research(self, project: ResearchProject, intake: dict[str, Any], emit: TraceEmitter | None = None) -> dict[str, Any]:
        target = intake.get("target_name") or project.target_name or project.title
        industry = intake.get("industry") or project.industry
        strategy = get_research_strategy(str(intake.get("target_type") or project.target_type or "company"))
        modules = intake.get("focus_modules") or strategy.default_modules or DEFAULT_RESEARCH_MODULES
        if intake.get("target_type") == "industry":
            modules = list(modules)
            if (intake.get("industry_scope") or {}).get("capital_market") == "none":
                modules = [m for m in modules if m != "投融资与资本市场"]
            if (intake.get("industry_scope") or {}).get("named_companies") and "核心企业尽调" not in modules:
                modules.append("核心企业尽调")
            elif not (intake.get("industry_scope") or {}).get("named_companies"):
                modules = [m for m in modules if m != "核心企业尽调"]
        plan = {
            "target_name": target,
            "client_name": intake.get("client_name", ""),
            "deadline": intake.get("deadline", ""),
            "research_type": intake.get("research_type", "鍟嗕笟灏借皟"),
            "region": intake.get("region", ""),
            "official_identifier": intake.get("official_identifier", ""),
            "industry": industry,
            "modules": [],
            "coverage_thresholds": {
                "min_sources_per_module": intake.get("min_sources_per_module", FIXED_MIN_SOURCES_PER_MODULE),
                "require_authoritative_source": True,
                "require_ocr_for_images": True,
            },
            "special_requirements": intake.get("special_requirements", ""),
            "industry_scope": intake.get("industry_scope", {}),
        }
        for module in modules:
            templates = strategy.templates_for_module(module, target, industry)
            plan["modules"].append(
                {
                    "name": module,
                    "research_questions": strategy.module_questions(module, target, industry),
                    "query_templates": templates,
                    "required_source_types": strategy.required_source_types(module),
                }
            )
        if intake.get("target_type") == "person":
            plan["person_template_version"] = PERSON_TEMPLATE_VERSION
            plan["identity_anchor"] = intake.get("person_anchor") or {}
            plan["person_evidence_requirements"] = person_retrieval_coverage([], intake)["chapters"]
            plan["chapter_research_tasks"] = [
                {"chapter": i, "title": title, "requirements": requirements,
                 "scope": "actual_citations" if i == 14 else "verification_plan" if i == 15 else "evidence_bound"}
                for i, (title, requirements) in enumerate(PersonReportAgent.outline, 1)]
        if intake.get('target_type') == 'industry':
            try:
                from .industry_evidence import evidence_requirements, VERSION
            except ImportError:
                from industry_evidence import evidence_requirements, VERSION
            plan['evidence_contract_version'] = VERSION
            plan['evidence_requirements'] = evidence_requirements(plan['modules'],intake.get('industry_scope') or {})
        _emit(emit, "planning", "research_planning_agent", "研究计划生成完成", "", status="done")
        return plan

    def _person_affiliation_anchors(self, value: str) -> list[str]:
        """Normalize optional, multi-value person affiliations for search and disambiguation."""
        return get_research_strategy("person").normalize_affiliations(value)

    def _expand_search_queries(self, plan: dict[str, Any], intake: dict[str, Any]) -> list[dict[str, str]]:
        return get_research_strategy(str(intake.get("target_type") or "company")).expand_search_queries(plan, intake)

    def _search_query_items_parallel(
        self,
        query_items: list[dict[str, Any]],
        max_results_per_query: int,
        configured_providers: list[str],
        emit: TraceEmitter | None = None,
        pause_requested: Callable[[], bool] | None = None,
    ) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
        if not query_items:
            return []
        concurrency = min(_env_int("WEB_SEARCH_QUERY_CONCURRENCY", 3, 1, 8), len(query_items))
        _emit(
            emit,
            "web_search",
            "online_search_agent",
            "并行调用 WebSearch 工具",
            f"queries={len(query_items)}, concurrency={concurrency}, providers={','.join(configured_providers) or 'no_provider'}",
            query_count=len(query_items),
            concurrency=concurrency,
            providers=configured_providers,
            status="running",
        )

        def search_one(index: int, query_item: dict[str, Any]) -> tuple[int, dict[str, Any], list[dict[str, Any]], str]:
            if pause_requested and pause_requested():
                raise WorkflowPaused("任务已暂停")
            query = query_item["query"]
            try:
                if "person_search_audit_index" in query_item:
                    results = web_search_provider.search_single(
                        query_item["preferred_providers"][0], query,
                        limit=min(max_results_per_query, _env_int("PERSON_SEARCH_RESULTS_PER_QUERY", 6, 1, 12)),
                        include_domains=list(query_item.get("include_domains") or []), category=query_item.get("exa_category"))
                    for item in results:
                        item["metadata"] = {**(item.get("metadata") or {}), "person_discovery_only": True}
                else:
                    results = web_search_provider.search(
                        query, limit=max(1, max_results_per_query),
                        include_domains=list(query_item.get("include_domains") or []),
                        category=query_item.get("exa_category"),
                        preferred_providers=list(query_item.get("preferred_providers") or []))
                query_item["person_search_status"] = "returned" if results else "empty_or_unavailable"
                return index, query_item, results, ""
            except WorkflowPaused:
                raise
            except Exception as exc:
                query_item["person_search_status"] = "failed"
                query_item["person_search_error_type"] = type(exc).__name__
                query_item["person_search_error_reason"] = platform_failure_kind({"error": str(exc)})
                return index, query_item, [], type(exc).__name__

        ordered: list[tuple[int, dict[str, Any], list[dict[str, Any]]]] = []
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(search_one, index, query_item): (index, query_item)
                for index, query_item in enumerate(query_items)
            }
            for future in as_completed(futures):
                index, query_item = futures[future]
                query = str(query_item.get("query") or "")
                module = str(query_item.get("module") or "general")
                if pause_requested and pause_requested():
                    raise WorkflowPaused("任务已暂停")
                try:
                    result_index, result_item, results, error = future.result()
                except WorkflowPaused:
                    raise
                except Exception as exc:
                    result_index, result_item, results, error = index, query_item, [], str(exc)
                if error:
                    _emit(emit, "web_search", "online_search_agent", "在线检索失败", error, query=query, module=module, status="error")
                else:
                    _emit(
                        emit,
                        "web_search",
                        "online_search_agent",
                        "在线检索完成",
                        f"query={query}, results={len(results)}",
                        query=query,
                        module=module,
                        result_count=len(results),
                        status="done",
                    )
                ordered.append((result_index, result_item, results))
        ordered.sort(key=lambda item: item[0])
        return [(query_item, results) for _index, query_item, results in ordered]

    def _gap_queries(self, plan: dict[str, Any], intake: dict[str, Any], gaps: list[str]) -> list[dict[str, str]]:
        if intake.get("target_type") == "industry":
            missing = {str(gap).split("：", 1)[0] for gap in gaps}
            gap_plan = {**plan, "modules": [m for m in plan.get("modules", []) if m.get("name") in missing]}
            if not gap_plan["modules"]:
                return []
            scope = intake.get('industry_scope') or {}
            target = intake.get('target_name') or scope.get('industry_name') or ''
            suffixes = {
                '市场规模与增长': '市场规模 统计口径 数据年度 中国信通院 官方统计',
                '商业模式与盈利逻辑': '商业化 收入结构 盈利模式 毛利率 行业研究 披露',
                '竞争格局与代表企业': '市场份额 CR3 CR5 样本范围 统计年度',
                '技术路线对比': '技术路线 成本 性能 实测 场景 对比',
            }
            rows = [row for row in self._expand_search_queries(gap_plan, intake) if row.get('module') in missing]
            for module in sorted(missing):
                if module in suffixes:
                    rows.insert(0, {'module': module, 'query': f'{target} {scope.get("geography", "")} {suffixes[module]}',
                                    'evidence_scope': 'industry_level', 'industry_name': target,
                                    'search_tier': 'open_web', 'gap_reason': next((gap for gap in gaps if str(gap).startswith(module)), '')})
            requirements = {r['id']:r for r in plan.get('evidence_requirements',[])}
            targeted = []
            for gap in gaps:
                match = re.search(r'\[需求:([^\]]+)\]',str(gap))
                req = requirements.get(match[1]) if match else None
                if req:
                    targeted.append({'module':req['module'],'query':f'{target} {scope.get("geography", "")} {req["query_terms"]}',
                        'search_tier':'open_web','evidence_scope':'industry_level','industry_name':target,
                        'requirement_id':req['id'],'gap_reason':str(gap)})
            generic_missing={str(g).split('：',1)[0] for g in gaps if '[需求:' not in str(g)}
            return (targeted + [r for r in rows if r.get('module') in generic_missing])[:24]
        target = (intake.get("target_name") or "").strip()
        items: list[dict[str, str]] = []
        routes: list[tuple[tuple[str, ...], str, tuple[str, ...]]] = [
            (("融资", "投资方", "估值", "出资"), "融资与资本", ("融资公告 投资方官网", "融资 工商变更", "投资协议 公开披露")),
            (("专利", "商标", "软著", "知识产权"), "知识产权", ("site:cnipa.gov.cn 专利", "专利 申请人 发明人", "商标 软件著作权")),
            (("股东", "实控", "受益人", "股权穿透", "关联企业", "控制权"), "工商穿透", ("国家企业信用信息公示系统 股东", "最终受益人 股权穿透", "工商变更 关联企业")),
            (("备案", "ICP", "算法", "许可", "资质", "网信"), "备案与资质", ("site:beian.miit.gov.cn ICP备案", "网信办 备案 清单", "行政许可 资质")),
            (("处罚", "失信", "被执行", "法院", "裁判", "监管", "税务"), "司法与监管", ("site:creditchina.gov.cn 行政处罚", "法院 被执行 失信", "市场监管 处罚")),
            (("标准", "国标", "行标", "团标", "IEEE", "ISO"), "标准参与", ("全国标准信息公共服务平台", "标准 起草单位", "标准委员会 参与")),
        ]
        offline_only = ("合同", "订单", "回款", "银行流水", "发票", "客户名单", "供应商名单", "员工花名册", "内部测试", "访谈", "现场走访")
        for gap in gaps[:12]:
            gap_text = str(gap or "").strip()
            if not gap_text:
                continue
            if any(keyword in gap_text for keyword in offline_only):
                continue
            matched = False
            for keywords, module, query_suffixes in routes:
                if not any(keyword.lower() in gap_text.lower() for keyword in keywords):
                    continue
                matched = True
                for suffix in query_suffixes:
                    items.append({"module": module, "query": f"{target} {suffix}".strip()})
            if not matched:
                module = gap_text.split("：", 1)[0].replace("缺少", "").strip() or "公开信息补核"
                items.extend([
                    {"module": module, "query": f"{target} {module} 官方 公示".strip()},
                    {"module": module, "query": f"{target} {module} 监管 公开披露".strip()},
                ])
        seen: set[str] = set()
        deduped: list[dict[str, str]] = []
        for item in items:
            key = re.sub(r"\s+", "", item["query"].lower())
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        deduped.sort(key=lambda item: 0 if item.get("search_tier") == "authority_first" else 1)
        return deduped
    def _is_technical_content_source(self, host: str, title: str, content: str, query: str = "") -> bool:
        blob = f"{host} {title} {content[:800]} {query}".lower()
        if host in TECH_CONTENT_DOMAINS:
            return any(term in blob for term in TECH_CONTENT_TERMS) and not any(term in blob for term in DUE_DILIGENCE_TERMS)
        return False

    def _person_source_is_relevant(self, title: str, content: str, intake: dict[str, Any]) -> bool:
        """Reject generic and same-name noise before coverage counting and cleaning."""
        return self._person_source_identity_confidence(title, content, intake)["confidence"] != "rejected"

    def _person_source_identity_confidence(self, title: str, content: str, intake: dict[str, Any]) -> dict[str, Any]:
        """Classify identity evidence without discarding potentially useful new affiliations."""
        if str(intake.get("target_type") or "").lower() != "person":
            return {"confidence": "high", "reason": "非人物项目", "matched_anchors": [], "identity_policy_version": ""}
        raw_target = str(intake.get("target_name") or "").strip()
        target = re.sub(r"\s+", "", raw_target).lower()
        blob = re.sub(r"\s+", "", f"{title} {content[:8000]}").lower()
        aliases = [target]
        latin = re.sub(r"[^A-Za-z ]", "", raw_target).strip()
        chinese = "".join(re.findall(r"[\u4e00-\u9fff]", raw_target))
        if len(re.sub(r"\s+", "", latin)) >= 6:
            aliases.append(re.sub(r"\s+", "", latin).lower())
        if len(chinese) >= 2:
            aliases.append(chinese)
        supplied_names = list((intake.get("person_anchor") or {}).get("aliases") or [raw_target])
        for name in supplied_names:
            aliases.extend(re.sub(r"\s+", "", form).lower() for form in matched_name_forms(name, f"{title} {content[:8000]}"))
        if not target or not any(alias and alias in blob for alias in aliases):
            return {
                "confidence": "rejected",
                "reason": "未命中目标姓名",
                "matched_anchors": [],
                "identity_policy_version": PERSON_IDENTITY_POLICY_VERSION,
            }
        anchor = intake.get("person_anchor") if isinstance(intake.get("person_anchor"), dict) else {}
        anchor_affiliations = list(anchor.get("known_affiliations") or [])
        affiliation = str(intake.get("associated_company") or intake.get("affiliation") or "")
        company_anchors = [
            re.sub(r"\s+", "", item).lower()
            for item in (anchor_affiliations or self._person_affiliation_anchors(affiliation))
        ]
        def near_target(anchor_text: str, window: int = 280) -> bool:
            if not anchor_text:
                return False
            positions = [match.start() for match in re.finditer(re.escape(anchor_text), blob)]
            if not positions:
                return False
            target_positions: list[int] = []
            for alias in aliases:
                if alias:
                    target_positions.extend(match.start() for match in re.finditer(re.escape(alias), blob))
            return any(abs(anchor_pos - target_pos) <= window for anchor_pos in positions for target_pos in target_positions)

        matched_company = [anchor for anchor in company_anchors if near_target(anchor)]
        if matched_company:
            return {
                "confidence": "high",
                "reason": "目标姓名与已知关联机构近邻共现",
                "matched_anchors": matched_company,
                "identity_policy_version": PERSON_IDENTITY_POLICY_VERSION,
            }
        raw_identity_anchors = list(anchor.get("identity_anchors") or [])
        if not raw_identity_anchors:
            raw_identity_anchors = [
                item.strip()
                for item in re.split(r"\s*[/／|｜,，;；]\s*", str(intake.get("identity_anchors") or ""))
                if len(item.strip()) >= 3
            ]
        anchors = [re.sub(r"\s+", "", item).lower() for item in raw_identity_anchors if len(str(item).strip()) >= 2]
        matched_identity = [anchor for anchor in anchors if near_target(anchor)]
        if matched_identity:
            return {
                "confidence": "medium",
                "reason": "命中身份锚点",
                "matched_anchors": matched_identity,
                "identity_policy_version": PERSON_IDENTITY_POLICY_VERSION,
            }
        # A page containing both the full Latin and Chinese names is itself a strong identity anchor.
        if latin and chinese and re.sub(r"\s+", "", latin).lower() in blob and chinese in blob:
            return {
                "confidence": "medium",
                "reason": "中英文姓名同时出现",
                "matched_anchors": [chinese, latin],
                "identity_policy_version": PERSON_IDENTITY_POLICY_VERSION,
            }
        # Affiliation is optional. Without a matching anchor, keep ordinary person pages
        # so the workflow can discover historical and investment relationships itself,
        # but continue rejecting obvious same-name company registry records.
        registry_noise = any(term in blob for term in ("统一社会信用代码", "注册资本", "经营范围", "企业类型"))
        company_title = any(term in re.sub(r"\s+", "", title) for term in ("有限公司", "股份有限公司", "有限责任公司"))
        if registry_noise or company_title:
            return {
                "confidence": "rejected",
                "reason": "疑似同名企业工商记录",
                "matched_anchors": [],
                "identity_policy_version": PERSON_IDENTITY_POLICY_VERSION,
            }
        return {
            "confidence": "low",
            "reason": "仅命中姓名，缺少机构或履历锚点",
            "matched_anchors": [],
            "identity_policy_version": PERSON_IDENTITY_POLICY_VERSION,
        }

    def _discover_person_affiliations(
        self,
        sources: list[ResearchSource],
        intake: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Find relationship candidates for a second search round without promoting them to facts."""
        if str(intake.get("target_type") or "").lower() != "person":
            return []
        target = re.sub(r"\s+", "", str(intake.get("target_name") or ""))
        supplied = {
            re.sub(r"\s+", "", item).lower()
            for item in self._person_affiliation_anchors(
                str(intake.get("affiliation") or intake.get("associated_company") or "")
            )
        }
        relation_pattern = re.compile(
            r"(?P<relation>创办|创立|创建|成立|联合创办|共同创办|发起|投资于?|任职于|就职于|担任|供职于)"
            r"[^。；;，,\n]{0,18}?"
            r"([\u4e00-\u9fffA-Za-z0-9·]{2,24}?(?:股份有限公司|有限责任公司|有限公司|集团|基金|资本|控股))"
        )
        support: dict[str, dict[str, Any]] = {}
        for source in sources:
            text = self._clean_source_text(f"{source.title or ''}\n{source.content or source.summary or ''}")
            compact = re.sub(r"\s+", "", text)
            if target and target not in compact:
                continue
            host = urlparse(source.url or "").netloc.lower().replace("www.", "") or f"source:{source.id}"
            for match in relation_pattern.finditer(text[:12000]):
                # group 1 is the relationship verb (for example "联合创办"); the
                # actual organization is group 2.  Using group 1 caused every QCC/TYC/
                # Xiniu lookup to query the verb instead of the company name.
                candidate = match.group(2).strip("：:，,。；;（）()[]【】\"'“”")
                candidate = re.sub(r"^(?:其|了|的|在|与|和)", "", candidate).strip()
                compact_candidate = re.sub(r"\s+", "", candidate)
                if (
                    len(compact_candidate) < 3
                    or not self._is_usable_company_anchor(candidate)
                    or compact_candidate.lower() in supplied
                    or compact_candidate == target
                    or target and target in compact_candidate
                ):
                    continue
                item = support.setdefault(
                    compact_candidate,
                    {
                        "name": candidate,
                        "source_ids": set(),
                        "hosts": set(),
                        "max_score": 0,
                        "authoritative": False,
                        "medium_high": False,
                        "professional_database": False,
                        "independent_non_database": False,
                        "relation_types": set(),
                    },
                )
                item["source_ids"].add(source.id)
                item["hosts"].add(host)
                item["max_score"] = max(item["max_score"], int(source.credibility_score or 0))
                item["relation_types"].add(match.group("relation"))
                source_type = str(getattr(source, "source_type", "") or "").lower()
                identity = self._person_source_identity_confidence(source.title or "", text, intake)
                if identity["confidence"] in {"high", "medium"}:
                    item["medium_high"] = True
                if source_type == "business_database":
                    item["professional_database"] = True
                else:
                    item["independent_non_database"] = True
                if (
                    host.endswith(".gov.cn")
                    or host.endswith(("hkexnews.hk", "sec.gov", "cninfo.com.cn"))
                    or source_type in {"government", "court", "regulatory", "filing", "official"}
                ):
                    item["authoritative"] = True
        confirmed = [
            {
                "name": item["name"],
                "source_count": len(item["source_ids"]),
                "host_count": len(item["hosts"]),
                "max_score": item["max_score"],
                "relationship_type": "、".join(sorted(item["relation_types"])) or "待由原始证据确认",
                "relationship_evidence_source_ids": sorted(item["source_ids"]),
                "relationship_evidence_hosts": sorted(item["hosts"]),
            }
            for item in support.values()
            if (
                (item["authoritative"] and item["max_score"] >= 80)
                or (len(item["hosts"]) >= 2 and item["medium_high"])
                or (item["professional_database"] and item["independent_non_database"] and len(item["hosts"]) >= 2)
            )
        ]
        confirmed.sort(key=lambda item: (item["host_count"], item["source_count"], item["max_score"]), reverse=True)
        return confirmed[:_env_int("PERSON_DISCOVERED_AFFILIATION_LIMIT", 6, 0, 20)]

    def _person_affiliation_discovery_queries(self, target: str, affiliations: list[str]) -> list[dict[str, str]]:
        return get_research_strategy("person").affiliation_discovery_queries(target, affiliations)

    def _detect_source_type(self, host: str, title: str, url: str) -> str:
        text = f"{host} {title} {url}".lower()
        if any(key in text for key in ["qcc.com", "tianyancha.com", "aiqicha.baidu.com", "qixin.com", "企查查", "天眼查", "爱企查", "启信宝"]):
            return "business_database"
        if any(key in text for key in ["court", "法院", "裁判文书"]):
            return "court"
        if any(key in text for key in ["cninfo.com.cn", "sse.com.cn", "szse.cn", "hkexnews.hk", "sec.gov"]):
            return "filing"
        if any(key in text for key in ["csrc.gov.cn", "pbc.gov.cn", "nfra.gov.cn", "samr.gov.cn", "creditchina.gov.cn"]):
            return "regulatory"
        if any(key in text for key in ["gov.cn", "政府", "监管", "处罚"]):
            return "government"
        if any(key in text for key in ["36kr", "tmtpost", "news", "新闻", "媒体"]):
            return "news"
        return "web_search"

    def _detect_platform(self, url: str, title: str = "") -> str:
        text = f"{url} {title}".lower()
        if "qcc.com" in text or "企查查" in text:
            return "企查查"
        if "tianyancha.com" in text or "天眼查" in text:
            return "天眼查"
        if "aiqicha.baidu.com" in text or "爱企查" in text:
            return "爱企查"
        if "xiniudata" in text or "稀牛" in text:
            return "稀牛"
        if "36kr" in text:
            return "36氪"
        if "tmtpost" in text or "钛媒体" in text:
            return "钛媒体"
        return ""

    def _is_low_quality_open_web_source(
        self,
        host: str,
        title: str,
        url: str,
        source_type: str,
        query: str = "",
        module: str = "",
    ) -> tuple[bool, str]:
        """Skip weak, user-generated or document-share pages before archiving.

        These pages are common in broad person-report searches.  They consume
        fetch/cleaning budget and can make thin chapters look well sourced.
        Official, regulatory, filing, court, business-database and recognized
        media sources are deliberately exempted.
        """
        host = (host or "").lower().replace("www.", "")
        text = f"{host} {title or ''} {url or ''} {query or ''} {module or ''}".lower()
        hard_hosts = (
            "docin.com",
            "taodocs.com",
            "book118.com",
            "max.book118.com",
            "doc88.com",
            "wenku.baidu.com",
            "daokebaba.com",
            "douchai.cn",
            "jinchutou.com",
            "wendangxiazai.com",
            "360doc.com",
            "360docs.net",
            "fanwen118.com",
            "chazidian.com",
            "xuexila.com",
            "zuowen",
            "pptsupermarket.com",
            "processon.com",
            "zhihu.com",
            "jianshu.com",
            "wenxuecity.com",
            "androidtea.com",
            "qingganwu.cn",
            "iask.sina.com.cn",
            "zol.com.cn",
            "sogou.com",
            "csdn.net",
            "bilibili.com",
            "toutiao.com",
            "m.toutiao.com",
        )
        if any(token in host for token in hard_hosts):
            return True, f"low_quality_host:{host}"

        weak_title_terms = (
            "ppt",
            "pptx",
            ".doc",
            ".docx",
            "课件",
            "范文",
            "模板",
            "读后感",
            "作文",
            "励志",
            "名言",
            "语录",
            "网名",
            "英文名",
            "简介英文",
            "个人简介样稿",
            "问答",
            "学习心得",
            "听课笔记",
        )
        if any(term in text for term in weak_title_terms):
            return True, "low_quality_title"
        if source_type in {"government", "court", "regulatory", "filing", "business_database", "official", "news"}:
            return False, ""
        return False, ""

    def _needs_ocr(self, item: dict[str, Any], content: str, url: str) -> bool:
        image_url = str(item.get("image_url") or item.get("image") or "")
        if image_url:
            return True
        if self._is_pdf_url(url):
            return True
        return False

    def _is_pdf_url(self, url: str) -> bool:
        return str(url or "").lower().split("?", 1)[0].endswith(".pdf")
    def _source_grade(self, source: ResearchSource, quality: dict[str, Any] | None = None) -> str:
        meta = source.source_metadata or {}
        provider = str(meta.get("provider") or "").lower()
        platform = str(meta.get("platform") or "")
        source_type = str(source.source_type or "")
        url = str(source.url or "").lower()
        title = str(source.title or "")
        content = str(source.content or source.summary or "")[:1000]
        if self._is_structured_professional_source(source):
            # Commercial databases are useful cross-checks, but are not primary
            # evidence unless the record is an actual filing/court/regulator item.
            return "A" if source_type in {"court", "regulatory", "filing"} else "B"
        if provider in {"qcc", "tyc", "xiniu"} or platform in {"企查查", "天眼查", "稀牛"}:
            return "B"
        if source_type in {"government", "court", "regulatory", "filing"}:
            repost_signal = any(token in f"{title} {content}" for token in ["转载", "来源：", "转自"])
            return "B" if repost_signal else "A"
        if source_type in {"business_database", "official"}:
            return "B"
        if source_type == "news":
            return "B"
        return "C"

    def score_source(
        self,
        item: dict[str, Any],
        module: str = "",
        query: str = "",
        target: str = "",
    ) -> dict[str, Any]:
        title = str(item.get("title") or "")
        url = str(item.get("url") or item.get("link") or "")
        content = str(item.get("content") or item.get("summary") or item.get("snippet") or "")
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        provider = str(metadata.get("provider") or item.get("provider") or "").lower()
        platform = self._detect_platform(url, title)
        source_type = self._detect_source_type(url.lower(), title, url)

        host = ""
        try:
            host = urlparse(url).netloc.lower()
        except Exception:
            host = ""

        score = int(item.get("credibility_score") or item.get("score") or 50)
        authority_score = 0
        if source_type in {"government", "court", "regulatory", "filing"} or host.endswith(".gov.cn"):
            authority_score = 35
        elif source_type in {"business_database", "official"}:
            authority_score = 28
        elif source_type == "news":
            authority_score = 18
        else:
            authority_score = 10

        provider_score = 0
        if provider in {"serper", "tavily", "exa"}:
            provider_score = 12
        if platform in {"企查查", "天眼查", "爱企查", "启信宝", "稀牛"}:
            provider_score = max(provider_score, 25)

        relevance_blob = f"{title} {content[:1200]}".lower()
        target_hits = 1 if target and target.lower() in relevance_blob else 0
        query_terms = [term for term in re.split(r"\s+", query.lower()) if len(term) >= 2]
        query_hits = sum(1 for term in query_terms[:8] if term in relevance_blob)
        relevance_score = min(25, target_hits * 12 + query_hits * 2)

        depth_score = 0
        cleaned_len = len(self._clean_source_text(content))
        if cleaned_len >= 3000:
            depth_score = 18
        elif cleaned_len >= 1000:
            depth_score = 14
        elif cleaned_len >= 300:
            depth_score = 8
        elif cleaned_len >= 80:
            depth_score = 4

        score = max(score, authority_score + provider_score + relevance_score + depth_score)
        if self._is_pdf_url(url):
            score += 4
        if module and module in title:
            score += 3
        score = max(30, min(98, score))

        return {
            "score": score,
            "authority_score": authority_score,
            "provider_score": provider_score,
            "relevance_score": relevance_score,
            "depth_score": depth_score,
            "source_type": source_type,
            "platform": platform,
            "provider": provider,
        }

    def _clean_source_text(self, text: str) -> str:
        text = html.unescape(str(text or ""))
        text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
        text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        noise_terms = ["登录", "注册", "收藏", "分享", "返回首页", "网站导航", "客户端下载"]
        for term in noise_terms:
            text = text.replace(term, "")
        return text.strip()

    def _is_empty_structured_text(self, text: str) -> bool:
        clean = self._clean_source_text(text)
        if not clean:
            return True
        compact = re.sub(r"[\s|:：,，。；;`*_#>-]+", "", clean).lower()
        empty_markers = [
            "暂无记录",
            "暂无数据",
            "无数据",
            "无匹配项",
            "未查询到",
            "查询无结果",
            "请输入完整企业名称",
            "请输入18位统一社会信用代码",
            "no data",
            "not found",
            "empty",
            "地域限制",
            "后续调用建议",
            "error calling tool",
            "空结果：未发现",
        ]
        no_hit_markers = ["无匹配项", "未查询到", "查询无结果", "请输入完整企业名称", "请输入18位统一社会信用代码", "地域限制", "后续调用建议", "error calling tool", "空结果：未发现"]
        if any(marker.lower() in clean.lower() for marker in no_hit_markers):
            return True
        if any(marker in clean.lower() for marker in empty_markers):
            informative = re.sub(r"(暂无记录|暂无数据|无数据|未查询到|查询无结果|no data|not found|empty)", "", clean, flags=re.I).strip()
            return len(informative) < 80
        low_value = {"基础字段字段值待查", "字段值待查", "待查"}
        return len(compact) < 8 or compact in low_value

    def _is_structured_no_hit_text(self, text: str) -> bool:
        clean = self._clean_source_text(text)
        markers = [
            "无匹配项",
            "未查询到",
            "查询无结果",
            "请输入完整企业名称",
            "请输入18位统一社会信用代码",
            "company not found",
            "no matching",
            "未发现任何记录",
            "未发现相关记录",
            "未查到相关记录",
            "未返回相关记录",
            "地域限制",
            "后续调用建议",
            "error calling tool",
            "空结果：未发现",
        ]
        return any(marker.lower() in clean.lower() for marker in markers)

    def _source_content_flags(self, source: ResearchSource, text: str, quality: dict[str, Any]) -> list[str]:
        flags = []
        if len(text) < 80:
            flags.append("low_content")
        meta = source.source_metadata or {}
        content_kind = meta.get("content_kind") or meta.get("extraction_status")
        if content_kind:
            flags.append(str(content_kind))
        if quality.get("needs_ocr"):
            flags.append("needs_ocr")
        if meta.get("ocr_status") == "done":
            flags.append("ocr_done")
        elif quality.get("needs_ocr"):
            flags.append("ocr_pending")
        document = meta.get('document_extraction') or {}
        if (document.get('ocr') or {}).get('accepted_pages'):
            flags.append('ocr_transcribed_requires_fact_review')
        if document.get('needs_ocr_pages') and 'ocr_pending' not in flags:
            flags.append('ocr_pending')
        if not (source.content or "").strip() and (source.summary or "").strip():
            flags.append("summary_only")
        return flags

    def evaluate_source_quality(self, project: ResearchProject, plan: dict[str, Any]) -> dict[str, Any]:
        sources = self._active_industry_sources(project)
        module_counts: dict[str, int] = defaultdict(int)
        authoritative_counts: dict[str, int] = defaultdict(int)
        source_rows: list[dict[str, Any]] = []
        total_score = 0
        for source in sources:
            if str(project.target_type or "").lower() == "industry" and (not (source.content or source.summary or "").strip() or self._is_failed_extraction_source(source)):
                continue
            meta = source.source_metadata or {}
            module = str(meta.get("module") or source.source_type or "unknown")
            module_counts[module] += 1
            quality = meta.get("quality") or {}
            grade = self._source_grade(source, quality)
            if grade == "A":
                authoritative_counts[module] += 1
            score = int(source.credibility_score or quality.get("score") or 50)
            total_score += score
            source_rows.append({
                "title": source.title,
                "url": source.url,
                "source_type": source.source_type,
                "module": module,
                "provider": meta.get("provider", ""),
                "platform": meta.get("platform", ""),
                "grade": grade,
                "score": score,
                "content_chars": len(source.content or source.summary or ""),
            })
        gaps: list[str] = []
        min_sources = _env_int("QUALITY_MIN_SOURCES_PER_MODULE", 3, 1, 50)
        for module in [m.get("name") for m in plan.get("modules", []) if isinstance(m, dict)]:
            if module and module_counts.get(module, 0) < min_sources:
                gaps.append(f"{module}：有效来源不足，当前 {module_counts.get(module, 0)} 条，目标 {min_sources} 条")
        result = {
            "source_count": len(sources),
            "average_score": round(total_score / len(sources), 2) if sources else 0,
            "module_counts": dict(module_counts),
            "authoritative_counts": dict(authoritative_counts),
            "information_gaps": gaps,
            "ocr_items": [],
            "sources": source_rows[:500],
        }
        if project.target_type=='industry' and plan.get('evidence_requirements'):
            try:
                from .industry_evidence import source_coverage
            except ImportError:
                from industry_evidence import source_coverage
            coverage=source_coverage([s for s in sources if not self._is_failed_extraction_source(s)],plan['evidence_requirements'])
            result['evidence_coverage']=coverage
            result['information_gaps']=list(dict.fromkeys(gaps+coverage['information_gaps']))
        return result

    def _industry_retrieval_gaps(self, project, plan):
        try:
            from .industry_evidence import source_coverage, VERSION
        except ImportError:
            from industry_evidence import source_coverage, VERSION
        gaps=source_coverage(self._active_industry_sources(project),plan.get('evidence_requirements',[]))['information_gaps']
        previous=self._latest_artifact(project,'cleaned_facts')
        payload=_plain_json(previous.content) if previous else {}
        coverage=(payload.get('evidence_coverage') or {}) if isinstance(payload,dict) else {}
        if coverage.get('version')==VERSION and payload.get('industry_scope')==getattr(project,'industry_scope',{}):
            active_ids={r['id'] for r in plan.get('evidence_requirements',[])}
            gaps += [g for g in coverage.get('information_gaps',[]) if any(f'[需求:{rid}]' in g for rid in active_ids)]
        return list(dict.fromkeys(gaps))

    def _prepare_industry_evidence(self, project, cleaned, plan):
        try:
            from .industry_evidence import attach_provenance, fact_coverage
        except ImportError:
            from industry_evidence import attach_provenance, fact_coverage
        payload=_plain_json(cleaned)
        if not isinstance(payload,dict) or not isinstance(payload.get('facts'),list):
            return cleaned  # Preserve the existing invalid-JSON/index failure path.
        payload['facts']=attach_provenance(payload['facts'],self._active_industry_sources(project))
        for fact in payload['facts']:
            if fact['provenance']['locator']['status']!='verified':
                fact.update(eligible_for_report=False,eligible_for_risk_scoring=False,requires_human_review=True)
                fact['provenance']['quarantine_reason']='unlocated_source_quote'
        payload['evidence_requirements']=plan.get('evidence_requirements',[])
        payload['provenance_summary']={'total_fact_count':len(payload['facts']),
            'located_fact_count':sum(f['provenance']['locator']['status']=='verified' for f in payload['facts']),
            'quarantined_fact_count':sum(f['provenance']['locator']['status']!='verified' for f in payload['facts']),
            'index_eligible_fact_count':sum(f.get('eligible_for_report') is not False for f in payload['facts'])}
        payload['evidence_coverage']=fact_coverage(payload['facts'],payload['evidence_requirements'])
        payload['information_gaps']=list(dict.fromkeys(list(payload.get('information_gaps') or [])+payload['evidence_coverage']['information_gaps']))
        return json.dumps(payload,ensure_ascii=False,indent=2)

    def _apply_authority_coverage_requirements(self, quality: dict[str, Any], target_type: str, scope: dict | None = None) -> dict[str, Any]:
        result = dict(quality or {})
        authoritative_counts = dict(result.get("authoritative_counts") or {})
        requirements: dict[str, int] = {}
        for route in get_research_strategy(target_type).authority_queries:
            module = str(route.get("module") or "权威来源")
            if target_type == "industry" and (scope or {}).get("capital_market") == "none" and module == "投融资与资本市场":
                continue
            requirements[module] = max(requirements.get(module, 0), int(route.get("min_sources") or 2))
        gaps = [
            f"{module}：权威来源 {authoritative_counts.get(module, 0)} 条，最低要求 {minimum} 条"
            for module, minimum in requirements.items()
            if authoritative_counts.get(module, 0) < minimum
        ]
        result["authority_requirements"] = requirements
        result["authority_coverage_gaps"] = gaps
        result["authority_coverage_passed"] = not gaps
        result["information_gaps"] = list(dict.fromkeys(list(result.get("information_gaps") or []) + gaps))
        return result
    def enrich_ocr_sources(self, db: Session, project: ResearchProject, emit: TraceEmitter | None = None) -> int:
        if str(project.target_type or '').lower() != 'company':
            _emit(emit, "ocr", "ocr_extraction_agent", "当前链路未启用OCR", "", status="skipped")
            return 0
        from company_ocr import VERSION, _integer
        if os.getenv('COMPANY_PDF_OCR_ENABLED', 'true').lower() in {'false', '0', 'off'}:
            _emit(emit, 'ocr', 'ocr_extraction_agent', '公司按页OCR已关闭', '原待识别页保留', status='skipped')
            return 0
        maximum = _integer('COMPANY_PDF_OCR_MAX_SOURCES', 4, 1, 20)
        refreshed = 0
        attempted = 0
        for source in list(project.sources or []):
            meta = dict(source.source_metadata or {})
            extraction = meta.get('document_extraction') or {}
            # Fresh company fetches already ran page-selective OCR. Do not
            # refetch them or silently promote partial OCR to a complete run.
            previous_ocr=extraction.get('ocr') or {}
            retry_pending=os.getenv('COMPANY_PDF_OCR_RETRY_PENDING', 'false').lower() in {'true','1','on'}
            if (previous_ocr.get('version') == VERSION and previous_ocr.get('status') not in {'busy','unavailable','disabled'} and not retry_pending):
                continue
            pending = extraction.get('needs_ocr_pages') or []
            pdf = str(source.url or '').split('?', 1)[0].lower().endswith('.pdf') or 'pdf' in str(meta.get('fetched_content_type') or '')
            if not pdf or not pending:
                continue
            if attempted >= maximum:
                _emit(emit, 'ocr', 'ocr_extraction_agent', '扫描页待后续处理', '本轮来源预算已用完，原缺口保留', url=source.url, status='warning')
                continue
            attempted += 1
            _emit(emit, 'ocr', 'ocr_extraction_agent', '公司PDF按页补充识别', f'pending_pages={len(pending)}', url=source.url, status='running')
            fetched = self._fetch_web_url_with_timeout(source.url, False, emit=emit, document_profile='company')
            if fetched.get('document_extraction') and fetched.get('document_pages'):
                source.content = fetched.get('content') or source.content
                meta.update(document_pages=fetched['document_pages'], document_extraction=fetched['document_extraction'])
                if fetched.get('content'):
                    meta.update(content_kind='pdf_text_extracted', fetch_status=fetched.get('status') or 'done',
                                fetched_content_type=fetched.get('content_type') or 'application/pdf',
                                fetched_pages=fetched.get('pages') or 0)
                ocr = fetched['document_extraction'].get('ocr') or {}
                meta['ocr_status'] = ocr.get('status', 'pending')
                refreshed += 1
                detail = f"accepted={len(ocr.get('accepted_pages') or [])}, pending={len(ocr.get('pending_pages') or [])}"
                status = 'done'
            else:
                # Fetch failure must not erase original text/coverage or be
                # represented as an empty search result.
                meta['ocr_retry'] = {'status': fetched.get('status') or 'failed', 'error': fetched.get('error') or ''}
                detail = '重新获取失败，保留原文字与待识别页'
                status = 'warning'
            source.source_metadata = meta
            _emit(emit, 'ocr', 'ocr_extraction_agent', '公司PDF识别状态已保存', detail, url=source.url, status=status)
        if attempted:
            db.commit()
        _emit(emit, 'ocr', 'ocr_extraction_agent', '公司按页OCR检查完成', f'refreshed_sources={refreshed}; failed/partial/pages remain explicit', status='done')
        return refreshed

    def _company_chart_refresh_candidates(self, project):
        if str(getattr(project,'target_type','')).lower()!='company':return []
        from company_charts import VERSION,looks_like_survey_chart
        from report_agents.company_evidence import document_pages,source_body
        retry=os.getenv('COMPANY_PDF_CHART_RETRY_PENDING','false').lower() in {'true','1','on'}
        candidates=[]
        for source in list(getattr(project,'sources',[]) or []):
            meta=source.source_metadata or {}
            if meta.get('entity_validation') in {'rejected','ambiguous','related_entity_context'}:continue
            if source_body(source)[1]=='discovery_summary':continue
            extraction=meta.get('document_extraction') or {}
            previous=extraction.get('survey_charts') or meta.get('survey_chart_refresh') or {}
            if previous.get('version')==VERSION and not retry:continue
            if urlparse(source.url or '').scheme not in {'http','https'}:continue
            if any(looks_like_survey_chart(p['text']) for p in document_pages(source)):candidates.append(source)
        return candidates

    def enrich_company_survey_charts(self, db, project, emit=None):
        from company_charts import VERSION
        candidates=self._company_chart_refresh_candidates(project)
        maximum=_env_int('COMPANY_PDF_CHART_MAX_SOURCES',4,1,20)
        refreshed=0
        for source in candidates[:maximum]:
            _emit(emit,'charts','company_chart_agent','公司调查图表补充版面提取',
                  '重新取得完整PDF；年份/标签/曲线/坐标一致时才写入图表记录。',url=source.url,status='running')
            fetched=self._fetch_web_url_with_timeout(source.url,False,emit=emit,document_profile='company')
            meta=dict(source.source_metadata or {})
            extraction=fetched.get('document_extraction') or {}
            charts=extraction.get('survey_charts') or {}
            if fetched.get('content') and fetched.get('document_pages') and charts.get('version')==VERSION:
                # Replace one coherent original, never attach new coordinates
                # to an earlier body merely because its URL is unchanged.
                old_sha=((meta.get('document_extraction') or {}).get('ocr') or {}).get('source_sha256')
                new_sha=charts.get('source_sha256')
                if old_sha and new_sha and old_sha!=new_sha:
                    snapshot=json.dumps({'content':source.content,'source_metadata':meta},ensure_ascii=False)
                    snapshot_sha=hashlib.sha256(snapshot.encode('utf-8')).hexdigest()
                    key=research_store.put_text(f'projects/{project.id}/source_revisions/{source.id}_{snapshot_sha}.json',
                        snapshot,'application/json; charset=utf-8')
                    meta['previous_document_revision']={'source_sha256':old_sha,'object_key':key}
                source.content=fetched['content']
                meta.update(document_pages=fetched['document_pages'],document_extraction=extraction,
                            content_kind='pdf_text_extracted',fetch_status=fetched.get('status') or 'done',
                            content_retrieved_at=datetime.now().isoformat(timespec='seconds'))
                refreshed+=1
                status='done' if not (charts.get('unresolved_pages') or charts.get('pending_pages')) else 'warning'
                detail=f"charts={charts.get('charts',0)}; unresolved={charts.get('unresolved_pages',[])}; pending={charts.get('pending_pages',[])}"
            else:
                meta['survey_chart_refresh']={'version':VERSION,'status':'failed','reason':fetched.get('status') or 'failed',
                                              'retrieved_at':datetime.now().isoformat(timespec='seconds')}
                detail='获取或提取失败；原文及原图表缺口保留，不表示没有披露。';status='warning'
            source.source_metadata=meta
            _emit(emit,'charts','company_chart_agent','公司图表提取状态已保存',detail,url=source.url,status=status)
        if candidates:db.commit()
        if len(candidates)>maximum:
            _emit(emit,'charts','company_chart_agent','公司图表来源预算未覆盖全部原件',
                  f'pending_sources={len(candidates)-maximum}',status='warning')
        return refreshed

    def _should_use_vision_for_source(self, source: ResearchSource) -> bool:
        return False

    def _skip_ocr_for_source(self, source: ResearchSource) -> bool:
        return True

    def _wait_for_ocr_slot(self) -> None:
        return None

    def _ocr_provider_order(self) -> list[str]:
        return []

    def _ocr_with_fallback(self, image_url: str, providers: list[str], emit: TraceEmitter | None = None) -> str:
        return ""

    def _tencent_ocr(self, image_url: str, emit: TraceEmitter | None = None) -> str:
        return ""

    def _baidu_ocr(self, image_url: str, emit: TraceEmitter | None = None) -> str:
        return ""

    def _get_baidu_ocr_token(self, emit: TraceEmitter | None = None) -> str:
        return ""
    def _extract_image_urls(self, source: ResearchSource) -> list[str]:
        meta = source.source_metadata or {}
        candidates: list[Any] = []
        candidates.extend(meta.get("images") or [])
        if isinstance(meta.get("quality"), dict) and (meta["quality"].get("needs_ocr") or meta["quality"].get("needs_visual_review")):
            candidates.append(source.url)
        urls: list[str] = []
        for item in candidates:
            if isinstance(item, str):
                url = item
            elif isinstance(item, dict):
                url = item.get("url") or item.get("image_url") or item.get("src") or item.get("object_key") or ""
            else:
                url = ""
            url = str(url).strip()
            if not url:
                continue
            if isinstance(item, dict) and (item.get("object_key") or item.get("kind") == "professional_visual_evidence"):
                data_url = self._store_image_to_data_url(str(item.get("object_key") or url), str(item.get("mime_type") or ""))
                if data_url and data_url not in urls:
                    urls.append(data_url)
                continue
            if url.startswith("local://"):
                data_url = self._local_image_to_data_url(url.removeprefix("local://"))
                if data_url and data_url not in urls:
                    urls.append(data_url)
                continue
            if re.match(r"^projects/.+\.(png|jpe?g|webp|gif|bmp)$", url, flags=re.I):
                data_url = self._store_image_to_data_url(url, "")
                if data_url and data_url not in urls:
                    urls.append(data_url)
                continue
            lower = url.lower().split("?", 1)[0]
            if lower.startswith("data:image/") and url not in urls:
                urls.append(url)
                continue
            if lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")) and url not in urls:
                urls.append(url)
        return urls

    def _store_image_to_data_url(self, key: str, mime_type: str = "") -> str:
        try:
            payload = research_store.get_bytes(key)
            if not payload:
                return ""
            mime = mime_type or mimetypes.guess_type(key)[0] or "image/png"
            encoded = base64.b64encode(payload).decode("ascii")
            return f"data:{mime};base64,{encoded}"
        except Exception:
            return ""

    def _local_image_to_data_url(self, path: str) -> str:
        try:
            image_path = Path(path)
            if not image_path.exists() or not image_path.is_file():
                return ""
            mime_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
            encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
            return f"data:{mime_type};base64,{encoded}"
        except Exception:
            return ""

    def _save_professional_visual_evidence(
        self,
        project: ResearchProject,
        provider: str,
        title: str,
        content: str,
        metadata: dict[str, Any],
        emit: TraceEmitter | None = None,
    ) -> list[dict[str, str]]:
        if provider not in {"qcc", "qcc_company", "qcc_risk", "qcc_operation", "qcc_ipr", "tyc", "xiniu"}:
            return []
        max_images = _env_int("PROFESSIONAL_VISUAL_MAX_IMAGES", 4, 0, 20)
        if max_images <= 0:
            return []
        max_bytes = _env_int("PROFESSIONAL_VISUAL_MAX_BYTES", 5_000_000, 100_000, 50_000_000)
        pattern = re.compile(r"data:image/(?P<ext>png|jpe?g|webp|gif|bmp);base64,(?P<data>[A-Za-z0-9+/=\s]+)", re.I)
        images: list[dict[str, str]] = []
        seen: set[str] = set()
        for index, match in enumerate(pattern.finditer(content or ""), 1):
            if len(images) >= max_images:
                break
            ext = match.group("ext").lower().replace("jpeg", "jpg")
            raw = re.sub(r"\s+", "", match.group("data") or "")
            if not raw or raw[:80] in seen:
                continue
            seen.add(raw[:80])
            try:
                payload = base64.b64decode(raw, validate=False)
            except Exception as exc:
                _emit(emit, "structured_data", "visual_evidence_agent", "专业平台图片解析失败", "", status="warning")
                continue
            if not payload or len(payload) > max_bytes:
                _emit(emit, "structured_data", "visual_evidence_agent", "专业平台图片过大或为空，跳过该图", f"{provider} image={index}, bytes={len(payload)}", status="warning")
                continue
            content_type = f"image/{'jpeg' if ext == 'jpg' else ext}"
            key = research_store.put_bytes(
                f"projects/{project.id}/visual_evidence/{provider}_{_now_key()}_{index}.{ext}",
                payload,
                content_type,
            )
            images.append(
                {
                    "url": key,
                    "object_key": key,
                    "mime_type": content_type,
                    "provider": provider,
                    "title": title,
                    "kind": "professional_visual_evidence",
                    "source_url": metadata.get("source_url") or "",
                }
            )
        if images:
            _emit(emit, "structured_data", "visual_evidence_agent", "专业平台视觉证据已保存", "", status="done")
        return images

    def _parse_mcp_response(self, response: requests.Response) -> dict[str, Any]:
        response.encoding = "utf-8"
        text = (response.text or "").strip()
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type or text.startswith("event:") or text.startswith("data:"):
            payloads = []
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    data = line.removeprefix("data:").strip()
                    if data and data != "[DONE]":
                        payloads.append(data)
            for data in reversed(payloads):
                try:
                    return json.loads(data)
                except json.JSONDecodeError:
                    continue
            return {"raw_sse": text[:4000]}
        try:
            return response.json()
        except ValueError:
            return {"raw": text[:4000]}

    def _mcp_rpc(
        self,
        url: str,
        headers: dict[str, str],
        method: str,
        params: dict[str, Any] | None = None,
        session: requests.Session | None = None,
        request_id: int = 1,
        timeout: int = 30,
    ) -> tuple[dict[str, Any], requests.Session]:
        active_session = session or requests.Session()
        active_session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2024-11-05",
                **headers,
            }
        )
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            body["params"] = params
        response = active_session.post(url, json=body, timeout=(5, timeout))
        session_id = response.headers.get("mcp-session-id") or response.headers.get("Mcp-Session-Id")
        if session_id:
            active_session.headers.update({"Mcp-Session-Id": session_id})
        payload = self._parse_mcp_response(response)
        if response.status_code >= 400:
            return {"error": f"HTTP {response.status_code}", "response": payload}, active_session
        return payload, active_session

    def _mcp_initialize(self, url: str, headers: dict[str, str], timeout: int = 30) -> tuple[requests.Session, bool, str]:
        session = requests.Session()
        payload, session = self._mcp_rpc(
            url,
            headers,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "rag-workflow-mcp", "version": "0.1.0"},
            },
            session=session,
            request_id=1,
            timeout=timeout,
        )
        if payload.get("error") or payload.get("errorCode"):
            return session, False, json.dumps(payload, ensure_ascii=False)[:1000]
        try:
            self._mcp_rpc(url, headers, "notifications/initialized", {}, session=session, request_id=2, timeout=timeout)
        except Exception:
            pass
        return session, True, ""

    def _mcp_call_tool(
        self,
        url: str,
        headers: dict[str, str],
        tool_name: str,
        arguments: dict[str, Any],
        session: requests.Session | None = None,
        request_id: int = 10,
        timeout: int = 45,
    ) -> tuple[dict[str, Any], requests.Session]:
        payload, active_session = self._mcp_rpc(
            url,
            headers,
            "tools/call",
            {"name": tool_name, "arguments": arguments},
            session=session,
            request_id=request_id,
            timeout=timeout,
        )
        result = payload.get("result", payload)
        blocks = result.get("content", []) if isinstance(result, dict) else []
        message = "\n".join(str(item.get("text") or "") for item in blocks if isinstance(item, dict)) if isinstance(blocks, list) else ""
        if (isinstance(result, dict) and result.get("isError")) or message.lstrip().lower().startswith("error calling tool"):
            return {"error": {"code": "tool_execution_error", "message": message[:800] or "MCP工具执行失败"}}, active_session
        return payload, active_session

    def _extract_mcp_text(self, payload: dict[str, Any], *, preserve_company_risk: bool = False) -> str:
        if payload.get("error"):
            return json.dumps(payload, ensure_ascii=False, indent=2)
        result = payload.get("result", payload)
        blocks: list[str] = []
        content = result.get("content") if isinstance(result, dict) else None
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if text:
                        blocks.append(str(text))
        if blocks:
            return "\n\n".join(self._structured_json_to_markdown(block, limits=(500, 32, 12000) if preserve_company_risk else None) for block in blocks)
        return self._structured_json_to_markdown(result, limits=(500, 32, 12000) if preserve_company_risk else None)

    def _structured_json_to_markdown(self, value: Any, title: str = "", limits=None) -> str:
        if isinstance(value, str):
            clean = value.strip()
            if not clean:
                return ""
            try:
                parsed = json.loads(clean)
            except Exception:
                return clean
            return self._structured_json_to_markdown(parsed, title=title, limits=limits)
        if isinstance(value, list):
            if not value:
                return "暂无记录"
            if all(isinstance(item, dict) for item in value):
                return self._dict_list_to_markdown_table(value, title=title, limits=limits)
            return "\n".join(f"- {self._structured_scalar_to_text(item)}" for item in value)
        if not isinstance(value, dict):
            return self._structured_scalar_to_text(value)
        sections: list[str] = []
        scalar_rows: list[dict[str, Any]] = []
        for key, item in value.items():
            label = str(key)
            if isinstance(item, list) and item and all(isinstance(row, dict) for row in item):
                sections.append(self._dict_list_to_markdown_table(item, title=label, limits=limits))
            elif isinstance(item, dict):
                sections.append(self._structured_json_to_markdown(item, title=label, limits=limits))
            elif isinstance(item, list):
                sections.append(f"### {label}\n\n{self._structured_json_to_markdown(item, title=label, limits=limits)}")
            else:
                scalar_rows.append({"字段": label, "值": self._structured_scalar_to_text(item)})
        if scalar_rows:
            sections.insert(0, self._dict_list_to_markdown_table(scalar_rows, title=title or "基础字段", limits=limits))
        return "\n\n".join(part for part in sections if part.strip()) or json.dumps(value, ensure_ascii=False, indent=2)

    def _structured_scalar_to_text(self, value: Any) -> str:
        if value is None:
            return "待查"
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        text = str(value).strip()
        return text if text else "待查"

    def _dict_list_to_markdown_table(self, rows: list[dict[str, Any]], title: str = "", limits=None) -> str:
        if not rows:
            return ""
        max_rows, max_columns, max_cell = limits or (80, 8, 600)
        keys: list[str] = []
        preferred = [
            "name", "company_name", "企业名称", "公司名称", "股东名称", "shareholder_name",
            "ratio", "shareholding_ratio", "持股比例", "amount", "认缴出资额",
            "legal_person", "法定代表人", "registered_capital", "注册资本",
            "status", "登记状态", "date", "成立日期", "role", "职位",
        ]
        for key in preferred:
            if any(key in row for row in rows) and key not in keys:
                keys.append(key)
        for row in rows:
            for key in row.keys():
                if key not in keys:
                    keys.append(key)
                if len(keys) >= max_columns:
                    break
            if len(keys) >= max_columns:
                break
        lines: list[str] = []
        if title:
            lines.extend([f"### {title}", ""])
        lines.append("| " + " | ".join(str(key) for key in keys) + " |")
        lines.append("| " + " | ".join("---" for _ in keys) + " |")
        clipped_cells = 0
        for row in rows[:max_rows]:
            cells: list[str] = []
            for key in keys:
                cell = self._structured_scalar_to_text(row.get(key))
                cell = cell.replace("\r\n", "<br>").replace("\n", "<br>").replace("|", " / ")
                if len(cell) > max_cell:
                    clipped_cells += 1
                cells.append(_clip(cell, max_cell))
            lines.append("| " + " | ".join(cells) + " |")
        if len(rows) > max_rows:
            lines.append(f"\n> 已截取前 {max_rows} 条记录，完整返回共 {len(rows)} 条。")
        if limits and (clipped_cells or any(set(row) - set(keys) for row in rows)):
            lines.append(f"\n> 公司风险格式化存在字段截断：长字段{clipped_cells}处；未展示列或字段请回原始返回核对。")
        return "\n".join(lines)
    def _mcp_error_is_disabled_tool(self, payload: dict[str, Any]) -> bool:
        text = json.dumps(payload or {}, ensure_ascii=False).lower()
        return any(marker in text for marker in ["未启用", "未配置", "未开通", "not enabled", "not configured", "disabled"])

    def _extract_tyc_company_anchor(self, text: str, fallback_name: str) -> dict[str, str]:
        anchor = {"company_name": fallback_name, "company_id": ""}
        clean = self._clean_source_text(text)
        target_key = re.sub(r"[\s\d.。．_-]+", "", fallback_name or "")
        company_suffix = r"(?:有限责任公司|股份有限公司|有限公司|集团有限公司|科技股份有限公司|科技有限公司)"
        for match in re.finditer(r"[\u4e00-\u9fffA-Za-z0-9（）()·]{2,48}" + company_suffix, clean):
            name = self._clean_company_candidate_name(match.group(0))
            if target_key and target_key in re.sub(r"[\s\d.。．_-]+", "", name):
                anchor["company_name"] = name
                break
        for line in clean.splitlines():
            if fallback_name and fallback_name in line:
                id_match = re.search(r"\b\d{6,}\b", line)
                if id_match:
                    anchor["company_id"] = id_match.group(0)
                break
        return anchor

    def _normalize_company_search_payload(self, result: Any, target_name: str) -> Any:
        return result
    def _structured_entity_matches_request(self, content: str, metadata: dict[str, Any], intake: dict[str, Any] | None) -> tuple[bool, str]:
        """Fail closed when a professional platform returns a subsidiary for a brand query."""
        expected = str(
            metadata.get("canonical_company_name")
            or metadata.get("query")
            or (intake or {}).get("canonical_company_name")
            or (intake or {}).get("structured_target")
            or ""
        ).strip()
        expected_key = re.sub(r"\s+", "", expected).lower()
        if len(expected_key) < 2:
            return False, "no_structured_anchor"
        clean = self._clean_source_text(content)
        if re.fullmatch(r"[0-9A-Z]{18}", expected, re.I):
            returned_codes = {value.upper() for value in re.findall(r"\b[0-9A-Z]{18}\b", clean, flags=re.I)}
            if expected.upper() in returned_codes:
                return True, "credit_code_match"
            return False, "credit_code_mismatch"

        # If the structured response contains a labelled enterprise-name field
        # (e.g. ``企业名称| 京东科技控股股份有限公司``), compare it directly
        # against the target.  This is the strongest signal available and must
        # not be silently skipped.
        enterprise_name_match = re.search(
            r"(?:企业名称|公司名称|法定全称|查询公司名称)\s*[|：:]\s*([^\n|；;]{2,100})",
            str(content or ""),
        )
        if enterprise_name_match:
            structured_name = re.sub(r"\s+", "", enterprise_name_match.group(1)).lower()
            structured_name = structured_name.strip("| ，,。；;")
            full_legal_name = bool(re.search(r"(?:有限责任公司|股份有限公司|有限公司|集团|有限合伙)", expected))
            if (full_legal_name and expected_key != structured_name) or (not full_legal_name and expected_key not in structured_name):
                return False, "enterprise_name_field_mismatch"
            # A short brand (e.g. 京东 — no legal suffix) must never silently
            # resolve to a subsidiary whose name contains only the brand as a
            # substring alongside vertical / branch terms.
            short_brand = not re.search(
                r"(?:有限责任公司|股份有限公司|有限公司|集团|有限合伙)", expected
            )
            branch_terms_expanded = (
                "广告", "物流", "健康", "影业", "供应链", "小额贷款", "软件",
                "云计算", "数字营销", "科技", "金融", "数科", "大数据",
                "人工智能", "智能", "信息技术", "电商", "网络科技", "支付",
                "保险", "证券", "基金", "投资", "商业保理", "融资租赁",
                "小额贷", "消费金融", "到家", "零售", "云", "出行",
            )
            if short_brand and any(term in structured_name for term in branch_terms_expanded):
                return False, "brand_query_resolved_to_subsidiary"
            return True, "enterprise_name_field_match"

        # Fallback: scan for any company names (with legal suffixes) in the
        # response body and check whether the expected name appears as a
        # substring.  This is weaker than the enterprise-name field check
        # because the response may merely *mention* the target while the
        # primary subject is a different entity.
        names = [
            self._clean_company_candidate_name(item)
            for item in re.findall(r"[\u4e00-\u9fffA-Za-z0-9（）()·]{2,48}(?:有限责任公司|股份有限公司|集团有限公司|有限公司)", clean)
        ]
        names = [item for item in names if item]
        if not names:
            # When the content is substantial but contains no identifiable
            # company name, and we have a meaningful target anchor, it is
            # safer to treat the source as unverified rather than silently
            # accepting it.
            if len(clean) > 200 and len(expected_key) >= 2:
                if expected_key in re.sub(r"\s+", "", clean).lower():
                    return True, "expected_key_found_in_body"
                return False, "no_parseable_entity_name_in_structured_response"
            return True, "no_parseable_entity_name"
        full_legal_name = bool(re.search(r"(?:有限责任公司|股份有限公司|有限公司|集团|有限合伙)", expected))
        matched = [
            item for item in names
            if (
                expected_key == re.sub(r"\s+", "", item).lower()
                if full_legal_name else expected_key in re.sub(r"\s+", "", item).lower()
            )
        ]
        if not matched:
            return False, "returned_entity_does_not_match_anchor"
        # A short brand such as 阿里巴巴 must not silently become a vertical
        # subsidiary such as 阿里巴巴广告有限公司.  Registered core entities (e.g.
        # 阿里巴巴（中国）网络技术有限公司) remain allowed.
        short_brand = not re.search(r"(?:有限责任公司|股份有限公司|有限公司|集团|有限合伙)", expected)
        branch_terms_expanded = (
            "广告", "物流", "健康", "影业", "供应链", "小额贷款", "软件",
            "云计算", "数字营销", "科技", "金融", "数科", "大数据",
            "人工智能", "智能", "信息技术", "电商", "网络科技", "支付",
            "保险", "证券", "基金", "投资", "商业保理", "融资租赁",
            "小额贷", "消费金融", "到家", "零售", "云", "出行",
        )
        if short_brand and all(any(term in item for term in branch_terms_expanded) for item in matched):
            return False, "brand_query_resolved_to_subsidiary"
        return True, "matched_anchor"

    def _structured_entity_is_related_context(self, content: str, metadata: dict[str, Any], intake: dict[str, Any] | None) -> bool:
        """Retain a clearly related legal entity as context, never as target evidence."""
        expected = str(metadata.get("canonical_company_name") or metadata.get("query") or (intake or {}).get("canonical_company_name") or "").strip()
        returned = re.search(r"(?:企业名称|公司名称|法定全称|查询公司名称)\s*[|：:]\s*([^\n|；;]{2,100})", str(content or ""))
        if not expected or not returned:
            return False
        expected_name = re.sub(r"\s+", "", expected)
        returned_name = re.sub(r"\s+", "", returned.group(1)).strip("| ，,。；;")
        if not re.search(r"(?:有限责任公司|股份有限公司|有限公司|集团|有限合伙)", expected_name):
            return False
        expected_core = re.sub(r"(?:有限责任公司|股份有限公司|集团有限公司|有限公司|集团|控股|科技|金融|物流|健康|数科)", "", expected_name)
        returned_core = re.sub(r"(?:有限责任公司|股份有限公司|集团有限公司|有限公司|集团|控股|科技|金融|物流|健康|数科)", "", returned_name)
        ignored = {"北京", "上海", "深圳", "杭州", "中国", "有限", "公司"}
        return any(
            token not in ignored and token in returned_core
            for token in (expected_core[index:index + 2] for index in range(max(0, len(expected_core) - 1)))
        )

    def _save_structured_source(
        self,
        db: Session,
        project: ResearchProject,
        provider: str,
        module: str,
        title: str,
        content: str,
        metadata: dict[str, Any],
        emit: TraceEmitter | None = None,
        intake: dict[str, Any] | None = None,
    ) -> bool:
        clean = self._clean_source_text(content)
        if self._is_empty_structured_text(clean):
            return False
        entity_ok, entity_reason = self._structured_entity_matches_request(content, metadata, intake)
        related_entity_context = False
        if not entity_ok:
            related_entity_context = self._structured_entity_is_related_context(content, metadata, intake)
            if not related_entity_context:
                _emit(
                    emit,
                    "structured_data",
                    "structured_data_agent",
                    "专业平台返回主体与当前锚点不一致，已拒绝入库",
                    f"query={metadata.get('query') or metadata.get('target')}, reason={entity_reason}",
                    status="warning",
                )
                return False
            _emit(
                emit,
                "structured_data",
                "structured_data_agent",
                "专业平台返回关联主体，已按关联背景入库",
                f"query={metadata.get('query') or metadata.get('target')}, reason={entity_reason}",
                status="warning",
            )
        key = f"structured://{provider}/{module}/{title}"
        exists = (
            db.query(ResearchSource)
            .filter(ResearchSource.project_id == project.id, ResearchSource.url == key)
            .first()
        )
        if exists:
            if (exists.source_metadata or {}).get('retention_policy') != 'record_only':
                return False
            db.delete(exists)
            db.flush()
        # Several tools can finish within the same second. Their raw responses
        # must remain separate objects so later evidence can be reproduced.
        source_stamp = f"{_now_key()}_{uuid.uuid4().hex}"
        object_key = research_store.put_text(
            f"projects/{project.id}/structured/{provider}_{module}_{source_stamp}.md",
            content,
            "text/markdown; charset=utf-8",
        )
        metadata = dict(metadata)
        raw_response = metadata.pop("company_qcc_raw_response", None)
        if raw_response is not None:
            metadata["raw_response_key"] = research_store.put_text(
                f"projects/{project.id}/structured/{provider}_{module}_{source_stamp}_raw.json",
                json.dumps(raw_response, ensure_ascii=False), "application/json; charset=utf-8")
        if (intake or {}).get("target_type") == "person":
            metadata["person_intake_fingerprint"] = self._intake_evidence_fingerprint(intake)
        source_metadata = {
            "provider": provider,
            "module": module,
            "retention_policy": "transient_platform_body",
            "content_kind": "structured_data",
            "entity_validation": "related_entity_context" if related_entity_context else "verified",
            "entity_validation_reason": entity_reason,
            "evidence_scope": "related_entity_context" if related_entity_context else "target_direct",
            **metadata,
        }
        affiliation_context = (intake or {}).get("person_affiliation_context")
        if not metadata.get("person_subject_verified") and isinstance(affiliation_context, dict) and affiliation_context.get("person_name") and affiliation_context.get("affiliation_name"):
            source_metadata["person_affiliation"] = dict(affiliation_context)
        visual_images = self._save_professional_visual_evidence(project, provider, title, content, source_metadata, emit=emit)
        if visual_images:
            source_metadata["images"] = list(source_metadata.get("images") or []) + visual_images
            source_metadata["quality"] = {
                **(source_metadata.get("quality") or {}),
                "needs_ocr": True,
                "needs_visual_review": True,
                "visual_evidence_count": len(visual_images),
                "provider": provider,
            }
            source_metadata["content_kind"] = "structured_data_with_visual_evidence"
        db.add(
            ResearchSource(
                project_id=project.id,
                source_type="business_database",
                title=title,
                url=key,
                object_key=object_key,
                content=content,
                summary=clean[:500],
                source_metadata=source_metadata,
                credibility_score=92,
            )
        )
        db.commit()
        return True

    def collect_structured_sources(self, db: Session, project: ResearchProject, intake: dict[str, Any], emit: TraceEmitter | None = None) -> int:
        if (intake.get("target_type") or project.target_type) != "company" and not intake.get("structured_target"):
            return 0
        target = (intake.get("structured_target") or intake.get("target_name") or project.target_name or project.title or "").strip()
        if not target:
            return 0
        added = 0
        company = self._standardize_target_type(project, intake, target) == "company"
        if company:
            project.company_professional_platform_attempts = []
            project.company_judicial_query_attempts = []
        if str(intake.get("target_type") or project.target_type).lower() == "person":
            try:
                from .person_platforms import collect as collect_person_platforms
            except ImportError:
                from person_platforms import collect as collect_person_platforms
            return collect_person_platforms(self, db, project, target, intake, emit)
        collectors = [self._collect_qcc_sources, self._collect_tyc_sources, self._collect_xiniu_sources]
        for collector in collectors:
            try:
                added += collector(db, project, target, intake, emit=emit)
            except Exception as exc:
                _emit(emit, "structured_data", "structured_data_agent", "结构化采集失败", str(exc), status="warning")
        if company:
            audit = {"attempts": getattr(project, "company_professional_platform_attempts", []),
                     "judicial_query_attempts": getattr(project, "company_judicial_query_attempts", [])}
            self.save_artifact(db, project, "professional_platform_audit", "专业平台查询覆盖记录",
                               json.dumps(audit, ensure_ascii=False), {"provider_audit_version": 1})
            failures = sum(r["status"] in {"failed", "not_queried"} for r in audit["attempts"])
            if failures:
                _emit(emit, "structured_data", "structured_data_agent", "专业平台存在未完成查询",
                      f"失败或未查询={failures}；平台不可用不表示企业无记录。", status="warning")
        _emit(emit, "structured_data", "structured_data_agent", "结构化采集完成", f"sources_added={added}", sources_added=added, status="done")
        return added

    def _company_platform_audit(self, project, intake, target, provider, credential):
        if not hasattr(self, "_company_platform_failure_cache"):
            self._company_platform_failure_cache = {}
        kind = self._standardize_target_type(project, intake, target)
        return CompanyPlatformAudit(project, provider, credential, self._company_platform_failure_cache,
                                    kind in {"company", "person"},
                                    attribute="person_platform_attempts" if kind == "person" else "company_professional_platform_attempts",
                                    subject=target)

    def _emit_platform_stop(self, audit, emit):
        _emit(emit, "structured_data", audit.provider + "_mcp_agent", "专业平台暂不可用，停止本轮调用",
              f"{audit.provider}: {audit.stop_reason}；后续工具未查询，不计为企业无记录。", status="warning")

    def collect_person_affiliation_structured_sources(
        self,
        db: Session,
        project: ResearchProject,
        intake: dict[str, Any],
        emit: TraceEmitter | None = None,
    ) -> int:
        """Collect confirmed direct affiliations once, without graph recursion."""
        if str(intake.get("target_type") or project.target_type or "").lower() != "person":
            return 0
        if os.getenv("PERSON_AFFILIATION_STRUCTURED_ENABLED", "true").strip().lower() not in {"1", "true", "yes", "on"}:
            return 0
        limit = _env_int("PERSON_AFFILIATION_STRUCTURED_LIMIT", 5, 0, 12)
        if limit <= 0:
            return 0

        explicit_affiliations = list(intake.get("affiliations") or [])
        rows = [
            {
                "name": name,
                "relationship_type": "用户提供的直接关联主体",
                "relationship_confidence": "medium",
                "host_count": 0,
                "source_count": 0,
                "max_score": 0,
                "explicit_intake": True,
            }
            for name in explicit_affiliations
            if str(name or "").strip()
        ]
        rows.extend([row for row in intake.get("confirmed_person_affiliations", []) if isinstance(row, dict)])
        rows.sort(
            key=lambda row: (
                1 if row.get("explicit_intake") else 0,
                int(row.get("host_count") or 0),
                int(row.get("source_count") or 0),
                int(row.get("max_score") or 0),
            ),
            reverse=True,
        )
        initial_keys = {
            re.sub(r"\s+", "", str(item or "")).lower()
            for item in (
                intake.get("associated_company"),
                intake.get("structured_target"),
                intake.get("canonical_company_name"),
            )
            if str(item or "").strip()
        }
        # Only concrete structured targets are treated as already collected.
        # Explicit multi-value affiliations still need their own controlled
        # professional-platform pass.
        raw_affiliation_aliases = [
            re.sub(r"\s+", "", item).lower()
            for item in re.split(r"[、,，/；;]+", str(intake.get("affiliation") or ""))
            if item.strip()
        ]
        for alias in raw_affiliation_aliases:
            if any(
                alias == initial
                or alias in initial
                or initial in alias
                or (len(alias) >= 2 and len(initial) >= 2 and alias[:2] == initial[:2])
                for initial in initial_keys
            ):
                initial_keys.add(alias)
        seen: set[str] = set()
        selected: list[dict[str, Any]] = []
        for row in rows:
            name = str(row.get("name") or "").strip()
            key = re.sub(r"\s+", "", name).lower()
            strong = row.get('explicit_intake') or int(row.get('host_count') or 0) >= 2 or (
                int(row.get('source_count') or 0) >= 1 and int(row.get('max_score') or 0) >= 85)
            if not strong or (not row.get('explicit_intake') and re.match(r'^(?:在|任职于|曾任职于|并担任|同时担任|曾担任|担任)', name)):
                attempts = getattr(project, 'person_platform_attempts', None)
                if attempts is None:
                    attempts = []
                    project.person_platform_attempts = attempts
                attempts.append({'provider': 'person_routing', 'tool': 'affiliation_core_checks', 'subject': name,
                                 'status': 'not_queried', 'reason': 'weak_affiliation_candidate'})
                continue
            already_collected = any(key == initial or key in initial or initial in key for initial in initial_keys)
            if len(key) < 3 or key in seen or already_collected:
                continue
            seen.add(key)
            selected.append(row)
            if len(selected) >= limit:
                break
        if not selected:
            return 0

        _emit(
            emit,
            "structured_data",
            "person_affiliation_structured_agent",
            "启动人物直接关联企业受控穿透",
            "；".join(str(row.get("name") or "") for row in selected),
            affiliation_count=len(selected),
            recursion_depth=1,
            status="running",
        )
        added = 0
        jobs = []
        for selection_rank, row in enumerate(selected, 1):
            name = str(row.get("name") or "").strip()
            affiliation_context = {
                "person_name": intake.get("target_name") or project.target_name,
                "affiliation_name": name,
                "canonical_company_name": "",
                "relationship_type": row.get("relationship_type") or "待由原始证据确认",
                "relationship_evidence_source_ids": list(row.get("relationship_evidence_source_ids") or []),
                "relationship_evidence_hosts": list(row.get("relationship_evidence_hosts") or []),
                "relationship_confidence": row.get("relationship_confidence") or "medium",
                "recursion_depth": 1,
                "selection_rank": selection_rank,
                "selection_reason": (
                    f"关联线索（用户提供关系仍待核验）：独立域名{int(row.get('host_count') or 0)}个、"
                    f"来源{int(row.get('source_count') or 0)}条、最高可信度{int(row.get('max_score') or 0)}。"
                ),
                "filtering_note": "仅执行一跳受控穿透；平台返回的股东、子公司和投资企业仅作为线索，不继续递归采集。",
            }
            candidate_intake = dict(intake)
            candidate_intake.update(
                {
                    "target_type": "person",
                    "target_name": intake.get("target_name") or project.target_name,
                    "company_name": name,
                    "canonical_company_name": "",
                    "associated_company": name,
                    "structured_target": name,
                    "confirmed_person_affiliations": [],
                    "person_affiliation_context": affiliation_context,
                }
            )
            candidates = self._structured_entity_candidates(project, candidate_intake, name)
            person_key = re.sub(r"\s+", "", str(candidate_intake["target_name"] or "")).lower()
            candidates = [
                item
                for item in candidates
                if re.sub(r"\s+", "", item).lower() != person_key
                and (
                    not re.fullmatch(r"[0-9A-Z]{18}", item)
                    or self._credit_code_is_near_affiliation(project, name, item)
                )
            ]
            if not candidates:
                candidates = [name]
            candidate_intake["structured_target_candidates"] = candidates
            candidate_intake["structured_target"] = candidates[0]
            candidate_intake["canonical_company_name"] = candidates[0]
            affiliation_context["canonical_company_name"] = candidates[0]
            jobs.append((candidates[0], candidate_intake))
            _emit(
                emit,
                "structured_data",
                "person_affiliation_structured_agent",
                "人物关联机构查询计划已生成",
                name,
                affiliation=name,
                canonical_candidate=candidates[0],
                sources_added=0,
                recursion_depth=1,
                status="planned",
            )
        try:
            from .person_platforms import collect_group
        except ImportError:
            from person_platforms import collect_group
        added += collect_group(self, db, project, jobs, emit)
        return added

    def _credit_code_is_near_affiliation(
        self,
        project: ResearchProject,
        affiliation: str,
        credit_code: str,
    ) -> bool:
        """Reject credit codes copied from an unrelated company in the same project."""
        name_key = re.sub(r"\s+", "", str(affiliation or "")).lower()
        if len(name_key) < 3 or not re.fullmatch(r"[0-9A-Z]{18}", str(credit_code or "")):
            return False
        for source in list(getattr(project, "sources", []) or [])[:500]:
            meta = source.source_metadata or {}
            text = "\n".join(
                str(value or "")[:12000]
                for value in (
                    source.title,
                    source.summary,
                    source.content,
                    meta.get("ocr_text"),
                    meta.get("vision_text"),
                )
                if value
            )
            compact = re.sub(r"\s+", "", text).lower()
            code_key = credit_code.lower()
            start = 0
            while True:
                position = compact.find(name_key, start)
                if position < 0:
                    break
                window = compact[max(0, position - 300): position + len(name_key) + 300]
                if code_key in window:
                    return True
                start = position + len(name_key)
        return False

    def _collect_qcc_sources(self, db: Session, project: ResearchProject, target: str, intake: dict[str, Any], emit: TraceEmitter | None = None) -> int:
        token = os.getenv("QCC_API_KEY", "").strip()
        audit = self._company_platform_audit(project, intake, target, "qcc", token)
        audit.planned(["get_company_registration_info", "get_shareholder_info", "get_key_personnel",
                       "get_company_profile", "get_company_risk_scan", "get_administrative_penalty", "get_recruitment_info"])
        if not token:
            audit.stop_reason = "not_configured"
            audit.finish_unqueried()
            _emit(emit, "structured_data", "qcc_mcp_agent", "企查查 API Key 为空，跳过", "", status="skipped")
            return 0
        if token.lower().startswith("bearer "):
            token = token.split(None, 1)[1].strip()
        headers = {"Authorization": f"Bearer {token}"}
        timeout = _env_int("STRUCTURED_SOURCE_TIMEOUT_SECONDS", 45, 10, 180)
        endpoints = [
            ("qcc_company", os.getenv("QCC_MCP_COMPANY_URL", "https://agent.qcc.com/mcp/company/stream"), [
                ("get_company_registration_info", "公司背景"),
                ("get_shareholder_info", "股东高管"),
                ("get_key_personnel", "管理团队"),
                ("get_company_profile", "公司背景"),
            ]),
            ("qcc_risk", os.getenv("QCC_MCP_RISK_URL", "https://agent.qcc.com/mcp/risk/stream"), [
                ("get_company_risk_scan", "诉讼/制裁"),
                ("get_administrative_penalty", "诉讼/制裁"),
            ]),
            ("qcc_operation", os.getenv("QCC_MCP_OPERATION_URL", "https://agent.qcc.com/mcp/operation/stream"), [
                ("get_recruitment_info", "主营业务真实经营情况核验"),
            ]),
        ]
        if os.getenv("QCC_ENABLE_IPR_TOOLS", "false").strip().lower() in {"1", "true", "yes", "on"}:
            endpoints.append(("qcc_ipr", os.getenv("QCC_MCP_IPR_URL", "https://agent.qcc.com/mcp/ipr/stream"), [("get_patents", "技术实力")]))
            audit.planned(["get_patents"])
        if audit.cached_failure():
            self._emit_platform_stop(audit, emit)
            return 0
        added = 0
        candidates = intake.get("structured_target_candidates") or [target]
        disabled_tools: set[str] = set()
        company_risk = self._standardize_target_type(project, intake, target) == "company"
        if company_risk:
            project.company_judicial_query_attempts = []
        for provider, url, tools in endpoints:
            session, ok, error = audit.initialize(self._mcp_initialize, url, headers, timeout=timeout)
            if not ok:
                if audit.result(provider + "初始化", {}, {"error": error}):
                    self._emit_platform_stop(audit, emit)
                    return added
                for tool, _ in tools:
                    audit.record(tool, {}, "not_queried", "initialization_failed")
                if company_risk and provider == "qcc_risk":
                    project.company_judicial_query_attempts.append({"tool": "qcc_risk初始化", "status": "failed"})
                _emit(emit, "structured_data", "qcc_mcp_agent", "企查查 MCP 初始化失败", error, status="warning")
                continue
            for index, (tool, module) in enumerate(tools, 1):
                if tool in disabled_tools:
                    continue
                saved = False
                failed = False
                for candidate in candidates:
                    payload, session = audit.call(self._mcp_call_tool, url, headers, tool, {"searchKey": candidate}, session=session, request_id=10 + index, timeout=timeout)
                    if audit.result(tool, {"searchKey": candidate}, payload):
                        self._emit_platform_stop(audit, emit)
                        return added
                    if payload.get("error"):
                        failed = True
                        if self._mcp_error_is_disabled_tool(payload):
                            disabled_tools.add(tool)
                            saved = True
                            break
                        _emit(emit, "structured_data", "qcc_mcp_agent", "企查查工具调用失败", f"{tool}: {json.dumps(payload, ensure_ascii=False)[:400]}", status="warning")
                        continue
                    text = self._extract_mcp_text(payload, preserve_company_risk=True) if company_risk and provider == "qcc_risk" else self._extract_mcp_text(payload)
                    query_meta = {"tool": tool, "target": target, "query": candidate,
                                  "query_status": "success", "retrieved_at": datetime.now().isoformat(timespec="seconds")}
                    if company_risk and provider == "qcc_risk":
                        query_meta["company_qcc_raw_response"] = payload
                        from company_risk import drilldown_tools, document_requests
                        scan_entity_ok, _ = self._structured_entity_matches_request(text, query_meta, intake)
                        if tool == "get_company_risk_scan" and scan_entity_ok:
                            queued = {name for name, _module in tools}
                            tools.extend((name, "诉讼/制裁") for name in drilldown_tools(text) if name not in queued)
                            audit.planned([name for name, _module in tools])
                        if tool == "get_judicial_documents" and scan_entity_ok:
                            for case_number, document_id in document_requests(text):
                                detail, session = audit.call(self._mcp_call_tool, url, headers, "get_judicial_document_detail",
                                    {"searchKey": candidate, "documentId": document_id, "section": "全部"},
                                    session=session, request_id=100 + index, timeout=timeout)
                                if audit.result("get_judicial_document_detail", {"searchKey": candidate,
                                                "documentId": document_id, "section": "全部"}, detail):
                                    # The list already returned successfully. A failed
                                    # detail lookup must not discard that original.
                                    if self._save_structured_source(db, project, provider, module,
                                        f"企查查-{tool}-{target}", text, query_meta, emit=emit, intake=intake):
                                        added += 1
                                    self._emit_platform_stop(audit, emit)
                                    return added
                                if not detail.get("error"):
                                    detail_text = self._extract_mcp_text(detail, preserve_company_risk=True)
                                    if self._save_structured_source(db, project, provider, module,
                                        f"企查查-get_judicial_document_detail-{case_number}-{target}", detail_text,
                                        {**query_meta, "company_qcc_raw_response": detail, "tool": "get_judicial_document_detail", "case_number": case_number,
                                         "document_id": document_id}, emit=emit, intake=intake):
                                        added += 1
                    if self._save_structured_source(db, project, provider, module, f"企查查-{tool}-{target}", text, query_meta, emit=emit, intake=intake):
                        added += 1
                        saved = True
                        break
                if not saved and not failed:
                    _emit(
                        emit,
                        "structured_data",
                        "qcc_mcp_agent",
                        "企查查未命中有效数据",
                        f"{tool}: tried={', '.join(str(item) for item in candidates[:5])}",
                        status="warning",
                    )
        return added

    def _collect_tyc_sources(self, db: Session, project: ResearchProject, target: str, intake: dict[str, Any], emit: TraceEmitter | None = None) -> int:
        api_key = (os.getenv("TYC_API_KEY") or os.getenv("TENC_API_KEY") or "").strip()
        audit = self._company_platform_audit(project, intake, target, "tyc", api_key)
        audit.planned(["search_companies", "get_company_basic_profile", "get_company_people", "get_company_group_profile", "search_patents"])
        if not api_key:
            audit.stop_reason = "not_configured"
            audit.finish_unqueried()
            _emit(emit, "structured_data", "tyc_mcp_agent", "天眼查 API Key 为空，跳过", "", status="skipped")
            return 0
        if audit.cached_failure():
            self._emit_platform_stop(audit, emit)
            return 0
        url = os.getenv("TYC_MCP_URL", "https://mcp.tianyancha.com/v1").strip()
        headers = {"Authorization": api_key}
        timeout = _env_int("STRUCTURED_SOURCE_TIMEOUT_SECONDS", 45, 10, 180)
        session, ok, error = audit.initialize(self._mcp_initialize, url, headers, timeout=timeout)
        if not ok:
            audit.result("initialize", {}, {"error": error})
            audit.stop_reason = audit.stop_reason or "initialization_failed"
            audit.finish_unqueried()
            _emit(emit, "structured_data", "tyc_mcp_agent", "天眼查 MCP 初始化失败", error, status="warning")
            return 0
        added = 0
        candidates = intake.get("structured_target_candidates") or [target]
        anchor = {"company_name": target, "company_id": ""}
        for candidate in candidates:
            payload, session = audit.call(self._mcp_call_tool, url, headers, "search_companies", {"query": candidate, "page": 1, "page_size": 5}, session=session, request_id=20, timeout=timeout)
            if audit.result("search_companies", {"query": candidate, "page": 1, "page_size": 5}, payload):
                self._emit_platform_stop(audit, emit)
                return added
            if payload.get("error"):
                _emit(emit, "structured_data", "tyc_mcp_agent", "天眼查搜索失败", json.dumps(payload, ensure_ascii=False)[:400], status="warning")
                continue
            text = self._extract_mcp_text(payload)
            if self._save_structured_source(db, project, "tyc", "公司背景", f"天眼查-search_companies-{target}", text, {"tool": "search_companies", "target": target, "query": candidate}, emit=emit, intake=intake):
                added += 1
            anchor = self._extract_tyc_company_anchor(text, candidate)
            if anchor.get("company_id") or anchor.get("company_name") != candidate:
                break
        subject_args = {"company_name": anchor.get("company_name") or target}
        if anchor.get("company_id"):
            subject_args["company_id"] = anchor["company_id"]
        detail_tools = [
            ("get_company_basic_profile", "公司背景", subject_args),
            ("get_company_people", "管理团队", subject_args),
            ("get_company_group_profile", "股东高管", subject_args),
            ("search_patents", "技术实力", {"query": subject_args["company_name"], "applicant": subject_args["company_name"], "page": 1, "page_size": 20}),
        ]
        for index, (tool, module, args) in enumerate(detail_tools, 1):
            payload, session = audit.call(self._mcp_call_tool, url, headers, tool, args, session=session, request_id=30 + index, timeout=timeout)
            if audit.result(tool, args, payload):
                self._emit_platform_stop(audit, emit)
                return added
            if payload.get("error"):
                _emit(emit, "structured_data", "tyc_mcp_agent", "天眼查工具调用失败", f"{tool}: {json.dumps(payload, ensure_ascii=False)[:400]}", status="warning")
                continue
            text = self._extract_mcp_text(payload)
            if self._save_structured_source(db, project, "tyc", module, f"天眼查-{tool}-{target}", text, {"tool": tool, "target": target, "query": subject_args.get("company_name"), "company_id": subject_args.get("company_id", "")}, emit=emit, intake=intake):
                added += 1
        return added

    def _collect_xiniu_sources(self, db: Session, project: ResearchProject, target: str, intake: dict[str, Any], emit: TraceEmitter | None = None) -> int:
        api_key = os.getenv("XINIU_API_KEY", "").strip()
        audit = self._company_platform_audit(project, intake, target, "xiniu", api_key)
        aspects = [
            ("企业基本信息", "公司背景"),
            ("融资状况分析", "融资情报"),
            ("市场与行业分析", "行业口碑、产品认可度与同业竞争地位研判"),
            ("团队人物及招聘分析", "管理团队"),
            ("风险评估", "风险核查"),
        ]
        audit.planned(["get_company_info:" + aspect for aspect, _module in aspects])
        if not api_key:
            audit.stop_reason = "not_configured"
            audit.finish_unqueried()
            return 0
        if audit.cached_failure():
            self._emit_platform_stop(audit, emit)
            return 0
        base_url = os.getenv("XINIU_MCP_URL", "https://vip.xiniudata.com/mcp").strip()
        url = base_url if "api_key=" in base_url else f"{base_url}{'&' if '?' in base_url else '?'}{urlencode({'api_key': api_key})}"
        timeout = _env_int("STRUCTURED_SOURCE_TIMEOUT_SECONDS", 45, 10, 180)
        session, ok, error = audit.initialize(self._mcp_initialize, url, {}, timeout=timeout)
        if not ok:
            audit.result("initialize", {}, {"error": error})
            audit.stop_reason = audit.stop_reason or "initialization_failed"
            audit.finish_unqueried()
            _emit(emit, "structured_data", "xiniu_mcp_agent", "稀牛 MCP 初始化失败", error, status="warning")
            return 0
        added = 0
        raw_candidates = intake.get("structured_target_candidates") or [target]
        candidates: list[str] = []
        for value in [intake.get("canonical_company_name"), intake.get("company_name"), *raw_candidates]:
            text = str(value or "").strip()
            if text and text not in candidates and not re.fullmatch(r"[0-9A-Z]{18}", text):
                candidates.append(text)
        for index, (aspect, module) in enumerate(aspects, 1):
            saved = False
            for candidate in candidates:
                payload, session = audit.call(self._mcp_call_tool, url, {}, "get_company_info", {"firm_name": candidate, "aspect": aspect}, session=session, request_id=30 + index, timeout=timeout)
                if audit.result("get_company_info:" + aspect, {"firm_name": candidate, "aspect": aspect}, payload):
                    self._emit_platform_stop(audit, emit)
                    return added
                if payload.get("error"):
                    _emit(emit, "structured_data", "xiniu_mcp_agent", "稀牛工具调用失败", json.dumps(payload, ensure_ascii=False)[:400], status="warning")
                    error_text = json.dumps(payload, ensure_ascii=False).lower()
                    if any(marker in error_text for marker in ("余额不足", "配额", "quota", "insufficient", "invalid_token", "unauthorized")):
                        _emit(emit, "structured_data", "xiniu_mcp_agent", "稀牛账号额度或权限不可用，停止本轮调用", "平台调用失败不是目标企业无记录。", status="warning")
                        return added
                    continue
                text = self._extract_mcp_text(payload)
                if self._save_structured_source(db, project, "xiniu", module, f"稀牛-{aspect}-{target}", text, {"tool": "get_company_info", "aspect": aspect, "target": target, "query": candidate}, emit=emit, intake=intake):
                    added += 1
                    saved = True
                    break
            if not saved and "get_company_info:" + aspect not in audit.failed_tools:
                _emit(emit, "structured_data", "xiniu_mcp_agent", "稀牛未命中有效数据", aspect, status="warning")
        return added
    def collect_web_sources(
        self,
        db: Session,
        project: ResearchProject,
        search_queries: list[str],
        focus_questions: list[str],
        max_results_per_query: int,
        emit: TraceEmitter | None = None,
        plan: dict[str, Any] | None = None,
        intake: dict[str, Any] | None = None,
        reuse_archived: bool = True,
        pause_requested: Callable[[], bool] | None = None,
    ) -> int:
        intake = intake or self._normalize_intake(project, {}, search_queries, focus_questions)
        plan = plan or self.plan_research(project, intake, emit=emit)
        if intake.get("ai_search_enabled") is False:
            _emit(emit, "web_search", "online_search_agent", "AI 在线检索已关闭，跳过", "", status="skipped")
            return 0

        expanded_query_items = self._expand_search_queries(plan, intake)
        discovered_company_recalls: set[str] = set()
        if str(intake.get("target_type") or "").lower() == "company":
            from report_agents.company_risk_register import recall_discovery_queries
            from report_agents.company_assessment import assessment_discovery_queries
            expanded_query_items = recall_discovery_queries(list(project.sources or []),
                str(intake.get("target_name") or project.target_name or ""), discovered_company_recalls) + assessment_discovery_queries(
                str(intake.get("target_name") or project.target_name or "")) + expanded_query_items
        if intake.get('target_type')=='industry' and plan.get('evidence_requirements') and not intake.get('search_queries'):
            active=self._active_industry_sources(project)
            counts=Counter(str((s.source_metadata or {}).get('module') or '') for s in active if (s.content or '').strip())
            minimum=int((plan.get('coverage_thresholds') or {}).get('min_sources_per_module') or FIXED_MIN_SOURCES_PER_MODULE)
            if active and all(counts.get(m['name'],0)>=minimum for m in plan.get('modules',[])):
                gaps=self._industry_retrieval_gaps(project,plan)
                if gaps:
                    expanded_query_items=self._gap_queries(plan,intake,gaps)
                    _emit(emit,'web_search','coverage_agent','复用已有来源，仅补采指标证据缺口',
                          f'queries={len(expanded_query_items)}',status='running')
        person_mode = str(intake.get("target_type") or "").lower() == "person"
        authority_queries = [item for item in expanded_query_items if item.get("search_tier") == "authority_first"]
        pending_open_web_queries = [item for item in expanded_query_items if item.get("search_tier") != "authority_first"] if authority_queries else []
        query_items = authority_queries or expanded_query_items
        max_rounds = max(1, int(intake.get("max_search_rounds") or FIXED_MAX_SEARCH_ROUNDS))
        if pending_open_web_queries:
            if intake.get("target_type") == "industry" and max_rounds == 1:
                query_items = expanded_query_items
                pending_open_web_queries = []
            else:
                max_rounds = max(2, max_rounds)
        browser_fetch_budget = _env_int("WEB_RENDER_FETCH_BUDGET_PER_RUN", 3, 0, 500)
        browser_fetch_used = 0
        person_fetch_used = 0
        person_fetch_per_chapter = Counter()
        person_fetch_budget = _env_int("PERSON_WEB_FETCH_BUDGET", 44, 0, 200)

        added = 0
        discovered_affiliations: set[str] = set()
        discovered_company_diligence: set[str] = set()
        active_sources = self._active_industry_sources(project)
        seen_urls = {s.url for s in active_sources if s.url and (s.source_metadata or {}).get("retention_policy") != "record_only"}
        host_counts: defaultdict[str, int] = defaultdict(int)
        authority_host_counts: defaultdict[str, int] = defaultdict(int)
        tech_content_saved = 0
        for existing_source in active_sources:
            existing_host = urlparse(existing_source.url or "").netloc.lower().replace("www.", "")
            if existing_host:
                host_counts[existing_host] += 1
            existing_meta = existing_source.source_metadata or {}
            existing_text = f"{existing_source.title} {existing_source.content or existing_source.summary or ''}"
            if self._is_technical_content_source(existing_host, existing_source.title or "", existing_text, str(existing_meta.get("query") or "")):
                tech_content_saved += 1
        max_per_host = _env_int("ONLINE_SOURCE_MAX_PER_HOST", 8, 1, 100)
        max_authority_per_host = _env_int("ONLINE_AUTHORITY_SOURCE_MAX_PER_HOST", 12, 1, 100)
        max_tech_sources = _env_int("ONLINE_TECH_SOURCE_MAX_PER_PROJECT", 25, 0, 500)
        configured_providers = [
            name
            for name, _engine in getattr(web_search_provider, "engines", [])
            if os.getenv(f"{name.upper()}_API_KEY")
        ]
        active_provider = os.getenv("WEB_SEARCH_PROVIDER", "").strip().lower()
        if active_provider in {"tavily", "serper", "exa", "serpapi", "brave", "bocha"}:
            configured_providers = [active_provider] if os.getenv(f"{active_provider.upper()}_API_KEY") else []
        _emit(
            emit,
            "web_search",
            "online_search_agent",
            "在线检索 Agent 启动",
            f"providers={','.join(configured_providers) or 'none'}, query_count={len(query_items)}, rounds={max_rounds}",
            providers=configured_providers,
            status="running",
        )
        person_search = PersonSearchSession(intake, configured_providers) if person_mode else None
        if person_search:
            # The first round spans the full template, rather than consuming the
            # budget with authority variants for only a few chapters.
            query_items = expanded_query_items
            pending_open_web_queries = []
        industry_query_history = []
        industry_seen_queries = set()
        for round_index in range(1, max_rounds + 1):
            if pause_requested and pause_requested():
                raise WorkflowPaused("任务已暂停")
            round_added = 0
            if intake.get("target_type") == "industry":
                budget = _env_int("INDUSTRY_SEARCH_QUERY_BUDGET", 80, 10, 200)
                try:
                    from .industry_research import unique_search_queries
                except ImportError:
                    from industry_research import unique_search_queries
                query_items = unique_search_queries(query_items, industry_seen_queries)
                used = sum(len(batch) for batch in industry_query_history)
                query_items = query_items[:max(0, budget - used)]
                if not query_items:
                    _emit(emit, "web_search", "coverage_agent", "行业检索预算已用完，保留证据缺口", f"query_budget={budget}", status="warning")
                    break
                industry_query_history.append(query_items)
            if person_search:
                query_items = person_search.choose(query_items, round_index, list(project.sources or []))
                if not query_items:
                    break
            _emit(emit, "web_search", "online_search_agent", "开始在线检索", "", status="running")
            search_batches = self._search_query_items_parallel(
                query_items,
                max_results_per_query,
                configured_providers,
                emit,
                pause_requested,
            )
            if person_search:
                person_search.record(search_batches)
            for query_item, results in search_batches:
                if pause_requested and pause_requested():
                    raise WorkflowPaused("任务已暂停")
                query = query_item["query"]
                module = query_item.get("module", "general")
                search_tier = query_item.get("search_tier", "open_web")
                include_domains = list(query_item.get("include_domains") or [])
                for item in results:
                    try:
                        url = item.get("url", "")
                        item_metadata = item.get("metadata") or {}
                        provider_name = item_metadata.get("provider", "unknown")
                        title = item.get("title") or url or query
                        platform_name = self._detect_platform(url, title)
                        host = urlparse(url or "").netloc.lower().replace("www.", "")
                        pre_source_type = self._detect_source_type(host, title, url)
                        if person_mode and search_tier != "authority_first":
                            low_quality, low_quality_reason = self._is_low_quality_open_web_source(
                                host,
                                title,
                                url,
                                pre_source_type,
                                query=query,
                                module=module,
                            )
                            if low_quality:
                                if url:
                                    seen_urls.add(url)
                                _emit(
                                    emit,
                                    "web_search",
                                    "online_search_agent",
                                    "跳过低质量开放网页来源",
                                    f"[{platform_name}] {title} | {low_quality_reason}",
                                    query=query,
                                    url=url,
                                    module=module,
                                    provider=provider_name,
                                    platform=platform_name,
                                    skip_reason=low_quality_reason,
                                    status="skipped",
                                )
                                continue
                        if url and url in seen_urls:
                            _emit(
                                emit,
                                "web_search",
                                "online_search_agent",
                                "跳过重复网页",
                                f"[{platform_name}] {url}",
                                query=query,
                                url=url,
                                module=module,
                                provider=provider_name,
                                platform=platform_name,
                                status="skipped",
                            )
                            continue
                        reused_source = None
                        if url and reuse_archived and os.getenv("REUSE_ARCHIVED_WEB_SOURCES", "true").strip().lower() in {"1", "true", "yes", "on"}:
                            reused_source = (
                                db.query(ResearchSource)
                                .filter(ResearchSource.url == url, ResearchSource.project_id != project.id)
                                .order_by(ResearchSource.created_at.desc())
                                .first()
                            )
                        if reused_source:
                            identity = self._person_source_identity_confidence(
                                title or reused_source.title,
                                reused_source.content or reused_source.summary,
                                intake,
                            )
                            if identity["confidence"] == "rejected":
                                seen_urls.add(url)
                                _emit(
                                    emit,
                                    "web_search",
                                    "online_search_agent",
                                    "跳过人物身份不匹配的归档来源",
                                    title or reused_source.title,
                                    query=query,
                                    url=url,
                                    module=module,
                                    skip_reason="person_identity_mismatch",
                                    status="skipped",
                                )
                                continue
                            reused_meta = dict(reused_source.source_metadata or {})
                            metadata = {
                                **reused_meta,
                                "query": query,
                                "module": module,
                                "person_chapters": list(query_item.get("person_chapters") or []),
                                "person_commission_id": query_item.get("commission_id", ""),
                                "person_requirement_ids": list(query_item.get("requirement_ids") or []),
                                "round": round_index,
                                "search_tier": search_tier,
                                "authority_domains": include_domains,
                                "authority_required": int(query_item.get("authority_required") or 0),
                                "evidence_scope": query_item.get("evidence_scope") or reused_meta.get("evidence_scope") or "",
                                "industry_name": query_item.get("industry_name") or reused_meta.get("industry_name") or "",
                                "segment_name": query_item.get("segment_name") or reused_meta.get("segment_name") or "",
                                "company_role": query_item.get("company_role") or reused_meta.get("company_role") or "",
                                "identity_confidence": identity["confidence"],
                                "identity_reason": identity["reason"],
                                "identity_anchors": identity["matched_anchors"],
                                "identity_policy_version": identity.get("identity_policy_version", PERSON_IDENTITY_POLICY_VERSION),
                            **({"person_intake_fingerprint": self._intake_evidence_fingerprint(intake)} if person_mode else {}),
                                "identity_status": "quarantined" if identity["confidence"] == "low" else "accepted",
                                **({"industry_scope_fingerprint": getattr(project, "industry_scope_fingerprint", scope_fingerprint(intake, source_only=True))} if intake.get("target_type") == "industry" else {}),
                                "reused_from_source_id": reused_source.id,
                                "reused_from_project_id": reused_source.project_id,
                                "content_kind": reused_meta.get("content_kind", "reused_full_text"),
                                "extraction_status": "reused_archive",
                            }
                            source = ResearchSource(
                                project_id=project.id,
                                source_type=reused_source.source_type,
                                title=title or reused_source.title,
                                url=url,
                                object_key=reused_source.object_key,
                                content=reused_source.content,
                                summary=reused_source.summary,
                                source_metadata=metadata,
                                credibility_score=reused_source.credibility_score,
                            )
                            db.add(source)
                            db.commit()
                            seen_urls.add(url)
                            host = urlparse(url or "").netloc.lower().replace("www.", "")
                            if host:
                                host_counts[host] += 1
                                if search_tier == "authority_first":
                                    authority_host_counts[host] += 1
                            added += 1
                            round_added += 1
                            _emit(
                                emit,
                                "web_search",
                                "online_search_agent",
                                "复用已归档网页来源",
                                f"[{platform_name}] {title or reused_source.title}",
                                query=query,
                                url=url,
                                module=module,
                                provider=provider_name,
                                platform=platform_name,
                                reused_from_source_id=reused_source.id,
                                status="done",
                            )
                            continue
                        host = urlparse(url or "").netloc.lower().replace("www.", "")
                        active_host_limit = max_authority_per_host if search_tier == "authority_first" else max_per_host
                        active_host_count = authority_host_counts[host] if search_tier == "authority_first" else host_counts[host]
                        if host and active_host_count >= active_host_limit:
                            if url:
                                seen_urls.add(url)
                            _emit(
                                emit,
                                "web_search",
                                "online_search_agent",
                                "跳过同域名过量来源",
                                f"{host} >= {active_host_limit}",
                                query=query,
                                url=url,
                                module=module,
                                provider=provider_name,
                                platform=platform_name,
                                status="skipped",
                            )
                            continue
                        raw_content = item.get("content") or ""
                        summary = item.get("summary") or ""
                        content = raw_content or summary or ""
                        item_metadata = dict(item_metadata)
                        min_online_chars = _env_int("ONLINE_SOURCE_MIN_CONTENT_CHARS", 600, 80, 5000)
                        cleaned_probe = self._clean_source_text(content)
                        summary_probe = self._clean_source_text(summary)
                        should_refetch = bool(
                            url
                            and (
                                self._is_pdf_url(url)
                                or len(cleaned_probe) < min_online_chars
                                or (summary_probe and cleaned_probe == summary_probe)
                            )
                        )
                        if person_mode and should_refetch:
                            chapter_key = next(iter(query_item.get("person_chapters") or [2]))
                            round_limit = 2 if round_index == 1 else 1
                            should_refetch = (person_fetch_used < person_fetch_budget
                                              and person_fetch_per_chapter[(chapter_key, round_index)] < round_limit)
                            if should_refetch:
                                person_fetch_used += 1
                                person_fetch_per_chapter[(chapter_key, round_index)] += 1
                        if should_refetch:
                            allow_browser = browser_fetch_used < browser_fetch_budget
                            _emit(
                                emit,
                                "web_search",
                                "online_search_agent",
                                "网页正文抓取开始",
                                f"[{platform_name}] {title} | browser={allow_browser}",
                                query=query,
                                url=url,
                                module=module,
                                provider=provider_name,
                                platform=platform_name,
                                browser_fetch_allowed=allow_browser,
                                status="running",
                            )
                            fetch_options = {'document_profile': 'company'} if project.target_type == 'company' else {}
                            fetched = self._fetch_web_url_with_timeout(url, allow_browser=allow_browser, emit=emit, **fetch_options)
                            _emit(
                                emit,
                                "web_search",
                                "online_search_agent",
                                "网页正文抓取完成",
                                f"[{platform_name}] {title} | fetch={fetched.get('status', 'empty')}, chars={len(fetched.get('content') or '')}",
                                query=query,
                                url=url,
                                module=module,
                                provider=provider_name,
                                platform=platform_name,
                                fetch_status=fetched.get("status", "empty"),
                                fetch_attempt=fetched.get("fetch_attempt", ""),
                                fetched_chars=len(fetched.get("content") or ""),
                                status="done" if fetched.get("content") else "warning",
                            )
                            if fetched.get("fetch_attempt") == "browser":
                                browser_fetch_used += 1
                            fetched_text = fetched.get("content") or ""
                            if person_mode and fetched.get("status") == "done" and fetched_text:
                                item_metadata["person_discovery_only"] = False
                            fetched_clean = self._clean_source_text(fetched_text)
                            item_metadata.update(
                                {
                                    "fetch_status": fetched.get("status", "empty"),
                                    "fetch_error": fetched.get("error", ""),
                                    "fetched_chars": len(fetched_text),
                                    "fetched_content_type": fetched.get("content_type", ""),
                                    "fetched_pages": fetched.get("pages", 0),
                                    "fetch_attempt": fetched.get("fetch_attempt", ""),
                                    "browser_fetch_allowed": allow_browser,
                                }
                            )
                            if fetched.get("images"):
                                item_metadata["images"] = fetched.get("images")
                            for document_key in ('document_pages', 'document_extraction'):
                                if fetched.get(document_key) is not None:
                                    item_metadata[document_key] = fetched[document_key]
                            if len(fetched_clean) > len(cleaned_probe) or (project.target_type in {'company', 'person'} and fetched.get('status') == 'done' and fetched_clean):
                                content = fetched_text
                                raw_content = fetched_text
                                cleaned_probe = fetched_clean
                                item["content"] = content
                                if not summary:
                                    summary = fetched_clean[:500]
                                    item["summary"] = summary
                        item["metadata"] = item_metadata
                        identity = self._person_source_identity_confidence(title, content or summary, intake)
                        if identity["confidence"] == "rejected":
                            if url:
                                seen_urls.add(url)
                            _emit(
                                emit,
                                "web_search",
                                "online_search_agent",
                                "跳过人物身份不匹配来源",
                                title,
                                query=query,
                                url=url,
                                module=module,
                                provider=provider_name,
                                skip_reason="person_identity_mismatch",
                                status="skipped",
                            )
                            continue
                        quality = self.score_source(item, module=module, query=query, target=intake.get("target_name", project.target_name))
                        is_tech_source = self._is_technical_content_source(host, title, content or summary, query)
                        if is_tech_source and tech_content_saved >= max_tech_sources:
                            if url:
                                seen_urls.add(url)
                            _emit(
                                emit,
                                "web_search",
                                "online_search_agent",
                                "跳过技术资料过量来源",
                                f"tech_sources={tech_content_saved}, limit={max_tech_sources}",
                                query=query,
                                url=url,
                                module=module,
                                provider=provider_name,
                                platform=platform_name,
                                status="skipped",
                            )
                            continue
                        content_kind = "full_text"
                        if not cleaned_probe:
                            content_kind = "empty_content"
                        elif self._is_pdf_url(url) and item_metadata.get("fetch_status") == "done":
                            content_kind = "pdf_text_extracted"
                        elif len(cleaned_probe) < min_online_chars:
                            content_kind = "low_content"
                        elif summary_probe and cleaned_probe == summary_probe:
                            content_kind = "summary_only"
                        metadata = {
                            "query": query,
                            "module": module,
                                "person_chapters": list(query_item.get("person_chapters") or []),
                                "person_commission_id": query_item.get("commission_id", ""),
                                "person_requirement_ids": list(query_item.get("requirement_ids") or []),
                            "round": round_index,
                            "search_tier": search_tier,
                            "authority_domains": include_domains,
                            "authority_required": int(query_item.get("authority_required") or 0),
                            "evidence_scope": query_item.get("evidence_scope") or "",
                            "diligence_entity": query_item.get("diligence_entity") or "",
                            "diligence_relationship_source": query_item.get("diligence_relationship_source") or "",
                            "recall_entity": query_item.get("recall_entity") or "",
                            "recall_relationship_source": query_item.get("recall_relationship_source") or "",
                            "industry_name": query_item.get("industry_name") or "",
                            "segment_name": query_item.get("segment_name") or "",
                            "company_role": query_item.get("company_role") or "",
                            "company_name": query_item.get("company_name") or "",
                            "geography": query_item.get("geography") or "",
                            "as_of_date": query_item.get("as_of_date") or "",
                            "identity_confidence": identity["confidence"],
                            "identity_reason": identity["reason"],
                            "identity_anchors": identity["matched_anchors"],
                            "identity_policy_version": identity.get("identity_policy_version", PERSON_IDENTITY_POLICY_VERSION),
                            **({"person_intake_fingerprint": self._intake_evidence_fingerprint(intake)} if person_mode else {}),
                            "identity_status": "quarantined" if identity["confidence"] == "low" else "accepted",
                            "quality": quality,
                            "platform": platform_name,
                            "content_kind": content_kind,
                            "extraction_status": item_metadata.get("fetch_status") or ("search_content" if cleaned_probe else "empty"),
                            **item_metadata,
                            **({"industry_scope_fingerprint": getattr(project, "industry_scope_fingerprint", scope_fingerprint(intake, source_only=True))} if intake.get("target_type") == "industry" else {}),
                        }
                        fetch_status = metadata.get("fetch_status", "")
                        detail = f"[{platform_name}] {title}（搜索工具：{provider_name}）"
                        if fetch_status:
                            detail += f" | fetch={fetch_status}, chars={metadata.get('fetched_chars', 0)}"
                        _emit(
                            emit,
                            "web_search",
                            "online_search_agent",
                            "命中网页，准备归档",
                            detail,
                            query=query,
                            url=url,
                            title=title,
                            module=module,
                            provider=provider_name,
                            platform=platform_name,
                            fetch_status=fetch_status,
                            content_chars=len(content),
                            quality_score=quality["score"],
                            status="running",
                        )
                        stored_text = content.strip()
                        if not stored_text:
                            stored_text = "\n".join(
                                part
                                for part in [
                                    f"标题：{title}",
                                    f"URL：{url}",
                                    f"摘要：{summary}",
                                ]
                                if part and part.split("：", 1)[-1].strip()
                            ).strip()
                        stored_clean = self._clean_source_text(stored_text)
                        summary_clean = self._clean_source_text(summary)
                        if quality["source_type"] == "news":
                            # News is often returned as a concise but useful
                            # search abstract.  Admit a slightly thinner item as
                            # a B-level lead; hard conclusions still require
                            # corroboration during chapter writing.
                            min_store_chars = _env_int("ONLINE_NEWS_MIN_STORE_CHARS", 80, 20, 2000)
                            min_summary_chars = _env_int("ONLINE_NEWS_MIN_SUMMARY_CHARS", 50, 20, 1000)
                        else:
                            min_store_chars = _env_int("ONLINE_SOURCE_MIN_STORE_CHARS", 120, 20, 2000)
                            min_summary_chars = _env_int("ONLINE_SOURCE_MIN_SUMMARY_CHARS", 80, 20, 1000)
                        if fetch_status in {"empty", "empty_pdf", "browser_empty", "reader_empty"} and len(stored_clean) < min_store_chars:
                            if len(summary_clean) < min_summary_chars:
                                if url:
                                    seen_urls.add(url)
                                _emit(
                                    emit,
                                    "web_search",
                                    "online_search_agent",
                                    "跳过空正文网页",
                                    f"[{platform_name}] {title} | fetch={fetch_status}, chars={metadata.get('fetched_chars', 0)}",
                                    query=query,
                                    url=url,
                                    module=module,
                                    provider=provider_name,
                                    platform=platform_name,
                                    fetch_status=fetch_status,
                                    skip_reason="empty_content",
                                    status="skipped",
                                )
                                continue
                            stored_text = "\n".join(
                                part
                                for part in [
                                    f"标题：{title}",
                                    f"URL：{url}",
                                    f"摘要：{summary_clean}",
                                ]
                                if part and part.split("：", 1)[-1].strip()
                            ).strip()
                            metadata["content_kind"] = "summary_only"
                            metadata["extraction_status"] = fetch_status
                            metadata["skip_fulltext_reason"] = "fetch_empty_saved_summary"
                        try:
                            from .json_utils import strip_nul
                        except ImportError:
                            from json_utils import strip_nul
                        title, summary, stored_text, metadata = strip_nul([str(title or ''), str(summary or ''), stored_text, metadata])
                        metadata["retention_policy"] = "transient_web_body"
                        object_key = research_store.put_text(
                            f"projects/{project.id}/raw_web/{_now_key()}_{added}.txt",
                            stored_text,
                        )
                        source = ResearchSource(
                            project_id=project.id,
                            source_type=quality["source_type"],
                            title=title,
                            url=url,
                            object_key=object_key,
                            content=stored_text,
                            summary=summary or stored_text[:500],
                            source_metadata=metadata,
                            credibility_score=quality["score"],
                        )
                        db.add(source)
                        db.commit()
                        if url:
                            seen_urls.add(url)
                        if host:
                            host_counts[host] += 1
                            if search_tier == "authority_first":
                                authority_host_counts[host] += 1
                        if is_tech_source:
                            tech_content_saved += 1
                        added += 1
                        round_added += 1
                        _emit(
                            emit,
                            "web_search",
                            "online_search_agent",
                            "网页来源已保存",
                            f"[{platform_name}] {title}",
                            query=query,
                            url=url,
                            object_key=object_key,
                            module=module,
                            provider=provider_name,
                            platform=platform_name,
                            status="done",
                        )
                    except Exception as exc:
                        db.rollback()
                        _emit(
                            emit,
                            "web_search",
                            "online_search_agent",
                            "单条网页归档失败，继续下一条",
                            str(exc),
                            query=query,
                            url=item.get("url", ""),
                            module=module,
                            status="warning",
                        )
            db.commit()
            db.expire(project, ["sources"])
            coverage = self.evaluate_source_quality(project, plan)
            if person_search:
                retrieval_audit = person_search.audit(list(project.sources or []))
                retrieval_audit.update(page_fetch_budget=person_fetch_budget, page_fetch_attempts=person_fetch_used)
                project.person_retrieval_audit = retrieval_audit
                self.save_artifact(db, project, "person_retrieval_audit", "人物逐章检索与预算记录",
                                   json.dumps(retrieval_audit, ensure_ascii=False), {"retrieval_version": retrieval_audit["version"], "intake_fingerprint": self._intake_evidence_fingerprint(intake)})
            gaps = coverage.get("information_gaps", [])
            discovery_items: list[dict[str, str]] = []
            if str(intake.get("target_type") or "").lower() == "person" and round_index < max_rounds:
                candidates = self._discover_person_affiliations(list(project.sources or []), intake)
                new_names = [
                    item["name"]
                    for item in candidates
                    if re.sub(r"\s+", "", item["name"]).lower() not in discovered_affiliations
                ]
                for name in new_names:
                    discovered_affiliations.add(re.sub(r"\s+", "", name).lower())
                if new_names:
                    confirmed_rows = intake.setdefault("confirmed_person_affiliations", [])
                    confirmed_keys = {
                        re.sub(r"\s+", "", str(row.get("name") or "")).lower()
                        for row in confirmed_rows
                        if isinstance(row, dict)
                    }
                    new_keys = {re.sub(r"\s+", "", name).lower() for name in new_names}
                    for item in candidates:
                        key = re.sub(r"\s+", "", str(item.get("name") or "")).lower()
                        if key and key in new_keys and key not in confirmed_keys:
                            confirmed_rows.append(dict(item))
                            confirmed_keys.add(key)
                    discovery_items = self._person_affiliation_discovery_queries(
                        str(intake.get("target_name") or project.target_name or "").strip(),
                        new_names,
                    )
                    _emit(
                        emit,
                        "web_search",
                        "person_affiliation_discovery_agent",
                        "发现可信关联机构，启动定向补充检索",
                        "；".join(new_names),
                        discovered_affiliations=new_names,
                        status="running",
                    )
            if str(intake.get("target_type") or "").lower() == "company" and round_index < max_rounds:
                from report_agents.company_diligence import diligence_discovery_queries
                company_discovery = diligence_discovery_queries(list(project.sources or []),
                    str(intake.get("target_name") or project.target_name or ""), discovered_company_diligence)
                from report_agents.company_risk_register import recall_discovery_queries
                company_discovery += recall_discovery_queries(list(project.sources or []),
                    str(intake.get("target_name") or project.target_name or ""), discovered_company_recalls)
                if company_discovery:
                    discovery_items.extend(company_discovery)
                    _emit(emit, "web_search", "company_diligence_discovery_agent",
                        "根据原件关系补充专项资料检索", "；".join(item["query"] for item in company_discovery), status="running")
            next_query_items = discovery_items + self._gap_queries(plan, intake, gaps)
            if round_index == 1 and pending_open_web_queries:
                next_query_items = pending_open_web_queries + next_query_items
                pending_open_web_queries = []
            if person_search and round_index < max_rounds:
                next_query_items = expanded_query_items
            if not gaps and not next_query_items:
                _emit(emit, "web_search", "coverage_agent", "来源覆盖率达标", "", status="done")
                break
            if round_index >= max_rounds or (round_added == 0 and not next_query_items):
                _emit(emit, "web_search", "coverage_agent", "来源覆盖率仍有缺口，继续后续流程", "", status="warning")
                break
            query_items = next_query_items
            _emit(
                emit,
                "web_search",
                "coverage_agent",
                "根据关联机构与证据缺口补充检索" if discovery_items else "根据缺口补充检索",
                "",
                status="running",
            )
        db.commit()
        if person_search:
            project.person_retrieval_audit = person_search.audit(list(project.sources or []))
            project.person_retrieval_audit.update(page_fetch_budget=person_fetch_budget, page_fetch_attempts=person_fetch_used)
            self.save_artifact(db, project, "person_retrieval_audit", "人物逐章检索与预算记录",
                               json.dumps(project.person_retrieval_audit, ensure_ascii=False), {"retrieval_version": project.person_retrieval_audit["version"], "intake_fingerprint": self._intake_evidence_fingerprint(intake)})
        _emit(emit, "web_search", "online_search_agent", "在线来源采集结束", "", status="done")
        return added

    def _fetch_web_url_with_timeout(self, url: str, allow_browser: bool, emit: TraceEmitter | None = None, *, document_profile: str = '') -> dict[str, Any]:
        timeout_seconds = _env_int("WEB_FETCH_TOTAL_TIMEOUT_SECONDS", 45, 5, 180)
        if document_profile == 'company':
            # Company PDFs may include hundreds of native pages plus bounded
            # OCR and its queue wait; the old 45s wrapper discarded good results.
            from company_ocr import _integer
            ocr_seconds=_integer('COMPANY_PDF_OCR_MAX_SECONDS',60,1,600)
            default=max(timeout_seconds, 60+2*ocr_seconds)
            timeout_seconds=_env_int('COMPANY_PDF_FETCH_TOTAL_TIMEOUT_SECONDS',default,30,1500)
        result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

        def worker() -> None:
            try:
                options = {'document_profile': document_profile} if document_profile else {}
                result_queue.put(("ok", web_search_provider.fetch_url(url, allow_browser=allow_browser, **options)))
            except Exception as exc:
                result_queue.put(("error", exc))

        thread = threading.Thread(target=worker, name="web-fetch-timeout-guard", daemon=True)
        thread.start()
        try:
            status, payload = result_queue.get(timeout=timeout_seconds)
        except queue.Empty:
            _emit(
                emit,
                "web_search",
                "online_search_agent",
                "网页正文抓取超时，使用搜索摘要继续",
                f"url={url}, timeout={timeout_seconds}s",
                url=url,
                timeout_seconds=timeout_seconds,
                status="warning",
            )
            return {
                "status": "fetch_timeout",
                "content": "",
                "error": f"fetch exceeded {timeout_seconds}s",
                "fetch_attempt": "workflow_timeout",
            }
        if status == "ok":
            return payload if isinstance(payload, dict) else {"status": "failed", "content": "", "error": "invalid_fetch_result"}
        return {"status": "failed", "content": "", "error": str(payload), "fetch_attempt": "workflow_error"}

    def clean_sources(
        self,
        project: ResearchProject,
        emit: TraceEmitter | None = None,
        plan: dict[str, Any] | None = None,
        quality: dict[str, Any] | None = None,
    ) -> str:
        plan = plan or {"modules": []}
        quality = quality or self.evaluate_source_quality(project, plan)
        mode = os.getenv("CLEANING_MODE", "fast").strip().lower()
        if mode in {"deep", "full"}:
            return self._deep_clean_sources(project, emit=emit, plan=plan, quality=quality)

        max_chars_per_source = _env_int("CLEANING_MAX_CHARS_PER_SOURCE", 1200, 200, 8000)
        llm_enabled = os.getenv("CLEANING_LLM_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}

        # Every usable source enters deterministic cleaning and the evidence
        # ledger.  LLM context is budgeted later by module; it must never decide
        # whether an already collected source continues to exist in the fact DB.
        selected_sources = self._select_cleaning_sources(project.sources, project=project)
        _emit(
            emit,
            "cleaning",
            "data_cleaning_agent",
            "快速清洗模式启动",
            f"source_count={len(project.sources)}, ledgered={len(selected_sources)}, llm_enabled={llm_enabled}",
            status="running",
        )

        fast = self._fast_clean_sources(selected_sources, project=project, max_chars_per_source=max_chars_per_source, emit=emit)
        person_mode = str(project.target_type or "").lower() == "person"
        rule_facts = self._extract_sentence_facts(selected_sources, project) if person_mode else []
        structured_rule_facts = self._extract_professional_structured_facts(selected_sources, project)
        # Rule-cleaned excerpts are the durable baseline, including when LLM
        # refinement is enabled.  The model may add interpretations/facts, but
        # it cannot erase deterministic or professional-platform evidence.
        if person_mode:
            try:
                from .person_company_records import company_records
            except ImportError:
                from person_company_records import company_records
            company_sources = {source.url: source for source in selected_sources
                               if (source.source_metadata or {}).get("person_affiliation")}
            fast["facts"] = [f for f in fast.get("facts", []) if f.get("source_url") not in company_sources]
            rule_facts = [f for f in rule_facts if f.get("source_url") not in company_sources]
            structured_rule_facts = [f for f in structured_rule_facts if f.get("source_url") not in company_sources]
            for source in company_sources.values():
                rule_facts.extend(company_records(source))
            record_sources = {source.url: source for source in selected_sources
                              if (source.source_metadata or {}).get("person_record_quotes")}
            fast["facts"] = [f for f in fast.get("facts", []) if f.get("source_url") not in record_sources]
            rule_facts = [f for f in rule_facts if f.get("source_url") not in record_sources]
            structured_rule_facts = [f for f in structured_rule_facts if f.get("source_url") not in record_sources]
            for url, source in record_sources.items():
                meta = source.source_metadata or {}
                for quote in meta["person_record_quotes"]:
                    if quote not in (source.content or ""):
                        continue
                    rule_facts.append({"fact": quote, "evidence_quote": quote, "claim_type": "person_platform_record", "source_url": url,
                        "source_title": source.title, "source_type": "business_database", "provider": meta.get("provider"),
                        "module": meta.get("module"), "identity_match": "confirmed", "identity_confidence": "high",
                        "eligible_for_report": True, "person_chapters": meta.get("person_chapters", []),
                        "published_at": "", "event_date": "", "retrieved_at": meta.get("retrieved_at", ""),
                        "attribution_boundary": "平台人员记录，不等于人工核验；成立日期不是任职日期，关系不证明个人承担企业责任"})
        all_facts: list[dict[str, Any]] = list(fast.get("facts", []))
        all_facts.extend(structured_rule_facts)
        if project.target_type == 'industry':
            all_facts.extend(self._extract_industry_rule_facts(selected_sources, project))
        if person_mode:
            all_facts.extend(rule_facts)
        discarded_patterns = self._normalize_cleaning_text_items(fast.get("discarded_patterns", []))
        information_gaps = self._normalize_cleaning_text_items(quality.get("information_gaps", []))
        information_gaps.extend(self._normalize_cleaning_text_items(fast.get("information_gaps", [])))

        if llm_enabled:
            llm_sources = self._select_llm_cleaning_sources(selected_sources)
            if project.target_type == 'industry':
                try:
                    from .industry_research import industry_cleaning_sources
                except ImportError:
                    from industry_research import industry_cleaning_sources
                llm_sources = industry_cleaning_sources(selected_sources, _env_int('CLEANING_LLM_SOURCES_PER_MODULE', 6, 1, 30))
            llm_batches = self._source_context_batches(
                llm_sources,
                max_chars=_env_int("CLEANING_MAX_CHARS_PER_BATCH", 8000, 1000, 30000),
                max_chars_per_source=max_chars_per_source,
                max_batches=None,
                target_type=str(project.target_type or ''),
                industry=project.target_type == 'industry',
            )
            _emit(
                emit,
                "cleaning",
                "data_cleaning_agent",
                "高价值来源进入 LLM 精洗",
                f"llm_sources={len(llm_sources)}, batches={len(llm_batches)}",
                status="running",
            )
            llm_results = self._clean_batches_with_llm(project, plan, quality, llm_batches, emit=emit)
            llm_facts = self._sanitize_structured_facts(llm_results.get("facts", []), project)
            all_facts.extend(llm_facts)
            discarded_patterns.extend(self._normalize_cleaning_text_items(llm_results.get("discarded_patterns", [])))
            information_gaps.extend(self._normalize_cleaning_text_items(llm_results.get("information_gaps", [])))
        else:
            _emit(emit, "cleaning", "data_cleaning_agent", "没有可清洗来源，跳过", "", status="skipped")

        deduped = self._annotate_evidence_facts(project, self._dedupe_facts(all_facts))
        person_rejections = []
        if person_mode:
            source_dates = {str(src.url or ""): src for src in selected_sources}
            for fact in deduped:
                src = source_dates.get(str(fact.get("source_url") or ""))
                if src is not None:
                    meta = src.source_metadata or {}
                    if meta.get("identity_confidence") in {"low", "rejected"}:
                        fact["identity_confidence"] = meta["identity_confidence"]
                        fact["eligible_for_report"] = False
                    if meta.get("person_discovery_only"):
                        fact["eligible_for_report"] = False
                    fact.setdefault("person_affiliation", meta.get("person_affiliation"))
                    fact.setdefault("person_chapters", list(meta.get("person_chapters") or []))
                    fact.setdefault("retrieved_at", str(getattr(src, "created_at", "") or "未记录"))
            deduped, person_rejections = normalize_person_facts({"facts": deduped}, str(project.target_name or ""), sources=selected_sources)
            self._validate_person_cleaned_facts(deduped)
        evidence_ledger = self._build_evidence_ledger(self._active_industry_sources(project), selected_sources, target_type=str(project.target_type or ''))
        result = {
            "facts": deduped,
            **({"person_evidence_version": PERSON_TEMPLATE_VERSION, "person_rejected_facts": person_rejections,
                "person_platform_attempts": getattr(project, "person_platform_attempts", []),
                "person_retrieval_audit": {**getattr(project, "person_retrieval_audit", {}),
                    "coverage": person_retrieval_coverage(selected_sources, getattr(project, "person_research_intake", {}) or {})}} if person_mode else {}),
            **({"industry_scope": getattr(project, "industry_scope", {})} if project.target_type == "industry" else {}),
            "identity_quarantine": [
                {
                    "target": project.target_name,
                    "source_title": source.title,
                    "source_url": source.url,
                    "source_domain": urlparse(source.url or "").netloc.lower().replace("www.", ""),
                    "identity_confidence": "low",
                    "reason": (source.source_metadata or {}).get("identity_reason", "仅命中姓名，需核验"),
                    "status": "quarantined",
                }
                for source in (project.sources or [])
                if (source.source_metadata or {}).get("identity_confidence") == "low"
            ],
            "identity_quarantine_facts": list(fast.get("identity_quarantine_facts", [])),
            "discarded_patterns": self._normalize_cleaning_text_items(discarded_patterns + ["fast cleaning enabled", "duplicate or low-evidence snippets removed"]),
            "information_gaps": self._normalize_cleaning_text_items(information_gaps),
            **({'cleaning_diagnostic': llm_results.get('cleaning_diagnostic', {})}
               if llm_enabled and project.target_type == 'industry' else {}),
            "evidence_ledger": evidence_ledger,
            "coverage_summary": {
                "source_count": quality.get("source_count", len(project.sources)),
                "ledgered_source_count": len(selected_sources),
                "deterministically_processed_source_count": len(selected_sources),
                "deterministically_cleaned_source_count": sum(1 for row in evidence_ledger if row["deterministically_cleaned"]),
                "average_source_score": quality.get("average_score", 0),
                "module_counts": quality.get("module_counts", {}),
                "fact_module_counts": dict(Counter(str(item.get("module") or "unknown") for item in deduped)),
                "ocr_items": quality.get("ocr_items", []),
                "cleaning_mode": "fast",
                "llm_enabled": llm_enabled,
            },
        }
        _emit(emit, "cleaning", "data_cleaning_agent", "快速清洗完成", "", status="done")
        return json.dumps(result, ensure_ascii=False, indent=2)

    def _extract_sentence_facts(self, sources: list[ResearchSource], project: ResearchProject) -> list[dict[str, Any]]:
        """Deterministic fallback: retain concise attributed sentences, never whole pages."""
        target = re.sub(r"\s+", "", str(project.target_name or "")).lower()
        facts: list[dict[str, Any]] = []
        noise = ("javascript", "var arg", "base64", "登录", "注册", "下载app", "网站首页", "推荐 快报", "免责声明")
        for source in sources:
            if (source.source_metadata or {}).get("identity_confidence") == "low":
                continue
            meta = source.source_metadata or {}
            text = self._clean_source_text(source.content or source.summary or "")
            candidates = re.split(r'(?<=[。！？!?；;])\s*|(?<=[.!?])(?<!\bDr\.)(?<!\bMr\.)(?<!\bMs\.)(?<!\bMrs\.)(?<!\bProf\.)(?<!\b[A-Z]\.)\s+(?=[A-Z“"\'])|[\r\n]+', text)
            kept = 0
            for sentence in candidates:
                sentence = re.sub(r"\s+", " ", sentence).strip(" -•\t")
                compact = re.sub(r"\s+", "", sentence).lower()
                if not (24 <= len(sentence) <= 420) or (target and not person_name_in_text(project.target_name, sentence)):
                    continue
                if any(marker in compact for marker in noise):
                    continue
                facts.append(
                    {
                        "fact": sentence,
                        "category": source.source_type or "unknown",
                        "claim_type": "source_statement",
                        "source_title": source.title,
                        "source_url": source.url,
                        "evidence_quote": sentence[:420],
                        "confidence": min(0.9, max(0.35, float(source.credibility_score or 50) / 100)),
                        "module": meta.get("module", ""),
                        "platform": meta.get("platform", ""),
                        "provider": meta.get("provider", ""),
                        "source_grade": self._source_grade(source, meta.get("quality") or {}),
                        "quality_score": source.credibility_score,
                        "date": "",
                    }
                )
                kept += 1
                if kept >= _env_int("PERSON_SENTENCE_FACTS_PER_SOURCE", 12, 2, 30):
                    break
        return facts

    def _extract_industry_rule_facts(self, sources, project):
        try:
            from .industry_research import extract_industry_source_facts
        except ImportError:
            from industry_research import extract_industry_source_facts
        return extract_industry_source_facts(sources, getattr(project, 'industry_scope', {}) or
                                             {'industry_name': project.target_name})

    def _extract_professional_structured_facts(
        self,
        sources: list[ResearchSource],
        project: ResearchProject,
    ) -> list[dict[str, Any]]:
        """Retain key professional-platform fields without an LLM dependency."""
        field_patterns = {
            "企业名称": r"(?:企业名称|公司名称|法定全称)\s*[|：:]\s*([^\n|；;]{2,100})",
            "统一社会信用代码": r"(?:统一社会信用代码|社会信用代码)\s*[|：:]\s*([0-9A-Z]{18})",
            "法定代表人": r"法定代表人\s*[|：:]\s*([^\n|；;]{2,50})",
            "成立时间": r"(?:成立日期|成立时间|注册日期)\s*[|：:]\s*([^\n|；;]{2,50})",
            "登记状态": r"(?:登记状态|经营状态)\s*[|：:]\s*([^\n|；;]{2,50})",
            "注册资本": r"注册资本\s*[|：:]\s*([^\n|；;]{2,80})",
            "经营范围": r"经营范围\s*[|：:]\s*([^\n|]{4,500})",
        }
        facts: list[dict[str, Any]] = []
        for source in sources:
            if not self._is_structured_professional_source(source) or not self._structured_source_is_safe(source):
                continue
            meta = source.source_metadata or {}
            affiliation = meta.get("person_affiliation") if isinstance(meta.get("person_affiliation"), dict) else {}
            subject = str(
                affiliation.get("canonical_company_name")
                or affiliation.get("affiliation_name")
                or meta.get("target")
                or source.title
                or "关联企业"
            ).strip()
            # Preserve line boundaries because many platform payloads are
            # Markdown tables or field-per-line records.
            text = html.unescape("\n".join([source.content or "", source.summary or ""]))
            text = re.sub(r"<[^>]+>", " ", text)
            if str(getattr(project, "target_type", "")) == "company" and meta.get("provider") == "qcc_risk":
                if meta.get("query_status") in {"failed", "error", "quota_exceeded", "unauthorized"}:
                    continue
                from report_agents.company_judicial import _structured
                observations = _structured(source.content or "", str(meta.get("tool") or ""),
                                           str(project.target_name or ""), {}, Counter())
                for record in observations:
                    anchor = record.get("case_number") or record.get("factor") or record.get("fields", {}).get("公告日期") or "摘要"
                    quote = record.get("evidence_quote") or next((line for line in (source.content or "").splitlines() if anchor in line), "")
                    facts.append({"fact": record["fact"], "category": "company_risk_observation",
                        "claim_type": record["kind"], "subject": project.target_name,
                        "source_title": source.title, "source_url": source.url,
                        "evidence_quote": quote, "confidence": 0.75,
                        "module": meta.get("module") or "企业司法负面核查", "provider": "qcc_risk",
                        "evidence_scope": "target_direct", "entity_validation": meta.get("entity_validation"),
                        "cleaning_method": "deterministic_structured", "source_grade": self._source_grade(source, meta.get("quality") or {})})
            for field, pattern in field_patterns.items():
                match = re.search(pattern, text, flags=re.I)
                if not match:
                    continue
                value = re.sub(r"\s+", " ", match.group(1)).strip(" |，,。；;")
                if not value or value in {"待查", "暂无", "无"}:
                    continue
                facts.append({
                    "fact": f"{subject}的{field}为{value}。",
                    "category": "person_affiliation_structured" if affiliation else "business_database_structured",
                    "claim_type": "structured_field",
                    "field": field,
                    "value": value,
                    "subject": subject,
                    "source_title": source.title,
                    "source_url": source.url,
                    "evidence_quote": match.group(0)[:500],
                    "confidence": min(0.95, max(0.5, float(source.credibility_score or 70) / 100)),
                    "module": meta.get("module") or "工商与关联企业",
                    "provider": meta.get("provider") or "",
                    "source_grade": self._source_grade(source, meta.get("quality") or {}),
                    "person_affiliation": affiliation,
                    "entity_validation": meta.get("entity_validation") or meta.get("matched_anchor") or "matched_anchor",
                    "attribution_boundary": "关联企业层面事实，不得归因为目标人物个人事实或个人风险" if affiliation else "",
                    "eligible_for_risk_scoring": False if affiliation else None,
                    "cleaning_method": "deterministic_structured",
                })
        return facts

    def _sanitize_structured_facts(self, facts: list[Any], project: ResearchProject) -> list[dict[str, Any]]:
        cleaned: list[dict[str, Any]] = []
        target_type = str(project.target_type or "").lower()
        target = re.sub(r"\s+", "", str(project.target_name or "")).lower()
        source_by_url = {
            str(source.url or ""): source
            for source in (getattr(project, "sources", []) or [])
        }
        for item in facts:
            if not isinstance(item, dict):
                continue
            text = re.sub(r"\s+", " ", str(item.get("fact") or "")).strip()
            quote = re.sub(r"\s+", " ", str(item.get("evidence_quote") or "")).strip()
            url = str(item.get("source_url") or "").strip()
            if not text or not url or len(text) > 900 or len(quote) > 700:
                continue
            blob = re.sub(r"\s+", "", f"{text} {quote}").lower()
            source = source_by_url.get(url)
            if target_type == 'company':
                from report_agents.company_evidence import source_body
                original, origin = source_body(source) if source else ('', 'discovery_summary')
                normalized_quote = re.sub(r'\s+', '', html.unescape(quote))
                normalized_original = re.sub(r'\s+', '', html.unescape(original))
                if origin == 'discovery_summary' or not normalized_quote or normalized_quote not in normalized_original:
                    continue
                claim_numbers = set(re.findall(r'\d+(?:,\d{3})*(?:\.\d+)?', text))
                quote_numbers = set(re.findall(r'\d+(?:,\d{3})*(?:\.\d+)?', quote))
                if not claim_numbers <= quote_numbers:
                    continue
            source_meta = (getattr(source, "source_metadata", {}) or {}) if source else {}
            if target_type == 'company' and source_meta.get('provider') == 'qcc_risk':
                # Provider prose may itself assert historical innocence or
                # normal operations. Only literal rule observations are admitted.
                continue
            affiliation_context = source_meta.get("person_affiliation") if isinstance(source_meta.get("person_affiliation"), dict) else {}
            affiliation_person = re.sub(r"\s+", "", str(affiliation_context.get("person_name") or "")).lower()
            affiliation_name = str(affiliation_context.get("affiliation_name") or "").strip()
            source_target = str(source_meta.get("target") or "").strip()
            is_affiliation_structured_fact = bool(
                target_type == "person"
                and source is not None
                and self._is_structured_professional_source(source)
                and target
                and affiliation_person == target
                and affiliation_name
                and source_target
                and (
                    re.sub(r"\s+", "", source_target).lower() in re.sub(r"\s+", "", affiliation_name).lower()
                    or re.sub(r"\s+", "", affiliation_name).lower() in re.sub(r"\s+", "", source_target).lower()
                )
            )
            if target and target not in blob and target_type == "person" and not is_affiliation_structured_fact:
                continue
            if any(marker in blob for marker in ("base64", "javascript", "vararg", "网站首页", "下载app")):
                continue
            normalized = dict(item)
            normalized["fact"] = text
            normalized["evidence_quote"] = quote[:700]
            normalized["claim_type"] = str(item.get("claim_type") or "fact")
            normalized["cleaning_method"] = "llm"
            # Relevance controls are deliberately type-specific.  A company is
            # not a person with a different label, and an industry source must
            # be tested against the requested research boundary instead of an
            # identity rule inherited from person due diligence.
            if target_type == "person":
                identity_match = str(item.get("identity_match") or "").lower()
                if str(source_meta.get("identity_confidence") or "") == "low" and identity_match not in {"confirmed", "probable"}:
                    continue
                normalized["identity_match"] = identity_match or (
                    "confirmed" if source_meta.get("identity_confidence") in {"high", "medium"} else "unknown"
                )
                normalized.pop("entity_match", None)
                normalized.pop("scope_match", None)
            elif target_type == "company":
                entity_match = str(item.get("entity_match") or "").lower()
                entity_validation = str(source_meta.get("entity_validation") or item.get("entity_validation") or "").lower()
                if entity_match in {"ambiguous", "mismatch", "out_of_scope"} or entity_validation == "rejected":
                    continue
                normalized["entity_match"] = entity_match or ("confirmed" if entity_validation in {"verified", "matched_anchor"} else "unknown")
                normalized.pop("identity_match", None)
                normalized.pop("scope_match", None)
            elif target_type == "industry":
                scope_match = str(item.get("scope_match") or "").lower()
                if scope_match in {"ambiguous", "uncertain", "mismatch", "out_of_scope"}:
                    continue
                # Sources that reach an industry project's cleaning stage have
                # already been retrieved for its declared boundary.  Preserve
                # that default unless the cleaner explicitly marks them out.
                normalized["scope_match"] = scope_match or "in_scope"
                body = re.sub(r'\s+', '', str(getattr(source, 'content', '') or '')).lower()
                native_quote = re.sub(r'\s+', '', quote).lower()
                normalized['evidence_quote_verified'] = bool(native_quote and native_quote in body)
                if not normalized['evidence_quote_verified']:
                    continue
                normalized['is_structured_evidence'] = normalized['claim_type'] == 'fact'
                normalized.pop("identity_match", None)
                normalized.pop("entity_match", None)
            if is_affiliation_structured_fact:
                normalized["category"] = "person_affiliation_structured"
                normalized["person_affiliation"] = affiliation_context
                normalized["due_diligence_relevance"] = "high"
                normalized["eligible_for_risk_scoring"] = False
                normalized["identity_match"] = "confirmed"
            if normalized.get("category") == "personal_background":
                normalized["due_diligence_relevance"] = str(item.get("due_diligence_relevance") or "low")
                normalized["privacy_sensitivity"] = str(item.get("privacy_sensitivity") or "medium")
                normalized["evidence_type"] = str(item.get("evidence_type") or "media_narrative")
                normalized["eligible_for_risk_scoring"] = False
            cleaned.append(normalized)
        return cleaned

    def _validate_person_cleaned_facts(self, facts: list[dict[str, Any]]) -> dict[str, Any]:
        # Sparse public profiles are legitimate research outcomes. Preserve a
        # useful, explicitly incomplete draft rather than demand 24 facts.
        return {"fact_count": len(facts),
                "source_count": len({f.get("source_url") for f in facts if f.get("source_url")}),
                "status": "source_bound_draft" if facts else "insufficient_evidence",
                "requires_human_review": True}

    def _deep_clean_sources(
        self,
        project: ResearchProject,
        emit: TraceEmitter | None = None,
        plan: dict[str, Any] | None = None,
        quality: dict[str, Any] | None = None,
    ) -> str:
        plan = plan or {"modules": []}
        quality = quality or self.evaluate_source_quality(project, plan)
        safe_sources = self._select_cleaning_sources(project.sources, project=project)
        model_sources = self._select_llm_cleaning_sources(safe_sources)
        if project.target_type == 'industry':
            try:
                from .industry_research import industry_cleaning_sources
            except ImportError:
                from industry_research import industry_cleaning_sources
            model_sources = industry_cleaning_sources(safe_sources, _env_int('CLEANING_LLM_SOURCES_PER_MODULE', 6, 1, 30))
        batches = self._source_context_batches(model_sources, industry=project.target_type == 'industry', target_type=str(project.target_type or ''))
        _emit(emit, "cleaning", "data_cleaning_agent", "开始深度清洗", "", status="running")
        llm_results = self._clean_batches_with_llm(project, plan, quality, batches, emit=emit)
        deterministic = self._fast_clean_sources(safe_sources, project=project, emit=emit)
        all_facts = list(deterministic.get("facts", []))
        all_facts.extend(self._extract_professional_structured_facts(safe_sources, project))
        if project.target_type == 'industry':
            all_facts.extend(self._extract_industry_rule_facts(safe_sources, project))
        if str(project.target_type or "").lower() == "person":
            all_facts.extend(self._extract_sentence_facts(safe_sources, project))
        all_facts.extend(self._sanitize_structured_facts(llm_results.get("facts", []), project))
        deduped = self._annotate_evidence_facts(project, self._dedupe_facts(all_facts))
        evidence_ledger = self._build_evidence_ledger(project.sources, safe_sources, target_type=str(project.target_type or ''))
        result = {
            "facts": deduped,
            **({"industry_scope": getattr(project, "industry_scope", {})} if project.target_type == "industry" else {}),
            "identity_quarantine": [
                {
                    "target": project.target_name,
                    "source_title": source.title,
                    "source_url": source.url,
                    "source_domain": urlparse(source.url or "").netloc.lower().replace("www.", ""),
                    "identity_confidence": "low",
                    "reason": (source.source_metadata or {}).get("identity_reason", "仅命中姓名，需核验"),
                    "status": "quarantined",
                }
                for source in (project.sources or [])
                if (source.source_metadata or {}).get("identity_confidence") == "low"
            ],
            "discarded_patterns": self._normalize_cleaning_text_items([llm_results.get("discarded_patterns", []), "duplicate or low-evidence snippets removed"]),
            "information_gaps": self._normalize_cleaning_text_items([quality.get("information_gaps", []), llm_results.get("information_gaps", [])]),
            **({'cleaning_diagnostic': llm_results.get('cleaning_diagnostic', {})} if project.target_type == 'industry' else {}),
            "evidence_ledger": evidence_ledger,
            "coverage_summary": {
                "source_count": quality.get("source_count", 0),
                "ledgered_source_count": len(safe_sources),
                "deterministically_processed_source_count": len(safe_sources),
                "deterministically_cleaned_source_count": sum(1 for row in evidence_ledger if row["deterministically_cleaned"]),
                "average_source_score": quality.get("average_score", 0),
                "module_counts": quality.get("module_counts", {}),
                "fact_module_counts": dict(Counter(str(item.get("module") or "unknown") for item in deduped)),
                "ocr_items": quality.get("ocr_items", []),
                "cleaning_mode": "deep",
            },
        }
        _emit(emit, "cleaning", "data_cleaning_agent", "深度清洗完成", f"facts={len(deduped)}, gaps={len(result['information_gaps'])}", facts=len(deduped), status="done")
        return json.dumps(result, ensure_ascii=False, indent=2)

    def _clean_batches_with_llm(
        self,
        project: ResearchProject,
        plan: dict[str, Any],
        quality: dict[str, Any],
        batches: list[str],
        emit: TraceEmitter | None = None,
    ) -> dict[str, list[Any]]:
        all_facts: list[dict[str, Any]] = []
        discarded_patterns: list[str] = []
        information_gaps: list[str] = []
        if not batches:
            return {"facts": all_facts, "discarded_patterns": discarded_patterns, "information_gaps": information_gaps}

        brief = self._cleaning_brief(project, plan, quality)
        target_type = str(project.target_type or "").lower()
        match_rules = {
            "person": (
                "人物项目必须仅依据本条材料中的机构、职务、履历等信号判断身份；不得仅凭常识认定同一人。\n"
                "identity_match=ambiguous/mismatch 时 extract_fact=false，不提取为正式事实。",
                '"identity_match": "confirmed|probable|ambiguous|mismatch",',
            ),
            "company": (
                "公司项目必须核对材料中的公司全称、统一代码、注册地或已验证主体锚点；不得把同名公司、品牌关联公司或子公司默认视为目标主体。\n"
                "entity_match=ambiguous/mismatch/out_of_scope 时 extract_fact=false，不提取为正式事实。",
                '"entity_match": "confirmed|probable|ambiguous|mismatch|out_of_scope",',
            ),
            "industry": (
                "行业项目必须核对事实是否符合已声明的行业/子赛道、地域、统计期和研究边界；不得把边界外行业数据混入结论。\n"
                "scope_match=ambiguous/uncertain/out_of_scope 时 extract_fact=false，不提取为正式事实。",
                '"scope_match": "in_scope|ambiguous|uncertain|out_of_scope",',
            ),
        }
        match_instruction, match_field = match_rules.get(target_type, ("", ""))
        workers = _env_int("CLEANING_MAX_WORKERS", 3, 1, 8)
        industry_mode = target_type == 'industry'
        batch_states = {}
        health = {'failures': 0, 'circuit_open': False}
        health_lock = threading.Lock()

        def invoke_cleaning(batch_index: int, source_blocks: str, depth: int = 0) -> list[dict[str, Any]]:
            if industry_mode:
                state = batch_states[batch_index]
                with health_lock:
                    if health['circuit_open']:
                        state['circuit_skipped'] = True
                        return []
                remaining = state['deadline'] - time.monotonic()
                if remaining < 1 or state['calls'] >= _env_int('INDUSTRY_CLEANING_MAX_CALLS_PER_BATCH', 3, 1, 5):
                    state['budget_exhausted'] = True
                    _emit(emit, 'cleaning', 'data_cleaning_agent', '行业清洗批次预算已用尽，保留规则事实',
                          f'batch={batch_index}, calls={state["calls"]}', batch=batch_index, status='fallback')
                    return []
            prompt = f"""
你是合规尽调资料的信息抽取 Agent。只客观提取材料中明确出现、可复核、可引用的信息；不得判罪、认定违法或补充材料中没有的事实。
{brief}

资料批次 {batch_index}/{len(batches)}：
{_clip(source_blocks, _env_int("CLEANING_MAX_CHARS_PER_BATCH", 8000, 1000, 30000))}

要求：
1. 每条事实必须保留 source_title、source_url、evidence_quote。
2. 区分客观事实、来源评价和待核验事项。
3. {match_instruction}
5. 婚姻、家庭、外貌、恋爱经历等材料可以保留为 personal_background，但必须 eligible_for_risk_scoring=false。
6. 若资料明确包含“人物关联企业上下文”，可提取其中企业的工商、股权、高管、风险等结构化事实，即使事实文本未重复人物姓名；此类事实的 category 必须为 person_affiliation_structured，且只能表述为“该关联企业信息”，不得写成目标人物个人事实或个人信用结论。
7. 只输出 JSON，不输出解释。
格式：{{
  "facts": [
    {{
      "fact": "...",
      "category": "profile|industry|legal|finance|reputation|relationship|operation|market|unknown",
      "claim_type": "fact|judgment|unknown",
      "source_title": "...",
      "source_url": "...",
      "evidence_quote": "...",
      "confidence": 0.0,
      "module": "...",
      "evidence_scope": "industry_level|segment_level|representative_company|capital_market|target_company|unknown",
      "industry_name": "...",
      "segment_name": "...",
      "company_role": "benchmark|target|unknown",
      "date": "",
      "numeric_context": {{"metric": "指标名称", "value": null, "unit": "", "geography": "", "period": "", "definition": "统计口径", "is_forecast": false}},
      {match_field}
      "matched_anchors": ["..."],
      "conflicting_signals": ["..."],
      "extract_fact": true,
      "due_diligence_relevance": "high|medium|low",
      "privacy_sensitivity": "low|medium|high",
      "evidence_type": "primary_record|media_report|media_narrative|other",
      "eligible_for_risk_scoring": true
    }}
  ],
  "discarded_patterns": ["..."],
  "information_gaps": ["..."]
}}
"""
            if industry_mode:
                # Industry extraction needs no person identity/privacy/company schema.
                prompt = f'''只抽取本批原文明示的最多3条行业事实，优先数值口径和商业模式。
{brief}
原文批次 {batch_index}/{len(batches)}：
{_clip(source_blocks, _env_int("CLEANING_MAX_CHARS_PER_BATCH", 8000, 1000, 30000))}
逐条保留原始source_url、source_title、module、evidence_scope，evidence_quote必须是连续原文，最长180字。
fact最长120字，不新增原文没有的数值或口径。企业个案保持representative_company；不适用的材料跳过。
只输出闭合JSON：{{"facts":[{{"fact":"...","claim_type":"fact","source_url":"...","source_title":"...","module":"...","evidence_scope":"industry_level|segment_level|representative_company|capital_market","scope_match":"in_scope","evidence_quote":"..."}}]}}
含数值时增加numeric_context：metric、value、unit、geography、period、definition、is_forecast；原文未明确的字段留空。无适用事实返回facts=[]。
'''
                remaining = state['deadline'] - time.monotonic()
                if remaining < 1:
                    state['budget_exhausted'] = True
                    return []
                state['calls'] += 1
                answer = self._invoke_industry_cleaning(f'行业清洗 Agent - 批次{batch_index}', prompt, emit=emit,
                    timeout_seconds=min(remaining, _env_int('INDUSTRY_CLEANING_TIMEOUT_SECONDS', 60, 10, 120)))
            else:
                answer = self._invoke("数据清洗 Agent", prompt, emit=emit)
            parsed = _plain_json(answer, allow_preface=not industry_mode)
            if isinstance(parsed, dict):
                if industry_mode:
                    with health_lock:
                        if parsed.get('facts'):
                            health['failures'] = 0
                return [parsed]
            if industry_mode:
                with health_lock:
                    health['failures'] += 1
                    if health['failures'] >= _env_int('INDUSTRY_CLEANING_FAILURE_LIMIT', 6, 2, 30) and not health['circuit_open']:
                        health['circuit_open'] = True
                        _emit(emit, 'cleaning', 'data_cleaning_agent', '行业精洗连续失败，停止追加模型请求',
                              f'failures={health["failures"]}; 原文规则事实保留', status='fallback')
            max_depth = (_env_int('INDUSTRY_CLEANING_SPLIT_MAX_DEPTH', 1, 0, 2) if industry_mode
                         else _env_int("CLEANING_INSPECTION_SPLIT_MAX_DEPTH", 2, 0, 5))
            parts = [part.strip() for part in source_blocks.split("\n\n---\n\n") if part.strip()]
            if depth >= max_depth or len(parts) <= 1:
                if industry_mode:
                    state['failed_parts'] += 1
                    return []
                fallback_answer = self._invoke_cleaning_fallback_model(prompt, emit=emit)
                fallback_parsed = _plain_json(fallback_answer)
                if isinstance(fallback_parsed, dict):
                    fallback_parsed["cleaning_model_route"] = "fallback_model"
                    return [fallback_parsed]
                return []
            midpoint = max(1, len(parts) // 2)
            _emit(emit, "cleaning", "data_cleaning_agent", "批次清洗被拒绝或无有效输出，自动二分重试", f"batch={batch_index}, depth={depth + 1}", status="warning")
            return invoke_cleaning(batch_index, "\n\n---\n\n".join(parts[:midpoint]), depth + 1) + invoke_cleaning(batch_index, "\n\n---\n\n".join(parts[midpoint:]), depth + 1)

        def clean_one(batch_index: int, source_blocks: str) -> tuple[int, list[dict[str, Any]]]:
            if industry_mode:
                batch_states[batch_index] = {'deadline': time.monotonic() +
                    _env_int('INDUSTRY_CLEANING_BATCH_BUDGET_SECONDS', 150, 20, 300), 'calls': 0,
                    'budget_exhausted': False, 'started': time.monotonic()}
                batch_states[batch_index]['failed_parts'] = 0
                batch_states[batch_index]['circuit_skipped'] = False
            try:
                return batch_index, invoke_cleaning(batch_index, source_blocks)
            finally:
                if industry_mode:
                    batch_states[batch_index]['finished'] = time.monotonic()

        with ThreadPoolExecutor(max_workers=min(workers, len(batches))) as executor:
            futures = {
                executor.submit(clean_one, idx, block): idx
                for idx, block in enumerate(batches, 1)
            }
            for future in as_completed(futures):
                batch_index = futures[future]
                try:
                    _returned_index, parsed_rows = future.result()
                except Exception as exc:
                    information_gaps.append(f"清洗批次 {batch_index} 失败：{type(exc).__name__}；已保留规则清洗事实，待人工复核。")
                    _emit(
                        emit,
                        "cleaning",
                        "data_cleaning_agent",
                        "单个清洗批次异常，保留其他批次与规则事实",
                        f"batch={batch_index}, error={exc}",
                        batch=batch_index,
                        status="fallback",
                    )
                    continue
                if parsed_rows:
                    for parsed in parsed_rows:
                        payload = self._normalize_cleaning_payload(parsed)
                        all_facts.extend(
                            fact for fact in payload["facts"]
                            if isinstance(fact, dict) and fact.get("extract_fact", True)
                        )
                        discarded_patterns.extend(payload["discarded_patterns"])
                        information_gaps.extend(payload["information_gaps"])
                    _emit(emit, "cleaning", "data_cleaning_agent", "批次清洗完成", f'batch={batch_index}', batch=batch_index, status="done")
                else:
                    fallback = self._fallback_clean_batch([], batch_index)
                    information_gaps.extend(fallback.get("information_gaps", []))
                    _emit(emit, "cleaning", "data_cleaning_agent", "批次清洗失败，使用规则降级", f'batch={batch_index}', batch=batch_index, status="fallback")

        result = {"facts": all_facts, "discarded_patterns": discarded_patterns, "information_gaps": information_gaps}
        if industry_mode:
            for idx, state in sorted(batch_states.items()):
                state['budget_exhausted'] = state['budget_exhausted'] or bool(state['failed_parts'] and
                    (state['finished'] >= state['deadline'] or state['calls'] >= _env_int('INDUSTRY_CLEANING_MAX_CALLS_PER_BATCH', 3, 1, 5)))
                if state['failed_parts'] or state['budget_exhausted'] or state['circuit_skipped']:
                    information_gaps.append(f'行业清洗批次{idx}有子片段未完成结构化提取；规则来源保留，需复核。')
            result['cleaning_diagnostic'] = {'batches': [{'batch': idx, 'model_calls': state['calls'],
                'failed_parts': state['failed_parts'], 'budget_exhausted': state['budget_exhausted'],
                'circuit_skipped': state['circuit_skipped']}
                for idx, state in sorted(batch_states.items())], 'circuit_open': health['circuit_open']}
        return result

    def assess_risk(self, project: ResearchProject, cleaned_json: str, emit: TraceEmitter | None = None) -> str:
        target_type = str(project.target_type or "").lower()
        if target_type == "person":
            payload = _plain_json(cleaned_json) or {}
            result = normalize_person_risk(payload)
            _emit(emit, "risk", "risk_assessment_agent", "人物风险按证据登记，未知项不评分", "", status="done")
            return json.dumps(result, ensure_ascii=False, indent=2)
        if target_type == "company":
            from report_agents.company_risk_register import build_risk_register
            cleaned = _plain_json(cleaned_json)
            package = build_risk_register(
                cleaned if isinstance(cleaned, dict) else {}, str(project.target_name or ""),
                list(project.sources or []), industry=str(project.industry or ""),
                intake=getattr(project, "company_research_intake", {}),
                query_attempts=getattr(project, "company_judicial_query_attempts", []),
            )
            project.company_risk_register_package = package
            _emit(emit, "risk", "risk_assessment_agent", "公司风险原件登记完成",
                  json.dumps(package["diagnostic"], ensure_ascii=False),
                  risk_level=package["risk_level"], status="done")
            return json.dumps(package, ensure_ascii=False, indent=2)
        risk_evidence = self._risk_evidence_payload(cleaned_json, target_type=target_type)
        company_evidence_rule = ""
        evidence_id_field = ""
        if target_type == "company":
            company_evidence_rule = """
公司报告附加规则：每个非 unknown 风险维度必须返回 `evidence_ids`，且只能填写清洗事实中已提供的 E-证据编号。`evidence_sources` 可作为可读说明保留，但不能替代 `evidence_ids`。没有有效 E-ID 的维度必须返回 score=null、level=unknown；不得把信息缺口计为低风险。
"""
            evidence_id_field = ', "evidence_ids": ["E-..."]'
        if target_type == "industry":
            try:
                from .industry_research import active_risk_dimensions
                from .industry_risk import scoring_rubric
            except ImportError:
                from industry_research import active_risk_dimensions
                from industry_risk import scoring_rubric
            applicable = active_risk_dimensions(getattr(project, "industry_scope", {}))
            dimension_schema = json.dumps([{'name': name, 'evidence_ids': [], 'score': None,
                'level': 'unknown|low|medium|high|critical', 'reason': '...', 'evidence_sources': []}
                for name in applicable], ensure_ascii=False)
            prompt = f"""
研究边界：{json.dumps(getattr(project, "industry_scope", {}), ensure_ascii=False)}
仅评估以下启用维度：{json.dumps(applicable, ensure_ascii=False)}。忽略下方结构示例中未启用的维度，不列为 unknown，不提出其补采建议。
请扮演行业风险研判 Agent。基于清洗事实，对目标行业进行行业维度风险评分，不得套用目标公司/标的主体尽调维度。每个维度必须输出 evidence_ids，且仅能引用输入事实的 E-ID。无有效且适用的行业证据时 score=null、level=unknown；不得用代表企业个案直接证明行业整体风险。
项目：{project.title}
研究对象：{project.target_name}
行业：{project.industry}

清洗事实：
{_clip(risk_evidence, 30000)}

评分口径必须统一：overall_score 和各维度 score 均为“风险分”，0 表示风险最低，100 表示风险最高。信息缺失必须列为 unknown/待核验，不能仅因“未搜索到、未提供、无法排除”就判为高风险。代表企业材料只能作为行业样本或竞争格局信号，不能写成目标公司经营风险。
评分参考：{json.dumps(scoring_rubric(getattr(project, 'industry_scope', {})), ensure_ascii=False)}
各维度只能使用 dimension_evidence_ids 中列出的编号；reason 中的编号必须同时列入 evidence_ids。理由每维120字以内，只写支撑该评分的判断，数值只可使用对应事实allowed_numbers中的值；禁止使用来源标题、URL或统计定义中的其他数字补结论。完整原文保留在事实库供审计，评分输入只授权fact中的单个指标。预测值须在同一分句明确预计/预测，不同事实编号不等于独立来源；同一发布方的卡片不能声称多源一致。政策目标不能写成已经实现的市场集中度。没有已核验数值时可以用适用定性证据作克制判断，禁止新增定量结论；证据不足仍返回unknown。

请只输出 JSON，结构为：
{{
  "overall_score": 0,
  "risk_level": "unknown|low|medium|high|critical",
  "dimensions": {dimension_schema},
  "key_risks": ["..."],
  "unknowns": ["..."],
  "recommended_followups": ["..."]
}}
"""
            answer = self._invoke_industry_risk("行业风险研判 Agent", prompt, emit=emit)
            parsed = _plain_json(answer, allow_preface=False)
            # Support counts describe the exact bounded input even when the model abstains or returns invalid JSON.
            retained_ids = {f.get('evidence_id') for f in json.loads(risk_evidence).get('facts', [])}
            cleaned_payload = _plain_json(cleaned_json)
            retained = [f for f in cleaned_payload.get('facts', []) if f.get('evidence_id') in retained_ids] if isinstance(cleaned_payload, dict) else []
            if isinstance(parsed, dict):
                # Only facts actually sent within the model's budget can authorize scores.
                parsed = normalize_industry_risk(parsed, retained, getattr(project, "industry_scope", {}))
                parsed = self._repair_industry_risk(parsed, json.loads(risk_evidence), retained,
                                                    getattr(project, 'industry_scope', {}), emit=emit)
                _emit(emit, "risk", "risk_assessment_agent", "模型行业风险评分完成", f"risk_level={parsed.get('risk_level')}", risk_level=parsed.get("risk_level"), status="done")
                return json.dumps(parsed, ensure_ascii=False, indent=2)
            fallback = unknown_industry_risk(scope=getattr(project, "industry_scope", {}))
            try:
                from .industry_risk import attach_risk_support
            except ImportError:
                from industry_risk import attach_risk_support
            fallback = attach_risk_support(fallback, retained, getattr(project, 'industry_scope', {}))
            fallback['validation_diagnostics'] = {'primary_status': 'empty_or_invalid_json',
                'model_response_excerpt': answer[:3000], 'repair': {'attempted': False, 'attempts': 0}}
            _emit(emit, "risk", "risk_assessment_agent", "使用规则降级行业评分", f"risk_level={fallback.get('risk_level')}", risk_level=fallback.get("risk_level"), status="fallback")
            return json.dumps(fallback, ensure_ascii=False, indent=2)
        prompt = f"""
请扮演风险研判 Agent。基于清洗事实，对目标进行多维度标准化打分。
项目：{project.title}
研究对象：{project.target_name}
行业：{project.industry}

清洗事实：
{_clip(risk_evidence, 30000)}

评分口径必须统一：overall_score 和各维度 score 均为“风险分”，0 表示风险最低，100 表示风险最高，绝不能解释为企业质量分或推荐分。信息缺失必须列为 unknown/待核验，不能仅因“未搜索到、未提供、无法排除”就判为高风险。只有人物身份存在相互冲突的证据、明显同名混入或关键履历被可靠来源否定时，才能把身份问题计入高风险；单纯公开资料不足不得虚增风险分。
{company_evidence_rule}

请只输出 JSON，结构为：
{{
  "overall_score": 0,
  "risk_level": "unknown|low|medium|high|critical",
  "dimensions": [
    {{"name": "法律合规风险", "score": null, "level": "unknown|low|medium|high|critical", "reason": "...", "evidence_sources": ["..."]{evidence_id_field}}},
    {{"name": "财务稳定性风险", "score": 0, "level": "...", "reason": "...", "evidence_sources": ["..."]{evidence_id_field}}},
    {{"name": "舆情声誉风险", "score": 0, "level": "...", "reason": "...", "evidence_sources": ["..."]{evidence_id_field}}},
    {{"name": "商业信用风险", "score": 0, "level": "...", "reason": "...", "evidence_sources": ["..."]{evidence_id_field}}},
    {{"name": "关联关系风险", "score": 0, "level": "...", "reason": "...", "evidence_sources": ["..."]{evidence_id_field}}},
    {{"name": "行业周期风险", "score": 0, "level": "...", "reason": "...", "evidence_sources": ["..."]{evidence_id_field}}}
  ],
  "key_risks": ["..."],
  "unknowns": ["..."],
  "recommended_followups": ["..."]
}}
"""
        answer = self._invoke("风险研判 Agent", prompt, emit=emit)
        parsed = _plain_json(answer)
        if parsed:
            if target_type == "company":
                parsed = self._normalize_company_risk_evidence(parsed, cleaned_json)
            parsed = self._normalize_risk_unknowns(parsed)
            _emit(emit, "risk", "risk_assessment_agent", "模型风险评分完成", f"risk_level={parsed.get('risk_level')}", risk_level=parsed.get("risk_level"), status="done")
            return json.dumps(parsed, ensure_ascii=False, indent=2)
        fallback = self._fallback_risk(cleaned_json)
        _emit(emit, "risk", "risk_assessment_agent", "使用规则降级评分", f"risk_level={fallback.get('risk_level')}", risk_level=fallback.get("risk_level"), status="fallback")
        return json.dumps(fallback, ensure_ascii=False, indent=2)

    def _repair_industry_risk(self, normalized: dict, evidence: dict, retained: list[dict], scope: dict,
                              emit: TraceEmitter | None = None) -> dict:
        try:
            from .industry_research import risk_repair_package, risk_level
        except ImportError:
            from industry_research import risk_repair_package, risk_level
        initial_diagnostics = [{'name': row['name'], 'cause': row.get('unknown_cause'),
                                **row['validation_diagnostic']} for row in normalized['dimensions'] if row.get('validation_diagnostic')]
        diagnostic = {'primary_status': 'validated', 'initial_rejections': initial_diagnostics,
                      'repair': {'attempted': False, 'attempts': 0}}
        result = {**normalized, 'validation_diagnostics': diagnostic}
        package = risk_repair_package(evidence, normalized)
        requested = {row['name'] for row in package['dimensions_to_repair']}
        if not requested:
            return result
        prompt = ('仅修复下列失败风险维度，返回完整JSON {"dimensions":[{"name":"...","score":null,'
                  '"level":"unknown|low|medium|high|critical","reason":"...","evidence_ids":[]}]}。'
                  '每维理由120字以内，只用该维dimension_evidence_ids中的编号；理由引用必须同时列入evidence_ids。'
                  '数字只可用对应证据allowed_numbers，禁止从先前失败理由补数据；没有定量证据可作有依据的定性判断。'
                  '预测数字必须在同一分句明确预计/预测；同一发布方的多张卡片不能写成多源印证。'
                  '保留政策目标、预测与实际统计的区别，企业样本不能评分行业整体。证据不足返回score=null、level=unknown，'
                  '不能为了修复凑分。无需返回其他维度、总分或额外章节。\n'
                  + json.dumps(normalized.get('scoring_methodology') or {}, ensure_ascii=False)
                  + '\n' + json.dumps(package, ensure_ascii=False))
        repair_diagnostic = {'attempted': True, 'attempts': 1, 'requested_dimensions': sorted(requested),
                             'input_chars': len(prompt), 'repaired_dimensions': [], 'remaining_dimensions': sorted(requested)}
        diagnostic['repair'] = repair_diagnostic
        _emit(emit, 'risk', 'risk_assessment_agent', '部分行业评分未通过校验，尝试一次局部修复',
              '、'.join(sorted(requested)), status='warning')
        try:
            answer = self._invoke_industry_risk('行业风险修复 Agent', prompt, emit=emit, repair=True)
            parsed = _plain_json(answer)
        except Exception as exc:
            parsed = None
            repair_diagnostic['exception_type'] = type(exc).__name__
        if not isinstance(parsed, dict):
            repair_diagnostic['status'] = 'empty_or_invalid_json'
            return result
        repair_ids = {f['evidence_id'] for f in package['facts']}
        repair_retained = [f for f in retained if f.get('evidence_id') in repair_ids]
        checked = normalize_industry_risk(parsed, repair_retained, scope)
        accepted = {row['name']: row for row in checked['dimensions'] if row['name'] in requested and row.get('score') is not None}
        result['dimensions'] = [accepted.get(row['name'], row) for row in normalized['dimensions']]
        scores = [row['score'] for row in result['dimensions'] if row.get('score') is not None]
        result['assessed_dimension_count'] = len(scores)
        result['overall_score'] = round(sum(scores)/len(scores), 1) if len(scores) == len(result['dimensions']) else None
        result['risk_level'] = risk_level(result['overall_score']) if result['overall_score'] is not None else 'unknown'
        result['unknowns'] = [note for note in normalized.get('unknowns', [])
                              if not any(str(note).startswith(name+'：') for name in accepted)]
        repair_diagnostic.update(status='complete' if len(accepted)==len(requested) else 'partial' if accepted else 'rejected',
            repaired_dimensions=sorted(accepted), remaining_dimensions=sorted(requested-set(accepted)),
            rejected_diagnostics=[{'name':row['name'], 'cause':row.get('unknown_cause'), **(row.get('validation_diagnostic') or {})}
                for row in checked['dimensions'] if row['name'] in requested and row.get('score') is None])
        _emit(emit, 'risk', 'risk_assessment_agent', '行业评分局部修复校验完成',
              f'repaired={len(accepted)}, remaining={len(requested)-len(accepted)}', status='done' if accepted else 'fallback')
        try:
            from .industry_risk import attach_risk_support
        except ImportError:
            from industry_risk import attach_risk_support
        return attach_risk_support(result, retained, scope)

    def _risk_evidence_payload(self, cleaned_json: str, target_type: str = "") -> str:
        parsed = _plain_json(cleaned_json)
        if not isinstance(parsed, dict):
            return _clip(cleaned_json, 30000)
        rows = []
        facts = parsed.get("facts") or []
        if target_type == "industry":
            try:
                from .industry_research import balanced_risk_facts, risk_fact_text, risk_fact_applicable, active_risk_dimensions, source_document_key
            except ImportError:
                from industry_research import balanced_risk_facts, risk_fact_text, risk_fact_applicable, active_risk_dimensions, source_document_key
            facts = balanced_risk_facts(facts)
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            if fact.get("eligible_for_risk_scoring") is False or fact.get("category") == "personal_background":
                continue
            row = {
                    "fact": _clip(str(fact.get("fact") or ""), 700),
                    "claim_type": fact.get("claim_type"),
                    "category": fact.get("category"),
                    "module": fact.get("module"),
                    "source_title": fact.get("source_title"),
                    "source_url": fact.get("source_url"),
                    "confidence": fact.get("confidence"),
                }
            if target_type == "company":
                row["evidence_id"] = fact.get("evidence_id")
                row["evidence_scope"] = fact.get("evidence_scope")
            if target_type == "industry":
                row['fact'] = risk_fact_text(fact)[:700]
                row['source_document_key'] = source_document_key(fact.get('source_url', ''))
                row["evidence_id"] = fact.get("evidence_id")
                row["evidence_scope"] = fact.get("evidence_scope")
                row["industry_name"] = fact.get("industry_name")
                row["segment_name"] = fact.get("segment_name")
                row["company_role"] = fact.get("company_role")
                row["attribution_boundary"] = fact.get("attribution_boundary")
                row["numeric_context"] = fact.get("numeric_context")
                row["numeric_validation"] = fact.get("numeric_validation")
                context = fact.get('numeric_context') or {}
                row['allowed_numbers'] = ([str(context.get('value')) + str(context.get('unit'))]
                    if (fact.get('numeric_validation') or {}).get('passed') is True else [])
            rows.append(row)
            if len(rows) >= 60:
                break
        if target_type == 'industry':
            try:
                from .industry_research import bounded_package
            except ImportError:
                from industry_research import bounded_package
            # The full payload used to reach ~79k chars and get sliced mid-JSON.
            # Cap complete cards before composing the risk prompt.
            for row in rows:
                row['source_title'] = str(row.get('source_title') or '')[:160]
                row['attribution_boundary'] = str(row.get('attribution_boundary') or '')[:250]
            payload = json.loads(bounded_package({'facts': rows,
                'information_gaps': [str(x)[:200] for x in (parsed.get('information_gaps') or [])[:12]],
                'gap_interpretation': '缺口是单批抽取线索，需结合全库事实核对；不能据此断言全行业无数据。'}, 25000))
            original_by_id = {f.get('evidence_id'): f for f in facts}
            while True:
                payload['dimension_evidence_ids'] = {name: [r['evidence_id'] for r in payload['facts']
                    if risk_fact_applicable(original_by_id[r['evidence_id']], name)]
                    for name in active_risk_dimensions(parsed.get('industry_scope') or {})}
                encoded = json.dumps(payload, ensure_ascii=False)
                if len(encoded) <= 28000 or not payload['facts']:
                    return encoded
                payload['facts'].pop()
        return json.dumps(
            {"facts": rows, "information_gaps": (parsed.get("information_gaps") or [])[:15]},
            ensure_ascii=False,
            indent=2,
        )

    def _normalize_company_risk_evidence(self, parsed: dict[str, Any], cleaned_json: str) -> dict[str, Any]:
        """Bind company risk results to admissible fact-card IDs only."""
        cleaned = _plain_json(cleaned_json)
        facts = cleaned.get("facts") if isinstance(cleaned, dict) else []
        by_id: dict[str, dict[str, Any]] = {}
        aliases: dict[str, set[str]] = {}
        for fact in facts or []:
            if not isinstance(fact, dict):
                continue
            if fact.get("eligible_for_risk_scoring") is False:
                continue
            if str(fact.get("evidence_scope") or "") not in {"", "target_direct"}:
                continue
            evidence_id = str(fact.get("evidence_id") or "").strip()
            if not evidence_id:
                continue
            by_id[evidence_id] = fact
            for value in (fact.get("source_url"), fact.get("source_title")):
                key = re.sub(r"\s+", "", str(value or "")).lower().rstrip("/")
                if key:
                    aliases.setdefault(key, set()).add(evidence_id)

        for dimension in parsed.get("dimensions") or []:
            if not isinstance(dimension, dict):
                continue
            resolved: list[str] = []
            for value in dimension.get("evidence_ids") or []:
                evidence_id = str(value or "").strip()
                if evidence_id in by_id and evidence_id not in resolved:
                    resolved.append(evidence_id)
            for value in dimension.get("evidence_sources") or []:
                key = re.sub(r"\s+", "", str(value or "")).lower().rstrip("/")
                matches = set(aliases.get(key, set()))
                if not matches and key:
                    matches = {
                        evidence_id
                        for alias, evidence_ids in aliases.items()
                        if key in alias or alias in key
                        for evidence_id in evidence_ids
                    }
                for evidence_id in sorted(matches):
                    if evidence_id not in resolved:
                        resolved.append(evidence_id)
            dimension["evidence_ids"] = resolved
            if not resolved:
                dimension["score"] = None
                dimension["level"] = "unknown"
                reason = str(dimension.get("reason") or "").rstrip("。")
                boundary = "缺少可绑定的主体直接证据编号，该项不参与评分，待核验。"
                dimension["reason"] = f"{reason}；{boundary}" if reason else boundary
        return parsed

    def _normalize_risk_unknowns(self, parsed: dict[str, Any]) -> dict[str, Any]:
        """Missing evidence is an unknown, never affirmative proof of low risk."""
        missing_markers = ["无证据", "未提供", "未包含", "未检索到", "未发现", "信息缺失", "空结果", "无法评估", "无法确认"]
        positive_clearance = ["经核验", "权威来源确认", "官方查询显示", "多源交叉验证"]
        known_scores: list[float] = []
        for dimension in parsed.get("dimensions") or []:
            if not isinstance(dimension, dict):
                continue
            reason = str(dimension.get("reason") or "")
            if any(marker in reason for marker in missing_markers) and not any(marker in reason for marker in positive_clearance):
                dimension["score"] = None
                dimension["level"] = "unknown"
                if "待核验" not in reason:
                    dimension["reason"] = reason.rstrip("。") + "；该项属于证据缺口，不构成低风险或高风险结论，待核验。"
                continue
            try:
                known_scores.append(float(dimension.get("score")))
            except (TypeError, ValueError):
                pass
        if not known_scores:
            parsed["overall_score"] = None
            parsed["risk_level"] = "unknown"
        else:
            parsed["overall_score"] = round(sum(known_scores) / len(known_scores), 1)
            score = parsed["overall_score"]
            parsed["risk_level"] = "critical" if score >= 85 else "high" if score >= 70 else "medium" if score >= 40 else "low"
        return parsed
    def generate_report(
        self,
        project: ResearchProject,
        cleaned_json: str,
        risk_json: str,
        emit: TraceEmitter | None = None,
        intake: dict[str, Any] | None = None,
    ) -> str:
        target_type = (intake or {}).get("target_type") or self._standardize_target_type(project, intake or {})
        if target_type == "person":
            project.person_research_intake = dict(intake or {})
        if target_type == "company":
            project.company_research_intake = dict(intake or {})
            if not hasattr(project, "company_professional_platform_attempts"):
                audits = [a for a in getattr(project, "artifacts", [])
                          if a.artifact_type == "professional_platform_audit"]
                if audits:
                    latest = max(audits, key=lambda a: a.version or 0)
                    try:
                        restore_platform_audit(project, json.loads(latest.content))
                    except (ValueError, TypeError):
                        _emit(emit, "report", "desktop_report_agent", "专业平台覆盖记录无法读取",
                              "本轮不据此认定已查询或无记录。", status="warning")
            # A template fallback after a writer failure must not inherit
            # successful diagnostics from an earlier generation attempt.
            project.company_verified_chapters_required = True
            project.company_summary_package = {}
            for chapter_key in ("summary", "governance", "history", "operations", "reputation", "business",
                                "management", "people", "judicial", "diligence", "risk_register", "assessment"):
                setattr(project, f"company_{chapter_key}_diagnostic", {})
        if target_type == "industry":
            # Transient generation context: no schema migration is required and
            # all downstream agents can read the same normalized scope.
            setattr(project, "industry_scope", (intake or {}).get("industry_scope") or self._resolve_industry_scope(project, {}, intake or {}))
        agent = self._report_agents.get(target_type, self._report_agents["company"])
        _emit(emit, "report", "desktop_report_agent", "报告 Agent 启动", "", status="running")
        result_queue: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=1)
        active_trace = {
            "enabled": True,
            "current_label": "report_starting",
            "current_detail": "",
            "current_section": "",
            "current_started_at": time.monotonic(),
            "last_event_at": time.monotonic(),
        }

        def guarded_emit(event: dict[str, Any]) -> None:
            now = time.monotonic()
            active_trace["last_event_at"] = now
            if event.get("status") == "running":
                active_trace["current_label"] = str(event.get("label") or "")
                active_trace["current_detail"] = str(event.get("detail") or "")
                active_trace["current_section"] = str(event.get("section") or "")
                active_trace["current_started_at"] = now
            elif event.get("status") in {"done", "error", "fallback"}:
                active_trace["current_label"] = str(event.get("label") or "")
                active_trace["current_detail"] = str(event.get("detail") or "")
                active_trace["current_section"] = str(event.get("section") or active_trace.get("current_section") or "")
            if active_trace["enabled"] and emit:
                emit(event)

        def report_invoke(role: str, prompt: str, trace_emit: TraceEmitter | None = None) -> str:
            if target_type == "company" and (role.endswith("摘要 Agent") or role.endswith("摘要修订 Agent")):
                return self._invoke_company_summary(role, prompt, emit=trace_emit)
            if target_type == 'industry':
                return self._invoke_industry_report(role, prompt, emit=trace_emit)
            if target_type == "person" and role.endswith("总编 Agent"):
                return self._invoke_person_report_editor(role, prompt, emit=trace_emit)
            if target_type == "person" and "章节 Agent" in role:
                return self._invoke_person_report_section(role, prompt, emit=trace_emit)
            if target_type == "company" and "分批主编 Agent" in role:
                return self._invoke_company_report_editor(role, prompt, emit=trace_emit)
            return self._invoke(role, prompt, emit=trace_emit)

        writer_project = project
        if target_type == "person":
            # ORM sessions and lazy relationships belong to the workflow thread.
            # Freeze all source fields before the background writer starts.
            writer_project = SimpleNamespace(**{
                key: getattr(project, key, "") for key in ("id", "title", "target_name", "target_type", "industry", "description")
            })
            writer_project.sources = [SimpleNamespace(**{
                key: getattr(source, key, None) for key in
                ("id", "url", "title", "content", "summary", "source_type", "source_metadata", "credibility_score", "created_at")
            }) for source in list(project.sources or [])]
            writer_project.person_research_intake = dict(getattr(project, "person_research_intake", {}) or {})
            writer_project.person_platform_attempts = list(getattr(project, "person_platform_attempts", []) or [])
            writer_project.person_retrieval_audit = dict(getattr(project, "person_retrieval_audit", {}) or {})

        def target() -> None:
            try:
                final_text = agent.generate(
                    writer_project,
                    cleaned_json,
                    risk_json,
                    invoke=report_invoke,
                    clip=_clip,
                    emit=_emit,
                    trace_emit=guarded_emit,
                )
                result_queue.put(("ok", final_text))
            except Exception as exc:
                result_queue.put(("error", str(exc)))

        threading.Thread(target=target, daemon=True).start()
        status = "running"
        final = ""
        started_at = time.monotonic()
        heartbeat_seconds = _env_int("REPORT_HEARTBEAT_SECONDS", 10, 5, 120)
        while True:
            try:
                status, final = result_queue.get(timeout=heartbeat_seconds)
                break
            except queue.Empty:
                elapsed = int(time.monotonic() - started_at)
                current_elapsed = int(time.monotonic() - float(active_trace.get("current_started_at") or started_at))
                idle_elapsed = int(time.monotonic() - float(active_trace.get("last_event_at") or started_at))
                current_label = str(active_trace.get("current_label") or "report_generating")
                current_section = str(active_trace.get("current_section") or "")
                current_detail = str(active_trace.get("current_detail") or "")
                slow_threshold = _env_int("REPORT_STEP_SLOW_WARNING_SECONDS", 180, 30, 1800)
                heartbeat_label = "报告生成心跳正常"
                heartbeat_status = "running"
                if current_elapsed >= slow_threshold:
                    heartbeat_label = "当前章节耗时较久，模型仍在返回"
                _emit(
                    emit,
                    "report",
                    "desktop_report_agent",
                    heartbeat_label,
                    (
                        f"总耗时 {elapsed}s；当前步骤 {current_elapsed}s；"
                        f"距上一条后端事件 {idle_elapsed}s；当前章节：{current_section or '-'}；"
                        f"当前动作：{current_label}；说明：{current_detail or '模型调用中，未设置强制超时'}"
                    ),
                    heartbeat=True,
                    elapsed_seconds=elapsed,
                    current_elapsed_seconds=current_elapsed,
                    idle_seconds=idle_elapsed,
                    current_label=current_label,
                    current_section=current_section,
                    current_detail=current_detail,
                    status=heartbeat_status,
                )
        active_trace["enabled"] = False
        if target_type == "person":
            for key in ("person_evidence_contract", "person_delivery_diagnostic", "person_section_packages"):
                if hasattr(writer_project, key):
                    setattr(project, key, getattr(writer_project, key))
        if status == "error":
            _emit(emit, "report", "desktop_report_agent", "报告 Agent 执行失败", "", status="error")
            raise RuntimeError(final)
        if final.strip():
            return final
        _emit(emit, "report", "desktop_report_agent", "报告生成异常", "", status="error")
        raise RuntimeError("report generation returned empty content")

    def _select_report_outline(self, project: ResearchProject, intake: dict[str, Any] | None = None) -> list[tuple[str, list[str]]]:
        intake = intake or {}
        target_type = (project.target_type or "").lower()
        research_type = str(intake.get("research_type") or "").lower()
        company_name = str(intake.get("company_name") or "").strip()
        title_blob = f"{project.title} {project.description} {project.industry} {research_type}".lower()
        if any(key in target_type for key in ["person", "founder", "individual", "个人", "人物", "创始人"]):
            return self._report_agents["person"].outline
        if company_name and any(key in research_type for key in ["商业", "due diligence", "risk screening", "尽调", "风险"]):
            return self._report_agents["company"].outline
        if any(key in target_type for key in ["industry", "sector", "赛道", "行业"]) or "cdd" in title_blob or "industry research" in title_blob:
            return self._report_agents["industry"].outline
        return self._report_agents["company"].outline

    def _write_report_section(
        self,
        project: ResearchProject,
        cleaned_json: str,
        risk_json: str,
        index: int,
        section_title: str,
        requirements: list[str],
        emit: TraceEmitter | None = None,
    ) -> str:
        outline = self._select_report_outline(project)
        report_kind = "桌面研究报告"
        for agent in self._report_agents.values():
            if agent.outline is outline:
                report_kind = agent.report_kind
                break
        prompt = build_section_prompt(
            report_kind=report_kind,
            outline=outline,
            project=project,
            cleaned_json=cleaned_json,
            risk_json=risk_json,
            index=index,
            section_title=section_title,
            requirements=requirements,
            clip=_clip,
        )
        answer = self._invoke(f"报告章节 Agent - {section_title}", prompt, emit=emit)
        if answer.strip():
            _emit(emit, "report", "section_writer_agent", "章节写作完成", section_title, section=section_title, status="done")
            return answer.strip()
        return f"## {index}. {section_title}\n\n待核验。本章节需要后续补充核验：{'; '.join(requirements)}。"

    def _consolidate_report_verification_gaps(
        self,
        report: str,
        emit: TraceEmitter | None = None,
        target_type: str = "",
    ) -> str:
        if not report.strip():
            return report
        if target_type == 'person':
            # Person chapters already contain source-bound quotes, explicit
            # review markers and a chapter-15 verification plan. Global prose
            # softening must not rewrite literal source statements such as
            # "未履约", or duplicate them into a generic follow-up appendix.
            return report
        if target_type == "company":
            from report_agents.company_delivery import company_followup_rows, company_followup_plan
            groups=company_followup_rows(report)
            rows=['## 14. 后续研究建议','',
                  '以下按章节列出代表性核验重点，每章最多两项；其余口径、缺口和边界保留在对应章节。核验优先级不等于企业风险等级。','',
                  '| 待核验事项 | 建议核验方式 | 优先级 | 建议材料 |',
                  '| --- | --- | --- | --- |']
            for group in groups:
                items='<br>'.join(group['items'])
                if group['additional']:items+=f"<br>另{group['additional']}项核验条件见第{group['chapter']}章对应小节。"
                plans=[company_followup_plan(item) for item in group['items']]
                action='<br>'.join(dict.fromkeys(plan[0] for plan in plans))
                priority='高' if any(plan[1]=='高' for plan in plans) else '中'
                materials='<br>'.join(dict.fromkeys(plan[2] for plan in plans))
                rows.append(f"| 第{group['chapter']}章：{items.replace('|','／')} | {action} | {priority} | {materials} |")
            if not groups:rows.append('尚未提取出可操作的后续核验项目；需结合章节缺口复核，不能视为已排除风险。')
            replacement='\n'.join(rows)+'\n\n'
            pattern=r'(?ms)^##\s*14[.、．][^\n]*\n.*?(?=^##\s+(?!14[.、．])|\Z)'
            result=re.sub(pattern,lambda _:replacement,report) if re.search(pattern,report) else report.rstrip()+'\n\n'+replacement
            _emit(emit,'report','desktop_report_agent','公司待核验事项已按章节归并到第14章',f'chapters={len(groups)}',status='done')
            return result.rstrip()+'\n'
        softened = self._soften_gap_phrasing(report)
        # Rebuild this generated appendix on every run. Older reports may contain
        # clipped Markdown table rows that should never be carried into delivery.
        softened = re.sub(r"(?ms)^## 集中式待核验清单\s*$.*\Z", "", softened).rstrip()
        markers = ["待核验", "证据不足", "无法确认", "未能确认"]
        gap_lines: list[str] = []
        for line in softened.splitlines():
            text = line.strip(" >-\t")
            if not text or not any(marker in text for marker in markers):
                continue
            if line.lstrip().startswith(("|", "#", "<!--")):
                continue
            if "...[truncated]" in text or len(text) > 240:
                continue
            if any(token in text for token in ["待核验事项 |", "为什么公开检索", "建议核验方式 |"]):
                continue
            if "本次已检索公开来源未形成可引用记录；相关核验事项见第14章" in text:
                continue
            text = re.sub(r"^\d+[.)、]\s*", "", text).strip()
            if len(text) >= 8:
                gap_lines.append(text)
        deduped: list[str] = []
        seen: set[str] = set()
        for item in gap_lines:
            key = re.sub(r"\s+", "", item)[:80]
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if len(deduped) >= 15:
                break
        if not deduped:
            return softened
        rows = [
            "## 集中式待核验清单",
            "",
            "| 待核验事项 | 为什么公开检索无法确认 | 建议核验方式 | 优先级 | 需客户/公司/访谈/走访提供材料 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in deduped:
            reason, action, priority, materials = self._verification_plan_for_gap(item)
            rows.append(f"| {item.replace('|', ' / ')} | {reason} | {action} | {priority} | {materials} |")
        _emit(emit, "report", "desktop_report_agent", "重复证据缺口已压缩为集中式待核验清单", f"items={len(deduped)}", status="done")
        return softened.rstrip() + "\n\n" + "\n".join(rows) + "\n"

    def _prepend_industry_scope_card(self, project: ResearchProject, report: str) -> str:
        if str(project.target_type or "").lower() != "industry" or not report.strip():
            return report
        if "研究边界与口径" in report[:3000]:
            return report
        scope = getattr(project, "industry_scope", None) or {}
        if not isinstance(scope, dict):
            scope = self._resolve_industry_scope(project, {}, {})
        included = "、".join(scope.get("segments") or []) or "待确认"
        companies = "、".join(scope.get("named_companies") or []) or "未指定"
        capital = {"summary": "一级融资、IPO及二级市场概览；不构成交易建议", "none": "不纳入交易性二级市场指标"}.get(str(scope.get("capital_market") or ""), "待确认")
        assumptions = "；".join(scope.get("assumptions") or []) or "无"
        excluded = "、".join(scope.get("excluded_segments") or []) or "未指定排除项；不同赛道分别呈现，不混算市场规模。"
        card = "\n".join([
            "## 研究边界与口径（自动生成）", "",
            "> 本卡由用户输入与系统默认假设共同生成。若与实际需求不符，应在后续研究前修订范围。", "",
            "| 项目 | 本报告口径 |",
            "| --- | --- |",
            f"| 研究对象 | {scope.get('industry_name') or project.industry or project.target_name} |",
            f"| 纳入范围 | {included} |",
            f"| 不纳入范围 | {excluded} |",
            f"| 地域 | {scope.get('geography') or '中国大陆'} |",
            f"| 数据截止日 | {scope.get('as_of_date') or datetime.now().date().isoformat()} |",
            f"| 研究用途 | {scope.get('purpose') or '日常了解'} |",
            f"| 资本市场模块 | {capital} |",
            f"| 关注公司 | {companies} |",
            f"| 范围置信度 | {scope.get('scope_confidence') or 'medium'} |",
            f"| 系统假设 | {assumptions} |",
            "",
        ])
        first_chapter = re.search(r"(?m)^##\s*1[.、．]", report)
        if first_chapter:
            return report[:first_chapter.start()] + card + report[first_chapter.start():]
        return card + report

    def _soften_gap_phrasing(self, report: str) -> str:
        report = report.replace("暂无充分公开证据", "待核验")
        report = report.replace("暂无公开证据", "待核验")
        report = report.replace("未履约", "履约状态待核验")
        report = report.replace("未兑现", "尚未取得可核验的履行证明")
        report = re.sub(
            r"(?:已|构成|涉嫌)?违反《([^》]+)》第([一二三四五六七八九十百零0-9]+)条",
            r"是否适用《\1》第\2条需由当地律师结合完整事实核验",
            report,
        )
        return report

    def _append_person_report_evidence_index(
        self,
        project: ResearchProject,
        report: str,
        cleaned_json: str,
        emit: TraceEmitter | None = None,
    ) -> str:
        """Backward-compatible entry point for the generic evidence index."""
        return self._append_report_evidence_index(project, report, cleaned_json, emit=emit)

    def _append_report_evidence_index(
        self,
        project: ResearchProject,
        report: str,
        cleaned_json: str,
        emit: TraceEmitter | None = None,
    ) -> str:
        """Append deterministic chapter-to-evidence mappings for all report types.

        The narrative model is useful for analysis but cannot be the system of
        record for citations.  This index is built from the exact facts supplied
        to the chapter writers, so every listed URL can be traced back to a fact
        card and every selected fact is visibly used in the delivered report.
        """
        target_type = str(project.target_type or "").lower()
        if target_type == "person" and report.strip():
            payload = _plain_json(cleaned_json) or {}
            contract = build_person_packages(payload, str(project.target_name or ""), PersonReportAgent.outline,
                                             getattr(project, "person_research_intake", {}), getattr(project, "sources", []) or [])
            previous = getattr(project, "person_delivery_diagnostic", {}) or {}
            result = append_person_index(report, contract["facts"])
            project.person_evidence_contract = contract
            diagnostic = audit_person_report(result, contract, previous.get("degradations", []))
            diagnostic.update({k: previous[k] for k in ("section_diagnostics", "api_attempts", "platform_attempts", "platform_query_coverage", "retrieval_audit", "generation_order") if k in previous})
            project.person_delivery_diagnostic = diagnostic
            return result
        if target_type == "industry" and report.strip():
            payload = _plain_json(cleaned_json)
            if not isinstance(payload, dict):
                payload = {"facts": []}
            result, diagnostic = append_industry_index(report, payload, IndustryReportAgent.outline,
                                                      getattr(project, "industry_section_packages", None))
            facts = payload.get('facts', [])
            diagnostic['fact_quality'] = {
                'structured_fact_count': sum(f.get('is_structured_evidence') is True and f.get('eligible_for_report') is not False for f in facts),
                'verified_numeric_fact_count': sum(f.get('numeric_validation', {}).get('passed') is True and f.get('eligible_for_report') is not False for f in facts),
                'rule_extracted_fact_count': sum(f.get('cleaning_method') == 'industry_rule' for f in facts),
                'llm_extracted_fact_count': sum(f.get('cleaning_method') == 'llm' for f in facts),
            }
            setattr(project, "industry_delivery_diagnostic", diagnostic)
            _emit(emit, "report", "desktop_report_agent", "行业事实引用索引已生成",
                  f"referenced_sources={diagnostic['referenced_sources']}", status="done")
            return result
        if target_type not in {"person", "company", "industry"} or not report.strip():
            return report
        try:
            payload = json.loads(cleaned_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return report
        facts = [item for item in payload.get("facts", []) if isinstance(item, dict)]
        if not facts:
            return report

        # Rebuild on every run so a resumed report cannot carry an index from a
        # prior fact library.
        marker = "## 审计引用索引（自动生成）"
        report = re.sub(rf"(?ms)^## {re.escape(marker[3:])}\s*$.*\Z", "", report).rstrip()
        # IDs are assigned during cleaning and therefore survive a report
        # rebuild.  Older fact libraries receive the same deterministic hash
        # fallback rather than a fragile sequential E-0001 numbering.
        url_to_id: dict[str, str] = {}
        for item in facts:
            url = str(item.get("source_url") or "").rstrip("/")
            if not url.startswith(("http://", "https://", "structured://")):
                continue
            url_to_id.setdefault(
                url,
                str(item.get("evidence_id") or self._stable_evidence_id(
                    url, str(item.get("source_title") or "")
                )),
            )
        if not url_to_id:
            return report

        # Company evidence must be measured against the target-matched pool,
        # not against every URL that happened to appear in a broad search
        # batch.  This is intentionally local to the company pipeline: person
        # identity rules and industry scope rules remain unchanged.
        eligible_company_urls: set[str] = set()
        if target_type == "company":
            for item in facts:
                url = str(item.get("source_url") or "").rstrip("/")
                if url in url_to_id and str(item.get("evidence_scope") or classify_company_fact_scope(item, str(project.target_name or ""))) == "target_direct":
                    eligible_company_urls.add(url)
            return self._append_company_claim_evidence_index(
                project,
                report,
                facts,
                total_traceable_sources=len(url_to_id),
                eligible_company_sources=len(eligible_company_urls),
                emit=emit,
            )

        rows_by_section: list[tuple[int, str, list[dict[str, Any]]]] = []
        selected_urls: set[str] = set()
        # The same selection routine used by the chapter prompt becomes a
        # deterministic audit record.  This prevents the model from silently
        # omitting its input URLs and keeps the appendix bounded/readable.  A
        # source is assigned only once across the index: this deliberately
        # favors breadth over repeating the same famous source in every chapter.
        report_agents = getattr(self, "_report_agents", {})
        agent = report_agents.get(target_type) if isinstance(report_agents, dict) else None
        fallback_agents = {"person": PersonReportAgent, "company": CompanyReportAgent, "industry": IndustryReportAgent}
        outline = agent.outline if agent is not None else fallback_agents[target_type]().outline
        for index, (title, requirements) in enumerate(outline, 1):
            if target_type == "industry" and index >= 14:
                # Chapter 14 is generated from this ledger and chapter 15 is
                # a verification plan; neither should consume a fresh source
                # quota that belongs to evidence-bearing chapters 1-13.
                break
            if target_type == "company" and index >= 13:
                # The company source chapter and the verification plan are
                # deterministic delivery sections.  They do not need a fresh
                # evidence quota beyond chapters 1-12.
                break
            remaining_facts = [
                item for item in facts
                if str(item.get("source_url") or "").rstrip("/") in url_to_id
                # The audit index must show breadth, not the same famous URL
                # repeated for every chapter.  Cross-chapter reuse remains
                # possible in narrative prose after the initial allocation.
                and str(item.get("source_url") or "").rstrip("/") not in selected_urls
            ]
            if not remaining_facts:
                break
            selection_payload = dict(payload)
            selection_payload["facts"] = remaining_facts
            section_payload = _focused_cleaned_json(
                json.dumps(selection_payload, ensure_ascii=False),
                title,
                requirements,
                str(project.target_name or ""),
                str(project.target_type or ""),
            )
            try:
                section_facts = json.loads(section_payload).get("facts", [])
            except (TypeError, ValueError, json.JSONDecodeError):
                section_facts = []
            usable = []
            for item in section_facts:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("source_url") or "").rstrip("/")
                if url not in url_to_id:
                    continue
                usable.append(item)
                selected_urls.add(url)
                if target_type == "industry" and len(usable) >= _env_int("INDUSTRY_REPORT_INDEX_SOURCES_PER_CHAPTER", 3, 1, 5):
                    break
                if target_type == "person" and len(usable) >= _env_int("PERSON_REPORT_INDEX_SOURCES_PER_CHAPTER", 4, 1, 8):
                    break
                if target_type == "company" and len(usable) >= 5:
                    break
            if usable:
                rows_by_section.append((index, title, usable))

        if not rows_by_section:
            return report
        lines = [
            "## 审计引用索引（自动生成）",
            "",
            "> 本索引由清洗事实库自动生成，不依赖模型自行抄写链接。每个证据编号可回溯至原始事实卡及其 URL；同一来源在不同章节出现时表示其分别支持对应章节的核验范围。",
            "",
            f"> 已纳入本报告章节证据包的唯一来源：{len(selected_urls)} / 清洗事实库可追溯来源：{len(url_to_id)}。"
            + (f"目标主体匹配可用来源：{len(eligible_company_urls)}。" if target_type == "company" else "")
            + "未纳入正文证据包的来源仍保留在项目证据台账，不构成被删除或否定。",
            "",
        ]
        for index, title, section_facts in rows_by_section:
            lines.extend([
                f"### 支持第 {index} 章：{title}",
                "",
                "| 证据编号 | 事实摘录 | 来源标题 | URL |",
                "| --- | --- | --- | --- |",
            ])
            for item in section_facts:
                url = str(item.get("source_url") or "").rstrip("/")
                fact = re.sub(r"\s+", " ", str(item.get("fact") or "")).replace("|", "/")[:360]
                source_title = re.sub(r"\s+", " ", str(item.get("source_title") or "公开来源")).replace("|", "/")[:120]
                if target_type == "industry":
                    module = re.sub(r"\s+", " ", str(item.get("module") or "待标注"))[:60]
                    date = re.sub(r"\s+", " ", str(item.get("date") or item.get("fact_date") or "待标注"))[:40]
                    lines.append(f"| {url_to_id[url]} | 第 {index} 章：{title} | {module} | {fact} | {source_title} | {date} | {url} |")
                else:
                    lines.append(f"| {url_to_id[url]} | {fact} | {source_title} | {url} |")
            lines.append("")
        _emit(
            emit,
            "report",
            "desktop_report_agent",
            "审计引用索引已由事实库自动生成",
            f"referenced_sources={len(selected_urls)}, total_fact_sources={len(url_to_id)}, sections={len(rows_by_section)}",
            referenced_sources=len(selected_urls),
            total_fact_sources=len(url_to_id),
            status="done",
        )
        index_text = "\n".join(lines).rstrip()
        if target_type in {"industry", "company", "person"}:
            # Chapter 14 is a compact delivery index, never a model-invented
            # source list.  The full fact card remains in the project ledger;
            # putting 280-character excerpts into seven narrow Word columns
            # turned a few dozen sources into hundreds of unusable pages.
            source_chapter = 14 if target_type in {"industry", "person"} else 13
            next_chapter = 15 if target_type in {"industry", "person"} else 14
            # Person reports use the same compact 4-column layout as industry;
            # company reports keep their existing compact format.
            if target_type == "person":
                ledger_rows = [
                    f"## {source_chapter}. 信息来源（自动生成审计索引）", "",
                    "> 本章为交付版精简索引；证据编号已链接至原始 URL 或结构化平台记录。完整事实摘录、证据强度和原始内容保留在项目证据台账。", "",
                    "| 证据编号 | 来源标题 | 信源等级/类型 | 支持章节 |",
                    "| --- | --- | --- | --- |",
                ]
                for _index, _title, section_facts in rows_by_section:
                    for item in section_facts:
                        url = str(item.get("source_url") or "").rstrip("/")
                        source_title = re.sub(r"\s+", " ", str(item.get("source_title") or "公开来源")).replace("|", "/")[:80]
                        level = str(item.get("evidence_level") or item.get("source_grade") or item.get("evidence_type") or "待标注")
                        ledger_rows.append(f"| [{url_to_id[url]}]({url}) | {source_title} | {level} | 第 {_index} 章 |")
            else:
                ledger_rows = [
                    f"## {source_chapter}. 信息来源（自动生成审计索引）", "",
                    "> 本章为交付版精简索引；完整事实摘录、模块、日期及原始内容保留在项目证据台账。每条记录均可按证据编号或 URL 回溯。", "",
                    "| 支持章节 | 核心来源定位 | 覆盖说明 |" if target_type == "industry" else "| 证据编号 | 支持章节 | 来源与关键摘要 | 台账定位 |",
                    "| --- | --- | --- |" if target_type == "industry" else "| --- | --- | --- | --- |",
                ]
            if target_type != "person":
                if target_type == "industry":
                    for _index, _title, section_facts in rows_by_section:
                        locators: list[str] = []
                        modules: set[str] = set()
                        for item in section_facts:
                            url = str(item.get("source_url") or "").rstrip("/")
                            source_title = re.sub(r"\s+", " ", str(item.get("source_title") or "公开来源")).replace("|", "/")[:42]
                            module = re.sub(r"\s+", " ", str(item.get("module") or item.get("category") or "行业公开来源")).replace("|", "/")[:18]
                            modules.add(module)
                            # Keep the URL visible so Word turns it into a hyperlink.
                            locators.append(f"{url_to_id[url]}｜{source_title}｜{url}")
                        locator_cell = "<br>".join(locators) if locators else "-"
                        coverage = "、".join(sorted(modules)) if modules else "核心公开来源"
                        ledger_rows.append(f"| 第 {_index} 章：{_title} | {locator_cell} | {coverage} |")
                else:
                    for _index, _title, section_facts in rows_by_section:
                        for item in section_facts:
                            url = str(item.get("source_url") or "").rstrip("/")
                            fact = re.sub(r"\s+", " ", str(item.get("fact") or "")).replace("|", "/")[:32]
                            source_title = re.sub(r"\s+", " ", str(item.get("source_title") or "公开来源")).replace("|", "/")[:36]
                            locator = f"原始链接 → {url}"
                            ledger_rows.append(f"| {url_to_id[url]} | 第 {_index} 章：{_title} | {source_title}：{fact} | {locator} |")
            ledger_rows.extend([
                "",
                f"> 已纳入章节证据包的唯一来源：{len(selected_urls)} / 清洗事实库可追溯来源：{len(url_to_id)}。"
                + (f"目标主体匹配可用来源：{len(eligible_company_urls)}。" if target_type == "company" else ""),
            ])
            ledger = "\n".join(ledger_rows)
            source_pattern = (
                rf"(?ms)^##\s*{source_chapter}[.、．][^\n]*\n.*?(?=^##\s*{next_chapter}[.、．]|\Z)"
                if target_type == "company"
                else rf"(?ms)^##\s*{source_chapter}[.、．]\s*信息来源[^\n]*\n.*?(?=^##\s*{next_chapter}[.、．]|\Z)"
            )
            if re.search(source_pattern, report):
                report = re.sub(source_pattern, ledger + "\n\n", report)
            else:
                next_match = re.search(rf"(?m)^##\s*{next_chapter}[.、．]", report or "")
                if next_match:
                    report = report[:next_match.start()].rstrip() + "\n\n" + ledger + "\n\n" + report[next_match.start():].lstrip()
                else:
                    report = report.rstrip() + "\n\n" + ledger + "\n"
            return report.rstrip() + "\n"
        return report.rstrip() + "\n\n" + index_text + "\n"

    def _append_company_claim_evidence_index(
        self,
        project: ResearchProject,
        report: str,
        facts: list[dict[str, Any]],
        *,
        total_traceable_sources: int,
        eligible_company_sources: int,
        emit: TraceEmitter | None = None,
    ) -> str:
        """Build chapter 13 from E-IDs actually present in company chapters 1-12."""
        from report_agents.company_delivery import source_excerpt
        from report_agents.company_governance import cited_evidence_ids
        outline = CompanyReportAgent().outline
        summary_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in getattr(project, "company_summary_package", {}).get("facts", []):
            summary_by_id[str(record.get("evidence_id") or "").upper()].append(record)
        governance_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in getattr(project, "company_governance_package", {}).get("facts", []):
            for evidence_id in record.get("evidence_ids", []):
                governance_by_id[evidence_id.upper()].append(record)
        history_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in getattr(project, "company_history_package", {}).get("facts", []):
            for evidence_id in record.get("evidence_ids", []):
                history_by_id[evidence_id.upper()].append(record)
        operations_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in getattr(project, "company_operations_package", {}).get("facts", []):
            for evidence_id in record.get("evidence_ids", []):
                operations_by_id[evidence_id.upper()].append(record)
        reputation_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in getattr(project, "company_reputation_package", {}).get("facts", []):
            for evidence_id in record.get("evidence_ids", []):
                reputation_by_id[evidence_id.upper()].append(record)
        business_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in getattr(project, "company_business_package", {}).get("facts", []):
            for evidence_id in record.get("evidence_ids", []):
                business_by_id[evidence_id.upper()].append(record)
        management_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in getattr(project, "company_management_package", {}).get("facts", []):
            for evidence_id in record.get("evidence_ids", []):
                management_by_id[evidence_id.upper()].append(record)
        people_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
        people_package = getattr(project, "company_people_package", {})
        for record in people_package.get("facts", []) + people_package.get("source_notes", []):
            for evidence_id in record.get("evidence_ids", []):
                people_by_id[evidence_id.upper()].append(record)
        judicial_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
        judicial_package = getattr(project, "company_judicial_package", {})
        for record in judicial_package.get("facts", []) + judicial_package.get("source_notes", []) + judicial_package.get("coverage", []):
            for evidence_id in record.get("evidence_ids", []):
                judicial_by_id[evidence_id.upper()].append(record)
        diligence_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in getattr(project, "company_diligence_package", {}).get("facts", []):
            for evidence_id in record.get("evidence_ids", []):
                diligence_by_id[evidence_id.upper()].append(record)
        risk_register_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in getattr(project, "company_risk_register_package", {}).get("facts", []):
            for evidence_id in record.get("evidence_ids", []):
                risk_register_by_id[evidence_id.upper()].append(record)
        assessment_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in getattr(project, "company_assessment_package", {}).get("facts", []):
            for evidence_id in record.get("evidence_ids", []):
                assessment_by_id[evidence_id.upper()].append(record)
        facts_by_id: dict[str, dict[str, Any]] = {}
        for item in facts:
            url = str(item.get("source_url") or "").rstrip("/")
            # Structured business records (for example QCC and Xiniu) use a
            # ``structured://`` locator rather than a public web URL.  They
            # are core company evidence and must be indexed just like web
            # sources whenever the body cites their E-ID.
            if not url:
                continue
            evidence_id = str(item.get("evidence_id") or self._stable_evidence_id(
                url, str(item.get("source_title") or "")
            )).strip().upper()
            if evidence_id:
                facts_by_id.setdefault(evidence_id, item)

        for evidence_id, records in risk_register_by_id.items():
            # Original-document recovery can supply an event the cleaner
            # omitted altogether. Its source-bound locator must still resolve.
            facts_by_id.setdefault(evidence_id, records[0])
        for evidence_id, records in assessment_by_id.items():
            facts_by_id.setdefault(evidence_id, records[0])

        chapters_by_id: dict[str, set[int]] = {}
        cited_ids: set[str] = set()
        chapter_matches = list(REPORT_CHAPTER_HEADING_RE.finditer(report or ""))
        for position, match in enumerate(chapter_matches):
            chapter = int(match.group(1))
            if chapter < 1 or chapter > 12:
                continue
            end = chapter_matches[position + 1].start() if position + 1 < len(chapter_matches) else len(report)
            section = report[match.end():end]
            for evidence_id in set(cited_evidence_ids(section)):
                canonical = evidence_id.upper()
                cited_ids.add(canonical)
                item = facts_by_id.get(canonical) or facts_by_id.get(evidence_id)
                if not item:
                    continue
                scope = str(item.get("evidence_scope") or classify_company_fact_scope(item, str(project.target_name or "")))
                if (scope == "target_direct" or (scope == "industry_context" and chapter == 5)
                        or (chapter == 2 and canonical in governance_by_id)
                        or (chapter == 3 and canonical in history_by_id)
                        or (chapter == 4 and canonical in operations_by_id)
                        or (chapter == 5 and canonical in reputation_by_id)
                        or (chapter == 6 and canonical in business_by_id)
                        or (chapter == 7 and canonical in management_by_id)
                        or (chapter == 8 and canonical in people_by_id)
                        or (chapter == 9 and canonical in judicial_by_id)
                        or (chapter == 10 and canonical in diligence_by_id)
                        or (chapter == 11 and canonical in risk_register_by_id)
                        or (chapter == 12 and canonical in assessment_by_id)):
                    chapters_by_id.setdefault(canonical, set()).add(chapter)
                elif canonical not in chapters_by_id:
                    # Keep the citation visible in chapter 13 even when it is
                    # later judged out of scope.  The row makes the boundary
                    # auditable instead of causing a generic "missing E-ID"
                    # quality failure.
                    chapters_by_id.setdefault(canonical, set()).add(chapter)

        selected_urls = {
            str(facts_by_id[evidence_id].get("source_url") or "").rstrip("/")
            for evidence_id in chapters_by_id
            if evidence_id in facts_by_id
        }
        ledger_rows = [
            "## 13. 信息来源（自动生成审计索引）",
            "",
            "> 本章仅列正文第1—12章实际引用的证据。相同来源可以支持多个章节，但各章引用的事实重点应分别表述；完整事实卡保留在项目证据台账。",
            "",
            "| 证据编号 | 支持章节 | 来源与关键摘要 | 台账定位 |",
            "| --- | --- | --- | --- |",
        ]
        for evidence_id in sorted(cited_ids - set(chapters_by_id)):
            # Some legacy or risk-derived citations can reach the narrative
            # before the fact card is available in the cleaned-facts payload.
            # They must still be listed so chapter 13 reflects every body
            # citation.  The locator is explicit that the row needs follow-up.
            chapters_by_id[evidence_id] = {0}
        for evidence_id, chapters in sorted(chapters_by_id.items(), key=lambda value: (min(value[1]), value[0])):
            item = facts_by_id.get(evidence_id, {})
            if any(evidence_id in mapping for mapping in (summary_by_id, governance_by_id, history_by_id, operations_by_id, reputation_by_id, business_by_id, management_by_id, people_by_id, judicial_by_id, diligence_by_id, risk_register_by_id, assessment_by_id)):
                # A page-level industry/related classification may have hidden
                # a literal issuer declaration recovered for chapter 2. Keep
                # the source ID, and show the actual field-level claim used.
                admitted = (summary_by_id.get(evidence_id, []) + governance_by_id.get(evidence_id, []) + history_by_id.get(evidence_id, [])
                            + operations_by_id.get(evidence_id, []) + reputation_by_id.get(evidence_id, []) + business_by_id.get(evidence_id, []) + management_by_id.get(evidence_id, []) + people_by_id.get(evidence_id, []) + judicial_by_id.get(evidence_id, []) + diligence_by_id.get(evidence_id, []) + risk_register_by_id.get(evidence_id, []) + assessment_by_id.get(evidence_id, []))
                labels = [label for label, mapping in [("第一章", summary_by_id), ("第二章", governance_by_id), ("第三章", history_by_id),
                                                       ("第四章", operations_by_id), ("第五章", reputation_by_id), ("第六章", business_by_id), ("第七章", management_by_id), ("第八章", people_by_id), ("第九章", judicial_by_id), ("第十章", diligence_by_id), ("第十一章", risk_register_by_id), ("第十二章", assessment_by_id)] if evidence_id in mapping]
                label = labels[0] + "原文核对："
                # Deduplicated claims can cite several originals. Their
                # E-IDs must keep their own URL/title, not all be redirected
                # to the first merged record's document and physical pages.
                item = {**item, "source_url": item.get("source_url") or admitted[0]["source_url"],
                        "source_title": item.get("source_title") or admitted[0]["source_title"],
                        "fact": label + "；".join(dict.fromkeys(str(
                                r.get("value") if r.get("field") else r.get("fact") or r.get("entity") or r.get("value") or "")
                            for r in admitted[:3]))}
            url = str(item.get("source_url") or "").rstrip("/")
            source_title = source_excerpt(str(item.get("source_title") or "公开来源").replace("|", "/"),48)
            fact = source_excerpt(str(item.get("fact") or item.get("evidence_quote") or "正文引用证据编号，事实卡待回溯").replace("|", "/"),90)
            supports = "、".join(
                f"第 {chapter} 章" if 1 <= chapter <= len(outline) else "正文引用位置待回溯"
                for chapter in sorted(chapters)
            )
            if url.startswith(("http://", "https://")):
                locator = f"原始链接 → {url}"
            elif url:
                provider = str(item.get("provider") or item.get("platform") or item.get("source_type") or "商业数据库")
                locator = f"结构化记录 → {provider} / {source_title}"
            else:
                locator = "待回溯事实卡 / 不作为新增事实依据"
            ledger_rows.append(f"| {evidence_id} | {supports} | {source_title}：{fact} | {locator} |")
        if not chapters_by_id:
            ledger_rows.append("| — | 暂无 | 正文尚未形成有效证据编号引用 | 待补充 |")
        ledger_rows.extend([
            "",
            f"> 已纳入章节证据包的唯一来源：{len(selected_urls)} / 清洗事实库可追溯来源：{total_traceable_sources}。"
            f"目标主体匹配可用来源：{eligible_company_sources}。",
        ])
        ledger = "\n".join(ledger_rows)
        source_pattern = r"(?ms)^##\s*13[.、．][^\n]*\n.*?(?=^##\s*14[.、．]|\Z)"
        if re.search(source_pattern, report):
            report = re.sub(source_pattern, ledger + "\n\n", report)
        else:
            chapter_14 = re.search(r"(?m)^##\s*14[.、．]", report)
            insert_at = chapter_14.start() if chapter_14 else len(report)
            report = report[:insert_at].rstrip() + "\n\n" + ledger + "\n\n" + report[insert_at:].lstrip()
        _emit(
            emit,
            "report",
            "desktop_report_agent",
            "公司审计索引已按正文实际 E-ID 生成",
            f"referenced_sources={len(selected_urls)}, evidence_ids={len(chapters_by_id)}",
            referenced_sources=len(selected_urls),
            evidence_ids=len(chapters_by_id),
            status="done",
        )
        return report.rstrip() + "\n"

    def _validate_delivery_report(self, project: ResearchProject, report: str) -> None:
        """Fail closed when a report is a polished shell without its evidence chain."""
        target_type = str(project.target_type or "").lower()
        if target_type not in {"person", "company", "industry"}:
            return
        if target_type == "person" and hasattr(project, "person_evidence_contract"):
            previous = getattr(project, "person_delivery_diagnostic", {}) or {}
            diagnostic = audit_person_report(report, project.person_evidence_contract, previous.get("degradations", []))
            if diagnostic["errors"]:
                raise RuntimeError("人物报告交付质量闸门未通过：" + "；".join(diagnostic["errors"]))
            return
        if target_type == "industry":
            errors = industry_delivery_errors(report, getattr(project, "industry_delivery_diagnostic", {}),
                                               getattr(project, "industry_scope", {}))
            project.industry_quality_issues = [{"message": message, "chapter": (int(match.group(1)) if (match := re.search(r"第(\d+)章", message)) else None)} for message in errors]
            if errors:
                raise RuntimeError("行业报告交付质量闸门未通过：" + "；".join(errors))
            return
        # Count only top-level report chapters. Subheadings like ``### 1.1``
        # previously produced duplicate artificial chapter bodies.
        matches = list(REPORT_CHAPTER_HEADING_RE.finditer(report or ""))
        present = {int(match.group(1)) for match in matches}
        expected_chapters = 14 if target_type == "company" else 15
        missing = [index for index in range(1, expected_chapters + 1) if index not in present]
        substantive = 0
        sourced_sections = 0
        section_bodies: list[str] = []
        for position, match in enumerate(matches):
            end = matches[position + 1].start() if position + 1 < len(matches) else len(report)
            section = report[match.end():end]
            compact = re.sub(r"\s+", "", section)
            section_bodies.append(compact)
            if len(compact) >= 320:
                substantive += 1
            if len(set(re.findall(r"(?:https?|structured)://[^\s)\]|>]+", section))) >= 2:
                sourced_sections += 1
        urls = set(re.findall(r"(?:https?|structured)://[^\s)\]|>]+", report or ""))
        audit_match = re.search(r"已纳入(?:本报告)?章节证据包的唯一来源：(\d+) / 清洗事实库可追溯来源：(\d+)", report or "")
        # Company delivery reports intentionally use compact evidence IDs in
        # Word rather than printing hundreds of long URLs.  Their deterministic
        # audit count is the traceability measure in that presentation mode.
        traceable_url_count = len(urls)
        if target_type in {"company", "person"} and audit_match:
            traceable_url_count = int(audit_match.group(1))
        if target_type == "person" and audit_match:
            source_chapter_match = re.search(r"(?ms)^##\s*14[.、．]\s*信息来源[^\n]*\n(?P<body>.*?)(?=^##\s*15[.、．]|\Z)", report or "")
            source_chapter_body = source_chapter_match.group("body") if source_chapter_match else report or ""
            indexed_chapters = {
                int(value)
                for value in re.findall(r"\|\s*第\s*(\d+)\s*章\s*\|", source_chapter_body)
                if value.isdigit()
            }
            # The compact chapter-14 index is the traceability surface for
            # person reports; narrative chapters are not required to repeat raw
            # URLs inline.
            sourced_sections = max(sourced_sections, len(indexed_chapters))
        env_prefix = {"person": "PERSON", "company": "COMPANY", "industry": "INDUSTRY"}[target_type]
        min_unique_sources = _env_int(
            f"{env_prefix}_REPORT_MIN_UNIQUE_SOURCES",
            30 if target_type == "industry" else 12,
            5,
            200,
        )
        min_sourced_sections = _env_int(
            f"{env_prefix}_REPORT_MIN_SOURCED_SECTIONS",
            12 if target_type == "industry" else 8,
            4,
            15,
        )
        fallback_chapters = (
            (report or "").count("本章为确定性证据保底内容，尚未完成人工分析复核。")
            + (report or "").count("本章为自动检索证据底稿内容，尚未进入人工尽调核验。")
        )
        max_fallback_chapters = _env_int(f"{env_prefix}_REPORT_MAX_FALLBACK_CHAPTERS", 4, 0, expected_chapters)
        repeated_candidates = section_bodies
        if target_type == "company":
            repeated_candidates = [
                body for body in section_bodies
                if "本次已检索公开来源未形成可引用记录；相关核验事项见第14章。" not in body
            ]
        repeated_bodies = len(repeated_candidates) - len(set(repeated_candidates))
        errors: list[str] = []
        if missing:
            errors.append(f"缺少章节：{missing}")
        if target_type != "company" and substantive < 8:
            errors.append(f"实质性章节不足：{substantive}/{expected_chapters}（最低8）")
        if target_type != "company" and traceable_url_count < min_unique_sources:
            errors.append(f"唯一可追溯URL不足：{traceable_url_count}（最低{min_unique_sources}）")
        if target_type != "company" and sourced_sections < min_sourced_sections:
            if target_type == "industry":
                legacy_index_chapters = set(re.findall(r"\|\s*E-[A-Z0-9-]+\s*\|\s*第\s*(\d+)\s*章", report or ""))
                compact_index_chapters = set(re.findall(r"(?m)^\|\s*第\s*(\d+)\s*章\s*[：:]", report or ""))
                sourced_sections = len(legacy_index_chapters | compact_index_chapters)
        if target_type != "company" and sourced_sections < min_sourced_sections:
            errors.append(f"双来源覆盖章节不足：{sourced_sections}/{expected_chapters}（最低{min_sourced_sections}）")
        if target_type == "company":
            if getattr(project, "company_summary_diagnostic", {}).get("degraded"):
                errors.append("第一章摘要未通过校验，原文摘录需人工复核")
            if getattr(project, "company_governance_diagnostic", {}).get("degraded"):
                errors.append("第二章工商股权核查未形成可交付证据，需人工复核")
            if getattr(project, "company_history_diagnostic", {}).get("degraded"):
                errors.append("第三章沿革与成长质量未形成可交付证据，需人工复核")
            if getattr(project, "company_operations_diagnostic", {}).get("degraded"):
                errors.append("第四章治理与运营未形成可交付证据，需人工复核")
            if getattr(project, "company_reputation_diagnostic", {}).get("degraded"):
                errors.append("第五章评价与对标未形成可交付证据，需人工复核")
            if getattr(project, "company_business_diagnostic", {}).get("degraded"):
                errors.append("第六章经营与研发进展未形成可交付证据，需人工复核")
            if getattr(project, "company_management_diagnostic", {}).get("degraded"):
                errors.append("第七章管理团队未形成可交付证据，需人工复核")
            if getattr(project, "company_people_diagnostic", {}).get("degraded"):
                errors.append("第八章文化与人员情况未形成可交付证据，需人工复核")
            if getattr(project, "company_judicial_diagnostic", {}).get("degraded"):
                errors.append("第九章司法记录未形成可交付证据，需人工复核")
            if getattr(project, "company_diligence_diagnostic", {}).get("degraded"):
                errors.append("第十章专项核查未形成具体可追溯对象，需人工复核")
            if getattr(project, "company_risk_register_diagnostic", {}).get("degraded"):
                errors.append("第十一章风险事项或75项核查目录未通过核对，需人工复核")
            if getattr(project, "company_assessment_diagnostic", {}).get("degraded"):
                errors.append("第十二章综合评价或评分计算未通过核对，需人工复核")
            if getattr(project, "company_verified_chapters_required", False):
                for number, key in enumerate(("summary", "governance", "history", "operations", "reputation", "business",
                                             "management", "people", "judicial", "diligence", "risk_register", "assessment"), 1):
                    diagnostic = getattr(project, f"company_{key}_diagnostic", {})
                    if not diagnostic or "degraded" not in diagnostic:
                        errors.append(f"第{number}章缺少本轮原件核对结果，降级模板不能代替验收")
            source_heading = re.search(r"(?m)^##\s*13[.、．]", report or "")
            next_heading = re.search(r"(?m)^##\s*14[.、．]", report or "")
            body_before_sources = (report or "")[:source_heading.start()] if source_heading else (report or "")
            source_index = (
                (report or "")[source_heading.start():next_heading.start()]
                if source_heading and next_heading and next_heading.start() > source_heading.start()
                else ""
            )
            from report_agents.company_governance import cited_evidence_ids
            body_evidence_ids = set(cited_evidence_ids(body_before_sources))
            indexed_evidence_ids = set(re.findall(r"(?m)^\|\s*(E-[A-Z0-9-]{6,})\s*\|", source_index, flags=re.I))
            missing_index_ids = {value.upper() for value in body_evidence_ids} - {value.upper() for value in indexed_evidence_ids}
            if missing_index_ids:
                errors.append("正文证据编号未进入第13章：" + "、".join(sorted(missing_index_ids)))
            if not body_evidence_ids:
                errors.append("正文第1—12章未引用任何有效证据编号")
            for position, match in enumerate(matches):
                chapter = int(match.group(1))
                if chapter < 1 or chapter > 12:
                    continue
                end = matches[position + 1].start() if position + 1 < len(matches) else len(report)
                section = (report or "")[match.end():end]
                compact = re.sub(r"\s+", "", section)
                no_evidence_notice = "本次已检索公开来源未形成可引用记录；相关核验事项见第14章。" in section
                if len(compact) >= 320 and not no_evidence_notice and not cited_evidence_ids(section):
                    errors.append(f"第{chapter}章存在实质性内容但没有证据编号")
            # A desktop search can establish only what its sources show.  Do
            # not let a report turn a non-hit into a clean legal conclusion or
            # a zero-risk score.  Such language must be backed by a reviewed
            # official record, which this automated delivery path cannot prove.
            from report_agents.company_delivery import company_overclaims
            if company_overclaims(report):
                errors.append("存在将公开检索未命中表述为确定不存在/零风险的公司结论")
        if not audit_match:
            errors.append("缺少自动生成的审计引用索引")
        else:
            referenced_sources, total_fact_sources = (int(value) for value in audit_match.groups())
            coverage_env = f"{env_prefix}_REPORT_MIN_EVIDENCE_SOURCE_COVERAGE"
            required_coverage = float(os.getenv(coverage_env, "0.15") or 0.15)
            required_coverage = min(max(required_coverage, 0.05), 1.0)
            # Industry chapters 1-13 are the evidence-bearing chapters and
            # each intentionally receives at most eight URLs.  Do not set an
            # impossible gate above that physical package capacity.
            if target_type == "industry":
                package_capacity = 13 * 8
            elif target_type == "company":
                package_capacity = 12 * 15
            elif target_type == "person":
                per_chapter = _env_int("PERSON_REPORT_INDEX_SOURCES_PER_CHAPTER", 4, 1, 8)
                package_capacity = expected_chapters * per_chapter
            else:
                package_capacity = total_fact_sources
            if target_type == "company":
                eligible_match = re.search(r"目标主体匹配可用来源：(\d+)", report or "")
                eligible_sources = int(eligible_match.group(1)) if eligible_match else 0
                # Company report length follows available evidence. Require a
                # modest share of the admissible pool, without imposing a fixed
                # chapter count that penalizes small companies.
                minimum_referenced = min(
                    eligible_sources or total_fact_sources,
                    package_capacity,
                    max(1, math.ceil((eligible_sources or total_fact_sources) * required_coverage)),
                )
            else:
                denominator = min(total_fact_sources, package_capacity)
                minimum_referenced = min(
                    denominator,
                    package_capacity,
                    max(30 if target_type == "industry" else (12 if target_type == "person" else 20), math.ceil(denominator * required_coverage)),
                )
            if referenced_sources < minimum_referenced:
                errors.append(
                    f"证据来源利用率不足：{referenced_sources}/{total_fact_sources}（最低{minimum_referenced}，"
                    f"覆盖率{required_coverage:.0%}）"
                )
        if target_type == "industry" and "研究边界与口径（自动生成）" not in report:
            errors.append("缺少自动生成的研究边界与口径卡片")
        if fallback_chapters > max_fallback_chapters:
            errors.append(f"证据保底章节过多：{fallback_chapters}/{expected_chapters}（最多{max_fallback_chapters}），需重新生成或人工分析")
        if repeated_bodies:
            errors.append(f"发现重复章节正文：{repeated_bodies}处")
        if "...[truncated]" in report or "<!--" in report:
            errors.append("正文含截断标记或HTML注释")
        noise_hits = [marker for marker in ("上一页 下一页", "error calling tool", "cb=") if marker in (report or "").lower()]
        if noise_hits:
            errors.append("正文含网页抓取噪声：" + ", ".join(noise_hits))
        if re.search(r"https?://(?:www\.)?(?:example\.com|example\.org|example\.net)\b", report or "", flags=re.I):
            errors.append("正文含示例占位链接")
        if errors:
            label = {"person": "人物报告", "company": "公司报告", "industry": "行业报告"}.get(target_type, "报告")
            raise RuntimeError(label + "交付质量闸门未通过：" + "；".join(errors))

    @staticmethod
    def _normalize_report_placeholders(report: str) -> str:
        """Remove model-invented placeholder URLs before indexing/export."""
        text = report or ""
        placeholder_url = re.compile(
            r"https?://(?:www\.)?(?:example\.com|example\.org|example\.net)(?:/[^\s)\]|>。；，、]*)?",
            flags=re.I,
        )
        text = re.sub(
            r"!\[([^\]]*)\]\(" + placeholder_url.pattern + r"\)",
            r"\1（图像链接待系统生成）",
            text,
            flags=re.I,
        )
        text = placeholder_url.sub("占位链接已移除，待系统生成或人工补充真实来源", text)
        text = re.sub(
            r"(?im)^\s*(?:图片证据|图谱证据|股权结构图|关系图)[：:]\s*占位链接已移除，待系统生成或人工补充真实来源\s*$",
            "图谱证据：待系统根据结构化事实生成或由人工补充真实来源。",
            text,
        )
        return text

    def _prepend_review_draft_notice(self, report: str, reason: str) -> str:
        if "待人工复核稿" in (report or "")[:500]:
            return report
        notice = (
            "> **待人工复核稿**：本报告已完成自动生成，但未通过交付质量闸门。"
            "请先按下列原因补充核验或人工修订后再作为正式交付稿使用。\n"
            f">\n> 未通过原因（摘要）：{reason[:600]}" + ("……完整问题见报告质量诊断。" if len(reason) > 600 else "") + "\n\n"
        )
        return notice + (report or "").lstrip()

    def _prepare_industry_delivery(self, project: ResearchProject, report: str, risk_json: str,
                                   emit: TraceEmitter | None = None) -> tuple[str, dict]:
        """Use the same delivery decision for generated reports and reexports."""
        report = re.sub(r'(?m)^> \*\*风险评分说明\*\*：[^\n]*(?:\n\s*\n)?', '', report, count=1).lstrip()
        try:
            from .industry_research import delivery_review_reasons
        except ImportError:
            from industry_research import delivery_review_reasons
        gate_warning = ''
        try:
            self._validate_delivery_report(project, report)
        except RuntimeError as exc:
            if os.getenv('REPORT_SAVE_REVIEW_DRAFT_ON_GATE_FAIL', 'true').strip().lower() not in {'1', 'true', 'yes', 'on'}:
                raise
            gate_warning = str(exc)
        degradations = list(getattr(project, 'industry_report_degradations', []) or [])
        # Preserve an explicit legacy fallback notice even if its old metadata was lost.
        if not degradations and ('模型摘要未通过校验' in report or '模型摘要未通过引用或目录校验' in report):
            degradations.append({'chapter': 1, 'message': '摘要沿用模型校验失败后的事实摘录，综合判断需人工复核。'})
        risk = _plain_json(risk_json)
        project.industry_risk_transparency = (risk or {}).get('risk_transparency', {}) if isinstance(risk, dict) else {}
        reasons = delivery_review_reasons(getattr(project, 'industry_scope', {}) or {},
                                         risk if isinstance(risk, dict) else {}, degradations)
        payload=getattr(project,'industry_evidence_payload',{}) or {}
        if payload.get('evidence_coverage'):
            try:
                from .industry_evidence import claim_ledger
            except ImportError:
                from industry_evidence import claim_ledger
            audit=claim_ledger(report,payload.get('facts',[]),getattr(project,'industry_delivery_diagnostic',{}),
                               payload['evidence_coverage'],{})
            unlocated={c['chapter'] for c in audit['claims'] if 'unlocated_source_quote' in c['issues']}
            reasons += [{'code':'source_locator_missing','chapter':chapter,
                         'message':f'第{chapter}章引用的事实尚未定位到已保存来源原文，需核对结论证据台账。'}
                        for chapter in sorted(unlocated)]
        issues = list(getattr(project, 'industry_quality_issues', []) or [])
        if gate_warning:
            reasons += [{'code': 'evidence_gate_failed', 'chapter': issue.get('chapter'), 'message': issue['message']}
                        for issue in issues if issue.get('message')]
            if not any(r['code'] == 'evidence_gate_failed' for r in reasons):
                reasons.append({'code': 'evidence_gate_failed', 'chapter': None, 'message': gate_warning})
        project.industry_delivery_review_reasons = reasons
        warning = '行业报告需人工复核：' + '；'.join(r['message'] for r in reasons) if reasons else ''
        # Replace our own old notice, so a reexport cannot show stale review reasons.
        report = re.sub(r'\A\s*> \*\*待人工复核稿\*\*.*?(?:\n\s*\n|\Z)', '', report, count=1, flags=re.S).lstrip()
        if project.industry_risk_transparency:
            report = ('> **风险评分说明**：' + project.industry_risk_transparency['notice'] + '\n\n' + report)
        if warning:
            report = ('> **待人工复核稿**：报告已生成，部分证据核验、章节综合写作或风险评估仍需复核。'
                      '请完成下列事项后再作为正式交付稿使用。\n>\n> 复核原因（摘要）：'
                      + warning[:600] + ('……完整原因见报告质量诊断。' if len(warning) > 600 else '') + '\n\n' + report)
            _emit(emit, 'report', 'desktop_report_agent', '行业报告保存为待复核稿', warning,
                  review_reason_count=len(reasons), status='fallback')
        return report, {'delivery_status': 'review_draft' if reasons else 'final_candidate',
                        'risk_transparency': project.industry_risk_transparency,
                        'delivery_review_reasons': reasons, 'quality_issues': issues,
                        'industry_evidence_diagnostic': getattr(project, 'industry_delivery_diagnostic', {}),
                        'generation_degradations': degradations,
                        **({'quality_warning': warning} if warning else {})}

    def _build_report_quality_diagnostic(self, project: ResearchProject, report: str, warning: str) -> str:
        """Persist a reviewable diagnosis alongside a failed-but-exported Word draft."""
        if str(project.target_type or '').lower() == 'person':
            audit = getattr(project, 'person_delivery_diagnostic', {}) or {}
            diagnostics = audit.get('section_diagnostics') or {}
            rows = []
            for chapter in audit.get('chapters', []):
                index = chapter['chapter']
                generation = diagnostics.get(index, diagnostics.get(str(index), {}))
                issues = list(chapter.get('gaps') or [])
                issues += ['模型分析或事实校验拦截：' + str(reason) for reason in generation.get('validation_rejections', [])]
                if generation.get('status') == 'insufficient_evidence' and not issues:
                    issues.append('缺少可引用且身份匹配的本章证据。')
                for issue in issues:
                    text = str(issue).replace('|', '/').replace('\n', ' ')
                    rows.append(f'| 第{index}章 | {text} |')
            table = '\n'.join(rows) or '| 全文 | 自动校验未列出具体缺口，仍须人工核对原文、身份和归属。 |'
            return (f'# {_project_doc_title(project, "报告质量诊断")}\n\n状态：待复核稿，生成完成不代表正式交付验收通过。\n\n'
                    f'质量门记录：{warning}\n\n| 章节 | 待核验或被拦截的事项 |\n| --- | --- |\n' + table +
                    '\n\n复核动作：对照第14章实际引用索引核验原文；按第15章补证；公司资料不能替代个人能力、品行或责任证据。Word逐页视觉验收单独记录。\n')
        if str(project.target_type or '').lower() == 'industry':
            reasons = getattr(project, 'industry_delivery_review_reasons', []) or []
            def cell(value):
                return re.sub(r'\s+', ' ', str(value or '-')).replace('|', '/')
            rows = '\n'.join(f'| {cell(r.get("chapter"))} | {cell(r.get("dimension"))} | {cell(r.get("message"))} |'
                             for r in reasons) or f'| - | - | {cell(warning)} |'
            coverage=(getattr(project,'industry_evidence_payload',{}) or {}).get('evidence_coverage') or {}
            labels={'verified':'已核验','candidate':'待核验候选','missing':'缺证'}
            requirements='\n'.join(f'| {cell(r.get("question"))} | {labels.get(r.get("status"),"待核验")} | {len(r.get("verified_evidence_ids",[]))} |'
                                   for r in coverage.get('requirements',[]))
            coverage_section=('## 指标证据覆盖\n\n候选原文不等于已核验事实；缺证不自动判高风险。\n\n'
                '| 研究问题 | 状态 | 完整事实数 |\n| --- | --- | --- |\n'+requirements+'\n\n') if requirements else ''
            try:
                from .industry_risk import risk_support_markdown
            except ImportError:
                from industry_risk import risk_support_markdown
            risk_section = risk_support_markdown(getattr(project, 'industry_risk_transparency', {}))
            return (f'# {_project_doc_title(project, "报告质量诊断")}\n\n状态：待复核稿，生成完成不代表已经通过正式交付验收。\n\n'
                    '## 复核原因\n\n| 章节 | 风险维度 | 需要复核的事项 |\n| --- | --- | --- |\n' + rows + '\n\n'
                    + coverage_section + risk_section +
                    '## 复核动作\n\n- 对照第15章来源索引核验正文引用、数值与口径。\n'
                    '- 章节采用事实摘录时，人工复核综合判断；补证后重新评估尚未完成的启用风险维度。\n'
                    '- 未启用的资本市场和核心企业尽调不列为必做补采；Word页面版式检查单独查看。\n')
        failures = [item.strip() for item in re.split(r"；|;", warning or "") if item.strip()]
        chapter_rows = []
        matches = list(REPORT_CHAPTER_HEADING_RE.finditer(report or ""))
        for position, match in enumerate(matches):
            chapter = int(match.group(1))
            if chapter > 12:
                continue
            end = matches[position + 1].start() if position + 1 < len(matches) else len(report)
            body = (report or "")[match.end():end]
            no_evidence = "本次已检索公开来源未形成可引用记录；相关核验事项见第14章。" in body
            if str(project.target_type).lower()=="company":
                from report_agents.company_governance import cited_evidence_ids
                evidence_ids=sorted(set(cited_evidence_ids(body)))
            else:evidence_ids=sorted(set(re.findall(r"\bE-[A-Z0-9-]{6,}\b",body,flags=re.I)))
            if no_evidence or (len(re.sub(r"\s+", "", body)) >= 320 and not evidence_ids):
                chapter_rows.append(f"| 第 {chapter} 章 | {'无可引用记录' if no_evidence else '实质性内容缺少 E-ID'} | {', '.join(evidence_ids) or '-'} |")
        failure_lines = "\n".join(f"- {item}" for item in failures) or "- 未记录具体失败原因。"
        table = "\n".join(chapter_rows) or "| - | 未发现章节级证据缺口 | - |"
        return (
            f"# {_project_doc_title(project, '报告质量诊断')}\n\n"
            "状态：待复核稿，不能作为正式交付。\n\n"
            "## 质量门失败原因\n\n" + failure_lines + "\n\n"
            "## 章节证据诊断\n\n| 章节 | 问题 | 正文 E-ID |\n| --- | --- | --- |\n" + table + "\n\n"
            "## 复核动作\n\n- 优先核对主体不匹配来源、正文与第13章审计索引的 E-ID 一致性，以及无证据章节是否应补充公开来源或仅保留缺口说明。\n"
        )

    def _verification_plan_for_gap(self, item: str) -> tuple[str, str, str, str]:
        text = item or ""
        if any(key in text for key in ["专利", "商标", "软著", "知识产权", "备案", "ICP", "算法", "许可", "资质", "处罚", "失信", "被执行", "标准", "国标", "行标", "团标"]):
            return ("已执行对应官方公示与监管渠道专项补搜，但当前公开结果仍不足以确认。", "优先在主管部门官网、国家级公示系统及专业数据库以主体全称/统一代码复核。", "中", "主体准确全称、统一社会信用代码；必要时补充证书、备案回执或官方查询截图。")
        if any(key in text for key in ["客户", "收入", "合同", "供应商", "订单", "回款"]):
            return ("公开网页和工商库无法穿透合同、订单、发票、回款及资金流水。", "客户/供应商访谈，抽样核验合同、发票、银行流水、回款记录。", "高", "Top客户/供应商清单、合同台账、发票、银行流水、访谈名单。")
        if any(key in text for key in ["融资", "股权", "出资", "股东", "实控", "控制权"]):
            return ("已补搜融资公告、投资方披露及工商变更；公开登记仍无法确认协议条款、资金到位和未登记安排。", "调取工商档案，核验股东名册、投资协议、打款凭证、董事会/股东会决议。", "高", "股东名册、投资协议、出资凭证、工商档案、董事会/股东会文件。")
        if any(key in text for key in ["团队", "员工", "离职", "文化", "治理"]):
            return ("内部治理、人员流动和文化信号通常不完整公开披露。", "现/离职员工、供应商、投资人访谈，交叉验证组织架构和制度文件。", "中", "员工花名册、离职率、组织架构、绩效/激励制度、访谈对象名单。")
        return ("公开信息未披露或披露口径不足，无法仅凭桌面检索形成强结论。", "客户补充材料、访谈、走访或付费数据库复核。", "中", "原始证明材料、访谈对象、现场走访记录、第三方数据库截图。")
    def _append_professional_evidence_assets(
        self,
        project: ResearchProject,
        report: str,
        cleaned_json: str,
        emit: TraceEmitter | None = None,
    ) -> str:
        assets: list[str] = []
        target_type = str(project.target_type or "").lower()
        if target_type == "company":
            # Company reports have two distinct questions: who owns the
            # company, and who can actually influence or control it.  Keeping
            # the diagrams separate matches the delivery style of the approved
            # company-report reference and avoids conflating shareholders with
            # executives or affiliated entities.
            equity_key = self._build_relationship_graph_svg(
                project, cleaned_json, title="股权结构分析示意图", graph_kind="equity", emit=emit
            )
            control_key = self._build_relationship_graph_svg(
                project, cleaned_json, title="实控人/关联方分析示意图", graph_kind="relationship", emit=emit
            )
            report = self._insert_company_governance_graphs(report, equity_key, control_key)
            graph_key = equity_key or control_key
        else:
            graph_key = self._build_relationship_graph_svg(project, cleaned_json, title="核心关系网络图", graph_kind="relationship", emit=emit)
            report = self._insert_relationship_graph(report, graph_key, project.target_type)

        professional_sources = [
            source for source in (project.sources or [])
            if self._is_structured_professional_source(source) and self._structured_source_is_safe(source)
        ]
        image_count = 0
        for source in professional_sources:
            meta = source.source_metadata or {}
            provider = meta.get("provider") or source.source_type or "professional"
            for item in meta.get("images") or []:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("object_key") or item.get("url") or "").strip()
                if not key:
                    continue
                if image_count == 0 and not assets:
                    assets.extend(["", "## 专业平台视觉证据与关系图", ""])
                image_count += 1
                caption = f"{provider}-{source.title}-图谱/截图证据 {image_count}"
                assets.extend([f"### {caption}", "", f"![{caption}]({key})", ""])
                vision_text = str(meta.get("vision_text") or "").strip()
                if vision_text:
                    assets.extend(["视觉模型结构化解析：", "", _clip(vision_text, 3000), ""])
                if image_count >= _env_int("REPORT_MAX_VISUAL_EVIDENCE_IMAGES", 8, 0, 30):
                    break
            if image_count >= _env_int("REPORT_MAX_VISUAL_EVIDENCE_IMAGES", 8, 0, 30):
                break

        if not assets:
            if graph_key:
                _emit(emit, "report", "desktop_report_agent", "关系图已插入对应正文章节", "", status="done")
            return report
        _emit(emit, "report", "desktop_report_agent", "专业平台证据图表处理完成", "", status="done")
        marker = "## 专业平台视觉证据与关系图"
        if marker in report:
            return report
        return report.rstrip() + "\n\n" + "\n".join(assets).strip() + "\n"

    def _insert_company_governance_graphs(self, report: str, equity_key: str, control_key: str) -> str:
        """Insert the two company-only governance diagrams into chapter 2."""
        if not equity_key and not control_key:
            return report
        report = re.sub(r"(?mi)^!\[[^\]]*(?:股权结构分析示意图|实控人/关联方分析示意图)[^\]]*\]\([^)]+\)\s*$", "", report)
        blocks: list[str] = []
        if equity_key:
            blocks.extend([
                "### 股权结构分析示意图", "", f"![股权结构分析示意图]({equity_key})", "",
                "> 注：本图最多展示10个已核对的股东节点；完整记录及数据时点以本章表格为准，不由登记持股推定实际控制。", "",
            ])
        if control_key:
            blocks.extend([
                "### 实控人/关联方分析示意图", "", f"![实控人/关联方分析示意图]({control_key})", "",
                "> 注：本图最多展示10个已核对节点；边线只代表标注的任职或明确披露关系，各自时点以本章表格为准，不补出未披露的一致行动或控制关系。", "",
            ])
        block = "\n".join(blocks).rstrip() + "\n\n"
        chapter = re.search(r"(?mi)^##\s*2[.、．]\s*[^\n]*(?:工商|股东|治理)[^\n]*$", report)
        if not chapter:
            return block + report
        next_chapter = re.search(r"(?m)^##\s*3[.、．]\s+", report[chapter.end():])
        insert_at = chapter.end() if not next_chapter else chapter.end() + next_chapter.start()
        return report[:insert_at].rstrip() + "\n\n" + block + report[insert_at:]

    def _insert_relationship_graph(self, report: str, graph_key: str, target_type: str = "company") -> str:
        """Replace model-produced Mermaid with one rendered graph inside the relevant chapter."""
        report = re.sub(r"(?ms)^```mermaid\s*.*?^```\s*", "", report)
        report = re.sub(r"(?mi)^!\[[^\]]*(?:关系网图|关系网络图|关系图)[^\]]*\]\([^)]+\)\s*$", "", report)
        if not graph_key:
            return report
        block = (
            f"![核心关系网络图]({graph_key})\n\n"
            "> 注：本图根据已取得的结构化证据生成；虚线或待核验节点不代表已确认事实。"
        )
        heading = re.search(r"(?mi)^(#{2,5}\s+[^\n]*(?:关系网图|关系网络图|关系图)[^\n]*)$", report)
        if heading:
            return report[:heading.end()] + "\n\n" + block + report[heading.end():]
        anchors = {
            "person": r"(?mi)^(#{2,4}\s+[^\n]*(?:底色画像|履历|关联利益)[^\n]*)$",
            "industry": r"(?mi)^(#{2,4}\s+[^\n]*(?:竞争格局|核心公司|产业链)[^\n]*)$",
            "company": r"(?mi)^(#{2,4}\s+[^\n]*(?:工商|股权|治理底盘)[^\n]*)$",
        }
        anchor = re.search(anchors.get(str(target_type).lower(), anchors["company"]), report)
        insert_at = anchor.end() if anchor else 0
        section = "\n\n### 核心关系网络图\n\n" + block + "\n"
        return report[:insert_at] + section + report[insert_at:]

    def _build_relationship_graph_svg(
        self,
        project: ResearchProject,
        cleaned_json: str,
        title: str = "股东/实控人/关联方关系网图",
        graph_kind: str = "relationship",
        emit: TraceEmitter | None = None,
    ) -> str:
        company_package = getattr(project, "company_governance_package", None) if str(project.target_type or "").lower() == "company" else None
        if company_package is not None:
            try:
                from .report_agents.company_governance import governance_graph_nodes
            except ImportError:
                from report_agents.company_governance import governance_graph_nodes
            nodes = governance_graph_nodes(company_package, graph_kind)
        else:
            nodes = self._professional_graph_nodes(project, graph_kind)
        if len(nodes) < 3 and company_package is None:
            seen = {name for name, _relation, _note in nodes}
            for node in self._cleaned_fact_graph_nodes(project, cleaned_json):
                if node[0] not in seen:
                    nodes.append(node)
                    seen.add(node[0])
                if len(nodes) >= 10:
                    break
        nodes = nodes[:10]

        def esc(value: str) -> str:
            return html.escape(str(value or ""), quote=True)

        def short_text(value: str, limit: int = 24) -> str:
            value = re.sub(r"\s+", " " if company_package is not None and re.search(r"[A-Za-z]", str(value or "")) else "", str(value or "")).strip()
            return value if len(value) <= limit else value[: max(0, limit - 3)] + "..."

        def wrap_lines(value: str, limit: int = 15, max_lines: int = 2) -> list[str]:
            value = short_text(value, limit * max_lines)
            if company_package is not None and re.search(r"[A-Za-z]", value):
                from textwrap import wrap
                return wrap(value, width=limit, break_long_words=False, break_on_hyphens=False)[:max_lines] or [""]
            return [value[index:index + limit] for index in range(0, len(value), limit)][:max_lines] or [""]

        def node_kind(name: str) -> str:
            organization_suffixes = (
                "公司", "集团", "基金", "资本", "控股", "大学", "学院",
                "协会", "商会", "实验室", "研究院", "中心", "机构",
            )
            english_org = company_package is not None and re.search(r"\b(?:LIMITED|LTD|INC|LLC|CORPORATION|PLC|LP)\b", name, re.I)
            return "organization" if english_org or any(token in str(name) for token in organization_suffixes) else "person"

        if not nodes:
            _emit(emit, "report", "desktop_report_agent", "关系网图数据不足，已跳过空图", graph_kind, status="warning")
            return ""

        width, height = 1120, 760
        center_x, center_y = width // 2, height // 2 + 20
        positions = []
        for side, side_nodes in [("left", nodes[::2]), ("right", nodes[1::2])]:
            if not side_nodes:
                continue
            gap = min(118, max(86, 560 // max(1, len(side_nodes))))
            start_y = center_y - gap * (len(side_nodes) - 1) / 2
            x = 220 if side == "left" else 900
            for index, node in enumerate(side_nodes):
                positions.append((x, int(start_y + index * gap), side, *node))

        svg = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="#ffffff"/>',
            f'<text x="44" y="48" font-family="Microsoft YaHei, Arial" font-size="25" font-weight="700" fill="#1f2937">{esc(title)}</text>',
            '<text x="44" y="78" font-family="Microsoft YaHei, Arial" font-size="14" fill="#64748b">分析示意图：基于已取得的结构化记录与可追溯事实生成；待核验关系不代表已确认事实。</text>',
        ]
        if company_package is not None:
            svg.append('<text x="44" y="102" font-family="Microsoft YaHei, Arial" font-size="13" fill="#64748b">图示最多10个已核对节点；完整记录及各自数据时点见第二章表格。边线关系以节点标签为准。</text>')
        for x, y, side, name, relation, note in positions:
            edge_x = x + 160 if side == "left" else x - 160
            dash = ' stroke-dasharray="7 5"' if "待核验" in relation or "不足" in name else ""
            svg.append(f'<line x1="{center_x}" y1="{center_y}" x2="{edge_x}" y2="{y}" stroke="#94a3b8" stroke-width="1.8"{dash}/>')
            label_x = center_x - 145 if side == "left" else center_x + 145
            label_y = int((center_y + y) / 2)
            if company_package is None:
                svg.append(f'<text x="{label_x}" y="{label_y}" font-family="Microsoft YaHei, Arial" font-size="12" fill="#475569" text-anchor="middle">{esc(short_text(relation, 12))}</text>')

        svg.append(f'<rect x="{center_x - 145}" y="{center_y - 46}" rx="10" ry="10" width="290" height="92" fill="#2563eb" stroke="#1d4ed8"/>')
        for offset, line in enumerate(wrap_lines(project.target_name or project.title or "目标公司", 15, 2)):
            svg.append(f'<text x="{center_x}" y="{center_y - 10 + offset * 22}" font-family="Microsoft YaHei, Arial" font-size="18" font-weight="700" fill="#ffffff" text-anchor="middle">{esc(line)}</text>')
        target_role = {"person": "目标人物", "industry": "目标行业", "company": "目标公司"}.get(str(project.target_type or "").lower(), "目标主体")
        svg.append(f'<text x="{center_x}" y="{center_y + 34}" font-family="Microsoft YaHei, Arial" font-size="13" fill="#dbeafe" text-anchor="middle">{target_role}</text>')

        for x, y, side, name, relation, note in positions:
            kind = node_kind(name)
            pending = "待核验" in relation or "待核验" in note
            fill = "#fff7ed" if pending else "#ecfdf5" if kind == "organization" else "#eff6ff"
            stroke = "#fb923c" if pending else "#10b981" if kind == "organization" else "#3b82f6"
            radius = "8" if kind == "organization" else "38"
            svg.append(f'<rect x="{x - 160}" y="{y - 40}" rx="{radius}" ry="{radius}" width="320" height="80" fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>')
            name_lines = wrap_lines(name, 16, 2)
            base_y = y - 13 if len(name_lines) == 1 else y - 21
            for offset, line in enumerate(name_lines):
                svg.append(f'<text x="{x}" y="{base_y + offset * 20}" font-family="Microsoft YaHei, Arial" font-size="14" font-weight="700" fill="#111827" text-anchor="middle">{esc(line)}</text>')
            type_label = "企业/机构" if kind == "organization" else "自然人"
            sub = f"{type_label} | {relation}" if not note else f"{type_label} | {relation} | {note}"
            svg.append(f'<text x="{x}" y="{y + 25}" font-family="Microsoft YaHei, Arial" font-size="12" fill="#475569" text-anchor="middle">{esc(short_text(sub, 28))}</text>')
        svg.append("</svg>")
        key = f"projects/{project.id}/visual_evidence/{graph_kind}_graph_{_now_key()}.svg"
        try:
            research_store.put_bytes(key, "\n".join(svg).encode("utf-8"), "image/svg+xml")
            return key
        except Exception as exc:
            _emit(emit, "report", "desktop_report_agent", "关系网图生成失败", str(exc), status="warning")
            return ""
    def _professional_graph_nodes(self, project: ResearchProject, graph_kind: str) -> list[tuple[str, str, str]]:
        nodes: list[tuple[str, str, str]] = []
        person_target = str(project.target_type or "").lower() == "person"
        target_aliases = {re.sub(r"\s+", "", str(value or "")) for value in [project.target_name, project.title] if str(value or "").strip()}
        bad_names = {
            "字段", "值", "企业名称", "公司名称", "统一社会信用代码", "注册资本", "实缴资本", "成立日期",
            "法定代表人", "登记状态", "摘要", "姓名", "职务", "持股比例", "持股数", "序号", "名称",
            "集团UUID", "集团简称", "集团企业数", "上市公司数", "核心企业数", "公司简介",
        }

        def clean_name(value: str) -> str:
            name = re.sub(r"<br\s*/?>.*$", "", str(value or ""), flags=re.I)
            name = re.sub(r"\[[^\]]+\]\([^)]+\)", "", name)
            name = re.sub(r"`|\*\*", "", name)
            name = re.sub(r"\s+", "", name).strip("|,，。；;[]【】")
            return name

        def valid_name(name: str) -> bool:
            if not name or len(name) < 2 or name in bad_names:
                return False
            if re.search(r"(人民币|万元|万人民币|%|日期|状态|待查|无记录|条目数|工具|代码|编号|UUID)", name):
                return False
            if re.fullmatch(r"[0-9A-Z\-]{6,}", name):
                return False
            compact = re.sub(r"\s+", "", name)
            if any(alias and (compact == alias or compact in alias or alias in compact) for alias in target_aliases):
                return False
            return bool(re.search(r"[\u4e00-\u9fff]", name))

        def is_organization(name: str) -> bool:
            return bool(re.search(r"(?:公司|集团|基金|资本|控股|大学|学院|协会|商会|实验室|研究院|中心|机构)$", name))

        def add(name: str, relation: str, note: str = "") -> None:
            clean = clean_name(name)
            if not valid_name(clean):
                return
            # For a person report, the centre is already the target natural
            # person.  Surrounding nodes must be companies/institutions only;
            # unrelated legal representatives and executives belong in a
            # separate enterprise-governance graph, not this affiliation map.
            if person_target and not is_organization(clean):
                return
            if any(existing == clean for existing, _rel, _note in nodes):
                return
            nodes.append((clean[:26], relation[:18], note[:24]))

        def parse_table_rows(content: str) -> list[dict[str, str]]:
            rows: list[dict[str, str]] = []
            current_header: list[str] = []
            for raw_line in (content or "").splitlines():
                line = raw_line.strip()
                if "|" not in line:
                    continue
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                if not cells or all(not cell for cell in cells):
                    continue
                if all(re.fullmatch(r":?-{2,}:?", cell or "") for cell in cells):
                    continue
                if any(cell in {"股东名称", "持股比例", "姓名", "职务", "企业名称", "法定代表人", "注册资本"} for cell in cells):
                    current_header = cells
                    continue
                if current_header and len(cells) >= min(2, len(current_header)):
                    rows.append({header: (cells[index] if index < len(cells) else "") for index, header in enumerate(current_header)})
            return rows

        professional_sources = [
            source for source in (project.sources or [])
            if self._is_structured_professional_source(source)
            and (
                (
                    person_target
                    and isinstance((source.source_metadata or {}).get("person_affiliation"), dict)
                    and (source.source_metadata or {}).get("person_affiliation")
                )
                or self._structured_source_is_safe(source)
            )
        ]
        for source in professional_sources:
            meta = source.source_metadata or {}
            module = str(meta.get("module") or "")
            tool = str(meta.get("tool") or "")
            provider = str(meta.get("provider") or "")
            content = source.content or source.summary or ""
            affiliation = meta.get("person_affiliation") if isinstance(meta.get("person_affiliation"), dict) else {}
            if person_target and affiliation:
                company_name = str(
                    affiliation.get("canonical_company_name")
                    or affiliation.get("affiliation_name")
                    or meta.get("target")
                    or ""
                )
                relation = str(affiliation.get("relationship_type") or "关联关系待核验")
                add(company_name, relation, provider)

            for match in re.finditer(r"(?:法定代表人|实际控制人|最终受益人)\s*[|：:]\s*([\u4e00-\u9fff·]{2,10})", content):
                if not person_target and graph_kind in {"relationship", "control"}:
                    label = "实际控制人" if "实际控制人" in match.group(0) else "法定代表人"
                    add(match.group(1), label, provider)

            for row in parse_table_rows(content):
                shareholder = row.get("股东名称") or row.get("名称") or ""
                ratio = row.get("持股比例") or row.get("持股数") or ""
                person = row.get("姓名") or ""
                role = row.get("职务") or ""
                company = row.get("企业名称") or ""

                if shareholder and ("股东" in module or "shareholder" in tool.lower() or "股东信息" in content):
                    if graph_kind == "equity":
                        add(shareholder, "股东/投资方", ratio if ratio and ratio != "待查" else provider)
                if not person_target and person and role and graph_kind in {"relationship", "control"}:
                    add(person, role, provider)
                if company and ("集团成员" in content or "集团画像" in content or "group" in tool.lower()):
                    if graph_kind in {"relationship", "control"}:
                        add(company, "集团成员/关联公司", provider)

        return nodes

    def _cleaned_fact_graph_nodes(self, project: ResearchProject, cleaned_json: str) -> list[tuple[str, str, str]]:
        """Build a conservative person-affiliation graph when paid DB rows are absent."""
        try:
            payload = json.loads(cleaned_json)
        except Exception:
            return []
        facts = payload.get("facts") if isinstance(payload, dict) else []
        if not isinstance(facts, list):
            return []
        target = re.sub(r"\s+", "", str(project.target_name or ""))
        relation_terms = ("创立", "创办", "任职", "担任", "董事", "主席", "股东", "持股", "投资", "控制", "合伙", "关联", "所属")
        org_pattern = re.compile(
            r"[A-Za-z0-9\u4e00-\u9fff·（）()]{2,28}(?:集团|公司|基金|资本|控股|大学|学院|协会|商会|实验室|研究院)"
        )
        nodes: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for fact in facts[:500]:
            if not isinstance(fact, dict):
                continue
            if project.target_type=='industry' and fact.get('eligible_for_report') is False:
                continue
            blob = " ".join(str(fact.get(key) or "") for key in ("subject", "predicate", "object", "claim", "fact", "content"))
            compact = re.sub(r"\s+", "", blob)
            if target and target not in compact:
                continue
            if not any(term in blob for term in relation_terms):
                continue
            for name in org_pattern.findall(blob):
                name = name.strip("，。；：:、（）()")
                if target and target in name:
                    name = name.split(target, 1)[-1]
                name = re.sub(r"^(?:曾|现|先后|共同|联合|于|在)*(?:创立|创办|任职于|任职|担任|投资于|投资|控制|关联|所属)", "", name)
                name = re.split(r"(?:并|以及|及其|旗下|随后)", name, maxsplit=1)[0].strip()
                if not name or name == target or name in seen:
                    continue
                seen.add(name)
                relation = next((term for term in relation_terms if term in blob), "公开资料关联")
                grade = str(fact.get("source_grade") or fact.get("grade") or "")
                note = f"{grade}级来源" if grade in {"A", "B"} else "待核验"
                nodes.append((name[:26], relation[:18], note))
                if len(nodes) >= 10:
                    return nodes
        return nodes
    def _cleaned_facts_to_markdown(self, project: ResearchProject, cleaned_json: str) -> str:
        try:
            parsed = json.loads(cleaned_json)
        except Exception:
            return cleaned_json
        facts = parsed.get("facts") if isinstance(parsed, dict) else []
        lines = [
            f"# {project.title or project.target_name or '项目'} 清洗事实库",
            "",
            f"- 项目ID：{project.id}",
            f"- 研究对象：{project.target_name or ''}",
            f"- 对象类型：{project.target_type or ''}",
            f"- 行业：{project.industry or ''}",
            "",
            "## 核心事实",
            "",
        ]
        if isinstance(facts, list):
            for index, fact in enumerate(facts[:500], 1):
                if not isinstance(fact, dict):
                    continue
                text = str(fact.get("fact") or fact.get("evidence_quote") or "").strip()
                if not text:
                    continue
                lines.extend([
                    f"### {index}. {fact.get('source_title') or '来源事实'}",
                    "",
                    text,
                    "",
                    f"- 来源：{fact.get('source_url') or fact.get('source_title') or '待查'}",
                    f"- 模块：{fact.get('module') or ''}",
                    f"- 可信度：{fact.get('confidence') or fact.get('quality_score') or ''}",
                    "",
                ])
        gaps = parsed.get("information_gaps") if isinstance(parsed, dict) else []
        if gaps:
            lines.extend(["## 信息缺口", ""])
            for gap in gaps[:100]:
                lines.append(f"- {gap}")
        return "\n".join(lines)
    def _index_cleaned_facts(
        self,
        project: ResearchProject,
        cleaned_json: str,
        version: int,
        markdown_object_key: str,
    ) -> int:
        parsed = _plain_json(cleaned_json)
        if not isinstance(parsed, dict):
            raise ValueError("清洗事实 JSON 无效，未执行事实索引；请检查清洗产物后重试。")
        else:
            facts = [fact for fact in (parsed.get("facts") or []) if isinstance(fact, dict)]
        if project.target_type=='industry':
            facts=[fact for fact in facts if fact.get('eligible_for_report') is not False]
        if not facts:
            return 0

        from milvus_writer import MilvusWriter

        docs = []
        for index, fact in enumerate(facts):
            text = str(fact.get("fact") or "").strip()
            if not text:
                continue
            evidence = str(fact.get("evidence_quote") or "").strip()
            if evidence and evidence not in text:
                text = f"{text}\n\n证据摘录：{evidence}"
            docs.append(
                {
                    "text": _clip_utf8_bytes(text, 1900),
                    "filename": f"research_project_{project.id}_cleaned_facts_v{version}.md",
                    "file_type": "research_cleaned_fact",
                    "file_path": markdown_object_key,
                    "page_number": 0,
                    "chunk_idx": index,
                    "chunk_id": f"research:{project.id}:cleaned_facts:v{version}:{index}",
                    "parent_chunk_id": f"research:{project.id}:cleaned_facts:v{version}",
                    "root_chunk_id": f"research:{project.id}",
                    "chunk_level": 3,
                    "project_id": project.id,
                    "artifact_type": "cleaned_facts",
                    "artifact_version": version,
                    "target_name": project.target_name or "",
                    "target_type": project.target_type or "",
                    "industry": project.industry or "",
                    "category": str(fact.get("category") or ""),
                    "module": str(fact.get("module") or ""),
                    "source_title": str(fact.get("source_title") or ""),
                    "source_url": str(fact.get("source_url") or ""),
                    "confidence": float(self._bounded_float(fact.get("confidence"), default=0.6)),
                }
            )

        if not docs:
            return 0
        writer = MilvusWriter()
        if project.target_type == "industry":
            manager = getattr(writer, "milvus_manager", None)
            if manager is not None and manager.has_collection():
                # Retry replaces this artifact version only, never another
                # project's vectors or a different version's evidence.
                manager.delete(f'project_id == {int(project.id)} and artifact_type == "cleaned_facts" and artifact_version == {int(version)}')
        writer.write_documents(docs)
        return len(docs)

    def _find_soffice(self) -> str:
        configured = os.getenv("LIBREOFFICE_SOFFICE_PATH", "").strip().strip('"')
        candidates = [
            configured,
            shutil.which("soffice") or "",
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return str(Path(candidate))
        return ""

    def _render_docx_quality(self, docx_payload: bytes) -> tuple[dict[str, Any], bytes]:
        """Render DOCX through LibreOffice without requiring it on the service PATH.

        Rendering is an additive QA signal: generation still succeeds if a local
        workstation has not installed LibreOffice, unless the deployment opts in
        to making it required.
        """
        if os.getenv("DOCX_RENDER_QA_ENABLED", "true").strip().lower() not in {"1", "true", "yes", "on"}:
            return {"docx_render_status": "disabled"}, b""
        soffice = self._find_soffice()
        if not soffice:
            return {"docx_render_status": "unavailable", "docx_render_error": "LibreOffice soffice not found"}, b""
        timeout = _env_int("DOCX_RENDER_QA_TIMEOUT_SECONDS", 120, 20, 600)
        try:
            # Service accounts and sandboxed Windows processes can be denied access
            # to the user TEMP folder. Keep the LibreOffice profile under the
            # application work directory unless an operator overrides it.
            render_root = Path(os.getenv("DOCX_RENDER_QA_WORKDIR", "").strip() or (Path.cwd() / "work" / "docx_render"))
            render_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="rag_docx_render_", dir=str(render_root)) as temp_dir:
                root = Path(temp_dir)
                input_path = root / "report.docx"
                output_dir = root / "out"
                profile_dir = root / "profile"
                input_path.write_bytes(docx_payload)
                output_dir.mkdir()
                profile_dir.mkdir()
                env = os.environ.copy()
                env["PATH"] = str(Path(soffice).parent) + os.pathsep + env.get("PATH", "")
                result = subprocess.run(
                    [
                        soffice, "--headless", f"-env:UserInstallation={profile_dir.as_uri()}",
                        "--convert-to", "pdf:writer_pdf_Export", "--outdir", str(output_dir), str(input_path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=env,
                    check=False,
                )
                pdf_path = output_dir / "report.pdf"
                if result.returncode != 0 or not pdf_path.is_file() or pdf_path.stat().st_size < 1024:
                    detail = (result.stderr or result.stdout or "LibreOffice did not produce a PDF").strip()[:800]
                    return {"docx_render_status": "failed", "docx_render_error": detail}, b""
                pdf_payload = pdf_path.read_bytes()
                if not pdf_payload.startswith(b"%PDF-"):
                    return {"docx_render_status": "failed", "docx_render_error": "rendered output is not a PDF"}, b""
                page_count = 0
                try:
                    from pypdf import PdfReader
                    page_count = len(PdfReader(pdf_path).pages)
                except Exception:
                    pass
                return {
                    "docx_render_status": "passed",
                    "docx_render_engine": "LibreOffice",
                    "docx_render_page_count": page_count,
                }, pdf_payload
        except subprocess.TimeoutExpired:
            return {"docx_render_status": "failed", "docx_render_error": f"LibreOffice render timed out after {timeout}s"}, b""
        except Exception as exc:
            return {"docx_render_status": "failed", "docx_render_error": str(exc)[:800]}, b""

    def save_artifact(
        self,
        db: Session,
        project: ResearchProject,
        artifact_type: str,
        title: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        created_by: str = "agent",
    ) -> ResearchArtifact:
        current = (
            db.query(ResearchArtifact)
            .filter(ResearchArtifact.project_id == project.id, ResearchArtifact.artifact_type == artifact_type)
            .order_by(ResearchArtifact.version.desc())
            .first()
        )
        version = (current.version + 1) if current else 1
        suffix = "json" if artifact_type in {"research_plan", "source_quality", "cleaned_facts", "risk_assessment", "professional_platform_audit", "industry_claim_ledger", "person_claim_ledger"} else "md"
        artifact_metadata = dict(metadata or {})
        if project.target_type == "person" and artifact_type == "desktop_report":
            artifact_metadata.update(requires_human_review=True, verification_status="source_statements_only", delivery_status="review_draft")
        index_job = None
        object_key = research_store.put_text(
            f"projects/{project.id}/{artifact_type}/{artifact_type}_v{version}.{suffix}",
            content,
            "application/json; charset=utf-8" if suffix == "json" else "text/markdown; charset=utf-8",
        )
        if artifact_type == "cleaned_facts":
            markdown = self._cleaned_facts_to_markdown(project, content)
            markdown_key = research_store.put_text(
                f"projects/{project.id}/{artifact_type}/{artifact_type}_v{version}.md",
                markdown,
                "text/markdown; charset=utf-8",
            )
            artifact_metadata["markdown_object_key"] = markdown_key
            artifact_metadata["raw_markdown_object_key"] = markdown_key
            try:
                index_payload = _plain_json(content)
                if not isinstance(index_payload, dict) or not isinstance(index_payload.get("facts"), list):
                    raise ValueError("清洗事实 JSON 无效，未执行事实索引；请检查清洗产物后重试。")
                sync = os.getenv("VECTOR_INDEX_SYNC", "false").strip().lower() in {"1", "true", "yes", "on"}
                asynchronous = os.getenv("VECTOR_INDEX_ASYNC", "true").strip().lower() in {"1", "true", "yes", "on"}
                if (sync or asynchronous) and os.getenv("RESEARCH_LEGACY_RAG_ENABLED", "false").lower() in ("true", "1"):
                    index_job = (content, version, markdown_key, sync)
                    artifact_metadata.update(vector_indexed=False, vector_indexed_count=0, vector_index_status="queued")
                else:
                    artifact_metadata["vector_indexed"] = False
                    artifact_metadata["vector_index_status"] = "disabled"
            except Exception as exc:
                artifact_metadata["vector_indexed"] = False
                artifact_metadata["vector_index_status"] = "error"
                artifact_metadata["vector_index_error"] = str(exc)
        if artifact_type in {"desktop_report", "proposal"}:
            try:
                docx_payload = markdown_to_docx_bytes(
                    content,
                    title=title,
                    review_draft=bool(artifact_metadata.get("quality_warning") or artifact_metadata.get("requires_human_review")),
                    outline=self._select_report_outline(project) if artifact_type == "desktop_report" else None,
                )
                if project.target_type == 'industry':
                    try:
                        from .industry_research import validate_docx_package
                    except ImportError:
                        from industry_research import validate_docx_package
                    artifact_metadata.update(validate_docx_package(docx_payload))
                docx_key = research_store.put_bytes(
                    f"projects/{project.id}/{artifact_type}/{artifact_type}_v{version}.docx",
                    docx_payload,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
                artifact_metadata["docx_object_key"] = docx_key
                artifact_metadata["default_download_format"] = "docx"
                render_metadata, pdf_payload = self._render_docx_quality(docx_payload)
                artifact_metadata.update(render_metadata)
                if pdf_payload:
                    artifact_metadata["pdf_object_key"] = research_store.put_bytes(
                        f"projects/{project.id}/{artifact_type}/{artifact_type}_v{version}.pdf",
                        pdf_payload,
                        "application/pdf",
                    )
                elif os.getenv("DOCX_RENDER_QA_REQUIRED", "false").strip().lower() in {"1", "true", "yes", "on"}:
                    artifact_metadata["docx_render_required_warning"] = "DOCX render QA is required but did not pass"
            except Exception as exc:
                artifact_metadata["docx_export_error"] = str(exc)
                if project.target_type == "industry":
                    artifact_metadata["delivery_status"] = "export_failed"
                    artifact_metadata['docx_integrity_status'] = 'failed'
        artifact = ResearchArtifact(
            project_id=project.id,
            artifact_type=artifact_type,
            title=title,
            version=version,
            content=content,
            object_key=object_key,
            artifact_metadata=artifact_metadata,
            created_by=created_by,
        )
        db.add(artifact)
        project.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(artifact)
        if artifact_type == "desktop_report":
            from report_knowledge import sync_report_safely
            sync_report_safely(db, project, artifact)
        if index_job:
            self.start_artifact_index(db, project, artifact, wait_seconds=_env_int("VECTOR_INDEX_SYNC_TIMEOUT_SECONDS", 30, 1, 3600) if index_job[3] else 0)
            db.refresh(artifact)
        return artifact

    def start_artifact_index(self, db, project, artifact, wait_seconds=0):
        """Start after artifact commit; worker owns its SQL session and always writes a terminal result."""
        metadata = dict(artifact.artifact_metadata or {})
        if any(t.name == f"research-index-{artifact.id}" and t.is_alive() for t in threading.enumerate()):
            raise ValueError("索引仍在后台执行，请等待完成。")
        if metadata.get("vector_index_status") not in {"queued", "failed", "error", "background_timeout", "disabled"}:
            raise ValueError("索引正在执行或已经完成。")
        content, version, key, artifact_id = artifact.content, artifact.version, metadata.get("markdown_object_key", ""), artifact.id
        payload = _plain_json(content)
        if not isinstance(payload, dict) or not isinstance(payload.get("facts"), list):
            raise ValueError("清洗事实 JSON 无效，不能执行索引。")
        bind = db.get_bind()
        if hasattr(bind, "engine"):
            bind = bind.engine
        snapshot = type("IndexProject", (), {name: getattr(project, name, "") for name in ("id", "title", "target_name", "target_type", "industry")})()
        # Transition before scheduling; API retries lock this artifact row.
        metadata.update(vector_index_status="running", vector_indexed=False, vector_index_started_at=datetime.utcnow().isoformat())
        metadata.pop("vector_index_error", None)
        artifact.artifact_metadata = metadata
        db.commit()
        finished = threading.Event()
        def worker():
            try:
                count = self._index_cleaned_facts(snapshot, content, version, key)
                result = {"vector_index_status": "completed", "vector_indexed": True, "vector_indexed_count": count}
            except Exception as exc:
                result = {"vector_index_status": "failed", "vector_indexed": False, "vector_indexed_count": 0, "vector_index_error": str(exc)[:1000]}
            result["vector_index_finished_at"] = datetime.utcnow().isoformat()
            try:
                with Session(bind=bind) as session:
                    row = session.query(ResearchArtifact).filter(ResearchArtifact.id == artifact_id).with_for_update().first()
                    if row:
                        merged = dict(row.artifact_metadata or {})
                        merged.pop("vector_index_error", None)
                        row.artifact_metadata = {**merged, **result}
                        session.commit()
            finally:
                finished.set()
        threading.Thread(target=worker, daemon=True, name=f"research-index-{artifact_id}").start()
        if wait_seconds and not finished.wait(wait_seconds):
            # Use the same row lock as the worker. Do not overwrite a result
            # that completed between the timeout and this transaction.
            row = db.query(ResearchArtifact).filter(ResearchArtifact.id == artifact_id).with_for_update().populate_existing().first()
            current = dict(row.artifact_metadata or {})
            if current.get("vector_index_status") == "running":
                current.update(vector_index_status="background_timeout", vector_index_error=f"vector indexing exceeded {wait_seconds}s; workflow continued")
                row.artifact_metadata = current
            db.commit()

    def _cleaning_brief(self, project: ResearchProject, plan: dict[str, Any], quality: dict[str, Any]) -> str:
        modules = [item.get("name", "") for item in plan.get("modules", []) if isinstance(item, dict)]
        gaps = quality.get("information_gaps", [])[:8] if isinstance(quality, dict) else []
        return "\n".join(
            [
                f"项目：{project.title}",
                f"研究对象：{project.target_name}",
                f"对象类型：{project.target_type}",
                f"行业：{project.industry}",
                f"重点模块：{', '.join(modules if project.target_type == 'industry' else modules[:8])}",
                *(["行业研究边界：" + json.dumps(getattr(project, 'industry_scope', {}) or plan.get('industry_scope') or {}, ensure_ascii=False)] if project.target_type == "industry" else []),
                f"信息缺口：{'; '.join(str(gap) for gap in gaps)}",
            ]
        )

    def _select_cleaning_sources(self, sources: list[ResearchSource], project: ResearchProject | None = None) -> list[ResearchSource]:
        """Return every safe, non-empty source in a stable quality order.

        This is deliberately not a quota selector.  Ordering is useful for
        deterministic processing and diagnostics, but no global rank cutoff is
        allowed to remove a module, news item, or professional-platform record.
        """
        def is_structured(source: ResearchSource) -> bool:
            return self._is_structured_professional_source(source)

        target_type = str(getattr(project, "target_type", "") or "").lower()
        raw_target = str(getattr(project, "target_name", "") or "")
        aliases = [re.sub(r"\s+", "", raw_target).lower()]
        latin = re.sub(r"[^A-Za-z ]", "", raw_target).strip()
        chinese = "".join(re.findall(r"[\u4e00-\u9fff]", raw_target))
        if latin:
            aliases.append(re.sub(r"\s+", "", latin).lower())
        if chinese:
            aliases.append(chinese)

        def score(source: ResearchSource) -> tuple[int, int, int, int]:
            meta = source.source_metadata or {}
            quality = meta.get("quality") or {}
            quality_score = int(quality.get("score") or source.credibility_score or 0)
            has_content = 1 if (source.content or source.summary or "").strip() else 0
            blob = re.sub(r"\s+", "", f"{source.title} {source.content or source.summary or ''}").lower()
            target_hit = 1 if any(alias and alias in blob for alias in aliases) else 0
            structured_hit = 1 if is_structured(source) else 0
            authoritative = 1 if self._source_grade(source, quality) in {"A", "B"} else 0
            return (target_hit, structured_hit, authoritative, quality_score + has_content)

        fingerprint = getattr(project, "industry_scope_fingerprint", "")
        selected = [
            source for source in sources
            if (not fingerprint or target_type != "industry" or source_in_current_run(source, fingerprint))
            and (source.content or source.summary or "").strip()
            and not self._is_failed_extraction_source(source)
            and self._structured_source_is_safe(source)
        ]
        selected.sort(key=score, reverse=True)
        return selected

    def _select_llm_cleaning_sources(self, sources: list[ResearchSource]) -> list[ResearchSource]:
        """Build a bounded model workload per evidence module, never globally.

        All sources have already been deterministically retained. This pass is
        optional enrichment. Independent evidence buckets prevent a busy module
        or platform from crowding every other chapter out of refinement.
        """
        authority_keywords = ["gov", "court", "regulator", "sec", "司法", "法院", "监管", "公告", "年报", "招股", "财报", "处罚", "诉讼"]

        def score(source: ResearchSource) -> tuple[int, int, int]:
            meta = source.source_metadata or {}
            quality = meta.get("quality") or {}
            blob = f"{source.title} {source.url} {source.source_type} {meta.get('module', '')}".lower()
            structured_hit = 1 if self._is_structured_professional_source(source) else 0
            authority_hit = 1 if any(key.lower() in blob for key in authority_keywords) else 0
            return (structured_hit, authority_hit, int(quality.get("score") or source.credibility_score or 0))

        eligible = [
            source for source in sources
            if not self._is_failed_extraction_source(source) and self._structured_source_is_safe(source)
        ]
        eligible.sort(key=score, reverse=True)
        per_module = _env_int("CLEANING_LLM_SOURCES_PER_MODULE", 6, 1, 30)
        per_module_news = _env_int("CLEANING_LLM_NEWS_PER_MODULE", 4, 1, 30)
        per_structured_bucket = _env_int("CLEANING_LLM_STRUCTURED_PER_BUCKET", 4, 1, 20)
        counts: Counter[str] = Counter()
        news_counts: Counter[str] = Counter()
        structured_counts: Counter[tuple[str, str, str]] = Counter()
        selected: list[ResearchSource] = []
        for source in eligible:
            if self._is_structured_professional_source(source):
                meta = source.source_metadata or {}
                affiliation = meta.get("person_affiliation") if isinstance(meta.get("person_affiliation"), dict) else {}
                bucket = (
                    str(meta.get("module") or source.source_type or "unknown"),
                    str(meta.get("provider") or meta.get("platform") or "professional"),
                    str(affiliation.get("affiliation_name") or meta.get("target") or "subject"),
                )
                if structured_counts[bucket] >= per_structured_bucket:
                    continue
                structured_counts[bucket] += 1
                selected.append(source)
                continue
            meta = source.source_metadata or {}
            module = str(meta.get("module") or source.source_type or "unknown")
            if str(source.source_type or "") == "news":
                if news_counts[module] >= per_module_news:
                    continue
                news_counts[module] += 1
            if counts[module] >= per_module:
                continue
            counts[module] += 1
            selected.append(source)
        return selected

    @staticmethod
    def _stable_evidence_id(url: str, title: str = "", quote: str = "") -> str:
        """A persistent evidence identifier; never renumber it at report time."""
        seed = "\n".join(
            re.sub(r"\s+", " ", str(value or "").strip())
            for value in (url, title, quote)
        )
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12].upper()
        return f"E-{digest}"

    def _annotate_evidence_facts(self, project: ResearchProject, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Attach durable IDs and a report-use boundary to every fact card."""
        target_type = str(getattr(project, "target_type", "") or "").lower()
        target = str(getattr(project, "target_name", "") or "")
        original_issuers = {}
        issuer_conflicts = set()
        if target_type == 'company':
            from report_agents.company_evidence import source_body
            from report_agents.company_management import issuer
            from report_agents.company_history import _issuer_hosts
            from report_agents.company_text import issuer_anchor
            from report_agents.company_governance import get as company_get
            sources = list(getattr(project, 'sources', []) or [])
            hosts = _issuer_hosts(sources, target)
            for source in sources:
                if source_body(source)[1] == 'discovery_summary':continue
                anchor=issuer_anchor(company_get(source,'content',''),target)
                url=str(company_get(source,'url',''))
                if anchor.get('conflicting_heading'):issuer_conflicts.add(url)
                elif issuer(source,target,hosts):original_issuers[url] = anchor
        annotated: list[dict[str, Any]] = []
        industry_sources = self._active_industry_sources(project) if target_type == "industry" else []
        industry_by_url = {str(s.url).rstrip('/'): s for s in industry_sources if s.url}
        industry_by_title = {str(s.title): s for s in industry_sources if not s.url}
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            item = dict(fact)
            item["evidence_id"] = str(item.get("evidence_id") or self._stable_evidence_id(
                str(item.get("source_url") or ""),
                str(item.get("source_title") or ""),
            ))
            if target_type == "company":
                # Identity comes from the retrieved original, never from an
                # extractor-invented issuer field or search title alone.
                item.pop('source_issuer_name', None)
                item.pop('source_issuer_quote', None)
                if (str(item.get('source_url') or '') in issuer_conflicts
                        and item.get('source_entity_validation')!='rejected'):
                    item['source_entity_validation']='related_entity_context'
                anchor = original_issuers.get(str(item.get('source_url') or ''))
                if (anchor and item.get('eligible_for_report') is not False
                        and item.get('source_entity_validation') not in {'rejected','ambiguous','related_entity_context'}
                        and item.get('entity_match') not in {'mismatch','ambiguous','out_of_scope'}):
                    item.update(source_issuer_name=anchor['issuer_name'],source_issuer_quote=anchor['evidence_quote'],
                                source_entity_validation='matched_original_issuer')
                scope = classify_company_fact_scope(item, target)
                item["evidence_scope"] = scope
                # A context item is retained for the industry chapter but never
                # eligible for company risk scoring or company-fact conclusions.
                if scope != "target_direct":
                    item["eligible_for_risk_scoring"] = False
                if scope == "noise":
                    item["eligible_for_report"] = False
            elif target_type == "industry":
                blob = " ".join(
                    str(item.get(key) or "")
                    for key in ("module", "fact", "source_title", "category", "evidence_quote")
                )
                scope = str(item.get("evidence_scope") or "")
                if not scope:
                    if any(word in blob for word in ("代表企业", "龙头", "市场份额", "竞争格局", "年报", "收入结构", "业务分部")):
                        scope = "representative_company"
                    elif any(word in blob for word in ("投融资", "IPO", "并购", "上市", "估值", "招股书", "资本")):
                        scope = "capital_market"
                    elif any(word in blob for word in ("子赛道", "细分", "本地生活", "云服务", "AI", "平台经济")):
                        scope = "segment_level"
                    else:
                        scope = "industry_level"
                item["evidence_scope"] = scope
                item["scope_match"] = str(item.get("scope_match") or "in_scope")
                if scope == "representative_company":
                    item["attribution_boundary"] = "代表企业/龙头公司样本；只能用于竞争格局、商业模式和对标分析，不得写成目标公司尽调结论。"
                elif scope == "segment_level":
                    item["attribution_boundary"] = "细分赛道事实；市场规模、份额、增速和估值口径不得与其他赛道直接相加。"
                elif scope == "capital_market":
                    item["attribution_boundary"] = "资本市场或投融资事实；只能用于资本热度、融资和上市披露判断，不构成交易建议。"
                else:
                    item["attribution_boundary"] = "行业层事实；可用于行业定义、政策、规模、趋势和风险判断。"
            if target_type == "industry":
                url = str(item.get("source_url") or '').rstrip('/')
                source = industry_by_url.get(url) if url else industry_by_title.get(str(item.get("source_title") or ''))
                if source is not None:
                    meta = source.source_metadata or {}
                    for key in ("company_role", "company_name", "module", "industry_name", "segment_name"):
                        if meta.get(key):
                            item[key] = meta[key]
                    if meta.get("company_role") == "requested_due_diligence":
                        item["evidence_scope"] = "representative_company"
                    elif meta.get("evidence_scope") and not fact.get("evidence_scope"):
                        item["evidence_scope"] = meta["evidence_scope"]
                    if company_filing_source(source):
                        item['evidence_scope'] = 'representative_company'
                    item["date"] = item.get("date") or meta.get("published_date") or ""
                    item["source_id"] = getattr(source, "id", None)
                    item["source_title"] = source.title
                    item["quality_score"] = item.get("quality_score") or getattr(source, "credibility_score", 50)
                    item["source_grade"] = item.get("source_grade") or self._source_grade(source, meta.get("quality") or {})
                    if not url:
                        item["source_url"] = f"structured://projects/{project.id}/sources/{source.id}"
                    item["source_provenance_verified"] = True
                else:
                    item["source_provenance_verified"] = False
                    item["eligible_for_report"] = False
                    item["eligible_for_risk_scoring"] = False
                item = annotate_industry_fact(item, getattr(project, "industry_scope", {}) or {"industry_name": target})
            annotated.append(item)
        return annotated

    def _build_evidence_ledger(
        self,
        sources: list[ResearchSource],
        cleaned_sources: list[ResearchSource],
        *, target_type: str = '',
    ) -> list[dict[str, Any]]:
        cleaned_ids = {
            getattr(source, "id", None) or (source.url or id(source))
            for source in cleaned_sources
        }
        rows: list[dict[str, Any]] = []
        seen_content_keys: set[str] = set()
        for source in sources:
            meta = source.source_metadata or {}
            discovery_only = False
            if target_type == 'company':
                from report_agents.company_evidence import source_body
                discovery_only = source_body(source)[1] == 'discovery_summary'
            quality = meta.get("quality") if isinstance(meta.get("quality"), dict) else {}
            source_key = getattr(source, "id", None) or (source.url or id(source))
            failed = self._is_failed_extraction_source(source)
            safe = self._structured_source_is_safe(source)
            canonical_url = (source.url or "").split("#", 1)[0]
            canonical_url = re.sub(r"([?&])(utm_[^=&]+|spm|from|clickfrom|fr|source)=[^&]*", r"\1", canonical_url)
            normalized = re.sub(r"\s+", "", f"{source.title}{(source.content or source.summary or '')[:300]}").lower()
            content_key = canonical_url or normalized[:240]
            duplicate = bool(content_key and content_key in seen_content_keys)
            if content_key:
                seen_content_keys.add(content_key)
            person_affiliation = meta.get("person_affiliation") if isinstance(meta.get("person_affiliation"), dict) else {}
            processed = source_key in cleaned_ids
            cleaned = bool(processed and not failed and safe and not duplicate)
            rows.append({
                "evidence_id": self._stable_evidence_id(source.url, source.title),
                "source_id": getattr(source, "id", None),
                "title": source.title,
                "url": source.url,
                "subject": meta.get("target") or person_affiliation.get("affiliation_name") or "",
                "person_affiliation": person_affiliation,
                "module": meta.get("module") or source.source_type or "unknown",
                "source_type": source.source_type,
                "provider": meta.get("provider") or "",
                "platform": meta.get("platform") or "",
                "source_grade": self._source_grade(source, quality),
                "entity_validation": meta.get("entity_validation") or meta.get("matched_anchor") or "",
                "identity_status": meta.get("identity_status") or "",
                "content_kind": meta.get("content_kind") or meta.get("extraction_status") or "",
                "content_chars": len(source.content or source.summary or ""),
                "duplicate": duplicate,
                "usable_for_hard_fact": bool(not failed and safe and not discovery_only and self._source_grade(source, quality) in {"A", "B"}),
                "deterministically_processed": processed,
                "deterministically_cleaned": cleaned,
                "status": "duplicate" if duplicate else "discovery_only" if discovery_only else "cleaned" if cleaned else "rejected",
                "rejected_reason": "duplicate" if duplicate else "failed_extraction" if failed else "entity_mismatch" if not safe else "empty_content",
            })
        return rows

    def _fast_clean_sources(
        self,
        sources: list[ResearchSource],
        project: ResearchProject | None = None,
        max_chars_per_source: int = 1200,
        emit: TraceEmitter | None = None,
    ) -> dict[str, Any]:
        facts = []
        identity_quarantine_facts = []
        seen = set()
        low_content_count = 0
        ocr_pending_count = 0
        identity_quarantine_count = 0
        source_errors = 0
        raw_text_limit = _env_int("CLEANING_RAW_TEXT_LIMIT", 20000, 1000, 200000)
        progress_every = _env_int("CLEANING_PROGRESS_EVERY", 10, 1, 100)
        total = len(sources)
        company_mode = str(getattr(project, 'target_type', '') or '').lower() == 'company'
        for index, source in enumerate(sources, 1):
            if total and (index == 1 or index % progress_every == 0):
                _emit(emit, "cleaning", "data_cleaning_agent", "规则清洗来源片段", "", status="running")
            meta = source.source_metadata or {}
            quality = meta.get("quality") or {}
            raw_parts = []
            text_origin = ''
            if company_mode:
                from report_agents.company_evidence import source_body
                body, text_origin = source_body(source)
                parts = [body]
            else:
                parts = [source.summary or "", source.content or "", meta.get("ocr_text") or ""]
            if project.target_type=='industry':
                try:
                    from .industry_evidence import stored_body
                except ImportError:
                    from industry_evidence import stored_body
                parts=[stored_body(source)]
                if not parts[0].strip():
                    source_errors+=1
                    continue
            for part in parts:
                part_text = str(part or "").strip()
                if part_text:
                    raw_parts.append(part_text[:raw_text_limit])
            raw_text = "\n\n".join(raw_parts)
            text = self._clean_source_text(raw_text)
            if not text and not (source.title or source.url):
                continue
            if not text:
                text = "\n".join(part for part in [source.title, source.url] if part).strip()
            is_structured_source = self._is_structured_professional_source(source)
            if is_structured_source and self._is_structured_no_hit_text(text):
                source_errors += 1
                continue
            canonical_url = (source.url or "").split("#", 1)[0]
            canonical_url = re.sub(r"([?&])(utm_[^=&]+|spm|from|clickfrom|fr|source)=[^&]*", r"\1", canonical_url)
            normalized = re.sub(r"\s+", "", f"{source.title}{text[:300]}").lower()
            key = canonical_url or normalized[:240]
            if key in seen:
                continue
            seen.add(key)
            flags = self._source_content_flags(source, text, quality)
            if "low_content" in flags:
                low_content_count += 1
            if "ocr_pending" in flags:
                ocr_pending_count += 1
            source_grade = self._source_grade(source, quality)
            confidence = min(0.95, max(0.3, float(source.credibility_score or quality.get("score") or 50) / 100))
            image_urls = self._extract_image_urls(source)[:_env_int("REPORT_IMAGE_URLS_PER_SOURCE", 6, 0, 30)]
            source_clip_limit = _env_int("CLEANING_STRUCTURED_MAX_CHARS_PER_SOURCE", 8000, 1000, 30000) if is_structured_source else max_chars_per_source
            evidence_limit = min(900 if is_structured_source else 300, source_clip_limit)
            affiliation_context = meta.get("person_affiliation") if isinstance(meta.get("person_affiliation"), dict) else {}
            target_type = str(getattr(project, "target_type", "") or "").lower()
            identity_confidence = str(meta.get("identity_confidence") or "").lower()
            entity_validation = str(meta.get("entity_validation") or "").lower()
            # Each report type owns its own admissibility control.  In
            # particular, a low-confidence same-name check is meaningful for a
            # person only; it must not suppress company or industry evidence.
            if target_type == "person":
                report_eligible = not meta.get("person_discovery_only") and (bool(affiliation_context) or identity_confidence not in {"low", "rejected"})
            elif target_type == "company":
                report_eligible = entity_validation != "rejected" and text_origin != 'discovery_summary'
            else:
                report_eligible = True
            fact_category = (
                "person_affiliation_structured"
                if is_structured_source and affiliation_context
                else source.source_type or "unknown"
            )
            identity_match = ""
            if target_type == "person":
                identity_match = (
                    "confirmed" if identity_confidence == "high"
                    else "probable" if identity_confidence == "medium"
                    else "ambiguous" if identity_confidence == "low"
                    else "mismatch" if identity_confidence == "rejected"
                    else "unknown"
                )
            fact_card = {
                "fact": text[:source_clip_limit] if target_type=='industry' else _clip(text, source_clip_limit),
                "category": fact_category,
                "claim_type": "source_excerpt",
                **({'text_origin': text_origin, 'claim_type': 'discovery_summary' if text_origin == 'discovery_summary' else 'source_excerpt'} if company_mode else {}),
                "source_title": source.title,
                "source_url": source.url,
                "evidence_quote": text[:evidence_limit] if target_type=='industry' else _clip(text, evidence_limit),
                "source_type": source.source_type,
                "is_structured_evidence": is_structured_source,
                "source_entity_validation": entity_validation,
                "confidence": confidence,
                "module": meta.get("module", ""),
                "evidence_scope": meta.get("evidence_scope") or ("industry_level" if target_type == "industry" else ""),
                "industry_name": meta.get("industry_name", ""),
                "segment_name": meta.get("segment_name", ""),
                "company_role": meta.get("company_role", ""),
                "platform": meta.get("platform", ""),
                "provider": meta.get("provider", ""),
                "person_affiliation": affiliation_context,
                "identity_confidence": identity_confidence or "unknown",
                "identity_reason": str(meta.get("identity_reason") or ""),
                "eligible_for_report": report_eligible,
                "attribution_boundary": (
                    "关联企业层面事实，不得归因为目标人物个人事实或个人风险"
                    if affiliation_context else ""
                ),
                "eligible_for_risk_scoring": False if affiliation_context or not report_eligible else None,
                "source_grade": source_grade,
                "quality_score": source.credibility_score,
                "authority_score": quality.get("authority_score"),
                "content_flags": flags,
                "content_chars": len(text),
                "image_urls": image_urls,
                "vision_status": meta.get("vision_status", ""),
                "vision_text": _clip(str(meta.get("vision_text") or ""), 1200),
                "date": "",
                **({"identity_match": identity_match} if target_type == "person" else {}),
                **({"entity_match": "confirmed" if entity_validation in {"verified", "matched_anchor"} else "unknown"} if target_type == "company" else {}),
                **({"scope_match": "in_scope"} if target_type == "industry" else {}),
            }
            if target_type == "person" and not report_eligible:
                identity_quarantine_count += 1
                fact_card["usable_as"] = "identity_quarantine"
                identity_quarantine_facts.append(fact_card)
                continue
            fact_card["usable_as"] = "affiliation_fact" if affiliation_context else "person_or_background_fact"
            facts.append(fact_card)
        gaps = ["规则清洗模式仅保留来源级事实，关键结论建议结合来源引用进行人工复核。"]
        if low_content_count:
            gaps.append(f"低正文来源：{low_content_count} 条，已保留但降权")
        if ocr_pending_count:
            gaps.append(f"OCR 待处理来源：{ocr_pending_count} 条，已保留并标记 needs_ocr")
        if source_errors:
            gaps.append(f"专业平台返回无匹配或参数错误 {source_errors} 条；这属于检索/入参缺口，不作为企业实质风险结论。")
        if identity_quarantine_count:
            gaps.append(f"人物同名或身份锚点不足来源：{identity_quarantine_count} 条，已入库隔离，不进入正文结论。")
        return {
            "facts": facts,
            "identity_quarantine_facts": identity_quarantine_facts,
            "discarded_patterns": ["duplicate source snippets removed", "only fully empty sources removed"],
            "information_gaps": gaps,
        }
    def _source_context(self, sources: list[ResearchSource], max_chars_per_source: int = 5000, industry: bool = False, *, target_type: str = '') -> str:
        blocks = []
        for idx, source in enumerate(sources, 1):
            text = source.content or source.summary
            if target_type == 'company':
                from report_agents.company_evidence import source_body
                text, origin = source_body(source)
                if origin == 'discovery_summary':
                    continue  # Discovery leads cannot become model-extracted facts.
            meta = source.source_metadata or {}
            quality = meta.get("quality") or {}
            is_structured_source = self._is_structured_professional_source(source)
            source_limit = _env_int("CLEANING_STRUCTURED_MAX_CHARS_PER_SOURCE", 8000, 1000, 30000) if is_structured_source else max_chars_per_source
            if industry and not is_structured_source:
                try:
                    from .industry_research import industry_excerpt
                except ImportError:
                    from industry_research import industry_excerpt
                text = industry_excerpt(text, str(meta.get('module') or ''), source_limit)
            if industry:
                blocks.append(f'标题：{source.title}\nURL：{source.url}\n模块：{meta.get("module", "")}\n'
                              f'行业证据层级：{meta.get("evidence_scope", "industry_level")}\n'
                              f'内容：{_clip(text, source_limit)}')
                continue
            blocks.append(
                f"[{idx}] {source.title}\n"
                f"类型：{source.source_type}\n"
                f"URL：{source.url}\n"
                f"可信度：{source.credibility_score}\n"
                f"模块：{meta.get('module', '')}\n"
                f"行业证据层级：{meta.get('evidence_scope', '')}\n"
                f"行业名称：{meta.get('industry_name', '')}\n"
                f"细分赛道：{meta.get('segment_name', '')}\n"
                f"公司角色：{meta.get('company_role', '')}\n"
                f"身份置信度：{meta.get('identity_confidence', '')}\n"
                f"身份判断理由：{meta.get('identity_reason', '')}\n"
                f"身份锚点：{meta.get('identity_anchors', [])}\n"
                f"人物关联企业上下文：{json.dumps(meta.get('person_affiliation', {}), ensure_ascii=False)}\n"
                f"质量评分：{quality}\n"
                f"鍥剧墖/鍥捐〃鍏冩暟鎹細{_clip(json.dumps(meta.get('images', []), ensure_ascii=False), 1200)}\n"
                f"内容：{_clip(text, source_limit)}"
            )
        return "\n\n---\n\n".join(blocks)

    def _source_context_batches(
        self,
        sources: list[ResearchSource],
        max_chars: int = 18000,
        max_chars_per_source: int = 5000,
        max_batches: int | None = None,
        target_type: str = '',
        industry: bool = False,
    ) -> list[str]:
        batches: list[str] = []
        current: list[str] = []
        current_len = 0
        for source in sources:
            block = self._source_context([source], max_chars_per_source=max_chars_per_source, target_type=target_type, industry=industry)
            if not block:
                continue
            if current and current_len + len(block) > max_chars:
                batches.append("\n\n---\n\n".join(current))
                if max_batches and len(batches) >= max_batches:
                    break
                current = []
                current_len = 0
            current.append(block)
            current_len += len(block)
        if current and (not max_batches or len(batches) < max_batches):
            batches.append("\n\n---\n\n".join(current))
        return batches or [""]

    def _dedupe_facts(self, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            text = str(fact.get("fact") or "").strip()
            if not text:
                continue
            key = re.sub(r"\s+", "", text.lower())[:160]
            source_url = str(fact.get("source_url") or "")
            key = f"{key}|{source_url}"
            if fact.get('cleaning_method') == 'industry_rule':
                key += '|industry_rule|' + json.dumps(fact.get('numeric_context') or {}, sort_keys=True, ensure_ascii=False)
            elif fact.get('cleaning_method') == 'llm' and fact.get('numeric_context'):
                key += '|llm_numeric|' + json.dumps(fact['numeric_context'], sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            fact["confidence"] = self._bounded_float(fact.get("confidence"), default=0.6)
            deduped.append(fact)
        return deduped

    def _normalize_cleaning_text_items(self, value: Any) -> list[str]:
        """Convert malformed model list items into stable, hashable text.

        Cleaning models occasionally return objects for ``information_gaps`` or
        ``discarded_patterns`` despite the JSON schema requesting strings.  A
        raw ``set(items)`` then raises ``TypeError: unhashable type: 'dict'`` and
        used to discard the complete cleaning run.  This boundary accepts the
        imperfect response without promoting it to a workflow-wide failure.
        """
        rows: list[str] = []

        def append_item(item: Any) -> None:
            if item is None:
                return
            if isinstance(item, str):
                text = item.strip()
                if text:
                    rows.append(text)
                return
            if isinstance(item, dict):
                # Prefer a human-readable reason where the model supplied one;
                # otherwise retain a deterministic JSON audit record.
                for key in ("message", "reason", "detail", "gap", "pattern", "description", "error"):
                    candidate = item.get(key)
                    if isinstance(candidate, str) and candidate.strip():
                        rows.append(candidate.strip())
                        return
                rows.append(json.dumps(item, ensure_ascii=False, sort_keys=True, default=str))
                return
            if isinstance(item, (list, tuple, set)):
                for nested in item:
                    append_item(nested)
                return
            rows.append(str(item).strip())

        append_item(value)
        return sorted({item for item in rows if item})

    def _normalize_cleaning_payload(self, payload: Any) -> dict[str, list[Any]]:
        """Normalize one LLM batch response before it reaches aggregation."""
        if not isinstance(payload, dict):
            return {"facts": [], "discarded_patterns": [], "information_gaps": []}
        raw_facts = payload.get("facts")
        if isinstance(raw_facts, dict):
            raw_facts = [raw_facts]
        facts = [item for item in raw_facts if isinstance(item, dict)] if isinstance(raw_facts, list) else []
        return {
            "facts": facts,
            "discarded_patterns": self._normalize_cleaning_text_items(payload.get("discarded_patterns", [])),
            "information_gaps": self._normalize_cleaning_text_items(payload.get("information_gaps", [])),
        }

    def _bounded_float(self, value: Any, default: float = 0.5) -> float:
        try:
            number = float(value)
        except Exception:
            number = default
        return max(0.0, min(1.0, number))

    def _fallback_clean_batch(self, sources: list[ResearchSource], batch_index: int) -> dict[str, Any]:
        facts = []
        start = (batch_index - 1) * 8
        for source in sources[start:start + 8]:
            text = (source.summary or source.content or "").strip()
            if not text:
                continue
            meta = source.source_metadata or {}
            if self._is_failed_extraction_source(source):
                source_errors += 1
                continue
            facts.append(
                {
                    "fact": text[:700],
                    "category": source.source_type,
                    "claim_type": "fact",
                    "source_title": source.title,
                    "source_url": source.url,
                    "evidence_quote": text[:240],
                    "confidence": min(0.95, max(0.3, source.credibility_score / 100)),
                    "module": meta.get("module", ""),
                    "date": "",
                    "cleaning_method": "fallback",
                    "requires_human_review": True,
                }
            )
        return {
            "facts": facts,
            "information_gaps": ["部分资料使用规则降级清洗，建议人工复核关键结论。"],
        }

    def _is_failed_extraction_source(self, source: ResearchSource) -> bool:
        meta = source.source_metadata or {}
        text = str(source.content or source.summary or "").lstrip()
        return str(meta.get("extraction_status") or "").lower() in {"failed", "pending"} or text.startswith(("[解析失败", "[待解析"))

    def _fallback_clean(self, project: ResearchProject) -> dict[str, Any]:
        if str(project.target_type or '').lower() == 'company':
            return self._fast_clean_sources(project.sources, project=project)
        if project.target_type == "industry":
            sources = self._select_cleaning_sources(self._active_industry_sources(project), project=project)
            payload = self._fast_clean_sources(sources, project=project)
            payload["facts"] = self._annotate_evidence_facts(project, payload.get("facts", []))
            payload["industry_scope"] = getattr(project, "industry_scope", {})
            return payload
        facts = []
        seen = set()
        for source in self._active_industry_sources(project):
            if self._is_failed_extraction_source(source):
                continue
            text = (source.summary or source.content or "").strip()
            if not text:
                continue
            normalized = re.sub(r"\s+", "", text[:200])
            if normalized in seen:
                continue
            seen.add(normalized)
            facts.append(
                {
                    "fact": text[:500],
                    "category": source.source_type,
                    "source_title": source.title,
                    "source_url": source.url,
                    "confidence": min(0.95, max(0.3, source.credibility_score / 100)),
                }
            )
        return {
            "facts": facts,
            "discarded_patterns": ["duplicate URL", "empty content"],
            "information_gaps": ["需要补充监管、诉讼、财务、舆情等权威来源交叉验证。"],
        }

    def _fallback_risk(self, cleaned_json: str) -> dict[str, Any]:
        dimensions = []
        for name in ["法律合规风险", "财务稳定性风险", "舆情声誉风险", "商业信用风险", "关联关系风险", "行业周期风险"]:
            dimensions.append(
                {
                    "name": name,
                    "score": None,
                    "level": "unknown",
                    "reason": "风险模型未返回可审计结果；证据缺口不构成高风险或低风险结论。",
                    "evidence_sources": [],
                }
            )
        return {
            "overall_score": None,
            "risk_level": "unknown",
            "dimensions": dimensions,
            "key_risks": [],
            "unknowns": ["风险模型调用失败，所有维度暂按 unknown 处理。"],
            "recommended_followups": ["补充监管、司法、工商、新闻和行业报告来源。"],
        }

    def _normalize_report_date(self, report: str) -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        result = re.sub(r"(?m)^(报告日期|编制日期|编制时间)\s*[：:]\s*[^\n]+$", rf"\1：{today}", report or "")
        return result

    def _fallback_report(self, project: ResearchProject, cleaned_json: str, risk_json: str) -> str:
        try:
            cleaned = json.loads(cleaned_json)
        except Exception:
            cleaned = {}
        try:
            risk = json.loads(risk_json)
        except Exception:
            risk = {}
        facts = []
        raw_facts = cleaned.get("facts", []) if isinstance(cleaned, dict) else []
        if str(project.target_type or "").lower() == "company":
            # A model/template fallback must be at least as strict as the
            # normal report path.  Never let its first-N facts resurrect a
            # broad-search result that company evidence isolation rejected.
            raw_facts = [
                item for item in raw_facts
                if isinstance(item, dict)
                and str(item.get("evidence_scope") or classify_company_fact_scope(item, str(project.target_name or ""))) == "target_direct"
                and item.get("eligible_for_report") is not False
            ]
        for item in raw_facts[:20]:
            if not isinstance(item, dict):
                continue
            fact = self._clean_source_text(item.get("fact") or "")
            if not fact or fact.startswith(("[解析失败", "[待解析")) or "base64," in fact:
                continue
            facts.append(f"- {fact[:500]}（来源：{item.get('source_title') or '待核验'}）")
        dimensions = []
        for item in risk.get("dimensions", []) if isinstance(risk, dict) else []:
            if isinstance(item, dict):
                dimensions.append(f"- {item.get('name', '风险项')}：{item.get('level', 'unknown')}。{str(item.get('reason') or '')[:300]}")
        fact_text = "\n".join(facts) or "- 当前没有可可靠提取的事实；解析失败的上传资料未作为事实使用。"
        risk_text = "\n".join(dimensions) or "- 当前证据不足以形成可靠风险评级，相关事项列为待核验，不以缺失本身推定高风险。"
        return f"""# {project.title}：桌面研究报告

## 一、执行摘要
本报告基于已入库资料、在线检索资料和清洗后的事实库生成。当前版本为降级生成稿，适合用于内部研判和后续人工复核。

## 二、研究对象概况
- 研究对象：{project.target_name or "未指定"}
- 对象类型：{project.target_type or "未指定"}
- 行业：{project.industry or "未指定"}
- 项目背景：{project.description or "未填写"}

## 三、核心事实梳理
{fact_text}

## 四、风险识别与研判
{risk_text}

## 五、待核验事项
- 补充权威网页、监管、司法、工商、财务和舆情数据源。
- 关键结论在正式交付前需要人工复核。

## 六、初步结论
当前资料可支持形成初步判断，但不宜直接作为最终尽调结论。建议进入人工复核和重点问题深化阶段。
"""

    def generate_proposal(
        self,
        project: ResearchProject,
        report: str,
        risk_json: str,
        emit: TraceEmitter | None = None,
    ) -> str:
        if str(project.target_type or "").lower() == "industry":
            try:
                from .report_agents.industry_proposal import build_industry_proposal
            except ImportError:
                from report_agents.industry_proposal import build_industry_proposal
            _emit(emit, "proposal", "proposal_agent", "行业建议书按研究范围和七章模板生成", "人员、周期和报价保留确认项", status="done")
            return build_industry_proposal(project)
        if (
            str(project.target_type or "").lower() == "company"
            and os.getenv("COMPANY_PROPOSAL_LLM_ENABLED", "false").strip().lower() not in {"1", "true", "yes", "on"}
        ):
            _emit(
                emit,
                "proposal",
                "proposal_agent",
                "公司项目建议书使用确定性模板生成",
                "避免全文报告输入导致的模型超时；可通过 COMPANY_PROPOSAL_LLM_ENABLED=true 启用模型润色",
                status="done",
            )
            return self._fallback_company_proposal(project)
        prompt = f"""
请扮演咨询项目建议书总监。基于下方桌面研究报告和风险研判，生成可直接给客户沟通的项目建议书。

硬性要求：
1. 使用中文 Markdown，结构清晰，可直接转 Word。
2. 不要复述整份报告，要把报告发现转化为项目方案、研究范围、方法、交付物和推进计划。
3. 不得编造已经完成的访谈、付费数据库核验、客户/供应商确认或财务数据。
4. 对证据不足事项写成“待客户补充/待访谈/待付费数据库核验”，并说明为什么需要核验。
5. 必须包含以下 7 节：
   1）项目基本情况
   2）项目调研分析
   3）项目调研框架与主要研究范围
   4）项目调研方法与渠道资源
   5）项目工作方法与周期安排
   6）项目团队安排
   7）项目报价与保密条款
6. 尽量用表格承载研究范围、方法渠道、工作计划、团队角色、交付物、报价条款和风险优先级。

项目信息：
- 项目：{project.title}
- 研究对象：{project.target_name}
- 对象类型：{project.target_type}
- 行业：{project.industry}
- 项目背景：{project.description}

风险研判：
{_clip(risk_json, 8000)}

桌面研究报告：
{_clip(report, 24000)}
"""
        answer = self._invoke("项目建议书总监 Agent", prompt, emit=emit)
        if answer.strip():
            return answer.strip()
        return self._fallback_proposal(project, report)

    def _normalize_proposal_placeholders(self, proposal: str) -> str:
        """Replace common model placeholders with explicit, honest pending values."""
        text = str(proposal or "")
        replacements = {
            "[客户名称]": "待客户确认",
            "[咨询公司名称]": "项目服务团队",
            "[您的姓名/签名]": "待指定",
            "[电话/邮箱]": "待补充",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        text = re.sub(r"202X年X月X日", datetime.now().strftime("%Y年%m月%d日"), text)
        text = re.sub(r"[¥￥]X{2,}(?:,X{3})?", "待双方确认", text)
        text = re.sub(r"[¥￥]XXX,XXX", "待双方确认", text, flags=re.I)
        return text

    def _proposal_quality_warning(self, proposal: str, target_type: str = "") -> str:
        """Return a concise reason when a generated proposal is not deliverable."""
        text = str(proposal or "").strip()
        issues: list[str] = []
        missing = [
            index
            for index in range(1, 8)
            if not re.search(rf"(?m)^#{{1,4}}\s*{index}\s*[.、．）)]", text)
        ]
        if missing:
            issues.append(f"缺少章节：{missing}")
        if len(re.sub(r"\s+", "", text)) < (1200 if target_type == "industry" else 1800):
            issues.append("正文过薄")
        placeholder_patterns = [
            r"\[(?:客户名称|咨询公司名称|您的姓名/签名|电话/邮箱)[^\]]*\]",
            r"202X年",
            r"[¥￥]X{2,}",
            r"XXX,?XXX",
        ]
        if any(re.search(pattern, text, flags=re.I) for pattern in placeholder_patterns):
            issues.append("仍含未替换占位符")
        return "；".join(issues)

    def _fallback_proposal(self, project: ResearchProject, report: str) -> str:
        if str(project.target_type or "").lower() == "industry":
            try:
                from .report_agents.industry_proposal import build_industry_proposal
            except ImportError:
                from report_agents.industry_proposal import build_industry_proposal
            return build_industry_proposal(project)
        if str(project.target_type or "").lower() == "company":
            return self._fallback_company_proposal(project)
        subject = project.target_name or project.industry or project.title
        return f"""# {project.title}：背景调查项目建议书

> 本建议书依据现有桌面研究形成，用于明确后续正式尽调的范围、方法、周期与交付边界。桌面研究中的待核验事项不作为既定事实。

## 1. 项目基本情况

| 项目要素 | 内容 |
| --- | --- |
| 项目名称 | {project.title} |
| 研究对象 | {subject} |
| 对象类型 | {project.target_type or '待确认'} |
| 所属行业 | {project.industry or '待客户确认'} |
| 项目背景 | {project.description or '客户拟对研究对象开展背景调查，具体交易背景、决策用途和授权边界待启动会确认。'} |

项目目标是以可追溯证据核查研究对象的履历、商业关系、合规记录、信用与声誉风险，区分“已验证事实”“合理研判”和“待核验事项”，为客户的合作、投资或治理决策提供依据。

## 2. 项目调研分析

现有桌面研究已经形成初步事实库和风险假设，但公开资料存在时间滞后、口径差异及非公开关系难以验证等限制。正式项目不直接复述自动生成报告，而是对高影响事项执行来源回溯、交叉验证和反证检索。

当前优先核验方向包括：研究对象身份与关键履历、核心关联企业与控制关系、重大监管及司法事项、商业信用与舆情争议、个人财务及授权信息，以及上述事项对客户拟议交易的实际影响。任何缺少直接证据的判断均列入待核验清单。

## 3. 项目调研框架与主要研究范围

| 研究模块 | 主要工作 | 判定标准 |
| --- | --- | --- |
| 身份与履历核验 | 核对教育、任职、创业及重大职业节点 | 至少两类独立来源相互印证 |
| 关联关系穿透 | 梳理直接关联企业、股权、任职、控制与重大交易关系 | 区分直接证据、间接关联和待确认关系 |
| 法律合规 | 检索监管、行政处罚、诉讼、执行及公开纪律记录 | 以官方或司法来源为主，记录主体匹配依据 |
| 商业信用与声誉 | 复核重大争议、履约记录及权威媒体报道 | 同时检索支持证据与反证，避免单一舆情定性 |
| 财务与资产风险 | 在合法授权范围内核验债务、担保、冻结及资产集中度 | 无授权信息明确标注不可核验 |
| 团队与治理 | 识别关键管理团队、继任、授权和利益冲突风险 | 结合公开资料与经客户批准的访谈证据 |

## 4. 项目调研方法与渠道资源

| 方法 | 渠道 | 适用事项 | 合规边界 |
| --- | --- | --- | --- |
| 案头研究 | 政府、监管、司法、企业公告及权威媒体 | 履历、监管、诉讼、重大事件 | 保存原始链接、日期和证据摘录 |
| 结构化数据库核验 | 工商、司法、金融及知识产权专业平台 | 股权穿透、任职、涉诉、资产线索 | 仅使用客户已采购或合法授权账户 |
| 专家与利益相关方访谈 | 经客户批准的行业专家、前员工或合作方 | 治理、口碑、非公开业务背景 | 事先确认身份、利益冲突和记录方式 |
| 交叉验证与反证检索 | 多来源比对、时间线和主体消歧 | 争议事实和高风险假设 | 不以匿名传闻或单一自媒体作为结论 |

## 5. 项目工作方法与周期安排

| 阶段 | 工作内容 | 交付物 | 建议周期 |
| --- | --- | --- | --- |
| 启动与范围确认 | 明确决策问题、研究边界、授权和重点主体 | 启动备忘录、资料需求清单 | 第1周 |
| 深化检索与核验 | 补充权威来源、专业数据库核验、建立证据台账 | 事实库、来源清单、问题清单 | 第1-2周 |
| 访谈与专项核查 | 对高影响缺口开展访谈或专项核验 | 访谈纪要、专项核验底稿 | 第2-3周 |
| 综合研判与质检 | 执行交叉验证、风险分级和内部质量复核 | 报告初稿、质量复核记录 | 第4周 |
| 交付与沟通 | 提交报告、汇报关键结论并吸收客户反馈 | 正式报告、汇报材料、底稿目录 | 第5周 |

## 6. 项目团队安排

| 角色 | 主要职责 |
| --- | --- |
| 项目总监 | 把控范围、重大判断、质量与客户沟通 |
| 项目经理 | 统筹计划、证据台账、任务分配与版本管理 |
| 法律合规顾问 | 审核司法、监管、数据合规及结论措辞 |
| 行业研究员 | 开展行业、商业模式、竞争与关键人物研究 |
| 数据分析员 | 负责主体消歧、关系穿透、来源归档和一致性检查 |

具体人员名单、投入强度及是否配置境外顾问，待客户确认研究范围后确定。

## 7. 项目报价与保密条款

报价采用“固定专业服务费 + 经客户预批准的实报实销费用”结构。专业服务费、税率、专家访谈费用上限、差旅及付费数据库成本均在范围确认后形成书面报价；在客户书面确认前不发生额外费用。

双方应在项目启动前签署保密协议。项目资料仅限授权团队使用，个人信息和敏感数据按照适用法律及最小必要原则处理。未经客户书面同意，不向第三方披露项目身份、材料或结论。最终报告将明确来源、证据限制、使用范围及人工复核状态。

### 当前桌面研究摘要（仅作范围设计参考）

{_clip(report, 3000)}
"""

    def _fallback_company_proposal(self, project: ResearchProject) -> str:
        """A company-only proposal fallback; never append raw report Markdown."""
        subject = project.target_name or project.title or "目标公司"
        return f"""# {project.title}：背景调查项目建议书

> 本建议书依据现有桌面研究形成，用于明确后续企业尽调的范围、方法、周期与交付边界。桌面研究中的待核验事项不作为既定事实。

## 1. 项目基本情况

| 项目要素 | 内容 |
| --- | --- |
| 项目名称 | {project.title} |
| 调研对象 | {subject} |
| 对象类型 | 目标公司 |
| 所属行业 | {project.industry or '待客户确认'} |
| 项目背景 | {getattr(project, 'description', '') or '客户拟对目标公司开展商业尽调，交易背景、决策用途和授权边界待启动会确认。'} |

本项目旨在以可追溯证据核验目标公司的主体资格、股权治理、融资与资金使用、团队能力、产品技术、商业化进展及合规风险，为投资、合作或交易决策提供事实基础。

## 2. 项目调研分析

现有桌面研究已形成初步事实库和风险假设，但公开资料无法充分验证协议安排、资金流水、客户合同、研发真实性及内部治理。正式尽调将对高影响事项执行主体消歧、多源交叉验证和反证检索；缺少直接证据的事项均列为待核验，不作确定性结论。

项目将优先处理可能改变交易判断的事项：主体是否一致、控制权与股权安排是否清晰、融资是否实际交割、核心技术是否具备合法权属、产品是否存在真实的客户验证，以及是否存在重大司法或监管风险。每项判断均按照“原始材料—独立来源—访谈或走访”逐层验证；如不同来源存在冲突，将保留冲突记录并说明需要补充的证明材料，而不以推测替代事实。

研究过程中将建立可追溯证据台账，记录信息来源、获取日期、支持事项、证据强度和复核状态。项目组仅将已核验材料用于确定性结论；媒体报道、行业观点和单一渠道信息仅作为线索或风险信号使用。客户可在阶段沟通中确认优先级、追加专项范围或终止低价值核验工作。

## 3. 项目调研框架与主要研究范围

| 研究模块 | 主要工作 | 核验重点 |
| --- | --- | --- |
| 主体与股权治理 | 核验工商档案、股东名册、出资、控制关系及关联方 | 实控权、代持、异常变更、关联交易 |
| 融资与资本事项 | 复核融资公告、投资协议、资金到账和用途 | 估值、优先权、资金到位、用途合规 |
| 团队与组织 | 核验核心团队履历、任职、激励和人员稳定性 | 技术来源、关键人依赖、组织能力 |
| 产品技术与知识产权 | 核验产品状态、研发进度、专利/软著及技术归属 | 技术可行性、权属瑕疵、交付进度 |
| 经营与商业化 | 抽样核验客户、合同、订单、回款及供应链 | 收入真实性、客户集中度、持续经营 |
| 合规与风险 | 检索司法、监管、行政处罚、舆情及数据合规事项 | 重大纠纷、监管风险、声誉风险 |

## 4. 项目调研方法与渠道资源

| 方法 | 渠道 | 适用事项 | 合规边界 |
| --- | --- | --- | --- |
| 案头研究 | 政府、监管、司法、企业披露与权威媒体 | 主体、融资、监管、重大事件 | 保存原始链接、日期和证据摘录 |
| 结构化数据库核验 | 工商、司法、融资、知识产权等合法授权平台 | 股权穿透、任职、涉诉、融资线索 | 仅使用客户已采购或合法授权账户 |
| 文件核验 | 工商档案、协议、合同、财务及研发资料 | 交易条款、资金、客户、技术真实性 | 按最小必要原则使用和留存 |
| 访谈与走访 | 经客户批准的管理层、员工、客户、供应商及专家 | 治理、经营、产品和声誉交叉验证 | 事先确认授权、利益冲突和纪要方式 |

## 5. 项目工作方法与周期安排

| 阶段 | 工作内容 | 交付物 | 建议周期 |
| --- | --- | --- | --- |
| 启动与范围确认 | 明确交易背景、重点主体、授权和资料清单 | 启动备忘录、资料清单 | 第1周 |
| 深化检索与资料核验 | 建立事实台账，核验工商、融资、司法与技术资料 | 核验底稿、问题清单 | 第1-2周 |
| 访谈与专项穿透 | 围绕高影响缺口开展访谈、走访和专项核查 | 访谈纪要、专项核验底稿 | 第2-3周 |
| 综合研判与质检 | 执行交叉验证、风险分级和内部质量复核 | 报告初稿、复核记录 | 第4周 |
| 交付与沟通 | 汇报核心发现、风险边界和后续动作 | 正式报告、证据台账、汇报材料 | 第5周 |

## 6. 项目团队安排

| 角色 | 主要职责 |
| --- | --- |
| 项目总监 | 把控范围、重大判断、质量与客户沟通 |
| 项目经理 | 统筹计划、资料清单、证据台账与版本管理 |
| 公司研究员 | 开展工商、融资、团队、经营与竞争研究 |
| 法律合规顾问 | 审核司法、监管、合同及数据合规事项 |
| 数据分析员 | 负责主体消歧、关系图谱、来源归档与一致性检查 |

具体人员名单、投入强度及是否配置技术或行业专家，待客户确认研究范围后确定。

项目总监负责独立质量复核，重点检查主体混淆、来源可追溯性、事实与判断的边界以及重大风险是否被充分披露。对涉及个人信息、商业秘密和敏感交易信息的材料，项目组将设置访问权限、使用登记和交付留痕；未经客户书面授权，不将非公开材料用于本项目之外的任何用途。

## 7. 项目报价与保密条款

报价采用“固定专业服务费 + 经客户预批准的实报实销费用”结构。付费数据库、专家访谈、现场走访及差旅费用须经客户书面确认后发生。专业服务费、税率、交付节奏和资料授权边界将在启动会后形成书面报价与项目约定。

双方应在项目启动前签署保密协议。项目资料仅限授权团队使用，按最小必要原则处理；最终交付将区分已验证事实、分析判断与待核验事项，并附可回溯的证据台账。
"""


research_workflow = ResearchWorkflow()
