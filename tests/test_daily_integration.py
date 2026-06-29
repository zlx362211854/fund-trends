from datetime import date, timedelta

import pandas as pd

from src.agents.pipeline import run_analysis_agent
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
from src.report.daily import render_daily_report
from src.report.image import render_dashboard
from src.scoring.event import EventScore


def test_fixed_data_generates_observation_report_and_png(tmp_path, monkeypatch):
    fund = FundConfig("000001", "固定样本基金", "domestic_active")
    cfg = Config(
        funds=[fund],
        scoring=ScoringConfig(),
        quality=QualityConfig(),
        llm=LLMConfig("test", "key", "https://example.invalid", "fixed-model"),
        push=PushConfig("key"),
        schedule=ScheduleConfig(),
        db_path=tmp_path / "test.db",
        log_level="INFO",
        log_path=tmp_path / "test.log",
    )
    init_db(cfg.db_path)
    today = date.today()
    dates = [(today - timedelta(days=i)).isoformat() for i in range(249, -1, -1)]
    nav = pd.DataFrame(
        {
            "trade_date": dates,
            "unit_nav": [1.0 + i / 1000 for i in range(250)],
            "acc_nav": [1.0 + i / 1000 for i in range(250)],
            "daily_pct": [0.1] * 250,
        }
    )
    market = pd.DataFrame(
        {
            "trade_date": dates,
            "close": [3000 + i for i in range(250)],
            "daily_pct": [0.1] * 250,
        }
    )
    holdings = pd.DataFrame(
        [
            {
                "report_date": today.isoformat(),
                "stock_code": "600000",
                "stock_name": "固定样本",
                "pct": 5.0,
            }
        ]
    )
    save_nav(cfg.db_path, fund.code, nav)
    save_market(cfg.db_path, "HS300", market)
    save_holdings(cfg.db_path, fund.code, holdings)
    record_source_attempt(
        cfg.db_path, "news", "market", True, 0, today.isoformat()
    )
    monkeypatch.setattr(
        "src.agents.tools.compute_event_score",
        lambda *args, **kwargs: EventScore(
            50.0,
            "固定样本无重大事件",
            [],
            model="fixed-model",
            status="no_material_news",
        ),
    )

    results = run_analysis_agent(cfg)
    _, body = render_daily_report(results)
    output = tmp_path / "daily.png"
    render_dashboard(results, output)

    assert len(results) == 1
    assert "观察分" in body
    assert "数据可信度" in body
    assert output.stat().st_size > 10_000
