"""
Tests fuer das Spielerprofil (Block LIVE D1).

Abgedeckt:
  A) build_player_detail() / _player_detail_stats() - reine Logik,
     kein Netzwerk, kein Flask
  B) HTTP-Route /api/player-profile - Flask-Testclient, Loader gemockt
  C) Wiederverwendung der bestehenden Player-Infrastruktur (keine zweite
     Pipeline)

Der bestehende Loader (get_player_season_profile) wird konsequent
gemockt, damit kein Testlauf einen echten API-Request ausloest - exakt
dasselbe Muster wie tests/test_player_routes.py.
"""

import os

import pytest

from src.data.player_compare_loader import build_player_profile, SCOPE_LABELS


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(PROJECT_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


BUNDESLIGA_ID = 78


def _api_entry(player_id=1, name="Test Spieler", position="Attacker",
               minutes=1800, league_id=BUNDESLIGA_ID, team="Test FC",
               rating="7.30", cards_red=0, photo="https://media.example/1.png"):
    """Ein /players-Eintrag in der Form, die API-Sports liefert."""
    return {
        "player": {
            "id": player_id,
            "name": name,
            "firstname": "Test",
            "lastname": "Spieler",
            "photo": photo,
            "age": 25,
            "nationality": "Germany",
            "height": "182 cm",
            "weight": "76 kg",
            "birth": {"date": "2001-03-01"},
        },
        "statistics": [{
            "league": {"id": league_id, "name": "Liga"},
            "team": {"id": 10, "name": team, "logo": "logo.png"},
            "games": {
                "appearences": 28, "lineups": 25, "minutes": minutes,
                "position": position, "rating": rating,
            },
            "shots": {"total": 60, "on": 26},
            "goals": {"total": 14, "conceded": None, "assists": 6, "saves": None},
            "passes": {"total": 700, "key": 34, "accuracy": 81},
            "tackles": {"total": 18, "blocks": 2, "interceptions": 9},
            "duels": {"total": 240, "won": 118},
            "dribbles": {"attempts": 70, "success": 33},
            "fouls": {"drawn": 30, "committed": 18},
            "cards": {"yellow": 4, "red": cards_red},
            "penalty": {"saved": None, "scored": 2, "missed": 1},
        }],
    }


def _profile(**kwargs):
    """Ein Spielerprofil, wie get_player_season_profile() es liefert."""
    entry = _api_entry(**{k: v for k, v in kwargs.items() if k in (
        "player_id", "name", "position", "minutes", "league_id", "team",
        "rating", "cards_red", "photo",
    )})
    return build_player_profile(entry, season=2025, scope=kwargs.get("scope"))


# ===========================================================================
# A) build_player_detail() / _player_detail_stats()
# ===========================================================================

class TestPlayerDetailAufbau:
    def _import(self):
        import app as app_module
        return app_module

    def test_kernwerte_in_fester_reihenfolge(self):
        app_module = self._import()
        core, _ = app_module._player_detail_stats(_profile())

        assert [row["key"] for row in core] == [
            "appearances", "minutes", "goals", "assists", "rating",
        ]

    def test_kernwerte_haben_werte(self):
        app_module = self._import()
        core, _ = app_module._player_detail_stats(_profile())
        by_key = {row["key"]: row["value"] for row in core}

        assert by_key["appearances"] == 28
        assert by_key["minutes"] == 1800
        assert by_key["goals"] == 14
        assert by_key["assists"] == 6
        assert by_key["rating"] == 7.3

    def test_karten_immer_in_weiteren_statistiken(self):
        app_module = self._import()
        _, extra = app_module._player_detail_stats(_profile(position="Attacker"))
        keys = [row["key"] for row in extra]

        assert "cards_yellow" in keys
        assert "cards_red" in keys

    def test_rote_karte_hat_einen_wert(self):
        app_module = self._import()
        _, extra = app_module._player_detail_stats(_profile(cards_red=1))
        by_key = {row["key"]: row["value"] for row in extra}
        assert by_key["cards_red"] == 1

    def test_weitere_statistiken_sind_positionsabhaengig(self):
        """
        Dieselbe Gruppierung wie im Radar (RADAR_PROFILES): ein Stuermer
        bekommt andere Zusatzwerte als ein Torwart - keine zweite,
        eigene Gruppierungslogik fuer das Profil.
        """
        app_module = self._import()

        _, attacker_extra = app_module._player_detail_stats(_profile(position="Attacker"))
        _, keeper_extra = app_module._player_detail_stats(_profile(position="Goalkeeper"))

        attacker_keys = {row["key"] for row in attacker_extra}
        keeper_keys = {row["key"] for row in keeper_extra}

        assert "shots_per90" in attacker_keys
        assert "shots_per90" not in keeper_keys
        assert "saves_per90" in keeper_keys
        assert "saves_per90" not in attacker_keys

    def test_keine_ueberschneidung_zwischen_kern_und_weiteren_werten(self):
        app_module = self._import()
        core, extra = app_module._player_detail_stats(_profile(position="Midfielder"))

        core_keys = {row["key"] for row in core}
        extra_keys = {row["key"] for row in extra}
        assert core_keys.isdisjoint(extra_keys)

    def test_unbekannte_position_liefert_nur_karten_als_extra(self):
        app_module = self._import()
        _, extra = app_module._player_detail_stats(_profile(position=None))
        assert {row["key"] for row in extra} == {"cards_yellow", "cards_red"}

    def test_jede_zeile_hat_metadaten(self):
        """Label, kind, direction, description - dieselben Metadaten wie im Vergleich."""
        app_module = self._import()
        core, extra = app_module._player_detail_stats(_profile())

        for row in core + extra:
            assert row["label"]
            assert row["kind"]
            assert row["direction"] in ("higher_better", "lower_better")
            assert "value" in row

    def test_build_player_detail_enthaelt_identitaet_und_scope(self):
        app_module = self._import()
        detail = app_module.build_player_detail(_profile())

        assert detail["player_id"] == 1
        assert detail["name"] == "Test Spieler"
        assert detail["firstname"] == "Test"
        assert detail["lastname"] == "Spieler"
        assert detail["height"] == "182 cm"
        assert detail["weight"] == "76 kg"
        assert detail["birth_date"] == "2001-03-01"
        assert detail["scope"] == "club_all"
        assert detail["scope_label"] == SCOPE_LABELS["club_all"]
        assert detail["scope_hint"]

    def test_build_player_detail_ganz_ohne_statistikbloecke(self):
        """
        Spieler ganz ohne statistics-Bloecke (z. B. noch kein einziger
        Einsatz erfasst): Identitaet bleibt vollstaendig, Kernwerte sind
        None statt erfunden.
        """
        app_module = self._import()
        entry = _api_entry()
        entry["statistics"] = []
        profile = build_player_profile(entry, season=2025)
        assert profile["data_available"] is False

        detail = app_module.build_player_detail(profile)
        assert detail["player_id"] == 1
        assert detail["name"] == "Test Spieler"
        assert detail["data_available"] is False
        assert [row["key"] for row in detail["core_stats"]] == [
            "appearances", "minutes", "goals", "assists", "rating",
        ]
        assert all(row["value"] is None for row in detail["core_stats"])

    def test_data_available_false_verbirgt_vorhandene_werte_nicht(self):
        """
        Wichtiger Grenzfall (siehe Analyse, Abschnitt 10): data_available
        bedeutet "im Perzentil-Pool der fuenf Vergleichsligen vertreten",
        NICHT "hat Werte". Ein unbekannter Liga-Block faellt in
        _infer_comp_type() auf "cup" zurueck und wird in club_all darum
        trotzdem aggregiert - die Zahlen sind dann echt und duerfen nicht
        unterschlagen werden, obwohl data_available False bleibt.
        """
        app_module = self._import()
        profile = _profile(league_id=99999)   # unbekannte Liga
        assert profile["data_available"] is False

        detail = app_module.build_player_detail(profile)
        by_key = {row["key"]: row["value"] for row in detail["core_stats"]}
        assert by_key["minutes"] == 1800
        assert by_key["goals"] == 14

    def test_fehlendes_foto_bleibt_none(self):
        app_module = self._import()
        detail = app_module.build_player_detail(_profile(photo=None))
        assert detail["photo"] is None

    def test_competitions_werden_durchgereicht(self):
        app_module = self._import()
        detail = app_module.build_player_detail(_profile())
        assert detail["competition_count"] == len(detail["competitions"])
        assert detail["competition_count"] >= 1


# ===========================================================================
# B) HTTP-Route
# ===========================================================================

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APISPORTS_KEY", "test-key")
    monkeypatch.setenv("FOOTBALL_DATA_KEY", "test-key")

    import app as app_module
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def _patch_profile(monkeypatch, **kwargs):
    import app as app_module

    def fake(player_id, season, scope=None):
        return _profile(player_id=player_id, scope=scope, **kwargs)

    monkeypatch.setattr(app_module, "get_player_season_profile", fake)


class TestRoute:
    def test_fehlende_player_id(self, client):
        response = client.get("/api/player-profile")
        assert response.status_code == 400

    def test_ungueltige_player_id(self, client):
        assert client.get("/api/player-profile?player_id=abc").status_code == 400

    def test_negative_player_id(self, client):
        assert client.get("/api/player-profile?player_id=-1").status_code == 400
        assert client.get("/api/player-profile?player_id=0").status_code == 400

    def test_gueltige_anfrage(self, client, monkeypatch):
        _patch_profile(monkeypatch)
        response = client.get("/api/player-profile?player_id=1&season=2025")
        assert response.status_code == 200

        data = response.get_json()
        assert data["player_id"] == 1
        assert data["name"] == "Test Spieler"
        assert data["core_stats"]
        assert data["extra_stats"]

    def test_ungueltige_season(self, client, monkeypatch):
        _patch_profile(monkeypatch)
        response = client.get("/api/player-profile?player_id=1&season=abc")
        assert response.status_code == 400

    def test_season_ausserhalb_des_gueltigen_bereichs(self, client, monkeypatch):
        _patch_profile(monkeypatch)
        assert client.get("/api/player-profile?player_id=1&season=1990").status_code == 400

    def test_ohne_season_gilt_aktuelle_saison(self, client, monkeypatch):
        import app as app_module
        from src.api import apisports_api

        _patch_profile(monkeypatch)
        response = client.get("/api/player-profile?player_id=1")
        assert response.status_code == 200
        assert response.get_json()["season"] == apisports_api.CURRENT_SEASON

    def test_gueltiger_scope(self, client, monkeypatch):
        _patch_profile(monkeypatch)
        response = client.get("/api/player-profile?player_id=1&season=2025&scope=league")
        assert response.status_code == 200
        assert response.get_json()["scope"] == "league"

    def test_ungueltiger_scope_faellt_auf_standard_zurueck(self, client, monkeypatch):
        """
        Wie ueberall sonst in der Vergleichsarchitektur (normalize_scope):
        ein unbekannter Scope erzeugt keinen Fehler, sondern faellt auf
        club_all zurueck.
        """
        _patch_profile(monkeypatch)
        response = client.get("/api/player-profile?player_id=1&season=2025&scope=unsinn")
        assert response.status_code == 200
        assert response.get_json()["scope"] == "club_all"

    def test_unbekannter_spieler_ergibt_404(self, client, monkeypatch):
        import app as app_module

        def fake(player_id, season, scope=None):
            # Wie get_player_season_profile() bei unbekannter ID: player_id
            # bleibt None im Ergebnisprofil.
            return build_player_profile({}, season, scope=scope)

        monkeypatch.setattr(app_module, "get_player_season_profile", fake)

        response = client.get("/api/player-profile?player_id=999999&season=2025")
        assert response.status_code == 404
        assert "error" in response.get_json()

    def test_spieler_ohne_saisondaten_ist_kein_404(self, client, monkeypatch):
        """
        Bekannter Spieler, aber keine Statistiken im gewaehlten Scope
        (z. B. ausserhalb der fuenf Vergleichsligen) - das ist ein
        gueltiges 200 mit data_available=False, kein Fehler.
        """
        _patch_profile(monkeypatch, league_id=99999)
        response = client.get("/api/player-profile?player_id=1&season=2025")
        assert response.status_code == 200

        data = response.get_json()
        assert data["player_id"] == 1
        assert data["name"] == "Test Spieler"
        assert data["data_available"] is False

    def test_provider_rate_limit(self, client, monkeypatch):
        import app as app_module
        from src.api.live_api import ApisportsRateLimit

        def boom(player_id, season, scope=None):
            raise ApisportsRateLimit("Limit")

        monkeypatch.setattr(app_module, "get_player_season_profile", boom)
        assert client.get("/api/player-profile?player_id=1&season=2025").status_code == 429

    def test_provider_ausfall(self, client, monkeypatch):
        import app as app_module
        from src.api.live_api import ApisportsUnavailable

        def boom(player_id, season, scope=None):
            raise ApisportsUnavailable("weg")

        monkeypatch.setattr(app_module, "get_player_season_profile", boom)
        assert client.get("/api/player-profile?player_id=1&season=2025").status_code == 503

    def test_bestehender_loader_wird_aufgerufen(self, client, monkeypatch):
        """
        Die Route MUSS get_player_season_profile() nutzen - keine zweite,
        eigene Player-Pipeline.
        """
        import app as app_module

        calls = []

        def fake(player_id, season, scope=None):
            calls.append((player_id, season, scope))
            return _profile(player_id=player_id, scope=scope)

        monkeypatch.setattr(app_module, "get_player_season_profile", fake)

        client.get("/api/player-profile?player_id=42&season=2024&scope=cl")
        assert calls == [(42, 2024, "cl")]


# ===========================================================================
# C) Wiederverwendung bestehender Infrastruktur
# ===========================================================================

class TestWiederverwendung:
    def test_route_importiert_bestehenden_loader(self):
        source = _read("app.py")
        assert "get_player_season_profile" in source
        # Kein zweiter Rohdatenabruf, kein eigener /players-Aufruf in app.py
        # fuer dieses Feature - nur der bereits importierte Loader.
        assert 'source=("games", "rating")' not in source

    def test_keine_zweite_metrikliste(self):
        """
        Kernwerte und weitere Statistiken nutzen METRICS/RADAR_PROFILES
        aus player_metrics.py - keine zweite Kennzahltabelle in app.py.
        """
        source = _read("app.py")
        assert "metrics_for_position" in source
        assert "compute_metric" in source
        assert "describe_metric" in source

    def test_cards_red_gehoert_zum_bestehenden_katalog(self):
        """
        Rote Karten wurden dem bestehenden METRICS-Katalog hinzugefuegt
        (neben cards_yellow), nicht als Sonderfall im Profil-Code.
        """
        source = _read("src", "data", "player_metrics.py")
        assert '"cards_red"' in source

    def test_keine_eigene_saison_ttl(self):
        """
        Caching bleibt vollstaendig in player_compare_loader.py - app.py
        setzt keine eigene TTL fuer Spielerprofile.
        """
        source = _read("app.py")
        start = source.index("def api_player_profile")
        end = source.index("\n\n\n", start)
        block = source[start:end]
        assert "disk_cached_call" not in block
        assert "TTL_" not in block
