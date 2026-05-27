import hashlib
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import database_init, db, models, tasks
from app.api.v1.endpoints import audio as audio_endpoint
from app.core import config
from app.core.security import create_access_token, get_password_hash
from app.services import lyrics, storage
from main import app


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


app.dependency_overrides[db.get_db] = override_get_db
client = TestClient(app)


def reset_database():
    models.Base.metadata.drop_all(bind=engine)
    models.Base.metadata.create_all(bind=engine)
    config.settings.CLOUDINARY_URL = None
    config.settings.CLOUDINARY_CLOUD_NAME = None
    config.settings.CLOUDINARY_API_KEY = None
    config.settings.CLOUDINARY_API_SECRET = None
    config.settings.AUDIO_PROCESSING_MODE = None
    config.settings.PROCESSING_MODE = None
    config.settings.MODAL_TRIGGER_URL = None
    config.settings.YOUTUBE_COOKIES_FILE = None
    config.settings.YOUTUBE_COOKIES = None
    config.settings.YOUTUBE_COOKIES_B64 = None
    config.settings.YOUTUBE_PO_TOKEN = None
    config.settings.YOUTUBE_VISITOR_DATA = None
    config.settings.YOUTUBE_PLAYER_CLIENT = None
    config.settings.YOUTUBE_PLAYER_CLIENTS = None
    config.settings.ENABLE_USAGE_LIMITS = True
    config.settings.MAX_ACTIVE_JOBS_PER_USER = 1
    config.settings.DAILY_PROCESSING_JOB_LIMIT = 5
    config.settings.ENABLE_ADMIN_USAGE_RESET = False
    config.settings.ENVIRONMENT = "development"


def create_user(session, username: str, email: str):
    user = models.User(
        username=username,
        email=email,
        hashed_password=get_password_hash("password123"),
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def auth_headers(username: str):
    token = create_access_token(data={"sub": username})
    return {"Authorization": f"Bearer {token}"}


def sample_notes_json():
    return (
        '{"notes": ['
        '{"onset": 0.0, "offset": 0.5, "pitch": 43, "velocity": 84, "confidence": 0.91}'
        ']}'
    )


def sample_tab_json(instrument: str = "guitar"):
    if instrument == "bass":
        return (
            '{"instrument": "bass", "tuning": [28, 33, 38, 43], '
            '"tablature": [{"string": 1, "fret": 0, "onset": 0.0, "offset": 0.5}]}'
        )
    return (
        '{"instrument": "guitar", "tuning": [40, 45, 50, 55, 59, 64], '
        '"tablature": [{"string": 1, "fret": 3, "onset": 0.0, "offset": 0.5}]}'
    )


def test_list_transcriptions_requires_authentication():
    reset_database()

    response = client.get("/api/v1/audio/")

    assert response.status_code == 401
    assert response.json()["detail"] == {
        "status": "unauthorized",
        "error": "Missing Authorization header",
        "requires_login": True,
    }


def test_list_transcriptions_rejects_missing_bearer_prefix():
    reset_database()

    response = client.get(
        "/api/v1/audio/",
        headers={"Authorization": "Token not-a-bearer-token"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "Missing Bearer token prefix"


def test_list_transcriptions_rejects_malformed_token():
    reset_database()

    response = client.get(
        "/api/v1/audio/",
        headers={"Authorization": "Bearer undefined"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["status"] == "unauthorized"
    assert response.json()["detail"]["error"] == "Access token is malformed or invalid"
    assert response.json()["detail"]["requires_login"] is True


def test_list_transcriptions_rejects_expired_token():
    reset_database()
    session = TestingSessionLocal()
    try:
        create_user(session, "expired-owner", "expired-owner@example.com")
    finally:
        session.close()
    token = create_access_token(
        data={"sub": "expired-owner"},
        expires_delta=timedelta(seconds=-1),
    )

    response = client.get(
        "/api/v1/audio/",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "Access token expired"


def test_list_transcriptions_accepts_valid_token_after_invalid_token_cycle():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "cycle-owner", "cycle-owner@example.com")
        session.add(models.Transcription(
            title="Recovered session song",
            audio_file_path="uploads/recovered.wav",
            user_id=owner.id,
            is_processed=True,
            created_at=datetime.utcnow(),
        ))
        session.commit()
    finally:
        session.close()

    stale_response = client.get(
        "/api/v1/audio/",
        headers={"Authorization": "Bearer undefined"},
    )
    valid_response = client.get(
        "/api/v1/audio/",
        headers=auth_headers("cycle-owner"),
    )

    assert stale_response.status_code == 401
    assert valid_response.status_code == 200
    assert valid_response.json()[0]["title"] == "Recovered session song"


def test_get_transcription_source_audio_normalizes_windows_style_uploaded_path(tmp_path):
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "winpath-user", "winpath@example.com")
        local_audio = tmp_path / "uploaded.wav"
        local_audio.write_bytes(b"wave data")
        windows_path = str(local_audio).replace("/", "\\")

        transcription = models.Transcription(
            title="Windows path upload",
            audio_file_path=windows_path,
            user_id=owner.id,
            is_processed=True,
            created_at=datetime.utcnow(),
            duration=10,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)
    finally:
        session.close()

    response = client.get(
        f"/api/v1/audio/{transcription.id}/source",
        headers=auth_headers("winpath-user"),
    )

    assert response.status_code == 200
    assert response.content == b"wave data"
    assert response.headers["content-type"].startswith("audio/wav")


def test_windows_app_uploads_path_normalizes_to_local_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(storage.os, "name", "nt")
    monkeypatch.setattr(storage, "_windows_local_upload_dir", lambda: tmp_path / "uploads")

    normalized_path = storage.normalize_local_path("/app/uploads/youtube-download.wav")

    assert Path(normalized_path) == (tmp_path / "uploads" / "youtube-download.wav").resolve()
    assert str(normalized_path).endswith(str(Path("uploads") / "youtube-download.wav"))


def test_demo_static_audio_route_serves_public_wav_without_cors_error():
    response = client.get(
        "/demo/example-guitar-riff.wav",
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.status_code == 200
    assert response.content
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_demo_transcription_response_uses_public_audio_url_for_playback_fields():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "demo-owner", "demo-owner@example.com")
        local_path = "/app/app/static/demo_guitar_riff.wav"
        demo = models.Transcription(
            title="Example guitar riff",
            audio_file_path=local_path,
            separated_audio_file_path=local_path,
            original_audio_url="/demo/example-guitar-riff.wav",
            separated_audio_url="/demo/example-guitar-riff.wav",
            source_url="/demo/example-guitar-riff.wav",
            normalized_source_id="demo:example-guitar-riff",
            source_type="demo",
            user_id=owner.id,
            is_demo=True,
            is_processed=True,
            processing_status="completed",
            can_play_stem=True,
        )
        session.add(demo)
        session.commit()
        session.refresh(demo)
        session.add(models.InstrumentTrack(
            transcription_id=demo.id,
            instrument_type="guitar",
            display_name="Demo guitar stem",
            stem_audio_path=local_path,
            processing_status="completed",
        ))
        session.commit()
        demo_id = demo.id
    finally:
        session.close()

    demo_response = client.get(
        "/api/v1/audio/demo",
        headers=auth_headers("demo-owner"),
    )
    tracks_response = client.get(
        f"/api/v1/audio/{demo_id}/tracks",
        headers=auth_headers("demo-owner"),
    )

    assert demo_response.status_code == 200
    demo_payload = demo_response.json()
    assert demo_payload["audio_file_path"] == "/demo/example-guitar-riff.wav"
    assert demo_payload["separated_audio_file_path"] == "/demo/example-guitar-riff.wav"
    assert "/app/app/static" not in json.dumps(demo_payload)

    assert tracks_response.status_code == 200
    tracks_payload = tracks_response.json()
    assert tracks_payload[0]["stem_audio_path"] == "/demo/example-guitar-riff.wav"
    assert "/app/app/static" not in json.dumps(tracks_payload)


def test_demo_seed_repairs_stale_processing_status(monkeypatch):
    reset_database()
    monkeypatch.setattr(database_init, "SessionLocal", TestingSessionLocal)
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "demo-system", "demo-system@example.local")
        stale_demo = models.Transcription(
            title="Example guitar riff",
            audio_file_path="stale.wav",
            separated_audio_file_path="stale.wav",
            source_type="demo",
            source_url="/demo/example-guitar-riff.wav",
            normalized_source_id="demo:example-guitar-riff",
            user_id=owner.id,
            is_demo=True,
            is_processed=True,
            processing_status="processing",
            queue_position=1,
            estimated_wait_time=300,
            celery_task_id="stale-task",
            modal_dispatch_status="dispatched",
            modal_job_type="process",
            modal_request_id="stale-request",
            modal_retry_count=2,
        )
        session.add(stale_demo)
        session.commit()
    finally:
        session.close()

    database_init._seed_demo_transcription()

    session = TestingSessionLocal()
    try:
        demo = (
            session.query(models.Transcription)
            .filter(models.Transcription.normalized_source_id == "demo:example-guitar-riff")
            .one()
        )

        assert demo.processing_status == "completed"
        assert demo.is_processed is True
        assert demo.queue_position == 0
        assert demo.estimated_wait_time == 0
        assert demo.celery_task_id is None
        assert demo.modal_dispatch_status is None
        assert demo.modal_job_type is None
        assert demo.modal_request_id is None
        assert demo.modal_retry_count == 0
        assert demo.processing_error is None
        assert demo.warning_message is None
    finally:
        session.close()


def test_list_transcriptions_returns_only_current_users_items_newest_first():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "owner", "owner@example.com")
        other_user = create_user(session, "other", "other@example.com")
        base_time = datetime(2026, 5, 14, 12, 0, 0)

        older = models.Transcription(
            title="Older song",
            audio_file_path="uploads/older.wav",
            user_id=owner.id,
            is_processed=True,
            created_at=base_time,
            duration=60,
        )
        newer = models.Transcription(
            title="Newer song",
            audio_file_path="uploads/newer.wav",
            user_id=owner.id,
            is_processed=False,
            created_at=base_time + timedelta(minutes=5),
            duration=90,
        )
        same_time_later = models.Transcription(
            title="Same time later id",
            audio_file_path="uploads/same-time.wav",
            user_id=owner.id,
            is_processed=False,
            created_at=base_time + timedelta(minutes=5),
            duration=95,
        )
        other = models.Transcription(
            title="Other user song",
            audio_file_path="uploads/other.wav",
            user_id=other_user.id,
            is_processed=True,
            created_at=base_time + timedelta(minutes=10),
            duration=120,
        )
        session.add_all([older, newer, same_time_later, other])
        session.commit()
        other_user_id = other_user.id
    finally:
        session.close()

    response = client.get("/api/v1/audio/", headers=auth_headers("owner"))

    assert response.status_code == 200
    payload = response.json()
    assert [item["title"] for item in payload] == [
        "Same time later id",
        "Newer song",
        "Older song",
    ]
    assert all(item["user_id"] != other_user_id for item in payload)


def test_status_returns_processing_for_unfinished_warning_only_job():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "warning-owner", "warning-owner@example.com")
        transcription = models.Transcription(
            title="Warning stuck song",
            audio_file_path="uploads/warning-stuck.wav",
            user_id=owner.id,
            is_processed=False,
            processing_error=(
                "Source separation unavailable; processed the full mix instead. "
                "Details: worker stopped before finishing"
            ),
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
    finally:
        session.close()

    response = client.get(
        f"/api/v1/audio/{transcription_id}/status",
        headers=auth_headers("warning-owner"),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert response.json().get("error") is None


def test_generate_tabs_local_background_keeps_stem_ready_status(tmp_path):
    reset_database()
    session = TestingSessionLocal()
    original_audio_mode = config.settings.AUDIO_PROCESSING_MODE
    try:
        config.settings.AUDIO_PROCESSING_MODE = "local"
        owner = create_user(session, "tab-owner", "tab-owner@example.com")
        stem_path = tmp_path / "other.wav"
        stem_path.write_bytes(b"other")
        transcription = models.Transcription(
            title="Stem ready song",
            separated_audio_file_path=str(stem_path),
            selected_stem="other",
            user_id=owner.id,
            is_processed=True,
            processing_status="stem_ready",
            tab_generation_status="idle",
            can_play_stem=True,
            can_generate_score=False,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)
        transcription_id = transcription.id
    finally:
        session.close()

    try:
        with patch("app.api.v1.endpoints.audio._celery_has_available_worker", return_value=False):
            with patch("app.api.v1.endpoints.audio._run_tab_generation_locally") as local_run_mock:
                response = client.post(
                    f"/api/v1/audio/{transcription_id}/generate-tabs",
                    headers=auth_headers("tab-owner"),
                    json={"sensitivity": "normal"},
                )
    finally:
        config.settings.AUDIO_PROCESSING_MODE = original_audio_mode

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "stem_ready"
    assert payload["tab_generation_status"] == "processing"
    local_run_mock.assert_called_once()

    session = TestingSessionLocal()
    try:
        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).one()
        assert refreshed.processing_status == "stem_ready"
        assert refreshed.tab_generation_status == "processing"
        assert refreshed.celery_task_id is None
        assert refreshed.is_processed is True
    finally:
        session.close()


def test_upload_audio_requires_selected_stem():
    reset_database()
    session = TestingSessionLocal()
    try:
        create_user(session, "missing-stem-owner", "missing-stem-owner@example.com")
    finally:
        session.close()

    response = client.post(
        "/api/v1/audio/upload",
        headers=auth_headers("missing-stem-owner"),
        files={"file": ("sample.wav", b"RIFF....", "audio/wav")},
    )

    assert response.status_code == 422


def test_upload_audio_rejects_when_active_transcription_exists():
    reset_database()
    session = TestingSessionLocal()
    original_audio_mode = config.settings.AUDIO_PROCESSING_MODE
    original_mode = config.settings.PROCESSING_MODE
    original_modal_url = config.settings.MODAL_TRIGGER_URL
    try:
        owner = create_user(session, "active-owner", "active-owner@example.com")
        config.settings.AUDIO_PROCESSING_MODE = "modal"
        config.settings.PROCESSING_MODE = "modal"
        config.settings.MODAL_TRIGGER_URL = "https://modal.test/trigger"
        transcription = models.Transcription(
            title="Processing track",
            audio_file_path="uploads/processing.wav",
            user_id=owner.id,
            is_processed=False,
            processing_status="processing",
        )
        session.add(transcription)
        session.commit()
    finally:
        session.close()

    try:
        with (
            patch("app.api.v1.endpoints.audio._trigger_modal_worker") as modal_trigger_mock,
            patch("app.api.v1.endpoints.audio.celery_app.send_task") as send_task_mock,
        ):
            response = client.post(
                "/api/v1/audio/upload",
                headers=auth_headers("active-owner"),
                data={"selected_stem": "other"},
                files={"file": ("sample.wav", b"RIFF....", "audio/wav")},
            )
    finally:
        config.settings.AUDIO_PROCESSING_MODE = original_audio_mode
        config.settings.PROCESSING_MODE = original_mode
        config.settings.MODAL_TRIGGER_URL = original_modal_url

    assert response.status_code == 429
    assert response.json()["detail"] == (
        "You already have a transcription job in progress. Please wait for it to finish before starting another."
    )
    modal_trigger_mock.assert_not_called()
    send_task_mock.assert_not_called()


def test_upload_audio_reuses_completed_duplicate_same_hash_and_stem():
    reset_database()
    contents = b"RIFF duplicate upload"
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "duplicate-owner", "duplicate-owner@example.com")
        existing = models.Transcription(
            title="Already processed",
            audio_file_path="uploads/existing.wav",
            user_id=owner.id,
            selected_stem="other",
            audio_hash=hashlib.sha256(contents).hexdigest(),
            is_processed=True,
            processing_status="completed",
        )
        session.add(existing)
        session.commit()
        existing_id = existing.id
    finally:
        session.close()

    with patch("app.api.v1.endpoints.audio.celery_app.send_task") as send_task_mock:
        response = client.post(
            "/api/v1/audio/upload",
            headers=auth_headers("duplicate-owner"),
            data={"selected_stem": "other"},
            files={"file": ("same.wav", contents, "audio/wav")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == existing_id
    assert payload["duplicate_reused"] is True
    assert "already processed" in payload["duplicate_message"]
    send_task_mock.assert_not_called()


def test_legacy_processing_mode_is_ignored_for_local_default():
    reset_database()
    session = TestingSessionLocal()
    original_audio_mode = config.settings.AUDIO_PROCESSING_MODE
    original_mode = config.settings.PROCESSING_MODE
    original_modal_url = config.settings.MODAL_TRIGGER_URL
    try:
        create_user(session, "external-mode-owner", "external-mode@example.com")
        config.settings.AUDIO_PROCESSING_MODE = None
        config.settings.PROCESSING_MODE = "external_worker"
        config.settings.MODAL_TRIGGER_URL = "https://modal.test/trigger"
    finally:
        session.close()

    try:
        with (
            patch("app.api.v1.endpoints.audio._celery_has_available_worker", return_value=False),
            patch("app.api.v1.endpoints.audio._run_transcription_locally") as local_runner_mock,
            patch("app.api.v1.endpoints.audio._trigger_modal_worker") as modal_trigger_mock,
        ):
            response = client.post(
                "/api/v1/audio/upload",
                headers=auth_headers("external-mode-owner"),
                data={"selected_stem": "other"},
                files={"file": ("external.wav", b"RIFF external", "audio/wav")},
            )
    finally:
        config.settings.AUDIO_PROCESSING_MODE = original_audio_mode
        config.settings.PROCESSING_MODE = original_mode
        config.settings.MODAL_TRIGGER_URL = original_modal_url

    assert response.status_code == 200
    payload = response.json()
    assert payload["processing_status"] == "processing"
    assert payload["selected_stem"] == "other"
    assert payload["modal_dispatch_status"] != "modal_required"
    local_runner_mock.assert_called_once()
    modal_trigger_mock.assert_not_called()


def test_upload_audio_local_mode_does_not_require_modal_and_runs_background_fallback():
    reset_database()
    session = TestingSessionLocal()
    original_audio_mode = config.settings.AUDIO_PROCESSING_MODE
    original_legacy_mode = config.settings.PROCESSING_MODE
    original_modal_url = config.settings.MODAL_TRIGGER_URL
    try:
        create_user(session, "local-mode-owner", "local-mode@example.com")
        config.settings.AUDIO_PROCESSING_MODE = "local"
        config.settings.PROCESSING_MODE = None
        config.settings.MODAL_TRIGGER_URL = "https://modal.test/trigger"
    finally:
        session.close()

    try:
        with (
            patch("app.api.v1.endpoints.audio._celery_has_available_worker", return_value=False),
            patch("app.api.v1.endpoints.audio._run_transcription_locally") as local_runner_mock,
            patch("app.api.v1.endpoints.audio._trigger_modal_worker") as modal_trigger_mock,
        ):
            response = client.post(
                "/api/v1/audio/upload",
                headers=auth_headers("local-mode-owner"),
                data={"selected_stem": "other"},
                files={"file": ("local.wav", b"RIFF local", "audio/wav")},
            )
    finally:
        config.settings.AUDIO_PROCESSING_MODE = original_audio_mode
        config.settings.PROCESSING_MODE = original_legacy_mode
        config.settings.MODAL_TRIGGER_URL = original_modal_url

    assert response.status_code == 200
    payload = response.json()
    assert payload["processing_status"] == "processing"
    assert payload["modal_dispatch_status"] != "modal_required"
    local_runner_mock.assert_called_once()
    modal_trigger_mock.assert_not_called()


def test_upload_audio_modal_mode_requires_modal_trigger_url():
    reset_database()
    session = TestingSessionLocal()
    original_audio_mode = config.settings.AUDIO_PROCESSING_MODE
    original_legacy_mode = config.settings.PROCESSING_MODE
    original_modal_url = config.settings.MODAL_TRIGGER_URL
    try:
        create_user(session, "modal-config-owner", "modal-config@example.com")
        config.settings.AUDIO_PROCESSING_MODE = "modal"
        config.settings.PROCESSING_MODE = None
        config.settings.MODAL_TRIGGER_URL = None
    finally:
        session.close()

    try:
        response = client.post(
            "/api/v1/audio/upload",
            headers=auth_headers("modal-config-owner"),
            data={"selected_stem": "other"},
            files={"file": ("modal-missing.wav", b"RIFF modal missing", "audio/wav")},
        )
    finally:
        config.settings.AUDIO_PROCESSING_MODE = original_audio_mode
        config.settings.PROCESSING_MODE = original_legacy_mode
        config.settings.MODAL_TRIGGER_URL = original_modal_url

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Modal processing is enabled but MODAL_TRIGGER_URL is not configured."
    )


def test_upload_audio_disabled_mode_returns_clear_error_without_queueing():
    reset_database()
    session = TestingSessionLocal()
    original_audio_mode = config.settings.AUDIO_PROCESSING_MODE
    original_legacy_mode = config.settings.PROCESSING_MODE
    try:
        create_user(session, "disabled-mode-owner", "disabled-mode@example.com")
        config.settings.AUDIO_PROCESSING_MODE = "disabled"
        config.settings.PROCESSING_MODE = None
    finally:
        session.close()

    try:
        response = client.post(
            "/api/v1/audio/upload",
            headers=auth_headers("disabled-mode-owner"),
            data={"selected_stem": "other"},
            files={"file": ("disabled.wav", b"RIFF disabled", "audio/wav")},
        )
    finally:
        config.settings.AUDIO_PROCESSING_MODE = original_audio_mode
        config.settings.PROCESSING_MODE = original_legacy_mode

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Audio processing is disabled by AUDIO_PROCESSING_MODE=disabled."
    )
    session = TestingSessionLocal()
    try:
        assert session.query(models.Transcription).count() == 0
    finally:
        session.close()


def test_local_status_response_masks_stale_modal_required_without_mutating_row():
    reset_database()
    original_audio_mode = config.settings.AUDIO_PROCESSING_MODE
    original_mode = config.settings.PROCESSING_MODE
    session = TestingSessionLocal()
    retry_at = datetime.utcnow() + timedelta(minutes=10)
    try:
        owner = create_user(session, "local-stale-owner", "local-stale@example.com")
        transcription = models.Transcription(
            title="Stale modal row",
            user_id=owner.id,
            selected_stem="other",
            is_processed=False,
            processing_status="queued",
            modal_dispatch_status="modal_required",
            modal_retry_at=retry_at,
            modal_request_id="modal-request-1",
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
        config.settings.AUDIO_PROCESSING_MODE = "local"
        config.settings.PROCESSING_MODE = None
    finally:
        session.close()

    try:
        response = client.get(
            f"/api/v1/audio/{transcription_id}/status",
            headers=auth_headers("local-stale-owner"),
        )
    finally:
        config.settings.AUDIO_PROCESSING_MODE = original_audio_mode
        config.settings.PROCESSING_MODE = original_mode

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["message"] == "Queued for local processing."
    assert "Queued for Modal processing" not in json.dumps(payload)
    assert payload["modal_dispatch_status"] is None
    assert payload["modal_retry_at"] is None

    session = TestingSessionLocal()
    try:
        stored = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).one()
        assert stored.modal_dispatch_status == "modal_required"
        assert stored.modal_request_id == "modal-request-1"
        assert stored.modal_retry_at is not None
    finally:
        session.close()


def test_status_cleanup_skips_celery_inspect_when_no_active_job_is_stale():
    reset_database()
    original_audio_mode = config.settings.AUDIO_PROCESSING_MODE
    original_timeout = config.settings.STALE_TRANSCRIPTION_TIMEOUT_SECONDS
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "fresh-active-owner", "fresh-active@example.com")
        transcription = models.Transcription(
            title="Fresh active row",
            user_id=owner.id,
            selected_stem="other",
            is_processed=False,
            processing_status="processing",
            celery_task_id="fresh-task-id",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
        config.settings.AUDIO_PROCESSING_MODE = "local"
        config.settings.STALE_TRANSCRIPTION_TIMEOUT_SECONDS = 1800
    finally:
        session.close()

    try:
        with patch(
            "app.api.v1.endpoints.audio._active_celery_task_ids"
        ) as active_task_ids_mock:
            response = client.get(
                f"/api/v1/audio/{transcription_id}/status",
                headers=auth_headers("fresh-active-owner"),
            )
    finally:
        config.settings.AUDIO_PROCESSING_MODE = original_audio_mode
        config.settings.STALE_TRANSCRIPTION_TIMEOUT_SECONDS = original_timeout

    assert response.status_code == 200
    active_task_ids_mock.assert_not_called()


def test_stale_cleanup_throttles_repeated_celery_inspect_failure_logs(caplog):
    reset_database()
    original_audio_mode = config.settings.AUDIO_PROCESSING_MODE
    original_timeout = config.settings.STALE_TRANSCRIPTION_TIMEOUT_SECONDS
    original_last_log = audio_endpoint._last_celery_inspect_failure_log_at
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "stale-celery-owner", "stale-celery@example.com")
        transcription = models.Transcription(
            title="Stale celery row",
            user_id=owner.id,
            selected_stem="other",
            is_processed=False,
            processing_status="processing",
            celery_task_id="stale-task-id",
            created_at=datetime.utcnow() - timedelta(hours=2),
            updated_at=datetime.utcnow() - timedelta(hours=2),
        )
        session.add(transcription)
        session.commit()
        config.settings.AUDIO_PROCESSING_MODE = "local"
        config.settings.STALE_TRANSCRIPTION_TIMEOUT_SECONDS = 1
        audio_endpoint._last_celery_inspect_failure_log_at = None

        with patch(
            "app.api.v1.endpoints.audio.celery_app.control.inspect",
            side_effect=RuntimeError("redis refused"),
        ):
            with caplog.at_level(logging.INFO, logger="app.api.v1.endpoints.audio"):
                first_cleanup_count = (
                    audio_endpoint._cleanup_stale_active_transcription_jobs(session)
                )
                second_cleanup_count = (
                    audio_endpoint._cleanup_stale_active_transcription_jobs(session)
                )

        assert first_cleanup_count == 0
        assert second_cleanup_count == 0

        session.refresh(transcription)
        assert transcription.processing_status == "processing"
    finally:
        config.settings.AUDIO_PROCESSING_MODE = original_audio_mode
        config.settings.STALE_TRANSCRIPTION_TIMEOUT_SECONDS = original_timeout
        audio_endpoint._last_celery_inspect_failure_log_at = original_last_log
        session.close()

    inspect_failure_logs = [
        record
        for record in caplog.records
        if "Could not inspect active Celery tasks during stale cleanup" in record.message
    ]
    assert len(inspect_failure_logs) == 1


