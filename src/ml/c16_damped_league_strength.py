"""
Gedaempfte Ligastaerke und finale Freigabeentscheidung (V2-C16).

DIE FRAGE
---------
V2-C15 bestand zehn von elf Gates. Gescheitert ist genau eines:

    no_severe_segment_damage
    home_origin_league:PD   n=36   +0,01186   Grenze +0,01000

Die Ligastaerkekorrektur wirkt insgesamt stark und richtig
(-0,095118 gegen V0, Intervall [-0,131169; -0,057305]), aber sie
ueberkorrigiert an einer Stelle knapp ueber die eingefrorene Grenze.

WAS C16 AUSDRUECKLICH NICHT TUT
-------------------------------
Es baut KEINE spanische Ausnahme. Kein `if league == "PD"`, kein
eigener Faktor fuer eine im Test auffaellige Liga, keine
Vereinsnamen in der Modelllogik, kein Routing nach Testsegment. Eine
Regel, die aus einem Testergebnis entsteht, ist keine Regel, sondern
eine Anpassung an genau diesen Test.

Ebenso wenig wird die Grenze von 0,01 gelockert, umdefiniert oder
anders interpretiert. Sie stammt aus V2-C2B und bleibt, wo sie ist.

WAS C16 TUT
-----------
Genau eine generalisierte Aenderung: eine GLOBALE Daempfung der
gesamten Ligastaerkekorrektur.

    lambda_heim' = lambda_heim * exp(gamma * (a[liga_heim] + d[liga_gast]))
    lambda_gast' = lambda_gast * exp(gamma * (a[liga_gast] + d[liga_heim]))

`gamma` liegt in (0, 1] und wirkt auf JEDE Liga gleich. Bei gamma = 1
ist das Wort fuer Wort die C15-Formel; kleinere Werte ziehen alle
Ligafaktoren gleichmaessig Richtung 1.

Der Gedanke dahinter ist kein Ausweichen vor dem PD-Segment, sondern
der uebliche Umgang mit einer aus wenigen Partien geschaetzten
Groesse: Fold 1 schaetzt 30 Parameter aus 218 Beobachtungen. Eine
Punktschaetzung aus so wenig Material ist im Mittel zu gross, und
gamma ist die einfachste Form, sie zu schrumpfen. Dass davon auch das
PD-Segment profitiert, ist eine Folge und nicht der Zweck.

DIE AUSWAHL VON GAMMA
---------------------
Vier vorab eingefrorene Werte, gewaehlt auf einer zeitlichen inneren
Validierung INNERHALB der Trainingshistorie. Der aeussere Testfold
sieht weder Gamma noch Alpha. Bei Gleichstand gewinnt das kleinere
Gamma, also die vorsichtigere Wahl.

DIE REIHENFOLGE
---------------
Vertrag, dann Messung, dann Entscheidung. `evaluation_contract()` ist
vollstaendig bildbar, ohne dass eine Zahl gerechnet wurde.
"""

import hashlib
import json

from src.features import league_strength as ls
from src.ml import c8_ablation as c8
from src.ml import cl_evaluate as ce
from src.ml import evaluate as ev
from src.ml import feature_groups as fg

CONTRACT_VERSION = "v2-c16.1"

CONTRACT_PATH = "data/ml/c16_damped_league_strength_contract.json"
ARTIFACT_PATH = "data/ml/c16_damped_league_strength_evaluation.json"
RELEASE_PATH = "data/ml/c16_damped_league_strength_release.json"


class ContractViolation(RuntimeError):
    """Ein Ergebnis gehoert nicht zu diesem Vertrag. Nie stillschweigend."""


VERDICT_ACCEPTED = "accepted"
VERDICT_PROVISIONAL_SHADOW = "provisional_shadow"
VERDICT_REJECTED = "rejected"
VERDICT_NOT_EVALUABLE = "not_evaluable"

VERDICTS = (VERDICT_ACCEPTED, VERDICT_PROVISIONAL_SHADOW,
            VERDICT_REJECTED, VERDICT_NOT_EVALUABLE)

ACCEPTANCE_CLASS_DEVELOPMENT = "accepted_development_evidence"

#: Unveraendert aus V2-C2B/C8/C14/C15.
SEGMENT_MIN_SIZE = 30

TOP5_LEAGUES = ("BL1", "PL", "PD", "SA", "FL1")

THIN_EVIDENCE_MAX = 20

#: Der Kandidatenname. Eigene Gruppe, damit ein C15-Bundle nicht
#: versehentlich als C16-Modell durchgeht.
CANDIDATE = "team_profile_cl_plus_damped_league_strength"


