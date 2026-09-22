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

from tests.big_games_v2_welt import big_games_welt  # noqa: F401

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


# GEAENDERT FUER DIE CI: Diese Tests liefen gegen den ECHTEN gesammelten
# Datensatz. Auf einem frischen Checkout fehlen die bewusst
# unversionierten UEFA-/FIFA-Snapshots; die Route antwortete deshalb
# voellig richtig mit "snapshot_missing" bzw. wies die Saison ab - und
# die Tests scheiterten an der Umgebung statt an der Anwendung.
#
# Jetzt liegt unter jedem dieser Tests die synthetische Welt aus
# tests/big_games_v2_welt.py: eigene Snapshots, eigener Datensatz,
# eigenes Artefakt. Dieselbe Route, derselbe Rechenweg, keine private
# Datei. Dass die Route OHNE Grundlage geschlossen bleibt, prueft
# TestFailClosed am Ende dieser Datei.


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


@pytest.mark.usefixtures("big_games_welt")
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


@pytest.mark.usefixtures("big_games_welt")
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


# ---------------------------------------------------------------------------
# Fail closed ueber die Route
# ---------------------------------------------------------------------------
#
# Genau der Zustand, in dem die CI die frueheren Tests scheitern liess -
# hier ausdruecklich als gewolltes Verhalten festgehalten. Die Route darf
# ohne belegte Grundlage KEINE Liste liefern, und kein Testaufbau darf
# das umgehen.


class TestFailClosed:

    def test_ohne_snapshots_liefert_die_route_keine_liste(
            self, client, tmp_path, monkeypatch):
        from tests import big_games_v2_welt as welt
        from src.data import fifa_rankings
        from src.data import uefa_coefficients as uc

        welt.baue(tmp_path, monkeypatch)
        monkeypatch.setattr(uc, "COEFFICIENT_DIR", str(tmp_path / "weg"))
        monkeypatch.setattr(fifa_rankings, "FIFA_RANKING_DIR", str(tmp_path / "weg"))
        uc.clear_cache()
        fifa_rankings.clear_cache()

        status, daten = hole(
            client, "scope=big_games&season_from=2025&season_to=2025"
                    "&position=all&limit=10")
        # Ohne Snapshot kennt die Route die Saison gar nicht mehr; liegt
        # sie doch im Bereich, bleibt die Liste als nicht verfuegbar
        # gekennzeichnet. Beides ist geschlossen - nie eine Liste.
        if status == 200:
            assert daten["available"] is False
            assert daten["rows"] == []
        else:
            assert status == 400
            assert daten["error_key"] == "leaderboard.error.invalidSeason"

    def test_ohne_datensatz_bleibt_die_route_geschlossen(
            self, client, tmp_path, monkeypatch):
        """Snapshots allein genuegen nicht."""
        from tests import big_games_v2_welt as welt
        from src.data import big_games_dataset as bgd
        from src.data import big_games_public as bgp

        welt.baue(tmp_path, monkeypatch, mit_artefakt=False)
        monkeypatch.setattr(bgd, "DATASET_DIR", str(tmp_path / "leer"))
        monkeypatch.setattr(bgp, "PUBLIC_DIR", str(tmp_path / "leer"))
        bgd.clear_document_memo()

        status, daten = hole(
            client, "scope=big_games&season_from=2025&season_to=2025"
                    "&position=all&limit=10")
        assert status == 200
        assert daten["available"] is False
        assert daten["reason"] == bgd.REASON_DATASET_MISSING
        assert daten["rows"] == []


# ---------------------------------------------------------------------------
# Detailroute: /api/big-games/player-matches
# ---------------------------------------------------------------------------

def detail(client, query):
    antwort = client.get(f"/api/big-games/player-matches?{query}")
    return antwort.status_code, antwort.get_json()


