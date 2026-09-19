"""
V2-C22: Referenzartefakt und numerische Aequivalenz im Freigabeweg.

WARUM ES DIESES MODUL GIBT
--------------------------
Der Freigabeweg baut jedes Modell neu und verlangte bis hierher, dass
der Neubau BITGLEICH mit dem gemessenen und gespeicherten Modell ist:
dieselbe Modell-ID. Die Modell-ID hasht die angepassten Koeffizienten in
voller Gleitkommagenauigkeit.

Nachgemessen ist das auf einer anderen Plattform unerreichbar, ohne dass
sich am Modell etwas aendert:

  - Die C-Bibliothek liefert fuer dasselbe Argument ein um eine Einheit
    der letzten Stelle anderes exp(): Windows UCRT gegen Linux glibc,
    rund 0,4 Prozent der Werte der Poisson-Zielfunktion.
  - Der CPU-abhaengige OpenBLAS-Kern allein aendert die Modell-ID, auf
    Windows wie auf Linux (erzwungener Sandybridge-Kern).
  - L-BFGS verstaerkt diese Unterschiede der letzten Stelle zu relativen
    Koeffizientenabweichungen von hoechstens 5,8e-11. Die Lambdas
    unterscheiden sich um hoechstens 2,4e-14. Echt verschiedene Modelle
    (Nachbar-Alpha, anderer Trainingsumfang) liegen bei 1,5 bis 5,0.

DER VERTRAG
-----------
1. Das gespeicherte, per SHA-256 gepinnte Bundle bleibt das Artefakt.
   Ein Neubau wird nie geschrieben, registriert oder aktiviert, wenn er
   nicht bitgleich ist - er ist ein Nachweis, kein Ersatz.
2. Bitgleich zuerst. Der bisherige Weg bleibt unveraendert der
   staerkste.
3. Nicht bitgleich: Aequivalenz NUR, wenn jedes Struktur- und
   Definitionsfeld exakt gleich ist, ausschliesslich die ausdruecklich
   genannten Zahlenfelder innerhalb der eingefrorenen Toleranz liegen,
   beide Modell-IDs aus ihrem eigenen Inhalt nachrechenbar sind und die
   Lambdas auf der eingefrorenen Referenzpopulation innerhalb der
   Toleranz liegen.
4. Sonst wird verweigert - wie bisher.

Die Toleranzen stehen AUSSCHLIESSLICH in `contract()`. Das eingefrorene
Vertragsartefakt muss ihm gleichen (`dependency_findings`); abgeleitet
aus dem zu pruefenden Neubau wird nichts.

Die Referenzumgebung steht im Vertrag als Nachweis, und die Tests
verlangen dort den bitgleichen Weg. Eine Freigabeentscheidung haengt an
ihr nicht: Entschieden wird ausschliesslich ueber den Vergleich der
Modelle, nie ueber Betriebssystem oder Prozessor.
"""

import datetime as _dt
import hashlib
import json
import math
import os
import re

CONTRACT_VERSION = "v2-c22.1"
CONTRACT_PATH = "data/ml/c22_release_equivalence_contract.json"
FOLD_REFERENCE_PATH = "data/ml/c22_fold_reference_bundles.json"

CONTRACT_ARTIFACT = "v2-c22 release equivalence contract"
FOLD_REFERENCE_ARTIFACT = "v2-c22 fold reference bundles"

MODE_EXACT = "exact"
MODE_EQUIVALENT = "equivalent"
MODE_REFUSED = "refused"

KLASSE_BAUMETADATEN = "build_metadata"
KLASSE_KENNUNG = "derived_identity"
KLASSE_PARAMETER = "parameters"
KLASSE_AUSWAHL = "selection_evidence"
KLASSE_STRUKTUR = "structural"


