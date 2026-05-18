#!/usr/bin/env python3
"""Run SQL migration files and Alembic migrations for the backend."""
import glob
import logging
import os
from sqlalchemy import text
from alembic.config import Config
from alembic import command
from app.database_init import engine
from app.db import Base
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
            logger.info("Running SQL migration: %s", os.path.basename(migration_file))
            with open(migration_file, "r", encoding="utf-8") as f:
                sql_content = f.read()

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

            for statement in statements:
                logger.debug("Executing SQL statement: %s", statement[:120])
                conn.execute(text(statement))
            conn.commit()


def run_migrations() -> None:
    logger.info("Creating base metadata tables if missing")
    Base.metadata.create_all(bind=engine)
    _run_sql_migrations()

    alembic_cfg = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

    logger.info("Running Alembic upgrade head")
    command.upgrade(alembic_cfg, "head")
    logger.info("Alembic migrations complete")


if __name__ == "__main__":
    run_migrations()
