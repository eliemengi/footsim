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


def get_team_strengths_by_id(last_n=5):
    """
    Wie get_all_team_strengths, aber indiziert nach team_id statt Name.

    Grund: In team_matches.json existieren fuer denselben Verein teils
    mehrere Namens-Keys (z. B. 'Chelsea' und 'Chelsea FC', beide id=61).
    Namens-Matching ist dadurch ein Gluecksspiel. Die team_id ist
    eindeutig und wird sowohl von der Tabelle als auch von den
    Spielplan-Daten geliefert, deshalb matchen wir darueber.

    Rueckgabe: { team_id: {avg_goals_scored, ..., matches_used} }
    Wenn zwei Namens-Keys dieselbe id teilen, gewinnt der Eintrag mit
    mehr ausgewerteten Spielen (mehr Datenbasis).
    """
    all_data = load_raw_team_matches()
    by_id = {}

    for team_data in all_data.values():
        team_id = team_data.get("team_id")
        if team_id is None:
            continue

        strength = calculate_team_strength(team_data, last_n=last_n)

        existing = by_id.get(team_id)
        if existing is None or strength["matches_used"] > existing["matches_used"]:
            by_id[team_id] = strength

    return by_id