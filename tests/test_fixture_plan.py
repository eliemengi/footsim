"""
Tests fuer den Saisonspielplan (fixture_plan).

Prueft die Ligastruktur unabhaengig von konkreten Teamnamen:
Doppelrunde, Spiele pro Team, Verhalten an Spieltag 0, waehrend der
Saison und mit verschobenen Spielen. Nichts davon braucht Netzwerk -
die Klassifizierung wird direkt auf Rohspielen getestet.
"""

from collections import defaultdict

import pytest

from src.predict import fixture_plan
from tests.conftest import make_round_robin_raw


def classify(raw_matches, expected_team_count=None, monkeypatch=None):
    """build_season_plan mit eingeschobenen Rohdaten (kein Netzwerk)."""
    def fake_loader(api_code, season=None):
        return raw_matches, season or 2026
    original = fixture_plan.load_full_season_matches
    fixture_plan.load_full_season_matches = fake_loader
    try:
        return fixture_plan.build_season_plan(
            "TEST", season=2026, expected_team_count=expected_team_count
        )
    finally:
        fixture_plan.load_full_season_matches = original


# ---------------------------------------------------------------------------
# Ligastruktur
# ---------------------------------------------------------------------------

def test_18_team_league_has_306_matches():
    raw = make_round_robin_raw(list(range(1, 19)))
    plan = classify(raw, expected_team_count=18)

    assert plan["coverage"]["teams"] == 18
    assert plan["coverage"]["expected_total"] == 306
    assert plan["coverage"]["fixtures_received"] == 306
    assert plan["coverage"]["ok"] is True


def test_20_team_league_has_380_matches():
    raw = make_round_robin_raw(list(range(1, 21)))
    plan = classify(raw, expected_team_count=20)

    assert plan["coverage"]["expected_total"] == 380
    assert plan["coverage"]["fixtures_received"] == 380
    assert plan["coverage"]["ok"] is True


def test_matchday_zero_all_matches_remaining():
    """Spieltag 0: 0 beendet, komplette Saison offen, 34 Spiele je Team."""
    raw = make_round_robin_raw(list(range(1, 19)), finished_matchdays=0)
    plan = classify(raw)

    assert len(plan["finished_matches"]) == 0
    assert len(plan["remaining_matches"]) == 306
    assert plan["played_matchdays"] == 0

    per_team = defaultdict(int)
    for match in plan["remaining_matches"]:
        per_team[match["home_id"]] += 1
        per_team[match["away_id"]] += 1
    assert all(count == 34 for count in per_team.values())


def test_matchday_zero_20_teams_38_per_team():
    raw = make_round_robin_raw(list(range(1, 21)), finished_matchdays=0)
    plan = classify(raw)

    per_team = defaultdict(int)
    for match in plan["remaining_matches"]:
        per_team[match["home_id"]] += 1
        per_team[match["away_id"]] += 1
    assert all(count == 38 for count in per_team.values())


def test_mid_season_counts_actual_matches():
    """Nach 5 vollen Spieltagen einer 18er-Liga: 45 beendet, 261 offen."""
    raw = make_round_robin_raw(list(range(1, 19)), finished_matchdays=5)
    plan = classify(raw)

    assert len(plan["finished_matches"]) == 45
    assert len(plan["remaining_matches"]) == 261
    assert plan["played_matchdays"] == 5
    assert plan["coverage"]["ok"] is True


def test_mid_season_20_teams():
    """Nach 5 Spieltagen einer 20er-Liga: 50 beendet, 330 offen."""
    raw = make_round_robin_raw(list(range(1, 21)), finished_matchdays=5)
    plan = classify(raw)

    assert len(plan["finished_matches"]) == 50
    assert len(plan["remaining_matches"]) == 330


def test_postponed_match_stays_remaining():
    """
    Ein verschobenes Spiel eines frueheren Spieltags bleibt offen.
    Die Zaehlung darf NICHT Spieltag x Spiele-pro-Spieltag annehmen.
    """
    raw = make_round_robin_raw(list(range(1, 19)), finished_matchdays=5)

    # Ein Spiel von Spieltag 3 nachtraeglich auf POSTPONED setzen.
    for match in raw:
        if match["matchday"] == 3:
            match["status"] = "POSTPONED"
            match["score"] = {"fullTime": {"home": None, "away": None}}
            break

    plan = classify(raw)

    assert len(plan["finished_matches"]) == 44
    assert len(plan["remaining_matches"]) == 262
    assert plan["coverage"]["ok"] is True

    statuses = {m["status"] for m in plan["remaining_matches"]}
    assert "POSTPONED" in statuses


def test_no_fixture_silently_disappears():
    """Jedes Spiel landet in genau einer der drei Kategorien."""
    raw = make_round_robin_raw(list(range(1, 21)), finished_matchdays=7)

    # Ein Spiel kuenstlich beschaedigen (Team-ID fehlt).
    raw[5]["homeTeam"]["id"] = None
    # Ein FINISHED ohne Ergebnis.
    raw[40]["score"] = {"fullTime": {"home": None, "away": None}}
    # Ein exotischer Status.
    raw[100]["status"] = "CANCELLED"
    raw[100]["score"] = {"fullTime": {"home": None, "away": None}}

    plan = classify(raw)
    coverage = plan["coverage"]

    total = (len(plan["finished_matches"]) + len(plan["remaining_matches"])
             + len(plan["invalid_matches"]))
    assert total == 380
    assert coverage["fixtures_received"] == 380
    assert len(plan["invalid_matches"]) == 3

    reasons = {entry["reason"] for entry in plan["invalid_matches"]}
    assert "team_id_missing" in reasons
    assert "finished_without_score" in reasons
    assert any(reason.startswith("unhandled_status") for reason in reasons)


def test_incomplete_plan_fails_validation():
    """Fehlen Spiele, wird der Plan als unvollstaendig markiert."""
    raw = make_round_robin_raw(list(range(1, 19)))
    incomplete = raw[:-9]  # letzter Spieltag fehlt komplett

    plan = classify(incomplete)

    assert plan["coverage"]["ok"] is False
    assert plan["coverage"]["problems"]


def test_team_count_mismatch_is_flagged():
    raw = make_round_robin_raw(list(range(1, 19)))
    plan = classify(raw, expected_team_count=20)

    assert plan["coverage"]["ok"] is True or plan["coverage"]["problems"]
    assert any("Teamanzahl" in problem for problem in plan["coverage"]["problems"])


def test_non_regular_season_stage_is_ignored():
    """Relegations-/Playoff-Spiele verfaelschen die 306er-Rechnung nicht."""
    raw = make_round_robin_raw(list(range(1, 19)))
    raw.append({
        "id": 99999, "stage": "PLAYOFFS", "matchday": None,
        "status": "SCHEDULED",
        "homeTeam": {"id": 16, "name": "Team 16"},
        "awayTeam": {"id": 999, "name": "Zweitligist"},
        "score": {"fullTime": {"home": None, "away": None}},
    })

    plan = classify(raw)
    assert plan["coverage"]["fixtures_received"] == 306
    assert plan["coverage"]["ok"] is True
