"""
Walk-forward-Auswertung des Korrekturmodells - ausschliesslich im Schatten.

WAS HIER GEMESSEN WIRD
----------------------
Ob eine gelernte Korrektur die bestehende Baseline schlaegt. Nichts
davon beeinflusst eine Nutzerprognose: Das Ergebnis ist eine Zahl in
einer JSON-Datei, kein aktiviertes Modell.

DIE ZEITLICHE ORDNUNG
---------------------
    Fold 1   Training 2023            Test 2024
    Fold 2   Training 2023 + 2024     Test 2025

Keine spaetere Saison im Training einer frueheren. Kein zufaelliger
Split. Der aeussere Test wird je Fold genau einmal angefasst - nachdem
die Modellwahl abgeschlossen ist.

DIE MODELLWAHL PASSIERT INNEN
-----------------------------
Bei zwei aeusseren Folds waere jede Alpha-Wahl am Testergebnis eine
verdeckte Optimierung auf die Zukunft. Deshalb:

    Fold 1   innerer Fit: fruehe 2023er Partien
             innere Validierung: spaete 2023er Partien
    Fold 2   innerer Fit: 2023
             innere Validierung: 2024

Die Grenze in Fold 1 wird deterministisch aus den Daten abgeleitet - das
mittlere Spieldatum - und im Ergebnis dokumentiert.

DIE BASELINE IST EIN KANDIDAT, KEIN GEGNER
------------------------------------------
no_correction tritt gleichberechtigt an. Verbessert kein Alpha die
innere Validierung, gewinnt sie. Ohne diesen Kandidaten waere die Wahl
gezwungen, irgendein Modell zu nehmen - auch ein schlechteres. Ein
Auswertungsweg, der nur gewinnen kann, misst nichts.

VORZEICHENKONVENTION
--------------------
    delta = ML - Baseline

Negativ heisst besser, positiv schlechter. Diese Richtung gilt
durchgehend in Code, Ergebnis und Bericht.
"""

from collections import defaultdict

from src.ml import model as mdl

#: Fassung des Ergebnisformats.
SCHEMA_VERSION = 1

#: Die aeusseren Folds, vorab festgelegt.
OUTER_FOLDS = (
    {"name": "fold_1", "train_seasons": [2023], "test_seasons": [2024]},
    {"name": "fold_2", "train_seasons": [2023, 2024], "test_seasons": [2025]},
)

#: Gepaarter Bootstrap - fester Seed, damit zwei Laeufe dieselbe Zahl
#: ergeben.
BOOTSTRAP_SEED = 20260827
BOOTSTRAP_ITERATIONS = 2000


# ---------------------------------------------------------------------------
# Metriken - ueber die bestehenden Funktionen, nicht neu geschrieben
# ---------------------------------------------------------------------------

def probabilities_for(lambdas):
    """
    H/D/A ueber den bestehenden FootSim-Poisson-Pfad.

    Dieselbe Funktion fuer Baseline und ML. Eine zweite Implementierung
    waere die sicherste Art, einen Vergleich unbrauchbar zu machen.
    """
    from src.features.go3_backtest import outcome_probabilities

    return [outcome_probabilities(lh, la) for lh, la in lambdas]


def calibration_sums(wahrscheinlichkeiten, ausgaenge):
    """
    Rohe Bin-Summen fuer die Kalibrierung.

    Dieselbe Einteilung wie _Accumulator im Backtest: zehn Eimer ueber
    die vorhergesagte Wahrscheinlichkeit, drei Klassenbeobachtungen je
    Partie.

    Zurueckgegeben werden SUMMEN, keine Quotienten. Nur so lassen sich
    mehrere Folds zusammenfuehren, ohne den Absolutbetrag zu frueh zu
    bilden - siehe pooled_calibration_error().
    """
    eimer = defaultdict(lambda: [0.0, 0, 0])
    for p, ziel in zip(wahrscheinlichkeiten, ausgaenge):
        for i in range(3):
            index = min(9, int(p[i] * 10))
            eimer[index][0] += p[i]
            eimer[index][1] += 1 if i == ziel else 0
            eimer[index][2] += 1
    return {index: list(werte) for index, werte in eimer.items()}


