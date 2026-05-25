from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
from urllib.parse import urlsplit

LOCAL_ENVIRONMENTS = {"development", "local", "test"}
VALID_AUDIO_PROCESSING_MODES = {"local", "modal", "disabled"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=(".env", ".env.local"),
        extra="ignore",
    )

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
    # AUDIO_PROCESSING_MODE is the explicit current setting:
    # local | modal | disabled. PROCESSING_MODE is deprecated and ignored.
    AUDIO_PROCESSING_MODE: str | None = None
    PROCESSING_MODE: str | None = None
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
    # Hosted providers sometimes mangle multiline env vars. Base64 keeps the
    # Netscape cookie file byte-for-byte intact.
    YOUTUBE_COOKIES_B64: str | None = None
    # Optional yt-dlp YouTube extractor args for newer bot/attestation checks.
    # Example token format: web.gvs+TOKEN or mweb.gvs+TOKEN.
    YOUTUBE_PO_TOKEN: str | None = None
    YOUTUBE_VISITOR_DATA: str | None = None
    YOUTUBE_PLAYER_CLIENTS: str | None = None

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
    WHISPER_MODEL_SIZE: str = "base"
    WHISPER_DEVICE: str = "auto"
    WHISPER_COMPUTE_TYPE: str = "auto"
    WHISPER_LANGUAGE: str = "auto"
    WHISPER_BEAM_SIZE: int = 8
    WHISPER_BEST_OF: int = 5
    WHISPER_VAD_FILTER: bool = False
    WHISPER_CONDITION_ON_PREVIOUS_TEXT: bool = False
    WHISPER_INITIAL_PROMPT: str = (
        "Transcribe the sung lyrics exactly as heard. Preserve Tagalog, "
        "Cebuano/Bisaya, English, and mixed-language phrases. Do not translate. "
        "Keep repeated chorus lines."
    )

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

    @property
    def audio_processing_mode(self) -> str:
        """Resolve the active audio processing backend."""
        if isinstance(self.AUDIO_PROCESSING_MODE, str) and self.AUDIO_PROCESSING_MODE.strip():
            return self._clean_mode(self.AUDIO_PROCESSING_MODE)

        environment = (self.ENVIRONMENT or "").strip().lower()
        if environment in LOCAL_ENVIRONMENTS:
            return "local"
        raise ValueError("Invalid AUDIO_PROCESSING_MODE")

    @staticmethod
    def _clean_mode(mode: str) -> str:
        normalized = mode.strip().lower()
        if normalized not in VALID_AUDIO_PROCESSING_MODES:
            raise ValueError("Invalid AUDIO_PROCESSING_MODE")
        return normalized

    @property
    def raw_audio_processing_mode(self) -> str | None:
        """Return the configured raw mode value for diagnostics."""
        if not isinstance(self.AUDIO_PROCESSING_MODE, str):
            return None
        normalized = self.AUDIO_PROCESSING_MODE.strip().lower()
        return normalized or None

    @property
    def modal_trigger_url_configured(self) -> bool:
        return bool((self.MODAL_TRIGGER_URL or "").strip())

    @property
    def redis_configured(self) -> bool:
        return bool((self.REDIS_URL or "").strip())

    @property
    def celery_enabled(self) -> bool:
        return bool(
            (self.CELERY_BROKER_URL or "").strip()
            and (self.CELERY_RESULT_BACKEND or "").strip()
        )

settings = Settings()
