import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.services import audio, chord_chart, midi, tablature
from app.tasks import (
    cleanup_transient_audio_files,
    copy_and_persist_instrument_tracks,
    estimate_stem_confidence,
    generate_single_track_transcription_output,
    generate_tab_from_separated_stem,
    generate_track_transcription_outputs,
    process_audio_transcription,
    persist_selected_stem_track,
    reprocess_instrument_track,
    select_analysis_source,
)


def create_test_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return testing_session()


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


def test_tablature_supports_standard_bass_tuning():
    notes_data = {
        "notes": [
            {"onset": 0.0, "offset": 0.5, "pitch": 28, "velocity": 80, "confidence": 0.95},
            {"onset": 0.5, "offset": 1.0, "pitch": 43, "velocity": 76, "confidence": 0.9},
        ],
    }

    tab = tablature.notes_to_tablature(notes_data, instrument_type="bass")
    ascii_tab = tablature.tablature_to_ascii_tab(tab)

    assert tab["instrument"] == "bass"
    assert tab["tuning"] == [28, 33, 38, 43]
    assert len(tab["tablature"]) == 2
    assert {note["string"] for note in tab["tablature"]}.issubset({1, 2, 3, 4})
    assert ascii_tab.splitlines()[0].startswith("G|")
    assert len(ascii_tab.splitlines()) == 4


def test_midi_generation_accepts_enhanced_pitch_info_shape(tmp_path):
    notes_data = {
        "pitch_info": [
            {"onset": 0.0, "offset": 0.5, "pitch": 64, "velocity": 80, "confidence": 0.95}
        ],
        "rhythm_analysis": {"total_duration": 0.5},
    }
    output_path = tmp_path / "output.mid"

    result = midi.notes_to_midi(notes_data, str(output_path))

    assert result == output_path.as_posix()
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


def test_analyze_drum_rhythm_returns_hit_timing_and_confidence(tmp_path):
    drum_path = tmp_path / "drums.wav"
    drum_path.write_bytes(b"drums")

    with patch("app.services.audio.librosa.load", return_value=(audio.np.array([0.0, 0.4, -0.2, 0.1]), 22050)):
        with patch("app.services.audio.librosa.get_duration", return_value=1.25):
            with patch(
                "app.services.audio.librosa.onset.onset_strength",
                return_value=audio.np.array([0.1, 0.8, 0.2, 0.4]),
            ):
                with patch(
                    "app.services.audio.librosa.onset.onset_detect",
                    return_value=audio.np.array([1, 3]),
                ):
                    with patch(
                        "app.services.audio.librosa.frames_to_time",
                        return_value=audio.np.array([0.2, 0.9]),
                    ):
                        result = audio.analyze_drum_rhythm(str(drum_path))

    assert result["total_hits_detected"] == 2
    assert result["drum_hits"][0]["onset"] == 0.2
    assert result["drum_hits"][0]["confidence"] == 1.0
    assert result["rhythm_analysis"]["source"] == "drum_stem_onset_detection"


def test_source_separation_prefers_demucs_other_stem(tmp_path):
    input_path = tmp_path / "song.wav"
    input_path.write_bytes(b"audio")
    output_dir = tmp_path / "separated"
    other_path = output_dir / audio.DEMUCS_GUITAR_MODEL / "song" / "other.wav"

    def fake_run(cmd, capture_output, text, **kwargs):
        other_path.parent.mkdir(parents=True, exist_ok=True)
        other_path.write_bytes(b"other")
        return Mock(returncode=0, stderr="", stdout="")

    with patch("app.services.audio.importlib.util.find_spec", return_value=object()):
        with patch("app.services.audio.subprocess.run", side_effect=fake_run) as run_mock:
            result = audio.separate_sources(str(input_path), str(output_dir))

    assert result == other_path.as_posix()
    assert audio.DEMUCS_GUITAR_MODEL in run_mock.call_args.args[0]


def test_multi_source_separation_returns_available_six_stem_outputs(tmp_path):
    input_path = tmp_path / "song.wav"
    input_path.write_bytes(b"audio")
    output_dir = tmp_path / "separated"
    stem_dir = output_dir / audio.DEMUCS_GUITAR_MODEL / "song"

    def fake_run(cmd, capture_output, text, **kwargs):
        stem_dir.mkdir(parents=True, exist_ok=True)
        for stem_name in audio.DEMUCS_MULTI_STEMS.values():
            (stem_dir / f"{stem_name}.wav").write_bytes(stem_name.encode("utf-8"))
        return Mock(returncode=0, stderr="", stdout="")

    with patch("app.services.audio.importlib.util.find_spec", return_value=object()):
        with patch("app.services.audio.subprocess.run", side_effect=fake_run):
            result = audio.separate_sources_multi(str(input_path), str(output_dir))

    assert set(result) == {"bass", "drums", "vocals", "other"}
    assert result["other"] == (stem_dir / "other.wav").as_posix()


def test_multi_source_separation_skips_missing_optional_six_stems(tmp_path):
    input_path = tmp_path / "song.wav"
    input_path.write_bytes(b"audio")
    output_dir = tmp_path / "separated"
    stem_dir = output_dir / audio.DEMUCS_GUITAR_MODEL / "song"

    def fake_run(cmd, capture_output, text, **kwargs):
        stem_dir.mkdir(parents=True, exist_ok=True)
        (stem_dir / "other.wav").write_bytes(b"other")
        (stem_dir / "bass.wav").write_bytes(b"bass")
        return Mock(returncode=0, stderr="", stdout="")

    with patch("app.services.audio.importlib.util.find_spec", return_value=object()):
        with patch("app.services.audio.subprocess.run", side_effect=fake_run):
            result = audio.separate_sources_multi(str(input_path), str(output_dir))

    assert result == {
        "other": (stem_dir / "other.wav").as_posix(),
        "bass": (stem_dir / "bass.wav").as_posix(),
    }


