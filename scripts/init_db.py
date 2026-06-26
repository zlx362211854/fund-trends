"""初始化数据库。可重复执行。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config
from src.db import init_db


def main() -> None:
    cfg = load_config()
    init_db(cfg.db_path)
    print(f"[OK] 数据库已初始化:{cfg.db_path}")


if __name__ == "__main__":
    main()
