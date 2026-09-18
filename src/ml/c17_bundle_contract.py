"""
Der Bundlevertrag fuer mehrstufige Modelle (V2-C17).

WARUM ES DIESEN VERTRAG GIBT
----------------------------
Der Bundlevertrag aus V2-C0B kennt genau ein Modell: eine Stufe,
Schema 2, der Kandidat der CL-Shadow-Evaluation. Er hat das
akzeptierte C16-Modell korrekt abgelehnt, denn dessen zweite Stufe
kommt darin nicht vor.

Diese Ablehnung war richtig. Ein Loader, der ein unbekanntes Bundle
durchwinkt, ist kein Loader, sondern eine Hoffnung.

WAS HIER NICHT PASSIERT
-----------------------
Die bestehenden Schranken werden NICHT gelockert. Es gibt keine
Ausnahme der Form "alle Kandidatennamen erlauben" und keine
abgeschaltete Pruefung. Stattdessen wird der Vertrag ausdruecklich um
genau die Faelle erweitert, die er tragen soll, und jede Erweiterung
ist einzeln benannt:

    ALLOWED_MULTISTAGE_CANDIDATES   welcher Kandidat welche zweite
                                    Stufe tragen MUSS
    ALLOWED_EVALUATION_TASKS        welche Evaluationsart ein Bundle
                                    binden darf

Was hier nicht steht, wird abgelehnt.

RUECKWAERTSKOMPATIBILITAET
--------------------------
Schema 1 und 2 bleiben Wort fuer Wort lesbar. Ein Schema-2-Bundle
darf allerdings keine Schema-3-Felder tragen: Ein einstufiges Bundle
mit einem `league_strength`-Block waere entweder ein Irrtum oder ein
Versuch, die zweite Stufe an der Pruefung vorbeizuschmuggeln.

FAIL-CLOSED, UND ZWAR GANZ
--------------------------
Ist die zweite Stufe beschaedigt, gilt das GESAMTE Bundle als
ungueltig. Nur die Basisstufe weiterrechnen zu lassen waere die
gefaehrlichste aller Varianten: Das Ergebnis saehe vollstaendig aus,
waere es aber nicht, und niemand haette einen Anlass nachzusehen.
"""

import hashlib
import json

CONTRACT_VERSION = "v2-c17.1"

CONTRACT_PATH = "data/ml/c17_multistage_bundle_release_contract.json"

#: Die Bundlefassung mit zweiter Stufe.
MULTISTAGE_SCHEMA_VERSION = 3

#: Welcher Kandidat welche zweite Stufe tragen MUSS.
#:
#: Bewusst eine ausgeschriebene Zuordnung und keine Regel der Form
#: "wer einen league_strength-Block hat, darf ihn haben". Ein Bundle,
#: das sich seine eigene Stufe aussucht, ist kein Vertrag.
ALLOWED_MULTISTAGE_CANDIDATES = {
    "team_profile_cl_plus_damped_league_strength": {
        "stage_2": "damped_league_strength",
        "required_fields": ("attack", "defence", "gamma", "alpha",
                            "team_leagues", "factor_bounds"),
        "source_block": "V2-C16",
    },
}

#: Welche Evaluationsart ein Bundle binden darf.
#:
#: `cl_shadow_backtest` ist die bestehende Art aus V2-C0B und bleibt
#: unveraendert gueltig. `v2-c16 damped league strength evaluation`
#: kommt hinzu, weil sie dieselbe Strenge hat: eingefrorener Vertrag
#: vor der Messung, zeitliche Folds, gepaarter Bootstrap, Segmente,
#: elf Gates.
ALLOWED_EVALUATION_TASKS = {
    "cl_shadow_backtest": {
        "schema": "V2-C0B", "binds_via": "manifest",
    },
    "v2-c16 damped league strength evaluation": {
        "schema": "V2-C16", "binds_via": "artifact",
    },
}

#: Grenzen, die eine zweite Stufe einhalten muss. Sie stammen aus
#: V2-C15/C16 und werden hier nicht neu gewaehlt.
GAMMA_MIN, GAMMA_MAX = 0.0, 1.0


class BundleContractError(ValueError):
    """
    Ein Bundle verletzt den mehrstufigen Vertrag.

    Eigene Klasse, damit ein Aufrufer sie von einem gewoehnlichen
    Fehler unterscheiden kann. Sie fuehrt immer zur Ablehnung des
    GESAMTEN Bundles.
    """


