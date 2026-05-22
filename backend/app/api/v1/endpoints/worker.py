import json
import logging
import secrets
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .... import core, db, models
from ....services import tablature
from .. import schemas
from .audio import _promote_oldest_queued_transcription, _trigger_next_queued_transcription

router = APIRouter()
logger = logging.getLogger(__name__)

VALID_SELECTED_STEMS = {"vocals", "drums", "bass", "other"}
STEM_TO_ANALYSIS_INSTRUMENT = {
    "vocals": "vocals",
    "drums": "drums",
    "bass": "bass",
    "other": "guitar",
}


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
INSTRUMENT_DISPLAY_NAMES = {
    "vocals": "Vocals",
    "drums": "Drums",
    "bass": "Bass",
    "other": "Guitar / Other",
}


def _worker_token_dependency(
    authorization: str | None = Header(default=None),
    x_worker_token: str | None = Header(default=None),
) -> None:
    expected_token = core.config.settings.WORKER_API_TOKEN
    if not expected_token:
        logger.error("WORKER_API_TOKEN is not configured; rejecting worker callback.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Worker API token is not configured.",
        )

    bearer_token = None
    if authorization:
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() == "bearer" and credentials:
            bearer_token = credentials.strip()

    provided_token = (bearer_token or x_worker_token or "").strip()
    if not secrets.compare_digest(provided_token, expected_token.strip()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid worker token.",
        )


def _json_or_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _sanitize_worker_error(error: str | None) -> str:
    cleaned = " ".join(str(error or "").split())
    if not cleaned:
        return "Worker processing failed."
    return cleaned[:500]


def _payload_has_note_events(value: Any) -> bool:
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, dict):
        notes = value.get("notes")
        pitch_info = value.get("pitch_info")
        return (
            isinstance(notes, list) and len(notes) > 0
        ) or (
            isinstance(pitch_info, list) and len(pitch_info) > 0
        )
    return False


