"""
Invariantentests der Saisonsimulation und der Liga-Einzelspielsimulation.

Alle Tests laufen mit synthetischen Daten, deterministisch per Seed.
"""

import pytest

from src.features import strength_provider
from src.predict import fixture_plan
from src.predict.season_sim import simulate_season
from src.predict import league_match_sim
from tests.conftest import (
    make_historical_payload,
    make_round_robin_raw,
    make_standings_table,
)


TEAMS = list(range(1, 19))
PROMOTED = [200, 201]
CURRENT = TEAMS[:-2] + PROMOTED


def patch_history(monkeypatch, history_by_season):
    def fake_load(api_code, seasons=None):
        return [(s, history_by_season[s])
                for s in sorted(history_by_season, reverse=True)]
    monkeypatch.setattr(strength_provider, "load_available_seasons", fake_load)


def default_history():
    return {
        2025: make_historical_payload(TEAMS, season=2025, strong=[1], weak=[16]),
        2024: make_historical_payload(TEAMS, season=2024, strong=[1], weak=[16]),
    }


def build_plan(team_ids, finished_matchdays=0):
    raw = make_round_robin_raw(team_ids, finished_matchdays=finished_matchdays)
    original = fixture_plan.load_full_season_matches
    fixture_plan.load_full_season_matches = lambda code, season=None: (raw, 2026)
    try:
        return fixture_plan.build_season_plan("TEST", season=2026,
                                              expected_team_count=len(team_ids))
    finally:
        fixture_plan.load_full_season_matches = original


def run_sim(monkeypatch, team_ids=None, simulations=400, seed=7,
            finished_matchdays=0, history=None):
    team_ids = team_ids or CURRENT
    patch_history(monkeypatch, history if history is not None else default_history())
    plan = build_plan(team_ids, finished_matchdays=finished_matchdays)
    assert plan["coverage"]["ok"], plan["coverage"]["problems"]

    return simulate_season(
        competition_code="bl1",
        standings_table=make_standings_table(team_ids),
        remaining_matches=plan["remaining_matches"],
        simulations=simulations,
        current_matches=plan["finished_matches"],
        seed=seed,
        season=2026,
        fixture_coverage=plan["coverage"],
    ), plan


# ---------------------------------------------------------------------------
# Routentests ohne Anbieter
# ---------------------------------------------------------------------------
#
# Die drei Routentests weiter unten hatten frueher UEBERHAUPT keine
# Ersatzquelle. Sie riefen /api/season-sim und /api/cl-season-sim direkt
# auf und erreichten damit den echten Anbieter. Lokal fiel das nicht auf,
# weil .env einen Schluessel enthaelt und data/cache gefuellt ist. Im
# frischen CI-Checkout gibt es beides nicht, und die Routen antworteten
# ehrlich mit 503 "FOOTBALL_API_KEY fehlt in der .env".
#
# Ein Dummy-Schluessel waere die falsche Abhilfe: Er wuerde echte
# Netzabrufe ausloesen statt sie zu verhindern. Stattdessen wird die
# Datenquelle dort ersetzt, wo sie in die Route eintritt.


def patch_season_sim_quellen(monkeypatch, team_ids=None):
    """
    Ersetzt die beiden Datenquellen von /api/season-sim.

    app.py importiert get_standings und build_season_plan in seinen
    eigenen Namensraum - also muss dort gepatcht werden, nicht im
    Ursprungsmodul. Der Plan entsteht ueber den ECHTEN Planbauer aus
    synthetischen Partien, damit die Abdeckungspruefung der Route
    wirklich durchlaeuft und nicht umgangen wird.
    """
    import app as app_module

    team_ids = team_ids or CURRENT
    patch_history(monkeypatch, default_history())
    plan = build_plan(team_ids)
    assert plan["coverage"]["ok"], plan["coverage"]["problems"]

    monkeypatch.setattr(app_module, "get_standings",
                        lambda code, season=None: {
                            "tables": {"TOTAL": make_standings_table(team_ids)}})
    monkeypatch.setattr(app_module, "build_season_plan", lambda *a, **k: plan)
    return plan


