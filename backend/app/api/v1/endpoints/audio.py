from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Response, Body, UploadFile, File, Form, Request
import json
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, update
from dataclasses import dataclass
import base64
import binascii
import os
import uuid
import hashlib
import shutil
from pathlib import Path
import re
import tempfile
import yt_dlp
from yt_dlp.utils import DownloadError
import httpx
from pydantic import BaseModel
from urllib.parse import parse_qs, urlsplit
from datetime import datetime, timedelta, timezone
import random

from .... import db, core, models
from ....core.security import get_current_user
from .. import schemas
from ....services import midi, storage, tablature
from ....services.audio_source_resolver import (
    MISSING_SEPARATED_STEM_MESSAGE,
    resolve_generate_tab_audio_source,
)
from ....services.tablature import tablature_to_ascii_tab
from ....celery import celery_app

# Schema for YouTube URL request
class YouTubeUploadRequest(BaseModel):
    youtube_url: str
    selected_stem: str
    project_id: int = None

class GenerateTabRequest(BaseModel):
    sensitivity: str | None = None

class GenerateLyricsRequest(BaseModel):
    language: str | None = "auto"

router = APIRouter()
VALID_SELECTED_STEMS = {"vocals", "drums", "bass", "other"}
VALID_LYRICS_LANGUAGES = {"auto", "en", "tl", "ceb", "es", "ja", "ko"}
ACTIVE_TRANSCRIPTION_STATUSES = ("pending", "queued", "processing")
USAGE_LIMIT_ACTIVE_STATUSES = ACTIVE_TRANSCRIPTION_STATUSES
QUEUE_WAITING_STATUSES = ("pending", "queued")
TERMINAL_TRANSCRIPTION_STATUSES = (
    "stem_ready",
    "completed",
    "completed_with_warning",
    "failed",
    "cancelled",
    "deleted",
)
ESTIMATED_SECONDS_PER_SELECTED_STEM_JOB = 300
DEMO_AUDIO_URL = "/demo/example-guitar-riff.wav"
STEM_READY_MESSAGE = "Stem is ready. Listen first, then generate tabs if the stem sounds useful."
YOUTUBE_COOKIE_REJECTED_DETAIL = (
    "Cookies were loaded, but YouTube rejected them. Re-export fresh cookies, add YOUTUBE_PO_TOKEN, or upload audio directly."
)
YOUTUBE_COOKIES_MALFORMED_DETAIL = (
    "YOUTUBE_COOKIES is configured but is not valid Netscape cookie format."
)
YOUTUBE_COOKIES_NO_YOUTUBE_DOMAIN_DETAIL = (
    "YOUTUBE_COOKIES is configured but does not contain YouTube cookies."
)
IMPORTANT_YOUTUBE_COOKIE_NAMES = {
    "SID",
    "HSID",
    "SSID",
    "SAPISID",
    "LOGIN_INFO",
    "VISITOR_INFO1_LIVE",
}
LOW_YOUTUBE_COOKIE_COUNT_THRESHOLD = 3
DEFAULT_YOUTUBE_PLAYER_CLIENTS = ("default", "mweb")
ACTIVE_JOB_LIMIT_DETAIL = (
    "You already have a transcription job in progress. Please wait for it to finish before starting another."
)
DAILY_JOB_LIMIT_DETAIL = "Daily processing limit reached. Please try again tomorrow."

# Define the upload directory relative to the backend package so the location is
# stable whether uvicorn is launched from the repo root or from backend/.
# BACKEND_DIR = Path(__file__).resolve().parents[4]
# UPLOAD_DIR = BACKEND_DIR / "uploads"
# UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

UPLOAD_DIR = Path(storage.normalize_local_path(core.config.settings.UPLOAD_DIR)).resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

import logging
import traceback
from threading import Lock

logger = logging.getLogger(__name__)
_queue_promotion_lock = Lock()


def _log_modal_dispatch_event(
    event: str,
    transcription: models.Transcription | None = None,
    *,
    transcription_id: int | None = None,
    selected_stem: str | None = None,
    job_type: str | None = None,
    modal_request_id: str | None = None,
    dispatch_status: str | None = None,
    retry_count: int | None = None,
    extra: dict | None = None,
) -> None:
    if transcription is not None:
        transcription_id = transcription.id
        selected_stem = selected_stem or transcription.selected_stem
        job_type = job_type or transcription.modal_job_type
        modal_request_id = modal_request_id or transcription.modal_request_id
        dispatch_status = dispatch_status or transcription.modal_dispatch_status
        retry_count = retry_count if retry_count is not None else transcription.modal_retry_count

    logger.info(
        "modal_dispatch_event event=%s transcription_id=%s selected_stem=%s "
        "job_type=%s modal_request_id=%s dispatch_status=%s retry_count=%s extra=%s",
        event,
        transcription_id,
        selected_stem,
        job_type,
        modal_request_id,
        dispatch_status,
        retry_count,
        extra or {},
    )


def _modal_status_detail(transcription: models.Transcription) -> str | None:
    dispatch_status = transcription.modal_dispatch_status
    processing_status = transcription.processing_status
    if processing_status == "queued" and dispatch_status in {"rate_limited", "retry_queued"}:
        return "rate_limited_retry"
    if processing_status == "queued":
        return "queued_waiting_for_active_job"
    if processing_status == "processing" and dispatch_status == "dispatched":
        return "dispatched"
    if dispatch_status == "completed":
        return "callback_completed"
    if dispatch_status == "failed":
        return "dispatch_failed"
    return dispatch_status


def _run_transcription_locally(
    transcription_id: int,
    detection_sensitivity: str | None = None,
    selected_stem_override: str | None = None,
):
    """Run the local transcription task directly for development."""
    from ....tasks import process_audio_transcription

    process_audio_transcription.run(
        transcription_id,
        detection_sensitivity,
        selected_stem_override,
    )


def _run_instrument_track_reprocess_locally(track_id: int):
    """Run local track reprocessing directly for development."""
    from ....tasks import reprocess_instrument_track

    reprocess_instrument_track.run(track_id)


def _run_tab_generation_locally(
    transcription_id: int,
    detection_sensitivity: str | None = None,
):
    """Run local tab generation directly for development."""
    from ....tasks import generate_tab_from_separated_stem

    generate_tab_from_separated_stem.run(transcription_id, detection_sensitivity)


def _run_lyrics_generation_locally(
    transcription_id: int,
    lyrics_language: str | None = None,
):
    """Run local lyrics generation directly for development."""
    from ....tasks import generate_lyrics_from_vocal_stem

    generate_lyrics_from_vocal_stem.run(transcription_id, lyrics_language)


def _start_transcription_processing(
    transcription_id: int,
    background_tasks: BackgroundTasks,
    db_session: Session,
    *,
    detection_sensitivity: str | None = None,
    selected_stem_override: str | None = None,
) -> str | None:
    """Start transcription according to the configured processing mode."""
    mode = _processing_mode()
    if mode == "local":
        if _celery_has_available_worker():
            result = celery_app.send_task(
                "app.tasks.process_audio_transcription",
                args=[transcription_id, detection_sensitivity, selected_stem_override],
            )
            return result.id

        logger.info(
            "No Celery worker detected; running transcription %s in a local background task.",
            transcription_id,
        )
        background_tasks.add_task(
            _run_transcription_locally,
            transcription_id,
            detection_sensitivity,
            selected_stem_override,
        )
        return "local-background"

    if mode == "modal":
        background_tasks.add_task(_trigger_modal_worker, transcription_id, "process", detection_sensitivity, None)
        return None

    if mode == "disabled":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audio processing is disabled by AUDIO_PROCESSING_MODE=disabled.",
        )

    raise ValueError("Invalid AUDIO_PROCESSING_MODE")


def _start_tab_generation(
    transcription_id: int,
    background_tasks: BackgroundTasks,
    *,
    detection_sensitivity: str | None = None,
) -> str | None:
    """Start TAB/score generation according to the configured processing mode."""
    mode = _processing_mode()
    if mode == "local":
        if _celery_has_available_worker():
            result = celery_app.send_task(
                "app.tasks.generate_tab_from_separated_stem",
                args=[transcription_id, detection_sensitivity],
            )
            return result.id

        logger.info(
            "No Celery worker detected; running tab generation %s in a local background task.",
            transcription_id,
        )
        background_tasks.add_task(
            _run_tab_generation_locally,
            transcription_id,
            detection_sensitivity,
        )
        return None

    if mode == "modal":
        background_tasks.add_task(
            _trigger_modal_worker,
            transcription_id,
            "generate_tab",
            detection_sensitivity,
            None,
        )
        return None

    if mode == "disabled":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audio processing is disabled by AUDIO_PROCESSING_MODE=disabled.",
        )

    raise ValueError("Invalid AUDIO_PROCESSING_MODE")


def _start_lyrics_generation(
    transcription_id: int,
    background_tasks: BackgroundTasks,
    *,
    lyrics_language: str | None = None,
) -> str | None:
    """Start vocal lyrics generation without changing the main processing state."""
    mode = _processing_mode()
    if mode == "local":
        if _celery_has_available_worker():
            result = celery_app.send_task(
                "app.tasks.generate_lyrics_from_vocal_stem",
                args=[transcription_id, lyrics_language],
            )
            return result.id

        logger.info(
            "No Celery worker detected; running lyrics generation %s in a local background task.",
            transcription_id,
        )
        background_tasks.add_task(
            _run_lyrics_generation_locally,
            transcription_id,
            lyrics_language,
        )
        return "local-background"

    if mode == "modal":
        background_tasks.add_task(
            _trigger_modal_worker,
            transcription_id,
            "generate_lyrics",
            None,
            None,
            lyrics_language,
        )
        return None

    if mode == "disabled":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audio processing is disabled by AUDIO_PROCESSING_MODE=disabled.",
        )

    raise ValueError("Invalid AUDIO_PROCESSING_MODE")


def _processing_mode() -> str:
    mode = core.config.settings.audio_processing_mode
    if mode not in {"local", "modal", "disabled"}:
        raise ValueError("Invalid AUDIO_PROCESSING_MODE")
    return mode


def _modal_trigger_url_configured() -> bool:
    return core.config.settings.modal_trigger_url_configured


def _validate_processing_mode_ready() -> None:
    mode = _processing_mode()
    if mode == "disabled":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audio processing is disabled by AUDIO_PROCESSING_MODE=disabled.",
        )
    if mode == "modal" and not _modal_trigger_url_configured():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Modal processing is enabled but MODAL_TRIGGER_URL is not configured.",
        )


def _build_worker_payload_for_modal(
    transcription: models.Transcription,
    *,
    job_type: str = "process",
    detection_sensitivity: str | None = None,
    track_id: int | None = None,
    lyrics_language: str | None = None,
) -> dict[str, str | int | None]:
    selected_stem = transcription.selected_stem or "other"
    original_audio_url = transcription.original_audio_url if job_type == "process" else None
    separated_audio_url = transcription.separated_audio_url
    if job_type == "generate_tab" and selected_stem in {"bass", "other"}:
        resolved_source = resolve_generate_tab_audio_source(transcription)
        if resolved_source != transcription.separated_audio_url:
            raise ValueError("separated_audio_url is required for Modal tab generation.")
        separated_audio_url = resolved_source
    elif job_type == "generate_tab" and not separated_audio_url:
        raise ValueError("separated_audio_url is required for Modal tab generation.")
    return {
        "transcription_id": transcription.id,
        "job_type": job_type,
        "modal_request_id": transcription.modal_request_id,
        "selected_stem": selected_stem,
        "demucs_stem": selected_stem,
        "original_audio_url": original_audio_url,
        "separated_audio_url": separated_audio_url,
        "detection_sensitivity": detection_sensitivity,
        "lyrics_language": lyrics_language,
        "track_id": track_id,
        "source_type": transcription.source_type,
        "source_url": (
            (transcription.source_url or transcription.youtube_url)
            if job_type == "process"
            else None
        ),
        "normalized_source_id": transcription.normalized_source_id,
        "audio_hash": transcription.audio_hash,
    }


def _modal_retry_delay_seconds(retry_count: int) -> int:
    # Define base delays as specified in requirements
    base_delays = {
        1: 30,   # 30 seconds
        2: 60,   # 60 seconds
        3: 120,  # 120 seconds
        4: 300,  # 300 seconds
        5: 600,  # 600 seconds
    }

    # Get base delay for this retry count, default to exponential backoff if not found
    if retry_count in base_delays:
        base_delay = base_delays[retry_count]
    else:
        # Fallback to exponential backoff for retry counts > 5
        base = core.config.settings.MODAL_RATE_LIMIT_BASE_BACKOFF_SECONDS
        base_delay = base * (2 ** (retry_count - 1))

    # Add random jitter: random.uniform(5, 20) as specified
    jitter = random.uniform(5, 20)
    delay = base_delay + jitter

    # Apply ceiling from settings
    ceiling = core.config.settings.MODAL_RATE_LIMIT_MAX_BACKOFF_SECONDS
    return int(min(ceiling, delay))


def _manual_generation_field(selected_stem: str | None) -> str | None:
    stem = (selected_stem or "other").strip().lower()
    if stem == "drums":
        return "rhythm_generation_status"
    if stem in {"bass", "other"}:
        return "tab_generation_status"
    return None


def _set_manual_generation_status(
    transcription: models.Transcription,
    generation_status: str,
) -> None:
    field_name = _manual_generation_field(transcription.selected_stem)
    if not field_name:
        return
    setattr(transcription, field_name, generation_status)


def _mark_modal_retry(
    transcription: models.Transcription,
    session: Session,
    *,
    error: str,
    retry_after_seconds: int | None = None,
    rate_limited: bool = False,
) -> None:
    # Check if this is an internal worker failure that should not be retried
    internal_worker_failures = [
        "TensorFlow JIT compilation failed",
        "libdevice not found",
        "Basic Pitch",
        "Graph execution error"
    ]

    # If this is an internal worker failure, mark as failed permanently
    if any(failure_indicator in error for failure_indicator in internal_worker_failures):
        transcription.processing_status = "failed"
        transcription.processing_error = error
        transcription.modal_dispatch_status = "failed"
        if transcription.modal_job_type == "generate_tab":
            _set_manual_generation_status(transcription, "failed")
        transcription.modal_retry_at = None
        transcription.queue_position = None
        transcription.estimated_wait_time = None
        transcription.is_processed = False
        transcription.celery_task_id = None
        session.add(transcription)
        session.commit()
        return

    next_retry_count = int(transcription.modal_retry_count or 0) + 1
    max_retries = max(1, int(core.config.settings.MODAL_MAX_DISPATCH_RETRIES))
    if next_retry_count > max_retries:
        transcription.processing_status = "failed"
        transcription.processing_error = (
            "Modal capacity unavailable. Please retry later."
        )
        transcription.modal_dispatch_status = "failed"
        if transcription.modal_job_type == "generate_tab":
            _set_manual_generation_status(transcription, "failed")
        transcription.modal_retry_at = None
        transcription.queue_position = None
        transcription.estimated_wait_time = None
        transcription.is_processed = False
    else:
        delay = retry_after_seconds or _modal_retry_delay_seconds(next_retry_count)
        transcription.processing_status = "queued"
        transcription.processing_error = error
        transcription.modal_dispatch_status = "rate_limited" if rate_limited else "retry_queued"
        if transcription.modal_job_type == "generate_tab":
            _set_manual_generation_status(transcription, "queued")
        transcription.modal_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        transcription.modal_retry_count = next_retry_count
        transcription.queue_position = None
        transcription.estimated_wait_time = delay
        # Metrics: retry delay for averaging
        logger.info(
            f"METRICS: modal_retry_delay_seconds {delay}"
        )
        logger.info(
            f"Modal retry scheduled: transcription_id={transcription.id}, "
            f"retry_count={transcription.modal_retry_count}, "
            f"retry_at={transcription.modal_retry_at}, "
            f"modal_dispatch_status={transcription.modal_dispatch_status}"
        )
        _log_modal_dispatch_event(
            "retry_scheduled",
            transcription,
            job_type=transcription.modal_job_type,
            extra={"retry_at": transcription.modal_retry_at.isoformat()},
        )
    transcription.celery_task_id = None
    session.add(transcription)
    session.commit()


