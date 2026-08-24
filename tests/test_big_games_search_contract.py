"""
Tests fuer die Big-Games-Suche und die Radar-Rueckfallebene (Block F1.1).

Hintergrund: In Block F1 lieferte die Big-Games-Suche ein anderes
Feldformat, als die bestehende Trefferliste erwartet. Folge im UI:
jeder Treffer erschien als "Unbekannt" und war deaktiviert - auch
aktuelle Spieler. Diese Datei sichert genau diese Vertraege ab.

Abgedeckt:
  A) Suchergebnis-Vertrag (Feldnamen, comparable, Labels)
  B) Positionsnormalisierung (G/D/M/F -> FootSim-Gruppen)
  C) Mehrsaison-Suche ueber den gesamten Zeitraum
  D) Deduplizierung ueber die Player-ID
  E) Route /api/big-games-search mit Zeitraum
  F) Radar-Rueckfallebene: Pool hat Vorrang, Live nur als Ergaenzung
  G) Population/Pool bleiben unberuehrt

Kein echter Netzwerkzugriff: alle Anbieterantworten sind synthetisch.
"""

import pytest

from src.data import live_player_search as lps
from src.data import big_games_loader as bgl
from src.data import player_compare_loader as pcl


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    from src.utils import disk_cache
    monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path))


def make_entry(player_id=19617, name="M. Olise", position="M",
               team="Bayern München", league_id=78, minutes=2100, age=24):
    return {
        "player": {"id": player_id, "name": name, "age": age,
                   "photo": f"https://x/{player_id}.png", "nationality": "France"},
        "statistics": [{
            "team": {"id": 157, "name": team, "logo": "https://x/t.png"},
            "league": {"id": league_id, "name": "Testliga"},
            "games": {"position": position, "minutes": minutes},
        }],
    }


# ===========================================================================
# A) Vertrag der Trefferliste
# ===========================================================================

class TestSearchContract:
    """
    Die Feldnamen hier sind KEIN Implementierungsdetail: exakt diese liest
    das Frontend (pcRenderResults/pcSelectPlayer/pcRenderSelected). Weichen
    sie ab, erscheint der Treffer als "Unbekannt" und laesst sich nicht
    anwaehlen - genau der Fehler aus Block F1.
    """

    @pytest.fixture
    def results(self, monkeypatch):
        monkeypatch.setattr(lps.apisports_api, "search_players_in_league",
                            lambda q, league_id, season: [make_entry(league_id=league_id)])
        return lps.search_live("olise", [2025], ("bl1",))

    def test_pflichtfelder_vorhanden(self, results):
        assert results
        entry = results[0]
        for key in ("player_id", "name", "photo", "age", "team_name",
                    "position", "position_label", "league_label",
                    "minutes", "comparable", "season"):
            assert key in entry, key

    def test_name_ist_gesetzt_und_nicht_unbekannt(self, results):
        """Frueher lag der Name unter player_name - das Frontend las name."""
        assert results[0]["name"] == "M. Olise"

    def test_photo_ist_gesetzt(self, results):
        """Frueher unter player_photo - das Frontend las photo."""
        assert results[0]["photo"]

    def test_comparable_ist_wahr(self, results):
        """
        DER Kernfehler aus F1: ohne dieses Feld war !player.comparable in
        JavaScript immer wahr, wodurch JEDER Treffer deaktiviert wurde.

        Fachlich: Zugehoerigkeit zur Top-5-Population und Vergleichbarkeit
        in Big Games sind zwei verschiedene Dinge.
        """
        assert results[0]["comparable"] is True

    def test_labels_sind_gesetzt(self, results):
        assert results[0]["position_label"] == "Mittelfeld"
        assert results[0]["league_label"] == "Bundesliga"

    def test_herkunft_ist_erkennbar(self, results):
        assert results[0]["source"] == "live"

    def test_eintrag_ohne_id_wird_verworfen(self, monkeypatch):
        monkeypatch.setattr(lps.apisports_api, "search_players_in_league",
                            lambda q, l, s: [{"player": {"name": "Ohne ID"}}])
        assert lps.search_live("ohne", [2025], ("bl1",)) == []