@pytest.mark.usefixtures("big_games_welt")
class TestDetailRoute:

    def _erster_spieler(self, client, uefa=30, fifa=20):
        _s, liste = hole(
            client, "scope=big_games&season_from=2025&season_to=2025"
                    f"&position=all&limit=10&uefa_max_rank={uefa}&fifa_max_rank={fifa}")
        return liste["rows"][0]

    def test_eine_zeile_laesst_sich_aufschluesseln(self, client):
        zeile = self._erster_spieler(client)
        status, daten = detail(
            client, f"player_id={zeile['player_id']}"
                    "&season_from=2025&season_to=2025"
                    "&uefa_max_rank=30&fifa_max_rank=20")
        assert status == 200
        assert daten["available"] is True, daten.get("reason")
        assert len(daten["matches"]) == zeile["big_games"]
        assert daten["summary"]["big_games"] == zeile["big_games"]
        for feld in ("player_id", "name", "team_name", "position"):
            assert feld in daten["player"], feld

    @pytest.mark.parametrize("uefa,fifa", [(30, 20), (20, 15), (5, 10)])
    def test_die_huerde_gilt_auch_im_auszug(self, client, uefa, fifa):
        """Zeile und Auszug muessen unter JEDER Huerde dasselbe zaehlen."""
        zeile = self._erster_spieler(client, uefa, fifa)
        _status, daten = detail(
            client, f"player_id={zeile['player_id']}"
                    "&season_from=2025&season_to=2025"
                    f"&uefa_max_rank={uefa}&fifa_max_rank={fifa}")
        assert daten["opponent_cutoffs"]["uefa_max_rank"] == uefa
        assert daten["opponent_cutoffs"]["fifa_max_rank"] == fifa
        assert len(daten["matches"]) == zeile["big_games"]

    def test_die_partien_tragen_die_erzaehlbaren_felder(self, client):
        zeile = self._erster_spieler(client)
        _s, daten = detail(
            client, f"player_id={zeile['player_id']}"
                    "&season_from=2025&season_to=2025")
        for partie in daten["matches"]:
            for feld in ("fixture_id", "date", "competition", "opponent_name",
                         "is_home", "goals_for", "goals_against", "minutes",
                         "goals", "assists", "rating"):
                assert feld in partie, feld

    @pytest.mark.parametrize("query,schluessel", [
        ("player_id=abc&season_from=2025&season_to=2025",
         "leaderboard.error.invalidPlayer"),
        ("player_id=0&season_from=2025&season_to=2025",
         "leaderboard.error.invalidPlayer"),
        ("player_id=5&season_from=2025",
         "leaderboard.error.invalidSeason"),
        ("player_id=5&season_from=2025&season_to=2025&uefa_max_rank=7",
         "leaderboard.error.invalidOpponentCutoff"),
        ("player_id=5&season_from=2025&season_to=2025&fifa_max_rank=30",
         "leaderboard.error.invalidOpponentCutoff"),
        ("player_id=5&season_from=2025&season_to=2025&unsinn=1",
         "leaderboard.error.unknownParameter"),
    ])
    def test_ungueltiges_wird_abgewiesen(self, client, query, schluessel):
        status, daten = detail(client, query)
        assert status == 400
        assert daten["error_key"] == schluessel

    def test_ein_unbekannter_spieler_erfindet_nichts(self, client):
        status, daten = detail(
            client, "player_id=999999999&season_from=2025&season_to=2025")
        assert status == 200
        assert daten["available"] is False
        assert daten["reason"] == "player_not_in_dataset"
        assert daten["matches"] == []

    def test_keine_privaten_rangdaten_in_der_antwort(self, client):
        zeile = self._erster_spieler(client)
        _s, daten = detail(
            client, f"player_id={zeile['player_id']}"
                    "&season_from=2025&season_to=2025")
        text = json.dumps(daten)
        for verboten in ("opponent_rank", "opponent_coefficient", "coefficient",
                         "strength", '"weight"', "importance", "opponent_band"):
            assert verboten not in text, verboten

    def test_ohne_datensatz_bleibt_der_auszug_zu(self, client, tmp_path, monkeypatch):
        from src.data import big_games_dataset as bgd
        from src.data import big_games_public as bgp

        zeile = self._erster_spieler(client)
        monkeypatch.setattr(bgd, "DATASET_DIR", str(tmp_path / "leer"))
        monkeypatch.setattr(bgp, "PUBLIC_DIR", str(tmp_path / "leer"))
        bgd.clear_document_memo()

        status, daten = detail(
            client, f"player_id={zeile['player_id']}"
                    "&season_from=2025&season_to=2025")
        assert status == 200
        assert daten["available"] is False
        assert daten["reason"] == bgd.REASON_DATASET_MISSING


