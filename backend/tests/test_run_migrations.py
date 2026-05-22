import logging
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy import String

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_migrations
from run_migrations import _ensure_alembic_version_table, _execute_sql_statement


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


def test_alembic_version_table_created_with_long_version_column():
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as conn:
        _ensure_alembic_version_table(conn)
        conn.execute(
            text(
                "INSERT INTO alembic_version (version_num) "
                "VALUES ('20260520_add_missing_transcription_fields')"
            )
        )
        columns = {
            column["name"]: column
            for column in inspect(conn).get_columns("alembic_version")
        }
        version_rows = conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).fetchall()

    assert "version_num" in columns
    assert getattr(columns["version_num"]["type"], "length", None) == 255
    assert version_rows == [("20260520_add_missing_transcription_fields",)]


def test_postgresql_short_alembic_version_column_is_widened(monkeypatch):
    executed = []

    class FakeDialect:
        name = "postgresql"

    class FakeConnection:
        dialect = FakeDialect()

        def execute(self, statement):
            executed.append(str(statement))

    class FakeInspector:
        def get_table_names(self):
            return ["alembic_version"]

        def get_columns(self, table_name):
            assert table_name == "alembic_version"
            return [{"name": "version_num", "type": String(32)}]

    monkeypatch.setattr(
        run_migrations,
        "inspect",
        lambda conn: FakeInspector(),
    )

    _ensure_alembic_version_table(FakeConnection())

    assert executed == [
        "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)"
    ]
