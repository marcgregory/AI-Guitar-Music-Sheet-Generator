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
