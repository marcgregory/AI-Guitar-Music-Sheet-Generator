from fastapi import APIRouter
from .endpoints import auth  # , audio

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
# api_router.include_router(audio.router, prefix="/audio", tags=["audio"])