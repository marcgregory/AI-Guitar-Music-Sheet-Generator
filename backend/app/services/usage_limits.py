from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import models
from app.core.config import settings


def current_utc_day_start() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def next_utc_reset_at() -> datetime:
    return current_utc_day_start() + timedelta(days=1)


def next_utc_reset_at_iso() -> str:
    return next_utc_reset_at().isoformat().replace("+00:00", "Z")


def user_daily_usage_count(db_session: Session, user_id: int) -> int:
    return (
        db_session.query(models.UsageEvent.id)
        .filter(models.UsageEvent.user_id == user_id)
        .filter(models.UsageEvent.created_at >= current_utc_day_start())
        .count()
    )


def user_usage_summary(db_session: Session, user_id: int) -> dict[str, object]:
    usage_count = user_daily_usage_count(db_session, user_id)
    daily_limit = max(0, int(settings.DAILY_PROCESSING_JOB_LIMIT))
    is_unlimited = daily_limit == 0

    if is_unlimited:
        return {
            "usage_count": usage_count,
            "daily_limit": daily_limit,
            "remaining_quota": None,
            "resets_at": None,
            "is_unlimited": True,
        }

    return {
        "usage_count": usage_count,
        "daily_limit": daily_limit,
        "remaining_quota": max(daily_limit - usage_count, 0),
        "resets_at": next_utc_reset_at_iso(),
        "is_unlimited": False,
    }
