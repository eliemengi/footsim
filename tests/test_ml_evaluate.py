"""
Tests fuer die Walk-forward-Auswertung.

Die Auswertung entscheidet, ob ein Modell besser ist als die Baseline.
Ein Fehler hier faellt nicht auf - er produziert eine plausible Zahl.
Deshalb prueft jeder Test hier eine Eigenschaft, die sich tatsaechlich
verletzen laesst, und mehrere Tests enthalten eine Gegenprobe.
"""

import pytest

from src.ml import dataset as ds
from src.ml import evaluate as ev
from src.ml import model as mdl

SPALTEN = mdl.feature_columns()


# ---------------------------------------------------------------------------
# Bausteine
# ---------------------------------------------------------------------------

def zeile(season, tag, index=0, lam_home=1.30, lam_away=1.10,
          tore_home=1, tore_away=1, eligible=True):
    """
    Eine Zeile mit frei waehlbarem Datum innerhalb einer Saison.

    tag laeuft von 0 aufwaerts und wird auf Kalendertage ab dem
    1. August der Saison abgebildet - so entsteht eine echte zeitliche
    Ordnung, an der sich Foldgrenzen pruefen lassen.
    """
    from datetime import date, timedelta

    datum = (date(season, 8, 1) + timedelta(days=tag)).isoformat()
    daten = {
        "row_id": f"bl1:{season}:{datum}:{index}:{index + 100}",
        "match_id": season * 1000 + index,
        "league": "bl1" if index % 2 == 0 else "pl",
        "season": season,
        "date": datum,
        "matchday": tag // 7 + 1,
        "home_id": index,
        "away_id": index + 100,
        "evaluation_eligible": eligible,
        "home_goals": tore_home,
        "away_goals": tore_away,
        "outcome": (0 if tore_home > tore_away
                    else (1 if tore_home == tore_away else 2)),
        "baseline_lambda_home": lam_home,
        "baseline_lambda_away": lam_away,
    }
    for i, spalte in enumerate(SPALTEN):
        daten[spalte] = 0.1 * ((index * 7 + i * 3 + tag) % 19) + 0.05
    return daten


def saison(season, anzahl=60, **rest):
    """Eine Saison mit gleichmaessig verteilten Spieltagen."""
    return [zeile(season, tag=i * 4, index=i, **rest) for i in range(anzahl)]


def drei_saisons(**rest):
    return saison(2023, **rest) + saison(2024, **rest) + saison(2025, **rest)


class StubPipeline:
    """Ein Modell mit vorgegebenem Korrekturfaktor - fuer Auswahltests."""

    def __init__(self, faktor):
        self.faktor = faktor

    def predict(self, X):
        import numpy as np
        return np.full(len(X), self.faktor, dtype=float)


# ---------------------------------------------------------------------------
# 1. Zeitliche Ordnung der aeusseren Folds
# ---------------------------------------------------------------------------

class TestAeussereFolds:

    def test_die_folds_stehen_wie_festgelegt(self):
        assert [f["train_seasons"] for f in ev.OUTER_FOLDS] \
            == [[2023], [2023, 2024]]
        assert [f["test_seasons"] for f in ev.OUTER_FOLDS] \
            == [[2024], [2025]]

    def test_keine_spaetere_saison_liegt_im_training(self):
        for fold in ev.OUTER_FOLDS:
            assert max(fold["train_seasons"]) < min(fold["test_seasons"]), fold

    def test_kein_fold_trainiert_je_auf_seiner_testsaison(self, monkeypatch):
        """
        Nicht am Konstantenwert gemessen, sondern an dem, was beim
        Anpassen tatsaechlich ankommt.

        Waere die Zeitgrenze irgendwo im Ablauf undicht, stuende hier
        eine Testsaison in der Aufzeichnung.
        """
        gesehen = []
        original = mdl.fit_side

        def merken(zeilen, seite, alpha, spalten=None):
            gesehen.append({z["season"] for z in zeilen})
            return original(zeilen, seite, alpha, spalten)

        monkeypatch.setattr(mdl, "fit_side", merken)

        zeilen = drei_saisons()
        for fold in ev.OUTER_FOLDS:
            gesehen.clear()
            ev.evaluate_fold(zeilen, fold, SPALTEN, alphas=(1.0,))
            assert gesehen, "es wurde ueberhaupt nicht angepasst"
            verboten = set(fold["test_seasons"])
            for saisons in gesehen:
                assert not (saisons & verboten), (fold["name"], saisons)

    def test_nur_auswertbare_zeilen_gehen_in_die_messung(self):
        """
        Die Aufwaermphase misst die Anlaufzeit der Profile, nicht die
        Guete der Vorhersage.
        """
        zeilen = saison(2024, anzahl=20) + saison(2024, anzahl=20,
                                                  eligible=False)
        passend = ev.eligible_rows(zeilen, [2024])
        assert len(passend) == 20
        assert all(z["evaluation_eligible"] for z in passend)

    def test_die_zeilen_sind_zeitlich_sortiert(self):
        zeilen = list(reversed(saison(2024, anzahl=20)))
        daten = [z["date"] for z in ev.eligible_rows(zeilen, [2024])]
        assert daten == sorted(daten)


