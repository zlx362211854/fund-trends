"""ServerChan Markdown report for quality-aware fund observations."""
from __future__ import annotations

from datetime import date

from src.quality import ISSUE_LABELS
from src.report.verdict import get_verdict

LEVEL_INFO = {
    "high_attention": ("🟢", "高关注"),
    "attention": ("🟢", "较高关注"),
    "neutral": ("🟡", "中性观察"),
    "caution": ("🟠", "谨慎观察"),
    "low_attention": ("🔴", "低关注"),
}

QUALITY_INFO = {
    "reliable": ("数据可靠", "✅"),
    "degraded": ("数据降级", "⚠️"),
    "unscorable": ("不可评分", "⛔"),
}

TYPE_TAG = {
    "domestic_active": "国内主动",
    "domestic_index": "国内指数",
    "qdii_index": "QDII 指数",
}


def _fund_links(code: str) -> tuple[str, str]:
    return (
        f"https://fund.eastmoney.com/{code}.html",
        f"https://fundf10.eastmoney.com/jbgk_{code}.html",
    )


def _issue_lines(quality: dict) -> list[str]:
    return [ISSUE_LABELS.get(issue, issue) for issue in quality.get("issues", [])]


def _format_evidence(event: dict) -> list[str]:
    lines: list[str] = []
    for item in event.get("evidence", [])[:3]:
        if item.get("type") != "news" or not item.get("title"):
            continue
        title = str(item["title"]).replace("[", "").replace("]", "")
        source = item.get("source") or "来源未标注"
        url = item.get("url")
        if url:
            lines.append(f"- [{title}]({url}) · {source}")
        else:
            lines.append(f"- {title} · {source}")
    return lines


def _format_unscorable(r: dict) -> str:
    quality = r["quality"]
    detail_url, f10_url = _fund_links(r["code"])
    lines = [
        f"### ⛔ [{r['name']}]({detail_url})",
        f"`{r['code']}` · {TYPE_TAG.get(r.get('type', ''), '')} · [F10 资料]({f10_url})",
        "",
        "**数据可信度：不可评分**",
    ]
    for issue in _issue_lines(quality):
        lines.append(f"- {issue}")
    nav_date = quality.get("data_dates", {}).get("nav")
    if nav_date:
        lines.append(f"- 最近净值日期：`{nav_date}`")
    lines.extend(["", "> 数据恢复前不生成数值观察分。"])
    return "\n".join(lines)


def _format_scored(r: dict) -> str:
    technical = r["technical"]
    valuation = r["valuation"]
    event = r["event"]
    quality = r["quality"]
    emoji, level_label = LEVEL_INFO.get(
        r.get("observation_level"), ("⚪", "未知等级")
    )
    quality_label, quality_icon = QUALITY_INFO.get(
        quality.get("status"), ("状态未知", "⚪")
    )
    detail_url, f10_url = _fund_links(r["code"])
    event_score = (
        f"{event['score']:.0f}" if event and event.get("score") is not None else "不可用"
    )
    lines = [
        f"### {emoji} [{r['name']}]({detail_url})",
        f"`{r['code']}` · {TYPE_TAG.get(r.get('type', ''), '')} · [F10 资料]({f10_url})",
        "",
        f"**观察分 `{r['total_score']:.0f}/100` · {level_label}**",
        f"{quality_icon} **数据可信度：{quality_label}** · 版本 `{r['scoring_version']}`",
        "",
        f"- 技术 `{technical['score']:.0f}` · 估值代理 `{valuation['score']:.0f}` · 事件 `{event_score}`",
        f"- 估值代理方法：`{valuation['method']}`",
        f"- 近1年分位 `{technical['quantile_1y'] * 100:.0f}%` · 回撤 `{technical['drawdown_pct']:.1f}%`",
        f"- 距MA60 `{technical['ma60_dist_pct']:+.1f}%` · RSI `{technical['rsi_14']:.0f}`",
    ]

    dates = quality.get("data_dates", {})
    date_parts = [
        f"净值 {dates.get('nav') or '未知'}",
        f"市场 {dates.get('market') or '未知'}",
        f"持仓 {dates.get('holdings') or '未知'}",
    ]
    lines.extend(["", "**数据日期**", "- " + " · ".join(date_parts)])

    issues = _issue_lines(quality)
    if issues:
        lines.extend(["", "**降级原因**"])
        lines.extend(f"- {issue}" for issue in issues)

    if r.get("market_events"):
        lines.extend(["", "**市场状态**"])
        lines.extend(
            f"- {line.strip()}"
            for line in r["market_events"].splitlines()
            if line.strip()
        )

    if event:
        lines.extend(["", f"**AI事件分析** · `{event.get('status', 'unknown')}`"])
        if event.get("model"):
            lines.append(f"- 模型：`{event['model']}`")
        if event.get("reason"):
            lines.append(f"> {event['reason']}")
        evidence = _format_evidence(event)
        if evidence:
            lines.append("**证据来源**")
            lines.extend(evidence)

    risks = list(event.get("risks", []) if event else [])
    if not technical.get("trend_filter_passed", True):
        risks.append("短期趋势仍下行，技术分已应用反转过滤")
    if risks:
        lines.extend(["", "**风险说明**"])
        lines.extend(f"- {risk}" for risk in risks)

    lines.extend(["", f"> {get_verdict(r.get('observation_level'))}"])
    return "\n".join(lines)


def render_daily_report(results: list[dict]) -> tuple[str, str]:
    today = date.today()
    weekday = ["一", "二", "三", "四", "五", "六", "日"][today.weekday()]
    title = f"📊 基金观察日报 · {today.strftime('%m-%d')}(周{weekday})"
    if not results:
        return title, "⚠️ 今日无观察结果，请检查数据抓取和日志。"

    scored = [item for item in results if item.get("total_score") is not None]
    parts: list[str] = []
    if scored:
        top = max(scored, key=lambda item: item["total_score"])
        _, label = LEVEL_INFO.get(top.get("observation_level"), ("⚪", "未知等级"))
        parts.extend(
            [
                "> **今日最高观察分**",
                f"> {top['name']} · `{top['total_score']:.0f}/100` · {label}",
                "",
            ]
        )
    else:
        parts.extend(["> 今日没有可评分基金。", ""])

    if len(results) > 1:
        parts.extend(
            [
                "**全部基金速览**",
                "",
                "| 基金 | 观察分 | 等级 | 可信度 |",
                "| :-- | :-: | :-- | :-- |",
            ]
        )
        for item in results:
            _, level = LEVEL_INFO.get(item.get("observation_level"), ("⛔", "不可评分"))
            quality, _ = QUALITY_INFO.get(
                item["quality"]["status"], ("状态未知", "⚪")
            )
            score = f"{item['total_score']:.0f}" if item.get("total_score") is not None else "-"
            url, _ = _fund_links(item["code"])
            parts.append(
                f"| [{item['name']}]({url}) | `{score}` | {level} | {quality} |"
            )
        parts.append("")

    for item in results:
        parts.extend(
            [
                "---",
                "",
                _format_scored(item)
                if item.get("total_score") is not None
                else _format_unscorable(item),
                "",
            ]
        )

    parts.extend(
        [
            "---",
            "",
            "📝 *观察分仅用于研究排序，不是收益预测或操作指令。请独立判断风险。*",
        ]
    )
    return title, "\n".join(parts)
