"""================================================================================
 多 Agent 桌面研究工作流 · 命令行演示工具 (research_demo.py)

 编排拓扑（线性串行，前一个 Agent 的输出作为下一个的输入）：

        search (在线搜索) → clean (数据清洗) → risk (风险研判)
                                                        │
                                                        ▼
          proposal (项目建议书) ← report (桌面研究报告)

 每个子命令可以独立运行：
    python scripts/research_demo.py search  --query "比亚迪 简介"
    python scripts/research_demo.py clean   --project-id 1 --save
    python scripts/research_demo.py risk    --project-id 1 --save
    python scripts/research_demo.py report  --project-id 1 --save
    python scripts/research_demo.py proposal --project-id 1 --save
    python scripts/research_demo.py full    --project-id 1 \
                                            --query "比亚迪 简介" --save
================================================================================="""
import argparse
import json
import sys
from pathlib import Path

# ── 把项目根目录加入 sys.path，让 Python 能找到 backend.* ──────────────────
ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# ── 加载 .env（必须放在 import 项目模块之前，因为模块里可能就读环境变量）
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

# ── 导入项目核心模块 ─────────────────────────────────────────────────────────
from database import SessionLocal  # noqa: E402
from models import ResearchArtifact, ResearchProject, User  # noqa: E402
from research_workflow import research_workflow  # noqa: E402
from web_search import web_search_provider  # noqa: E402


SEPERATOR = "━" * 72  # 终端分隔线


def print_header(title: str):
    """打印一个带标题的分隔线块，让终端输出更像 "步骤动画"。"""
    print(f"\n{SEPERATOR}")
    print(f"  {title}")
    print(SEPERATOR)


def print_trace(event: dict):
    """追踪回调：把 Agent 内部事件格式化打印（status / agent / stage / label）。"""
    if event.get("type") != "trace_step":
        # 非标准 trace 事件，原样打印以便排查
        print(f"  · [{event.get('type', 'event')}] {event}")
        return
    status = event.get("status") or "info"
    agent = event.get("agent") or "agent"
    stage = event.get("stage") or "stage"
    label = event.get("label") or ""
    detail = event.get("detail") or ""
    print(f"  [{status.upper():8}] {stage:<12} {agent:<20} {label}")
    if detail:
        print(f"             detail: {detail}")
    if event.get("url"):
        print(f"             url:    {event['url']}")


def pretty_json_preview(raw_text: str, max_items: int = 3, max_chars: int = 3000):
    """Agent 输出的 JSON 做可视化处理：太长就截断，避免刷屏。"""
    try:
        parsed = json.loads(raw_text)
    except Exception:
        # 不是合法 JSON，按文本截断输出
        print(raw_text[:max_chars])
        if len(raw_text) > max_chars:
            print(f"\n  ... (已截断，完整 {len(raw_text)} chars 已写入对象存储)")
        return

    # ── 事实库预览（cleaned_facts） ─────────────────────────────────────
    if "facts" in parsed:
        print(f"  抽取事实数: {len(parsed.get('facts', []))} 条")
        if parsed.get("information_gaps"):
            print(f"  信息缺口:   {parsed['information_gaps'][:3]}")
        for i, fact in enumerate(parsed["facts"][:max_items], 1):
            print(f"\n  [{i}] {json.dumps(fact, ensure_ascii=False, indent=4)}")
        if len(parsed["facts"]) > max_items:
            print(f"\n  ... 剩余 {len(parsed['facts']) - max_items} 条未展示")
        return

    # ── 风险评分预览（risk_assessment） ────────────────────────────────
    if "dimensions" in parsed:
        print(f"  总体评分: {parsed.get('overall_score')}  等级: {parsed.get('risk_level')}")
        for dim in parsed.get("dimensions", []):
            print(
                f"    · {dim.get('name', '?'):<18} "
                f"score={dim.get('score', '?'):<4} "
                f"level={dim.get('level', '?')}"
            )
        if parsed.get("key_risks"):
            print("  关键风险点:")
            for r in parsed["key_risks"][:max_items]:
                print(f"    - {r}")
        return

    # ── 其他 JSON：直接紧凑输出 ────────────────────────────────────────
    print(json.dumps(parsed, ensure_ascii=False, indent=2)[:max_chars])


