"""Agent 编排管道。
MVP 阶段:Agent 框架是薄壳,核心逻辑在 tools.py。
后续可改造为 openai-agents SDK 的 Handoff 模式。
"""
from __future__ import annotations

from loguru import logger

from src.config import Config
from src.evaluation.outcomes import update_mature_outcomes
from src.agents.tools import (
    tool_refresh_fund_data,
    tool_refresh_market_data,
    tool_refresh_news,
    tool_score_fund,
)


def run_data_agent(cfg: Config) -> dict:
    """Data Agent:刷新所有数据"""
    logger.info("=== Data Agent ===")
    out = {"funds": {}, "market": {}, "news": {}}

    for fund in cfg.funds:
        try:
            out["funds"][fund.code] = tool_refresh_fund_data(cfg, fund.code)
        except Exception as e:
            logger.error(f"[data] {fund.code} 抓取失败: {e}")
            out["funds"][fund.code] = {"error": str(e)}

    out["market"] = tool_refresh_market_data(cfg)
    try:
        out["news"] = tool_refresh_news(cfg)
    except Exception as exc:
        logger.error(f"[data] 新闻抓取失败: {exc}")
        out["news"] = {"error": str(exc)}
    return out


def run_analysis_agent(cfg: Config) -> list[dict]:
    """Analysis Agent:对所有基金打分"""
    logger.info("=== Analysis Agent ===")
    results: list[dict] = []
    for fund in cfg.funds:
        try:
            r = tool_score_fund(cfg, fund)
            if r["total_score"] is None:
                logger.warning(
                    f"  {fund.name}({fund.code}): 不可评分 → {r['quality']['issues']}"
                )
            else:
                logger.success(
                    f"  {fund.name}({fund.code}): {r['total_score']} → "
                    f"{r['observation_level']} ({r['quality']['status']})"
                )
            results.append(r)
        except Exception as e:
            logger.error(f"  打分失败 {fund.code}: {e}")
    # 按总分降序
    results.sort(
        key=lambda item: (
            item["total_score"] is not None,
            item["total_score"] if item["total_score"] is not None else -1,
        ),
        reverse=True,
    )
    return results


def run_pipeline(cfg: Config) -> list[dict]:
    """Orchestrator:Data → Analysis"""
    run_data_agent(cfg)
    results = run_analysis_agent(cfg)
    try:
        updated = update_mature_outcomes(cfg)
        logger.info(f"[outcome] 新增到期结果 {updated} 条")
    except Exception as exc:
        logger.error(f"[outcome] 结果评价失败,下次重试: {exc}")
    return results
