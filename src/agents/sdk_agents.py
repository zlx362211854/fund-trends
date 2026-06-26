"""openai-agents SDK 版本的 Agent 定义。
MVP 阶段默认走 pipeline.py 的直接调用,
当需要让 LLM 自主决策"先查哪个、要不要重试"时切换到这个版本。

启用方式:在 scripts/run_daily.py 中改为:
    from src.agents.sdk_agents import run_with_sdk
    results = run_with_sdk(cfg)
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger

from src.config import Config
from src.agents.tools import (
    tool_refresh_fund_data,
    tool_refresh_market_data,
    tool_refresh_news,
    tool_score_fund,
)


def _build_agents(cfg: Config):
    """延迟导入 agents SDK,避免没装时影响主流程"""
    from agents import Agent, function_tool, OpenAIChatCompletionsModel
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=cfg.llm.api_key, base_url=cfg.llm.base_url)
    model = OpenAIChatCompletionsModel(model=cfg.llm.model, openai_client=client)

    @function_tool
    def refresh_fund(code: str) -> str:
        """抓取并保存单只基金的最新净值和持仓。"""
        return json.dumps(tool_refresh_fund_data(cfg, code), ensure_ascii=False)

    @function_tool
    def refresh_market() -> str:
        """刷新纳指、汇率、沪深300 行情数据。"""
        return json.dumps(tool_refresh_market_data(cfg), ensure_ascii=False)

    @function_tool
    def refresh_news(limit: int = 100) -> str:
        """抓取最新财经新闻。"""
        return json.dumps(tool_refresh_news(cfg, limit), ensure_ascii=False)

    @function_tool
    def score_fund(code: str) -> str:
        """对单只基金打分,返回 JSON。"""
        fund = next((f for f in cfg.funds if f.code == code), None)
        if not fund:
            return json.dumps({"error": f"fund {code} not configured"})
        return json.dumps(tool_score_fund(cfg, fund), ensure_ascii=False)

    data_agent = Agent(
        name="DataAgent",
        instructions=(
            "你负责抓取数据。按需调用 refresh_market、refresh_news 和"
            " 对每只基金调用 refresh_fund。完成后输出 'DATA_READY'。"
        ),
        model=model,
        tools=[refresh_fund, refresh_market, refresh_news],
    )

    analysis_agent = Agent(
        name="AnalysisAgent",
        instructions=(
            "数据已就绪。请对配置的每只基金调用 score_fund,"
            "然后返回打分汇总 JSON 数组(按总分降序)。"
        ),
        model=model,
        tools=[score_fund],
    )

    fund_list = ", ".join(f"{f.code}({f.name})" for f in cfg.funds)
    orchestrator = Agent(
        name="Orchestrator",
        instructions=(
            f"基金清单:{fund_list}\n\n"
            "工作流:先 handoff 给 DataAgent 刷新数据,"
            "然后 handoff 给 AnalysisAgent 打分,"
            "最后把打分结果返回。"
        ),
        model=model,
        handoffs=[data_agent, analysis_agent],
    )
    return orchestrator


def run_with_sdk(cfg: Config) -> list[dict[str, Any]]:
    """用 openai-agents SDK 跑完整流程"""
    try:
        from agents import Runner
    except ImportError:
        logger.error("openai-agents 未安装,回退到 pipeline.run_pipeline")
        from src.agents.pipeline import run_pipeline
        return run_pipeline(cfg)

    orchestrator = _build_agents(cfg)
    result = asyncio.run(
        Runner.run(orchestrator, input="请开始今天的基金分析流程。")
    )
    try:
        return json.loads(result.final_output)
    except Exception:
        logger.warning("Agent 输出不是 JSON,回退到直接调用 pipeline")
        from src.agents.pipeline import run_analysis_agent
        return run_analysis_agent(cfg)
