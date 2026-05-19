## Plan: Fix Windows YouTube audio path handling

TL;DR: Normalize backend upload paths using pathlib and OS-native paths, map Docker-style `/app/uploads` to local backend uploads on Windows, validate downloaded files before save/move, and add a regression test.

**Steps**

1. Update `backend/app/services/storage.py`:
   - Change `normalize_local_path` to return OS-native local paths instead of forced POSIX strings.
   - Add Windows-specific handling for paths starting with `/app/uploads` so they map to the local backend `uploads` directory.
   - Keep path normalization robust for backslashes, absolute paths, and relative paths.
2. Update `backend/app/api/v1/endpoints/audio.py`:
   - Change `UPLOAD_DIR` initialization to use `Path(storage.normalize_local_path(core.config.settings.UPLOAD_DIR)).resolve()`.
   - Add explicit logs after yt-dlp download for expected output path, actual downloaded path, and normalized path.
   - In `_move_source_to_transcription_scratch`, validate `source.exists()` before `shutil.move`, log source/destination details, and if missing map Windows `/app/uploads/...` to local dir.
   - Catch move failures in the YouTube upload endpoint and mark the transcription as `failed` with `processing_error` instead of leaving it queued.
3. Add regression test in `backend/tests/test_audio_list_endpoint.py`:
   - Test that a Windows-style `/app/uploads/...` path is normalized to the local backend uploads directory when the code is running in Windows mode.

**Relevant files**

- `backend/app/services/storage.py` — normalize local paths and Windows `/app/uploads` mapping
- `backend/app/api/v1/endpoints/audio.py` — `UPLOAD_DIR` resolution, YouTube download logging, move validation, failure handling
- `backend/tests/test_audio_list_endpoint.py` — regression coverage for Windows-style local path normalization

**Verification**

1. Run the existing focused test that covers path normalization and source audio retrieval.
2. Add and run the new regression test for Windows-style `/app/uploads` normalization.
3. Optionally exercise the YouTube extraction path on Windows or by simulating the Windows path mapping logic.

**Decisions**

- This fix is scoped to Windows local backend path normalization and YouTube download handling only.
- No changes are planned for Demucs, Basic Pitch, UI, or queue orchestration.
