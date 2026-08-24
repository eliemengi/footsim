"""
Wenig Daten heisst nicht "keine Daten".

DER FEHLER, DEN DIESE DATEI VERHINDERT
--------------------------------------
Die Grenze von 450 Minuten ist eine Belastbarkeitsgrenze fuer Perzentile
und Vergleichsverteilungen - mehr nicht. Sie darf niemals:

    Spieler aus der Suche entfernen
    reale Saisonwerte unterdruecken
    Vergleiche verhindern
    Rohwerte verstecken
    Radare grundsaetzlich blockieren

Ein Spieler mit 1, 10, 38 oder 90 Minuten muss sichtbar und vergleichbar
bleiben. Die Oberflaeche darf nur dazusagen, dass die Stichprobe klein
beziehungsweise vorlaeufig ist.

Am 24.08.2026 traten diese Faelle alle gleichzeitig auf: elf Spieler mit
38 Minuten, mehrere mit minutes=None, und ein ganzer Verein ohne einen
einzigen Vereinsblock. Jede dieser Lagen hat eine eigene richtige
Antwort - und "keine Einsaetze" ist in drei von vier Faellen die falsche.
"""

import pytest

from src.data.player_compare_loader import (
    SCOPE_CLUB_ALL,
    SCOPE_LEAGUE,
    SCOPE_NATIONAL,
    build_player_profile,
)
from src.data.player_data_quality import (
    LOW_SAMPLE_MINUTES,
    VISIBLE_STATES,
    classify_profile_quality,
    detect_uniform_minutes,
)


def block(league_id=140, name="La Liga", country="Spain", minutes=90,
          appearances=1, season=2026, position="Attacker"):
    return {
        "team": {"id": 1, "name": "Testverein"},
        "league": {"id": league_id, "name": name, "country": country,
                   "season": season, "type": "League"},
        "games": {"minutes": minutes, "appearences": appearances,
                  "position": position, "lineups": appearances or 0},
        "goals": {"total": 1, "assists": 0},
        "passes": {"total": 30, "key": 2, "accuracy": 80},
        "shots": {"total": 3, "on": 1},
        "duels": {"total": 10, "won": 5},
    }


def profil(bloecke, scope=SCOPE_CLUB_ALL, season=2026):
    roh = {"player": {"id": 1, "name": "Testspieler", "age": 22},
           "statistics": bloecke}
    return build_player_profile(roh, season, scope=scope)


class TestWenigMinutenBleibenSichtbar:

    @pytest.mark.parametrize("minuten", [1, 10, 38, 90, 449])
    def test_der_spieler_hat_daten(self, minuten):
        """Die Grenze entscheidet ueber Einordnung, nicht ueber Existenz."""
        p = profil([block(minutes=minuten)])
        assert p["data_available"] is True
        assert p["minutes"] == minuten

    @pytest.mark.parametrize("minuten", [1, 10, 38, 90, 449])
    def test_der_rohwert_wird_nicht_unterdrueckt(self, minuten):
        p = profil([block(minutes=minuten)])
        assert p["stats"]["games"]["minutes"] == minuten

    @pytest.mark.parametrize("minuten", [1, 10, 38, 90, 449])
    def test_der_zustand_bleibt_ein_sichtbarer(self, minuten):
        zustand, _ = classify_profile_quality({"statistics": [block(minutes=minuten)]})
        assert zustand in VISIBLE_STATES

    def test_unter_der_grenze_heisst_duenne_stichprobe(self):
        zustand, grund = classify_profile_quality(
            {"statistics": [block(minutes=38)]})
        assert zustand == "low_sample"
        assert str(LOW_SAMPLE_MINUTES) in grund

    def test_low_sample_ist_nicht_keine_daten(self):
        """Der Kern der ganzen Datei."""
        p = profil([block(minutes=38)])
        assert p["data_quality"]["cache_quality"] == "low_sample"
        assert p["data_available"] is True

    def test_ueber_der_grenze_gilt_es_als_belastbar(self):
        zustand, _ = classify_profile_quality(
            {"statistics": [block(minutes=2500, appearances=30)]})
        assert zustand == "current_final_or_latest"

    def test_die_grenze_ist_dieselbe_zahl_wie_im_pool(self):
        from src.data.player_compare_loader import DEFAULT_MIN_MINUTES
        assert LOW_SAMPLE_MINUTES == DEFAULT_MIN_MINUTES


class TestFehlendeMinuten:

    def test_minutes_none_wird_nicht_zu_null_erfunden(self):
        """
        None heisst "nicht verbucht", nicht "null gespielt". Der
        Unterschied verschwindet, sobald jemand einen Ersatzwert einsetzt.
        """
        p = profil([block(minutes=None, appearances=1)])
        assert p["stats"]["games"]["minutes"] in (None, 0)

    def test_einsatz_ohne_minuten_gilt_als_daten(self):
        """
        Der Anbieter meldet den Einsatz, aber noch keine Minuten. Genau so
        standen am 24.08.2026 fuenf Real-Madrid-Spieler da.
        """
        p = profil([block(minutes=None, appearances=1)])
        assert p["data_available"] is True

    def test_ohne_einsatz_und_ohne_minuten_ist_eine_aussage(self):
        zustand, grund = classify_profile_quality(
            {"statistics": [block(minutes=0, appearances=0)]})
        assert zustand == "no_current_appearance"
        assert "ohne Einsatz" in grund


