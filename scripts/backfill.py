"""首次部署:回填所有基金和市场数据的历史"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from src.config import load_config
from src.data.fund import (
    fetch_fund_holdings,
    fetch_fund_nav_history,
    save_holdings,
    save_nav,
)
from src.data.market import (
    fetch_nasdaq,
    fetch_usdcny,
    fetch_index_a,
    save_market,
)
from src.db import init_db


def main() -> None:
    cfg = load_config()
    init_db(cfg.db_path)
    logger.info(f"DB: {cfg.db_path}")

    # 1. 基金数据
    for fund in cfg.funds:
        try:
            nav = fetch_fund_nav_history(fund.code)
            n_nav = save_nav(cfg.db_path, fund.code, nav)
            logger.success(f"  净值 {fund.code} ({fund.name}): {n_nav} 条")
        except Exception as e:
            logger.error(f"  净值 {fund.code} 失败: {e}")

        try:
            holdings = fetch_fund_holdings(fund.code)
            n_h = save_holdings(cfg.db_path, fund.code, holdings)
            logger.success(f"  持仓 {fund.code}: {n_h} 条")
        except Exception as e:
            logger.error(f"  持仓 {fund.code} 失败: {e}")

    # 2. 市场数据
    try:
        save_market(cfg.db_path, "NDX", fetch_nasdaq())
        logger.success("  纳指 OK")
    except Exception as e:
        logger.error(f"  纳指失败: {e}")

    try:
        save_market(cfg.db_path, "USDCNY", fetch_usdcny())
        logger.success("  USD/CNY OK")
    except Exception as e:
        logger.error(f"  USD/CNY 失败: {e}")

    try:
        save_market(cfg.db_path, "HS300", fetch_index_a("sh000300"))
        logger.success("  沪深300 OK")
    except Exception as e:
        logger.error(f"  沪深300 失败: {e}")

    logger.info("回填完成")


if __name__ == "__main__":
    main()
