#!/usr/bin/env python3
"""Fantasy Cycling League — fetch PCS rankings and generate league table."""

import argparse
import csv
import os
import re
from datetime import datetime, timezone

import cloudscraper
import yaml

BASE_URL = "https://www.procyclingstats.com"


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    """Load league configuration from YAML."""
    with open(path) as f:
        return yaml.safe_load(f)


def get_active_teams(config: dict) -> dict[str, list[str]]:
    """Return the currently active rosters based on transfer status."""
    if config["transfers_done"] and config.get("second_half"):
        return config["second_half"]
    return config["first_half"]


def build_rider_to_manager(teams: dict[str, list[str]]) -> dict[str, str]:
    """Build reverse lookup: rider name → manager."""
    lookup = {}
    for manager, riders in teams.items():
        for rider in riders:
            lookup[rider] = manager
    return lookup


# ---------------------------------------------------------------------------
# Snapshot (mid-season baseline)
# ---------------------------------------------------------------------------

def load_snapshot(path: str) -> dict[str, int]:
    """Load mid-season snapshot: rider → points at snapshot time."""
    snapshot = {}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            snapshot[row["rider"]] = int(row["points"])
    return snapshot


def write_snapshot(ranking: dict[str, dict], path: str):
    """Write current PCS rankings as a snapshot CSV."""
    rows = []
    for name, info in ranking.items():
        rows.append({"rider": name, "points": info["points"]})
    rows.sort(key=lambda x: x["rider"])
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["rider", "points"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Written snapshot: {path}")


# ---------------------------------------------------------------------------
# PCS scraping
# ---------------------------------------------------------------------------

def parse_ranking_page(html: str) -> list[dict]:
    """Parse rider rows from a PCS season ranking HTML page.

    Season ranking rows have 6 columns:
      0: rank, 1: prev_rank, 2: delta, 3: rider, 4: team, 5: points
    """
    riders = []
    rows = re.findall(r'<tr class="[^"]*">(.*?)</tr>', html, re.DOTALL)
    for row in rows:
        tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        if len(tds) < 6:
            continue
        try:
            rank = int(tds[0].strip())
            prev_rank = int(tds[1].strip())
        except ValueError:
            continue
        name_match = re.search(r'href="rider/[^"]+">([^<]+)</a>', tds[3])
        team_match = re.search(r'href="team/[^"]+">([^<]+)</a>', tds[4])
        points_match = re.search(r'>(\d+)</a>', tds[5])
        if not name_match or not points_match:
            continue
        riders.append({
            "rider_name": name_match.group(1),
            "rank": rank,
            "prev_rank": prev_rank,
            "team_name": team_match.group(1) if team_match else "",
            "points": int(points_match.group(1)),
        })
    return riders


def fetch_rankings() -> list[dict]:
    """Fetch all pages of PCS season individual ranking."""
    print("Fetching PCS season individual ranking...")
    session = cloudscraper.create_scraper()

    # First page (establishes session)
    r = session.get(f"{BASE_URL}/rankings/me/season-individual")
    all_riders = parse_ranking_page(r.text)
    print(f"  Page 1: {len(all_riders)} riders")

    # Discover page offsets from the offset <select>
    offset_select = re.search(
        r'<select[^>]*name="offset"[^>]*>(.*?)</select>', r.text, re.DOTALL
    )
    if not offset_select:
        print("  Warning: could not find pagination, using first page only")
        return all_riders

    offsets = re.findall(r'<option[^>]*value="(\d+)"', offset_select.group(1))

    # Fetch remaining pages (skip offset=0 which is page 1)
    for i, offset in enumerate(offsets[1:], start=2):
        r = session.get(
            f"{BASE_URL}/rankings.php",
            params={"p": "me", "s": "season-individual", "offset": offset},
        )
        riders = parse_ranking_page(r.text)
        print(f"  Page {i}: {len(riders)} riders")
        all_riders.extend(riders)

    print(f"Total riders fetched: {len(all_riders)}")
    return all_riders


def build_ranking_lookup(raw_rankings: list[dict], aliases: dict[str, str]) -> dict[str, dict]:
    """Build a lookup dict keyed by rider name, applying aliases."""
    lookup = {}
    for entry in raw_rankings:
        name = entry["rider_name"]
        name = aliases.get(name, name)
        lookup[name] = {
            "rank": entry["rank"],
            "prev_rank": entry["prev_rank"],
            "team": entry["team_name"],
            "points": entry["points"],
        }
    return lookup


# ---------------------------------------------------------------------------
# League computation
# ---------------------------------------------------------------------------

def compute_league_table(
    active_teams: dict[str, list[str]],
    ranking: dict[str, dict],
    transfers_done: bool = False,
    first_half_teams: dict[str, list[str]] | None = None,
    snapshot: dict[str, int] | None = None,
) -> list[dict]:
    """Compute league standings for each manager.

    When transfers_done:
      banked = sum of 1st-half riders' snapshot points
      delta  = sum of (current - baseline) for each 2nd-half rider
      total  = banked + delta

    Otherwise:
      total = sum of current rider points
    """
    standings = []
    for manager, riders in active_teams.items():
        if transfers_done and snapshot is not None and first_half_teams is not None:
            banked = sum(snapshot.get(r, 0) for r in first_half_teams[manager])
            delta = 0
            for rider in riders:
                baseline = snapshot.get(rider, 0)
                current = ranking.get(rider, {}).get("points", 0)
                delta += max(0, current - baseline)
            total_points = banked + delta
        else:
            banked = 0
            delta = 0
            total_points = 0
            for rider in riders:
                total_points += ranking.get(rider, {}).get("points", 0)

        standings.append({
            "manager": manager,
            "points": total_points,
            "banked": banked,
        })

    standings.sort(key=lambda x: x["points"], reverse=True)
    for i, entry in enumerate(standings, start=1):
        entry["rank"] = i
    return standings


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_league_csv(standings: list[dict], path: str):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["rank", "manager", "points", "banked"])
        writer.writeheader()
        writer.writerows(standings)
    print(f"Written: {path}")


