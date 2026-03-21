"""Tests for Fantasy Cycling League logic."""

import csv
import os
import tempfile

import pytest
import yaml

from update_league import (
    build_ranking_lookup,
    compute_league_table,
    get_active_teams,
    load_config,
    load_snapshot,
    write_snapshot,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CONFIG = {
    "transfers_done": False,
    "first_half": {
        "Alice": ["RIDER A", "RIDER B", "RIDER C"],
        "Bob": ["RIDER D", "RIDER E", "RIDER F"],
    },
    "second_half": {
        "Alice": ["RIDER A", "RIDER G", "RIDER H"],  # kept A, swapped B/C
        "Bob": ["RIDER D", "RIDER E", "RIDER I"],     # kept D/E, swapped F
    },
    "aliases": {"RIDER X Alt": "RIDER X"},
}

SAMPLE_RANKING = {
    "RIDER A": {"rank": 1, "prev_rank": 2, "team": "Team 1", "points": 500},
    "RIDER B": {"rank": 2, "prev_rank": 1, "team": "Team 1", "points": 300},
    "RIDER C": {"rank": 3, "prev_rank": 3, "team": "Team 2", "points": 200},
    "RIDER D": {"rank": 4, "prev_rank": 5, "team": "Team 2", "points": 400},
    "RIDER E": {"rank": 5, "prev_rank": 4, "team": "Team 3", "points": 150},
    "RIDER F": {"rank": 6, "prev_rank": 6, "team": "Team 3", "points": 100},
    "RIDER G": {"rank": 7, "prev_rank": 7, "team": "Team 4", "points": 350},
    "RIDER H": {"rank": 8, "prev_rank": 8, "team": "Team 4", "points": 250},
    "RIDER I": {"rank": 9, "prev_rank": 9, "team": "Team 5", "points": 180},
}

# Snapshot taken at mid-season: points at that time
SAMPLE_SNAPSHOT = {
    "RIDER A": 300,  # was 300, now 500 → delta = 200
    "RIDER B": 200,  # was 200, now 300
    "RIDER C": 100,  # was 100, now 200
    "RIDER D": 250,  # was 250, now 400 → delta = 150
    "RIDER E": 100,  # was 100, now 150 → delta = 50
    "RIDER F": 80,   # was 80, now 100
    "RIDER G": 200,  # was 200, now 350 → delta = 150
    "RIDER H": 150,  # was 150, now 250 → delta = 100
    "RIDER I": 90,   # was 90, now 180 → delta = 90
}


# ---------------------------------------------------------------------------
# Config loading tests
# ---------------------------------------------------------------------------

class TestConfigLoading:
    def test_load_config(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(SAMPLE_CONFIG))
        config = load_config(str(config_file))
        assert config["transfers_done"] is False
        assert "Alice" in config["first_half"]
        assert len(config["first_half"]["Alice"]) == 3

    def test_get_active_teams_first_half(self):
        config = {**SAMPLE_CONFIG, "transfers_done": False}
        teams = get_active_teams(config)
        assert teams == SAMPLE_CONFIG["first_half"]

    def test_get_active_teams_second_half(self):
        config = {**SAMPLE_CONFIG, "transfers_done": True}
        teams = get_active_teams(config)
        assert teams == SAMPLE_CONFIG["second_half"]

    def test_get_active_teams_transfers_done_but_no_second_half(self):
        config = {**SAMPLE_CONFIG, "transfers_done": True, "second_half": {}}
        teams = get_active_teams(config)
        assert teams == SAMPLE_CONFIG["first_half"]


# ---------------------------------------------------------------------------
# First half (no transfers) tests
# ---------------------------------------------------------------------------

class TestFirstHalf:
    def test_total_is_sum_of_current_points(self):
        standings = compute_league_table(
            SAMPLE_CONFIG["first_half"], SAMPLE_RANKING,
        )
        alice = next(s for s in standings if s["manager"] == "Alice")
        bob = next(s for s in standings if s["manager"] == "Bob")
        # Alice: A(500) + B(300) + C(200) = 1000
        assert alice["points"] == 1000
        assert alice["banked"] == 0
        # Bob: D(400) + E(150) + F(100) = 650
        assert bob["points"] == 650
        assert bob["banked"] == 0

    def test_rankings_are_ordered(self):
        standings = compute_league_table(
            SAMPLE_CONFIG["first_half"], SAMPLE_RANKING,
        )
        assert standings[0]["rank"] == 1
        assert standings[0]["points"] >= standings[1]["points"]

    def test_rider_not_in_ranking_gets_zero(self):
        teams = {"Alice": ["RIDER A", "UNKNOWN RIDER", "RIDER C"]}
        standings = compute_league_table(teams, SAMPLE_RANKING)
        alice = standings[0]
        # A(500) + 0 + C(200) = 700
        assert alice["points"] == 700


# ---------------------------------------------------------------------------
# Second half (with transfers) tests
# ---------------------------------------------------------------------------

class TestSecondHalf:
    def test_banked_plus_delta(self):
        standings = compute_league_table(
            SAMPLE_CONFIG["second_half"],
            SAMPLE_RANKING,
            transfers_done=True,
            first_half_teams=SAMPLE_CONFIG["first_half"],
            snapshot=SAMPLE_SNAPSHOT,
        )
        alice = next(s for s in standings if s["manager"] == "Alice")
        # Banked: A(300) + B(200) + C(100) = 600
        assert alice["banked"] == 600
        # 2nd half riders: A(500-300=200) + G(350-200=150) + H(250-150=100) = 450
        # Total: 600 + 450 = 1050
        assert alice["points"] == 1050

    def test_all_new_riders(self):
        # Bob keeps D and E, swaps F for I
        standings = compute_league_table(
            SAMPLE_CONFIG["second_half"],
            SAMPLE_RANKING,
            transfers_done=True,
            first_half_teams=SAMPLE_CONFIG["first_half"],
            snapshot=SAMPLE_SNAPSHOT,
        )
        bob = next(s for s in standings if s["manager"] == "Bob")
        # Banked: D(250) + E(100) + F(80) = 430
        assert bob["banked"] == 430
        # 2nd half: D(400-250=150) + E(150-100=50) + I(180-90=90) = 290
        # Total: 430 + 290 = 720
        assert bob["points"] == 720

    def test_kept_rider_only_contributes_delta(self):
        """A kept rider should not be double-counted."""
        standings = compute_league_table(
            SAMPLE_CONFIG["second_half"],
            SAMPLE_RANKING,
            transfers_done=True,
            first_half_teams=SAMPLE_CONFIG["first_half"],
            snapshot=SAMPLE_SNAPSHOT,
        )
        alice = next(s for s in standings if s["manager"] == "Alice")
        # RIDER A: banked includes 300, delta includes (500-300)=200
        # Total contribution from A: 300 + 200 = 500 = current points (correct, no double-counting)
        # If double-counted, it would be 300 (banked) + 500 (full current) = 800
        assert alice["points"] == 1050  # not 1250

    def test_rider_not_in_snapshot_baseline_zero(self):
        """A rider not in the snapshot should have baseline 0."""
        snapshot_missing = {k: v for k, v in SAMPLE_SNAPSHOT.items() if k != "RIDER G"}
        standings = compute_league_table(
            SAMPLE_CONFIG["second_half"],
            SAMPLE_RANKING,
            transfers_done=True,
            first_half_teams=SAMPLE_CONFIG["first_half"],
            snapshot=snapshot_missing,
        )
        alice = next(s for s in standings if s["manager"] == "Alice")
        # Banked: same = 600
        # RIDER G baseline = 0 (not in snapshot), current = 350, delta = 350
        # A(200) + G(350) + H(100) = 650
        # Total: 600 + 650 = 1250
        assert alice["points"] == 1250

    def test_rider_points_dropped_delta_not_negative(self):
        """If a rider's current points are below baseline, delta should be 0."""
        ranking_dropped = {**SAMPLE_RANKING}
        ranking_dropped["RIDER G"] = {**SAMPLE_RANKING["RIDER G"], "points": 100}
        standings = compute_league_table(
            SAMPLE_CONFIG["second_half"],
            ranking_dropped,
            transfers_done=True,
            first_half_teams=SAMPLE_CONFIG["first_half"],
            snapshot=SAMPLE_SNAPSHOT,
        )
        alice = next(s for s in standings if s["manager"] == "Alice")
        # RIDER G: current(100) - baseline(200) = -100, clamped to 0
        # A(200) + G(0) + H(100) = 300
        # Total: 600 + 300 = 900
        assert alice["points"] == 900


# ---------------------------------------------------------------------------
# Snapshot I/O tests
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_write_and_load_snapshot(self, tmp_path):
        snapshot_path = str(tmp_path / "snapshot.csv")
        ranking = {
            "RIDER A": {"rank": 1, "prev_rank": 2, "team": "T1", "points": 500},
            "RIDER B": {"rank": 2, "prev_rank": 1, "team": "T2", "points": 300},
        }
        write_snapshot(ranking, snapshot_path)
        loaded = load_snapshot(snapshot_path)
        assert loaded == {"RIDER A": 500, "RIDER B": 300}

    def test_snapshot_csv_format(self, tmp_path):
        snapshot_path = str(tmp_path / "snapshot.csv")
        ranking = {
            "RIDER A": {"rank": 1, "prev_rank": 2, "team": "T1", "points": 500},
        }
        write_snapshot(ranking, snapshot_path)
        with open(snapshot_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["rider"] == "RIDER A"
        assert rows[0]["points"] == "500"


# ---------------------------------------------------------------------------
# Alias tests
# ---------------------------------------------------------------------------

class TestAliases:
    def test_alias_applied(self):
        raw = [
            {"rider_name": "RIDER X Alt", "rank": 1, "prev_rank": 1,
             "team_name": "Team", "points": 100},
        ]
        lookup = build_ranking_lookup(raw, {"RIDER X Alt": "RIDER X"})
        assert "RIDER X" in lookup
        assert "RIDER X Alt" not in lookup
