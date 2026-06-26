"""从已有市场数据中提炼"事件卡"。
对 QDII 来说,昨夜美股 / 汇率 / 美元指数 比文本新闻更直接。
"""
from __future__ import annotations

from dataclasses import dataclass
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


def _quantile_tone(q: float) -> str:
    # q 是当前在历史中的分位(0-1),高分位 = 估值贵 = 偏 bearish
    if q >= 0.8:
        return "bearish"
    if q <= 0.2:
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
            # 近1年分位
            ndx_1y = ndx["close"].iloc[-min(250, len(ndx)):]
            q = (ndx_1y <= ndx_1y.iloc[-1]).mean()
            events.append(MarketEvent(
                label="纳指 1 年分位",
                value=f"{q*100:.0f}%",
                tone=_quantile_tone(q),
                detail="分位越高 = 越接近 1 年高点",
            ))

        # 2. 美元兑人民币
        fx = load_market(db_path, "USDCNY", days=400)
        if not fx.empty and len(fx) >= 2:
            last = fx.iloc[-1]
            pct = float(last["daily_pct"]) if pd.notna(last["daily_pct"]) else 0.0
            # 对买 QDII 来说:汇率上升(人民币贬值)= 持有 QDII 的人民币计价收益偏利好
            # 但同时:汇率高位入场可能面临汇率回调
            fx_1y = fx["close"].iloc[-min(250, len(fx)):]
            q = (fx_1y <= last["close"]).mean()
            tone = "bearish" if q >= 0.8 else ("bullish" if q <= 0.2 else "neutral")
            events.append(MarketEvent(
                label="USD/CNY",
                value=f"{last['close']:.4f}  日变 {pct:+.2f}%",
                tone=tone,
                detail=f"1 年分位 {q*100:.0f}%(高位入场不利)",
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
        idx_1y = idx["close"].iloc[-min(250, len(idx)):]
        q = (idx_1y <= last["close"]).mean()
        events.append(MarketEvent(
            label="沪深 300 一年分位",
            value=f"{q*100:.0f}%",
            tone=_quantile_tone(q),
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
