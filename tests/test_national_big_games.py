"""Focused pure-domain tests for National-Team Big Games."""

import pytest

from src.features import national_big_games as nbg


FRANCE = 85
DR_CONGO = 9001
SPAIN = 86


def senior_team(team_id, name):
    return {"id": team_id, "name": name, "national": True}


def fixture(fixture_id=101, competition_id=1, competition_name="World Cup",
            round_name="Group A - 1", home=senior_team(FRANCE, "France"),
            away=senior_team(DR_CONGO, "DR Congo"), status="FT"):
    return {
        "fixture": {
            "id": fixture_id,
            "date": "2022-12-01T19:00:00+00:00",
            "status": {"short": status},
        },
        "league": {
            "id": competition_id,
            "name": competition_name,
            "round": round_name,
        },
        "teams": {"home": home, "away": away},
    }


def classify(raw, own_team_id, ranking=None, own_team=None, opponent_team=None):
    perspective = nbg.resolve_opponent(raw, own_team_id)
    assert perspective is not None
    return nbg.classify_national_fixture(
        raw,
        own_team_id,
        ranking,
        own_team=own_team or perspective["own_team"],
        opponent_team=opponent_team or perspective["opponent"],
    )


class TestFifaTop20AndStrength:
    @pytest.mark.parametrize("rank", [1, 10, 11, 20])
    def test_top20_qualifies(self, rank):
        assert nbg.is_fifa_top20(rank) is True

    def test_rank_21_and_unknown_do_not_qualify(self):
        assert nbg.is_fifa_top20(21) is False
        assert nbg.is_fifa_top20(None) is False

    def test_two_strength_tiers_are_modest_and_ordered(self):
        elite = nbg.national_opponent_strength(10)
        other_top20 = nbg.national_opponent_strength(11)
        assert elite > other_top20 > nbg.FIFA_STRENGTH_UNKNOWN
        assert elite - other_top20 <= 0.05
        assert nbg.national_opponent_strength(21) == nbg.FIFA_STRENGTH_UNKNOWN

    def test_ranking_row_must_match_exact_opponent_id(self):
        raw = fixture(competition_id=10, competition_name="Friendlies")
        result = classify(raw, FRANCE, {"rank": 3, "apisports_team_id": SPAIN})
        assert result["opponent_rank"] is None
        assert result["ranking_qualified"] is False
        assert result["is_big_game"] is False

    @pytest.mark.parametrize("competition_id", [10, 480, 999999])
    def test_only_exact_supported_competitive_competitions_can_enter_big_games(
        self, competition_id
    ):
        raw = fixture(competition_id=competition_id, competition_name="Excluded")
        result = classify(raw, FRANCE, {"rank": 1, "apisports_team_id": DR_CONGO})

        assert result["competition_eligible"] is False
        assert result["ranking_qualified"] is False
        assert result["is_big_game"] is False
        assert result["reason"] == "not_competitive_competition"

    def test_supported_nations_league_keeps_top20_boundary(self):
        raw = fixture(competition_id=5, competition_name="UEFA Nations League")
        rank_20 = classify(raw, FRANCE, {"rank": 20, "apisports_team_id": DR_CONGO})
        rank_21 = classify(raw, FRANCE, {"rank": 21, "apisports_team_id": DR_CONGO})

        assert rank_20["competition_eligible"] is True
        assert rank_20["is_big_game"] is True
        assert rank_21["is_big_game"] is False


class TestPlayerPerspective:
    def test_same_group_fixture_qualifies_only_for_lower_ranked_side(self):
        raw = fixture()

        france_result = classify(
            raw, FRANCE, {"rank": 55, "apisports_team_id": DR_CONGO}
        )
        congo_result = classify(
            raw, DR_CONGO, {"rank": 3, "apisports_team_id": FRANCE}
        )

        assert france_result["opponent_id"] == DR_CONGO
        assert france_result["is_big_game"] is False
        assert congo_result["opponent_id"] == FRANCE
        assert congo_result["is_big_game"] is True
        assert congo_result["qualification_reasons"] == ["fifa_top20_opponent"]

    def test_away_perspective_resolves_exact_other_team(self):
        raw = fixture()
        result = classify(raw, DR_CONGO, {"rank": 5, "apisports_team_id": FRANCE})
        assert result["is_home"] is False
        assert result["opponent"]["side"] == "home"
        assert result["opponent_id"] == FRANCE