def _stabil(block):
    text = json.dumps(block, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normiert(objekt):
    """So, wie `persist.save_bundle` es schreiben wuerde (wie
    `c16_release.bundle_mismatch`): Tupel werden Listen."""
    return json.loads(json.dumps(objekt, sort_keys=True, ensure_ascii=False,
                                 default=str))


# ---------------------------------------------------------------------------
# Der Vertrag
# ---------------------------------------------------------------------------

def contract():
    """
    Der eingefrorene Aequivalenzvertrag. Nur Regeln und Belege, die VOR
    der plattformuebergreifenden Pruefung feststanden - kein Messwert
    eines zu pruefenden Neubaus.
    """
    from src.ml import c16_release as rel

    return {
        "purpose": (
            "Ein Neubau, der wegen der numerischen Umgebung (exp der "
            "C-Bibliothek, CPU-abhaengiger BLAS-Kern) nicht bitgleich "
            "entsteht, bestaetigt das gespeicherte Referenzartefakt nur "
            "dann, wenn er strukturell identisch und numerisch innerhalb "
            "dieser eingefrorenen Toleranz aequivalent ist. Das "
            "gespeicherte Artefakt bleibt das Artefakt."),
        "scope": {
            "candidate": "c16_release.release - das finale Bundle",
            "folds": ("c21_season_validation.release_evidence - die "
                      "C21-Foldmodelle"),
        },
        "reference_artifacts": {
            "candidate": {
                "model_id": "clm-936ecce472696ccb-ls1c4f4e1d",
                "path": "data/ml/models/clm-936ecce472696ccb-ls1c4f4e1d.json",
                "file_sha256": ("9f2caf3a38e3385194e48311406844204e85a97e"
                                "66ee1ef9c8ca949ab1f62479"),
                "lineage": ("gleicher Kandidat und gleiche gebundene "
                            "Evaluation (provenance/evaluation/"
                            "evaluation_sha256)"),
            },
            "folds": {
                "path": FOLD_REFERENCE_PATH,
                "measured_ids": {
                    "2024": "clm-be8db299253605dc-ls085040dc",
                    "2025": "clm-664cc4f2959fea76-ls0743a761",
                },
                "source_of_ids": ("data/ml/c21_season_validation.json, "
                                  "binding.<saison>.model_id"),
                "verification": (
                    "Jede Foldreferenz ist der Neubau des gemessenen "
                    "Foldmodells in der Referenzumgebung. Ihre aus dem "
                    "eigenen Inhalt nachgerechnete Modell-ID muss der "
                    "C21-Bindung gleichen - eine veraenderte Referenz "
                    "faellt damit kryptographisch auf."),
            },
        },
        "comparison_order": [MODE_EXACT, MODE_EQUIVALENT],
        "exact_rule": ("Bitgleich heisst: ausserhalb der Baumetadaten "
                       "weicht kein Feld ab."),
        "tolerance_rule": ("|a - b| <= atol + rtol * max(|a|, |b|); beide "
                           "Werte endliche Zahlen, kein Wahrheitswert"),
        "tolerances": {
            KLASSE_PARAMETER: {
                "rtol": 1e-8,
                "atol": 1e-9,
                "paths": [
                    r"^models/(home|away)/regressor/coef\[\d+\]$",
                    r"^models/(home|away)/regressor/intercept$",
                    r"^league_strength/(attack|defence)/[^/\[\]]+$",
                ],
            },
            KLASSE_AUSWAHL: {
                "rtol": 1e-8,
                "atol": 1e-9,
                "paths": [
                    r"^training/selection/baseline_inner_log_loss$",
                    r"^training/selection/selected_inner_log_loss$",
                    r"^training/selection/candidates\[\d+\]/inner_log_loss$",
                    (r"^league_strength/selection/(alpha|gamma)/"
                     r"candidates\[\d+\]/validation_deviance$"),
                ],
                "note": ("Messwerte der Auswahl, dieselbe Anpassung wie die "
                         "Koeffizienten. Die GEWAEHLTEN Werte (selected, "
                         "alpha, gamma) sind Strukturfelder und bleiben "
                         "exakt."),
            },
            "predictions": {
                "rtol": 1e-8,
                "atol": 1e-12,
                "quantities": ["base_lambda_home", "base_lambda_away",
                               "final_lambda_home", "final_lambda_away"],
            },
        },
        "derived_identity_fields": ["model_id", "integrity/models_sha256"],
        "derived_identity_rule": (
            "Duerfen abweichen, aber nur, wenn beide Seiten aus ihrem "
            "eigenen Inhalt nachrechenbar sind: Modell-ID ueber "
            "persist.build_model_id und die zweite Stufe, models_sha256 "
            "ueber persist.models_digest."),
        "build_metadata_fields": list(rel.BUILD_METADATA_FIELDS),
        "exact_numeric_fields": {
            "paths": ["models/<seite>/imputer/statistics",
                      "models/<seite>/scaler/mean",
                      "models/<seite>/scaler/scale"],
            "reason": ("Median, Mittelwert und Streuung sind feste "
                       "Reduktionen ohne Optimierer; plattformuebergreifend "
                       "nachgemessen bitgleich. Sie bleiben exakt."),
        },
        "structural_rule": (
            "Jedes Feld, das weder Baumetadatum noch abgeleitete Kennung "
            "noch ausdruecklich toleriertes Zahlenfeld ist, muss exakt "
            "gleich sein - Merkmale und ihre Reihenfolge, Saisons, "
            "Kandidat, Alpha, Gamma, Ligakarte, Vertragsbindungen, "
            "Datensatz- und Evaluationsfingerabdruck, Foldteilung, "
            "Schema, Familie, Freigabestufe. Fehlende oder zusaetzliche "
            "Schluessel und Listen anderer Laenge sind Strukturabweichungen."),
        "reference_population": {
            "definition": ("CL-Testzeilen der aeusseren Folds "
                           "(cl_evaluate.OUTER_FOLDS, test_season), "
                           "evaluation_eligible, sortiert nach (date, row_id) "
                           "- dieselben Partien, auf denen C20 gemessen hat"),
            "rows": 283,
            "path": ("Evaluationsweg: evaluate.predict_lambdas, danach "
                     "league_strength.apply_factors mit der Karte des "
                     "jeweiligen Bundles - fuer Referenz und Neubau im "
                     "selben Prozess"),
        },
        "authoritative_artifact_rule": (
            "Nach bestandener Aequivalenz wird das gespeicherte Bundle "
            "registriert und benutzt, nie der Neubau. Fehlt das "
            "gespeicherte Artefakt oder stimmt sein SHA-256 nicht, wird "
            "verweigert; ein nicht bitgleicher Neubau ersetzt es nicht."),
        "negative_controls": [
            "Koeffizient um mindestens 1e-6 verschoben",
            "Achsenabschnitt um mindestens 1e-6 verschoben",
            "anderes Alpha (0.01 statt 0.1)",
            "andere Merkmalsreihenfolge",
            "ein geaenderter Merkmalsname",
            "geaenderte Trainingssaison",
            "geaenderter Datensatzfingerabdruck",
            "geaenderter Vertragsfingerabdruck",
            "geaenderte Vereins-Liga-Karte",
            "andere Foldteilung",
            "geaendertes Gamma",
            "spuerbar andere Vorhersage",
            "falscher SHA-256 des gespeicherten Bundles",
        ],
        "evidence_basis": {
            "observed_platform_noise": {
                "fitted_coefficients_max_relative": 5.8e-11,
                "final_model_coefficients_max_relative": 6.3e-12,
                "lambda_max_relative": 2.4e-14,
                "environments": [
                    "Windows UCRT + OpenBLAS Zen (Referenz)",
                    "Linux glibc + OpenBLAS Zen",
                    "Linux glibc + OpenBLAS Sandybridge (erzwungen)",
                    "Windows UCRT + OpenBLAS Sandybridge (erzwungen)",
                    "GitHub Actions ubuntu-latest",
                ],
            },
            "genuinely_different_models_min_relative": 1.5,
            "stored_quantisation": {
                "league_strength_attack_defence": 1e-10,
                "note": ("gerundet auf 10 Stellen; ein Plattformunterschied "
                         "kann die letzte Stelle kippen. atol 1e-9 deckt "
                         "das zehnfach."),
            },
            "margins": (
                "rtol 1e-8 liegt 170-fach ueber dem beobachteten "
                "Koeffizientenrauschen und 400000-fach ueber dem der "
                "Lambdas. Ein um 1e-6 verschobener Koeffizient "
                "(|Wert| <= 0,5) liegt mindestens 160-fach darueber, "
                "ein echt anderes Modell 8 Groessenordnungen. Die "
                "Vorhersagetoleranz 1e-8 liegt 50-fach ueber dem Einfluss "
                "zweier gekippter Ligaparameter (<= 2e-10 relativ)."),
        },
        "reference_environment": {
            "role": ("nur Nachweis und Teststrenge: dort muss der Neubau "
                     "bitgleich sein. Keine Freigabeentscheidung haengt "
                     "daran."),
            "system": "Windows",
            "machine": "AMD64",
            "c_library": "MSVC UCRT",
            "cpu": "AMD Ryzen 5 3500U (Zen+)",
            "numpy": "2.0.2",
            "scipy": "1.13.1",
            "scikit_learn": "1.6.1",
            "blas": [["openblas", "0.3.27", "Zen"]],
        },
    }


def contract_fingerprint():
    return _stabil(contract())


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def _lesen(wurzel, relativ):
    pfad = os.path.join(wurzel, relativ)
    if not os.path.isfile(pfad):
        return None, "fehlt: %s" % relativ
    try:
        with open(pfad, encoding="utf-8") as datei:
            return json.load(datei), None
    except (OSError, ValueError):
        return None, "ist unlesbar: %s" % relativ


def write_json(relativ, dokument, repo_root=None):
    """Atomar schreiben, nie ueberschreiben (wie C20 und C21)."""
    ziel = os.path.join(repo_root or _repo_root(), relativ)
    if os.path.exists(ziel):
        raise FileExistsError("%s existiert bereits" % relativ)
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    tmp = ziel + ".tmp"
    with open(tmp, "w", encoding="utf-8") as datei:
        json.dump(dokument, datei, ensure_ascii=False, indent=1,
                  sort_keys=True, default=str)
        datei.write("\n")
    os.replace(tmp, ziel)
    return ziel


def _jetzt():
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def build_contract_artifact():
    from src.ml import c19_league_map as c19

    return {
        "artifact": CONTRACT_ARTIFACT,
        "schema_version": CONTRACT_VERSION,
        "created_at": _jetzt(),
        "git_commit": c19._git(),
        "contract": contract(),
        "contract_fingerprint": contract_fingerprint(),
        "frozen_before_measurement": True,
        "fingerprint_excludes": ["created_at", "git_commit"],
    }


# ---------------------------------------------------------------------------
# Numerische Umgebung - Nachweis, keine Entscheidung
# ---------------------------------------------------------------------------

def numerical_environment():
    """Was die letzte Gleitkommastelle eines Neubaus bestimmt."""
    import platform

    import numpy
    import scipy
    import sklearn
    from threadpoolctl import threadpool_info

    blas = sorted({(t.get("internal_api"), t.get("version"),
                    t.get("architecture"))
                   for t in threadpool_info() if t.get("user_api") == "blas"},
                  key=lambda t: tuple(str(x) for x in t))
    bibliothek = ("MSVC UCRT" if platform.system() == "Windows"
                  else " ".join(x for x in platform.libc_ver() if x) or "?")
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "c_library": bibliothek,
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "scipy": scipy.__version__,
        "scikit_learn": sklearn.__version__,
        "blas": [list(t) for t in blas],
    }


