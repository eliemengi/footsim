import json
import os
import time

from src.api.football_api import find_team_by_name, get_team_matches
from src.predict.simulate_scores import run_score_simulations
from src.utils.team_aliases import TEAM_ALIASES


all_team_data = {}

for short_name, api_name in TEAM_ALIASES.items():
    print(f"Lade Team: {short_name} -> {api_name}")

    team = find_team_by_name(api_name)

    if not team:
        print(f"Team nicht gefunden: {api_name}")
        continue

    team_id = team["id"]
    team_name = team["name"]

    print(f"Gefunden: {team_name} | ID: {team_id}")

    matches_data = get_team_matches(team_id, limit=15)

    if isinstance(matches_data, dict):
        matches_list = matches_data.get("matches", [])
    else:
        matches_list = matches_data

    time.sleep(7)

    all_team_data[short_name] = {
        "team_id": team_id,
        "team_name": team_name,
        "matches": matches_list
    }

os.makedirs("data/raw", exist_ok=True)

output_path = "data/raw/team_matches.json"

with open(output_path, "w", encoding="utf-8") as file:
    json.dump(all_team_data, file, ensure_ascii=False, indent=4)

print(f"\nAlle Teamdaten wurden gespeichert in: {output_path}")
print(f"Anzahl gespeicherter Teams: {len(all_team_data)}")

run_score_simulations()