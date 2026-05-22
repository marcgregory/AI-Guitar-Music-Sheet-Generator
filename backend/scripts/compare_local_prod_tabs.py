import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from sqlalchemy import create_engine, text


SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
DEFAULT_ENV_FILE = BACKEND_DIR / ".env.local"
DEFAULT_DEBUG_DIR = BACKEND_DIR / "debug"

TAB_CAPABLE_STEMS = {"bass", "other"}
TRACK_INSTRUMENT_BY_STEM = {
    "bass": "bass",
    "other": "guitar",
}

TRANSCRIPTION_ARTIFACT_FIELDS = (
    "tablature_data",
    "notation_data",
    "midi_file_path",
    "midi_file_url",
    "midi_file_public_id",
    "tab_file_path",
    "tab_file_url",
    "tab_file_public_id",
)

TRANSCRIPTION_RESET_FIELDS = (
    "tab_generation_status",
    "modal_job_type",
    "modal_request_id",
    "modal_dispatch_status",
    "modal_dispatched_at",
    "modal_retry_at",
)

TRACK_ARTIFACT_FIELDS = (
    "tab_json",
    "notation_json",
)


@dataclass(frozen=True)
class EnvironmentConfig:
    name: str
    api_url: str
    transcription_id: int
    auth_token: str


@dataclass(frozen=True)
class EnvironmentPayload:
    config: EnvironmentConfig
    status: dict[str, Any]
    result: dict[str, Any]
    tracks: list[dict[str, Any]]
    selected_track: dict[str, Any] | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare LOCAL vs PROD transcription JSON and optionally clear stale "
            "prod tab artifacts before regenerating tabs."
        )
    )
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
        help="Env file containing API URLs, tokens, and transcription ids.",
    )
    parser.add_argument(
        "--local-id",
        type=int,
        default=None,
        help="Override LOCAL_TRANSCRIPTION_ID from env.",
    )
    parser.add_argument(
        "--prod-id",
        type=int,
        default=None,
        help="Override PROD_TRANSCRIPTION_ID from env. Defaults to 12 when unset.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually clear prod DB artifact fields and trigger regeneration.",
    )
    parser.add_argument(
        "--force-regenerate",
        action="store_true",
        help="Regenerate even when no stale prod artifacts are detected.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=300,
        help="Maximum seconds to poll prod after triggering regeneration in --apply mode.",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=5,
        help="Seconds between prod status polls in --apply mode.",
    )
    parser.add_argument(
        "--write-debug-payloads",
        action="store_true",
        help="Write full local/prod comparison payloads to JSON files.",
    )
    parser.add_argument(
        "--debug-dir",
        default=str(DEFAULT_DEBUG_DIR),
        help="Directory for debug payload files when --write-debug-payloads is enabled.",
    )
    return parser.parse_args()


def require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise SystemExit(f"Missing required environment value: {name}")
    return value.strip()


def optional_int_env(name: str, default: int | None = None) -> int | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer, got {value!r}") from exc


def normalize_api_url(value: str) -> str:
    return value.rstrip("/")


def load_config(args: argparse.Namespace) -> tuple[EnvironmentConfig, EnvironmentConfig]:
    env_path = Path(args.env_file)
    if env_path.exists():
        load_dotenv(env_path, override=False)

    local_id = args.local_id or optional_int_env("LOCAL_TRANSCRIPTION_ID")
    if local_id is None:
        legacy_id = optional_int_env("TRANSCRIPTION_ID")
        if legacy_id is not None:
            raise SystemExit(
                "TRANSCRIPTION_ID is present, but this script requires separate IDs. "
                "Set LOCAL_TRANSCRIPTION_ID and PROD_TRANSCRIPTION_ID instead."
            )
        raise SystemExit("Missing LOCAL_TRANSCRIPTION_ID. Refusing to assume local and prod IDs match.")

    prod_id = args.prod_id or optional_int_env("PROD_TRANSCRIPTION_ID", 12)
    if prod_id is None:
        raise SystemExit("Missing PROD_TRANSCRIPTION_ID.")

    local = EnvironmentConfig(
        name="local",
        api_url=normalize_api_url(require_env("LOCAL_API_URL")),
        transcription_id=local_id,
        auth_token=require_env("LOCAL_AUTH_TOKEN"),
    )
    prod = EnvironmentConfig(
        name="prod",
        api_url=normalize_api_url(require_env("PROD_API_URL")),
        transcription_id=prod_id,
        auth_token=require_env("PROD_AUTH_TOKEN"),
    )
    return local, prod


