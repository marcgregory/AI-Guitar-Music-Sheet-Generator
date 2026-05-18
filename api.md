# API Contract

## Processing Requests

Audio upload and YouTube processing must include one selected target:

- `selected_stem`
- or `selected_instrument`

Valid MVP values:

- `vocals`
- `drums`
- `bass`
- `other`

For MVP guitar transcription, clients should submit `other`.

API and frontend copy should explain that `other` is the guitar/accompaniment MVP target and may contain guitar, piano, synths, melody, or accompaniment depending on the mix. The MVP should not present `other` as isolated lead guitar.

Supported MVP input types:

1. Audio upload
2. YouTube URL

MIDI import, Guitar Pro import, PowerTab import/export, imported project playback architecture, and imported multi-track workflows are future roadmap items only. MIDI export, MusicXML export, and TAB export remain in scope when generated from separated-stem transcription results.

## Endpoints

Expected MVP endpoints:

- `POST /api/v1/audio/upload` with multipart `file` and `selected_stem`
- `POST /api/v1/audio/youtube` with `youtube_url` and `selected_stem`
- `GET /api/v1/audio/{id}/status`
- `GET /api/v1/audio/{id}/result`
- `GET /api/v1/audio/{id}/tracks`
- `GET /api/v1/audio/{id}/tracks/{track_id}`
- `GET /api/v1/audio/{id}/tracks/{track_id}/preview` to preview the selected separated stem
- `DELETE /api/v1/transcriptions/{id}` to delete or hide a record and cleanup Cloudinary assets when safe
- `POST /api/v1/transcriptions/{id}/cancel` if cancellation is modeled separately from deletion
- `GET /api/v1/worker/jobs/next` for authenticated external workers to pull the next queued job
- `POST /api/v1/worker/jobs/{transcription_id}/complete` for workers to report Cloudinary output references and mark completion
- `POST /api/v1/worker/jobs/{transcription_id}/failed` for workers to report failure and mark the job failed
- Download/playback endpoints may redirect to, proxy, or return Cloudinary-hosted URLs

Worker endpoints should require `WORKER_API_TOKEN`. They support `PROCESSING_MODE=external_worker` and may also be used by Modal callback flows.

## Duplicate Handling

Before a new job is queued:

```txt
User Upload / YouTube URL + selected stem
-> Generate audio hash or normalize YouTube ID
-> Check existing completed/completed_with_warning record with same user + source identity + selected_stem
-> If found, return existing result
-> If not found, upload/process normally
-> Save result for future reuse
```

Duplicate lookup keys:

- uploaded file: `audio_hash` + `selected_stem`
- YouTube URL: `source_type` + `normalized_source_id` + `selected_stem`

If a duplicate completed or completed_with_warning record is found, do not run Demucs again. Return the existing result and let the frontend show the appropriate reuse message.

Same song plus a different selected stem may create a new processing job.

Duplicate responses include `duplicate_reused: true` and `duplicate_message`. Duplicate records are not queued.

## Status Values

- `pending`: record created but not yet queued
- `queued`: waiting because another job is active or ahead in the queue
- `processing`: local Celery, external worker, or Modal worker is actively processing the selected stem
- `completed`: selected-stem outputs are available where supported
- `completed_with_warning`: transcription succeeded but has limited generated output, such as a no-note stem
- `failed`: processing ended with `processing_error`

## Response Fields

Result/status payloads should include:

- `selected_stem`
- `original_audio_url`
- `original_audio_public_id`
- `separated_audio_url`
- `separated_audio_public_id`
- `midi_file_url`
- `midi_file_public_id`
- `musicxml_file_url`
- `musicxml_file_public_id`
- `tab_file_url`
- `tab_file_public_id`
- `processing_status`
- `processing_error`
- `warning_message`
- `can_play_stem`
- `can_generate_score`
- `queue_position`
- `estimated_wait_time`
- `duplicate_reused`
- `duplicate_message`
- `audio_hash`
- `source_type`
- `source_url`
- `normalized_source_id`
- `duplicate_of_id`
- `is_deleted`
- `deleted_at`

Cloudinary URL fields may be `null` when an output is unsupported for the selected stem. For example, `vocals` is playback-only in the MVP. `queue_position` is `0` for active processing, positive for pending/queued jobs, and `null` after terminal states.

