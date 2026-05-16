from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Response, Body, UploadFile, File
import json
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import os
import uuid
from pathlib import Path
import re
import tempfile
import yt_dlp
from pydantic import BaseModel

from .... import db, core, models
from ....core.security import get_current_user
from .. import schemas
from ....services import audio
from ....services import midi
from ....services import tablature as tablature_service
from ....services.tablature import tablature_to_ascii_tab
from ....celery import celery_app

# Schema for YouTube URL request
class YouTubeUploadRequest(BaseModel):
    youtube_url: str
    project_id: int = None

router = APIRouter()

# Define the upload directory relative to the backend package so the location is
# stable whether uvicorn is launched from the repo root or from backend/.
BACKEND_DIR = Path(__file__).resolve().parents[4]
UPLOAD_DIR = BACKEND_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

import logging
import traceback

logger = logging.getLogger(__name__)


def _run_transcription_locally(transcription_id: int):
    """Run transcription without a Celery broker for local development."""
    from ....tasks import process_audio_transcription

    original_update_state = process_audio_transcription.update_state
    process_audio_transcription.update_state = lambda *args, **kwargs: None
    try:
        process_audio_transcription.run(transcription_id)
    except Exception as e:
        logger.error(
            "Local transcription task failed for transcription %s: %s",
            transcription_id,
            e,
        )
    finally:
        process_audio_transcription.update_state = original_update_state


def _run_instrument_track_reprocess_locally(track_id: int):
    """Run one track reprocess without a Celery broker for local development."""
    from ....tasks import reprocess_instrument_track

    original_update_state = reprocess_instrument_track.update_state
    reprocess_instrument_track.update_state = lambda *args, **kwargs: None
    try:
        reprocess_instrument_track.run(track_id)
    except Exception as e:
        logger.error(
            "Local instrument track reprocess failed for track %s: %s",
            track_id,
            e,
        )
    finally:
        reprocess_instrument_track.update_state = original_update_state


def _start_transcription_processing(
    transcription_id: int,
    background_tasks: BackgroundTasks,
    db_session: Session,
):
    """Start processing through Celery, with an in-process fallback for dev."""
    if _should_use_local_worker_fallback() and not _celery_has_available_worker():
        logger.warning(
            "No Celery worker is available; running transcription %s as a local background task",
            transcription_id,
        )
        background_tasks.add_task(_run_transcription_locally, transcription_id)
        return

    try:
        celery_app.send_task(
            "app.tasks.process_audio_transcription",
            args=[transcription_id]
        )
    except Exception as e:
        logger.warning(
            "Celery broker unavailable; falling back to local background task: %s",
            e,
        )
        background_tasks.add_task(_run_transcription_locally, transcription_id)


def _start_instrument_track_reprocess(
    track_id: int,
    background_tasks: BackgroundTasks,
):
    """Start one track reprocess through Celery, with an in-process dev fallback."""
    if _should_use_local_worker_fallback() and not _celery_has_available_worker():
        logger.warning(
            "No Celery worker is available; running track %s reprocess as a local background task",
            track_id,
        )
        background_tasks.add_task(_run_instrument_track_reprocess_locally, track_id)
        return

    try:
        celery_app.send_task(
            "app.tasks.reprocess_instrument_track",
            args=[track_id]
        )
    except Exception as e:
        logger.warning(
            "Celery broker unavailable; falling back to local track reprocess: %s",
            e,
        )
        background_tasks.add_task(_run_instrument_track_reprocess_locally, track_id)


def _has_note_events(notes_data: str | None) -> bool:
    if not notes_data:
        return False
    try:
        parsed = json.loads(notes_data)
    except json.JSONDecodeError:
        return False

    if isinstance(parsed, list):
        return len(parsed) > 0
    if isinstance(parsed, dict):
        notes = parsed.get("notes")
        pitch_info = parsed.get("pitch_info")
        return (
            isinstance(notes, list) and len(notes) > 0
        ) or (
            isinstance(pitch_info, list) and len(pitch_info) > 0
        )
    return False


def _notes_error(notes_data: str | None) -> str | None:
    if not notes_data:
        return None
    try:
        parsed = json.loads(notes_data)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict) and parsed.get("error"):
        return str(parsed["error"])
    return None


def _is_non_blocking_processing_warning(error: str | None) -> bool:
    """Warnings stored in processing_error should not make the whole job fail."""
    if not error:
        return False
    return error.startswith("Source separation unavailable; processed the full mix instead.")


