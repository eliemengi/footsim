"""
Der Nachweis des reparierten nationalen Profilpfads (V2-C13).

WAS HIER BELEGT WIRD
--------------------
1. Welche Wettbewerbe als nationale Profilquelle zugelassen sind - und
   welche ausdruecklich nicht.
2. Dass Vereins-IDs niemals providerueberschreitend gleichgesetzt
   werden.
3. Wie sich die Profilabdeckung der Champions League dadurch
   veraendert hat.
4. Dass der C9-Freeze und der C10-Stichtag dabei unberuehrt blieben.

ZWEI FINGERABDRUECKE, NICHT EINER
---------------------------------
In C11 steckten Vertrag und Zustand in einem gemeinsamen
Fingerabdruck. Die Folge war laestig und irrefuehrend zugleich: Jede
Registrierung eines Modells veraenderte ihn, und man konnte nicht mehr
sehen, ob sich die REGEL geaendert hatte oder nur die Belegung.

Deshalb hier getrennt:

    contract_fingerprint   die Regeln. Aendert sich nur, wenn jemand
                           die Ligaliste, die Ausschluesse, die
                           Identitaetsregel oder die Stichtagsregel
                           anfasst.

    state_fingerprint      die Messung. Aendert sich, sobald neue
                           Spieldaten vorliegen - was voellig normal
                           ist und kein Vertragsbruch.

Erzeugungszeit und git-Stand stehen im Artefakt, gehen aber in keinen
der beiden Fingerabdruecke ein. Sonst waere jeder zweite Lauf per
Definition ein anderer Vertrag.
"""

import hashlib
import json

from src.data import national_sources as ns
from src.features import prediction_cutoff as pc
from src.features import team_identity as ti

CONTRACT_VERSION = "v2-c13.1"

ARTIFACT_PATH = "data/ml/c13_national_profile_contract_2023-2025.json"


