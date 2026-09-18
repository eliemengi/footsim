"""
Die Team-Liga-Zuordnung als EIN Vertrag fuer Messung und Auslieferung
(V2-C19).

DAS PROBLEM, DAS HIER VERSCHWINDET
----------------------------------
Bis C18 gab es zwei Zuordnungen, die niemand gegeneinander geprueft
hat:

  - Die MESSUNG nahm c14.team_league_map(): jeden Verein, der in
    irgendeiner lokalen Ligadatei vorkommt. 146 Vereine.
  - Das BUNDLE nahm nur die Vereine, die in den Trainings-CL-Partien
    auftauchten. 63 Vereine.

Beide Karten trugen dieselbe Bedeutung im Namen und meinten etwas
anderes. Nachgemessen in C18: Auf 188 von 283 Standardpartien wandte
die Evaluation einen Ligafaktor an, den die Laufzeit mit der Karte des
Bundles gar nicht anwenden KONNTE. Das ausgelieferte Modell war ein
anderes als das gemessene - nicht in den Parametern, sondern in dem,
was es ueberhaupt zuordnen kann.

Ein Modell, dessen Messung mehr weiss als seine Auslieferung, ist
nicht zu wenig genau. Es ist falsch etikettiert.

DIE ZEITLICHE FRAGE, DIE DABEI AUFGEHT
--------------------------------------
Die alte Karte war ueber den GESAMTEN lokalen Bestand gebildet und
kannte damit auch Saisons, die nach dem Testzeitpunkt eines Folds
liegen. Fuer eine Struktureigenschaft wie "in welcher Liga spielt
dieser Verein" wirkt das harmlos. Es ist es nicht: Ein Verein, der
erst 2025 in einer Ligadatei auftaucht, war 2023 kein bekannter
Verein, und ein Fold, der 2024 testet, darf ihn nicht kennen.

Deshalb traegt jede Karte hier eine OBERGRENZE. Sie ist Teil ihrer
Identitaet und geht in ihren Fingerabdruck ein. Gemessen betrifft das
real 32 Vereine: 114 Vereine bis 2023, 132 bis 2024, 146 bis 2025.

WAS HIER AUSDRUECKLICH NICHT PASSIERT
-------------------------------------
Kein Namensraten, kein Abgleich ueber zufaellig gleiche Zahlen, keine
Sonderregel fuer einen Verein oder eine Liga. Wer sich nicht ueber den
geprueften Crosswalk aufloesen laesst, bekommt keinen Eintrag - und
die Laufzeit meldet das als das, was es ist: ein unbekannter Verein,
nicht eine unbekannte Liga.

DIE ZWEITE FALLE, DIE C19 AUFGEDECKT HAT
----------------------------------------
Mit der groesseren Karte kommen Vereine vor, deren Liga bekannt ist,
fuer die das Modell aber nichts gelernt hat. C18 liess die Laufzeit in
diesem Fall die ganze Korrektur ausfallen - die Messung dagegen
rechnete weiter und behandelte die unbekannte Liga als Beitrag 0.
Solange die Bundlekarte nur die 63 Vereine der CL-Trainingshistorie
trug, kam der Fall nicht vor. Mit 146 Vereinen kam er vor und haette
52 der 283 Standardpartien anders gerechnet als die akzeptierte
Messung. Die Laufzeit folgt jetzt der Messung.
"""

import collections
import datetime as _dt
import hashlib
import json
import os
import pathlib
import subprocess

CONTRACT_VERSION = "v2-c19.1"

ARTIFACT_PATH = "data/ml/c19_league_map_contract.json"

#: Der kanonische Namensraum. Die Champions League wird in
#: football-data-Kennungen gefuehrt; alles andere wird darauf
#: uebersetzt, nie umgekehrt.
CANONICAL_NAMESPACE = "football-data.org"

