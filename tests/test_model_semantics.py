"""
Tests der Modellsemantik: Attack/Defence-Richtung, xG-Formel,
Heim-/Auswaertstrennung, Saisongewichtung.
"""

from src.features.team_profile import (
    build_season_profiles,
    blend_profiles,
    expected_goals,
    neutral_profile,
    season_weights,
)
from tests.conftest import make_historical_payload


TEAMS = list(range(1, 19))
STRONG = [1]
WEAK = [18]


def build_profiles():
    payload = make_historical_payload(TEAMS, season=2025, strong=STRONG, weak=WEAK)
    return build_season_profiles(payload)


# ---------------------------------------------------------------------------
# Semantik der Ratings
# ---------------------------------------------------------------------------

def test_strong_attack_increases_xg():
    data = build_profiles()
    avg = data["league_avg"]
    strong = data["profiles"][STRONG[0]]
    neutral = neutral_profile(0, "Durchschnitt")

    xg_strong, _ = expected_goals(strong, neutral, avg)
    xg_neutral, _ = expected_goals(neutral, neutral, avg)

    assert xg_strong > xg_neutral


def test_strong_defence_reduces_opponent_xg():
    """
    Kleinere Defence-Werte bedeuten bessere Defensive und muessen die
    gegnerischen erwarteten Tore REDUZIEREN.
    """
    data = build_profiles()
    avg = data["league_avg"]
    neutral = neutral_profile(0, "Durchschnitt")

    good_defence = dict(neutral)
    good_defence["defence_home"] = 0.70
    good_defence["defence_away"] = 0.70

    bad_defence = dict(neutral)
    bad_defence["defence_home"] = 1.30
    bad_defence["defence_away"] = 1.30

    _, xa_vs_good = expected_goals(good_defence, neutral, avg)
    _, xa_vs_bad = expected_goals(bad_defence, neutral, avg)
    _, xa_vs_neutral = expected_goals(neutral, neutral, avg)

    assert xa_vs_good < xa_vs_neutral < xa_vs_bad


def test_home_and_away_profiles_not_swapped():
    """
    Heim-xG nutzt attack_home des Heimteams und defence_away des Gasts.
    Manipulation genau dieser Felder muss sich auswirken - der jeweils
    andere Kontext darf sich NICHT auswirken.
    """
    data = build_profiles()
    avg = data["league_avg"]
    neutral = neutral_profile(0, "A")

    home_only_strong = dict(neutral)
    home_only_strong["attack_home"] = 1.5   # nur Heimangriff verstaerkt

    xh_base, xa_base = expected_goals(neutral, neutral, avg)
    xh_mod, xa_mod = expected_goals(home_only_strong, neutral, avg)

    assert xh_mod > xh_base            # Heim-xG steigt
    assert abs(xa_mod - xa_base) < 1e-9  # Gast-xG unveraendert

    away_only_strong = dict(neutral)
    away_only_strong["attack_away"] = 1.5  # nur Auswaertsangriff

    xh2, xa2 = expected_goals(neutral, away_only_strong, avg)
    assert xa2 > xa_base
    assert abs(xh2 - xh_base) < 1e-9


def test_home_advantage_is_implicit():
    """Zwei identische Durchschnittsteams: Heim-xG > Gast-xG."""
    data = build_profiles()
    avg = data["league_avg"]
    neutral = neutral_profile(0, "A")

    xh, xa = expected_goals(neutral, neutral, avg)
    assert xh > xa


def test_neutral_profile_produces_league_average():
    data = build_profiles()
    avg = data["league_avg"]
    neutral = neutral_profile(0, "A")

    xh, xa = expected_goals(neutral, neutral, avg)
    assert abs(xh - avg["home_goals"]) < 1e-9
    assert abs(xa - avg["away_goals"]) < 1e-9


# ---------------------------------------------------------------------------
# Saisongewichtung
# ---------------------------------------------------------------------------

def test_newest_season_has_highest_weight():
    weights = season_weights(3)
    assert weights[0] > weights[1] > weights[2]
    assert abs(sum(weights) - 1.0) < 1e-9


def test_blend_uses_newest_first_ordering():
    """
    Team 7 ist in der NEUEREN Saison stark, in der aelteren schwach.
    Das Gesamtprofil muss naeher an der neueren Saison liegen.
    """
    newer = build_season_profiles(
        make_historical_payload(TEAMS, season=2025, strong=[7])
    )
    older = build_season_profiles(
        make_historical_payload(TEAMS, season=2024, weak=[7])
    )

    blended = blend_profiles([newer, older])
    attack = blended[7]["attack_home"]

    newer_attack = newer["profiles"][7]["attack_home"]
    older_attack = older["profiles"][7]["attack_home"]
    midpoint = (newer_attack + older_attack) / 2

    assert attack > midpoint  # naeher an der starken, neueren Saison


def test_partial_participation_renormalizes_weights():
    """
    Ein Team nur in der aelteren Saison darf nicht kuenstlich Richtung
    Ligamittel gezogen werden, sondern behaelt sein volles Saisonprofil.
    """
    only_old_team = 400
    newer = build_season_profiles(make_historical_payload(TEAMS, season=2025))
    older = build_season_profiles(
        make_historical_payload(TEAMS[:-1] + [only_old_team], season=2024,
                                strong=[only_old_team])
    )

    blended = blend_profiles([newer, older])
    assert abs(
        blended[only_old_team]["attack_home"]
        - older["profiles"][only_old_team]["attack_home"]
    ) < 1e-9
