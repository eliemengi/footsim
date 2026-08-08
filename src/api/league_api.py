"""
Liga-Datenzugriff fuer football-data.org v4.

Bewusst getrennt von football_api.py:
    football_api.py  = gewachsener Bestand, wird von main.py benutzt, bleibt unangetastet
    league_api.py    = neue, generische Funktionen fuer Tabellen, Torjaeger, Spieltage

Alle Funktionen hier gehen ueber den Cache. Ein Aufruf im Frontend loest also
nicht automatisch einen externen Request aus.
"""

import os
import time
import requests
from dotenv import load_dotenv

from src.utils.disk_cache import disk_cached_call
from src.utils.cache import (
    cached_call,
    TTL_SEASON_INFO,
    TTL_STANDINGS,
    TTL_SCORERS,
    TTL_MATCHES_UPCOMING,
    TTL_MATCHES_FINISHED,
    TTL_TEAMS,
    TTL_CUP_MATCHES,
)

load_dotenv()

API_KEY = os.getenv("FOOTBALL_API_KEY")
BASE_URL = "https://api.football-data.org/v4"

# Fallback, falls die Saison nicht automatisch ermittelt werden kann.
# Bei football-data.org bezeichnet 2026 die Saison 2026/27.
FALLBACK_SEASON = 2026


def _headers():
    if not API_KEY:
        return {}
    return {"X-Auth-Token": API_KEY}


class ApiUnavailable(Exception):
    """Externe API nicht erreichbar oder Datenpunkt nicht im Plan enthalten."""
    pass


def _parse_wait_seconds(message):
    """Liest aus der Rate-Limit-Meldung heraus, wie lange gewartet werden soll."""
    if not message:
        return 7

    if "Wait" in message and "seconds" in message:
        try:
            part = message.split("Wait")[1].split("seconds")[0]
            return int(part.replace(".", "").strip())
        except Exception:
            return 7

    return 7


def _get_json(path, params=None, retries=3):
    """
    Zentraler HTTP-Zugriff mit Retry bei Rate Limit.

    Wirft ApiUnavailable statt einer rohen Exception, damit app.py
    dem Frontend eine saubere Meldung schicken kann.
    """
    if not API_KEY:
        raise ApiUnavailable("FOOTBALL_API_KEY fehlt in der .env")

    url = f"{BASE_URL}{path}"

    for attempt in range(retries):
        try:
            response = requests.get(url, headers=_headers(), params=params, timeout=20)
        except requests.RequestException as error:
            raise ApiUnavailable(f"Netzwerkfehler: {error}")

        if response.status_code == 200:
            return response.json()

        if response.status_code == 429:
            wait = 7
            try:
                wait = _parse_wait_seconds(response.json().get("message", ""))
            except Exception:
                pass

            # Beim letzten Versuch nicht mehr schlafen, sondern aufgeben
            if attempt == retries - 1:
                raise ApiUnavailable("Rate Limit erreicht. Bitte kurz warten.")

            time.sleep(min(wait, 10))
            continue

        if response.status_code == 403:
            raise ApiUnavailable("Dieser Datenpunkt ist im aktuellen API Plan nicht enthalten")

        if response.status_code == 404:
            raise ApiUnavailable("Daten fuer diesen Wettbewerb nicht gefunden")

        raise ApiUnavailable(f"API antwortete mit Status {response.status_code}")

    raise ApiUnavailable("Keine Antwort nach mehreren Versuchen")


# ---------------------------------------------------------------------------
# Saison automatisch erkennen
# ---------------------------------------------------------------------------

def get_season_info(api_code):
    """
    Liefert die aktuell laufende Saison und den aktuellen Spieltag.

    Dadurch muss die Jahreszahl nicht jede Saison im Code geaendert werden.
    Rueckgabe:
        {
            "season": 2026,
            "current_matchday": 3,
            "start_date": "2026-08-14",
            "end_date": "2027-05-15",
            "auto_detected": True
        }
    """
    def loader():
        data = _get_json(f"/competitions/{api_code}")
        current = data.get("currentSeason") or {}

        start_date = current.get("startDate") or ""
        season_year = None

        if len(start_date) >= 4:
            try:
                season_year = int(start_date[:4])
            except ValueError:
                season_year = None

        return {
            "season": season_year or FALLBACK_SEASON,
            "current_matchday": current.get("currentMatchday") or 1,
            "start_date": start_date,
            "end_date": current.get("endDate") or "",
            "auto_detected": season_year is not None,
        }

    try:
        return disk_cached_call(
            key=f"season_info:{api_code}",
            ttl_seconds=TTL_SEASON_INFO,
            loader=loader,
            source="league_api.get_season_info"
        )
    except ApiUnavailable:
        # Die App soll auch dann laufen, wenn dieser Endpunkt nicht verfuegbar ist
        return {
            "season": FALLBACK_SEASON,
            "current_matchday": 1,
            "start_date": "",
            "end_date": "",
            "auto_detected": False,
        }


