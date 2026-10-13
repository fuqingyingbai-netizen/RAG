"""Diagnose the real research workflow's web collection and cleaning steps.

This script intentionally reuses production methods instead of simulating rules:
collect_web_sources() -> evaluate_source_quality() -> clean_sources().
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:
        return False

ROOT_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = ROOT_DIR.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

load_dotenv(ROOT_DIR / ".env")

DEFAULT_MODULES = [
    "公司背景",
    "融资情报",
    "股东高管",
    "诉讼/制裁",
    "负面新闻",
    "行业市场",
]


def split_csv(value: str | None, default: list[str] | None = None) -> list[str]:
    if not value:
        return list(default or [])
    return [item.strip() for item in re.split(r"[,，\n]", value) if item.strip()]


def now_key() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return str(value)


def parse_cleaned(cleaned_json: str) -> dict[str, Any]:
    try:
        parsed = json.loads(cleaned_json)
        return parsed if isinstance(parsed, dict) else {"raw": parsed}
    except Exception as exc:
        return {"parse_error": str(exc), "raw_text": cleaned_json[:5000]}


def host_of(url: str) -> str:
    return urlparse(url or "").netloc.lower().replace("www.", "")


def ensure_diagnostic_user(db) -> User:
    user = db.query(User).filter(User.username == "diagnostic_runner").first()
    if user:
        return user
    user = User(
        username="diagnostic_runner",
        password_hash="diagnostic-only",
        role="admin",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_markdown(report: dict[str, Any]) -> str:
    quality = report["quality"]
    cleaning = report["cleaning"]
    collection = report["collection"]
    lines = [
        f"# 真实前两步诊断：{report['project']['target_name']}",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 项目ID：{report['project']['id']}",
        f"- 行业：{report['project']['industry']}",
        f"- 搜索 Provider：{', '.join(collection['configured_providers']) or 'none'}",
        f"- 新增来源：{collection['sources_added']}",
        f"- 来源总数：{quality['source_count']}",
        f"- 平均质量分：{quality['average_score']}",
        f"- 清洗事实数：{cleaning['fact_count']}",
        f"- 信息缺口数：{len(cleaning['information_gaps'])}",
        "",
        "## 模块覆盖",
        "",
        "| 模块 | 来源数 | 权威来源数 | 进入清洗数 | 清洗事实数 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in report["module_summary"]:
        lines.append(
            f"| {row['module']} | {row['source_count']} | {row['authoritative_count']} | "
            f"{row['selected_for_cleaning_count']} | {row['cleaned_fact_count']} |"
        )

    lines.extend(["", "## 进入清洗的来源", ""])
    for source in report["selected_sources"][:80]:
        lines.append(
            f"- [{source['score']}] [{source['module'] or 'unassigned'}] "
            f"{source['title']} - {source['url']}"
        )

    lines.extend(["", "## 信息缺口", ""])
    gaps = cleaning["information_gaps"] or quality.get("information_gaps", [])
    if gaps:
        lines.extend(f"- {gap}" for gap in gaps)
    else:
        lines.append("- 暂无")

    lines.extend(["", "## 清洗事实样例", ""])
    for fact in cleaning["facts_sample"]:
        lines.append(
            f"- [{fact.get('module') or 'unassigned'}] {fact.get('fact', '')[:260]} "
            f"({fact.get('source_title', '')})"
        )

    lines.extend(["", "## Top 来源域名", ""])
    for host, count in report["host_counts"]:
        lines.append(f"- {host or 'no-host'}: {count}")

    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> tuple[Path, Path]:
    if args.provider and args.provider != "multi":
        os.environ["WEB_SEARCH_PROVIDER"] = args.provider
    elif args.provider == "multi":
        os.environ.pop("WEB_SEARCH_PROVIDER", None)
    if not args.llm_cleaning:
        os.environ["CLEANING_LLM_ENABLED"] = "false"

    output_dir = Path(args.output_dir) if args.output_dir else ROOT_DIR / "diagnostics" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url
    elif not args.use_project_db:
        sqlite_path = output_dir / "diagnostics.sqlite3"
        os.environ["DATABASE_URL"] = f"sqlite:///{sqlite_path.as_posix()}"

    if args.verbose:
        print(f"[init] database={os.environ.get('DATABASE_URL', '')}", flush=True)

    from RAG.backend.database import Base, SessionLocal, engine
    from RAG.backend.models import ResearchProject, User
    from RAG.backend.research_workflow import FIXED_MAX_RESULTS_PER_QUERY, ResearchWorkflow
    globals()["User"] = User

    if args.verbose:
        print("[init] creating/checking tables", flush=True)
    Base.metadata.create_all(bind=engine)
    if args.verbose:
        print("[init] tables ready", flush=True)
    workflow = ResearchWorkflow()
    db = SessionLocal()
    project = None
    try:
        user = ensure_diagnostic_user(db)
        project = ResearchProject(
            title=f"诊断项目 - {args.target}",
            target_name=args.target,
            target_type=args.target_type,
            industry=args.industry,
            description=args.description,
            status="diagnostic",
            created_by_id=user.id,
        )
        db.add(project)
        db.commit()
        db.refresh(project)

        search_queries = split_csv(args.search_query)
        focus_questions = split_csv(args.focus_question)
        intake = {
            "target_name": args.target,
            "company_name": args.target if args.target_type == "company" else "",
            "target_type": args.target_type,
            "industry": args.industry,
            "research_type": args.research_type,
            "focus_modules": split_csv(args.modules, DEFAULT_MODULES),
            "special_requirements": args.description,
            "max_search_rounds": args.max_rounds,
            "ai_search_enabled": True,
        }
        normalized = workflow._normalize_intake(project, intake, search_queries, focus_questions)
        normalized["max_search_rounds"] = args.max_rounds
        plan = workflow.plan_research(project, normalized)

        trace_events: list[dict[str, Any]] = []

        def emit(event: dict[str, Any]) -> None:
            trace_events.append({key: json_safe(value) for key, value in event.items()})
            if args.verbose:
                stage = event.get("stage") or event.get("type") or ""
                agent = event.get("agent") or ""
                message = event.get("message") or event.get("title") or ""
                detail = event.get("detail") or ""
                status = event.get("status") or ""
                print(f"[{status}] {stage}/{agent} {message} {detail}".strip(), flush=True)

        max_results = args.max_results or FIXED_MAX_RESULTS_PER_QUERY
        sources_added = workflow.collect_web_sources(
            db,
            project,
            search_queries=search_queries,
            focus_questions=focus_questions,
            max_results_per_query=max_results,
            emit=emit,
            plan=plan,
            intake=normalized,
        )
        db.refresh(project)
        quality = workflow.evaluate_source_quality(project, plan)
        selected_sources = workflow._select_cleaning_sources(project.sources, max_sources=args.max_cleaning_sources)
        cleaned_json = workflow.clean_sources(project, emit=emit, plan=plan, quality=quality)
        cleaned = parse_cleaned(cleaned_json)
        facts = cleaned.get("facts") if isinstance(cleaned.get("facts"), list) else []

        source_by_module: dict[str, list[Any]] = defaultdict(list)
        selected_by_module: Counter[str] = Counter()
        fact_by_module: Counter[str] = Counter()
        authoritative_by_module: Counter[str] = Counter()
        hosts: Counter[str] = Counter()
        platforms: Counter[str] = Counter()
        providers: Counter[str] = Counter()

        for source in project.sources:
            meta = source.source_metadata or {}
            quality_meta = meta.get("quality") or {}
            module = meta.get("module") or "unassigned"
            source_by_module[module].append(source)
            hosts[host_of(source.url)] += 1
            platforms[meta.get("platform") or "unknown"] += 1
            providers[meta.get("provider") or "unknown"] += 1
            if int(quality_meta.get("authority_score") or source.credibility_score or 0) >= 80:
                authoritative_by_module[module] += 1

        for source in selected_sources:
            meta = source.source_metadata or {}
            selected_by_module[meta.get("module") or "unassigned"] += 1

        for fact in facts:
            if isinstance(fact, dict):
                fact_by_module[str(fact.get("module") or "unassigned")] += 1

        modules = [item.get("name", "unassigned") for item in plan.get("modules", [])]
        for module in source_by_module:
            if module not in modules:
                modules.append(module)

        module_summary = [
            {
                "module": module,
                "source_count": len(source_by_module.get(module, [])),
                "authoritative_count": authoritative_by_module.get(module, 0),
                "selected_for_cleaning_count": selected_by_module.get(module, 0),
                "cleaned_fact_count": fact_by_module.get(module, 0),
            }
            for module in modules
        ]

        selected_rows = []
        for source in selected_sources:
            meta = source.source_metadata or {}
            quality_meta = meta.get("quality") or {}
            selected_rows.append(
                {
                    "id": source.id,
                    "title": source.title,
                    "url": source.url,
                    "host": host_of(source.url),
                    "module": meta.get("module", ""),
                    "platform": meta.get("platform", ""),
                    "provider": meta.get("provider", ""),
                    "source_type": source.source_type,
                    "score": source.credibility_score,
                    "authority_score": quality_meta.get("authority_score"),
                    "content_chars": len(source.content or source.summary or ""),
                }
            )

        configured_providers = [
            name
            for name in ["tavily", "serper", "exa"]
            if os.getenv(f"{name.upper()}_API_KEY")
        ]
        active_provider = os.getenv("WEB_SEARCH_PROVIDER", "").strip().lower()
        if active_provider:
            configured_providers = [active_provider]

        report = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "project": {
                "id": project.id,
                "title": project.title,
                "target_name": project.target_name,
                "target_type": project.target_type,
                "industry": project.industry,
            },
            "collection": {
                "sources_added": sources_added,
                "max_results_per_query": max_results,
                "max_search_rounds": normalized.get("max_search_rounds"),
                "configured_providers": configured_providers,
                "provider_counts": providers.most_common(),
                "platform_counts": platforms.most_common(),
            },
            "plan": plan,
            "quality": quality,
            "module_summary": module_summary,
            "selected_sources": selected_rows,
            "cleaning": {
                "mode": (cleaned.get("coverage_summary") or {}).get("cleaning_mode"),
                "llm_enabled": (cleaned.get("coverage_summary") or {}).get("llm_enabled"),
                "fact_count": len(facts),
                "discarded_patterns": cleaned.get("discarded_patterns", []),
                "information_gaps": cleaned.get("information_gaps", []),
                "facts_sample": facts[: args.fact_sample],
            },
            "host_counts": hosts.most_common(30),
            "trace_events": trace_events,
        }

        safe_target = re.sub(r'[\\/:*?"<>|\s]+', "_", args.target).strip("_") or "target"
        base_name = f"first_steps_{safe_target}_{now_key()}"
        json_path = output_dir / f"{base_name}.json"
        md_path = output_dir / f"{base_name}.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(make_markdown(report), encoding="utf-8")
        return json_path, md_path
    finally:
        if project is not None and not args.keep_project:
            try:
                db.delete(project)
                db.commit()
            except Exception:
                db.rollback()
        db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Diagnose real collect/evaluate/clean workflow steps.")
    parser.add_argument("--target", default="乐奇Rokid", help="Target company/person/industry name.")
    parser.add_argument("--target-type", default="company", choices=["company", "person", "industry"])
    parser.add_argument("--industry", default="AI智能眼镜", help="Industry or sector.")
    parser.add_argument("--research-type", default="商业尽调", help="Research type.")
    parser.add_argument("--description", default="真实前两步诊断：检索覆盖与清洗抽取质量。")
    parser.add_argument("--modules", default=",".join(DEFAULT_MODULES), help="Comma-separated research modules.")
    parser.add_argument("--search-query", action="append", default=[], help="Extra search query. Can be repeated.")
    parser.add_argument("--focus-question", action="append", default=[], help="Extra focus question. Can be repeated.")
    parser.add_argument("--max-results", type=int, default=10, help="Results per query for this diagnostic.")
    parser.add_argument("--max-rounds", type=int, default=1, help="Search rounds for this diagnostic.")
    parser.add_argument("--provider", default="", choices=["", "multi", "tavily", "serper", "exa"], help="Override WEB_SEARCH_PROVIDER.")
    parser.add_argument("--llm-cleaning", action="store_true", help="Enable LLM refinement inside clean_sources(). Disabled by default for faster diagnostics.")
    parser.add_argument("--max-cleaning-sources", type=int, default=80, help="Sources to display as selected for cleaning.")
    parser.add_argument("--fact-sample", type=int, default=30, help="Number of cleaned facts to include in report sample.")
    parser.add_argument("--output-dir", default="", help="Output directory. Defaults to RAG/diagnostics/output.")
    parser.add_argument("--database-url", default="", help="Override DATABASE_URL for the diagnostic run.")
    parser.add_argument("--use-project-db", action="store_true", help="Use the project's configured DATABASE_URL instead of an isolated SQLite diagnostics DB.")
    parser.add_argument("--keep-project", action="store_true", help="Keep diagnostic project and sources in DB.")
    parser.add_argument("--verbose", action="store_true", help="Print workflow trace events while running.")
    return parser


if __name__ == "__main__":
    json_report, md_report = run(build_parser().parse_args())
    print(f"JSON report: {json_report}")
    print(f"Markdown report: {md_report}")
