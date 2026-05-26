#!/usr/bin/env python3
"""Hosted deploy smoke check.

Usage:
    python scripts/deploy_smoke.py --base-url https://your-api.example
    python scripts/deploy_smoke.py --base-url https://your-api.example \
        --username smoke@example.com --password '...' --run-upload
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
import uuid
import wave
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


READY_STATUSES = {"stem_ready", "completed", "completed_with_warning"}
RATE_LIMITED_MODAL_STATUSES = {"rate_limited", "retry_queued"}

def _request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
) -> dict:
    request = Request(
        url,
        data=data,
        method=method,
        headers={"Accept": "application/json", **(headers or {})},
    )
    with urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def _get_json(url: str, token: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    return _request_json(url, headers=headers)


def _post_form_json(url: str, fields: dict[str, str]) -> dict:
    return _request_json(
        url,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=urlencode(fields).encode("utf-8"),
    )


def _post_json(url: str, payload: dict) -> dict:
    return _request_json(
        url,
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload).encode("utf-8"),
    )


def _tiny_wav_bytes() -> bytes:
    buffer = io.BytesIO()
    sample_rate = 8_000
    duration_seconds = 1
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for index in range(sample_rate * duration_seconds):
            sample = int(2600 * ((index // 32) % 2 * 2 - 1))
            wav_file.writeframesraw(sample.to_bytes(2, "little", signed=True))
    return buffer.getvalue()


def _multipart_upload(
    url: str,
    *,
    token: str,
    selected_stem: str,
    file_bytes: bytes,
) -> dict:
    boundary = f"----musicstudio-smoke-{uuid.uuid4().hex}"
    parts = [
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="selected_stem"\r\n\r\n'
            f"{selected_stem}\r\n"
        ).encode("utf-8"),
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="modal-smoke.wav"\r\n'
            "Content-Type: audio/wav\r\n\r\n"
        ).encode("utf-8"),
        file_bytes,
        f"\r\n--{boundary}--\r\n".encode("utf-8"),
    ]
    return _request_json(
        url,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        data=b"".join(parts),
    )


def _login(api_url: str, username: str, password: str) -> str:
    payload = _post_form_json(
        f"{api_url}/auth/login",
        {"username": username, "password": password},
    )
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("login did not return an access token")
    return token


def _register(api_url: str, username: str, password: str) -> None:
    _post_json(
        f"{api_url}/auth/register",
        {
            "email": username,
            "username": username.split("@", 1)[0][:50],
            "password": password,
        },
    )


def _run_upload_smoke(
    api_url: str,
    *,
    username: str,
    password: str,
    register: bool,
    selected_stem: str,
    poll_seconds: int,
) -> int:
    if register:
        try:
            _register(api_url, username, password)
            print("registered smoke user")
        except HTTPError as exc:
            if exc.code != 400:
                raise
            print("smoke user already exists; continuing")

    token = _login(api_url, username, password)
    print("login ok")

    upload = _multipart_upload(
        f"{api_url}/audio/upload",
        token=token,
        selected_stem=selected_stem,
        file_bytes=_tiny_wav_bytes(),
    )
    transcription_id = upload["id"]
    print(f"upload ok: transcription_id={transcription_id}")
    print(f"initial status: {upload.get('processing_status')}")

    deadline = time.monotonic() + poll_seconds
    last_status: dict | None = None
    while time.monotonic() < deadline:
        status_payload = _get_json(f"{api_url}/audio/{transcription_id}/status", token)
        last_status = status_payload
        status_value = status_payload.get("status")
        modal_dispatch_status = status_payload.get("modal_dispatch_status")
        modal_request_id = status_payload.get("modal_request_id")
        print(
            "poll: "
            f"status={status_value} "
            f"modal_dispatch_status={modal_dispatch_status} "
            f"modal_request_id={modal_request_id} "
            f"retry_count={status_payload.get('modal_retry_count')} "
            f"retry_at={status_payload.get('modal_retry_at')}"
        )

        if status_value in READY_STATUSES:
            print(f"ready terminal status observed: {status_value}")
            return 0
        if status_value == "failed":
            print(f"job failed: {status_payload.get('error')}", file=sys.stderr)
            return 4
        if modal_dispatch_status in RATE_LIMITED_MODAL_STATUSES:
            print("Modal rate-limited; retry scheduled")
            return 0
        time.sleep(5)

    print("timed out waiting for Modal completion", file=sys.stderr)
    if last_status:
        print(json.dumps(last_status, indent=2, sort_keys=True), file=sys.stderr)
    return 3


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a deployed backend.")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Backend base URL, for example https://musicstudio-api.example",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print raw deployment health JSON.",
    )
    parser.add_argument(
        "--run-upload",
        action="store_true",
        help="Upload a generated tiny WAV and poll Modal dispatch status.",
    )
    parser.add_argument("--username", help="Smoke-test account username or email.")
    parser.add_argument("--password", help="Smoke-test account password.")
    parser.add_argument(
        "--register",
        action="store_true",
        help="Register the smoke-test account before login.",
    )
    parser.add_argument(
        "--selected-stem",
        default="other",
        choices=["vocals", "drums", "bass", "other"],
        help="Selected stem for the upload smoke.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=420,
        help="Maximum seconds to poll the uploaded transcription.",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    api_url = f"{base_url}/api/v1"
    try:
        health = _get_json(f"{base_url}/health/deployment")
    except HTTPError as exc:
        print(f"health request failed: HTTP {exc.code}", file=sys.stderr)
        return 2
    except (OSError, URLError, json.JSONDecodeError) as exc:
        print(f"health request failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(health, indent=2, sort_keys=True))
    else:
        checks = health.get("checks", {})
        print(f"deployment status: {health.get('status')}")
        print(f"ready/proceed: {health.get('ready')} / {health.get('proceed')}")
        for name, result in checks.items():
            marker = "ok" if result.get("ok") else "fail"
            print(f"{marker}: {name}")

    if not health.get("ready"):
        return 1

    if not args.run_upload:
        return 0

    if not args.username or not args.password:
        print("--username and --password are required with --run-upload", file=sys.stderr)
        return 2

    try:
        return _run_upload_smoke(
            api_url,
            username=args.username,
            password=args.password,
            register=args.register,
            selected_stem=args.selected_stem,
            poll_seconds=args.poll_seconds,
        )
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"upload smoke failed: HTTP {exc.code} {detail}", file=sys.stderr)
        return 2
    except (OSError, URLError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"upload smoke failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
