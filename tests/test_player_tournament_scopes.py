"""
Regressionstests fuer die Turnier-Scopes euro und world_cup.

Abgedeckt:
  A) Scope-Filter: euro nur league_id 4, world_cup nur league_id 1
  B) Season-Mapping (inkl. COVID-Sonderfall EM 2021)
  C) Saisonverfuegbarkeit
  D) Aggregation und Spieler ohne Turnierdaten
  E) Gemischte Verfuegbarkeit im Vergleich
  F) Wettbewerbsspezifische Mindestminuten
  G) Perzentile
  H) Scatter
  I) Offline-Backfill mit Nationalbloecken
  J) Isolierter Einzelwettbewerbs-Import
  K) Regression der bestehenden Scopes

Kein Test macht einen echten API-Request.
"""

import os

import pytest

from src.data.player_compare_loader import (
    SCOPE_ALL,
    SCOPE_CL,
    SCOPE_CLUB_ALL,
    SCOPE_EURO,
    SCOPE_LEAGUE,
    SCOPE_NATIONAL,
    SCOPE_WORLD_CUP,
    COMPETITION_SCOPES,
    SCOPE_HINTS,
    SCOPE_LABELS,
    build_comparison,
    build_player_profile,
    entry_matches_scope,
    normalize_scope,
)
from src.data.national_competitions import (
    FOOTSIM_SEASON_OF_TOURNAMENT,
    NATIONAL_COMPETITIONS,
    TOURNAMENT_SCOPE_LEAGUE_IDS,
    footsim_seasons_for_tournament_scope,
    national_targets_for_footsim_season,
    tournament_scope_availability,
)
from src.data.percentile_engine import (
    DEFAULT_MIN_MINUTES,
    SCOPE_MIN_MINUTES,
    SNAPSHOT_SCOPES,
    build_snapshot,
    describe_pool,
    distributions_for_scope,
    min_minutes_for_scope,
)


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --- API-Sports-Wettbewerbs-IDs -------------------------------------------

ID_BUNDESLIGA = 78
ID_CHAMPIONS_LEAGUE = 2
ID_WORLD_CUP = 1
ID_EURO = 4
ID_NATIONS_LEAGUE = 5
ID_FRIENDLIES = 10
ID_WC_QUALI_EUROPE = 32
ID_EURO_QUALI = 960
ID_COPA_AMERICA = 9
ID_AFCON = 6
ID_GOLD_CUP = 22


def _block(league_id, name, minutes, goals, position="Attacker"):
    return {
        "league": {"id": league_id, "name": name, "type": None, "country": "World"},
        "team": {"id": 1, "name": f"Team {league_id}", "logo": None},
        "games": {"appearences": 3, "lineups": 3, "minutes": minutes,
                  "position": position, "rating": "7.20"},
        "shots": {"total": 8, "on": 4},
        "goals": {"total": goals, "conceded": None, "assists": 1, "saves": None},
        "passes": {"total": 90, "key": 3, "accuracy": "82"},
        "tackles": {"total": 2, "blocks": 0, "interceptions": 1},
        "duels": {"total": 18, "won": 9},
        "dribbles": {"attempts": 4, "success": 2},
        "fouls": {"drawn": 2, "committed": 1},
        "cards": {"yellow": 1, "red": 0},
        "penalty": {"saved": None, "scored": 0, "missed": 0},
    }


def _raw(player_id, name, blocks):
    return {"player": {"id": player_id, "name": name}, "statistics": blocks}


