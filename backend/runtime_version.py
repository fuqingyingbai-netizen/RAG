"""Read-only identity of the loaded application, with no filesystem/DB queries."""
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse


def create_version_router(industry_versions: dict[str, str]) -> APIRouter:
    # Capture values bound to the already imported workflow modules. Reading
    # edited Python files or Git here would misreport an old running process.
    snapshot = {
        'service': 'rag-backend',
        'instance_id': str(uuid4()),
        'loaded_at_utc': datetime.now(timezone.utc).isoformat(),
        'industry': dict(industry_versions),
    }
    router = APIRouter(tags=['system'])

    @router.get('/version', summary='查询已加载的后端版本')
    def loaded_version():
        return JSONResponse(snapshot, headers={
            'Cache-Control': 'no-store, max-age=0',
            'Pragma': 'no-cache',
            'Expires': '0',
        })

    return router
