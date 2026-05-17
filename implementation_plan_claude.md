# Implementation Plan

The canonical implementation plan lives in [implementation-plan.md](implementation-plan.md).

Current MVP priority:

1. Selected stem only, one active processing job at a time, and Cloudinary storage integration.
2. Multiple selected stems.
3. GPU worker or external AI processing service.
4. Full Songsterr-like multi-track tabs.

Demucs default stems are `vocals`, `drums`, `bass`, and `other`. For guitar transcription, use `other` in the MVP and explain that guitar/piano may be grouped there depending on the model and mix.

Durable files should live in Cloudinary, with both `secure_url` and `public_id` stored for original audio, selected separated stem audio, MIDI files, and TAB files. Railway local storage is temporary worker scratch space only.

Duplicate detection and deletion are also Phase 1 concerns:

- Check `audio_hash` for uploaded files or normalized YouTube/source ID for URL submissions before queueing.
- Reuse an existing completed result when the same song and same `selected_stem` already exists.
- Allow deletion of completed, failed, queued, and processing records.
- Delete Cloudinary files when safe; log cleanup errors without making database deletion unsafe.
