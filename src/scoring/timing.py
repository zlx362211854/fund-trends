"""Current additional-investment timing score."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src.config import TimingWeights
from src.scoring.common import (
    HorizonScore,
    clamp_score,
    score_level,
    value_series,
)


def _rsi(values: pd.Series, period: int = 14) -> float:
    changes = values.diff().dropna()
    gains = changes.clip(lower=0).rolling(period).mean()
    losses = (-changes.clip(upper=0)).rolling(period).mean()
    if gains.empty or pd.isna(gains.iloc[-1]) or pd.isna(losses.iloc[-1]):
        return 50.0
    gain = float(gains.iloc[-1])
    loss = float(losses.iloc[-1])
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    relative_strength = gain / loss
    return float(100 - 100 / (1 + relative_strength))


def _temperature_score(rsi: float, return_20d: float) -> float:
    if rsi < 25:
        score = 40.0
    elif rsi < 35:
        score = 70.0
    elif rsi <= 60:
        score = 90.0
    elif rsi <= 70:
        score = 70.0
    elif rsi <= 80:
        score = 40.0
    else:
        score = 10.0
    if return_20d > 0.12:
        score -= min(40.0, (return_20d - 0.12) * 200)
    return clamp_score(score)


def compute_timing_score(
    nav_df: pd.DataFrame,
    weights: TimingWeights | None = None,
) -> HorizonScore:
    values = value_series(nav_df)
    if len(values) < 220:
        return HorizonScore(None, None, issues=["timing_history_insufficient"])

    configured = weights or TimingWeights()
    current = float(values.iloc[-1])
    ma20_series = values.rolling(20).mean()
    ma60 = float(values.rolling(60).mean().iloc[-1])
    ma200_series = values.rolling(200).mean()
    ma200 = float(ma200_series.iloc[-1])
    ma200_previous = float(ma200_series.iloc[-21])
    ma200_slope = ma200 / ma200_previous - 1 if ma200_previous else 0.0
    distance_ma60 = current / ma60 - 1 if ma60 else 0.0
    distance_ma200 = current / ma200 - 1 if ma200 else 0.0

    returns = values.pct_change().dropna()
    annualized_volatility = float(returns.iloc[-60:].std(ddof=0) * math.sqrt(252))
    expected_60d_move = max(0.02, annualized_volatility * math.sqrt(60 / 252))
    deviation_z = distance_ma60 / expected_60d_move

    slope_score = float(np.clip(50 + ma200_slope / 0.04 * 50, 0, 100))
    position_score = float(np.clip(50 + distance_ma200 / 0.12 * 50, 0, 100))
    trend_score = clamp_score(slope_score * 0.6 + position_score * 0.4)

    deviation_score = clamp_score(
        100 - max(0.0, abs(deviation_z) - 0.5) * 45
    )

    recent = values.iloc[-min(250, len(values)) :]
    peak = float(recent.max())
    drawdown = current / peak - 1 if peak else 0.0
    ma20_previous = float(ma20_series.iloc[-6])
    ma20_slope = (
        float(ma20_series.iloc[-1]) / ma20_previous - 1 if ma20_previous else 0.0
    )
    return_5d = current / float(values.iloc[-6]) - 1
    return_20d = current / float(values.iloc[-21]) - 1
    stabilized = ma20_slope >= -0.002 and return_5d >= -0.01
    if drawdown <= -0.03:
        depth = min(0.30, abs(drawdown))
        if stabilized:
            stabilization_score = clamp_score(55 + depth / 0.30 * 40)
        else:
            stabilization_score = clamp_score(35 - depth * 100)
    else:
        stabilization_score = 60.0 if stabilized else 35.0

    rsi = _rsi(values)
    temperature_score = _temperature_score(rsi, return_20d)
    factors = {
        "trend": trend_score,
        "deviation": deviation_score,
        "stabilization": stabilization_score,
        "temperature": temperature_score,
    }
    score = clamp_score(
        trend_score * configured.trend
        + deviation_score * configured.deviation
        + stabilization_score * configured.stabilization
        + temperature_score * configured.temperature
    )
    metrics: dict[str, float | str | None] = {
        "ma200_slope_pct": round(ma200_slope * 100, 2),
        "distance_ma60_pct": round(distance_ma60 * 100, 2),
        "distance_ma200_pct": round(distance_ma200 * 100, 2),
        "deviation_z": round(deviation_z, 2),
        "drawdown_pct": round(drawdown * 100, 2),
        "ma20_slope_pct": round(ma20_slope * 100, 2),
        "return_5d_pct": round(return_5d * 100, 2),
        "return_20d_pct": round(return_20d * 100, 2),
        "rsi_14": round(rsi, 1),
        "annualized_volatility_pct": round(annualized_volatility * 100, 2),
        "stabilized": "yes" if stabilized else "no",
    }
    return HorizonScore(score, score_level(score), factors, metrics, [])
