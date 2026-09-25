"""
Big-Games-Datensatz fuer die Bestenliste (Block C24).

WARUM ES DEN DATENSATZ BRAUCHT
------------------------------
Der Big-Games-Einzelvergleich rechnet je Spieler und bei Bedarf: Profil,
Spielplaene seiner Vereine, Einzelspielerwerte der qualifizierten Spiele.
Eine Bestenliste braucht dasselbe fuer die GESAMTE Population einer
Saison. Aus den wenigen zufaellig gecachten Einzelvergleichen liesse sich
keine ehrliche Rangliste bauen - sie waere eine Liste der Spieler, die
jemand zufaellig verglichen hat.

Dieser Datensatz wird vom Sammler (src/data/big_games_collector.py)
geschrieben und von der Route ausschliesslich gelesen.

EINE DEFINITION FUER LISTE UND EINZELVERGLEICH
----------------------------------------------
Jede Zeile entsteht aus big_games_loader.compute_player_big_games_uncached()
- derselben Funktion, die der Einzelvergleich mit Cache aufruft:
dieselbe Klassifikation, dieselbe Fixture-Deduplizierung, dieselbe
Aggregation (big_games.aggregate_big_games), dieselbe Mindestmenge
(big_games.has_sufficient_sample). Die Kennzahlen pro 90 und die Quoten
entstehen mit player_metrics.per90 und player_metrics.rate aus genau den
Rohsummen, die auch der Einzelvergleich zeigt.

Fuer Zeitraeume ueber mehrere Saisons speichert jede Zeile die kompakten
Spielzeilen. Die Liste fuehrt sie mit derselben Deduplizierung und
derselben Aggregation zusammen wie der Einzelvergleich.

PRIVATE RANGLISTEN
------------------
Die UEFA- und FIFA-Listen verlassen den Server nie. Der Datensatz haelt je
Spiel nur abgeleitete Werte (Kontextgewicht, Gegnerstaerke, Bedeutung)
und je Saison einen Fingerabdruck der benutzten Snapshots - keinen Rang
und keinen Koeffizienten.
"""

import hashlib
import html
import json
import os
import tempfile
from datetime import datetime, timezone

from src.data.player_metrics import per90, rate

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: Liegt unter data/big_games/ und ist damit wie die privaten Snapshots
#: von der Versionsverwaltung ausgenommen (.gitignore).
DATASET_DIR = os.path.join(_PROJECT_ROOT, "data", "big_games", "leaderboard")

DATASET_SCHEMA_VERSION = 1
#: v2: Rangfolge fest nach big_game_score, Zeilen tragen den Score,
#: Snapshot-Fingerabdruecke werden beim Lesen gegengeprueft.
#: v3: Je Spiel kommen Gegnerband und Phase dazu, damit die waehlbare
#: Gegnerhuerde SERVERSEITIG nachgerechnet werden kann, und die Rangfolge
#: entsteht aus der positionsgerechten V2-Bewertung. Ein v2-Datensatz
#: traegt diese Felder nicht und wird deshalb bewusst nicht mehr
#: angenommen - lieber "nicht verfuegbar" als eine Liste, deren Huerde
#: nur behauptet waere.
#: v4: Je Spiel kommen Gegnerkennung, Heim-/Auswaertsflagge und das
#: Ergebnis aus eigener Sicht dazu. Erst damit laesst sich eine einzelne
#: Big-Game-Partie erzaehlen ("2:1 bei Real Madrid") statt nur zaehlen.
#: Ein v3-Datensatz traegt diese Felder nicht und wird deshalb bewusst
#: nicht mehr angenommen - lieber "nicht verfuegbar" als eine Detailliste,
#: die Ergebnisse verschweigt oder erfindet.
DATASET_CONTRACT_VERSION = "big-games-leaderboard-v4"

STATUS_COMPLETE = "complete"
STATUS_INCOMPLETE = "incomplete"

#: Pilotsaison des Sammlers: 2025/26.
PILOT_SEASON = 2025

#: Was je Spiel gespeichert wird: genau die Felder, die Aggregation,
#: Positionsregel und Anzeige brauchen.
#:
#: WEITERHIN KEIN GEGNERRANG UND KEIN KOEFFIZIENT. Neu sind ``stage`` und
#: ``opponent_band``: die Phase ist ohnehin oeffentlich (sie steht auf
#: jeder Spielkarte), und das Band sagt nur "lag innerhalb der Top N" -
#: genau die Stufe, die der Nutzer selbst auswaehlt. Die vollstaendige
#: private Rangliste bleibt damit unveraendert auf dem Server.
#: GEAENDERT IN V4: Dazu kommen die Felder, ohne die eine Spielzeile nicht
#: erzaehlbar ist - gegen WEN, in welchem WETTBEWERB, WO und mit welchem
#: AUSGANG. Alle lagen upstream laengst vor (classify_fixture) und wurden
#: hier bisher nur verworfen.
#:
#: Name und Wappen des Gegners sowie der Wettbewerbsname stehen NUR im
#: privaten Datensatz je Spiel. Das oeffentliche Artefakt fuehrt sie
#: dedupliziert in eigenen Karten (teams/competitions) und speichert je
#: Spiel bloss die Kennung - sonst waeren es rund 2 MB derselben
#: Zeichenketten.
#:
#: Weiterhin NICHT dabei: Gegnerrang und Koeffizient.
MATCH_FIELDS = (
    "fixture_id", "date", "source", "league_id", "league_name",
    "stage", "opponent_band",
    "opponent_id", "opponent_name", "opponent_logo",
    "is_home", "goals_for", "goals_against",
    "own_team_id", "own_team_name", "own_team_logo",
    "position", "minutes", "rating", "weight", "strength", "importance",
    "goals", "assists", "shots_total", "shots_on", "passes_key",
    "passes_total", "tackles", "interceptions", "duels_total", "duels_won",
    "dribbles_attempts", "dribbles_success", "saves", "goals_conceded",
)

