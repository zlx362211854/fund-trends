"""日报模板 — Server酱 Markdown 渲染优化版"""
from __future__ import annotations

from datetime import date

REC_INFO = {
    "strong_buy": ("🟢", "强烈加仓"),
    "buy":        ("🟢", "可加仓"),
    "neutral":    ("🟡", "小幅 / 定投"),
    "watch":      ("🟠", "观望"),
    "avoid":      ("🔴", "暂不加仓"),
}

TYPE_TAG = {
    "domestic_active": "国内主动",
    "domestic_index":  "国内指数",
    "qdii_index":      "QDII 指数",
}


def _fund_links(code: str) -> tuple[str, str]:
    """返回 (天天基金详情, F10 资料)"""
    return (
        f"https://fund.eastmoney.com/{code}.html",
        f"https://fundf10.eastmoney.com/jbgk_{code}.html",
    )


def _badge(rec: str) -> str:
    emoji, label = REC_INFO.get(rec, ("⚪", rec))
    return f"{emoji} **{label}**"


def _fmt_fund_block(r: dict, rank: int) -> str:
    tech = r["technical"]
    val = r["valuation"]
    ev = r["event"]
    rec_emoji, rec_label = REC_INFO.get(r["recommendation"], ("⚪", r["recommendation"]))
    tag = TYPE_TAG.get(r.get("type", ""), "")

    lines: list[str] = []
    detail_url, f10_url = _fund_links(r["code"])

    # 标题:基金名 → 天天基金详情页
    lines.append(f"### {rec_emoji} [{r['name']}]({detail_url})")
    lines.append(f"`{r['code']}` · {tag} · [F10 资料]({f10_url})")
    lines.append("")

    # 顶部一行:综合分 + 三维子分
    lines.append(
        f"**综合 `{r['total_score']:.0f}/100`** · {rec_label}　　"
        f"📐 技术 `{tech['score']:.0f}`　"
        f"💰 估值 `{val['score']:.0f}`　"
        f"📰 事件 `{ev['score']:.0f}`"
    )
    lines.append("")

    # 关键指标
    lines.append("**📊 技术指标**")
    lines.append(
        f"- 近 1 年分位 `{tech['quantile_1y']*100:.0f}%`"
        f" · 回撤 `{tech['drawdown_pct']:.1f}%`"
    )
    lines.append(
        f"- 距 MA60 `{tech['ma60_dist_pct']:+.1f}%`"
        f" · RSI `{tech['rsi_14']:.0f}`"
    )
    lines.append("")

    # 市场状态(结构化事件)
    if r.get("market_events"):
        lines.append("**🌍 市场状态**")
        for ev_line in r["market_events"].split("\n"):
            if ev_line.strip():
                lines.append(f"- {ev_line.strip()}")
        lines.append("")

    # AI 评语(事件分理由)
    if ev.get("reason") and ev["reason"] not in ("无可用事件,中性", "无相关新闻,中性"):
        lines.append("**💡 AI 评语**")
        lines.append(f"> {ev['reason']}")
        news_cnt = r.get("related_news_count", 0)
        if news_cnt:
            lines.append(f"> 关联新闻 {news_cnt} 条")
        lines.append("")

    # 风险提示
    risks: list[str] = []
    if ev.get("risks"):
        risks.extend(ev["risks"])
    if not tech.get("trend_filter_passed", True):
        risks.append("短期趋势仍下行(反转过滤打折)")
    if risks:
        lines.append("**⚠️ 风险**")
        for risk in risks:
            lines.append(f"- {risk}")
        lines.append("")

    return "\n".join(lines).rstrip()


def render_daily_report(results: list[dict]) -> tuple[str, str]:
    """返回 (title, markdown_body)
    Server酱 会把 title 单独显示在顶部,所以正文不要重复 title。
    """
    today = date.today()
    weekday = ["一", "二", "三", "四", "五", "六", "日"][today.weekday()]
    title = f"📊 基金日报 · {today.strftime('%m-%d')}(周{weekday})"

    if not results:
        return title, "⚠️ 今日无打分结果,请检查数据抓取和日志。"

    parts: list[str] = []

    # 顶部 callout:今日最佳 + 全部基金一句话汇总
    top = results[0]
    top_emoji, top_label = REC_INFO.get(top["recommendation"], ("⚪", ""))
    parts.append(f"> {top_emoji} **今日最佳信号**")
    parts.append(f"> {top['name']}")
    parts.append(f"> 综合 `{top['total_score']:.0f}/100` · {top_label}")
    parts.append("")

    # 多只基金时给一个速览表
    if len(results) > 1:
        parts.append("**📋 全部基金速览**")
        parts.append("")
        parts.append("| # | 基金 | 综合 | 建议 |")
        parts.append("| :-: | :-- | :-: | :-- |")
        for i, r in enumerate(results, 1):
            emoji, label = REC_INFO.get(r["recommendation"], ("⚪", ""))
            short_name = r["name"] if len(r["name"]) <= 14 else r["name"][:14] + "…"
            detail_url, _ = _fund_links(r["code"])
            parts.append(
                f"| {i} | [{short_name}]({detail_url}) `{r['code']}` "
                f"| `{r['total_score']:.0f}` | {emoji} {label} |"
            )
        parts.append("")

    parts.append("---")
    parts.append("")

    # 每只基金详细块
    for i, r in enumerate(results, 1):
        parts.append(_fmt_fund_block(r, i))
        parts.append("")
        parts.append("---")
        parts.append("")

    # 页脚
    parts.append("📝 *本报告仅供参考,不构成投资建议*")

    return title, "\n".join(parts)
