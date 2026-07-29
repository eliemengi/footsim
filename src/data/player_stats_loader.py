"""
Spielerstatistik-Loader fuer den Transfervergleich.

Aufgabe:
    Laedt die Leistungsdaten eines Spielers in der ZIELLIGA fuer die
    Saison nach seinem Wechsel und normalisiert sie.

Wichtige API-Sports-Eigenheiten, die hier behandelt werden:
    - /players?id=X&season=Y liefert MEHRERE statistics-Eintraege
      (ein Eintrag pro Wettbewerb, teils pro Verein). Wir werten nur
      Eintraege der Zielliga aus und summieren sie, falls der Spieler
      innerhalb der Saison den Verein in derselben Liga gewechselt hat.
    - rating ist ein String ("7.25") oder None -> Konvertierung noetig.
    - assists ist teilweise null. Null bedeutet unbekannt, nicht 0.
      Wir erfinden keine Nullwerte.
    - Position steht pro statistics-Eintrag unter games.position.

Rate-Limit-Schutz:
    Ein Request pro Spieler und Saison, dauerhaft im Disk-Cache.
    Abgeschlossene Saisons aendern sich nie mehr -> sehr lange TTL.
"""

from src.api.apisports_api import _get, LEAGUE_IDS, CURRENT_SEASON, ApisportsUnavailable
from src.utils.disk_cache import disk_cached_call

TTL_STATS_FINISHED = 60 * 60 * 24 * 365   # 1 Jahr: fertige Saison ist fix
TTL_STATS_CURRENT  = 60 * 60 * 24         # 24 Stunden: laufende Saison

# Positionsgruppen wie von API-Sports geliefert.
KNOWN_POSITIONS = ("Goalkeeper", "Defender", "Midfielder", "Attacker")


def _stats_ttl(season):
    if season < CURRENT_SEASON:
        return TTL_STATS_FINISHED
    return TTL_STATS_CURRENT


def _to_int(value):
    """API liefert Zahlen teils als int, teils als None."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_rating(value):
    """Rating-String ('7.25') -> float, sonst None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_player_statistics(raw_entries, target_league_id):
    """
    Reine Normalisierung ohne API-Zugriff (dadurch testbar).

    raw_entries: die 'statistics'-Liste eines /players-Eintrags.
    Rueckgabe: dict mit normalisierten Werten oder Kennzeichnung,
    dass keine Daten fuer die Zielliga vorliegen.
    """
    relevant = []
    for stats in raw_entries or []:
        league = stats.get("league") or {}
        if league.get("id") == target_league_id:
            relevant.append(stats)

    if not relevant:
        return {
            "data_available": False,
            "minutes": None,
            "appearances": None,
            "goals": None,
            "assists": None,
            "scorer_points": None,
            "rating": None,
            "position": None,
        }

    total_minutes = 0
    total_appearances = 0
    total_goals = 0
    assists_sum = 0
    assists_known = False
    rating_weighted_sum = 0.0
    rating_minutes = 0

    # Position und Verein aus dem Eintrag mit den meisten Minuten.
    best_entry = None
    best_entry_minutes = -1

    for stats in relevant:
        games = stats.get("games") or {}
        goals = stats.get("goals") or {}

        minutes = _to_int(games.get("minutes")) or 0
        appearances = _to_int(games.get("appearences")) or 0
        goals_total = _to_int(goals.get("total")) or 0
        assists = _to_int(goals.get("assists"))
        rating = _to_rating(games.get("rating"))

        total_minutes += minutes
        total_appearances += appearances
        total_goals += goals_total

        if assists is not None:
            assists_sum += assists
            assists_known = True

        if rating is not None and minutes > 0:
            rating_weighted_sum += rating * minutes
            rating_minutes += minutes

        if minutes > best_entry_minutes:
            best_entry_minutes = minutes
            best_entry = stats

    assists_value = assists_sum if assists_known else None

    scorer_points = None
    if assists_value is not None:
        scorer_points = total_goals + assists_value

    rating_value = None
    if rating_minutes > 0:
        rating_value = round(rating_weighted_sum / rating_minutes, 2)

    position = None
    if best_entry is not None:
        games = best_entry.get("games") or {}
        raw_position = games.get("position")
        if raw_position in KNOWN_POSITIONS:
            position = raw_position

    return {
        "data_available": True,
        "minutes": total_minutes,
        "appearances": total_appearances,
        "goals": total_goals,
        "assists": assists_value,
        "scorer_points": scorer_points,
        "rating": rating_value,
        "position": position,
    }


def get_player_target_league_stats(player_id, season, target_league_code):
    """
    Statistik eines Spielers in der Zielliga fuer eine Saison.

    Ein API-Request pro Spieler+Saison, dauerhaft gecacht.
    Rueckgabe enthaelt zusaetzlich Foto und Namen aus der API-Antwort,
    damit das Frontend keine zweite Quelle braucht.
    """
    target_league_id = LEAGUE_IDS.get(target_league_code)
    if not target_league_id:
        raise ApisportsUnavailable(f"Unbekannte Zielliga: {target_league_code}")

    def loader():
        # Bewusst OHNE league-Parameter: so liegt die komplette Saison
        # des Spielers einmal im Cache und kann spaeter auch fuer andere
        # Ziel-Ligen wiederverwendet werden (0 zusaetzliche Requests).
        return _get("players", params={"id": player_id, "season": season})

    raw = disk_cached_call(
        key=f"apisports:playerstats:{player_id}:{season}",
        ttl_seconds=_stats_ttl(season),
        loader=loader,
        source="api-sports",
    )

    if not raw:
        return {
            "player_photo": None,
            **normalize_player_statistics([], target_league_id),
        }

    entry = raw[0] or {}
    player = entry.get("player") or {}
    normalized = normalize_player_statistics(entry.get("statistics"), target_league_id)

    return {
        "player_photo": player.get("photo"),
        **normalized,
    }
