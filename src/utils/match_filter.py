import json


TARGET_MATCHES = [
    ("Galatasaray SK", "Liverpool FC"),
    ("Atlético de Madrid", "Tottenham Hotspur FC"),
    ("Newcastle United FC", "FC Barcelona"),
    ("Atalanta BC", "FC Bayern München")
]


def load_cl_matches(file_path="data/raw/cl_matches.json"):
    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)


def find_target_matches(data, target_matches=TARGET_MATCHES):
    matches = data.get("matches", [])
    found_matches = []

    for match in matches:
        home_team = match["homeTeam"]["name"]
        away_team = match["awayTeam"]["name"]

        for target_home, target_away in target_matches:
            if home_team == target_home and away_team == target_away:
                found_matches.append(match)

    return found_matches