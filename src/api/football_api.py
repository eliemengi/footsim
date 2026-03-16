import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("FOOTBALL_API_KEY")
BASE_URL = "https://api.football-data.org/v4"

HEADERS = {
    "X-Auth-Token": API_KEY
}

KNOWN_TEAM_IDS = {
    "Paris Saint-Germain FC": 524,
    "Chelsea FC": 61,
    "Galatasaray SK": 610,
    "Liverpool FC": 64,
    "Real Madrid CF": 86,
    "Manchester City FC": 65,
    "Atalanta BC": 102,
    "FC Bayern München": 5,
    "Newcastle United FC": 67,
    "FC Barcelona": 81,
    "Club Atlético de Madrid": 78,
    "Tottenham Hotspur FC": 73,
    "FK Bodø/Glimt": 754,
    "Sporting Clube de Portugal": 498,
    "Bayer 04 Leverkusen": 3,
    "Arsenal FC": 57
}


def parse_wait_seconds(message):
    if not message:
        return 7

    if "Wait" in message and "seconds" in message:
        try:
            wait_part = message.split("Wait")[1].split("seconds")[0]
            wait_part = wait_part.replace(".", "").strip()
            return int(wait_part)
        except Exception:
            return 7

    return 7


def get_json_with_retry(url, timeout=20, retries=5):
    for attempt in range(retries):
        response = requests.get(url, headers=HEADERS, timeout=timeout)

        if response.status_code == 200:
            return response.json()

        if response.status_code == 429:
            wait_seconds = 7
            try:
                data = response.json()
                wait_seconds = parse_wait_seconds(data.get("message", ""))
            except Exception:
                pass

            print(f"Rate limit bei {url} -> warte {wait_seconds} Sekunden...")
            time.sleep(wait_seconds)
            continue

        return None

    return None


def find_team_by_name(search_name):
    if search_name in KNOWN_TEAM_IDS:
        return {
            "id": KNOWN_TEAM_IDS[search_name],
            "name": search_name
        }

    competitions = [
        "PL",
        "PD",
        "BL1",
        "SA",
        "FL1",
        "PPL",
        "DED",
        "BSA",
        "ELC",
        "CL"
    ]

    all_teams = []
    seen_ids = set()

    for comp in competitions:
        url = f"{BASE_URL}/competitions/{comp}/teams"
        data = get_json_with_retry(url, timeout=20, retries=3)

        if not data:
            print(f"Competition {comp} konnte nicht geladen werden")
            continue

        teams = data.get("teams", [])

        for team in teams:
            team_id = team.get("id")
            if team_id not in seen_ids:
                seen_ids.add(team_id)
                all_teams.append(team)

    search_lower = search_name.lower().strip()

    exact_matches = []
    startswith_matches = []
    contains_matches = []

    for team in all_teams:
        team_name = team["name"]
        team_lower = team_name.lower().strip()

        if team_lower == search_lower:
            exact_matches.append(team)
        elif team_lower.startswith(search_lower):
            startswith_matches.append(team)
        elif search_lower in team_lower:
            contains_matches.append(team)

    if exact_matches:
        return exact_matches[0]

    if startswith_matches:
        return startswith_matches[0]

    if contains_matches:
        return contains_matches[0]

    return None


def get_team_matches(team_id, limit=10):
    url = f"{BASE_URL}/teams/{team_id}/matches?status=FINISHED&limit={limit}"
    data = get_json_with_retry(url, timeout=20, retries=5)

    if not data:
        raise Exception("Fehler beim Laden der Spiele nach mehreren Versuchen")

    return data


def get_bundesliga_matchday_matches(matchday=26, season=2025):
    url = f"{BASE_URL}/competitions/BL1/matches?season={season}&matchday={matchday}"
    data = get_json_with_retry(url, timeout=20, retries=5)

    if not data:
        raise Exception("Fehler beim Laden der Bundesliga Spiele nach mehreren Versuchen")

    return data.get("matches", [])


def get_bundesliga_matchday_match_options(matchday=26, season=2025):
    matches = get_bundesliga_matchday_matches(matchday=matchday, season=season)

    options = []

    for match in matches:
        home_team = match["homeTeam"]["name"]
        away_team = match["awayTeam"]["name"]

        match_id = f"bl1_{matchday}_{home_team.lower().replace(' ', '_')}_vs_{away_team.lower().replace(' ', '_')}"

        options.append({
            "id": match_id,
            "home_team": home_team,
            "away_team": away_team,
            "label": f"{home_team} vs {away_team}",
            "matchday": matchday,
            "competition": "bl1"
        })

    return options


def get_bundesliga_matchday_team_map(matchday=26, season=2025):
    matches = get_bundesliga_matchday_matches(matchday=matchday, season=season)

    team_map = {}

    for match in matches:
        home = match["homeTeam"]
        away = match["awayTeam"]

        team_map[home["name"]] = {
            "id": home["id"],
            "name": home["name"]
        }

        team_map[away["name"]] = {
            "id": away["id"],
            "name": away["name"]
        }

    return team_map