def resolve_season(api_code, season=None):
    """Nimmt die uebergebene Saison oder ermittelt sie automatisch."""
    if season:
        return int(season)
    return get_season_info(api_code)["season"]


# ---------------------------------------------------------------------------
# Tabellen
# ---------------------------------------------------------------------------

def get_standings(api_code, season=None):
    """
    Liefert die Tabellen eines Wettbewerbs, aufgeteilt nach Gesamt, Heim und Auswaerts.

    Rueckgabe:
        {
            "season": 2026,
            "competition": "Bundesliga",
            "tables": {
                "TOTAL": [ {...zeile...}, ... ],
                "HOME":  [ ... ],
                "AWAY":  [ ... ]
            }
        }
    """
    season = resolve_season(api_code, season)

    def loader():
        data = _get_json(f"/competitions/{api_code}/standings", params={"season": season})

        tables = {}

        for block in data.get("standings", []):
            block_type = block.get("type", "TOTAL")
            rows = []

            for row in block.get("table", []):
                team = row.get("team") or {}
                rows.append({
                    "position": row.get("position"),
                    "team_id": team.get("id"),
                    "team_name": team.get("shortName") or team.get("name"),
                    "team_full_name": team.get("name"),
                    "team_tla": team.get("tla"),
                    "crest": team.get("crest"),
                    "played": row.get("playedGames") or 0,
                    "won": row.get("won") or 0,
                    "draw": row.get("draw") or 0,
                    "lost": row.get("lost") or 0,
                    "points": row.get("points") or 0,
                    "goals_for": row.get("goalsFor") or 0,
                    "goals_against": row.get("goalsAgainst") or 0,
                    "goal_difference": row.get("goalDifference") or 0,
                    "form": row.get("form"),
                })

            tables[block_type] = rows

        competition = data.get("competition") or {}

        return {
            "season": season,
            "competition": competition.get("name", api_code),
            "competition_emblem": competition.get("emblem"),
            "tables": tables,
        }

    return disk_cached_call(
        key=f"standings:{api_code}:{season}",
        ttl_seconds=TTL_STANDINGS,
        loader=loader,
        source="league_api.get_standings"
    )


# ---------------------------------------------------------------------------
# Torjaeger
# ---------------------------------------------------------------------------

def get_scorers(api_code, season=None, limit=20):
    """
    Liefert die Torjaegerliste eines Wettbewerbs.

    Assists sind je nach Wettbewerb und Plan nicht immer gefuellt.
    In dem Fall steht dort None und das Frontend zeigt einen Strich.
    """
    season = resolve_season(api_code, season)

    def loader():
        data = _get_json(
            f"/competitions/{api_code}/scorers",
            params={"season": season, "limit": limit}
        )

        scorers = []

        for index, entry in enumerate(data.get("scorers", []), start=1):
            player = entry.get("player") or {}
            team = entry.get("team") or {}

            goals = entry.get("goals") or 0
            assists = entry.get("assists")
            played = entry.get("playedMatches") or 0

            scorers.append({
                "rank": index,
                "player_id": player.get("id"),
                "player_name": player.get("name"),
                "nationality": player.get("nationality"),
                "position": player.get("position"),
                "date_of_birth": player.get("dateOfBirth"),
                "team_id": team.get("id"),
                "team_name": team.get("shortName") or team.get("name"),
                "team_crest": team.get("crest"),
                "goals": goals,
                "assists": assists,
                "penalties": entry.get("penalties"),
                "played_matches": played,
                "goals_per_match": round(goals / played, 2) if played else None,
                "scorer_points": goals + (assists or 0),
            })

        return {
            "season": season,
            "scorers": scorers,
        }

    return cached_call(
        key=f"scorers:{api_code}:{season}:{limit}",
        ttl_seconds=TTL_SCORERS,
        loader=loader
    )


