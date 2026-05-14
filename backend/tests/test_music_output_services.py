import json
from unittest.mock import Mock, patch

from app import models
from app.services import audio, chord_chart, midi, tablature
from app.tasks import cleanup_transient_audio_files


def test_chord_chart_generation_handles_muted_strings():
    chord_data = {
        "chords": [
            {"chord": "C:maj", "onset": 0, "offset": 1.5, "confidence": 0.9}
        ]
    }

    chart_json = chord_chart.chord_data_to_chord_chart_json(json.dumps(chord_data))
    charts = json.loads(chart_json)

    assert len(charts) == 1
    assert charts[0]["chord_symbol"] == "C:maj"
    assert "<svg" in charts[0]["svg"]


def test_tablature_accepts_enhanced_pitch_info_shape():
    notes_data = {
        "pitch_info": [
            {"onset": 0.0, "offset": 0.5, "pitch": 64, "velocity": 80, "confidence": 0.95}
        ],
        "rhythm_analysis": {"total_duration": 0.5},
    }

    tab = tablature.notes_to_tablature(notes_data)

    assert len(tab["tablature"]) == 1
    assert tab["tablature"][0]["fret"] >= 0


def test_midi_generation_accepts_enhanced_pitch_info_shape(tmp_path):
    notes_data = {
        "pitch_info": [
            {"onset": 0.0, "offset": 0.5, "pitch": 64, "velocity": 80, "confidence": 0.95}
        ],
        "rhythm_analysis": {"total_duration": 0.5},
    }
    output_path = tmp_path / "output.mid"

    result = midi.notes_to_midi(notes_data, str(output_path))

    assert result == str(output_path)
    assert output_path.exists()
    assert output_path.stat().st_size > 0


def test_basic_pitch_csv_note_events_are_normalized(tmp_path):
    csv_path = tmp_path / "input_basic_pitch.csv"
    csv_path.write_text(
        "start_time_s,end_time_s,pitch_midi,amplitude\n"
        "0.0,0.5,64,0.75\n",
        encoding="utf-8",
    )

    notes = audio._load_basic_pitch_note_events_csv(csv_path)

    assert notes == [
        {
            "onset": 0.0,
            "offset": 0.5,
            "pitch": 64,
            "velocity": 95,
            "confidence": 0.75,
        }
    ]


def test_source_separation_prefers_demucs_guitar_stem(tmp_path):
    input_path = tmp_path / "song.wav"
    input_path.write_bytes(b"audio")
    output_dir = tmp_path / "separated"
    guitar_path = output_dir / audio.DEMUCS_GUITAR_MODEL / "song" / "guitar.wav"

    def fake_run(cmd, capture_output, text):
        guitar_path.parent.mkdir(parents=True, exist_ok=True)
        guitar_path.write_bytes(b"guitar")
        return Mock(returncode=0, stderr="", stdout="")

    with patch("app.services.audio.importlib.util.find_spec", return_value=object()):
        with patch("app.services.audio.subprocess.run", side_effect=fake_run) as run_mock:
            result = audio.separate_sources(str(input_path), str(output_dir))

    assert result == str(guitar_path)
    assert audio.DEMUCS_GUITAR_MODEL in run_mock.call_args.args[0]


def test_source_separation_falls_back_to_accompaniment(tmp_path):
    input_path = tmp_path / "song.wav"
    input_path.write_bytes(b"audio")
    output_dir = tmp_path / "separated"
    accompaniment_path = output_dir / audio.DEMUCS_FALLBACK_MODEL / "song" / "accompaniment.wav"

    def fake_run(cmd, capture_output, text):
        if audio.DEMUCS_GUITAR_MODEL in cmd:
            return Mock(returncode=1, stderr="model failed", stdout="")
        accompaniment_path.parent.mkdir(parents=True, exist_ok=True)
        accompaniment_path.write_bytes(b"accompaniment")
        return Mock(returncode=0, stderr="", stdout="")

    with patch("app.services.audio.importlib.util.find_spec", return_value=object()):
        with patch("app.services.audio.subprocess.run", side_effect=fake_run) as run_mock:
            result = audio.separate_sources(str(input_path), str(output_dir))

    assert result == str(accompaniment_path)
    assert run_mock.call_count == 2


def test_cleanup_transient_audio_files_deletes_audio_artifacts_and_clears_paths(tmp_path):
    original_path = tmp_path / "upload.wav"
    preprocessed_path = tmp_path / "upload_preprocessed.wav"
    separated_path = tmp_path / "separated.wav"
    midi_path = tmp_path / "transcription.mid"

    for path in [original_path, preprocessed_path, separated_path, midi_path]:
        path.write_bytes(b"data")

    transcription = models.Transcription(
        id=42,
        title="Cleanup test",
        audio_file_path=str(original_path),
        preprocessed_audio_file_path=str(preprocessed_path),
        separated_audio_file_path=str(separated_path),
        midi_file_path=str(midi_path),
    )
    db_session = Mock()

    cleanup_transient_audio_files(transcription, db_session)

    assert not original_path.exists()
    assert not preprocessed_path.exists()
    assert not separated_path.exists()
    assert midi_path.exists()
    assert transcription.audio_file_path is None
    assert transcription.preprocessed_audio_file_path is None
    assert transcription.separated_audio_file_path is None
    assert transcription.midi_file_path == str(midi_path)
    db_session.add.assert_called_once_with(transcription)
    db_session.commit.assert_called_once()
