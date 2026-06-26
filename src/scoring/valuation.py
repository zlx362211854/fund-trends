"""估值面打分。
不同基金类型用不同方法:
  domestic_active  -> 持仓股加权 PE 分位(MVP 阶段先用净值分位代理)
  domestic_index   -> 跟踪指数 PE 分位
  qdii_index       -> 纳指 PE 分位 + 汇率因子
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.config import FundType


@dataclass
class ValuationScore:
    score: float                    # 0-100
    method: str                     # 用了什么方法
    detail: dict                    # 关键中间值


def _quantile_score(series: pd.Series, current: float) -> float:
    """当前值在历史中越低 → 分数越高"""
    if len(series) < 30 or pd.isna(current):
        return 50.0
    q = (series <= current).mean()
    return float((1 - q) * 100)


def compute_valuation_score(
    fund_type: FundType,
    nav_df: pd.DataFrame,
    nasdaq_df: pd.DataFrame | None = None,
    fx_df: pd.DataFrame | None = None,
    index_df: pd.DataFrame | None = None,
) -> ValuationScore:
    # MVP 阶段:暂用净值历史分位代理估值
    # TODO: 接入持仓股 PE 加权(需要 akshare 实时股票 PE 接口)

    if fund_type == "qdii_index":
        # 纳指分位 + 汇率因子
        if nasdaq_df is None or nasdaq_df.empty:
            return ValuationScore(50.0, "fallback_nav_quantile", {})

        ndx = nasdaq_df["close"].astype(float)
        ndx_1y = ndx.iloc[-min(250, len(ndx)):]
        ndx_score = _quantile_score(ndx_1y, float(ndx.iloc[-1]))

        # 汇率因子:USD/CNY 高位时买纳指 QDII 不利(将来汇率回落会双重损失)
        fx_score = 50.0
        fx_now = None
        if fx_df is not None and not fx_df.empty:
            fx = fx_df["close"].astype(float)
            fx_now = float(fx.iloc[-1])
            fx_1y = fx.iloc[-min(250, len(fx)):]
            # 汇率高(USD/CNY 大)对买入 QDII 不利
            fx_q = (fx_1y <= fx_now).mean()
            fx_score = (1 - fx_q) * 100

        score = ndx_score * 0.7 + fx_score * 0.3
        return ValuationScore(
            score=float(np.clip(score, 0, 100)),
            method="nasdaq_quantile + fx_factor",
            detail={
                "ndx_score": ndx_score,
                "fx_score": fx_score,
                "fx_now": fx_now,
            },
        )

    if fund_type == "domestic_index":
        # 用跟踪指数(如沪深300)分位
        if index_df is not None and not index_df.empty:
            idx = index_df["close"].astype(float)
            idx_1y = idx.iloc[-min(250, len(idx)):]
            score = _quantile_score(idx_1y, float(idx.iloc[-1]))
            return ValuationScore(
                score=float(score),
                method="tracking_index_quantile",
                detail={"index_quantile_score": score},
            )

    # domestic_active 或 fallback:用基金净值近 3 年分位代理
    if not nav_df.empty:
        nav = nav_df["unit_nav"].astype(float)
        nav_3y = nav.iloc[-min(750, len(nav)):]
        score = _quantile_score(nav_3y, float(nav.iloc[-1]))
        return ValuationScore(
            score=float(score),
            method="nav_3y_quantile",
            detail={"nav_quantile_score": score},
        )

    return ValuationScore(50.0, "neutral_default", {})
