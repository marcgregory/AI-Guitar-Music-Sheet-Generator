import librosa
import numpy as np
import soundfile as sf
from pathlib import Path
import importlib.util
import os
import subprocess
import tempfile
import sys
import json
import csv
import shutil

from app.core.config import settings
from app.services import storage

DEMUCS_GUITAR_MODEL = settings.DEMUCS_GUITAR_MODEL
DEMUCS_FALLBACK_MODEL = settings.DEMUCS_FALLBACK_MODEL
DEMUCS_CMD_TIMEOUT_SECONDS = settings.DEMUCS_CMD_TIMEOUT_SECONDS
DEMUCS_MULTI_STEMS = {
    "bass": "bass",
    "drums": "drums",
    "vocals": "vocals",
    "other": "other",
}
DEMUCS_VENDOR_PATH = Path(os.environ.get("DEMUCS_VENDOR_PATH", r"C:\tmp\demucs_py313"))


def _configure_demucs_vendor_path() -> None:
    if DEMUCS_VENDOR_PATH.exists():
        vendor_path = str(DEMUCS_VENDOR_PATH)
        if vendor_path not in sys.path:
            sys.path.append(vendor_path)


def _ensure_demucs_available() -> None:
    _configure_demucs_vendor_path()
    if importlib.util.find_spec("demucs") is None:
        raise RuntimeError(
            "Demucs is not installed. Install backend requirements to enable source separation."
        )


def _run_demucs(input_path: Path, output_path: Path, model_name: str, two_stems: str = None) -> None:
    _configure_demucs_vendor_path()
    cmd = [
        sys.executable,
        "-m",
        "demucs.separate",
        "-n",
        model_name,
        "-o",
        str(output_path),
    ]
    if two_stems:
        cmd.extend(["--two-stems", two_stems])
    cmd.append(str(input_path))

    env = os.environ.copy()
    if DEMUCS_VENDOR_PATH.exists():
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            f"{DEMUCS_VENDOR_PATH}{os.pathsep}{existing_pythonpath}"
            if existing_pythonpath
            else str(DEMUCS_VENDOR_PATH)
        )

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=DEMUCS_CMD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as timeout_error:
        raise RuntimeError(
            f"Demucs separation timed out after {DEMUCS_CMD_TIMEOUT_SECONDS} seconds "
            f"for model {model_name}"
        ) from timeout_error

    if result.returncode != 0:
        error_text = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Demucs separation failed with {model_name}: {error_text}")


def _find_demucs_stem(output_path: Path, model_name: str, input_stem: str, stem_name: str) -> Path:
    expected_path = output_path / model_name / input_stem / f"{stem_name}.wav"
    if expected_path.exists():
        return expected_path

    matches = list((output_path / model_name).rglob(f"{stem_name}.wav"))
    if matches:
        return matches[0]

    all_matches = list(output_path.rglob(f"{stem_name}.wav"))
    if all_matches:
        return all_matches[0]

    raise FileNotFoundError(f"Could not find {stem_name} stem after Demucs separation")


def _maybe_find_demucs_stem(output_path: Path, model_name: str, input_stem: str, stem_name: str) -> Path | None:
    try:
        return _find_demucs_stem(output_path, model_name, input_stem, stem_name)
    except FileNotFoundError:
        return None

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
    input_path = Path(storage.normalize_local_path(input_file_path))
    if not input_path.exists():
        raise FileNotFoundError(f"Input audio file not found: {input_file_path}")

    # Determine output file path
    if output_file_path is None:
        output_file_path = str(input_path.parent / f"{input_path.stem}_preprocessed{input_path.suffix}")
    output_path = Path(storage.normalize_local_path(output_file_path))

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

    return output_path.as_posix()


