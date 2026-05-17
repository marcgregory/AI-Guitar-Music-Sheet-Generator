# AI Guitar Music Sheet Generator / MusicStudio

An MVP/portfolio-friendly AI music transcription app for turning an uploaded song or YouTube audio source into a selected-stem practice view with playback, MIDI, TAB, and sheet-style output where supported.

## Current MVP Architecture

The app now prioritizes selective Demucs processing instead of full multi-stem generation on every upload.

```txt
Audio Upload / YouTube URL + selected stem
-> Generate audio hash or normalize YouTube ID
-> Check existing completed record with same source + selected stem
-> If duplicate exists, return existing result
-> Upload original audio to Cloudinary
-> Queue processing job
-> Celery worker downloads a temporary local file
-> Demucs selected stem separation
-> Upload separated stem to Cloudinary
-> MIDI conversion for selected stem if supported
-> TAB generation for selected stem if supported
-> Upload outputs to Cloudinary
-> Playback/export/download
```

Demucs default stems are `vocals`, `drums`, `bass`, and `other`. For MVP guitar transcription, use the `other` stem as the target because guitar and piano are commonly grouped there by the default model. True separate guitar, rhythm guitar, lead guitar, and piano separation may require better specialist models later.

Only one processing job should run at a time on Railway. The Celery worker is configured with `--concurrency=1` so jobs queue instead of running concurrently and exhausting CPU/RAM. This is intentional for cost control and memory stability, not a full-scale multi-user AI processing design.

Recommended MVP limits:
- Process one selected stem per job.
- Prefer songs around 3-5 minutes.
- Save Cloudinary `secure_url` and `public_id` references for original audio, separated audio, MIDI, and TAB outputs.
- Treat Railway local storage as temporary worker scratch space only.
- Treat full multi-instrument processing as a future premium or GPU-backed feature.

Selective stem processing reduces CPU usage, RAM usage, storage costs, and processing time because the MVP does not separate and transcribe every stem for every upload.

Duplicate detection should run before starting a new processing job. Uploaded files use an `audio_hash`; YouTube submissions use a normalized video/source ID. The same song plus the same `selected_stem` should reuse an existing completed result, while the same song with a different stem may create a new job because the output is different. This avoids repeated Demucs runs, duplicate Cloudinary storage, unnecessary queue jobs, and extra Railway CPU/RAM cost.

## Selected-Stem API

Uploads now require `selected_stem`:

- `POST /api/v1/audio/upload` accepts multipart form data with `file` and `selected_stem`.
- `POST /api/v1/audio/youtube` accepts JSON with `youtube_url` and `selected_stem`.
- Valid values are `vocals`, `drums`, `bass`, and `other`.
- `GET /api/v1/audio/{id}/status` returns `pending`, `queued`, `processing`, `completed`, or `failed`.
- `DELETE /api/v1/transcriptions/{id}` deletes or hides a processing record and safely cleans up related Cloudinary files where possible.
- `POST /api/v1/transcriptions/{id}/cancel` may be used for explicit cancellation if separate cancel/delete semantics are needed.
- Result payloads should expose Cloudinary-hosted output URLs where available: `original_audio_url`, `separated_audio_url`, `midi_file_url`, and `tab_file_url`.

Users should be able to delete records in `completed`, `failed`, `queued`, and `processing` states. Queued jobs should be removed/cancelled when possible. Processing jobs should be marked cancelled/deleted in the database; if stopping the active Celery task is not reliable yet, the MVP may hide/delete the UI record while the worker finishes silently and cleanup still runs.

Run the worker with one active job:

```sh
celery -A app.celery worker --loglevel=info --concurrency=1
```

## Storage

Cloudinary is the durable storage layer for uploaded audio and generated outputs:

- original uploaded or YouTube-extracted audio
- selected separated stem audio
- MIDI files
- TAB files

Persist both the Cloudinary `secure_url` and `public_id` for each stored asset so the app can display/download files and later delete or replace them. Railway filesystem paths are only temporary processing paths and should be cleaned up after each job reaches `completed` or `failed`.

Record deletion should delete related Cloudinary assets when safe: original audio, separated stem audio, MIDI file, and TAB file. If Cloudinary deletion fails, keep the database deletion safe and log the cleanup error for retry or manual follow-up.

## Backend Runtime Requirements

The backend is supported on Python 3.11. The Docker-based Railway runtime uses Python 3.11, and selected-stem Demucs processing depends on the pinned PyTorch audio stack in `backend/requirements.txt`: `demucs`, `torch`, `torchaudio`, and `torchcodec`. `ffmpeg` must also be installed and available on `PATH`.

The API validates these dependencies at startup and exposes their availability and versions from `GET /health`.

## Project Structure

- `backend/` - Python/FastAPI backend with audio processing
- `frontend/` - React + TypeScript frontend interface

## Environment Variables

- Frontend uses `VITE_API_URL` to connect to the backend API.
- For Vercel deployment, set `VITE_API_URL` in your Vercel project settings to your deployed backend URL, e.g. `https://your-backend-xxxxx.railway.app/api/v1`.
- Do not deploy local-only values such as `VITE_FFMPEG_LOCATION=C:\ffmpeg\bin` to Vercel.
- Use `frontend/.env.example` as a template for local development.

## Technology Stack

See [tech-stack.md](tech-stack.md) for detailed technology recommendations.

## Architecture and Operations

- [architecture.md](architecture.md) - selected-stem MVP architecture and data model
- [api.md](api.md) - upload, status, output, and job field contract
- [storage.md](storage.md) - Cloudinary storage rules and temporary file cleanup
- [queue-worker.md](queue-worker.md) - Celery/Redis queue behavior and concurrency policy
- [deployment.md](deployment.md) - Railway and environment variable notes
- [setup.md](setup.md) - local setup checklist
- [roadmap.md](roadmap.md) - MVP-to-Songsterr-like phased roadmap

## Implementation Plan

See [implementation-plan.md](implementation-plan.md) for phased implementation approach.

## Scope Document

See [ai_guitar_music_sheet_generator_scope.md](ai_guitar_music_sheet_generator_scope.md) for the current selected-stem MVP scope and future multi-track roadmap.