def test_source_separation_falls_back_to_accompaniment(tmp_path):
    input_path = tmp_path / "song.wav"
    input_path.write_bytes(b"audio")
    output_dir = tmp_path / "separated"
    accompaniment_path = output_dir / audio.DEMUCS_FALLBACK_MODEL / "song" / "accompaniment.wav"

    def fake_run(cmd, capture_output, text, **kwargs):
        if "--two-stems" not in cmd:
            return Mock(returncode=1, stderr="model failed", stdout="")
        accompaniment_path.parent.mkdir(parents=True, exist_ok=True)
        accompaniment_path.write_bytes(b"accompaniment")
        return Mock(returncode=0, stderr="", stdout="")

    with patch("app.services.audio.importlib.util.find_spec", return_value=object()):
        with patch("app.services.audio.subprocess.run", side_effect=fake_run) as run_mock:
            result = audio.separate_sources(str(input_path), str(output_dir))

    assert result == accompaniment_path.as_posix()
    assert run_mock.call_count == 2


def test_multi_source_separation_falls_back_to_vocals_and_accompaniment(tmp_path):
    input_path = tmp_path / "song.wav"
    input_path.write_bytes(b"audio")
    output_dir = tmp_path / "separated"
    fallback_dir = output_dir / audio.DEMUCS_FALLBACK_MODEL / "song"
    vocals_path = fallback_dir / "vocals.wav"
    accompaniment_path = fallback_dir / "accompaniment.wav"

    def fake_run(cmd, capture_output, text, **kwargs):
        if "--two-stems" not in cmd:
            return Mock(returncode=1, stderr="model failed", stdout="")
        fallback_dir.mkdir(parents=True, exist_ok=True)
        vocals_path.write_bytes(b"vocals")
        accompaniment_path.write_bytes(b"accompaniment")
        return Mock(returncode=0, stderr="", stdout="")

    with patch("app.services.audio.importlib.util.find_spec", return_value=object()):
        with patch("app.services.audio.subprocess.run", side_effect=fake_run) as run_mock:
            result = audio.separate_sources_multi(str(input_path), str(output_dir))

    assert result == {
        "vocals": vocals_path.as_posix(),
        "other": accompaniment_path.as_posix(),
    }
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
    assert separated_path.exists()
    assert midi_path.exists()
    assert transcription.audio_file_path is None
    assert transcription.preprocessed_audio_file_path is None
    assert transcription.separated_audio_file_path == str(separated_path)
    assert transcription.midi_file_path == str(midi_path)
    db_session.add.assert_called_once_with(transcription)
    db_session.commit.assert_called_once()


