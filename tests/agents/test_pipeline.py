from src.agents.pipeline import run_analysis_agent
from src.config import FundConfig


class FakeConfig:
    funds = [
        FundConfig("000001", "一号", "domestic_active"),
        FundConfig("000002", "二号", "domestic_active"),
    ]


def test_analysis_keeps_and_sorts_unscorable_funds(monkeypatch):
    def fake_score(cfg, fund):
        score = 80.0 if fund.code == "000002" else None
        return {
            "code": fund.code,
            "name": fund.name,
            "total_score": score,
            "observation_level": "attention" if score is not None else None,
            "quality": {
                "status": "reliable" if score is not None else "unscorable",
                "issues": [],
            },
        }

    monkeypatch.setattr("src.agents.pipeline.tool_score_fund", fake_score)
    results = run_analysis_agent(FakeConfig())

    assert [item["code"] for item in results] == ["000002", "000001"]
