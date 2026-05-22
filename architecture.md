# MusicStudio MVP Architecture

## Selected-Stem Audio/YouTube MVP

MusicStudio is scoped as a selected-stem transcription MVP for uploaded audio and YouTube sources. Railway or Render is the lightweight FastAPI API/controller layer for auth, database records, status polling, Cloudinary references, and Modal dispatch/callback handling. It should not be treated as the primary Demucs, Basic Pitch, lyrics, or audio-analysis environment for production-like use. The production processing target is a Modal GPU worker, with the backend configured as `AUDIO_PROCESSING_MODE=modal`.

Supported MVP input types:

1. Audio upload
2. YouTube URL

Primary architecture:

```txt
Audio Upload / YouTube URL
-> User selects target stem
-> Generate audio hash or normalize YouTube ID
-> Check existing completed record with same source + selected stem
-> If found, return existing result
-> Upload original audio to Cloudinary
-> Queue processing job
-> Trigger Modal/serverless GPU worker or expose worker pull endpoint
-> Modal worker downloads original audio from Cloudinary
-> Modal worker runs Demucs selected-stem separation on GPU
-> Modal worker uploads selected separated stem to Cloudinary
-> Modal worker normalizes selected separated stem volume
-> Spotify Basic Pitch-style note detection runs only for melodic non-vocal stems (`other`, `bass`)
-> Onset/rhythm analysis runs for `drums`; Basic Pitch does not run on drums
-> faster-whisper lyrics generation runs for `vocals`
-> Generate instrument-aware tabs/notation/rhythm data where supported
-> Modal worker uploads supported MIDI/MusicXML/TAB exports to Cloudinary
-> Modal worker calls backend complete/failed endpoint
-> Backend updates status and output references
-> Frontend renders synchronized playback with waveform, playhead, tabs/score/rhythm, and exports
```

MIDI import, Guitar Pro import, PowerTab import/export, imported project playback architecture, and imported multi-track workflows are not part of the MVP. They remain future roadmap items only. MIDI export, MusicXML export, and TAB export remain in scope when generated from separated-stem transcription results.

## Warning States vs Failures

Stem separation and notation generation are separate capability layers. If Demucs/source separation succeeds, the transcription record should not be marked failed just because note detection returns zero playable notes. In that case the backend records `processing_status=completed_with_warning` or returns API status `completed`, sets `warning_message`, preserves `separated_audio_file_path`/`separated_audio_url` and track stem metadata, and exposes:

- `can_play_stem=true`
- `can_generate_score=false`
- `warning="No note events detected for this stem."`

Only hard blockers such as missing source audio, failed separation, deleted records, or worker infrastructure errors should become `failed`. MIDI, MusicXML, and TAB endpoints return unavailable/export errors when `can_generate_score=false`, while stem preview remains available.

## Stem Capability Matrix

For the MVP:

- `vocals`: selected-stem playback plus lyrics generation with `faster-whisper`. Lyrics use `lyrics_generation_status`, separate from the main `processing_status`, so lyric generation must not reopen the processing screen.
- `drums`: analyze drum stem with onset/rhythm detection only; do not use Basic Pitch; generate a drum rhythm lane and percussion/drum tab where possible, support synchronized playback highlighting, and support drum MIDI export when possible.
- `bass`: analyze bass stem with Basic Pitch, generate 4-string bass tablature using standard E A D G tuning, generate bass score data, and support synchronized playback/playhead highlighting.
- `other`: primary guitar/accompaniment transcription target; analyze with Basic Pitch, generate guitar-oriented tablature, score notation, and synchronized playback/playhead highlighting.

Unsupported notation for a valid separated stem is a warning state, not a processing failure.

## Instrument-Aware Rendering

Viewer behavior:

- `other`/guitar: 6-string tablature plus score notation where generated.
- `bass`: 4-string bass tablature plus bass score notation where generated.
- `drums`: rhythm lane/percussion tab with hit highlighting.
- `vocals`: selected-stem playback plus lyrics view.

All rendered views must share playback synchronization:

- waveform
- playhead
- tabs
- score
- active notes or drum hits
- selected-stem audio

The frontend should use one shared `currentTime` source for waveform, tabs, score, and stem playback. Do not create separate timers for waveform, tab, and score synchronization.

## Basic Pitch, Fallback Transcription, and Retry Flow

Spotify Basic Pitch-style note detection is the primary note detection path for selected melodic non-vocal stems. The note-detection pipeline normalizes separated stem volume before transcription, logs RMS loudness, peak amplitude, onset count, confidence statistics, selected stem, and model output metadata, then retries with lower threshold/high-sensitivity settings if the first pass detects zero notes.

Basic Pitch-style note detection runs only for `other` and `bass`. Drum processing uses onset/rhythm analysis and must not route through Basic Pitch. Vocal processing generates lyrics with `faster-whisper` instead of tabs in the current MVP.

If Basic Pitch still detects zero notes after retry, preserve selected-stem playback and mark the record as `completed_with_warning` with `can_play_stem=true` and `can_generate_score=false`. Score, TAB, MIDI, and MusicXML exports should be disabled or unavailable for that no-note result while the separated stem remains playable.

Users can call `POST /api/v1/audio/{transcription_id}/retry` with lower-threshold mode and an optional alternate `selected_stem`. Same-stem retry can reuse the retained separated stem. Alternate-stem retry requires the original/preprocessed source to still be available so Demucs can run again.

The old architecture is replaced:

```txt
Audio Upload
-> Separate all stems
-> Convert all stems to MIDI
-> Generate all tabs
```

## Stem Model

Demucs default stems are:

- `vocals`
- `drums`
- `bass`
- `other`

