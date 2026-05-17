# Project Scope

The canonical scope lives in [ai_guitar_music_sheet_generator_scope.md](ai_guitar_music_sheet_generator_scope.md).

Current architecture summary:

- Use Cloudinary for durable storage of original audio, selected separated stems, MIDI files, and TAB files.
- Save Cloudinary `secure_url` and `public_id` references on transcription/job records.
- Treat Railway local storage as temporary scratch space only.
- Use Demucs selected-stem processing for the MVP.
- Require the user to choose `vocals`, `drums`, `bass`, or `other` before processing.
- Use `other` as the MVP target for guitar transcription.
- Queue jobs and run only one active Celery job at a time on Railway.
- Expose `queue_position` and `estimated_wait_time` so the UI can explain the single-worker queue.
- Check for duplicate completed results before queueing new work.
- Reuse the same song plus same selected stem instead of reprocessing.
- Allow users to delete completed, failed, queued, and processing records from the UI.
- Provide selected-stem preview playback from Cloudinary when available, with local byte-range streaming only for development or legacy records.
- Save and transcribe only the selected stem by default.
- Treat optional multi-stem processing, GPU workers, and full Songsterr-like multi-track tabs as future phases.

Canonical phase scope:

1. Phase 1: selected stem only, one active job at a time, Cloudinary storage integration.
2. Phase 2: multiple selected stems.
3. Phase 3: GPU worker or external AI processing service.
4. Phase 4: full Songsterr-like multi-track tabs.

Deletion, duplicate handling, and preview playback are part of the Phase 1 MVP cost controls. Duplicate detection should use `audio_hash` for uploads, normalized YouTube/source IDs for URL submissions, and `selected_stem` as part of the lookup key. Deletion should clean Cloudinary files when safe and treat active Celery cancellation as best-effort until reliable task revocation is implemented. Railway local files are scratch files and should be removed after terminal states once durable Cloudinary references exist.