def _read(*parts):
    with open(os.path.join(PROJECT_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


# ===========================================================================
# A) Scope-Filter
# ===========================================================================

class TestTournamentScopeFilter:
    def test_world_cup_akzeptiert_nur_league_id_1(self):
        assert entry_matches_scope(
            _block(ID_WORLD_CUP, "World Cup", 400, 2), SCOPE_WORLD_CUP) is True

    def test_euro_akzeptiert_nur_league_id_4(self):
        assert entry_matches_scope(
            _block(ID_EURO, "Euro Championship", 400, 2), SCOPE_EURO) is True

    @pytest.mark.parametrize("league_id,name", [
        (ID_BUNDESLIGA, "Bundesliga"),
        (ID_CHAMPIONS_LEAGUE, "UEFA Champions League"),
        (ID_EURO, "Euro Championship"),
        (ID_NATIONS_LEAGUE, "UEFA Nations League"),
        (ID_FRIENDLIES, "Friendlies"),
        (ID_WC_QUALI_EUROPE, "World Cup - Qualification Europe"),
        (ID_EURO_QUALI, "Euro Championship - Qualification"),
        (ID_COPA_AMERICA, "Copa America"),
        (ID_AFCON, "Africa Cup of Nations"),
        (ID_GOLD_CUP, "CONCACAF Gold Cup"),
    ])
    def test_world_cup_schliesst_alles_andere_aus(self, league_id, name):
        assert entry_matches_scope(
            _block(league_id, name, 400, 2), SCOPE_WORLD_CUP) is False

    @pytest.mark.parametrize("league_id,name", [
        (ID_BUNDESLIGA, "Bundesliga"),
        (ID_CHAMPIONS_LEAGUE, "UEFA Champions League"),
        (ID_WORLD_CUP, "World Cup"),
        (ID_NATIONS_LEAGUE, "UEFA Nations League"),
        (ID_FRIENDLIES, "Friendlies"),
        (ID_WC_QUALI_EUROPE, "World Cup - Qualification Europe"),
        (ID_EURO_QUALI, "Euro Championship - Qualification"),
        (ID_COPA_AMERICA, "Copa America"),
        (ID_AFCON, "Africa Cup of Nations"),
    ])
    def test_euro_schliesst_alles_andere_aus(self, league_id, name):
        assert entry_matches_scope(
            _block(league_id, name, 400, 2), SCOPE_EURO) is False

    def test_qualifikation_zaehlt_nicht_zur_endrunde(self):
        """
        Der wichtigste Trennfall: Quali und Endrunde liegen beide im
        international-Bucket und haben aehnliche Namen.
        """
        quali = _block(ID_EURO_QUALI, "Euro Championship - Qualification", 500, 3)
        assert entry_matches_scope(quali, SCOPE_EURO) is False
        # ... gehoert aber weiterhin zum Sammel-Scope national.
        assert entry_matches_scope(quali, SCOPE_NATIONAL) is True

    def test_endrunden_zaehlen_weiter_zum_sammel_scope(self):
        for league_id, name in ((ID_WORLD_CUP, "World Cup"), (ID_EURO, "Euro Championship")):
            block = _block(league_id, name, 400, 2)
            assert entry_matches_scope(block, SCOPE_NATIONAL) is True
            assert entry_matches_scope(block, SCOPE_ALL) is True

    def test_endrunden_zaehlen_nicht_zu_vereinsscopes(self):
        for league_id, name in ((ID_WORLD_CUP, "World Cup"), (ID_EURO, "Euro Championship")):
            block = _block(league_id, name, 400, 2)
            assert entry_matches_scope(block, SCOPE_CLUB_ALL) is False
            assert entry_matches_scope(block, SCOPE_LEAGUE) is False
            assert entry_matches_scope(block, SCOPE_CL) is False


# ===========================================================================
# B) Season-Mapping
# ===========================================================================

class TestSeasonMapping:
    @pytest.mark.parametrize("league_id,api_season,footsim_season,label", [
        (4, 2020, 2020, "EM 2021 (EURO 2020)"),
        (1, 2022, 2022, "WM 2022"),
        (4, 2024, 2023, "EM 2024"),
        (1, 2026, 2025, "WM 2026"),
    ])
    def test_verifiziertes_mapping(self, league_id, api_season, footsim_season, label):
        assert FOOTSIM_SEASON_OF_TOURNAMENT[(league_id, api_season)] == footsim_season, label

    def test_em_2021_ist_kein_n_minus_1(self):
        """
        COVID-Sonderfall: API-Season 2020, FootSim 2020. Eine generische
        "api_season - 1"-Regel wuerde faelschlich 2019 ergeben.
        """
        assert FOOTSIM_SEASON_OF_TOURNAMENT[(4, 2020)] == 2020
        assert FOOTSIM_SEASON_OF_TOURNAMENT[(4, 2020)] != 2019

    def test_wm_2022_zaehlt_zur_saison_2022(self):
        """WM 2022 lag im Winter - sie gehoert zu FootSim 2022/23."""
        assert FOOTSIM_SEASON_OF_TOURNAMENT[(1, 2022)] == 2022

    def test_verifizierte_usable_seasons(self):
        assert sorted(NATIONAL_COMPETITIONS[1]["usable_seasons"]) == [2022, 2026]
        assert sorted(NATIONAL_COMPETITIONS[4]["usable_seasons"]) == [2020, 2024]

    def test_scope_league_ids(self):
        assert TOURNAMENT_SCOPE_LEAGUE_IDS["euro"] == 4
        assert TOURNAMENT_SCOPE_LEAGUE_IDS["world_cup"] == 1

    def test_footsim_seasons_je_scope(self):
        assert footsim_seasons_for_tournament_scope("euro") == frozenset({2020, 2023})
        assert footsim_seasons_for_tournament_scope("world_cup") == frozenset({2022, 2025})

    def test_unbekannter_scope_hat_keine_saisons(self):
        assert footsim_seasons_for_tournament_scope("gibtsnicht") == frozenset()


# ===========================================================================
# C) Saisonverfuegbarkeit
# ===========================================================================

class TestSeasonAvailability:
    @pytest.mark.parametrize("season,euro,world_cup", [
        (2020, True,  False),   # EM 2021
        (2021, False, False),   # kein Turnier
        (2022, False, True),    # WM 2022
        (2023, True,  False),   # EM 2024
        (2024, False, False),   # kein Turnier
        (2025, False, True),    # WM 2026
    ])
    def test_verfuegbarkeit_je_saison(self, season, euro, world_cup):
        available = tournament_scope_availability(season)
        assert available["euro"] is euro
        assert available["world_cup"] is world_cup

    def test_verfuegbarkeit_meldet_nur_turnierscopes(self):
        available = tournament_scope_availability(2025)
        assert set(available) == {"euro", "world_cup"}
        # Liga/CL/national sind immer verfuegbar und tauchen deshalb nicht auf.
        assert "cl" not in available
        assert "league" not in available

    def test_route_liefert_verfuegbarkeit_je_saison(self, monkeypatch):
        monkeypatch.setenv("APISPORTS_KEY", "test-key")
        monkeypatch.setenv("FOOTBALL_DATA_KEY", "test-key")
        import app as app_module
        app_module.app.config["TESTING"] = True

        with app_module.app.test_client() as client:
            response = client.get("/api/player-seasons")

        assert response.status_code == 200
        by_season = {s["season"]: s for s in response.get_json()["seasons"]}

        assert by_season[2025]["tournaments_available"]["world_cup"] is True
        assert by_season[2025]["tournaments_available"]["euro"] is False
        assert by_season[2023]["tournaments_available"]["euro"] is True
        assert by_season[2024]["tournaments_available"] == {"euro": False,
                                                            "world_cup": False}


# ===========================================================================
# D) Aggregation und fehlende Turnierdaten
# ===========================================================================

class TestAggregationUndFehlendeDaten:
    def _mixed(self):
        return _raw(10, "Nationalspieler", [
            _block(ID_BUNDESLIGA, "Bundesliga", 2000, 12),
            _block(ID_CHAMPIONS_LEAGUE, "UEFA Champions League", 600, 4),
            _block(ID_WORLD_CUP, "World Cup", 450, 3),
            _block(ID_EURO, "Euro Championship", 300, 2),
            _block(ID_FRIENDLIES, "Friendlies", 180, 1),
            _block(ID_WC_QUALI_EUROPE, "World Cup - Qualification Europe", 540, 5),
        ])

    def test_world_cup_liefert_nur_wm_werte(self):
        profile = build_player_profile(self._mixed(), 2025, scope=SCOPE_WORLD_CUP)
        assert profile["minutes"] == 450
        assert profile["stats"]["goals"]["total"] == 3
        assert [c["name"] for c in profile["competitions"]] == ["World Cup"]

    def test_euro_liefert_nur_em_werte(self):
        profile = build_player_profile(self._mixed(), 2023, scope=SCOPE_EURO)
        assert profile["minutes"] == 300
        assert profile["stats"]["goals"]["total"] == 2
        assert [c["name"] for c in profile["competitions"]] == ["Euro Championship"]

    def test_quali_und_friendlies_bleiben_draussen(self):
        profile = build_player_profile(self._mixed(), 2025, scope=SCOPE_WORLD_CUP)
        # 450 (WM) - NICHT 450+540 (Quali) und nicht +180 (Friendlies)
        assert profile["minutes"] == 450

    def test_sammel_scope_national_enthaelt_weiterhin_alles(self):
        profile = build_player_profile(self._mixed(), 2025, scope=SCOPE_NATIONAL)
        assert profile["minutes"] == 450 + 300 + 180 + 540

    def test_ohne_turnierdaten_keine_fake_nullen(self):
        raw = _raw(11, "Kein Turnier", [
            _block(ID_BUNDESLIGA, "Bundesliga", 2000, 12),
            _block(ID_FRIENDLIES, "Friendlies", 180, 1),
        ])
        for scope in (SCOPE_EURO, SCOPE_WORLD_CUP):
            profile = build_player_profile(raw, 2025, scope=scope)
            assert profile["data_available"] is False
            assert profile["minutes"] is None
            assert profile["stats"]["goals"]["total"] is None
            assert profile["competitions"] == []

    def test_kein_domestic_fallback(self):
        raw = _raw(12, "Nur Liga", [_block(ID_BUNDESLIGA, "Bundesliga", 2000, 12)])
        profile = build_player_profile(raw, 2025, scope=SCOPE_WORLD_CUP)
        assert profile["minutes"] != 2000
        assert profile["minutes"] is None

    def test_kein_national_all_fallback(self):
        """Friendlies duerfen keinen WM-Wert vortaeuschen."""
        raw = _raw(13, "Nur Freundschaftsspiele", [
            _block(ID_BUNDESLIGA, "Bundesliga", 2000, 12),
            _block(ID_FRIENDLIES, "Friendlies", 270, 2),
        ])
        profile = build_player_profile(raw, 2025, scope=SCOPE_WORLD_CUP)
        assert profile["data_available"] is False
        assert profile["minutes"] is None

    def test_spieler_ohne_top5_liga_bleibt_gueltig(self):
        raw = _raw(14, "Legionaer", [_block(ID_WORLD_CUP, "World Cup", 500, 4)])
        profile = build_player_profile(raw, 2025, scope=SCOPE_WORLD_CUP)
        assert profile["data_available"] is True
        assert profile["minutes"] == 500


# ===========================================================================
# E) Gemischte Verfuegbarkeit
# ===========================================================================

class TestGemischteVerfuegbarkeit:
    def _with_wc(self):
        return build_player_profile(_raw(1, "Kane", [
            _block(ID_BUNDESLIGA, "Bundesliga", 2000, 20),
            _block(ID_WORLD_CUP, "World Cup", 540, 4),
        ]), 2025, scope=SCOPE_WORLD_CUP)

    def _without_wc(self):
        return build_player_profile(_raw(2, "Haaland", [
            _block(ID_BUNDESLIGA, "Bundesliga", 2000, 25),
        ]), 2025, scope=SCOPE_WORLD_CUP)

    def test_nur_spieler_a_hat_turnierdaten(self):
        comparison = build_comparison(self._with_wc(), self._without_wc())
        assert comparison["metrics"]
        assert any(m["value_a"] is not None for m in comparison["metrics"])
        assert all(m["value_b"] is None for m in comparison["metrics"])

    def test_nur_spieler_b_hat_turnierdaten(self):
        comparison = build_comparison(self._without_wc(), self._with_wc())
        assert all(m["value_a"] is None for m in comparison["metrics"])
        assert any(m["value_b"] is not None for m in comparison["metrics"])

    def test_beide_ohne_turnierdaten(self):
        comparison = build_comparison(self._without_wc(), self._without_wc())
        assert comparison["metrics"]
        assert all(m["value_a"] is None for m in comparison["metrics"])
        assert comparison["percentiles_available"] is False

    def test_data_available_unterscheidet_beide_spieler(self):
        assert self._with_wc()["data_available"] is True
        assert self._without_wc()["data_available"] is False


# ===========================================================================
# F) Wettbewerbsspezifische Mindestminuten
# ===========================================================================

class TestMindestminuten:
    def test_turniere_nutzen_270(self):
        assert min_minutes_for_scope("euro") == 270
        assert min_minutes_for_scope("world_cup") == 270
        assert SCOPE_MIN_MINUTES == {"euro": 270, "world_cup": 270}

    @pytest.mark.parametrize("scope", ["club_all", "league", "cl", "national", "all"])
    def test_bestehende_scopes_bleiben_bei_450(self, scope):
        assert min_minutes_for_scope(scope) == DEFAULT_MIN_MINUTES == 450

    def test_uebergebener_standard_gilt_fuer_nicht_turniere(self):
        assert min_minutes_for_scope("league", 600) == 600
        # Turniere behalten ihren Sonderwert.
        assert min_minutes_for_scope("world_cup", 600) == 270

    def test_scatter_default_ist_scope_abhaengig(self, monkeypatch, tmp_path):
        monkeypatch.setenv("APISPORTS_KEY", "test-key")
        monkeypatch.setenv("FOOTBALL_DATA_KEY", "test-key")
        import app as app_module
        app_module.app.config["TESTING"] = True

        # Die Route cacht ihr Ergebnis ueber disk_cached_call - sonst
        # antwortet sie aus einem frueheren Lauf statt neu zu rechnen.
        from src.utils import disk_cache
        monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path / "cache"))

        captured = {}

        def fake_points(season, leagues, position, min_minutes, x, y, scope="club_all"):
            captured["min_minutes"] = min_minutes
            return [], list(leagues)

        monkeypatch.setattr(app_module, "load_scatter_points", fake_points)

        with app_module.app.test_client() as client:
            client.get("/api/player-scatter?season=2025&scope=world_cup")
            assert captured["min_minutes"] == 270

            client.get("/api/player-scatter?season=2025&scope=club_all")
            assert captured["min_minutes"] == 450

    def test_benutzerwert_schlaegt_den_default(self, monkeypatch, tmp_path):
        monkeypatch.setenv("APISPORTS_KEY", "test-key")
        monkeypatch.setenv("FOOTBALL_DATA_KEY", "test-key")
        import app as app_module
        app_module.app.config["TESTING"] = True

        from src.utils import disk_cache
        monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path / "cache"))

        captured = {}

        def fake_points(season, leagues, position, min_minutes, x, y, scope="club_all"):
            captured["min_minutes"] = min_minutes
            return [], list(leagues)

        monkeypatch.setattr(app_module, "load_scatter_points", fake_points)

        with app_module.app.test_client() as client:
            # Ausdrueckliche Nutzereingabe - auch hoeher als der Default.
            client.get("/api/player-scatter?season=2025&scope=world_cup&min_minutes=600")
            assert captured["min_minutes"] == 600

            client.get("/api/player-scatter?season=2025&scope=world_cup&min_minutes=0")
            assert captured["min_minutes"] == 0


