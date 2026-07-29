"""
Einzelspielsimulation fuer Ligaspiele ueber das moderne Staerkemodell.

Warum ein eigenes Modul?
------------------------
Der alte Pfad (simulate_scores._simulate_direct_team_match) griff auf
team_matches.json zurueck - eine von main.py gepflegte Datei, die nur die
dort erfassten Teams enthaelt und ueber NAMEN matcht. Jedes neue oder
aufgestiegene Team fehlte darin, und die Simulation brach mit
"Teamdaten fehlen" ab. Genau das Muster:

    etabliert gegen etabliert   -> funktionierte
    Spiel mit Aufsteiger        -> ValueError

Dieser Pfad hier benutzt dieselbe Quelle wie die Saisonsimulation:
strength_provider.get_league_strengths mit der garantierten
Fallback-Kette (ID -> Alias/Name -> laufende Saison -> Aufsteigerprofil
-> Neutralwert). Ein Team ohne Historie fuehrt damit NIE zum Abbruch,
sondern zu einem konservativen Profil mit ausgewiesener Herkunft.

Die Zuordnung laeuft primaer ueber die team_id (Frontend liefert sie
mit), Namen sind nur Notbehelf.
"""

import math
import random
from collections import Counter

from src.api.league_api import get_standings, resolve_season
from src.features.strength_provider import (
    get_league_strengths,
    normalize_name,
    _alias_candidates,
)
from src.features.team_profile import expected_goals, neutral_profile
from src.utils import cache


def _poisson(lmbda, rng):
    limit = math.exp(-lmbda)
    k, p = 0, 1.0
    while p > limit:
        k += 1
        p *= rng.random()
    return k - 1


def _resolve_profile(profiles, standings_rows, team_id, team_name):
    """
    Findet das Profil eines Teams. Reihenfolge:
      1. exakte team_id
      2. team_id ueber die Tabellenzeile mit gleichem Namen
      3. normalisierter Name / Alias gegen die Profil-Namen
      4. Neutralprofil (niemals None)
    Rueckgabe: (profil, resolution) - resolution beschreibt den Weg.
    """
    if team_id is not None and team_id in profiles:
        return profiles[team_id], "id"

    # Tabellenzeile ueber den Namen finden, dann deren ID benutzen.
    wanted = normalize_name(team_name)
    if wanted:
        for row in standings_rows:
            if normalize_name(row.get("team_name")) == wanted \
                    or normalize_name(row.get("team_full_name")) == wanted:
                rid = row.get("team_id")
                if rid in profiles:
                    return profiles[rid], "standings_name"

        # Aliase gegen die Profilnamen selbst.
        candidates = {normalize_name(c) for c in _alias_candidates(team_name)}
        for profile in profiles.values():
            names = {
                normalize_name(profile.get("team_name")),
                normalize_name(profile.get("short_name")),
            }
            if candidates & {n for n in names if n}:
                return profile, "alias"

    return neutral_profile(team_id, team_name), "neutral"


def simulate_league_match(
    competition_code,
    api_code,
    home_team,
    away_team,
    home_id=None,
    away_id=None,
    season=None,
    simulations=5000,
    use_seed=False,
):
    """
    Simuliert ein einzelnes Ligaspiel.

    Liefert dasselbe Antwortformat wie die alte Einzelspielsimulation
    (das Frontend bleibt unveraendert), ergaenzt um Herkunftsangaben.
    """
    rng = random.Random(42 if use_seed else None)
    season = resolve_season(api_code, season)

    standings = get_standings(api_code, season=season)
    table = (standings.get("tables") or {}).get("TOTAL") or []

    strength_key = f"league_strengths:{competition_code}:{season}"
    strength_data = cache.cached_call(
        key=strength_key,
        ttl_seconds=60 * 30,
        loader=lambda: get_league_strengths(
            league_key=competition_code,
            standings_table=table,
            current_matches=None,
            current_season=season,
        ),
    )

    profiles = strength_data["profiles"]
    league_avg = strength_data["league_avg"]

    home_profile, home_resolution = _resolve_profile(profiles, table, home_id, home_team)
    away_profile, away_resolution = _resolve_profile(profiles, table, away_id, away_team)

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
        # Herkunft der Werte, damit im Zweifel nachvollziehbar ist,
        # worauf die Prognose beruht.
        "model": "team_profile_v2",
        "home_data": {
            "resolution": home_resolution,
            "data_source": home_profile.get("data_source", "unknown"),
            "fallback_level": home_profile.get("fallback_level", 4),
            "is_promoted": home_profile.get("is_promoted"),
        },
        "away_data": {
            "resolution": away_resolution,
            "data_source": away_profile.get("data_source", "unknown"),
            "fallback_level": away_profile.get("fallback_level", 4),
            "is_promoted": away_profile.get("is_promoted"),
        },
    }
