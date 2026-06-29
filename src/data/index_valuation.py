"""Lightweight index valuation fetch and SQLite cache."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from src.data.status import load_source_status, record_source_attempt
from src.db import get_conn

NDX_FORWARD_PE_URL = "https://historyofmarket.com/api/ndx/forward-pe.json"
NDX_FORWARD_PE_SOURCE = "History of Market / Bloomberg BEst"


class ValuationDataError(ValueError):
    """Raised when an upstream valuation payload cannot be audited."""


@dataclass(frozen=True)
class ParsedValuation:
    data_date: str
    points: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class ValuationSnapshot:
    benchmark_code: str
    metric: str
    value: float | None
    percentile: float | None
    data_date: str | None
    source: str | None
    sample_count: int
    cache_status: str
    available: bool
    issues: tuple[str, ...]


def _positive_number(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValuationDataError(f"invalid {field}") from exc
    if number <= 0:
        raise ValuationDataError(f"invalid {field}")
    return number


def parse_ndx_forward_pe(payload: dict[str, Any]) -> ParsedValuation:
    if not isinstance(payload, dict):
        raise ValuationDataError("payload must be an object")
    try:
        updated = date.fromisoformat(str(payload["updated"])[:10]).isoformat()
        current = _positive_number(payload["current"]["forward"], "current.forward")
        history = payload["forward"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValuationDataError("missing NDX forward PE fields") from exc
    if not isinstance(history, list) or not history:
        raise ValuationDataError("forward PE history is empty")

    points: dict[str, float] = {}
    for item in history:
        if not isinstance(item, dict):
            raise ValuationDataError("invalid forward PE history row")
        try:
            data_date = date.fromisoformat(str(item["date"])[:10]).isoformat()
            value = _positive_number(item["value"], "forward.value")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValuationDataError("invalid forward PE history row") from exc
        points[data_date] = value
    points[updated] = current
    return ParsedValuation(updated, tuple(sorted(points.items())))


def fetch_ndx_forward_pe() -> dict[str, Any]:
    headers = {"User-Agent": "fund-trends/observation-v2 (+research use)"}
    with httpx.Client(timeout=8.0, follow_redirects=True, headers=headers) as client:
        response = client.get(NDX_FORWARD_PE_URL)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValuationDataError("NDX valuation response is not an object")
    return payload


def _save_history(
    db_path: str | Path,
    benchmark_code: str,
    metric: str,
    source: str,
    parsed: ParsedValuation,
) -> int:
    rows = [
        (benchmark_code, metric, data_date, value, source)
        for data_date, value in parsed.points
    ]
    with get_conn(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO index_valuations(
                benchmark_code, metric, data_date, value, source
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(benchmark_code, metric, data_date) DO UPDATE SET
                value = excluded.value,
                source = excluded.source,
                fetched_at = CURRENT_TIMESTAMP
            """,
            rows,
        )
    return len(rows)


def load_valuation_snapshot(
    db_path: str | Path,
    benchmark_code: str,
    metric: str,
    *,
    as_of: date | None = None,
    max_age_days: int = 7,
    min_samples: int = 60,
) -> ValuationSnapshot:
    evaluation_date = as_of or date.today()
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT data_date, value, source
            FROM index_valuations
            WHERE benchmark_code = ? AND metric = ?
              AND data_date <= ?
            ORDER BY data_date DESC
            LIMIT 120
            """,
            (benchmark_code, metric, evaluation_date.isoformat()),
        ).fetchall()
    if not rows:
        return ValuationSnapshot(
            benchmark_code,
            metric,
            None,
            None,
            None,
            None,
            0,
            "missing",
            False,
            ("valuation_missing",),
        )

    latest = rows[0]
    data_date = str(latest["data_date"])
    age_days = (evaluation_date - date.fromisoformat(data_date)).days
    values = [float(row["value"]) for row in rows]
    current = float(latest["value"])
    percentile = sum(value <= current for value in values) / len(values)
    issues: list[str] = []
    if len(values) < min_samples:
        issues.append("valuation_history_insufficient")
    if age_days > max_age_days:
        issues.append("valuation_stale")
    available = not issues
    cache_status = "fresh" if age_days == 0 else "cached"
    if "valuation_stale" in issues:
        cache_status = "stale"
    return ValuationSnapshot(
        benchmark_code,
        metric,
        current,
        round(percentile, 4),
        data_date,
        str(latest["source"]),
        len(values),
        cache_status,
        available,
        tuple(issues),
    )


def refresh_index_valuation(
    db_path: str | Path,
    benchmark_code: str,
    *,
    provider: Callable[[], dict[str, Any]] = fetch_ndx_forward_pe,
    as_of: date | None = None,
    max_age_days: int = 7,
    min_samples: int = 60,
) -> ValuationSnapshot:
    refresh_date = as_of or date.today()
    metric = "forward_pe"
    status = load_source_status(db_path, "index_valuation", benchmark_code)
    if status and str(status["last_attempt_at"])[:10] == refresh_date.isoformat():
        snapshot = load_valuation_snapshot(
            db_path,
            benchmark_code,
            metric,
            as_of=refresh_date,
            max_age_days=max_age_days,
            min_samples=min_samples,
        )
        if status.get("last_error") and "refresh_failed" not in snapshot.issues:
            return ValuationSnapshot(
                **{
                    **snapshot.__dict__,
                    "cache_status": "cached" if snapshot.available else snapshot.cache_status,
                    "issues": (*snapshot.issues, "refresh_failed"),
                }
            )
        return snapshot

    try:
        parsed = parse_ndx_forward_pe(provider())
        count = _save_history(
            db_path,
            benchmark_code,
            metric,
            NDX_FORWARD_PE_SOURCE,
            parsed,
        )
        record_source_attempt(
            db_path,
            "index_valuation",
            benchmark_code,
            True,
            count,
            parsed.data_date,
            attempted_at=refresh_date.isoformat(),
        )
    except Exception as exc:
        record_source_attempt(
            db_path,
            "index_valuation",
            benchmark_code,
            False,
            error=str(exc),
            attempted_at=refresh_date.isoformat(),
        )
        cached = load_valuation_snapshot(
            db_path,
            benchmark_code,
            metric,
            as_of=refresh_date,
            max_age_days=max_age_days,
            min_samples=min_samples,
        )
        return ValuationSnapshot(
            **{
                **cached.__dict__,
                "cache_status": "cached" if cached.available else cached.cache_status,
                "issues": (*cached.issues, "refresh_failed"),
            }
        )

    return load_valuation_snapshot(
        db_path,
        benchmark_code,
        metric,
        as_of=refresh_date,
        max_age_days=max_age_days,
        min_samples=min_samples,
    )
