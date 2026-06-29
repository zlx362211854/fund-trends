import pandas as pd

from src.data.market import fetch_nasdaq


def test_nasdaq_fetch_uses_nasdaq_100_symbol(monkeypatch):
    called: list[str] = []

    def fake_fetch(symbol: str):
        called.append(symbol)
        return pd.DataFrame(
            {
                "date": ["2026-06-26", "2026-06-27"],
                "close": [25000.0, 25100.0],
            }
        )

    monkeypatch.setattr("src.data.market.ak.index_us_stock_sina", fake_fetch)

    result = fetch_nasdaq()

    assert called == [".NDX"]
    assert result["close"].tolist() == [25000.0, 25100.0]
