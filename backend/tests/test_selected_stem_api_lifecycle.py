import hashlib
import json
from datetime import datetime
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


def _create_transcription(username: str, **overrides) -> int:
    session = TestingSessionLocal()
    try:
        owner = create_user(session, username, f"{username}@example.com")
        values = {
            "title": "Lifecycle song",
            "audio_file_path": "uploads/lifecycle.wav",
            "selected_stem": "other",
            "user_id": owner.id,
            "is_processed": False,
            "processing_status": "pending",
            "created_at": datetime.utcnow(),
        }
        values.update(overrides)
        transcription = models.Transcription(**values)
        session.add(transcription)
        session.commit()
        return transcription.id
    finally:
        session.close()


def test_youtube_reuses_completed_duplicate_same_source_and_stem():
    reset_database()
    normalized_source_id = "dQw4w9WgXcQ"
    existing_id = _create_transcription(
        "youtube-duplicate-owner",
        title="Already separated",
        selected_stem="bass",
        source_type="youtube",
        source_url=f"https://www.youtube.com/watch?v={normalized_source_id}",
        normalized_source_id=normalized_source_id,
        is_processed=True,
        processing_status="completed",
    )

    with patch("app.api.v1.endpoints.audio.yt_dlp.YoutubeDL") as youtube_dl_mock:
        response = client.post(
            "/api/v1/audio/youtube",
            headers=auth_headers("youtube-duplicate-owner"),
            json={
                "youtube_url": f"https://youtu.be/{normalized_source_id}",
                "selected_stem": "bass",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == existing_id
    assert payload["duplicate_reused"] is True
    youtube_dl_mock.assert_not_called()


def test_upload_same_source_different_stem_queues_new_job(tmp_path):
    reset_database()
    contents = b"RIFF same source different stem"
    existing_hash = hashlib.sha256(contents).hexdigest()
    _create_transcription(
        "different-stem-owner",
        title="Existing guitar stem",
        selected_stem="other",
        audio_hash=existing_hash,
        is_processed=True,
        processing_status="completed",
    )
    original_audio_mode = config.settings.AUDIO_PROCESSING_MODE
    original_processing_mode = config.settings.PROCESSING_MODE
    original_modal_url = config.settings.MODAL_TRIGGER_URL
    config.settings.AUDIO_PROCESSING_MODE = "modal"
    config.settings.PROCESSING_MODE = "modal"
    config.settings.MODAL_TRIGGER_URL = "https://modal.test/trigger"

    try:
        with (
            patch("app.api.v1.endpoints.audio.UPLOAD_DIR", tmp_path),
            patch(
                "app.api.v1.endpoints.audio._upload_original_audio",
                return_value={
                    "secure_url": "https://cdn.example.com/original.wav",
                    "public_id": "original/new-bass",
                },
            ),
            patch("app.api.v1.endpoints.audio._trigger_modal_worker") as trigger_mock,
        ):
            response = client.post(
                "/api/v1/audio/upload",
                headers=auth_headers("different-stem-owner"),
                data={"selected_stem": "bass"},
                files={"file": ("same.wav", contents, "audio/wav")},
            )
    finally:
        config.settings.AUDIO_PROCESSING_MODE = original_audio_mode
        config.settings.PROCESSING_MODE = original_processing_mode
        config.settings.MODAL_TRIGGER_URL = original_modal_url

    assert response.status_code == 200
    payload = response.json()
    assert payload["duplicate_reused"] is False
    assert payload["selected_stem"] == "bass"
    assert payload["audio_hash"] == existing_hash
    assert payload["processing_status"] == "processing"
    trigger_mock.assert_called_once()

    session = TestingSessionLocal()
    try:
        rows = session.query(models.Transcription).order_by(models.Transcription.id.asc()).all()
        assert len(rows) == 2
        assert rows[0].selected_stem == "other"
        assert rows[1].selected_stem == "bass"
    finally:
        session.close()


@pytest.mark.parametrize(
    ("stored_status", "is_processed", "expected_status"),
    [
        ("pending", False, "pending"),
        ("queued", False, "queued"),
        ("processing", False, "processing"),
        ("stem_ready", True, "stem_ready"),
        ("completed_with_warning", True, "completed_with_warning"),
        ("failed", False, "failed"),
    ],
)
def test_status_returns_selected_stem_lifecycle_states(
    tmp_path,
    stored_status,
    is_processed,
    expected_status,
):
    reset_database()
    stem_path = tmp_path / f"{stored_status}.wav"
    stem_path.write_bytes(b"stem")
    transcription_id = _create_transcription(
        f"status-{stored_status}-owner",
        selected_stem="other",
        separated_audio_file_path=str(stem_path) if is_processed else None,
        notes_data=sample_notes_json() if stored_status != "failed" else None,
        tablature_data=sample_tab_json("guitar") if stored_status == "completed_with_warning" else None,
        is_processed=is_processed,
        processing_status=stored_status,
        processing_error="worker failed" if stored_status == "failed" else None,
        warning_message=(
            "Completed with a warning"
            if stored_status == "completed_with_warning"
            else None
        ),
        can_play_stem=is_processed,
        can_generate_score=stored_status == "completed_with_warning",
    )

    response = client.get(
        f"/api/v1/audio/{transcription_id}/status",
        headers=auth_headers(f"status-{stored_status}-owner"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == expected_status
    assert payload["selected_stem"] == "other"
    assert payload["transcription_id"] == transcription_id


@pytest.mark.parametrize("stored_status", ["pending", "queued", "processing"])
def test_result_rejects_before_ready_states(stored_status):
    reset_database()
    transcription_id = _create_transcription(
        f"result-not-ready-{stored_status}",
        selected_stem="other",
        is_processed=False,
        processing_status=stored_status,
    )

    response = client.get(
        f"/api/v1/audio/{transcription_id}/result",
        headers=auth_headers(f"result-not-ready-{stored_status}"),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Transcription is still processing"


@pytest.mark.parametrize("stored_status", ["stem_ready", "completed", "completed_with_warning"])
def test_result_returns_after_ready_states(tmp_path, stored_status):
    reset_database()
    stem_path = tmp_path / f"{stored_status}.wav"
    stem_path.write_bytes(b"stem")
    transcription_id = _create_transcription(
        f"result-ready-{stored_status}",
        selected_stem="other",
        separated_audio_file_path=str(stem_path),
        notes_data=sample_notes_json(),
        tablature_data=sample_tab_json("guitar"),
        is_processed=True,
        processing_status=stored_status,
        can_play_stem=True,
        can_generate_score=True,
    )

    response = client.get(
        f"/api/v1/audio/{transcription_id}/result",
        headers=auth_headers(f"result-ready-{stored_status}"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == transcription_id
    assert payload["processing_status"] == stored_status


def test_selected_stem_upload_ready_result_delete_smoke_path(tmp_path):
    reset_database()
    original_audio_mode = config.settings.AUDIO_PROCESSING_MODE
    original_processing_mode = config.settings.PROCESSING_MODE
    original_modal_url = config.settings.MODAL_TRIGGER_URL
    original_token = config.settings.WORKER_API_TOKEN
    config.settings.AUDIO_PROCESSING_MODE = "modal"
    config.settings.PROCESSING_MODE = "modal"
    config.settings.MODAL_TRIGGER_URL = "https://modal.test/trigger"
    config.settings.WORKER_API_TOKEN = "test-worker-token"

    session = TestingSessionLocal()
    try:
        create_user(session, "selected-smoke-owner", "selected-smoke@example.com")
    finally:
        session.close()

    try:
        with (
            patch("app.api.v1.endpoints.audio.UPLOAD_DIR", tmp_path),
            patch(
                "app.api.v1.endpoints.audio._upload_original_audio",
                return_value={
                    "secure_url": "https://cdn.example.com/original.wav",
                    "public_id": "smoke/original",
                },
            ),
            patch("app.api.v1.endpoints.audio._trigger_modal_worker") as trigger_mock,
        ):
            upload_response = client.post(
                "/api/v1/audio/upload",
                headers=auth_headers("selected-smoke-owner"),
                data={"selected_stem": "other"},
                files={"file": ("smoke.wav", b"RIFF selected smoke one", "audio/wav")},
            )
            assert upload_response.status_code == 200
            upload_payload = upload_response.json()
            transcription_id = upload_payload["id"]
            assert upload_payload["selected_stem"] == "other"
            assert upload_payload["processing_status"] == "processing"

            status_response = client.get(
                f"/api/v1/audio/{transcription_id}/status",
                headers=auth_headers("selected-smoke-owner"),
            )
            assert status_response.status_code == 200
            assert status_response.json()["status"] == "processing"

            premature_result = client.get(
                f"/api/v1/audio/{transcription_id}/result",
                headers=auth_headers("selected-smoke-owner"),
            )
            assert premature_result.status_code == 400
            assert premature_result.json()["detail"] == "Transcription is still processing"

            complete_response = client.post(
                f"/api/v1/worker/jobs/{transcription_id}/complete",
                headers={"X-Worker-Token": "test-worker-token"},
                json={
                    "separated_audio_url": "https://cdn.example.com/other.wav",
                    "separated_audio_public_id": "smoke/other",
                    "confidence": 91,
                    "notes_data": {
                        "notes": [
                            {"pitch": 64, "onset": 0.0, "offset": 0.5, "velocity": 90}
                        ]
                    },
                    "tablature_data": {
                        "instrument": "guitar",
                        "tablature": [
                            {"string": 1, "fret": 3, "onset": 0.0, "offset": 0.5}
                        ],
                    },
                },
            )
            assert complete_response.status_code == 200
            assert complete_response.json()["processing_status"] == "stem_ready"

            ready_status = client.get(
                f"/api/v1/audio/{transcription_id}/status",
                headers=auth_headers("selected-smoke-owner"),
            )
            assert ready_status.status_code == 200
            assert ready_status.json()["status"] == "stem_ready"

            result_response = client.get(
                f"/api/v1/audio/{transcription_id}/result",
                headers=auth_headers("selected-smoke-owner"),
            )
            assert result_response.status_code == 200
            result_payload = result_response.json()
            assert result_payload["processing_status"] == "stem_ready"
            assert result_payload["can_play_stem"] is True

            active_response = client.post(
                "/api/v1/audio/upload",
                headers=auth_headers("selected-smoke-owner"),
                data={"selected_stem": "drums"},
                files={"file": ("active.wav", b"RIFF selected smoke two", "audio/wav")},
            )
            assert active_response.status_code == 200
            active_id = active_response.json()["id"]

            blocked_response = client.post(
                "/api/v1/audio/upload",
                headers=auth_headers("selected-smoke-owner"),
                data={"selected_stem": "vocals"},
                files={"file": ("blocked.wav", b"RIFF selected smoke three", "audio/wav")},
            )
            assert blocked_response.status_code == 429

            delete_response = client.delete(
                f"/api/v1/audio/{active_id}",
                headers=auth_headers("selected-smoke-owner"),
            )
            assert delete_response.status_code == 200
            assert delete_response.json()["processing_status"] == "cancelled"

            retry_after_delete = client.post(
                "/api/v1/audio/upload",
                headers=auth_headers("selected-smoke-owner"),
                data={"selected_stem": "vocals"},
                files={"file": ("after-delete.wav", b"RIFF selected smoke four", "audio/wav")},
            )
            assert retry_after_delete.status_code == 200

        assert trigger_mock.call_count == 3
    finally:
        config.settings.AUDIO_PROCESSING_MODE = original_audio_mode
        config.settings.PROCESSING_MODE = original_processing_mode
        config.settings.MODAL_TRIGGER_URL = original_modal_url
        config.settings.WORKER_API_TOKEN = original_token


def test_worker_complete_no_note_result_preserves_playback_and_disables_exports():
    reset_database()
    original_token = config.settings.WORKER_API_TOKEN
    transcription_id = _create_transcription(
        "worker-no-note-owner",
        selected_stem="other",
        original_audio_url="https://res.cloudinary.com/demo/video/upload/source.wav",
        is_processed=False,
        processing_status="processing",
    )
    config.settings.WORKER_API_TOKEN = "test-worker-token"

    try:
        response = client.post(
            f"/api/v1/worker/jobs/{transcription_id}/complete",
            headers={"X-Worker-Token": "test-worker-token"},
            json={
                "separated_audio_url": "https://res.cloudinary.com/demo/video/upload/stem.wav",
                "separated_audio_public_id": "musicstudio/stem",
                "confidence": 90,
            },
        )
    finally:
        config.settings.WORKER_API_TOKEN = original_token

    assert response.status_code == 200
    payload = response.json()
    assert payload["processing_status"] == "completed_with_warning"
    assert payload["can_play_stem"] is True
    assert payload["can_generate_score"] is False
    assert payload["warning_message"] == "No note events detected for this stem."
    assert payload["midi_file_url"] is None
    assert payload["tab_file_url"] is None

    status_response = client.get(
        f"/api/v1/audio/{transcription_id}/status",
        headers=auth_headers("worker-no-note-owner"),
    )
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["status"] == "completed_with_warning"
    assert status_payload["can_play_stem"] is True
    assert status_payload["can_generate_score"] is False
    assert status_payload["available_exports"] == []
    assert json.loads(status_payload["notes_data"]) == {
        "notes": [],
        "message": "No note events detected for this stem.",
    }
