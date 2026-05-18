# AI Guitar Music Sheet Generator / MusicStudio

An MVP/portfolio-friendly music transcription app for turning uploaded audio or YouTube audio into synchronized practice views with separated-stem playback, instrument-aware tabs/notation/rhythm data, and MIDI/MusicXML/TAB exports where supported.

## Current MVP Architecture

The app prioritizes selected-stem processing for audio/YouTube sources. Railway is the lightweight API/controller. Modal/serverless GPU is the recommended production-like AI processing layer for Demucs workloads. Railway/Celery Demucs is retained only as a local/dev fallback for very short files.

Supported MVP input types:

1. Audio upload
2. YouTube URL

```txt
Audio Upload / YouTube URL
-> User selects target stem
-> Generate audio hash or normalize YouTube ID
-> Check existing completed record with same source + selected stem
-> If duplicate exists, return existing result
-> Upload original audio to Cloudinary
-> Queue processing job
-> Trigger Modal/serverless GPU worker or expose worker pull endpoint
-> Modal worker downloads original audio from Cloudinary
-> Modal worker runs Demucs selected-stem separation on GPU
-> Pitch/rhythm detection runs on separated stem
-> Generate instrument-aware tabs/notation/rhythm data
-> Modal worker uploads selected separated stem and supported exports to Cloudinary
-> Modal worker calls backend complete/failed endpoint
-> Backend updates transcription status and output references
-> Frontend renders synchronized playback with playhead/waveform and export/download controls
```

Demucs default stems are `vocals`, `drums`, `bass`, and `other`. For MVP guitar transcription, use the `other` stem as the target because guitar and piano are commonly grouped there by the default model. True separate guitar, rhythm guitar, lead guitar, and piano separation may require better specialist models later.

Recommended MVP limits:
- Process one selected stem per job.
- Prefer songs around 3-5 minutes.
- Save Cloudinary `secure_url` and `public_id` references for original audio, selected separated stem audio, MIDI exports, MusicXML exports, and TAB outputs.
- Treat Railway local storage as temporary worker scratch space only.
- Treat full multi-instrument processing and imported project workflows as future premium or GPU-backed features.
- Do not rely on Railway free/trial resources for production Demucs processing.
- Treat Kaggle as optional/manual GPU testing only, not 24/7 production infrastructure.

MIDI import, Guitar Pro import, PowerTab import/export, imported project playback architecture, and imported multi-track workflows are future roadmap items only. MIDI export, MusicXML export, and TAB export stay in scope when generated from separated-stem transcription results.

Selective stem processing reduces CPU usage, RAM usage, storage costs, and processing time because the MVP does not separate and transcribe every stem for every upload.

Duplicate detection should run before starting a new processing job. Uploaded audio files use an `audio_hash`; YouTube submissions use a normalized video/source ID. The same song plus the same `selected_stem` should reuse an existing completed result, while the same song with a different stem may create a new job because the output is different.

## Stem Support Matrix

- `vocals`: playback only for MVP; future roadmap: melody extraction.
- `drums`: analyze drum stem, detect hits/onsets, generate drum rhythm lane/percussion tab where possible, support synchronized playback highlighting, and support drum MIDI export when possible.
- `bass`: analyze bass stem, generate 4-string bass tablature with standard E A D G tuning, generate bass score data, and support synchronized playback/playhead highlighting.
- `other`: primary guitar transcription target, generating guitar tablature, score notation, and synchronized playback/playhead highlighting.

## Playback and Rendering

Viewer behavior:

- guitar/`other` -> 6-string tablature
- `bass` -> 4-string bass tablature
- `drums` -> rhythm lane/percussion tab
- `vocals` -> playback-only

All views use shared playback synchronization:

- waveform
- playhead
- tabs
- score
- active notes or drum hits
- selected-stem playback

The app should use one shared `currentTime` for waveform, tabs, score, and stem playback. Separate timers for waveform, tabs, and score are out of scope.

## Selected-Stem API

Uploads require `selected_stem`:

