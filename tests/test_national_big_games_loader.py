"""Focused contract tests for the match-level National Big Games loader."""

from copy import deepcopy

import pytest

from src.data import national_big_games_loader as loader


@pytest.fixture(autouse=True)
def isolated_disk_cache(tmp_path, monkeypatch):
    """The loader must never populate the repository's real runtime cache in tests."""
    from src.utils import disk_cache
    monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path))


def target(league_id=1, api_season=2022, name="World Cup"):
    return {"league_id": league_id, "api_season": api_season, "name": name}


def player_block(team_id=2, league_id=1, api_season=2022, team_name="France"):
    return {
        "team": {"id": team_id, "name": team_name, "logo": f"https://x/{team_id}.png"},
        "league": {
            "id": league_id,
            "name": "World Cup" if league_id == 1 else "Friendlies",
            "season": api_season,
        },
    }


def fixture(fixture_id=101, *, home_id=2, away_id=99, date="2022-12-10T19:00:00+00:00",
            league_id=1, api_season=2022, round_name="Quarter-finals", status="FT"):
    return {
        "fixture": {"id": fixture_id, "date": date, "status": {"short": status}},
        "teams": {
            "home": {"id": home_id, "name": "France", "logo": "https://x/fr.png"},
            "away": {"id": away_id, "name": "Opponent", "logo": "https://x/op.png"},
        },
        "league": {
            "id": league_id,
            "name": "World Cup" if league_id == 1 else "Friendlies",
            "season": api_season,
            "round": round_name,
        },
    }


def senior_team(team_id, name=None):
    return {
        "id": team_id,
        "name": name or f"Team {team_id}",
        "national": True,
        "logo": f"https://x/{team_id}.png",
    }


def player_line(player_id=7, *, minutes=90, rating="7.4", goals=1, assists=1):
    return [{
        "players": [{
            "player": {"id": player_id},
            "statistics": [{
                "games": {"minutes": minutes, "rating": rating, "position": "M"},
                "goals": {"total": goals, "assists": assists, "saves": None, "conceded": 0},
                "shots": {"total": 1, "on": 1},
                "passes": {"total": 30, "key": 2},
                "tackles": {"total": 2, "interceptions": 1},
                "duels": {"total": 4, "won": 3},
                "dribbles": {"attempts": 2, "success": 1},
            }],
        }],
    }]


def configure_one_target(monkeypatch, *, footsim_season=2021, target_value=None,
                         raw_blocks=None, imported_blocks=None):
    selected_target = target_value or target()
    monkeypatch.setattr(loader, "national_targets_for_footsim_season",
                        lambda season: [selected_target] if season == footsim_season else [])
    monkeypatch.setattr(
        loader,
        "get_player_season_raw",
        lambda player_id, api_season: {
            "player": {"id": player_id},
            "statistics": raw_blocks if raw_blocks is not None else [player_block()],
        },
    )
    import src.data.national_import as national_import
    monkeypatch.setattr(national_import, "get_national_blocks",
                        lambda player_id, season: imported_blocks or [])


class TestNationalEngagementDiscovery:
    def test_uses_target_api_season_and_exact_league(self, monkeypatch):
        selected = target(league_id=4, api_season=2024, name="Euro Championship")
        calls = []
        monkeypatch.setattr(loader, "national_targets_for_footsim_season", lambda s: [selected])

        def raw(player_id, api_season):
            calls.append(api_season)
            return {"statistics": [
                player_block(team_id=2, league_id=4, api_season=2024),
                player_block(team_id=55, league_id=10, api_season=2024),
            ]}

        monkeypatch.setattr(loader, "get_player_season_raw", raw)
        import src.data.national_import as national_import
        monkeypatch.setattr(national_import, "get_national_blocks", lambda *args: [])

        engagements = loader.player_national_engagements(7, 2023)
        assert calls == [2024]
        assert [(e["team_id"], e["league_id"], e["api_season"])
                for e in engagements] == [(2, 4, 2024)]

    def test_import_fallback_requires_composite_league_and_api_season(self, monkeypatch):
        selected = target(league_id=10, api_season=2026, name="Friendlies")
        configure_one_target(
            monkeypatch,
            footsim_season=2025,
            target_value=selected,
            raw_blocks=[],
            imported_blocks=[
                player_block(team_id=16, league_id=10, api_season=2025),
                player_block(team_id=26, league_id=10, api_season=2026),
            ],
        )

        engagements = loader.player_national_engagements(7, 2025)
        assert [(e["team_id"], e["league_id"], e["api_season"])
                for e in engagements] == [(26, 10, 2026)]

    def test_duplicate_profile_and_import_block_has_one_discovery_key(self, monkeypatch):
        block = player_block()
        configure_one_target(monkeypatch, raw_blocks=[block], imported_blocks=[deepcopy(block)])

        engagements = loader.player_national_engagements(7, 2021)
        assert len(engagements) == 1
        assert engagements[0]["source"] == "player_profile"