def merge_calibration_sums(summen_liste):
    """Bin-Summen mehrerer Folds addieren."""
    gesamt = defaultdict(lambda: [0.0, 0, 0])
    for summen in summen_liste:
        for index, (vorhergesagt, treffer, anzahl) in summen.items():
            gesamt[index][0] += vorhergesagt
            gesamt[index][1] += treffer
            gesamt[index][2] += anzahl
    return {index: list(werte) for index, werte in gesamt.items()}


def pooled_calibration_error(summen):
    """
    Der gepoolte Kalibrierungsfehler.

    Der Betrag wird gebildet, NACHDEM die Beobachtungen je Bin
    zusammengefuehrt sind. Wuerde man die Fold-Fehler mitteln, koennten
    sich entgegengesetzte Abweichungen nicht aufheben, und der globale
    Fehler waere systematisch zu hoch - derselbe Fehler, der im
    Backtestlaeufer bereits einmal korrigiert werden musste.

    Rueckgabe: (fehler, bins).
    """
    if not summen:
        return None, []

    bins, abweichung, gesamt = [], 0.0, 0
    for index in sorted(summen):
        vorhergesagt_summe, treffer, anzahl = summen[index]
        if not anzahl:
            continue
        vorhergesagt = vorhergesagt_summe / anzahl
        beobachtet = treffer / anzahl
        bins.append({
            "bin": f"{index / 10:.1f}-{(index + 1) / 10:.1f}",
            "predicted": vorhergesagt,
            "observed": beobachtet,
            "n": anzahl,
        })
        abweichung += abs(vorhergesagt - beobachtet) * anzahl
        gesamt += anzahl

    return (abweichung / gesamt if gesamt else None), bins


def per_match_losses(wahrscheinlichkeiten, ausgaenge):
    """
    Verlust je Partie - die Grundlage fuer Aggregation und Bootstrap.

    Bewusst je Partie und nicht als fertiger Mittelwert: Der gepaarte
    Bootstrap zieht Partien, nicht Mittelwerte.
    """
    from src.features.go3_backtest import _brier, _log_loss, _rps

    return {
        "log_loss": [_log_loss(p, z) for p, z in
                     zip(wahrscheinlichkeiten, ausgaenge)],
        "brier": [_brier(p, z) for p, z in
                  zip(wahrscheinlichkeiten, ausgaenge)],
        "rps": [_rps(p, z) for p, z in zip(wahrscheinlichkeiten, ausgaenge)],
    }


def summarise(wahrscheinlichkeiten, ausgaenge):
    """Die Kennzahlen eines Bestands."""
    if not wahrscheinlichkeiten:
        return None

    verluste = per_match_losses(wahrscheinlichkeiten, ausgaenge)
    anzahl = len(wahrscheinlichkeiten)
    treffer = sum(1 for p, z in zip(wahrscheinlichkeiten, ausgaenge)
                  if max(range(3), key=lambda i: p[i]) == z)
    fehler, bins = pooled_calibration_error(
        calibration_sums(wahrscheinlichkeiten, ausgaenge))

    return {
        "n": anzahl,
        "log_loss": sum(verluste["log_loss"]) / anzahl,
        "brier": sum(verluste["brier"]) / anzahl,
        "rps": sum(verluste["rps"]) / anzahl,
        "calibration_error": fehler,
        "calibration_bins": bins,
        "accuracy_supplementary": treffer / anzahl,
    }


