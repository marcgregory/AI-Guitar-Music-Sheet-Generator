from pydantic import BaseModel, EmailStr, Field
from typing import Optional
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
    id: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True

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
    id: int
    owner_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True

class ProjectInDB(ProjectInDBBase):
    pass

class Project(ProjectInDBBase):
    pass

# Transcription schemas
class TranscriptionBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    audio_file_path: Optional[str] = None
    preprocessed_audio_file_path: Optional[str] = None
    separated_audio_file_path: Optional[str] = None
    youtube_url: Optional[str] = None
    duration: Optional[int] = None
    detected_tempo: Optional[int] = None
    detected_key: Optional[str] = None

class TranscriptionCreate(TranscriptionBase):
    project_id: int

class TranscriptionUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    audio_file_path: Optional[str] = None
    youtube_url: Optional[str] = None
    duration: Optional[int] = None
    detected_tempo: Optional[int] = None
    detected_key: Optional[str] = None
    is_processed: Optional[bool] = None
    processing_error: Optional[str] = None

class TranscriptionInDBBase(TranscriptionBase):
    id: int
    user_id: int
    project_id: int
    is_processed: bool
    processing_error: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True

class TranscriptionInDB(TranscriptionInDBBase):
    notes_data: Optional[str] = None
    chords_data: Optional[str] = None
    tablature_data: Optional[str] = None
    notation_data: Optional[str] = None

class Transcription(TranscriptionInDBBase):
    notes_data: Optional[str] = None
    chords_data: Optional[str] = None
    tablature_data: Optional[str] = None
    notation_data: Optional[str] = None