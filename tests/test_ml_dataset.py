"""
Der Point-in-Time-Datensatz fuer die erste ML-Messung.

WORAN ALLES HAENGT
------------------
Der Datensatz muss dasselbe rechnen wie der Backtest. Tut er es nicht,
lernt ein Modell etwas anderes, als spaeter gegen die Baseline gemessen
wird - und der Unterschied faellt niemandem auf, weil beide Wege fuer
sich plausibel aussehen.

Der wichtigste Test dieser Datei ist deshalb nicht die Zeilenzahl,
sondern test_lambdas_stimmen_mit_dem_backtest_ueberein: Er baut fuer
dieselbe Partie beide Wege und vergleicht die Lambdas Ziffer fuer
Ziffer.

Die uebrigen Tests sichern, was ein Datensatz fuer zeitliche Auswertung
braucht: strenge Point-in-Time-Trennung, feste Reihenfolge, sichtbare
Kaltstartfaelle und keine Abhaengigkeit von Dateien, die nicht im
Repository liegen.

Die meisten Tests laufen auf einer einzigen Liga-Saison. Der volle
Datensatz braucht Minuten und gehoert nicht in eine Suite, die bei jedem
Lauf mitlaeuft.
"""

import json
import os

import pytest

import run_ml
from src.ml import cl_dataset as clds
from src.ml import dataset as ds
from src.ml import model as mdl

#: Eine kleine, vollstaendige Liga-Saison als Arbeitsgrundlage.
#: bl1 2024 steht mit 251 auswertbaren Spielen im Backtestergebnis.
TEST_LIGA = "bl1"
TEST_SAISON = 2024


@pytest.fixture(scope="module")
def zeilen():
    gebaut, _ = ds.build_league_season(TEST_LIGA, TEST_SAISON)
    assert gebaut, "keine Zeilen entstanden"
    return gebaut


# ---------------------------------------------------------------------------
# Struktur und Determinismus
# ---------------------------------------------------------------------------

class TestStrukturUndReihenfolge:

    def test_jede_zeile_traegt_alle_spalten(self, zeilen):
        for zeile in zeilen[:50]:
            fehlend = set(ds.SPALTEN) - set(zeile)
            assert not fehlend, f"Spalten fehlen: {sorted(fehlend)[:5]}"

    def test_keine_zeile_traegt_unbekannte_spalten(self, zeilen):
        erlaubt = set(ds.SPALTEN)
        for zeile in zeilen[:50]:
            assert not set(zeile) - erlaubt

    def test_zwei_builds_liefern_identische_zeilen(self):
        """
        Ohne diese Zusicherung waere keine der spaeteren Messungen
        vergleichbar.
        """
        a, _ = ds.build_dataset([TEST_LIGA], [TEST_SAISON])
        b, _ = ds.build_dataset([TEST_LIGA], [TEST_SAISON])
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_das_schema_ist_stabil(self):
        assert ds.build_schema() == ds.build_schema()

    def test_die_reihenfolge_ist_vollstaendig_bestimmt(self):
        """
        row_id ist eindeutig, also haengt die Sortierung nicht an der
        Einlesereihenfolge.
        """
        gebaut, _ = ds.build_dataset([TEST_LIGA], [TEST_SAISON])
        schluessel = [(z["league"], z["season"], z["date"], z["row_id"])
                      for z in gebaut]
        assert schluessel == sorted(schluessel)

    def test_row_id_ist_eindeutig(self, zeilen):
        ids = [z["row_id"] for z in zeilen]
        assert len(ids) == len(set(ids))

    def test_match_id_wird_nicht_erfunden(self, zeilen):
        """
        Die Ligadateien fuehren kein match_id. Es bleibt ehrlich None,
        statt ersatzweise mit row_id gefuellt zu werden.
        """
        assert all(z["match_id"] is None for z in zeilen)
        assert all(z["row_id"] for z in zeilen)

    def test_es_gibt_keine_zufallswerte(self):
        """Zwei Laeufe in getrennten Prozessen ergeben dasselbe."""
        import subprocess
        import sys

        befehl = [sys.executable, "-c",
                  "import sys; sys.path.insert(0, '.');"
                  "from src.ml import dataset as ds;"
                  "z, _ = ds.build_dataset(['bl1'], [2024]);"
                  "import json; print(json.dumps(z[0], sort_keys=True))"]
        a = subprocess.run(befehl, capture_output=True, text=True, timeout=600)
        b = subprocess.run(befehl, capture_output=True, text=True, timeout=600)
        assert a.returncode == 0 and b.returncode == 0
        assert a.stdout == b.stdout


# ---------------------------------------------------------------------------
# Point-in-Time
# ---------------------------------------------------------------------------

