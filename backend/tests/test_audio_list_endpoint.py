import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db, models
from app.core import config
from app.core.security import create_access_token, get_password_hash
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


def test_upload_audio_queues_when_active_transcription_exists():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "active-owner", "active-owner@example.com")
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

    with (
        patch("app.api.v1.endpoints.audio._celery_has_available_worker", return_value=True),
        patch("app.api.v1.endpoints.audio.celery_app.send_task") as send_task_mock,
    ):
        response = client.post(
            "/api/v1/audio/upload",
            headers=auth_headers("active-owner"),
            data={"selected_stem": "other"},
            files={"file": ("sample.wav", b"RIFF....", "audio/wav")},
        )

    assert response.status_code == 200
    assert response.json()["selected_stem"] == "other"
    assert response.json()["processing_status"] == "queued"
    send_task_mock.assert_called_once()


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


def test_upload_audio_external_worker_mode_queues_without_celery():
    reset_database()
    session = TestingSessionLocal()
    original_mode = config.settings.PROCESSING_MODE
    try:
        create_user(session, "external-mode-owner", "external-mode@example.com")
        config.settings.PROCESSING_MODE = "external_worker"
    finally:
        session.close()

    try:
        with patch("app.api.v1.endpoints.audio.celery_app.send_task") as send_task_mock:
            response = client.post(
                "/api/v1/audio/upload",
                headers=auth_headers("external-mode-owner"),
                data={"selected_stem": "other"},
                files={"file": ("external.wav", b"RIFF external", "audio/wav")},
            )
    finally:
        config.settings.PROCESSING_MODE = original_mode

    assert response.status_code == 200
    payload = response.json()
    assert payload["processing_status"] in {"pending", "queued"}
    assert payload["selected_stem"] == "other"
    send_task_mock.assert_not_called()


def test_upload_audio_modal_mode_triggers_modal_path_without_celery():
    reset_database()
    session = TestingSessionLocal()
    original_mode = config.settings.PROCESSING_MODE
    try:
        create_user(session, "modal-mode-owner", "modal-mode@example.com")
        config.settings.PROCESSING_MODE = "modal"
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
        config.settings.PROCESSING_MODE = original_mode

    assert response.status_code == 200
    assert response.json()["selected_stem"] == "bass"
    modal_trigger_mock.assert_called_once()
    send_task_mock.assert_not_called()


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
    assert payload["processing_status"] == "completed"
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
        assert track.processing_status == "completed"
    finally:
        session.close()


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
        patch("app.api.v1.endpoints.audio.storage.delete_asset", return_value=True) as delete_mock,
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
    assert not local_audio.exists()

    list_response = client.get("/api/v1/audio/", headers=auth_headers("delete-owner"))
    assert list_response.status_code == 200
    assert list_response.json() == []


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
        owner = create_user(session, "reprocess-vocal-owner", "reprocess-vocal-owner@example.com")
        stem_path = tmp_path / "vocals.wav"
        stem_path.write_bytes(b"vocals")
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
            instrument_type="vocals",
            display_name="Vocals",
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
        headers=auth_headers("reprocess-vocal-owner"),
    )

    assert response.status_code == 422
    assert "supports guitar, bass, piano, and drum tracks" in response.json()["detail"]


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

    assert midi_response.status_code == 200
    assert midi_response.content.startswith(b"MThd")
    assert musicxml_response.status_code == 200
    assert musicxml_response.text == "<score-partwise version=\"3.1\"></score-partwise>"
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
    assert "Per-track MIDI export currently supports guitar, bass, and piano" in response.json()["detail"]


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
    assert "Per-track MIDI export currently supports guitar, bass, and piano" in response.json()["detail"]


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
