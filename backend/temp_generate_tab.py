def _generate_tab_from_stem(
    stem_path: Path,
    transcription_id: int,
    selected_stem: str,
    *,
    sensitivity: str = "normal",
) -> dict[str, Any]:
    # Start with basic analysis
    analysis = _analyze_selected_stem(stem_path, selected_stem)
    analysis.update(_detect_tempo_key_duration(stem_path))

    notes_data = analysis.get("notes_data")
    if selected_stem in {"bass", "other"} and isinstance(notes_data, dict) and notes_data.get("notes"):
        # For tab generation, we want to create tablature from the notes
        if selected_stem == "bass":
            instrument_type = "bass"
        else:
            instrument_type = "guitar"

        if sensitivity == "high" and notes_data.get("model_outputs"):
            notes_data["model_outputs"]["requested_sensitivity"] = "high"

        # Generate tablature data using our improved function
        tab_data = _note_to_tablature(notes_data, instrument_type)
        analysis["tablature_data"] = tab_data

        # Also generate MIDI file (keep this for compatibility)
        midi_path = stem_path.with_name(f"transcription_{transcription_id}.mid")
        _notes_to_midi(notes_data, midi_path, tempo_bpm=float(analysis.get("detected_tempo") or 120))
        midi_upload = _upload_file(midi_path, transcription_id, "exports", resource_type="raw")
        analysis["midi_file_url"] = midi_upload.get("secure_url")
        analysis["midi_file_public_id"] = midi_upload.get("public_id")

        # Generate ASCII tab from tablature data
        tab_ascii = _tablature_to_ascii(tab_data)
        tab_path = stem_path.with_name(f"transcription_{transcription_id}.tab")
        tab_path.write_text(tab_ascii, encoding="utf-8")
        tab_upload = _upload_file(tab_path, transcription_id, "exports", resource_type="raw")
        analysis["tab_file_url"] = tab_upload.get("secure_url")
        analysis["tab_file_public_id"] = tab_upload.get("public_id")

        # Add warning for "other" stem
        if selected_stem == "other":
            track_metadata = analysis.setdefault("track_metadata", {})
            existing_notes = track_metadata.get("confidence_notes")
            warning_msg = "This stem may contain guitar, piano, and other instruments. Tabs are experimental."
            if existing_notes:
                track_metadata["confidence_notes"] = f"{existing_notes} {warning_msg}"
            else:
                track_metadata["confidence_notes"] = warning_msg

    return analysis