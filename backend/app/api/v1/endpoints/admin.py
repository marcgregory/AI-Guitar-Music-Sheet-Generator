from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from .... import db, models
from ....core.config import LOCAL_ENVIRONMENTS, settings

router = APIRouter()

ACTIVE_JOB_STATUSES = {"pending", "queued", "processing"}
ACTIVE_MODAL_DISPATCH_STATUSES = {"dispatched", "rate_limited", "retry_queued"}
TERMINAL_JOB_STATUSES = {"completed", "completed_with_warning", "failed"}
TERMINAL_MODAL_DISPATCH_STATUSES = {"completed", "failed"}


class AdminUsageResetRequest(BaseModel):
    user_id: int


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
        return "failed"
    return dispatch_status


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _duration_seconds(transcription: models.Transcription) -> int | None:
    started_at = transcription.modal_dispatched_at or transcription.created_at
    finished_at = transcription.updated_at
    if not started_at or not finished_at or finished_at < started_at:
        return None
    return int((finished_at - started_at).total_seconds())


def _utc_day_window(day: date | None = None) -> tuple[datetime, datetime, date]:
    selected_day = day or datetime.now(timezone.utc).date()
    day_start = datetime.combine(selected_day, time.min, tzinfo=timezone.utc)
    return day_start, day_start + timedelta(days=1), selected_day


def _admin_usage_reset_available() -> bool:
    environment = (settings.ENVIRONMENT or "").strip().lower()
    return environment in LOCAL_ENVIRONMENTS or bool(settings.ENABLE_ADMIN_USAGE_RESET)


def _require_admin_token(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    expected = (settings.ADMIN_API_TOKEN or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API is not configured.",
        )
    if not x_admin_token or x_admin_token.strip() != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin token.",
        )


def _job_payload(transcription: models.Transcription) -> dict[str, Any]:
    owner = transcription.user
    return {
        "id": transcription.id,
        "title": transcription.title,
        "user_id": transcription.user_id,
        "user_email": owner.email if owner else None,
        "selected_stem": transcription.selected_stem,
        "processing_status": transcription.processing_status,
        "queue_position": transcription.queue_position,
        "estimated_wait_time": transcription.estimated_wait_time,
        "modal_job_type": transcription.modal_job_type,
        "modal_dispatch_status": transcription.modal_dispatch_status,
        "modal_status_detail": _modal_status_detail(transcription),
        "modal_request_id": transcription.modal_request_id,
        "modal_retry_count": transcription.modal_retry_count,
        "modal_retry_at": _isoformat(transcription.modal_retry_at),
        "modal_dispatched_at": _isoformat(transcription.modal_dispatched_at),
        "duration_seconds": _duration_seconds(transcription),
        "last_error": transcription.processing_error,
        "warning_message": transcription.warning_message,
        "created_at": _isoformat(transcription.created_at),
        "updated_at": _isoformat(transcription.updated_at),
    }


@router.get("/jobs")
def list_active_jobs(
    _: None = Depends(_require_admin_token),
    db_session: Session = Depends(db.get_db),
) -> dict[str, Any]:
    jobs = (
        db_session.query(models.Transcription)
        .join(models.User, models.Transcription.user_id == models.User.id, isouter=True)
        .filter(models.Transcription.is_deleted == False)
        .filter(
            (models.Transcription.processing_status.in_(ACTIVE_JOB_STATUSES))
            | (models.Transcription.modal_dispatch_status.in_(ACTIVE_MODAL_DISPATCH_STATUSES))
        )
        .order_by(
            models.Transcription.modal_retry_at.asc().nullslast(),
            models.Transcription.queue_position.asc().nullslast(),
            models.Transcription.created_at.asc(),
            models.Transcription.id.asc(),
        )
        .all()
    )

    return {
        "jobs": [_job_payload(job) for job in jobs],
        "counts": {
            "active": len(jobs),
            "queued": sum(1 for job in jobs if job.processing_status == "queued"),
            "processing": sum(1 for job in jobs if job.processing_status == "processing"),
            "rate_limited": sum(
                1
                for job in jobs
                if job.modal_dispatch_status in {"rate_limited", "retry_queued"}
            ),
        },
    }


def _usage_payload(
    user: models.User,
    *,
    usage_count: int,
    active_job_count: int,
) -> dict[str, Any]:
    daily_limit = max(0, int(settings.DAILY_PROCESSING_JOB_LIMIT))
    remaining_quota = max(0, daily_limit - usage_count) if daily_limit > 0 else 0
    return {
        "user_id": user.id,
        "username": user.username,
        "usage_count": usage_count,
        "daily_limit": daily_limit,
        "remaining_quota": remaining_quota,
        "active_job_count": active_job_count,
        "reset_available": _admin_usage_reset_available(),
    }


def _active_usage_job_counts(
    db_session: Session,
    user_ids: set[int] | None = None,
) -> dict[int, int]:
    query = (
        db_session.query(models.Transcription.user_id, func.count(models.Transcription.id))
        .filter(models.Transcription.is_deleted == False)
        .filter(models.Transcription.is_demo == False)
        .filter(models.Transcription.processing_status.in_(ACTIVE_JOB_STATUSES))
    )
    if user_ids is not None:
        if not user_ids:
            return {}
        query = query.filter(models.Transcription.user_id.in_(user_ids))
    return {user_id: count for user_id, count in query.group_by(models.Transcription.user_id)}