def _should_use_local_worker_fallback() -> bool:
    return core.config.settings.ENVIRONMENT.lower() in {"development", "local", "test"}


def _celery_has_available_worker() -> bool:
    """Return True only when a worker answers quickly enough for local requests."""
    try:
        return bool(celery_app.control.ping(timeout=0.5))
    except Exception as e:
        logger.warning("Celery worker check failed; using local background task: %s", e)
        return False


def _blocking_processing_error(transcription: models.Transcription) -> str | None:
    error = transcription.processing_error
    if _is_non_blocking_processing_warning(error):
        return None
    return error


def _ensure_transcription_access(
    transcription: models.Transcription,
    db_session: Session,
    current_user: schemas.User,
) -> None:
    if transcription.user_id == current_user.id:
        return
    if transcription.project_id:
        project = db_session.query(models.Project).filter(
            models.Project.id == transcription.project_id
        ).first()
        if project and project.owner_id == current_user.id:
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not authorized to access this transcription"
    )


def _ensure_derived_outputs(transcription: models.Transcription, db_session: Session) -> None:
    """Regenerate downloadable/viewable outputs from stored notes when possible."""
    if not _has_note_events(transcription.notes_data):
        return

    changed = False

    if not transcription.midi_file_path or not os.path.exists(transcription.midi_file_path):
        transcription.midi_file_path = midi.save_midi_from_transcription(
            transcription.notes_data,
            transcription.id,
            str(UPLOAD_DIR),
        )
        changed = True

    if not transcription.notation_data and transcription.midi_file_path and os.path.exists(transcription.midi_file_path):
        try:
            transcription.notation_data = midi.midi_to_musicxml(transcription.midi_file_path)
            changed = True
        except Exception as e:
            logger.warning(
                "Could not regenerate MusicXML for transcription %s: %s",
                transcription.id,
                e,
            )

    if not transcription.tablature_data:
        transcription.tablature_data = json.dumps(
            tablature_service.notes_to_tablature(transcription.notes_data)
        )
        changed = True

    if changed:
        db_session.add(transcription)
        db_session.commit()
        db_session.refresh(transcription)


def _require_note_events_for_export(transcription: models.Transcription) -> None:
    if _has_note_events(transcription.notes_data):
        return

    notes_error = _notes_error(transcription.notes_data)
    detail = (
        f"Cannot generate exports because pitch detection failed: {notes_error}"
        if notes_error
        else "Cannot generate exports because no note events were detected."
    )
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _require_track_note_events_for_export(track: models.InstrumentTrack) -> None:
    if _has_note_events(track.notes_json):
        return

    notes_error = _notes_error(track.notes_json)
    detail = (
        f"Cannot generate exports for {track.display_name} because pitch detection failed: {notes_error}"
        if notes_error
        else f"Cannot generate exports for {track.display_name} because no note events were detected."
    )
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _get_accessible_transcription(
    transcription_id: int,
    db_session: Session,
    current_user: schemas.User,
) -> models.Transcription:
    transcription = db_session.query(models.Transcription).filter(
        models.Transcription.id == transcription_id
    ).first()

    if not transcription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcription not found"
        )

    _ensure_transcription_access(transcription, db_session, current_user)
    return transcription


def _has_active_transcription(user_id: int, db_session: Session) -> bool:
    active_transcriptions = (
        db_session.query(models.Transcription)
        .filter(models.Transcription.user_id == user_id)
        .filter(models.Transcription.is_processed == False)
        .all()
    )
    return any(
        transcription.processing_error is None
        or _is_non_blocking_processing_warning(transcription.processing_error)
        for transcription in active_transcriptions
    )


def _ensure_no_active_transcription(user_id: int, db_session: Session) -> None:
    if _has_active_transcription(user_id, db_session):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A transcription is already being processed. "
                "Please wait for it to finish before uploading another audio file."
            ),
        )


def _get_accessible_track(
    transcription_id: int,
    track_id: int,
    db_session: Session,
    current_user: schemas.User,
) -> tuple[models.Transcription, models.InstrumentTrack]:
    transcription = _get_accessible_transcription(transcription_id, db_session, current_user)
    track = db_session.query(models.InstrumentTrack).filter(
        models.InstrumentTrack.id == track_id,
        models.InstrumentTrack.transcription_id == transcription_id,
    ).first()

    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument track not found"
        )

    return transcription, track


