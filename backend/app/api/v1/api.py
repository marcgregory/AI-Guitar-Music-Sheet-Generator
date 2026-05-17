from fastapi import APIRouter
from .endpoints import auth, audio, transcriptions, worker

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(audio.router, prefix="/audio", tags=["audio"])
api_router.include_router(transcriptions.router, prefix="/transcriptions", tags=["transcriptions"])
api_router.include_router(worker.router, prefix="/worker", tags=["worker"])
