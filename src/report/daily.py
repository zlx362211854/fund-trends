"""ServerChan Markdown report for dual-horizon observations."""
from __future__ import annotations

from datetime import date

from src.quality import ISSUE_LABELS

LEVEL_LABELS = {
    "strong": "条件较强",
    "above_average": "条件偏强",
    "neutral": "条件中性",
    "below_average": "条件偏弱",
    "weak": "条件较弱",
}

QUALITY_INFO = {
    "reliable": ("数据可靠", "✅"),
    "degraded": ("数据降级", "⚠️"),
    "unscorable": ("数据不足", "⛔"),
}

TYPE_TAG = {
    "domestic_active": "国内主动",
    "domestic_index": "国内指数",
    "qdii_index": "QDII 指数",
}

INPUT_LABELS = {
    "nav": "基金净值",
    "holdings": "基金持仓",
    "news": "新闻",
    "event": "AI事件",
    "ndx_market": "纳斯达克100行情",
    "usdcny": "USD/CNY",
    "ndx_valuation": "纳指估值",
    "hs300_market": "沪深300行情",
}

STATUS_LABELS = {
    "ok": "正常",
    "cached": "缓存可用",
    "stale": "过期",
    "missing": "缺失",
    "failed": "失败",
    "insufficient": "样本不足",
}


def _fund_links(code: str) -> tuple[str, str]:
    return (
        f"https://fund.eastmoney.com/{code}.html",
        f"https://fundf10.eastmoney.com/jbgk_{code}.html",
    )


def _score_text(score: dict) -> str:
    if score.get("score") is None:
        return "暂不可评估"
    label = LEVEL_LABELS.get(score.get("level"), "状态未知")
    return f"`{score['score']:.0f}/100` · {label}"


def _combination_summary(result: dict) -> str:
    long_term = result["long_term"]
    timing = result["timing"]
    long_score = long_term.get("score")
    timing_score = timing.get("score")
    if long_score is None and timing_score is None:
        return "核心数据不足，目前无法形成长期条件或当前时机判断。"
    if long_score is None:
        return "长期条件因真实估值或基本面数据不足暂不可评估；当前时机仍可独立观察。"
    if timing_score is None:
        return "长期条件可以评估，但当前时机所需的价格历史不足。"
    if long_score >= 60 and timing_score >= 60:
        return "长期条件和当前时机均偏强，但仍需结合自身风险承受能力判断。"
    if long_score >= 60 and timing_score < 40:
        return "长期条件偏强，但当前偏热或尚未企稳，两项结论并不矛盾。"
    if long_score < 40 and timing_score >= 60:
        return "当前可能处于修复阶段，但长期依据仍偏弱。"
    return "长期条件与当前时机信号存在分化，建议分别查看下方驱动因素。"


def _long_term_lines(score: dict) -> list[str]:
    if score.get("score") is None:
        return [f"- {ISSUE_LABELS.get(issue, issue)}" for issue in score.get("issues", [])]
    metrics = score.get("metrics", {})
    lines = [
        "- 前瞻PE "
        f"`{metrics.get('valuation_value', 0):.2f}` · 近10年分位 "
        f"`{metrics.get('valuation_percentile_pct', 0):.0f}%` · "
        f"数据 `{metrics.get('valuation_date') or '未知'}`",
        "- 长期趋势："
        f"近6个月 `{metrics.get('return_6m_pct', 0):+.1f}%` · "
        f"近12个月 `{metrics.get('return_12m_pct', 0):+.1f}%`",
        "- 风险与跟踪："
        f"年化波动 `{metrics.get('annualized_volatility_pct', 0):.1f}%` · "
        f"最大回撤 `{metrics.get('max_drawdown_pct', 0):.1f}%` · "
        f"跟踪相关 `{metrics.get('tracking_correlation', 0):.2f}`",
    ]
    source = metrics.get("valuation_source")
    cache = metrics.get("valuation_cache_status")
    if source:
        lines.append(f"- 估值来源：`{source}` · 状态 `{cache or '未知'}`")
    return lines


