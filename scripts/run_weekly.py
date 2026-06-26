"""每周五 17:00 执行:汇总本周打分 → 推送周报"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from src.config import load_config
from src.db import init_db
from src.push.serverchan import push
from src.report.weekly import render_weekly_report


def main() -> int:
    cfg = load_config()
    init_db(cfg.db_path)

    logger.add(cfg.log_path, rotation="10 MB", retention="30 days", level=cfg.log_level)
    logger.info("====== Weekly run start ======")

    title, body = render_weekly_report(cfg)
    ok = push(cfg, title, body, push_type="weekly")
    logger.info(f"====== Weekly run done: push={'OK' if ok else 'FAIL'} ======")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
