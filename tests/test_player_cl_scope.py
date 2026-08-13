"""
Regressionstests fuer den Champions-League-Scope in Player Analytics.

Abgedeckt:
  A) Scope-Filter: "cl" akzeptiert ausschliesslich league_id == 2
  B) Aggregation: Domestic + CL + Pokal -> bei scope="cl" nur CL-Werte
  C) Spieler ohne CL-Daten: data_available False, keine Fake-Nullen
  D) Vergleich mit gemischter Verfuegbarkeit stuerzt nicht ab
  E) CL-Perzentile stammen ausschliesslich aus echten CL-Spielern
  F) Scatter akzeptiert scope="cl" und zeigt keine kuenstlichen 0-Punkte
  G) Die vier bestehenden Scopes bleiben unveraendert
  H) Registrierung/Verdrahtung in Backend und Oberflaeche

Kein echter API-Request: alle Tests arbeiten auf synthetischen Rohantworten
im Format von /players?id=&season=.
"""

import os

import pytest

from src.data.player_compare_loader import (
    SCOPE_CL,
    SCOPE_CLUB_ALL,
    SCOPE_LEAGUE,
    SCOPE_NATIONAL,
    SCOPE_ALL,
    COMPETITION_SCOPES,
    SCOPE_LABELS,
    SCOPE_HINTS,
    build_comparison,
    build_player_profile,
    entry_matches_scope,
    normalize_scope,
)


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --- Wettbewerbs-IDs, wie API-Sports sie verwendet -------------------------

ID_BUNDESLIGA = 78
ID_PREMIER_LEAGUE = 39
ID_CHAMPIONS_LEAGUE = 2
ID_EUROPA_LEAGUE = 3
ID_CONFERENCE_LEAGUE = 848
ID_DFB_POKAL = 81
ID_WORLD_CUP = 1
ID_EURO = 4
ID_FRIENDLIES = 10


def _block(league_id, name, minutes, goals, league_type=None,
           position="Attacker", assists=1):
    """Ein statistics-Block im echten API-Sports-Format."""
    return {
        "league": {"id": league_id, "name": name, "type": league_type,
                   "country": "Germany"},
        "team": {"id": 1, "name": f"Team {league_id}", "logo": None},
        "games": {"appearences": 5, "lineups": 5, "minutes": minutes,
                  "position": position, "rating": "7.50"},
        "shots": {"total": 10, "on": 5},
        "goals": {"total": goals, "conceded": None, "assists": assists,
                  "saves": None},
        "passes": {"total": 100, "key": 3, "accuracy": "80"},
        "tackles": {"total": 2, "blocks": 0, "interceptions": 1},
        "duels": {"total": 20, "won": 10},
        "dribbles": {"attempts": 5, "success": 3},
        "fouls": {"drawn": 2, "committed": 1},
        "cards": {"yellow": 1, "red": 0},
        "penalty": {"saved": None, "scored": 0, "missed": 0},
    }


def _raw(player_id, name, blocks):
    return {"player": {"id": player_id, "name": name}, "statistics": blocks}


# ===========================================================================
# A) Scope-Filter
# ===========================================================================

class TestClScopeFilter:
    def test_champions_league_wird_akzeptiert(self):
        block = _block(ID_CHAMPIONS_LEAGUE, "UEFA Champions League", 600, 4)
        assert entry_matches_scope(block, SCOPE_CL) is True

    @pytest.mark.parametrize("league_id,name", [
        (ID_BUNDESLIGA, "Bundesliga"),
        (ID_PREMIER_LEAGUE, "Premier League"),
        (ID_EUROPA_LEAGUE, "UEFA Europa League"),
        (ID_CONFERENCE_LEAGUE, "UEFA Europa Conference League"),
        (ID_DFB_POKAL, "DFB Pokal"),
        (ID_WORLD_CUP, "World Cup"),
        (ID_EURO, "Euro Championship"),
        (ID_FRIENDLIES, "Friendlies"),
    ])
    def test_andere_wettbewerbe_werden_ausgeschlossen(self, league_id, name):
        block = _block(league_id, name, 500, 3)
        assert entry_matches_scope(block, SCOPE_CL) is False

    def test_europa_league_trotz_cup_typ_ausgeschlossen(self):
        """
        Der entscheidende Unterschied zu club_all: EL ist ebenfalls ein
        "Cup", darf im cl-Scope aber nicht mitzaehlen.
        """
        block = _block(ID_EUROPA_LEAGUE, "UEFA Europa League", 500, 3,
                       league_type="Cup")
        assert entry_matches_scope(block, SCOPE_CLUB_ALL) is True
        assert entry_matches_scope(block, SCOPE_CL) is False

    def test_id_entscheidet_auch_bei_abweichendem_typ(self):
        """
        Die league.id ist eindeutig. Selbst wenn API-Sports einen
        unerwarteten Typ meldet, darf der CL-Block nicht verloren gehen.
        """
        block = _block(ID_CHAMPIONS_LEAGUE, "UEFA Champions League", 600, 4,
                       league_type="League")
        assert entry_matches_scope(block, SCOPE_CL) is True

    def test_block_ohne_league_id_wird_ausgeschlossen(self):
        block = _block(None, "Unbekannt", 500, 3)
        assert entry_matches_scope(block, SCOPE_CL) is False


