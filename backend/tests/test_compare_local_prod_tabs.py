import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "compare_local_prod_tabs.py"
SPEC = importlib.util.spec_from_file_location("compare_local_prod_tabs", SCRIPT_PATH)
compare_script = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(compare_script)


def make_payload(
    *,
    name: str,
    selected_stem: str = "bass",
    status: str = "completed",
    notes: list[dict] | None = None,
    tabs: list[dict] | None = None,
    track_notes: list[dict] | None = None,
):
    notes = notes or []
    tabs = tabs or []
    track_notes = track_notes if track_notes is not None else notes
    return compare_script.EnvironmentPayload(
        config=compare_script.EnvironmentConfig(
            name=name,
            api_url=f"https://{name}.example.test",
            transcription_id=1,
            auth_token="token",
        ),
        status={"status": status, "selected_stem": selected_stem},
        result={
            "selected_stem": selected_stem,
            "processing_status": status,
            "tab_generation_status": "completed",
            "notes_data": json.dumps({"notes": notes, "total_notes_detected": len(notes)}),
            "tablature_data": json.dumps({"tablature": tabs}),
        },
        tracks=[
            {
                "id": 10,
                "instrument_type": "bass" if selected_stem == "bass" else "guitar",
                "processing_status": status,
                "notes_json": json.dumps({"notes": track_notes}),
            }
        ],
        selected_track={
            "id": 10,
            "instrument_type": "bass" if selected_stem == "bass" else "guitar",
            "processing_status": status,
            "notes_json": json.dumps({"notes": track_notes}),
            "confidence_score": 80,
        },
    )


def test_extract_event_list_supports_direct_lists_and_common_object_shapes():
    event = {"string": 4, "fret": 10}

    assert compare_script.extract_event_list([event]) == [event]
    assert compare_script.extract_event_list({"tablature": [event]}) == [event]
    assert compare_script.extract_event_list({"tabs": [event]}) == [event]
    assert compare_script.extract_event_list({"events": [event]}) == [event]
    assert compare_script.extract_event_list({"notes_data": {"notes": [event]}}) == [event]
    assert compare_script.extract_event_list({"unknown": [event]}) == []


def test_event_confidence_stats_handles_empty_and_missing_confidence():
    assert compare_script.event_confidence_stats([]) == {
        "count": 0,
        "avg_confidence": None,
        "min_confidence": None,
        "max_confidence": None,
    }

    stats = compare_script.event_confidence_stats(
        [
            {"confidence": 0.25},
            {"pitch": 64},
            {"confidence": 0.75},
            {"confidence": "0.95"},
        ]
    )

    assert stats == {
        "count": 4,
        "avg_confidence": 0.5,
        "min_confidence": 0.25,
        "max_confidence": 0.75,
    }


def test_preview_events_truncates_and_keeps_stable_fields_only():
    events = [
        {"string": 1, "fret": 2, "startTime": 0.1, "duration": 0.2, "confidence": 0.9, "pitch": 64},
        {"string": 2, "fret": 3, "startTime": 0.3, "duration": 0.4, "confidence": 0.8, "pitch": 65},
        {"string": 3, "fret": 4, "startTime": 0.5, "duration": 0.6, "confidence": 0.7, "pitch": 66},
    ]

    assert compare_script.preview_events(events, limit=2) == [
        {"string": 1, "fret": 2, "startTime": 0.1, "duration": 0.2, "confidence": 0.9},
        {"string": 2, "fret": 3, "startTime": 0.3, "duration": 0.4, "confidence": 0.8},
    ]


def test_count_differing_events_is_position_aware_and_counts_length_mismatch():
    local = [{"id": 1}, {"id": 2}, {"id": 3}]
    prod = [{"id": 1}, {"id": 3}]

    assert compare_script.count_differing_events(local, prod) == 2


def test_print_comparison_prints_summary_and_differences_without_raw_array_dump(capsys):
    local = make_payload(
        name="local",
        notes=[
            {"string": 4, "fret": 10, "startTime": 0.1, "duration": 0.2, "confidence": 0.6},
            {"string": 3, "fret": 8, "startTime": 0.3, "duration": 0.2, "confidence": 0.8},
            {"string": 2, "fret": 7, "startTime": 0.5, "duration": 0.2, "confidence": 0.7},
            {"string": 1, "fret": 5, "startTime": 0.7, "duration": 0.2, "confidence": 0.9},
        ],
        tabs=[
            {"string": 4, "fret": 10, "startTime": 0.1, "duration": 0.2, "confidence": 0.6},
            {"string": 3, "fret": 8, "startTime": 0.3, "duration": 0.2, "confidence": 0.8},
        ],
    )
    prod = make_payload(
        name="prod",
        selected_stem="other",
        notes=[
            {"string": 4, "fret": 10, "startTime": 0.1, "duration": 0.2, "confidence": 0.6},
            {"string": 3, "fret": 9, "startTime": 0.3, "duration": 0.2, "confidence": 0.5},
        ],
        tabs=[
            {"string": 4, "fret": 10, "startTime": 0.1, "duration": 0.2, "confidence": 0.6},
        ],
    )

    compare_script.print_comparison(local, prod)

    output = capsys.readouterr().out
    assert "=== LOCAL ===" in output
    assert "=== PROD ===" in output
    assert "notes_count: 4" in output
    assert "tablature_events_count: 2" in output
    assert "avg_confidence: 0.75" in output
    assert "notes_data length differs: local=4 prod=2" in output
    assert "notes_data differing event positions: 3" in output
    assert "tablature_data length differs: local=2 prod=1" in output
    assert "tablature_data differing event positions: 1" in output
    assert "selected_stem differs: local='bass' prod='other'" in output
    assert "=== Comparison Snapshot JSON ===" not in output
    assert '\\"notes\\"' not in output
    assert "total_notes_detected" not in output
    assert "fret': 5" not in output


def test_debug_payload_writing_creates_files_and_preserves_full_content(tmp_path, capsys):
    local = make_payload(
        name="local",
        notes=[{"string": 4, "fret": 10, "confidence": 0.6}],
        tabs=[{"string": 4, "fret": 10, "confidence": 0.6}],
    )
    prod = make_payload(
        name="prod",
        notes=[{"string": 3, "fret": 8, "confidence": 0.8}],
        tabs=[{"string": 3, "fret": 8, "confidence": 0.8}],
    )

    compare_script.print_comparison(
        local,
        prod,
        write_debug_payload_files=True,
        debug_dir=tmp_path,
    )

    output = capsys.readouterr().out
    local_path = tmp_path / "local_tabs.json"
    prod_path = tmp_path / "prod_tabs.json"
    assert "Saved:" in output
    assert str(local_path) in output
    assert str(prod_path) in output
    assert local_path.exists()
    assert prod_path.exists()

    local_payload = json.loads(local_path.read_text(encoding="utf-8"))
    prod_payload = json.loads(prod_path.read_text(encoding="utf-8"))
    assert local_payload["notes_data"]["notes"][0]["fret"] == 10
    assert prod_payload["notes_data"]["notes"][0]["fret"] == 8
