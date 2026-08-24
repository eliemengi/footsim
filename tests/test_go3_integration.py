"""
GO 3 im Produktivpfad: Modus, Reproduzierbarkeit, Diagnose.

Worum es geht
-------------
GO 3 laeuft in der Voreinstellung im Modus "shadow": es rechnet
vollstaendig, veraendert die Vorhersage aber nicht. Diese Tests halten
genau das fest - denn ein Schattenmodus, der doch etwas veraendert,
waere schlimmer als gar keiner: er wuerde eine unbelegte Korrektur
einschleusen, ohne dass jemand danach sucht.

Die Verdrahtung stammt aus tests/test_domestic_path_consistency.py:
synthetische Historie, synthetischer Saisonstand, kein Netzwerk.
"""

import os

import pytest

from tests.conftest import (
    make_historical_payload,
    make_round_robin_raw,
    make_standings_table,
)

TEAM_IDS = [10, 11, 12, 13]


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Beide Pfade gegen dieselben synthetischen Daten, ohne Netzwerk."""
    import src.features.strength_provider as sp
    import src.predict.league_match_sim as lms
    import src.predict.fixture_plan as fp
    import src.utils.disk_cache as disk_cache
    from src.features import go3, go3_provider
    from src.utils import cache as memory_cache

    memory_cache.clear_all()
    go3_provider.clear_cache()
    os.environ.pop(go3.MODE_ENV_VAR, None)
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

    go3_provider.clear_cache()
    os.environ.pop(go3.MODE_ENV_VAR, None)


def _simulate(**kwargs):
    import src.predict.league_match_sim as lms
    from datetime import datetime

    argumente = dict(
        competition_code="bl1", api_code="BL1",
        home_team="Team 10", away_team="Team 11",
        home_id=10, away_id=11, season=2026,
        simulations=400, use_seed=True,
        # Fester Stichtag: sonst haengt das Ergebnis am Kalendertag des
        # Testlaufs, und der Test waere morgen ein anderer.
        kickoff=datetime(2026, 3, 1, 15, 0),
    )
    argumente.update(kwargs)
    return lms.simulate_league_match(**argumente)


class TestModus:

    def test_shadow_ist_die_voreinstellung(self, wired):
        assert _simulate()["go3"]["mode"] == "shadow"

    def test_shadow_veraendert_die_vorhersage_nicht(self, wired):
        """
        Der Kern des Schattenmodus. Verglichen wird gegen "off", also
        gegen den Zustand, in dem GO 3 gar nicht erst rechnet.
        """
        from src.features import go3, go3_provider

        os.environ[go3.MODE_ENV_VAR] = "off"
        go3_provider.clear_cache()
        aus = _simulate()

        os.environ[go3.MODE_ENV_VAR] = "shadow"
        go3_provider.clear_cache()
        schatten = _simulate()

        for schluessel in ("expected_home_goals", "expected_away_goals",
                           "home_win_probability", "draw_probability",
                           "away_win_probability"):
            assert aus[schluessel] == schatten[schluessel], schluessel

    def test_shadow_meldet_applied_false(self, wired):
        assert _simulate()["go3"]["applied"] is False

    def test_shadow_rechnet_trotzdem(self, wired):
        """Sichtbar, aber wirkungslos - sonst waere er nutzlos."""
        block = _simulate()["go3"]
        assert block["available"] is True
        assert "modifier" in block["home"]
        assert block["home"]["number_of_usable_matches"] >= 0

    def test_off_liefert_trotzdem_einen_block(self, wired):
        """Auch abgeschaltet darf die Antwort kein Loch haben."""
        from src.features import go3, go3_provider

        os.environ[go3.MODE_ENV_VAR] = "off"
        go3_provider.clear_cache()
        block = _simulate()["go3"]
        assert block["mode"] == "off"
        assert block["applied"] is False


class TestReproduzierbarkeit:

    def test_gleicher_startwert_gleiches_ergebnis(self, wired):
        a = _simulate()
        b = _simulate()
        assert a["home_win_probability"] == b["home_win_probability"]
        assert a["expected_home_goals"] == b["expected_home_goals"]

    def test_stichtag_bestimmt_die_belastung(self, wired):
        """
        Zwei verschiedene Stichtage duerfen verschiedene Merkmale
        ergeben - sonst wuerde der Stichtag gar nicht ausgewertet.
        """
        from datetime import datetime

        frueh = _simulate(kickoff=datetime(2026, 1, 5, 15, 0))["go3"]
        spaet = _simulate(kickoff=datetime(2026, 5, 5, 15, 0))["go3"]
        assert (frueh["home"]["number_of_usable_matches"]
                <= spaet["home"]["number_of_usable_matches"])

    def test_ohne_stichtag_bleibt_es_innerhalb_eines_tages_stabil(self, wired):
        """
        Ohne Angabe wird der heutige Tag um 12 Uhr angesetzt - nicht die
        aktuelle Uhrzeit. Zwei Aufrufe kurz nacheinander muessen deshalb
        identisch sein.
        """
        a = _simulate(kickoff=None)
        b = _simulate(kickoff=None)
        assert a["go3"]["home"] == b["go3"]["home"]


class TestDiagnose:

    def test_block_enthaelt_die_geforderten_felder(self, wired):
        block = _simulate()["go3"]
        for seite in ("home", "away"):
            for feld in ("rest_hours", "rest_days", "matches_last_14_days",
                         "congestion_level", "recent_opponent_strength",
                         "modifier", "data_quality", "clamp_applied"):
                assert feld in block[seite], f"{seite}.{feld} fehlt"
        assert "mode" in block

    def test_block_nennt_die_wettbewerbsabdeckung(self, wired):
        abdeckung = _simulate()["go3"]["coverage"]
        assert "competitions" in abdeckung
        assert "known_gaps" in abdeckung

    def test_block_enthaelt_keine_pfade_oder_secrets(self, wired):
        import json

        text = json.dumps(_simulate()["go3"]).lower()
        for verboten in ("c:" + chr(92), "/root", "api_key", "secret",
                         "passwo", "traceback", ".env"):
            assert verboten not in text, verboten

    def test_normalzustand_erzeugt_keinen_fehler(self, wired):
        """
        Unbekannte Teams sind eine Datenlage, kein Ausfall. Die
        Simulation muss trotzdem ein vollstaendiges Ergebnis liefern.
        """
        ergebnis = _simulate(home_id=999999, away_id=999998)
        assert ergebnis["home_win_probability"] is not None
        assert ergebnis["go3"]["applied"] is False

    def test_ausfall_von_go3_bricht_die_simulation_nicht(self, wired, monkeypatch):
        """
        GO 3 ist eine Ergaenzung. Faellt sie aus, muss die Vorhersage
        trotzdem herauskommen - ohne Korrektur, aber vollstaendig.
        """
        import src.features.go3_provider as gp

        def kaputt(*args, **kwargs):
            raise RuntimeError("absichtlicher Ausfall")

        monkeypatch.setattr(gp, "fixture_snapshot", kaputt)
        ergebnis = _simulate()
        assert ergebnis["home_win_probability"] is not None
        assert ergebnis["go3"]["available"] is False
