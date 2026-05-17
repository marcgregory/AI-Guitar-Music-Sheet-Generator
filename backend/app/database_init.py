# Database initialization
# Now that SQLAlchemy/Python 3.13 compatibility issues are resolved,
# actual database initialization is implemented

import logging
from sqlalchemy import inspect, text
from .db import Base, engine
# Import models to ensure they are registered with the Base
from . import models

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db():
    """Initialize the database by creating all tables."""
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    _ensure_transcription_phase1_columns()
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

if __name__ == "__main__":
    init_db()