def test_modal_status_response_preserves_modal_required_fields():
    reset_database()
    original_audio_mode = config.settings.AUDIO_PROCESSING_MODE
    original_mode = config.settings.PROCESSING_MODE
    original_modal_url = config.settings.MODAL_TRIGGER_URL
    session = TestingSessionLocal()
    retry_at = datetime.utcnow() + timedelta(minutes=10)
    try:
        owner = create_user(session, "modal-stale-owner", "modal-stale@example.com")
        transcription = models.Transcription(
            title="Modal queued row",
            user_id=owner.id,
            selected_stem="other",
            is_processed=False,
            processing_status="queued",
            modal_dispatch_status="modal_required",
            modal_retry_at=retry_at,
            modal_request_id="modal-request-2",
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
        config.settings.AUDIO_PROCESSING_MODE = "modal"
        config.settings.PROCESSING_MODE = None
        config.settings.MODAL_TRIGGER_URL = "https://modal.test/trigger"
    finally:
        session.close()

    try:
        response = client.get(
            f"/api/v1/audio/{transcription_id}/status",
            headers=auth_headers("modal-stale-owner"),
        )
    finally:
        config.settings.AUDIO_PROCESSING_MODE = original_audio_mode
        config.settings.PROCESSING_MODE = original_mode
        config.settings.MODAL_TRIGGER_URL = original_modal_url

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["message"] == (
        "Queued for Modal processing. It will start when capacity is available."
    )
    assert payload["modal_dispatch_status"] == "modal_required"
    assert payload["modal_retry_at"] is not None

    session = TestingSessionLocal()
    try:
        stored = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).one()
        assert stored.modal_dispatch_status == "modal_required"
        assert stored.modal_request_id == "modal-request-2"
        assert stored.modal_retry_at is not None
    finally:
        session.close()


def test_upload_audio_modal_mode_triggers_modal_path_without_celery():
    reset_database()
    session = TestingSessionLocal()
    original_audio_mode = config.settings.AUDIO_PROCESSING_MODE
    original_mode = config.settings.PROCESSING_MODE
    original_modal_url = config.settings.MODAL_TRIGGER_URL
    try:
        create_user(session, "modal-mode-owner", "modal-mode@example.com")
        config.settings.AUDIO_PROCESSING_MODE = "modal"
        config.settings.PROCESSING_MODE = "modal"
        config.settings.MODAL_TRIGGER_URL = "https://modal.test/trigger"
    finally:
        session.close()

    try:
        with (
            patch("app.api.v1.endpoints.audio._trigger_modal_worker") as modal_trigger_mock,
            patch("app.api.v1.endpoints.audio.celery_app.send_task") as send_task_mock,
        ):
            response = client.post(
                "/api/v1/audio/upload",
                headers=auth_headers("modal-mode-owner"),
                data={"selected_stem": "bass"},
                files={"file": ("modal.wav", b"RIFF modal", "audio/wav")},
            )
    finally:
        config.settings.AUDIO_PROCESSING_MODE = original_audio_mode
        config.settings.PROCESSING_MODE = original_mode
        config.settings.MODAL_TRIGGER_URL = original_modal_url

    assert response.status_code == 200
    assert response.json()["selected_stem"] == "bass"
    assert response.json()["processing_status"] == "processing"
    modal_trigger_mock.assert_called_once()
    send_task_mock.assert_not_called()


def test_upload_audio_modal_second_job_is_rejected_while_first_is_processing():
    reset_database()
    session = TestingSessionLocal()
    original_audio_mode = config.settings.AUDIO_PROCESSING_MODE
    original_mode = config.settings.PROCESSING_MODE
    original_modal_url = config.settings.MODAL_TRIGGER_URL
    try:
        create_user(session, "modal-queue-owner", "modal-queue@example.com")
        config.settings.AUDIO_PROCESSING_MODE = "modal"
        config.settings.PROCESSING_MODE = "modal"
        config.settings.MODAL_TRIGGER_URL = "https://modal.test/trigger"
    finally:
        session.close()

    try:
        with patch("app.api.v1.endpoints.audio._trigger_modal_worker") as modal_trigger_mock:
            first = client.post(
                "/api/v1/audio/upload",
                headers=auth_headers("modal-queue-owner"),
                data={"selected_stem": "bass"},
                files={"file": ("first.wav", b"RIFF first", "audio/wav")},
            )
            second = client.post(
                "/api/v1/audio/upload",
                headers=auth_headers("modal-queue-owner"),
                data={"selected_stem": "bass"},
                files={"file": ("second.wav", b"RIFF second", "audio/wav")},
            )
    finally:
        config.settings.AUDIO_PROCESSING_MODE = original_audio_mode
        config.settings.PROCESSING_MODE = original_mode
        config.settings.MODAL_TRIGGER_URL = original_modal_url

    assert first.status_code == 200
    assert second.status_code == 429
    assert first.json()["processing_status"] == "processing"
    assert second.json()["detail"] == (
        "You already have a transcription job in progress. Please wait for it to finish before starting another."
    )
    modal_trigger_mock.assert_called_once()


def test_worker_complete_triggers_oldest_queued_modal_job():
    reset_database()
    original_token = config.settings.WORKER_API_TOKEN
    original_audio_mode = config.settings.AUDIO_PROCESSING_MODE
    original_mode = config.settings.PROCESSING_MODE
    original_modal_url = config.settings.MODAL_TRIGGER_URL
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "handoff-owner", "handoff@example.com")
        first = models.Transcription(
            title="Complete first",
            user_id=owner.id,
            selected_stem="other",
            original_audio_url="https://res.cloudinary.com/demo/video/upload/first.wav",
            is_processed=False,
            processing_status="processing",
        )
        second = models.Transcription(
            title="Queued second",
            user_id=owner.id,
            selected_stem="bass",
            original_audio_url="https://res.cloudinary.com/demo/video/upload/second.wav",
            is_processed=False,
            processing_status="queued",
            created_at=datetime.utcnow() + timedelta(seconds=1),
        )
        session.add_all([first, second])
        session.commit()
        first_id = first.id
        second_id = second.id
        config.settings.WORKER_API_TOKEN = "test-worker-token"
        config.settings.AUDIO_PROCESSING_MODE = "modal"
        config.settings.PROCESSING_MODE = "modal"
        config.settings.MODAL_TRIGGER_URL = "https://modal.test/trigger"
    finally:
        session.close()

    try:
        with patch("app.api.v1.endpoints.audio._trigger_modal_worker") as modal_trigger_mock:
            response = client.post(
                f"/api/v1/worker/jobs/{first_id}/complete",
                headers={"X-Worker-Token": "test-worker-token"},
                json={
                    "notes_data": {"notes": [{"pitch": 64, "onset": 0.0, "offset": 0.5}]},
                    "tablature_data": {"instrument": "guitar", "tablature": []},
                },
            )
    finally:
        config.settings.WORKER_API_TOKEN = original_token
        config.settings.AUDIO_PROCESSING_MODE = original_audio_mode
        config.settings.PROCESSING_MODE = original_mode
        config.settings.MODAL_TRIGGER_URL = original_modal_url

    assert response.status_code == 200
    modal_trigger_mock.assert_called_once_with(second_id, "process", None, None)
    session = TestingSessionLocal()
    try:
        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == second_id
        ).one()
        assert refreshed.processing_status == "processing"
        assert refreshed.queue_position == 0
    finally:
        session.close()


def test_second_modal_upload_does_not_become_processing_while_first_is_active():
    reset_database()
    session = TestingSessionLocal()
    original_audio_mode = config.settings.AUDIO_PROCESSING_MODE
    original_mode = config.settings.PROCESSING_MODE
    original_modal_url = config.settings.MODAL_TRIGGER_URL
    try:
        create_user(session, "race-owner-a", "race-a@example.com")
        create_user(session, "race-owner-b", "race-b@example.com")
        config.settings.AUDIO_PROCESSING_MODE = "modal"
        config.settings.PROCESSING_MODE = "modal"
        config.settings.MODAL_TRIGGER_URL = "https://modal.test/trigger"
    finally:
        session.close()

    def upload(username: str, filename: str, contents: bytes):
        return client.post(
            "/api/v1/audio/upload",
            headers=auth_headers(username),
            data={"selected_stem": "other"},
            files={"file": (filename, contents, "audio/wav")},
        )

    try:
        with patch("app.api.v1.endpoints.audio._trigger_modal_worker") as modal_trigger_mock:
            responses = [
                upload("race-owner-a", "race-a.wav", b"RIFF race a"),
                upload("race-owner-b", "race-b.wav", b"RIFF race b"),
            ]
    finally:
        config.settings.AUDIO_PROCESSING_MODE = original_audio_mode
        config.settings.PROCESSING_MODE = original_mode
        config.settings.MODAL_TRIGGER_URL = original_modal_url

    assert sorted(response.status_code for response in responses) == [200, 200]
    session = TestingSessionLocal()
    try:
        statuses = [
            row[0]
            for row in session.query(models.Transcription.processing_status).all()
        ]
    finally:
        session.close()

    assert statuses.count("processing") == 1
    assert statuses.count("queued") == 1
    assert modal_trigger_mock.call_count == 1