def api_headers(config: EnvironmentConfig) -> dict[str, str]:
    return {"Authorization": f"Bearer {config.auth_token}"}


def get_json(client: httpx.Client, config: EnvironmentConfig, suffix: str) -> Any:
    url = f"{config.api_url}/audio/{config.transcription_id}{suffix}"
    response = client.get(url, headers=api_headers(config))
    if response.is_error:
        raise SystemExit(
            f"{config.name} API request failed: GET {url} returned "
            f"{response.status_code}\n{response.text[:1000]}"
        )
    return response.json()


def post_json(client: httpx.Client, config: EnvironmentConfig, suffix: str, payload: dict[str, Any] | None = None) -> Any:
    url = f"{config.api_url}/audio/{config.transcription_id}{suffix}"
    response = client.post(url, headers=api_headers(config), json=payload or {})
    if response.is_error:
        raise SystemExit(
            f"{config.name} API request failed: POST {url} returned "
            f"{response.status_code}\n{response.text[:1000]}"
        )
    return response.json()


def fetch_environment(config: EnvironmentConfig) -> EnvironmentPayload:
    with httpx.Client(timeout=30.0) as client:
        status_payload = get_json(client, config, "/status")
        result_payload = get_json(client, config, "/result")
        tracks_payload = get_json(client, config, "/tracks")

    if not isinstance(status_payload, dict):
        raise SystemExit(f"{config.name} status response was not an object.")
    if not isinstance(result_payload, dict):
        raise SystemExit(f"{config.name} result response was not an object.")
    if not isinstance(tracks_payload, list):
        raise SystemExit(f"{config.name} tracks response was not a list.")

    return EnvironmentPayload(
        config=config,
        status=status_payload,
        result=result_payload,
        tracks=tracks_payload,
        selected_track=select_track(result_payload, tracks_payload),
    )


def select_track(result: dict[str, Any], tracks: list[dict[str, Any]]) -> dict[str, Any] | None:
    selected_stem = str(result.get("selected_stem") or "other").strip().lower()
    expected_instrument = TRACK_INSTRUMENT_BY_STEM.get(selected_stem, selected_stem)
    for track in tracks:
        if str(track.get("instrument_type") or "").strip().lower() == expected_instrument:
            return track
    for track in tracks:
        if track.get("notes_json"):
            return track
    return tracks[0] if tracks else None