# ===========================================================================
# G) Perzentile
# ===========================================================================

class TestPercentiles:
    def _entry(self, player_id, wc_minutes, wc_goals_per90):
        minutes = {"club_all": 2000, "league": 2000, "cl": None,
                   "euro": None, "national": None, "all": 2000}
        metrics = {"club_all": {"goals_per90": 0.3}, "league": {"goals_per90": 0.3},
                   "cl": {}, "euro": {}, "national": {}, "all": {"goals_per90": 0.3}}
        minutes["world_cup"] = wc_minutes
        metrics["world_cup"] = ({} if wc_minutes is None
                                else {"goals_per90": wc_goals_per90})
        return {
            "player_id": player_id, "name": f"Spieler {player_id}",
            "position": "Attacker", "league_code": "bl1", "age": 26,
            "team_name": "Test FC",
            "minutes_by_scope": minutes, "metrics_by_scope": metrics,
        }

    def test_turniere_sind_eigene_snapshot_scopes(self):
        assert "euro" in SNAPSHOT_SCOPES
        assert "world_cup" in SNAPSHOT_SCOPES

    def test_verteilung_nur_aus_echten_turnierspielern(self):
        entries = [self._entry(i, 400, 0.5 + i * 0.01) for i in range(40)]
        entries += [self._entry(500 + i, None, None) for i in range(40)]

        snapshot = build_snapshot(entries, 2025, ["bl1"])
        dist = distributions_for_scope(snapshot, "world_cup")["Attacker"]
        assert dist["player_count"] == 40

    def test_270_minuten_eligibility(self):
        """269 Minuten fallen raus, 270 sind drin."""
        below = [self._entry(i, 269, 0.5) for i in range(40)]
        assert distributions_for_scope(
            build_snapshot(below, 2025, ["bl1"]), "world_cup"
        ).get("Attacker") is None

        exactly = [self._entry(i, 270, 0.5 + i * 0.01) for i in range(40)]
        dist = distributions_for_scope(
            build_snapshot(exactly, 2025, ["bl1"]), "world_cup"
        )["Attacker"]
        assert dist["player_count"] == 40

    def test_450er_huerde_wuerde_turnierspieler_ausschliessen(self):
        """
        Beleg fuer die Notwendigkeit der Sonderhuerde: mit der Ligahuerde
        gaebe es fuer ein Vorrunden-Aus gar keinen Referenzpool.
        """
        entries = [self._entry(i, 300, 0.5) for i in range(40)]
        snapshot = build_snapshot(entries, 2025, ["bl1"])
        assert distributions_for_scope(snapshot, "world_cup")["Attacker"]["player_count"] == 40

        strict = build_snapshot(entries, 2025, ["bl1"],
                                scopes=("club_all", "world_cup"))
        # Sonderhuerde gilt auch hier - 300 >= 270.
        assert distributions_for_scope(strict, "world_cup")["Attacker"]

    def test_snapshot_dokumentiert_huerde_je_scope(self):
        snapshot = build_snapshot([], 2025, ["bl1"])
        by_scope = snapshot["min_minutes_by_scope"]
        assert by_scope["world_cup"] == 270
        assert by_scope["euro"] == 270
        assert by_scope["league"] == 450
        assert by_scope["cl"] == 450
        # Top-Level bleibt der Standard (Rueckwaertskompatibilitaet).
        assert snapshot["min_minutes"] == 450

    def test_describe_pool_meldet_scope_huerde(self):
        entries = [self._entry(i, 400, 0.5 + i * 0.01) for i in range(40)]
        snapshot = build_snapshot(entries, 2025, ["bl1"])

        assert describe_pool(snapshot, "Attacker", scope="world_cup")["min_minutes"] == 270
        assert describe_pool(snapshot, "Attacker", scope="league")["min_minutes"] == 450

    def test_alter_snapshot_ohne_aufschluesselung(self):
        """Rueckwaertskompatibel: faellt auf den Top-Level-Wert zurueck."""
        legacy = {
            "season": 2025, "leagues": ["bl1"], "min_minutes": 450,
            "distributions": {"Attacker": {"player_count": 50, "metrics": {}}},
        }
        assert describe_pool(legacy, "Attacker")["min_minutes"] == 450


