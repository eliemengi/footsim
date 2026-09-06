"""
Der historische Stichtag ueber den echten Anwendungspfad (V2-C1B).

WAS V2-C1 OFFEN LIESS
---------------------
V2-C1 machte den Stichtag zur Pflicht und vereinheitlichte die
Profilfabrik. Die Laufzeit setzte ihn aber immer auf "jetzt". Fuer ein
kuenftiges Spiel ist das richtig; wer eine BEREITS GESPIELTE Partie
nachsimulierte, bekam dadurch alle spaeteren Partien derselben Saison -
Information, die es zum Anstoss noch nicht gab.

Die Saisonobergrenze wirkte bereits (keine Folgesaison mehr), innerhalb
der Saison floss aber weiterhin alles ein.

WIE ES GESCHLOSSEN WIRD
-----------------------
Serverseitig. Der Anstoss wird aus derselben lokalen Historie
aufgeloest, aus der auch die Profile entstehen - Saison und
Mannschaften stehen ohnehin im Request. Es gibt kein neues Feld in der
Nutzlast und damit keine Manipulationsflaeche: Ein Client kann keinen
Zeitpunkt behaupten.

KEIN NETZ, KEIN PRIVATER ZUSTAND
--------------------------------
Alle Tests hier lesen ausschliesslich die versionierte Historie unter
data/historical/ oder eigene synthetische Daten. Kein Anbieterschluessel,
keine .env, kein data/cache/.
"""

import pytest

from src.data.historical_loader import load_cl_season
from src.features import pit_profiles as pp

SEASON = 2025


