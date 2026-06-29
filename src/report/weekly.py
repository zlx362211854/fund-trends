"""Weekly dual-horizon trends and prospective outcome evidence."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from src.config import Config
from src.db import get_conn
from src.evaluation.outcomes import load_outcome_summary
from src.report.daily import LEVEL_LABELS

DIMENSION_LABELS = {
    "long_term": "长期持有条件",
    "timing": "当前投入时机",
    "legacy": "旧版观察分",
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
        if cfg.scoring.version == "observation-v2":
            frame = pd.read_sql(
                """
                SELECT code, score_date, long_term_score, long_term_level,
                       timing_score, timing_level,
                       COALESCE(quality_status, 'legacy') AS quality_status,
                       reason
                FROM daily_scores
                WHERE score_date >= ? AND score_date <= ?
                  AND scoring_version = ?
                ORDER BY code, score_date
                """,
                conn,
                params=(week_start.isoformat(), today.isoformat(), cfg.scoring.version),
            )
        else:
            frame = pd.read_sql(
                """
                SELECT code, score_date, total_score AS timing_score,
                       COALESCE(observation_level, recommendation) AS timing_level,
                       NULL AS long_term_score, NULL AS long_term_level,
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
    parts.append(f"- 观察记录：{len(frame)} 条")
    degraded = int((frame["quality_status"] == "degraded").sum())
    parts.append(f"- 降级记录：{degraded} 条")
    parts.extend(["", "### 双评分趋势", ""])

    code_to_name = {fund.code: fund.name for fund in cfg.funds}
    for code, group in frame.groupby("code"):
        name = code_to_name.get(code, code)
        parts.append(f"**{name} (`{code}`)**")
        for dimension, score_column, level_column in (
            ("long_term", "long_term_score", "long_term_level"),
            ("timing", "timing_score", "timing_level"),
        ):
            scores = group[score_column].dropna().astype(float).tolist()
            label = DIMENSION_LABELS[dimension]
            if not scores:
                parts.append(f"- {label}：暂不可评估")
                continue
            latest = group.dropna(subset=[score_column]).iloc[-1]
            level = LEVEL_LABELS.get(latest[level_column], latest[level_column])
            parts.append(
                f"- {label}：{_spark(scores)} {_direction(scores)} "
                f"最新 `{scores[-1]:.0f}` · {level}"
            )
        latest_reason = group.iloc[-1].get("reason")
        if latest_reason:
            parts.append(f"- AI事件摘要（不参与评分）：{latest_reason}")
        parts.append("")

    parts.extend(["### 结果证据", ""])
    summary = load_outcome_summary(cfg)
    if not summary:
        parts.append("> 尚无到期样本。系统会在记录满5/20/60个交易日后分别评价两项分数。")
    else:
        for item in summary:
            dimension = DIMENSION_LABELS.get(item["dimension"], item["dimension"])
            level = LEVEL_LABELS.get(
                item["observation_level"], item["observation_level"]
            )
            prefix = (
                f"- {dimension} · {level} · {item['horizon_days']}日："
                f"样本 {item['sample_count']}"
            )
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
            "> 双评分仅用于研究观察，不是收益预测或操作指令。",
        ]
    )
    return title, "\n".join(parts)