# ---------------------------------------------------------------------------
# 2. Die innere Teilung
# ---------------------------------------------------------------------------

class TestInnereTeilung:

    def test_fold_eins_teilt_2023_zeitlich_und_deterministisch(self):
        zeilen = drei_saisons()
        anpassen, validieren, beschreibung = ev.inner_split(
            zeilen, ev.OUTER_FOLDS[0])

        assert beschreibung["strategy"].startswith("zeitliche Teilung")
        assert beschreibung["boundary_rule"] == \
            "mittleres Spieldatum der Trainingssaison"
        assert anpassen and validieren
        # Die Grenze trennt wirklich: kein Anpassdatum liegt auf oder
        # nach einem Validierungsdatum.
        assert max(z["date"] for z in anpassen) \
            < min(z["date"] for z in validieren)
        assert all(z["season"] == 2023 for z in anpassen + validieren)

    def test_dieselbe_teilung_bei_wiederholung_und_bei_umsortierung(self):
        """
        Zweimal dasselbe Ergebnis - auch wenn die Eingabe anders
        sortiert ankommt. Eine Grenze, die von der Reihenfolge abhinge,
        waere nicht reproduzierbar.
        """
        zeilen = drei_saisons()
        erste = ev.inner_split(zeilen, ev.OUTER_FOLDS[0])[2]
        zweite = ev.inner_split(list(reversed(zeilen)),
                                ev.OUTER_FOLDS[0])[2]
        assert erste == zweite
        assert erste["boundary_date"] == zweite["boundary_date"]

    def test_fold_zwei_teilt_nach_saison(self):
        zeilen = drei_saisons()
        anpassen, validieren, beschreibung = ev.inner_split(
            zeilen, ev.OUTER_FOLDS[1])

        assert beschreibung["strategy"] == "Teilung nach Saison"
        assert beschreibung["fit_seasons"] == [2023]
        assert beschreibung["validation_seasons"] == [2024]
        assert {z["season"] for z in anpassen} == {2023}
        assert {z["season"] for z in validieren} == {2024}

    def test_die_innere_validierung_enthaelt_keine_testsaison(self):
        zeilen = drei_saisons()
        for fold in ev.OUTER_FOLDS:
            anpassen, validieren, _ = ev.inner_split(zeilen, fold)
            verboten = set(fold["test_seasons"])
            assert not ({z["season"] for z in anpassen} & verboten)
            assert not ({z["season"] for z in validieren} & verboten)


# ---------------------------------------------------------------------------
# 3. Die Modellwahl
# ---------------------------------------------------------------------------