class TestSeniorIdentity:
    def test_exact_senior_metadata_is_required(self):
        assert nbg.is_senior_national_team(senior_team(FRANCE, "France")) is True
        assert nbg.is_senior_national_team({"id": FRANCE, "name": "France"}) is False
        assert nbg.is_senior_national_team({"id": 0, "name": "France", "national": True}) is False

    @pytest.mark.parametrize("name", ["France U21", "France U-23", "France Women", "France Olympic"])
    def test_explicit_non_senior_labels_are_rejected(self, name):
        assert nbg.is_senior_national_team({"id": FRANCE, "name": name, "national": True}) is False

    def test_ambiguous_or_metadata_mismatch_fixture_fails_closed(self):
        raw = fixture()
        assert nbg.classify_national_fixture(raw, FRANCE, 3) is not None
        # The fixture has national=True, so the first assertion demonstrates
        # that a fully annotated provider fixture can be accepted.
        assert classify(
            raw,
            FRANCE,
            3,
            own_team=senior_team(SPAIN, "Spain"),
            opponent_team=senior_team(DR_CONGO, "DR Congo"),
        ) is None

    def test_abbreviated_fixture_teams_without_national_metadata_fail_closed(self):
        raw = fixture(
            home={"id": FRANCE, "name": "France"},
            away={"id": DR_CONGO, "name": "DR Congo"},
        )
        assert nbg.classify_national_fixture(raw, FRANCE, 3) is None

    def test_fixture_youth_marker_overrides_stale_generic_metadata(self):
        raw = fixture(home={"id": FRANCE, "name": "France U21"})
        assert classify(
            raw,
            FRANCE,
            {"rank": 3, "apisports_team_id": DR_CONGO},
            own_team=senior_team(FRANCE, "France"),
            opponent_team=senior_team(DR_CONGO, "DR Congo"),
        ) is None


