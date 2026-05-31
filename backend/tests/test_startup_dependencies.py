import builtins
import importlib
import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_startup_health_uses_local_processing_by_default(caplog):
    main = importlib.import_module("main")
    original_admin_token = main.settings.ADMIN_API_TOKEN
    main.settings.ADMIN_API_TOKEN = None

    try:
        with caplog.at_level(logging.INFO), TestClient(main.app) as client:
            response = client.get("/health")
    finally:
        main.settings.ADMIN_API_TOKEN = original_admin_token

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "processing_backend": "local",
    }
    assert "AUDIO_PROCESSING_MODE=local" in caplog.text
    assert "MODAL_TRIGGER_URL configured=False" in caplog.text
    assert "Admin API configured=False" in caplog.text
    assert "Redis configured=True" in caplog.text
    assert "Celery enabled=True" in caplog.text


def test_deployment_health_reports_safe_readiness_details():
    main = importlib.import_module("main")
    original_admin_token = main.settings.ADMIN_API_TOKEN
    main.settings.ADMIN_API_TOKEN = None

    try:
        with TestClient(main.app) as client:
            response = client.get("/health/deployment")
    finally:
        main.settings.ADMIN_API_TOKEN = original_admin_token

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"ok", "degraded", "failed"}
    assert payload["proceed"] is payload["ready"]
    checks = payload["checks"]
    assert checks["processing_backend"]["value"] == "local"
    assert checks["processing_backend"]["expected"] == "modal"
    assert checks["modal"]["configured"] is False
    assert checks["admin_api"]["admin_api_configured"] is False
    assert checks["cloudinary"]["configured"] is False
    assert checks["database"]["ok"] is True
    assert "schema" in checks
    assert "alembic" in checks
    assert "SECRET_KEY" not in str(payload)
    assert "WORKER_API_TOKEN" not in str(payload)
    assert "ADMIN_API_TOKEN" not in str(payload)


def test_production_startup_fails_when_required_deploy_settings_are_missing():
    main = importlib.import_module("main")
    settings = main.settings
    original_values = {
        "ENVIRONMENT": settings.ENVIRONMENT,
        "AUDIO_PROCESSING_MODE": settings.AUDIO_PROCESSING_MODE,
        "MODAL_TRIGGER_URL": settings.MODAL_TRIGGER_URL,
        "WORKER_API_TOKEN": settings.WORKER_API_TOKEN,
        "CLOUDINARY_URL": settings.CLOUDINARY_URL,
        "CLOUDINARY_CLOUD_NAME": settings.CLOUDINARY_CLOUD_NAME,
        "CLOUDINARY_API_KEY": settings.CLOUDINARY_API_KEY,
        "CLOUDINARY_API_SECRET": settings.CLOUDINARY_API_SECRET,
        "DATABASE_URL": settings.DATABASE_URL,
    }

    settings.ENVIRONMENT = "production"
    settings.AUDIO_PROCESSING_MODE = None
    settings.MODAL_TRIGGER_URL = None
    settings.WORKER_API_TOKEN = None
    settings.CLOUDINARY_URL = None
    settings.CLOUDINARY_CLOUD_NAME = None
    settings.CLOUDINARY_API_KEY = None
    settings.CLOUDINARY_API_SECRET = None
    settings.DATABASE_URL = "sqlite:///./test.db"

    try:
        with pytest.raises(RuntimeError) as exc_info:
            with TestClient(main.app):
                pass
    finally:
        for name, value in original_values.items():
            setattr(settings, name, value)

    message = str(exc_info.value)
    assert "Production deployment is not ready" in message
    assert "AUDIO_PROCESSING_MODE=modal" in message
    assert "MODAL_TRIGGER_URL" in message
    assert "WORKER_API_TOKEN" in message
    assert "CLOUDINARY_URL" in message
    assert "DATABASE_URL" in message


def test_api_and_celery_import_without_local_audio_ml_dependencies(monkeypatch):
    blocked_roots = {
        "basic_pitch",
        "demucs",
        "essentia",
        "librosa",
        "numpy",
        "soundfile",
        "torch",
        "torchaudio",
    }
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in blocked_roots:
            raise ModuleNotFoundError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    for module_name in ("main", "app.tasks", "app.services.audio"):
        sys.modules.pop(module_name, None)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    importlib.import_module("main")
    importlib.import_module("app.tasks")
    importlib.import_module("app.services.audio")
