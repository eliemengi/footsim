"""
Versionierte Persistenz des Champions-League-Schattenmodells.

WAS HIER ENTSTEHT - UND WAS AUSDRUECKLICH NICHT
-----------------------------------------------
Ein reproduzierbarer Trainingspfad und ein nachpruefbares Artefakt.
Kein aktiviertes Modell, keine Vorhersagefunktion fuer den produktiven
Pfad, keine Freigabe. Jedes Bundle traegt shadow_only = true und
production_approved = false, und der Loader verweigert die Arbeit,
sobald eines davon anders lautet.

Der Anlass ist ehrlich zu benennen: C3 hat die Uebertragung auf die
Champions League gemessen und ist zu INCONCLUSIVE gekommen
(delta LogLoss -0,00890, Intervall [-0,02986, +0,01135] ueber 213
Spiele). Dieses Modul baut die Infrastruktur, nicht den Beleg. Das
C3-Urteil steht deshalb in jedem Bundle - als Herkunftsangabe, nicht
als Erfolgsmeldung.

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

#: Fassung des Bundleformats. Der Loader lehnt jede andere ab.
MODEL_SCHEMA_VERSION = 1

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


class ModelBundleError(Exception):
    """Ein Bundle ist unbrauchbar - beschaedigt, fremd oder unpassend."""


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
                   models_sha):
    """
    Eine deterministische Modellkennung.

    Ausdruecklich OHNE Zeitstempel: Zweimal dasselbe Training aus
    denselben Daten soll dieselbe Kennung ergeben. Sonst liesse sich
    nicht pruefen, ob zwei Bundles dasselbe Modell enthalten - und
    genau das ist die Frage, die eine Kennung beantworten soll.
    """
    roh = _kanonisch({
        "candidate": candidate,
        "features": list(features),
        "alpha": alpha,
        "seasons": sorted(seasons),
        "dataset_sha256": dataset_sha,
        "models_sha256": models_sha,
        "schema_version": MODEL_SCHEMA_VERSION,
        "family": MODEL_FAMILY,
    })
    return f"clm-{hashlib.sha256(roh).hexdigest()[:16]}"


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


def train_cl_model(zeilen, seasons=DEFAULT_TRAINING_SEASONS,
                   candidate=None, alphas=mdl.ALPHA_CANDIDATES,
                   dataset_fingerprint=None):
    """
    Traineirt das Schattenmodell und baut das Bundle im Speicher.

    Der Ablauf ist derselbe wie in cl_evaluate.evaluate_fold, nur ohne
    Testbestand: nationale Ligazeilen holen, innen zeitlich teilen,
    Alpha waehlen, dann auf ALLEN Trainingszeilen neu anpassen.

    Kein CL-Spiel geht in Training oder Alphawahl ein - beides wird
    geprueft und nicht angenommen.
    """
    from src.ml import cl_evaluate as cle

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

    return _baue_bundle(candidate, spalten, kandidat, alphas, seasons,
                        training, innen, wahl, modelle, diagnosen, sha,
                        fingerprint)


def _baue_bundle(candidate, spalten, alpha, alphas, seasons, training,
                 innen, wahl, modelle, diagnosen, sha, fingerprint):
    import sklearn

    from run_backtests import git_arbeitsstand, git_commit
    from src.ml import cl_evaluate as cle
    from src.ml import dataset as ds

    stand = git_arbeitsstand()
    return {
        "schema_version": MODEL_SCHEMA_VERSION,
        "model_id": build_model_id(candidate, spalten, alpha, seasons,
                                   fingerprint["sha256"], sha),
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
            "c3_verdict": {
                "verdict": "INCONCLUSIVE",
                "delta_log_loss": -0.00890,
                "ci_95": [-0.02986, 0.01135],
                "test_matches": 213,
                "meaning": "Punktschaetzer besser, Intervall enthaelt die "
                           "Null. Dies ist eine Herkunftsangabe, KEIN "
                           "Nachweis der Ueberlegenheit.",
            },
        },
        "shadow_only": True,
        "production_approved": False,
        "usage_note": "Nur fuer Messungen im Schatten. Keine Freigabe fuer "
                      "Nutzerprognosen; C3 konnte die Uebertragung auf die "
                      "Champions League nicht belegen.",
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

def _verlange(bedingung, meldung):
    if not bedingung:
        raise ModelBundleError(meldung)


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

    _verlange(os.path.exists(pfad), f"Modellbundle nicht gefunden: {pfad}")

    try:
        with open(pfad, encoding="utf-8") as datei:
            bundle = json.load(datei)
    except json.JSONDecodeError as fehler:
        raise ModelBundleError(f"{pfad} ist kein lesbares JSON: {fehler}")

    _verlange(isinstance(bundle, dict), f"{pfad} enthaelt kein Bundleobjekt")

    fassung = bundle.get("schema_version")
    _verlange(fassung == MODEL_SCHEMA_VERSION,
              f"Bundlefassung {fassung!r} wird nicht unterstuetzt - "
              f"erwartet {MODEL_SCHEMA_VERSION}")

    familie = bundle.get("model_family")
    _verlange(familie == MODEL_FAMILY,
              f"unbekannte Modellfamilie {familie!r} - dieser Loader kann "
              f"nur {MODEL_FAMILY!r} rekonstruieren")

    erwarteter_kandidat = candidate or cle.CANDIDATE
    _verlange(bundle.get("candidate") == erwarteter_kandidat,
              f"Kandidat {bundle.get('candidate')!r} passt nicht zum "
              f"erwarteten {erwarteter_kandidat!r}")

    features = bundle.get("features")
    _verlange(isinstance(features, list) and features,
              "das Bundle nennt keine Merkmalsliste")

    soll = list(erwartete_features if erwartete_features is not None
                else fg.columns_for(erwarteter_kandidat))
    _verlange(len(features) == len(soll),
              f"{len(features)} Merkmale im Bundle, erwartet werden "
              f"{len(soll)}")
    _verlange(features == soll,
              "Merkmalsnamen oder ihre Reihenfolge weichen ab: erste "
              f"Abweichung bei Position "
              f"{next((i for i, (a, b) in enumerate(zip(features, soll)) if a != b), 0)}")
    _verlange(bundle.get("feature_count") == len(soll),
              f"feature_count {bundle.get('feature_count')!r} passt nicht "
              f"zur Merkmalsliste ({len(soll)})")

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

    _verlange(bundle.get("shadow_only") is True,
              "shadow_only ist nicht true - dieses Bundle behauptet einen "
              "anderen Status, als dieser Stand rechtfertigt")
    _verlange(bundle.get("production_approved") is False,
              "production_approved ist nicht false - fuer die Champions "
              "League liegt keine Freigabe vor")

    herkunft = bundle.get("provenance") or {}
    for pflicht in ("dataset_fingerprint", "dataset_schema_version",
                    "python_version", "git_commit", "c3_verdict"):
        _verlange(pflicht in herkunft,
                  f"die Herkunftsangabe {pflicht!r} fehlt")

    alpha = bundle.get("alpha")
    _verlange(isinstance(alpha, (int, float)) and alpha > 0,
              f"unbrauchbares Alpha: {alpha!r}")

    modelle = {seite: LoadedModel(modelle_roh[seite], features)
               for seite in SIDES}
    return bundle, modelle
