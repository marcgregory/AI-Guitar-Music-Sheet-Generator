import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import modal


app = modal.App("musicstudio")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install(
        "fastapi[standard]==0.115.6",
        "demucs==4.0.1",
        "torch==2.1.0",
        "torchaudio==2.1.0",
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


def _upload_stem(stem_path: Path, transcription_id: int, selected_stem: str) -> dict[str, str | None]:
    from cloudinary import uploader

    _configure_cloudinary()
    cloudinary_folder = os.environ.get("CLOUDINARY_FOLDER", "musicstudio").strip("/")
    folder = f"{cloudinary_folder}/transcriptions/{transcription_id}/selected-stem"
    result = uploader.upload(
        str(stem_path),
        folder=folder,
        resource_type="video",
        use_filename=True,
        unique_filename=True,
        overwrite=False,
    )
    return {
        "secure_url": result.get("secure_url"),
        "public_id": result.get("public_id"),
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


def _complete_job(job: dict[str, Any], upload_result: dict[str, str | None]) -> None:
    payload = {
        "separated_audio_url": upload_result.get("secure_url"),
        "separated_audio_public_id": upload_result.get("public_id"),
        "confidence": 90,
        "track_metadata": {
            "confidence_notes": "Selected stem separated by Modal/Demucs.",
        },
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
        raise ValueError("original_audio_url is required")

    selected_stem = str(job.get("selected_stem") or job.get("demucs_stem") or "other").strip().lower()
    if selected_stem not in VALID_SELECTED_STEMS:
        raise ValueError(f"selected_stem must be one of: {', '.join(sorted(VALID_SELECTED_STEMS))}")

    normalized = dict(job)
    normalized["selected_stem"] = selected_stem
    normalized["demucs_stem"] = selected_stem
    return normalized


def _process_job(job: dict[str, Any]) -> dict[str, Any]:
    job = _normalize_job(job)
    transcription_id = int(job["transcription_id"])
    selected_stem = str(job["selected_stem"])

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        input_path = temp_path / f"original_{transcription_id}{_download_suffix(str(job['original_audio_url']))}"
        output_dir = temp_path / "demucs"

        _download_file(str(job["original_audio_url"]), input_path)
        selected_stem_path = _run_demucs(input_path, output_dir, selected_stem)
        upload_result = _upload_stem(selected_stem_path, transcription_id, selected_stem)
        _complete_job(job, upload_result)

    return {
        "status": "completed",
        "transcription_id": transcription_id,
        "selected_stem": selected_stem,
        "separated_audio_url": upload_result.get("secure_url"),
        "separated_audio_public_id": upload_result.get("public_id"),
    }


@app.function(
    image=image,
    gpu="T4",
    secrets=secrets,
    timeout=DEFAULT_TIMEOUT_SECONDS + 300,
)
@modal.fastapi_endpoint(method="POST", label="musicstudio-process")
def process(job: dict[str, Any]) -> dict[str, Any]:
    try:
        return _process_job(job)
    except Exception as exc:
        try:
            if isinstance(job, dict):
                _fail_job(job, "Could not isolate the selected stem.", str(exc))
        finally:
            raise
