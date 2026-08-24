# Thesis-FPL

**Beating the market with recent Premier League data — detecting structural mispricing in football betting markets.**

This repository contains the code, data, and models for my master's thesis at Maastricht University.
The project uses recent Premier League match and player data to build predictive models that aim to
**outperform the betting market**, and to investigate whether bookmaker odds show **structural
mispricing** that can be exploited systematically.

## Research Question

Can models trained on recent Premier League data produce probability estimates that are more accurate
than the implied probabilities of bookmaker odds, and — if so — does this reveal **structural, repeatable
mispricing** in the market rather than noise?

Sub-questions:

- How do model-based predictions compare to the market's implied probabilities (after removing the bookmaker margin)?
- Are there specific segments (e.g. certain teams, market types, or match situations) where mispricing is consistent?
- Would a betting strategy based on these discrepancies be profitable out-of-sample?

## Approach

1. **Data collection & cleaning** — recent Premier League fixtures, match statistics, and player-level
   data are gathered and processed into a consistent dataset (see `data/` and `scripts/`).
2. **Odds integration** — bookmaker odds (Bet365) are extracted and converted into implied probabilities,
   with the overround (margin) removed to obtain fair market probabilities.
3. **Modelling** — predictive models are trained on historical data to estimate outcome probabilities.
4. **Market comparison** — model probabilities are compared against the market's implied probabilities to
   identify discrepancies.
5. **Mispricing analysis** — discrepancies are tested for structure and persistence, and evaluated through
   a simulated betting strategy on out-of-sample data.

## Repository Structure

| Folder / file | Contents |
| --- | --- |
| `data/` | Premier League datasets per season (`2025-2026`, `2026-2027`), split by gameweek and by tournament. Includes fixtures, matches, playerstats, shots, xG, and momentum. |
| `model/` | Trained models and associated code. |
| `scripts/` | Scripts for cleaning and processing data (e.g. `clean_playermatchstats.py`). |
| `Parameter tuning/` | Notebooks / scripts for hyperparameter optimisation. |
| `update/` | Scripts for updating datasets and models with new gameweeks. |
| `old/` | Older / archived files (see note below). |
| `.github/workflows/` | GitHub Actions workflows (automation). |
| `Betting.ipynb`, `Betting B365.ipynb` | Analysis of bookmaker odds (Bet365) and comparison against model predictions. |
| `odds extractor.ipynb` | Fetching / extracting odds data. |
| `Running models.ipynb` | Training and evaluating models. |
| `Update model.ipynb` | Updating existing models with new data. |
| `DATA_INTEGRATION_REVIEW.md` | Documentation on the data integration process. |

> **Note on repository tidiness:** This repository also contains a number of older files and
> experimental work-in-progress (for example, the `old/` folder and some early notebooks).
> As a result, parts of the project may look a little messy or unstructured. These files have been
> kept for reference and to preserve earlier stages of the research, and are not all part of the
> final pipeline.

## Data

The datasets in `data/` are organised by season and then by:

- **By Gameweek** — all matches grouped per gameweek.
- **By Tournament** — split by competition (Premier League, Champions League, Europa League, EFL Cup, etc.).

For each gameweek there are files such as `fixtures`, `matches`, `players`,
`playerstats`, `playermatchstats`, `shots`, `xg_by_minute`, and `momentum`. Bookmaker odds are sourced
from Bet365 and integrated separately (see the odds notebooks).



- Remove `old/credentials.json` from both the repository and the Git history if it is still present.
- **Revoke / rotate the key** in the Google Cloud Console, even if you have already deleted it — a key that has ever been public can no longer be trusted.
- Add `credentials.json` (and `*.json` key files) to your `.gitignore` to prevent this from happening again.
