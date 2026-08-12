"""
Historische FIFA-Herren-Weltranglisten fuer National-Team Big Games.

Die kuratierten Top-20-Snapshots liegen ausschliesslich serverseitig unter
``data/big_games/fifa_rankings/``. Sie sind absichtlich gitignored und dieses
Modul stellt keine Route oder Serialisierung der Rohdaten bereit. Aufrufer
erhalten nur die abgeleitete Ranginformation fuer eine bereits bekannte,
numerische API-Football-Nationalteam-ID.

Die Produktregel verwendet ein Ranking-Jahr, nicht eine monatliche
Veroeffentlichungshistorie: ``lookup_team(2024, team_id)`` fragt genau den
validierten 2024-Snapshot ab. Fehlt er oder ist er kaputt, ist die Antwort
neutral ``None``; es gibt niemals einen Jahres-Fallback oder eine
Namensaufloesung.
"""

import datetime as _datetime
import json
import math
import os
import threading


# Projektwurzel: .../src/data/fifa_rankings.py -> drei Ebenen hoch.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FIFA_RANKING_DIR = os.path.join(_PROJECT_ROOT, "data", "big_games", "fifa_rankings")
EARLIEST_FIFA_RANKING_YEAR = 2021
FIFA_TOP_RANK = 20
_EXPECTED_RANKS = frozenset(range(1, FIFA_TOP_RANK + 1))
_EXPECTED_RANKING_TYPE = "fifa_mens_world_ranking_top20"
_VALID_STATUSES = frozenset(("final", "provisional"))

# Kleine, unveraenderliche Dateien: Prozesscache vermeidet wiederholtes
# Parsen. Er ist bewusst getrennt vom Fixture-/Diskcache der Big-Games-Pipeline.
_CACHE = {}
_CACHE_LOCK = threading.Lock()


def _normalise_year(year):
    """Akzeptiert nur ganzzahlige Jahre; bool ist nie ein valides Jahr."""
    if isinstance(year, bool):
        return None
    if isinstance(year, int):
        return year
    if isinstance(year, str) and year.strip().isdigit():
        return int(year.strip())
    return None


def snapshot_path(year):
    """Dateipfad eines Jahres-Snapshots, ohne ihn zu lesen."""
    return os.path.join(FIFA_RANKING_DIR, f"fifa_rankings_{year}.json")


def _empty_snapshot(year, reason):
    """Neutraler Ersatzwert: fehlende Privatdaten duerfen nie die App stoppen."""
    return {
        "year": year,
        "available": False,
        "reason": reason,
        "snapshot_date": None,
        "ranking_type": None,
        "status": None,
        "provisional": False,
        "by_team_id": {},
        "team_count": 0,
    }


def _is_nonempty_string(value):
    return isinstance(value, str) and bool(value.strip())


def _is_finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _valid_snapshot_date(value, expected_year):
    if not isinstance(value, str):
        return False
    try:
        return _datetime.date.fromisoformat(value).year == expected_year
    except ValueError:
        return False


