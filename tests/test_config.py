from src.config import QualityConfig, ScoringConfig


def test_quality_defaults_cover_non_trading_days():
    quality = QualityConfig()
    assert quality.max_nav_age_days == 7
    assert quality.max_market_age_days == 7
    assert quality.max_holdings_age_days == 180
    assert quality.max_news_refresh_age_days == 3
    assert quality.min_nav_rows == 60


def test_scoring_has_stable_version():
    assert ScoringConfig().version == "observation-v1"
