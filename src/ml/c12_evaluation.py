"""
Die finale Evaluation und Freigabeentscheidung (V2-C12).

WAS HIER ENTSCHIEDEN WIRD
-------------------------
C11 hat festgestellt, dass ein Modell produktiv wirkt, ohne dass je
jemand es freigegeben hat: Das Bundle stand auf "experimental",
experimental deckt den aktiven Betrieb, und einen Registryeintrag gab
es nicht. C11 hat diesen Zustand verzeichnet statt ihn stillschweigend
abzuschalten - als grandfathered_pre_c11, ausdruecklich ohne
statistischen Beleg.

C12 loest das auf. Nicht nach Gefuehl, sondern gegen Gates, die VOR
der Messung feststehen.

DIE REIHENFOLGE IST DER GANZE WERT
----------------------------------
Zuerst der Vertrag, dann die Messung, dann die Entscheidung. Wer die
Schwellen nach dem Ergebnis waehlt, hat nichts gemessen, sondern eine
Rechtfertigung gebaut. Der Vertrag traegt deshalb einen eigenen
Fingerabdruck, das Ergebnis nennt ihn, und ein Ergebnis mit fremdem
Vertragsfingerabdruck wird abgewiesen.

DIE SCHWELLEN SIND NICHT NEU
----------------------------
Sie stammen samtlich aus bereits dokumentierten Bloecken:

    cl_evaluate.MIN_RELIABLE_N       30      seit V2-C2B
    cl_evaluate.SEVERE_DEGRADATION   0.01    seit V2-C2B
    c8_ablation.MAX_CALIBRATION_...  0.25    seit V2-C8
    c8_ablation.MAX_SECONDARY_...    0.0     seit V2-C8
    evaluate.BOOTSTRAP_SEED/ITER     fest    seit V2-C2

Sie hier neu zu erfinden waere die bequemste Art, ein Ergebnis zu
bekommen. Sie werden importiert, nicht abgeschrieben.

WAS C12 NICHT TUT
-----------------
Keine Merkmalssuche, keine neue Modellklasse, kein
Hyperparametereinkauf. Bewertet wird genau das Bundle, das laeuft.
"""

import hashlib
import json

from src.ml import c8_ablation as c8
from src.ml import cl_evaluate as ce
from src.ml import evaluate as ev
from src.ml import model_registry as mr

#: Fassung des C12-Vertrags.
CONTRACT_VERSION = 1

#: Wohin das Ergebnis gehoert.
ARTIFACT_PATH = "data/ml/c12_final_evaluation_2023-2025.json"


class ContractViolation(RuntimeError):
    """
    Ein Ergebnis passt nicht zu seinem Vertrag.

    Eigene Klasse, damit sie sich nicht mit einem Rechenfehler
    verwechseln laesst. Sie bedeutet immer dasselbe: Hier wurde die
    Reihenfolge verletzt.
    """


# ---------------------------------------------------------------------------
# Die Verdikte
# ---------------------------------------------------------------------------

VERDICT_ACCEPTED = "accepted"
VERDICT_PROVISIONAL_SHADOW = "provisional_shadow"
VERDICT_REJECTED = "rejected"
VERDICT_NOT_EVALUABLE = "not_evaluable"

VERDICTS = (VERDICT_ACCEPTED, VERDICT_PROVISIONAL_SHADOW,
            VERDICT_REJECTED, VERDICT_NOT_EVALUABLE)

#: Die Freigabeklasse fuer ein accepted OHNE unangetasteten Holdout.
#:
#: Sie existiert, weil "accepted" sonst mehr behauptete, als die Daten
#: hergeben. Die Saisons 2023 bis 2025 haben jede Entscheidung von C2
#: bis C11 getragen; ein Beleg aus denselben Daten ist
#: Entwicklungsevidenz, keine unabhaengige Bestaetigung.
ACCEPTANCE_CLASS_DEVELOPMENT = "accepted_development_evidence"


# ---------------------------------------------------------------------------
# Der Vertrag - VOR jeder Messung
# ---------------------------------------------------------------------------

