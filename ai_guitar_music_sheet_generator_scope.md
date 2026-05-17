# AI Guitar Music Sheet Generator / MusicStudio

## 2026 MVP Scope Update: Selected-Stem Demucs Processing + Modal Worker

This project is now scoped as an MVP/portfolio-friendly selected-stem transcription app, not a full-scale multi-user AI processing system yet. Railway is the lightweight API/controller layer. Modal/serverless GPU is the preferred production-like AI processing layer. Railway/Celery Demucs remains fallback/dev only.

The old pipeline:

```txt
Audio Upload
-> Separate all stems
-> Convert all stems to MIDI
-> Generate all tabs
```

is replaced with:

```txt
Audio Upload / YouTube URL + selected stem
-> Generate audio hash or normalize YouTube ID
-> Check existing completed record with same source + selected stem
-> If duplicate exists, return existing result
-> Upload original audio to Cloudinary
-> Queue processing job
-> Trigger Modal/serverless GPU worker OR expose worker pull endpoint
-> Modal/external worker downloads original audio from Cloudinary
-> Worker runs Demucs selected-stem separation on GPU when available
-> Worker uploads selected separated stem to Cloudinary
-> Worker optionally generates MIDI/TAB/MusicXML if supported
-> Worker calls backend complete/failed endpoint
-> Backend updates transcription status and output references
-> Frontend polls status and shows playback/export/download
```

Demucs default stems are `vocals`, `drums`, `bass`, and `other`. For MVP guitar transcription, the app should use the `other` stem as the target because default Demucs models commonly group guitar, piano, synths, and accompaniment there. The UI must make this clear: guitar and piano may be inside `other` depending on the mix and model.

The backend should accept `selected_stem` or `selected_instrument` in upload/process requests, upload the original source audio to Cloudinary, run Demucs only for the selected output needed, convert only that selected stem to MIDI/TAB/sheet output when applicable, upload durable outputs to Cloudinary, and save only the selected stem output unless explicit caching is needed.

Jobs should be queued and status responses should explain when work is waiting. In `PROCESSING_MODE=local`, Celery worker concurrency should be `1` and local processing should be limited to very short development files. Production-like MVP processing should use `PROCESSING_MODE=modal`.

Recommended MVP limits:
- Process one selected stem per job.
- Prefer 3-5 minute songs.
- Avoid full multi-stem transcription by default.
- Treat Railway local storage as temporary worker scratch space only.
- Store Cloudinary `secure_url` and `public_id` references for original audio, selected separated stem audio, MIDI files, and TAB files.
- Detect duplicate same-song/same-stem requests before queueing work and reuse completed output.
- Let users delete completed, failed, queued, and processing records.
- Do not rely on Railway free/trial resources for Demucs production processing.
- Use Kaggle only for optional/manual free GPU testing.
- Treat full multi-instrument processing as a future premium or GPU-backed feature.

Future roadmap:
- Phase 1: selected-stem MVP, Cloudinary persistence, duplicate detection, delete/cancel, queue/status UX.
- Phase 2: Modal/serverless GPU worker integration, worker endpoints, external worker authentication, status callback flow, selected-stem preview/export from Cloudinary outputs.
- Phase 3: multiple selected stems, improved transcription quality, better retry/recovery.
- Phase 4: full Songsterr-like multi-track tabs, lead/rhythm guitar separation, piano/guitar specialist models.

## Problem

Musicians often struggle to turn finished audio into useful practice material. A song may contain vocals, drums, bass, guitar, piano, synths, and other instruments mixed together, making it difficult to hear one part clearly or transcribe it by ear.

Existing tools tend to solve only part of the workflow. Stem splitters can isolate instruments but usually do not create playable notation. Tab and sheet music tools may provide notation, but often depend on manual entry, MIDI files, or a limited instrument focus. Learners and working musicians need a more connected workflow: separate the song, inspect each part, generate notation or tabs where possible, and practice with synchronized playback.

