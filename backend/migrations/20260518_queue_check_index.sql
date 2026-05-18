-- Add index to speed up global active-job conflict check
CREATE INDEX IF NOT EXISTS ix_transcriptions_processing_status_not_deleted
ON transcriptions (processing_status)
WHERE is_deleted = FALSE;
