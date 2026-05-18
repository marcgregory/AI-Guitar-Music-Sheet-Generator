from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import logging
from contextlib import asynccontextmanager
from app.api.v1 import api
from app.database_init import init_db
from app.core.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.processing_backend = "modal"
    yield


app = FastAPI(
    title="AI Guitar Music Sheet Generator",
    description="API for converting audio to guitar tablature and notation",
    version="0.1.0",
    lifespan=lifespan,
)

init_db()

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
