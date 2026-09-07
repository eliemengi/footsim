"""
Modellklassen-Ablation (V2-C8).

DIE FRAGE
---------
    Verbessert eine BEGRENZTE, nachvollziehbare Erweiterung der
    bestehenden Poisson-Modellklasse Generalisierung und Kalibrierung
    gegenueber V1 - ohne Leakage, instabile Freiheitsgrade oder
    Scheingenauigkeit?

Nicht: "welches Modell gewinnt". C3 bis C7 haben gezeigt, dass mehr
Merkmale in derselben Klasse wenig bringen; C8 prueft, ob die KLASSE
das Problem war.

ZWEI VERTRAEGE, WEIL ES NICHT ANDERS GEHT
-----------------------------------------
Die C5-Kontextmerkmale sind im urspruenglichen Auswertungsvertrag
KONSTANT - gemessen: alle zwoelf, in Training und Test. Ein konstantes
Merkmal kann nicht interagieren; eine Interaktion darauf waere
ebenfalls konstant. Die Interaktionskandidaten laufen deshalb unter dem
Kontextvertrag aus V2-C5 (Training Ligen plus fruehere CL-Saisons, Test
CL regulaer plus K.-o.), die Transformationskandidaten unter dem
urspruenglichen.

Beide Verhaeltnisse werden AUSSCHLIESSLICH gegen ihren eigenen
V1-Kontrollarm gelesen. Zahlen ueber Vertragsgrenzen hinweg zu
vergleichen waere der bequemste Weg zu einem falschen Ergebnis - und
das Artefakt nennt zu jeder Zeile ihren Vertrag.

WAS HIER NICHT PASSIERT
-----------------------
Kein Baumverfahren, kein Boosting, keine automatische Merkmalssuche.
Bei 213 bis 303 Testpartien waere ein grosser Suchraum eine Uebung im
Ueberanpassen. Die Kandidatenmenge steht vorab fest und ist klein.
"""

import math
import time

from src.ml import cl_ablation as ca
from src.ml import cl_evaluate as ce
from src.ml import evaluate as ev
from src.ml import feature_groups as fg
from src.ml import model as mdl
from src.ml import model_class as mc

#: Fassung des C8-Ergebnisformats.
SCHEMA_VERSION = 1

#: Die Auswertungsvertraege.
CONTRACT_STANDARD = "standard"
CONTRACT_CONTEXT = "context"


# ---------------------------------------------------------------------------
# Merkmalsauswahl je Kandidat
# ---------------------------------------------------------------------------

#: Welche C7-Spalten wie transformiert werden.
#:
#: Gemessen im Trainingsbestand (Liga 2023+2024): arrivals_120d traegt
#: Schiefe +2,06, departures_120d +1,70, net_transfers_120d -1,16. Und
#: schwerer wiegend: arrivals_365d hat im Training Median 16, im Test
#: 32. Ein linear angepasster Koeffizient wird damit auf den doppelten
#: Wertebereich extrapoliert - genau das staucht log1p.
#:
#: Die Bewertungsspalten (…_rating) bleiben unveraendert: Sie liegen
#: zwischen 6,2 und 7,4, sind praktisch symmetrisch und haben in
#: Training und Test dieselbe Lage.
C7_COUNT_COLUMNS = ("arrivals_365d", "departures_365d",
                    "arrivals_120d", "departures_120d",
                    "loans_in_365d", "loans_out_365d")
C7_NET_COLUMNS = ("net_transfers_365d", "net_transfers_120d")
C7_RATING_COLUMNS = ("arrivals_mean_rating", "departures_mean_rating",
                     "arrivals_minus_departures_rating")


def c7_transform_spec():
    """
    {spalte: transformationsart} fuer die C7-Merkmale beider Seiten.

    Rohwert UND Transformation aufzunehmen waere ein redundanter
    Freiheitsgrad - log1p ist streng monoton, also traegt der Rohwert
    daneben keine zusaetzliche Ordnung. Die Spalte wird deshalb
    ERSETZT, nicht ergaenzt.
    """
    spec = {}
    for seite in ("home", "away"):
        for feld in C7_COUNT_COLUMNS:
            spec[f"{seite}_{feld}"] = mc.TRANSFORM_LOG1P
        for feld in C7_NET_COLUMNS:
            spec[f"{seite}_{feld}"] = mc.TRANSFORM_SIGNED_LOG1P
        for feld in C7_RATING_COLUMNS:
            spec[f"{seite}_{feld}"] = mc.TRANSFORM_IDENTITY
    return spec


def c7_winsor_columns():
    """Welche Spalten oben begrenzt werden - nur die Zaehlwerte."""
    spalten = set()
    for seite in ("home", "away"):
        for feld in C7_COUNT_COLUMNS + C7_NET_COLUMNS:
            spalten.add(f"{seite}_{feld}")
    return spalten


def c5_interaction_columns():
    """Die Namen der Interaktionsspalten."""
    return tuple(spec["name"] for spec in mc.INTERACTION_SPECS)


#: Im Bestand konstant - und deshalb ausgeschlossen.
#:
#: away_goals_rule_active traegt in JEDER Zeile dieses Bestands
#: denselben Wert: Die Auswaertstorregel wurde 2021 abgeschafft, der
#: Bestand beginnt 2023. Nachgemessen im Kontexttraining (n = 3128):
#: ein einziger distinkter Wert.
#:
#: Ein konstantes Merkmal ist kein harmloses Merkmal. Der
#: StandardScaler bildet es auf null ab, der Regressor traegt trotzdem
#: einen Koeffizienten dafuer - ein Freiheitsgrad ohne Information.
#: Das Merkmal bleibt im Datensatz und im C5-Vertrag; es geht nur
#: nicht in die C8-Kandidaten ein.
CONSTANT_IN_RANGE = {
    "away_goals_rule_active": ("2021 abgeschafft, Bestand ab 2023 - ein "
                               "distinkter Wert in Training und Test"),
}


