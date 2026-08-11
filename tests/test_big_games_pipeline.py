"""
Tests fuer die Big-Games-Pipeline und die Routen (Block F1).

Abgedeckt:
  A) Spielklassifizierung (Zulassung, Gegner, Phase, Saisonbezug)
  B) Vereinswechsel und Trennung von Vereins-/Nationalmannschaftsdaten
  C) Request-Sparsamkeit: Zulassung entscheidet VOR dem Statistikabruf
  D) Routen: Parametervalidierung, Vertrauensgrenze, Fehlerfaelle
  E) Trennung von Direktsuche und Top-5-Population
  F) Keine Regression an bestehenden Endpunkten

Alle Tests arbeiten mit synthetischen Antworten und einem isolierten
Cache-Verzeichnis - kein echter Netzwerkzugriff.
"""

import json

import pytest

from src.data import big_games_loader as bgl
from src.data import uefa_coefficients as uc
from src.features import big_games as bg


HOME_TEAM = 33          # Manchester United
ELITE_OPPONENT = 40     # Liverpool - in den Testsnapshots Rang 2
WEAK_OPPONENT = 999999  # nirgends im Ranking


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path, monkeypatch):
    """Eigener Plattencache UND eigene Snapshots je Test."""
    from src.utils import disk_cache
    monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path / "cache"))

    coeff_dir = tmp_path / "coeff"
    coeff_dir.mkdir()
    (coeff_dir / "uefa_coefficients_2021_22.json").write_text(json.dumps({
        "season": "2021/22",
        "status": "complete",
        "clubs": [
            {"rank": 1,  "total_coefficient": 138.0, "apisports_team_id": 157},
            {"rank": 2,  "total_coefficient": 134.0, "apisports_team_id": ELITE_OPPONENT},
            {"rank": 30, "total_coefficient": 53.0,  "apisports_team_id": 168},
            {"rank": 31, "total_coefficient": 53.0,  "apisports_team_id": 487},
            {"rank": 40, "total_coefficient": 41.0,  "apisports_team_id": 553},
        ],
    }), encoding="utf-8")

    monkeypatch.setattr(uc, "COEFFICIENT_DIR", str(coeff_dir))
    uc.clear_cache()
    yield
    uc.clear_cache()


def make_fixture(fixture_id=1, opponent_id=ELITE_OPPONENT, league_id=39,
                 round_name="Regular Season - 10", status="FT",
                 own_id=HOME_TEAM, date="2021-10-24T15:00:00+00:00"):
    return {
        "fixture": {"id": fixture_id, "date": date, "status": {"short": status}},
        "league": {"id": league_id, "name": "Testwettbewerb", "round": round_name},
        "teams": {
            "home": {"id": own_id, "name": "Eigenes Team"},
            "away": {"id": opponent_id, "name": "Gegner"},
        },
    }


def classify(fixture, season=2021):
    snapshot = uc.load_snapshot(season)
    return bgl.classify_fixture(fixture, HOME_TEAM, season, snapshot)


# ===========================================================================
# A) Klassifizierung
# ===========================================================================