def test_copy_and_persist_instrument_tracks_creates_rows_and_retains_stems(tmp_path):
    session = create_test_session()
    try:
        transcription = models.Transcription(
            title="Track persistence",
            user_id=1,
            is_processed=False,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        guitar_source = tmp_path / "guitar.wav"
        bass_source = tmp_path / "bass.wav"
        guitar_source.write_bytes(b"guitar")
        bass_source.write_bytes(b"bass")
        upload_dir = tmp_path / "uploads"

        with patch("app.tasks.settings") as settings_mock:
            settings_mock.UPLOAD_DIR = str(upload_dir)
            with patch("app.tasks.estimate_stem_confidence", return_value=90):
                persisted = copy_and_persist_instrument_tracks(
                    transcription,
                    {
                        "guitar": str(guitar_source),
                        "bass": str(bass_source),
                    },
                    session,
                )

        tracks = (
            session.query(models.InstrumentTrack)
            .filter(models.InstrumentTrack.transcription_id == transcription.id)
            .order_by(models.InstrumentTrack.instrument_type.asc())
            .all()
        )

        assert set(persisted) == {"guitar", "bass"}
        assert [track.instrument_type for track in tracks] == ["bass", "guitar"]
        assert all(track.processing_status == "completed" for track in tracks)
        assert all(track.confidence_score == 90 for track in tracks)
        assert all(track.stem_audio_path and Path(track.stem_audio_path).exists() for track in tracks)
    finally:
        session.close()


def test_persist_selected_stem_track_uses_local_path_when_cloudinary_upload_fails(tmp_path):
    session = create_test_session()
    try:
        transcription = models.Transcription(
            title="Local stem fallback",
            user_id=1,
            selected_stem="other",
            separated_audio_url="https://res.cloudinary.com/demo/video/upload/old.wav",
            separated_audio_public_id="old-public-id",
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        source_path = tmp_path / "other.wav"
        source_path.write_bytes(b"stem")
        upload_dir = tmp_path / "uploads"

        with patch("app.tasks.settings") as settings_mock:
            settings_mock.UPLOAD_DIR = str(upload_dir)
            with patch("app.tasks.estimate_stem_confidence", return_value=90):
                with patch(
                    "app.tasks.upload_transcription_artifact",
                    side_effect=RuntimeError("cloudinary unavailable"),
                ):
                    track = persist_selected_stem_track(
                        transcription,
                        "other",
                        str(source_path),
                        session,
                    )

        session.refresh(transcription)
        assert transcription.separated_audio_url is None
        assert transcription.separated_audio_public_id is None
        assert transcription.separated_audio_file_path
        assert Path(transcription.separated_audio_file_path).exists()
        assert track.stem_audio_path == transcription.separated_audio_file_path
    finally:
        session.close()


def test_persist_selected_stem_track_requires_secure_url_before_saving_cloudinary_url(tmp_path):
    session = create_test_session()
    try:
        transcription = models.Transcription(
            title="Missing secure url",
            user_id=1,
            selected_stem="other",
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        source_path = tmp_path / "other.wav"
        source_path.write_bytes(b"stem")
        upload_dir = tmp_path / "uploads"

        with patch("app.tasks.settings") as settings_mock:
            settings_mock.UPLOAD_DIR = str(upload_dir)
            with patch("app.tasks.estimate_stem_confidence", return_value=90):
                with patch(
                    "app.tasks.upload_transcription_artifact",
                    return_value={"secure_url": None, "public_id": "stem-public-id"},
                ):
                    persist_selected_stem_track(
                        transcription,
                        "other",
                        str(source_path),
                        session,
                    )

        session.refresh(transcription)
        assert transcription.separated_audio_url is None
        assert transcription.separated_audio_public_id is None
        assert transcription.separated_audio_file_path
    finally:
        session.close()


def test_generate_track_transcription_outputs_stores_guitar_bass_and_piano_data(tmp_path):
    session = create_test_session()
    try:
        transcription = models.Transcription(
            title="Track analysis",
            user_id=1,
            is_processed=False,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        guitar_stem = tmp_path / "guitar.wav"
        bass_stem = tmp_path / "bass.wav"
        piano_stem = tmp_path / "piano.wav"
        drums_stem = tmp_path / "drums.wav"
        guitar_stem.write_bytes(b"guitar")
        bass_stem.write_bytes(b"bass")
        piano_stem.write_bytes(b"piano")
        drums_stem.write_bytes(b"drums")

        tracks = [
            models.InstrumentTrack(
                transcription_id=transcription.id,
                instrument_type="guitar",
                display_name="Guitar",
                stem_audio_path=str(guitar_stem),
                processing_status="completed",
            ),
            models.InstrumentTrack(
                transcription_id=transcription.id,
                instrument_type="bass",
                display_name="Bass",
                stem_audio_path=str(bass_stem),
                processing_status="completed",
            ),
            models.InstrumentTrack(
                transcription_id=transcription.id,
                instrument_type="drums",
                display_name="Drums",
                stem_audio_path=str(drums_stem),
                processing_status="completed",
            ),
            models.InstrumentTrack(
                transcription_id=transcription.id,
                instrument_type="piano",
                display_name="Piano",
                stem_audio_path=str(piano_stem),
                processing_status="completed",
            ),
        ]
        session.add_all(tracks)
        session.commit()

        def fake_detect_pitch(stem_path, output_dir, **_kwargs):
            pitch_by_name = {
                "bass.wav": 28,
                "piano.wav": 60,
            }
            pitch = pitch_by_name.get(Path(stem_path).name, 64)
            return {
                "notes": [
                    {"onset": 0.0, "offset": 0.5, "pitch": pitch, "velocity": 90, "confidence": 0.8}
                ]
            }

        with patch("app.tasks.audio.detect_pitch", side_effect=fake_detect_pitch) as pitch_mock:
            with patch(
                "app.tasks.audio.analyze_drum_rhythm",
                return_value={
                    "drum_hits": [
                        {"onset": 0.0, "offset": 0.12, "intensity": 1.0, "confidence": 0.8}
                    ],
                    "total_hits_detected": 1,
                    "rhythm_analysis": {
                        "total_duration": 1.0,
                        "grid_size": 0.125,
                        "source": "drum_stem_onset_detection",
                    },
                },
            ) as drum_mock:
                with patch("app.tasks.midi.notes_to_midi", return_value=str(tmp_path / "guitar.mid")):
                    with patch("app.tasks.midi.midi_to_musicxml", return_value="<score />"):
                        generate_track_transcription_outputs(transcription.id, session)

        refreshed_tracks = {
            track.instrument_type: track
            for track in session.query(models.InstrumentTrack)
            .filter(models.InstrumentTrack.transcription_id == transcription.id)
            .all()
        }
        guitar_track = refreshed_tracks["guitar"]
        bass_track = refreshed_tracks["bass"]
        piano_track = refreshed_tracks["piano"]
        drums_track = refreshed_tracks["drums"]

        assert pitch_mock.call_count == 3
        assert drum_mock.call_args.args[0] == str(drums_stem)
        assert json.loads(guitar_track.notes_json)["notes"][0]["pitch"] == 64
        assert json.loads(guitar_track.tab_json)["instrument"] == "guitar"
        assert guitar_track.notation_json == "<score />"
        assert json.loads(bass_track.notes_json)["notes"][0]["pitch"] == 28
        assert json.loads(bass_track.tab_json)["tuning"] == [28, 33, 38, 43]
        assert bass_track.notation_json == "<score />"
        assert json.loads(piano_track.notes_json)["notes"][0]["pitch"] == 60
        assert piano_track.tab_json is None
        assert piano_track.notation_json == "<score />"
        assert json.loads(drums_track.notes_json)["drum_hits"][0]["confidence"] == 0.8
        assert drums_track.tab_json is None
        assert drums_track.notation_json is None
        assert drums_track.processing_status == "completed"
        assert piano_track.processing_status == "completed"
        assert guitar_track.processing_status == "completed"
        assert bass_track.processing_status == "completed"
    finally:
        session.close()


def test_generate_single_track_transcription_output_reprocesses_only_selected_track(tmp_path):
    session = create_test_session()
    try:
        transcription = models.Transcription(
            title="Selected track analysis",
            user_id=1,
            is_processed=True,
            notes_data='{"notes": [{"pitch": 40}]}',
            tablature_data='{"tablature": []}',
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        guitar_stem = tmp_path / "guitar.wav"
        bass_stem = tmp_path / "bass.wav"
        guitar_stem.write_bytes(b"guitar")
        bass_stem.write_bytes(b"bass")

        guitar_track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="guitar",
            display_name="Guitar",
            stem_audio_path=str(guitar_stem),
            notes_json='{"notes": [{"pitch": 40}]}',
            tab_json='{"old": true}',
            processing_status="completed",
        )
        bass_track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="bass",
            display_name="Bass",
            stem_audio_path=str(bass_stem),
            notes_json='{"notes": [{"pitch": 28}]}',
            tab_json='{"old": true}',
            processing_status="completed",
        )
        session.add_all([guitar_track, bass_track])
        session.commit()

        with patch(
            "app.tasks.audio.detect_pitch",
            return_value={
                "notes": [
                    {"onset": 0.0, "offset": 0.5, "pitch": 64, "velocity": 90, "confidence": 0.8}
                ]
            },
        ) as pitch_mock:
            with patch("app.tasks.midi.notes_to_midi", return_value=str(tmp_path / "guitar.mid")):
                with patch("app.tasks.midi.midi_to_musicxml", return_value="<score />"):
                    generate_single_track_transcription_output(
                        guitar_track,
                        session,
                        clear_existing=True,
                    )

        session.refresh(guitar_track)
        session.refresh(bass_track)
        session.refresh(transcription)

        assert pitch_mock.call_args.args[0] == str(guitar_stem)
        assert json.loads(guitar_track.notes_json)["notes"][0]["pitch"] == 64
        assert json.loads(guitar_track.tab_json)["instrument"] == "guitar"
        assert guitar_track.notation_json == "<score />"
        assert guitar_track.processing_status == "completed"
        assert json.loads(bass_track.notes_json)["notes"][0]["pitch"] == 28
        assert bass_track.tab_json == '{"old": true}'
        assert json.loads(transcription.notes_data)["notes"][0]["pitch"] == 40
    finally:
        session.close()


def test_generate_single_track_transcription_output_failure_clears_stale_outputs(tmp_path):
    session = create_test_session()
    try:
        transcription = models.Transcription(
            title="Failed selected track analysis",
            user_id=1,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        guitar_stem = tmp_path / "guitar.wav"
        guitar_stem.write_bytes(b"guitar")
        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="guitar",
            display_name="Guitar",
            stem_audio_path=str(guitar_stem),
            notes_json='{"notes": [{"pitch": 40}]}',
            tab_json='{"old": true}',
            notation_json="<old />",
            processing_status="completed",
        )
        session.add(track)
        session.commit()

        with patch("app.tasks.audio.detect_pitch", side_effect=RuntimeError("pitch failed")):
            generate_single_track_transcription_output(
                track,
                session,
                clear_existing=True,
            )

        session.refresh(track)

        assert track.processing_status == "failed"
        assert track.confidence_notes == "pitch failed"
        assert json.loads(track.notes_json)["error"] == "pitch failed"
        assert track.tab_json is None
        assert track.notation_json is None
    finally:
        session.close()


def test_reprocess_instrument_track_task_uses_selected_track_stem(tmp_path):
    session = create_test_session()
    try:
        transcription = models.Transcription(
            title="Task selected track",
            user_id=1,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        bass_stem = tmp_path / "bass.wav"
        bass_stem.write_bytes(b"bass")
        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="bass",
            display_name="Bass",
            stem_audio_path=str(bass_stem),
            processing_status="processing",
        )
        session.add(track)
        session.commit()
        track_id = track.id

        with patch("app.tasks.get_db_session", return_value=session):
            with patch(
                "app.tasks.audio.detect_pitch",
                return_value={
                    "notes": [
                        {"onset": 0.0, "offset": 0.5, "pitch": 28, "velocity": 90, "confidence": 0.8}
                    ]
                },
            ) as pitch_mock:
                with patch("app.tasks.midi.notes_to_midi", return_value=str(tmp_path / "bass.mid")):
                    with patch("app.tasks.midi.midi_to_musicxml", return_value="<score />"):
                        result = reprocess_instrument_track.run(track_id)

        refreshed = session.query(models.InstrumentTrack).filter(
            models.InstrumentTrack.id == track_id
        ).first()

        assert result["status"] == "completed"
        assert pitch_mock.call_args.args[0] == str(bass_stem)
        assert json.loads(refreshed.tab_json)["instrument"] == "bass"
        assert refreshed.notation_json == "<score />"
    finally:
        session.close()


def test_reprocess_instrument_track_task_uses_selected_drum_stem(tmp_path):
    session = create_test_session()
    try:
        transcription = models.Transcription(
            title="Task selected drums",
            user_id=1,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        drum_stem = tmp_path / "drums.wav"
        drum_stem.write_bytes(b"drums")
        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="drums",
            display_name="Drums",
            stem_audio_path=str(drum_stem),
            processing_status="processing",
        )
        session.add(track)
        session.commit()
        track_id = track.id

        drum_result = {
            "drum_hits": [
                {"onset": 0.0, "offset": 0.12, "intensity": 0.9, "confidence": 0.75}
            ],
            "total_hits_detected": 1,
            "rhythm_analysis": {
                "total_duration": 1.0,
                "grid_size": 0.125,
                "source": "drum_stem_onset_detection",
            },
        }

        with patch("app.tasks.get_db_session", return_value=session):
            with patch("app.tasks.audio.analyze_drum_rhythm", return_value=drum_result) as drum_mock:
                result = reprocess_instrument_track.run(track_id)

        refreshed = session.query(models.InstrumentTrack).filter(
            models.InstrumentTrack.id == track_id
        ).first()

        assert result["status"] == "completed"
        assert drum_mock.call_args.args[0] == str(drum_stem)
        assert json.loads(refreshed.notes_json)["drum_hits"][0]["confidence"] == 0.75
        assert refreshed.tab_json is None
        assert refreshed.notation_json is None
        assert refreshed.confidence_score == 75
    finally:
        session.close()


def test_reprocess_instrument_track_task_uses_selected_piano_stem(tmp_path):
    session = create_test_session()
    try:
        transcription = models.Transcription(
            title="Task selected piano",
            user_id=1,
            is_processed=True,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        piano_stem = tmp_path / "piano.wav"
        piano_stem.write_bytes(b"piano")
        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="piano",
            display_name="Piano",
            stem_audio_path=str(piano_stem),
            processing_status="processing",
        )
        session.add(track)
        session.commit()
        track_id = track.id

        with patch("app.tasks.get_db_session", return_value=session):
            with patch(
                "app.tasks.audio.detect_pitch",
                return_value={
                    "notes": [
                        {"onset": 0.0, "offset": 0.5, "pitch": 60, "velocity": 90, "confidence": 0.8}
                    ]
                },
            ) as pitch_mock:
                with patch("app.tasks.midi.notes_to_midi", return_value=str(tmp_path / "piano.mid")):
                    with patch("app.tasks.midi.midi_to_musicxml", return_value="<score />"):
                        result = reprocess_instrument_track.run(track_id)

        refreshed = session.query(models.InstrumentTrack).filter(
            models.InstrumentTrack.id == track_id
        ).first()

        assert result["status"] == "completed"
        assert pitch_mock.call_args.args[0] == str(piano_stem)
        assert json.loads(refreshed.notes_json)["notes"][0]["pitch"] == 60
        assert refreshed.tab_json is None
        assert refreshed.notation_json == "<score />"
    finally:
        session.close()


def test_select_analysis_source_prefers_other_then_default_stems():
    assert select_analysis_source({"other": "other.wav"}, "mix.wav") == "other.wav"
    assert select_analysis_source({"bass": "bass.wav"}, "mix.wav") == "bass.wav"
    assert select_analysis_source({}, "mix.wav") == "mix.wav"


def test_estimate_stem_confidence_uses_non_empty_duration(tmp_path):
    stem_path = tmp_path / "guitar.wav"
    stem_path.write_bytes(b"audio")

    with patch("app.tasks.audio.librosa.get_duration", return_value=2.5):
        assert estimate_stem_confidence(str(stem_path)) == 90


def test_process_audio_transcription_persists_selected_other_stem_and_analyzes_as_guitar(tmp_path):
    session = create_test_session()
    try:
        upload_path = tmp_path / "upload.wav"
        preprocessed_path = tmp_path / "upload_preprocessed.wav"
        other_stem = tmp_path / "other.wav"
        bass_stem = tmp_path / "bass.wav"
        upload_path.write_bytes(b"upload")
        preprocessed_path.write_bytes(b"preprocessed")
        other_stem.write_bytes(b"other")
        bass_stem.write_bytes(b"bass")

        transcription = models.Transcription(
            title="Task flow",
            audio_file_path=str(upload_path),
            selected_stem="other",
            user_id=1,
            is_processed=False,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)
        transcription_id = transcription.id
        upload_dir = tmp_path / "uploads"

        pitch_mock = Mock(return_value={
            "notes": [
                {"onset": 0.0, "offset": 0.5, "pitch": 64, "velocity": 90, "confidence": 0.8}
            ]
        })

        with patch("app.tasks.get_db_session", return_value=session):
            with patch("app.tasks.settings") as settings_mock:
                settings_mock.UPLOAD_DIR = str(upload_dir)
                with patch("app.tasks.audio.preprocess_audio", return_value=str(preprocessed_path)):
                    with patch(
                        "app.tasks.audio.separate_selected_stem",
                        return_value=str(other_stem),
                    ):
                        with patch("app.tasks.audio.detect_pitch", pitch_mock):
                            with patch("app.tasks.midi.save_midi_from_transcription", return_value=str(tmp_path / "out.mid")):
                                with patch("app.tasks.midi.midi_to_musicxml", return_value="<score />"):
                                    with patch("app.tasks.tablature.save_tablature_from_transcription", return_value=str(tmp_path / "tab.json")):
                                        with patch("app.tasks.tablature.notes_to_tablature", return_value={"tablature": []}):
                                            with patch("app.tasks.audio.detect_beat_and_tempo", return_value={"tempo": 120, "tempo_confidence": 88}):
                                                with patch("app.tasks.audio.detect_key", return_value={"key": "C major", "confidence": 77}):
                                                    with patch("app.tasks.audio.detect_rhythm", return_value={"total_duration": 1.0}):
                                                        with patch("app.tasks.audio.detect_chords", return_value={"chords": []}):
                                                            with patch("app.tasks.chord_chart.chord_data_to_chord_chart_json", return_value="[]"):
                                                                with patch("app.tasks.estimate_stem_confidence", return_value=90):
                                                                    result = process_audio_transcription.run(transcription_id)

        tracks = (
            session.query(models.InstrumentTrack)
            .filter(models.InstrumentTrack.transcription_id == transcription_id)
            .order_by(models.InstrumentTrack.instrument_type.asc())
            .all()
        )
        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).first()
        assert result["status"] == "stem_ready"
        assert [track.instrument_type for track in tracks] == ["guitar"]
        assert all(track.processing_status == "stem_ready" for track in tracks)
        assert all(track.stem_audio_path and Path(track.stem_audio_path).exists() for track in tracks)
        assert pitch_mock.call_count == 0
        assert refreshed.is_processed is True
        assert refreshed.processing_status == "stem_ready"
        assert refreshed.can_play_stem is True
        assert refreshed.can_generate_score is False
        assert refreshed.audio_file_path is None
        assert refreshed.preprocessed_audio_file_path is None
        assert refreshed.separated_audio_file_path == tracks[0].stem_audio_path
    finally:
        session.close()


def test_process_audio_transcription_no_notes_completes_with_warning_and_keeps_stem(tmp_path):
    session = create_test_session()
    try:
        upload_path = tmp_path / "upload.wav"
        preprocessed_path = tmp_path / "upload_preprocessed.wav"
        other_stem = tmp_path / "other.wav"
        upload_path.write_bytes(b"upload")
        preprocessed_path.write_bytes(b"preprocessed")
        other_stem.write_bytes(b"other")

        transcription = models.Transcription(
            title="No notes task flow",
            audio_file_path=str(upload_path),
            selected_stem="other",
            user_id=1,
            is_processed=False,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)
        transcription_id = transcription.id
        upload_dir = tmp_path / "uploads"

        pitch_mock = Mock(return_value={
            "notes": [],
            "model_outputs": {"backend": "test"},
            "confidence_stats": {"count": 0, "min": None, "max": None, "mean": None},
            "total_notes_detected": 0,
        })

        with patch("app.tasks.get_db_session", return_value=session):
            with patch("app.tasks.settings") as settings_mock:
                settings_mock.UPLOAD_DIR = str(upload_dir)
                settings_mock.NOTE_DETECTION_SENSITIVITY = "normal"
                with patch("app.tasks.audio.preprocess_audio", return_value=str(preprocessed_path)):
                    with patch("app.tasks.audio.separate_selected_stem", return_value=str(other_stem)):
                        with patch("app.tasks.audio.normalize_audio_volume", return_value=str(other_stem)):
                            with patch("app.tasks.audio.audio_debug_stats", return_value={"rms_loudness": 0.1, "peak_amplitude": 0.5, "detected_onset_count": 0}):
                                with patch("app.tasks.audio.detect_pitch", pitch_mock):
                                    with patch("app.tasks.audio.detect_beat_and_tempo", return_value={"tempo": 120, "tempo_confidence": 88}):
                                        with patch("app.tasks.audio.detect_key", return_value={"key": "C major", "confidence": 77}):
                                            with patch("app.tasks.audio.detect_rhythm", return_value={"total_duration": 1.0}):
                                                with patch("app.tasks.audio.detect_chords", return_value={"chords": []}):
                                                    with patch("app.tasks.chord_chart.chord_data_to_chord_chart_json", return_value="[]"):
                                                        with patch("app.tasks.estimate_stem_confidence", return_value=90):
                                                            result = process_audio_transcription.run(transcription_id)

        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).first()
        track = session.query(models.InstrumentTrack).filter(
            models.InstrumentTrack.transcription_id == transcription_id
        ).one()

        assert result["status"] == "stem_ready"
        assert result["warning"] is None
        assert result["can_play_stem"] is True
        assert result["can_generate_score"] is False
        assert refreshed.is_processed is True
        assert refreshed.processing_status == "stem_ready"
        assert refreshed.warning_message is None
        assert refreshed.can_play_stem is True
        assert refreshed.can_generate_score is False
        assert refreshed.processing_error is None
        assert track.processing_status == "stem_ready"
        assert track.stem_audio_path and Path(track.stem_audio_path).exists()
        assert pitch_mock.call_count == 0
    finally:
        session.close()


def test_generate_tab_from_separated_stem_runs_pitch_after_user_confirmation(tmp_path):
    session = create_test_session()
    try:
        upload_path = tmp_path / "upload.wav"
        stem_path = tmp_path / "other.wav"
        upload_path.write_bytes(b"upload")
        stem_path.write_bytes(b"other")
        transcription = models.Transcription(
            title="Confirmed tab generation",
            audio_file_path=str(upload_path),
            separated_audio_file_path=str(stem_path),
            selected_stem="other",
            user_id=1,
            is_processed=True,
            processing_status="stem_ready",
            can_play_stem=True,
            can_generate_score=False,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)
        transcription_id = transcription.id
        track = models.InstrumentTrack(
            transcription_id=transcription_id,
            instrument_type="guitar",
            display_name="Guitar / Other",
            stem_audio_path=str(stem_path),
            processing_status="stem_ready",
        )
        session.add(track)
        session.commit()

        pitch_mock = Mock(return_value={
            "notes": [
                {"onset": 0.0, "offset": 0.5, "pitch": 64, "velocity": 90, "confidence": 0.8}
            ]
        })

        with patch("app.tasks.get_db_session", return_value=session):
            with patch("app.tasks.audio_processing_mode", return_value="local"):
                with patch("app.tasks.update_task_state") as update_state_mock:
                    with patch("app.tasks.settings") as settings_mock:
                        settings_mock.UPLOAD_DIR = str(tmp_path / "uploads")
                        settings_mock.NOTE_DETECTION_SENSITIVITY = "normal"
                        with patch("app.tasks.audio.normalize_audio_volume", return_value=str(stem_path)):
                            with patch("app.tasks.audio.audio_debug_stats", return_value={"rms_loudness": 0.1}):
                                with patch("app.tasks.audio.detect_pitch", pitch_mock):
                                    with patch("app.tasks.midi.save_midi_from_transcription", return_value=str(tmp_path / "out.mid")):
                                        with patch("app.tasks.midi.midi_to_musicxml", return_value="<score />"):
                                            with patch("app.tasks.tablature.save_tablature_from_transcription", return_value=str(tmp_path / "tab.json")):
                                                with patch("app.tasks.tablature.notes_to_tablature", return_value={"tablature": []}):
                                                    with patch("app.tasks.audio.detect_beat_and_tempo", return_value={"tempo": 120, "tempo_confidence": 88}):
                                                        with patch("app.tasks.audio.detect_key", return_value={"key": "C major", "confidence": 77}):
                                                            with patch("app.tasks.audio.detect_rhythm", return_value={"total_duration": 1.0}):
                                                                with patch("app.tasks.audio.detect_chords", return_value={"chords": []}):
                                                                    with patch("app.tasks.chord_chart.chord_data_to_chord_chart_json", return_value="[]"):
                                                                        result = generate_tab_from_separated_stem.run(transcription_id)

        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).first()
        assert result["status"] == "completed"
        update_state_mock.assert_not_called()
        assert pitch_mock.call_count == 1
        assert refreshed.processing_status == "completed"
        assert refreshed.tab_generation_status == "completed"
        assert refreshed.can_play_stem is True
        assert refreshed.can_generate_score is True
        assert refreshed.tablature_data
        assert refreshed.audio_file_path is None
    finally:
        session.close()


