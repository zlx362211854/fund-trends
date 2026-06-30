"""市场数据:纳指、美元汇率、A股指数等"""
from __future__ import annotations

from datetime import date, timedelta
from io import StringIO
from pathlib import Path

import akshare as ak
import httpx
import pandas as pd
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.db import get_conn


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def fetch_nasdaq() -> pd.DataFrame:
    """Nasdaq-100 index history."""
    logger.info("[market] 抓取纳斯达克100指数")
    df = ak.index_us_stock_sina(symbol=".NDX")
    df = df.rename(columns={"date": "trade_date", "close": "close"})
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["daily_pct"] = df["close"].pct_change() * 100
    return df[["trade_date", "close", "daily_pct"]].dropna(subset=["close"])


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def fetch_usdcny() -> pd.DataFrame:
    """USD/CNY derived from official ECB EUR reference rates."""
    logger.info("[market] 抓取 ECB USD/CNY")
    start = (date.today() - timedelta(days=1460)).isoformat()
    response = httpx.get(
        "https://data-api.ecb.europa.eu/service/data/EXR/D.USD+CNY.EUR.SP00.A",
        params={"startPeriod": start, "format": "csvdata"},
        headers={"User-Agent": "fund-trends/observation-v2 (+research use)"},
        timeout=20.0,
        follow_redirects=True,
    )
    response.raise_for_status()
    raw = pd.read_csv(StringIO(response.text))
    required = {"CURRENCY", "TIME_PERIOD", "OBS_VALUE"}
    if not required.issubset(raw.columns):
        raise ValueError("ECB exchange-rate response is missing required columns")
    raw = raw[raw["CURRENCY"].isin(["USD", "CNY"])].copy()
    raw["OBS_VALUE"] = pd.to_numeric(raw["OBS_VALUE"], errors="coerce")
    pivot = raw.pivot_table(
        index="TIME_PERIOD", columns="CURRENCY", values="OBS_VALUE", aggfunc="last"
    ).dropna(subset=["USD", "CNY"])
    pivot = pivot[(pivot["USD"] > 0) & (pivot["CNY"] > 0)]
    if pivot.empty:
        raise ValueError("ECB exchange-rate response has no aligned USD/CNY rows")
    result = pivot.reset_index().rename(columns={"TIME_PERIOD": "trade_date"})
    result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.strftime(
        "%Y-%m-%d"
    )
    result["close"] = result["CNY"] / result["USD"]
    result = result.sort_values("trade_date")
    result["daily_pct"] = result["close"].pct_change() * 100
    return result[["trade_date", "close", "daily_pct"]]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def fetch_index_a(symbol: str = "sh000300") -> pd.DataFrame:
    """A股指数(默认沪深300)"""
    logger.info(f"[market] 抓取 A股指数 {symbol}")
    df = ak.stock_zh_index_daily(symbol=symbol)
    df = df.rename(columns={"date": "trade_date", "close": "close"})
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["daily_pct"] = df["close"].pct_change() * 100
    return df[["trade_date", "close", "daily_pct"]].dropna(subset=["close"])


def save_market(db_path: str | Path, symbol: str, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    with get_conn(db_path) as conn:
        rows = [(symbol, r.trade_date, r.close, r.daily_pct) for r in df.itertuples()]
        conn.executemany(
            "INSERT OR REPLACE INTO market_data(symbol, trade_date, close, daily_pct) "
            "VALUES (?,?,?,?)",
            rows,
        )
    return len(rows)


def load_market(db_path: str | Path, symbol: str, days: int = 365) -> pd.DataFrame:
    cutoff = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn(db_path) as conn:
        df = pd.read_sql(
            "SELECT trade_date, close, daily_pct FROM market_data "
            "WHERE symbol = ? AND trade_date >= ? ORDER BY trade_date ASC",
            conn,
            params=(symbol, cutoff),
        )
    return df
