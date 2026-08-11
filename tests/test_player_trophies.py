"""
Tests fuer Spielererfolge (Block LIVE D2+).

Abgedeckt:
  A) normalize_trophies() - reine Gruppierungslogik, kein Netzwerk
  B) get_player_trophies() - Cache, Player-ID im Schluessel
  C) Einbindung in /api/player-profile (weicher Ausfall, kein Absturz
     des restlichen Profils)

Provider-Funktionen werden konsequent gemockt. Testdaten sind an einer
echten Antwort (API-Football, Spieler 278) ausgerichtet: "place" kommt
als "Winner" oder "2nd Place", und mindestens ein echter Titel hatte in
der Praxis season=None - genau dieser Fall wird unten nachgebaut
(test_winner_ohne_saison_zaehlt_trotzdem).
"""

import os

import pytest

from src.data.player_compare_loader import (
    normalize_trophies,
    get_player_trophies,
    TROPHY_WINNER_PLACE,
)


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(PROJECT_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def make_trophy(league="Ligue 1", country="France", season="2023/2024", place="Winner"):
    return {"league": league, "country": country, "season": season, "place": place}


# ===========================================================================
# A) Gruppierung
# ===========================================================================

class TestNormalizeTrophies:
    def test_ein_titel(self):
        trophies = normalize_trophies([make_trophy()])
        assert trophies == [{
            "league": "Ligue 1", "country": "France",
            "count": 1, "seasons": ["2023/2024"],
        }]

    def test_mehrere_gleiche_titel_werden_gruppiert(self):
        raw = [
            make_trophy(season="2021/2022"),
            make_trophy(season="2022/2023"),
            make_trophy(season="2023/2024"),
        ]
        trophies = normalize_trophies(raw)
        assert len(trophies) == 1
        assert trophies[0]["count"] == 3
        assert trophies[0]["seasons"] == ["2021/2022", "2022/2023", "2023/2024"]

    def test_unterschiedliche_saisons_zaehlen_korrekt(self):
        raw = [
            make_trophy(league="Champions League", season="2019/2020"),
            make_trophy(league="Champions League", season="2020/2021"),
            make_trophy(league="Ligue 1", season="2022/2023"),
        ]
        trophies = normalize_trophies(raw)
        by_league = {t["league"]: t["count"] for t in trophies}
        assert by_league["Champions League"] == 2
        assert by_league["Ligue 1"] == 1

    def test_runner_up_wird_nicht_gezaehlt(self):
        raw = [make_trophy(place="2nd Place"), make_trophy(place="Winner")]
        trophies = normalize_trophies(raw)
        assert len(trophies) == 1
        assert trophies[0]["count"] == 1

    def test_ausschliesslich_runner_up_ergibt_leere_liste(self):
        raw = [make_trophy(place="2nd Place"), make_trophy(place="3rd Place")]
        assert normalize_trophies(raw) == []

    def test_winner_ohne_saison_zaehlt_trotzdem(self):
        """
        An einer echten Antwort geprueft: ein Titel kann season=None
        haben und ist trotzdem ein echter, gewonnener Titel. Die Zaehlung
        (count) darf ihn nicht verlieren, nur die seasons-Liste bleibt
        fuer diesen Eintrag unvollstaendig.
        """
        raw = [
            make_trophy(season="2016/2017"),
            make_trophy(season=None),
        ]
        trophies = normalize_trophies(raw)
        assert trophies[0]["count"] == 2
        assert trophies[0]["seasons"] == ["2016/2017"]

    def test_sortierung_absteigend_nach_anzahl(self):
        raw = [
            make_trophy(league="A", season="1"),
            make_trophy(league="B", season="1"),
            make_trophy(league="B", season="2"),
            make_trophy(league="B", season="3"),
        ]
        trophies = normalize_trophies(raw)
        assert [t["league"] for t in trophies] == ["B", "A"]

    def test_keine_trophies(self):
        assert normalize_trophies([]) == []
        assert normalize_trophies(None) == []

    def test_kaputte_eintraege_werden_uebersprungen(self):
        raw = [None, "kaputt", {}, make_trophy()]
        trophies = normalize_trophies(raw)
        assert len(trophies) == 1

    def test_eintrag_ohne_liga_wird_uebersprungen(self):
        raw = [make_trophy(league=None), make_trophy()]
        trophies = normalize_trophies(raw)
        assert len(trophies) == 1

    def test_land_bleibt_erhalten(self):
        trophies = normalize_trophies([make_trophy(country="World")])
        assert trophies[0]["country"] == "World"

    def test_winner_konstante(self):
        """place-Vergleich nutzt die zentrale Konstante, kein Freitext-Duplikat."""
        assert TROPHY_WINNER_PLACE == "Winner"


# ===========================================================================
# B) Cache
# ===========================================================================

class TestCache:
    @pytest.fixture(autouse=True)
    def _isolierter_cache(self, tmp_path, monkeypatch):
        from src.utils import disk_cache
        monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path))
        self.tmp_path = tmp_path

    def test_zweiter_aufruf_kostet_keinen_request(self, monkeypatch):
        import src.data.player_compare_loader as loader_module

        calls = []
        monkeypatch.setattr(loader_module, "_get",
                            lambda endpoint, params=None: calls.append(params) or
                            [make_trophy()])

        get_player_trophies(278)
        get_player_trophies(278)

        assert len(calls) == 1

    def test_player_id_im_request(self, monkeypatch):
        import src.data.player_compare_loader as loader_module

        captured = {}
        monkeypatch.setattr(loader_module, "_get",
                            lambda endpoint, params=None: captured.update(
                                endpoint=endpoint, params=params) or [])

        get_player_trophies(278)

        assert captured["endpoint"] == "trophies"
        assert captured["params"] == {"player": 278}

    def test_unterschiedliche_spieler_eigene_cache_eintraege(self, monkeypatch):
        import src.data.player_compare_loader as loader_module

        monkeypatch.setattr(loader_module, "_get",
                            lambda endpoint, params=None: [make_trophy(
                                league=f"Liga-{params['player']}")])

        trophies_a = get_player_trophies(1)
        trophies_b = get_player_trophies(2)

        assert trophies_a[0]["league"] == "Liga-1"
        assert trophies_b[0]["league"] == "Liga-2"

    def test_cache_liegt_auf_der_platte(self, monkeypatch):
        import src.data.player_compare_loader as loader_module
        monkeypatch.setattr(loader_module, "_get",
                            lambda endpoint, params=None: [make_trophy()])

        get_player_trophies(278)

        files = list(self.tmp_path.glob("apisports__trophies__278*.json"))
        assert len(files) == 1

    def test_fehlende_player_id_wirft(self):
        from src.api.apisports_api import ApisportsUnavailable
        with pytest.raises(ApisportsUnavailable):
            get_player_trophies(None)

    def test_lange_ttl(self):
        """Titel aendern sich extrem selten - eigene, lange TTL."""
        source = _read("src", "data", "player_compare_loader.py")
        assert "TTL_PLAYER_TROPHIES = 60 * 60 * 24 * 14" in source