def _fetch_next_rate_limited_modal_job(session: Session) -> models.Transcription | None:
    now_utc = datetime.now(timezone.utc)
    return (
        session.query(models.Transcription)
        .filter(
            models.Transcription.modal_dispatch_status.in_(["rate_limited", "retry_queued"]),
            models.Transcription.modal_retry_at != None,
            models.Transcription.modal_retry_at <= now_utc,
            models.Transcription.is_deleted == False,
            models.Transcription.is_processed == False,
        )
        .order_by(models.Transcription.modal_retry_at.asc(), models.Transcription.id.asc())
        .with_for_update(skip_locked=True)
        .first()
    )


def retry_rate_limited_modal_jobs_once() -> dict[str, object]:
    if _processing_mode() != "modal":
        return {
            "status": "disabled",
            "message": "Modal retry scanning is disabled unless AUDIO_PROCESSING_MODE=modal.",
        }

    session = db.SessionLocal()
    try:
        logger.info("[MODAL RETRY SCAN] scanning for rate-limited Modal retries")
        transcription = _fetch_next_rate_limited_modal_job(session)
        if not transcription:
            return {
                "status": "idle",
                "message": "No rate-limited Modal retries are ready.",
            }

        logger.info(
            "[MODAL RETRY FOUND] transcription_id=%s modal_retry_at=%s",
            transcription.id,
            transcription.modal_retry_at,
        )
        transcription.processing_status = "processing"
        transcription.processing_error = None
        transcription.modal_dispatch_status = "rate_limited"
        if transcription.modal_job_type == "generate_tab":
            _set_manual_generation_status(transcription, "processing")
        session.add(transcription)
        session.commit()

        logger.info("[MODAL RETRY DISPATCHING] transcription_id=%s", transcription.id)
        _trigger_modal_worker(
            transcription.id,
            job_type=transcription.modal_job_type or "process",
            detection_sensitivity=None,
            track_id=None,
        )

        session.expire(transcription)
        session.refresh(transcription)

        if transcription.modal_dispatch_status == "dispatched":
            logger.info("[MODAL RETRY SUCCESS] transcription_id=%s", transcription.id)
        elif transcription.modal_dispatch_status == "rate_limited":
            logger.info(
                "[MODAL RETRY RATE LIMITED] transcription_id=%s retry_count=%s next_retry_at=%s",
                transcription.id,
                transcription.modal_retry_count,
                transcription.modal_retry_at,
            )
        else:
            logger.info(
                "[MODAL RETRY FAILED] transcription_id=%s modal_dispatch_status=%s",
                transcription.id,
                transcription.modal_dispatch_status,
            )

        return {
            "status": transcription.modal_dispatch_status,
            "transcription_id": transcription.id,
            "modal_retry_at": transcription.modal_retry_at,
            "modal_retry_count": transcription.modal_retry_count,
        }
    except Exception as exc:
        logger.exception("[MODAL RETRY FAILED] error scanning or dispatching rate-limited Modal jobs")
        return {"status": "failed", "error": str(exc)}
    finally:
        session.close()


def _trigger_modal_worker(
    transcription_id: int,
    job_type: str = "process",
    detection_sensitivity: str | None = None,
    track_id: int | None = None,
    lyrics_language: str | None = None,
) -> None:
    modal_trigger_url = core.config.settings.MODAL_TRIGGER_URL
    session = db.SessionLocal()

    def fail_track_reprocess(track: models.InstrumentTrack | None, message: str) -> None:
        if not track:
            return
        track.processing_status = "failed"
        track.confidence_notes = message
        session.add(track)

    try:
        transcription = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).first()
        if not transcription or transcription.is_deleted:
            _log_modal_dispatch_event(
                "skipped_missing_or_deleted",
                transcription_id=transcription_id,
                job_type=job_type,
            )
            logger.info(
                "Modal dispatch skipped because transcription %s is missing or deleted.",
                transcription_id,
            )
            return

        is_lyrics_job = job_type == "generate_lyrics"
        is_manual_generation_job = job_type == "generate_tab"
        is_track_reprocess_job = job_type == "reprocess_track"
        reprocess_track = None
        if is_track_reprocess_job:
            if track_id is None:
                logger.error(
                    "Modal track reprocess skipped for transcription %s because track_id is missing.",
                    transcription_id,
                )
                return
            reprocess_track = session.query(models.InstrumentTrack).filter(
                models.InstrumentTrack.id == track_id,
                models.InstrumentTrack.transcription_id == transcription.id,
            ).first()
            if not reprocess_track:
                logger.error(
                    "Modal track reprocess skipped for transcription %s because track %s was not found.",
                    transcription_id,
                    track_id,
                )
                return
            if reprocess_track.processing_status != "processing":
                logger.info(
                    "Skipping Modal track reprocess for transcription %s track %s with status %s.",
                    transcription_id,
                    track_id,
                    reprocess_track.processing_status,
                )
                return

        # Skip if in a terminal state. Lyrics jobs are allowed to run from
        # playback-ready terminal states because they have their own status.
        # Manual tab/rhythm jobs are also allowed from stem_ready because their
        # progress is tracked by tab_generation_status/rhythm_generation_status.
        if (
            not is_lyrics_job
            and not is_manual_generation_job
            and not is_track_reprocess_job
            and transcription.processing_status in {"completed", "completed_with_warning", "failed", "stem_ready"}
        ):
            logger.info(
                "Skipping Modal dispatch for transcription %s with terminal status %s.",
                transcription_id,
                transcription.processing_status,
            )
            return

        manual_generation_status = (
            (
                transcription.rhythm_generation_status
                if (transcription.selected_stem or "other").strip().lower() == "drums"
                else transcription.tab_generation_status
            )
            or "idle"
        )
        if (
            not is_lyrics_job
            and not is_manual_generation_job
            and not is_track_reprocess_job
            and transcription.processing_status != "processing"
        ):
            logger.info(
                "Skipping Modal dispatch for transcription %s with status %s.",
                transcription_id,
                transcription.processing_status,
            )
            return
        if is_manual_generation_job and manual_generation_status != "processing":
            logger.info(
                "Skipping Modal tab dispatch for transcription %s with generation status %s.",
                transcription_id,
                manual_generation_status,
            )
            return

        retry_at = _as_aware_utc(transcription.modal_retry_at)
        if retry_at and retry_at > datetime.now(timezone.utc):
            logger.info(
                "Skipping Modal dispatch for transcription %s until retry time %s.",
                transcription_id,
                retry_at,
            )
            return

        if (
            transcription.modal_dispatch_status == "dispatched"
            and transcription.modal_request_id
            and transcription.modal_job_type == job_type
        ):
            logger.info(
                "Skipping duplicate Modal dispatch for transcription %s request %s.",
                transcription_id,
                transcription.modal_request_id,
            )
            return

        if is_manual_generation_job and (transcription.selected_stem or "other").strip().lower() in {"bass", "other"}:
            try:
                resolved_source = resolve_generate_tab_audio_source(transcription)
            except ValueError as exc:
                _set_manual_generation_status(transcription, "failed")
                transcription.processing_status = "stem_ready"
                transcription.is_processed = True
                transcription.processing_error = str(exc)
                transcription.modal_dispatch_status = "failed"
                transcription.queue_position = None
                transcription.estimated_wait_time = None
                session.add(transcription)
                session.commit()
                return
            if resolved_source != transcription.separated_audio_url:
                _set_manual_generation_status(transcription, "failed")
                transcription.processing_status = "stem_ready"
                transcription.is_processed = True
                transcription.processing_error = "separated_audio_url is required for Modal tab generation."
                transcription.modal_dispatch_status = "failed"
                transcription.queue_position = None
                transcription.estimated_wait_time = None
                session.add(transcription)
                session.commit()
                return

        if not modal_trigger_url:
            if is_lyrics_job:
                transcription.lyrics_generation_status = "failed"
                transcription.processing_error = "Lyrics generation is not configured."
            elif is_manual_generation_job:
                _set_manual_generation_status(transcription, "failed")
                transcription.processing_status = "stem_ready"
                transcription.is_processed = True
                transcription.processing_error = (
                    "Modal processing is enabled but MODAL_TRIGGER_URL is not configured."
                )
                transcription.queue_position = None
                transcription.estimated_wait_time = None
            elif is_track_reprocess_job:
                fail_track_reprocess(
                    reprocess_track,
                    "Track reprocessing is not configured. Modal trigger URL is missing.",
                )
            else:
                transcription.processing_status = "failed"
                transcription.processing_error = (
                    "Modal processing is enabled but MODAL_TRIGGER_URL is not configured."
                )
                transcription.queue_position = None
                transcription.estimated_wait_time = None
            transcription.modal_dispatch_status = "failed"
            transcription.modal_job_type = job_type
            session.add(transcription)
            session.commit()
            logger.error(
                "AUDIO_PROCESSING_MODE=modal but MODAL_TRIGGER_URL is not configured; "
                "transcription %s failed instead of remaining queued.",
                transcription_id,
            )
            return

        transcription.modal_request_id = transcription.modal_request_id or str(uuid.uuid4())
        transcription.modal_job_type = job_type
        old_retry_at = transcription.modal_retry_at

        transcription.modal_dispatch_status = "dispatched"
        transcription.modal_dispatched_at = datetime.now(timezone.utc)
        transcription.modal_retry_at = None
        transcription.celery_task_id = None
        session.add(transcription)
        session.commit()
        session.refresh(transcription)
        _log_modal_dispatch_event("dispatch_started", transcription, job_type=job_type)

        headers = {}
        if core.config.settings.WORKER_API_TOKEN:
            headers["Authorization"] = f"Bearer {core.config.settings.WORKER_API_TOKEN}"

        response = httpx.post(
            modal_trigger_url,
            json=_build_worker_payload_for_modal(
                transcription,
                job_type=job_type,
                detection_sensitivity=detection_sensitivity,
                track_id=track_id,
                lyrics_language=lyrics_language,
            ),
            headers=headers,
            timeout=30.0,
        )

        logger.info(
            "Modal dispatch attempt: transcription_id=%s, job_type=%s, "
            "status_code=%s, retry_count=%s, retry_at=%s, modal_request_id=%s",
            transcription_id,
            job_type,
            response.status_code,
            transcription.modal_retry_count,
            old_retry_at,
            transcription.modal_request_id,
        )

        if response.status_code == 429:
            if is_lyrics_job:
                transcription.lyrics_generation_status = "failed"
                transcription.processing_error = (
                    "Lyrics generation is temporarily unavailable. Please retry later."
                )
                transcription.modal_dispatch_status = "rate_limited"
                transcription.modal_retry_at = None
                transcription.celery_task_id = None
                session.add(transcription)
                session.commit()
                logger.warning(
                    "Modal rate limited lyrics generation for transcription %s.",
                    transcription_id,
                )
                return
            if is_track_reprocess_job:
                fail_track_reprocess(
                    reprocess_track,
                    "Track reprocessing is temporarily unavailable. Please retry later.",
                )
                transcription.modal_dispatch_status = "rate_limited"
                transcription.modal_retry_at = None
                transcription.celery_task_id = None
                session.add(transcription)
                session.commit()
                logger.warning(
                    "Modal rate limited track reprocess for transcription %s track %s.",
                    transcription_id,
                    track_id,
                )
                return
            retry_after_header = response.headers.get("Retry-After")
            try:
                retry_after = int(retry_after_header) if retry_after_header else None
            except ValueError:
                retry_after = None

            _mark_modal_retry(
                transcription,
                session,
                error="Modal is rate limited. This job will retry automatically.",
                retry_after_seconds=retry_after,
                rate_limited=True,
            )
            logger.warning(
                "Modal rate limited transcription %s; queued retry.", transcription_id
            )
            # Metrics: rate limited job
            logger.info(
                "METRICS: modal_rate_limited_jobs_total +1"
            )
            return

        response.raise_for_status()
        logger.info("Triggered Modal worker for transcription %s", transcription_id)
        _log_modal_dispatch_event(
            "dispatch_completed",
            transcription,
            job_type=job_type,
            dispatch_status="dispatched",
            extra={"status_code": response.status_code},
        )
        # Metrics: successful dispatch
        logger.info(
            "METRICS: modal_successful_dispatches_total +1"
        )
    except Exception as exc:
        logger.exception(
            "Modal dispatch failed for transcription %s; scheduling retry if possible.",
            transcription_id,
        )
        # Metrics: failed dispatch
        logger.info(
            "METRICS: modal_failed_dispatches_total +1"
        )
        try:
            # Reload DB row to check current status before scheduling retry
            transcription = session.query(models.Transcription).filter(
                models.Transcription.id == transcription_id
            ).first()
            # Only schedule retry if still processing (not already failed/completed/etc.)
            if transcription and job_type == "generate_lyrics":
                transcription.lyrics_generation_status = "failed"
                transcription.processing_error = (
                    "Lyrics generation could not be started. Please retry later."
                )
                transcription.modal_dispatch_status = "failed"
                session.add(transcription)
                session.commit()
            elif transcription and job_type == "reprocess_track":
                track = None
                if track_id is not None:
                    track = session.query(models.InstrumentTrack).filter(
                        models.InstrumentTrack.id == track_id,
                        models.InstrumentTrack.transcription_id == transcription.id,
                    ).first()
                fail_track_reprocess(
                    track,
                    "Track reprocessing could not be started. Please retry later.",
                )
                transcription.modal_dispatch_status = "failed"
                session.add(transcription)
                session.commit()
            elif transcription and transcription.processing_status == "processing":
                _mark_modal_retry(
                    transcription,
                    session,
                    error="Modal dispatch failed. This job will retry automatically.",
                )
        except Exception:
            logger.exception(
                "Failed to mark Modal retry for transcription %s after dispatch error.",
                transcription_id,
            )
            session.rollback()
    finally:
        session.close()


def _dispatch_transcription_processing(
    transcription: models.Transcription,
    background_tasks: BackgroundTasks,
    db_session: Session,
) -> str | None:
    if transcription.processing_status != "processing":
        logger.info(
            "Transcription %s is queued; Modal/Celery dispatch skipped until it is promoted.",
            transcription.id,
        )
        return None

    mode = _processing_mode()
    if mode == "modal":
        if not _modal_trigger_url_configured():
            transcription.processing_status = "failed"
            transcription.processing_error = (
                "Modal processing is enabled but MODAL_TRIGGER_URL is not configured."
            )
            transcription.modal_dispatch_status = "failed"
            transcription.queue_position = None
            transcription.estimated_wait_time = None
            db_session.add(transcription)
            db_session.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Modal processing is enabled but MODAL_TRIGGER_URL is not configured.",
            )
        logger.info("Dispatching transcription %s to Modal", transcription.id)
        job_type = transcription.modal_job_type or "process"
        background_tasks.add_task(_trigger_modal_worker, transcription.id, job_type, None, None)
        return None
    if mode == "local":
        logger.info("Dispatching transcription %s to local processing", transcription.id)
        transcription.modal_dispatch_status = None
        db_session.add(transcription)
        db_session.commit()
        return _start_transcription_processing(transcription.id, background_tasks, db_session)
    if mode == "disabled":
        transcription.processing_status = "failed"
        transcription.processing_error = "Audio processing is disabled by AUDIO_PROCESSING_MODE=disabled."
        transcription.modal_dispatch_status = "failed"
        transcription.queue_position = None
        transcription.estimated_wait_time = None
        db_session.add(transcription)
        db_session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audio processing is disabled by AUDIO_PROCESSING_MODE=disabled.",
        )

    raise ValueError("Invalid AUDIO_PROCESSING_MODE")


def _active_transcription_query(db_session: Session):
    return (
        db_session.query(models.Transcription)
        .filter(models.Transcription.is_deleted == False)
        .filter(models.Transcription.processing_status.in_(ACTIVE_TRANSCRIPTION_STATUSES))
    )


def _stale_active_cutoff() -> datetime:
    timeout_seconds = max(0, int(core.config.settings.STALE_TRANSCRIPTION_TIMEOUT_SECONDS))
    return datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if not value:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _active_celery_task_ids() -> set[str] | None:
    try:
        active = celery_app.control.inspect(timeout=1.0).active() or {}
    except Exception as exc:
        logger.info("Could not inspect active Celery tasks during stale cleanup: %s", exc)
        return None

    task_ids: set[str] = set()
    for tasks in active.values():
        for task in tasks or []:
            task_id = task.get("id") if isinstance(task, dict) else None
            if task_id:
                task_ids.add(str(task_id))
    return task_ids


