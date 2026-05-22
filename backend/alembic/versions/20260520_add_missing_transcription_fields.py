import logging

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260520_add_missing_transcription_fields"
down_revision = None
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def _transcription_columns() -> list[sa.Column]:
    return [
        sa.Column("selected_stem", sa.String(), nullable=False, server_default="other"),
        sa.Column("audio_file_path", sa.String(), nullable=True),
        sa.Column("preprocessed_audio_file_path", sa.String(), nullable=True),
        sa.Column("processing_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("queue_position", sa.Integer(), nullable=True),
        sa.Column("estimated_wait_time", sa.Integer(), nullable=True),
        sa.Column("celery_task_id", sa.String(), nullable=True),
        sa.Column("modal_dispatch_status", sa.String(), nullable=True),
        sa.Column("modal_job_type", sa.String(), nullable=True),
        sa.Column("modal_dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("modal_request_id", sa.String(), nullable=True),
        sa.Column("modal_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("modal_retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("separated_audio_file_path", sa.String(), nullable=True),
        sa.Column("midi_file_path", sa.String(), nullable=True),
        sa.Column("tab_file_path", sa.String(), nullable=True),
        sa.Column("youtube_url", sa.String(), nullable=True),
        sa.Column("source_type", sa.String(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("normalized_source_id", sa.String(), nullable=True),
        sa.Column("audio_hash", sa.String(), nullable=True),
        sa.Column("duplicate_of_id", sa.Integer(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("original_audio_url", sa.Text(), nullable=True),
        sa.Column("original_audio_public_id", sa.String(), nullable=True),
        sa.Column("separated_audio_url", sa.Text(), nullable=True),
        sa.Column("separated_audio_public_id", sa.String(), nullable=True),
        sa.Column("midi_file_url", sa.Text(), nullable=True),
        sa.Column("midi_file_public_id", sa.String(), nullable=True),
        sa.Column("tab_file_url", sa.Text(), nullable=True),
        sa.Column("tab_file_public_id", sa.String(), nullable=True),
        sa.Column("duration", sa.Integer(), nullable=True),
        sa.Column("detected_tempo", sa.Integer(), nullable=True),
        sa.Column("tempo_confidence", sa.Integer(), nullable=True),
        sa.Column("detected_key", sa.String(), nullable=True),
        sa.Column("key_confidence", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("is_processed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("warning_message", sa.Text(), nullable=True),
        sa.Column("lyrics_generation_status", sa.String(), nullable=True, server_default="pending"),
        sa.Column("can_generate_score", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("can_play_stem", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("transcription_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes_data", sa.Text(), nullable=True),
        sa.Column("chords_data", sa.Text(), nullable=True),
        sa.Column("tablature_data", sa.Text(), nullable=True),
        sa.Column("notation_data", sa.Text(), nullable=True),
        sa.Column("chord_chart_data", sa.Text(), nullable=True),
        sa.Column("lyrics_data", sa.Text(), nullable=True),
    ]


def _ensure_transcription_columns() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_columns = {
        column["name"]
        for column in inspector.get_columns("transcriptions")
    }
    logger.info(
        "existing_columns_detected table=transcriptions count=%d",
        len(existing_columns),
    )

    for column in _transcription_columns():
        if column.name in existing_columns:
            logger.info(
                "column_skipped_already_exists table=transcriptions column=%s",
                column.name,
            )
            continue

        op.add_column("transcriptions", column)
        existing_columns.add(column.name)
        logger.info("column_added table=transcriptions column=%s", column.name)


def upgrade() -> None:
    logger.info("migration_started revision=%s", revision)
    _ensure_transcription_columns()

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transcriptions_modal_retry_at "
        "ON transcriptions (modal_retry_at)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_transcriptions_modal_request_id "
        "ON transcriptions (modal_request_id) WHERE modal_request_id IS NOT NULL"
    )
    logger.info("migration_completed revision=%s", revision)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_transcriptions_modal_retry_at")
    op.execute("DROP INDEX IF EXISTS ux_transcriptions_modal_request_id")
