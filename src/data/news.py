"""新闻抓取 + 行业关键词预筛选"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

import akshare as ak
import pandas as pd
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.db import get_conn


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def fetch_market_news(limit: int = 100) -> pd.DataFrame:
    """抓取财经快讯。akshare 东方财富新闻接口。
    返回列:source, title, content, url, publish_at
    """
    logger.info(f"[news] 抓取财经快讯 (limit={limit})")
    try:
        df = ak.stock_news_em(symbol="财经")
    except Exception:
        # 兜底:东财全局快讯
        df = ak.stock_info_global_em()

    if df is None or df.empty:
        return pd.DataFrame(columns=["source", "title", "content", "url", "publish_at"])

    # 字段名因 akshare 版本不同有差异,做兼容映射
    col_map = {
        "新闻标题": "title", "标题": "title",
        "新闻内容": "content", "内容": "content", "摘要": "content",
        "新闻链接": "url", "链接": "url",
        "发布时间": "publish_at", "时间": "publish_at",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    if "source" not in df.columns:
        df["source"] = "eastmoney"
    if "content" not in df.columns:
        df["content"] = ""
    if "url" not in df.columns:
        df["url"] = ""
    if "publish_at" not in df.columns:
        df["publish_at"] = datetime.now().isoformat()

    df["publish_at"] = pd.to_datetime(df["publish_at"], errors="coerce").astype(str)
    return df[["source", "title", "content", "url", "publish_at"]].head(limit)


def save_news(db_path: str | Path, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    with get_conn(db_path) as conn:
        rows = [
            (r.source, r.title, r.content, r.url, r.publish_at)
            for r in df.itertuples()
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO news_cache(source, title, content, url, publish_at) "
            "VALUES (?,?,?,?,?)",
            rows,
        )
        return conn.total_changes


def load_recent_news(db_path: str | Path, hours: int = 24) -> pd.DataFrame:
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    with get_conn(db_path) as conn:
        df = pd.read_sql(
            "SELECT source, title, content, url, publish_at FROM news_cache "
            "WHERE publish_at >= ? ORDER BY publish_at DESC",
            conn,
            params=(cutoff,),
        )
    return df


def filter_news_by_keywords(news_df: pd.DataFrame, keywords: list[str]) -> pd.DataFrame:
    """根据持仓行业关键词筛选新闻"""
    if news_df.empty or not keywords:
        return news_df
    pattern = "|".join(re.escape(k) for k in keywords)
    mask = (
        news_df["title"].str.contains(pattern, na=False, regex=True)
        | news_df["content"].str.contains(pattern, na=False, regex=True)
    )
    return news_df[mask].reset_index(drop=True)