def _cleanup_stale_active_transcription_jobs(db_session: Session) -> int:
    cutoff = _stale_active_cutoff()
    active_task_ids = set() if _processing_mode() == "modal" else _active_celery_task_ids()
    active_jobs = (
        db_session.query(models.Transcription)
        .filter(models.Transcription.is_deleted == False)
        .filter(models.Transcription.processing_status.in_(ACTIVE_TRANSCRIPTION_STATUSES))
        .all()
    )
    stale_jobs = []
    for transcription in active_jobs:
        if (
            active_task_ids is not None
            and transcription.celery_task_id
            and str(transcription.celery_task_id) in active_task_ids
        ):
            logger.info(
                "Skipping stale cleanup for transcription %s because Celery task %s is active",
                transcription.id,
                transcription.celery_task_id,
            )
            continue

        last_activity = (
            _as_aware_utc(transcription.modal_dispatched_at)
            or _as_aware_utc(transcription.updated_at)
            or _as_aware_utc(transcription.created_at)
        )
        if not last_activity:
            logger.info(
                "Skipping stale cleanup for transcription %s because no timestamp is available",
                transcription.id,
            )
            continue
        if last_activity >= cutoff:
            continue
        stale_jobs.append(transcription)
    if not stale_jobs:
        return 0

    for transcription in stale_jobs:
        transcription.processing_status = "failed"
        transcription.processing_error = (
            "Processing job timed out without worker activity and was marked failed."
        )
        transcription.queue_position = None
        transcription.estimated_wait_time = None
        transcription.celery_task_id = None
        transcription.modal_dispatch_status = "failed"
        transcription.modal_retry_at = None
        transcription.is_processed = False
        db_session.add(transcription)

    db_session.commit()
    logger.warning("Marked %s stale transcription job(s) failed.", len(stale_jobs))
    return len(stale_jobs)


def _promote_oldest_queued_transcription(db_session: Session) -> models.Transcription | None:
    with _queue_promotion_lock:
        candidate = (
            db_session.query(models.Transcription)
            .filter(models.Transcription.processing_status.in_(QUEUE_WAITING_STATUSES))
            .filter(models.Transcription.is_deleted == False)
            .filter(or_(
                models.Transcription.modal_retry_at == None,
                models.Transcription.modal_retry_at <= datetime.now(timezone.utc),
            ))
            .order_by(models.Transcription.created_at.asc(), models.Transcription.id.asc())
            .first()
        )
        if not candidate:
            return None

        active_exists = (
            db_session.query(models.Transcription.id)
            .filter(models.Transcription.processing_status == "processing")
            .filter(models.Transcription.is_deleted == False)
            .exists()
        )
        result = db_session.execute(
            update(models.Transcription)
            .where(models.Transcription.id == candidate.id)
            .where(models.Transcription.processing_status.in_(QUEUE_WAITING_STATUSES))
            .where(models.Transcription.is_deleted == False)
            .where(~active_exists)
            .values(
                processing_status="processing",
                queue_position=0,
                estimated_wait_time=0,
                processing_error=None,
                modal_dispatch_status=None,
            ),
            execution_options={"synchronize_session": False},
        )
        if result.rowcount != 1:
            db_session.rollback()
            logger.info(
                "Transcription %s stayed queued because another job is already processing.",
                candidate.id,
            )
            return None

        db_session.commit()
        db_session.refresh(candidate)
        logger.info("Promoted queued transcription %s to processing", candidate.id)
        return candidate


def _trigger_next_queued_transcription(
    background_tasks: BackgroundTasks,
    db_session: Session,
) -> models.Transcription | None:
    promoted = _promote_oldest_queued_transcription(db_session)
    if not promoted:
        return None

    task_id = _dispatch_transcription_processing(promoted, background_tasks, db_session)
    if task_id:
        promoted.celery_task_id = task_id
        db_session.add(promoted)
        db_session.commit()
        db_session.refresh(promoted)
    return promoted


def _start_instrument_track_reprocess(
    transcription_id: int,
    track_id: int,
    background_tasks: BackgroundTasks,
):
    """Start one track reprocess by dispatching Modal or local Celery when available."""
    mode = _processing_mode()
    if mode == "local":
        if _celery_has_available_worker():
            celery_app.send_task("app.tasks.reprocess_instrument_track", args=[track_id])
            return
        background_tasks.add_task(_run_instrument_track_reprocess_locally, track_id)
        return
    if mode == "disabled":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audio processing is disabled by AUDIO_PROCESSING_MODE=disabled.",
        )
    if not _modal_trigger_url_configured():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Modal processing is enabled but MODAL_TRIGGER_URL is not configured.",
        )

    background_tasks.add_task(
        _trigger_modal_worker,
        transcription_id,
        "reprocess_track",
        None,
        track_id,
    )


def _has_note_events(notes_data: str | None) -> bool:
    return tablature.has_note_events(notes_data)


def _ensure_structured_tablature_repaired(
    transcription: models.Transcription,
    db_session: Session,
) -> bool:
    selected_stem = (transcription.selected_stem or "other").strip().lower()
    if selected_stem not in {"bass", "other"}:
        return False
    if (transcription.tab_generation_status or "idle") == "processing":
        return False
    if tablature.has_structured_tablature(transcription.tablature_data):
        return False

    try:
        repaired = tablature.repair_structured_tablature(
            selected_stem,
            transcription.notes_data,
            transcription.tablature_data,
        )
    except Exception:
        logger.exception(
            "structured_tablature_repair_failed transcription_id=%s selected_stem=%s",
            transcription.id,
            selected_stem,
        )
        if (
            _has_note_events(transcription.notes_data)
            and (transcription.tab_generation_status or "idle") == "completed"
        ):
            transcription.tab_generation_status = "completed_with_warning"
            transcription.processing_status = "stem_ready"
            transcription.can_generate_score = False
            message = (
                "Tab generation completed with note events, but structured "
                "tablature could not be assembled."
            )
            transcription.warning_message = transcription.warning_message or message
            transcription.processing_error = transcription.processing_error or message
            db_session.add(transcription)
            db_session.commit()
            db_session.refresh(transcription)
            return True
        return False

    if not repaired:
        if (
            _has_note_events(transcription.notes_data)
            and (transcription.tab_generation_status or "idle") == "completed"
        ):
            transcription.tab_generation_status = "completed_with_warning"
            transcription.processing_status = "stem_ready"
            transcription.can_generate_score = False
            message = (
                "Tab generation completed with note events, but structured "
                "tablature could not be assembled."
            )
            transcription.warning_message = transcription.warning_message or message
            transcription.processing_error = transcription.processing_error or message
            db_session.add(transcription)
            db_session.commit()
            db_session.refresh(transcription)
            return True
        return False

    transcription.tablature_data = json.dumps(repaired)
    if tablature.has_structured_tablature(transcription.tablature_data):
        instrument_type = "bass" if selected_stem == "bass" else "guitar"
        selected_track = (
            db_session.query(models.InstrumentTrack)
            .filter(
                models.InstrumentTrack.transcription_id == transcription.id,
                models.InstrumentTrack.instrument_type == instrument_type,
            )
            .first()
        )
        if selected_track and not tablature.has_structured_tablature(selected_track.tab_json):
            selected_track.tab_json = transcription.tablature_data
            selected_track.notes_json = selected_track.notes_json or transcription.notes_data
            if selected_track.processing_status in {None, "completed_with_warning", "failed"}:
                selected_track.processing_status = "completed"
            db_session.add(selected_track)
        transcription.can_generate_score = True
        if (transcription.tab_generation_status or "idle") == "completed_with_warning":
            transcription.tab_generation_status = "completed"
        if transcription.processing_error and "structured tablature" in transcription.processing_error:
            transcription.processing_error = None
        db_session.add(transcription)
        db_session.commit()
        db_session.refresh(transcription)
        return True
    return False


def _notes_error(notes_data: str | None) -> str | None:
    if not notes_data:
        return None
    try:
        parsed = json.loads(notes_data)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict) and parsed.get("error"):
        return str(parsed["error"])
    return None


def _is_non_blocking_processing_warning(error: str | None) -> bool:
    """Warnings stored in processing_error should not make the whole job fail."""
    if not error:
        return False
    return error.startswith("Source separation unavailable; processed the full mix instead.")


def _validate_selected_stem(selected_stem: str | None) -> str:
    if not selected_stem:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Please choose one target stem before processing.",
        )
    normalized = selected_stem.strip().lower()
    if normalized not in VALID_SELECTED_STEMS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "selected_stem must be one of: vocals, drums, bass, other. "
                "Use other for the MVP guitar/piano/melody target."
            ),
        )
    return normalized


def _validate_lyrics_language(language: str | None) -> str:
    normalized = (language or "auto").strip().lower()
    if not normalized:
        return "auto"
    if normalized not in VALID_LYRICS_LANGUAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="lyrics language must be one of: auto, en, tl, ceb, es, ja, ko",
        )
    return normalized


