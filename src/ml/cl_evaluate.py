"""
Champions-League-Shadow-Backtest.

DIE FRAGE
---------
Traegt eine auf Ligaspielen gelernte Korrektur auch in der Champions
League? Bisher war das eine Vermutung: Die Ablation hat gemessen, dass
die Verbesserung aus den Teamprofilen stammt, und die
Bereitschaftsanalyse hat gezeigt, wie weit die beiden Bereiche
auseinanderliegen. Gemessen wurde die Uebertragung nie.

Diese Datei misst sie. Sie aktiviert nichts, speichert kein Modell und
beruehrt keinen produktiven Pfad.

DER AUFBAU - UND WARUM ER SO UND NICHT ANDERS IST
-------------------------------------------------
Trainiert wird ausschliesslich auf nationalen Ligazeilen, getestet
ausschliesslich auf CL-Zeilen:

    Fold cl_2024    Training Liga 2023            Test CL 2024
    Fold cl_2025    Training Liga 2023 + 2024     Test CL 2025

Das ist die Frage in Reinform: Ein Modell, das nur Ligen kennt, trifft
auf einen Wettbewerb, den es nie gesehen hat.

CL 2023 IST KEIN FOLD
---------------------
Fuer die CL-Saison 2023 gaebe es keine zeitlich frueher liegende
Ligasaison - die lokale Historie beginnt mit 2023, und CL 2023 laeuft
ab September 2023, also parallel. Ein Fold daraus waere entweder
leckagebehaftet oder erfunden. Die Saison wird deshalb ausgewiesen und
nicht ausgewertet.

DER TESTBESTAND WIRD EINMAL ANGEFASST
-------------------------------------
Die Alphawahl laeuft ueber eine innere zeitliche Teilung der
LIGA-Trainingsdaten - dieselbe Funktion wie in der bestehenden
Ligaauswertung. Kein CL-Spiel geht in Training, Alphawahl,
Merkmalswahl oder Clamp-Wahl ein. Der Merkmalssatz stand vor diesem
Lauf fest (feature_groups.CL_PRIMARY_CANDIDATE) und wurde nicht nach
Betrachtung eines CL-Ergebnisses geaendert.

KEINE ZWEITE STATISTIK
----------------------
Kennzahlen, Kalibrierung und Bootstrap kommen aus evaluate.py, die
Modellrechnung aus model.py. Diese Datei fuegt Foldbildung, Trennung
nach Herkunft und die Urteilslogik hinzu - mehr nicht.
"""

import hashlib
import json

from src.ml import evaluate as ev
from src.ml import feature_groups as fg
from src.ml import model as mdl

#: Fassung des Ergebnisformats.
#:
#: 2  C0B: Der Fingerabdruck erfasst seither auch die Zielwerte
#:    home_goals und away_goals. Ergebnisse der Fassung 1 sind damit
#:    NICHT vergleichbar - ihr Fingerabdruck belegt weniger, als er
#:    behauptet (siehe FINGERPRINT_SCHEMA_VERSION).
SCHEMA_VERSION = 2

#: Der vorab festgelegte Kandidat. Die Wahl fiel in C2 anhand von
#: LIGADATEN und der Merkmalsverteilung - nicht anhand eines
#: CL-Ergebnisses, das es zu diesem Zeitpunkt noch nicht gab.
CANDIDATE = fg.CL_PRIMARY_CANDIDATE

#: Die aeusseren Folds. Training immer ausschliesslich Liga, Test
#: immer ausschliesslich CL.
OUTER_FOLDS = (
    {"name": "cl_2024", "train_seasons": [2023], "test_season": 2024},
    {"name": "cl_2025", "train_seasons": [2023, 2024], "test_season": 2025},
)

#: CL-Saisons ohne frueher liegende Ligasaison. Sie werden gezaehlt und
#: berichtet, aber nicht ausgewertet.
SEASONS_WITHOUT_TRAINING = (2023,)

