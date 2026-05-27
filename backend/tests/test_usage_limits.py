import hashlib
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app import models
from app.core import config
from test_audio_list_endpoint import (
    TestingSessionLocal,
    auth_headers,
    client,
    create_user,
    reset_database,
    sample_notes_json,
    sample_tab_json,
)


ACTIVE_JOB_LIMIT_DETAIL = (
    "You already have a transcription job in progress. Please wait for it to finish before starting another."
)
DAILY_JOB_LIMIT_DETAIL = "Daily processing limit reached. Please try again tomorrow."


def _use_modal_mode():
    config.settings.AUDIO_PROCESSING_MODE = "modal"
    config.settings.PROCESSING_MODE = "modal"
    config.settings.MODAL_TRIGGER_URL = "https://modal.test/trigger"


def _upload_sample(username: str, contents: bytes = b"RIFF usage sample"):
    with tempfile.TemporaryDirectory() as tmp_dir, patch(
        "app.api.v1.endpoints.audio._upload_original_audio",
        return_value={"secure_url": "https://example.com/original.wav", "public_id": "orig123"},
    ), patch(
        "app.api.v1.endpoints.audio._trigger_modal_worker",
    ), patch(
        "app.api.v1.endpoints.audio.UPLOAD_DIR",
        Path(tmp_dir),
    ):
        return client.post(
            "/api/v1/audio/upload",
            headers=auth_headers(username),
            data={"selected_stem": "other"},
            files={"file": ("sample.wav", contents, "audio/wav")},
        )


def _usage_count(username: str) -> int:
    session = TestingSessionLocal()
    try:
        user = session.query(models.User).filter(models.User.username == username).one()
        return session.query(models.UsageEvent).filter(
            models.UsageEvent.user_id == user.id
        ).count()
    finally:
        session.close()


def _seed_daily_usage(username: str, count: int = 5, *, previous_day: bool = False):
    session = TestingSessionLocal()
    try:
        user = session.query(models.User).filter(models.User.username == username).one()
        created_at = datetime.now(timezone.utc)
        if previous_day:
            created_at = created_at - timedelta(days=1, minutes=5)
        for index in range(count):
            session.add(models.UsageEvent(
                user_id=user.id,
                action_type=f"seed_{index}",
                created_at=created_at,
            ))
        session.commit()
    finally:
        session.close()


def _create_transcription(
    username: str,
    *,
    selected_stem: str = "other",
    processing_status: str = "completed",
    is_processed: bool = True,
    separated_audio_url: str | None = "https://cdn.example.com/stem.wav",
    can_play_stem: bool = True,
):
    session = TestingSessionLocal()
    try:
        user = session.query(models.User).filter(models.User.username == username).one()
        transcription = models.Transcription(
            title=f"{selected_stem} usage song",
            audio_file_path=f"uploads/{selected_stem}.wav",
            selected_stem=selected_stem,
            separated_audio_url=separated_audio_url,
            user_id=user.id,
            is_processed=is_processed,
            processing_status=processing_status,
            can_play_stem=can_play_stem,
            can_generate_score=selected_stem in {"other", "bass"},
            notes_data=sample_notes_json(),
            tablature_data=sample_tab_json("bass" if selected_stem == "bass" else "guitar"),
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)
        return transcription.id
    finally:
        session.close()


def _create_track(transcription_id: int, *, instrument_type: str = "guitar"):
    session = TestingSessionLocal()
    try:
        track = models.InstrumentTrack(
            transcription_id=transcription_id,
            instrument_type=instrument_type,
            display_name=instrument_type.title(),
            stem_audio_path="uploads/stems/existing.wav",
            notes_json=sample_notes_json(),
            tab_json=sample_tab_json("bass" if instrument_type == "bass" else "guitar"),
            processing_status="completed",
        )
        session.add(track)
        session.commit()
        session.refresh(track)
        return track.id
    finally:
        session.close()


def test_upload_accepts_first_job_and_records_usage_event():
    reset_database()
    _use_modal_mode()
    session = TestingSessionLocal()
    try:
        create_user(session, "usage-upload-owner", "usage-upload@example.com")
    finally:
        session.close()

    response = _upload_sample("usage-upload-owner")

    assert response.status_code == 200
    assert _usage_count("usage-upload-owner") == 1
    session = TestingSessionLocal()
    try:
        event = session.query(models.UsageEvent).one()
        assert event.action_type == "upload"
        assert event.transcription_id == response.json()["id"]
    finally:
        session.close()


