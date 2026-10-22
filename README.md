# Speed at the Cost of Quality: How Cursor AI Increases Short-Term Velocity and Long-Term Complexity in Open-Source Projects

This repository contains the replication package for the following paper:

> Hao He, Courtney Miller, Shyam Agarwal, Christian Kästner, and Bogdan Vasilescu. 2026. Speed at the Cost of Quality: How Cursor AI Increases Short-Term Velocity and Long-Term Complexity in Open-Source Projects. In 23rd International Conference on Mining Software Repositories (MSR ’26), April 13–14, 2026, Rio de Janeiro, Brazil. ACM, New York, NY, USA, 19 pages. https://doi.org/10.1145/3793302.3793349

The additional `.gitignore`d files are available on Zenodo: [10.5281/zenodo.18368661](https://doi.org/10.5281/zenodo.18368661)

## MOSIP extension study

This repository also hosts a follow-on study applying the same measurement
approach to the MOSIP digital public infrastructure project.

**Report:** [`report/LLM_AI_Impact_Report_update (1).pdf`](report/) —
*AI Coding Agents and Software Development in MOSIP: code volume, code quality,
and code-review practice following AI adoption.* Upanzi Network, Carnegie
Mellon University Africa.

| | |
|---|---|
| Subjects | 20 MOSIP core-service repositories, 326 repository-months |
| Window | January 2025 – August 2026 |
| Data | 6,786 commits · 5,603 pull requests · 286 SonarQube snapshots |
| Design | Event study + interrupted time series, split on AI coding-agent adoption |

* [`repo outputs/_tools/`](repo%20outputs/_tools/) — per-repository collection
  pipeline (clone → SonarQube → AI detection → GitHub collectors → analysis)
* [`repo outputs/_tools/analysis/`](repo%20outputs/_tools/analysis/) — pooled
  analysis, statistics and figures. **Start here to reproduce the report**;
  its README documents every script and output.
* [`repo outputs/paper/`](repo%20outputs/paper/) — LaTeX source for the report

Unlike the replication package below, this study reports **absolute** measures
throughout and uses an interrupted time-series specification to separate
adoption effects from pre-existing growth trends.

## Organization

* The `scripts/` folder contains all the scripts we used to collect data, run propensity score matching, and collect SonarQube metrics. These scripts are volatile in nature: Rerunning them will likely not get the same dataset we obtained for our paper (GitHub repositories growing and taken down, GitHub API changing, SonarQube changing, etc.), but they might be a valuable reference.
* The `data/` folder contains the exact dataset we used for our paper. Some data files are `.gitignore`d in the GitHub repository but available in Zenodo.
    * `repos.csv`: Metadata for treatment group repositories (Cursor-adopting projects)
    * `cursor_commits.csv`: Commit-level data showing commits modifying Cursor configuration files
    * `cursor_files.csv`: File-level data for Cursor configuration files
    * `repo_events.csv` / `repo_events_control.csv`: GitHub event data for treatment/control repositories
    * `matching.csv`: Propensity score matching results (treatment-control pairs)
    * `panel_event_monthly.csv`: Main panel dataset used for DiD analysis (monthly aggregated)
    * `ts_repos_monthly.csv` / `ts_repos_control_monthly.csv`: Monthly time series for treatment/control groups
    * `repo_metrics.csv`: Additional repository-level metrics (stars, contributors, etc.)
    * `sonarqube_warnings.csv`: SonarQube static analysis warnings per repository (as available)
    * `sonarqube_warning_definitions.csv`: Definitions and categories of SonarQube warning types
    * `control_repo_candidates_*.csv`: Monthly snapshots of candidate control repositories
* The `notebooks/` folder contains R notebooks that will read from `data/` and reproduce results in the paper.
    * `DataCollection.md`: Dataset description
    * `PropensityScoreMatching.md`: Matching results
    * `DiffInDiffBorusyak.md`: Main DiD results
    * `DynamicPanel.md`: Main panel GMM results
    * `DiffInDiffAll.md`: Comparing alternative DiD estimators
    * `AnalyzeSonarQubeWarnings.md`: Appendix analysis on SonarQube warnings
    * `NonCausalMethods.md`: Some interesting results replicating the same RQ with only descriptive and correlational methods
    * `DiffInDiffCallaway.md`, `DiffInDiffPosterFigures.md`, `DiffInDiffTWFE.md`: Older notebooks that has been deprecated
* The `plots/` folder contains all the plots in this paper (`.gitignore`d in the GitHub repository but available in Zenodo)

## Development Environment

All results were obtained using **R 4.3.3** for statistical analysis and visualization (DiD estimation, panel models, plotting), and **Python 3.11.4** for data collection scripts (GitHub API, BigQuery, SonarQube). We provide the detailed packages and their versions for future replication purposes.
Due to the R ecosystem constantly evolving, different R versions and package versions may lead to slightly different results for this paper.

### R Packages

| Package | Version | Description |
|---------|---------|-------------|
| tidyverse | 2.0.0 | Data manipulation and visualization |
| ggplot2 | 3.5.1 | Grammar of graphics plotting |
| data.table | 1.15.4 | Fast data manipulation |
| dplyr | 1.1.4 | Data manipulation verbs |
| tidyr | 1.3.1 | Data tidying |
| tibble | 3.2.1 | Modern data frames |
| lubridate | 1.9.3 | Date/time manipulation |
| scales | 1.3.0 | Scale functions for visualization |
| fixest | 0.12.1 | Fixed effects estimation |
| did | 2.1.2 | Callaway & Sant'Anna DiD estimator |
| didimputation | 0.3.0 | Borusyak et al. imputation estimator |
| plm | 2.6-4 | Panel data models (GMM) |
| bacondecomp | 0.1.1 | Bacon decomposition for TWFE |
| modelsummary | 2.1.1 | Model summary tables |
| knitr | 1.48 | Dynamic report generation |
| kableExtra | 1.4.0 | Enhanced table formatting |
| gridExtra | 2.3 | Arrange multiple plots |
| cowplot | 1.1.3 | Plot composition |
| corrplot | 0.94 | Correlation visualization |
| RColorBrewer | 1.1-3 | Color palettes |
| Cairo | 1.6-2 | High-quality graphics device |
| showtext | 0.9-7 | Custom fonts in plots |
| ggfx | 1.0.1 | Graphics effects for ggplot2 |

### Python Packages

| Package | Version | Description |
|---------|---------|-------------|
| pandas | 2.2.0 | Data manipulation |
| numpy | 1.26.4 | Numerical computing |
| requests | 2.31.0 | HTTP requests |
| python-dotenv | 1.0.1 | Environment variable management |
| GitPython | 3.1.43 | Git repository interaction |
| PyGithub | 2.3.0 | GitHub API client |
| google-cloud-bigquery | 3.25.0 | BigQuery client for GH Archive |
| scikit-learn | 1.5.0 | Machine learning (propensity scores) |
| semver | 3.0.2 | Semantic versioning |
| node-semver | 0.9.0 | Node.js semver parsing |
| gql | 3.5.0 | GraphQL client |
| aiohttp | 3.9.5 | Async HTTP for GraphQL |

## Replication Instructions

### 1. Obtain the Data

Clone this repository and download the full dataset from Zenodo:

```bash
git clone https://github.com/hehao98/CursorStudy.git
cd CursorStudy
# (Optional) Download data files from Zenodo and place them in the data/ folder
```

### 2. Set Up R Environment

Install R 4.3.3 and the required packages:

```r
install.packages(c(
    "tidyverse", "ggplot2", "data.table", "dplyr", "tidyr", "tibble",
    "lubridate", "scales", "fixest", "did", "didimputation", "plm",
    "bacondecomp", "modelsummary", "knitr", "kableExtra", "gridExtra",
    "cowplot", "corrplot", "RColorBrewer", "Cairo"
))
```

### 3. Reproduce Results

Knit the notebooks in the following order (Using RStudio or the R VS Code extension):

1. **`notebooks/DataCollection.Rmd`** — Overview of the dataset (Table 1, Figure 2)
2. **`notebooks/PropensityScoreMatching.Rmd`** — Matching diagnostics (Appendix)
3. **`notebooks/DiffInDiffBorusyak.Rmd`** — Main DiD results (Tables 2, Figure 3, Figure 4)
4. **`notebooks/DynamicPanel.Rmd`** — Panel GMM results (Table 3)
5. **`notebooks/DiffInDiffAll.Rmd`** — Comparing DiD estimators (Appendix)
6. **`notebooks/AnalyzeSonarQubeWarnings.Rmd`** — SonarQube analysis (Appendix)

Each notebook reads from `data/` and outputs tables/figures to `plots/`.

### 4. (Optional) Rerun Data Collection

To rerun the data collection scripts (not recommended for exact replication):

```bash
# Set up Python environment
python -m venv venv
source venv/bin/activate
pip install pandas numpy requests python-dotenv GitPython PyGithub google-cloud-bigquery scikit-learn semver node-semver gql aiohttp

# Configure API keys in .env file
cp .env.example .env
# Edit .env with your GitHub token and BigQuery credentials

# Run scripts (see scripts/ for individual script usage)
```

**Note:** Data collection scripts interact with live APIs and will produce different results due to repository changes, API updates, or rate limiting.
