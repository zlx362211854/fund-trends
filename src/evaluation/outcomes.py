"""Evaluate matured observation scores without reconstructing historical signals."""
from __future__ import annotations

from datetime import date
import json
from statistics import median

import pandas as pd
from loguru import logger

from src.config import Config
from src.db import get_conn

HORIZONS = (5, 20, 60)


def interval_return(
    values: pd.DataFrame, start_date: str, horizon_days: int
) -> tuple[str, float] | None:
    usable = values[values["trade_date"] >= start_date].sort_values("trade_date")
    if len(usable) <= horizon_days:
        return None
    start_value = float(usable.iloc[0]["value"])
    end_row = usable.iloc[horizon_days]
    if start_value == 0:
        return None
    return str(end_row["trade_date"]), round(
        (float(end_row["value"]) / start_value - 1) * 100, 4
    )


def qdii_benchmark_return(
    index_start: float,
    index_end: float,
    fx_start: float,
    fx_end: float,
) -> float:
    if index_start == 0 or fx_start == 0:
        raise ValueError("benchmark start values must be non-zero")
    return round(
        ((index_end / index_start) * (fx_end / fx_start) - 1) * 100,
        4,
    )


def _load_values(
    cfg: Config,
    table: str,
    value_column: str,
    where_column: str,
    subject: str,
    start_date: str,
    as_of: date,
) -> pd.DataFrame:
    with get_conn(cfg.db_path) as conn:
        frame = pd.read_sql(
            f"SELECT trade_date, {value_column} AS value FROM {table} "
            f"WHERE {where_column} = ? AND trade_date >= ? AND trade_date <= ? "
            "ORDER BY trade_date",
            conn,
            params=(subject, start_date, as_of.isoformat()),
        )
    return frame


def _value_at_or_after(values: pd.DataFrame, target_date: str) -> float | None:
    usable = values[values["trade_date"] >= target_date].sort_values("trade_date")
    return float(usable.iloc[0]["value"]) if not usable.empty else None


def _benchmark_return(
    cfg: Config,
    fund_type: str,
    signal_date: str,
    end_date: str,
    as_of: date,
) -> float | None:
    if fund_type == "qdii_index":
        ndx = _load_values(
            cfg, "market_data", "close", "symbol", "NDX", signal_date, as_of
        )
        fx = _load_values(
            cfg, "market_data", "close", "symbol", "USDCNY", signal_date, as_of
        )
        if ndx.empty or fx.empty:
            return None
        ndx_start = _value_at_or_after(ndx, signal_date)
        ndx_end = _value_at_or_after(ndx, end_date)
        fx_start = _value_at_or_after(fx, signal_date)
        fx_end = _value_at_or_after(fx, end_date)
        if None in (ndx_start, ndx_end, fx_start, fx_end):
            return None
        return qdii_benchmark_return(ndx_start, ndx_end, fx_start, fx_end)

    benchmark = _load_values(
        cfg, "market_data", "close", "symbol", "HS300", signal_date, as_of
    )
    start_value = _value_at_or_after(benchmark, signal_date)
    end_value = _value_at_or_after(benchmark, end_date)
    if start_value is None or end_value is None or start_value == 0:
        return None
    return round((end_value / start_value - 1) * 100, 4)


