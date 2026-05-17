import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from .... import core, db, models
from .. import schemas

router = APIRouter()
logger = logging.getLogger(__name__)

VALID_SELECTED_STEMS = {"vocals", "drums", "bass", "other"}
STEM_TO_ANALYSIS_INSTRUMENT = {
    "vocals": "vocals",
    "drums": "drums",
    "bass": "bass",
    "other": "guitar",
}
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
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Worker API token is not configured.",
        )

    bearer_token = None
    if authorization:
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() == "bearer" and credentials:
            bearer_token = credentials.strip()

    provided_token = bearer_token or x_worker_token
    if provided_token != expected_token:
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


def _sanitize_worker_error(error: str) -> str:
    cleaned = " ".join(error.split())
    if not cleaned:
        return "Worker processing failed."
    return cleaned[:500]


def _build_worker_job(transcription: models.Transcription, request: Request) -> schemas.WorkerJob:
    selected_stem = transcription.selected_stem or "other"
    if selected_stem not in VALID_SELECTED_STEMS:
        selected_stem = "other"

    base_url = str(request.base_url).rstrip("/")
    return schemas.WorkerJob(
        transcription_id=transcription.id,
        selected_stem=selected_stem,
        demucs_stem=selected_stem,
        original_audio_url=transcription.original_audio_url,
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
    transcription = (
        db_session.query(models.Transcription)
        .filter(models.Transcription.processing_status.in_(["pending", "queued"]))
        .filter(models.Transcription.is_deleted == False)
        .filter(models.Transcription.original_audio_url.isnot(None))
        .order_by(models.Transcription.created_at.asc(), models.Transcription.id.asc())
        .first()
    )

    if not transcription:
        return None

    transcription.processing_status = "processing"
    transcription.queue_position = 0
    transcription.estimated_wait_time = 0
    transcription.processing_error = None
    db_session.add(transcription)
    db_session.commit()
    db_session.refresh(transcription)
    return _build_worker_job(transcription, request)


@router.post(
    "/jobs/{transcription_id}/complete",
    response_model=schemas.TranscriptionInDB,
    dependencies=[Depends(_worker_token_dependency)],
)
async def complete_worker_job(
    transcription_id: int,
    payload: schemas.WorkerCompleteRequest,
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

    transcription.separated_audio_url = payload.separated_audio_url
    transcription.separated_audio_public_id = payload.separated_audio_public_id
    transcription.midi_file_url = payload.midi_file_url
    transcription.midi_file_public_id = payload.midi_file_public_id
    transcription.tab_file_url = payload.tab_file_url
    transcription.tab_file_public_id = payload.tab_file_public_id
    transcription.duration = payload.duration if payload.duration is not None else transcription.duration
    transcription.detected_tempo = payload.detected_tempo
    transcription.tempo_confidence = payload.tempo_confidence
    transcription.detected_key = payload.detected_key
    transcription.key_confidence = payload.key_confidence
    transcription.notes_data = _json_or_text(payload.notes_data)
    transcription.chords_data = _json_or_text(payload.chords_data)
    transcription.tablature_data = _json_or_text(payload.tablature_data)
    transcription.notation_data = _json_or_text(payload.notation_data)
    transcription.chord_chart_data = _json_or_text(payload.chord_chart_data)
    transcription.processing_status = "completed"
    transcription.is_processed = True
    transcription.processing_error = None
    transcription.queue_position = None
    transcription.estimated_wait_time = None
    transcription.celery_task_id = None

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
    track.processing_status = "completed"
    db_session.add(track)

    db_session.add(transcription)
    db_session.commit()
    db_session.refresh(transcription)
    return transcription


@router.post(
    "/jobs/{transcription_id}/failed",
    response_model=schemas.TranscriptionInDB,
    dependencies=[Depends(_worker_token_dependency)],
)
async def fail_worker_job(
    transcription_id: int,
    payload: schemas.WorkerFailedRequest,
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
            detail="Transcription was deleted before worker failure callback.",
        )

    sanitized_error = _sanitize_worker_error(payload.error)
    if payload.internal_logs:
        logger.error(
            "Worker failed transcription %s. User error: %s. Internal logs: %s",
            transcription_id,
            sanitized_error,
            payload.internal_logs,
        )

    transcription.processing_status = "failed"
    transcription.is_processed = False
    transcription.processing_error = sanitized_error
    transcription.queue_position = None
    transcription.estimated_wait_time = None
    transcription.celery_task_id = None
    db_session.add(transcription)
    db_session.commit()
    db_session.refresh(transcription)
    return transcription