def test_worker_endpoints_require_worker_token():
    reset_database()
    original_token = config.settings.WORKER_API_TOKEN
    try:
        config.settings.WORKER_API_TOKEN = "test-worker-token"
        response = client.get("/api/v1/worker/jobs/next")
    finally:
        config.settings.WORKER_API_TOKEN = original_token

    assert response.status_code == 401


def test_worker_next_marks_oldest_queued_job_processing():
    reset_database()
    original_token = config.settings.WORKER_API_TOKEN
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "worker-owner", "worker-owner@example.com")
        transcription = models.Transcription(
            title="Worker job",
            user_id=owner.id,
            selected_stem="other",
            source_type="upload",
            source_url="worker.wav",
            audio_hash="hash-worker",
            original_audio_url="https://res.cloudinary.com/demo/video/upload/source.wav",
            is_processed=False,
            processing_status="queued",
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
        config.settings.WORKER_API_TOKEN = "test-worker-token"
    finally:
        session.close()

    try:
        response = client.get(
            "/api/v1/worker/jobs/next",
            headers={"Authorization": "Bearer test-worker-token"},
        )
    finally:
        config.settings.WORKER_API_TOKEN = original_token

    assert response.status_code == 200
    payload = response.json()
    assert payload["transcription_id"] == transcription_id
    assert payload["selected_stem"] == "other"
    assert payload["demucs_stem"] == "other"
    assert payload["original_audio_url"].startswith("https://res.cloudinary.com")

    session = TestingSessionLocal()
    try:
        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).first()
        assert refreshed.processing_status == "processing"
        assert refreshed.queue_position == 0
    finally:
        session.close()


def test_worker_complete_saves_cloudinary_outputs_and_track_metadata():
    reset_database()
    original_token = config.settings.WORKER_API_TOKEN
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "complete-owner", "complete-owner@example.com")
        transcription = models.Transcription(
            title="Complete job",
            user_id=owner.id,
            selected_stem="other",
            original_audio_url="https://res.cloudinary.com/demo/video/upload/source.wav",
            is_processed=False,
            processing_status="processing",
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
        config.settings.WORKER_API_TOKEN = "test-worker-token"
    finally:
        session.close()

    try:
        response = client.post(
            f"/api/v1/worker/jobs/{transcription_id}/complete",
            headers={"X-Worker-Token": "test-worker-token"},
            json={
                "separated_audio_url": "https://res.cloudinary.com/demo/video/upload/stem.wav",
                "separated_audio_public_id": "musicstudio/stem",
                "midi_file_url": "https://res.cloudinary.com/demo/raw/upload/out.mid",
                "midi_file_public_id": "musicstudio/out-midi",
                "tab_file_url": "https://res.cloudinary.com/demo/raw/upload/out.txt",
                "tab_file_public_id": "musicstudio/out-tab",
                "confidence": 84,
                "notes_data": {"notes": [{"pitch": 64, "onset": 0.0, "offset": 0.5}]},
                "tablature_data": {"instrument": "guitar", "tablature": []},
                "detected_tempo": 120,
                "detected_key": "E minor",
            },
        )
    finally:
        config.settings.WORKER_API_TOKEN = original_token

    assert response.status_code == 200
    payload = response.json()
    assert payload["processing_status"] == "stem_ready"
    assert payload["is_processed"] is True
    assert payload["separated_audio_public_id"] == "musicstudio/stem"
    assert payload["processing_error"] is None

    session = TestingSessionLocal()
    try:
        track = session.query(models.InstrumentTrack).filter(
            models.InstrumentTrack.transcription_id == transcription_id
        ).one()
        assert track.instrument_type == "guitar"
        assert track.confidence_score == 84
        assert track.processing_status == "stem_ready"
    finally:
        session.close()


def test_worker_generate_tab_complete_derives_missing_structured_tablature_for_status_and_result():
    reset_database()
    original_token = config.settings.WORKER_API_TOKEN
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "derive-tab-owner", "derive-tab@example.com")
        transcription = models.Transcription(
            title="Derive tab payload",
            user_id=owner.id,
            selected_stem="bass",
            separated_audio_url="https://res.cloudinary.com/demo/video/upload/bass.wav",
            is_processed=True,
            processing_status="stem_ready",
            tab_generation_status="processing",
            modal_job_type="generate_tab",
            can_play_stem=True,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
        config.settings.WORKER_API_TOKEN = "test-worker-token"
    finally:
        session.close()

    notes_payload = {
        "notes": [
            {"pitch": 43, "onset": 0.0, "offset": 0.5, "velocity": 84, "confidence": 0.91}
        ]
    }

    try:
        response = client.post(
            f"/api/v1/worker/jobs/{transcription_id}/complete",
            headers={"X-Worker-Token": "test-worker-token"},
            json={
                "midi_file_url": "https://res.cloudinary.com/demo/raw/upload/out.mid",
                "tab_file_url": "https://res.cloudinary.com/demo/raw/upload/out.tab",
                "notes_data": notes_payload,
                "tablature_data": None,
            },
        )
    finally:
        config.settings.WORKER_API_TOKEN = original_token

    assert response.status_code == 200
    payload = response.json()
    assert payload["tab_generation_status"] == "completed"
    assert payload["notes_data"] == json.dumps(notes_payload)
    assert payload["tablature_data"] is not None
    parsed_tab = json.loads(payload["tablature_data"])
    assert parsed_tab["instrument"] == "bass"
    assert parsed_tab["tablature"]

    headers = auth_headers("derive-tab-owner")
    status_payload = client.get(
        f"/api/v1/audio/{transcription_id}/status",
        headers=headers,
    ).json()
    result_payload = client.get(
        f"/api/v1/audio/{transcription_id}/result",
        headers=headers,
    ).json()
    assert status_payload["tablature_data"] == payload["tablature_data"]
    assert result_payload["tablature_data"] == payload["tablature_data"]
    assert status_payload["notes_data"] == payload["notes_data"]
    assert result_payload["notes_data"] == payload["notes_data"]


def test_worker_reprocess_complete_derives_missing_structured_tablature_for_track():
    reset_database()
    original_token = config.settings.WORKER_API_TOKEN
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "reprocess-tab-owner", "reprocess-tab@example.com")
        transcription = models.Transcription(
            title="Reprocess tab payload",
            user_id=owner.id,
            selected_stem="bass",
            separated_audio_url="https://res.cloudinary.com/demo/video/upload/bass.wav",
            is_processed=True,
            processing_status="completed",
            tab_generation_status="completed",
            modal_job_type="reprocess_track",
            can_play_stem=True,
        )
        session.add(transcription)
        session.flush()
        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="bass",
            display_name="Bass",
            processing_status="processing",
        )
        session.add(track)
        session.commit()
        transcription_id = transcription.id
        track_id = track.id
        config.settings.WORKER_API_TOKEN = "test-worker-token"
    finally:
        session.close()

    notes_payload = {
        "notes": [
            {"pitch": 43, "onset": 0.0, "offset": 0.5, "velocity": 84, "confidence": 0.91}
        ]
    }

    try:
        response = client.post(
            f"/api/v1/worker/jobs/{transcription_id}/complete",
            headers={"X-Worker-Token": "test-worker-token"},
            json={
                "track_id": track_id,
                "notes_data": notes_payload,
                "tablature_data": None,
            },
        )
    finally:
        config.settings.WORKER_API_TOKEN = original_token

    assert response.status_code == 200
    payload = response.json()
    parsed_tab = json.loads(payload["tablature_data"])
    assert parsed_tab["instrument"] == "bass"
    assert parsed_tab["tablature"]

    session = TestingSessionLocal()
    try:
        refreshed_track = session.query(models.InstrumentTrack).filter(
            models.InstrumentTrack.id == track_id
        ).one()
        assert refreshed_track.processing_status == "completed"
        assert refreshed_track.tab_json == payload["tablature_data"]
        assert refreshed_track.notes_json == payload["notes_data"]
    finally:
        session.close()


def test_result_endpoint_repairs_and_persists_missing_structured_tablature():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "repair-result-owner", "repair-result@example.com")
        notes_payload = {
            "notes": [
                {"pitch": 43, "onset": 0.0, "offset": 0.5, "velocity": 84}
            ]
        }
        transcription = models.Transcription(
            title="Repair existing result",
            user_id=owner.id,
            selected_stem="bass",
            separated_audio_url="https://res.cloudinary.com/demo/video/upload/bass.wav",
            notes_data=json.dumps(notes_payload),
            tablature_data=None,
            is_processed=True,
            processing_status="completed",
            tab_generation_status="completed",
            can_play_stem=True,
            can_generate_score=True,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
    finally:
        session.close()

    response = client.get(
        f"/api/v1/audio/{transcription_id}/result",
        headers=auth_headers("repair-result-owner"),
    )

    assert response.status_code == 200
    payload = response.json()
    parsed_tab = json.loads(payload["tablature_data"])
    assert parsed_tab["instrument"] == "bass"
    assert parsed_tab["tablature"]

    session = TestingSessionLocal()
    try:
        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).one()
        assert refreshed.tablature_data == payload["tablature_data"]
    finally:
        session.close()


def test_result_endpoint_repairs_matching_track_tablature_too():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "repair-track-owner", "repair-track@example.com")
        notes_payload = {
            "notes": [
                {"pitch": 43, "onset": 0.0, "offset": 0.5, "velocity": 84}
            ]
        }
        transcription = models.Transcription(
            title="Repair track result",
            user_id=owner.id,
            selected_stem="bass",
            separated_audio_url="https://res.cloudinary.com/demo/video/upload/bass.wav",
            notes_data=json.dumps(notes_payload),
            tablature_data=None,
            is_processed=True,
            processing_status="completed",
            tab_generation_status="completed",
            can_play_stem=True,
            can_generate_score=True,
        )
        session.add(transcription)
        session.flush()
        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="bass",
            display_name="Bass",
            notes_json=json.dumps(notes_payload),
            tab_json=None,
            processing_status="completed_with_warning",
        )
        session.add(track)
        session.commit()
        transcription_id = transcription.id
        track_id = track.id
    finally:
        session.close()

    response = client.get(
        f"/api/v1/audio/{transcription_id}/result",
        headers=auth_headers("repair-track-owner"),
    )

    assert response.status_code == 200
    payload = response.json()
    parsed_tab = json.loads(payload["tablature_data"])
    assert parsed_tab["instrument"] == "bass"
    assert parsed_tab["tablature"]

    session = TestingSessionLocal()
    try:
        refreshed_track = session.query(models.InstrumentTrack).filter(
            models.InstrumentTrack.id == track_id
        ).one()
        assert refreshed_track.tab_json == payload["tablature_data"]
        assert refreshed_track.processing_status == "completed"
    finally:
        session.close()


