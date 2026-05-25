import json
import logging
import secrets
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .... import core, db, models
from ....services import storage, tablature
from ....services.audio_source_resolver import resolve_generate_tab_audio_source
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
    return tablature.has_note_events(value)


def _payload_has_tablature_data(value: Any) -> bool:
    return tablature.has_structured_tablature(value)


def _structured_tablature_payload(
    selected_stem: str,
    notes_data: Any,
    tablature_data: Any,
) -> Any:
    if _payload_has_tablature_data(tablature_data):
        return tablature_data
    if selected_stem not in {"bass", "other"} or not _payload_has_note_events(notes_data):
        return tablature_data

    repaired = tablature.repair_structured_tablature(
        selected_stem,
        notes_data,
        tablature_data,
    )
    return repaired if repaired else tablature_data


def _payload_has_drum_hits(value: Any) -> bool:
    if isinstance(value, dict):
        drum_hits = value.get("drum_hits")
        return isinstance(drum_hits, list) and len(drum_hits) > 0
    return False


def _cleanup_original_cloudinary_audio_after_tab_completion(
    transcription: models.Transcription,
) -> None:
    selected_stem = (transcription.selected_stem or "other").strip().lower()
    if selected_stem not in {"bass", "other"}:
        return
    if not tablature.has_structured_tablature(transcription.tablature_data):
        return
    if transcription.original_audio_public_id:
        storage.delete_cloudinary_asset(
            transcription.original_audio_public_id,
            resource_type="video",
        )
    transcription.original_audio_url = None
    transcription.original_audio_public_id = None


def _build_worker_job(transcription: models.Transcription, request: Request) -> schemas.WorkerJob:
    selected_stem = transcription.selected_stem or "other"
    if selected_stem not in VALID_SELECTED_STEMS:
        selected_stem = "other"
    job_type = transcription.modal_job_type or "process"
    original_audio_url = transcription.original_audio_url if job_type == "process" else None
    separated_audio_url = transcription.separated_audio_url
    if job_type == "generate_tab" and selected_stem in {"bass", "other"}:
        resolved_source = resolve_generate_tab_audio_source(transcription)
        if resolved_source != transcription.separated_audio_url:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="separated_audio_url is required for Modal tab generation.",
            )
        separated_audio_url = resolved_source
    elif job_type == "generate_tab" and not separated_audio_url:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="separated_audio_url is required for Modal tab generation.",
        )

    base_url = str(request.base_url).rstrip("/")
    return schemas.WorkerJob(
        transcription_id=transcription.id,
        job_type=job_type,
        modal_request_id=transcription.modal_request_id,
        selected_stem=selected_stem,
        demucs_stem=selected_stem,
        original_audio_url=original_audio_url,
        separated_audio_url=separated_audio_url,
        lyrics_language=None,
        source_type=transcription.source_type,
        source_url=(transcription.source_url or transcription.youtube_url) if job_type == "process" else None,
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
    is_reprocess_track_job = transcription.modal_job_type == "reprocess_track"
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
    if transcription.separated_audio_url or transcription.separated_audio_file_path:
        transcription.audio_file_path = None
        transcription.preprocessed_audio_file_path = None
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
        has_valid_tablature = tablature.has_structured_tablature(transcription.tablature_data)
        if (
            selected_stem in {"bass", "other"}
            and has_notes
            and (missing_required_tablature or not has_valid_tablature)
        ):
            _set_manual_generation_status(transcription, "completed_with_warning")
            warning_message = (
                "Tab generation completed with note events, but structured tablature "
                "could not be assembled."
            )
            transcription.warning_message = warning_message
            transcription.processing_status = "stem_ready"
            transcription.processing_error = warning_message
            transcription.can_generate_score = False
        else:
            if selected_stem in {"bass", "other"}:
                _set_manual_generation_status(
                    transcription,
                    "completed" if has_valid_tablature else "completed_with_warning",
                )
            else:
                _set_manual_generation_status(transcription, "completed")
            transcription.processing_status = (
                "completed"
                if (selected_stem in {"bass", "other"} and has_valid_tablature)
                or (selected_stem == "drums" and has_drum_hits)
                else "completed_with_warning"
                if warning_message
                else "stem_ready"
            )
            transcription.processing_error = None
            if selected_stem in {"bass", "other"} and has_valid_tablature:
                _cleanup_original_cloudinary_audio_after_tab_completion(transcription)
    else:
        transcription.can_generate_score = False
        transcription.processing_status = "stem_ready"
    transcription.is_processed = True
    if not (
        is_generate_tab_job
        and selected_stem in {"bass", "other"}
        and has_notes
        and (
            missing_required_tablature
            or not tablature.has_structured_tablature(transcription.tablature_data)
        )
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
    track_query = db_session.query(models.InstrumentTrack).filter(
        models.InstrumentTrack.transcription_id == transcription.id
    )
    if payload.track_id is not None:
        track_query = track_query.filter(models.InstrumentTrack.id == payload.track_id)
    else:
        track_query = track_query.filter(models.InstrumentTrack.instrument_type == instrument_type)
    track = track_query.first()
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
    track.processing_status = (
        "completed_with_warning"
        if is_reprocess_track_job and warning_message
        else "completed"
        if is_reprocess_track_job
        else transcription.processing_status
    )
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
        elif transcription.modal_job_type == "reprocess_track":
            track = None
            if payload.track_id is not None:
                track = db_session.query(models.InstrumentTrack).filter(
                    models.InstrumentTrack.id == payload.track_id,
                    models.InstrumentTrack.transcription_id == transcription.id,
                ).first()
            if track:
                track.processing_status = "failed"
                track.confidence_notes = sanitized_error or "Track reprocessing failed."
                db_session.add(track)
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
