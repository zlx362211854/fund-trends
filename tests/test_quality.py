from datetime import date

from src.config import QualityConfig, ScoringThresholds, ScoringWeights
from src.quality import assess_quality, compose_observation


def test_stale_nav_is_unscorable():
    result = assess_quality(
        as_of=date(2026, 6, 29),
        nav_rows=250,
        nav_date="2026-06-01",
        market_date="2026-06-27",
        holdings_date="2026-03-31",
        news_refresh_date="2026-06-29",
        event_available=True,
        config=QualityConfig(),
    )
    assert result.status == "unscorable"
    assert "nav_stale" in result.issues


def test_optional_missing_data_is_degraded():
    result = assess_quality(
        as_of=date(2026, 6, 29),
        nav_rows=250,
        nav_date="2026-06-27",
        market_date=None,
        holdings_date="2026-03-31",
        news_refresh_date="2026-06-29",
        event_available=False,
        config=QualityConfig(),
    )
    assert result.status == "degraded"
    assert result.issues == ["market_missing", "event_unavailable"]


def test_missing_event_reweights_available_dimensions():
    result = compose_observation(
        {"technical": 80.0, "valuation": 40.0, "event": None},
        ScoringWeights(),
        ScoringThresholds(),
    )
    assert result.score == 62.9
    assert result.level == "neutral"
    assert result.used_dimensions == ["technical", "valuation"]


def test_missing_technical_dimension_is_unscorable():
    result = compose_observation(
        {"technical": None, "valuation": 40.0, "event": 60.0},
        ScoringWeights(),
        ScoringThresholds(),
    )
    assert result.score is None
    assert result.level is None


def test_chinese_quarter_holding_date_is_supported():
    result = assess_quality(
        as_of=date(2026, 1, 2),
        nav_rows=250,
        nav_date="2026-01-02",
        market_date="2026-01-02",
        holdings_date="2025年4季度股票投资明细",
        news_refresh_date="2026-01-02",
        event_available=True,
        config=QualityConfig(),
    )
    assert result.status == "reliable"
