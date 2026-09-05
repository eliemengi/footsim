"""
Versionierte Persistenz des Champions-League-Schattenmodells.

WAS HIER ENTSTEHT
-----------------
Ein reproduzierbarer Trainingspfad und ein nachpruefbares Artefakt.

FREIGABESTUFE STATT ZWEIER WAHRHEITSWERTE (C0B)
-----------------------------------------------
Bis C0B trug jedes Bundle shadow_only = true und
production_approved = false, und der Loader verlangte genau das. Das
stand im Widerspruch zur Wirklichkeit: Ueber approach=ml wurde dasselbe
Modell mit vollem Gewicht in die Nutzerprognose gerechnet. Die
Metadaten sagten "nur Schatten", der Laufzeitpfad tat etwas anderes,
und kein Code verband beide Aussagen.

An ihre Stelle tritt EIN Feld mit drei Stufen:

    shadow        darf gerechnet und protokolliert werden, veraendert
                  aber niemals ein Nutzerergebnis
    experimental  darf unter dem ausdruecklichen Produktvertrag aktiv
                  wirken; noch nicht statistisch abschliessend belegt
    approved      vollstaendig freigegebene Modellgeneration

Die Stufe ist kein Schmuck: Sie geht in die Modellkennung ein, der
Loader prueft sie, und runtime.py verweigert die Anwendung, wenn sie
den aktiven Betrieb nicht deckt. Eine unbekannte Stufe wird
abgewiesen, nicht geraten.

Das aktuelle CL-Modell steht auf experimental. Der Grund ist in den
Zahlen nachlesbar, die das Bundle traegt - C3 hat einen besseren
Punktschaetzer und ein Intervall gemessen, das die Null einschliesst.

EVALUATION WIRD GEBUNDEN, NICHT BEHAUPTET (C0B)
-----------------------------------------------
Frueher stand das C3-Urteil als Literal in dieser Datei. Jedes kuenftige
Bundle - auch ein V2-Modell mit anderen Merkmalen und anderen Daten -
haette damit "INCONCLUSIVE, -0,00890, n=213" geerbt, ohne dass diese
Zahlen je etwas mit ihm zu tun gehabt haetten. Das war Scheinprovenienz.

Ein Bundle bekommt seine Kennzahlen jetzt ausschliesslich aus einem
uebergebenen, geprueften Evaluationsartefakt. Dabei muessen
Datensatz-Fingerabdruck und Merkmalsvertrag von Training und
Auswertung uebereinstimmen; sonst entsteht kein Bundle.

WARUM JSON UND NICHT JOBLIB
---------------------------
Nachgemessen, nicht vermutet: Die Pipeline besteht aus SimpleImputer
(median), StandardScaler und PoissonRegressor. Alle drei sind
vollstaendig durch Zahlenfelder beschrieben - statistics_, mean_,
scale_, coef_, intercept_ -, und ihre Vorhersage ist

    x_imputiert = median, wo der Wert fehlt
    x_skaliert  = (x - mean) / scale
    faktor      = exp(intercept + x_skaliert @ coef)

Der Nachbau aus diesen Zahlen wurde gegen pipeline.predict() geprueft:
groesste Abweichung 0,000e+00 ueber echte Trainingszeilen. Es gibt
also keinen Genauigkeitsgrund fuer eine Binaerserialisierung.

Dagegen spricht einiges gegen joblib/pickle: Das Laden fuehrt Code aus,
das Format ist an die sklearn-Fassung gebunden, und der Inhalt laesst
sich nicht lesen. Ein JSON-Bundle ist pruefbar, versionsrobust und
kann beim Laden nichts ausfuehren. Deshalb JSON.

Sollte ein spaeteres Modell nicht mehr rein linear sein, traegt es
diese Eigenschaft nicht mehr - dann ist MODEL_FAMILY zu erweitern und
diese Entscheidung neu zu treffen. Der Loader bricht bei unbekannter
Familie ab, statt zu raten.

INTEGRITAET
-----------
Ueber die Modellbestandteile laeuft ein SHA-256. Er wird beim Speichern
gebildet und beim Laden nachgerechnet. Er schuetzt vor Beschaedigung
und vertauschten Dateien - er ist KEIN Schutz gegen einen Angreifer mit
Schreibrecht, denn wer die Zahlen aendert, kann auch den Hash neu
setzen. Fuer diesen Zweck reicht das: Geladen werden ausschliesslich
Artefakte, die FootSim selbst erzeugt hat, aus dem eigenen
Arbeitsverzeichnis. Fremde oder aus dem Netz bezogene Bundles gehoeren
nicht hierher.
"""

import hashlib
import json
import os
import platform
from datetime import datetime, timezone

from src.ml import evaluate as ev
from src.ml import feature_groups as fg
from src.ml import model as mdl

#: Fassung des Bundleformats.
#:
#: 2  C0B: gebundene Evaluation (provenance.evaluation) und
#:    release_stage statt shadow_only/production_approved.
MODEL_SCHEMA_VERSION = 2

