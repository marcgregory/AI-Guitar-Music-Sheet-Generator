# Storage Strategy

## Durable Storage

Use Cloudinary for uploaded audio and generated outputs:

- original audio
- selected separated stem audio
- MIDI export files
- MusicXML export files
- TAB files

Store both Cloudinary values for each asset:

- `secure_url` for playback, export, and download
- `public_id` for deletion, replacement, and lifecycle management

## Temporary Storage

Railway local storage is temporary only. The backend/worker may use local paths for:

- upload buffering
- YouTube extraction output
- worker downloads from Cloudinary
- Demucs intermediate files
- MIDI/MusicXML/TAB generation before upload

Temporary files should be cleaned after each job reaches `completed`, `completed_with_warning`, or `failed`. A failed job should still attempt cleanup and record `processing_error`.

Modal/serverless GPU and external workers should treat Cloudinary as the source of truth: download `original_audio_url`, upload the selected separated stem and supported exports, and report the resulting `secure_url`/`public_id` values back to the backend. No worker local filesystem should be treated as durable storage.

For preview playback, prefer `separated_audio_url` and redirect to Cloudinary. Local stem paths are development/legacy fallback only and may be removed after durable upload.

If Basic Pitch finds no notes after retry for a melodic stem, keep the selected separated stem in Cloudinary for playback and mark notation-dependent exports unavailable rather than deleting the stem or failing the job.

## Deleting Stored Assets

When a processing record is deleted, delete related Cloudinary files when safe:

- original audio with `resource_type="video"`
- selected separated stem audio with `resource_type="video"`
- MIDI file with `resource_type="raw"`
- MusicXML file with `resource_type="raw"`
- TAB/text export with `resource_type="raw"`

Cleanup is attempted before soft-deleting or hard-deleting database records. If Cloudinary deletion fails, log the exception, keep the database deletion safe, and leave enough log context for retry or manual follow-up.

Before deleting a Cloudinary public ID, check whether another transcription outside the current deletion set still references it. This protects duplicate-reused files from being removed while another transcription still needs them. Project deletion should collect all related transcription IDs, delete assets shared only within that project once, skip assets referenced outside the project, and then delete or mark the database records.

## Duplicate Storage Guard

Before uploading and processing, check whether the same song and selected stem already has a completed or completed_with_warning result:

- uploaded files: use `audio_hash`
- YouTube submissions: use `source_type`, `source_url`, and `normalized_source_id`
- queued work: skip entirely when a completed duplicate exists
- include `selected_stem` in the audio/YouTube lookup

Reuse existing completed output for the same source plus same stem. A different selected stem may create a new job because the separated stem and generated outputs differ.

## Cost Notes

Selective stem processing reduces:

- CPU usage
- RAM usage
- storage costs
- processing time
- repeated Cloudinary storage from duplicate jobs

Phase 1 should recommend 3-5 minute songs and avoid full multi-stem processing. Production-like selected-stem AI work should move to Modal/serverless GPU; Kaggle remains optional/manual testing only.

Selected-stem processing also reduces Basic Pitch work because note detection runs only for the selected melodic stem; drum jobs use onset/rhythm analysis instead of melodic transcription.

MIDI import, Guitar Pro import, PowerTab import/export, imported project editing, and imported multi-track workflows are future roadmap only.
