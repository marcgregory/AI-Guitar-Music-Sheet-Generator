# Admin Access + History Filters

## Goal

Make `/admin/jobs` clearer and safer by adding a visible local admin-token clearing action and server-side History filters for terminal admin jobs.

## Requirements

- Add a visible `Forget admin token` action in the admin Jobs dashboard.
- The action must remove only `musicstudio_admin_token`, clear the token input, clear admin errors, reset loaded active and history jobs, and clear the last sync timestamp.
- Add History-only filters for status and limit.
- History status options are `All`, `Completed`, `Completed with warning`, and `Failed`.
- History limit options are `25`, `50`, and `100`, with `50` as the default.
- Reload History when the active History status or limit changes.
- Send History filters to the backend as query params; do not filter or slice locally.
- Backend status filtering must apply to `Transcription.processing_status`.
- Keep the existing admin history terminal inclusion rules and ordering.

## Strict Non-Goals

- Do not change `/admin/jobs` route protection.
- Do not change Jobs nav visibility behavior.
- Do not revoke the backend token.
- Do not change backend token semantics.
- Do not remove or modify `musicstudio_admin_mode`.
- Do not change existing terminal history inclusion rules.
- Do not change history ordering.

## Touched Areas

- `frontend/src/components/admin/AdminJobsDashboard.tsx`
- `frontend/src/services/audioService.ts`
- `backend/app/api/v1/endpoints/admin.py`
- `backend/tests/test_admin_jobs_endpoint.py`
- `frontend/src/components/admin/AdminJobsDashboard.test.tsx`

## Verification Commands

```bash
python -m pytest backend/tests/test_admin_jobs_endpoint.py
npm test -- AdminJobsDashboard
npm run build
```