#: Statistikfelder, deren Fehlen je Spieler gezaehlt wird.
MISSINGNESS_FIELDS = (
    "rating", "goals", "assists", "shots_on", "passes_key", "tackles",
    "interceptions", "duels_total", "duels_won", "saves", "goals_conceded",
)

#: Gruende fuer available=false.
REASON_DATASET_MISSING = "dataset_missing"
REASON_DATASET_INCOMPLETE = "dataset_incomplete"
REASON_DATASET_INVALID = "dataset_invalid"
REASON_SNAPSHOT_MISSING = "snapshot_missing"
REASON_SNAPSHOT_CHANGED = "snapshot_changed"
REASON_NO_ELIGIBLE = "no_eligible_players"
#: Der angefragte Spieler steht in keinem Datensatz des Zeitraums.
REASON_PLAYER_MISSING = "player_not_in_dataset"


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def dataset_path(season):
    return os.path.join(DATASET_DIR, f"big_games_{int(season)}.json")


def checkpoint_path(season):
    return os.path.join(DATASET_DIR, f"checkpoint_{int(season)}.json")


def lock_path():
    return os.path.join(DATASET_DIR, "collector.lock")


# ---------------------------------------------------------------------------
# Kennzahlen aus den Rohsummen
# ---------------------------------------------------------------------------

def big_games_metrics(summary):
    """
    Die Bestenlisten-Kennzahlen aus einer Big-Games-Zusammenfassung.

    Dieselben Schluessel wie im Poolkatalog (player_metrics.METRICS), damit
    Richtung und Beschriftung aus einer Quelle kommen. Fehlt eine Rohsumme,
    fehlt die Kennzahl - nie 0.
    """
    raw = (summary or {}).get("raw") or {}
    minutes = raw.get("minutes")
    return {
        "goal_contributions_per90": per90(raw.get("goal_assists"), minutes),
        "shots_on_per90": per90(raw.get("shots_on"), minutes),
        "key_passes_per90": per90(raw.get("passes_key"), minutes),
        "tackles_per90": per90(raw.get("tackles"), minutes),
        "interceptions_per90": per90(raw.get("interceptions"), minutes),
        "duels_won_pct": rate(raw.get("duels_won"), raw.get("duels_total")),
        "saves_per90": per90(raw.get("saves"), minutes),
        "conceded_per90": per90(raw.get("goals_conceded"), minutes),
        "rating": (summary or {}).get("avg_rating"),
    }


def display_name(name):
    """
    Anzeigename eines Spielers, einmal entschaerft.

    Der Anbieter liefert Apostrophnamen HTML-maskiert ("N. O&apos;Reilly",
    "M&apos;Bala Nzola"). Ungeprueft uebernommen stuenden diese Zeichen
    woertlich in der Liste. Die Oberflaeche setzt Namen ausschliesslich
    ueber textContent (static/script.js: make()), deshalb ist das
    Aufloesen hier eine reine Darstellungskorrektur und oeffnet keinen
    Einschleusungsweg - aus "&lt;b&gt;" wird Text, nie Auszeichnung.
    """
    if not isinstance(name, str):
        return name
    return html.unescape(name)


def compact_match(match):
    return {field: match.get(field) for field in MATCH_FIELDS}


def missingness(matches):
    """Je Statistikfeld: in wie vielen gespielten Big Games fehlte der Wert."""
    played = [m for m in matches if (m.get("minutes") or 0) > 0]
    return {
        field: sum(1 for m in played if m.get(field) is None)
        for field in MISSINGNESS_FIELDS
    }


def aggregate_matches(matches):
    """
    Spielzeilen -> (deduplizierte Spiele, Zusammenfassung).

    Exakt die Reihenfolge des Einzelvergleichs: ueber die stabile
    Fixture-ID deduplizieren, chronologisch sortieren, EINMAL aggregieren.
    """
    from src.features import big_games, national_big_games

    unique = national_big_games.dedupe_fixtures(list(matches))
    unique.sort(key=lambda m: (m.get("date") or "", m["fixture_id"]))
    return unique, big_games.aggregate_big_games(unique)


