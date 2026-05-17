# MusicStudio MVP Architecture

## Selected-Stem MVP

MusicStudio is scoped as a selected-stem transcription MVP. Railway is the lightweight API/controller layer; it should not be treated as the primary Demucs processing environment for production-like use. The recommended AI processing layer is a Modal/serverless GPU worker. Local Railway/Celery Demucs remains a development fallback for very short files only.

```txt
User Upload / YouTube URL + selected stem
-> Generate audio hash or normalize YouTube ID
-> Check existing completed record with same source + selected stem
-> If found, return existing result
-> Upload original audio to Cloudinary
-> Queue processing job
-> Trigger Modal/serverless GPU worker or expose worker pull endpoint
-> Modal worker downloads original audio from Cloudinary
-> Modal worker runs Demucs selected-stem separation on GPU
-> Modal worker uploads selected separated stem to Cloudinary
-> Modal worker optionally generates MIDI/TAB/MusicXML if supported
-> Modal worker calls backend complete/failed endpoint
-> Backend updates status and output references
-> Frontend polls status and shows playback/export/download
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
- MusicXML files where generated

Persist both `secure_url` and `public_id` for every Cloudinary asset. Railway local storage is temporary only and should be used for worker downloads, Demucs scratch output, intermediate MIDI/TAB generation, and cleanup after `completed` or `failed`.

## Backend/API

Railway remains useful for:

- FastAPI
- PostgreSQL
- authentication
- project and transcription records
- duplicate detection
- queue/status orchestration
- Cloudinary upload references
- worker job coordination

Redis is required for local Celery mode and may still be useful for status or queue coordination, but the production-like MVP should not rely on Railway free/trial CPU/RAM for Demucs.

## Processing Modes

`PROCESSING_MODE=local`

- Development fallback.
- Railway/Celery can process very short files only.
- Not recommended for production Demucs processing.
- If used, Celery worker concurrency should remain `1`.

`PROCESSING_MODE=external_worker`

- Backend queues jobs and exposes worker endpoints.
- A manual worker, including a Kaggle notebook, pulls jobs and reports results.
- Useful for free GPU experiments and manual testing.

`PROCESSING_MODE=modal`

- Preferred MVP production-like architecture.
- Backend triggers Modal/serverless GPU processing.
- Modal handles the selected-stem Demucs workload.

## Worker Endpoints

Planned worker coordination endpoints:

- `GET /api/v1/worker/jobs/next`
- `POST /api/v1/worker/jobs/{transcription_id}/complete`
- `POST /api/v1/worker/jobs/{transcription_id}/failed`

These endpoints should require `WORKER_API_TOKEN`, return only jobs the worker is allowed to process, store full backend logs, and expose sanitized errors to the frontend.

## Modal Worker

The Modal worker should:

- process one selected stem per job
- use GPU-backed Demucs
- support `vocals`, `drums`, `bass`, and `other`
- download `original_audio_url` from Cloudinary
- upload the selected separated stem to Cloudinary
- optionally generate MIDI, TAB, and MusicXML outputs when supported
- report completion or failure to the backend
- keep full logs in Modal/backend while returning user-safe errors to the UI

## Kaggle

Kaggle is optional/manual GPU testing only. It is not 24/7 infrastructure, cannot be reliably auto-started for each user upload, and queued jobs wait until the notebook is running. Do not describe Kaggle as production processing.

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

Legacy local path fields can remain temporarily during migration, but they should not be treated as durable storage.

Current additive migration: `backend/migrations/20260517_selected_stem_persistence.sql`.
