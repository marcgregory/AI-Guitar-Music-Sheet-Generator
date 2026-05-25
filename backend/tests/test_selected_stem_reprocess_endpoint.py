from datetime import datetime
from unittest.mock import patch

import httpx
import pytest

from app import models
from app.core import config
from app.api.v1.endpoints.audio import _trigger_modal_worker
from test_audio_list_endpoint import (
    TestingSessionLocal,
    auth_headers,
    client,
    create_user,
    reset_database,
)


STEM_TO_TRACK = {
    "other": "guitar",
    "bass": "bass",
    "drums": "drums",
    "vocals": "vocals",
}


def _create_selected_stem_transcription(
    *,
    username: str,
    selected_stem: str,
    instrument_type: str,
    stem_audio_path: str | None = None,
    separated_audio_url: str | None = None,
    processing_status: str = "completed",
):
    session = TestingSessionLocal()
    try:
        owner = create_user(session, username, f"{username}@example.com")
        transcription = models.Transcription(
            title=f"{selected_stem.title()} reprocess song",
            audio_file_path=f"uploads/{selected_stem}.wav",
            selected_stem=selected_stem,
            separated_audio_url=separated_audio_url,
            user_id=owner.id,
            is_processed=True,
            processing_status=processing_status,
            processing_error="old error",
            warning_message="old warning",
            queue_position=None,
            estimated_wait_time=None,
            modal_request_id="old-modal-request",
            modal_dispatch_status="completed",
            created_at=datetime.utcnow(),
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)
        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type=instrument_type,
            display_name=instrument_type.title(),
            stem_audio_path=stem_audio_path,
            notes_json='{"notes": [{"onset": 0.0, "pitch": 60}]}',
            chords_json='{"chords": [{"name": "C"}]}',
            tab_json='{"tablature": [{"string": 1, "fret": 3}]}',
            notation_json="<old />",
            confidence_notes="old confidence note",
            processing_status="completed",
            created_at=datetime.utcnow(),
        )
        session.add(track)
        session.commit()
        session.refresh(track)
        return transcription.id, track.id
    finally:
        session.close()


@pytest.mark.parametrize(
    ("selected_stem", "instrument_type"),
    STEM_TO_TRACK.items(),
)
def test_selected_stem_reprocess_maps_stem_and_queues_same_track_job(
    tmp_path,
    selected_stem,
    instrument_type,
):
    reset_database()
    original_audio_mode = config.settings.AUDIO_PROCESSING_MODE
    config.settings.AUDIO_PROCESSING_MODE = "local"
    username = f"selected-reprocess-{selected_stem}"
    stem_path = tmp_path / f"{selected_stem}.wav"
    stem_path.write_bytes(selected_stem.encode("utf-8"))
    transcription_id, track_id = _create_selected_stem_transcription(
        username=username,
        selected_stem=selected_stem,
        instrument_type=instrument_type,
        stem_audio_path=str(stem_path),
    )

    try:
        with (
            patch("app.api.v1.endpoints.audio._celery_has_available_worker", return_value=True),
            patch("app.api.v1.endpoints.audio.celery_app.send_task") as send_task_mock,
        ):
            response = client.post(
                f"/api/v1/transcriptions/{transcription_id}/reprocess",
                headers=auth_headers(username),
            )
    finally:
        config.settings.AUDIO_PROCESSING_MODE = original_audio_mode

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == track_id
    assert payload["instrument_type"] == instrument_type
    assert payload["processing_status"] == "processing"
    assert payload["notes_json"] is None
    assert payload["chords_json"] is None
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
        assert refreshed.processing_status == "completed"
        assert refreshed.is_processed is True
        assert refreshed.processing_error == "old error"
        assert refreshed.warning_message == "old warning"
        assert refreshed.queue_position is None
        assert refreshed.estimated_wait_time is None
        assert refreshed.modal_request_id is None
        assert refreshed.modal_dispatch_status is None
    finally:
        session.close()