def _ensure_track_export_ready(
    transcription: models.Transcription,
    track: models.InstrumentTrack,
    *,
    format_name: str,
) -> None:
    if not transcription.is_processed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcription is still processing"
        )

    blocking_error = _blocking_processing_error(transcription)
    if blocking_error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transcription failed: {blocking_error}"
        )

    supported_by_format = {
        "tab": {"guitar", "bass"},
        "midi": {"guitar", "bass", "piano"},
        "musicxml": {"guitar", "bass", "piano"},
    }
    supported_instruments = supported_by_format.get(format_name, set())
    if track.instrument_type not in supported_instruments:
        supported_label = (
            "guitar and bass"
            if format_name == "tab"
            else "guitar, bass, and piano"
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{track.display_name} exports are not available yet. "
                f"Per-track {format_name.upper()} export currently supports {supported_label} tracks."
            )
        )

    if track.processing_status == "failed" and not _has_note_events(track.notes_json):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{track.display_name} export is unavailable: {track.confidence_notes or 'track analysis failed'}"
        )

    _require_track_note_events_for_export(track)


def _prepare_track_reprocess(track: models.InstrumentTrack, db_session: Session) -> None:
    if track.instrument_type not in {"guitar", "bass", "piano", "drums"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{track.display_name} reprocessing is not available yet. "
                "Single-track reprocessing currently supports guitar, bass, piano, and drum tracks."
            )
        )

    if not track.stem_audio_path or not os.path.exists(track.stem_audio_path):
        track.processing_status = "failed"
        track.confidence_notes = "Stem audio file is missing; track reprocessing skipped."
        db_session.add(track)
        db_session.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{track.display_name} stem audio file is missing."
        )

    track.notes_json = None
    track.chords_json = None
    track.tab_json = None
    track.notation_json = None
    track.confidence_notes = None
    track.processing_status = "processing"
    db_session.add(track)
    db_session.commit()
    db_session.refresh(track)


def _track_export_filename(
    transcription_id: int,
    track: models.InstrumentTrack,
    extension: str,
) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", track.instrument_type.lower()).strip("_") or "track"
    return f"transcription_{transcription_id}_{slug}.{extension}"