#: Ab wann eine Untergruppe als belastbar gilt. Darunter wird sie
#: ausdruecklich als deskriptiv gekennzeichnet. Kein Test, sondern eine
#: Lesehilfe - bei zwoelf Spielen sagt ein Mittelwert wenig.
MIN_RELIABLE_N = 30

#: Ab welchem Verlust ein Fold als schwerer Qualitaetsabfall gilt.
#:
#: VORAB festgelegt und aus der bestehenden Auswertungskonvention
#: abgeleitet, nicht aus dem CL-Ergebnis: Die gesamte auf Ligadaten je
#: nachgewiesene Verbesserung betraegt -0,00944 (voller Merkmalssatz)
#: bzw. -0,01446 (profile_only). Ein Fold, der um mehr als 0,01
#: SCHLECHTER wird, verliert damit mehr, als das Verfahren insgesamt je
#: gewonnen hat. Das ist die Grenze - und sie steht hier, damit sie
#: nicht nachtraeglich passend gemacht werden kann.
SEVERE_DEGRADATION = 0.01

#: Klassen der Profiltiefe (duennste Seite). Feste Grenzen, damit zwei
#: Laeufe dieselben Gruppen bilden. Die Untergrenze ist die
#: Eligibility-Schwelle aus cl_dataset.
DEPTH_BINS = ((6, 10), (10, 20), (20, 40), (40, None))


# ---------------------------------------------------------------------------
# Bestandsbildung
# ---------------------------------------------------------------------------

def league_rows(zeilen, seasons):
    """
    Auswertbare NATIONALE Ligazeilen der genannten Saisons.

    Der Filter auf league != "cl" ist der wichtigste Handgriff dieser
    Datei. evaluate.eligible_rows() filtert nur nach Saison und
    Eligibility - CL-Zeilen tragen dieselben Saisonnummern und geraeten
    ohne diesen Schritt still ins Training des Modells, das sie
    anschliessend vorhersagen soll.
    """
    national = [z for z in zeilen if z.get("league") != "cl"]
    return ev.eligible_rows(national, seasons)


def cl_rows(zeilen, season):
    """
    Auswertbare CL-Zeilen einer Saison, in fester Reihenfolge.

    evaluation_eligible traegt bereits die fachlichen Ausschluesse aus
    cl_dataset: nur regulaere Phase, kein neutrales Profil, Mindest-
    tiefe. Hier wird nichts zusaetzlich gefiltert - sonst gaebe es zwei
    Stellen, an denen ueber Auswertbarkeit entschieden wird.
    """
    passend = [z for z in zeilen
               if z.get("league") == "cl" and z.get("season") == season
               and z.get("evaluation_eligible")]
    return sorted(passend, key=lambda z: (z["date"], z["row_id"]))


def excluded_summary(zeilen):
    """Was aus dem CL-Bestand herausfaellt - und warum."""
    from collections import Counter

    alle = [z for z in zeilen if z.get("league") == "cl"]
    ausgeschlossen = [z for z in alle if not z.get("evaluation_eligible")]
    return {
        "cl_rows_loaded": len(alle),
        "cl_rows_eligible": len(alle) - len(ausgeschlossen),
        "cl_rows_excluded": len(ausgeschlossen),
        "exclusion_reasons": dict(Counter(
            z.get("exclusion_reason") for z in ausgeschlossen)),
        "seasons_without_training_fold": {
            str(s): len(cl_rows(zeilen, s)) for s in SEASONS_WITHOUT_TRAINING},
    }


#: Identitaet und Bestandszugehoerigkeit einer Zeile. league, season und
#: evaluation_eligible entscheiden, ob eine Zeile ueberhaupt in Training
#: oder Test geraet - eine Aenderung daran veraendert die Messung, auch
#: wenn kein einziger Merkmalswert wandert.
FINGERPRINT_IDENTITY = ("row_id", "match_id", "league", "season", "date",
                        "evaluation_eligible")

#: Fassung des Fingerabdruckvertrags. Sie geht in den Hash ein, damit
#: ein Wert der alten Fassung niemals zufaellig einem der neuen
#: gleicht - zwei Fassungen mit demselben sha256 waeren schlimmer als
#: gar kein Fingerabdruck.
FINGERPRINT_SCHEMA_VERSION = 2

