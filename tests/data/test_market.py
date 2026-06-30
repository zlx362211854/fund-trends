import pandas as pd

from src.data.market import fetch_nasdaq, fetch_usdcny


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


def test_usdcny_is_derived_from_ecb_reference_rates(monkeypatch):
    csv_text = """KEY,CURRENCY,TIME_PERIOD,OBS_VALUE
EXR.D.CNY.EUR.SP00.A,CNY,2026-06-25,8.1200
EXR.D.CNY.EUR.SP00.A,CNY,2026-06-26,8.1000
EXR.D.USD.EUR.SP00.A,USD,2026-06-25,1.1600
EXR.D.USD.EUR.SP00.A,USD,2026-06-26,1.1250
"""

    class Response:
        text = csv_text

        @staticmethod
        def raise_for_status():
            return None

    monkeypatch.setattr(
        "src.data.market.httpx.get", lambda *args, **kwargs: Response()
    )

    result = fetch_usdcny()

    assert result["trade_date"].tolist() == ["2026-06-25", "2026-06-26"]
    assert result["close"].round(4).tolist() == [7.0, 7.2]
