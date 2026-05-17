import logging
from pathlib import Path, PurePosixPath
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


def normalize_local_path(path: str | Path) -> str:
    """Normalize a local filesystem path to POSIX format for Docker/Linux.

    This helper is intended for temporary local scratch paths only.
    Durable URLs should remain unchanged and should continue using the Cloudinary fields.
    """
    if isinstance(path, Path):
        return PurePosixPath(path).as_posix()
    normalized = str(path).replace("\\", "/")
    return PurePosixPath(normalized).as_posix()


def _cloudinary_configured() -> bool:
    return bool(
        settings.CLOUDINARY_URL
        or (
            settings.CLOUDINARY_CLOUD_NAME
            and settings.CLOUDINARY_API_KEY
            and settings.CLOUDINARY_API_SECRET
        )
    )


def _configure_cloudinary():
    try:
        import cloudinary
    except ImportError as exc:
        if _cloudinary_configured():
            raise RuntimeError(
                "Cloudinary credentials are configured but the cloudinary package is not installed."
            ) from exc
        return None

    config: dict[str, Any] = {"secure": True}
    if settings.CLOUDINARY_CLOUD_NAME:
        config["cloud_name"] = settings.CLOUDINARY_CLOUD_NAME
    if settings.CLOUDINARY_API_KEY:
        config["api_key"] = settings.CLOUDINARY_API_KEY
    if settings.CLOUDINARY_API_SECRET:
        config["api_secret"] = settings.CLOUDINARY_API_SECRET
    cloudinary.config(**config)
    return cloudinary


def upload_file(
    file_path: str,
    *,
    folder: str,
    resource_type: str = "auto",
) -> dict[str, str] | None:
    """Upload a local file to Cloudinary and return its durable references."""
    if not _cloudinary_configured():
        return None

    path = Path(file_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Cannot upload missing file: {file_path}")

    _configure_cloudinary()
    from cloudinary import uploader

    upload_folder = "/".join(
        part.strip("/")
        for part in (settings.CLOUDINARY_FOLDER, folder)
        if part and part.strip("/")
    )
    result = uploader.upload(
        str(path),
        folder=upload_folder,
        resource_type=resource_type,
        use_filename=True,
        unique_filename=True,
        overwrite=False,
    )
    return {
        "secure_url": result.get("secure_url"),
        "public_id": result.get("public_id"),
    }


def safe_upload_file(
    file_path: str,
    *,
    folder: str,
    resource_type: str = "auto",
) -> dict[str, str] | None:
    """Upload when configured, logging failures without hiding local cleanup paths."""
    try:
        return upload_file(file_path, folder=folder, resource_type=resource_type)
    except Exception as exc:
        logger.warning("Cloudinary upload failed for %s: %s", file_path, exc)
        raise


def delete_cloudinary_asset(public_id: str | None, resource_type: str = "video") -> bool:
    """Best-effort Cloudinary asset deletion with lifecycle logging."""
    if not public_id:
        logger.info("Cloudinary asset missing; nothing to delete")
        return False

    if not _cloudinary_configured():
        logger.info("Cloudinary asset skipped for %s; Cloudinary is not configured", public_id)
        return False

    try:
        _configure_cloudinary()
        from cloudinary import uploader

        result = uploader.destroy(public_id, resource_type=resource_type, invalidate=True)
        if result.get("result") == "not found":
            logger.info(
                "Cloudinary asset missing for %s with resource_type=%s",
                public_id,
                resource_type,
            )
            return False
        logger.info(
            "Cloudinary asset deleted for %s with resource_type=%s",
            public_id,
            resource_type,
        )
        return result.get("result") == "ok"
    except Exception as exc:
        logger.exception(
            "Cloudinary deletion failure for %s with resource_type=%s: %s",
            public_id,
            resource_type,
            exc,
        )
        return False


def delete_asset(public_id: str | None, *, resource_type: str = "auto") -> bool:
    """Backward-compatible wrapper for best-effort Cloudinary deletion."""
    return delete_cloudinary_asset(public_id, resource_type=resource_type)


def delete_assets(public_ids: list[str | None], *, resource_type: str = "auto") -> None:
    """Delete a group of durable assets best-effort, leaving DB deletion safe."""
    for public_id in public_ids:
        delete_cloudinary_asset(public_id, resource_type=resource_type)
