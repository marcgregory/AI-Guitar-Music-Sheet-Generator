from celery import current_task
from app.celery import celery_app
from app.core.config import settings
from app import db, models
from app.services import audio
import json
import os
from pathlib import Path
from sqlalchemy.orm import Session
from typing import Dict, Any
from datetime import datetime


def get_db_session() -> Session:
    """Create a new database session for Celery tasks."""
    db_session = db.SessionLocal()
    try:
        return db_session
    finally:
        pass  # Caller must close the session


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
        self.update_state(state="PROGRESS", meta={"step": "loading_transcription"})

        # Get database session
        db_session = get_db_session()

        # Load transcription record
        transcription = db_session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).first()

        if not transcription:
            raise ValueError(f"Transcription with ID {transcription_id} not found")

        # Update task state
        self.update_state(state="PROGRESS", meta={"step": "preprocessing_audio"})

        # Ensure we have a preprocessed audio file
        audio_file_path = transcription.audio_file_path
        if not audio_file_path or not os.path.exists(audio_file_path):
            raise ValueError(f"Audio file not found: {audio_file_path}")

        preprocessed_path = transcription.preprocessed_audio_file_path
        if not preprocessed_path or not os.path.exists(preprocessed_path):
            # Preprocess the audio
            preprocessed_path = audio.preprocess_audio(audio_file_path)
            # Update transcription record
            transcription.preprocessed_audio_file_path = preprocessed_path
            db_session.add(transcription)
            db_session.commit()

        # Update task state
        self.update_state(state="PROGRESS", meta={"step": "source_separation"})

        # Separate audio sources to isolate guitar
        try:
            separated_path = audio.separate_sources(preprocessed_path)
            # Update transcription record with separated audio file path
            transcription.separated_audio_file_path = separated_path
            db_session.add(transcription)
            db_session.commit()
        except Exception as e:
            # If source separation fails, continue with preprocessed audio
            # but log the error
            self.update_state(state="PROGRESS", meta={"step": "source_separation_failed"})
            # We'll still continue processing with the preprocessed audio
            separated_path = preprocessed_path

        # Update task state
        self.update_state(state="PROGRESS", meta={"step": "pitch_detection"})

        # Detect pitch (notes) from the separated audio
        try:
            pitch_result = audio.detect_pitch(separated_path)
            # Update transcription record with pitch data
            transcription.notes_data = json.dumps(pitch_result)
            db_session.add(transcription)
            db_session.commit()
        except Exception as e:
            # If pitch detection fails, we'll store an error but continue processing
            self.update_state(state="PROGRESS", meta={"step": "pitch_detection_failed"})
            # Create empty notes data so the transcription can still be processed
            transcription.notes_data = json.dumps({"notes": [], "error": str(e)})
            db_session.add(transcription)
            db_session.commit()

        # Update task state
        self.update_state(state="PROGRESS", meta={"step": "beat_tempo_detection"})

        # Detect beat and tempo from the separated audio
        try:
            beat_result = audio.detect_beat_and_tempo(separated_path)
            # Update transcription record with tempo data
            transcription.detected_tempo = int(round(beat_result["tempo"]))
            db_session.add(transcription)
            db_session.commit()
        except Exception as e:
            # If beat/tempo detection fails, we'll continue without setting tempo
            self.update_state(state="PROGRESS", meta={"step": "beat_tempo_detection_failed"})
            # Leave detected_tempo as None (already initialized as such)

        # Update task state
        self.update_state(state="PROGRESS", meta={"step": "key_detection"})

        # Detect musical key from the separated audio
        try:
            key_result = audio.detect_key(separated_path)
            # Update transcription record with key data
            transcription.detected_key = key_result["key"]
            db_session.add(transcription)
            db_session.commit()
        except Exception as e:
            # If key detection fails, we'll continue without setting key
            self.update_state(state="PROGRESS", meta={"step": "key_detection_failed"})
            # Leave detected_key as None (already initialized as such)

        # Update task state
        self.update_state(state="PROGRESS", meta={"step": "rhythm_analysis"})

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

            # If existing notes data had a different structure, preserve it
            if "notes" in existing_notes and isinstance(existing_notes["notes"], list):
                enhanced_notes_data["pitch_info"] = existing_notes["notes"]
            elif isinstance(existing_notes, list) and len(existing_notes) > 0 and isinstance(existing_notes[0], dict) and "pitch" in existing_notes[0]:
                enhanced_notes_data["pitch_info"] = existing_notes

            # Update transcription record with enhanced notes data
            transcription.notes_data = json.dumps(enhanced_notes_data)
            db_session.add(transcription)
            db_session.commit()
        except Exception as e:
            # If rhythm detection fails, we'll continue with existing notes data
            self.update_state(state="PROGRESS", meta={"step": "rhythm_analysis_failed"})
            # Continue processing without updating notes data for rhythm

        # Update task state
        self.update_state(state="PROGRESS", meta={"step": "chord_recognition"})

        # Detect chords from the separated audio
        try:
            chord_result = audio.detect_chords(separated_path)
            # Update transcription record with chord data
            transcription.chords_data = json.dumps(chord_result)
            db_session.add(transcription)
            db_session.commit()
        except Exception as e:
            # If chord detection fails, we'll continue without setting chord data
            self.update_state(state="PROGRESS", meta={"step": "chord_recognition_failed"})
            # Set empty chords data to avoid None
            transcription.chords_data = json.dumps({})
            db_session.add(transcription)
            db_session.commit()

        # Update task state
        self.update_state(state="PROGRESS", meta={"step": "completing_processing"})

        # Mark as processed (placeholder - actual implementation will come later)
        transcription.is_processed = True
        transcription.processing_error = None

        # Placeholder results for other data types - will be replaced with actual processing in subsequent tasks
        # Note: We don't overwrite notes_data, detected_tempo, or detected_key as they have been set by implemented steps
        # We also don't overwrite chords_data as it was set in the chord detection step
        transcription.tablature_data = json.dumps({"placeholder": "tablature_data"})
        transcription.notation_data = json.dumps({"placeholder": "notation_data"})

        db_session.add(transcription)
        db_session.commit()
        db_session.refresh(transcription)

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
        self.update_state(
            state="FAILURE",
            meta={"exc_type": type(e).__name__, "exc_message": str(e)}
        )

        # Re-raise so Celery records the failure
        raise

    finally:
        if db_session:
            db_session.close()


# Health check task for monitoring
@celery_app.task
def health_check():
    """Simple health check task for monitoring Celery worker status."""
    return {"status": "healthy", "worker": "audio_processing"}