def test_generate_tab_from_separated_stem_failure_restores_stem_ready_status(tmp_path):
    session = create_test_session()
    try:
        stem_path = tmp_path / "other.wav"
        stem_path.write_bytes(b"other")
        transcription = models.Transcription(
            title="Failed tab generation",
            separated_audio_file_path=str(stem_path),
            selected_stem="other",
            user_id=1,
            is_processed=True,
            processing_status="stem_ready",
            tab_generation_status="idle",
            can_play_stem=True,
            can_generate_score=False,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)
        transcription_id = transcription.id

        with patch("app.tasks.get_db_session", return_value=session):
            with patch("app.tasks.audio_processing_mode", return_value="local"):
                with patch("app.tasks.update_task_state") as update_state_mock:
                    with patch(
                        "app.tasks.generate_tab_outputs_for_transcription",
                        side_effect=RuntimeError("pitch failed"),
                    ):
                        with pytest.raises(RuntimeError, match="pitch failed"):
                            generate_tab_from_separated_stem.run(transcription_id)

        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).first()
        update_state_mock.assert_not_called()
        assert refreshed.processing_status == "stem_ready"
        assert refreshed.tab_generation_status == "failed"
        assert refreshed.processing_error == "pitch failed"
        assert refreshed.queue_position is None
        assert refreshed.estimated_wait_time is None
        assert refreshed.celery_task_id is None
    finally:
        session.close()


