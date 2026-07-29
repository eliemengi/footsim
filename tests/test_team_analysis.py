"""
Tests fuer src/features/team_analysis.py (Block A).

Alle Tests laufen offline auf synthetischen Fixtures im Format von
partition_season_matches()["finished"].
"""

import pytest

from src.features.team_analysis import (
    get_team_form,
    split_home_away,
    compute_power_ranking,
    get_head_to_head,
    get_team_summary,
    POWER_WEIGHTS,
)


FIXTURES = [
    {"home_id": 1, "away_id": 2, "home_goals": 3, "away_goals": 1, "matchday": 1},
    {"home_id": 3, "away_id": 1, "home_goals": 0, "away_goals": 2, "matchday": 2},
    {"home_id": 1, "away_id": 3, "home_goals": 1, "away_goals": 1, "matchday": 3},
    {"home_id": 2, "away_id": 1, "home_goals": 2, "away_goals": 2, "matchday": 4},
    {"home_id": 1, "away_id": 2, "home_goals": 0, "away_goals": 1, "matchday": 5},
]

TABLE = [
    {"team_id": 1, "team_name": "Alpha", "team_full_name": "Alpha FC", "crest": None,
     "position": 1, "played": 5, "points": 8, "won": 2, "draw": 2, "lost": 1,
     "goals_for": 8, "goals_against": 5, "goal_difference": 3},
    {"team_id": 2, "team_name": "Beta", "team_full_name": "Beta FC", "crest": None,
     "position": 2, "played": 3, "points": 4, "won": 1, "draw": 1, "lost": 1,
     "goals_for": 4, "goals_against": 5, "goal_difference": -1},
    {"team_id": 3, "team_name": "Gamma", "team_full_name": "Gamma FC", "crest": None,
     "position": 3, "played": 2, "points": 1, "won": 0, "draw": 1, "lost": 1,
     "goals_for": 1, "goals_against": 3, "goal_difference": -2},
]

PROFILES = {
    1: {"attack_home": 1.5, "attack_away": 1.3, "defence_home": 0.8, "defence_away": 0.9},
    2: {"attack_home": 0.9, "attack_away": 0.8, "defence_home": 1.2, "defence_away": 1.3},
    3: {"attack_home": 1.0, "attack_away": 1.0, "defence_home": 1.0, "defence_away": 1.0},
}


# ---------------------------------------------------------------------------
# Form
# ---------------------------------------------------------------------------

class TestForm:
    def test_sequence_newest_first(self):
        form = get_team_form(1, FIXTURES)
        assert form["sequence"] == ["L", "D", "D", "W", "W"]

    def test_points_and_score(self):
        form = get_team_form(1, FIXTURES)
        assert form["points"] == 8
        assert form["form_score"] == round(8 / 15, 2)

    def test_last_n_limits_window(self):
        form = get_team_form(1, FIXTURES, last_n=2)
        assert form["sample_size"] == 2
        assert form["sequence"] == ["L", "D"]
        assert form["points"] == 1

    def test_team_without_matches(self):
        form = get_team_form(99, FIXTURES)
        assert form["sample_size"] == 0
        assert form["form_score"] == 0.0
        assert form["sequence"] == []

    def test_empty_fixtures(self):
        form = get_team_form(1, [])
        assert form["sample_size"] == 0


# ---------------------------------------------------------------------------
# Heim / Auswaerts
# ---------------------------------------------------------------------------

class TestHomeAway:
    def test_split_counts(self):
        ha = split_home_away(1, FIXTURES)
        assert ha["home"]["played"] == 3
        assert ha["away"]["played"] == 2

    def test_points_per_side(self):
        ha = split_home_away(1, FIXTURES)
        # Heim: W(3:1) D(1:1) L(0:1) = 4 Punkte
        # Auswaerts: W(2:0) D(2:2) = 4 Punkte
        assert ha["home"]["points"] == 4
        assert ha["away"]["points"] == 4

    def test_goals_consistent_with_table(self):
        ha = split_home_away(1, FIXTURES)
        total_for = ha["home"]["goals_for"] + ha["away"]["goals_for"]
        total_against = ha["home"]["goals_against"] + ha["away"]["goals_against"]
        assert total_for == 8
        assert total_against == 5


# ---------------------------------------------------------------------------
# Power Ranking
# ---------------------------------------------------------------------------