# ===========================================================================
# B) Positionsnormalisierung
# ===========================================================================

class TestPositionNormalization:
    @pytest.mark.parametrize("code,expected", [
        ("G", "Goalkeeper"),
        ("D", "Defender"),
        ("M", "Midfielder"),
        ("F", "Attacker"),
    ])
    def test_kurzcodes(self, code, expected):
        assert lps.normalize_position(code) == expected

    def test_ausgeschriebene_werte_bleiben(self):
        assert lps.normalize_position("Attacker") == "Attacker"

    @pytest.mark.parametrize("raw", [None, "", "  ", "XX", 5])
    def test_unbekanntes_bleibt_none(self, raw):
        assert lps.normalize_position(raw) is None

    def test_positionsfilter_greift_im_suchergebnis(self, monkeypatch):
        """
        Der Frontend-Filter vergleicht result.position mit der gewaehlten
        Gruppe ("Attacker"). Bliebe der Kurzcode "F" stehen, faende der
        Filter nichts - die Suche wirkte dann leer.
        """
        monkeypatch.setattr(lps.apisports_api, "search_players_in_league",
                            lambda q, l, s: [make_entry(position="F")])
        result = lps.search_live("x", [2025], ("bl1",))[0]
        assert result["position"] == "Attacker"
        assert result["position_label"] == "Angriff"

    def test_loader_nutzt_dieselbe_normalisierung(self):
        """Suche und Auswertung duerfen nicht zwei Positionssprachen sprechen."""
        assert bgl._normalize_position is lps.normalize_position


# ===========================================================================
# C) Mehrsaison-Suche
# ===========================================================================

class TestMultiSeasonSearch:
    def test_spieler_nur_in_der_ersten_saison_wird_gefunden(self, monkeypatch):
        """
        Kernanforderung F1.1: wer 2024/25 in einer unserer Ligen spielte und
        danach wechselte, muss fuer den Zeitraum 2024/25-2025/26 trotzdem
        auffindbar sein. Vorher wurde nur die Endsaison durchsucht.
        """
        def fake(query, league_id, season):
            return [make_entry(player_id=874, name="Cristiano Ronaldo")] if season == 2024 else []

        monkeypatch.setattr(lps.apisports_api, "search_players_in_league", fake)

        results = bgl.search_big_games_players("ronaldo", 2024, 2025, ("pl",))
        assert [r["player_id"] for r in results] == [874]

    def test_alle_saisons_des_bereichs_werden_durchsucht(self, monkeypatch):
        seen = []

        def fake(query, league_id, season):
            seen.append(season)
            return []

        monkeypatch.setattr(lps.apisports_api, "search_players_in_league", fake)
        bgl.search_big_games_players("x", 2021, 2024, ("pl",))
        assert sorted(set(seen)) == [2021, 2022, 2023, 2024]

    def test_juengste_saison_bestimmt_die_anzeige(self, monkeypatch):
        """
        Ein Spieler mit Vereinswechsel im Zeitraum soll mit seinem
        juengsten Verein erscheinen - das ist der, den der Nutzer sucht.
        """
        def fake(query, league_id, season):
            team = "Manchester United" if season == 2021 else "Juventus"
            return [make_entry(player_id=874, name="C. Ronaldo", team=team)]

        monkeypatch.setattr(lps.apisports_api, "search_players_in_league", fake)

        results = bgl.search_big_games_players("ronaldo", 2020, 2021, ("pl",))
        assert len(results) == 1
        assert results[0]["team_name"] == "Manchester United"
        assert results[0]["season"] == 2021

    def test_vertauschter_zeitraum_wird_korrigiert(self, monkeypatch):
        seen = []
        monkeypatch.setattr(lps.apisports_api, "search_players_in_league",
                            lambda q, l, s: seen.append(s) or [])
        bgl.search_big_games_players("x", 2024, 2022, ("pl",))
        assert sorted(set(seen)) == [2022, 2023, 2024]


