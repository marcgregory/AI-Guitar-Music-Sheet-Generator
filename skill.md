# MusicStudio Project Rules

Use these rules for future agent work in this repo.

## Current Product Direction

- This is an AI Guitar Music Sheet / MusicStudio selected-stem MVP.
- Users upload audio or submit a YouTube URL, then select exactly one stem: `vocals`, `drums`, `bass`, or `other`.
- `vocals`: selected-stem playback plus Generate Lyrics with faster-whisper. Track lyric work with `lyrics_generation_status`, separate from main audio `processing_status`.
- `other` and `bass`: Generate Tabs with Basic Pitch-style note detection and existing non-vocal behavior.
- `drums`: rhythm/onset lane only; do not route drums through Basic Pitch-style melodic note detection.
- Multi-track Songsterr-level output, advanced Guitar Pro notation, and imported MIDI/GP workflows are future scope.

## Runtime Rules

- Hosted backend services should use `AUDIO_PROCESSING_MODE=modal`.
- Railway/Render should handle API, auth, DB access, status polling, Cloudinary metadata, and Modal dispatch/callbacks.
- Modal handles heavy audio/AI processing: selected-stem separation, stem-specific generation, Cloudinary output uploads, and retry/rate-limit handling.
- Cloudinary stores uploaded source audio, selected separated stems, and generated exports.
- One global processing job at a time is preferred for MVP stability.
- YouTube processing may require fresh `YOUTUBE_COOKIES` or `YOUTUBE_COOKIES_FILE`.

## Frontend Rules

- Do not do random UI rewrites.
- Preserve existing viewer and playback interactions.
- Do not add duplicate audio players.
- Keep selected-stem playback visible even when notation generation is unavailable.
- Poll `/status` first and call `/result` only after a ready status such as `stem_ready`, `completed`, or `completed_with_warning`.
- Generate Lyrics must not send the viewer back to the processing screen.
- Non-vocal Generate Tabs behavior must remain unchanged unless the user explicitly asks to change it.

## Critical Responsive Layout Rules

- Do not solve responsive issues by compressing desktop layouts indefinitely.
- Do not hide responsive bugs using excessive `overflow-x: hidden`.
- Preserve desktop compositions until intentional breakpoint transitions occur.
- Components must stack, wrap, or switch layouts before becoming unreadable or unusable.
- Prevent ultra-compressed/squeezed layouts in:
  - nav groups
  - auth layouts
  - hero sections
  - waveform/player surfaces
  - dashboard cards
  - viewer panels

### Required Constraints

- Cards/panels:
  - `min-width: min(100%, 280px)`
- Larger viewer/auth/player surfaces:
  - `min-width: min(100%, 320px)`
- Nav groups/action clusters:
  - use `flex-shrink: 0` where appropriate
- Shrinkable flex/grid children:
  - use `min-width: 0`

### Responsive Behavior Rules

- Switch multi-column layouts to stacked layouts earlier.
- Preserve hero readability and cinematic spacing.
- Auth split layouts must become vertical on tablet/mobile instead of compressing horizontally.
- Large waveform/player/score areas should stack vertically before becoming unusable.
- Prefer wrapping and layout transitions over shrinking/scaling.

### Do Not

- Blindly reduce scale
- Compress typography excessively
- Squeeze desktop sections into mobile widths
- Hide layout bugs using overflow clipping

## Known Limitations

- Automatic tabs are experimental.
- Lyrics accuracy depends on vocal stem quality and faster-whisper settings.
- Bends, slides, harmonics, let-ring markings, and exact rhythm notation are not guaranteed.
- Advanced Guitar Pro/Songsterr-style notation is future work.

## Roadmap

- AlphaTab or VexFlow renderer.
- Better quantization.
- Chord grouping.
- Fingering optimizer.
- MusicXML/GP-like export.
- Manual correction editor.
- Better lyrics model settings.