def _signal_start_date(signal) -> str:
    try:
        snapshot = json.loads(signal["raw_json"] or "{}")
        nav_date = snapshot["quality"]["data_dates"]["nav"]
        return str(nav_date) if nav_date else signal["score_date"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return signal["score_date"]


def update_mature_outcomes(cfg: Config, as_of: date | None = None) -> int:
    evaluation_date = as_of or date.today()
    fund_types = {fund.code: fund.type for fund in cfg.funds}
    with get_conn(cfg.db_path) as conn:
        signals = conn.execute(
            """
            SELECT code, score_date, observation_level, scoring_version, raw_json,
                   long_term_score, long_term_level, timing_score, timing_level
            FROM daily_scores
            WHERE total_score IS NOT NULL
              AND scoring_version IS NOT NULL
            ORDER BY score_date
            """
        ).fetchall()

    inserted = 0
    for signal in signals:
        code = signal["code"]
        fund_type = fund_types.get(code)
        if fund_type is None:
            logger.warning(f"[outcome] 未配置基金 {code},跳过结果评价")
            continue
        start_date = _signal_start_date(signal)
        nav = _load_values(
            cfg,
            "fund_nav",
            "COALESCE(acc_nav, unit_nav)",
            "code",
            code,
            start_date,
            evaluation_date,
        )
        if signal["scoring_version"] == "observation-v2":
            dimensions = [
                ("long_term", signal["long_term_score"], signal["long_term_level"]),
                ("timing", signal["timing_score"], signal["timing_level"]),
            ]
        else:
            dimensions = [
                ("legacy", 1.0, signal["observation_level"]),
            ]

        for dimension, score, level in dimensions:
            if score is None or level is None:
                continue
            for horizon in HORIZONS:
                table = (
                    "score_outcomes_v2"
                    if dimension != "legacy"
                    else "signal_outcomes"
                )
                with get_conn(cfg.db_path) as conn:
                    if dimension == "legacy":
                        exists = conn.execute(
                            """
                            SELECT 1 FROM signal_outcomes
                            WHERE code = ? AND signal_date = ?
                              AND scoring_version = ? AND horizon_days = ?
                            """,
                            (
                                code,
                                signal["score_date"],
                                signal["scoring_version"],
                                horizon,
                            ),
                        ).fetchone()
                    else:
                        exists = conn.execute(
                            """
                            SELECT 1 FROM score_outcomes_v2
                            WHERE code = ? AND signal_date = ?
                              AND scoring_version = ? AND dimension = ?
                              AND horizon_days = ?
                            """,
                            (
                                code,
                                signal["score_date"],
                                signal["scoring_version"],
                                dimension,
                                horizon,
                            ),
                        ).fetchone()
                if exists:
                    continue
                matured = interval_return(nav, start_date, horizon)
                if matured is None:
                    continue
                end_date, fund_return = matured
                benchmark_return = _benchmark_return(
                    cfg, fund_type, start_date, end_date, evaluation_date
                )
                if benchmark_return is None:
                    continue
                excess = round(fund_return - benchmark_return, 4)
                with get_conn(cfg.db_path) as conn:
                    if table == "signal_outcomes":
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO signal_outcomes(
                                code, signal_date, scoring_version,
                                observation_level, horizon_days, start_date,
                                end_date, fund_return_pct, benchmark_return_pct,
                                excess_return_pct, beat_benchmark
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                code,
                                signal["score_date"],
                                signal["scoring_version"],
                                level,
                                horizon,
                                start_date,
                                end_date,
                                fund_return,
                                benchmark_return,
                                excess,
                                int(excess > 0),
                            ),
                        )
                    else:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO score_outcomes_v2(
                                code, signal_date, scoring_version, dimension,
                                level, horizon_days, start_date, end_date,
                                fund_return_pct, benchmark_return_pct,
                                excess_return_pct, beat_benchmark
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                code,
                                signal["score_date"],
                                signal["scoring_version"],
                                dimension,
                                level,
                                horizon,
                                start_date,
                                end_date,
                                fund_return,
                                benchmark_return,
                                excess,
                                int(excess > 0),
                            ),
                        )
                    inserted += conn.total_changes
    return inserted


def load_outcome_summary(
    cfg: Config, min_samples: int = 30
) -> list[dict]:
    with get_conn(cfg.db_path) as conn:
        if cfg.scoring.version == "observation-v2":
            rows = conn.execute(
                """
                SELECT scoring_version, dimension, level, horizon_days,
                       excess_return_pct, beat_benchmark
                FROM score_outcomes_v2
                WHERE scoring_version = ?
                ORDER BY dimension, level, horizon_days
                """,
                (cfg.scoring.version,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT scoring_version, 'legacy' AS dimension,
                       observation_level AS level, horizon_days,
                       excess_return_pct, beat_benchmark
                FROM signal_outcomes
                WHERE scoring_version = ?
                ORDER BY observation_level, horizon_days
                """,
                (cfg.scoring.version,),
            ).fetchall()
    groups: dict[tuple[str, str, str, int], list] = {}
    for row in rows:
        key = (
            row["scoring_version"],
            row["dimension"],
            row["level"],
            int(row["horizon_days"]),
        )
        groups.setdefault(key, []).append(row)

    summary: list[dict] = []
    for (version, dimension, level, horizon), items in groups.items():
        excess = [float(item["excess_return_pct"]) for item in items]
        count = len(items)
        summary.append(
            {
                "scoring_version": version,
                "dimension": dimension,
                "observation_level": level,
                "horizon_days": horizon,
                "sample_count": count,
                "mean_excess_pct": round(sum(excess) / count, 4),
                "median_excess_pct": round(median(excess), 4),
                "beat_rate_pct": round(
                    sum(int(item["beat_benchmark"]) for item in items)
                    / count
                    * 100,
                    1,
                ),
                "evidence_sufficient": count >= min_samples,
            }
        )
    return sorted(
        summary,
        key=lambda item: (
            item["dimension"],
            item["horizon_days"],
            item["observation_level"],
        ),
    )