def test_status_repair_never_overwrites_valid_structured_tablature():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "valid-tab-owner", "valid-tab@example.com")
        existing_tab = sample_tab_json("bass")
        transcription = models.Transcription(
            title="Already valid tab",
            user_id=owner.id,
            selected_stem="bass",
            separated_audio_url="https://res.cloudinary.com/demo/video/upload/bass.wav",
            notes_data=sample_notes_json(),
            tablature_data=existing_tab,
            is_processed=True,
            processing_status="completed",
            tab_generation_status="completed",
            can_play_stem=True,
            can_generate_score=True,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
    finally:
        session.close()

    with patch("app.api.v1.endpoints.audio.tablature.notes_to_tablature") as tab_mock:
        response = client.get(
            f"/api/v1/audio/{transcription_id}/status",
            headers=auth_headers("valid-tab-owner"),
        )

    assert response.status_code == 200
    assert response.json()["tablature_data"] == existing_tab
    tab_mock.assert_not_called()


def test_status_repair_skips_while_tab_generation_is_processing():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "processing-tab-owner", "processing-tab@example.com")
        transcription = models.Transcription(
            title="Processing tab",
            user_id=owner.id,
            selected_stem="other",
            separated_audio_url="https://res.cloudinary.com/demo/video/upload/guitar.wav",
            notes_data=sample_notes_json(),
            tablature_data=None,
            is_processed=True,
            processing_status="stem_ready",
            tab_generation_status="processing",
            can_play_stem=True,
            can_generate_score=False,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
    finally:
        session.close()

    with patch("app.api.v1.endpoints.audio.tablature.notes_to_tablature") as tab_mock:
        response = client.get(
            f"/api/v1/audio/{transcription_id}/status",
            headers=auth_headers("processing-tab-owner"),
        )

    assert response.status_code == 200
    assert response.json()["tablature_data"] is None
    tab_mock.assert_not_called()


def test_result_repairs_completed_tab_generation_stuck_in_processing():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "stuck-tab-owner", "stuck-tab@example.com")
        transcription = models.Transcription(
            title="Stuck tab generation",
            user_id=owner.id,
            selected_stem="other",
            separated_audio_file_path="uploads/separated/transcription_1/other.wav",
            notes_data=sample_notes_json(),
            tablature_data=sample_tab_json(),
            is_processed=False,
            processing_status="processing",
            tab_generation_status="completed",
            can_play_stem=True,
            can_generate_score=True,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
    finally:
        session.close()

    response = client.get(
        f"/api/v1/audio/{transcription_id}/result",
        headers=auth_headers("stuck-tab-owner"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processing_status"] == "completed"
    assert payload["tab_generation_status"] == "completed"
    assert payload["can_generate_score"] is True

    session = TestingSessionLocal()
    try:
        refreshed = session.query(models.Transcription).get(transcription_id)
        assert refreshed.processing_status == "completed"
        assert refreshed.is_processed is True
        assert refreshed.celery_task_id is None
    finally:
        session.close()


def test_worker_generate_tab_complete_does_not_mark_completed_when_structured_tab_fails():
    reset_database()
    original_token = config.settings.WORKER_API_TOKEN
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "failed-structured-tab-owner", "failed-structured-tab@example.com")
        transcription = models.Transcription(
            title="Failed structured tab",
            user_id=owner.id,
            selected_stem="other",
            separated_audio_url="https://res.cloudinary.com/demo/video/upload/guitar.wav",
            is_processed=True,
            processing_status="stem_ready",
            tab_generation_status="processing",
            modal_job_type="generate_tab",
            can_play_stem=True,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
        config.settings.WORKER_API_TOKEN = "test-worker-token"
    finally:
        session.close()

    try:
        with patch(
            "app.api.v1.endpoints.worker.tablature.notes_to_tablature",
            side_effect=RuntimeError("tab conversion failed"),
        ):
            response = client.post(
                f"/api/v1/worker/jobs/{transcription_id}/complete",
                headers={"X-Worker-Token": "test-worker-token"},
                json={
                    "midi_file_url": "https://res.cloudinary.com/demo/raw/upload/out.mid",
                    "tab_file_url": "https://res.cloudinary.com/demo/raw/upload/out.tab",
                    "notes_data": {
                        "notes": [
                            {
                                "pitch": 64,
                                "onset": 0.0,
                                "offset": 0.5,
                                "velocity": 90,
                            }
                        ]
                    },
                    "tablature_data": None,
                },
            )
    finally:
        config.settings.WORKER_API_TOKEN = original_token

    assert response.status_code == 200
    payload = response.json()
    assert payload["tab_generation_status"] == "completed_with_warning"
    assert payload["processing_status"] == "stem_ready"
    assert payload["tablature_data"] is None
    assert "structured tablature" in payload["processing_error"]
    assert payload["notes_data"] is not None
    assert payload["midi_file_url"].endswith("out.mid")
    assert payload["tab_file_url"].endswith("out.tab")


def test_worker_generate_tab_complete_deletes_only_original_cloudinary_audio():
    reset_database()
    original_token = config.settings.WORKER_API_TOKEN
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "cleanup-original-owner", "cleanup-original@example.com")
        transcription = models.Transcription(
            title="Cleanup original after tab",
            user_id=owner.id,
            selected_stem="bass",
            original_audio_url="https://res.cloudinary.com/demo/video/upload/source.wav",
            original_audio_public_id="musicstudio/original",
            separated_audio_url="https://res.cloudinary.com/demo/video/upload/bass.wav",
            separated_audio_public_id="musicstudio/stem",
            is_processed=True,
            processing_status="stem_ready",
            tab_generation_status="processing",
            modal_job_type="generate_tab",
            can_play_stem=True,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
        config.settings.WORKER_API_TOKEN = "test-worker-token"
    finally:
        session.close()

    try:
        with patch(
            "app.api.v1.endpoints.worker.storage.delete_cloudinary_asset",
            return_value=True,
        ) as delete_mock:
            response = client.post(
                f"/api/v1/worker/jobs/{transcription_id}/complete",
                headers={"X-Worker-Token": "test-worker-token"},
                json={
                    "separated_audio_url": "https://res.cloudinary.com/demo/video/upload/bass.wav",
                    "separated_audio_public_id": "musicstudio/stem",
                    "midi_file_url": "https://res.cloudinary.com/demo/raw/upload/out.mid",
                    "midi_file_public_id": "musicstudio/out-midi",
                    "tab_file_url": "https://res.cloudinary.com/demo/raw/upload/out.tab",
                    "tab_file_public_id": "musicstudio/out-tab",
                    "notes_data": {
                        "notes": [
                            {"pitch": 43, "onset": 0.0, "offset": 0.5, "velocity": 84}
                        ]
                    },
                    "tablature_data": {
                        "instrument": "bass",
                        "tablature": [
                            {"string": 1, "fret": 0, "onset": 0.0, "offset": 0.5}
                        ],
                    },
                },
            )
    finally:
        config.settings.WORKER_API_TOKEN = original_token

    assert response.status_code == 200
    delete_mock.assert_called_once_with("musicstudio/original", resource_type="video")
    payload = response.json()
    assert payload["original_audio_url"] is None
    assert payload["original_audio_public_id"] is None
    assert payload["separated_audio_url"].endswith("bass.wav")
    assert payload["separated_audio_public_id"] == "musicstudio/stem"
    assert payload["midi_file_url"].endswith("out.mid")
    assert payload["tab_file_url"].endswith("out.tab")
    assert payload["notes_data"] is not None
    assert payload["tablature_data"] is not None


def test_worker_complete_does_not_keep_stale_separated_audio_url_without_secure_url():
    reset_database()
    original_token = config.settings.WORKER_API_TOKEN
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "missing-secure-owner", "missing-secure@example.com")
        transcription = models.Transcription(
            title="Missing secure URL job",
            user_id=owner.id,
            selected_stem="other",
            original_audio_url="https://res.cloudinary.com/demo/video/upload/source.wav",
            separated_audio_url="https://res.cloudinary.com/demo/video/upload/stale.wav",
            separated_audio_public_id="musicstudio/stale",
            is_processed=False,
            processing_status="processing",
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
        config.settings.WORKER_API_TOKEN = "test-worker-token"
    finally:
        session.close()

    try:
        response = client.post(
            f"/api/v1/worker/jobs/{transcription_id}/complete",
            headers={"X-Worker-Token": "test-worker-token"},
            json={
                "separated_audio_url": None,
                "separated_audio_public_id": "musicstudio/new-without-url",
                "confidence": 84,
            },
        )
    finally:
        config.settings.WORKER_API_TOKEN = original_token

    assert response.status_code == 200
    payload = response.json()
    assert payload["separated_audio_url"] is None
    assert payload["separated_audio_public_id"] is None
    assert payload["can_play_stem"] is False

    session = TestingSessionLocal()
    try:
        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).one()
        assert refreshed.separated_audio_url is None
        assert refreshed.separated_audio_public_id is None
    finally:
        session.close()


def test_worker_complete_persists_empty_notes_warning_for_modal_stem():
    reset_database()
    original_token = config.settings.WORKER_API_TOKEN
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "modal-warning-owner", "modal-warning-owner@example.com")
        transcription = models.Transcription(
            title="Modal warning job",
            user_id=owner.id,
            selected_stem="other",
            original_audio_url="https://res.cloudinary.com/demo/video/upload/source.wav",
            is_processed=False,
            processing_status="processing",
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
        config.settings.WORKER_API_TOKEN = "test-worker-token"
    finally:
        session.close()

    try:
        response = client.post(
            f"/api/v1/worker/jobs/{transcription_id}/complete",
            headers={"X-Worker-Token": "test-worker-token"},
            json={
                "separated_audio_url": "https://res.cloudinary.com/demo/video/upload/stem.wav",
                "separated_audio_public_id": "musicstudio/stem",
                "confidence": 90,
                "track_metadata": {
                    "confidence_notes": "Selected stem separated by Modal/Demucs.",
                },
            },
        )
    finally:
        config.settings.WORKER_API_TOKEN = original_token

    assert response.status_code == 200
    payload = response.json()
    assert payload["processing_status"] == "completed_with_warning"
    assert payload["warning_message"] == "No note events detected for this stem."
    assert json.loads(payload["notes_data"]) == {
        "notes": [],
        "message": "No note events detected for this stem.",
    }

    session = TestingSessionLocal()
    try:
        track = session.query(models.InstrumentTrack).filter(
            models.InstrumentTrack.transcription_id == transcription_id
        ).one()
        assert track.instrument_type == "guitar"
        assert track.processing_status == "completed_with_warning"
        assert json.loads(track.notes_json) == {
            "notes": [],
            "message": "No note events detected for this stem.",
        }
        assert track.confidence_notes == "Selected stem separated by Modal/Demucs."
    finally:
        session.close()


def test_status_no_note_warning_is_completed_and_playable(tmp_path):
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "warning-owner", "warning-owner@example.com")
        stem_path = tmp_path / "other.wav"
        stem_path.write_bytes(b"stem")
        transcription = models.Transcription(
            title="No note warning",
            user_id=owner.id,
            selected_stem="other",
            separated_audio_file_path=str(stem_path),
            notes_data='{"notes": [], "message": "No note events detected for this stem."}',
            is_processed=True,
            processing_status="stem_ready",
            warning_message="No note events detected for this stem.",
            can_play_stem=True,
            can_generate_score=False,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
        session.add(models.InstrumentTrack(
            transcription_id=transcription_id,
            instrument_type="guitar",
            display_name="Guitar",
            stem_audio_path=str(stem_path),
            processing_status="completed_with_warning",
            confidence_notes="No note events detected for this stem.",
        ))
        session.commit()
    finally:
        session.close()

    response = client.get(
        f"/api/v1/audio/{transcription_id}/status",
        headers=auth_headers("warning-owner"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "stem_ready"
    assert payload["warning"] == "No note events detected for this stem."
    assert payload["warning_message"] == "No note events detected for this stem."
    assert payload["transcription_id"] == transcription_id
    assert payload["selected_stem"] == "other"
    assert payload["can_play_stem"] is True
    assert payload["can_generate_score"] is False
    assert payload["can_generate_tab"] is False
    assert payload["can_generate_rhythm"] is False
    assert payload["separated_audio_url"] is None
    assert payload["available_exports"] == []
    assert payload["is_demo"] is False
    assert payload["queue_position"] is None
    assert payload["estimated_wait_time"] is None
    assert payload["modal_dispatch_status"] is None
    assert payload["modal_retry_at"] is None
    assert payload["message"] == "Stem is ready. Listen first, then generate tabs if the stem sounds useful."
    assert payload["output_mode"] == "playback_only"


def test_status_repairs_processing_playback_only_stem_to_stem_ready(tmp_path):
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "stem-ready-owner", "stem-ready-owner@example.com")
        stem_path = tmp_path / "bass.wav"
        stem_path.write_bytes(b"stem")
        transcription = models.Transcription(
            title="Separated bass stem",
            user_id=owner.id,
            selected_stem="bass",
            separated_audio_file_path=str(stem_path),
            is_processed=True,
            processing_status="processing",
            can_play_stem=True,
            can_generate_score=False,
            queue_position=0,
            estimated_wait_time=0,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
    finally:
        session.close()

    response = client.get(
        f"/api/v1/audio/{transcription_id}/status",
        headers=auth_headers("stem-ready-owner"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "stem_ready"
    assert payload["output_mode"] == "playback_only"
    assert payload["can_play_stem"] is True
    assert payload["can_generate_score"] is False
    assert payload["can_generate_tab"] is False
    assert payload["can_generate_rhythm"] is False
    assert payload["selected_stem"] == "bass"
    assert payload["queue_position"] is None
    assert payload["estimated_wait_time"] is None
    assert payload["message"] == (
        "Stem is ready. Listen first, then generate tabs if the stem sounds useful."
    )

    result_response = client.get(
        f"/api/v1/audio/{transcription_id}/result",
        headers=auth_headers("stem-ready-owner"),
    )
    assert result_response.status_code == 200
    result_payload = result_response.json()
    assert result_payload["processing_status"] == "stem_ready"
    assert result_payload["output_mode"] == "playback_only"
    assert result_payload["can_generate_tab"] is False
    assert result_payload["can_generate_rhythm"] is False

    session = TestingSessionLocal()
    try:
        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).one()
        assert refreshed.processing_status == "stem_ready"
        assert refreshed.can_play_stem is True
        assert refreshed.can_generate_score is False
        assert refreshed.queue_position is None
        assert refreshed.estimated_wait_time is None
    finally:
        session.close()


def test_drum_payloads_are_rhythm_only_across_result_and_status(tmp_path):
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "drum-owner", "drum-owner@example.com")
        stem_path = tmp_path / "drums.wav"
        stem_path.write_bytes(b"stem")
        notes_data = json.dumps({
            "drum_hits": [{"onset": 0.0, "offset": 0.1, "confidence": 0.8}],
            "rhythm_analysis": {"total_duration": 1.0},
        })
        transcription = models.Transcription(
            title="Drum rhythm",
            user_id=owner.id,
            selected_stem="drums",
            separated_audio_file_path=str(stem_path),
            notes_data=notes_data,
            tablature_data='{"tablature": [{"fret": 0}]}',
            midi_file_path=str(tmp_path / "stale.mid"),
            tab_file_path=str(tmp_path / "stale.tab"),
            is_processed=True,
            processing_status="completed",
            can_play_stem=True,
            can_generate_score=True,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
    finally:
        session.close()

    for suffix in ("result", "status"):
        response = client.get(
            f"/api/v1/audio/{transcription_id}/{suffix}",
            headers=auth_headers("drum-owner"),
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["selected_stem"] == "drums"
        assert payload["can_generate_score"] is False
        assert payload["can_generate_tab"] is False
        assert payload["can_generate_rhythm"] is True
        assert payload["available_exports"] == []
        assert payload["output_mode"] == "rhythm"


def test_drum_stem_ready_payload_is_playback_with_rhythm_generation_available(tmp_path):
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "drum-ready-owner", "drum-ready@example.com")
        stem_path = tmp_path / "drums.wav"
        stem_path.write_bytes(b"stem")
        transcription = models.Transcription(
            title="Drum stem ready",
            user_id=owner.id,
            selected_stem="drums",
            separated_audio_file_path=str(stem_path),
            is_processed=True,
            processing_status="stem_ready",
            can_play_stem=True,
            can_generate_score=False,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
    finally:
        session.close()

    response = client.get(
        f"/api/v1/audio/{transcription_id}/status",
        headers=auth_headers("drum-ready-owner"),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["output_mode"] == "playback_only"
    assert payload["can_generate_score"] is False
    assert payload["can_generate_tab"] is False
    assert payload["can_generate_rhythm"] is True
    assert payload["available_exports"] == []


def test_retry_transcription_endpoint_queues_lower_threshold_retry(tmp_path):
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "retry-owner", "retry-owner@example.com")
        stem_path = tmp_path / "other.wav"
        stem_path.write_bytes(b"stem")
        transcription = models.Transcription(
            title="Retry warning",
            user_id=owner.id,
            selected_stem="other",
            separated_audio_file_path=str(stem_path),
            notes_data='{"notes": []}',
            is_processed=True,
            processing_status="completed_with_warning",
            warning_message="No note events detected for this stem.",
            can_play_stem=True,
            can_generate_score=False,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
        session.add(models.InstrumentTrack(
            transcription_id=transcription_id,
            instrument_type="guitar",
            display_name="Guitar",
            stem_audio_path=str(stem_path),
            processing_status="completed_with_warning",
        ))
        session.commit()
    finally:
        session.close()

    with patch("app.api.v1.endpoints.audio._start_transcription_processing", return_value="retry-task") as start_mock:
        response = client.post(
            f"/api/v1/audio/{transcription_id}/retry",
            headers=auth_headers("retry-owner"),
            json={"lower_threshold": True},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "processing"
    assert payload["selected_stem"] == "other"
    assert payload["can_play_stem"] is True
    assert payload["can_generate_score"] is True
    assert start_mock.call_args.kwargs["detection_sensitivity"] == "high"

    session = TestingSessionLocal()
    try:
        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).one()
        assert refreshed.processing_status == "processing"
        assert refreshed.warning_message is None
        assert refreshed.celery_task_id == "retry-task"
    finally:
        session.close()


def test_generate_tab_endpoint_accepts_high_sensitivity_option():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "tab-owner", "tab-owner@example.com")
        transcription = models.Transcription(
            title="Tab from stem",
            user_id=owner.id,
            selected_stem="bass",
            separated_audio_file_path=str(Path("/tmp/bass.wav")),
            can_play_stem=True,
            processing_status="stem_ready",
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
    finally:
        session.close()

    with patch("app.api.v1.endpoints.audio._start_tab_generation", return_value="tab-task") as start_mock:
        response = client.post(
            f"/api/v1/audio/{transcription_id}/generate-tabs",
            headers=auth_headers("tab-owner"),
            json={"sensitivity": "high"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "stem_ready"
    assert payload["selected_stem"] == "bass"
    assert payload["can_play_stem"] is True
    assert payload["can_generate_score"] is False
    assert payload["tab_generation_status"] == "processing"
    assert payload["rhythm_generation_status"] == "idle"
    assert payload["message"] == "Tab generation started."
    assert start_mock.call_args.args[0] == transcription_id
    assert start_mock.call_args.kwargs["detection_sensitivity"] == "high"
    assert isinstance(start_mock.call_args.args[1], BackgroundTasks)

    session = TestingSessionLocal()
    try:
        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).one()
        assert refreshed.processing_status == "stem_ready"
        assert refreshed.tab_generation_status == "processing"
        assert refreshed.rhythm_generation_status == "idle"
        assert refreshed.celery_task_id == "tab-task"
    finally:
        session.close()


def test_generate_tab_endpoint_requires_separated_stem_for_bass_other():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "missing-tab-stem-owner", "missing-tab-stem@example.com")
        transcription = models.Transcription(
            title="No stem tab",
            user_id=owner.id,
            selected_stem="other",
            original_audio_url="https://res.cloudinary.com/demo/video/upload/original.wav",
            audio_file_path="/tmp/original.wav",
            can_play_stem=True,
            processing_status="stem_ready",
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
    finally:
        session.close()

    with patch("app.api.v1.endpoints.audio._start_tab_generation") as start_mock:
        response = client.post(
            f"/api/v1/audio/{transcription_id}/generate-tabs",
            headers=auth_headers("missing-tab-stem-owner"),
            json={},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Separated stem audio is required before generating tabs."
    start_mock.assert_not_called()


def test_modal_generate_tab_payload_uses_only_separated_url():
    transcription = models.Transcription(
        id=204,
        title="Modal tab strict source",
        selected_stem="other",
        audio_file_path="/tmp/transcriptions/204/original.mp3",
        preprocessed_audio_file_path="/tmp/transcriptions/204/preprocessed.wav",
        original_audio_url="https://res.cloudinary.com/demo/video/upload/original.mp3",
        separated_audio_url="https://res.cloudinary.com/demo/video/upload/selected-stem/other_nqdpu9.wav",
        separated_audio_file_path="/tmp/transcriptions/204/other.wav",
        source_url="https://example.test/original",
        modal_request_id="request-204",
    )

    payload = audio_endpoint._build_worker_payload_for_modal(
        transcription,
        job_type="generate_tab",
        detection_sensitivity="high",
    )

    assert payload["separated_audio_url"] == transcription.separated_audio_url
    assert payload["original_audio_url"] is None
    assert payload["source_url"] is None
    assert payload["detection_sensitivity"] == "high"


def test_modal_generate_lyrics_payload_includes_requested_language():
    transcription = models.Transcription(
        id=206,
        title="Modal lyrics language",
        selected_stem="vocals",
        separated_audio_url="https://res.cloudinary.com/demo/video/upload/vocals.wav",
        modal_request_id="request-206",
    )

    payload = audio_endpoint._build_worker_payload_for_modal(
        transcription,
        job_type="generate_lyrics",
        lyrics_language="ceb",
    )

    assert payload["separated_audio_url"] == transcription.separated_audio_url
    assert payload["original_audio_url"] is None
    assert payload["lyrics_language"] == "ceb"


def test_modal_generate_tab_payload_requires_separated_url_not_local_path():
    transcription = models.Transcription(
        id=205,
        title="Modal local-only tab source",
        selected_stem="bass",
        separated_audio_file_path="/tmp/transcriptions/205/bass.wav",
        original_audio_url="https://res.cloudinary.com/demo/video/upload/original.mp3",
    )

    with pytest.raises(ValueError, match="separated_audio_url is required for Modal tab generation."):
        audio_endpoint._build_worker_payload_for_modal(
            transcription,
            job_type="generate_tab",
        )


def test_generate_tab_endpoint_queues_drum_rhythm_generation():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "rhythm-owner", "rhythm-owner@example.com")
        transcription = models.Transcription(
            title="Rhythm from stem",
            user_id=owner.id,
            selected_stem="drums",
            separated_audio_file_path=str(Path("/tmp/drums.wav")),
            can_play_stem=True,
            processing_status="stem_ready",
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
    finally:
        session.close()

    with patch("app.api.v1.endpoints.audio._start_tab_generation", return_value="rhythm-task") as start_mock:
        response = client.post(
            f"/api/v1/audio/{transcription_id}/generate-tabs",
            headers=auth_headers("rhythm-owner"),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "stem_ready"
    assert payload["selected_stem"] == "drums"
    assert payload["can_generate_score"] is False
    assert payload["can_generate_tab"] is False
    assert payload["available_exports"] == []
    assert payload["tab_generation_status"] == "idle"
    assert payload["rhythm_generation_status"] == "processing"
    assert payload["message"] == "Rhythm generation started."
    assert start_mock.call_args.args[0] == transcription_id

    session = TestingSessionLocal()
    try:
        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).one()
        assert refreshed.processing_status == "stem_ready"
        assert refreshed.tab_generation_status == "idle"
        assert refreshed.rhythm_generation_status == "processing"
        assert refreshed.celery_task_id == "rhythm-task"
    finally:
        session.close()


def test_generate_lyrics_endpoint_uses_lyrics_status_without_processing_audio():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "lyrics-owner", "lyrics-owner@example.com")
        transcription = models.Transcription(
            title="Vocal stem",
            user_id=owner.id,
            selected_stem="vocals",
            separated_audio_url="https://res.cloudinary.com/demo/video/upload/vocals.wav",
            can_play_stem=True,
            processing_status="stem_ready",
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
    finally:
        session.close()

    with patch("app.api.v1.endpoints.audio._start_lyrics_generation", return_value="lyrics-task") as start_mock:
        response = client.post(
            f"/api/v1/audio/{transcription_id}/generate-lyrics",
            headers=auth_headers("lyrics-owner"),
            json={"language": "tl"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "stem_ready"
    assert payload["lyrics_generation_status"] == "processing"
    assert payload["tab_generation_status"] == "idle"
    assert payload["rhythm_generation_status"] == "idle"
    assert payload["lyrics_language"] == "tl"
    assert payload["message"] == "Lyrics generation started."
    assert start_mock.call_args.args[0] == transcription_id
    assert start_mock.call_args.kwargs["lyrics_language"] == "tl"

    session = TestingSessionLocal()
    try:
        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).one()
        assert refreshed.processing_status == "stem_ready"
        assert refreshed.lyrics_generation_status == "processing"
        assert refreshed.tab_generation_status == "idle"
        assert refreshed.rhythm_generation_status == "idle"
        assert refreshed.celery_task_id == "lyrics-task"
        assert refreshed.separated_audio_url.endswith("vocals.wav")
    finally:
        session.close()


def test_generate_lyrics_rejects_non_vocal_stem():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "lyrics-bass-owner", "lyrics-bass-owner@example.com")
        transcription = models.Transcription(
            title="Bass stem",
            user_id=owner.id,
            selected_stem="bass",
            separated_audio_url="https://res.cloudinary.com/demo/video/upload/bass.wav",
            can_play_stem=True,
            processing_status="stem_ready",
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
    finally:
        session.close()

    response = client.post(
        f"/api/v1/audio/{transcription_id}/generate-lyrics",
        headers=auth_headers("lyrics-bass-owner"),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Lyrics generation is only available for vocal stems."


@pytest.mark.parametrize("language", ["auto", "en", "tl", "ceb", "es", "ja", "ko"])
def test_generate_lyrics_endpoint_accepts_supported_languages(language):
    reset_database()
    session = TestingSessionLocal()
    try:
        username = f"lyrics-{language}-owner"
        owner = create_user(session, username, f"{username}@example.com")
        transcription = models.Transcription(
            title=f"Vocal stem {language}",
            user_id=owner.id,
            selected_stem="vocals",
            separated_audio_url="https://res.cloudinary.com/demo/video/upload/vocals.wav",
            can_play_stem=True,
            processing_status="stem_ready",
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
    finally:
        session.close()

    with patch("app.api.v1.endpoints.audio._start_lyrics_generation", return_value="lyrics-task") as start_mock:
        response = client.post(
            f"/api/v1/audio/{transcription_id}/generate-lyrics",
            headers=auth_headers(username),
            json={"language": language},
        )

    assert response.status_code == 200
    assert response.json()["lyrics_language"] == language
    assert start_mock.call_args.kwargs["lyrics_language"] == language


def test_generate_lyrics_endpoint_rejects_invalid_language():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "lyrics-invalid-owner", "lyrics-invalid@example.com")
        transcription = models.Transcription(
            title="Invalid language vocal",
            user_id=owner.id,
            selected_stem="vocals",
            separated_audio_url="https://res.cloudinary.com/demo/video/upload/vocals.wav",
            can_play_stem=True,
            processing_status="stem_ready",
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
    finally:
        session.close()

    response = client.post(
        f"/api/v1/audio/{transcription_id}/generate-lyrics",
        headers=auth_headers("lyrics-invalid-owner"),
        json={"language": "xx"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "lyrics language must be one of: auto, en, tl, ceb, es, ja, ko"


def test_transcribe_vocal_stem_auto_does_not_force_language(tmp_path, monkeypatch):
    stem_path = tmp_path / "auto-vocals.wav"
    stem_path.write_bytes(b"fake wav")

    class FakeWhisperModel:
        kwargs = None

        def transcribe(self, *_args, **kwargs):
            self.kwargs = kwargs
            return iter([]), SimpleNamespace(language="tl")

    fake_model = FakeWhisperModel()
    monkeypatch.setattr(lyrics, "get_whisper_model", lambda: fake_model)
    monkeypatch.setattr(
        lyrics,
        "resolve_whisper_runtime",
        lambda: {"model_size": "base", "device": "cpu", "compute_type": "int8"},
    )

    result = lyrics.transcribe_vocal_stem(stem_path, language="auto")

    assert fake_model.kwargs["language"] is None
    assert result["requested_language"] == "auto"
    assert result["language"] == "tl"


def test_transcribe_vocal_stem_cebuano_uses_auto_detection(tmp_path, monkeypatch):
    stem_path = tmp_path / "cebuano-vocals.wav"
    stem_path.write_bytes(b"fake wav")

    class FakeWhisperModel:
        kwargs = None

        def transcribe(self, *_args, **kwargs):
            self.kwargs = kwargs
            return iter([]), SimpleNamespace(language="tl")

    fake_model = FakeWhisperModel()
    monkeypatch.setattr(lyrics, "get_whisper_model", lambda: fake_model)
    monkeypatch.setattr(
        lyrics,
        "resolve_whisper_runtime",
        lambda: {"model_size": "base", "device": "cpu", "compute_type": "int8"},
    )

    result = lyrics.transcribe_vocal_stem(stem_path, language="ceb")

    assert fake_model.kwargs["language"] is None
    assert result["requested_language"] == "ceb"
    assert result["language"] == "tl"


def test_transcribe_vocal_stem_forces_supported_language(tmp_path, monkeypatch):
    stem_path = tmp_path / "tagalog-vocals.wav"
    stem_path.write_bytes(b"fake wav")

    class FakeSegment:
        start = 0
        end = 1.2
        text = "kumusta"

    class FakeWhisperModel:
        kwargs = None

        def transcribe(self, *_args, **kwargs):
            self.kwargs = kwargs
            return iter([FakeSegment()]), SimpleNamespace(language="tl")

    fake_model = FakeWhisperModel()
    monkeypatch.setattr(lyrics, "get_whisper_model", lambda: fake_model)
    monkeypatch.setattr(
        lyrics,
        "resolve_whisper_runtime",
        lambda: {"model_size": "base", "device": "cpu", "compute_type": "int8"},
    )

    result = lyrics.transcribe_vocal_stem(stem_path, language="tl")

    assert fake_model.kwargs["language"] == "tl"
    assert fake_model.kwargs["vad_filter"] is False
    assert fake_model.kwargs["beam_size"] == 8
    assert fake_model.kwargs["best_of"] == 5
    assert fake_model.kwargs["condition_on_previous_text"] is False
    assert result["requested_language"] == "tl"
    assert result["text"] == "kumusta"


def test_generate_lyrics_output_returns_after_saving_lyrics_result(tmp_path):
    reset_database()
    stem_path = tmp_path / "vocals.wav"
    stem_path.write_bytes(b"fake wav")
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "lyrics-direct-owner", "lyrics-direct@example.com")
        transcription = models.Transcription(
            title="Direct vocal lyrics",
            user_id=owner.id,
            selected_stem="vocals",
            separated_audio_file_path=str(stem_path),
            processing_status="stem_ready",
            lyrics_generation_status="processing",
            notes_data='{"notes": [{"pitch": 60}]}',
            tablature_data='{"tablature": [{"fret": 3}]}',
            midi_file_path="/tmp/original.mid",
            tab_file_path="/tmp/original.tab",
            can_play_stem=True,
            can_generate_score=False,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id

        lyrics_result = {
            "text": "hello there",
            "segments": [{"start": 0, "end": 1.2, "text": "hello there"}],
            "requested_language": "ceb",
            "language": "en",
            "model": "faster-whisper",
            "model_size": "base",
            "device": "cpu",
            "compute_type": "int8",
            "message": None,
        }
        with (
            patch("app.tasks.lyrics.resolve_whisper_runtime", return_value={
                "model_size": "base",
                "device": "cpu",
                "compute_type": "int8",
            }),
            patch("app.tasks.lyrics.transcribe_vocal_stem", return_value=lyrics_result) as transcribe_mock,
            patch("app.tasks.generate_single_track_transcription_output") as track_mock,
            patch("app.tasks.audio.detect_beat_and_tempo") as tempo_mock,
            patch("app.tasks.audio.detect_key") as key_mock,
            patch("app.tasks.audio.detect_rhythm") as rhythm_mock,
            patch("app.tasks.audio.detect_chords") as chords_mock,
        ):
            result = tasks.generate_lyrics_output_for_transcription(
                transcription,
                session,
                lyrics_language="ceb",
            )

        assert result is None
        transcribe_mock.assert_called_once_with(str(stem_path), language="ceb")
        track_mock.assert_not_called()
        tempo_mock.assert_not_called()
        key_mock.assert_not_called()
        rhythm_mock.assert_not_called()
        chords_mock.assert_not_called()

        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).one()
        assert refreshed.lyrics_generation_status == "completed"
        lyrics_payload = json.loads(refreshed.lyrics_data)
        assert lyrics_payload["text"] == "hello there"
        assert lyrics_payload["requested_language"] == "ceb"
        assert refreshed.processing_status == "stem_ready"
        assert refreshed.notes_data == '{"notes": [{"pitch": 60}]}'
        assert refreshed.tablature_data == '{"tablature": [{"fret": 3}]}'
        assert refreshed.midi_file_path == "/tmp/original.mid"
        assert refreshed.tab_file_path == "/tmp/original.tab"
        assert refreshed.can_play_stem is True
    finally:
        session.close()


def test_generate_lyrics_output_empty_text_completes_with_warning(tmp_path):
    reset_database()
    stem_path = tmp_path / "vocals.wav"
    stem_path.write_bytes(b"fake wav")
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "lyrics-warning-owner", "lyrics-warning@example.com")
        transcription = models.Transcription(
            title="Quiet vocal lyrics",
            user_id=owner.id,
            selected_stem="vocals",
            separated_audio_file_path=str(stem_path),
            processing_status="stem_ready",
            lyrics_generation_status="processing",
            can_play_stem=True,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id

        lyrics_result = {
            "text": "",
            "segments": [],
            "requested_language": "auto",
            "language": None,
            "model": "faster-whisper",
            "model_size": "base",
            "device": "cpu",
            "compute_type": "int8",
            "message": "No clear vocals detected for lyrics generation.",
        }
        with (
            patch("app.tasks.lyrics.resolve_whisper_runtime", return_value={
                "model_size": "base",
                "device": "cpu",
                "compute_type": "int8",
            }),
            patch("app.tasks.lyrics.transcribe_vocal_stem", return_value=lyrics_result),
            patch("app.tasks.generate_single_track_transcription_output") as track_mock,
        ):
            tasks.generate_lyrics_output_for_transcription(transcription, session)

        track_mock.assert_not_called()
        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).one()
        payload = json.loads(refreshed.lyrics_data)
        assert refreshed.lyrics_generation_status == "completed_with_warning"
        assert payload["message"] == "No clear vocals detected for lyrics generation."
        assert payload["requested_language"] == "auto"
        assert refreshed.processing_status == "stem_ready"
        assert refreshed.can_play_stem is True
    finally:
        session.close()


def test_worker_lyrics_failure_keeps_vocal_stem_playable_and_viewer_status():
    reset_database()
    original_token = config.settings.WORKER_API_TOKEN
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "lyrics-fail-owner", "lyrics-fail-owner@example.com")
        transcription = models.Transcription(
            title="Vocal failure",
            user_id=owner.id,
            selected_stem="vocals",
            separated_audio_url="https://res.cloudinary.com/demo/video/upload/vocals.wav",
            can_play_stem=True,
            processing_status="stem_ready",
            lyrics_generation_status="processing",
            modal_job_type="generate_lyrics",
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
        config.settings.WORKER_API_TOKEN = "test-worker-token"
    finally:
        session.close()

    try:
        response = client.post(
            f"/api/v1/worker/jobs/{transcription_id}/failed",
            headers={"Authorization": "Bearer test-worker-token"},
            json={"error": "internal stack detail"},
        )
    finally:
        config.settings.WORKER_API_TOKEN = original_token

    assert response.status_code == 200
    payload = response.json()
    assert payload["processing_status"] == "stem_ready"
    assert payload["lyrics_generation_status"] == "failed"
    assert payload["can_play_stem"] is True
    assert payload["separated_audio_url"].endswith("vocals.wav")

    status_response = client.get(
        f"/api/v1/audio/{transcription_id}/status",
        headers=auth_headers("lyrics-fail-owner"),
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "stem_ready"
    assert status_response.json()["lyrics_generation_status"] == "failed"


def test_worker_lyrics_complete_only_updates_lyrics_fields():
    reset_database()
    original_token = config.settings.WORKER_API_TOKEN
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "lyrics-complete-owner", "lyrics-complete@example.com")
        transcription = models.Transcription(
            title="Vocal complete",
            user_id=owner.id,
            selected_stem="vocals",
            separated_audio_url="https://res.cloudinary.com/demo/video/upload/vocals.wav",
            notes_data='{"notes": [{"pitch": 60}]}',
            tablature_data='{"tablature": [{"fret": 3}]}',
            midi_file_path="/tmp/original.mid",
            tab_file_path="/tmp/original.tab",
            can_play_stem=True,
            processing_status="stem_ready",
            lyrics_generation_status="processing",
            modal_job_type="generate_lyrics",
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
        config.settings.WORKER_API_TOKEN = "test-worker-token"
    finally:
        session.close()

    try:
        response = client.post(
            f"/api/v1/worker/jobs/{transcription_id}/complete",
            headers={"Authorization": "Bearer test-worker-token"},
            json={
                "lyrics_data": {
                    "text": "hello there",
                    "segments": [{"start": 0, "end": 1.2, "text": "hello there"}],
                    "requested_language": "tl",
                    "language": "en",
                    "model": "faster-whisper",
                }
            },
        )
    finally:
        config.settings.WORKER_API_TOKEN = original_token

    assert response.status_code == 200
    payload = response.json()
    assert payload["processing_status"] == "stem_ready"
    assert payload["lyrics_generation_status"] == "completed"
    lyrics_payload = json.loads(payload["lyrics_data"])
    assert lyrics_payload["text"] == "hello there"
    assert lyrics_payload["requested_language"] == "tl"
    assert payload["notes_data"] == '{"notes": [{"pitch": 60}]}'
    assert payload["tablature_data"] == '{"tablature": [{"fret": 3}]}'
    assert payload["midi_file_path"] == "/tmp/original.mid"
    assert payload["tab_file_path"] == "/tmp/original.tab"
    assert payload["separated_audio_url"].endswith("vocals.wav")


def test_worker_failed_saves_sanitized_error_without_internal_logs():
    reset_database()
    original_token = config.settings.WORKER_API_TOKEN
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "failed-owner", "failed-owner@example.com")
        transcription = models.Transcription(
            title="Failed job",
            user_id=owner.id,
            selected_stem="bass",
            original_audio_url="https://res.cloudinary.com/demo/video/upload/source.wav",
            is_processed=False,
            processing_status="processing",
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
        config.settings.WORKER_API_TOKEN = "test-worker-token"
    finally:
        session.close()

    try:
        response = client.post(
            f"/api/v1/worker/jobs/{transcription_id}/failed",
            headers={"Authorization": "Bearer test-worker-token"},
            json={
                "error": "Could not isolate the selected stem.",
                "internal_logs": "stack trace with modal internals and secrets",
            },
        )
    finally:
        config.settings.WORKER_API_TOKEN = original_token

    assert response.status_code == 200
    payload = response.json()
    assert payload["processing_status"] == "failed"
    assert payload["is_processed"] is False
    assert payload["processing_error"] == "Could not isolate the selected stem."
    assert "stack trace" not in payload["processing_error"]


def test_modal_failed_callback_accepts_missing_optional_fields():
    reset_database()
    original_token = config.settings.WORKER_API_TOKEN
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "modal-failed-owner", "modal-failed@example.com")
        transcription = models.Transcription(
            title="Modal failed callback",
            user_id=owner.id,
            selected_stem="other",
            original_audio_url="https://res.cloudinary.com/demo/video/upload/source.wav",
            is_processed=False,
            processing_status="processing",
            processing_error=None,
            queue_position=0,
            estimated_wait_time=0,
            celery_task_id="modal-job",
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
        config.settings.WORKER_API_TOKEN = "test-worker-token"
    finally:
        session.close()

    try:
        response = client.post(
            f"/api/v1/worker/jobs/{transcription_id}/failed",
            headers={"Authorization": "Bearer test-worker-token"},
            json={},
        )
    finally:
        config.settings.WORKER_API_TOKEN = original_token

    assert response.status_code == 200
    payload = response.json()
    assert payload["processing_status"] == "failed"
    assert payload["is_processed"] is False
    assert payload["processing_error"] == "Worker processing failed."
    assert payload["queue_position"] is None
    assert payload["estimated_wait_time"] is None
    assert payload["celery_task_id"] is None

    session = TestingSessionLocal()
    try:
        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).one()
        assert refreshed.processing_status == "failed"
        assert refreshed.processing_error == "Worker processing failed."
    finally:
        session.close()


def test_modal_failed_callback_truncates_long_worker_error():
    reset_database()
    original_token = config.settings.WORKER_API_TOKEN
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "modal-long-error-owner", "modal-long-error@example.com")
        transcription = models.Transcription(
            title="Modal long error callback",
            user_id=owner.id,
            selected_stem="bass",
            original_audio_url="https://res.cloudinary.com/demo/video/upload/source.wav",
            is_processed=False,
            processing_status="processing",
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
        config.settings.WORKER_API_TOKEN = "test-worker-token"
    finally:
        session.close()

    try:
        response = client.post(
            f"/api/v1/worker/jobs/{transcription_id}/failed",
            headers={"X-Worker-Token": "test-worker-token"},
            json={
                "error": "Demucs failed " + ("because the selected stem was absent " * 40),
                "internal_logs": {"stderr": "full demucs traceback"},
            },
        )
    finally:
        config.settings.WORKER_API_TOKEN = original_token

    assert response.status_code == 200
    payload = response.json()
    assert payload["processing_status"] == "failed"
    assert payload["processing_error"].startswith("Demucs failed")
    assert len(payload["processing_error"]) == 500
    assert "full demucs traceback" not in payload["processing_error"]


def test_extract_audio_from_youtube_requires_selected_stem():
    reset_database()
    session = TestingSessionLocal()
    try:
        create_user(session, "youtube-owner", "youtube-owner@example.com")
    finally:
        session.close()

    response = client.post(
        "/api/v1/audio/youtube",
        headers=auth_headers("youtube-owner"),
        json={"youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    )

    assert response.status_code == 422


def test_extract_audio_from_youtube_returns_service_unavailable_for_verification_challenge():
    reset_database()
    original_cookies_file = config.settings.YOUTUBE_COOKIES_FILE
    original_cookies = config.settings.YOUTUBE_COOKIES
    config.settings.YOUTUBE_COOKIES_FILE = None
    config.settings.YOUTUBE_COOKIES = None
    session = TestingSessionLocal()
    try:
        create_user(session, "youtube-bot-check", "youtube-bot-check@example.com")
    finally:
        session.close()

    class RaisingYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def extract_info(self, url, download):
            raise RuntimeError("Sign in to confirm you're not a bot. Use --cookies for authentication.")

    try:
        with patch("app.api.v1.endpoints.audio.yt_dlp.YoutubeDL", RaisingYoutubeDL):
            response = client.post(
                "/api/v1/audio/youtube",
                headers=auth_headers("youtube-bot-check"),
                json={
                    "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "selected_stem": "other",
                },
            )
    finally:
        config.settings.YOUTUBE_COOKIES_FILE = original_cookies_file
        config.settings.YOUTUBE_COOKIES = original_cookies

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "YouTube rejected this request. Please upload the audio directly or refresh cookies/PO token."
    )


def test_extract_audio_from_youtube_rejects_missing_cookie_file_before_ytdlp(tmp_path):
    reset_database()
    original_cookies_file = config.settings.YOUTUBE_COOKIES_FILE
    original_cookies = config.settings.YOUTUBE_COOKIES
    config.settings.YOUTUBE_COOKIES_FILE = str(tmp_path / "missing.cookies.txt")
    config.settings.YOUTUBE_COOKIES = None
    session = TestingSessionLocal()
    try:
        create_user(session, "youtube-missing-cookies", "youtube-missing-cookies@example.com")
    finally:
        session.close()

    try:
        with patch("app.api.v1.endpoints.audio.yt_dlp.YoutubeDL") as youtube_dl:
            response = client.post(
                "/api/v1/audio/youtube",
                headers=auth_headers("youtube-missing-cookies"),
                json={
                    "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "selected_stem": "other",
                },
            )
    finally:
        config.settings.YOUTUBE_COOKIES_FILE = original_cookies_file
        config.settings.YOUTUBE_COOKIES = original_cookies

    assert response.status_code == 503
    assert "missing or invalid" in response.json()["detail"]
    youtube_dl.assert_not_called()


def test_extract_audio_from_youtube_rejects_placeholder_cookie_file_before_ytdlp(tmp_path):
    reset_database()
    original_cookies_file = config.settings.YOUTUBE_COOKIES_FILE
    original_cookies = config.settings.YOUTUBE_COOKIES
    cookie_file = tmp_path / "youtube.cookies.txt"
    cookie_file.write_text("# Place your YouTube browser cookies here.\n", encoding="utf-8")
    config.settings.YOUTUBE_COOKIES_FILE = str(cookie_file)
    config.settings.YOUTUBE_COOKIES = None
    session = TestingSessionLocal()
    try:
        create_user(session, "youtube-placeholder-cookies", "youtube-placeholder-cookies@example.com")
    finally:
        session.close()

    try:
        with patch("app.api.v1.endpoints.audio.yt_dlp.YoutubeDL") as youtube_dl:
            response = client.post(
                "/api/v1/audio/youtube",
                headers=auth_headers("youtube-placeholder-cookies"),
                json={
                    "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "selected_stem": "other",
                },
            )
    finally:
        config.settings.YOUTUBE_COOKIES_FILE = original_cookies_file
        config.settings.YOUTUBE_COOKIES = original_cookies

    assert response.status_code == 503
    assert "missing or invalid" in response.json()["detail"]
    youtube_dl.assert_not_called()


def test_youtube_raw_cookies_with_escaped_newlines_are_normalized():
    from app.api.v1.endpoints.audio import _get_youtube_cookiefile

    original_cookies_file = config.settings.YOUTUBE_COOKIES_FILE
    original_cookies = config.settings.YOUTUBE_COOKIES
    config.settings.YOUTUBE_COOKIES_FILE = None
    config.settings.YOUTUBE_COOKIES = (
        "# Netscape HTTP Cookie File\\n"
        ".youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tfresh-cookie\\n"
    )

    cookiefile = None
    try:
        resolved = _get_youtube_cookiefile()
        cookiefile = Path(resolved.path)

        assert resolved.loaded is True
        assert resolved.cleanup is True
        assert resolved.cookie_count == 1
        assert "\n.youtube.com" in cookiefile.read_text(encoding="utf-8")
    finally:
        if cookiefile and cookiefile.exists():
            cookiefile.unlink()
        config.settings.YOUTUBE_COOKIES_FILE = original_cookies_file
        config.settings.YOUTUBE_COOKIES = original_cookies


def test_youtube_env_cookies_win_and_ignore_placeholder_file(tmp_path, caplog):
    from app.api.v1.endpoints.audio import _get_youtube_cookiefile

    original_cookies_file = config.settings.YOUTUBE_COOKIES_FILE
    original_cookies = config.settings.YOUTUBE_COOKIES
    cookie_file = tmp_path / "youtube.cookies.txt"
    cookie_file.write_text("# Place your YouTube browser cookies here.\n", encoding="utf-8")
    raw_secret_cookie = "fresh-secret-cookie"
    config.settings.YOUTUBE_COOKIES_FILE = str(cookie_file)
    config.settings.YOUTUBE_COOKIES = (
        "# Netscape HTTP Cookie File\n"
        f".youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\t{raw_secret_cookie}\n"
    )
    caplog.set_level("INFO", logger="app.api.v1.endpoints.audio")

    cookiefile = None
    try:
        resolved = _get_youtube_cookiefile()
        cookiefile = Path(resolved.path)

        assert resolved.loaded is True
        assert resolved.cleanup is True
        assert resolved.source == "YOUTUBE_COOKIES"
        assert cookiefile.exists()
        assert "Using YOUTUBE_COOKIES from environment; ignoring YOUTUBE_COOKIES_FILE." in caplog.text
        assert "effective cookie source=env" in caplog.text
        assert "has_youtube_domain=True" in caplog.text
        assert "cookie fingerprint=" in caplog.text
        assert raw_secret_cookie not in caplog.text
    finally:
        if cookiefile and cookiefile.exists():
            cookiefile.unlink()
        config.settings.YOUTUBE_COOKIES_FILE = original_cookies_file
        config.settings.YOUTUBE_COOKIES = original_cookies


def test_youtube_cookie_diagnostics_warn_for_low_count_and_do_not_log_raw_values(caplog):
    from app.api.v1.endpoints.audio import _get_youtube_cookiefile

    original_cookies_file = config.settings.YOUTUBE_COOKIES_FILE
    original_cookies = config.settings.YOUTUBE_COOKIES
    raw_secret_cookie = "raw-cookie-value-that-must-not-appear"
    cookie_payload = (
        "# Netscape HTTP Cookie File\n"
        f".youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\t{raw_secret_cookie}\n"
    )
    expected_fingerprint = hashlib.sha256(cookie_payload.encode("utf-8")).hexdigest()[:8]
    config.settings.YOUTUBE_COOKIES_FILE = None
    config.settings.YOUTUBE_COOKIES = cookie_payload
    caplog.set_level("INFO", logger="app.api.v1.endpoints.audio")

    cookiefile = None
    try:
        resolved = _get_youtube_cookiefile()
        cookiefile = Path(resolved.path)

        assert resolved.cookie_count == 1
        assert f"cookie fingerprint={expected_fingerprint}" in caplog.text
        assert "cookie_count=1" in caplog.text
        assert "has_youtube_domain=True" in caplog.text
        assert "SID': True" in caplog.text
        assert "YouTube cookie count appears low; cookies may be incomplete or expired." in caplog.text
        assert raw_secret_cookie not in caplog.text
        assert cookie_payload not in caplog.text
    finally:
        if cookiefile and cookiefile.exists():
            cookiefile.unlink()
        config.settings.YOUTUBE_COOKIES_FILE = original_cookies_file
        config.settings.YOUTUBE_COOKIES = original_cookies


def test_extract_audio_from_youtube_rejects_malformed_env_cookies_before_ytdlp():
    reset_database()
    original_cookies_file = config.settings.YOUTUBE_COOKIES_FILE
    original_cookies = config.settings.YOUTUBE_COOKIES
    config.settings.YOUTUBE_COOKIES_FILE = None
    config.settings.YOUTUBE_COOKIES = "not netscape cookies"
    session = TestingSessionLocal()
    try:
        create_user(session, "youtube-bad-env-cookies", "youtube-bad-env-cookies@example.com")
    finally:
        session.close()

    try:
        with patch("app.api.v1.endpoints.audio.yt_dlp.YoutubeDL") as youtube_dl:
            response = client.post(
                "/api/v1/audio/youtube",
                headers=auth_headers("youtube-bad-env-cookies"),
                json={
                    "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "selected_stem": "other",
                },
            )
    finally:
        config.settings.YOUTUBE_COOKIES_FILE = original_cookies_file
        config.settings.YOUTUBE_COOKIES = original_cookies

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "YOUTUBE_COOKIES is configured but is not valid Netscape cookie format."
    )
    youtube_dl.assert_not_called()


def test_get_youtube_cookiefile_accepts_base64_env_cookies(tmp_path):
    from app.api.v1.endpoints.audio import _get_youtube_cookiefile

    original_cookies_file = config.settings.YOUTUBE_COOKIES_FILE
    original_cookies = config.settings.YOUTUBE_COOKIES
    original_cookies_b64 = config.settings.YOUTUBE_COOKIES_B64
    config.settings.YOUTUBE_COOKIES_FILE = None
    config.settings.YOUTUBE_COOKIES = None
    cookie_payload = (
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tfresh-cookie\n"
    )
    import base64

    config.settings.YOUTUBE_COOKIES_B64 = base64.b64encode(
        cookie_payload.encode("utf-8")
    ).decode("ascii")
    cookiefile = None

    try:
        resolved = _get_youtube_cookiefile()
        cookiefile = Path(resolved.path)

        assert resolved.source == "YOUTUBE_COOKIES_B64"
        assert resolved.loaded is True
        assert resolved.cookie_count == 1
        assert cookiefile.read_text(encoding="utf-8") == cookie_payload
    finally:
        if cookiefile and cookiefile.exists():
            cookiefile.unlink()
        config.settings.YOUTUBE_COOKIES_FILE = original_cookies_file
        config.settings.YOUTUBE_COOKIES = original_cookies
        config.settings.YOUTUBE_COOKIES_B64 = original_cookies_b64


def test_extract_audio_from_youtube_rejects_env_cookies_without_youtube_domain_before_ytdlp():
    reset_database()
    original_cookies_file = config.settings.YOUTUBE_COOKIES_FILE
    original_cookies = config.settings.YOUTUBE_COOKIES
    config.settings.YOUTUBE_COOKIES_FILE = None
    config.settings.YOUTUBE_COOKIES = (
        "# Netscape HTTP Cookie File\n"
        ".google.com\tTRUE\t/\tTRUE\t2147483647\tSID\tgoogle-cookie\n"
    )
    session = TestingSessionLocal()
    try:
        create_user(session, "youtube-no-domain-cookies", "youtube-no-domain-cookies@example.com")
    finally:
        session.close()

    try:
        with patch("app.api.v1.endpoints.audio.yt_dlp.YoutubeDL") as youtube_dl:
            response = client.post(
                "/api/v1/audio/youtube",
                headers=auth_headers("youtube-no-domain-cookies"),
                json={
                    "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "selected_stem": "other",
                },
            )
    finally:
        config.settings.YOUTUBE_COOKIES_FILE = original_cookies_file
        config.settings.YOUTUBE_COOKIES = original_cookies

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "YOUTUBE_COOKIES is configured but does not contain YouTube cookies."
    )
    youtube_dl.assert_not_called()


def test_extract_audio_from_youtube_retries_without_cookies_then_returns_rejected_detail(caplog):
    reset_database()
    original_cookies_file = config.settings.YOUTUBE_COOKIES_FILE
    original_cookies = config.settings.YOUTUBE_COOKIES
    original_po_token = config.settings.YOUTUBE_PO_TOKEN
    raw_secret_cookie = "fresh-cookie-that-must-not-log"
    raw_po_token = "po-token-that-must-not-log"
    config.settings.YOUTUBE_COOKIES_FILE = None
    config.settings.YOUTUBE_COOKIES = (
        "# Netscape HTTP Cookie File\n"
        f".youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\t{raw_secret_cookie}\n"
    )
    config.settings.YOUTUBE_PO_TOKEN = raw_po_token
    caplog.set_level("INFO", logger="app.api.v1.endpoints.audio")
    session = TestingSessionLocal()
    try:
        create_user(session, "youtube-rejected-cookies", "youtube-rejected-cookies@example.com")
    finally:
        session.close()

    calls = []

    class RaisingYoutubeDL:
        def __init__(self, options):
            self.options = options
            calls.append(options.copy())

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def extract_info(self, url, download):
            raise RuntimeError("Sign in to confirm you're not a bot. Use --cookies for authentication.")

    try:
        with patch("app.api.v1.endpoints.audio.yt_dlp.YoutubeDL", RaisingYoutubeDL):
            response = client.post(
                "/api/v1/audio/youtube",
                headers=auth_headers("youtube-rejected-cookies"),
                json={
                    "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "selected_stem": "other",
                },
            )
    finally:
        config.settings.YOUTUBE_COOKIES_FILE = original_cookies_file
        config.settings.YOUTUBE_COOKIES = original_cookies
        config.settings.YOUTUBE_PO_TOKEN = original_po_token

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "YouTube rejected this request. Please upload the audio directly or refresh cookies/PO token."
    )
    assert len(calls) == 2
    assert "cookiefile" in calls[0]
    assert "cookiefile" not in calls[1]
    assert [call["format"] for call in calls] == ["bestaudio/best", "bestaudio/best"]
    assert "cookies_loaded=True" in caplog.text
    assert "cookies_loaded=False" in caplog.text
    assert "po_token_configured=True" in caplog.text
    assert "yt_dlp_version=" in caplog.text
    assert "retry_without_cookies=True" in caplog.text
    assert raw_secret_cookie not in caplog.text
    assert raw_po_token not in caplog.text


def test_extract_audio_from_youtube_cookie_rejection_retry_can_succeed():
    reset_database()
    original_cookies_file = config.settings.YOUTUBE_COOKIES_FILE
    original_cookies = config.settings.YOUTUBE_COOKIES
    config.settings.YOUTUBE_COOKIES_FILE = None
    config.settings.YOUTUBE_COOKIES = (
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tfresh-cookie\n"
    )
    session = TestingSessionLocal()
    try:
        create_user(session, "youtube-retry-success", "youtube-retry-success@example.com")
    finally:
        session.close()

    calls = []

    class RetryYoutubeDL:
        def __init__(self, options):
            self.options = options
            calls.append(options.copy())

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def extract_info(self, url, download):
            if "cookiefile" in self.options:
                raise RuntimeError("Sign in to confirm you're not a bot. Use --cookies for authentication.")
            outtmpl = self.options["outtmpl"]["default"]
            output_name = outtmpl.replace("%(ext)s", "wav")
            output_path = Path(self.options["paths"]["home"]) / output_name
            output_path.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")
            return {"title": "Retry worked"}

    try:
        with (
            patch("app.api.v1.endpoints.audio.yt_dlp.YoutubeDL", RetryYoutubeDL),
            patch("app.api.v1.endpoints.audio._start_transcription_processing", return_value=None),
        ):
            response = client.post(
                "/api/v1/audio/youtube",
                headers=auth_headers("youtube-retry-success"),
                json={
                    "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "selected_stem": "other",
                },
            )
    finally:
        config.settings.YOUTUBE_COOKIES_FILE = original_cookies_file
        config.settings.YOUTUBE_COOKIES = original_cookies

    assert response.status_code == 200
    assert response.json()["title"] == "Retry worked"
    assert len(calls) == 2
    assert "cookiefile" in calls[0]
    assert "cookiefile" not in calls[1]
    assert [call["format"] for call in calls] == ["bestaudio/best", "bestaudio/best"]


def test_extract_audio_from_youtube_does_not_retry_cookie_attempt_for_unrelated_error():
    reset_database()
    original_cookies_file = config.settings.YOUTUBE_COOKIES_FILE
    original_cookies = config.settings.YOUTUBE_COOKIES
    config.settings.YOUTUBE_COOKIES_FILE = None
    config.settings.YOUTUBE_COOKIES = (
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tfresh-cookie\n"
    )
    session = TestingSessionLocal()
    try:
        create_user(session, "youtube-no-retry", "youtube-no-retry@example.com")
    finally:
        session.close()

    calls = []

    class RaisingYoutubeDL:
        def __init__(self, options):
            self.options = options
            calls.append(options.copy())

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def extract_info(self, url, download):
            raise RuntimeError("Temporary filesystem failure")

    try:
        with patch("app.api.v1.endpoints.audio.yt_dlp.YoutubeDL", RaisingYoutubeDL):
            response = client.post(
                "/api/v1/audio/youtube",
                headers=auth_headers("youtube-no-retry"),
                json={
                    "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "selected_stem": "other",
                },
            )
    finally:
        config.settings.YOUTUBE_COOKIES_FILE = original_cookies_file
        config.settings.YOUTUBE_COOKIES = original_cookies

    assert response.status_code == 500
    assert len(calls) == 1
    assert "cookiefile" in calls[0]
    assert calls[0]["format"] == "bestaudio/best"


def test_youtube_download_options_include_cookiefile_when_configured():
    from app.api.v1.endpoints.audio import _build_youtube_download_options

    options = _build_youtube_download_options(
        unique_filename="song",
        ffmpeg_path="/usr/bin",
        cookiefile="/app/secrets/youtube.cookies.txt",
    )

    assert options["cookiefile"] == "/app/secrets/youtube.cookies.txt"


def test_youtube_download_options_use_default_format_without_extractor_args():
    from app.api.v1.endpoints.audio import _build_youtube_download_options

    original_po_token = config.settings.YOUTUBE_PO_TOKEN
    original_player_client = config.settings.YOUTUBE_PLAYER_CLIENT
    original_visitor_data = config.settings.YOUTUBE_VISITOR_DATA
    config.settings.YOUTUBE_PO_TOKEN = None
    config.settings.YOUTUBE_PLAYER_CLIENT = None
    config.settings.YOUTUBE_VISITOR_DATA = None

    try:
        options = _build_youtube_download_options(
            unique_filename="song",
            ffmpeg_path="/usr/bin",
        )
    finally:
        config.settings.YOUTUBE_PO_TOKEN = original_po_token
        config.settings.YOUTUBE_PLAYER_CLIENT = original_player_client
        config.settings.YOUTUBE_VISITOR_DATA = original_visitor_data

    assert options["format"] == "bestaudio/best"
    assert options["noplaylist"] is True
    assert options["quiet"] is True
    assert options["no_warnings"] is True
    assert "extractor_args" not in options


def test_extract_audio_from_youtube_does_not_retry_format_selection():
    reset_database()
    session = TestingSessionLocal()
    try:
        create_user(session, "youtube-format-no-retry", "youtube-format-no-retry@example.com")
    finally:
        session.close()

    calls = []

    class FormatFailYoutubeDL:
        def __init__(self, options):
            self.options = options
            calls.append(options.copy())

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def extract_info(self, url, download):
            raise RuntimeError("Requested format is not available")

    with patch("app.api.v1.endpoints.audio.yt_dlp.YoutubeDL", FormatFailYoutubeDL):
        response = client.post(
            "/api/v1/audio/youtube",
            headers=auth_headers("youtube-format-no-retry"),
            json={
                "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "selected_stem": "other",
            },
        )

    assert response.status_code == 500
    assert len(calls) == 1
    assert calls[0]["format"] == "bestaudio/best"


def test_extract_audio_from_youtube_logs_youtube_debug_options(caplog):
    reset_database()
    caplog.set_level("WARNING", logger="app.api.v1.endpoints.audio")
    session = TestingSessionLocal()
    try:
        create_user(session, "youtube-format-fail", "youtube-format-fail@example.com")
    finally:
        session.close()

    calls = []

    class FormatFailYoutubeDL:
        def __init__(self, options):
            self.options = options
            calls.append(options.copy())

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def extract_info(self, url, download):
            raise RuntimeError("Requested format is not available")

    with patch("app.api.v1.endpoints.audio.yt_dlp.YoutubeDL", FormatFailYoutubeDL):
        response = client.post(
            "/api/v1/audio/youtube",
            headers=auth_headers("youtube-format-fail"),
            json={
                "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "selected_stem": "other",
            },
        )

    assert response.status_code == 500
    assert len(calls) == 1
    assert calls[0]["format"] == "bestaudio/best"
    assert "youtube_debug format=bestaudio/best" in caplog.text
    assert "extractor_args_enabled=False" in caplog.text
    assert "postprocessors_enabled=True" in caplog.text
    assert "yt_dlp_format_retry" not in caplog.text


def test_youtube_download_options_include_po_token_extractor_args():
    from app.api.v1.endpoints.audio import _build_youtube_download_options

    original_po_token = config.settings.YOUTUBE_PO_TOKEN
    original_visitor_data = config.settings.YOUTUBE_VISITOR_DATA
    original_player_client = config.settings.YOUTUBE_PLAYER_CLIENT
    config.settings.YOUTUBE_PO_TOKEN = "token-one"
    config.settings.YOUTUBE_VISITOR_DATA = "visitor-data"
    config.settings.YOUTUBE_PLAYER_CLIENT = "mweb"

    try:
        options = _build_youtube_download_options(
            unique_filename="song",
            ffmpeg_path="/usr/bin",
        )
    finally:
        config.settings.YOUTUBE_PO_TOKEN = original_po_token
        config.settings.YOUTUBE_VISITOR_DATA = original_visitor_data
        config.settings.YOUTUBE_PLAYER_CLIENT = original_player_client

    assert options["extractor_args"] == {
        "youtube": {
            "po_token": ["token-one"],
            "visitor_data": ["visitor-data"],
            "player_client": ["mweb"],
        }
    }


def test_youtube_download_options_include_player_client_without_po_token():
    from app.api.v1.endpoints.audio import _build_youtube_download_options

    original_po_token = config.settings.YOUTUBE_PO_TOKEN
    original_player_client = config.settings.YOUTUBE_PLAYER_CLIENT
    config.settings.YOUTUBE_PO_TOKEN = None
    config.settings.YOUTUBE_PLAYER_CLIENT = "mweb"

    try:
        options = _build_youtube_download_options(
            unique_filename="song",
            ffmpeg_path="/usr/bin",
        )
    finally:
        config.settings.YOUTUBE_PO_TOKEN = original_po_token
        config.settings.YOUTUBE_PLAYER_CLIENT = original_player_client

    assert options["extractor_args"] == {
        "youtube": {
            "player_client": ["mweb"],
        }
    }


def test_youtube_download_options_preserve_scoped_po_token():
    from app.api.v1.endpoints.audio import _build_youtube_download_options

    original_po_token = config.settings.YOUTUBE_PO_TOKEN
    original_player_client = config.settings.YOUTUBE_PLAYER_CLIENT
    config.settings.YOUTUBE_PO_TOKEN = "web.gvs+token-one"
    config.settings.YOUTUBE_PLAYER_CLIENT = "mweb"

    try:
        options = _build_youtube_download_options(
            unique_filename="song",
            ffmpeg_path="/usr/bin",
        )
    finally:
        config.settings.YOUTUBE_PO_TOKEN = original_po_token
        config.settings.YOUTUBE_PLAYER_CLIENT = original_player_client

    assert options["extractor_args"]["youtube"]["po_token"] == ["web.gvs+token-one"]
    assert options["extractor_args"]["youtube"]["player_client"] == ["mweb"]


def test_list_instrument_tracks_requires_transcription_access():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "track-owner", "track-owner@example.com")
        other_user = create_user(session, "track-other", "track-other@example.com")
        transcription = models.Transcription(
            title="Owner song",
            audio_file_path="uploads/owner.wav",
            user_id=owner.id,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
    finally:
        session.close()

    response = client.get(
        f"/api/v1/audio/{transcription_id}/tracks",
        headers=auth_headers("track-other"),
    )

    assert response.status_code == 403


def test_list_and_get_instrument_tracks_for_owner():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "tracks-owner", "tracks-owner@example.com")
        transcription = models.Transcription(
            title="Multi-track song",
            audio_file_path="uploads/multitrack.wav",
            user_id=owner.id,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        guitar_track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="guitar",
            display_name="Guitar",
            stem_audio_path="uploads/stems/guitar.wav",
            tab_json='{"strings": []}',
            confidence_score=82,
            processing_status="completed",
        )
        bass_track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="bass",
            display_name="Bass",
            confidence_score=74,
            processing_status="completed",
        )
        session.add_all([guitar_track, bass_track])
        session.commit()
        transcription_id = transcription.id
        guitar_track_id = guitar_track.id
    finally:
        session.close()

    list_response = client.get(
        f"/api/v1/audio/{transcription_id}/tracks",
        headers=auth_headers("tracks-owner"),
    )

    assert list_response.status_code == 200
    payload = list_response.json()
    assert [track["instrument_type"] for track in payload] == ["guitar", "bass"]
    assert payload[0]["confidence_score"] == 82

    get_response = client.get(
        f"/api/v1/audio/{transcription_id}/tracks/{guitar_track_id}",
        headers=auth_headers("tracks-owner"),
    )

    assert get_response.status_code == 200
    track_payload = get_response.json()
    assert track_payload["display_name"] == "Guitar"
    assert track_payload["tab_json"] == '{"strings": []}'


def test_delete_transcription_cancels_queued_job_and_hides_record(tmp_path):
    reset_database()
    local_audio = tmp_path / "source.wav"
    local_audio.write_bytes(b"audio")
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "delete-owner", "delete-owner@example.com")
        transcription = models.Transcription(
            title="Queued song",
            audio_file_path=str(local_audio),
            original_audio_public_id="musicstudio/original",
            separated_audio_public_id="musicstudio/stem",
            midi_file_public_id="musicstudio/midi",
            tab_file_public_id="musicstudio/tab",
            celery_task_id="task-123",
            user_id=owner.id,
            is_processed=False,
            processing_status="queued",
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
    finally:
        session.close()

    with (
        patch("app.api.v1.endpoints.audio.celery_app.control.revoke") as revoke_mock,
        patch("app.api.v1.endpoints.audio.storage.delete_cloudinary_asset", return_value=True) as delete_mock,
    ):
        response = client.delete(
            f"/api/v1/transcriptions/{transcription_id}",
            headers=auth_headers("delete-owner"),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["is_deleted"] is True
    assert payload["processing_status"] == "cancelled"
    revoke_mock.assert_called_once_with("task-123", terminate=False)
    assert delete_mock.call_count == 4
    delete_mock.assert_any_call("musicstudio/original", resource_type="video")
    delete_mock.assert_any_call("musicstudio/stem", resource_type="video")
    delete_mock.assert_any_call("musicstudio/midi", resource_type="raw")
    delete_mock.assert_any_call("musicstudio/tab", resource_type="raw")
    assert not local_audio.exists()

    list_response = client.get("/api/v1/audio/", headers=auth_headers("delete-owner"))
    assert list_response.status_code == 200
    assert list_response.json() == []


def test_delete_transcription_skips_cloudinary_asset_still_referenced_elsewhere():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "shared-delete-owner", "shared-delete@example.com")
        deleting = models.Transcription(
            title="Shared source",
            original_audio_public_id="musicstudio/shared-original",
            separated_audio_public_id="musicstudio/delete-stem",
            user_id=owner.id,
            is_processed=True,
            processing_status="completed",
        )
        keeper = models.Transcription(
            title="Keep source",
            original_audio_public_id="musicstudio/shared-original",
            user_id=owner.id,
            is_processed=True,
            processing_status="completed",
        )
        session.add_all([deleting, keeper])
        session.commit()
        deleting_id = deleting.id
    finally:
        session.close()

    with patch(
        "app.api.v1.endpoints.audio.storage.delete_cloudinary_asset",
        return_value=True,
    ) as delete_mock:
        response = client.delete(
            f"/api/v1/transcriptions/{deleting_id}",
            headers=auth_headers("shared-delete-owner"),
        )

    assert response.status_code == 200
    deleted_public_ids = [call.args[0] for call in delete_mock.call_args_list]
    assert "musicstudio/shared-original" not in deleted_public_ids
    assert "musicstudio/delete-stem" in deleted_public_ids


def test_delete_transcription_with_missing_assets_does_not_crash():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "missing-delete-owner", "missing-delete@example.com")
        transcription = models.Transcription(
            title="No cloud assets",
            user_id=owner.id,
            is_processed=True,
            processing_status="completed",
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
    finally:
        session.close()

    with patch(
        "app.api.v1.endpoints.audio.storage.delete_cloudinary_asset",
        return_value=False,
    ) as delete_mock:
        response = client.delete(
            f"/api/v1/transcriptions/{transcription_id}",
            headers=auth_headers("missing-delete-owner"),
        )

    assert response.status_code == 200
    assert response.json()["is_deleted"] is True
    assert delete_mock.call_count == 4


def test_delete_project_removes_transcriptions_and_cloudinary_assets():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "project-delete-owner", "project-delete@example.com")
        project = models.Project(
            name="Delete me",
            owner_id=owner.id,
        )
        session.add(project)
        session.commit()
        session.refresh(project)
        transcription = models.Transcription(
            title="Project song",
            project_id=project.id,
            user_id=owner.id,
            original_audio_public_id="musicstudio/project-original",
            separated_audio_public_id="musicstudio/project-stem",
            midi_file_public_id="musicstudio/project-midi",
            tab_file_public_id="musicstudio/project-tab",
            is_processed=True,
            processing_status="completed",
        )
        session.add(transcription)
        session.commit()
        project_id = project.id
        transcription_id = transcription.id
    finally:
        session.close()

    with patch(
        "app.api.v1.endpoints.audio.storage.delete_cloudinary_asset",
        return_value=True,
    ) as delete_mock:
        response = client.delete(
            f"/api/v1/projects/{project_id}",
            headers=auth_headers("project-delete-owner"),
        )

    assert response.status_code == 200
    delete_mock.assert_any_call("musicstudio/project-original", resource_type="video")
    delete_mock.assert_any_call("musicstudio/project-stem", resource_type="video")
    delete_mock.assert_any_call("musicstudio/project-midi", resource_type="raw")
    delete_mock.assert_any_call("musicstudio/project-tab", resource_type="raw")

    session = TestingSessionLocal()
    try:
        assert session.query(models.Project).filter(models.Project.id == project_id).first() is None
        assert (
            session.query(models.Transcription)
            .filter(models.Transcription.id == transcription_id)
            .first()
            is None
        )
    finally:
        session.close()


def test_delete_project_keeps_duplicate_cloudinary_assets_referenced_elsewhere():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "project-shared-owner", "project-shared@example.com")
        project = models.Project(name="Shared delete", owner_id=owner.id)
        session.add(project)
        session.commit()
        session.refresh(project)
        deleting = models.Transcription(
            title="Project duplicate",
            project_id=project.id,
            user_id=owner.id,
            original_audio_public_id="musicstudio/shared-project-original",
            separated_audio_public_id="musicstudio/project-only-stem",
            is_processed=True,
            processing_status="completed",
        )
        keeper = models.Transcription(
            title="Outside duplicate",
            user_id=owner.id,
            original_audio_public_id="musicstudio/shared-project-original",
            is_processed=True,
            processing_status="completed",
        )
        session.add_all([deleting, keeper])
        session.commit()
        project_id = project.id
    finally:
        session.close()

    with patch(
        "app.api.v1.endpoints.audio.storage.delete_cloudinary_asset",
        return_value=True,
    ) as delete_mock:
        response = client.delete(
            f"/api/v1/projects/{project_id}",
            headers=auth_headers("project-shared-owner"),
        )

    assert response.status_code == 200
    deleted_public_ids = [call.args[0] for call in delete_mock.call_args_list]
    assert "musicstudio/shared-project-original" not in deleted_public_ids
    assert "musicstudio/project-only-stem" in deleted_public_ids


def test_soft_delete_project_marks_records_after_cloudinary_cleanup():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "project-soft-owner", "project-soft@example.com")
        project = models.Project(name="Soft delete", owner_id=owner.id)
        session.add(project)
        session.commit()
        session.refresh(project)
        transcription = models.Transcription(
            title="Soft project song",
            project_id=project.id,
            user_id=owner.id,
            original_audio_public_id="musicstudio/soft-original",
            is_processed=True,
            processing_status="completed",
        )
        session.add(transcription)
        session.commit()
        project_id = project.id
        transcription_id = transcription.id
    finally:
        session.close()

    with patch(
        "app.api.v1.endpoints.audio.storage.delete_cloudinary_asset",
        return_value=True,
    ) as delete_mock:
        response = client.delete(
            f"/api/v1/projects/{project_id}?hard_delete=false",
            headers=auth_headers("project-soft-owner"),
        )

    assert response.status_code == 200
    assert response.json()["is_deleted"] is True
    delete_mock.assert_any_call("musicstudio/soft-original", resource_type="video")

    session = TestingSessionLocal()
    try:
        project = session.query(models.Project).filter(models.Project.id == project_id).one()
        transcription = (
            session.query(models.Transcription)
            .filter(models.Transcription.id == transcription_id)
            .one()
        )
        assert project.is_deleted is True
        assert transcription.is_deleted is True
        assert transcription.processing_status == "deleted"
    finally:
        session.close()


def test_delete_transcription_marks_processing_job_best_effort_cancelled():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "processing-delete-owner", "processing-delete@example.com")
        transcription = models.Transcription(
            title="Processing song",
            user_id=owner.id,
            is_processed=False,
            processing_status="processing",
            celery_task_id="task-processing",
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
    finally:
        session.close()

    with patch("app.api.v1.endpoints.audio.celery_app.control.revoke") as revoke_mock:
        response = client.delete(
            f"/api/v1/transcriptions/{transcription_id}",
            headers=auth_headers("processing-delete-owner"),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["is_deleted"] is True
    assert payload["processing_status"] == "cancelled"
    assert "best-effort" in payload["processing_error"]
    revoke_mock.assert_called_once_with("task-processing", terminate=True)


def test_update_instrument_track_metadata_only_changes_user_editable_fields():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "metadata-owner", "metadata-owner@example.com")
        transcription = models.Transcription(
            title="Metadata song",
            audio_file_path="uploads/metadata.wav",
            user_id=owner.id,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="guitar",
            display_name="Guitar",
            tab_json='{"generated": true}',
            confidence_score=80,
            processing_status="completed",
        )
        session.add(track)
        session.commit()
        transcription_id = transcription.id
        track_id = track.id
    finally:
        session.close()

    response = client.patch(
        f"/api/v1/audio/{transcription_id}/tracks/{track_id}",
        headers=auth_headers("metadata-owner"),
        json={
            "display_name": "Lead Guitar",
            "instrument_type": "guitar",
            "confidence_notes": "Bright lead part, likely reliable.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["display_name"] == "Lead Guitar"
    assert payload["confidence_notes"] == "Bright lead part, likely reliable."
    assert payload["tab_json"] == '{"generated": true}'
    assert payload["confidence_score"] == 80


def test_reprocess_instrument_track_requires_authentication():
    reset_database()

    response = client.post("/api/v1/audio/1/tracks/1/reprocess")

    assert response.status_code == 401


def test_reprocess_instrument_track_requires_transcription_access(tmp_path):
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "reprocess-owner", "reprocess-owner@example.com")
        create_user(session, "reprocess-other", "reprocess-other@example.com")
        stem_path = tmp_path / "guitar.wav"
        stem_path.write_bytes(b"guitar")
        transcription = models.Transcription(
            title="Private reprocess song",
            audio_file_path="uploads/private-reprocess.wav",
            user_id=owner.id,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)
        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="guitar",
            display_name="Guitar",
            stem_audio_path=str(stem_path),
            processing_status="completed",
        )
        session.add(track)
        session.commit()
        transcription_id = transcription.id
        track_id = track.id
    finally:
        session.close()

    response = client.post(
        f"/api/v1/audio/{transcription_id}/tracks/{track_id}/reprocess",
        headers=auth_headers("reprocess-other"),
    )

    assert response.status_code == 403


def test_reprocess_instrument_track_returns_404_for_missing_track():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "reprocess-missing-owner", "reprocess-missing-owner@example.com")
        transcription = models.Transcription(
            title="Missing track song",
            audio_file_path="uploads/missing-track.wav",
            user_id=owner.id,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        transcription_id = transcription.id
    finally:
        session.close()

    response = client.post(
        f"/api/v1/audio/{transcription_id}/tracks/999/reprocess",
        headers=auth_headers("reprocess-missing-owner"),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Instrument track not found"


def test_reprocess_instrument_track_rejects_unsupported_instrument(tmp_path):
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "reprocess-strings-owner", "reprocess-strings-owner@example.com")
        stem_path = tmp_path / "strings.wav"
        stem_path.write_bytes(b"strings")
        transcription = models.Transcription(
            title="Unsupported reprocess song",
            audio_file_path="uploads/unsupported-reprocess.wav",
            user_id=owner.id,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)
        track = models.InstrumentTrack(
            transcription_id=transcription.id,
                instrument_type="strings",
                display_name="Strings",
            stem_audio_path=str(stem_path),
            processing_status="completed",
        )
        session.add(track)
        session.commit()
        transcription_id = transcription.id
        track_id = track.id
    finally:
        session.close()

    response = client.post(
        f"/api/v1/audio/{transcription_id}/tracks/{track_id}/reprocess",
        headers=auth_headers("reprocess-strings-owner"),
    )

    assert response.status_code == 422
    assert "supports guitar, bass, drum, and vocal stems" in response.json()["detail"]


def test_reprocess_instrument_track_marks_missing_stem_failed():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "reprocess-missing-stem-owner", "reprocess-missing-stem-owner@example.com")
        transcription = models.Transcription(
            title="Missing stem reprocess song",
            audio_file_path="uploads/missing-stem-reprocess.wav",
            user_id=owner.id,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)
        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="guitar",
            display_name="Guitar",
            stem_audio_path="uploads/stems/missing-reprocess-guitar.wav",
            processing_status="completed",
        )
        session.add(track)
        session.commit()
        transcription_id = transcription.id
        track_id = track.id
    finally:
        session.close()

    response = client.post(
        f"/api/v1/audio/{transcription_id}/tracks/{track_id}/reprocess",
        headers=auth_headers("reprocess-missing-stem-owner"),
    )

    assert response.status_code == 422
    session = TestingSessionLocal()
    try:
        refreshed = session.query(models.InstrumentTrack).filter(
            models.InstrumentTrack.id == track_id
        ).first()
        assert refreshed.processing_status == "failed"
        assert "missing" in refreshed.confidence_notes.lower()
    finally:
        session.close()


def test_reprocess_instrument_track_queues_supported_track_and_clears_outputs(tmp_path):
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "reprocess-guitar-owner", "reprocess-guitar-owner@example.com")
        stem_path = tmp_path / "guitar.wav"
        stem_path.write_bytes(b"guitar")
        transcription = models.Transcription(
            title="Queue reprocess song",
            audio_file_path="uploads/queue-reprocess.wav",
            user_id=owner.id,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)
        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="guitar",
            display_name="Guitar",
            stem_audio_path=str(stem_path),
            notes_json=sample_notes_json(),
            tab_json=sample_tab_json("guitar"),
            notation_json="<old />",
            confidence_notes="old note",
            processing_status="completed",
        )
        session.add(track)
        session.commit()
        transcription_id = transcription.id
        track_id = track.id
    finally:
        session.close()

    with (
        patch("app.api.v1.endpoints.audio._celery_has_available_worker", return_value=True),
        patch("app.api.v1.endpoints.audio.celery_app.send_task") as send_task_mock,
    ):
        response = client.post(
            f"/api/v1/audio/{transcription_id}/tracks/{track_id}/reprocess",
            headers=auth_headers("reprocess-guitar-owner"),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processing_status"] == "processing"
    assert payload["notes_json"] is None
    assert payload["tab_json"] is None
    assert payload["notation_json"] is None
    assert payload["confidence_notes"] is None
    send_task_mock.assert_called_once_with(
        "app.tasks.reprocess_instrument_track",
        args=[track_id],
    )
    session = TestingSessionLocal()
    try:
        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).one()
        assert refreshed.processing_status != "processing"
        assert refreshed.is_processed is True
    finally:
        session.close()


def test_reprocess_drum_track_queues_and_clears_outputs(tmp_path):
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "reprocess-drum-owner", "reprocess-drum-owner@example.com")
        stem_path = tmp_path / "drums.wav"
        stem_path.write_bytes(b"drums")
        transcription = models.Transcription(
            title="Queue drum reprocess song",
            audio_file_path="uploads/queue-drum-reprocess.wav",
            user_id=owner.id,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)
        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="drums",
            display_name="Drums",
            stem_audio_path=str(stem_path),
            notes_json='{"drum_hits": [{"onset": 0.0}]}',
            tab_json='{"old": true}',
            notation_json="<old />",
            confidence_notes="old note",
            processing_status="completed",
        )
        session.add(track)
        session.commit()
        transcription_id = transcription.id
        track_id = track.id
    finally:
        session.close()

    with (
        patch("app.api.v1.endpoints.audio._celery_has_available_worker", return_value=True),
        patch("app.api.v1.endpoints.audio.celery_app.send_task") as send_task_mock,
    ):
        response = client.post(
            f"/api/v1/audio/{transcription_id}/tracks/{track_id}/reprocess",
            headers=auth_headers("reprocess-drum-owner"),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processing_status"] == "processing"
    assert payload["notes_json"] is None
    assert payload["tab_json"] is None
    assert payload["notation_json"] is None
    assert payload["confidence_notes"] is None
    send_task_mock.assert_called_once_with(
        "app.tasks.reprocess_instrument_track",
        args=[track_id],
    )
    session = TestingSessionLocal()
    try:
        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).one()
        assert refreshed.processing_status != "processing"
        assert refreshed.is_processed is True
    finally:
        session.close()