class TestOhneVereinsblock:

    def test_nur_nationalmannschaft_heisst_anbieterluecke(self):
        """
        Der Fall Lamine Yamal: frisch geholt, nur Laenderspielbloecke,
        kein Verein. Das ist eine Luecke beim Anbieter - kein Grund, den
        Spieler zu verstecken.
        """
        nm = block(league_id=1, name="World Cup", country="World",
                   minutes=615, appearances=8)
        zustand, _ = classify_profile_quality({"statistics": [nm]})
        assert zustand == "provider_incomplete"
        assert zustand in VISIBLE_STATES

    def test_die_laenderspieldaten_bleiben_im_nationalscope_sichtbar(self):
        nm = block(league_id=1, name="World Cup", country="World",
                   minutes=615, appearances=8)
        p = profil([nm], scope=SCOPE_NATIONAL)
        assert p["data_available"] is True
        assert p["minutes"] == 615

    def test_club_all_bleibt_ehrlich_leer(self):
        """Keine erfundenen Vereinsdaten, wo der Anbieter keine liefert."""
        nm = block(league_id=1, name="World Cup", country="World",
                   minutes=615, appearances=8)
        p = profil([nm], scope=SCOPE_CLUB_ALL)
        assert not p["minutes"]


class TestGleicheMinutenImTeam:

    def test_elf_gleiche_werte_sind_ein_hinweis(self):
        """
        Elf Spieler mit exakt 38 Minuten, Torwart eingeschlossen. Kein
        Feldspieler kann in einem regulaeren Spiel weniger haben als der
        durchspielende Torwart.
        """
        verdacht, wert, anzahl = detect_uniform_minutes([38] * 11)
        assert verdacht is True and wert == 38 and anzahl == 11

    def test_der_hinweis_aendert_keinen_wert(self):
        """
        FootSim darf niemals behaupten, jemand habe 90 Minuten gespielt,
        wenn der Anbieter 38 liefert. Der Hinweis steht daneben, nicht
        anstelle der Zahl.
        """
        p = profil([block(minutes=38)])
        assert p["minutes"] == 38

    def test_eine_normale_mannschaft_loest_nichts_aus(self):
        verdacht, _, _ = detect_uniform_minutes([90] * 11)
        assert verdacht is False

    def test_wenige_gleiche_werte_reichen_nicht(self):
        verdacht, _, _ = detect_uniform_minutes([45, 45, 90, 90, 90])
        assert verdacht is False


class TestSupercupUndLigaGemeinsam:

    def test_beide_zaehlen_in_club_all(self):
        bloecke = [block(140, "La Liga", "Spain", minutes=38, appearances=1),
                   block(556, "Super Cup", "Spain", minutes=31, appearances=2)]
        assert profil(bloecke, scope=SCOPE_CLUB_ALL)["minutes"] == 69

    def test_nur_die_liga_zaehlt_in_league(self):
        bloecke = [block(140, "La Liga", "Spain", minutes=38, appearances=1),
                   block(556, "Super Cup", "Spain", minutes=31, appearances=2)]
        assert profil(bloecke, scope=SCOPE_LEAGUE)["minutes"] == 38

    def test_beide_zusammen_bleiben_unter_der_grenze(self):
        """69 Minuten sind eine duenne Stichprobe - und trotzdem Daten."""
        bloecke = [block(140, "La Liga", "Spain", minutes=38, appearances=1),
                   block(556, "Super Cup", "Spain", minutes=31, appearances=2)]
        p = profil(bloecke)
        assert p["data_available"] is True
        assert p["data_quality"]["cache_quality"] == "low_sample"


class TestAelterreEintraegeBleibenLesbar:

    def test_ein_profil_ohne_qualitaetsvermerk_zerlegt_nichts(self):
        from src.data.player_data_quality import read_quality

        block_ = read_quality({"player_id": 1, "minutes_by_scope": {}})
        assert block_["cache_quality"] is None
        assert block_["provisional"] is None

    def test_der_vermerk_ist_additiv(self):
        """
        Alle bisherigen Felder bleiben unveraendert - ein neuer Schluessel
        darf keinen alten Aufrufer stoeren.
        """
        p = profil([block(minutes=90)])
        for feld in ("name", "minutes", "position", "stats", "scope",
                     "data_available", "in_league_cohort"):
            assert feld in p, feld
        assert "data_quality" in p

    def test_ein_ausfall_der_einstufung_zerlegt_das_profil_nicht(self, monkeypatch):
        """
        Ein fehlender Hinweis ist aergerlich, eine kaputte Seite ist
        schlimmer.
        """
        import src.data.player_data_quality as pdq

        def kaputt(*args, **kwargs):
            raise RuntimeError("absichtlicher Ausfall")

        monkeypatch.setattr(pdq, "classify_profile_quality", kaputt)
        p = profil([block(minutes=90)])
        assert p["minutes"] == 90
        assert p["data_quality"] is None