class TestClassification:
    def test_elitegegner_im_ligaspiel_ist_big_game(self):
        result = classify(make_fixture(opponent_id=ELITE_OPPONENT))
        assert result["is_big_game"] is True
        assert result["opponent_qualified"] is True
        assert result["opponent_rank"] == 2

    def test_schwacher_gegner_im_ligaspiel_ist_kein_big_game(self):
        result = classify(make_fixture(opponent_id=WEAK_OPPONENT))
        assert result["is_big_game"] is False
        assert result["opponent_rank"] is None

    def test_rang_30_qualifiziert_rang_31_nicht(self):
        r30 = classify(make_fixture(opponent_id=168))
        r31 = classify(make_fixture(opponent_id=487))
        assert r30["is_big_game"] is True
        assert r31["is_big_game"] is False

    def test_gleiche_koeffizienten_gleiche_staerke_trotz_rangunterschied(self):
        """
        Rang 30 und 31 haben in den Testdaten - wie in der Realitaet -
        denselben Koeffizienten. Sie muessen deshalb dieselbe
        Gegnerstaerke bekommen, obwohl nur einer zulassungsfaehig ist.
        """
        r30 = classify(make_fixture(opponent_id=168))
        r31 = classify(make_fixture(opponent_id=487))
        assert r30["strength"] == r31["strength"]

    def test_ko_spiel_gegen_schwachen_gegner_qualifiziert_ueber_die_bedeutung(self):
        result = classify(make_fixture(
            opponent_id=WEAK_OPPONENT, league_id=2, round_name="Final"))
        assert result["is_big_game"] is True
        assert result["opponent_qualified"] is False
        assert result["importance_qualified"] is True

    def test_nationaler_pokal_achtelfinale_qualifiziert_nicht_allein(self):
        result = classify(make_fixture(
            opponent_id=WEAK_OPPONENT, league_id=45, round_name="Round of 16"))
        assert result["is_big_game"] is False

    def test_nationales_pokalfinale_qualifiziert(self):
        result = classify(make_fixture(
            opponent_id=WEAK_OPPONENT, league_id=45, round_name="Final"))
        assert result["is_big_game"] is True

    def test_nicht_gespieltes_spiel_wird_verworfen(self):
        for status in ("NS", "PST", "CANC", "TBD"):
            assert classify(make_fixture(status=status)) is None

    def test_auswaertsspiel_erkennt_den_richtigen_gegner(self):
        raw = make_fixture()
        raw["teams"] = {
            "home": {"id": ELITE_OPPONENT, "name": "Gegner"},
            "away": {"id": HOME_TEAM, "name": "Eigenes Team"},
        }
        result = classify(raw)
        assert result["is_home"] is False
        assert result["opponent_id"] == ELITE_OPPONENT

    def test_fremdes_spiel_wird_verworfen(self):
        raw = make_fixture()
        raw["teams"] = {"home": {"id": 111}, "away": {"id": 222}}
        assert classify(raw) is None

    def test_fehlende_saison_liefert_keine_gegnerstaerke(self):
        snapshot = uc.load_snapshot(2020)
        result = bgl.classify_fixture(make_fixture(), HOME_TEAM, 2020, snapshot)
        assert result["opponent_rank"] is None
        assert result["strength"] == bg.OPPONENT_STRENGTH_UNKNOWN


# ===========================================================================
# B) Vereinswechsel und Nationalmannschaft
# ===========================================================================

class TestEngagements:
    def _patch_raw(self, monkeypatch, statistics):
        monkeypatch.setattr(bgl, "get_player_season_raw",
                            lambda pid, season: {"player": {"id": pid, "name": "Test"},
                                                 "statistics": statistics})

    def test_vereinswechsel_ergibt_zwei_engagements(self, monkeypatch):
        """
        Der Spieler behaelt seine ID, der Verein kommt je Wettbewerb aus
        den Daten - nie wird ein aktueller Verein rueckprojiziert.
        """
        self._patch_raw(monkeypatch, [
            {"team": {"id": 496, "name": "Juventus"}, "league": {"id": 135, "name": "Serie A"}},
            {"team": {"id": 33, "name": "Manchester United"},
             "league": {"id": 39, "name": "Premier League"}},
        ])
        engagements, _ = bgl.player_club_engagements(874, 2021)
        assert {e["team_id"] for e in engagements} == {496, 33}

    def test_nationalmannschaft_wird_verworfen(self, monkeypatch):
        """F1 ist ausdruecklich Vereinsfussball."""
        self._patch_raw(monkeypatch, [
            {"team": {"id": 33, "name": "Manchester United"},
             "league": {"id": 39, "name": "Premier League"}},
            {"team": {"id": 27, "name": "Portugal"},
             "league": {"id": 1, "name": "World Cup"}},
            {"team": {"id": 27, "name": "Portugal"},
             "league": {"id": 4, "name": "Euro Championship"}},
        ])
        engagements, _ = bgl.player_club_engagements(874, 2021)
        assert [e["team_id"] for e in engagements] == [33]

    def test_doppelte_engagements_werden_entfernt(self, monkeypatch):
        self._patch_raw(monkeypatch, [
            {"team": {"id": 33}, "league": {"id": 39, "name": "Premier League"}},
            {"team": {"id": 33}, "league": {"id": 39, "name": "Premier League"}},
        ])
        engagements, _ = bgl.player_club_engagements(874, 2021)
        assert len(engagements) == 1

    def test_ohne_daten_leere_liste(self, monkeypatch):
        monkeypatch.setattr(bgl, "get_player_season_raw", lambda pid, season: None)
        engagements, player = bgl.player_club_engagements(874, 2021)
        assert engagements == []
        assert player is None


