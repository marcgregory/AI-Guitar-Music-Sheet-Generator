#!/usr/bin/env python3
"""Run SQL migration files and Alembic migrations for the backend."""
import glob
import logging
import os
import re
from sqlalchemy import inspect, text
from alembic.config import Config
from alembic import command
from app.database_init import engine
from app.db import Base
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_ADD_COLUMN_RE = re.compile(
    r"""
    ALTER\s+TABLE\s+
    (?P<table>"?[A-Za-z_][A-Za-z0-9_]*"?)
    \s+ADD\s+COLUMN\s+
    (?P<column>"?[A-Za-z_][A-Za-z0-9_]*"?)
    \s+
    (?P<definition>.+?)
    \s*;?\s*$
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


def _split_sql_statements(sql_content: str) -> list[str]:
    statements = []
    current_statement = ""
    in_dollar_quote = False
    i = 0
    while i < len(sql_content):
        char = sql_content[i]
        if char == "$" and i + 1 < len(sql_content) and sql_content[i + 1] == "$":
            current_statement += "$$"
            i += 2
            in_dollar_quote = not in_dollar_quote
            continue

        if char == ";" and not in_dollar_quote:
            if current_statement.strip():
                statements.append(current_statement.strip())
            current_statement = ""
        else:
            current_statement += char
        i += 1

    if current_statement.strip():
        statements.append(current_statement.strip())

    return statements


def _strip_leading_comments(statement: str) -> str:
    lines = statement.strip().splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and lines[0].lstrip().startswith("--"):
        lines.pop(0)
    return "\n".join(lines).strip()


def _extract_add_column(statement: str) -> tuple[str, str, str] | None:
    cleaned = _strip_leading_comments(statement)
    candidates = [cleaned]

    if cleaned.upper().startswith("DO $$"):
        candidates = re.findall(
            r"ALTER\s+TABLE\s+.+?\s+ADD\s+COLUMN\s+.+?(?=;)",
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        )

    for candidate in candidates:
        match = _ADD_COLUMN_RE.match(candidate.strip())
        if not match:
            continue
        table_name = match.group("table").strip('"')
        column_name = match.group("column").strip('"')
        column_definition = f"{column_name} {match.group('definition').strip()}"
        return table_name, column_name, column_definition

    return None


def _execute_sql_statement(conn, statement: str) -> None:
    add_column = _extract_add_column(statement)
    if not add_column:
        logger.debug("Executing SQL statement: %s", statement[:120])
        conn.execute(text(statement))
        return

    table_name, column_name, column_definition = add_column
    inspector = inspect(conn)
    table_names = set(inspector.get_table_names())
    if table_name not in table_names:
        logger.debug("Executing SQL statement: %s", statement[:120])
        conn.execute(text(statement))
        return

    existing_columns = {
        column["name"]
        for column in inspector.get_columns(table_name)
    }
    logger.info(
        "existing_columns_detected table=%s count=%d",
        table_name,
        len(existing_columns),
    )

    if column_name in existing_columns:
        logger.info(
            "column_skipped_already_exists table=%s column=%s",
            table_name,
            column_name,
        )
        return

    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_definition}"))
    logger.info("column_added table=%s column=%s", table_name, column_name)


def _run_sql_migrations() -> None:
    migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")
    if not os.path.exists(migrations_dir):
        logger.info("No SQL migrations directory found at %s", migrations_dir)
        return

    migration_files = sorted(glob.glob(os.path.join(migrations_dir, "*.sql")))
    if not migration_files:
        logger.info("No SQL migration files found.")
        return

    logger.info("Found %d SQL migrations", len(migration_files))
    with engine.connect() as conn:
        for migration_file in migration_files:
            logger.info(
                "migration_started migration=%s",
                os.path.basename(migration_file),
            )
            logger.info("Running SQL migration: %s", os.path.basename(migration_file))
            with open(migration_file, "r", encoding="utf-8") as f:
                sql_content = f.read()

            statements = _split_sql_statements(sql_content)
            for statement in statements:
                _execute_sql_statement(conn, statement)
            conn.commit()
            logger.info(
                "migration_completed migration=%s",
                os.path.basename(migration_file),
            )


def _ensure_alembic_version_table(conn) -> None:
    inspector = inspect(conn)
    table_names = set(inspector.get_table_names())

    if "alembic_version" not in table_names:
        conn.execute(
            text(
                "CREATE TABLE alembic_version ("
                "version_num VARCHAR(255) NOT NULL PRIMARY KEY"
                ")"
            )
        )
        logger.info("alembic_version_table_created version_num_length=255")
        return

    version_column = next(
        (
            column
            for column in inspector.get_columns("alembic_version")
            if column["name"] == "version_num"
        ),
        None,
    )
    if not version_column:
        logger.warning("alembic_version_missing_version_num_column")
        return

    version_length = getattr(version_column["type"], "length", None)
    if conn.dialect.name == "postgresql" and version_length and version_length < 255:
        conn.execute(
            text(
                "ALTER TABLE alembic_version "
                "ALTER COLUMN version_num TYPE VARCHAR(255)"
            )
        )
        logger.info(
            "alembic_version_column_widened old_length=%s new_length=255",
            version_length,
        )


def _prepare_alembic_version_table() -> None:
    with engine.begin() as conn:
        _ensure_alembic_version_table(conn)


def run_migrations() -> None:
    logger.info("Creating base metadata tables if missing")
    Base.metadata.create_all(bind=engine)
    _run_sql_migrations()
    _prepare_alembic_version_table()

    alembic_cfg = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

    logger.info("Running Alembic upgrade head")
    command.upgrade(alembic_cfg, "head")
    logger.info("Alembic migrations complete")


if __name__ == "__main__":
    run_migrations()
