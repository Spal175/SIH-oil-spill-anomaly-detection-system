"""Health check endpoint."""
from datetime import datetime, timezone

from fastapi import APIRouter

from app.config import settings
from app.database.connection import database_available

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "database": "connected" if database_available() else "unavailable",
        "time": datetime.now(timezone.utc).isoformat(),
    }