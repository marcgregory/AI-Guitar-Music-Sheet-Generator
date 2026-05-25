from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .... import db, models
from ....core.security import get_current_user
from .. import schemas
from .audio import (
    _get_accessible_transcription,
    _queue_instrument_track_reprocess,
    _soft_delete_transcription,
    retry_transcription,
)

router = APIRouter()


@router.delete("/{transcription_id}", response_model=schemas.TranscriptionInDB)
async def delete_transcription_record(
    transcription_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user),
):
    transcription = _get_accessible_transcription(
        transcription_id,
        db_session,
        current_user,
    )
    return _soft_delete_transcription(transcription, db_session)


@router.post("/{transcription_id}/retry")
async def retry_transcription_record(
    transcription_id: int,
    retry: schemas.RetryTranscriptionRequest,
    background_tasks: BackgroundTasks,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user),
):
    return await retry_transcription(
        transcription_id,
        retry,
        background_tasks,
        db_session,
        current_user,
    )


@router.post("/{transcription_id}/reprocess", response_model=schemas.InstrumentTrack)
async def reprocess_selected_transcription_track(
    transcription_id: int,
    background_tasks: BackgroundTasks,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user),
):
    transcription = _get_accessible_transcription(
        transcription_id,
        db_session,
        current_user,
    )
    selected_instrument = {
        "other": "guitar",
        "bass": "bass",
        "drums": "drums",
        "vocals": "vocals",
    }.get(transcription.selected_stem or "other", "guitar")
    track = (
        db_session.query(models.InstrumentTrack)
        .filter(models.InstrumentTrack.transcription_id == transcription.id)
        .filter(models.InstrumentTrack.instrument_type == selected_instrument)
        .order_by(models.InstrumentTrack.id.desc())
        .first()
    )
    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Selected stem track is not available for reprocessing.",
        )

    return _queue_instrument_track_reprocess(
        transcription,
        track,
        background_tasks,
        db_session,
        current_user,
    )