#: Zielgroesse und Vergleichsmassstab.
#:
#: WARUM home_goals UND away_goals HIER STEHEN MUESSEN
#: Bis C0B fehlten sie. Das war ein echter Fehler, kein Schoenheits-
#: mangel: Trainiert wird auf den TOREN, nicht auf dem Ausgang -
#: model.targets_and_weights() bildet tore/lambda als Ziel. Ein Bestand
#: liess sich deshalb von 1:0 auf 4:0 aendern, das Trainingsziel
#: vervierfachte sich, und der Fingerabdruck blieb byte-identisch. Ein
#: Reproduzierbarkeitsnachweis darauf war keiner.
#:
#: outcome bleibt zusaetzlich drin: Es ist die Zielgroesse der
#: Guetemessung (LogLoss, Brier, RPS) und aus den Toren zwar ableitbar,
#: aber nicht identisch - ein Bestand mit widerspruechlichem outcome
#: soll auffallen.
FINGERPRINT_TARGETS = ("home_goals", "away_goals", "outcome",
                       "baseline_lambda_home", "baseline_lambda_away")

#: Herkunftsangaben, die die AUSWERTUNG lesen: Die ersten vier bilden
#: die Gruppen von per_profile_source und per_profile_depth, der Grund
#: geht in die Ausschlussuebersicht. Herkunftsfelder, die hier nichts
#: beeinflussen (competition, stage), stehen bewusst nicht drin.
FINGERPRINT_PROVENANCE = ("home_profile_source", "away_profile_source",
                          "home_profile_matches", "away_profile_matches",
                          "exclusion_reason")


def fingerprint_columns(candidate=CANDIDATE):
    """
    Genau die Spalten, die dieser Backtest liest - in fester Reihenfolge.

    Die Merkmalsspalten kommen aus fg.columns_for(): dieselbe sortierte,
    ueber Laeufe stabile Liste, die auch das Modell bekommt. Damit ist
    die Reihenfolge nicht nur deterministisch, sondern dieselbe, in der
    die Werte spaeter in die Matrix gehen.
    """
    return (list(FINGERPRINT_IDENTITY) + list(FINGERPRINT_TARGETS)
            + list(fg.columns_for(candidate)) + list(FINGERPRINT_PROVENANCE))


