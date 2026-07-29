"""Invarianten der vollen Saisonsimulation (Audit §6, §13)."""
import pytest
from src.predict.season_sim import simulate_season
from src.predict.fixture_plan import partition_season_matches, validate_fixture_coverage
from tests.conftest import build_raw_season, standings_from

IDS = list(range(1, 19))


def _setup(test_league, finished_matchdays=0):
    names = {i: f"Klub {i}" for i in IDS}
    test_league["write"]("TESTL", 2025, IDS, names)
    test_league["write"]("TESTL", 2024, IDS, names)
    raw = build_raw_season(IDS, names=names, finished_matchdays=finished_matchdays)
    plan = partition_season_matches(raw)
    table = standings_from(IDS, names=names, finished=plan["finished"])
    cov = validate_fixture_coverage(table, plan["finished"], plan["remaining"], plan["excluded"])
    assert cov["complete"] is True
    return table, plan


def test_spieltag_0_simuliert_alle_306_partien_und_34_pro_team(test_league):
    table, plan = _setup(test_league)
    result = simulate_season("testl", table, plan["remaining"],
                             simulations=200, current_matches=plan["finished"], seed=42)
    assert result["fixture_audit"]["fixtures_prepared"] == 306
    assert result["games_remaining"] == 306
    assert all(e["games_remaining"] == 34 for e in result["entries"])
    assert all(e["expected_points"] is not None for e in result["entries"])


def test_raenge_lueckenlos_und_meisterwahrscheinlichkeit_summiert_100(test_league):
    table, plan = _setup(test_league)
    result = simulate_season("testl", table, plan["remaining"], simulations=300, seed=1)
    assert [e["rank"] for e in result["entries"]] == list(range(1, 19))
    assert sum(e["champion_pct"] for e in result["entries"]) == pytest.approx(100.0, abs=0.75)


def test_gleicher_seed_liefert_identisches_ergebnis(test_league):
    table, plan = _setup(test_league)
    a = simulate_season("testl", table, plan["remaining"], simulations=200, seed=99)
    b = simulate_season("testl", table, plan["remaining"], simulations=200, seed=99)
    assert [(e["team_id"], e["champion_pct"], e["expected_points"]) for e in a["entries"]] == \
           [(e["team_id"], e["champion_pct"], e["expected_points"]) for e in b["entries"]]


def test_laufende_saison_uebernimmt_reale_tabelle(test_league):
    table, plan = _setup(test_league, finished_matchdays=5)
    result = simulate_season("testl", table, plan["remaining"],
                             simulations=200, current_matches=plan["finished"], seed=3)
    assert result["fixture_audit"]["fixtures_prepared"] == 261
    fuehrender = max(table, key=lambda r: r["points"])
    entry = next(e for e in result["entries"] if e["team_id"] == fuehrender["team_id"])
    assert entry["current_points"] == fuehrender["points"]
    assert entry["expected_points"] >= fuehrender["points"]
