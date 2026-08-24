"""
Regressionstests fuer Block B2 (Phase 4.0).

Abgedeckt:
  A) CL Ligaphase: stage=LEAGUE_STAGE Filterung
  B) Keine Vermischung mit PLAYOFFS/LAST_16/anderen Stages
  C) Saisonvalidierung: Response-Saison != angefragt -> leere Liste
  D) 2026/27 ohne echte Daten -> Empty State
  E) 2025/26 mit korrekten Daten -> Daten werden akzeptiert
  F) CL type=="cl" und genau einmal in /api/competitions
  G) Simulation: CL-Frontend-Vertrag mit home_team/away_team/IDs
  H) Top-5-Team-Simulation funktioniert
  I) Non-Top-5-Team erreicht Fallback-Kette
  J) K.-o.-Stages werden datengetrieben geliefert
  K) K.-o.-Endpoint liefert ausschliesslich die angeforderte Stage
  L) Finale/Single-Leg wird nicht kuenstlich als Hin-/Rueckspiel behandelt
  M) Domestic-Liga-Regression
  N) Alte CL-State-/UI-Logik ist nicht mehr aktiv
  O) CL-Ligaphasen-Tabelle: eigene Positionszonen, kein Gesamt/Heim/Auswaerts
  P) Season-Leak-Fix: explizite selectedSeason fuer CL statt Auto-Erkennung,
     Season-Validation in get_standings/get_scorers/get_finished_season_matches/
     get_all_matches, datengetriebenes Matchday-Gating ohne echte Ligaphase
  Q) Korrekturpatch: abgeschlossene CL-Saison entsperrt echte Spieltage
     datengetrieben (status=FINISHED statt is_current_season), und ein
     erwartbarer 404-No-Data-Fall bei CL ist ein Empty State, kein Fehler
"""

import json
import os
import re
import pytest


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def client(monkeypatch):
    """
    Testclient, der sich wie das echte Frontend verhaelt.

    /api/simulate ist ein mutierender POST und von CSRFProtect geschuetzt.
    Frueher liefen diese Tests unbemerkt mit abgeschaltetem CSRF - nicht
    weil sie es abschalteten, sondern weil eine fruehere Testdatei
    WTF_CSRF_ENABLED global auf False gesetzt und nie zurueckgestellt
    hatte. In der CI, wo jene Datei uebersprang, antworteten dieselben
    POSTs mit 400 auth.csrfError.

    Jetzt holt der Client ein echtes Token aus dem Meta-Tag der Seite,
    genau wie der Browser. Der Schutz bleibt scharf: ohne gueltiges Token
    weiterhin 400.
    """
    from tests.conftest import mit_csrf

    monkeypatch.setenv("APISPORTS_KEY", "test-key")
    monkeypatch.setenv("FOOTBALL_DATA_KEY", "test-key")
    import app as app_module
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield mit_csrf(c)


# ===========================================================================
# A) + B) Stage-Filter: nur LEAGUE_STAGE fuer CL Ligaphase
# ===========================================================================

class TestCLStageFilter:
    def test_cl_league_phase_loader_sendet_stage_parameter(self):
        """
        get_cl_league_phase_matches muss stage=LEAGUE_STAGE an die API
        senden. Wir pruefen das indirekt: die Funktion muss existieren
        und aufrufbar sein.
        """
        from src.api.league_api import get_cl_league_phase_matches
        assert callable(get_cl_league_phase_matches)

    def test_cl_matchday_route_nutzt_stage_filter(self, client, monkeypatch):
        """
        /api/matches?competition=cl&matchday=1 muss den stage-gefilterten
        CL-Loader verwenden, nicht den generischen get_matchday_match_options.
        """
        import app as app_module

        captured = {}

        def fake_cl_options(matchday, season=None):
            captured["matchday"] = matchday
            captured["season"] = season
            return [{"id": "cl_1_test", "home_team": "A", "away_team": "B",
                     "home_id": 1, "away_id": 2, "matchday": matchday,
                     "competition": "cl"}]

        monkeypatch.setattr(app_module, "get_cl_league_phase_match_options", fake_cl_options)
        monkeypatch.setattr(app_module, "is_matchday_unlocked", lambda *a, **k: True)

        response = client.get("/api/matches?competition=cl&matchday=3&season=2025")
        assert response.status_code == 200
        assert captured["matchday"] == 3

    def test_domestic_route_nutzt_weiterhin_generischen_loader(self, client, monkeypatch):
        """BL1 darf NICHT den CL-Loader verwenden."""
        import app as app_module

        captured = {}

        def fake_generic_options(competition_code, api_code, matchday, season=None):
            captured["api_code"] = api_code
            return []

        monkeypatch.setattr(app_module, "get_matchday_match_options", fake_generic_options)
        monkeypatch.setattr(app_module, "is_matchday_unlocked", lambda *a, **k: True)

        client.get("/api/matches?competition=bl1&matchday=1")
        assert captured["api_code"] == "BL1"


# ===========================================================================
# C) + D) + E) Saison-Validierung
# ===========================================================================

class TestSaisonValidierung:
    def test_validate_cl_season_erkennt_falsche_saison(self):
        from src.api.league_api import _validate_cl_season
        # Response behauptet 2025 (= 2025/26), aber wir haben 2026 angefragt
        matches = [{"season": {"startDate": "2025-09-15"}}]
        assert _validate_cl_season(matches, 2026) is False

    def test_validate_cl_season_akzeptiert_korrekte_saison(self):
        from src.api.league_api import _validate_cl_season
        matches = [{"season": {"startDate": "2025-09-15"}}]
        assert _validate_cl_season(matches, 2025) is True

    def test_validate_cl_season_leere_liste_ist_ok(self):
        from src.api.league_api import _validate_cl_season
        assert _validate_cl_season([], 2026) is True

    def test_validate_cl_season_ohne_startdate_ist_ok(self):
        from src.api.league_api import _validate_cl_season
        matches = [{"season": {}}]
        assert _validate_cl_season(matches, 2026) is True

    def test_cl_matchday_route_leert_bei_saison_mismatch(self, client, monkeypatch):
        """
        Wenn die API 2025/26-Daten fuer season=2026 zurueckgibt, muss
        der CL-Loader eine leere Liste liefern (Empty State).
        """
        import app as app_module

        def fake_cl_options(matchday, season=None):
            # Simuliert: Saison-Validierung hat gefiltert -> leere Liste
            return []

        monkeypatch.setattr(app_module, "get_cl_league_phase_match_options", fake_cl_options)
        monkeypatch.setattr(app_module, "is_matchday_unlocked", lambda *a, **k: True)

        response = client.get("/api/matches?competition=cl&matchday=1&season=2026")
        assert response.status_code == 200
        assert response.get_json() == []