@pytest.mark.parametrize("active_status", ["pending", "queued", "processing"])
def test_upload_rejected_when_same_user_has_active_usage_job(active_status):
    reset_database()
    _use_modal_mode()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "usage-active-owner", "usage-active@example.com")
        session.add(models.Transcription(
            title="Active usage job",
            audio_file_path="uploads/active.wav",
            selected_stem="other",
            user_id=owner.id,
            is_processed=active_status == "stem_ready",
            processing_status=active_status,
            is_deleted=False,
        ))
        session.commit()
    finally:
        session.close()

    response = _upload_sample("usage-active-owner")

    assert response.status_code == 429
    assert response.json()["detail"] == ACTIVE_JOB_LIMIT_DETAIL
    assert _usage_count("usage-active-owner") == 0


def test_upload_allowed_when_only_another_user_has_active_modal_job():
    reset_database()
    _use_modal_mode()
    session = TestingSessionLocal()
    try:
        active_owner = create_user(session, "usage-other-active", "usage-other-active@example.com")
        create_user(session, "usage-other-uploader", "usage-other-uploader@example.com")
        session.add(models.Transcription(
            title="Other user's active job",
            audio_file_path="uploads/other-active.wav",
            user_id=active_owner.id,
            is_processed=False,
            processing_status="processing",
            is_deleted=False,
        ))
        session.commit()
    finally:
        session.close()

    response = _upload_sample("usage-other-uploader")

    assert response.status_code == 200
    assert _usage_count("usage-other-uploader") == 1


@pytest.mark.parametrize(
    ("processing_status", "is_processed", "is_deleted"),
    [
        ("failed", False, False),
        ("stem_ready", True, False),
        ("completed", True, False),
        ("completed_with_warning", True, False),
        ("cancelled", False, False),
        ("deleted", True, True),
    ],
)
def test_terminal_jobs_do_not_block_upload(processing_status, is_processed, is_deleted):
    reset_database()
    _use_modal_mode()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "usage-terminal-owner", "usage-terminal@example.com")
        session.add(models.Transcription(
            title=f"{processing_status} job",
            audio_file_path=f"uploads/{processing_status}.wav",
            user_id=owner.id,
            is_processed=is_processed,
            processing_status=processing_status,
            is_deleted=is_deleted,
        ))
        session.commit()
    finally:
        session.close()

    response = _upload_sample("usage-terminal-owner")

    assert response.status_code == 200
    assert _usage_count("usage-terminal-owner") == 1


def test_previous_day_usage_events_do_not_count_toward_daily_limit():
    reset_database()
    _use_modal_mode()
    session = TestingSessionLocal()
    try:
        create_user(session, "usage-yesterday-owner", "usage-yesterday@example.com")
    finally:
        session.close()
    _seed_daily_usage("usage-yesterday-owner", previous_day=True)

    response = _upload_sample("usage-yesterday-owner")

    assert response.status_code == 200
    assert _usage_count("usage-yesterday-owner") == 6


def test_current_user_usage_requires_auth():
    reset_database()

    response = client.get("/api/v1/usage/me")

    assert response.status_code == 401


