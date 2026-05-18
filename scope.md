# Project Scope

The canonical scope lives in [ai_guitar_music_sheet_generator_scope.md](ai_guitar_music_sheet_generator_scope.md).

Current architecture summary:

- Railway is the lightweight FastAPI/PostgreSQL controller, not the primary Demucs processing environment.
- Modal/serverless GPU is the recommended production-like AI processing layer.
- Use Cloudinary for durable storage of original audio, selected separated stems, MIDI files, MusicXML files, and TAB files.
- Support MVP input types: audio upload and YouTube URL.
- Require the user to choose `vocals`, `drums`, `bass`, or `other` before processing.
- Use Demucs selected-stem processing for the MVP.
- Run pitch/rhythm detection on the separated selected stem.
- Generate instrument-aware outputs from separated stems: guitar tabs/score from `other`, bass tabs/score from `bass`, drum rhythm lane/percussion tab from `drums`, and playback-only output from `vocals`.
- Render one synchronized practice view with waveform, playhead, tabs, score, active notes, and selected-stem playback all driven by a shared `currentTime`.
- Keep MIDI export, MusicXML export, and TAB export in scope.
- Move MIDI import, Guitar Pro import, PowerTab import/export, imported project editing, and imported multi-track workflows to the future roadmap only.
- Save Cloudinary `secure_url` and `public_id` references on transcription/job records.
- Treat Railway local storage as temporary scratch space only.
- Queue jobs and expose `queue_position` and `estimated_wait_time` so the UI can explain pending work.
- Use `completed_with_warning` for successful selected-stem processing with limited generated output, such as no-note vocal playback-only results.
- Use `PROCESSING_MODE=modal` for Modal/serverless GPU, `external_worker` for manual/Kaggle tests, and `local` for dev fallback.
- Check for duplicate completed or completed_with_warning audio/YouTube results before queueing new work.
- Reuse the same song plus same selected stem instead of reprocessing.
- Allow users to delete completed, completed_with_warning, failed, queued, and processing records from the UI.
- Treat optional multi-stem processing and imported project workflows as future phases.

Canonical phase scope:

1. Phase 1: selected-stem audio/YouTube MVP, Cloudinary persistence, duplicate detection, delete/cancel, queue/status UX, synchronized playback, and exports.
2. Phase 2: Modal/serverless GPU worker integration, worker endpoints, external worker authentication, status callback flow, selected-stem preview/export from Cloudinary.
3. Phase 3: instrument-aware rendering polish, drum rhythm lanes, bass tab quality, selected-stem retry/recovery, and timing accuracy.
4. Phase 4: future imports and advanced workflows, including MIDI import, Guitar Pro import, PowerTab import/export, imported project editing, multiple selected stems, lead/rhythm guitar separation, and specialist models.

Deletion, duplicate handling, and preview playback are part of the Phase 1 MVP cost controls. Duplicate detection should use `audio_hash` for uploads, normalized YouTube/source IDs for URL submissions, and `selected_stem` as part of the lookup key. Deletion should clean Cloudinary files when safe and treat active Celery cancellation as best-effort until reliable task revocation is implemented. Railway local files are scratch files and should be removed after terminal states once durable Cloudinary references exist.