def get_project(db, project_id: int) -> ResearchProject:
    """根据 project_id 加载项目；不存在直接退出。"""
    project = db.query(ResearchProject).filter(ResearchProject.id == project_id).first()
    if not project:
        raise SystemExit(f"❌ Project not found: {project_id}")
    return project


def latest_artifact(db, project_id: int, artifact_type: str) -> ResearchArtifact | None:
    """取某项目某类型 artifact 的最新版本（用于链式调用——前一步的产物喂给下一步）。"""
    return (
        db.query(ResearchArtifact)
        .filter(ResearchArtifact.project_id == project_id, ResearchArtifact.artifact_type == artifact_type)
        .order_by(ResearchArtifact.version.desc())
        .first()
    )


def cmd_search(args):
    """【Agent 1】在线搜索：单纯展示搜索结果（不写数据库），"先看看都抓到了什么"。"""
    print_header(f"🔍 在线搜索 Agent | query: {args.query} | limit: {args.limit}")
    results = web_search_provider.search(args.query, limit=args.limit)
    print(f"  → 命中 {len(results)} 条结果：\n")
    for idx, item in enumerate(results, 1):
        snippet = (item.get("summary") or item.get("content") or "(无摘要)")[:220]
        print(
            f"  [{idx:>2}] {item.get('title') or '(无标题)':<60}\n"
            f"        🔗  {item.get('url') or '(无 URL)'}\n"
            f"        📊  可信度: {item.get('credibility_score')}/100\n"
            f"        📝  {snippet} ...\n"
        )


def cmd_clean(args):
    """【Agent 2】数据清洗：把项目已有的 sources → 变成结构化 facts JSON。"""
    db = SessionLocal()
    try:
        project = get_project(db, args.project_id)
        print_header(
            f"🧹 数据清洗 Agent | 项目 #{project.id} {project.title} "
            f"| 原始资料 {len(project.sources)} 条"
        )
        result = research_workflow.clean_sources(project, emit=print_trace)

        print("\n📋 清洗后事实库预览：")
        pretty_json_preview(result)

        if args.save:
            artifact = research_workflow.save_artifact(
                db, project, "cleaned_facts", "清洗后事实库", result,
                {"agent": "cli_data_cleaning"}, created_by="cli"
            )
            print(f"\n✅ 已保存 artifact #{artifact.id} | MinIO: {artifact.object_key}")
    finally:
        db.close()


def cmd_risk(args):
    """【Agent 3】风险研判：基于 cleaned_facts（若没有则自动跑一次）做多维度风险评分。"""
    db = SessionLocal()
    try:
        project = get_project(db, args.project_id)
        print_header(f"⚠️  风险研判 Agent | 项目 #{project.id} {project.title}")

        # 优先复用之前生成的 cleaned_facts，没有则现场跑一次清洗（"自动补前一步"）
        cleaned = latest_artifact(db, project.id, "cleaned_facts")
        if cleaned:
            print(f"  📦 复用已有的 cleaned_facts v{cleaned.version}（artifact #{cleaned.id}）")
            cleaned_text = cleaned.content
        else:
            print("  ⚙️  未找到 cleaned_facts，现场跑一次数据清洗 ...")
            cleaned_text = research_workflow.clean_sources(project, emit=print_trace)

        result = research_workflow.assess_risk(project, cleaned_text, emit=print_trace)

        print("\n📊 风险评分预览：")
        pretty_json_preview(result)

        if args.save:
            artifact = research_workflow.save_artifact(
                db, project, "risk_assessment", "风险研判", result,
                {"agent": "cli_risk"}, created_by="cli"
            )
            print(f"\n✅ 已保存 artifact #{artifact.id} | MinIO: {artifact.object_key}")
    finally:
        db.close()


