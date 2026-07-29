"""Semantik des Staerkemodells: Vorzeichen, Venues, Gewichte (Audit §15, §16)."""
import pytest
from src.features.team_profile import (
    expected_goals, neutral_profile, season_weights, blend_profiles,
)
from src.features.dynamic_weights import current_season_weight, DEFAULT_K

AVG = {"home_goals": 1.60, "away_goals": 1.25}


def _profile(**overrides):
    base = neutral_profile(1, "Testklub")
    base.update(overrides)
    return base


def test_starke_defensive_senkt_gegnerische_erwartungstore():
    stark = _profile(defence_home=0.7, defence_away=0.7)
    xg_home, _ = expected_goals(neutral_profile(), stark, AVG)
    assert xg_home < AVG["home_goals"]


def test_schwache_defensive_erhoeht_gegnerische_erwartungstore():
    schwach = _profile(defence_home=1.3, defence_away=1.3)
    xg_home, _ = expected_goals(neutral_profile(), schwach, AVG)
    assert xg_home > AVG["home_goals"]


def test_heim_und_auswaertsstaerke_sind_nicht_vertauscht():
    heimstark = _profile(attack_home=1.6, attack_away=0.8)
    xg_als_heim, _ = expected_goals(heimstark, neutral_profile(), AVG)
    _, xg_als_gast = expected_goals(neutral_profile(), heimstark, AVG)
    assert xg_als_heim > AVG["home_goals"]
    assert xg_als_gast < AVG["away_goals"]


def test_neutral_gegen_neutral_ergibt_exakt_den_ligaschnitt():
    xh, xa = expected_goals(neutral_profile(), neutral_profile(), AVG)
    assert xh == pytest.approx(AVG["home_goals"])
    assert xa == pytest.approx(AVG["away_goals"])


def test_neueste_saison_hat_das_hoechste_gewicht():
    weights = season_weights(3)
    assert weights[0] > weights[1] > weights[2]
    assert sum(weights) == pytest.approx(1.0)

    neu = {"season": 2025, "league_avg": AVG,
           "profiles": {1: _profile(attack_home=1.6, matches_played=34)}}
    alt = {"season": 2024, "league_avg": AVG,
           "profiles": {1: _profile(attack_home=0.8, matches_played=34)}}
    blended = blend_profiles([neu, alt])
    assert blended[1]["attack_home"] > 1.2      # naeher an der neuen Saison


def test_dynamische_gewichtung_startet_bei_null_und_waechst_monoton():
    assert current_season_weight(0) == 0.0
    assert current_season_weight(DEFAULT_K) == pytest.approx(0.5)
    values = [current_season_weight(n) for n in range(0, 35)]
    assert all(b >= a for a, b in zip(values, values[1:]))
    assert values[-1] < 1.0                     # Historie bleibt immer beteiligt
