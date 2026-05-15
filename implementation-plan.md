# Implementation Plan for AI Multi-Instrument Sheet and Stem Studio

## Phase 0: Project Setup & Infrastructure

- [x] Initialize git repository and set up project structure
- [x] Configure development environment (Python, Node.js, Docker)
- [x] Set up backend repository with FastAPI template
- [x] Set up frontend repository with React + Vite + TypeScript template
- [x] Configure Docker Compose for local development (backend, frontend, Redis, PostgreSQL)
- [x] Set up CI/CD pipeline with GitHub Actions (lint, test, build) - frontend job now runs `npm run lint` and `npm run build` instead of a missing `npm test` script
- [x] Initialize database schema (users, projects, transcriptions) - Structure created, execution pending SQLAlchemy/Python 3.13 compatibility resolution RESOLVED
- [x] Implement basic authentication (JWT-based login/register) - Structure created, execution pending SQLAlchemy/Python 3.13 compatibility resolution RESOLVED
- [x] Create basic API health check endpoint

## Phase 1: Core Audio Processing Pipeline

- [x] Implement file upload endpoint (MP3/WAV) with size validation
- [x] Integrate yt-dlp for YouTube audio extraction (temporary storage)
- [x] Add audio preprocessing (normalization, resampling) using librosa
- [x] Implement source separation using Demucs or Spleeter - Demucs dependency enabled; processing now uses the multi-stem `htdemucs_6s` model when available and falls back to vocals/accompaniment or full-mix processing when needed
- [x] Implement pitch detection using Spotify Basic Pitch (or CREPE as fallback)
- [x] Implement beat/tempo detection using librosa.beat
- [x] Implement key detection using Essentia or librosa chroma features
- [x] Implement rhythm analysis (onset detection, duration estimation)
- [x] Create basic chord recognition using librosa chroma + template matching
- [x] Design data structure for transcription results (notes, chords, timing)
- [x] Create async processing pipeline with Celery (handle long-running tasks)
- [x] Add confidence scoring for detected elements - note events include per-note confidence/velocity, chord segments include averaged template confidence, tempo uses beat consistency, and key detection returns chroma-template confidence; task storage now persists key confidence from the correct result field
- [x] Implement error handling and fallback for low-confidence sections - Basic Pitch falls back to CLI, then CREPE, then librosa pYIN; source separation falls back from selected stems to accompaniment or preprocessed audio

### Multi-Instrument Separation Foundation (Moises-style Backend)

- [x] Upgrade source separation from single guitar isolation to multi-stem extraction using Demucs `htdemucs_6s` or equivalent model
- [x] Generate and persist separate stems for vocals, drums, bass, guitar, piano, and other/accompaniment
- [x] Add fallback behavior when a specific stem is unavailable or low quality
- [x] Add per-stem confidence scoring so users know which instrument tracks are reliable
- [x] Add optional stem preview endpoint so users can listen before generating tabs
- [ ] Run pitch detection separately for melodic stems such as guitar, bass, piano, and vocals - guitar and bass stems now generate per-track notes/tabs; piano stems now generate per-track notes/staff notation; vocals remain stem-only for now
- [x] Generate drum onset/rhythm data from the drum stem instead of standard pitch-based tabs - drum tracks now store `drum_hits` rhythm-lane data in `notes_json` while leaving tab/notation empty for this MVP slice
- [x] Allow users to reprocess only one selected instrument track instead of reprocessing the whole song - guitar, bass, and drum tracks can now be reprocessed from retained stems without rerunning full-song separation/transcription

## Phase 2: Basic Transcription Output & Storage

- [x] Convert pitch detection output to MIDI notes (using music21 or mido)
- [x] Generate fretted-instrument tablature from MIDI notes (guitar/bass fret position mapping)
- [x] Create standard music notation from MIDI (using music21 or VexFlow backend)
- [x] Generate chord charts from detected chords
- [x] Implement export as MIDI file
- [x] Implement export as MusicXML file (using music21)
- [x] Implement export as plain text tabs for tab-capable tracks
- [x] Store transcription results in database linked to user/project
- [x] Create API endpoints to retrieve transcription data
- [x] Implement automatic cleanup of temporary audio files after processing - uploaded, preprocessed, and separated audio files are deleted at terminal task state while persisted analysis and export data remain available

### Multi-Track Transcription Output & Storage