#: Was eine Zuordnung NICHT liefern kann, und wie das heisst.
#:
#: Die beiden Faelle sind NICHT dasselbe, auch nicht im Ergebnis:
#: Ein fehlender Verein laesst die Lambdas unveraendert, eine Liga
#: ohne gelernte Werte traegt 0 bei und laesst die BEKANNTE Seite
#: weiter korrigieren. Genau so hat league_strength.apply_factors
#: gemessen; die Laufzeit folgt dem.
UNKNOWN_TEAM = "team_not_in_map"
LEAGUE_WITHOUT_PARAMS = "league_without_parameters"


def _stabil(block):
    """Ein Fingerabdruck, der nicht an der Schluesselreihenfolge haengt."""
    text = json.dumps(block, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:                                    # pragma: no cover
        return None


# ---------------------------------------------------------------------------
# Der unveraenderliche Teil: die Regeln
# ---------------------------------------------------------------------------

def contract():
    """
    Die Regeln der Zuordnung - ohne eine einzige Messung.

    Bewusst getrennt vom Ergebnis: Der Fingerabdruck der REGELN darf
    sich nicht aendern, nur weil eine Saison hinzugekommen ist.
    """
    from src.data import national_sources as ns

    return {
        "version": CONTRACT_VERSION,
        "purpose": ("eine Team-Liga-Zuordnung fuer Messung, Bundlebau "
                    "und Laufzeit - nicht drei"),

        "canonical_namespace": CANONICAL_NAMESPACE,
        "canonical_key_type": "int",

        "sources": {
            "kind": "ausschliesslich lokale, bereits vorhandene "
                    "Saisondateien der nationalen Ligen",
            "league_codes": sorted(ns.profile_source_codes()),
            "league_count": len(ns.profile_source_codes()),
            "by_provider": {p: sorted(ns.codes_for_provider(p))
                            for p in sorted(ns.PROVIDERS)},
            "no_network": True,
            "no_live_file_at_runtime": (
                "Die Laufzeit liest diese Dateien NICHT. Sie benutzt "
                "die im Bundle eingefrorene Karte. Zwei Bundles duerfen "
                "nicht je nach Plattenstand verschieden rechnen."),
        },

        "provider_resolution": {
            "bridge": "src.features.team_identity.to_football_data",
            "basis": "gepruefter Crosswalk aus lokalen Dateien",
            "ambiguous_targets_dropped": True,
            "forbidden": [
                "numerische Gleichheit ueber Providergrenzen",
                "Namensabgleich oder Fuzzy-Matching",
                "Sonderregeln je Verein oder Liga",
            ],
            "unresolvable": ("kein Eintrag; der Verein bleibt "
                             "unbekannt und wird gezaehlt"),
        },

        "temporal_rule": {
            "bounded_by": "upto_season",
            "meaning": ("es werden ausschliesslich Saisons s <= "
                        "upto_season gelesen"),
            "why": ("Eine Foldzuordnung darf nichts kennen, was nach "
                    "ihrem Testzeitpunkt liegt - auch keine spaetere "
                    "Ligazugehoerigkeit und keinen spaeter erst "
                    "auftauchenden Verein."),
            "part_of_fingerprint": True,
        },

        "conflict_rule": {
            "case": ("derselbe Verein erscheint im zugelassenen "
                     "Zeitfenster in mehr als einer Liga"),
            "resolution": "kein Eintrag",
            "why": ("Ein Profil, das zwei Ligen gehoeren koennte, "
                    "gehoert keiner. Dieselbe Regel wie im Crosswalk: "
                    "unbekannt ist besser als vielleicht falsch."),
            "diagnosed_as": "ambiguous_leagues",
        },

        "unknown_semantics": {
            UNKNOWN_TEAM: {
                "meaning": "der Verein steht nicht in der Karte",
                "factor": 1.0,
                "note": ("ein bislang nicht in der CL aufgetretener "
                         "Verein ist NICHT automatisch eine unbekannte "
                         "Liga"),
            },
            LEAGUE_WITHOUT_PARAMS: {
                "meaning": ("die Liga des Vereins ist bekannt, das "
                            "Modell hat fuer sie aber nichts gelernt"),
                "contribution": 0.0,
                "correction_still_applied": True,
                "why": ("Das ist NICHT dasselbe wie ein fehlender "
                        "Verein. Die bekannte Seite behaelt ihre "
                        "Offsets, die unbekannte traegt 0 bei - genau "
                        "so hat league_strength.apply_factors "
                        "gemessen. Beide Seiten auf 1 zu setzen waere "
                        "eine andere Rechnung als die akzeptierte."),
            },
            "identical_on_both_paths": True,
        },

        "binds": ["evaluation", "bundle", "runtime"],
        "binding_note": ("Messung und Bundle bauen die Karte ueber "
                         "DIESELBE Funktion. Es gibt keine zweite, "
                         "unabhaengig gepflegte Karte."),
    }


def contract_fingerprint():
    """Der Fingerabdruck der REGELN, ohne jede Messung."""
    return _stabil(contract())


# ---------------------------------------------------------------------------
# Der gemessene Teil: die Karte
# ---------------------------------------------------------------------------

def build_team_league_map(upto_season):
    """
    Die Zuordnung bis einschliesslich `upto_season`.

    Rueckgabe: (karte, diagnose).

    karte:    {football-data-Team-ID (int): Liga-Code}
    diagnose: Zaehlwerte, Konflikte und der Fingerabdruck der Karte.

    `upto_season` ist PFLICHT und hat kein Standardargument. Ein
    Vorgabewert waere hier die gefaehrlichste Bequemlichkeit: Wer ihn
    vergisst, bekaeme stillschweigend die neueste Karte und damit
    Wissen aus der Zukunft des Folds, den er gerade misst.
    """
    from src.data import national_sources as ns
    from src.data.historical_loader import (AVAILABLE_HISTORICAL_SEASONS,
                                            season_file_path)
    from src.features.team_identity import to_football_data

    if upto_season is None:
        raise ValueError(
            "upto_season ist Pflicht - ohne Obergrenze entsteht eine "
            "Karte, die mehr weiss als der Fold, der sie benutzt")

    zaehler = collections.defaultdict(collections.Counter)
    saisons = sorted(s for s in AVAILABLE_HISTORICAL_SEASONS
                     if s <= upto_season)
    gelesen, fehlend, unaufloesbar = 0, 0, 0

    for code in sorted(ns.profile_source_codes()):
        provider = ns.league_provider(code)
        for saison in saisons:
            pfad = pathlib.Path(season_file_path(code, saison))
            if not pfad.is_file():
                fehlend += 1
                continue
            try:
                daten = json.loads(pfad.read_text(encoding="utf-8"))
            except (OSError, ValueError):             # pragma: no cover
                fehlend += 1
                continue
            gelesen += 1
            for partie in (daten.get("matches") or []):
                for feld in ("home_id", "away_id"):
                    roh = partie.get(feld)
                    if roh is None:
                        continue
                    tid = int(roh)
                    if provider == ns.PROVIDER_API_FOOTBALL:
                        tid = to_football_data(tid)
                        if tid is None:
                            unaufloesbar += 1
                            continue
                    zaehler[tid][code] += 1

    # Ein Verein in zwei Ligen ist ein Widerspruch der Quellen, keine
    # Mehrheitsfrage. Er fliegt heraus und wird benannt.
    mehrdeutig = {tid: sorted(c) for tid, c in zaehler.items()
                  if len(c) > 1}
    karte = {tid: next(iter(c)) for tid, c in zaehler.items()
             if len(c) == 1}

    diagnose = {
        "upto_season": upto_season,
        "seasons_used": saisons,
        "files_read": gelesen,
        "files_missing": fehlend,
        "teams": len(karte),
        "unresolvable_id_occurrences": unaufloesbar,
        "ambiguous_leagues": {str(k): v for k, v in sorted(
            mehrdeutig.items())},
        "ambiguous_count": len(mehrdeutig),
        "leagues_present": sorted({liga for liga in karte.values()}),
        "teams_per_league": dict(sorted(
            collections.Counter(karte.values()).items())),
        "contract_fingerprint": contract_fingerprint(),
        "map_fingerprint": map_fingerprint(karte, upto_season),
    }
    return karte, diagnose


def map_fingerprint(karte, upto_season):
    """
    Der Fingerabdruck EINER Karte, samt ihrer Obergrenze.

    Die Obergrenze gehoert hinein, nicht daneben: Zwei Karten mit
    demselben Inhalt, aber verschiedenen Zeitfenstern sind nicht
    dieselbe Karte - die eine durfte mehr lesen als die andere und
    hatte nur zufaellig kein anderes Ergebnis.
    """
    return _stabil({
        "upto_season": upto_season,
        "namespace": CANONICAL_NAMESPACE,
        "entries": {str(k): v for k, v in sorted(karte.items())},
    })


def bundle_map(karte):
    """
    Die Karte in der Form, die das Bundle traegt.

    Schluessel als Zeichenkette, weil JSON keine ganzzahligen
    Schluessel kennt und die Laufzeit ohnehin ueber str(team_id)
    nachschlaegt.
    """
    return {str(tid): liga for tid, liga in sorted(karte.items())}


def classify(karte, team_id, attack, defence):
    """
    Warum eine Partieseite korrigierbar ist oder nicht.

    Genau die Unterscheidung, um die es diesem Vertrag geht:
    Ein Verein ohne Eintrag ist etwas anderes als eine Liga, fuer die
    das Modell nichts gelernt hat. Beide ergeben Faktor 1, und nur
    einer davon ist ein Grund, die Karte zu erweitern.
    """
    if team_id is None:
        return None, UNKNOWN_TEAM
    liga = karte.get(str(team_id)) if isinstance(
        next(iter(karte), ""), str) else karte.get(team_id)
    if not liga:
        return None, UNKNOWN_TEAM
    if liga not in (attack or {}) and liga not in (defence or {}):
        # Bekannte Liga, keine gelernten Werte. Die Korrektur laeuft
        # trotzdem; diese Seite traegt 0 bei. Siehe unknown_semantics
        # im Vertrag.
        return liga, LEAGUE_WITHOUT_PARAMS
    return liga, None


# ---------------------------------------------------------------------------
# Das Artefakt
# ---------------------------------------------------------------------------

def build_artifact(upto_seasons):
    """
    Das Vertragsartefakt mit einer Karte je gemessener Obergrenze.

    Mehrere Obergrenzen in EINEM Artefakt, damit die zeitliche
    Staffelung sichtbar bleibt und ein Leser nicht drei Dateien
    vergleichen muss, um zu sehen, dass die Karte mit der Saison
    waechst.
    """
    vertrag = contract()
    karten = {}
    for saison in sorted(upto_seasons):
        _karte, diagnose = build_team_league_map(saison)
        karten[str(saison)] = diagnose

    return {
        "artifact": "v2-c19 league map contract",
        "schema_version": CONTRACT_VERSION,
        "created_at": _dt.datetime.now(
            _dt.timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git(),
        "contract": vertrag,
        "contract_fingerprint": _stabil(vertrag),
        "maps": karten,
    }


def write_artifact(upto_seasons, pfad=None):
    """Das Artefakt deterministisch schreiben."""
    artefakt = build_artifact(upto_seasons)
    ziel = pfad or os.path.join(_repo_root(), ARTIFACT_PATH)
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    tmp = ziel + ".tmp"
    with open(tmp, "w", encoding="utf-8") as datei:
        json.dump(artefakt, datei, ensure_ascii=False, indent=1,
                  sort_keys=True)
        datei.write("\n")
    os.replace(tmp, ziel)
    return ziel, artefakt


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
