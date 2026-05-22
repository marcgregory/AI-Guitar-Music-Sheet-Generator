# Project Scope

The canonical scope currently lives in [ai_guitar_music_sheet_generator_scope.md](ai_guitar_music_sheet_generator_scope.md), with a short summary in [scope.md](scope.md).

MVP supported input types:

1. Audio upload
2. YouTube URL

Primary MVP workflow:

```txt
Audio Upload / YouTube URL
-> User selects target stem
-> Check existing completed result for the same source + selected stem
-> Upload original audio to Cloudinary when processing is needed
-> Queue one selected-stem job
-> Demucs separates selected stem
-> Basic Pitch-style note detection runs only for melodic non-vocal stems (`other`, `bass`)
-> Onset/rhythm detection runs for `drums`
-> faster-whisper lyrics generation runs for `vocals`
-> Generate instrument-aware tabs/notation/rhythm data where supported
-> Render synchronized playback with playhead/waveform
-> Export generated outputs
```

Audio upload and YouTube processing require a selected stem (`vocals`, `drums`, `bass`, or `other`). Hosted MVP backends should use `AUDIO_PROCESSING_MODE=modal` so Modal handles heavy AI/audio work while Railway/Render handles API, auth, DB, polling, Cloudinary references, and callbacks.

MVP stem behavior:

- `vocals`: selected-stem playback plus Generate Lyrics using faster-whisper. Lyrics use `lyrics_generation_status`, separate from the main `processing_status`.
- `drums`: analyze drum stem with onset/rhythm detection only; do not use Basic Pitch; generate a rhythm lane/percussion tab where possible, support synchronized playback highlighting, and support drum MIDI export when possible.
- `bass`: analyze bass stem with Basic Pitch, generate 4-string bass tablature using standard E A D G tuning, generate bass score data, and support synchronized playback/playhead highlighting.
- `other`: primary guitar/accompaniment target, analyzed with Basic Pitch and rendered as guitar-oriented tablature, score notation, and synchronized playback/playhead highlighting. The UI/API must explain that guitar, piano, synths, melody, or accompaniment may be grouped inside `other`.

The MVP does not include MIDI import, Guitar Pro import, PowerTab import/export, imported project playback architecture, advanced Guitar Pro/Songsterr-style notation, or imported multi-track project workflows. These remain future roadmap items only. MIDI export, MusicXML export, and TAB export remain in scope and should be generated from transcription results created from separated stems.

Valid MVP `source_type` values are `upload`, `youtube`, and `demo`. Future import source types may include `midi_import` and Guitar Pro/PowerTab-specific values when those features return to scope.

The frontend should poll `/status` first and call `/result` only after a ready status such as `stem_ready`, `completed`, or `completed_with_warning`. Generate Tabs is for non-vocal melodic stems and should remain unchanged; Generate Lyrics should update lyrics in-place without sending the viewer back to processing.