def patch_cl_season_sim_quellen(monkeypatch):
    """
    Ersetzt die Datenquelle von /api/cl-season-sim.

    Gepatcht wird get_all_matches im Fixture-Plan-Modul - die Stelle, an
    der die Anbieterdaten ins Projekt kommen. Alles danach (Planaufbau,
    Abdeckungspruefung, Simulation) laeuft echt.

    Die Teamzahl richtet sich nach der echten Konfiguration: Bei acht
    Partien je Team braucht eine vollstaendige Einfachrunde neun Teams.
    Mit weniger scheitert die Abdeckungspruefung der Route zu Recht.
    """
    import app as app_module
    import src.predict.cl_fixture_plan as cl_plan_modul

    # Der Rohdatenbauer liegt bereits in tests/test_cl_season_sim.py.
    # Ihn hier zu importieren ist ehrlicher, als ihn ein zweites Mal
    # aufzuschreiben - zwei Fassungen wuerden auseinanderlaufen.
    from tests.test_cl_season_sim import _round_robin_raw

    partien_je_team = app_module.CL_LEAGUE_PHASE_CONFIG["total_matchdays"]
    raw = _round_robin_raw(partien_je_team + 1, finished=False)

    monkeypatch.setattr(cl_plan_modul, "get_all_matches", lambda *a, **k: raw)
    monkeypatch.setattr(cl_plan_modul, "resolve_season",
                        lambda api_code, s=None: 2025)
    return raw


@pytest.fixture
def kein_netzwerk(monkeypatch):
    """
    Sperrt jeden Verbindungsaufbau.

    Die Zusicherung, um die es hier geht: Diese Tests duerfen den
    Anbieter nicht erreichen. Ohne die Sperre faellt ein fehlender
    Patchpunkt nicht auf - der Test wuerde still einen Request
    verbrauchen und trotzdem gruen sein.
    """
    import socket

    def gesperrt(*args, **kwargs):
        raise AssertionError(
            "Ein Routentest hat eine Netzverbindung aufgebaut - eine "
            "Datenquelle ist nicht ersetzt worden."
        )

    monkeypatch.setattr(socket.socket, "connect", gesperrt)
    monkeypatch.setattr(socket, "create_connection", gesperrt)


# ---------------------------------------------------------------------------
# Saisonsimulation
# ---------------------------------------------------------------------------

def test_full_season_simulates_every_fixture(monkeypatch):
    result, plan = run_sim(monkeypatch)

    report = result["fixture_report"]
    assert report["fixtures_to_simulate"] == 306
    assert report["fixtures_prepared"] == 306
    assert report["fixtures_simulated_per_run"] == 306
    assert report["fixtures_rejected"] == 0
    assert report["fixtures_with_fallback_profile"] == 0
    assert result["games_remaining"] == 306


def test_each_team_has_correct_remaining_match_count(monkeypatch):
    result, _ = run_sim(monkeypatch)
    for entry in result["entries"]:
        assert entry["games_remaining"] == 34


def test_seed_is_deterministic(monkeypatch):
    result_a, _ = run_sim(monkeypatch, seed=42)
    result_b, _ = run_sim(monkeypatch, seed=42)

    points_a = [e["expected_points"] for e in result_a["entries"]]
    points_b = [e["expected_points"] for e in result_b["entries"]]
    assert points_a == points_b


def test_ranks_are_contiguous(monkeypatch):
    result, _ = run_sim(monkeypatch)
    ranks = [entry["rank"] for entry in result["entries"]]
    assert ranks == list(range(1, len(result["entries"]) + 1))


def test_display_rank_matches_sorted_order(monkeypatch):
    """Anzeigereihenfolge und Rangnummer laufen nie auseinander."""
    result, _ = run_sim(monkeypatch)
    positions = [entry["expected_position"] for entry in result["entries"]]
    assert positions == sorted(positions)
    for index, entry in enumerate(result["entries"], start=1):
        assert entry["rank"] == index


def test_champion_probabilities_sum_to_100(monkeypatch):
    result, _ = run_sim(monkeypatch)
    total = sum(entry["champion_pct"] for entry in result["entries"])
    assert abs(total - 100.0) < 1.5  # Rundung je Team auf eine Stelle