# ===========================================================================
# C) Request-Sparsamkeit
# ===========================================================================

class TestRequestBudget:
    def test_statistiken_nur_fuer_qualifizierte_spiele(self, monkeypatch):
        """
        Entscheidend fuer das Request-Budget: die Zulassung faellt aus der
        Spielliste, BEVOR je Spiel Einzelspielerwerte geholt werden.
        """
        monkeypatch.setattr(bgl, "get_player_season_raw",
                            lambda pid, season: {"player": {"id": pid, "name": "Test"},
                                                 "statistics": [{"team": {"id": HOME_TEAM},
                                                                 "league": {"id": 39, "name": "Premier League"}}]})
        monkeypatch.setattr(bgl.apisports_api, "get_team_season_fixtures",
                            lambda t, l, s: [
                                make_fixture(fixture_id=1, opponent_id=ELITE_OPPONENT),
                                make_fixture(fixture_id=2, opponent_id=WEAK_OPPONENT),
                                make_fixture(fixture_id=3, opponent_id=WEAK_OPPONENT),
                            ])

        requested = []

        def fake_players(fixture_id):
            requested.append(fixture_id)
            return [{"team": {"id": HOME_TEAM},
                     "players": [{"player": {"id": 874},
                                  "statistics": [{"games": {"minutes": 90, "rating": "7.5",
                                                            "position": "F"},
                                                  "goals": {"total": 1}}]}]}]

        monkeypatch.setattr(bgl.apisports_api, "get_fixture_players", fake_players)

        result = bgl.get_player_big_games(874, 2021, 2021)

        # Nur das eine qualifizierte Spiel kostet einen Request.
        assert requested == [1]
        assert len(result["matches"]) == 1

    def test_zweiter_aufruf_kostet_keine_requests(self, monkeypatch):
        monkeypatch.setattr(bgl, "get_player_season_raw",
                            lambda pid, season: {"player": {"id": pid},
                                                 "statistics": [{"team": {"id": HOME_TEAM},
                                                                 "league": {"id": 39, "name": "Premier League"}}]})
        calls = []
        monkeypatch.setattr(bgl.apisports_api, "get_team_season_fixtures",
                            lambda t, l, s: calls.append("fixtures") or [make_fixture()])
        monkeypatch.setattr(bgl.apisports_api, "get_fixture_players",
                            lambda f: [{"team": {"id": HOME_TEAM},
                                        "players": [{"player": {"id": 874},
                                                     "statistics": [{"games": {"minutes": 90}}]}]}])

        bgl.get_player_big_games(874, 2021, 2021)
        bgl.get_player_big_games(874, 2021, 2021)
        assert calls.count("fixtures") == 1

    def test_ausfall_eines_wettbewerbs_reisst_nicht_alles_mit(self, monkeypatch):
        from src.api.apisports_api import ApisportsUnavailable

        monkeypatch.setattr(bgl, "get_player_season_raw",
                            lambda pid, season: {"player": {"id": pid}, "statistics": [
                                {"team": {"id": HOME_TEAM}, "league": {"id": 39, "name": "Premier League"}},
                                {"team": {"id": HOME_TEAM}, "league": {"id": 2, "name": "UEFA Champions League"}},
                            ]})

        def fixtures(team_id, league_id, season):
            if league_id == 39:
                raise ApisportsUnavailable("weg")
            return [make_fixture(fixture_id=7, league_id=2, round_name="Final",
                                 opponent_id=WEAK_OPPONENT)]

        monkeypatch.setattr(bgl.apisports_api, "get_team_season_fixtures", fixtures)
        monkeypatch.setattr(bgl.apisports_api, "get_fixture_players",
                            lambda f: [{"team": {"id": HOME_TEAM},
                                        "players": [{"player": {"id": 874},
                                                     "statistics": [{"games": {"minutes": 90, "rating": "7.0"}}]}]}])

        result = bgl.get_player_big_games(874, 2021, 2021)
        assert len(result["matches"]) == 1

    def test_spieler_nicht_im_kader_zaehlt_nicht(self, monkeypatch):
        monkeypatch.setattr(bgl, "get_player_season_raw",
                            lambda pid, season: {"player": {"id": pid},
                                                 "statistics": [{"team": {"id": HOME_TEAM},
                                                                 "league": {"id": 39, "name": "Premier League"}}]})
        monkeypatch.setattr(bgl.apisports_api, "get_team_season_fixtures",
                            lambda t, l, s: [make_fixture()])
        monkeypatch.setattr(bgl.apisports_api, "get_fixture_players",
                            lambda f: [{"team": {"id": HOME_TEAM},
                                        "players": [{"player": {"id": 111111},
                                                     "statistics": [{"games": {"minutes": 90}}]}]}])

        result = bgl.get_player_big_games(874, 2021, 2021)
        assert result["matches"] == []