def test_get_instrument_track_stem_returns_404_when_file_is_missing():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "stem-owner", "stem-owner@example.com")
        transcription = models.Transcription(
            title="Stem song",
            audio_file_path="uploads/stem.wav",
            user_id=owner.id,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="guitar",
            display_name="Guitar",
            stem_audio_path="uploads/stems/missing-guitar.wav",
            processing_status="completed",
        )
        session.add(track)
        session.commit()
        transcription_id = transcription.id
        track_id = track.id
    finally:
        session.close()

    response = client.get(
        f"/api/v1/audio/{transcription_id}/tracks/{track_id}/stem",
        headers=auth_headers("stem-owner"),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Instrument stem audio file not available"


def test_get_guitar_track_tab_export_uses_track_tab_json():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "track-tab-owner", "track-tab-owner@example.com")
        transcription = models.Transcription(
            title="Track export song",
            audio_file_path="uploads/export.wav",
            user_id=owner.id,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="guitar",
            display_name="Guitar",
            notes_json=sample_notes_json(),
            tab_json=sample_tab_json("guitar"),
            processing_status="completed",
        )
        session.add(track)
        session.commit()
        transcription_id = transcription.id
        track_id = track.id
    finally:
        session.close()

    response = client.get(
        f"/api/v1/audio/{transcription_id}/tracks/{track_id}/tab",
        headers=auth_headers("track-tab-owner"),
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "filename=transcription_" in response.headers["content-disposition"]
    assert "_guitar.tab" in response.headers["content-disposition"]
    assert response.text.startswith("e|")
    assert " 3" in response.text


def test_get_bass_track_tab_export_returns_four_bass_strings():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "bass-tab-owner", "bass-tab-owner@example.com")
        transcription = models.Transcription(
            title="Bass export song",
            audio_file_path="uploads/bass.wav",
            user_id=owner.id,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="bass",
            display_name="Bass",
            notes_json=sample_notes_json(),
            tab_json=sample_tab_json("bass"),
            processing_status="completed",
        )
        session.add(track)
        session.commit()
        transcription_id = transcription.id
        track_id = track.id
    finally:
        session.close()

    response = client.get(
        f"/api/v1/audio/{transcription_id}/tracks/{track_id}/tab",
        headers=auth_headers("bass-tab-owner"),
    )

    assert response.status_code == 200
    lines = response.text.splitlines()
    assert len(lines) == 4
    assert [line[:2] for line in lines] == ["G|", "D|", "A|", "E|"]


