"""Persist refresh status separately from the downloaded market data."""
from __future__ import annotations

from pathlib import Path

from src.db import get_conn


def record_source_attempt(
    db_path: str | Path,
    source: str,
    subject: str,
    success: bool,
    row_count: int = 0,
    latest_data_date: str | None = None,
    error: str | None = None,
    attempted_at: str | None = None,
) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO data_source_status(
                source, subject, last_attempt_at, last_success_at,
                row_count, latest_data_date, last_error
            ) VALUES (?, ?, COALESCE(?, CURRENT_TIMESTAMP),
                      CASE WHEN ? THEN COALESCE(?, CURRENT_TIMESTAMP) END,
                      ?, ?, ?)
            ON CONFLICT(source, subject) DO UPDATE SET
                last_attempt_at = excluded.last_attempt_at,
                last_success_at = CASE
                    WHEN ? THEN excluded.last_success_at
                    ELSE data_source_status.last_success_at
                END,
                row_count = CASE
                    WHEN ? THEN excluded.row_count
                    ELSE data_source_status.row_count
                END,
                latest_data_date = CASE
                    WHEN ? THEN excluded.latest_data_date
                    ELSE data_source_status.latest_data_date
                END,
                last_error = CASE WHEN ? THEN NULL ELSE excluded.last_error END
            """,
            (
                source,
                subject,
                attempted_at,
                success,
                attempted_at,
                row_count,
                latest_data_date,
                error,
                success,
                success,
                success,
                success,
            ),
        )


def load_source_status(
    db_path: str | Path, source: str, subject: str
) -> dict | None:
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM data_source_status WHERE source = ? AND subject = ?",
            (source, subject),
        ).fetchone()
    return dict(row) if row else None
