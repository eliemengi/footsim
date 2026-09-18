"""
Zustandsfreie Release-Vorbereitung fuer den C20-Kandidaten (V2-C21).

WOZU DIESES MODUL DA IST
------------------------
Die reale Freigabe ist ein einziger, ausdruecklich autorisierter
Schritt: `run_ml.py --release-c16 apply` gegen das echte Repository.
Alles, was sich davor pruefen laesst, ohne den Produktionszustand zu
beruehren, wird hier geprueft - in temporaeren Wurzelverzeichnissen, mit
denselben Funktionen, die spaeter real laufen:

  - der Trockenlauf des EXAKTEN Kandidaten,
  - eine vollstaendige Aktivierung ueber apply_release,
  - die Laufzeitantwort danach (Modell-ID und applied),
  - der Rollback auf den gesicherten Vorzustand,
  - die Laufzeitantwort nach dem Rollback.

Die echte Registry wird dabei nur gelesen, um sie zu KOPIEREN. Kein
Freigabezeichen fuer die echte Registry entsteht, keine Datei im echten
Modellverzeichnis, keine Aenderung des Standardmodus.

SEIT V2-C22: ZUSTANDSUNABHAENGIG
--------------------------------
Nach der lokalen Aktivierung ist der Kandidat in der echten Registry
bereits aktiv. Ein Trockenlauf gegen diese Kopie meldete nur noch
`already_active` und pruefte den Weg nicht mehr. Deshalb stellt jede
Probe zuerst in der KOPIE den Vorzustand her, und zwar ueber den echten
Rollback aus dem gesicherten Vorzustand. Damit prueft sie nebenbei genau
den Rueckweg, den ein realer Rollback gehen wuerde.
"""

import contextlib
import functools
import hashlib
import json
import os
import shutil
import tempfile

from src.ml.c16_release import (BUILD_METADATA_FIELDS,  # noqa: F401
                                differing_fields, is_build_metadata)

CANDIDATE_ID = "clm-936ecce472696ccb-ls1c4f4e1d"
CANDIDATE_PATH = "data/ml/models/%s.json" % CANDIDATE_ID
CANDIDATE_SHA256 = (
    "9f2caf3a38e3385194e48311406844204e85a97e66ee1ef9c8ca949ab1f62479")

#: Das bis C21 aktive Modell - der Vorzustand der lokalen Aktivierung.
PREVIOUS_ACTIVE_ID = "clm-3475c9aacef6fec9-lsa165be9c"

#: Eine Partie fuer die Laufzeitprobe: Bayern gegen Arsenal, beide in
#: jeder Bundlekarte. Mit festem historischem Stichtag, damit die Probe
#: ausschliesslich lokale Daten liest und keinen Live-Spielplan braucht.
PROBE_MATCH = {"home_id": 5, "away_id": 57, "season": 2025,
               "kickoff": "2025-11-25T12:00:00"}


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def _sha(pfad):
    with open(pfad, "rb") as datei:
        return hashlib.sha256(datei.read()).hexdigest()


@contextlib.contextmanager
def runtime_root(wurzel):
    """
    Die Laufzeit liest Registry und aktives Bundle unter `wurzel`.

    Genau die zwei Stellen, die sonst auf das echte Repository zeigen.
    Freigabe-, Stufen- und Registrypruefung laufen unveraendert.
    """
    from src.ml import inference as inf
    from src.ml import model_registry as mr

    echt_active_entry = mr.active_entry
    echt_root = inf._REPO_ROOT
    mr.active_entry = functools.partial(echt_active_entry, repo_root=wurzel)
    inf._REPO_ROOT = wurzel
    inf.reset_model_cache()
    try:
        yield
    finally:
        mr.active_entry = echt_active_entry
        inf._REPO_ROOT = echt_root
        inf.reset_model_cache()


def copy_release_state(ziel):
    """
    Kopiert, was der Freigabeweg liest: Registry, deren Bundles, die
    C20-Messung, den C21-Vertrag mit Ergebnis und - falls vorhanden -
    den gesicherten Vorzustand fuer den Rollback. Nichts wird im
    Original veraendert.
    """
    from src.ml import c15_release as base
    from src.ml import c20_temporal_map as c20
    from src.ml import c21_season_validation as c21
    from src.ml import model_registry as mr

    quelle = _repo_root()
    dokument = mr.load_registry(repo_root=quelle)
    kopien = [mr.REGISTRY_PATH, c20.EVALUATION_PATH, c21.CONTRACT_PATH,
              c21.RESULT_PATH]
    kopien += [m["bundle_path"] for m in dokument["models"]]
    if os.path.isfile(os.path.join(quelle, base.SNAPSHOT_PATH)):
        kopien.append(base.SNAPSHOT_PATH)
    for relativ in kopien:
        ziel_pfad = os.path.join(ziel, relativ)
        os.makedirs(os.path.dirname(ziel_pfad), exist_ok=True)
        shutil.copyfile(os.path.join(quelle, relativ), ziel_pfad)
    return kopien


