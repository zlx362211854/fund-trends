# Dual-Horizon Observation Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ambiguous single observation score with independently auditable long-term holding and current timing scores, backed by cached real index valuation data.

**Architecture:** Add a small valuation provider/cache boundary, two pure scoring modules, and a versioned result shape consumed by the existing pipeline and reports. Preserve `observation-v1` rows, keep LLM event analysis outside both numeric scores, and make each missing input explicit.

**Tech Stack:** Python 3, pandas, numpy, requests, SQLite, Pillow, pytest

---

## File Map

- Create `src/data/index_valuation.py`: fetch, validate, cache and load index valuation history.
- Create `src/scoring/common.py`: shared score levels and pure numeric helpers.
- Create `src/scoring/timing.py`: current timing factor calculation.
- Create `src/scoring/long_term.py`: long-term valuation, trend, risk and tracking calculation.
- Modify `src/config.py`: `observation-v2` defaults and valuation cache settings.
- Modify `src/db.py`: valuation cache and dual-score audit columns/tables.
- Modify `src/quality.py`: per-input quality states and independent score availability.
- Modify `src/agents/tools.py`: valuation refresh, benchmark construction, dual scoring and persistence.
- Modify `src/agents/pipeline.py`: dual-score logging and sorting.
- Modify `src/report/daily.py`, `src/report/image.py`, `src/report/weekly.py`: dual-score presentation.
- Modify `src/evaluation/outcomes.py`: dimension-aware outcome evaluation.
- Modify `config.yaml.example` and `README.md`: configuration and score semantics.
- Add focused tests under `tests/data`, `tests/scoring`, `tests/report` and existing integration/migration suites.

### Task 1: Configuration, Levels, and Database Contract

**Files:**
- Create: `src/scoring/common.py`
- Modify: `src/config.py`
- Modify: `src/db.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_db_migrations.py`

- [ ] **Step 1: Write failing configuration and migration tests**

```python
def test_v2_defaults_include_valuation_cache():
    scoring = ScoringConfig()
    assert scoring.version == "observation-v2"
    assert scoring.long_term_weights.valuation == 0.40
    assert scoring.timing_weights.deviation == 0.30
    assert scoring.max_valuation_age_days == 7


def test_migration_adds_dual_score_and_valuation_storage(tmp_path):
    path = tmp_path / "scores.db"
    init_db(path)
    init_db(path)
    with get_conn(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(daily_scores)")}
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert {"long_term_score", "long_term_level", "long_term_json",
            "timing_score", "timing_level", "timing_json"} <= columns
    assert {"index_valuations", "score_outcomes_v2"} <= tables
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `.venv/bin/pytest tests/test_config.py tests/test_db_migrations.py -q`

Expected: failures for missing v2 fields and tables.

- [ ] **Step 3: Add v2 configuration and score-level helper**

```python
@dataclass
class LongTermWeights:
    valuation: float = 0.40
    trend: float = 0.30
    risk: float = 0.20
    tracking: float = 0.10


@dataclass
class TimingWeights:
    trend: float = 0.30
    deviation: float = 0.30
    stabilization: float = 0.25
    temperature: float = 0.15


def score_level(score: float) -> str:
    if score >= 80:
        return "strong"
    if score >= 60:
        return "above_average"
    if score >= 40:
        return "neutral"
    if score >= 20:
        return "below_average"
    return "weak"
```

`ScoringConfig` receives both weight sets, `max_valuation_age_days=7`, `min_valuation_samples=60`, and defaults to `observation-v2`. Validate each weight set sums to one after YAML loading.

- [ ] **Step 4: Add idempotent schema changes**

Add dual-score columns to `DAILY_SCORE_COLUMNS`. Add `index_valuations` keyed by `(benchmark_code, metric, data_date)` and `score_outcomes_v2` keyed by `(code, signal_date, scoring_version, dimension, horizon_days)`. Keep all v1 columns and rows untouched.

- [ ] **Step 5: Run tests and commit**

Run: `.venv/bin/pytest tests/test_config.py tests/test_db_migrations.py -q`

Expected: all focused tests pass.

```bash
git add src/config.py src/db.py src/scoring/common.py tests/test_config.py tests/test_db_migrations.py
git commit -m "feat: add dual-score configuration and schema"
```

### Task 2: Lightweight Index Valuation Provider and Cache

**Files:**
- Create: `src/data/index_valuation.py`
- Create: `tests/data/test_index_valuation.py`
- Modify: `src/agents/tools.py`

- [ ] **Step 1: Write provider validation and cache tests**

```python
def test_parse_ndx_forward_pe_rejects_invalid_payload():
    with pytest.raises(ValuationDataError):
        parse_ndx_forward_pe({"updated": "2026-06-27", "forward": []})


