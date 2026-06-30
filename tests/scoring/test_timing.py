import numpy as np
import pandas as pd

from src.scoring.timing import compute_timing_score


def _frame(values) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=len(values), freq="D")
    return pd.DataFrame(
        {"trade_date": dates.strftime("%Y-%m-%d"), "unit_nav": values}
    )


def _steady_growth(length: int) -> list[float]:
    return [100 * (1.0008**index) for index in range(length)]


def test_steady_uptrend_is_not_penalized_for_new_high():
    result = compute_timing_score(_frame(_steady_growth(300)))

    assert result.score is not None
    assert result.score >= 40
    assert result.factors["trend"] >= 70
    assert "quantile_1y" not in result.metrics


def test_sudden_spike_reduces_timing_but_not_trend():
    baseline = _steady_growth(300)
    spiked = baseline[:295] + [140, 148, 157, 167, 178]

    steady = compute_timing_score(_frame(baseline))
    spike = compute_timing_score(_frame(spiked))

    assert spike.factors["trend"] >= steady.factors["trend"]
    assert spike.factors["deviation"] < steady.factors["deviation"]
    assert spike.score < steady.score


def test_falling_knife_scores_below_stabilized_drawdown():
    rising = np.linspace(100, 140, 220)
    falling = np.concatenate([rising, np.linspace(140, 95, 80)])
    stabilized = np.concatenate(
        [rising, np.linspace(140, 98, 60), np.linspace(98, 101, 20)]
    )

    falling_result = compute_timing_score(_frame(falling))
    stabilized_result = compute_timing_score(_frame(stabilized))

    assert falling_result.factors["stabilization"] < 40
    assert stabilized_result.factors["stabilization"] > falling_result.factors["stabilization"]
    assert stabilized_result.score > falling_result.score


def test_timing_requires_long_enough_history():
    result = compute_timing_score(_frame(_steady_growth(100)))

    assert result.score is None
    assert result.issues == ["timing_history_insufficient"]
