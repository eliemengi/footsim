import json
import os

from src.api.football_api import (
    find_team_by_name,
    get_team_matches,
    get_bundesliga_matchday_team_map
)

from src.utils.team_aliases import TEAM_ALIASES
from src.predict.matches_to_predict import MATCHES_TO_PREDICT_EL


BUNDESLIGA_MATCHDAY = 26
BUNDESLIGA_SEASON = 2025
MATCH_LIMIT = 15


def load_uel_team_names():
    uel_team_names = set()

    for home_team, away_team in MATCHES_TO_PREDICT_EL.values():
        uel_team_names.add(home_team)
        uel_team_names.add(away_team)

    return uel_team_names


def load_ucl_and_uel_teams(all_team_data):
    uel_team_names = load_uel_team_names()

    for short_name, api_name in TEAM_ALIASES.items():
        print(f"Lade Team: {short_name} -> {api_name}")

        try:
            if short_name in uel_team_names:
                print("API Quelle: API Sports (UEL)")

                team = find_team_by_name_apisports(api_name)

                if not team:
                    print(f"Team nicht gefunden: {api_name}")
                    continue

                team_id = team["id"]
                team_name = team["name"]

                print(f"Gefunden: {team_name} | ID: {team_id}")

                matches_list = get_last_matches_normalized(team_id, limit=MATCH_LIMIT)

            else:
                print("API Quelle: football-data.org (UCL)")

                team = find_team_by_name(api_name)

                if not team:
                    print(f"Team nicht gefunden: {api_name}")
                    continue

                team_id = team["id"]
                team_name = team["name"]

                print(f"Gefunden: {team_name} | ID: {team_id}")

                matches_data = get_team_matches(team_id, limit=MATCH_LIMIT)
                matches_list = matches_data.get("matches", [])

            all_team_data[short_name] = {
                "team_id": team_id,
                "team_name": team_name,
                "matches": matches_list
            }

        except Exception as error:
            print(f"Fehler bei {short_name}: {error}")
            continue


def load_bundesliga_matchday_teams(all_team_data):
    print(f"\nLade Bundesliga Teams für Spieltag {BUNDESLIGA_MATCHDAY} ...")

    try:
        team_map = get_bundesliga_matchday_team_map(
            matchday=BUNDESLIGA_MATCHDAY,
            season=BUNDESLIGA_SEASON
        )
    except Exception as error:
        print(f"Fehler beim Laden der Bundesliga Paarungen: {error}")
        return

    for team_key, team_info in team_map.items():
        try:
            team_id = team_info["id"]
            team_name = team_info["name"]

            print(f"[BL1] Lade {team_name} | ID: {team_id}")

            matches_data = get_team_matches(team_id, limit=MATCH_LIMIT)
            matches_list = matches_data.get("matches", [])

            all_team_data[team_name] = {
                "team_id": team_id,
                "team_name": team_name,
                "matches": matches_list
            }

        except Exception as error:
            print(f"Fehler bei Bundesliga Team {team_key}: {error}")
            continue


def main():
    all_team_data = {}

    load_ucl_and_uel_teams(all_team_data)
    load_bundesliga_matchday_teams(all_team_data)

    os.makedirs("data/raw", exist_ok=True)
    output_path = "data/raw/team_matches.json"

    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(all_team_data, file, ensure_ascii=False, indent=4)

    print(f"\nAlle Teamdaten wurden gespeichert in: {output_path}")
    print(f"Anzahl gespeicherter Teams: {len(all_team_data)}")


if __name__ == "__main__":
    main()