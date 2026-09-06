"""
Der echte Anbietervertrag der nationalen Ligen (V2-C2B) - optional.

WARUM GETRENNT
--------------
tests/test_national_league_loader.py prueft den Importer vollstaendig
ohne Netz. Das ist richtig so: Die CI darf weder einen Schluessel noch
Kontingent brauchen, und ein Anbieterausfall darf keinen roten Build
erzeugen.

Trotzdem bleibt eine Frage offen, die nur der Anbieter beantworten kann:
Stimmt der Vertrag noch? Liefert /fixtures?league=X&season=Y weiterhin
eine vollstaendige Saison auf einer Seite, mit denselben Feldern und
derselben Saisonsemantik?

Diese Datei stellt genau diese Frage - und zwar sparsam: EIN Aufruf.

AUSFUEHREN
----------
    python -m pytest tests/test_national_league_live.py -q --e2e -m e2e

Ohne --e2e ueberspringt sie sich sichtbar. Das ist eine bewusste
Entscheidung und KEINE Entwarnung.
"""

import os

import pytest

#: Anbietertest - laeuft nur mit "--e2e" (siehe pytest.ini).
pytestmark = pytest.mark.e2e

from src.data import national_league_loader as nl  # noqa: E402

#: Die groesste betroffene Liga. Ein Aufruf genuegt: Was fuer sie gilt,
#: gilt fuer den Endpunkt.
PROBE_LIGA = "pt1"
PROBE_SAISON = 2025


@pytest.fixture(scope="module")
def antwort():
    from dotenv import load_dotenv

    load_dotenv(".env")
    if not os.environ.get("APISPORTS_KEY"):
        pytest.skip("APISPORTS_KEY nicht gesetzt - kein Anbieterzugriff")

    from src.api.apisports_api import _get_full

    return _get_full("fixtures", params={
        "league": nl.league_config(PROBE_LIGA)["apisports_id"],
        "season": PROBE_SAISON})


class TestAnbietervertrag:

    def test_die_antwort_ist_fehlerfrei(self, antwort):
        assert not antwort.get("errors")
        assert antwort.get("results")

    def test_eine_ligasaison_passt_auf_eine_seite(self, antwort):
        """
        Der Importer holt bewusst nur EINE Seite je Liga und Saison.
        Braeuchte es Pagination, fehlten stillschweigend Partien.
        """
        paging = antwort.get("paging") or {}
        assert paging.get("total") == 1, paging

    def test_die_felder_stimmen_mit_der_normalisierung_ueberein(self, antwort):
        eintrag = (antwort.get("response") or [])[0]
        assert eintrag["fixture"]["id"]
        assert eintrag["fixture"]["date"]
        assert eintrag["fixture"]["status"]["short"]
        assert eintrag["teams"]["home"]["id"]
        assert eintrag["teams"]["away"]["id"]
        assert "home" in eintrag["goals"] and "away" in eintrag["goals"]

    def test_die_saisonsemantik_ist_das_startjahr(self, antwort):
        """
        API-Sports bezeichnet eine Saison mit ihrem Startjahr - dieselbe
        Konvention wie FootSim. Liefe das auseinander, laege der ganze
        Bestand um ein Jahr daneben.
        """
        daten = sorted(e["fixture"]["date"][:10]
                       for e in antwort.get("response") or [])
        assert daten[0].startswith(str(PROBE_SAISON))
        assert daten[-1].startswith(str(PROBE_SAISON + 1))

    def test_der_gespeicherte_stand_passt_noch_zum_anbieter(self, antwort):
        gespeichert = nl.load_league_season(PROBE_LIGA, PROBE_SAISON)
        if gespeichert is None:
            pytest.skip("keine lokale Datei zum Vergleich")

        assert gespeichert["meta"]["matches"] == antwort.get("results")