---

## Solution

Develop an AI-powered web application that combines selective Demucs stem separation with Songsterr-style synchronized notation and playback for one selected target stem.

The system will analyze audio from MP3/WAV uploads or YouTube links, let the user choose a target stem, separate only the selected output needed, detect notes, chords, tempo, key, rhythm, and confidence levels for that selected stem where supported, then generate track-specific musical outputs.

The application will provide:
- Selected-stem playback for vocals, drums, bass, or other/accompaniment
- Per-job selected-stem transcription tracks
- Guitar-oriented tablature from the `other` stem for the MVP
- Bass tablature when `bass` is selected
- Drum rhythm lanes when `drums` is selected
- Piano, vocal, and melodic staff notation where supported later
- Chord progressions and chord charts
- Synchronized playback, looping, speed control, and export options

The goal is a practical selected-stem transcription and practice studio first, with full multi-track Songsterr-like tabs as a later expansion.

---

## Features

### Audio Input
- Upload MP3/WAV audio files
- Paste YouTube video links
- Audio preprocessing, normalization, and resampling

### AI Audio Analysis
- Source separation into broad stems
- Pitch detection for melodic stems
- Chord recognition
- BPM/tempo detection
- Key detection
- Rhythm and onset analysis
- Per-track confidence scoring

### Selected-Stem Source Separation
- Require the user to choose a target stem before processing
- Support Demucs default stems first: vocals, drums, bass, and other
- Use `other` as the MVP target for guitar transcription
- Explain that guitar and piano may be grouped inside `other`
- Run Demucs only for the selected output needed
- Persist the selected separated stem, not every stem by default
- Allow selected-stem reprocessing without rerunning unrelated outputs

### Selected-Track Transcription
- Store transcription data for the selected instrument/stem
- Generate guitar-oriented tablature from the `other` stem in the MVP
- Generate bass tablature from the `bass` stem where supported
- Generate drum rhythm data from the `drums` stem
- Generate piano/vocal notation only when model support and transcription quality are adequate
- Keep full-mix transcription as a fallback or summary view

### Notation and Track Viewer
- Interactive instrument selector
- Tab, rhythm, and notation views based on selected instrument
- Audio playback synchronization
- Playback speed controls
- Looping and practice controls
- Zoom controls
- Dark/light mode

### Export Options
- Export track or full-mix MIDI
- Export MusicXML for notation-capable tracks
- Export TXT tabs for tab-capable tracks
- Export PDF sheet music
- Export sheet images
- Future support for Guitar Pro, PowerTab, and stem remix/export

### User Features
- User authentication
- Save transcription history
- Favorite projects
- Project management dashboard
- Track metadata editing
- Manual correction history

### Optional Advanced Features
- Beginner-friendly simplification
- Instrument role detection
- Lead/rhythm guitar classification
- Solo and melody extraction
- AI-generated practice suggestions
- Real-time transcription support
- Collaborative review and comments

---

## Technical Considerations and Product Decisions

### AI Models and Technologies

The platform may use the following AI and audio processing technologies:

#### Source Separation
- Demucs using default stems: vocals, drums, bass, and other
- Future specialist models for true guitar, piano, lead/rhythm guitar, and other instrument-specific separation

#### Pitch Detection
- Spotify Basic Pitch
- CREPE
- librosa pYIN fallback

#### Chord Recognition
- CNN/RNN-based chord classification
- librosa chroma analysis
- Template matching

#### Audio Processing
- FFmpeg
- librosa
- Essentia
- music21 or mido for notation and MIDI conversion

These technologies may evolve as the platform improves accuracy and performance.

---

### Failure Handling and Confidence Scoring

The system will provide:
- Confidence scores for detected notes, chords, tempo, key, and stems
- Suggested alternative transcriptions
- Error indicators for uncertain sections
- Partial transcription fallback when full analysis fails
- Clear per-track status messages

