"""
Ligastaerke, finale Evaluation und Freigabe (V2-C15).

DIE FRAGE
---------
V2-C14 lehnte ab, und der Grund war diesmal kein Datenfehler, sondern
ein Modellfehler mit klarer Ursache: Die 16 Merkmale sind
Verhaeltniswerte zur eigenen Liga und tragen keine Ligastaerke.

    origin:top5_vs_other   n=73   +0,01453   schwer verschlechtert

C15 fuegt genau eine Sache hinzu: eine zweite Modellstufe fuer die
Staerke der Herkunftsliga, geschaetzt ausschliesslich aus frueheren
Champions-League-Begegnungen.

WARUM DIE ZWEITE STUFE UND NICHT EINE WEITERE SPALTE
-----------------------------------------------------
Ein Ligastaerkemerkmal im bisherigen Trainingsbestand waere ein totes
Merkmal. In einem nationalen Ligaspiel stammen beide Mannschaften aus
derselben Liga; die Ligastaerkedifferenz ist strukturell null.
Nachgemessen: von 2917 nationalen Trainingszeilen verbinden NULL zwei
verschiedene Herkunftsligen. In frueheren CL-Partien sind es 100
Prozent (Fold 1) beziehungsweise 98 Prozent (Fold 2).

Der Effekt ist also genau dort identifizierbar, wo er geschaetzt wird,
und nachweislich nirgends sonst.

GENAU EIN KANDIDAT
------------------
C15 bewertet einen einzigen Challenger gegen zwei unveraenderte
Kontrollen. Mehrere Ligastaerkevarianten waeren verstecktes
Modellshopping, und die beste davon auszuwaehlen hiesse, den
Testbestand zur Modellwahl zu benutzen.

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

CONTRACT_VERSION = "v2-c15.1"

CONTRACT_PATH = "data/ml/c15_league_strength_contract_2023-2025.json"
ARTIFACT_PATH = "data/ml/c15_league_strength_evaluation_2023-2025.json"


class ContractViolation(RuntimeError):
    """Ein Ergebnis gehoert nicht zu diesem Vertrag. Nie stillschweigend."""


VERDICT_ACCEPTED = "accepted"
VERDICT_PROVISIONAL_SHADOW = "provisional_shadow"
VERDICT_REJECTED = "rejected"
VERDICT_NOT_EVALUABLE = "not_evaluable"

VERDICTS = (VERDICT_ACCEPTED, VERDICT_PROVISIONAL_SHADOW,
            VERDICT_REJECTED, VERDICT_NOT_EVALUABLE)

ACCEPTANCE_CLASS_DEVELOPMENT = "accepted_development_evidence"

#: Unveraendert aus V2-C2B/C8/C14.
SEGMENT_MIN_SIZE = 30

TOP5_LEAGUES = ("BL1", "PL", "PD", "SA", "FL1")

#: Ab wie vielen frueheren CL-Beobachtungen eine Liga als gut belegt
#: gilt. Vorab festgelegt, damit das Segment "duenne Evidenz" nicht
#: nachtraeglich passend geschnitten werden kann.
THIN_EVIDENCE_MAX = 20


def _kanonisch(wert):
    return json.dumps(wert, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def _stabil(block):
    return hashlib.sha256(_kanonisch(block).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Das Merkmalsschema des Kandidaten
# ---------------------------------------------------------------------------

def model_schema():
    """
    Das vollstaendige Schema des C15-Kandidaten.

    Es deckt beide Stufen ab. Nur die Spaltenliste zu binden waere
    hier gefaehrlich: Sie ist mit der des C14-Kandidaten identisch, und
    ein Bundle der einen Stufe wuerde sonst zum anderen Modell passen,
    obwohl es etwas voellig anderes berechnet.
    """
    return {
        "schema_version": CONTRACT_VERSION,
        "candidate": fg.C15_CANDIDATE,
        "base_columns": sorted(fg.columns_for(fg.C15_CANDIDATE)),
        "base_column_count": len(fg.columns_for(fg.C15_CANDIDATE)),
        "stages": [
            {"stage": 1, "name": "national_base",
             "model_class": "poisson_offset_correction_linear",
             "trained_on": "nationale Ligazeilen der Trainingssaisons",
             "alpha_space": list(_alpha_kandidaten())},
            {"stage": 2, "name": "league_strength",
             "model_class": "poisson_ridge_league_offsets",
             "trained_on": ("ausschliesslich CL-Partien frueherer "
                            "Saisons"),
             "parameters": "je Liga ein offensiver und ein defensiver "
                           "log-Multiplikator",
             "alpha_space": list(_alpha_kandidaten()),
             "factor_bounds": [ls.FACTOR_MIN, ls.FACTOR_MAX],
             "min_observations": ls.MIN_OBSERVATIONS},
        ],
    }


def schema_fingerprint():
    """Der Fingerabdruck des C15-Modellschemas, getrennt von C9."""
    return _stabil(model_schema())


def _alpha_kandidaten():
    from src.ml import model as mdl

    return tuple(mdl.ALPHA_CANDIDATES)


# ---------------------------------------------------------------------------
# Der Vertrag
# ---------------------------------------------------------------------------

def evaluation_contract():
    """
    Der vollstaendige Vertrag - ohne eine einzige gemessene Zahl.

    Erwartungswerte aus C13/C14 stehen als ERWARTUNG darin und werden
    bei der Messung geprueft, nicht stillschweigend angepasst.
    """
    from src.features import prediction_cutoff as pc
    from src.ml import c13_contract as c13
    from src.ml import c14_reevaluation as c14
    from src.ml import early_v2 as e9
    from src.ml import model_registry as mr

    return {
        "version": CONTRACT_VERSION,
        "purpose": (
            "Misst, ob eine zweite Modellstufe fuer die Staerke der "
            "Herkunftsliga den in V2-C14 belegten Segmentschaden "
            "behebt, ohne den Gesamtnutzen zu verlieren."),

        "exactly_one_candidate": (
            "C15 bewertet genau einen Challenger. Mehrere "
            "Ligastaerkevarianten waeren verstecktes Modellshopping, "
            "und die beste davon zu waehlen hiesse, den Testbestand "
            "zur Modellwahl zu benutzen."),

        # -- Kandidat und Kontrollen ---------------------------------------
        "candidate": {
            "name": fg.C15_CANDIDATE,
            "schema": model_schema(),
            "schema_fingerprint": schema_fingerprint(),
        },
        "controls": {
            "v0": {"name": "v0_baseline",
                   "what": "die bestehende Poisson-Baseline aus Profil "
                           "und Ligaschnitt, kein Modell"},
            "c14_v2": {"name": ce.CANDIDATE,
                       "what": "der unveraenderte C14-Ansatz mit "
                               "denselben 16 Merkmalen auf den "
                               "reparierten C13-Profilen",
                       "expected_delta_log_loss": -0.011628,
                       "expected_folds": [-0.025747, 0.002999]},
            "fairness": ("Alle drei bewerten identische Match-IDs, "
                         "identische Zielwerte, identische Folds und "
                         "identische Ausschluesse."),
        },

        # -- Die Ligastaerke ------------------------------------------------
        "league_strength": {
            "form": ("lambda_heim' = lambda_heim * exp(a[liga_heim] + "
                     "d[liga_gast]); lambda_gast' = lambda_gast * "
                     "exp(a[liga_gast] + d[liga_heim])"),
            "estimator": ("PoissonRegressor ohne Achsenabschnitt ueber "
                          "den Offset-Umweg - dieselbe Technik wie das "
                          "Basismodell, nicht eine neue Modellklasse"),
            "observations": ("je Partie zwei, eine je Seite; der "
                             "Heimvorteil steckt bereits in Stufe eins "
                             "und wird nicht doppelt modelliert"),
            "training_source": ("ausschliesslich CL-Partien aus Saisons, "
                                "die vollstaendig vor der Testsaison "
                                "liegen"),
            "league_provenance": ("Vereins-ID zu Ligacode ueber den "
                                  "validierten C13-Crosswalk; rohe IDs "
                                  "werden nie providerueberschreitend "
                                  "gleichgesetzt"),
            "identifiability": {
                "claim": ("Der Effekt ist aus frueheren CL-Partien "
                          "identifizierbar und aus nationalen Spielen "
                          "nachweislich nicht."),
                "national_rows_with_two_leagues_expected": 0,
                "cl_rows_with_two_leagues_expected_share": 0.98,
                "rank_deficiency_expected": 1,
                "why_rank_deficiency": (
                    "Ohne Achsenabschnitt ist die Loesung nur bis auf "
                    "eine Konstante bestimmt: Man koennte auf alle a "
                    "einen Wert addieren und ihn von allen d abziehen. "
                    "Die Ridge-Strafe waehlt darunter die Loesung "
                    "kleinster Norm."),
            },
            "cold_start": {
                "rule": ("Eine Liga ohne fruehere CL-Historie bekommt "
                         "den Wert 0 und damit den Faktor 1."),
                "neutral": True,
                "never_a_bonus": ("Unbekannt heisst unbekannt. Eine "
                                  "unbekannte Liga darf keinen Vorteil "
                                  "erhalten."),
            },
            "regularisation": {
                "type": "Ridge auf beiden Ligaparametersaetzen",
                "role": ("nicht nur Vorsicht, sondern Teil der "
                         "Definition: Sie loest die Nichteindeutigkeit "
                         "auf."),
                "alpha_space": list(_alpha_kandidaten()),
                "selection": (
                    "zeitliche innere Teilung AUSSCHLIESSLICH innerhalb "
                    "der Trainingshistorie: bei einer Trainingssaison "
                    "Teilung am mittleren Spieldatum, bei mehreren "
                    "Teilung nach Saison. Dieselbe Regel wie im "
                    "Basismodell."),
                "criterion": "Poissondevianz auf dem spaeteren Teil",
                "tie_break": "groesseres Alpha gewinnt",
                "never": ["Wahl anhand des Testfolds",
                          "grosse Rastersuche",
                          "nachtraegliche Wahl der besten Darstellung",
                          "manuelles Nachjustieren einzelner Ligen"],
            },
            "bounds": {"factor_min": ls.FACTOR_MIN,
                       "factor_max": ls.FACTOR_MAX,
                       "why": ("Enger als die Grenzen des Basismodells, "
                               "weil hier eine ZWEITE Korrektur auf eine "
                               "bereits korrigierte Vorhersage trifft.")},
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
            "note": ("Der C11-Wert ist der unveraenderliche "
                     "Vertragsteil, NICHT der Registryzustand."),
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
            "no_double_counting": ("Die Bestaende ueberlappen und werden "
                                   "nie addiert."),
        },

        "folds": {
            "standard": [dict(f) for f in ce.OUTER_FOLDS],
            "context": [dict(f) for f in ce.CONTEXT_FOLDS],
            "chronological_only": True,
            "league_strength_history": (
                "je Fold ausschliesslich CL-Partien der "
                "Trainingssaisons"),
            "preprocessing": "foldlokal, nie auf dem Testfold",
            "calibration": "foldlokal, nie auf dem Testfold",
        },

        "metrics": {
            "primary": "log_loss",
            "primary_comparison": "C15 gegen V0",
            "additional_comparison": "C15 gegen C14-V2",
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
                      "source": "unveraendert aus V2-C2B/C12/C14"},

        "segments": {
            "min_size": SEGMENT_MIN_SIZE,
            "min_size_source": "V2-C2B/C8, nicht fuer C15 neu gewaehlt",
            "thin_evidence_max": THIN_EVIDENCE_MAX,
            "mandatory": [
                "season:*", "fold:*", "phase:league", "phase:knockout",
                "stage:*", "leg:first", "leg:second", "leg:single",
                "leg:final",
                "origin:top5_vs_top5", "origin:top5_vs_other",
                "origin:other_vs_top5", "origin:other_vs_other",
                "home_origin_league:*", "away_origin_league:*",
                "league_evidence:cold_start",
                "league_evidence:thin", "league_evidence:strong",
                "home_profile_depth:*", "away_profile_depth:*",
                "min_profile_depth:*", "both_profile_depth:>=20",
                "match_balance:*", "outcome:*",
                "home_data_quality:*",
            ],
            "directed_and_symmetric": True,
            "overlap_rule": ("Segmente mit identischer Zeilenmenge "
                             "bilden eine Gruppe und zaehlen als EIN "
                             "Befund."),
            "explicitly_watched": ["origin:top5_vs_other",
                                   "home_origin_league:PL"],
        },

        "missing_data": {
            "rule": ("Fehlende Merkmalswerte bleiben fehlend und werden "
                     "foldlokal vom Medianimputer gefuellt."),
            "identical_rows": ("V0, C14 und C15 bewerten dieselben "
                               "Partien mit denselben Zielwerten."),
            "exclusions_are_rule_based": (
                "Alle Ausschluesse folgen der C13-Eligibility und "
                "stehen vor der Messung fest."),
        },

        "calibration": {
            "allowed": ["keine zusaetzliche Kalibrierung",
                        "bestehende Konvention"],
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
            "provenance": ("saemtlich aus V2-C2B, V2-C8, V2-C12 und "
                           "V2-C14 importiert, nicht fuer C15 neu "
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
                "Messung technisch nicht reproduzierbar"],
        },

        "acceptance_class_if_accepted": ACCEPTANCE_CLASS_DEVELOPMENT,

        "no_untouched_holdout": {
            "true": True,
            "already_used_for": ("C2 bis C14, einschliesslich der "
                                 "C14-Diagnose, die zu dieser "
                                 "Modellform gefuehrt hat"),
            "consequence": (
                "Die Ligastaerkeform wurde aus einer C14-Diagnose auf "
                "denselben Saisons abgeleitet. Das ist "
                "Entwicklungsevidenz und ausdruecklich keine "
                "unabhaengige Bestaetigung. Ein Accepted traegt "
                "deshalb die Klasse "
                "accepted_development_evidence."),
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
# Atomares Schreiben
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
        "artifact": "v2-c15 league strength contract",
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
# Die zeitliche Historie der Ligastaerke
# ---------------------------------------------------------------------------

def league_history(zeilen, train_seasons):
    """
    Die CL-Partien, aus denen die Ligastaerke eines Folds entsteht.

    AUSSCHLIESSLICH Trainingssaisons. Der Selektor ist derselbe wie im
    Kontextvertrag, damit K.-o.-Partien nicht stillschweigend
    herausfallen - sie tragen `knockout_eligible` statt
    `evaluation_eligible`.
    """
    return ce.context_rows(zeilen, list(train_seasons))


def _innere_teilung(historie, train_seasons):
    """
    Die zeitliche innere Teilung der Ligastaerkehistorie.

    Dieselbe Regel wie `evaluate.inner_split`, und aus demselben
    Grund: Bei einer Trainingssaison wird am mittleren Spieldatum
    geteilt, bei mehreren nach Saison. Der aeussere Testfold wird nie
    gesehen.
    """
    if not historie:
        return [], [], {"strategy": "leer"}

    if len(train_seasons) > 1:
        grenze = max(train_seasons)
        frueh = [z for z in historie if z["season"] < grenze]
        spaet = [z for z in historie if z["season"] == grenze]
        if frueh and spaet:
            return frueh, spaet, {
                "strategy": "nach Saison",
                "fit_seasons": sorted({z["season"] for z in frueh}),
                "validation_seasons": [grenze]}

    daten = sorted(z["date"] for z in historie)
    mitte = daten[len(daten) // 2]
    frueh = [z for z in historie if z["date"] < mitte]
    spaet = [z for z in historie if z["date"] >= mitte]
    return frueh, spaet, {
        "strategy": "am mittleren Spieldatum",
        "split_date": mitte,
        "fit_rows": len(frueh),
        "validation_rows": len(spaet)}


# ---------------------------------------------------------------------------
# Ein Fold, drei Kandidaten
# ---------------------------------------------------------------------------

def evaluate_fold(zeilen, fold, ligakarte, train_rows=None,
                  test_rows=None):
    """
    Ein aeusserer Fold mit V0, C14-V2 und C15 auf DENSELBEN Zeilen.

    Bewusst eine gemeinsame Funktion statt dreier Laeufe: Sobald die
    drei ihre Testzeilen getrennt bestimmen, misst man auch
    Unterschiede, die nur aus dem Messaufbau stammen.

    Stufe eins ist Wort fuer Wort die bestehende C14-Rechnung. Stufe
    zwei setzt darauf auf.
    """
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

    # -- Stufe zwei: die Ligastaerke, nur aus frueheren CL-Partien -------
    historie = league_history(zeilen, fold["train_seasons"])
    h_frueh, h_spaet, h_innen = _innere_teilung(historie,
                                                fold["train_seasons"])

    alpha, alpha_protokoll = None, {"strategy": "keine Historie"}
    if h_frueh and h_spaet:
        alpha, alpha_protokoll = ls.select_alpha(
            h_frueh, basis_lambdas(h_frueh), h_spaet,
            basis_lambdas(h_spaet), ligakarte, mdl.ALPHA_CANDIDATES)
    if alpha is None:
        # Fail-closed: Ohne belastbare innere Wahl bleibt die Stufe
        # neutral, statt eine Zahl zu raten.
        alpha = max(mdl.ALPHA_CANDIDATES)
        alpha_protokoll = dict(alpha_protokoll,
                               fallback="staerkste Regularisierung, "
                                        "weil keine innere Wahl moeglich")

    staerke = ls.estimate(historie, basis_lambdas(historie), ligakarte,
                          alpha)

    # -- Die drei Vorhersagen auf identischen Testzeilen -----------------
    ausgaenge = [z["outcome"] for z in test]
    v0_p = ev.probabilities_for(mdl.baseline_lambdas(test))

    c14_lambdas = basis_lambdas(test)
    c14_p = ev.probabilities_for(c14_lambdas)

    c15_lambdas, klammern = ls.apply_factors(staerke, test, c14_lambdas,
                                             ligakarte)
    c15_p = ev.probabilities_for(c15_lambdas)

    ce.assert_paired(test, v0_p, c14_p)
    ce.assert_paired(test, v0_p, c15_p)

    v0 = ev.summarise(v0_p, ausgaenge)
    c14 = ev.summarise(c14_p, ausgaenge)
    c15 = ev.summarise(c15_p, ausgaenge)

    ergebnis = {
        "fold": fold["name"],
        "train_seasons": list(fold["train_seasons"]),
        "test_season": fold["test_season"],
        "train_rows": len(training),
        "test_rows": len(test),
        "inner_split": innen,
        "base_selection": wahl,
        "base_candidate": kandidat,
        "league_history_rows": len(historie),
        "league_inner_split": h_innen,
        "league_alpha_selection": alpha_protokoll,
        "league_alpha": alpha,
        "league_strength": staerke.summary(),
        "league_clamps": klammern,
        "v0": v0,
        "c14": c14,
        "c15": c15,
        "delta_log_loss": c15["log_loss"] - v0["log_loss"],
        "delta_brier": c15["brier"] - v0["brier"],
        "delta_rps": c15["rps"] - v0["rps"],
        "delta_vs_c14_log_loss": c15["log_loss"] - c14["log_loss"],
        "c14_delta_log_loss": c14["log_loss"] - v0["log_loss"],
        "mean_probabilities": {
            "v0": _mittel(v0_p), "c14": _mittel(c14_p),
            "c15": _mittel(c15_p),
            "observed": _beobachtet(ausgaenge)},
        "extreme_probabilities": {
            "v0": _extreme(v0_p), "c14": _extreme(c14_p),
            "c15": _extreme(c15_p)},
        "mean_lambdas": {
            "c14": _mittlere_lambdas(c14_lambdas),
            "c15": _mittlere_lambdas(c15_lambdas)},
        "_internal": {
            "rows": test,
            "v0_losses": ev.per_match_losses(v0_p, ausgaenge),
            "c14_losses": ev.per_match_losses(c14_p, ausgaenge),
            "c15_losses": ev.per_match_losses(c15_p, ausgaenge),
            "v0_calibration": ev.calibration_sums(v0_p, ausgaenge),
            "c15_calibration": ev.calibration_sums(c15_p, ausgaenge),
            "staerke": staerke,
        },
    }
    return ergebnis


def _mittel(wahrscheinlichkeiten):
    if not wahrscheinlichkeiten:
        return None
    n = len(wahrscheinlichkeiten)
    return {name: round(sum(p[i] for p in wahrscheinlichkeiten) / n, 5)
            for i, name in enumerate(("home", "draw", "away"))}


def _beobachtet(ausgaenge):
    if not ausgaenge:
        return None
    n = len(ausgaenge)
    return {name: round(sum(1 for a in ausgaenge if a == i) / n, 5)
            for i, name in enumerate(("home", "draw", "away"))}


def _extreme(wahrscheinlichkeiten, grenze=0.9):
    """
    Wie oft wird das Modell sehr sicher?

    Eine Vorhersage nahe 1 ist bei 283 Partien ein Risiko: Liegt sie
    daneben, kostet sie im LogLoss unverhaeltnismaessig viel.
    """
    if not wahrscheinlichkeiten:
        return None
    hoch = sum(1 for p in wahrscheinlichkeiten if max(p) >= grenze)
    return {"threshold": grenze, "count": hoch,
            "share": round(hoch / len(wahrscheinlichkeiten), 5),
            "max_probability": round(
                max(max(p) for p in wahrscheinlichkeiten), 5)}


def _mittlere_lambdas(lambdas):
    if not lambdas:
        return None
    n = len(lambdas)
    return {"home": round(sum(l[0] for l in lambdas) / n, 5),
            "away": round(sum(l[1] for l in lambdas) / n, 5)}


# ---------------------------------------------------------------------------
# Segmente
# ---------------------------------------------------------------------------

def _tiefenklasse(tiefe):
    if not isinstance(tiefe, (int, float)):
        return "unknown"
    if tiefe < 6:
        return "<6"
    if tiefe < 20:
        return "6-19"
    return ">=20"


def _evidenzklasse(staerke, liga):
    """
    Wie gut ist die Ligastaerke dieser Liga belegt?

    Die Grenze steht vorab im Vertrag. Nachtraeglich geschnitten waere
    sie das bequemste Segment der Welt.
    """
    if staerke is None or liga is None or staerke.is_cold_start(liga):
        return "cold_start"
    je_liga = (staerke.diagnose.get("observations_per_league") or {})
    n = je_liga.get(liga, 0)
    return "thin" if n <= THIN_EVIDENCE_MAX else "strong"


def _segment_keys(zeile, ligakarte=None, staerke=None, fold=None):
    """
    Alle Pflichtsegmente einer Partie - gerichtet UND symmetrisch.

    Unveraendert aus V2-C14 uebernommen und um die Segmente ergaenzt,
    die erst mit der Ligastaerke entstehen.
    """
    ligakarte = ligakarte or {}
    schluessel = []

    schluessel.append("season:%s" % zeile.get("season"))
    if fold:
        schluessel.append("fold:%s" % fold)
    schluessel.append("phase:knockout" if zeile.get("is_knockout")
                      else "phase:league")
    stufe = zeile.get("stage")
    if stufe:
        schluessel.append("stage:%s" % stufe)
    if zeile.get("is_final"):
        schluessel.append("leg:final")
    elif zeile.get("is_first_leg"):
        schluessel.append("leg:first")
    elif zeile.get("is_second_leg"):
        schluessel.append("leg:second")
    else:
        schluessel.append("leg:single")
    if zeile.get("neutral_venue"):
        schluessel.append("venue:neutral")

    heim_q = zeile.get("home_profile_source")
    gast_q = zeile.get("away_profile_source")
    if heim_q:
        schluessel.append("home_profile_source:%s" % heim_q)
    if gast_q:
        schluessel.append("away_profile_source:%s" % gast_q)

    heim_t = zeile.get("home_profile_matches")
    gast_t = zeile.get("away_profile_matches")
    schluessel.append("home_profile_depth:%s" % _tiefenklasse(heim_t))
    schluessel.append("away_profile_depth:%s" % _tiefenklasse(gast_t))
    if isinstance(heim_t, (int, float)) and isinstance(gast_t, (int, float)):
        schluessel.append("min_profile_depth:%s"
                          % _tiefenklasse(min(heim_t, gast_t)))
        if heim_t >= 20 and gast_t >= 20:
            schluessel.append("both_profile_depth:>=20")

    heim_l = ligakarte.get(zeile.get("home_id"))
    gast_l = ligakarte.get(zeile.get("away_id"))
    if heim_l and gast_l:
        schluessel.append("origin:%s_vs_%s"
                          % ("top5" if heim_l in TOP5_LEAGUES else "other",
                             "top5" if gast_l in TOP5_LEAGUES else "other"))
    if heim_l:
        schluessel.append("home_origin_league:%s" % heim_l)
    if gast_l:
        schluessel.append("away_origin_league:%s" % gast_l)

    # -- Neu in C15: wie gut ist die Ligastaerke belegt? -----------------
    klassen = {_evidenzklasse(staerke, heim_l),
               _evidenzklasse(staerke, gast_l)}
    if "cold_start" in klassen:
        schluessel.append("league_evidence:cold_start")
    elif "thin" in klassen:
        schluessel.append("league_evidence:thin")
    else:
        schluessel.append("league_evidence:strong")

    ergebnis = zeile.get("outcome")
    schluessel.append({0: "outcome:home", 1: "outcome:draw",
                       2: "outcome:away"}.get(ergebnis, "outcome:unknown"))

    lh = zeile.get("baseline_lambda_home")
    la = zeile.get("baseline_lambda_away")
    if isinstance(lh, (int, float)) and isinstance(la, (int, float)):
        spanne = abs(lh - la)
        schluessel.append("match_balance:%s"
                          % ("balanced" if spanne < 0.35
                             else "clear" if spanne < 0.9 else "lopsided"))

    qualitaet = zeile.get("home_data_quality")
    if qualitaet:
        schluessel.append("home_data_quality:%s" % qualitaet)

    return schluessel


def _segmente(eintraege, basis_verluste, ml_verluste):
    """
    Die Segmentauswertung mit Ueberlappungserkennung.

    eintraege: Liste von (zeile, schluesselliste).
    """
    eimer = {}
    for i, (_, schluessel) in enumerate(eintraege):
        for name in schluessel:
            eimer.setdefault(name, []).append(i)

    nach_menge = {}
    for name, indizes in eimer.items():
        nach_menge.setdefault(frozenset(indizes), []).append(name)
    gruppe_von = {}
    for namen in nach_menge.values():
        fuehrend = sorted(namen)[0]
        for name in namen:
            gruppe_von[name] = fuehrend

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
            "overlap_group": gruppe_von[name],
            "is_group_representative": gruppe_von[name] == name,
        }
    return heraus


def distinct_damage(segmente):
    """Schwer verschlechterte Segmente ohne Doppelzaehlung."""
    gruppen = {}
    for name, block in segmente.items():
        if block.get("severely_worse"):
            gruppen.setdefault(block["overlap_group"], []).append(name)
    return sorted(gruppen)


# ---------------------------------------------------------------------------
# Konzentration
# ---------------------------------------------------------------------------

def concentration(zeilen, basis_verluste, ml_verluste, ligakarte=None,
                  top_n=5):
    """
    Traegt eine Handvoll Vereine oder Ligen den gesamten Vorteil?

    AUSDRUECKLICH KEIN GATE. Fuer diese Frage existiert in den
    freigegebenen Vertraegen keine Schwelle, und eine hier erfundene
    waere ein nachtraeglich passend gemachtes Gate.
    """
    import collections

    je_verein = collections.defaultdict(float)
    partien = collections.Counter()
    je_liga = collections.defaultdict(float)

    for i, zeile in enumerate(zeilen):
        beitrag = ml_verluste[i] - basis_verluste[i]
        for feld in ("home_id", "away_id"):
            tid = zeile.get(feld)
            if tid is None:
                continue
            je_verein[tid] += beitrag / 2.0
            partien[tid] += 1
            if ligakarte:
                liga = ligakarte.get(tid)
                if liga:
                    je_liga[liga] += beitrag / 2.0

    gesamt = sum(ml_verluste) - sum(basis_verluste)
    n = len(zeilen)
    sortiert = sorted(je_verein.items(), key=lambda kv: kv[1])
    besten = sortiert[:top_n]
    ohne_beste = gesamt - sum(b for _, b in besten)

    def anteil(betrag):
        return None if gesamt == 0 else round(betrag / gesamt, 4)

    lolo = []
    for tid in list(je_verein):
        behalten = [i for i, z in enumerate(zeilen)
                    if z.get("home_id") != tid and z.get("away_id") != tid]
        if len(behalten) < ce.MIN_RELIABLE_N:
            continue
        d = (sum(ml_verluste[i] - basis_verluste[i] for i in behalten)
             / len(behalten))
        lolo.append((tid, d, len(behalten)))
    lolo.sort(key=lambda t: t[1], reverse=True)

    liga_lolo = []
    if ligakarte:
        # Klammern, nicht Kosmetik: Ohne sie band das "- {None}" nur an
        # die zweite Menge, und eine unbekannte Liga der HEIMseite
        # blieb drin. Solange die Zuordnung jeden Verein kannte, fiel
        # das nicht auf; mit einer zeitlich begrenzten Karte (V2-C19)
        # steht dort None, und sorted() bricht ab, bevor das
        # vorhandene continue darunter ueberhaupt greifen kann.
        for liga in sorted(({ligakarte.get(z.get("home_id")) for z in zeilen}
                            | {ligakarte.get(z.get("away_id"))
                               for z in zeilen}) - {None}):
            if liga is None:                          # pragma: no cover
                continue
            behalten = [i for i, z in enumerate(zeilen)
                        if ligakarte.get(z.get("home_id")) != liga
                        and ligakarte.get(z.get("away_id")) != liga]
            if len(behalten) < ce.MIN_RELIABLE_N:
                continue
            d = (sum(ml_verluste[i] - basis_verluste[i] for i in behalten)
                 / len(behalten))
            liga_lolo.append({"league": liga,
                              "mean_delta_without": round(d, 5),
                              "n": len(behalten)})
    liga_lolo.sort(key=lambda e: e["mean_delta_without"], reverse=True)

    besser = sum(1 for i in range(n) if ml_verluste[i] < basis_verluste[i])

    return {
        "total_delta_sum": round(gesamt, 5),
        "mean_delta": round(gesamt / n, 5) if n else None,
        "matches_with_lower_loss": besser,
        "share_matches_with_lower_loss": round(besser / n, 4) if n else None,
        "top_contributors": [
            {"team_id": tid, "delta_sum": round(betrag, 5),
             "share_of_total": anteil(betrag), "matches": partien[tid]}
            for tid, betrag in besten],
        "top_n_share": anteil(sum(b for _, b in besten)),
        "mean_delta_without_top_n": round(ohne_beste / n, 5) if n else None,
        "direction_holds_without_top_n": (
            None if gesamt == 0 else (ohne_beste < 0) == (gesamt < 0)),
        "leave_one_team_out_worst": [
            {"team_id": tid, "mean_delta_without": round(d, 5), "n": m}
            for tid, d, m in lolo[:5]],
        "leave_one_team_out_direction_holds": (
            all(d < 0 for _, d, _ in lolo) if lolo else None),
        "leave_one_league_out_worst": liga_lolo[:5],
        "leave_one_league_out_direction_holds": (
            all(e["mean_delta_without"] < 0 for e in liga_lolo)
            if liga_lolo else None),
        "league_contributions": {
            liga: round(wert, 5)
            for liga, wert in sorted(je_liga.items(),
                                     key=lambda kv: kv[1])[:8]},
        "is_a_gate": False,
        "why_not_a_gate": (
            "Fuer die Konzentration existiert in den freigegebenen "
            "Vertraegen keine numerische Schwelle. Eine hier erfundene "
            "waere ein nachtraeglich passend gemachtes Gate."),
    }


def _reliability(summen):
    """Die Zuverlaessigkeitskurve aus den bereits gebildeten Binsummen."""
    heraus = []
    for name, werte in sorted((summen or {}).items()):
        try:
            summe, treffer, anzahl = werte[0], werte[1], werte[2]
        except (TypeError, IndexError, KeyError):        # pragma: no cover
            continue
        if not anzahl:
            continue
        heraus.append({
            "bin": name, "n": anzahl,
            "mean_predicted": round(summe / anzahl, 5),
            "observed_rate": round(treffer / anzahl, 5),
            "gap": round(treffer / anzahl - summe / anzahl, 5),
        })
    return heraus


# ---------------------------------------------------------------------------
# Die Messung
# ---------------------------------------------------------------------------

def _aggregiere(folds, schluessel_basis, schluessel_ml):
    """
    Zwei Kandidaten ueber beide Folds zusammenfassen.

    Der gepaarte Bootstrap laeuft ueber die Einzelverluste beider
    Folds gemeinsam - dieselbe Methode und derselbe Seed wie seit
    V2-C2B.
    """
    basis_v, ml_v = [], []
    n = 0
    for fold in folds:
        if "error" in fold:
            continue
        intern = fold["_internal"]
        basis_v.extend(intern[schluessel_basis]["log_loss"])
        ml_v.extend(intern[schluessel_ml]["log_loss"])
        n += fold["test_rows"]

    if not basis_v:
        return {"n": 0}

    basis_ll = sum(basis_v) / len(basis_v)
    ml_ll = sum(ml_v) / len(ml_v)
    boot = ev.paired_bootstrap(basis_v, ml_v)

    return {
        "n": n,
        "baseline_log_loss": round(basis_ll, 6),
        "ml_log_loss": round(ml_ll, 6),
        "delta_log_loss": ml_ll - basis_ll,
        "bootstrap": {"log_loss": boot},
    }


def _messe_bestand(zeilen, name, folds_def, ligakarte, train_rows,
                   test_rows):
    """Ein Bestand, alle drei Kandidaten, dieselbe Strecke."""
    folds = [evaluate_fold(zeilen, fold, ligakarte,
                           train_rows=train_rows, test_rows=test_rows)
             for fold in folds_def]

    gute = [f for f in folds if "error" not in f]
    if not gute:
        return {"inventory": name, "folds": folds, "error": "kein Fold"}

    # Einzelverluste und Zeilen einsammeln, bevor _internal faellt.
    test_zeilen, v0_v, c14_v, c15_v = [], [], [], []
    v0_kal, c15_kal = [], []
    eintraege = []
    for fold in gute:
        intern = fold["_internal"]
        staerke = intern["staerke"]
        for zeile in intern["rows"]:
            test_zeilen.append(zeile)
            eintraege.append((zeile, _segment_keys(
                zeile, ligakarte, staerke, fold["fold"])))
        v0_v.extend(intern["v0_losses"]["log_loss"])
        c14_v.extend(intern["c14_losses"]["log_loss"])
        c15_v.extend(intern["c15_losses"]["log_loss"])
        v0_kal.append(intern["v0_calibration"])
        c15_kal.append(intern["c15_calibration"])

    def summe(werte):
        return sum(werte) / len(werte) if werte else None

    gegen_v0 = _aggregiere(gute, "v0_losses", "c15_losses")
    gegen_c14 = _aggregiere(gute, "c14_losses", "c15_losses")
    c14_gegen_v0 = _aggregiere(gute, "v0_losses", "c14_losses")

    # Sekundaermetriken gewichtet ueber die Folds.
    def gewichtet(pfad):
        gesamt, zaehler = 0.0, 0
        for fold in gute:
            wert = fold
            for teil in pfad:
                wert = wert[teil]
            gesamt += wert * fold["test_rows"]
            zaehler += fold["test_rows"]
        return gesamt / zaehler if zaehler else None

    aggregat = dict(gegen_v0)
    aggregat.update({
        "v0": {k: gewichtet(["v0", k])
               for k in ("log_loss", "brier", "rps",
                         "calibration_error",
                         "accuracy_supplementary")},
        "c14": {k: gewichtet(["c14", k])
                for k in ("log_loss", "brier", "rps",
                          "calibration_error",
                         "accuracy_supplementary")},
        "c15": {k: gewichtet(["c15", k])
                for k in ("log_loss", "brier", "rps",
                          "calibration_error",
                         "accuracy_supplementary")},
    })
    aggregat["delta_brier"] = (aggregat["c15"]["brier"]
                               - aggregat["v0"]["brier"])
    aggregat["delta_rps"] = aggregat["c15"]["rps"] - aggregat["v0"]["rps"]
    aggregat["baseline"] = {
        "log_loss": aggregat["v0"]["log_loss"],
        "calibration_error": aggregat["v0"]["calibration_error"]}
    aggregat["ml"] = {
        "log_loss": aggregat["c15"]["log_loss"],
        "calibration_error": aggregat["c15"]["calibration_error"]}
    aggregat["c15_vs_c14"] = gegen_c14
    aggregat["c14_vs_v0"] = c14_gegen_v0

    segmente = _segmente(eintraege, v0_v, c15_v)
    segmente_gegen_c14 = _segmente(eintraege, c14_v, c15_v)

    for fold in folds:
        fold.pop("_internal", None)

    return {
        "inventory": name,
        "folds": folds,
        "aggregate": aggregat,
        "segments": segmente,
        "segments_vs_c14": segmente_gegen_c14,
        "distinct_damage": distinct_damage(segmente),
        "concentration": concentration(test_zeilen, v0_v, c15_v,
                                       ligakarte),
        "reliability": {
            "v0": _reliability(ev.merge_calibration_sums(v0_kal)),
            "c15": _reliability(ev.merge_calibration_sums(c15_kal))},
        "rows_evaluated": len(test_zeilen),
        "distinct_row_ids": len({z["row_id"] for z in test_zeilen}),
    }


def run_measurement(zeilen, ligakarte=None):
    """Standard- und Kontextbestand, alle drei Kandidaten."""
    import collections

    from src.ml import c14_reevaluation as c14

    ligakarte = ligakarte or c14.team_league_map()
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
        "candidate": fg.C15_CANDIDATE,
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
    """Unveraendert aus V2-C12/C14."""
    summe = sum(fold_deltas)
    if not fold_deltas or summe >= 0:
        return True
    return max(d / summe for d in fold_deltas) <= grenze


#: Fuer jede Bedingung ein Klartextgrund. Die Lehre aus C14: Dort
#: hatte `no_single_fold_carries_all` keine Meldung, und die
#: Gruendeliste war unvollstaendig. Jede Bedingung steht hier.
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

    Jede Schwelle stammt aus einem frueher freigegebenen Vertrag.
    Jede fehlgeschlagene Bedingung erscheint in `reasons`; das war in
    C14 nicht vollstaendig der Fall.
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

    #: JEDE fehlgeschlagene Bedingung bekommt einen Grund. Keine
    #: bestandene bekommt einen.
    messwerte = {
        "primary_better": "%+.6f" % delta,
        "all_folds_same_direction": ", ".join("%+.6f" % d
                                              for d in fold_deltas),
        "no_single_fold_carries_all": "Folddeltas %s" % (
            ", ".join("%+.6f" % d for d in fold_deltas)),
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
        "delta_vs_c14": (zusammen.get("c15_vs_c14") or {}).get(
            "delta_log_loss"),
        "n": n,
        "distinct_damage": schaden,
        "acceptance_class": (ACCEPTANCE_CLASS_DEVELOPMENT
                             if verdict == VERDICT_ACCEPTED else None),
        "holdout_caveat": (
            "Die Ligastaerkeform wurde aus einer C14-Diagnose auf "
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
    return _stabil(json.loads(json.dumps(ohne, sort_keys=True, default=str)))


def _identifizierbarkeitsnachweis(zeilen, ligakarte):
    """
    Der Beweis, dass die Ligastaerke dort lernbar ist, wo sie
    geschaetzt wird, und nirgends sonst.

    Er steht im Artefakt, weil er die zentrale Voraussetzung der
    ganzen Modellform ist. Waere er falsch, waere die zweite Stufe ein
    totes Merkmal.
    """
    nat = ce.league_rows(zeilen, [2023, 2024])
    nat_verschieden = sum(
        1 for z in nat
        if (ligakarte.get(z.get("home_id"))
            != ligakarte.get(z.get("away_id"))))

    je_fold = {}
    for fold in ce.OUTER_FOLDS:
        historie = league_history(zeilen, fold["train_seasons"])
        verschieden = ligen = 0
        namen = set()
        for zeile in historie:
            h = ligakarte.get(zeile.get("home_id"))
            a = ligakarte.get(zeile.get("away_id"))
            if not h or not a:
                continue
            namen.add(h)
            namen.add(a)
            if h != a:
                verschieden += 1
        ligen = len(namen)
        je_fold[fold["name"]] = {
            "history_matches": len(historie),
            "cross_league_matches": verschieden,
            "cross_league_share": (round(verschieden / len(historie), 4)
                                   if historie else None),
            "leagues": ligen,
            "parameters": 2 * ligen,
            "observations": 2 * len(historie),
        }

    return {
        "national_training_rows": len(nat),
        "national_rows_with_two_leagues": nat_verschieden,
        "learnable_from_national_matches": nat_verschieden > 0,
        "why_not": (
            "In einem nationalen Ligaspiel stammen beide Mannschaften "
            "aus derselben Liga. Die Ligastaerkedifferenz ist dort "
            "strukturell null, und ein Koeffizient darauf bekaeme kein "
            "Gewicht. Ein Ligastaerkemerkmal im nationalen Bestand "
            "waere ein totes Merkmal."),
        "per_fold_cl_history": je_fold,
        "conclusion": (
            "Der Effekt ist aus frueheren CL-Begegnungen "
            "identifizierbar und aus nationalen Spielen nachweislich "
            "nicht. Genau deshalb ist die Ligastaerke eine zweite "
            "Stufe und keine weitere Spalte."),
    }


def build_artifact(messung, urteil, zeilen=None, ligakarte=None):
    """Der C15-Nachweis - deterministisch und ohne Rohdaten."""
    import datetime as _dt

    from src.features import prediction_cutoff as pc
    from src.ml import c13_contract as c13
    from src.ml import c14_reevaluation as c14
    from src.ml import early_v2 as e9
    from src.ml import model_registry as mr

    vertrag = evaluation_contract()
    aktiv, grund = mr.active_entry()

    artefakt = {
        "artifact": "v2-c15 league strength evaluation",
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
        },

        "candidate": vertrag["candidate"],
        "controls": vertrag["controls"],

        "identifiability": (
            _identifizierbarkeitsnachweis(zeilen, ligakarte)
            if zeilen is not None and ligakarte is not None else None),

        "measurement": messung,
        "decision": urteil,
        "verdict": urteil["verdict"],

        "registry": {
            "active_model": (aktiv or {}).get("model_id"),
            "no_active_reason": grund,
            "changed_by_evaluation": False,
            "why": ("Die Evaluation entscheidet und aktiviert nicht. "
                    "Eine Aktivierung laeuft ausschliesslich ueber den "
                    "ausdruecklichen C11-Freigabeweg."),
        },

        "fingerprint_excludes": list(VOLATILE_FIELDS),

        "known_limits": [
            "Kein unangetasteter Holdout. Die Ligastaerkeform wurde aus "
            "einer C14-Diagnose auf denselben Saisons abgeleitet; das "
            "ist Entwicklungsevidenz und keine unabhaengige "
            "Bestaetigung.",
            "Zwei aeussere Folds sind wenig. Eine Foldabweichung kann "
            "eine Saisoneigenschaft sein.",
            "Fold 1 schaetzt die Ligastaerke aus nur 109 frueheren "
            "CL-Partien ueber 15 Ligen; mehrere davon sind duenn "
            "belegt und werden entsprechend stark regularisiert.",
            "Die Konzentrationsdiagnose hat keine numerische Schwelle "
            "und ist deshalb kein Gate.",
        ],
    }
    artefakt["result_fingerprint"] = result_fingerprint(artefakt)
    return artefakt


def write_artifact(messung, urteil, pfad=None, zeilen=None,
                   ligakarte=None):
    """Das Ergebnisartefakt atomar schreiben."""
    return _atomar_schreiben(
        pfad or ARTIFACT_PATH,
        json.dumps(build_artifact(messung, urteil, zeilen, ligakarte),
                   indent=2, ensure_ascii=False, default=str))
