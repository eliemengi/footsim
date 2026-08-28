"""
Regressionstests fuer die Spieltagsfreischaltung der nationalen Ligen.

WARUM DIESE DATEI
-----------------
Die freigeschalteten Spieltage sind eine Produktentscheidung, die an
GENAU EINER Stelle steht: LEAGUE_CONFIG[<code>]["unlocked_matchdays"] in
app.py. Backend (is_matchday_unlocked, /api/matchdays, /api/matches) und
Frontend (static/script.js) lesen ausschliesslich diese Quelle.

Genau das ist die Gefahr: Wird die Liste erweitert, faellt eine zweite,
parallel gepflegte Sperre nicht auf - der gesperrte Spieltag waere
weiterhin gesperrt, ohne dass ein Test es meldet. Diese Datei nagelt
deshalb beide Richtungen fest: was offen sein MUSS und was zu SEIN hat.

HERMETISCH
----------
Kein Test hier haengt an einer Live-API-Antwort. Zwei Punkte machen das
moeglich:

  * is_matchday_unlocked(code, tag, season=None) ruft is_current_season
    gar nicht erst auf - ohne Saisonangabe gilt die laufende Saison.
    Diese Aufrufe sind damit von sich aus netzfrei.
  * Wo eine Route doch get_season_info/is_current_season braucht, werden
    beide gepatcht. Ein Test, der bei ausgefallenem Anbieter rot wird,
    misst den Anbieter und nicht die Freischaltung.
"""

import os
import re

import pytest


ERWARTETE_FREISCHALTUNG = {
    "bl1": [1, 2, 3],
    "pl": [1, 2, 3, 4, 5],
    "pd": [1, 2, 3, 4, 5],
    "sa": [1, 2, 3, 4, 5],
    "fl1": [1, 2, 3],
}

# Die erwartete Gesamtlaenge je Liga. Steht hier, damit ein
# versehentlich veraendertes total_matchdays nicht unbemerkt bleibt -
# es bestimmt zugleich, wie viele Spieltage /api/matchdays ausliefert.
ERWARTETE_GESAMTSPIELTAGE = {
    "bl1": 34, "pl": 38, "pd": 38, "sa": 38, "fl1": 34,
}


@pytest.fixture
def app_module():
    import app as app_module
    return app_module


@pytest.fixture
def client(monkeypatch, app_module):
    monkeypatch.setenv("APISPORTS_KEY", "test-key")
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# 1. Die Konfiguration selbst
# ---------------------------------------------------------------------------

class TestFreischaltungKonfiguration:
    @pytest.mark.parametrize("code,erwartet", sorted(ERWARTETE_FREISCHALTUNG.items()))
    def test_liga_hat_erwartete_spieltage(self, app_module, code, erwartet):
        assert app_module.LEAGUE_CONFIG[code]["unlocked_matchdays"] == erwartet

    def test_champions_league_bleibt_unveraendert(self, app_module):
        """Die CL-Ligaphase ist ein eigener, spaeterer Schritt."""
        assert app_module.CL_LEAGUE_PHASE_CONFIG["unlocked_matchdays"] == [1]
        assert app_module.CL_LEAGUE_PHASE_CONFIG["total_matchdays"] == 8

    def test_globaler_schalter_bleibt_aus(self, app_module):
        """
        Mit UNLOCK_ALL_MATCHDAYS=True waere jeder Sperrtest hier
        bedeutungslos - er wuerde die Sperre nie erreichen.
        """
        assert app_module.UNLOCK_ALL_MATCHDAYS is False

    def test_keine_saisonerzwingung(self, app_module):
        assert app_module.SEASON_OVERRIDE is None

    @pytest.mark.parametrize("code,gesamt", sorted(ERWARTETE_GESAMTSPIELTAGE.items()))
    def test_gesamtspieltage_unveraendert(self, app_module, code, gesamt):
        """Freischalten darf die Laenge der Saison nicht anfassen."""
        assert app_module.LEAGUE_CONFIG[code]["total_matchdays"] == gesamt

    def test_keine_liga_uebersehen(self, app_module):
        """
        Die Erwartungstabellen oben muessen ALLE Ligen abdecken. Kaeme
        eine sechste Liga dazu, liefe sie sonst voellig ungeprueft mit.
        """
        assert set(app_module.LEAGUE_CONFIG) == set(ERWARTETE_FREISCHALTUNG)
        assert set(app_module.LEAGUE_CONFIG) == set(ERWARTETE_GESAMTSPIELTAGE)


