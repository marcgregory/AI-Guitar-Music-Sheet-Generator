from celery import current_task
from app.celery import celery_app
from app.core.config import settings
from app import db, models
from app.services import audio
from app.services import midi
from app.services import tablature
from app.services import chord_chart
import json
import os
import shutil
import tempfile
from pathlib import Path
from sqlalchemy.orm import Session
from typing import Dict, Any
from datetime import datetime


INSTRUMENT_DISPLAY_NAMES = {
    "guitar": "Guitar",
    "bass": "Bass",
    "drums": "Drums",
    "vocals": "Vocals",
    "piano": "Piano",
    "other": "Other",
}

TAB_TRANSCRIPTION_INSTRUMENTS = ("guitar", "bass")
STAFF_NOTATION_INSTRUMENTS = ("piano",)
DRUM_RHYTHM_INSTRUMENTS = ("drums",)
NOTE_TRANSCRIPTION_INSTRUMENTS = TAB_TRANSCRIPTION_INSTRUMENTS + STAFF_NOTATION_INSTRUMENTS
TRACK_REPROCESS_INSTRUMENTS = NOTE_TRANSCRIPTION_INSTRUMENTS + DRUM_RHYTHM_INSTRUMENTS


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


def generate_single_track_transcription_output(
    track: models.InstrumentTrack,
    db_session: Session,
    *,
    clear_existing: bool = False,
) -> models.InstrumentTrack:
    """Generate notes/rhythm, tab data, and notation for one supported instrument track."""
    if track.instrument_type not in TRACK_REPROCESS_INSTRUMENTS:
        track.processing_status = "failed"
        track.confidence_notes = (
            "Single-track reprocessing currently supports guitar, bass, piano, and drum tracks."
        )
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
                raise RuntimeError("Drum rhythm analysis completed but found no usable hits")

            track.notes_json = json.dumps(drum_result)
            track.tab_json = None
            track.notation_json = None
            track.confidence_score = average_drum_hit_confidence(drum_result)
            track.confidence_notes = None
            track.processing_status = "completed"
        else:
            pitch_result = audio.detect_pitch(track.stem_audio_path, pitch_temp_dir)
            if not has_note_events(pitch_result):
                raise RuntimeError("Pitch detection completed but found no usable note events")

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
    """Delete stored audio artifacts once analysis data has been persisted."""
    path_fields = [
        "audio_file_path",
        "preprocessed_audio_file_path",
    ]
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
    uploads_dir = Path(settings.UPLOAD_DIR if hasattr(settings, 'UPLOAD_DIR') else "uploads")
    stem_upload_dir = uploads_dir / "separated" / f"transcription_{transcription.id}"
    stem_upload_dir.mkdir(parents=True, exist_ok=True)

    persisted_paths = {}
    for instrument_type, source_path_value in stem_paths.items():
        source_path = Path(source_path_value)
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

        track.stem_audio_path = str(destination_path)
        track.confidence_score = estimate_stem_confidence(str(destination_path))
        track.processing_status = "completed"
        db_session.add(track)
        persisted_paths[instrument_type] = str(destination_path)

    db_session.commit()
    return persisted_paths


def select_analysis_source(stem_paths: dict[str, str], fallback_path: str) -> str:
    """Choose the best source for the existing global transcription pipeline."""
    for preferred_stem in ("guitar", "other", "bass", "piano", "vocals", "drums"):
        if stem_paths.get(preferred_stem):
            return stem_paths[preferred_stem]
    return fallback_path


