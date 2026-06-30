from datetime import date, timedelta

import pandas as pd

from src.agents.tools import tool_refresh_valuation_data, tool_score_fund
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
from src.db import get_conn, init_db
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
    dates = [(today - timedelta(days=offset)).isoformat() for offset in range(299, -1, -1)]
    nav = pd.DataFrame(
        {
            "trade_date": dates,
            "unit_nav": [1 + i / 1000 for i in range(300)],
            "acc_nav": [1 + i / 1000 for i in range(300)],
            "daily_pct": [0.1] * 300,
        }
    )
    save_nav(cfg.db_path, "000001", nav)
    holdings = pd.DataFrame(
        [{"report_date": today.isoformat(), "stock_code": "600000", "stock_name": "测试", "pct": 5.0}]
    )
    save_holdings(cfg.db_path, "000001", holdings)
    market = pd.DataFrame(
        {"trade_date": dates, "close": [3000 + i for i in range(300)], "daily_pct": [0.1] * 300}
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
    assert result["timing"]["score"] is not None
    assert result["long_term"]["score"] is None
    assert result["quality"]["inputs"]["event"]["status"] == "failed"
    assert result["scoring_version"] == cfg.scoring.version


def test_event_analysis_does_not_change_dual_scores(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    _seed(cfg)
    monkeypatch.setattr(
        "src.agents.tools.compute_event_score",
        lambda *args, **kwargs: EventScore(5.0, "低事件分", [], status="ok"),
    )
    first = tool_score_fund(cfg, cfg.funds[0])
    monkeypatch.setattr(
        "src.agents.tools.compute_event_score",
        lambda *args, **kwargs: EventScore(95.0, "高事件分", [], status="ok"),
    )
    second = tool_score_fund(cfg, cfg.funds[0])

    assert first["timing"]["score"] == second["timing"]["score"]
    assert first["long_term"]["score"] == second["long_term"]["score"]


def test_missing_valuation_keeps_qdii_timing_score(tmp_path, monkeypatch):
    fund = FundConfig("000001", "纳指测试基金", "qdii_index")
    cfg = _config(tmp_path)
    cfg.funds = [fund]
    _seed(cfg)
    with get_conn(cfg.db_path) as conn:
        hs300 = pd.read_sql(
            "SELECT trade_date, close, daily_pct FROM market_data WHERE symbol='HS300'",
            conn,
        )
    save_market(cfg.db_path, "NDX", hs300)
    fx = hs300.copy()
    fx["close"] = 7.0
    save_market(cfg.db_path, "USDCNY", fx)
    monkeypatch.setattr(
        "src.agents.tools.compute_event_score",
        lambda *args, **kwargs: EventScore(50.0, "无重大事件", [], status="ok"),
    )

    result = tool_score_fund(cfg, fund)

    assert result["long_term"]["score"] is None
    assert result["timing"]["score"] is not None
    assert result["quality"]["inputs"]["ndx_valuation"]["status"] == "missing"


def test_valuation_refresh_is_shared_by_qdii_funds(tmp_path):
    cfg = _config(tmp_path)
    cfg.funds = [
        FundConfig("000001", "QDII A", "qdii_index"),
        FundConfig("000002", "QDII B", "qdii_index"),
    ]
    init_db(cfg.db_path)
    calls: list[int] = []
    history = [
        {"date": f"{year}-{month:02d}-28", "value": 18 + month / 10}
        for year in range(2021, 2026)
        for month in range(1, 13)
    ]

    def provider():
        calls.append(1)
        return {
            "updated": date.today().isoformat(),
            "current": {"forward": 24.0},
            "forward": history,
        }

    result = tool_refresh_valuation_data(cfg, provider=provider)

    assert calls == [1]
    assert result["NDX"]["available"] is True