def test_current_user_usage_counts_today_only_and_returns_reset():
    reset_database()
    now = datetime.now(timezone.utc)
    with TestingSessionLocal() as session:
        owner = create_user(session, "usage-me-owner", "usage-me@example.com")
        other = create_user(session, "usage-me-other", "usage-me-other@example.com")
        session.add_all(
            [
                models.UsageEvent(
                    user_id=owner.id,
                    action_type="today_one",
                    created_at=now,
                ),
                models.UsageEvent(
                    user_id=owner.id,
                    action_type="today_two",
                    created_at=now,
                ),
                models.UsageEvent(
                    user_id=owner.id,
                    action_type="yesterday",
                    created_at=now - timedelta(days=1, minutes=5),
                ),
                models.UsageEvent(
                    user_id=other.id,
                    action_type="other_user",
                    created_at=now,
                ),
            ]
        )
        session.commit()

    response = client.get("/api/v1/usage/me", headers=auth_headers("usage-me-owner"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["usage_count"] == 2
    assert payload["daily_limit"] == 5
    assert payload["remaining_quota"] == 3
    assert payload["is_unlimited"] is False
    resets_at = datetime.fromisoformat(payload["resets_at"].replace("Z", "+00:00"))
    assert resets_at.tzinfo is not None
    assert resets_at.hour == 0
    assert resets_at.minute == 0
    assert resets_at > now


def test_current_user_usage_clamps_remaining_quota_at_zero():
    reset_database()
    with TestingSessionLocal() as session:
        create_user(session, "usage-me-exhausted", "usage-me-exhausted@example.com")

    _seed_daily_usage("usage-me-exhausted", count=7)

    response = client.get(
        "/api/v1/usage/me",
        headers=auth_headers("usage-me-exhausted"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["usage_count"] == 7
    assert payload["daily_limit"] == 5
    assert payload["remaining_quota"] == 0
    assert payload["is_unlimited"] is False


def test_current_user_usage_reports_unlimited_daily_limit():
    reset_database()
    config.settings.DAILY_PROCESSING_JOB_LIMIT = 0
    with TestingSessionLocal() as session:
        create_user(session, "usage-me-unlimited", "usage-me-unlimited@example.com")

    _seed_daily_usage("usage-me-unlimited", count=3)

    response = client.get(
        "/api/v1/usage/me",
        headers=auth_headers("usage-me-unlimited"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "usage_count": 3,
        "daily_limit": 0,
        "remaining_quota": None,
        "resets_at": None,
        "is_unlimited": True,
    }


@pytest.mark.parametrize(
    "endpoint_kind",
    ["upload", "youtube", "retry", "generate_tabs", "generate_lyrics", "track_reprocess"],
)
def test_costly_actions_rejected_after_daily_limit(endpoint_kind):
    reset_database()
    _use_modal_mode()
    username = f"daily-limit-{endpoint_kind}"
    session = TestingSessionLocal()
    try:
        create_user(session, username, f"{username}@example.com")
    finally:
        session.close()
    _seed_daily_usage(username)

    if endpoint_kind == "upload":
        response = _upload_sample(username)
    elif endpoint_kind == "youtube":
        response = client.post(
            "/api/v1/audio/youtube",
            headers=auth_headers(username),
            json={
                "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "selected_stem": "other",
            },
        )
    elif endpoint_kind == "retry":
        transcription_id = _create_transcription(username)
        response = client.post(
            f"/api/v1/audio/{transcription_id}/retry",
            headers=auth_headers(username),
            json={"lower_threshold": True},
        )
    elif endpoint_kind == "generate_tabs":
        transcription_id = _create_transcription(
            username,
            processing_status="stem_ready",
            is_processed=True,
        )
        response = client.post(
            f"/api/v1/audio/{transcription_id}/generate-tabs",
            headers=auth_headers(username),
            json={"sensitivity": "normal"},
        )
    elif endpoint_kind == "generate_lyrics":
        transcription_id = _create_transcription(
            username,
            selected_stem="vocals",
            processing_status="stem_ready",
            is_processed=True,
            can_play_stem=True,
        )
        response = client.post(
            f"/api/v1/audio/{transcription_id}/generate-lyrics",
            headers=auth_headers(username),
            json={"language": "auto"},
        )
    else:
        transcription_id = _create_transcription(username)
        track_id = _create_track(transcription_id)
        response = client.post(
            f"/api/v1/audio/{transcription_id}/tracks/{track_id}/reprocess",
            headers=auth_headers(username),
        )

    assert response.status_code == 429
    assert response.json()["detail"] == DAILY_JOB_LIMIT_DETAIL
    assert _usage_count(username) == 5


def test_usage_event_not_recorded_for_validation_failure_or_duplicate_reuse():
    reset_database()
    _use_modal_mode()
    duplicate_contents = b"RIFF duplicate quota"
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "usage-no-record-owner", "usage-no-record@example.com")
        session.add(models.Transcription(
            title="Existing duplicate",
            audio_file_path="uploads/existing.wav",
            selected_stem="other",
            audio_hash=hashlib.sha256(duplicate_contents).hexdigest(),
            user_id=owner.id,
            is_processed=True,
            processing_status="completed",
        ))
        session.commit()
    finally:
        session.close()

    invalid_response = client.post(
        "/api/v1/audio/upload",
        headers=auth_headers("usage-no-record-owner"),
        files={"file": ("sample.wav", b"RIFF invalid", "audio/wav")},
    )
    duplicate_response = _upload_sample(
        "usage-no-record-owner",
        contents=duplicate_contents,
    )

    assert invalid_response.status_code == 422
    assert duplicate_response.status_code == 200
    assert duplicate_response.json()["duplicate_reused"] is True
    assert _usage_count("usage-no-record-owner") == 0


def test_delete_clears_active_usage_blocking():
    reset_database()
    _use_modal_mode()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "usage-delete-owner", "usage-delete@example.com")
        active = models.Transcription(
            title="Active before delete",
            audio_file_path="uploads/active-before-delete.wav",
            selected_stem="other",
            user_id=owner.id,
            is_processed=False,
            processing_status="processing",
        )
        session.add(active)
        session.commit()
        session.refresh(active)
        transcription_id = active.id
    finally:
        session.close()

    delete_response = client.delete(
        f"/api/v1/audio/{transcription_id}",
        headers=auth_headers("usage-delete-owner"),
    )
    upload_response = _upload_sample("usage-delete-owner")

    assert delete_response.status_code == 200
    assert delete_response.json()["processing_status"] == "cancelled"
    assert upload_response.status_code == 200
    assert _usage_count("usage-delete-owner") == 1