# ===========================================================================
# H) Scatter
# ===========================================================================

class TestScatter:
    def _entry(self, player_id, wc_minutes, wc_goals):
        metrics_wc = {} if wc_minutes is None else {
            "goals_per90": wc_goals, "assists_per90": 0.2,
        }
        return {
            "player_id": player_id, "name": f"Spieler {player_id}",
            "position": "Attacker", "league_code": "bl1", "age": 26,
            "team_name": "Test FC",
            "minutes_by_scope": {"club_all": 2000, "league": 2000, "cl": None,
                                 "euro": None, "world_cup": wc_minutes,
                                 "national": None, "all": 2000},
            "metrics_by_scope": {
                "club_all": {"goals_per90": 0.3, "assists_per90": 0.1},
                "league": {"goals_per90": 0.3, "assists_per90": 0.1},
                "cl": {}, "euro": {}, "world_cup": metrics_wc,
                "national": {}, "all": {"goals_per90": 0.3, "assists_per90": 0.1},
            },
        }

    def _patch(self, monkeypatch, entries):
        from src.data import player_pool
        monkeypatch.setattr(player_pool, "load_all_players",
                            lambda season, codes: (entries, list(codes)))

    def test_scope_world_cup_wird_akzeptiert(self, monkeypatch):
        from src.data.player_pool import load_scatter_points
        self._patch(monkeypatch, [self._entry(1, 400, 0.6)])

        points, _ = load_scatter_points(
            2025, ["bl1"], None, 270, "goals_per90", "assists_per90",
            scope="world_cup")
        assert len(points) == 1
        assert points[0]["x"] == 0.6
        assert points[0]["minutes"] == 400

    def test_scope_euro_wird_akzeptiert(self, monkeypatch):
        from src.data.player_pool import load_scatter_points
        self._patch(monkeypatch, [self._entry(1, 400, 0.6)])

        points, _ = load_scatter_points(
            2025, ["bl1"], None, 270, "goals_per90", "assists_per90", scope="euro")
        # Keine euro-Daten im Eintrag -> keine Punkte, aber kein Fehler.
        assert points == []

    def test_spieler_ohne_turnierdaten_erscheinen_nicht(self, monkeypatch):
        from src.data.player_pool import load_scatter_points
        self._patch(monkeypatch, [
            self._entry(1, 400, 0.6),
            self._entry(2, None, None),
            self._entry(3, None, None),
        ])

        points, _ = load_scatter_points(
            2025, ["bl1"], None, 270, "goals_per90", "assists_per90",
            scope="world_cup")
        assert len(points) == 1
        assert points[0]["id"] == 1

    def test_keine_kuenstlichen_nullpunkte(self, monkeypatch):
        from src.data.player_pool import load_scatter_points
        self._patch(monkeypatch, [self._entry(i, None, None) for i in range(5)])

        points, _ = load_scatter_points(
            2025, ["bl1"], None, 270, "goals_per90", "assists_per90",
            scope="world_cup")
        assert points == []

    def test_ligafilter_und_scope_bleiben_getrennt(self, monkeypatch):
        from src.data.player_pool import load_scatter_points
        self._patch(monkeypatch, [self._entry(1, 400, 0.6)])

        points, used = load_scatter_points(
            2025, ["bl1"], None, 270, "goals_per90", "assists_per90",
            scope="world_cup")
        assert used == ["bl1"]
        assert points[0]["league"] == "bl1"    # Herkunftsliga
        assert points[0]["x"] == 0.6           # aber WM-Wert, nicht 0.3

    def test_benutzerhuerde_wird_beachtet(self, monkeypatch):
        from src.data.player_pool import load_scatter_points
        self._patch(monkeypatch, [self._entry(1, 400, 0.6)])

        assert load_scatter_points(2025, ["bl1"], None, 500, "goals_per90",
                                   "assists_per90", scope="world_cup")[0] == []
        assert len(load_scatter_points(2025, ["bl1"], None, 100, "goals_per90",
                                       "assists_per90", scope="world_cup")[0]) == 1