- [x] Design database schema for multi-track instrument transcriptions using an `InstrumentTrack` model
- [x] Store separated stem audio paths, notes, chords, tabs, notation, confidence scores, and processing status per instrument track - stem path, confidence, status, guitar/bass per-track notes/tabs, piano notes/notation, and drum rhythm hits are persisted; vocals/other remain stem-only for now
- [x] Generate guitar tablature from the guitar stem
- [x] Generate bass tablature from the bass stem
- [x] Generate piano note data or staff notation from the piano stem
- [ ] Store transcription results per instrument track instead of only one global transcription
- [x] Create API endpoint to list available instrument tracks for a transcription
- [x] Create API endpoint to retrieve one instrument track result
- [x] Create API endpoint to stream/play one separated stem
- [x] Create API endpoint to reprocess one selected instrument track
- [x] Create API endpoint to export one selected instrument as TXT tab, MIDI, MusicXML, or future Guitar Pro format - guitar/bass track exports are available for TXT tab, MIDI, and MusicXML; future Guitar Pro remains post-MVP
- [x] Create API endpoint to update/correct track metadata such as display name, instrument type, and confidence notes

Suggested new table/model:

```txt
InstrumentTrack
- id
- transcription_id
- instrument_type: guitar | bass | piano | drums | vocals | other
- display_name
- stem_audio_path
- notes_json
- chords_json
- tab_json
- notation_json
- confidence_score
- processing_status
- created_at
- updated_at
```

Suggested relationship:

```txt
Transcription
- has many InstrumentTrack records
```

## Phase 3: Frontend - Basic Interface

- [x] Create login/logout/register pages
- [x] Design dashboard layout (projects list, new transcription button) - UI exists and now loads authenticated transcription data from the backend
- [x] Build audio upload component (file drag&drop, YouTube URL input)
- [x] Create processing status page (progress bar, estimated time) - route wired at `/processing/:transcriptionId`
- [x] Design basic transcription viewer (tabs + notation side-by-side) - guitar/bass score views now prefer alphaTab rendering from generated AlphaTex and fall back to the existing custom SVG viewer when needed
- [x] Implement audio playback controls (play/pause, seek, volume)
- [x] Add synchronized playback highlighting (current position in tab/notation)
- [x] Implement playback speed control (0.5x to 2.0x)
- [x] Add zoom controls for notation viewer
- [x] Implement dark/light mode toggle
- [x] Add download buttons for each export format (MIDI, MusicXML, TXT, PDF later) - MIDI, MusicXML, and TAB buttons are wired; PDF remains Phase 6

### Multi-Instrument Track Interface (Moises/Songsterr-style UI)

- [x] Add instrument selector for Guitar, Bass, Piano, Drums, Vocals, and Other - viewer now lists available `InstrumentTrack` rows plus a global Full Mix fallback
- [x] Add mute, solo, and volume controls for each separated stem - transcription viewer now loads available stem audio into a compact mixer with per-track mute/solo/volume controls and synchronized transport
- [x] Add tab/notation viewer that changes based on the selected instrument - guitar/bass tracks use per-track notes/tab JSON, drum tracks show a rhythm lane when `drum_hits` exist, and stem-only tracks show a pending-score state
- [x] Add synchronized playback for separated stems - selected tracks stream their stem audio and drive the existing score playhead when tab data exists
- [x] Add confidence indicators per instrument track
- [x] Add loading/progress state per instrument, not only per full transcription - selected track status and confidence notes are shown in the viewer
- [x] Add UX message explaining that lead/rhythm guitar separation may require manual correction - guitar-track transcriptions now show a non-blocking notice that the MVP produces one broad guitar stem and lead/rhythm parts may be blended

MVP scope recommendation:

1. Multi-stem separation: vocals, drums, bass, guitar, piano, other
2. Track-specific outputs: guitar/bass tabs, drum rhythm lanes, then piano/vocal notation
3. Stem playback with mute/solo controls
4. Instrument selector in the transcription viewer
5. Per-track reprocessing and export where supported

## Phase 4: Enhanced Multi-Instrument Transcription Features

