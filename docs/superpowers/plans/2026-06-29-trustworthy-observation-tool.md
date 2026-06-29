# Trustworthy Observation Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the existing recommendation-style fund monitor into a versioned, auditable observation tool with explicit data quality and prospective 5/20/60-day benchmark evaluation.

**Architecture:** Keep fetchers and pure score functions, add independent quality and outcome modules, and make the orchestration layer compose only available dimensions. Extend SQLite through idempotent migrations, then expose the new semantics through the existing Markdown and Pillow reports.

**Tech Stack:** Python 3.11+, SQLite, pandas, numpy, OpenAI-compatible API, Pillow, pytest.

---

## File Map

- `src/config.py`: quality thresholds and scoring version configuration.
- `src/db.py`: idempotent migrations, source status and outcome tables.
- `src/data/status.py`: source refresh status writes and reads.
- `src/quality.py`: pure data-quality assessment and observation-score composition.
- `src/scoring/event.py`: validated, auditable event result.
- `src/agents/tools.py`: collect quality inputs, compose observations and persist snapshots.
- `src/agents/pipeline.py`: pass refresh state through analysis and update mature outcomes.
- `src/evaluation/outcomes.py`: calculate and aggregate 5/20/60-day excess returns.
- `scripts/run_backtest.py`: manually recalculate all mature outcomes.
- `src/report/daily.py`, `src/report/image.py`, `src/report/verdict.py`, `src/report/weekly.py`: observation-only reporting.
- `tests/`: unit, migration, report and integration coverage with no live network calls.

### Task 1: Test Baseline and Quality Configuration

**Files:**
- Modify: `requirements.txt`
- Modify: `src/config.py`
- Modify: `config.yaml.example`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing configuration tests**

```python
from src.config import QualityConfig, ScoringConfig


def test_quality_defaults_cover_non_trading_days():
    quality = QualityConfig()
    assert quality.max_nav_age_days == 7
    assert quality.max_market_age_days == 7
    assert quality.max_holdings_age_days == 180
    assert quality.max_news_refresh_age_days == 3
    assert quality.min_nav_rows == 60


def test_scoring_has_stable_version():
    assert ScoringConfig().version == "observation-v1"
```

- [ ] **Step 2: Run the tests and confirm the missing types fail**

Run: `pytest tests/test_config.py -v`
Expected: collection fails because `QualityConfig` and `ScoringConfig.version` do not exist.

- [ ] **Step 3: Add configuration dataclasses and parser wiring**

```python
@dataclass
class QualityConfig:
    max_nav_age_days: int = 7
    max_market_age_days: int = 7
    max_holdings_age_days: int = 180
    max_news_refresh_age_days: int = 3
    min_nav_rows: int = 60


@dataclass
class ScoringConfig:
    weights: ScoringWeights = field(default_factory=ScoringWeights)
    thresholds: ScoringThresholds = field(default_factory=ScoringThresholds)
    version: str = "observation-v1"
```

Add `quality: QualityConfig` to `Config`, parse `quality` and `scoring.version` in `load_config`, document the keys in `config.yaml.example`, and add `pytest>=8.0.0` to `requirements.txt`.

- [ ] **Step 4: Run the configuration tests**

Run: `pytest tests/test_config.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt src/config.py config.yaml.example tests/test_config.py
git commit -m "test: establish observation quality configuration"
```

### Task 2: Idempotent Database Migration and Source Status

**Files:**
- Modify: `src/db.py`
- Create: `src/data/status.py`
- Create: `tests/test_db_migrations.py`

- [ ] **Step 1: Write migration and status tests**

```python
import sqlite3

from src.data.status import record_source_attempt, load_source_status
from src.db import init_db


def test_init_db_is_idempotent_and_adds_observation_schema(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    init_db(path)
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(daily_scores)")}
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"observation_level", "quality_status", "quality_json", "scoring_version"} <= columns
    assert {"data_source_status", "signal_outcomes"} <= tables


def test_source_status_preserves_last_success_on_failure(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    record_source_attempt(path, "fund_nav", "000001", True, 10, "2026-06-26")
    record_source_attempt(path, "fund_nav", "000001", False, 0, None, "timeout")
    status = load_source_status(path, "fund_nav", "000001")
    assert status["last_success_at"] is not None
    assert status["last_error"] == "timeout"
```

- [ ] **Step 2: Run the tests and confirm schema/status failures**

Run: `pytest tests/test_db_migrations.py -v`
Expected: failures for missing columns, tables and `src.data.status`.

