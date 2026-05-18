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
-> Spotify Basic Pitch runs only for melodic stems (`other`, `bass`, future melodic `vocals`)
-> Onset/rhythm detection runs for `drums`
-> Generate instrument-aware tabs/notation/rhythm data where supported
-> Render synchronized playback with playhead/waveform
-> Export generated outputs
```

Audio upload and YouTube processing require a selected stem (`vocals`, `drums`, `bass`, or `other`) and may use Demucs through Modal/serverless GPU, external worker, or local development fallback.

MVP stem behavior:

- `vocals`: playback only. Future roadmap: Basic Pitch or specialist melody extraction.
- `drums`: analyze drum stem with onset/rhythm detection only; do not use Basic Pitch; generate a rhythm lane/percussion tab where possible, support synchronized playback highlighting, and support drum MIDI export when possible.
- `bass`: analyze bass stem with Basic Pitch, generate 4-string bass tablature using standard E A D G tuning, generate bass score data, and support synchronized playback/playhead highlighting.
- `other`: primary guitar/accompaniment target, analyzed with Basic Pitch and rendered as guitar-oriented tablature, score notation, and synchronized playback/playhead highlighting. The UI/API must explain that guitar, piano, synths, melody, or accompaniment may be grouped inside `other`.

The MVP does not include MIDI import, Guitar Pro import, PowerTab import/export, imported project playback architecture, or imported multi-track project workflows. These remain future roadmap items only. MIDI export, MusicXML export, and TAB export remain in scope and should be generated from transcription results created from separated stems.

Valid MVP `source_type` values are `upload`, `youtube`, and `demo`. Future import source types may include `midi_import` and Guitar Pro/PowerTab-specific values when those features return to scope.
