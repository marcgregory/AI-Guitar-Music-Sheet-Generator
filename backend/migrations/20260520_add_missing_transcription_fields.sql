DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='selected_stem') THEN
        ALTER TABLE transcriptions ADD COLUMN selected_stem VARCHAR NOT NULL DEFAULT 'other';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='audio_file_path') THEN
        ALTER TABLE transcriptions ADD COLUMN audio_file_path VARCHAR;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='preprocessed_audio_file_path') THEN
        ALTER TABLE transcriptions ADD COLUMN preprocessed_audio_file_path VARCHAR;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='separated_audio_file_path') THEN
        ALTER TABLE transcriptions ADD COLUMN separated_audio_file_path VARCHAR;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='midi_file_path') THEN
        ALTER TABLE transcriptions ADD COLUMN midi_file_path VARCHAR;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='tab_file_path') THEN
        ALTER TABLE transcriptions ADD COLUMN tab_file_path VARCHAR;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='youtube_url') THEN
        ALTER TABLE transcriptions ADD COLUMN youtube_url VARCHAR;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='duration') THEN
        ALTER TABLE transcriptions ADD COLUMN duration INTEGER;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='detected_tempo') THEN
        ALTER TABLE transcriptions ADD COLUMN detected_tempo INTEGER;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='tempo_confidence') THEN
        ALTER TABLE transcriptions ADD COLUMN tempo_confidence INTEGER;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='detected_key') THEN
        ALTER TABLE transcriptions ADD COLUMN detected_key VARCHAR;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='key_confidence') THEN
        ALTER TABLE transcriptions ADD COLUMN key_confidence INTEGER;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='is_processed') THEN
        ALTER TABLE transcriptions ADD COLUMN is_processed BOOLEAN DEFAULT FALSE;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='notes_data') THEN
        ALTER TABLE transcriptions ADD COLUMN notes_data TEXT;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='chords_data') THEN
        ALTER TABLE transcriptions ADD COLUMN chords_data TEXT;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='tablature_data') THEN
        ALTER TABLE transcriptions ADD COLUMN tablature_data TEXT;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='notation_data') THEN
        ALTER TABLE transcriptions ADD COLUMN notation_data TEXT;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='transcriptions' AND column_name='chord_chart_data') THEN
        ALTER TABLE transcriptions ADD COLUMN chord_chart_data TEXT;
    END IF;
END $$;