def is_reference_environment(umgebung=None):
    """
    Laeuft dieser Prozess in der Referenzumgebung des Vertrags?

    NUR fuer die Teststrenge: Dort muss der Neubau bitgleich sein, die
    Aequivalenz waere ein Rueckschritt. Kein Freigabeweg fragt das ab.
    """
    umgebung = umgebung or numerical_environment()
    referenz = contract()["reference_environment"]
    return all(umgebung.get(k) == referenz[k]
               for k in ("system", "machine", "c_library", "numpy", "scipy",
                         "scikit_learn", "blas"))


# ---------------------------------------------------------------------------
# Kennung aus dem Inhalt
# ---------------------------------------------------------------------------

def recompute_model_id(bundle):
    """
    Die Modell-ID aus dem Inhalt eines Bundles - dieselbe Rechnung wie
    beim Bau (`persist.build_model_id`, zweite Stufe `c16_release`).
    """
    from src.ml import c16_release as rel
    from src.ml import persist as ps

    b = _normiert(bundle)
    basis = ps.build_model_id(
        b["candidate"], b["features"], b["alpha"], b["training"]["seasons"],
        b["provenance"]["dataset_fingerprint"]["sha256"],
        ps.models_digest(b["models"]),
        b["provenance"]["evaluation"]["evaluation_sha256"],
        b["release_stage"])
    if "league_strength" in b:
        return "%s-ls%s" % (basis, rel._stabil_kurz(b["league_strength"]))
    return basis


