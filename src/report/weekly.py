"""Weekly observation trends and prospective outcome evidence."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from src.config import Config
from src.db import get_conn
from src.evaluation.outcomes import load_outcome_summary

LEVEL_LABELS = {
    "high_attention": "高关注",
    "attention": "较高关注",
    "neutral": "中性观察",
    "caution": "谨慎观察",
    "low_attention": "低关注",
    "strong_buy": "高关注",
    "buy": "较高关注",
    "watch": "谨慎观察",
    "avoid": "低关注",
}


def _spark(scores: list[float]) -> str:
    if not scores:
        return ""
    bars = "▁▂▃▄▅▆▇█"
    low, high = min(scores), max(scores)
    span = high - low if high != low else 1
    return "".join(
        bars[min(7, int((score - low) / span * 7))] for score in scores
    )


def _direction(scores: list[float]) -> str:
    if len(scores) < 2:
        return "→"
    difference = scores[-1] - scores[0]
    if difference > 5:
        return "↗"
    if difference < -5:
        return "↘"
    return "→"


def render_weekly_report(cfg: Config) -> tuple[str, str]:
    today = date.today()
    week_start = today - timedelta(days=6)
    title = f"📈 基金观察周报 · {week_start} ~ {today}"
    with get_conn(cfg.db_path) as conn:
        frame = pd.read_sql(
            """
            SELECT code, score_date, total_score,
                   COALESCE(observation_level, recommendation) AS level,
                   COALESCE(quality_status, 'legacy') AS quality_status,
                   reason
            FROM daily_scores
            WHERE score_date >= ? AND score_date <= ?
            ORDER BY code, score_date
            """,
            conn,
            params=(week_start.isoformat(), today.isoformat()),
        )
    if frame.empty:
        return title, "本周无观察数据，请检查日报是否正常运行。"

    parts = [f"## {title}", "", "### 本周数据状态"]
    parts.append(f"- 监控基金：{frame['code'].nunique()} 只")
    parts.append(f"- 有效观察记录：{len(frame)} 条")
    degraded = int((frame["quality_status"] == "degraded").sum())
    parts.append(f"- 降级记录：{degraded} 条")
    parts.extend(["", "### 观察分趋势", ""])

    code_to_name = {fund.code: fund.name for fund in cfg.funds}
    for code, group in frame.groupby("code"):
        scores = group["total_score"].dropna().astype(float).tolist()
        if not scores:
            continue
        name = code_to_name.get(code, code)
        latest = group.dropna(subset=["total_score"]).iloc[-1]
        level = LEVEL_LABELS.get(latest["level"], latest["level"])
        parts.append(f"**{name} (`{code}`)** {_spark(scores)} {_direction(scores)}")
        parts.append("- 观察分：" + " → ".join(f"{score:.0f}" for score in scores))
        parts.append(
            f"- 最新：{latest['score_date']} · {latest['total_score']:.0f}分 · {level}"
        )
        if latest.get("reason"):
            parts.append(f"- 事件摘要：{latest['reason']}")
        parts.append("")

    parts.extend(["### 结果证据", ""])
    summary = load_outcome_summary(cfg)
    if not summary:
        parts.append("> 尚无到期样本。系统会在观察记录满5/20/60个交易日后自动评价。")
    else:
        for item in summary:
            label = LEVEL_LABELS.get(
                item["observation_level"], item["observation_level"]
            )
            prefix = f"- {label} · {item['horizon_days']}日：样本 {item['sample_count']}"
            if item["evidence_sufficient"]:
                parts.append(
                    prefix
                    + f"，平均超额 {item['mean_excess_pct']:+.2f}%"
                    + f"，中位超额 {item['median_excess_pct']:+.2f}%"
                    + f"，跑赢比例 {item['beat_rate_pct']:.1f}%"
                )
            else:
                parts.append(prefix + "，证据不足（至少需要30条）")

    parts.extend(
        [
            "",
            "---",
            "> 观察分仅用于研究排序，不是收益预测或操作指令。",
        ]
    )
    return title, "\n".join(parts)