- [ ] **Step 3: Implement migrations and status access**

Add `data_source_status` with primary key `(source, subject)`, attempt/success timestamps, row count, latest data date and error. Add `signal_outcomes` with unique `(code, signal_date, scoring_version, horizon_days)`. Add a `_ensure_column` helper based on `PRAGMA table_info` and call it from `init_db` for the four new `daily_scores` columns.

Implement `record_source_attempt(db_path, source, subject, success, row_count=0,
latest_data_date=None, error=None)` and
`load_source_status(db_path, source, subject)`. The first function returns `None`;
the second returns the matching row as a dictionary or `None` when no attempt has
been recorded.

The UPSERT always updates attempt state, only replaces `last_success_at`, `row_count` and `latest_data_date` on success, and stores the latest error on failure.

- [ ] **Step 4: Run migration tests**

Run: `pytest tests/test_db_migrations.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/db.py src/data/status.py tests/test_db_migrations.py
git commit -m "feat: add auditable data status schema"
```

### Task 3: Quality Assessment and Observation Composition

**Files:**
- Create: `src/quality.py`
- Create: `tests/test_quality.py`

- [ ] **Step 1: Write quality and composition tests**

```python
from datetime import date

from src.config import QualityConfig, ScoringThresholds, ScoringWeights
from src.quality import assess_quality, compose_observation


def test_stale_nav_is_unscorable():
    result = assess_quality(
        as_of=date(2026, 6, 29), nav_rows=250, nav_date="2026-06-01",
        market_date="2026-06-27", holdings_date="2026-03-31",
        news_refresh_date="2026-06-29", event_available=True,
        config=QualityConfig(),
    )
    assert result.status == "unscorable"
    assert "nav_stale" in result.issues


def test_missing_event_reweights_available_dimensions():
    result = compose_observation(
        {"technical": 80.0, "valuation": 40.0, "event": None},
        ScoringWeights(), ScoringThresholds(),
    )
    assert result.score == 62.9
    assert result.level == "neutral"
    assert result.used_dimensions == ["technical", "valuation"]
```

- [ ] **Step 2: Run tests and confirm module failure**

Run: `pytest tests/test_quality.py -v`
Expected: collection fails because `src.quality` does not exist.

- [ ] **Step 3: Implement pure quality and composition models**

```python
@dataclass
class QualityResult:
    status: Literal["reliable", "degraded", "unscorable"]
    issues: list[str]
    data_dates: dict[str, str | None]


@dataclass
class ObservationResult:
    score: float | None
    level: str | None
    used_dimensions: list[str]


LEVELS = (
    ("high_attention", "strong_buy"),
    ("attention", "buy"),
    ("neutral", "neutral"),
    ("caution", "avoid"),
)
```

`assess_quality` checks row count and date ages, making only invalid NAV critical. Missing/old optional data and unavailable events produce `degraded`. `compose_observation` rejects an unavailable technical dimension, normalizes configured weights over available dimensions, rounds to one decimal, and maps the existing thresholds to the five new levels.

- [ ] **Step 4: Run quality tests**

Run: `pytest tests/test_quality.py -v`
Expected: tests pass, including exact reweighted score `62.9`.

- [ ] **Step 5: Commit**

```bash
git add src/quality.py tests/test_quality.py
git commit -m "feat: assess data quality and compose observation scores"
```

### Task 4: Validate and Audit LLM Event Results

**Files:**
- Modify: `src/scoring/event.py`
- Create: `tests/scoring/test_event.py`

- [ ] **Step 1: Write event validation tests**

```python
import pytest

from src.scoring.event import parse_event_response


def test_parse_event_response_clamps_nothing_and_rejects_out_of_range():
    with pytest.raises(ValueError, match="score"):
        parse_event_response('{"score": 130, "reason": "x", "risks": []}')


def test_parse_event_response_requires_string_risks():
    with pytest.raises(ValueError, match="risks"):
        parse_event_response('{"score": 50, "reason": "x", "risks": [1]}')


def test_parse_event_response_returns_auditable_result():
    result = parse_event_response('{"score": 55, "reason": "消息影响有限", "risks": []}')
    assert result.available is True
    assert result.score == 55
```

- [ ] **Step 2: Run tests and confirm parser failure**

Run: `pytest tests/scoring/test_event.py -v`
Expected: import fails because `parse_event_response` does not exist.

- [ ] **Step 3: Implement strict parser and unavailable state**