def _stabil(block):
    """Ein Fingerabdruck, der nicht an der Schluesselreihenfolge haengt."""
    text = json.dumps(block, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Der unveraenderliche Teil
# ---------------------------------------------------------------------------

def contract():
    """
    Die Regeln des nationalen Profilpfads.

    Bewusst ohne jede Messung. Was hier steht, gilt unabhaengig davon,
    wie viele Partien gerade auf der Platte liegen.
    """
    return {
        "version": CONTRACT_VERSION,

        "profile_sources": {
            "allowed": {code: dict(eintrag)
                        for code, eintrag in sorted(
                            ns.NATIONAL_LEAGUES.items())},
            "count": len(ns.NATIONAL_LEAGUES),
            "by_provider": {p: ns.codes_for_provider(p)
                            for p in ns.PROVIDERS},
            "selection_rule": (
                "Ausgeschriebene Liste, kein Verzeichnisglob. Ein Glob "
                "wuerde den naechsten heruntergeladenen Wettbewerb "
                "stillschweigend aufnehmen."),
        },

        "excluded_competitions": {
            "entries": dict(sorted(ns.EXCLUDED_COMPETITIONS.items())),
            "reason": (
                "Ein Pokal ist kein Ligabetrieb: gemischte Ligaebenen, "
                "zwischen einer und sieben Partien je Verein. Ein Profil "
                "daraus beschreibt nicht die Staerke gegen vergleichbare "
                "Gegner. Die Dateien liegen lokal vor und werden "
                "ausdruecklich nicht gelesen."),
        },

        "identity_rule": {
            "statement": ("Provider plus Zahl ergeben eine "
                          "Vereinsidentitaet. Eine Zahl allein nicht."),
            "direction": ("API-Football -> football-data, weil die "
                          "Champions League in football-data-Kennungen "
                          "gefuehrt wird."),
            "translation_order": (
                "Erst werden ALLE Profile im Namensraum der Ligadatei "
                "gebaut, dann zurueckuebersetzt. Nie wird gefragt, ob "
                "eine football-data-Kennung in einer API-Football-Datei "
                "vorkommt - genau diese Frage waere die Falle."),
            "on_unmapped": ("Kein nationales Profil. Unbekannt ist "
                            "besser als vielleicht falsch."),
            "on_ambiguous": ("Ein Ziel, auf das zwei Vereine zeigen, "
                             "wird aus BEIDEN Richtungen entfernt."),
            "never": ("Kein Fuzzy-Matching zur Laufzeit. Keine rohe ID "
                      "providerueberschreitend."),
        },

        "point_in_time": {
            "cutoff_hour": pc.CUTOFF_HOUR,
            "inclusive": pc.CUTOFF_INCLUSIVE,
            "unchanged_by_c13": True,
            "kickoff_field_ignored": (
                "Die API-Football-Dateien fuehren ein kickoff-Feld, die "
                "football-data-Dateien nicht. point_in_time liest es "
                "nicht, und das bleibt so - ein zusaetzliches Zeitfeld "
                "wuerde die Stichtagssemantik ALLER Aufrufer "
                "verschieben. Die Folge ist konservativ: Partien am "
                "Stichtag bleiben draussen."),
        },

        "out_of_scope": [
            "kein Shrinkage",
            "keine Modellentscheidung, kein Training, keine Evaluation",
            "keine Registryaenderung",
            "keine externen Abrufe, keine neuen Daten",
            "C9-Schemafingerabdruck unveraendert",
            "C10-Stichtag nicht abgeschwaecht",
        ],
    }


def contract_fingerprint():
    """Der Fingerabdruck der REGELN."""
    return _stabil(contract())


# ---------------------------------------------------------------------------
# Der gemessene Teil
# ---------------------------------------------------------------------------

def measure(zeilen=None):
    """
    Die Abdeckung, gemessen statt behauptet.

    zeilen: bereits gebauter Datensatz. Ohne Angabe wird er gebaut.
    """
    import collections

    from src.features import pit_profiles as pp

    if zeilen is None:
        from src.ml import dataset as ds
        zeilen, _ = ds.build_dataset(include_cl=True)

    cl = [z for z in zeilen if z.get("league") == "cl"]

    quellen = collections.Counter()
    tiefen = []
    for zeile in cl:
        for seite in ("home", "away"):
            quellen[zeile.get(seite + "_profile_source")] += 1
            wert = zeile.get(seite + "_profile_matches")
            if isinstance(wert, (int, float)):
                tiefen.append(wert)
    tiefen.sort()

    repo = pp.PitProfileRepository()
    repo.domestic_profiles(2025, "2026-01-20")
    herkunft = repo.domestic_provenance()

    inventar = ns.league_inventory()

    rest = [z for z in cl
            if not z.get("evaluation_eligible")
            and not z.get("knockout_eligible")]

    return {
        "inventory": ns.inventory_summary(inventar),
        "leagues_contributing": {
            code: {"kept": spur["kept"],
                   "dropped_unmapped": spur["dropped_unmapped"],
                   "provider": spur["provider"]}
            for code, spur in sorted(herkunft.items())},

        "identity": ti.identity_report(),

        "cl_coverage": {
            "matches": len(cl),
            "team_sides": 2 * len(cl),
            "profile_sources": dict(sorted(quellen.items())),
            "profile_depth_median": (tiefen[len(tiefen) // 2]
                                     if tiefen else None),
            "profile_depth_min": tiefen[0] if tiefen else None,
        },

        "eligibility": {
            "evaluation_eligible": sum(1 for z in cl
                                       if z.get("evaluation_eligible")),
            "knockout_eligible": sum(1 for z in cl
                                     if z.get("knockout_eligible")),
            "neither": len(rest),
            "remaining_exclusions": dict(sorted(collections.Counter(
                z.get("exclusion_reason") for z in rest).items(),
                key=lambda kv: str(kv[0]))),
        },
    }


def state_fingerprint(messung=None):
    """Der Fingerabdruck der MESSUNG."""
    return _stabil(messung if messung is not None else measure())


# ---------------------------------------------------------------------------
# Artefakt
# ---------------------------------------------------------------------------

def _git():
    """Der git-Stand, rein informativ. Geht in keinen Fingerabdruck."""
    import subprocess

    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True,
            text=True, timeout=10)
        return commit.stdout.strip() or None
    except Exception:                                    # pragma: no cover
        return None


def build_artifact(zeilen=None):
    """
    Der C13-Nachweis - deterministisch und ohne Rohdaten.

    Es stehen keine vollstaendigen Merkmalsvektoren, keine Zugangsdaten
    und keine lokalen absoluten Pfade darin.
    """
    import datetime as _dt

    from src.ml import early_v2 as e9

    vertrag = contract()
    messung = measure(zeilen)

    return {
        "artifact": "v2-c13 national profile path",
        "schema_version": CONTRACT_VERSION,
        "created_at": _dt.datetime.now(
            _dt.timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git(),

        "contract": vertrag,
        "contract_fingerprint": _stabil(vertrag),

        "state": messung,
        "state_fingerprint": _stabil(messung),

        "fingerprint_separation": (
            "Zwei getrennte Fingerabdruecke. Der Vertrag aendert sich "
            "nur, wenn jemand eine Regel anfasst; die Messung aendert "
            "sich, sobald neue Spieldaten vorliegen. In C11 steckte "
            "beides in einem Wert, und man konnte nicht unterscheiden, "
            "ob sich die Regel oder nur die Belegung geaendert hatte."),

        "unchanged_upstream": {
            "c9_schema_fingerprint": e9.schema_fingerprint(),
            "c9_selected_features": len(e9.selected_columns()),
            "c10_cutoff_hour": pc.CUTOFF_HOUR,
            "c10_inclusive": pc.CUTOFF_INCLUSIVE,
        },

        "what_this_does_not_claim": [
            "Kein Beleg, dass das Modell jetzt besser ist - C13 misst "
            "Abdeckung, nicht Guete.",
            "Keine Freigabe. Die Registry bleibt unveraendert, das "
            "C12-Urteil bleibt rejected.",
            "Die verbleibenden Ausschluesse sind echte Datenluecken und "
            "werden nicht wegdefiniert.",
        ],
    }


def write_artifact(pfad=None, zeilen=None):
    """Das Artefakt atomar schreiben."""
    import os
    import pathlib
    import tempfile

    pfad = pathlib.Path(pfad or ARTIFACT_PATH)
    pfad.parent.mkdir(parents=True, exist_ok=True)

    inhalt = json.dumps(build_artifact(zeilen), indent=2,
                        ensure_ascii=False, sort_keys=False)

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
