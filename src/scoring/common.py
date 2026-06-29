"""Shared primitives for versioned observation scores."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HorizonScore:
    score: float | None
    level: str | None
    factors: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, float | str | None] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)


def clamp_score(value: float) -> float:
    return round(max(0.0, min(100.0, float(value))), 1)


def score_level(score: float) -> str:
    if score >= 80:
        return "strong"
    if score >= 60:
        return "above_average"
    if score >= 40:
        return "neutral"
    if score >= 20:
        return "below_average"
    return "weak"
