# Setup Notes

## Local Services

Local development needs:

- FastAPI backend
- React/Vite frontend
- PostgreSQL or SQLite for development
- Redis/Celery only for `AUDIO_PROCESSING_MODE=local` development fallback
- Cloudinary account for durable media/output storage
- Modal account for production-like GPU processing with `AUDIO_PROCESSING_MODE=modal`

## Backend Environment

Set these values in the backend environment:

- `DATABASE_URL`
- `AUDIO_PROCESSING_MODE=modal` for hosted MVP backends
- `WORKER_API_TOKEN`
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`
- `REDIS_URL` if using local Celery/status coordination
- `MODAL_TRIGGER_URL` when using `AUDIO_PROCESSING_MODE=modal`
- `CELERY_BROKER_URL` if using `AUDIO_PROCESSING_MODE=local`
- `CELERY_RESULT_BACKEND` if using `AUDIO_PROCESSING_MODE=local`
- `MODAL_TOKEN_ID` if deploying/testing Modal
- `MODAL_TOKEN_SECRET` if deploying/testing Modal
- `YOUTUBE_COOKIES` or `YOUTUBE_COOKIES_FILE` for YouTube downloads that require fresh cookies
- `WHISPER_MODEL_SIZE`
- `WHISPER_LANGUAGE`
- `WHISPER_BEAM_SIZE`
- `WHISPER_BEST_OF`
- `WHISPER_VAD_FILTER`
- `WHISPER_CONDITION_ON_PREVIOUS_TEXT`
- `WHISPER_INITIAL_PROMPT`

## Frontend Environment

Set:

- `VITE_API_URL`

## Worker

For local fallback only, start the Celery worker with one active processing slot:

```sh
celery -A app.celery worker --loglevel=info --concurrency=1
```

For `AUDIO_PROCESSING_MODE=modal`, the Modal worker should use GPU, download `original_audio_url`, run Demucs for the selected stem, run stem-aware generation, upload outputs to Cloudinary, and report completion/failure to the backend. Modal handles heavy AI/audio work, including selected-stem separation, Basic Pitch-style note detection for `other`/`bass`, rhythm/onset lanes for `drums`, faster-whisper lyrics for `vocals`, and retry/rate-limit handling.

Worker callback endpoints:

- `GET /api/v1/worker/jobs/next`
- `POST /api/v1/worker/jobs/{transcription_id}/complete`
- `POST /api/v1/worker/jobs/{transcription_id}/failed`

## MVP Test Flow

1. Upload an MP3/WAV file or submit a YouTube URL.
2. Select exactly one stem: `vocals`, `drums`, `bass`, or `other`.
3. Confirm uploaded files generate `audio_hash` and YouTube URLs generate `normalized_source_id`.
4. Confirm duplicate same-song/same-stem requests return the existing completed result.
5. Confirm the original audio is uploaded to Cloudinary when no duplicate exists.
6. Confirm status moves through `queued` or `processing`.
7. Confirm the selected separated stem is uploaded to Cloudinary.
8. Confirm pitch/rhythm/onset detection runs on the separated selected stem.
9. Confirm `other` renders as 6-string guitar tab/score where generated.
10. Confirm `bass` renders as 4-string E A D G bass tab/score where generated.
11. Confirm `drums` renders a rhythm lane/percussion tab where generated.
12. Confirm `vocals` supports selected-stem playback and Generate Lyrics using separate `lyrics_generation_status`.
13. Confirm synchronized playback uses one shared `currentTime` for waveform, playhead, tabs, score, active notes/hits, and selected-stem audio.
14. Confirm MIDI, MusicXML, and TAB exports are uploaded only when supported.
15. Confirm users can delete completed, completed_with_warning, failed, queued, and processing records.
16. Confirm deletion cleans Cloudinary assets when safe and logs cleanup failures.
17. Confirm temporary local files are cleaned after terminal or deleted/cancelled status.
18. Confirm frontend polling calls `/status` first and calls `/result` only after a ready status.
19. Confirm Generate Lyrics keeps the viewer open and does not reset the main `processing_status`.

Future roadmap only:

- MIDI import.
- Guitar Pro import.
- PowerTab import/export.
- Imported project editing.
- Imported multi-track workflows.
