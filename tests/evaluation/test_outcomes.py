from datetime import date, timedelta

import pandas as pd

from src.config import (
    Config,
    FundConfig,
    LLMConfig,
    PushConfig,
    QualityConfig,
    ScheduleConfig,
    ScoringConfig,
)
from src.data.fund import save_nav
from src.data.market import save_market
from src.db import get_conn, init_db
from src.evaluation.outcomes import (
    interval_return,
    load_outcome_summary,
    qdii_benchmark_return,
    update_mature_outcomes,
)


def test_interval_return_uses_horizon_trading_row():
    values = pd.DataFrame(
        {
            "trade_date": ["2026-01-01", "2026-01-02", "2026-01-05"],
            "value": [100, 105, 110],
        }
    )
    assert interval_return(values, "2026-01-01", 2) == ("2026-01-05", 10.0)


def test_qdii_benchmark_combines_index_and_fx():
    assert qdii_benchmark_return(100, 110, 7.0, 7.07) == 11.1


def _config(tmp_path):
    return Config(
        funds=[FundConfig("000001", "测试基金", "domestic_active")],
        scoring=ScoringConfig(),
        quality=QualityConfig(),
        llm=LLMConfig("test", "key", "https://example.invalid", "test"),
        push=PushConfig("key"),
        schedule=ScheduleConfig(),
        db_path=tmp_path / "test.db",
        log_level="INFO",
        log_path=tmp_path / "test.log",
    )


def test_update_mature_domestic_outcome_and_summary(tmp_path):
    cfg = _config(tmp_path)
    init_db(cfg.db_path)
    start = date(2026, 1, 1)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(70)]
    nav = pd.DataFrame(
        {
            "trade_date": dates,
            "unit_nav": [100 + i for i in range(70)],
            "acc_nav": [100 + i for i in range(70)],
            "daily_pct": [1.0] * 70,
        }
    )
    market = pd.DataFrame(
        {
            "trade_date": dates,
            "close": [100 + i / 2 for i in range(70)],
            "daily_pct": [0.5] * 70,
        }
    )
    save_nav(cfg.db_path, "000001", nav)
    save_market(cfg.db_path, "HS300", market)
    with get_conn(cfg.db_path) as conn:
        conn.execute(
            """
            INSERT INTO daily_scores(
                code, score_date, total_score, recommendation,
                observation_level, quality_status, scoring_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "000001",
                dates[0],
                75.0,
                "attention",
                "attention",
                "reliable",
                "observation-v1",
            ),
        )

    assert update_mature_outcomes(cfg, as_of=date(2026, 3, 31)) == 3
    summary = load_outcome_summary(cfg)
    assert {item["horizon_days"] for item in summary} == {5, 20, 60}
    assert all(item["sample_count"] == 1 for item in summary)
    assert all(item["evidence_sufficient"] is False for item in summary)