# ===========================================================================
# B) Aggregation
# ===========================================================================

class TestClAggregation:
    def _mixed_player(self):
        return _raw(99, "Testspieler", [
            _block(ID_BUNDESLIGA, "Bundesliga", 2000, 10),
            _block(ID_CHAMPIONS_LEAGUE, "UEFA Champions League", 600, 4),
            _block(ID_DFB_POKAL, "DFB Pokal", 300, 2),
        ])

    def test_cl_scope_liefert_ausschliesslich_cl_werte(self):
        profile = build_player_profile(self._mixed_player(), 2025, scope=SCOPE_CL)

        assert profile["minutes"] == 600
        assert profile["stats"]["goals"]["total"] == 4
        assert profile["competition_count"] == 1
        assert [c["name"] for c in profile["competitions"]] == \
               ["UEFA Champions League"]
        assert profile["data_available"] is True

    def test_domestic_werte_werden_nicht_eingemischt(self):
        profile = build_player_profile(self._mixed_player(), 2025, scope=SCOPE_CL)

        # 2000 (Liga) + 600 (CL) + 300 (Pokal) = 2900 waere club_all
        assert profile["minutes"] != 2900
        assert profile["stats"]["goals"]["total"] != 16

    def test_club_all_enthaelt_weiterhin_alles(self):
        profile = build_player_profile(self._mixed_player(), 2025,
                                       scope=SCOPE_CLUB_ALL)
        assert profile["minutes"] == 2900
        assert profile["stats"]["goals"]["total"] == 16

    def test_mehrere_cl_bloecke_werden_summiert(self):
        """Vereinswechsel innerhalb derselben CL-Saison."""
        raw = _raw(99, "Wechsler", [
            _block(ID_CHAMPIONS_LEAGUE, "UEFA Champions League", 400, 2),
            _block(ID_CHAMPIONS_LEAGUE, "UEFA Champions League", 200, 1),
        ])
        profile = build_player_profile(raw, 2025, scope=SCOPE_CL)

        assert profile["minutes"] == 600
        assert profile["stats"]["goals"]["total"] == 3


# ===========================================================================
# C) Spieler ohne CL-Daten
# ===========================================================================

class TestOhneClDaten:
    def _domestic_only(self):
        return _raw(7, "St.-Pauli-Spieler", [
            _block(ID_BUNDESLIGA, "Bundesliga", 2000, 10),
            _block(ID_DFB_POKAL, "DFB Pokal", 300, 2),
        ])

    def test_data_available_ist_false(self):
        profile = build_player_profile(self._domestic_only(), 2025, scope=SCOPE_CL)
        assert profile["data_available"] is False

    def test_keine_fake_nullen(self):
        """
        Entscheidend: fehlende Daten bleiben None. Eine 0 waere die Aussage
        "hat gespielt und nichts erreicht" - das waere schlicht falsch.
        """
        profile = build_player_profile(self._domestic_only(), 2025, scope=SCOPE_CL)

        assert profile["minutes"] is None
        assert profile["stats"]["goals"]["total"] is None
        assert profile["stats"]["shots"]["total"] is None
        assert profile["stats"]["games"]["rating"] is None

    def test_kein_fallback_auf_domestic(self):
        profile = build_player_profile(self._domestic_only(), 2025, scope=SCOPE_CL)

        assert profile["competitions"] == []
        assert profile["competition_count"] == 0
        assert profile["minutes"] != 2000

    def test_domestic_scope_desselben_spielers_funktioniert_weiter(self):
        profile = build_player_profile(self._domestic_only(), 2025,
                                       scope=SCOPE_CLUB_ALL)
        assert profile["data_available"] is True
        assert profile["minutes"] == 2300

    def test_reiner_cl_spieler_ohne_top5_liga_ist_verfuegbar(self):
        """
        Ein Spieler mit CL-Minuten, aber ohne Einsatz in einer der fuenf
        Vergleichsligen: im cl-Scope gueltig, weil die Vergleichsgruppe
        dort der CL-Pool ist und kein Ligapool.
        """
        raw = _raw(50, "Galatasaray-Spieler", [
            _block(ID_CHAMPIONS_LEAGUE, "UEFA Champions League", 500, 3),
        ])
        profile = build_player_profile(raw, 2025, scope=SCOPE_CL)

        assert profile["data_available"] is True
        assert profile["minutes"] == 500


