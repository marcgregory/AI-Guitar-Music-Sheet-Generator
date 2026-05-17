# Roadmap

## Phase 1: Selected-Stem MVP

- Selected stem only
- One active processing job at a time
- Celery worker concurrency set to `1`
- Cloudinary storage integration
- Railway local storage treated as temporary only
- Duplicate song/stem detection before queueing work
- Delete/cancel processing records from the UI
- Recommended song duration: 3-5 minutes

## Phase 2: Multiple Selected Stems

- Allow users to choose more than one target stem
- Queue each selected stem predictably
- Keep output storage Cloudinary-backed
- Reuse completed outputs per source + selected stem
- Avoid full automatic all-stem transcription unless cost and reliability are acceptable

## Phase 3: GPU Worker or External AI Processing

- Move heavy AI processing off the basic Railway worker
- Explore GPU-backed workers or an external AI processing service
- Revisit concurrency after memory and cost limits are better understood

## Phase 4: Songsterr-Like Multi-Track Tabs

- Full multi-track synchronized tab/notation experience
- Better specialist separation for guitar, piano, lead/rhythm guitar, and other roles
- More complete per-track MIDI, TAB, MusicXML, and sharing workflows

## Out of Scope for Phase 1

- Large-scale concurrent AI processing
- Full automatic all-stem transcription
- True isolated lead guitar/rhythm guitar/piano separation
- Songsterr-like complete multi-track tabs