# ---------------------------------------------------------------------------
# Spieltage, generisch fuer alle Ligen
# ---------------------------------------------------------------------------

def get_current_season(api_code):
    """Nur die Jahreszahl der aktuell laufenden Saison."""
    return get_season_info(api_code)["season"]


def is_current_season(api_code, season):
    """
    Prueft, ob die angefragte Saison die laufende ist.

    Wird gebraucht, um bei abgeschlossenen Saisons alle Spieltage
    freizugeben. Eine gespielte Saison zu sperren waere sinnlos.
    """
    if season is None:
        return True
    return int(season) == get_current_season(api_code)


# ---------------------------------------------------------------------------
# Vereine eines Wettbewerbs, Basis fuer die Liga Zuordnung
# ---------------------------------------------------------------------------

def get_competition_teams(api_code, season=None):
    """
    Alle Vereine eines Wettbewerbs in einer Saison.

    Rueckgabe: { team_id: {"id", "name", "short_name", "tla", "crest"} }

    Wird gebraucht, um Champions League Teilnehmer ihrer Heimatliga
    zuzuordnen. Wichtig dabei: die Zuordnung muss fuer DIE ANALYSIERTE
    Saison geholt werden, nicht fuer die aktuelle. Ein Absteiger waere
    sonst in der falschen Liga oder ganz verschwunden.
    """
    season = resolve_season(api_code, season)

    def loader():
        data = _get_json(f"/competitions/{api_code}/teams", params={"season": season})

        teams = {}

        for team in data.get("teams", []):
            team_id = team.get("id")
            if team_id is None:
                continue

            teams[team_id] = {
                "id": team_id,
                "name": team.get("name"),
                "short_name": team.get("shortName") or team.get("name"),
                "tla": team.get("tla"),
                "crest": team.get("crest"),
            }

        return teams

    return cached_call(
        key=f"teams:{api_code}:{season}",
        ttl_seconds=TTL_TEAMS,
        loader=loader
    )


# ---------------------------------------------------------------------------
# Champions League Spiele inklusive Turnierphase
# ---------------------------------------------------------------------------

def get_cup_matches(api_code, season=None):
    """
    Alle beendeten Spiele eines Pokalwettbewerbs mit Phasenangabe.

    Anders als bei Ligen ist hier das Feld stage entscheidend. Es sagt,
    ob ein Spiel zur Ligaphase, zum Playoff oder zu einer K o Runde gehoert.
    """
    season = resolve_season(api_code, season)

    def loader():
        data = _get_json(
            f"/competitions/{api_code}/matches",
            params={"season": season, "status": "FINISHED"}
        )

        matches = []

        for match in data.get("matches", []):
            score = match.get("score") or {}
            full_time = score.get("fullTime") or {}

            home_goals = full_time.get("home")
            away_goals = full_time.get("away")

            if home_goals is None or away_goals is None:
                continue

            home = match.get("homeTeam") or {}
            away = match.get("awayTeam") or {}

            matches.append({
                "id": match.get("id"),
                "stage": match.get("stage") or "UNKNOWN",
                "group": match.get("group"),
                "matchday": match.get("matchday"),
                "utc_date": match.get("utcDate"),
                "home_id": home.get("id"),
                "away_id": away.get("id"),
                "home_team": home.get("shortName") or home.get("name"),
                "away_team": away.get("shortName") or away.get("name"),
                "home_goals": home_goals,
                "away_goals": away_goals,
                # winner beruecksichtigt bei Finals auch Verlaengerung
                "winner": score.get("winner"),
                "duration": score.get("duration"),
                "penalties_home": (score.get("penalties") or {}).get("home"),
                "penalties_away": (score.get("penalties") or {}).get("away"),
            })

        return matches

    return cached_call(
        key=f"cup_matches:{api_code}:{season}",
        ttl_seconds=TTL_CUP_MATCHES,
        loader=loader
    )