def _track_notes_to_midi_bytes(track: models.InstrumentTrack) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as temp_file:
        temp_path = temp_file.name
    try:
        midi.notes_to_midi(track.notes_json, temp_path)
        with open(temp_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass

@router.post("/upload", response_model=schemas.TranscriptionInDB)
async def upload_audio_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    project_id: int = None,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Upload an audio file (MP3 or WAV) for transcription.
    """
    # Validate file extension
    file_extension = os.path.splitext(file.filename)[1].lower()
    if file_extension not in core.config.settings.ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File extension {file_extension} not allowed. Allowed extensions: {core.config.settings.ALLOWED_AUDIO_EXTENSIONS}"
        )

    # Read the file content
    contents = await file.read()

    # Validate file size
    if len(contents) > core.config.settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size too large. Maximum size is {core.config.settings.MAX_UPLOAD_SIZE} bytes"
        )

    # Prevent new uploads while another transcription is still processing
    _ensure_no_active_transcription(current_user.id, db_session)

    # Generate a unique filename to avoid collisions
    unique_filename = f"{uuid.uuid4().hex}{file_extension}"
    file_path = UPLOAD_DIR / unique_filename

    # Save the file to disk
    try:
        with open(file_path, "wb") as buffer:
            buffer.write(contents)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not save file: {str(e)}"
        )

    # Create a transcription record in the database
    # If project_id is provided, we need to check that the project exists and belongs to the user
    if project_id is not None:
        project = db_session.query(models.Project).filter(models.Project.id == project_id).first()
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found"
            )
        if project.owner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to upload to this project"
            )

    # Determine the title for the transcription (use filename if not provided)
    title = file.filename if file.filename else "Audio Upload"

    db_transcription = models.Transcription(
        title=title,
        audio_file_path=str(file_path),
        user_id=current_user.id,
        project_id=project_id,
        is_processed=False
    )
    db_session.add(db_transcription)
    db_session.commit()
    db_session.refresh(db_transcription)

    _start_transcription_processing(db_transcription.id, background_tasks, db_session)

    return db_transcription


def _find_ffmpeg_path():
    """Find ffmpeg location on the system."""
    import shutil
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return str(Path(ffmpeg_path).resolve().parent)
    # Fallback to known winget installation path
    winget_ffmpeg = Path(os.path.expanduser("~")) / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    for p in winget_ffmpeg.glob("Gyan.FFmpeg*/ffmpeg-*-full_build/bin"):
        if (p / "ffmpeg.exe").exists():
            return str(p.resolve())
    return None


def _build_youtube_download_options(unique_filename: str, ffmpeg_path: str | None):
    """Build yt-dlp options using a simple filename template for Windows."""
    options = {
        'format': 'bestaudio/best',
        'paths': {'home': str(UPLOAD_DIR)},
        'outtmpl': {'default': f'{unique_filename}.%(ext)s'},
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',
            'preferredquality': '192',
        }],
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'no_color': True,
        # Restrict to safe filesystem operations.
        'restrictfilenames': True,
        'windowsfilenames': True,
    }

    if ffmpeg_path:
        options['ffmpeg_location'] = ffmpeg_path

    return options


@router.post("/youtube", response_model=schemas.TranscriptionInDB)
async def extract_audio_from_youtube(
    request: YouTubeUploadRequest,
    background_tasks: BackgroundTasks,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Extract audio from a YouTube URL and save it for transcription.
    """
    youtube_url = request.youtube_url.strip()
    project_id = request.project_id

    # Validate the YouTube URL (basic validation)
    if not youtube_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="YouTube URL is required"
        )
    if re.search(r"[\x00-\x1f\x7f]", youtube_url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="YouTube URL contains invalid characters"
        )

    # Prevent new uploads while another transcription is still processing
    _ensure_no_active_transcription(current_user.id, db_session)

    # Generate a unique filename for the output (without extension, yt-dlp will add it)
    unique_filename = f"{uuid.uuid4().hex}"

    # Determine ffmpeg location
    ffmpeg_path = _find_ffmpeg_path()

    # Keep yt-dlp's template as a plain filename; paths.home carries the directory.
    yt_dlp_opts = _build_youtube_download_options(unique_filename, ffmpeg_path)

    logger.info(f"yt-dlp output directory: {UPLOAD_DIR}")
    logger.info(f"yt-dlp output template: {yt_dlp_opts['outtmpl']}")
    logger.info(f"ffmpeg_path: {ffmpeg_path}")

    video_title = "YouTube Audio"

    try:
        # Download and extract audio in a single pass
        with yt_dlp.YoutubeDL(yt_dlp_opts) as ydl:
            info_dict = ydl.extract_info(youtube_url, download=True)
            video_title = info_dict.get('title', 'YouTube Audio') if info_dict else 'YouTube Audio'

        # After download, the file should be at the resolved path
        audio_file_path = UPLOAD_DIR / f"{unique_filename}.wav"

        # Check if the file exists
        if not audio_file_path.exists():
            # Sometimes yt-dlp keeps the original extension — check for common ones
            for ext in ['wav', 'mp3', 'webm', 'opus', 'm4a', 'ogg']:
                candidate = UPLOAD_DIR / f"{unique_filename}.{ext}"
                if candidate.exists():
                    audio_file_path = candidate
                    break
            else:
                # List what files we DO have for debugging
                existing = list(UPLOAD_DIR.glob(f"{unique_filename}.*"))
                logger.error(f"Expected audio file not found. Files matching pattern: {existing}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to extract audio from YouTube URL. No output file found."
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"YouTube extraction failed: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error extracting audio from YouTube: {str(e)}"
        )

    # Create a transcription record in the database
    # If project_id is provided, we need to check that the project exists and belongs to the user
    if project_id is not None:
        project = db_session.query(models.Project).filter(models.Project.id == project_id).first()
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found"
            )
        if project.owner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to upload to this project"
            )

    db_transcription = models.Transcription(
        title=video_title,
        audio_file_path=str(audio_file_path),
        youtube_url=youtube_url,
        user_id=current_user.id,
        project_id=project_id,
        is_processed=False
    )
    db_session.add(db_transcription)
    db_session.commit()
    db_session.refresh(db_transcription)

    _start_transcription_processing(db_transcription.id, background_tasks, db_session)

    return db_transcription