def separate_sources_multi(input_file_path: str, output_dir: str = None) -> dict[str, str]:
    """
    Separate audio sources using Demucs and return available instrument stems.

    The primary path uses Demucs' configured model. If that model is unavailable at
    runtime, the fallback uses the standard vocals/accompaniment split and maps
    accompaniment to the app's broad "other" instrument track.

    Args:
        input_file_path: Path to the input audio file.
        output_dir: Directory to save the separated stems. If None,
                   we will create a temporary directory.

    Returns:
        Dictionary mapping instrument type to separated stem path.
    """
    input_path = Path(storage.normalize_local_path(input_file_path))
    if not input_path.exists():
        raise FileNotFoundError(f"Input audio file not found: {input_file_path}")

    # Determine output directory
    if output_dir is None:
        output_dir = tempfile.mkdtemp()
    output_path = Path(storage.normalize_local_path(output_dir))
    output_path.mkdir(parents=True, exist_ok=True)

    _ensure_demucs_available()

    primary_error = None
    try:
        input_stem = input_path.stem
        try:
            _run_demucs(input_path, output_path, DEMUCS_GUITAR_MODEL)
            stems = {}
            for instrument_type, stem_name in DEMUCS_MULTI_STEMS.items():
                stem_path = _maybe_find_demucs_stem(
                    output_path,
                    DEMUCS_GUITAR_MODEL,
                    input_stem,
                    stem_name,
                )
                if stem_path:
                    stems[instrument_type] = storage.normalize_local_path(stem_path)

            if stems:
                return stems

            raise FileNotFoundError("No stems found after Demucs 6-stem separation")
        except Exception as e:
            primary_error = e

        _run_demucs(input_path, output_path, DEMUCS_FALLBACK_MODEL, two_stems="vocals")
        fallback_stems = {}
        vocals_path = _maybe_find_demucs_stem(output_path, DEMUCS_FALLBACK_MODEL, input_stem, "vocals")
        accompaniment_path = _maybe_find_demucs_stem(
            output_path,
            DEMUCS_FALLBACK_MODEL,
            input_stem,
            "accompaniment",
        )
        if vocals_path:
            fallback_stems["vocals"] = storage.normalize_local_path(vocals_path)
        if accompaniment_path:
            fallback_stems["other"] = storage.normalize_local_path(accompaniment_path)
        if fallback_stems:
            return fallback_stems
        raise FileNotFoundError("No stems found after Demucs fallback separation")

    except Exception as e:
        if primary_error:
            raise RuntimeError(
                "Failed to separate audio sources. "
                f"Primary guitar model error: {str(primary_error)}. "
                f"Fallback error: {str(e)}"
            )
        raise RuntimeError(f"Failed to separate audio sources: {str(e)}")


def separate_selected_stem(
    input_file_path: str,
    selected_stem: str,
    output_dir: str = None,
) -> str:
    """
    Separate one Demucs MVP stem and return only that stem path.

    Demucs may write temporary files for all default stems while separating, but
    callers should persist only the requested output. This keeps the Railway MVP
    storage and transcription cost focused on one selected target per job.
    """
    if selected_stem not in DEMUCS_MULTI_STEMS:
        raise ValueError(
            f"selected_stem must be one of: {', '.join(sorted(DEMUCS_MULTI_STEMS))}"
        )

    stems = separate_sources_multi(input_file_path, output_dir)
    stem_path = stems.get(selected_stem)
    if stem_path:
        return stem_path

    raise FileNotFoundError(
        f"Demucs did not produce the selected '{selected_stem}' stem for this audio."
    )


def separate_sources(input_file_path: str, output_dir: str = None) -> str:
    """
    Separate audio sources using Demucs and return the preferred analysis stem.

    Compatibility wrapper for the original single-stem pipeline. Guitar is
    preferred, then other/accompaniment, then any available separated stem.
    """
    stems = separate_sources_multi(input_file_path, output_dir)
    for preferred_stem in ("other", "bass", "vocals", "drums"):
        if preferred_stem in stems:
            return stems[preferred_stem]
    raise RuntimeError("Source separation completed without usable stems")