# ===========================================================================
# D) Vergleich mit gemischter Verfuegbarkeit
# ===========================================================================

class TestGemischteVerfuegbarkeit:
    def _with_cl(self):
        return build_player_profile(_raw(1, "Mit CL", [
            _block(ID_BUNDESLIGA, "Bundesliga", 2000, 10),
            _block(ID_CHAMPIONS_LEAGUE, "UEFA Champions League", 600, 4),
        ]), 2025, scope=SCOPE_CL)

    def _without_cl(self):
        return build_player_profile(_raw(2, "Ohne CL", [
            _block(ID_BUNDESLIGA, "Bundesliga", 2000, 8),
        ]), 2025, scope=SCOPE_CL)

    def test_nur_spieler_a_hat_cl_daten(self):
        comparison = build_comparison(self._with_cl(), self._without_cl())

        assert comparison["metrics"]
        # A traegt echte Werte, B bleibt durchgehend None.
        assert any(m["value_a"] is not None for m in comparison["metrics"])
        assert all(m["value_b"] is None for m in comparison["metrics"])

    def test_nur_spieler_b_hat_cl_daten(self):
        comparison = build_comparison(self._without_cl(), self._with_cl())

        assert all(m["value_a"] is None for m in comparison["metrics"])
        assert any(m["value_b"] is not None for m in comparison["metrics"])

    def test_beide_ohne_cl_daten_kein_absturz(self):
        comparison = build_comparison(self._without_cl(), self._without_cl())

        assert comparison["metrics"]
        assert all(m["value_a"] is None for m in comparison["metrics"])
        assert all(m["value_b"] is None for m in comparison["metrics"])
        assert comparison["percentiles_available"] is False

    def test_beide_mit_cl_daten(self):
        other = build_player_profile(_raw(3, "Auch CL", [
            _block(ID_CHAMPIONS_LEAGUE, "UEFA Champions League", 700, 6),
        ]), 2025, scope=SCOPE_CL)

        comparison = build_comparison(self._with_cl(), other)
        assert any(m["value_a"] is not None for m in comparison["metrics"])
        assert any(m["value_b"] is not None for m in comparison["metrics"])


# ===========================================================================
# E) CL-Perzentile
# ===========================================================================

