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
import urllib.request
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
PLAYBACK_ONLY_INSTRUMENTS = ("vocals",)
NO_NOTES_WARNING = "No note events detected for this stem."
UNSUPPORTED_STEM_WARNING = (
    "Stem separated successfully, but notation generation is not supported for this stem in the MVP."
)
STEM_READY_MESSAGE = "Stem is ready. Listen first, then generate tabs if the stem sounds useful."

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


def stem_available_exports(selected_stem: str, has_notes: bool) -> list[str]:
    if selected_stem in {"other", "bass"} and has_notes:
        return ["tab", "midi", "musicxml"]
    return []


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


def set_transcription_stem_ready(transcription, track: models.InstrumentTrack | None = None) -> None:
    transcription.processing_status = "stem_ready"
    transcription.is_processed = True
    transcription.processing_error = None
    transcription.warning_message = None
    transcription.can_play_stem = True
    transcription.can_generate_score = False
    transcription.queue_position = None
    transcription.estimated_wait_time = None
    transcription.celery_task_id = None
    transcription.notes_data = None
    transcription.chords_data = None
    transcription.tablature_data = None
    transcription.notation_data = None
    transcription.chord_chart_data = None
    transcription.midi_file_path = None
    transcription.midi_file_url = None
    transcription.midi_file_public_id = None
    transcription.tab_file_path = None
    transcription.tab_file_url = None
    transcription.tab_file_public_id = None
    if track:
        track.processing_status = "stem_ready"
        track.notes_json = None
        track.chords_json = None
        track.tab_json = None
        track.notation_json = None
        track.confidence_notes = None


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