def test_get_track_midi_export_generates_midi_from_track_notes():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "track-midi-owner", "track-midi-owner@example.com")
        transcription = models.Transcription(
            title="MIDI export song",
            audio_file_path="uploads/midi.wav",
            user_id=owner.id,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="guitar",
            display_name="Guitar",
            notes_json=sample_notes_json(),
            tab_json=sample_tab_json("guitar"),
            processing_status="completed",
        )
        session.add(track)
        session.commit()
        transcription_id = transcription.id
        track_id = track.id
    finally:
        session.close()

    response = client.get(
        f"/api/v1/audio/{transcription_id}/tracks/{track_id}/midi",
        headers=auth_headers("track-midi-owner"),
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/midi")
    assert response.content.startswith(b"MThd")


def test_get_piano_track_exports_use_note_events_without_tab_data():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "piano-export-owner", "piano-export-owner@example.com")
        transcription = models.Transcription(
            title="Piano export song",
            audio_file_path="uploads/piano.wav",
            user_id=owner.id,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="piano",
            display_name="Piano",
            notes_json=sample_notes_json(),
            notation_json="<score-partwise version=\"3.1\"></score-partwise>",
            processing_status="completed",
        )
        session.add(track)
        session.commit()
        transcription_id = transcription.id
        track_id = track.id
    finally:
        session.close()

    midi_response = client.get(
        f"/api/v1/audio/{transcription_id}/tracks/{track_id}/midi",
        headers=auth_headers("piano-export-owner"),
    )
    musicxml_response = client.get(
        f"/api/v1/audio/{transcription_id}/tracks/{track_id}/musicxml",
        headers=auth_headers("piano-export-owner"),
    )
    tab_response = client.get(
        f"/api/v1/audio/{transcription_id}/tracks/{track_id}/tab",
        headers=auth_headers("piano-export-owner"),
    )

    assert midi_response.status_code == 422
    assert "Per-track MIDI export currently supports guitar and bass" in midi_response.json()["detail"]
    assert musicxml_response.status_code == 422
    assert "Per-track MUSICXML export currently supports guitar and bass" in musicxml_response.json()["detail"]
    assert tab_response.status_code == 422
    assert "Per-track TAB export currently supports guitar and bass" in tab_response.json()["detail"]


