from src.agents.pipeline import run_analysis_agent, run_data_agent
from src.config import FundConfig


class FakeConfig:
    funds = [
        FundConfig("000001", "一号", "domestic_active"),
        FundConfig("000002", "二号", "domestic_active"),
    ]


def test_analysis_keeps_configured_order_without_blended_ranking(monkeypatch):
    def fake_score(cfg, fund):
        score = 80.0 if fund.code == "000002" else None
        return {
            "code": fund.code,
            "name": fund.name,
            "long_term": {"score": score, "level": "strong" if score else None},
            "timing": {"score": score, "level": "strong" if score else None},
            "quality": {
                "status": "reliable" if score is not None else "unscorable",
                "issues": [],
            },
        }

    monkeypatch.setattr("src.agents.pipeline.tool_score_fund", fake_score)
    results = run_analysis_agent(FakeConfig())

    assert [item["code"] for item in results] == ["000001", "000002"]


def test_news_refresh_failure_does_not_abort_data_agent(monkeypatch):
    class EmptyConfig:
        funds = []

    monkeypatch.setattr(
        "src.agents.pipeline.tool_refresh_market_data", lambda cfg: {}
    )
    monkeypatch.setattr(
        "src.agents.pipeline.tool_refresh_news",
        lambda cfg: (_ for _ in ()).throw(RuntimeError("news timeout")),
    )

    result = run_data_agent(EmptyConfig())

    assert result["news"] == {"error": "news timeout"}
