"""供 Agent 调用的 tool 函数(纯 Python 函数,后续用 @function_tool 装饰)
说明:这里把对外的能力都封成幂等、易测的函数。
Agent 框架装饰只是个薄壳。
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from src.config import Config, FundConfig
from src.data.fund import (
    fetch_fund_holdings,
    fetch_fund_nav_history,
    load_holdings,
    load_nav,
    save_holdings,
    save_nav,
)
from src.data.market import (
    fetch_index_a,
    fetch_nasdaq,
    fetch_usdcny,
    load_market,
    save_market,
)
from src.data.keywords import keywords_for_fund
from src.data.market_events import build_market_events, format_events_for_llm
from src.data.news import (
    fetch_market_news,
    filter_news_by_keywords,
    load_recent_news,
    save_news,
)
from src.db import get_conn
from src.scoring.event import compute_event_score
from src.scoring.technical import compute_technical_score
from src.scoring.valuation import compute_valuation_score


# ============ Data Agent tools ============

def tool_refresh_fund_data(cfg: Config, code: str) -> dict:
    """抓取并保存单只基金最新净值和持仓。"""
    nav = fetch_fund_nav_history(code)
    n = save_nav(cfg.db_path, code, nav)
    holdings = fetch_fund_holdings(code)
    save_holdings(cfg.db_path, code, holdings)
    latest = nav.iloc[-1] if not nav.empty else None
    return {
        "code": code,
        "nav_rows_saved": n,
        "latest_date": latest["trade_date"] if latest is not None else None,
        "latest_nav": float(latest["unit_nav"]) if latest is not None else None,
    }


def tool_refresh_market_data(cfg: Config) -> dict:
    out: dict[str, Any] = {}
    for sym, fetcher in [
        ("NDX", fetch_nasdaq),
        ("USDCNY", fetch_usdcny),
        ("HS300", lambda: fetch_index_a("sh000300")),
    ]:
        try:
            df = fetcher()
            n = save_market(cfg.db_path, sym, df)
            out[sym] = {"rows": n, "latest": float(df["close"].iloc[-1])}
        except Exception as e:
            logger.error(f"[market] {sym} 失败: {e}")
            out[sym] = {"error": str(e)}
    return out


def tool_refresh_news(cfg: Config, limit: int = 100) -> dict:
    df = fetch_market_news(limit=limit)
    n = save_news(cfg.db_path, df)
    return {"fetched": len(df), "newly_saved": n}


# ============ Analysis Agent tools ============

def tool_score_fund(cfg: Config, fund: FundConfig) -> dict:
    """对单只基金完整打分。"""
    nav_df = load_nav(cfg.db_path, fund.code, days=1100)  # ~3 年
    holdings = load_holdings(cfg.db_path, fund.code)

    ndx_df = load_market(cfg.db_path, "NDX", days=400)
    fx_df = load_market(cfg.db_path, "USDCNY", days=400)
    idx_df = load_market(cfg.db_path, "HS300", days=400)

    tech = compute_technical_score(nav_df)
    val = compute_valuation_score(
        fund_type=fund.type,
        nav_df=nav_df,
        nasdaq_df=ndx_df,
        fx_df=fx_df,
        index_df=idx_df,
    )

    # 新闻按 fund_type 关键词包筛选
    news = load_recent_news(cfg.db_path, hours=48)
    holdings_names = holdings["stock_name"].tolist() if not holdings.empty else []
    kws = keywords_for_fund(fund.type, fund.name, holdings_names)
    related = filter_news_by_keywords(news, kws)

    # 结构化市场事件(对 QDII 尤其重要)
    market_events = build_market_events(cfg.db_path, fund.type)
    events_str = format_events_for_llm(market_events)

    event = compute_event_score(
        cfg.llm, fund.name, fund.type, holdings, related, events_str
    )

    w = cfg.scoring.weights
    total = tech.score * w.technical + val.score * w.valuation + event.score * w.event

    th = cfg.scoring.thresholds
    if total >= th.strong_buy:
        rec = "strong_buy"
    elif total >= th.buy:
        rec = "buy"
    elif total >= th.neutral:
        rec = "neutral"
    elif total >= th.avoid:
        rec = "watch"
    else:
        rec = "avoid"

    result = {
        "code": fund.code,
        "name": fund.name,
        "type": fund.type,
        "score_date": date.today().isoformat(),
        "technical": {**asdict(tech)},
        "valuation": {**asdict(val)},
        "event": {**asdict(event)},
        "total_score": round(total, 1),
        "recommendation": rec,
        "related_news_count": len(related),
        "market_events": events_str,
    }
    _persist_score(cfg, result)
    return result


def _persist_score(cfg: Config, r: dict) -> None:
    with get_conn(cfg.db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO daily_scores"
            "(code, score_date, technical_score, valuation_score, event_score, "
            " total_score, recommendation, reason, raw_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                r["code"],
                r["score_date"],
                r["technical"]["score"],
                r["valuation"]["score"],
                r["event"]["score"],
                r["total_score"],
                r["recommendation"],
                r["event"].get("reason", ""),
                json.dumps(r, ensure_ascii=False),
            ),
        )


def tool_load_recent_scores(cfg: Config, code: str, days: int = 7) -> list[dict]:
    with get_conn(cfg.db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM daily_scores WHERE code = ? "
            "AND score_date >= date('now', ?) ORDER BY score_date ASC",
            (code, f"-{days} days"),
        ).fetchall()
    return [dict(r) for r in rows]
