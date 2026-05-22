# AI Guitar Music Sheet Generator - Project Overview

## Project Status
- **Current MVP Architecture** - Selected-stem audio/YouTube transcription MVP with Railway API/controller, Cloudinary durable storage, and Modal/serverless GPU as the preferred production-like worker for Demucs jobs
  - Supported input types: audio upload and YouTube URL
  - Upload or YouTube audio is stored in Cloudinary first
  - User selects one Demucs stem: `vocals`, `drums`, `bass`, or `other`
  - Duplicate same-song/same-stem requests reuse completed results before queueing
  - Guitar transcription uses `other`; guitar/piano/melody may be grouped there depending on model and mix
  - Bass transcription uses the `bass` stem and renders standard 4-string E A D G bass tab
  - Drum transcription uses the `drums` stem for hit/onset analysis, rhythm lane rendering, percussion tab, and drum MIDI export where possible
  - Vocals support selected-stem playback and Generate Lyrics via faster-whisper; lyric work uses `lyrics_generation_status`, separate from `processing_status`
  - Playback must share one `currentTime` across waveform, playhead, tabs, score, active notes, and selected-stem audio
  - `AUDIO_PROCESSING_MODE=modal` is the hosted MVP path; Modal downloads from Cloudinary, separates only the selected stem on GPU, performs stem-specific generation, uploads outputs to Cloudinary, and calls back
  - `AUDIO_PROCESSING_MODE=local` is fallback/dev mode for very short files only; `AUDIO_PROCESSING_MODE=disabled` disables processing
  - Result fetching is status-first: poll `/status`, then call `/result` only after a ready status such as `stem_ready`, `completed`, or `completed_with_warning`
  - Users can delete completed, completed_with_warning, failed, queued, and processing records; active cancellation is best-effort in the MVP
- **Phase 0: Project Setup & Infrastructure** - COMPLETED
  - Git repository initialized
  - Backend: FastAPI with modular structure
  - Frontend: React + Vite + TypeScript
  - Docker Compose configured (backend, frontend, PostgreSQL, Redis)
  - CI/CD pipeline with GitHub Actions
  - SQLAlchemy/Python 3.13 compatibility issue resolved
  - Database schema initialization functional
  - Authentication framework (JWT with bcrypt) implemented

## Current Blockers
- None documented. Keep Phase 1 focused on selected-stem audio/YouTube processing, synchronized playback, instrument-aware rendering, Cloudinary persistence, duplicate detection, delete/cancel, and queue/status UX.

## Next Steps (Phase 1: Core Audio Processing Pipeline)
1. Stabilize selected-stem processing.
2. Improve stem-aware transcription.
3. Finish bass tab generation.
4. Finish drum rhythm lane/percussion tab generation.
5. Improve playback timing accuracy and shared `currentTime` sync.
6. Stabilize MIDI, MusicXML, and TAB exports generated from separated-stem transcription results.
7. Harden duplicate reuse and Cloudinary persistence.
8. Keep MIDI import, Guitar Pro import, PowerTab import/export, imported project editing, larger multi-stem, and imported multi-track workflows out of the current MVP.

## Technology Stack
- **Frontend**: React + TypeScript + Vite
- **Backend**: Python + FastAPI
- **Database**: PostgreSQL + SQLAlchemy ORM
- **Authentication**: JWT with bcrypt password hashing
- **Task Queue / Worker Coordination**: FastAPI job orchestration; Redis/Celery for local fallback; Modal/serverless GPU for preferred processing
- **Storage**: Cloudinary for durable audio/output files; Railway local disk for temporary processing only
- **Audio Processing**: Modal GPU worker plus Librosa, Essentia, Demucs, Spotify Basic Pitch
- **Music Notation**: music21 or VexFlow
- **DevOps**: Docker, Docker Compose, GitHub Actions
- **Testing**: Pytest, Jest + React Testing Library

## Important Notes
- MIDI export, MusicXML export, and TAB export stay in scope.
- MIDI import, Guitar Pro import, PowerTab import/export, and imported project editing are future roadmap only.
- SQLAlchemy/Python 3.13 compatibility was resolved by upgrading to SQLAlchemy 2.1.0b2.
- Pydantic V2 compatibility fixed by migrating to pydantic-settings.
- Database tables can now be created successfully using the initialized schema.
- Authentication endpoints are functional with real database backend.
- Memory system initialized at ./memory/ for tracking project context.

## File Structure
```
.
├── backend/                  # FastAPI backend
├── frontend/                 # React + Vite frontend
├── memory/                   # Claude Code memory storage
├── .github/                  # GitHub Actions CI/CD
├── docker-compose.yml        # Multi-service orchestration
├── CLAUDE.md                 # This file
├── architecture.md           # Selected-stem MVP architecture
├── api.md                    # API and data contract
├── deployment.md             # Railway/Cloudinary/Modal deployment notes
├── implementation-plan.md    # Detailed phased implementation plan
├── queue-worker.md           # Queue and worker policy
├── roadmap.md                # MVP roadmap
├── setup.md                  # Local setup checklist
├── storage.md                # Cloudinary storage strategy
├── PHASE0_COMPLETED.md       # Documentation of completed Phase 0 work
├── tech-stack.md             # Recommended open-source tech stack
└── README.md                 # Project overview
```