class TestDetailOberflaeche:

    def test_der_detailknopf_steht_in_der_zeile(self):
        js = _read("static", "script.js")
        assert "pc-lb-details" in js
        assert "leaderboard.detailsAria" in js

    def test_die_identitaet_oeffnet_denselben_auszug(self):
        js = _read("static", "script.js")
        start = js.index("function pcLbBuildRow(")
        block = js[start:js.index("\n}", start)]
        # Beide Wege rufen dieselbe Handlung auf.
        assert block.count("bgDetailOpen(row, data") >= 2
        # Die Identitaet ist ein echter Knopf, kein klickbares div.
        assert 'make("button", "pc-lb-info pc-lb-open")' in block

    def test_spieler_a_und_b_bleiben_geschwister(self):
        """
        Kein verschachteltes Bedienelement: A/B haengen an der Zeile,
        nicht am Identitaetsknopf. Sonst waere das Markup ungueltig - und
        ein Tipp auf A/B wuerde den Auszug mitoeffnen.
        """
        js = _read("static", "script.js")
        start = js.index("function pcLbBuildRow(")
        block = js[start:js.index("\n}", start)]
        assert "actions.appendChild(button)" in block
        assert "item.appendChild(actions)" in block
        assert "info.appendChild(actions)" not in block

    def test_der_dialog_ist_als_dialog_ausgezeichnet(self):
        html = _read("templates", "index.html")
        assert 'id="bg-detail"' in html
        assert 'role="dialog"' in html
        assert 'aria-modal="true"' in html
        assert 'aria-labelledby="bg-detail-name"' in html

    def test_der_auszug_erzeugt_keinen_history_eintrag(self):
        js = _read("static", "script.js")
        start = js.index("async function bgDetailOpen(")
        block = js[start:js.index("\nfunction bgDetailRenderUnavailable", start)]
        assert "pushState" not in block
        assert "replaceState" not in block

    def test_der_aktive_reiter_schliesst_den_auszug(self):
        js = _read("static", "script.js")
        start = js.index("function resetAreaToRoot(")
        block = js[start:js.index("\n}", start)]
        assert "bgDetailClose()" in block

    def test_ein_filterwechsel_entwertet_den_auszug(self):
        js = _read("static", "script.js")
        start = js.index("function pcLbOnFilterChange(")
        block = js[start:js.index("\n}", start)]
        assert "bgDetailClose()" in block

    def test_veraltete_antworten_werden_verworfen(self):
        js = _read("static", "script.js")
        assert "AbortController" in js
        start = js.index("async function bgDetailOpen(")
        block = js[start:js.index("\nfunction bgDetailRenderUnavailable", start)]
        assert "requestId !== bgDetailState.requestId" in block

    def test_beide_sprachen_kennen_die_neuen_texte(self):
        for sprache in ("de", "en"):
            texte = json.loads(_read("static", "i18n", f"{sprache}.json"))
            for schluessel in ("leaderboard.details", "leaderboard.detailsAria",
                               "bigGames.detail.title", "bigGames.detail.loading",
                               "bigGames.detail.unavailable", "bigGames.detail.empty",
                               "bigGames.detail.close", "bigGames.detail.moreMatches",
                               "bigGames.detail.home", "bigGames.detail.away"):
                assert schluessel in texte, (sprache, schluessel)

    def test_der_cache_wurde_erhoeht(self):
        """Ohne Sprung liefe neues Markup gegen altes Skript."""
        sw = _read("static", "sw.js")
        assert 'const CACHE_NAME = "footsim-v44"' in sw


