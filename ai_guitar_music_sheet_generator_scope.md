# AI Guitar Music Sheet Generator / MusicStudio

## 2026 MVP Scope Update: Selected-Stem Audio/YouTube Transcription

This project is scoped as an MVP/portfolio-friendly selected-stem transcription and synchronized practice app. Railway is the lightweight API/controller layer. Modal/serverless GPU is the preferred production-like AI processing layer for Demucs jobs. Railway/Celery Demucs remains fallback/dev only.

Supported MVP input types:

1. Audio upload
2. YouTube URL

Primary MVP workflow:

```txt
Audio Upload / YouTube URL
-> User selects target stem
-> Check duplicate by source identity + selected stem
-> Upload original audio to Cloudinary when processing is needed
-> Queue one selected-stem job
-> Demucs separates selected stem
-> Normalize selected separated stem volume
-> Spotify Basic Pitch runs only for melodic stems (`other`, `bass`, future melodic `vocals`)
-> Onset/rhythm detection runs for `drums`
-> Generate instrument-aware tabs/notation/rhythm data where supported
-> Render synchronized playback with playhead/waveform
-> Export generated outputs
```

The old pipeline:

```txt
Audio Upload
-> Separate all stems
-> Convert all stems to MIDI
-> Generate all tabs
```

is replaced with one selected-stem job per request:

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
-> Worker normalizes selected separated stem volume
-> Worker runs Spotify Basic Pitch only for melodic stems (`other`, `bass`, future melodic `vocals`)
-> Worker runs onset/rhythm analysis for `drums`
-> Worker generates tabs/notation/rhythm data based on selected stem where supported
-> Worker uploads supported MIDI/MusicXML/TAB exports to Cloudinary
-> Worker calls backend complete/failed endpoint
-> Backend updates transcription status and output references
-> Frontend renders synchronized playback and export/download controls
```

Demucs default stems are `vocals`, `drums`, `bass`, and `other`. For MVP guitar/accompaniment transcription, the app should use the `other` stem as the target because default Demucs models commonly group guitar, piano, synths, melody, and accompaniment there. The UI and API metadata must make this clear: those parts may be inside `other` depending on the mix and model. Do not market the MVP as isolated lead guitar transcription or promise perfect Songsterr-level accuracy.

The backend should accept `selected_stem` or `selected_instrument` in audio/YouTube upload/process requests, upload the original source audio to Cloudinary, run Demucs only for the selected output needed, transcribe only that selected stem when applicable, upload durable outputs to Cloudinary, and save only the selected stem output unless explicit caching is needed.

Jobs should be queued and status responses should explain when work is waiting. In `PROCESSING_MODE=local`, Celery worker concurrency should be `1` and local processing should be limited to very short development files. Production-like MVP processing should use `PROCESSING_MODE=modal`.

Recommended MVP limits:

- Process one selected stem per job.
- Support audio upload and YouTube URL in the MVP.
- Prefer 3-5 minute songs.
- Avoid full multi-stem transcription by default.
- Treat Railway local storage as temporary worker scratch space only.
- Store Cloudinary `secure_url` and `public_id` references for original audio, selected separated stem audio, MIDI exports, MusicXML exports, and TAB files.
- Detect duplicate same-song/same-stem requests before queueing work and reuse completed output.
- Let users delete completed, completed_with_warning, failed, queued, and processing records.
- Do not rely on Railway free/trial resources for Demucs production processing.
- Use Kaggle only for optional/manual free GPU testing.
- Treat full multi-instrument processing as a future premium or GPU-backed feature.

Future roadmap only:

- MIDI import
- Guitar Pro import
- PowerTab import/export
- Imported project editing
- Imported multi-track workflows
- Lead/rhythm guitar separation
- True isolated guitar models
- Piano specialist models
- Real-time transcription
- Collaborative editing

Do not remove or deprioritize:

- MIDI export
- MusicXML export
- TAB export

Exports should be generated from transcription results created from separated stems.

## Problem

Musicians often struggle to turn finished audio into useful practice material. A song may contain vocals, drums, bass, guitar, piano, synths, and other instruments mixed together, making it difficult to hear one part clearly or transcribe it by ear.

Existing tools tend to solve only part of the workflow. Stem splitters can isolate instruments but usually do not create playable notation. Tab and sheet music tools may provide notation, but often depend on manual entry, imported files, or a limited instrument focus. Learners and working musicians need a more connected workflow: separate the target stem, inspect it, generate notation or tabs where possible, and practice with synchronized playback.

## Solution

Develop an AI-powered web application that combines selective Demucs stem separation, Spotify Basic Pitch for melodic selected stems, drum onset/rhythm analysis, and synchronized notation/playback for one selected target stem.

The system will analyze audio from MP3/WAV uploads or YouTube links, let the user choose a target stem, separate only the selected output needed, run Basic Pitch only for melodic supported stems, run onset/rhythm analysis for drums, detect chords/tempo/key where supported, record confidence levels, then generate selected-stem musical outputs.

The application will provide:

- Selected-stem playback for vocals, drums, bass, or other/accompaniment
- Guitar-oriented tablature from the `other` stem for the MVP
- Bass tablature when `bass` is selected
- Drum rhythm lanes and percussion/drum tab when `drums` is selected
- Vocal playback-only results for the MVP
- Chord progressions and chord charts where supported
- Synchronized playback, looping, speed control, waveform sync, playhead sync, note/hit highlighting, and export options

The goal is a practical selected-stem transcription and practice studio first, with imports and full multi-track project workflows as later expansion.

## Stem Support Matrix

### Vocals

- Playback only for MVP.
- Preserve separated stem playback and metadata.
- Future roadmap: Basic Pitch or specialist melody extraction.

### Drums

- Analyze the drum stem.
- Detect drum hits and onsets with rhythm/onset analysis.
- Do not run Spotify Basic Pitch for drums.
- Generate a drum rhythm lane.
- Generate percussion/drum tab where possible.
- Support synchronized playback highlighting.
- Support drum MIDI export when possible.

### Bass

- Analyze the bass stem with Spotify Basic Pitch.
- Generate 4-string bass tablature.
- Use standard tuning E A D G.
- Generate bass score data where possible.
- Support synchronized playback/playhead highlighting.

### Other

- Primary guitar/accompaniment transcription target.
- Analyze the selected `other` stem with Spotify Basic Pitch.
- Generate guitar tablature.
- Generate score notation.
- Support synchronized playback/playhead highlighting.
- Clearly explain that guitar, piano, synth, melody, and accompaniment may be grouped together depending on the mix.

## Instrument-Aware Rendering Architecture

Viewer behavior:

- Guitar/`other` -> 6-string tablature
- `bass` -> 4-string bass tablature
- `drums` -> rhythm lane/percussion tab
- `vocals` -> playback-only

All views use shared playback synchronization:

- waveform
- playhead
- tabs
- score
- active notes or drum hits
- selected-stem playback

The playback system must support:

- moving playhead
- note highlighting
- waveform sync
- seek synchronization
- shared `currentTime`
- tab/score sync
- stem playback sync

Do not use separate timers for waveform, tabs, and score. One shared playback clock/current time source should drive the whole viewer.

## Features

### Audio Input

- Upload MP3/WAV audio files.
- Paste YouTube video links.
- Audio preprocessing, normalization, and resampling.
- Required target stem selection before processing.

### AI Audio Analysis

- Selected-stem source separation into one Demucs stem.
- Spotify Basic Pitch as the primary note detection engine for melodic selected stems.
- Onset and hit detection for drum stems.
- Chord recognition where supported.
- BPM/tempo detection.
- Key detection.
- Rhythm and duration analysis.
- Per-track confidence scoring.

### Selected-Stem Source Separation

- Require the user to choose a target stem before processing.
- Support Demucs default stems first: vocals, drums, bass, and other.
- Use `other` as the MVP target for guitar transcription.
- Explain that guitar and piano may be grouped inside `other`.
- Run Demucs only for the selected output needed.
- Persist the selected separated stem, not every stem by default.
- Allow selected-stem reprocessing without rerunning unrelated outputs.

### Selected-Track Transcription

- Store transcription data for the selected instrument/stem.
- Run Basic Pitch only for `other`, `bass`, and future melodic `vocals`.
- Generate guitar-oriented tablature from the `other` stem in the MVP.
- Generate bass tablature from the `bass` stem.
- Generate drum rhythm data from the `drums` stem using onset/rhythm analysis, not Basic Pitch.
- Generate vocal notation only when future melody extraction is added.
- Keep full-mix or imported project playback architecture out of the MVP.

### Notation and Track Viewer

- Instrument-aware selected-stem viewer.
- Tab, rhythm, and notation views based on selected instrument.
- Audio playback synchronization.
- Waveform visualization.
- Moving playhead.
- Active note/hit highlighting.
- Playback speed controls.
- Looping and practice controls.
- Zoom controls.
- Dark/light mode.

### Export Options

- Export generated MIDI.
- Export generated MusicXML for notation-capable tracks.
- Export generated TXT tabs for tab-capable tracks.
- Export PDF sheet music later.
- Export sheet images later.

MIDI, MusicXML, and TAB exports are generated from separated-stem transcription results.

### User Features

- User authentication.
- Save transcription history.
- Favorite projects.
- Project management dashboard.
- Track metadata editing.
- Manual correction history.

### Optional Advanced Features

- Beginner-friendly simplification.
- Instrument role detection.
- Lead/rhythm guitar classification.
- Solo and melody extraction.
- AI-generated practice suggestions.
- Real-time transcription support.
- Collaborative review and comments.

## Technical Considerations and Product Decisions

### AI Models and Technologies

The platform may use the following AI and audio processing technologies:

#### Source Separation

- Demucs using default stems: vocals, drums, bass, and other.
- Future specialist models for true guitar, piano, lead/rhythm guitar, and other instrument-specific separation.

#### Pitch Detection

- Spotify Basic Pitch as the primary melodic note detection engine.
- CREPE and librosa pYIN as fallback implementation details when needed.
- Basic Pitch is used for `other`, `bass`, and future melodic `vocals`, not for `drums`.

#### Rhythm and Drum Detection

- librosa onset detection.
- Drum hit grouping by onset strength and frequency bands.
- Future specialist drum transcription models.

#### Chord Recognition

- CNN/RNN-based chord classification.
- librosa chroma analysis.
- Template matching.

#### Audio Processing

- FFmpeg.
- librosa.
- Essentia.
- music21 or mido for notation and MIDI conversion.

These technologies may evolve as the platform improves accuracy and performance.

## Failure Handling and Confidence Scoring

The system will provide:

- Confidence scores for detected notes, chords, tempo, key, stems, and drum hits.
- Suggested alternative transcriptions.
- Error indicators for uncertain sections.
- Partial transcription fallback when full analysis fails.
- Clear per-track status messages.

A no-note result after successful stem separation should be `completed_with_warning`, not `failed`, when the selected stem is playable.

For melodic stems, the worker should normalize separated stem volume before Basic Pitch, retry with lower-threshold/high-sensitivity settings when zero notes are detected, preserve playback if the retry still finds no notes, and disable only score/TAB/MIDI/MusicXML exports that require generated notes.

Users may manually edit generated track data to correct inaccuracies.

## Accuracy Expectations

Target performance:

- 80-90% chord detection accuracy for clean, isolated harmonic material.
- 70-85% note transcription accuracy target for clean supported melodic stems, without promising perfect Songsterr-level accuracy.
- Higher reliability for selected separated stems than dense mixed audio.

Performance depends heavily on:

- Audio quality.
- Background noise.
- Number of instruments.
- Instrument overlap.
- Recording clarity.
- Distortion, reverb, and live-room bleed.

## Audio Quality Requirements

Recommended audio quality:

- Minimum: 128kbps MP3.
- Recommended: 320kbps MP3 or WAV.

Performance may decrease with:

- Heavy distortion.
- Reverb-heavy mixes.
- Crowd/live recordings.
- Low signal-to-noise ratio.
- Instruments occupying the same frequency range.

## Manual Error Correction

Users will be able to:

- Edit generated notes, tabs, rhythm hits, and chords.
- Modify chord names.
- Move guitar/bass notes between strings and frets.
- Adjust note timing and pitch where supported.
- Reprocess selected tracks or sections only.
- Save edited versions without losing the AI-generated baseline.

## User Verification and Learning Support

The application will provide:

- Synchronized stem and score playback.
- Animated note highlighting.
- Tempo slowdown features.
- Looping for selected sections.
- Focused selected-stem listening.

This helps users validate generated notation even without advanced music theory knowledge.

## Copyright and Legal Compliance

The platform will:

- Process user-provided content only.
- Avoid permanent copyrighted audio storage unless explicitly required for user projects.
- Follow YouTube API and DMCA policies.
- Display copyright notices where applicable.

Users remain responsible for sharing copyrighted material publicly.

## Data Retention and Privacy

The platform will:

- Automatically delete temporary uploaded and preprocessed audio after processing.
- Retain durable audio/output assets in Cloudinary only when needed for playback, reprocessing, downloads, or user projects.
- Store Cloudinary `public_id` values so retained assets can be deleted or replaced later.
- Treat Railway local files as temporary processing artifacts and clean them up after terminal job status.
- Allow users to delete processing records and clean related Cloudinary files when safe.
- Keep database deletion safe and log cleanup errors if Cloudinary deletion fails.
- Allow users to manage saved projects.
- Minimize storage of copyrighted material.

## Processing Time

Expected processing speed:

- 1-3 minutes for a typical 3-minute song, depending on model choice and hardware.
- 3-5 minute songs are recommended for the selected-stem MVP.
- Longer songs should be rejected, warned, or reserved for later premium/GPU processing.

## System Architecture

The platform will use:

- Server-side AI processing.
- Browser-based playback/editing.
- Per-selected-stem transcription storage.
- Cloudinary durable storage for saved audio/output assets.
- Railway local storage only for temporary processing files.

Benefits include:

- Better AI performance.
- Scalability.
- Cross-device compatibility.
- Track-level reprocessing and editing.

## Instrument Support

MVP support:

- User-selected `vocals` stem playback.
- User-selected `drums` stem playback, onset/rhythm hit detection, rhythm lane, and percussion/drum tab.
- User-selected `bass` stem playback, Basic Pitch transcription, 4-string bass tab, and bass score.
- User-selected `other` stem playback, Basic Pitch transcription, 6-string guitar-oriented tab, and score notation.
- Clear messaging that guitar, piano, synths, melody, or accompaniment may live inside `other`.

Near-term expansion:

- Drum MIDI export polish.
- Better drum notation.
- Per-track MIDI/MusicXML exports beyond guitar and bass where transcription quality supports it.

Future support may include:

- MIDI import.
- Guitar Pro import.
- PowerTab import/export.
- Imported project editing.
- Ukulele.
- Strings.
- Brass and woodwinds.
- Synth lead and pad classification.
- Improved multi-guitar separation.
- Instrument role detection across sections.

## Fretted Instrument Support

For guitar, bass, ukulele, and similar instruments, the transcription engine will support:

- Tab generation.
- Tuning preferences.
- Capo settings where applicable.
- Fret positioning optimization.
- Playability-aware simplification.

MVP tunings:

- Guitar standard tuning.
- Bass standard tuning E A D G.

Additional tunings may be added over time.

## Quality Assurance and Validation

The system will improve through:

- Beta testing.
- Known-song benchmarking.
- User feedback collection.
- Accuracy evaluation datasets.
- Per-instrument accuracy tracking.

User corrections may help improve future transcription models.

## Operational Cost Management

To manage AI processing costs, the platform may use:

- Modal/serverless GPU for preferred production-like selected-stem processing.
- `PROCESSING_MODE=local` with one active Celery worker only as a development fallback.
- `PROCESSING_MODE=external_worker` for manual external workers such as Kaggle notebooks.
- Duplicate detection before queueing work.
- Usage limits.
- Prioritized processing.
- Subscription-based premium access.
- Caching for repeated audio or stem processing.

Selective processing reduces CPU/RAM usage, storage requirements, and processing time because the app does not create and transcribe every stem for every song. Full multi-instrument processing should be treated as a future premium capability, especially if GPU workers or external AI processing services are added.

Railway is the MVP backend/API target, not the heavy AI processing platform. Railway trial/free resources are not reliable for Demucs production processing. Kaggle is optional/manual testing only, not 24/7 production infrastructure and not reliably auto-started per user upload.

Duplicate detection reduces repeated Demucs processing, repeated Cloudinary storage usage, unnecessary queue jobs, and Railway CPU/RAM cost.

## Duplicate Song Handling

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

- `audio_hash` for uploaded files.
- `source_type`.
- `source_url`.
- `normalized_source_id` for YouTube URLs.
- `selected_stem`.

Same song plus same selected stem should reuse existing output. Same song plus a different selected stem may create a new job because output will be different.

## Delete Processing Records

Users should be allowed to delete processing records from the UI for these statuses:

- `completed`
- `completed_with_warning`
- `failed`
- `queued`
- `processing`

If the job is queued, remove or cancel it if possible. If the job is processing, mark it as cancelled/deleted in the database and stop it if cancellation is supported.

MVP limitation: stopping an active Celery task may not be reliable yet. In that case, the UI record can be hidden/deleted, temporary files should still be cleaned up, and the active worker may finish silently.

Deleting a record should also delete related Cloudinary files when safe:

- original audio
- separated stem audio
- MIDI file
- MusicXML file
- TAB file

If Cloudinary deletion fails, keep the database deletion safe and log the cleanup error.

## Data Model and API Scope

Upload and YouTube processing requests should include one of:

- `selected_stem`
- `selected_instrument`

Valid MVP stem values:

- `vocals`
- `drums`
- `bass`
- `other`

Supported MVP source types:

- `upload`
- `youtube`
- `demo`

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
- `musicxml_file_url`
- `musicxml_file_public_id`
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
- `completed_with_warning`
- `failed`

Recommended processing modes:

- `PROCESSING_MODE=local`: development fallback; Railway/Celery can process very short files only.
- `PROCESSING_MODE=external_worker`: backend queues jobs for a manual/external worker. Kaggle jobs wait until the notebook is running.
- `PROCESSING_MODE=modal`: preferred MVP production-like architecture with Modal/serverless GPU processing.

Worker endpoints:

- `GET /api/v1/worker/jobs/next`
- `POST /api/v1/worker/jobs/{transcription_id}/complete`
- `POST /api/v1/worker/jobs/{transcription_id}/failed`

## Highest Frontend Priorities

1. Selected stem playback sync.
2. Synchronized tab highlighting.
3. Synchronized score highlighting.
4. Waveform sync.
5. Instrument-aware rendering.
6. Stem metadata visibility.
7. Drum rhythm lane rendering.
8. Bass tab rendering.

The selected stem should always be visible in the viewer. Stem confidence, low-confidence warnings, `other` stem limitations, and no-note warning states should be visible without blocking separated-stem playback.

## Highest Backend Priorities

1. Selected-stem processing stability.
2. Basic Pitch quality for selected melodic stems.
3. Bass tab generation.
4. Drum rhythm lane generation.
5. Playback timing accuracy.
6. Export stability.
7. Duplicate reuse.
8. Cloudinary persistence.

## MVP Scope Recommendation

1. Audio upload and YouTube transcription.
2. Selected-stem separation.
3. Guitar tab generation from `other`.
4. Bass tab generation from `bass`.
5. Drum rhythm lane/tab generation from `drums`.
6. Synchronized practice playback with shared waveform/playhead/tab timing.
7. Selected-stem playback/export.
8. Queue-aware processing status.

## Current Next Priorities

1. Stabilize selected-stem processing.
2. Improve Basic Pitch quality for selected melodic stems.
3. Finish bass tab generation.
4. Finish drum rhythm lane/percussion tab generation.
5. Improve playback timing accuracy.
6. Stabilize MIDI, MusicXML, and TAB exports generated from separated-stem transcription results.
7. Harden duplicate reuse.
8. Harden Cloudinary persistence.

## Future Roadmap

- MIDI import.
- Guitar Pro import.
- PowerTab import/export.
- Imported project editing.
- Imported multi-track workflows.
- Lead/rhythm guitar separation.
- True isolated guitar models.
- Piano specialist models.
- Real-time transcription.
- Collaborative editing.