def _timing_lines(score: dict) -> list[str]:
    if score.get("score") is None:
        return [f"- {ISSUE_LABELS.get(issue, issue)}" for issue in score.get("issues", [])]
    metrics = score.get("metrics", {})
    stabilized = "已出现企稳" if metrics.get("stabilized") == "yes" else "尚未确认企稳"
    return [
        "- 趋势状态："
        f"MA200斜率 `{metrics.get('ma200_slope_pct', 0):+.2f}%`",
        "- 趋势偏离："
        f"距MA60 `{metrics.get('distance_ma60_pct', 0):+.1f}%` · "
        f"标准化偏离 `{metrics.get('deviation_z', 0):+.2f}`",
        "- 回撤确认："
        f"当前回撤 `{metrics.get('drawdown_pct', 0):.1f}%` · {stabilized} · "
        f"RSI `{metrics.get('rsi_14', 0):.0f}`",
    ]


def _format_evidence(event: dict) -> list[str]:
    lines: list[str] = []
    for item in event.get("evidence", [])[:3]:
        if item.get("type") != "news" or not item.get("title"):
            continue
        title = str(item["title"]).replace("[", "").replace("]", "")
        source = item.get("source") or "来源未标注"
        url = item.get("url")
        lines.append(f"- [{title}]({url}) · {source}" if url else f"- {title} · {source}")
    return lines


def _format_result(result: dict) -> str:
    detail_url, f10_url = _fund_links(result["code"])
    quality = result["quality"]
    quality_label, quality_icon = QUALITY_INFO.get(
        quality.get("status"), ("状态未知", "⚪")
    )
    lines = [
        f"### [{result['name']}]({detail_url})",
        f"`{result['code']}` · {TYPE_TAG.get(result.get('type', ''), '')} · [F10 资料]({f10_url})",
        "",
        f"> {_combination_summary(result)}",
        "",
        f"**长期持有条件** {_score_text(result['long_term'])}",
        *_long_term_lines(result["long_term"]),
        "",
        f"**当前投入时机** {_score_text(result['timing'])}",
        *_timing_lines(result["timing"]),
        "",
        f"{quality_icon} **数据可信度：{quality_label}** · 版本 `{result['scoring_version']}`",
    ]

    inputs = quality.get("inputs", {})
    if inputs:
        lines.extend(["", "**数据状态**"])
        for name, item in inputs.items():
            label = INPUT_LABELS.get(name, name)
            status = STATUS_LABELS.get(item.get("status"), item.get("status", "未知"))
            data_date = str(item.get("date") or "未知")[:10]
            lines.append(f"- {label}：{status} · `{data_date}`")

    event = result.get("event")
    if event:
        lines.extend(["", f"**AI事件分析（不参与评分）** · `{event.get('status', 'unknown')}`"])
        if event.get("model"):
            lines.append(f"- 模型：`{event['model']}`")
        if event.get("reason"):
            lines.append(f"> {event['reason']}")
        evidence = _format_evidence(event)
        if evidence:
            lines.extend(["**证据来源**", *evidence])
        if event.get("risks"):
            lines.extend(["**事件风险**", *(f"- {risk}" for risk in event["risks"])])
    return "\n".join(lines)


def render_daily_report(results: list[dict]) -> tuple[str, str]:
    today = date.today()
    weekday = ["一", "二", "三", "四", "五", "六", "日"][today.weekday()]
    title = f"📊 基金观察日报 · {today.strftime('%m-%d')}(周{weekday})"
    if not results:
        return title, "⚠️ 今日无观察结果，请检查数据抓取和日志。"

    parts: list[str] = []
    if len(results) > 1:
        parts.extend(
            [
                "**全部基金速览**",
                "",
                "| 基金 | 长期持有条件 | 当前投入时机 | 数据状态 |",
                "| :-- | :-- | :-- | :-- |",
            ]
        )
        for result in results:
            url, _ = _fund_links(result["code"])
            quality_label, _ = QUALITY_INFO.get(result["quality"]["status"], ("未知", ""))
            parts.append(
                f"| [{result['name']}]({url}) | {_score_text(result['long_term'])} | "
                f"{_score_text(result['timing'])} | {quality_label} |"
            )
        parts.append("")

    for result in results:
        parts.extend(["---", "", _format_result(result), ""])
    parts.extend(
        [
            "---",
            "",
            "📝 *两项分数是规则化研究观察，不是收益预测或操作指令。请独立判断风险。*",
        ]
    )
    return title, "\n".join(parts)
