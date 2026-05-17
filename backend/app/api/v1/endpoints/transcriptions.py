from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .... import db
from ....core.security import get_current_user
from .. import schemas
from .audio import _get_accessible_transcription, _soft_delete_transcription

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
