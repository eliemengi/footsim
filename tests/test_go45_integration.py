"""
GO 4 und GO 5 im Produktivpfad: Modus, Reproduzierbarkeit, Diagnose.

Der Kern dieser Datei ist eine einzige Zusicherung: In der
Voreinstellung "shadow" rechnen beide Features vollstaendig und
erscheinen in der Diagnose, veraendern die Vorhersage aber um keine
Stelle. Ein Schattenmodus, der doch etwas veraendert, waere schlimmer
als gar keiner - er wuerde eine unbelegte Korrektur einschleusen, ohne
dass jemand danach sucht.

Verdrahtung wie in tests/test_domestic_path_consistency.py: synthetische
Historie, synthetischer Saisonstand, kein Netzwerk.
"""

import os
from datetime import datetime

import pytest

from tests.conftest import (
    make_historical_payload,
    make_round_robin_raw,
    make_standings_table,
)

TEAM_IDS = [10, 11, 12, 13]
KICKOFF = datetime(2026, 3, 1, 15, 0)


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Beide Pfade gegen dieselben synthetischen Daten, ohne Netzwerk."""
    import src.features.strength_provider as sp
    import src.predict.fixture_plan as fp
    import src.predict.league_match_sim as lms
    import src.utils.disk_cache as disk_cache
    from src.features import go3, go4, go45_provider, go5
    from src.utils import cache as memory_cache

    memory_cache.clear_all()
    go45_provider.clear_cache()
    for var in (go3.MODE_ENV_VAR, go4.MODE_ENV_VAR, go5.MODE_ENV_VAR):
        os.environ.pop(var, None)
    monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path / "cache"))

    history = make_historical_payload(TEAM_IDS, season=2025)
    monkeypatch.setattr(sp, "load_available_seasons", lambda *a, **k: [(2025, history)])

    raw = make_round_robin_raw(TEAM_IDS, finished_matchdays=2)
    monkeypatch.setattr(fp, "_fetch_full_season", lambda *a, **k: raw)
    monkeypatch.setattr(fp, "resolve_season", lambda code, season=None: 2026)

    table = make_standings_table(TEAM_IDS, played=2)
    monkeypatch.setattr(lms, "resolve_season", lambda code, season=None: 2026)
    monkeypatch.setattr(lms, "get_standings", lambda *a, **k: {"tables": {"TOTAL": table}})

    yield {"table": table}

    go45_provider.clear_cache()
    for var in (go3.MODE_ENV_VAR, go4.MODE_ENV_VAR, go5.MODE_ENV_VAR):
        os.environ.pop(var, None)


def _simulate(**kwargs):
    import src.predict.league_match_sim as lms

    argumente = dict(
        competition_code="bl1", api_code="BL1",
        home_team="Team 10", away_team="Team 11",
        home_id=10, away_id=11, season=2026,
        simulations=400, use_seed=True, kickoff=KICKOFF,
    )
    argumente.update(kwargs)
    return lms.simulate_league_match(**argumente)


ERGEBNISFELDER = ("expected_home_goals", "expected_away_goals",
                  "home_win_probability", "draw_probability",
                  "away_win_probability")


class TestModus:

    def test_shadow_ist_die_voreinstellung(self, wired):
        r = _simulate()
        assert r["go4"]["mode"] == "shadow"
        assert r["go5"]["mode"] == "shadow"

    def test_shadow_veraendert_die_vorhersage_nicht(self, wired):
        """Der Kern: verglichen gegen 'off', wo gar nicht gerechnet wird."""
        from src.features import go4, go45_provider, go5

        os.environ[go4.MODE_ENV_VAR] = "off"
        os.environ[go5.MODE_ENV_VAR] = "off"
        go45_provider.clear_cache()
        aus = _simulate()

        os.environ[go4.MODE_ENV_VAR] = "shadow"
        os.environ[go5.MODE_ENV_VAR] = "shadow"
        go45_provider.clear_cache()
        schatten = _simulate()

        for feld in ERGEBNISFELDER:
            assert aus[feld] == schatten[feld], feld

    def test_shadow_meldet_applied_false(self, wired):
        r = _simulate()
        assert r["go4"]["applied"] is False
        assert r["go5"]["applied"] is False

    def test_off_liefert_trotzdem_einen_block(self, wired):
        from src.features import go4, go45_provider, go5

        os.environ[go4.MODE_ENV_VAR] = "off"
        os.environ[go5.MODE_ENV_VAR] = "off"
        go45_provider.clear_cache()
        r = _simulate()
        assert r["go4"]["mode"] == "off"
        assert r["go5"]["mode"] == "off"
        assert r["go4"]["applied"] is False

    def test_go5_active_aktiviert_go4_nicht(self, wired):
        from src.features import go4, go45_provider, go5

        os.environ[go5.MODE_ENV_VAR] = "active"
        os.environ.pop(go4.MODE_ENV_VAR, None)
        go45_provider.clear_cache()
        r = _simulate()
        assert r["go5"]["mode"] == "active"
        assert r["go4"]["mode"] == "shadow"
        assert r["go4"]["applied"] is False

    def test_go3_bleibt_unabhaengig_shadow(self, wired):
        from src.features import go4, go45_provider, go5

        os.environ[go4.MODE_ENV_VAR] = "active"
        os.environ[go5.MODE_ENV_VAR] = "active"
        go45_provider.clear_cache()
        r = _simulate()
        assert r["go3"]["mode"] == "shadow"
        assert r["go3"]["applied"] is False


class TestReproduzierbarkeit:

    def test_gleicher_startwert_gleiches_ergebnis(self, wired):
        a = _simulate()
        b = _simulate()
        for feld in ERGEBNISFELDER:
            assert a[feld] == b[feld], feld

    def test_ohne_stichtag_bleibt_es_stabil(self, wired):
        a = _simulate(kickoff=None)
        b = _simulate(kickoff=None)
        assert a["go5"]["home"] == b["go5"]["home"]

    def test_saisonsimulation_bleibt_unberuehrt(self, wired):
        """
        GO 4 und GO 5 haengen am Einzelspielpfad. Die Saisonsimulation
        muss weiter funktionieren UND bei gleichem Startwert dasselbe
        liefern - unabhaengig davon, welcher Modus gesetzt ist.
        """
        from src.features import go4, go45_provider, go5
        from src.predict.season_sim import simulate_season

        tabelle = wired["table"]
        ausstehend = [{"home_id": 10, "away_id": 11, "matchday": 3},
                      {"home_id": 12, "away_id": 13, "matchday": 3}]

        def lauf():
            return simulate_season(
                competition_code="bl1", standings_table=tabelle,
                remaining_matches=ausstehend, simulations=50,
                seed=42, season=2026)

        os.environ[go4.MODE_ENV_VAR] = "off"
        os.environ[go5.MODE_ENV_VAR] = "off"
        go45_provider.clear_cache()
        aus = lauf()

        os.environ[go4.MODE_ENV_VAR] = "active"
        os.environ[go5.MODE_ENV_VAR] = "active"
        go45_provider.clear_cache()
        aktiv = lauf()

        assert aus is not None and aktiv is not None
        # Die Saisonsimulation bindet GO 4/GO 5 bewusst nicht ein - sie
        # muss deshalb bitgleich bleiben.
        gemeinsam = set(aus) & set(aktiv)
        assert gemeinsam
        for schluessel in gemeinsam:
            assert aus[schluessel] == aktiv[schluessel], schluessel


class TestDiagnose:

    def test_block_enthaelt_die_geforderten_go4_felder(self, wired):
        block = _simulate()["go4"]
        for seite in ("home", "away"):
            for feld in ("attack_modifier", "defence_modifier",
                         "goalkeeper_modifier", "data_quality",
                         "clamp_applied"):
                assert feld in block[seite], f"go4.{seite}.{feld}"

    def test_block_enthaelt_die_geforderten_go5_felder(self, wired):
        block = _simulate()["go5"]
        for seite in ("home", "away"):
            for feld in ("attack_modifier", "defence_modifier",
                         "lambda_transfer", "season_matches_played",
                         "relevant_transfers", "data_quality",
                         "clamp_applied"):
                assert feld in block[seite], f"go5.{seite}.{feld}"

    def test_kombinierte_grenze_wird_gemeldet(self, wired):
        r = _simulate()
        assert "combined" in r
        assert r["combined"]["max_combined_effect"] > 0

    def test_block_enthaelt_keine_pfade_oder_secrets(self, wired):
        import json

        r = _simulate()
        text = json.dumps({k: r[k] for k in ("go3", "go4", "go5", "combined")}).lower()
        for verboten in ("c:" + chr(92), "/root", "api_key", "secret",
                         "passwo", "traceback", ".env"):
            assert verboten not in text, verboten

    def test_unbekannte_teams_erzeugen_keinen_fehler(self, wired):
        """Eine fehlende Datenlage ist ein Zustand, kein HTTP 500."""
        r = _simulate(home_id=999999, away_id=999998)
        assert r["home_win_probability"] is not None
        assert r["go4"]["applied"] is False

    def test_ausfall_von_go45_bricht_die_simulation_nicht(self, wired, monkeypatch):
        import src.features.go45_provider as gp

        def kaputt(*args, **kwargs):
            raise RuntimeError("absichtlicher Ausfall")

        monkeypatch.setattr(gp, "fixture_snapshot", kaputt)
        r = _simulate()
        assert r["home_win_probability"] is not None
        assert r["go4"]["available"] is False


class TestPerformance:

    def test_keine_netzabfrage_in_der_simulation(self, wired):
        """
        Kernvorgabe: keine Anbieterabfrage je Monte-Carlo-Durchlauf. Der
        Test sperrt den Socketaufbau vollstaendig.
        """
        import socket

        original = socket.socket.connect

        def gesperrt(*args, **kwargs):
            raise AssertionError("GO 4/GO 5 hat eine Netzverbindung aufgebaut")

        socket.socket.connect = gesperrt
        try:
            _simulate(simulations=2000)
        finally:
            socket.socket.connect = original

    def test_mehr_durchlaeufe_kosten_kaum_mehr(self, wired):
        """
        Der Snapshot entsteht einmal vor der Schleife. Zehnmal so viele
        Wuerfe duerfen deshalb nicht zehnmal so lange dauern - sonst
        stuende die Merkmalsbeschaffung in der Schleife.
        """
        import time

        _simulate(simulations=100)          # Caches fuellen

        start = time.time()
        _simulate(simulations=200)
        klein = time.time() - start

        start = time.time()
        _simulate(simulations=2000)
        gross = time.time() - start

        # Grosszuegig gefasst: entscheidend ist, dass der feste Anteil
        # dominiert und nicht linear mitwaechst.
        assert gross < klein * 8 + 1.0
