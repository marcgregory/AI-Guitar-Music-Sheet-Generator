import os
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import modal


app = modal.App("musicstudio")
logger = logging.getLogger(__name__)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install(
    "numpy==1.26.4",
    )
    .pip_install(
    "torch==2.2.2",
    "torchaudio==2.2.2",
    )
    .pip_install(
    "demucs==4.0.1",
    "librosa==0.10.1",
    "basic-pitch==0.4.0",
    "mido==1.2.0",
    "music21==9.9.2",
    "fastapi[standard]==0.115.6",
    "cloudinary==1.44.1",
    "requests==2.32.3",
    )
)

secrets = [
    modal.Secret.from_name("cloudinary"),
    modal.Secret.from_name("backend"),
]

VALID_SELECTED_STEMS = {"vocals", "drums", "bass", "other"}
DEFAULT_DEMUCS_MODEL = "htdemucs"
DEFAULT_TIMEOUT_SECONDS = 1800

def _worker_headers() -> dict[str, str]:
    token = os.environ.get("WORKER_API_TOKEN")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _backend_base_url() -> str | None:
    value = os.environ.get("BACKEND_API_URL")
    if not value:
        return None
    return value.rstrip("/")


def _complete_url(job: dict[str, Any]) -> str:
    if job.get("callback_complete_url"):
        return str(job["callback_complete_url"])

    base_url = _backend_base_url()
    if not base_url:
        raise ValueError("callback_complete_url or BACKEND_API_URL is required")
    return f"{base_url}/worker/jobs/{job['transcription_id']}/complete"


def _failed_url(job: dict[str, Any]) -> str:
    if job.get("callback_failed_url"):
        return str(job["callback_failed_url"])

    base_url = _backend_base_url()
    if not base_url:
        raise ValueError("callback_failed_url or BACKEND_API_URL is required")
    return f"{base_url}/worker/jobs/{job['transcription_id']}/failed"


def _download_file(url: str, destination: Path) -> None:
    import requests

    with requests.get(url, stream=True, timeout=(10, 300)) as response:
        response.raise_for_status()
        with destination.open("wb") as output_file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output_file.write(chunk)


def _download_suffix(url: str) -> str:
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix in {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".webm", ".mp4"}:
        return suffix
    return ".audio"


def _find_selected_stem(output_dir: Path, model_name: str, input_stem: str, selected_stem: str) -> Path:
    expected_path = output_dir / model_name / input_stem / f"{selected_stem}.wav"
    if expected_path.exists():
        return expected_path

    matches = list((output_dir / model_name).rglob(f"{selected_stem}.wav"))
    if matches:
        return matches[0]

    all_matches = list(output_dir.rglob(f"{selected_stem}.wav"))
    if all_matches:
        return all_matches[0]

    raise FileNotFoundError(f"Demucs did not produce {selected_stem}.wav")


