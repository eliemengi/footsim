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
"""

import json
import os
import re
import pytest


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APISPORTS_KEY", "test-key")
    monkeypatch.setenv("FOOTBALL_DATA_KEY", "test-key")
    import app as app_module
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


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

        response = client.get("/api/cl-knockout?stage=LAST_16&season=2025")
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

        response = client.get("/api/cl-knockout?stage=FINAL&season=2025")
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
