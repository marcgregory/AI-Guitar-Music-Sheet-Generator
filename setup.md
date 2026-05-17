# Setup Notes

## Local Services

Local development needs:

- FastAPI backend
- React/Vite frontend
- PostgreSQL or SQLite for development
- Redis/Celery only for `PROCESSING_MODE=local`
- Cloudinary account for durable media/output storage
- Modal account for preferred production-like GPU processing, when testing `PROCESSING_MODE=modal`

## Backend Environment

Set these values in the backend environment:

- `DATABASE_URL`
- `PROCESSING_MODE=local|external_worker|modal`
- `WORKER_API_TOKEN`
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`
- `REDIS_URL` if using local Celery/status coordination
- `CELERY_BROKER_URL` if using `PROCESSING_MODE=local`
- `CELERY_RESULT_BACKEND` if using `PROCESSING_MODE=local`
- `MODAL_TOKEN_ID` if using `PROCESSING_MODE=modal`
- `MODAL_TOKEN_SECRET` if using `PROCESSING_MODE=modal`

## Frontend Environment

Set:

- `VITE_API_URL`

## Worker

For local fallback only, start the Celery worker with one active processing slot:

```sh
celery -A app.celery worker --loglevel=info --concurrency=1
```

For `PROCESSING_MODE=external_worker`, run the external/manual worker and use:

- `GET /api/v1/worker/jobs/next`
- `POST /api/v1/worker/jobs/{transcription_id}/complete`
- `POST /api/v1/worker/jobs/{transcription_id}/failed`

For `PROCESSING_MODE=modal`, the Modal worker should use GPU, download `original_audio_url`, run Demucs for the selected stem, upload outputs to Cloudinary, and report completion/failure to the backend.

## MVP Test Flow

1. Upload an MP3/WAV file or submit a YouTube URL.
2. Select exactly one stem: `vocals`, `drums`, `bass`, or `other`.
3. Confirm uploaded files generate `audio_hash` and YouTube URLs generate `normalized_source_id`.
4. Confirm duplicate same-song/same-stem requests return the existing completed result.
5. Confirm the original audio is uploaded to Cloudinary when no duplicate exists.
6. Confirm status moves through `queued` or `processing`.
7. Confirm the selected separated stem is uploaded to Cloudinary.
8. Confirm MIDI/TAB outputs are uploaded only when supported.
9. Confirm users can delete completed, failed, queued, and processing records.
10. Confirm deletion cleans Cloudinary assets when safe and logs cleanup failures.
11. Confirm temporary local files are cleaned after terminal or deleted/cancelled status.