def _c5_raw_columns():
    """
    Die C5-Kontextspalten wie in V2-C5 - ohne jede C8-Bereinigung.

    Die exakten Doppelspalten und die konstante bleiben hier bewusst
    DRIN: Der Kontrollarm soll den Zustand vor C8 abbilden, nicht eine
    halb bereinigte Zwischenstufe. Sonst maesse die Differenz zu M2
    zwei Dinge auf einmal.
    """
    from src.ml import dataset as ds

    return tuple(ds.CONTEXT_FELDER)


def c5_base_columns():
    """
    Die C5-Kontextspalten, die NEBEN den Interaktionen bleiben.

    Ausgeschlossen sind dreierlei: die durch eine Interaktion ersetzten
    Rohwerte (siehe INTERACTION_REPLACES), die exakten Doppelspalten
    (aggregate_available ist is_second_leg, neutral_venue ist is_final -
    beide mit r = 1,0000 in V2-C5 gemessen) und die im Bestand
    konstanten (siehe CONSTANT_IN_RANGE).

    Was bleibt, sind die reinen Zustandsindikatoren.
    """
    from src.ml import dataset as ds

    behalten = []
    for spalte in ds.CONTEXT_FELDER:
        if spalte in mc.INTERACTION_REPLACES:
            continue
        if spalte in mc.EXACT_DUPLICATES:
            continue
        if spalte in CONSTANT_IN_RANGE:
            continue
        behalten.append(spalte)
    return tuple(behalten)


# ---------------------------------------------------------------------------
# Die Kandidatenmatrix
# ---------------------------------------------------------------------------

def candidate_matrix():
    """
    Alle C8-Kandidaten, VORAB festgelegt.

    Jeder Eintrag nennt Hypothese, Vertrag, Merkmalsherkunft,
    Transformation und Kalibrierungsart. Die Liste steht vor dem ersten
    Lauf fest und wird danach nicht ergaenzt - eine nachtraeglich
    hinzugefuegte Variante waere eine Auswahl auf dem Testbestand.
    """
    v1 = tuple(fg.columns_for(fg.C3_BASE_CANDIDATE))
    c7 = tuple(sorted(
        f"{seite}_{feld}"
        for seite in ("home", "away")
        for feld in (C7_COUNT_COLUMNS + C7_NET_COLUMNS + C7_RATING_COLUMNS)))

    return (
        {
            "name": "M0_v1_control",
            "hypothesis": ("Die Kontrolle. Unveraenderter V1-Kandidat in "
                           "der bestehenden Modellklasse - ohne ihn im "
                           "selben Lauf waere jeder Vergleich gegen eine "
                           "Zahl aus einem anderen Artefakt."),
            "contract": CONTRACT_STANDARD,
            "columns": v1,
            "interactions": (),
            "transform_spec": {},
            "winsor": (),
            "calibration": mc.CALIBRATION_NONE,
        },
        {
            "name": "M1_c7_transformed",
            "hypothesis": ("Die C7-Zaehlmerkmale halfen im Punktschaetzer "
                           "und schadeten der Kalibrierung. Wenn die "
                           "Ursache die Schiefe und der Skalenversatz "
                           "zwischen Training und Test sind, muss log1p "
                           "beides mildern."),
            "contract": CONTRACT_STANDARD,
            "columns": tuple(sorted(set(v1) | set(c7))),
            "interactions": (),
            "transform_spec": c7_transform_spec(),
            "winsor": tuple(sorted(c7_winsor_columns())),
            "calibration": mc.CALIBRATION_NONE,
        },
        {
            "name": "M1c_c7_transformed_calibrated",
            "hypothesis": ("Wie M1, zusaetzlich mit einem auf der "
                           "INNEREN Validierung gelernten Kalibrator. "
                           "Traegt die Transformation den Punktschaetzer "
                           "und die Kalibrierung die Verteilung?"),
            "contract": CONTRACT_STANDARD,
            "columns": tuple(sorted(set(v1) | set(c7))),
            "interactions": (),
            "transform_spec": c7_transform_spec(),
            "winsor": tuple(sorted(c7_winsor_columns())),
            "calibration": mc.CALIBRATION_MULTIPLICATIVE,
        },
        {
            # KONTROLLARM, kein Kandidat.
            #
            # Ohne ihn waere die C8-Frage nicht beantwortbar: M1 gegen
            # M0 misst "C7 transformiert gegen V1", nicht "transformiert
            # gegen roh". Die Zahl aus dem C7-Artefakt hierher zu
            # uebernehmen waere ein Vergleich ueber zwei Laeufe hinweg.
            "name": "M1r_c7_raw_control",
            "role": "control",
            "hypothesis": ("Dieselben C7-Spalten OHNE Transformation. "
                           "Der Kontrollarm fuer die Transformation "
                           "selbst - erst die Differenz M1 minus M1r "
                           "beantwortet, ob log1p etwas beitraegt."),
            "contract": CONTRACT_STANDARD,
            "columns": tuple(sorted(set(v1) | set(c7))),
            "interactions": (),
            "transform_spec": {},
            "winsor": (),
            "calibration": mc.CALIBRATION_NONE,
        },
        {
            "name": "M2_c5_interactions",
            "hypothesis": ("Die C5-Kontextmerkmale schadeten, weil ein "
                           "Aggregatstand fuer 85 % der Zeilen imputiert "
                           "wurde. Als definitorisches Produkt ist er "
                           "dort exakt null. Behebt das den Schaden?"),
            "contract": CONTRACT_CONTEXT,
            "columns": tuple(sorted(set(v1) | set(c5_base_columns()))),
            "interactions": c5_interaction_columns(),
            "transform_spec": {},
            "winsor": (),
            "calibration": mc.CALIBRATION_NONE,
        },
        {
            # KONTROLLARM, kein Kandidat. Analog zu M1r.
            "name": "M2r_c5_raw_control",
            "role": "control",
            "hypothesis": ("Die vollstaendigen C5-Kontextspalten OHNE "
                           "Interaktionen, mit dem Aggregatstand als "
                           "Rohwert und damit als Imputationsopfer. Der "
                           "Kontrollarm fuer die Interaktion selbst."),
            "contract": CONTRACT_CONTEXT,
            "columns": tuple(sorted(set(v1) | set(_c5_raw_columns()))),
            "interactions": (),
            "transform_spec": {},
            "winsor": (),
            "calibration": mc.CALIBRATION_NONE,
        },
        {
            "name": "M3_c7_transformed_plus_c5_interactions",
            "hypothesis": ("Beide bekannten Problemstellen zugleich "
                           "behoben. Traegt die Kombination mehr als "
                           "jeder Teil fuer sich?"),
            "contract": CONTRACT_CONTEXT,
            "columns": tuple(sorted(set(v1) | set(c7)
                                    | set(c5_base_columns()))),
            "interactions": c5_interaction_columns(),
            "transform_spec": c7_transform_spec(),
            "winsor": tuple(sorted(c7_winsor_columns())),
            "calibration": mc.CALIBRATION_NONE,
        },
        {
            "name": "M4_reduced",
            "hypothesis": ("Der kleinste Kandidat, der die beiden "
                           "Befunde traegt: nur die Transferstaerke "
                           "(engstes Intervall in C7) und die "
                           "Aggregatinteraktion. Regelbasiert vorab "
                           "geschnitten, nicht nach Testergebnis."),
            "contract": CONTRACT_CONTEXT,
            "columns": tuple(sorted(
                set(v1)
                | {f"{seite}_{feld}" for seite in ("home", "away")
                   for feld in C7_RATING_COLUMNS}
                | {"is_second_leg", "is_knockout"})),
            "interactions": ("x_aggregate_diff_second_leg",),
            "transform_spec": {},
            "winsor": (),
            "calibration": mc.CALIBRATION_NONE,
        },
    )