def _note_detection_attempt_summary(pitch_result: dict, attempt: int) -> dict:
    model_outputs = pitch_result.get("model_outputs", {}) or {}
    return {
        "attempt": attempt,
        "backend": model_outputs.get("backend"),
        "sensitivity": model_outputs.get("sensitivity"),
        "confidence_threshold": model_outputs.get("confidence_threshold"),
        "total_notes_detected": pitch_result.get("total_notes_detected", len(pitch_result.get("notes", []))),
        "confidence_stats": pitch_result.get("confidence_stats"),
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

            audio_stats = audio.audio_debug_stats(normalized_stem_path)
            note_detection_attempts = []

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
            note_detection_attempts.append(_note_detection_attempt_summary(pitch_result, 1))
            pitch_result["audio_debug_stats"] = audio_stats
            pitch_result["note_detection_attempts"] = note_detection_attempts
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
                fallback_result = audio.detect_pitch(
                    normalized_stem_path,
                    pitch_temp_dir,
                    sensitivity="high",
                )
                note_detection_attempts.append(_note_detection_attempt_summary(fallback_result, 2))
                fallback_result["audio_debug_stats"] = audio_stats
                fallback_result["note_detection_attempts"] = note_detection_attempts
                pitch_result = fallback_result
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


def sync_selected_track_to_transcription(
    transcription: models.Transcription,
    track: models.InstrumentTrack,
    db_session: Session,
) -> None:
    selected_stem = (transcription.selected_stem or "other").lower()
    analysis_instrument = STEM_TO_ANALYSIS_INSTRUMENT.get(selected_stem)
    if analysis_instrument != track.instrument_type:
        return

    transcription.notes_data = track.notes_json
    transcription.chords_data = track.chords_json
    transcription.tablature_data = track.tab_json
    transcription.notation_data = track.notation_json
    transcription.processing_error = None
    transcription.can_play_stem = stem_playback_available(transcription)
    transcription.can_generate_score = bool(
        stem_can_generate_score(selected_stem, track.instrument_type)
        and has_note_events(track.notes_json)
    )

    if track.processing_status == "completed_with_warning":
        transcription.warning_message = track.confidence_notes or NO_NOTES_WARNING
    elif track.instrument_type == "vocals":
        transcription.warning_message = UNSUPPORTED_STEM_WARNING
    else:
        transcription.warning_message = None

    if not transcription.can_generate_score:
        transcription.midi_file_path = None
        transcription.midi_file_url = None
        transcription.midi_file_public_id = None
        transcription.tab_file_path = None
        transcription.tab_file_url = None
        transcription.tab_file_public_id = None

    transcription.is_processed = True
    transcription.processing_status = (
        "completed_with_warning"
        if transcription.warning_message and not transcription.can_generate_score
        else "completed"
    )
    db_session.add(transcription)
    db_session.commit()


def ensure_local_separated_stem(
    transcription: models.Transcription,
    selected_stem: str,
) -> str:
    if transcription.separated_audio_file_path:
        local_path = Path(storage.normalize_local_path(transcription.separated_audio_file_path))
        if local_path.exists() and local_path.is_file():
            return storage.normalize_local_path(local_path)

    if not transcription.separated_audio_url:
        raise FileNotFoundError("Separated stem is missing. Run stem separation before generating tabs.")

    uploads_dir = Path(storage.normalize_local_path(settings.UPLOAD_DIR if hasattr(settings, 'UPLOAD_DIR') else "uploads"))
    stem_upload_dir = uploads_dir / "separated" / f"transcription_{transcription.id}"
    stem_upload_dir.mkdir(parents=True, exist_ok=True)
    destination_path = stem_upload_dir / f"{selected_stem}.wav"
    urllib.request.urlretrieve(transcription.separated_audio_url, destination_path)
    transcription.separated_audio_file_path = storage.normalize_local_path(destination_path)
    return transcription.separated_audio_file_path


def generate_tab_outputs_for_transcription(
    transcription: models.Transcription,
    db_session: Session,
    *,
    detection_sensitivity: str = "normal",
) -> None:
    selected_stem = (transcription.selected_stem or "other").strip().lower()
    if selected_stem not in VALID_SELECTED_STEMS:
        raise ValueError(f"selected_stem must be one of: {', '.join(sorted(VALID_SELECTED_STEMS))}")
    if selected_stem == "vocals":
        raise ValueError("Vocal stems are playback-only in this MVP.")

    analysis_instrument = STEM_TO_ANALYSIS_INSTRUMENT[selected_stem]
    separated_path = ensure_local_separated_stem(transcription, selected_stem)
    track = db_session.query(models.InstrumentTrack).filter(
        models.InstrumentTrack.transcription_id == transcription.id,
        models.InstrumentTrack.instrument_type == analysis_instrument,
    ).first()
    if not track:
        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type=analysis_instrument,
            display_name=INSTRUMENT_DISPLAY_NAMES.get(selected_stem, selected_stem.title()),
        )
    track.stem_audio_path = separated_path
    db_session.add(track)
    db_session.commit()

    generate_single_track_transcription_output(
        track,
        db_session,
        clear_existing=True,
        detection_sensitivity=detection_sensitivity,
        selected_stem=selected_stem,
    )
    db_session.refresh(track)

    transcription.notes_data = track.notes_json
    transcription.tablature_data = track.tab_json
    transcription.notation_data = track.notation_json
    transcription.chords_data = track.chords_json
    transcription.can_play_stem = stem_playback_available(transcription)

    if track.processing_status == "failed":
        raise RuntimeError(track.confidence_notes or "Selected stem analysis failed.")

    if track.processing_status == "completed_with_warning":
        set_transcription_warning(
            transcription,
            track.confidence_notes or (
                "No drum hits detected for this stem." if selected_stem == "drums" else NO_NOTES_WARNING
            ),
            can_generate_score=False,
        )

    if selected_stem in {"other", "bass"} and has_note_events(transcription.notes_data):
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
    elif selected_stem == "drums" and has_drum_hits(transcription.notes_data):
        transcription.can_generate_score = False
        transcription.warning_message = None
    else:
        transcription.can_generate_score = False
        transcription.midi_file_path = None
        transcription.midi_file_url = None
        transcription.midi_file_public_id = None
        transcription.tab_file_path = None
        transcription.tab_file_url = None
        transcription.tab_file_public_id = None

    try:
        beat_result = audio.detect_beat_and_tempo(separated_path)
        transcription.detected_tempo = int(round(beat_result["tempo"]))
        transcription.tempo_confidence = beat_result.get("tempo_confidence", 0)
    except Exception:
        pass

    try:
        key_result = audio.detect_key(separated_path)
        transcription.detected_key = key_result["key"]
        transcription.key_confidence = key_result.get("confidence", 0)
    except Exception:
        pass

    if selected_stem != "drums":
        try:
            rhythm_result = audio.detect_rhythm(separated_path)
            existing_notes = json.loads(transcription.notes_data) if transcription.notes_data else {}
            pitch_info = []
            if isinstance(existing_notes, dict):
                pitch_info = existing_notes.get("notes", [])
            elif isinstance(existing_notes, list):
                pitch_info = existing_notes
            enhanced_notes_data = {
                "pitch_info": pitch_info,
                "rhythm_analysis": rhythm_result,
                "analysis_timestamp": datetime.now().isoformat(),
            }
            if isinstance(existing_notes, dict) and existing_notes.get("error"):
                enhanced_notes_data["error"] = existing_notes["error"]
            transcription.notes_data = json.dumps(enhanced_notes_data)
            track.notes_json = transcription.notes_data
            if rhythm_result.get("total_duration") is not None:
                transcription.duration = int(round(rhythm_result["total_duration"]))
        except Exception:
            pass

    if selected_stem in {"other", "bass"}:
        try:
            chord_result = audio.detect_chords(separated_path)
            transcription.chords_data = json.dumps(chord_result)
            track.chords_json = transcription.chords_data
            try:
                transcription.chord_chart_data = chord_chart.chord_data_to_chord_chart_json(
                    transcription.chords_data
                )
            except Exception as chart_e:
                print(f"Failed to generate chord charts for transcription {transcription.id}: {str(chart_e)}")
        except Exception:
            transcription.chords_data = json.dumps({})
    else:
        transcription.chords_data = json.dumps({})
        transcription.chord_chart_data = None

    transcription.is_processed = True
    transcription.processing_status = (
        "completed_with_warning"
        if transcription.warning_message and not transcription.can_generate_score
        else "completed"
    )
    transcription.processing_error = None
    transcription.queue_position = None
    transcription.estimated_wait_time = None
    transcription.celery_task_id = None
    transcription.can_play_stem = stem_playback_available(transcription)
    transcription.can_generate_score = bool(
        stem_can_generate_score(selected_stem, analysis_instrument)
        and has_note_events(transcription.notes_data)
    )
    db_session.add(track)
    db_session.add(transcription)
    db_session.commit()


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


