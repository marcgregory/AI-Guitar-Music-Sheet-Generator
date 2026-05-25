import logging
from pathlib import Path
from threading import Lock
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

NO_CLEAR_VOCALS_MESSAGE = "No clear vocals detected for lyrics generation."
SUPPORTED_LYRICS_LANGUAGES = {"auto", "en", "tl", "ceb", "es", "ja", "ko"}

_model_lock = Lock()
_model = None
_model_config: dict[str, str] | None = None


class LyricsTranscriptionError(RuntimeError):
    """User-safe lyrics transcription failure."""


def _cuda_available() -> bool:
    try:
        import ctranslate2

        return bool(ctranslate2.get_cuda_device_count())
    except Exception:
        return False


def resolve_whisper_runtime() -> dict[str, str]:
    requested_device = (settings.WHISPER_DEVICE or "auto").strip().lower()
    requested_compute_type = (settings.WHISPER_COMPUTE_TYPE or "auto").strip().lower()

    if requested_device == "auto":
        device = "cuda" if _cuda_available() else "cpu"
    else:
        device = requested_device

    if requested_compute_type == "auto":
        compute_type = "float16" if device == "cuda" else "int8"
    else:
        compute_type = requested_compute_type

    return {
        "model_size": (settings.WHISPER_MODEL_SIZE or "base").strip() or "base",
        "device": device,
        "compute_type": compute_type,
    }


def normalize_lyrics_language(language: str | None) -> str:
    normalized = (language or settings.WHISPER_LANGUAGE or "auto").strip().lower()
    if not normalized:
        return "auto"
    if normalized not in SUPPORTED_LYRICS_LANGUAGES:
        raise ValueError(
            "lyrics language must be one of: auto, en, tl, ceb, es, ja, ko"
        )
    return normalized


def _whisper_bool(value: bool | str | None, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def get_whisper_model():
    global _model, _model_config

    config = resolve_whisper_runtime()
    with _model_lock:
        if _model is not None and _model_config == config:
            return _model

        try:
            from faster_whisper import WhisperModel

            logger.info(
                "loading_whisper_model whisper_model=%s whisper_device=%s compute_type=%s",
                config["model_size"],
                config["device"],
                config["compute_type"],
            )
            _model = WhisperModel(
                config["model_size"],
                device=config["device"],
                compute_type=config["compute_type"],
            )
            _model_config = config
            return _model
        except Exception as exc:
            logger.exception(
                "lyrics_generation_failed reason=model_load whisper_model=%s whisper_device=%s",
                config["model_size"],
                config["device"],
            )
            raise LyricsTranscriptionError(
                "Lyrics transcription model could not be loaded."
            ) from exc


def transcribe_vocal_stem(
    audio_path: str | Path,
    language: str | None = None,
) -> dict[str, Any]:
    path = Path(audio_path)
    if not path.exists() or not path.is_file():
        raise LyricsTranscriptionError("Separated vocal stem is not available.")

    runtime = resolve_whisper_runtime()
    model = get_whisper_model()
    requested_language = normalize_lyrics_language(language)
    forced_language = None if requested_language == "auto" else requested_language

    try:
        segments_iter, info = model.transcribe(
            str(path),
            language=forced_language,
            vad_filter=_whisper_bool(settings.WHISPER_VAD_FILTER, False),
            beam_size=max(1, int(settings.WHISPER_BEAM_SIZE or 8)),
            best_of=max(1, int(settings.WHISPER_BEST_OF or 5)),
            condition_on_previous_text=_whisper_bool(
                settings.WHISPER_CONDITION_ON_PREVIOUS_TEXT,
                False,
            ),
            initial_prompt=(settings.WHISPER_INITIAL_PROMPT or "").strip() or None,
        )
        segments = [
            {
                "start": round(float(segment.start), 3),
                "end": round(float(segment.end), 3),
                "text": str(segment.text or "").strip(),
            }
            for segment in segments_iter
            if str(segment.text or "").strip()
        ]
    except LyricsTranscriptionError:
        raise
    except Exception as exc:
        logger.exception(
            "lyrics_generation_failed reason=transcribe whisper_model=%s whisper_device=%s",
            runtime["model_size"],
            runtime["device"],
        )
        raise LyricsTranscriptionError("Lyrics transcription failed.") from exc

    text = "\n".join(segment["text"] for segment in segments).strip()
    language = getattr(info, "language", None)
    logger.info(
        "lyrics_generation_completed whisper_model=%s whisper_device=%s segment_count=%s detected_language=%s",
        runtime["model_size"],
        runtime["device"],
        len(segments),
        language,
    )

    return {
        "text": text,
        "segments": segments,
        "requested_language": requested_language,
        "language": language,
        "model": "faster-whisper",
        "model_size": runtime["model_size"],
        "device": runtime["device"],
        "compute_type": runtime["compute_type"],
        "message": None if text else NO_CLEAR_VOCALS_MESSAGE,
    }
