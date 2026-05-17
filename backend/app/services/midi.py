"""
MIDI conversion utilities for converting pitch detection output to MIDI files.
"""
import mido
from mido import Message, MidiFile, MidiTrack
import json
import os
from pathlib import Path
import tempfile
from typing import Dict, Any, List, Optional

# Optional: music21 for MusicXML conversion
try:
    from music21 import converter
    MUSIC21_AVAILABLE = True
except ImportError:
    MUSIC21_AVAILABLE = False


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

    notes = _extract_notes(notes_data)

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
    seconds_per_tick = tempo_microseconds_per_beat / 1000000.0 / ticks_per_beat

    events = []
    for note in notes:
        # Validate note structure
        if not all(key in note for key in ["onset", "offset", "pitch", "velocity"]):
            continue

        onset_tick = int(note["onset"] / seconds_per_tick)
        offset_tick = int(note["offset"] / seconds_per_tick)
        pitch = int(note["pitch"])
        velocity = int(note["velocity"])
        if 0 <= pitch <= 127:
            events.append((max(0, onset_tick), 1, Message('note_on', note=pitch, velocity=velocity, time=0)))
            events.append((max(0, offset_tick), 0, Message('note_off', note=pitch, velocity=0, time=0)))

    previous_tick = 0
    for tick, _, message in sorted(events, key=lambda event: (event[0], event[1])):
        message.time = max(0, tick - previous_tick)
        track.append(message)
        previous_tick = tick

    # Save the MIDI file
    if output_path is None:
        # Create temporary file
        temp_dir = tempfile.mkdtemp()
        output_path = str(Path(temp_dir) / "output.mid")

    # Ensure output directory exists
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    mid.save(output_path)
    return Path(output_path).as_posix()


def _extract_notes(notes_data: Any) -> List[Dict[str, Any]]:
    """Extract note events from supported pitch-analysis shapes."""
    if isinstance(notes_data, str):
        try:
            notes_data = json.loads(notes_data)
        except json.JSONDecodeError:
            raise ValueError("Invalid notes_data format")

    if isinstance(notes_data, list):
        return notes_data

    if isinstance(notes_data, dict):
        if isinstance(notes_data.get("notes"), list):
            return notes_data["notes"]
        if isinstance(notes_data.get("pitch_info"), list):
            return notes_data["pitch_info"]

    raise ValueError("Invalid notes_data structure")


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
    return midi_file_path.as_posix()


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


def midi_to_musicxml(midi_file_path: str) -> str:
    """
    Convert a MIDI file to MusicXML string using music21.

    Args:
        midi_file_path: Path to the MIDI file.

    Returns:
        MusicXML string representation of the MIDI file.

    Raises:
        ImportError: If music21 is not installed.
        ValueError: If the MIDI file is invalid or conversion fails.
    """
    if not MUSIC21_AVAILABLE:
        raise ImportError("music21 is not installed. Install it with 'pip install music21'")

    try:
        midi_score = converter.parse(midi_file_path)
        with tempfile.NamedTemporaryFile(suffix=".musicxml", delete=False) as temp_file:
            temp_path = temp_file.name

        try:
            musicxml_path = midi_score.write('musicxml', fp=temp_path)
            with open(musicxml_path, "r", encoding="utf-8") as f:
                return f.read()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    except Exception as e:
        raise ValueError(f"Failed to convert MIDI to MusicXML: {e}")
