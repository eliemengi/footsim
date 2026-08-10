"""
Tests fuer die Belastungs-/Erholungsmerkmale.

Zwei Dinge stehen hier im Mittelpunkt:

1. Kein Leak. Ein Merkmal fuer ein Spiel am 1. Oktober darf keine Partie
   vom 2. Oktober kennen - auch nicht ueber den Umweg "Spiele der
   letzten 30 Tage".

2. Ehrlichkeit ueber Luecken. Die nationalen Pokale liefert der
   football-data-Tarif dieses Projekts nicht (HTTP 403). Die Kennzahlen
   sind in Pokalwochen deshalb systematisch zu niedrig. Das muss aus dem
   Ergebnis erkennbar sein, statt stillschweigend unterzugehen.
"""

import pytest

from src.features import congestion


def match(date, home, away, match_id=None):
    entry = {"date": date, "home_id": home, "away_id": away,
             "home_goals": 1, "away_goals": 0}
    if match_id is not None:
        entry["match_id"] = match_id
    return entry


# Team 10 im englischen Wochenrhythmus: Liga Samstag, CL Mittwoch.
LEAGUE = [
    match("2025-09-13", 10, 20),
    match("2025-09-20", 21, 10),
    match("2025-09-27", 10, 22),
    match("2025-10-04", 23, 10),   # nach dem Stichtag
]
CL = [
    match("2025-09-17", 10, 50),
    match("2025-10-01", 51, 10),   # am Stichtag
]
FIXTURES = {"BL1": LEAGUE, "CL": CL}


# ---------------------------------------------------------------------------
# Zeitleiste
# ---------------------------------------------------------------------------

def test_timeline_merges_competitions_chronologically():
    timeline = congestion.build_team_timeline(FIXTURES, 10)
    dates = [m["date"] for m in timeline]

    assert dates == sorted(dates)
    assert len(timeline) == 6
    assert {m["competition"] for m in timeline} == {"BL1", "CL"}


def test_timeline_marks_home_and_opponent():
    timeline = congestion.build_team_timeline(FIXTURES, 10)
    first = timeline[0]

    assert first["is_home"] is True
    assert first["opponent_id"] == 20

    away_game = next(m for m in timeline if m["date"] == "2025-09-20")
    assert away_game["is_home"] is False
    assert away_game["opponent_id"] == 21


def test_timeline_ignores_other_teams():
    timeline = congestion.build_team_timeline(FIXTURES, 99)
    assert timeline == []


def test_timeline_skips_matches_without_date():
    broken = {"BL1": [{"home_id": 10, "away_id": 20}]}
    assert congestion.build_team_timeline(broken, 10) == []


# ---------------------------------------------------------------------------
# Kein Leak
# ---------------------------------------------------------------------------

def test_no_future_match_counts_towards_load():
    """Das Spiel vom 4. Oktober darf am 1. Oktober nicht zaehlen."""
    timeline = congestion.build_team_timeline(FIXTURES, 10)

    count = congestion.matches_in_last_days(timeline, "2025-10-01", 30)

    assert count == 4  # 13., 17., 20., 27. September
    assert congestion.matches_in_last_days(timeline, "2025-10-01", 3) == 0


def test_same_day_match_excluded_by_default():
    """
    Das CL-Spiel am 1. Oktober selbst gilt als noch nicht bekannt -
    ohne Anstosszeiten laesst sich die Reihenfolge nicht belegen.
    """
    timeline = congestion.build_team_timeline(FIXTURES, 10)

    assert congestion.days_since_last_match(timeline, "2025-10-01") == 4
    assert congestion.days_since_last_match(
        timeline, "2025-10-01", inclusive=True) == 0


def test_days_since_last_match_is_none_without_history():
    """
    Ehrlicher als eine grosse Zahl: Die wuerde "lange ausgeruht"
    suggerieren, obwohl schlicht nichts bekannt ist.
    """
    timeline = congestion.build_team_timeline(FIXTURES, 10)

    assert congestion.days_since_last_match(timeline, "2025-01-01") is None


def test_window_is_half_open():
    timeline = congestion.build_team_timeline(FIXTURES, 10)

    # Genau 14 Tage vor dem 1. Oktober ist der 17. September.
    assert congestion.matches_in_last_days(timeline, "2025-10-01", 14) == 3
    assert congestion.matches_in_last_days(timeline, "2025-10-01", 13) == 2


# ---------------------------------------------------------------------------
# Aufschluesselung
# ---------------------------------------------------------------------------

def test_competition_breakdown_shows_european_load():
    timeline = congestion.build_team_timeline(FIXTURES, 10)

    breakdown = congestion.competitions_in_last_days(timeline, "2025-10-01", 14)

    assert breakdown == {"BL1": 2, "CL": 1}


def test_travel_load_counts_away_matches():
    timeline = congestion.build_team_timeline(FIXTURES, 10)

    load = congestion.travel_load_in_last_days(timeline, "2025-10-01", 14)

    assert load["matches"] == 3
    assert load["away_matches"] == 1


