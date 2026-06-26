"""基金数据采集:净值历史、持仓 - 数据源:akshare"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import akshare as ak
import pandas as pd
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.db import get_conn


# ---------- 抓取 ----------

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def fetch_fund_nav_history(code: str) -> pd.DataFrame:
    """抓取基金全部历史净值。akshare 默认返回完整历史。
    返回列:trade_date, unit_nav, acc_nav, daily_pct
    """
    logger.info(f"[fund] 抓取净值 {code}")
    df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
    if df is None or df.empty:
        raise RuntimeError(f"基金 {code} 未返回净值数据")

    df = df.rename(columns={
        "净值日期": "trade_date",
        "单位净值": "unit_nav",
        "日增长率": "daily_pct",
    })
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
    df["unit_nav"] = pd.to_numeric(df["unit_nav"], errors="coerce")
    df["daily_pct"] = pd.to_numeric(df["daily_pct"], errors="coerce")

    # 累计净值另抓
    try:
        df_acc = ak.fund_open_fund_info_em(symbol=code, indicator="累计净值走势")
        df_acc = df_acc.rename(columns={"净值日期": "trade_date", "累计净值": "acc_nav"})
        df_acc["trade_date"] = pd.to_datetime(df_acc["trade_date"]).dt.strftime("%Y-%m-%d")
        df_acc["acc_nav"] = pd.to_numeric(df_acc["acc_nav"], errors="coerce")
        df = df.merge(df_acc[["trade_date", "acc_nav"]], on="trade_date", how="left")
    except Exception as e:
        logger.warning(f"[fund] {code} 累计净值抓取失败,跳过: {e}")
        df["acc_nav"] = None

    return df[["trade_date", "unit_nav", "acc_nav", "daily_pct"]].dropna(subset=["unit_nav"])


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def fetch_fund_holdings(code: str, year: int | None = None) -> pd.DataFrame:
    """抓取基金前十大重仓股(最新季报)
    返回列:report_date, stock_code, stock_name, pct
    """
    logger.info(f"[fund] 抓取持仓 {code}")
    if year is None:
        year = date.today().year

    try:
        df = ak.fund_portfolio_hold_em(symbol=code, date=str(year))
    except Exception:
        df = ak.fund_portfolio_hold_em(symbol=code, date=str(year - 1))

    if df is None or df.empty:
        return pd.DataFrame(columns=["report_date", "stock_code", "stock_name", "pct"])

    df = df.rename(columns={
        "股票代码": "stock_code",
        "股票名称": "stock_name",
        "占净值比例": "pct",
        "季度": "report_date",
    })
    df["pct"] = pd.to_numeric(df["pct"], errors="coerce")

    # 取最近一期
    if "report_date" in df.columns:
        latest = df["report_date"].max()
        df = df[df["report_date"] == latest]

    return df[["report_date", "stock_code", "stock_name", "pct"]].head(10)


# ---------- 持久化 ----------

def save_nav(db_path: str | Path, code: str, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    with get_conn(db_path) as conn:
        rows = [
            (code, r.trade_date, r.unit_nav, r.acc_nav, r.daily_pct)
            for r in df.itertuples()
        ]
        conn.executemany(
            "INSERT OR REPLACE INTO fund_nav(code, trade_date, unit_nav, acc_nav, daily_pct) "
            "VALUES (?,?,?,?,?)",
            rows,
        )
    return len(rows)


def save_holdings(db_path: str | Path, code: str, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    with get_conn(db_path) as conn:
        # 清空旧持仓(只保留最新一期)
        conn.execute("DELETE FROM fund_holdings WHERE code = ?", (code,))
        rows = [
            (code, r.report_date, r.stock_code, r.stock_name, r.pct)
            for r in df.itertuples()
        ]
        conn.executemany(
            "INSERT OR REPLACE INTO fund_holdings(code, report_date, stock_code, stock_name, pct) "
            "VALUES (?,?,?,?,?)",
            rows,
        )
    return len(rows)


# ---------- 查询 ----------

def load_nav(db_path: str | Path, code: str, days: int = 365) -> pd.DataFrame:
    cutoff = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn(db_path) as conn:
        df = pd.read_sql(
            "SELECT trade_date, unit_nav, acc_nav, daily_pct FROM fund_nav "
            "WHERE code = ? AND trade_date >= ? ORDER BY trade_date ASC",
            conn,
            params=(code, cutoff),
        )
    return df


def load_holdings(db_path: str | Path, code: str) -> pd.DataFrame:
    with get_conn(db_path) as conn:
        df = pd.read_sql(
            "SELECT * FROM fund_holdings WHERE code = ? ORDER BY pct DESC",
            conn,
            params=(code,),
        )
    return df
