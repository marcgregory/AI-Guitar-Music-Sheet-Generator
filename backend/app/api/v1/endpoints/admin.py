from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from .... import db, models
from ....core.config import settings

router = APIRouter()

ACTIVE_JOB_STATUSES = {"pending", "queued", "processing"}
ACTIVE_MODAL_DISPATCH_STATUSES = {"dispatched", "rate_limited", "retry_queued"}
TERMINAL_JOB_STATUSES = {"completed", "completed_with_warning", "failed"}
TERMINAL_MODAL_DISPATCH_STATUSES = {"completed", "failed"}


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
