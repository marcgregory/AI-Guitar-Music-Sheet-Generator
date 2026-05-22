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

### Additional Responsive Regression Fixes From Screenshots

1. Ultra-wide desktop width issue

   Problem:
   At 2000px+ screens, landing/auth pages stretch too wide and the composition becomes disconnected.

   Requirements:
   - Add a max-width wrapper for large desktop content.
   - Use a shared container like `--app-container-width` / `.app-container`.
   - Cap hero/auth/landing content around a sane max width, e.g. `1440px-1680px`.
   - Center the capped content with `margin-inline: auto`.
   - Do not let auth split, hero preview, workflow sections, or landing cards stretch endlessly across ultra-wide screens.

2. Navbar/hero alignment issue

   Problem:
   Navbar content is not aligned with hero content.

   Requirements:
   - Navbar inner container and hero inner container must use the same max-width and horizontal padding system.
   - Logo/nav links/CTA should align with the hero left/right edges.
   - Do not use separate random padding values for nav and hero.
   - Use one shared container rule for:
     - public nav inner
     - hero inner
     - landing sections
     - auth split page

3. Desktop hero regression

   Problem:
   Hero content is pushed too far left and preview/player floats awkwardly.

   Requirements:
   - Restore intentional desktop composition.
   - Hero should use a balanced two-column grid on desktop.
   - Left copy and right preview must stay visually aligned.
   - At tablet/mobile, switch to stacked layout.
   - At ultra-wide, keep the whole hero centered and capped.

4. Workflow/cards section regression

   Problem:
   Workflow cards and section content do not align with the same page grid.

   Requirements:
   - Workflow section must use same shared container width/padding as nav and hero.
   - Cards should not start at random page edges.
   - On desktop, keep clean grid.
   - On mobile, stack cards with proper spacing.

5. Mobile hero preview height regression

   Problem:
   On mobile, the hero/player preview card becomes extremely tall and dominates the whole viewport.

   Requirements:
   - Mobile hero preview must not use desktop fixed height or an oversized aspect ratio.
   - Cap preview height on mobile, e.g. `max-height: 420px`.
   - Use `aspect-ratio` instead of fixed height where possible.
   - Scale and position decorative preview content inside the card without increasing page height.
   - Stack hero copy and preview cleanly.
   - Keep the preview readable, but do not let it consume the entire mobile screen.
   - Navbar remains compact at top.

   Suggested CSS direction:
   - Under mobile breakpoints, `.hero-preview`, `.hero-player`, and `.landing-preview` should use `height: auto`, `max-height: 420px`, `aspect-ratio: 4 / 5` or `3 / 4`, and `overflow: hidden`.
   - Reduce inner decorative spacing on mobile.
   - Remove desktop transforms or large rotations when they cause height overflow.

6. Auth/login/register height regression

   Problem:
   Login/register pages become too tall and poster-like. The form panel and marketing panel stretch vertically instead of fitting cleanly.

   Requirements:
   - Auth shell must not force full desktop-height composition on tablet/mobile.
   - Cap auth panels on large screens with shared max-width.
   - On tablet/mobile, stack or simplify the split layout.
   - Form card should stay compact and vertically centered.
   - Marketing/visual panel should reduce height or move above/below form.
   - Avoid `min-height: 100vh` causing huge empty vertical space when content is smaller.
   - Use `min-height: auto` or `min-height: calc(100svh - navHeight)` only where needed.
   - Use `svh` instead of `vh` for mobile viewport stability.

   Suggested CSS direction:
   - `.auth-shell`, `.auth-page`, and `.auth-split` should be centered and max-width capped on desktop.
   - On tablet/mobile, use `grid-template-columns: 1fr`.
   - On mobile, reduce padding block and use `min-height: auto`.
   - `.auth-visual-panel` should use `max-height: 320px-420px` or hide decorative overflow on tablet/mobile.
   - `.auth-form-panel` should use `max-width: 420px-480px`, `margin-inline: auto`, `height: auto`, and `align-self: center`.

Acceptance:

