# Fantasy Cycling League

Scrapes ProCyclingStats rankings, scores a fantasy league, and writes a static
site to `docs/`. Entry point: `update_league.py`. Tests: `test_league.py`
(pytest). Config: `league_config.yaml`. Mid-season baseline: `history.json`.

## Mid-season transfers - read before changing scoring

The league has a mid-season transfer window. Once `transfers_done: true` in
`league_config.yaml`, scoring switches from "total points" to "points gained
since the snapshot baseline":

- A rider's contribution becomes `max(0, current_points - baseline)`.
- Riders kept across the transfer window must not be double-counted - the
  baseline cancels their first-half points.
- New 2nd-half riders have an effective baseline of 0.
- League totals, rider contribution tables, hot-riders, and best-value
  calculations all branch on `transfers_done` and `snapshot`.

Any change that touches scoring, contribution display, or aggregations must be
checked against both halves of the season (transfers_done false AND true).
The existing tests in `test_league.py` cover the kept-rider, new-rider, and
dropped-rider cases - run them and add new cases when you change this path.

## Workflow

- Run `python3 -m pytest` before committing.
- Regenerate outputs with `python3 update_league.py` after any change that
  affects HTML or CSVs; commit the regenerated files alongside the code.
