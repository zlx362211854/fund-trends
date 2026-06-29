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
    load_valuation_snapshot,
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
from src.quality import age_days, compose_v2_quality
from src.scoring.event import compute_event_score
from src.scoring.common import HorizonScore
from src.scoring.long_term import compute_long_term_score
from src.scoring.timing import compute_timing_score


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

def _latest_date(frame: pd.DataFrame) -> str | None:
    if frame.empty or "trade_date" not in frame:
        return None
    return str(frame["trade_date"].iloc[-1])


def _dated_input(
    data_date: str | None,
    max_age_days: int,
    issue_prefix: str,
    *,
    failed: bool = False,
) -> dict:
    if not data_date:
        return {
            "status": "failed" if failed else "missing",
            "date": None,
            "issue": f"{issue_prefix}_{'failed' if failed else 'missing'}",
        }
    age = age_days(data_date, date.today())
    if age is None:
        return {"status": "failed", "date": data_date, "issue": f"{issue_prefix}_failed"}
    if age > max_age_days:
        return {"status": "stale", "date": data_date, "issue": f"{issue_prefix}_stale"}
    return {"status": "ok", "date": data_date}


def _build_benchmark(
    fund_type: str,
    ndx_df: pd.DataFrame,
    fx_df: pd.DataFrame,
    index_df: pd.DataFrame,
) -> pd.DataFrame:
    if fund_type != "qdii_index":
        return index_df.copy()
    if ndx_df.empty or fx_df.empty:
        return pd.DataFrame(columns=["trade_date", "close", "daily_pct"])
    ndx = ndx_df[["trade_date", "close"]].rename(columns={"close": "index_close"})
    fx = fx_df[["trade_date", "close"]].rename(columns={"close": "fx_close"})
    benchmark = ndx.merge(fx, on="trade_date", how="inner")
    benchmark["close"] = (
        pd.to_numeric(benchmark["index_close"], errors="coerce")
        * pd.to_numeric(benchmark["fx_close"], errors="coerce")
    )
    benchmark["daily_pct"] = benchmark["close"].pct_change() * 100
    return benchmark[["trade_date", "close", "daily_pct"]].dropna(
        subset=["close"]
    )

def tool_score_fund(cfg: Config, fund: FundConfig) -> dict:
    """Calculate independent long-term and timing observation scores."""
    nav_df = load_nav(cfg.db_path, fund.code, days=1100)  # ~3 年
    holdings = load_holdings(cfg.db_path, fund.code)

    ndx_df = load_market(cfg.db_path, "NDX", days=1100)
    fx_df = load_market(cfg.db_path, "USDCNY", days=1100)
    idx_df = load_market(cfg.db_path, "HS300", days=1100)
    benchmark_df = _build_benchmark(fund.type, ndx_df, fx_df, idx_df)

    nav_date = _latest_date(nav_df)
    holdings_date = (
        str(holdings["report_date"].max()) if not holdings.empty else None
    )
    news_status = load_source_status(cfg.db_path, "news", "market")
    news_refresh_date = news_status["last_success_at"] if news_status else None

    timing_input = benchmark_df if fund.type != "domestic_active" else nav_df
    timing = compute_timing_score(timing_input, cfg.scoring.timing_weights)
    if fund.type == "qdii_index":
        valuation = load_valuation_snapshot(
            cfg.db_path,
            "NDX",
            "forward_pe",
            max_age_days=cfg.scoring.max_valuation_age_days,
            min_samples=cfg.scoring.min_valuation_samples,
        )
        long_term = compute_long_term_score(
            nav_df,
            benchmark_df,
            valuation,
            cfg.scoring.long_term_weights,
        )
    elif fund.type == "domestic_index":
        valuation = None
        long_term = compute_long_term_score(
            nav_df,
            benchmark_df,
            valuation,
            cfg.scoring.long_term_weights,
        )
    else:
        valuation = None
        long_term = HorizonScore(
            None, None, issues=["active_fundamentals_unavailable"]
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

    inputs = {
        "nav": _dated_input(nav_date, cfg.quality.max_nav_age_days, "nav"),
        "holdings": _dated_input(
            holdings_date, cfg.quality.max_holdings_age_days, "holdings"
        ),
        "news": _dated_input(
            news_refresh_date,
            cfg.quality.max_news_refresh_age_days,
            "news_refresh",
            failed=bool(news_status and news_status.get("last_error")),
        ),
        "event": {
            "status": "ok" if event.available else "failed",
            "date": event.generated_at,
            **({} if event.available else {"issue": "event_unavailable"}),
        },
    }
    if fund.type == "qdii_index":
        inputs["ndx_market"] = _dated_input(
            _latest_date(ndx_df), cfg.quality.max_market_age_days, "ndx_market"
        )
        inputs["usdcny"] = _dated_input(
            _latest_date(fx_df), cfg.quality.max_market_age_days, "usdcny"
        )
        valuation_status = "missing"
        valuation_date = None
        valuation_issue = "valuation_missing"
        if valuation is not None:
            valuation_date = valuation.data_date
            valuation_status = {
                "fresh": "ok",
                "cached": "cached",
                "stale": "stale",
                "missing": "missing",
            }.get(valuation.cache_status, "failed")
            valuation_issue = valuation.issues[0] if valuation.issues else ""
        inputs["ndx_valuation"] = {
            "status": valuation_status,
            "date": valuation_date,
            **({"issue": valuation_issue} if valuation_issue else {}),
        }
    else:
        inputs["hs300_market"] = _dated_input(
            _latest_date(idx_df), cfg.quality.max_market_age_days, "hs300_market"
        )

    score_issues = [*long_term.issues, *timing.issues]
    quality = compose_v2_quality(
        inputs=inputs,
        long_term_available=long_term.score is not None,
        timing_available=timing.score is not None,
        score_issues=score_issues,
    )

    result = {
        "code": fund.code,
        "name": fund.name,
        "type": fund.type,
        "score_date": date.today().isoformat(),
        "long_term": asdict(long_term),
        "timing": asdict(timing),
        "event": {**asdict(event)},
        "quality": asdict(quality),
        "scoring_version": cfg.scoring.version,
        "related_news_count": len(related),
        "market_events": events_str,
    }
    _persist_score(cfg, result)
    return result


def _persist_score(cfg: Config, r: dict) -> None:
    legacy_score = r["timing"]["score"]
    if legacy_score is None:
        legacy_score = r["long_term"]["score"]
    if legacy_score is None:
        legacy_score = 0.0
    legacy_level = r["timing"]["level"] or r["long_term"]["level"] or "unscorable"
    valuation_factor = r["long_term"].get("factors", {}).get("valuation")
    with get_conn(cfg.db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO daily_scores"
            "(code, score_date, technical_score, valuation_score, event_score, "
            " total_score, recommendation, reason, raw_json, observation_level, "
            " quality_status, quality_json, scoring_version, long_term_score, "
            " long_term_level, long_term_json, timing_score, timing_level, timing_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                r["code"],
                r["score_date"],
                r["timing"]["score"],
                valuation_factor,
                r["event"]["score"],
                legacy_score,
                legacy_level,
                r["event"].get("reason", ""),
                json.dumps(r, ensure_ascii=False),
                legacy_level,
                r["quality"]["status"],
                json.dumps(r["quality"], ensure_ascii=False),
                r["scoring_version"],
                r["long_term"]["score"],
                r["long_term"]["level"],
                json.dumps(r["long_term"], ensure_ascii=False),
                r["timing"]["score"],
                r["timing"]["level"],
                json.dumps(r["timing"], ensure_ascii=False),
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
