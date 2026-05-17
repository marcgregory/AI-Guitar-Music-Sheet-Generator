# MusicStudio Frontend

React + TypeScript frontend for the AI Guitar Music Sheet Generator / MusicStudio app.

## MVP Flow

Before starting upload or YouTube processing, the user must choose a target Demucs stem:

- `vocals`
- `drums`
- `bass`
- `other`

For MVP guitar transcription, the UI should guide users to choose `other`. The copy should clearly explain that guitar, piano, and accompaniment may be grouped inside `other` with default Demucs models. True separate guitar, lead/rhythm guitar, and piano stems are future model upgrades.

The frontend should show queue-aware processing states:

- `pending`
- `queued`
- `processing`
- `completed`
- `failed`

If another job is active, show that the new job is queued or waiting because the Railway MVP intentionally processes one job at a time to reduce cost and prevent memory overload.

Completed outputs should use the Cloudinary-hosted URLs returned by the backend:

- `original_audio_url` for source playback when needed
- `separated_audio_url` for selected-stem playback
- `midi_file_url` for MIDI download where supported
- `tab_file_url` for TAB download where supported

If the backend finds an existing completed result for the same song and selected stem, the frontend should load that result instead of showing a new processing job. Display:

"This song and stem were already processed. Existing result was loaded."

## UI Requirements

- Add a required stem selector before the process action.
- Prefer Demucs-supported labels first: vocals, drums, bass, other.
- Use friendly helper text for `other`: "Best MVP choice for guitar or piano, depending on the mix."
- Do not imply the MVP can reliably split lead guitar, rhythm guitar, and piano into separate stems.
- In the viewer, emphasize the selected stem output rather than a full multi-stem mixer by default.
- Display queue status clearly when `processing_status` is `queued`.
- Display downloadable Cloudinary-hosted outputs only when their URL fields are present.
- Add a delete button for completed, failed, queued, and processing items.
- Show confirmation before deleting a record.
- Explain that deleting a processing item may hide the UI record while the active worker finishes silently if MVP task cancellation is not yet reliable.

## Development

```bash
npm install
npm run dev
npm run build
```

Set `VITE_API_URL` to the deployed or local FastAPI API base URL.
