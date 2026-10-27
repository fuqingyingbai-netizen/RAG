from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pathlib import Path
import asyncio
from contextlib import suppress
import os
import sys

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import api as api_module
import research_api as research_api_module
import company_knowledge as company_knowledge_module
import research_workflow as research_workflow_module
import industry_research as industry_research_module
from database import init_db
from runtime_version import create_version_router
from account_lifecycle import invitation_cleanup_loop
from personal_home import create_home_router

BASE_DIR = BACKEND_DIR.parent
FRONTEND_DIR = BASE_DIR / "frontend"


def create_app() -> FastAPI:
    app = FastAPI(title="Cute Cat Bot API")

    @app.exception_handler(company_knowledge_module.KnowledgeError)
    async def _knowledge_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={'detail': str(exc)})

    @app.on_event("startup")
    async def _startup_init_db():
        init_db()
        # Workflows run in process-local threads. If the development server is
        # restarted, their database status otherwise remains "generating"
        # forever even though no worker exists to finish them.
        research_api_module.recover_stale_research_projects()
        app.state.invitation_cleanup_task = asyncio.create_task(invitation_cleanup_loop())

    @app.on_event("shutdown")
    async def _stop_invitation_cleanup():
        task = getattr(app.state, "invitation_cleanup_task", None)
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # No-cache middleware for development
    @app.middleware("http")
    async def _no_cache(request, call_next):
        response = await call_next(request)
        path = request.url.path or ""
        if path == "/" or path.endswith((".html", ".js", ".css")):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    app.include_router(api_module.router)
    app.include_router(research_api_module.router)
    app.include_router(create_home_router(research_api_module._is_project_running))
    app.include_router(company_knowledge_module.router)
    app.include_router(create_version_router({
        'cleaning': research_workflow_module.INDUSTRY_CLEANING_VERSION,
        'risk': industry_research_module.INDUSTRY_RISK_VERSION,
        'report': research_workflow_module.INDUSTRY_REPORT_VERSION,
    }))

    # serve frontend static files at root
    if FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", 8000)))
