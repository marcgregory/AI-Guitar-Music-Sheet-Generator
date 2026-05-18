#!/usr/bin/env python3
"""
Run SQL migration files in the migrations directory in order.
"""
import os
import glob
from sqlalchemy import text
from app.database_init import engine, SessionLocal
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migrations():
    """Run all SQL migration files in order."""
    migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")
    if not os.path.exists(migrations_dir):
        logger.warning("Migrations directory not found: %s", migrations_dir)
        return

    # Get all .sql files and sort them by name (which should be timestamped)
    migration_files = sorted(glob.glob(os.path.join(migrations_dir, "*.sql")))

    if not migration_files:
        logger.info("No migration files found.")
        return

    logger.info("Found %d migration files to process", len(migration_files))

    with engine.connect() as conn:
        for migration_file in migration_files:
            logger.info("Running migration: %s", os.path.basename(migration_file))
            try:
                with open(migration_file, 'r') as f:
                    sql_content = f.read()

                # Split by semicolon and execute each statement
                statements = [stmt.strip() for stmt in sql_content.split(';') if stmt.strip()]
                for statement in statements:
                    if statement:  # Skip empty statements
                        conn.execute(text(statement))

                conn.commit()
                logger.info("Successfully ran migration: %s", os.path.basename(migration_file))
            except Exception as e:
                logger.error("Failed to run migration %s: %s", os.path.basename(migration_file), str(e))
                conn.rollback()
                raise

if __name__ == "__main__":
    run_migrations()