#: M5 - alternative GLM-Regularisierung.
#:
#: NICHT ausgewertet. sklearn bietet fuer PoissonRegressor
#: ausschliesslich eine L2-Strafe; ein Elastic Net waere hier eine
#: Eigenimplementierung des IRLS-Verfahrens mit Koordinatenabstieg.
#: Das ist machbar, aber es waere neuer, ungetesteter numerischer Code
#: im Kern der Modellrechnung - und der Auftrag verlangt ausdruecklich,
#: keine halbgare Eigenimplementierung zu erzwingen.
#:
#: statsmodels ist im Projekt nicht vorhanden und waere eine neue
#: schwere Abhaengigkeit.
M5_STATUS = {
    "name": "M5_elastic_net_glm",
    "status": "NOT_EVALUATED",
    "reason": ("sklearn.PoissonRegressor kennt nur eine L2-Strafe. Eine "
               "Elastic-Net-Variante erforderte entweder statsmodels - "
               "im Projekt nicht vorhanden, neue schwere Abhaengigkeit - "
               "oder eine eigene IRLS-Implementierung mit "
               "Koordinatenabstieg. Beides steht ausser Verhaeltnis zu "
               "213 bis 303 Testpartien."),
    "would_reevaluate_when": ("Wenn der Testbestand deutlich waechst und "
                              "eine Sparsamkeitsstrafe ueber viele "
                              "Merkmale ueberhaupt etwas zu waehlen "
                              "haette."),
}


# ---------------------------------------------------------------------------
# Ein Fold
# ---------------------------------------------------------------------------

def _matrix(zeilen, spalten, interaktionen):
    """
    Die Merkmalsmatrix samt Interaktionsspalten.

    Die Interaktionen werden aus den ROHZEILEN gebildet, nicht aus der
    Matrix: Nur dort ist "nicht anwendbar" noch von "fehlt" zu
    unterscheiden. Nach der Imputation waere beides derselbe Median.
    """
    basis = mdl.feature_matrix(zeilen, list(spalten))
    if not interaktionen:
        return basis, list(spalten)

    zusatz = mc.build_interaction_columns(zeilen)
    namen = list(spalten) + list(interaktionen)
    erweitert = []
    for i, zeile in enumerate(basis):
        werte = list(zeile)
        for name in interaktionen:
            werte.append(zusatz[name][i])
        erweitert.append(werte)
    return erweitert, namen


def _fit(zeilen, seite, alpha, spalten, interaktionen, transform_spec,
         winsor):
    """Eine Seite anpassen - mit Transformation als erstem Schritt."""
    import numpy as np

    matrix, namen = _matrix(zeilen, spalten, interaktionen)
    ziel, gewicht = mdl.targets_and_weights(zeilen, seite)

    X = np.array(matrix, dtype=float)
    y = np.array(ziel, dtype=float)
    w = np.array(gewicht, dtype=float)

    # Der Transformationsschritt geht durch model.build_pipeline() -
    # denselben Codepfad, den auch fit_side() und die Runtime nutzen.
    # Eine eigene C8-Pipeline waere eine zweite Stelle, an der die
    # Schrittfolge entsteht, und damit die erste Gelegenheit fuer eine
    # Abweichung zwischen Training und Laufzeit.
    transform = mc.FeatureTransform(namen, transform_spec, winsor)
    voll = mdl.build_pipeline(alpha, transform)
    voll.fit(X, y, regressor__sample_weight=w)

    konvergiert = True
    regressor = voll.named_steps["regressor"]
    n_iter = getattr(regressor, "n_iter_", None)
    if n_iter is not None:
        try:
            konvergiert = int(n_iter) < int(regressor.max_iter)
        except (TypeError, ValueError):                  # pragma: no cover
            konvergiert = True

    diagnose = {
        "rows": len(zeilen),
        "features": len(namen),
        "constant_features": mdl.constant_features(matrix, namen),
        "fully_missing_features": mdl.fully_missing_features(matrix, namen),
        "n_iter": (int(n_iter) if n_iter is not None else None),
        "converged": konvergiert,
        "transform": voll.named_steps[mdl.TRANSFORM_STEP].to_dict(),
    }
    return voll, namen, diagnose


