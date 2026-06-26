"""技术面打分:近1年分位 + MA60 距离 + 回撤 + RSI"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class TechnicalScore:
    score: float                    # 0-100
    quantile_1y: float              # 近1年分位 0-1
    ma60_dist_pct: float            # 距 MA60 的百分比距离
    drawdown_pct: float             # 当前回撤(负值)
    rsi_14: float                   # RSI(14)
    trend_filter_passed: bool       # 5日均线斜率是否转正
    raw_score: float                # 应用反转过滤前的分


def _rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff().dropna()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty and not np.isnan(rsi.iloc[-1]) else 50.0


def compute_technical_score(nav_df: pd.DataFrame) -> TechnicalScore:
    """nav_df 列:trade_date, unit_nav(按日期升序)
    至少需要 ~250 个交易日的数据。
    """
    if len(nav_df) < 60:
        return TechnicalScore(50.0, 0.5, 0.0, 0.0, 50.0, True, 50.0)

    nav = nav_df["unit_nav"].astype(float).reset_index(drop=True)
    current = nav.iloc[-1]

    # --- 1. 近1年分位数(越低越加分) ---
    nav_1y = nav.iloc[-min(250, len(nav)):]
    quantile = (nav_1y <= current).mean()       # 当前在历史中的分位
    score_quantile = (1 - quantile) * 100       # 低位 → 高分

    # --- 2. 距 MA60 距离(跌破均线加分) ---
    ma60 = nav.rolling(60).mean().iloc[-1]
    ma60_dist = (current - ma60) / ma60 if ma60 else 0.0
    # -10% → 100 分;0% → 50 分;+10% → 0 分
    score_ma60 = float(np.clip(50 - ma60_dist * 500, 0, 100))

    # --- 3. 当前回撤(从近 1 年高点) ---
    peak = nav_1y.max()
    drawdown = (current - peak) / peak if peak else 0.0
    # -30% → 100 分;0% → 0 分
    score_dd = float(np.clip(-drawdown / 0.3 * 100, 0, 100))

    # --- 4. RSI ---
    rsi = _rsi(nav, 14)
    # RSI<30 超卖 → 100;RSI>70 超买 → 0
    if rsi <= 30:
        score_rsi = 100.0
    elif rsi >= 70:
        score_rsi = 0.0
    else:
        score_rsi = (70 - rsi) / 40 * 100

    # 内部权重(归到 100 分):分位 37.5% + MA60 25% + 回撤 25% + RSI 12.5%
    raw = (
        score_quantile * 0.375
        + score_ma60 * 0.25
        + score_dd * 0.25
        + score_rsi * 0.125
    )

    # --- 反转过滤:5日均线斜率 ---
    ma5 = nav.rolling(5).mean()
    if len(ma5.dropna()) >= 3:
        slope_positive = ma5.iloc[-1] > ma5.iloc[-3]
    else:
        slope_positive = True
    score = raw if slope_positive else raw * 0.7

    return TechnicalScore(
        score=float(np.clip(score, 0, 100)),
        quantile_1y=float(quantile),
        ma60_dist_pct=float(ma60_dist * 100),
        drawdown_pct=float(drawdown * 100),
        rsi_14=float(rsi),
        trend_filter_passed=bool(slope_positive),
        raw_score=float(raw),
    )
