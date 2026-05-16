from pydantic_settings import BaseSettings
from typing import List
from urllib.parse import urlsplit

class Settings(BaseSettings):
    PROJECT_NAME: str = "AI Guitar Music Sheet Generator"
    API_V1_STR: str = "/api/v1"

    # Security
    SECRET_KEY: str = "your-secret-key-here-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Database
    DATABASE_URL: str = "sqlite:///./test.db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # CORS
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    # File upload limits
    MAX_UPLOAD_SIZE: int = 100 * 1024 * 1024  # 100MB
    ALLOWED_AUDIO_EXTENSIONS: set = {".mp3", ".wav"}

    # Environment
    ENVIRONMENT: str = "development"

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

    class Config:
        case_sensitive = True
        env_file = ".env"

settings = Settings()
