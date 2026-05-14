from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db, models
from app.core.security import create_access_token, get_password_hash
from main import app


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


app.dependency_overrides[db.get_db] = override_get_db
client = TestClient(app)


def reset_database():
    models.Base.metadata.drop_all(bind=engine)
    models.Base.metadata.create_all(bind=engine)


def create_user(session, username: str, email: str):
    user = models.User(
        username=username,
        email=email,
        hashed_password=get_password_hash("password123"),
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def auth_headers(username: str):
    token = create_access_token(data={"sub": username})
    return {"Authorization": f"Bearer {token}"}


def test_list_transcriptions_requires_authentication():
    reset_database()

    response = client.get("/api/v1/audio/")

    assert response.status_code == 401


def test_list_transcriptions_returns_only_current_users_items_newest_first():
    reset_database()
    session = TestingSessionLocal()
    try:
        owner = create_user(session, "owner", "owner@example.com")
        other_user = create_user(session, "other", "other@example.com")
        base_time = datetime(2026, 5, 14, 12, 0, 0)

        older = models.Transcription(
            title="Older song",
            audio_file_path="uploads/older.wav",
            user_id=owner.id,
            is_processed=True,
            created_at=base_time,
            duration=60,
        )
        newer = models.Transcription(
            title="Newer song",
            audio_file_path="uploads/newer.wav",
            user_id=owner.id,
            is_processed=False,
            created_at=base_time + timedelta(minutes=5),
            duration=90,
        )
        same_time_later = models.Transcription(
            title="Same time later id",
            audio_file_path="uploads/same-time.wav",
            user_id=owner.id,
            is_processed=False,
            created_at=base_time + timedelta(minutes=5),
            duration=95,
        )
        other = models.Transcription(
            title="Other user song",
            audio_file_path="uploads/other.wav",
            user_id=other_user.id,
            is_processed=True,
            created_at=base_time + timedelta(minutes=10),
            duration=120,
        )
        session.add_all([older, newer, same_time_later, other])
        session.commit()
        other_user_id = other_user.id
    finally:
        session.close()

    response = client.get("/api/v1/audio/", headers=auth_headers("owner"))

    assert response.status_code == 200
    payload = response.json()
    assert [item["title"] for item in payload] == [
        "Same time later id",
        "Newer song",
        "Older song",
    ]
    assert all(item["user_id"] != other_user_id for item in payload)
