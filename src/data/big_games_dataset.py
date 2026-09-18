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
DATASET_CONTRACT_VERSION = "big-games-leaderboard-v2"

STATUS_COMPLETE = "complete"
STATUS_INCOMPLETE = "incomplete"

#: Pilotsaison des Sammlers: 2025/26.
PILOT_SEASON = 2025

#: Was je Spiel gespeichert wird: genau die Felder, die Aggregation,
#: Positionsregel und Anzeige brauchen. Kein Gegnerrang, kein Koeffizient.
MATCH_FIELDS = (
    "fixture_id", "date", "source", "league_id",
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
        "name": pool_entry.get("name"),
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


def load_dataset(season):
    """
    Rueckgabe: (dokument, problem). problem ist None oder ein Grundschluessel.
    """
    document = read_json(dataset_path(season))
    if document is None:
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


def big_games_leaderboard(season_from, season_to, position, limit):
    """
    Big-Games-Bestenliste ueber einen Saisonbereich.

    DIE RANGFOLGE IST FEST: der bestehende big_game_score aus
    big_games.aggregate_big_games() - derselbe Wert wie im Einzelvergleich.
    Es gibt keine waehlbare Kennzahl und keine eigene Formel. Die Position
    filtert nur die Population.

    Wer die bestehende Mindestmenge (has_sufficient_sample) nicht erreicht,
    hat keinen Score und wird nicht einsortiert.

    Verfuegbar NUR, wenn fuer JEDE Saison des Bereichs ein vollstaendiger
    Datensatz vorliegt und dessen historische Snapshots unveraendert auf
    dem Server liegen. Sonst available=false mit Grund - nie eine Liste aus
    einem Teilbestand.
    """
    from src.api.apisports_api import CURRENT_SEASON
    from src.data.big_games_loader import dominant_position
    from src.features import big_games
    from src.features.player_leaderboard import (
        BIG_GAME_SCORE_KEY, POSITION_ALL, rank_rows)

    eligibility = {
        "min_matches": big_games.MIN_BIG_GAMES,
        "min_minutes": big_games.MIN_BIG_GAME_MINUTES,
        "rule": "big_games_sufficient_sample",
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
    eligible = []

    for player_id in sorted(by_player):
        entry = by_player[player_id]
        latest = entry["rows"][-1]
        # Dieselbe Deduplizierung und dieselbe Aggregation wie im
        # Einzelvergleich - ueber alle Saisons des Zeitraums EINMAL.
        matches, summary = aggregate_matches(entry["matches"])
        group = dominant_position(matches) or latest.get("pool_position")
        if position != POSITION_ALL and group != position:
            continue
        considered += 1
        if not summary.get("sufficient_sample"):
            excluded_sample += 1
            continue
        score = summary.get("big_game_score")
        if score is None:
            # Genug Spiele, aber keine bewerteten Einsaetze: kein Score, nie 0.
            without_score += 1
            continue
        team_id, team_name, team_logo = _latest_club_team(matches)
        eligible.append({
            "player_id": player_id,
            "name": latest.get("name"),
            "team_name": team_name or latest.get("team_name"),
            "team_id": team_id if team_id is not None else latest.get("team_id"),
            "team_logo": latest.get("team_logo") if team_logo is None else _safe(team_logo),
            "league": latest.get("league"),
            "position": group,
            "minutes": summary["raw"]["minutes"],
            "appearances": summary["raw"]["matches"],
            "big_games": summary["raw"]["matches"],
            "value": float(score),
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


def _safe(url):
    from src.features.player_leaderboard import safe_crest
    return safe_crest(url)
