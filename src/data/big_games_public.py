"""
Oeffentliches Bestenlisten-Artefakt fuer Big Games (V2).

DAS PROBLEM
-----------
Der gesammelte Datensatz liegt unter data/big_games/ und ist dort
ABSICHTLICH von der Versionsverwaltung ausgenommen (.gitignore: "bleibt
bewusst server-seitig und ungeteilt"). Diese Entscheidung gilt fuer die
privaten UEFA-/FIFA-Ranglisten und wird hier NICHT angetastet.

Die Folge war aber, dass auf einem frischen Stand ueberhaupt keine
Big-Games-Daten liegen - die Bestenliste meldete dort voellig zu Recht
"nicht verfuegbar", ohne dass ein Fehler vorlag.

DIE LOESUNG
-----------
Aus dem privaten Datensatz entsteht deterministisch ein KOMPAKTES,
OEFFENTLICHES Artefakt, das ausschliesslich das enthaelt, was die
Bestenliste wirklich rechnet:

    * je Spiel: Minuten, Bewertung, Phase, Gegnerband, Staerke,
      Bedeutung und die Statistikfelder der V2-Bewertung
    * je Spieler: Kennung, Name, Position, Liga, Verein
    * je Saison: die Fingerabdruecke der benutzten Snapshots

NICHT enthalten sind Gegnerrang, Koeffizient und die Ranglisten selbst.
Das Band ("lag innerhalb der Top N") ist genau die Stufe, die der Nutzer
in der Oberflaeche ohnehin selbst waehlt.

SPEICHERFORM
------------
Die Spielzeilen stehen als POSITIONSLISTEN, nicht als Objekte: bei rund
60.000 Spielen sparen die weggelassenen Schluesselnamen den groessten
Teil der Datei. Die Reihenfolge steht als ``match_fields`` im Kopf des
Artefakts und wird beim Lesen daraus aufgebaut - nie aus einer zweiten,
womoeglich abweichenden Liste im Code.
"""

import json
import os

from src.data import big_games_dataset as dataset

PUBLIC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "big_games_public")

PUBLIC_SCHEMA_VERSION = 1
#: v2: Gegnerkennung, Heimflagge und Ergebnis je Spiel; Gegner stehen
#: zusaetzlich in der teams-Karte, Wettbewerbsnamen in der neuen
#: competitions-Karte. Ein v1-Artefakt kann die Detailansicht nicht
#: bedienen und wird deshalb nicht mehr angenommen.
PUBLIC_CONTRACT_VERSION = "big-games-public-v2"

#: Genau die Felder, die die V2-Bewertung und die Anzeige brauchen.
#: Bewusst OHNE own_team_name/own_team_logo (stehen dedupliziert im Kopf)
#: und ohne die von V2 nicht benutzten Rohwerte.
#: GEAENDERT IN V2: Gegnerkennung, Heimflagge und Ergebnis kommen dazu.
#: Name und Wappen des Gegners stehen NICHT je Spiel, sondern einmal in
#: der teams-Karte; der Wettbewerbsname einmal in der competitions-Karte.
#: Bei rund 29.000 Spielzeilen spart das etwa 2 MB derselben
#: Zeichenketten. Rang und Koeffizient bleiben draussen.
PUBLIC_MATCH_FIELDS = (
    "fixture_id", "date", "source", "league_id", "stage", "opponent_band",
    "opponent_id", "is_home", "goals_for", "goals_against",
    "own_team_id", "position", "minutes", "rating", "strength", "importance",
    "goals", "assists", "shots_on", "passes_key", "passes_total",
    "tackles", "interceptions", "duels_total", "duels_won",
    "dribbles_success", "saves", "goals_conceded",
)


def public_path(season):
    return os.path.join(PUBLIC_DIR, f"big_games_leaderboard_{int(season)}.json")


