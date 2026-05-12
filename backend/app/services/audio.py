import librosa
import numpy as np
import soundfile as sf
from pathlib import Path
import subprocess
import tempfile
import os
import json

def preprocess_audio(input_file_path: str, output_file_path: str = None, target_sr: int = 22050) -> str:
    """
    Preprocess audio file: load, normalize (peak normalization), and resample.

    Args:
        input_file_path: Path to the input audio file.
        output_file_path: Path to save the preprocessed audio. If None,
                          we will create a new filename by appending '_preprocessed' to the input file stem.
        target_sr: Target sample rate (default: 22050 Hz).

    Returns:
        Path to the preprocessed audio file.
    """
    input_path = Path(input_file_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input audio file not found: {input_file_path}")

    # Determine output file path
    if output_file_path is None:
        output_file_path = str(input_path.parent / f"{input_path.stem}_preprocessed{input_path.suffix}")
    output_path = Path(output_file_path)

    # Load the audio file
    try:
        audio, sr = librosa.load(input_path, sr=None)  # Load with original sample rate
    except Exception as e:
        raise RuntimeError(f"Failed to load audio file: {str(e)}")

    # Normalize: peak normalization to 0 dB (i.e., scale so that the maximum absolute value is 1.0)
    if np.max(np.abs(audio)) > 0:
        audio = audio / np.max(np.abs(audio))

    # Resample if necessary
    if sr != target_sr:
        try:
            audio = librosa.resample(audio, orig_sr=sr, target_sr=target_sr)
        except Exception as e:
            raise RuntimeError(f"Failed to resample audio: {str(e)}")

    # Save the preprocessed audio
    try:
        sf.write(output_path, audio, target_sr)
    except Exception as e:
        raise RuntimeError(f"Failed to save preprocessed audio: {str(e)}")

    return str(output_path)


def separate_sources(input_file_path: str, output_dir: str = None) -> str:
    """
    Separate audio sources using Demucs and return the path to the guitar stem.

    Args:
        input_file_path: Path to the input audio file.
        output_dir: Directory to save the separated stems. If None,
                   we will create a temporary directory.

    Returns:
        Path to the separated guitar stem file.
    """
    input_path = Path(input_file_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input audio file not found: {input_file_path}")

    # Determine output directory
    if output_dir is None:
        output_dir = tempfile.mkdtemp()
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        # Run Demucs to separate sources
        # Using the pretrained model 'htdemucs' which is good for music separation
        cmd = [
            "python", "-m", "demucs.separate",
            "-n", "htdemucs",  # Model name
            "--two-stems", "vocals",  # Separate vocals and accompaniment (we'll extract guitar from accompaniment)
            "-o", str(output_path),
            str(input_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"Demucs separation failed: {result.stderr}")

        # Demucs creates output in: output_dir/model_name/input_filename_without_extension/
        # For htdemucs model with two-stems vocals, we get:
        # {output_dir}/htdemucs/{input_filename_without_extension}/
        # containing vocals.wav and accompaniment.wav

        input_stem = input_path.stem
        accompaniment_path = output_path / "htdemucs" / input_stem / "accompaniment.wav"

        if not accompaniment_path.exists():
            # Fallback: try to find any accompaniment file
            accompaniment_files = list(output_path.rglob("*accompaniment*.wav"))
            if not accompaniment_files:
                raise FileNotFoundError("Could not find accompaniment stem after Demucs separation")
            accompaniment_path = accompaniment_files[0]

        # For better guitar isolation, we could further process the accompaniment,
        # but for now we'll return the accompaniment as our guitar-containing stem
        # In a more advanced implementation, we could use additional techniques
        # to isolate guitar from other accompaniment instruments

        return str(accompaniment_path)

    except Exception as e:
        raise RuntimeError(f"Failed to separate audio sources: {str(e)}")


def detect_pitch(input_file_path: str, output_dir: str = None) -> dict:
    """
    Detect pitch (notes) from audio using Spotify Basic Pitch.

    Args:
        input_file_path: Path to the input audio file.
        output_dir: Directory to save the Basic Pitch output. If None,
                   we will create a temporary directory.

    Returns:
        Dictionary containing note data with onset, offset, pitch, velocity, and confidence.
    """
    input_path = Path(input_file_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input audio file not found: {input_file_path}")

    # Determine output directory
    if output_dir is None:
        output_dir = tempfile.mkdtemp()
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        # Run Basic Pitch to detect pitches
        # Using basic-pitch command line interface
        cmd = [
            "basic-pitch",
            input_file_path,
            str(output_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            # If basic-pitch is not available or fails, we'll raise an error
            # In a production environment, we might want to fall back to another method
            raise RuntimeError(f"Basic Pitch failed: {result.stderr}")

        # Basic Pitch outputs a MIDI file and a JSON file
        # Look for the JSON output which contains the note data
        input_stem = input_path.stem
        json_path = output_path / f"{input_stem}_basic_pitch_output.json"

        # If the exact filename pattern doesn't match, look for any JSON file
        if not json_path.exists():
            json_files = list(output_path.glob("*.json"))
            if not json_files:
                raise FileNotFoundError("Could not find Basic Pitch JSON output")
            json_path = json_files[0]

        # Load the JSON data
        with open(json_path, 'r') as f:
            pitch_data = json.load(f)

        # Basic Pitch output format typically includes:
        # {
        #   "notes": [
        #     {
        #       "onset": float,  # onset time in seconds
        #       "offset": float, # offset time in seconds
        #       "pitch": int,    # MIDI pitch number (0-127)
        #       "velocity": int  # MIDI velocity (0-127)
        #       # Confidence might be in a separate field or derived
        #     }
        #   ],
        #   "model_outputs": {...}  # Additional model outputs
        # }

        # Extract and format note data for storage
        formatted_notes = []
        if "notes" in pitch_data:
            for note in pitch_data["notes"]:
                formatted_note = {
                    "onset": round(note.get("onset", 0), 3),
                    "offset": round(note.get("offset", 0), 3),
                    "pitch": note.get("pitch", 0),
                    "velocity": note.get("velocity", 64),
                    "confidence": round(note.get("confidence", 0.8), 3)  # Default confidence if not provided
                }
                formatted_notes.append(formatted_note)

        return {
            "notes": formatted_notes,
            "model_outputs": pitch_data.get("model_outputs", {}),
            "total_notes_detected": len(formatted_notes)
        }

    except Exception as e:
        raise RuntimeError(f"Failed to detect pitch: {str(e)}")


def detect_beat_and_tempo(input_file_path: str) -> dict:
    """
    Detect beat and tempo from audio using librosa.beat.

    Args:
        input_file_path: Path to the input audio file.

    Returns:
        Dictionary containing tempo (BPM) and beat frames/times.
    """
    input_path = Path(input_file_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input audio file not found: {input_file_path}")

    try:
        # Load the audio file
        y, sr = librosa.load(input_path, sr=None)

        # Detect tempo and beat frames
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)

        # Convert beat frames to time
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)

        # Return tempo and beat information
        return {
            "tempo": float(tempo),  # Tempo in BPM
            "beat_frames": beat_frames.tolist(),  # Beat frame indices
            "beat_times": beat_times.tolist(),    # Beat times in seconds
            "beat_count": len(beat_frames)
        }

    except Exception as e:
        raise RuntimeError(f"Failed to detect beat and tempo: {str(e)}")


def detect_key(input_file_path: str) -> dict:
    """
    Detect musical key from audio using librosa chroma features.

    Args:
        input_file_path: Path to the input audio file.

    Returns:
        Dictionary containing key information (key name, scale, strength).
    """
    input_path = Path(input_file_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input audio file not found: {input_file_path}")

    try:
        # Load the audio file
        y, sr = librosa.load(input_path, sr=None)

        # Extract chroma features
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)

        # Average chroma across time to get overall chroma profile
        chroma_mean = np.mean(chroma, axis=1)

        # Define key names (C, C#, D, D#, E, F, F#, G, G#, A, A#, B)
        key_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

        # Define major and minor key templates (Krumhansl-Schmuckler key-finding algorithm)
        # Major key template: [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
        # Minor key template: [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
        major_template = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
        minor_template = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

        # Normalize the templates
        major_template = major_template / np.linalg.norm(major_template)
        minor_template = minor_template / np.linalg.norm(minor_template)

        # Normalize the chroma vector
        chroma_norm = chroma_mean / np.linalg.norm(chroma_mean)

        # Compute correlations with all key templates
        major_correlations = []
        minor_correlations = []

        for i in range(12):
            # Rotate templates for each key
            major_rotated = np.roll(major_template, i)
            minor_rotated = np.roll(minor_template, i)

            # Calculate correlation
            major_corr = np.dot(chroma_norm, major_rotated)
            minor_corr = np.dot(chroma_norm, minor_rotated)

            major_correlations.append(major_corr)
            minor_correlations.append(minor_corr)

        # Find the best matching key
        major_best_idx = np.argmax(major_correlations)
        minor_best_idx = np.argmax(minor_correlations)

        major_best_corr = major_correlations[major_best_idx]
        minor_best_corr = minor_correlations[minor_best_idx]

        # Determine if it's major or minor based on higher correlation
        if major_best_corr >= minor_best_corr:
            key_name = key_names[major_best_idx]
            scale = "major"
            strength = float(major_best_corr)
        else:
            key_name = key_names[minor_best_idx]
            scale = "minor"
            strength = float(minor_best_corr)

        # Format key as "C major", "A minor", etc.
        key_string = f"{key_name} {scale}"

        return {
            "key": key_string,
            "key_name": key_name,
            "scale": scale,
            "strength": strength,
            "all_major_correlations": {key_names[i]: float(major_correlations[i]) for i in range(12)},
            "all_minor_correlations": {key_names[i]: float(minor_correlations[i]) for i in range(12)}
        }

    except Exception as e:
        raise RuntimeError(f"Failed to detect key: {str(e)}")


def detect_rhythm(input_file_path: str) -> dict:
    """
    Detect rhythm information (onsets, duration estimates) from audio using librosa.

    Args:
        input_file_path: Path to the input audio file.

    Returns:
        Dictionary containing onset times, duration estimates, and rhythm parameters.
    """
    input_path = Path(input_file_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input audio file not found: {input_file_path}")

    try:
        # Load the audio file
        y, sr = librosa.load(input_path, sr=None)

        # Detect onsets using multiple methods for robustness
        onset_frames = librosa.onset.onset_detect(
            y=y,
            sr=sr,
            hop_length=512,
            units='frames'
        )

        # Convert onset frames to time
        onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=512)

        # Estimate note durations based on onset intervals
        # For each onset, estimate duration as time to next onset (or end of file)
        durations = []
        if len(onset_times) > 0:
            # Get total duration of audio
            total_duration = librosa.get_duration(y=y, sr=sr)

            for i, onset_time in enumerate(onset_times):
                if i < len(onset_times) - 1:
                    # Duration to next onset
                    duration = onset_times[i + 1] - onset_time
                else:
                    # Duration to end of file
                    duration = total_duration - onset_time
                durations.append(max(duration, 0.01))  # Ensure minimum duration

        # Calculate additional rhythm features
        # Tempo from onset intervals (if we have enough onsets)
        onset_tempo = None
        if len(onset_times) > 1:
            onset_intervals = np.diff(onset_times)
            if len(onset_intervals) > 0:
                median_interval = np.median(onset_intervals)
                if median_interval > 0:
                    onset_tempo = 60.0 / median_interval  # BPM

        return {
            "onset_times": onset_times.tolist(),
            "onset_frames": onset_frames.tolist(),
            "note_durations": durations,
            "onset_count": len(onset_times),
            "onset_tempo_bpm": float(onset_tempo) if onset_tempo is not None else None,
            "total_duration": float(librosa.get_duration(y=y, sr=sr)),
            "sample_rate": int(sr)
        }

    except Exception as e:
        raise RuntimeError(f"Failed to detect rhythm: {str(e)}")


def detect_chords(input_file_path: str) -> dict:
    """
    Detect chords from audio using librosa chroma features and template matching.

    Args:
        input_file_path: Path to the input audio file.

    Returns:
        Dictionary containing chord sequence with timestamps.
    """
    input_path = Path(input_file_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input audio file not found: {input_file_path}")

    try:
        # Load the audio file
        y, sr = librosa.load(input_path, sr=None)

        # Compute chroma features using constant-Q transform
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)

        # Get the times for each chroma frame
        times = librosa.frames_to_time(np.arange(chroma.shape[1]), sr=sr)

        # Define chord templates for major, minor, and dominant seventh chords
        # We'll use the chroma vector representation for each chord
        # Major chord: [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0] (root, major third, perfect fifth)
        # Minor chord: [1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0] (root, minor third, perfect fifth)
        # Dominant seventh: [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1] (root, major third, perfect fifth, minor seventh)

        # We'll create templates for all 12 roots for each chord type
        chord_templates = {}
        chord_names = []

        # Major chords
        major_template = np.array([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0])
        for i in range(12):
            rotated = np.roll(major_template, i)
            chord_templates[f"{['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'][i]}:maj"] = rotated
            chord_names.append(f"{['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'][i]}:maj")

        # Minor chords
        minor_template = np.array([1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0])
        for i in range(12):
            rotated = np.roll(minor_template, i)
            chord_templates[f"{['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'][i]}:min"] = rotated
            chord_names.append(f"{['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'][i]}:min")

        # Dominant seventh chords
        dom7_template = np.array([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1])
        for i in range(12):
            rotated = np.roll(dom7_template, i)
            chord_templates[f"{['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'][i]}:7"] = rotated
            chord_names.append(f"{['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'][i]}:7")

        # Normalize the templates
        for key in chord_templates:
            chord_templates[key] = chord_templates[key] / np.linalg.norm(chord_templates[key])

        # For each time frame, compute the similarity to each chord template
        chord_probs = np.zeros((chroma.shape[1], len(chord_names)))
        for i, (chord_name, template) in enumerate(chord_templates.items()):
            # Compute cosine similarity between chroma vector and template for each frame
            # We'll normalize the chroma frame to unit vector for cosine similarity
            chroma_norm = chroma[:, i] / np.linalg.norm(chroma[:, i]) if np.linalg.norm(chroma[:, i]) > 0 else chroma[:, i]
            chord_probs[:, i] = np.dot(chroma_norm, template)

        # For each frame, pick the chord with the highest similarity (if above a threshold)
        # We'll set a threshold of 0.3 (can be adjusted)
        threshold = 0.3
        chord_indices = np.argmax(chord_probs, axis=1)
        chord_max_values = np.max(chord_probs, axis=1)

        # Set to -1 (no chord) if below threshold
        chord_indices[chord_max_values < threshold] = -1

        # Map indices to chord names
        chord_seq = [chord_names[idx] if idx != -1 else "N" for idx in chord_indices]

        # Now we can convert the chord sequence to a list of chords with onset and offset times
        # We'll group consecutive frames with the same chord
        chords = []
        if len(chord_seq) > 0:
            current_chord = chord_seq[0]
            start_time = times[0]
            for i in range(1, len(chord_seq)):
                if chord_seq[i] != current_chord:
                    # End of current chord segment
                    end_time = times[i]
                    chords.append({
                        "chord": current_chord,
                        "onset": round(start_time, 3),
                        "offset": round(end_time, 3),
                        "confidence": round(float(np.mean(chord_max_values[start_i:i])), 3) if 'start_i' in locals() else 0.5
                    })
                    current_chord = chord_seq[i]
                    start_time = times[i]
                    start_i = i
            # Add the last chord
            end_time = times[-1]
            chords.append({
                "chord": current_chord,
                "onset": round(start_time, 3),
                "offset": round(end_time, 3),
                "confidence": round(float(np.mean(chord_max_values[start_i:])), 3) if 'start_i' in locals() else 0.5
            })

        return {
            "chords": chords,
            "chord_sequence": chord_seq,
            "times": times.tolist(),
            "total_chords_detected": len(chords)
        }

    except Exception as e:
        raise RuntimeError(f"Failed to detect chords: {str(e)}")