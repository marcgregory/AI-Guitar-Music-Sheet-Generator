from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .db import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    projects = relationship("Project", back_populates="owner")
    transcriptions = relationship("Transcription", back_populates="user")

class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    description = Column(Text, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    is_public = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    owner = relationship("User", back_populates="projects")
    transcriptions = relationship("Transcription", back_populates="project")

class Transcription(Base):
    __tablename__ = "transcriptions"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True, nullable=False)
    audio_file_path = Column(String, nullable=True)
    preprocessed_audio_file_path = Column(String, nullable=True)
    separated_audio_file_path = Column(String, nullable=True)
    midi_file_path = Column(String, nullable=True)  # Path to generated MIDI file
    youtube_url = Column(String, nullable=True)
    duration = Column(Integer, nullable=True)  # in seconds
    detected_tempo = Column(Integer, nullable=True)  # BPM
    tempo_confidence = Column(Integer, nullable=True)  # Confidence percentage (0-100)
    detected_key = Column(String, nullable=True)
    key_confidence = Column(Integer, nullable=True)  # Confidence percentage (0-100)
    user_id = Column(Integer, ForeignKey("users.id"))
    project_id = Column(Integer, ForeignKey("projects.id"))
    is_processed = Column(Boolean, default=False)
    processing_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="transcriptions")
    project = relationship("Project", back_populates="transcriptions")
    instrument_tracks = relationship(
        "InstrumentTrack",
        back_populates="transcription",
        cascade="all, delete-orphan",
    )

    # JSON fields for storing transcription data (we'll use Text for simplicity)
    notes_data = Column(Text, nullable=True)  # JSON string of detected notes
    chords_data = Column(Text, nullable=True)  # JSON string of detected chords
    tablature_data = Column(Text, nullable=True)  # JSON string of generated tablature
    notation_data = Column(Text, nullable=True)  # MusicXML string of standard notation
    chord_chart_data = Column(Text, nullable=True)  # SVG string of chord chart


class InstrumentTrack(Base):
    __tablename__ = "instrument_tracks"

    id = Column(Integer, primary_key=True, index=True)
    transcription_id = Column(Integer, ForeignKey("transcriptions.id"), nullable=False, index=True)
    instrument_type = Column(String, index=True, nullable=False)
    display_name = Column(String, nullable=False)
    stem_audio_path = Column(String, nullable=True)
    notes_json = Column(Text, nullable=True)
    chords_json = Column(Text, nullable=True)
    tab_json = Column(Text, nullable=True)
    notation_json = Column(Text, nullable=True)
    confidence_score = Column(Integer, nullable=True)
    processing_status = Column(String, nullable=False, default="pending")
    confidence_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    transcription = relationship("Transcription", back_populates="instrument_tracks")
