"""
Spieler-Bestenlisten (Block C24).

Eine Bestenliste ordnet die Spieler EINER Positionsgruppe nach EINER
benannten Kennzahl. Es gibt bewusst keinen Gesamtscore, keine
Mischformel und keine "besten Spieler" - die Ueberschrift sagt immer,
nach welcher Statistik sortiert wird.

Dieses Modul enthaelt die gemeinsamen Regeln fuer beide Datenbasen:

    - welche Kennzahlen je Position waehlbar sind (Schluessel und
      Richtung aus dem bestehenden Katalog player_metrics.METRICS),
    - welche Listenlaengen zulaessig sind,
    - wie deterministisch sortiert wird,
    - die Bestenliste aus dem lokalen Spielerpool.

Die Big-Games-Bestenliste liegt in src/data/big_games_dataset.py; sie
benutzt Katalog und Sortierung von hier.

Grundregeln:
    1. Kein Anbieterabruf. Gelesen werden ausschliesslich lokale Dateien.
    2. Ein fehlender Wert bleibt fehlend. Er wird nie zu 0 und nie
       mitsortiert; er wird in der Abdeckung gezaehlt.
    3. Ein Spieler erscheint hoechstens einmal, auch wenn er in zwei
       Ligapools liegt (Wechsel waehrend der Saison). Zusammengefuehrt
       wird ueber die stabile Player-ID, nie ueber den Namen; Werte werden
       dabei nicht addiert.
"""

import os
import unicodedata

from src.data import player_pool
from src.data.percentile_engine import min_minutes_for_scope
from src.data.player_metrics import (
    HIGHER_BETTER,
    LOWER_BETTER,
    METRICS,
    POSITION_ATT,
    compute_metric,
    POSITION_DEF,
    POSITION_GK,
    POSITION_GROUPS,
    POSITION_MID,
    normalize_position,
)

#: Zulaessige Listenlaengen. Keine freie Zahl.
LEADERBOARD_LIMITS = (5, 10, 15, 20, 30)
DEFAULT_LIMIT = 10

#: Positionswert fuer "alle Positionen" in der API.
POSITION_ALL = "all"
LEADERBOARD_POSITIONS = POSITION_GROUPS + (POSITION_ALL,)

SCOPE_BIG_GAMES = "big_games"

#: Waehlbare Kennzahlen je Position, die erste ist der Standard.
#:
#: Nur Schluessel aus METRICS - Richtung, Typ und Erklaerung kommen von
#: dort. "Alle Positionen" bekommt ausschliesslich die Anbieterbewertung:
#: Sie ist die einzige Kennzahl, die fuer Torhueter und Stuermer gleich
#: erhoben wird. Eine selbst erfundene positionsuebergreifende
#: Leistungszahl gibt es nicht.
LEADERBOARD_METRICS = {
    POSITION_ATT: ("goal_contributions_per90", "shots_on_per90", "key_passes_per90"),
    POSITION_MID: ("key_passes_per90", "goal_contributions_per90"),
    POSITION_DEF: ("tackles_per90", "interceptions_per90", "duels_won_pct"),
    POSITION_GK: ("saves_per90", "conceded_per90", "rating"),
    POSITION_ALL: ("rating",),
}

#: Die Bewertung heisst in der Bestenliste ausdruecklich
#: Anbieterbewertung: Sie ist eine Note von API-Football, keine
#: FootSim-Berechnung.
PROVIDER_RATING_LABEL = "Anbieterbewertung (API-Football)"

#: Big Games haben KEINE frei waehlbare Kennzahl. Die Liste beantwortet
#: genau eine Frage - wer nach der bestehenden FootSim-Big-Games-Logik der
#: staerkste Big-Game-Spieler des Zeitraums war - und sortiert deshalb fest
#: nach dem big_game_score aus big_games.aggregate_big_games(). Es gibt
#: dafuer keine eigene Formel in diesem Modul.
BIG_GAME_SCORE_KEY = "big_game_score"
BIG_GAME_SCORE_META = {
    "key": BIG_GAME_SCORE_KEY,
    "label": "Big-Game-Score",
    "kind": "value",
    "direction": HIGHER_BETTER,
    "description": ("Leistung in großen Spielen, gewichtet nach "
                    "Gegnerstärke und Spielbedeutung."),
}