class TestClPercentiles:
    def _pool_entry(self, player_id, cl_minutes, cl_goals_per90,
                    league_minutes=2000, league_goals_per90=0.1):
        """
        Pooleintrag im scope-bewussten Schema. cl_minutes=None bedeutet:
        der Spieler hat keine Champions-League-Daten.
        """
        minutes = {"club_all": league_minutes, "league": league_minutes,
                   "national": None, "all": league_minutes}
        metrics = {
            "club_all": {"goals_per90": league_goals_per90},
            "league": {"goals_per90": league_goals_per90},
            "national": {},
            "all": {"goals_per90": league_goals_per90},
        }

        minutes["cl"] = cl_minutes
        metrics["cl"] = {} if cl_minutes is None else {"goals_per90": cl_goals_per90}

        return {
            "player_id": player_id,
            "name": f"Spieler {player_id}",
            "position": "Attacker",
            "league_code": "bl1",
            "age": 25,
            "team_name": "Test FC",
            "minutes_by_scope": minutes,
            "metrics_by_scope": metrics,
        }

    def test_cl_ist_eigener_snapshot_scope(self):
        from src.data.percentile_engine import SNAPSHOT_SCOPES
        assert "cl" in SNAPSHOT_SCOPES

    def test_cl_verteilung_enthaelt_nur_echte_cl_spieler(self):
        from src.data.percentile_engine import build_snapshot, distributions_for_scope

        # 40 Spieler mit CL-Daten, 40 ohne. MIN_POOL_SIZE ist 30.
        entries = [self._pool_entry(i, 900, 0.5 + i * 0.01) for i in range(40)]
        entries += [self._pool_entry(500 + i, None, None) for i in range(40)]

        snapshot = build_snapshot(entries, 2025, ["bl1"], min_minutes=450)
        cl_dist = distributions_for_scope(snapshot, "cl").get("Attacker")

        assert cl_dist is not None
        assert cl_dist["player_count"] == 40

    def test_cl_verteilung_unterscheidet_sich_von_domestic(self):
        from src.data.percentile_engine import build_snapshot, distributions_for_scope

        entries = [
            self._pool_entry(i, 900, 0.9, league_minutes=2000,
                             league_goals_per90=0.1)
            for i in range(40)
        ]
        snapshot = build_snapshot(entries, 2025, ["bl1"], min_minutes=450)

        cl_dist = distributions_for_scope(snapshot, "cl")["Attacker"]
        league_dist = distributions_for_scope(snapshot, "league")["Attacker"]

        assert cl_dist["metrics"]["goals_per90"]["q"] != \
               league_dist["metrics"]["goals_per90"]["q"]

    def test_spieler_ohne_cl_minuten_zaehlt_nicht_in_die_cl_verteilung(self):
        from src.data.percentile_engine import build_snapshot, distributions_for_scope

        entries = [self._pool_entry(i, 900, 0.5) for i in range(35)]
        entries += [self._pool_entry(900 + i, None, None) for i in range(20)]

        snapshot = build_snapshot(entries, 2025, ["bl1"], min_minutes=450)

        cl_dist = distributions_for_scope(snapshot, "cl")["Attacker"]
        league_dist = distributions_for_scope(snapshot, "league")["Attacker"]

        assert cl_dist["player_count"] == 35
        assert league_dist["player_count"] == 55

    def test_mindestminuten_greifen_gegen_cl_minuten(self):
        """
        Die Grenze muss sich auf die CL-Minuten beziehen, nicht auf die
        Gesamtminuten. Sonst kaeme ein Spieler mit 3000 Ligaminuten und
        90 CL-Minuten in den CL-Pool.
        """
        from src.data.percentile_engine import build_snapshot, distributions_for_scope

        entries = [self._pool_entry(i, 90, 1.0, league_minutes=3000)
                   for i in range(40)]
        snapshot = build_snapshot(entries, 2025, ["bl1"], min_minutes=450)

        assert distributions_for_scope(snapshot, "cl").get("Attacker") is None


# ===========================================================================
# F) Scatter
# ===========================================================================

