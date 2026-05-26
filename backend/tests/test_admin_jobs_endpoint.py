from datetime import datetime, timedelta, timezone

from app import models
from app.core import config
from test_audio_list_endpoint import (
    TestingSessionLocal,
    client,
    create_user,
    reset_database,
)


def _create_job(username: str, **overrides) -> int:
    session = TestingSessionLocal()
    try:
        owner = create_user(session, username, f"{username}@example.com")
        values = {
            "title": "Admin visible job",
            "audio_file_path": "uploads/admin.wav",
            "selected_stem": "other",
            "user_id": owner.id,
            "is_processed": False,
            "processing_status": "processing",
            "modal_dispatch_status": "dispatched",
            "modal_request_id": "modal-req-123",
            "modal_retry_count": 0,
            "created_at": datetime.now(timezone.utc),
        }
        values.update(overrides)
        transcription = models.Transcription(**values)
        session.add(transcription)
        session.commit()
        return transcription.id
    finally:
        session.close()


def test_admin_jobs_requires_configured_token():
    reset_database()
    original_token = config.settings.ADMIN_API_TOKEN
    config.settings.ADMIN_API_TOKEN = None
    try:
        response = client.get("/api/v1/admin/jobs")
    finally:
        config.settings.ADMIN_API_TOKEN = original_token

    assert response.status_code == 503
    assert response.json()["detail"] == "Admin API is not configured."


def test_admin_jobs_rejects_invalid_token():
    reset_database()
    original_token = config.settings.ADMIN_API_TOKEN
    config.settings.ADMIN_API_TOKEN = "admin-secret"
    try:
        response = client.get(
            "/api/v1/admin/jobs",
            headers={"X-Admin-Token": "wrong"},
        )
    finally:
        config.settings.ADMIN_API_TOKEN = original_token

    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid admin token."


def test_admin_jobs_lists_active_modal_observability_fields():
    reset_database()
    original_token = config.settings.ADMIN_API_TOKEN
    config.settings.ADMIN_API_TOKEN = "admin-secret"
    retry_at = datetime.now(timezone.utc) + timedelta(seconds=60)
    active_id = _create_job(
        "admin-job-owner",
        title="Rate limited stem",
        processing_status="queued",
        modal_dispatch_status="rate_limited",
        modal_request_id="modal-rate-123",
        modal_retry_count=2,
        modal_retry_at=retry_at,
        processing_error="Modal dispatch failed. This job will retry automatically.",
    )
    _create_job(
        "admin-complete-owner",
        title="Completed job",
        processing_status="completed",
        modal_dispatch_status="completed",
        modal_request_id="modal-complete-123",
    )

    try:
        response = client.get(
            "/api/v1/admin/jobs",
            headers={"X-Admin-Token": "admin-secret"},
        )
    finally:
        config.settings.ADMIN_API_TOKEN = original_token

    assert response.status_code == 200
    payload = response.json()
    assert payload["counts"] == {
        "active": 1,
        "queued": 1,
        "processing": 0,
        "rate_limited": 1,
    }
    assert len(payload["jobs"]) == 1
    job = payload["jobs"][0]
    assert job["id"] == active_id
    assert job["title"] == "Rate limited stem"
    assert job["user_email"] == "admin-job-owner@example.com"
    assert job["modal_status_detail"] == "rate_limited_retry"
    assert job["modal_request_id"] == "modal-rate-123"
    assert job["modal_retry_count"] == 2
    assert job["modal_retry_at"] is not None
    assert job["last_error"] == "Modal dispatch failed. This job will retry automatically."
