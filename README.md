# Fantasy Cycling League

Automated fantasy cycling league table, powered by [ProCyclingStats](https://www.procyclingstats.com/) season rankings.

## 2027 draft

The active season is 2027. All teams are empty and auction costs, scores,
rankings and history have been cleared. Manager names and name matching aliases
are retained. GitHub Pages shows a holding page with the final 2026 standings.
With `status: draft`, the updater keeps this holding page and renders team
selection at `docs/draft.html`, without fetching PCS rankings or adding history.

1. Edit `first_half` in `league_config.yaml` to select each manager's 8 riders.
2. Enter the new draft prices in `auction_costs` (the budget is $1,000 per team).
3. Run `python3 update_league.py` to refresh `docs/draft.html`.
4. Once teams are complete and the 2027 season has begun, set `status: active`
   and run the updater to start scoring. Keep `transfers_done: false` until the
   mid-season transfer window.

The updater uses `season` to select the PCS ranking year. It rejects a future
season in active mode. The history backfill script also reads the season from
configuration and pauses during the draft.

## 2026 archive

The [2026 league page](docs/archive/2026/index.html) and all season data are in
`docs/archive/2026/`: standings, rider scores, full PCS rankings, all 65 history
snapshots, rosters, auction prices, the original spreadsheet and the old README.
The archive preserves the remote's results through 26 October 2026, from commit
`7859ee6`. `manifest.json` records checksums of the archived files. These files
are frozen; normal updates write only to the active season files at the root
and `docs/index.html`.

## Overview

9 managers each drafted 8 riders via auction (with a $1,000 budget each). Each rider's points come from the PCS individual season ranking. The manager's total is the sum of their 8 riders' points. A mid-season transfer window allows managers to swap riders, with first-half points banked.

The update script fetches the latest rankings, computes standings, tracks history, and publishes an interactive HTML league table with charts via GitHub Pages.

## Configuration

All league data lives in `league_config.yaml`:

```yaml
season: 2027
status: draft  # switch to active after team selection, once the season begins
transfers_done: false

first_half:
  Nick:
    - AYUSO Juan
    - VINGEGAARD Jonas
    # ...

second_half: {}   # populated at mid-season

aliases:
  GEE-WEST Derek: GEE Derek

auction_costs:
  AYUSO Juan: 280
  VINGEGAARD Jonas: 600
  # ...
```

The `auction_costs` section records what each manager paid for their riders at the draft. Riders picked for free (Joe and Gemini's Hipsters joined after the auction) are omitted.

## Points Calculation

### First Half (transfers_done: false)
- Each rider's points = their PCS season ranking points (0 if not ranked)
- Manager total = sum of all 8 riders' points

### Second Half (transfers_done: true)
- **Banked points** = sum of 1st-half riders' PCS points at the time of the snapshot
- **Delta points** = for each 2nd-half rider, current PCS points minus their baseline (snapshot value)
- Manager total = banked + sum of deltas
- Kept riders only contribute the delta since mid-season (no double-counting)

## Setup

```bash
pip install -r requirements.txt
python3 update_league.py
```

## Season Progress Charts

The league page includes four interactive Chart.js charts:

- **Team Points Over Time** — line chart tracking each manager's cumulative points across the season
- **League Position Over Time** — bump chart showing rank changes (1st through 9th)
- **Points Gained Per Update** — grouped bar chart highlighting who's gaining the most between updates
- **Rider Contributions** — horizontal stacked bar showing how each rider contributes to their manager's total

### Best Value Picks

A top 10 table ranks riders by points per dollar spent at auction, showing which draft picks have delivered the best return. Each rider's breakdown also includes a pts/$ column.

### History Tracking

Standings history is stored in `history.json`, which the update script appends to on each run. Each entry records the date, every manager's total/rank, and per-rider point breakdowns — providing the data for all charts.

### Backfilling History

To reconstruct history from the start of the season (e.g. if `history.json` is lost or the league started before history tracking was added), use the one-off backfill script:

```bash
pip install procyclingstats
python3 backfill_history.py --dry-run   # preview
python3 backfill_history.py             # write history.json
```

This fetches each rider's individual race results from PCS and reconstructs weekly standings snapshots going back to January. It uses `SLUG_OVERRIDES` in the script for riders whose PCS URL doesn't match the auto-generated slug.

## Mid-Season Transfer Workflow

1. **Take a snapshot** of current PCS rankings at the transfer window:
   ```bash
   python3 update_league.py --snapshot
   ```
   This creates `mid_season_snapshot.csv` with every rider's points at that moment.

2. **Edit `league_config.yaml`**:
   - Set `transfers_done: true`
   - Add `second_half` rosters (managers can keep or swap riders)

3. **Run the updater** as normal:
   ```bash
   python3 update_league.py
   ```
   It will use the snapshot to calculate banked + delta points.

## Output Files

| File | Description |
|------|-------------|
| `docs/index.html` | Interactive HTML league table with charts (served by GitHub Pages) |
| `league_table.csv` | Rank, Manager, Points, Banked |
| `league_detailed.csv` | Manager, Rider, Points (per-rider breakdown) |
| `ranking.csv` | Full PCS ranking with manager column for drafted riders |
| `history.json` | Timestamped standings snapshots (appended each update) |
| `mid_season_snapshot.csv` | PCS points at snapshot time (generated by `--snapshot`) |
| `backfill_history.py` | One-off script to reconstruct history from PCS rider results |

## Testing

```bash
python3 -m pytest test_league.py -v
```

Tests use dummy data to verify all calculation paths without hitting PCS.

## GitHub Pages

The league table is published automatically:
1. Push this repo to GitHub
2. Go to Settings → Pages → Source: "Deploy from a branch", Branch: `main`, Folder: `/docs`
3. The table is live at `https://<username>.github.io/fantasy-cycling/`

## GitHub Actions

The league update workflow has been removed and GitHub Actions is disabled for
this repository after deploying the 2026 holding page. There are no remote league
updates or manual update triggers. To publish future changes, first re-enable
GitHub Actions in repository settings so GitHub Pages can build and deploy them.

`run_update.sh` remains available for local updates. In draft mode, scoring and
history updates remain paused and the homepage keeps the archived 2026 results.

## Name Matching

PCS returns names as `Pogačar Tadej`. The script converts to `POGAČAR Tadej` (uppercase surname) to match the spreadsheet format. Any mismatches can be handled via the `aliases` section in `league_config.yaml`.
