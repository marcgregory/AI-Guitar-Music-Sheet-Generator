DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='modal_dispatch_status') THEN
        ALTER TABLE transcriptions ADD COLUMN modal_dispatch_status VARCHAR;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='modal_job_type') THEN
        ALTER TABLE transcriptions ADD COLUMN modal_job_type VARCHAR;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='modal_dispatched_at') THEN
        ALTER TABLE transcriptions ADD COLUMN modal_dispatched_at TIMESTAMP WITH TIMEZONE;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='modal_request_id') THEN
        ALTER TABLE transcriptions ADD COLUMN modal_request_id VARCHAR;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='modal_retry_at') THEN
        ALTER TABLE transcriptions ADD COLUMN modal_retry_at TIMESTAMP WITH TIMEZONE;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='modal_retry_count') THEN
        ALTER TABLE transcriptions ADD COLUMN modal_retry_count INTEGER NOT NULL DEFAULT 0;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_transcriptions_modal_retry_at
ON transcriptions (modal_retry_at);

CREATE UNIQUE INDEX IF NOT EXISTS ux_transcriptions_modal_request_id
ON transcriptions (modal_request_id)
WHERE modal_request_id IS NOT NULL;