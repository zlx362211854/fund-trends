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

-- 数据源刷新审计状态
CREATE TABLE IF NOT EXISTS data_source_status (
    source           TEXT NOT NULL,
    subject          TEXT NOT NULL,
    last_attempt_at  TEXT NOT NULL,
    last_success_at  TEXT,
    row_count        INTEGER NOT NULL DEFAULT 0,
    latest_data_date TEXT,
    last_error       TEXT,
    PRIMARY KEY (source, subject)
);

-- 观察信号到期后的真实结果
CREATE TABLE IF NOT EXISTS signal_outcomes (
    code                 TEXT NOT NULL,
    signal_date          TEXT NOT NULL,
    scoring_version      TEXT NOT NULL,
    observation_level    TEXT NOT NULL,
    horizon_days         INTEGER NOT NULL,
    end_date             TEXT NOT NULL,
    fund_return_pct      REAL NOT NULL,
    benchmark_return_pct REAL NOT NULL,
    excess_return_pct    REAL NOT NULL,
    beat_benchmark       INTEGER NOT NULL,
    evaluated_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (code, signal_date, scoring_version, horizon_days)
);

CREATE INDEX IF NOT EXISTS idx_nav_date ON fund_nav(trade_date);
CREATE INDEX IF NOT EXISTS idx_market_date ON market_data(trade_date);
CREATE INDEX IF NOT EXISTS idx_news_publish ON news_cache(publish_at);
CREATE INDEX IF NOT EXISTS idx_scores_date ON daily_scores(score_date);
CREATE INDEX IF NOT EXISTS idx_outcomes_signal ON signal_outcomes(signal_date);
"""


DAILY_SCORE_COLUMNS = {
    "observation_level": "TEXT",
    "quality_status": "TEXT",
    "quality_json": "TEXT",
    "scoring_version": "TEXT",
}


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, declaration in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def init_db(db_path: str | Path) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        _ensure_columns(conn, "daily_scores", DAILY_SCORE_COLUMNS)
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
