from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Response, Body, UploadFile, File, Form, Request
import json
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, update
import os
import uuid
import hashlib
from pathlib import Path
import re
import tempfile
import yt_dlp
import httpx
from pydantic import BaseModel
from urllib.parse import parse_qs, urlsplit
from datetime import datetime, timezone

from .... import db, core, models
from ....core.security import get_current_user
from .. import schemas
from ....services import audio
from ....services import midi
from ....services import storage
from ....services import tablature as tablature_service
from ....services.tablature import tablature_to_ascii_tab
from ....celery import celery_app

# Schema for YouTube URL request
class YouTubeUploadRequest(BaseModel):
    youtube_url: str
    selected_stem: str
    project_id: int = None

router = APIRouter()
VALID_SELECTED_STEMS = {"vocals", "drums", "bass", "other"}
ESTIMATED_SECONDS_PER_SELECTED_STEM_JOB = 300

# Define the upload directory relative to the backend package so the location is
# stable whether uvicorn is launched from the repo root or from backend/.
# BACKEND_DIR = Path(__file__).resolve().parents[4]
# UPLOAD_DIR = BACKEND_DIR / "uploads"
# UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

UPLOAD_DIR = Path(core.config.settings.UPLOAD_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

import logging
import traceback
from threading import Lock

logger = logging.getLogger(__name__)
_queue_promotion_lock = Lock()


def _run_transcription_locally(
    transcription_id: int,
    detection_sensitivity: str | None = None,
    selected_stem_override: str | None = None,
):
    """Run transcription without a Celery broker for local development."""
    from ....tasks import process_audio_transcription

    original_update_state = process_audio_transcription.update_state
    process_audio_transcription.update_state = lambda *args, **kwargs: None
    try:
        process_audio_transcription.run(
            transcription_id,
            detection_sensitivity,
            selected_stem_override,
        )
    except Exception as e:
        logger.error(
            "Local transcription task failed for transcription %s: %s",
            transcription_id,
            e,
        )
    finally:
        process_audio_transcription.update_state = original_update_state


def _run_instrument_track_reprocess_locally(track_id: int):
    """Run one track reprocess without a Celery broker for local development."""
    from ....tasks import reprocess_instrument_track

    original_update_state = reprocess_instrument_track.update_state
    reprocess_instrument_track.update_state = lambda *args, **kwargs: None
    try:
        reprocess_instrument_track.run(track_id)
    except Exception as e:
        logger.error(
            "Local instrument track reprocess failed for track %s: %s",
            track_id,
            e,
        )
    finally:
        reprocess_instrument_track.update_state = original_update_state


def _start_transcription_processing(
    transcription_id: int,
    background_tasks: BackgroundTasks,
    db_session: Session,
    *,
    detection_sensitivity: str | None = None,
    selected_stem_override: str | None = None,
) -> str | None:
    """Start processing through Celery, with an in-process fallback for dev."""
    if _should_use_local_worker_fallback() and not _celery_has_available_worker():
        logger.warning(
            "No Celery worker is available; running transcription %s as a local background task",
            transcription_id,
        )
        background_tasks.add_task(
            _run_transcription_locally,
            transcription_id,
            detection_sensitivity,
            selected_stem_override,
        )
        return None

    try:
        task_args = [transcription_id]
        if detection_sensitivity or selected_stem_override:
            task_args.extend([detection_sensitivity, selected_stem_override])
        result = celery_app.send_task(
            "app.tasks.process_audio_transcription",
            args=task_args
        )
        task_id = getattr(result, "id", None)
        return str(task_id) if isinstance(task_id, (str, int)) else None
    except Exception as e:
        logger.warning(
            "Celery broker unavailable; falling back to local background task: %s",
            e,
        )
        background_tasks.add_task(
            _run_transcription_locally,
            transcription_id,
            detection_sensitivity,
            selected_stem_override,
        )
        return None


def _processing_mode() -> str:
    mode = (core.config.settings.PROCESSING_MODE or "local").strip().lower()
    if mode not in {"local", "external_worker", "modal"}:
        logger.warning("Unknown PROCESSING_MODE=%s; falling back to local", mode)
        return "local"
    return mode


def _build_worker_payload_for_modal(transcription: models.Transcription) -> dict[str, str | int | None]:
    selected_stem = transcription.selected_stem or "other"
    return {
        "transcription_id": transcription.id,
        "selected_stem": selected_stem,
        "demucs_stem": selected_stem,
        "original_audio_url": transcription.original_audio_url,
        "source_type": transcription.source_type,
        "source_url": transcription.source_url or transcription.youtube_url,
        "normalized_source_id": transcription.normalized_source_id,
        "audio_hash": transcription.audio_hash,
    }


def _trigger_modal_worker(transcription_id: int) -> None:
    modal_trigger_url = core.config.settings.MODAL_TRIGGER_URL
    session = db.SessionLocal()
    try:
        transcription = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).first()
        if not transcription or transcription.is_deleted:
            return
        if not modal_trigger_url:
            transcription.processing_status = "queued"
            transcription.queue_position = None
            transcription.estimated_wait_time = None
            session.add(transcription)
            session.commit()
            logger.info(
                "PROCESSING_MODE=modal but MODAL_TRIGGER_URL is not configured; "
                "transcription %s remains queued.",
                transcription_id,
            )
            return

        headers = {}
        if core.config.settings.WORKER_API_TOKEN:
            headers["Authorization"] = f"Bearer {core.config.settings.WORKER_API_TOKEN}"

        response = httpx.post(
            modal_trigger_url,
            json=_build_worker_payload_for_modal(transcription),
            headers=headers,
            timeout=120.0,
)
        response.raise_for_status()
        logger.info("Triggered Modal worker for transcription %s", transcription_id)
    except Exception as exc:
        try:
            transcription = session.query(models.Transcription).filter(
                models.Transcription.id == transcription_id
            ).first()
            if transcription and transcription.processing_status == "processing":
                transcription.processing_status = "queued"
                transcription.queue_position = None
                transcription.estimated_wait_time = None
                session.add(transcription)
                session.commit()
        except Exception:
            session.rollback()
        logger.error(
            "Modal trigger failed for transcription %s; leaving job queued: %s",
            transcription_id,
            exc,
        )
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
    if mode == "local":
        return _start_transcription_processing(
            transcription.id,
            background_tasks,
            db_session,
        )
    if mode == "modal":
        logger.info("Dispatching transcription %s to Modal", transcription.id)
        background_tasks.add_task(_trigger_modal_worker, transcription.id)
        return None

    logger.info(
        "Queued transcription %s for an external selected-stem worker",
        transcription.id,
    )
    return None


