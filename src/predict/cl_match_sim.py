"""
Einzelspielsimulation fuer die Champions-League-Ligaphase (Block B1).

Warum ein eigenes Modul, getrennt von league_match_sim.py?
------------------------------------------------------------
league_match_sim.py ist an die fuenf nationalen Ligen gebunden: seine
Fallback-Kette (strength_provider.get_league_strengths) sucht
Team-Historie INNERHALB einer einzigen Liga und kennt eine
Aufsteiger-Stufe. Beides ergibt fuer die Champions League keinen
fachlichen Sinn - CL-Teilnehmer koennen aus jeder europaeischen Liga
kommen, nicht nur aus den fuenf von FootSim simulierten, und es gibt
keine Auf-/Abstiegsbeziehung zwischen CL und den Top-5-Ligen.

Die Fallback-Kette hier ist deshalb bewusst anders (siehe
strength_provider.get_cl_team_strengths fuer die Datengrundlage):

    Stufe 0  Team-ID in der geblendeten Historie EINER der fuenf
             Top-Ligen (deckt die meisten CL-Teilnehmer ab: Bayern,
             PSG, Real Madrid, ...)
    Stufe 1  keine Top-5-Liga-Historie, aber echte CL-Ergebnisse dieser
             Saison vorhanden (Bodoe/Glimt, Galatasaray, Qarabag, ...)
    Stufe 2  neutral_profile - letzter Ausweg

Ersetzt vollstaendig den alten Pfad in simulate_scores.py
(MATCHES_TO_PREDICT_CL-Dictionaries, Teams identifiziert ueber
Klarnamen wie "Bodo Glimt"). Teams werden hier ausschliesslich ueber
football-data-Team-IDs identifiziert. Nutzt dasselbe moderne
Staerkemodell (team_profile.expected_goals) wie die Ligen, nicht die
alte avg_goals_scored/winrate-Formel aus simulate_scores.py.

Deckt in Block B1 nur die Ligaphase ab (Einzelspiel, kein Hin-/
Rueckspiel-Aggregat). Die K.-o.-Phase mit ihrer Zwei-Leg-Logik folgt in
einem spaeteren Schritt, sobald echte Runden/Begegnungen in der
Oberflaeche abgebildet werden (Block B2).
"""

import math
import random
from collections import Counter

from src.features.strength_provider import get_cl_team_strengths
from src.features.team_profile import expected_goals, neutral_profile
from src.utils import cache


def _poisson(lmbda, rng):
    limit = math.exp(-lmbda)
    k, p = 0, 1.0
    while p > limit:
        k += 1
        p *= rng.random()
    return k - 1


def _resolve_cl_profile(strengths, team_id, team_name):
    """
    Loest ein Champions-League-Teamprofil auf.

    Reihenfolge:
      1. Team-ID in der Top-5-Liga-Historie (strengths["domestic_by_id"])
      2. Team-ID in den echten CL-Ergebnissen dieser Saison
         (strengths["cl_current_by_id"])
      3. Neutralprofil (niemals None)

    Rueckgabe: (profil, resolution) - resolution beschreibt den Weg und
    landet in der API-Antwort, damit im Frontend/Debug sichtbar ist, wie
    belastbar der Wert ist.
    """
    domestic = strengths["domestic_by_id"]
    cl_current = strengths["cl_current_by_id"]

    if team_id is not None and team_id in domestic:
        return domestic[team_id], "domestic_history"

    if team_id is not None and team_id in cl_current:
        return cl_current[team_id], "cl_current_season"

    return neutral_profile(team_id, team_name), "neutral"


def simulate_cl_league_phase_match(
    home_team,
    away_team,
    home_id=None,
    away_id=None,
    season=None,
    simulations=5000,
    use_seed=False,
):
    """
    Simuliert ein einzelnes Champions-League-Ligaphasenspiel.

    Liefert dasselbe Antwortformat wie league_match_sim.simulate_league_match
    (das Frontend braucht keine CL-Sonderbehandlung fuer die Grunddaten),
    ergaenzt um Herkunftsangaben je Team (home_resolution/away_resolution).
    """
    rng = random.Random(42 if use_seed else None)

    strength_key = f"cl_strengths:{season}"
    strengths = cache.cached_call(
        key=strength_key,
        ttl_seconds=60 * 30,
        loader=lambda: get_cl_team_strengths(season=season),
    )

    home_profile, home_resolution = _resolve_cl_profile(strengths, home_id, home_team)
    away_profile, away_resolution = _resolve_cl_profile(strengths, away_id, away_team)

    league_avg = strengths["league_avg"]
    xh, xa = expected_goals(home_profile, away_profile, league_avg)

    home_wins = draws = away_wins = 0
    score_counter = Counter()

    for _ in range(simulations):
        hg = _poisson(xh, rng)
        ag = _poisson(xa, rng)
        score_counter[f"{hg}:{ag}"] += 1

        if hg > ag:
            home_wins += 1
        elif hg == ag:
            draws += 1
        else:
            away_wins += 1

    return {
        "home_team": home_team,
        "away_team": away_team,
        "expected_home_goals": round(xh, 2),
        "expected_away_goals": round(xa, 2),
        "home_win_probability": round(home_wins / simulations * 100, 2),
        "draw_probability": round(draws / simulations * 100, 2),
        "away_win_probability": round(away_wins / simulations * 100, 2),
        "top_scores": [
            {"score": score, "count": count}
            for score, count in score_counter.most_common(5)
        ],
        "competition": "Champions League",
        "phase": "league",
        "home_resolution": home_resolution,
        "away_resolution": away_resolution,
    }