def _predict(pipeline, zeilen, spalten, interaktionen):
    import numpy as np

    matrix, _ = _matrix(zeilen, spalten, interaktionen)
    faktoren = pipeline.predict(np.array(matrix, dtype=float))
    if not np.isfinite(faktoren).all():
        raise ValueError("das Modell hat NaN oder Inf vorhergesagt")
    return [float(f) for f in faktoren]


def _select_alpha(fit_zeilen, val_zeilen, kandidat, alphas):
    """
    Alphawahl AUSSCHLIESSLICH auf der inneren Validierung.

    Gleichstandsregeln wie in evaluate.select_candidate und aus
    demselben Grund: Bei gleichem Verlust gewinnt das GROESSERE Alpha,
    also die staerkere Regularisierung - das zurueckhaltendere Modell
    lernt weniger aus dem Rauschen.
    """
    ausgaenge = [z["outcome"] for z in val_zeilen]
    basis = ev.summarise(ev.probabilities_for(mdl.baseline_lambdas(val_zeilen)),
                         ausgaenge)["log_loss"]

    protokoll = [{"alpha": mdl.NO_CORRECTION, "inner_log_loss": basis}]
    gemessen = []

    for alpha in alphas:
        try:
            heim, _, d_heim = _fit(fit_zeilen, "home", alpha,
                                   kandidat["columns"],
                                   kandidat["interactions"],
                                   kandidat["transform_spec"],
                                   kandidat["winsor"])
            gast, _, d_gast = _fit(fit_zeilen, "away", alpha,
                                   kandidat["columns"],
                                   kandidat["interactions"],
                                   kandidat["transform_spec"],
                                   kandidat["winsor"])
            fh = _predict(heim, val_zeilen, kandidat["columns"],
                          kandidat["interactions"])
            fa = _predict(gast, val_zeilen, kandidat["columns"],
                          kandidat["interactions"])
            lambdas, _ = mdl.apply_correction(val_zeilen, fh, fa)
            verlust = ev.summarise(ev.probabilities_for(lambdas),
                                   ausgaenge)["log_loss"]
        except Exception as fehler:                      # pragma: no cover
            protokoll.append({"alpha": alpha, "error": str(fehler)})
            continue

        protokoll.append({"alpha": alpha, "inner_log_loss": verlust,
                          "converged": d_heim["converged"]
                          and d_gast["converged"]})
        gemessen.append((verlust, alpha, (heim, gast), (d_heim, d_gast)))

    if not gemessen:
        return None, None, None, {"candidates": protokoll,
                                  "selected": mdl.NO_CORRECTION,
                                  "baseline_inner_log_loss": basis}

    bestes = min(gemessen, key=lambda e: (e[0], -e[1]))
    if bestes[0] >= basis:
        return None, None, None, {
            "candidates": protokoll, "selected": mdl.NO_CORRECTION,
            "baseline_inner_log_loss": basis,
            "selected_inner_log_loss": basis,
            "tie_break": ("gegenueber der Baseline zaehlt nur strikte "
                          "Verbesserung")}

    return bestes[1], bestes[2], bestes[3], {
        "candidates": protokoll, "selected": bestes[1],
        "baseline_inner_log_loss": basis,
        "selected_inner_log_loss": bestes[0],
        "tie_break": ("bei gleichem inneren Verlust gewinnt das "
                      "groessere Alpha - die staerkere Regularisierung"),
    }