class TestClScatter:
    def _entry(self, player_id, cl_minutes, cl_goals):
        metrics_cl = {} if cl_minutes is None else {
            "goals_per90": cl_goals, "assists_per90": 0.2,
        }
        return {
            "player_id": player_id,
            "name": f"Spieler {player_id}",
            "position": "Attacker",
            "league_code": "bl1",
            "age": 25,
            "team_name": "Test FC",
            "minutes_by_scope": {"club_all": 2000, "league": 2000,
                                 "cl": cl_minutes, "national": None,
                                 "all": 2000},
            "metrics_by_scope": {
                "club_all": {"goals_per90": 0.4, "assists_per90": 0.2},
                "league": {"goals_per90": 0.4, "assists_per90": 0.2},
                "cl": metrics_cl,
                "national": {},
                "all": {"goals_per90": 0.4, "assists_per90": 0.2},
            },
        }

    def _patch_pool(self, monkeypatch, entries):
        from src.data import player_pool
        monkeypatch.setattr(player_pool, "load_all_players",
                            lambda season, codes: (entries, list(codes)))

    def test_scope_cl_wird_akzeptiert(self, monkeypatch):
        from src.data.player_pool import load_scatter_points

        self._patch_pool(monkeypatch, [self._entry(1, 900, 0.6)])
        points, used = load_scatter_points(
            2025, ["bl1"], None, 450, "goals_per90", "assists_per90", scope="cl",
        )

        assert len(points) == 1
        assert points[0]["x"] == 0.6
        assert points[0]["minutes"] == 900

    def test_spieler_ohne_cl_daten_erscheinen_nicht(self, monkeypatch):
        from src.data.player_pool import load_scatter_points

        self._patch_pool(monkeypatch, [
            self._entry(1, 900, 0.6),
            self._entry(2, None, None),
            self._entry(3, None, None),
        ])
        points, _ = load_scatter_points(
            2025, ["bl1"], None, 450, "goals_per90", "assists_per90", scope="cl",
        )

        assert len(points) == 1
        assert points[0]["id"] == 1

    def test_keine_kuenstlichen_nullpunkte(self, monkeypatch):
        from src.data.player_pool import load_scatter_points

        self._patch_pool(monkeypatch, [self._entry(i, None, None) for i in range(5)])
        points, _ = load_scatter_points(
            2025, ["bl1"], None, 450, "goals_per90", "assists_per90", scope="cl",
        )

        assert points == []

    def test_ligafilter_und_scope_sind_getrennte_dimensionen(self, monkeypatch):
        """
        Bundesliga-Pool + Scope CL heisst: Spieler aus dem Bundesliga-Pool,
        bewertet nach ihren Champions-League-Werten.
        """
        from src.data.player_pool import load_scatter_points

        entry = self._entry(1, 900, 0.6)
        self._patch_pool(monkeypatch, [entry])

        points, used = load_scatter_points(
            2025, ["bl1"], None, 450, "goals_per90", "assists_per90", scope="cl",
        )

        assert used == ["bl1"]
        assert points[0]["league"] == "bl1"     # Herkunftsliga bleibt
        assert points[0]["x"] == 0.6            # aber CL-Wert, nicht 0.4

    def test_unbekannter_scope_faellt_weiter_auf_club_all(self, monkeypatch):
        from src.data.player_pool import load_scatter_points

        self._patch_pool(monkeypatch, [self._entry(1, None, None)])
        points, _ = load_scatter_points(
            2025, ["bl1"], None, 450, "goals_per90", "assists_per90",
            scope="gibtsnicht",
        )

        assert len(points) == 1
        assert points[0]["x"] == 0.4


# ===========================================================================
# G) Regression der vier bestehenden Scopes
# ===========================================================================

class TestBestehendeScopesUnveraendert:
    def _all_competitions(self):
        return _raw(1, "Allrounder", [
            _block(ID_BUNDESLIGA, "Bundesliga", 2000, 10),
            _block(ID_CHAMPIONS_LEAGUE, "UEFA Champions League", 600, 4),
            _block(ID_DFB_POKAL, "DFB Pokal", 300, 2),
            _block(ID_WORLD_CUP, "World Cup", 400, 3),
        ])

    def test_club_all_unveraendert(self):
        profile = build_player_profile(self._all_competitions(), 2025,
                                       scope=SCOPE_CLUB_ALL)
        assert profile["minutes"] == 2900          # Liga + CL + Pokal
        assert profile["data_available"] is True

    def test_league_unveraendert(self):
        profile = build_player_profile(self._all_competitions(), 2025,
                                       scope=SCOPE_LEAGUE)
        assert profile["minutes"] == 2000
        assert profile["data_available"] is True

    def test_national_unveraendert(self):
        profile = build_player_profile(self._all_competitions(), 2025,
                                       scope=SCOPE_NATIONAL)
        assert profile["minutes"] == 400
        assert profile["data_available"] is True

    def test_all_unveraendert(self):
        profile = build_player_profile(self._all_competitions(), 2025,
                                       scope=SCOPE_ALL)
        assert profile["minutes"] == 3300          # alles zusammen
        assert profile["data_available"] is True

    def test_default_scope_bleibt_club_all(self):
        from src.data.player_compare_loader import DEFAULT_SCOPE
        assert DEFAULT_SCOPE == SCOPE_CLUB_ALL
        assert normalize_scope(None) == SCOPE_CLUB_ALL
        assert normalize_scope("unsinn") == SCOPE_CLUB_ALL

    def test_bestehende_scope_reihenfolge_erhalten(self):
        """
        Die vier urspruenglichen Scopes bleiben enthalten und behalten ihre
        relative Reihenfolge; cl kommt hinzu.

        Bewusst KEINE feste Gesamtlaenge: weitere wettbewerbsscharfe Scopes
        (euro, world_cup, ...) duerfen dazukommen, ohne diesen Test zu
        brechen. Geschuetzt wird, dass nichts Bestehendes verschwindet oder
        umsortiert wird.
        """
        original = [SCOPE_CLUB_ALL, SCOPE_LEAGUE, SCOPE_NATIONAL, SCOPE_ALL]
        for scope in original:
            assert scope in COMPETITION_SCOPES
        assert SCOPE_CL in COMPETITION_SCOPES
        assert [s for s in COMPETITION_SCOPES if s in original] == original


