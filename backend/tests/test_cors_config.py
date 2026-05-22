import pytest

from app.core.config import Settings


def test_allowed_origins_are_normalized_to_browser_origins():
    settings = Settings(
        ALLOWED_ORIGINS=(
            "http://localhost:3000,"
            " https://ai-guitar-music-sheet-generator-sta.vercel.app/,"
            "https://example.com/some/path/"
        )
    )

    assert settings.get_allowed_origins == [
        "http://localhost:3000",
        "https://ai-guitar-music-sheet-generator-sta.vercel.app",
        "https://example.com",
    ]


def test_allowed_origins_ignores_empty_values():
    settings = Settings(ALLOWED_ORIGINS="http://localhost:5173,, ")

    assert settings.get_allowed_origins == ["http://localhost:5173"]


def test_development_defaults_audio_processing_to_local():
    settings = Settings(
        ENVIRONMENT="development",
        AUDIO_PROCESSING_MODE=None,
        PROCESSING_MODE=None,
    )

    assert settings.audio_processing_mode == "local"


def test_production_requires_explicit_audio_processing_mode():
    settings = Settings(
        ENVIRONMENT="production",
        AUDIO_PROCESSING_MODE=None,
        PROCESSING_MODE=None,
    )

    with pytest.raises(ValueError, match="Invalid AUDIO_PROCESSING_MODE"):
        _ = settings.audio_processing_mode


def test_explicit_audio_processing_mode_overrides_environment():
    settings = Settings(
        ENVIRONMENT="production",
        AUDIO_PROCESSING_MODE="disabled",
        PROCESSING_MODE="modal",
    )

    assert settings.audio_processing_mode == "disabled"


def test_processing_mode_legacy_value_is_ignored():
    settings = Settings(
        ENVIRONMENT="development",
        AUDIO_PROCESSING_MODE=None,
        PROCESSING_MODE="modal",
    )

    assert settings.audio_processing_mode == "local"


def test_env_local_overrides_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("AUDIO_PROCESSING_MODE", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "ENVIRONMENT=production\nAUDIO_PROCESSING_MODE=modal\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.local").write_text(
        "ENVIRONMENT=development\nAUDIO_PROCESSING_MODE=local\n",
        encoding="utf-8",
    )

    settings = Settings()

    assert settings.audio_processing_mode == "local"
