from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .... import schemas
from ....core.security import get_current_user
from ....services.usage_limits import user_usage_summary
from .... import db

router = APIRouter()


@router.get("/me", response_model=schemas.UserUsage)
def read_current_user_usage(
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user),
) -> dict[str, object]:
    return user_usage_summary(db_session, current_user.id)