class TestPowerRanking:
    def test_weights_sum_to_one(self):
        assert abs(sum(POWER_WEIGHTS.values()) - 1.0) < 1e-9

    def test_ranking_order_and_scores(self):
        ranking = compute_power_ranking(TABLE, PROFILES, FIXTURES)
        assert [r["rank"] for r in ranking] == [1, 2, 3]
        assert ranking[0]["team_id"] == 1
        assert all(0.0 <= r["score"] <= 100.0 for r in ranking)

    def test_scores_strictly_ordered(self):
        ranking = compute_power_ranking(TABLE, PROFILES, FIXTURES)
        scores = [r["score"] for r in ranking]
        assert scores == sorted(scores, reverse=True)

    def test_empty_table(self):
        assert compute_power_ranking([], PROFILES, FIXTURES) == []

    def test_missing_profile_defaults_neutral(self):
        # Team 2 ohne Profil: darf nicht crashen, bekommt Neutralwerte.
        profiles = {1: PROFILES[1], 3: PROFILES[3]}
        ranking = compute_power_ranking(TABLE, profiles, FIXTURES)
        assert len(ranking) == 3


# ---------------------------------------------------------------------------
# Head-to-Head
# ---------------------------------------------------------------------------

# H2H-Tests nutzen "testl" (keine historischen Dateien) und hohe
# synthetische IDs (99001/99002) die in keiner echten Ligatdatei
# auftauchen koennen.
H2H_FIXTURES = [
    {"home_id": 99001, "away_id": 99002, "home_goals": 3, "away_goals": 1, "matchday": 1},
    {"home_id": 99003, "away_id": 99001, "home_goals": 0, "away_goals": 2, "matchday": 2},
    {"home_id": 99001, "away_id": 99003, "home_goals": 1, "away_goals": 1, "matchday": 3},
    {"home_id": 99002, "away_id": 99001, "home_goals": 2, "away_goals": 2, "matchday": 4},
    {"home_id": 99001, "away_id": 99002, "home_goals": 0, "away_goals": 1, "matchday": 5},
]


class TestHeadToHead:
    def test_current_season_only(self):
        h2h = get_head_to_head("testl", 99001, 99002, current_finished=H2H_FIXTURES)
        # MD1 3:1 (A), MD4 2:2 (D), MD5 0:1 (B)
        assert h2h["matches_considered"] == 3
        assert h2h["wins_a"] == 1
        assert h2h["draws"] == 1
        assert h2h["wins_b"] == 1
        assert h2h["goals_a"] == 5
        assert h2h["goals_b"] == 4

    def test_sum_invariant(self):
        h2h = get_head_to_head("testl", 99001, 99002, current_finished=H2H_FIXTURES)
        assert (h2h["wins_a"] + h2h["wins_b"] + h2h["draws"]
                == h2h["matches_considered"])

    def test_no_meetings(self):
        h2h = get_head_to_head("testl", 99001, 99999, current_finished=H2H_FIXTURES)
        assert h2h["matches_considered"] == 0
        assert h2h["last_meetings"] == []

    def test_symmetry(self):
        ab = get_head_to_head("testl", 99001, 99002, current_finished=H2H_FIXTURES)
        ba = get_head_to_head("testl", 99002, 99001, current_finished=H2H_FIXTURES)
        assert ab["wins_a"] == ba["wins_b"]
        assert ab["goals_a"] == ba["goals_b"]
        assert ab["matches_considered"] == ba["matches_considered"]

    def test_newest_meeting_first(self):
        h2h = get_head_to_head("testl", 99001, 99002, current_finished=H2H_FIXTURES)
        matchdays = [m["matchday"] for m in h2h["last_meetings"]]
        assert matchdays == sorted(matchdays, reverse=True)


# ---------------------------------------------------------------------------
# Team Summary
# ---------------------------------------------------------------------------

class TestTeamSummary:
    def test_full_summary(self):
        ranking = compute_power_ranking(TABLE, PROFILES, FIXTURES)
        summary = get_team_summary(1, TABLE, PROFILES, FIXTURES, ranking)
        assert summary["season_stats"]["position"] == 1
        assert summary["per_game"]["points"] == 1.6
        assert summary["form"]["sample_size"] == 5
        assert summary["home_away"]["home"]["played"] == 3
        assert summary["power"]["rank"] == 1
        assert summary["strength"]["attack_home"] == 1.5

    def test_unknown_team_returns_none(self):
        assert get_team_summary(99, TABLE, PROFILES, FIXTURES) is None

    def test_summary_without_ranking(self):
        summary = get_team_summary(1, TABLE, PROFILES, FIXTURES)
        assert summary["power"] is None

    def test_per_game_zero_safe(self):
        table = [dict(TABLE[0], played=0, points=0)]
        summary = get_team_summary(1, table, PROFILES, [])
        assert summary["per_game"]["points"] == 0.0