class TestNationalFixtureLoader:
    def test_normalizes_qualifying_fixture_with_player_statistics(self, monkeypatch):
        configure_one_target(monkeypatch)
        raw = fixture()
        monkeypatch.setattr(loader, "_team_identity", lambda team_id: senior_team(team_id))
        monkeypatch.setattr(loader, "_team_season_fixtures", lambda *args: [raw])
        monkeypatch.setattr(loader, "_fixture_players", lambda fixture_id: player_line())
        monkeypatch.setattr(loader.fifa_rankings, "lookup_team",
                        lambda year, team_id: {"rank": 3} if (year, team_id) == (2022, 99) else None)
        monkeypatch.setattr(loader.fifa_rankings, "load_snapshot", lambda year: {
            "available": True, "snapshot_date": "2022-12-22", "status": "final",
            "provisional": False,
        })

        result = loader._season_result(7, 2021)

        assert result["available"] is True
        assert len(result["matches"]) == 1
        match = result["matches"][0]
        assert match["fixture_id"] == 101
        assert match["source"] == "national"
        assert match["ranking_source"] == "fifa"
        assert match["opponent_rank"] == 3
        assert match["ranking_qualified"] is True
        assert match["minutes"] == 90
        assert match["rating"] == 7.4
        assert match["goals"] == 1
        assert match["assists"] == 1

    def test_knockout_survives_missing_ranking_snapshot_neutrally(self, monkeypatch):
        configure_one_target(monkeypatch)
        monkeypatch.setattr(loader, "_team_identity", lambda team_id: senior_team(team_id))
        monkeypatch.setattr(loader, "_team_season_fixtures", lambda *args: [fixture()])
        monkeypatch.setattr(loader, "_fixture_players", lambda fixture_id: player_line(goals=0, assists=0))
        monkeypatch.setattr(loader.fifa_rankings, "lookup_team", lambda year, team_id: None)
        monkeypatch.setattr(loader.fifa_rankings, "load_snapshot", lambda year: {
            "available": False, "snapshot_date": None, "status": None, "provisional": False,
        })

        match = loader._season_result(7, 2021)["matches"][0]
        assert match["ranking_qualified"] is False
        assert match["knockout_qualified"] is True
        assert match["ranking_snapshot_available"] is False
        assert match["weight"] > 1.0

    def test_group_stage_non_top20_does_not_fetch_fixture_players(self, monkeypatch):
        configure_one_target(monkeypatch)
        monkeypatch.setattr(loader, "_team_identity", lambda team_id: senior_team(team_id))
        monkeypatch.setattr(loader, "_team_season_fixtures",
                        lambda *args: [fixture(round_name="Group A")])
        monkeypatch.setattr(loader.fifa_rankings, "lookup_team", lambda *args: None)
        monkeypatch.setattr(loader.fifa_rankings, "load_snapshot", lambda *args: {"available": True})

        def player_call(*args):
            raise AssertionError("player stats must be fetched only after qualification")

        monkeypatch.setattr(loader, "_fixture_players", player_call)
        assert loader._season_result(7, 2021)["matches"] == []

    def test_friendly_top20_opponent_never_fetches_fixture_players(self, monkeypatch):
        friendly_target = target(league_id=10, api_season=2022, name="Friendlies")
        configure_one_target(monkeypatch, target_value=friendly_target)
        monkeypatch.setattr(loader, "_team_identity", lambda team_id: senior_team(team_id))
        monkeypatch.setattr(
            loader,
            "_team_season_fixtures",
            lambda *args: [fixture(league_id=10, api_season=2022, round_name="Final")],
        )
        monkeypatch.setattr(loader.fifa_rankings, "lookup_team", lambda *args: {"rank": 1})
        monkeypatch.setattr(loader.fifa_rankings, "load_snapshot", lambda *args: {"available": True})
        monkeypatch.setattr(
            loader,
            "_fixture_players",
            lambda *args: pytest.fail("Friendlies must never request player statistics"),
        )

        assert loader._season_result(7, 2021)["matches"] == []

    def test_missing_snapshot_is_reported_even_when_group_fixture_is_skipped(self, monkeypatch):
        configure_one_target(monkeypatch)
        monkeypatch.setattr(loader, "_team_identity", lambda team_id: senior_team(team_id))
        monkeypatch.setattr(loader, "_team_season_fixtures",
                        lambda *args: [fixture(round_name="Group A")])
        monkeypatch.setattr(loader.fifa_rankings, "lookup_team", lambda *args: None)
        monkeypatch.setattr(loader.fifa_rankings, "load_snapshot", lambda *args: {
            "available": False, "provisional": False,
        })
        monkeypatch.setattr(loader, "_fixture_players", lambda *args: pytest.fail("not qualified"))

        result = loader._season_result(7, 2021)
        assert result["matches"] == []
        assert result["unavailable_ranking_years"] == [2022]

    def test_unverified_or_youth_team_fails_closed_before_fixtures(self, monkeypatch):
        configure_one_target(monkeypatch)
        youth = senior_team(2, "France U21")
        monkeypatch.setattr(loader, "_team_identity", lambda team_id: youth)

        def fixtures_call(*args):
            raise AssertionError("an unverified senior identity must stop discovery")

        monkeypatch.setattr(loader, "_team_season_fixtures", fixtures_call)
        assert loader._season_result(7, 2021)["matches"] == []

    def test_same_fixture_discovered_twice_is_loaded_once(self, monkeypatch):
        raw_blocks = [player_block(team_id=2), player_block(team_id=2)]
        configure_one_target(monkeypatch, raw_blocks=raw_blocks)
        calls = []
        monkeypatch.setattr(loader, "_team_identity", lambda team_id: senior_team(team_id))
        monkeypatch.setattr(loader, "_team_season_fixtures", lambda *args: [fixture()])
        monkeypatch.setattr(loader, "_fixture_players", lambda fixture_id: calls.append(fixture_id) or player_line())
        monkeypatch.setattr(loader.fifa_rankings, "lookup_team", lambda *args: {"rank": 11})
        monkeypatch.setattr(loader.fifa_rankings, "load_snapshot", lambda *args: {"available": True})

        result = loader._season_result(7, 2021)
        assert [match["fixture_id"] for match in result["matches"]] == [101]
        assert calls == [101]

    def test_range_uses_footsim_period_and_deduplicates_by_fixture_id(self, monkeypatch):
        per_season = {
            2023: {"season": 2023, "season_label": "2023/24", "available": True,
                   "reason": None, "provisional": False,
                   "matches": [{"fixture_id": 9, "date": "2024-06-15", "source": "national"}],
                   "unavailable_targets": [], "unavailable_ranking_years": []},
            2024: {"season": 2024, "season_label": "2024/25", "available": True,
                   "reason": None, "provisional": False,
                   "matches": [{"fixture_id": 10, "date": "2024-09-01", "source": "national"},
                               {"fixture_id": 9, "date": "2024-06-15", "source": "national"}],
                   "unavailable_targets": [], "unavailable_ranking_years": []},
        }
        monkeypatch.setattr(loader, "get_player_national_big_games_season",
                        lambda player_id, season: per_season[season])

        result = loader.get_player_national_big_games(7, 2023, 2024)
        assert [match["fixture_id"] for match in result["matches"]] == [9, 10]
        assert result["season_from"] == 2023
        assert result["season_to"] == 2024


class TestNationalCacheContract:
    def test_national_cache_namespace_is_distinct_from_club(self):
        assert loader.CACHE_NAMESPACE == "national_big_games:v2"
        assert "biggames:player_season" not in loader.CACHE_NAMESPACE

    def test_invalid_public_input_fails_closed_without_a_request(self, monkeypatch):
        monkeypatch.setattr(loader, "_season_result",
                        lambda *args: pytest.fail("invalid input must not run loader"))
        result = loader.get_player_national_big_games_season("bad", 2021)
        assert result["available"] is False
        assert result["reason"] == "invalid_input"

    def test_fractional_identity_is_not_silently_truncated(self):
        assert loader._as_positive_int(2.9) is None
        assert loader._as_positive_int("2.9") is None
        assert loader._as_positive_int("002") == 2
