# Implementation Summary: Phase 2 - Convert Pitch Detection Output to MIDI Notes

## Overview
This implementation adds MIDI file generation capabilities to the AI Guitar Music Sheet Generator by converting pitch detection output to MIDI notes using the mido library.

## Changes Made

### 1. Dependencies
- Added `mido==1.2.0` to `backend/requirements.txt`

### 2. New Service
- Created `backend/app/services/midi.py` with:
  - `notes_to_midi()` function: Converts pitch detection data to MIDI file
  - `save_midi_from_transcription()` function: Saves MIDI file to uploads/midi/ directory

### 3. Database Model
- Added `midi_file_path` column to `Transcription` model in `backend/app/models.py`
  - Stores the file path to the generated MIDI file

### 4. API Schemas
- Added `midi_file_path` field to Transcription schemas in `backend/app/schemas.py`
  - Included in both `TranscriptionBase` and `TranscriptionInDBBase`

### 5. Background Processing
- Modified `backend/app/tasks.py`:
  - Imported the midi service
  - In the pitch detection success block, after storing notes_data:
    - Generates MIDI file using `save_midi_from_transcription()`
    - Stores the file path in `transcription.midi_file_path`
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
4. The MIDI file is saved to `uploads/midi/transcription_{id}.mid`
5. The file path is stored in the transcription's `midi_file_path` field
6. Users can retrieve the MIDI file via the `/midi` endpoint

## Usage
- Process an audio file through the transcription pipeline
- Once processing is complete, access the MIDI file at:
  `GET /api/v1/audio/{transcription_id}/midi`
- The endpoint returns a downloadable MIDI file with proper content type

## Verification
To verify the implementation:
1. Upload an audio file and wait for processing to complete
2. Check that the transcription record has a non-null `midi_file_path`
3. Verify that the file exists at the specified path
4. Call the MIDI endpoint and confirm it returns a valid MIDI file
5. Test edge cases (empty notes data, processing errors, etc.)

## Note on Timing
The current implementation uses a fixed tempo (120 BPM) for MIDI timing when the detected tempo is not available in the pitch detection data. For improved accuracy, future versions could use the detected_tempo from the transcription record.