class TestModellwahl:

    @staticmethod
    def _mit_festen_faktoren(monkeypatch, faktoren):
        def stub(zeilen, seite, alpha, spalten=None):
            return StubPipeline(faktoren[alpha]), {}
        monkeypatch.setattr(mdl, "fit_side", stub)

    def test_gleichstand_geht_an_das_groessere_alpha(self, monkeypatch):
        """
        Der Kern der Gleichstandsregel.

        Aufbau: Alle Partien enden 2:0, die Baseline erwartet aber
        1.30 zu 1.10. Ein Faktor ueber eins auf der Heimseite verbessert
        die Vorhersage also nachweislich. Genau diesen Faktor liefern
        alpha 10.0 UND alpha 100.0 - identisch, also exakter
        Gleichstand. Die kleineren Alphas liefern die Baseline.

        Gewinnen muss 100.0. Eine Auswahl, die aufsteigend prueft und
        nur bei strikter Verbesserung ersetzt, wuerde 10.0 waehlen -
        also die schwaechere Regularisierung. Dieser Test faellt darauf
        nicht herein.
        """
        self._mit_festen_faktoren(monkeypatch, {
            0.01: 1.0, 0.1: 1.0, 1.0: 1.0, 10.0: 1.5, 100.0: 1.5})

        val = saison(2024, anzahl=40, tore_home=2, tore_away=0)
        kandidat, _, protokoll = ev.select_candidate(
            saison(2023, anzahl=40), val, SPALTEN)

        verluste = {e["candidate"]: e["inner_log_loss"]
                    for e in protokoll["candidates"] if "inner_log_loss" in e}
        assert verluste[10.0] == verluste[100.0], "der Aufbau erzeugt keinen Gleichstand"
        assert verluste[100.0] < verluste[mdl.NO_CORRECTION], \
            "der Aufbau erzeugt keine Verbesserung"
        assert kandidat == 100.0

    def test_ein_gleichstand_mit_der_baseline_geht_an_no_correction(
            self, monkeypatch):
        """
        Gegen die Baseline zaehlt nur strikte Verbesserung. Ein Faktor
        von exakt eins ist keine.
        """
        self._mit_festen_faktoren(monkeypatch, dict.fromkeys(
            mdl.ALPHA_CANDIDATES, 1.0))

        kandidat, modelle, protokoll = ev.select_candidate(
            saison(2023, anzahl=30), saison(2024, anzahl=30), SPALTEN)

        assert kandidat == mdl.NO_CORRECTION
        assert modelle is None
        assert protokoll["selected_inner_log_loss"] == \
            protokoll["baseline_inner_log_loss"]

    def test_ein_schlechteres_alpha_gewinnt_nicht(self, monkeypatch):
        self._mit_festen_faktoren(monkeypatch, dict.fromkeys(
            mdl.ALPHA_CANDIDATES, 0.5))
        val = saison(2024, anzahl=40, tore_home=2, tore_away=0)
        kandidat, _, _ = ev.select_candidate(
            saison(2023, anzahl=40), val, SPALTEN)
        assert kandidat == mdl.NO_CORRECTION

    def test_ein_besseres_alpha_gewinnt(self, monkeypatch):
        """
        Gegenprobe zu den beiden Tests darueber: Die Auswahl darf nicht
        einfach immer no_correction sagen.
        """
        self._mit_festen_faktoren(monkeypatch, {
            0.01: 1.0, 0.1: 1.0, 1.0: 1.5, 10.0: 1.0, 100.0: 1.0})
        val = saison(2024, anzahl=40, tore_home=2, tore_away=0)
        kandidat, modelle, _ = ev.select_candidate(
            saison(2023, anzahl=40), val, SPALTEN)
        assert kandidat == 1.0
        assert modelle is not None

    def test_die_baseline_steht_immer_im_protokoll(self, monkeypatch):
        self._mit_festen_faktoren(monkeypatch, dict.fromkeys(
            mdl.ALPHA_CANDIDATES, 1.0))
        _, _, protokoll = ev.select_candidate(
            saison(2023, anzahl=20), saison(2024, anzahl=20), SPALTEN)
        namen = [e["candidate"] for e in protokoll["candidates"]]
        assert mdl.NO_CORRECTION in namen
        assert set(mdl.ALPHA_CANDIDATES) <= set(namen)

    def test_die_auswahl_ist_ueber_laeufe_stabil(self):
        """
        Ohne Stub, mit echter Anpassung: Zwei Laeufe muessen bis auf die
        letzte Stelle dasselbe ergeben. Eine zufaellige Initialisierung
        oder eine Mengenreihenfolge im Ablauf faellt hier auf.
        """
        anpassen = saison(2023, anzahl=50)
        validieren = saison(2024, anzahl=50)

        erste = ev.select_candidate(anpassen, validieren, SPALTEN,
                                    alphas=(0.1, 10.0))
        zweite = ev.select_candidate(anpassen, validieren, SPALTEN,
                                     alphas=(0.1, 10.0))
        assert erste[0] == zweite[0]
        assert erste[2]["candidates"] == zweite[2]["candidates"]

    def test_die_alphakandidaten_stehen_vorab_fest(self):
        assert mdl.ALPHA_CANDIDATES == (0.01, 0.1, 1.0, 10.0, 100.0)


