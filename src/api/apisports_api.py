"""
API-Sports (api-football.com) Zugriff für FootSim.

Zweck: Ergänzt football-data.org dort, wo der Free-Plan Lücken hat.
       Konkret: Spielerstatistiken, Top-Scorer mit Fotos, Verletzungen.

Free-Plan Limits:
    100 Requests pro Tag
    Kein kommerzieller Einsatz ohne kostenpflichtigen Plan

Deshalb wird hier sehr aggressiv gecacht.
Kein Endpoint wird öfter als nötig aufgerufen.
"""

import os
import requests
from dotenv import load_dotenv

from src.utils.cache import cached_call

load_dotenv()

APISPORTS_KEY = os.getenv("APISPORTS_KEY")
BASE_URL = "https://v3.football.api-sports.io"

# Saison in API-Sports Format: 4-stellige Jahreszahl des Saisonbeginns
# 2025 = Saison 2025/26
CURRENT_SEASON = 2025

# Liga-IDs bei API-Sports
LEAGUE_IDS = {
    "bl1": 78,   # Bundesliga
    "pl":  39,   # Premier League
    "pd":  140,  # LaLiga
    "sa":  135,  # Serie A
    "fl1": 61,   # Ligue 1
    "cl":  2,    # Champions League
    "el":  3,    # Europa League
}

# Cache-Zeiten: sehr lang, weil wir nur 100 Requests pro Tag haben
TTL_PLAYERS   = 60 * 60 * 6    # 6 Stunden
TTL_INJURIES  = 60 * 60 * 3    # 3 Stunden
TTL_STANDINGS = 60 * 60 * 2    # 2 Stunden


class ApisportsUnavailable(Exception):
    pass


def _headers():
    if not APISPORTS_KEY:
        return {}
    return {
        "x-rapidapi-host": "v3.football.api-sports.io",
        "x-rapidapi-key": APISPORTS_KEY,
    }


def _get(endpoint, params=None):
    if not APISPORTS_KEY:
        raise ApisportsUnavailable("APISPORTS_KEY fehlt in der .env")

    url = f"{BASE_URL}/{endpoint}"

    try:
        response = requests.get(url, headers=_headers(), params=params or {}, timeout=20)
    except requests.RequestException as e:
        raise ApisportsUnavailable(f"Netzwerkfehler: {e}")

    if response.status_code == 429:
        raise ApisportsUnavailable("API-Sports Tageslimit erreicht (100 Requests/Tag)")

    if response.status_code != 200:
        raise ApisportsUnavailable(f"API-Sports: HTTP {response.status_code}")

    data = response.json()

    # API-Sports liefert Fehler im Body mit errors-Feld
    errors = data.get("errors", {})
    if errors:
        raise ApisportsUnavailable(f"API-Sports Fehler: {errors}")

    return data.get("response", [])


# ---------------------------------------------------------------------------
# Torjäger mit Fotos
# ---------------------------------------------------------------------------

def get_top_scorers(competition_code, season=CURRENT_SEASON, limit=20):
    """
    Torjäger einer Liga mit Spielerfoto, Team-Logo und Statistiken.

    Rückgabe: Liste von Einträgen, sofort fürs Frontend nutzbar.
    """
    league_id = LEAGUE_IDS.get(competition_code)
    if not league_id:
        raise ApisportsUnavailable(f"Unbekannte Liga: {competition_code}")

    def loader():
        raw = _get("players/topscorers", params={"league": league_id, "season": season})

        result = []

        for index, entry in enumerate(raw[:limit], start=1):
            player = entry.get("player") or {}
            stats_list = entry.get("statistics") or [{}]
            stats = stats_list[0] if stats_list else {}

            team = stats.get("team") or {}
            games = stats.get("games") or {}
            goals = stats.get("goals") or {}
            passes = stats.get("passes") or {}

            result.append({
                "rank": index,
                "player_id": player.get("id"),
                "player_name": player.get("name"),
                "player_photo": player.get("photo"),
                "nationality": player.get("nationality"),
                "age": player.get("age"),
                "position": player.get("position"),
                "team_id": team.get("id"),
                "team_name": team.get("name"),
                "team_logo": team.get("logo"),
                "goals": goals.get("total") or 0,
                "assists": goals.get("assists"),
                "penalties": goals.get("conceded"),
                "appearances": games.get("appearences"),
                "minutes": games.get("minutes"),
                "goals_per_match": (
                    round((goals.get("total") or 0) / games["appearences"], 2)
                    if games.get("appearences") else None
                ),
                "key_passes": passes.get("key"),
            })

        return result

    return cached_call(
        key=f"apisports:scorers:{competition_code}:{season}:{limit}",
        ttl_seconds=TTL_PLAYERS,
        loader=loader,
    )


# ---------------------------------------------------------------------------
# Verletzungen und Sperren
# ---------------------------------------------------------------------------

def get_injuries(competition_code, season=CURRENT_SEASON):
    """
    Aktuelle Verletzungen und Sperren einer Liga.

    Nur Spieler mit aktivem Status werden zurückgegeben.
    """
    league_id = LEAGUE_IDS.get(competition_code)
    if not league_id:
        raise ApisportsUnavailable(f"Unbekannte Liga: {competition_code}")

    def loader():
        raw = _get("injuries", params={"league": league_id, "season": season})

        result = []

        for entry in raw:
            player = entry.get("player") or {}
            team = entry.get("team") or {}
            fixture = entry.get("fixture") or {}

            result.append({
                "player_id": player.get("id"),
                "player_name": player.get("name"),
                "player_photo": player.get("photo"),
                "team_id": team.get("id"),
                "team_name": team.get("name"),
                "team_logo": team.get("logo"),
                "reason": player.get("reason"),
                "type": player.get("type"),
                "fixture_date": fixture.get("date"),
            })

        return result

    return cached_call(
        key=f"apisports:injuries:{competition_code}:{season}",
        ttl_seconds=TTL_INJURIES,
        loader=loader,
    )


# ---------------------------------------------------------------------------
# Spielersuche
# ---------------------------------------------------------------------------

def search_player(name, team_id=None, season=CURRENT_SEASON):
    """
    Sucht einen Spieler nach Name.
    Rückgabe: erste Treffer-Liste, unverarbeitet.
    """
    params = {"search": name, "season": season}
    if team_id:
        params["team"] = team_id

    raw = _get("players", params=params)

    result = []

    for entry in raw[:10]:
        player = entry.get("player") or {}
        stats_list = entry.get("statistics") or [{}]
        stats = stats_list[0] if stats_list else {}
        team = stats.get("team") or {}

        result.append({
            "player_id": player.get("id"),
            "player_name": player.get("name"),
            "player_photo": player.get("photo"),
            "nationality": player.get("nationality"),
            "age": player.get("age"),
            "position": player.get("position"),
            "team_name": team.get("name"),
            "team_logo": team.get("logo"),
        })

    return result


# ---------------------------------------------------------------------------
# Tagesverbrauch überwachen
# ---------------------------------------------------------------------------

def get_request_usage():
    """
    Prüft wie viele der 100 täglichen Requests noch übrig sind.
    Dieser Aufruf selbst verbraucht einen Request.
    """
    try:
        response = requests.get(
            f"{BASE_URL}/status",
            headers=_headers(),
            timeout=15
        )

        if response.status_code != 200:
            return None

        data = response.json()
        sub = data.get("response", {}).get("requests") or {}

        return {
            "used": sub.get("current", 0),
            "limit": sub.get("limit_day", 100),
            "remaining": sub.get("limit_day", 100) - sub.get("current", 0),
        }

    except Exception:
        return None