def _promote_oldest_queued_transcription(db_session: Session) -> models.Transcription | None:
    with _queue_promotion_lock:
        candidate = (
            db_session.query(models.Transcription)
            .filter(models.Transcription.processing_status.in_(["pending", "queued"]))
            .filter(models.Transcription.is_deleted == False)
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
            .where(models.Transcription.processing_status.in_(["pending", "queued"]))
            .where(models.Transcription.is_deleted == False)
            .where(~active_exists)
            .values(
                processing_status="processing",
                queue_position=0,
                estimated_wait_time=0,
                processing_error=None,
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
    if _processing_mode() == "external_worker":
        logger.info(
            "PROCESSING_MODE=external_worker; queued jobs will be claimed by worker polling."
        )
        return None

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
    track_id: int,
    background_tasks: BackgroundTasks,
):
    """Start one track reprocess through Celery, with an in-process dev fallback."""
    if _should_use_local_worker_fallback() and not _celery_has_available_worker():
        logger.warning(
            "No Celery worker is available; running track %s reprocess as a local background task",
            track_id,
        )
        background_tasks.add_task(_run_instrument_track_reprocess_locally, track_id)
        return

    try:
        celery_app.send_task(
            "app.tasks.reprocess_instrument_track",
            args=[track_id]
        )
    except Exception as e:
        logger.warning(
            "Celery broker unavailable; falling back to local track reprocess: %s",
            e,
        )
        background_tasks.add_task(_run_instrument_track_reprocess_locally, track_id)


def _has_note_events(notes_data: str | None) -> bool:
    if not notes_data:
        return False
    try:
        parsed = json.loads(notes_data)
    except json.JSONDecodeError:
        return False

    if isinstance(parsed, list):
        return len(parsed) > 0
    if isinstance(parsed, dict):
        notes = parsed.get("notes")
        pitch_info = parsed.get("pitch_info")
        return (
            isinstance(notes, list) and len(notes) > 0
        ) or (
            isinstance(pitch_info, list) and len(pitch_info) > 0
        )
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
        .filter(models.Transcription.processing_status.in_(["completed", "completed_with_warning"]))
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
    previous_status = transcription.processing_status or "pending"
    if previous_status in {"queued", "pending", "processing"}:
        _revoke_transcription_task(transcription)
        transcription.processing_status = "cancelled"
        transcription.processing_error = (
            "Transcription was deleted. Active worker cancellation is best-effort."
            if previous_status == "processing"
            else "Transcription was deleted before processing completed."
        )
    elif previous_status in {"completed", "failed", "cancelled", "deleted"}:
        transcription.processing_status = "deleted"
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete transcription in {previous_status} state",
        )

    _cleanup_transcription_cloudinary_assets(transcription, db_session)
    _cleanup_transcription_local_assets(transcription)

    transcription.is_deleted = True
    transcription.deleted_at = datetime.now(timezone.utc)
    transcription.is_processed = False if transcription.processing_status == "cancelled" else transcription.is_processed
    db_session.add(transcription)
    db_session.commit()
    db_session.refresh(transcription)

    return transcription