class TestRoundAndEligibility:
    @pytest.mark.parametrize("raw,expected", [
        ("Group A - 2", nbg.STAGE_GROUP),
        ("Round of 32", nbg.STAGE_ROUND_OF_32),
        ("Round of 16", nbg.STAGE_ROUND_OF_16),
        ("Quarter-finals", nbg.STAGE_QUARTERFINAL),
        ("Semi-finals", nbg.STAGE_SEMIFINAL),
        ("Final", nbg.STAGE_FINAL),
        ("3rd Place Final", nbg.STAGE_THIRD_PLACE),
    ])
    def test_normalizes_explicit_provider_stages(self, raw, expected):
        assert nbg.normalize_national_round(raw) == expected

    @pytest.mark.parametrize("competition_id", [nbg.WORLD_CUP_COMPETITION_ID, nbg.EURO_COMPETITION_ID])
    @pytest.mark.parametrize("round_name", [
        "Round of 32", "Round of 16", "Quarter-finals", "Semi-finals", "Final",
    ])
    def test_world_cup_and_euro_knockouts_qualify_without_top20_opponent(
        self, competition_id, round_name
    ):
        raw = fixture(competition_id=competition_id, round_name=round_name)
        result = classify(raw, FRANCE, {"rank": 55, "apisports_team_id": DR_CONGO})
        assert result["knockout_qualified"] is True
        assert result["ranking_qualified"] is False
        assert result["is_big_game"] is True

    @pytest.mark.parametrize("competition_id", [nbg.WORLD_CUP_COMPETITION_ID, nbg.EURO_COMPETITION_ID])
    def test_world_cup_and_euro_group_is_not_automatic(self, competition_id):
        raw = fixture(competition_id=competition_id, round_name="Group Stage - 1")
        weak = classify(raw, FRANCE, {"rank": 55, "apisports_team_id": DR_CONGO})
        strong = classify(raw, FRANCE, {"rank": 20, "apisports_team_id": DR_CONGO})
        assert weak["knockout_qualified"] is False
        assert weak["is_big_game"] is False
        assert strong["knockout_qualified"] is False
        assert strong["is_big_game"] is True

    @pytest.mark.parametrize("competition_id,competition_name", [
        (5, "UEFA Nations League"),
        (29, "World Cup - Qualification Africa"),
        (6, "Africa Cup of Nations"),
    ])
    def test_other_competitions_are_rank_only(self, competition_id, competition_name):
        raw = fixture(
            competition_id=competition_id,
            competition_name=competition_name,
            round_name="Quarter-finals",
        )
        weak = classify(raw, FRANCE, {"rank": 21, "apisports_team_id": DR_CONGO})
        strong = classify(raw, FRANCE, {"rank": 12, "apisports_team_id": DR_CONGO})
        assert weak["knockout_qualified"] is False
        assert weak["is_big_game"] is False
        assert weak["importance"] == nbg.IMPORTANCE_BASE
        assert strong["ranking_qualified"] is True
        assert strong["is_big_game"] is True

    @pytest.mark.parametrize("rank", [1, 10, 20])
    def test_friendlies_never_qualify_against_a_world_class_opponent(self, rank):
        raw = fixture(
            competition_id=10,
            competition_name="Friendlies",
            round_name="Final",
        )
        result = classify(raw, FRANCE, {"rank": rank, "apisports_team_id": DR_CONGO})

        assert result["competition_eligible"] is False
        assert result["ranking_qualified"] is False
        assert result["knockout_qualified"] is False
        assert result["qualification_reasons"] == []
        assert result["is_big_game"] is False

    def test_top20_knockout_has_two_reasons_but_one_fixture(self):
        raw = fixture(round_name="Quarter-finals")
        result = classify(raw, FRANCE, {"rank": 3, "apisports_team_id": DR_CONGO})
        assert result["qualification_reasons"] == [
            "fifa_top20_opponent", "world_cup_or_euro_knockout"
        ]
        assert result["is_big_game"] is True

    def test_third_place_is_not_an_implicit_automatic_knockout(self):
        raw = fixture(round_name="3rd Place Final")
        result = classify(raw, FRANCE, {"rank": 55, "apisports_team_id": DR_CONGO})
        assert result["stage"] == nbg.STAGE_THIRD_PLACE
        assert result["is_big_game"] is False

    def test_unfinished_fixture_is_skipped(self):
        assert classify(fixture(status="NS"), FRANCE, 3) is None


class TestEqualGoalAssistContribution:
    def test_one_goal_equals_one_assist(self):
        assert nbg.goal_assist_contribution(1, 0) == 1
        assert nbg.goal_assist_contribution(0, 1) == 1
        assert nbg.goal_assist_contribution(1, 1) == 2

    def test_context_weight_preserves_goal_assist_equality(self):
        goal = nbg.weighted_goal_assist_contribution(1, 0, 1.08)
        assist = nbg.weighted_goal_assist_contribution(0, 1, 1.08)
        assert goal == pytest.approx(assist)
        assert nbg.weighted_goal_assist_contribution(1, 1, 1.08) == pytest.approx(goal * 2)

    def test_missing_values_remain_unknown(self):
        assert nbg.goal_assist_contribution(None, None) is None


class TestFixtureDeduplication:
    def test_same_fixture_is_once_and_keeps_all_reasons(self):
        first = {
            "fixture_id": 501,
            "source": "national",
            "ranking_qualified": True,
            "knockout_qualified": False,
            "is_big_game": True,
            "qualification_reasons": ["fifa_top20_opponent"],
        }
        duplicate = {
            "fixture_id": 501,
            "source": "national",
            "ranking_qualified": False,
            "knockout_qualified": True,
            "is_big_game": True,
            "qualification_reasons": ["world_cup_or_euro_knockout"],
        }
        result = nbg.dedupe_fixtures([first, duplicate])
        assert len(result) == 1
        assert result[0]["qualification_reasons"] == [
            "fifa_top20_opponent", "world_cup_or_euro_knockout"
        ]
        assert result[0]["ranking_qualified"] is True
        assert result[0]["knockout_qualified"] is True
        assert first["qualification_reasons"] == ["fifa_top20_opponent"]

    def test_entries_without_stable_fixture_id_are_skipped(self):
        assert nbg.dedupe_fixtures([{"fixture_id": None}, {"fixture_id": 7}]) == [
            {"fixture_id": 7}
        ]