# ===========================================================================
# I) Offline-Backfill mit Nationalbloecken
# ===========================================================================

class TestBackfill:
    def test_backfill_merged_nationalbloecke(self, monkeypatch, tmp_path):
        """
        Der Kern des Offline-Pfads: WM-Bloecke liegen NICHT in der
        Vereinsantwort, sondern in der National-Datei. Ohne Merge bliebe
        world_cup dauerhaft leer.
        """
        import refresh_players as rp
        from src.data import player_pool

        pool = {
            "league": "bl1", "season": 2025, "pages_done": [1],
            "players": [{
                "player_id": 44, "name": "Rodri", "position": "Midfielder",
                "league_code": "bl1", "age": 29, "team_name": "Man City",
                "minutes_by_scope": {"club_all": 2000, "league": 2000,
                                     "national": None, "all": 2000},
                "metrics_by_scope": {"club_all": {}, "league": {},
                                     "national": {}, "all": {}},
            }],
        }
        written = {}

        monkeypatch.setattr(rp, "is_pool_complete", lambda code, season: code == "bl1")
        monkeypatch.setattr(player_pool, "read_pool", lambda code, season: pool)
        monkeypatch.setattr(player_pool, "write_pool",
                            lambda p: written.update({"pool": p}))
        monkeypatch.setattr(rp, "build_and_save_snapshot", lambda *a, **k: None)

        # Vereinsantwort im Cache: nur Liga.
        from src.utils import disk_cache
        monkeypatch.setattr(disk_cache, "read_entry", lambda key: {
            "payload": [_raw(44, "Rodri", [
                _block(ID_BUNDESLIGA, "Bundesliga", 2000, 8, position="Midfielder"),
            ])],
        })
        monkeypatch.setattr(rp, "disk_read_entry", disk_cache.read_entry, raising=False)

        # WM-Bloecke separat, wie sie national_import ablegt.
        import src.data.national_import as national_import
        monkeypatch.setattr(national_import, "get_national_blocks",
                            lambda pid, season: [
                                _block(ID_WORLD_CUP, "World Cup", 540, 2,
                                       position="Midfielder")
                            ])

        rp.backfill_missing_scopes(2025, 450, league_codes=["bl1"])

        entry = written["pool"]["players"][0]
        assert entry["minutes_by_scope"]["world_cup"] == 540
        assert entry["metrics_by_scope"]["world_cup"]
        # euro bleibt leer - kein Fake-Scope.
        assert entry["minutes_by_scope"]["euro"] is None
        assert entry["metrics_by_scope"]["euro"] == {}

    def test_backfill_macht_keine_requests(self, monkeypatch):
        """Harter Nachweis: jeder Netzzugriff laesst den Test scheitern."""
        import socket
        import refresh_players as rp
        from src.data import player_pool

        def _blocked(*a, **k):
            raise AssertionError("Backfill darf keine Requests ausloesen")

        monkeypatch.setattr(socket.socket, "connect", _blocked)
        monkeypatch.setattr(rp, "is_pool_complete", lambda code, season: code == "bl1")
        monkeypatch.setattr(player_pool, "read_pool", lambda code, season: {
            "league": "bl1", "season": 2025, "pages_done": [], "players": [],
        })
        monkeypatch.setattr(player_pool, "write_pool", lambda p: None)
        monkeypatch.setattr(rp, "build_and_save_snapshot", lambda *a, **k: None)

        report = rp.backfill_missing_scopes(2025, 450, league_codes=["bl1"])
        assert report is not None

    def test_force_scopes_erzwingt_neuberechnung(self, monkeypatch):
        """
        Nach einem frischen Turnierimport stehen euro/world_cup bereits
        (leer) im Eintrag und muessen trotzdem neu aggregiert werden.
        """
        import refresh_players as rp
        from src.data import player_pool

        pool = {
            "league": "bl1", "season": 2025, "pages_done": [1],
            "players": [{
                "player_id": 44, "name": "Rodri", "position": "Midfielder",
                "league_code": "bl1", "age": 29, "team_name": "Man City",
                "minutes_by_scope": {s: None for s in COMPETITION_SCOPES},
                "metrics_by_scope": {s: {} for s in COMPETITION_SCOPES},
            }],
        }
        written = {}

        monkeypatch.setattr(rp, "is_pool_complete", lambda code, season: code == "bl1")
        monkeypatch.setattr(player_pool, "read_pool", lambda code, season: pool)
        monkeypatch.setattr(player_pool, "write_pool",
                            lambda p: written.update({"pool": p}))
        monkeypatch.setattr(rp, "build_and_save_snapshot", lambda *a, **k: None)

        from src.utils import disk_cache
        monkeypatch.setattr(disk_cache, "read_entry", lambda key: {
            "payload": [_raw(44, "Rodri", [])],
        })
        import src.data.national_import as national_import
        monkeypatch.setattr(national_import, "get_national_blocks",
                            lambda pid, season: [
                                _block(ID_WORLD_CUP, "World Cup", 540, 2,
                                       position="Midfielder")
                            ])

        # Ohne force: nichts fehlt, also keine Aenderung.
        rp.backfill_missing_scopes(2025, 450, league_codes=["bl1"])
        assert written["pool"]["players"][0]["minutes_by_scope"]["world_cup"] is None

        # Mit force: WM wird neu aggregiert.
        rp.backfill_missing_scopes(2025, 450, league_codes=["bl1"],
                                   force_scopes=("world_cup",))
        assert written["pool"]["players"][0]["minutes_by_scope"]["world_cup"] == 540


