# Implementation Plan for AI Guitar Music Sheet Generator / MusicStudio

## 2026 Architecture Update: Selected-Stem MVP + Modal Worker

The implementation target is a selected-stem MVP where Railway/Render is the lightweight API/controller for auth, DB records, status polling, Cloudinary references, and Modal dispatch/callbacks. Modal GPU is the production processing target for heavy audio/AI work. Do not run full multi-stem transcription by default, and do not treat Railway/Render resources as reliable Demucs, Basic Pitch, faster-whisper, or audio-analysis production infrastructure.

Current target pipeline:

```txt
Audio Upload / YouTube URL + selected stem
-> Generate audio hash or normalize YouTube ID
-> Check existing completed record with same source + selected stem
-> If duplicate exists, return existing result
-> Upload original audio to Cloudinary
-> Queue processing job
-> Trigger Modal GPU worker
-> Modal worker downloads original audio from Cloudinary
-> Worker runs Demucs selected-stem separation on GPU when available
-> Worker uploads selected separated stem to Cloudinary
-> Worker normalizes selected separated stem volume
-> Worker runs Basic Pitch-style note detection only for melodic non-vocal stems (`other`, `bass`)
-> Worker runs onset/rhythm analysis only for `drums`
-> Worker runs faster-whisper lyrics generation for `vocals`
-> Worker generates instrument-aware tabs/notation/rhythm data where supported
-> Worker optionally generates MIDI/MusicXML/TAB exports if supported
-> Worker calls backend complete/failed endpoint
-> Backend updates transcription status and output references
-> Frontend polls status and renders synchronized playback with playhead/waveform plus export/download
```

Demucs default stems are `vocals`, `drums`, `bass`, and `other`. For guitar/accompaniment transcription, use `other` as the MVP target and clearly tell users that guitar, piano, synths, melody, or accompaniment may be grouped inside `other` depending on the model and mix. Do not market the MVP as isolated lead guitar transcription or promise perfect Songsterr-level accuracy. True separate guitar, rhythm guitar, lead guitar, or piano stems require better specialist models later.

Queue policy:
- New jobs should be queued instead of running heavy AI work in request handlers.
- Status responses should distinguish `pending`, `queued`, `processing`, `stem_ready`, `completed`, `completed_with_warning`, and `failed`.
- A no-note result after successful stem separation is `completed_with_warning`/API `completed`, not `failed`.
- In `AUDIO_PROCESSING_MODE=modal`, Modal GPU handles heavy audio/AI work.
- In `AUDIO_PROCESSING_MODE=local`, Celery worker concurrency must be `1` and should process very short files only.
- Result fetching is status-first: poll `/status`, then call `/result` only after a ready status such as `stem_ready`, `completed`, or `completed_with_warning`.

Cost policy:
- Process one selected stem per job.
- Upload durable files to Cloudinary and save both `secure_url` and `public_id` references.
- Treat Railway local storage as temporary scratch space only.
- Save only the selected separated stem and generated outputs unless caching is explicitly needed.
- Recommend 3-5 minute songs for the MVP.
- Treat full multi-instrument processing as a future premium or GPU-backed feature.
- Treat Kaggle as optional/manual GPU testing only, not 24/7 infrastructure.
- Selective stem processing reduces CPU usage, RAM usage, storage costs, and processing time.
- Duplicate detection reduces repeated Demucs processing, repeated Cloudinary storage usage, unnecessary queue jobs, and Railway CPU/RAM cost.

Processing mode:

- `AUDIO_PROCESSING_MODE=modal`: hosted MVP mode; backend triggers Modal GPU processing.
- `AUDIO_PROCESSING_MODE=local`: development fallback. Local Celery can process very short files only and is not recommended for production.
- `AUDIO_PROCESSING_MODE=disabled`: disables audio processing.

Required worker/environment variables:

- `AUDIO_PROCESSING_MODE=modal`
- `MODAL_TRIGGER_URL`
- `WORKER_API_TOKEN`
- `MODAL_TOKEN_ID`
- `MODAL_TOKEN_SECRET`
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`
- `YOUTUBE_COOKIES` or `YOUTUBE_COOKIES_FILE`
- `WHISPER_MODEL_SIZE`
- `WHISPER_LANGUAGE`
- `WHISPER_BEAM_SIZE`
- `WHISPER_BEST_OF`
- `WHISPER_VAD_FILTER`
- `WHISPER_CONDITION_ON_PREVIOUS_TEXT`
- `WHISPER_INITIAL_PROMPT`

Worker endpoints to add/document:

- `GET /api/v1/worker/jobs/next`
- `POST /api/v1/worker/jobs/{transcription_id}/complete`
- `POST /api/v1/worker/jobs/{transcription_id}/failed`
- `POST /api/v1/audio/{transcription_id}/retry`

Warning/capability rules:

- Preserve separated stem playback, local/cloud stem references, waveform/rhythm data, and stem metadata when note detection finds zero notes.
- Set `warning_message`, `can_play_stem=true`, `can_generate_score=false`, and increment `transcription_attempts`.
- Return status payloads like `{"status":"completed","warning":"No note events detected for this stem.","can_play_stem":true,"can_generate_score":false}`.
- Persist zero-note melodic results as `completed_with_warning` when separation succeeds; API responses may expose `status="completed"` plus warning/capability flags for compatibility.
- Disable only score/TAB/MIDI/MusicXML export generation for no-note stems. Stem playback remains available.

Basic Pitch and fallback transcription behavior:

- Use Basic Pitch-style note detection as the primary note detection path for selected melodic non-vocal stems.
- Run note detection only for `other` and `bass`; do not run Basic Pitch-style note detection on `vocals` or `drums`.
- Lower the default Basic Pitch note confidence threshold and expose sensitivity through configuration.
- Normalize separated stem volume before Basic Pitch transcription.
- Retry Basic Pitch with lower-threshold/high-sensitivity settings when the first pass detects zero notes.
- Log RMS loudness, peak amplitude, onset count, note confidence stats, selected stem, and transcription model output metadata.

Stem support matrix:

- `vocals`: selected-stem playback plus Generate Lyrics using faster-whisper. Lyrics use `lyrics_generation_status`, separate from main audio `processing_status`.
- `drums`: analyze drum stem with onset/rhythm detection only; do not use Basic Pitch; generate a drum rhythm lane and percussion/drum tab where possible, support synchronized playback highlighting, and support drum MIDI export when possible.
- `bass`: analyze bass stem with Basic Pitch, generate 4-string bass tablature using standard tuning E A D G, generate bass score data, and support synchronized playback/playhead highlighting.
- `other`: primary guitar/accompaniment transcription target; analyze with Basic Pitch, generate guitar-oriented tablature, score notation, and synchronized playback/playhead highlighting.

Primary MVP architecture:

```txt
Audio/YouTube
-> selected stem separation
-> instrument-aware transcription
-> synchronized playback
-> tab/score/rhythm rendering
```

The app focus is generating practical tabs/rhythm/lyrics views from one selected output stem, synchronized practice playback, instrument-aware rendering, and fast selected-stem turnaround. MIDI import, Guitar Pro import, PowerTab import/export, imported project playback architecture, imported project editing, advanced Songsterr-like multi-track workflows, and isolated lead/rhythm guitar workflows are future roadmap only. Do not treat them as MVP work. MIDI export, MusicXML export, and TAB export remain in scope when generated from separated-stem transcription results.

Instrument-aware rendering architecture:

- Guitar/`other` renders as 6-string tablature.
- Bass renders as 4-string bass tablature.
- Drums render as a rhythm lane/percussion tab.
- Vocals render selected-stem playback and lyrics when generated.
- All views share synchronized playback using waveform, playhead, tabs, score, active notes/hits, and selected-stem playback.

Synchronized playback requirements:

- moving playhead
- note highlighting
- waveform sync
- seek synchronization
- shared `currentTime`
- tab/score sync
- stem playback sync

Do not use separate timers for waveform, tabs, and score. The viewer should derive all synchronization from one shared playback clock/current time source.

Highest frontend priorities:

1. selected stem playback sync
2. synchronized tab highlighting
3. synchronized score highlighting
4. waveform sync
5. instrument-aware rendering
6. stem metadata visibility
7. drum rhythm lane rendering
8. bass tab rendering

Highest backend priorities:

1. selected-stem processing stability
2. Basic Pitch quality for selected melodic stems
3. bass tab generation
4. drum rhythm lane generation
5. playback timing accuracy
6. export stability
7. duplicate reuse
8. Cloudinary persistence

Modal worker rules:

- Process selected-stem only.
- Use GPU.
- Download `original_audio_url` from Cloudinary.
- Run Demucs with `vocals`, `drums`, `bass`, or `other`.
- Normalize the selected separated stem before transcription.
- Run Basic Pitch-style note detection only for melodic non-vocal selected stems: `other` and `bass`.
- Run drum onset/rhythm analysis for `drums`; do not run Basic Pitch-style note detection on drum stems.
- Run faster-whisper lyrics generation for `vocals`.
- Upload separated stem and supported outputs to Cloudinary.
- Report completion/failure to the backend.
- Keep full logs in Modal/backend and sanitize frontend errors.

Deletion policy:
- Users can delete records in `completed`, `completed_with_warning`, `failed`, `queued`, and `processing` states.
- Queued jobs should be removed/cancelled when possible.
- Processing jobs should be marked cancelled/deleted in the database and stopped if cancellation is supported.
- MVP limitation: stopping an active Celery task may not be reliable; the UI record can be hidden/deleted, temporary files should still be cleaned up, and the active worker may finish silently.
- Delete related Cloudinary files before DB records are soft-deleted or hard-deleted: original audio, separated stem audio, MIDI file, and TAB file.
- Use `resource_type="video"` for original/separated audio and `resource_type="raw"` for MIDI/MusicXML/TAB/text exports.
- Before deleting a Cloudinary public ID, check whether another transcription outside the deletion set still references it. Shared duplicate assets must be skipped.
- If Cloudinary deletion fails, log the exception and continue the DB cleanup safely.
- Project deletion cascades through all related transcriptions and uses the same cleanup path as manual transcription delete, admin delete, and scheduled cleanup jobs.

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
- [x] Implement melodic pitch detection using Spotify Basic Pitch as the primary engine for `other` and `bass` (CREPE/librosa remain fallback details)
- [x] Implement beat/tempo detection using librosa.beat
- [x] Implement key detection using Essentia or librosa chroma features
- [x] Implement rhythm analysis (onset detection, duration estimation)
- [x] Create basic chord recognition using librosa chroma + template matching
- [x] Design data structure for transcription results (notes, chords, timing)
- [x] Create async processing pipeline with Celery (handle long-running tasks)
- [x] Enforce one active local fallback processing job at a time with Celery worker concurrency set to `1`
- [x] Add queue-aware backend status/validation so users know when another job is active
- [x] Add delete/cancel handling for `queued` and `processing` records
- [x] Add confidence scoring for detected elements - note events include per-note confidence/velocity, chord segments include averaged template confidence, tempo uses beat consistency, and key detection returns chroma-template confidence; task storage now persists key confidence from the correct result field
- [x] Implement error handling and fallback for low-confidence sections - Basic Pitch is the headline melodic engine, with CLI/CREPE/librosa fallback details; selected-stem source separation should fail clearly or fall back only when doing so does not contradict the user-selected target

### Selected-Stem Separation Foundation

- [x] Replace full multi-stem default behavior with selected-stem processing
- [x] Map guitar MVP requests to Demucs `other`
- [x] Add helper text/API metadata explaining that guitar and piano may be inside `other`
- [x] Add fallback behavior when the selected stem is unavailable or low quality
- [x] Add per-stem confidence scoring so users know which instrument tracks are reliable
- [x] Add selected-stem preview endpoint so users can listen to the processed target
- [x] Run Basic Pitch-style note detection only for selected non-vocal melodic stems when needed
- [x] Generate drum onset/rhythm data only when `drums` is selected, without Basic Pitch
- [ ] Allow users to reprocess the selected stem without rerunning unrelated stems

## Phase 2: Basic Transcription Output, Storage & Worker Integration

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
- [x] Add `AUDIO_PROCESSING_MODE=local|modal|disabled`
- [x] Add authenticated worker endpoint: `GET /api/v1/worker/jobs/next`
- [x] Add authenticated worker endpoint: `POST /api/v1/worker/jobs/{transcription_id}/complete`
- [x] Add authenticated worker endpoint: `POST /api/v1/worker/jobs/{transcription_id}/failed`
- [x] Add `WORKER_API_TOKEN` validation for external worker endpoints
- [x] Add Modal GPU worker trigger path for `AUDIO_PROCESSING_MODE=modal`
- [x] Add Modal worker selected-stem Demucs implementation
- [x] Add status callback flow from Modal worker to backend
- [x] Ensure worker failures store full logs internally and sanitized `processing_error` for users
- [x] Document Kaggle as manual testing only, not production infrastructure

### Selected-Stem Output & Storage

- [x] Design database schema for selected-stem instrument transcriptions using an `InstrumentTrack` model that can grow into future multi-track workflows
- [x] Add/confirm top-level selected job fields: `selected_stem`, `processing_status`, legacy local path fields, and output references
- [x] Add Cloudinary fields: `original_audio_url`, `original_audio_public_id`, `separated_audio_url`, `separated_audio_public_id`, `midi_file_url`, `midi_file_public_id`, `tab_file_url`, `tab_file_public_id`, and `processing_error`
- [x] Add duplicate/deletion fields: `audio_hash`, `source_type`, `source_url`, `normalized_source_id`, `duplicate_of_id`, `is_deleted`, and `deleted_at`
- [x] Store separated stem audio path, notes, chords, tabs, notation, confidence scores, and processing status for the selected stem
- [x] Generate guitar-oriented tablature from Demucs `other` for the MVP
- [x] Generate bass tablature when `bass` is selected
- [x] Generate drum rhythm data when `drums` is selected, using onset/rhythm analysis instead of Basic Pitch
- [x] Generate vocal lyrics with faster-whisper and track `lyrics_generation_status` separately from `processing_status`
- [x] Store transcription results for the selected stem instead of creating all track outputs by default
- [x] Create API endpoint to list available instrument tracks for a transcription
- [x] Create API endpoint to retrieve one instrument track result
- [x] Create API endpoint to stream/play one separated stem
- [ ] Create API endpoint or request path to process/reprocess one selected stem
- [ ] Create API endpoint to export one selected stem as TXT tab, MIDI, or MusicXML where supported
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
- processing_status: pending | queued | processing | completed | completed_with_warning | failed
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

Existing/new track table can remain for future multi-track expansion, but MVP records should focus on the selected stem output:

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
- [x] Explain when a job is queued because another job is processing
- [x] Show duplicate reuse message: "This song and stem were already processed. Existing result was loaded."
- [x] Add delete button for completed, failed, queued, and processing items
- [x] Show confirmation before deleting a processing record
- [x] Explain active processing deletion as best-effort cancellation when the worker cannot be stopped reliably
- [x] Design basic transcription viewer (tabs + notation side-by-side) - guitar/bass score views now prefer alphaTab rendering from generated AlphaTex and fall back to the existing custom SVG viewer when needed
- [x] Implement audio playback controls (play/pause, seek, volume)
- [x] Add synchronized playback highlighting (current position in tab/notation)
- [x] Implement playback speed control (0.5x to 2.0x)
- [x] Add zoom controls for notation viewer
- [x] Implement dark/light mode toggle
- [x] Add download buttons for each export format (MIDI, MusicXML, TXT, PDF later) - MIDI, MusicXML, and TAB buttons are wired; PDF remains Phase 6
- [ ] Responsive stabilization must follow the "Critical Responsive Layout Rules" from `skill.md`; layout fixes should prioritize minimum width constraints, earlier stacking/wrapping, preserving desktop composition integrity instead of overflow masking, mobile hero preview height caps, and compact auth/login/register tablet/mobile layouts.

### Selected-Stem Track Interface

- [x] Prioritize a selected-stem result view over historical full multi-stem mixer behavior
- [ ] Add tab/notation/rhythm viewer that changes based on the selected stem
- [ ] Add synchronized playback for the selected separated stem
- [x] Add confidence indicators per instrument track
- [x] Add loading/progress state per instrument, not only per full transcription - selected track status and confidence notes are shown in the viewer
- [ ] Add persistent UX/API copy explaining that `other` may contain guitar, piano, synths, melody, or accompaniment and that isolated lead/rhythm guitar separation requires future models
- [ ] Preserve selected-stem playback when score/tab generation is unavailable due to low confidence or no detected notes

MVP scope recommendation:

1. Audio upload and YouTube transcription
2. Selected-stem separation
3. Guitar tab generation from `other`
4. Bass tab generation from `bass`
5. Drum rhythm lane/tab generation from `drums`
6. Synchronized practice playback with shared waveform/playhead/tab timing
7. Selected-stem playback/export
8. Queue-aware processing status

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
- [ ] Add future support for import/editing formats such as MIDI import, Guitar Pro import, and PowerTab import/export

## Future Roadmap Summary

The selected-stem architecture grows in four steps:

- **Phase 1**: selected-stem MVP, Cloudinary persistence, duplicate detection, delete/cancel, queue/status UX
- **Phase 2**: Modal GPU worker integration, worker endpoints, worker authentication, status callback flow, selected-stem preview/export from Cloudinary outputs
- **Phase 3**: improved transcription quality, playback timing accuracy, better retry/recovery, drum/bass rendering polish, and better lyrics model settings
- **Phase 4**: AlphaTab or VexFlow renderer, better quantization, chord grouping, fingering optimizer, MusicXML/GP-like export, manual correction editor, MIDI import, Guitar Pro import, PowerTab import/export, imported project editing, advanced Songsterr-like multi-track tabs, lead/rhythm guitar separation, piano/guitar specialist models, real-time transcription, collaborative editing

Current limitations: automatic tabs are experimental, lyrics accuracy depends on vocal stem quality, and advanced Guitar Pro/Songsterr-style notation including bends, slides, harmonics, let-ring, exact rhythm notation, and multi-track Songsterr-level output is future work.

For MVP, prioritize Demucs default stems first: vocals, drums, bass, and other. Lead guitar versus rhythm guitar, true isolated guitar, and true isolated piano should be treated as advanced features because they are harder than default broad stem separation.

Each phase should be completed with code review, testing, and stakeholder feedback before proceeding to the next. Estimated timeline: 6-9 months for MVP (Phases 0-4), additional 3-6 months for full feature set.

## Historical Review Notes

The notes below document earlier implementation slices. Any previous full multi-stem, full-mix fallback, mixer, or all-track transcription behavior is historical only and is superseded by the selected-stem Basic Pitch MVP architecture described at the top of this plan. Do not reintroduce those workflows as the MVP default.

## Review Notes - 2026-05-13

- Backend verification: `python -m py_compile main.py app\api\v1\endpoints\audio.py app\tasks.py` passed.
- Backend tests: `python -m pytest tests` passed with 4 tests and 6 deprecation warnings.
- Frontend verification: build was not run because `npm`/`npm.cmd` is not available on the current shell PATH.
- Fixed during review: processing route wiring, upload-to-processing redirect, authenticated status/result API calls, missing transcription result API client method, export download API client method/buttons, static serving for uploaded audio files, and Docker Compose frontend API URL.

## Review Notes - 2026-05-14

- Historical backend service coverage included multi-stem separation, stem persistence, task-flow fallback, and cleanup-retention tests in `backend/tests/test_music_output_services.py`; current MVP behavior should remain selected-stem-first.
- Current confidence scoring status: notes, chords, tempo, and key detection produce confidence values, and `process_audio_transcription` persists key confidence from the correct result field.
- Historical source separation status: Demucs `htdemucs_6s` broad stems were persisted when available, with vocals/accompaniment and preprocessed-audio fallbacks keeping the pipeline usable when separation failed. Current MVP processing persists the selected stem only by default.
- Phase 2 cleanup update: temporary Demucs/Basic Pitch working directories are cleaned, original/preprocessed audio files are deleted at terminal task state, and separated instrument stems are retained for playback.

## Review Notes - 2026-05-14 Multi-Stem Backend Slice

- Added multi-stem source separation that returns available guitar, bass, drums, vocals, piano, and other stems from `htdemucs_6s`, with a vocals/accompaniment fallback when the 6-stem model fails.
- Historical behavior persisted available stems as `InstrumentTrack` rows and kept global transcription by analyzing guitar first, then other/accompaniment, then preprocessed audio. Current MVP processing should create only the selected-stem output by default.
- Cleanup now deletes original/preprocessed audio but retains separated stem files so `/tracks/{track_id}/stem` can stream them after processing.

## Review Notes - 2026-05-14 Guitar/Bass Per-Track Output Slice

- Guitar and bass `InstrumentTrack` rows now get track-specific `notes_json` and `tab_json` from their separated stems.
- Bass tablature supports standard 4-string tuning and 4-line ASCII rendering.
- Guitar tracks optionally store per-track notation data when MIDI-to-MusicXML conversion is available.

## Review Notes - 2026-05-14 Frontend Track Viewer Slice

- Historical viewer work fetched available instrument tracks, offered a Full Mix fallback plus per-track selector, and switched score data/audio playback to the selected track. Current MVP viewer should center the selected-stem result and keep full-mix/multi-track workflows as legacy or future behavior.
- Bass-aware rendering uses the selected track tuning so bass tabs display as four strings.
- Stem-only tracks show playback/status/confidence information with a pending-score state instead of a broken notation view.

## Review Notes - 2026-05-14 Historical Stem Mixer Slice

- Added a historical multi-stem mixer to the transcription viewer for separated instrument tracks, with synchronized playback transport plus per-stem mute, solo, and volume controls. This is not the selected-stem MVP default.
- Selecting a mixer row also selects that instrument's score/stem view, while older transcriptions without `InstrumentTrack` rows still use the original single audio player fallback.
- Frontend verification: `npm run build` passed when run through the local Corepack npm shim with the Cursor helper path added for `node`.
- Frontend lint status: direct ESLint on `src/components/TranscriptionViewer.tsx` passed; full `npm run lint` still fails on pre-existing issues in `AudioPlayer.tsx`, `AudioUpload.tsx`, `ProcessingStatus.tsx`, `ThemeProvider.tsx`, `AuthContext.tsx`, `Dashboard.tsx`, `Login.tsx`, and `Register.tsx`.

## Review Notes - 2026-05-14 Lead/Rhythm Guitar UX Warning Slice

- Added a guitar separation notice to the transcription viewer so users understand that the MVP creates one broad guitar stem and lead/rhythm parts may require manual correction.

## Review Notes - 2026-05-14 Per-Track Export Slice

- Added guitar/bass per-track export endpoints for TAB, MIDI, and MusicXML while preserving historical Full Mix export routes. Current MVP export UX should prefer the selected stem.
- Historical transcription viewer download buttons exported the selected instrument track when Guitar or Bass was selected, and kept global downloads for Full Mix. Current MVP export UX should prefer the selected stem.
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
- Historical drum tracks could be generated during multi-track processing and reprocessed from retained stems; current MVP should generate drum rhythm data only for the selected `drums` stem.
- The transcription viewer now labels drum tracks with rhythm data as `Rhythm ready` and renders a playback-synced drum rhythm lane instead of the pending-score state.
- Backend verification: `python -m py_compile app/services/audio.py app/tasks.py app/api/v1/endpoints/audio.py` passed, and `python -m pytest tests/test_music_output_services.py tests/test_audio_list_endpoint.py` passed with 43 tests and existing warnings.
- Frontend verification: `npm run build` passed through `C:\nvm4w\nodejs\npm.cmd`.

## Review Notes - 2026-05-17 Railway Persistence Slice

- Added selected-stem persistence fields for Cloudinary URLs/public IDs, duplicate detection, soft deletion, and queue metadata, with additive schema compatibility and a SQL migration.
- Upload and YouTube ingestion now reuse completed duplicates before queueing, upload originals to Cloudinary when configured, and persist `audio_hash` or normalized YouTube IDs.
- Processing persists exactly one selected separated stem, uploads selected-stem/MIDI/MusicXML/TAB artifacts to Cloudinary when configured, clears queue metadata at terminal states, and treats local files as temporary scratch after durable upload.
- Added `GET /audio/{transcription_id}/tracks/{track_id}/preview`, with Cloudinary redirect for durable stems and HTTP byte-range support for legacy/local stem files.
- Added best-effort `DELETE /transcriptions/{id}` cleanup/cancellation behavior for completed, failed, queued, and processing records. Active Celery task termination remains best-effort for the MVP.