def get_matchday_matches(api_code, matchday, season=None):
    """Rohdaten der Spiele eines Spieltags."""
    season = resolve_season(api_code, season)

    def loader():
        data = _get_json(
            f"/competitions/{api_code}/matches",
            params={"season": season, "matchday": matchday}
        )
        return data.get("matches", [])

    matches = cached_call(
        key=f"matches:{api_code}:{season}:{matchday}",
        ttl_seconds=TTL_MATCHES_UPCOMING,
        loader=loader
    )

    # Wenn alle Spiele abgeschlossen sind, laenger cachen. Die Daten
    # aendern sich dann nicht mehr.
    if matches and all(m.get("status") == "FINISHED" for m in matches):
        cached_call(
            key=f"matches:{api_code}:{season}:{matchday}",
            ttl_seconds=TTL_MATCHES_FINISHED,
            loader=lambda: matches
        )

    return matches


def get_finished_season_matches(api_code, season=None):
    """
    Alle bereits beendeten Spiele einer Saison mit EINEM Request.

    Das ist die Datenbasis fuer den Ligenvergleich. Aus Spielergebnissen
    lassen sich Kennzahlen berechnen, die in der Tabelle nicht stehen,
    zum Beispiel wie oft beide Teams treffen oder wie oft mehr als
    zweieinhalb Tore fallen.
    """
    season = resolve_season(api_code, season)

    def loader():
        data = _get_json(
            f"/competitions/{api_code}/matches",
            params={"season": season, "status": "FINISHED"}
        )

        matches = []

        for match in data.get("matches", []):
            score = (match.get("score") or {}).get("fullTime") or {}
            home_goals = score.get("home")
            away_goals = score.get("away")

            if home_goals is None or away_goals is None:
                continue

            matches.append({
                "matchday": match.get("matchday"),
                "utc_date": match.get("utcDate"),
                "home_team": (match.get("homeTeam") or {}).get("name"),
                "away_team": (match.get("awayTeam") or {}).get("name"),
                "home_goals": home_goals,
                "away_goals": away_goals,
            })

        return matches

    return disk_cached_call(
        key=f"season_matches:{api_code}:{season}",
        ttl_seconds=TTL_STANDINGS,
        loader=loader,
        source="league_api.get_finished_season_matches"
    )


# ---------------------------------------------------------------------------
# Saisonauswahl
# ---------------------------------------------------------------------------

def get_available_seasons(api_code, previous_count=1):
    """
    Liefert die auswaehlbaren Saisons.

    Die laufende Saison steht immer an erster Stelle und ist die Vorauswahl.
    Danach folgen abgeschlossene Saisons, die zum Vergleichen taugen.

    Rueckgabe:
        [
            {"season": 2026, "label": "2026/27", "is_current": True,  "is_complete": False},
            {"season": 2025, "label": "2025/26", "is_current": False, "is_complete": True},
        ]
    """
    info = get_season_info(api_code)
    current = info["season"]

    seasons = [{
        "season": current,
        "label": f"{current}/{str(current + 1)[2:]}",
        "is_current": True,
        "is_complete": False,
    }]

    for offset in range(1, previous_count + 1):
        year = current - offset
        seasons.append({
            "season": year,
            "label": f"{year}/{str(year + 1)[2:]}",
            "is_current": False,
            "is_complete": True,
        })

    return seasons


# ---------------------------------------------------------------------------
# Teams eines Wettbewerbs, inklusive Herkunftsland
# ---------------------------------------------------------------------------

def get_competition_teams(api_code, season=None):
    """
    Alle Teams eines Wettbewerbs mit Herkunftsland.

    Das ist die Grundlage fuer den Champions League Vergleich: nur ueber
    das Herkunftsland laesst sich ein Verein einer nationalen Liga zuordnen.
    Ein Request liefert alle 36 Teilnehmer.

    Rueckgabe:
        {
            team_id: {
                "id": 5,
                "name": "FC Bayern Muenchen",
                "short_name": "Bayern",
                "tla": "FCB",
                "crest": "https://...",
                "country": "Germany",
                "country_code": "DEU",
            },
            ...
        }
    """
    season = resolve_season(api_code, season)

    def loader():
        data = _get_json(f"/competitions/{api_code}/teams", params={"season": season})

        teams = {}

        for team in data.get("teams", []):
            team_id = team.get("id")
            if team_id is None:
                continue

            area = team.get("area") or {}

            teams[team_id] = {
                "id": team_id,
                "name": team.get("name"),
                "short_name": team.get("shortName") or team.get("name"),
                "tla": team.get("tla"),
                "crest": team.get("crest"),
                "country": area.get("name"),
                "country_code": area.get("code"),
            }

        return teams

    return cached_call(
        key=f"competition_teams:{api_code}:{season}",
        ttl_seconds=TTL_MATCHES_FINISHED,
        loader=loader
    )