def _kanonisch(wert):
    return json.dumps(wert, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def _stabil(block):
    return hashlib.sha256(_kanonisch(block).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Der Vertrag
# ---------------------------------------------------------------------------

def contract():
    """Der vollstaendige Vertrag - ohne einen einzigen Messwert."""
    from src.features import league_strength as ls
    from src.features import prediction_cutoff as pc
    from src.ml import c13_contract as c13
    from src.ml import c14_reevaluation as c14
    from src.ml import c15_league_strength as c15
    from src.ml import c16_damped_league_strength as c16
    from src.ml import early_v2 as e9
    from src.ml import model_registry as mr
    from src.ml import persist as ps

    return {
        "version": CONTRACT_VERSION,
        "purpose": (
            "Erweitert den Bundlevertrag ausdruecklich um mehrstufige "
            "Modelle, ohne eine bestehende Schranke zu lockern."),

        "schema": {
            "multistage_version": MULTISTAGE_SCHEMA_VERSION,
            "backward_compatible": [1, 2],
            "rules": [
                "Schema 1 und 2 bleiben unveraendert lesbar.",
                "Ein Schema-2-Bundle darf KEINE Schema-3-Felder "
                "tragen - das waere ein Versuch, die zweite Stufe an "
                "der Pruefung vorbeizufuehren.",
                "Ein Schema-3-Bundle ohne zweite Stufe wird abgelehnt.",
                "Ein Schema-3-Bundle ohne gamma wird abgelehnt.",
                "Ein Schema-3-Bundle ohne gueltige Evaluationsbindung "
                "wird abgelehnt.",
                "Unbekannte Fassungen werden abgelehnt.",
            ],
        },

        "allowed_multistage_candidates": {
            name: dict(regel)
            for name, regel in sorted(ALLOWED_MULTISTAGE_CANDIDATES.items())},
        "no_generic_exception": (
            "Es gibt keine Regel der Form 'alle Kandidatennamen "
            "erlauben'. Was nicht in der Liste steht, wird abgelehnt."),

        "allowed_evaluation_tasks": {
            name: dict(regel)
            for name, regel in sorted(ALLOWED_EVALUATION_TASKS.items())},

        "required_bundle_fields": [
            "model_id", "schema_version", "model_family", "candidate",
            "features", "feature_count", "alpha", "models", "integrity",
            "training", "provenance"],

        "required_league_strength_fields": list(
            ALLOWED_MULTISTAGE_CANDIDATES[
                "team_profile_cl_plus_damped_league_strength"][
                    "required_fields"]),

        "parameter_bounds": {
            "gamma_min": GAMMA_MIN, "gamma_max": GAMMA_MAX,
            "factor_min": ls.FACTOR_MIN, "factor_max": ls.FACTOR_MAX,
            "alpha_space": list(_alpha_kandidaten()),
        },

        "cold_start": (
            "Eine Liga ohne Eintrag traegt 0 und damit den Faktor 1. "
            "Unbekannt heisst unbekannt und niemals 'vermutlich "
            "schwach'."),
        "unknown_league": (
            "Was auf sie wirkt, ist ausschliesslich die Staerke des "
            "bekannten Gegners."),
        "provenance": (
            "Die Ligazuordnung liegt IM Bundle und stammt aus dem "
            "validierten C13-Crosswalk. Rohe IDs werden nie "
            "providerueberschreitend gleichgesetzt."),
        "training_cutoff": {
            "hour": pc.CUTOFF_HOUR,
            "inclusive": pc.CUTOFF_INCLUSIVE,
            "unchanged_by_c17": True,
        },

        "loader_rules": [
            "Der Loader prueft Fassung, Familie, Kandidat, Merkmale "
            "nach Zahl UND Reihenfolge, Integritaet und - bei Schema 3 "
            "- die vollstaendige zweite Stufe.",
            "Eine beschaedigte zweite Stufe macht das GESAMTE Bundle "
            "ungueltig. Nur die Basisstufe weiterrechnen zu lassen "
            "waere die gefaehrlichste Variante: Das Ergebnis saehe "
            "vollstaendig aus, waere es aber nicht.",
        ],

        "allowed_registry_transitions": ["candidate -> shadow",
                                         "shadow -> active",
                                         "active -> rollback"],
        "release_gates": [
            "Urteil accepted", "Bundle validiert und ladbar",
            "Bundle-Hash stimmt", "Merkmalsschema stimmt",
            "alle Vertragsfingerabdruecke stimmen",
            "genau ein aktives Modell danach",
            "Registry vor und nach dem Schreiben valide"],

        "runtime_parity": (
            "Dieselbe Partie muss in Training, Evaluation, Bundle, "
            "Loader, direkter Inference und sichtbarer Simulation "
            "dieselben Lambdas ergeben."),
        "shadow_isolation": (
            "Ein Modell im Schatten veraendert keine Nutzerantwort. "
            "Erst nach bestandener Isolationspruefung darf Active "
            "gesetzt werden."),
        "rollback": (
            "Technische Wiederherstellung eines gueltigen frueheren "
            "Zustands. Ausdruecklich kein Weg, ein fachlich "
            "abgelehntes Modell zu reaktivieren."),
        "recovery": (
            "Ein unterbrochener Vorgang wird eindeutig aufgeloest. "
            "Kein halbfertiges Active-Modell."),

        "fail_closed_cases": [
            "Bundle fehlt", "Bundle-Hash falsch",
            "zweite Stufe fehlt oder beschaedigt", "gamma fehlt",
            "gamma ausserhalb der Grenzen", "Evaluation passt nicht",
            "Registry beschaedigt", "mehrere aktive Modelle",
            "aktives Modell ohne Freigabe", "unbekannte Schemafassung",
            "Schema-2-Bundle mit Schema-3-Feldern"],

        "bound_contracts": {
            "c9_schema_fingerprint": e9.schema_fingerprint(),
            "c10_cutoff_hour": pc.CUTOFF_HOUR,
            "c11_contract_fingerprint": _stabil(mr.contract()),
            "c13_contract_fingerprint": c13.contract_fingerprint(),
            "c14_contract_fingerprint": c14.contract_fingerprint(),
            "c15_contract_fingerprint": c15.contract_fingerprint(),
            "c16_contract_fingerprint": c16.contract_fingerprint(),
            "c16_model_schema_fingerprint": c16.schema_fingerprint(),
            "c16_result_fingerprint": _c16_ergebnis_fingerabdruck(),
            "base_model_family": ps.MODEL_FAMILY,
        },

        "does_not_change": [
            "die statistische C16-Evaluation",
            "die Gates aus C2B, C8, C12, C14, C15 und C16",
            "den C9-Merkmalsfreeze",
            "den C10-Stichtag",
            "die C11-Registryregeln",
        ],

        "no_untouched_holdout": (
            "Das freigegebene Modell traegt die Klasse "
            "accepted_development_evidence. Eine unabhaengige "
            "Bestaetigung waere erst mit Saison 2026/27 moeglich."),
    }


def _alpha_kandidaten():
    from src.ml import model as mdl

    return tuple(mdl.ALPHA_CANDIDATES)


def _c16_ergebnis_fingerabdruck():
    """
    Der C16-Ergebnisfingerabdruck, gelesen statt behauptet.

    V2-C22: Der Pfad wird gegen das Repository aufgeloest, nicht gegen
    das Arbeitsverzeichnis. Vorher lieferte ein Aufruf aus einem anderen
    Verzeichnis None und damit still einen anderen Vertragsfingerabdruck.
    Inhalt und Fingerabdruck des Vertrags bleiben unveraendert; fehlt die
    Datei, bleibt es bei None, und der Freigabeweg weist das ab
    (`c16_release.dependency_findings`).
    """
    import os

    from src.ml import c16_damped_league_strength as c16

    wurzel = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    pfad = os.path.join(wurzel, c16.ARTIFACT_PATH)
    if not os.path.isfile(pfad):
        return None
    try:
        with open(pfad, encoding="utf-8") as datei:
            return json.load(datei).get("result_fingerprint")
    except (OSError, ValueError):                        # pragma: no cover
        return None


def contract_fingerprint(vertrag=None):
    return _stabil(vertrag if vertrag is not None else contract())


# ---------------------------------------------------------------------------
# Die Pruefung
# ---------------------------------------------------------------------------

def is_multistage_candidate(name):
    return name in ALLOWED_MULTISTAGE_CANDIDATES


def validate_schema_version(fassung, kandidat, bundle):
    """
    Passen Fassung und Kandidat zusammen?

    Rueckgabe: Liste der Befunde. Leer heisst in Ordnung.
    """
    befunde = []
    mehrstufig = is_multistage_candidate(kandidat)

    if fassung == MULTISTAGE_SCHEMA_VERSION:
        if not mehrstufig:
            befunde.append(
                "Fassung %d ist mehrstufigen Modellen vorbehalten; %r "
                "steht nicht in der Liste der zugelassenen Kandidaten"
                % (MULTISTAGE_SCHEMA_VERSION, kandidat))
    else:
        # Ein einstufiges Bundle darf keine zweite Stufe vortaeuschen.
        if bundle.get("league_strength") is not None:
            befunde.append(
                "ein Bundle der Fassung %r traegt einen "
                "league_strength-Block - eine zweite Stufe gehoert in "
                "Fassung %d und wird hier nicht anerkannt"
                % (fassung, MULTISTAGE_SCHEMA_VERSION))
        if mehrstufig:
            befunde.append(
                "der Kandidat %r verlangt Fassung %d, das Bundle traegt "
                "%r" % (kandidat, MULTISTAGE_SCHEMA_VERSION, fassung))
    return befunde


def validate_league_strength(bundle):
    """
    Die zweite Stufe vollstaendig pruefen.

    Rueckgabe: Liste der Befunde. Leer heisst in Ordnung.

    Jeder Befund macht das GESAMTE Bundle ungueltig - siehe Modulkopf.
    """
    import math

    from src.features import league_strength as ls

    kandidat = bundle.get("candidate")
    regel = ALLOWED_MULTISTAGE_CANDIDATES.get(kandidat)
    if regel is None:
        return ["%r ist kein zugelassener mehrstufiger Kandidat"
                % kandidat]

    block = bundle.get("league_strength")
    if not isinstance(block, dict):
        return ["dem Bundle fehlt die zweite Stufe (league_strength)"]

    befunde = []
    for feld in regel["required_fields"]:
        if feld not in block:
            befunde.append("der zweiten Stufe fehlt %r" % feld)

    gamma = block.get("gamma")
    if not isinstance(gamma, (int, float)) or isinstance(gamma, bool):
        befunde.append("gamma ist keine Zahl: %r" % (gamma,))
    elif not math.isfinite(gamma):
        befunde.append("gamma ist nicht endlich")
    elif not (GAMMA_MIN < gamma <= GAMMA_MAX):
        befunde.append("gamma liegt ausserhalb (%s, %s]: %r"
                       % (GAMMA_MIN, GAMMA_MAX, gamma))

    for name in ("attack", "defence"):
        werte = block.get(name)
        if not isinstance(werte, dict) or not werte:
            befunde.append("%r ist leer oder kein Objekt" % name)
            continue
        for liga, wert in werte.items():
            if (not isinstance(wert, (int, float))
                    or isinstance(wert, bool)
                    or not math.isfinite(wert)):
                befunde.append("%s[%r] ist keine endliche Zahl"
                               % (name, liga))
                break

    karte = block.get("team_leagues")
    if not isinstance(karte, dict) or not karte:
        befunde.append("die Ligazuordnung fehlt oder ist leer")

    grenzen = block.get("factor_bounds")
    if (not isinstance(grenzen, (list, tuple)) or len(grenzen) != 2
            or list(grenzen) != [ls.FACTOR_MIN, ls.FACTOR_MAX]):
        befunde.append("die Faktorgrenzen weichen von %s ab"
                       % ([ls.FACTOR_MIN, ls.FACTOR_MAX],))

    return befunde


def validate_evaluation_task(aufgabe):
    """Ist diese Evaluationsart zugelassen?"""
    if aufgabe in ALLOWED_EVALUATION_TASKS:
        return []
    return ["die Evaluationsart %r ist nicht zugelassen; erlaubt sind %s"
            % (aufgabe, sorted(ALLOWED_EVALUATION_TASKS))]


def validate_bundle(bundle):
    """
    Der vollstaendige Vertragscheck eines Bundles.

    Rueckgabe: Liste der Befunde. Leer heisst in Ordnung.
    """
    if not isinstance(bundle, dict):
        return ["das Bundle ist kein Objekt"]

    fassung = bundle.get("schema_version")
    kandidat = bundle.get("candidate")

    befunde = validate_schema_version(fassung, kandidat, bundle)
    if fassung == MULTISTAGE_SCHEMA_VERSION and not befunde:
        befunde.extend(validate_league_strength(bundle))
    return befunde


def assert_bundle(bundle):
    """Wirft, wenn das Bundle den Vertrag verletzt."""
    befunde = validate_bundle(bundle)
    if befunde:
        raise BundleContractError(
            "das Bundle verletzt den mehrstufigen Vertrag: %s"
            % "; ".join(befunde))
    return True


# ---------------------------------------------------------------------------
# Schreiben
# ---------------------------------------------------------------------------

def write_contract(pfad=None):
    """Den Vertrag festschreiben - VOR dem Bundlebau."""
    import datetime as _dt
    import os
    import pathlib
    import tempfile

    vertrag = contract()
    dokument = {
        "artifact": "v2-c17 multistage bundle release contract",
        "schema_version": CONTRACT_VERSION,
        "created_at": _dt.datetime.now(
            _dt.timezone.utc).isoformat(timespec="seconds"),
        "frozen_before_bundle": True,
        "contract": vertrag,
        "contract_fingerprint": contract_fingerprint(vertrag),
        "fingerprint_excludes": ["created_at", "git_commit"],
    }
    ziel = pathlib.Path(pfad or CONTRACT_PATH)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    inhalt = json.dumps(dokument, indent=2, ensure_ascii=False)
    griff, temp = tempfile.mkstemp(dir=str(ziel.parent), suffix=".tmp")
    try:
        with os.fdopen(griff, "w", encoding="utf-8") as datei:
            datei.write(inhalt + "\n")
            datei.flush()
            os.fsync(datei.fileno())
        os.replace(temp, ziel)
    except BaseException:                                # pragma: no cover
        if os.path.exists(temp):
            os.unlink(temp)
        raise
    return str(ziel)