def test_cl_probabilities_sum_to_spots_times_100(monkeypatch):
    result, _ = run_sim(monkeypatch)
    cl_spots = result["zones"]["cl"]
    total = sum(entry["cl_pct"] for entry in result["entries"])
    assert abs(total - cl_spots * 100.0) < 3.0


def test_relegation_probabilities_sum_to_spots(monkeypatch):
    result, _ = run_sim(monkeypatch)
    rel_positions = result["zones"]["relegation"]
    total = sum(entry["relegation_pct"] for entry in result["entries"])
    assert abs(total - len(rel_positions) * 100.0) < 3.0


def test_expected_points_are_consistent(monkeypatch):
    """
    Punktesumme aller Teams = bisherige Punkte + je Spiel 2 oder 3 neue.
    Bei 306 Spielen liegt die Summe zwischen 2x306 und 3x306.
    """
    result, _ = run_sim(monkeypatch)
    total = sum(entry["expected_points"] for entry in result["entries"])
    assert 2 * 306 <= total <= 3 * 306

    for entry in result["entries"]:
        # 18er-Liga: maximal 34 Siege = 102 Punkte
        assert 0 <= entry["expected_points"] <= 102


def test_strong_team_beats_weak_team_in_expectation(monkeypatch):
    result, _ = run_sim(monkeypatch, team_ids=TEAMS)
    by_id = {}
    for entry, row in zip(result["entries"], result["entries"]):
        pass
    entries = {e["team_name"]: e for e in result["entries"]}
    strong = entries["Team 1"]
    weak = entries["Team 16"]
    assert strong["expected_points"] > weak["expected_points"]
    assert strong["expected_position"] < weak["expected_position"]


def test_promoted_teams_are_flagged_and_simulated(monkeypatch):
    """Aufsteiger tauchen markiert auf und kein Fixture fehlt."""
    result, plan = run_sim(monkeypatch)

    promoted_entries = [e for e in result["entries"] if e["is_promoted"] is True]
    assert len(promoted_entries) == len(PROMOTED)
    assert result["data_quality"]["teams_promoted"] == len(PROMOTED)

    # Kein Fixture mit Aufsteiger wurde uebersprungen:
    assert result["fixture_report"]["fixtures_to_simulate"] == 306


def test_matchday_filter_not_used_for_season_simulation(monkeypatch):
    """
    Regressionstest fuer den urspruenglichen Bug: Die Saisonsimulation
    darf an Spieltag 0 NIEMALS nur einen Spieltag (9 Spiele) erhalten.
    """
    result, plan = run_sim(monkeypatch)
    assert result["games_remaining"] != 9
    assert result["games_remaining"] == 306
    for entry in result["entries"]:
        assert entry["games_remaining"] != 1


def test_mid_season_uses_real_results(monkeypatch):
    result, plan = run_sim(monkeypatch, team_ids=TEAMS, finished_matchdays=5)
    assert result["games_remaining"] == 261
    assert len(plan["finished_matches"]) == 45


# ---------------------------------------------------------------------------
# Liga-Einzelspielsimulation
# ---------------------------------------------------------------------------

def patch_league_match_env(monkeypatch, team_ids, history):
    patch_history(monkeypatch, history)
    monkeypatch.setattr(
        league_match_sim, "get_standings",
        lambda api_code, season=None: {
            "season": 2026,
            "tables": {"TOTAL": make_standings_table(team_ids)},
        },
    )
    monkeypatch.setattr(
        league_match_sim, "resolve_season",
        lambda api_code, season=None: season or 2026,
    )
    # In-Memory-Cache zwischen Tests leeren.
    from src.utils import cache
    cache.invalidate_prefix("league_strengths:")


def simulate(monkeypatch, home_id, away_id, home_name=None, away_name=None):
    patch_league_match_env(monkeypatch, CURRENT, default_history())
    return league_match_sim.simulate_league_match(
        competition_code="bl1",
        api_code="BL1",
        home_team=home_name or f"Team {home_id}",
        away_team=away_name or f"Team {away_id}",
        home_id=home_id,
        away_id=away_id,
        season=2026,
        simulations=2000,
        use_seed=True,
    )


