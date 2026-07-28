from src.utils.data_loader import load_raw_team_matches


def calculate_team_strength(team_data, last_n=5):
    matches = team_data["matches"][:last_n]
    team_id = team_data["team_id"]

    goals_scored = 0
    goals_conceded = 0
    wins = 0
    draws = 0
    valid_matches = 0

    for match in matches:
        full_time = match.get("score", {}).get("fullTime", {})
        home_goals = full_time.get("home")
        away_goals = full_time.get("away")

        if home_goals is None or away_goals is None:
            continue

        home_id = match["homeTeam"]["id"]
        away_id = match["awayTeam"]["id"]

        if team_id == home_id:
            team_goals = home_goals
            opponent_goals = away_goals
        elif team_id == away_id:
            team_goals = away_goals
            opponent_goals = home_goals
        else:
            continue

        goals_scored += team_goals
        goals_conceded += opponent_goals
        valid_matches += 1

        if team_goals > opponent_goals:
            wins += 1
        elif team_goals == opponent_goals:
            draws += 1

    if valid_matches == 0:
        return {
            "avg_goals_scored": 0.0,
            "avg_goals_conceded": 0.0,
            "points_per_game": 0.0,
            "winrate": 0.0,
            "matches_used": 0
        }

    points = wins * 3 + draws

    return {
        "avg_goals_scored": goals_scored / valid_matches,
        "avg_goals_conceded": goals_conceded / valid_matches,
        "points_per_game": points / valid_matches,
        "winrate": wins / valid_matches,
        "matches_used": valid_matches
    }


def get_all_team_strengths(last_n=5):
    all_data = load_raw_team_matches()
    strengths = {}

    for short_name, team_data in all_data.items():
        strengths[short_name] = calculate_team_strength(team_data, last_n=last_n)

    return strengths