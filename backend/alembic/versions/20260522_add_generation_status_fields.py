import logging

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260522_add_generation_status_fields"
down_revision = "20260520_add_missing_transcription_fields"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def _ensure_column(column: sa.Column) -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_columns = {
        existing["name"]
        for existing in inspector.get_columns("transcriptions")
    }
    if column.name in existing_columns:
        logger.info(
            "column_skipped_already_exists table=transcriptions column=%s",
            column.name,
        )
        return
    op.add_column("transcriptions", column)
    logger.info("column_added table=transcriptions column=%s", column.name)


def upgrade() -> None:
    logger.info("migration_started revision=%s", revision)
    _ensure_column(
        sa.Column(
            "tab_generation_status",
            sa.String(),
            nullable=False,
            server_default="idle",
        )
    )
    _ensure_column(
        sa.Column(
            "rhythm_generation_status",
            sa.String(),
            nullable=False,
            server_default="idle",
        )
    )
    op.execute(
        "UPDATE transcriptions "
        "SET tab_generation_status = 'idle' "
        "WHERE tab_generation_status IS NULL"
    )
    op.execute(
        "UPDATE transcriptions "
        "SET rhythm_generation_status = 'idle' "
        "WHERE rhythm_generation_status IS NULL"
    )
    logger.info("migration_completed revision=%s", revision)


def downgrade() -> None:
    op.drop_column("transcriptions", "rhythm_generation_status")
    op.drop_column("transcriptions", "tab_generation_status")
