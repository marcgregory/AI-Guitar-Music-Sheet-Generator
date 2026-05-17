# Implementation Plan for AI Guitar Music Sheet Generator / MusicStudio

## 2026 Architecture Update: Selected-Stem MVP

The implementation target is now a Railway-friendly selected-stem MVP. Do not run full multi-stem transcription by default.

Current target pipeline:

```txt
Audio Upload / YouTube URL + selected stem
-> Generate audio hash or normalize YouTube ID
-> Check existing completed record with same source + selected stem
-> If duplicate exists, return existing result
-> Upload original audio to Cloudinary
-> Queue processing job
-> Celery worker downloads a temporary local file
-> Demucs selected stem separation
-> Upload separated stem to Cloudinary
-> MIDI conversion for selected stem if supported
-> TAB generation for selected stem if supported
-> Upload outputs to Cloudinary
-> Playback/export/download
```

Demucs default stems are `vocals`, `drums`, `bass`, and `other`. For guitar transcription, use `other` as the MVP target and clearly tell users that guitar/piano/accompaniment may be grouped inside `other` depending on the model and mix. True separate guitar, rhythm guitar, lead guitar, or piano stems require better specialist models later.

Queue policy:
- Only one processing job should run at a time.
- Celery worker concurrency must be `1`.
- New jobs should be queued instead of running concurrently.
- Status responses should distinguish `pending`, `queued`, `processing`, `completed`, and `failed`.
- The app should explain this is intentional to reduce Railway CPU/RAM cost and prevent memory overload.

Cost policy:
- Process one selected stem per job.
- Upload durable files to Cloudinary and save both `secure_url` and `public_id` references.
- Treat Railway local storage as temporary scratch space only.
- Save only the selected separated stem and generated outputs unless caching is explicitly needed.
- Recommend 3-5 minute songs for the MVP.
- Treat full multi-instrument processing as a future premium or GPU-backed feature.
- Selective stem processing reduces CPU usage, RAM usage, storage costs, and processing time.
- Duplicate detection reduces repeated Demucs processing, repeated Cloudinary storage usage, unnecessary queue jobs, and Railway CPU/RAM cost.

Deletion policy:
- Users can delete records in `completed`, `failed`, `queued`, and `processing` states.
- Queued jobs should be removed/cancelled when possible.
- Processing jobs should be marked cancelled/deleted in the database and stopped if cancellation is supported.
- MVP limitation: stopping an active Celery task may not be reliable; the UI record can be hidden/deleted, temporary files should still be cleaned up, and the active worker may finish silently.
- Delete related Cloudinary files when safe: original audio, separated stem audio, MIDI file, and TAB file.
- If Cloudinary deletion fails, keep database deletion safe and log the cleanup error.

Duplicate flow:

```txt
User Upload / YouTube URL + selected stem
-> Generate audio hash or normalize YouTube ID
-> Check existing completed record with same source + selected_stem
-> If found, return existing result
-> If not found, upload/process normally
-> Save result for future reuse
```

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
- [x] Upload original audio to Cloudinary and persist `original_audio_url` plus `original_audio_public_id`
- [x] Generate and persist `audio_hash` for uploaded files
- [x] Normalize YouTube URLs to `normalized_source_id` before duplicate checks
- [x] Check existing completed records by source identity plus `selected_stem` before queueing work
- [x] Return existing result instead of processing duplicate same-song/same-stem requests
- [x] Add audio preprocessing (normalization, resampling) using librosa
- [x] Update upload and YouTube processing requests to require `selected_stem` or `selected_instrument`
- [x] Validate selected stems against Demucs MVP outputs: `vocals`, `drums`, `bass`, `other`
- [x] Implement selected-stem Demucs processing - run separation only for the requested output needed instead of processing every stem by default
- [x] Upload selected separated stem to Cloudinary and persist `separated_audio_url` plus `separated_audio_public_id`
- [x] Persist only the selected separated stem unless caching is explicitly needed
- [x] Implement pitch detection using Spotify Basic Pitch (or CREPE as fallback)
- [x] Implement beat/tempo detection using librosa.beat
- [x] Implement key detection using Essentia or librosa chroma features
- [x] Implement rhythm analysis (onset detection, duration estimation)
- [x] Create basic chord recognition using librosa chroma + template matching
- [x] Design data structure for transcription results (notes, chords, timing)
- [x] Create async processing pipeline with Celery (handle long-running tasks)
- [x] Enforce one active processing job at a time with Celery worker concurrency set to `1`
- [x] Add queue-aware backend status/validation so users know when another job is active
- [x] Add delete/cancel handling for `queued` and `processing` records
- [x] Add confidence scoring for detected elements - note events include per-note confidence/velocity, chord segments include averaged template confidence, tempo uses beat consistency, and key detection returns chroma-template confidence; task storage now persists key confidence from the correct result field
- [x] Implement error handling and fallback for low-confidence sections - Basic Pitch falls back to CLI, then CREPE, then librosa pYIN; selected-stem source separation should fail clearly or fall back only when doing so does not contradict the user-selected target

