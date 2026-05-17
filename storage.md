# Storage Strategy

## Durable Storage

Use Cloudinary for uploaded audio and generated outputs:

- original audio
- selected separated stem audio
- MIDI files
- TAB files

Store both Cloudinary values for each asset:

- `secure_url` for playback, export, and download
- `public_id` for deletion, replacement, and lifecycle management

## Temporary Storage

Railway local storage is temporary only. The backend/worker may use local paths for:

- upload buffering
- YouTube extraction output
- worker downloads from Cloudinary
- Demucs intermediate files
- MIDI/TAB generation before upload

Temporary files should be cleaned after each job reaches `completed` or `failed`. A failed job should still attempt cleanup and record `processing_error`.

Modal/serverless GPU and external workers should treat Cloudinary as the source of truth: download `original_audio_url`, upload the selected separated stem and supported exports, and report the resulting `secure_url`/`public_id` values back to the backend. No worker local filesystem should be treated as durable storage.

Temporary files should also be cleaned when a user deletes or cancels a queued/processing record. If the active Celery task cannot be stopped reliably in the MVP, the UI record may be hidden/deleted while the worker finishes silently and cleanup still runs.

For preview playback, prefer `separated_audio_url` and redirect to Cloudinary. Local stem paths are development/legacy fallback only and may be removed after durable upload.

## Deleting Stored Assets

When a processing record is deleted, delete related Cloudinary files when safe:

- original audio
- selected separated stem audio
- MIDI file
- TAB file

If Cloudinary deletion fails, keep the database deletion safe and log the cleanup error for retry or manual follow-up.

## Duplicate Storage Guard

Before uploading and processing, check whether the same song and selected stem already has a completed result:

- uploaded files: use `audio_hash`
- YouTube submissions: use `source_type`, `source_url`, and `normalized_source_id`
- queued work: skip entirely when a completed duplicate exists
- include `selected_stem` in the lookup

Reuse existing completed output for the same source plus same stem. A different selected stem may create a new job because the separated stem and generated outputs differ.

## Cost Notes

Selective stem processing reduces:

- CPU usage
- RAM usage
- storage costs
- processing time
- repeated Cloudinary storage from duplicate jobs

Phase 1 should recommend 3-5 minute songs and avoid full multi-stem processing. Production-like selected-stem AI work should move to Modal/serverless GPU; Kaggle remains optional/manual testing only.