def _kanonisch(wert):
    return json.dumps(wert, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def _stabil(block):
    return hashlib.sha256(_kanonisch(block).encode("utf-8")).hexdigest()


def _alpha_kandidaten():
    from src.ml import model as mdl

    return tuple(mdl.ALPHA_CANDIDATES)


# ---------------------------------------------------------------------------
# Das Modellschema
# ---------------------------------------------------------------------------

def model_schema():
    """
    Das vollstaendige Schema des C16-Kandidaten.

    Es deckt beide Stufen UND die Daempfung ab. Nur die Spaltenliste zu
    binden waere hier gefaehrlich: Sie ist mit C14 und C15 identisch,
    und ein Bundle der einen Stufe passte sonst zum anderen Modell,
    obwohl es etwas anderes rechnet.
    """
    return {
        "schema_version": CONTRACT_VERSION,
        "candidate": CANDIDATE,
        "base_columns": sorted(fg.columns_for(fg.C15_CANDIDATE)),
        "base_column_count": len(fg.columns_for(fg.C15_CANDIDATE)),
        "stages": [
            {"stage": 1, "name": "national_base",
             "model_class": "poisson_offset_correction_linear",
             "trained_on": "nationale Ligazeilen der Trainingssaisons",
             "alpha_space": list(_alpha_kandidaten())},
            {"stage": 2, "name": "damped_league_strength",
             "model_class": "poisson_ridge_league_offsets_damped",
             "trained_on": "ausschliesslich CL-Partien frueherer Saisons",
             "parameters": ("je Liga ein offensiver und ein defensiver "
                            "log-Multiplikator, dazu EIN globaler "
                            "Daempfungsfaktor gamma"),
             "alpha_space": list(_alpha_kandidaten()),
             "gamma_grid": list(ls.GAMMA_GRID),
             "factor_bounds": [ls.FACTOR_MIN, ls.FACTOR_MAX],
             "min_observations": ls.MIN_OBSERVATIONS},
        ],
    }


def schema_fingerprint():
    return _stabil(model_schema())


# ---------------------------------------------------------------------------
# Der Vertrag
# ---------------------------------------------------------------------------

def evaluation_contract():
    """Der vollstaendige Vertrag - ohne eine einzige gemessene Zahl."""
    from src.features import prediction_cutoff as pc
    from src.ml import c13_contract as c13
    from src.ml import c14_reevaluation as c14
    from src.ml import c15_league_strength as c15
    from src.ml import early_v2 as e9
    from src.ml import model_registry as mr

    return {
        "version": CONTRACT_VERSION,
        "purpose": (
            "Prueft, ob eine GLOBALE Daempfung der C15-Ligastaerke die "
            "verbliebene Ueberkorrektur beseitigt, ohne den belegten "
            "Gesamtvorteil und die Foldstabilitaet zu verlieren."),

        "exactly_one_candidate": (
            "C16 bewertet genau einen Challenger. Mehrere "
            "Daempfungsvarianten waeren verstecktes Modellshopping."),

        "no_league_specific_rule": (
            "Die Daempfung wirkt auf JEDE Liga mit demselben gamma. Es "
            "gibt keine Sonderregel fuer PD, keine Vereinsnamen in der "
            "Modelllogik und kein Routing nach Testsegment. Eine Regel, "
            "die aus einem Testergebnis entsteht, waere eine Anpassung "
            "an genau diesen Test."),

        "no_gate_change": (
            "Die Grenze fuer schwere Segmentverschlechterung bleibt bei "
            "0,01 aus V2-C2B. Sie wird nicht gelockert, nicht "
            "umdefiniert und nicht anders interpretiert. Das PD-Segment "
            "wird nicht entfernt und nicht verkleinert."),

        # -- Kandidat und Kontrollen ---------------------------------------
        "candidate": {
            "name": CANDIDATE,
            "schema": model_schema(),
            "schema_fingerprint": schema_fingerprint(),
            "derived_from": c15.CANDIDATE if hasattr(c15, "CANDIDATE")
                            else fg.C15_CANDIDATE,
        },
        "controls": {
            "v0": {"name": "v0_baseline",
                   "what": "die bestehende Poisson-Baseline, kein Modell"},
            "c14_v2": {"name": ce.CANDIDATE,
                       "expected_delta_log_loss": -0.011628},
            "c15": {"name": fg.C15_CANDIDATE,
                    "expected_delta_log_loss": -0.095118,
                    "expected_folds": [-0.066131, -0.125147],
                    "known_blocker": {
                        "segment": "home_origin_league:PD",
                        "n": 36, "delta_log_loss": 0.01186,
                        "threshold": 0.01}},
            "fairness": ("Alle vier bewerten identische Match-IDs, "
                         "identische Zielwerte, identische Folds und "
                         "identische Ausschluesse."),
        },

        # -- Die Daempfung ---------------------------------------------------
        "damping": {
            "form": ("lambda_heim' = lambda_heim * exp(gamma * "
                     "(a[liga_heim] + d[liga_gast])); lambda_gast' = "
                     "lambda_gast * exp(gamma * (a[liga_gast] + "
                     "d[liga_heim]))"),
            "range": "0 < gamma <= 1",
            "grid": list(ls.GAMMA_GRID),
            "grid_frozen_before_measurement": True,
            "no_grid_extension": (
                "Das Gitter wird nach Sichtung der Ergebnisse nicht "
                "erweitert."),
            "global_only": (
                "EIN gamma fuer alle Ligen. Ein ligaspezifisches gamma "
                "waere genau die Sonderregel, die C16 vermeiden soll."),
            "gamma_1_is_c15": (
                "Bei gamma = 1 ist die Formel Wort fuer Wort die "
                "C15-Formel. C15 liegt damit im Kandidatenraum und "
                "kann gewinnen."),
            "why_damping": (
                "Fold 1 schaetzt 30 Ligaparameter aus 218 "
                "Beobachtungen. Eine Punktschaetzung aus so wenig "
                "Material ist im Mittel zu gross. gamma ist die "
                "einfachste generalisierte Form, sie zu schrumpfen."),
            "selection": {
                "where": ("zeitliche innere Validierung AUSSCHLIESSLICH "
                          "innerhalb der Trainingshistorie"),
                "inner_split": ("bei einer Trainingssaison Teilung am "
                                "mittleren Spieldatum, bei mehreren "
                                "Teilung nach Saison - dieselbe Regel "
                                "wie fuer Alpha"),
                "criterion": "Poissondevianz auf dem spaeteren Teil",
                "tolerance": ls.GAMMA_TOLERANCE,
                "tie_break": ("kleineres Gamma gewinnt - weniger "
                              "Korrektur ist die vorsichtigere Wahl"),
                "outer_fold_never_seen": True,
            },
            "fallback_if_no_inner_split": {
                "rule": ("Reicht die Historie fuer keine faire innere "
                         "Auswahl, gilt das KLEINSTE Gamma des Gitters."),
                "why": ("Ohne Beleg wird am wenigsten korrigiert. "
                        "Testdaten als Ersatz zu benutzen waere die "
                        "Alternative und ist ausgeschlossen."),
                "must_be_reported": True,
            },
        },

        "alpha_selection": {
            "space": list(_alpha_kandidaten()),
            "rule": ("unveraendert aus V2-C15: zeitliche innere "
                     "Teilung innerhalb der Trainingshistorie, "
                     "Poissondevianz, bei Gleichstand groesseres Alpha"),
            "order": ("Alpha wird zuerst gewaehlt, dann Gamma auf "
                      "derselben inneren Validierung. Sequentiell und "
                      "nicht als Gitter ueber beide, weil zwanzig "
                      "Kombinationen eine Suche waeren und vier eine "
                      "Auswahl."),
        },

        "league_strength": {
            "estimator": ("PoissonRegressor ohne Achsenabschnitt ueber "
                          "den Offset-Umweg, unveraendert aus C15"),
            "training_source": ("ausschliesslich CL-Partien aus Saisons "
                                "vollstaendig vor der Testsaison"),
            "league_provenance": ("Vereins-ID zu Ligacode ueber den "
                                  "validierten C13-Crosswalk"),
            "cold_start": {
                "rule": ("Eine Liga ohne fruehere CL-Historie bekommt "
                         "den Wert 0 und damit den Faktor 1 - "
                         "unabhaengig von gamma."),
                "neutral": True,
                "never_a_bonus": True,
                "finite_and_deterministic": True,
            },
            "unknown_league": (
                "Eine Liga, die die Schaetzung nicht kennt, traegt 0 "
                "bei. Was auf sie wirkt, ist ausschliesslich die "
                "Staerke des BEKANNTEN Gegners."),
            "missing_provenance": (
                "Laesst sich fuer eine Seite keine Herkunftsliga "
                "bestimmen, bleibt die Partie unkorrigiert (Faktor 1 "
                "auf beiden Seiten). Neutral statt geraten."),
            "bounds": {"factor_min": ls.FACTOR_MIN,
                       "factor_max": ls.FACTOR_MAX,
                       "applied_after_damping": True},
            "min_observations": ls.MIN_OBSERVATIONS,
        },

        # -- Bindungen -------------------------------------------------------
        "bound_contracts": {
            "c9_schema_fingerprint": e9.schema_fingerprint(),
            "c10_cutoff_hour": pc.CUTOFF_HOUR,
            "c10_inclusive": pc.CUTOFF_INCLUSIVE,
            "c11_contract_fingerprint": _stabil(mr.contract()),
            "c13_contract_fingerprint": c13.contract_fingerprint(),
            "c14_contract_fingerprint": c14.contract_fingerprint(),
            "c15_contract_fingerprint": c15.contract_fingerprint(),
            "c15_model_schema_fingerprint": c15.schema_fingerprint(),
        },

        # -- Bestaende --------------------------------------------------------
        "inventories": {
            "standard": {"selector": "cl_evaluate.cl_rows",
                         "expected_rows": 283,
                         "carries_release_decision": True},
            "context": {"selector": "cl_evaluate.context_rows",
                        "expected_rows": 373,
                        "carries_release_decision": False,
                        "blocking_rule": (
                            "Genau eine Kontextbedingung sperrt: ein "
                            "Gesamtdelta ab SEVERE_DEGRADATION.")},
            "deviation_is_a_blocker": (
                "Weicht eine Bestandsgroesse ab, ist das ein Befund und "
                "wird erklaert, nicht still uebernommen."),
        },

        "folds": {
            "standard": [dict(f) for f in ce.OUTER_FOLDS],
            "context": [dict(f) for f in ce.CONTEXT_FOLDS],
            "chronological_only": True,
            "no_random_split": True,
            "preprocessing": "foldlokal, nie auf dem Testfold",
            "calibration": "foldlokal, nie auf dem Testfold",
        },

        "prediction_cutoff": {
            "hour": pc.CUTOFF_HOUR,
            "inclusive": pc.CUTOFF_INCLUSIVE,
            "applies_to": ["nationale Profile", "Ligastaerkehistorie",
                           "Crosswalk"],
            "unchanged_by_c16": True,
        },

        "metrics": {
            "primary": "log_loss",
            "primary_comparison": "C16 gegen V0",
            "additional_comparisons": ["C16 gegen C14", "C16 gegen C15"],
            "secondary": ["brier", "rps"],
            "supporting": ["accuracy", "calibration_error",
                           "reliability_bins",
                           "mean_predicted_probabilities",
                           "observed_frequencies",
                           "mean_lambda_home", "mean_lambda_away",
                           "extreme_probabilities"],
            "probability_contract": ("endlich, nicht negativ, Summe 1; "
                                     "NaN und Infinity sind ein Befund"),
        },

        "bootstrap": {"method": "gepaart, je Partie", "seed": 20260827,
                      "iterations": 2000,
                      "source": "unveraendert aus V2-C2B/C12/C14/C15"},

        "segments": {
            "min_size": SEGMENT_MIN_SIZE,
            "min_size_source": "V2-C2B/C8, nicht fuer C16 neu gewaehlt",
            "thin_evidence_max": THIN_EVIDENCE_MAX,
            "mandatory": [
                "season:*", "fold:*", "phase:league", "phase:knockout",
                "stage:*", "leg:first", "leg:second", "leg:single",
                "leg:final",
                "origin:top5_vs_top5", "origin:top5_vs_other",
                "origin:other_vs_top5", "origin:other_vs_other",
                "home_origin_league:*", "away_origin_league:*",
                "league_evidence:cold_start", "league_evidence:thin",
                "league_evidence:strong",
                "home_profile_depth:*", "away_profile_depth:*",
                "min_profile_depth:*", "both_profile_depth:>=20",
                "match_balance:*", "outcome:*", "home_data_quality:*",
            ],
            "directed_and_symmetric": True,
            "overlap_rule": ("Segmente mit identischer Zeilenmenge "
                             "bilden eine Gruppe und zaehlen als EIN "
                             "Befund."),
            "explicitly_watched": ["home_origin_league:PD",
                                   "origin:top5_vs_other"],
            "no_segment_removed": (
                "Kein Segment wird entfernt oder verkleinert, um ein "
                "Gate zu erfuellen."),
        },

        "missing_data": {
            "rule": ("Fehlende Merkmalswerte bleiben fehlend und werden "
                     "foldlokal vom Medianimputer gefuellt."),
            "identical_rows": ("V0, C14, C15 und C16 bewerten dieselben "
                               "Partien mit denselben Zielwerten."),
            "exclusions_are_rule_based": True,
        },

        "calibration": {
            "allowed": ["keine zusaetzliche Kalibrierung"],
            "forbidden": ["neue Kalibrierungsmethode",
                          "Fit auf dem Testfold",
                          "Auswahl anhand des Testfolds"],
            "max_degradation": c8.MAX_CALIBRATION_DEGRADATION,
        },

        "thresholds": {
            "severe_degradation": ce.SEVERE_DEGRADATION,
            "max_secondary_degradation": c8.MAX_SECONDARY_DEGRADATION,
            "max_calibration_degradation": c8.MAX_CALIBRATION_DEGRADATION,
            "min_reliable_n": ce.MIN_RELIABLE_N,
            "segment_min_size": SEGMENT_MIN_SIZE,
            "fold_dominance_limit": 0.9,
            "provenance": ("saemtlich aus V2-C2B, V2-C8, V2-C12, V2-C14 "
                           "und V2-C15 importiert, nicht fuer C16 neu "
                           "gewaehlt"),
        },

        "gates": {
            "accepted": [
                "primary_better", "all_folds_same_direction",
                "no_single_fold_carries_all", "ci_excludes_zero",
                "brier_not_worse", "rps_not_worse", "calibration_holds",
                "no_severe_segment_damage", "sample_large_enough",
                "no_fold_severely_worse",
                "context_not_severely_damaged"],
            "provisional_shadow": [
                "Punktschaetzer zugunsten des Modells",
                "kein klarer schaedlicher Gesamteffekt",
                "aber Intervall oder Foldstabilitaet tragen keine "
                "regulaere Freigabe"],
            "rejected": [
                "primaere Metrik schlechter", "Folds widersprechen sich",
                "ein Fold schwer verschlechtert",
                "ein grosses Pflichtsegment schwer beschaedigt",
                "Brier oder RPS materiell schlechter",
                "Kontextbestand schwer beschaedigt",
                "PIT oder Leakage scheitert",
                "Ergebnis nicht reproduzierbar"],
            "not_evaluable": [
                "zu wenige Folds oder Zeilen",
                "Datensatzidentitaet nicht herstellbar",
                "Zielwerte nicht stabil",
                "Messung technisch nicht reproduzierbar",
                "innere Auswahl in einem Fold nicht fair moeglich und "
                "Ersatzregel nicht tragfaehig"],
            "no_new_verdict_class": (
                "Es gibt genau vier Urteile. Eine fuenfte Klasse waere "
                "die bequemste Art, ein unbequemes Ergebnis "
                "umzubenennen."),
        },

        "acceptance_class_if_accepted": ACCEPTANCE_CLASS_DEVELOPMENT,

        "no_untouched_holdout": {
            "true": True,
            "already_used_for": ("C2 bis C15, einschliesslich der "
                                 "C15-Diagnose, die zu dieser "
                                 "Daempfung gefuehrt hat"),
            "consequence": (
                "Die Daempfungsform wurde aus einem C15-Ergebnis auf "
                "denselben Saisons abgeleitet. Das ist "
                "Entwicklungsevidenz und ausdruecklich keine "
                "unabhaengige Bestaetigung. Eine unabhaengige "
                "Bestaetigung waere erst mit Saison 2026/27 moeglich."),
        },

        "no_result_peeking": (
            "Kein Messergebnis darf diesen Vertrag veraendern. Ein "
            "Ergebnis unter einem anderen Vertragsfingerabdruck wird "
            "zurueckgewiesen."),
    }


def contract_fingerprint(vertrag=None):
    return _stabil(vertrag if vertrag is not None
                   else evaluation_contract())


def assert_contract_matches(ergebnis, vertrag=None):
    """Fail-closed: Ohne passenden Fingerabdruck wird abgelehnt."""
    erwartet = contract_fingerprint(vertrag)
    gefunden = (ergebnis or {}).get("contract_fingerprint")
    if gefunden != erwartet:
        raise ContractViolation(
            "Das Ergebnis gehoert nicht zu diesem Vertrag. Erwartet "
            "%s, gefunden %r." % (erwartet, gefunden))
    return True


# ---------------------------------------------------------------------------
# Schreiben
# ---------------------------------------------------------------------------

def _atomar_schreiben(pfad, inhalt):
    """Atomar, damit ein Abbruch keine halbe Datei hinterlaesst."""
    import os
    import pathlib
    import tempfile

    pfad = pathlib.Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    griff, temp = tempfile.mkstemp(dir=str(pfad.parent), suffix=".tmp")
    try:
        with os.fdopen(griff, "w", encoding="utf-8") as datei:
            datei.write(inhalt + "\n")
            datei.flush()
            os.fsync(datei.fileno())
        os.replace(temp, pfad)
    except BaseException:                                # pragma: no cover
        if os.path.exists(temp):
            os.unlink(temp)
        raise
    return str(pfad)


def write_contract(pfad=None):
    """Den Vertrag festschreiben - VOR der Messung."""
    import datetime as _dt

    vertrag = evaluation_contract()
    dokument = {
        "artifact": "v2-c16 damped league strength contract",
        "schema_version": CONTRACT_VERSION,
        "created_at": _dt.datetime.now(
            _dt.timezone.utc).isoformat(timespec="seconds"),
        "frozen_before_measurement": True,
        "contract": vertrag,
        "contract_fingerprint": contract_fingerprint(vertrag),
        "model_schema_fingerprint": schema_fingerprint(),
        "fingerprint_excludes": ["created_at", "git_commit",
                                 "jeder Messwert", "Registryzustand"],
    }
    return _atomar_schreiben(pfad or CONTRACT_PATH,
                             json.dumps(dokument, indent=2,
                                        ensure_ascii=False))


# ---------------------------------------------------------------------------
# Ein Fold, vier Kandidaten
# ---------------------------------------------------------------------------

def evaluate_fold(zeilen, fold, ligakarte, train_rows=None,
                  test_rows=None):
    """
    Ein aeusserer Fold mit V0, C14, C15 und C16 auf DENSELBEN Zeilen.

    Stufe eins und die Ligaschaetzung sind Wort fuer Wort die
    C15-Rechnung. C16 ergaenzt genau eine Sache: die auf der inneren
    Validierung gewaehlte Daempfung.
    """
    from src.ml import c15_league_strength as c15
    from src.ml import model as mdl

    spalten = fg.columns_for(fg.C15_CANDIDATE)
    waehle_training = train_rows or ce.league_rows
    waehle_test = test_rows or (lambda z, s: ce.cl_rows(z, s[0]))

    training = waehle_training(zeilen, fold["train_seasons"])
    test = waehle_test(zeilen, [fold["test_season"]])
    if not training or not test:
        return {"fold": fold["name"], "error": "zu wenig Daten",
                "train_rows": len(training), "test_rows": len(test)}

    # -- Stufe eins: das unveraenderte nationale Basismodell -------------
    fit_z, val_z, innen = ev.inner_split(
        training, {"train_seasons": fold["train_seasons"]},
        select=waehle_training)
    kandidat, modelle, wahl = ev.select_candidate(
        fit_z, val_z, spalten, mdl.ALPHA_CANDIDATES)
    if kandidat != mdl.NO_CORRECTION:
        heim, _ = mdl.fit_side(training, "home", kandidat, spalten)
        gast, _ = mdl.fit_side(training, "away", kandidat, spalten)
        modelle = {"home": heim, "away": gast}

    def basis_lambdas(rows):
        lam, _ = ev.predict_lambdas(kandidat, modelle, rows, spalten)
        return lam

    # -- Stufe zwei: Ligastaerke aus frueheren CL-Partien ----------------
    historie = c15.league_history(zeilen, fold["train_seasons"])
    h_frueh, h_spaet, h_innen = c15._innere_teilung(historie,
                                                    fold["train_seasons"])

    alpha, alpha_protokoll = None, {"strategy": "keine Historie"}
    if h_frueh and h_spaet:
        alpha, alpha_protokoll = ls.select_alpha(
            h_frueh, basis_lambdas(h_frueh), h_spaet,
            basis_lambdas(h_spaet), ligakarte, mdl.ALPHA_CANDIDATES)
    if alpha is None:
        alpha = max(mdl.ALPHA_CANDIDATES)
        alpha_protokoll = dict(alpha_protokoll,
                               fallback="staerkste Regularisierung")

    staerke = ls.estimate(historie, basis_lambdas(historie), ligakarte,
                          alpha)

    # -- Die Daempfung, auf DERSELBEN inneren Validierung -----------------
    #
    # Wichtig: Geschaetzt wird fuer die Auswahl auf dem FRUEHEN Teil und
    # bewertet auf dem SPAETEN. Sonst waehlte gamma auf denselben
    # Partien, aus denen die Ligaparameter stammen, und das kleinste
    # gamma haette nie eine Chance.
    gamma, gamma_protokoll = None, {"strategy": "keine innere Teilung"}
    if h_frueh and h_spaet:
        staerke_innen = ls.estimate(h_frueh, basis_lambdas(h_frueh),
                                    ligakarte, alpha)
        gamma, gamma_protokoll = ls.select_gamma(
            staerke_innen, h_spaet, basis_lambdas(h_spaet), ligakarte)
    if gamma is None:
        # Vertraglich festgelegte Ersatzregel: ohne Beleg wird am
        # wenigsten korrigiert.
        gamma = min(ls.GAMMA_GRID)
        gamma_protokoll = dict(gamma_protokoll,
                               fallback="kleinstes Gamma des Gitters")

    staerke_c16 = staerke.with_gamma(gamma)

    # -- Die vier Vorhersagen auf identischen Testzeilen ------------------
    ausgaenge = [z["outcome"] for z in test]
    v0_p = ev.probabilities_for(mdl.baseline_lambdas(test))

    c14_lambdas = basis_lambdas(test)
    c14_p = ev.probabilities_for(c14_lambdas)

    c15_lambdas, _ = ls.apply_factors(staerke, test, c14_lambdas,
                                      ligakarte)
    c15_p = ev.probabilities_for(c15_lambdas)

    c16_lambdas, klammern = ls.apply_factors(staerke_c16, test,
                                             c14_lambdas, ligakarte)
    c16_p = ev.probabilities_for(c16_lambdas)

    for p in (c14_p, c15_p, c16_p):
        ce.assert_paired(test, v0_p, p)

    v0 = ev.summarise(v0_p, ausgaenge)
    c14 = ev.summarise(c14_p, ausgaenge)
    c15_m = ev.summarise(c15_p, ausgaenge)
    c16 = ev.summarise(c16_p, ausgaenge)

    return {
        "fold": fold["name"],
        "train_seasons": list(fold["train_seasons"]),
        "test_season": fold["test_season"],
        "train_rows": len(training),
        "test_rows": len(test),
        "inner_split": innen,
        "base_candidate": kandidat,
        "base_selection": wahl,
        "league_history_rows": len(historie),
        "league_inner_split": h_innen,
        "league_inner_fit_rows": len(h_frueh),
        "league_inner_validation_rows": len(h_spaet),
        "league_alpha": alpha,
        "league_alpha_selection": alpha_protokoll,
        "gamma": gamma,
        "gamma_selection": gamma_protokoll,
        "league_strength": staerke_c16.summary(),
        "league_clamps": klammern,
        "parameter_fingerprint": _stabil({
            "alpha": alpha, "gamma": gamma,
            "attack": {k: round(v, 8)
                       for k, v in sorted(staerke.attack.items())},
            "defence": {k: round(v, 8)
                        for k, v in sorted(staerke.defence.items())}}),
        "v0": v0, "c14": c14, "c15": c15_m, "c16": c16,
        "delta_log_loss": c16["log_loss"] - v0["log_loss"],
        "delta_brier": c16["brier"] - v0["brier"],
        "delta_rps": c16["rps"] - v0["rps"],
        "delta_vs_c14": c16["log_loss"] - c14["log_loss"],
        "delta_vs_c15": c16["log_loss"] - c15_m["log_loss"],
        "c15_delta_log_loss": c15_m["log_loss"] - v0["log_loss"],
        "c14_delta_log_loss": c14["log_loss"] - v0["log_loss"],
        "mean_probabilities": {
            "v0": c15._mittel(v0_p), "c14": c15._mittel(c14_p),
            "c15": c15._mittel(c15_p), "c16": c15._mittel(c16_p),
            "observed": c15._beobachtet(ausgaenge)},
        "extreme_probabilities": {
            "v0": c15._extreme(v0_p), "c16": c15._extreme(c16_p)},
        "mean_lambdas": {
            "c14": c15._mittlere_lambdas(c14_lambdas),
            "c15": c15._mittlere_lambdas(c15_lambdas),
            "c16": c15._mittlere_lambdas(c16_lambdas)},
        "_internal": {
            "rows": test,
            "v0_losses": ev.per_match_losses(v0_p, ausgaenge),
            "c14_losses": ev.per_match_losses(c14_p, ausgaenge),
            "c15_losses": ev.per_match_losses(c15_p, ausgaenge),
            "c16_losses": ev.per_match_losses(c16_p, ausgaenge),
            "v0_calibration": ev.calibration_sums(v0_p, ausgaenge),
            "c16_calibration": ev.calibration_sums(c16_p, ausgaenge),
            "staerke": staerke_c16,
        },
    }


# ---------------------------------------------------------------------------
# Die Messung
# ---------------------------------------------------------------------------

def _aggregiere(folds, basis_key, ml_key):
    """Zwei Kandidaten ueber beide Folds, gepaarter Bootstrap."""
    basis_v, ml_v, n = [], [], 0
    for fold in folds:
        intern = fold["_internal"]
        basis_v.extend(intern[basis_key]["log_loss"])
        ml_v.extend(intern[ml_key]["log_loss"])
        n += fold["test_rows"]
    if not basis_v:
        return {"n": 0}
    basis_ll = sum(basis_v) / len(basis_v)
    ml_ll = sum(ml_v) / len(ml_v)
    return {"n": n,
            "baseline_log_loss": round(basis_ll, 6),
            "ml_log_loss": round(ml_ll, 6),
            "delta_log_loss": ml_ll - basis_ll,
            "bootstrap": {"log_loss": ev.paired_bootstrap(basis_v, ml_v)}}


def _karte_fuer(ligakarte, fold):
    """
    Die Zuordnung DIESES Folds.

    Additiv seit V2-C19: `ligakarte` darf eine Funktion sein, die je
    Fold eine eigene Karte liefert. Eine Karte fuer alle Folds bleibt
    zulaessig und veraendert nichts - der bisherige Aufrufweg geht
    unveraendert durch.

    Der Grund fuer die Erweiterung: Eine Zuordnung, die ueber den
    gesamten lokalen Bestand gebildet ist, kennt auch Saisons nach dem
    Testzeitpunkt eines Folds. Fuer eine Struktureigenschaft wirkt das
    harmlos, ist es aber nicht - der fruehere Fold wuesste dann von
    Vereinen, die es zu seiner Zeit noch nicht gab.
    """
    return ligakarte(fold) if callable(ligakarte) else ligakarte


def _messe_bestand(zeilen, name, folds_def, ligakarte, train_rows,
                   test_rows):
    """Ein Bestand, alle vier Kandidaten, dieselbe Strecke."""
    from src.ml import c15_league_strength as c15

    folds = [evaluate_fold(zeilen, fold, _karte_fuer(ligakarte, fold),
                           train_rows, test_rows)
             for fold in folds_def]
    gute = [f for f in folds if "error" not in f]
    if not gute:
        return {"inventory": name, "folds": folds, "error": "kein Fold"}

    test_zeilen, eintraege = [], []
    verluste = {k: [] for k in ("v0", "c14", "c15", "c16")}
    v0_kal, c16_kal = [], []
    for fold in gute:
        intern = fold["_internal"]
        staerke = intern["staerke"]
        fold_karte = _karte_fuer(ligakarte, fold)
        for zeile in intern["rows"]:
            test_zeilen.append(zeile)
            eintraege.append((zeile, c15._segment_keys(
                zeile, fold_karte, staerke, fold["fold"])))
        for k in verluste:
            verluste[k].extend(intern["%s_losses" % k]["log_loss"])
        v0_kal.append(intern["v0_calibration"])
        c16_kal.append(intern["c16_calibration"])

    def gewichtet(kandidat, metrik):
        gesamt, zaehler = 0.0, 0
        for fold in gute:
            gesamt += fold[kandidat][metrik] * fold["test_rows"]
            zaehler += fold["test_rows"]
        return gesamt / zaehler if zaehler else None

    METRIKEN = ("log_loss", "brier", "rps", "calibration_error",
                "accuracy_supplementary")
    aggregat = dict(_aggregiere(gute, "v0_losses", "c16_losses"))
    for kandidat in ("v0", "c14", "c15", "c16"):
        aggregat[kandidat] = {m: gewichtet(kandidat, m)
                              for m in METRIKEN}
    aggregat["delta_brier"] = (aggregat["c16"]["brier"]
                               - aggregat["v0"]["brier"])
    aggregat["delta_rps"] = aggregat["c16"]["rps"] - aggregat["v0"]["rps"]
    aggregat["baseline"] = {
        "log_loss": aggregat["v0"]["log_loss"],
        "calibration_error": aggregat["v0"]["calibration_error"]}
    aggregat["ml"] = {
        "log_loss": aggregat["c16"]["log_loss"],
        "calibration_error": aggregat["c16"]["calibration_error"]}
    aggregat["c16_vs_c14"] = _aggregiere(gute, "c14_losses", "c16_losses")
    aggregat["c16_vs_c15"] = _aggregiere(gute, "c15_losses", "c16_losses")
    aggregat["c15_vs_v0"] = _aggregiere(gute, "v0_losses", "c15_losses")
    aggregat["c14_vs_v0"] = _aggregiere(gute, "v0_losses", "c14_losses")

    segmente = c15._segmente(eintraege, verluste["v0"], verluste["c16"])
    segmente_c15 = c15._segmente(eintraege, verluste["v0"],
                                 verluste["c15"])

    for fold in folds:
        fold.pop("_internal", None)

    return {
        "inventory": name,
        "folds": folds,
        "aggregate": aggregat,
        "segments": segmente,
        "segments_c15_reference": segmente_c15,
        "distinct_damage": c15.distinct_damage(segmente),
        "distinct_damage_c15": c15.distinct_damage(segmente_c15),
        # Konzentration ist eine Diagnose UEBER die Folds hinweg und
        # braucht deshalb eine einzelne Karte. Genommen wird die des
        # letzten Folds, also die weiteste zulaessige - eine engere
        # wuerde spaetere Testzeilen faelschlich als unbekannt fuehren.
        "concentration": c15.concentration(
            test_zeilen, verluste["v0"], verluste["c16"],
            _karte_fuer(ligakarte, gute[-1])),
        "reliability": {
            "v0": c15._reliability(ev.merge_calibration_sums(v0_kal)),
            "c16": c15._reliability(ev.merge_calibration_sums(c16_kal))},
        "rows_evaluated": len(test_zeilen),
        "distinct_row_ids": len({z["row_id"] for z in test_zeilen}),
    }


def run_measurement(zeilen, ligakarte=None):
    """Standard- und Kontextbestand, alle vier Kandidaten."""
    import collections

    from src.ml import c14_reevaluation as c14

    # Eine Karte fuer alle Folds oder eine Funktion je Fold - beides
    # zulaessig (V2-C19). Ohne Angabe bleibt es beim bisherigen Weg.
    ligakarte = ligakarte if ligakarte is not None else c14.team_league_map()
    cl_zeilen = [z for z in zeilen if z.get("league") == "cl"]

    standard = _messe_bestand(zeilen, "standard", ce.OUTER_FOLDS,
                              ligakarte, None, None)
    kontext = _messe_bestand(zeilen, "context", ce.CONTEXT_FOLDS,
                             ligakarte, ce.context_training_rows,
                             ce.context_rows)

    quellen = collections.Counter()
    for zeile in cl_zeilen:
        for seite in ("home", "away"):
            quellen[zeile.get(seite + "_profile_source")] += 1

    return {
        "candidate": CANDIDATE,
        "model_schema_fingerprint": schema_fingerprint(),
        "feature_columns": sorted(fg.columns_for(fg.C15_CANDIDATE)),
        "dataset": {
            "total_rows": len(zeilen),
            "cl_rows": len(cl_zeilen),
            "dataset_fingerprint": ce.dataset_fingerprint(zeilen),
            "pure_target_fingerprint": c14.pure_target_fingerprint(zeilen),
            "profile_sources": dict(sorted(quellen.items())),
            "evaluation_eligible": sum(
                1 for z in cl_zeilen if z.get("evaluation_eligible")),
            "knockout_eligible": sum(
                1 for z in cl_zeilen if z.get("knockout_eligible")),
        },
        "exclusions": ce.excluded_summary(zeilen),
        "standard": standard,
        "context": kontext,
    }


# ---------------------------------------------------------------------------
# Die Entscheidung
# ---------------------------------------------------------------------------

def _keine_fold_dominanz(fold_deltas, grenze=0.9):
    """Unveraendert aus V2-C12/C14/C15."""
    summe = sum(fold_deltas)
    if not fold_deltas or summe >= 0:
        return True
    return max(d / summe for d in fold_deltas) <= grenze


#: Fuer jede Bedingung ein Klartextgrund. Uebernommen aus V2-C15, wo
#: die Vollstaendigkeit der Gruendeliste repariert wurde.
REASON_TEXTS = {
    "primary_better": "der primaere LogLoss ist nicht besser",
    "all_folds_same_direction": "die Folds widersprechen sich",
    "no_single_fold_carries_all": "ein einzelner Fold traegt den Gewinn",
    "ci_excludes_zero": "das 95-%-Intervall schliesst die Null ein",
    "brier_not_worse": "Brier wird materiell schlechter",
    "rps_not_worse": "RPS wird materiell schlechter",
    "calibration_holds": "die Kalibrierung bricht ein",
    "no_severe_segment_damage": "ein grosses Pflichtsegment ist schwer "
                                "verschlechtert",
    "sample_large_enough": "die Stichprobe ist zu klein",
    "no_fold_severely_worse": "ein Fold ist schwer verschlechtert",
    "context_not_severely_damaged": "der Kontextbestand ist schwer "
                                    "beschaedigt",
}


def decide(messung, vertrag=None):
    """
    Die Gates anwenden - Bedingung fuer Bedingung.

    Jede Schwelle stammt aus einem frueher freigegebenen Vertrag. Jede
    fehlgeschlagene Bedingung erscheint in `reasons`.
    """
    vertrag = vertrag if vertrag is not None else evaluation_contract()

    standard = messung.get("standard") or {}
    kontext = messung.get("context") or {}
    zusammen = standard.get("aggregate") or {}
    folds = [f for f in standard.get("folds") or [] if "error" not in f]

    n = zusammen.get("n") or 0
    delta = zusammen.get("delta_log_loss")
    intervall = (zusammen.get("bootstrap") or {}).get("log_loss") or {}
    ci_high = intervall.get("ci_high")
    ci_low = intervall.get("ci_low")

    if not folds or n < ce.MIN_RELIABLE_N or delta is None:
        return {
            "verdict": VERDICT_NOT_EVALUABLE,
            "conditions": {"evaluable": False},
            "reasons": ["n = %s, Folds = %s, Delta = %r"
                        % (n, len(folds), delta)],
            "contract_fingerprint": contract_fingerprint(vertrag),
        }

    fold_deltas = [f.get("delta_log_loss") for f in folds
                   if f.get("delta_log_loss") is not None]
    schaden = standard.get("distinct_damage") or []

    kalib_basis = (zusammen.get("baseline") or {}).get("calibration_error")
    kalib_ml = (zusammen.get("ml") or {}).get("calibration_error")
    kalib_ok = (kalib_basis is not None and kalib_ml is not None
                and kalib_ml <= kalib_basis
                * (1.0 + c8.MAX_CALIBRATION_DEGRADATION))

    kontext_delta = (kontext.get("aggregate") or {}).get("delta_log_loss")
    kontext_ok = (kontext_delta is None
                  or kontext_delta < ce.SEVERE_DEGRADATION)

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
        "no_severe_segment_damage": not schaden,
        "sample_large_enough": n >= ce.MIN_RELIABLE_N,
        "no_fold_severely_worse": all(
            d < ce.SEVERE_DEGRADATION for d in fold_deltas),
        "context_not_severely_damaged": kontext_ok,
    }

    messwerte = {
        "primary_better": "%+.6f" % delta,
        "all_folds_same_direction": ", ".join("%+.6f" % d
                                              for d in fold_deltas),
        "no_single_fold_carries_all": ", ".join("%+.6f" % d
                                                for d in fold_deltas),
        "ci_excludes_zero": "[%s; %s]" % (
            "-" if ci_low is None else "%+.6f" % ci_low,
            "-" if ci_high is None else "%+.6f" % ci_high),
        "brier_not_worse": "%s" % zusammen.get("delta_brier"),
        "rps_not_worse": "%s" % zusammen.get("delta_rps"),
        "calibration_holds": "%s gegen %s" % (kalib_ml, kalib_basis),
        "no_severe_segment_damage": "%s" % (schaden[:5] or "keine"),
        "sample_large_enough": "n=%d" % n,
        "no_fold_severely_worse": "max %s" % (
            "%+.6f" % max(fold_deltas) if fold_deltas else "-"),
        "context_not_severely_damaged": "%s" % kontext_delta,
    }
    gruende = ["%s (%s)" % (REASON_TEXTS[name], messwerte.get(name, ""))
               for name in sorted(bedingungen)
               if not bedingungen[name] and name in REASON_TEXTS]

    if all(bedingungen.values()):
        verdict = VERDICT_ACCEPTED
        gruende = ["alle Gates erfuellt"]
    elif (not bedingungen["primary_better"]
          or not bedingungen["all_folds_same_direction"]
          or not bedingungen["no_fold_severely_worse"]
          or schaden
          or not bedingungen["brier_not_worse"]
          or not bedingungen["rps_not_worse"]
          or not bedingungen["context_not_severely_damaged"]):
        verdict = VERDICT_REJECTED
    else:
        verdict = VERDICT_PROVISIONAL_SHADOW

    return {
        "verdict": verdict,
        "conditions": bedingungen,
        "reasons": gruende,
        "failed_conditions": sorted(k for k, v in bedingungen.items()
                                    if not v),
        "measured_values": messwerte,
        "delta_log_loss": delta,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "per_fold_delta": fold_deltas,
        "calibration_baseline": kalib_basis,
        "calibration_ml": kalib_ml,
        "context_delta_log_loss": kontext_delta,
        "delta_vs_c14": (zusammen.get("c16_vs_c14") or {}).get(
            "delta_log_loss"),
        "delta_vs_c15": (zusammen.get("c16_vs_c15") or {}).get(
            "delta_log_loss"),
        "n": n,
        "distinct_damage": schaden,
        "acceptance_class": (ACCEPTANCE_CLASS_DEVELOPMENT
                             if verdict == VERDICT_ACCEPTED else None),
        "holdout_caveat": (
            "Die Daempfungsform wurde aus einem C15-Ergebnis auf "
            "denselben Saisons abgeleitet. Entwicklungsevidenz, keine "
            "unabhaengige Bestaetigung."),
        "contract_fingerprint": contract_fingerprint(vertrag),
    }