@router.get("/", response_model=list[schemas.TranscriptionInDB])
async def list_transcriptions(
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    List the current user's transcriptions, newest first.
    """
    return (
        db_session.query(models.Transcription)
        .filter(models.Transcription.user_id == current_user.id)
        .order_by(models.Transcription.created_at.desc(), models.Transcription.id.desc())
        .all()
    )


@router.get("/{transcription_id}/status")
async def get_transcription_status(
    transcription_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Get the processing status of a transcription.
    """
    # Get the transcription record
    transcription = db_session.query(models.Transcription).filter(
        models.Transcription.id == transcription_id
    ).first()

    if not transcription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcription not found"
        )

    _ensure_transcription_access(transcription, db_session, current_user)

    blocking_error = _blocking_processing_error(transcription)
    if blocking_error:
        return {
            "status": "failed",
            "error": blocking_error,
            "transcription_id": transcription_id
        }

    # Return status based on transcription record
    if transcription.is_processed:
        notes_error = _notes_error(transcription.notes_data)
        if blocking_error or notes_error:
            return {
                "status": "failed",
                "error": blocking_error or f"Pitch detection failed: {notes_error}",
                "transcription_id": transcription_id
            }
        if not _has_note_events(transcription.notes_data):
            return {
                "status": "failed",
                "error": "No note events were detected, so MIDI, MusicXML, and TAB exports cannot be generated.",
                "transcription_id": transcription_id
            }
        else:
            return {
                "status": "completed",
                "transcription_id": transcription_id
            }
    else:
        return {
            "status": "processing",
            "transcription_id": transcription_id
        }


@router.get("/{transcription_id}/source")
async def get_transcription_source_audio(
    transcription_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """Stream the original uploaded/extracted audio for playback."""
    transcription = db_session.query(models.Transcription).filter(
        models.Transcription.id == transcription_id
    ).first()

    if not transcription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcription not found"
        )

    _ensure_transcription_access(transcription, db_session, current_user)

    candidates = [
        transcription.audio_file_path,
        str(UPLOAD_DIR / Path(transcription.audio_file_path).name) if transcription.audio_file_path else None,
        transcription.separated_audio_file_path,
        transcription.preprocessed_audio_file_path,
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return FileResponse(
                path=candidate,
                media_type="audio/wav",
                filename=Path(candidate).name,
            )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Source audio file not available"
    )


