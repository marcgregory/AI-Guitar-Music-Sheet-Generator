# Implementation Plan

The canonical implementation plan lives in [implementation-plan.md](implementation-plan.md).

Current MVP priority:

1. Selected-stem processing stability.
2. Stem-aware transcription.
3. Bass tab generation.
4. Drum rhythm lane generation.
5. Playback timing accuracy.
6. Export stability.
7. Duplicate reuse.
8. Cloudinary persistence.

Supported MVP input types are audio upload and YouTube URL.

Primary MVP workflow:

```txt
Audio Upload / YouTube URL
-> User selects target stem
-> Demucs separates selected stem
-> Pitch/rhythm detection runs on separated stem
-> Generate instrument-aware tabs/notation/rhythm data
-> Render synchronized playback with playhead/waveform
-> Export generated outputs
```

Demucs default stems are `vocals`, `drums`, `bass`, and `other`. For guitar transcription, use `other` in the MVP and explain that guitar/piano may be grouped there depending on the model and mix.

Stem behavior:

- `vocals`: playback only for MVP; future roadmap: melody extraction.
- `drums`: hit/onset analysis, rhythm lane, percussion/drum tab, synchronized highlighting, and drum MIDI export where possible.
- `bass`: 4-string E A D G bass tablature, bass score data, and synchronized playback.
- `other`: primary guitar transcription target with 6-string guitar tab, score notation, and synchronized playback.

Durable files should live in Cloudinary, with both `secure_url` and `public_id` stored for original audio, selected separated stem audio, MIDI exports, MusicXML exports, and TAB files. Railway local storage is temporary worker scratch space only.

Railway should be documented as the FastAPI/PostgreSQL controller, not the main AI worker. `PROCESSING_MODE=local` keeps Celery as a development fallback for very short files, `PROCESSING_MODE=external_worker` supports manual/Kaggle testing, and `PROCESSING_MODE=modal` is the preferred production-like MVP path.

Duplicate detection and deletion are also Phase 1 concerns:

- Check `audio_hash` for uploaded files or normalized YouTube/source ID for URL submissions before queueing.
- Reuse an existing completed result when the same song and same `selected_stem` already exists.
- Allow deletion of completed, completed_with_warning, failed, queued, and processing records.
- Delete Cloudinary files when safe; log cleanup errors without making database deletion unsafe.

Future roadmap only:

- MIDI import.
- Guitar Pro import.
- PowerTab import/export.
- Imported project editing.
- Imported multi-track workflows.