#: Fassungen, die der Loader lesen kann. Fassung 1 wird ausschliesslich
#: konservativ gelesen - siehe _lies_freigabestufe().
SUPPORTED_SCHEMA_VERSIONS = (1, MODEL_SCHEMA_VERSION)

#: Die Freigabestufen. Reihenfolge ist Absicht: aufsteigend.
STAGE_SHADOW = "shadow"
STAGE_EXPERIMENTAL = "experimental"
STAGE_APPROVED = "approved"
RELEASE_STAGES = (STAGE_SHADOW, STAGE_EXPERIMENTAL, STAGE_APPROVED)

#: Stufen, unter denen ein Modell ein Nutzerergebnis veraendern darf.
#: shadow steht ausdruecklich NICHT hier.
STAGES_ALLOWED_ACTIVE = (STAGE_EXPERIMENTAL, STAGE_APPROVED)

#: Die Stufe eines Bundles ohne ausdrueckliche Angabe. Der sichere Wert
#: ist der niedrigste - wer nichts sagt, bekommt nichts.
DEFAULT_RELEASE_STAGE = STAGE_SHADOW

#: Die Modellfamilie. Nur diese eine ist rekonstruierbar; eine andere
#: Bauform braucht eine eigene Kennung und einen eigenen Loader.
MODEL_FAMILY = "poisson_offset_correction_linear"

#: Trainingssaisons des Zukunftsmodells.
DEFAULT_TRAINING_SEASONS = (2023, 2024, 2025)

#: Die Seiten. Beide muessen vorhanden sein - ein Bundle mit nur einer
#: waere unbrauchbar und wird abgelehnt.
SIDES = ("home", "away")

#: Toleranz des Roundtrips. Erwartet wird exakte Gleichheit: Pythons
#: float-Darstellung in JSON ist verlustfrei rundreisefaehig. Der Wert
#: steht als Sicherheitsnetz, nicht als Erwartung - ein Test haelt
#: fest, dass die tatsaechliche Abweichung null ist.
ROUNDTRIP_TOLERANCE = 1e-12


#: Maschinenlesbare Fehlerarten. Sie erlauben einer aufrufenden
#: Schicht, den Grund zu unterscheiden, ohne auf Meldungstexte zu
#: greifen - eine Textpruefung waere bei der naechsten Umformulierung
#: still kaputt.
KIND_MISSING = "model_missing"
KIND_INVALID = "model_invalid"
KIND_INCOMPATIBLE = "model_incompatible"


class ModelBundleError(Exception):
    """
    Ein Bundle ist unbrauchbar - beschaedigt, fremd oder unpassend.

    kind traegt die Art des Problems: KIND_MISSING (nicht da),
    KIND_INVALID (kaputt oder veraendert) oder KIND_INCOMPATIBLE
    (lesbar, aber passt nicht zu diesem Stand).
    """

    def __init__(self, meldung, kind=KIND_INVALID):
        super().__init__(meldung)
        self.kind = kind


# ---------------------------------------------------------------------------
# Serialisierung der Pipeline
# ---------------------------------------------------------------------------

def serialise_pipeline(pipeline, spalten):
    """
    Die angepasste Pipeline als reine Zahlen.

    Bricht ab, wenn ein Schritt eine andere Spaltenzahl sieht als
    erwartet. Das ist kein theoretischer Fall: SimpleImputer VERWIRFT
    Spalten, die ueberhaupt keinen Wert tragen - die nachgelagerten
    Schritte haetten dann weniger Merkmale als Namen, und jede
    Zuordnung waere geraten.
    """
    imputer = pipeline.named_steps["imputer"]
    scaler = pipeline.named_steps["scaler"]
    regressor = pipeline.named_steps["regressor"]

    erwartet = len(spalten)
    for name, schritt, laenge in (
            ("imputer.statistics_", imputer, len(imputer.statistics_)),
            ("scaler.mean_", scaler, len(scaler.mean_)),
            ("scaler.scale_", scaler, len(scaler.scale_)),
            ("regressor.coef_", regressor, len(regressor.coef_))):
        if laenge != erwartet:
            raise ModelBundleError(
                f"{name} hat {laenge} Eintraege, erwartet sind {erwartet} - "
                f"vermutlich hat der Imputer leere Spalten verworfen")

    return {
        "imputer": {"strategy": "median",
                    "statistics": [float(v) for v in imputer.statistics_]},
        "scaler": {"mean": [float(v) for v in scaler.mean_],
                   "scale": [float(v) for v in scaler.scale_]},
        "regressor": {"kind": "PoissonRegressor",
                      "link": "log",
                      "intercept": float(regressor.intercept_),
                      "coef": [float(v) for v in regressor.coef_]},
    }


