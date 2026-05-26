from __future__ import annotations

from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text

from ..core.config import settings
from ..database_init import engine, validate_schema_against_models


def _check_database() -> dict[str, Any]:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _check_schema() -> dict[str, Any]:
    try:
        validate_schema_against_models()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _check_alembic() -> dict[str, Any]:
    backend_dir = Path(__file__).resolve().parents[2]
    alembic_ini = backend_dir / "alembic.ini"
    try:
        alembic_cfg = Config(str(alembic_ini))
        alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
        script = ScriptDirectory.from_config(alembic_cfg)
        head_revision = script.get_current_head()

        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            current_revision = context.get_current_revision()

        return {
            "ok": bool(head_revision and current_revision == head_revision),
            "current_revision": current_revision,
            "head_revision": head_revision,
        }
    except Exception as exc:
        return {
            "ok": False,
            "current_revision": None,
            "head_revision": None,
            "error": str(exc),
        }


def build_deployment_health() -> dict[str, Any]:
    """Return deployment diagnostics without exposing secret values."""
    try:
        processing_backend = settings.audio_processing_mode
    except ValueError as exc:
        processing_backend = settings.raw_audio_processing_mode or "invalid"
        processing_error = str(exc)
    else:
        processing_error = None

    modal_configured = settings.modal_trigger_url_configured
    worker_token_configured = bool((settings.WORKER_API_TOKEN or "").strip())
    admin_token_configured = bool((settings.ADMIN_API_TOKEN or "").strip())
    cloudinary_configured = settings.cloudinary_configured
    db_check = _check_database()
    schema_check = _check_schema()
    alembic_check = _check_alembic()

    checks = {
        "processing_backend": {
            "ok": processing_backend == "modal",
            "value": processing_backend,
            "expected": "modal",
            **({"error": processing_error} if processing_error else {}),
        },
        "modal": {"ok": modal_configured, "configured": modal_configured},
        "worker_api_token": {
            "ok": worker_token_configured,
            "configured": worker_token_configured,
        },
        "admin_api": {
            "ok": True,
            "admin_api_configured": admin_token_configured,
        },
        "cloudinary": {
            "ok": cloudinary_configured,
            "configured": cloudinary_configured,
        },
        "database": db_check,
        "schema": schema_check,
        "alembic": alembic_check,
    }
    required = [
        checks["processing_backend"]["ok"],
        checks["modal"]["ok"],
        checks["worker_api_token"]["ok"],
        checks["cloudinary"]["ok"],
        checks["database"]["ok"],
        checks["schema"]["ok"],
        checks["alembic"]["ok"],
    ]
    ready = all(required)

    return {
        "status": "ok" if ready else "failed",
        "ready": ready,
        "proceed": ready,
        "environment": settings.ENVIRONMENT,
        "checks": checks,
    }