def _cleanup_transcription_local_assets(transcription: models.Transcription) -> None:
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


def _can_generate_score(transcription: models.Transcription) -> bool:
    return bool(transcription.can_generate_score and _has_note_events(transcription.notes_data))


def _status_payload(
    transcription: models.Transcription,
    transcription_id: int,
    selected_stem: str,
    *,
    message: str | None = None,
) -> dict:
    warning = transcription.warning_message
    can_play_stem = _can_play_stem(transcription)
    can_generate_score = _can_generate_score(transcription)
    payload = {
        "status": "completed",
        "warning": warning,
        "transcription_id": transcription_id,
        "selected_stem": selected_stem,
        "can_play_stem": can_play_stem,
        "can_generate_score": can_generate_score,
        "queue_position": None,
        "estimated_wait_time": None,
    }
    if message:
        payload["message"] = message
    return payload


def _ensure_transcription_access(
    transcription: models.Transcription,
    db_session: Session,
    current_user: schemas.User,
) -> None:
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
    """Regenerate downloadable/viewable outputs from stored notes when possible."""
    if not _has_note_events(transcription.notes_data):
        return

    changed = False

    if not transcription.midi_file_path or not os.path.exists(storage.normalize_local_path(transcription.midi_file_path)):
        transcription.midi_file_path = midi.save_midi_from_transcription(
            transcription.notes_data,
            transcription.id,
            str(UPLOAD_DIR),
        )
        changed = True

    if not transcription.notation_data and transcription.midi_file_path and os.path.exists(storage.normalize_local_path(transcription.midi_file_path)):
        try:
            transcription.notation_data = midi.midi_to_musicxml(storage.normalize_local_path(transcription.midi_file_path))
            changed = True
        except Exception as e:
            logger.warning(
                "Could not regenerate MusicXML for transcription %s: %s",
                transcription.id,
                e,
            )

    if not transcription.tablature_data:
        transcription.tablature_data = json.dumps(
            tablature_service.notes_to_tablature(transcription.notes_data)
        )
        changed = True

    if changed:
        db_session.add(transcription)
        db_session.commit()
        db_session.refresh(transcription)


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
        db_session.query(models.Transcription)
        .filter(models.Transcription.user_id == user_id)
        .filter(models.Transcription.is_processed == False)
        .filter(models.Transcription.is_deleted == False)
        .all()
    )
    return any(
        transcription.processing_error is None
        or _is_non_blocking_processing_warning(transcription.processing_error)
        for transcription in active_transcriptions
    )


