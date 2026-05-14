# Implementation Plan for AI Guitar Music Sheet Generator

## Phase 0: Project Setup & Infrastructure

- [x] Initialize git repository and set up project structure
- [x] Configure development environment (Python, Node.js, Docker)
- [x] Set up backend repository with FastAPI template
- [x] Set up frontend repository with React + Vite + TypeScript template
- [x] Configure Docker Compose for local development (backend, frontend, Redis, PostgreSQL)
- [ ] Set up CI/CD pipeline with GitHub Actions (lint, test, build) - workflow exists, but frontend job calls `npm test` even though no test script exists; needs correction before this is complete
- [x] Initialize database schema (users, projects, transcriptions) - Structure created, execution pending SQLAlchemy/Python 3.13 compatibility resolution RESOLVED
- [x] Implement basic authentication (JWT-based login/register) - Structure created, execution pending SQLAlchemy/Python 3.13 compatibility resolution RESOLVED
- [x] Create basic API health check endpoint

## Phase 1: Core Audio Processing Pipeline

- [x] Implement file upload endpoint (MP3/WAV) with size validation
- [x] Integrate yt-dlp for YouTube audio extraction (temporary storage)
- [x] Add audio preprocessing (normalization, resampling) using librosa
- [x] Implement source separation using Demucs or Spleeter (guitar isolation) - Demucs dependency enabled; processing now prefers the `htdemucs_6s` guitar stem and falls back to vocals/accompaniment separation when needed
- [x] Implement pitch detection using Spotify Basic Pitch (or CREPE as fallback)
- [x] Implement beat/tempo detection using librosa.beat
- [x] Implement key detection using Essentia or librosa chroma features
- [x] Implement rhythm analysis (onset detection, duration estimation)
- [x] Create basic chord recognition using librosa chroma + template matching
- [x] Design data structure for transcription results (notes, chords, timing)
- [x] Create async processing pipeline with Celery (handle long-running tasks)
- [x] Add confidence scoring for detected elements - note events include per-note confidence/velocity, chord segments include averaged template confidence, tempo uses beat consistency, and key detection returns chroma-template confidence; task storage for `key_confidence` still needs a field-name correction
- [x] Implement error handling and fallback for low-confidence sections - Basic Pitch falls back to CLI, then CREPE, then librosa pYIN; source separation falls back from guitar stem extraction to accompaniment or preprocessed audio

## Phase 2: Basic Transcription Output & Storage

- [x] Convert pitch detection output to MIDI notes (using music21 or mido)
- [x] Generate guitar tablature from MIDI notes (fret position mapping)
- [x] Create standard music notation from MIDI (using music21 or VexFlow backend)
- [x] Generate chord charts from detected chords
- [x] Implement export as MIDI file
- [x] Implement export as MusicXML file (using music21)
- [x] Implement export as plain text guitar tabs
- [x] Store transcription results in database linked to user/project
- [x] Create API endpoints to retrieve transcription data
- [x] Implement automatic cleanup of temporary audio files after processing - uploaded, preprocessed, and separated audio files are deleted at terminal task state while persisted analysis and export data remain available

## Phase 3: Frontend - Basic Interface

- [x] Create login/logout/register pages
- [x] Design dashboard layout (projects list, new transcription button) - UI exists, currently backed by mock project data
- [x] Build audio upload component (file drag&drop, YouTube URL input)
- [x] Create processing status page (progress bar, estimated time) - route wired at `/processing/:transcriptionId`
- [x] Design basic transcription viewer (tabs + notation side-by-side) - displays tablature/MusicXML data; notation rendering is still raw MusicXML, not staff notation
- [x] Implement audio playback controls (play/pause, seek, volume)
- [x] Add synchronized playback highlighting (current position in tab/notation)
- [x] Implement playback speed control (0.5x to 2.0x)
- [x] Add zoom controls for notation viewer
- [x] Implement dark/light mode toggle
- [x] Add download buttons for each export format (MIDI, MusicXML, TXT, PDF later) - MIDI, MusicXML, and TAB buttons are wired; PDF remains Phase 6

## Phase 4: Enhanced Transcription Features

- [ ] Implement capo support (transpose detection and display)
- [ ] Add alternate tuning support (standard, drop D, open G, DADGAD, etc.)
- [ ] Improve fret positioning algorithm for playability (avoid stretches)
- [ ] Implement chord chart generation with finger diagrams
- [ ] Add manual tab editing interface (move notes between strings/frets)
- [ ] Allow chord name corrections and reharmonization suggestions
- [ ] Implement section-specific reprocessing (re-analyze selected measures)
- [ ] Add suggested alternative transcriptions for low-confidence areas
- [ ] Implement error indicators (highlight uncertain notes/chords)

