# Database initialization
# Now that SQLAlchemy/Python 3.13 compatibility issues are resolved,
# actual database initialization is implemented

import json
import logging
from pathlib import Path
from sqlalchemy import inspect, text
from .db import Base, SessionLocal, engine
# Import models to ensure they are registered with the Base
from . import models

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db():
    """Initialize the database by creating all tables."""
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    _ensure_transcription_phase1_columns()
    _ensure_project_deletion_columns()
    _seed_demo_transcription()
    logger.info("Database tables created successfully")


def _ensure_transcription_phase1_columns():
    """Lightweight schema compatibility for deployments without Alembic yet."""
    inspector = inspect(engine)
    if "transcriptions" not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"]
        for column in inspector.get_columns("transcriptions")
    }
    required_columns = {
    "selected_stem": "VARCHAR DEFAULT 'other'",
    "processing_status": "VARCHAR DEFAULT 'pending'",
    "queue_position": "INTEGER",
    "estimated_wait_time": "INTEGER",
    "celery_task_id": "VARCHAR",
    "tab_file_path": "VARCHAR",
    "source_type": "VARCHAR",
    "source_url": "TEXT",
    "normalized_source_id": "VARCHAR",
    "audio_hash": "VARCHAR",
    "duplicate_of_id": "INTEGER",
    "is_demo": "BOOLEAN DEFAULT FALSE",
    "is_deleted": "BOOLEAN DEFAULT FALSE",
    "deleted_at": "TIMESTAMP",
    "original_audio_url": "TEXT",
    "original_audio_public_id": "VARCHAR",
    "separated_audio_url": "TEXT",
    "separated_audio_public_id": "VARCHAR",
    "midi_file_url": "TEXT",
    "midi_file_public_id": "VARCHAR",
    "tab_file_url": "TEXT",
    "tab_file_public_id": "VARCHAR",
    "processing_error": "TEXT",
    "warning_message": "TEXT",
    "can_generate_score": "BOOLEAN DEFAULT TRUE",
    "can_play_stem": "BOOLEAN DEFAULT FALSE",
    "transcription_attempts": "INTEGER DEFAULT 0",
}

    with engine.connect() as conn:
        for column_name, ddl_type in required_columns.items():
            if column_name in existing_columns:
                continue
            logger.info("Adding missing transcriptions.%s column", column_name)
            conn.execute(
                text(f"ALTER TABLE transcriptions ADD COLUMN {column_name} {ddl_type}")
            )
        conn.commit()


def _demo_tablature_data() -> dict:
    tab_notes = [
        {"string": 6, "fret": 0, "onset": 0.0, "offset": 0.36, "time": 0.0, "confidence": 0.96},
        {"string": 6, "fret": 3, "onset": 0.5, "offset": 0.86, "time": 0.5, "confidence": 0.95},
        {"string": 5, "fret": 0, "onset": 1.0, "offset": 1.36, "time": 1.0, "confidence": 0.97},
        {"string": 5, "fret": 2, "onset": 1.5, "offset": 1.86, "time": 1.5, "confidence": 0.95},
        {"string": 4, "fret": 0, "onset": 2.0, "offset": 2.36, "time": 2.0, "confidence": 0.94},
        {"string": 5, "fret": 2, "onset": 2.5, "offset": 2.86, "time": 2.5, "confidence": 0.94},
        {"string": 5, "fret": 0, "onset": 3.0, "offset": 3.16, "time": 3.0, "confidence": 0.94},
    ]
    return {
        "strings": ["e", "B", "G", "D", "A", "E"],
        "tuning": [40, 45, 50, 55, 59, 64],
        "measures": [{"beats": tab_notes[:4]}, {"beats": tab_notes[4:]}],
        "tablature": tab_notes,
    }


def _demo_notes_data(tab_data: dict) -> dict:
    tuning = tab_data["tuning"]
    notes = []
    for tab_note in tab_data["tablature"]:
        string_number = int(tab_note["string"])
        pitch = tuning[len(tuning) - string_number] + int(tab_note["fret"])
        notes.append({**tab_note, "pitch": pitch})
    return {"notes": notes, "pitch_info": notes}