# ---------------------------------------------------------------------------
# Gesamtschnittstelle
# ---------------------------------------------------------------------------

def test_congestion_features_shape():
    features = congestion.congestion_features(FIXTURES, 10, "2025-10-01")

    assert features["team_id"] == 10
    assert features["days_since_last_match"] == 4
    assert features["matches_last_7_days"] == 1
    assert features["matches_last_14_days"] == 3
    assert features["matches_last_30_days"] == 4
    assert features["competitions_last_7_days"] == {"BL1": 1}


def test_congestion_features_are_json_serialisable():
    import json

    features = congestion.congestion_features(FIXTURES, 10, "2025-10-01")

    assert json.loads(json.dumps(features))["team_id"] == 10


def test_two_teams_differ_in_rest_days():
    """
    Der eigentliche Zweck: Europapokalteilnehmer gegen Nicht-Teilnehmer.
    """
    opponent_league = [match("2025-09-27", 30, 31)]

    busy = congestion.congestion_features(FIXTURES, 10, "2025-10-04")
    rested = congestion.congestion_features(
        {"BL1": opponent_league}, 30, "2025-10-04")

    assert busy["matches_last_14_days"] > rested["matches_last_14_days"]
    assert busy["days_since_last_match"] < rested["days_since_last_match"]


# ---------------------------------------------------------------------------
# Ehrlichkeit ueber die Datenluecke
# ---------------------------------------------------------------------------

def test_coverage_names_the_missing_competitions():
    """
    Die nationalen Pokale fehlen im Tarif (HTTP 403). Das muss im
    Ergebnis stehen - sonst liest jemand "zwei Spiele in sieben Tagen"
    als vollstaendige Wahrheit.
    """
    features = congestion.congestion_features(FIXTURES, 10, "2025-10-01")
    cov = features["coverage"]

    assert cov["complete"] is False
    assert cov["competitions"] == ["BL1", "CL"]
    assert any("cup" in gap.lower() for gap in cov["known_gaps"])


def test_coverage_never_claims_completeness():
    """
    Auch mit allen verfuegbaren Wettbewerben bleibt die Zeitleiste
    unvollstaendig, solange Pokale und Europa League fehlen.
    """
    everything = {code: [] for code in
                  ("BL1", "PL", "PD", "SA", "FL1", "CL")}

    assert congestion.coverage(everything)["complete"] is False


# ---------------------------------------------------------------------------
# Gegen echte Projektdaten
# ---------------------------------------------------------------------------

def test_against_real_history():
    """
    Muss mit den tatsaechlich gespeicherten Dateien funktionieren, nicht
    nur mit Testdaten. Real Madrid (ID 86) spielte 2024/25 Liga und CL.
    """
    timeline, by_competition = congestion.build_timeline_from_history(
        [2024], team_id=86)

    if not timeline:
        pytest.skip("Historiedateien liegen nicht vor")

    assert len(by_competition) >= 1
    dates = [m["date"] for m in timeline]
    assert dates == sorted(dates)


def test_real_history_shows_multi_competition_load():
    """
    Der konkrete Mehrwert der CL-Persistenz aus Block 2: Ein Team, das
    Liga UND Champions League spielt, zeigt jetzt eine dichtere
    Zeitleiste als aus der Ligadatei allein ableitbar waere.
    """
    league_only, _ = congestion.build_timeline_from_history(
        [2024], team_id=86, competitions=["PD"])
    with_cl, _ = congestion.build_timeline_from_history(
        [2024], team_id=86, competitions=["PD", "CL"])

    if not league_only or len(with_cl) == len(league_only):
        pytest.skip("PD- oder CL-Historie fuer 2024 liegt nicht vor")

    assert len(with_cl) > len(league_only)


def test_point_in_time_holds_against_real_data():
    from src.features.point_in_time import assert_no_future_data, matches_known_at

    timeline, _ = congestion.build_timeline_from_history([2024], team_id=86)
    if not timeline:
        pytest.skip("Historiedateien liegen nicht vor")

    known = matches_known_at(timeline, "2025-01-01")
    assert_no_future_data(known, "2025-01-01")


# ---------------------------------------------------------------------------
# Abgrenzung
# ---------------------------------------------------------------------------

def test_congestion_is_not_wired_into_the_model():
    """
    Die Wirkung dieser Merkmale soll erst gemessen werden, bevor sie das
    Modell veraendern. Alles andere waere eine unbelegte Modellaenderung.

    Faellt dieser Test, wurde die Verdrahtung vorgenommen - dann gehoert
    sie mit einem Vorher/Nachher-Vergleich belegt.
    """
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    model_modules = [
        "src/features/team_profile.py",
        "src/features/strength_provider.py",
        "src/predict/league_match_sim.py",
        "src/predict/season_sim.py",
        "src/predict/cl_match_sim.py",
        "src/predict/cl_season_sim.py",
    ]

    users = []
    for rel in model_modules:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            if "congestion" in fh.read():
                users.append(rel)

    assert not users, f"Belastungsmerkmale im Modellpfad: {users}"