def identity_findings(bundle, bezeichnung):
    """Traegt ein Bundle die Kennungen, die sein Inhalt ergibt?"""
    from src.ml import persist as ps

    b = _normiert(bundle)
    try:
        gerechnet = recompute_model_id(b)
        digest = ps.models_digest(b["models"])
    except (KeyError, TypeError, ValueError) as fehler:
        return ["%s: die Kennung ist aus dem Inhalt nicht nachrechenbar "
                "(%s fehlt oder ist unbrauchbar)" % (bezeichnung, fehler)]
    befunde = []
    if gerechnet != b.get("model_id"):
        befunde.append("%s: die Modell-ID %s passt nicht zum Inhalt (%s)"
                       % (bezeichnung, b.get("model_id"), gerechnet))
    if digest != (b.get("integrity") or {}).get("models_sha256"):
        befunde.append("%s: models_sha256 passt nicht zu den Modellen"
                       % bezeichnung)
    return befunde


# ---------------------------------------------------------------------------
# Der Vergleich
# ---------------------------------------------------------------------------

def _abweichungen(a, b, pfad=""):
    """
    (Pfad, Wert A, Wert B) fuer jede Abweichung - dieselben Pfade wie
    `c16_release.differing_fields`, nur mit den Werten.
    """
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            unter = "%s/%s" % (pfad, k) if pfad else k
            if k not in a or k not in b:
                yield unter, a.get(k), b.get(k)
            else:
                yield from _abweichungen(a[k], b[k], unter)
        return
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            yield pfad, a, b
            return
        for i, (x, y) in enumerate(zip(a, b)):
            yield from _abweichungen(x, y, "%s[%d]" % (pfad, i))
        return
    if a != b:
        yield pfad, a, b