Users may manually edit generated track data to correct inaccuracies.

---

### Accuracy Expectations

Target performance:
- 80-90% chord detection accuracy for clean, isolated harmonic material
- 70-85% note transcription accuracy for supported melodic stems
- Higher reliability for isolated stems than dense full mixes

Performance depends heavily on:
- Audio quality
- Background noise
- Number of instruments
- Instrument overlap
- Recording clarity
- Distortion, reverb, and live-room bleed

---

### Polyphonic Audio Handling

The system will support songs containing:
- Vocals
- Drums
- Bass
- Guitar
- Piano
- Other melodic and accompaniment instruments

The application will:
- Ask the user for one selected target stem before transcription
- Separate and analyze only the selected stem in the MVP
- Store results against the selected stem/instrument
- Use full-mix processing only as a fallback or overview

Complex mixes may reduce accuracy, especially when multiple similar instruments overlap.

---

### Audio Quality Requirements

Recommended audio quality:
- Minimum: 128kbps MP3
- Recommended: 320kbps MP3 or WAV

Performance may decrease with:
- Heavy distortion
- Reverb-heavy mixes
- Crowd/live recordings
- Low signal-to-noise ratio
- Instruments occupying the same frequency range

---

### Beginner Guidance and Accessibility

The platform will include:
- Beginner-friendly explanations
- Tooltips for music theory terms
- Guided onboarding/tutorials
- Simplified viewing modes

Accessibility considerations:
- Keyboard navigation support
- Colorblind-friendly UI
- Responsive design
- Tablet compatibility for music stand usage

---

### Mobile and Tablet Support

Responsive design is planned from the beginning for:
- Desktop
- Tablet
- Mobile devices

Tablet optimization is important because musicians commonly use tablets while practicing.

---

### Manual Error Correction

Users will be able to:
- Edit generated notes, tabs, rhythm hits, and chords
- Modify chord names
- Move guitar/bass notes between strings and frets
- Adjust piano/vocal note timing and pitch
- Reprocess selected tracks or sections only
- Save edited versions without losing the AI-generated baseline

---

### User Verification and Learning Support

The application will provide:
- Synchronized stem and score playback
- MIDI comparison playback
- Animated note highlighting
- Tempo slowdown features
- Looping for selected sections
- Track mute/solo controls for focused listening

This helps users validate generated notation even without advanced music theory knowledge.

---

### AI-Generated Practice Suggestions

Possible practice assistance features:
- Slow practice recommendations
- Repeated difficult section detection
- Suggested exercises
- Finger transition practice hints for fretted instruments
- Coordination hints for rhythm instruments
- Difficulty scoring per track

---

### Intended Workflow

The platform is intended for:
- Learning songs
- Multi-instrument practice
- Band rehearsal preparation
- Cover preparation
- Arrangement assistance
- Transcription support
- Stem listening and remix-style study

The system is designed to assist musicians rather than replace professional transcriptionists.

---

### Copyright and Legal Compliance

The platform will:
- Process user-provided content only
- Avoid permanent copyrighted audio storage unless explicitly required for user projects
- Follow YouTube API and DMCA policies
- Display copyright notices where applicable

Users remain responsible for sharing copyrighted material publicly.

---

### Attribution

Generated exports may include:
- Song title
- Artist name
- AI transcription notice
- Source attribution
- Selected instrument or track name

---

### Data Retention and Privacy

The platform will:
- Automatically delete temporary uploaded and preprocessed audio after processing
- Retain durable audio/output assets in Cloudinary only when needed for playback, reprocessing, downloads, or user projects
- Store Cloudinary `public_id` values so retained assets can be deleted or replaced later
- Treat Railway local files as temporary processing artifacts and clean them up after terminal job status
- Allow users to delete processing records and clean related Cloudinary files when safe
- Keep database deletion safe and log cleanup errors if Cloudinary deletion fails
- Allow users to manage saved projects
- Minimize storage of copyrighted material