def run_fold(zeilen, fold, kandidat, alphas=mdl.ALPHA_CANDIDATES,
             train_rows=None, test_rows=None):
    """
    Ein aeusserer Fold fuer einen Kandidaten.

    Ablauf, und die Reihenfolge ist der ganze Leakageschutz:

      1. Trainings- und Testbestand nach Vertrag waehlen.
      2. Training INNEN teilen.
      3. Alpha auf der inneren Validierung waehlen.
      4. Kalibrator auf denselben inneren Validierungsvorhersagen
         lernen.
      5. Mit dem gewaehlten Alpha auf dem GESAMTEN Training anpassen.
      6. EINMAL auf dem aeusseren Test messen.

    Der aeussere Test geht in keinen der Schritte 2 bis 5 ein.
    """
    waehle_training = train_rows or ce.league_rows
    waehle_test = test_rows or (lambda z, s: ce.cl_rows(z, s[0]))

    training = waehle_training(zeilen, fold["train_seasons"])
    test_zeilen = waehle_test(zeilen, [fold["test_season"]])
    if not training or not test_zeilen:
        return {"fold": fold["name"], "error": "zu wenig Daten"}

    fit_zeilen, val_zeilen, innen = ev.inner_split(
        training, {"train_seasons": fold["train_seasons"]},
        select=waehle_training)

    alpha, modelle, diagnosen, wahl = _select_alpha(
        fit_zeilen, val_zeilen, kandidat, alphas)

    # -- Kalibrierung: auf der INNEREN Validierung -----------------------
    kalibratoren = {"home": mc.LambdaCalibrator(),
                    "away": mc.LambdaCalibrator()}
    if alpha is not None and kandidat["calibration"] != mc.CALIBRATION_NONE:
        fh = _predict(modelle[0], val_zeilen, kandidat["columns"],
                      kandidat["interactions"])
        fa = _predict(modelle[1], val_zeilen, kandidat["columns"],
                      kandidat["interactions"])
        val_lambdas, _ = mdl.apply_correction(val_zeilen, fh, fa)
        for i, seite in enumerate(("home", "away")):
            kalibratoren[seite] = mc.fit_calibrator(
                [l[i] for l in val_lambdas],
                [z[f"{seite}_goals"] for z in val_zeilen],
                mode=kandidat["calibration"])

    # -- Aeussere Anpassung und Messung ----------------------------------
    ausgaenge = [z["outcome"] for z in test_zeilen]
    basis_p = ev.probabilities_for(mdl.baseline_lambdas(test_zeilen))

    if alpha is None:
        ml_lambdas = mdl.baseline_lambdas(test_zeilen)
        clamps = {}
        aussen_diagnose = {"selected": mdl.NO_CORRECTION}
    else:
        heim, _, d_heim = _fit(training, "home", alpha, kandidat["columns"],
                               kandidat["interactions"],
                               kandidat["transform_spec"], kandidat["winsor"])
        gast, _, d_gast = _fit(training, "away", alpha, kandidat["columns"],
                               kandidat["interactions"],
                               kandidat["transform_spec"], kandidat["winsor"])
        fh = _predict(heim, test_zeilen, kandidat["columns"],
                      kandidat["interactions"])
        fa = _predict(gast, test_zeilen, kandidat["columns"],
                      kandidat["interactions"])
        roh_lambdas, clamps = mdl.apply_correction(test_zeilen, fh, fa)

        kalibriert_home = kalibratoren["home"].apply(
            [l[0] for l in roh_lambdas])
        kalibriert_away = kalibratoren["away"].apply(
            [l[1] for l in roh_lambdas])
        # Die Guardrails greifen NACH der Kalibrierung erneut. Sie zu
        # umgehen waere die einfachste Art, ein unsinniges Lambda in die
        # Verteilung zu bekommen.
        ml_lambdas = [
            (min(max(h, mdl.LAMBDA_MIN), mdl.LAMBDA_MAX),
             min(max(a, mdl.LAMBDA_MIN), mdl.LAMBDA_MAX))
            for h, a in zip(kalibriert_home, kalibriert_away)]
        aussen_diagnose = {"selected": alpha, "home": d_heim, "away": d_gast}

    ml_p = ev.probabilities_for(ml_lambdas)
    ce.assert_paired(test_zeilen, basis_p, ml_p)

    basis = ev.summarise(basis_p, ausgaenge)
    ml = ev.summarise(ml_p, ausgaenge)

    ergebnis = {
        "fold": fold["name"],
        "train_seasons": fold["train_seasons"],
        "test_season": fold["test_season"],
        "train_rows": len(training),
        "test_rows": len(test_zeilen),
        "inner_split": innen,
        "alpha_selection": wahl,
        "selected_alpha": alpha,
        "calibration": {seite: kalibratoren[seite].to_dict()
                        for seite in ("home", "away")},
        "baseline": basis,
        "ml": ml,
        "delta_log_loss": ml["log_loss"] - basis["log_loss"],
        "delta_brier": ml["brier"] - basis["brier"],
        "delta_rps": ml["rps"] - basis["rps"],
        "clamps": clamps,
        "fit_diagnostics": aussen_diagnose,
        "mean_lambda_home": (sum(l[0] for l in ml_lambdas) / len(ml_lambdas)),
        "mean_lambda_away": (sum(l[1] for l in ml_lambdas) / len(ml_lambdas)),
    }
    ergebnis["_internal"] = {
        "baseline_losses": ev.per_match_losses(basis_p, ausgaenge),
        "ml_losses": ev.per_match_losses(ml_p, ausgaenge),
        "baseline_calibration": ev.calibration_sums(basis_p, ausgaenge),
        "ml_calibration": ev.calibration_sums(ml_p, ausgaenge),
        "rows": test_zeilen,
    }
    return ergebnis


# ---------------------------------------------------------------------------
# Ein Kandidat ueber beide Folds
# ---------------------------------------------------------------------------

def run_candidate(zeilen, kandidat, alphas=mdl.ALPHA_CANDIDATES):
    """Ein Kandidat ueber die Folds seines Vertrags."""
    beginn = time.time()

    if kandidat["contract"] == CONTRACT_CONTEXT:
        folds = ce.CONTEXT_FOLDS
        train_rows, test_rows = ce.context_training_rows, ce.context_rows
    else:
        folds = ce.OUTER_FOLDS
        train_rows = test_rows = None

    ergebnisse = [run_fold(zeilen, fold, kandidat, alphas,
                           train_rows=train_rows, test_rows=test_rows)
                  for fold in folds]
    zusammen = ce.aggregate(ergebnisse)

    verluste = {"log_loss": [], "brier": [], "rps": []}
    for fold in ergebnisse:
        intern = fold.get("_internal") or {}
        for schluessel in verluste:
            verluste[schluessel].extend(
                (intern.get("ml_losses") or {}).get(schluessel, []))
    for fold in ergebnisse:
        fold.pop("_internal", None)

    return {
        "_losses": verluste,
        "name": kandidat["name"],
        "hypothesis": kandidat["hypothesis"],
        "contract": kandidat["contract"],
        "feature_count": len(kandidat["columns"]) + len(kandidat["interactions"]),
        "base_features": len(kandidat["columns"]),
        "interactions": list(kandidat["interactions"]),
        "transformed_columns": sorted(
            k for k, v in kandidat["transform_spec"].items()
            if v != mc.TRANSFORM_IDENTITY),
        "winsor_columns": list(kandidat["winsor"]),
        "calibration_mode": kandidat["calibration"],
        "folds": ergebnisse,
        "aggregate": zusammen,
        "runtime_seconds": round(time.time() - beginn, 2),
    }


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