## Phase 5: Advanced Features & Polish

- [ ] Implement beginner-friendly tab simplification (reduce complexity)
- [ ] Add fingerstyle mode detection and notation
- [ ] Implement solo extraction (melody line separation)
- [ ] Create AI-generated practice suggestions (difficult sections, exercises)
- [ ] Add difficulty scoring for transcriptions
- [ ] Implement real-time transcription support (experimental, WebAssembly)
- [ ] Add animated note highlighting during playback
- [ ] Implement looping specific sections for practice
- [ ] Add metronome click track option
- [ ] Create tutorial/onboarding flow for new users
- [ ] Add tooltips for music theory terms
- [ ] Implement colorblind-friendly palettes for notation

## Phase 6: Export & Sharing

- [ ] Implement PDF export using WeasyPrint or ReportLab (styled sheet music)
- [ ] Add option to download sheet as image (PNG/SVG)
- [ ] Add sharing options (generate shareable link for view-only access)
- [ ] Implement version history for edited transcriptions
- [ ] Add collaborative commenting on transcriptions (future)
- [ ] Create print-friendly view with appropriate margins

## Phase 7: Testing, Performance & Optimization

- [x] Create unit tests for audio processing components - 6 backend service tests cover chord charts, enhanced pitch-info output shape, MIDI/tab generation, Basic Pitch CSV normalization, and Demucs source-separation fallback behavior; broader audio accuracy coverage still needed
- [ ] Implement integration tests for API endpoints
- [ ] Add frontend component testing (Jest + React Testing Library)
- [ ] Conduct accuracy testing with known songs benchmark suite
- [ ] Optimize audio processing pipeline (batch processing, GPU acceleration exploration)
- [ ] Implement caching for repeated processing of same audio
- [ ] Add rate limiting and usage tracking for cost management
- [ ] Perform load testing with Celery worker scaling
- [ ] Optimize bundle size (code splitting, lazy loading)
- [ ] Implement service worker for PWA capabilities (offline viewing)

## Phase 8: Deployment & Production Readiness

- [ ] Set up production Docker images (multi-stage builds)
- [ ] Configure Kubernetes deployment manifests (or Docker Swarm)
- [ ] Set up monitoring (Prometheus metrics, Grafana dashboards)
- [ ] Implement logging aggregation (ELK or Loki)
- [ ] Configure SSL/TLS with Let's Encrypt via ingress
- [ ] Set up automated backups for database and storage
- [ ] Implement security scanning (OWASP ZAP, dependency checks)
- [ ] Create documentation for administrators and developers
- [ ] Prepare privacy policy and terms of service
- [ ] Set up error tracking (Sentry or similar)
- [ ] Conduct user acceptance testing with musician community

## Phase 9: Post-Launch & Iteration

- [ ] Collect user feedback and accuracy reports
- [ ] Prioritize bug fixes and usability improvements
- [ ] Plan for premium features (subscription model)
- [ ] Expand instrument support (bass, ukulele) based on demand
- [ ] Investigate real-time collaboration features
- [ ] Explore educational institution partnerships
- [ ] Continuously update AI models with new training data
- [ ] Add support for additional export formats (GuitarPro, PowerTab)

Each phase should be completed with code review, testing, and stakeholder feedback before proceeding to the next. Estimated timeline: 6-9 months for MVP (Phases 0-4), additional 3-6 months for full feature set.

## Review Notes - 2026-05-13

- Backend verification: `python -m py_compile main.py app\api\v1\endpoints\audio.py app\tasks.py` passed.
- Backend tests: `python -m pytest tests` passed with 4 tests and 6 deprecation warnings.
- Frontend verification: build was not run because `npm`/`npm.cmd` is not available on the current shell PATH.
- Fixed during review: processing route wiring, upload-to-processing redirect, authenticated status/result API calls, missing transcription result API client method, export download API client method/buttons, static serving for uploaded audio files, and Docker Compose frontend API URL.

## Review Notes - 2026-05-14

- Backend service coverage now includes 6 tests in `backend/tests/test_music_output_services.py`.
- Current confidence scoring status: notes, chords, tempo, and key detection produce confidence values; `process_audio_transcription` stores tempo confidence but currently reads `key_confidence` from the wrong key name, so persisted key confidence remains a follow-up fix.
- Source separation status: Demucs `htdemucs_6s` guitar stem is preferred, with accompaniment and preprocessed-audio fallbacks keeping the pipeline usable when separation fails.
- Phase 2 cleanup update: temporary Demucs/Basic Pitch working directories are cleaned, and retained upload, preprocessed, and separated audio files are now deleted when processing reaches a terminal state. MIDI and database-backed export data are retained/regenerated for downloads.
