from alembic import op

revision = "20260520_add_missing_transcription_fields"
down_revision = None
branch_labels = None
depends_on = None


def _ensure_column(table_name: str, column_definition: str) -> None:
    op.execute(
        f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_definition}"
    )


def upgrade() -> None:
    _ensure_column("transcriptions", "selected_stem VARCHAR NOT NULL DEFAULT 'other'")
    _ensure_column("transcriptions", "audio_file_path VARCHAR")
    _ensure_column("transcriptions", "preprocessed_audio_file_path VARCHAR")
    _ensure_column("transcriptions", "processing_status VARCHAR NOT NULL DEFAULT 'pending'")
    _ensure_column("transcriptions", "queue_position INTEGER")
    _ensure_column("transcriptions", "estimated_wait_time INTEGER")
    _ensure_column("transcriptions", "celery_task_id VARCHAR")
    _ensure_column("transcriptions", "modal_dispatch_status VARCHAR")
    _ensure_column("transcriptions", "modal_job_type VARCHAR")
    _ensure_column("transcriptions", "modal_dispatched_at TIMESTAMP WITH TIME ZONE")
    _ensure_column("transcriptions", "modal_request_id VARCHAR")
    _ensure_column("transcriptions", "modal_retry_at TIMESTAMP WITH TIME ZONE")
    _ensure_column("transcriptions", "modal_retry_count INTEGER NOT NULL DEFAULT 0")
    _ensure_column("transcriptions", "separated_audio_file_path VARCHAR")
    _ensure_column("transcriptions", "midi_file_path VARCHAR")
    _ensure_column("transcriptions", "tab_file_path VARCHAR")
    _ensure_column("transcriptions", "youtube_url VARCHAR")
    _ensure_column("transcriptions", "source_type VARCHAR")
    _ensure_column("transcriptions", "source_url TEXT")
    _ensure_column("transcriptions", "normalized_source_id VARCHAR")
    _ensure_column("transcriptions", "audio_hash VARCHAR")
    _ensure_column("transcriptions", "duplicate_of_id INTEGER")
    _ensure_column("transcriptions", "is_demo BOOLEAN NOT NULL DEFAULT FALSE")
    _ensure_column("transcriptions", "is_deleted BOOLEAN NOT NULL DEFAULT FALSE")
    _ensure_column("transcriptions", "deleted_at TIMESTAMP WITH TIME ZONE")
    _ensure_column("transcriptions", "original_audio_url TEXT")
    _ensure_column("transcriptions", "original_audio_public_id VARCHAR")
    _ensure_column("transcriptions", "separated_audio_url TEXT")
    _ensure_column("transcriptions", "separated_audio_public_id VARCHAR")
    _ensure_column("transcriptions", "midi_file_url TEXT")
    _ensure_column("transcriptions", "midi_file_public_id VARCHAR")
    _ensure_column("transcriptions", "tab_file_url TEXT")
    _ensure_column("transcriptions", "tab_file_public_id VARCHAR")
    _ensure_column("transcriptions", "duration INTEGER")
    _ensure_column("transcriptions", "detected_tempo INTEGER")
    _ensure_column("transcriptions", "tempo_confidence INTEGER")
    _ensure_column("transcriptions", "detected_key VARCHAR")
    _ensure_column("transcriptions", "key_confidence INTEGER")
    _ensure_column("transcriptions", "project_id INTEGER")
    _ensure_column("transcriptions", "is_processed BOOLEAN NOT NULL DEFAULT FALSE")
    _ensure_column("transcriptions", "processing_error TEXT")
    _ensure_column("transcriptions", "warning_message TEXT")
    _ensure_column("transcriptions", "can_generate_score BOOLEAN NOT NULL DEFAULT TRUE")
    _ensure_column("transcriptions", "can_play_stem BOOLEAN NOT NULL DEFAULT FALSE")
    _ensure_column("transcriptions", "transcription_attempts INTEGER NOT NULL DEFAULT 0")
    _ensure_column("transcriptions", "notes_data TEXT")
    _ensure_column("transcriptions", "chords_data TEXT")
    _ensure_column("transcriptions", "tablature_data TEXT")
    _ensure_column("transcriptions", "notation_data TEXT")
    _ensure_column("transcriptions", "chord_chart_data TEXT")

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transcriptions_modal_retry_at "
        "ON transcriptions (modal_retry_at)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_transcriptions_modal_request_id "
        "ON transcriptions (modal_request_id) WHERE modal_request_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_transcriptions_modal_retry_at")
    op.execute("DROP INDEX IF EXISTS ux_transcriptions_modal_request_id")
