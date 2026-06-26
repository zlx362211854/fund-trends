"""事件面打分:LLM(DeepSeek)分析持仓相关新闻
输入:基金信息 + 持仓 + 预筛选新闻
输出:事件分(0-100, 50 中性) + 简要理由 + 风险提示
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd
from loguru import logger
from openai import OpenAI

from src.config import LLMConfig


@dataclass
class EventScore:
    score: float             # 0-100, 50 = 中性
    reason: str              # 一句话理由
    risks: list[str]         # 风险提示


SYSTEM_PROMPT = """你是基金研究助理。给定一只基金的核心持仓、结构化市场事件、最近相关新闻,
请评估近期事件对"加仓决策"的综合影响,并输出 JSON。

打分规则(0-100,50 为中性):
- 0-30: 显著不利于加仓(板块/政策/重仓股明显负面;或市场过热)
- 31-49: 偏负面
- 50: 无重大消息 / 利好利空对冲
- 51-70: 偏正面
- 71-100: 显著利好加仓(行业利好叠加、政策催化、估值修复信号)

加仓视角的逻辑:
- 市场已大涨/分位偏高 → 减分(追高不利)
- 市场已大跌/分位偏低 → 加分(便宜)
- 利好新闻 → 视情形加分;利空新闻 → 减分

注意:
- 结构化市场事件(📈/📉)是最重要的信号,优先参考。
- 新闻必须明确指向该基金的持仓行业/标的才计为有效信号。
- 无信号 → 50。
- 不要预测未来,只评估"已发生事件"。
- 输出必须是合法 JSON,不要解释、不要 markdown 围栏。
"""


JSON_SCHEMA_HINT = """请按以下 JSON 模式输出:
{
  "score": <0-100 的整数>,
  "reason": "<不超过 30 字的中文一句话理由>",
  "risks": ["<可选,简短风险点,可为空数组>"]
}"""


def _build_user_message(
    fund_name: str,
    fund_type: str,
    holdings: pd.DataFrame,
    news: pd.DataFrame,
    market_events_str: str = "",
) -> str:
    holdings_str = "(无持仓数据)"
    if not holdings.empty:
        top = holdings.head(10)
        holdings_str = "\n".join(
            f"- {r.stock_name}({r.stock_code}) 占净值 {r.pct:.2f}%"
            for r in top.itertuples()
        )

    if news.empty:
        news_str = "(无相关新闻)"
    else:
        news_str = "\n".join(
            f"[{r.publish_at[:16]}] {r.title}"
            for r in news.head(20).itertuples()
        )

    events_block = market_events_str or "(无结构化市场事件)"

    return f"""基金:{fund_name}(类型:{fund_type})

前十大持仓:
{holdings_str}

结构化市场事件(关键信号):
{events_block}

近 24 小时相关新闻:
{news_str}

{JSON_SCHEMA_HINT}"""


def compute_event_score(
    llm_cfg: LLMConfig,
    fund_name: str,
    fund_type: str,
    holdings: pd.DataFrame,
    news: pd.DataFrame,
    market_events_str: str = "",
) -> EventScore:
    # 既无新闻也无市场事件 → 返回中性,省一次 LLM 调用
    if news.empty and not market_events_str:
        return EventScore(50.0, "无可用事件,中性", [])

    client = OpenAI(api_key=llm_cfg.api_key, base_url=llm_cfg.base_url)
    user_msg = _build_user_message(fund_name, fund_type, holdings, news, market_events_str)

    try:
        resp = client.chat.completions.create(
            model=llm_cfg.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or "{}"
        data = json.loads(content)
        return EventScore(
            score=float(data.get("score", 50)),
            reason=str(data.get("reason", "")),
            risks=list(data.get("risks", []) or []),
        )
    except Exception as e:
        logger.error(f"[event] LLM 打分失败 ({fund_name}): {e}")
        return EventScore(50.0, "事件分析失败,按中性处理", [])