class LoadedModel:
    """
    Ein aus JSON rekonstruiertes Korrekturmodell.

    Es tritt an dieselbe Stelle wie eine sklearn-Pipeline: Es stellt
    named_steps bereit und beantwortet predict(). Damit brauchen
    model.predict_factors() und model.coefficients() keinen eigenen
    Zweig fuer geladene Modelle - und ein geladenes Modell laeuft
    zwangslaeufig durch genau denselben Code wie ein frisch
    angepasstes.
    """

    def __init__(self, parameter, features):
        import numpy as np

        self.features = list(features)
        self.statistics_ = np.asarray(parameter["imputer"]["statistics"],
                                      dtype=float)
        self.mean_ = np.asarray(parameter["scaler"]["mean"], dtype=float)
        self.scale_ = np.asarray(parameter["scaler"]["scale"], dtype=float)
        self.intercept_ = float(parameter["regressor"]["intercept"])
        self.coef_ = np.asarray(parameter["regressor"]["coef"], dtype=float)
        self.named_steps = {"regressor": self}

        if (self.scale_ <= 0).any():
            raise ModelBundleError(
                "scaler.scale_ enthaelt einen nichtpositiven Wert - "
                "die Skalierung waere nicht umkehrbar")

    def predict(self, X):
        import numpy as np

        X = np.asarray(X, dtype=float)
        if X.ndim != 2 or X.shape[1] != len(self.features):
            raise ModelBundleError(
                f"Merkmalsmatrix hat die Form {X.shape}, erwartet werden "
                f"{len(self.features)} Spalten")

        # Dieselben drei Schritte wie die Pipeline, in derselben Folge.
        gefuellt = np.where(np.isnan(X), self.statistics_, X)
        skaliert = (gefuellt - self.mean_) / self.scale_
        return np.exp(self.intercept_ + skaliert @ self.coef_)

    def __repr__(self):                                  # pragma: no cover
        return f"LoadedModel(features={len(self.features)})"


# ---------------------------------------------------------------------------
# Integritaet und Kennung
# ---------------------------------------------------------------------------

