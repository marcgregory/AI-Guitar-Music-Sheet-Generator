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


def _seed_usage_event(user_id: int, *, created_at: datetime) -> None:
    session = TestingSessionLocal()
    try:
        session.add(
            models.UsageEvent(
                user_id=user_id,
                action_type="admin_usage_test",
                created_at=created_at,
            )
        )
        session.commit()
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


def test_admin_usage_requires_admin_token():
    reset_database()
    original_token = config.settings.ADMIN_API_TOKEN
    config.settings.ADMIN_API_TOKEN = "admin-secret"
    try:
        response = client.get("/api/v1/admin/usage")
    finally:
        config.settings.ADMIN_API_TOKEN = original_token

    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid admin token."


def test_admin_usage_counts_selected_utc_date_and_filters_user():
    reset_database()
    original_token = config.settings.ADMIN_API_TOKEN
    config.settings.ADMIN_API_TOKEN = "admin-secret"
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "usage-date-owner", "usage-date@example.com")
        other = create_user(session, "usage-date-other", "usage-date-other@example.com")
        owner_id = owner.id
        other_id = other.id
    finally:
        session.close()

    _seed_usage_event(
        owner_id,
        created_at=datetime(2026, 5, 27, 8, 30, tzinfo=timezone.utc),
    )
    _seed_usage_event(
        owner_id,
        created_at=datetime(2026, 5, 27, 23, 59, tzinfo=timezone.utc),
    )
    _seed_usage_event(
        owner_id,
        created_at=datetime(2026, 5, 26, 23, 59, tzinfo=timezone.utc),
    )
    _seed_usage_event(
        other_id,
        created_at=datetime(2026, 5, 27, 9, 0, tzinfo=timezone.utc),
    )

    try:
        response = client.get(
            f"/api/v1/admin/usage?user_id={owner_id}&date=2026-05-27",
            headers={"X-Admin-Token": "admin-secret"},
        )
    finally:
        config.settings.ADMIN_API_TOKEN = original_token

    assert response.status_code == 200
    payload = response.json()
    assert payload["date"] == "2026-05-27"
    assert payload["reset_available"] is True
    assert payload["usage"] == [
        {
            "user_id": owner_id,
            "username": "usage-date-owner",
            "usage_count": 2,
            "daily_limit": 5,
            "remaining_quota": 3,
            "active_job_count": 0,
            "reset_available": True,
        }
    ]


def test_admin_usage_default_today_excludes_previous_day_usage():
    reset_database()
    original_token = config.settings.ADMIN_API_TOKEN
    config.settings.ADMIN_API_TOKEN = "admin-secret"
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "usage-today-owner", "usage-today@example.com")
        owner_id = owner.id
    finally:
        session.close()
    now = datetime.now(timezone.utc)
    _seed_usage_event(owner_id, created_at=now)
    _seed_usage_event(owner_id, created_at=now - timedelta(days=1, minutes=5))

    try:
        response = client.get(
            "/api/v1/admin/usage",
            headers={"X-Admin-Token": "admin-secret"},
        )
    finally:
        config.settings.ADMIN_API_TOKEN = original_token

    assert response.status_code == 200
    rows = response.json()["usage"]
    assert len(rows) == 1
    assert rows[0]["username"] == "usage-today-owner"
    assert rows[0]["usage_count"] == 1


def test_admin_usage_active_job_count_and_usage_count_are_independent():
    reset_database()
    original_token = config.settings.ADMIN_API_TOKEN
    config.settings.ADMIN_API_TOKEN = "admin-secret"
    session = TestingSessionLocal()
    try:
        usage_owner = create_user(session, "usage-only-owner", "usage-only@example.com")
        usage_owner_id = usage_owner.id
    finally:
        session.close()
    _seed_usage_event(usage_owner_id, created_at=datetime.now(timezone.utc))
    active_id = _create_job("usage-active-only", processing_status="processing")

    try:
        response = client.get(
            "/api/v1/admin/usage",
            headers={"X-Admin-Token": "admin-secret"},
        )
    finally:
        config.settings.ADMIN_API_TOKEN = original_token

    assert response.status_code == 200
    rows = {row["username"]: row for row in response.json()["usage"]}
    assert rows["usage-only-owner"]["usage_count"] == 1
    assert rows["usage-only-owner"]["active_job_count"] == 0
    assert rows["usage-active-only"]["usage_count"] == 0
    assert rows["usage-active-only"]["active_job_count"] == 1
    assert active_id is not None


