from src.config import QualityConfig, ScoringConfig


def test_quality_defaults_cover_non_trading_days():
    quality = QualityConfig()
    assert quality.max_nav_age_days == 7
    assert quality.max_market_age_days == 7
    assert quality.max_holdings_age_days == 180
    assert quality.max_news_refresh_age_days == 3
    assert quality.min_nav_rows == 60


def test_scoring_has_stable_version():
    scoring = ScoringConfig()
    assert scoring.version == "observation-v2"
    assert scoring.long_term_weights.valuation == 0.4
    assert scoring.long_term_weights.trend == 0.3
    assert scoring.long_term_weights.risk == 0.2
    assert scoring.long_term_weights.tracking == 0.1
    assert scoring.timing_weights.trend == 0.3
    assert scoring.timing_weights.deviation == 0.3
    assert scoring.timing_weights.stabilization == 0.25
    assert scoring.timing_weights.temperature == 0.15
    assert scoring.max_valuation_age_days == 7
    assert scoring.min_valuation_samples == 60
