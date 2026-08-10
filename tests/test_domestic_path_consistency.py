"""
Tests fuer die einheitliche Datengrundlage beider Domestic-Pfade.

Das Problem
-----------
Die Einzelspielsimulation uebergab current_matches=None, die
Saisonsimulation die tatsaechlich gespielten Partien. Zwei produktive
Pfade rechneten also mit unterschiedlicher Teamstaerke, obwohl sie
denselben Kenntnisstand hatten.

Praktisch hiess das: Wer Bayern gegen Dortmund einzeln simulierte, bekam
andere Erwartungswerte als fuer dieselbe Partie innerhalb der
Saisonsimulation. Ein Aufsteiger mit ueberraschend starker Hinrunde
blieb in der Einzelsimulation dauerhaft ein Aufsteiger.

War das Absicht?
----------------
Nein. Im Code stand keine Begruendung, kein Kommentar, kein Test - es
sah nach einem Versehen aus, nicht nach einer Entscheidung. Die
Saisonsimulation, die spaeter entstand, machte es von Anfang an richtig.

Kein Leak
---------
Verwendet werden ausschliesslich ABGESCHLOSSENE Partien der laufenden
Saison. Das ist genau der Kenntnisstand zum Simulationszeitpunkt. Ein
Test unten haelt das ausdruecklich fest.
"""

import pytest

from tests.conftest import (
    make_historical_payload,
    make_round_robin_raw,
    make_standings_table,
)


TEAM_IDS = [10, 11, 12, 13]


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """
    Verdrahtet beide Pfade gegen dieselben synthetischen Daten:
    dieselbe Historie, denselben Saisonstand, kein Netzwerk.

    Der Disk-Cache wird dabei auf ein leeres Verzeichnis umgebogen. Ohne
    das liefert data/cache/season_full_matches__BL1__2026.json die echte
    Bundesliga-Saison, der Loader wird nie aufgerufen und der Test misst
    etwas voellig anderes als beabsichtigt.
    """
    import src.features.strength_provider as sp
    import src.predict.league_match_sim as lms
    import src.predict.fixture_plan as fp
    import src.utils.disk_cache as disk_cache
    from src.utils import cache as memory_cache

    memory_cache.clear_all()
    monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path / "cache"))

    history = make_historical_payload(TEAM_IDS, season=2025)
    monkeypatch.setattr(sp, "load_available_seasons", lambda *a, **k: [(2025, history)])

    # Zwei gespielte Spieltage, in denen Team 13 auffaellig stark ist.
    def goals(home, away, matchday):
        if home == 13:
            return 5, 0
        if away == 13:
            return 0, 5
        return 1, 1

    raw = make_round_robin_raw(TEAM_IDS, finished_matchdays=2, goals=goals)
    monkeypatch.setattr(fp, "_fetch_full_season", lambda *a, **k: raw)
    monkeypatch.setattr(fp, "resolve_season", lambda code, season=None: 2026)

    table = make_standings_table(TEAM_IDS, played=2)
    monkeypatch.setattr(lms, "resolve_season", lambda code, season=None: 2026)
    monkeypatch.setattr(lms, "get_standings", lambda *a, **k: {"tables": {"TOTAL": table}})

    return {"table": table, "raw": raw}


def _season_sim_profiles(table, finished):
    import src.features.strength_provider as sp

    return sp.get_league_strengths(
        league_key="bl1",
        standings_table=table,
        current_matches=finished,
        current_season=2026,
        use_squad_data=False,
    )["profiles"]


# ---------------------------------------------------------------------------
# Der eigentliche Punkt
# ---------------------------------------------------------------------------

def test_single_match_sim_now_sees_the_current_season(wired, monkeypatch):
    """
    Vorher: current_matches=None, die laufende Saison war unsichtbar.
    Jetzt: dieselbe Grundlage wie die Saisonsimulation.
    """
    import src.predict.league_match_sim as lms

    captured = {}
    real = lms.get_league_strengths

    def spy(**kwargs):
        captured.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(lms, "get_league_strengths", spy)

    lms.simulate_league_match(
        "bl1", "BL1", "Team 10", "Team 13",
        home_id=10, away_id=13, season=2026, simulations=100, use_seed=True,
    )

    assert captured["current_matches"], (
        "Einzelspielsimulation rechnet weiterhin ohne die laufende Saison"
    )
    assert all("home_id" in m and "home_goals" in m
               for m in captured["current_matches"])


def test_both_paths_use_identical_strengths_at_the_same_cutoff(wired, monkeypatch):
    """
    Kernzusicherung: Gleicher Kenntnisstand, gleiche Teamstaerke.
    """
    import src.predict.league_match_sim as lms
    import src.predict.fixture_plan as fp

    captured = {}
    real = lms.get_league_strengths

    def spy(**kwargs):
        captured.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(lms, "get_league_strengths", spy)

    lms.simulate_league_match(
        "bl1", "BL1", "Team 10", "Team 13",
        home_id=10, away_id=13, season=2026, simulations=100, use_seed=True,
    )

    match_profiles = _season_sim_profiles(
        wired["table"], captured["current_matches"])

    plan = fp.build_season_plan("BL1", 2026)
    season_profiles = _season_sim_profiles(
        wired["table"], plan["finished_matches"])

    assert match_profiles.keys() == season_profiles.keys()
    for team_id in match_profiles:
        for key in ("attack_home", "attack_away", "defence_home", "defence_away"):
            assert match_profiles[team_id][key] == pytest.approx(
                season_profiles[team_id][key]
            ), f"Team {team_id}, {key} weicht zwischen den Pfaden ab"