def test_admin_usage_reset_blocked_outside_local_without_explicit_enable():
    reset_database()
    original_token = config.settings.ADMIN_API_TOKEN
    original_environment = config.settings.ENVIRONMENT
    original_reset = config.settings.ENABLE_ADMIN_USAGE_RESET
    config.settings.ADMIN_API_TOKEN = "admin-secret"
    config.settings.ENVIRONMENT = "production"
    config.settings.ENABLE_ADMIN_USAGE_RESET = False
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "reset-blocked-owner", "reset-blocked@example.com")
        owner_id = owner.id
    finally:
        session.close()
    _seed_usage_event(owner_id, created_at=datetime.now(timezone.utc))

    try:
        response = client.post(
            "/api/v1/admin/usage/reset",
            headers={"X-Admin-Token": "admin-secret"},
            json={"user_id": owner_id},
        )
    finally:
        config.settings.ADMIN_API_TOKEN = original_token
        config.settings.ENVIRONMENT = original_environment
        config.settings.ENABLE_ADMIN_USAGE_RESET = original_reset

    assert response.status_code == 403
    session = TestingSessionLocal()
    try:
        assert session.query(models.UsageEvent).count() == 1
    finally:
        session.close()


def test_admin_usage_reset_deletes_today_usage_only_and_leaves_jobs():
    reset_database()
    original_token = config.settings.ADMIN_API_TOKEN
    original_environment = config.settings.ENVIRONMENT
    config.settings.ADMIN_API_TOKEN = "admin-secret"
    config.settings.ENVIRONMENT = "development"
    active_id = _create_job("reset-owner", processing_status="processing")
    session = TestingSessionLocal()
    try:
        owner = session.query(models.User).filter(models.User.username == "reset-owner").one()
        owner_id = owner.id
    finally:
        session.close()
    now = datetime.now(timezone.utc)
    _seed_usage_event(owner_id, created_at=now)
    _seed_usage_event(owner_id, created_at=now - timedelta(days=1, minutes=5))

    try:
        response = client.post(
            "/api/v1/admin/usage/reset",
            headers={"X-Admin-Token": "admin-secret"},
            json={"user_id": owner_id},
        )
    finally:
        config.settings.ADMIN_API_TOKEN = original_token
        config.settings.ENVIRONMENT = original_environment

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["deleted_count"] == 1
    assert payload["usage"] == {
        "user_id": owner_id,
        "username": "reset-owner",
        "usage_count": 0,
        "daily_limit": 5,
        "remaining_quota": 5,
        "active_job_count": 1,
        "reset_available": True,
    }
    session = TestingSessionLocal()
    try:
        remaining_events = session.query(models.UsageEvent).all()
        job = session.query(models.Transcription).filter(models.Transcription.id == active_id).one()
        assert len(remaining_events) == 1
        assert job.processing_status == "processing"
        assert job.is_deleted is False
    finally:
        session.close()


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


