from celery import current_task
from app.celery import celery_app
from app.core.config import settings
from app import db, models
from app.services import audio
from app.services import midi
from app.services import storage
from app.services import tablature
from app.services import chord_chart
import json
import os
import shutil
import tempfile
import logging
from pathlib import Path
from sqlalchemy.orm import Session
from typing import Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


INSTRUMENT_DISPLAY_NAMES = {
    "guitar": "Guitar",
    "bass": "Bass",
    "drums": "Drums",
    "vocals": "Vocals",
    "piano": "Piano",
    "other": "Other / Guitar / Piano / Melody",
}

TAB_TRANSCRIPTION_INSTRUMENTS = ("guitar", "bass")
STAFF_NOTATION_INSTRUMENTS = ("piano",)
DRUM_RHYTHM_INSTRUMENTS = ("drums",)
NOTE_TRANSCRIPTION_INSTRUMENTS = TAB_TRANSCRIPTION_INSTRUMENTS + STAFF_NOTATION_INSTRUMENTS
TRACK_REPROCESS_INSTRUMENTS = NOTE_TRANSCRIPTION_INSTRUMENTS + DRUM_RHYTHM_INSTRUMENTS
PLAYBACK_ONLY_INSTRUMENTS = ("vocals", "drums")
NO_NOTES_WARNING = "No note events detected for this stem."
UNSUPPORTED_STEM_WARNING = (
    "Stem separated successfully, but notation generation is not supported for this stem in the MVP."
)

VALID_SELECTED_STEMS = {"vocals", "drums", "bass", "other"}
STEM_TO_ANALYSIS_INSTRUMENT = {
    "other": "guitar",
    "bass": "bass",
    "drums": "drums",
    "vocals": "vocals",
}


def has_note_events(notes_data) -> bool:
    """Return True when pitch analysis contains usable note events."""
    if isinstance(notes_data, str):
        try:
            notes_data = json.loads(notes_data)
        except json.JSONDecodeError:
            return False

    if isinstance(notes_data, list):
        return len(notes_data) > 0

    if isinstance(notes_data, dict):
        notes = notes_data.get("notes")
        pitch_info = notes_data.get("pitch_info")
        return (
            isinstance(notes, list) and len(notes) > 0
        ) or (
            isinstance(pitch_info, list) and len(pitch_info) > 0
        )

    return False


def has_drum_hits(notes_data) -> bool:
    """Return True when drum rhythm analysis contains usable hit events."""
    if isinstance(notes_data, str):
        try:
            notes_data = json.loads(notes_data)
        except json.JSONDecodeError:
            return False

    if isinstance(notes_data, dict):
        drum_hits = notes_data.get("drum_hits")
        return isinstance(drum_hits, list) and len(drum_hits) > 0

    return False


def average_drum_hit_confidence(drum_result: Dict[str, Any]) -> int | None:
    drum_hits = drum_result.get("drum_hits")
    if not isinstance(drum_hits, list) or not drum_hits:
        return None

    confidences = [
        float(hit.get("confidence", 0))
        for hit in drum_hits
        if isinstance(hit, dict)
    ]
    if not confidences:
        return None

    return int(round(max(0.0, min(1.0, sum(confidences) / len(confidences))) * 100))


def stem_can_generate_score(selected_stem: str, analysis_instrument: str) -> bool:
    if selected_stem in {"vocals", "drums"}:
        return False
    return analysis_instrument in NOTE_TRANSCRIPTION_INSTRUMENTS


def stem_playback_available(transcription) -> bool:
    if getattr(transcription, "separated_audio_url", None):
        return True
    if getattr(transcription, "separated_audio_file_path", None):
        return Path(transcription.separated_audio_file_path).exists()
    return any(
        track.stem_audio_path and Path(track.stem_audio_path).exists()
        for track in getattr(transcription, "instrument_tracks", [])
    )


def set_transcription_warning(
    transcription,
    warning: str,
    *,
    can_generate_score: bool = False,
) -> None:
    transcription.warning_message = warning
    transcription.processing_error = None
    transcription.can_generate_score = can_generate_score
    transcription.can_play_stem = True


def pitch_debug_payload(stem_path: str, selected_stem: str, result: dict | None = None) -> dict:
    try:
        stats = audio.audio_debug_stats(stem_path)
    except Exception as exc:
        stats = {"audio_debug_error": str(exc)}
    result = result or {}
    notes = result.get("notes") if isinstance(result, dict) else []
    if not isinstance(notes, list):
        notes = []
    return {
        **stats,
        "selected_stem": selected_stem,
        "confidence_stats": result.get("confidence_stats") or audio.note_confidence_stats(notes),
        "model_outputs": result.get("model_outputs"),
        "total_notes_detected": result.get("total_notes_detected", len(notes)),
    }


