# MusicStudio MVP Architecture

## Selected-Stem MVP

MusicStudio is scoped as a Railway-friendly selected-stem transcription MVP. Phase 1 does not process every stem by default and does not attempt Songsterr-like full multi-track tabs.

```txt
User Upload / YouTube URL + selected stem
-> Generate audio hash or normalize YouTube ID
-> Check existing completed record with same source + selected stem
-> If found, return existing result
-> Upload original audio to Cloudinary
-> Queue processing job
-> Celery worker downloads temporary file
-> Demucs selected stem separation
-> Upload separated stem to Cloudinary
-> MIDI conversion for selected stem if supported
-> TAB generation for selected stem if supported
-> Upload outputs to Cloudinary
-> Playback/export/download
```

The old architecture is replaced:

```txt
Audio Upload
-> Separate all stems
-> Convert all stems to MIDI
-> Generate all tabs
```

## Stem Model

Demucs default stems are:

- `vocals`
- `drums`
- `bass`
- `other`

The MVP processes one selected stem per job. Guitar transcription uses `other`, because default Demucs models commonly group guitar, piano, synths, melody, and accompaniment into `other` depending on the mix. True isolated guitar, lead guitar, rhythm guitar, and piano stems are later model upgrades.

## Storage

Cloudinary is the durable storage layer for:

- original audio
- selected separated stem audio
- MIDI files
- TAB files

Persist both `secure_url` and `public_id` for every Cloudinary asset. Railway local storage is temporary only and should be used for worker downloads, Demucs scratch output, intermediate MIDI/TAB generation, and cleanup after `completed` or `failed`.

## Queue

Only one processing job runs at a time in Phase 1.

- Celery worker concurrency: `1`
- Broker: Redis
- Other jobs remain queued
- Statuses: `pending`, `queued`, `processing`, `completed`, `failed`

This is intentional to reduce Railway CPU/RAM usage and avoid memory crashes. Large-scale concurrent AI processing is out of scope for Phase 1.

## Duplicate Detection

Before queueing a new job, the backend should check whether the same source and selected stem already has a completed result.

```txt
User Upload / YouTube URL + selected stem
-> Generate audio hash or normalize YouTube ID
-> Check existing completed record with same source + selected_stem
-> If found, return existing result
-> If not found, upload/process normally
-> Save result for future reuse
```

Duplicate identity should consider:

- `audio_hash` for uploaded files
- `normalized_source_id` for YouTube URLs
- `source_type`
- `selected_stem`

The same song plus the same selected stem should reuse output. The same song plus a different selected stem may create a new job because the separated audio, MIDI, and TAB outputs will differ.

## Deletion and Cancellation

Users should be able to delete processing records with these statuses:

- `completed`
- `failed`
- `queued`
- `processing`

Queued jobs should be removed or cancelled when possible. Processing jobs should be marked cancelled/deleted in the database and stopped if cancellation is supported. If active Celery task cancellation is not reliable in the MVP, the UI record can be hidden/deleted, temporary files should still be cleaned up, and the active worker may finish silently.

Deleting a record should also delete related Cloudinary assets when safe:

- original audio
- separated stem audio
- MIDI file
- TAB file

If Cloudinary deletion fails, database deletion should remain safe and the cleanup error should be logged.

## Data Model

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
- `processing_error`
- `queue_position`
- `estimated_wait_time`
- `celery_task_id`

Legacy local path fields can remain temporarily during migration, but they should not be treated as durable storage in the Railway MVP.

Current additive migration: `backend/migrations/20260517_selected_stem_persistence.sql`.