def test_admin_job_history_lists_recent_terminal_modal_jobs():
    reset_database()
    original_token = config.settings.ADMIN_API_TOKEN
    config.settings.ADMIN_API_TOKEN = "admin-secret"
    started_at = datetime.now(timezone.utc) - timedelta(minutes=4)
    finished_at = started_at + timedelta(seconds=145)
    failed_id = _create_job(
        "admin-history-owner",
        title="Failed Modal job",
        processing_status="failed",
        modal_dispatch_status="failed",
        modal_request_id="modal-failed-123",
        modal_retry_count=3,
        modal_dispatched_at=started_at,
        updated_at=finished_at,
        processing_error="Worker processing failed.",
    )
    completed_id = _create_job(
        "admin-history-complete",
        title="Completed Modal job",
        processing_status="completed",
        modal_dispatch_status="completed",
        modal_request_id="modal-completed-123",
        modal_dispatched_at=started_at,
        updated_at=finished_at + timedelta(seconds=5),
    )
    _create_job(
        "admin-history-active",
        title="Still running",
        processing_status="processing",
        modal_dispatch_status="dispatched",
        modal_request_id="modal-active-123",
    )

    try:
        response = client.get(
            "/api/v1/admin/jobs/history",
            headers={"X-Admin-Token": "admin-secret"},
        )
    finally:
        config.settings.ADMIN_API_TOKEN = original_token

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    ids = [job["id"] for job in payload["jobs"]]
    assert ids == [completed_id, failed_id]
    failed_job = next(job for job in payload["jobs"] if job["id"] == failed_id)
    assert failed_job["modal_request_id"] == "modal-failed-123"
    assert failed_job["duration_seconds"] == 145
    assert failed_job["processing_status"] == "failed"
    assert failed_job["modal_retry_count"] == 3
    assert failed_job["last_error"] == "Worker processing failed."


def test_admin_job_history_filters_by_processing_status():
    reset_database()
    original_token = config.settings.ADMIN_API_TOKEN
    config.settings.ADMIN_API_TOKEN = "admin-secret"
    now = datetime.now(timezone.utc)
    failed_id = _create_job(
        "admin-history-filter-failed",
        title="Failed history job",
        processing_status="failed",
        modal_dispatch_status="failed",
        modal_request_id="modal-filter-failed",
        updated_at=now,
    )
    _create_job(
        "admin-history-filter-complete",
        title="Completed history job",
        processing_status="completed",
        modal_dispatch_status="completed",
        modal_request_id="modal-filter-completed",
        updated_at=now + timedelta(seconds=1),
    )
    _create_job(
        "admin-history-filter-warning",
        title="Warning history job",
        processing_status="completed_with_warning",
        modal_dispatch_status="completed",
        modal_request_id="modal-filter-warning",
        updated_at=now + timedelta(seconds=2),
    )

    try:
        response = client.get(
            "/api/v1/admin/jobs/history?status=failed",
            headers={"X-Admin-Token": "admin-secret"},
        )
    finally:
        config.settings.ADMIN_API_TOKEN = original_token

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["jobs"][0]["id"] == failed_id
    assert payload["jobs"][0]["processing_status"] == "failed"


def test_admin_job_history_limit_still_limits_results():
    reset_database()
    original_token = config.settings.ADMIN_API_TOKEN
    config.settings.ADMIN_API_TOKEN = "admin-secret"
    now = datetime.now(timezone.utc)
    newest_id = _create_job(
        "admin-history-limit-newest",
        title="Newest history job",
        processing_status="completed",
        modal_dispatch_status="completed",
        modal_request_id="modal-limit-newest",
        updated_at=now + timedelta(seconds=2),
    )
    _create_job(
        "admin-history-limit-middle",
        title="Middle history job",
        processing_status="completed",
        modal_dispatch_status="completed",
        modal_request_id="modal-limit-middle",
        updated_at=now + timedelta(seconds=1),
    )
    _create_job(
        "admin-history-limit-oldest",
        title="Oldest history job",
        processing_status="completed",
        modal_dispatch_status="completed",
        modal_request_id="modal-limit-oldest",
        updated_at=now,
    )

    try:
        response = client.get(
            "/api/v1/admin/jobs/history?limit=1",
            headers={"X-Admin-Token": "admin-secret"},
        )
    finally:
        config.settings.ADMIN_API_TOKEN = original_token

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert [job["id"] for job in payload["jobs"]] == [newest_id]


def test_admin_job_history_rejects_invalid_status_filter():
    reset_database()
    original_token = config.settings.ADMIN_API_TOKEN
    config.settings.ADMIN_API_TOKEN = "admin-secret"
    try:
        response = client.get(
            "/api/v1/admin/jobs/history?status=processing",
            headers={"X-Admin-Token": "admin-secret"},
        )
    finally:
        config.settings.ADMIN_API_TOKEN = original_token

    assert response.status_code == 422