@celery_app.task(bind=True)
def process_audio_transcription(self, transcription_id: int):
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

        if not preprocessed_path or not os.path.exists(preprocessed_path):
            if not audio_file_path or not os.path.exists(audio_file_path):
                raise ValueError(f"Audio file not found: {audio_file_path}")
            # Preprocess the audio
            preprocessed_path = audio.preprocess_audio(audio_file_path)
            # Update transcription record
            transcription.preprocessed_audio_file_path = preprocessed_path
            db_session.add(transcription)
            db_session.commit()

        # Update task state
        update_task_state(self, state="PROGRESS", meta={"step": "source_separation"})

        # Separate audio sources and persist available broad instrument stems.
        # If separation is unavailable in local dev, continue with the full mix.
        sep_temp_dir = tempfile.mkdtemp()
        try:
            separated_stems = audio.separate_sources_multi(preprocessed_path, sep_temp_dir)
            persisted_stems = copy_and_persist_instrument_tracks(
                transcription,
                separated_stems,
                db_session,
            )
            if not persisted_stems:
                raise RuntimeError("Source separation completed but no instrument stems were saved")
            generate_track_transcription_outputs(transcription.id, db_session)
            separated_path = select_analysis_source(persisted_stems, preprocessed_path)
            transcription.separated_audio_file_path = (
                separated_path if separated_path != preprocessed_path else None
            )
            db_session.add(transcription)
            db_session.commit()
        except Exception as e:
            update_task_state(self, state="PROGRESS", meta={"step": "source_separation_failed"})
            print(
                "Source separation failed; continuing with preprocessed full mix: "
                f"{str(e)}"
            )
            separated_path = preprocessed_path
            transcription.separated_audio_file_path = None
            transcription.processing_error = (
                "Source separation unavailable; processed the full mix instead. "
                f"Details: {str(e)}"
            )
            db_session.add(transcription)
            db_session.commit()
        finally:
            # Clean up the temporary directory
            shutil.rmtree(sep_temp_dir)

        # Update task state
        update_task_state(self, state="PROGRESS", meta={"step": "pitch_detection"})

        # Detect pitch (notes) from the separated audio
        # Create a temporary directory for pitch detection output
        pitch_temp_dir = tempfile.mkdtemp()
        try:
            pitch_result = audio.detect_pitch(separated_path, pitch_temp_dir)
            if not has_note_events(pitch_result):
                raise RuntimeError("Pitch detection completed but found no usable note events")

            # Update transcription record with pitch data
            transcription.notes_data = json.dumps(pitch_result)
            # Generate MIDI file from the pitch data
            try:
                midi_file_path = midi.save_midi_from_transcription(
                    transcription.notes_data,
                    transcription.id,
                    settings.UPLOAD_DIR if hasattr(settings, 'UPLOAD_DIR') else "uploads"
                )
                transcription.midi_file_path = midi_file_path
                # Generate MusicXML from the MIDI file
                try:
                    musicxml_string = midi.midi_to_musicxml(midi_file_path)
                    transcription.notation_data = musicxml_string
                except Exception as xml_e:
                    # Log the error but don't fail the pitch detection step
                    print(f"Failed to generate MusicXML for transcription {transcription.id}: {str(xml_e)}")
                    # Leave notation_data as None
            except Exception as midi_e:
                # Log the error but don't fail the pitch detection step
                # We'll just leave midi_file_path as None
                print(f"Failed to generate MIDI for transcription {transcription.id}: {str(midi_e)}")
            # Generate tablature from the pitch data
            try:
                tab_file_path = tablature.save_tablature_from_transcription(
                    transcription.notes_data,
                    transcription.id,
                    settings.UPLOAD_DIR if hasattr(settings, 'UPLOAD_DIR') else "uploads"
                )
                # We are storing the tablature data in the database field, not the file path
                # But we can also store the file path if we want. However, the model has a tablature_data field for JSON.
                # Let's generate the tablature data and store it in the tablature_data field.
                tablature_data = tablature.notes_to_tablature(transcription.notes_data)
                transcription.tablature_data = json.dumps(tablature_data)
            except Exception as tab_e:
                # Log the error but don't fail the pitch detection step
                print(f"Failed to generate tablature for transcription {transcription.id}: {str(tab_e)}")
                # Leave tablature_data as None
            db_session.add(transcription)
            db_session.commit()
        except Exception as e:
            update_task_state(self, state="PROGRESS", meta={"step": "pitch_detection_failed"})
            transcription.notes_data = json.dumps({"notes": [], "error": str(e)})
            transcription.processing_error = f"Pitch detection failed: {str(e)}"
            db_session.add(transcription)
            db_session.commit()
        finally:
            # Clean up the temporary directory
            shutil.rmtree(pitch_temp_dir)

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

        # Mark as processed (placeholder - actual implementation will come later)
        transcription.is_processed = True
        if has_note_events(transcription.notes_data):
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
            "transcription_id": transcription_id,
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
                    transcription.is_processed = False
                    transcription.processing_error = str(e)
                    db_session.add(transcription)
                    db_session.commit()
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