# ===========================================================================
# D) Mehrjahresbereich
# ===========================================================================

class TestSeasonRange:
    def test_fehlende_saison_wird_ehrlich_gemeldet(self, monkeypatch):
        """
        2020/21 hat keinen Snapshot. Die Saison darf weder still
        weggelassen noch mit einer fremden Rangliste bewertet werden.
        """
        monkeypatch.setattr(bgl, "get_player_season_raw", lambda pid, season: None)

        result = bgl.get_player_big_games(874, 2020, 2021)
        by_season = {s["season"]: s for s in result["seasons"]}

        assert by_season[2020]["available"] is False
        assert by_season[2020]["reason"] == "no_coefficient_snapshot"
        assert by_season[2021]["available"] is True
        assert result["has_unavailable_seasons"] is True

    def test_jede_saison_nutzt_ihren_eigenen_snapshot(self, monkeypatch):
        """
        Es darf niemals eine Saison-Rangliste auf einen ganzen Zeitraum
        angewendet werden. Geprueft wird, dass je Saison genau mit deren
        Saisonzahl nachgeschlagen wird.
        """
        looked_up = []
        original = uc.lookup_team

        def spy(season, team_id):
            looked_up.append(season)
            return original(season, team_id)

        monkeypatch.setattr(uc, "lookup_team", spy)
        monkeypatch.setattr(bgl, "get_player_season_raw",
                            lambda pid, season: {"player": {"id": pid},
                                                 "statistics": [{"team": {"id": HOME_TEAM},
                                                                 "league": {"id": 39, "name": "Premier League"}}]})
        monkeypatch.setattr(bgl.apisports_api, "get_team_season_fixtures",
                            lambda t, l, s: [make_fixture()])
        monkeypatch.setattr(bgl.apisports_api, "get_fixture_players", lambda f: [])

        # Nur 2021 hat einen Snapshot; 2022 faellt vorher sauber aus.
        bgl.get_player_big_games(874, 2021, 2021)
        assert looked_up and set(looked_up) == {2021}


