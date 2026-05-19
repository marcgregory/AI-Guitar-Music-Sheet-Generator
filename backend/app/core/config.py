from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
from urllib.parse import urlsplit

class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True, env_file=".env")

    PROJECT_NAME: str = "AI Guitar Music Sheet Generator"
    API_V1_STR: str = "/api/v1"

    # Security
    SECRET_KEY: str = "your-secret-key-here-change-in-production"
    JWT_SECRET_KEY: str | None = None
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Database
    DATABASE_URL: str = "sqlite:///./test.db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # Selected-stem processing orchestration
    PROCESSING_MODE: str = "local"
    WORKER_API_TOKEN: str | None = None
    MODAL_TRIGGER_URL: str | None = None
    MODAL_TOKEN_ID: str | None = None
    MODAL_TOKEN_SECRET: str | None = None
    STALE_TRANSCRIPTION_TIMEOUT_SECONDS: int = 1800
    MODAL_RATE_LIMIT_BASE_BACKOFF_SECONDS: int = 60
    MODAL_RATE_LIMIT_MAX_BACKOFF_SECONDS: int = 900
    MODAL_MAX_DISPATCH_RETRIES: int = 5
    MODAL_RETRY_SCAN_INTERVAL_SECONDS: int = 30
    MODAL_RETRY_ADMIN_TOKEN: str | None = None

    # CORS
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    # File upload limits
    MAX_UPLOAD_SIZE: int = 100 * 1024 * 1024  # 100MB
    UPLOAD_DIR: str = "/app/uploads"
    MAX_SONG_DURATION_SECONDS: int = 5 * 60  # Railway-friendly MVP recommendation
    ALLOWED_AUDIO_EXTENSIONS: set = {".mp3", ".wav"}

    # YouTube imports
    # Set YOUTUBE_COOKIES_FILE to a Netscape cookies.txt path in the container,
    # or YOUTUBE_COOKIES to the raw cookies.txt contents for hosted deploys.
    YOUTUBE_COOKIES_FILE: str | None = None
    YOUTUBE_COOKIES: str | None = None

    # Cloudinary durable storage
    CLOUDINARY_URL: str | None = None
    CLOUDINARY_CLOUD_NAME: str | None = None
    CLOUDINARY_API_KEY: str | None = None
    CLOUDINARY_API_SECRET: str | None = None
    CLOUDINARY_FOLDER: str = "musicstudio"

    # Environment
    ENVIRONMENT: str = "development"
    SKIP_SOURCE_SEPARATION: bool = False
    DEMUCS_GUITAR_MODEL: str = "htdemucs"
    DEMUCS_FALLBACK_MODEL: str = "htdemucs"
    DEMUCS_CMD_TIMEOUT_SECONDS: int = 1800
    NOTE_DETECTION_SENSITIVITY: str = "normal"
    NOTE_CONFIDENCE_THRESHOLD: float = 0.35
    NOTE_CONFIDENCE_THRESHOLD_LOW: float = 0.2

    @property
    def get_allowed_origins(self) -> List[str]:
        """Parse ALLOWED_ORIGINS into normalized browser Origin values."""
        if isinstance(self.ALLOWED_ORIGINS, str):
            origins = self.ALLOWED_ORIGINS.split(",")
        else:
            origins = self.ALLOWED_ORIGINS

        normalized_origins: List[str] = []
        for origin in origins:
            normalized_origin = self._normalize_origin(origin)
            if normalized_origin:
                normalized_origins.append(normalized_origin)
        return normalized_origins

    @staticmethod
    def _normalize_origin(origin: str) -> str:
        origin = origin.strip()
        if not origin:
            return ""

        parsed = urlsplit(origin)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"

        return origin.rstrip("/")

    @property
    def jwt_secret_key(self) -> str:
        return self.JWT_SECRET_KEY or self.SECRET_KEY

settings = Settings()
