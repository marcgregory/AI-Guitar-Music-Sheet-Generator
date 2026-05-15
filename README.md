# AI Multi-Instrument Sheet and Stem Studio

An AI-powered web application that combines Moises-style stem separation with Songsterr-style synchronized playback, notation, tabs, and per-instrument practice tools.

## Project Structure

- `backend/` - Python/FastAPI backend with audio processing
- `frontend/` - React + TypeScript frontend interface

## Environment Variables

- Frontend uses `VITE_API_URL` to connect to the backend API.
- For Vercel deployment, set `VITE_API_URL` in your Vercel project settings to your deployed backend URL, e.g. `https://your-backend-xxxxx.railway.app/api/v1`.
- Do not deploy local-only values such as `VITE_FFMPEG_LOCATION=C:\ffmpeg\bin` to Vercel.
- Use `frontend/.env.example` as a template for local development.

## Technology Stack

See [tech-stack.md](tech-stack.md) for detailed technology recommendations.

## Implementation Plan

See [implementation-plan.md](implementation-plan.md) for phased implementation approach.

## Scope Document

See [ai_guitar_music_sheet_generator_scope.md](ai_guitar_music_sheet_generator_scope.md) for the current multi-instrument project scope and features.
