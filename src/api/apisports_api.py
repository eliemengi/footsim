"""
API-Sports (api-football.com) Zugriff für FootSim.

Zweck: Ergänzt football-data.org dort, wo dessen Free-Tier Lücken hat.
       Konkret: Spielerstatistiken, Top-Scorer mit Fotos, Verletzungen,
       sowie seit Live-Block A die Fixtures/Live-Daten (siehe live_api.py).

Plan-Limits (am Konto verifiziert, Stand August 2026):
    Plan "Pro", 7.500 Requests pro Tag

Frueher stand hier "Free-Plan, 100 Requests pro Tag". Das war seit dem
Upgrade veraltet und hat die Architektur unnoetig eingeschraenkt.

Trotz des groesseren Budgets wird hier weiterhin konsequent gecacht: ein
Cache-Miss soll genau einen externen Request kosten, nicht einen pro
Nutzer. Das ist eine Frage sauberen Server-Designs, nicht des Kontingents.
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
# Unveraenderte Eintraege fuer Simulation und bestehende Features:
LEAGUE_IDS = {
    "bl1": 78,    # Bundesliga
    "pl":  39,    # Premier League
    "pd":  140,   # LaLiga
    "sa":  135,   # Serie A
    "fl1": 61,    # Ligue 1
    "cl":  2,     # Champions League
    "el":  3,     # Europa League
    # Zusaetzliche Ligen fuer den Transfervergleich:
    "ned1": 88,   # Eredivisie
    "por1": 94,   # Primeira Liga
    "bel1": 144,  # Belgische Pro League
    "tur1": 203,  # Suepper Lig
    "aut1": 218,  # Oesterreichische Bundesliga
    "sui1": 207,  # Schweizer Super League
    "sco1": 179,  # Scottish Premiership
    "mls":  253,  # MLS
    "sau1": 307,  # Saudi Pro League
    "bra1": 71,   # Brasileirao Serie A
    "arg1": 128,  # Primera Division Argentina
    "mex1": 262,  # Liga MX
    "jpn1": 98,   # J1 League
    # Zweite und dritte Ligen:
    "bl2":  79,   # 2. Bundesliga
    "bl3":  80,   # 3. Liga
    "eng2": 40,   # Championship
    "eng3": 41,   # League One
    "eng4": 42,   # League Two
    "pd2":  141,  # LaLiga Hypermotion
    "sa2":  136,  # Serie B
    "fl2":  62,   # Ligue 2
}

# Cache-Zeiten. Bewusst lang: diese Daten aendern sich nicht im
# Minutentakt. Live-Daten haben eigene, kurze TTLs (src/utils/cache.py).
TTL_PLAYERS   = 60 * 60 * 6    # 6 Stunden
TTL_INJURIES  = 60 * 60 * 3    # 3 Stunden
TTL_STANDINGS = 60 * 60 * 2    # 2 Stunden


class ApisportsUnavailable(Exception):
    pass


class ApisportsRateLimit(ApisportsUnavailable):
    """Tages- oder Minutenlimit des API-Sports-Plans erreicht."""
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
        raise ApisportsRateLimit("API-Sports Rate Limit erreicht (HTTP 429)")

    if response.status_code != 200:
        raise ApisportsUnavailable(f"API-Sports: HTTP {response.status_code}")

    data = response.json()

    # API-Sports liefert Fehler im Body mit errors-Feld.
    # ACHTUNG: Auch Rate-Limit-Fehler kommen teils mit HTTP 200 im Body
    # (Schluessel 'requests' oder 'rateLimit').
    errors = data.get("errors", {})
    if errors:
        if isinstance(errors, dict) and ("requests" in errors or "rateLimit" in errors):
            raise ApisportsRateLimit(f"API-Sports Limit erreicht: {errors}")
        raise ApisportsUnavailable(f"API-Sports Fehler: {errors}")

    return data.get("response", [])


def _get_full(endpoint, params=None):
    """
    Wie _get(), liefert aber die VOLLSTAENDIGE API-Antwort zurueck.

    Hintergrund (Phase 3):
        _get() gibt nur data["response"] zurueck. Fuer paginierte Endpunkte
        wie /players?league=X&season=Y geht dabei der paging-Block verloren,
        sodass ein Importer nicht wissen kann, wie viele Seiten es gibt.

    Rueckgabe:
        {
          "response": [...],          # Nutzdaten dieser Seite
          "results":  20,             # Anzahl Eintraege dieser Seite
          "paging":   {"current": 1, "total": 28},
        }

    Bewusst eine eigene Funktion statt einer Signaturaenderung an _get(),
    damit bestehende Aufrufer (Transfervergleich, Torjaeger, Verletzungen)
    unveraendert weiterlaufen.
    """
    if not APISPORTS_KEY:
        raise ApisportsUnavailable("APISPORTS_KEY fehlt in der .env")

    url = f"{BASE_URL}/{endpoint}"

    try:
        response = requests.get(url, headers=_headers(), params=params or {}, timeout=20)
    except requests.RequestException as e:
        raise ApisportsUnavailable(f"Netzwerkfehler: {e}")

    if response.status_code == 429:
        raise ApisportsRateLimit("API-Sports Rate Limit erreicht (HTTP 429)")

    if response.status_code != 200:
        raise ApisportsUnavailable(f"API-Sports: HTTP {response.status_code}")

    data = response.json()

    errors = data.get("errors", {})
    if errors:
        if isinstance(errors, dict) and ("requests" in errors or "rateLimit" in errors):
            raise ApisportsRateLimit(f"API-Sports Limit erreicht: {errors}")
        raise ApisportsUnavailable(f"API-Sports Fehler: {errors}")

    paging = data.get("paging") or {}

    return {
        "response": data.get("response", []),
        "results": data.get("results", 0),
        "paging": {
            "current": paging.get("current", 1),
            "total": paging.get("total", 1),
        },
    }


def get_league_players_page(league_code, season, page=1):
    """
    Eine Seite der Spielerliste einer Liga (20 Eintraege pro Seite).

    NUR fuer den Importjob gedacht (refresh_players.py), nicht fuer
    Nutzeranfragen: eine komplette Liga braucht rund 26 bis 31 Seiten.

    Kein Cache an dieser Stelle. Der Importer entscheidet selbst, was er
    persistiert, damit nicht hunderte Einzelseiten im Cache landen.
    """
    league_id = LEAGUE_IDS.get(league_code)
    if not league_id:
        raise ApisportsUnavailable(f"Unbekannte Liga: {league_code}")

    return _get_full("players", params={
        "league": league_id,
        "season": season,
        "page": page,
    })


# ---------------------------------------------------------------------------
# Fixtures (Basis fuer den Live-Bereich)
# ---------------------------------------------------------------------------

# API-Football rechnet Datumsgrenze UND die zurueckgegebenen Anstosszeiten
# in diese Zone um, inklusive Sommer-/Winterzeit. Damit muss FootSim
# nirgends selbst einen UTC-Offset rechnen.
DISPLAY_TIMEZONE = "Europe/Berlin"


def get_fixtures_by_date(date_str, timezone=DISPLAY_TIMEZONE):
    """
    Alle Spiele eines Kalendertags - weltweit, mit EINEM Request.

    Bewusst ohne Liga-Filter: ein Request pro Liga waere bei sieben
    Wettbewerben siebenmal so teuer. Gefiltert wird serverseitig im
    Aufrufer (src/api/live_api.py), der die FootSim-Wettbewerbe kennt.

    Bewusst ohne Cache: die TTL haengt davon ab, ob an diesem Tag noch
    gespielt wird. Das weiss erst der Aufrufer, nachdem er die Antwort
    gesehen hat. Gleiches Muster wie get_league_players_page().

    date_str: "YYYY-MM-DD", interpretiert in der uebergebenen Zeitzone.
    """
    return _get("fixtures", params={"date": date_str, "timezone": timezone})


# ---------------------------------------------------------------------------
# Einzelnes Spiel: Details, Ereignisse, Aufstellungen, Statistiken
# ---------------------------------------------------------------------------
#
# Vier getrennte Endpunkte fuer dasselbe Spiel. Alle vier bewusst ohne
# eigenen Cache: das Match Center (src/api/live_api.py) fuehrt sie zu
# EINEM Payload zusammen und cacht diesen gemeinsam. Ein Cache je
# Teilaspekt waere vier Eintraege mit derselben Lebensdauer - mehr
# Verwaltung ohne Nutzen. Gleiches Muster wie get_fixtures_by_date().

def get_fixture_by_id(fixture_id, timezone=DISPLAY_TIMEZONE):
    """
    Stammdaten eines Spiels: Teams, Stand, Status, Stadion, Schiedsrichter.

    Rueckgabe ist eine Liste mit hoechstens einem Eintrag (so antwortet
    der Endpunkt), oder eine leere Liste bei unbekannter fixture id.
    """
    return _get("fixtures", params={"id": fixture_id, "timezone": timezone})


def get_fixture_events(fixture_id):
    """Tore, Karten und Wechsel eines Spiels in zeitlicher Reihenfolge."""
    return _get("fixtures/events", params={"fixture": fixture_id})


def get_fixture_lineups(fixture_id):
    """
    Aufstellungen beider Teams: Formation, Startelf, Bank, Trainer.

    Vor der Aufstellungsveroeffentlichung antwortet der Endpunkt mit
    einer leeren Liste - das ist ein normaler Zustand, kein Fehler.
    """
    return _get("fixtures/lineups", params={"fixture": fixture_id})


def get_fixture_statistics(fixture_id):
    """
    Teamstatistiken eines Spiels (Ballbesitz, Schuesse, Ecken, ...).

    Vor dem Anpfiff leer. Einzelne Werte koennen je nach Wettbewerb
    null sein - das bedeutet "nicht erhoben", nicht "null".
    """
    return _get("fixtures/statistics", params={"fixture": fixture_id})


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
    Prüft wie viele Requests des Tageskontingents noch übrig sind.
    Das Limit wird aus der Antwort gelesen, nicht angenommen.
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
        response_body = data.get("response") or {}
        sub = response_body.get("requests") or {}
        plan = (response_body.get("subscription") or {}).get("plan")

        used = sub.get("current") or 0
        limit = sub.get("limit_day") or 0

        return {
            "used": used,
            "limit": limit,
            "remaining": limit - used,
            "plan": plan,
        }

    except Exception:
        return None
