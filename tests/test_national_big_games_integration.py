"""Integration contracts for the unified F1+ player Big-Games profile.

The national loader and the club loader deliberately keep their domain rules
separate. These tests cover their one allowed meeting point: normalized,
fixture-ID-deduplicated player matches feed one chronological aggregation and
one existing Big-Games UI.
"""

from src.data import big_games_loader as bgl


def _match(fixture_id, date, source, *, goals=0, assists=0, rating=7.5,
           rank=3, league_name=None, weight=1.0):
    return {
        "fixture_id": fixture_id,
        "date": date,
        "source": source,
        "ranking_source": "fifa" if source == "national" else "uefa",
        "own_team_name": "France" if source == "national" else "Bayern",
        "opponent_name": "Spain" if source == "national" else "Real Madrid",
        "opponent_rank": rank,
        "league_name": league_name or (
            "World Cup" if source == "national" else "Champions League"
        ),
        "is_home": True,
        "minutes": 90,
        "rating": rating,
        "goals": goals,
        "assists": assists,
        "strength": weight,
        "importance": 1.0,
        "weight": weight,
        "position": "Attacker",
        "qualification_reasons": ["fifa_top20_opponent"] if source == "national" else [],
    }


def _club_result(season, matches):
    return {
        "season": season,
        "season_label": f"{season}/{str(season + 1)[-2:]}",
        "available": True,
        "reason": None,
        "provisional": False,
        "matches": matches,
    }


def _national_result(season, matches):
    return {
        "season": season,
        "season_label": f"{season}/{str(season + 1)[-2:]}",
        "available": True,
        "reason": None,
        "provisional": False,
        "matches": matches,
        "unavailable_targets": [],
        "unavailable_ranking_years": [],
    }


class TestUnifiedProfile:
    def test_club_and_national_matches_are_one_chronological_aggregation(self, monkeypatch):
        club = _match(101, "2024-04-30T19:00:00+00:00", "club", goals=1)
        national = _match(202, "2024-06-15T19:00:00+00:00", "national", assists=1)
        monkeypatch.setattr(
            bgl, "get_player_big_games_season", lambda player_id, season: _club_result(season, [club])
        )
        monkeypatch.setattr(
            bgl.national_big_games_loader,
            "get_player_national_big_games_season",
            lambda player_id, season: _national_result(season, [national]),
        )

        result = bgl.get_player_big_games(7, 2024, 2024)

        assert [match["fixture_id"] for match in result["matches"]] == [101, 202]
        assert [match["source"] for match in result["matches"]] == ["club", "national"]
        assert result["summary"]["raw"]["matches"] == 2
        assert result["summary"]["raw"]["goals"] == 1
        assert result["summary"]["raw"]["assists"] == 1
        assert result["summary"]["raw"]["goal_assists"] == 2
        assert result["seasons"][0]["club_match_count"] == 1
        assert result["seasons"][0]["national_match_count"] == 1

    def test_fixture_id_is_deduplicated_across_combined_discovery_paths(self, monkeypatch):
        club = _match(303, "2024-06-20T19:00:00+00:00", "club", goals=1)
        duplicate = _match(303, "2024-06-20T19:00:00+00:00", "national", assists=1)
        duplicate["qualification_reasons"] = [
            "fifa_top20_opponent", "world_cup_or_euro_knockout"
        ]
        monkeypatch.setattr(
            bgl, "get_player_big_games_season", lambda player_id, season: _club_result(season, [club])
        )
        monkeypatch.setattr(
            bgl.national_big_games_loader,
            "get_player_national_big_games_season",
            lambda player_id, season: _national_result(season, [duplicate]),
        )

        result = bgl.get_player_big_games(7, 2024, 2024)

        assert [match["fixture_id"] for match in result["matches"]] == [303]
        assert set(result["matches"][0]["qualification_reasons"]) == {
            "fifa_top20_opponent", "world_cup_or_euro_knockout"
        }

    def test_adjacent_footsim_periods_do_not_leak_national_matches(self, monkeypatch):
        national_by_season = {
            2023: _national_result(2023, [_match(401, "2024-06-15T19:00:00+00:00", "national")]),
            2024: _national_result(2024, [_match(402, "2024-10-15T19:00:00+00:00", "national")]),
        }
        monkeypatch.setattr(
            bgl, "get_player_big_games_season", lambda player_id, season: _club_result(season, [])
        )
        monkeypatch.setattr(
            bgl.national_big_games_loader,
            "get_player_national_big_games_season",
            lambda player_id, season: national_by_season[season],
        )

        result = bgl.get_player_big_games(7, 2023, 2023)

        assert [match["fixture_id"] for match in result["matches"]] == [401]
        assert result["season_from"] == result["season_to"] == 2023

    def test_profile_exposes_only_derived_source_and_ranking_metadata(self, monkeypatch):
        national = _match(505, "2024-06-20T19:00:00+00:00", "national", goals=1, assists=1)
        national.update({
            "ranking_year": 2024,
            "ranking_snapshot_date": "2024-12-19",
            "ranking_snapshot_status": "final",
            "ranking_snapshot_available": True,
        })
        monkeypatch.setattr(
            bgl, "get_player_big_games_season", lambda player_id, season: _club_result(season, [])
        )
        monkeypatch.setattr(
            bgl.national_big_games_loader,
            "get_player_national_big_games_season",
            lambda player_id, season: _national_result(season, [national]),
        )
        monkeypatch.setattr(
            bgl,
            "_player_identity",
            lambda player_id, seasons, season_from, season_to: {
                "player_id": player_id, "name": "Test", "photo": None,
                "nationality": "France", "age": 24,
            },
        )

        profile = bgl.build_big_games_profile(7, 2024, 2024)
        match = profile["matches"][0]

        assert match["source"] == "national"
        assert match["ranking_source"] == "fifa"
        assert match["opponent_rank"] == 3
        assert match["ranking_snapshot_date"] == "2024-12-19"
        assert "opponent_coefficient" not in match
        assert profile["summary"]["raw"]["goal_assists"] == 2


class TestUnifiedUiContract:
    def _script(self):
        with open("static/script.js", encoding="utf-8") as handle:
            return handle.read()

    def test_existing_match_list_chooses_rank_namespace_from_server_metadata(self):
        script = self._script()
        start = script.index("function bgBuildMatchList(player)")
        block = script[start:script.index("function bgBuildPlayerColumn", start)]
        assert 'match.ranking_source === "fifa" ? "FIFA" : "UEFA"' in block
        assert "Verein | Nationalteam" not in block

    def test_raw_and_contextual_goal_assist_dimensions_are_rendered(self):
        script = self._script()
        raw_start = script.index("function bgBuildRawBlock(player)")
        raw_block = script[raw_start:script.index("function bgBuildContextBlock", raw_start)]
        context_start = script.index("function bgBuildContextBlock(player)")
        context_block = script[context_start:script.index("function bgBuildMatchList", context_start)]
        assert "player.summary.raw.goal_assists" in raw_block
        assert '"G+A"' in raw_block
        assert "weighted_goal_assists_per90" in context_block
        assert '"G+A/90 (gew.)"' in context_block