# ===========================================================================
# D) Deduplizierung
# ===========================================================================

class TestDeduplication:
    def test_ueber_saisons_und_wettbewerbe_hinweg_nur_einmal(self, monkeypatch):
        monkeypatch.setattr(lps.apisports_api, "search_players_in_league",
                            lambda q, l, s: [make_entry(player_id=154, name="L. Messi")])

        results = bgl.search_big_games_players("messi", 2021, 2024, ("pl", "cl", "fl1"))
        assert len(results) == 1
        assert results[0]["player_id"] == 154

    def test_gleicher_name_verschiedene_ids_bleiben_getrennt(self, monkeypatch):
        """
        Zusammengefuehrt wird ueber die ID, NIE ueber den Namen. Zwei
        verschiedene Spieler mit demselben Nachnamen muessen beide
        erscheinen (z. B. Messi und Messias).
        """
        def fake(query, league_id, season):
            return [
                make_entry(player_id=154, name="L. Messi"),
                make_entry(player_id=56396, name="Junior Messias"),
            ]

        monkeypatch.setattr(lps.apisports_api, "search_players_in_league", fake)
        results = bgl.search_big_games_players("messi", 2021, 2021, ("pl",))
        assert {r["player_id"] for r in results} == {154, 56396}


# ===========================================================================
# E) Route
# ===========================================================================

class TestSearchRoute:
    @pytest.fixture
    def client(self, monkeypatch):
        """
        Testclient mit deterministischer Big-Games-Abdeckung.

        WARUM DIE ABDECKUNG ERSETZT WIRD
        --------------------------------
        /api/big-games-search loest zuerst den Saisonbereich auf:

            _resolve_big_games_range -> _big_games_season_bounds
              -> uefa_coefficients.available_seasons
              -> liest data/big_games/uefa_coefficients/

        Dieses Verzeichnis ist gitignored. Im frischen Checkout ist es
        leer, die Route bricht mit 400 "Fuer Big Games liegen derzeit
        keine Vergleichsdaten vor" ab - und zwar BEVOR der weiter unten
        gemockte big_games_search_players ueberhaupt erreicht wird.
        Deshalb fehlten season_from und season_to in der Antwort.

        Ersetzt wird die Abdeckung deshalb genau dort, wo die privaten
        Daten ins Projekt kommen. Alles danach - Bereichspruefung,
        Vertauschung, Spannenbegrenzung, Antwortfelder - laeuft echt.

        Die Fenstergrenzen werden aus den Argumenten abgeleitet und nicht
        fest verdrahtet: So bleibt der Test auch dann richtig, wenn sich
        die laufende Saison weiterdreht.
        """
        from src.data import uefa_coefficients

        monkeypatch.setattr(uefa_coefficients, "available_seasons",
                            lambda erste, letzte: list(range(erste, letzte + 1)))

        import app as app_module
        app_module.app.config["TESTING"] = True
        return app_module.app.test_client()

    def test_die_abdeckung_ist_im_test_wirklich_vorhanden(self, client):
        """
        Sicherung gegen einen stillen Rueckfall: Waere die Abdeckung
        wieder leer, liefen alle Vertragstests unten ins Leere und der
        400-Test unten bestuende aus dem falschen Grund.
        """
        antwort = client.get("/api/big-games-seasons")
        assert antwort.status_code == 200
        assert antwort.get_json()["seasons"], "keine Saisons verfuegbar"

    def test_zeitraum_wird_durchgereicht(self, client, monkeypatch):
        import app as app_module
        captured = {}

        def fake(query, season_from, season_to, league_codes):
            captured["range"] = (season_from, season_to)
            return []

        monkeypatch.setattr(app_module, "big_games_search_players", fake)
        response = client.get(
            "/api/big-games-search?q=Olise&season_from=2024&season_to=2025")

        assert response.status_code == 200
        assert captured["range"] == (2024, 2025)

    def test_einzelne_saison_bleibt_zulaessig(self, client, monkeypatch):
        """Rueckwaertskompatibel: season= wird als Zeitraum von genau
        einer Saison verstanden."""
        import app as app_module
        captured = {}

        def fake(query, season_from, season_to, league_codes):
            captured["range"] = (season_from, season_to)
            return []

        monkeypatch.setattr(app_module, "big_games_search_players", fake)
        client.get("/api/big-games-search?q=Olise&season=2023")
        assert captured["range"] == (2023, 2023)

    def test_zu_kurze_anfrage(self, client):
        assert client.get(
            "/api/big-games-search?q=ab&season_from=2021&season_to=2021"
        ).status_code == 400

    def test_zeitraum_ausserhalb_der_abdeckung(self, client):
        response = client.get(
            "/api/big-games-search?q=Messi&season_from=2019&season_to=2021")
        assert response.status_code == 400
        assert response.get_json()["results"] == []

    def test_antwort_enthaelt_den_zeitraum(self, client, monkeypatch):
        import app as app_module
        monkeypatch.setattr(app_module, "big_games_search_players",
                            lambda q, a, b, c: [])
        body = client.get(
            "/api/big-games-search?q=Olise&season_from=2024&season_to=2025").get_json()
        assert body["season_from"] == 2024
        assert body["season_to"] == 2025