@pytest.fixture(scope="module")
def zielspiel():
    """
    Eine echte, bereits gespielte Ligaphasenpartie aus der versionierten
    Historie. Bewusst nicht der allererste Spieltag: Es soll Historie
    VOR dem Spiel geben, sonst waere jeder Stichtag gleich wirkungslos.
    """
    matches = [m for m in load_cl_season(SEASON)["matches"]
               if m.get("stage") == "LEAGUE_STAGE"]
    assert matches, f"data/historical/CL_{SEASON}.json fehlt oder ist leer"
    spaet = sorted(matches, key=lambda m: m["date"])
    return spaet[len(spaet) // 2]


@pytest.fixture(autouse=True)
def _leerer_cache():
    """
    Die Staerken liegen 30 Minuten im Prozesscache. Ohne Leeren
    beantwortete ein spaeterer Test die Frage eines frueheren.
    """
    from src.utils import cache

    cache.clear_all()
    yield
    cache.clear_all()


@pytest.fixture
def client():
    from tests.conftest import mit_csrf

    import app as app_module

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as verbindung:
        yield mit_csrf(verbindung)


def _request(zielspiel, **extra):
    return {"competition": "cl", "home_team": "Heim", "away_team": "Gast",
            "home_id": zielspiel["home_id"], "away_id": zielspiel["away_id"],
            "season": SEASON, "simulations": 200, "use_seed": True, **extra}


def _beobachte_cutoff(monkeypatch):
    """
    Zeichnet auf, welcher Stichtag wirklich in der Profilfabrik ankommt.

    Angesetzt wird an der Naht, die der Simulator benutzt - nicht an
    einer nachgebauten. Sonst pruefte der Test seinen eigenen Zwilling.
    """
    import src.predict.cl_match_sim as cms
    from src.features import strength_provider as sp

    gesehen = []
    echt = sp.get_cl_team_strengths

    def beobachtend(season, cutoff, repository=None):
        gesehen.append(cutoff)
        return echt(season, cutoff, repository)

    monkeypatch.setattr(cms, "get_cl_team_strengths", beobachtend)
    return gesehen


# ---------------------------------------------------------------------------
# 1. Ende zu Ende: der echte Anstoss kommt an
# ---------------------------------------------------------------------------

class TestEndeZuEnde:

    def test_ein_historisches_spiel_uebergibt_seinen_eigenen_anstoss(
            self, client, zielspiel, monkeypatch):
        """
        Der Kern von V2-C1B. Ueber den oeffentlichen Pfad
        /api/simulate muss GENAU das Anstossdatum des Zielspiels in der
        Profilfabrik ankommen - nicht der heutige Tag.
        """
        gesehen = _beobachte_cutoff(monkeypatch)

        antwort = client.post("/api/simulate", json=_request(zielspiel))

        assert antwort.status_code == 200
        assert gesehen == [zielspiel["date"]], (
            f"Stichtag {gesehen} statt des Anstosses {zielspiel['date']}")

    def test_das_ist_nicht_der_heutige_tag(self, client, zielspiel,
                                           monkeypatch):
        """
        Die Gegenprobe. Waere der Stichtag weiterhin "jetzt", saehe der
        Test oben zwar einen Wert - aber den falschen.
        """
        gesehen = _beobachte_cutoff(monkeypatch)
        client.post("/api/simulate", json=_request(zielspiel))

        assert not gesehen[0].startswith(pp.runtime_cutoff()[:10])

    def test_ein_unbekanntes_spiel_faellt_auf_jetzt_zurueck(
            self, client, zielspiel, monkeypatch):
        """
        Eine Paarung, die nicht in der Historie steht, ist kuenftig oder
        unbekannt. Dann gilt "jetzt" - ausdruecklich NICHT die komplette
        Saison.
        """
        gesehen = _beobachte_cutoff(monkeypatch)

        antwort = client.post("/api/simulate", json=_request(
            zielspiel, home_id=999001, away_id=999002))

        assert antwort.status_code == 200
        assert gesehen == [pp.runtime_cutoff()]

    def test_die_herkunft_weist_den_stichtag_aus(self, zielspiel):
        from src.features import strength_provider as sp

        prov = sp.get_cl_team_strengths(
            season=SEASON, cutoff=zielspiel["date"])["provenance"]
        assert prov["pit_cutoff"] == zielspiel["date"]
        assert prov["matches_through_date"] < zielspiel["date"]


# ---------------------------------------------------------------------------
# 2. Zukunftsleck ueber den echten Pfad
# ---------------------------------------------------------------------------

class TestZukunftsleck:

    def test_eine_spaetere_partie_aendert_das_ergebnis_nicht(
            self, client, zielspiel, monkeypatch):
        """
        DER eigentliche Nachweis.

        Der Historie wird eine Partie NACH dem Zielspiel hinzugefuegt -
        mit absurd hohem Ergebnis, damit ein Durchschlagen sofort
        auffiele. Prognose und Torerwartung muessen unveraendert
        bleiben.

        Vor V2-C1B waere dieser Test gefallen: Der Stichtag war "heute",
        also lag die spaetere Partie im Kenntnisstand.
        """
        from src.features import pit_profiles

        echt = load_cl_season(SEASON)
        spaeter = dict(echt["matches"][0])
        spaeter.update({"date": "2026-05-01", "home_id": zielspiel["home_id"],
                        "away_id": zielspiel["away_id"],
                        "home_goals": 9, "away_goals": 0,
                        "stage": "LEAGUE_STAGE", "match_id": -1})

        ohne = client.post("/api/simulate", json=_request(zielspiel)).get_json()

        from src.utils import cache
        cache.clear_all()

        original = pit_profiles.PitProfileRepository.cl_payload

        def mit_zusatz(self, season):
            payload = original(self, season)
            if season != SEASON or not payload:
                return payload
            kopie = dict(payload)
            kopie["matches"] = list(payload["matches"]) + [spaeter]
            return kopie

        monkeypatch.setattr(pit_profiles.PitProfileRepository, "cl_payload",
                            mit_zusatz)

        mit = client.post("/api/simulate", json=_request(zielspiel)).get_json()

        assert mit["expected_home_goals"] == ohne["expected_home_goals"]
        assert mit["expected_away_goals"] == ohne["expected_away_goals"]
        assert mit["home_win_probability"] == ohne["home_win_probability"]

    def test_die_gegenprobe_schlaegt_an(self, zielspiel, monkeypatch):
        """
        Waere der Filter wirkungslos, muesste dieselbe Zusatzpartie sehr
        wohl durchschlagen. Ohne diesen Nachweis koennte der Test oben
        auch dann gruen sein, wenn er gar nichts misst.
        """
        from src.features import pit_profiles

        spaeter = {"date": "2026-05-01", "home_id": zielspiel["home_id"],
                   "away_id": zielspiel["away_id"], "home_goals": 9,
                   "away_goals": 0, "stage": "LEAGUE_STAGE"}

        repo = pit_profiles.PitProfileRepository()
        vorher, _, _ = repo.cl_history(SEASON, zielspiel["date"])

        original = pit_profiles.PitProfileRepository.cl_payload

        def mit_zusatz(self, season):
            payload = original(self, season)
            kopie = dict(payload)
            kopie["matches"] = list(payload["matches"]) + [spaeter]
            return kopie

        monkeypatch.setattr(pit_profiles.PitProfileRepository, "cl_payload",
                            mit_zusatz)

        repo2 = pit_profiles.PitProfileRepository()
        # Stichtag NACH der Zusatzpartie: jetzt muss sie ankommen.
        spaet, _, _ = repo2.cl_history(SEASON, "2026-06-01")
        frueh, _, _ = repo2.cl_history(SEASON, zielspiel["date"])

        assert frueh == vorher, "der Stichtagsfilter laesst die Partie durch"
        assert spaet != vorher, "die Zusatzpartie kommt nirgends an"


# ---------------------------------------------------------------------------
# 3. Selbstleck
# ---------------------------------------------------------------------------

class TestSelbstleck:

    def test_das_zielspiel_geht_nicht_in_sein_eigenes_profil_ein(
            self, zielspiel):
        """
        kickoff == cutoff bleibt ausgeschlossen. Sonst traege das zu
        prognostizierende Spiel zu seiner eigenen Vorhersage bei.
        """
        repo = pp.PitProfileRepository()
        _, _, bekannt = repo.cl_history(SEASON, zielspiel["date"])

        assert all(m["date"] < zielspiel["date"] for m in bekannt)
        assert not any(m.get("match_id") == zielspiel.get("match_id")
                       for m in bekannt), "das Zielspiel steckt im eigenen Profil"

    def test_auch_andere_partien_desselben_tages_bleiben_draussen(
            self, zielspiel):
        """
        Die Historie traegt nur Datumsangaben ohne Uhrzeit. Ohne
        Uhrzeiten auf beiden Seiten ist nicht entscheidbar, welches
        Spiel des Tages frueher war - die leak-sichere Antwort ist,
        keines mitzuzaehlen.
        """
        gleicher_tag = [m for m in load_cl_season(SEASON)["matches"]
                        if m["date"] == zielspiel["date"]]
        assert len(gleicher_tag) > 1, "Testvoraussetzung: mehrere Spiele am Tag"

        repo = pp.PitProfileRepository()
        _, _, bekannt = repo.cl_history(SEASON, zielspiel["date"])
        assert not any(m["date"] == zielspiel["date"] for m in bekannt)


# ---------------------------------------------------------------------------
# 4. Autoritative Aufloesung statt Client-Behauptung
# ---------------------------------------------------------------------------

class TestAutoritativeAufloesung:

    def test_der_client_sendet_keinen_zeitpunkt(self):
        """
        Der Stichtag ist eine fachliche Wahrheit. Er wird nicht
        entgegengenommen, sondern aufgeloest - deshalb gibt es kein
        neues Feld in der Nutzlast und keine Manipulationsflaeche.
        """
        import os

        wurzel = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(wurzel, "static", "script.js"),
                  encoding="utf-8") as datei:
            skript = datei.read()

        block = skript[skript.index("async function runSimulation()"):]
        block = block[:block.index("nativeHaptik")]
        for feld in ("kickoff", "cutoff", "utc_date", "utcDate"):
            assert feld not in block, (
                f"das Frontend schickt {feld} - der Stichtag darf nicht "
                f"vom Client kommen")

    def test_die_aufloesung_trifft_die_regulaere_phase(self):
        """
        Innerhalb der regulaeren Phase ist eine Paarung je Saison
        eindeutig. Trifft dieselbe Paarung spaeter noch einmal im
        K.-o. aufeinander, gewinnt die Ligaphase.
        """
        from collections import Counter

        matches = load_cl_season(SEASON)["matches"]
        zaehler = Counter((m["home_id"], m["away_id"]) for m in matches)
        doppelt = [k for k, v in zaehler.items() if v > 1]
        if not doppelt:
            pytest.skip("keine doppelte Paarung in dieser Saison")

        paarung = doppelt[0]
        kandidaten = [m for m in matches
                      if (m["home_id"], m["away_id"]) == paarung]
        regulaer = [m for m in kandidaten
                    if m.get("stage") in pp.REGULAR_STAGES]
        assert regulaer, "Testvoraussetzung: eine Partie in der regulaeren Phase"

        assert pp.fixture_cutoff(SEASON, *paarung) == regulaer[0]["date"]

    def test_bei_mehreren_ko_partien_gewinnt_die_frueheste(self,
                                                            monkeypatch):
        """
        Bleiben nur K.-o.-Partien, ist die frueheste die leak-sichere
        Wahl: weniger Information, nie mehr.

        Synthetisch, und zwar begruendet: In den echten Saisons 2023 bis
        2025 gibt es diesen Fall nicht, weil die beiden Legs einer
        Begegnung Heim und Gast tauschen und damit verschiedene geordnete
        Paarungen sind. Der Zweig ist ein Netz fuer Wiederholungsspiele
        und Formatwechsel - ein uebersprungener Test haette ihn
        ungeprueft gelassen.
        """
        from src.features import pit_profiles

        kunst = {"meta": {}, "teams": {}, "matches": [
            {"date": "2026-04-15", "home_id": 111, "away_id": 222,
             "home_goals": 1, "away_goals": 1, "stage": "LAST_16"},
            {"date": "2026-03-10", "home_id": 111, "away_id": 222,
             "home_goals": 2, "away_goals": 0, "stage": "LAST_16"},
        ]}
        monkeypatch.setattr(pit_profiles.PitProfileRepository, "cl_payload",
                            lambda self, season: kunst)

        assert pp.fixture_cutoff(SEASON, 111, 222) == "2026-03-10"

    def test_die_regulaere_phase_gewinnt_auch_gegen_eine_fruehere_ko_partie(
            self, monkeypatch):
        """
        Die Vorrangregel ist nicht bloss "das fruehere Datum": Die
        regulaere Phase ist das, was die Einzelspielsimulation abdeckt.
        """
        from src.features import pit_profiles

        kunst = {"meta": {}, "teams": {}, "matches": [
            {"date": "2026-02-01", "home_id": 111, "away_id": 222,
             "home_goals": 1, "away_goals": 1, "stage": "LAST_16"},
            {"date": "2026-03-10", "home_id": 111, "away_id": 222,
             "home_goals": 2, "away_goals": 0, "stage": "LEAGUE_STAGE"},
        ]}
        monkeypatch.setattr(pit_profiles.PitProfileRepository, "cl_payload",
                            lambda self, season: kunst)

        assert pp.fixture_cutoff(SEASON, 111, 222) == "2026-03-10"

    def test_die_aufloesung_liest_dieselbe_quelle_wie_die_profile(self):
        """
        Ein zweiter Leser derselben Datei koennte auseinanderlaufen.
        Beide gehen ueber die Fabrik.
        """
        import inspect

        quelle = inspect.getsource(pp.fixture_cutoff)
        assert "repository.cl_payload" in quelle