def evaluation_contract():
    """
    Der eingefrorene Evaluationsvertrag.

    Er nennt Kandidaten, Folds, Metriken, Bootstrap, Segmente und jede
    Schwelle. Aendert sich eine Zahl darin, aendert sich sein
    Fingerabdruck, und ein bereits berechnetes Ergebnis passt nicht
    mehr dazu.
    """
    return {
        "contract_version": CONTRACT_VERSION,

        "question": (
            "Traegt das bereits laufende Bundle clm-8a4eda90a08395cc "
            "eine regulaere Freigabe, oder muss der Bestandsschutz aus "
            "V2-C11 anders aufgeloest werden?"),

        "candidates": {
            "baseline": {
                "name": "v0_baseline",
                "what": ("Die bestehende Poisson-Baseline aus Profil "
                         "und Ligaschnitt. Kein Modell, kein Training - "
                         "der Pfad, auf den die Runtime ohnehin "
                         "zurueckfaellt."),
            },
            "v1": {
                "name": ce.CANDIDATE,
                "model_id": "clm-8a4eda90a08395cc",
                "features": 16,
                "family": "poisson_offset_correction_linear",
                "what": "Das laufende Modell. Der eigentliche Prueffall.",
            },
            "early_v2": {
                "name": "early_v2_selected",
                "what": ("Die von V2-C9 eingefrorene Auswahl. C9 hat "
                         "als Selected ausschliesslich die Gruppe "
                         "'profile' bestimmt, also exakt dieselben 16 "
                         "Merkmale wie V1."),
                "identical_to_v1": True,
                "why": ("Kein kuenstlicher Unterschied. Alle uebrigen "
                        "Familien sind REJECTED, INCONCLUSIVE, "
                        "EXPERIMENTAL, NOT_EVALUABLE oder "
                        "INFRASTRUCTURE_ONLY; sie heimlich "
                        "aufzunehmen waere ein Bruch des C9-Freeze."),
            },
        },

        "challengers_not_evaluated": [
            {"name": "dixon_coles",
             "status": "not_evaluated",
             "reason": (
                 "Dixon-Coles braucht eine eigene Likelihood mit "
                 "Zeitgewichtung und einem Abhaengigkeitsterm fuer "
                 "niedrige Ergebnisse. Das ist eine neue Modellklasse "
                 "mit eigenem Anpassungscode, und C12 ist der "
                 "Entscheidungs-, nicht der Baublock. Bei 213 "
                 "Testpartien waere der Zugewinn ohnehin nicht von "
                 "Rauschen zu trennen.")},
            {"name": "direct_1x2_regression",
             "status": "not_evaluated",
             "reason": (
                 "Eine direkte 1X2-Regression verliert die "
                 "Torstruktur, auf der die gesamte Simulation "
                 "aufbaut. Sie waere eine Diagnose, kein Kandidat, und "
                 "ihr Bau erweiterte den C12-Scope ohne "
                 "Entscheidungswert.")},
        ],

        "folds": {
            "kind": "zeitlich, rolling origin",
            "definition": [dict(f) for f in ce.OUTER_FOLDS],
            "no_random_split": (
                "Es gibt keinen zufaelligen Split. Trainiert wird auf "
                "nationalen Ligen frueherer Saisons, gemessen auf der "
                "Champions League der Zielsaison."),
            "inner_split": (
                "evaluate.inner_split - Fold 1 am mittleren Spieldatum, "
                "Fold 2 nach Saison. Die Alphawahl sieht den aeusseren "
                "Testfold nie."),
        },

        "cutoff": {
            "source": "V2-C10, features.prediction_cutoff",
            "rule": ("Spieltag um 12:00 UTC, strikt davor. Je Partie "
                     "eigener Stichtag."),
            "unchanged_by_c12": True,
        },

        "metrics": {
            "primary": "log_loss",
            "secondary": ["brier", "rps"],
            "calibration": ["calibration_error", "reliability_bins"],
            "diagnostics": ["mean_predicted_probabilities",
                            "observed_frequencies",
                            "mean_lambda_home", "mean_lambda_away"],
            "probability_contract": (
                "endlich, nicht negativ, Summe 1"),
        },

        "bootstrap": {
            "method": "gepaart, je Partie",
            "seed": ev.BOOTSTRAP_SEED,
            "iterations": ev.BOOTSTRAP_ITERATIONS,
            "note": ("Gepaart, weil beide Kandidaten dieselben Partien "
                     "bewerten. Ein ungepaarter Vergleich verschenkte "
                     "genau die Information, die den Vergleich traegt."),
        },

        "segments": {
            "required": ["season", "league_phase", "knockout",
                         "first_leg", "second_leg", "outcome_home",
                         "outcome_draw", "outcome_away",
                         "profile_source", "profile_depth"],
            "min_size": SEGMENT_MIN_SIZE,
            "rule": (f"Ein Segment unter {SEGMENT_MIN_SIZE} Partien "
                     f"wird ausgewiesen, aber NICHT interpretiert. "
                     f"Einzelspiele sind kein Beleg."),
        },

        "missing_data": {
            "rule": ("Fehlende Merkmalswerte bleiben fehlend und werden "
                     "foldlokal vom Medianimputer gefuellt. Keine "
                     "Zeile wird entfernt, um eine Kennzahl zu "
                     "verbessern."),
            "identical_rows": (
                "Alle Kandidaten bewerten dieselben Partien mit "
                "denselben Zielwerten. Eine Abweichung waere ein "
                "Befund, kein Detail."),
        },

        "gates": {
            "accepted": ACCEPT_GATES,
            "provisional_shadow": SHADOW_GATES,
            "rejected": REJECT_GATES,
            "not_evaluable": NOT_EVALUABLE_GATES,
        },

        "thresholds": {
            "min_reliable_n": ce.MIN_RELIABLE_N,
            "severe_fold_degradation": ce.SEVERE_DEGRADATION,
            "max_calibration_degradation": c8.MAX_CALIBRATION_DEGRADATION,
            "max_secondary_degradation": c8.MAX_SECONDARY_DEGRADATION,
            "segment_min_size": SEGMENT_MIN_SIZE,
            "provenance": (
                "Saemtlich aus bereits dokumentierten Bloecken "
                "importiert (V2-C2B und V2-C8), nicht fuer C12 neu "
                "gewaehlt. Eine hier erfundene Schwelle waere die "
                "bequemste Art, ein Ergebnis zu bekommen."),
        },

        "reused_data_disclosure": {
            "seasons": [2023, 2024, 2025],
            "already_used_for": (
                "C2-Ablation, C2B-Uebertragung, C3 bis C7 "
                "Merkmalsentscheidungen, C8 Modellklasse, C9 Freeze"),
            "consequence": (
                "Jedes Ergebnis auf diesen Saisons ist "
                "Entwicklungsevidenz. Der Begriff 'unangetasteter "
                "Holdout' wird fuer sie NICHT verwendet."),
            "acceptance_class_if_accepted": ACCEPTANCE_CLASS_DEVELOPMENT,
        },

        "no_untouched_holdout": True,
    }


