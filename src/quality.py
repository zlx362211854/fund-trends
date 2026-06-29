"""Data quality gates and score composition for observation results."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import re
from typing import Literal

from src.config import QualityConfig, ScoringThresholds, ScoringWeights

QualityStatus = Literal["reliable", "degraded", "unscorable"]


@dataclass
class QualityResult:
    status: QualityStatus
    issues: list[str]
    data_dates: dict[str, str | None]
    inputs: dict[str, dict] = field(default_factory=dict)


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
    "valuation_missing": "缺少真实指数估值数据",
    "valuation_stale": "真实指数估值数据过期",
    "valuation_history_insufficient": "真实指数估值历史样本不足",
    "refresh_failed": "估值数据本次刷新失败，已检查缓存",
    "timing_history_insufficient": "时机评分所需历史数据不足",
    "long_term_history_insufficient": "长期评分所需基准历史不足",
    "tracking_history_insufficient": "基金与基准重合历史不足",
    "ndx_market_missing": "缺少纳斯达克100行情",
    "usdcny_missing": "缺少美元兑人民币汇率",
    "active_fundamentals_unavailable": "主动基金基本面评价尚不可用",
}


def age_days(value: str | None, as_of: date) -> int | None:
    if not value:
        return None
    text = str(value)
    try:
        parsed = date.fromisoformat(text[:10])
    except ValueError:
        quarter = re.search(r"(\d{4})年([1-4])季度", text)
        if not quarter:
            return None
        year, number = int(quarter.group(1)), int(quarter.group(2))
        month_day = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
        month, day = month_day[number]
        parsed = date(year, month, day)
    return (as_of - parsed).days


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
    nav_age = age_days(nav_date, as_of)
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
        age = age_days(value, as_of)
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


def compose_v2_quality(
    *,
    inputs: dict[str, dict],
    long_term_available: bool,
    timing_available: bool,
    score_issues: list[str],
) -> QualityResult:
    issues = list(dict.fromkeys(score_issues))
    for name, item in inputs.items():
        status = item.get("status")
        if status in {"missing", "stale", "failed", "insufficient"}:
            issue = item.get("issue") or f"{name}_{status}"
            if issue not in issues:
                issues.append(issue)
    if not long_term_available and not timing_available:
        status: QualityStatus = "unscorable"
    elif issues or any(
        item.get("status") not in {"ok"} for item in inputs.values()
    ):
        status = "degraded"
    else:
        status = "reliable"
    data_dates = {name: item.get("date") for name, item in inputs.items()}
    return QualityResult(status, issues, data_dates, inputs)
