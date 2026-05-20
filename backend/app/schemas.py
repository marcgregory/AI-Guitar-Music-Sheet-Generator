from pydantic import BaseModel, ConfigDict, EmailStr, Field
from typing import Any, Optional
from datetime import datetime

# User schemas
class UserBase(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)

class UserCreate(UserBase):
    password: str = Field(..., min_length=8)

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    password: Optional[str] = Field(None, min_length=8)

class UserInDBBase(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

class UserInDB(UserInDBBase):
    hashed_password: str

class User(UserInDBBase):
    pass

# Token schemas
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

# Project schemas
class ProjectBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    is_public: bool = False

class ProjectCreate(ProjectBase):
    pass

class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    is_public: Optional[bool] = None

class ProjectInDBBase(ProjectBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    is_deleted: Optional[bool] = False
    deleted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

class ProjectInDB(ProjectInDBBase):
    pass

class Project(ProjectInDBBase):
    pass

# Transcription schemas
class TranscriptionBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    audio_file_path: Optional[str] = None
    preprocessed_audio_file_path: Optional[str] = None
    selected_stem: Optional[str] = None
    processing_status: Optional[str] = None
    queue_position: Optional[int] = None
    estimated_wait_time: Optional[int] = None
    celery_task_id: Optional[str] = None
    modal_dispatch_status: Optional[str] = None
    modal_job_type: Optional[str] = None
    modal_dispatched_at: Optional[datetime] = None
    modal_request_id: Optional[str] = None
    modal_retry_at: Optional[datetime] = None
    modal_retry_count: Optional[int] = 0
    separated_audio_file_path: Optional[str] = None
    midi_file_path: Optional[str] = None
    tab_file_path: Optional[str] = None
    youtube_url: Optional[str] = None
    source_type: Optional[str] = None
    source_url: Optional[str] = None
    normalized_source_id: Optional[str] = None
    audio_hash: Optional[str] = None
    duplicate_of_id: Optional[int] = None
    is_demo: Optional[bool] = False
    is_deleted: Optional[bool] = False
    deleted_at: Optional[datetime] = None
    original_audio_url: Optional[str] = None
    original_audio_public_id: Optional[str] = None
    separated_audio_url: Optional[str] = None
    separated_audio_public_id: Optional[str] = None
    midi_file_url: Optional[str] = None
    midi_file_public_id: Optional[str] = None
    tab_file_url: Optional[str] = None
    tab_file_public_id: Optional[str] = None
    duplicate_reused: Optional[bool] = False
    duplicate_message: Optional[str] = None
    duration: Optional[int] = None
    detected_tempo: Optional[int] = None
    tempo_confidence: Optional[int] = None
    detected_key: Optional[str] = None
    key_confidence: Optional[int] = None
    warning_message: Optional[str] = None
    lyrics_generation_status: Optional[str] = None
    instrument_type: Optional[str] = None
    output_mode: Optional[str] = None
    can_generate_tab: Optional[bool] = False
    can_generate_score: Optional[bool] = True
    can_generate_rhythm: Optional[bool] = False
    can_play_stem: Optional[bool] = False
    available_exports: Optional[list[str]] = None
    track_count: Optional[int] = 0
    tuning: Optional[str] = None
    import_type: Optional[str] = None
    transcription_attempts: Optional[int] = 0

class TranscriptionCreate(TranscriptionBase):
    project_id: Optional[int] = None

class TranscriptionUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    audio_file_path: Optional[str] = None
    youtube_url: Optional[str] = None
    duration: Optional[int] = None
    detected_tempo: Optional[int] = None
    detected_key: Optional[str] = None
    is_processed: Optional[bool] = None
    processing_status: Optional[str] = None
    processing_error: Optional[str] = None
    warning_message: Optional[str] = None
    lyrics_generation_status: Optional[str] = None
    can_generate_score: Optional[bool] = None
    can_play_stem: Optional[bool] = None
    transcription_attempts: Optional[int] = None

class TranscriptionInDBBase(TranscriptionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    project_id: Optional[int] = None
    is_processed: bool
    processing_error: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    chord_chart_data: Optional[str] = None
    lyrics_data: Optional[str] = None

class TranscriptionInDB(TranscriptionInDBBase):
    notes_data: Optional[str] = None
    chords_data: Optional[str] = None
    tablature_data: Optional[str] = None
    notation_data: Optional[str] = None
    chord_chart_data: Optional[str] = None
    lyrics_data: Optional[str] = None

class Transcription(TranscriptionInDBBase):
    notes_data: Optional[str] = None
    chords_data: Optional[str] = None
    tablature_data: Optional[str] = None
    notation_data: Optional[str] = None
    chord_chart_data: Optional[str] = None
    lyrics_data: Optional[str] = None


class InstrumentTrackBase(BaseModel):
    transcription_id: int
    instrument_type: str
    display_name: str
    stem_audio_path: Optional[str] = None
    notes_json: Optional[str] = None
    chords_json: Optional[str] = None
    tab_json: Optional[str] = None
    notation_json: Optional[str] = None
    confidence_score: Optional[int] = None
    processing_status: str = "pending"
    confidence_notes: Optional[str] = None


class InstrumentTrackCreate(BaseModel):
    instrument_type: str = Field(..., min_length=1, max_length=50)
    display_name: Optional[str] = Field(None, min_length=1, max_length=100)
    stem_audio_path: Optional[str] = None
    notes_json: Optional[str] = None
    chords_json: Optional[str] = None
    tab_json: Optional[str] = None
    notation_json: Optional[str] = None
    confidence_score: Optional[int] = None
    processing_status: str = "pending"
    confidence_notes: Optional[str] = None


class InstrumentTrackUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=100)
    instrument_type: Optional[str] = Field(None, min_length=1, max_length=50)
    confidence_notes: Optional[str] = None


class InstrumentTrack(InstrumentTrackBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None


class WorkerJob(BaseModel):
    transcription_id: int
    selected_stem: str
    demucs_stem: str
    original_audio_url: str
    job_type: Optional[str] = "process"
    modal_request_id: Optional[str] = None
    separated_audio_url: Optional[str] = None
    detection_sensitivity: Optional[str] = None
    track_id: Optional[int] = None
    source_type: Optional[str] = None
    source_url: Optional[str] = None
    normalized_source_id: Optional[str] = None
    audio_hash: Optional[str] = None
    callback_complete_url: str
    callback_failed_url: str


class WorkerCompleteRequest(BaseModel):
    separated_audio_url: Optional[str] = None
    separated_audio_public_id: Optional[str] = None
    midi_file_url: Optional[str] = None
    midi_file_public_id: Optional[str] = None
    tab_file_url: Optional[str] = None
    tab_file_public_id: Optional[str] = None
    confidence: Optional[int] = None
    duration: Optional[int] = None
    detected_tempo: Optional[int] = None
    tempo_confidence: Optional[int] = None
    detected_key: Optional[str] = None
    key_confidence: Optional[int] = None
    notes_data: Optional[Any] = None
    chords_data: Optional[Any] = None
    chord_chart_data: Optional[Any] = None
    tablature_data: Optional[Any] = None
    lyrics_data: Optional[Any] = None
    track_metadata: Optional[dict[str, Any]] = None


class WorkerFailedRequest(BaseModel):
    error: Optional[str] = None
    internal_logs: Optional[Any] = None


class RetryTranscriptionRequest(BaseModel):
    lower_threshold: bool = True
    alternate_settings: Optional[dict[str, Any]] = None
    selected_stem: Optional[str] = None
