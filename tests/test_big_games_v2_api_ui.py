"""
Big Game Rating V2: Route, Oberflaeche und Bereichsnavigation.

Zwei Arten von Tests, bewusst getrennt:

  * Routentests gegen den echten Flask-Testclient - sie pruefen den
    Vertrag zwischen Oberflaeche und Server (Parameter, Fehlerfaelle,
    Nutzlast).
  * Quelltexttests auf templates/index.html und static/script.js - im
    selben Stil wie tests/test_navigation_block1.py, weil FootSim keinen
    Browser in der Testumgebung hat.
"""

import json
import os

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(PROJECT_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    os.environ.setdefault("DATABASE_URL", "sqlite://")
    os.environ.setdefault("SECRET_KEY", "test")
    import app as appmod
    appmod.app.config["TESTING"] = True
    with appmod.app.test_client() as c:
        yield c


def hole(client, query):
    antwort = client.get(f"/api/player-leaderboard?{query}")
    return antwort.status_code, antwort.get_json()


def datensatz_fehlt():
    from src.data import big_games_dataset as bgd
    from src.data import big_games_public as bgp
    return not (os.path.exists(bgd.dataset_path(2025))
                or os.path.exists(bgp.public_path(2025)))


echte_daten = pytest.mark.skipif(
    datensatz_fehlt(), reason="Big-Games-Datensatz liegt auf diesem Host nicht vor")


class TestKatalog:

    def test_der_katalog_nennt_die_waehlbaren_huerden(self, client):
        """Die Oberflaeche baut ihre Auswahl aus dem Serverkatalog."""
        antwort = client.get("/api/player-leaderboard-options")
        assert antwort.status_code == 200
        big = antwort.get_json()["big_games"]
        assert big["uefa_max_ranks"] == [5, 10, 15, 20, 25, 30]
        assert big["fifa_max_ranks"] == [5, 10, 15, 20]
        assert big["default_uefa_max_rank"] == 30
        assert big["default_fifa_max_rank"] == 20

    def test_anzahl_und_gegnerhuerde_sind_verschiedene_dinge(self, client):
        """
        "Anzahl" ist die Laenge der Liste, die Huerde die Gegnerstaerke.
        Beide Kataloge existieren nebeneinander und sind nicht dasselbe.
        """
        katalog = client.get("/api/player-leaderboard-options").get_json()
        assert katalog["limits"] == [5, 10, 15, 20, 30]
        assert katalog["big_games"]["uefa_max_ranks"] != katalog["limits"]


class TestParameter:

    @pytest.mark.parametrize("huerde", [5, 10, 15, 20, 25, 30])
    def test_jede_uefa_stufe_wird_angenommen(self, client, huerde):
        status, daten = hole(
            client, "scope=big_games&season_from=2025&season_to=2025"
                    f"&position=all&limit=10&uefa_max_rank={huerde}")
        assert status == 200
        assert daten["opponent_cutoffs"]["uefa_max_rank"] == huerde

    @pytest.mark.parametrize("huerde", [5, 10, 15, 20])
    def test_jede_fifa_stufe_wird_angenommen(self, client, huerde):
        status, daten = hole(
            client, "scope=big_games&season_from=2025&season_to=2025"
                    f"&position=all&limit=10&fifa_max_rank={huerde}")
        assert status == 200
        assert daten["opponent_cutoffs"]["fifa_max_rank"] == huerde

    @pytest.mark.parametrize("query,feld", [
        ("uefa_max_rank=40", "uefa"),
        ("uefa_max_rank=7", "uefa"),
        ("uefa_max_rank=0", "uefa"),
        ("uefa_max_rank=abc", "uefa"),
        ("fifa_max_rank=30", "fifa"),
        ("fifa_max_rank=12", "fifa"),
    ])
    def test_unzulaessige_stufen_werden_abgewiesen(self, client, query, feld):
        """
        Nicht stillschweigend zurechtbiegen: eine unbekannte Stufe ist ein
        Fehler des Aufrufers. Sonst saehe der Nutzer eine Liste, die etwas
        anderes zeigt als seine Auswahl behauptet.
        """
        status, daten = hole(
            client, "scope=big_games&season_from=2025&season_to=2025"
                    f"&position=all&limit=10&{query}")
        assert status == 400
        assert daten["error_key"] == "leaderboard.error.invalidOpponentCutoff"

    def test_ohne_angabe_gilt_die_weiteste_stufe(self, client):
        status, daten = hole(
            client, "scope=big_games&season_from=2025&season_to=2025"
                    "&position=all&limit=10")
        assert status == 200
        assert daten["opponent_cutoffs"]["uefa_max_rank"] == 30
        assert daten["opponent_cutoffs"]["fifa_max_rank"] == 20

    def test_die_huerde_gilt_nur_fuer_big_games(self, client):
        """Die normalen Datenbasen kennen den Begriff nicht."""
        status, daten = hole(client, "scope=club_all&season=2024&position=all"
                                     "&limit=10&uefa_max_rank=5")
        assert status == 400
        assert daten["error_key"] == "leaderboard.error.unknownParameter"


@echte_daten
class TestNutzlast:

    def test_die_liste_kommt_mit_den_feldern_der_anzeige(self, client):
        status, daten = hole(
            client, "scope=big_games&season_from=2025&season_to=2025"
                    "&position=all&limit=20")
        assert status == 200
        assert daten["available"] is True, daten.get("reason")
        assert len(daten["rows"]) == 20
        for zeile in daten["rows"]:
            for feld in ("rank", "player_id", "name", "team_name", "position",
                         "big_games", "minutes", "goals", "assists", "value"):
                assert feld in zeile, feld

    @pytest.mark.parametrize("limit", [5, 10, 15, 20, 30])
    def test_die_anzahl_begrenzt_die_liste(self, client, limit):
        status, daten = hole(
            client, "scope=big_games&season_from=2025&season_to=2025"
                    f"&position=all&limit={limit}")
        assert status == 200
        assert len(daten["rows"]) <= limit

    def test_eine_engere_huerde_liefert_eine_andere_liste(self, client):
        _s, weit = hole(client, "scope=big_games&season_from=2025&season_to=2025"
                                "&position=all&limit=20&uefa_max_rank=30&fifa_max_rank=20")
        _s, eng = hole(client, "scope=big_games&season_from=2025&season_to=2025"
                               "&position=all&limit=20&uefa_max_rank=5&fifa_max_rank=10")
        assert weit["available"] and eng["available"]
        assert eng["coverage"]["eligible"] < weit["coverage"]["eligible"]
        # Nicht nur eine andere Beschriftung: dieselben Spieler haben
        # unter der engeren Huerde weniger Big Games.
        weit_bg = {z["player_id"]: z["big_games"] for z in weit["rows"]}
        eng_bg = {z["player_id"]: z["big_games"] for z in eng["rows"]}
        gemeinsam = set(weit_bg) & set(eng_bg)
        assert gemeinsam
        assert any(eng_bg[p] < weit_bg[p] for p in gemeinsam)

    def test_keine_privaten_rangdaten_in_der_antwort(self, client):
        _s, daten = hole(client, "scope=big_games&season_from=2025&season_to=2025"
                                 "&position=all&limit=30")
        text = json.dumps(daten)
        for verboten in ("opponent_rank", "coefficient", "strength", '"weight"'):
            assert verboten not in text, verboten


# ---------------------------------------------------------------------------
# Oberflaeche: Markup und Skript
# ---------------------------------------------------------------------------

class TestOberflaeche:

    def test_die_beiden_gegnerfelder_stehen_im_markup(self):
        html = _read("templates", "index.html")
        assert 'id="pc-lb-uefa"' in html
        assert 'id="pc-lb-fifa"' in html
        # Und sie liegen in der bestehenden Filterzeile, nicht in einem
        # neuen Block - die Seite wird nicht umgebaut.
        assert html.index('id="pc-lb-uefa-field"') < html.index('id="pc-lb-limit"')

    def test_die_vorhandenen_bedienelemente_bleiben(self):
        html = _read("templates", "index.html")
        for kennung in ('id="pc-lb-limit"', 'id="pc-lb-generate"',
                        'id="bg-season-from"', 'id="bg-season-to"',
                        'id="pc-lb-bg-metric"', 'id="pc-lb-result"'):
            assert kennung in html, kennung

    def test_die_huerden_gehen_an_den_server(self):
        """Kein Nachfiltern im Browser - die Auswahl wird mitgeschickt."""
        js = _read("static", "script.js")
        assert 'params.set("uefa_max_rank"' in js
        assert 'params.set("fifa_max_rank"' in js

    def test_die_stufen_kommen_aus_dem_katalog(self):
        js = _read("static", "script.js")
        assert "pcLbFillOpponentCutoffs" in js
        assert "uefa_max_ranks" in js and "fifa_max_ranks" in js

    def test_tore_und_vorlagen_stehen_in_der_zeile(self):
        js = _read("static", "script.js")
        assert "leaderboard.goalsAssists" in js

    def test_beide_sprachen_kennen_die_neuen_texte(self):
        for sprache in ("de", "en"):
            texte = json.loads(_read("static", "i18n", f"{sprache}.json"))
            for schluessel in ("leaderboard.clubOpponent",
                               "leaderboard.nationalOpponent",
                               "leaderboard.uefaTop", "leaderboard.fifaTop",
                               "leaderboard.goalsAssists"):
                assert schluessel in texte, (sprache, schluessel)


class TestBereichsnavigation:
    """Der aktive Reiter fuehrt an den Anfang seines Bereichs."""

    def test_der_aktive_reiter_setzt_den_bereich_zurueck(self):
        js = _read("static", "script.js")
        assert "function resetAreaToRoot" in js
        # Der Klickpfad unterscheidet aktiven und fremden Reiter.
        assert "state.activeArea === area" in js
        assert "resetAreaToRoot(area)" in js

    def test_der_wechsel_in_einen_anderen_bereich_bleibt_wie_er_war(self):
        js = _read("static", "script.js")
        assert "navigateToArea(area)" in js
        assert "window.history.pushState({ footsimArea: area }" in js

    def test_der_ruecksetzer_erzeugt_keinen_history_eintrag(self):
        """
        Der Bereich bleibt derselbe - ein zusaetzlicher Eintrag wuerde die
        Zurueck-Taste mit Stationen fuellen, die niemand besucht hat.
        """
        js = _read("static", "script.js")
        start = js.index("function resetAreaToRoot")
        ende = js.index("\n}", start)
        rumpf = js[start:ende]
        assert "pushState" not in rumpf
        assert "replaceState" not in rumpf

    def test_der_ruecksetzer_benutzt_die_vorhandenen_schliesswege(self):
        """Kein zweiter Weg, eine Ansicht zu verlassen."""
        js = _read("static", "script.js")
        start = js.index("function resetAreaToRoot")
        ende = js.index("\n}", start)
        rumpf = js[start:ende]
        for schliesser in ("pdClose()", "tdClose()", "mcClose()"):
            assert schliesser in rumpf, schliesser

    def test_die_vier_bereiche_bleiben_unveraendert(self):
        js = _read("static", "script.js")
        assert 'const AREAS = ["simulation", "compare", "live", "players"]' in js
        html = _read("templates", "index.html")
        assert html.count('class="area-btn') == 4
        assert html.count('class="bottom-nav-btn') == 4
