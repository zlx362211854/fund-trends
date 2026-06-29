"""Data quality gates and score composition for observation results."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from src.config import QualityConfig, ScoringThresholds, ScoringWeights

QualityStatus = Literal["reliable", "degraded", "unscorable"]


@dataclass
class QualityResult:
    status: QualityStatus
    issues: list[str]
    data_dates: dict[str, str | None]


@dataclass
class ObservationResult:
    score: float | None
    level: str | None
    used_dimensions: list[str]


ISSUE_LABELS = {
    "nav_missing": "缺少基金净值数据",
    "nav_insufficient": "基金净值历史不足",
    "nav_stale": "基金净值数据过期",
    "market_missing": "缺少对应市场数据",
    "market_stale": "对应市场数据过期",
    "holdings_missing": "缺少基金持仓数据",
    "holdings_stale": "基金持仓数据过期",
    "news_refresh_missing": "缺少新闻刷新记录",
    "news_refresh_stale": "新闻数据未及时刷新",
    "event_unavailable": "事件分析不可用",
    "valuation_fallback": "估值代理使用净值分位回退",
}


def _age_days(value: str | None, as_of: date) -> int | None:
    if not value:
        return None
    return (as_of - date.fromisoformat(str(value)[:10])).days


def assess_quality(
    *,
    as_of: date,
    nav_rows: int,
    nav_date: str | None,
    market_date: str | None,
    holdings_date: str | None,
    news_refresh_date: str | None,
    event_available: bool,
    config: QualityConfig,
    valuation_fallback: bool = False,
) -> QualityResult:
    issues: list[str] = []
    if not nav_date:
        issues.append("nav_missing")
    if nav_rows < config.min_nav_rows:
        issues.append("nav_insufficient")
    nav_age = _age_days(nav_date, as_of)
    if nav_age is not None and nav_age > config.max_nav_age_days:
        issues.append("nav_stale")

    critical = {"nav_missing", "nav_insufficient", "nav_stale"}
    data_dates = {
        "nav": nav_date,
        "market": market_date,
        "holdings": holdings_date,
        "news_refresh": news_refresh_date,
    }
    if critical.intersection(issues):
        return QualityResult("unscorable", issues, data_dates)

    checks = (
        ("market", market_date, config.max_market_age_days),
        ("holdings", holdings_date, config.max_holdings_age_days),
        ("news_refresh", news_refresh_date, config.max_news_refresh_age_days),
    )
    for name, value, max_age in checks:
        age = _age_days(value, as_of)
        if age is None:
            issues.append(f"{name}_missing")
        elif age > max_age:
            issues.append(f"{name}_stale")
    if not event_available:
        issues.append("event_unavailable")
    if valuation_fallback:
        issues.append("valuation_fallback")

    return QualityResult("degraded" if issues else "reliable", issues, data_dates)


def compose_observation(
    scores: dict[str, float | None],
    weights: ScoringWeights,
    thresholds: ScoringThresholds,
) -> ObservationResult:
    if scores.get("technical") is None:
        return ObservationResult(None, None, [])

    configured = {
        "technical": weights.technical,
        "valuation": weights.valuation,
        "event": weights.event,
    }
    used = [name for name in configured if scores.get(name) is not None]
    weight_sum = sum(configured[name] for name in used)
    if weight_sum <= 0:
        return ObservationResult(None, None, [])

    score = round(
        sum(float(scores[name]) * configured[name] for name in used) / weight_sum,
        1,
    )
    if score >= thresholds.strong_buy:
        level = "high_attention"
    elif score >= thresholds.buy:
        level = "attention"
    elif score >= thresholds.neutral:
        level = "neutral"
    elif score >= thresholds.avoid:
        level = "caution"
    else:
        level = "low_attention"
    return ObservationResult(score, level, used)