def get_premier_league_matchday_matches(matchday=30, season=2025):
    url = f"{BASE_URL}/competitions/PL/matches?season={season}&matchday={matchday}"
    data = get_json_with_retry(url, timeout=20, retries=5)

    if not data:
        raise Exception("Fehler beim Laden der Premier League Spiele nach mehreren Versuchen")

    return data.get("matches", [])


def get_premier_league_matchday_match_options(matchday=30, season=2025):
    matches = get_premier_league_matchday_matches(matchday=matchday, season=season)

    options = []

    for match in matches:
        home_team = match["homeTeam"]["name"]
        away_team = match["awayTeam"]["name"]

        match_id = f"pl_{matchday}_{home_team.lower().replace(' ', '_')}_vs_{away_team.lower().replace(' ', '_')}"

        options.append({
            "id": match_id,
            "home_team": home_team,
            "away_team": away_team,
            "label": f"{home_team} vs {away_team}",
            "matchday": matchday,
            "competition": "pl"
        })

    return options


def get_premier_league_matchday_team_map(matchday=30, season=2025):
    matches = get_premier_league_matchday_matches(matchday=matchday, season=season)

    team_map = {}

    for match in matches:
        home = match["homeTeam"]
        away = match["awayTeam"]

        team_map[home["name"]] = {
            "id": home["id"],
            "name": home["name"]
        }

        team_map[away["name"]] = {
            "id": away["id"],
            "name": away["name"]
        }

    return team_map


def get_laliga_matchday_matches(matchday=30, season=2025):
    url = f"{BASE_URL}/competitions/PD/matches?season={season}&matchday={matchday}"
    data = get_json_with_retry(url, timeout=20, retries=5)

    if not data:
        raise Exception("Fehler beim Laden der LaLiga Spiele nach mehreren Versuchen")

    return data.get("matches", [])


def get_laliga_matchday_match_options(matchday=30, season=2025):
    matches = get_laliga_matchday_matches(matchday=matchday, season=season)

    options = []

    for match in matches:
        home_team = match["homeTeam"]["name"]
        away_team = match["awayTeam"]["name"]

        match_id = f"pd_{matchday}_{home_team.lower().replace(' ', '_')}_vs_{away_team.lower().replace(' ', '_')}"

        options.append({
            "id": match_id,
            "home_team": home_team,
            "away_team": away_team,
            "label": f"{home_team} vs {away_team}",
            "matchday": matchday,
            "competition": "pd"
        })

    return options


def get_laliga_matchday_team_map(matchday=30, season=2025):
    matches = get_laliga_matchday_matches(matchday=matchday, season=season)

    team_map = {}

    for match in matches:
        home = match["homeTeam"]
        away = match["awayTeam"]

        team_map[home["name"]] = {
            "id": home["id"],
            "name": home["name"]
        }

        team_map[away["name"]] = {
            "id": away["id"],
            "name": away["name"]
        }

    return team_map


def get_serie_a_matchday_matches(matchday=30, season=2025):
    url = f"{BASE_URL}/competitions/SA/matches?season={season}&matchday={matchday}"
    data = get_json_with_retry(url, timeout=20, retries=5)

    if not data:
        raise Exception("Fehler beim Laden der Serie A Spiele nach mehreren Versuchen")

    return data.get("matches", [])


def get_serie_a_matchday_match_options(matchday=30, season=2025):
    matches = get_serie_a_matchday_matches(matchday=matchday, season=season)

    options = []

    for match in matches:
        home_team = match["homeTeam"]["name"]
        away_team = match["awayTeam"]["name"]

        match_id = f"sa_{matchday}_{home_team.lower().replace(' ', '_')}_vs_{away_team.lower().replace(' ', '_')}"

        options.append({
            "id": match_id,
            "home_team": home_team,
            "away_team": away_team,
            "label": f"{home_team} vs {away_team}",
            "matchday": matchday,
            "competition": "sa"
        })

    return options


def get_serie_a_matchday_team_map(matchday=30, season=2025):
    matches = get_serie_a_matchday_matches(matchday=matchday, season=season)

    team_map = {}

    for match in matches:
        home = match["homeTeam"]
        away = match["awayTeam"]

        team_map[home["name"]] = {
            "id": home["id"],
            "name": home["name"]
        }

        team_map[away["name"]] = {
            "id": away["id"],
            "name": away["name"]
        }

    return team_map


def print_team_matches(data):
    matches = data.get("matches", [])

    for match in matches:
        home_team = match["homeTeam"]["name"]
        away_team = match["awayTeam"]["name"]
        utc_date = match["utcDate"]

        score = match.get("score", {}).get("fullTime", {})
        home_goals = score.get("home")
        away_goals = score.get("away")

        status = match["status"]

        print(f"{utc_date} | {home_team} vs {away_team} | {home_goals}:{away_goals} | {status}")