def _hash_bytes(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _normalize_youtube_id(url: str) -> str | None:
    parsed = urlsplit(url.strip())
    hostname = (parsed.hostname or "").lower()

    if hostname.endswith("youtu.be"):
        video_id = parsed.path.strip("/").split("/")[0]
        return video_id or None

    if "youtube.com" in hostname:
        query_video_id = parse_qs(parsed.query).get("v", [None])[0]
        if query_video_id:
            return query_video_id

        parts = [part for part in parsed.path.split("/") if part]
        for prefix in ("shorts", "embed", "live"):
            if prefix in parts:
                index = parts.index(prefix)
                if len(parts) > index + 1:
                    return parts[index + 1]

    return None


def _find_duplicate_transcription(
    db_session: Session,
    *,
    user_id: int,
    selected_stem: str,
    audio_hash: str | None = None,
    normalized_source_id: str | None = None,
) -> models.Transcription | None:
    query = (
        db_session.query(models.Transcription)
        .filter(models.Transcription.user_id == user_id)
        .filter(models.Transcription.selected_stem == selected_stem)
        .filter(models.Transcription.processing_status.in_(["stem_ready", "completed", "completed_with_warning"]))
        .filter(models.Transcription.is_processed == True)
        .filter(models.Transcription.is_deleted == False)
    )
    if audio_hash:
        query = query.filter(models.Transcription.audio_hash == audio_hash)
    elif normalized_source_id:
        query = query.filter(models.Transcription.normalized_source_id == normalized_source_id)
    else:
        return None

    return query.order_by(models.Transcription.created_at.desc(), models.Transcription.id.desc()).first()


def _mark_duplicate_response(transcription: models.Transcription) -> models.Transcription:
    transcription.duplicate_reused = True
    transcription.duplicate_message = (
        "This song and stem were already processed. Existing result was loaded."
    )
    return transcription


def _upload_original_audio(file_path: str, transcription_id: int) -> dict[str, str] | None:
    return storage.safe_upload_file(
        file_path,
        folder=f"transcriptions/{transcription_id}/original",
        resource_type="auto",
    )


def _delete_local_file(path_value: str | None) -> None:
    if not path_value:
        return
    try:
        normalized = storage.normalize_local_path(path_value)
        path = Path(normalized)
        if path.exists() and path.is_file():
            path.unlink()
    except OSError as exc:
        logger.warning("Local cleanup failed for %s: %s", path_value, exc)


def _transcription_scratch_dir(transcription_id: int) -> Path:
    scratch_dir = Path(tempfile.gettempdir()) / "transcriptions" / str(transcription_id)
    scratch_dir.mkdir(parents=True, exist_ok=True)
    return scratch_dir


def _file_lifecycle_snapshot(path_value: str | Path | None) -> dict:
    if not path_value:
        return {"path": None, "exists": False}
    path = Path(storage.normalize_local_path(path_value))
    snapshot = {"path": storage.normalize_local_path(path), "exists": path.exists()}
    if path.exists():
        try:
            stat = path.stat()
            snapshot.update({
                "is_file": path.is_file(),
                "size": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        except OSError as exc:
            snapshot["stat_error"] = str(exc)
    return snapshot


def _move_source_to_transcription_scratch(
    transcription: models.Transcription,
    source_path: str | Path,
    db_session: Session,
) -> Path:
    source = Path(storage.normalize_local_path(source_path))
    scratch_dir = _transcription_scratch_dir(transcription.id)
    destination = scratch_dir / f"original{source.suffix or '.wav'}"
    logger.info(
        "Moving source audio into transcription scratch dir transcription_id=%s source=%s destination=%s",
        transcription.id,
        _file_lifecycle_snapshot(source),
        storage.normalize_local_path(destination),
    )
    if not source.exists():
        logger.error(
            "Source audio missing before scratch move transcription_id=%s source=%s",
            transcription.id,
            _file_lifecycle_snapshot(source),
        )
        raise FileNotFoundError(
            f"Source audio does not exist: {storage.normalize_local_path(source)}"
        )
    if source.resolve() != destination.resolve():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
    transcription.audio_file_path = storage.normalize_local_path(destination)
    db_session.add(transcription)
    db_session.commit()
    db_session.refresh(transcription)
    logger.info(
        "Source audio scratch move complete transcription_id=%s file=%s",
        transcription.id,
        _file_lifecycle_snapshot(destination),
    )
    return destination


def _cloudinary_asset_specs(transcription: models.Transcription):
    return [
        (
            "original_audio_public_id",
            transcription.original_audio_public_id,
            "video",
        ),
        (
            "separated_audio_public_id",
            transcription.separated_audio_public_id,
            "video",
        ),
        (
            "midi_file_public_id",
            transcription.midi_file_public_id,
            "raw",
        ),
        (
            "tab_file_public_id",
            transcription.tab_file_public_id,
            "raw",
        ),
    ]


def _cloudinary_asset_is_referenced(
    db_session: Session,
    *,
    public_id: str,
    resource_type: str,
    excluded_transcription_ids: set[int],
) -> bool:
    fields = (
        [
            models.Transcription.original_audio_public_id,
            models.Transcription.separated_audio_public_id,
        ]
        if resource_type == "video"
        else [
            models.Transcription.midi_file_public_id,
            models.Transcription.tab_file_public_id,
        ]
    )
    query = db_session.query(models.Transcription.id).filter(
        or_(*(field == public_id for field in fields))
    )
    if excluded_transcription_ids:
        query = query.filter(~models.Transcription.id.in_(excluded_transcription_ids))
    return db_session.query(query.exists()).scalar()


def _cleanup_transcription_cloudinary_assets(
    transcription: models.Transcription,
    db_session: Session | None = None,
    *,
    excluded_transcription_ids: set[int] | None = None,
) -> None:
    excluded_ids = excluded_transcription_ids or {transcription.id}
    deleted_or_attempted: set[tuple[str, str]] = set()
    for field_name, public_id, resource_type in _cloudinary_asset_specs(transcription):
        if not public_id:
            logger.info(
                "Cloudinary asset missing for transcription %s field %s",
                transcription.id,
                field_name,
            )
            storage.delete_cloudinary_asset(public_id, resource_type=resource_type)
            continue
        asset_key = (public_id, resource_type)
        if asset_key in deleted_or_attempted:
            logger.info(
                "Cloudinary asset skipped for transcription %s field %s public_id %s; already handled",
                transcription.id,
                field_name,
                public_id,
            )
            continue
        if db_session is not None and _cloudinary_asset_is_referenced(
            db_session,
            public_id=public_id,
            resource_type=resource_type,
            excluded_transcription_ids=excluded_ids,
        ):
            logger.info(
                "Cloudinary asset skipped for transcription %s field %s public_id %s; still referenced",
                transcription.id,
                field_name,
                public_id,
            )
            continue
        storage.delete_cloudinary_asset(public_id, resource_type=resource_type)
        deleted_or_attempted.add(asset_key)


def _cleanup_transcriptions_cloudinary_assets(
    transcriptions: list[models.Transcription],
    db_session: Session,
) -> None:
    excluded_ids = {transcription.id for transcription in transcriptions}
    deleted_or_attempted: set[tuple[str, str]] = set()
    for transcription in transcriptions:
        for field_name, public_id, resource_type in _cloudinary_asset_specs(transcription):
            if not public_id:
                logger.info(
                    "Cloudinary asset missing for transcription %s field %s",
                    transcription.id,
                    field_name,
                )
                storage.delete_cloudinary_asset(public_id, resource_type=resource_type)
                continue
            asset_key = (public_id, resource_type)
            if asset_key in deleted_or_attempted:
                logger.info(
                    "Cloudinary asset skipped for transcription %s field %s public_id %s; already handled",
                    transcription.id,
                    field_name,
                    public_id,
                )
                continue
            if _cloudinary_asset_is_referenced(
                db_session,
                public_id=public_id,
                resource_type=resource_type,
                excluded_transcription_ids=excluded_ids,
            ):
                logger.info(
                    "Cloudinary asset skipped for transcription %s field %s public_id %s; still referenced",
                    transcription.id,
                    field_name,
                    public_id,
                )
                continue
            storage.delete_cloudinary_asset(public_id, resource_type=resource_type)
            deleted_or_attempted.add(asset_key)


def _revoke_transcription_task(transcription: models.Transcription) -> None:
    if not transcription.celery_task_id:
        return
    try:
        celery_app.control.revoke(
            transcription.celery_task_id,
            terminate=transcription.processing_status == "processing",
        )
    except Exception as exc:
        logger.warning(
            "Could not revoke Celery task %s for transcription %s: %s",
            transcription.celery_task_id,
            transcription.id,
            exc,
        )


def _soft_delete_transcription(
    transcription: models.Transcription,
    db_session: Session,
) -> models.Transcription:
    if transcription.is_demo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Demo transcriptions are shared examples and cannot be deleted.",
        )

    previous_status = transcription.processing_status or "pending"
    if previous_status in ACTIVE_TRANSCRIPTION_STATUSES:
        _revoke_transcription_task(transcription)
        transcription.processing_status = "cancelled"
        transcription.processing_error = (
            "Transcription was deleted. Active worker cancellation is best-effort."
            if previous_status == "processing"
            else "Transcription was deleted before processing completed."
        )
    elif previous_status in TERMINAL_TRANSCRIPTION_STATUSES:
        transcription.processing_status = "deleted"
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete transcription in {previous_status} state",
        )

    _cleanup_transcription_cloudinary_assets(transcription, db_session)
    if previous_status == "processing":
        logger.info(
            "Skipping immediate local cleanup for deleted processing transcription %s; active worker cleanup is best-effort",
            transcription.id,
        )
    else:
        _cleanup_transcription_local_assets(transcription)

    transcription.is_deleted = True
    transcription.deleted_at = datetime.now(timezone.utc)
    transcription.is_processed = False if transcription.processing_status == "cancelled" else transcription.is_processed
    transcription.queue_position = None
    transcription.estimated_wait_time = None
    transcription.celery_task_id = None
    db_session.add(transcription)
    db_session.commit()
    db_session.refresh(transcription)

    return transcription


def _cleanup_transcription_local_assets(transcription: models.Transcription) -> None:
    if (
        transcription.processing_status == "processing"
        and transcription.celery_task_id
        and str(transcription.celery_task_id) in _active_celery_task_ids()
    ):
        logger.info(
            "Skipping local cleanup for transcription %s because Celery task %s is active",
            transcription.id,
            transcription.celery_task_id,
        )
        return

    for path_value in [
        transcription.audio_file_path,
        transcription.preprocessed_audio_file_path,
        transcription.separated_audio_file_path,
        transcription.midi_file_path,
        transcription.tab_file_path,
    ]:
        _delete_local_file(path_value)

    for track in transcription.instrument_tracks:
        _delete_local_file(track.stem_audio_path)


def _hard_delete_transcription(
    transcription: models.Transcription,
    db_session: Session,
) -> None:
    _cleanup_transcription_cloudinary_assets(transcription, db_session)
    _cleanup_transcription_local_assets(transcription)
    db_session.delete(transcription)
    db_session.commit()


def _delete_project_with_transcriptions(
    project: models.Project,
    db_session: Session,
    *,
    hard_delete: bool = True,
):
    transcriptions = (
        db_session.query(models.Transcription)
        .filter(models.Transcription.project_id == project.id)
        .all()
    )
    for transcription in transcriptions:
        if transcription.processing_status in {"queued", "pending", "processing"}:
            _revoke_transcription_task(transcription)

    _cleanup_transcriptions_cloudinary_assets(transcriptions, db_session)
    for transcription in transcriptions:
        _cleanup_transcription_local_assets(transcription)

    project_payload = {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "owner_id": project.owner_id,
        "is_public": project.is_public,
        "is_deleted": project.is_deleted,
        "deleted_at": project.deleted_at,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }

    if hard_delete:
        for transcription in transcriptions:
            db_session.delete(transcription)
        db_session.delete(project)
    else:
        deletion_time = datetime.now(timezone.utc)
        for transcription in transcriptions:
            previous_status = transcription.processing_status or "pending"
            transcription.processing_status = (
                "cancelled"
                if previous_status in {"queued", "pending", "processing"}
                else "deleted"
            )
            transcription.is_deleted = True
            transcription.deleted_at = deletion_time
            transcription.is_processed = (
                False
                if transcription.processing_status == "cancelled"
                else transcription.is_processed
            )
            db_session.add(transcription)
        project.is_deleted = True
        project.deleted_at = deletion_time
        db_session.add(project)

    db_session.commit()
    if not hard_delete:
        db_session.refresh(project)
        return project
    return project_payload


def _should_use_local_worker_fallback() -> bool:
    return core.config.settings.ENVIRONMENT.lower() in {"development", "local", "test"}


def _celery_has_available_worker() -> bool:
    """Return True only when a worker answers quickly enough for local requests."""
    try:
        return bool(celery_app.control.ping(timeout=0.5))
    except Exception as e:
        logger.warning("Celery worker check failed; using local background task: %s", e)
        return False


def _blocking_processing_error(transcription: models.Transcription) -> str | None:
    error = transcription.processing_error
    if transcription.processing_status in {"pending", "queued", "processing"}:
        return None
    if (
        transcription.lyrics_generation_status in {"failed", "completed_with_warning"}
        and transcription.processing_status not in {"failed"}
    ):
        return None
    if transcription.modal_dispatch_status in {"rate_limited", "retry_queued"}:
        return None
    if _is_non_blocking_processing_warning(error):
        return None
    return error


def _can_play_stem(transcription: models.Transcription) -> bool:
    if transcription.can_play_stem or transcription.separated_audio_url:
        return True
    if transcription.separated_audio_file_path and os.path.exists(
        storage.normalize_local_path(transcription.separated_audio_file_path)
    ):
        return True
    return any(
        track.stem_audio_path and os.path.exists(storage.normalize_local_path(track.stem_audio_path))
        for track in transcription.instrument_tracks
    )


def _has_stem_audio_reference(transcription: models.Transcription) -> bool:
    return bool(
        transcription.separated_audio_url
        or transcription.separated_audio_file_path
        or any(track.stem_audio_path for track in transcription.instrument_tracks)
    )


def _is_viewable_stem_ready(transcription: models.Transcription) -> bool:
    return bool(
        transcription.processing_status == "stem_ready"
        and _can_play_stem(transcription)
        and _has_stem_audio_reference(transcription)
    )


def _can_generate_score(transcription: models.Transcription) -> bool:
    selected_stem = (transcription.selected_stem or "other").lower()
    return bool(
        selected_stem in {"other", "bass"}
        and transcription.can_generate_score
        and _has_note_events(transcription.notes_data)
    )


def _available_exports(transcription: models.Transcription) -> list[str]:
    selected_stem = (transcription.selected_stem or "other").lower()
    if selected_stem not in {"other", "bass"}:
        return []

    exports: list[str] = []
    if transcription.midi_file_url or transcription.midi_file_path:
        exports.append("midi")
    if _has_tablature_events(transcription.tablature_data):
        exports.append("tab")
    if transcription.notation_data:
        exports.append("musicxml")
    return exports


def _json_field(value: str | None):
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def _has_tablature_events(value: str | None) -> bool:
    return tablature.has_structured_tablature(value)


def _has_score_output(transcription: models.Transcription) -> bool:
    selected_stem = (transcription.selected_stem or "other").lower()
    if selected_stem == "drums":
        return _has_drum_hits(transcription.notes_data)
    if selected_stem == "vocals":
        return False
    return bool(
        _has_note_events(transcription.notes_data)
        or _has_tablature_events(transcription.tablature_data)
        or transcription.notation_data
        or transcription.midi_file_path
        or transcription.midi_file_url
        or transcription.tab_file_path
        or transcription.tab_file_url
    )


def _is_playback_only_stem_state(transcription: models.Transcription) -> bool:
    return bool(
        _can_play_stem(transcription)
        and _has_stem_audio_reference(transcription)
        and not _has_score_output(transcription)
    )


def _repair_playback_only_stem_ready(
    transcription: models.Transcription,
    db_session: Session,
) -> bool:
    if not _is_playback_only_stem_state(transcription):
        return False
    if transcription.processing_status not in {"pending", "queued", "processing"}:
        return False

    transcription.processing_status = "stem_ready"
    transcription.is_processed = True
    transcription.processing_error = None
    transcription.can_play_stem = True
    transcription.can_generate_score = False
    transcription.queue_position = None
    transcription.estimated_wait_time = None
    transcription.celery_task_id = None
    db_session.add(transcription)
    db_session.commit()
    db_session.refresh(transcription)
    return True


def _repair_completed_manual_generation_status(
    transcription: models.Transcription,
    db_session: Session,
) -> bool:
    """Recover rows where TAB/rhythm generation finished but main status stayed active."""
    if transcription.processing_status not in {"pending", "queued", "processing"}:
        return False

    selected_stem = (transcription.selected_stem or "other").strip().lower()
    if selected_stem == "drums":
        generation_status = transcription.rhythm_generation_status or "idle"
        has_output = _has_drum_hits(transcription.notes_data)
    elif selected_stem in {"bass", "other"}:
        generation_status = transcription.tab_generation_status or "idle"
        has_output = bool(
            _has_note_events(transcription.notes_data)
            or _has_tablature_events(transcription.tablature_data)
            or transcription.midi_file_path
            or transcription.midi_file_url
            or transcription.tab_file_path
            or transcription.tab_file_url
            or transcription.notation_data
        )
    else:
        return False

    if generation_status not in {"completed", "completed_with_warning", "failed"}:
        return False
    if not (has_output or _can_play_stem(transcription)):
        return False

    transcription.processing_status = (
        "completed"
        if generation_status == "completed" and has_output
        else "stem_ready"
    )
    transcription.is_processed = True
    transcription.can_play_stem = _can_play_stem(transcription)
    if selected_stem in {"bass", "other"}:
        transcription.can_generate_score = bool(
            generation_status == "completed"
            and _has_note_events(transcription.notes_data)
            and _has_tablature_events(transcription.tablature_data)
        )
    else:
        transcription.can_generate_score = False
    if generation_status in {"completed", "completed_with_warning"}:
        transcription.processing_error = None
    transcription.queue_position = None
    transcription.estimated_wait_time = None
    transcription.celery_task_id = None
    db_session.add(transcription)
    db_session.commit()
    db_session.refresh(transcription)
    return True


def _has_drum_hits(value: str | None) -> bool:
    parsed = _json_field(value)
    return bool(
        isinstance(parsed, dict) and
        isinstance(parsed.get("drum_hits"), list) and
        parsed.get("drum_hits")
    )


def _duration_from_json(notes_data: str | None, tablature_data: str | None) -> int:
    candidates: list[float] = []

    def collect(items) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            start = item.get("startTime", item.get("onset", 0)) or 0
            duration = item.get("duration", 0) or 0
            end = item.get("offset", None)
            try:
                end_value = float(end) if end is not None else float(start) + float(duration)
            except (TypeError, ValueError):
                continue
            if end_value > 0:
                candidates.append(end_value)

    parsed_notes = _json_field(notes_data)
    if isinstance(parsed_notes, list):
        collect(parsed_notes)
    elif isinstance(parsed_notes, dict):
        collect(parsed_notes.get("notes"))
        collect(parsed_notes.get("pitch_info"))
        collect(parsed_notes.get("drum_hits"))
        rhythm_analysis = parsed_notes.get("rhythm_analysis")
        if isinstance(rhythm_analysis, dict):
            try:
                total_duration = float(rhythm_analysis.get("total_duration") or 0)
                if total_duration > 0:
                    candidates.append(total_duration)
            except (TypeError, ValueError):
                pass

    parsed_tab = _json_field(tablature_data)
    if isinstance(parsed_tab, dict):
        collect(parsed_tab.get("tablature"))

    return int(max(candidates, default=0) + 0.999) if candidates else 0


def _import_type(transcription: models.Transcription) -> str | None:
    source_type = (transcription.source_type or "").lower()
    if "midi" in source_type:
        return "midi"
    if "gp" in source_type or "guitar_pro" in source_type:
        return "gp5"
    if "tab" in source_type:
        return "tab"
    return None


def _instrument_type_for(transcription: models.Transcription) -> str:
    selected_stem = (transcription.selected_stem or "other").lower()
    if selected_stem == "bass":
        return "Bass Guitar"
    if selected_stem == "drums":
        return "Percussion"
    if selected_stem == "vocals":
        return "Vocal Stem"
    return "Guitar/Accompaniment"


def _tuning_for(transcription: models.Transcription) -> str | None:
    selected_stem = (transcription.selected_stem or "other").lower()
    if selected_stem == "bass":
        return "E A D G"
    if selected_stem == "other":
        return "E A D G B E"
    return None


def _metadata_payload(transcription: models.Transcription) -> dict:
    selected_stem = (transcription.selected_stem or "other").lower()
    import_type = _import_type(transcription)
    track_count = len(transcription.instrument_tracks or [])
    has_drum_hits = _has_drum_hits(transcription.notes_data)
    can_generate_tab = (
        selected_stem in {"other", "bass"}
        and _has_tablature_events(transcription.tablature_data)
    )
    can_generate_rhythm = selected_stem == "drums" and (
        has_drum_hits
        or (
            transcription.processing_status == "stem_ready"
            and _can_play_stem(transcription)
            and _has_stem_audio_reference(transcription)
        )
    )
    can_generate_score = _can_generate_score(transcription)
    can_play_stem = _can_play_stem(transcription)
    output_mode = (
        "rhythm" if has_drum_hits else
        "tab_score" if can_generate_tab and can_generate_score else
        "tab" if can_generate_tab else
        "score" if can_generate_score else
        "playback_only" if can_play_stem else
        "metadata_only"
    )
    calculated_duration = _duration_from_json(transcription.notes_data, transcription.tablature_data)

    return {
        "selected_stem": selected_stem,
        "separated_audio_url": transcription.separated_audio_url,
        "warning_message": transcription.warning_message,
        "tab_generation_status": transcription.tab_generation_status or "idle",
        "rhythm_generation_status": transcription.rhythm_generation_status or "idle",
        "available_exports": _available_exports(transcription),
        "instrument_type": _instrument_type_for(transcription),
        "output_mode": output_mode,
        "can_generate_tab": can_generate_tab,
        "can_generate_score": can_generate_score,
        "can_generate_rhythm": can_generate_rhythm,
        "can_play_stem": can_play_stem,
        "track_count": track_count,
        "tuning": _tuning_for(transcription),
        "import_type": import_type,
        "duration": transcription.duration or calculated_duration or None,
    }


def _status_payload(
    transcription: models.Transcription,
    transcription_id: int,
    selected_stem: str,
    *,
    message: str | None = None,
) -> dict:
    warning = transcription.warning_message
    metadata = _metadata_payload(transcription)
    payload = {
        "status": transcription.processing_status or "completed",
        "warning": warning,
        "transcription_id": transcription_id,
        **metadata,
        "warning_message": warning,
        "lyrics_generation_status": transcription.lyrics_generation_status,
        "lyrics_data": transcription.lyrics_data,
        "is_demo": transcription.is_demo,
        "queue_position": transcription.queue_position,
        "estimated_wait_time": transcription.estimated_wait_time,
        "modal_dispatch_status": transcription.modal_dispatch_status,
        "modal_status_detail": _modal_status_detail(transcription),
        "modal_job_type": transcription.modal_job_type,
        "modal_request_id": transcription.modal_request_id,
        "modal_retry_count": transcription.modal_retry_count,
        "modal_retry_at": transcription.modal_retry_at,
        "notes_data": transcription.notes_data,
        "tablature_data": transcription.tablature_data,
        "midi_file_url": transcription.midi_file_url,
        "tab_file_url": transcription.tab_file_url,
    }
    if message:
        payload["message"] = message
    elif (
        transcription.processing_status == "queued"
        and transcription.modal_dispatch_status in {"rate_limited", "retry_queued"}
    ):
        payload["message"] = "Waiting for Modal capacity. Retry scheduled."
    elif transcription.processing_status == "stem_ready":
        payload["message"] = STEM_READY_MESSAGE
    return _finalize_status_response_for_mode(payload)


def _finalize_status_response_for_mode(payload: dict) -> dict:
    """Apply response-only local mode masking without mutating stored rows."""
    if _processing_mode() != "local":
        return payload

    local_payload = dict(payload)
    if local_payload.get("status") == "queued":
        local_payload["message"] = "Queued for local processing."

    message = local_payload.get("message")
    if isinstance(message, str) and "Modal" in message:
        local_payload["message"] = (
            "Queued for local processing."
            if local_payload.get("status") == "queued"
            else local_payload.get("message")
        )

    if local_payload.get("modal_dispatch_status") == "modal_required":
        local_payload["modal_dispatch_status"] = None
        local_payload["modal_retry_at"] = None

    return local_payload


@router.post("/modal-retry")
async def manual_retry_rate_limited_modal_jobs(
    request: Request,
):
    admin_token = core.config.settings.MODAL_RETRY_ADMIN_TOKEN
    if not admin_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Modal retry endpoint is not configured.",
        )

    provided_token = request.headers.get("X-Modal-Retry-Token")
    if provided_token != admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin retry token",
        )

    return retry_rate_limited_modal_jobs_once()