def _has_active_processing_job(db_session: Session) -> bool:
    return (
        db_session.query(models.Transcription)
        .filter(models.Transcription.processing_status == "processing")
        .filter(models.Transcription.is_deleted == False)
        .first()
        is not None
    )


def _active_queue_count(db_session: Session) -> int:
    return (
        db_session.query(models.Transcription)
        .filter(models.Transcription.processing_status.in_(["pending", "queued", "processing"]))
        .filter(models.Transcription.is_deleted == False)
        .count()
    )


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
        db_session.query(models.Transcription)
        .filter(models.Transcription.processing_status.in_(["pending", "queued", "processing"]))
        .filter(models.Transcription.is_deleted == False)
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
        "midi": {"guitar", "bass", "piano"},
        "musicxml": {"guitar", "bass", "piano"},
    }
    supported_instruments = supported_by_format.get(format_name, set())
    if track.instrument_type not in supported_instruments:
        supported_label = (
            "guitar and bass"
            if format_name == "tab"
            else "guitar, bass, and piano"
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


def _prepare_track_reprocess(track: models.InstrumentTrack, db_session: Session) -> None:
    if track.instrument_type not in {"guitar", "bass", "piano", "drums"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{track.display_name} reprocessing is not available yet. "
                "Single-track reprocessing currently supports guitar, bass, piano, and drum tracks."
            )
        )

    if not track.stem_audio_path or not os.path.exists(track.stem_audio_path):
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


def _track_export_filename(
    transcription_id: int,
    track: models.InstrumentTrack,
    extension: str,
) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", track.instrument_type.lower()).strip("_") or "track"
    return f"transcription_{transcription_id}_{slug}.{extension}"


