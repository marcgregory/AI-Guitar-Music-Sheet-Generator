# Implementation Plan

The canonical implementation plan lives in [implementation-plan.md](implementation-plan.md).

Current MVP priority:

1. Selected-stem MVP with Cloudinary persistence, duplicate detection, delete/cancel, and queue/status UX.
2. Modal/serverless GPU worker integration with worker endpoints, external worker authentication, status callbacks, and selected-stem preview/export from Cloudinary outputs.
3. Multiple selected stems, improved transcription quality, and better retry/recovery.
4. Full Songsterr-like multi-track tabs with lead/rhythm guitar separation and piano/guitar specialist models.

Demucs default stems are `vocals`, `drums`, `bass`, and `other`. For guitar transcription, use `other` in the MVP and explain that guitar/piano may be grouped there depending on the model and mix.

Durable files should live in Cloudinary, with both `secure_url` and `public_id` stored for original audio, selected separated stem audio, MIDI files, and TAB files. Railway local storage is temporary worker scratch space only.

Railway should be documented as the FastAPI/PostgreSQL controller, not the main AI worker. `PROCESSING_MODE=local` keeps Celery as a development fallback for very short files, `PROCESSING_MODE=external_worker` supports manual/Kaggle testing, and `PROCESSING_MODE=modal` is the preferred production-like MVP path.

Duplicate detection and deletion are also Phase 1 concerns:

- Check `audio_hash` for uploaded files or normalized YouTube/source ID for URL submissions before queueing.
- Reuse an existing completed result when the same song and same `selected_stem` already exists.
- Allow deletion of completed, failed, queued, and processing records.
- Delete Cloudinary files when safe; log cleanup errors without making database deletion unsafe.