def test_get_track_musicxml_export_uses_existing_notation_json():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "track-xml-owner", "track-xml-owner@example.com")
        transcription = models.Transcription(
            title="MusicXML export song",
            audio_file_path="uploads/xml.wav",
            user_id=owner.id,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="guitar",
            display_name="Guitar",
            notes_json=sample_notes_json(),
            tab_json=sample_tab_json("guitar"),
            notation_json="<score-partwise version=\"3.1\"></score-partwise>",
            processing_status="completed",
        )
        session.add(track)
        session.commit()
        transcription_id = transcription.id
        track_id = track.id
    finally:
        session.close()

    response = client.get(
        f"/api/v1/audio/{transcription_id}/tracks/{track_id}/musicxml",
        headers=auth_headers("track-xml-owner"),
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert response.text == "<score-partwise version=\"3.1\"></score-partwise>"


def test_get_track_musicxml_export_generates_and_persists_when_missing():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "track-xml-gen-owner", "track-xml-gen-owner@example.com")
        transcription = models.Transcription(
            title="Generate MusicXML song",
            audio_file_path="uploads/xml-gen.wav",
            user_id=owner.id,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="guitar",
            display_name="Guitar",
            notes_json=sample_notes_json(),
            tab_json=sample_tab_json("guitar"),
            processing_status="completed",
        )
        session.add(track)
        session.commit()
        transcription_id = transcription.id
        track_id = track.id
    finally:
        session.close()

    with patch(
        "app.api.v1.endpoints.audio.midi.midi_to_musicxml",
        return_value="<score-partwise generated=\"true\"></score-partwise>",
    ):
        response = client.get(
            f"/api/v1/audio/{transcription_id}/tracks/{track_id}/musicxml",
            headers=auth_headers("track-xml-gen-owner"),
        )

    assert response.status_code == 200
    assert response.text == "<score-partwise generated=\"true\"></score-partwise>"

    session = TestingSessionLocal()
    try:
        refreshed = session.query(models.InstrumentTrack).filter(
            models.InstrumentTrack.id == track_id
        ).first()
        assert refreshed.notation_json == "<score-partwise generated=\"true\"></score-partwise>"
    finally:
        session.close()