def test_refresh_once_shares_cache_for_same_benchmark(tmp_path):
    calls = []
    payload = fixture_ndx_payload()
    provider = lambda: calls.append(1) or payload
    first = refresh_index_valuation(tmp_path / "db.sqlite", "NDX", provider)
    second = refresh_index_valuation(tmp_path / "db.sqlite", "NDX", provider)
    assert len(calls) == 1
    assert first.current_value == second.current_value == 24.29


def test_cache_older_than_seven_days_is_not_scoreable(tmp_path):
    snapshot = load_valuation_snapshot(
        tmp_path / "db.sqlite", "NDX", "forward_pe", date(2026, 7, 10), 7, 60
    )
    assert snapshot.available is False
    assert "valuation_stale" in snapshot.issues
```

- [ ] **Step 2: Run the new tests and verify failure**

Run: `.venv/bin/pytest tests/data/test_index_valuation.py -q`

Expected: import failure because the provider module does not exist.

- [ ] **Step 3: Implement the provider boundary**

Use one GET request to `https://historyofmarket.com/api/ndx/forward-pe.json` with a short timeout and explicit user agent. Parse `updated`, `current.forward`, and the `forward` history. Reject empty history, non-positive values, invalid dates, current/history mismatch, or fewer than configured samples.

```python
@dataclass(frozen=True)
class ValuationSnapshot:
    benchmark_code: str
    metric: str
    value: float | None
    percentile: float | None
    data_date: str | None
    source: str | None
    sample_count: int
    cache_status: str
    available: bool
    issues: list[str]
```

Persist every valid monthly history row in one transaction. Calculate the percentile from the latest 120 monthly observations to avoid the 2001-2003 earnings-denominator distortion dominating the current regime.

- [ ] **Step 4: Wire one valuation refresh per daily pipeline**

Add `tool_refresh_valuation_data(cfg)` beside market refresh. Derive the unique required benchmarks from configured fund types and refresh NDX once even when several QDII funds are configured. Record success/failure in `data_source_status` under source `index_valuation`.

- [ ] **Step 5: Run tests and commit**

Run: `.venv/bin/pytest tests/data/test_index_valuation.py tests/agents/test_tools.py -q`

Expected: all focused tests pass, including a single provider call for duplicate benchmarks.

```bash
git add src/data/index_valuation.py src/agents/tools.py tests/data/test_index_valuation.py tests/agents/test_tools.py
git commit -m "feat: cache lightweight index valuation data"
```

### Task 3: Pure Timing and Long-Term Scoring

**Files:**
- Create: `src/scoring/timing.py`
- Create: `src/scoring/long_term.py`
- Create: `tests/scoring/test_timing.py`
- Create: `tests/scoring/test_long_term.py`

- [ ] **Step 1: Write behavior-first timing tests**

```python
def test_steady_uptrend_is_not_penalized_for_new_high():
    result = compute_timing_score(price_frame(steady_growth(300)))
    assert result.score >= 40
    assert result.factors["trend"] >= 80


def test_sudden_spike_reduces_timing_but_not_trend():
    steady = compute_timing_score(price_frame(steady_growth(300)))
    spike = compute_timing_score(price_frame(steady_growth(295) + [140, 145, 150, 158, 165]))
    assert spike.factors["trend"] >= steady.factors["trend"]
    assert spike.score < steady.score


def test_falling_knife_scores_below_stabilized_drawdown():
    falling = compute_timing_score(price_frame(falling_series()))
    stabilized = compute_timing_score(price_frame(stabilized_series()))
    assert falling.factors["stabilization"] < 40
    assert stabilized.score > falling.score
```

- [ ] **Step 2: Write long-term availability and factor tests**

