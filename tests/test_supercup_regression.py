"""
Supercups duerfen nicht wieder aus den Vereinsstatistiken fallen.

DIE VORGESCHICHTE
-----------------
Supercups fehlten in club_all. Arda Gueler hatte damit 38 statt 69
Minuten - die 31 Minuten aus dem spanischen Supercup zaehlten nicht mit.
Das war kein Rundungsfehler, sondern eine fehlende Kategorie: "Super Cup"
enthaelt das Wort "cup", ging in einer namensbasierten Zuordnung als
gewoehnlicher Pokal durch und fiel dann durch das Raster.

Repariert wurde es ueber die zentrale Taxonomie in
src/data/competition_taxonomy.py. Diese Datei haelt das Ergebnis fest -
und zwar fuer alle fuenf Ligen, nicht nur fuer die beiden, an denen der
Fehler auffiel.

DIE ZWEITE HAELFTE
------------------
Gleichzeitig duerfen Freundschaftsspiele NICHT in die Vereinsstatistiken
geraten. Beide Fehler sind Spiegelbilder voneinander: einmal fehlt ein
Pflichtspiel, einmal zaehlt ein Testspiel mit. Eine Reparatur, die nur
die eine Richtung prueft, laedt die andere geradezu ein.
"""

import pytest

from src.data.competition_taxonomy import (
    CLUB_FRIENDLY_IDS,
    CONTINENTAL_SUPERCUP_IDS,
    DOMESTIC_CUP_IDS,
    DOMESTIC_LEAGUE_IDS,
    DOMESTIC_SUPERCUP_IDS,
    NATIONAL_FRIENDLY_IDS,
    classify,
    is_club_competitive,
)
from src.data.player_compare_loader import (
    SCOPE_ALL,
    SCOPE_CLUB_ALL,
    SCOPE_LEAGUE,
    SCOPE_NATIONAL,
    build_player_profile,
    entry_matches_scope,
)

#: Die fuenf nationalen Supercups, jeweils mit ihrer Liga. Aus der
#: zentralen Taxonomie gelesen, NICHT hier noch einmal aufgeschrieben -
#: eine zweite Liste waere genau die Streuung, die den Fehler erzeugt hat.
SUPERCUPS = sorted(DOMESTIC_SUPERCUP_IDS.items())


def block(league_id, name="Wettbewerb", country="Spain", minutes=31,
          appearances=2, team="Testverein", season=2026):
    """Ein statistics-Block, wie ihn der Anbieter liefert."""
    return {
        "team": {"id": 1, "name": team},
        "league": {"id": league_id, "name": name, "country": country,
                   "season": season, "type": "Cup"},
        "games": {"minutes": minutes, "appearences": appearances,
                  "position": "Midfielder", "lineups": appearances},
        "goals": {"total": 0, "assists": 0},
    }


def profil_mit(bloecke, season=2026, scope=SCOPE_CLUB_ALL):
    roh = {"player": {"id": 1, "name": "Testspieler", "age": 21},
           "statistics": bloecke}
    return build_player_profile(roh, season, scope=scope)


# ---------------------------------------------------------------------------
# Die Taxonomie kennt alle fuenf
# ---------------------------------------------------------------------------

class TestAlleFuenfSupercupsSindBelegt:

    def test_es_sind_genau_fuenf(self):
        assert len(DOMESTIC_SUPERCUP_IDS) == 5

    @pytest.mark.parametrize("liga_id,eintrag", SUPERCUPS)
    def test_jeder_supercup_ist_ein_vereinspflichtspiel(self, liga_id, eintrag):
        land, _ = eintrag
        assert is_club_competitive({"id": liga_id, "name": "Super Cup",
                                    "country": land}) is True

    @pytest.mark.parametrize("liga_id,eintrag", SUPERCUPS)
    def test_jeder_supercup_wird_als_supercup_eingeordnet(self, liga_id, eintrag):
        land, _ = eintrag
        assert classify({"id": liga_id, "name": "Super Cup",
                         "country": land}) == "domestic_supercup"

    def test_jede_der_fuenf_ligen_hat_genau_einen(self):
        ligen = [liga for _, (_, liga) in SUPERCUPS]
        assert sorted(ligen) == sorted(DOMESTIC_LEAGUE_IDS.values())

    def test_der_uefa_supercup_zaehlt_ebenfalls(self):
        for liga_id in CONTINENTAL_SUPERCUP_IDS:
            assert is_club_competitive({"id": liga_id,
                                        "name": "UEFA Super Cup"}) is True

    def test_die_id_entscheidet_nicht_der_name(self):
        """
        Die belegten IDs schlagen jede Heuristik. Ein Wettbewerb mit
        irrefuehrendem Namen unter einer belegten ID bleibt richtig
        eingeordnet.
        """
        for liga_id, (land, _) in SUPERCUPS:
            assert classify({"id": liga_id, "name": "Irgendein Pokal",
                             "country": land}) == "domestic_supercup"


# ---------------------------------------------------------------------------
# Die Scopes
# ---------------------------------------------------------------------------

