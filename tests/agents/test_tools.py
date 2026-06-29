from datetime import date, timedelta

import pandas as pd

from src.agents.tools import tool_score_fund
from src.config import (
    Config,
    FundConfig,
    LLMConfig,
    PushConfig,
    QualityConfig,
    ScheduleConfig,
    ScoringConfig,
)
from src.data.fund import save_holdings, save_nav
from src.data.market import save_market
from src.data.status import record_source_attempt
from src.db import init_db
from src.scoring.event import EventScore


def _config(tmp_path):
    fund = FundConfig("000001", "测试基金", "domestic_active")
    return Config(
        funds=[fund],
        scoring=ScoringConfig(),
        quality=QualityConfig(),
        llm=LLMConfig("test", "key", "https://example.invalid", "test-model"),
        push=PushConfig("key"),
        schedule=ScheduleConfig(),
        db_path=tmp_path / "test.db",
        log_level="INFO",
        log_path=tmp_path / "test.log",
    )


def _seed(cfg):
    init_db(cfg.db_path)
    today = date.today()
    dates = [(today - timedelta(days=offset)).isoformat() for offset in range(119, -1, -1)]
    nav = pd.DataFrame(
        {
            "trade_date": dates,
            "unit_nav": [1 + i / 1000 for i in range(120)],
            "acc_nav": [1 + i / 1000 for i in range(120)],
            "daily_pct": [0.1] * 120,
        }
    )
    save_nav(cfg.db_path, "000001", nav)
    holdings = pd.DataFrame(
        [{"report_date": today.isoformat(), "stock_code": "600000", "stock_name": "测试", "pct": 5.0}]
    )
    save_holdings(cfg.db_path, "000001", holdings)
    market = pd.DataFrame(
        {"trade_date": dates, "close": [3000 + i for i in range(120)], "daily_pct": [0.1] * 120}
    )
    save_market(cfg.db_path, "HS300", market)
    record_source_attempt(cfg.db_path, "news", "market", True, 0, today.isoformat())


def test_score_fund_marks_missing_event_as_degraded(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    _seed(cfg)
    monkeypatch.setattr(
        "src.agents.tools.compute_event_score",
        lambda *args, **kwargs: EventScore(
            None, "事件分析不可用", [], available=False, status="error"
        ),
    )

    result = tool_score_fund(cfg, cfg.funds[0])

    assert result["quality"]["status"] == "degraded"
    assert result["observation_level"] is not None
    assert "event" not in result["observation"]["used_dimensions"]
    assert result["scoring_version"] == "observation-v1"