### Selected-Stem Separation Foundation

- [x] Replace full multi-stem default behavior with selected-stem processing
- [x] Map guitar MVP requests to Demucs `other`
- [x] Add helper text/API metadata explaining that guitar and piano may be inside `other`
- [x] Add fallback behavior when the selected stem is unavailable or low quality
- [x] Add per-stem confidence scoring so users know which instrument tracks are reliable
- [x] Add selected-stem preview endpoint so users can listen to the processed target
- [x] Run pitch detection only for the selected melodic stem when needed
- [x] Generate drum onset/rhythm data only when `drums` is selected
- [ ] Allow users to reprocess the selected stem without rerunning unrelated stems

## Phase 2: Basic Transcription Output & Storage

- [x] Convert pitch detection output to MIDI notes (using music21 or mido)
- [x] Generate fretted-instrument tablature from MIDI notes (guitar/bass fret position mapping)
- [x] Create standard music notation from MIDI (using music21 or VexFlow backend)
- [x] Generate chord charts from detected chords
- [x] Implement export as MIDI file
- [x] Implement export as MusicXML file (using music21)
- [x] Implement export as plain text tabs for tab-capable tracks
- [x] Upload MIDI and TAB outputs to Cloudinary and persist URL/public ID fields
- [x] Store transcription results in database linked to user/project
- [x] Create API endpoints to retrieve transcription data
- [x] Implement automatic cleanup of temporary audio files after processing - uploaded, preprocessed, and separated audio files are deleted at terminal task state while persisted analysis and export data remain available
- [x] Ensure Railway local files are treated as temporary only after Cloudinary upload
- [x] Delete Cloudinary assets when a record is deleted and log cleanup failures safely

### Selected-Stem Output & Storage

- [x] Design database schema for multi-track instrument transcriptions using an `InstrumentTrack` model
- [x] Add/confirm top-level selected job fields: `selected_stem`, `processing_status`, legacy local path fields, and output references
- [x] Add Cloudinary fields: `original_audio_url`, `original_audio_public_id`, `separated_audio_url`, `separated_audio_public_id`, `midi_file_url`, `midi_file_public_id`, `tab_file_url`, `tab_file_public_id`, and `processing_error`
- [x] Add duplicate/deletion fields: `audio_hash`, `source_type`, `source_url`, `normalized_source_id`, `duplicate_of_id`, `is_deleted`, and `deleted_at`
- [x] Store separated stem audio path, notes, chords, tabs, notation, confidence scores, and processing status for the selected stem
- [x] Generate guitar-oriented tablature from Demucs `other` for the MVP
- [x] Generate bass tablature when `bass` is selected
- [x] Generate drum rhythm data when `drums` is selected
- [x] Store transcription results for the selected stem instead of creating all track outputs by default
- [x] Create API endpoint to list available instrument tracks for a transcription
- [x] Create API endpoint to retrieve one instrument track result
- [x] Create API endpoint to stream/play one separated stem
- [ ] Create API endpoint or request path to process/reprocess one selected stem
- [ ] Create API endpoint to export one selected stem as TXT tab, MIDI, MusicXML, or future Guitar Pro format where supported
- [x] Create `DELETE /transcriptions/{id}` for completed, failed, queued, and processing records
- [ ] Create `POST /transcriptions/{id}/cancel` if explicit cancellation is needed separately from delete
- [x] Create API endpoint to update/correct track metadata such as display name, instrument type, and confidence notes

Suggested selected-stem fields:

```txt
Transcription
- id
- selected_stem: vocals | drums | bass | other
- audio_hash
- source_type: upload | youtube
- source_url
- normalized_source_id
- duplicate_of_id
- is_deleted
- deleted_at
- processing_status: pending | queued | processing | completed | failed
- processing_error
- queue_position
- original_audio_url
- original_audio_public_id
- separated_audio_url
- separated_audio_public_id
- midi_file_url
- midi_file_public_id
- tab_file_url
- tab_file_public_id
```