@pytest.mark.parametrize("parent_status", ["completed", "completed_with_warning", "stem_ready"])
def test_track_reprocess_modal_dispatches_when_parent_is_viewable(parent_status):
    reset_database()
    original_audio_mode = config.settings.AUDIO_PROCESSING_MODE
    original_processing_mode = config.settings.PROCESSING_MODE
    original_modal_url = config.settings.MODAL_TRIGGER_URL
    username = f"modal-track-reprocess-{parent_status}"
    transcription_id, track_id = _create_selected_stem_transcription(
        username=username,
        selected_stem="other",
        instrument_type="guitar",
        separated_audio_url="https://cdn.example.com/stems/other.wav",
        processing_status=parent_status,
    )

    try:
        config.settings.AUDIO_PROCESSING_MODE = "modal"
        config.settings.PROCESSING_MODE = "modal"
        config.settings.MODAL_TRIGGER_URL = "https://modal.test/trigger"
        modal_response = httpx.Response(
            202,
            request=httpx.Request("POST", "https://modal.test/trigger"),
        )
        session = TestingSessionLocal()
        try:
            transcription = session.query(models.Transcription).filter(
                models.Transcription.id == transcription_id
            ).one()
            track = session.query(models.InstrumentTrack).filter(
                models.InstrumentTrack.id == track_id
            ).one()
            transcription.modal_job_type = "reprocess_track"
            transcription.modal_request_id = None
            transcription.modal_dispatch_status = None
            session.add(transcription)
            session.query(models.InstrumentTrack).filter(
                models.InstrumentTrack.id == track.id
            ).update({"processing_status": "processing"})
            session.commit()
        finally:
            session.close()
        with (
            patch("app.api.v1.endpoints.audio.db.SessionLocal", TestingSessionLocal),
            patch("app.api.v1.endpoints.audio.httpx.post", return_value=modal_response) as post_mock,
        ):
            _trigger_modal_worker(
                transcription_id,
                "reprocess_track",
                None,
                track_id,
            )
    finally:
        config.settings.AUDIO_PROCESSING_MODE = original_audio_mode
        config.settings.PROCESSING_MODE = original_processing_mode
        config.settings.MODAL_TRIGGER_URL = original_modal_url

    post_mock.assert_called_once()
    payload = post_mock.call_args.kwargs["json"]
    assert payload["job_type"] == "reprocess_track"
    assert payload["track_id"] == track_id
    assert payload["separated_audio_url"] == "https://cdn.example.com/stems/other.wav"

    session = TestingSessionLocal()
    try:
        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).one()
        refreshed_track = session.query(models.InstrumentTrack).filter(
            models.InstrumentTrack.id == track_id
        ).one()
        assert refreshed.processing_status == parent_status
        assert refreshed.is_processed is True
        assert refreshed.modal_job_type == "reprocess_track"
        assert refreshed.modal_dispatch_status == "dispatched"
        assert refreshed_track.processing_status == "processing"
    finally:
        session.close()


def test_track_reprocess_missing_modal_config_marks_track_failed():
    reset_database()
    original_audio_mode = config.settings.AUDIO_PROCESSING_MODE
    original_processing_mode = config.settings.PROCESSING_MODE
    original_modal_url = config.settings.MODAL_TRIGGER_URL
    username = "modal-track-reprocess-missing-config"
    transcription_id, track_id = _create_selected_stem_transcription(
        username=username,
        selected_stem="other",
        instrument_type="guitar",
        separated_audio_url="https://cdn.example.com/stems/other.wav",
    )

    try:
        config.settings.AUDIO_PROCESSING_MODE = "modal"
        config.settings.PROCESSING_MODE = "modal"
        config.settings.MODAL_TRIGGER_URL = None
        response = client.post(
            f"/api/v1/audio/{transcription_id}/tracks/{track_id}/reprocess",
            headers=auth_headers(username),
        )
    finally:
        config.settings.AUDIO_PROCESSING_MODE = original_audio_mode
        config.settings.PROCESSING_MODE = original_processing_mode
        config.settings.MODAL_TRIGGER_URL = original_modal_url

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Modal processing is enabled but MODAL_TRIGGER_URL is not configured."
    )

    session = TestingSessionLocal()
    try:
        refreshed_track = session.query(models.InstrumentTrack).filter(
            models.InstrumentTrack.id == track_id
        ).one()
        assert refreshed_track.processing_status == "failed"
        assert refreshed_track.confidence_notes == (
            "Track reprocessing could not be started. Please retry later."
        )
    finally:
        session.close()


def test_selected_stem_reprocess_returns_404_when_selected_track_missing(tmp_path):
    reset_database()
    username = "selected-reprocess-missing-track"
    session = TestingSessionLocal()
    try:
        owner = create_user(session, username, f"{username}@example.com")
        transcription = models.Transcription(
            title="Missing selected track",
            audio_file_path="uploads/missing-track.wav",
            selected_stem="bass",
            user_id=owner.id,
            is_processed=True,
            processing_status="completed",
            created_at=datetime.utcnow(),
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)
        session.add(models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="guitar",
            display_name="Guitar",
            stem_audio_path=str(tmp_path / "wrong-stem.wav"),
            processing_status="completed",
            created_at=datetime.utcnow(),
        ))
        session.commit()
        transcription_id = transcription.id
    finally:
        session.close()

    response = client.post(
        f"/api/v1/transcriptions/{transcription_id}/reprocess",
        headers=auth_headers(username),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Selected stem track is not available for reprocessing."


def test_selected_stem_reprocess_returns_422_when_stem_audio_source_missing():
    reset_database()
    username = "selected-reprocess-missing-stem"
    transcription_id, track_id = _create_selected_stem_transcription(
        username=username,
        selected_stem="other",
        instrument_type="guitar",
        stem_audio_path="uploads/stems/missing-selected-guitar.wav",
    )

    response = client.post(
        f"/api/v1/transcriptions/{transcription_id}/reprocess",
        headers=auth_headers(username),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Guitar stem audio file is missing."

    session = TestingSessionLocal()
    try:
        refreshed = session.query(models.InstrumentTrack).filter(
            models.InstrumentTrack.id == track_id
        ).one()
        assert refreshed.processing_status == "failed"
        assert refreshed.confidence_notes == "Stem audio file is missing; track reprocessing skipped."
    finally:
        session.close()