def _kanonisch(objekt):
    return json.dumps(objekt, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def models_digest(models):
    """SHA-256 ueber die Modellbestandteile."""
    return hashlib.sha256(_kanonisch(models)).hexdigest()


def build_model_id(candidate, features, alpha, seasons, dataset_sha,
                   models_sha, evaluation_sha=None,
                   release_stage=DEFAULT_RELEASE_STAGE):
    """
    Eine deterministische Modellkennung.

    Ausdruecklich OHNE Zeitstempel: Zweimal dasselbe Training aus
    denselben Daten soll dieselbe Kennung ergeben. Sonst liesse sich
    nicht pruefen, ob zwei Bundles dasselbe Modell enthalten - und
    genau das ist die Frage, die eine Kennung beantworten soll.

    Evaluation und Freigabestufe gehen MIT ein (C0B). Zwei Bundles mit
    denselben Gewichten, aber verschiedenem Messergebnis oder
    verschiedener Freigabe sind fuer jeden praktischen Zweck
    verschiedene Artefakte - eine gemeinsame Kennung waere irrefuehrend.
    """
    roh = _kanonisch({
        "candidate": candidate,
        "features": list(features),
        "alpha": alpha,
        "seasons": sorted(seasons),
        "dataset_sha256": dataset_sha,
        "models_sha256": models_sha,
        "evaluation_sha256": evaluation_sha,
        "release_stage": release_stage,
        "schema_version": MODEL_SCHEMA_VERSION,
        "family": MODEL_FAMILY,
    })
    return f"clm-{hashlib.sha256(roh).hexdigest()[:16]}"


# ---------------------------------------------------------------------------
# Gebundene Evaluation
# ---------------------------------------------------------------------------

def evaluation_digest(evaluation):
    """
    Inhaltshash ueber das gesamte Evaluationsartefakt.

    Bewusst ueber ALLES, nicht nur die uebernommenen Kennzahlen: Wer
    einen Fold, eine Ausschlussregel oder die Bootstrap-Iterationen
    aendert, veraendert die Aussage der Messung - auch wenn die
    Aggregatzahl zufaellig gleich bliebe.
    """
    return hashlib.sha256(_kanonisch(evaluation)).hexdigest()


def _pflichtfeld(quelle, pfad):
    """Holt quelle["a"]["b"] und wirft mit lesbarem Pfad, wenn es fehlt."""
    wert = quelle
    for teil in pfad:
        if not isinstance(wert, dict) or teil not in wert:
            raise ModelBundleError(
                f"das Evaluationsartefakt hat kein Feld "
                f"{'.'.join(pfad)!r}", KIND_INCOMPATIBLE)
        wert = wert[teil]
    return wert


def evaluation_reference(evaluation, candidate, spalten, fingerprint):
    """
    Prueft ein Evaluationsartefakt und baut den Provenienzblock daraus.

    evaluation    das vollstaendige Ergebnis von
                  run_ml.py --evaluate-cl (bereits geladenes JSON).
    candidate     der Merkmalskandidat des Trainings.
    spalten       die Merkmalsspalten des Trainings, in Reihenfolge.
    fingerprint   der Datensatz-Fingerabdruck des Trainings.

    Es wird NICHTS uebernommen, was nicht im Artefakt steht, und nichts
    gebaut, dessen Grundlage nicht passt. Die drei harten Bedingungen:

        1. Es ist wirklich ein CL-Shadow-Backtest.
        2. Sein Datensatz-Fingerabdruck ist DERSELBE wie der des
           Trainings - inklusive Fassungsnummer. Sonst beschreiben
           Modell und Messung verschiedene Daten.
        3. Sein Merkmalsvertrag ist derselbe.

    Rueckgabe: der Block, der unter provenance.evaluation landet.
    """
    from src.ml import cl_evaluate as cle

    if not isinstance(evaluation, dict):
        raise ModelBundleError(
            "das Evaluationsartefakt ist kein Objekt", KIND_INCOMPATIBLE)

    aufgabe = _pflichtfeld(evaluation, ("configuration", "task"))
    if aufgabe != "cl_shadow_backtest":
        raise ModelBundleError(
            f"das Evaluationsartefakt beschreibt {aufgabe!r}, nicht den "
            f"CL-Shadow-Backtest", KIND_INCOMPATIBLE)

    eval_fp = _pflichtfeld(evaluation, ("manifest", "dataset_fingerprint"))
    for feld in ("sha256", "fingerprint_schema_version"):
        if eval_fp.get(feld) != fingerprint.get(feld):
            raise ModelBundleError(
                f"Datensatz-Fingerabdruck von Training und Auswertung "
                f"weichen ab ({feld}): Training "
                f"{str(fingerprint.get(feld))[:16]}, Auswertung "
                f"{str(eval_fp.get(feld))[:16]}", KIND_INCOMPATIBLE)

    eval_kandidat = _pflichtfeld(evaluation, ("configuration", "candidate"))
    if eval_kandidat != candidate:
        raise ModelBundleError(
            f"die Auswertung nutzte den Kandidaten {eval_kandidat!r}, das "
            f"Training {candidate!r}", KIND_INCOMPATIBLE)

    eval_spalten = _pflichtfeld(evaluation,
                                ("configuration", "feature_columns"))
    if list(eval_spalten) != list(spalten):
        raise ModelBundleError(
            "Merkmalsvertrag von Training und Auswertung weicht ab",
            KIND_INCOMPATIBLE)

    aggregat = _pflichtfeld(evaluation, ("results", "aggregate"))
    urteil = _pflichtfeld(evaluation, ("results", "verdict"))
    bootstrap = _pflichtfeld(evaluation,
                             ("results", "aggregate", "bootstrap"))
    folds = _pflichtfeld(evaluation, ("results", "folds"))

    def _kennzahlen(block):
        return {name: block.get(name)
                for name in ("log_loss", "brier", "rps", "calibration_error")}

    return {
        "source": "cl_shadow_backtest",
        "evaluation_sha256": evaluation_digest(evaluation),
        "evaluation_schema_version": _pflichtfeld(
            evaluation, ("manifest", "schema_version")),
        "cl_evaluate_schema_version": cle.SCHEMA_VERSION,
        "created_at": _pflichtfeld(evaluation, ("manifest", "created_at")),
        "dataset_fingerprint_sha256": eval_fp.get("sha256"),
        "fingerprint_schema_version": eval_fp.get("fingerprint_schema_version"),
        "candidate": eval_kandidat,
        "feature_columns": list(eval_spalten),
        "test_scope": evaluation["configuration"].get("test_scope"),
        "training_scope": evaluation["configuration"].get("training_scope"),
        "test_matches": aggregat.get("n"),
        "folds": [{"fold": f.get("fold"),
                   "train_seasons": f.get("train_seasons"),
                   "test_season": f.get("test_season"),
                   "test_rows": f.get("test_rows"),
                   "selected_candidate": f.get("selected_candidate"),
                   "delta_log_loss": f.get("delta_log_loss")}
                  for f in folds],
        "baseline_metrics": _kennzahlen(aggregat.get("baseline") or {}),
        "ml_metrics": _kennzahlen(aggregat.get("ml") or {}),
        "deltas": {"log_loss": aggregat.get("delta_log_loss"),
                   "brier": aggregat.get("delta_brier"),
                   "rps": aggregat.get("delta_rps")},
        "uncertainty": {
            metrik: {"point": (bootstrap.get(metrik) or {}).get("point"),
                     "ci_low": (bootstrap.get(metrik) or {}).get("ci_low"),
                     "ci_high": (bootstrap.get(metrik) or {}).get("ci_high"),
                     "iterations": (bootstrap.get(metrik) or {}).get("iterations"),
                     "seed": (bootstrap.get(metrik) or {}).get("seed")}
            for metrik in ("log_loss", "brier", "rps")
            if metrik in bootstrap},
        "verdict": urteil.get("verdict"),
        "verdict_reasons": urteil.get("reasons"),
        "meaning": "Diese Zahlen stammen aus genau der Messung, deren "
                   "Hash oben steht. Sie sind eine Herkunftsangabe, "
                   "kein Nachweis der Ueberlegenheit.",
    }


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def _pruefe_trainingsbestand(zeilen, spalten, seasons):
    """
    Die Guards vor dem Training - alle vor dem ersten fit().

    Ein Abbruch hier kostet Sekunden. Ein CL-Spiel, das unbemerkt ins
    Training rutscht, kostet die Aussagekraft jeder spaeteren Messung
    mit diesem Modell.
    """
    if not zeilen:
        raise ModelBundleError(
            f"keine Trainingszeilen fuer die Saisons {sorted(seasons)}")

    wettbewerbe = {z.get("league") for z in zeilen}
    if "cl" in wettbewerbe:
        anzahl = sum(1 for z in zeilen if z.get("league") == "cl")
        raise ModelBundleError(
            f"{anzahl} CL-Zeilen im Training - das Modell wuerde auf genau "
            f"den Partien lernen, gegen die es spaeter gemessen wird")

    fremde = {z.get("season") for z in zeilen} - set(seasons)
    if fremde:
        raise ModelBundleError(
            f"Zeilen aus nicht vorgesehenen Saisons im Training: "
            f"{sorted(fremde)}")

    if any(not z.get("evaluation_eligible") for z in zeilen):
        raise ModelBundleError(
            "nicht auswertbare Zeilen im Training - die Aufwaermphase "
            "misst die Anlaufzeit der Profile, nicht die Guete")

    fehlend = sorted({s for s in spalten
                      for z in zeilen if s not in z})
    if fehlend:
        raise ModelBundleError(
            f"Merkmalsspalten fehlen im Bestand: {fehlend[:5]}")


def _pruefe_merkmalsreihenfolge(spalten, candidate):
    """Die Reihenfolge ist Teil des Vertrags, nicht Zierde."""
    erwartet = fg.columns_for(candidate)
    if list(spalten) != erwartet:
        raise ModelBundleError(
            f"Merkmalsreihenfolge weicht ab: erwartet {len(erwartet)} "
            f"Spalten beginnend mit {erwartet[:2]}, erhalten "
            f"{len(spalten)} beginnend mit {list(spalten)[:2]}")


def train_cl_model(zeilen, evaluation, seasons=DEFAULT_TRAINING_SEASONS,
                   candidate=None, alphas=mdl.ALPHA_CANDIDATES,
                   dataset_fingerprint=None,
                   release_stage=DEFAULT_RELEASE_STAGE):
    """
    Trainiert das Modell und baut das Bundle im Speicher.

    Der Ablauf ist derselbe wie in cl_evaluate.evaluate_fold, nur ohne
    Testbestand: nationale Ligazeilen holen, innen zeitlich teilen,
    Alpha waehlen, dann auf ALLEN Trainingszeilen neu anpassen.

    Kein CL-Spiel geht in Training oder Alphawahl ein - beides wird
    geprueft und nicht angenommen.

    evaluation      PFLICHT (C0B). Das geladene Ergebnis von
                    run_ml.py --evaluate-cl. Ohne eine passende Messung
                    entsteht kein Bundle: Ein Artefakt, das keine
                    ueberpruefte Guete nennen kann, hat im Betrieb
                    nichts zu suchen.
    release_stage   eine der RELEASE_STAGES. Der Standard ist die
                    niedrigste Stufe.
    """
    from src.ml import cl_evaluate as cle

    if evaluation is None:
        raise ModelBundleError(
            "ohne Evaluationsartefakt entsteht kein Bundle - die "
            "Kennzahlen eines Modells duerfen nicht behauptet, sondern "
            "muessen gebunden werden", KIND_INCOMPATIBLE)

    release_stage = _pruefe_freigabestufe(release_stage)

    candidate = candidate or cle.CANDIDATE
    spalten = fg.columns_for(candidate)
    _pruefe_merkmalsreihenfolge(spalten, candidate)

    training = cle.league_rows(zeilen, list(seasons))
    _pruefe_trainingsbestand(training, spalten, seasons)

    fit_zeilen, val_zeilen, innen = ev.inner_split(
        training, {"train_seasons": sorted(seasons)})
    kandidat, _, wahl = ev.select_candidate(fit_zeilen, val_zeilen, spalten,
                                            alphas)

    if kandidat == mdl.NO_CORRECTION:
        raise ModelBundleError(
            "die innere Auswahl hat no_correction gewaehlt - kein Alpha "
            "schlaegt die Baseline auf der inneren Validierung. Ein Bundle "
            "waere ein Modell, das nach eigener Messung nicht angewandt "
            "werden sollte")

    modelle, diagnosen = {}, {}
    for seite in SIDES:
        pipeline, diagnose = mdl.fit_side(training, seite, kandidat, spalten)
        modelle[seite] = serialise_pipeline(pipeline, spalten)
        diagnosen[seite] = diagnose

    sha = models_digest(modelle)
    fingerprint = dataset_fingerprint or cle.dataset_fingerprint(zeilen)
    eval_ref = evaluation_reference(evaluation, candidate, spalten,
                                    fingerprint)

    return _baue_bundle(candidate, spalten, kandidat, alphas, seasons,
                        training, innen, wahl, modelle, diagnosen, sha,
                        fingerprint, eval_ref, release_stage)


def _pruefe_freigabestufe(stufe):
    """Genau eine der drei Stufen - alles andere wird abgewiesen."""
    if stufe not in RELEASE_STAGES:
        raise ModelBundleError(
            f"unbekannte Freigabestufe {stufe!r}. Erlaubt sind: "
            f"{', '.join(RELEASE_STAGES)}", KIND_INCOMPATIBLE)
    return stufe


#: Was eine Stufe im Betrieb bedeutet. Steht im Bundle, damit ein
#: spaeterer Leser die Regel nicht im Code suchen muss.
STAGE_NOTES = {
    STAGE_SHADOW:
        "Nur fuer Messungen im Schatten. Dieses Modell darf kein "
        "Nutzerergebnis veraendern; runtime.py weist die Anwendung ab.",
    STAGE_EXPERIMENTAL:
        "Darf unter dem ausdruecklichen FootSim-Produktvertrag aktiv "
        "wirken. Nicht statistisch abschliessend belegt - die "
        "gebundene Messung nennt Punktschaetzer und Intervall. Bei "
        "jedem Fehler greift die Baseline (V0).",
    STAGE_APPROVED:
        "Vollstaendig freigegebene Modellgeneration.",
}


def _baue_bundle(candidate, spalten, alpha, alphas, seasons, training,
                 innen, wahl, modelle, diagnosen, sha, fingerprint,
                 eval_ref, release_stage):
    import sklearn

    from run_backtests import git_arbeitsstand, git_commit
    from src.ml import cl_evaluate as cle
    from src.ml import dataset as ds

    stand = git_arbeitsstand()
    return {
        "schema_version": MODEL_SCHEMA_VERSION,
        "model_id": build_model_id(candidate, spalten, alpha, seasons,
                                   fingerprint["sha256"], sha,
                                   eval_ref["evaluation_sha256"],
                                   release_stage),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_family": MODEL_FAMILY,
        "candidate": candidate,
        "features": list(spalten),
        "feature_count": len(spalten),
        "alpha": alpha,
        "alpha_candidates": list(alphas),
        "training": {
            "scope": "national_leagues_only",
            "scope_note": "ausschliesslich auswertbare nationale "
                          "Ligazeilen - kein Champions-League-Spiel",
            "seasons": sorted(seasons),
            "rows": len(training),
            "leagues": sorted({z["league"] for z in training}),
            "competitions": sorted({z.get("competition")
                                    for z in training if z.get("competition")}),
            "inner_split": innen,
            "selection": wahl,
            "fit_diagnostics": diagnosen,
        },
        "models": modelle,
        "integrity": {
            "algorithm": "sha256",
            "models_sha256": sha,
            "covers": "der models-Block in kanonischer JSON-Form",
            "note": "schuetzt vor Beschaedigung und vertauschten Dateien, "
                    "nicht gegen einen Angreifer mit Schreibrecht",
        },
        "provenance": {
            "dataset_fingerprint": fingerprint,
            "dataset_schema_version": ds.SCHEMA_VERSION,
            "feature_groups_schema_version": fg.SCHEMA_VERSION,
            "evaluation_schema_version": ev.SCHEMA_VERSION,
            "cl_evaluate_schema_version": cle.SCHEMA_VERSION,
            "python_version": platform.python_version(),
            "sklearn_version": sklearn.__version__,
            "platform": platform.system(),
            "git_commit": git_commit(),
            "git_dirty": None if stand is None else stand["dirty"],
            "git_status": stand,
            # Gebunden, nicht behauptet. Die Zahlen hier stammen
            # ausschliesslich aus dem Artefakt, dessen Hash danebensteht.
            "evaluation": eval_ref,
        },
        "release_stage": release_stage,
        "release_stages": list(RELEASE_STAGES),
        "usage_note": STAGE_NOTES[release_stage],
    }


# ---------------------------------------------------------------------------
# Speichern - atomar
# ---------------------------------------------------------------------------

def save_bundle(bundle, pfad, force=False):
    """
    Schreibt das Bundle - erst danebenlegen, pruefen, dann ersetzen.

    Die Pruefung ist ein vollstaendiger load_bundle() auf die
    Temporaerdatei. Damit kann kein Bundle entstehen, das sich nicht
    laden laesst: Was hier ankommt, ist bereits einmal erfolgreich
    gelesen worden.

    Bei jedem Fehler wird die Temporaerdatei entfernt. Ein halbes
    Artefakt ist schlimmer als keines - es sieht aus wie ein ganzes.
    """
    if os.path.exists(pfad) and not force:
        raise ModelBundleError(
            f"{pfad} existiert bereits. Zum bewussten Ersetzen --force, "
            f"sonst anderen Pfad waehlen.")

    ordner = os.path.dirname(os.path.abspath(pfad))
    os.makedirs(ordner, exist_ok=True)
    temporaer = pfad + ".tmp"

    try:
        with open(temporaer, "w", encoding="utf-8") as datei:
            json.dump(bundle, datei, indent=2, ensure_ascii=False,
                      sort_keys=True)
            datei.write("\n")
        load_bundle(temporaer)          # der Beweis, dass es lesbar ist
        os.replace(temporaer, pfad)
    except BaseException:
        if os.path.exists(temporaer):
            os.remove(temporaer)
        raise

    return pfad


# ---------------------------------------------------------------------------
# Laden - streng
# ---------------------------------------------------------------------------

def _verlange(bedingung, meldung, kind=KIND_INVALID):
    if not bedingung:
        raise ModelBundleError(meldung, kind)


def _lies_freigabestufe(bundle, fassung):
    """
    Die Freigabestufe eines Bundles - fail-closed.

    Fassung 2 nennt sie ausdruecklich. Fassung 1 kannte sie nicht; dort
    stand stattdessen shadow_only/production_approved.

    ALTBESTAENDE WERDEN NIEMALS HOCHGESTUFT
    Ein Bundle der Fassung 1 kann bestenfalls "nur Schatten" gemeint
    haben - mehr gab sein Vertrag nicht her. Es wird deshalb als shadow
    gelesen, und zwar nur dann, wenn seine beiden alten Felder genau
    das aussagen. Jede andere Kombination ist unklar und wird
    abgewiesen, statt wohlwollend gedeutet zu werden.

    Ein Bundle der Fassung 2 darf die alten Felder nicht mehr tragen:
    Zwei Quellen fuer dieselbe Aussage laufen frueher oder spaeter
    auseinander, und dann gilt die falsche.
    """
    if fassung == 1:
        _verlange(bundle.get("shadow_only") is True
                  and bundle.get("production_approved") is False,
                  "Altbestand der Fassung 1 mit unklarem Freigabezustand "
                  f"(shadow_only={bundle.get('shadow_only')!r}, "
                  f"production_approved="
                  f"{bundle.get('production_approved')!r}) - er wird "
                  "nicht gedeutet", KIND_INCOMPATIBLE)
        _verlange("release_stage" not in bundle,
                  "Fassung 1 mit release_stage - widerspruechlicher "
                  "Vertrag", KIND_INCOMPATIBLE)
        return STAGE_SHADOW

    for alt in ("shadow_only", "production_approved"):
        _verlange(alt not in bundle,
                  f"Fassung {fassung} traegt noch das alte Feld {alt!r} - "
                  f"zwei Quellen fuer dieselbe Aussage", KIND_INCOMPATIBLE)

    stufe = bundle.get("release_stage")
    _verlange(stufe in RELEASE_STAGES,
              f"unbekannte Freigabestufe {stufe!r}. Erlaubt sind: "
              f"{', '.join(RELEASE_STAGES)}", KIND_INCOMPATIBLE)
    return stufe


def _pruefe_gebundene_evaluation(bundle, features):
    """
    Die Evaluation muss zum Bundle passen - sonst ist sie Zierde.

    Geprueft wird gegen den Fingerabdruck und den Merkmalsvertrag, die
    im selben Bundle stehen. Damit faellt eine nachtraeglich
    eingesetzte, fremde Messung auf, ohne dass die Datei daneben liegen
    muss.
    """
    herkunft = bundle.get("provenance") or {}
    messung = herkunft.get("evaluation")
    _verlange(isinstance(messung, dict) and messung,
              "die Herkunftsangabe 'evaluation' fehlt - dieses Bundle "
              "nennt keine ueberpruefbare Messung", KIND_INCOMPATIBLE)

    for pflicht in ("evaluation_sha256", "dataset_fingerprint_sha256",
                    "feature_columns", "test_matches", "verdict",
                    "baseline_metrics", "ml_metrics", "deltas"):
        _verlange(pflicht in messung,
                  f"die gebundene Evaluation nennt {pflicht!r} nicht",
                  KIND_INCOMPATIBLE)

    fingerprint = herkunft.get("dataset_fingerprint") or {}
    _verlange(messung["dataset_fingerprint_sha256"]
              == fingerprint.get("sha256"),
              "die gebundene Evaluation beschreibt einen anderen "
              "Datensatz als das Training", KIND_INCOMPATIBLE)
    _verlange(messung.get("fingerprint_schema_version")
              == fingerprint.get("fingerprint_schema_version"),
              "die gebundene Evaluation nutzt eine andere "
              "Fingerabdruckfassung als das Training", KIND_INCOMPATIBLE)
    _verlange(list(messung["feature_columns"]) == list(features),
              "die gebundene Evaluation nutzt einen anderen "
              "Merkmalsvertrag als das Modell", KIND_INCOMPATIBLE)
    _verlange(isinstance(messung["test_matches"], int)
              and messung["test_matches"] > 0,
              f"unbrauchbare Stichprobengroesse "
              f"{messung['test_matches']!r}", KIND_INCOMPATIBLE)
    return messung


def load_bundle(pfad, candidate=None, erwartete_features=None):
    """
    Laedt ein Bundle und prueft es vollstaendig, bevor es zurueckkommt.

    Geprueft wird der Reihe nach: Existenz, Lesbarkeit, Fassung,
    Familie, Kandidat, Merkmale nach Zahl UND Reihenfolge, beide
    Seiten, Integritaet, Trainingsumfang, Schattenkennzeichen. Erst
    danach werden die Modelle rekonstruiert.

    Der Grundsatz: Es wird ausschliesslich geladen, was FootSim selbst
    erzeugt hat. Ein Bundle aus fremder Quelle gehoert nicht hierher -
    auch wenn dieses Format beim Laden keinen Code ausfuehrt.

    Rueckgabe: (bundle, modelle) mit modelle = {"home": ..., "away": ...}.
    """
    from src.ml import cl_evaluate as cle

    _verlange(os.path.exists(pfad), f"Modellbundle nicht gefunden: {pfad}",
              KIND_MISSING)

    try:
        with open(pfad, encoding="utf-8") as datei:
            bundle = json.load(datei)
    except json.JSONDecodeError as fehler:
        raise ModelBundleError(f"{pfad} ist kein lesbares JSON: {fehler}",
                               KIND_INVALID)

    _verlange(isinstance(bundle, dict), f"{pfad} enthaelt kein Bundleobjekt")

    fassung = bundle.get("schema_version")
    _verlange(fassung in SUPPORTED_SCHEMA_VERSIONS,
              f"Bundlefassung {fassung!r} wird nicht unterstuetzt - "
              f"lesbar sind {SUPPORTED_SCHEMA_VERSIONS}", KIND_INCOMPATIBLE)

    familie = bundle.get("model_family")
    _verlange(familie == MODEL_FAMILY,
              f"unbekannte Modellfamilie {familie!r} - dieser Loader kann "
              f"nur {MODEL_FAMILY!r} rekonstruieren", KIND_INCOMPATIBLE)

    erwarteter_kandidat = candidate or cle.CANDIDATE
    _verlange(bundle.get("candidate") == erwarteter_kandidat,
              f"Kandidat {bundle.get('candidate')!r} passt nicht zum "
              f"erwarteten {erwarteter_kandidat!r}", KIND_INCOMPATIBLE)

    features = bundle.get("features")
    _verlange(isinstance(features, list) and features,
              "das Bundle nennt keine Merkmalsliste")

    soll = list(erwartete_features if erwartete_features is not None
                else fg.columns_for(erwarteter_kandidat))
    _verlange(len(features) == len(soll),
              f"{len(features)} Merkmale im Bundle, erwartet werden "
              f"{len(soll)}", KIND_INCOMPATIBLE)
    _verlange(features == soll,
              "Merkmalsnamen oder ihre Reihenfolge weichen ab: erste "
              f"Abweichung bei Position "
              f"{next((i for i, (a, b) in enumerate(zip(features, soll)) if a != b), 0)}",
              KIND_INCOMPATIBLE)
    _verlange(bundle.get("feature_count") == len(soll),
              f"feature_count {bundle.get('feature_count')!r} passt nicht "
              f"zur Merkmalsliste ({len(soll)})", KIND_INCOMPATIBLE)

    modelle_roh = bundle.get("models")
    _verlange(isinstance(modelle_roh, dict), "das Bundle enthaelt keine Modelle")
    for seite in SIDES:
        _verlange(seite in modelle_roh,
                  f"das Modell fuer die Seite {seite!r} fehlt")

    integritaet = bundle.get("integrity") or {}
    _verlange(integritaet.get("algorithm") == "sha256",
              f"unbekanntes Integritaetsverfahren "
              f"{integritaet.get('algorithm')!r}")
    gespeichert = integritaet.get("models_sha256")
    gerechnet = models_digest(modelle_roh)
    _verlange(gespeichert == gerechnet,
              f"Integritaetswert stimmt nicht: gespeichert "
              f"{str(gespeichert)[:16]}..., gerechnet {gerechnet[:16]}... - "
              f"das Bundle wurde veraendert oder ist beschaedigt")

    training = bundle.get("training") or {}
    _verlange(training.get("scope") == "national_leagues_only",
              f"unerwarteter Trainingsumfang {training.get('scope')!r}")
    _verlange("cl" not in (training.get("leagues") or []),
              "das Bundle nennt CL im Trainingsumfang")
    _verlange((training.get("rows") or 0) > 0,
              "das Bundle nennt keine Trainingszeilen")
    _verlange(training.get("seasons"), "das Bundle nennt keine Trainingssaisons")

    # Freigabestufe. Der Loader stellt sie nur fest; ob sie den aktiven
    # Betrieb deckt, entscheidet runtime.py - dort steht der
    # Betriebszusammenhang.
    stufe = _lies_freigabestufe(bundle, fassung)
    bundle["release_stage"] = stufe

    herkunft = bundle.get("provenance") or {}
    for pflicht in ("dataset_fingerprint", "dataset_schema_version",
                    "python_version", "git_commit"):
        _verlange(pflicht in herkunft,
                  f"die Herkunftsangabe {pflicht!r} fehlt")

    # Die gebundene Messung gilt ab Fassung 2. Ein Altbestand kennt sie
    # nicht - er steht dafuer auf shadow und veraendert nichts.
    if fassung >= 2:
        _pruefe_gebundene_evaluation(bundle, features)

    alpha = bundle.get("alpha")
    _verlange(isinstance(alpha, (int, float)) and alpha > 0,
              f"unbrauchbares Alpha: {alpha!r}")

    modelle = {seite: LoadedModel(modelle_roh[seite], features)
               for seite in SIDES}
    return bundle, modelle