```python
def test_long_term_requires_real_valuation():
    result = compute_long_term_score(nav_frame(), benchmark_frame(), None)
    assert result.score is None
    assert "valuation_missing" in result.issues


def test_lower_valid_pe_percentile_improves_valuation_factor():
    low = compute_long_term_score(nav_frame(), benchmark_frame(), valuation(0.25))
    high = compute_long_term_score(nav_frame(), benchmark_frame(), valuation(0.85))
    assert low.factors["valuation"] > high.factors["valuation"]
```

- [ ] **Step 3: Run tests and verify failure**

Run: `.venv/bin/pytest tests/scoring/test_timing.py tests/scoring/test_long_term.py -q`

Expected: import failures for the missing scoring modules.

- [ ] **Step 4: Implement pure scoring functions**

`compute_timing_score` requires at least 220 valid observations. It calculates MA20/60/200, MA200 slope over 20 observations, annualized 60-day volatility, standardized MA distance, 250-day drawdown, RSI14, and 5/20-day returns. Drawdown only increases stabilization when MA20 is flat/rising and five-day decline has stopped.

`compute_long_term_score` requires a valid valuation snapshot, at least 252 benchmark observations and enough aligned fund/benchmark returns. It computes the fixed 40/30/20/10 weighted score and returns all raw metrics and factor scores.

```python
@dataclass
class HorizonScore:
    score: float | None
    level: str | None
    factors: dict[str, float]
    metrics: dict[str, float | str | None]
    issues: list[str]
```

Clamp every factor and final score to `0..100`; return explicit issues instead of neutral defaults for invalid or insufficient data.

- [ ] **Step 5: Run tests and commit**

Run: `.venv/bin/pytest tests/scoring/test_timing.py tests/scoring/test_long_term.py -q`

Expected: all scoring tests pass.

```bash
git add src/scoring/common.py src/scoring/timing.py src/scoring/long_term.py tests/scoring/test_timing.py tests/scoring/test_long_term.py
git commit -m "feat: add long-term and timing scores"
```

### Task 4: Pipeline, Quality, Persistence, and Outcomes

**Files:**
- Modify: `src/quality.py`
- Modify: `src/agents/tools.py`
- Modify: `src/agents/pipeline.py`
- Modify: `src/evaluation/outcomes.py`
- Modify: `tests/test_quality.py`
- Modify: `tests/agents/test_pipeline.py`
- Modify: `tests/evaluation/test_outcomes.py`

- [ ] **Step 1: Write failing integration tests for independent availability**

```python
def test_missing_valuation_keeps_timing_score(monkeypatch, configured_db):
    result = tool_score_fund(configured_db.cfg, configured_db.fund)
    assert result["long_term"]["score"] is None
    assert result["timing"]["score"] is not None
    assert result["quality"]["inputs"]["ndx_valuation"]["status"] == "missing"


def test_event_score_does_not_change_numeric_scores(monkeypatch, configured_db):
    first = tool_score_fund(configured_db.cfg, configured_db.fund)
    monkeypatch.setattr("src.agents.tools.compute_event_score", extreme_event_score)
    second = tool_score_fund(configured_db.cfg, configured_db.fund)
    assert first["long_term"]["score"] == second["long_term"]["score"]
    assert first["timing"]["score"] == second["timing"]["score"]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv/bin/pytest tests/test_quality.py tests/agents/test_pipeline.py tests/evaluation/test_outcomes.py -q`

Expected: failures because v1 result fields and outcome grouping are still used.

- [ ] **Step 3: Build benchmark series and v2 result shape**

For QDII, align NDX and USD/CNY by date and calculate `benchmark_value = ndx_close * fx_close`. For domestic funds use HS300. Produce:

```python
result = {
    "long_term": asdict(long_term),
    "timing": asdict(timing),
    "event": asdict(event),
    "quality": {"status": status, "inputs": inputs, "issues": issues},
    "scoring_version": "observation-v2",
}
```

Persist both score JSON payloads. Keep legacy `total_score` populated with the timing score only for the existing non-null database column; no v2 report or evaluator may label or consume it as a total score.

- [ ] **Step 4: Make outcomes dimension-aware**

Read v2 long-term and timing columns separately and write `dimension` as `long_term` or `timing` to `score_outcomes_v2`. Group summaries by `(scoring_version, dimension, level, horizon_days)` and preserve the 30-sample evidence gate.

- [ ] **Step 5: Run tests and commit**

