# AI Guitar Music Sheet Generator - Project Overview

## Project Status
- **Current MVP Architecture** - Selected-stem MVP with Railway API/controller, Cloudinary durable storage, and Modal/serverless GPU as the preferred production-like worker
  - Upload or YouTube audio is stored in Cloudinary first
  - User selects one Demucs stem: `vocals`, `drums`, `bass`, or `other`
  - Duplicate same-song/same-stem requests reuse completed results before queueing
  - Guitar transcription uses `other`; guitar/piano/melody may be grouped there depending on model and mix
  - `PROCESSING_MODE=modal` is the preferred production-like path; Modal downloads from Cloudinary, separates only the selected stem on GPU, uploads outputs to Cloudinary, and calls back
  - `PROCESSING_MODE=local` keeps Redis/Celery as fallback/dev mode for very short files only
  - `PROCESSING_MODE=external_worker` supports manual workers such as Kaggle notebooks for testing
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
- None documented. Keep Phase 1 focused on selected-stem processing, Cloudinary persistence, duplicate detection, delete/cancel, and queue/status UX.

## Next Steps (Phase 1: Core Audio Processing Pipeline)
1. Add Modal/serverless GPU worker integration for selected-stem Demucs
2. Add worker endpoints: `GET /api/v1/worker/jobs/next`, `POST /api/v1/worker/jobs/{id}/complete`, and `POST /api/v1/worker/jobs/{id}/failed`
3. Add external worker authentication with `WORKER_API_TOKEN`
4. Add status callback flow from Modal/external workers
5. Keep local Redis/Celery as fallback/dev only with concurrency `1`
6. Document Kaggle as manual testing only, not production infrastructure
7. Keep larger multi-stem and Songsterr-like processing out of the current MVP

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