def dataset_fingerprint(zeilen, candidate=CANDIDATE):
    """
    Ein Fingerabdruck ueber alles, was die Auswertung tatsaechlich liest.

    DIE REGEL
    Erfasst wird genau der Satz von Feldern, den dieser Backtest
    konsumiert - Identitaet, Eligibility, Zielgroesse, Baseline und
    saemtliche Merkmalswerte des Kandidaten, dazu die Herkunftsfelder,
    aus denen die Aufschluesselungen entstehen.

    Damit gilt in beide Richtungen etwas Nuetzliches: Gleicher
    Fingerabdruck heisst, dass ein erneuter Lauf dieselben Eingaben
    sieht - und jede Aenderung, die das Ergebnis verschieben KANN,
    aendert ihn.

    Der ersten Fassung fehlten die Merkmalswerte, der zweiten die TORE
    (siehe FINGERPRINT_TARGETS). Beide Luecken sind geschlossen.

    Die Sortierung nach row_id macht den Wert unabhaengig von der
    Einlesereihenfolge - row_id ist eindeutig, also ist die Ordnung
    vollstaendig bestimmt.

    Die Fassungsnummer und die Spaltenliste gehen MIT in den Hash. Ohne
    sie koennte ein Wert der Fassung 1 zufaellig einem der Fassung 2
    gleichen, und zwei unvergleichbare Bestaende traegen denselben
    Nachweis.
    """
    spalten = fingerprint_columns(candidate)
    kern = [[zeile.get(spalte) for spalte in spalten]
            for zeile in sorted(zeilen, key=lambda r: r["row_id"])]

    roh = json.dumps(
        {"fingerprint_schema_version": FINGERPRINT_SCHEMA_VERSION,
         "candidate": candidate,
         "columns": spalten,
         "rows": kern},
        sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")
    return {
        "fingerprint_schema_version": FINGERPRINT_SCHEMA_VERSION,
        "rows": len(kern),
        "sha256": hashlib.sha256(roh).hexdigest(),
        "candidate": candidate,
        "columns": spalten,
        "column_count": len(spalten),
        "covers": "alle Felder, die dieser Backtest liest: Identitaet, "
                  "evaluation_eligible, die Zielwerte home_goals und "
                  "away_goals, der daraus gebildete Ausgang, die "
                  "Baseline-Lambdas, die Merkmalswerte des Kandidaten "
                  "und die auswertungsrelevanten Herkunftsfelder",
        "row_order": "nach row_id sortiert - unabhaengig von der "
                     "Einlesereihenfolge",
    }


# ---------------------------------------------------------------------------
# Paarungspruefung
# ---------------------------------------------------------------------------

def assert_paired(test_zeilen, basis_p, ml_p):
    """
    ML und Baseline muessen dieselben Spiele in derselben Reihenfolge
    bewerten.

    Ohne diese Pruefung waere eine verrutschte Liste ein stiller Fehler:
    Der Bootstrap paart dann Spiel i der einen mit Spiel i der anderen
    Seite, und das Ergebnis saehe vollkommen plausibel aus.
    """
    if not (len(test_zeilen) == len(basis_p) == len(ml_p)):
        raise ValueError(
            f"Stichprobengroessen weichen ab: {len(test_zeilen)} Zeilen, "
            f"{len(basis_p)} Baseline-, {len(ml_p)} ML-Wahrscheinlichkeiten")

    erwartet = sorted(test_zeilen, key=lambda z: (z["date"], z["row_id"]))
    if [z["row_id"] for z in test_zeilen] != [z["row_id"] for z in erwartet]:
        raise ValueError("die Testreihenfolge ist nicht die kanonische")

    ids = [z.get("match_id") for z in test_zeilen]
    if len(set(ids)) != len(ids):
        raise ValueError("doppelte match_id im Testbestand")
    return True


# ---------------------------------------------------------------------------
# Ein Fold
# ---------------------------------------------------------------------------

def evaluate_fold(zeilen, fold, spalten, alphas=mdl.ALPHA_CANDIDATES):
    """
    Ein aeusserer Fold: innen auf Liga waehlen, aussen einmal auf CL messen.

    Rueckgabe: Ergebnisblock. _internal traegt die Verluste je Spiel und
    wird vom Aufrufer entfernt.
    """
    training = league_rows(zeilen, fold["train_seasons"])
    test_zeilen = cl_rows(zeilen, fold["test_season"])

    if not training or not test_zeilen:
        return {"fold": fold["name"], "error": "zu wenig Daten",
                "train_rows": len(training), "test_rows": len(test_zeilen)}

    # Die innere Teilung laeuft AUSSCHLIESSLICH auf den Ligadaten -
    # dieselbe Funktion und dieselbe Aufteilungsregel wie in der
    # bestehenden Ligaauswertung.
    fit_zeilen, val_zeilen, innen = ev.inner_split(
        training, {"train_seasons": fold["train_seasons"]})

    kandidat, modelle, wahl = ev.select_candidate(
        fit_zeilen, val_zeilen, spalten, alphas)

    diagnose = {}
    if kandidat != mdl.NO_CORRECTION:
        heim, d_heim = mdl.fit_side(training, "home", kandidat, spalten)
        gast, d_gast = mdl.fit_side(training, "away", kandidat, spalten)
        modelle = {"home": heim, "away": gast}
        diagnose = {"home": d_heim, "away": d_gast}

    ausgaenge = [z["outcome"] for z in test_zeilen]
    basis_p = ev.probabilities_for(mdl.baseline_lambdas(test_zeilen))
    ml_lambdas, clamps = ev.predict_lambdas(kandidat, modelle, test_zeilen,
                                            spalten)
    ml_p = ev.probabilities_for(ml_lambdas)

    assert_paired(test_zeilen, basis_p, ml_p)

    basis = ev.summarise(basis_p, ausgaenge)
    ml = ev.summarise(ml_p, ausgaenge)

    ergebnis = {
        "fold": fold["name"],
        "train_seasons": fold["train_seasons"],
        "train_competition": "national leagues only",
        "test_season": fold["test_season"],
        "test_competition": "CL",
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
        "mean_probabilities": {
            "baseline": _mittlere_wahrscheinlichkeiten(basis_p),
            "ml": _mittlere_wahrscheinlichkeiten(ml_p),
            "observed": _beobachtete_anteile(ausgaenge),
        },
    }
    ergebnis.update(ev.probability_change(basis_p, ml_p))

    if kandidat != mdl.NO_CORRECTION:
        ergebnis["coefficients"] = {
            "home": mdl.coefficients(modelle["home"], spalten),
            "away": mdl.coefficients(modelle["away"], spalten),
        }

    ergebnis["_internal"] = {
        "baseline_losses": ev.per_match_losses(basis_p, ausgaenge),
        "ml_losses": ev.per_match_losses(ml_p, ausgaenge),
        "baseline_calibration": ev.calibration_sums(basis_p, ausgaenge),
        "ml_calibration": ev.calibration_sums(ml_p, ausgaenge),
        "rows": test_zeilen,
    }
    return ergebnis


def _mittlere_wahrscheinlichkeiten(wahrscheinlichkeiten):
    if not wahrscheinlichkeiten:
        return None
    anzahl = len(wahrscheinlichkeiten)
    return {name: sum(p[i] for p in wahrscheinlichkeiten) / anzahl
            for i, name in enumerate(("home", "draw", "away"))}


def _beobachtete_anteile(ausgaenge):
    if not ausgaenge:
        return None
    anzahl = len(ausgaenge)
    return {name: sum(1 for z in ausgaenge if z == i) / anzahl
            for i, name in enumerate(("home", "draw", "away"))}


# ---------------------------------------------------------------------------
# Aufschluesselung
# ---------------------------------------------------------------------------

def profile_source_class(zeile):
    """
    Die Herkunftsklasse einer Zeile.

    Drei Klassen, weil genau sie unterschiedlich belastbar sind: Zwei
    Ligaprofile sind der Normalfall des Trainings, ein CL-Historien-
    profil ist eine andere Quelle, ein neutrales Profil ist gar keine.
    """
    from src.ml.cl_dataset import (SOURCE_CL_HISTORY, SOURCE_DOMESTIC,
                                   SOURCE_NEUTRAL)

    quellen = {zeile["home_profile_source"], zeile["away_profile_source"]}
    if SOURCE_NEUTRAL in quellen:
        return "mind. eine Seite neutral"
    if quellen == {SOURCE_DOMESTIC}:
        return "beide Seiten domestic_pit"
    if SOURCE_CL_HISTORY in quellen:
        return "mind. eine Seite cl_history_pit"
    return "sonstige"


def depth_class(zeile):
    """Klasse der duennsten Profilseite - feste Grenzen, siehe DEPTH_BINS."""
    tiefe = min(zeile["home_profile_matches"], zeile["away_profile_matches"])
    for unten, oben in DEPTH_BINS:
        if oben is None:
            if tiefe >= unten:
                return f"{unten}+"
        elif unten <= tiefe < oben:
            return f"{unten}-{oben - 1}"
    return "unbekannt"


def _gruppiere(zeilen, basis_verluste, ml_verluste, schluesselfunktion,
               feldname):
    """
    Kennzahlen je Gruppe.

    Kleine Gruppen werden ausdruecklich als deskriptiv markiert. Ein
    Mittelwert ueber zwoelf Spiele ist eine Beobachtung, keine Aussage -
    und ohne Hinweis liest ihn jeder wie eine.
    """
    from collections import defaultdict

    gruppen = defaultdict(lambda: {"basis": [], "ml": []})
    for zeile, b, m in zip(zeilen, basis_verluste, ml_verluste):
        eintrag = gruppen[schluesselfunktion(zeile)]
        eintrag["basis"].append(b)
        eintrag["ml"].append(m)

    ergebnis = []
    for schluessel in sorted(gruppen, key=str):
        eintrag = gruppen[schluessel]
        anzahl = len(eintrag["basis"])
        basis = sum(eintrag["basis"]) / anzahl
        ml = sum(eintrag["ml"]) / anzahl
        ergebnis.append({
            feldname: schluessel,
            "n": anzahl,
            "baseline_log_loss": basis,
            "ml_log_loss": ml,
            "delta_log_loss": ml - basis,
            "reliable": anzahl >= MIN_RELIABLE_N,
            "note": (None if anzahl >= MIN_RELIABLE_N
                     else "nur deskriptiv, nicht belastbar "
                          "(n < %d)" % MIN_RELIABLE_N),
        })
    return ergebnis


def aggregate(folds):
    """
    Beide Folds zusammenfuehren - nach Spielen gewichtet.

    Derselbe Weg wie in der Ligaauswertung: Verluste je Spiel sammeln,
    Kalibrierungsbins zusammenfuehren, dann erst mitteln.
    """
    brauchbar = [f for f in folds if "error" not in f]
    if not brauchbar:
        return None

    basis_verluste = {"log_loss": [], "brier": [], "rps": []}
    ml_verluste = {"log_loss": [], "brier": [], "rps": []}
    zeilen = []
    for fold in brauchbar:
        intern = fold["_internal"]
        for schluessel in basis_verluste:
            basis_verluste[schluessel].extend(
                intern["baseline_losses"][schluessel])
            ml_verluste[schluessel].extend(intern["ml_losses"][schluessel])
        zeilen.extend(intern["rows"])

    anzahl = len(basis_verluste["log_loss"])
    basis_kalib, basis_bins = ev.pooled_calibration_error(
        ev.merge_calibration_sums(
            [f["_internal"]["baseline_calibration"] for f in brauchbar]))
    ml_kalib, ml_bins = ev.pooled_calibration_error(
        ev.merge_calibration_sums(
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
        zusammen["delta_" + schluessel] = (zusammen["ml"][schluessel]
                                           - zusammen["baseline"][schluessel])

    zusammen["bootstrap"] = {
        schluessel: ev.paired_bootstrap(basis_verluste[schluessel],
                                        ml_verluste[schluessel])
        for schluessel in ("log_loss", "brier", "rps")
    }
    for intervall in zusammen["bootstrap"].values():
        if intervall:
            intervall["interpretation"] = ev.interpret(intervall)

    zusammen["per_test_season"] = _gruppiere(
        zeilen, basis_verluste["log_loss"], ml_verluste["log_loss"],
        lambda z: z["season"], "season")
    zusammen["per_profile_source"] = _gruppiere(
        zeilen, basis_verluste["log_loss"], ml_verluste["log_loss"],
        profile_source_class, "profile_source")
    zusammen["per_profile_depth"] = _gruppiere(
        zeilen, basis_verluste["log_loss"], ml_verluste["log_loss"],
        depth_class, "profile_depth")
    return zusammen


# ---------------------------------------------------------------------------
# Urteil
# ---------------------------------------------------------------------------

def verdict(zusammen, folds):
    """
    PASS, INCONCLUSIVE oder FAIL - nach vorab festgelegten Regeln.

    Die Schwellen stehen als Modulkonstanten und wurden vor der
    Ergebnisberechnung festgelegt. Diese Funktion wendet sie an; sie
    waehlt sie nicht aus.
    """
    if zusammen is None:
        return {"verdict": "FAIL", "reasons": ["kein auswertbarer Fold"],
                "criteria": _kriterien()}

    delta = zusammen["delta_log_loss"]
    intervall = (zusammen.get("bootstrap") or {}).get("log_loss") or {}
    obergrenze = intervall.get("ci_high")

    gruende = []
    schwere_abfaelle = [f["fold"] for f in folds
                        if "error" not in f
                        and f["delta_log_loss"] >= SEVERE_DEGRADATION]
    zu_klein = zusammen["n"] < MIN_RELIABLE_N

    if delta >= 0:
        urteil = "FAIL"
        gruende.append(
            "aggregiertes delta_log_loss %+.5f ist nicht negativ - das "
            "Modell ist im Mittel nicht besser als die Baseline" % delta)
    elif schwere_abfaelle:
        urteil = "FAIL"
        gruende.append(
            "schwerer Qualitaetsabfall in %s (delta >= %s)"
            % (schwere_abfaelle, SEVERE_DEGRADATION))
    elif zu_klein:
        urteil = "INCONCLUSIVE"
        gruende.append("Stichprobe zu klein (n = %d < %d)"
                       % (zusammen["n"], MIN_RELIABLE_N))
    elif obergrenze is None or obergrenze >= 0:
        urteil = "INCONCLUSIVE"
        gruende.append(
            "Punktschaetzer besser (%+.5f), aber das 95-%%-Intervall "
            "schliesst die Null ein (obere Grenze %s)"
            % (delta, "-" if obergrenze is None else "%+.5f" % obergrenze))
    else:
        urteil = "PASS"
        gruende.append(
            "delta_log_loss %+.5f und obere Intervallgrenze %+.5f liegen "
            "beide unter null" % (delta, obergrenze))

    # Widersprechen sich die Folds im Vorzeichen, ist das auch bei
    # gutem Mittelwert ein Vorbehalt.
    vorzeichen = {f["delta_log_loss"] < 0 for f in folds if "error" not in f}
    if len(vorzeichen) > 1:
        gruende.append("die Folds widersprechen sich im Vorzeichen")
        if urteil == "PASS":
            urteil = "INCONCLUSIVE"

    return {
        "verdict": urteil,
        "reasons": gruende,
        "criteria": _kriterien(),
        "aggregate_delta_log_loss": delta,
        "ci_high": obergrenze,
        "per_fold_delta": {f["fold"]: f.get("delta_log_loss")
                           for f in folds if "error" not in f},
    }


def _kriterien():
    """Die Regeln im Klartext - sie gehoeren ins Artefakt."""
    return {
        "pass": "delta_log_loss < 0 UND obere 95-%-Intervallgrenze < 0 UND "
                "kein Fold mit schwerem Qualitaetsabfall UND kein "
                "Vorzeichenwiderspruch zwischen den Folds",
        "inconclusive": "Punktschaetzer besser, aber Intervall enthaelt "
                        "null; oder Folds widersprechen sich; oder "
                        "Stichprobe zu klein",
        "fail": "delta_log_loss >= 0 oder ein Fold mit delta >= %s"
                % SEVERE_DEGRADATION,
        "severe_degradation_threshold": SEVERE_DEGRADATION,
        "severe_degradation_rationale":
            "Die gesamte auf Ligadaten nachgewiesene Verbesserung betrug "
            "-0,00944 (voller Merkmalssatz) bzw. -0,01446 (profile_only). "
            "Ein Fold, der um mehr als 0,01 schlechter wird, verliert mehr, "
            "als das Verfahren je gewonnen hat. Vor der Messung festgelegt.",
        "min_reliable_n": MIN_RELIABLE_N,
    }


# ---------------------------------------------------------------------------
# Gesamtlauf
# ---------------------------------------------------------------------------

def run_cl_evaluation(zeilen, folds=OUTER_FOLDS, alphas=mdl.ALPHA_CANDIDATES,
                      candidate=CANDIDATE):
    """Der vollstaendige CL-Shadow-Backtest."""
    spalten = fg.columns_for(candidate)

    ergebnisse = [evaluate_fold(zeilen, fold, spalten, alphas)
                  for fold in folds]
    zusammen = aggregate(ergebnisse)
    bewertung = verdict(zusammen, ergebnisse)

    for fold in ergebnisse:
        fold.pop("_internal", None)

    return {
        "candidate": candidate,
        "feature_columns": spalten,
        "feature_count": len(spalten),
        "folds": ergebnisse,
        "aggregate": zusammen,
        "exclusions": excluded_summary(zeilen),
        "verdict": bewertung,
    }