# ---------------------------------------------------------------------------
# Alle Spiele einer Saison, inklusive Runde
# ---------------------------------------------------------------------------

def get_all_matches(api_code, season=None, only_finished=True):
    """
    Alle Spiele einer Saison mit Rundeninformation.

    Anders als get_finished_season_matches bleibt hier das Feld stage
    erhalten. Nur damit laesst sich Ligaphase von K o Phase trennen.

    Rueckgabe je Spiel:
        {
            "stage": "LEAGUE_STAGE",
            "matchday": 3,
            "utc_date": "...",
            "status": "FINISHED",
            "home_id": 5, "home_team": "FC Bayern",
            "away_id": 81, "away_team": "FC Barcelona",
            "home_goals": 2, "away_goals": 1,
            "home_goals_regular": 2, "away_goals_regular": 1,
            "penalty_home": None, "penalty_away": None,
            "winner": "HOME_TEAM",
        }
    """
    season = resolve_season(api_code, season)

    def loader():
        params = {"season": season}
        if only_finished:
            params["status"] = "FINISHED"

        data = _get_json(f"/competitions/{api_code}/matches", params=params)

        matches = []

        for match in data.get("matches", []):
            score = match.get("score") or {}
            full_time = score.get("fullTime") or {}
            regular = score.get("regularTime") or {}
            penalties = score.get("penalties") or {}

            home = match.get("homeTeam") or {}
            away = match.get("awayTeam") or {}

            home_goals = full_time.get("home")
            away_goals = full_time.get("away")

            # Spiele ohne Ergebnis sind fuer die Auswertung wertlos
            if only_finished and (home_goals is None or away_goals is None):
                continue

            matches.append({
                "id": match.get("id"),
                "stage": match.get("stage"),
                "group": match.get("group"),
                "matchday": match.get("matchday"),
                "utc_date": match.get("utcDate"),
                "status": match.get("status"),
                "home_id": home.get("id"),
                "home_team": home.get("name"),
                "home_crest": home.get("crest"),
                "away_id": away.get("id"),
                "away_team": away.get("name"),
                "away_crest": away.get("crest"),
                "home_goals": home_goals,
                "away_goals": away_goals,
                "home_goals_regular": regular.get("home"),
                "away_goals_regular": regular.get("away"),
                "penalty_home": penalties.get("home"),
                "penalty_away": penalties.get("away"),
                "winner": score.get("winner"),
            })

        return matches

    return cached_call(
        key=f"all_matches:{api_code}:{season}:{only_finished}",
        ttl_seconds=TTL_MATCHES_FINISHED if only_finished else TTL_MATCHES_UPCOMING,
        loader=loader
    )


# ---------------------------------------------------------------------------
# Champions League: stage-gefilterter Ligaphasen-Loader (Block B2)
# ---------------------------------------------------------------------------

def _validate_cl_season(matches, requested_season):
    """
    Prueft, ob die zurueckgegebenen Matches tatsaechlich zur angefragten
    Saison gehoeren. football-data.org liefert bei einer noch nicht
    gestarteten Saison (z. B. season=2026 ohne 2026/27-CL-Daten) still
    die currentSeason zurueck statt einen leeren Response. Ohne diese
    Pruefung wuerden 2025/26-Ergebnisse faelschlich unter 2026/27
    erscheinen.

    Prueft das season.startDate-Feld des ersten zurueckgegebenen Matches.
    Rueckgabe: True wenn die Saison passt oder nicht pruefbar ist
    (dann lieber Daten zeigen als ablehnen), False wenn gesichert eine
    andere Saison zurueckgekommen ist.
    """
    if not matches or requested_season is None:
        return True

    for match in matches:
        season_obj = match.get("season") or {}
        start_date = season_obj.get("startDate") or ""
        if len(start_date) >= 4:
            try:
                response_year = int(start_date[:4])
                return response_year == int(requested_season)
            except (ValueError, TypeError):
                pass
    return True