# ===========================================================================
# J) Isolierter Einzelwettbewerbs-Import
# ===========================================================================

class TestIsolierterImport:
    def test_laedt_genau_einen_wettbewerb(self, monkeypatch):
        import refresh_players as rp
        from src.data import player_pool
        import src.data.national_import as national_import

        captured = {}

        def fake_import(footsim_season, ids, progress=None, targets=None,
                        merge_existing=False):
            captured["footsim_season"] = footsim_season
            captured["targets"] = targets
            captured["merge_existing"] = merge_existing
            return {}

        monkeypatch.setattr(national_import, "import_national_for_season", fake_import)
        monkeypatch.setattr(national_import, "clear_runtime_cache", lambda: None)
        monkeypatch.setattr(rp, "is_pool_complete", lambda code, season: True)
        monkeypatch.setattr(player_pool, "read_pool", lambda code, season: {
            "league": code, "season": season, "pages_done": [],
            "players": [{"player_id": 1}],
        })
        monkeypatch.setattr(rp, "backfill_missing_scopes", lambda *a, **k: {})

        rp.import_single_national_competition(4, 2024, 450)

        assert captured["targets"] == [
            {"league_id": 4, "api_season": 2024, "name": "Euro Championship"}
        ]
        assert len(captured["targets"]) == 1
        assert captured["footsim_season"] == 2023      # aus dem Mapping
        assert captured["merge_existing"] is True      # Teilimport schuetzt Bestand

    def test_keine_anderen_national_wettbewerbe(self, monkeypatch):
        """
        Der Kern der Isolation: --national fuer Saison 2023 wuerde neun
        Wettbewerbe laden, der Einzelimport genau einen.
        """
        alle = national_targets_for_footsim_season(2023)
        assert len(alle) > 1
        ids = {t["league_id"] for t in alle}
        assert {6, 9, 10, 960}.issubset(ids)   # AFCON, Copa, Friendlies, Quali

        import refresh_players as rp
        from src.data import player_pool
        import src.data.national_import as national_import

        captured = {}
        monkeypatch.setattr(national_import, "import_national_for_season",
                            lambda fs, ids_, progress=None, targets=None,
                            merge_existing=False: captured.update(targets=targets) or {})
        monkeypatch.setattr(national_import, "clear_runtime_cache", lambda: None)
        monkeypatch.setattr(rp, "is_pool_complete", lambda code, season: True)
        monkeypatch.setattr(player_pool, "read_pool", lambda code, season: {
            "league": code, "season": season, "pages_done": [], "players": [],
        })
        monkeypatch.setattr(rp, "backfill_missing_scopes", lambda *a, **k: {})

        rp.import_single_national_competition(4, 2024, 450)

        geladene_ids = {t["league_id"] for t in captured["targets"]}
        assert geladene_ids == {4}
        assert 6 not in geladene_ids and 10 not in geladene_ids

    def test_dry_run_ohne_import(self, monkeypatch):
        import refresh_players as rp
        from src.data import player_pool
        import src.data.national_import as national_import

        def fail(*a, **k):
            raise AssertionError("dry-run darf nicht importieren")

        monkeypatch.setattr(national_import, "import_national_for_season", fail)
        monkeypatch.setattr(rp, "is_pool_complete", lambda code, season: True)
        monkeypatch.setattr(player_pool, "read_pool", lambda code, season: {
            "league": code, "season": season, "pages_done": [], "players": [],
        })

        result = rp.import_single_national_competition(4, 2024, 450, dry_run=True)
        assert result["dry_run"] is True
        assert result["footsim_season"] == 2023

    def test_unbekannter_wettbewerb_wird_abgelehnt(self):
        import refresh_players as rp
        assert rp.import_single_national_competition(99999, 2024, 450,
                                                     dry_run=True) is None

    def test_unverifizierte_season_wird_abgelehnt(self):
        import refresh_players as rp
        # EM hat nur 2020 und 2024 verifiziert.
        assert rp.import_single_national_competition(4, 2021, 450,
                                                     dry_run=True) is None

    def test_unvollstaendiger_pool_wird_abgelehnt(self, monkeypatch):
        import refresh_players as rp
        monkeypatch.setattr(rp, "is_pool_complete", lambda code, season: False)
        assert rp.import_single_national_competition(4, 2024, 450,
                                                     dry_run=True) is None

    def test_bestehendes_national_bleibt_vollstaendig(self):
        """--national laedt weiterhin ALLE Zielwettbewerbe einer Saison."""
        targets = national_targets_for_footsim_season(2025)
        ids = {t["league_id"] for t in targets}
        assert 1 in ids            # WM 2026
        assert len(targets) > 1    # plus die uebrigen

    def test_teilimport_erhaelt_bestehende_bloecke(self, monkeypatch, tmp_path):
        """
        Ein Einzelimport darf eine bereits gefuellte Saisondatei nicht
        ueberschreiben - sonst ginge ein zuvor importiertes Turnier verloren.
        """
        import json
        import src.data.national_import as ni

        monkeypatch.setattr(ni, "NATIONAL_DIR", str(tmp_path))
        monkeypatch.setattr(ni, "national_path",
                            lambda s: str(tmp_path / f"national_{s}.json"))

        # Bestand: Spieler 7 hat bereits einen Friendlies-Block.
        with open(tmp_path / "national_2023.json", "w", encoding="utf-8") as f:
            json.dump({
                "footsim_season": 2023,
                "targets": [{"league_id": 10, "api_season": 2023, "name": "Friendlies"}],
                "player_count": 1,
                "blocks_by_player": {"7": [_block(ID_FRIENDLIES, "Friendlies", 180, 1)]},
            }, f)

        monkeypatch.setattr(ni, "_iter_competition_players",
                            lambda lid, api_s, progress=None: iter([
                                (7, _block(ID_EURO, "Euro Championship", 400, 3))
                            ]))

        ni.import_national_for_season(
            2023, {7},
            targets=[{"league_id": 4, "api_season": 2024, "name": "Euro Championship"}],
            merge_existing=True,
        )

        with open(tmp_path / "national_2023.json", encoding="utf-8") as f:
            saved = json.load(f)

        league_ids = {(b.get("league") or {}).get("id")
                      for b in saved["blocks_by_player"]["7"]}
        assert league_ids == {ID_FRIENDLIES, ID_EURO}   # beides erhalten
        assert len(saved["targets"]) == 2


