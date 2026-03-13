import math
import random
from collections import Counter

from src.features.team_strength import get_all_team_strengths
from src.predict.matches_to_predict import (
    MATCHES_TO_PREDICT,
    MATCHES_TO_PREDICT_CL,
    MATCHES_TO_PREDICT_EL,
    UEL_SECOND_LEG_CONTEXT
)
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


def get_penalty_win_probability(home_strength, away_strength):
    home_score = (
        home_strength["points_per_game"] * 0.55
        + home_strength["winrate"] * 0.45
    )

    away_score = (
        away_strength["points_per_game"] * 0.55
        + away_strength["winrate"] * 0.45
    )

    total = home_score + away_score

    if total <= 0:
        return 0.5

    home_probability = home_score / total

    return max(0.35, min(0.65, home_probability))


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


def simulate_uel_second_leg(match_id, home_team, away_team, home_strength, away_strength, simulations=5000):
    context = UEL_SECOND_LEG_CONTEXT[match_id]

    first_leg_home_goals = context["first_leg_home_goals"]
    first_leg_away_goals = context["first_leg_away_goals"]

    expected_home_goals, expected_away_goals = calculate_expected_goals(home_strength, away_strength)

    home_wins = 0
    draws = 0
    away_wins = 0

    home_qualifications = 0
    away_qualifications = 0
    extra_time_count = 0
    penalties_count = 0

    score_counter = Counter()
    aggregate_counter = Counter()

    penalty_home_probability = get_penalty_win_probability(home_strength, away_strength)

    for _ in range(simulations):
        second_leg_home_goals = poisson_sample(expected_home_goals)
        second_leg_away_goals = poisson_sample(expected_away_goals)

        score_counter[f"{second_leg_home_goals}:{second_leg_away_goals}"] += 1

        if second_leg_home_goals > second_leg_away_goals:
            home_wins += 1
        elif second_leg_home_goals == second_leg_away_goals:
            draws += 1
        else:
            away_wins += 1

        aggregate_home = first_leg_away_goals + second_leg_home_goals
        aggregate_away = first_leg_home_goals + second_leg_away_goals

        if aggregate_home > aggregate_away:
            home_qualifications += 1
            aggregate_counter[f"{aggregate_home}:{aggregate_away}"] += 1
            continue

        if aggregate_away > aggregate_home:
            away_qualifications += 1
            aggregate_counter[f"{aggregate_home}:{aggregate_away}"] += 1
            continue

        extra_time_count += 1

        extra_home_goals = poisson_sample(expected_home_goals / 3)
        extra_away_goals = poisson_sample(expected_away_goals / 3)

        aggregate_home += extra_home_goals
        aggregate_away += extra_away_goals

        if aggregate_home > aggregate_away:
            home_qualifications += 1
            aggregate_counter[f"{aggregate_home}:{aggregate_away}"] += 1
            continue

        if aggregate_away > aggregate_home:
            away_qualifications += 1
            aggregate_counter[f"{aggregate_home}:{aggregate_away}"] += 1
            continue

        penalties_count += 1

        if random.random() < penalty_home_probability:
            home_qualifications += 1
        else:
            away_qualifications += 1

        aggregate_counter[f"{aggregate_home}:{aggregate_away}"] += 1

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
        ],
        "is_two_legged_tie": True,
        "competition": "Europa League",
        "tie_format": "second_leg_only",
        "first_leg_score": f"{context['first_leg_home_team']} {first_leg_home_goals}:{first_leg_away_goals} {context['first_leg_away_team']}",
        "qualification_home_probability": round(home_qualifications / simulations * 100, 2),
        "qualification_away_probability": round(away_qualifications / simulations * 100, 2),
        "extra_time_probability": round(extra_time_count / simulations * 100, 2),
        "penalties_probability": round(penalties_count / simulations * 100, 2),
        "top_aggregate_scores": [
            {"score": score, "count": count}
            for score, count in aggregate_counter.most_common(5)
        ]
    }

    save_simulation_result(result)
    return result


def _simulate_direct_team_match(home_team, away_team, strengths, simulations):
    if home_team not in strengths or away_team not in strengths:
        raise ValueError(
            f"Teamdaten fehlen für {home_team} oder {away_team}. "
            f"Führe zuerst python main.py aus, damit team_matches.json aktualisiert wird."
        )

    return simulate_match_many_times(
        home_team,
        away_team,
        strengths[home_team],
        strengths[away_team],
        simulations=simulations
    )


def simulate_selected_match(match_id=None, simulations=5000, use_seed=False, home_team=None, away_team=None):
    if use_seed:
        random.seed(42)

    strengths = get_all_team_strengths(last_n=5)

    if home_team and away_team:
        return _simulate_direct_team_match(
            home_team=home_team,
            away_team=away_team,
            strengths=strengths,
            simulations=simulations
        )

    if not match_id:
        raise ValueError("match_id fehlt")

    if match_id in MATCHES_TO_PREDICT_CL:
        home_team, away_team = MATCHES_TO_PREDICT_CL[match_id]

        if home_team not in strengths or away_team not in strengths:
            raise ValueError("Teamdaten fehlen")

        return simulate_match_many_times(
            home_team,
            away_team,
            strengths[home_team],
            strengths[away_team],
            simulations=simulations
        )

    if match_id in MATCHES_TO_PREDICT_EL:
        home_team, away_team = MATCHES_TO_PREDICT_EL[match_id]

        if home_team not in strengths or away_team not in strengths:
            raise ValueError("Teamdaten fehlen")

        return simulate_uel_second_leg(
            match_id,
            home_team,
            away_team,
            strengths[home_team],
            strengths[away_team],
            simulations=simulations
        )

    if match_id in MATCHES_TO_PREDICT:
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

    raise ValueError("Ungültige Match ID")