# ---------------------------------------------------------------------------
# 2. is_matchday_unlocked - die Funktion, an der alles haengt
# ---------------------------------------------------------------------------

class TestIsMatchdayUnlocked:
    @pytest.mark.parametrize("code,tag", sorted(
        (code, max(tage)) for code, tage in ERWARTETE_FREISCHALTUNG.items()
    ))
    def test_letzter_freigeschalteter_tag_ist_offen(self, app_module, code, tag):
        assert app_module.is_matchday_unlocked(code, tag, None) is True

    @pytest.mark.parametrize("code,tag", sorted(
        (code, max(tage) + 1) for code, tage in ERWARTETE_FREISCHALTUNG.items()
    ))
    def test_erster_gesperrter_tag_bleibt_zu(self, app_module, code, tag):
        """
        Die Gegenprobe zum Test darueber. Ohne sie wuerde ein
        versehentliches list(range(1, 39)) unbemerkt durchgehen.
        """
        assert app_module.is_matchday_unlocked(code, tag, None) is False

    @pytest.mark.parametrize("code", sorted(ERWARTETE_FREISCHALTUNG))
    def test_erster_spieltag_bleibt_offen(self, app_module, code):
        """Bereits gespielte Spieltage duerfen nie zufallen."""
        assert app_module.is_matchday_unlocked(code, 1, None) is True

    @pytest.mark.parametrize("code,tage", sorted(ERWARTETE_FREISCHALTUNG.items()))
    def test_jeder_konfigurierte_tag_ist_offen(self, app_module, code, tage):
        for tag in tage:
            assert app_module.is_matchday_unlocked(code, tag, None) is True

    def test_unbekannter_wettbewerb_bleibt_gesperrt(self, app_module):
        assert app_module.is_matchday_unlocked("gibtesnicht", 1, None) is False


# ---------------------------------------------------------------------------
# 3. Historische Saisons - unveraendertes Verhalten
# ---------------------------------------------------------------------------

class TestHistorischeSaison:
    def test_abgeschlossene_saison_gibt_alles_frei(self, app_module, monkeypatch):
        """
        Bei einer vergangenen Saison ist jede Partie laengst gespielt.
        Eine Sperre waere dort sinnlos - und dieses Verhalten darf die
        Freischaltung der laufenden Saison nicht beruehrt haben.
        """
        monkeypatch.setattr(app_module, "is_current_season", lambda api_code, season: False)
        for code in ERWARTETE_FREISCHALTUNG:
            gesamt = app_module.LEAGUE_CONFIG[code]["total_matchdays"]
            assert app_module.is_matchday_unlocked(code, gesamt, 2024) is True

    def test_laufende_saison_greift_weiterhin_die_sperre(self, app_module, monkeypatch):
        monkeypatch.setattr(app_module, "is_current_season", lambda api_code, season: True)
        assert app_module.is_matchday_unlocked("bl1", 4, 2026) is False
        assert app_module.is_matchday_unlocked("pl", 6, 2026) is False
        assert app_module.is_matchday_unlocked("bl1", 3, 2026) is True
        assert app_module.is_matchday_unlocked("pl", 5, 2026) is True


# ---------------------------------------------------------------------------
# 4. /api/matchdays - was das Frontend tatsaechlich bekommt
# ---------------------------------------------------------------------------