# ---------------------------------------------------------------------------
# Big-Game-Definition ueber die Schnittstelle
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("big_games_welt")
class TestDefinitionRoute:

    BASIS = ("scope=big_games&season_from=2025&season_to=2025"
             "&position=all&limit=10")

    def test_ohne_angabe_antwortet_die_kontextuelle_liste(self, client):
        """Alte Lesezeichen und alte Clients duerfen sich nicht aendern."""
        status, ohne = hole(client, self.BASIS)
        assert status == 200
        assert ohne["opponent_cutoffs"]["big_game_mode"] == "contextual"
        _s, mit = hole(client, self.BASIS + "&big_game_mode=contextual")
        assert mit["rows"] == ohne["rows"]

    def test_streng_ist_eine_andere_und_kleinere_frage(self, client):
        _s, kontext = hole(client, self.BASIS + "&big_game_mode=contextual")
        status, streng = hole(client, self.BASIS + "&big_game_mode=strict")
        assert status == 200
        assert streng["opponent_cutoffs"]["big_game_mode"] == "strict"
        assert streng["coverage"]["eligible"] <= kontext["coverage"]["eligible"]

    @pytest.mark.parametrize("mode", ["streng", "STRICT", "", "alles"])
    def test_eine_unbekannte_definition_wird_abgewiesen(self, client, mode):
        """
        Kein stiller Rueckfall: wer ausdruecklich etwas anderes verlangt,
        bekommt einen Fehler statt einer Liste, die er nicht gemeint hat.
        """
        status, daten = hole(client, self.BASIS + "&big_game_mode=" + mode)
        assert status == 400
        assert daten["error_key"] == "leaderboard.error.invalidMode"
        assert daten["allowed_modes"] == ["contextual", "strict"]

    def test_die_huerde_wirkt_auch_im_strengen_modus(self, client):
        _s, eng = hole(client, self.BASIS
                       + "&big_game_mode=strict&uefa_max_rank=5&fifa_max_rank=5")
        _s, weit = hole(client, self.BASIS
                        + "&big_game_mode=strict&uefa_max_rank=30&fifa_max_rank=20")
        assert eng["opponent_cutoffs"]["uefa_max_rank"] == 5
        assert eng["coverage"]["eligible"] <= weit["coverage"]["eligible"]

    @pytest.mark.parametrize("mode", ["contextual", "strict"])
    def test_zeile_und_auszug_teilen_die_definition(self, client, mode):
        _s, liste = hole(client, self.BASIS + "&big_game_mode=" + mode
                         + "&uefa_max_rank=30&fifa_max_rank=20")
        assert liste["rows"]
        for zeile in liste["rows"][:5]:
            status, daten = detail(
                client, "player_id=%s&season_from=2025&season_to=2025"
                        "&uefa_max_rank=30&fifa_max_rank=20&big_game_mode=%s"
                        % (zeile["player_id"], mode))
            assert status == 200
            assert daten["opponent_cutoffs"]["big_game_mode"] == mode
            assert len(daten["matches"]) == zeile["big_games"]
            assert daten["summary"]["big_games"] == zeile["big_games"]

    def test_der_auszug_weist_dieselbe_unbekannte_definition_ab(self, client):
        status, daten = detail(
            client, "player_id=5&season_from=2025&season_to=2025"
                    "&big_game_mode=streng")
        assert status == 400
        assert daten["error_key"] == "leaderboard.error.invalidMode"

    def test_der_strenge_modus_verraet_keine_raenge(self, client):
        _s, liste = hole(client, self.BASIS + "&big_game_mode=strict")
        text = json.dumps(liste)
        for verboten in ("opponent_rank", "opponent_coefficient",
                         "coefficient", "opponent_band"):
            assert verboten not in text, verboten

    def test_ohne_snapshots_bleibt_auch_streng_zu(self, client, tmp_path,
                                                  monkeypatch):
        """Fail-Closed gilt unveraendert fuer beide Definitionen."""
        from src.data import fifa_rankings
        from src.data import uefa_coefficients as uc

        monkeypatch.setattr(uc, "COEFFICIENT_DIR", str(tmp_path / "weg"))
        monkeypatch.setattr(fifa_rankings, "FIFA_RANKING_DIR", str(tmp_path / "weg"))
        uc.clear_cache()
        fifa_rankings.clear_cache()

        status, daten = hole(client, self.BASIS + "&big_game_mode=strict")
        # Wie oben in TestFailClosed: entweder kennt die Route die Saison
        # ohne Snapshot gar nicht mehr, oder die Liste bleibt als nicht
        # verfuegbar gekennzeichnet. Nie eine Liste.
        if status == 200:
            assert daten["available"] is False
            assert daten["rows"] == []
        else:
            assert status == 400
            assert daten["error_key"] == "leaderboard.error.invalidSeason"