- `POST /api/v1/audio/upload` accepts multipart form data with `file` and `selected_stem`.
- `POST /api/v1/audio/youtube` accepts JSON with `youtube_url` and `selected_stem`.
- Valid values are `vocals`, `drums`, `bass`, and `other`.
- MVP `source_type` values are `upload`, `youtube`, and `demo`.
- `GET /api/v1/audio/{id}/status` returns `pending`, `queued`, `processing`, `completed`, `completed_with_warning`, or `failed`.
- `DELETE /api/v1/transcriptions/{id}` deletes or hides a processing record and safely cleans up related Cloudinary files where possible.
- `POST /api/v1/transcriptions/{id}/cancel` may be used for explicit cancellation if separate cancel/delete semantics are needed.
- `GET /api/v1/worker/jobs/next` lets an authenticated external worker pull queued work.
- `POST /api/v1/worker/jobs/{transcription_id}/complete` lets a worker report Cloudinary output references.
- `POST /api/v1/worker/jobs/{transcription_id}/failed` lets a worker report failure details.
- Result payloads should expose Cloudinary-hosted output URLs where available: `original_audio_url`, `separated_audio_url`, `midi_file_url`, `musicxml_file_url`, and `tab_file_url`.

Users should be able to delete records in `completed`, `completed_with_warning`, `failed`, `queued`, and `processing` states. Queued jobs should be removed/cancelled when possible. Processing jobs should be marked cancelled/deleted in the database; if stopping the active Celery task is not reliable yet, the MVP may hide/delete the UI record while the worker finishes silently and cleanup still runs.

## Processing Modes

- `PROCESSING_MODE=local`: development fallback. Railway/Celery can process very short files only and should run with `--concurrency=1`.
- `PROCESSING_MODE=external_worker`: backend queues jobs and a manual/external worker pulls them. Useful for Kaggle/manual GPU testing.
- `PROCESSING_MODE=modal`: preferred MVP production-like architecture. Backend triggers Modal/serverless GPU processing.

For local fallback only, run the Celery worker with one active job:

```sh
celery -A app.celery worker --loglevel=info --concurrency=1
```

## Storage

Cloudinary is the durable storage layer for uploaded audio and generated outputs:

- original uploaded or YouTube-extracted audio
- selected separated stem audio
- MIDI export files
- MusicXML export files
- TAB files

Persist both the Cloudinary `secure_url` and `public_id` for each stored asset so the app can display/download files and later delete or replace them. Railway filesystem paths are only temporary processing paths and should be cleaned up after each job reaches `completed` or `failed`.

Record deletion should delete related Cloudinary assets when safe: original audio, separated stem audio, MIDI file, MusicXML file, and TAB file. If Cloudinary deletion fails, keep the database deletion safe and log the cleanup error for retry or manual follow-up.

## Backend Runtime Requirements

The backend is supported on Python 3.11. The Docker-based Railway runtime uses Python 3.11. Local selected-stem Demucs fallback depends on the pinned PyTorch audio stack in `backend/requirements.txt`: `demucs`, `torch`, and `torchaudio`. `ffmpeg` must also be installed and available on `PATH`.

The API validates these dependencies at startup and exposes their availability and versions from `GET /health`.

## Project Structure

- `backend/` - Python/FastAPI backend with audio processing
- `frontend/` - React + TypeScript frontend interface

## Environment Variables

- Frontend uses `VITE_API_URL` to connect to the backend API.
- For Vercel deployment, set `VITE_API_URL` in your Vercel project settings to your deployed backend URL, e.g. `https://your-backend-xxxxx.railway.app/api/v1`.
- Do not deploy local-only values such as `VITE_FFMPEG_LOCATION=C:\ffmpeg\bin` to Vercel.
- Backend processing uses `PROCESSING_MODE=local|external_worker|modal`.
- External/Modal workers use `WORKER_API_TOKEN`.
- Modal uses `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`.
- Cloudinary uses `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, and `CLOUDINARY_API_SECRET`.
- Use `frontend/.env.example` as a template for local development.

## Technology Stack

See [tech-stack.md](tech-stack.md) for detailed technology recommendations.

## Architecture and Operations

- [architecture.md](architecture.md) - selected-stem MVP architecture and data model
- [api.md](api.md) - upload, status, output, and job field contract
- [storage.md](storage.md) - Cloudinary storage rules and temporary file cleanup
- [queue-worker.md](queue-worker.md) - Celery/Redis queue behavior and concurrency policy
- [deployment.md](deployment.md) - Railway, Cloudinary, Modal, and environment variable notes
- [setup.md](setup.md) - local setup checklist
- [roadmap.md](roadmap.md) - MVP-to-Songsterr-like phased roadmap

## Implementation Plan

See [implementation-plan.md](implementation-plan.md) for phased implementation approach.

## Scope Document

See [project-scope.md](project-scope.md) and [ai_guitar_music_sheet_generator_scope.md](ai_guitar_music_sheet_generator_scope.md) for the current selected-stem audio/YouTube MVP scope and future import roadmap.