def cmd_report(args):
    """【Agent 4】桌面研究报告：基于 cleaned_facts + risk_assessment 生成 Markdown 报告。"""
    db = SessionLocal()
    try:
        project = get_project(db, args.project_id)
        print_header(f"📄 桌面研究报告 Agent | 项目 #{project.id} {project.title}")

        # 自动补前两步（如果缺失）——保证任一子命令都能 "单独跑通"
        cleaned = latest_artifact(db, project.id, "cleaned_facts")
        risk = latest_artifact(db, project.id, "risk_assessment")
        if cleaned:
            print(f"  📦 复用 cleaned_facts v{cleaned.version}")
            cleaned_text = cleaned.content
        else:
            print("  ⚙️  缺少 cleaned_facts，自动补数据清洗 ...")
            cleaned_text = research_workflow.clean_sources(project, emit=print_trace)
        if risk:
            print(f"  📦 复用 risk_assessment v{risk.version}")
            risk_text = risk.content
        else:
            print("  ⚙️  缺少 risk_assessment，自动补风险研判 ...")
            risk_text = research_workflow.assess_risk(project, cleaned_text, emit=print_trace)

        result = research_workflow.generate_report(project, cleaned_text, risk_text, emit=print_trace)

        print("\n📄 报告预览（只展示开头，完整内容见 MinIO）：")
        print("=" * 72)
        preview_len = 1200
        print(result[:preview_len])
        if len(result) > preview_len:
            print(f"\n  ... 已截断（完整 {len(result)} chars，已写入对象存储）")

        if args.save:
            artifact = research_workflow.save_artifact(
                db, project, "desktop_report", "桌面研究报告", result,
                {"agent": "cli_report"}, created_by="cli"
            )
            print(f"\n✅ 已保存 artifact #{artifact.id} | MinIO: {artifact.object_key}")
    finally:
        db.close()


def cmd_proposal(args):
    """【Agent 5】项目建议书：基于 desktop_report + risk_assessment 生成客户建议书。"""
    db = SessionLocal()
    try:
        project = get_project(db, args.project_id)
        print_header(f"💼 项目建议书 Agent | 项目 #{project.id} {project.title}")

        # 自动补前三步（report 本身也会自动补 clean/risk）
        report = latest_artifact(db, project.id, "desktop_report")
        risk = latest_artifact(db, project.id, "risk_assessment")
        if report:
            print(f"  📦 复用 desktop_report v{report.version}")
            report_text = report.content
        else:
            print("  ⚙️  缺少 desktop_report，自动跑数据清洗 → 风险研判 → 报告 ...")
            cleaned_text = research_workflow.clean_sources(project, emit=print_trace)
            risk_text_for_report = (
                risk.content if risk else research_workflow.assess_risk(project, cleaned_text, emit=print_trace)
            )
            report_text = research_workflow.generate_report(project, cleaned_text, risk_text_for_report, emit=print_trace)
        risk_text = risk.content if risk else "{}"

        result = research_workflow.generate_proposal(project, report_text, risk_text, emit=print_trace)

        print("\n💼 建议书预览：")
        print("=" * 72)
        preview_len = 1200
        print(result[:preview_len])
        if len(result) > preview_len:
            print(f"\n  ... 已截断（完整 {len(result)} chars，已写入对象存储）")

        if args.save:
            artifact = research_workflow.save_artifact(
                db, project, "proposal", "项目建议书", result,
                {"agent": "cli_proposal"}, created_by="cli"
            )
            print(f"\n✅ 已保存 artifact #{artifact.id} | MinIO: {artifact.object_key}")
    finally:
        db.close()


def cmd_full(args):
    """【完整流水线】run_project 一行调用：5 个 Agent 顺序跑完所有产物。"""
    db = SessionLocal()
    try:
        project = get_project(db, args.project_id)
        print_header(
            f"🚀 完整工作流 run_project | 项目 #{project.id} {project.title} "
            f"| queries={len(args.query)} | focus={len(args.focus)} | limit={args.limit}"
        )

        artifacts, sources_added = research_workflow.run_project(
            db,
            project,
            search_queries=args.query,
            focus_questions=args.focus,
            max_results_per_query=args.limit,
            generate_proposal=not args.no_proposal,
            emit=print_trace,
        )

        print_header("🎉 工作流完成 · 产物汇总")
        print(f"  📥 原始资料数     : {sources_added} 条")
        print(f"  📄 生成 artifact  : {len(artifacts)} 个")
        for artifact in artifacts:
            print(
                f"     · #{artifact.id:<3} {artifact.artifact_type:<18} "
                f"v{artifact.version}  MinIO: {artifact.object_key}"
            )
    finally:
        db.close()