@router.get("/{transcription_id}/result")
async def get_transcription_result(
    transcription_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Get the result of a completed transcription.
    """
    # Get the transcription record
    transcription = db_session.query(models.Transcription).filter(
        models.Transcription.id == transcription_id
    ).first()

    if not transcription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcription not found"
        )

    # Check if the user owns this transcription (or has access via project)
    if transcription.user_id != current_user.id:
        # Check if it's in a project the user owns
        if transcription.project_id:
            project = db_session.query(models.Project).filter(
                models.Project.id == transcription.project_id
            ).first()
            if not project or project.owner_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to access this transcription"
                )
        else:
            # Not in a project and not owned by user
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this transcription"
            )

    # Check if processing is complete
    if not transcription.is_processed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcription is still processing"
        )

    blocking_error = _blocking_processing_error(transcription)
    if blocking_error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transcription failed: {blocking_error}"
        )

    try:
        _ensure_derived_outputs(transcription, db_session)
    except Exception as e:
        logger.warning(
            "Could not regenerate derived outputs for transcription %s: %s",
            transcription_id,
            e,
        )

    # Return the transcription data
    return transcription


@router.get("/{transcription_id}/tracks", response_model=list[schemas.InstrumentTrack])
async def list_instrument_tracks(
    transcription_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    List instrument tracks generated for a transcription.
    """
    _get_accessible_transcription(transcription_id, db_session, current_user)

    return (
        db_session.query(models.InstrumentTrack)
        .filter(models.InstrumentTrack.transcription_id == transcription_id)
        .order_by(models.InstrumentTrack.id.asc())
        .all()
    )


@router.get("/{transcription_id}/tracks/{track_id}", response_model=schemas.InstrumentTrack)
async def get_instrument_track(
    transcription_id: int,
    track_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Retrieve one instrument track result for a transcription.
    """
    _get_accessible_transcription(transcription_id, db_session, current_user)

    track = db_session.query(models.InstrumentTrack).filter(
        models.InstrumentTrack.id == track_id,
        models.InstrumentTrack.transcription_id == transcription_id,
    ).first()

    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument track not found"
        )

    return track


@router.get("/{transcription_id}/tracks/{track_id}/stem")
async def get_instrument_track_stem(
    transcription_id: int,
    track_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Stream one separated stem for playback.
    """
    _get_accessible_transcription(transcription_id, db_session, current_user)

    track = db_session.query(models.InstrumentTrack).filter(
        models.InstrumentTrack.id == track_id,
        models.InstrumentTrack.transcription_id == transcription_id,
    ).first()

    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument track not found"
        )

    if not track.stem_audio_path or not os.path.exists(track.stem_audio_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument stem audio file not available"
        )

    return FileResponse(
        path=track.stem_audio_path,
        media_type="audio/wav",
        filename=Path(track.stem_audio_path).name,
    )


@router.patch("/{transcription_id}/tracks/{track_id}", response_model=schemas.InstrumentTrack)
async def update_instrument_track_metadata(
    transcription_id: int,
    track_id: int,
    update: schemas.InstrumentTrackUpdate,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Update user-correctable instrument track metadata.
    """
    _get_accessible_transcription(transcription_id, db_session, current_user)

    track = db_session.query(models.InstrumentTrack).filter(
        models.InstrumentTrack.id == track_id,
        models.InstrumentTrack.transcription_id == transcription_id,
    ).first()

    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument track not found"
        )

    changes = update.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(track, field, value)

    db_session.add(track)
    db_session.commit()
    db_session.refresh(track)
    return track


@router.post("/{transcription_id}/tracks/{track_id}/reprocess", response_model=schemas.InstrumentTrack)
async def reprocess_instrument_track_endpoint(
    transcription_id: int,
    track_id: int,
    background_tasks: BackgroundTasks,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Reprocess one supported instrument track from its retained separated stem.
    """
    _transcription, track = _get_accessible_track(
        transcription_id,
        track_id,
        db_session,
        current_user,
    )
    _prepare_track_reprocess(track, db_session)
    _start_instrument_track_reprocess(track.id, background_tasks)
    return track


@router.get("/{transcription_id}/tracks/{track_id}/tab")
async def get_instrument_track_tab(
    transcription_id: int,
    track_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Export ASCII tab for one instrument track.
    """
    transcription, track = _get_accessible_track(
        transcription_id, track_id, db_session, current_user
    )
    _ensure_track_export_ready(transcription, track, format_name="tab")

    if not track.tab_json:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tab export is not available for {track.display_name}"
        )

    try:
        tablature_dict = json.loads(track.tab_json)
        ascii_tab = tablature_to_ascii_tab(tablature_dict)
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating {track.display_name} ASCII tab: {str(e)}"
        )

    return Response(
        content=ascii_tab,
        media_type="text/plain",
        headers={
            "Content-Disposition": (
                f"attachment; filename={_track_export_filename(transcription_id, track, 'tab')}"
            )
        },
    )


@router.get("/{transcription_id}/tracks/{track_id}/midi")
async def get_instrument_track_midi(
    transcription_id: int,
    track_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Export MIDI for one instrument track.
    """
    transcription, track = _get_accessible_track(
        transcription_id, track_id, db_session, current_user
    )
    _ensure_track_export_ready(transcription, track, format_name="midi")

    try:
        midi_bytes = _track_notes_to_midi_bytes(track)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not generate {track.display_name} MIDI file: {str(e)}"
        )

    return Response(
        content=midi_bytes,
        media_type="audio/midi",
        headers={
            "Content-Disposition": (
                f"attachment; filename={_track_export_filename(transcription_id, track, 'mid')}"
            )
        },
    )


@router.get("/{transcription_id}/tracks/{track_id}/musicxml")
async def get_instrument_track_musicxml(
    transcription_id: int,
    track_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Export MusicXML for one instrument track.
    """
    transcription, track = _get_accessible_track(
        transcription_id, track_id, db_session, current_user
    )
    _ensure_track_export_ready(transcription, track, format_name="musicxml")

    if not track.notation_json:
        try:
            with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as temp_file:
                temp_path = temp_file.name
            try:
                midi.notes_to_midi(track.notes_json, temp_path)
                track.notation_json = midi.midi_to_musicxml(temp_path)
            finally:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            db_session.add(track)
            db_session.commit()
            db_session.refresh(track)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not generate {track.display_name} MusicXML data: {str(e)}"
            )

    return Response(
        content=track.notation_json,
        media_type="application/xml",
        headers={
            "Content-Disposition": (
                f"attachment; filename={_track_export_filename(transcription_id, track, 'musicxml')}"
            )
        },
    )


@router.get("/{transcription_id}/midi")
async def get_transcription_midi(
    transcription_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Get the MIDI file for a completed transcription.
    """
    # Get the transcription record
    transcription = db_session.query(models.Transcription).filter(
        models.Transcription.id == transcription_id
    ).first()

    if not transcription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcription not found"
        )

    # Check if the user owns this transcription (or has access via project)
    if transcription.user_id != current_user.id:
        # Check if it's in a project the user owns
        if transcription.project_id:
            project = db_session.query(models.Project).filter(
                models.Project.id == transcription.project_id
            ).first()
            if not project or project.owner_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to access this transcription"
                )
        else:
            # Not in a project and not owned by user
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this transcription"
            )

    # Check if processing is complete
    if not transcription.is_processed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcription is still processing"
        )

    blocking_error = _blocking_processing_error(transcription)
    if blocking_error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transcription failed: {blocking_error}"
        )

    try:
        _ensure_derived_outputs(transcription, db_session)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not generate MIDI file: {str(e)}"
        )

    _require_note_events_for_export(transcription)

    # Check if MIDI file exists
    if not transcription.midi_file_path or not os.path.exists(transcription.midi_file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MIDI file not available"
        )

    # Return the MIDI file
    return FileResponse(
        path=transcription.midi_file_path,
        media_type='audio/midi',
        filename=f"transcription_{transcription_id}.mid"
    )


