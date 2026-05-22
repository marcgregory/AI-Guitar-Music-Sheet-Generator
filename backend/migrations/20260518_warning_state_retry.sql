ALTER TABLE transcriptions ADD COLUMN warning_message TEXT;
ALTER TABLE transcriptions ADD COLUMN can_generate_score BOOLEAN DEFAULT TRUE;
ALTER TABLE transcriptions ADD COLUMN can_play_stem BOOLEAN DEFAULT FALSE;
ALTER TABLE transcriptions ADD COLUMN transcription_attempts INTEGER DEFAULT 0;
