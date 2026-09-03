from typing import Any

from fastapi import APIRouter, Depends

from cv_agent.api.auth import require_bearer
from cv_agent.config import settings
from cv_agent.obs.metrics import metrics

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/v1/models")
async def list_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [{"id": settings.model_id, "object": "model", "owned_by": "cv-agent"}],
    }


@router.get("/metrics", dependencies=[Depends(require_bearer)])
async def get_metrics() -> dict[str, Any]:
    return metrics.snapshot()