def _run_demucs(input_path: Path, output_dir: Path, selected_stem: str) -> Path:
    model_name = os.environ.get("DEMUCS_MODEL", DEFAULT_DEMUCS_MODEL)
    timeout_seconds = int(os.environ.get("DEMUCS_CMD_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    cmd = [
        sys.executable,
        "-m",
        "demucs.separate",
        "-n",
        model_name,
        "--two-stems",
        selected_stem,
        "-o",
        str(output_dir),
        str(input_path),
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if result.returncode != 0:
        error_text = (result.stderr or result.stdout or "Demucs returned a non-zero exit code").strip()
        raise RuntimeError(error_text[-2000:])

    return _find_selected_stem(output_dir, model_name, input_path.stem, selected_stem)


def _configure_cloudinary() -> None:
    import cloudinary

    config = {"secure": True}
    if os.environ.get("CLOUDINARY_CLOUD_NAME"):
        config["cloud_name"] = os.environ["CLOUDINARY_CLOUD_NAME"]
    if os.environ.get("CLOUDINARY_API_KEY"):
        config["api_key"] = os.environ["CLOUDINARY_API_KEY"]
    if os.environ.get("CLOUDINARY_API_SECRET"):
        config["api_secret"] = os.environ["CLOUDINARY_API_SECRET"]
    cloudinary.config(**config)


def _upload_file(
    file_path: Path,
    transcription_id: int,
    folder_name: str,
    *,
    resource_type: str,
) -> dict[str, str | None]:
    from cloudinary import uploader

    _configure_cloudinary()
    cloudinary_folder = os.environ.get("CLOUDINARY_FOLDER", "musicstudio").strip("/")
    folder = f"{cloudinary_folder}/transcriptions/{transcription_id}/{folder_name}"
    result = uploader.upload(
        str(file_path),
        folder=folder,
        resource_type=resource_type,
        use_filename=True,
        unique_filename=True,
        overwrite=False,
    )
    return {
        "secure_url": result.get("secure_url"),
        "public_id": result.get("public_id"),
    }


def _upload_stem(stem_path: Path, transcription_id: int, selected_stem: str) -> dict[str, str | None]:
    return _upload_file(
        stem_path,
        transcription_id,
        "selected-stem",
        resource_type="video",
    )


def _normalize_audio_volume(input_path: Path) -> Path:
    import librosa
    import numpy as np
    import soundfile as sf

    output_path = input_path.with_name(f"{input_path.stem}_normalized{input_path.suffix}")
    y, sr = librosa.load(input_path, sr=None, mono=True)
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak > 0:
        y = y * min(0.95 / peak, 20.0)
    sf.write(output_path, y, sr)
    return output_path


def _format_basic_pitch_events(note_events: list) -> list[dict[str, Any]]:
    notes = []
    for event in note_events:
        if len(event) < 4:
            continue
        onset, offset, pitch, amplitude = event[:4]
        confidence = float(amplitude or 0)
        notes.append({
            "onset": round(float(onset), 3),
            "offset": round(float(offset), 3),
            "pitch": int(pitch),
            "velocity": max(1, min(127, int(round(confidence * 127)))),
            "confidence": round(confidence, 3),
        })
    return notes


def _confidence_stats(notes: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(note.get("confidence", 0)) for note in notes if isinstance(note, dict)]
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "mean": round(sum(values) / len(values), 4),
    }


def _detect_pitch_basic_pitch(input_path: Path, sensitivity: str = "normal") -> dict[str, Any]:
    logger.info("[BASIC PITCH CPU MODE] [TENSORFLOW GPU DISABLED]")
    try:
        # Set environment variables to hide GPUs from TensorFlow
        import os
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
        os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"
        os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"

        import tensorflow as tf
        tf.config.set_visible_devices([], "GPU")

        from basic_pitch.inference import predict

        threshold = 0.2 if sensitivity == "high" else 0.35
        model_output, _midi_data, note_events = predict(str(input_path))
        notes = [
            note
            for note in _format_basic_pitch_events(note_events)
            if float(note.get("confidence", 1.0)) >= threshold
        ]
        return {
            "notes": notes,
            "model_outputs": {
                "backend": "basic_pitch.modal",
                "sensitivity": sensitivity,
                "confidence_threshold": threshold,
                "raw_output_summary": str(type(model_output)),
            },
            "confidence_stats": _confidence_stats(notes),
            "total_notes_detected": len(notes),
        }
    except Exception as exc:
        logger.exception("Basic Pitch inference failed: %s", exc)
        raise


def _note_to_tablature(notes_data: dict[str, Any], instrument_type: str) -> dict[str, Any]:
    tuning = [28, 33, 38, 43] if instrument_type == "bass" else [40, 45, 50, 55, 59, 64]
    string_labels = ["E", "A", "D", "G"] if instrument_type == "bass" else ["E", "A", "D", "G", "B", "E"]
    tab_notes = []
    for note in notes_data.get("notes", []):
        pitch = int(note.get("pitch", 0))
        candidates = [
            (string_index + 1, pitch - open_pitch)
            for string_index, open_pitch in enumerate(tuning)
            if 0 <= pitch - open_pitch <= 24
        ]
        if not candidates:
            continue
        string_number, fret = min(candidates, key=lambda item: (item[1], item[0]))
        onset = float(note.get("onset", 0))
        offset = float(note.get("offset", onset))
        tab_notes.append({
            "string": string_number,
            "fret": fret,
            "startTime": onset,
            "duration": max(0.05, offset - onset),
            "confidence": note.get("confidence"),
        })
    return {
        "instrument": instrument_type,
        "tuning": string_labels,
        "tablature": tab_notes,
    }


def _notes_to_midi(notes_data: dict[str, Any], output_path: Path, tempo_bpm: float = 120.0) -> None:
    import mido
    from mido import Message, MidiFile, MidiTrack

    ticks_per_beat = 480
    tempo = int(60000000 / max(1.0, tempo_bpm))
    seconds_per_tick = tempo / 1000000.0 / ticks_per_beat
    mid = MidiFile(ticks_per_beat=ticks_per_beat)
    track = MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=tempo))

    events = []
    for note in notes_data.get("notes", []):
        onset = float(note.get("onset", 0))
        offset = float(note.get("offset", onset + 0.1))
        pitch = int(note.get("pitch", 0))
        velocity = int(note.get("velocity", 64))
        if 0 <= pitch <= 127:
            events.append((int(onset / seconds_per_tick), 1, Message("note_on", note=pitch, velocity=velocity, time=0)))
            events.append((int(offset / seconds_per_tick), 0, Message("note_off", note=pitch, velocity=0, time=0)))

    previous_tick = 0
    for tick, _order, message in sorted(events, key=lambda item: (item[0], item[1])):
        message.time = max(0, tick - previous_tick)
        track.append(message)
        previous_tick = tick
    mid.save(output_path)