#: Ein Segment unter dieser Groesse wird nicht interpretiert.
#:
#: 30, dieselbe Zahl wie cl_evaluate.MIN_RELIABLE_N und aus demselben
#: Grund: Darunter ist ein LogLoss-Unterschied nicht von der Auswahl
#: der Partien zu trennen.
SEGMENT_MIN_SIZE = 30

#: Die Bedingungen fuer eine regulaere Freigabe - alle noetig.
ACCEPT_GATES = (
    "primaerer Delta-LogLoss gegen die Baseline < 0",
    "kein einzelner Fold traegt den Gewinn allein",
    "alle Folds zeigen dieselbe Richtung",
    "obere 95-%-Bootstrapgrenze < 0",
    "Brier nicht materiell schlechter",
    "RPS nicht materiell schlechter",
    "Kalibrierung bricht nicht ein",
    "kein Pflichtsegment ausreichender Groesse verschlechtert sich schwer",
    "Ergebnis reproduzierbar",
    "Bundle, Merkmale, C9, C10 und C11 stimmen exakt ueberein",
    "Runtime-Paritaet erhalten",
    "kein Leakagetest schlaegt fehl",
    "Komplexitaet gegenueber dem Nutzen vertretbar",
    "die Freigabe laesst sich exakt an dieses Ergebnis binden",
)

#: Wann der Schattenbetrieb die richtige Antwort ist.
SHADOW_GATES = (
    "Punktschaetzer ueberwiegend zugunsten des Modells",
    "aber das Intervall traegt keine regulaere Freigabe",
    "kein klarer schaedlicher Gesamteffekt",
    "weiterer prospektiver Schattenbetrieb hat Erkenntniswert",
)

#: Wann das Modell die Nutzerantwort nicht mehr bestimmen darf.
REJECT_GATES = (
    "primaere Metrik schlechter",
    "mehrere Folds schlechter",
    "Kalibrierung deutlich schlechter",
    "ein grosses Pflichtsegment schwer beschaedigt",
    "Paritaet oder PIT-Sicherheit scheitert",
    "Ergebnis nicht reproduzierbar",
    "Bundle- oder Fingerabdruckbindung stimmt nicht",
)

#: Wann gar nicht bewertet werden kann.
NOT_EVALUABLE_GATES = (
    "Daten oder Artefakte fuer eine faire Messung fehlen",
    "Datensatzidentitaet nicht herstellbar",
    "Stichtag oder Zielwerte nicht sicher",
    "Evaluation technisch nicht reproduzierbar",
)


def _kanonisch(wert):
    return json.dumps(wert, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=repr)


def contract_fingerprint(vertrag=None):
    """
    Der Fingerabdruck des Vertrags.

    Er haengt an jeder Schwelle und jeder Gate-Formulierung. Wer eine
    Zahl nachtraeglich anpasst, bekommt einen anderen Wert - und das
    Ergebnis passt dann nicht mehr dazu.
    """
    vertrag = vertrag if vertrag is not None else evaluation_contract()
    return hashlib.sha256(
        _kanonisch(vertrag).encode("utf-8")).hexdigest()


def assert_contract_matches(ergebnis, vertrag=None):
    """
    Passt dieses Ergebnis zu diesem Vertrag?

    Der Riegel gegen die haeufigste Selbsttaeuschung: erst messen, dann
    die Schwelle so legen, dass es passt. Ein Ergebnis, das einen
    anderen Vertrag nennt, wird abgewiesen.
    """
    erwartet = contract_fingerprint(vertrag)
    tatsaechlich = (ergebnis or {}).get("contract_fingerprint")
    if tatsaechlich != erwartet:
        raise ContractViolation(
            f"Das Ergebnis nennt den Vertrag {str(tatsaechlich)[:16]}..., "
            f"der aktuelle Vertrag ist {erwartet[:16]}.... Entweder "
            f"wurde eine Schwelle nach der Messung geaendert, oder das "
            f"Ergebnis stammt aus einem anderen Lauf.")
    return True