class TestSupercupInDenRichtigenScopes:

    @pytest.mark.parametrize("liga_id,eintrag", SUPERCUPS)
    def test_supercup_zaehlt_zu_club_all(self, liga_id, eintrag):
        land, _ = eintrag
        eintrag_block = block(liga_id, "Super Cup", land)
        assert entry_matches_scope(eintrag_block, SCOPE_CLUB_ALL) is True

    @pytest.mark.parametrize("liga_id,eintrag", SUPERCUPS)
    def test_supercup_zaehlt_zu_all(self, liga_id, eintrag):
        land, _ = eintrag
        eintrag_block = block(liga_id, "Super Cup", land)
        assert entry_matches_scope(eintrag_block, SCOPE_ALL) is True

    @pytest.mark.parametrize("liga_id,eintrag", SUPERCUPS)
    def test_supercup_zaehlt_NICHT_zu_league(self, liga_id, eintrag):
        """
        "Nur Liga" heisst nur Liga. Ein Supercup ist ein eigener
        Wettbewerb und gehoert dort nicht hinein - sonst waere die
        Ligastatistik keine Ligastatistik mehr.
        """
        land, _ = eintrag
        eintrag_block = block(liga_id, "Super Cup", land)
        assert entry_matches_scope(eintrag_block, SCOPE_LEAGUE) is False

    @pytest.mark.parametrize("liga_id,eintrag", SUPERCUPS)
    def test_supercup_zaehlt_NICHT_zu_national(self, liga_id, eintrag):
        land, _ = eintrag
        eintrag_block = block(liga_id, "Super Cup", land)
        assert entry_matches_scope(eintrag_block, SCOPE_NATIONAL) is False


class TestFriendliesBleibenDraussen:

    @pytest.mark.parametrize("liga_id", sorted(CLUB_FRIENDLY_IDS))
    def test_vereinstestspiel_zaehlt_nicht_zu_club_all(self, liga_id):
        """
        Die Spiegelseite des Supercup-Fehlers. Ein Testspiel darf die
        Vereinsstatistik nicht aufblaehen - sonst haette ein Spieler nach
        der Vorbereitung mehr "Pflichtminuten" als nach vier Spieltagen.
        """
        eintrag = block(liga_id, "Friendlies Clubs", "World", minutes=120)
        assert entry_matches_scope(eintrag, SCOPE_CLUB_ALL) is False

    @pytest.mark.parametrize("liga_id", sorted(CLUB_FRIENDLY_IDS))
    def test_vereinstestspiel_zaehlt_nicht_zu_league(self, liga_id):
        eintrag = block(liga_id, "Friendlies Clubs", "World")
        assert entry_matches_scope(eintrag, SCOPE_LEAGUE) is False

    @pytest.mark.parametrize("liga_id", sorted(NATIONAL_FRIENDLY_IDS))
    def test_laenderspieltestspiel_bleibt_im_nationalscope(self, liga_id):
        """
        Die Trennung ist wesentlich: Ein Klubtestspiel gehoert aus den
        Vereinsstatistiken heraus, ein Laenderspiel-Testspiel bleibt dort,
        wo es hingehoert.
        """
        eintrag = block(liga_id, "Friendlies", "World")
        assert entry_matches_scope(eintrag, SCOPE_NATIONAL) is True
        assert entry_matches_scope(eintrag, SCOPE_CLUB_ALL) is False

    def test_ein_testspiel_ist_kein_vereinspflichtspiel(self):
        for liga_id in CLUB_FRIENDLY_IDS:
            assert is_club_competitive({"id": liga_id,
                                        "name": "Friendlies Clubs"}) is False


# ---------------------------------------------------------------------------
# Die Rechnung, an der es aufgefallen ist
# ---------------------------------------------------------------------------

class TestDieAddition:

    def test_liga_plus_supercup_ergibt_club_all(self):
        """
        Der Fall, an dem der Fehler sichtbar wurde: 38 Ligaminuten plus 31
        Supercupminuten. club_all muss 69 ergeben, nicht 38.

        Kein Spielername, keine feste ID - die Rechnung gilt generisch.
        """
        bloecke = [
            block(140, "La Liga", "Spain", minutes=38, appearances=1),
            block(556, "Super Cup", "Spain", minutes=31, appearances=2),
        ]

        club_all = profil_mit(bloecke, scope=SCOPE_CLUB_ALL)
        nur_liga = profil_mit(bloecke, scope=SCOPE_LEAGUE)

        assert club_all["minutes"] == 69
        assert nur_liga["minutes"] == 38

    @pytest.mark.parametrize("liga_id,eintrag", SUPERCUPS)
    def test_die_addition_gilt_fuer_alle_fuenf_ligen(self, liga_id, eintrag):
        land, liga_code = eintrag
        liga_api_id = [k for k, v in DOMESTIC_LEAGUE_IDS.items()
                       if v == liga_code][0]

        bloecke = [
            block(liga_api_id, "Liga", land, minutes=38, appearances=1),
            block(liga_id, "Super Cup", land, minutes=31, appearances=2),
        ]
        assert profil_mit(bloecke, scope=SCOPE_CLUB_ALL)["minutes"] == 69

    def test_ein_testspiel_erhoeht_die_summe_nicht(self):
        bloecke = [
            block(140, "La Liga", "Spain", minutes=38, appearances=1),
            block(667, "Friendlies Clubs", "World", minutes=120, appearances=2),
        ]
        assert profil_mit(bloecke, scope=SCOPE_CLUB_ALL)["minutes"] == 38

    def test_pokal_und_supercup_zaehlen_beide(self):
        """Sie sind verschiedene Wettbewerbe und beide Pflichtspiele."""
        bloecke = [
            block(140, "La Liga", "Spain", minutes=38, appearances=1),
            block(143, "Copa del Rey", "Spain", minutes=90, appearances=1),
            block(556, "Super Cup", "Spain", minutes=31, appearances=2),
        ]
        assert profil_mit(bloecke, scope=SCOPE_CLUB_ALL)["minutes"] == 159

    def test_alle_nationalen_pokale_sind_vereinspflichtspiele(self):
        for liga_id in DOMESTIC_CUP_IDS:
            assert is_club_competitive({"id": liga_id, "name": "Pokal"}) is True


