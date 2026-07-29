"""Spielplan-Aufteilung und Coverage-Validierung (Audit §2, §9, §11)."""
from src.predict.fixture_plan import partition_season_matches, validate_fixture_coverage
from tests.conftest import build_raw_season, standings_from


def _run(team_ids, **kwargs):
    raw = build_raw_season(team_ids, **kwargs)
    plan = partition_season_matches(raw)
    table = standings_from(team_ids, finished=plan["finished"])
    cov = validate_fixture_coverage(table, plan["finished"], plan["remaining"], plan["excluded"])
    return plan, cov


def test_18er_liga_spieltag_0_hat_306_offene_spiele():
    plan, cov = _run(list(range(1, 19)))
    assert len(plan["remaining"]) == 306
    assert len(plan["finished"]) == 0
    assert plan["played_matchdays"] == 0
    assert cov["complete"] is True
    assert cov["expected_matches_per_team"] == 34


def test_20er_liga_spieltag_0_hat_380_offene_spiele():
    plan, cov = _run(list(range(1, 21)))
    assert len(plan["remaining"]) == 380
    assert cov["complete"] is True
    assert cov["expected_matches_per_team"] == 38


def test_laufende_saison_zaehlt_echte_spiele_nicht_spieltag_mal_neun():
    plan, cov = _run(list(range(1, 19)), finished_matchdays=5)
    assert len(plan["finished"]) == 45
    assert len(plan["remaining"]) == 261
    assert plan["played_matchdays"] == 5
    assert cov["complete"] is True


def test_verschobenes_spiel_bleibt_im_plan():
    plan, cov = _run(list(range(1, 19)), finished_matchdays=5, postponed_indices={100, 101, 102})
    assert len(plan["remaining"]) == 261  # POSTPONED zaehlt als offen
    assert plan["status_counts"].get("POSTPONED") == 3
    assert cov["complete"] is True


def test_abgesagtes_spiel_wird_dokumentiert_nicht_verschluckt():
    plan, cov = _run(list(range(1, 19)), cancelled_indices={200, 201})
    assert len(plan["excluded"]) == 2
    assert all(e["reason"] == "cancelled" for e in plan["excluded"])
    assert cov["fixtures_to_simulate"] == 304
    assert cov["complete"] is True  # dokumentiert ausgeschlossen != verloren


def test_fehlende_team_id_macht_coverage_unvollstaendig():
    plan, cov = _run(list(range(1, 19)), missing_id_indices={10})
    assert any(e["reason"] == "missing_team_id" for e in plan["excluded"])
    assert cov["complete"] is False
    assert cov["per_team_problems"]


def test_fremdes_team_im_spielplan_faellt_auf():
    raw = build_raw_season(list(range(1, 19)))
    raw.append({"status": "SCHEDULED", "matchday": 1,
                "homeTeam": {"id": 999, "name": "Geisterteam"},
                "awayTeam": {"id": 1, "name": "Team 1"},
                "score": {"fullTime": {"home": None, "away": None}}})
    plan = partition_season_matches(raw)
    table = standings_from(list(range(1, 19)))
    cov = validate_fixture_coverage(table, plan["finished"], plan["remaining"], plan["excluded"])
    assert cov["complete"] is False
    assert cov["fixtures_unknown_team"] >= 1