- 1440px desktop looks close to the original intended design.
- 2000px+ screens do not stretch the page endlessly.
- Navbar, hero, auth, workflow, and landing sections share one consistent container alignment.
- No document-level horizontal scroll remains.
- At 320-425px width, the hero preview fits comfortably within one screen section and does not become a long vertical poster.
- At 320-768px width, login and register forms are reachable quickly and panels stack cleanly without extra-long poster layouts.

Main rule: fix width with max-width containers, not by scaling the whole UI or letting sections stretch forever.

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

**Plan: Implement TranscriptionViewer Consistency + Drum Rhythm Only**

**Summary**

- Normalize API capabilities so local/prod viewer decisions come from the same fields.
- Keep selected-stem processing playback-first: initial processing separates the stem and marks it ready.
- Make drums rhythm-only across API, workers, UI labels, badges, exports, and tests.
- Before adding new fields or logic, audit existing implementations and reuse/normalize them. Do not create duplicate status fields, duplicate capability helpers, or parallel UI conditions.

**Backend Changes**

- In `backend/app/api/v1/endpoints/audio.py`, make `_metadata_payload` the source of truth for list, demo, result, and status payload capability fields.
- All viewer-driving booleans must be computed consistently in one place. No endpoint should manually override drum/tab/export capability fields after `_metadata_payload`.
- Narrow `_finalize_status_response_for_mode` to only adjust harmless queue messages; do not change viewer-driving fields such as `can_generate_score`, `available_exports`, generation statuses, `output_mode`, or stem metadata.
- Enforce drum payload semantics:
  - `can_generate_score: false`
  - `can_generate_tab: false`
  - `can_generate_rhythm: true` when drum rhythm data exists or rhythm generation is available from a stem-ready drum record
  - `available_exports: []`
  - `output_mode: "rhythm"` with hits, otherwise `"playback_only"` when stem audio exists.
- Keep `/audio/{id}/generate-tabs`, but branch wording/status:
  - drums set/use `rhythm_generation_status` and return rhythm wording
  - bass/other set/use `tab_generation_status`
  - vocals remain unsupported.

**Worker Changes**

- In `backend/app/tasks.py`, keep `process_audio_transcription` as separation-only/stem-ready, with no automatic drum rhythm, tab, MIDI, or score generation during initial processing.
- Update manual generation so drums call only `audio.analyze_drum_rhythm`, store hits in `notes_data` and selected track `notes_json`, clear all tab/MIDI/notation fields, and keep `can_generate_score` false.
- Guard `generate_derived_outputs` so `selected_stem in {"drums", "vocals"}` returns without creating MIDI/TAB artifacts.
- In `backend/modal_worker.py`, ensure `generate_tab` jobs for drums return rhythm data only and never include `tablature_data`, `tab_file_url`, `tab_file_public_id`, `midi_file_url`, or `midi_file_public_id`.

**Frontend Changes**

- In `frontend/src/utils/transcriptionMetadata.ts`, make drum capability badges mutually exclusive from TAB:
  - drums never show `TAB READY`
  - drums show `RHYTHM READY` when rhythm hits/data exist or backend `can_generate_rhythm` is true.
- Do not infer TAB readiness from `notes_data` alone for drums. For drums, notes/hits mean rhythm data only.
- In `frontend/src/components/TranscriptionViewer.tsx`, drive rendering only from normalized payload fields:
  - `other`/`bass`: Generate Tabs, score/tab views, and exports.
  - `drums`: Generate Rhythm only, rhythm output only, no TAB export/button/readiness.
  - `vocals`: Generate Lyrics only.
- Rename visible drum “tabs” copy to rhythm wording without changing layout structure.
- In `frontend/src/components/ProcessingStatus.tsx` and `frontend/src/components/auth/Dashboard.tsx`, make stem-ready copy stem-aware so drums mention rhythm generation, bass/other mention tabs, vocals mention lyrics.
- Apply only a minimal text-fitting fix if needed for the existing Generate Tabs/Rhythm button so labels do not clip.

**Tests**