def restore_pre_activation(wurzel):
    """
    Stellt in der KOPIE den Zustand vor der Aktivierung her.

    Ist der Kandidat dort bereits aktiv, laeuft der echte Rollback aus
    dem gesicherten Vorzustand. Rueckgabe: was geschah.
    """
    from src.ml import c16_release as rel
    from src.ml import model_registry as mr

    aktiv, _g = mr.active_entry(repo_root=wurzel)
    start = (aktiv or {}).get("model_id")
    if start != CANDIDATE_ID:
        return {"start_active": start, "rollback": None,
                "pre_activation_active": start}
    zurueck = rel.rollback(repo_root=wurzel, dry_run=False)
    danach, _g = mr.active_entry(repo_root=wurzel)
    return {"start_active": start, "rollback": zurueck.get("status"),
            "rollback_reason": zurueck.get("reason"),
            "pre_activation_active": (danach or {}).get("model_id")}


def runtime_answer(modus="ml"):
    """
    Die Laufzeitantwort fuer die Probepartie, ueber den echten
    Einzelspielpfad.

    modus "ml": Request-Ansatz approach=ml, wie das Frontend ihn sendet.
    modus "off": ohne Ansatz, Standardbetriebsart aus der Umgebung.
    """
    from src.predict import cl_custom_factors as ccf
    from src.predict import cl_match_sim as cms

    optionen = ccf.parse_options({"approach": "ml"}) if modus == "ml" else None
    r = cms.simulate_cl_league_phase_match(
        "Heim", "Gast", home_id=PROBE_MATCH["home_id"],
        away_id=PROBE_MATCH["away_id"], season=PROBE_MATCH["season"],
        simulations=200, use_seed=True, options=optionen,
        kickoff=PROBE_MATCH["kickoff"])
    ml = r["ml"]
    return {"mode": ml["mode"], "applied": ml["applied"],
            "model_id": ml["model_id"], "status": ml["status"],
            "league_stage": (ml.get("league_stage") or {}).get("status")}


def dry_run_candidate():
    """
    Der Trockenlauf des exakten Kandidaten, isoliert.

    Die gespeicherte Kandidatendatei liegt in der Kopie vor, wie im
    lokalen Repository und auf einem VPS, dem sie mitgeliefert wird. Der
    Freigabeweg muss sie dann gegen seinen Neubau pruefen
    (`bundle_comparison`) und darf sie nur bei inhaltlicher Gleichheit
    uebernehmen.
    """
    from src.ml import c16_release as rel
    from src.ml import model_registry as mr

    echt_vorher = mr.registry_fingerprint(mr.load_registry())
    with tempfile.TemporaryDirectory() as wurzel:
        copy_release_state(wurzel)
        vorzustand = restore_pre_activation(wurzel)
        ziel = os.path.join(wurzel, CANDIDATE_PATH)
        if not os.path.isfile(ziel):
            shutil.copyfile(os.path.join(_repo_root(), CANDIDATE_PATH), ziel)
        registry_vor_lauf = mr.registry_fingerprint(
            mr.load_registry(repo_root=wurzel))
        ergebnis = rel.release(dry_run=True, repo_root=wurzel,
                               expected_model_id=CANDIDATE_ID)
        registry_tmp = mr.registry_fingerprint(
            mr.load_registry(repo_root=wurzel))
    vergleich = ergebnis.get("bundle_comparison") or {}
    return {
        "status": ergebnis["status"],
        "reason": ergebnis.get("reason"),
        "model_id": ergebnis.get("model_id"),
        "matches_candidate": ergebnis.get("model_id") == CANDIDATE_ID,
        "pre_activation": vorzustand,
        "stored_candidate_sha256": _sha(os.path.join(_repo_root(),
                                                     CANDIDATE_PATH)),
        "stored_candidate_matches_c20": (
            _sha(os.path.join(_repo_root(), CANDIDATE_PATH))
            == CANDIDATE_SHA256),
        "existing_file_used": vergleich.get("existing_file"),
        "differing_fields": vergleich.get("differing_fields"),
        "model_fields_differing": vergleich.get("model_fields_differing"),
        "season_evidence": ergebnis.get("season_evidence"),
        "wrote_anything": ergebnis.get("wrote_anything"),
        "temporary_registry_unchanged": registry_tmp == registry_vor_lauf,
        "real_registry_unchanged": (
            mr.registry_fingerprint(mr.load_registry()) == echt_vorher),
        "log": ergebnis.get("log", []),
    }


