import logging
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app.api.v1.endpoints.audio import retry_rate_limited_modal_jobs_once

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    result = retry_rate_limited_modal_jobs_once()
    logger.info("Retry rate-limited modal jobs result: %s", result)
    print(result)