- Backend:
  - Add/adjust tests in `backend/tests/test_audio_list_endpoint.py` for drum list/result/status payload parity.
  - Assert drum payloads have no exports, no score/tab capability, and correct rhythm capability/output mode.
  - Assert `/generate-tabs` on drums queues rhythm generation and returns rhythm wording/status.
  - Keep/assert drum MIDI/TAB endpoints are unsupported.
  - Add/adjust `backend/tests/test_music_output_services.py` so manual drum rhythm generation never calls pitch/tab generation and never creates `tab_file_path`.
- Frontend:
  - Update `frontend/src/components/TranscriptionViewer.test.tsx` to cover drum Generate Rhythm, no Generate Tabs, Rhythm Ready without Tab Ready, no TAB download, bass/other Generate Tabs, and vocals Generate Lyrics.
- Verification:
  - Run targeted backend tests for audio endpoints and music output services.
  - Run frontend tests if configured.
  - Run `npm run build`.

**Assumptions**

- Keep the route name `/generate-tabs` for backward compatibility, but stem-aware messages may say rhythm for drums.
- Demo remains guitar unless an existing drum demo/sample record has fake tab-ready fields; any such record should be changed to rhythm-only.
- No UI redesign or unrelated playback/layout changes.

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

### Additional Responsive Regression Fixes From Screenshots

1. Ultra-wide desktop width issue

   Problem:
   At 2000px+ screens, landing/auth pages stretch too wide and the composition becomes disconnected.

   Requirements:
   - Add a max-width wrapper for large desktop content.
   - Use a shared container like `--app-container-width` / `.app-container`.
   - Cap hero/auth/landing content around a sane max width, e.g. `1440px-1680px`.
   - Center the capped content with `margin-inline: auto`.
   - Do not let auth split, hero preview, workflow sections, or landing cards stretch endlessly across ultra-wide screens.

2. Navbar/hero alignment issue

   Problem:
   Navbar content is not aligned with hero content.

   Requirements:
   - Navbar inner container and hero inner container must use the same max-width and horizontal padding system.
   - Logo/nav links/CTA should align with the hero left/right edges.
   - Do not use separate random padding values for nav and hero.
   - Use one shared container rule for:
     - public nav inner
     - hero inner
     - landing sections
     - auth split page

3. Desktop hero regression

   Problem:
   Hero content is pushed too far left and preview/player floats awkwardly.

   Requirements:
   - Restore intentional desktop composition.
   - Hero should use a balanced two-column grid on desktop.
   - Left copy and right preview must stay visually aligned.
   - At tablet/mobile, switch to stacked layout.
   - At ultra-wide, keep the whole hero centered and capped.

4. Workflow/cards section regression

   Problem:
   Workflow cards and section content do not align with the same page grid.

   Requirements:
   - Workflow section must use same shared container width/padding as nav and hero.
   - Cards should not start at random page edges.
   - On desktop, keep clean grid.
   - On mobile, stack cards with proper spacing.

5. Mobile hero preview height regression

   Problem:
   On mobile, the hero/player preview card becomes extremely tall and dominates the whole viewport.

   Requirements:
   - Mobile hero preview must not use desktop fixed height or an oversized aspect ratio.
   - Cap preview height on mobile, e.g. `max-height: 420px`.
   - Use `aspect-ratio` instead of fixed height where possible.
   - Scale and position decorative preview content inside the card without increasing page height.
   - Stack hero copy and preview cleanly.
   - Keep the preview readable, but do not let it consume the entire mobile screen.
   - Navbar remains compact at top.

   Suggested CSS direction:
   - Under mobile breakpoints, `.hero-preview`, `.hero-player`, and `.landing-preview` should use `height: auto`, `max-height: 420px`, `aspect-ratio: 4 / 5` or `3 / 4`, and `overflow: hidden`.
   - Reduce inner decorative spacing on mobile.
   - Remove desktop transforms or large rotations when they cause height overflow.