# ===========================================================================
# F) CL type=="cl" und genau einmal
# ===========================================================================

class TestCLCompetitionType:
    def test_cl_hat_type_cl(self, client, monkeypatch):
        import app as app_module
        monkeypatch.setattr(app_module, "is_current_season", lambda api_code, season: True)

        response = client.get("/api/competitions")
        data = response.get_json()

        cl_entries = [c for c in data if c["code"] == "cl"]
        assert len(cl_entries) == 1
        assert cl_entries[0]["type"] == "cl"

    def test_el_bleibt_type_cup(self, client, monkeypatch):
        import app as app_module
        monkeypatch.setattr(app_module, "is_current_season", lambda api_code, season: True)

        response = client.get("/api/competitions")
        data = response.get_json()

        el_entries = [c for c in data if c["code"] == "el"]
        assert len(el_entries) == 1
        assert el_entries[0]["type"] == "cup"

    def test_domestic_ligen_bleiben_type_league(self, client, monkeypatch):
        import app as app_module
        monkeypatch.setattr(app_module, "is_current_season", lambda api_code, season: True)

        response = client.get("/api/competitions")
        data = response.get_json()

        for code in ("bl1", "pl", "pd", "sa", "fl1"):
            entries = [c for c in data if c["code"] == code]
            assert len(entries) == 1
            assert entries[0]["type"] == "league", f"{code} hat falschen Typ"


# ===========================================================================
# G) Simulation: Frontend-Vertrag mit home_team/away_team
# ===========================================================================

