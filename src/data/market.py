"""市场数据:纳指、美元汇率、A股指数等"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import akshare as ak
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
    """美元兑人民币汇率"""
    logger.info("[market] 抓取 USD/CNY")
    df = ak.currency_boc_sina(symbol="美元")
    df = df.rename(columns={"日期": "trade_date", "中行汇买价": "close"})
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
    df["close"] = pd.to_numeric(df["close"], errors="coerce") / 100  # 中行报价 100 单位
    df["daily_pct"] = df["close"].pct_change() * 100
    return df[["trade_date", "close", "daily_pct"]].dropna(subset=["close"])


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