def _seed_demo_transcription() -> None:
    """Create one shared example transcription for all users."""
    session = SessionLocal()
    try:
        demo_user = (
            session.query(models.User)
            .filter(models.User.username == "demo-system")
            .first()
        )
        if not demo_user:
            demo_user = models.User(
                email="demo-system@example.local",
                username="demo-system",
                hashed_password="not-used",
                is_active=False,
            )
            session.add(demo_user)
            session.commit()
            session.refresh(demo_user)

        tab_data = _demo_tablature_data()
        notes_data = _demo_notes_data(tab_data)
        chords_data = {
            "chords": [
                {"chord": "E:min", "onset": 0.0, "offset": 1.0, "confidence": 0.82},
                {"chord": "A:min", "onset": 1.0, "offset": 2.0, "confidence": 0.78},
                {"chord": "D:maj", "onset": 2.0, "offset": 3.2, "confidence": 0.74},
            ]
        }
        static_audio_path = Path(__file__).resolve().parent / "static" / "demo_guitar_riff.wav"
        demo_audio_url = "/demo/example-guitar-riff.wav"
        demo = (
            session.query(models.Transcription)
            .filter(models.Transcription.is_demo == True)
            .filter(models.Transcription.normalized_source_id == "demo:example-guitar-riff")
            .first()
        )
        if not demo:
            demo = models.Transcription(
                title="Example guitar riff",
                user_id=demo_user.id,
                source_type="demo",
                source_url=demo_audio_url,
                normalized_source_id="demo:example-guitar-riff",
                selected_stem="other",
                processing_status="completed",
                is_processed=True,
                is_demo=True,
            )
            session.add(demo)

        demo.audio_file_path = str(static_audio_path)
        demo.separated_audio_file_path = str(static_audio_path)
        demo.title = "Example guitar riff"
        demo.source_url = demo_audio_url
        demo.original_audio_url = demo_audio_url
        demo.separated_audio_url = demo_audio_url
        demo.duration = 12
        demo.detected_tempo = 120
        demo.tempo_confidence = 92
        demo.detected_key = "E minor"
        demo.key_confidence = 84
        demo.processing_error = None
        demo.warning_message = None
        demo.can_play_stem = True
        demo.can_generate_score = True
        demo.transcription_attempts = 1
        demo.notes_data = json.dumps(notes_data)
        demo.chords_data = json.dumps(chords_data)
        demo.tablature_data = json.dumps(tab_data)
        demo.notation_data = "<score-partwise version=\"3.1\"><part-list><score-part id=\"P1\"><part-name>Guitar</part-name></score-part></part-list><part id=\"P1\" /></score-partwise>"
        session.add(demo)
        session.commit()
        session.refresh(demo)

        track = (
            session.query(models.InstrumentTrack)
            .filter(models.InstrumentTrack.transcription_id == demo.id)
            .filter(models.InstrumentTrack.instrument_type == "guitar")
            .first()
        )
        if not track:
            track = models.InstrumentTrack(
                transcription_id=demo.id,
                instrument_type="guitar",
                display_name="Demo guitar stem",
            )
            session.add(track)
        track.stem_audio_path = str(static_audio_path)
        track.notes_json = demo.notes_data
        track.chords_json = demo.chords_data
        track.tab_json = demo.tablature_data
        track.notation_json = demo.notation_data
        track.confidence_score = 96
        track.processing_status = "completed"
        track.confidence_notes = None
        session.add(track)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Could not seed demo transcription")
    finally:
        session.close()


def _ensure_project_deletion_columns():
    """Lightweight schema compatibility for project soft-deletion fields."""
    inspector = inspect(engine)
    if "projects" not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"]
        for column in inspector.get_columns("projects")
    }
    required_columns = {
        "is_deleted": "BOOLEAN DEFAULT FALSE",
        "deleted_at": "TIMESTAMP",
    }

    with engine.connect() as conn:
        for column_name, ddl_type in required_columns.items():
            if column_name in existing_columns:
                continue
            logger.info("Adding missing projects.%s column", column_name)
            conn.execute(
                text(f"ALTER TABLE projects ADD COLUMN {column_name} {ddl_type}")
            )
        conn.commit()

if __name__ == "__main__":
    init_db()
