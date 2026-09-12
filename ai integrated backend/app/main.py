"""FastAPI application entrypoint.

Layer separation: routes -> services -> ML / GIS / database.

During startup the AIS worker is launched as a background task: it consumes
the upstream AIS feed, persists each report, and broadcasts the same message
to every dashboard connected on ``/ws/live``.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import health, live, oil_spills, vessels
from app.config import settings
from app.services.live import live_hub
from app.workers.ais_worker import AISWorker

logger = logging.getLogger(__name__)

# Make the worker/live-hub INFO logs visible when running under uvicorn.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker: AISWorker | None = None
    task: asyncio.Task | None = None

    if settings.ais_run_worker:
        try:
            worker = AISWorker(
                ws_url=settings.ais_ws_url,
                reconnect_base=settings.ais_reconnect_base,
                reconnect_max=settings.ais_reconnect_max,
                broadcast=live_hub.broadcast,
            )
            task = asyncio.create_task(worker.run_forever())
            app.state.ais_worker = worker
            app.state.ais_worker_task = task
            logger.info("AIS worker started (upstream: %s)", settings.ais_ws_url)
        except Exception:
            logger.exception("AIS worker failed to start; running without live feed")
            if task is not None:
                task.cancel()

    try:
        yield
    finally:
        if task is not None:
            if worker is not None:
                await worker.stop()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)

# Allow the local dashboards (file:// or any dev server) to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(oil_spills.router)
app.include_router(vessels.router)
app.include_router(live.router)


# ── Dashboard static assets ────────────────────────────────────────────────
# Serve the OceanWatch dashboard from the API itself (http://<host>:<port>/),
# so the browser origin always matches the API/WebSocket origin. Only the
# files the dashboard references are exposed.
_DASH = settings.base_dir

@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(_DASH / "index.html")


@app.get("/index.html", include_in_schema=False)
async def dashboard_index() -> FileResponse:
    return FileResponse(_DASH / "index.html")


@app.get("/style.css", include_in_schema=False)
async def dashboard_style() -> FileResponse:
    return FileResponse(_DASH / "style.css")


app.mount(
    "/js",
    StaticFiles(directory=_DASH / "js"),
    name="dashboard-js",
)
app.mount(
    "/vendor",
    StaticFiles(directory=_DASH / "vendor"),
    name="dashboard-vendor",
)