def _public_transcription_payload(transcription: models.Transcription) -> dict:
    """Serialize while keeping local demo filesystem paths out of browser playback fields."""
    payload = schemas.TranscriptionInDB.model_validate(transcription).model_dump(mode="json")
    payload.update(_metadata_payload(transcription))
    if transcription.is_demo:
        payload["source_url"] = DEMO_AUDIO_URL
        payload["original_audio_url"] = DEMO_AUDIO_URL
        payload["separated_audio_url"] = DEMO_AUDIO_URL
        payload["audio_file_path"] = DEMO_AUDIO_URL
        payload["preprocessed_audio_file_path"] = None
        payload["separated_audio_file_path"] = DEMO_AUDIO_URL
    return payload


def _public_track_payload(track: models.InstrumentTrack) -> dict:
    payload = schemas.InstrumentTrack.model_validate(track).model_dump(mode="json")
    if track.transcription and track.transcription.is_demo:
        payload["stem_audio_path"] = DEMO_AUDIO_URL
    return payload


def _ensure_transcription_access(
    transcription: models.Transcription,
    db_session: Session,
    current_user: schemas.User,
) -> None:
    if transcription.is_demo:
        return
    if transcription.user_id == current_user.id:
        return
    if transcription.project_id:
        project = db_session.query(models.Project).filter(
            models.Project.id == transcription.project_id
        ).first()
        if project and project.owner_id == current_user.id:
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not authorized to access this transcription"
    )


def _ensure_derived_outputs(transcription: models.Transcription, db_session: Session) -> None:
    """Modal owns derived output generation; API endpoints only serve stored outputs."""
    return


def _require_note_events_for_export(transcription: models.Transcription) -> None:
    if _has_note_events(transcription.notes_data):
        return

    notes_error = _notes_error(transcription.notes_data)
    detail = (
        f"Cannot generate exports because pitch detection failed: {notes_error}"
        if notes_error
        else "Cannot generate exports because no note events were detected."
    )
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _require_transcription_export_supported(
    transcription: models.Transcription,
    format_name: str,
) -> None:
    selected_stem = (transcription.selected_stem or "other").lower()
    if selected_stem not in {"other", "bass"}:
        label = "drum rhythm data" if selected_stem == "drums" else "vocal stem playback"
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{format_name.upper()} export is not available for the selected "
                f"{selected_stem} stem in this MVP. Use the result JSON for {label}."
            ),
        )
    if not transcription.can_generate_score:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Stem playback is available, but no reliable notes were detected for export generation.",
        )


def _require_track_note_events_for_export(track: models.InstrumentTrack) -> None:
    if _has_note_events(track.notes_json):
        return

    notes_error = _notes_error(track.notes_json)
    detail = (
        f"Cannot generate exports for {track.display_name} because pitch detection failed: {notes_error}"
        if notes_error
        else f"Cannot generate exports for {track.display_name} because no note events were detected."
    )
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _get_accessible_transcription(
    transcription_id: int,
    db_session: Session,
    current_user: schemas.User,
) -> models.Transcription:
    transcription = db_session.query(models.Transcription).filter(
        models.Transcription.id == transcription_id
    ).first()

    if not transcription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcription not found"
        )

    _ensure_transcription_access(transcription, db_session, current_user)
    return transcription


def _has_active_transcription(user_id: int, db_session: Session) -> bool:
    active_transcriptions = (
        _active_transcription_query(db_session)
        .filter(models.Transcription.user_id == user_id)
        .all()
    )
    return any(
        transcription.processing_error is None
        or _is_non_blocking_processing_warning(transcription.processing_error)
        for transcription in active_transcriptions
    )


def _has_global_active_transcription_job(db_session: Session) -> bool:
    return _active_transcription_query(db_session).first() is not None


def _usage_limits_enabled() -> bool:
    return bool(core.config.settings.ENABLE_USAGE_LIMITS)


def _user_active_usage_job_count(
    db_session: Session,
    user_id: int,
    *,
    exclude_transcription_id: int | None = None,
) -> int:
    query = (
        db_session.query(models.Transcription.id)
        .filter(models.Transcription.user_id == user_id)
        .filter(models.Transcription.is_demo == False)
        .filter(models.Transcription.is_deleted == False)
        .filter(models.Transcription.processing_status.in_(USAGE_LIMIT_ACTIVE_STATUSES))
    )
    if exclude_transcription_id is not None:
        query = query.filter(models.Transcription.id != exclude_transcription_id)
    return query.count()


def _current_utc_day_start() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def _user_daily_usage_count(db_session: Session, user_id: int) -> int:
    return (
        db_session.query(models.UsageEvent.id)
        .filter(models.UsageEvent.user_id == user_id)
        .filter(models.UsageEvent.created_at >= _current_utc_day_start())
        .count()
    )


def _enforce_usage_limits(
    db_session: Session,
    current_user: schemas.User,
    *,
    exclude_transcription_id: int | None = None,
) -> None:
    if not _usage_limits_enabled():
        return

    max_active = max(0, int(core.config.settings.MAX_ACTIVE_JOBS_PER_USER))
    if max_active > 0:
        active_count = _user_active_usage_job_count(
            db_session,
            current_user.id,
            exclude_transcription_id=exclude_transcription_id,
        )
        if active_count >= max_active:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=ACTIVE_JOB_LIMIT_DETAIL,
            )

    daily_limit = max(0, int(core.config.settings.DAILY_PROCESSING_JOB_LIMIT))
    if daily_limit > 0 and _user_daily_usage_count(db_session, current_user.id) >= daily_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=DAILY_JOB_LIMIT_DETAIL,
        )


def _record_usage_event(
    db_session: Session,
    current_user: schemas.User,
    action_type: str,
    *,
    transcription_id: int | None = None,
) -> None:
    if not _usage_limits_enabled():
        return
    db_session.add(
        models.UsageEvent(
            user_id=current_user.id,
            transcription_id=transcription_id,
            action_type=action_type,
        )
    )
    db_session.commit()


def _active_queue_count(db_session: Session) -> int:
    return _active_transcription_query(db_session).count()


def _queue_metadata_for_new_job(db_session: Session) -> tuple[str, int | None, int | None]:
    active_count = _active_queue_count(db_session)
    status_value = "queued"
    queue_position = active_count + 1 if active_count else 0
    estimated_wait = active_count * ESTIMATED_SECONDS_PER_SELECTED_STEM_JOB
    return status_value, queue_position, estimated_wait


def _queue_metadata_for_existing_job(
    transcription: models.Transcription,
    db_session: Session,
) -> tuple[int | None, int | None]:
    if transcription.processing_status == "processing":
        return 0, 0
    if transcription.processing_status not in {"pending", "queued"}:
        return None, None

    queued_ahead = (
        _active_transcription_query(db_session)
        .filter(models.Transcription.created_at < transcription.created_at)
        .count()
    )
    return queued_ahead + 1, queued_ahead * ESTIMATED_SECONDS_PER_SELECTED_STEM_JOB


def _apply_queue_metadata(transcription: models.Transcription, db_session: Session) -> None:
    queue_position, estimated_wait = _queue_metadata_for_existing_job(transcription, db_session)
    transcription.queue_position = queue_position
    transcription.estimated_wait_time = estimated_wait


def _range_file_response(
    file_path: str,
    range_header: str | None,
    *,
    media_type: str = "audio/wav",
):
    path = Path(file_path)
    file_size = path.stat().st_size
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Disposition": f'inline; filename="{path.name}"',
    }

    if not range_header:
        return FileResponse(path=file_path, media_type=media_type, filename=path.name, headers=headers)

    match = re.match(r"bytes=(\d*)-(\d*)$", range_header.strip())
    if not match:
        return FileResponse(path=file_path, media_type=media_type, filename=path.name, headers=headers)

    start_text, end_text = match.groups()
    start = int(start_text) if start_text else 0
    end = int(end_text) if end_text else file_size - 1
    end = min(end, file_size - 1)
    if start > end or start >= file_size:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail="Requested range is not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    chunk_size = end - start + 1

    def iter_file():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = chunk_size
            while remaining > 0:
                data = f.read(min(1024 * 1024, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers.update({
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Length": str(chunk_size),
    })
    return StreamingResponse(
        iter_file(),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=media_type,
        headers=headers,
    )


def _get_accessible_track(
    transcription_id: int,
    track_id: int,
    db_session: Session,
    current_user: schemas.User,
) -> tuple[models.Transcription, models.InstrumentTrack]:
    transcription = _get_accessible_transcription(transcription_id, db_session, current_user)
    track = db_session.query(models.InstrumentTrack).filter(
        models.InstrumentTrack.id == track_id,
        models.InstrumentTrack.transcription_id == transcription_id,
    ).first()

    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument track not found"
        )

    return transcription, track


def _ensure_track_export_ready(
    transcription: models.Transcription,
    track: models.InstrumentTrack,
    *,
    format_name: str,
) -> None:
    if not transcription.is_processed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcription is still processing"
        )

    blocking_error = _blocking_processing_error(transcription)
    if blocking_error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transcription failed: {blocking_error}"
        )

    supported_by_format = {
        "tab": {"guitar", "bass"},
        "midi": {"guitar", "bass"},
        "musicxml": {"guitar", "bass"},
    }
    supported_instruments = supported_by_format.get(format_name, set())
    if track.instrument_type not in supported_instruments:
        supported_label = (
            "guitar and bass"
            if format_name == "tab"
            else "guitar and bass"
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{track.display_name} exports are not available yet. "
                f"Per-track {format_name.upper()} export currently supports {supported_label} tracks."
            )
        )

    if track.processing_status == "failed" and not _has_note_events(track.notes_json):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{track.display_name} export is unavailable: {track.confidence_notes or 'track analysis failed'}"
        )

    _require_track_note_events_for_export(track)


def _prepare_track_reprocess(
    transcription: models.Transcription,
    track: models.InstrumentTrack,
    db_session: Session,
) -> None:
    if track.instrument_type not in {"guitar", "bass", "drums", "vocals"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{track.display_name} reprocessing is not available yet. "
                "Selected-stem reprocessing currently supports guitar, bass, drum, and vocal stems."
            )
        )

    if (
        not transcription.separated_audio_url
        and (not track.stem_audio_path or not os.path.exists(track.stem_audio_path))
    ):
        track.processing_status = "failed"
        track.confidence_notes = "Stem audio file is missing; track reprocessing skipped."
        db_session.add(track)
        db_session.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{track.display_name} stem audio file is missing."
        )

    track.notes_json = None
    track.chords_json = None
    track.tab_json = None
    track.notation_json = None
    track.confidence_notes = None
    track.processing_status = "processing"
    db_session.add(track)
    db_session.commit()
    db_session.refresh(track)


def _queue_instrument_track_reprocess(
    transcription: models.Transcription,
    track: models.InstrumentTrack,
    background_tasks: BackgroundTasks,
    db_session: Session,
    current_user: schemas.User,
) -> models.InstrumentTrack:
    _enforce_usage_limits(
        db_session,
        current_user,
        exclude_transcription_id=transcription.id,
    )
    _prepare_track_reprocess(transcription, track, db_session)
    # Track reprocessing is scoped to InstrumentTrack. Keep the parent
    # transcription viewable so the dashboard and result page do not treat this
    # as a full audio processing job.
    transcription.modal_request_id = None
    transcription.modal_dispatch_status = None
    transcription.modal_job_type = "reprocess_track"
    transcription.modal_retry_at = None
    transcription.modal_dispatched_at = None
    db_session.add(transcription)
    db_session.commit()
    db_session.refresh(track)
    try:
        _start_instrument_track_reprocess(transcription.id, track.id, background_tasks)
    except Exception:
        track.processing_status = "failed"
        track.confidence_notes = "Track reprocessing could not be started. Please retry later."
        db_session.add(track)
        db_session.commit()
        db_session.refresh(track)
        raise
    _record_usage_event(
        db_session,
        current_user,
        "track_reprocess",
        transcription_id=transcription.id,
    )
    db_session.refresh(track)
    return track


def _track_export_filename(
    transcription_id: int,
    track: models.InstrumentTrack,
    extension: str,
) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", track.instrument_type.lower()).strip("_") or "track"
    return f"transcription_{transcription_id}_{slug}.{extension}"


def _track_notes_to_midi_bytes(track: models.InstrumentTrack) -> bytes:
    if not track.notes_json:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{track.display_name} note data is not available.",
        )

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as temp_file:
            temp_path = temp_file.name
        midi.notes_to_midi(track.notes_json, temp_path)
        return Path(temp_path).read_bytes()
    finally:
        if temp_path:
            _delete_local_file(temp_path)