def generate_single_track_transcription_output(
    track: models.InstrumentTrack,
    db_session: Session,
    *,
    clear_existing: bool = False,
    detection_sensitivity: str = "normal",
    selected_stem: str | None = None,
) -> models.InstrumentTrack:
    """Generate notes/rhythm, tab data, and notation for one supported instrument track."""
    if track.instrument_type in PLAYBACK_ONLY_INSTRUMENTS:
        track.processing_status = "completed_with_warning"
        track.confidence_notes = UNSUPPORTED_STEM_WARNING
        track.notes_json = json.dumps({
            "notes": [],
            "message": UNSUPPORTED_STEM_WARNING,
            "stem_capability": "playback_only",
        })
        track.tab_json = None
        track.notation_json = None
        db_session.add(track)
        db_session.commit()
        return track

    if track.instrument_type not in TRACK_REPROCESS_INSTRUMENTS:
        track.processing_status = "completed_with_warning"
        track.confidence_notes = UNSUPPORTED_STEM_WARNING
        db_session.add(track)
        db_session.commit()
        return track

    if clear_existing:
        track.notes_json = None
        track.chords_json = None
        track.tab_json = None
        track.notation_json = None
        track.confidence_notes = None

    if not track.stem_audio_path or not Path(track.stem_audio_path).exists():
        track.processing_status = "failed"
        track.confidence_notes = "Stem audio file is missing; track analysis skipped."
        db_session.add(track)
        db_session.commit()
        return track

    track.processing_status = "processing"
    db_session.add(track)
    db_session.commit()

    pitch_temp_dir = tempfile.mkdtemp()
    try:
        if track.instrument_type in DRUM_RHYTHM_INSTRUMENTS:
            drum_result = audio.analyze_drum_rhythm(track.stem_audio_path)
            if not has_drum_hits(drum_result):
                track.notes_json = json.dumps({
                    "drum_hits": [],
                    "message": "Drum stem separated successfully, but no usable hits were detected.",
                    "stem_capability": "playback_only",
                })
                track.tab_json = None
                track.notation_json = None
                track.processing_status = "completed_with_warning"
                track.confidence_notes = "No drum hits detected for this stem."
                db_session.add(track)
                db_session.commit()
                return track

            track.notes_json = json.dumps(drum_result)
            track.tab_json = None
            track.notation_json = None
            track.confidence_score = average_drum_hit_confidence(drum_result)
            track.confidence_notes = None
            track.processing_status = "completed"
        else:
            try:
                normalized_stem_path = audio.normalize_audio_volume(track.stem_audio_path)
            except Exception as normalize_error:
                logger.warning(
                    "Could not normalize separated stem for track %s; using original stem: %s",
                    track.id,
                    normalize_error,
                )
                normalized_stem_path = track.stem_audio_path
            logger.info(
                "Starting note detection for transcription track %s with stats %s",
                track.id,
                pitch_debug_payload(normalized_stem_path, selected_stem or track.instrument_type),
            )
            pitch_result = audio.detect_pitch(
                normalized_stem_path,
                pitch_temp_dir,
                sensitivity=detection_sensitivity,
            )
            logger.info(
                "Note detection output for transcription track %s: %s",
                track.id,
                pitch_debug_payload(normalized_stem_path, selected_stem or track.instrument_type, pitch_result),
            )
            if not has_note_events(pitch_result) and detection_sensitivity != "high":
                logger.info(
                    "Retrying note detection for transcription track %s with fallback sensitivity",
                    track.id,
                )
                pitch_result = audio.detect_pitch(
                    normalized_stem_path,
                    pitch_temp_dir,
                    sensitivity="high",
                )
                logger.info(
                    "Fallback note detection output for transcription track %s: %s",
                    track.id,
                    pitch_debug_payload(normalized_stem_path, selected_stem or track.instrument_type, pitch_result),
                )
            if not has_note_events(pitch_result):
                track.notes_json = json.dumps({
                    "notes": [],
                    "message": NO_NOTES_WARNING,
                    "debug": pitch_debug_payload(
                        normalized_stem_path,
                        selected_stem or track.instrument_type,
                        pitch_result,
                    ),
                })
                track.tab_json = None
                track.notation_json = None
                track.processing_status = "completed_with_warning"
                track.confidence_notes = NO_NOTES_WARNING
                db_session.add(track)
                db_session.commit()
                return track

            track.notes_json = json.dumps(pitch_result)
            if track.instrument_type in TAB_TRANSCRIPTION_INSTRUMENTS:
                track.tab_json = json.dumps(
                    tablature.notes_to_tablature(
                        pitch_result,
                        instrument_type=track.instrument_type,
                    )
                )
            else:
                track.tab_json = None
            track.confidence_notes = None

            try:
                with tempfile.TemporaryDirectory() as midi_temp_dir:
                    midi_path = Path(midi_temp_dir) / f"track_{track.id}.mid"
                    midi.notes_to_midi(pitch_result, str(midi_path))
                    track.notation_json = midi.midi_to_musicxml(str(midi_path))
            except Exception as notation_error:
                print(
                    f"Failed to generate notation for {track.instrument_type} "
                    f"track {track.id}: {str(notation_error)}"
                )

            track.processing_status = "completed"
    except Exception as track_error:
        track.processing_status = "failed"
        track.confidence_notes = str(track_error)
        track.notes_json = json.dumps({"notes": [], "error": str(track_error)})
        track.tab_json = None
        track.notation_json = None
    finally:
        shutil.rmtree(pitch_temp_dir, ignore_errors=True)

    db_session.add(track)
    db_session.commit()
    return track


