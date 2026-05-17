# AI Guitar Music Sheet Generator - Project Overview

## Project Status
- **Current MVP Architecture** - Selected-stem Railway MVP with Cloudinary durable storage
  - Upload or YouTube audio is stored in Cloudinary first
  - User selects one Demucs stem: `vocals`, `drums`, `bass`, or `other`
  - Duplicate same-song/same-stem requests reuse completed results before queueing
  - Guitar transcription uses `other`; guitar/piano/melody may be grouped there depending on model and mix
  - Redis/Celery queues processing and the worker runs with concurrency `1`
  - Worker downloads temporary audio, separates only the selected stem, uploads outputs to Cloudinary, then cleans local files
  - Users can delete completed, failed, queued, and processing records; active cancellation is best-effort in the MVP
- **Phase 0: Project Setup & Infrastructure** - COMPLETED ✅
  - Git repository initialized
  - Backend: FastAPI with modular structure
  - Frontend: React + Vite + TypeScript
  - Docker Compose configured (backend, frontend, PostgreSQL, Redis)
  - CI/CD pipeline with GitHub Actions
  - SQLAlchemy/Python 3.13 compatibility issue RESOLVED
  - Database schema initialization functional
  - Authentication framework (JWT with bcrypt) implemented

## Current Blockers
- None documented. Keep Phase 1 focused on selected-stem processing, one active job at a time, and Cloudinary storage integration.

## Next Steps (Phase 1: Core Audio Processing Pipeline)
1. Upload original audio to Cloudinary after file upload or YouTube extraction
2. Require `selected_stem` before queueing processing
3. Check duplicates with `audio_hash` or normalized YouTube/source ID plus `selected_stem`
4. Use Redis/Celery with worker concurrency `1`
5. Run Demucs only for the selected stem
6. Upload selected separated stem, MIDI output, and TAB output to Cloudinary when generated
7. Store Cloudinary `secure_url` and `public_id` fields plus duplicate/deletion/status fields
8. Add delete/cancel behavior and Cloudinary cleanup for processing records
9. Clean temporary Railway worker files after `completed`, `failed`, or deleted/cancelled status
10. Keep larger multi-stem and concurrent AI processing out of Phase 1

## Technology Stack
- **Frontend**: React + TypeScript + Vite
- **Backend**: Python + FastAPI
- **Database**: PostgreSQL + SQLAlchemy ORM
- **Authentication**: JWT with bcrypt password hashing
- **Task Queue**: Celery with Redis
- **Storage**: Cloudinary for durable audio/output files; Railway local disk for temporary processing only
- **Audio Processing**: Librosa, Essentia, Demucs/Spleeter, Spotify Basic Pitch
- **Music Notation**: music21 or VexFlow
- **DevOps**: Docker, Docker Compose, GitHub Actions
- **Testing**: Pytest, Jest + React Testing Library

## Important Notes
- SQLAlchemy/Python 3.13 compatibility was resolved by upgrading to SQLAlchemy 2.1.0b2
- Pydantic V2 compatibility fixed by migrating to pydantic-settings
- Database tables can now be created successfully using the initialized schema
- Authentication endpoints are functional with real database backend
- Memory system initialized at ./memory/ for tracking project context
- Used Context7 to fetch up-to-date documentation for key libraries (SQLAlchemy, Librosa, FastAPI) during development

## Context7 Documentation References
During development, I used Context7 to obtain current documentation for:
- **SQLAlchemy 2.1.0b2**: Table creation, session setup, and ORM usage patterns
- **Librosa**: Audio loading, feature extraction (chroma, beat tracking, onset detection), and preprocessing
- **FastAPI**: JWT authentication implementation, dependency injection, and security best practices
This ensured implementation followed current best practices and API standards.

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
├── deployment.md             # Railway/Cloudinary deployment notes
├── implementation-plan.md    # Detailed phased implementation plan
├── queue-worker.md           # Celery queue and worker policy
├── roadmap.md                # MVP roadmap
├── setup.md                  # Local setup checklist
├── storage.md                # Cloudinary storage strategy
├── PHASE0_COMPLETED.md       # Documentation of completed Phase 0 work
├── tech-stack.md             # Recommended open-source tech stack
└── README.md                 # Project overview
```
