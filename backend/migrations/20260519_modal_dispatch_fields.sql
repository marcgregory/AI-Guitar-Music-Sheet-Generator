ALTER TABLE transcriptions ADD COLUMN modal_dispatch_status VARCHAR;
ALTER TABLE transcriptions ADD COLUMN modal_job_type VARCHAR;
ALTER TABLE transcriptions ADD COLUMN modal_dispatched_at TIMESTAMP;
ALTER TABLE transcriptions ADD COLUMN modal_request_id VARCHAR;
ALTER TABLE transcriptions ADD COLUMN modal_retry_at TIMESTAMP;
ALTER TABLE transcriptions ADD COLUMN modal_retry_count INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS ix_transcriptions_modal_retry_at
ON transcriptions (modal_retry_at);

CREATE UNIQUE INDEX IF NOT EXISTS ux_transcriptions_modal_request_id
ON transcriptions (modal_request_id)
WHERE modal_request_id IS NOT NULL;
