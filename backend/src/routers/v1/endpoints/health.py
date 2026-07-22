"""Liveness and readiness, outside the /api/v1 prefix."""

from fastapi import APIRouter, Depends

from ....core.config import Settings, get_settings
from ....utils.detection import detector_ready

health_router = APIRouter(prefix="/health")


@health_router.get("/live")
async def live() -> dict:
    return {"status": "ok"}


@health_router.get("/ready")
async def ready(settings: Settings = Depends(get_settings)) -> dict:
    detectors = {
        name: ("ready" if detector_ready(name, settings) else "unavailable")
        for name in settings.detector_names
    }
    all_ready = all(state == "ready" for state in detectors.values()) and bool(detectors)
    return {"status": "ready" if all_ready else "degraded", "detectors": detectors}
