from __future__ import annotations

from src.db import get_conn, init_db
from scripts.run_report_once import has_successful_push


def test_has_successful_push_requires_success(tmp_path):
    db_path = tmp_path / "fund_trends.db"
    init_db(db_path)

    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO push_history(push_type, push_date, title, content, success, error) "
            "VALUES (?,?,?,?,?,?)",
            ("daily", "2026-07-24", "failed", "", 0, "boom"),
        )

    assert not has_successful_push(db_path, "daily", "2026-07-24")

    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO push_history(push_type, push_date, title, content, success, error) "
            "VALUES (?,?,?,?,?,?)",
            ("daily", "2026-07-24", "ok", "", 1, None),
        )

    assert has_successful_push(db_path, "daily", "2026-07-24")
    assert not has_successful_push(db_path, "weekly", "2026-07-24")
