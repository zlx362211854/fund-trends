"""SQLite 初始化和连接管理"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
-- 基金净值历史
CREATE TABLE IF NOT EXISTS fund_nav (
    code        TEXT NOT NULL,
    trade_date  TEXT NOT NULL,        -- YYYY-MM-DD
    unit_nav    REAL NOT NULL,        -- 单位净值
    acc_nav     REAL,                 -- 累计净值
    daily_pct   REAL,                 -- 日涨跌幅 %
    PRIMARY KEY (code, trade_date)
);

-- 基金前十大持仓(季度)
CREATE TABLE IF NOT EXISTS fund_holdings (
    code         TEXT NOT NULL,
    report_date  TEXT NOT NULL,       -- 季报日期
    stock_code   TEXT NOT NULL,
    stock_name   TEXT NOT NULL,
    pct          REAL NOT NULL,       -- 占净值比例 %
    PRIMARY KEY (code, report_date, stock_code)
);

-- 指数 / 市场数据(纳指、汇率等)
CREATE TABLE IF NOT EXISTS market_data (
    symbol      TEXT NOT NULL,        -- 如 'NDX', 'USDCNY'
    trade_date  TEXT NOT NULL,
    close       REAL NOT NULL,
    daily_pct   REAL,
    PRIMARY KEY (symbol, trade_date)
);

-- 新闻缓存
CREATE TABLE IF NOT EXISTS news_cache (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    title       TEXT NOT NULL,
    content     TEXT,
    url         TEXT,
    publish_at  TEXT NOT NULL,        -- ISO 时间
    tags        TEXT,                 -- 逗号分隔关键词
    fetched_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source, title, publish_at)
);

-- 每日打分结果(供周报回顾、未来回测)
CREATE TABLE IF NOT EXISTS daily_scores (
    code            TEXT NOT NULL,
    score_date      TEXT NOT NULL,    -- 推送日期
    technical_score REAL,
    valuation_score REAL,
    event_score     REAL,
    total_score     REAL NOT NULL,
    recommendation  TEXT NOT NULL,    -- strong_buy / buy / neutral / avoid
    reason          TEXT,             -- LLM 生成的简要说明
    raw_json        TEXT,             -- 完整快照(便于复盘)
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (code, score_date)
);

-- 推送历史
CREATE TABLE IF NOT EXISTS push_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    push_type   TEXT NOT NULL,        -- daily / weekly
    push_date   TEXT NOT NULL,
    title       TEXT,
    content     TEXT,
    success     INTEGER NOT NULL,     -- 0 / 1
    error       TEXT,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_nav_date ON fund_nav(trade_date);
CREATE INDEX IF NOT EXISTS idx_market_date ON market_data(trade_date);
CREATE INDEX IF NOT EXISTS idx_news_publish ON news_cache(publish_at);
CREATE INDEX IF NOT EXISTS idx_scores_date ON daily_scores(score_date);
"""


def init_db(db_path: str | Path) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def get_conn(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
