"""配置加载:YAML + 环境变量覆盖"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

FundType = Literal["domestic_active", "domestic_index", "qdii_index"]


@dataclass
class FundConfig:
    code: str
    name: str
    type: FundType


@dataclass
class ScoringWeights:
    technical: float = 0.4
    valuation: float = 0.3
    event: float = 0.3


@dataclass
class LongTermWeights:
    valuation: float = 0.4
    trend: float = 0.3
    risk: float = 0.2
    tracking: float = 0.1


@dataclass
class TimingWeights:
    trend: float = 0.3
    deviation: float = 0.3
    stabilization: float = 0.25
    temperature: float = 0.15


@dataclass
class ScoringThresholds:
    strong_buy: int = 85
    buy: int = 70
    neutral: int = 50
    avoid: int = 30


@dataclass
class ScoringConfig:
    weights: ScoringWeights = field(default_factory=ScoringWeights)
    thresholds: ScoringThresholds = field(default_factory=ScoringThresholds)
    long_term_weights: LongTermWeights = field(default_factory=LongTermWeights)
    timing_weights: TimingWeights = field(default_factory=TimingWeights)
    max_valuation_age_days: int = 7
    min_valuation_samples: int = 60
    version: str = "observation-v2"


@dataclass
class QualityConfig:
    max_nav_age_days: int = 7
    max_market_age_days: int = 7
    max_holdings_age_days: int = 180
    max_news_refresh_age_days: int = 3
    min_nav_rows: int = 60


@dataclass
class LLMConfig:
    provider: str
    api_key: str
    base_url: str
    model: str


@dataclass
class PushConfig:
    serverchan_key: str


@dataclass
class ScheduleConfig:
    daily_time: str = "08:00"
    weekly_time: str = "17:00"
    weekly_day: str = "friday"


@dataclass
class Config:
    funds: list[FundConfig]
    scoring: ScoringConfig
    quality: QualityConfig
    llm: LLMConfig
    push: PushConfig
    schedule: ScheduleConfig
    db_path: Path
    log_level: str
    log_path: Path


def load_config(path: str | Path | None = None) -> Config:
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    cfg_path = Path(path) if path else PROJECT_ROOT / "config.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"未找到配置文件 {cfg_path}。请复制 config.yaml.example 为 config.yaml 并填写。"
        )

    with open(cfg_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    funds = [FundConfig(**f) for f in raw["funds"]]

    scoring_raw = raw.get("scoring", {})
    scoring = ScoringConfig(
        weights=ScoringWeights(**scoring_raw.get("weights", {})),
        thresholds=ScoringThresholds(**scoring_raw.get("thresholds", {})),
        long_term_weights=LongTermWeights(
            **scoring_raw.get("long_term_weights", {})
        ),
        timing_weights=TimingWeights(**scoring_raw.get("timing_weights", {})),
        max_valuation_age_days=scoring_raw.get("max_valuation_age_days", 7),
        min_valuation_samples=scoring_raw.get("min_valuation_samples", 60),
        version=scoring_raw.get("version", "observation-v2"),
    )
    for name, weights in (
        ("long_term_weights", scoring.long_term_weights),
        ("timing_weights", scoring.timing_weights),
    ):
        if abs(sum(vars(weights).values()) - 1.0) > 1e-9:
            raise ValueError(f"scoring.{name} 权重之和必须为 1.0")
    quality = QualityConfig(**raw.get("quality", {}))

    llm_raw = raw.get("llm", {})
    llm_key = os.getenv("DEEPSEEK_API_KEY") or llm_raw.get("api_key", "")
    if not llm_key:
        raise ValueError("缺少 DEEPSEEK_API_KEY。请在 .env 中配置或在 config.yaml 的 llm.api_key 填写。")
    llm = LLMConfig(
        provider=llm_raw.get("provider", "deepseek"),
        api_key=llm_key,
        base_url=llm_raw.get("base_url", "https://api.deepseek.com/v1"),
        model=llm_raw.get("model", "deepseek-chat"),
    )

    push_raw = raw.get("push", {})
    push_key = os.getenv("SERVERCHAN_KEY") or push_raw.get("serverchan_key", "")
    if not push_key:
        raise ValueError("缺少 SERVERCHAN_KEY。请在 .env 中配置或在 config.yaml 的 push.serverchan_key 填写。")
    push = PushConfig(serverchan_key=push_key)

    schedule = ScheduleConfig(**raw.get("schedule", {}))

    db_path = PROJECT_ROOT / raw.get("database", {}).get("path", "data/fund_trends.db")
    log_raw = raw.get("logging", {})
    log_path = PROJECT_ROOT / log_raw.get("path", "logs/fund_trends.log")

    return Config(
        funds=funds,
        scoring=scoring,
        quality=quality,
        llm=llm,
        push=push,
        schedule=schedule,
        db_path=db_path,
        log_level=log_raw.get("level", "INFO"),
        log_path=log_path,
    )
