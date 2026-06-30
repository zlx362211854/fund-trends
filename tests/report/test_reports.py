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
        "long_term": {
            "score": 72.0,
            "level": "above_average",
            "factors": {
                "valuation": 65.0,
                "trend": 80.0,
                "risk": 70.0,
                "tracking": 75.0,
            },
            "metrics": {
                "valuation_metric": "forward_pe",
                "valuation_value": 24.29,
                "valuation_percentile_pct": 58.0,
                "valuation_date": "2026-06-27",
                "valuation_source": "test source",
                "valuation_cache_status": "fresh",
                "return_6m_pct": 8.2,
                "return_12m_pct": 15.4,
                "annualized_volatility_pct": 21.0,
                "max_drawdown_pct": -18.0,
                "tracking_correlation": 0.91,
            },
            "issues": [],
        },
        "timing": {
            "score": 38.0,
            "level": "below_average",
            "factors": {
                "trend": 75.0,
                "deviation": 20.0,
                "stabilization": 35.0,
                "temperature": 40.0,
            },
            "metrics": {
                "ma200_slope_pct": 1.2,
                "distance_ma60_pct": 8.5,
                "deviation_z": 2.1,
                "drawdown_pct": -4.0,
                "stabilized": "no",
                "rsi_14": 68.0,
            },
            "issues": [],
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
                "holdings": "2026-03-31",
                "ndx_market": "2026-06-27",
                "usdcny": "2026-06-27",
                "ndx_valuation": "2026-06-27",
                "news": "2026-06-29",
            },
            "inputs": {
                "nav": {"status": "ok", "date": "2026-06-27"},
                "ndx_market": {"status": "ok", "date": "2026-06-27"},
                "usdcny": {"status": "ok", "date": "2026-06-27"},
                "ndx_valuation": {"status": "ok", "date": "2026-06-27"},
                "news": {"status": "ok", "date": "2026-06-29"},
                "event": {"status": "ok", "date": "2026-06-29"},
            },
        },
        "scoring_version": "observation-v2",
        "market_events": "",
    }


def test_daily_report_uses_observation_language():
    title, body = render_daily_report([_sample_result()])
    assert "长期持有条件" in body
    assert "当前投入时机" in body
    assert "数据可信度" in body
    assert "前瞻PE" in body
    assert "不参与评分" in body
    assert "观察总分" not in body
    assert "不是收益预测或操作指令" in body
    assert "测试新闻" in body
    assert not any(term in title + body for term in FORBIDDEN)


def test_unscorable_result_remains_visible():
    result = _sample_result()
    result.update(
        {
            "long_term": {"score": None, "level": None, "factors": {}, "metrics": {}, "issues": ["nav_stale"]},
            "timing": {"score": None, "level": None, "factors": {}, "metrics": {}, "issues": ["nav_stale"]},
            "event": None,
            "quality": {
                "status": "unscorable",
                "issues": ["nav_stale"],
                "data_dates": {"nav": "2026-06-01"},
            },
        }
    )
    _, body = render_daily_report([result])
    assert "暂不可评估" in body
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
                observation_level, quality_status, scoring_version,
                long_term_score, long_term_level, timing_score, timing_level
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "000001", today, 65.0, "above_average", "above_average",
                "reliable", "observation-v2", 72.0, "above_average",
                38.0, "below_average",
            ),
        )
        conn.execute(
            """
            INSERT INTO score_outcomes_v2(
                code, signal_date, scoring_version, dimension, level,
                horizon_days, end_date, fund_return_pct,
                benchmark_return_pct, excess_return_pct, beat_benchmark
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "000001", today, "observation-v2", "timing", "below_average",
                5, today, 2.0, 1.0, 1.0, 1,
            ),
        )

    title, body = render_weekly_report(cfg)

    assert "长期持有条件" in body
    assert "当前投入时机" in body
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
            "long_term": {"score": None, "level": None, "factors": {}, "metrics": {}, "issues": ["nav_stale"]},
            "timing": {"score": None, "level": None, "factors": {}, "metrics": {}, "issues": ["nav_stale"]},
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
