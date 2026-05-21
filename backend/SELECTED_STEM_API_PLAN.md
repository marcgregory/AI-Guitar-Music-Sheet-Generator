# Selected-Stem API Plan

This backend plan documents the MusicStudio MVP API contract for selective Demucs processing. Railway/Render is the API/controller for auth, DB, status polling, Cloudinary references, and Modal dispatch/callbacks. Modal GPU is the production AI/audio processing layer. Railway/Celery Demucs remains local/dev fallback only.

## Request Contract

Upload and YouTube processing requests should include one selected target:

- `selected_stem`
- or `selected_instrument`

Valid MVP values should match Demucs default stems:

- `vocals`
- `drums`
- `bass`
- `other`

For guitar transcription, the frontend should submit `other` for the MVP. Default Demucs models do not reliably provide true isolated guitar, lead guitar, rhythm guitar, or piano stems; those require later specialist models.

## Processing Contract

The backend should not run full multi-stem transcription by default.

```txt
Audio Upload / YouTube URL + selected stem
-> generate audio hash or normalize YouTube ID
-> check existing completed record with same source + selected_stem
-> if duplicate exists, return existing result
-> upload original audio to Cloudinary
-> validate selected_stem
-> create queued job
-> trigger Modal/serverless GPU worker or expose worker pull endpoint
-> worker downloads original audio from Cloudinary
-> run Demucs for selected output needed
-> upload selected separated stem to Cloudinary
-> run stem-specific generation: faster-whisper lyrics for vocals, Basic Pitch-style tabs/score for other/bass, rhythm/onset lanes for drums
-> convert selected stem to MIDI/TAB/MusicXML where supported
-> upload generated outputs to Cloudinary
-> worker calls backend complete/failed endpoint
-> backend marks completed or failed
```

Only save the selected stem output unless explicit caching is added. Selective processing reduces CPU/RAM usage, storage, and total processing time.

Duplicate detection should happen before starting a new job. Uploaded files should be identified by `audio_hash`; YouTube submissions should use `source_type`, `source_url`, and a normalized YouTube/video ID in `normalized_source_id`. The lookup must include `selected_stem`. Same song plus same selected stem reuses an existing completed result. Same song plus a different selected stem may create a new job.

Railway local storage must be treated as temporary scratch space. The worker may download audio, create Demucs outputs, and generate MIDI/TAB files locally during the job, but terminal cleanup should remove those temporary files after Cloudinary upload succeeds or after failure handling completes.

## Storage Contract

Cloudinary is the durable store for:

- original audio
- selected separated stem audio
- MIDI files
- MusicXML files
- TAB files

Persist both `secure_url` and `public_id` for each Cloudinary asset so the API can serve downloads/playback and later delete or replace files.

## Processing Mode

- `AUDIO_PROCESSING_MODE=modal`: hosted MVP mode. Backend triggers Modal GPU processing.
- `AUDIO_PROCESSING_MODE=local`: development fallback only. Uses Redis/Celery and should process very short files only. Keep Celery concurrency at `1`.
- `AUDIO_PROCESSING_MODE=disabled`: disables audio processing.

## Queue Contract

- New work should become `queued` instead of running heavy AI work in request handlers.
- Status responses should tell users when another job is active.
- Local Celery workers, when used, must run with `--concurrency=1`.
- Modal/serverless GPU should handle preferred MVP Demucs processing.

Queued records may be deleted by the user. The backend should remove or cancel the queued Celery task when possible.

## Worker Endpoints

Documented worker endpoints:

- `GET /api/v1/worker/jobs/next`
- `POST /api/v1/worker/jobs/{transcription_id}/complete`
- `POST /api/v1/worker/jobs/{transcription_id}/failed`

These endpoints should require `WORKER_API_TOKEN`. The worker should keep full logs in Modal/backend and report sanitized user-facing errors.

## Status Values

Supported statuses:

- `pending`
- `queued`
- `processing`
- `stem_ready`
- `completed`
- `completed_with_warning`
- `failed`

Lyrics status is tracked separately in `lyrics_generation_status`, so Generate Lyrics should not change the main audio `processing_status` or navigate the viewer back to the processing screen.

## Data Fields

Recommended transcription/job fields:

- `selected_stem`
- `audio_hash`
- `source_type`
- `source_url`
- `normalized_source_id`
- `duplicate_of_id`
- `is_deleted`
- `deleted_at`
- `original_audio_url`
- `original_audio_public_id`
- `separated_audio_url`
- `separated_audio_public_id`
- `midi_file_url`
- `midi_file_public_id`
- `musicxml_file_url`
- `musicxml_file_public_id`
- `tab_file_url`
- `tab_file_public_id`
- `processing_status`
- `lyrics_generation_status`
- `queue_position`
- `processing_error`

Legacy local path fields such as `separated_audio_file_path`, `midi_file_path`, and `tab_file_path` should be treated as temporary or migration-only fields. New MVP API responses should prefer Cloudinary URL/public ID fields.

Existing `InstrumentTrack` rows can remain for future multi-track expansion, but Phase 1 should produce only the selected stem output by default.

## Delete and Cancel Contract

Documented endpoints:

- `DELETE /transcriptions/{id}`
- `POST /transcriptions/{id}/cancel` if explicit cancellation is useful separately from delete

Users should be allowed to delete records in these statuses:

- `completed`
- `completed_with_warning`
- `failed`
- `queued`
- `processing`

Behavior:

- Completed/failed records can be marked deleted or removed and should delete related Cloudinary assets when safe.
- Queued records should remove/cancel the queued task if possible.
- Processing records should be marked cancelled/deleted in the database and stopped if Celery cancellation is supported.
- MVP limitation: active Celery cancellation may not be reliable yet. If so, hide/delete the UI record, keep cleanup logic in place, and allow the worker to finish silently.
- Delete Cloudinary assets for original audio, separated stem audio, MIDI file, and TAB file when safe.
- If Cloudinary deletion fails, keep database deletion safe and log the cleanup error.

## Roadmap

- Phase 1: selected-stem MVP, Cloudinary persistence, duplicate detection, delete/cancel, queue/status UX.
- Phase 2: Modal/serverless GPU worker integration, worker endpoints, external worker authentication, status callback flow, selected-stem preview/export from Cloudinary outputs.
- Phase 3: improved transcription quality, better retry/recovery, lyrics settings, quantization, chord grouping, and playback reliability.
- Phase 4: multiple selected stems, AlphaTab or VexFlow renderer, fingering optimizer, MusicXML/GP-like export, manual correction editor, advanced Songsterr-like multi-track tabs, lead/rhythm guitar separation, and piano/guitar specialist models.
