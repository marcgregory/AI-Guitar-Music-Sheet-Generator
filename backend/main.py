import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import logging
from contextlib import asynccontextmanager
from app.api.v1 import api
from app.database_init import init_db
from app.core import config

logger = logging.getLogger(__name__)
settings = config.settings

async def _modal_retry_scheduler() -> None:
    from app.api.v1.endpoints.audio import retry_rate_limited_modal_jobs_once

    interval = config.settings.MODAL_RETRY_SCAN_INTERVAL_SECONDS
    while True:
        try:
            result = await asyncio.to_thread(retry_rate_limited_modal_jobs_once)
            logger.info("[MODAL RETRY SCHEDULER] %s", result)
        except Exception:
            logger.exception("[MODAL RETRY SCHEDULER] failed to scan or dispatch")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.processing_backend = "modal"
    init_db()
    app.state.modal_retry_task = asyncio.create_task(_modal_retry_scheduler())
    try:
        yield
    finally:
        if getattr(app.state, "modal_retry_task", None) is not None:
            app.state.modal_retry_task.cancel()
            try:
                await app.state.modal_retry_task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="AI Guitar Music Sheet Generator",
    description="API for converting audio to guitar tablature and notation",
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS based on environment
allowed_origins = settings.get_allowed_origins

print("ALLOWED_ORIGINS:", allowed_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(api.api_router, prefix="/api/v1")

uploads_dir = Path(__file__).resolve().parent / "uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/audio-files", StaticFiles(directory=uploads_dir), name="audio-files")

demo_static_dir = Path(__file__).resolve().parent / "app" / "static"
app.mount("/demo", StaticFiles(directory=demo_static_dir), name="demo")

@app.get("/")
async def root():
    return {"message": "AI Guitar Music Sheet Generator API"}

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "processing_backend": getattr(app.state, "processing_backend", "modal"),
    }