6. Auth/login/register height regression

   Problem:
   Login/register pages become too tall and poster-like. The form panel and marketing panel stretch vertically instead of fitting cleanly.

   Requirements:
   - Auth shell must not force full desktop-height composition on tablet/mobile.
   - Cap auth panels on large screens with shared max-width.
   - On tablet/mobile, stack or simplify the split layout.
   - Form card should stay compact and vertically centered.
   - Marketing/visual panel should reduce height or move above/below form.
   - Avoid `min-height: 100vh` causing huge empty vertical space when content is smaller.
   - Use `min-height: auto` or `min-height: calc(100svh - navHeight)` only where needed.
   - Use `svh` instead of `vh` for mobile viewport stability.

   Suggested CSS direction:
   - `.auth-shell`, `.auth-page`, and `.auth-split` should be centered and max-width capped on desktop.
   - On tablet/mobile, use `grid-template-columns: 1fr`.
   - On mobile, reduce padding block and use `min-height: auto`.
   - `.auth-visual-panel` should use `max-height: 320px-420px` or hide decorative overflow on tablet/mobile.
   - `.auth-form-panel` should use `max-width: 420px-480px`, `margin-inline: auto`, `height: auto`, and `align-self: center`.

Acceptance:

- 1440px desktop looks close to the original intended design.
- 2000px+ screens do not stretch the page endlessly.
- Navbar, hero, auth, workflow, and landing sections share one consistent container alignment.
- No document-level horizontal scroll remains.
- At 320-425px width, the hero preview fits comfortably within one screen section and does not become a long vertical poster.
- At 320-768px width, login and register forms are reachable quickly and panels stack cleanly without extra-long poster layouts.

Main rule: fix width with max-width containers, not by scaling the whole UI or letting sections stretch forever.

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

Implement this after the drum rhythm-only fix.
Do not change upload/stem separation flow.
Do not set main `processing_status = "processing"` during manual tab/rhythm generation if the separated stem is already playable.
Use `tab_generation_status` / `rhythm_generation_status` as the UI progress source.
Only call Celery `update_state` when a real `task.request.id` exists.

Ready. Use this as the implementation instruction:

> Implement exactly this plan. Audit first. Do not redesign UI. Do not create duplicate capability fields/helpers. Backend `_metadata_payload` is the viewer contract. Frontend renders only from normalized response fields. Drums must never be treated as tablature-capable even when `notes_data` exists. After changes, run targeted backend tests, frontend tests if available, and `npm run build`.

Test order:

1. Local drum stem-ready
2. Local drum Generate Rhythm
3. Bass/other Generate Tabs
4. Vocals Generate Lyrics
5. Prod/staging same behavior

Compare LOCAL vs PROD API JSON for the same transcription:

- notes_data
- tablature_data
- notes_json
- detected_note_count
- average_note_confidence
- processing_version/config if available

Then force-regenerate tabs in prod after clearing old generated tab artifacts.

GET {LOCAL_API_URL}/audio/{LOCAL_TRANSCRIPTION_ID}/status
GET {PROD_API_URL}/audio/{PROD_TRANSCRIPTION_ID}/status

First compare local and prod API JSON using separate local/prod transcription IDs.
Only if prod has stale generated tab artifacts and the stem is tab-capable, clear generated DB artifact fields and trigger prod regeneration.

Before DB mutation, print the exact fields and values that will be cleared, then require execution to continue only if the script is running in explicit `--apply` mode. Default mode must be dry-run.

#==============
Yes — the login card/container is too tall on large screens.

Use this fix prompt:

```md
Fix the login/auth page height on large screens.

Problem:
On desktop/large screens, the auth layout becomes too tall and stretched vertically. The main split card should fit comfortably inside the viewport without looking oversized.

Tasks:

- Inspect the auth/login page layout and CSS first.
- Find the outer auth wrapper, split panel/card, left hero panel, and right login panel styles.
- Add a responsive max-height for desktop, e.g. `min(92vh, 820px)` or similar.
- Avoid fixed huge heights like `100vh` inside the card content.
- Make the auth shell vertically centered with safe padding.
- Ensure the card does not overflow on 1366x768 / 1440x900 / 1920x1080.
- Keep mobile layout unchanged.
- If content exceeds height, allow internal scrolling only where needed.
- Keep the current design, colors, typography, and split layout.

Acceptance:

- On large screens, the login card is shorter and balanced.
- Top and bottom spacing look even.
- No clipped content.
- Mobile still works.
```

