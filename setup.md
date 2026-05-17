# Setup Notes

## Local Services

Local development needs:

- FastAPI backend
- React/Vite frontend
- PostgreSQL or SQLite for development
- Redis for Celery
- Celery worker
- Cloudinary account for durable media/output storage

## Backend Environment

Set these values in the backend environment:

- `DATABASE_URL`
- `REDIS_URL`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`

## Frontend Environment

Set:

- `VITE_API_URL`

## Worker

Start the worker with one active processing slot:

```sh
celery -A app.celery worker --loglevel=info --concurrency=1
```

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
