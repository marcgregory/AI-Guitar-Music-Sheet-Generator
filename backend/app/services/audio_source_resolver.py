import logging


logger = logging.getLogger(__name__)

MANUAL_TAB_STEMS = {"bass", "other"}
MISSING_SEPARATED_STEM_MESSAGE = "Separated stem audio is required before generating tabs."


def resolve_generate_tab_audio_source(transcription) -> str | None:
    """
    Resolve the only allowed audio source for manual bass/other TAB generation.

    Manual TAB generation must never fall back to original or preprocessed audio.
    """
    selected_stem = (getattr(transcription, "selected_stem", None) or "other").strip().lower()
    if selected_stem not in MANUAL_TAB_STEMS:
        return None

    source_type = "missing"
    source = None
    separated_audio_url = getattr(transcription, "separated_audio_url", None)
    separated_audio_file_path = getattr(transcription, "separated_audio_file_path", None)

    if separated_audio_url:
        source_type = "separated_audio_url"
        source = separated_audio_url
    elif separated_audio_file_path:
        source_type = "separated_audio_file_path"
        source = separated_audio_file_path

    logger.info("tab_generation_audio_source=%s", source_type)
    logger.info(
        "generate_tab_source transcription_id=%s stem=%s source=%s",
        getattr(transcription, "id", None),
        selected_stem,
        source,
    )

    if source:
        return source

    raise ValueError(MISSING_SEPARATED_STEM_MESSAGE)
