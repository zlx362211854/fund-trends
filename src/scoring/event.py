"""Validated LLM analysis of recent fund-related events."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from loguru import logger
from openai import OpenAI

from src.config import LLMConfig


@dataclass
class EventScore:
    score: float | None
    reason: str
    risks: list[str]
    available: bool = True
    status: str = "ok"
    model: str = ""
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    evidence: list[dict[str, Any]] = field(default_factory=list)


SYSTEM_PROMPT = """你是基金研究助理。根据基金持仓、结构化市场事件和相关新闻，
评估这些已发生事实对当前观察优先级的影响，并输出 JSON。

打分规则(0-100,50 为中性):
- 0-30: 当前关注吸引力明显偏低
- 31-49: 当前关注吸引力偏低
- 50: 无重大消息或影响相互抵消
- 51-70: 当前关注吸引力偏高
- 71-100: 多项已发生事实共同支持重点关注

只使用给定证据，不预测未来价格，不给出买入、卖出、加仓、减仓或仓位指令。
无有效信号时输出 50。输出必须是合法 JSON，不要解释或使用 markdown 围栏。
"""

JSON_SCHEMA_HINT = """请按以下 JSON 模式输出:
{
  "score": <0-100 的数字>,
  "reason": "<不超过 60 字的中文一句话理由>",
  "risks": ["<可选,每项不超过 60 字,最多 5 项>"]
}"""

OPERATION_TERMS = ("买入", "卖出", "加仓", "减仓", "梭哈", "仓位指令")


def _evidence_from_news(news: pd.DataFrame) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for row in news.head(20).itertuples():
        evidence.append(
            {
                "type": "news",
                "source": str(getattr(row, "source", "")),
                "title": str(getattr(row, "title", "")),
                "publish_at": str(getattr(row, "publish_at", "")),
                "url": str(getattr(row, "url", "")),
            }
        )
    return evidence


def _build_user_message(
    fund_name: str,
    fund_type: str,
    holdings: pd.DataFrame,
    news: pd.DataFrame,
    market_events_str: str = "",
) -> str:
    holdings_str = "(无持仓数据)"
    if not holdings.empty:
        holdings_str = "\n".join(
            f"- {row.stock_name}({row.stock_code}) 占净值 {row.pct:.2f}%"
            for row in holdings.head(10).itertuples()
        )

    news_str = "(无相关新闻)"
    if not news.empty:
        news_str = "\n".join(
            f"[{row.publish_at[:16]}] {row.title}"
            for row in news.head(20).itertuples()
        )

    return f"""基金:{fund_name}(类型:{fund_type})

前十大持仓:
{holdings_str}

结构化市场事件:
{market_events_str or "(无结构化市场事件)"}

最近相关新闻:
{news_str}

{JSON_SCHEMA_HINT}"""


def parse_event_response(
    content: str,
    *,
    model: str = "",
    evidence: list[dict[str, Any]] | None = None,
) -> EventScore:
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("response must be a JSON object")

    score = data.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError("score must be numeric")
    if not 0 <= float(score) <= 100:
        raise ValueError("score must be between 0 and 100")

    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 60:
        raise ValueError("reason must be a non-empty string up to 60 characters")

    risks = data.get("risks", [])
    if not isinstance(risks, list) or len(risks) > 5:
        raise ValueError("risks must be a list with at most 5 items")
    if any(not isinstance(item, str) or len(item) > 60 for item in risks):
        raise ValueError("risks entries must be strings up to 60 characters")
    if any(term in reason for term in OPERATION_TERMS) or any(
        term in item for item in risks for term in OPERATION_TERMS
    ):
        raise ValueError("response contains an operation instruction")

    return EventScore(
        score=float(score),
        reason=reason.strip(),
        risks=[item.strip() for item in risks if item.strip()],
        model=model,
        evidence=list(evidence or []),
    )


def compute_event_score(
    llm_cfg: LLMConfig,
    fund_name: str,
    fund_type: str,
    holdings: pd.DataFrame,
    news: pd.DataFrame,
    market_events_str: str = "",
) -> EventScore:
    evidence = _evidence_from_news(news)
    if market_events_str:
        evidence.insert(
            0,
            {"type": "market_events", "summary": market_events_str},
        )

    if news.empty and not market_events_str:
        return EventScore(
            50.0,
            "无重大相关新闻或市场事件",
            [],
            status="no_material_news",
            model=llm_cfg.model,
            evidence=evidence,
        )

    client = OpenAI(api_key=llm_cfg.api_key, base_url=llm_cfg.base_url)
    user_msg = _build_user_message(
        fund_name, fund_type, holdings, news, market_events_str
    )
    try:
        response = client.chat.completions.create(
            model=llm_cfg.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        return parse_event_response(
            content, model=llm_cfg.model, evidence=evidence
        )
    except Exception as exc:
        logger.error(f"[event] LLM 分析失败 ({fund_name}): {exc}")
        return EventScore(
            score=None,
            reason="事件分析不可用",
            risks=[],
            available=False,
            status="error",
            model=llm_cfg.model,
            evidence=evidence,
        )