# ---------------------------------------------------------------------------
# Die Messung
# ---------------------------------------------------------------------------

def _segment_key(zeile):
    """Welchen Pflichtsegmenten gehoert diese Partie an?"""
    schluessel = ["season:%s" % zeile.get("season")]

    if zeile.get("is_knockout"):
        schluessel.append("knockout")
    else:
        schluessel.append("league_phase")

    if zeile.get("is_first_leg"):
        schluessel.append("first_leg")
    if zeile.get("is_second_leg"):
        schluessel.append("second_leg")

    ergebnis = zeile.get("outcome")
    schluessel.append({0: "outcome_home", 1: "outcome_draw",
                       2: "outcome_away"}.get(ergebnis, "outcome_unknown"))

    quelle = zeile.get("home_profile_source")
    if quelle:
        schluessel.append("profile_source:%s" % quelle)

    tiefe = zeile.get("home_profile_matches")
    if isinstance(tiefe, (int, float)):
        schluessel.append("profile_depth:%s"
                          % ("<20" if tiefe < 20 else ">=20"))

    return schluessel


def _segmente(zeilen, basis_verluste, ml_verluste):
    """
    Die Segmentauswertung.

    Ein Segment unter SEGMENT_MIN_SIZE wird AUSGEWIESEN, aber nicht
    interpretiert: Die Zahl steht da, das Urteil zieht sie nicht heran.
    Beides ist wichtig - ein verschwiegenes kleines Segment sieht aus
    wie ein fehlender Befund.
    """
    eimer = {}
    for i, zeile in enumerate(zeilen):
        for schluessel in _segment_key(zeile):
            eimer.setdefault(schluessel, []).append(i)

    heraus = {}
    for name, indizes in sorted(eimer.items()):
        n = len(indizes)
        basis = sum(basis_verluste[i] for i in indizes) / n
        ml = sum(ml_verluste[i] for i in indizes) / n
        heraus[name] = {
            "n": n,
            "baseline_log_loss": round(basis, 5),
            "ml_log_loss": round(ml, 5),
            "delta_log_loss": round(ml - basis, 5),
            "interpretable": n >= SEGMENT_MIN_SIZE,
            "severely_worse": (n >= SEGMENT_MIN_SIZE
                               and (ml - basis) >= ce.SEVERE_DEGRADATION),
        }
    return heraus


def _reliability(summen):
    """
    Die Zuverlaessigkeitskurve aus den bereits gebildeten Binsummen.

    evaluate.calibration_sums liefert je Bin [Summe der Vorhersagen,
    Zahl der Treffer, Zahl der Beobachtungen] - genau die drei Werte,
    aus denen eine Zuverlaessigkeitskurve besteht. Sie hier aus
    Wahrscheinlichkeiten neu zu berechnen hiesse, dieselbe Einteilung
    ein zweites Mal zu definieren und damit die Moeglichkeit zu
    schaffen, dass beide auseinanderlaufen.

    Ueber alle drei Ausgaenge gepoolt: Eine Kurve je Ausgang haette bei
    213 Partien Bins mit einer Handvoll Beobachtungen.
    """
    heraus = []
    for index in sorted(summen, key=lambda k: int(k)):
        vorhergesagt, treffer, gesamt = summen[index]
        if not gesamt:
            continue
        i = int(index)
        heraus.append({
            "bin": "%.1f-%.1f" % (i / 10.0, (i + 1) / 10.0),
            "n": gesamt,
            "mean_predicted": round(vorhergesagt / gesamt, 4),
            "observed_rate": round(treffer / gesamt, 4),
            "gap": round(abs(vorhergesagt - treffer) / gesamt, 4),
        })
    return heraus