def activation_rollback_probe():
    """
    Aktivierung und Rollback ueber die echten Funktionen - isoliert.

    Ablauf im temporaeren Wurzelverzeichnis:
      1. Zustand kopieren, Vorzustand herstellen (siehe oben)
      2. release(dry_run=False)            -> C20-Kandidat aktiv; die
         Kandidatendatei fehlt in der Kopie und wird neu gebaut, wie auf
         einem VPS ohne mitgelieferte Datei
      3. Neubau gegen gespeicherten Kandidaten vergleichen
      4. Laufzeitantwort                   -> applied, Kandidat-ID
      5. rollback(dry_run=False)           -> Vorzustand aktiv
      6. Laufzeitantwort                   -> applied, alte ID
    Danach wird geprueft, dass die echte Registry und das echte
    Modellverzeichnis unveraendert sind.
    """
    from src.ml import c16_release as rel
    from src.ml import model_registry as mr

    echt_registry = mr.registry_fingerprint(mr.load_registry())
    echt_modelle = sorted(os.listdir(os.path.join(_repo_root(), "data",
                                                  "ml", "models")))
    with open(os.path.join(_repo_root(), CANDIDATE_PATH),
              encoding="utf-8") as datei:
        gespeichert = json.load(datei)
    alt_env = {k: os.environ.get(k) for k in ("FOOTSIM_ML_MODE",
                                              "FOOTSIM_ML_WEIGHT")}
    os.environ.pop("FOOTSIM_ML_MODE", None)
    os.environ.pop("FOOTSIM_ML_WEIGHT", None)
    try:
        with tempfile.TemporaryDirectory() as wurzel:
            copy_release_state(wurzel)
            vorzustand = restore_pre_activation(wurzel)
            ziel = os.path.join(wurzel, CANDIDATE_PATH)
            if os.path.isfile(ziel):
                os.remove(ziel)            # nur in der temporaeren Kopie
            vorher, _g = mr.active_entry(repo_root=wurzel)

            freigabe = rel.release(dry_run=False, repo_root=wurzel,
                                   expected_model_id=CANDIDATE_ID)
            nach_freigabe, _g = mr.active_entry(repo_root=wurzel)
            neubau = None
            if os.path.isfile(ziel):
                with open(ziel, encoding="utf-8") as datei:
                    neubau = differing_fields(gespeichert, json.load(datei))
            with runtime_root(wurzel):
                antwort_aktiv = runtime_answer("ml")
                antwort_aus = runtime_answer("off")

            zurueck = rel.rollback(repo_root=wurzel, dry_run=False)
            nach_rollback, _g = mr.active_entry(repo_root=wurzel)
            with runtime_root(wurzel):
                antwort_nach_rollback = runtime_answer("ml")
    finally:
        for k, v in alt_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    return {
        "pre_activation": vorzustand,
        "active_before": (vorher or {}).get("model_id"),
        "release_status": freigabe.get("status"),
        "release_reason": freigabe.get("reason"),
        "active_after_release": (nach_freigabe or {}).get("model_id"),
        "fresh_build_differing_fields": neubau,
        "fresh_build_only_build_metadata": (
            neubau is not None and all(is_build_metadata(p)
                                       for p in neubau)),
        "runtime_after_release_ml": antwort_aktiv,
        "runtime_after_release_off": antwort_aus,
        "rollback_status": zurueck.get("status"),
        "active_after_rollback": (nach_rollback or {}).get("model_id"),
        "runtime_after_rollback_ml": antwort_nach_rollback,
        "real_registry_unchanged": (
            mr.registry_fingerprint(mr.load_registry()) == echt_registry),
        "real_models_dir_unchanged": (
            sorted(os.listdir(os.path.join(_repo_root(), "data", "ml",
                                           "models"))) == echt_modelle),
    }