- [x] Add piano note data and staff notation from piano stems
- [ ] Add vocal melody note data and staff notation from vocal stems
- [ ] Extend per-track MIDI/MusicXML exports to piano and vocals - piano MIDI/MusicXML exports are available; vocals remain post-MVP
- [ ] Add drum MIDI or basic drum notation export from drum rhythm lanes
- [ ] Implement capo support for fretted instruments (transpose detection and display)
- [ ] Add alternate tuning support for fretted instruments (standard, drop D, open G, DADGAD, bass tunings, etc.)
- [ ] Improve fret positioning algorithm for fretted-instrument playability (avoid stretches)
- [ ] Implement chord chart generation with finger diagrams
- [ ] Add manual per-track editing interface (tabs, notes, drum hits, and chords)
- [ ] Allow chord name corrections and reharmonization suggestions
- [ ] Implement section-specific reprocessing (re-analyze selected measures)
- [ ] Add suggested alternative transcriptions for low-confidence areas
- [ ] Implement error indicators (highlight uncertain notes/chords)

## Phase 5: Advanced Features & Polish

- [ ] Implement beginner-friendly tab simplification (reduce complexity)
- [ ] Add fingerstyle mode detection and notation for guitar-like tracks
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

### Advanced Multi-Instrument Features

- [ ] Implement lead guitar vs rhythm guitar separation
- [ ] Add basic detection/classification for lead-style guitar phrases versus rhythm/chord guitar sections
- [ ] Provide manual user controls to label a guitar stem section as Lead Guitar or Rhythm Guitar
- [ ] Add future support for splitting one guitar stem into multiple guitar tracks when AI confidence is high enough
- [ ] Add automatic solo extraction
- [ ] Implement AI-assisted instrument role detection
- [ ] Add stem remix/export support
- [ ] Implement real-time stem isolation preview
- [ ] Add warning when lead/rhythm separation is uncertain, since separating multiple similar instruments from a mixed track is harder than broad stem separation

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
- [ ] Expand instrument support beyond MVP stems, including ukulele, strings, synth roles, and improved multi-guitar separation
- [ ] Investigate real-time collaboration features
- [ ] Explore educational institution partnerships
- [ ] Continuously update AI models with new training data
- [ ] Add support for additional export formats (GuitarPro, PowerTab)

## Multi-Instrument Feature Placement Summary

The Moises/Songsterr-style feature is split across the roadmap instead of being treated as a single standalone phase:

- **Phase 1**: source separation, stem generation, per-stem processing, and confidence scoring
- **Phase 2**: multi-track database model, per-instrument tabs/notation, and API endpoints
- **Phase 3**: instrument selector, mute/solo/volume controls, and selected-track viewer
- **Phase 5**: advanced lead/rhythm separation, solo extraction, remix/export, and AI-assisted role detection

For MVP, prioritize broad stems first: vocals, drums, bass, guitar, piano, and other. Lead guitar versus rhythm guitar should be treated as an advanced feature because it is much harder than broad instrument separation.

Each phase should be completed with code review, testing, and stakeholder feedback before proceeding to the next. Estimated timeline: 6-9 months for MVP (Phases 0-4), additional 3-6 months for full feature set.

## Review Notes - 2026-05-13

- Backend verification: `python -m py_compile main.py app\api\v1\endpoints\audio.py app\tasks.py` passed.
- Backend tests: `python -m pytest tests` passed with 4 tests and 6 deprecation warnings.
- Frontend verification: build was not run because `npm`/`npm.cmd` is not available on the current shell PATH.
- Fixed during review: processing route wiring, upload-to-processing redirect, authenticated status/result API calls, missing transcription result API client method, export download API client method/buttons, static serving for uploaded audio files, and Docker Compose frontend API URL.

## Review Notes - 2026-05-14

- Backend service coverage now includes multi-stem separation, stem persistence, task-flow fallback, and cleanup-retention tests in `backend/tests/test_music_output_services.py`.
- Current confidence scoring status: notes, chords, tempo, and key detection produce confidence values, and `process_audio_transcription` persists key confidence from the correct result field.
- Source separation status: Demucs `htdemucs_6s` broad stems are persisted when available, with vocals/accompaniment and preprocessed-audio fallbacks keeping the pipeline usable when separation fails.
- Phase 2 cleanup update: temporary Demucs/Basic Pitch working directories are cleaned, original/preprocessed audio files are deleted at terminal task state, and separated instrument stems are retained for playback.

## Review Notes - 2026-05-14 Multi-Stem Backend Slice

- Added multi-stem source separation that returns available guitar, bass, drums, vocals, piano, and other stems from `htdemucs_6s`, with a vocals/accompaniment fallback when the 6-stem model fails.
- Processing now persists available stems as `InstrumentTrack` rows and keeps the existing global transcription behavior by analyzing guitar first, then other/accompaniment, then preprocessed audio.
- Cleanup now deletes original/preprocessed audio but retains separated stem files so `/tracks/{track_id}/stem` can stream them after processing.