# ---------------------------------------------------------------------------
# Das Ergebnisartefakt
# ---------------------------------------------------------------------------

VOLATILE_FIELDS = ("created_at", "git_commit", "runtime_seconds")


def _git_commit():
    import subprocess

    try:
        lauf = subprocess.run(["git", "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10)
        return lauf.stdout.strip() or None
    except Exception:                                    # pragma: no cover
        return None


def result_fingerprint(artefakt):
    """Der fachliche Fingerabdruck, ohne Zeit und git-Stand."""
    ohne = {k: v for k, v in artefakt.items()
            if k not in VOLATILE_FIELDS and k != "result_fingerprint"}
    return _stabil(json.loads(json.dumps(ohne, sort_keys=True,
                                         default=str)))


def build_artifact(messung, urteil, zeilen=None, ligakarte=None):
    """Der C16-Nachweis - deterministisch und ohne Rohdaten."""
    import datetime as _dt

    from src.features import prediction_cutoff as pc
    from src.ml import c13_contract as c13
    from src.ml import c14_reevaluation as c14
    from src.ml import c15_league_strength as c15
    from src.ml import early_v2 as e9
    from src.ml import model_registry as mr

    vertrag = evaluation_contract()
    aktiv, grund = mr.active_entry()

    artefakt = {
        "artifact": "v2-c16 damped league strength evaluation",
        "schema_version": CONTRACT_VERSION,
        "created_at": _dt.datetime.now(
            _dt.timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),

        "contract_fingerprint": contract_fingerprint(vertrag),
        "contract_frozen_before_measurement": True,
        "contract_path": CONTRACT_PATH,
        "model_schema_fingerprint": schema_fingerprint(),

        "bound_contracts": {
            "c9_schema_fingerprint": e9.schema_fingerprint(),
            "c10_cutoff_hour": pc.CUTOFF_HOUR,
            "c10_inclusive": pc.CUTOFF_INCLUSIVE,
            "c11_contract_fingerprint": _stabil(mr.contract()),
            "c13_contract_fingerprint": c13.contract_fingerprint(),
            "c14_contract_fingerprint": c14.contract_fingerprint(),
            "c15_contract_fingerprint": c15.contract_fingerprint(),
            "c15_model_schema_fingerprint": c15.schema_fingerprint(),
        },

        "candidate": vertrag["candidate"],
        "controls": vertrag["controls"],
        "damping": vertrag["damping"],

        "identifiability": (
            c15._identifizierbarkeitsnachweis(zeilen, ligakarte)
            if zeilen is not None and ligakarte is not None else None),

        "measurement": messung,
        "decision": urteil,
        "verdict": urteil["verdict"],

        "registry": {
            "active_model_before": (aktiv or {}).get("model_id"),
            "no_active_reason_before": grund,
            "changed_by_evaluation": False,
            "why": ("Die Evaluation entscheidet und aktiviert nicht. "
                    "Eine Aktivierung laeuft ausschliesslich ueber den "
                    "ausdruecklichen C11-Freigabeweg."),
        },

        "fingerprint_excludes": list(VOLATILE_FIELDS),

        "known_limits": [
            "Kein unangetasteter Holdout. Die Daempfungsform wurde aus "
            "einem C15-Ergebnis auf denselben Saisons abgeleitet; das "
            "ist Entwicklungsevidenz und keine unabhaengige "
            "Bestaetigung. Eine unabhaengige Bestaetigung waere erst "
            "mit Saison 2026/27 moeglich.",
            "Zwei aeussere Folds sind wenig. Eine Foldabweichung kann "
            "eine Saisoneigenschaft sein.",
            "Fold 1 schaetzt die Ligastaerke aus 109 frueheren "
            "CL-Partien ueber 15 Ligen.",
            "Die Konzentrationsdiagnose hat keine numerische Schwelle "
            "und ist deshalb kein Gate.",
        ],
    }
    artefakt["result_fingerprint"] = result_fingerprint(artefakt)
    return artefakt


def write_artifact(messung, urteil, pfad=None, zeilen=None,
                   ligakarte=None):
    return _atomar_schreiben(
        pfad or ARTIFACT_PATH,
        json.dumps(build_artifact(messung, urteil, zeilen, ligakarte),
                   indent=2, ensure_ascii=False, default=str))
