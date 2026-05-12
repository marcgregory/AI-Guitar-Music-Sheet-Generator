"""
Chord chart generation utilities for converting detected chords to guitar chord diagrams.
"""
import json
from typing import Dict, Any, List, Optional, Tuple
import os
from pathlib import Path


def parse_chord_symbol(chord_symbol: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse a chord symbol into root and type.

    Args:
        chord_symbol: Chord symbol like "C:maj", "G:min", "D:7", "N" (no chord)

    Returns:
        Tuple of (root, chord_type) or (None, None) if invalid/no chord
    """
    if chord_symbol == "N":
        return None, None

    if ":" not in chord_symbol:
        # Assume major chord if no type specified
        return chord_symbol, "maj"

    parts = chord_symbol.split(":", 1)
    root = parts[0]
    chord_type = parts[1]

    return root, chord_type


def get_chord_intervals(chord_type: str) -> List[int]:
    """
    Get semitone intervals for a chord type from the root note.

    Args:
        chord_type: Chord type suffix (maj, min, 7, etc.)

    Returns:
        List of semitone intervals from root
    """
    # Define intervals for common chord types
    chord_intervals = {
        "maj": [0, 4, 7],           # Major triad: root, major third, perfect fifth
        "min": [0, 3, 7],           # Minor triad: root, minor third, perfect fifth
        "7": [0, 4, 7, 10],         # Dominant 7th: major triad + minor seventh
        "maj7": [0, 4, 7, 11],      # Major 7th: major triad + major seventh
        "min7": [0, 3, 7, 10],      # Minor 7th: minor triad + minor seventh
        "dim": [0, 3, 6],           # Diminished triad: root, minor third, diminished fifth
        "aug": [0, 4, 8],           # Augmented triad: root, major third, augmented fifth
        "sus2": [0, 2, 7],          # Suspended 2nd: root, major second, perfect fifth
        "sus4": [0, 5, 7],          # Suspended 4th: root, perfect fourth, perfect fifth
        "6": [0, 4, 7, 9],          # Major 6th: major triad + major sixth
        "min6": [0, 3, 7, 9],       # Minor 6th: minor triad + major sixth
        "9": [0, 4, 7, 10, 14],     # Dominant 9th: dominant 7th + major ninth
        "maj9": [0, 4, 7, 11, 14],  # Major 9th: major 7th + major ninth
        "min9": [0, 3, 7, 10, 14],  # Minor 9th: minor 7th + major ninth
    }

    return chord_intervals.get(chord_type, [0, 4, 7])  # Default to major triad


def note_name_to_midi(note_name: str) -> int:
    """
    Convert a note name to MIDI note number.

    Args:
        note_name: Note name like "C", "C#", "Db", etc.

    Returns:
        MIDI note number (0-127)
    """
    # Note names to semitone offset from C
    note_map = {
        "C": 0, "B#": 0,
        "C#": 1, "Db": 1,
        "D": 2,
        "D#": 3, "Eb": 3,
        "E": 4, "Fb": 4,
        "E#": 5, "F": 5,
        "F#": 6, "Gb": 6,
        "G": 7,
        "G#": 8, "Ab": 8,
        "A": 9,
        "A#": 10, "Bb": 10,
        "B": 11, "Cb": 11
    }

    # Extract note name without octave
    base_name = ''.join([c for c in note_name if not c.isdigit()])

    if base_name not in note_map:
        raise ValueError(f"Invalid note name: {note_name}")

    # Extract octave if present
    octave_part = ''.join([c for c in note_name if c.isdigit()])
    octave = int(octave_part) if octave_part else 4  # Default to octave 4

    # MIDI note = 12 * (octave + 1) + note_offset
    # Actually, MIDI note 0 is C-1, so MIDI note = 12 * (octave + 1) + note_offset
    # But let's use a simpler approach: A4 = 69
    # A4 is note_name "A4" -> note_offset=9, octave=4 -> 12*4 + 9 = 57 + 12 = 69 ✓
    midi_note = 12 * octave + note_map[base_name]

    return midi_note


def midi_to_note_name(midi_note: int) -> str:
    """
    Convert MIDI note number to note name (simplified, returns sharps).

    Args:
        midi_note: MIDI note number (0-127)

    Returns:
        Note name like "C4", "C#4", etc.
    """
    note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    octave = (midi_note // 12) - 1
    note_index = midi_note % 12
    return f"{note_names[note_index]}{octave}"


def get_guitar_tuning() -> List[int]:
    """
    Get standard guitar tuning as MIDI note numbers.

    Returns:
        List of MIDI note numbers for strings 6 to 1 (low E to high E)
    """
    # Standard tuning: E2, A2, D3, G3, B3, E4
    return [40, 45, 50, 55, 59, 64]  # MIDI notes


def find_chord_positions(root_note: str, chord_type: str,
                         max_fret: int = 12,
                         tuning: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    """
    Find all possible guitar fret positions for a chord.

    Args:
        root_note: Root note name (e.g., "C", "G#")
        chord_type: Chord type (e.g., "maj", "min", "7")
        max_fret: Maximum fret to consider
        tuning: Guitar tuning as MIDI note numbers (6 strings, low to high)

    Returns:
        List of possible fingerings, each as a dict with:
        - frets: List of fret numbers for each string (None for muted/unplayed)
        - bars: List of barre information (start_string, end_string, fret)
        - fingers: Suggested finger placement (simplified)
        - score: Playability score (lower is better)
    """
    if tuning is None:
        tuning = get_guitar_tuning()

    # Parse root note to get MIDI note number
    try:
        root_midi = note_name_to_midi(root_note)
    except ValueError:
        # If we can't parse the note name, return empty list
        return []

    # Get chord intervals
    intervals = get_chord_intervals(chord_type)

    # Calculate target notes for the chord
    target_notes = [root_midi + interval for interval in intervals]

    # For each string, find frets that produce notes in the chord
    string_options = []  # List of lists of possible frets for each string
    for string_index, open_note in enumerate(tuning):
        frets = []
        for target_note in target_notes:
            fret = target_note - open_note
            if 0 <= fret <= max_fret:
                frets.append(fret)
        # Also consider muting the string (fret = None)
        frets.append(None)
        string_options.append(sorted(list(set(frets))))  # Remove duplicates and sort

    # Generate all possible combinations (this could be huge, so we'll use a smarter approach)
    # For now, let's implement a basic backtracking algorithm with pruning

    # We'll generate fingerings by selecting one fret per string
    best_fingerings = []

    def backtrack(string_index: int, current_frets: List[Optional[int]],
                  used_notes: set, depth: int):
        # If we've processed all strings
        if string_index == len(tuning):
            # Check if we have all required notes covered
            # For simplicity, we'll accept any fingering that plays notes from the chord
            # A more sophisticated approach would ensure all chord tones are present

            # Calculate a simple score based on:
            # - Number of fretted notes (more is generally better)
            # - Average fret position (lower is generally better)
            # - Whether we have a barre (can be good or bad depending on context)

            fretted_count = sum(1 for f in current_frets if f is not None)
            if fretted_count == 0:
                return  # Skip all-muted fingerings

            avg_fret = sum(f for f in current_frets if f is not None) / fretted_count

            # Simple scoring: prefer lower frets and more fretted notes
            score = avg_fret * 2 - fretted_count * 0.5

            # Determine if we have a barre
            bars = []
            # Check for consecutive strings at same fret
            for fret in range(max_fret + 1):
                strings_at_fret = [i for i, f in enumerate(current_frets) if f == fret]
                if len(strings_at_fret) >= 2:  # At least 2 strings at same fret
                    # Check if they are consecutive
                    strings_at_fret.sort()
                    start = strings_at_fret[0]
                    end = strings_at_fret[-1]
                    if end - start + 1 == len(strings_at_fret):  # Consecutive
                        bars.append({
                            'start_string': start,
                            'end_string': end,
                            'fret': fret
                        })

            fingering = {
                'frets': current_frets.copy(),
                'bars': bars,
                'score': score
            }
            best_fingerings.append(fingering)
            return

        # Try each possible fret for this string
        for fret in string_options[string_index]:
            current_frets.append(fret)
            # Simple pruning: if we're already too high in fret, skip deeper searches
            fretted_so_far = [f for f in current_frets if f is not None]
            if fretted_so_far and max(fretted_so_far) > max_fret * 0.7:  # Don't go too high
                current_frets.pop()
                continue
            backtrack(string_index + 1, current_frets, used_notes, depth + 1)
            current_frets.pop()

    backtrack(0, [], set(), 0)

    # Sort by score (lower is better) and return top options
    best_fingerings.sort(key=lambda x: x['score'])
    return best_fingerings[:5]  # Return top 5 fingerings


def generate_chord_chart_svg(fingering: Dict[str, Any],
                             chord_symbol: str,
                             width: int = 200,
                             height: int = 250) -> str:
    """
    Generate an SVG chord diagram from a fingering.

    Args:
        fingering: Fingering dict from find_chord_positions
        chord_symbol: Original chord symbol (e.g., "C:maj")
        width: SVG width in pixels
        height: SVG height in pixels

    Returns:
        SVG string representing the chord diagram
    """
    frets = fingering['frets']
    bars = fingering.get('bars', [])

    # SVG constants
    padding = 20
    string_spacing = (width - 2 * padding) / 5  # 5 spaces between 6 strings
    fret_spacing = (height - 2 * padding) / 4   # 4 spaces between 5 frets (we show 4 frets + nut)

    # Start building SVG
    svg_lines = [
        f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">',
        f'<rect width="100%" height="100%" fill="white"/>',
    ]

    # Draw nut (thick line at top)
    nut_y = padding
    svg_lines.append(
        f'<line x1="{padding}" y1="{nut_y}" x2="{width - padding}" y2="{nut_y}" '
        f'stroke="black" stroke-width="3"/>'
    )

    # Draw strings
    for string_index in range(6):
        x = padding + string_index * string_spacing
        svg_lines.append(
            f'<line x1="{x}" y1="{nut_y}" x2="{x}" y2="{height - padding}" '
            f'stroke="black" stroke-width="1"/>'
        )

    # Draw frets (we'll show 4 frets)
    for fret_num in range(1, 5):  # Frets 1, 2, 3, 4
        y = padding + fret_num * fret_spacing
        svg_lines.append(
            f'<line x1="{padding}" y1="{y}" x2="{width - padding}" y2="{y}" '
            f'stroke="black" stroke-width="1"/>'
        )

    # Draw fret numbers (for frets 2, 3, 4 if applicable)
    # Actually, we'll show the fret number to the left of the diagram if starting above fret 1
    # For simplicity, we'll assume we're showing frets 1-4 and label accordingly

    # Place finger dots
    finger_labels = {1: '1', 2: '2', 3: '3', 4: '4'}  # Simplified fingering
    # In a real implementation, we'd calculate proper fingering

    for string_index, fret in enumerate(frets):
        if fret is None:
            # Muted string - show 'x' above nut
            x = padding + string_index * string_spacing
            y = nut_y - 10  # Above nut
            svg_lines.append(
                f'<text x="{x}" y="{y}" text-anchor="middle" '
                f'font-family="Arial" font-size="14" fill="black">x</text>'
            )
        elif fret == 0:
            # Open string - show 'o' above nut
            x = padding + string_index * string_spacing
            y = nut_y - 10  # Above nut
            svg_lines.append(
                f'<text x="{x}" y="{y}" text-anchor="middle" '
                f'font-family="Arial" font-size="14" fill="black">o</text>'
            )
        else:
            # Fretted note
            x = padding + string_index * string_spacing
            y = padding + fret * fret_spacing

            # Check if this note is part of a barre
            is_barre = False
            for bar in bars:
                if (bar['start_string'] <= string_index <= bar['end_string'] and
                    bar['fret'] == fret):
                    is_barre = True
                    break

            # Draw circle for fretted note
            radius = min(string_spacing, fret_spacing) * 0.3
            svg_lines.append(
                f'<circle cx="{x}" cy="{y}" r="{radius}" fill="black"/>'
            )

            # Add finger number (simplified - just use fret number for demo)
            # In reality, we'd compute proper fingering
            finger_num = min(fret, 4)  # Cap at 4 for simplicity
            if finger_label := finger_labels.get(finger_num):
                svg_lines.append(
                    f'<text x="{x}" y="{y + 4}" text-anchor="middle" '
                    f'font-family="Arial" font-size="{radius*2}" fill="white">'
                    f'{finger_label}</text>'
                )

    # Draw barre lines
    for bar in bars:
        start_x = padding + bar['start_string'] * string_spacing
        end_x = padding + bar['end_string'] * string_spacing
        y = padding + bar['fret'] * fret_spacing
        svg_lines.append(
            f'<line x1="{start_x}" y1="{y}" x2="{end_x}" y2="{y}" '
            f'stroke="black" stroke-width="2"/>'
        )

    # Add chord symbol label at top
    svg_lines.append(
        f'<text x="{width/2}" y="{padding - 10}" text-anchor="middle" '
        f'font-family="Arial" font-size="18" font-weight="black" fill="black">'
        f'{chord_symbol}</text>'
    )

    svg_lines.append('</svg>')

    return '\n'.join(svg_lines)


def chord_chord_to_chart(chord_data_json: str) -> List[Dict[str, Any]]:
    """
    Convert chord detection JSON to a list of chord charts.

    Args:
        chord_data_json: JSON string from audio.detect_chords output

    Returns:
        List of chord chart dictionaries, each containing:
        - chord_symbol: The chord symbol (e.g., "C:maj")
        - onset: Start time in seconds
        - offset: End time in seconds
        - confidence: Confidence score
        - svg: SVG string of the chord diagram
        - fingering: The fingering used to generate the chart
    """
    try:
        chord_data = json.loads(chord_data_json)
    except json.JSONDecodeError:
        return []

    if "chords" not in chord_data:
        return []

    charts = []

    for chord_info in chord_data["chords"]:
        chord_symbol = chord_info.get("chord", "N")
        onset = chord_info.get("onset", 0)
        offset = chord_info.get("offset", 0)
        confidence = chord_info.get("confidence", 0)

        if chord_symbol == "N":
            # Skip "no chord" entries
            continue

        # Parse chord symbol
        root, chord_type = parse_chord_symbol(chord_symbol)
        if root is None:
            # Couldn't parse, skip
            continue

        # Find possible fingerings
        fingerings = find_chord_positions(root, chord_type)
        if not fingerings:
            # No fingerings found, skip
            continue

        # Use the best fingering (first in the list)
        best_fingering = fingerings[0]

        # Generate SVG
        svg = generate_chord_chart_svg(best_fingering, chord_symbol)

        charts.append({
            "chord_symbol": chord_symbol,
            "onset": onset,
            "offset": offset,
            "confidence": confidence,
            "svg": svg,
            "fingering": best_fingering
        })

    return charts


def chord_data_to_chord_chart_json(chord_data_json: str) -> str:
    """
    Convert chord detection JSON to a JSON string containing chord chart data.

    Args:
        chord_data_json: JSON string from audio.detect_chords output

    Returns:
        JSON string containing chord chart data for storage in database
    """
    # Generate chord charts
    charts = chord_chord_to_chart(chord_data_json)

    if not charts:
        # Return empty array as JSON
        return json.dumps([])

    # Convert to format suitable for storage
    # We'll store a list of chart objects, each containing:
    # - chord_symbol, onset, offset, confidence
    # - svg: the SVG string
    # Note: We're not storing the full fingering data to keep it simple
    chart_data = []
    for chart in charts:
        chart_data.append({
            "chord_symbol": chart["chord_symbol"],
            "onset": chart["onset"],
            "offset": chart["offset"],
            "confidence": chart["confidence"],
            "svg": chart["svg"]
        })

    return json.dumps(chart_data)