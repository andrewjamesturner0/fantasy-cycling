#!/usr/bin/env bash
# run_update.sh — Run the fantasy cycling league update locally and push to GitHub.
# Intended as a cron job (Mon/Thu morning) since GitHub Actions IPs are blocked by
# PCS Cloudflare.
#
# Usage: ./run_update.sh
# Cron:  0 8 * * 1,4 cd /home/ajt/fantasy-cycling && ./run_update.sh >> /tmp/fantasy-cycling-cron.log 2>&1

set -euo pipefail
cd "$(dirname "$0")"

echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) Starting league update ==="

# Pull latest from GitHub
git pull --ff-only origin main

# Run the update
./venv/bin/python3 update_league.py

# If anything changed, commit and push
if ! git diff --quiet -- docs/index.html league_table.csv league_detailed.csv ranking.csv history.json; then
    git add docs/index.html league_table.csv league_detailed.csv ranking.csv history.json
    git commit -m "Update league table $(date -u +%Y-%m-%d)"
    git push origin main
    echo "Committed and pushed updated league data."
else
    echo "No changes to commit."
fi

echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) Done ==="