No-note melodic results should preserve `separated_audio_url`, return `can_play_stem=true`, set `can_generate_score=false`, and include a warning such as `"No note events detected for this stem."`. The database should prefer `completed_with_warning`; API responses may expose `status="completed"` plus warning/capability fields when existing clients require that shape.

Valid MVP `source_type` values are:

- `upload`
- `youtube`
- `demo`

## Stem Output Semantics

- `vocals`: preserve separated stem playback and metadata; generated notation is future roadmap.
- `drums`: return onset/rhythm hit data for rhythm lane/percussion tab rendering and drum MIDI export when possible. Do not use Basic Pitch for drums.
- `bass`: run Spotify Basic Pitch on the normalized selected bass stem, return bass notes, 4-string E A D G tablature, score notation, and timing data where detected.
- `other`: run Spotify Basic Pitch on the normalized selected `other` stem, return guitar-oriented notes, 6-string tablature, score notation, and timing data where detected. Explain that `other` may include guitar, piano, synths, melody, or accompaniment.

## Basic Pitch and Warning Semantics

Spotify Basic Pitch is the primary note detection engine for selected melodic stems: `other`, `bass`, and future melodic `vocals`. Workers normalize the separated stem before transcription and retry Basic Pitch with lower-threshold/high-sensitivity settings when the first pass detects zero notes.

If retry still detects zero notes, the job is not a failure when the separated stem is playable. Preserve stem playback and waveform/rhythm metadata, set `warning_message`, expose `can_play_stem=true` and `can_generate_score=false`, and make score/TAB/MIDI/MusicXML exports unavailable for that result.

## Preview Semantics

`GET /api/v1/audio/{id}/tracks/{track_id}/preview` should stream the selected stem for quick playback before export. When `separated_audio_url` exists, the API may redirect to Cloudinary. For local development or legacy records with retained local stems, the endpoint supports `Range` requests and returns `Accept-Ranges`, `Content-Range`, and `206 Partial Content` when possible.

## Frontend Behavior

The frontend must require one stem before submitting an audio/YouTube processing request, display queue status, and show downloadable Cloudinary-hosted outputs only when the corresponding URL fields are present.

The frontend must also show the selected stem, stem confidence, low-confidence warnings, and the `other` stem explanation. Playback should remain available for playable separated stems even when score/tab generation is unavailable.

Highest frontend priorities:

1. selected stem playback sync
2. synchronized tab highlighting
3. synchronized score highlighting
4. waveform sync
5. instrument-aware rendering
6. stem metadata visibility
7. drum rhythm lane rendering
8. bass tab rendering

The viewer should use one shared `currentTime` for waveform, playhead, tabs, score, active notes/hits, and selected-stem playback. Do not use separate timers for waveform, tabs, and score.

## Processing Modes

- `PROCESSING_MODE=local`: development fallback. Railway/Celery can process very short files only and should not be used as production Demucs infrastructure.
- `PROCESSING_MODE=external_worker`: backend queues jobs for a manually running worker. Kaggle can be used here for manual/free GPU testing, but queued jobs wait until the notebook is running.
- `PROCESSING_MODE=modal`: preferred production-like MVP mode. Backend triggers Modal/serverless GPU processing.

## Delete Semantics

Records may be deleted in `completed`, `completed_with_warning`, `failed`, `queued`, and `processing` states.

- `completed` or `failed`: delete Cloudinary assets when safe, then mark deleted or remove the record.
- `queued`: remove/cancel the queued Celery task when possible, then mark deleted.
- `processing`: mark as cancelled/deleted and revoke/stop the Celery task if supported.

Cloudinary cleanup uses `resource_type="video"` for original and separated audio and `resource_type="raw"` for MIDI/MusicXML/TAB/text exports. Before deleting a public ID, the API checks whether another transcription outside the current deletion set still references it; shared duplicate assets are skipped. Project deletion cascades through related transcriptions with the same cleanup strategy.

MVP limitation: stopping an active Celery task may not be reliable. In that case, the API can hide/delete the UI record while the worker finishes silently. Temporary files should still be cleaned up. If Cloudinary deletion fails, keep the database deletion safe and log the cleanup error.
