# Queue and Worker Policy

## Current Direction

Railway is the API/controller. Modal/serverless GPU is the preferred production-like AI processing layer. Local Celery remains a development fallback and should not be described as the main Demucs worker for production.

The MVP queue is for audio/YouTube selected-stem jobs only. MIDI import, Guitar Pro import, PowerTab import/export, imported project playback architecture, and imported multi-track workflows are future roadmap items only.

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
- Worker processes one selected stem, normalizes the separated stem, runs Basic Pitch only for melodic stems, and runs onset/rhythm analysis for drums.

`PROCESSING_MODE=modal`

- Preferred MVP production-like mode.
- Backend triggers Modal/serverless GPU worker.
- Modal downloads from Cloudinary, runs selected-stem Demucs on GPU, normalizes the selected stem, performs Basic Pitch transcription only for `other`/`bass`/future melodic `vocals`, performs onset/rhythm analysis for `drums`, uploads outputs, and calls back.

## Statuses

- `pending`
- `queued`
- `processing`
- `completed`
- `completed_with_warning`
- `failed`

`processing_error` should contain a user-safe failure message when status is `failed`.

Use `completed_with_warning` when separation succeeds but generated output is limited, such as a vocal playback-only result or a stem with no detected notes.

For melodic stems, zero-note results after Basic Pitch retry should preserve selected-stem playback, expose `can_play_stem=true`, set `can_generate_score=false`, and disable only score/TAB/MIDI/MusicXML exports that require generated notes.

## Worker Endpoints

Planned worker endpoints:

- `GET /api/v1/worker/jobs/next`
- `POST /api/v1/worker/jobs/{transcription_id}/complete`
- `POST /api/v1/worker/jobs/{transcription_id}/failed`

They should require `WORKER_API_TOKEN`, keep full diagnostic logs in Modal/backend, and sanitize frontend-facing errors.

## Delete and Cancel Behavior

Users should be able to delete records in `completed`, `completed_with_warning`, `failed`, `queued`, and `processing` states.

- `queued`: remove or cancel the queued Celery task if possible.
- `processing`: mark the database record cancelled/deleted and stop the task if cancellation is supported.
- MVP limitation: active Celery task cancellation may not be reliable. The UI record can be hidden/deleted, temporary files should still be cleaned up, and the worker may finish silently.

Deletion should also trigger safe Cloudinary cleanup for original audio, separated stem audio, MIDI files, MusicXML files, and TAB files. Cloudinary cleanup errors should be logged without making database deletion unsafe.

## Duplicate Queue Guard

Before adding work to the queue, check for a completed or completed_with_warning record with the same uploaded `audio_hash` or normalized YouTube ID plus the same `selected_stem`. If found, return that existing result instead of queueing another job.

## Future Scaling

Later phases can add multiple selected stems, better retry/recovery, MIDI import, Guitar Pro import, PowerTab import/export, imported project editing, specialist separation models, and full Songsterr-like multi-track tabs.