def qualified_player_matches(row_matches, uefa_max_rank, fifa_max_rank,
                             mode=None):
    """
    Die unter der gewaehlten Huerde zaehlenden Spiele EINES Spielers.

    DIE EINZIGE WAHRHEITSQUELLE der Zulassung - Bestenliste UND
    Detailansicht gehen ausschliesslich hier durch. Genau deshalb ist die
    Gleichheit

        len(qualified_player_matches(...)) == Big Games der Bestenliste

    keine Zusicherung, die jemand pflegen muss, sondern eine Folge davon,
    dass es nur einen Rechenweg gibt. Eine zweite Implementierung fuer die
    Details waere der sichere Weg in zwei Wahrheiten.

    Reihenfolge wie im Einzelvergleich: erst ueber die stabile Fixture-ID
    deduplizieren, dann die Huerde anwenden.

    mode reicht die Big-Game-Definition durch (kontextuell/streng). Ohne
    Angabe gilt kontextuell - der bisherige Weg.
    """
    from src.features import big_games_rules

    alle, _summary = aggregate_matches(row_matches)
    return big_games_rules.qualified_matches(
        alle, uefa_max_rank, fifa_max_rank,
        big_games_rules.normalize_mode(mode))


def _latest_club_team(matches):
    """Verein der juengsten Vereinspartie - fuer Anzeige und Wappen."""
    for match in sorted(matches, key=lambda m: (m.get("date") or "", m["fixture_id"]),
                        reverse=True):
        if match.get("source", "club") == "club" and match.get("own_team_name"):
            return match.get("own_team_id"), match.get("own_team_name"), match.get("own_team_logo")
    return None, None, None


def build_player_row(pool_entry, season, range_result):
    """
    Eine Datensatzzeile aus dem Ergebnis von
    compute_player_big_games_uncached(player_id, season, season).
    """
    from src.data.big_games_loader import dominant_position
    from src.data.player_metrics import normalize_position
    from src.features.player_leaderboard import safe_crest

    matches = [compact_match(m) for m in range_result.get("matches") or []]
    summary = range_result.get("summary") or {}
    raw = summary.get("raw") or {}
    pool_position = normalize_position(pool_entry.get("position"))
    team_id, team_name, team_logo = _latest_club_team(matches)

    return {
        "player_id": pool_entry["player_id"],
        "name": display_name(pool_entry.get("name")),
        "season": season,
        "position": dominant_position(matches) or pool_position,
        "pool_position": pool_position,
        "league": pool_entry.get("league_code"),
        "team_id": team_id if team_id is not None else pool_entry.get("team_id"),
        "team_name": team_name or pool_entry.get("team_name"),
        "team_logo": safe_crest(team_logo),
        "fixture_ids": [m["fixture_id"] for m in matches if (m.get("minutes") or 0) > 0],
        "big_games": raw.get("matches", 0),
        "minutes": raw.get("minutes", 0),
        "raw_totals": raw,
        "metrics": big_games_metrics(summary),
        "rating": summary.get("avg_rating"),
        # Unveraendert aus aggregate_big_games(); None unterhalb der
        # Mindestmenge oder ohne bewertete Einsaetze.
        "big_game_score": summary.get("big_game_score"),
        "sufficient_sample": bool(summary.get("sufficient_sample")),
        "missing": missingness(matches),
        "matches": matches,
        "seasons": [
            {key: s.get(key) for key in (
                "season", "available", "provisional", "club_available",
                "national_available", "match_count")}
            for s in range_result.get("seasons") or []
        ],
    }


# ---------------------------------------------------------------------------
# Snapshot-Fingerabdruecke
# ---------------------------------------------------------------------------

def _fingerprint(payload):
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def snapshot_fingerprints(season, fifa_years=()):
    """
    Fingerabdruecke der benutzten Snapshots - nie deren Inhalt.

    Wird der private Snapshot einer Saison ersetzt, aendert sich der
    Fingerabdruck; ein Datensatz auf altem Stand ist dadurch erkennbar.
    """
    from src.data import fifa_rankings, uefa_coefficients

    uefa = uefa_coefficients.load_snapshot(season)
    result = {
        "uefa": _fingerprint(uefa) if uefa.get("available") else None,
        "uefa_provisional": bool(uefa.get("provisional")),
        "fifa": {},
    }
    for year in sorted(set(int(y) for y in fifa_years if y)):
        snapshot = fifa_rankings.load_snapshot(year)
        result["fifa"][str(year)] = (
            _fingerprint(snapshot) if snapshot.get("available") else None)
    return result


# ---------------------------------------------------------------------------
# Lesen und Schreiben
# ---------------------------------------------------------------------------

