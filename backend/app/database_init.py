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
        "audio_file_path": "VARCHAR",
        "preprocessed_audio_file_path": "VARCHAR",
        "selected_stem": "VARCHAR DEFAULT 'other'",
        "processing_status": "VARCHAR DEFAULT 'pending'",
        "queue_position": "INTEGER",
        "estimated_wait_time": "INTEGER",
        "celery_task_id": "VARCHAR",
        "modal_dispatch_status": "VARCHAR",
        "modal_job_type": "VARCHAR",
        "modal_dispatched_at": "TIMESTAMP WITH TIME ZONE",
        "modal_request_id": "VARCHAR",
        "modal_retry_at": "TIMESTAMP WITH TIME ZONE",
        "modal_retry_count": "INTEGER DEFAULT 0",
        "separated_audio_file_path": "VARCHAR",
        "midi_file_path": "VARCHAR",
        "tab_file_path": "VARCHAR",
        "youtube_url": "VARCHAR",
        "source_type": "VARCHAR",
        "source_url": "TEXT",
        "normalized_source_id": "VARCHAR",
        "audio_hash": "VARCHAR",
        "duplicate_of_id": "INTEGER",
        "is_demo": "BOOLEAN DEFAULT FALSE",
        "is_deleted": "BOOLEAN DEFAULT FALSE",
        "deleted_at": "TIMESTAMP WITH TIME ZONE",
        "original_audio_url": "TEXT",
        "original_audio_public_id": "VARCHAR",
        "separated_audio_url": "TEXT",
        "separated_audio_public_id": "VARCHAR",
        "midi_file_url": "TEXT",
        "midi_file_public_id": "VARCHAR",
        "tab_file_url": "TEXT",
        "tab_file_public_id": "VARCHAR",
        "duration": "INTEGER",
        "detected_tempo": "INTEGER",
        "tempo_confidence": "INTEGER",
        "detected_key": "VARCHAR",
        "key_confidence": "INTEGER",
        "project_id": "INTEGER",
        "is_processed": "BOOLEAN DEFAULT FALSE",
        "processing_error": "TEXT",
        "warning_message": "TEXT",
        "can_generate_score": "BOOLEAN DEFAULT TRUE",
        "can_play_stem": "BOOLEAN DEFAULT FALSE",
        "transcription_attempts": "INTEGER DEFAULT 0",
        "notes_data": "TEXT",
        "chords_data": "TEXT",
        "tablature_data": "TEXT",
        "notation_data": "TEXT",
        "chord_chart_data": "TEXT",
    }

    with engine.connect() as conn:
        for column_name, ddl_type in required_columns.items():
            if column_name in existing_columns:
                continue
            logger.info("Adding missing transcriptions.%s column", column_name)
            conn.execute(
                text(f"ALTER TABLE transcriptions ADD COLUMN {column_name} {ddl_type}")
            )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_transcriptions_modal_retry_at "
                "ON transcriptions (modal_retry_at)"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_transcriptions_modal_request_id "
                "ON transcriptions (modal_request_id) "
                "WHERE modal_request_id IS NOT NULL"
            )
        )
        conn.commit()


def _demo_tablature_data() -> dict:
    tab_pattern = [
        (6, 0, 0.0),
        (6, 3, 0.5),
        (5, 0, 1.0),
        (5, 2, 1.5),
        (4, 0, 2.0),
        (5, 2, 2.5),
        (5, 0, 3.0),
        (6, 0, 3.5),
        (6, 3, 4.0),
        (5, 0, 4.5),
        (5, 2, 5.0),
        (4, 0, 5.5),
        (4, 2, 6.0),
        (4, 0, 6.5),
        (5, 2, 7.0),
        (5, 0, 7.5),
        (6, 3, 8.0),
        (6, 0, 8.5),
        (6, 3, 9.0),
        (5, 0, 9.5),
        (5, 2, 10.0),
        (4, 0, 10.5),
    ]
    note_duration = 0.36
    tab_notes = []
    for index, (string, fret, onset) in enumerate(tab_pattern):
        measure = int(onset // 2.0) + 1
        beat = int((onset % 2.0) / 0.5) + 1
        tab_notes.append(
            {
                "startTime": onset,
                "duration": note_duration,
                "string": string,
                "fret": fret,
                "measure": measure,
                "beat": beat,
                "onset": onset,
                "offset": onset + note_duration,
                "time": onset,
                "confidence": 0.94 + (index % 4) * 0.01,
            }
        )
    return {
        "strings": ["e", "B", "G", "D", "A", "E"],
        "tuning": [40, 45, 50, 55, 59, 64],
        "measures": [
            {"beats": tab_notes[index:index + 4]}
            for index in range(0, len(tab_notes), 4)
        ],
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
                {"chord": "D:maj", "onset": 2.0, "offset": 3.5, "confidence": 0.74},
                {"chord": "E:min", "onset": 3.5, "offset": 5.0, "confidence": 0.8},
                {"chord": "A:min", "onset": 5.0, "offset": 6.5, "confidence": 0.78},
                {"chord": "D:maj", "onset": 6.5, "offset": 8.5, "confidence": 0.75},
                {"chord": "E:min", "onset": 8.5, "offset": 11.0, "confidence": 0.82},
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