class TestDefinitionOberflaeche:

    def test_die_liste_bietet_beide_definitionen_an(self):
        html = _read("templates", "index.html")
        assert 'id="pc-lb-mode"' in html
        assert 'id="pc-lb-mode-field"' in html
        js = _read("static", "script.js")
        assert '"contextual"' in js and '"strict"' in js

    def test_kontextuell_ist_die_voreinstellung(self):
        js = _read("static", "script.js")
        start = js.index("leaderboard: {")
        block = js[start:js.index("}", start)]
        assert 'bigGameMode: "contextual"' in block

    def test_die_huerden_gehoeren_nur_zur_strengen_frage(self):
        """
        Kontextuell sagt die Huerde nichts aus - ein sichtbares, aber
        wirkungsloses Feld waere eine Luege ueber die Antwort.
        """
        html = _read("templates", "index.html")
        assert html.count("pc-lb-strict-only") == 2
        js = _read("static", "script.js")
        start = js.index("function pcLbSyncFields(")
        block = js[start:js.index("\n}", start)]
        assert 'bigGameMode === "strict"' in block
        assert "uefaField" in block and "fifaField" in block

    def test_eine_kontextuelle_anfrage_traegt_keine_alte_huerde(self):
        """
        Nach einem Wechsel stehen in den versteckten Feldern noch die
        strengen Werte. Sie duerfen die kontextuelle Antwort nicht
        heimlich verengen.
        """
        js = _read("static", "script.js")
        start = js.index("function pcLbBuildParams(")
        block = js[start:js.index("\n}", start)]
        assert 'params.set("big_game_mode"' in block
        assert 'lb.bigGameMode === "strict"' in block
        vor_huerde = block.index("uefa_max_rank")
        assert block.index('lb.bigGameMode === "strict"') < vor_huerde

    def test_der_auszug_folgt_der_beantworteten_frage(self):
        """
        Massgeblich ist der Modus AUS DER ANTWORT, nicht der gerade im
        Bedienfeld stehende - sonst zerfaellt Zeile und Auszug.
        """
        js = _read("static", "script.js")
        start = js.index("async function bgDetailOpen(")
        block = js[start:js.index("\nfunction bgDetailRenderUnavailable", start)]
        assert "cutoffs.big_game_mode" in block

    def test_ein_wechsel_entwertet_den_offenen_auszug(self):
        js = _read("static", "script.js")
        start = js.index('nodes.mode.addEventListener')
        block = js[start:js.index("});", start)]
        assert "pcLbSyncFields()" in block
        assert "pcLbOnFilterChange()" in block

    def test_beide_sprachen_kennen_die_neuen_texte(self):
        for sprache in ("de", "en"):
            texte = json.loads(_read("static", "i18n", f"{sprache}.json"))
            for schluessel in ("leaderboard.bigGameMode",
                               "leaderboard.mode.contextual",
                               "leaderboard.mode.strict",
                               "leaderboard.mode.contextualHint",
                               "leaderboard.mode.strictHint",
                               "leaderboard.error.invalidMode"):
                assert schluessel in texte, (sprache, schluessel)