def _zahl(wert):
    return (isinstance(wert, (int, float)) and not isinstance(wert, bool)
            and math.isfinite(wert))


def _innerhalb(a, b, rtol, atol):
    return abs(a - b) <= atol + rtol * max(abs(a), abs(b))


def _relativ(a, b):
    groesser = max(abs(a), abs(b))
    return 0.0 if groesser == 0 else abs(a - b) / groesser


def classify_path(pfad, vertrag=None):
    """Welche Regel gilt fuer einen abweichenden Pfad?"""
    from src.ml import c16_release as rel

    vertrag = vertrag or contract()
    if rel.is_build_metadata(pfad):
        return KLASSE_BAUMETADATEN
    if pfad in vertrag["derived_identity_fields"]:
        return KLASSE_KENNUNG
    for klasse in (KLASSE_PARAMETER, KLASSE_AUSWAHL):
        if any(re.match(m, pfad)
               for m in vertrag["tolerances"][klasse]["paths"]):
            return klasse
    return KLASSE_STRUKTUR


def classify_differences(referenz, neubau, praefix="", vertrag=None):
    """
    Jede Abweichung zweier (Teil-)Dokumente, nach der Regel ihres Pfads.

    `praefix` ist der Pfad des Teildokuments im Bundle, damit dieselben
    Regeln gelten wie beim Vergleich ganzer Bundles.
    """
    vertrag = vertrag or contract()
    bericht = {"differing_fields": [], KLASSE_BAUMETADATEN: [],
               KLASSE_KENNUNG: [], "tolerated_fields": [],
               "numerical_mismatches": [], "structural_mismatches": [],
               "max_abs_difference": 0.0, "max_rel_difference": 0.0}
    for pfad, a, b in _abweichungen(_normiert(referenz), _normiert(neubau),
                                    praefix):
        bericht["differing_fields"].append(pfad)
        klasse = classify_path(pfad, vertrag)
        if klasse in (KLASSE_BAUMETADATEN, KLASSE_KENNUNG):
            bericht[klasse].append(pfad)
            continue
        if klasse == KLASSE_STRUKTUR or not (_zahl(a) and _zahl(b)):
            bericht["structural_mismatches"].append(pfad)
            continue
        grenze = vertrag["tolerances"][klasse]
        bericht["max_abs_difference"] = max(bericht["max_abs_difference"],
                                            abs(a - b))
        bericht["max_rel_difference"] = max(bericht["max_rel_difference"],
                                            _relativ(a, b))
        if _innerhalb(a, b, grenze["rtol"], grenze["atol"]):
            bericht["tolerated_fields"].append(pfad)
        else:
            bericht["numerical_mismatches"].append(
                "%s (%r gegen %r)" % (pfad, a, b))
    return bericht


def reference_population(zeilen):
    """Die eingefrorene Referenzpopulation aus dem vollen Datensatz."""
    from src.ml import cl_evaluate as ce

    return [z for fold in ce.OUTER_FOLDS
            for z in ce.cl_rows(zeilen, fold["test_season"])]


