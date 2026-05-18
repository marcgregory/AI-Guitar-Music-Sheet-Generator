# MusicStudio Frontend

React + TypeScript frontend for the AI Guitar Music Sheet Generator / MusicStudio app.

## MVP Flow

Supported MVP input types:

1. Audio upload
2. YouTube URL

Before starting upload or YouTube processing, the user must choose a target Demucs stem:

- `vocals`
- `drums`
- `bass`
- `other`

For MVP guitar transcription, the UI should guide users to choose `other`. The copy should clearly explain that guitar, piano, and accompaniment may be grouped inside `other` with default Demucs models. True separate guitar, lead/rhythm guitar, and piano stems are future model upgrades.

Primary flow:

```txt
Audio Upload / YouTube URL
-> User selects target stem
-> Demucs separates selected stem
-> Pitch/rhythm detection runs on separated stem
-> Generate instrument-aware tabs/notation/rhythm data
-> Render synchronized playback with playhead/waveform
-> Export generated outputs
```

The frontend should show queue-aware processing states:

- `pending`
- `queued`
- `processing`
- `completed`
- `completed_with_warning`
- `failed`

If another job is active, show that the new job is queued or waiting. In production-like MVP mode, Railway coordinates the job while Modal/serverless GPU performs the selected-stem processing.

Completed outputs should use the Cloudinary-hosted URLs returned by the backend:

- `original_audio_url` for source playback when needed
- `separated_audio_url` for selected-stem playback
- `midi_file_url` for MIDI download where supported
- `musicxml_file_url` for MusicXML download where supported
- `tab_file_url` for TAB download where supported

If the backend finds an existing completed result for the same song and selected stem, the frontend should load that result instead of showing a new processing job. Display:

"This song and stem were already processed. Existing result was loaded."

## UI Requirements

- Add a required stem selector before the process action.
- Prefer Demucs-supported labels first: vocals, drums, bass, other.
- Use friendly helper text for `other`: "Best MVP choice for guitar or piano, depending on the mix."
- Do not imply the MVP can reliably split lead guitar, rhythm guitar, and piano into separate stems.
- In the viewer, emphasize the selected stem output rather than a full multi-stem mixer by default.
- Render guitar/`other` as 6-string tablature.
- Render `bass` as 4-string E A D G bass tablature.
- Render `drums` as a rhythm lane/percussion tab.
- Render `vocals` as playback-only.
- Display queue status clearly when `processing_status` is `queued`.
- Display downloadable Cloudinary-hosted outputs only when their URL fields are present.
- Add a delete button for completed, completed_with_warning, failed, queued, and processing items.
- Show confirmation before deleting a record.
- Explain that deleting a processing item may hide the UI record while the active worker finishes silently if MVP task cancellation is not yet reliable.

## Synchronization Requirements

Playback must support:

- moving playhead
- note highlighting
- waveform sync
- seek synchronization
- shared `currentTime`
- tab/score sync
- stem playback sync

Do not use separate timers for waveform, tabs, and score. The selected-stem audio element or shared transport state should be the source of truth for synchronized UI updates.

Highest frontend priorities:

1. selected stem playback sync
2. synchronized tab highlighting
3. synchronized score highlighting
4. waveform sync
5. instrument-aware rendering
6. stem metadata visibility
7. drum rhythm lane rendering
8. bass tab rendering

## Future Roadmap Only

- MIDI import
- Guitar Pro import
- PowerTab import/export
- Imported project editing
- Imported multi-track workflows

MIDI export, MusicXML export, and TAB export remain in scope when generated from separated-stem transcription results.

## Development

```bash
npm install
npm run dev
npm run build
```

Set `VITE_API_URL` to the deployed or local FastAPI API base URL.
