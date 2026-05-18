# Roadmap

## Phase 1: Selected-Stem MVP

- Supported input types: audio upload and YouTube URL
- Required selected stem: `vocals`, `drums`, `bass`, or `other`
- Demucs selected-stem separation, one selected stem per job
- Pitch/rhythm detection on the separated selected stem
- Guitar tablature and score notation from `other`
- 4-string bass tablature and bass score notation from `bass`, using standard E A D G tuning
- Drum hit/onset detection, rhythm lane, and percussion/drum tab from `drums`
- Vocal stem playback only
- Synchronized Songsterr-style playback with one shared `currentTime`
- Moving playhead, note highlighting, tab sync, score sync, waveform sync, seek sync, and selected-stem playback sync
- Cloudinary persistence for original audio, selected separated stem, and generated MIDI/MusicXML/TAB outputs
- Duplicate song/stem detection before queueing work
- Delete/cancel processing records from the UI
- Queue/status UX using `pending`, `queued`, `processing`, `completed`, `completed_with_warning`, and `failed`
- Recommended song duration: 3-5 minutes

## Phase 2: Modal/Serverless GPU Worker

- Modal/serverless GPU worker integration
- Worker endpoints: `GET /api/v1/worker/jobs/next`, `POST /api/v1/worker/jobs/{id}/complete`, and `POST /api/v1/worker/jobs/{id}/failed`
- External worker authentication with `WORKER_API_TOKEN`
- Status callback flow from worker to backend
- Selected-stem preview and export from Cloudinary outputs

## Phase 3: Playback and Instrument Reliability

- Selected-stem playback timing accuracy
- Synchronized tab highlighting
- Synchronized score highlighting
- Waveform synchronization
- Instrument-aware rendering polish
- Stem metadata visibility
- Drum rhythm lane rendering
- Bass tab rendering
- Better retry/recovery and worker logs
- Duplicate reuse and Cloudinary persistence hardening

## Phase 4: Future Imports and Advanced Workflows

- MIDI import
- Guitar Pro import
- PowerTab import/export
- Imported project editing
- Imported multi-track project workflows
- Multiple selected stems
- Full multi-track synchronized tab/notation experience
- Lead/rhythm guitar separation
- True isolated guitar models
- Piano specialist models
- Real-time transcription
- Collaborative editing

## Out of Scope for Phase 1

- MIDI import
- Guitar Pro import
- PowerTab import/export
- Imported project playback architecture
- Imported multi-track workflows
- Large-scale concurrent AI processing
- Full automatic all-stem transcription
- True isolated lead guitar/rhythm guitar/piano separation
- Kaggle as production infrastructure
- Railway free/trial Demucs processing as production infrastructure

## Current Next Priorities

1. Selected-stem processing stability.
2. Stem-aware transcription.
3. Bass tab generation.
4. Drum rhythm lane generation.
5. Playback timing accuracy.
6. Export stability.
7. Duplicate reuse.
8. Cloudinary persistence.