@router.post("/upload", response_model=schemas.TranscriptionInDB)
async def upload_audio_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    selected_stem: str = Form(...),
    project_id: int = None,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Upload an audio file (MP3 or WAV) for transcription.
    """
    _validate_processing_mode_ready()
    selected_stem = _validate_selected_stem(selected_stem)

    # Validate file extension
    file_extension = os.path.splitext(file.filename)[1].lower()
    if file_extension not in core.config.settings.ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File extension {file_extension} not allowed. Allowed extensions: {core.config.settings.ALLOWED_AUDIO_EXTENSIONS}"
        )

    # Read the file content
    contents = await file.read()

    # Validate file size
    if len(contents) > core.config.settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size too large. Maximum size is {core.config.settings.MAX_UPLOAD_SIZE} bytes"
        )

    audio_hash = _hash_bytes(contents)
    duplicate = _find_duplicate_transcription(
        db_session,
        user_id=current_user.id,
        selected_stem=selected_stem,
        audio_hash=audio_hash,
    )
    if duplicate:
        return _mark_duplicate_response(duplicate)

    _cleanup_stale_active_transcription_jobs(db_session)
    if _processing_mode() == "local" and _has_global_active_transcription_job(db_session):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Another transcription is currently processing. Please wait until it finishes before starting a new one."
            ),
        )
    _enforce_usage_limits(db_session, current_user)

    initial_processing_status, queue_position, estimated_wait = _queue_metadata_for_new_job(db_session)

    # Generate a unique filename to avoid collisions
    unique_filename = f"{uuid.uuid4().hex}{file_extension}"
    file_path = UPLOAD_DIR / unique_filename

    # Save the file to disk
    try:
        with open(file_path, "wb") as buffer:
            buffer.write(contents)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not save file: {str(e)}"
        )

    # Create a transcription record in the database
    # If project_id is provided, we need to check that the project exists and belongs to the user
    if project_id is not None:
        project = db_session.query(models.Project).filter(models.Project.id == project_id).first()
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found"
            )
        if project.owner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to upload to this project"
            )

    # Determine the title for the transcription (use filename if not provided)
    title = file.filename if file.filename else "Audio Upload"

    db_transcription = models.Transcription(
        title=title,
        audio_file_path=storage.normalize_local_path(file_path),
        selected_stem=selected_stem,
        processing_status=initial_processing_status,
        queue_position=queue_position,
        estimated_wait_time=estimated_wait,
        audio_hash=audio_hash,
        source_type="upload",
        source_url=file.filename,
        user_id=current_user.id,
        project_id=project_id,
        is_processed=False
    )
    db_session.add(db_transcription)
    db_session.commit()
    db_session.refresh(db_transcription)
    file_path = _move_source_to_transcription_scratch(
        db_transcription,
        file_path,
        db_session,
    )

    try:
        original_upload = _upload_original_audio(str(file_path), db_transcription.id)
        if original_upload:
            db_transcription.original_audio_url = original_upload["secure_url"]
            db_transcription.original_audio_public_id = original_upload["public_id"]
            db_session.add(db_transcription)
            db_session.commit()
            db_session.refresh(db_transcription)
    except Exception as exc:
        db_transcription.processing_status = "failed"
        db_transcription.processing_error = f"Original audio upload failed: {exc}"
        db_session.add(db_transcription)
        db_session.commit()
        _delete_local_file(str(file_path))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Original audio could not be uploaded to durable storage.",
        ) from exc

    _trigger_next_queued_transcription(background_tasks, db_session)
    _record_usage_event(
        db_session,
        current_user,
        "upload",
        transcription_id=db_transcription.id,
    )
    db_session.refresh(db_transcription)

    return db_transcription


def _find_ffmpeg_path():
    """Find ffmpeg location on the system."""
    import shutil
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return str(Path(ffmpeg_path).resolve().parent)
    # Fallback to known winget installation path
    winget_ffmpeg = Path(os.path.expanduser("~")) / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    for p in winget_ffmpeg.glob("Gyan.FFmpeg*/ffmpeg-*-full_build/bin"):
        if (p / "ffmpeg.exe").exists():
            return str(p.resolve())
    return None


def _build_youtube_download_options(
    unique_filename: str,
    ffmpeg_path: str | None,
    cookiefile: str | None = None,
):
    """Build yt-dlp options using a simple filename template for Windows."""
    options = {
        'format': 'bestaudio/best',
        'paths': {'home': str(UPLOAD_DIR)},
        'outtmpl': {'default': f'{unique_filename}.%(ext)s'},
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',
            'preferredquality': '192',
        }],
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'no_color': True,
        # Restrict to safe filesystem operations.
        'restrictfilenames': True,
        'windowsfilenames': True,
    }

    if ffmpeg_path:
        options['ffmpeg_location'] = ffmpeg_path
    if cookiefile:
        options['cookiefile'] = cookiefile
    extractor_args = _build_youtube_extractor_args()
    if extractor_args:
        options['extractor_args'] = {'youtube': extractor_args}

    return options


def _split_env_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[,;\s]+", value) if item.strip()]


def _build_youtube_extractor_args() -> dict[str, list[str]]:
    extractor_args: dict[str, list[str]] = {}
    po_tokens = _split_env_list(core.config.settings.YOUTUBE_PO_TOKEN)
    visitor_data = (core.config.settings.YOUTUBE_VISITOR_DATA or "").strip()
    player_clients = _split_env_list(core.config.settings.YOUTUBE_PLAYER_CLIENTS)

    if po_tokens:
        extractor_args["po_token"] = po_tokens
    if visitor_data:
        extractor_args["visitor_data"] = [visitor_data]
    if po_tokens or visitor_data:
        extractor_args["player_client"] = player_clients or list(DEFAULT_YOUTUBE_PLAYER_CLIENTS)
    elif player_clients:
        extractor_args["player_client"] = player_clients

    return extractor_args


@dataclass(frozen=True)
class YouTubeCookiefile:
    path: str | None
    cleanup: bool
    loaded: bool
    source: str | None
    line_count: int = 0
    cookie_count: int = 0


@dataclass(frozen=True)
class YouTubeCookieDiagnostics:
    valid: bool
    line_count: int
    cookie_count: int
    has_youtube_domain: bool
    important_cookie_names: frozenset[str]
    fingerprint: str


def _normalize_youtube_cookies_text(cookies_text: str) -> str:
    if "\\n" in cookies_text and "\n" not in cookies_text:
        cookies_text = cookies_text.replace("\\n", "\n")
    return cookies_text


def _decode_youtube_cookies_b64(cookies_b64: str) -> str:
    try:
        return base64.b64decode(cookies_b64.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        logger.warning("YOUTUBE_COOKIES_B64 is configured but could not be decoded.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="YOUTUBE_COOKIES_B64 is configured but is not valid base64-encoded UTF-8 cookies.txt content.",
        ) from exc


def _inspect_youtube_cookies_text(cookies_text: str) -> YouTubeCookieDiagnostics:
    normalized = _normalize_youtube_cookies_text(cookies_text)
    lines = [line.strip() for line in normalized.splitlines()]
    meaningful_lines = [
        line for line in lines
        if line and not line.startswith("#")
    ]
    cookie_count = 0
    has_youtube_domain = False
    important_cookie_names: set[str] = set()
    for line in meaningful_lines:
        fields = line.split("\t")
        if len(fields) < 7:
            continue
        cookie_count += 1
        domain = fields[0].strip().lower()
        name = fields[5].strip()
        if domain == ".youtube.com" or domain.endswith(".youtube.com"):
            has_youtube_domain = True
        if name in IMPORTANT_YOUTUBE_COOKIE_NAMES:
            important_cookie_names.add(name)

    fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]
    return YouTubeCookieDiagnostics(
        valid=cookie_count > 0,
        line_count=len(lines),
        cookie_count=cookie_count,
        has_youtube_domain=has_youtube_domain,
        important_cookie_names=frozenset(important_cookie_names),
        fingerprint=fingerprint,
    )


def _invalid_youtube_cookies_detail(source: str) -> str:
    return (
        f"YouTube cookies from {source} are missing or invalid. "
        "For Render, set YOUTUBE_COOKIES to fresh Netscape-format browser cookies, "
        "or upload the audio file directly."
    )


def _get_ytdlp_version() -> str:
    version_module = getattr(yt_dlp, "version", None)
    version = getattr(version_module, "__version__", None)
    return str(version or "unknown")


def _effective_youtube_cookie_source(cookies_text: str | None, cookies_file: str | None) -> str:
    if cookies_text:
        return "env"
    if (core.config.settings.YOUTUBE_COOKIES_B64 or "").strip():
        return "env-b64"
    if cookies_file:
        return "file"
    return "none"


def _log_youtube_cookie_environment(
    cookies_text: str | None,
    cookies_file: str | None,
    cookies_b64: str | None,
    effective_source: str,
) -> None:
    logger.info(
        "YouTube cookie config: YOUTUBE_COOKIES configured=%s "
        "YOUTUBE_COOKIES_B64 configured=%s YOUTUBE_COOKIES_FILE configured=%s "
        "effective cookie source=%s yt-dlp version=%s",
        bool(cookies_text),
        bool(cookies_b64),
        bool(cookies_file),
        effective_source,
        _get_ytdlp_version(),
    )


def _log_youtube_cookie_diagnostics(
    source: str,
    diagnostics: YouTubeCookieDiagnostics,
) -> None:
    important_presence = {
        name: name in diagnostics.important_cookie_names
        for name in sorted(IMPORTANT_YOUTUBE_COOKIE_NAMES)
    }
    logger.info(
        "yt-dlp cookies source=%s lines=%s cookie_count=%s "
        "has_youtube_domain=%s important_cookie_names=%s "
        "cookie fingerprint=%s",
        source,
        diagnostics.line_count,
        diagnostics.cookie_count,
        diagnostics.has_youtube_domain,
        important_presence,
        diagnostics.fingerprint,
    )
    if diagnostics.cookie_count < LOW_YOUTUBE_COOKIE_COUNT_THRESHOLD:
        logger.warning(
            "YouTube cookie count appears low; cookies may be incomplete or expired."
        )


def _write_youtube_cookies_tempfile(cookies_text: str) -> str:
    cookies_text = _normalize_youtube_cookies_text(cookies_text)

    cookie_file = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".cookies.txt",
        dir=UPLOAD_DIR,
        delete=False,
    )
    try:
        cookie_file.write(cookies_text)
        if not cookies_text.endswith("\n"):
            cookie_file.write("\n")
        return cookie_file.name
    finally:
        cookie_file.close()
        os.chmod(cookie_file.name, 0o600)


def _read_youtube_cookies_file(cookies_file: str) -> str:
    try:
        return Path(cookies_file).read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning(
            "yt-dlp cookie file configured but unreadable: path=%s error=%s",
            cookies_file,
            exc.__class__.__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_invalid_youtube_cookies_detail("YOUTUBE_COOKIES_FILE"),
        ) from exc


def _get_youtube_cookiefile() -> YouTubeCookiefile:
    cookies_file = (core.config.settings.YOUTUBE_COOKIES_FILE or "").strip()
    cookies_text = core.config.settings.YOUTUBE_COOKIES
    cookies_b64 = (core.config.settings.YOUTUBE_COOKIES_B64 or "").strip()
    effective_source = _effective_youtube_cookie_source(cookies_text, cookies_file)
    _log_youtube_cookie_environment(cookies_text, cookies_file, cookies_b64, effective_source)

    if sum(bool(value) for value in (cookies_text, cookies_b64, cookies_file)) > 1:
        logger.info(
            "Multiple YouTube cookie sources configured; using precedence "
            "YOUTUBE_COOKIES, then YOUTUBE_COOKIES_B64, then YOUTUBE_COOKIES_FILE."
        )

    if cookies_text:
        if cookies_file:
            logger.info("Using YOUTUBE_COOKIES from environment; ignoring YOUTUBE_COOKIES_FILE.")
        diagnostics = _inspect_youtube_cookies_text(cookies_text)
        _log_youtube_cookie_diagnostics("env", diagnostics)
        if not diagnostics.valid:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=YOUTUBE_COOKIES_MALFORMED_DETAIL,
            )
        if not diagnostics.has_youtube_domain:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=YOUTUBE_COOKIES_NO_YOUTUBE_DOMAIN_DETAIL,
            )
        return YouTubeCookiefile(
            path=_write_youtube_cookies_tempfile(cookies_text),
            cleanup=True,
            loaded=True,
            source="YOUTUBE_COOKIES",
            line_count=diagnostics.line_count,
            cookie_count=diagnostics.cookie_count,
        )

    if cookies_b64:
        decoded_cookies_text = _decode_youtube_cookies_b64(cookies_b64)
        diagnostics = _inspect_youtube_cookies_text(decoded_cookies_text)
        _log_youtube_cookie_diagnostics("env-b64", diagnostics)
        if not diagnostics.valid:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="YOUTUBE_COOKIES_B64 decoded successfully but is not valid Netscape cookie format.",
            )
        if not diagnostics.has_youtube_domain:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="YOUTUBE_COOKIES_B64 decoded successfully but does not contain YouTube cookies.",
            )
        return YouTubeCookiefile(
            path=_write_youtube_cookies_tempfile(decoded_cookies_text),
            cleanup=True,
            loaded=True,
            source="YOUTUBE_COOKIES_B64",
            line_count=diagnostics.line_count,
            cookie_count=diagnostics.cookie_count,
        )

    if cookies_file:
        file_cookies_text = _read_youtube_cookies_file(cookies_file)
        diagnostics = _inspect_youtube_cookies_text(file_cookies_text)
        _log_youtube_cookie_diagnostics("file", diagnostics)
        if not diagnostics.valid:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=_invalid_youtube_cookies_detail("YOUTUBE_COOKIES_FILE"),
            )
        return YouTubeCookiefile(
            path=cookies_file,
            cleanup=False,
            loaded=True,
            source="YOUTUBE_COOKIES_FILE",
            line_count=diagnostics.line_count,
            cookie_count=diagnostics.cookie_count,
        )

    logger.info("yt-dlp cookies source=none")
    return YouTubeCookiefile(path=None, cleanup=False, loaded=False, source=None)


def _is_youtube_verification_error(error: Exception) -> bool:
    message = str(error).lower()
    return (
        "sign in to confirm" in message
        or "not a bot" in message
        or "use --cookies-from-browser or --cookies" in message
    )


def _youtube_verification_detail() -> str:
    return (
        "YouTube is requiring sign-in or bot verification for this video. "
        "For Render, set YOUTUBE_COOKIES_B64 to fresh base64-encoded Netscape cookies "
        "and, if cookies alone are rejected, set YOUTUBE_PO_TOKEN. "
        "You can also upload the audio file directly."
    )


@router.post("/youtube", response_model=schemas.TranscriptionInDB)
async def extract_audio_from_youtube(
    request: YouTubeUploadRequest,
    background_tasks: BackgroundTasks,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Extract audio from a YouTube URL and save it for transcription.
    """
    _validate_processing_mode_ready()
    youtube_url = request.youtube_url.strip()
    selected_stem = _validate_selected_stem(request.selected_stem)
    project_id = request.project_id
    current_user_id = current_user.id

    # Validate the YouTube URL (basic validation)
    if not youtube_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="YouTube URL is required"
        )
    if re.search(r"[\x00-\x1f\x7f]", youtube_url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="YouTube URL contains invalid characters"
        )

    normalized_source_id = _normalize_youtube_id(youtube_url)
    if not normalized_source_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not determine a YouTube video ID from this URL",
        )

    duplicate = _find_duplicate_transcription(
        db_session,
        user_id=current_user_id,
        selected_stem=selected_stem,
        normalized_source_id=normalized_source_id,
    )
    if duplicate:
        return _mark_duplicate_response(duplicate)

    _cleanup_stale_active_transcription_jobs(db_session)
    if _processing_mode() == "local" and _has_global_active_transcription_job(db_session):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Another transcription is currently processing. Please wait until it finishes before starting a new one."
            ),
        )
    _enforce_usage_limits(db_session, current_user)

    initial_processing_status, queue_position, estimated_wait = _queue_metadata_for_new_job(db_session)
    if db.DATABASE_URL.startswith("sqlite"):
        db_session.rollback()

    # Generate a unique filename for the output (without extension, yt-dlp will add it)
    unique_filename = f"{uuid.uuid4().hex}"

    # Determine ffmpeg location
    ffmpeg_path = _find_ffmpeg_path()

    # Keep yt-dlp's template as a plain filename; paths.home carries the directory.
    youtube_cookiefile = _get_youtube_cookiefile()
    yt_dlp_opts = _build_youtube_download_options(unique_filename, ffmpeg_path, youtube_cookiefile.path)

    logger.info(f"yt-dlp output directory: {UPLOAD_DIR}")
    logger.info(f"yt-dlp output template: {yt_dlp_opts['outtmpl']}")
    logger.info(f"ffmpeg_path: {ffmpeg_path}")
    logger.info(
        "yt-dlp cookies configured: %s source=%s",
        youtube_cookiefile.loaded,
        youtube_cookiefile.source or "none",
    )

    video_title = "YouTube Audio"

    try:
        # Download and extract audio in a single pass
        try:
            with yt_dlp.YoutubeDL(yt_dlp_opts) as ydl:
                info_dict = ydl.extract_info(youtube_url, download=True)
                video_title = info_dict.get('title', 'YouTube Audio') if info_dict else 'YouTube Audio'
        finally:
            if youtube_cookiefile.cleanup and youtube_cookiefile.path:
                _delete_local_file(youtube_cookiefile.path)

        expected_audio_file_path = UPLOAD_DIR / f"{unique_filename}.wav"
        logger.info("yt-dlp expected output path: %s", expected_audio_file_path)

        # After download, the file should be at the resolved path
        audio_file_path = expected_audio_file_path

        # Check if the file exists
        if not audio_file_path.exists():
            # Sometimes yt-dlp keeps the original extension — check for common ones
            for ext in ['wav', 'mp3', 'webm', 'opus', 'm4a', 'ogg']:
                candidate = UPLOAD_DIR / f"{unique_filename}.{ext}"
                if candidate.exists():
                    audio_file_path = candidate
                    break
            else:
                # List what files we DO have for debugging
                existing = list(UPLOAD_DIR.glob(f"{unique_filename}.*"))
                logger.error(
                    "Expected audio file not found. Files matching pattern: %s",
                    existing,
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to extract audio from YouTube URL. No output file found."
                )

        logger.info("yt-dlp actual downloaded file path: %s", audio_file_path)
        logger.info("yt-dlp normalized source path: %s", storage.normalize_local_path(audio_file_path))

    except HTTPException:
        raise
    except DownloadError as e:
        logger.error(f"YouTube extraction failed: {traceback.format_exc()}")
        if _is_youtube_verification_error(e):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    YOUTUBE_COOKIE_REJECTED_DETAIL
                    if youtube_cookiefile.loaded
                    else _youtube_verification_detail()
                ),
            ) from e
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"YouTube download failed: {str(e)}",
        ) from e
    except Exception as e:
        logger.error(f"YouTube extraction failed: {traceback.format_exc()}")
        if _is_youtube_verification_error(e):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    YOUTUBE_COOKIE_REJECTED_DETAIL
                    if youtube_cookiefile.loaded
                    else _youtube_verification_detail()
                ),
            ) from e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error extracting audio from YouTube: {str(e)}"
        )

    # Create a transcription record in the database
    # If project_id is provided, we need to check that the project exists and belongs to the user
    if project_id is not None:
        project = db_session.query(models.Project).filter(models.Project.id == project_id).first()
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found"
            )
        if project.owner_id != current_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to upload to this project"
            )

    db_transcription = models.Transcription(
        title=video_title,
        audio_file_path=storage.normalize_local_path(audio_file_path),
        youtube_url=youtube_url,
        selected_stem=selected_stem,
        processing_status=initial_processing_status,
        queue_position=queue_position,
        estimated_wait_time=estimated_wait,
        source_type="youtube",
        source_url=youtube_url,
        normalized_source_id=normalized_source_id,
        user_id=current_user_id,
        project_id=project_id,
        is_processed=False
    )
    db_session.add(db_transcription)
    db_session.commit()
    db_session.refresh(db_transcription)
    try:
        audio_file_path = _move_source_to_transcription_scratch(
            db_transcription,
            audio_file_path,
            db_session,
        )
    except Exception as exc:
        db_transcription.processing_status = "failed"
        db_transcription.processing_error = (
            f"Could not move downloaded YouTube audio into scratch: {exc}"
        )
        db_session.add(db_transcription)
        db_session.commit()
        _delete_local_file(str(audio_file_path))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to prepare downloaded audio for transcription.",
        ) from exc

    try:
        original_upload = _upload_original_audio(str(audio_file_path), db_transcription.id)
        if original_upload:
            db_transcription.original_audio_url = original_upload["secure_url"]
            db_transcription.original_audio_public_id = original_upload["public_id"]
            db_session.add(db_transcription)
            db_session.commit()
            db_session.refresh(db_transcription)
    except Exception as exc:
        db_transcription.processing_status = "failed"
        db_transcription.processing_error = f"Original audio upload failed: {exc}"
        db_session.add(db_transcription)
        db_session.commit()
        _delete_local_file(str(audio_file_path))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Original audio could not be uploaded to durable storage.",
        ) from exc

    _trigger_next_queued_transcription(background_tasks, db_session)
    _record_usage_event(
        db_session,
        current_user,
        "youtube",
        transcription_id=db_transcription.id,
    )
    db_session.refresh(db_transcription)

    return db_transcription