def _midi_to_musicxml(midi_path: Path) -> str | None:
    try:
        from music21 import converter

        score = converter.parse(str(midi_path))
        return score.write("musicxml")
    except Exception as exc:
        logger.warning("MusicXML conversion failed: %s", exc)
        return None


def _tablature_to_ascii(tab_data: dict[str, Any]) -> str:
    labels = tab_data.get("tuning") or ["E", "A", "D", "G", "B", "E"]
    notes = tab_data.get("tablature") or []
    lines = {label: [f"{label}|"] for label in labels}
    for note in sorted(notes, key=lambda item: float(item.get("startTime", item.get("onset", 0)))):
        string_number = int(note.get("string", 1))
        fret = str(note.get("fret", ""))
        label_index = max(0, min(len(labels) - 1, len(labels) - string_number))
        for index, label in enumerate(labels):
            lines[label].append(fret if index == label_index else "-" * max(1, len(fret)))
            lines[label].append("-")
    return "\n".join("".join(lines[label]) for label in reversed(labels))


def _detect_tempo_key_duration(input_path: Path) -> dict[str, Any]:
    import librosa
    import numpy as np

    y, sr = librosa.load(input_path, sr=None, mono=True)
    duration = int(round(float(librosa.get_duration(y=y, sr=sr)))) if y.size else None
    tempo = None
    tempo_confidence = None
    try:
        tempo_fn = getattr(librosa.feature, "tempo", None) or librosa.beat.tempo
        tempo_values = tempo_fn(y=y, sr=sr)
        tempo = int(round(float(tempo_values[0]))) if len(tempo_values) else None
        tempo_confidence = 75 if tempo else None
    except Exception:
        pass

    detected_key = None
    key_confidence = None
    try:
        chroma = librosa.feature.chroma_stft(y=y, sr=sr)
        chroma_mean = np.mean(chroma, axis=1)
        names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        index = int(np.argmax(chroma_mean))
        total = float(np.sum(chroma_mean))
        detected_key = names[index]
        key_confidence = int(round((float(chroma_mean[index]) / total) * 100)) if total > 0 else None
    except Exception:
        pass

    return {
        "duration": duration,
        "detected_tempo": tempo,
        "tempo_confidence": tempo_confidence,
        "detected_key": detected_key,
        "key_confidence": key_confidence,
    }


def _analyze_drum_rhythm(input_path: Path) -> dict[str, Any]:
    import librosa
    import numpy as np

    y, sr = librosa.load(input_path, sr=None, mono=True)
    onset_frames = librosa.onset.onset_detect(y=y, sr=sr, units="frames", backtrack=False)
    onset_times = librosa.frames_to_time(onset_frames, sr=sr)
    envelope = librosa.onset.onset_strength(y=y, sr=sr)
    max_strength = float(np.max(envelope)) if envelope.size else 0.0
    drum_hits = []
    for index, onset in enumerate(onset_times):
        frame = int(onset_frames[index]) if index < len(onset_frames) else 0
        strength = float(envelope[frame]) if frame < len(envelope) else max_strength
        confidence = strength / max_strength if max_strength > 0 else 0.75
        drum_hits.append({
            "onset": round(float(onset), 3),
            "offset": round(float(onset) + 0.12, 3),
            "confidence": round(max(0.0, min(1.0, confidence)), 3),
        })
    duration = float(librosa.get_duration(y=y, sr=sr)) if y.size else 0.0
    return {
        "drum_hits": drum_hits,
        "rhythm_analysis": {
            "source": "drum_stem_onset_detection",
            "total_duration": duration,
            "hit_count": len(drum_hits),
        },
    }


