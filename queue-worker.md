# Queue and Worker Policy

## Phase 1 Behavior

Only one processing job runs at a time.

- Celery worker concurrency must be `1`
- Redis is the broker/result backend for queued work
- Other jobs remain queued until the active job finishes
- The UI should clearly show queued jobs

Recommended worker command:

```sh
celery -A app.celery worker --loglevel=info --concurrency=1
```

## Why Concurrency Is One

Demucs and audio transcription are memory-heavy. Running multiple jobs at once on Railway can exhaust CPU/RAM, slow every job down, or crash the worker. The MVP intentionally trades throughput for stability and predictable cost.

## Statuses

- `pending`
- `queued`
- `processing`
- `completed`
- `failed`

`processing_error` should contain a user-safe failure message when status is `failed`.

## Delete and Cancel Behavior

Users should be able to delete records in `completed`, `failed`, `queued`, and `processing` states.

- `queued`: remove or cancel the queued Celery task if possible.
- `processing`: mark the database record cancelled/deleted and stop the task if cancellation is supported.
- MVP limitation: active Celery task cancellation may not be reliable. The UI record can be hidden/deleted, temporary files should still be cleaned up, and the worker may finish silently.

Deletion should also trigger safe Cloudinary cleanup for original audio, separated stem audio, MIDI files, and TAB files. Cloudinary cleanup errors should be logged without making database deletion unsafe.

## Duplicate Queue Guard

Before adding work to the queue, check for a completed record with the same uploaded `audio_hash` or normalized YouTube ID plus the same `selected_stem`. If found, return that existing result instead of queueing another job.

## Future Scaling

Phase 2 can allow multiple selected stems per user request. Phase 3 should move heavy AI work to a GPU worker or external AI processing service before increasing concurrency. Phase 4 can pursue full Songsterr-like multi-track tabs.
