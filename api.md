# API Contract

## Processing Requests

Upload and YouTube processing must include one selected target:

- `selected_stem`
- or `selected_instrument`

Valid MVP values:

- `vocals`
- `drums`
- `bass`
- `other`

For MVP guitar transcription, clients should submit `other`.

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
- Download/playback endpoints may redirect to, proxy, or return Cloudinary-hosted URLs

## Duplicate Handling

Before a new job is queued:

```txt
User Upload / YouTube URL + selected stem
-> Generate audio hash or normalize YouTube ID
-> Check existing completed record with same source + selected_stem
-> If found, return existing result
-> If not found, upload/process normally
-> Save result for future reuse
```

Duplicate lookup keys:

- uploaded file: `audio_hash` + `selected_stem`
- YouTube URL: `source_type` + `normalized_source_id` + `selected_stem`

If a duplicate completed record is found, do not run Demucs again. Return the existing result and let the frontend show: "This song and stem were already processed. Existing result was loaded."

Same song plus a different selected stem may create a new processing job.

Duplicate responses include `duplicate_reused: true` and `duplicate_message`. Duplicate records are not queued.

## Status Values

- `pending`: record created but not yet queued
- `queued`: waiting because another job is active or ahead in the queue
- `processing`: Celery worker is actively processing the selected stem
- `completed`: selected-stem outputs are available where supported
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
- `tab_file_url`
- `tab_file_public_id`
- `processing_status`
- `processing_error`
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

Cloudinary URL fields may be `null` when an output is unsupported for the selected stem. For example, `drums` may produce rhythm data but no TAB, and `vocals` may not produce a guitar-style TAB. `queue_position` is `0` for active processing, positive for pending/queued jobs, and `null` after terminal states.

## Preview Semantics

`GET /api/v1/audio/{id}/tracks/{track_id}/preview` should stream the selected stem for quick playback before export. When `separated_audio_url` exists, the API may redirect to Cloudinary. For local development or legacy records with retained local stems, the endpoint supports `Range` requests and returns `Accept-Ranges`, `Content-Range`, and `206 Partial Content` when possible.

## Frontend Behavior

The frontend must require one stem before submitting a processing request, display queue status, and show downloadable Cloudinary-hosted outputs only when the corresponding URL fields are present.

## Delete Semantics

Records may be deleted in `completed`, `failed`, `queued`, and `processing` states.

- `completed` or `failed`: mark deleted or remove record, then delete Cloudinary assets when safe.
- `queued`: remove/cancel the queued Celery task when possible, then mark deleted.
- `processing`: mark as cancelled/deleted and revoke/stop the Celery task if supported.

MVP limitation: stopping an active Celery task may not be reliable. In that case, the API can hide/delete the UI record while the worker finishes silently. Temporary files should still be cleaned up. If Cloudinary deletion fails, keep the database deletion safe and log the cleanup error.