def bundle_lambdas(bundle, zeilen):
    """
    Die Lambdas eines Bundles auf dem Evaluationsweg: erste Stufe, dann
    Ligastaerke mit der Karte DIESES Bundles.

    Rueckgabe: (basis, final), je eine Liste von (home, away).
    """
    from src.features import league_strength as ls
    from src.ml import evaluate as ev
    from src.ml import persist as ps

    b = _normiert(bundle)
    merkmale = list(b["features"])
    modelle = {seite: ps.LoadedModel(b["models"][seite], merkmale)
               for seite in ("home", "away")}
    basis, _ = ev.predict_lambdas(b["alpha"], modelle, zeilen, merkmale)
    stufe = b.get("league_strength")
    if not stufe:
        return basis, basis
    karte = {int(k): v for k, v in stufe["team_leagues"].items()}
    final, _ = ls.apply_factors(
        ls.LeagueStrength(stufe["attack"], stufe["defence"],
                          gamma=stufe["gamma"]), zeilen, basis, karte)
    return basis, final


def compare_predictions(referenz, neubau, zeilen, vertrag=None,
                        stufen=("base", "final")):
    """
    Die Lambdas beider Bundles auf denselben Partien.

    `stufen`: "base" (erste Stufe) und/oder "final" (mit Ligastaerke).
    Nur "base" dient dem Vergleich zweier Bundles, deren Ligakarte sich
    gewollt unterscheidet (C19 gegen den Vorgaenger).
    """
    vertrag = vertrag or contract()
    grenze = vertrag["tolerances"]["predictions"]
    ref_basis, ref_final = bundle_lambdas(referenz, zeilen)
    neu_basis, neu_final = bundle_lambdas(neubau, zeilen)
    paare = {"base": (ref_basis, neu_basis), "final": (ref_final, neu_final)}
    bericht = {"rows": len(zeilen), "within_tolerance": True,
               "max_abs_difference": 0.0, "max_rel_difference": 0.0,
               "violations": 0, "stages": list(stufen)}
    for alt, neu in (paare[s] for s in stufen):
        for (ah, aa), (nh, na) in zip(alt, neu):
            for a, b in ((ah, nh), (aa, na)):
                bericht["max_abs_difference"] = max(
                    bericht["max_abs_difference"], abs(a - b))
                bericht["max_rel_difference"] = max(
                    bericht["max_rel_difference"], _relativ(a, b))
                if not (_zahl(a) and _zahl(b)
                        and _innerhalb(a, b, grenze["rtol"], grenze["atol"])):
                    bericht["violations"] += 1
    bericht["within_tolerance"] = bericht["violations"] == 0
    return bericht


def compare_bundles(referenz, neubau, zeilen=None):
    """
    Referenzartefakt gegen Neubau. Bitgleich zuerst, dann Aequivalenz.

    `zeilen` ist der volle Datensatz; die Referenzpopulation wird daraus
    gebildet. Ohne ihn gibt es keinen Aequivalenznachweis.

    Rueckgabe: ein Bericht mit `exact`, `equivalent`, `mode`, `reason`,
    allen Abweichungen nach Regel und den Messwerten.
    """
    vertrag = contract()
    ref, neu = _normiert(referenz), _normiert(neubau)
    bericht = classify_differences(ref, neu, vertrag=vertrag)
    bericht.update({
        "reference_model_id": ref.get("model_id"),
        "rebuilt_model_id": neu.get("model_id"),
        "tolerance_contract_fingerprint": contract_fingerprint(),
        "identity_findings": [], "prediction": None,
    })
    abweichend = (bericht[KLASSE_KENNUNG] or bericht["tolerated_fields"]
                  or bericht["numerical_mismatches"]
                  or bericht["structural_mismatches"])
    bericht["exact"] = not abweichend
    if bericht["exact"]:
        bericht.update(equivalent=True, mode=MODE_EXACT,
                       reason="bitgleich bis auf Baumetadaten")
        return bericht

    bericht["equivalent"] = False
    bericht["mode"] = MODE_REFUSED
    bericht["identity_findings"] = (identity_findings(ref, "Referenz")
                                    + identity_findings(neu, "Neubau"))
    if bericht["structural_mismatches"]:
        bericht["reason"] = ("Strukturabweichung: %s"
                             % ", ".join(bericht["structural_mismatches"][:5]))
        return bericht
    if bericht["numerical_mismatches"]:
        bericht["reason"] = ("ausserhalb der eingefrorenen Toleranz: %s"
                             % ", ".join(bericht["numerical_mismatches"][:3]))
        return bericht
    if bericht["identity_findings"]:
        bericht["reason"] = bericht["identity_findings"][0]
        return bericht
    if zeilen is None:
        bericht["reason"] = "ohne Referenzpopulation kein Aequivalenznachweis"
        return bericht
    population = reference_population(zeilen)
    soll = vertrag["reference_population"]["rows"]
    if len(population) != soll:
        bericht["reason"] = ("die Referenzpopulation hat %d statt %d Partien"
                             % (len(population), soll))
        return bericht
    bericht["prediction"] = compare_predictions(ref, neu, population, vertrag)
    if not bericht["prediction"]["within_tolerance"]:
        bericht["reason"] = (
            "die Lambdas weichen ausserhalb der eingefrorenen Toleranz ab "
            "(max. relativ %.3g auf %d Partien)"
            % (bericht["prediction"]["max_rel_difference"], soll))
        return bericht
    bericht.update(equivalent=True, mode=MODE_EQUIVALENT, reason=(
        "nicht bitgleich, aber aequivalent: Struktur exakt, %d Zahlenfelder "
        "innerhalb der Toleranz (max. relativ %.3g), Lambdas max. relativ "
        "%.3g auf %d Partien"
        % (len(bericht["tolerated_fields"]), bericht["max_rel_difference"],
           bericht["prediction"]["max_rel_difference"], soll)))
    return bericht