def leaderboard_metrics(scope, position):
    """Waehlbare Kennzahlen: bei Big Games ausschliesslich der Big-Game-Score."""
    if scope == SCOPE_BIG_GAMES:
        return (BIG_GAME_SCORE_KEY,)
    return metrics_for_leaderboard_position(position)


def leaderboard_metric_meta(scope, key):
    if scope == SCOPE_BIG_GAMES:
        return dict(BIG_GAME_SCORE_META) if key == BIG_GAME_SCORE_KEY else None
    return metric_meta(key)

#: Gruende fuer available=false. Stabile Schluessel fuer die Oberflaeche.
REASON_NO_POOL = "no_pool_data"
REASON_TOURNAMENT = "tournament_not_in_season"
REASON_NO_ELIGIBLE = "no_eligible_players"


def metrics_for_leaderboard_position(position):
    """Die waehlbaren Kennzahlen einer Position (Standard zuerst)."""
    return LEADERBOARD_METRICS.get(position or POSITION_ALL, ())


def default_metric(position):
    metrics = metrics_for_leaderboard_position(position)
    return metrics[0] if metrics else None


def metric_meta(key):
    """Anzeige-Metadaten einer Kennzahl aus dem zentralen Katalog."""
    metric = METRICS.get(key)
    if metric is None:
        return None
    return {
        "key": key,
        "label": PROVIDER_RATING_LABEL if key == "rating" else metric["label"],
        "kind": metric["kind"],
        "direction": metric["direction"],
        "description": metric["description"],
    }


def allowed_metrics(position):
    return [metric_meta(key) for key in metrics_for_leaderboard_position(position)]


