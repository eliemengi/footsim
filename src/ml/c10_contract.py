"""
Der C10-Vertragsnachweis (V2-C10).

Der Stichtagsvertrag selbst steht in src/features/prediction_cutoff.py:
Er wird von features, data, ml UND predict benutzt und gehoert deshalb
in keine dieser Schichten allein. Ein bestehender Test haelt fest, dass
die Ligasimulation nichts aus src.ml importiert - das ist die Trennung
zwischen ML-Pfad und individueller Simulation.

Diese Datei baut nur den Nachweis. Sie liest early_v2, persist und
inference und gehoert damit sehr wohl auf die ML-Seite.
"""

from src.features.prediction_cutoff import (      # noqa: F401
    CONTRACT_VERSION,
    CUTOFF_HOUR,
    CUTOFF_INCLUSIVE,
    MissingCutoff,
    PredictionCutoff,
    assert_hours_match,
    contract,
    require,
)

# ---------------------------------------------------------------------------
# Das C10-Artefakt
# ---------------------------------------------------------------------------

#: Wohin der Vertragsnachweis gehoert.
#:
#: Namensschema wie C3 bis C9: data/ml/c<N>_<thema>_<zeitraum>.json.
ARTIFACT_PATH = "data/ml/c10_prediction_cutoff_contract_2023-2025.json"

#: Die Laufzeitpfade, die einen Stichtag fuehren muessen.
#:
#: Geprueft wird nicht, dass sie existieren, sondern DASS SIE IHN
#: FUEHREN. Ein Pfad, der ohne Stichtag rechnet, gehoert hier mit dem
#: Vermerk hinein, nicht weggelassen.
RUNTIME_ENTRY_POINTS = (
    {"module": "src/predict/cl_match_sim.py",
     "function": "simulate_cl_league_phase_match",
     "cutoff_source": ("kickoff-Argument, sonst fixture_cutoff() aus der "
                       "eigenen Historie, sonst runtime_cutoff()"),
     "explicit": True},
    {"module": "src/predict/cl_season_sim.py",
     "function": "Saisonsimulation",
     "cutoff_source": ("EIN runtime_cutoff() am Rand fuer den ganzen "
                       "Lauf; die Profile werden einmal daraus "
                       "aufgeloest, danach simuliert die Schleife nur "
                       "noch. Kein Nachladen je Partie und keine "
                       "Fortschreibung simulierter Ergebnisse in "
                       "spaetere Partien."),
     "explicit": True},
    {"module": "src/predict/league_match_sim.py",
     "function": "simulate_league_match",
     "cutoff_source": ("kickoff-Argument, sonst PredictionCutoff.now(); "
                       "seit V2-C10 keine eigene date.today()-Zeile mehr"),
     "explicit": True},
    {"module": "src/ml/inference.py",
     "function": "feature_columns / build_feature_row",
     "cutoff_source": ("kein eigener Stichtag - die Profile kommen "
                       "bereits zum Stichtag herein"),
     "explicit": False},
)

#: Die zeitabhaengigen Quellen, die der Stichtag steuert.
CUTOFF_CONTROLLED_SOURCES = (
    {"source": "data/historical ueber PitProfileRepository",
     "scale": "day_key",
     "why": ("Die Historie fuehrt ausschliesslich 'date'; "
             "point_in_time.match_time liest 'utc_date'/'utcDate' und "
             "findet dort nichts. Eine Stundenangabe waere wirkungslos, "
             "aber sichtbar - und wuerde Genauigkeit vortaeuschen.")},
    {"source": "match_timeline ueber matches_before",
     "scale": "instant_key",
     "why": ("Die Zeitleiste fuehrt echte Zeitstempel; Partien ohne "
             "Anstosszeit bekommen Tag@FALLBACK_KICKOFF_HOUR.")},
    {"source": "data/snapshots ueber snapshot_archive",
     "scale": "instant_key",
     "why": ("captured_at wird lexikografisch verglichen. Seit V2-C10 "
             "werden beide Seiten normalisiert, sonst entschiede die "
             "Schreibweise mit.")},
)


