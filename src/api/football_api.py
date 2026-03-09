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


def find_team_by_name(search_name):
    competitions = ["PL", "PD", "BL1", "SA", "CL"]
    all_teams = []

    for comp in competitions:
        url = f"{BASE_URL}/competitions/{comp}/teams"

        time.sleep(7)
        response = requests.get(url, headers=HEADERS)

        if response.status_code != 200:
            continue

        data = response.json()
        teams = data.get("teams", [])
        all_teams.extend(teams)

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

    time.sleep(7)
    response = requests.get(url, headers=HEADERS)

    if response.status_code != 200:
        raise Exception(f"Fehler beim Laden der Spiele: {response.status_code} - {response.text}")

    return response.json()


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