def _analyze_selected_stem(stem_path: Path, selected_stem: str) -> dict[str, Any]:
    if selected_stem == "vocals":
        return {
            "notes_data": {"notes": [], "message": "Vocal stem playback is available; notation is not enabled in this MVP."},
            "track_metadata": {"confidence_notes": "Playback-only vocal stem."},
        }
    if selected_stem == "drums":
        rhythm = _analyze_drum_rhythm(stem_path)
        return {
            "notes_data": rhythm,
            "track_metadata": {"confidence_notes": None},
        }

    normalized_path = _normalize_audio_volume(stem_path)
    pitch_result = _detect_pitch_basic_pitch(normalized_path, "normal")
    if not pitch_result.get("notes"):
        pitch_result = _detect_pitch_basic_pitch(normalized_path, "high")

    instrument_type = "bass" if selected_stem == "bass" else "guitar"
    tab_data = _note_to_tablature(pitch_result, instrument_type) if pitch_result.get("notes") else None
    track_metadata = {
        "display_name": "Bass" if selected_stem == "bass" else "Guitar / Other",
        "confidence_notes": pitch_result.get("warning_message"),
    }
    return {
        "notes_data": pitch_result,
        "tablature_data": tab_data,
        "track_metadata": track_metadata,
    }


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    import requests

    response = requests.post(
        url,
        json=payload,
        headers=_worker_headers(),
        timeout=(10, 60),
    )
    response.raise_for_status()
    if not response.content:
        return None
    return response.json()


def _complete_job(
    job: dict[str, Any],
    upload_result: dict[str, str | None],
    analysis_result: dict[str, Any],
) -> None:
    track_metadata = analysis_result.get("track_metadata") or {}
    if upload_result.get("secure_url"):
        track_metadata.setdefault("confidence_notes", "Selected stem separated by Modal/Demucs.")
    payload = {
        "separated_audio_url": upload_result.get("secure_url"),
        "separated_audio_public_id": upload_result.get("public_id"),
        "midi_file_url": analysis_result.get("midi_file_url"),
        "midi_file_public_id": analysis_result.get("midi_file_public_id"),
        "tab_file_url": analysis_result.get("tab_file_url"),
        "tab_file_public_id": analysis_result.get("tab_file_public_id"),
        "confidence": analysis_result.get("confidence", 90),
        "duration": analysis_result.get("duration"),
        "detected_tempo": analysis_result.get("detected_tempo"),
        "tempo_confidence": analysis_result.get("tempo_confidence"),
        "detected_key": analysis_result.get("detected_key"),
        "key_confidence": analysis_result.get("key_confidence"),
        "notes_data": analysis_result.get("notes_data"),
        "chords_data": analysis_result.get("chords_data"),
        "tablature_data": analysis_result.get("tablature_data"),
        "notation_data": analysis_result.get("notation_data"),
        "chord_chart_data": analysis_result.get("chord_chart_data"),
        "track_metadata": track_metadata,
    }
    _post_json(_complete_url(job), payload)


def _fail_job(job: dict[str, Any], error: str, internal_logs: str | None = None) -> None:
    payload = {
        "error": error[:500] or "Modal worker failed.",
        "internal_logs": internal_logs,
    }
    _post_json(_failed_url(job), payload)