def probability_change(basis, ml):
    """Wie stark verschiebt die Korrektur die Wahrscheinlichkeiten?"""
    if not basis:
        return {"avg_probability_change": 0.0, "max_probability_change": 0.0}

    aenderungen = [max(abs(a[i] - b[i]) for i in range(3))
                   for a, b in zip(basis, ml)]
    return {
        "avg_probability_change": sum(aenderungen) / len(aenderungen),
        "max_probability_change": max(aenderungen),
    }


# ---------------------------------------------------------------------------
# Folds
# ---------------------------------------------------------------------------

def eligible_rows(zeilen, seasons):
    """
    Auswertbare Zeilen der genannten Saisons, zeitlich sortiert.

    Nur evaluation_eligible: Die Aufwaermphase misst die Anlaufzeit der
    Profile, nicht die Guete der Vorhersage.
    """
    passend = [z for z in zeilen
               if z["season"] in seasons and z["evaluation_eligible"]]
    return sorted(passend, key=lambda z: (z["date"], z["row_id"]))


def inner_split(zeilen, fold):
    """
    Die innere Aufteilung fuer die Modellwahl.

    Fold 1 hat nur eine Trainingssaison. Sie wird am mittleren Spieldatum
    geteilt - deterministisch aus den Daten abgeleitet, nicht geraten und
    nicht zufaellig.

    Fold 2 teilt nach Saison: 2023 anpassen, 2024 validieren. Das ist
    dieselbe zeitliche Richtung wie aussen.

    Rueckgabe: (fit_zeilen, val_zeilen, beschreibung).
    """
    training = eligible_rows(zeilen, fold["train_seasons"])
    if not training:
        return [], [], {"strategy": "leer"}

    if len(fold["train_seasons"]) == 1:
        daten = sorted({z["date"] for z in training})
        grenze = daten[len(daten) // 2]
        anpassen = [z for z in training if z["date"] < grenze]
        validieren = [z for z in training if z["date"] >= grenze]
        beschreibung = {
            "strategy": "zeitliche Teilung innerhalb einer Saison",
            "boundary_date": grenze,
            "boundary_rule": "mittleres Spieldatum der Trainingssaison",
            "fit_rows": len(anpassen),
            "validation_rows": len(validieren),
        }
    else:
        fit_saisons = fold["train_seasons"][:-1]
        val_saisons = fold["train_seasons"][-1:]
        anpassen = eligible_rows(zeilen, fit_saisons)
        validieren = eligible_rows(zeilen, val_saisons)
        beschreibung = {
            "strategy": "Teilung nach Saison",
            "fit_seasons": fit_saisons,
            "validation_seasons": val_saisons,
            "fit_rows": len(anpassen),
            "validation_rows": len(validieren),
        }

    return anpassen, validieren, beschreibung


def predict_lambdas(kandidat, modelle, zeilen, spalten):
    """
    Lambdas eines Kandidaten - mit Clamps.

    Rueckgabe: (lambdas, clamp_statistik).
    """
    if kandidat == mdl.NO_CORRECTION:
        # Keine Korrektur heisst keine Korrektur: dieselben Lambdas,
        # keine Begrenzung, kein Rundungsschritt dazwischen.
        return mdl.baseline_lambdas(zeilen), {
            "correction_min": mdl.CORRECTION_MIN,
            "correction_max": mdl.CORRECTION_MAX,
            "lambda_min_allowed": mdl.LAMBDA_MIN,
            "lambda_max_allowed": mdl.LAMBDA_MAX,
            "clamped_home": 0, "clamped_away": 0,
            "clamp_rate_home": 0.0, "clamp_rate_away": 0.0,
            "raw_factor_home": None, "raw_factor_away": None,
            "final_lambda_home": None, "final_lambda_away": None,
        }

    faktoren_home = mdl.predict_factors(modelle["home"], zeilen, spalten)
    faktoren_away = mdl.predict_factors(modelle["away"], zeilen, spalten)
    return mdl.apply_correction(zeilen, faktoren_home, faktoren_away)


def select_candidate(fit_zeilen, val_zeilen, spalten,
                     alphas=mdl.ALPHA_CANDIDATES):
    """
    Waehlt den Kandidaten anhand des INNEREN H/D/A-LogLoss.

    Nicht anhand der Poisson-Devianz: Gemessen wird spaeter der
    Ergebnisausgang, also muss auch hier der Ergebnisausgang entscheiden.

    Zwei Gleichstandsregeln, beide in dieselbe Richtung:

    Unter den Alphas gewinnt bei gleichem Verlust das GROESSERE, also
    die staerkere Regularisierung. Bei zwei gleich guten Modellen ist
    das zurueckhaltendere das bessere, weil es weniger aus dem Rauschen
    lernt.

    Gegenueber der Baseline zaehlt nur STRIKTE Verbesserung.
    no_correction ist der zurueckhaltendste Kandidat ueberhaupt und
    gewinnt deshalb jeden Gleichstand gegen jedes Alpha.

    Rueckgabe: (kandidat, modelle, protokoll).
    """
    ausgaenge = [z["outcome"] for z in val_zeilen]

    protokoll = []
    basis_lambdas = mdl.baseline_lambdas(val_zeilen)
    basis_verlust = summarise(probabilities_for(basis_lambdas),
                              ausgaenge)["log_loss"]
    protokoll.append({"candidate": mdl.NO_CORRECTION,
                      "inner_log_loss": basis_verlust})

    # Erst alle Alphas messen, dann waehlen. Die Trennung ist noetig:
    # Die Gleichstandsregel muss den gesamten Kandidatensatz kennen und
    # kann nicht schrittweise entschieden werden.
    gemessen = []
    for alpha in alphas:
        try:
            heim, _ = mdl.fit_side(fit_zeilen, "home", alpha, spalten)
            gast, _ = mdl.fit_side(fit_zeilen, "away", alpha, spalten)
            modelle = {"home": heim, "away": gast}
            lambdas, _ = predict_lambdas(alpha, modelle, val_zeilen, spalten)
            verlust = summarise(probabilities_for(lambdas),
                                ausgaenge)["log_loss"]
        except Exception as fehler:                      # pragma: no cover
            protokoll.append({"candidate": alpha, "error": str(fehler)})
            continue

        protokoll.append({"candidate": alpha, "inner_log_loss": verlust})
        gemessen.append((verlust, alpha, modelle))

    bester = mdl.NO_CORRECTION
    bester_verlust = basis_verlust
    beste_modelle = None

    if gemessen:
        # -alpha im Sortierschluessel: Bei gleichem Verlust steht das
        # GROESSERE Alpha vorn. Ein aufsteigender Durchlauf mit
        # "nur bei strikt besser ersetzen" wuerde genau das Gegenteil
        # tun und die schwaechste Regularisierung behalten.
        bestes = min(gemessen, key=lambda eintrag: (eintrag[0], -eintrag[1]))
        # Gegen die Baseline zaehlt nur strikte Verbesserung. Ein
        # Gleichstand ist keine Verbesserung.
        if bestes[0] < basis_verlust:
            bester_verlust, bester, beste_modelle = bestes

    return bester, beste_modelle, {
        "candidates": protokoll,
        "selected": bester,
        "selected_inner_log_loss": bester_verlust,
        "baseline_inner_log_loss": basis_verlust,
        "tie_break": "unter gleichauf liegenden Alphas gewinnt das groessere "
                     "(staerkere Regularisierung); gegenueber der Baseline "
                     "zaehlt nur strikte Verbesserung, ein Gleichstand geht "
                     "an no_correction",
    }


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def paired_bootstrap(basis_verluste, ml_verluste, seed=BOOTSTRAP_SEED,
                     iterations=BOOTSTRAP_ITERATIONS):
    """
    Gepaarter Bootstrap auf Spielebene.

    Entscheidend ist das Wort GEPAART: In jeder Wiederholung werden
    dieselben Spielindizes fuer Baseline UND ML verwendet. Zwei
    unabhaengige Stichproben wuerden die Differenz kuenstlich verrauschen
    und das Intervall unbrauchbar weit machen.

    Der Bootstrap dient ausschliesslich der Einordnung des Ergebnisses -
    niemals der Modell- oder Alphawahl. Er laeuft, nachdem alles
    entschieden ist.

    Rueckgabe: {"point", "ci_low", "ci_high", "iterations", "seed"}.
    """
    import numpy as np

    if len(basis_verluste) != len(ml_verluste):
        raise ValueError("Baseline und ML haben verschieden viele Spiele")
    anzahl = len(basis_verluste)
    if not anzahl:
        return None

    basis = np.asarray(basis_verluste, dtype=float)
    ml = np.asarray(ml_verluste, dtype=float)
    punkt = float(ml.mean() - basis.mean())

    rng = np.random.default_rng(seed)
    deltas = np.empty(iterations, dtype=float)
    for i in range(iterations):
        # EIN Indexsatz fuer beide Seiten - das ist die Paarung.
        index = rng.integers(0, anzahl, size=anzahl)
        deltas[i] = ml[index].mean() - basis[index].mean()

    return {
        "point": punkt,
        "ci_low": float(np.percentile(deltas, 2.5)),
        "ci_high": float(np.percentile(deltas, 97.5)),
        "iterations": iterations,
        "seed": seed,
    }


def interpret(intervall):
    """Was das Intervall aussagt - ohne Signifikanzbehauptung nach Gefuehl."""
    if not intervall:
        return "kein Intervall"
    if intervall["ci_high"] < 0:
        return "Intervall vollstaendig unter null - belastbarer Hinweis auf Verbesserung"
    if intervall["ci_low"] > 0:
        return "Intervall vollstaendig ueber null - belastbarer Hinweis auf Verschlechterung"
    return "Intervall enthaelt null - keine belastbar nachgewiesene Aenderung"


# ---------------------------------------------------------------------------
# Auswertung
# ---------------------------------------------------------------------------

def evaluate_fold(zeilen, fold, spalten, alphas=mdl.ALPHA_CANDIDATES):
    """Ein aeusserer Fold: innen waehlen, aussen genau einmal messen."""
    fit_zeilen, val_zeilen, innen = inner_split(zeilen, fold)
    test_zeilen = eligible_rows(zeilen, fold["test_seasons"])

    if not fit_zeilen or not val_zeilen or not test_zeilen:
        return {"fold": fold["name"], "error": "zu wenig Daten"}

    kandidat, modelle, wahl = select_candidate(
        fit_zeilen, val_zeilen, spalten, alphas)

    # Fuer den aeusseren Test wird auf dem VOLLEN aeusseren Training neu
    # angepasst - die innere Teilung diente nur der Wahl.
    training = eligible_rows(zeilen, fold["train_seasons"])
    diagnose = {}
    if kandidat != mdl.NO_CORRECTION:
        heim, d_heim = mdl.fit_side(training, "home", kandidat, spalten)
        gast, d_gast = mdl.fit_side(training, "away", kandidat, spalten)
        modelle = {"home": heim, "away": gast}
        diagnose = {"home": d_heim, "away": d_gast}

    ausgaenge = [z["outcome"] for z in test_zeilen]
    basis_lambdas = mdl.baseline_lambdas(test_zeilen)
    basis_p = probabilities_for(basis_lambdas)

    ml_lambdas, clamps = predict_lambdas(kandidat, modelle, test_zeilen, spalten)
    ml_p = probabilities_for(ml_lambdas)

    basis = summarise(basis_p, ausgaenge)
    ml = summarise(ml_p, ausgaenge)

    ergebnis = {
        "fold": fold["name"],
        "train_seasons": fold["train_seasons"],
        "test_seasons": fold["test_seasons"],
        "train_rows": len(training),
        "test_rows": len(test_zeilen),
        "inner_split": innen,
        "selection": wahl,
        "selected_candidate": kandidat,
        "baseline": basis,
        "ml": ml,
        "delta_log_loss": ml["log_loss"] - basis["log_loss"],
        "delta_brier": ml["brier"] - basis["brier"],
        "delta_rps": ml["rps"] - basis["rps"],
        "clamps": clamps,
        "fit_diagnostics": diagnose,
        "per_league": _per_league(test_zeilen, basis_p, ml_p, ausgaenge),
    }
    ergebnis.update(probability_change(basis_p, ml_p))

    if kandidat != mdl.NO_CORRECTION:
        ergebnis["coefficients"] = {
            "home": mdl.coefficients(modelle["home"], spalten),
            "away": mdl.coefficients(modelle["away"], spalten),
        }

    ergebnis["_internal"] = {
        "baseline_losses": per_match_losses(basis_p, ausgaenge),
        "ml_losses": per_match_losses(ml_p, ausgaenge),
        "baseline_calibration": calibration_sums(basis_p, ausgaenge),
        "ml_calibration": calibration_sums(ml_p, ausgaenge),
        # Liga und Saison je Spiel, damit die Aggregation ueber beide
        # Folds hinweg aufschluesseln kann. Ohne diese Zuordnung liesse
        # sich nur je Fold berichten - und ein Fold ist keine Liga.
        "leagues": [z["league"] for z in test_zeilen],
        "seasons": [z["season"] for z in test_zeilen],
    }
    return ergebnis


def _per_league(test_zeilen, basis_p, ml_p, ausgaenge):
    """Kennzahlen je Liga - eine Verbesserung im Mittel kann eine Liga
    deutlich verschlechtern, und das muss sichtbar sein."""
    nach_liga = defaultdict(lambda: {"basis": [], "ml": [], "ziel": []})
    for zeile, bp, mp, ziel in zip(test_zeilen, basis_p, ml_p, ausgaenge):
        eintrag = nach_liga[zeile["league"]]
        eintrag["basis"].append(bp)
        eintrag["ml"].append(mp)
        eintrag["ziel"].append(ziel)

    ergebnis = []
    for liga in sorted(nach_liga):
        eintrag = nach_liga[liga]
        basis = summarise(eintrag["basis"], eintrag["ziel"])
        ml = summarise(eintrag["ml"], eintrag["ziel"])
        ergebnis.append({
            "league": liga,
            "n": basis["n"],
            "baseline_log_loss": basis["log_loss"],
            "ml_log_loss": ml["log_loss"],
            "delta_log_loss": ml["log_loss"] - basis["log_loss"],
            "delta_brier": ml["brier"] - basis["brier"],
            "delta_rps": ml["rps"] - basis["rps"],
        })
    return ergebnis


def _breakdown(schluessel_liste, basis_verluste, ml_verluste, feldname):
    """
    Aufschluesselung nach einem Merkmal je Spiel - Liga oder Saison.

    Ueber BEIDE Folds hinweg. Eine Aufschluesselung je Fold allein
    wuerde verbergen, ob eine Liga durchgaengig verliert oder nur in
    einem Fold.
    """
    gruppen = defaultdict(lambda: {"basis": [], "ml": []})
    for schluessel, basis, ml in zip(schluessel_liste,
                                     basis_verluste["log_loss"],
                                     ml_verluste["log_loss"]):
        gruppen[schluessel]["basis"].append(basis)
        gruppen[schluessel]["ml"].append(ml)

    ergebnis = []
    for schluessel in sorted(gruppen):
        eintrag = gruppen[schluessel]
        basis = sum(eintrag["basis"]) / len(eintrag["basis"])
        ml = sum(eintrag["ml"]) / len(eintrag["ml"])
        ergebnis.append({
            feldname: schluessel,
            "n": len(eintrag["basis"]),
            "baseline_log_loss": basis,
            "ml_log_loss": ml,
            "delta_log_loss": ml - basis,
        })
    return ergebnis


def aggregate(folds):
    """
    Beide Folds zusammenfuehren - gewichtet nach SPIELEN.

    Ein ungewichteter Mittelwert der beiden Folds waere falsch: Sie haben
    verschieden viele Testspiele. Fuer die Kalibrierung werden die Bins
    zusammengefuehrt, bevor der Betrag gebildet wird.
    """
    brauchbar = [f for f in folds if "error" not in f]
    if not brauchbar:
        return None

    basis_verluste = {"log_loss": [], "brier": [], "rps": []}
    ml_verluste = {"log_loss": [], "brier": [], "rps": []}
    for fold in brauchbar:
        for schluessel in basis_verluste:
            basis_verluste[schluessel].extend(
                fold["_internal"]["baseline_losses"][schluessel])
            ml_verluste[schluessel].extend(
                fold["_internal"]["ml_losses"][schluessel])

    ligen, saisons = [], []
    for fold in brauchbar:
        ligen.extend(fold["_internal"]["leagues"])
        saisons.extend(fold["_internal"]["seasons"])

    anzahl = len(basis_verluste["log_loss"])
    basis_kalib, basis_bins = pooled_calibration_error(merge_calibration_sums(
        [f["_internal"]["baseline_calibration"] for f in brauchbar]))
    ml_kalib, ml_bins = pooled_calibration_error(merge_calibration_sums(
        [f["_internal"]["ml_calibration"] for f in brauchbar]))

    def mittel(werte):
        return sum(werte) / len(werte) if werte else None

    zusammen = {
        "n": anzahl,
        "baseline": {
            "log_loss": mittel(basis_verluste["log_loss"]),
            "brier": mittel(basis_verluste["brier"]),
            "rps": mittel(basis_verluste["rps"]),
            "calibration_error": basis_kalib,
            "calibration_bins": basis_bins,
        },
        "ml": {
            "log_loss": mittel(ml_verluste["log_loss"]),
            "brier": mittel(ml_verluste["brier"]),
            "rps": mittel(ml_verluste["rps"]),
            "calibration_error": ml_kalib,
            "calibration_bins": ml_bins,
        },
    }
    for schluessel in ("log_loss", "brier", "rps"):
        zusammen[f"delta_{schluessel}"] = (zusammen["ml"][schluessel]
                                           - zusammen["baseline"][schluessel])

    zusammen["per_league"] = _breakdown(ligen, basis_verluste,
                                        ml_verluste, "league")
    zusammen["per_test_season"] = _breakdown(saisons, basis_verluste,
                                             ml_verluste, "season")

    zusammen["bootstrap"] = {
        schluessel: paired_bootstrap(basis_verluste[schluessel],
                                     ml_verluste[schluessel])
        for schluessel in ("log_loss", "brier", "rps")
    }
    for intervall in zusammen["bootstrap"].values():
        if intervall:
            intervall["interpretation"] = interpret(intervall)

    return zusammen


def run_evaluation(zeilen, folds=OUTER_FOLDS, alphas=mdl.ALPHA_CANDIDATES):
    """Die vollstaendige Auswertung."""
    spalten = mdl.feature_columns()
    ergebnisse = [evaluate_fold(zeilen, fold, spalten, alphas)
                  for fold in folds]
    zusammen = aggregate(ergebnisse)

    # Der interne Block traegt Verlustlisten je Spiel. Er ist die
    # Grundlage der Aggregation, blaeht das Artefakt aber unnoetig auf.
    for fold in ergebnisse:
        fold.pop("_internal", None)

    return {"folds": ergebnisse, "aggregate": zusammen,
            "feature_columns": spalten}