def _parse_snapshot(year, raw):
    """
    Validiert und normalisiert einen kompletten FIFA-Top-20-Snapshot.

    Im Unterschied zum UEFA-Loader wird ein nationaler Snapshot nicht
    teilweise verwertet: eine doppelte ID, ein fehlender Rang oder eine nicht
    hoch aufgeloeste Teamidentitaet macht die ganze Jahresquelle unbrauchbar.
    Das verhindert, dass eine unvollstaendige private Quelle stillschweigend
    als vollstaendige historische Wahrheit verwendet wird.
    """
    if not isinstance(raw, dict):
        return _empty_snapshot(year, "invalid_structure")
    if raw.get("year") != year:
        return _empty_snapshot(year, "year_mismatch")
    if raw.get("ranking_type") != _EXPECTED_RANKING_TYPE:
        return _empty_snapshot(year, "invalid_ranking_type")
    if not _valid_snapshot_date(raw.get("snapshot_date"), year):
        return _empty_snapshot(year, "invalid_snapshot_date")
    if raw.get("status") not in _VALID_STATUSES:
        return _empty_snapshot(year, "invalid_status")
    if not _is_nonempty_string(raw.get("source")):
        return _empty_snapshot(year, "invalid_source")

    team_identity = raw.get("team_identity")
    if not isinstance(team_identity, dict):
        return _empty_snapshot(year, "invalid_team_identity")
    if any(not _is_nonempty_string(team_identity.get(field))
           for field in ("id_scheme", "id_source", "resolution_rule")):
        return _empty_snapshot(year, "invalid_team_identity")
    if team_identity.get("unresolved_teams") != []:
        return _empty_snapshot(year, "unresolved_team_identity")

    teams = raw.get("teams")
    if not isinstance(teams, list) or len(teams) != FIFA_TOP_RANK:
        return _empty_snapshot(year, "invalid_team_count")

    by_team_id = {}
    seen_ranks = set()
    seen_names = set()

    for team in teams:
        if not isinstance(team, dict):
            return _empty_snapshot(year, "invalid_team_entry")

        rank = team.get("rank")
        team_id = team.get("apisports_team_id")
        team_name = team.get("team_name")
        team_name_en = team.get("team_name_en")

        if not isinstance(rank, int) or isinstance(rank, bool):
            return _empty_snapshot(year, "invalid_rank")
        if rank in seen_ranks:
            return _empty_snapshot(year, "duplicate_rank")
        seen_ranks.add(rank)

        # Der Loader loest niemals Namen auf. Die Namenspruefung ist nur eine
        # Datenintegritaetspruefung fuer eine bereits kuratierte Liste.
        if not _is_nonempty_string(team_name) or not _is_nonempty_string(team_name_en):
            return _empty_snapshot(year, "invalid_team_name")
        canonical_name = team_name_en.strip().casefold()
        if canonical_name in seen_names:
            return _empty_snapshot(year, "duplicate_team_name")
        seen_names.add(canonical_name)

        if not isinstance(team_id, int) or isinstance(team_id, bool) or team_id <= 0:
            return _empty_snapshot(year, "invalid_team_id")
        if team_id in by_team_id:
            return _empty_snapshot(year, "duplicate_team_id")
        if not _is_finite_number(team.get("points")):
            return _empty_snapshot(year, "invalid_points")
        if team.get("apisports_resolution_confidence") != "high":
            return _empty_snapshot(year, "unresolved_team_identity")
        if not _is_nonempty_string(team.get("apisports_resolution_method")):
            return _empty_snapshot(year, "unresolved_team_identity")

        by_team_id[team_id] = {
            "rank": rank,
            "points": float(team["points"]),
            "team_name": team_name,
            "team_name_en": team_name_en,
        }

    if frozenset(seen_ranks) != _EXPECTED_RANKS:
        return _empty_snapshot(year, "invalid_rank_range")

    return {
        "year": year,
        "available": True,
        "reason": None,
        "snapshot_date": raw["snapshot_date"],
        "ranking_type": raw["ranking_type"],
        "status": raw["status"],
        "provisional": raw["status"] == "provisional",
        "by_team_id": by_team_id,
        "team_count": len(by_team_id),
    }


def load_snapshot(year):
    """
    Liefert den validierten Snapshot fuer genau dieses Ranking-Jahr.

    Fehlende, unlesbare oder schemawidrige Dateien ergeben immer einen
    neutralen Snapshot. Insbesondere wird niemals ein anderes Jahr als
    Ersatz verwendet.
    """
    normalized_year = _normalise_year(year)
    if normalized_year is None:
        return _empty_snapshot(year, "invalid_year")

    with _CACHE_LOCK:
        cached = _CACHE.get(normalized_year)
    if cached is not None:
        return cached

    path = snapshot_path(normalized_year)
    if not os.path.exists(path):
        snapshot = _empty_snapshot(normalized_year, "missing_file")
    else:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            snapshot = _parse_snapshot(normalized_year, raw)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            snapshot = _empty_snapshot(normalized_year, "unreadable")

    with _CACHE_LOCK:
        _CACHE[normalized_year] = snapshot
    return snapshot


def clear_cache():
    """Verwirft geparste Rankings; fuer Tests und explizite Wartung."""
    with _CACHE_LOCK:
        _CACHE.clear()


def has_year(year):
    """True nur bei einem vollstaendig validierten Snapshot des Jahres."""
    return load_snapshot(year)["available"]


def available_years(first, last):
    """Verfuegbare, validierte Jahre im inklusiven Bereich."""
    first_year = _normalise_year(first)
    last_year = _normalise_year(last)
    if first_year is None or last_year is None or first_year > last_year:
        return []
    return [year for year in range(first_year, last_year + 1) if has_year(year)]


def lookup_team(year, apisports_team_id):
    """
    Liefert Rangdaten ausschliesslich ueber eine exakte API-Football-ID.

    ``None`` bedeutet: nicht Top 20, fehlende Jahresquelle oder ungueltige
    Eingabe. Namen werden hier absichtlich nie als Fallback verwendet.
    """
    if isinstance(apisports_team_id, bool):
        return None
    try:
        team_id = int(apisports_team_id)
    except (TypeError, ValueError):
        return None
    if team_id <= 0:
        return None
    return load_snapshot(year)["by_team_id"].get(team_id)


def is_top20(year, apisports_team_id):
    """Exakte FIFA-Top-20-Zulassung fuer die nationale Gegnerbewertung."""
    entry = lookup_team(year, apisports_team_id)
    return entry is not None and 1 <= entry["rank"] <= FIFA_TOP_RANK
