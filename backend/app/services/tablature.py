"""
Tablature generation utilities for converting MIDI notes to guitar tablature.
"""
import json
import math
from typing import Dict, Any, List, Optional, Tuple, Union


STANDARD_GUITAR_TUNING = [40, 45, 50, 55, 59, 64]
STANDARD_BASS_TUNING = [28, 33, 38, 43]


def _parse_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def has_structured_tablature(tablature_data: Any) -> bool:
    """Return True only for non-empty structured TAB payloads."""
    parsed = _parse_jsonish(tablature_data)
    if not isinstance(parsed, dict):
        return False

    tablature = parsed.get("tablature")
    if not isinstance(tablature, list):
        return False

    return any(bool(event) for event in tablature)


def has_note_events(notes_data: Any) -> bool:
    parsed = _parse_jsonish(notes_data)
    if isinstance(parsed, list):
        return bool(parsed)
    if isinstance(parsed, dict):
        notes = parsed.get("notes")
        pitch_info = parsed.get("pitch_info")
        return (
            isinstance(notes, list) and bool(notes)
        ) or (
            isinstance(pitch_info, list) and bool(pitch_info)
        )
    return False


def repair_structured_tablature(
    selected_stem: str | None,
    notes_data: Any,
    tablature_data: Any,
) -> Dict[str, Any] | None:
    """Build structured TAB from notes only when stored TAB is absent or invalid."""
    if has_structured_tablature(tablature_data):
        return None

    stem = (selected_stem or "other").strip().lower()
    if stem not in {"bass", "other"} or not has_note_events(notes_data):
        return None

    instrument_type = "bass" if stem == "bass" else "guitar"
    repaired = notes_to_tablature(notes_data, instrument_type=instrument_type)
    if not has_structured_tablature(repaired):
        return None
    return repaired


def get_standard_tuning(instrument_type: str = "guitar") -> List[int]:
    """Return standard open-string MIDI notes for supported tab instruments."""
    normalized_instrument = (instrument_type or "guitar").lower()
    if normalized_instrument == "bass":
        return STANDARD_BASS_TUNING.copy()
    return STANDARD_GUITAR_TUNING.copy()


def notes_to_tablature(notes_data: Dict[str, Any],
                       tuning: Optional[List[int]] = None,
                       max_fret: int = 24,
                       instrument_type: str = "guitar") -> Dict[str, Any]:
    """
    Convert pitch detection output to guitar tablature.

    Args:
        notes_data: Dictionary containing pitch detection results from audio.detect_pitch()
        tuning: List of MIDI note numbers for the open strings from lowest to highest.
                Default: standard guitar tuning [40, 45, 50, 55, 59, 64]
        max_fret: Maximum fret to consider (default: 24)
        instrument_type: Instrument tuning preset to use when tuning is omitted.

    Returns:
        Dictionary containing the tuning and tablature notes.
        Tablature notes are a list of dictionaries with keys:
            string (1-number of strings, where 1 is the highest string),
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

    notes = _extract_notes(notes_data)

    # Set default tuning.
    if tuning is None:
        tuning = get_standard_tuning(instrument_type)

    # Validate tuning
    if len(tuning) < 1:
        raise ValueError("Tuning must include at least one string")

    # For each note, find all possible (string_index, fret) pairs
    # string_index: 0 to len(tuning) - 1 (0=lowest string)
    note_options = []  # List of lists of (string_index, fret) for each note
    for note in notes:
        # Validate note structure
        if not all(key in note for key in ["onset", "offset", "pitch", "velocity"]):
            # Skip invalid notes
            note_options.append([])
            continue

        midi_note = note["pitch"]
        if midi_note is None:
            note_options.append([])
            continue
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
        # Convert string_index to string number (1=highest string).
        string_number = len(tuning) - string_index
        tablature_note = {
            "string": string_number,
            "fret": fret,
            "onset": round(note.get("onset") or 0, 3),
            "offset": round(note.get("offset") or 0, 3),
            "velocity": note.get("velocity") or 64,
            "confidence": round(note.get("confidence") or 0.8, 3)
        }
        tablature_notes.append(tablature_note)

    return {
        "instrument": instrument_type,
        "tuning": tuning,
        "tablature": tablature_notes
    }


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
    return tab_file_path.as_posix()


def tablature_to_ascii_tab(tablature_data: Union[str, dict]) -> str:
    """
    Convert tablature data (JSON string or dict) to ASCII tab format.

    Args:
        tablature_data: JSON string or dict containing tablature data from notes_to_tablature()

    Returns:
        ASCII tab string ready for display/download
    """
    # Parse JSON if string
    if isinstance(tablature_data, str):
        try:
            tablature_dict = json.loads(tablature_data)
        except json.JSONDecodeError:
            raise ValueError("Invalid tablature data format")
    else:
        tablature_dict = tablature_data

    # Extract tablature notes
    tablature_notes = tablature_dict.get("tablature", [])
    if not tablature_notes:
        return ""  # Return empty string if no notes

    # Calculate total duration (max offset)
    max_offset = max((note.get("offset") or 0) for note in tablature_notes)
    if max_offset <= 0:
        max_offset = 0.1  # Avoid division by zero

    # Configuration for ASCII tab generation
    block_time = 0.1        # seconds per note block
    columns_per_block = 2   # columns per note block (for 2-digit frets)

    # Calculate total columns needed
    num_blocks = math.ceil(max_offset / block_time)
    total_columns = num_blocks * columns_per_block

    tuning = tablature_dict.get("tuning") or STANDARD_GUITAR_TUNING
    string_count = len(tuning)
    if string_count == 4:
        string_labels = ['G', 'D', 'A', 'E']
    else:
        string_labels = ['e', 'B', 'G', 'D', 'A', 'E'][:string_count]

    # Initialize tab array with strings ordered highest to lowest.
    tab_array = [['-' for _ in range(total_columns)] for _ in range(string_count)]

    # Process each note
    for note in tablature_notes:
        string_num = note.get("string") or 1  # 1=highest string
        fret = note.get("fret") or 0
        onset = note.get("onset") or 0.0

        # Validate string number
        if string_num < 1 or string_num > string_count:
            continue

        # Calculate column position
        row_index = string_num - 1  # Convert to 0-based index (0=high E)
        block_index = round(onset / block_time)

        # Clamp block index to valid range
        max_block_index = num_blocks - 1
        if block_index < 0:
            block_index = 0
        elif block_index > max_block_index:
            block_index = max_block_index

        column_start = block_index * columns_per_block

        # Format fret as right-aligned 2-character string
        fret_str = str(fret).rjust(2)

        # Place fret characters in tab array
        for i, ch in enumerate(fret_str):
            col = column_start + i
            if col < total_columns:
                tab_array[row_index][col] = ch

    # Build output lines
    lines = []
    for i in range(string_count):
        line_content = ''.join(tab_array[i])
        lines.append(f"{string_labels[i]}|{line_content}")

    return "\n".join(lines)
