# Deployment Notes

## Recommended MVP Deployment

Railway should run the lightweight backend/controller only, never Demucs, Basic Pitch, librosa analysis, MIDI generation, or TAB/score generation.

- Frontend: Vercel or the current frontend host
- Backend/API: Railway FastAPI
- Database: PostgreSQL
- Durable storage: Cloudinary
- AI processing: Modal/serverless GPU worker
- Redis: optional for non-audio infrastructure; not required for production audio processing

Railway trial/free resources are not reliable for Demucs production processing. Railway local storage must not be used as durable file storage. It is temporary scratch space only.

The MVP is audio/YouTube selected-stem processing. MIDI import, Guitar Pro import, PowerTab import/export, imported project playback architecture, and imported multi-track workflows are future roadmap items only. MIDI export, MusicXML export, and TAB export remain in scope when generated from separated-stem transcription results.

The backend runtime is Python 3.11. Both Dockerfiles use Python 3.11 images, and `railway.json` points to the root Dockerfile. Heavy audio/AI dependencies are installed in the Modal image, not Railway.

## Required Environment Variables

Backend/API:

- `DATABASE_URL`
- `PROCESSING_MODE=modal`
- `WORKER_API_TOKEN`
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`
- `SECRET_KEY`
- `ALGORITHM`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `MODAL_TRIGGER_URL`
- `STALE_TRANSCRIPTION_TIMEOUT_SECONDS=1800`
- `MODAL_RATE_LIMIT_BASE_BACKOFF_SECONDS`
- `MODAL_RATE_LIMIT_MAX_BACKOFF_SECONDS`
- `MODAL_MAX_DISPATCH_RETRIES`

Modal worker:

- `MODAL_TOKEN_ID`
- `MODAL_TOKEN_SECRET`
- `WORKER_API_TOKEN`
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`

Frontend:

- `VITE_API_URL`

## Processing Modes

### `PROCESSING_MODE=local`

Legacy/dev only. Heavy audio Celery tasks now fail closed and tell the caller to dispatch Modal. Do not use local mode for production audio processing.

### `PROCESSING_MODE=external_worker`

The backend queues jobs and exposes worker endpoints for a manually running external worker. This is useful for Kaggle/manual GPU tests. Jobs wait until the worker is running.

### `PROCESSING_MODE=modal`

Preferred production-like MVP mode. The backend triggers Modal/serverless GPU processing. Modal downloads the original audio from Cloudinary, runs Demucs selected-stem separation on GPU, runs selected-stem transcription/analysis, uploads outputs to Cloudinary, and reports completion/failure back to Railway.

Worker transcription should normalize the selected separated stem, run Spotify Basic Pitch only for melodic selected stems (`other`, `bass`, and future melodic `vocals`), and run onset/rhythm analysis for `drums`. Zero-note melodic results after retry should report `completed_with_warning` with playable stem metadata instead of failing the job.

## Worker Endpoints

Documented worker coordination endpoints:

- `GET /api/v1/worker/jobs/next`
- `POST /api/v1/worker/jobs/{transcription_id}/complete`
- `POST /api/v1/worker/jobs/{transcription_id}/failed`

These endpoints should require `WORKER_API_TOKEN`. Store detailed logs in Modal/backend and return sanitized errors to the frontend.

## Kaggle Clarification

Kaggle may be used for optional/manual free GPU testing. It is not 24/7, cannot be reliably auto-started for every upload, and should not be documented as production infrastructure.

## Cleanup Strategy

After a job reaches `completed`, `completed_with_warning`, `failed`, or is marked deleted/cancelled, the worker should delete temporary local files:

- original temporary upload or YouTube extraction file
- worker download copy
- Demucs work directories
- generated MIDI/MusicXML/TAB files after Cloudinary upload

Cloudinary assets remain durable and are tracked by `secure_url` and `public_id`.

When a user deletes a processing record, the API should delete related Cloudinary assets when safe:

- original audio
- separated stem audio
- MIDI file
- MusicXML file
- TAB file

If Cloudinary deletion fails, the database deletion should remain safe and the cleanup error should be logged for retry/manual follow-up.

## Duplicate Processing Guard

Before queueing work, the backend should check for a completed duplicate using uploaded `audio_hash` or normalized YouTube ID plus `selected_stem`. Returning an existing result reduces repeated Demucs processing, repeated Cloudinary storage usage, unnecessary queue jobs, and Railway CPU/RAM cost.
