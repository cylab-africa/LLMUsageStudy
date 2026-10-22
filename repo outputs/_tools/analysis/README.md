# Cross-repo analysis layer (`_tools/analysis/`)

> **The report these scripts produce:**
> [`report/LLM_AI_Impact_Report_update (1).pdf`](../../../report/)
> — *AI Coding Agents and Software Development in MOSIP*, Upanzi Network,
> Carnegie Mellon University Africa. LaTeX source in
> [`repo outputs/paper/`](../../paper/).

`_tools/` proper produces **one report per repository**. These scripts sit on
top of that: they pool the per-repo reports into a panel and produce the
figures, statistics and tables that appear in that report.

Every number in the report comes from one of these scripts. If a table or
figure cannot be traced to a command below, treat that as a bug — it means
something was computed by hand and will drift.

## Setup

Run everything from the **repository root**; paths are relative to it.

```bash
cd "$(git rev-parse --show-toplevel)"
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python \
    "pandas==2.2.3" "numpy==1.26.4" matplotlib scipy statsmodels pymupdf
```

`pandas` and `numpy` are pinned to the versions the study was run with: pandas
3.x changes the `inplace`/copy-on-write semantics the upstream `scripts/*.py`
rely on. `statsmodels` is needed only for the ITS, `pymupdf` only for reading
PDFs.

## Pipeline

```
repo_report/*/  ──► build_panel.py ──► panel_ai_impact.csv ──┬─► figures
                                                             ├─► run_its.py
                                                             └─► run_statistics.py
clones/ ──► collect_branch_velocity.py ──► velocity_develop_monthly.csv
                                           branch_scope.csv
```

### 1. Build the panel

```bash
python "repo outputs/_tools/analysis/build_panel.py"
```

Reads every report directory whose `.batch_state.json` says `done`, so a
repository still being written is never half-read. Excludes the **current,
incomplete month** — a three-day stub month otherwise sits inside the short
post-adoption window and drags every post-period mean down. Override with
`AI_IMPACT_CUTOFF=YYYY-MM`.

Writes `analytics/panel_ai_impact.csv` and `analytics/repo_effects.csv`.

### 2. Branch-scope velocity — needs the clones

```bash
python "repo outputs/_tools/analysis/collect_branch_velocity.py" \
    --clones ~/aiimpact/repos --since 2025-01-01 --until 2026-09-01
```

The panel records **all-branch** activity only. This walks the clones directly
to produce velocity on the **integration branch** (`develop` where it exists,
else the repository default) and the per-branch commit counts behind the
branch-scope table.

Clone normally — `--single-branch` omits the remote refs this needs.

Writes `analytics/velocity_develop_monthly.csv` and `analytics/branch_scope.csv`.

### 3. Statistics

| Script | Produces |
|---|---|
| `run_its.py` | `its_results.csv` — interrupted time series, both branch scopes |
| `run_statistics.py` | paired Wilcoxon tests, Spearman correlations, diagnostics; writes `repo_intensity_vs_change.csv` |
| `review_breakdown.py` | `review_actor_monthly.csv` — reviews split AI / human / other-bot |

### 4. Figures

| Script | Produces | Used as |
|---|---|---|
| `plot_its.py` | `its_counterfactual.png` | ITS with counterfactual |
| `plot_eventstudy_raw.py` | `eventstudy_raw.png` | main event study (raw values) |
| `plot_per_repo_panels.py` | `permultiples_all_repos.png` | per-repository panel |
| `plot_review.py` | `review_practice.png` | review coverage, volume, actors |
| `plot_commit_size.py` | `eventstudy_commit_size.png` | lines per commit |
| `plot_eventstudy_coding.py` | `eventstudy_coding_v2.png` | normalised version, superseded |
| `plot_eventstudy_review.py` | `eventstudy_review.png`, `eventstudy_coding.png` | review-bot aligned, superseded |
| `plot_beforeafter_correlation.py` | `perrepo_beforeafter.png`, `intensity_correlation.png` | slopegraph, intensity scatter |

The last three are kept for comparison but are not the figures in the current
paper, which reports raw values throughout.

### Run everything

```bash
cd "$(git rev-parse --show-toplevel)"
P=".venv/bin/python"; A="repo outputs/_tools/analysis"
$P "$A/build_panel.py"
$P "$A/collect_branch_velocity.py" --clones ~/aiimpact/repos
$P "$A/review_breakdown.py"
$P "$A/run_its.py"
$P "$A/run_statistics.py"
for f in plot_its plot_eventstudy_raw plot_per_repo_panels plot_review plot_commit_size; do
  $P "$A/$f.py"
done
```

## Which event is month 0

Two interventions, a median of **7 months** apart, and they must not be merged:

* **review bot** — CodeRabbit, ~2025-11, reviews code people wrote
* **coding agent** — Cursor / Codex / Claude Code, ~2026-06, writes code

RQ1 and RQ2 split on the **coding agent**; RQ3 splits on the **review bot**.
Per-repo plots under `repo_report/*/plots/` follow the same convention — see
`analyze_single_repo.py --split-on coding|review|any`.

## Reading the output honestly

* **All values are raw.** No normalisation: no ratio to a pre-adoption
  baseline, no division by code size. Log axes in figures are a display choice
  and leave values untouched.
* **Absolute counts confound quality with quantity.** A growing codebase
  accumulates complexity and rule violations regardless. This is what
  `run_its.py` exists to address: it estimates the pre-adoption trend and
  measures change relative to it. Read `its_results.csv` before quoting any
  pre/post ratio.
* **Box height in the pooled figures is mostly between-repository size**, not
  change over time. Use the per-repository panel for that.
* **Outliers are suppressed** (`showfliers=False`), so a whisker cap is not
  the range, and the same repo can be drawn in one column and hidden in the
  next because its neighbours moved.
* **Adoption is near-simultaneous**: `corr(tau, calendar month) = 0.997` for
  the review wave, `0.980` for the coding wave. Event time is close to
  collinear with calendar time, so a shared shock cannot be separated from a
  treatment effect. A null survives this; a difference does not.
* Several repositories (`imagedecoder`, `nfiq`, `bio-utils`, `gist`) have very
  few distinct SonarQube snapshots, so their flat panels carry little
  information.

## Where the output goes

| | |
|---|---|
| **Report (PDF)** | `report/LLM_AI_Impact_Report_update (1).pdf` |
| LaTeX source | `repo outputs/paper/main.tex` + `preamble.tex` |
| Drop-in sections | `its_sections.tex`, `appendix_repos.tex`, `extra_tables.tex` |
| Figures | `repo outputs/paper/figures/` (copied from `analytics/`) |

Each drop-in block says in a header comment which section of the report it
belongs to. Tables are generated from the CSVs above rather than typed, so
regenerating the data and re-pasting keeps the report and the data consistent.
Table C.1 in particular is emitted from `branch_scope.csv`: an earlier
hand-transcribed version drifted by two commits between runs.