def write_json_atomic(path, payload):
    """Erst in eine temporaere Datei, dann umbenennen - nie halb geschrieben."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def read_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


#: Gelesene Datensaetze, gebunden an Pfad, Aenderungszeit und Groesse.
#:
#: Der Datensatz einer Saison ist mehrere Megabyte gross. Ohne diesen
#: Zwischenspeicher wuerde er bei JEDER Anfrage neu geparst - auch beim
#: blossen Fuellen der Saisonauswahl. Aendert sich die Datei, aendert sich
#: der Schluessel: ein neuer Sammellauf wird also sofort gesehen, ohne
#: dass irgendwo von Hand aufgeraeumt werden muesste.
_DOCUMENT_MEMO = {}
_DOCUMENT_MEMO_MAX = 8


def read_json_memoized(path):
    try:
        stat = os.stat(path)
    except OSError:
        return None
    schluessel = (path, stat.st_mtime_ns, stat.st_size)
    if schluessel in _DOCUMENT_MEMO:
        return _DOCUMENT_MEMO[schluessel]
    document = read_json(path)
    if document is not None:
        if len(_DOCUMENT_MEMO) >= _DOCUMENT_MEMO_MAX:
            _DOCUMENT_MEMO.clear()
        _DOCUMENT_MEMO[schluessel] = document
    return document


def clear_document_memo():
    _DOCUMENT_MEMO.clear()


def has_leaderboard_data(season):
    """
    Liegt fuer diese Saison eine auswertbare Bestenliste vor?

    Genau dieselbe Pruefung wie in der Route - vollstaendiger Datensatz
    (privat oder oeffentlich) UND unveraenderte historische Snapshots.
    Die Oberflaeche kann damit von vornherein die richtige Saison
    vorschlagen, statt den Nutzer auf eine leere Liste laufen zu lassen.
    """
    document, problem = load_dataset(season)
    if problem or document is None:
        return False
    return snapshot_problem(document) is None


def build_dataset(season, rows, population, collector_meta, fifa_years=()):
    """Das vollstaendige Datensatzdokument einer Saison."""
    from src.api.apisports_api import CURRENT_SEASON
    from src.features import big_games

    fingerprints = snapshot_fingerprints(season, fifa_years)
    # Fail closed: Ohne den historischen Snapshot der Saison (bzw. eines
    # benutzten FIFA-Jahres) gibt es keinen gueltigen Datensatz. Es wird
    # nie eine andere Saison und nie eine andere Rangquelle eingesetzt.
    if fingerprints["uefa"] is None or any(v is None for v in fingerprints["fifa"].values()):
        raise ValueError("historischer Snapshot fehlt - kein Datensatz")
    return {
        "schema_version": DATASET_SCHEMA_VERSION,
        "contract_version": DATASET_CONTRACT_VERSION,
        "season": season,
        "status": STATUS_COMPLETE,
        "provisional": season >= CURRENT_SEASON or fingerprints["uefa_provisional"],
        "created_at": _now_iso(),
        "eligibility": {
            "min_matches": big_games.MIN_BIG_GAMES,
            "min_minutes": big_games.MIN_BIG_GAME_MINUTES,
        },
        "snapshots": fingerprints,
        "population": population,
        "collector": collector_meta,
        "players": sorted(rows, key=lambda r: r["player_id"]),
    }


def write_dataset(document):
    """
    Schreibt einen Datensatz - ausschliesslich einen vollstaendigen.

    Ein unvollstaendiger Stand gehoert in den Checkpoint, nie hierher: eine
    halbfertige Datei duerfte nie wie eine vollstaendige aussehen.
    """
    if document.get("status") != STATUS_COMPLETE:
        raise ValueError("nur vollstaendige Datensaetze werden geschrieben")
    write_json_atomic(dataset_path(document["season"]), document)


def load_dataset(season, allow_public=True):
    """
    Rueckgabe: (dokument, problem). problem ist None oder ein Grundschluessel.

    ZWEI QUELLEN, KLARE REIHENFOLGE
    -------------------------------
    1. Der private, gesammelte Datensatz unter data/big_games/ - wenn er
       da ist, gilt er. Er ist die Quelle, aus der alles andere entsteht.
    2. Sonst das mitgelieferte oeffentliche Artefakt unter
       data/big_games_public/ (src/data/big_games_public.py).

    Der zweite Weg existiert, weil data/big_games/ bewusst nicht
    versioniert wird: ohne ihn gaebe es auf einem frischen Stand
    ueberhaupt keine Bestenliste. Die Snapshotpruefung des Aufrufers
    bleibt fuer BEIDE Wege unveraendert streng.
    """
    document = read_json_memoized(dataset_path(season))
    if document is None:
        if allow_public:
            from src.data.big_games_public import load_public
            return load_public(season)
        return None, REASON_DATASET_MISSING
    if (document.get("schema_version") != DATASET_SCHEMA_VERSION
            or document.get("contract_version") != DATASET_CONTRACT_VERSION
            or document.get("season") != season
            or not isinstance(document.get("players"), list)):
        return None, REASON_DATASET_INVALID
    if document.get("status") != STATUS_COMPLETE:
        return None, REASON_DATASET_INCOMPLETE
    return document, None


def season_coverage(season):
    """Oeffentlich unbedenkliche Abdeckung einer Saison (fuer die Route)."""
    document = read_json(dataset_path(season))
    checkpoint = read_json(checkpoint_path(season))
    population = (checkpoint or {}).get("population_size")
    done = len(((checkpoint or {}).get("players_done") or {}))
    return {
        "season": season,
        "dataset_status": (document or {}).get("status") if document else "missing",
        "collection_status": (checkpoint or {}).get("status") if checkpoint else "not_started",
        "players_collected": done,
        "population": population,
        "updated_at": (checkpoint or {}).get("updated_at"),
    }


# ---------------------------------------------------------------------------
# Bestenliste
# ---------------------------------------------------------------------------

def snapshot_problem(document):
    """
    Prueft die historischen Snapshots eines Datensatzes gegen den Server.

    Die Rangfolge beruht auf Kontextgewichten aus GENAU den Snapshots, mit
    denen der Datensatz gebaut wurde. Fehlt einer davon heute oder wurde er
    ersetzt, ist der Datensatz nicht mehr belegbar: fail closed. Geprueft
    werden nur die Snapshots DIESER Saison bzw. der benutzten FIFA-Jahre -
    eine neue aktuelle Rangliste beruehrt einen historischen Datensatz nicht.

    Rueckgabe: None oder REASON_SNAPSHOT_MISSING / REASON_SNAPSHOT_CHANGED.
    """
    stored = document.get("snapshots") or {}
    fifa_years = [int(y) for y in (stored.get("fifa") or {})]
    current = snapshot_fingerprints(document["season"], fifa_years)

    if not stored.get("uefa") or current["uefa"] is None:
        return REASON_SNAPSHOT_MISSING
    if current["uefa"] != stored["uefa"]:
        return REASON_SNAPSHOT_CHANGED
    for year, fingerprint in (stored.get("fifa") or {}).items():
        now = current["fifa"].get(str(year))
        if fingerprint is None or now is None:
            return REASON_SNAPSHOT_MISSING
        if now != fingerprint:
            return REASON_SNAPSHOT_CHANGED
    return None


def big_games_leaderboard(season_from, season_to, position, limit,
                          uefa_max_rank=None, fifa_max_rank=None, mode=None):
    """
    Big-Games-Bestenliste ueber einen Saisonbereich (V2).

    DREI SCHRITTE, JE ANFRAGE NEU
    -----------------------------
    1. ZULASSUNG DER SPIELE unter der gewaehlten Gegnerhuerde
       (big_games_rules.qualified_matches). Eine engere Huerde entfernt
       Spiele, die nur ueber den Gegner zaehlten - ein CL-Finale oder ein
       WM-Halbfinale bleibt, verliert aber den Elitebonus.
    2. ZULASSUNG DER SPIELER: mindestens
       big_games_score.RANKING_MIN_BIG_GAMES Spiele UND
       RANKING_MIN_MINUTES Minuten AUS DEN SO ZUGELASSENEN SPIELEN.
    3. BEWERTUNG der verbliebenen Population gemeinsam
       (big_games_score.score_population): positionsgerechte Kennzahlen,
       robuste Normalisierung INNERHALB der Position, Schrumpfung kleiner
       Stichproben, Mischung aus Rate und Umfang.

    Die Position filtert erst danach die ANZEIGE - normalisiert wird immer
    gegen die volle Positionsgruppe, sonst haette die Auswahl "nur
    Mittelfeld" die Bezugsgroesse veraendert.

    Verfuegbar NUR, wenn fuer JEDE Saison des Bereichs ein vollstaendiger
    Datensatz vorliegt und dessen historische Snapshots unveraendert auf
    dem Server liegen. Sonst available=false mit Grund - nie eine Liste aus
    einem Teilbestand.
    """
    from src.api.apisports_api import CURRENT_SEASON
    from src.data.big_games_loader import dominant_position
    from src.features import (
        big_games, big_games_rules, big_games_score, national_big_games)
    from src.features.player_leaderboard import (
        BIG_GAME_SCORE_KEY, POSITION_ALL, rank_rows)

    uefa_max_rank = big_games_rules.clamp_uefa_max_rank(uefa_max_rank)
    fifa_max_rank = big_games_rules.clamp_fifa_max_rank(fifa_max_rank)
    mode = big_games_rules.normalize_mode(mode)

    eligibility = {
        "min_matches": big_games_score.RANKING_MIN_BIG_GAMES,
        "min_minutes": big_games_score.RANKING_MIN_MINUTES,
        "rule": "big_games_rankable",
    }
    seasons = list(range(season_from, season_to + 1))
    coverage_seasons = [season_coverage(s) for s in seasons]

    documents = []
    problem = None
    for season in seasons:
        document, reason = load_dataset(season)
        if reason is None:
            reason = snapshot_problem(document)
        if reason:
            problem = problem or reason
        else:
            documents.append(document)

    provisional = any(s >= CURRENT_SEASON for s in seasons) or any(
        d.get("provisional") for d in documents)

    base = {
        "ranking_key": BIG_GAME_SCORE_KEY,
        "eligibility": eligibility,
        "provisional": provisional,
        # Was tatsaechlich gerechnet wurde - nicht, was angefragt war.
        "opponent_cutoffs": {
            "uefa_max_rank": uefa_max_rank,
            "fifa_max_rank": fifa_max_rank,
            "uefa_options": list(big_games.UEFA_RANK_BANDS),
            "fifa_options": list(national_big_games.FIFA_RANK_BANDS),
            # Der WIRKSAME Modus, nicht der angefragte. Die Oberflaeche
            # baut ihre Detailanfrage genau hieraus - damit kann ein
            # Auszug niemals eine andere Definition zeigen als die Zeile,
            # aus der er geoeffnet wurde.
            "big_game_mode": mode,
        },
    }
    if problem:
        return {
            **base,
            "available": False,
            "reason": problem,
            "rows": [],
            "incomplete": True,
            "coverage": {"seasons": coverage_seasons},
        }

    by_player = {}
    for document in sorted(documents, key=lambda d: d["season"]):
        for row in document["players"]:
            entry = by_player.setdefault(row["player_id"], {"rows": [], "matches": []})
            entry["rows"].append(row)
            entry["matches"].extend(row.get("matches") or [])

    considered = 0
    excluded_sample = 0
    without_score = 0

    # ---- Schritt 1 und 2: Spiele unter der Huerde, dann Spielerzulassung ----
    #
    # Bewertet wird die GANZE zugelassene Population, unabhaengig vom
    # Positionsfilter: die Normalisierung braucht die volle
    # Positionsgruppe als Bezug. Der Filter wirkt erst bei der Anzeige.
    kandidaten = []
    for player_id in sorted(by_player):
        entry = by_player[player_id]
        latest = entry["rows"][-1]
        # Dieselbe Deduplizierung wie im Einzelvergleich - ueber alle
        # Saisons des Zeitraums EINMAL.
        alle, _summary = aggregate_matches(entry["matches"])
        # Dieselbe Funktion, die auch die Detailansicht benutzt.
        matches = qualified_player_matches(
            entry["matches"], uefa_max_rank, fifa_max_rank, mode)
        group = dominant_position(matches) or dominant_position(alle) or \
            latest.get("pool_position")
        considered += 1

        inputs = big_games_score.player_inputs(matches)
        if not big_games_score.is_rankable(inputs["matches"], inputs["minutes"]):
            excluded_sample += 1
            continue
        if inputs["metrics"].get(big_games_score.METRIC_RATING) is None:
            # Genug Spiele, aber keine einzige bewertete Partie: kein
            # Score, nie 0.
            without_score += 1
            continue

        team_id, team_name, team_logo = _latest_club_team(matches)
        raw = _raw_totals(matches)
        kandidaten.append({
            "player_id": player_id,
            "position": group,
            "inputs": inputs,
            "anzeige": {
                "player_id": player_id,
                "name": display_name(latest.get("name")),
                "team_name": team_name or latest.get("team_name"),
                "team_id": team_id if team_id is not None else latest.get("team_id"),
                "team_logo": (latest.get("team_logo") if team_logo is None
                              else _safe(team_logo)),
                "league": latest.get("league"),
                "position": group,
                "minutes": inputs["minutes"],
                "appearances": inputs["matches"],
                "big_games": inputs["matches"],
                "goals": raw["goals"],
                "assists": raw["assists"],
                "goal_assists": raw["goal_assists"],
                # Angezeigt wird die echte Durchschnittsnote, nicht die
                # kontextgewichtete Rechengroesse.
                "rating": (round(inputs["avg_rating"], 2)
                           if inputs.get("avg_rating") is not None else None),
            },
        })

    # ---- Schritt 3: die Population gemeinsam bewerten ----
    bewertung = big_games_score.score_population(kandidaten)

    eligible = []
    for kandidat in kandidaten:
        if position != POSITION_ALL and kandidat["position"] != position:
            continue
        teil = bewertung[kandidat["player_id"]]
        eligible.append({
            **kandidat["anzeige"],
            "value": float(teil["score"]),
            # Nachvollziehbarkeit fuer die Oberflaeche: woher kommt der
            # Wert? Keine Modell- oder Implementierungskennung.
            # Bewusst OHNE die Woerter "weight"/"strength": die
            # Kontextgewichte je Spiel bleiben serverseitig (siehe den
            # Vertragstest in tests/test_big_games_dataset.py).
            "score_parts": {
                "quality": teil["shrunk_quality_z"],
                "volume": teil["volume_z"],
                "shrinkage": teil["shrinkage"],
                "exposure_90s": teil["weighted_90s"],
            },
        })

    # Big-Game-Score absteigend, dann mehr Big-Game-Minuten, Name, Player-ID.
    rows = rank_rows(eligible, "higher_better", limit)
    reason = None if rows else REASON_NO_ELIGIBLE
    return {
        **base,
        "available": reason is None,
        "reason": reason,
        "rows": rows,
        "incomplete": False,
        "coverage": {
            "seasons": coverage_seasons,
            "players_considered": considered,
            "excluded_min_sample": excluded_sample,
            "without_score": without_score,
            "eligible": len(eligible),
            "population": sum(len(d["players"]) for d in documents),
        },
    }


def _raw_totals(matches):
    """Rohsummen fuer die Anzeige. Fehlt alles, bleibt es None - nie 0."""
    from src.features.big_games import _goal_assist_contribution, _sum_optional

    return {
        "goals": _sum_optional([m.get("goals") for m in matches]),
        "assists": _sum_optional([m.get("assists") for m in matches]),
        "goal_assists": _sum_optional([
            _goal_assist_contribution(m.get("goals"), m.get("assists"))
            for m in matches
        ]),
    }


def _safe(url):
    from src.features.player_leaderboard import safe_crest
    return safe_crest(url)


# ---------------------------------------------------------------------------
# Einzelner Spieler: die gezaehlten Partien nachvollziehbar machen
# ---------------------------------------------------------------------------

#: Genau die Felder, die eine Spielzeile ERZAEHLBAR machen. Bewusst als
#: Positivliste: was hier nicht steht, verlaesst den Server nicht.
#:
#: GEAENDERT: ``opponent_rank`` und ``opponent_rank_type`` sind jetzt dabei.
#: Der Auszug behauptete "dieser Gegner lag innerhalb der gewaehlten
#: Grenze", ohne zu zeigen, WORAUS das folgt - bei "UEFA Top 10" stand
#: Bayer Leverkusen da und der Nutzer musste es glauben. Der Rang ist die
#: Begruendung dieser Auswahl und damit eine Fussballfrage.
#:
#: WEITERHIN NICHT dabei und nie dazuzunehmen: opponent_coefficient,
#: opponent_band, weight, strength, importance. Der Koeffizient ist die
#: Rangliste selbst (der Rang ist bloss die Position darin, die UEFA und
#: FIFA ohnehin veroeffentlichen), die uebrigen drei sind Rechengroessen
#: des Modells - die beantworten keine Fussballfrage.
DETAIL_MATCH_FIELDS = (
    "fixture_id", "date", "competition", "stage",
    "opponent_name", "opponent_logo", "is_home",
    "opponent_rank", "opponent_rank_type",
    "goals_for", "goals_against",
    "minutes", "goals", "assists", "rating",
)

#: Welche Rangliste fuer eine Spielzeile gilt. Die Zulassung unterscheidet
#: genau danach: Vereinsspiele an der UEFA-Huerde, Laenderspiele an der
#: FIFA-Huerde.
RANK_TYPE_UEFA = "uefa"
RANK_TYPE_FIFA = "fifa"


def _ranking_year(raw_date):
    """
    Das Kalenderjahr einer Partie - der Schluessel der FIFA-Rangliste.

    Dieselbe Regel wie beim Bauen des Datensatzes
    (national_big_games_loader._fixture_year): das Jahr aus dem
    ISO-Datum, ohne Rueckfall auf ein anderes. Eine Mannschaft kann 2022
    Weltmeister und 2026 Mittelmass gewesen sein.
    """
    if not isinstance(raw_date, str) or len(raw_date) < 4:
        return None
    try:
        year = int(raw_date[:4])
    except ValueError:
        return None
    return year if 1900 <= year <= 2100 else None


def opponent_rank_for_match(match, season):
    """
    Der Rang, mit dem DIESE Partie eingeordnet wurde - (rang, art).

    DIESELBE QUELLE WIE DIE ZULASSUNG, KEINE ZWEITE RECHNUNG
    --------------------------------------------------------
    Gespeichert wird je Spiel nur das Band ("lag innerhalb der Top 10").
    Der Rang dahinter steht weiterhin ausschliesslich in den privaten
    Snapshots - und genau die werden hier gelesen, ueber dieselben
    Nachschlagefunktionen und mit demselben Schluessel wie beim Bauen des
    Datensatzes:

        Verein         uefa_coefficients.lookup_team(SAISON DES SPIELS, id)
        Nationalteam   fifa_rankings.lookup_team(JAHR DER PARTIE, id)

    Dass es wirklich dieselbe Quelle ist, ist nachpruefbar und wird
    geprueft: ``rank_band(rang)`` muss das gespeicherte ``opponent_band``
    ergeben. Ueber den gesamten Datensatz 2025/26 stimmt das fuer alle
    29.190 Spielzeilen.

    Zulaessig ist das hier, weil der Auszug ohnehin nur ausgeliefert wird,
    wenn snapshot_problem() bestaetigt hat, dass GENAU die Snapshots
    vorliegen, mit denen der Datensatz gebaut wurde (Fingerabdruck je
    Saison). Ein spaeter ausgetauschter Snapshot wuerde den Auszug
    schliessen, nicht einen anderen Rang zeigen.

    Rueckgabe (None, art) wenn der Gegner in dieser Saison nicht in der
    Liste stand. None heisst "kein Rang belegt" - nie ein geschaetzter.
    """
    from src.data import fifa_rankings, uefa_coefficients
    from src.features import big_games_rules

    opponent_id = match.get("opponent_id")

    if match.get("source") == big_games_rules.SOURCE_NATIONAL:
        year = _ranking_year(match.get("date"))
        row = (fifa_rankings.lookup_team(year, opponent_id)
               if year is not None else None)
        return (row.get("rank") if row else None), RANK_TYPE_FIFA

    row = uefa_coefficients.lookup_team(season, opponent_id)
    return (row.get("rank") if row else None), RANK_TYPE_UEFA


def _detail_match(match):
    """Eine Spielzeile fuer die Detailansicht - nur erzaehlbare Werte."""
    rank, rank_type = opponent_rank_for_match(match, match.get("season"))
    return {
        "fixture_id": match.get("fixture_id"),
        "date": match.get("date"),
        "competition": match.get("league_name"),
        "stage": match.get("stage"),
        "opponent_name": match.get("opponent_name"),
        "opponent_logo": _safe(match.get("opponent_logo")),
        "is_home": match.get("is_home"),
        # Warum dieser Gegner in der gewaehlten Grenze lag - oder eben
        # nicht: im kontextuellen Modus qualifiziert auch die Runde, dann
        # steht hier ein Rang ausserhalb der Grenze (oder keiner).
        "opponent_rank": rank,
        "opponent_rank_type": rank_type,
        # Ergebnis steht bereits aus eigener Sicht im Datensatz; die
        # Oberflaeche soll die Richtung nie selbst herleiten muessen.
        "goals_for": match.get("goals_for"),
        "goals_against": match.get("goals_against"),
        "minutes": match.get("minutes"),
        "goals": match.get("goals"),
        "assists": match.get("assists"),
        "rating": match.get("rating"),
    }


def player_match_details(season_from, season_to, player_id,
                         uefa_max_rank=None, fifa_max_rank=None, mode=None):
    """
    Die gezaehlten Big Games EINES Spielers unter der gewaehlten Huerde.

    Beantwortet die Frage hinter einer Bestenlistenzeile: WELCHE Partien
    waren das eigentlich? Dieselben Datensaetze, dieselbe Snapshotpruefung
    und - entscheidend - dieselbe Zulassung wie die Liste
    (qualified_player_matches). Deshalb stimmt die Zahl der hier
    gelieferten Partien zwangslaeufig mit den Big Games der Zeile ueberein.

    KEIN Big-Game-Score: der entsteht erst aus der ganzen Population
    (big_games_score.score_population) und liesse sich fuer einen
    einzelnen Spieler nur durch eine vollstaendige Neuberechnung der
    Liste gewinnen - gemessen rund zwei Sekunden gegenueber einem
    Bruchteil einer Millisekunde hier. Die Oberflaeche zeigt deshalb den
    Wert, den sie aus der Zeile ohnehin schon kennt.

    Sortierung: neueste Partie zuerst, bei gleichem Datum nach
    Fixture-ID - damit ist die Reihenfolge deterministisch.
    """
    from src.api.apisports_api import CURRENT_SEASON
    from src.data.big_games_loader import dominant_position
    from src.features import big_games, big_games_rules, big_games_score
    from src.features import national_big_games

    uefa_max_rank = big_games_rules.clamp_uefa_max_rank(uefa_max_rank)
    fifa_max_rank = big_games_rules.clamp_fifa_max_rank(fifa_max_rank)
    mode = big_games_rules.normalize_mode(mode)

    basis = {
        "opponent_cutoffs": {
            "uefa_max_rank": uefa_max_rank,
            "fifa_max_rank": fifa_max_rank,
            "uefa_options": list(big_games.UEFA_RANK_BANDS),
            "fifa_options": list(national_big_games.FIFA_RANK_BANDS),
            "big_game_mode": mode,
        },
        "eligibility": {
            "min_matches": big_games_score.RANKING_MIN_BIG_GAMES,
            "min_minutes": big_games_score.RANKING_MIN_MINUTES,
            "rule": "big_games_rankable",
        },
    }

    seasons = list(range(season_from, season_to + 1))
    documents = []
    problem = None
    for season in seasons:
        document, reason = load_dataset(season)
        if reason is None:
            reason = snapshot_problem(document)
        if reason:
            problem = problem or reason
        else:
            documents.append(document)

    if problem:
        return {**basis, "available": False, "reason": problem,
                "player": None, "summary": None, "matches": []}

    provisional = any(s >= CURRENT_SEASON for s in seasons) or any(
        d.get("provisional") for d in documents)

    # Ueber alle Saisons des Zeitraums dieselbe Zeile zusammentragen.
    zeilen, roh = [], []
    for document in sorted(documents, key=lambda d: d["season"]):
        for row in document["players"]:
            if row["player_id"] == player_id:
                zeilen.append(row)
                # Die Saison je Spiel mitfuehren: ueber mehrere Saisons
                # hinweg waere sonst nicht mehr erkennbar, aus WELCHEM
                # UEFA-Snapshot der Rang dieser Partie stammen muss. Eine
                # Kopie, damit der gemerkte Datensatz unberuehrt bleibt.
                roh.extend({**m, "season": document["season"]}
                           for m in (row.get("matches") or []))

    if not zeilen:
        return {**basis, "available": False, "reason": REASON_PLAYER_MISSING,
                "player": None, "summary": None, "matches": []}

    matches = qualified_player_matches(roh, uefa_max_rank, fifa_max_rank, mode)
    matches.sort(key=lambda m: (m.get("date") or "", m.get("fixture_id") or 0),
                 reverse=True)

    latest = zeilen[-1]
    inputs = big_games_score.player_inputs(matches)
    summe = _raw_totals(matches)
    team_id, team_name, team_logo = _latest_club_team(matches)
    mit_beteiligung = sum(
        1 for m in matches
        if (m.get("goals") or 0) > 0 or (m.get("assists") or 0) > 0)

    return {
        **basis,
        "available": True,
        "reason": None,
        "provisional": provisional,
        "player": {
            "player_id": player_id,
            "name": display_name(latest.get("name")),
            "team_name": team_name or latest.get("team_name"),
            "team_id": team_id if team_id is not None else latest.get("team_id"),
            "team_logo": (latest.get("team_logo") if team_logo is None
                          else _safe(team_logo)),
            "position": (dominant_position(matches)
                         or latest.get("position")
                         or latest.get("pool_position")),
        },
        "summary": {
            "big_games": inputs["matches"],
            "minutes": inputs["minutes"],
            "goals": summe["goals"],
            "assists": summe["assists"],
            "matches_with_goal_contribution": mit_beteiligung,
            # Ob der Spieler unter DIESER Huerde ueberhaupt platziert
            # wuerde. Ist er es nicht, zeigt die Oberflaeche die Partien
            # trotzdem - nur eben ohne Rang, statt einen zu erfinden.
            "rankable": big_games_score.is_rankable(
                inputs["matches"], inputs["minutes"]),
        },
        "matches": [_detail_match(m) for m in matches],
    }