def detect_pitch(input_file_path: str, output_dir: str = None) -> dict:
    """
    Detect pitch (notes) from audio using Spotify Basic Pitch with CREPE as fallback.

    Args:
        input_file_path: Path to the input audio file.
        output_dir: Directory to save the output. If None,
                   we will create a temporary directory.

    Returns:
        Dictionary containing note data with onset, offset, pitch, velocity, and confidence.
    """
    input_path = Path(storage.normalize_local_path(input_file_path))
    if not input_path.exists():
        raise FileNotFoundError(f"Input audio file not found: {input_file_path}")

    # Determine output directory
    if output_dir is None:
        output_dir = tempfile.mkdtemp()
    output_path = Path(storage.normalize_local_path(output_dir))
    output_path.mkdir(parents=True, exist_ok=True)

    # First, try Basic Pitch
    try:
        basic_pitch_api_error = None
        try:
            from basic_pitch.inference import predict

            model_output, _midi_data, note_events = predict(str(input_path))
            formatted_notes = _format_basic_pitch_note_events(note_events)
            return {
                "notes": formatted_notes,
                "model_outputs": {},
                "total_notes_detected": len(formatted_notes)
            }
        except Exception as api_e:
            # Fall back to the CLI before trying CREPE. Some local installs expose
            # only the executable, while others expose the Python API.
            basic_pitch_api_error = api_e

        basic_pitch_executable = shutil.which("basic-pitch")
        if not basic_pitch_executable:
            raise RuntimeError(
                "Basic Pitch Python API failed and the basic-pitch CLI was not found on PATH. "
                f"Python API error: {basic_pitch_api_error}"
            )

        # Run Basic Pitch to detect pitches
        # Using basic-pitch command line interface
        cmd = [
            basic_pitch_executable,
            str(output_path),
            input_file_path,
            "--save-note-events"
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            note_event_files = list(output_path.glob("*_basic_pitch.csv"))
            if not note_event_files:
                note_event_files = list(output_path.glob("*.csv"))
            if not note_event_files:
                raise FileNotFoundError("Could not find Basic Pitch note-event CSV output")

            formatted_notes = _load_basic_pitch_note_events_csv(note_event_files[0])

            return {
                "notes": formatted_notes,
                "model_outputs": {},
                "total_notes_detected": len(formatted_notes)
            }
        else:
            # Basic Pitch failed, fall back to CREPE
            raise RuntimeError(f"Basic Pitch failed: {result.stderr}")
    except Exception as e:
        # If Basic Pitch fails, try CREPE
        try:
            return _detect_pitch_crepe(input_file_path, output_dir)
        except Exception as crepe_e:
            try:
                return _detect_pitch_librosa(input_file_path)
            except Exception as librosa_e:
                # If all pitch backends fail, raise an error
                raise RuntimeError(
                    "Failed to detect pitch with Basic Pitch, CREPE, and librosa pYIN. "
                    f"Basic Pitch error: {str(e)}. "
                    f"CREPE error: {str(crepe_e)}. "
                    f"librosa error: {str(librosa_e)}"
                )


def _format_basic_pitch_note_events(note_events) -> list:
    formatted_notes = []
    for event in note_events:
        if len(event) < 4:
            continue
        onset, offset, pitch, amplitude = event[:4]
        confidence = float(amplitude or 0)
        formatted_notes.append({
            "onset": round(float(onset), 3),
            "offset": round(float(offset), 3),
            "pitch": int(pitch),
            "velocity": max(1, min(127, int(round(confidence * 127)))),
            "confidence": round(confidence, 3)
        })
    return formatted_notes


def _load_basic_pitch_note_events_csv(csv_path: Path) -> list:
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        events = []
        for row in reader:
            onset = row.get("start_time_s") or row.get("onset") or row.get("start_time")
            offset = row.get("end_time_s") or row.get("offset") or row.get("end_time")
            pitch = row.get("pitch_midi") or row.get("pitch")
            amplitude = row.get("amplitude") or row.get("confidence") or 0.8
            if onset is None or offset is None or pitch is None:
                continue
            events.append((float(onset), float(offset), int(float(pitch)), float(amplitude)))

    return _format_basic_pitch_note_events(events)


def _detect_pitch_crepe(input_file_path: str, output_dir: str = None) -> dict:
    """
    Detect pitch (notes) from audio using CREPE as a fallback.

    Args:
        input_file_path: Path to the input audio file.
        output_dir: Directory to save the CREPE output. If None,
                   we will create a temporary directory.

    Returns:
        Dictionary containing note data with onset, offset, pitch, velocity, and confidence.
    """
    input_path = Path(storage.normalize_local_path(input_file_path))
    if not input_path.exists():
        raise FileNotFoundError(f"Input audio file not found: {input_file_path}")

    # Determine output directory
    if output_dir is None:
        output_dir = tempfile.mkdtemp()
    output_path = Path(storage.normalize_local_path(output_dir))
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        # Run CREPE to detect pitches
        # Using CREPE command line interface (if available) or Python API
        # We'll use the Python API for more control
        import crepe
        import numpy as np
        from scipy.signal import medfilt
        from scipy.interpolate import interp1d

        # Load the audio file
        sr = 16000  # CREPE expects 16kHz audio
        audio, _ = librosa.load(input_path, sr=sr, mono=True)

        # Run CREPE
        time, frequency, confidence, activation = crepe.predict(
            audio, sr, viterbi=True, step_size=10
        )

        # Filter out low-confidence predictions
        # We'll use a confidence threshold of 0.5
        confidence_threshold = 0.5
        valid = confidence > confidence_threshold
        time = time[valid]
        frequency = frequency[valid]
        confidence = confidence[valid]

        # Convert frequency to MIDI note number
        # MIDI note = 69 + 12 * log2(frequency / 440)
        midi_notes = 69 + 12 * np.log2(frequency / 440.0)
        # Round to the nearest MIDI note
        midi_notes = np.round(midi_notes).astype(int)
        # Ensure MIDI notes are within valid range (0-127)
        midi_notes = np.clip(midi_notes, 0, 127)

        # Convert to note events (onset, offset, pitch, velocity)
        # We'll assume each detected pitch is a note with a fixed duration (e.g., 0.1 seconds)
        # or we can group consecutive same pitches.
        # For simplicity, we'll create a note for each time step with a small duration.
        # However, a better approach is to group consecutive same pitches.

        # Group consecutive same pitches
        if len(midi_notes) == 0:
            notes = []
        else:
            notes = []
            current_pitch = midi_notes[0]
            start_time = time[0]
            current_confidence = confidence[0]

            for i in range(1, len(midi_notes)):
                if midi_notes[i] != current_pitch or i == len(midi_notes) - 1:
                    # End of current note
                    end_time = time[i]
                    # If this is the last element and it's the same pitch, we need to adjust
                    if i == len(midi_notes) - 1 and midi_notes[i] == current_pitch:
                        end_time = time[i] + (time[1] - time[0])  # Assume one more step
                    notes.append({
                        "onset": round(start_time, 3),
                        "offset": round(end_time, 3),
                        "pitch": int(current_pitch),
                        "velocity": 64,  # Default velocity
                        "confidence": round(float(np.mean(confidence[start_i:i])), 3) if 'start_i' in locals() else round(float(current_confidence), 3)
                    })
                    if i < len(midi_notes):
                        current_pitch = midi_notes[i]
                        start_time = time[i]
                        start_i = i
                        current_confidence = confidence[i]
                # else: continue the current note

            # Handle the last note if the loop ended without adding it
            if len(notes) == 0 or notes[-1]["offset"] != time[-1]:
                # Add the last note
                notes.append({
                    "onset": round(start_time, 3),
                    "offset": round(time[-1] + (time[1] - time[0]), 3),
                    "pitch": int(current_pitch),
                    "velocity": 64,
                    "confidence": round(float(np.mean(confidence[start_i:])), 3) if 'start_i' in locals() else round(float(current_confidence), 3)
                })

        return {
            "notes": notes,
            "model_outputs": {},  # CREPE doesn't provide the same model outputs as Basic Pitch
            "total_notes_detected": len(notes)
        }

    except Exception as e:
        raise RuntimeError(f"CREPE pitch detection failed: {str(e)}")


def _detect_pitch_librosa(input_file_path: str) -> dict:
    """
    Detect monophonic pitch using librosa pYIN as a dependency-light fallback.

    This is less accurate than Basic Pitch for polyphonic guitar, but it keeps
    local development usable on Python versions where TensorFlow-backed pitch
    detectors are unavailable.
    """
    input_path = Path(storage.normalize_local_path(input_file_path))
    y, sr = librosa.load(input_path, sr=22050, mono=True)
    if y.size == 0:
        raise RuntimeError("Audio file is empty")

    fmin = librosa.note_to_hz("E2")
    fmax = librosa.note_to_hz("E6")
    f0, voiced_flag, voiced_prob = librosa.pyin(
        y,
        fmin=fmin,
        fmax=fmax,
        sr=sr,
        frame_length=2048,
        hop_length=256,
    )

    times = librosa.frames_to_time(np.arange(len(f0)), sr=sr, hop_length=256)
    valid = voiced_flag & ~np.isnan(f0)
    if not np.any(valid):
        return {"notes": [], "model_outputs": {}, "total_notes_detected": 0}

    midi_notes = np.full(len(f0), -1, dtype=int)
    midi_notes[valid] = np.rint(librosa.hz_to_midi(f0[valid])).astype(int)
    midi_notes = np.clip(midi_notes, -1, 127)

    notes = []
    current_pitch = None
    start_index = None
    confidences = []

    def append_note(end_index: int) -> None:
        if current_pitch is None or start_index is None:
            return
        onset = float(times[start_index])
        offset = float(times[min(end_index, len(times) - 1)])
        if offset <= onset:
            offset = onset + 0.05
        confidence = float(np.mean(confidences)) if confidences else 0.5
        notes.append({
            "onset": round(onset, 3),
            "offset": round(offset, 3),
            "pitch": int(current_pitch),
            "velocity": max(1, min(127, int(round(confidence * 127)))),
            "confidence": round(confidence, 3),
        })

    for i, pitch in enumerate(midi_notes):
        if pitch < 0:
            append_note(i)
            current_pitch = None
            start_index = None
            confidences = []
            continue

        confidence = float(voiced_prob[i]) if not np.isnan(voiced_prob[i]) else 0.5
        if current_pitch is None:
            current_pitch = pitch
            start_index = i
            confidences = [confidence]
        elif pitch == current_pitch:
            confidences.append(confidence)
        else:
            append_note(i)
            current_pitch = pitch
            start_index = i
            confidences = [confidence]

    append_note(len(times) - 1)

    # Drop tiny fragments that are usually frame-level pitch noise.
    notes = [note for note in notes if note["offset"] - note["onset"] >= 0.04]

    return {
        "notes": notes,
        "model_outputs": {"backend": "librosa.pyin"},
        "total_notes_detected": len(notes),
    }


def detect_beat_and_tempo(input_file_path: str) -> dict:
    """
    Detect beat and tempo from audio using librosa.beat.

    Args:
        input_file_path: Path to the input audio file.

    Returns:
        Dictionary containing tempo (BPM), confidence, and beat frames/times.
    """
    input_path = Path(storage.normalize_local_path(input_file_path))
    if not input_path.exists():
        raise FileNotFoundError(f"Input audio file not found: {input_file_path}")

    try:
        # Load the audio file
        y, sr = librosa.load(input_path, sr=None)

        # Detect tempo and beat frames
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)

        # Convert beat frames to time
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)

        # Calculate tempo confidence based on consistency of beat intervals
        tempo_confidence = 0
        if len(beat_frames) > 1:
            # Calculate intervals between beats
            beat_intervals = np.diff(beat_frames)
            # Convert to time intervals
            time_intervals = np.diff(beat_times)
            if len(time_intervals) > 0:
                # Calculate coefficient of variation (std/mean) - lower is more consistent
                mean_interval = np.mean(time_intervals)
                if mean_interval > 0:
                    cv = np.std(time_intervals) / mean_interval
                    # Convert to confidence (0-100), where lower CV means higher confidence
                    tempo_confidence = max(0, min(100, (1 - cv) * 100))

        # Return tempo and beat information with confidence
        return {
            "tempo": float(tempo),  # Tempo in BPM
            "tempo_confidence": int(tempo_confidence),  # Confidence percentage (0-100)
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
        Dictionary containing key information (key name, scale, confidence).
    """
    input_path = Path(storage.normalize_local_path(input_file_path))
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
            confidence = float(major_best_corr)
        else:
            key_name = key_names[minor_best_idx]
            scale = "minor"
            confidence = float(minor_best_corr)

        # Format key as "C major", "A minor", etc.
        key_string = f"{key_name} {scale}"

        # Convert confidence to percentage (0-100)
        confidence_percent = int(confidence * 100)

        return {
            "key": key_string,
            "key_name": key_name,
            "scale": scale,
            "confidence": confidence_percent,
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
    input_path = Path(storage.normalize_local_path(input_file_path))
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


def analyze_drum_rhythm(input_file_path: str, grid_size: float = 0.125) -> dict:
    """
    Detect drum hit timing and intensity from a separated drum stem.

    This intentionally avoids kit-piece classification. The output is a compact
    rhythm-lane representation for playback-synced UI rendering.
    """
    input_path = Path(storage.normalize_local_path(input_file_path))
    if not input_path.exists():
        raise FileNotFoundError(f"Input audio file not found: {input_file_path}")

    try:
        y, sr = librosa.load(input_path, sr=None, mono=True)
        total_duration = float(librosa.get_duration(y=y, sr=sr))

        if y.size == 0 or total_duration <= 0 or float(np.max(np.abs(y))) <= 0:
            raise RuntimeError("Drum stem is empty or silent")

        hop_length = 512
        onset_envelope = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
        onset_frames = librosa.onset.onset_detect(
            onset_envelope=onset_envelope,
            sr=sr,
            hop_length=hop_length,
            units="frames",
            backtrack=False,
        )
        onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop_length)

        if len(onset_times) == 0:
            raise RuntimeError("No usable drum hits were detected")

        max_strength = float(np.max(onset_envelope)) if len(onset_envelope) > 0 else 0.0
        if max_strength <= 0:
            raise RuntimeError("No usable drum hits were detected")

        hits = []
        for index, onset_time in enumerate(onset_times):
            onset = float(onset_time)
            next_onset = (
                float(onset_times[index + 1])
                if index < len(onset_times) - 1
                else total_duration
            )
            frame = int(onset_frames[index])
            raw_strength = (
                float(onset_envelope[frame])
                if 0 <= frame < len(onset_envelope)
                else max_strength
            )
            intensity = max(0.0, min(1.0, raw_strength / max_strength))
            confidence = max(0.05, min(1.0, intensity))
            offset = min(total_duration, max(onset + 0.06, next_onset))

            hits.append({
                "onset": round(onset, 4),
                "offset": round(offset, 4),
                "intensity": round(intensity, 4),
                "confidence": round(confidence, 4),
            })

        return {
            "drum_hits": hits,
            "total_hits_detected": len(hits),
            "rhythm_analysis": {
                "total_duration": round(total_duration, 4),
                "grid_size": grid_size,
                "source": "drum_stem_onset_detection",
            },
        }

    except Exception as e:
        if isinstance(e, (FileNotFoundError, RuntimeError)):
            raise
        raise RuntimeError(f"Failed to analyze drum rhythm: {str(e)}")


def detect_chords(input_file_path: str) -> dict:
    """
    Detect chords from audio using librosa chroma features and template matching.

    Args:
        input_file_path: Path to the input audio file.

    Returns:
        Dictionary containing chord sequence with timestamps.
    """
    input_path = Path(storage.normalize_local_path(input_file_path))
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
        # Reshape chroma to (n_frames, 12) for easier computation
        chroma_frames = chroma.T  # Shape: (n_frames, 12)

        # Normalize each chroma frame to unit vector
        chroma_norms = np.linalg.norm(chroma_frames, axis=1, keepdims=True)
        # Avoid division by zero
        chroma_norms = np.where(chroma_norms == 0, 1, chroma_norms)
        chroma_frames_normalized = chroma_frames / chroma_norms  # Shape: (n_frames, 12)

        # Stack all chord templates into a matrix (12, n_templates)
        template_matrix = np.column_stack(list(chord_templates.values()))  # Shape: (12, n_templates)

        # Compute similarity: (n_frames, 12) @ (12, n_templates) = (n_frames, n_templates)
        chord_probs = chroma_frames_normalized @ template_matrix

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
            start_idx = 0  # Start index of the current chord segment
            for i in range(1, len(chord_seq)):
                if chord_seq[i] != current_chord:
                    # End of current chord segment
                    end_time = times[i]
                    # Calculate average confidence for this segment
                    segment_confidence = np.mean(chord_max_values[start_idx:i])
                    chords.append({
                        "chord": current_chord,
                        "onset": round(start_time, 3),
                        "offset": round(end_time, 3),
                        "confidence": round(float(segment_confidence), 3)
                    })
                    current_chord = chord_seq[i]
                    start_time = times[i]
                    start_idx = i
            # Add the last chord
            end_time = times[-1]
            # Calculate average confidence for the last segment
            segment_confidence = np.mean(chord_max_values[start_idx:])
            chords.append({
                "chord": current_chord,
                "onset": round(start_time, 3),
                "offset": round(end_time, 3),
                "confidence": round(float(segment_confidence), 3)
            })

        return {
            "chords": chords,
            "chord_sequence": chord_seq,
            "times": times.tolist(),
            "total_chords_detected": len(chords)
        }

    except Exception as e:
        raise RuntimeError(f"Failed to detect chords: {str(e)}")
