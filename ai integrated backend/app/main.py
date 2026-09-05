"""FastAPI application entrypoint.

Layer separation: routes -> services -> ML / GIS / database.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import health, oil_spills, vessels
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(oil_spills.router)
app.include_router(vessels.router)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "openapi": "/openapi.json",
    }