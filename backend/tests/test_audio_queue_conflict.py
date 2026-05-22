import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app import models
from test_audio_list_endpoint import (
    TestingSessionLocal,
    auth_headers,
    client,
    create_user,
    reset_database,
)


def upload_sample(username: str):
    with tempfile.TemporaryDirectory() as tmp_dir, patch(
        "app.api.v1.endpoints.audio._upload_original_audio",
        return_value={"secure_url": "https://example.com/original.wav", "public_id": "orig123"},
    ), patch(
        "app.api.v1.endpoints.audio._trigger_next_queued_transcription",
    ), patch(
        "app.api.v1.endpoints.audio.UPLOAD_DIR",
        Path(tmp_dir),
    ):
        return client.post(
            "/api/v1/audio/upload",
            headers=auth_headers(username),
            data={"selected_stem": "other"},
            files={"file": ("sample.wav", b"RIFF....", "audio/wav")},
        )


def test_upload_rejected_when_active_transcription_exists():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "active-owner", "active@example.com")
        # create an active processing transcription globaly
        t = models.Transcription(
            title="Active processing",
            audio_file_path="uploads/active.wav",
            user_id=owner.id,
            is_processed=False,
            processing_status="processing",
        )
        session.add(t)
        session.commit()
    finally:
        session.close()

    with patch("app.api.v1.endpoints.audio.storage.safe_upload_file") as mock_upload:
        response = client.post(
            "/api/v1/audio/upload",
            headers=auth_headers("active-owner"),
            data={"selected_stem": "other"},
            files={"file": ("sample.wav", b"RIFF....", "audio/wav")},
        )

    assert response.status_code == 409
    assert response.json().get("detail") == (
        "Another transcription is currently processing. Please wait until it finishes before starting a new one."
    )
    mock_upload.assert_not_called()


def test_only_non_deleted_active_statuses_block_uploads():
    non_blocking_statuses = [
        ("completed", True, False),
        ("completed_with_warning", True, False),
        ("failed", False, False),
        ("cancelled", False, False),
        ("deleted", False, True),
        ("processing", False, True),
    ]

    for index, (processing_status, is_processed, is_deleted) in enumerate(non_blocking_statuses):
        reset_database()
        session = TestingSessionLocal()
        username = f"status-owner-{index}"
        try:
            owner = create_user(session, username, f"{username}@example.com")
            transcription = models.Transcription(
                title=f"{processing_status} song",
                audio_file_path=f"uploads/{processing_status}.wav",
                user_id=owner.id,
                is_processed=is_processed,
                is_deleted=is_deleted,
                processing_status=processing_status,
            )
            session.add(transcription)
            session.commit()
        finally:
            session.close()

        response = upload_sample(username)
        assert response.status_code == 200, processing_status
        assert response.json().get("title") == "sample.wav"


def test_pending_queued_and_processing_block_uploads():
    for processing_status in ["pending", "queued", "processing"]:
        reset_database()
        session = TestingSessionLocal()
        username = f"active-{processing_status}-owner"
        try:
            owner = create_user(session, username, f"{username}@example.com")
            transcription = models.Transcription(
                title=f"{processing_status} song",
                audio_file_path=f"uploads/{processing_status}.wav",
                user_id=owner.id,
                is_processed=False,
                is_deleted=False,
                processing_status=processing_status,
            )
            session.add(transcription)
            session.commit()
        finally:
            session.close()

        response = upload_sample(username)
        assert response.status_code == 409, processing_status


def test_stale_active_job_is_failed_before_upload_conflict_check():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "stale-owner", "stale-owner@example.com")
        stale = models.Transcription(
            title="Stale processing",
            audio_file_path="uploads/stale.wav",
            user_id=owner.id,
            is_processed=False,
            processing_status="processing",
            queue_position=0,
            estimated_wait_time=0,
            celery_task_id="stale-task",
            created_at=datetime.utcnow() - timedelta(seconds=8000),
        )
        session.add(stale)
        session.commit()
        stale_id = stale.id
    finally:
        session.close()

    response = upload_sample("stale-owner")
    assert response.status_code == 200

    session = TestingSessionLocal()
    try:
        refreshed = session.query(models.Transcription).filter(models.Transcription.id == stale_id).one()
        assert refreshed.processing_status == "failed"
        assert refreshed.queue_position is None
        assert refreshed.estimated_wait_time is None
        assert refreshed.celery_task_id is None
        assert "timed out" in refreshed.processing_error
    finally:
        session.close()


def test_upload_allowed_after_deleting_active_transcription():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "active-owner", "active-owner@example.com")
        transcription = models.Transcription(
            title="Active processing",
            audio_file_path="uploads/active.wav",
            user_id=owner.id,
            is_processed=False,
            processing_status="processing",
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)
    finally:
        session.close()

    delete_response = client.delete(
        f"/api/v1/audio/{transcription.id}",
        headers=auth_headers("active-owner"),
    )
    assert delete_response.status_code == 200
    delete_payload = delete_response.json()
    assert delete_payload.get("is_deleted") is True
    assert delete_payload.get("processing_status") == "cancelled"
    assert delete_payload.get("queue_position") is None
    assert delete_payload.get("estimated_wait_time") is None

    response = upload_sample("active-owner")

    assert response.status_code == 200
    assert response.json().get("title") == "sample.wav"
    assert response.json().get("is_deleted") is False