# ===========================================================================
# K) Regression der bestehenden Scopes
# ===========================================================================

class TestRegression:
    def _all(self):
        return _raw(1, "Allrounder", [
            _block(ID_BUNDESLIGA, "Bundesliga", 2000, 10),
            _block(ID_CHAMPIONS_LEAGUE, "UEFA Champions League", 600, 4),
            _block(ID_WORLD_CUP, "World Cup", 400, 3),
            _block(ID_EURO, "Euro Championship", 300, 2),
        ])

    @pytest.mark.parametrize("scope,minutes", [
        (SCOPE_CLUB_ALL, 2600),          # Liga + CL
        (SCOPE_LEAGUE, 2000),
        (SCOPE_CL, 600),
        (SCOPE_NATIONAL, 700),           # WM + EM
        (SCOPE_ALL, 3300),
    ])
    def test_bestehende_scopes_unveraendert(self, scope, minutes):
        profile = build_player_profile(self._all(), 2025, scope=scope)
        assert profile["minutes"] == minutes
        assert profile["data_available"] is True

    def test_default_scope_unveraendert(self):
        from src.data.player_compare_loader import DEFAULT_SCOPE
        assert DEFAULT_SCOPE == SCOPE_CLUB_ALL
        assert normalize_scope(None) == SCOPE_CLUB_ALL
        assert normalize_scope("quatsch") == SCOPE_CLUB_ALL

    def test_alle_scopes_registriert(self):
        assert COMPETITION_SCOPES == (
            "club_all", "league", "cl", "euro", "world_cup", "national", "all",
        )
        for scope in COMPETITION_SCOPES:
            assert SCOPE_LABELS[scope]
            assert SCOPE_HINTS[scope]

    def test_normalize_akzeptiert_neue_scopes(self):
        assert normalize_scope("euro") == SCOPE_EURO
        assert normalize_scope(" WORLD_CUP ") == SCOPE_WORLD_CUP

    def test_labels(self):
        assert SCOPE_LABELS[SCOPE_EURO] == "Europameisterschaft"
        assert SCOPE_LABELS[SCOPE_WORLD_CUP] == "Weltmeisterschaft"


