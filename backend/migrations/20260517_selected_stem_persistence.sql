-- Selected-stem MVP persistence fields for Railway-friendly processing.
-- Keep this migration additive so existing SQLite/PostgreSQL deployments remain compatible.

ALTER TABLE transcriptions ADD COLUMN original_audio_url TEXT;
ALTER TABLE transcriptions ADD COLUMN original_audio_public_id VARCHAR;
ALTER TABLE transcriptions ADD COLUMN separated_audio_url TEXT;
ALTER TABLE transcriptions ADD COLUMN separated_audio_public_id VARCHAR;
ALTER TABLE transcriptions ADD COLUMN midi_file_url TEXT;
ALTER TABLE transcriptions ADD COLUMN midi_file_public_id VARCHAR;
ALTER TABLE transcriptions ADD COLUMN tab_file_url TEXT;
ALTER TABLE transcriptions ADD COLUMN tab_file_public_id VARCHAR;

ALTER TABLE transcriptions ADD COLUMN audio_hash VARCHAR;
ALTER TABLE transcriptions ADD COLUMN source_type VARCHAR;
ALTER TABLE transcriptions ADD COLUMN source_url TEXT;
ALTER TABLE transcriptions ADD COLUMN normalized_source_id VARCHAR;
ALTER TABLE transcriptions ADD COLUMN duplicate_of_id INTEGER;
ALTER TABLE transcriptions ADD COLUMN is_deleted BOOLEAN DEFAULT FALSE;
ALTER TABLE transcriptions ADD COLUMN deleted_at DATETIME;

ALTER TABLE transcriptions ADD COLUMN processing_status VARCHAR DEFAULT 'pending';
ALTER TABLE transcriptions ADD COLUMN processing_error TEXT;
ALTER TABLE transcriptions ADD COLUMN queue_position INTEGER;
ALTER TABLE transcriptions ADD COLUMN estimated_wait_time INTEGER;
ALTER TABLE transcriptions ADD COLUMN celery_task_id VARCHAR;

ALTER TABLE projects ADD COLUMN is_deleted BOOLEAN DEFAULT FALSE;
ALTER TABLE projects ADD COLUMN deleted_at DATETIME;

CREATE INDEX IF NOT EXISTS ix_transcriptions_audio_hash ON transcriptions (audio_hash);
CREATE INDEX IF NOT EXISTS ix_transcriptions_normalized_source_id ON transcriptions (normalized_source_id);