def _c10_git():
    import subprocess

    try:
        fertig = subprocess.run(["git", "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=30)
    except Exception:                                    # pragma: no cover
        return None
    return fertig.stdout.strip() if fertig.returncode == 0 else None


def build_artifact(c9_manifest=None):
    """
    Der C10-Vertragsnachweis - deterministisch und ohne Rohdaten.

    Er belegt vier Dinge: dass der Vertrag eindeutig ist, dass er
    ueberall derselbe ist, dass Training und Laufzeit denselben
    Zeitpunkt bezeichnen, und dass der C9-Freeze unberuehrt blieb.

    Fluechtige Felder (Erzeugungszeit, git-Stand) stehen drin, gehen
    aber NICHT in den stabilen Fingerabdruck - sonst waere jeder zweite
    Lauf per Definition ein anderer Vertrag.
    """
    import datetime as _dt
    import hashlib
    import json as _json

    from src.features import match_timeline as mt
    from src.ml import dataset as ds
    from src.ml import early_v2 as e9
    from src.ml import inference as inf
    from src.ml import persist as ps

    import pathlib

    if c9_manifest is None:
        pfad = pathlib.Path(e9.MANIFEST_PATH)
        c9_manifest = (_json.loads(pfad.read_text(encoding="utf-8"))
                       if pfad.exists() else None)

    # -- Paritaet, gemessen statt behauptet ------------------------------
    from src.features import pit_profiles as pp

    paritaet = []
    for tag in ("2023-09-19", "2024-12-31", "2025-03-11"):
        training = PredictionCutoff.at(ds.prediction_cutoff(tag))
        laufzeit = PredictionCutoff.parse(pp.runtime_cutoff(tag))
        paritaet.append({
            "match_day": tag,
            "training_cutoff": training.iso(),
            "runtime_cutoff": laufzeit.iso(),
            "identical": training == laufzeit,
        })

    # -- Der Merkmalsvektor beider Pfade ---------------------------------
    beispiel = {"attack_home": 1.21, "attack_away": 0.98,
                "defence_home": 0.87, "defence_away": 1.14,
                "points_per_game": 2.1, "goals_for_per_game": 2.0,
                "goals_against_per_game": 0.9, "win_rate": 0.67}
    laufzeit_zeile = inf.build_feature_row(beispiel, beispiel)
    training_zeile = {}
    training_zeile.update(ds.profile_feature_values(
        "home", beispiel, ds.PROFILE_RATING_FELDER))
    training_zeile.update(ds.profile_feature_values(
        "away", beispiel, ds.PROFILE_RATING_FELDER))

    vektor_gleich = (sorted(laufzeit_zeile) == sorted(training_zeile)
                     and all(laufzeit_zeile[k] == training_zeile[k]
                             for k in laufzeit_zeile))

    artefakt = {
        "artifact": "v2-c10 prediction cutoff contract",
        "schema_version": CONTRACT_VERSION,
        "created_at": _dt.datetime.now(
            _dt.timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _c10_git(),

        "contract": contract(),

        "hour_coupling": {
            "cutoff_hour": CUTOFF_HOUR,
            "timeline_fallback_hour": mt.FALLBACK_KICKOFF_HOUR,
            "match": CUTOFF_HOUR == mt.FALLBACK_KICKOFF_HOUR,
            "why_it_matters": (
                "Eine Partie ohne Anstosszeit bekommt Tag@Rueckfallstunde, "
                "ihr Stichtag liegt bei Tag@Stichtagsstunde. Der Filter "
                "ist strikt kleiner. Laufen die Stunden auseinander, "
                "faellt die Partie in ihr eigenes Merkmalsfenster."),
        },

        "runtime_entry_points": [dict(e) for e in RUNTIME_ENTRY_POINTS],
        "cutoff_controlled_sources": [dict(s)
                                      for s in CUTOFF_CONTROLLED_SOURCES],

        "parity": {
            "cutoff_identical_per_match_day": paritaet,
            "all_identical": all(p["identical"] for p in paritaet),
            "feature_vector_identical": vektor_gleich,
            "feature_count": len(laufzeit_zeile),
            "shared_mapping": ("dataset.profile_feature_values - beide "
                               "Pfade rufen dieselbe Funktion"),
            "shared_profile_factory": ("pit_profiles.PitProfileRepository "
                                       "und resolve_profile - cl_dataset "
                                       "und die Laufzeit importieren "
                                       "beide von dort"),
        },

        "fixed_divergence": {
            "what": ("Ein Snapshot vom Vormittag des Spieltags galt im "
                     "Training als bekannt und zur Laufzeit als "
                     "unbekannt."),
            "measured_case": {
                "captured_at": "2025-03-11T06:00:00+00:00",
                "training_cutoff_before_c10": "2025-03-11T12:00:00",
                "runtime_cutoff_before_c10": "2025-03-11",
                "training_verdict": "bekannt",
                "runtime_verdict": "unbekannt",
            },
            "root_cause": ("Lexikografischer Textvergleich. "
                           "'2025-03-11' ist ein Praefix des Stempels, "
                           "und kuerzer heisst kleiner."),
            "fix": ("snapshot_archive._vergleichstext normalisiert beide "
                    "Seiten ueber PredictionCutoff auf UTC, "
                    "sekundengenau, ohne Zonenanhang."),
        },

        "cutoff_definitions_before_c10": 4,
        "cutoff_definitions_after_c10": 1,
        "removed_duplicates": [
            "src/ml/dataset.py: eigene fromisoformat-Zeile",
            "src/ml/cl_dataset.py: eigene fromisoformat-Zeile",
            "src/features/pit_profiles.py: eigenes date.today()",
            "src/predict/league_match_sim.py: eigenes date.today()",
        ],

        "c9_freeze": {
            "manifest_path": e9.MANIFEST_PATH,
            "manifest_fingerprint": ((c9_manifest or {})
                                     .get("manifest_fingerprint")),
            "schema_fingerprint_live": e9.schema_fingerprint(),
            "schema_fingerprint_matches": (
                e9.schema_fingerprint()
                == ((c9_manifest or {}).get("fingerprints") or {})
                .get("schema")),
            "selected_candidate": e9.SELECTED_CANDIDATE,
            "selected_feature_count": len(e9.selected_columns()),
            "selected_family": [f for f, m in e9.FAMILY_REGISTRY.items()
                                if m["status"] == e9.STATUS_SELECTED],
            "model_family": ps.MODEL_FAMILY,
            "model_schema_version": ps.MODEL_SCHEMA_VERSION,
            "activated_anything": False,
            "overwrote_bundle": False,
        },

        "known_limits": [
            "Der Stichtag ist ein Tagesstichtag um "
            f"{CUTOFF_HOUR}:00 UTC, kein Anstosszeitpunkt. "
            "data/historical fuehrt keine Anstosszeiten; eine je Quelle "
            "unterschiedliche Regel waere schlechter als eine "
            "einheitlich leicht zu fruehe.",

            "Intern rechnet das Projekt in naiver UTC. Der kanonische "
            "Wert dieses Vertrags ist zeitzonenbehaftet, die "
            "Vergleichsskala bleibt naiv - ein Umbau traefe "
            "point_in_time, die Zeitleiste und den eingefrorenen "
            "C9-Stand.",

            "Die Paritaet ist fuer den ausgewaehlten Kandidaten belegt "
            "(16 Profilmerkmale). Forschungsmerkmale aus Zeitleiste und "
            "Snapshots teilen dieselbe Infrastruktur, sind aber nicht "
            "aktiviert und daher nicht Teil der Paritaetszusage.",

            "Es gibt weiterhin keinen unangetasteten Holdout. Die "
            "Saisons 2023 bis 2025 haben alle bisherigen Entscheidungen "
            "getragen; C10 aendert daran nichts und behauptet keine "
            "unabhaengige Bestaetigung.",

            "C10 aktiviert kein Modell. Der ausgewaehlte Kandidat bleibt "
            "der V1-Stand aus C9.",
        ],

        "status": "COMPLETE",
    }

    stabil = {k: v for k, v in sorted(artefakt.items())
              if k not in ("created_at", "git_commit")}
    artefakt["contract_fingerprint"] = hashlib.sha256(
        _json.dumps(stabil, sort_keys=True, ensure_ascii=False,
                    default=repr).encode("utf-8")).hexdigest()
    artefakt["fingerprint_excludes"] = ["created_at", "git_commit"]
    return artefakt