Usage analytics may be collected to:
- Improve transcription accuracy
- Detect system failures
- Optimize AI performance

---

### User Content Ownership

Users retain ownership of:
- Uploaded content
- Edited track data
- Generated exports
- Saved arrangements and corrections

The platform only processes data necessary for transcription and practice functionality.

---

### Processing Time

Expected processing speed:
- 1-3 minutes for a typical 3-minute song, depending on model choice and hardware
- 3-5 minute songs are recommended for the selected-stem MVP
- Longer songs should be rejected, warned, or reserved for later premium/GPU processing

Real-time transcription may be explored using:
- WebAssembly
- Browser-based inference
- GPU acceleration

---

### System Architecture

The platform will use:
- Server-side AI processing
- Browser-based playback/editing
- Per-track transcription storage
- Cloudinary durable storage for saved audio/output assets
- Railway local storage only for temporary processing files

Benefits include:
- Better AI performance
- Scalability
- Cross-device compatibility
- Track-level reprocessing and editing

---

### File Limits

Initial limitations:
- Maximum file size: 100MB
- Recommended maximum duration: 3-5 minutes for MVP cost and memory stability

Premium plans may support larger uploads.

---

### Instrument Support

MVP support:
- User-selected `vocals` stem playback
- User-selected `drums` stem playback and rhythm lane
- User-selected `bass` stem playback and bass tab
- User-selected `other` stem playback and guitar-oriented tab attempt
- Clear messaging that guitar/piano may live inside `other`

Near-term expansion:
- Piano note and staff notation
- Vocal melody notation
- Drum MIDI or drum notation
- Per-track MIDI/MusicXML exports beyond guitar and bass

Future support may include:
- Ukulele
- Strings
- Brass and woodwinds
- Synth lead and pad classification
- Improved multi-guitar separation
- Instrument role detection across sections

---

### Fretted Instrument Support

For guitar, bass, ukulele, and similar instruments, the transcription engine will support:
- Tab generation
- Tuning preferences
- Capo settings where applicable
- Fret positioning optimization
- Playability-aware simplification

Supported tunings may include:
- Guitar standard tuning
- Drop D
- Open G
- DADGAD
- Half-step down
- Bass standard tuning

Additional tunings may be added over time.

---

### Guitar Technique Support

For guitar-specific tracks, the system aims to support:
- Bends
- Slides
- Hammer-ons
- Pull-offs
- Harmonics
- Palm muting
- Tapping notation

Support quality may vary depending on audio clarity.

---

### Polyphonic Instrument Support

The platform will attempt to detect:
- Guitar fingerstyle playing
- Piano chords and voicings
- Simultaneous ringing notes
- Arpeggios
- Chord voicings

Polyphonic transcription remains one of the most technically challenging features.

---

### Notation Customization

Users can customize:
- Track-only view
- Full-mix view
- TAB-only mode
- Standard notation
- Rhythmic notation
- Chord-only view
- Tuning preferences
- Capo settings
- Instrument-specific display preferences

---

### Quality Assurance and Validation

The system will improve through:
- Beta testing
- Known-song benchmarking
- User feedback collection
- Accuracy evaluation datasets
- Per-instrument accuracy tracking

User corrections may help improve future transcription models.

---

### Operational Cost Management

To manage AI processing costs, the platform may use:
- Modal/serverless GPU for preferred production-like selected-stem processing
- `PROCESSING_MODE=local` with one active Celery worker only as a development fallback
- `PROCESSING_MODE=external_worker` for manual external workers such as Kaggle notebooks
- Duplicate detection before queueing work
- Usage limits
- Prioritized processing
- Subscription-based premium access
- Caching for repeated audio or stem processing

Selective processing reduces CPU/RAM usage, storage requirements, and processing time because the app does not create and transcribe every stem for every song. Full multi-instrument processing should be treated as a future premium capability, especially if GPU workers or external AI processing services are added.