Extend `EventScore` with `available`, `status`, `model`, `generated_at` and `evidence`. Implement `parse_event_response` using explicit JSON/type/range/length validation. Change API exceptions and validation errors to return an unavailable `EventScore` whose score is `None`, status is `error`, reason contains the failure category, risks is empty, and audit fields retain model/evidence. Change valid no-news input to `score=50`, `available=True`, `status="no_material_news"`.

Replace prompt language about “加仓决策” with “当前观察优先级”, forbid operation instructions and future-price predictions, and pass news evidence dictionaries containing source, title, publish time and URL.

- [ ] **Step 4: Run event tests**

Run: `pytest tests/scoring/test_event.py -v`
Expected: all parser tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/scoring/event.py tests/scoring/test_event.py
git commit -m "feat: validate and audit event analysis"
```

### Task 5: Integrate Quality Into Refresh and Scoring Pipeline

**Files:**
- Modify: `src/agents/tools.py`
- Modify: `src/agents/pipeline.py`
- Create: `tests/agents/test_tools.py`
- Create: `tests/agents/test_pipeline.py`

- [ ] **Step 1: Write integration tests with local sample frames**

```python
def test_score_fund_marks_missing_event_as_degraded(config, seeded_db, monkeypatch):
    monkeypatch.setattr("src.agents.tools.compute_event_score", unavailable_event)
    result = tool_score_fund(config, config.funds[0])
    assert result["quality"]["status"] == "degraded"
    assert result["observation_level"] is not None
    assert "event" not in result["observation"]["used_dimensions"]


def test_pipeline_keeps_unscorable_funds(config, monkeypatch):
    monkeypatch.setattr("src.agents.pipeline.run_data_agent", lambda cfg: {})
    monkeypatch.setattr("src.agents.pipeline.tool_score_fund", lambda cfg, fund: unscorable_result(fund))
    results = run_pipeline(config)
    assert len(results) == len(config.funds)
    assert results[0]["total_score"] is None
```

- [ ] **Step 2: Run integration tests and confirm failures**

Run: `pytest tests/agents -v`
Expected: failures because scoring does not expose quality/observation fields and pipeline drops failed results.

- [ ] **Step 3: Record refresh state and compose observations**

Wrap every fund, market and news refresh result with `record_source_attempt`. In `tool_score_fund`, load the latest dates, assess quality, compute only valid dimensions, compose the observation, and produce:

```python
{
    "total_score": observation.score,
    "observation_level": observation.level,
    "quality": asdict(quality),
    "scoring_version": cfg.scoring.version,
    "observation": asdict(observation),
}
```

Persist the new columns and retain a compatible non-null `recommendation` value. For an unscorable fund use `recommendation="unscorable"`, null component/total values in the result, and skip persistence because the legacy table requires a non-null total. Return it to the report with its quality reasons. Sort scored results first and unscorable results last.

- [ ] **Step 4: Run agent tests**

Run: `pytest tests/agents -v`
Expected: all tests pass without network access.

- [ ] **Step 5: Commit**

```bash
git add src/agents/tools.py src/agents/pipeline.py tests/agents
git commit -m "feat: integrate quality-aware observation scoring"
```

### Task 6: Prospective Signal Outcome Evaluation

**Files:**
- Create: `src/evaluation/__init__.py`
- Create: `src/evaluation/outcomes.py`
- Create: `scripts/run_backtest.py`
- Modify: `src/agents/pipeline.py`
- Create: `tests/evaluation/test_outcomes.py`

- [ ] **Step 1: Write deterministic outcome tests**

```python
import pandas as pd

from src.evaluation.outcomes import interval_return, qdii_benchmark_return


def test_interval_return_uses_horizon_trading_row():
    values = pd.DataFrame({"trade_date": ["2026-01-01", "2026-01-02", "2026-01-05"], "value": [100, 105, 110]})
    assert interval_return(values, "2026-01-01", 2) == ("2026-01-05", 10.0)


def test_qdii_benchmark_combines_index_and_fx():
    assert qdii_benchmark_return(100, 110, 7.0, 7.07) == 11.1