#: Wie stark die Kalibrierung hoechstens leiden darf.
#:
#: 25 % relativ. Der Wert steht VORAB fest: V1 erreicht im
#: Standardvertrag 0,01647, ein Viertel schlechter waere 0,02059.
#: C7 lag zwischen 0,0215 und 0,0431 - also durchweg darueber, und
#: genau deshalb wurde dort nichts aufgenommen.
MAX_CALIBRATION_DEGRADATION = 0.25

#: Wie stark Brier und RPS hoechstens leiden duerfen. Null: Eine
#: Verschlechterung in einer zweiten Guetemetrik ist kein Preis, den
#: ein besserer LogLoss wert waere.
MAX_SECONDARY_DEGRADATION = 0.0

DECISION_ACCEPTED = "ACCEPTED"
DECISION_REJECTED = "REJECTED"
DECISION_INCONCLUSIVE = "INCONCLUSIVE"
DECISION_NOT_EVALUATED = "NOT_EVALUATED"


def check_gate(kandidat_ergebnis, kontrolle, gepaart):
    """
    Das vollstaendige Aufnahmegate - Bedingung fuer Bedingung.

    Rueckgabe: dict mit Urteil und dem Ergebnis JEDER Bedingung. Ein
    einzelnes False genuegt; welches, steht daneben.
    """
    zusammen = kandidat_ergebnis.get("aggregate")
    kontroll_zusammen = kontrolle.get("aggregate")
    if zusammen is None or kontroll_zusammen is None:
        return {"decision": DECISION_REJECTED,
                "conditions": {"evaluable": False},
                "reasons": ["kein auswertbarer Fold"]}

    intervall = (gepaart or {}).get("log_loss") or {}
    delta = intervall.get("point")
    ci_low, ci_high = intervall.get("ci_low"), intervall.get("ci_high")

    folds = [f for f in kandidat_ergebnis["folds"] if "error" not in f]
    kontroll_folds = {f["fold"]: f for f in kontrolle["folds"]
                      if "error" not in f}

    # 2. Richtung in BEIDEN Folds
    richtungen = []
    for fold in folds:
        gegen = kontroll_folds.get(fold["fold"])
        if gegen is None:
            continue
        richtungen.append(fold["delta_log_loss"] - gegen["delta_log_loss"])
    beide_richtungen = bool(richtungen) and all(r < 0 for r in richtungen)

    # 6. Keine einzelne Saison traegt praktisch alles
    dominanz = None
    if len(richtungen) == 2 and sum(richtungen) < 0:
        anteile = [r / sum(richtungen) for r in richtungen]
        dominanz = max(anteile)
    keine_dominanz = dominanz is None or dominanz <= 0.9

    # 4. Brier und RPS
    brier_ok = (zusammen["delta_brier"] - kontroll_zusammen["delta_brier"]
                <= MAX_SECONDARY_DEGRADATION)
    rps_ok = (zusammen["delta_rps"] - kontroll_zusammen["delta_rps"]
              <= MAX_SECONDARY_DEGRADATION)

    # 5. Kalibrierung
    kalib_kandidat = zusammen["ml"]["calibration_error"]
    kalib_kontrolle = kontroll_zusammen["ml"]["calibration_error"]
    kalib_ok = (kalib_kandidat is not None and kalib_kontrolle is not None
                and kalib_kandidat
                <= kalib_kontrolle * (1.0 + MAX_CALIBRATION_DEGRADATION))

    # 9. Konvergenz
    konvergiert = True
    for fold in folds:
        for seite in ("home", "away"):
            block = (fold.get("fit_diagnostics") or {}).get(seite) or {}
            if block.get("converged") is False:
                konvergiert = False

    # 10. Komplexitaet
    zusatz = (kandidat_ergebnis["feature_count"]
              - kontrolle["feature_count"])
    komplexitaet_ok = zusatz <= 0 or (delta is not None and delta < 0)

    bedingungen = {
        "paired_delta_negative": delta is not None and delta < 0,
        "same_direction_in_both_folds": beide_richtungen,
        "ci_excludes_zero": (ci_high is not None and ci_high < 0),
        "brier_not_worse": brier_ok,
        "rps_not_worse": rps_ok,
        "calibration_acceptable": kalib_ok,
        "no_single_season_dominance": keine_dominanz,
        "converged": konvergiert,
        "complexity_justified": komplexitaet_ok,
        "sample_large_enough": zusammen["n"] >= ce.MIN_RELIABLE_N,
    }

    gruende = []
    if not bedingungen["paired_delta_negative"]:
        gruende.append(
            "gepaarte Differenz gegen die Kontrolle %s ist nicht negativ"
            % ("-" if delta is None else "%+.6f" % delta))
    if not bedingungen["same_direction_in_both_folds"]:
        gruende.append("nicht in beiden Folds besser als die Kontrolle")
    if not bedingungen["ci_excludes_zero"]:
        gruende.append(
            "das 95-%%-Intervall schliesst die Null nicht aus (obere "
            "Grenze %s)" % ("-" if ci_high is None else "%+.6f" % ci_high))
    if not bedingungen["calibration_acceptable"]:
        gruende.append(
            "Kalibrierung %.5f gegen %.5f der Kontrolle - mehr als %.0f %% "
            "schlechter" % (kalib_kandidat or float("nan"),
                            kalib_kontrolle or float("nan"),
                            100 * MAX_CALIBRATION_DEGRADATION))
    if not bedingungen["brier_not_worse"]:
        gruende.append("Brier schlechter als die Kontrolle")
    if not bedingungen["rps_not_worse"]:
        gruende.append("RPS schlechter als die Kontrolle")
    if not bedingungen["no_single_season_dominance"]:
        gruende.append("eine einzelne Saison traegt praktisch den "
                       "gesamten Gewinn")
    if not bedingungen["converged"]:
        gruende.append("mindestens eine Anpassung ist nicht konvergiert")

    if all(bedingungen.values()):
        urteil = DECISION_ACCEPTED
        gruende.append("alle Gate-Bedingungen erfuellt")
    elif not bedingungen["paired_delta_negative"]:
        urteil = DECISION_REJECTED
    elif not bedingungen["converged"]:
        urteil = DECISION_REJECTED
    else:
        urteil = DECISION_INCONCLUSIVE

    return {"decision": urteil, "conditions": bedingungen,
            "reasons": gruende,
            "paired_delta_log_loss": delta,
            "ci_low": ci_low, "ci_high": ci_high,
            "calibration_candidate": kalib_kandidat,
            "calibration_control": kalib_kontrolle,
            "fold_direction_vs_control": richtungen}


