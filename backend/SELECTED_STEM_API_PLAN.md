# Selected-Stem API Plan

This backend plan documents the MusicStudio MVP API contract for selective Demucs processing.

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
-> worker downloads temporary local file
-> run Demucs for selected output needed
-> upload selected separated stem to Cloudinary
-> convert selected stem to MIDI/TAB/sheet output where supported
-> upload generated outputs to Cloudinary
-> mark completed or failed
```

Only save the selected stem output unless explicit caching is added. Selective processing reduces CPU/RAM usage, storage, and total processing time on Railway.

Duplicate detection should happen before starting a new job. Uploaded files should be identified by `audio_hash`; YouTube submissions should use `source_type`, `source_url`, and a normalized YouTube/video ID in `normalized_source_id`. The lookup must include `selected_stem`. Same song plus same selected stem reuses an existing completed result. Same song plus a different selected stem may create a new job.

Railway local storage must be treated as temporary scratch space. The worker may download audio, create Demucs outputs, and generate MIDI/TAB files locally during the job, but terminal cleanup should remove those temporary files after Cloudinary upload succeeds or after failure handling completes.

## Storage Contract

Cloudinary is the durable store for:

- original audio
- selected separated stem audio
- MIDI files
- TAB files

Persist both `secure_url` and `public_id` for each Cloudinary asset so the API can serve downloads/playback and later delete or replace files.

## Queue Contract

Only one active processing job should run at a time.

- Run Celery workers with `--concurrency=1`.
- Use Redis/Celery as the queue.
- New work should become `queued` instead of running concurrently.
- Status responses should tell users when another job is active.
- This is intentional MVP cost control, not a full-scale multi-user processing system.

Queued records may be deleted by the user. The backend should remove or cancel the queued Celery task when possible.

## Status Values

Supported statuses:

- `pending`
- `queued`
- `processing`
- `completed`
- `failed`

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
- `tab_file_url`
- `tab_file_public_id`
- `processing_status`
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

- Phase 1: selected stem only, one active job at a time, Cloudinary storage integration.
- Phase 2: multiple selected stems.
- Phase 3: GPU worker or external AI processing service.
- Phase 4: full Songsterr-like multi-track tabs.