def _normalize_job(job: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(job, dict):
        raise ValueError("Job payload must be a JSON object")
    if not job.get("transcription_id"):
        raise ValueError("transcription_id is required")
    if not job.get("original_audio_url"):
        if str(job.get("job_type") or "process") == "process":
            raise ValueError("original_audio_url is required")
    if str(job.get("job_type") or "process") in {"generate_tab", "reprocess_track"} and not job.get("separated_audio_url"):
        raise ValueError("separated_audio_url is required for this Modal job")

    selected_stem = str(job.get("selected_stem") or job.get("demucs_stem") or "other").strip().lower()
    if selected_stem not in VALID_SELECTED_STEMS:
        raise ValueError(f"selected_stem must be one of: {', '.join(sorted(VALID_SELECTED_STEMS))}")

    normalized = dict(job)
    normalized["selected_stem"] = selected_stem
    normalized["demucs_stem"] = selected_stem
    return normalized


def _generate_analysis_and_exports(
    stem_path: Path,
    transcription_id: int,
    selected_stem: str,
    *,
    sensitivity: str = "normal",
) -> dict[str, Any]:
    analysis = _analyze_selected_stem(stem_path, selected_stem)
    analysis.update(_detect_tempo_key_duration(stem_path))

    notes_data = analysis.get("notes_data")
    if selected_stem in {"bass", "other"} and isinstance(notes_data, dict) and notes_data.get("notes"):
        instrument_type = "bass" if selected_stem == "bass" else "guitar"
        if sensitivity == "high" and notes_data.get("model_outputs"):
            notes_data["model_outputs"]["requested_sensitivity"] = "high"
        tab_data = analysis.get("tablature_data") or _note_to_tablature(notes_data, instrument_type)
        analysis["tablature_data"] = tab_data

        midi_path = stem_path.with_name(f"transcription_{transcription_id}.mid")
        _notes_to_midi(notes_data, midi_path, tempo_bpm=float(analysis.get("detected_tempo") or 120))
        midi_upload = _upload_file(midi_path, transcription_id, "exports", resource_type="raw")
        analysis["midi_file_url"] = midi_upload.get("secure_url")
        analysis["midi_file_public_id"] = midi_upload.get("public_id")

        musicxml_path_text = _midi_to_musicxml(midi_path)
        if musicxml_path_text:
            musicxml_path = Path(musicxml_path_text)
            if musicxml_path.exists():
                analysis["notation_data"] = musicxml_path.read_text(encoding="utf-8", errors="ignore")

        tab_path = stem_path.with_name(f"transcription_{transcription_id}.tab")
        tab_path.write_text(_tablature_to_ascii(tab_data), encoding="utf-8")
        tab_upload = _upload_file(tab_path, transcription_id, "exports", resource_type="raw")
        analysis["tab_file_url"] = tab_upload.get("secure_url")
        analysis["tab_file_public_id"] = tab_upload.get("public_id")

    return analysis


def _process_job(job: dict[str, Any]) -> dict[str, Any]:
    job = _normalize_job(job)
    transcription_id = int(job["transcription_id"])
    selected_stem = str(job["selected_stem"])
    job_type = str(job.get("job_type") or "process")
    sensitivity = str(job.get("detection_sensitivity") or "normal")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        upload_result = {"secure_url": job.get("separated_audio_url"), "public_id": None}

        if job_type == "process":
            input_path = temp_path / f"original_{transcription_id}{_download_suffix(str(job['original_audio_url']))}"
            output_dir = temp_path / "demucs"
            _download_file(str(job["original_audio_url"]), input_path)
            selected_stem_path = _run_demucs(input_path, output_dir, selected_stem)
            upload_result = _upload_stem(selected_stem_path, transcription_id, selected_stem)
        else:
            selected_stem_path = temp_path / f"selected_{transcription_id}{_download_suffix(str(job['separated_audio_url']))}"
            _download_file(str(job["separated_audio_url"]), selected_stem_path)

        analysis_result = _generate_analysis_and_exports(
            selected_stem_path,
            transcription_id,
            selected_stem,
            sensitivity=sensitivity,
        )
        _complete_job(job, upload_result, analysis_result)

    return {
        "status": "completed",
        "job_type": job_type,
        "transcription_id": transcription_id,
        "selected_stem": selected_stem,
        "separated_audio_url": upload_result.get("secure_url"),
        "separated_audio_public_id": upload_result.get("public_id"),
        "can_generate_score": bool(analysis_result.get("notes_data", {}).get("notes")),
    }


@app.function(
    image=image,
    gpu="T4",
    secrets=secrets,
    timeout=DEFAULT_TIMEOUT_SECONDS + 300,
)
def _process_job_background(job: dict[str, Any]) -> None:
    try:
        _process_job(job)
    except Exception as exc:
        logger.exception(
            "Modal worker failed before backend callback for job %s",
            job.get("transcription_id") if isinstance(job, dict) else None,
        )
        try:
            if isinstance(job, dict):
                _fail_job(job, "Could not isolate the selected stem.", str(exc))
        except Exception:
            logger.exception("Failed to call failure callback for job %s", job.get("transcription_id"))


@app.function(
    image=image,
    gpu="T4",
    secrets=secrets,
    timeout=DEFAULT_TIMEOUT_SECONDS + 300,
)
@modal.fastapi_endpoint(method="POST", label="musicstudio-process")
def process(job: dict[str, Any]) -> dict[str, Any]:
    # Spawn the background job
    _process_job_background.spawn(job)
    return {
        "status": "accepted",
        "transcription_id": job.get("transcription_id"),
        "modal_request_id": job.get("modal_request_id"),
    }