@router.get("/", response_model=list[schemas.TranscriptionInDB])
async def list_transcriptions(
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    List the current user's transcriptions, newest first.
    """
    transcriptions = (
        db_session.query(models.Transcription)
        .filter(or_(
            models.Transcription.user_id == current_user.id,
            models.Transcription.is_demo == True,
        ))
        .filter(models.Transcription.is_deleted == False)
        .order_by(models.Transcription.is_demo.desc())
        .order_by(models.Transcription.created_at.desc(), models.Transcription.id.desc())
        .all()
    )
    return [_public_transcription_payload(transcription) for transcription in transcriptions]


@router.get("/demo", response_model=schemas.TranscriptionInDB)
async def get_demo_transcription(
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user),
):
    demo = (
        db_session.query(models.Transcription)
        .filter(models.Transcription.is_demo == True)
        .filter(models.Transcription.is_deleted == False)
        .order_by(models.Transcription.id.asc())
        .first()
    )
    if not demo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demo transcription is not available.",
        )
    return _public_transcription_payload(demo)


@router.get("/demo-guitar-riff.wav")
async def get_demo_guitar_riff_audio():
    demo_path = Path(__file__).resolve().parents[3] / "static" / "demo_guitar_riff.wav"
    if not demo_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demo audio file not available",
        )
    return FileResponse(
        path=str(demo_path),
        media_type="audio/wav",
        filename=demo_path.name,
    )


@router.delete("/{transcription_id}", response_model=schemas.TranscriptionInDB)
async def delete_transcription(
    transcription_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user),
):
    """
    Soft-delete a transcription and best-effort cancel queued/active work.
    """
    transcription = _get_accessible_transcription(
        transcription_id,
        db_session,
        current_user,
    )
    return _soft_delete_transcription(transcription, db_session)


@router.get("/{transcription_id}/status")
async def get_transcription_status(
    transcription_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Get the processing status of a transcription.
    """
    # Get the transcription record
    transcription = db_session.query(models.Transcription).filter(
        models.Transcription.id == transcription_id
    ).first()

    if not transcription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcription not found"
        )

    _ensure_transcription_access(transcription, db_session, current_user)
    _cleanup_stale_active_transcription_jobs(db_session)
    db_session.refresh(transcription)
    _repair_playback_only_stem_ready(transcription, db_session)
    _ensure_structured_tablature_repaired(transcription, db_session)
    _repair_completed_manual_generation_status(transcription, db_session)

    selected_stem = transcription.selected_stem or "other"
    if transcription.is_deleted:
        return _finalize_status_response_for_mode({
            "status": transcription.processing_status or "deleted",
            "transcription_id": transcription_id,
            **_metadata_payload(transcription),
            "warning": transcription.warning_message,
            "warning_message": transcription.warning_message,
            "lyrics_generation_status": transcription.lyrics_generation_status,
            "lyrics_data": transcription.lyrics_data,
            "is_demo": transcription.is_demo,
            "deleted_at": transcription.deleted_at,
            "message": "This transcription record was deleted.",
            "queue_position": None,
            "estimated_wait_time": None,
            "modal_dispatch_status": transcription.modal_dispatch_status,
            "modal_status_detail": _modal_status_detail(transcription),
            "modal_job_type": transcription.modal_job_type,
            "modal_request_id": transcription.modal_request_id,
            "modal_retry_count": transcription.modal_retry_count,
            "modal_retry_at": transcription.modal_retry_at,
        })

    blocking_error = _blocking_processing_error(transcription)
    if blocking_error or transcription.processing_status == "failed":
        return _finalize_status_response_for_mode({
            "status": "failed",
            "error": blocking_error or transcription.processing_error or "Processing failed",
            "transcription_id": transcription_id,
            **_metadata_payload(transcription),
            "warning": transcription.warning_message,
            "warning_message": transcription.warning_message,
            "lyrics_generation_status": transcription.lyrics_generation_status,
            "lyrics_data": transcription.lyrics_data,
            "is_demo": transcription.is_demo,
            "queue_position": None,
            "estimated_wait_time": None,
            "modal_dispatch_status": transcription.modal_dispatch_status,
            "modal_status_detail": _modal_status_detail(transcription),
            "modal_job_type": transcription.modal_job_type,
            "modal_request_id": transcription.modal_request_id,
            "modal_retry_count": transcription.modal_retry_count,
            "modal_retry_at": transcription.modal_retry_at,
        })

    # Return status based on transcription record
    if transcription.is_processed or _is_viewable_stem_ready(transcription):
        notes_error = _notes_error(transcription.notes_data)
        if notes_error and not transcription.warning_message:
            transcription.warning_message = f"Pitch detection warning: {notes_error}"
            transcription.can_generate_score = False
            transcription.can_play_stem = _can_play_stem(transcription)
            db_session.add(transcription)
            db_session.commit()
            db_session.refresh(transcription)
        if selected_stem not in {"drums", "vocals"} and not _has_note_events(transcription.notes_data):
            if not transcription.warning_message:
                transcription.warning_message = "No note events detected for this stem."
            transcription.can_generate_score = False
            transcription.can_play_stem = _can_play_stem(transcription)
            db_session.add(transcription)
            db_session.commit()
            db_session.refresh(transcription)
        return _status_payload(transcription, transcription_id, selected_stem)
    else:
        current_status = transcription.processing_status or "queued"
        _apply_queue_metadata(transcription, db_session)
        db_session.add(transcription)
        db_session.commit()
        message = None
        if current_status == "queued":
            if transcription.modal_dispatch_status in {"rate_limited", "retry_queued"}:
                message = "Waiting for Modal capacity. Retry scheduled."
            elif _processing_mode() == "local":
                message = "Queued for local processing."
            else:
                message = (
                    "Queued for Modal processing. It will start when capacity is available."
                )
        elif current_status == "pending":
            message = "Waiting for the selected-stem job to start."
        return _finalize_status_response_for_mode({
            "status": current_status,
            "transcription_id": transcription_id,
            **_metadata_payload(transcription),
            "warning": transcription.warning_message,
            "warning_message": transcription.warning_message,
            "lyrics_generation_status": transcription.lyrics_generation_status,
            "lyrics_data": transcription.lyrics_data,
            "is_demo": transcription.is_demo,
            "message": message,
            "queue_position": transcription.queue_position,
            "estimated_wait_time": transcription.estimated_wait_time,
            "modal_dispatch_status": transcription.modal_dispatch_status,
            "modal_status_detail": _modal_status_detail(transcription),
            "modal_job_type": transcription.modal_job_type,
            "modal_request_id": transcription.modal_request_id,
            "modal_retry_count": transcription.modal_retry_count,
            "modal_retry_at": transcription.modal_retry_at,
        })


@router.get("/{transcription_id}/source")
async def get_transcription_source_audio(
    transcription_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """Stream the original uploaded/extracted audio for playback."""
    transcription = db_session.query(models.Transcription).filter(
        models.Transcription.id == transcription_id
    ).first()

    if not transcription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcription not found"
        )

    _ensure_transcription_access(transcription, db_session, current_user)

    if transcription.processing_status == "stem_ready" and transcription.separated_audio_url:
        return RedirectResponse(transcription.separated_audio_url)

    if transcription.original_audio_url:
        return RedirectResponse(transcription.original_audio_url)

    source_candidates = [
        transcription.audio_file_path,
        str(UPLOAD_DIR / Path(transcription.audio_file_path).name) if transcription.audio_file_path else None,
        transcription.preprocessed_audio_file_path,
    ]
    candidates = (
        [transcription.separated_audio_file_path, *source_candidates]
        if transcription.processing_status == "stem_ready"
        else [*source_candidates, transcription.separated_audio_file_path]
    )
    for candidate in candidates:
        if not candidate:
            continue
        normalized_candidate = storage.normalize_local_path(candidate)
        candidate_path = Path(normalized_candidate)
        if candidate_path.exists():
            return FileResponse(
                path=str(candidate_path),
                media_type="audio/wav",
                filename=candidate_path.name,
            )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Source audio file not available"
    )


