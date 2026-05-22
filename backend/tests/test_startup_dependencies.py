import builtins
import importlib
import logging
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_startup_health_uses_local_processing_by_default(caplog):
    main = importlib.import_module("main")

    with caplog.at_level(logging.INFO), TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "processing_backend": "local",
    }
    assert "AUDIO_PROCESSING_MODE=local" in caplog.text
    assert "MODAL_TRIGGER_URL configured=False" in caplog.text
    assert "Redis configured=True" in caplog.text
    assert "Celery enabled=True" in caplog.text


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
