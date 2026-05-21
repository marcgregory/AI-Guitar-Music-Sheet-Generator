# Deployment Notes

## Recommended MVP Deployment

Railway or Render should run the lightweight backend/controller only, never Demucs, Basic Pitch-style note detection, faster-whisper, librosa analysis, MIDI generation, or TAB/score generation.

- Frontend: Vercel or the current frontend host
- Backend/API: Railway or Render FastAPI
- Database: PostgreSQL
- Durable storage: Cloudinary
- AI processing: Modal/serverless GPU worker
- Redis: optional for non-audio infrastructure; not required for production audio processing

Railway/Render resources are for API, auth, DB access, status polling, Cloudinary metadata, and Modal dispatch/callback handling. Railway/Render local storage must not be used as durable file storage. It is temporary scratch space only.

The MVP is audio/YouTube selected-stem processing. MIDI import, Guitar Pro import, PowerTab import/export, imported project playback architecture, and imported multi-track workflows are future roadmap items only. MIDI export, MusicXML export, and TAB export remain in scope when generated from separated-stem transcription results.

The backend runtime is Python 3.11. Both Dockerfiles use Python 3.11 images, and `railway.json` points to the root Dockerfile. Heavy audio/AI dependencies are installed in the Modal image, not Railway.

## Required Environment Variables

Backend/API:

- `DATABASE_URL`
- `AUDIO_PROCESSING_MODE=modal`
- `WORKER_API_TOKEN`
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`
- `SECRET_KEY`
- `ALGORITHM`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `MODAL_TRIGGER_URL`
- `STALE_TRANSCRIPTION_TIMEOUT_SECONDS=1800`
- `MODAL_RATE_LIMIT_BASE_BACKOFF_SECONDS`
- `MODAL_RATE_LIMIT_MAX_BACKOFF_SECONDS`
- `MODAL_MAX_DISPATCH_RETRIES`
- `YOUTUBE_COOKIES` or `YOUTUBE_COOKIES_FILE`
- `WHISPER_MODEL_SIZE`
- `WHISPER_LANGUAGE`
- `WHISPER_BEAM_SIZE`
- `WHISPER_BEST_OF`
- `WHISPER_VAD_FILTER`
- `WHISPER_CONDITION_ON_PREVIOUS_TEXT`
- `WHISPER_INITIAL_PROMPT`

Modal worker:

- `MODAL_TOKEN_ID`
- `MODAL_TOKEN_SECRET`
- `WORKER_API_TOKEN`
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`

Frontend:

- `VITE_API_URL`

## Processing Mode

`AUDIO_PROCESSING_MODE=modal` is the production MVP mode. The backend triggers Modal GPU processing. Modal downloads the original audio from Cloudinary, runs selected-stem separation, runs stem-specific generation, uploads outputs to Cloudinary, and reports completion/failure back to the backend.

Worker transcription should normalize the selected separated stem, run Basic Pitch-style note detection only for melodic non-vocal selected stems (`other`, `bass`), run onset/rhythm analysis for `drums`, and run faster-whisper lyrics generation for `vocals`. Zero-note melodic results after retry should report `completed_with_warning` with playable stem metadata instead of failing the job.

`AUDIO_PROCESSING_MODE=local` is development fallback only. `AUDIO_PROCESSING_MODE=disabled` disables audio processing.

## Worker Endpoints

Documented worker coordination endpoints:

- `GET /api/v1/worker/jobs/next`
- `POST /api/v1/worker/jobs/{transcription_id}/complete`
- `POST /api/v1/worker/jobs/{transcription_id}/failed`

These endpoints should require `WORKER_API_TOKEN`. Store detailed logs in Modal/backend and return sanitized errors to the frontend. Modal dispatch includes retry/rate-limit handling, and the backend should prefer one active global processing job at a time for MVP stability.

## Status and Result Flow

Clients should poll `GET /api/v1/audio/{id}/status` first. Call `GET /api/v1/audio/{id}/result` only after the status is ready, such as `stem_ready`, `completed`, or `completed_with_warning`. Vocal lyrics use `lyrics_generation_status`, which is separate from the main `processing_status`, so Generate Lyrics should not send users back to the processing screen.

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
