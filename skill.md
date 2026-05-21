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

Audit and fix local/prod TranscriptionView mismatch + remove automatic drum tab generation.

Problems:

1. Local and production TranscriptionViewer UI/behavior are not the same.
2. Drum stem still has code that auto-generates tabs/score output. Drums should only show rhythm lane / drum rhythm output, not guitar-style tabs.

Scope:

- Frontend and backend audit.
- Do not redesign UI.
- Do not change unrelated layout/playback behavior.

Tasks:

1. Compare local vs production TranscriptionView behavior

- Inspect:
  - `frontend/src/pages/TranscriptionViewer.tsx`
  - viewer child components
  - `frontend/src/services/audioService.ts`
  - deployed env/API base URL config
  - backend response payload serializers
- Check if local and prod use different:
  - API URLs
  - feature flags
  - status fields
  - cached build output
  - demo/sample data
  - conditional rendering logic
  - environment variables

Fix:

- Make viewer rendering depend on the same API fields in both local and prod.
- Ensure local and prod use the same UI code path.
- Remove stale conditionals that behave differently by environment unless truly required.

2. Remove automatic tab generation for drums

- Search the repo for drum-related auto tab generation logic:
  - `selected_stem === "drums"`
  - `"drums"`
  - `"drum"`
  - `generate_tabs`
  - `tab_file_path`
  - `can_generate_score`
  - `can_generate_tab`
  - `rhythm_lane`
  - `detected_onset_count`
- Backend:
  - Drums should not trigger Basic Pitch tab/note generation.
  - Drums should not create guitar/bass TAB output.
  - Drums should only create rhythm/onset/rhythm lane data.
  - `can_generate_score` should be false for drums unless it means rhythm lane only.
- Frontend:
  - For selected stem `drums`, show `Generate Rhythm` only.
  - Do not show `Generate Tabs`.
  - Do not show guitar-style TAB as ready for drums.
  - Show drum rhythm lane/status/output only.
  - Badges should say `Rhythm Ready`, not `Tab Ready`, for drums.
- Demo data:
  - If demo/sample drum project includes fake tab-ready flags, update it to rhythm-only.

3. State/status rules

- Guitar/other/bass:
  - may generate tabs/score.
- Drums:
  - rhythm lane only.
  - no automatic tab generation.
- Vocals:
  - lyrics only.
  - no tabs/score/rhythm.

4. API payload consistency

- Verify `/audio/{id}/result`, `/audio/{id}/status`, dashboard/list endpoints return consistent fields.
- If prod viewer uses dashboard payload first and local uses result payload, normalize both.
- Ensure `selected_stem`, `available_exports`, `can_generate_score`, `tab_file_path`, `notes_json`, `rhythm_data`, and `processing_status` mean the same thing across endpoints.

Acceptance:

- Local and prod TranscriptionViewer show the same layout and button logic for the same API payload.
- Drum projects never display or auto-generate guitar-style tabs.
- Drum projects show only rhythm lane / rhythm generation.
- Guitar/bass/other projects still support Generate Tabs/Score.
- Vocals still support Generate Lyrics only.
- `npm run build` passes.
- Report exact files changed and removed drum auto-tab code paths.
