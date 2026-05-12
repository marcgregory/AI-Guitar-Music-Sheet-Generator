"""
Tablature generation utilities for converting MIDI notes to guitar tablature.
"""
import json
from typing import Dict, Any, List, Optional, Tuple


def notes_to_tablature(notes_data: Dict[str, Any],
                       tuning: Optional[List[int]] = None,
                       max_fret: int = 24) -> Dict[str, Any]:
    """
    Convert pitch detection output to guitar tablature.

    Args:
        notes_data: Dictionary containing pitch detection results from audio.detect_pitch()
        tuning: List of MIDI note numbers for the open strings from 6th string (low E) to 1st string (high E).
                Default: standard tuning [40, 45, 50, 55, 59, 64]
        max_fret: Maximum fret to consider (default: 24)

    Returns:
        Dictionary containing the tuning and tablature notes.
        Tablature notes are a list of dictionaries with keys:
            string (1-6, where 1 is high E, 6 is low E),
            fret (0-max_fret),
            onset (float),
            offset (float),
            velocity (int),
            confidence (float)
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

    # Set default tuning (standard guitar: E2, A2, D3, G3, B3, E4)
    if tuning is None:
        tuning = [40, 45, 50, 55, 59, 64]  # MIDI notes for open strings 6th to 1st

    # Validate tuning
    if len(tuning) != 6:
        raise ValueError("Tuning must have 6 strings for standard guitar")

    # For each note, find all possible (string_index, fret) pairs
    # string_index: 0 to 5 (0=6th string, 5=1st string)
    note_options = []  # List of lists of (string_index, fret) for each note
    for note in notes:
        # Validate note structure
        if not all(key in note for key in ["onset", "offset", "pitch", "velocity"]):
            # Skip invalid notes
            note_options.append([])
            continue

        midi_note = note["pitch"]
        options = []
        for string_index, open_note in enumerate(tuning):
            fret = midi_note - open_note
            if 0 <= fret <= max_fret:
                options.append((string_index, fret))
        note_options.append(options)

    # Now choose the best option for each note to minimize jumping
    # We'll use a simple greedy algorithm: for each note, choose the option that is closest
    # to the previous note's chosen string and fret.
    chosen_options = []  # List of (string_index, fret) for each note
    prev_string_index = None
    prev_fret = None

    for i, options in enumerate(note_options):
        if not options:
            # No options for this note, skip it (or we could choose a placeholder?)
            chosen_options.append(None)
            continue

        if prev_string_index is None:
            # First note: choose the option with the smallest fret (or highest string for tone?)
            # We'll choose the option with the smallest fret, and if tie, highest string (so we prefer higher strings)
            best_option = min(options, key=lambda x: (x[1], -x[0]))  # min fret, then max string_index (since string_index 0 is low E, 5 is high E)
            chosen_options.append(best_option)
            prev_string_index, prev_fret = best_option
        else:
            # Choose the option that minimizes the distance from the previous note
            # We'll define distance as: sqrt((string_index - prev_string_index)^2 + (fret - prev_fret)^2)
            # But we can also weight string changes more than fret changes.
            # For simplicity, we'll use Euclidean distance.
            best_option = min(options,
                              key=lambda x: ((x[0] - prev_string_index) ** 2 + (x[1] - prev_fret) ** 2))
            chosen_options.append(best_option)
            prev_string_index, prev_fret = best_option

    # Build the tablature notes list
    tablature_notes = []
    for i, note in enumerate(notes):
        if i >= len(chosen_options) or chosen_options[i] is None:
            # Skip notes that couldn't be mapped
            continue
        string_index, fret = chosen_options[i]
        # Convert string_index to string number (1=high E, 6=low E)
        string_number = 6 - string_index  # because string_index 0 is 6th string, 5 is 1st string
        tablature_note = {
            "string": string_number,
            "fret": fret,
            "onset": round(note.get("onset", 0), 3),
            "offset": round(note.get("offset", 0), 3),
            "velocity": note.get("velocity", 64),
            "confidence": round(note.get("confidence", 0.8), 3)
        }
        tablature_notes.append(tablature_note)

    return {
        "tuning": tuning,
        "tablature": tablature_notes
    }


def save_tablature_from_transcription(notes_data: str, transcription_id: int,
                                     uploads_dir: str = "uploads") -> str:
    """
    Save tablature data from transcription notes data to a JSON file in the uploads directory.

    Args:
        notes_data: JSON string containing pitch detection results
        transcription_id: ID of the transcription
        uploads_dir: Base uploads directory

    Returns:
        Relative path to the saved tablature JSON file
    """
    import json
    import os
    from pathlib import Path

    # Generate tablature data
    tablature_data = notes_to_tablature(notes_data)

    # Create a subdirectory for tablature if we want to organize, but for now we'll put in uploads
    # Alternatively, we can store it in the database directly and not save a file.
    # However, the plan says to store transcription results in database, so we'll store in the tablature_data field.
    # This function is kept for consistency with the MIDI service, but we might not need to save a file.
    # We'll return a placeholder path or None.

    # Since we are storing in the database, we don't need to save a file.
    # We'll return an empty string or None to indicate that the data is stored in the database.
    # But to match the pattern of the MIDI service, let's save a JSON file as well.

    # Create tablature subdirectory
    tab_dir = Path(uploads_dir) / "tablature"
    tab_dir.mkdir(parents=True, exist_ok=True)

    # Generate file path
    tab_file_name = f"transcription_{transcription_id}_tab.json"
    tab_file_path = tab_dir / tab_file_name

    # Save tablature data as JSON
    with open(tab_file_path, 'w') as f:
        json.dump(tablature_data, f, indent=2)

    # Return relative path for storage in database (if we wanted to store the path)
    # But we are storing the actual data in the tablature_data field, so we don't need this.
    # We'll return the path anyway in case we change our mind.
    return str(tab_file_path)