# ---------------------------------------------------------------------------
# Die Referenzartefakte
# ---------------------------------------------------------------------------

def reference_candidate():
    return dict(contract()["reference_artifacts"]["candidate"])


def same_lineage(referenz, neubau):
    """Gehoert ein Neubau zur Linie des Referenzkandidaten?"""
    def kennung(b):
        b = b or {}
        return (b.get("candidate"),
                ((b.get("provenance") or {}).get("evaluation") or {}).get(
                    "evaluation_sha256"))
    return kennung(_normiert(referenz)) == kennung(_normiert(neubau))


def load_reference_candidate(repo_root=None):
    """
    Das gespeicherte, autoritative Kandidatenbundle - nur mit gepinntem
    SHA-256. Rueckgabe: (bundle, pfad, befunde).
    """
    from src.ml import model_registry as mr

    ref = reference_candidate()
    pfad = os.path.join(repo_root or ".", ref["path"])
    if not os.path.isfile(pfad):
        return None, pfad, [
            "das autoritative Bundle %s fehlt; ein nicht bitgleicher "
            "Neubau ersetzt es nicht" % ref["model_id"]]
    if mr.bundle_sha256(pfad) != ref["file_sha256"]:
        return None, pfad, [
            "der SHA-256 des autoritativen Bundles %s stimmt nicht mit dem "
            "eingefrorenen Wert ueberein" % ref["model_id"]]
    try:
        with open(pfad, encoding="utf-8") as datei:
            bundle = json.load(datei)
    except (OSError, ValueError) as fehler:
        return None, pfad, ["das autoritative Bundle ist unlesbar: %s"
                            % fehler]
    if bundle.get("model_id") != ref["model_id"]:
        return None, pfad, ["das autoritative Bundle traegt die Modell-ID "
                            "%s statt %s" % (bundle.get("model_id"),
                                             ref["model_id"])]
    return bundle, pfad, []


def fold_references(repo_root=None, bindung=None):
    """
    Die Foldreferenzen, geprueft. Rueckgabe: ({saison: bundle}, befunde).

    `bindung` ist `binding` aus dem C21-Ergebnis. Die gemessenen IDs im
    Vertrag muessen ihr gleichen, und jede Referenz muss aus ihrem Inhalt
    genau diese ID ergeben.
    """
    from src.ml import c21_season_validation as c21

    wurzel = repo_root or _repo_root()
    dokument, fehler = _lesen(wurzel, FOLD_REFERENCE_PATH)
    if fehler:
        return {}, ["die C22-Foldreferenzen %s" % fehler]
    befunde = []
    if (dokument.get("artifact") != FOLD_REFERENCE_ARTIFACT
            or dokument.get("schema_version") != CONTRACT_VERSION):
        befunde.append("die C22-Foldreferenzen haben nicht die erwartete "
                       "Fassung")
    if dokument.get("contract_fingerprint") != contract_fingerprint():
        befunde.append("die C22-Foldreferenzen sind nicht an den geltenden "
                       "Aequivalenzvertrag gebunden")
    if dokument.get("c21_contract_fingerprint") != c21.contract_fingerprint():
        befunde.append("die C22-Foldreferenzen sind nicht an den geltenden "
                       "C21-Vertrag gebunden")
    gemessen = contract()["reference_artifacts"]["folds"]["measured_ids"]
    folds = dokument.get("folds") or {}
    referenzen = {}
    for saison, modell_id in sorted(gemessen.items()):
        if bindung is not None and (bindung.get(saison) or {}).get(
                "model_id") != modell_id:
            befunde.append("Saison %s: die C21-Bindung nennt nicht die im "
                           "Vertrag eingefrorene Modell-ID" % saison)
        bundle = folds.get(saison)
        if not isinstance(bundle, dict):
            befunde.append("Saison %s: keine Foldreferenz" % saison)
            continue
        if bundle.get("model_id") != modell_id:
            befunde.append("Saison %s: die Foldreferenz traegt %s statt %s"
                           % (saison, bundle.get("model_id"), modell_id))
            continue
        eigene = identity_findings(bundle, "Foldreferenz %s" % saison)
        if eigene:
            befunde.extend(eigene)
            continue
        referenzen[saison] = bundle
    return (referenzen if not befunde else {}), befunde


