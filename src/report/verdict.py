"""Short factual summaries for observation levels."""
from __future__ import annotations

SUMMARY = {
    "high_attention": "多项规则指标处于高关注区间",
    "attention": "规则指标显示较高观察优先级",
    "neutral": "当前规则指标整体处于中性区间",
    "caution": "当前规则指标支持保持谨慎观察",
    "low_attention": "当前规则指标的观察优先级较低",
}


def get_verdict(
    observation_level: str | None,
    fund_code: str = "",
    seed_date=None,
) -> str:
    del fund_code, seed_date
    return SUMMARY.get(observation_level or "", "当前数据不足，无法形成观察结论")
