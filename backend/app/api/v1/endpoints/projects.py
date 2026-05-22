from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .... import db, models
from ....core.security import get_current_user
from .. import schemas
from .audio import _delete_project_with_transcriptions

router = APIRouter()


@router.delete("/{project_id}", response_model=schemas.ProjectInDB)
async def delete_project(
    project_id: int,
    hard_delete: bool = Query(True),
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user),
):
    project = (
        db_session.query(models.Project)
        .filter(models.Project.id == project_id)
        .filter(models.Project.owner_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    if project.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    return _delete_project_with_transcriptions(
        project,
        db_session,
        hard_delete=hard_delete,
    )
