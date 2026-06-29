"""Long-term holding-condition score."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src.config import LongTermWeights
from src.data.index_valuation import ValuationSnapshot
from src.scoring.common import (
    HorizonScore,
    clamp_score,
    score_level,
    value_series,
)


def _trend_factor(values: pd.Series) -> tuple[float, dict[str, float]]:
    current = float(values.iloc[-1])
    ma200 = values.rolling(200).mean()
    ma200_now = float(ma200.iloc[-1])
    ma200_previous = float(ma200.iloc[-21])
    slope = ma200_now / ma200_previous - 1 if ma200_previous else 0.0
    return_126 = current / float(values.iloc[-127]) - 1
    return_252 = current / float(values.iloc[-253]) - 1
    position_score = float(np.clip(50 + (current / ma200_now - 1) / 0.15 * 50, 0, 100))
    slope_score = float(np.clip(50 + slope / 0.04 * 50, 0, 100))
    momentum_score = float(
        np.clip(50 + (return_126 * 0.4 + return_252 * 0.6) / 0.25 * 50, 0, 100)
    )
    score = clamp_score(
        position_score * 0.3 + slope_score * 0.3 + momentum_score * 0.4
    )
    return score, {
        "ma200_slope_pct": round(slope * 100, 2),
        "return_6m_pct": round(return_126 * 100, 2),
        "return_12m_pct": round(return_252 * 100, 2),
    }


def _risk_factor(values: pd.Series) -> tuple[float, dict[str, float]]:
    recent = values.iloc[-min(750, len(values)) :]
    returns = recent.pct_change().dropna()
    volatility = float(returns.std(ddof=0) * math.sqrt(252))
    drawdowns = recent / recent.cummax() - 1
    max_drawdown = float(drawdowns.min())
    volatility_score = float(np.clip(100 - max(0.0, volatility - 0.10) / 0.25 * 100, 0, 100))
    drawdown_score = float(np.clip(100 - abs(max_drawdown) / 0.50 * 100, 0, 100))
    return clamp_score(volatility_score * 0.5 + drawdown_score * 0.5), {
        "annualized_volatility_pct": round(volatility * 100, 2),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
    }


def _tracking_factor(
    nav_df: pd.DataFrame, benchmark_df: pd.DataFrame
) -> tuple[float | None, dict[str, float]]:
    nav_column = next((name for name in ("unit_nav", "close", "value") if name in nav_df), None)
    benchmark_column = next(
        (name for name in ("close", "value", "unit_nav") if name in benchmark_df), None
    )
    if not nav_column or not benchmark_column or "trade_date" not in nav_df or "trade_date" not in benchmark_df:
        return None, {}
    nav = nav_df[["trade_date", nav_column]].rename(columns={nav_column: "nav"})
    benchmark = benchmark_df[["trade_date", benchmark_column]].rename(
        columns={benchmark_column: "benchmark"}
    )
    aligned = nav.merge(benchmark, on="trade_date", how="inner").tail(500)
    if len(aligned) < 80:
        return None, {}
    nav_returns = pd.to_numeric(aligned["nav"], errors="coerce").pct_change()
    benchmark_returns = pd.to_numeric(
        aligned["benchmark"], errors="coerce"
    ).pct_change()
    valid = pd.DataFrame({"nav": nav_returns, "benchmark": benchmark_returns}).dropna()
    if len(valid) < 60:
        return None, {}
    if np.allclose(valid["nav"], valid["benchmark"], rtol=1e-6, atol=1e-10):
        correlation = 1.0
    else:
        correlations = [
            valid["nav"].corr(valid["benchmark"].shift(lag))
            for lag in range(-2, 3)
        ]
        finite_correlations = [
            float(value) for value in correlations if pd.notna(value)
        ]
        correlation = max(finite_correlations, default=0.0)
    tracking_error = float(
        (valid["nav"] - valid["benchmark"]).std(ddof=0) * math.sqrt(252)
    )
    correlation_score = float(np.clip((correlation - 0.4) / 0.55 * 100, 0, 100))
    error_score = float(np.clip(100 - tracking_error / 0.15 * 100, 0, 100))
    return clamp_score(correlation_score * 0.6 + error_score * 0.4), {
        "tracking_correlation": round(correlation, 3),
        "tracking_error_pct": round(tracking_error * 100, 2),
    }


def compute_long_term_score(
    nav_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    valuation: ValuationSnapshot | None,
    weights: LongTermWeights | None = None,
) -> HorizonScore:
    if valuation is None:
        return HorizonScore(None, None, issues=["valuation_missing"])
    if not valuation.available or valuation.percentile is None:
        issues = list(valuation.issues) or ["valuation_unavailable"]
        return HorizonScore(None, None, issues=issues)

    benchmark = value_series(benchmark_df)
    if len(benchmark) < 253:
        return HorizonScore(None, None, issues=["long_term_history_insufficient"])
    tracking_score, tracking_metrics = _tracking_factor(nav_df, benchmark_df)
    if tracking_score is None:
        return HorizonScore(None, None, issues=["tracking_history_insufficient"])

    configured = weights or LongTermWeights()
    valuation_score = clamp_score((1 - valuation.percentile) * 100)
    trend_score, trend_metrics = _trend_factor(benchmark)
    risk_score, risk_metrics = _risk_factor(benchmark)
    factors = {
        "valuation": valuation_score,
        "trend": trend_score,
        "risk": risk_score,
        "tracking": tracking_score,
    }
    score = clamp_score(
        valuation_score * configured.valuation
        + trend_score * configured.trend
        + risk_score * configured.risk
        + tracking_score * configured.tracking
    )
    metrics: dict[str, float | str | None] = {
        "valuation_metric": valuation.metric,
        "valuation_value": valuation.value,
        "valuation_percentile_pct": round(valuation.percentile * 100, 1),
        "valuation_date": valuation.data_date,
        "valuation_source": valuation.source,
        "valuation_cache_status": valuation.cache_status,
        "valuation_sample_count": float(valuation.sample_count),
        **trend_metrics,
        **risk_metrics,
        **tracking_metrics,
    }
    return HorizonScore(score, score_level(score), factors, metrics, [])