Likely CSS direction:

```css
.auth-shell {
  min-height: 100dvh;
  padding: clamp(16px, 3vw, 32px);
  display: grid;
  place-items: center;
}

.auth-card {
  width: min(100%, 1100px);
  height: min(92dvh, 820px);
  max-height: 820px;
}
```

Important:

- Inspect existing auth CSS first.
- Do not change JSX/components.
- Do not change colors, typography, gradients, card styling, or copy.
- Apply desktop height cap only above the existing split-layout breakpoint.
- Mobile/tablet stacked layout must keep existing behavior.

#==================tabs issue

Use this updated prompt instead:

```txt
Fix prod tab generation using original audio instead of selected stem, and prevent collapsed/single-line TAB fallback.

Root causes:
1. Prod Generate Tabs may be analyzing original_audio_url/audio_file_path instead of the selected separated stem.
2. Frontend only renders real multi-string TAB when `tablature_data.tablature` exists.
3. Some prod completed bass/other rows have notes_data but missing/empty/malformed `tablature_data`, so viewer falls back to note-only/one-line layout.

Tasks:

1. Enforce Generate Tabs stem-only input
- Audit local task and Modal worker generate_tab path.
- For selected_stem `bass` or `other`, Generate Tabs must load audio from:
  1. `separated_audio_url`
  2. `separated_audio_file_path`
- Do not fall back to `original_audio_url` or `audio_file_path`.
- If no separated stem exists, fail tab generation with a clear error:
  `Separated stem audio is required before generating tabs.`
- Log the exact source used:
  `tab_generation_audio_source=separated_audio_url|separated_audio_file_path|missing`

2. Repair/persist structured tablature
- Add backend helper for selected_stem `bass`/`other` only.
- If notes_data has note events and tablature_data is missing, invalid, or has empty `tablature`, call:
  `tablature.notes_to_tablature(notes_data, instrument_type="bass"|"guitar")`
- Persist result to `Transcription.tablature_data`.
- Call this helper in worker completion and before returning `/audio/{id}/result` and `/audio/{id}/status`.

3. Prevent false completed status
- If selected_stem is `bass`/`other`
- and notes_data exists
- but structured tablature cannot be generated
- do not mark `tab_generation_status` as `completed`.
- Use `failed` or `completed_with_warning`.

4. Cleanup original Cloudinary audio after full flow completes
- After selected-stem processing and manual generation complete successfully:
  - delete only `original_audio_public_id` from Cloudinary
  - set `original_audio_url = null`
  - set `original_audio_public_id = null`
- Do not delete:
  - `separated_audio_url`
  - `separated_audio_public_id`
  - `midi_file_url`
  - `tab_file_url`
  - `notes_data`
  - `tablature_data`
- Local temp cleanup and Cloudinary cleanup must be separate.

5. Do not change frontend layout
- No redesign.
- No CSS changes.
- Keep drums/vocals behavior unchanged.

Regression tests:
1. Generate Tabs source selection:
- completed/stem_ready bass or other transcription
- has separated_audio_url
- has original_audio_url
- generate-tabs uses separated stem, not original audio

2. Missing stem:
- bass/other generate-tabs with no separated_audio_url/file
- returns clear failure and does not silently analyze original audio

3. Structured tablature repair:
- completed bass/other transcription
- notes_data exists
- tablature_data is null
- result endpoint returns and persists non-empty `tablature_data.tablature`

4. Cloudinary cleanup:
- after full successful flow
- original_audio_public_id is deleted/null
- separated stem and exports remain

Expected:
- Prod Generate Tabs analyzes the selected separated stem only.
- Prod always returns non-empty structured `tablature_data.tablature` when tab generation succeeds.
- Frontend renders proper multi-string TAB lines instead of one-line fallback.
- Original uploaded audio is removed from Cloudinary only after the full flow is safely completed.
```