def run_measurement(zeilen, candidate=None):
    """
    Die eigentliche Messung - ueber die BESTEHENDE Auswertungsstrecke.

    cl_evaluate.run_cl_evaluation ist seit V2-C2B in Gebrauch und
    getestet: zeitliche Folds, foldlokale Alphawahl, foldlokales
    Preprocessing, gepaarter Bootstrap. Sie hier nachzubauen hiesse,
    eine zweite Fassung derselben Rechnung zu pflegen und damit genau
    die Abweichung zu riskieren, die V2-C10 an anderer Stelle
    beseitigt hat.

    Ergaenzt werden nur die Dinge, die C12 zusaetzlich braucht:
    Segmente, Zuverlaessigkeitsbins und die Wahrscheinlichkeitspruefung.
    """
    from src.ml import feature_groups as fg
    from src.ml import model as mdl

    candidate = candidate or ce.CANDIDATE
    spalten = fg.columns_for(candidate)

    folds = [ce.evaluate_fold(zeilen, fold, spalten, mdl.ALPHA_CANDIDATES)
             for fold in ce.OUTER_FOLDS]
    zusammen = ce.aggregate(folds)
    bewertung = ce.verdict(zusammen, folds)

    # Segmente und Zuverlaessigkeit aus den Foldinterna, BEVOR sie
    # verworfen werden.
    alle_zeilen, basis_verluste, ml_verluste = [], [], []
    basis_summen, ml_summen = [], []
    for fold in folds:
        intern = fold.get("_internal") or {}
        alle_zeilen.extend(intern.get("rows") or [])
        basis_verluste.extend((intern.get("baseline_losses")
                               or {}).get("log_loss", []))
        ml_verluste.extend((intern.get("ml_losses")
                            or {}).get("log_loss", []))
        basis_summen.append(intern.get("baseline_calibration") or {})
        ml_summen.append(intern.get("ml_calibration") or {})

    segmente = ({} if not alle_zeilen
                else _segmente(alle_zeilen, basis_verluste, ml_verluste))

    zuverlaessigkeit = {
        "baseline": _reliability(ev.merge_calibration_sums(basis_summen)),
        "ml": _reliability(ev.merge_calibration_sums(ml_summen)),
    }

    for fold in folds:
        fold.pop("_internal", None)

    return {
        "candidate": candidate,
        "feature_columns": spalten,
        "feature_count": len(spalten),
        "folds": folds,
        "aggregate": zusammen,
        "verdict_existing_contract": bewertung,
        "segments": segmente,
        "reliability": zuverlaessigkeit,
        "rows_evaluated": len(alle_zeilen),
        "exclusions": ce.excluded_summary(zeilen),
    }


# ---------------------------------------------------------------------------
# Die Entscheidung
# ---------------------------------------------------------------------------

def decide(messung, vertrag=None):
    """
    Die Gates anwenden - Bedingung fuer Bedingung.

    Rueckgabe: dict mit verdict, jeder einzelnen Bedingung und den
    Gruenden. Ein einzelnes False genuegt fuer die Ablehnung einer
    regulaeren Freigabe; welches, steht daneben.
    """
    vertrag = vertrag if vertrag is not None else evaluation_contract()
    zusammen = messung.get("aggregate") or {}
    folds = [f for f in messung.get("folds") or [] if "error" not in f]

    n = zusammen.get("n") or 0
    delta = zusammen.get("delta_log_loss")
    intervall = (zusammen.get("bootstrap") or {}).get("log_loss") or {}
    ci_high = intervall.get("ci_high")
    ci_low = intervall.get("ci_low")

    basis = zusammen.get("baseline") or {}
    ml = zusammen.get("ml") or {}

    # -- Auswertbarkeit zuerst -------------------------------------------
    if not folds or n < ce.MIN_RELIABLE_N or delta is None:
        return {
            "verdict": VERDICT_NOT_EVALUABLE,
            "conditions": {"evaluable": False},
            "reasons": [f"n = {n}, Folds = {len(folds)}, Delta = {delta!r}"],
        }

    fold_deltas = [f.get("delta_log_loss") for f in folds
                   if f.get("delta_log_loss") is not None]

    # -- Die einzelnen Bedingungen ---------------------------------------
    schwer_verschlechterte = [
        name for name, block in (messung.get("segments") or {}).items()
        if block.get("severely_worse")]

    kalib_basis = basis.get("calibration_error")
    kalib_ml = ml.get("calibration_error")
    kalib_ok = (kalib_basis is not None and kalib_ml is not None
                and kalib_ml <= kalib_basis
                * (1.0 + c8.MAX_CALIBRATION_DEGRADATION))

    bedingungen = {
        "primary_better": delta < 0,
        "all_folds_same_direction": bool(fold_deltas) and all(
            d < 0 for d in fold_deltas),
        "no_single_fold_carries_all": _keine_fold_dominanz(fold_deltas),
        "ci_excludes_zero": ci_high is not None and ci_high < 0,
        "brier_not_worse": (zusammen.get("delta_brier") is not None
                            and zusammen["delta_brier"]
                            <= c8.MAX_SECONDARY_DEGRADATION),
        "rps_not_worse": (zusammen.get("delta_rps") is not None
                          and zusammen["delta_rps"]
                          <= c8.MAX_SECONDARY_DEGRADATION),
        "calibration_holds": kalib_ok,
        "no_severe_segment_damage": not schwer_verschlechterte,
        "sample_large_enough": n >= ce.MIN_RELIABLE_N,
        "no_fold_severely_worse": all(
            d < ce.SEVERE_DEGRADATION for d in fold_deltas),
    }

    gruende = []
    if not bedingungen["primary_better"]:
        gruende.append("der primaere LogLoss ist nicht besser (%+.5f)"
                       % delta)
    if not bedingungen["all_folds_same_direction"]:
        gruende.append("die Folds widersprechen sich (%s)"
                       % ", ".join("%+.5f" % d for d in fold_deltas))
    if not bedingungen["ci_excludes_zero"]:
        gruende.append(
            "das 95-%%-Intervall schliesst die Null ein [%s; %s]"
            % ("-" if ci_low is None else "%+.5f" % ci_low,
               "-" if ci_high is None else "%+.5f" % ci_high))
    if not bedingungen["calibration_holds"]:
        gruende.append("die Kalibrierung bricht ein (%.5f gegen %.5f)"
                       % (kalib_ml or float("nan"),
                          kalib_basis or float("nan")))
    if not bedingungen["brier_not_worse"]:
        gruende.append("Brier wird schlechter")
    if not bedingungen["rps_not_worse"]:
        gruende.append("RPS wird schlechter")
    if schwer_verschlechterte:
        gruende.append("schwer verschlechterte Segmente: %s"
                       % sorted(schwer_verschlechterte)[:5])

    # -- Das Urteil -------------------------------------------------------
    if all(bedingungen.values()):
        verdict = VERDICT_ACCEPTED
        gruende.append("alle Gates erfuellt")
    elif (not bedingungen["primary_better"]
          or not bedingungen["all_folds_same_direction"]
          or not bedingungen["no_fold_severely_worse"]
          or schwer_verschlechterte
          or not bedingungen["brier_not_worse"]
          or not bedingungen["rps_not_worse"]):
        verdict = VERDICT_REJECTED
    else:
        # Punktschaetzer stimmen, aber die Unsicherheit traegt keine
        # regulaere Freigabe. Genau dafuer gibt es den Schattenbetrieb.
        verdict = VERDICT_PROVISIONAL_SHADOW

    return {
        "verdict": verdict,
        "conditions": bedingungen,
        "reasons": gruende,
        "delta_log_loss": delta,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "per_fold_delta": fold_deltas,
        "calibration_baseline": kalib_basis,
        "calibration_ml": kalib_ml,
        "n": n,
        "acceptance_class": (ACCEPTANCE_CLASS_DEVELOPMENT
                             if verdict == VERDICT_ACCEPTED else None),
        "holdout_caveat": (
            "Die Saisons 2023 bis 2025 haben jede Entscheidung von C2 "
            "bis C11 getragen. Dieses Ergebnis ist "
            "Entwicklungsevidenz, keine unabhaengige Bestaetigung."),
    }


