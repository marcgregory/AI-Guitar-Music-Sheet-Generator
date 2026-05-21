# Implementation Summary: Phase 2 - Convert Pitch Detection Output to MIDI Notes

## Overview

This historical implementation note records MIDI file generation work. The current MVP architecture is selected-stem-first: generate MIDI only for the selected stem when supported, upload durable MIDI output to Cloudinary, and persist Cloudinary references instead of relying on Railway local file paths.

## Changes Made

### 1. Dependencies

- Added `mido==1.2.0` to `backend/requirements.txt`

### 2. New Service

- Created `backend/app/services/midi.py` with:
  - `notes_to_midi()` function: Converts pitch detection data to MIDI file
  - `save_midi_from_transcription()` function: Historical helper that saves MIDI locally before Cloudinary upload in the current MVP architecture

### 3. Database Model

- Added `midi_file_path` column to `Transcription` model in `backend/app/models.py`
  - Historical local path field. New MVP storage should prefer `midi_file_url` and `midi_file_public_id` after Cloudinary upload.

### 4. API Schemas

- Added `midi_file_path` field to Transcription schemas in `backend/app/schemas.py`
  - Historical local path field. New schemas should expose `midi_file_url` and `midi_file_public_id` for durable output.

### 5. Background Processing

- Modified `backend/app/tasks.py`:
  - Imported the midi service
  - In the pitch detection success block, after storing notes_data:
    - Generates MIDI file using `save_midi_from_transcription()`
    - Historically stored the file path in `transcription.midi_file_path`; the current MVP should upload to Cloudinary and store URL/public ID fields
    - Handles MIDI generation errors gracefully (doesn't fail transcription)

### 6. API Endpoint

- Added new GET endpoint in `backend/app/api/v1/endpoints/audio.py`:
  - `GET /{transcription_id}/midi`
  - Returns the generated MIDI file as a FileResponse
  - Includes proper authorization and validation checks
  - Returns 404 if MIDI file not available, 400 if still processing, 403 if unauthorized

## How It Works

1. When audio is processed, pitch detection runs (Basic Pitch or CREPE fallback)
2. Pitch detection results are stored as JSON in `notes_data`
3. Immediately after, the system generates a MIDI file from this data
4. The MIDI file is created in temporary worker storage
5. The MIDI file is uploaded to Cloudinary
6. `midi_file_url` and `midi_file_public_id` are stored on the transcription/job record
7. Users can download the Cloudinary-hosted MIDI file through the API or frontend link

## Usage

- Process an audio file through the transcription pipeline
- Once processing is complete, access the MIDI file at:
  `GET /api/v1/audio/{transcription_id}/midi`
- The endpoint returns a downloadable MIDI file with proper content type

## Verification

To verify the implementation:

1. Upload an audio file and wait for processing to complete
2. Check that the transcription record has a non-null `midi_file_url` and `midi_file_public_id`
3. Verify that temporary local MIDI files are cleaned up after terminal job status
4. Call the MIDI endpoint and confirm it returns a valid MIDI file
5. Test edge cases (empty notes data, processing errors, etc.)

## Note on Timing

The current implementation uses a fixed tempo (120 BPM) for MIDI timing when the detected tempo is not available in the pitch detection data. For improved accuracy, future versions could use the detected_tempo from the transcription record.

## Current MVP Direction

Completed historical note/staff work should be interpreted through the current selected-stem MVP architecture. Vocal stems now use Generate Lyrics with faster-whisper and separate `lyrics_generation_status`; vocal melody/staff notation is future work.

Next priorities:

- Keep result fetching gated behind `/status`; call `/result` only after a ready status such as `stem_ready`, `completed`, or `completed_with_warning`.
- Preserve non-vocal Generate Tabs behavior for `other` and `bass`.
- Keep Modal as the heavy AI/audio worker with `AUDIO_PROCESSING_MODE=modal`.

Relevant files:

- `backend/app/tasks.py`
- `backend/app/api/v1/endpoints/audio.py`
- `backend/tests/test_music_output_services.py`
- `backend/tests/test_audio_list_endpoint.py`
- `frontend/src/components/TranscriptionViewer.tsx`
- `implementation-plan.md`

Verification last run:

- `python -m py_compile app/tasks.py app/api/v1/endpoints/audio.py`
- `python -m pytest tests/test_music_output_services.py tests/test_audio_list_endpoint.py`
- `npm run build`