@router.get("/{transcription_id}/musicxml")
async def get_transcription_musicxml(
    transcription_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Get the MusicXML file for a completed transcription.
    """
    # Get the transcription record
    transcription = db_session.query(models.Transcription).filter(
        models.Transcription.id == transcription_id
    ).first()

    if not transcription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcription not found"
        )

    # Check if the user owns this transcription (or has access via project)
    if transcription.user_id != current_user.id:
        # Check if it's in a project the user owns
        if transcription.project_id:
            project = db_session.query(models.Project).filter(
                models.Project.id == transcription.project_id
            ).first()
            if not project or project.owner_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to access this transcription"
                )
        else:
            # Not in a project and not owned by user
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this transcription"
            )

    # Check if processing is complete
    if not transcription.is_processed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcription is still processing"
        )

    blocking_error = _blocking_processing_error(transcription)
    if blocking_error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transcription failed: {blocking_error}"
        )

    try:
        _ensure_derived_outputs(transcription, db_session)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not generate MusicXML data: {str(e)}"
        )

    _require_note_events_for_export(transcription)

    # Check if MusicXML data exists
    if not transcription.notation_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MusicXML data not available"
        )

    # Return the MusicXML data as a string with the appropriate media type
    return Response(
        content=transcription.notation_data,
        media_type='application/xml',
        headers={
            "Content-Disposition": f"attachment; filename=transcription_{transcription_id}.musicxml"
        }
    )


@router.get("/{transcription_id}/tab")
async def get_transcription_tab(
    transcription_id: int,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Get the ASCII tab file for a completed transcription.
    """
    # Get the transcription record
    transcription = db_session.query(models.Transcription).filter(
        models.Transcription.id == transcription_id
    ).first()

    if not transcription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcription not found"
        )

    # Check if the user owns this transcription (or has access via project)
    if transcription.user_id != current_user.id:
        # Check if it's in a project the user owns
        if transcription.project_id:
            project = db_session.query(models.Project).filter(
                models.Project.id == transcription.project_id
            ).first()
            if not project or project.owner_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to access this transcription"
                )
        else:
            # Not in a project and not owned by user
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this transcription"
            )

    # Check if processing is complete
    if not transcription.is_processed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcription is still processing"
        )

    blocking_error = _blocking_processing_error(transcription)
    if blocking_error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transcription failed: {blocking_error}"
        )

    try:
        _ensure_derived_outputs(transcription, db_session)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not generate tablature data: {str(e)}"
        )

    _require_note_events_for_export(transcription)

    # Check if tablature data exists
    if not transcription.tablature_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tablature data not available"
        )

    # Parse tablature data and generate ASCII tab
    try:
        tablature_dict = json.loads(transcription.tablature_data)
        ascii_tab = tablature_to_ascii_tab(tablature_dict)
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating ASCII tab: {str(e)}"
        )

    # Return as plain text file
    return Response(
        content=ascii_tab,
        media_type='text/plain',
        headers={
            "Content-Disposition": f"attachment; filename=transcription_{transcription_id}.tab"
        }
    )
