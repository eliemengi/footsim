"""
Regressionstests fuer Block A (Phase 4.0).

Abgedeckt:
  A1 – build_and_save_snapshot existiert als aufrufbare Top-Level-Funktion.
  A5 – Saisonzuordnung FootSim<->API-Sports ohne Bug-Offset.
  A5 – Empty-State-Gate: keine alte Torjaegerliste fuer ungestartete Saisons.
"""

import os
import pytest


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestBuildAndSaveSnapshot:
    def test_funktion_importierbar(self):
        import refresh_players
        assert callable(getattr(refresh_players, "build_and_save_snapshot", None)), (
            "build_and_save_snapshot ist nicht als Top-Level-Funktion definiert."
        )

    def test_funktion_ist_nicht_eingebettet(self):
        import refresh_players
        fn = getattr(refresh_players, "build_and_save_snapshot", None)
        assert fn is not None
        qualname = getattr(fn, "__qualname__", "")
        assert "<locals>" not in qualname

    def test_alle_drei_aufrufstellen_im_modul(self):
        path = os.path.join(PROJECT_ROOT, "refresh_players.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert src.count("build_and_save_snapshot(") >= 3

    def test_kein_toter_code_hinter_return(self):
        import ast
        path = os.path.join(PROJECT_ROOT, "refresh_players.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "enrich_pool_with_national":
                stmts = node.body
                for i, stmt in enumerate(stmts):
                    if isinstance(stmt, ast.Return) and i < len(stmts) - 1:
                        pytest.fail("Unerreichbarer Code nach return in enrich_pool_with_national")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APISPORTS_KEY", "test-key")
    monkeypatch.setenv("FOOTBALL_DATA_KEY", "test-key")
    import app as app_module
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


class TestSaisonzuordnung:
    def test_kein_season_minus_1_offset_in_app_py(self):
        path = os.path.join(PROJECT_ROOT, "app.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert "apisports_season = (season - 1)" not in src


class TestEmptyStateGate:
    def test_empty_state_wenn_keine_finished_matches(self, client, monkeypatch):
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

        response = client.get("/api/player-scorers?competition=bl1&season=2026")
        assert response.status_code == 200
        data = response.get_json()
        assert data.get("empty_state") is True
        assert data.get("scorers") == []
        assert not called

    def test_season_parameter_ohne_offset(self, client, monkeypatch):
        import app as app_module
        from src.api import apisports_api

        monkeypatch.setattr(
            app_module, "get_finished_season_matches",
            lambda api_code, season=None: [{"matchday": 1, "home_goals": 1, "away_goals": 0}]
        )
        received = []
        monkeypatch.setattr(
            apisports_api, "get_top_scorers",
            lambda competition_code, season=None, limit=20: received.append(season) or []
        )

        client.get("/api/player-scorers?competition=bl1&season=2025")
        assert received == [2025]

    def test_alle_ligen_unterstuetzt(self, client, monkeypatch):
        import app as app_module
        from src.api import apisports_api

        monkeypatch.setattr(
            app_module, "get_finished_season_matches",
            lambda api_code, season=None: []
        )
        monkeypatch.setattr(apisports_api, "get_top_scorers", lambda *a, **k: [])

        for code in ("bl1", "pl", "pd", "sa", "fl1"):
            response = client.get(f"/api/player-scorers?competition={code}&season=2026")
            assert response.status_code == 200
            assert response.get_json().get("empty_state") is True


class TestI18nBereinigung:
    def test_i18n_dateien_entfernt(self):
        assert not os.path.exists(os.path.join(PROJECT_ROOT, "static", "i18n", "de.json"))
        assert not os.path.exists(os.path.join(PROJECT_ROOT, "static", "i18n", "en.json"))


class TestSocialLinks:
    def _read_index(self):
        path = os.path.join(PROJECT_ROOT, "templates", "index.html")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_instagram_und_tiktok_vorhanden(self):
        src = self._read_index()
        assert "instagram.com/elie_rdc" in src
        assert "tiktok.com/@elie_rdc" in src

    def test_disabled_spans_entfernt(self):
        src = self._read_index()
        assert "Instagram — folgt" not in src
        assert "TikTok — folgt" not in src
