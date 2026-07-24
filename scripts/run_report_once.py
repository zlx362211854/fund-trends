"""Run a report only if today's successful push does not already exist."""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from src.config import load_config
from src.db import get_conn, init_db


def has_successful_push(db_path: str | Path, push_type: str, push_date: str) -> bool:
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM push_history "
            "WHERE push_type = ? AND push_date = ? AND success = 1 LIMIT 1",
            (push_type, push_date),
        ).fetchone()
    return row is not None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report_type", choices=("daily", "weekly"))
    args = parser.parse_args()

    cfg = load_config()
    init_db(cfg.db_path)
    today = date.today().isoformat()
    if has_successful_push(cfg.db_path, args.report_type, today):
        logger.info(f"{today} {args.report_type} already pushed successfully, skip")
        return 0

    if args.report_type == "weekly":
        from scripts.run_weekly import main as run_weekly

        return run_weekly()

    from scripts.run_daily import main as run_daily

    return run_daily()


if __name__ == "__main__":
    sys.exit(main())