def test_generate_tab_from_separated_stem_drums_generates_rhythm_only(tmp_path):
    session = create_test_session()
    try:
        stem_path = tmp_path / "drums.wav"
        stem_path.write_bytes(b"drums")
        transcription = models.Transcription(
            title="Confirmed rhythm generation",
            separated_audio_file_path=str(stem_path),
            selected_stem="drums",
            user_id=1,
            is_processed=True,
            processing_status="stem_ready",
            can_play_stem=True,
            can_generate_score=False,
            tablature_data='{"tablature": [{"fret": 0}]}',
            midi_file_path=str(tmp_path / "stale.mid"),
            tab_file_path=str(tmp_path / "stale.tab"),
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)
        track = models.InstrumentTrack(
            transcription_id=transcription.id,
            instrument_type="drums",
            display_name="Drums",
            stem_audio_path=str(stem_path),
            processing_status="stem_ready",
        )
        session.add(track)
        session.commit()

        drum_result = {
            "drum_hits": [{"onset": 0.0, "offset": 0.12, "confidence": 0.75}],
            "rhythm_analysis": {"source": "drum_stem_onset_detection", "total_duration": 1.0},
        }

        with patch("app.tasks.get_db_session", return_value=session):
            with patch("app.tasks.audio.detect_pitch") as pitch_mock:
                with patch("app.tasks.tablature.notes_to_tablature") as tab_mock:
                    with patch("app.tasks.midi.save_midi_from_transcription") as midi_mock:
                        with patch("app.tasks.audio.analyze_drum_rhythm", return_value=drum_result) as drum_mock:
                            result = generate_tab_from_separated_stem.run(transcription.id)

        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription.id
        ).first()
        refreshed_track = session.query(models.InstrumentTrack).filter(
            models.InstrumentTrack.transcription_id == transcription.id,
            models.InstrumentTrack.instrument_type == "drums",
        ).one()

        assert result["status"] == "completed"
        assert result["can_generate_score"] is False
        assert result["message"] == "Rhythm generation completed."
        assert drum_mock.call_count == 1
        assert pitch_mock.call_count == 0
        assert tab_mock.call_count == 0
        assert midi_mock.call_count == 0
        assert json.loads(refreshed.notes_data)["drum_hits"][0]["confidence"] == 0.75
        assert json.loads(refreshed_track.notes_json)["drum_hits"][0]["confidence"] == 0.75
        assert refreshed.tablature_data is None
        assert refreshed.notation_data is None
        assert refreshed.can_generate_score is False
        assert refreshed.midi_file_path is None
        assert refreshed.tab_file_path is None
    finally:
        session.close()


