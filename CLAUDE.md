# AI Guitar Music Sheet Generator - Project Overview

## Project Status
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
- None - Phase 0 is complete and ready for Phase 1

## Next Steps (Phase 1: Core Audio Processing Pipeline)
1. Implement file upload endpoint (MP3/WAV) with size validation
2. Integrate yt-dlp for YouTube audio extraction
3. Add audio preprocessing using librosa (normalization, resampling)
4. Implement source separation for guitar isolation (Demucs or Spleeter)
5. Implement pitch detection (Spotify Basic Pitch or CREPE)
6. Implement beat/tempo detection using librosa.beat
7. Implement key detection using Essentia or librosa chroma features
8. Implement rhythm analysis (onset detection, duration estimation)
9. Create basic chord recognition using librosa chroma + template matching
10. Design data structure for transcription results
11. Create async processing pipeline with Celery
12. Add confidence scoring for detected elements
13. Implement error handling and fallback for low-confidence sections

## Technology Stack
- **Frontend**: React + TypeScript + Vite
- **Backend**: Python + FastAPI
- **Database**: PostgreSQL + SQLAlchemy ORM
- **Authentication**: JWT with bcrypt password hashing
- **Task Queue**: Celery with Redis
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
├── implementation-plan.md    # Detailed phased implementation plan
├── PHASE0_COMPLETED.md       # Documentation of completed Phase 0 work
├── tech-stack.md             # Recommended open-source tech stack
└── README.md                 # Project overview
```