Run: `.venv/bin/pytest tests/test_quality.py tests/agents/test_pipeline.py tests/evaluation/test_outcomes.py -q`

Expected: all focused tests pass.

```bash
git add src/quality.py src/agents/tools.py src/agents/pipeline.py src/evaluation/outcomes.py tests/test_quality.py tests/agents/test_pipeline.py tests/evaluation/test_outcomes.py
git commit -m "feat: integrate versioned dual-score observations"
```

### Task 5: Daily, Image, and Weekly Reports

**Files:**
- Modify: `src/report/daily.py`
- Modify: `src/report/image.py`
- Modify: `src/report/weekly.py`
- Modify: `src/report/verdict.py`
- Modify: `tests/report/test_reports.py`
- Modify: `tests/test_daily_integration.py`

- [ ] **Step 1: Replace report fixtures with v2 result shape**

```python
def test_daily_report_explains_both_scores_without_total_score():
    _, body = render_daily_report([sample_v2_result()])
    assert "长期持有" in body
    assert "当前投入时机" in body
    assert "前瞻PE" in body
    assert "观察总分" not in body
    assert "AI事件分析" in body


def test_missing_valuation_is_plainly_disclosed():
    result = sample_v2_result(long_term_score=None)
    _, body = render_daily_report([result])
    assert "长期持有分：暂不可评估" in body
    assert "纳指估值" in body
    assert "当前投入时机" in body
```

- [ ] **Step 2: Run report tests and verify failure**

Run: `.venv/bin/pytest tests/report/test_reports.py tests/test_daily_integration.py -q`

Expected: failures because the reports still render v1 total/technical/valuation/event bars.

- [ ] **Step 3: Render plain-language dual scores**

Replace the v1 total score header with two equal-weight visual rows. Show at most three drivers per horizon, exact source dates, valuation source and cache state. Keep event evidence in a separate section and retain the non-advice disclaimer.

Dashboard cards must use stable dimensions and include both scores even when one is unavailable. Weekly report shows separate long-term and timing trend lines and separate outcome evidence groups.

- [ ] **Step 4: Run report tests and inspect PNG**

Run: `.venv/bin/pytest tests/report/test_reports.py tests/test_daily_integration.py -q`

Run: `.venv/bin/python -m scripts.run_daily --help` only if the script supports dry-run; otherwise use the fixed integration fixture to write a temporary PNG.

Expected: report tests pass and PNG size exceeds 10 KB with no clipped score labels.

- [ ] **Step 5: Commit**

```bash
git add src/report/daily.py src/report/image.py src/report/weekly.py src/report/verdict.py tests/report/test_reports.py tests/test_daily_integration.py
git commit -m "feat: explain dual-horizon scores in reports"
```

### Task 6: Documentation and Full Verification

**Files:**
- Modify: `README.md`
- Modify: `config.yaml.example`
- Modify: `requirements.txt` only if the existing HTTP client dependency is absent.

- [ ] **Step 1: Update configuration example and README**

Document both score meanings, fixed default weights, the NDX forward-PE source and attribution, seven-day cache rule, unavailable behavior, `observation-v2` history boundary and expected 1C1G resource usage. Remove v1 examples that imply price percentile is valuation.

- [ ] **Step 2: Run placeholder and terminology scans**

Run: `rg -n "TODO|TBD|估值代理|近1年分位|观察总分|强烈加仓|闭眼买|梭哈" src README.md config.yaml.example tests`

Expected: no v2 user-facing price-percentile valuation or operational recommendation wording; legacy-only compatibility references are explicitly identified.

- [ ] **Step 3: Run full verification**

Run: `.venv/bin/pytest -q`

Expected: all tests pass.

Run: `.venv/bin/python -m compileall -q src scripts`

Expected: exit code 0 and no output.

Run: `git diff --check`

Expected: exit code 0 and no output.

- [ ] **Step 4: Verify current database migration on a copy**

Copy the current SQLite database to a temporary path, run `init_db` twice against the copy, and query the new columns/tables. Do not alter or delete the production database during this check.

- [ ] **Step 5: Commit documentation**

```bash
git add README.md config.yaml.example requirements.txt
git commit -m "docs: explain dual-horizon observation scores"
```

- [ ] **Step 6: Record final evidence**

Capture the final test count, compile result, generated report path, database migration result, `git status --short`, and the measured valuation request behavior for the completion summary.
