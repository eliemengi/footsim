"""Die Fallback-Kette liefert IMMER ein Profil, kein Spiel verschwindet (Audit §3, §9)."""
from src.features import fallback_strengths as fs
from src.predict.season_sim import simulate_season
from src.predict.fixture_plan import partition_season_matches
from tests.conftest import build_raw_season, standings_from

LEGACY_KEYS = {"avg_goals_scored", "avg_goals_conceded", "points_per_game",
               "winrate", "matches_used"}


def test_ensure_team_strengths_kennt_alle_stufen(test_league):
    ids = [1, 2, 3, 4, 5, 6]
    names = {i: f"Klub {i}" for i in ids}
    test_league["write"]("TESTL", 2025, ids, names)
    test_league["write"]("TESTL", 2024, [1, 2, 3, 4, 5, 9], names | {9: "Klub 9"})
    fs._reset_cache()

    strengths = {"Schon Da": {"avg_goals_scored": 1.5, "avg_goals_conceded": 1.1,
                              "points_per_game": 1.8, "winrate": 0.5, "matches_used": 5}}
    strengths, info = fs.ensure_team_strengths(
        strengths, ["Schon Da", "Klub 3", "Voellig Unbekannt FC"])

    assert info["Schon Da"]["resolved_by"] == "team_matches"
    assert info["Klub 3"]["resolved_by"] == "historical_profile"
    assert info["Voellig Unbekannt FC"]["resolved_by"] in ("promoted_profile", "neutral")

    for name in ("Schon Da", "Klub 3", "Voellig Unbekannt FC"):
        assert strengths[name] is not None
        assert LEGACY_KEYS.issubset(strengths[name].keys())


def test_aufsteiger_spiel_wird_in_der_saisonsimulation_nie_uebersprungen(test_league):
    ids_hist = [1, 2, 3, 4, 5, 6]
    names = {i: f"Klub {i}" for i in range(1, 9)}
    test_league["write"]("TESTL", 2025, ids_hist, names)
    test_league["write"]("TESTL", 2024, ids_hist, names)

    current = [1, 2, 3, 4, 5, 8]                 # 8 = Aufsteiger ohne Historie
    raw = build_raw_season(current, names={i: names[i] for i in current})
    plan = partition_season_matches(raw)
    table = standings_from(current, names={i: names[i] for i in current})

    result = simulate_season("testl", table, plan["remaining"],
                             simulations=200, seed=7)

    audit = result["fixture_audit"]
    assert audit["fixtures_received"] == 30      # 6 Teams -> 6*5 Partien
    assert audit["fixtures_prepared"] == 30
    assert audit["fixtures_unknown_team"] == 0

    aufsteiger = next(e for e in result["entries"] if e["team_id"] == 8)
    assert aufsteiger["is_promoted"] is True
    assert aufsteiger["games_remaining"] == 10
    assert [e["rank"] for e in result["entries"]] == list(range(1, 7))
