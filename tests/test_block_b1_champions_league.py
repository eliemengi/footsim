"""
Regressionstests fuer Block B1 (Phase 4.0).

Abgedeckt:
  - Keine verbliebenen aktiven Referenzen auf die alten hartcodierten
    CL-Dictionaries (MATCHES_TO_PREDICT_CL*, UCL_SECOND_LEG_CONTEXT).
  - CL laeuft ueber denselben generischen Matchday-/Standings-/Scorers-
    Pfad wie die nationalen Ligen, ohne LEAGUE_CONFIG zu erweitern
    (kein Doppel-Listing in /api/competitions).
  - /api/cl-stages liefert echte, dynamisch ermittelte K.-o.-Runden.
  - CL-Ligaphasen-Spielsimulation laeuft ueber die neue, ID-basierte
    Fallback-Kette (Top-5-Liga-Historie -> echte CL-Ergebnisse ->
    neutral_profile), inklusive des Bodoe/Glimt-Szenarios.
  - Bundesliga und die anderen bestehenden Ligen bleiben unveraendert
    funktionsfaehig (Regression).
"""

import os
import pytest


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ===========================================================================
# Keine Altlasten mehr
# ===========================================================================

class TestKeineHardcodiertenCLReferenzen:
    def test_matches_to_predict_hat_keine_cl_dicts_mehr(self):
        import src.predict.matches_to_predict as mtp
        for name in ("MATCHES_TO_PREDICT_CL", "MATCHES_TO_PREDICT_CL_RO16",
                     "MATCHES_TO_PREDICT_CL_QF", "MATCHES_TO_PREDICT_CL_SF",
                     "UCL_SECOND_LEG_CONTEXT", "UCL_RO16_SECOND_LEG_CONTEXT",
                     "UCL_QF_SECOND_LEG_CONTEXT", "UCL_SF_SECOND_LEG_CONTEXT"):
            assert not hasattr(mtp, name), f"{name} ist noch in matches_to_predict.py vorhanden"

    def test_el_ist_weiterhin_vorhanden(self):
        """Europa League bleibt unangetastet - nur CL wurde entfernt."""
        import src.predict.matches_to_predict as mtp
        assert hasattr(mtp, "MATCHES_TO_PREDICT_EL")
        assert hasattr(mtp, "UEL_SECOND_LEG_CONTEXT")
        assert len(mtp.MATCHES_TO_PREDICT_EL) == 8

    def test_matches_to_predict_generischer_fallback_zeigt_auf_el(self):
        import src.predict.matches_to_predict as mtp
        assert mtp.MATCHES_TO_PREDICT is mtp.MATCHES_TO_PREDICT_EL

    def test_app_py_importiert_keine_cl_dicts_mehr(self):
        """
        Erlaubt sind erklaerende KOMMENTARE, die die Namen der alten
        Dicts zur Dokumentation erwaehnen (z. B. "ersetzt
        MATCHES_TO_PREDICT_CL"). Nicht erlaubt ist ein echter Import
        oder eine echte Code-Referenz. Deshalb wird hier die
        tatsaechlich importierte Zeile geprueft, nicht der gesamte
        Dateitext.
        """
        path = os.path.join(PROJECT_ROOT, "app.py")
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()

        import_block = []
        inside_import = False
        for line in lines:
            if "from src.predict.matches_to_predict import" in line:
                inside_import = True
            if inside_import:
                import_block.append(line)
                if ")" in line:
                    break

        import_text = "".join(import_block)
        for name in ("MATCHES_TO_PREDICT_CL_RO16", "MATCHES_TO_PREDICT_CL_QF",
                     "MATCHES_TO_PREDICT_CL_SF", "MATCHES_TO_PREDICT_CL"):
            assert name not in import_text, f"app.py importiert noch {name}"

    def test_app_py_hat_zur_laufzeit_keine_cl_dict_namen(self):
        """Bestaetigt zusaetzlich, dass die Namen im geladenen Modul nicht existieren."""
        import app as app_module
        for name in ("MATCHES_TO_PREDICT_CL_RO16", "MATCHES_TO_PREDICT_CL_QF",
                     "MATCHES_TO_PREDICT_CL_SF", "MATCHES_TO_PREDICT_CL"):
            assert not hasattr(app_module, name), f"app.py hat noch ein Attribut {name}"

    def test_simulate_scores_hat_keinen_cl_branch_mehr(self):
        path = os.path.join(PROJECT_ROOT, "src", "predict", "simulate_scores.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert "MATCHES_TO_PREDICT_CL" not in src
        assert "UCL_SECOND_LEG_CONTEXT" not in src
        # EL bleibt drin
        assert "MATCHES_TO_PREDICT_EL" in src

    def test_simulate_selected_match_kennt_kein_cl_mehr(self):
        """
        simulate_selected_match muss weiterhin importierbar und lauffaehig
        sein (EL-Pfad!), darf aber fuer eine (nicht mehr existierende)
        CL-match_id keinen Sonderfall mehr haben.
        """
        from src.predict.simulate_scores import simulate_selected_match
        with pytest.raises(ValueError):
            simulate_selected_match(match_id="gala_liverpool")  # alte CL-ID, muss ValueError geben

    def test_app_py_importiert_simulate_selected_match_nicht_mehr(self):
        """
        Der Import ist tot, da keine Route mehr darauf zeigt (CL laeuft
        jetzt ueber cl_match_sim.simulate_cl_league_phase_match).
        """
        path = os.path.join(PROJECT_ROOT, "app.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert "import simulate_selected_match" not in src

    def test_competition_matches_hat_keinen_cl_key_mehr(self):
        import app as app_module
        assert "cl" not in app_module.COMPETITION_MATCHES
        assert "el" in app_module.COMPETITION_MATCHES


# ===========================================================================
# CL nicht in LEAGUE_CONFIG - kein Doppel-Listing
# ===========================================================================

class TestKeinDoppelListing:
    def test_cl_ist_nicht_in_league_config(self):
        import app as app_module
        assert "cl" not in app_module.LEAGUE_CONFIG

    def test_resolve_competition_config_findet_cl(self):
        import app as app_module
        config = app_module._resolve_competition_config("cl")
        assert config is not None
        assert config["api_code"] == "CL"
        assert config["total_matchdays"] == 8

    def test_resolve_competition_config_domestic_unveraendert(self):
        import app as app_module
        for code in ("bl1", "pl", "pd", "sa", "fl1"):
            assert app_module._resolve_competition_config(code) == app_module.LEAGUE_CONFIG[code]

    def test_resolve_competition_config_unbekannt_gibt_none(self):
        import app as app_module
        assert app_module._resolve_competition_config("xx") is None


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


class TestCompetitionsListing:
    def test_cl_erscheint_genau_einmal(self, client, monkeypatch):
        import app as app_module
        monkeypatch.setattr(app_module, "is_current_season", lambda api_code, season: True)

        response = client.get("/api/competitions")
        assert response.status_code == 200
        data = response.get_json()

        cl_entries = [c for c in data if c["code"] == "cl"]
        assert len(cl_entries) == 1, f"CL erscheint {len(cl_entries)} mal statt einmal"
        assert cl_entries[0]["type"] == "cl"


# ===========================================================================
# CL ueber den generischen Matchday-Pfad
# ===========================================================================

class TestCLMatchday:
    def test_cl_matchday_route_nutzt_stage_gefilterten_loader(self, client, monkeypatch):
        """
        Seit B2 laeuft CL ueber get_cl_league_phase_match_options (mit
        stage=LEAGUE_STAGE), nicht mehr ueber den generischen Loader.
        """
        import app as app_module

        captured = {}

        def fake_cl_options(matchday, season=None):
            captured["matchday"] = matchday
            captured["season"] = season
            return [{
                "id": "cl_3_bayern_vs_psg",
                "home_team": "Bayern", "away_team": "Paris",
                "home_id": 5, "away_id": 524,
                "matchday": matchday, "competition": "cl",
            }]

        monkeypatch.setattr(app_module, "get_cl_league_phase_match_options", fake_cl_options)
        monkeypatch.setattr(app_module, "is_matchday_unlocked", lambda *a, **k: True)

        response = client.get("/api/matches?competition=cl&matchday=3&season=2025")
        assert response.status_code == 200
        data = response.get_json()

        assert captured["matchday"] == 3
        assert data[0]["home_id"] == 5
        assert data[0]["away_id"] == 524

    def test_cl_matchday_gesperrt_liefert_leere_liste(self, client, monkeypatch):
        import app as app_module
        monkeypatch.setattr(app_module, "is_matchday_unlocked", lambda *a, **k: False)

        response = client.get("/api/matches?competition=cl&matchday=5&season=2026")
        assert response.status_code == 200
        assert response.get_json() == []

    def test_alte_round_navigation_existiert_nicht_mehr(self):
        """
        Der 'round'-Query-Parameter (ro16/qf/sf) darf im Quellcode von
        /api/matches nicht mehr als Sonderfall behandelt werden.
        """
        path = os.path.join(PROJECT_ROOT, "app.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert 'request.args.get("round"' not in src


# ===========================================================================
# CL ueber den generischen Standings-/Scorers-Pfad
# ===========================================================================

class TestCLStandingsUndScorers:
    def test_cl_standings_ruft_generische_funktion(self, client, monkeypatch):
        import app as app_module

        captured = {}

        def fake_get_standings(api_code, season=None):
            captured["api_code"] = api_code
            return {
                "season": season,
                "competition": "Champions League",
                "tables": {"TOTAL": [{"team_id": 5, "team_name": "Bayern", "played": 8}]},
            }

        monkeypatch.setattr(app_module, "get_standings", fake_get_standings)

        response = client.get("/api/standings?competition=cl&season=2025")
        assert response.status_code == 200
        data = response.get_json()

        assert captured["api_code"] == "CL"
        assert data["competition"] == "Champions League"
        assert data["table"][0]["team_name"] == "Bayern"

    def test_cl_scorers_ruft_generische_funktion(self, client, monkeypatch):
        import app as app_module

        captured = {}

        def fake_get_scorers(api_code, season=None, limit=20):
            captured["api_code"] = api_code
            return {"season": season, "scorers": [{"player_name": "H. Kane", "goals": 5}]}

        monkeypatch.setattr(app_module, "get_scorers", fake_get_scorers)

        response = client.get("/api/scorers?competition=cl&season=2025")
        assert response.status_code == 200
        data = response.get_json()

        assert captured["api_code"] == "CL"
        assert data["scorers"][0]["player_name"] == "H. Kane"

    def test_cl_player_scorers_empty_state_bei_ungestarteter_saison(self, client, monkeypatch):
        import app as app_module
        from src.api import apisports_api

        monkeypatch.setattr(
            app_module, "get_finished_season_matches",
            lambda api_code, season=None: []
        )
        called = []
        monkeypatch.setattr(
            apisports_api, "get_top_scorers",
            lambda *a, **k: called.append(True) or []
        )

        response = client.get("/api/player-scorers?competition=cl&season=2026")
        assert response.status_code == 200
        data = response.get_json()
        assert data.get("empty_state") is True
        assert not called


# ===========================================================================
# /api/cl-stages - echte, dynamische K.-o.-Runden
# ===========================================================================

class TestCLStages:
    def test_liefert_nur_tatsaechlich_vorhandene_stages(self, client, monkeypatch):
        import app as app_module

        fake_matches = [
            {"stage": "LEAGUE_STAGE", "matchday": 1},
            {"stage": "LEAGUE_STAGE", "matchday": 2},
            {"stage": "LAST_16", "matchday": None},
            {"stage": "LAST_16", "matchday": None},
            {"stage": "QUARTER_FINALS", "matchday": None},
        ]
        monkeypatch.setattr(
            app_module, "get_all_matches",
            lambda api_code, season=None, only_finished=False: fake_matches
        )

        response = client.get("/api/cl-stages?season=2025&lang=de")
        assert response.status_code == 200
        data = response.get_json()

        stage_codes = [s["stage"] for s in data["stages"]]
        assert stage_codes == ["LAST_16", "QUARTER_FINALS"]
        assert "LEAGUE_STAGE" not in stage_codes

    def test_leere_liste_vor_der_auslosung(self, client, monkeypatch):
        """Vor der ersten K.-o.-Auslosung gibt es nur Ligaphasen-Spiele."""
        import app as app_module

        fake_matches = [
            {"stage": "LEAGUE_STAGE", "matchday": 1},
            {"stage": "LEAGUE_STAGE", "matchday": 2},
        ]
        monkeypatch.setattr(
            app_module, "get_all_matches",
            lambda api_code, season=None, only_finished=False: fake_matches
        )

        response = client.get("/api/cl-stages?season=2026")
        assert response.status_code == 200
        assert response.get_json()["stages"] == []

    def test_labels_sind_deutsch(self, client, monkeypatch):
        import app as app_module

        fake_matches = [{"stage": "SEMI_FINALS", "matchday": None}]
        monkeypatch.setattr(
            app_module, "get_all_matches",
            lambda api_code, season=None, only_finished=False: fake_matches
        )

        response = client.get("/api/cl-stages?season=2025&lang=de")
        data = response.get_json()
        assert data["stages"][0]["label"] == "Halbfinale"


# ===========================================================================
# CL-Fallback-Kette: Top-5-Historie -> echte CL-Ergebnisse -> neutral
# ===========================================================================

class TestCLFallbackKette:
    def test_resolve_bevorzugt_top5_liga_historie(self):
        from src.predict.cl_match_sim import _resolve_cl_profile

        strengths = {
            "domestic_by_id": {5: {"team_id": 5, "team_name": "Bayern", "attack_home": 1.6}},
            "cl_current_by_id": {5: {"team_id": 5, "team_name": "Bayern", "attack_home": 1.9}},
        }

        profile, resolution = _resolve_cl_profile(strengths, 5, "Bayern")
        assert resolution == "domestic_history"
        assert profile["attack_home"] == 1.6  # Stufe 0, nicht Stufe 1

    def test_bodo_glimt_faellt_auf_cl_ergebnisse_zurueck(self):
        """
        Kernszenario aus der Diskussion: Bodoe/Glimt hat KEINE Top-5-
        Ligahistorie (Norwegen wird von FootSim nicht simuliert), aber
        echte CL-Ergebnisse dieser Saison. Es darf NICHT direkt auf
        neutral_profile fallen.
        """
        from src.predict.cl_match_sim import _resolve_cl_profile

        BODO_GLIMT_ID = 5721
        strengths = {
            "domestic_by_id": {5: {"team_id": 5, "team_name": "Bayern"}},  # Bodoe fehlt hier
            "cl_current_by_id": {
                BODO_GLIMT_ID: {
                    "team_id": BODO_GLIMT_ID, "team_name": "FK Bodoe/Glimt",
                    "attack_home": 1.3, "matches_used": 6,
                }
            },
        }

        profile, resolution = _resolve_cl_profile(strengths, BODO_GLIMT_ID, "FK Bodoe/Glimt")
        assert resolution == "cl_current_season", (
            "Bodoe/Glimt haette auf Stufe 1 (echte CL-Ergebnisse) landen muessen, "
            f"ist aber auf Stufe '{resolution}' gelandet."
        )
        assert profile["matches_used"] == 6

    def test_team_ganz_ohne_daten_faellt_auf_neutral(self):
        from src.predict.cl_match_sim import _resolve_cl_profile

        strengths = {"domestic_by_id": {}, "cl_current_by_id": {}}
        profile, resolution = _resolve_cl_profile(strengths, 999999, "Unbekannter Verein")

        assert resolution == "neutral"
        assert profile["attack_home"] == 1.0  # NEUTRAL_RATING

    def test_get_cl_team_strengths_baut_beide_quellen(self, monkeypatch):
        """
        get_cl_team_strengths muss domestic_by_id UND cl_current_by_id
        befuellen, nicht nur eine der beiden Quellen.
        """
        from src.features import strength_provider

        # Historie: ein Top-5-Team.
        fake_season_payload = {
            "meta": {"api_code": "BL1", "season": 2025},
            "teams": {5: {"id": 5, "name": "FC Bayern München", "short_name": "Bayern"}},
            "matches": [
                {"matchday": 1, "date": "2025-08-01", "home_id": 5, "away_id": 999,
                 "home_goals": 3, "away_goals": 0},
            ],
        }
        # Seit V2-C1 laedt die Profilfabrik ueber historical_loader.
        # Dort sitzt die Naht - und zwar fuer BEIDE Quellen, damit der
        # Test ohne lokale Dateien und ohne Netz auskommt.
        from src.data import historical_loader

        monkeypatch.setattr(
            historical_loader, "load_season",
            lambda api_code, season: (fake_season_payload
                                      if api_code == "BL1" and season == 2025
                                      else None))
        monkeypatch.setattr(historical_loader, "load_cl_season", lambda s: None)

        # Echte CL-Ergebnisse: ein Non-Top5-Team (Bodoe/Glimt-artig).
        fake_cl_matches = [
            {"home_id": 5721, "away_id": 610, "home_goals": 3, "away_goals": 1,
             "matchday": 3, "date": "2025-10-01"},
        ]
        monkeypatch.setattr(strength_provider, "get_all_matches", lambda *a, **k: fake_cl_matches)

        strengths = strength_provider.get_cl_team_strengths(
            season=2025, cutoff="2025-12-01")

        assert 5 in strengths["domestic_by_id"], "Bayern muss aus der BL1-Historie kommen"
        assert 5721 in strengths["cl_current_by_id"], "Team 5721 muss aus echten CL-Ergebnissen kommen"
        assert 610 in strengths["cl_current_by_id"]

    def test_get_cl_team_strengths_ohne_cl_daten_bricht_nicht(self, monkeypatch):
        """Vor Saisonbeginn (keine CL-Spiele) darf die Funktion nicht abstuerzen."""
        from src.features import strength_provider

        from src.data import historical_loader

        monkeypatch.setattr(historical_loader, "load_season",
                            lambda api_code, season: None)
        monkeypatch.setattr(historical_loader, "load_cl_season", lambda s: None)
        monkeypatch.setattr(strength_provider, "get_all_matches", lambda *a, **k: [])

        strengths = strength_provider.get_cl_team_strengths(
            season=2026, cutoff="2026-08-01")

        assert strengths["domestic_by_id"] == {}
        assert strengths["cl_current_by_id"] == {}
        assert strengths["league_avg"]["matches"] == 0


# ===========================================================================
# CL-Ligaphasen-Spielsimulation ueber /api/simulate
# ===========================================================================

class TestCLSimulation:
    def test_cl_simulation_ruft_neue_engine_auf(self, client, monkeypatch):
        import app as app_module

        captured = {}

        # options spiegelt die echte Signatur (C8A). Ohne den Parameter
        # scheiterte der Mock mit TypeError, und die Route antwortete
        # mit 500 statt 200.
        def fake_simulate(home_team, away_team, home_id=None, away_id=None,
                           season=None, simulations=5000, use_seed=False,
                           options=None):
            captured.update(locals())
            return {
                "home_team": home_team, "away_team": away_team,
                "home_win_probability": 45.0, "draw_probability": 25.0,
                "away_win_probability": 30.0, "expected_home_goals": 1.8,
                "expected_away_goals": 1.2, "top_scores": [],
                "competition": "Champions League", "phase": "league",
                "home_resolution": "domestic_history", "away_resolution": "cl_current_season",
            }

        monkeypatch.setattr(app_module, "simulate_cl_league_phase_match", fake_simulate)

        response = client.post("/api/simulate", json={
            "competition": "cl",
            "home_team": "Bayern", "away_team": "FK Bodoe/Glimt",
            "home_id": 5, "away_id": 5721,
            "season": 2025, "simulations": 2000,
        })
        assert response.status_code == 200
        data = response.get_json()

        assert captured["home_id"] == 5
        assert captured["away_id"] == 5721
        assert data["phase"] == "league"
        # Ein Request ohne 'approach' darf keine Optionen erzeugen -
        # bestehendes Verhalten bleibt unveraendert.
        assert captured["options"] is None
        assert data["away_resolution"] == "cl_current_season"

    def test_cl_simulation_ohne_teamnamen_gibt_fehler(self, client):
        response = client.post("/api/simulate", json={"competition": "cl"})
        assert response.status_code == 400
        assert "fehlt" in response.get_json().get("error", "")

    def test_cl_simulation_nutzt_kein_match_id_mehr(self, client, monkeypatch):
        """
        Ein alter match_id-basierter Aufruf (wie er frueher fuer CL noetig
        war) darf nicht mehr funktionieren, wenn kein home_team/away_team
        mitgeschickt wird.
        """
        response = client.post("/api/simulate", json={
            "competition": "cl",
            "match_id": "gala_liverpool",
        })
        assert response.status_code == 400


# ===========================================================================
# Regression: nationale Ligen unveraendert funktionsfaehig
# ===========================================================================

class TestDomestischeLigenRegression:
    def test_bundesliga_matchday_weiterhin_ueber_league_config(self, client, monkeypatch):
        import app as app_module

        captured = {}

        def fake_match_options(competition_code, api_code, matchday, season=None):
            captured["api_code"] = api_code
            return []

        monkeypatch.setattr(app_module, "get_matchday_match_options", fake_match_options)
        monkeypatch.setattr(app_module, "is_matchday_unlocked", lambda *a, **k: True)

        response = client.get("/api/matches?competition=bl1&matchday=1")
        assert response.status_code == 200
        assert captured["api_code"] == "BL1"

    def test_alle_fuenf_ligen_weiterhin_in_league_config(self):
        import app as app_module
        for code in ("bl1", "pl", "pd", "sa", "fl1"):
            assert code in app_module.LEAGUE_CONFIG

    def test_bundesliga_simulation_weiterhin_ueber_alten_pfad(self, client, monkeypatch):
        import app as app_module

        captured = {}

        def fake_simulate_league_match(**kwargs):
            captured.update(kwargs)
            return {"home_team": kwargs["home_team"], "away_team": kwargs["away_team"]}

        monkeypatch.setattr(app_module, "simulate_league_match", fake_simulate_league_match)

        response = client.post("/api/simulate", json={
            "competition": "bl1",
            "home_team": "Bayern", "away_team": "Dortmund",
        })
        assert response.status_code == 200
        assert captured["api_code"] == "BL1"

    def test_is_matchday_unlocked_domestic_unveraendert(self, monkeypatch):
        import app as app_module
        monkeypatch.setattr(app_module, "UNLOCK_ALL_MATCHDAYS", False)
        monkeypatch.setattr(app_module, "is_current_season", lambda api_code, season: True)

        # Hier geht es darum, dass der DOMESTIC-Pfad unveraendert ueber
        # LEAGUE_CONFIG entscheidet - nicht darum, welche Spieltage
        # gerade freigeschaltet sind. Die konkreten Tage kommen deshalb
        # aus der Konfiguration selbst. Vorher stand "Spieltag 2 ist
        # gesperrt" fest im Test; das brach, sobald Spieltag 2 regulaer
        # freigeschaltet wurde, ohne dass die CL-Trennung gelitten haette.
        freigeschaltet = app_module.LEAGUE_CONFIG["bl1"]["unlocked_matchdays"]

        assert app_module.is_matchday_unlocked("bl1", freigeschaltet[0], season=2026) is True
        assert app_module.is_matchday_unlocked(
            "bl1", max(freigeschaltet) + 1, season=2026
        ) is False