def _track_notes_to_midi_bytes(track: models.InstrumentTrack) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as temp_file:
        temp_path = temp_file.name
    try:
        midi.notes_to_midi(track.notes_json, temp_path)
        with open(temp_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass

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


def _build_youtube_download_options(unique_filename: str, ffmpeg_path: str | None):
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

    return options


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
    youtube_url = request.youtube_url.strip()
    selected_stem = _validate_selected_stem(request.selected_stem)
    project_id = request.project_id

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
        user_id=current_user.id,
        selected_stem=selected_stem,
        normalized_source_id=normalized_source_id,
    )
    if duplicate:
        return _mark_duplicate_response(duplicate)

    initial_processing_status, queue_position, estimated_wait = _queue_metadata_for_new_job(db_session)

    # Generate a unique filename for the output (without extension, yt-dlp will add it)
    unique_filename = f"{uuid.uuid4().hex}"

    # Determine ffmpeg location
    ffmpeg_path = _find_ffmpeg_path()

    # Keep yt-dlp's template as a plain filename; paths.home carries the directory.
    yt_dlp_opts = _build_youtube_download_options(unique_filename, ffmpeg_path)

    logger.info(f"yt-dlp output directory: {UPLOAD_DIR}")
    logger.info(f"yt-dlp output template: {yt_dlp_opts['outtmpl']}")
    logger.info(f"ffmpeg_path: {ffmpeg_path}")

    video_title = "YouTube Audio"

    try:
        # Download and extract audio in a single pass
        with yt_dlp.YoutubeDL(yt_dlp_opts) as ydl:
            info_dict = ydl.extract_info(youtube_url, download=True)
            video_title = info_dict.get('title', 'YouTube Audio') if info_dict else 'YouTube Audio'

        # After download, the file should be at the resolved path
        audio_file_path = UPLOAD_DIR / f"{unique_filename}.wav"

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
                logger.error(f"Expected audio file not found. Files matching pattern: {existing}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to extract audio from YouTube URL. No output file found."
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"YouTube extraction failed: {traceback.format_exc()}")
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
        if project.owner_id != current_user.id:
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
        user_id=current_user.id,
        project_id=project_id,
        is_processed=False
    )
    db_session.add(db_transcription)
    db_session.commit()
    db_session.refresh(db_transcription)

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
    return (
        db_session.query(models.Transcription)
        .filter(models.Transcription.user_id == current_user.id)
        .filter(models.Transcription.is_deleted == False)
        .order_by(models.Transcription.created_at.desc(), models.Transcription.id.desc())
        .all()
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

    selected_stem = transcription.selected_stem or "other"
    if transcription.is_deleted:
        return {
            "status": transcription.processing_status or "deleted",
            "transcription_id": transcription_id,
            "selected_stem": selected_stem,
            "warning": transcription.warning_message,
            "can_play_stem": _can_play_stem(transcription),
            "can_generate_score": _can_generate_score(transcription),
            "deleted_at": transcription.deleted_at,
            "message": "This transcription record was deleted.",
            "queue_position": None,
            "estimated_wait_time": None,
        }

    blocking_error = _blocking_processing_error(transcription)
    if blocking_error or transcription.processing_status == "failed":
        return {
            "status": "failed",
            "error": blocking_error or transcription.processing_error or "Processing failed",
            "transcription_id": transcription_id,
            "selected_stem": selected_stem,
            "warning": transcription.warning_message,
            "can_play_stem": _can_play_stem(transcription),
            "can_generate_score": _can_generate_score(transcription),
            "queue_position": None,
            "estimated_wait_time": None,
        }

    # Return status based on transcription record
    if transcription.is_processed:
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
            message = (
                "Queued behind another selected-stem job. "
                "The Railway MVP worker intentionally runs one job at a time."
            )
        elif current_status == "pending":
            message = "Waiting for the selected-stem job to start."
        return {
            "status": current_status,
            "transcription_id": transcription_id,
            "selected_stem": selected_stem,
            "warning": transcription.warning_message,
            "can_play_stem": _can_play_stem(transcription),
            "can_generate_score": _can_generate_score(transcription),
            "message": message,
            "queue_position": transcription.queue_position,
            "estimated_wait_time": transcription.estimated_wait_time,
        }


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

    if transcription.original_audio_url:
        return RedirectResponse(transcription.original_audio_url)

    candidates = [
        transcription.audio_file_path,
        str(UPLOAD_DIR / Path(transcription.audio_file_path).name) if transcription.audio_file_path else None,
        transcription.separated_audio_file_path,
        transcription.preprocessed_audio_file_path,
    ]
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

    try:
        _ensure_derived_outputs(transcription, db_session)
    except Exception as e:
        logger.warning(
            "Could not regenerate derived outputs for transcription %s: %s",
            transcription_id,
            e,
        )

    # Return the transcription data
    return transcription


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

    return {
        "status": transcription.processing_status,
        "transcription_id": transcription.id,
        "selected_stem": selected_stem,
        "can_play_stem": _can_play_stem(transcription),
        "can_generate_score": transcription.can_generate_score,
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

    return (
        db_session.query(models.InstrumentTrack)
        .filter(models.InstrumentTrack.transcription_id == transcription_id)
        .order_by(models.InstrumentTrack.id.asc())
        .all()
    )


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

    return track


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
    _transcription, track = _get_accessible_track(
        transcription_id,
        track_id,
        db_session,
        current_user,
    )
    _prepare_track_reprocess(track, db_session)
    _start_instrument_track_reprocess(track.id, background_tasks)
    return track


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
        try:
            with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as temp_file:
                temp_path = temp_file.name
            try:
                midi.notes_to_midi(track.notes_json, temp_path)
                track.notation_json = midi.midi_to_musicxml(temp_path)
            finally:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            db_session.add(track)
            db_session.commit()
            db_session.refresh(track)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not generate {track.display_name} MusicXML data: {str(e)}"
            )

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