class TestKeineVerstreutenSonderlisten:
    """
    Der Fehler entstand, weil Wettbewerbe an mehreren Stellen anhand ihrer
    Namen eingeordnet wurden. Diese Tests halten fest, dass es jetzt eine
    Quelle gibt.
    """

    def test_die_taxonomie_ist_die_quelle_fuer_die_qualitaetseinstufung(self):
        from src.data.player_data_quality import club_minutes

        roh = {"player": {"id": 1},
               "statistics": [block(556, "Super Cup", "Spain", minutes=31)]}
        assert club_minutes(roh) == 31

    def test_die_taxonomie_ist_die_quelle_fuer_den_pooleintrag(self):
        from src.data.player_refetch import build_entry_from_raw

        roh = {"player": {"id": 1, "name": "Test", "age": 21},
               "statistics": [
                   block(140, "La Liga", "Spain", minutes=38, appearances=1),
                   block(556, "Super Cup", "Spain", minutes=31, appearances=2)]}

        eintrag = build_entry_from_raw(roh, 2026, "pd")
        assert eintrag["minutes_by_scope"]["club_all"] == 69
        assert eintrag["minutes_by_scope"]["league"] == 38

    def test_die_scopezuordnung_folgt_wirklich_der_taxonomie(self, monkeypatch):
        """
        Der schaerfste verfuegbare Nachweis, dass es nur EINE Quelle gibt.

        Ein erfundener Wettbewerb wird der Taxonomie voruebergehend als
        Supercup hinzugefuegt. Danach MUSS die Scopezuordnung ihn als
        Vereinspflichtspiel behandeln. Haette irgendein Modul noch seine
        eigene Liste, bliebe die ID dort unbekannt und der Test fiele um.

        Eine Textsuche nach den fuenf Zahlen waere hier untauglich: Sie
        stehen auch in der Routing-Tabelle LEAGUE_IDS, die Abrufe
        adressiert und keine Kategorien entscheidet - und sie treffen
        zufaellig auf Vereins-IDs und auf Zahlen in Dokumentation.
        """
        from src.data import competition_taxonomy as ct

        erfunden = 999123
        erweitert = dict(ct.DOMESTIC_SUPERCUP_IDS)
        erweitert[erfunden] = ("Testland", "bl1")
        monkeypatch.setattr(ct, "DOMESTIC_SUPERCUP_IDS", erweitert)

        eintrag = block(erfunden, "Erfundener Supercup", "Testland", minutes=45)

        assert ct.is_club_competitive(eintrag["league"]) is True
        assert entry_matches_scope(eintrag, SCOPE_CLUB_ALL) is True
        assert entry_matches_scope(eintrag, SCOPE_LEAGUE) is False

    def test_eine_entfernte_kategorie_faellt_ueberall_aus(self, monkeypatch):
        """
        Die Gegenprobe. Wird ein Supercup aus der Taxonomie genommen,
        darf ihn kein Modul mehr aus eigener Kenntnis mitzaehlen.
        """
        from src.data import competition_taxonomy as ct
        from src.data.player_data_quality import club_minutes

        ohne_spanien = {k: v for k, v in ct.DOMESTIC_SUPERCUP_IDS.items()
                        if k != 556}
        monkeypatch.setattr(ct, "DOMESTIC_SUPERCUP_IDS", ohne_spanien)

        roh = {"player": {"id": 1},
               "statistics": [block(556, "Super Cup", "Spain", minutes=31)]}

        # Ohne die belegte ID greift die Namensheuristik: "Super Cup"
        # wird weiterhin als Supercup erkannt. Genau dafuer gibt es sie -
        # die Zusicherung ist, dass die Entscheidung in der Taxonomie
        # faellt und nicht in einer Kopie irgendwo anders.
        assert club_minutes(roh) == 31
        assert ct.classify({"id": 556, "name": "Super Cup",
                            "country": "Spain"}) == "domestic_supercup"
