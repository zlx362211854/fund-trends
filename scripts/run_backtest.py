"""Recalculate all matured prospective observation outcomes."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config
from src.db import init_db
from src.evaluation.outcomes import update_mature_outcomes


def main() -> int:
    cfg = load_config()
    init_db(cfg.db_path)
    count = update_mature_outcomes(cfg)
    print(f"新增到期结果: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
