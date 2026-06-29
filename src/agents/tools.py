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
from src.data.index_valuation import (
    fetch_ndx_forward_pe,
    refresh_index_valuation,
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
from src.data.status import load_source_status, record_source_attempt
from src.db import get_conn
from src.quality import assess_quality, compose_observation
from src.scoring.event import compute_event_score
from src.scoring.technical import compute_technical_score
from src.scoring.valuation import compute_valuation_score


# ============ Data Agent tools ============

def tool_refresh_fund_data(cfg: Config, code: str) -> dict:
    """抓取并保存单只基金最新净值和持仓。"""
    try:
        nav = fetch_fund_nav_history(code)
        n = save_nav(cfg.db_path, code, nav)
        latest_nav_date = str(nav["trade_date"].iloc[-1]) if not nav.empty else None
        record_source_attempt(
            cfg.db_path, "fund_nav", code, not nav.empty, n, latest_nav_date,
            None if not nav.empty else "no NAV data returned",
        )
    except Exception as exc:
        record_source_attempt(
            cfg.db_path, "fund_nav", code, False, error=str(exc)
        )
        raise

    holdings = fetch_fund_holdings(code)
    holdings_count = save_holdings(cfg.db_path, code, holdings)
    holdings_date = (
        str(holdings["report_date"].max()) if not holdings.empty else None
    )
    record_source_attempt(
        cfg.db_path,
        "fund_holdings",
        code,
        not holdings.empty,
        holdings_count,
        holdings_date,
        None if not holdings.empty else "no holdings data returned",
    )
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
            latest_date = str(df["trade_date"].iloc[-1]) if not df.empty else None
            record_source_attempt(
                cfg.db_path, "market", sym, not df.empty, n, latest_date,
                None if not df.empty else "no market data returned",
            )
            out[sym] = {"rows": n, "latest": float(df["close"].iloc[-1])}
        except Exception as e:
            logger.error(f"[market] {sym} 失败: {e}")
            record_source_attempt(
                cfg.db_path, "market", sym, False, error=str(e)
            )
            out[sym] = {"error": str(e)}
    return out


def tool_refresh_news(cfg: Config, limit: int = 100) -> dict:
    try:
        df = fetch_market_news(limit=limit)
        n = save_news(cfg.db_path, df)
        latest = str(df["publish_at"].max()) if not df.empty else date.today().isoformat()
        record_source_attempt(
            cfg.db_path, "news", "market", True, len(df), latest
        )
        return {"fetched": len(df), "newly_saved": n}
    except Exception as exc:
        record_source_attempt(
            cfg.db_path, "news", "market", False, error=str(exc)
        )
        raise


def tool_refresh_valuation_data(cfg: Config, provider=None) -> dict:
    """Refresh each required benchmark valuation at most once per day."""
    required = {"NDX" for fund in cfg.funds if fund.type == "qdii_index"}
    out: dict[str, Any] = {}
    for benchmark_code in sorted(required):
        snapshot = refresh_index_valuation(
            cfg.db_path,
            benchmark_code,
            provider=provider or fetch_ndx_forward_pe,
            max_age_days=cfg.scoring.max_valuation_age_days,
            min_samples=cfg.scoring.min_valuation_samples,
        )
        out[benchmark_code] = asdict(snapshot)
    return out


# ============ Analysis Agent tools ============

def tool_score_fund(cfg: Config, fund: FundConfig) -> dict:
    """对单只基金完整打分。"""
    nav_df = load_nav(cfg.db_path, fund.code, days=1100)  # ~3 年
    holdings = load_holdings(cfg.db_path, fund.code)

    ndx_df = load_market(cfg.db_path, "NDX", days=400)
    fx_df = load_market(cfg.db_path, "USDCNY", days=400)
    idx_df = load_market(cfg.db_path, "HS300", days=400)

    nav_date = str(nav_df["trade_date"].iloc[-1]) if not nav_df.empty else None
    holdings_date = (
        str(holdings["report_date"].max()) if not holdings.empty else None
    )
    if fund.type == "qdii_index":
        market_dates = [
            str(frame["trade_date"].iloc[-1])
            for frame in (ndx_df, fx_df)
            if not frame.empty
        ]
        market_date = min(market_dates) if len(market_dates) == 2 else None
    else:
        market_date = str(idx_df["trade_date"].iloc[-1]) if not idx_df.empty else None
    news_status = load_source_status(cfg.db_path, "news", "market")
    news_refresh_date = news_status["last_success_at"] if news_status else None

    preliminary_quality = assess_quality(
        as_of=date.today(),
        nav_rows=len(nav_df),
        nav_date=nav_date,
        market_date=market_date,
        holdings_date=holdings_date,
        news_refresh_date=news_refresh_date,
        event_available=True,
        config=cfg.quality,
    )
    if preliminary_quality.status == "unscorable":
        return {
            "code": fund.code,
            "name": fund.name,
            "type": fund.type,
            "score_date": date.today().isoformat(),
            "technical": None,
            "valuation": None,
            "event": None,
            "observation": {
                "score": None,
                "level": None,
                "used_dimensions": [],
            },
            "total_score": None,
            "observation_level": None,
            "quality": asdict(preliminary_quality),
            "scoring_version": cfg.scoring.version,
            "related_news_count": 0,
            "market_events": "",
        }

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
    events_str = format_events_for_llm(market_events) if market_events else ""

    event = compute_event_score(
        cfg.llm, fund.name, fund.type, holdings, related, events_str
    )

    quality = assess_quality(
        as_of=date.today(),
        nav_rows=len(nav_df),
        nav_date=nav_date,
        market_date=market_date,
        holdings_date=holdings_date,
        news_refresh_date=news_refresh_date,
        event_available=event.available,
        config=cfg.quality,
        valuation_fallback=val.method == "fallback_nav_quantile",
    )
    observation = compose_observation(
        {
            "technical": tech.score,
            "valuation": val.score,
            "event": event.score if event.available else None,
        },
        cfg.scoring.weights,
        cfg.scoring.thresholds,
    )

    result = {
        "code": fund.code,
        "name": fund.name,
        "type": fund.type,
        "score_date": date.today().isoformat(),
        "technical": {**asdict(tech)},
        "valuation": {**asdict(val)},
        "event": {**asdict(event)},
        "observation": asdict(observation),
        "total_score": observation.score,
        "observation_level": observation.level,
        "recommendation": observation.level,
        "quality": asdict(quality),
        "scoring_version": cfg.scoring.version,
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
            " total_score, recommendation, reason, raw_json, observation_level, "
            " quality_status, quality_json, scoring_version) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                r["observation_level"],
                r["quality"]["status"],
                json.dumps(r["quality"], ensure_ascii=False),
                r["scoring_version"],
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
