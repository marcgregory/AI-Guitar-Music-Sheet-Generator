from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from app.api.v1 import api

app = FastAPI(
    title="AI Guitar Music Sheet Generator",
    description="API for converting audio to guitar tablature and notation",
    version="0.1.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(api.api_router, prefix="/api/v1")

uploads_dir = Path(__file__).resolve().parent / "uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/audio-files", StaticFiles(directory=uploads_dir), name="audio-files")

@app.get("/")
async def root():
    return {"message": "AI Guitar Music Sheet Generator API"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
