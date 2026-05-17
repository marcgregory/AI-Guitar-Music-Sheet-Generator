# Deployment Notes

## Railway MVP

Railway is the MVP backend target for:

- FastAPI API service
- Celery worker service
- Redis
- PostgreSQL

Railway local storage must not be used as durable file storage. It is temporary scratch space for uploads, worker downloads, Demucs output, and generated files before Cloudinary upload.

The backend runtime is Python 3.11. Both Dockerfiles use Python 3.11 images, and `railway.json` points to the root Dockerfile. Demucs selected-stem processing requires the PyTorch audio stack from `backend/requirements.txt` (`demucs`, `torch`, `torchaudio`, and `torchcodec`) plus an `ffmpeg` executable on `PATH`.

The FastAPI service validates these audio dependencies during startup. `GET /health` returns the overall status and per-dependency availability/version details for `demucs`, `torch`, `torchaudio`, `torchcodec`, and `ffmpeg`.

## Required Environment Variables

Backend/API and worker:

- `DATABASE_URL`
- `REDIS_URL`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`
- `SECRET_KEY`
- `ALGORITHM`
- `ACCESS_TOKEN_EXPIRE_MINUTES`

Frontend:

- `VITE_API_URL`

## Worker Configuration

Run one active job at a time:

```sh
celery -A app.celery worker --loglevel=info --concurrency=1
```

This keeps Railway CPU/RAM usage lower and avoids Demucs memory crashes. Large-scale concurrent AI processing is out of scope for Phase 1.

## Cleanup Strategy

After a job reaches `completed`, `failed`, or is marked deleted/cancelled, the worker should delete temporary local files:

- original temporary upload or YouTube extraction file
- worker download copy
- Demucs work directories
- generated MIDI/TAB files after Cloudinary upload

Cloudinary assets remain durable and are tracked by `secure_url` and `public_id`.

When a user deletes a processing record, the API should delete related Cloudinary assets when safe:

- original audio
- separated stem audio
- MIDI file
- TAB file

If Cloudinary deletion fails, the database deletion should remain safe and the cleanup error should be logged for retry/manual follow-up.

## Duplicate Processing Guard

Before queueing work, the backend should check for a completed duplicate using uploaded `audio_hash` or normalized YouTube ID plus `selected_stem`. Returning an existing result reduces repeated Demucs processing, repeated Cloudinary storage usage, unnecessary queue jobs, and Railway CPU/RAM cost.