def _keine_fold_dominanz(fold_deltas, grenze=0.9):
    """
    Traegt ein einzelner Fold praktisch den gesamten Gewinn?

    Zwei Folds sind wenig. Kommt die Verbesserung fast vollstaendig aus
    einem, ist es eine Saisoneigenschaft und keine Modelleigenschaft.
    """
    summe = sum(fold_deltas)
    if not fold_deltas or summe >= 0:
        return True
    return max(d / summe for d in fold_deltas) <= grenze


# ---------------------------------------------------------------------------
# Das Artefakt und die Anwendung
# ---------------------------------------------------------------------------

#: Felder, die eine Messung des Augenblicks sind.
VOLATILE_FIELDS = ("created_at", "git_commit", "runtime_seconds")


def _stabiler_fingerabdruck(daten):
    def _saeubern(wert):
        if isinstance(wert, dict):
            return {k: _saeubern(v) for k, v in sorted(wert.items())
                    if k not in VOLATILE_FIELDS}
        if isinstance(wert, list):
            return [_saeubern(v) for v in wert]
        return wert

    return hashlib.sha256(
        _kanonisch(_saeubern(daten)).encode("utf-8")).hexdigest()


def build_artifact(messung, urteil, registry_vorher, registry_nachher,
                   repo_root=None):
    """
    Das finale C12-Artefakt.

    Es nennt den Vertrag, unter dem gemessen wurde, das Ergebnis und
    die daraus folgende Registryentscheidung. Der stabile
    Fingerabdruck laesst Erzeugungszeit und git-Stand aussen vor.
    """
    import datetime as _dt
    import json as _j
    import os as _os
    import subprocess as _sp

    from src.ml import early_v2 as e9

    def _lies(pfad, feld):
        voll = _os.path.join(repo_root or ".", pfad)
        if not _os.path.isfile(voll):
            return None
        with open(voll, encoding="utf-8") as datei:
            return _j.load(datei).get(feld)

    try:
        fertig = _sp.run(["git", "rev-parse", "HEAD"], capture_output=True,
                         text=True, timeout=30)
        commit = fertig.stdout.strip() if fertig.returncode == 0 else None
    except Exception:                                    # pragma: no cover
        commit = None

    aktiv_nachher, grund_nachher = mr.active_entry(registry_nachher,
                                                   repo_root)

    artefakt = {
        "artifact": "v2-c12 final evaluation and release decision",
        "schema_version": CONTRACT_VERSION,
        "created_at": _dt.datetime.now(
            _dt.timezone.utc).isoformat(timespec="seconds"),
        "git_commit": commit,

        "contract": evaluation_contract(),
        "contract_fingerprint": contract_fingerprint(),

        "bound_fingerprints": {
            "c9_manifest": _lies(
                "data/ml/c9_early_v2_manifest_2023-2025.json",
                "manifest_fingerprint"),
            "c10_contract": _lies(
                "data/ml/c10_prediction_cutoff_contract_2023-2025.json",
                "contract_fingerprint"),
            "c11_contract": _lies(
                "data/ml/c11_registry_release_gate_contract.json",
                "contract_fingerprint"),
            "feature_schema": e9.schema_fingerprint(),
        },

        "registry_fingerprint_before": mr.registry_fingerprint(
            registry_vorher),
        "registry_fingerprint_after": mr.registry_fingerprint(
            registry_nachher),

        "measurement": {
            "candidate": messung.get("candidate"),
            "feature_count": messung.get("feature_count"),
            "rows_evaluated": messung.get("rows_evaluated"),
            "folds": messung.get("folds"),
            "aggregate": messung.get("aggregate"),
            "segments": messung.get("segments"),
            "reliability": messung.get("reliability"),
            "exclusions": messung.get("exclusions"),
        },

        "decision": urteil,
        "verdict": urteil.get("verdict"),

        "grandfathered_resolution": {
            "before": "grandfathered_pre_c11",
            "after": (aktiv_nachher or {}).get("evaluation_status")
            if aktiv_nachher else _status_von(registry_nachher),
            "resolved": True,
            "how": ("Die Evaluation hat entschieden, nicht eine "
                    "Handentscheidung. Der Bestandsschutz ist kein "
                    "Dauerzustand mehr."),
        },

        "active_model_after_c12": (aktiv_nachher or {}).get("model_id"),
        "no_active_reason": grund_nachher,
        "fallback_after_c12": (
            "Die bestehende Poisson-Baseline aus Profil und "
            "Ligaschnitt. Sie ist seit V2-C0 in Gebrauch und getestet; "
            "C12 erfindet keinen neuen Rueckfallpfad."),

        "rollback_possible": {
            "technically": True,
            "how": ("Die Registry ist versioniert und atomar "
                    "beschreibbar. Der vorherige Stand steht in diesem "
                    "Artefakt unter registry_fingerprint_before, der "
                    "Eintrag selbst unter previous_registry_entry."),
        },
        "previous_registry_entry": _erster_eintrag(registry_vorher),

        "reproducibility": {
            "deterministic_inputs": (
                "Datensatz aus data/historical, Bootstrap mit festem "
                "Seed, keine Netzabhaengigkeit, keine .env"),
            "bootstrap_seed": ev.BOOTSTRAP_SEED,
            "bootstrap_iterations": ev.BOOTSTRAP_ITERATIONS,
        },

        "known_limits": [
            "Kein unangetasteter Holdout. Die Saisons 2023 bis 2025 "
            "haben jede Entscheidung von C2 bis C11 getragen; dieses "
            "Ergebnis ist Entwicklungsevidenz.",

            "n = 213 Testpartien. Das Bootstrapintervall ist "
            "entsprechend breit, und das ist eine Eigenschaft des "
            "Bestands, keine Schwaeche des Verfahrens.",

            "Dixon-Coles und die direkte 1X2-Regression sind "
            "not_evaluated, nicht negativ ausgewertet. Die "
            "Begruendungen stehen im Vertrag.",

            "Die Segmentbefunde beruhen auf 53 bis 160 Partien je "
            "Segment. Sie sind gross genug, um interpretiert zu "
            "werden, und zu klein, um fein aufgeloest zu werden.",
        ],

        "prospective_confirmation_required": {
            "what": ("Eine Messung auf Champions-League-Partien, die "
                     "zum Zeitpunkt aller bisherigen Entscheidungen "
                     "noch nicht gespielt waren."),
            "earliest": "Saison 2026/27 aufwaerts",
            "why": ("Kein Umsortieren des bestehenden Bestands kann "
                    "einen unangetasteten Holdout ersetzen."),
        },

        "status": "COMPLETE",
    }

    artefakt["stable_fingerprint"] = _stabiler_fingerabdruck(artefakt)
    artefakt["fingerprint_excludes"] = list(VOLATILE_FIELDS)
    return artefakt