def _payload_has_tablature_data(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return False
    if isinstance(value, dict):
        return bool(value.get("tablature") is not None or value.get("tracks") is not None)
    if isinstance(value, list):
        return bool(value)
    return False


def _structured_tablature_payload(
    selected_stem: str,
    notes_data: Any,
    tablature_data: Any,
) -> Any:
    if _payload_has_tablature_data(tablature_data):
        return tablature_data
    if selected_stem not in {"bass", "other"} or not _payload_has_note_events(notes_data):
        return tablature_data

    instrument_type = "bass" if selected_stem == "bass" else "guitar"
    return tablature.notes_to_tablature(notes_data, instrument_type=instrument_type)


def _payload_has_drum_hits(value: Any) -> bool:
    if isinstance(value, dict):
        drum_hits = value.get("drum_hits")
        return isinstance(drum_hits, list) and len(drum_hits) > 0
    return False


def _build_worker_job(transcription: models.Transcription, request: Request) -> schemas.WorkerJob:
    selected_stem = transcription.selected_stem or "other"
    if selected_stem not in VALID_SELECTED_STEMS:
        selected_stem = "other"

    base_url = str(request.base_url).rstrip("/")
    return schemas.WorkerJob(
        transcription_id=transcription.id,
        job_type=transcription.modal_job_type or "process",
        modal_request_id=transcription.modal_request_id,
        selected_stem=selected_stem,
        demucs_stem=selected_stem,
        original_audio_url=transcription.original_audio_url,
        separated_audio_url=transcription.separated_audio_url,
        source_type=transcription.source_type,
        source_url=transcription.source_url or transcription.youtube_url,
        normalized_source_id=transcription.normalized_source_id,
        audio_hash=transcription.audio_hash,
        callback_complete_url=(
            f"{base_url}{core.config.settings.API_V1_STR}/worker/jobs/"
            f"{transcription.id}/complete"
        ),
        callback_failed_url=(
            f"{base_url}{core.config.settings.API_V1_STR}/worker/jobs/"
            f"{transcription.id}/failed"
        ),
    )


@router.get(
    "/jobs/next",
    response_model=schemas.WorkerJob | None,
    dependencies=[Depends(_worker_token_dependency)],
)
async def get_next_worker_job(
    request: Request,
    db_session: Session = Depends(db.get_db),
):
    transcription = _promote_oldest_queued_transcription(db_session)
    if not transcription:
        return None

    return _build_worker_job(transcription, request)


@router.post(
    "/jobs/{transcription_id}/complete",
    response_model=schemas.TranscriptionInDB,
    dependencies=[Depends(_worker_token_dependency)],
)
async def complete_worker_job(
    transcription_id: int,
    payload: schemas.WorkerCompleteRequest,
    background_tasks: BackgroundTasks,
    db_session: Session = Depends(db.get_db),
):
    transcription = db_session.query(models.Transcription).filter(
        models.Transcription.id == transcription_id
    ).first()
    if not transcription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transcription not found")
    if transcription.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transcription was deleted before worker completion.",
        )

    is_generate_lyrics_job = transcription.modal_job_type == "generate_lyrics"
    if is_generate_lyrics_job:
        lyrics_payload = payload.lyrics_data if isinstance(payload.lyrics_data, dict) else {}
        lyrics_text = str(lyrics_payload.get("text") or "").strip()
        transcription.lyrics_data = _json_or_text(payload.lyrics_data)
        transcription.lyrics_generation_status = (
            "completed" if lyrics_text else "completed_with_warning"
        )
        transcription.processing_error = None
        transcription.modal_dispatch_status = "completed"
        transcription.modal_retry_at = None
        transcription.modal_retry_count = 0
        transcription.celery_task_id = None
        db_session.add(transcription)
        db_session.commit()
        db_session.refresh(transcription)
        logger.info(
            "lyrics_generation_completed transcription_id=%s selected_stem=%s segment_count=%s detected_language=%s",
            transcription.id,
            transcription.selected_stem,
            len(lyrics_payload.get("segments") or []),
            lyrics_payload.get("language"),
        )
        return transcription

    separated_audio_url = (payload.separated_audio_url or "").strip()
    if separated_audio_url.startswith("https://"):
        transcription.separated_audio_url = separated_audio_url
        transcription.separated_audio_public_id = payload.separated_audio_public_id
    else:
        transcription.separated_audio_url = None
        transcription.separated_audio_public_id = None
    transcription.midi_file_url = payload.midi_file_url
    transcription.midi_file_public_id = payload.midi_file_public_id
    transcription.tab_file_url = payload.tab_file_url
    transcription.tab_file_public_id = payload.tab_file_public_id
    transcription.duration = payload.duration if payload.duration is not None else transcription.duration
    transcription.detected_tempo = payload.detected_tempo
    transcription.tempo_confidence = payload.tempo_confidence
    transcription.detected_key = payload.detected_key
    transcription.key_confidence = payload.key_confidence
    selected_stem = transcription.selected_stem or "other"
    is_generate_tab_job = transcription.modal_job_type == "generate_tab"
    transcription.notes_data = _json_or_text(payload.notes_data)
    transcription.chords_data = _json_or_text(payload.chords_data)
    transcription.chord_chart_data = _json_or_text(payload.chord_chart_data)
    has_notes = _payload_has_note_events(payload.notes_data)
    has_drum_hits = _payload_has_drum_hits(payload.notes_data)
    missing_required_tablature = False
    try:
        structured_tablature_data = (
            _structured_tablature_payload(
                selected_stem,
                payload.notes_data,
                payload.tablature_data,
            )
            if is_generate_tab_job
            else payload.tablature_data
        )
        transcription.tablature_data = _json_or_text(structured_tablature_data)
    except Exception:
        logger.exception(
            "worker_structured_tablature_failed transcription_id=%s selected_stem=%s",
            transcription.id,
            selected_stem,
        )
        transcription.tablature_data = _json_or_text(payload.tablature_data)
        missing_required_tablature = True
    warning_message = None
    if selected_stem in {"vocals"}:
        warning_message = "Stem separated successfully, but notation generation is not supported for this stem in the MVP."
    elif selected_stem == "drums" and not has_drum_hits:
        warning_message = "Drum stem separated successfully, but no usable hits were detected."
    elif selected_stem in {"bass", "other"} and not has_notes:
        warning_message = "No note events detected for this stem."
    transcription.warning_message = warning_message
    transcription.can_play_stem = bool(
        transcription.separated_audio_url or transcription.separated_audio_file_path
    )
    if (
        transcription.notes_data is None
        and selected_stem in {"bass", "other"}
        and warning_message == "No note events detected for this stem."
    ):
        transcription.notes_data = json.dumps(
            {"notes": [], "message": warning_message}
        )
    if is_generate_tab_job:
        transcription.can_generate_score = bool(selected_stem in {"bass", "other"} and has_notes)
        if (
            selected_stem in {"bass", "other"}
            and has_notes
            and (missing_required_tablature or not transcription.tablature_data)
        ):
            _set_manual_generation_status(transcription, "failed")
            warning_message = (
                "Tab generation finished without structured tablature data. "
                "Please try generating tabs again."
            )
            transcription.warning_message = warning_message
            transcription.processing_status = "stem_ready"
            transcription.processing_error = warning_message
            transcription.can_generate_score = False
        else:
            _set_manual_generation_status(transcription, "completed")
            transcription.processing_status = (
                "completed"
                if transcription.can_generate_score or (selected_stem == "drums" and has_drum_hits)
                else "completed_with_warning"
                if warning_message
                else "stem_ready"
            )
            transcription.processing_error = None
    else:
        transcription.can_generate_score = False
        transcription.processing_status = "stem_ready"
    transcription.is_processed = True
    if not (
        is_generate_tab_job
        and selected_stem in {"bass", "other"}
        and has_notes
        and (missing_required_tablature or not transcription.tablature_data)
    ):
        transcription.processing_error = None
    transcription.queue_position = None
    transcription.estimated_wait_time = None
    transcription.celery_task_id = None
    transcription.modal_dispatch_status = "completed"
    transcription.modal_retry_at = None
    transcription.modal_retry_count = 0

    selected_stem = transcription.selected_stem or "other"
    instrument_type = STEM_TO_ANALYSIS_INSTRUMENT.get(selected_stem, selected_stem)
    display_name = INSTRUMENT_DISPLAY_NAMES.get(selected_stem, selected_stem.title())
    track = (
        db_session.query(models.InstrumentTrack)
        .filter(models.InstrumentTrack.transcription_id == transcription.id)
        .filter(models.InstrumentTrack.instrument_type == instrument_type)
        .first()
    )
    if not track:
        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type=instrument_type,
            display_name=display_name,
        )
    if payload.track_metadata:
        track.display_name = str(payload.track_metadata.get("display_name") or track.display_name)
        track.confidence_notes = payload.track_metadata.get("confidence_notes")
    track.notes_json = transcription.notes_data
    track.chords_json = transcription.chords_data
    track.tab_json = transcription.tablature_data
    track.notation_json = transcription.notation_data
    track.confidence_score = payload.confidence
    track.processing_status = transcription.processing_status
    if not track.confidence_notes:
        track.confidence_notes = "Selected stem separated by worker."
    db_session.add(track)

    db_session.add(transcription)
    db_session.commit()
    db_session.refresh(transcription)
    _trigger_next_queued_transcription(background_tasks, db_session)
    return transcription


