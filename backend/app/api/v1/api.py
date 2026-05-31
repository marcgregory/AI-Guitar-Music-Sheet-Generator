from fastapi import APIRouter
from .endpoints import admin, auth, audio, projects, transcriptions, usage, worker

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(audio.router, prefix="/audio", tags=["audio"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(transcriptions.router, prefix="/transcriptions", tags=["transcriptions"])
api_router.include_router(usage.router, prefix="/usage", tags=["usage"])
api_router.include_router(worker.router, prefix="/worker", tags=["worker"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
