"""
Tests fuer den Liga-zu-Liga-Transfervergleich.

Getestet wird ausschliesslich reine Logik ohne API-Zugriff:
    - Transferfilterung (Sommerfenster, Liga-Zugehoerigkeit, Dedup)
    - Statistik-Normalisierung (mehrere statistics-Objekte, Rating als
      String, fehlende Assists)
    - Gruppenbildung und Vergleich (Mindestminuten, Durchschnitte,
      kein kuenstlicher Gesamtsieger)
"""

import pytest

from src.data.transfer_loader import (
    filter_summer_transfers,
    parse_transfer_date,
    is_summer_transfer,
)
from src.data.player_stats_loader import normalize_player_statistics
from src.features.transfer_comparison import (
    MIN_QUALIFYING_MINUTES,
    split_players,
    build_group,
    compare_metric_winners,
    build_comparison_result,
)


# ---------------------------------------------------------------------------
# Hilfsfabriken
# ---------------------------------------------------------------------------

def raw_transfer(player_id, name, out_id, in_id, date, ttype="Free"):
    return {
        "player": {"id": player_id, "name": name},
        "transfers": [{
            "date": date,
            "type": ttype,
            "teams": {
                "in": {"id": in_id, "name": f"In{in_id}", "logo": None},
                "out": {"id": out_id, "name": f"Out{out_id}", "logo": None},
            },
        }],
    }


def player(pid, minutes, goals=0, assists=0, rating=7.0,
           position="Midfielder", available=True):
    return {
        "player_id": pid,
        "player_name": f"Spieler {pid}",
        "data_available": available,
        "minutes": minutes if available else None,
        "appearances": 10 if available else None,
        "goals": goals if available else None,
        "assists": assists,
        "scorer_points": (goals + assists) if (available and assists is not None) else None,
        "rating": rating,
        "position": position,
    }


TARGET_IDS = {100, 101}
SOURCE_IDS = {200, 201}


# ---------------------------------------------------------------------------
# Transferfilterung
# ---------------------------------------------------------------------------

class TestTransferFilter:

    def test_normal_summer_transfer_matched(self):
        entries = [raw_transfer(1, "A", 200, 100, "2024-07-15")]
        result = filter_summer_transfers(entries, TARGET_IDS, SOURCE_IDS,
                                         2024, "bl1", "pl")
        assert len(result) == 1
        assert result[0]["player_id"] == 1
        assert result[0]["transfer_type"] == "Free"
        assert result[0]["source_league"] == "bl1"

    def test_winter_transfer_excluded(self):
        entries = [raw_transfer(1, "A", 200, 100, "2024-01-15")]
        result = filter_summer_transfers(entries, TARGET_IDS, SOURCE_IDS,
                                         2024, "bl1", "pl")
        assert result == []

    def test_wrong_year_excluded(self):
        entries = [raw_transfer(1, "A", 200, 100, "2023-07-15")]
        result = filter_summer_transfers(entries, TARGET_IDS, SOURCE_IDS,
                                         2024, "bl1", "pl")
        assert result == []

    def test_source_not_in_source_league_excluded(self):
        entries = [raw_transfer(1, "A", 999, 100, "2024-07-15")]
        result = filter_summer_transfers(entries, TARGET_IDS, SOURCE_IDS,
                                         2024, "bl1", "pl")
        assert result == []

    def test_target_not_in_target_league_excluded(self):
        entries = [raw_transfer(1, "A", 200, 999, "2024-07-15")]
        result = filter_summer_transfers(entries, TARGET_IDS, SOURCE_IDS,
                                         2024, "bl1", "pl")
        assert result == []

    def test_duplicate_entries_deduplicated(self):
        entries = [
            raw_transfer(1, "A", 200, 100, "2024-07-15"),
            raw_transfer(1, "A", 200, 100, "2024-07-15"),
        ]
        result = filter_summer_transfers(entries, TARGET_IDS, SOURCE_IDS,
                                         2024, "bl1", "pl")
        assert len(result) == 1

    def test_multiple_summer_moves_latest_wins(self):
        # Spieler wechselt zweimal im selben Sommer in die Zielliga:
        # der spaetere Wechsel zaehlt.
        entries = [
            raw_transfer(1, "A", 200, 100, "2024-06-10", ttype="Loan"),
            raw_transfer(1, "A", 201, 101, "2024-08-20", ttype="Free"),
        ]
        result = filter_summer_transfers(entries, TARGET_IDS, SOURCE_IDS,
                                         2024, "bl1", "pl")
        assert len(result) == 1
        assert result[0]["to_team_id"] == 101
        assert result[0]["transfer_type"] == "Free"

    def test_loan_type_kept(self):
        entries = [raw_transfer(1, "A", 200, 100, "2024-07-01", ttype="Loan")]
        result = filter_summer_transfers(entries, TARGET_IDS, SOURCE_IDS,
                                         2024, "bl1", "pl")
        assert result[0]["transfer_type"] == "Loan"

    def test_broken_date_excluded(self):
        entries = [raw_transfer(1, "A", 200, 100, "kaputt")]
        result = filter_summer_transfers(entries, TARGET_IDS, SOURCE_IDS,
                                         2024, "bl1", "pl")
        assert result == []

    def test_missing_team_ids_excluded(self):
        entries = [{
            "player": {"id": 1, "name": "A"},
            "transfers": [{"date": "2024-07-01", "type": "Free",
                           "teams": {"in": {}, "out": {}}}],
        }]
        result = filter_summer_transfers(entries, TARGET_IDS, SOURCE_IDS,
                                         2024, "bl1", "pl")
        assert result == []

    def test_empty_input(self):
        assert filter_summer_transfers([], TARGET_IDS, SOURCE_IDS,
                                       2024, "bl1", "pl") == []
        assert filter_summer_transfers(None, TARGET_IDS, SOURCE_IDS,
                                       2024, "bl1", "pl") == []

    def test_date_helpers(self):
        assert parse_transfer_date("2024-07-01").month == 7
        assert parse_transfer_date(None) is None
        assert parse_transfer_date("nope") is None
        assert is_summer_transfer(parse_transfer_date("2024-06-01"), 2024)
        assert is_summer_transfer(parse_transfer_date("2024-08-31"), 2024)
        assert not is_summer_transfer(parse_transfer_date("2024-09-01"), 2024)
        assert not is_summer_transfer(None, 2024)


