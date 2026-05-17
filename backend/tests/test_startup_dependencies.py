import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main


def test_startup_reports_unhealthy_when_required_audio_dependency_is_broken(monkeypatch):
    def fake_validate_audio_dependencies(*args, **kwargs):
        return {
            "available": False,
            "dependencies": {
                "torch": {
                    "available": False,
                    "version": "2.1.0",
                    "error": "torch import failed: NumPy compatibility error",
                }
            },
            "missing": ["torch"],
        }

    monkeypatch.setattr(main, "validate_audio_dependencies", fake_validate_audio_dependencies)

    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "unhealthy"
    assert response.json()["missing_dependencies"] == ["torch"]
