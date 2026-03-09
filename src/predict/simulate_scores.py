import math
import random
from collections import Counter

from src.features.team_strength import get_all_team_strengths
from src.predict.matches_to_predict import MATCHES_TO_PREDICT
from src.utils.data_loader import save_simulation_result


def poisson_sample(lmbda):
    l = math.exp(-lmbda)
    k = 0
    p = 1.0

    while p > l:
        k += 1
        p *= random.random()

    return k - 1


def clamp_value(value, min_value=0.2, max_value=3.5):
    return max(min_value, min(value, max_value))


def calculate_expected_goals(home_strength, away_strength):
    home_attack = home_strength["avg_goals_scored"]
    home_defense = home_strength["avg_goals_conceded"]
    home_points = home_strength["points_per_game"]
    home_winrate = home_strength["winrate"]

    away_attack = away_strength["avg_goals_scored"]
    away_defense = away_strength["avg_goals_conceded"]
    away_points = away_strength["points_per_game"]
    away_winrate = away_strength["winrate"]

    expected_home_goals = (
        home_attack * 0.45
        + away_defense * 0.25
        + home_points * 0.15
        + home_winrate * 0.35
        + 0.25
    )

    expected_away_goals = (
        away_attack * 0.45
        + home_defense * 0.25
        + away_points * 0.15
        + away_winrate * 0.35
    )

    expected_home_goals = clamp_value(expected_home_goals)
    expected_away_goals = clamp_value(expected_away_goals)

    return expected_home_goals, expected_away_goals


def simulate_match_many_times(home_team, away_team, home_strength, away_strength, simulations=5000):
    expected_home_goals, expected_away_goals = calculate_expected_goals(home_strength, away_strength)

    home_wins = 0
    draws = 0
    away_wins = 0
    score_counter = Counter()

    for _ in range(simulations):
        home_goals = poisson_sample(expected_home_goals)
        away_goals = poisson_sample(expected_away_goals)

        score_counter[f"{home_goals}:{away_goals}"] += 1

        if home_goals > away_goals:
            home_wins += 1
        elif home_goals == away_goals:
            draws += 1
        else:
            away_wins += 1

    result = {
        "home_team": home_team,
        "away_team": away_team,
        "expected_home_goals": round(expected_home_goals, 2),
        "expected_away_goals": round(expected_away_goals, 2),
        "home_win_probability": round(home_wins / simulations * 100, 2),
        "draw_probability": round(draws / simulations * 100, 2),
        "away_win_probability": round(away_wins / simulations * 100, 2),
        "top_scores": [
            {"score": score, "count": count}
            for score, count in score_counter.most_common(5)
        ]
    }

    save_simulation_result(result)
    return result


def simulate_selected_match(match_id, simulations=5000, use_seed=False):
    if use_seed:
        random.seed(42)

    if match_id not in MATCHES_TO_PREDICT:
        raise ValueError("Ungültige Match ID")

    strengths = get_all_team_strengths(last_n=5)
    home_team, away_team = MATCHES_TO_PREDICT[match_id]

    if home_team not in strengths or away_team not in strengths:
        raise ValueError("Teamdaten fehlen")

    return simulate_match_many_times(
        home_team,
        away_team,
        strengths[home_team],
        strengths[away_team],
        simulations=simulations
    )