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


def normalize_name(name):
    if not name:
        return ""

    text = name.lower().strip()

    replacements = {
        "ü": "u",
        "ö": "o",
        "ä": "a",
        "ß": "ss",
        "-": " ",
        "/": " ",
        ".": " ",
        "'": "",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    removable_words = [
        "fc", "cf", "afc", "cfc", "sc", "ac", "fk", "sk", "bc",
        "club", "the"
    ]

    words = text.split()
    words = [word for word in words if word not in removable_words]

    return " ".join(words)


def find_team_by_name(search_name):
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

        time.sleep(2)
        response = requests.get(url, headers=HEADERS, timeout=20)

        if response.status_code != 200:
            continue

        data = response.json()
        teams = data.get("teams", [])

        for team in teams:
            team_id = team.get("id")
            if team_id not in seen_ids:
                seen_ids.add(team_id)
                all_teams.append(team)

    search_lower = search_name.lower().strip()
    search_normalized = normalize_name(search_name)

    exact_matches = []
    startswith_matches = []
    contains_matches = []
    normalized_matches = []

    for team in all_teams:
        team_name = team["name"]
        team_lower = team_name.lower().strip()
        team_normalized = normalize_name(team_name)

        if team_lower == search_lower:
            exact_matches.append(team)
        elif team_lower.startswith(search_lower):
            startswith_matches.append(team)
        elif search_lower in team_lower:
            contains_matches.append(team)
        elif team_normalized == search_normalized or search_normalized in team_normalized:
            normalized_matches.append(team)

    if exact_matches:
        return exact_matches[0]

    if startswith_matches:
        return startswith_matches[0]

    if contains_matches:
        return contains_matches[0]

    if normalized_matches:
        return normalized_matches[0]

    return None


def get_team_matches(team_id, limit=10):
    url = f"{BASE_URL}/teams/{team_id}/matches?status=FINISHED&limit={limit}"

    time.sleep(2)
    response = requests.get(url, headers=HEADERS, timeout=20)

    if response.status_code != 200:
        raise Exception(f"Fehler beim Laden der Spiele: {response.status_code} - {response.text}")

    return response.json()


def get_bundesliga_matchday_matches(matchday=26, season=2025):
    url = f"{BASE_URL}/competitions/BL1/matches?season={season}&matchday={matchday}"

    response = requests.get(url, headers=HEADERS, timeout=20)

    if response.status_code != 200:
        raise Exception(f"Fehler beim Laden der Bundesliga Spiele: {response.status_code} - {response.text}")

    data = response.json()
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