def test_current_form_actually_moves_the_expectation(wired, monkeypatch):
    """
    Belegt, dass die Aenderung wirkt: Team 13 hat in der laufenden Saison
    jedes Spiel 5:0 gewonnen. Das muss den Erwartungswert verschieben
    gegenueber einer Rechnung, die nur die Historie kennt.
    """
    import src.predict.league_match_sim as lms
    import src.features.strength_provider as sp

    with_form = lms.simulate_league_match(
        "bl1", "BL1", "Team 10", "Team 13",
        home_id=10, away_id=13, season=2026, simulations=100, use_seed=True,
    )

    history_only = sp.get_league_strengths(
        league_key="bl1", standings_table=wired["table"],
        current_matches=None, current_season=2026, use_squad_data=False,
    )
    from src.features.team_profile import expected_goals

    profiles = history_only["profiles"]
    _, xa_history = expected_goals(
        profiles[10], profiles[13], history_only["league_avg"])

    assert with_form["expected_away_goals"] != pytest.approx(xa_history, abs=1e-6), (
        "Die laufende Saison veraendert den Erwartungswert nicht - "
        "die Vereinheitlichung waere wirkungslos"
    )


# ---------------------------------------------------------------------------
# Kein Leak
# ---------------------------------------------------------------------------

def test_only_finished_matches_are_used(wired, monkeypatch):
    """
    Es duerfen ausschliesslich abgeschlossene Partien einfliessen -
    niemals angesetzte. Sonst wuesste die Simulation Ergebnisse, die es
    noch nicht gibt.
    """
    import src.predict.league_match_sim as lms

    captured = {}
    real = lms.get_league_strengths

    def spy(**kwargs):
        captured.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(lms, "get_league_strengths", spy)

    lms.simulate_league_match(
        "bl1", "BL1", "Team 10", "Team 13",
        home_id=10, away_id=13, season=2026, simulations=100, use_seed=True,
    )

    used = captured["current_matches"]
    finished_ids = {
        (m["homeTeam"]["id"], m["awayTeam"]["id"])
        for m in wired["raw"] if m["status"] == "FINISHED"
    }

    assert len(used) == len(finished_ids)
    for match in used:
        assert match["home_goals"] is not None
        assert match["away_goals"] is not None
        assert (match["home_id"], match["away_id"]) in finished_ids


# ---------------------------------------------------------------------------
# Robustheit
# ---------------------------------------------------------------------------

def test_broken_fixture_plan_does_not_break_a_single_match(wired, monkeypatch):
    """
    Wichtiger Unterschied zur Saisonsimulation: Die braucht jede einzelne
    Restpartie und muss bei Luecken abbrechen. Ein einzelnes Spiel
    braucht nur die bisherige Form - fehlt sie, traegt die Historie.
    """
    import src.predict.league_match_sim as lms
    import src.predict.fixture_plan as fp

    def boom(*args, **kwargs):
        raise RuntimeError("Spielplan nicht abrufbar")

    monkeypatch.setattr(fp, "_fetch_full_season", boom)
    monkeypatch.setattr(lms, "build_season_plan", boom)

    result = lms.simulate_league_match(
        "bl1", "BL1", "Team 10", "Team 13",
        home_id=10, away_id=13, season=2026, simulations=100, use_seed=True,
    )

    assert result["expected_home_goals"] > 0
    assert result["home_win_probability"] >= 0


def test_season_start_without_finished_matches_still_works(tmp_path, monkeypatch):
    """Zu Saisonbeginn gibt es nichts - die Historie muss reichen."""
    import src.features.strength_provider as sp
    import src.predict.league_match_sim as lms
    import src.predict.fixture_plan as fp
    import src.utils.disk_cache as disk_cache
    from src.utils import cache as memory_cache

    memory_cache.clear_all()
    monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path / "cache"))

    history = make_historical_payload(TEAM_IDS, season=2025)
    monkeypatch.setattr(sp, "load_available_seasons", lambda *a, **k: [(2025, history)])

    raw = make_round_robin_raw(TEAM_IDS, finished_matchdays=0)
    monkeypatch.setattr(fp, "_fetch_full_season", lambda *a, **k: raw)
    monkeypatch.setattr(fp, "resolve_season", lambda code, season=None: 2026)

    table = make_standings_table(TEAM_IDS, played=0)
    monkeypatch.setattr(lms, "resolve_season", lambda code, season=None: 2026)
    monkeypatch.setattr(lms, "get_standings", lambda *a, **k: {"tables": {"TOTAL": table}})

    result = lms.simulate_league_match(
        "bl1", "BL1", "Team 10", "Team 11",
        home_id=10, away_id=11, season=2026, simulations=100, use_seed=True,
    )

    assert result["expected_home_goals"] > 0


def test_no_extra_api_request(wired, monkeypatch):
    """
    Der Saisonplan liegt im Disk-Cache unter demselben Schluessel, den die
    Saisonsimulation ohnehin fuellt. Die Vereinheitlichung darf das
    Request-Budget nicht belasten.
    """
    import src.predict.league_match_sim as lms
    import src.predict.fixture_plan as fp

    calls = []
    original = fp._fetch_full_season

    def counting(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(fp, "_fetch_full_season", counting)

    for _ in range(3):
        lms.simulate_league_match(
            "bl1", "BL1", "Team 10", "Team 13",
            home_id=10, away_id=13, season=2026, simulations=50, use_seed=True,
        )

    assert len(calls) <= 1, f"{len(calls)} Saison-Requests fuer drei Simulationen"