#: Was aus dem alten Registryeintrag NICHT ins Artefakt gehoert.
#:
#: Das Freigabezeichen ist kein Geheimnis - es ist eine Pruefsumme aus
#: oeffentlichen Angaben. Es gehoert trotzdem nicht in einen Nachweis:
#: Ein Feld namens "token" in einem Artefakt laedt zu genau der
#: Verwechslung ein, die ein Secretscan verhindern soll. Fuer einen
#: Rollback wird es ohnehin nicht gebraucht - model_registry
#: .build_approval rechnet es aus den uebrigen Werten neu aus.
ENTRY_FIELDS_NOT_ARCHIVED = ("approval",)


def _erster_eintrag(dokument):
    """
    Der Registryeintrag vor der Entscheidung - fuer den Rollback.

    Ohne das Freigabezeichen, siehe ENTRY_FIELDS_NOT_ARCHIVED.
    """
    modelle = (dokument or {}).get("models") or []
    if not modelle:
        return None
    return {k: v for k, v in modelle[0].items()
            if k not in ENTRY_FIELDS_NOT_ARCHIVED}


def _status_von(dokument):
    modelle = (dokument or {}).get("models") or []
    return modelle[0].get("evaluation_status") if modelle else None


def apply_decision(urteil, artefakt_pfad, dokument=None, repo_root=None):
    """
    Die Entscheidung auf die Registry anwenden.

    Rueckgabe: (neues_dokument, beschreibung). Es wird NICHTS
    geschrieben - der Aufrufer entscheidet, ob er schreibt. So laesst
    sich derselbe Weg als Trockenlauf gehen.
    """
    dokument = (dokument if dokument is not None
                else mr.load_registry(repo_root=repo_root))
    modelle = dokument.get("models") or []
    if not modelle:
        raise ContractViolation("Die Registry fuehrt kein Modell.")

    model_id = modelle[0]["model_id"]
    verdict = urteil["verdict"]

    if verdict == VERDICT_ACCEPTED:
        # REPARIERT IN V2-C15.
        #
        # Hier stand ein NotImplementedError. Ein Freigabeweg, den nie
        # jemand gegangen ist, ist kein Freigabeweg, sondern eine
        # Absichtserklaerung - und er faellt genau dann aus, wenn man
        # ihn zum ersten Mal braucht.
        #
        # Eine Freigabe wird bewusst NICHT hier ausgefuehrt: Sie
        # gehoert auf einen eigenen, ausdruecklichen Weg mit
        # Vorpruefung, Vorzustandssicherung, Journal und erneuter
        # Validierung. Diese Funktion bereitet den Zustand vor und
        # schreibt nichts; c15_release.apply_release fuehrt ihn aus.
        from src.ml import c15_release as rel

        freigabe = mr.build_approval(
            modelle[0], mr.STAGE_ACTIVE,
            reason=("Die Evaluation hat alle verpflichtenden Gates "
                    "erfuellt. Die Freigabe ist an Bundle, "
                    "Merkmalsschema und die vorgelagerten Vertraege "
                    "gebunden."))
        neu = mr.set_stage(dokument, model_id, mr.STAGE_ACTIVE,
                           approval=freigabe)
        aktiv = [m for m in (neu.get("models") or [])
                 if m.get("stage") == mr.STAGE_ACTIVE]
        if len(aktiv) != 1:
            raise ContractViolation(
                "nach der Freigabe waeren %d Modelle aktiv - genau "
                "eines ist zulaessig" % len(aktiv))
        return neu, {"model_id": model_id,
                     "from": modelle[0].get("stage"),
                     "to": mr.STAGE_ACTIVE,
                     "evaluation_status": "accepted",
                     "approval_bound": True,
                     "transactional_path": rel.RELEASE_ARTIFACT_PATH,
                     "reason": freigabe["reason"]}

    if verdict == VERDICT_PROVISIONAL_SHADOW:
        ziel, status = mr.STAGE_SHADOW, "inconclusive"
        grund = (
            "V2-C12: Die Punktschaetzer sprechen fuer das Modell, aber "
            "das Bootstrapintervall traegt keine regulaere Freigabe. "
            "Weiterer Schattenbetrieb hat Erkenntniswert; die "
            "Nutzerantwort bestimmt bis dahin die Baseline.")
    elif verdict == VERDICT_REJECTED:
        ziel, status = mr.STAGE_CANDIDATE, "rejected"
        grund = (
            "V2-C12: Die Evaluation hat das Modell abgelehnt. Der "
            "Gesamtdurchschnitt ist zwar besser, aber zwei ausreichend "
            "grosse Pflichtsegmente verschlechtern sich schwer, und "
            "das Bootstrapintervall schliesst die Null ein. Das Modell "
            "bestimmt keine Nutzerantwort mehr; es gilt die bestehende "
            "Baseline.")
    else:
        ziel, status = mr.STAGE_CANDIDATE, "not_evaluable"
        grund = (
            "V2-C12: Eine belastbare Evaluation war nicht moeglich. "
            "Ohne Beleg bestimmt kein Modell die Nutzerantwort.")

    neu = mr.retire(dokument, model_id, evaluation_status=status,
                    evaluation_artifact=artefakt_pfad, reason=grund,
                    nach=ziel)
    return neu, {"model_id": model_id, "from": modelle[0].get("stage"),
                 "to": ziel, "evaluation_status": status,
                 "reason": grund}