def write_detailed_csv(
    active_teams: dict[str, list[str]],
    ranking: dict[str, dict],
    path: str,
    transfers_done: bool = False,
    snapshot: dict[str, int] | None = None,
):
    rows = []
    for manager, riders in active_teams.items():
        for rider in riders:
            current = ranking.get(rider, {}).get("points", 0)
            if transfers_done and snapshot is not None:
                baseline = snapshot.get(rider, 0)
                pts = max(0, current - baseline)
            else:
                pts = current
            rows.append({"manager": manager, "rider": rider, "points": pts})
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["manager", "rider", "points"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Written: {path}")


def write_ranking_csv(ranking: dict[str, dict], rider_to_manager: dict[str, str], path: str):
    rows = []
    for name, info in ranking.items():
        rows.append({
            "rank": info["rank"],
            "prev_rank": info["prev_rank"],
            "rider": name,
            "team": info["team"],
            "points": info["points"],
            "manager": rider_to_manager.get(name, ""),
        })
    rows.sort(key=lambda x: x["rank"])
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["rank", "prev_rank", "rider", "team", "points", "manager"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Written: {path}")


def generate_html(
    standings: list[dict],
    active_teams: dict[str, list[str]],
    ranking: dict[str, dict],
    path: str,
    transfers_done: bool = False,
    snapshot: dict[str, int] | None = None,
):
    """Generate a self-contained HTML league table."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Build per-manager rider details sorted by points descending
    manager_details = {}
    for manager, riders in active_teams.items():
        details = []
        for rider in riders:
            info = ranking.get(rider, {})
            current = info.get("points", 0)
            if transfers_done and snapshot is not None:
                baseline = snapshot.get(rider, 0)
                display_points = max(0, current - baseline)
            else:
                display_points = current
            details.append({
                "rider": rider,
                "points": display_points,
                "rank": info.get("rank", "—"),
                "team": info.get("team", ""),
            })
        details.sort(key=lambda x: x["points"], reverse=True)
        manager_details[manager] = details

    # Build standings rows
    standings_rows = ""
    for entry in standings:
        standings_rows += f"""        <tr>
          <td class="rank">{entry['rank']}</td>
          <td class="manager">{entry['manager']}</td>
          <td class="points">{entry['points']:,}</td>
        </tr>
"""

    # Build detail sections
    detail_sections = ""
    for entry in standings:
        mgr = entry["manager"]
        riders_html = ""

        # Show banked points row if transfers have happened
        if transfers_done and entry["banked"] > 0:
            riders_html += f"""            <tr class="banked-row">
              <td><em>1st Half (banked)</em></td>
              <td class="team"></td>
              <td class="points">{entry['banked']:,}</td>
              <td class="rider-rank"></td>
            </tr>
"""

        for r in manager_details[mgr]:
            rank_display = f"#{r['rank']}" if r["rank"] != "—" else "—"
            riders_html += f"""            <tr>
              <td>{r['rider']}</td>
              <td class="team">{r['team']}</td>
              <td class="points">{r['points']:,}</td>
              <td class="rider-rank">{rank_display}</td>
            </tr>
"""
        detail_sections += f"""      <details class="manager-detail">
        <summary>{mgr} — {entry['points']:,} pts</summary>
        <table class="rider-table">
          <thead><tr><th>Rider</th><th>Team</th><th>Points</th><th>PCS Rank</th></tr></thead>
          <tbody>
{riders_html}          </tbody>
        </table>
      </details>
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>2026 Fantasy Cycling League</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #ffffff;
    --surface: #f8f8f8;
    --text: #1a1a1a;
    --text-secondary: #6b6b6b;
    --accent: #00a67e;
    --accent-light: rgba(0, 166, 126, 0.06);
    --border: #e5e5e5;
    --border-strong: #d0d0d0;
    --gold: #c5960c;
    --silver: #6b7280;
    --bronze: #a0622d;
  }}

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    font-family: 'Hanken Grotesk', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.55;
    padding: 3rem 1.25rem;
    min-height: 100vh;
    -webkit-font-smoothing: antialiased;
  }}

  .container {{ max-width: 840px; margin: 0 auto; }}

  /* --- Header --- */
  header {{
    margin-bottom: 2.75rem;
    padding-bottom: 1.5rem;
    border-bottom: 2px solid var(--text);
  }}
  h1 {{
    font-size: 2rem;
    font-weight: 800;
    letter-spacing: -0.035em;
    line-height: 1.15;
    margin-bottom: 0.35rem;
  }}
  .subtitle {{
    color: var(--text-secondary);
    font-size: 0.85rem;
    font-weight: 500;
    letter-spacing: 0.01em;
  }}

  /* --- Standings table --- */
  table.standings {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 3rem;
  }}
  table.standings thead {{
    border-bottom: 2px solid var(--text);
  }}
  table.standings th {{
    font-weight: 700;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    padding: 0.6rem 0.75rem;
    text-align: left;
    color: var(--text);
  }}
  table.standings td {{
    padding: 0.65rem 0.75rem;
    border-bottom: 1px solid var(--border);
    font-size: 0.92rem;
    transition: background 0.12s ease;
  }}
  table.standings tr:last-child td {{ border-bottom: 1px solid var(--border); }}
  table.standings tbody tr:hover {{ background: var(--accent-light); }}
  td.rank {{
    font-weight: 700;
    width: 3rem;
    text-align: center;
    font-variant-numeric: tabular-nums;
  }}
  td.manager {{ font-weight: 600; }}
  td.points {{
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.01em;
  }}
  tbody tr:nth-child(1) td.rank {{ color: var(--gold); }}
  tbody tr:nth-child(2) td.rank {{ color: var(--silver); }}
  tbody tr:nth-child(3) td.rank {{ color: var(--bronze); }}

  /* --- Breakdown --- */
  h2 {{
    font-size: 1.15rem;
    font-weight: 800;
    letter-spacing: -0.02em;
    text-transform: uppercase;
    margin-bottom: 0.65rem;
    color: var(--text);
  }}
  .manager-detail {{
    border-top: 1px solid var(--border);
    transition: background 0.15s ease;
  }}
  .manager-detail:last-of-type {{
    border-bottom: 1px solid var(--border);
  }}
  .manager-detail summary {{
    padding: 0.6rem 0.25rem;
    cursor: pointer;
    font-weight: 600;
    font-size: 0.9rem;
    user-select: none;
    list-style: none;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    transition: color 0.15s ease;
  }}
  .manager-detail summary:hover {{
    color: var(--accent);
  }}
  .manager-detail summary::-webkit-details-marker {{ display: none; }}
  .manager-detail summary::before {{
    content: '';
    display: inline-block;
    width: 6px;
    height: 6px;
    border-right: 2px solid var(--accent);
    border-bottom: 2px solid var(--accent);
    transform: rotate(-45deg);
    transition: transform 0.2s ease;
    flex-shrink: 0;
  }}
  .manager-detail[open] summary::before {{
    transform: rotate(45deg);
  }}
  .rider-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.82rem;
    margin-bottom: 0.5rem;
  }}
  .rider-table th {{
    text-align: left;
    padding: 0.35rem 0.75rem;
    color: var(--text-secondary);
    font-weight: 600;
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
  }}
  .rider-table td {{
    padding: 0.4rem 0.75rem;
    border-bottom: 1px solid var(--border);
  }}
  .rider-table tr:last-child td {{ border-bottom: none; }}
  .rider-table td.points {{ font-weight: 600; font-variant-numeric: tabular-nums; }}
  .rider-table td.team {{ color: var(--text-secondary); font-size: 0.78rem; }}
  .rider-table td.rider-rank {{ color: var(--text-secondary); font-variant-numeric: tabular-nums; }}
  .banked-row td {{ background: var(--surface); }}

  /* --- Footer --- */
  .updated {{
    text-align: center;
    color: var(--text-secondary);
    font-size: 0.72rem;
    font-weight: 500;
    margin-top: 2.75rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
    letter-spacing: 0.01em;
  }}

  /* --- Responsive --- */
  @media (max-width: 600px) {{
    body {{ padding: 1.5rem 0.75rem; }}
    h1 {{ font-size: 1.5rem; }}
    table.standings td, table.standings th {{ padding: 0.5rem 0.5rem; font-size: 0.82rem; }}
    .rider-table td, .rider-table th {{ padding: 0.3rem 0.5rem; }}
  }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>2026 Fantasy Cycling League</h1>
    <p class="subtitle">Points sourced from ProCyclingStats season ranking</p>
  </header>

  <table class="standings">
    <thead>
      <tr><th>Rank</th><th>Manager</th><th>Points</th></tr>
    </thead>
    <tbody>
{standings_rows}    </tbody>
  </table>

  <h2>Rider Breakdown</h2>
{detail_sections}
  <p class="updated">Last updated: {now}</p>
</div>
</body>
</html>"""

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(html)
    print(f"Written: {path}")


def log_missing_riders(active_teams: dict[str, list[str]], ranking: dict[str, dict]):
    """Log any drafted riders not found in the PCS ranking."""
    all_riders = [r for riders in active_teams.values() for r in riders]
    missing = []
    for manager, riders in active_teams.items():
        for rider in riders:
            if rider not in ranking:
                missing.append((manager, rider))
    if missing:
        print(f"\n⚠ {len(missing)} drafted rider(s) NOT found in PCS ranking:")
        for manager, rider in missing:
            print(f"  {rider} ({manager})")
    else:
        print(f"\n✓ All {len(all_riders)} drafted riders found in PCS ranking")


def main():
    parser = argparse.ArgumentParser(description="Fantasy Cycling League updater")
    parser.add_argument(
        "--snapshot", action="store_true",
        help="Save current PCS rankings as mid-season snapshot and exit",
    )
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, "league_config.yaml")
    snapshot_path = os.path.join(base_dir, "mid_season_snapshot.csv")

    # Load config
    config = load_config(config_path)
    aliases = config.get("aliases", {})
    transfers_done = config.get("transfers_done", False)
    first_half_teams = config["first_half"]
    active_teams = get_active_teams(config)
    rider_to_manager = build_rider_to_manager(active_teams)

    # Step 1: Fetch rankings
    raw = fetch_rankings()

    # Step 2: Build lookup
    ranking = build_ranking_lookup(raw, aliases)

    # Handle snapshot mode
    if args.snapshot:
        write_snapshot(ranking, snapshot_path)
        print("Snapshot saved. Update league_config.yaml with second_half rosters")
        print("and set transfers_done: true, then run without --snapshot.")
        return

    # Step 3: Check for missing riders
    log_missing_riders(active_teams, ranking)

    # Step 4: Load snapshot if transfers are active
    snapshot = None
    if transfers_done:
        if not os.path.exists(snapshot_path):
            print(f"ERROR: transfers_done is true but {snapshot_path} not found.")
            print("Run with --snapshot first to create the baseline.")
            return
        snapshot = load_snapshot(snapshot_path)
        print(f"Loaded mid-season snapshot ({len(snapshot)} riders)")

    # Step 5: Compute league table
    standings = compute_league_table(
        active_teams, ranking, transfers_done, first_half_teams, snapshot
    )

    # Step 6: Print summary
    print("\n=== League Standings ===")
    for entry in standings:
        banked_info = f" (banked: {entry['banked']:,})" if entry["banked"] > 0 else ""
        print(f"  {entry['rank']}. {entry['manager']}: {entry['points']:,} pts{banked_info}")

    # Step 7: Write outputs
    write_league_csv(standings, os.path.join(base_dir, "league_table.csv"))
    write_detailed_csv(
        active_teams, ranking, os.path.join(base_dir, "league_detailed.csv"),
        transfers_done, snapshot,
    )
    write_ranking_csv(ranking, rider_to_manager, os.path.join(base_dir, "ranking.csv"))
    generate_html(
        standings, active_teams, ranking,
        os.path.join(base_dir, "docs", "index.html"),
        transfers_done, snapshot,
    )

    print("\nDone!")


if __name__ == "__main__":
    main()
