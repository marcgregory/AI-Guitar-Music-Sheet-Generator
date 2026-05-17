# Queue and Worker Policy

## Current Direction

Railway is the API/controller. Modal/serverless GPU is the preferred production-like AI processing layer. Local Celery remains a development fallback and should not be described as the main Demucs worker for production.

## Processing Modes

`PROCESSING_MODE=local`

- Development fallback.
- Uses Redis/Celery when configured.
- Railway/Celery can process very short files only.
- Keep worker concurrency at `1`.

```sh
celery -A app.celery worker --loglevel=info --concurrency=1
```

`PROCESSING_MODE=external_worker`

- Backend queues jobs.
- External/manual worker pulls jobs from the backend.
- Useful for Kaggle/manual GPU testing.

`PROCESSING_MODE=modal`

- Preferred MVP production-like mode.
- Backend triggers Modal/serverless GPU worker.
- Modal downloads from Cloudinary, runs selected-stem Demucs on GPU, uploads outputs, and calls back.

## Statuses

- `pending`
- `queued`
- `processing`
- `completed`
- `failed`

`processing_error` should contain a user-safe failure message when status is `failed`.

## Worker Endpoints

Planned worker endpoints:

- `GET /api/v1/worker/jobs/next`
- `POST /api/v1/worker/jobs/{transcription_id}/complete`
- `POST /api/v1/worker/jobs/{transcription_id}/failed`

They should require `WORKER_API_TOKEN`, keep full diagnostic logs in Modal/backend, and sanitize frontend-facing errors.

## Delete and Cancel Behavior

Users should be able to delete records in `completed`, `failed`, `queued`, and `processing` states.

- `queued`: remove or cancel the queued Celery task if possible.
- `processing`: mark the database record cancelled/deleted and stop the task if cancellation is supported.
- MVP limitation: active Celery task cancellation may not be reliable. The UI record can be hidden/deleted, temporary files should still be cleaned up, and the worker may finish silently.

Deletion should also trigger safe Cloudinary cleanup for original audio, separated stem audio, MIDI files, and TAB files. Cloudinary cleanup errors should be logged without making database deletion unsafe.

## Duplicate Queue Guard

Before adding work to the queue, check for a completed record with the same uploaded `audio_hash` or normalized YouTube ID plus the same `selected_stem`. If found, return that existing result instead of queueing another job.

## Future Scaling

Phase 2 should add Modal/serverless GPU worker integration and worker callbacks. Later phases can add multiple selected stems, better retry/recovery, and full Songsterr-like multi-track tabs.