def generate_track_transcription_outputs(
    transcription_id: int,
    db_session: Session,
) -> None:
    """Generate notes and tab data for supported separated instrument tracks."""
    tracks = (
            db_session.query(models.InstrumentTrack)
        .filter(
            models.InstrumentTrack.transcription_id == transcription_id,
            models.InstrumentTrack.instrument_type.in_(TRACK_REPROCESS_INSTRUMENTS),
        )
        .all()
    )

    for track in tracks:
        generate_single_track_transcription_output(track, db_session)


def get_db_session() -> Session:
    """Create a new database session for Celery tasks."""
    db_session = db.SessionLocal()
    try:
        return db_session
    finally:
        pass  # Caller must close the session


def update_task_state(task, state: str, meta: Dict[str, Any]) -> None:
    """Best-effort Celery progress update for local dev without Redis."""
    try:
        task.update_state(state=state, meta=meta)
    except Exception as e:
        print(f"Skipping task state update ({state}/{meta.get('step')}): {str(e)}")


def upload_transcription_artifact(
    transcription,
    file_path: str | None,
    *,
    folder_name: str,
) -> dict[str, str] | None:
    if not file_path:
        return None
    return storage.safe_upload_file(
        file_path,
        folder=f"transcriptions/{transcription.id}/{folder_name}",
        resource_type="auto",
    )


def save_ascii_tab_artifact(transcription, tablature_json: str, uploads_dir: str) -> str:
    uploads_dir = Path(storage.normalize_local_path(uploads_dir))
    tab_dir = uploads_dir / "tablature"
    tab_dir.mkdir(parents=True, exist_ok=True)
    tab_file_path = tab_dir / f"transcription_{transcription.id}.tab"
    tab_dict = json.loads(tablature_json)
    tab_file_path.write_text(tablature.tablature_to_ascii_tab(tab_dict), encoding="utf-8")
    return storage.normalize_local_path(tab_file_path)


def ensure_transcription_not_deleted(transcription) -> None:
    if getattr(transcription, "is_deleted", False):
        raise RuntimeError("Transcription was deleted before processing completed.")


def generate_derived_outputs(transcription, db_session: Session) -> None:
    """Regenerate MIDI, MusicXML, tablature, and chord charts from stored JSON."""
    if transcription.notes_data:
        try:
            midi_file_path = midi.save_midi_from_transcription(
                transcription.notes_data,
                transcription.id,
                settings.UPLOAD_DIR if hasattr(settings, 'UPLOAD_DIR') else "uploads"
            )
            transcription.midi_file_path = midi_file_path
            midi_upload = upload_transcription_artifact(
                transcription,
                midi_file_path,
                folder_name="exports",
            )
            if midi_upload:
                transcription.midi_file_url = midi_upload["secure_url"]
                transcription.midi_file_public_id = midi_upload["public_id"]
            try:
                transcription.notation_data = midi.midi_to_musicxml(midi_file_path)
            except Exception as xml_e:
                print(f"Failed to generate MusicXML for transcription {transcription.id}: {str(xml_e)}")
        except Exception as midi_e:
            print(f"Failed to generate MIDI for transcription {transcription.id}: {str(midi_e)}")

        try:
            tablature.save_tablature_from_transcription(
                transcription.notes_data,
                transcription.id,
                settings.UPLOAD_DIR if hasattr(settings, 'UPLOAD_DIR') else "uploads"
            )
            transcription.tablature_data = json.dumps(tablature.notes_to_tablature(transcription.notes_data))
            transcription.tab_file_path = storage.normalize_local_path(
                save_ascii_tab_artifact(
                    transcription,
                    transcription.tablature_data,
                    settings.UPLOAD_DIR if hasattr(settings, 'UPLOAD_DIR') else "uploads",
                )
            )
            tab_upload = upload_transcription_artifact(
                transcription,
                transcription.tab_file_path,
                folder_name="exports",
            )
            if tab_upload:
                transcription.tab_file_url = tab_upload["secure_url"]
                transcription.tab_file_public_id = tab_upload["public_id"]
        except Exception as tab_e:
            print(f"Failed to generate tablature for transcription {transcription.id}: {str(tab_e)}")

    if transcription.chords_data:
        try:
            transcription.chord_chart_data = chord_chart.chord_data_to_chord_chart_json(
                transcription.chords_data
            )
        except Exception as chart_e:
            print(f"Failed to generate chord charts for transcription {transcription.id}: {str(chart_e)}")

    db_session.add(transcription)
    db_session.commit()


