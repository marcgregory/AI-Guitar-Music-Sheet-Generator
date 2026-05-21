# Queue and Worker Policy

## Current Direction

Railway or Render is the API/controller. Modal GPU is the production AI/audio processing layer. Local Celery remains a development fallback and should not be described as the main Demucs, Basic Pitch, lyrics, or audio-analysis worker for production.

The MVP queue is for audio/YouTube selected-stem jobs only. MIDI import, Guitar Pro import, PowerTab import/export, imported project playback architecture, and imported multi-track workflows are future roadmap items only.

## Processing Mode

`AUDIO_PROCESSING_MODE=modal`

- Hosted MVP mode.
- Backend dispatches selected-stem jobs to Modal.
- Modal downloads from Cloudinary, runs selected-stem Demucs on GPU, normalizes the selected stem, performs Basic Pitch-style note detection only for `other`/`bass`, performs onset/rhythm analysis for `drums`, performs faster-whisper lyrics generation for `vocals`, uploads outputs, and calls back.
- Modal dispatch should keep retry/rate-limit handling, and one active global processing job is preferred for MVP stability.

`AUDIO_PROCESSING_MODE=local`

- Development fallback only.
- Uses Redis/Celery when configured.
- Local processing should be limited to very short files.
- Keep worker concurrency at `1`.

```sh
celery -A app.celery worker --loglevel=info --concurrency=1
```

`AUDIO_PROCESSING_MODE=disabled`

- Disables audio processing.

## Statuses

- `pending`
- `queued`
- `processing`
- `stem_ready`
- `completed`
- `completed_with_warning`
- `failed`

`processing_error` should contain a user-safe failure message when status is `failed`.

Use `completed_with_warning` when separation succeeds but generated output is limited, such as a stem with no detected notes. Vocal lyrics use `lyrics_generation_status`, separate from `processing_status`.

For melodic stems, zero-note results after Basic Pitch retry should preserve selected-stem playback, expose `can_play_stem=true`, set `can_generate_score=false`, and disable only score/TAB/MIDI/MusicXML exports that require generated notes.

## Worker Endpoints

Planned worker endpoints:

- `GET /api/v1/worker/jobs/next`
- `POST /api/v1/worker/jobs/{transcription_id}/complete`
- `POST /api/v1/worker/jobs/{transcription_id}/failed`

They should require `WORKER_API_TOKEN`, keep full diagnostic logs in Modal/backend, and sanitize frontend-facing errors.

## Status-First Result Loading

The frontend should poll `/status` first and call `/result` only after status is ready, such as `stem_ready`, `completed`, or `completed_with_warning`. Generate Lyrics should update `lyrics_generation_status` in-place and keep the viewer open. Generate Tabs for non-vocal melodic stems should keep its current behavior.

## Delete and Cancel Behavior

Users should be able to delete records in `completed`, `completed_with_warning`, `failed`, `queued`, and `processing` states.

- `queued`: remove or cancel the queued Celery task if possible.
- `processing`: mark the database record cancelled/deleted and stop the task if cancellation is supported.
- MVP limitation: active Celery task cancellation may not be reliable. The UI record can be hidden/deleted, temporary files should still be cleaned up, and the worker may finish silently.

Deletion should also trigger safe Cloudinary cleanup for original audio, separated stem audio, MIDI files, MusicXML files, and TAB files. Cloudinary cleanup errors should be logged without making database deletion unsafe.

## Duplicate Queue Guard

Before adding work to the queue, check for a completed or completed_with_warning record with the same uploaded `audio_hash` or normalized YouTube ID plus the same `selected_stem`. If found, return that existing result instead of queueing another job.

## Future Scaling

Later phases can add multiple selected stems, better quantization, chord grouping, fingering optimization, MusicXML/GP-like export, a manual correction editor, better lyrics model settings, MIDI import, Guitar Pro import, PowerTab import/export, imported project editing, specialist separation models, and advanced Songsterr-like multi-track tabs.