def parse_jsonish(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return value
    return value


def note_list_from_payload(value: Any) -> list[dict[str, Any]]:
    parsed = parse_jsonish(value)
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if not isinstance(parsed, dict):
        return []
    for key in ("notes", "pitch_info"):
        notes = parsed.get(key)
        if isinstance(notes, list):
            return [item for item in notes if isinstance(item, dict)]
    return []


def extract_event_list(value: Any) -> list[dict[str, Any]]:
    parsed = parse_jsonish(value)
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if not isinstance(parsed, dict):
        return []

    for key in (
        "tablature",
        "tabs",
        "events",
        "notes",
        "pitch_info",
        "tablature_data",
        "tab_json",
        "notes_data",
        "notes_json",
    ):
        events = parsed.get(key)
        if isinstance(events, list):
            return [item for item in events if isinstance(item, dict)]
        nested_events = extract_event_list(events)
        if nested_events:
            return nested_events
    return []


def event_confidence_stats(events: list[dict[str, Any]]) -> dict[str, float | int | None]:
    confidences = [
        float(event["confidence"])
        for event in events
        if isinstance(event.get("confidence"), (int, float))
    ]
    if not confidences:
        return {
            "count": len(events),
            "avg_confidence": None,
            "min_confidence": None,
            "max_confidence": None,
        }
    return {
        "count": len(events),
        "avg_confidence": round(sum(confidences) / len(confidences), 4),
        "min_confidence": round(min(confidences), 4),
        "max_confidence": round(max(confidences), 4),
    }


def preview_events(events: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    stable_fields = ("string", "fret", "startTime", "duration", "confidence")
    return [
        {key: event[key] for key in stable_fields if key in event}
        for event in events[:max(0, limit)]
    ]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def count_differing_events(local_events: list[dict[str, Any]], prod_events: list[dict[str, Any]]) -> int:
    shared_length = min(len(local_events), len(prod_events))
    differing_positions = sum(
        1
        for index in range(shared_length)
        if canonical_json(local_events[index]) != canonical_json(prod_events[index])
    )
    return differing_positions + abs(len(local_events) - len(prod_events))


def detected_note_count(value: Any) -> int:
    parsed = parse_jsonish(value)
    if isinstance(parsed, dict):
        total = parsed.get("total_notes_detected")
        if isinstance(total, int):
            return total
        if isinstance(total, float):
            return int(total)
    return len(note_list_from_payload(parsed))


def average_note_confidence(value: Any, selected_track: dict[str, Any] | None = None) -> float | int | None:
    parsed = parse_jsonish(value)
    if isinstance(parsed, dict):
        stats = parsed.get("confidence_stats")
        if isinstance(stats, dict):
            for key in ("average", "avg", "mean", "average_confidence"):
                candidate = stats.get(key)
                if isinstance(candidate, (int, float)):
                    return round(float(candidate), 4)
        model_outputs = parsed.get("model_outputs")
        if isinstance(model_outputs, dict):
            for key in ("average_note_confidence", "avg_note_confidence"):
                candidate = model_outputs.get(key)
                if isinstance(candidate, (int, float)):
                    return round(float(candidate), 4)

    confidences = [
        float(note["confidence"])
        for note in note_list_from_payload(parsed)
        if isinstance(note.get("confidence"), (int, float))
    ]
    if confidences:
        return round(sum(confidences) / len(confidences), 4)

    if selected_track:
        track_score = selected_track.get("confidence_score")
        if isinstance(track_score, (int, float)):
            return track_score
    return None


def nested_get(payload: Any, path: tuple[str, ...]) -> Any:
    current = payload
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def processing_config(value: Any) -> dict[str, Any]:
    parsed = parse_jsonish(value)
    if not isinstance(parsed, dict):
        return {}
    candidates = {
        "model_outputs": parsed.get("model_outputs"),
        "confidence_stats": parsed.get("confidence_stats"),
        "note_detection_attempts": parsed.get("note_detection_attempts"),
        "debug_model_outputs": nested_get(parsed, ("debug", "model_outputs")),
        "debug_confidence_stats": nested_get(parsed, ("debug", "confidence_stats")),
        "debug_note_detection_attempts": nested_get(parsed, ("debug", "note_detection_attempts")),
        "processing_version": parsed.get("processing_version"),
        "config": parsed.get("config"),
    }
    return {key: value for key, value in candidates.items() if value is not None}


def selected_track_notes(payload: EnvironmentPayload) -> Any:
    if payload.selected_track:
        return payload.selected_track.get("notes_json")
    return None


def comparison_snapshot(payload: EnvironmentPayload) -> dict[str, Any]:
    notes_data = payload.result.get("notes_data")
    return {
        "environment": payload.config.name,
        "api_url": payload.config.api_url,
        "transcription_id": payload.config.transcription_id,
        "selected_stem": payload.result.get("selected_stem") or payload.status.get("selected_stem"),
        "status": payload.status.get("status") or payload.result.get("processing_status"),
        "tab_generation_status": payload.result.get("tab_generation_status") or payload.status.get("tab_generation_status"),
        "notes_data": parse_jsonish(notes_data),
        "tablature_data": parse_jsonish(payload.result.get("tablature_data")),
        "selected_track": {
            "id": payload.selected_track.get("id"),
            "instrument_type": payload.selected_track.get("instrument_type"),
            "processing_status": payload.selected_track.get("processing_status"),
            "notes_json": parse_jsonish(payload.selected_track.get("notes_json")),
        } if payload.selected_track else None,
        "detected_note_count": detected_note_count(notes_data),
        "average_note_confidence": average_note_confidence(notes_data, payload.selected_track),
        "processing_config": processing_config(notes_data),
    }


def snapshot_event_sets(snapshot: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    selected_track = snapshot.get("selected_track") or {}
    return {
        "notes_data": extract_event_list(snapshot.get("notes_data")),
        "tablature_data": extract_event_list(snapshot.get("tablature_data")),
        "selected_track_notes_json": extract_event_list(selected_track.get("notes_json")),
    }


def comparison_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    events = snapshot_event_sets(snapshot)
    note_stats = event_confidence_stats(events["notes_data"])
    preview_source = events["tablature_data"] or events["notes_data"]
    return {
        "status": snapshot.get("status"),
        "selected_stem": snapshot.get("selected_stem"),
        "notes_count": snapshot.get("detected_note_count") or len(events["notes_data"]),
        "tablature_events_count": len(events["tablature_data"]),
        "selected_track_notes_count": len(events["selected_track_notes_json"]),
        "avg_confidence": note_stats["avg_confidence"] if note_stats["avg_confidence"] is not None else snapshot.get("average_note_confidence"),
        "min_confidence": note_stats["min_confidence"],
        "max_confidence": note_stats["max_confidence"],
        "preview": preview_events(preview_source),
    }


def print_summary_section(label: str, summary: dict[str, Any]) -> None:
    print(f"\n=== {label.upper()} ===")
    for key in (
        "status",
        "selected_stem",
        "notes_count",
        "tablature_events_count",
        "selected_track_notes_count",
        "avg_confidence",
        "min_confidence",
        "max_confidence",
    ):
        print(f"{key}: {summary.get(key)}")
    print(f"preview: {summary.get('preview')}")


def comparison_differences(local_snapshot: dict[str, Any], prod_snapshot: dict[str, Any]) -> list[str]:
    local_events = snapshot_event_sets(local_snapshot)
    prod_events = snapshot_event_sets(prod_snapshot)
    differences: list[str] = []

    for key in ("selected_stem", "status", "tab_generation_status"):
        if local_snapshot.get(key) != prod_snapshot.get(key):
            differences.append(
                f"{key} differs: local={local_snapshot.get(key)!r} prod={prod_snapshot.get(key)!r}"
            )

    for label in ("notes_data", "tablature_data", "selected_track_notes_json"):
        local_count = len(local_events[label])
        prod_count = len(prod_events[label])
        if local_count != prod_count:
            differences.append(f"{label} length differs: local={local_count} prod={prod_count}")
        differing_events = count_differing_events(local_events[label], prod_events[label])
        if differing_events:
            differences.append(f"{label} differing event positions: {differing_events}")

    if canonical_json(local_snapshot.get("processing_config")) != canonical_json(prod_snapshot.get("processing_config")):
        differences.append("processing_config differs")
    return differences


def write_debug_payloads(local_snapshot: dict[str, Any], prod_snapshot: dict[str, Any], debug_dir: str | Path) -> list[Path]:
    target_dir = Path(debug_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    paths = [
        target_dir / "local_tabs.json",
        target_dir / "prod_tabs.json",
    ]
    paths[0].write_text(json.dumps(local_snapshot, indent=2, sort_keys=True, default=str), encoding="utf-8")
    paths[1].write_text(json.dumps(prod_snapshot, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return paths


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def print_comparison(
    local: EnvironmentPayload,
    prod: EnvironmentPayload,
    *,
    write_debug_payload_files: bool = False,
    debug_dir: str | Path = DEFAULT_DEBUG_DIR,
) -> None:
    local_snapshot = comparison_snapshot(local)
    prod_snapshot = comparison_snapshot(prod)
    print("\n=== Local vs Prod Comparison ===")
    print_summary_section("local", comparison_summary(local_snapshot))
    print_summary_section("prod", comparison_summary(prod_snapshot))

    print("\nDifferences:")
    differences = comparison_differences(local_snapshot, prod_snapshot)
    if differences:
        for difference in differences:
            print(f"- {difference}")
    else:
        print("- none")

    if write_debug_payload_files:
        saved_paths = write_debug_payloads(local_snapshot, prod_snapshot, debug_dir)
        print("\nSaved:")
        for path in saved_paths:
            print(f"- {display_path(path)}")


def terminal_safe_value(value: Any) -> Any:
    parsed = parse_jsonish(value)
    events = extract_event_list(parsed)
    if events:
        return {
            "event_count": len(events),
            "preview": preview_events(events),
        }
    if isinstance(parsed, dict):
        return {
            "type": "object",
            "keys": sorted(str(key) for key in parsed.keys()),
        }
    if isinstance(parsed, list):
        return {
            "type": "list",
            "length": len(parsed),
        }
    if isinstance(parsed, str) and len(parsed) > 240:
        return f"{parsed[:240]}... [truncated {len(parsed) - 240} chars]"
    return parsed


def stale_artifact_values(payload: EnvironmentPayload) -> dict[str, Any]:
    values = {
        field: payload.result.get(field)
        for field in TRANSCRIPTION_ARTIFACT_FIELDS
        if payload.result.get(field) not in (None, "", [])
    }
    if payload.selected_track:
        for field in TRACK_ARTIFACT_FIELDS:
            value = payload.selected_track.get(field)
            if value not in (None, "", []):
                values[f"selected_track.{field}"] = value
    return values


def prod_is_processing(payload: EnvironmentPayload) -> bool:
    status = str(payload.status.get("status") or payload.result.get("processing_status") or "").lower()
    generation_status = str(
        payload.status.get("tab_generation_status")
        or payload.result.get("tab_generation_status")
        or ""
    ).lower()
    modal_dispatch_status = str(
        payload.status.get("modal_dispatch_status")
        or payload.result.get("modal_dispatch_status")
        or ""
    ).lower()
    return (
        status == "processing"
        or generation_status == "processing"
        or modal_dispatch_status in {"dispatched", "rate_limited", "retry_queued"}
    )


def print_would_clear(payload: EnvironmentPayload, stale_values: dict[str, Any]) -> None:
    selected_track_id = payload.selected_track.get("id") if payload.selected_track else None
    current_values = {
        "transcription": {
            field: terminal_safe_value(payload.result.get(field))
            for field in TRANSCRIPTION_ARTIFACT_FIELDS + TRANSCRIPTION_RESET_FIELDS
        },
        "selected_track": {
            "id": selected_track_id,
            **({
                field: terminal_safe_value(payload.selected_track.get(field))
                for field in TRACK_ARTIFACT_FIELDS
            } if payload.selected_track else {}),
        },
    }
    print("\n=== Prod Fields To Clear ===")
    print(json.dumps(current_values, indent=2, sort_keys=True, default=str))
    if not stale_values:
        print("No stale generated artifact values were detected.")


def require_prod_database_url() -> str:
    database_url = os.getenv("PROD_DATABASE_URL") or os.getenv("PROD_DATABASE_URL".lower())
    if not database_url:
        raise SystemExit(
            "PROD_DATABASE_URL is required for --apply because there is no API cleanup route "
            "for generated tab artifacts."
        )
    return database_url


def clear_prod_artifacts(database_url: str, prod: EnvironmentPayload) -> None:
    selected_stem = str(prod.result.get("selected_stem") or "other").strip().lower()
    selected_instrument = TRACK_INSTRUMENT_BY_STEM.get(selected_stem)
    selected_track_id = prod.selected_track.get("id") if prod.selected_track else None

    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.begin() as connection:
        result = connection.execute(
            text(
                """
                UPDATE transcriptions
                SET
                    tablature_data = NULL,
                    notation_data = NULL,
                    midi_file_path = NULL,
                    midi_file_url = NULL,
                    midi_file_public_id = NULL,
                    tab_file_path = NULL,
                    tab_file_url = NULL,
                    tab_file_public_id = NULL,
                    tab_generation_status = 'idle',
                    modal_job_type = NULL,
                    modal_request_id = NULL,
                    modal_dispatch_status = NULL,
                    modal_dispatched_at = NULL,
                    modal_retry_at = NULL
                WHERE id = :transcription_id
                """
            ),
            {"transcription_id": prod.config.transcription_id},
        )
        if result.rowcount != 1:
            raise SystemExit(
                f"Expected to update one transcription row, updated {result.rowcount}."
            )

        if selected_track_id is not None:
            connection.execute(
                text(
                    """
                    UPDATE instrument_tracks
                    SET tab_json = NULL,
                        notation_json = NULL
                    WHERE id = :track_id
                      AND transcription_id = :transcription_id
                    """
                ),
                {
                    "track_id": selected_track_id,
                    "transcription_id": prod.config.transcription_id,
                },
            )
        elif selected_instrument:
            connection.execute(
                text(
                    """
                    UPDATE instrument_tracks
                    SET tab_json = NULL,
                        notation_json = NULL
                    WHERE transcription_id = :transcription_id
                      AND instrument_type = :instrument_type
                    """
                ),
                {
                    "transcription_id": prod.config.transcription_id,
                    "instrument_type": selected_instrument,
                },
            )


def verify_cleanup(prod_config: EnvironmentConfig) -> EnvironmentPayload:
    refreshed = fetch_environment(prod_config)
    stale_values = stale_artifact_values(refreshed)
    if stale_values:
        raise SystemExit(
            "Cleanup verification failed; stale artifact values are still present:\n"
            + json.dumps(stale_values, indent=2, sort_keys=True, default=str)
        )
    print("Cleanup verification passed: prod generated artifact fields are clear.")
    return refreshed


def trigger_and_poll_regeneration(prod_config: EnvironmentConfig, poll_seconds: int, poll_interval: int) -> EnvironmentPayload:
    with httpx.Client(timeout=30.0) as client:
        response = post_json(client, prod_config, "/generate-tabs", {})
    print("\n=== Regeneration Trigger Response ===")
    print(json.dumps(response, indent=2, sort_keys=True, default=str))

    deadline = time.monotonic() + max(0, poll_seconds)
    last_payload: EnvironmentPayload | None = None
    while time.monotonic() <= deadline:
        last_payload = fetch_environment(prod_config)
        status = (
            last_payload.status.get("tab_generation_status")
            or last_payload.result.get("tab_generation_status")
            or "unknown"
        )
        processing = last_payload.status.get("status") or last_payload.result.get("processing_status")
        print(f"poll: status={processing!r} tab_generation_status={status!r}")
        if status in {"completed", "failed"}:
            break
        time.sleep(max(1, poll_interval))

    if last_payload is None:
        last_payload = fetch_environment(prod_config)

    print_summary_section("final prod", comparison_summary(comparison_snapshot(last_payload)))
    return last_payload


def main() -> int:
    args = parse_args()
    local_config, prod_config = load_config(args)

    print(
        "Mode: APPLY" if args.apply else "Mode: DRY-RUN / compare-only",
        f"(local_id={local_config.transcription_id}, prod_id={prod_config.transcription_id})",
    )

    local_payload = fetch_environment(local_config)
    prod_payload = fetch_environment(prod_config)
    print_comparison(
        local_payload,
        prod_payload,
        write_debug_payload_files=args.write_debug_payloads,
        debug_dir=args.debug_dir,
    )

    prod_stem = str(
        prod_payload.result.get("selected_stem")
        or prod_payload.status.get("selected_stem")
        or "other"
    ).strip().lower()
    if prod_stem not in TAB_CAPABLE_STEMS:
        print(
            f"\nProd stem is {prod_stem!r}, not tab-capable. "
            "Stopping before cleanup/regeneration."
        )
        return 0

    if prod_is_processing(prod_payload):
        print("\nProd is currently processing or queued for Modal work. Stopping before mutation.")
        return 1

    stale_values = stale_artifact_values(prod_payload)
    print_would_clear(prod_payload, stale_values)

    if not stale_values and not args.force_regenerate:
        print(
            "\nNo stale generated tab artifacts found. "
            "Skipping cleanup and regeneration. Use --force-regenerate to override."
        )
        return 0

    if not args.apply:
        print(
            "\nDry-run complete. No DB fields were cleared and regeneration was not triggered. "
            "Run again with --apply to mutate prod."
        )
        return 0

    database_url = require_prod_database_url()
    clear_prod_artifacts(database_url, prod_payload)
    verify_cleanup(prod_config)
    trigger_and_poll_regeneration(prod_config, args.poll_seconds, args.poll_interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