# ===========================================================================
# C) Einbindung in /api/player-profile
# ===========================================================================

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APISPORTS_KEY", "test-key")
    monkeypatch.setenv("FOOTBALL_DATA_KEY", "test-key")

    import app as app_module
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def _patch_profile_and_trophies(monkeypatch, trophies_result, trophies_raises=None):
    import app as app_module
    from src.data.player_compare_loader import build_player_profile

    def fake_profile(player_id, season, scope=None):
        entry = {
            "player": {"id": player_id, "name": "Test Spieler", "photo": "https://x/p.png",
                      "age": 25, "nationality": "Germany", "height": "182 cm",
                      "weight": "76 kg", "birth": {"date": "2001-03-01"}},
            "statistics": [{
                "league": {"id": 78, "name": "Bundesliga"},
                "team": {"id": 10, "name": "Test FC", "logo": "logo.png"},
                "games": {"appearences": 10, "minutes": 900, "position": "Attacker", "rating": "7.0"},
                "goals": {"total": 3, "assists": 1},
                "cards": {"yellow": 0, "red": 0},
            }],
        }
        return build_player_profile(entry, season, scope=scope)

    monkeypatch.setattr(app_module, "get_player_season_profile", fake_profile)

    if trophies_raises is not None:
        def boom(player_id):
            raise trophies_raises
        monkeypatch.setattr(app_module, "get_player_trophies", boom)
    else:
        monkeypatch.setattr(app_module, "get_player_trophies", lambda player_id: trophies_result)


class TestRouteIntegration:
    def test_trophies_im_profil_enthalten(self, client, monkeypatch):
        _patch_profile_and_trophies(monkeypatch, [
            {"league": "Ligue 1", "country": "France", "count": 3, "seasons": ["a", "b", "c"]},
        ])

        response = client.get("/api/player-profile?player_id=1&season=2025")
        assert response.status_code == 200
        assert response.get_json()["trophies"][0]["league"] == "Ligue 1"

    def test_keine_trophies_ergibt_leere_liste(self, client, monkeypatch):
        _patch_profile_and_trophies(monkeypatch, [])

        response = client.get("/api/player-profile?player_id=1&season=2025")
        assert response.status_code == 200
        assert response.get_json()["trophies"] == []

    def test_trophy_ausfall_lässt_profil_benutzbar(self, client, monkeypatch):
        """
        Der zentrale Punkt: ein Ausfall bei den Erfolgen darf die
        Kernstatistiken nicht mit sich reissen. Das Profil bleibt 200 mit
        vollstaendigen Kernwerten, trophies faellt auf [] zurueck.
        """
        from src.api.live_api import ApisportsUnavailable
        _patch_profile_and_trophies(monkeypatch, None, trophies_raises=ApisportsUnavailable("weg"))

        response = client.get("/api/player-profile?player_id=1&season=2025")
        assert response.status_code == 200

        data = response.get_json()
        assert data["trophies"] == []
        assert data["name"] == "Test Spieler"
        assert any(row["value"] == 3 for row in data["core_stats"] if row["key"] == "goals")

    def test_trophy_rate_limit_lässt_profil_benutzbar(self, client, monkeypatch):
        from src.api.live_api import ApisportsRateLimit
        _patch_profile_and_trophies(monkeypatch, None, trophies_raises=ApisportsRateLimit("Limit"))

        response = client.get("/api/player-profile?player_id=1&season=2025")
        assert response.status_code == 200
        assert response.get_json()["trophies"] == []