## Review Notes - 2026-05-14 Guitar/Bass Per-Track Output Slice

- Guitar and bass `InstrumentTrack` rows now get track-specific `notes_json` and `tab_json` from their separated stems.
- Bass tablature supports standard 4-string tuning and 4-line ASCII rendering.
- Guitar tracks optionally store per-track notation data when MIDI-to-MusicXML conversion is available.

## Review Notes - 2026-05-14 Frontend Track Viewer Slice

- The transcription viewer now fetches available instrument tracks, offers a Full Mix fallback plus per-track selector, and switches score data/audio playback to the selected track.
- Bass-aware rendering uses the selected track tuning so bass tabs display as four strings.
- Stem-only tracks show playback/status/confidence information with a pending-score state instead of a broken notation view.

## Review Notes - 2026-05-14 Stem Mixer MVP Slice

- Added a multi-stem mixer to the transcription viewer for separated instrument tracks, with synchronized playback transport plus per-stem mute, solo, and volume controls.
- Selecting a mixer row also selects that instrument's score/stem view, while older transcriptions without `InstrumentTrack` rows still use the original single audio player fallback.
- Frontend verification: `npm run build` passed when run through the local Corepack npm shim with the Cursor helper path added for `node`.
- Frontend lint status: direct ESLint on `src/components/TranscriptionViewer.tsx` passed; full `npm run lint` still fails on pre-existing issues in `AudioPlayer.tsx`, `AudioUpload.tsx`, `ProcessingStatus.tsx`, `ThemeProvider.tsx`, `AuthContext.tsx`, `Dashboard.tsx`, `Login.tsx`, and `Register.tsx`.

## Review Notes - 2026-05-14 Lead/Rhythm Guitar UX Warning Slice

- Added a guitar separation notice to the transcription viewer so users understand that the MVP creates one broad guitar stem and lead/rhythm parts may require manual correction.

## Review Notes - 2026-05-14 Per-Track Export Slice

- Added guitar/bass per-track export endpoints for TAB, MIDI, and MusicXML while preserving the existing Full Mix export routes.
- Transcription viewer download buttons now export the selected instrument track when Guitar or Bass is selected, and keep global downloads for Full Mix.
- Backend verification: `python -m py_compile app/api/v1/endpoints/audio.py` passed.
- Backend endpoint tests: `python -m pytest tests/test_audio_list_endpoint.py` passed with 13 tests and existing deprecation warnings.
- Frontend verification: `npm run build` passed through `C:\nvm4w\nodejs\npm.cmd`.

## Review Notes - 2026-05-14 Single-Track Reprocessing Slice

- Added `POST /audio/{transcription_id}/tracks/{track_id}/reprocess` for guitar/bass tracks, using retained separated stems and leaving the global transcription unchanged.
- Track reprocessing clears stale per-track notes/tab/notation data before queueing, regenerates outputs asynchronously, and records useful failed status notes when stem or pitch analysis fails.
- Transcription viewer now exposes a compact selected-track reprocess action for guitar/bass tracks.
- Backend verification: `python -m py_compile app/api/v1/endpoints/audio.py app/tasks.py` passed, and `python -m pytest tests/test_audio_list_endpoint.py tests/test_music_output_services.py` passed with 39 tests and existing warnings.
- Frontend verification: `npm run build` passed through `C:\nvm4w\nodejs\npm.cmd`.

## Review Notes - 2026-05-14 Drum Rhythm Track MVP Slice

- Added drum-stem onset/rhythm analysis that stores `drum_hits` in each drum `InstrumentTrack.notes_json`, with average hit confidence persisted as the track confidence score.
- Drum tracks can now be generated during multi-track processing and reprocessed from retained stems; TAB, MIDI, and MusicXML exports remain limited to guitar/bass tracks.
- The transcription viewer now labels drum tracks with rhythm data as `Rhythm ready` and renders a playback-synced drum rhythm lane instead of the pending-score state.
- Backend verification: `python -m py_compile app/services/audio.py app/tasks.py app/api/v1/endpoints/audio.py` passed, and `python -m pytest tests/test_music_output_services.py tests/test_audio_list_endpoint.py` passed with 43 tests and existing warnings.
- Frontend verification: `npm run build` passed through `C:\nvm4w\nodejs\npm.cmd`.