def _patch_saison(app_module, monkeypatch, matchday=1):
    """
    Saisonauskunft festnageln, damit kein Test ans Netz geht.

    get_current_season MUSS mitgepatcht werden, auch wenn die Routen es
    nicht sichtbar aufrufen: /api/status geht ueber build_season_options,
    und das fragt get_current_season(SEASON_REFERENCE_CODE). Ohne diesen
    Patch holte der Test die Bundesliga-Saison live vom Anbieter und
    schrieb sie in den Plattencache - ein Test, der Netz braucht und
    dabei Produktionsdaten anfasst.
    """
    monkeypatch.setattr(app_module, "get_season_info", lambda api_code: {
        "season": 2026, "current_matchday": matchday,
        "start_date": "2026-08-28", "end_date": "2027-05-22",
        "auto_detected": True,
    })
    monkeypatch.setattr(app_module, "is_current_season", lambda api_code, season: True)
    monkeypatch.setattr(app_module, "get_current_season", lambda api_code: 2026)


class TestApiMatchdays:
    @pytest.mark.parametrize("code,tage", sorted(ERWARTETE_FREISCHALTUNG.items()))
    def test_route_spiegelt_die_konfiguration(self, client, app_module, monkeypatch, code, tage):
        _patch_saison(app_module, monkeypatch)

        antwort = client.get(f"/api/matchdays?competition={code}")
        assert antwort.status_code == 200
        tage_json = antwort.get_json()

        assert len(tage_json) == app_module.LEAGUE_CONFIG[code]["total_matchdays"]

        offen = [t["matchday"] for t in tage_json if t["available"]]
        assert offen == tage

    def test_gesperrte_tage_bleiben_sichtbar(self, client, app_module, monkeypatch):
        """
        Gesperrt heisst nicht unsichtbar: die Zelle wird angezeigt und
        traegt eine Begruendung. Faellt sie ganz weg, ist die Navigation
        kaputt, obwohl jeder Freischaltungstest gruen bliebe.
        """
        _patch_saison(app_module, monkeypatch)

        tage_json = client.get("/api/matchdays?competition=bl1").get_json()
        gesperrt = [t for t in tage_json if not t["available"]]

        assert len(gesperrt) == 31
        assert all(t["message"] for t in gesperrt)
        assert gesperrt[0]["matchday"] == 4


# ---------------------------------------------------------------------------
# 5. /api/matches - Begegnungen eines freigeschalteten Spieltags
# ---------------------------------------------------------------------------

BEGEGNUNGEN = [
    {"match_id": 1, "home_team": "FC Bayern", "away_team": "RB Leipzig",
     "home_id": 5, "away_id": 721},
]


class TestApiMatches:
    def test_bl1_spieltag_3_liefert_begegnungen(self, client, app_module, monkeypatch):
        gerufen = {}

        def fake_options(competition_code, api_code, matchday, season):
            gerufen.update(code=competition_code, matchday=matchday)
            return BEGEGNUNGEN

        monkeypatch.setattr(app_module, "get_matchday_match_options", fake_options)

        antwort = client.get("/api/matches?competition=bl1&matchday=3")
        assert antwort.status_code == 200
        assert antwort.get_json() == BEGEGNUNGEN
        assert gerufen == {"code": "bl1", "matchday": 3}

    @pytest.mark.parametrize("code,tag", sorted(
        (code, max(tage)) for code, tage in ERWARTETE_FREISCHALTUNG.items()
    ))
    def test_freigeschalteter_tag_erreicht_den_loader(self, client, app_module, monkeypatch, code, tag):
        monkeypatch.setattr(
            app_module, "get_matchday_match_options",
            lambda **kwargs: BEGEGNUNGEN,
        )
        antwort = client.get(f"/api/matches?competition={code}&matchday={tag}")
        assert antwort.status_code == 200
        assert antwort.get_json() == BEGEGNUNGEN

    @pytest.mark.parametrize("code,tag", sorted(
        (code, max(tage) + 1) for code, tage in ERWARTETE_FREISCHALTUNG.items()
    ))
    def test_gesperrter_tag_ruft_den_loader_gar_nicht(self, client, app_module, monkeypatch, code, tag):
        """
        Eine Sperre, die trotzdem die API befragt, kostet Kontingent und
        laesst Daten durchsickern. Deshalb wird hier nicht nur die leere
        Antwort geprueft, sondern dass der Loader unberuehrt bleibt.
        """
        def darf_nicht_laufen(**kwargs):
            raise AssertionError("Loader trotz gesperrtem Spieltag aufgerufen")

        monkeypatch.setattr(app_module, "get_matchday_match_options", darf_nicht_laufen)

        antwort = client.get(f"/api/matches?competition={code}&matchday={tag}")
        assert antwort.status_code == 200
        assert antwort.get_json() == []


