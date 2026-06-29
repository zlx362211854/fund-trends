from src.report.daily import render_daily_report
from src.report.verdict import get_verdict
from src.report.weekly import render_weekly_report
from src.report.image import render_dashboard
from PIL import Image
from src.config import (
    Config,
    FundConfig,
    LLMConfig,
    PushConfig,
    QualityConfig,
    ScheduleConfig,
    ScoringConfig,
)
from src.db import get_conn, init_db
from datetime import date

FORBIDDEN = ("加仓", "梭哈", "闭眼买", "捡钱", "上车", "接盘")


def _sample_result():
    return {
        "code": "000001",
        "name": "测试基金",
        "type": "domestic_active",
        "total_score": 62.9,
        "observation_level": "neutral",
        "technical": {
            "score": 70.0,
            "quantile_1y": 0.35,
            "drawdown_pct": -8.0,
            "ma60_dist_pct": -2.0,
            "rsi_14": 45.0,
            "trend_filter_passed": True,
        },
        "valuation": {
            "score": 50.0,
            "method": "nav_3y_quantile",
            "detail": {},
        },
        "event": {
            "score": 55.0,
            "reason": "相关消息影响有限",
            "risks": ["样本仍少"],
            "available": True,
            "status": "ok",
            "model": "test-model",
            "evidence": [
                {
                    "type": "news",
                    "title": "测试新闻",
                    "url": "https://example.com/news",
                    "source": "test",
                    "publish_at": "2026-06-29",
                }
            ],
        },
        "quality": {
            "status": "reliable",
            "issues": [],
            "data_dates": {
                "nav": "2026-06-27",
                "market": "2026-06-27",
                "holdings": "2026-03-31",
                "news_refresh": "2026-06-29",
            },
        },
        "scoring_version": "observation-v1",
        "market_events": "",
    }


def test_daily_report_uses_observation_language():
    title, body = render_daily_report([_sample_result()])
    assert "观察分" in body
    assert "数据可信度" in body
    assert "估值代理" in body
    assert "不是收益预测或操作指令" in body
    assert "测试新闻" in body
    assert not any(term in title + body for term in FORBIDDEN)


def test_unscorable_result_remains_visible():
    result = _sample_result()
    result.update(
        {
            "total_score": None,
            "observation_level": None,
            "technical": None,
            "valuation": None,
            "event": None,
            "quality": {
                "status": "unscorable",
                "issues": ["nav_stale"],
                "data_dates": {"nav": "2026-06-01"},
            },
        }
    )
    _, body = render_daily_report([result])
    assert "不可评分" in body
    assert "基金净值数据过期" in body


def test_verdict_copy_is_non_operational():
    copy = " ".join(
        get_verdict(level)
        for level in (
            "high_attention",
            "attention",
            "neutral",
            "caution",
            "low_attention",
        )
    )
    assert not any(term in copy for term in FORBIDDEN)


def test_weekly_report_discloses_insufficient_outcome_evidence(tmp_path):
    cfg = Config(
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
    init_db(cfg.db_path)
    today = date.today().isoformat()
    with get_conn(cfg.db_path) as conn:
        conn.execute(
            """
            INSERT INTO daily_scores(
                code, score_date, total_score, recommendation,
                observation_level, quality_status, scoring_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("000001", today, 70.0, "attention", "attention", "reliable", "observation-v1"),
        )
        conn.execute(
            """
            INSERT INTO signal_outcomes(
                code, signal_date, scoring_version, observation_level,
                horizon_days, end_date, fund_return_pct,
                benchmark_return_pct, excess_return_pct, beat_benchmark
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("000001", today, "observation-v1", "attention", 5, today, 2.0, 1.0, 1.0, 1),
        )

    title, body = render_weekly_report(cfg)

    assert "观察分" in body
    assert "5日" in body
    assert "样本 1" in body
    assert "证据不足" in body
    assert not any(term in title + body for term in FORBIDDEN)


def test_dashboard_renders_scored_and_unscorable_cards(tmp_path):
    scored = _sample_result()
    unscorable = _sample_result()
    unscorable.update(
        {
            "code": "000002",
            "name": "数据不足基金",
            "total_score": None,
            "observation_level": None,
            "technical": None,
            "valuation": None,
            "event": None,
            "quality": {
                "status": "unscorable",
                "issues": ["nav_stale"],
                "data_dates": {"nav": "2026-06-01"},
            },
        }
    )
    output = tmp_path / "dashboard.png"

    render_dashboard([scored, unscorable], output)

    with Image.open(output) as image:
        assert image.width == 900
        assert image.height > 700
    assert output.stat().st_size > 10_000