# ---------------------------------------------------------------------------
# 4. Die Baseline wird zifferngenau reproduziert
# ---------------------------------------------------------------------------

class TestBaselineReproduktion:

    def test_no_correction_liefert_exakt_die_baseline(self):
        """
        Mit leerer Alphaliste bleibt nur no_correction. Dann muss jede
        Differenz exakt null sein - nicht ungefaehr null.
        """
        zeilen = drei_saisons()
        ergebnis = ev.evaluate_fold(zeilen, ev.OUTER_FOLDS[0], SPALTEN,
                                    alphas=())

        assert ergebnis["selected_candidate"] == mdl.NO_CORRECTION
        assert ergebnis["delta_log_loss"] == 0.0
        assert ergebnis["delta_brier"] == 0.0
        assert ergebnis["delta_rps"] == 0.0
        assert ergebnis["avg_probability_change"] == 0.0
        assert ergebnis["max_probability_change"] == 0.0
        assert ergebnis["ml"]["log_loss"] == ergebnis["baseline"]["log_loss"]
        assert ergebnis["ml"]["calibration_error"] == \
            ergebnis["baseline"]["calibration_error"]
        assert ergebnis["clamps"]["clamped_home"] == 0
        assert ergebnis["clamps"]["clamped_away"] == 0

    def test_die_auswertung_trifft_die_gespeicherte_baseline_des_datensatzes(
            self):
        """
        Eine Probe an echten Daten - und zugleich ein Vergleich zweier
        unabhaengiger Wege.

        baseline_metrics rechnet mit den GESPEICHERTEN
        Wahrscheinlichkeiten aus dem Datensatz. Die Auswertung rechnet
        sie aus den Lambdas NEU. Stimmen beide ueberein, ist der
        Vergleichsmassstab derselbe wie im Backtest.
        """
        zeilen, _ = ds.build_league_season("bl1", 2024)
        auswertbar = [z for z in zeilen if z["evaluation_eligible"]]

        erwartet = ds.baseline_metrics(zeilen)
        gemessen = ev.summarise(
            ev.probabilities_for(mdl.baseline_lambdas(auswertbar)),
            [z["outcome"] for z in auswertbar])

        assert gemessen["n"] == erwartet["n"]
        assert gemessen["log_loss"] == pytest.approx(erwartet["log_loss"],
                                                     abs=1e-12)
        assert gemessen["brier"] == pytest.approx(erwartet["brier"], abs=1e-12)
        assert gemessen["rps"] == pytest.approx(erwartet["rps"], abs=1e-12)


# ---------------------------------------------------------------------------
# 5. Wahrscheinlichkeiten
# ---------------------------------------------------------------------------

class TestWahrscheinlichkeiten:

    @pytest.mark.parametrize("lam_home,lam_away", [
        (0.05, 0.05), (1.0, 1.0), (1.37, 1.12), (6.0, 0.05), (0.05, 6.0),
        (3.4, 2.9)])
    def test_die_drei_ausgaenge_summieren_sich_zu_eins(self, lam_home,
                                                       lam_away):
        (p,) = ev.probabilities_for([(lam_home, lam_away)])
        assert sum(p) == pytest.approx(1.0, abs=1e-9)
        assert all(0.0 <= wert <= 1.0 for wert in p)

    def test_es_wird_der_bestehende_poisson_pfad_benutzt(self):
        """
        Keine zweite Poisson-Umsetzung. Waere hier eine eigene Formel
        entstanden, koennte sie unbemerkt von der Produktion abweichen.
        """
        from src.features.go3_backtest import outcome_probabilities
        assert ev.probabilities_for([(1.4, 1.1)]) == \
            [outcome_probabilities(1.4, 1.1)]


# ---------------------------------------------------------------------------
# 6. Vorzeichen der Differenz
# ---------------------------------------------------------------------------