@router.get("/{transcription_id}/result")
async def get_transcription_result(
    transcription_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Get the result of a completed transcription.
    """
    # Get the transcription record
    transcription = db_session.query(models.Transcription).filter(
        models.Transcription.id == transcription_id
    ).first()

    if not transcription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcription not found"
        )

    _ensure_transcription_access(transcription, db_session, current_user)
    _repair_playback_only_stem_ready(transcription, db_session)
    _ensure_structured_tablature_repaired(transcription, db_session)
    _repair_completed_manual_generation_status(transcription, db_session)

    processing_status_value = transcription.processing_status or "pending"
    if processing_status_value in {"pending", "queued", "processing"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcription is still processing"
        )

    blocking_error = _blocking_processing_error(transcription)
    if blocking_error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transcription failed: {blocking_error}"
        )

    if not transcription.is_processed and not _is_viewable_stem_ready(transcription):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcription is not ready to view"
        )

    if transcription.processing_status != "stem_ready":
        try:
            _ensure_derived_outputs(transcription, db_session)
        except Exception as e:
            logger.warning(
                "Could not regenerate derived outputs for transcription %s: %s",
                transcription_id,
                e,
            )

    # Return the transcription data
    return _public_transcription_payload(transcription)


@router.post("/{transcription_id}/generate-tab")
@router.post("/{transcription_id}/generate-tabs")
async def generate_tab(
    transcription_id: int,
    background_tasks: BackgroundTasks,
    request: GenerateTabRequest = Body(default=GenerateTabRequest()),
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user),
):
    """
    Generate TAB/rhythm output from an existing separated selected stem.
    """
    transcription = _get_accessible_transcription(transcription_id, db_session, current_user)
    if transcription.is_demo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Demo transcriptions already include their example outputs.",
        )
    if transcription.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot generate tabs for a deleted transcription.",
        )

    selected_stem = _validate_selected_stem(transcription.selected_stem)
    if selected_stem == "vocals":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Vocal stems are playback-only in this MVP.",
        )
    if selected_stem in {"bass", "other"}:
        try:
            resolve_generate_tab_audio_source(transcription)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
    if not _can_play_stem(transcription):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=MISSING_SEPARATED_STEM_MESSAGE,
        )
    if transcription.processing_status == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This transcription is already processing.",
        )

    relevant_generation_status = (
        transcription.rhythm_generation_status
        if selected_stem == "drums"
        else transcription.tab_generation_status
    ) or "idle"
    if relevant_generation_status == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tab generation is already processing.",
        )
    _enforce_usage_limits(
        db_session,
        current_user,
        exclude_transcription_id=transcription.id,
    )
    existing_score_ready = _can_generate_score(transcription)
    if transcription.processing_status in {"pending", "queued"}:
        transcription.processing_status = "stem_ready"
    transcription.is_processed = True
    transcription.can_generate_score = existing_score_ready
    if relevant_generation_status == "failed":
        transcription.processing_error = None
        transcription.warning_message = None
    transcription.queue_position = 0
    transcription.estimated_wait_time = 0
    transcription.modal_job_type = "generate_tab"
    _set_manual_generation_status(transcription, "processing")
    transcription.modal_request_id = None
    transcription.modal_dispatch_status = None
    transcription.modal_retry_at = None
    transcription.modal_dispatched_at = None
    transcription.celery_task_id = None
    db_session.add(transcription)
    db_session.commit()
    db_session.refresh(transcription)
    task_id = _start_tab_generation(
        transcription.id,
        background_tasks,
        detection_sensitivity=request.sensitivity,
    )
    if task_id:
        transcription.celery_task_id = task_id
        db_session.add(transcription)
        db_session.commit()
        db_session.refresh(transcription)
    _record_usage_event(
        db_session,
        current_user,
        "generate_tabs",
        transcription_id=transcription.id,
    )
    db_session.refresh(transcription)
    metadata = _metadata_payload(transcription)
    message = (
        "Rhythm generation started."
        if selected_stem == "drums"
        else "Tab generation started."
    )
    return {
        "status": transcription.processing_status,
        "transcription_id": transcription.id,
        **metadata,
        "is_demo": transcription.is_demo,
        "message": message,
    }


@router.post("/transcriptions/{transcription_id}/generate-lyrics")
@router.post("/{transcription_id}/generate-lyrics")
async def generate_lyrics(
    transcription_id: int,
    background_tasks: BackgroundTasks,
    request: GenerateLyricsRequest | None = Body(default=None),
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user),
):
    """
    Generate lyrics from an existing separated vocal stem.

    This intentionally uses lyrics_generation_status instead of changing the
    main processing_status, so the viewer remains open and stem playback stays
    available while lyrics are transcribed.
    """
    transcription = _get_accessible_transcription(transcription_id, db_session, current_user)
    if transcription.is_demo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Demo transcriptions already include their example outputs.",
        )
    if transcription.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot generate lyrics for a deleted transcription.",
        )

    selected_stem = _validate_selected_stem(transcription.selected_stem)
    if selected_stem != "vocals":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lyrics generation is only available for vocal stems.",
        )
    if not _can_play_stem(transcription) or not _has_stem_audio_reference(transcription):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Separated vocal stem is required before generating lyrics.",
        )
    if transcription.lyrics_generation_status == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lyrics generation is already processing.",
        )
    _enforce_usage_limits(
        db_session,
        current_user,
        exclude_transcription_id=transcription.id,
    )
    lyrics_language = _validate_lyrics_language(
        request.language if request else None
    )

    runtime = None
    try:
        from ....services.lyrics import resolve_whisper_runtime

        runtime = resolve_whisper_runtime()
    except Exception:
        runtime = {
            "model_size": core.config.settings.WHISPER_MODEL_SIZE,
            "device": core.config.settings.WHISPER_DEVICE,
        }
    logger.info(
        "lyrics_generation_requested transcription_id=%s selected_stem=%s whisper_model=%s whisper_device=%s lyrics_language=%s",
        transcription.id,
        selected_stem,
        runtime.get("model_size"),
        runtime.get("device"),
        lyrics_language,
    )

    transcription.lyrics_generation_status = "processing"
    transcription.processing_error = None
    transcription.modal_job_type = "generate_lyrics"
    transcription.modal_request_id = None
    transcription.modal_dispatch_status = None
    transcription.modal_retry_at = None
    transcription.modal_dispatched_at = None
    db_session.add(transcription)
    db_session.commit()
    db_session.refresh(transcription)

    task_id = _start_lyrics_generation(
        transcription.id,
        background_tasks,
        lyrics_language=lyrics_language,
    )
    if task_id:
        transcription.celery_task_id = task_id
        db_session.add(transcription)
        db_session.commit()
        db_session.refresh(transcription)
    _record_usage_event(
        db_session,
        current_user,
        "generate_lyrics",
        transcription_id=transcription.id,
    )
    db_session.refresh(transcription)

    return {
        "status": transcription.processing_status,
        "lyrics_generation_status": transcription.lyrics_generation_status,
        "tab_generation_status": transcription.tab_generation_status or "idle",
        "rhythm_generation_status": transcription.rhythm_generation_status or "idle",
        "transcription_id": transcription.id,
        "selected_stem": selected_stem,
        "can_play_stem": _can_play_stem(transcription),
        "separated_audio_url": transcription.separated_audio_url,
        "is_demo": transcription.is_demo,
        "lyrics_language": lyrics_language,
        "message": "Lyrics generation started.",
    }


@router.post("/{transcription_id}/retry")
async def retry_transcription(
    transcription_id: int,
    retry: schemas.RetryTranscriptionRequest,
    background_tasks: BackgroundTasks,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user),
):
    """
    Retry note transcription from the retained stem when possible.

    Lower-threshold mode increases detection sensitivity without treating a
    previous no-note pass as a failed separation job. A new stem selection is
    accepted when the original/preprocessed source is still available.
    """
    transcription = _get_accessible_transcription(transcription_id, db_session, current_user)
    if transcription.is_demo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Demo transcriptions are shared examples and cannot be retried.",
        )
    if transcription.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot retry a deleted transcription.",
        )

    selected_stem = _validate_selected_stem(retry.selected_stem or transcription.selected_stem)
    stem_changed = selected_stem != (transcription.selected_stem or "other")
    source_available = any(
        path_value and os.path.exists(storage.normalize_local_path(path_value))
        for path_value in (transcription.audio_file_path, transcription.preprocessed_audio_file_path)
    )
    if stem_changed and not source_available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Cannot choose another stem because the original source is no longer local. "
                "Upload the source again to separate a different stem."
            ),
        )
    _enforce_usage_limits(
        db_session,
        current_user,
        exclude_transcription_id=transcription.id,
    )

    sensitivity = (
        "high"
        if retry.lower_threshold or (retry.alternate_settings or {}).get("sensitivity") == "high"
        else "normal"
    )
    transcription.selected_stem = selected_stem
    transcription.is_processed = False
    transcription.processing_status = "processing"
    transcription.processing_error = None
    transcription.warning_message = None
    transcription.can_generate_score = selected_stem not in {"vocals", "drums"}
    transcription.can_play_stem = _can_play_stem(transcription)
    transcription.queue_position = 0
    transcription.estimated_wait_time = 0
    transcription.modal_request_id = None
    transcription.modal_dispatch_status = None
    transcription.modal_job_type = None
    transcription.modal_retry_at = None
    transcription.midi_file_path = None
    transcription.midi_file_url = None
    transcription.midi_file_public_id = None
    transcription.tab_file_path = None
    transcription.tab_file_url = None
    transcription.tab_file_public_id = None
    db_session.add(transcription)
    db_session.commit()
    db_session.refresh(transcription)

    task_id = _start_transcription_processing(
        transcription.id,
        background_tasks,
        db_session,
        detection_sensitivity=sensitivity,
        selected_stem_override=selected_stem,
    )
    if task_id:
        transcription.celery_task_id = task_id
        db_session.add(transcription)
        db_session.commit()
        db_session.refresh(transcription)
    _record_usage_event(
        db_session,
        current_user,
        "retry",
        transcription_id=transcription.id,
    )
    db_session.refresh(transcription)

    return {
        "status": transcription.processing_status,
        "transcription_id": transcription.id,
        "selected_stem": selected_stem,
        "can_play_stem": _can_play_stem(transcription),
        "can_generate_score": transcription.can_generate_score,
        "is_demo": transcription.is_demo,
        "message": "Retry transcription queued with alternate detection settings.",
    }


@router.get("/{transcription_id}/tracks", response_model=list[schemas.InstrumentTrack])
async def list_instrument_tracks(
    transcription_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    List instrument tracks generated for a transcription.
    """
    _get_accessible_transcription(transcription_id, db_session, current_user)

    tracks = (
        db_session.query(models.InstrumentTrack)
        .filter(models.InstrumentTrack.transcription_id == transcription_id)
        .order_by(models.InstrumentTrack.id.asc())
        .all()
    )
    return [_public_track_payload(track) for track in tracks]


@router.get("/{transcription_id}/tracks/{track_id}", response_model=schemas.InstrumentTrack)
async def get_instrument_track(
    transcription_id: int,
    track_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Retrieve one instrument track result for a transcription.
    """
    _get_accessible_transcription(transcription_id, db_session, current_user)

    track = db_session.query(models.InstrumentTrack).filter(
        models.InstrumentTrack.id == track_id,
        models.InstrumentTrack.transcription_id == transcription_id,
    ).first()

    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument track not found"
        )

    return _public_track_payload(track)


@router.get("/{transcription_id}/tracks/{track_id}/stem")
async def get_instrument_track_stem(
    transcription_id: int,
    track_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Stream one separated stem for playback.
    """
    transcription = _get_accessible_transcription(transcription_id, db_session, current_user)

    track = db_session.query(models.InstrumentTrack).filter(
        models.InstrumentTrack.id == track_id,
        models.InstrumentTrack.transcription_id == transcription_id,
    ).first()

    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument track not found"
        )

    selected_instrument = {
        "other": "guitar",
        "bass": "bass",
        "drums": "drums",
        "vocals": "vocals",
    }.get(transcription.selected_stem or "other")
    if transcription.separated_audio_url and track.instrument_type == selected_instrument:
        return RedirectResponse(transcription.separated_audio_url)

    if not track.stem_audio_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument stem audio file not available"
        )

    stem_path = Path(storage.normalize_local_path(track.stem_audio_path))
    if not stem_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument stem audio file not available"
        )

    return FileResponse(
        path=str(stem_path),
        media_type="audio/wav",
        filename=stem_path.name,
    )


@router.get("/{transcription_id}/tracks/{track_id}/preview")
async def get_instrument_track_preview(
    transcription_id: int,
    track_id: int,
    request: Request,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user),
):
    """
    Preview the selected separated stem before export.

    Cloudinary URLs are preferred because Railway local disk is temporary in the
    selected-stem MVP. Local range streaming remains for development and for any
    legacy records that still have a retained scratch file.
    """
    transcription, track = _get_accessible_track(
        transcription_id,
        track_id,
        db_session,
        current_user,
    )

    selected_instrument = {
        "other": "guitar",
        "bass": "bass",
        "drums": "drums",
        "vocals": "vocals",
    }.get(transcription.selected_stem or "other")
    if transcription.separated_audio_url and track.instrument_type == selected_instrument:
        return RedirectResponse(transcription.separated_audio_url)

    if not track.stem_audio_path or not os.path.exists(track.stem_audio_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Selected stem preview is not available",
        )

    return _range_file_response(
        track.stem_audio_path,
        request.headers.get("range"),
        media_type="audio/wav",
    )


@router.patch("/{transcription_id}/tracks/{track_id}", response_model=schemas.InstrumentTrack)
async def update_instrument_track_metadata(
    transcription_id: int,
    track_id: int,
    update: schemas.InstrumentTrackUpdate,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Update user-correctable instrument track metadata.
    """
    _get_accessible_transcription(transcription_id, db_session, current_user)

    track = db_session.query(models.InstrumentTrack).filter(
        models.InstrumentTrack.id == track_id,
        models.InstrumentTrack.transcription_id == transcription_id,
    ).first()

    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument track not found"
        )

    changes = update.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(track, field, value)

    db_session.add(track)
    db_session.commit()
    db_session.refresh(track)
    return track


@router.post("/{transcription_id}/tracks/{track_id}/reprocess", response_model=schemas.InstrumentTrack)
async def reprocess_instrument_track_endpoint(
    transcription_id: int,
    track_id: int,
    background_tasks: BackgroundTasks,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Reprocess one supported instrument track from its retained separated stem.
    """
    transcription, track = _get_accessible_track(
        transcription_id,
        track_id,
        db_session,
        current_user,
    )
    return _queue_instrument_track_reprocess(
        transcription,
        track,
        background_tasks,
        db_session,
        current_user,
    )


@router.get("/{transcription_id}/tracks/{track_id}/tab")
async def get_instrument_track_tab(
    transcription_id: int,
    track_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Export ASCII tab for one instrument track.
    """
    transcription, track = _get_accessible_track(
        transcription_id, track_id, db_session, current_user
    )
    _ensure_track_export_ready(transcription, track, format_name="tab")

    if not track.tab_json:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tab export is not available for {track.display_name}"
        )

    try:
        tablature_dict = json.loads(track.tab_json)
        ascii_tab = tablature_to_ascii_tab(tablature_dict)
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating {track.display_name} ASCII tab: {str(e)}"
        )

    return Response(
        content=ascii_tab,
        media_type="text/plain",
        headers={
            "Content-Disposition": (
                f"attachment; filename={_track_export_filename(transcription_id, track, 'tab')}"
            )
        },
    )


@router.get("/{transcription_id}/tracks/{track_id}/midi")
async def get_instrument_track_midi(
    transcription_id: int,
    track_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Export MIDI for one instrument track.
    """
    transcription, track = _get_accessible_track(
        transcription_id, track_id, db_session, current_user
    )
    _ensure_track_export_ready(transcription, track, format_name="midi")

    try:
        midi_bytes = _track_notes_to_midi_bytes(track)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not generate {track.display_name} MIDI file: {str(e)}"
        )

    return Response(
        content=midi_bytes,
        media_type="audio/midi",
        headers={
            "Content-Disposition": (
                f"attachment; filename={_track_export_filename(transcription_id, track, 'mid')}"
            )
        },
    )


@router.get("/{transcription_id}/tracks/{track_id}/musicxml")
async def get_instrument_track_musicxml(
    transcription_id: int,
    track_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Export MusicXML for one instrument track.
    """
    transcription, track = _get_accessible_track(
        transcription_id, track_id, db_session, current_user
    )
    _ensure_track_export_ready(transcription, track, format_name="musicxml")

    if not track.notation_json:
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as temp_file:
                temp_path = temp_file.name
            midi.notes_to_midi(track.notes_json, temp_path)
            track.notation_json = midi.midi_to_musicxml(temp_path)
            db_session.add(track)
            db_session.commit()
            db_session.refresh(track)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not generate {track.display_name} MusicXML data: {exc}",
            ) from exc
        finally:
            if temp_path:
                _delete_local_file(temp_path)

    return Response(
        content=track.notation_json,
        media_type="application/xml",
        headers={
            "Content-Disposition": (
                f"attachment; filename={_track_export_filename(transcription_id, track, 'musicxml')}"
            )
        },
    )


@router.get("/{transcription_id}/midi")
async def get_transcription_midi(
    transcription_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Get the MIDI file for a completed transcription.
    """
    # Get the transcription record
    transcription = db_session.query(models.Transcription).filter(
        models.Transcription.id == transcription_id
    ).first()

    if not transcription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcription not found"
        )

    # Check if the user owns this transcription (or has access via project)
    if transcription.user_id != current_user.id:
        # Check if it's in a project the user owns
        if transcription.project_id:
            project = db_session.query(models.Project).filter(
                models.Project.id == transcription.project_id
            ).first()
            if not project or project.owner_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to access this transcription"
                )
        else:
            # Not in a project and not owned by user
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this transcription"
            )

    # Check if processing is complete
    if not transcription.is_processed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcription is still processing"
        )

    blocking_error = _blocking_processing_error(transcription)
    if blocking_error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transcription failed: {blocking_error}"
        )

    _require_transcription_export_supported(transcription, "midi")
    try:
        _ensure_derived_outputs(transcription, db_session)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not generate MIDI file: {str(e)}"
        )

    _require_note_events_for_export(transcription)

    if transcription.midi_file_url:
        return RedirectResponse(transcription.midi_file_url)

    # Check if MIDI file exists
    if not transcription.midi_file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MIDI file not available"
        )

    normalized_midi_path = storage.normalize_local_path(transcription.midi_file_path)
    midi_path = Path(normalized_midi_path)
    if not midi_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MIDI file not available"
        )

    # Return the MIDI file
    return FileResponse(
        path=str(midi_path),
        media_type='audio/midi',
        filename=f"transcription_{transcription_id}.mid"
    )


@router.get("/{transcription_id}/musicxml")
async def get_transcription_musicxml(
    transcription_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Get the MusicXML file for a completed transcription.
    """
    # Get the transcription record
    transcription = db_session.query(models.Transcription).filter(
        models.Transcription.id == transcription_id
    ).first()

    if not transcription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcription not found"
        )

    # Check if the user owns this transcription (or has access via project)
    if transcription.user_id != current_user.id:
        # Check if it's in a project the user owns
        if transcription.project_id:
            project = db_session.query(models.Project).filter(
                models.Project.id == transcription.project_id
            ).first()
            if not project or project.owner_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to access this transcription"
                )
        else:
            # Not in a project and not owned by user
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this transcription"
            )

    # Check if processing is complete
    if not transcription.is_processed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcription is still processing"
        )

    blocking_error = _blocking_processing_error(transcription)
    if blocking_error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transcription failed: {blocking_error}"
        )

    _require_transcription_export_supported(transcription, "musicxml")
    try:
        _ensure_derived_outputs(transcription, db_session)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not generate MusicXML data: {str(e)}"
        )

    _require_note_events_for_export(transcription)

    # Check if MusicXML data exists
    if not transcription.notation_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MusicXML data not available"
        )

    # Return the MusicXML data as a string with the appropriate media type
    return Response(
        content=transcription.notation_data,
        media_type='application/xml',
        headers={
            "Content-Disposition": f"attachment; filename=transcription_{transcription_id}.musicxml"
        }
    )


@router.get("/{transcription_id}/tab")
async def get_transcription_tab(
    transcription_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Get the ASCII tab file for a completed transcription.
    """
    # Get the transcription record
    transcription = db_session.query(models.Transcription).filter(
        models.Transcription.id == transcription_id
    ).first()

    if not transcription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcription not found"
        )

    # Check if the user owns this transcription (or has access via project)
    if transcription.user_id != current_user.id:
        # Check if it's in a project the user owns
        if transcription.project_id:
            project = db_session.query(models.Project).filter(
                models.Project.id == transcription.project_id
            ).first()
            if not project or project.owner_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to access this transcription"
                )
        else:
            # Not in a project and not owned by user
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this transcription"
            )

    # Check if processing is complete
    if not transcription.is_processed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcription is still processing"
        )

    blocking_error = _blocking_processing_error(transcription)
    if blocking_error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transcription failed: {blocking_error}"
        )

    _require_transcription_export_supported(transcription, "tab")
    try:
        _ensure_derived_outputs(transcription, db_session)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not generate tablature data: {str(e)}"
        )

    _require_note_events_for_export(transcription)

    if transcription.tab_file_url:
        return RedirectResponse(transcription.tab_file_url)

    # Check if tablature data exists
    if not transcription.tablature_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tablature data not available"
        )

    # Parse tablature data and generate ASCII tab
    try:
        tablature_dict = json.loads(transcription.tablature_data)
        ascii_tab = tablature_to_ascii_tab(tablature_dict)
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating ASCII tab: {str(e)}"
        )

    # Return as plain text file
    return Response(
        content=ascii_tab,
        media_type='text/plain',
        headers={
            "Content-Disposition": f"attachment; filename=transcription_{transcription_id}.tab"
        }
    )