The MVP processes one selected stem per job. Guitar/accompaniment transcription uses `other`, because default Demucs models commonly group guitar, piano, synths, melody, and accompaniment into `other` depending on the mix. API metadata and frontend copy should explain this clearly. Do not market the MVP as isolated lead guitar transcription or perfect Songsterr-level accuracy. True isolated guitar, lead guitar, rhythm guitar, and piano stems are later model upgrades.

## Storage

Cloudinary is the durable storage layer for:

- original audio
- selected separated stem audio
- MIDI export files
- MusicXML export files
- TAB export files

Persist both `secure_url` and `public_id` for every Cloudinary asset. Use `resource_type="video"` for audio and separated stems, and `resource_type="raw"` for MIDI/TAB/MusicXML exports. Railway local storage is temporary only and should be used for upload buffering, worker downloads, Demucs scratch output, intermediate MIDI/TAB/MusicXML generation, and cleanup after `completed`, `completed_with_warning`, or `failed`.

## Backend/API

Railway/Render remains useful for:

- FastAPI
- PostgreSQL
- authentication
- project and transcription records
- duplicate detection
- queue/status orchestration and status-first result gating
- Cloudinary upload references
- Modal worker dispatch and callback coordination

Redis is required for local Celery mode and may still be useful for status or queue coordination, but the production-like MVP should not rely on Railway free/trial CPU/RAM for Demucs.

## Processing Mode

`AUDIO_PROCESSING_MODE=modal` is the hosted MVP setting. The backend triggers Modal GPU processing, and Modal handles selected-stem separation, stem-specific generation, Cloudinary output uploads, retry/rate-limit handling, and worker callbacks.

`AUDIO_PROCESSING_MODE=local` is a development fallback only for very short local files. `AUDIO_PROCESSING_MODE=disabled` disables processing.

## Worker Endpoints

Planned worker coordination endpoints:

- `GET /api/v1/worker/jobs/next`
- `POST /api/v1/worker/jobs/{transcription_id}/complete`
- `POST /api/v1/worker/jobs/{transcription_id}/failed`

These endpoints should require `WORKER_API_TOKEN`, return only jobs the worker is allowed to process, store full backend logs, and expose sanitized errors to the frontend.

## Modal Worker

The Modal worker should:

- process one selected stem per job
- use GPU-backed Demucs
- support `vocals`, `drums`, `bass`, and `other`
- download `original_audio_url` from Cloudinary
- upload the selected separated stem to Cloudinary
- normalize selected separated stem volume before transcription
- run Basic Pitch-style note detection only for selected melodic non-vocal stems (`other`, `bass`)
- run onset/rhythm analysis for `drums`
- run faster-whisper lyrics generation for `vocals`
- generate MIDI, MusicXML, and TAB outputs when supported by the selected stem transcription result
- report completion or failure to the backend
- retry/rate-limit Modal dispatch and callback work safely
- keep full logs in Modal/backend while returning user-safe errors to the UI

## Status-First Result Flow

The frontend should poll `GET /api/v1/audio/{id}/status` and call `GET /api/v1/audio/{id}/result` only when status is ready, such as `stem_ready`, `completed`, or `completed_with_warning`. `/result` should not be called for `pending`, `queued`, or `processing` jobs. Lyrics use `lyrics_generation_status` and are updated independently from the main audio `processing_status`.

## Kaggle

Kaggle is optional/manual GPU testing only. It is not 24/7 infrastructure, cannot be reliably auto-started for each user upload, and queued jobs wait until the notebook is running. Do not describe Kaggle as production processing.

## Duplicate Detection

Before queueing a new job, the backend should check whether the same source and selected stem already has a completed result.

```txt
User Upload / YouTube URL + selected stem
-> Generate audio hash or normalize YouTube ID
-> Check existing completed/completed_with_warning record with same source identity + selected_stem
-> If found, return existing result
-> If not found, upload/process normally
-> Save result for future reuse
```

Duplicate identity should consider:

- `audio_hash` for uploaded files
- `normalized_source_id` for YouTube URLs
- `source_type`
- `selected_stem`

The same song plus the same selected stem should reuse output. The same song plus a different selected stem may create a new job because the separated audio, transcription, and exports will differ.

## Deletion and Cancellation

Users should be able to delete processing records with these statuses:

- `completed`
- `completed_with_warning`
- `failed`
- `queued`
- `processing`

Queued jobs should be removed or cancelled when possible. Processing jobs should be marked cancelled/deleted in the database and stopped if cancellation is supported. If active Celery task cancellation is not reliable in the MVP, the UI record can be hidden/deleted, temporary files should still be cleaned up, and the active worker may finish silently.

Deleting a record should also delete related Cloudinary assets when safe:

- original audio: `resource_type="video"`
- separated stem audio: `resource_type="video"`
- MIDI file: `resource_type="raw"`
- MusicXML file: `resource_type="raw"`
- TAB/text export: `resource_type="raw"`

Cloudinary lifecycle management is best-effort but must run before the database row is soft-deleted or hard-deleted. The cleanup service logs asset deleted, skipped, missing, and deletion-failure states. If Cloudinary deletion fails, database deletion should remain safe and the cleanup error should be logged.

Duplicate asset protection is required because completed duplicate records may reuse the same Cloudinary public IDs. Before deleting a public ID, the API checks for references from transcriptions outside the current deletion set.

## Data Model

Recommended transcription/job fields:

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
- `estimated_wait_time`
- `celery_task_id`

Legacy local path fields can remain temporarily during migration, but they should not be treated as durable storage.

Current additive migration: `backend/migrations/20260517_selected_stem_persistence.sql`.
