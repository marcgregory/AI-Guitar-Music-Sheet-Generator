#!/usr/bin/env python3
"""
Run SQL migration files in the migrations directory in order.
"""
import os
import glob
from sqlalchemy import text
from app.database_init import engine, SessionLocal
import logging
import re

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

                # Split by semicolon but preserve semicolons within $$ blocks
                # This regex splits on semicolons that are not inside $$ blocks
                statements = []
                current_statement = ""
                in_dollar_quote = False
                dollar_quote_depth = 0

                i = 0
                while i < len(sql_content):
                    char = sql_content[i]

                    # Check for dollar quote start/end
                    if char == '$' and i + 1 < len(sql_content) and sql_content[i+1] == '$':
                        # Look for the end of the dollar quote delimiter
                        j = i + 2
                        while j < len(sql_content) and sql_content[j] != '$':
                            j += 1
                        if j < len(sql_content) and j + 1 < len(sql_content) and sql_content[j+1] == '$':
                            # Found end delimiter
                            if not in_dollar_quote:
                                # Starting a dollar quote block
                                in_dollar_quote = True
                                dollar_quote_depth += 1
                                current_statement += sql_content[i:j+2]  # Add $$
                                i = j + 2
                                continue
                            else:
                                # Ending a dollar quote block
                                dollar_quote_depth -= 1
                                if dollar_quote_depth == 0:
                                    in_dollar_quote = False
                                    current_statement += sql_content[i:j+2]  # Add $$
                                    i = j + 2
                                    continue
                                else:
                                    # Nested dollar quote, just add the characters
                                    current_statement += char
                                    i += 1
                                    continue

                    # Handle semicolon splitting
                    if char == ';' and not in_dollar_quote:
                        # End of statement
                        if current_statement.strip():
                            statements.append(current_statement.strip())
                        current_statement = ""
                    else:
                        current_statement += char

                    i += 1

                # Add the last statement if it exists
                if current_statement.strip():
                    statements.append(current_statement.strip())

                # Execute each statement
                for statement in statements:
                    if statement:  # Skip empty statements
                        logger.debug("Executing statement: %s", statement[:100] + "..." if len(statement) > 100 else statement)
                        conn.execute(text(statement))

                conn.commit()
                logger.info("Successfully ran migration: %s", os.path.basename(migration_file))
            except Exception as e:
                logger.error("Failed to run migration %s: %s", os.path.basename(migration_file), str(e))
                logger.error("SQL content: %s", sql_content[:500] + "..." if len(sql_content) > 500 else sql_content)
                conn.rollback()
                raise

if __name__ == "__main__":
    run_migrations()