def cleanup_transient_audio_files(transcription, db_session: Session) -> None:
    """Delete source scratch files while retaining separated stems for playback/retry."""
    path_fields = [
        "audio_file_path",
        "preprocessed_audio_file_path",
    ]
    if transcription.midi_file_url:
        path_fields.append("midi_file_path")
    if transcription.tab_file_url:
        path_fields.append("tab_file_path")
    changed = False

    for field_name in path_fields:
        path_value = getattr(transcription, field_name, None)
        if not path_value:
            continue

        try:
            path = Path(path_value)
            if path.exists() and path.is_file():
                path.unlink()
        except OSError as cleanup_error:
            print(
                f"Failed to delete {field_name} for transcription "
                f"{transcription.id}: {cleanup_error}"
            )
            continue

        setattr(transcription, field_name, None)
        changed = True

    if changed:
        db_session.add(transcription)
        db_session.commit()


def estimate_stem_confidence(stem_path: str) -> int:
    """Return a simple v1 confidence score for a persisted stem."""
    path = Path(stem_path)
    if not path.exists() or not path.is_file():
        return 0

    try:
        duration = audio.librosa.get_duration(path=str(path))
        if duration and duration > 0:
            return 90
    except Exception:
        pass

    return 60 if path.stat().st_size > 0 else 0


def copy_and_persist_instrument_tracks(
    transcription,
    stem_paths: dict[str, str],
    db_session: Session,
) -> dict[str, str]:
    """Copy separated stems into uploads and upsert InstrumentTrack rows."""
    uploads_dir = Path(storage.normalize_local_path(settings.UPLOAD_DIR if hasattr(settings, 'UPLOAD_DIR') else "uploads"))
    stem_upload_dir = uploads_dir / "separated" / f"transcription_{transcription.id}"
    stem_upload_dir.mkdir(parents=True, exist_ok=True)

    persisted_paths = {}
    for instrument_type, source_path_value in stem_paths.items():
        source_path = Path(storage.normalize_local_path(source_path_value))
        if not source_path.exists() or not source_path.is_file():
            continue

        destination_path = stem_upload_dir / f"{instrument_type}{source_path.suffix or '.wav'}"
        shutil.copy2(source_path, destination_path)

        track = db_session.query(models.InstrumentTrack).filter(
            models.InstrumentTrack.transcription_id == transcription.id,
            models.InstrumentTrack.instrument_type == instrument_type,
        ).first()
        if not track:
            track = models.InstrumentTrack(
                transcription_id=transcription.id,
                instrument_type=instrument_type,
                display_name=INSTRUMENT_DISPLAY_NAMES.get(
                    instrument_type,
                    instrument_type.replace("_", " ").title(),
                ),
            )

        track.stem_audio_path = storage.normalize_local_path(destination_path)
        track.confidence_score = estimate_stem_confidence(storage.normalize_local_path(destination_path))
        track.processing_status = "completed"
        db_session.add(track)
        persisted_paths[instrument_type] = storage.normalize_local_path(destination_path)

    db_session.commit()
    return persisted_paths


def persist_selected_stem_track(
    transcription,
    selected_stem: str,
    source_path_value: str,
    db_session: Session,
) -> models.InstrumentTrack:
    """Persist exactly one selected Demucs stem for Phase 1 processing.

    The Railway MVP intentionally stores and analyzes only the requested stem.
    That keeps Demucs CPU/RAM pressure, Cloudinary storage, and queue time
    predictable while the worker runs with concurrency=1.
    """
    source_path = Path(storage.normalize_local_path(source_path_value))
    if not source_path.exists() or not source_path.is_file():
        raise FileNotFoundError(f"Selected stem audio file not found: {source_path_value}")

    uploads_dir = Path(storage.normalize_local_path(settings.UPLOAD_DIR if hasattr(settings, 'UPLOAD_DIR') else "uploads"))
    stem_upload_dir = uploads_dir / "separated" / f"transcription_{transcription.id}"
    stem_upload_dir.mkdir(parents=True, exist_ok=True)

    destination_path = stem_upload_dir / f"{selected_stem}{source_path.suffix or '.wav'}"
    shutil.copy2(source_path, destination_path)

    instrument_type = STEM_TO_ANALYSIS_INSTRUMENT[selected_stem]
    track = db_session.query(models.InstrumentTrack).filter(
        models.InstrumentTrack.transcription_id == transcription.id,
        models.InstrumentTrack.instrument_type == instrument_type,
    ).first()
    if not track:
        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type=instrument_type,
            display_name=INSTRUMENT_DISPLAY_NAMES.get(selected_stem, selected_stem.title()),
        )

    track.stem_audio_path = storage.normalize_local_path(destination_path)
    track.confidence_score = estimate_stem_confidence(storage.normalize_local_path(destination_path))
    track.processing_status = "completed"
    db_session.add(track)

    transcription.separated_audio_file_path = storage.normalize_local_path(destination_path)
    try:
        stem_upload = upload_transcription_artifact(
            transcription,
            str(destination_path),
            folder_name="selected-stem",
        )
        if stem_upload:
            transcription.separated_audio_url = stem_upload["secure_url"]
            transcription.separated_audio_public_id = stem_upload["public_id"]
    except Exception as exc:
        logger.warning(
            "Failed to upload selected stem for transcription %s: %s",
            transcription.id,
            exc,
        )
        raise
    db_session.add(transcription)
    db_session.commit()
    db_session.refresh(track)
    return track