Legacy local path fields such as `separated_audio_file_path`, `midi_file_path`, and `tab_file_path` may remain during migration, but they should not be treated as durable Railway storage.

Existing/new track table can remain for future multi-track expansion:

```txt
InstrumentTrack
- id
- transcription_id
- instrument_type: vocals | drums | bass | other | guitar_alias_for_other
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
- [x] Add required target stem selector before upload/YouTube processing
- [x] Submit `selected_stem` or `selected_instrument` with the upload/process request
- [x] Use Demucs-supported options first: vocals, drums, bass, other
- [x] Mark `other` as the MVP guitar target and explain that guitar/piano may be grouped there
- [x] Create processing status page (progress bar, estimated time) - route wired at `/processing/:transcriptionId`
- [x] Show queue-aware statuses: pending, queued, processing, completed, failed
- [x] Explain when a job is queued because another Railway MVP job is processing
- [ ] Show duplicate reuse message: "This song and stem were already processed. Existing result was loaded."
- [ ] Add delete button for completed, failed, queued, and processing items
- [ ] Show confirmation before deleting a processing record
- [ ] Explain active processing deletion as best-effort cancellation when the worker cannot be stopped reliably
- [x] Design basic transcription viewer (tabs + notation side-by-side) - guitar/bass score views now prefer alphaTab rendering from generated AlphaTex and fall back to the existing custom SVG viewer when needed
- [x] Implement audio playback controls (play/pause, seek, volume)
- [x] Add synchronized playback highlighting (current position in tab/notation)
- [x] Implement playback speed control (0.5x to 2.0x)
- [x] Add zoom controls for notation viewer
- [x] Implement dark/light mode toggle
- [x] Add download buttons for each export format (MIDI, MusicXML, TXT, PDF later) - MIDI, MusicXML, and TAB buttons are wired; PDF remains Phase 6

### Selected-Stem Track Interface

- [x] Prioritize a selected-stem result view over a full multi-stem mixer
- [ ] Add tab/notation/rhythm viewer that changes based on the selected stem
- [ ] Add synchronized playback for the selected separated stem
- [x] Add confidence indicators per instrument track
- [x] Add loading/progress state per instrument, not only per full transcription - selected track status and confidence notes are shown in the viewer
- [ ] Add UX message explaining that lead/rhythm guitar separation and true piano/guitar splitting may require future models

MVP scope recommendation:

1. Selected-stem separation: vocals, drums, bass, or other
2. `other` stem as the MVP guitar transcription target
3. Selected-stem playback and export
4. Queue-aware processing status
5. Multiple selected stems only after MVP stability

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

## Future Roadmap Summary

The selected-stem architecture grows in four steps:

- **Phase 1**: selected stem only, one active processing job at a time, Cloudinary storage integration
- **Phase 2**: multiple selected stems
- **Phase 3**: GPU worker or external AI processing service
- **Phase 4**: full Songsterr-like multi-track tabs

For MVP, prioritize Demucs default stems first: vocals, drums, bass, and other. Lead guitar versus rhythm guitar, true isolated guitar, and true isolated piano should be treated as advanced features because they are harder than default broad stem separation.

Each phase should be completed with code review, testing, and stakeholder feedback before proceeding to the next. Estimated timeline: 6-9 months for MVP (Phases 0-4), additional 3-6 months for full feature set.

## Historical Review Notes

The notes below document earlier implementation slices. Any previous full multi-stem behavior is superseded by the selected-stem MVP architecture described at the top of this plan.

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

## Review Notes - 2026-05-17 Railway Persistence Slice

- Added selected-stem persistence fields for Cloudinary URLs/public IDs, duplicate detection, soft deletion, and queue metadata, with additive schema compatibility and a SQL migration.
- Upload and YouTube ingestion now reuse completed duplicates before queueing, upload originals to Cloudinary when configured, and persist `audio_hash` or normalized YouTube IDs.
- Processing persists exactly one selected separated stem, uploads selected-stem/MIDI/TAB artifacts to Cloudinary when configured, clears queue metadata at terminal states, and treats local files as temporary scratch after durable upload.
- Added `GET /audio/{transcription_id}/tracks/{track_id}/preview`, with Cloudinary redirect for durable stems and HTTP byte-range support for legacy/local stem files.
- Added best-effort `DELETE /transcriptions/{id}` cleanup/cancellation behavior for completed, failed, queued, and processing records. Active Celery task termination remains best-effort for the MVP.
