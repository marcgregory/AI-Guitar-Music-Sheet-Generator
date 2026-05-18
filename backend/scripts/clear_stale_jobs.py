import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import db, models  # noqa: E402
from app.core.config import settings  # noqa: E402

ACTIVE_STATUSES = ("pending", "queued", "processing")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clear stale transcription queue state for local/admin recovery."
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=settings.STALE_TRANSCRIPTION_TIMEOUT_SECONDS,
        help="Only clear active jobs older than this many seconds.",
    )
    parser.add_argument(
        "--status",
        choices=("all", "pending", "queued", "processing"),
        default="all",
        help="Restrict cleanup to one active status.",
    )
    parser.add_argument(
        "--mark",
        choices=("failed", "cancelled"),
        default="failed",
        help="Terminal status to apply to stale active jobs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print matching jobs without changing them.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(0, args.timeout_seconds))
    statuses = ACTIVE_STATUSES if args.status == "all" else (args.status,)

    session = db.SessionLocal()
    try:
        jobs = (
            session.query(models.Transcription)
            .filter(models.Transcription.is_deleted == False)
            .filter(models.Transcription.processing_status.in_(statuses))
            .filter(models.Transcription.created_at < cutoff)
            .order_by(models.Transcription.created_at.asc(), models.Transcription.id.asc())
            .all()
        )

        for job in jobs:
            print(
                f"{job.id}: {job.title!r} status={job.processing_status} "
                f"created_at={job.created_at}"
            )

        if args.dry_run:
            print(f"Matched {len(jobs)} stale job(s); no changes made.")
            return 0

        for job in jobs:
            job.processing_status = args.mark
            job.processing_error = (
                "Processing job timed out without worker activity and was reset locally."
            )
            job.queue_position = None
            job.estimated_wait_time = None
            job.celery_task_id = None
            job.is_processed = False
            session.add(job)

        session.commit()
        print(f"Marked {len(jobs)} stale job(s) as {args.mark}.")
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