def select_analysis_source(stem_paths: dict[str, str], fallback_path: str) -> str:
    """Compatibility helper for older tests and historical multi-stem paths."""
    for preferred_stem in ("other", "bass", "vocals", "drums"):
        if stem_paths.get(preferred_stem):
            return stem_paths[preferred_stem]
    return fallback_path


def ensure_duration_within_mvp_limit(audio_path: str) -> int | None:
    """Reject songs that are too long for the single-worker Railway MVP."""
    max_duration = getattr(settings, "MAX_SONG_DURATION_SECONDS", 300)
    try:
        duration = audio.librosa.get_duration(path=audio_path)
    except Exception:
        return None

    if duration and duration > max_duration:
        minutes = max_duration // 60
        raise RuntimeError(
            f"This MVP supports songs up to about {minutes} minutes. "
            "Please upload a shorter section for selected-stem processing."
        )
    return int(round(duration)) if duration else None


@celery_app.task(bind=True)
def process_audio_transcription(
    self,
    transcription_id: int,
    detection_sensitivity: str | None = None,
    selected_stem_override: str | None = None,
):
    """
    Process audio transcription asynchronously.

    This task orchestrates the full audio processing pipeline:
    1. Load transcription record
    2. Preprocess audio (if not already done)
    3. Source separation (guitar isolation)
    4. Pitch detection (using Spotify Basic Pitch) [IMPLEMENTED]
    5. Beat/tempo detection (using librosa.beat) [IMPLEMENTED]
    6. Key detection (using librosa chroma) [IMPLEMENTED]
    7. Rhythm analysis (using librosa onset detection) [IMPLEMENTED]
    8. Chord recognition (using librosa chroma + template matching) [IMPLEMENTED]
    9. Update transcription record with results

    Args:
        transcription_id: ID of the transcription to process

    Returns:
        Dict with processing results and status
    """
    db_session = None
    try:
        # Update task state to show progress
        update_task_state(self, state="PROGRESS", meta={"step": "loading_transcription"})

        # Get database session
        db_session = get_db_session()

        # Load transcription record
        transcription = db_session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).first()

        if not transcription:
            raise ValueError(f"Transcription with ID {transcription_id} not found")

        if transcription.is_deleted:
            return {
                "status": transcription.processing_status or "cancelled",
                "transcription_id": transcription_id,
                "message": "Transcription was deleted before processing started",
            }

        selected_stem = (selected_stem_override or transcription.selected_stem or "other").strip().lower()
        if selected_stem not in VALID_SELECTED_STEMS:
            raise ValueError(
                f"selected_stem must be one of: {', '.join(sorted(VALID_SELECTED_STEMS))}"
            )
        if selected_stem != transcription.selected_stem:
            transcription.selected_stem = selected_stem

        analysis_instrument = STEM_TO_ANALYSIS_INSTRUMENT[selected_stem]
        detection_sensitivity = detection_sensitivity or getattr(
            settings,
            "NOTE_DETECTION_SENSITIVITY",
            "normal",
        )
        transcription.processing_status = "processing"
        transcription.queue_position = 0
        transcription.estimated_wait_time = 0
        transcription.processing_error = None
        transcription.warning_message = None
        transcription.can_generate_score = stem_can_generate_score(selected_stem, analysis_instrument)
        transcription.can_play_stem = stem_playback_available(transcription)
        transcription.transcription_attempts = (transcription.transcription_attempts or 0) + 1
        db_session.add(transcription)
        db_session.commit()
        ensure_transcription_not_deleted(transcription)

        existing_selected_track = db_session.query(models.InstrumentTrack).filter(
            models.InstrumentTrack.transcription_id == transcription.id,
            models.InstrumentTrack.instrument_type == analysis_instrument,
        ).first()
        can_reuse_selected_stem = (
            existing_selected_track
            and existing_selected_track.stem_audio_path
            and Path(existing_selected_track.stem_audio_path).exists()
        )

        # Update task state
        update_task_state(self, state="PROGRESS", meta={"step": "preprocessing_audio"})

        # Ensure we have a preprocessed audio file. Existing processed records may
        # no longer have the original upload, but can still be regenerated from
        # the preprocessed WAV.
        audio_file_path = transcription.audio_file_path
        preprocessed_path = transcription.preprocessed_audio_file_path
        if (
            (not preprocessed_path or not os.path.exists(preprocessed_path)) and
            (not audio_file_path or not os.path.exists(audio_file_path)) and
            (transcription.notes_data or transcription.chords_data)
        ):
            update_task_state(self, state="PROGRESS", meta={"step": "regenerating_derived_outputs"})
            generate_derived_outputs(transcription, db_session)
            transcription.is_processed = True
            transcription.processing_error = None
            db_session.add(transcription)
            db_session.commit()
            return {
                "status": "completed",
                "transcription_id": transcription_id,
                "message": "Derived music outputs regenerated from stored analysis"
            }

        if can_reuse_selected_stem:
            preprocessed_path = None
        elif not preprocessed_path or not os.path.exists(preprocessed_path):
            if not audio_file_path or not os.path.exists(audio_file_path):
                raise ValueError(f"Audio file not found: {audio_file_path}")
            # Preprocess the audio
            preprocessed_path = audio.preprocess_audio(audio_file_path)
            # Update transcription record
            transcription.preprocessed_audio_file_path = preprocessed_path
            db_session.add(transcription)
            db_session.commit()

        if preprocessed_path:
            detected_duration = ensure_duration_within_mvp_limit(preprocessed_path)
            if detected_duration is not None:
                transcription.duration = detected_duration
                db_session.add(transcription)
                db_session.commit()
        ensure_transcription_not_deleted(transcription)

        # Update task state
        update_task_state(self, state="PROGRESS", meta={"step": "source_separation"})

        if can_reuse_selected_stem:
            selected_track = existing_selected_track
            separated_path = selected_track.stem_audio_path
            transcription.separated_audio_file_path = separated_path
            transcription.can_play_stem = True
            db_session.add(transcription)
            db_session.commit()
        else:
            sep_temp_dir = tempfile.mkdtemp()
            try:
                selected_stem_path = audio.separate_selected_stem(
                    preprocessed_path,
                    selected_stem,
                    sep_temp_dir,
                )
                selected_track = persist_selected_stem_track(
                    transcription,
                    selected_stem,
                    selected_stem_path,
                    db_session,
                )
                separated_path = selected_track.stem_audio_path
                transcription.can_play_stem = True
                db_session.add(transcription)
                db_session.commit()
            except Exception as e:
                update_task_state(self, state="PROGRESS", meta={"step": "source_separation_failed"})
                logger.exception(
                    "Selected-stem separation failed for transcription %s using stem %s",
                    transcription_id,
                    selected_stem,
                )
                raise RuntimeError(
                    "Could not isolate the selected stem. "
                    "Try a shorter or clearer song section, or choose a different stem."
                ) from e
            finally:
                shutil.rmtree(sep_temp_dir, ignore_errors=True)
        db_session.refresh(transcription)
        ensure_transcription_not_deleted(transcription)

        # Update task state
        update_task_state(self, state="PROGRESS", meta={"step": "pitch_detection"})

        if analysis_instrument in TRACK_REPROCESS_INSTRUMENTS:
            generate_single_track_transcription_output(
                selected_track,
                db_session,
                clear_existing=True,
                detection_sensitivity=detection_sensitivity,
                selected_stem=selected_stem,
            )
            db_session.refresh(selected_track)

            transcription.notes_data = selected_track.notes_json
            transcription.tablature_data = selected_track.tab_json
            transcription.notation_data = selected_track.notation_json
            if selected_track.processing_status == "failed":
                transcription.processing_error = (
                    selected_track.confidence_notes
                    or "Selected stem analysis failed."
                )
                db_session.add(transcription)
                db_session.commit()
                raise RuntimeError(transcription.processing_error)
            if selected_track.processing_status == "completed_with_warning":
                set_transcription_warning(
                    transcription,
                    selected_track.confidence_notes or NO_NOTES_WARNING,
                    can_generate_score=False,
                )
                transcription.midi_file_path = None
                transcription.midi_file_url = None
                transcription.midi_file_public_id = None
                transcription.tab_file_path = None
                transcription.tab_file_url = None
                transcription.tab_file_public_id = None

            if has_note_events(transcription.notes_data):
                transcription.can_generate_score = True
                try:
                    midi_file_path = midi.save_midi_from_transcription(
                        transcription.notes_data,
                        transcription.id,
                        settings.UPLOAD_DIR if hasattr(settings, 'UPLOAD_DIR') else "uploads"
                    )
                    transcription.midi_file_path = midi_file_path
                    midi_upload = upload_transcription_artifact(
                        transcription,
                        midi_file_path,
                        folder_name="exports",
                    )
                    if midi_upload:
                        transcription.midi_file_url = midi_upload["secure_url"]
                        transcription.midi_file_public_id = midi_upload["public_id"]
                    if not transcription.notation_data:
                        transcription.notation_data = midi.midi_to_musicxml(midi_file_path)
                except Exception as midi_e:
                    print(f"Failed to generate MIDI for transcription {transcription.id}: {str(midi_e)}")

                if analysis_instrument in TAB_TRANSCRIPTION_INSTRUMENTS:
                    try:
                        tablature.save_tablature_from_transcription(
                            transcription.notes_data,
                            transcription.id,
                            settings.UPLOAD_DIR if hasattr(settings, 'UPLOAD_DIR') else "uploads"
                        )
                        transcription.tablature_data = json.dumps(
                            tablature.notes_to_tablature(
                                transcription.notes_data,
                                instrument_type=analysis_instrument,
                            )
                        )
                        transcription.tab_file_path = save_ascii_tab_artifact(
                            transcription,
                            transcription.tablature_data,
                            settings.UPLOAD_DIR if hasattr(settings, 'UPLOAD_DIR') else "uploads",
                        )
                        tab_upload = upload_transcription_artifact(
                            transcription,
                            transcription.tab_file_path,
                            folder_name="exports",
                        )
                        if tab_upload:
                            transcription.tab_file_url = tab_upload["secure_url"]
                            transcription.tab_file_public_id = tab_upload["public_id"]
                    except Exception as tab_e:
                        print(f"Failed to generate tablature for transcription {transcription.id}: {str(tab_e)}")

            db_session.add(transcription)
            db_session.commit()
        else:
            transcription.notes_data = json.dumps({
                "notes": [],
                "message": (
                    "Selected vocal stem was saved. MIDI/TAB generation for vocals "
                    "is not enabled in this MVP yet."
                ),
            })
            set_transcription_warning(
                transcription,
                UNSUPPORTED_STEM_WARNING,
                can_generate_score=False,
            )
            db_session.add(transcription)
            db_session.commit()

        # Update task state
        update_task_state(self, state="PROGRESS", meta={"step": "beat_tempo_detection"})

        # Detect beat and tempo from the separated audio
        try:
            beat_result = audio.detect_beat_and_tempo(separated_path)
            # Update transcription record with tempo data
            transcription.detected_tempo = int(round(beat_result["tempo"]))
            transcription.tempo_confidence = beat_result.get("tempo_confidence", 0)
            db_session.add(transcription)
            db_session.commit()
        except Exception as e:
            # If beat/tempo detection fails, we'll continue without setting tempo
            update_task_state(self, state="PROGRESS", meta={"step": "beat_tempo_detection_failed"})
            # Leave detected_tempo as None (already initialized as such)

        # Update task state
        update_task_state(self, state="PROGRESS", meta={"step": "key_detection"})

        # Detect musical key from the separated audio
        try:
            key_result = audio.detect_key(separated_path)
            # Update transcription record with key data
            transcription.detected_key = key_result["key"]
            transcription.key_confidence = key_result.get("confidence", 0)
            db_session.add(transcription)
            db_session.commit()
        except Exception as e:
            # If key detection fails, we'll continue without setting key
            update_task_state(self, state="PROGRESS", meta={"step": "key_detection_failed"})
            # Leave detected_key as None (already initialized as such)

        # Update task state
        update_task_state(self, state="PROGRESS", meta={"step": "rhythm_analysis"})

        # Detect rhythm information (onsets, durations) from the separated audio
        try:
            rhythm_result = audio.detect_rhythm(separated_path)
            # Store rhythm data in the transcription by enhancing notes_data with rhythm information
            # or by storing it in a structured way that doesn't conflict with existing usage

            # Get existing notes data if any
            existing_notes = {}
            if transcription.notes_data:
                try:
                    existing_notes = json.loads(transcription.notes_data)
                except json.JSONDecodeError:
                    existing_notes = {}

            # Create enhanced notes data that includes both pitch and rhythm information
            enhanced_notes_data = {
                "pitch_info": existing_notes.get("notes", existing_notes if isinstance(existing_notes, list) and len(existing_notes) > 0 and isinstance(existing_notes[0], dict) and "pitch" in existing_notes[0] else []),
                "rhythm_analysis": rhythm_result,
                "analysis_timestamp": datetime.now().isoformat() if 'datetime' in globals() else None
            }
            if isinstance(existing_notes, dict) and existing_notes.get("error"):
                enhanced_notes_data["error"] = existing_notes["error"]

            # If existing notes data had a different structure, preserve it
            if "notes" in existing_notes and isinstance(existing_notes["notes"], list):
                enhanced_notes_data["pitch_info"] = existing_notes["notes"]
            elif isinstance(existing_notes, list) and len(existing_notes) > 0 and isinstance(existing_notes[0], dict) and "pitch" in existing_notes[0]:
                enhanced_notes_data["pitch_info"] = existing_notes

            # Update transcription record with enhanced notes data
            transcription.notes_data = json.dumps(enhanced_notes_data)

            # Store audio duration
            if rhythm_result.get("total_duration") is not None:
                transcription.duration = int(round(rhythm_result["total_duration"]))

            db_session.add(transcription)
            db_session.commit()
        except Exception as e:
            # If rhythm detection fails, we'll continue with existing notes data
            update_task_state(self, state="PROGRESS", meta={"step": "rhythm_analysis_failed"})
            # Continue processing without updating notes data for rhythm

        # Update task state
        update_task_state(self, state="PROGRESS", meta={"step": "chord_recognition"})

        # Detect chords from the separated audio
        try:
            chord_result = audio.detect_chords(separated_path)
            # Update transcription record with chord data
            transcription.chords_data = json.dumps(chord_result)
            db_session.add(transcription)
            db_session.commit()

            # Generate chord charts from the detected chords
            try:
                chord_chart_json = chord_chart.chord_data_to_chord_chart_json(
                    transcription.chords_data
                )
                transcription.chord_chart_data = chord_chart_json
                db_session.add(transcription)
                db_session.commit()
            except Exception as chart_e:
                # Log the error but don't fail the chord detection step
                print(f"Failed to generate chord charts for transcription {transcription.id}: {str(chart_e)}")
                # Leave chord_chart_data as None
        except Exception as e:
            # If chord detection fails, we'll continue without setting chord data
            update_task_state(self, state="PROGRESS", meta={"step": "chord_recognition_failed"})
            # Set empty chords data to avoid None
            transcription.chords_data = json.dumps({})
            db_session.add(transcription)
            db_session.commit()

        # Update task state
        update_task_state(self, state="PROGRESS", meta={"step": "completing_processing"})
        db_session.refresh(transcription)
        ensure_transcription_not_deleted(transcription)

        # Mark as processed (placeholder - actual implementation will come later)
        transcription.is_processed = True
        transcription.processing_status = (
            "completed_with_warning"
            if transcription.warning_message and not transcription.can_generate_score
            else "completed"
        )
        transcription.queue_position = None
        transcription.estimated_wait_time = None
        transcription.can_play_stem = stem_playback_available(transcription)
        transcription.can_generate_score = bool(
            stem_can_generate_score(selected_stem, analysis_instrument)
            and has_note_events(transcription.notes_data)
        )
        if has_note_events(transcription.notes_data) or transcription.warning_message:
            transcription.processing_error = None

        # Placeholder results for other data types - will be replaced with actual processing in subsequent tasks
        # Note: We don't overwrite notes_data, detected_tempo, or detected_key as they have been set by implemented steps
        # We also don't overwrite chords_data as it was set in the chord detection step

        db_session.add(transcription)
        db_session.commit()
        db_session.refresh(transcription)
        cleanup_transient_audio_files(transcription, db_session)

        return {
            "status": "completed",
            "warning": transcription.warning_message,
            "transcription_id": transcription_id,
            "selected_stem": selected_stem,
            "can_play_stem": transcription.can_play_stem,
            "can_generate_score": transcription.can_generate_score,
            "message": "Audio processing completed successfully"
        }

    except Exception as e:
        # Handle errors
        if db_session:
            try:
                transcription = db_session.query(models.Transcription).filter(
                    models.Transcription.id == transcription_id
                ).first()
                if transcription:
                    if transcription.is_deleted:
                        transcription.processing_status = "cancelled"
                        transcription.processing_error = (
                            transcription.processing_error
                            or "Transcription was deleted before processing completed."
                        )
                    else:
                        transcription.is_processed = False
                        transcription.processing_status = "failed"
                        transcription.processing_error = str(e)
                    transcription.queue_position = None
                    transcription.estimated_wait_time = None
                    db_session.add(transcription)
                    db_session.commit()
                    cleanup_transient_audio_files(transcription, db_session)
            except Exception:
                pass  # Don't let error handling obscure the original error

        # Update task state to show failure
        update_task_state(
            self,
            state="FAILURE",
            meta={"exc_type": type(e).__name__, "exc_message": str(e)}
        )

        # Re-raise so Celery records the failure
        raise

    finally:
        if db_session:
            db_session.close()