# ---------------------------------------------------------------------------
# 5. Fehlende, unbrauchbare und widerspruechliche Angaben
# ---------------------------------------------------------------------------

class TestRobustheit:

    @pytest.mark.parametrize("kaputt", [
        {"home_id": None}, {"away_id": None},
        {"home_id": "abc"}, {"away_id": -1},
        {"season": None}, {"season": 9999},
    ])
    def test_unbrauchbare_angaben_erzeugen_keinen_serverfehler(
            self, client, zielspiel, kaputt):
        antwort = client.post("/api/simulate", json=_request(zielspiel, **kaputt))
        assert antwort.status_code in (200, 400), antwort.status_code

    @pytest.mark.parametrize("kaputt", [
        {"home_id": "abc"}, {"season": 9999}, {"home_id": 999001},
    ])
    def test_unbrauchbare_angaben_aktivieren_keine_zukunftsdaten(
            self, client, zielspiel, monkeypatch, kaputt):
        """
        Der wichtige Teil: Eine unbrauchbare Angabe darf nicht dazu
        fuehren, dass MEHR Information einfliesst als bei einer
        gueltigen. Schlimmstenfalls gilt "jetzt".
        """
        gesehen = _beobachte_cutoff(monkeypatch)
        client.post("/api/simulate", json=_request(zielspiel, **kaputt))

        if gesehen:
            assert gesehen[0] <= pp.runtime_cutoff(), (
                "ein Stichtag in der Zukunft")

    def test_eine_unlesbare_historie_verhindert_keine_prognose(
            self, client, zielspiel, monkeypatch):
        from src.features import pit_profiles

        def kaputt(self, season):
            raise OSError("Datei unlesbar")

        monkeypatch.setattr(pit_profiles.PitProfileRepository, "cl_payload",
                            kaputt)

        assert pp.fixture_cutoff(SEASON, zielspiel["home_id"],
                                 zielspiel["away_id"]) is None

    def test_ohne_saison_wird_nichts_aufgeloest(self, zielspiel):
        assert pp.fixture_cutoff(None, zielspiel["home_id"],
                                 zielspiel["away_id"]) is None


