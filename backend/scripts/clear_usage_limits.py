"""Clear local usage-limit counters for testing.

Examples:
    python scripts/clear_usage_limits.py --username demo
    python scripts/clear_usage_limits.py --email demo@example.com --all-days
    python scripts/clear_usage_limits.py --username demo --clear-active-jobs
    python scripts/clear_usage_limits.py --username your_username --dry-run
This deletes UsageEvent rows. It only marks active jobs cancelled when
--clear-active-jobs is provided.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app import models  # noqa: E402
from app.db import DATABASE_URL, SessionLocal  # noqa: E402


ACTIVE_STATUSES = {"pending", "queued", "processing"}


def utc_day_start() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clear UsageEvent rows for a user so local testing is no longer daily-limit blocked."
    )
    user_group = parser.add_mutually_exclusive_group(required=True)
    user_group.add_argument("--username", help="Username whose usage counter should be reset.")
    user_group.add_argument("--email", help="Email whose usage counter should be reset.")
    user_group.add_argument("--user-id", type=int, help="User id whose usage counter should be reset.")
    user_group.add_argument(
        "--all-users",
        action="store_true",
        help="Reset usage counters for every user. Requires --yes.",
    )
    parser.add_argument(
        "--all-days",
        action="store_true",
        help="Delete all usage events for the target user instead of only today's UTC events.",
    )
    parser.add_argument(
        "--clear-active-jobs",
        action="store_true",
        help="Also mark pending/queued/processing transcriptions as cancelled/deleted to clear active-job blocks.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be cleared without changing the database.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required with --all-users.",
    )
    return parser.parse_args()


def find_users(session, args: argparse.Namespace) -> list[models.User]:
    query = session.query(models.User)
    if args.all_users:
        if not args.yes:
            raise SystemExit("--all-users requires --yes")
        return query.order_by(models.User.id.asc()).all()
    if args.username:
        query = query.filter(models.User.username == args.username)
    elif args.email:
        query = query.filter(models.User.email == args.email)
    else:
        query = query.filter(models.User.id == args.user_id)
    users = query.all()
    if not users:
        raise SystemExit("No matching user found.")
    return users


def main() -> int:
    args = parse_args()
    day_start = utc_day_start()

    session = SessionLocal()
    try:
        users = find_users(session, args)
        user_ids = [user.id for user in users]

        usage_query = session.query(models.UsageEvent).filter(
            models.UsageEvent.user_id.in_(user_ids)
        )
        if not args.all_days:
            usage_query = usage_query.filter(models.UsageEvent.created_at >= day_start)
        usage_count = usage_query.count()

        active_query = session.query(models.Transcription).filter(
            models.Transcription.user_id.in_(user_ids),
            models.Transcription.is_deleted == False,  # noqa: E712
            models.Transcription.processing_status.in_(ACTIVE_STATUSES),
        )
        active_jobs = active_query.all()

        user_labels = ", ".join(f"{user.username}#{user.id}" for user in users)
        scope = "all days" if args.all_days else f"since {day_start.isoformat()}"
        print(f"Database: {DATABASE_URL}")
        print(f"Users: {user_labels}")
        print(f"Usage events to delete ({scope}): {usage_count}")
        print(f"Active jobs found: {len(active_jobs)}")

        if args.dry_run:
            print("Dry run only; no changes made.")
            return 0

        usage_query.delete(synchronize_session=False)

        cancelled_count = 0
        if args.clear_active_jobs:
            now = datetime.now(timezone.utc)
            for transcription in active_jobs:
                transcription.processing_status = "cancelled"
                transcription.processing_error = "Cancelled by local testing usage-limit reset script."
                transcription.is_deleted = True
                transcription.deleted_at = now
                transcription.queue_position = None
                transcription.estimated_wait_time = None
                transcription.celery_task_id = None
                cancelled_count += 1
                session.add(transcription)

        session.commit()
        print(f"Deleted usage events: {usage_count}")
        print(f"Cancelled active jobs: {cancelled_count}")
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
