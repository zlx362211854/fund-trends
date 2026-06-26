"""周报:本周打分趋势 + 信号回顾"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from src.config import Config
from src.db import get_conn


def _spark(scores: list[float]) -> str:
    """简易 ASCII 趋势线"""
    if not scores:
        return ""
    bars = "▁▂▃▄▅▆▇█"
    lo, hi = min(scores), max(scores)
    rng = hi - lo if hi != lo else 1
    return "".join(bars[min(7, int((s - lo) / rng * 7))] for s in scores)


def _direction(scores: list[float]) -> str:
    if len(scores) < 2:
        return "→"
    diff = scores[-1] - scores[0]
    if diff > 5:
        return "↗"
    if diff < -5:
        return "↘"
    return "→"


def render_weekly_report(cfg: Config) -> tuple[str, str]:
    today = date.today()
    week_start = today - timedelta(days=6)
    title = f"📈 基金周报 · {week_start} ~ {today}"

    with get_conn(cfg.db_path) as conn:
        df = pd.read_sql(
            "SELECT code, score_date, total_score, recommendation, reason "
            "FROM daily_scores WHERE score_date >= ? AND score_date <= ? "
            "ORDER BY code, score_date ASC",
            conn,
            params=(week_start.isoformat(), today.isoformat()),
        )

    if df.empty:
        return title, "本周无打分数据。请检查日报是否正常运行。"

    parts = [f"## {title}", ""]

    # 1. 综合
    buy_signals = (df["recommendation"].isin(["buy", "strong_buy"])).sum()
    avoid_signals = (df["recommendation"] == "avoid").sum()
    parts.append("### 🎯 本周综合")
    parts.append(f"- 监控基金:{df['code'].nunique()} 只")
    parts.append(f"- 出现可加仓信号:{buy_signals} 次")
    parts.append(f"- 出现暂不加仓信号:{avoid_signals} 次")
    parts.append("")

    # 2. 每只基金趋势
    parts.append("### 📊 每只基金趋势")
    parts.append("")
    code_to_name = {f.code: f.name for f in cfg.funds}
    for code, sub in df.groupby("code"):
        scores = sub["total_score"].astype(float).tolist()
        name = code_to_name.get(code, code)
        trend = " → ".join(f"{s:.0f}" for s in scores)
        spark = _spark(scores)
        direction = _direction(scores)
        peak_row = sub.loc[sub["total_score"].idxmax()]
        parts.append(f"**{name} ({code})** {spark} {direction}")
        parts.append(f"- 打分:{trend}")
        parts.append(
            f"- 峰值:{peak_row['score_date']} {peak_row['total_score']:.0f}分"
            f" → {peak_row['recommendation']}"
        )
        if peak_row.get("reason"):
            parts.append(f"- 关键事件:{peak_row['reason']}")
        parts.append("")

    # 3. 信号回顾(运行 >2 周后才有意义)
    parts.append("### 🔍 信号回顾")
    parts.append("> 累计样本不足,将在运行 4 周后启用回顾。")
    parts.append("")

    parts.append("---")
    parts.append("> 本报告仅供参考,不构成投资建议。")

    return title, "\n".join(parts)
