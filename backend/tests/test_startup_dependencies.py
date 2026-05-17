import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main


def test_startup_does_not_fail_when_optional_audio_dependency_is_broken(monkeypatch):
    def fake_validate_audio_dependencies(*args, **kwargs):
        return {
            "available": False,
            "dependencies": {
                "torchcodec": {
                    "available": False,
                    "version": "0.12.0",
                    "error": "torchcodec import failed: Could not load libtorchcodec_core4.dll",
                }
            },
            "missing": ["torchcodec"],
        }

    monkeypatch.setattr(main, "validate_audio_dependencies", fake_validate_audio_dependencies)

    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "unhealthy"
    assert response.json()["missing_dependencies"] == ["torchcodec"]
