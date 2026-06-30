from datetime import date

import pytest

from src.data.index_valuation import (
    ValuationDataError,
    load_valuation_snapshot,
    parse_ndx_forward_pe,
    refresh_index_valuation,
)
from src.db import get_conn, init_db


def _payload(updated: str = "2026-06-27") -> dict:
    history = [
        {"date": f"{year}-{month:02d}-28", "value": 15 + (month % 8)}
        for year in range(2021, 2026)
        for month in range(1, 13)
    ]
    return {
        "updated": updated,
        "current": {"forward": 24.29},
        "forward": history,
    }


def test_parse_ndx_forward_pe_rejects_invalid_payload():
    with pytest.raises(ValuationDataError):
        parse_ndx_forward_pe({"updated": "2026-06-27", "forward": []})


def test_refresh_once_shares_cache_for_same_benchmark(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    calls: list[int] = []

    def provider() -> dict:
        calls.append(1)
        return _payload()

    first = refresh_index_valuation(
        path, "NDX", provider=provider, as_of=date(2026, 6, 27)
    )
    second = refresh_index_valuation(
        path, "NDX", provider=provider, as_of=date(2026, 6, 27)
    )

    assert len(calls) == 1
    assert first.value == second.value == 24.29
    assert first.available is True
    assert first.sample_count == 61
    with get_conn(path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM index_valuations WHERE benchmark_code = 'NDX'"
        ).fetchone()[0]
    assert count == 61


def test_cache_older_than_seven_days_is_not_scoreable(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    refresh_index_valuation(
        path,
        "NDX",
        provider=lambda: _payload("2026-06-27"),
        as_of=date(2026, 6, 27),
    )

    snapshot = load_valuation_snapshot(
        path,
        "NDX",
        "forward_pe",
        as_of=date(2026, 7, 10),
        max_age_days=7,
        min_samples=60,
    )

    assert snapshot.available is False
    assert snapshot.cache_status == "stale"
    assert "valuation_stale" in snapshot.issues


def test_failed_refresh_uses_fresh_cache(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    refresh_index_valuation(
        path,
        "NDX",
        provider=lambda: _payload("2026-06-26"),
        as_of=date(2026, 6, 26),
    )

    def failed_provider() -> dict:
        raise RuntimeError("upstream unavailable")

    snapshot = refresh_index_valuation(
        path,
        "NDX",
        provider=failed_provider,
        as_of=date(2026, 6, 27),
    )

    assert snapshot.available is True
    assert snapshot.cache_status == "cached"
    assert "refresh_failed" in snapshot.issues