# ---------------------------------------------------------------------------
# Statistik-Normalisierung
# ---------------------------------------------------------------------------

def stats_entry(league_id, minutes, goals=0, assists=None,
                rating=None, position="Midfielder"):
    return {
        "league": {"id": league_id},
        "games": {"minutes": minutes, "appearences": 10,
                  "rating": rating, "position": position},
        "goals": {"total": goals, "assists": assists},
    }


class TestStatsNormalization:

    TARGET_LEAGUE = 39  # Premier League bei API-Sports

    def test_no_target_league_entry_means_no_data(self):
        result = normalize_player_statistics(
            [stats_entry(78, 900)], self.TARGET_LEAGUE)
        assert result["data_available"] is False
        assert result["minutes"] is None

    def test_multiple_statistics_objects_summed(self):
        # Spieler wechselt innerhalb der Saison den Verein in der Zielliga:
        # zwei Eintraege derselben Liga werden summiert.
        entries = [
            stats_entry(39, 600, goals=3, assists=2, rating="7.10"),
            stats_entry(39, 400, goals=1, assists=1, rating="6.80"),
            stats_entry(2, 300, goals=5),  # Champions League ignorieren
        ]
        result = normalize_player_statistics(entries, self.TARGET_LEAGUE)
        assert result["data_available"] is True
        assert result["minutes"] == 1000
        assert result["goals"] == 4
        assert result["assists"] == 3
        assert result["scorer_points"] == 7
        # Rating minutengewichtet: (7.10*600 + 6.80*400) / 1000 = 6.98
        assert result["rating"] == pytest.approx(6.98, abs=0.01)

    def test_rating_string_converted(self):
        result = normalize_player_statistics(
            [stats_entry(39, 500, rating="7.25")], self.TARGET_LEAGUE)
        assert result["rating"] == pytest.approx(7.25)

    def test_missing_rating_is_none(self):
        result = normalize_player_statistics(
            [stats_entry(39, 500, rating=None)], self.TARGET_LEAGUE)
        assert result["rating"] is None

    def test_missing_assists_stay_unknown_not_zero(self):
        result = normalize_player_statistics(
            [stats_entry(39, 500, goals=2, assists=None)], self.TARGET_LEAGUE)
        assert result["assists"] is None
        assert result["scorer_points"] is None

    def test_unknown_position_is_none(self):
        result = normalize_player_statistics(
            [stats_entry(39, 500, position="Weirdo")], self.TARGET_LEAGUE)
        assert result["position"] is None

    def test_empty_input(self):
        result = normalize_player_statistics([], self.TARGET_LEAGUE)
        assert result["data_available"] is False
        result = normalize_player_statistics(None, self.TARGET_LEAGUE)
        assert result["data_available"] is False


# ---------------------------------------------------------------------------
# Gruppenbildung und Vergleich
# ---------------------------------------------------------------------------