def normalized_name(name):
    """Sortierschluessel fuer Namen: ohne Akzente, ohne Gross/klein."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.casefold().split())


def sort_key(direction):
    """
    Deterministische Reihenfolge:
        1. Kennzahl gemaess Richtung
        2. mehr Minuten
        3. normalisierter Name
        4. stabile Player-ID
    """
    sign = -1 if direction == HIGHER_BETTER else 1

    def key(row):
        return (
            sign * row["value"],
            -(row.get("minutes") or 0),
            normalized_name(row.get("name")),
            row.get("player_id") or 0,
        )

    return key


def rank_rows(rows, direction, limit):
    """Sortiert und nummeriert. Zeilen ohne Wert duerfen hier nicht ankommen."""
    ordered = sorted(rows, key=sort_key(direction))
    for index, row in enumerate(ordered[:limit], start=1):
        row["rank"] = index
    return ordered[:limit]


# ---------------------------------------------------------------------------
# Vereinswappen
# ---------------------------------------------------------------------------

def safe_crest(url):
    """Nur Wappen von zugelassenen Hosts, sonst None (Platzhalter)."""
    from src.api.auth import normalize_crest_url

    value, error = normalize_crest_url(url)
    return None if error else value


# ---------------------------------------------------------------------------
# Bestenliste aus dem Spielerpool
# ---------------------------------------------------------------------------

def _league_label(code):
    from src.data.player_compare_loader import COMPARE_LEAGUE_LABELS
    return COMPARE_LEAGUE_LABELS.get(code, code)


def _cached_profile(player_id, season, scope, raw_loader=None):
    """Profil eines Pool-Spielers wie im Einzelvergleich, nur aus dem Cache."""
    from src.data.player_compare_loader import (
        build_player_profile, cached_season_raw_enriched)

    if not isinstance(player_id, int) or player_id <= 0:
        return None
    raw = (raw_loader or (lambda pid: cached_season_raw_enriched(pid, season)))(player_id)
    if not raw:
        return None
    return build_player_profile(raw, season, scope=scope)


def _scope_minutes(entry, scope):
    """Minuten im Scope. None bleibt None (keine Daten im Wettbewerb)."""
    by_scope = entry.get("minutes_by_scope")
    if isinstance(by_scope, dict) and scope in by_scope:
        return by_scope.get(scope)
    metrics = (entry.get("metrics_by_scope") or {}).get(scope) or {}
    return metrics.get("minutes")


def _league_order(code, league_codes):
    return league_codes.index(code) if code in league_codes else len(league_codes)


def deduplicate_pool_entries(entries_with_league, scope, league_codes):
    """
    Ein Eintrag je Player-ID.

    Liegt ein Spieler in zwei Ligapools (Wechsel waehrend der Saison),
    stammen beide Eintraege aus derselben Profilantwort des Anbieters. Sie
    werden deshalb NICHT addiert - das zaehlte dieselben Minuten doppelt.
    Gewaehlt wird deterministisch: mehr Minuten im Scope, dann die
    Ligareihenfolge des Vergleichs.

    Rueckgabe: (eintraege, doppelte, konflikte, ohne_id)
    """
    by_player = {}
    without_id = 0
    for code, entry in entries_with_league:
        player_id = entry.get("player_id")
        if not isinstance(player_id, int) or player_id <= 0:
            without_id += 1
            continue
        by_player.setdefault(player_id, []).append((code, entry))

    chosen = []
    duplicates = 0
    conflicts = 0
    for player_id in sorted(by_player):
        group = by_player[player_id]
        if len(group) > 1:
            duplicates += len(group) - 1
            scope_values = {
                repr(sorted(((e.get("metrics_by_scope") or {}).get(scope) or {}).items()))
                for _code, e in group
            }
            if len(scope_values) > 1:
                conflicts += 1
        group.sort(key=lambda item: (
            -(_scope_minutes(item[1], scope) or 0),
            _league_order(item[0], league_codes),
        ))
        chosen.append(group[0])
    return chosen, duplicates, conflicts, without_id


def _pool_league_status(season, league_codes):
    """Status je Ligapool: was ist da, was fehlt, was ist unvollstaendig."""
    rows = []
    for code in league_codes:
        effective = player_pool.effective_pool_status(code, season)
        rows.append({
            "league": code,
            "label": _league_label(code),
            "status": effective["status"],
            "players": effective["players"],
            "teams": effective["teams"],
            "expected_teams": effective["expected_teams"],
        })
    return rows


#: Alle Kennzahlen, die irgendeine Position anbietet - einmal je Spieler
#: berechnet, damit ein Positions- oder Kennzahlwechsel nichts neu liest.
ALL_LEADERBOARD_METRIC_KEYS = tuple(sorted({
    key for keys in LEADERBOARD_METRICS.values() for key in keys
}))


def tournament_missing(season, scope):
    """True, wenn der Turnier-Scope in dieser Saison nicht stattfand."""
    from src.data.national_competitions import tournament_scope_availability

    tournaments = tournament_scope_availability(season)
    return scope in tournaments and not tournaments[scope]


def _read_pool_data(season, league_codes):
    """Ligastatus und Pooleintraege einer Saison - einmal gelesen."""
    league_rows = _pool_league_status(season, league_codes)
    entries = []
    used = []
    for code in league_codes:
        players, used_codes = player_pool.load_all_players(season, [code])
        if used_codes:
            used.append(code)
            entries.extend((code, entry) for entry in players)
    for row in league_rows:
        row["used"] = row["league"] in used
    return league_rows, entries, used


def pool_populations(season, league_codes=None):
    """
    Die Populationen ALLER Datenbasen einer Saison in einem Durchlauf.

    Jede lokale Profilantwort wird dabei genau einmal gelesen. Das ist der
    teure Teil: Eine noch nicht vom Betriebssystem zwischengespeicherte
    Datei kostete lokal gemessen rund 19 ms (warm 0,3 ms); eine Saison hat
    rund 3.700 Profile. Die Route legt das Ergebnis im Plattencache ab,
    damit Neustarts und weitere Serverprozesse es nicht erneut lesen.
    """
    from src.data.player_compare_loader import (
        COMPARE_LEAGUE_CODES, COMPETITION_SCOPES, cached_season_raw_enriched)

    league_codes = tuple(league_codes or COMPARE_LEAGUE_CODES)
    pool_data = _read_pool_data(season, league_codes)
    gelesen = {}

    def raw_for(player_id):
        if player_id not in gelesen:
            gelesen[player_id] = cached_season_raw_enriched(player_id, season)
        return gelesen[player_id]

    return {
        scope: pool_population(season, scope, league_codes,
                               pool_data=pool_data, raw_loader=raw_for)
        for scope in COMPETITION_SCOPES
    }


def pool_population(season, scope, league_codes=None, with_profiles=True,
                    pool_data=None, raw_loader=None):
    """
    Die Population einer Saison und eines Wettbewerbsumfangs.

    Liest die Ligapools (wer gehoert dazu, aus welcher Liga) und je Spieler
    die lokal gespeicherte Profilantwort. Die Werte entstehen in DERSELBEN
    Rechnung wie im Einzelvergleich: build_player_profile -> compute_metric.

    Die im Pool gespeicherten Kennzahlen werden bewusst NICHT als Wert
    benutzt: Sie koennen aelter sein als die heutige Wettbewerbseinordnung.
    Gemessen fuer 2025/26 wichen bei 1.106 von 3.715 Eintraegen die
    club_all-Minuten ab (u. a. zaehlten dort U21- und U17-Laenderspiele
    noch als Vereinsspiele). Die Liste stuende sonst im Widerspruch zum
    Einzelvergleich.

    Kein Anbieterabruf: Fehlt eine Profilantwort, wird der Spieler als
    profile_not_cached gezaehlt und nicht aufgenommen.
    """
    from src.data.player_compare_loader import COMPARE_LEAGUE_CODES

    league_codes = tuple(league_codes or COMPARE_LEAGUE_CODES)
    league_rows, entries, used = pool_data or _read_pool_data(season, league_codes)
    league_rows = [dict(row) for row in league_rows]

    chosen, duplicates, conflicts, without_id = deduplicate_pool_entries(
        entries, scope, league_codes)

    candidates = []
    profile_not_cached = 0
    for code, entry in (chosen if with_profiles else ()):
        profile = _cached_profile(entry.get("player_id"), season, scope, raw_loader)
        if profile is None:
            profile_not_cached += 1
            continue

        stats = profile.get("stats") or {}
        minutes = profile.get("minutes")
        league = profile.get("league_code")
        if league not in league_codes:
            league = code
        candidates.append({
            "player_id": entry.get("player_id"),
            "name": profile.get("name") or entry.get("name"),
            "team_name": profile.get("team_name"),
            "team_id": profile.get("team_id"),
            "team_logo": safe_crest(profile.get("team_logo")),
            "league": league,
            "league_label": _league_label(league),
            "position": (normalize_position(profile.get("position"))
                         or normalize_position(entry.get("position"))),
            "minutes": int(minutes) if minutes else minutes,
            "appearances": compute_metric("appearances", stats, minutes),
            "metrics": {
                key: compute_metric(key, stats, minutes)
                for key in ALL_LEADERBOARD_METRIC_KEYS
            },
        })

    return {
        "season": season,
        "scope": scope,
        "league_codes": list(league_codes),
        "league_rows": league_rows,
        "used": used,
        "candidates": candidates,
        "duplicates": duplicates,
        "conflicts": conflicts,
        "without_id": without_id,
        "profile_not_cached": profile_not_cached,
    }


def pool_leaderboard(season, scope, position, metric, limit,
                     league_codes=None, current_season=None, population=None):
    """
    Bestenliste aus dem lokalen Spielerpool einer Saison.

    population: Ergebnis von pool_population() - die Route reicht einen
    kurz zwischengespeicherten Stand herein, damit ein Kennzahlwechsel
    nicht alle Profile neu liest. Ohne Angabe wird sie berechnet.

    Rueckgabe: dict mit available, reason, rows, coverage, eligibility,
    provisional, incomplete. Parameter sind vom Aufrufer bereits geprueft.
    """
    if population is None:
        population = pool_population(
            season, scope, league_codes,
            with_profiles=not tournament_missing(season, scope))
    meta = metric_meta(metric)
    min_minutes = min_minutes_for_scope(scope)

    considered = 0
    excluded_minutes = 0
    without_scope_data = 0
    missing_metric = 0
    eligible = []

    for candidate in population["candidates"]:
        if position != POSITION_ALL and candidate["position"] != position:
            continue
        considered += 1

        minutes = candidate["minutes"]
        if not minutes:
            without_scope_data += 1
            continue
        if minutes < min_minutes:
            excluded_minutes += 1
            continue

        value = candidate["metrics"].get(metric)
        if value is None or isinstance(value, bool):
            missing_metric += 1
            continue

        row = {key: candidate[key] for key in (
            "player_id", "name", "team_name", "team_id", "team_logo",
            "league", "league_label", "position", "minutes", "appearances")}
        row["value"] = float(value)
        eligible.append(row)

    rows = rank_rows(eligible, meta["direction"], limit)

    league_rows = population["league_rows"]
    used = population["used"]
    incomplete_leagues = [r["league"] for r in league_rows
                          if r["status"] != player_pool.STATUS_COMPLETE]
    missing_leagues = [r["league"] for r in league_rows if not r["used"]]

    reason = None
    if not used:
        reason = REASON_NO_POOL
    elif tournament_missing(season, scope):
        reason = REASON_TOURNAMENT
    elif not rows:
        reason = REASON_NO_ELIGIBLE

    return {
        "available": reason is None,
        "reason": reason,
        "rows": rows if reason is None else [],
        "eligibility": {
            "min_minutes": min_minutes,
            "rule": "minutes_in_scope",
        },
        "coverage": {
            "leagues": league_rows,
            "used_leagues": used,
            "missing_leagues": missing_leagues,
            "incomplete_leagues": incomplete_leagues,
            "players_considered": considered,
            "duplicates_removed": population["duplicates"],
            "conflicting_duplicates": population["conflicts"],
            "entries_without_player_id": population["without_id"],
            "profile_not_cached": population["profile_not_cached"],
            "without_scope_data": without_scope_data,
            "excluded_min_minutes": excluded_minutes,
            "missing_metric": missing_metric,
            "eligible": len(eligible),
        },
        "provisional": current_season is not None and season >= current_season,
        "incomplete": bool(incomplete_leagues or missing_leagues),
    }


def pool_signature(season, league_codes=None):
    """
    Aenderungskennung der Pooldateien einer Saison (fuer den Kurzzeitcache).

    Ein Reimport aendert Groesse oder Zeitstempel - der Cache greift dann
    nicht mehr, ohne dass eine Frist abgewartet werden muss.
    """
    from src.data.player_compare_loader import COMPARE_LEAGUE_CODES

    parts = []
    for code in tuple(league_codes or COMPARE_LEAGUE_CODES):
        path = player_pool.pool_path(code, season)
        try:
            stat = os.stat(path)
            parts.append(f"{code}:{stat.st_size}:{int(stat.st_mtime)}")
        except OSError:
            parts.append(f"{code}:-")
    try:
        stat = os.stat(player_pool.STATUS_PATH)
        parts.append(f"status:{stat.st_size}:{int(stat.st_mtime)}")
    except OSError:
        parts.append("status:-")
    return "|".join(parts)


__all__ = [
    "LEADERBOARD_LIMITS", "DEFAULT_LIMIT", "POSITION_ALL",
    "LEADERBOARD_POSITIONS", "SCOPE_BIG_GAMES", "LEADERBOARD_METRICS",
    "metrics_for_leaderboard_position", "default_metric", "metric_meta",
    "allowed_metrics", "normalized_name", "sort_key", "rank_rows",
    "BIG_GAME_SCORE_KEY", "BIG_GAME_SCORE_META", "leaderboard_metrics",
    "leaderboard_metric_meta",
    "pool_leaderboard", "pool_population", "pool_populations", "pool_signature",
    "safe_crest",
    "deduplicate_pool_entries", "ALL_LEADERBOARD_METRIC_KEYS",
    "HIGHER_BETTER", "LOWER_BETTER",
]