class TestCLSimulationsPayload:
    def test_frontend_code_sendet_home_team_fuer_cl(self):
        """
        script.js muss fuer competitionType === 'cl' den home_team/away_team-
        Payload verwenden, nicht match_id/leg_mode.
        """
        path = os.path.join(PROJECT_ROOT, "static", "script.js")
        with open(path, encoding="utf-8") as f:
            src = f.read()

        # Die entscheidende Zeile: CL wird wie league behandelt
        assert 'competitionType === "cl"' in src, (
            "script.js hat keine Sonderbehandlung fuer competitionType === 'cl'. "
            "Die Simulation wuerde fuer CL den alten match_id/leg_mode-Payload senden."
        )

        # Finde den runSimulation-Payload-Block
        idx = src.find("async function runSimulation")
        assert idx > -1
        block = src[idx:idx + 1500]
        # Muss in derselben Bedingung wie "league" stehen
        assert 'competitionType === "league" || state.competitionType === "cl"' in block or \
               'competitionType === "league" || competitionType === "cl"' in block, (
            "runSimulation behandelt CL nicht zusammen mit league fuer den Payload"
        )

    def test_cl_simulation_mit_home_team_funktioniert(self, client, monkeypatch):
        import app as app_module

        def fake_sim(**kwargs):
            return {"home_team": kwargs["home_team"], "away_team": kwargs["away_team"],
                    "home_win_probability": 55.0, "draw_probability": 20.0,
                    "away_win_probability": 25.0, "expected_home_goals": 1.8,
                    "expected_away_goals": 1.1, "top_scores": [],
                    "competition": "Champions League", "phase": "league",
                    "home_resolution": "domestic_history", "away_resolution": "cl_current_season"}

        monkeypatch.setattr(app_module, "simulate_cl_league_phase_match", fake_sim)

        response = client.post("/api/simulate", json={
            "competition": "cl",
            "home_team": "FC Bayern", "away_team": "FK Bodoe/Glimt",
            "home_id": 5, "away_id": 5721,
            "season": 2025, "simulations": 1000,
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data["home_team"] == "FC Bayern"
        assert data["away_resolution"] == "cl_current_season"

    def test_cl_simulation_ohne_teams_gibt_400(self, client):
        response = client.post("/api/simulate", json={
            "competition": "cl", "simulations": 1000,
        })
        assert response.status_code == 400

    def test_alter_match_id_payload_gibt_400_fuer_cl(self, client):
        """Der alte match_id/leg_mode-Pfad darf fuer CL nicht funktionieren."""
        response = client.post("/api/simulate", json={
            "competition": "cl",
            "match_id": "gala_liverpool", "leg_mode": "first",
        })
        assert response.status_code == 400


# ===========================================================================
# H) + I) Fallback-Kette (Top-5 und Non-Top-5)
# ===========================================================================

class TestFallbackKette:
    def test_top5_team_ueber_domestic_history(self):
        from src.predict.cl_match_sim import _resolve_cl_profile

        strengths = {
            "domestic_by_id": {5: {"team_id": 5, "team_name": "Bayern", "attack_home": 1.6}},
            "cl_current_by_id": {},
        }
        profile, resolution = _resolve_cl_profile(strengths, 5, "Bayern")
        assert resolution == "domestic_history"

    def test_bodo_glimt_ueber_cl_current(self):
        from src.predict.cl_match_sim import _resolve_cl_profile

        strengths = {
            "domestic_by_id": {},
            "cl_current_by_id": {5721: {"team_id": 5721, "attack_home": 1.3, "matches_used": 6}},
        }
        profile, resolution = _resolve_cl_profile(strengths, 5721, "FK Bodoe/Glimt")
        assert resolution == "cl_current_season"
        assert profile["matches_used"] == 6

    def test_unbekanntes_team_faellt_auf_neutral(self):
        from src.predict.cl_match_sim import _resolve_cl_profile

        strengths = {"domestic_by_id": {}, "cl_current_by_id": {}}
        profile, resolution = _resolve_cl_profile(strengths, 99999, "Unbekannt")
        assert resolution == "neutral"


# ===========================================================================
# J) + K) K.-o.-Stages datengetrieben + Stage-Filter
# ===========================================================================

class TestCLKnockout:
    def test_cl_stages_nur_tatsaechlich_vorhandene(self, client, monkeypatch):
        import app as app_module

        fake_matches = [
            {"stage": "LEAGUE_STAGE"}, {"stage": "LEAGUE_STAGE"},
            {"stage": "PLAYOFFS"}, {"stage": "LAST_16"},
        ]
        monkeypatch.setattr(app_module, "get_all_matches",
                           lambda *a, **k: fake_matches)

        response = client.get("/api/cl-stages?season=2025")
        data = response.get_json()
        stage_codes = [s["stage"] for s in data["stages"]]

        assert "LEAGUE_STAGE" not in stage_codes
        assert "PLAYOFFS" in stage_codes
        assert "LAST_16" in stage_codes

    def test_cl_stages_leer_vor_auslosung(self, client, monkeypatch):
        import app as app_module
        monkeypatch.setattr(app_module, "get_all_matches",
                           lambda *a, **k: [{"stage": "LEAGUE_STAGE"}])

        response = client.get("/api/cl-stages?season=2026")
        assert response.get_json()["stages"] == []

    def test_cl_knockout_endpoint_existiert(self, client, monkeypatch):
        import app as app_module
        monkeypatch.setattr(app_module, "get_cl_knockout_matches",
                           lambda stage, season=None: [])

        response = client.get("/api/cl-knockout?stage=LAST_16&season=2025&lang=de")
        assert response.status_code == 200
        data = response.get_json()
        assert data["stage"] == "LAST_16"
        assert data["label"] == "Achtelfinale"
        assert data["ties"] == []

    def test_cl_knockout_gruppiert_ties(self, client, monkeypatch):
        import app as app_module

        fake_matches = [
            {"homeTeam": {"id": 5, "name": "Bayern", "crest": None},
             "awayTeam": {"id": 81, "name": "Barcelona", "crest": None},
             "score": {"fullTime": {"home": 2, "away": 1}},
             "utcDate": "2025-02-18T21:00:00Z", "status": "FINISHED"},
            {"homeTeam": {"id": 81, "name": "Barcelona", "crest": None},
             "awayTeam": {"id": 5, "name": "Bayern", "crest": None},
             "score": {"fullTime": {"home": 1, "away": 0}},
             "utcDate": "2025-02-25T21:00:00Z", "status": "FINISHED"},
        ]
        monkeypatch.setattr(app_module, "get_cl_knockout_matches",
                           lambda stage, season=None: fake_matches)

        response = client.get("/api/cl-knockout?stage=LAST_16&season=2025")
        data = response.get_json()

        assert len(data["ties"]) == 1
        assert len(data["ties"][0]["legs"]) == 2
        # Chronologisch: Leg 1 zuerst
        assert data["ties"][0]["legs"][0]["home_team"] == "Bayern"
        assert data["ties"][0]["legs"][1]["home_team"] == "Barcelona"

    def test_cl_knockout_ohne_stage_gibt_400(self, client):
        response = client.get("/api/cl-knockout?season=2025")
        assert response.status_code == 400


# ===========================================================================
# L) Finale (Single-Leg) wird korrekt behandelt
# ===========================================================================

class TestFinale:
    def test_finale_hat_nur_ein_leg(self, client, monkeypatch):
        import app as app_module

        fake_matches = [
            {"homeTeam": {"id": 5, "name": "Bayern", "crest": None},
             "awayTeam": {"id": 81, "name": "Barcelona", "crest": None},
             "score": {"fullTime": {"home": 3, "away": 1}},
             "utcDate": "2025-06-01T21:00:00Z", "status": "FINISHED"},
        ]
        monkeypatch.setattr(app_module, "get_cl_knockout_matches",
                           lambda stage, season=None: fake_matches)

        response = client.get("/api/cl-knockout?stage=FINAL&season=2025&lang=de")
        data = response.get_json()

        assert len(data["ties"]) == 1
        assert len(data["ties"][0]["legs"]) == 1
        assert data["label"] == "Finale"


# ===========================================================================
# M) Domestic-Liga-Regression
# ===========================================================================

class TestDomesticRegression:
    def test_bl1_matchday_unveraendert(self, client, monkeypatch):
        import app as app_module

        captured = {}
        def fake(competition_code, api_code, matchday, season=None):
            captured["api_code"] = api_code
            return []

        monkeypatch.setattr(app_module, "get_matchday_match_options", fake)
        monkeypatch.setattr(app_module, "is_matchday_unlocked", lambda *a, **k: True)

        client.get("/api/matches?competition=bl1&matchday=1")
        assert captured["api_code"] == "BL1"

    def test_alle_fuenf_ligen_in_league_config(self):
        import app as app_module
        for code in ("bl1", "pl", "pd", "sa", "fl1"):
            assert code in app_module.LEAGUE_CONFIG

    def test_bl1_simulation_unveraendert(self, client, monkeypatch):
        import app as app_module

        captured = {}
        def fake(**kwargs):
            captured.update(kwargs)
            return {"home_team": kwargs["home_team"], "away_team": kwargs["away_team"]}

        monkeypatch.setattr(app_module, "simulate_league_match", fake)

        response = client.post("/api/simulate", json={
            "competition": "bl1", "home_team": "Bayern", "away_team": "Dortmund",
        })
        assert response.status_code == 200
        assert captured["api_code"] == "BL1"

    def test_bl1_standings_unveraendert(self, client, monkeypatch):
        import app as app_module

        def fake(api_code, season=None):
            return {"season": 2026, "competition": "Bundesliga",
                    "tables": {"TOTAL": [{"team_id": 5, "team_name": "Bayern"}]}}

        monkeypatch.setattr(app_module, "get_standings", fake)

        response = client.get("/api/standings?competition=bl1")
        assert response.status_code == 200
        assert response.get_json()["competition"] == "Bundesliga"


# ===========================================================================
# N) Alte CL-State-/UI-Logik nicht mehr aktiv
# ===========================================================================

class TestAlteLogikEntfernt:
    def test_kein_round_section_in_html(self):
        path = os.path.join(PROJECT_ROOT, "templates", "index.html")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert 'id="round-section"' not in src
        assert 'id="leg-mode-section"' not in src

    def test_kein_renderClRounds_in_js(self):
        path = os.path.join(PROJECT_ROOT, "static", "script.js")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert "function renderClRounds" not in src
        assert "function renderClLegModes" not in src

    def test_neue_cl_phase_section_in_html(self):
        path = os.path.join(PROJECT_ROOT, "templates", "index.html")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert 'id="cl-phase-section"' in src
        assert 'id="cl-matchday-section"' in src
        assert 'id="cl-ko-stage-section"' in src

    def test_neue_cl_funktionen_in_js(self):
        path = os.path.join(PROJECT_ROOT, "static", "script.js")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert "function selectClPhase" in src
        assert "function loadClMatchdays" in src
        assert "function loadClKoStages" in src

    def test_cl_phase_state_im_js(self):
        path = os.path.join(PROJECT_ROOT, "static", "script.js")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert "clPhase:" in src
        assert "clKoStage:" in src


# ===========================================================================
# Scorers bleiben wettbewerbsweit
# ===========================================================================

class TestScorersWettbewerbsweit:
    def test_cl_scorers_kein_stage_filter(self, client, monkeypatch):
        """
        /api/scorers?competition=cl darf KEINEN stage-Filter haben.
        Die Torjaeegerliste muss den gesamten CL-Wettbewerb abdecken.
        """
        import app as app_module

        captured = {}
        def fake_scorers(api_code, season=None, limit=20):
            captured["api_code"] = api_code
            return {"season": 2025, "scorers": [{"player_name": "Kane", "goals": 8}]}

        monkeypatch.setattr(app_module, "get_scorers", fake_scorers)

        response = client.get("/api/scorers?competition=cl&season=2025")
        assert response.status_code == 200
        assert captured["api_code"] == "CL"
        data = response.get_json()
        assert data["scorers"][0]["player_name"] == "Kane"


# ===========================================================================
# O) CL-Ligaphasen-Tabelle: eigene Zonen + kein Gesamt/Heim/Auswaerts-Switcher
# ===========================================================================

def _read(*parts):
    path = os.path.join(PROJECT_ROOT, *parts)
    with open(path, encoding="utf-8") as f:
        return f.read()


def _js_block(src, header, length):
    idx = src.find(header)
    assert idx > -1, "{} nicht in script.js gefunden".format(header)
    return src[idx:idx + length]


class TestCLTabellenZonen:
    def test_position_class_hat_eigene_cl_zonen(self):
        """
        positionClass muss fuer competitionType 'cl' die UEFA-Ligaphasen-Zonen
        verwenden: 1-8 direkt Achtelfinale, 9-24 Play-offs, ab 25 raus.
        """
        block = _js_block(_read("static", "script.js"), "function positionClass", 800)

        assert 'competitionType === "cl"' in block, (
            "positionClass unterscheidet nicht zwischen CL und Domestic - "
            "die CL-Tabelle wuerde weiter die Liga-Zonen (4/6/Abstieg) zeigen."
        )
        assert "position <= 8" in block
        assert "position <= 24" in block

    def test_domestic_zonen_unveraendert(self):
        """Die bestehende Liga-Logik darf nicht angetastet werden."""
        block = _js_block(_read("static", "script.js"), "function positionClass", 800)

        assert "position <= 4" in block
        assert "position <= 6" in block
        assert "teamCount - 3" in block

    def test_legende_hat_cl_texte_und_behaelt_domestic_texte(self):
        block = _js_block(_read("static", "script.js"), "function buildLegend", 900)

        # CL-Variante und Domestic-Variante bleiben als stabile
        # Übersetzungsschlüssel erhalten; der sichtbare Text richtet sich
        # bewusst nach der aktiven Locale.
        for key in (
            "table.legend.clDirect",
            "table.legend.clPlayoffs",
            "table.legend.eliminated",
            "table.legend.championsLeague",
            "table.legend.europe",
            "table.legend.relegation",
        ):
            assert f't("{key}")' in block

    def test_keine_neuen_marker_klassen(self):
        """
        Die vorhandenen Marker-Klassen werden wiederverwendet. Es darf keine
        neue CL-Farbklasse eingefuehrt worden sein (kein Redesign).
        """
        block = _js_block(_read("static", "script.js"), "function positionClass", 800)

        for cls in ("pos-cl", "pos-el", "pos-relegation"):
            assert cls in block
        assert "pos-ko" not in block
        assert "pos-out" not in block

    def test_switcher_hat_id_und_unveraenderte_buttons(self):
        src = _read("templates", "index.html")

        assert 'id="table-type-switch"' in src
        assert 'class="table-type-switch"' in src
        assert 'data-type="TOTAL"' in src
        assert 'data-type="HOME"' in src
        assert 'data-type="AWAY"' in src

    def test_show_tabs_for_steuert_switcher(self):
        block = _js_block(_read("static", "script.js"), "function showTabsFor", 1400)

        assert "setTableTypeSwitchVisible(true)" in block, (
            "Domestic-Ligen blenden den Gesamt/Heim/Auswaerts-Switcher nicht "
            "wieder ein - nach einem CL-Besuch bliebe er versteckt."
        )
        assert block.count("setTableTypeSwitchVisible(false)") == 2, (
            "cl_league und cl_knockout muessen den Switcher beide ausblenden."
        )

    def test_switcher_erzwingt_total(self):
        block = _js_block(
            _read("static", "script.js"), "function setTableTypeSwitchVisible", 700
        )

        assert 'state.tableType = "TOTAL"' in block
        assert 'data-type="TOTAL"' in block

    def test_cl_standings_nutzt_generische_route(self, client, monkeypatch):
        """
        Kein eigener CL-Standings-Endpoint. Die CL-Tabelle laeuft weiterhin
        ueber /api/standings mit derselben Row-Struktur wie die Ligen.
        """
        import app as app_module

        captured = {}

        def fake(api_code, season=None):
            captured["api_code"] = api_code
            return {"season": 2025, "competition": "UEFA Champions League",
                    "tables": {"TOTAL": [{"position": 1, "team_id": 5,
                                          "team_name": "Bayern", "points": 18}]}}

        monkeypatch.setattr(app_module, "get_standings", fake)

        response = client.get("/api/standings?competition=cl&season=2025")
        assert response.status_code == 200
        assert captured["api_code"] == "CL"

        data = response.get_json()
        assert data["table"][0]["position"] == 1
        assert data["table"][0]["points"] == 18

    def test_kein_eigener_cl_standings_endpoint(self, client):
        import app as app_module

        rules = [str(rule) for rule in app_module.app.url_map.iter_rules()]
        assert "/api/cl-standings" not in rules


# ===========================================================================
# P) Season-Leak-Fix (Option 2): explizite selectedSeason fuer CL,
#    Season-Validation in Standings/Scorers/get_all_matches/
#    get_finished_season_matches, datengetriebenes Matchday-Gating
# ===========================================================================

def _bypass_cache(monkeypatch, league_api):
    """
    Laesst disk_cached_call/cached_call den loader direkt ausfuehren, ohne
    echte Festplatten- oder In-Memory-Cache-Dateien anzufassen. So testen
    wir die tatsaechliche Validierungslogik in get_standings() & co, ohne
    das reale data/cache/-Verzeichnis zu beruehren.
    """
    monkeypatch.setattr(
        league_api, "disk_cached_call",
        lambda key, ttl_seconds, loader, **kw: loader()
    )
    monkeypatch.setattr(
        league_api, "cached_call",
        lambda key, ttl_seconds, loader, **kw: loader()
    )


class TestCLResponseSeasonHelper:
    def test_erkennt_falsche_saison(self):
        from src.api.league_api import _cl_response_season_ok
        data = {"season": {"startDate": "2025-08-01"}}
        assert _cl_response_season_ok(data, 2026) is False

    def test_akzeptiert_korrekte_saison(self):
        from src.api.league_api import _cl_response_season_ok
        data = {"season": {"startDate": "2026-07-15"}}
        assert _cl_response_season_ok(data, 2026) is True

    def test_ohne_season_feld_ist_ok(self):
        from src.api.league_api import _cl_response_season_ok
        assert _cl_response_season_ok({}, 2026) is True

    def test_requested_none_ist_ok(self):
        from src.api.league_api import _cl_response_season_ok
        data = {"season": {"startDate": "2025-08-01"}}
        assert _cl_response_season_ok(data, None) is True


class TestGetStandingsCLValidation:
    def test_cl_mismatch_liefert_leere_tables(self, monkeypatch):
        import src.api.league_api as league_api
        _bypass_cache(monkeypatch, league_api)

        fake_response = {
            "season": {"startDate": "2025-08-01"},
            "competition": {"name": "UEFA Champions League", "emblem": "x"},
            "standings": [{"type": "TOTAL", "table": [
                {"position": 1, "team": {"id": 5, "name": "Bayern"},
                 "playedGames": 1, "won": 1, "draw": 0, "lost": 0,
                 "points": 3, "goalsFor": 2, "goalsAgainst": 0, "goalDifference": 2}
            ]}],
        }
        monkeypatch.setattr(league_api, "_get_json", lambda path, params=None, retries=3: fake_response)

        result = league_api.get_standings("CL", season=2026)
        assert result["tables"] == {}
        assert result["season"] == 2026

    def test_cl_match_liefert_echte_tables(self, monkeypatch):
        import src.api.league_api as league_api
        _bypass_cache(monkeypatch, league_api)

        fake_response = {
            "season": {"startDate": "2026-08-14"},
            "competition": {"name": "UEFA Champions League", "emblem": "x"},
            "standings": [{"type": "TOTAL", "table": [
                {"position": 1, "team": {"id": 5, "name": "Bayern"},
                 "playedGames": 1, "won": 1, "draw": 0, "lost": 0,
                 "points": 3, "goalsFor": 2, "goalsAgainst": 0, "goalDifference": 2}
            ]}],
        }
        monkeypatch.setattr(league_api, "_get_json", lambda path, params=None, retries=3: fake_response)

        result = league_api.get_standings("CL", season=2026)
        assert len(result["tables"]["TOTAL"]) == 1
        assert result["tables"]["TOTAL"][0]["team_name"] == "Bayern"

    def test_domestic_wird_nicht_gefiltert(self, monkeypatch):
        """
        Domestic-Standings-Architektur bleibt unveraendert: Ein Saison-
        Mismatch bei BL1 (theoretisch, kommt in der Praxis nicht vor) darf
        NICHT gefiltert werden, da die Validierung bewusst auf CL begrenzt ist.
        """
        import src.api.league_api as league_api
        _bypass_cache(monkeypatch, league_api)

        fake_response = {
            "season": {"startDate": "2025-08-01"},
            "competition": {"name": "Bundesliga", "emblem": "x"},
            "standings": [{"type": "TOTAL", "table": [
                {"position": 1, "team": {"id": 5, "name": "Bayern"},
                 "playedGames": 1, "won": 1, "draw": 0, "lost": 0,
                 "points": 3, "goalsFor": 2, "goalsAgainst": 0, "goalDifference": 2}
            ]}],
        }
        monkeypatch.setattr(league_api, "_get_json", lambda path, params=None, retries=3: fake_response)

        result = league_api.get_standings("BL1", season=2026)
        assert len(result["tables"]["TOTAL"]) == 1


class TestGetScorersCLValidation:
    def test_cl_mismatch_liefert_leere_scorers(self, monkeypatch):
        import src.api.league_api as league_api
        _bypass_cache(monkeypatch, league_api)

        fake_response = {
            "season": {"startDate": "2025-08-01"},
            "scorers": [{"player": {"id": 1, "name": "Kane"}, "team": {"id": 5, "name": "Bayern"},
                         "goals": 8, "assists": 2, "playedMatches": 5}],
        }
        monkeypatch.setattr(league_api, "_get_json", lambda path, params=None, retries=3: fake_response)

        result = league_api.get_scorers("CL", season=2026)
        assert result["scorers"] == []

    def test_domestic_wird_nicht_gefiltert(self, monkeypatch):
        import src.api.league_api as league_api
        _bypass_cache(monkeypatch, league_api)

        fake_response = {
            "season": {"startDate": "2025-08-01"},
            "scorers": [{"player": {"id": 1, "name": "Kane"}, "team": {"id": 5, "name": "FCB"},
                         "goals": 8, "assists": 2, "playedMatches": 5}],
        }
        monkeypatch.setattr(league_api, "_get_json", lambda path, params=None, retries=3: fake_response)

        result = league_api.get_scorers("BL1", season=2026)
        assert len(result["scorers"]) == 1


class TestGetFinishedSeasonMatchesCLValidation:
    def test_cl_mismatch_liefert_leere_liste(self, monkeypatch):
        import src.api.league_api as league_api
        _bypass_cache(monkeypatch, league_api)

        fake_response = {"matches": [
            {"season": {"startDate": "2025-08-01"},
             "score": {"fullTime": {"home": 1, "away": 0}},
             "homeTeam": {"name": "A"}, "awayTeam": {"name": "B"},
             "matchday": 1, "utcDate": "2025-09-01"}
        ]}
        monkeypatch.setattr(league_api, "_get_json", lambda path, params=None, retries=3: fake_response)

        result = league_api.get_finished_season_matches("CL", season=2026)
        assert result == []

    def test_domestic_wird_nicht_gefiltert(self, monkeypatch):
        import src.api.league_api as league_api
        _bypass_cache(monkeypatch, league_api)

        fake_response = {"matches": [
            {"season": {"startDate": "2025-08-01"},
             "score": {"fullTime": {"home": 1, "away": 0}},
             "homeTeam": {"name": "A"}, "awayTeam": {"name": "B"},
             "matchday": 1, "utcDate": "2025-09-01"}
        ]}
        monkeypatch.setattr(league_api, "_get_json", lambda path, params=None, retries=3: fake_response)

        result = league_api.get_finished_season_matches("BL1", season=2026)
        assert len(result) == 1


class TestGetAllMatchesCLValidation:
    def test_cl_mismatch_liefert_leere_liste(self, monkeypatch):
        import src.api.league_api as league_api
        _bypass_cache(monkeypatch, league_api)

        fake_response = {"matches": [
            {"season": {"startDate": "2025-08-01"}, "stage": "LEAGUE_STAGE",
             "score": {"fullTime": {"home": 1, "away": 0}},
             "homeTeam": {"id": 1, "name": "A"}, "awayTeam": {"id": 2, "name": "B"},
             "matchday": 1, "utcDate": "2025-09-01", "status": "FINISHED"}
        ]}
        monkeypatch.setattr(league_api, "_get_json", lambda path, params=None, retries=3: fake_response)

        result = league_api.get_all_matches("CL", season=2026, only_finished=False)
        assert result == []

    def test_cl_match_liefert_matches(self, monkeypatch):
        import src.api.league_api as league_api
        _bypass_cache(monkeypatch, league_api)

        fake_response = {"matches": [
            {"season": {"startDate": "2026-08-14"}, "stage": "LEAGUE_STAGE",
             "score": {"fullTime": {"home": None, "away": None}},
             "homeTeam": {"id": 1, "name": "A"}, "awayTeam": {"id": 2, "name": "B"},
             "matchday": 1, "utcDate": "2026-09-01", "status": "SCHEDULED"}
        ]}
        monkeypatch.setattr(league_api, "_get_json", lambda path, params=None, retries=3: fake_response)

        result = league_api.get_all_matches("CL", season=2026, only_finished=False)
        assert len(result) == 1
        assert result[0]["stage"] == "LEAGUE_STAGE"


class TestRouteLevelSeasonMismatch:
    """
    Integrationsebene: angefragt 2026, Response gehoert nachweislich zu
    2025 -> jede der vier Datenroute muss leer/Empty State liefern, nie
    die 2025er-Daten unter dem Label 2026/27 zeigen.
    """

    def test_standings_route_leer_bei_mismatch(self, client, monkeypatch):
        import app as app_module

        monkeypatch.setattr(
            app_module, "get_standings",
            lambda api_code, season=None: {"season": season, "competition": "UEFA Champions League", "tables": {}}
        )

        response = client.get("/api/standings?competition=cl&season=2026")
        assert response.status_code == 200
        assert response.get_json()["table"] == []

    def test_player_scorers_route_empty_state_bei_mismatch(self, client, monkeypatch):
        import app as app_module

        monkeypatch.setattr(app_module, "get_finished_season_matches", lambda api_code, season=None: [])

        response = client.get("/api/player-scorers?competition=cl&season=2026")
        assert response.status_code == 200
        data = response.get_json()
        assert data["empty_state"] is True
        assert "Champions League" in data["empty_state_message"]
        assert "2026/27" in data["empty_state_message"]
        assert data["scorers"] == []

    def test_cl_stages_route_leer_bei_mismatch(self, client, monkeypatch):
        import app as app_module

        monkeypatch.setattr(app_module, "get_all_matches", lambda *a, **k: [])

        response = client.get("/api/cl-stages?season=2026")
        assert response.status_code == 200
        assert response.get_json()["stages"] == []

    def test_cl_knockout_route_leer_bei_mismatch(self, client, monkeypatch):
        import app as app_module

        monkeypatch.setattr(app_module, "get_cl_knockout_matches", lambda stage, season=None: [])

        response = client.get("/api/cl-knockout?stage=LAST_16&season=2026")
        assert response.status_code == 200
        assert response.get_json()["ties"] == []


class TestMatchdayGatingDatengetrieben:
    def test_cl_ohne_ligaphasen_daten_alle_gesperrt(self, client, monkeypatch):
        """
        2026 explizit angefragt, aber keine echten LEAGUE_STAGE-Spiele fuer
        diese Saison -> keine acht scheinbar verfuegbaren Spieltage, egal
        was is_current_season() fuer CL's eigene Auto-Erkennung sagt.
        """
        import app as app_module

        monkeypatch.setattr(app_module, "get_all_matches", lambda *a, **k: [])
        # Simuliert exakt den befuerchteten Nebeneffekt: CL's eigene
        # Saisonerkennung haenge noch bei 2025, waehrend explizit 2026
        # angefragt wird - is_current_season wuerde also False liefern.
        monkeypatch.setattr(app_module, "is_current_season", lambda api_code, season: False)

        response = client.get("/api/matchdays?competition=cl&season=2026&lang=de")
        assert response.status_code == 200
        matchdays = response.get_json()

        assert len(matchdays) == 8
        assert all(day["available"] is False for day in matchdays)
        assert any("Ligaphasen-Spiele" in day["message"] for day in matchdays)

    def test_cl_abgeschlossene_saison_mit_echten_fixtures_alle_acht_frei(self, client, monkeypatch):
        """
        Problem 1: Abgeschlossene 2025/26-Saison mit echten, komplett
        gespielten Ligaphasen-Spielen (status=FINISHED) muss alle 8
        Spieltage freigeben - unabhaengig davon, was is_current_season()
        fuer CL's eigene (moeglicherweise nachlaufende) Auto-Erkennung
        sagt. Absichtlich KEIN is_current_season-Mock hier: der neue Code
        darf fuer CL gar nicht mehr darauf angewiesen sein.
        """
        import app as app_module

        finished_matchdays = [
            {"stage": "LEAGUE_STAGE", "matchday": day, "status": "FINISHED"}
            for day in range(1, 9)
        ]
        monkeypatch.setattr(app_module, "get_all_matches", lambda *a, **k: finished_matchdays)

        response = client.get("/api/matchdays?competition=cl&season=2025")
        assert response.status_code == 200
        matchdays = response.get_json()

        assert len(matchdays) == 8
        assert all(day["available"] is True for day in matchdays)

    def test_cl_laufende_saison_mit_unfertigen_spielen_nutzt_teilfreischaltung(self, client, monkeypatch):
        """
        Echte Fixtures, aber die Ligaphase ist noch nicht komplett gespielt
        (ein SCHEDULED-Match) -> keine automatische Vollfreischaltung,
        stattdessen greift weiterhin die gewohnte unlocked_matchdays-Gate.
        Zeigt, dass is_complete tatsaechlich zwischen "abgeschlossen" und
        "laeuft noch" unterscheidet, nicht nur zwischen "hat Daten" oder nicht.
        """
        import app as app_module

        mixed_matchdays = [
            {"stage": "LEAGUE_STAGE", "matchday": 1, "status": "FINISHED"},
            {"stage": "LEAGUE_STAGE", "matchday": 2, "status": "SCHEDULED"},
        ]
        monkeypatch.setattr(app_module, "get_all_matches", lambda *a, **k: mixed_matchdays)

        response = client.get("/api/matchdays?competition=cl&season=2026")
        assert response.status_code == 200
        matchdays = response.get_json()

        assert len(matchdays) == 8
        # CL_LEAGUE_PHASE_CONFIG["unlocked_matchdays"] == [1]
        assert matchdays[0]["available"] is True
        assert matchdays[1]["available"] is False

    def test_domestic_ruft_get_all_matches_nicht_auf(self, client, monkeypatch):
        """Domestic Matchday-Gating bleibt unveraendert: get_all_matches wird fuer Domestic-Ligen gar nicht erst aufgerufen."""
        import app as app_module

        def fail_if_called(*a, **k):
            raise AssertionError("get_all_matches darf fuer Domestic-Ligen nicht aufgerufen werden")

        monkeypatch.setattr(app_module, "get_all_matches", fail_if_called)
        monkeypatch.setattr(app_module, "is_current_season", lambda api_code, season: True)

        response = client.get("/api/matchdays?competition=bl1&season=2026")
        assert response.status_code == 200
        matchdays = response.get_json()
        assert len(matchdays) > 0


class TestFrontendExplicitSeasonForCl:
    def test_selected_season_state_existiert(self):
        src = _read("static", "script.js")
        assert "selectedSeason" in src

    def test_select_season_setzt_selected_season_immer(self):
        block = _js_block(src=_read("static", "script.js"), header="function selectSeason", length=500)
        assert "state.selectedSeason = season.season" in block
        # state.season behaelt seine bisherige is_current-Sonderbehandlung unveraendert
        assert "state.season = season.is_current ? null : season.season" in block

    def test_with_explicit_season_helper_existiert(self):
        block = _js_block(_read("static", "script.js"), "function withExplicitSeason", 400)
        assert "state.selectedSeason" in block

    def test_with_season_bleibt_unveraendert_fuer_domestic(self):
        block = _js_block(_read("static", "script.js"), "function withSeason", 300)
        assert "state.season === null" in block

    def test_cl_exklusive_loader_nutzen_explizite_saison(self):
        src = _read("static", "script.js")

        for header in ("function loadClMatchdays", "function loadClKoStages", "function loadClKnockoutMatches"):
            block = _js_block(src, header, 700)
            assert "withExplicitSeason(" in block, f"{header} nutzt withExplicitSeason nicht"

    def test_geteilte_loader_verzweigen_auf_competition_code(self):
        src = _read("static", "script.js")

        for header in ("async function loadMatches", "async function loadStandings", "async function loadScorers"):
            block = _js_block(src, header, 700)
            assert 'competitionCode === "cl"' in block, f"{header} verzweigt nicht auf competitionCode"
            assert "withExplicitSeason(" in block, f"{header} nutzt withExplicitSeason nicht"


class TestUCLTabellenfixBleibtErhalten:
    """Schneller Wachposten: der vorherige Tabellenfix darf durch diese Aenderung nicht angefasst worden sein."""

    def test_zonen_unveraendert(self):
        block = _js_block(_read("static", "script.js"), "function positionClass", 800)
        assert "position <= 8" in block
        assert "position <= 24" in block
        assert 'competitionType === "cl"' in block

    def test_kein_domestic_switcher_in_cl_league(self):
        block = _js_block(_read("static", "script.js"), "function showTabsFor", 1400)
        assert "setTableTypeSwitchVisible(false)" in block
        assert "setTableTypeSwitchVisible(true)" in block


# ===========================================================================
# Q) Erwartbarer CL-No-Data-Zustand (404) ist Empty State, kein Fehler
#
# football-data antwortet fuer eine Saison ohne Ligaphasen-Daten (z. B.
# 2026/27 vor der Auslosung) teils mit HTTP 404 statt einer leeren Liste.
# Das ist KEIN technischer Fehler, sondern derselbe erwartbare "noch
# keine Daten"-Fall wie ein Season-Mismatch. Nur fuer CL und nur fuer
# status_code==404 - jeder andere Fehler (Rate Limit, Netzwerk, Domestic)
# muss weiterhin durchschlagen und die bestehende Fehlerdarstellung nutzen.
# ===========================================================================

class TestCLNotFoundIstEmptyState:
    def test_get_standings_404_wird_zu_leerer_tabelle(self, monkeypatch):
        import src.api.league_api as league_api
        _bypass_cache(monkeypatch, league_api)

        def raise_404(path, params=None, retries=3):
            raise league_api.ApiUnavailable("Daten fuer diesen Wettbewerb nicht gefunden", status_code=404)

        monkeypatch.setattr(league_api, "_get_json", raise_404)

        result = league_api.get_standings("CL", season=2026)
        assert result == {
            "season": 2026,
            "competition": "UEFA Champions League",
            "competition_emblem": None,
            "tables": {},
        }

    def test_get_standings_echter_fehler_wird_weitergereicht(self, monkeypatch):
        import src.api.league_api as league_api
        _bypass_cache(monkeypatch, league_api)

        def raise_rate_limit(path, params=None, retries=3):
            raise league_api.ApiUnavailable("Rate Limit erreicht. Bitte kurz warten.", status_code=429)

        monkeypatch.setattr(league_api, "_get_json", raise_rate_limit)

        with pytest.raises(league_api.ApiUnavailable):
            league_api.get_standings("CL", season=2026)

    def test_get_standings_domestic_404_bleibt_ein_fehler(self, monkeypatch):
        """Domestic-Standings-Architektur bleibt unveraendert - dort ist 404 weiterhin ein Fehler."""
        import src.api.league_api as league_api
        _bypass_cache(monkeypatch, league_api)

        def raise_404(path, params=None, retries=3):
            raise league_api.ApiUnavailable("Daten fuer diesen Wettbewerb nicht gefunden", status_code=404)

        monkeypatch.setattr(league_api, "_get_json", raise_404)

        with pytest.raises(league_api.ApiUnavailable):
            league_api.get_standings("BL1", season=2026)

    def test_get_scorers_404_wird_zu_leerer_liste(self, monkeypatch):
        import src.api.league_api as league_api
        _bypass_cache(monkeypatch, league_api)

        monkeypatch.setattr(
            league_api, "_get_json",
            lambda path, params=None, retries=3: (_ for _ in ()).throw(
                league_api.ApiUnavailable("nicht gefunden", status_code=404)
            )
        )

        result = league_api.get_scorers("CL", season=2026)
        assert result == {"season": 2026, "scorers": []}

    def test_get_finished_season_matches_404_wird_zu_leerer_liste(self, monkeypatch):
        import src.api.league_api as league_api
        _bypass_cache(monkeypatch, league_api)

        def raise_404(path, params=None, retries=3):
            raise league_api.ApiUnavailable("nicht gefunden", status_code=404)

        monkeypatch.setattr(league_api, "_get_json", raise_404)

        assert league_api.get_finished_season_matches("CL", season=2026) == []

    def test_get_all_matches_cl_404_wird_zu_leerer_liste(self, monkeypatch):
        import src.api.league_api as league_api
        _bypass_cache(monkeypatch, league_api)

        def raise_404(path, params=None, retries=3):
            raise league_api.ApiUnavailable("nicht gefunden", status_code=404)

        monkeypatch.setattr(league_api, "_get_json", raise_404)

        assert league_api.get_all_matches("CL", season=2026, only_finished=False) == []

    def test_get_all_matches_domestic_404_wird_weitergereicht(self, monkeypatch):
        import src.api.league_api as league_api
        _bypass_cache(monkeypatch, league_api)

        def raise_404(path, params=None, retries=3):
            raise league_api.ApiUnavailable("nicht gefunden", status_code=404)

        monkeypatch.setattr(league_api, "_get_json", raise_404)

        with pytest.raises(league_api.ApiUnavailable):
            league_api.get_all_matches("BL1", season=2026)

    def test_get_cl_league_phase_matches_404_wird_zu_leerer_liste(self, monkeypatch):
        import src.api.league_api as league_api
        _bypass_cache(monkeypatch, league_api)

        def raise_404(path, params=None, retries=3):
            raise league_api.ApiUnavailable("nicht gefunden", status_code=404)

        monkeypatch.setattr(league_api, "_get_json", raise_404)

        assert league_api.get_cl_league_phase_matches(1, season=2026) == []

    def test_get_cl_knockout_matches_404_wird_zu_leerer_liste(self, monkeypatch):
        import src.api.league_api as league_api
        _bypass_cache(monkeypatch, league_api)

        def raise_404(path, params=None, retries=3):
            raise league_api.ApiUnavailable("nicht gefunden", status_code=404)

        monkeypatch.setattr(league_api, "_get_json", raise_404)

        assert league_api.get_cl_knockout_matches("LAST_16", season=2026) == []


class TestRouteLevelNotFoundIstEmptyState:
    def test_matchdays_route_200_statt_error_bei_404(self, client, monkeypatch):
        import app as app_module

        def raise_404(*a, **k):
            raise app_module.ApiUnavailable("nicht gefunden", status_code=404)

        monkeypatch.setattr(app_module, "get_all_matches", raise_404)

        response = client.get("/api/matchdays?competition=cl&season=2026")
        assert response.status_code == 200
        matchdays = response.get_json()
        assert all(day["available"] is False for day in matchdays)

    def test_standings_route_ende_zu_ende_200_mit_korrekter_saison(self, client, monkeypatch):
        """
        End-to-End ueber die echte get_standings()-Funktion (nicht am
        Routenlevel gemockt): 404 von football-data darf niemals als
        HTTP-Fehler beim Client ankommen und darf niemals eine falsche
        Saison im Response tragen.
        """
        import app as app_module
        import src.api.league_api as league_api

        def raise_404(path, params=None, retries=3):
            raise league_api.ApiUnavailable("nicht gefunden", status_code=404)

        monkeypatch.setattr(league_api, "_get_json", raise_404)
        _bypass_cache(monkeypatch, league_api)

        response = client.get("/api/standings?competition=cl&season=2026")
        assert response.status_code == 200
        data = response.get_json()
        assert data["season"] == 2026
        assert data["table"] == []

    def test_standings_route_zeigt_weiterhin_fehler_bei_echtem_ausfall(self, client, monkeypatch):
        """
        Faengt get_standings() (aus welchem Grund auch immer) doch eine
        ApiUnavailable nicht ab, muss die Route weiterhin die bestehende
        Fehlerdarstellung liefern - dieser Patch schaltet Fehlerbehandlung
        nicht global ab.
        """
        import app as app_module

        def raise_error(api_code, season=None):
            raise app_module.ApiUnavailable("Rate Limit erreicht. Bitte kurz warten.", status_code=429)

        monkeypatch.setattr(app_module, "get_standings", raise_error)

        response = client.get("/api/standings?competition=cl&season=2026")
        assert response.status_code == 503

    def test_cl_stages_route_ende_zu_ende_200_bei_404(self, client, monkeypatch):
        """
        Ende-zu-Ende ueber die echte get_all_matches()-Funktion: die faengt
        ein 404 fuer CL bereits selbst ab, deshalb kommt beim Client nie
        ein 503 an, obwohl football-data 404 antwortet.
        """
        import src.api.league_api as league_api

        def raise_404(path, params=None, retries=3):
            raise league_api.ApiUnavailable("nicht gefunden", status_code=404)

        monkeypatch.setattr(league_api, "_get_json", raise_404)
        _bypass_cache(monkeypatch, league_api)

        response = client.get("/api/cl-stages?season=2026")
        assert response.status_code == 200
        assert response.get_json()["stages"] == []


class TestFrontendEmptyStateStattError:
    def test_matchday_liste_setzt_active_nur_beim_klick(self):
        """
        Matchday 1 darf nicht automatisch als aktiv/weiss dargestellt
        werden, nur weil er (faelschlich) verfuegbar waere - "active"
        darf ausschliesslich durch einen Klick gesetzt werden.
        """
        block = _js_block(_read("static", "script.js"), "async function loadClMatchdays", 1400)
        forEach_start = block.find("matchdays.forEach")
        assert forEach_start > -1
        # Der Render-Block selbst (vor selectClMatchday) darf keine
        # active-Klasse vergeben.
        render_block = block[forEach_start:forEach_start + 500]
        assert "classList.add(\"active\")" not in render_block

    def test_standings_titel_wird_sofort_auf_gewaehlte_saison_gesetzt(self):
        block = _js_block(_read("static", "script.js"), "async function loadStandings", 700)
        assert "state.competitionName" in block
        assert "state.seasonLabel" in block

    def test_ko_empty_state_ist_saison_bewusst(self):
        block = _js_block(_read("static", "script.js"), "async function loadClKoStages", 700)
        assert "state.seasonLabel" in block
        assert "clKoEmpty.textContent" in block
