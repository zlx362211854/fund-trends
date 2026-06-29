"""从已有市场数据中提炼"事件卡"。
对 QDII 来说,昨夜美股 / 汇率 / 美元指数 比文本新闻更直接。
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

import pandas as pd

from src.config import FundType
from src.data.market import load_market


@dataclass
class MarketEvent:
    label: str           # 给 LLM 看的标题
    value: str           # 数值描述
    tone: str            # bullish / bearish / neutral
    detail: str = ""     # 可选补充


def _pct_tone(pct: float, threshold: float = 0.5) -> str:
    if pct >= threshold:
        return "bullish"
    if pct <= -threshold:
        return "bearish"
    return "neutral"


def _trend_metrics(values: pd.Series) -> tuple[float, float, float]:
    ma60 = float(values.rolling(60).mean().iloc[-1])
    ma200 = values.rolling(200).mean()
    distance = float(values.iloc[-1]) / ma60 - 1 if ma60 else 0.0
    slope = (
        float(ma200.iloc[-1]) / float(ma200.iloc[-21]) - 1
        if len(values) >= 220 and float(ma200.iloc[-21])
        else 0.0
    )
    expected_move = max(
        0.02,
        float(values.pct_change().iloc[-60:].std(ddof=0)) * math.sqrt(60),
    )
    return distance, distance / expected_move, slope


def _deviation_tone(deviation_z: float) -> str:
    if deviation_z >= 2.0:
        return "bearish"
    if deviation_z <= -2.0:
        return "bullish"
    return "neutral"


def build_market_events(db_path: str | Path, fund_type: FundType) -> list[MarketEvent]:
    events: list[MarketEvent] = []

    if fund_type == "qdii_index":
        # 1. 昨夜纳指
        ndx = load_market(db_path, "NDX", days=400)
        if not ndx.empty and len(ndx) >= 2:
            last = ndx.iloc[-1]
            pct = float(last["daily_pct"]) if pd.notna(last["daily_pct"]) else 0.0
            events.append(MarketEvent(
                label="昨夜纳斯达克",
                value=f"{last['close']:.2f}  {pct:+.2f}%",
                tone=_pct_tone(pct, 0.5),
                detail=f"日期 {last['trade_date']}",
            ))
            # 近5日累计
            recent = ndx.tail(5)
            cum = (recent["close"].iloc[-1] / recent["close"].iloc[0] - 1) * 100
            events.append(MarketEvent(
                label="纳指近5日累计",
                value=f"{cum:+.2f}%",
                tone=_pct_tone(cum, 2.0),
            ))
            if len(ndx) >= 220:
                distance, deviation_z, slope = _trend_metrics(ndx["close"])
                events.append(MarketEvent(
                    label="纳指趋势偏离",
                    value=f"距MA60 {distance*100:+.2f}%  标准化 {deviation_z:+.2f}",
                    tone=_deviation_tone(deviation_z),
                    detail=f"MA200 20日斜率 {slope*100:+.2f}%",
                ))

        # 2. 美元兑人民币
        fx = load_market(db_path, "USDCNY", days=400)
        if not fx.empty and len(fx) >= 2:
            last = fx.iloc[-1]
            pct = float(last["daily_pct"]) if pd.notna(last["daily_pct"]) else 0.0
            detail = f"日期 {last['trade_date']}"
            tone = _pct_tone(pct, 0.5)
            if len(fx) >= 220:
                distance, deviation_z, slope = _trend_metrics(fx["close"])
                tone = _deviation_tone(deviation_z)
                detail = (
                    f"距MA60 {distance*100:+.2f}%  标准化 {deviation_z:+.2f}  "
                    f"MA200 20日斜率 {slope*100:+.2f}%"
                )
            events.append(MarketEvent(
                label="USD/CNY趋势偏离",
                value=f"{last['close']:.4f}  日变 {pct:+.2f}%",
                tone=tone,
                detail=detail,
            ))

        return events

    # 国内基金:沪深300 状态
    idx = load_market(db_path, "HS300", days=400)
    if not idx.empty and len(idx) >= 2:
        last = idx.iloc[-1]
        pct = float(last["daily_pct"]) if pd.notna(last["daily_pct"]) else 0.0
        events.append(MarketEvent(
            label="沪深 300",
            value=f"{last['close']:.2f}  {pct:+.2f}%",
            tone=_pct_tone(pct, 0.5),
            detail=f"日期 {last['trade_date']}",
        ))
        if len(idx) >= 220:
            distance, deviation_z, slope = _trend_metrics(idx["close"])
            events.append(MarketEvent(
                label="沪深300趋势偏离",
                value=f"距MA60 {distance*100:+.2f}%  标准化 {deviation_z:+.2f}",
                tone=_deviation_tone(deviation_z),
                detail=f"MA200 20日斜率 {slope*100:+.2f}%",
            ))

    return events


def format_events_for_llm(events: list[MarketEvent]) -> str:
    if not events:
        return "(无结构化市场事件)"
    lines = []
    for e in events:
        flag = {"bullish": "📈", "bearish": "📉", "neutral": "·"}[e.tone]
        line = f"{flag} {e.label}: {e.value}"
        if e.detail:
            line += f"  ({e.detail})"
        lines.append(line)
    return "\n".join(lines)
