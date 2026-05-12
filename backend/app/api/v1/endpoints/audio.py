from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import os
import uuid
from pathlib import Path
import yt_dlp

from .... import db, core
from ....core.security import get_current_user
from .. import schemas, models
from ....services import audio
from ....app import celery_app

router = APIRouter()

# Define the upload directory
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@router.post("/upload", response_model=schemas.TranscriptionInDB)
async def upload_audio_file(
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

    # Generate a unique filename to avoid collisions
    unique_filename = f"{uuid.uuid4().hex}{file_extension}"
    file_path = UPLOAD_DIR / unique_filename
    # Resolve to absolute path
    file_path = file_path.resolve()

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

    # Trigger asynchronous audio processing
    try:
        # Start the Celery task for audio processing
        task = celery_app.send_task(
            "app.tasks.process_audio_transcription",
            args=[db_transcription.id]
        )
        # Note: We don't store the task ID in the transcription record for now
        # In a more advanced implementation, we might want to track it
    except Exception as e:
        # If task triggering fails, we still return the transcription but mark it as having processing issues
        db_transcription.processing_error = f"Failed to start processing task: {str(e)}"
        db_session.add(db_transcription)
        db_session.commit()
        db_session.refresh(db_transcription)

    return db_transcription


@router.post("/youtube", response_model=schemas.TranscriptionInDB)
async def extract_audio_from_youtube(
    youtube_url: str,
    project_id: int = None,
    db_session: Session = Depends(db.get_db),
    current_user: schemas.User = Depends(get_current_user)
):
    """
    Extract audio from a YouTube URL and save it for transcription.
    """
    # Validate the YouTube URL (basic validation)
    if not youtube_url.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="YouTube URL is required"
        )

    # Generate a unique filename for the output (without extension, yt-dlp will add it)
    unique_filename = f"{uuid.uuid4().hex}"
    # Set up yt-dlp options
    yt_dlp_opts = {
        'format': 'bestaudio/best',
        'outtmpl': str(UPLOAD_DIR / f'{unique_filename}.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',
            'preferredquality': '192',
        }],
        'quiet': True,  # Suppress output
        'no_warnings': True,
    }

    try:
        # Download and extract audio
        with yt_dlp.YoutubeDL(yt_dlp_opts) as ydl:
            # Extract information to get the filename (without actually downloading)
            info_dict = ydl.extract_info(youtube_url, download=False)
            # Now download
            ydl.download([youtube_url])

        # After download, the file should be at: UPLOAD_DIR / f"{unique_filename}.wav"
        # Because we set the preferred codec to wav
        audio_file_path = UPLOAD_DIR / f"{unique_filename}.wav"
        # Resolve to absolute path
        audio_file_path = audio_file_path.resolve()

        # Check if the file exists
        if not audio_file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to extract audio from YouTube URL"
            )

    except Exception as e:
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

    # Determine the title for the transcription (use the video title if available)
    title = "YouTube Audio"
    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info_dict = ydl.extract_info(youtube_url, download=False)
            title = info_dict.get('title', "YouTube Audio")
    except Exception:
        # If we can't get the title, use a default
        pass

    db_transcription = models.Transcription(
        title=title,
        audio_file_path=str(audio_file_path),
        user_id=current_user.id,
        project_id=project_id,
        is_processed=False
    )
    db_session.add(db_transcription)
    db_session.commit()
    db_session.refresh(db_transcription)

    # Trigger asynchronous audio processing
    try:
        # Start the Celery task for audio processing
        task = celery_app.send_task(
            "app.tasks.process_audio_transcription",
            args=[db_transcription.id]
        )
        # Note: We don't store the task ID in the transcription record for now
        # In a more advanced implementation, we might want to track it
    except Exception as e:
        # If task triggering fails, we still return the transcription but mark it as having processing issues
        db_transcription.processing_error = f"Failed to start processing task: {str(e)}"
        db_session.add(db_transcription)
        db_session.commit()
        db_session.refresh(db_transcription)

    return db_transcription


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

    # Return status based on transcription record
    if transcription.is_processed:
        if transcription.processing_error:
            return {
                "status": "failed",
                "error": transcription.processing_error,
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

    if transcription.processing_error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transcription failed: {transcription.processing_error}"
        )

    # Return the transcription data
    return transcription