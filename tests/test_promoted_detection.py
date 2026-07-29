"""
Tests fuer Aufsteiger-Erkennung und die Fallback-Kette der Teamstaerken.

Kernregeln:
  * Aufsteiger ist NUR, wer in der unmittelbaren Vorsaison fehlte.
  * "Keine Historie gefunden" bedeutet NICHT Aufsteiger.
  * Jedes Team der Tabelle bekommt IMMER ein gueltiges Profil - kein
    Spiel darf an einem fehlenden Profil scheitern.
"""

import pytest

from src.features import strength_provider
from src.features.strength_provider import get_league_strengths
from tests.conftest import make_historical_payload, make_standings_table


def strengths_with_history(standings_team_ids, history_by_season,
                           current_season=2026, current_matches=None):
    """
    get_league_strengths mit eingeschobener synthetischer Historie.

    history_by_season: {2025: payload, 2024: payload}
    """
    def fake_load(api_code, seasons=None):
        result = []
        for season in sorted(history_by_season, reverse=True):
            result.append((season, history_by_season[season]))
        return result

    original = strength_provider.load_available_seasons
    strength_provider.load_available_seasons = fake_load
    try:
        return get_league_strengths(
            league_key="testliga",
            standings_table=make_standings_table(standings_team_ids),
            current_matches=current_matches,
            current_season=current_season,
            use_squad_data=False,
        )
    finally:
        strength_provider.load_available_seasons = original


OLD_TEAMS = list(range(1, 17))          # seit Jahren dabei
RELEGATED = [90, 91]                     # 2025 dabei, 2026 nicht mehr
PROMOTED = [200, 201]                    # 2026 neu
CURRENT_TEAMS = OLD_TEAMS + PROMOTED     # 18 Teams


def build_two_season_history():
    return {
        2025: make_historical_payload(OLD_TEAMS + RELEGATED, season=2025),
        2024: make_historical_payload(OLD_TEAMS + RELEGATED, season=2024),
    }


# ---------------------------------------------------------------------------
# Aufsteiger-Erkennung
# ---------------------------------------------------------------------------

def test_promoted_detection_uses_previous_season_only():
    data = strengths_with_history(CURRENT_TEAMS, build_two_season_history())

    by_team = {c["team_id"]: c for c in data["coverage"]}

    for team_id in PROMOTED:
        assert by_team[team_id]["is_promoted"] is True
    for team_id in OLD_TEAMS:
        assert by_team[team_id]["is_promoted"] is False

    assert data["summary"]["teams_promoted"] == len(PROMOTED)
    assert data["summary"]["previous_season_available"] is True


def test_missing_history_does_not_imply_promoted():
    """
    Team 55 hat keine Historie (Datenluecke), war aber laut Vorsaison
    dabei -> is_promoted False, has_historical_data False. Beide
    Merkmale muessen getrennt bleiben.
    """
    history = build_two_season_history()
    # Team 55 in die Vorsaison-Teilnehmerliste aufnehmen, aber ohne
    # ein einziges Spiel -> keine Profildaten, nur Teilnahme.
    history[2025]["teams"][55] = {"id": 55, "name": "Team 55",
                                  "short_name": "T55", "crest": None}

    data = strengths_with_history(OLD_TEAMS + [55] + PROMOTED[:1], history)
    entry = next(c for c in data["coverage"] if c["team_id"] == 55)

    assert entry["is_promoted"] is False
    assert entry["has_historical_data"] is False
    # Und trotzdem existiert ein Profil:
    assert data["profiles"][55] is not None


def test_unknown_when_previous_season_missing():
    """Ohne Vorsaison-Daten wird der Status NICHT geraten."""
    history = {2024: make_historical_payload(OLD_TEAMS + RELEGATED, season=2024)}
    data = strengths_with_history(CURRENT_TEAMS, history, current_season=2026)

    for entry in data["coverage"]:
        assert entry["is_promoted"] is None

    assert data["summary"]["teams_promoted"] == 0
    assert data["summary"]["teams_promoted_unknown"] == len(CURRENT_TEAMS)
    assert data["summary"]["previous_season_available"] is False


def test_returning_team_keeps_old_history():
    """
    Wiederaufsteiger: 2026 neu UND mit Erstliga-Historie von 2024.
    is_promoted True und has_historical_data True muessen gleichzeitig
    moeglich sein.
    """
    returner = 300
    history = {
        2025: make_historical_payload(OLD_TEAMS + RELEGATED, season=2025),
        2024: make_historical_payload(OLD_TEAMS + [returner], season=2024),
    }
    data = strengths_with_history(OLD_TEAMS + [returner] + PROMOTED[:1], history)

    entry = next(c for c in data["coverage"] if c["team_id"] == returner)
    assert entry["is_promoted"] is True
    assert entry["has_historical_data"] is True


def test_exactly_promoted_count_no_inflation():
    """Nicht faelschlich 4 oder 5 Aufsteiger, wenn es 2 sind."""
    data = strengths_with_history(CURRENT_TEAMS, build_two_season_history())
    assert data["summary"]["teams_promoted"] == 2


# ---------------------------------------------------------------------------
# Fallback-Kette
# ---------------------------------------------------------------------------

def test_promoted_team_gets_fallback_profile():
    data = strengths_with_history(CURRENT_TEAMS, build_two_season_history())

    for team_id in PROMOTED:
        profile = data["profiles"][team_id]
        assert profile is not None
        assert profile["attack_home"] > 0
        assert profile["defence_home"] > 0
        assert profile["data_source"].startswith("promoted")
        assert profile["fallback_level"] == 3


def test_every_team_gets_a_profile_never_none():
    """Garantie: Selbst ohne jede Historie ist kein Profil None."""
    data = strengths_with_history(CURRENT_TEAMS, {})

    assert len(data["profiles"]) == len(CURRENT_TEAMS)
    for team_id in CURRENT_TEAMS:
        profile = data["profiles"][team_id]
        assert profile is not None
        for key in ("attack_home", "attack_away", "defence_home", "defence_away"):
            assert profile[key] is not None
            assert profile[key] > 0


def test_alias_match_resolves_history():
    """Namensabweichung: Tabelle sagt 'Team 1', Historie kennt die ID."""
    history = build_two_season_history()
    data = strengths_with_history(CURRENT_TEAMS, history)

    entry = next(c for c in data["coverage"] if c["team_id"] == 1)
    assert entry["fallback_level"] == 0
    assert entry["has_historical_data"] is True


def test_promoted_profile_is_below_league_average():
    """Aufsteigerprofil ist konservativ, nicht neutral oder ueberlegen."""
    data = strengths_with_history(CURRENT_TEAMS, build_two_season_history())
    profile = data["profiles"][PROMOTED[0]]

    assert profile["attack_home"] <= 1.0
    assert profile["defence_home"] >= 1.0