# ===========================================================================
# H) Registrierung und Verdrahtung
# ===========================================================================

def _read(*parts):
    with open(os.path.join(PROJECT_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class TestVerdrahtung:
    def test_scope_hat_label_und_hinweis(self):
        assert SCOPE_LABELS[SCOPE_CL] == "Champions League"
        assert SCOPE_HINTS[SCOPE_CL]

    def test_normalize_akzeptiert_cl(self):
        assert normalize_scope("cl") == SCOPE_CL
        assert normalize_scope(" CL ") == SCOPE_CL

    def test_scatter_endpoint_bietet_cl_an(self, monkeypatch):
        monkeypatch.setenv("APISPORTS_KEY", "test-key")
        monkeypatch.setenv("FOOTBALL_DATA_KEY", "test-key")
        import app as app_module
        app_module.app.config["TESTING"] = True

        with app_module.app.test_client() as client:
            monkeypatch.setattr(app_module, "load_scatter_points",
                                lambda *a, **k: ([], ["bl1"]))
            response = client.get("/api/player-scatter?season=2025&scope=cl")

        assert response.status_code == 200
        data = response.get_json()
        assert data["scope"] == "cl"
        assert data["scope_label"] == "Champions League"
        assert "cl" in [s["key"] for s in data["scopes"]]

    def test_compare_endpoint_akzeptiert_cl(self, monkeypatch):
        monkeypatch.setenv("APISPORTS_KEY", "test-key")
        monkeypatch.setenv("FOOTBALL_DATA_KEY", "test-key")
        import app as app_module
        app_module.app.config["TESTING"] = True

        captured = {}

        def fake_profile(player_id, season, scope=None):
            captured["scope"] = scope
            return build_player_profile(
                _raw(player_id, f"P{player_id}", [
                    _block(ID_CHAMPIONS_LEAGUE, "UEFA Champions League", 600, 4),
                ]), season, scope=scope,
            )

        monkeypatch.setattr(app_module, "get_player_season_profile", fake_profile)
        monkeypatch.setattr(app_module, "load_percentile_snapshot", lambda s: None)

        with app_module.app.test_client() as client:
            response = client.get(
                "/api/player-compare?a=1&b=2&season_a=2025&scope=cl"
            )

        assert response.status_code == 200
        assert captured["scope"] == "cl"

    def test_buttons_in_beiden_scope_navigationen(self):
        html = _read("templates", "index.html")
        # Radar-Navigation und Scatter-Navigation, seit Block LIVE D1
        # zusaetzlich die Wettbewerbsauswahl im Spielerprofil (pd-scope-nav).
        assert html.count('data-scope="cl"') == 3
        assert html.count('data-i18n="scope.cl"') == 3

    def test_buttons_nutzen_bestehendes_muster(self):
        html = _read("templates", "index.html")
        assert 'class="pc-scope-btn"\n                                role="radio" aria-checked="false" data-scope="cl"' in html

    def test_frontend_kennt_cl_hinweis(self):
        script = _read("static", "script.js")
        start = script.find("scopeHint: {")
        assert start > -1
        block = script[start:start + 900]
        assert "cl:" in block

    def test_frontend_hat_neutralen_empty_state(self):
        script = _read("static", "script.js")
        assert "function pcBuildScopeDataNote" in script
        assert "scopeNoDataBoth" in script
        # Neutrale pc-note, kein Fehlerzustand.
        start = script.find("function pcBuildScopeDataNote")
        block = script[start:start + 1200]
        assert 'make("div", "pc-note")' in block
        assert "error" not in block.lower()

    def test_kein_neues_css(self):
        """Der CL-Scope nutzt ausschliesslich vorhandenes Styling."""
        css = _read("static", "style.css")
        for cls in (".pc-scope-btn", ".pc-note", ".pc-head-detail"):
            assert cls in css

    def test_cl_ligasimulation_unberuehrt(self):
        """Dieser Patch darf die CL-Ligasimulation nicht verändern."""
        for module in ("cl_fixture_plan", "cl_season_sim"):
            path = os.path.join(PROJECT_ROOT, "src", "predict", f"{module}.py")
            assert os.path.exists(path)

        script = _read("static", "script.js")
        assert "function renderClSeasonTable" in script
        assert "async function runClSeasonSim" in script