class TestPointInTime:

    def test_das_zielspiel_steckt_nicht_im_eigenen_profil(self, zeilen):
        """
        Die zentrale Zusicherung. Fuer die letzte Partie einer Saison
        darf matches_used hoechstens die Zahl der VORHERIGEN Spiele
        dieses Teams sein - nie eine mehr.
        """
        letzte = zeilen[-1]
        heim_id = letzte["home_id"]

        vorher = sum(1 for z in zeilen
                     if z["date"] < letzte["date"]
                     and heim_id in (z["home_id"], z["away_id"]))

        assert letzte["home_matches_used"] <= vorher, (
            f"matches_used={letzte['home_matches_used']} bei nur {vorher} "
            f"vorherigen Spielen - das Zielspiel zaehlt sich selbst mit")

    def test_am_ersten_spieltag_ist_nichts_bekannt(self, zeilen):
        erstes_datum = min(z["date"] for z in zeilen)
        erste = [z for z in zeilen if z["date"] == erstes_datum]

        for zeile in erste:
            assert zeile["home_matches_used"] == 0
            assert zeile["away_matches_used"] == 0
            assert zeile["league_avg_matches"] == 0

    def test_der_ligaschnitt_waechst_monoton(self, zeilen):
        """
        Er zaehlt die zum Stichtag bekannten Spiele. Ein Rueckgang waere
        ein Zeichen, dass ein spaeterer Stand einfliesst.
        """
        nach_datum = {}
        for zeile in zeilen:
            nach_datum[zeile["date"]] = zeile["league_avg_matches"]

        werte = [nach_datum[d] for d in sorted(nach_datum)]
        assert werte == sorted(werte)

    def _stichtag_und_original(self):
        """Saisonmitte als Zielstichtag, dazu der unveraenderte Stand."""
        from src.data.historical_loader import LEAGUE_CODES, load_season

        payload = load_season(LEAGUE_CODES[TEST_LIGA], TEST_SAISON)
        daten = sorted({m["date"] for m in payload["matches"] if m.get("date")})
        return daten[len(daten) // 2], payload

    def _mit_payload(self, monkeypatch, api_code, ersatz):
        """
        Schiebt ein veraendertes Saison-Payload unter.

        Sowohl build_league_season als auch match_timeline._league_entries
        holen load_season ueber einen lokalen Import aus dem Modul -
        nachgemessen. Ein Patch auf das Modulattribut erreicht deshalb
        BEIDE Wege: Profile und Baseline ebenso wie die
        Belastungszeitleiste.

        Es wird keine echte Datei angefasst; das Original bleibt auf der
        Platte unberuehrt.
        """
        import copy

        from src.data import historical_loader

        echte_ladung = historical_loader.load_season

        def gepatcht(code, saison):
            if code == api_code and saison == TEST_SAISON:
                # Frische Kopie je Aufruf: Kein Aufrufer soll die
                # Testdaten eines anderen sehen.
                return copy.deepcopy(ersatz)
            return echte_ladung(code, saison)

        monkeypatch.setattr(historical_loader, "load_season", gepatcht)

    def test_zukuenftige_ergebnisse_veraendern_fruehere_zeilen_nicht(
            self, monkeypatch):
        """
        Der kausale Point-in-Time-Beweis.

        Zweimal denselben Datensatz zu bauen zeigt nur Determinismus. Der
        eigentliche Nachweis ist ein anderer: Wenn ausschliesslich
        ZUKUENFTIGE Ergebnisse veraendert werden, darf sich an den Zeilen
        bis zum Stichtag nichts bewegen - kein Profilwert, kein Lambda,
        keine Wahrscheinlichkeit.

        Verändert wird eine Tiefenkopie des Payloads, die ueber einen
        Monkeypatch untergeschoben wird. Die Dateien auf der Platte
        bleiben unangetastet.
        """
        import copy

        from src.data.historical_loader import LEAGUE_CODES

        stichtag, original_payload = self._stichtag_und_original()
        api_code = LEAGUE_CODES[TEST_LIGA]

        original_zeilen, _ = ds.build_league_season(TEST_LIGA, TEST_SAISON)

        # Nur die Zukunft anfassen, und zwar deutlich: 7:0 statt des
        # tatsaechlichen Ergebnisses. Ein kleiner Unterschied koennte in
        # der Rundung untergehen.
        manipuliert = copy.deepcopy(original_payload)
        geaendert = 0
        for match in manipuliert["matches"]:
            datum = match.get("date")
            if not datum or datum <= stichtag:
                continue
            if match.get("home_goals") is None:
                continue
            match["home_goals"] = 7
            match["away_goals"] = 0
            geaendert += 1

        assert geaendert > 50, (
            f"nur {geaendert} zukuenftige Spiele veraendert - zu wenig fuer "
            f"einen aussagekraeftigen Test")

        self._mit_payload(monkeypatch, api_code, manipuliert)
        neue_zeilen, _ = ds.build_league_season(TEST_LIGA, TEST_SAISON)

        # 1. Die Vergangenheit MUSS unveraendert sein - vollstaendig,
        #    nicht nur in einzelnen Spalten.
        alt_vorher = [z for z in original_zeilen if z["date"] <= stichtag]
        neu_vorher = [z for z in neue_zeilen if z["date"] <= stichtag]

        assert len(alt_vorher) == len(neu_vorher)
        assert alt_vorher, "kein Vergleichsbereich vor dem Stichtag"

        for alt, neu in zip(alt_vorher, neu_vorher):
            assert alt == neu, (
                f"Zeile {alt['row_id']} hat sich veraendert, obwohl nur "
                f"ZUKUENFTIGE Ergebnisse angefasst wurden - das ist Leakage")

        # 2. Die Gegenprobe: Ohne sie koennte der Test versehentlich
        #    zweimal dieselben Eingangsdaten benutzt haben und trotzdem
        #    gruen leuchten.
        alt_nachher = [z for z in original_zeilen if z["date"] > stichtag]
        neu_nachher = [z for z in neue_zeilen if z["date"] > stichtag]

        assert [z["home_goals"] for z in neu_nachher] != \
               [z["home_goals"] for z in alt_nachher], (
            "die Manipulation ist gar nicht angekommen")
        assert all(z["home_goals"] == 7 for z in neu_nachher)

        # 3. Und die Wirkung muss sich auch in den FEATURES zeigen -
        #    spaetere Profile beruhen ja jetzt auf anderen Ergebnissen.
        assert [z["home_attack_home"] for z in neu_nachher] != \
               [z["home_attack_home"] for z in alt_nachher], (
            "veraenderte Ergebnisse haben die spaeteren Profile nicht "
            "beeinflusst - dann misst der Test nicht, was er soll")

    def test_ein_zusaetzliches_zukuenftiges_spiel_aendert_die_belastung_nicht(
            self, monkeypatch):
        """
        Derselbe Beweis fuer den ZWEITEN Datenweg.

        Der Test oben veraendert Tore. Die Belastungsmerkmale zaehlen
        aber Spiele, keine Tore - sie blieben davon unberuehrt. Hier
        kommt deshalb ein zusaetzliches Spiel in die Zukunft, das die
        Zeitleiste sehr wohl sieht. Die Ruhezeiten und Spieldichten der
        frueheren Zeilen duerfen sich trotzdem nicht bewegen.
        """
        import copy

        from src.data.historical_loader import LEAGUE_CODES

        stichtag, original_payload = self._stichtag_und_original()
        api_code = LEAGUE_CODES[TEST_LIGA]

        original_zeilen, _ = ds.build_league_season(TEST_LIGA, TEST_SAISON)

        # Ein erfundenes Spiel weit nach dem Stichtag, zwischen zwei
        # Mannschaften, die es in dieser Liga wirklich gibt.
        spaeteste = max(m["date"] for m in original_payload["matches"]
                        if m.get("date"))
        vorlage = original_payload["matches"][0]

        manipuliert = copy.deepcopy(original_payload)
        manipuliert["matches"].append({
            "date": spaeteste,
            "matchday": 99,
            "home_id": vorlage["home_id"],
            "away_id": vorlage["away_id"],
            "home_goals": 3,
            "away_goals": 3,
        })

        self._mit_payload(monkeypatch, api_code, manipuliert)
        neue_zeilen, _ = ds.build_league_season(TEST_LIGA, TEST_SAISON)

        assert len(neue_zeilen) == len(original_zeilen) + 1, (
            "das zusaetzliche Spiel ist nicht angekommen")

        alt_vorher = [z for z in original_zeilen if z["date"] <= stichtag]
        neu_vorher = [z for z in neue_zeilen if z["date"] <= stichtag]

        for alt, neu in zip(alt_vorher, neu_vorher):
            assert alt == neu, (
                f"Zeile {alt['row_id']} hat sich veraendert, obwohl das "
                f"zusaetzliche Spiel erst spaeter stattfindet")

    def test_der_monkeypatch_erreicht_auch_die_zeitleiste(self, monkeypatch):
        """
        Die Zusicherung hinter beiden Tests oben: Der Patch deckt nicht
        nur den Profilpfad ab, sondern auch match_timeline.

        Ohne diesen Nachweis waere offen, ob die Belastungsmerkmale
        ueberhaupt aus dem untergeschobenen Payload stammen.
        """
        import copy

        from src.data.historical_loader import LEAGUE_CODES
        from src.features.match_timeline import build_timeline

        api_code = LEAGUE_CODES[TEST_LIGA]
        _, original_payload = self._stichtag_und_original()

        vorher, _ = build_timeline([TEST_SAISON])
        anzahl_vorher = sum(1 for e in vorher if e.get("competition") == "BL1")

        leer = copy.deepcopy(original_payload)
        leer["matches"] = []
        self._mit_payload(monkeypatch, api_code, leer)

        nachher, _ = build_timeline([TEST_SAISON])
        anzahl_nachher = sum(1 for e in nachher if e.get("competition") == "BL1")

        assert anzahl_vorher > 0
        assert anzahl_nachher == 0, (
            "der Patch erreicht die Zeitleiste nicht - die "
            "Belastungsmerkmale kaemen dann aus der echten Datei")

    def test_profilwerte_haengen_am_stichtag_nicht_am_endstand(self, zeilen):
        """
        Ein Team, dessen Saison stark schwankt, muss ueber die Saison
        verschiedene Profilwerte tragen. Waeren ueberall die Endwerte
        eingesetzt, waeren sie konstant.
        """
        nach_team = {}
        for zeile in zeilen:
            nach_team.setdefault(zeile["home_id"], []).append(
                zeile["home_points_per_game"])

        veraenderlich = [tid for tid, werte in nach_team.items()
                         if len(set(w for w in werte if w is not None)) > 1]
        assert veraenderlich, "alle Profile konstant - Verdacht auf Endstand"


# ---------------------------------------------------------------------------
# Aufwaermlogik
# ---------------------------------------------------------------------------

class TestEvaluationEligible:

    def test_die_zahl_entspricht_dem_backtest(self):
        """
        bl1 2024 steht im Backtestergebnis mit 251 bewerteten Spielen.
        """
        from src.features.go3_backtest import run_backtest

        gebaut, _ = ds.build_league_season(TEST_LIGA, TEST_SAISON)
        auswertbar = sum(1 for z in gebaut if z["evaluation_eligible"])

        backtest = run_backtest(TEST_LIGA, TEST_SAISON)
        assert auswertbar == backtest["variants"]["baseline"]["n"]

    def test_die_aufwaermzahl_entspricht_dem_backtest(self):
        from src.features.go3_backtest import run_backtest

        gebaut, _ = ds.build_league_season(TEST_LIGA, TEST_SAISON)
        aufwaerm = sum(1 for z in gebaut if not z["evaluation_eligible"])

        backtest = run_backtest(TEST_LIGA, TEST_SAISON)
        assert aufwaerm == backtest["skipped_warmup"]

    def test_alle_zeilen_bleiben_erhalten(self, zeilen):
        """
        Der Unterschied zum Backtest: Die Aufwaermphase wird markiert,
        nicht weggeworfen.
        """
        auswertbar = sum(1 for z in zeilen if z["evaluation_eligible"])
        assert auswertbar < len(zeilen)

    def test_die_fruehen_spieltage_sind_die_nicht_auswertbaren(self, zeilen):
        aufwaerm = [z for z in zeilen if not z["evaluation_eligible"]]
        rest = [z for z in zeilen if z["evaluation_eligible"]]
        assert max(z["date"] for z in aufwaerm) <= min(z["date"] for z in rest)

    def test_eine_hoehere_grenze_markiert_mehr_zeilen(self):
        wenig, _ = ds.build_league_season(TEST_LIGA, TEST_SAISON,
                                          min_matchday=2)
        viel, _ = ds.build_league_season(TEST_LIGA, TEST_SAISON,
                                         min_matchday=10)
        assert (sum(1 for z in wenig if z["evaluation_eligible"])
                > sum(1 for z in viel if z["evaluation_eligible"]))


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------

class TestBaselineStimmtMitDemBacktest:

    def test_lambdas_stimmen_mit_dem_backtest_ueberein(self):
        """
        DER Test dieser Datei.

        Fuer dieselbe Partie wird der Backtestpfad nachgebaut und mit der
        Datensatzzeile verglichen. Weichen die Lambdas ab, misst der
        Backtest etwas anderes, als das Modell lernt.
        """
        from datetime import datetime

        from src.data.historical_loader import LEAGUE_CODES, load_season
        from src.features.go3_backtest import outcome_probabilities
        from src.features.team_profile import (
            build_season_profiles, expected_goals, neutral_profile)

        gebaut, _ = ds.build_league_season(TEST_LIGA, TEST_SAISON)
        payload = load_season(LEAGUE_CODES[TEST_LIGA], TEST_SAISON)

        # Stichprobe ueber die ganze Saison, nicht nur der Anfang.
        proben = gebaut[::37]
        assert len(proben) >= 5

        for zeile in proben:
            aufbau = build_season_profiles(payload, cutoff=zeile["date"])
            profile, schnitt = aufbau["profiles"], aufbau["league_avg"]

            heim = profile.get(zeile["home_id"]) or neutral_profile(zeile["home_id"])
            gast = profile.get(zeile["away_id"]) or neutral_profile(zeile["away_id"])
            xh, xa = expected_goals(heim, gast, schnitt)
            p = outcome_probabilities(xh, xa)

            assert zeile["baseline_lambda_home"] == xh, zeile["row_id"]
            assert zeile["baseline_lambda_away"] == xa, zeile["row_id"]
            assert zeile["baseline_p_home"] == p[0], zeile["row_id"]
            assert zeile["baseline_p_draw"] == p[1], zeile["row_id"]
            assert zeile["baseline_p_away"] == p[2], zeile["row_id"]

    def test_die_kennzahlen_treffen_den_backtest(self):
        """
        Die Probe aufs Ganze: Rechnet man LogLoss ueber die auswertbaren
        Zeilen, muss der Backtestwert herauskommen.
        """
        from src.features.go3_backtest import run_backtest

        gebaut, _ = ds.build_league_season(TEST_LIGA, TEST_SAISON)
        eigene = ds.baseline_metrics(gebaut)
        backtest = run_backtest(TEST_LIGA, TEST_SAISON)["variants"]["baseline"]

        assert eigene["n"] == backtest["n"]
        assert round(eigene["log_loss"], 6) == backtest["log_loss"]
        assert round(eigene["brier"], 6) == backtest["brier"]
        assert round(eigene["rps"], 6) == backtest["rps"]

    def test_die_wahrscheinlichkeiten_summieren_sich_auf_eins(self, zeilen):
        for zeile in zeilen:
            summe = (zeile["baseline_p_home"] + zeile["baseline_p_draw"]
                     + zeile["baseline_p_away"])
            assert abs(summe - 1.0) < 1e-9, zeile["row_id"]

    def test_die_lambdas_sind_positiv(self, zeilen):
        for zeile in zeilen:
            assert zeile["baseline_lambda_home"] > 0
            assert zeile["baseline_lambda_away"] > 0

    def test_das_ergebnis_passt_zu_den_toren(self, zeilen):
        for zeile in zeilen:
            h, a = zeile["home_goals"], zeile["away_goals"]
            erwartet = 0 if h > a else (1 if h == a else 2)
            assert zeile["outcome"] == erwartet


# ---------------------------------------------------------------------------
# Kaltstart
# ---------------------------------------------------------------------------

class TestKaltstart:

    def test_aufsteiger_sind_sichtbar(self, zeilen):
        """
        14 Aufsteiger je Saison ueber alle fuenf Ligen. Sie starten ohne
        Historie und bekommen ein neutrales Profil - das muss an
        matches_used ablesbar sein, nicht verborgen.
        """
        kalt = [z for z in zeilen
                if not z["home_matches_used"] or not z["away_matches_used"]]
        assert kalt, "kein einziger Kaltstartfall - unerwartet"

    def test_die_diagnose_zaehlt_kaltstarts(self):
        _, info = ds.build_league_season(TEST_LIGA, TEST_SAISON)
        assert info.get("kaltstart", 0) > 0

    def test_neutrale_profile_werden_gezaehlt(self):
        _, info = ds.build_league_season(TEST_LIGA, TEST_SAISON)
        assert "neutrales_profil" in info


# ---------------------------------------------------------------------------
# Keine verbotenen Quellen
# ---------------------------------------------------------------------------

class TestNurGetrackteQuellen:
    """
    Der Datensatz muss aus einem frischen Checkout erzeugbar sein.
    data/player_pool, data/cache und data/big_games stehen in
    .gitignore - wer sie benutzt, baut etwas, das niemand sonst
    reproduzieren kann.
    """

    def _quelltext(self):
        pfad = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "src", "ml", "dataset.py")
        with open(pfad, encoding="utf-8") as datei:
            return datei.read()

    def _importierte_module(self):
        """
        Alle importierten Modulnamen - ueber den Syntaxbaum, nicht ueber
        eine Textsuche.

        Der Unterschied ist nicht akademisch: Der Modulkopf von
        dataset.py erklaert ausdruecklich, WARUM data/player_pool
        ausgeschlossen ist. Eine Textsuche findet das Wort dort und
        faellt um, obwohl der Code sauber ist. Genau das ist beim ersten
        Lauf passiert.
        """
        import ast

        baum = ast.parse(self._quelltext())
        namen = set()
        for knoten in ast.walk(baum):
            if isinstance(knoten, ast.Import):
                namen.update(a.name for a in knoten.names)
            elif isinstance(knoten, ast.ImportFrom):
                if knoten.module:
                    namen.add(knoten.module)
                namen.update(f"{knoten.module}.{a.name}"
                             for a in knoten.names if knoten.module)
        return namen

    @pytest.mark.parametrize("verboten", [
        "go45_provider", "go5", "go4", "transfer_events",
        "player_importance", "player_quality", "player_pool",
    ])
    def test_kein_go5_bezug_in_den_importen(self, verboten):
        """GO5 und der Spielerpool gehoeren nicht in Phase 1."""
        treffer = [m for m in self._importierte_module() if verboten in m]
        assert treffer == [], f"{verboten} importiert: {treffer}"

    def test_nur_erwartete_projektmodule_werden_benutzt(self):
        """
        Die Gegenprobe: Was importiert wird, muss der dokumentierten
        Liste im Modulkopf entsprechen.
        """
        erlaubt = {
            "src.data.historical_loader",
            "src.features.go3_backtest",
            "src.features.go3_provider",
            "src.features.match_timeline",
            "src.features.team_profile",
            "src.features.workload",
            # V2-C4. form rechnet ausschliesslich auf der Zeitleiste
            # und liest keine Datei.
            "src.features.form",
            # uefa_strength KANN aus data/big_games lesen - dieser
            # Bestand ist gitignoriert. Genau deshalb ist die Quelle
            # abwaehlbar und standardmaessig AUS
            # (dataset.INCLUDE_UEFA_BY_DEFAULT). Der Test
            # test_es_wird_nur_aus_data_historical_gelesen prueft
            # unveraendert, dass der Standardbau nichts anderes
            # anfasst.
            "src.features.uefa_strength",
            "src.features.pit_profiles",
            # Schwestermodul fuer die CL-Zeilen. Es liest ebenfalls
            # ausschliesslich aus data/historical - eine eigene
            # Testklasse prueft das dort gesondert.
            "src.ml.cl_dataset",
        }
        projektmodule = {m for m in self._importierte_module()
                         if m.startswith("src.") and m.count(".") <= 2}
        assert projektmodule <= erlaubt, (
            f"unerwartete Projektmodule: {sorted(projektmodule - erlaubt)}")

    def test_es_wird_nur_aus_data_historical_gelesen(self, monkeypatch):
        """
        Die harte Zusicherung: Jeder Lesezugriff ausserhalb von
        data/historical faellt sofort auf.
        """
        import builtins

        original = builtins.open
        gelesen = []

        def beobachtet(pfad, *args, **kwargs):
            text = str(pfad).replace("\\", "/")
            if "/data/" in text or text.startswith("data/"):
                gelesen.append(text)
            return original(pfad, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", beobachtet)
        ds.build_league_season(TEST_LIGA, TEST_SAISON)

        fremd = [p for p in gelesen if "data/historical" not in p]
        assert fremd == [], f"unerlaubte Quelle gelesen: {sorted(set(fremd))[:5]}"

    def test_die_gelesenen_dateien_sind_getrackt(self):
        """
        Was der Datensatz braucht, muss im Repository liegen.
        """
        import subprocess

        getrackt = set(subprocess.run(
            ["git", "ls-files", "data/historical"],
            capture_output=True, text=True, timeout=60).stdout.split())
        assert getrackt, "data/historical ist nicht versioniert"
        assert any("BL1_2024" in p for p in getrackt)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCli:

    def _args(self, argv):
        return run_ml.build_parser().parse_args(argv)

    def test_ohne_aufgabe_passiert_nichts(self):
        assert run_ml.main([]) == 2

    def test_standardwerte(self):
        args = self._args(["--build-dataset"])
        assert args.leagues == ["bl1", "pl", "pd", "sa", "fl1"]
        assert args.seasons == [2023, 2024, 2025]
        assert args.min_matchday == 6
        assert args.output is None
        assert args.force is False

    def test_ligen_und_saisons_werden_zerlegt(self):
        args = self._args(["--build-dataset", "--leagues", "bl1, pl",
                           "--seasons", "2024,2025"])
        assert args.leagues == ["bl1", "pl"]
        assert args.seasons == [2024, 2025]

    def test_unsinnige_saison_wird_abgewiesen(self):
        with pytest.raises(SystemExit):
            self._args(["--build-dataset", "--seasons", "zweitausend"])

    def test_force_ohne_output_wird_abgewiesen(self):
        assert run_ml.main(["--build-dataset", "--force"]) == 2

    def test_negativer_min_matchday_wird_abgewiesen(self):
        assert run_ml.main(["--build-dataset", "--min-matchday", "-1"]) == 2

    def test_ohne_output_wird_nichts_geschrieben(self, monkeypatch):
        geschrieben = []
        monkeypatch.setattr(run_ml, "write_payload",
                            lambda *a, **k: geschrieben.append(a) or True)

        code = run_ml.main(["--build-dataset", "--leagues", TEST_LIGA,
                            "--seasons", str(TEST_SAISON), "--no-coverage"])
        assert code == 0
        assert geschrieben == [], "ohne --output darf nichts geschrieben werden"

    def test_mit_output_entsteht_eine_datei(self, tmp_path):
        ziel = tmp_path / "datensatz.json"
        code = run_ml.main(["--build-dataset", "--leagues", TEST_LIGA,
                            "--seasons", str(TEST_SAISON), "--no-coverage",
                            "--output", str(ziel)])
        assert code == 0 and ziel.exists()

        inhalt = json.loads(ziel.read_text(encoding="utf-8"))
        assert set(inhalt) == {"manifest", "schema", "rows", "diagnostics"}

    def test_ueberschreibt_nicht_ohne_force(self, tmp_path):
        ziel = tmp_path / "datensatz.json"
        ziel.write_text("URSPRUNG", encoding="utf-8")

        code = run_ml.main(["--build-dataset", "--leagues", TEST_LIGA,
                            "--seasons", str(TEST_SAISON), "--no-coverage",
                            "--output", str(ziel)])
        assert code == 1
        assert ziel.read_text(encoding="utf-8") == "URSPRUNG"

    def test_ueberschreibt_mit_force(self, tmp_path):
        ziel = tmp_path / "datensatz.json"
        ziel.write_text("URSPRUNG", encoding="utf-8")

        code = run_ml.main(["--build-dataset", "--leagues", TEST_LIGA,
                            "--seasons", str(TEST_SAISON), "--no-coverage",
                            "--output", str(ziel), "--force"])
        assert code == 0
        assert ziel.read_text(encoding="utf-8") != "URSPRUNG"

    def test_hinterlaesst_keine_temporaerdatei(self, tmp_path):
        ziel = tmp_path / "datensatz.json"
        run_ml.main(["--build-dataset", "--leagues", TEST_LIGA,
                     "--seasons", str(TEST_SAISON), "--no-coverage",
                     "--output", str(ziel)])
        assert not (tmp_path / "datensatz.json.tmp").exists()


class TestManifest:

    def _payload(self):
        zeilen, diagnose = ds.build_dataset([TEST_LIGA], [TEST_SAISON])
        return run_ml.build_payload([TEST_LIGA], [TEST_SAISON], 6,
                                    zeilen, diagnose)

    @pytest.mark.parametrize("feld", [
        "schema_version", "git_commit", "git_dirty", "git_status",
        "leagues", "seasons", "min_matchday", "total_rows",
        "evaluation_eligible_rows", "columns", "created_at",
        "python_version", "data_sources",
    ])
    def test_das_manifest_traegt_die_geforderten_felder(self, feld):
        assert feld in self._payload()["manifest"], feld

    def test_die_quellen_stehen_ausdruecklich_drin(self):
        manifest = self._payload()["manifest"]
        assert manifest["data_sources"] == ["data/historical"]
        assert any("player_pool" in e for e in manifest["excluded_sources"])

    def test_zeilen_und_schema_sind_frei_von_zeitstempeln(self):
        """
        Die Trennung wie beim Backtestlaeufer: Alles Variable steht im
        Manifest, damit zwei Laeufe an rows und schema vergleichbar sind.
        """
        payload = self._payload()
        text = json.dumps({"rows": payload["rows"],
                           "schema": payload["schema"]})
        assert "created_at" not in text

    def test_zwei_payloads_haben_gleiche_zeilen(self):
        a, b = self._payload(), self._payload()
        assert json.dumps(a["rows"], sort_keys=True) == \
               json.dumps(b["rows"], sort_keys=True)
        assert a["schema"] == b["schema"]

    def test_das_schema_kennt_jede_spalte_genau_einmal(self):
        namen = [e["name"] for e in ds.build_schema()]
        assert len(namen) == len(set(namen))
        assert namen == ds.SPALTEN

    def test_identifikatoren_sind_als_solche_markiert(self):
        """
        Ein Modell, das aus row_id lernt, lernt die Vergangenheit
        auswendig. Die Rolle muss das verhindern koennen.
        """
        rollen = {e["name"]: e["role"] for e in ds.build_schema()}
        for name in ("row_id", "match_id", "league", "season", "date",
                     "matchday", "home_id", "away_id", "evaluation_eligible"):
            assert rollen[name] == "identifier", name

    def test_targets_sind_als_solche_markiert(self):
        rollen = {e["name"]: e["role"] for e in ds.build_schema()}
        for name in ("home_goals", "away_goals", "outcome"):
            assert rollen[name] == "target", name

    def test_diagnosefelder_sind_keine_merkmale(self):
        rollen = {e["name"]: e["role"] for e in ds.build_schema()}
        for seite in ("home", "away"):
            for feld in ds.DIAGNOSE_FELDER:
                assert rollen[f"{seite}_{feld}"] == "diagnostic"


class TestMissingness:

    def test_fehlende_werte_werden_gezaehlt(self, zeilen):
        fehlend = ds.missingness(zeilen)
        assert set(fehlend) == set(ds.SPALTEN)
        assert fehlend["match_id"] == len(zeilen)

    def test_qualitaetsfelder_bleiben_text(self, zeilen):
        """
        "partial" ist keine 0.5. Die Umdeutung gehoert in eine Pipeline,
        nicht in den Datensatz.
        """
        for zeile in zeilen[:20]:
            for seite in ("home", "away"):
                wert = zeile[f"{seite}_data_quality"]
                assert wert is None or isinstance(wert, str), wert


# ---------------------------------------------------------------------------
# 8. Champions-League-Zeilen im Gesamtdatensatz (C1)
# ---------------------------------------------------------------------------

class TestClImDatensatz:

    def test_die_schemafassung_wurde_erhoeht(self):
        """
        Sieben neue Spalten sind ein Formwechsel. Ohne Erhoehung
        trueegen zwei verschieden aufgebaute Datensaetze dieselbe
        Fassungsnummer.
        """
        assert ds.SCHEMA_VERSION >= 2

    def test_die_herkunftsspalten_stehen_im_schema(self):
        namen = {e["name"] for e in ds.build_schema()}
        for spalte in ("competition", "stage", "exclusion_reason",
                       "league_avg_source", "home_profile_source",
                       "away_profile_source", "home_profile_matches",
                       "away_profile_matches"):
            assert spalte in namen

    def test_herkunft_wird_niemals_modellmerkmal(self):
        """
        Ein Modell, das aus competition oder profile_source lernt,
        lernt die Datenbeschaffung auswendig.
        """
        rollen = {e["name"]: e["role"] for e in ds.build_schema()}
        for spalte in ("competition", "stage", "exclusion_reason",
                       "league_avg_source", "home_profile_source",
                       "away_profile_source", "home_profile_matches",
                       "away_profile_matches"):
            assert rollen[spalte] == "provenance"
        assert not [s for s in mdl.feature_columns()
                    if rollen.get(s) == "provenance"]

    def test_jede_ausgeschlossene_spalte_hat_weiterhin_eine_begruendung(self):
        ausgeschlossen = {e["column"] for e in mdl.excluded_columns()}
        merkmale = set(mdl.feature_columns())
        alle = {e["name"] for e in ds.build_schema()}
        assert merkmale | ausgeschlossen == alle

    def test_ligazeilen_tragen_ihre_herkunft(self):
        zeilen, _ = ds.build_dataset([TEST_LIGA], [TEST_SAISON])
        for zeile in zeilen:
            assert zeile["competition"] == "BL1"
            assert zeile["stage"] is None
            assert zeile["home_profile_source"] == ds.LEAGUE_PROFILE_SOURCE
            assert zeile["league_avg_source"] == ds.LEAGUE_AVG_SOURCE

    def test_ohne_flag_entstehen_keine_cl_zeilen(self):
        zeilen, diagnose = ds.build_dataset([TEST_LIGA], [TEST_SAISON])
        assert not [z for z in zeilen if z["league"] == "cl"]
        assert diagnose["champions_league"] is None

    def test_mit_flag_entstehen_cl_zeilen(self):
        zeilen, diagnose = ds.build_dataset([TEST_LIGA], [2024],
                                            include_cl=True)
        cl_zeilen = [z for z in zeilen if z["league"] == "cl"]
        assert cl_zeilen
        assert diagnose["champions_league"]["rows"] == len(cl_zeilen)

    def test_ligazeilen_bleiben_bitgenau_unveraendert(self):
        """
        Der wichtigste Test dieses Blocks: Das Hinzunehmen der
        CL-Zeilen darf keine einzige Zahl einer Ligazeile beruehren.
        Verglichen wird jede Spalte ausser den neuen Herkunftsfeldern -
        und die neuen sind fuer Ligazeilen ohnehin konstant.
        """
        ohne, _ = ds.build_dataset([TEST_LIGA], [2024])
        mit, _ = ds.build_dataset([TEST_LIGA], [2024], include_cl=True)
        mit_liga = [z for z in mit if z["league"] != "cl"]

        assert len(ohne) == len(mit_liga)
        for a, b in zip(sorted(ohne, key=lambda z: z["row_id"]),
                        sorted(mit_liga, key=lambda z: z["row_id"])):
            assert a == b, f"Ligazeile veraendert: {a['row_id']}"

    def test_cl_zeilen_stoeren_die_ligakennzahlen_nicht(self):
        """
        Die Gegenprobe in Zahlen: Die Baseline-Kennzahlen der
        Ligazeilen muessen mit und ohne CL identisch sein.
        """
        ohne, _ = ds.build_dataset([TEST_LIGA], [2024])
        mit, _ = ds.build_dataset([TEST_LIGA], [2024], include_cl=True)
        nur_liga = [z for z in mit if z["league"] != "cl"]
        assert ds.baseline_metrics(ohne) == ds.baseline_metrics(nur_liga)

    def test_die_sortierung_bleibt_vollstaendig_bestimmt(self):
        zeilen, _ = ds.build_dataset([TEST_LIGA], [2024], include_cl=True)
        schluessel = [(z["league"], z["season"], z["date"], z["row_id"])
                      for z in zeilen]
        assert schluessel == sorted(schluessel)

    def test_zwei_builds_mit_cl_sind_identisch(self):
        erst, _ = ds.build_dataset([TEST_LIGA], [2024], include_cl=True)
        zweit, _ = ds.build_dataset([TEST_LIGA], [2024], include_cl=True)
        assert erst == zweit


# ---------------------------------------------------------------------------
# 9. Der matches_used-Verteilungsbruch (C2)
# ---------------------------------------------------------------------------

class TestVerteilungsbruch:

    @staticmethod
    def _spanne(zeilen, spalte):
        werte = [z[spalte] for z in zeilen if z.get(spalte) is not None]
        return (min(werte), max(werte)) if werte else None

    def test_der_bruch_ist_im_cl_kandidaten_beseitigt(self):
        """
        Jede Spalte des CL-Kandidaten muss auf CL-Zeilen in derselben
        Spanne liegen wie im Ligatraining. Genau das war bei
        matches_used nicht der Fall - 95 % der Werte lagen ausserhalb.
        """
        from src.ml import feature_groups as fg

        liga, _ = ds.build_dataset([TEST_LIGA], [2024])
        cl_zeilen, _, _ = clds.build_cl_dataset([2024])

        draussen = {}
        for spalte in fg.columns_for(fg.CL_PRIMARY_CANDIDATE):
            spanne = self._spanne(liga, spalte)
            if spanne is None:
                continue
            lo, hi = spanne
            n = sum(1 for z in cl_zeilen
                    if z.get(spalte) is not None
                    and not (lo <= z[spalte] <= hi))
            if n:
                draussen[spalte] = n / len(cl_zeilen)

        schlimmste = max(draussen.values()) if draussen else 0.0
        assert schlimmste < 0.10, (
            f"Spalten ausserhalb der Ligaspanne: "
            f"{ {k: round(v, 3) for k, v in draussen.items()} }")

    def test_die_gegenprobe_zeigt_den_bruch_bei_matches_used(self):
        """
        Ohne diesen Test koennte der Test oben auch dann gruen sein,
        wenn gar kein Bruch existierte. matches_used steht bewusst
        NICHT im Kandidaten - hier wird gezeigt, warum.
        """
        liga, _ = ds.build_dataset([TEST_LIGA], [2024])
        cl_zeilen, _, _ = clds.build_cl_dataset([2024])

        lo, hi = self._spanne(liga, "home_matches_used")
        draussen = sum(1 for z in cl_zeilen
                       if z.get("home_matches_used") is not None
                       and not (lo <= z["home_matches_used"] <= hi))
        assert draussen > 0, (
            "kein einziger Wert ausserhalb - dann braeuchte es die "
            "Trennung von profile_depth nicht")

    def test_matches_used_bleibt_als_spalte_erhalten(self):
        """
        Entfernt wird es aus dem KANDIDATEN, nicht aus dem Datensatz -
        als Auswertungsgroesse ist es weiterhin nuetzlich.
        """
        assert "home_matches_used" in ds.SPALTEN
        assert "away_matches_used" in ds.SPALTEN