def cmd_list_projects(args):
    """【辅助】列出数据库里所有研究项目（方便找 project_id）。"""
    db = SessionLocal()
    try:
        projects = db.query(ResearchProject).order_by(ResearchProject.updated_at.desc()).all()
        print_header(f"📋 研究项目列表（共 {len(projects)} 个）")
        print(f"  {'ID':>4} | 状态 | 更新时间           | 对象 / 行业 | 标题")
        print("-" * 72)
        for p in projects:
            print(
                f"  {p.id:>4} | {p.status:<4} | {p.updated_at.isoformat(timespec='seconds')} "
                f"| {p.target_name or '-':<10} / {p.industry or '-':<10} | {p.title}"
            )
    finally:
        db.close()


def cmd_list_artifacts(args):
    """【辅助】列出某个项目的所有 artifact 版本（方便回看历史）。"""
    db = SessionLocal()
    try:
        project = get_project(db, args.project_id)
        artifacts = (
            db.query(ResearchArtifact)
            .filter(ResearchArtifact.project_id == project.id)
            .order_by(ResearchArtifact.artifact_type, ResearchArtifact.version.desc())
            .all()
        )
        print_header(f"📦 项目 #{project.id} 产物列表（{len(artifacts)} 个版本）")
        for a in artifacts:
            print(
                f"  · #{a.id:<3} {a.artifact_type:<18} v{a.version}  "
                f"by {a.created_by:<16} ({len(a.content)} chars)\n"
                f"      MinIO: {a.object_key}"
            )
    finally:
        db.close()


def build_parser():
    """构造命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description="多 Agent 桌面研究工作流演示 (research_demo.py)",
        epilog=(
            "示例：\n"
            "  python scripts/research_demo.py list\n"
            "  python scripts/research_demo.py search --query \"比亚迪 简介\"\n"
            "  python scripts/research_demo.py clean  --project-id 1 --save\n"
            "  python scripts/research_demo.py risk   --project-id 1 --save\n"
            "  python scripts/research_demo.py report --project-id 1 --save\n"
            "  python scripts/research_demo.py proposal --project-id 1 --save\n"
            "  python scripts/research_demo.py full --project-id 1 "
            "--query \"比亚迪 简介\" --query \"比亚迪 诉讼\" --save\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── 辅助命令 ─────────────────────────────────────────────────────────────
    sub.add_parser("list", help="列出所有研究项目（方便找 project_id）").set_defaults(func=cmd_list_projects)

    p = sub.add_parser("artifacts", help="列出某个项目的所有产物版本")
    p.add_argument("--project-id", type=int, required=True)
    p.set_defaults(func=cmd_list_artifacts)

    # ── 1. 在线搜索（只展示，不写库） ───────────────────────────────────────
    p = sub.add_parser("search", help="🔍 在线搜索 Agent：展示搜索结果")
    p.add_argument("--query", required=True, help="搜索关键词")
    p.add_argument("--limit", type=int, default=5, help="每个关键词最多结果数")
    p.set_defaults(func=cmd_search)

    # ── 2~5. 四个 Agent 统一参数：--project-id + --save ────────────────────
    for name, func, help_text in [
        ("clean", cmd_clean, "🧹 数据清洗 Agent：把原始资料变成结构化 facts JSON"),
        ("risk", cmd_risk, "⚠️  风险研判 Agent：基于事实库做多维度风险评分"),
        ("report", cmd_report, "📄 桌面研究报告 Agent：基于事实+风险生成 Markdown 报告"),
        ("proposal", cmd_proposal, "💼 项目建议书 Agent：基于报告生成客户建议书"),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--project-id", type=int, required=True, help="研究项目 ID（用 list 命令查看）")
        p.add_argument("--save", action="store_true", help="把产物写入数据库 + MinIO（默认只在终端展示）")
        p.set_defaults(func=func)

    # ── 6. 一键跑完整流程（推荐给自动化脚本） ─────────────────────────────
    p = sub.add_parser("full", help="🚀 一键跑完整流水线：搜索 → 清洗 → 风险 → 报告 → 建议书")
    p.add_argument("--project-id", type=int, required=True)
    p.add_argument("--query", action="append", default=[], help="搜索关键词，可重复多次")
    p.add_argument("--focus", action="append", default=[], help="重点追问，可重复多次")
    p.add_argument("--limit", type=int, default=5, help="每个关键词最多抓取多少条")
    p.add_argument("--no-proposal", action="store_true", help="跳过最后一步建议书生成")
    p.set_defaults(func=cmd_full)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()