def assert_valid_result(result):
    assert result["expected_home_goals"] is not None
    assert result["expected_away_goals"] is not None
    assert result["home_win_probability"] >= 0
    assert result["draw_probability"] >= 0
    assert result["away_win_probability"] >= 0
    total = (result["home_win_probability"] + result["draw_probability"]
             + result["away_win_probability"])
    assert abs(total - 100.0) < 0.5


def test_established_vs_established(monkeypatch):
    result = simulate(monkeypatch, 3, 5)
    assert_valid_result(result)
    assert result["home_data"]["resolution"] == "id"


def test_promoted_vs_established(monkeypatch):
    result = simulate(monkeypatch, PROMOTED[0], 3)
    assert_valid_result(result)
    assert result["home_data"]["is_promoted"] is True


def test_established_vs_promoted(monkeypatch):
    result = simulate(monkeypatch, 3, PROMOTED[0])
    assert_valid_result(result)
    assert result["away_data"]["is_promoted"] is True


def test_promoted_vs_promoted(monkeypatch):
    result = simulate(monkeypatch, PROMOTED[0], PROMOTED[1])
    assert_valid_result(result)


def test_unknown_team_still_simulates(monkeypatch):
    """Selbst ein voellig unbekanntes Team fuehrt nie zum Abbruch."""
    patch_league_match_env(monkeypatch, CURRENT, default_history())
    result = league_match_sim.simulate_league_match(
        competition_code="bl1", api_code="BL1",
        home_team="Voellig Unbekannt", away_team="Team 3",
        home_id=None, away_id=3, season=2026,
        simulations=1000, use_seed=True,
    )
    assert_valid_result(result)
    assert result["home_data"]["resolution"] == "neutral"


def test_name_only_resolution(monkeypatch):
    """Ohne IDs klappt die Aufloesung ueber den Tabellennamen."""
    patch_league_match_env(monkeypatch, CURRENT, default_history())
    result = league_match_sim.simulate_league_match(
        competition_code="bl1", api_code="BL1",
        home_team="Team 3", away_team="Team 5",
        home_id=None, away_id=None, season=2026,
        simulations=1000, use_seed=True,
    )
    assert_valid_result(result)
    assert result["home_data"]["resolution"] in ("standings_name", "alias")

def test_api_season_sim_minimum_simulations(monkeypatch, kein_netzwerk):
    from app import app

    patch_season_sim_quellen(monkeypatch)
    with app.test_client() as client:
        # Request exactly 100 simulations
        res = client.get('/api/season-sim?competition=bl1&simulations=100')
        assert res.status_code == 200, res.get_json()
        data = res.get_json()
        assert data['simulations'] == 100

def test_api_cl_season_sim_minimum_simulations(monkeypatch, kein_netzwerk):
    from app import app

    patch_cl_season_sim_quellen(monkeypatch)
    with app.test_client() as client:
        # Request exactly 100 simulations
        res = client.get('/api/cl-season-sim?season=2025&simulations=100')
        assert res.status_code == 200, res.get_json()
        data = res.get_json()
        assert data['simulations'] == 100


def test_api_season_sim_invalid_simulations():
    from app import app
    with app.test_client() as client:
        # 0 is invalid
        res = client.get('/api/season-sim?competition=bl1&simulations=0')
        assert res.status_code == 400
        assert '1 und 50.000' in res.get_json()['error']
        
        # 50001 is invalid
        res = client.get('/api/season-sim?competition=bl1&simulations=50001')
        assert res.status_code == 400
        
        # strings are invalid
        res = client.get('/api/season-sim?competition=bl1&simulations=abc')
        assert res.status_code == 400
        assert 'Simulationen' in res.get_json()['error']

def test_api_season_sim_minimum_one(monkeypatch, kein_netzwerk):
    from app import app

    patch_season_sim_quellen(monkeypatch)
    with app.test_client() as client:
        # Request exactly 1 simulation
        res = client.get('/api/season-sim?competition=bl1&simulations=1')
        assert res.status_code == 200, res.get_json()
        assert res.get_json()['simulations'] == 1

