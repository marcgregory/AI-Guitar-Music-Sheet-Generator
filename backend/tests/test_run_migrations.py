import logging
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from run_migrations import _execute_sql_statement


def test_duplicate_additive_column_skip_is_success(caplog):
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE transcriptions ("
                "id INTEGER PRIMARY KEY, "
                "original_audio_url TEXT"
                ")"
            )
        )

        with caplog.at_level(logging.INFO):
            _execute_sql_statement(
                conn,
                "ALTER TABLE transcriptions ADD COLUMN original_audio_url TEXT",
            )
            _execute_sql_statement(
                conn,
                "ALTER TABLE transcriptions ADD COLUMN separated_audio_url TEXT",
            )

        columns = {
            column["name"]
            for column in inspect(conn).get_columns("transcriptions")
        }

    assert "original_audio_url" in columns
    assert "separated_audio_url" in columns
    assert "column_skipped_already_exists table=transcriptions column=original_audio_url" in caplog.text
    assert "column_added table=transcriptions column=separated_audio_url" in caplog.text
