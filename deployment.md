# Deployment Notes

## Recommended MVP Deployment

Railway should run the lightweight backend/controller, not the primary Demucs workload.

- Frontend: Vercel or the current frontend host
- Backend/API: Railway FastAPI
- Database: PostgreSQL
- Durable storage: Cloudinary
- AI processing: Modal/serverless GPU worker
- Redis: only if needed for local fallback, queue metadata, or status coordination

Railway trial/free resources are not reliable for Demucs production processing. Railway local storage must not be used as durable file storage. It is temporary scratch space only.

The MVP is audio/YouTube selected-stem processing. MIDI import, Guitar Pro import, PowerTab import/export, imported project playback architecture, and imported multi-track workflows are future roadmap items only. MIDI export, MusicXML export, and TAB export remain in scope when generated from separated-stem transcription results.

The backend runtime is Python 3.11. Both Dockerfiles use Python 3.11 images, and `railway.json` points to the root Dockerfile. Local selected-stem Demucs fallback requires the PyTorch audio stack from `backend/requirements.txt` (`demucs`, `torch`, and `torchaudio`) plus an `ffmpeg` executable on `PATH`.

## Required Environment Variables

Backend/API:

- `DATABASE_URL`
- `PROCESSING_MODE=local|external_worker|modal`
- `WORKER_API_TOKEN`
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`
- `SECRET_KEY`
- `ALGORITHM`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `REDIS_URL` if Redis is used for local fallback/status
- `CELERY_BROKER_URL` if `PROCESSING_MODE=local`
- `CELERY_RESULT_BACKEND` if `PROCESSING_MODE=local`

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

Development fallback only. Railway/Celery may process very short files, but this is not recommended for production. If local mode is enabled, run one active job at a time:

```sh
celery -A app.celery worker --loglevel=info --concurrency=1
```

### `PROCESSING_MODE=external_worker`

The backend queues jobs and exposes worker endpoints for a manually running external worker. This is useful for Kaggle/manual GPU tests. Jobs wait until the worker is running.

### `PROCESSING_MODE=modal`

Preferred production-like MVP mode. The backend triggers Modal/serverless GPU processing. Modal downloads the original audio from Cloudinary, runs Demucs selected-stem separation on GPU, runs stem-aware transcription, uploads outputs to Cloudinary, and reports completion/failure back to Railway.

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