# ===========================================================================
# F) Radar-Rueckfallebene
# ===========================================================================

class TestRadarFallback:
    def test_pool_hat_vorrang_und_kostet_keinen_request(self, monkeypatch):
        """
        Solange der Pool liefert, darf KEIN Anbieter-Request entstehen -
        sonst waere die Rueckfallebene eine schleichende Budgetlast.
        """
        monkeypatch.setattr(pcl, "search_players_in_pool",
                            lambda q, s: [{"player_id": 1, "name": "Pool-Spieler",
                                           "comparable": True}])

        def boom(*args, **kwargs):
            raise AssertionError("Live-Suche darf hier nicht laufen")

        monkeypatch.setattr(lps, "search_live", boom)

        results = pcl.search_players("pool", 2025)
        assert results[0]["name"] == "Pool-Spieler"

    def test_live_faellt_ein_wenn_der_pool_nichts_hat(self, monkeypatch):
        monkeypatch.setattr(pcl, "search_players_in_pool", lambda q, s: [])
        monkeypatch.setattr(lps, "search_live",
                            lambda q, seasons, *a, **k: [{"player_id": 154,
                                                          "name": "L. Messi",
                                                          "comparable": True}])
        results = pcl.search_players("messi", 2021)
        assert results[0]["player_id"] == 154

    def test_zu_kurze_anfrage_loest_keinen_request_aus(self, monkeypatch):
        monkeypatch.setattr(pcl, "search_players_in_pool", lambda q, s: [])

        def boom(*args, **kwargs):
            raise AssertionError("Zu kurze Anfrage darf nicht live suchen")

        monkeypatch.setattr(lps, "search_live", boom)
        assert pcl.search_players("ab", 2025) == []

    def test_ausfall_der_rueckfallebene_ist_kein_fehler(self, monkeypatch):
        from src.api.apisports_api import ApisportsUnavailable

        monkeypatch.setattr(pcl, "search_players_in_pool", lambda q, s: [])

        def boom(*args, **kwargs):
            raise ApisportsUnavailable("weg")

        monkeypatch.setattr(lps, "search_live", boom)
        assert pcl.search_players("messi", 2021) == []

    def test_nur_die_angefragte_saison_wird_live_gesucht(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(pcl, "search_players_in_pool", lambda q, s: [])
        monkeypatch.setattr(lps, "search_live",
                            lambda q, seasons, *a, **k: captured.setdefault(
                                "seasons", list(seasons)) or [])
        pcl.search_players("messi", 2021)
        assert captured["seasons"] == [2021]


# ===========================================================================
# G) Population bleibt unberuehrt
# ===========================================================================

class TestPopulationUntouched:
    def test_live_suche_kennt_weder_pool_noch_perzentile(self):
        """
        Strukturtest: die Live-Suche darf die Vergleichspopulation nicht
        einmal erreichen koennen. Sonst koennte ein historischer Spieler
        in Scatter/Perzentile geraten.
        """
        import inspect
        source = inspect.getsource(lps)
        for forbidden in ("player_pool", "load_all_players", "percentile",
                          "build_quantiles", "save_pool"):
            assert forbidden not in source, forbidden

    def test_pool_suche_bleibt_erste_wahl(self):
        import inspect
        source = inspect.getsource(pcl.search_players)
        pool_pos = source.index("search_players_in_pool")
        live_pos = source.index("live_player_search.search_live")
        assert pool_pos < live_pos

    def test_scatter_nutzt_weiterhin_den_pool(self):
        """Die Plot-Population wird ausschliesslich aus dem Pool gebildet."""
        import inspect
        from src.data import player_pool
        source = inspect.getsource(player_pool)
        assert "live_player_search" not in source


# ===========================================================================
# H) Oberflaeche: Zeitmodell und Bereitschaftspruefung
# ===========================================================================

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(PROJECT_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class TestSeasonControlsUI:
    """
    Bei Big Games gilt EIN gemeinsamer Zeitraum. Die beiden
    Slot-Saisonfelder waeren dort nicht nur ueberfluessig, sondern
    irrefuehrend - der Vergleich wertet sie gar nicht aus.
    """

    def test_slot_saisonfelder_werden_bei_big_games_versteckt(self):
        script = _read("static", "script.js")
        start = script.index("function bgSyncVisibility()")
        block = script[start:script.index("async function bgEnsureLoaded", start)]
        assert ".pc-slot .pc-season-row" in block
        assert "hide(row)" in block
        assert "show(row)" in block

    def test_verlassen_stellt_die_felder_wieder_her(self):
        """Die Felder werden nur versteckt, nie geleert oder umgebaut."""
        script = _read("static", "script.js")
        start = script.index("function bgSyncVisibility()")
        block = script[start:script.index("async function bgEnsureLoaded", start)]
        for destructive in ("innerHTML", "remove()", ".value = "):
            assert destructive not in block, destructive

    def test_umschalten_ruft_die_sichtbarkeitslogik(self):
        script = _read("static", "script.js")
        start = script.index("function pcSetScope(scope, options)")
        block = script[start:script.index("/* ---------- 16d-bg", start)]
        assert "bgSyncVisibility()" in block

    def test_markup_hat_die_saisonzeilen_weiterhin(self):
        """Nicht geloescht - der Normalmodus braucht sie unveraendert."""
        html = _read("templates", "index.html")
        assert html.count('class="pc-season-row"') == 2
        assert 'id="pc-season-a"' in html
        assert 'id="pc-season-b"' in html

    def test_kein_zweiter_zeitraumwaehler(self):
        html = _read("templates", "index.html")
        assert html.count('id="bg-season-from"') == 1
        assert html.count('id="bg-season-to"') == 1


class TestReadyValidation:
    def test_doppelpruefung_haengt_bei_big_games_nicht_an_der_slot_saison(self):
        """
        Die Slot-Saisonwerte sind bei Big Games ausgeblendet und tot. Sie
        duerfen nicht darueber entscheiden, ob verglichen werden darf.
        """
        script = _read("static", "script.js")
        start = script.index("function pcUpdateReady()")
        block = script[start:script.index("/* ---------- 16e.", start)]
        assert "bgIsActive()" in block
        # Der Saisonvergleich bleibt fuer den Normalmodus erhalten.
        assert "pcState.a.season === pcState.b.season" in block

    def test_suche_nutzt_den_zeitraum_statt_einer_einzelsaison(self):
        script = _read("static", "script.js")
        assert "season_from=${bgState.from}&season_to=${bgState.to}" in script
        # Der alte Einzelsaison-Aufruf darf nicht zurueckkehren.
        assert "big-games-search?q=${encodeURIComponent(query)}`\n              + `&season=" not in script

    def test_zeitraum_steht_vor_der_suche_fest(self):
        """Sonst ginge beim ersten Tastendruck "null" an den Server."""
        script = _read("static", "script.js")
        assert "if (bgIsActive()) await bgEnsureLoaded();" in script