# ===========================================================================
# Verdrahtung Oberflaeche
# ===========================================================================

class TestVerdrahtung:
    def test_buttons_in_beiden_navigationen(self):
        html = _read("templates", "index.html")
        # Seit Block LIVE D1 eine dritte Stelle: die Wettbewerbsauswahl im
        # Spielerprofil (pd-scope-nav) nutzt dieselben sieben Scope-Buttons.
        assert html.count('data-scope="euro"') == 3
        assert html.count('data-scope="world_cup"') == 3

        # Die sieben geteilten Scopes stehen unveraendert in allen drei
        # Navigationen (Radar, Scatter, Spielerprofil).
        shared_scopes = ("club_all", "league", "cl", "euro",
                         "world_cup", "national", "all")
        for scope in shared_scopes:
            assert html.count(f'data-scope="{scope}"') == 3, scope

        # Block F1 ergaenzt GENAU EINEN weiteren Knopf: Big Games gibt es
        # nur im Radar (eigene Datenbasis mit eigenem Zeitraum), bewusst
        # nicht im Scatter und nicht im Spielerprofil.
        assert html.count('data-scope="big_games"') == 1

        # 7 geteilte Scopes x 3 Navigationen + 1 Big Games.
        assert html.count("data-scope=") == len(shared_scopes) * 3 + 1

    def test_buttons_nutzen_bestehendes_muster(self):
        html = _read("templates", "index.html")
        for scope in ("euro", "world_cup"):
            assert (f'class="pc-scope-btn"\n                                '
                    f'role="radio" aria-checked="false" data-scope="{scope}"') in html

    def test_frontend_kennt_hinweise(self):
        script = _read("static", "script.js")
        start = script.find("scopeHint: {")
        block = script[start:start + 1200]
        assert "euro:" in block
        assert "world_cup:" in block

    def test_frontend_deaktiviert_nicht_stattgefundene_turniere(self):
        script = _read("static", "script.js")
        assert "function pcApplyScopeAvailability" in script
        assert "function pcRefreshScopeAvailability" in script
        assert "tournaments_available" in script
        assert "scopeUnavailable" in script

    def test_deaktivierte_buttons_sind_nicht_klickbar(self):
        script = _read("static", "script.js")
        assert script.count("if (!button || button.disabled) return;") == 2

    def test_css_nutzt_bestehende_disabled_konvention(self):
        css = _read("static", "style.css")
        assert ".pc-scope-btn:disabled" in css
        # Gleiche Werte wie bei den vorhandenen deaktivierten Schaltflaechen.
        start = css.find(".pc-scope-btn:disabled")
        block = css[start:start + 200]
        assert "opacity: 0.35" in block
        assert "cursor: not-allowed" in block

    def test_cl_scope_bleibt_erhalten(self):
        """Der zuvor gebaute CL-Scope darf nicht regressieren."""
        script = _read("static", "script.js")
        html = _read("templates", "index.html")
        assert html.count('data-scope="cl"') == 3
        assert "function pcBuildScopeDataNote" in script
        assert entry_matches_scope(
            _block(ID_CHAMPIONS_LEAGUE, "UEFA Champions League", 600, 4),
            SCOPE_CL) is True