# ===========================================================================
# E) Routen
# ===========================================================================

class TestRoutes:
    @pytest.fixture
    def client(self):
        import app as app_module
        app_module.app.config["TESTING"] = True
        return app_module.app.test_client()

    def test_saisonauskunft(self, client):
        body = client.get("/api/big-games-seasons").get_json()
        assert body["available"] is True
        assert body["earliest_season"] == 2021
        assert body["max_span"] >= 1

    def test_fehlender_spieler(self, client):
        assert client.get("/api/big-games-compare").status_code == 400

    def test_ungueltige_player_id(self, client):
        assert client.get(
            "/api/big-games-compare?a=abc&season_from=2021&season_to=2021"
        ).status_code == 400
        assert client.get(
            "/api/big-games-compare?a=-3&season_from=2021&season_to=2021"
        ).status_code == 400

    def test_saison_vor_der_untergrenze_wird_abgelehnt(self, client):
        response = client.get(
            "/api/big-games-compare?a=874&season_from=2019&season_to=2021")
        assert response.status_code == 400
        assert "2021/22" in response.get_json()["error"]

    def test_zu_langer_zeitraum_wird_abgelehnt(self, client, monkeypatch):
        import app as app_module
        monkeypatch.setattr(app_module, "BIG_GAMES_MAX_SEASON_SPAN", 2)
        response = client.get(
            "/api/big-games-compare?a=874&season_from=2021&season_to=2025")
        assert response.status_code == 400

    def test_suche_verlangt_mindestlaenge(self, client):
        assert client.get("/api/big-games-search?q=a&season=2021").status_code == 400

    def test_suche_prueft_die_saison(self, client):
        assert client.get(
            "/api/big-games-search?q=Ronaldo&season=2019").status_code == 400

    def test_client_kann_kein_gewicht_setzen(self, client, monkeypatch):
        """
        VERTRAUENSGRENZE: Rang, Gewicht, Bedeutung und Score entstehen
        ausschliesslich serverseitig. Mitgeschickte Parameter dieser Art
        muessen wirkungslos bleiben.
        """
        import app as app_module

        captured = {}

        def fake_profile(player_id, season_from, season_to):
            captured["args"] = (player_id, season_from, season_to)
            return {"player_id": player_id, "name": "Test", "photo": None,
                    "nationality": None, "age": None, "position": None,
                    "season_from": season_from, "season_to": season_to,
                    "seasons": [], "has_unavailable_seasons": False,
                    "has_provisional_seasons": False,
                    "summary": bg.aggregate_big_games([]), "metrics": [],
                    "matches": [], "match_count": 0}

        monkeypatch.setattr(app_module, "big_games_profile", fake_profile)

        response = client.get(
            "/api/big-games-compare?a=874&season_from=2021&season_to=2021"
            "&weight=99&opponent_rank=1&importance=5&big_game_score=10"
        )
        assert response.status_code == 200
        # Die Route reicht ausschliesslich Spieler und Zeitraum weiter.
        assert captured["args"] == (874, 2021, 2021)

    def test_keine_route_liefert_die_rangliste_aus(self):
        """
        Die privaten Snapshots duerfen den Server nie vollstaendig
        verlassen - es darf keinen Endpunkt geben, der sie ausliefert.
        """
        import app as app_module
        rules = [str(r) for r in app_module.app.url_map.iter_rules()]
        assert not any("coefficient" in r.lower() or "ranking" in r.lower() for r in rules)

    def test_saisonauskunft_enthaelt_keine_klubdaten(self, client):
        """Die Auskunft nennt Saisons - niemals Klubs, Raenge oder Werte."""
        body = client.get("/api/big-games-seasons").get_json()
        payload = json.dumps(body).lower()
        for leak in ("coefficient", "club", "rank", "bayern", "barcelona"):
            assert leak not in payload