def gate_criteria():
    """Die Regeln im Klartext - sie gehoeren ins Artefakt."""
    return {
        "paired_delta_negative": "gepaarte LogLoss-Differenz gegen die "
                                 "Kontrolle desselben Vertrags < 0",
        "same_direction_in_both_folds": "in BEIDEN aeusseren Folds besser "
                                        "als die Kontrolle",
        "ci_excludes_zero": "obere 95-%-Bootstrapgrenze < 0",
        "brier_not_worse": "Brier nicht schlechter als die Kontrolle",
        "rps_not_worse": "RPS nicht schlechter als die Kontrolle",
        "calibration_acceptable":
            f"Kalibrierungsfehler hoechstens "
            f"{100 * MAX_CALIBRATION_DEGRADATION:.0f} % ueber der Kontrolle",
        "no_single_season_dominance": "kein Fold traegt ueber 90 % des "
                                      "Gewinns",
        "converged": "alle Anpassungen konvergiert",
        "complexity_justified": "zusaetzliche Merkmale nur bei negativem "
                                "Delta",
        "sample_large_enough": f"n >= {ce.MIN_RELIABLE_N}",
        "tie_break": ("Bestehen mehrere Kandidaten, gewinnt NICHT der "
                      "beste Punktschaetzer, sondern der einfachste: "
                      "weniger Merkmale, staerkere Regularisierung, "
                      "bessere Kalibrierung, stabilere Folds."),
    }


# ---------------------------------------------------------------------------
# Gesamtlauf
# ---------------------------------------------------------------------------

#: Welcher Arm gegen welchen Kontrollarm die eigentliche C8-Wirkung
#: zeigt. Beide Seiten laufen im SELBEN Lauf auf demselben Bestand -
#: nur so ist die Differenz eine Differenz und kein Artefaktvergleich.
ISOLATED_EFFECTS = (
    {"effect": "transformation", "arm": "M1_c7_transformed",
     "control": "M1r_c7_raw_control",
     "question": "Traegt log1p auf den C7-Zaehlmerkmalen etwas bei?"},
    {"effect": "calibration", "arm": "M1c_c7_transformed_calibrated",
     "control": "M1_c7_transformed",
     "question": ("Repariert ein auf der inneren Validierung gelernter "
                  "Faktor die Kalibrierung?")},
    {"effect": "interaction", "arm": "M2_c5_interactions",
     "control": "M2r_c5_raw_control",
     "question": ("Ist die definitorische Null besser als der "
                  "imputierte Median?")},
)


def _isolierte_wirkungen(ergebnisse, gepaart):
    """
    Die Wirkung JEDER Erweiterung fuer sich - gegen ihren eigenen Arm.

    Die Zahlen gegen M0 vermengen zwei Dinge: die zusaetzlichen
    Merkmale und deren Behandlung. Erst der Vergleich Arm gegen
    Kontrollarm trennt beides.
    """
    heraus = []
    for spez in ISOLATED_EFFECTS:
        arm = ergebnisse.get(spez["arm"])
        kontrolle = ergebnisse.get(spez["control"])
        if arm is None or kontrolle is None:
            heraus.append(dict(spez, status=DECISION_NOT_EVALUATED,
                               reason="ein Arm fehlt im Lauf"))
            continue

        a = arm["aggregate"]
        k = kontrolle["aggregate"]
        d_ll = a["delta_log_loss"] - k["delta_log_loss"]
        d_kal = (a["ml"]["calibration_error"]
                 - k["ml"]["calibration_error"])
        heraus.append(dict(
            spez,
            delta_log_loss=d_ll,
            delta_calibration_error=d_kal,
            arm_calibration=a["ml"]["calibration_error"],
            control_calibration=k["ml"]["calibration_error"],
            direction=("verbessert" if d_ll < 0 else
                       "verschlechtert" if d_ll > 0 else "unveraendert"),
            calibration_direction=("verbessert" if d_kal < 0 else
                                   "verschlechtert" if d_kal > 0
                                   else "unveraendert"),
        ))
    return heraus


#: Felder, die eine MESSUNG DER MASCHINE sind, kein Ergebnis.
#:
#: Sie gehoeren ins Artefakt - eine Laufzeit ist eine nuetzliche
#: Diagnose -, aber sie duerfen den Determinismusnachweis nicht
#: zerstoeren. Zwei Laeufe auf demselben Bestand liefern nie dieselbe
#: Wanduhrzeit; sie muessen dieselben Zahlen liefern.
NON_DETERMINISTIC_FIELDS = ("runtime_seconds",)


def result_fingerprint(ergebnis):
    """
    Ein Hash ueber alles, was ein zweiter Lauf reproduzieren MUSS.

    Ausgenommen sind ausschliesslich die Maschinenmessungen aus
    NON_DETERMINISTIC_FIELDS. Damit ist "zweimal gelaufen, gleiches
    Ergebnis" eine pruefbare Aussage und keine Behauptung.
    """
    import hashlib
    import json

    def _saeubern(wert):
        if isinstance(wert, dict):
            return {k: _saeubern(v) for k, v in sorted(wert.items())
                    if k not in NON_DETERMINISTIC_FIELDS}
        if isinstance(wert, list):
            return [_saeubern(v) for v in wert]
        return wert

    roh = json.dumps(_saeubern(ergebnis), sort_keys=True, ensure_ascii=False,
                     default=repr)
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()


