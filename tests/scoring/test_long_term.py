from datetime import date

import numpy as np
import pandas as pd

from src.data.index_valuation import ValuationSnapshot
from src.scoring.long_term import compute_long_term_score


def _frames(length: int = 500) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range("2024-01-01", periods=length, freq="D")
    benchmark = np.array([100 * (1.0007**index) for index in range(length)])
    nav = benchmark / benchmark[0] * 1.2
    return (
        pd.DataFrame(
            {"trade_date": dates.strftime("%Y-%m-%d"), "unit_nav": nav}
        ),
        pd.DataFrame(
            {"trade_date": dates.strftime("%Y-%m-%d"), "close": benchmark}
        ),
    )


def _valuation(percentile: float, available: bool = True) -> ValuationSnapshot:
    return ValuationSnapshot(
        benchmark_code="NDX",
        metric="forward_pe",
        value=24.29,
        percentile=percentile,
        data_date=date.today().isoformat(),
        source="test",
        sample_count=120,
        cache_status="fresh",
        available=available,
        issues=(),
    )


def test_long_term_requires_real_valuation():
    nav, benchmark = _frames()

    result = compute_long_term_score(nav, benchmark, None)

    assert result.score is None
    assert result.issues == ["valuation_missing"]


def test_lower_valid_pe_percentile_improves_valuation_factor():
    nav, benchmark = _frames()

    low = compute_long_term_score(nav, benchmark, _valuation(0.25))
    high = compute_long_term_score(nav, benchmark, _valuation(0.85))

    assert low.factors["valuation"] > high.factors["valuation"]
    assert low.score > high.score


def test_long_term_rewards_stable_positive_trend():
    nav, benchmark = _frames()

    result = compute_long_term_score(nav, benchmark, _valuation(0.5))

    assert result.score is not None
    assert result.factors["trend"] >= 70
    assert result.factors["tracking"] >= 90
    assert 0 <= result.score <= 100