# ===========================================================================
# F) Trennung von Direktsuche und Population
# ===========================================================================

class TestCohortSeparation:
    def test_big_games_suche_beruehrt_den_pool_nicht(self):
        """
        Die historische Suche darf keinen Pool befuellen und keine
        Population veraendern - sonst tauchten historische Spieler in den
        Top-5-Plots auf.
        """
        import inspect
        source = inspect.getsource(bgl.search_big_games_players)
        for forbidden in ("load_all_players", "player_pool", "save_pool", "percentile"):
            assert forbidden not in source

    def test_pool_suche_bleibt_unveraendert(self):
        """Die bestehende Radar-/Plot-Suche nutzt weiterhin den Pool."""
        from src.data import player_compare_loader as pcl
        import inspect
        source = inspect.getsource(pcl.search_players)
        assert "search_players_in_pool" in source

    def test_suche_dedupliziert_ueber_die_player_id(self, monkeypatch):
        """
        Derselbe Spieler taucht in Liga UND Champions League auf und darf
        nur einmal erscheinen. Zusammengefuehrt wird ueber die stabile ID,
        nie ueber den Namen.
        """
        def fake_search(query, league_id, season):
            return [{"player": {"id": 874, "name": "Cristiano Ronaldo"},
                     "statistics": [{"team": {"name": "Manchester United"},
                                     "games": {"position": "Attacker"}}]}]

        monkeypatch.setattr(bgl.apisports_api, "search_players_in_league", fake_search)

        results = bgl.search_big_games_players("ronaldo", 2021, ("pl", "cl"))
        assert len(results) == 1
        assert results[0]["player_id"] == 874

    def test_ausfall_eines_wettbewerbs_bricht_die_suche_nicht(self, monkeypatch):
        from src.api.apisports_api import ApisportsUnavailable

        def fake_search(query, league_id, season):
            if league_id == 39:
                raise ApisportsUnavailable("weg")
            return [{"player": {"id": 154, "name": "L. Messi"}, "statistics": []}]

        monkeypatch.setattr(bgl.apisports_api, "search_players_in_league", fake_search)

        results = bgl.search_big_games_players("messi", 2021, ("pl", "cl"))
        assert [r["player_id"] for r in results] == [154]


# ===========================================================================
# G) Keine Regression
# ===========================================================================

class TestNoRegression:
    @pytest.fixture
    def client(self):
        import app as app_module
        app_module.app.config["TESTING"] = True
        return app_module.app.test_client()

    def test_bestehende_scopes_unveraendert(self):
        from src.data.player_compare_loader import COMPETITION_SCOPES
        for scope in ("club_all", "league", "cl", "euro", "world_cup", "national", "all"):
            assert scope in COMPETITION_SCOPES

    def test_big_games_ist_kein_backend_scope(self):
        """
        Big Games ist eine eigene Route mit eigenem Modell - es darf NICHT
        als Scope in die bestehende Vergleichspipeline eingeschleust
        werden, sonst wuerde es deren Perzentillogik beruehren.
        """
        from src.data.player_compare_loader import COMPETITION_SCOPES
        assert "big_games" not in COMPETITION_SCOPES

    def test_player_seasons_route_unveraendert(self, client):
        body = client.get("/api/player-seasons").get_json()
        assert "seasons" in body and body["seasons"]

    def test_vier_hauptbereiche_unveraendert(self):
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "templates", "index.html"), encoding="utf-8") as f:
            html = f.read()
        assert html.count('class="area-btn') == 4
        assert html.count('class="bottom-nav-btn') == 4

    def test_big_games_button_im_bestehenden_scope_raster(self):
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "templates", "index.html"), encoding="utf-8") as f:
            html = f.read()
        assert 'data-scope="big_games"' in html
        # Dieselbe Komponente wie die uebrigen Optionen - kein eigenes Bedienmuster.
        assert 'class="pc-scope-btn pc-scope-btn--big-games"' in html
