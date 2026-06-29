from datetime import date, timedelta

import pandas as pd

from src.data.market import save_market
from src.data.market_events import build_market_events, format_events_for_llm
from src.db import init_db


def test_qdii_market_events_do_not_treat_one_year_high_as_bearish(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    today = date.today()
    dates = [
        (today - timedelta(days=offset)).isoformat()
        for offset in range(299, -1, -1)
    ]
    ndx = pd.DataFrame(
        {
            "trade_date": dates,
            "close": [20000 + index * 10 for index in range(300)],
            "daily_pct": [0.05] * 300,
        }
    )
    fx = pd.DataFrame(
        {
            "trade_date": dates,
            "close": [7.0 + index / 10000 for index in range(300)],
            "daily_pct": [0.01] * 300,
        }
    )
    save_market(path, "NDX", ndx)
    save_market(path, "USDCNY", fx)

    text = format_events_for_llm(build_market_events(path, "qdii_index"))

    assert "1 年分位" not in text
    assert "趋势偏离" in text
    assert "MA200" in text