def build_public_document(document):
    """Das oeffentliche Artefakt aus einem vollstaendigen Datensatz."""
    teams = {}
    competitions = {}
    players = []

    def merke_team(team_id, name, logo):
        """Erste belegte Nennung gewinnt; spaetere Luecken fuellen nur auf."""
        if team_id is None:
            return
        eintrag = teams.setdefault(team_id, {"name": None, "logo": None})
        if eintrag["name"] is None and name:
            eintrag["name"] = name
        if eintrag["logo"] is None and logo:
            eintrag["logo"] = logo

    for row in document["players"]:
        matches = []
        for match in row.get("matches") or []:
            merke_team(match.get("own_team_id"),
                       match.get("own_team_name"), match.get("own_team_logo"))
            # NEU IN V2: auch der Gegner landet in der gemeinsamen Karte.
            merke_team(match.get("opponent_id"),
                       match.get("opponent_name"), match.get("opponent_logo"))
            wettbewerb = match.get("league_id")
            if wettbewerb is not None and match.get("league_name"):
                competitions.setdefault(wettbewerb, match["league_name"])
            matches.append([match.get(field) for field in PUBLIC_MATCH_FIELDS])

        players.append({
            "player_id": row["player_id"],
            "name": row.get("name"),
            "position": row.get("position"),
            "pool_position": row.get("pool_position"),
            "league": row.get("league"),
            "team_id": row.get("team_id"),
            "team_name": row.get("team_name"),
            "team_logo": row.get("team_logo"),
            "matches": matches,
        })

    return {
        "schema_version": PUBLIC_SCHEMA_VERSION,
        "contract_version": PUBLIC_CONTRACT_VERSION,
        "season": document["season"],
        "status": document["status"],
        "provisional": document.get("provisional", False),
        "created_at": document.get("created_at"),
        "built_from": {
            "contract_version": document.get("contract_version"),
            "players": len(document["players"]),
        },
        # Die Fingerabdruecke der Snapshots, gegen die dieses Artefakt
        # gebaut wurde. Liegen die privaten Snapshots auf dem lesenden
        # Rechner, werden sie unveraendert streng dagegen geprueft.
        "snapshots": document.get("snapshots"),
        "eligibility": document.get("eligibility"),
        "population": document.get("population"),
        "match_fields": list(PUBLIC_MATCH_FIELDS),
        # Zwei deduplizierte Karten statt Wiederholung je Spiel. Sie
        # enthalten Namen und Wappen - also genau das, was die Oberflaeche
        # ohnehin anzeigt -, aber keinen Rang und keinen Koeffizienten.
        "teams": {str(k): v for k, v in sorted(teams.items()) if k is not None},
        "competitions": {str(k): v for k, v in sorted(competitions.items())},
        "players": sorted(players, key=lambda p: p["player_id"]),
    }


def write_public_document(document):
    os.makedirs(PUBLIC_DIR, exist_ok=True)
    dataset.write_json_atomic(public_path(document["season"]), document)


def build_from_dataset(season):
    """Liest den privaten Datensatz und schreibt das oeffentliche Artefakt."""
    document, problem = dataset.load_dataset(season, allow_public=False)
    if problem:
        raise ValueError(f"kein vollstaendiger Datensatz: {problem}")
    public = build_public_document(document)
    write_public_document(public)
    return public


def _expand(public):
    """Positionslisten zurueck in die Spielobjekte des Datensatzes."""
    felder = public.get("match_fields") or list(PUBLIC_MATCH_FIELDS)
    teams = public.get("teams") or {}
    competitions = public.get("competitions") or {}
    players = []
    for row in public.get("players") or []:
        matches = []
        for werte in row.get("matches") or []:
            match = dict(zip(felder, werte))
            team = teams.get(str(match.get("own_team_id"))) or {}
            match["own_team_name"] = team.get("name")
            match["own_team_logo"] = team.get("logo")
            # NEU IN V2: Gegner und Wettbewerb aus den deduplizierten
            # Karten zurueckholen. Fehlt ein Eintrag, bleibt das Feld None
            # - die Anzeige faellt dann auf ihren Unbekannt-Text zurueck,
            # statt etwas zu erfinden.
            gegner = teams.get(str(match.get("opponent_id"))) or {}
            match["opponent_name"] = gegner.get("name")
            match["opponent_logo"] = gegner.get("logo")
            match["league_name"] = competitions.get(str(match.get("league_id")))
            matches.append(match)
        players.append({**{k: v for k, v in row.items() if k != "matches"},
                        "matches": matches})
    return players


def load_public(season):
    """
    (Dokument, Problem) - in der Form, die big_games_dataset erwartet.

    Das Artefakt ist eine versionierte, mitgelieferte Datei des
    Repositorys; es wird deshalb so weit geprueft, wie es ohne die
    privaten Snapshots ueberhaupt geht: Vertrag, Saison und Vollstaendig-
    keit. Liegen die privaten Snapshots vor, prueft der Aufrufer
    zusaetzlich deren Fingerabdruecke - unveraendert streng.
    """
    document = dataset.read_json_memoized(public_path(season))
    if document is None:
        return None, dataset.REASON_DATASET_MISSING
    if (document.get("schema_version") != PUBLIC_SCHEMA_VERSION
            or document.get("contract_version") != PUBLIC_CONTRACT_VERSION
            or document.get("season") != season
            or not isinstance(document.get("players"), list)):
        return None, dataset.REASON_DATASET_INVALID
    if document.get("status") != dataset.STATUS_COMPLETE:
        return None, dataset.REASON_DATASET_INCOMPLETE

    return {
        "schema_version": dataset.DATASET_SCHEMA_VERSION,
        "contract_version": dataset.DATASET_CONTRACT_VERSION,
        "season": document["season"],
        "status": document["status"],
        "provisional": document.get("provisional", False),
        "created_at": document.get("created_at"),
        "eligibility": document.get("eligibility"),
        "snapshots": document.get("snapshots"),
        "population": document.get("population"),
        "players": _expand(document),
        "source": "public_artifact",
    }, None


__all__ = [
    "PUBLIC_DIR", "PUBLIC_SCHEMA_VERSION", "PUBLIC_CONTRACT_VERSION",
    "PUBLIC_MATCH_FIELDS", "public_path", "build_public_document",
    "write_public_document", "build_from_dataset", "load_public",
]