def build_fold_reference_artifact(zeilen, evaluation, repo_root=None):
    """
    Die Foldreferenzen bauen - ausschliesslich bitgleich.

    Gebaut wird ueber `c21_season_validation.fold_bundle`, genau wie der
    Freigabeweg. Stimmt die Modell-ID nicht mit der C21-Bindung ueberein,
    laeuft dieser Prozess NICHT in einer Umgebung, die das gemessene
    Modell reproduziert, und es entsteht keine Referenz.
    """
    from src.ml import c19_league_map as c19
    from src.ml import c21_season_validation as c21

    wurzel = repo_root or _repo_root()
    ergebnis, fehler = _lesen(wurzel, c21.RESULT_PATH)
    if fehler:
        raise RuntimeError("das C21-Ergebnis %s" % fehler)
    bindung = ergebnis.get("binding") or {}
    folds = {}
    for saison in c21.SEASONS:
        gemessen = (bindung.get(str(saison)) or {}).get("model_id")
        bundle = _normiert(c21.fold_bundle(saison, zeilen, evaluation))
        if bundle["model_id"] != gemessen:
            raise RuntimeError(
                "Saison %s: der Neubau %s ist nicht das gemessene Modell %s "
                "- Referenzen entstehen nur bitgleich" % (
                    saison, bundle["model_id"], gemessen))
        eigene = identity_findings(bundle, "Foldreferenz %s" % saison)
        if eigene:
            raise RuntimeError(eigene[0])
        folds[str(saison)] = bundle
    return {
        "artifact": FOLD_REFERENCE_ARTIFACT,
        "schema_version": CONTRACT_VERSION,
        "created_at": _jetzt(),
        "git_commit": c19._git(),
        "contract_fingerprint": contract_fingerprint(),
        "c21_contract_fingerprint": c21.contract_fingerprint(),
        "c21_result_created_at": ergebnis.get("created_at"),
        "numerical_environment": numerical_environment(),
        "rule": contract()["reference_artifacts"]["folds"]["verification"],
        "folds": folds,
    }


# ---------------------------------------------------------------------------
# Dateiabhaengigkeiten des Freigabewegs
# ---------------------------------------------------------------------------

def dependency_findings():
    """
    Vertragsartefakt eingefroren und gleich dem Code; Foldreferenzen
    vorhanden und an die C21-Bindung gebunden. Fail-closed.
    """
    from src.ml import c21_season_validation as c21

    wurzel = _repo_root()
    befunde = []
    dokument, fehler = _lesen(wurzel, CONTRACT_PATH)
    if fehler:
        befunde.append("das C22-Aequivalenzvertragsartefakt %s" % fehler)
    else:
        if dokument.get("contract_fingerprint") != contract_fingerprint():
            befunde.append("der eingefrorene C22-Aequivalenzvertrag gleicht "
                           "nicht dem Vertrag im Code")
        if dokument.get("frozen_before_measurement") is not True:
            befunde.append("der C22-Aequivalenzvertrag ist nicht als vor der "
                           "Messung eingefroren ausgewiesen")
    ergebnis, _fehler = _lesen(wurzel, c21.RESULT_PATH)
    _refs, fold_befunde = fold_references(
        wurzel, (ergebnis or {}).get("binding"))
    befunde.extend(fold_befunde)
    return befunde