def get_cl_league_phase_matches(matchday, season=None):
    """
    CL-Ligaphasen-Spiele eines Spieltags mit explizitem stage-Filter.

    Unterschied zu get_matchday_matches:
      - sendet stage=LEAGUE_STAGE an football-data, damit keine
        PLAYOFFS/LAST_16/QUARTER_FINALS-Matches eingemischt werden
      - validiert die Saison der Response (verhindert stille Fallbacks)
      - gibt bei Saison-Mismatch eine leere Liste zurueck

    Domestic-Ligen brauchen diesen Filter nicht, da deren matchday-Werte
    innerhalb einer Saison eindeutig sind. Deshalb ist dies ein eigener
    Loader statt einer Erweiterung von get_matchday_matches.
    """
    season = resolve_season("CL", season)

    def loader():
        data = _get_json(
            "/competitions/CL/matches",
            params={"season": season, "matchday": matchday, "stage": "LEAGUE_STAGE"}
        )
        raw = data.get("matches", [])

        if not _validate_cl_season(raw, season):
            return []

        return raw

    return cached_call(
        key=f"cl_league_phase:{season}:{matchday}",
        ttl_seconds=TTL_MATCHES_UPCOMING,
        loader=loader
    )


def get_cl_knockout_matches(stage, season=None):
    """
    Alle Matches einer bestimmten CL-K.-o.-Stage (z. B. LAST_16).

    Liefert die Matches direkt im football-data-Rohformat, damit der
    Aufrufer (app.py) sie zu Ties gruppieren und Hin-/Rueckspiele
    erkennen kann. Validiert die Saison wie der Ligaphasen-Loader.
    """
    season = resolve_season("CL", season)

    def loader():
        data = _get_json(
            "/competitions/CL/matches",
            params={"season": season, "stage": stage}
        )
        raw = data.get("matches", [])

        if not _validate_cl_season(raw, season):
            return []

        return raw

    return cached_call(
        key=f"cl_knockout:{season}:{stage}",
        ttl_seconds=TTL_MATCHES_UPCOMING,
        loader=loader
    )


def get_cl_league_phase_match_options(matchday, season=None):
    """
    CL-Ligaphasen-Spiele als Frontend-fertige Optionen.

    Wie get_matchday_match_options, aber ueber den stage-gefilterten
    CL-Loader statt ueber get_matchday_matches.
    """
    matches = get_cl_league_phase_matches(matchday, season)

    options = []

    for match in matches:
        home = match.get("homeTeam") or {}
        away = match.get("awayTeam") or {}

        home_name = home.get("name") or "Unbekannt"
        away_name = away.get("name") or "Unbekannt"

        slug_home = home_name.lower().replace(" ", "_")
        slug_away = away_name.lower().replace(" ", "_")

        score = (match.get("score") or {}).get("fullTime") or {}

        options.append({
            "id": f"cl_{matchday}_{slug_home}_vs_{slug_away}",
            "home_team": home_name,
            "away_team": away_name,
            "home_id": home.get("id"),
            "away_id": away.get("id"),
            "home_crest": home.get("crest"),
            "away_crest": away.get("crest"),
            "label": f"{home_name} vs {away_name}",
            "matchday": matchday,
            "competition": "cl",
            "utc_date": match.get("utcDate"),
            "status": match.get("status"),
            "home_score": score.get("home"),
            "away_score": score.get("away"),
        })

    return options


def get_matchday_match_options(competition_code, api_code, matchday, season=None):
    """
    Wandelt die Rohdaten in das Format um, das das Frontend erwartet.
    Ersetzt die vier fast identischen Funktionen aus football_api.py.
    """
    matches = get_matchday_matches(api_code, matchday, season)

    options = []

    for match in matches:
        home = match.get("homeTeam") or {}
        away = match.get("awayTeam") or {}

        home_name = home.get("name") or "Unbekannt"
        away_name = away.get("name") or "Unbekannt"

        slug_home = home_name.lower().replace(" ", "_")
        slug_away = away_name.lower().replace(" ", "_")

        score = (match.get("score") or {}).get("fullTime") or {}

        options.append({
            "id": f"{competition_code}_{matchday}_{slug_home}_vs_{slug_away}",
            "home_team": home_name,
            "away_team": away_name,
            "home_id": home.get("id"),
            "away_id": away.get("id"),
            "home_crest": home.get("crest"),
            "away_crest": away.get("crest"),
            "label": f"{home_name} vs {away_name}",
            "matchday": matchday,
            "competition": competition_code,
            "utc_date": match.get("utcDate"),
            "status": match.get("status"),
            "home_score": score.get("home"),
            "away_score": score.get("away"),
        })

    return options