# ---------------------------------------------------------------------------
# 6. Eine Quelle - Frontend wie Backend
# ---------------------------------------------------------------------------

class TestEineFreischaltungsquelle:
    @pytest.fixture
    def script_js(self):
        pfad = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "static", "script.js",
        )
        with open(pfad, encoding="utf-8") as f:
            return f.read()

    def test_frontend_hat_keine_eigene_freischaltung(self, script_js):
        assert "unlocked_matchdays" not in script_js
        assert not re.search(r"unlockedMatchdays|UNLOCKED_MATCHDAYS", script_js)

    def test_frontend_entscheidet_am_available_flag(self, script_js):
        """
        Das Frontend darf nur spiegeln, was das Backend sagt. Faellt
        diese Bindung weg, laeuft die Sperre auseinander.
        """
        assert "if (!day.available)" in script_js

    def test_status_route_meldet_dieselbe_quelle(self, client, app_module, monkeypatch):
        _patch_saison(app_module, monkeypatch)

        daten = client.get("/api/status").get_json()
        assert daten["unlock_all"] is False
        assert daten["season_override"] is None

        for code, tage in ERWARTETE_FREISCHALTUNG.items():
            assert daten["leagues"][code]["unlocked_matchdays"] == tage


# ---------------------------------------------------------------------------
# 7. Untertitel in /api/competitions - deutsch wie englisch
# ---------------------------------------------------------------------------

class TestVerfuegbarkeitsUntertitel:
    """
    Der Untertitel je Liga wird aus der Freischaltung gebildet. Er ist
    die einzige Stelle, an der ein Nutzer OHNE Klick sieht, wie viele
    Spieltage offen sind - eine stehengebliebene "Spieltag 1 verfuegbar"
    waere also sichtbar falsch, obwohl die Sperre selbst korrekt ist.
    """

    def _untertitel(self, client, sprache):
        antwort = client.get(f"/api/competitions?lang={sprache}")
        assert antwort.status_code == 200
        return {e["code"]: e["subtitle"] for e in antwort.get_json()}

    @pytest.mark.parametrize("code,tage", sorted(ERWARTETE_FREISCHALTUNG.items()))
    def test_deutsch(self, client, app_module, monkeypatch, code, tage):
        _patch_saison(app_module, monkeypatch)
        untertitel = self._untertitel(client, "de")
        assert untertitel[code] == f"Spieltag {min(tage)} bis {max(tage)} verfügbar"

    @pytest.mark.parametrize("code,tage", sorted(ERWARTETE_FREISCHALTUNG.items()))
    def test_englisch(self, client, app_module, monkeypatch, code, tage):
        _patch_saison(app_module, monkeypatch)
        untertitel = self._untertitel(client, "en")
        assert untertitel[code] == f"Matchdays {min(tage)} to {max(tage)} available"

    def test_ligue1_zeigt_die_neue_spanne(self, client, app_module, monkeypatch):
        """
        Ausdruecklich festgenagelt statt nur abgeleitet: Ligue 1 war bis
        zu dieser Aenderung die einzige Liga mit genau einem Spieltag und
        traf damit als einzige den Einzahl-Katalogeintrag.
        """
        _patch_saison(app_module, monkeypatch)
        assert self._untertitel(client, "de")["fl1"] == "Spieltag 1 bis 3 verfügbar"
        assert self._untertitel(client, "en")["fl1"] == "Matchdays 1 to 3 available"