def kunstfold(name, anzahl, basis_wert, ml_wert):
    """Ein Foldergebnis mit vorgegebenen Verlusten je Spiel."""
    def verluste(wert):
        return {schluessel: [wert] * anzahl
                for schluessel in ("log_loss", "brier", "rps")}

    return {
        "fold": name,
        "_internal": {
            "baseline_losses": verluste(basis_wert),
            "ml_losses": verluste(ml_wert),
            "baseline_calibration": {5: [0.5 * anzahl, anzahl // 2, anzahl]},
            "ml_calibration": {5: [0.5 * anzahl, anzahl // 2, anzahl]},
            "leagues": ["bl1"] * anzahl,
            "seasons": [2024] * anzahl,
        },
    }


class TestVorzeichen:

    def test_schlechteres_ml_ergibt_ein_positives_delta(self):
        zusammen = ev.aggregate([kunstfold("a", 50, 1.0, 1.5)])
        assert zusammen["delta_log_loss"] == pytest.approx(0.5)

    def test_besseres_ml_ergibt_ein_negatives_delta(self):
        zusammen = ev.aggregate([kunstfold("a", 50, 1.5, 1.0)])
        assert zusammen["delta_log_loss"] == pytest.approx(-0.5)

    def test_gleichstand_ergibt_genau_null(self):
        zusammen = ev.aggregate([kunstfold("a", 50, 1.2, 1.2)])
        assert zusammen["delta_log_loss"] == 0.0

    def test_das_vorzeichen_gilt_auch_je_fold(self):
        zeilen = drei_saisons()
        ergebnis = ev.evaluate_fold(zeilen, ev.OUTER_FOLDS[0], SPALTEN,
                                    alphas=())
        assert ergebnis["delta_log_loss"] == \
            ergebnis["ml"]["log_loss"] - ergebnis["baseline"]["log_loss"]


# ---------------------------------------------------------------------------
# 7. Aggregation
# ---------------------------------------------------------------------------

class TestAggregation:

    def test_es_wird_nach_spielen_gewichtet_nicht_nach_folds(self):
        """
        Der Unterschied ist gross und leicht zu uebersehen.

        Fold A: 10 Spiele ohne Unterschied. Fold B: 90 Spiele, ML um 1.0
        schlechter. Ein ungewichteter Foldmittelwert ergaebe 0.5. Richtig
        ist 0.9, weil neun von zehn Spielen aus Fold B stammen.
        """
        zusammen = ev.aggregate([kunstfold("a", 10, 1.0, 1.0),
                                 kunstfold("b", 90, 1.0, 2.0)])
        assert zusammen["n"] == 100
        assert zusammen["delta_log_loss"] == pytest.approx(0.9)
        assert zusammen["delta_log_loss"] != pytest.approx(0.5)

    def test_die_aufschluesselung_laeuft_ueber_beide_folds(self):
        """
        Eine Aufschluesselung je Fold allein wuerde verbergen, ob eine
        Liga durchgaengig verliert oder nur in einem Fold. Hier wird
        geprueft, dass die Gruppen die Foldgrenze ueberschreiten.
        """
        ergebnis = ev.run_evaluation(drei_saisons(), alphas=(1.0,))
        zusammen = ergebnis["aggregate"]

        ligen = {e["league"]: e["n"] for e in zusammen["per_league"]}
        assert set(ligen) == {"bl1", "pl"}
        assert sum(ligen.values()) == zusammen["n"]

        saisons = {e["season"]: e["n"] for e in zusammen["per_test_season"]}
        # Genau die Testsaisons der beiden Folds, keine Trainingssaison.
        assert set(saisons) == {2024, 2025}
        assert sum(saisons.values()) == zusammen["n"]

        for eintrag in zusammen["per_league"] + zusammen["per_test_season"]:
            assert eintrag["delta_log_loss"] == pytest.approx(
                eintrag["ml_log_loss"] - eintrag["baseline_log_loss"])

    def test_ein_fold_mit_fehler_wird_uebersprungen(self):
        zusammen = ev.aggregate([{"fold": "kaputt", "error": "zu wenig Daten"},
                                 kunstfold("b", 20, 1.0, 1.0)])
        assert zusammen["n"] == 20

    def test_ohne_brauchbaren_fold_gibt_es_kein_ergebnis(self):
        assert ev.aggregate([{"fold": "x", "error": "leer"}]) is None


# ---------------------------------------------------------------------------
# 8. Kalibrierung
# ---------------------------------------------------------------------------

class TestKalibrierung:

    def test_der_betrag_wird_erst_nach_dem_zusammenfuehren_gebildet(self):
        """
        Genau dieser Fehler musste im Backtestlaeufer schon einmal
        korrigiert werden.

        Zwei Bestaende weichen im selben Bin um dasselbe Mass in
        ENTGEGENGESETZTE Richtung ab. Zusammengefuehrt heben sie sich
        auf: der Fehler ist null. Wer die Einzelfehler mittelt, erhaelt
        0.15 - eine Abweichung, die es in den Daten nicht gibt.
        """
        zu_hoch = {5: [55.0, 40, 100]}
        zu_niedrig = {5: [55.0, 70, 100]}

        einzeln_hoch, _ = ev.pooled_calibration_error(zu_hoch)
        einzeln_niedrig, _ = ev.pooled_calibration_error(zu_niedrig)
        assert einzeln_hoch == pytest.approx(0.15)
        assert einzeln_niedrig == pytest.approx(0.15)

        gepoolt, _ = ev.pooled_calibration_error(
            ev.merge_calibration_sums([zu_hoch, zu_niedrig]))
        assert gepoolt == pytest.approx(0.0, abs=1e-12)
        assert gepoolt < (einzeln_hoch + einzeln_niedrig) / 2

    def test_gleichgerichtete_abweichungen_bleiben_erhalten(self):
        """
        Gegenprobe: Das Zusammenfuehren darf nicht generell alles zu
        null rechnen.
        """
        gepoolt, _ = ev.pooled_calibration_error(ev.merge_calibration_sums(
            [{5: [55.0, 40, 100]}, {5: [55.0, 40, 100]}]))
        assert gepoolt == pytest.approx(0.15)

    def test_die_bins_stammen_aus_den_vorhergesagten_wahrscheinlichkeiten(self):
        wahrscheinlichkeiten = [(0.5, 0.3, 0.2)]
        summen = ev.calibration_sums(wahrscheinlichkeiten, [0])
        # Drei Klassenbeobachtungen je Partie, verteilt auf ihre Bins.
        assert sum(eintrag[2] for eintrag in summen.values()) == 3
        assert summen[5][1] == 1     # der eingetretene Ausgang liegt in Bin 5
        assert summen[3][1] == 0
        assert summen[2][1] == 0

    def test_leere_summen_ergeben_keinen_fehler(self):
        assert ev.pooled_calibration_error({}) == (None, [])


# ---------------------------------------------------------------------------
# 9. Gepaarter Bootstrap
# ---------------------------------------------------------------------------

class TestBootstrap:

    def test_derselbe_seed_ergibt_dasselbe_intervall(self):
        import random

        basis = [random.Random(1).random() for _ in range(200)]
        ml = [wert + 0.1 for wert in basis]

        erste = ev.paired_bootstrap(basis, ml, seed=99, iterations=500)
        zweite = ev.paired_bootstrap(basis, ml, seed=99, iterations=500)
        assert erste == zweite

    def test_ein_anderer_seed_ergibt_ein_anderes_intervall(self):
        """
        Gegenprobe: Waere das Ergebnis vom Seed unabhaengig, wuerde der
        Test darueber nichts belegen.
        """
        import random

        rng = random.Random(2)
        basis = [rng.random() for _ in range(200)]
        ml = [rng.random() for _ in range(200)]

        erste = ev.paired_bootstrap(basis, ml, seed=1, iterations=500)
        zweite = ev.paired_bootstrap(basis, ml, seed=2, iterations=500)
        assert erste["ci_low"] != zweite["ci_low"]

    def test_die_ziehung_ist_gepaart(self):
        """
        Der entscheidende Test.

        ML ist hier in JEDER Partie um genau 0.5 schlechter, waehrend die
        Verluste selbst zwischen 0 und 10 streuen. Werden in einer
        Wiederholung dieselben Partien fuer beide Seiten gezogen, ist die
        Differenz zwangslaeufig exakt 0.5 - unabhaengig davon, welche
        Partien es sind. Das Intervall muss deshalb zu einem Punkt
        zusammenfallen.

        Zwei getrennte Ziehungen wuerden dagegen die volle Streuung der
        Verluste ins Intervall tragen und es weit aufziehen.
        """
        import random

        rng = random.Random(5)
        basis = [rng.uniform(0.0, 10.0) for _ in range(300)]
        ml = [wert + 0.5 for wert in basis]

        intervall = ev.paired_bootstrap(basis, ml, seed=7, iterations=1000)
        assert intervall["point"] == pytest.approx(0.5)
        assert intervall["ci_low"] == pytest.approx(0.5, abs=1e-9)
        assert intervall["ci_high"] == pytest.approx(0.5, abs=1e-9)

    def test_ungepaarte_ziehung_wuerde_auffallen(self):
        """
        Die Gegenprobe zum Test darueber: Sie zeigt, wie breit das
        Intervall bei getrennten Ziehungen tatsaechlich wuerde. Ohne
        diesen Vergleich waere nicht belegt, dass der Test oben
        ueberhaupt etwas unterscheiden kann.
        """
        import random

        import numpy as np

        rng = random.Random(5)
        basis = np.array([rng.uniform(0.0, 10.0) for _ in range(300)])
        ml = basis + 0.5

        zufall = np.random.default_rng(7)
        deltas = [ml[zufall.integers(0, 300, 300)].mean()
                  - basis[zufall.integers(0, 300, 300)].mean()
                  for _ in range(1000)]
        breite = float(np.percentile(deltas, 97.5)
                       - np.percentile(deltas, 2.5))
        assert breite > 0.5

    def test_der_seed_und_die_wiederholungen_stehen_fest(self):
        assert ev.BOOTSTRAP_SEED == 20260827
        assert ev.BOOTSTRAP_ITERATIONS >= 2000

    def test_unterschiedlich_lange_listen_brechen_ab(self):
        with pytest.raises(ValueError, match="verschieden viele"):
            ev.paired_bootstrap([1.0, 2.0], [1.0])

    @pytest.mark.parametrize("tief,hoch,erwartet", [
        (-0.02, -0.01, "Verbesserung"),
        (0.01, 0.02, "Verschlechterung"),
        (-0.01, 0.01, "enthaelt null"),
    ])
    def test_die_deutung_folgt_der_lage_des_intervalls(self, tief, hoch,
                                                       erwartet):
        assert erwartet in ev.interpret(
            {"ci_low": tief, "ci_high": hoch, "point": 0.0})


# ---------------------------------------------------------------------------
# 10. Gesamtlauf
# ---------------------------------------------------------------------------

class TestGesamtlauf:

    def test_der_lauf_liefert_beide_folds_und_eine_aggregation(self):
        ergebnis = ev.run_evaluation(drei_saisons(), alphas=(1.0,))

        assert [f["fold"] for f in ergebnis["folds"]] == ["fold_1", "fold_2"]
        assert ergebnis["aggregate"]["n"] > 0
        assert ergebnis["feature_columns"] == SPALTEN

        for fold in ergebnis["folds"]:
            assert "_internal" not in fold, \
                "die internen Verlustlisten gehoeren nicht ins Artefakt"
            assert fold["per_league"]
            assert set(fold["clamps"]) >= {"clamp_rate_home", "clamp_rate_away"}

    def test_die_aggregation_traegt_alle_drei_intervalle(self):
        ergebnis = ev.run_evaluation(drei_saisons(), alphas=(1.0,))
        bootstrap = ergebnis["aggregate"]["bootstrap"]
        assert set(bootstrap) == {"log_loss", "brier", "rps"}
        for intervall in bootstrap.values():
            assert intervall["ci_low"] <= intervall["ci_high"]
            assert intervall["interpretation"]

    def test_je_liga_wird_getrennt_ausgewiesen(self):
        """
        Eine Verbesserung im Mittel kann eine einzelne Liga deutlich
        verschlechtern. Ohne diese Aufschluesselung bliebe das
        unsichtbar.
        """
        ergebnis = ev.run_evaluation(drei_saisons(), alphas=(1.0,))
        ligen = {e["league"] for e in ergebnis["folds"][0]["per_league"]}
        assert ligen == {"bl1", "pl"}
        for eintrag in ergebnis["folds"][0]["per_league"]:
            assert eintrag["delta_log_loss"] == pytest.approx(
                eintrag["ml_log_loss"] - eintrag["baseline_log_loss"])

    def test_zu_wenig_daten_ergibt_einen_fehlereintrag_statt_einer_zahl(self):
        ergebnis = ev.evaluate_fold(saison(2023, anzahl=5), ev.OUTER_FOLDS[0],
                                    SPALTEN)
        assert ergebnis["error"] == "zu wenig Daten"