@celery_app.task(bind=True)
def reprocess_instrument_track(self, track_id: int):
    """Regenerate analysis output for one retained guitar or bass stem."""
    db_session = None
    try:
        update_task_state(self, state="PROGRESS", meta={"step": "loading_instrument_track"})
        db_session = get_db_session()
        track = db_session.query(models.InstrumentTrack).filter(
            models.InstrumentTrack.id == track_id
        ).first()

        if not track:
            raise ValueError(f"Instrument track with ID {track_id} not found")

        update_task_state(self, state="PROGRESS", meta={"step": "reprocessing_instrument_track"})
        generate_single_track_transcription_output(
            track,
            db_session,
            clear_existing=True,
        )
        db_session.refresh(track)

        return {
            "status": track.processing_status,
            "track_id": track_id,
            "transcription_id": track.transcription_id,
            "message": "Instrument track reprocessing finished",
        }
    except Exception as e:
        if db_session:
            try:
                track = db_session.query(models.InstrumentTrack).filter(
                    models.InstrumentTrack.id == track_id
                ).first()
                if track:
                    track.processing_status = "failed"
                    track.confidence_notes = str(e)
                    db_session.add(track)
                    db_session.commit()
            except Exception:
                pass

        update_task_state(
            self,
            state="FAILURE",
            meta={"exc_type": type(e).__name__, "exc_message": str(e)}
        )
        raise
    finally:
        if db_session:
            db_session.close()


# Health check task for monitoring
@celery_app.task
def health_check():
    """Simple health check task for monitoring Celery worker status."""
    return {"status": "healthy", "worker": "audio_processing"}