def run_c8_ablation(zeilen, alphas=mdl.ALPHA_CANDIDATES, kandidaten=None):
    """
    Die vollstaendige C8-Ablation.

    Je Vertrag laeuft ein eigener V1-Kontrollarm; jeder Kandidat wird
    ausschliesslich gegen die Kontrolle SEINES Vertrags gepaart.
    """
    kandidaten = kandidaten or candidate_matrix()

    ergebnisse = {}
    for kandidat in kandidaten:
        ergebnisse[kandidat["name"]] = run_candidate(zeilen, kandidat, alphas)

    # Der Kontrollarm des Kontextvertrags: derselbe V1-Merkmalssatz,
    # aber unter dem anderen Vertrag gemessen.
    kontext_kontrolle = None
    if any(k["contract"] == CONTRACT_CONTEXT for k in kandidaten):
        # Der Kontextkontrollarm entsteht aus M0. Waere an Position 0
        # etwas anderes, traege die "Kontrolle" fremde Merkmale und
        # jeder Kontextvergleich waere still falsch - deshalb hier ein
        # Abbruch und keine stillschweigende Annahme.
        if kandidaten[0]["name"] != "M0_v1_control":
            raise ValueError(
                "der erste Kandidat muss M0_v1_control sein - aus ihm "
                f"entsteht der Kontextkontrollarm, gefunden: "
                f"{kandidaten[0]['name']!r}")
        kontrolle_spec = dict(kandidaten[0])
        kontrolle_spec.update({"name": "M0_v1_control_context",
                               "contract": CONTRACT_CONTEXT,
                               "hypothesis": ("dieselbe Kontrolle unter dem "
                                              "Kontextvertrag - ohne sie "
                                              "waeren M2 bis M4 gegen eine "
                                              "Zahl aus einem anderen "
                                              "Bestand gemessen")})
        kontext_kontrolle = run_candidate(zeilen, kontrolle_spec, alphas)
        ergebnisse[kontrolle_spec["name"]] = kontext_kontrolle

    kontrollen = {
        CONTRACT_STANDARD: ergebnisse["M0_v1_control"],
        CONTRACT_CONTEXT: kontext_kontrolle,
    }

    gepaart, urteile = {}, {}
    for name, ergebnis in ergebnisse.items():
        kontrolle = kontrollen.get(ergebnis["contract"])
        if kontrolle is None or ergebnis["name"] == kontrolle["name"]:
            continue
        eigene = ergebnis["_losses"]
        kontroll_verluste = kontrolle["_losses"]
        block = {}
        for schluessel in ("log_loss", "brier", "rps"):
            a, b = eigene[schluessel], kontroll_verluste[schluessel]
            if len(a) != len(b):
                raise ValueError(
                    f"{name!r} und {kontrolle['name']!r} bewerten "
                    f"verschieden viele Spiele ({len(a)} gegen {len(b)})")
            intervall = ev.paired_bootstrap(b, a)
            if intervall:
                intervall["interpretation"] = ev.interpret(intervall)
            block[schluessel] = intervall
        gepaart[name] = block
        urteile[name] = check_gate(ergebnis, kontrolle, block)

    for ergebnis in ergebnisse.values():
        ergebnis.pop("_losses", None)

    rollen = {k["name"]: k.get("role", "candidate") for k in kandidaten}

    # Ein Kontrollarm kann das Gate bestehen - er wird dadurch aber
    # nicht zum C8-Ergebnis. M1r ist V1 plus C7 roh; genau das hat C7
    # bereits geprueft. Die Trennung steht hier und nicht im Bericht,
    # damit sie nicht von der Auslegung abhaengt.
    angenommen = [name for name, urteil in urteile.items()
                  if urteil["decision"] == DECISION_ACCEPTED
                  and rollen.get(name) == "candidate"]
    kontrollen_bestanden = [name for name, urteil in urteile.items()
                            if urteil["decision"] == DECISION_ACCEPTED
                            and rollen.get(name) == "control"]

    heraus = {
        "schema_version": SCHEMA_VERSION,
        "model_class_version": mc.MODEL_CLASS_VERSION,
        "candidates": [k["name"] for k in kandidaten],
        "roles": rollen,
        "contracts": {
            CONTRACT_STANDARD: "train national leagues, test CL regular phase",
            CONTRACT_CONTEXT: ("train national leagues + earlier CL seasons, "
                               "test CL regular phase + knockout"),
        },
        "controls": {vertrag: (kontrolle["name"] if kontrolle else None)
                     for vertrag, kontrolle in kontrollen.items()},
        "results": ergebnisse,
        "paired_against_control": gepaart,
        "gate": urteile,
        "gate_criteria": gate_criteria(),
        "not_evaluated": [M5_STATUS],
        "accepted": angenommen,
        "controls_passing_gate": kontrollen_bestanden,
        "isolated_effects": _isolierte_wirkungen(ergebnisse, gepaart),
        "final_candidate": (angenommen[0] if angenommen
                            else fg.C3_BASE_CANDIDATE),
        "bundle_decision": (
            "Modellbundle unveraendert - kein Kandidat hat das "
            "vollstaendige Gate bestanden" if not angenommen else
            "ein Kandidat hat das Gate bestanden; die Promotion ist eine "
            "eigene, ausdrueckliche Entscheidung"),
    }
    heraus["result_fingerprint"] = result_fingerprint(heraus)
    heraus["fingerprint_excludes"] = list(NON_DETERMINISTIC_FIELDS)
    return heraus