def task_request_id(task) -> str:
    request = getattr(task, "request", None)
    task_id = getattr(request, "id", None)
    return str(task_id) if task_id else "local"


def transcription_temp_dir(transcription_id: int, task_id: str | None = None) -> Path:
    safe_task_id = re_safe_task_id(task_id or "local")
    root = Path(tempfile.gettempdir()) / "transcriptions" / str(transcription_id)
    path = root / safe_task_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def re_safe_task_id(task_id: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in task_id)


def file_debug_snapshot(path_value: str | None) -> dict:
    if not path_value:
        return {"path": None, "exists": False}
    path = Path(storage.normalize_local_path(path_value))
    snapshot = {"path": storage.normalize_local_path(path), "exists": path.exists()}
    if path.exists():
        try:
            stat = path.stat()
            snapshot.update({
                "is_file": path.is_file(),
                "size": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        except OSError as exc:
            snapshot["stat_error"] = str(exc)
    return snapshot


def directory_debug_listing(path_value: str | Path | None, *, limit: int = 200) -> list[dict]:
    if not path_value:
        return []
    root = Path(storage.normalize_local_path(path_value))
    if not root.exists():
        return [{"path": storage.normalize_local_path(root), "exists": False}]

    entries = []
    for path in list(root.rglob("*"))[:limit]:
        item = {"path": storage.normalize_local_path(path), "is_file": path.is_file()}
        if path.is_file():
            try:
                item["size"] = path.stat().st_size
            except OSError as exc:
                item["stat_error"] = str(exc)
        entries.append(item)
    return entries


def log_file_lifecycle(transcription_id: int, task_id: str, event: str, **details) -> None:
    logger.info(
        "Transcription file lifecycle: transcription_id=%s task_id=%s event=%s details=%s",
        transcription_id,
        task_id,
        event,
        details,
    )


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
    task_id = getattr(transcription, "celery_task_id", None) or "local"
    if (
        transcription.processing_status
        and transcription.processing_status not in {"stem_ready", "completed", "completed_with_warning"}
    ):
        logger.info(
            "Skipping transient cleanup for transcription %s because status is %s",
            transcription.id,
            transcription.processing_status,
        )
        return

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
            path = Path(storage.normalize_local_path(path_value))
            log_file_lifecycle(
                transcription.id,
                task_id,
                "cleanup_before_delete",
                field=field_name,
                file=file_debug_snapshot(str(path)),
            )
            if path.exists() and path.is_file():
                path.unlink()
                log_file_lifecycle(
                    transcription.id,
                    task_id,
                    "cleanup_deleted",
                    field=field_name,
                    path=storage.normalize_local_path(path),
                )
        except OSError as cleanup_error:
            logger.warning(
                "Failed to delete %s for transcription %s: %s",
                field_name,
                transcription.id,
                cleanup_error,
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
        logger.error(
            "Demucs selected stem disappeared before persistence for transcription %s: %s",
            transcription.id,
            file_debug_snapshot(source_path_value),
        )
        raise FileNotFoundError(f"Selected stem audio file not found: {source_path_value}")

    uploads_dir = Path(storage.normalize_local_path(settings.UPLOAD_DIR if hasattr(settings, 'UPLOAD_DIR') else "uploads"))
    stem_upload_dir = uploads_dir / "separated" / f"transcription_{transcription.id}"
    stem_upload_dir.mkdir(parents=True, exist_ok=True)

    destination_path = stem_upload_dir / f"{selected_stem}{source_path.suffix or '.wav'}"
    logger.info(
        "Persisting selected stem for transcription %s stem=%s source=%s destination=%s",
        transcription.id,
        selected_stem,
        file_debug_snapshot(str(source_path)),
        storage.normalize_local_path(destination_path),
    )
    shutil.copy2(source_path, destination_path)
    if not destination_path.exists() or not destination_path.is_file():
        logger.error(
            "Selected stem copy disappeared before upload for transcription %s: %s",
            transcription.id,
            file_debug_snapshot(str(destination_path)),
        )
        raise FileNotFoundError(
            f"Selected stem copy disappeared before upload: {destination_path}"
        )

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
        logger.info(
            "Uploading selected stem for transcription %s stem=%s file=%s",
            transcription.id,
            selected_stem,
            file_debug_snapshot(str(destination_path)),
        )
        stem_upload = upload_transcription_artifact(
            transcription,
            str(destination_path),
            folder_name="selected-stem",
        )
        if stem_upload:
            transcription.separated_audio_url = stem_upload["secure_url"]
            transcription.separated_audio_public_id = stem_upload["public_id"]
        logger.info(
            "Selected stem upload complete for transcription %s stem=%s uploaded=%s",
            transcription.id,
            selected_stem,
            bool(stem_upload),
        )
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
    task_id = task_request_id(self)
    job_temp_dir = transcription_temp_dir(transcription_id, task_id)
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

        log_file_lifecycle(
            transcription_id,
            task_id,
            "task_loaded",
            temp_dir=storage.normalize_local_path(job_temp_dir),
            audio_file=file_debug_snapshot(transcription.audio_file_path),
            preprocessed_file=file_debug_snapshot(transcription.preprocessed_audio_file_path),
            original_audio_url=transcription.original_audio_url,
            separated_audio_url=transcription.separated_audio_url,
        )

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
        log_file_lifecycle(
            transcription_id,
            task_id,
            "before_preprocess",
            audio_file=file_debug_snapshot(audio_file_path),
            preprocessed_file=file_debug_snapshot(preprocessed_path),
        )
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
                logger.error(
                    "Downloaded/source audio disappeared before preprocessing for transcription %s task %s: %s",
                    transcription_id,
                    task_id,
                    file_debug_snapshot(audio_file_path),
                )
                raise ValueError(f"Audio file not found: {audio_file_path}")
            # Preprocess the audio
            preprocessed_output_path = job_temp_dir / "preprocessed.wav"
            preprocessed_path = audio.preprocess_audio(
                audio_file_path,
                storage.normalize_local_path(preprocessed_output_path),
            )
            # Update transcription record
            transcription.preprocessed_audio_file_path = preprocessed_path
            db_session.add(transcription)
            db_session.commit()
            log_file_lifecycle(
                transcription_id,
                task_id,
                "after_preprocess",
                preprocessed_file=file_debug_snapshot(preprocessed_path),
            )

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
            sep_temp_dir = job_temp_dir / "demucs"
            sep_temp_dir.mkdir(parents=True, exist_ok=True)
            try:
                if not preprocessed_path or not Path(storage.normalize_local_path(preprocessed_path)).exists():
                    logger.error(
                        "Preprocessed audio disappeared before Demucs for transcription %s task %s: %s",
                        transcription_id,
                        task_id,
                        file_debug_snapshot(preprocessed_path),
                    )
                    raise FileNotFoundError(
                        f"Preprocessed audio file disappeared before Demucs: {preprocessed_path}"
                    )
                log_file_lifecycle(
                    transcription_id,
                    task_id,
                    "before_demucs",
                    demucs_output_dir=storage.normalize_local_path(sep_temp_dir),
                    preprocessed_file=file_debug_snapshot(preprocessed_path),
                )
                selected_stem_path = audio.separate_selected_stem(
                    preprocessed_path,
                    selected_stem,
                    storage.normalize_local_path(sep_temp_dir),
                )
                log_file_lifecycle(
                    transcription_id,
                    task_id,
                    "after_demucs",
                    selected_stem=selected_stem,
                    selected_stem_file=file_debug_snapshot(selected_stem_path),
                    demucs_listing=directory_debug_listing(sep_temp_dir),
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
                log_file_lifecycle(
                    transcription_id,
                    task_id,
                    "after_selected_stem_persist",
                    separated_file=file_debug_snapshot(separated_path),
                    separated_audio_url=transcription.separated_audio_url,
                    db_committed=True,
                )
            except Exception as e:
                update_task_state(self, state="PROGRESS", meta={"step": "source_separation_failed"})
                logger.exception(
                    "Selected-stem separation failed for transcription %s using stem %s task_id=%s temp_dir=%s demucs_listing=%s",
                    transcription_id,
                    selected_stem,
                    task_id,
                    storage.normalize_local_path(sep_temp_dir),
                    directory_debug_listing(sep_temp_dir),
                )
                raise RuntimeError(
                    "Could not isolate the selected stem. "
                    "Try a shorter or clearer song section, or choose a different stem."
                ) from e
            finally:
                log_file_lifecycle(
                    transcription_id,
                    task_id,
                    "before_demucs_cleanup",
                    demucs_output_dir=storage.normalize_local_path(sep_temp_dir),
                    demucs_listing=directory_debug_listing(sep_temp_dir),
                    separated_file=file_debug_snapshot(
                        locals().get("separated_path")
                    ),
                )
                shutil.rmtree(sep_temp_dir, ignore_errors=True)
                log_file_lifecycle(
                    transcription_id,
                    task_id,
                    "after_demucs_cleanup",
                    demucs_output_dir=storage.normalize_local_path(sep_temp_dir),
                    exists=sep_temp_dir.exists(),
                )
        db_session.refresh(transcription)
        ensure_transcription_not_deleted(transcription)

        set_transcription_stem_ready(transcription, selected_track)
        db_session.add(selected_track)
        db_session.add(transcription)
        db_session.commit()
        db_session.refresh(transcription)
        cleanup_transient_audio_files(transcription, db_session)

        return {
            "status": "stem_ready",
            "warning": None,
            "transcription_id": transcription_id,
            "selected_stem": selected_stem,
            "can_play_stem": transcription.can_play_stem,
            "can_generate_score": False,
            "message": STEM_READY_MESSAGE,
        }

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

        # Detect rhythm information for melodic stems. Drum rhythm data is
        # already the primary selected-stem result and must not be wrapped away.
        if selected_stem == "drums":
            update_task_state(self, state="PROGRESS", meta={"step": "drum_rhythm_preserved"})
        else:
            try:
                rhythm_result = audio.detect_rhythm(separated_path)
                existing_notes = {}
                if transcription.notes_data:
                    try:
                        existing_notes = json.loads(transcription.notes_data)
                    except json.JSONDecodeError:
                        existing_notes = {}

                enhanced_notes_data = {
                    "pitch_info": existing_notes.get(
                        "notes",
                        existing_notes
                        if (
                            isinstance(existing_notes, list)
                            and len(existing_notes) > 0
                            and isinstance(existing_notes[0], dict)
                            and "pitch" in existing_notes[0]
                        )
                        else [],
                    ),
                    "rhythm_analysis": rhythm_result,
                    "analysis_timestamp": datetime.now().isoformat(),
                }
                if isinstance(existing_notes, dict) and existing_notes.get("error"):
                    enhanced_notes_data["error"] = existing_notes["error"]

                if isinstance(existing_notes, dict) and isinstance(existing_notes.get("notes"), list):
                    enhanced_notes_data["pitch_info"] = existing_notes["notes"]
                elif (
                    isinstance(existing_notes, list)
                    and len(existing_notes) > 0
                    and isinstance(existing_notes[0], dict)
                    and "pitch" in existing_notes[0]
                ):
                    enhanced_notes_data["pitch_info"] = existing_notes

                transcription.notes_data = json.dumps(enhanced_notes_data)
                if rhythm_result.get("total_duration") is not None:
                    transcription.duration = int(round(rhythm_result["total_duration"]))

                db_session.add(transcription)
                db_session.commit()
            except Exception:
                update_task_state(self, state="PROGRESS", meta={"step": "rhythm_analysis_failed"})

        # Update task state
        update_task_state(self, state="PROGRESS", meta={"step": "chord_recognition"})

        # Detect chords only for melodic tab-capable selected stems.
        if selected_stem in {"drums", "vocals"}:
            transcription.chords_data = json.dumps({})
            transcription.chord_chart_data = None
            db_session.add(transcription)
            db_session.commit()
        else:
            try:
                chord_result = audio.detect_chords(separated_path)
                transcription.chords_data = json.dumps(chord_result)
                db_session.add(transcription)
                db_session.commit()

                try:
                    chord_chart_json = chord_chart.chord_data_to_chord_chart_json(
                        transcription.chords_data
                    )
                    transcription.chord_chart_data = chord_chart_json
                    db_session.add(transcription)
                    db_session.commit()
                except Exception as chart_e:
                    print(f"Failed to generate chord charts for transcription {transcription.id}: {str(chart_e)}")
            except Exception:
                update_task_state(self, state="PROGRESS", meta={"step": "chord_recognition_failed"})
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
def generate_tab_from_separated_stem(
    self,
    transcription_id: int,
    detection_sensitivity: str | None = None,
):
    """Generate notation outputs from an already separated selected stem."""
    db_session = None
    try:
        update_task_state(self, state="PROGRESS", meta={"step": "loading_stem"})
        db_session = get_db_session()
        transcription = db_session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).first()
        if not transcription:
            raise ValueError(f"Transcription with ID {transcription_id} not found")
        if transcription.is_deleted:
            return {
                "status": transcription.processing_status or "cancelled",
                "transcription_id": transcription_id,
                "message": "Transcription was deleted before tab generation started",
            }

        selected_stem = (transcription.selected_stem or "other").strip().lower()
        if selected_stem == "vocals":
            raise ValueError("Vocal stems are playback-only in this MVP.")
        if not stem_playback_available(transcription):
            raise ValueError("Separated stem is missing. Run stem separation before generating tabs.")

        transcription.processing_status = "processing"
        transcription.processing_error = None
        transcription.warning_message = None
        transcription.can_generate_score = False
        transcription.can_play_stem = True
        transcription.queue_position = 0
        transcription.estimated_wait_time = 0
        db_session.add(transcription)
        db_session.commit()

        update_task_state(self, state="PROGRESS", meta={"step": "tab_generation"})
        generate_tab_outputs_for_transcription(
            transcription,
            db_session,
            detection_sensitivity=detection_sensitivity or getattr(
                settings,
                "NOTE_DETECTION_SENSITIVITY",
                "normal",
            ),
        )
        db_session.refresh(transcription)
        cleanup_transient_audio_files(transcription, db_session)

        return {
            "status": transcription.processing_status,
            "warning": transcription.warning_message,
            "transcription_id": transcription_id,
            "selected_stem": selected_stem,
            "can_play_stem": transcription.can_play_stem,
            "can_generate_score": transcription.can_generate_score,
            "message": "Tab generation completed.",
        }
    except Exception as e:
        if db_session:
            try:
                transcription = db_session.query(models.Transcription).filter(
                    models.Transcription.id == transcription_id
                ).first()
                if transcription:
                    if transcription.is_deleted:
                        transcription.processing_status = "cancelled"
                    else:
                        transcription.processing_status = "failed"
                        transcription.processing_error = str(e)
                        transcription.is_processed = False
                    transcription.queue_position = None
                    transcription.estimated_wait_time = None
                    db_session.add(transcription)
                    db_session.commit()
            except Exception:
                pass

        update_task_state(
            self,
            state="FAILURE",
            meta={"exc_type": type(e).__name__, "exc_message": str(e)},
        )
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
        transcription = db_session.query(models.Transcription).filter(
            models.Transcription.id == track.transcription_id
        ).first()
        if transcription:
            sync_selected_track_to_transcription(transcription, track, db_session)

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