# ---------------------------------------------------------------------------
# 6. Rueckwaertskompatibilitaet
# ---------------------------------------------------------------------------

class TestRueckwaertskompatibel:

    def test_ein_aktueller_cl_request_funktioniert_weiter(self, client,
                                                          zielspiel):
        antwort = client.post("/api/simulate", json=_request(zielspiel))
        daten = antwort.get_json()

        assert antwort.status_code == 200
        assert daten["competition"] == "Champions League"
        summe = (daten["home_win_probability"] + daten["draw_probability"]
                 + daten["away_win_probability"])
        assert abs(summe - 100.0) < 0.05

    def test_die_c8b_ansaetze_wirken_unveraendert(self, client, zielspiel):
        ml = client.post("/api/simulate",
                         json=_request(zielspiel, approach="ml")).get_json()
        assert ml["ml"]["requested_approach"] == "ml"
        assert ml["ml"]["applied"] is True

    def test_ein_request_ohne_season_bleibt_gueltig(self, client, zielspiel):
        nutzlast = _request(zielspiel)
        nutzlast.pop("season")
        antwort = client.post("/api/simulate", json=nutzlast)
        assert antwort.status_code == 200

    def test_die_signatur_bleibt_rueckwaertskompatibel(self):
        import inspect

        from src.predict.cl_match_sim import simulate_cl_league_phase_match

        parameter = inspect.signature(simulate_cl_league_phase_match).parameters
        assert parameter["kickoff"].default is None, (
            "kickoff muss optional bleiben")