@router.post(
    "/jobs/{transcription_id}/failed",
    response_model=schemas.TranscriptionInDB,
    dependencies=[Depends(_worker_token_dependency)],
)
async def fail_worker_job(
    transcription_id: int,
    payload: schemas.WorkerFailedRequest,
    background_tasks: BackgroundTasks,
    db_session: Session = Depends(db.get_db),
):
    try:
        transcription = db_session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).first()
        if not transcription:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "status": "not_found",
                    "transcription_id": transcription_id,
                    "detail": "Transcription not found",
                },
            )
        if transcription.is_deleted:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "status": "deleted",
                    "transcription_id": transcription_id,
                    "detail": "Transcription was deleted before worker failure callback.",
                },
            )

        sanitized_error = _sanitize_worker_error(payload.error)
        logger.error(
            "Worker failed transcription %s. User error: %s. Internal logs: %s",
            transcription_id,
            sanitized_error,
            _json_or_text(payload.internal_logs) if payload.internal_logs else None,
        )

        if transcription.modal_job_type == "generate_lyrics":
            transcription.lyrics_generation_status = "failed"
            transcription.processing_error = "Lyrics generation failed. Please try again with a clearer vocal stem."
            transcription.celery_task_id = None
            transcription.modal_dispatch_status = "failed"
            transcription.modal_retry_at = None
            logger.error(
                "lyrics_generation_failed transcription_id=%s selected_stem=%s error=%s",
                transcription_id,
                transcription.selected_stem,
                sanitized_error,
            )
        elif transcription.modal_job_type == "generate_tab":
            _set_manual_generation_status(transcription, "failed")
            transcription.processing_status = "stem_ready"
            transcription.is_processed = True
            transcription.processing_error = sanitized_error
            transcription.queue_position = None
            transcription.estimated_wait_time = None
            transcription.celery_task_id = None
            transcription.modal_dispatch_status = "failed"
            transcription.modal_retry_at = None
        else:
            transcription.processing_status = "failed"
            transcription.is_processed = False
            transcription.processing_error = sanitized_error
            transcription.queue_position = None
            transcription.estimated_wait_time = None
            transcription.celery_task_id = None
            transcription.modal_dispatch_status = "failed"
            transcription.modal_retry_at = None
        db_session.add(transcription)
        db_session.commit()
        db_session.refresh(transcription)
        try:
            _trigger_next_queued_transcription(background_tasks, db_session)
        except Exception:
            logger.exception(
                "Worker failure callback was recorded for transcription %s, "
                "but promoting the next queued job failed.",
                transcription_id,
            )
        return transcription
    except Exception as exc:
        db_session.rollback()
        logger.exception(
            "Failed to handle worker failure callback for transcription %s. Payload: %s",
            transcription_id,
            payload.model_dump() if hasattr(payload, "model_dump") else payload.dict(),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": "error",
                "transcription_id": transcription_id,
                "detail": "Worker failure callback could not be recorded.",
                "error": str(exc),
            },
        )