def test_process_audio_transcription_selected_drums_uses_rhythm_not_pitch(tmp_path):
    session = create_test_session()
    try:
        upload_path = tmp_path / "upload.wav"
        preprocessed_path = tmp_path / "upload_preprocessed.wav"
        drum_stem = tmp_path / "drums.wav"
        upload_path.write_bytes(b"upload")
        preprocessed_path.write_bytes(b"preprocessed")
        drum_stem.write_bytes(b"drums")

        transcription = models.Transcription(
            title="Drum task flow",
            audio_file_path=str(upload_path),
            selected_stem="drums",
            user_id=1,
            is_processed=False,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)
        transcription_id = transcription.id
        upload_dir = tmp_path / "uploads"
        drum_result = {
            "drum_hits": [{"onset": 0.0, "offset": 0.12, "confidence": 0.9}],
            "rhythm_analysis": {"source": "drum_stem_onset_detection", "total_duration": 1.0},
        }

        with patch("app.tasks.get_db_session", return_value=session):
            with patch("app.tasks.settings") as settings_mock:
                settings_mock.UPLOAD_DIR = str(upload_dir)
                with patch("app.tasks.audio.preprocess_audio", return_value=str(preprocessed_path)):
                    with patch("app.tasks.audio.separate_selected_stem", return_value=str(drum_stem)):
                        with patch("app.tasks.audio.detect_pitch") as pitch_mock:
                            with patch("app.tasks.audio.analyze_drum_rhythm", return_value=drum_result) as drum_mock:
                                with patch("app.tasks.audio.detect_beat_and_tempo", return_value={"tempo": 120, "tempo_confidence": 88}):
                                    with patch("app.tasks.audio.detect_key", return_value={"key": "C major", "confidence": 77}):
                                        result = process_audio_transcription.run(transcription_id)

        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).first()
        track = session.query(models.InstrumentTrack).filter(
            models.InstrumentTrack.transcription_id == transcription_id
        ).one()

        assert result["status"] == "stem_ready"
        assert pitch_mock.call_count == 0
        assert drum_mock.call_count == 0
        assert track.instrument_type == "drums"
        assert track.notes_json is None
        assert refreshed.notes_data is None
        assert refreshed.can_play_stem is True
        assert refreshed.can_generate_score is False
        assert refreshed.processing_status == "stem_ready"
        assert refreshed.midi_file_path is None
        assert refreshed.tab_file_path is None
    finally:
        session.close()