Railway is the MVP backend/API target, not the heavy AI processing platform. Railway trial/free resources are not reliable for Demucs production processing. Kaggle is optional/manual testing only, not 24/7 production infrastructure and not reliably auto-started per user upload.

Duplicate detection reduces repeated Demucs processing, repeated Cloudinary storage usage, unnecessary queue jobs, and Railway CPU/RAM cost.

### Duplicate Song Handling

Before starting a new processing job:

```txt
User Upload / YouTube URL + selected stem
-> Generate audio hash or normalize YouTube ID
-> Check existing completed record with same source + selected_stem
-> If found, return existing result
-> If not found, upload/process normally
-> Save result for future reuse
```

Duplicate detection should consider:

- `audio_hash` for uploaded files
- `source_type`
- `source_url`
- `normalized_source_id` for YouTube URLs
- `selected_stem`

Same song plus same selected stem should reuse existing output. Same song plus a different selected stem may create a new job because output will be different.

### Delete Processing Records

Users should be allowed to delete processing records from the UI for these statuses:

- `completed`
- `failed`
- `queued`
- `processing`

If the job is queued, remove or cancel it if possible. If the job is processing, mark it as cancelled/deleted in the database and stop it if cancellation is supported.

MVP limitation: stopping an active Celery task may not be reliable yet. In that case, the UI record can be hidden/deleted, temporary files should still be cleaned up, and the active worker may finish silently.

Deleting a record should also delete related Cloudinary files when safe:

- original audio
- separated stem audio
- MIDI file
- TAB file

If Cloudinary deletion fails, keep the database deletion safe and log the cleanup error.

### Data Model and API Scope

Upload and YouTube processing requests should include one of:
- `selected_stem`
- `selected_instrument`

Valid MVP stem values:
- `vocals`
- `drums`
- `bass`
- `other`

Recommended persisted fields:
- `selected_stem`
- `audio_hash`
- `source_type`
- `source_url`
- `normalized_source_id`
- `duplicate_of_id`
- `is_deleted`
- `deleted_at`
- `original_audio_url`
- `original_audio_public_id`
- `separated_audio_url`
- `separated_audio_public_id`
- `midi_file_url`
- `midi_file_public_id`
- `tab_file_url`
- `tab_file_public_id`
- `processing_status`
- `processing_error`
- `queue_position`

Legacy local path fields such as `separated_audio_file_path`, `midi_file_path`, and `tab_file_path` may exist during migration, but they should not be treated as durable storage fields.

Supported processing statuses:
- `pending`
- `queued`
- `processing`
- `completed`
- `failed`

Recommended processing modes:

- `PROCESSING_MODE=local`: development fallback; Railway/Celery can process very short files only.
- `PROCESSING_MODE=external_worker`: backend queues jobs for a manual/external worker. Kaggle jobs wait until the notebook is running.
- `PROCESSING_MODE=modal`: preferred MVP production-like architecture with Modal/serverless GPU processing.

Worker endpoints:

- `GET /api/v1/worker/jobs/next`
- `POST /api/v1/worker/jobs/{transcription_id}/complete`
- `POST /api/v1/worker/jobs/{transcription_id}/failed`

---

### Model Updates and Maintenance

AI models will be updated gradually to:
- Improve transcription quality
- Reduce errors
- Maintain compatibility
- Add support for more instruments and notation formats

Updates will be tested before deployment to avoid breaking existing functionality.

---

### Monetization Strategy

Potential pricing models:
- Free limited tier
- Subscription plans
- Premium exports
- Faster processing for paid users
- Larger file and project limits

---

### Offline Capability

The MVP will primarily rely on cloud-based or server-side AI processing.

Possible offline features:
- Viewing saved notation and tabs
- Audio playback for saved stems
- Basic editing
- Cached practice sessions
