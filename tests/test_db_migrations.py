import sqlite3

from src.data.status import load_source_status, record_source_attempt
from src.db import init_db


def test_init_db_is_idempotent_and_adds_observation_schema(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    init_db(path)
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(daily_scores)")}
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {
        "observation_level",
        "quality_status",
        "quality_json",
        "scoring_version",
    } <= columns
    assert {"data_source_status", "signal_outcomes"} <= tables


def test_source_status_preserves_last_success_on_failure(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    record_source_attempt(path, "fund_nav", "000001", True, 10, "2026-06-26")
    record_source_attempt(
        path, "fund_nav", "000001", False, 0, None, "timeout"
    )
    status = load_source_status(path, "fund_nav", "000001")
    assert status is not None
    assert status["last_success_at"] is not None
    assert status["row_count"] == 10
    assert status["last_error"] == "timeout"