def test_process_audio_transcription_selected_vocals_is_playback_only(tmp_path):
    session = create_test_session()
    try:
        upload_path = tmp_path / "upload.wav"
        preprocessed_path = tmp_path / "upload_preprocessed.wav"
        vocal_stem = tmp_path / "vocals.wav"
        upload_path.write_bytes(b"upload")
        preprocessed_path.write_bytes(b"preprocessed")
        vocal_stem.write_bytes(b"vocals")

        transcription = models.Transcription(
            title="Vocal task flow",
            audio_file_path=str(upload_path),
            selected_stem="vocals",
            user_id=1,
            is_processed=False,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)
        transcription_id = transcription.id
        upload_dir = tmp_path / "uploads"

        with patch("app.tasks.get_db_session", return_value=session):
            with patch("app.tasks.settings") as settings_mock:
                settings_mock.UPLOAD_DIR = str(upload_dir)
                with patch("app.tasks.audio.preprocess_audio", return_value=str(preprocessed_path)):
                    with patch("app.tasks.audio.separate_selected_stem", return_value=str(vocal_stem)):
                        with patch("app.tasks.audio.detect_pitch") as pitch_mock:
                            with patch("app.tasks.audio.detect_beat_and_tempo", return_value={"tempo": 120, "tempo_confidence": 88}):
                                with patch("app.tasks.audio.detect_key", return_value={"key": "C major", "confidence": 77}):
                                    result = process_audio_transcription.run(transcription_id)

        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).first()
        track = session.query(models.InstrumentTrack).filter(
            models.InstrumentTrack.transcription_id == transcription_id
        ).one()

        assert result["status"] == "stem_ready"
        assert pitch_mock.call_count == 0
        assert track.instrument_type == "vocals"
        assert track.tab_json is None
        assert track.notation_json is None
        assert refreshed.processing_status == "stem_ready"
        assert refreshed.warning_message is None
        assert refreshed.can_play_stem is True
        assert refreshed.can_generate_score is False
        assert refreshed.midi_file_path is None
        assert refreshed.tab_file_path is None
    finally:
        session.close()


