"""Read-only personal overview, independent of model and workflow initialization."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from auth import get_current_user, get_db
from models import ResearchArtifact, ResearchProject, User


STAGES = {
    "planning": "研究规划", "collecting": "资料收集", "searching": "资料检索",
    "source_assessing": "来源评估", "cleaning": "资料清洗", "risk_scoring": "风险研判",
    "risk_assessing": "风险研判", "report_generating": "报告生成", "proposal_generating": "建议书生成",
    "pausing": "正在暂停",
}


def stamp(value):
    return value.isoformat(timespec="seconds") + "Z" if value else None


def project_state(status, running):
    if running:
        return "进行中" + (" · " + STAGES[status] if status in STAGES else "")
    return {"completed": "已完成", "draft": "未开始", "paused": "已暂停", "failed": "执行失败",
            "diagnostic": "待检查"}.get(status, "待继续" if status in STAGES else "待处理")


def create_home_router(is_project_running):
    router = APIRouter(prefix="/research", tags=["Personal home"])

    @router.get("/home")
    def personal_home(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        # Administrators also see only their own work on their personal home.
        owned = ResearchProject.created_by_id == current_user.id
        states = db.execute(select(ResearchProject.id, ResearchProject.status).where(owned)).all()
        running = {row.id: bool(is_project_running(row.id)) for row in states}
        # Keep recent lists within the roster counted above if another request
        # creates a project while this read is in progress.
        roster = ResearchProject.id.in_(list(running))
        summary = {"total": len(states), "running": sum(running.values()), "completed": 0, "attention": 0}
        for row in states:
            if not running[row.id]:
                summary["completed" if row.status == "completed" else "attention"] += 1
        projects = db.execute(select(ResearchProject.id, ResearchProject.title, ResearchProject.target_type,
                                      ResearchProject.target_name, ResearchProject.status, ResearchProject.updated_at)
                              .where(owned, roster).order_by(ResearchProject.updated_at.desc(), ResearchProject.id.desc()).limit(6)).all()
        recent_projects = [{"id": row.id, "title": row.title, "target_type": row.target_type,
                            "target_name": row.target_name, "status": row.status, "is_running": running[row.id],
                            "state_label": project_state(row.status, running[row.id]), "updated_at": stamp(row.updated_at)}
                           for row in projects]
        # Rank summaries in SQL so old versions and large report bodies stay off
        # the overview response. A report and proposal each retain one latest version.
        latest = select(
            ResearchArtifact.id.label("artifact_id"),
            func.row_number().over(partition_by=(ResearchArtifact.project_id, ResearchArtifact.artifact_type),
                                   order_by=(ResearchArtifact.created_at.desc(), ResearchArtifact.version.desc(),
                                             ResearchArtifact.id.desc())).label("position"),
        ).join(ResearchProject, ResearchProject.id == ResearchArtifact.project_id).where(
            owned, roster, ResearchArtifact.artifact_type.in_(["desktop_report", "proposal"]),
        ).subquery()
        reports = db.execute(select(
            ResearchArtifact.id, ResearchArtifact.project_id, ResearchArtifact.title, ResearchArtifact.artifact_type,
            ResearchArtifact.version, ResearchArtifact.created_at, ResearchArtifact.artifact_metadata,
            ResearchProject.title.label("project_title"),
            or_(func.length(ResearchArtifact.content) > 0, ResearchArtifact.object_key != "").label("has_file"),
        ).join(latest, latest.c.artifact_id == ResearchArtifact.id)
          .join(ResearchProject, ResearchProject.id == ResearchArtifact.project_id)
          .where(latest.c.position == 1)
          .order_by(ResearchArtifact.created_at.desc(), ResearchArtifact.id.desc()).limit(6)).all()
        recent_reports = []
        for row in reports:
            metadata = row.artifact_metadata if isinstance(row.artifact_metadata, dict) else {}
            review = "建议书待确认" if metadata.get("proposal_confirmation_status") == "pending" else (
                "待复核稿" if metadata.get("delivery_status") == "review_draft" or metadata.get("quality_warning") else "")
            recent_reports.append({
                "id": row.id, "project_id": row.project_id, "project_title": row.project_title,
                "title": row.title, "artifact_type": row.artifact_type, "version": row.version,
                "created_at": stamp(row.created_at), "review_label": review,
                "export_error": bool(metadata.get("docx_export_error")), "can_download": bool(row.has_file),
            })
        return {"user": {"username": current_user.username, "display_name": current_user.display_name},
                "summary": summary, "recent_projects": recent_projects, "recent_reports": recent_reports,
                "updated_at": datetime.now(timezone.utc).isoformat()}

    return router
