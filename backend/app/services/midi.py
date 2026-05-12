"""
MIDI conversion utilities for converting pitch detection output to MIDI files.
"""
import mido
from mido import Message, MidiFile, MidiTrack
import json
import os
from pathlib import Path
import tempfile
from typing import Dict, Any, Optional


def notes_to_midi(notes_data: Dict[str, Any], output_path: Optional[str] = None,
                  ticks_per_beat: int = 480, tempo_bpm: Optional[float] = None) -> str:
    """
    Convert pitch detection output to MIDI file.

    Args:
        notes_data: Dictionary containing pitch detection results from audio.detect_pitch()
        output_path: Path to save the MIDI file. If None, creates a temporary file.
        ticks_per_beat: MIDI resolution (default: 480)
        tempo_bpm: Tempo in beats per minute. If None, uses detected tempo from notes_data or defaults to 120

    Returns:
        Path to the generated MIDI file
    """
    # Handle both direct notes_data and JSON string formats
    if isinstance(notes_data, str):
        try:
            notes_data = json.loads(notes_data)
        except json.JSONDecodeError:
            raise ValueError("Invalid notes_data format")

    # Extract notes array
    if "notes" in notes_data:
        notes = notes_data["notes"]
    elif isinstance(notes_data, list):
        notes = notes_data
    else:
        raise ValueError("Invalid notes_data structure")

    # Create MIDI file and track
    mid = MidiFile(ticks_per_beat=ticks_per_beat)
    track = MidiTrack()
    mid.tracks.append(track)

    # Determine tempo to use
    if tempo_bpm is None:
        # Try to get tempo from notes_data if available
        if "tempo" in notes_data:
            tempo_bpm = float(notes_data["tempo"])
        else:
            tempo_bpm = 120.0  # Default tempo

    # Convert BPM to microseconds per beat for MIDI
    tempo_microseconds_per_beat = int(60000000 / tempo_bpm)
    track.append(mido.MetaMessage('set_tempo', tempo=tempo_microseconds_per_beat))

    # Convert notes to MIDI messages
    # We need to convert time in seconds to MIDI ticks
    seconds_per_tick = 60.0 / (tempo_microseconds_per_beat / 1000000) / ticks_per_beat  # seconds per tick

    for note in notes:
        # Validate note structure
        if not all(key in note for key in ["onset", "offset", "pitch", "velocity"]):
            continue

        onset_tick = int(note["onset"] / seconds_per_tick)
        offset_tick = int(note["offset"] / seconds_per_tick)
        duration_tick = max(0, offset_tick - onset_tick)  # Ensure non-negative duration

        # Note on message
        track.append(Message('note_on',
                           note=note["pitch"],
                           velocity=note["velocity"],
                           time=onset_tick))

        # Note off message
        track.append(Message('note_off',
                           note=note["pitch"],
                           velocity=0,
                           time=duration_tick))

    # Save the MIDI file
    if output_path is None:
        # Create temporary file
        temp_dir = tempfile.mkdtemp()
        output_path = str(Path(temp_dir) / "output.mid")

    # Ensure output directory exists
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    mid.save(output_path)
    return output_path


def save_midi_from_transcription(notes_data: str, transcription_id: int,
                                uploads_dir: str = "uploads") -> str:
    """
    Save MIDI file from transcription notes data to the uploads directory.

    Args:
        notes_data: JSON string containing pitch detection results
        transcription_id: ID of the transcription
        uploads_dir: Base uploads directory

    Returns:
        Relative path to the saved MIDI file
    """
    # Create midi subdirectory if it doesn't exist
    midi_dir = Path(uploads_dir) / "midi"
    midi_dir.mkdir(parents=True, exist_ok=True)

    # Generate file path
    midi_file_name = f"transcription_{transcription_id}.mid"
    midi_file_path = midi_dir / midi_file_name

    # Convert notes to MIDI and save
    notes_to_midi(notes_data, str(midi_file_path))

    # Return relative path for storage in database
    return str(midi_file_path)


def midi_to_notes(midi_file_path: str) -> Dict[str, Any]:
    """
    Extract note events from a MIDI file and return them in the same format as pitch detection output.

    Args:
        midi_file_path: Path to the MIDI file to extract notes from.

    Returns:
        Dictionary containing pitch detection results in the format:
        {
            "notes": [
                {
                    "onset": float,      // Start time in seconds
                    "offset": float,     // End time in seconds
                    "pitch": int,        // MIDI note number (0-127)
                    "velocity": int,     // Note velocity (0-127)
                    "confidence": float  // Set to 1.0 for MIDI note events
                }
            ],
            "model_outputs": {},
            "total_notes_detected": int
        }

    Raises:
        ValueError: If the file is invalid or not a MIDI file.
    """
    try:
        midi_file = MidiFile(midi_file_path)
    except Exception as e:
        raise ValueError(f"Invalid MIDI file: {e}")

    ticks_per_beat = midi_file.ticks_per_beat
    if ticks_per_beat == 0:
        raise ValueError("Invalid MIDI file: ticks_per_beat is zero")

    # Find tempo (in microseconds per beat)
    tempo_microseconds_per_beat = 500000  # Default 120 BPM
    for track in midi_file.tracks:
        for msg in track:
            if msg.type == 'set_tempo':
                tempo_microseconds_per_beat = msg.tempo
                break
        if tempo_microseconds_per_beat != 500000:  # If we found a non-default tempo
            break

    # Time conversion: seconds per tick
    seconds_per_tick = tempo_microseconds_per_beat / 1000000.0 / ticks_per_beat

    # Track active notes: key = (note_number, channel) -> (onset_tick, onset_time, velocity)
    active_notes = {}
    notes = []  # List to hold the final note dictionaries

    # Process all tracks
    for track_index, track in enumerate(midi_file.tracks):
        current_tick = 0
        for msg in track:
            current_tick += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                # Note on
                key = (msg.note, msg.channel)
                active_notes[key] = {
                    'onset_tick': current_tick,
                    'velocity': msg.velocity
                }
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                # Note off
                key = (msg.note, msg.channel)
                if key in active_notes:
                    onset_info = active_notes.pop(key)
                    onset_tick = onset_info['onset_tick']
                    offset_tick = current_tick

                    # Convert ticks to seconds
                    onset_time = onset_tick * seconds_per_tick
                    offset_time = offset_tick * seconds_per_tick

                    # Only include notes within MIDI range 0-127
                    if 0 <= msg.note <= 127:
                        note_dict = {
                            'onset': round(onset_time, 3),
                            'offset': round(offset_time, 3),
                            'pitch': msg.note,
                            'velocity': onset_info['velocity'],
                            'confidence': 1.0
                        }
                        notes.append(note_dict)
                    # Note: notes outside 0-127 are skipped (silently ignored)

    # Sort notes by onset time
    notes.sort(key=lambda x: x['onset'])

    return {
        "notes": notes,
        "model_outputs": {},
        "total_notes_detected": len(notes)
    }