def test_process_audio_transcription_fails_clearly_when_selected_stem_separation_fails(tmp_path):
    session = create_test_session()
    try:
        upload_path = tmp_path / "upload.wav"
        preprocessed_path = tmp_path / "upload_preprocessed.wav"
        upload_path.write_bytes(b"upload")
        preprocessed_path.write_bytes(b"preprocessed")

        transcription = models.Transcription(
            title="Task fallback",
            audio_file_path=str(upload_path),
            selected_stem="other",
            user_id=1,
            is_processed=False,
        )
        session.add(transcription)
        session.commit()
        session.refresh(transcription)
        transcription_id = transcription.id
        upload_dir = tmp_path / "uploads"

        pitch_mock = Mock(return_value={
            "notes": [
                {"onset": 0.0, "offset": 0.5, "pitch": 64, "velocity": 90, "confidence": 0.8}
            ]
        })

        with patch("app.tasks.get_db_session", return_value=session):
            with patch("app.tasks.settings") as settings_mock:
                settings_mock.UPLOAD_DIR = str(upload_dir)
                with patch("app.tasks.audio.preprocess_audio", return_value=str(preprocessed_path)):
                    with patch("app.tasks.audio.separate_selected_stem", side_effect=RuntimeError("separation failed")):
                        with patch("app.tasks.audio.detect_pitch", pitch_mock):
                            with patch("app.tasks.midi.save_midi_from_transcription", return_value=str(tmp_path / "out.mid")):
                                with patch("app.tasks.midi.midi_to_musicxml", return_value="<score />"):
                                    with patch("app.tasks.tablature.save_tablature_from_transcription", return_value=str(tmp_path / "tab.json")):
                                        with patch("app.tasks.tablature.notes_to_tablature", return_value={"tablature": []}):
                                            with patch("app.tasks.audio.detect_beat_and_tempo", return_value={"tempo": 120, "tempo_confidence": 88}):
                                                with patch("app.tasks.audio.detect_key", return_value={"key": "C major", "confidence": 77}):
                                                    with patch("app.tasks.audio.detect_rhythm", return_value={"total_duration": 1.0}):
                                                        with patch("app.tasks.audio.detect_chords", return_value={"chords": []}):
                                                            with patch("app.tasks.chord_chart.chord_data_to_chord_chart_json", return_value="[]"):
                                                                with pytest.raises(RuntimeError):
                                                                    process_audio_transcription.run(transcription_id)

        tracks = session.query(models.InstrumentTrack).filter(
            models.InstrumentTrack.transcription_id == transcription_id
        ).all()

        assert tracks == []
        assert pitch_mock.call_count == 0
        refreshed = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).first()
        assert refreshed.is_processed is False
        assert refreshed.processing_status == "failed"
        assert "Could not isolate the selected stem" in refreshed.processing_error
        assert refreshed.separated_audio_file_path is None
    finally:
        session.close()