```

- [ ] **Step 2: Run tests and confirm module failure**

Run: `pytest tests/evaluation/test_outcomes.py -v`
Expected: collection fails because `src.evaluation.outcomes` does not exist.

- [ ] **Step 3: Implement outcome calculation and aggregation**

Define `HORIZONS = (5, 20, 60)`,
`update_mature_outcomes(cfg, as_of=None) -> int`, and
`load_outcome_summary(cfg, min_samples=30) -> list[dict]` as the module's public
API.

Read scored `daily_scores` records by `scoring_version`, skip existing outcomes, use fund NAV rows to determine maturity, then compute HS300 or NDX-times-FX returns. Store fund return, benchmark return, excess return, end date and evaluation timestamp. Aggregate by version, level and horizon using count, mean, median and positive-excess rate; include `evidence_sufficient = count >= min_samples`.

Call `update_mature_outcomes` after scoring with error isolation. Add `scripts/run_backtest.py` to initialize the DB, run the update and print the number of newly evaluated outcomes.

- [ ] **Step 4: Run evaluation tests**

Run: `pytest tests/evaluation/test_outcomes.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/evaluation scripts/run_backtest.py src/agents/pipeline.py tests/evaluation
git commit -m "feat: evaluate observation outcomes against benchmarks"
```

### Task 7: Replace Recommendation Reporting

**Files:**
- Modify: `src/report/verdict.py`
- Modify: `src/report/daily.py`
- Modify: `src/report/image.py`
- Modify: `src/report/weekly.py`
- Create: `tests/report/test_reports.py`

- [ ] **Step 1: Write report semantics tests**

```python
from src.report.daily import render_daily_report


FORBIDDEN = ("加仓", "梭哈", "闭眼买", "捡钱", "上车", "接盘")


def test_daily_report_uses_observation_language(sample_result):
    title, body = render_daily_report([sample_result])
    assert "观察分" in body
    assert "数据可信度" in body
    assert "估值代理" in body
    assert "不是收益预测或操作指令" in body
    assert not any(term in title + body for term in FORBIDDEN)


def test_unscorable_result_remains_visible(unscorable_result):
    _, body = render_daily_report([unscorable_result])
    assert "不可评分" in body
    assert "净值数据过期" in body
```

- [ ] **Step 2: Run tests and confirm old copy fails**

Run: `pytest tests/report/test_reports.py -v`
Expected: failures because existing reports use recommendation language and omit quality status.

- [ ] **Step 3: Implement observation-only Markdown and image copy**

Replace verdict pools with factual descriptions for each observation level. Rename all labels and section headings. Add quality badge, issue list, data dates, proxy method, scoring version and evidence links. Render unscorable cards without score bars. In the image, use stable card dimensions and `观察分`/`数据可靠`/`数据降级` labels, with no operation language.

Update weekly report to call `load_outcome_summary`, render only evidence-backed statistics when `evidence_sufficient` is true, and otherwise render the exact sample count plus “证据不足（至少需要 30 条）”.

- [ ] **Step 4: Run report tests and render a fixture image**

Run: `pytest tests/report/test_reports.py -v`
Expected: all report semantics tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/report tests/report
git commit -m "feat: report observations with quality and evidence"
```

### Task 8: Documentation and End-to-End Verification

**Files:**
- Modify: `README.md`
- Create: `tests/test_daily_integration.py`

- [ ] **Step 1: Add a no-network end-to-end test**

The test initializes a temporary database, seeds fixed NAV/market/news rows, replaces the LLM call with a fixed valid `EventScore`, runs analysis, renders Markdown and a PNG, and asserts the output file is non-empty.

```python
def test_fixed_data_generates_observation_report_and_png(tmp_path, configured_db, monkeypatch):
    results = run_analysis_agent(configured_db)
    title, body = render_daily_report(results)
    output = tmp_path / "daily.png"
    render_dashboard(results, output)
    assert "观察分" in body
    assert output.stat().st_size > 10_000
```

- [ ] **Step 2: Update README and configuration guidance**

Document the personal research positioning, observation semantics, quality statuses, `python scripts/run_backtest.py`, evidence threshold, and the fact that current valuation is proxy-based. Remove roadmap items completed by this phase and retain true valuation as later work.

- [ ] **Step 3: Run the complete automated suite**

Run: `pytest -q`
Expected: all tests pass.

Run: `python -m compileall -q src scripts`
Expected: exit code 0 with no output.

Run: `git diff --check`
Expected: exit code 0 with no output.

- [ ] **Step 4: Render and inspect the fixture dashboard**

Run: `pytest tests/test_daily_integration.py -v`
Expected: the test writes a valid non-empty PNG. Open the generated fixture and verify that observation score, quality status and disclaimer are legible with no overlap.

- [ ] **Step 5: Commit**

```bash
git add README.md tests/test_daily_integration.py docs/superpowers/plans/2026-06-29-trustworthy-observation-tool.md
git commit -m "docs: complete trustworthy observation workflow"
```
