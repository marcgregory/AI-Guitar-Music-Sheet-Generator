# Roadmap

## Phase 1: Selected-Stem MVP

- Selected stem only
- Cloudinary persistence for original audio, selected separated stem, and generated outputs
- Cloudinary storage integration
- Railway local storage treated as temporary only
- Duplicate song/stem detection before queueing work
- Delete/cancel processing records from the UI
- Queue/status UX using `pending`, `queued`, `processing`, `completed`, and `failed`
- Recommended song duration: 3-5 minutes

## Phase 2: Modal/Serverless GPU Worker

- Modal/serverless GPU worker integration
- Worker endpoints: `GET /api/v1/worker/jobs/next`, `POST /api/v1/worker/jobs/{id}/complete`, and `POST /api/v1/worker/jobs/{id}/failed`
- External worker authentication with `WORKER_API_TOKEN`
- Status callback flow from worker to backend
- Selected-stem preview and export from Cloudinary outputs

## Phase 3: Multiple Stems and Reliability

- Multiple selected stems
- Improved transcription quality
- Better retry/recovery
- More robust queue recovery and worker logs

## Phase 4: Songsterr-Like Multi-Track Tabs

- Full multi-track synchronized tab/notation experience
- Lead/rhythm guitar separation
- Piano/guitar specialist models
- Better specialist separation for guitar, piano, lead/rhythm guitar, and other roles
- More complete per-track MIDI, TAB, MusicXML, and sharing workflows

## Out of Scope for Phase 1

- Large-scale concurrent AI processing
- Full automatic all-stem transcription
- True isolated lead guitar/rhythm guitar/piano separation
- Songsterr-like complete multi-track tabs
- Kaggle as production infrastructure
- Railway free/trial Demucs processing as production infrastructure