def test_get_track_export_rejects_stem_only_track_with_useful_error():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "stem-only-owner", "stem-only-owner@example.com")
        transcription = models.Transcription(
            title="Stem only export song",
            audio_file_path="uploads/stem-only.wav",
            user_id=owner.id,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="vocals",
            display_name="Vocals",
            processing_status="completed",
        )
        session.add(track)
        session.commit()
        transcription_id = transcription.id
        track_id = track.id
    finally:
        session.close()

    response = client.get(
        f"/api/v1/audio/{transcription_id}/tracks/{track_id}/midi",
        headers=auth_headers("stem-only-owner"),
    )

    assert response.status_code == 422
    assert "Per-track MIDI export currently supports guitar and bass" in response.json()["detail"]


def test_get_drum_track_export_remains_unsupported_with_rhythm_data():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "drum-export-owner", "drum-export-owner@example.com")
        transcription = models.Transcription(
            title="Drum rhythm export song",
            audio_file_path="uploads/drums.wav",
            user_id=owner.id,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="drums",
            display_name="Drums",
            notes_json='{"drum_hits": [{"onset": 0.0, "offset": 0.12, "confidence": 0.8}]}',
            processing_status="completed",
        )
        session.add(track)
        session.commit()
        transcription_id = transcription.id
        track_id = track.id
    finally:
        session.close()

    response = client.get(
        f"/api/v1/audio/{transcription_id}/tracks/{track_id}/midi",
        headers=auth_headers("drum-export-owner"),
    )

    assert response.status_code == 422
    assert "Per-track MIDI export currently supports guitar and bass" in response.json()["detail"]


def test_get_track_export_requires_transcription_access():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "track-export-owner", "track-export-owner@example.com")
        create_user(session, "track-export-other", "track-export-other@example.com")
        transcription = models.Transcription(
            title="Private export song",
            audio_file_path="uploads/private-export.wav",
            user_id=owner.id,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="guitar",
            display_name="Guitar",
            notes_json=sample_notes_json(),
            tab_json=sample_tab_json("guitar"),
            processing_status="completed",
        )
        session.add(track)
        session.commit()
        transcription_id = transcription.id
        track_id = track.id
    finally:
        session.close()

    response = client.get(
        f"/api/v1/audio/{transcription_id}/tracks/{track_id}/tab",
        headers=auth_headers("track-export-other"),
    )

    assert response.status_code == 403