class TestComparisonLogic:

    def test_split_players_thresholds(self):
        players = [
            player(1, 500),                      # qualifiziert
            player(2, MIN_QUALIFYING_MINUTES),   # exakt 300: qualifiziert
            player(3, 299),                      # zu wenig
            player(4, 0, available=False),       # keine Daten
        ]
        qualified, low, missing = split_players(players)
        assert [p["player_id"] for p in qualified] == [1, 2]
        assert [p["player_id"] for p in low] == [3]
        assert [p["player_id"] for p in missing] == [4]

    def test_group_averages(self):
        players = [
            player(1, 1000, goals=4, assists=2, rating=7.0),
            player(2, 500, goals=2, assists=0, rating=6.5),
            player(3, 100, goals=9, assists=9, rating=9.9),  # nicht qualifiziert
        ]
        group = build_group("bl1", "Bundesliga", players)
        assert group["sample"]["transfers_total"] == 3
        assert group["sample"]["qualified"] == 2
        assert group["sample"]["low_minutes"] == 1
        assert group["averages"]["minutes"] == 750.0
        assert group["averages"]["goals"] == 3.0
        assert group["averages"]["assists"] == 1.0
        assert group["averages"]["rating"] == pytest.approx(6.75)

    def test_none_values_do_not_distort_averages(self):
        players = [
            player(1, 600, goals=2, assists=None, rating=None),
            player(2, 600, goals=2, assists=4, rating=7.0),
        ]
        # scorer_points von Spieler 1 ist None
        players[0]["scorer_points"] = None
        group = build_group("bl1", "Bundesliga", players)
        # Assists-Schnitt nur aus bekannten Werten
        assert group["averages"]["assists"] == 4.0
        assert group["averages"]["rating"] == pytest.approx(7.0)
        assert group["unknown_counts"]["assists"] == 1

    def test_all_values_unknown_gives_none_average(self):
        players = [player(1, 600, assists=None, rating=None)]
        players[0]["scorer_points"] = None
        group = build_group("bl1", "Bundesliga", players)
        assert group["averages"]["assists"] is None
        assert group["averages"]["rating"] is None

    def test_empty_group(self):
        group = build_group("bl1", "Bundesliga", [])
        assert group["sample"]["transfers_total"] == 0
        assert group["averages"]["minutes"] is None

    def test_position_groups(self):
        players = [
            player(1, 600, position="Attacker"),
            player(2, 600, position="Attacker"),
            player(3, 600, position="Goalkeeper"),
            player(4, 600, position=None),
        ]
        group = build_group("bl1", "Bundesliga", players)
        assert group["positions"]["Attacker"]["count"] == 2
        assert group["positions"]["Goalkeeper"]["count"] == 1
        assert group["positions"]["Unknown"]["count"] == 1

    def test_metric_winners_no_overall_winner(self):
        group_a = build_group("bl1", "Bundesliga",
                              [player(1, 800, goals=5, assists=1, rating=7.5)])
        group_b = build_group("pd", "La Liga",
                              [player(2, 900, goals=2, assists=3, rating=7.0)])
        winners = compare_metric_winners(group_a, group_b)
        assert winners["minutes"] == "b"
        assert winners["goals"] == "a"
        assert winners["assists"] == "b"
        assert winners["rating"] == "a"
        # Es darf keinen kuenstlichen Gesamtsieger geben
        assert "overall" not in winners
        assert "winner" not in winners

    def test_metric_winner_none_when_missing_or_equal(self):
        group_a = build_group("bl1", "Bundesliga",
                              [player(1, 600, rating=None)])
        group_b = build_group("pd", "La Liga",
                              [player(2, 600, rating=7.0)])
        winners = compare_metric_winners(group_a, group_b)
        assert winners["rating"] is None      # eine Seite ohne Wert
        assert winners["minutes"] is None     # gleichauf

    def test_full_result_structure_and_warnings(self):
        result = build_comparison_result(
            "bl1", "pd", "pl", 2024,
            "Bundesliga", "La Liga", "Premier League",
            [player(1, 600)],   # kleine Gruppe -> Hinweis
            [],                 # keine Transfers -> Hinweis
        )
        assert result["query"]["season_label"] == "2024 \u2192 2025"
        assert result["query"]["minimum_minutes"] == MIN_QUALIFYING_MINUTES
        assert result["group_a"]["league"] == "bl1"
        assert any("kleinen" in w for w in result["warnings"])
        assert any("keine passenden Sommertransfers" in w for w in result["warnings"])

    def test_missing_data_warning(self):
        result = build_comparison_result(
            "bl1", "pd", "pl", 2024,
            "Bundesliga", "La Liga", "Premier League",
            [player(i, 600) for i in range(1, 7)] + [player(99, 0, available=False)],
            [player(i, 600) for i in range(10, 16)],
        )
        assert any("keine vollstaendigen Leistungsdaten" in w
                   for w in result["warnings"])
