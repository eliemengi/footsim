"""
End-to-End-Tests mit den ECHTEN, im Disk-Cache liegenden Saisondaten
(La Liga und Ligue 1, Saison 2026/27). Komplett offline.

Diese Tests belegen mit realen API-Daten:
  * 380 bzw. 306 Fixtures an Spieltag 0
  * 38 bzw. 34 offene Spiele je Team
  * vollstaendige Monte-Carlo-Laeufe mit allen Invarianten
  * der urspruengliche Bug (nur 10 Fixtures) ist behoben
"""

from collections import defaultdict

import pytest

from src.predict import fixture_plan
from src.predict.season_sim import simulate_season


def plan_from_raw(raw_matches, api_code, expected_team_count):
    original = fixture_plan.load_full_season_matches
    fixture_plan.load_full_season_matches = lambda code, season=None: (raw_matches, 2026)
    try:
        return fixture_plan.build_season_plan(
            api_code, season=2026, expected_team_count=expected_team_count
        )
    finally:
        fixture_plan.load_full_season_matches = original


def test_real_pd_plan_has_380_fixtures(cached_pd_matches):
    plan = plan_from_raw(cached_pd_matches, "PD", 20)

    assert plan["coverage"]["teams"] == 20
    assert plan["coverage"]["fixtures_received"] == 380
    assert len(plan["remaining_matches"]) + len(plan["finished_matches"]) == 380
    assert plan["coverage"]["ok"] is True

    per_team = defaultdict(int)
    for match in plan["remaining_matches"]:
        per_team[match["home_id"]] += 1
        per_team[match["away_id"]] += 1
    for match in plan["finished_matches"]:
        per_team[match["home_id"]] += 1
        per_team[match["away_id"]] += 1

    assert len(per_team) == 20
    assert all(count == 38 for count in per_team.values())


def test_real_fl1_plan_has_306_fixtures(cached_fl1_matches):
    plan = plan_from_raw(cached_fl1_matches, "FL1", 18)

    assert plan["coverage"]["teams"] == 18
    assert plan["coverage"]["fixtures_received"] == 306
    assert plan["coverage"]["ok"] is True

    per_team = defaultdict(int)
    for match in plan["remaining_matches"]:
        per_team[match["home_id"]] += 1
        per_team[match["away_id"]] += 1
    assert all(count == 34 for count in per_team.values())


def test_real_pd_regression_not_only_matchday_one(cached_pd_matches):
    """
    Direkter Regressionstest gegen den Original-Bug: Vorher landeten
    exakt 10 Fixtures (ein Spieltag) in der Simulation.
    """
    plan = plan_from_raw(cached_pd_matches, "PD", 20)
    assert len(plan["remaining_matches"]) != 10
    assert len(plan["remaining_matches"]) == 380


def test_real_pd_full_season_simulation(cached_pd_matches, cached_pd_standings):
    """Vollstaendiger Monte-Carlo-Lauf auf echten La-Liga-Daten."""
    plan = plan_from_raw(cached_pd_matches, "PD", 20)
    table = cached_pd_standings["tables"]["TOTAL"]

    result = simulate_season(
        competition_code="pd",
        standings_table=table,
        remaining_matches=plan["remaining_matches"],
        simulations=300,
        current_matches=plan["finished_matches"],
        seed=1,
        season=2026,
        fixture_coverage=plan["coverage"],
    )

    assert result["games_remaining"] == 380
    assert len(result["entries"]) == 20

    # Raenge lueckenlos 1..20
    assert [e["rank"] for e in result["entries"]] == list(range(1, 21))

    # Meisterwahrscheinlichkeit summiert sich auf 100
    total = sum(e["champion_pct"] for e in result["entries"])
    assert abs(total - 100.0) < 1.5

    # Jedes Team: 38 offene Spiele, erwartete Punkte im gueltigen Bereich
    for entry in result["entries"]:
        assert entry["games_remaining"] == 38
        assert 0 <= entry["expected_points"] <= 114
        assert entry["expected_position"] is not None

    # Kein Fixture verschwunden
    report = result["fixture_report"]
    assert report["fixtures_simulated_per_run"] == 380
    assert report["fixtures_rejected"] == 0
    assert report["coverage_ok"] is True


def test_real_pd_barcelona_and_real_madrid_are_top(cached_pd_matches,
                                                   cached_pd_standings):
    """
    Plausibilitaet nach dem Fix: Barcelona (2x Meister in Folge) und
    Real Madrid gehoeren nach dem historischen Modell in die Spitzengruppe,
    nicht auf Rang 5 oder tiefer. Kein Hardcode - nur eine Warnschwelle.
    """
    plan = plan_from_raw(cached_pd_matches, "PD", 20)
    table = cached_pd_standings["tables"]["TOTAL"]

    result = simulate_season(
        competition_code="pd",
        standings_table=table,
        remaining_matches=plan["remaining_matches"],
        simulations=400,
        current_matches=plan["finished_matches"],
        seed=3,
        season=2026,
        fixture_coverage=plan["coverage"],
    )

    ranks = {
        (e.get("team_full_name") or e["team_name"]): e["rank"]
        for e in result["entries"]
    }
    barcelona = next((r for name, r in ranks.items()
                      if "Barcelona" in name or "Barça" in name), None)
    real = next((r for name, r in ranks.items() if "Real Madrid" in name), None)

    assert barcelona is not None and barcelona <= 3, f"Barcelona auf Rang {barcelona}"
    assert real is not None and real <= 4, f"Real Madrid auf Rang {real}"
