"""每个交易日早 8:00 执行:抓数据 → 打分 → 推送日报"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from src.agents.pipeline import run_pipeline
from src.config import PROJECT_ROOT, load_config
from src.db import init_db
from src.push.serverchan import push
from src.report.daily import render_daily_report
from src.report.image import render_dashboard


def main() -> int:
    cfg = load_config()
    init_db(cfg.db_path)

    logger.add(cfg.log_path, rotation="10 MB", retention="30 days", level=cfg.log_level)
    logger.info("====== Daily run start ======")

    results = run_pipeline(cfg)
    if not results:
        logger.error("无打分结果,放弃推送")
        return 1

    # 生成 Dashboard 图片
    img_path = PROJECT_ROOT / "data" / "reports" / f"{date.today().isoformat()}.png"
    try:
        render_dashboard(results, img_path)
        logger.success(f"Dashboard 已生成: {img_path}")
    except Exception as e:
        logger.error(f"图片生成失败,降级为纯文字: {e}")
        img_path = None

    title, body = render_daily_report(results)
    ok = push(cfg, title, body, push_type="daily", image_path=img_path)
    logger.info(f"====== Daily run done: push={'OK' if ok else 'FAIL'} ======")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