def _usage_event_counts(
    db_session: Session,
    *,
    day_start: datetime,
    day_end: datetime,
    user_ids: set[int] | None = None,
) -> dict[int, int]:
    query = (
        db_session.query(models.UsageEvent.user_id, func.count(models.UsageEvent.id))
        .filter(models.UsageEvent.created_at >= day_start)
        .filter(models.UsageEvent.created_at < day_end)
    )
    if user_ids is not None:
        if not user_ids:
            return {}
        query = query.filter(models.UsageEvent.user_id.in_(user_ids))
    return {user_id: count for user_id, count in query.group_by(models.UsageEvent.user_id)}


def _usage_rows(
    db_session: Session,
    *,
    selected_date: date | None = None,
    user_id: int | None = None,
) -> tuple[list[dict[str, Any]], date]:
    day_start, day_end, resolved_date = _utc_day_window(selected_date)

    if user_id is not None:
        user = db_session.query(models.User).filter(models.User.id == user_id).first()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )
        user_ids = {user.id}
    else:
        usage_user_ids = {
            user_id
            for (user_id,) in (
                db_session.query(models.UsageEvent.user_id)
                .filter(models.UsageEvent.created_at >= day_start)
                .filter(models.UsageEvent.created_at < day_end)
                .distinct()
                .all()
            )
        }
        active_user_ids = {
            active_user_id
            for (active_user_id,) in (
                db_session.query(models.Transcription.user_id)
                .filter(models.Transcription.is_deleted == False)
                .filter(models.Transcription.is_demo == False)
                .filter(models.Transcription.processing_status.in_(ACTIVE_JOB_STATUSES))
                .distinct()
                .all()
            )
        }
        user_ids = usage_user_ids | active_user_ids

    usage_counts = _usage_event_counts(
        db_session,
        day_start=day_start,
        day_end=day_end,
        user_ids=user_ids,
    )
    active_counts = _active_usage_job_counts(db_session, user_ids)

    users = (
        db_session.query(models.User)
        .filter(models.User.id.in_(user_ids))
        .order_by(models.User.username.asc(), models.User.id.asc())
        .all()
        if user_ids
        else []
    )
    rows = [
        _usage_payload(
            user,
            usage_count=usage_counts.get(user.id, 0),
            active_job_count=active_counts.get(user.id, 0),
        )
        for user in users
    ]
    return rows, resolved_date


@router.get("/usage")
def list_usage_limits(
    _: None = Depends(_require_admin_token),
    db_session: Session = Depends(db.get_db),
    user_id: int | None = Query(default=None, ge=1),
    usage_date: date | None = Query(default=None, alias="date"),
) -> dict[str, Any]:
    usage_rows, resolved_date = _usage_rows(
        db_session,
        selected_date=usage_date,
        user_id=user_id,
    )
    return {
        "date": resolved_date.isoformat(),
        "usage": usage_rows,
        "reset_available": _admin_usage_reset_available(),
    }


@router.post("/usage/reset")
def reset_usage_limits(
    request: AdminUsageResetRequest,
    _: None = Depends(_require_admin_token),
    db_session: Session = Depends(db.get_db),
) -> dict[str, Any]:
    if not _admin_usage_reset_available():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usage reset is not available in this environment.",
        )

    user = db_session.query(models.User).filter(models.User.id == request.user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    day_start, day_end, _ = _utc_day_window()
    delete_query = (
        db_session.query(models.UsageEvent)
        .filter(models.UsageEvent.user_id == user.id)
        .filter(models.UsageEvent.created_at >= day_start)
        .filter(models.UsageEvent.created_at < day_end)
    )
    deleted_count = delete_query.count()
    delete_query.delete(synchronize_session=False)
    db_session.commit()

    usage_counts = _usage_event_counts(
        db_session,
        day_start=day_start,
        day_end=day_end,
        user_ids={user.id},
    )
    active_counts = _active_usage_job_counts(db_session, {user.id})

    return {
        "success": True,
        "deleted_count": deleted_count,
        "usage": _usage_payload(
            user,
            usage_count=usage_counts.get(user.id, 0),
            active_job_count=active_counts.get(user.id, 0),
        ),
    }


@router.get("/jobs/history")
def list_job_history(
    _: None = Depends(_require_admin_token),
    db_session: Session = Depends(db.get_db),
    status: Optional[Literal["completed", "completed_with_warning", "failed"]] = Query(
        default=None
    ),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    query = (
        db_session.query(models.Transcription)
        .join(models.User, models.Transcription.user_id == models.User.id, isouter=True)
        .filter(models.Transcription.is_deleted == False)
        .filter(models.Transcription.modal_request_id.isnot(None))
        .filter(
            (models.Transcription.processing_status.in_(TERMINAL_JOB_STATUSES))
            | (
                models.Transcription.modal_dispatch_status.in_(
                    TERMINAL_MODAL_DISPATCH_STATUSES
                )
            )
        )
    )

    if status:
        query = query.filter(models.Transcription.processing_status == status)

    jobs = (
        query.order_by(
            models.Transcription.updated_at.desc().nullslast(),
            models.Transcription.created_at.desc(),
            models.Transcription.id.desc(),
        )
        .limit(limit)
        .all()
    )

    return {
        "jobs": [_job_payload(job) for job in jobs],
        "count": len(jobs),
    }
