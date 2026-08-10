"""
Tests fuer den Point-in-Time-Schnitt.

Der Kern jedes Tests hier ist dieselbe Frage: Kann ein Feature fuer ein
Spiel vom Tag X etwas sehen, das erst nach Tag X passiert ist?

Wenn diese Datei gruen ist, ist die Antwort nein - und zwar auch fuer die
unangenehmen Faelle: gleicher Tag, fehlendes Datum, unsortierte Eingabe,
gemischte Datumsformate aus historischer Datei und Live-API.
"""

import pytest

from src.features import point_in_time as pit
from src.features.point_in_time import PointInTime


# ---------------------------------------------------------------------------
# Testdaten: bewusst beide Formate, die im Projekt vorkommen
# ---------------------------------------------------------------------------

def hist_match(date, home, away, hg=1, ag=0, match_id=None, matchday=None):
    """Format der historischen Dateien: nur Datum, keine Uhrzeit."""
    entry = {"date": date, "home_id": home, "away_id": away,
             "home_goals": hg, "away_goals": ag}
    if match_id is not None:
        entry["match_id"] = match_id
    if matchday is not None:
        entry["matchday"] = matchday
    return entry


def live_match(utc_date, home, away, hg=1, ag=0, match_id=None):
    """Format der Live-API: vollstaendiger Zeitstempel."""
    entry = {"utc_date": utc_date, "home_id": home, "away_id": away,
             "home_goals": hg, "away_goals": ag}
    if match_id is not None:
        entry["id"] = match_id
    return entry


SEASON = [
    hist_match("2025-09-13", 1, 2, match_id=101),
    hist_match("2025-09-20", 3, 4, match_id=102),
    hist_match("2025-09-27", 1, 3, match_id=103),
    hist_match("2025-10-01", 2, 4, match_id=104),   # Zielspieltag
    hist_match("2025-10-02", 1, 4, match_id=105),   # danach
    hist_match("2025-10-18", 2, 3, match_id=106),   # danach
]


# ---------------------------------------------------------------------------
# Die vom Auftrag geforderte Kernzusicherung
# ---------------------------------------------------------------------------

def test_no_future_match_leaks_into_features():
    """
    Wird ein Spiel am 2025-10-01 betrachtet, duerfen Spiele vom
    2025-10-02 oder spaeter NICHT auftauchen.
    """
    known = pit.matches_known_at(SEASON, "2025-10-01")
    dates = [m["date"] for m in known]

    assert dates == ["2025-09-13", "2025-09-20", "2025-09-27"]
    assert "2025-10-02" not in dates
    assert "2025-10-18" not in dates


def test_same_day_is_excluded_by_default():
    """
    Ohne Uhrzeit laesst sich nicht belegen, dass ein Spiel desselben
    Tages vorher stattfand. Es wird deshalb ausgeschlossen.
    """
    known = pit.matches_known_at(SEASON, "2025-10-01")

    assert all(m["date"] < "2025-10-01" for m in known)
    assert not any(m.get("match_id") == 104 for m in known)


def test_inclusive_mode_takes_the_cutoff_day():
    """Fuer 'Stand nach dem Spieltag'-Aussagen, nicht fuer Features."""
    known = pit.matches_known_at(SEASON, "2025-10-01", inclusive=True)

    assert any(m.get("match_id") == 104 for m in known)
    assert not any(m.get("match_id") == 105 for m in known)


def test_kickoff_times_are_used_when_both_sides_have_them():
    """
    Liegen auf beiden Seiten Uhrzeiten vor, wird der Schnitt genauer:
    Das Nachmittagsspiel ist fuer das Abendspiel bekannt.
    """
    afternoon = live_match("2025-10-01T13:30:00Z", 5, 6)
    evening = live_match("2025-10-01T18:30:00Z", 7, 8)

    known = pit.matches_known_at([afternoon, evening], "2025-10-01T18:30:00Z")

    assert known == [afternoon]


def test_match_without_date_is_never_assumed_known():
    """
    Ein Datensatz, dessen Zeitpunkt sich nicht pruefen laesst, darf nicht
    stillschweigend in die Vergangenheit gerechnet werden.
    """
    broken = {"home_id": 1, "away_id": 2, "home_goals": 1, "away_goals": 1}

    assert pit.is_known_at(broken, "2030-01-01") is False
    assert pit.matches_known_at([broken], "2030-01-01") == []


def test_unsorted_input_is_handled():
    """Der Schnitt darf sich nicht auf eine sortierte Eingabe verlassen."""
    shuffled = [SEASON[4], SEASON[0], SEASON[5], SEASON[2], SEASON[1]]

    known = pit.matches_known_at(shuffled, "2025-10-01")
    dates = sorted(m["date"] for m in known)

    assert dates == ["2025-09-13", "2025-09-20", "2025-09-27"]


def test_mixed_source_formats_work_together():
    """
    Historische Datei (nur Datum) und Live-API (Zeitstempel) muessen sich
    im selben Aufruf mischen lassen - genau das passiert beim Aufbau
    saisonuebergreifender Trainingsdaten.
    """
    mixed = [
        hist_match("2025-09-13", 1, 2),
        live_match("2025-09-20T18:30:00Z", 3, 4),
        live_match("2025-10-05T18:30:00Z", 5, 6),
    ]

    known = pit.matches_known_at(mixed, "2025-10-01")

    assert len(known) == 2


# ---------------------------------------------------------------------------
# Datums-/Zeit-Extraktion
# ---------------------------------------------------------------------------

def test_match_date_reads_both_formats():
    assert pit.match_date(hist_match("2024-08-23", 1, 2)) == "2024-08-23"
    assert pit.match_date(live_match("2024-08-23T18:30:00Z", 1, 2)) == "2024-08-23"
    assert pit.match_date({"utcDate": "2024-08-23T18:30:00Z"}) == "2024-08-23"


def test_match_date_returns_none_for_unusable_input():
    assert pit.match_date({}) is None
    assert pit.match_date({"date": "kaputt"}) is None
    assert pit.match_date(None) is None
    assert pit.match_date("kein dict") is None


def test_match_time_only_where_the_source_has_one():
    assert pit.match_time(live_match("2024-08-23T18:30:00Z", 1, 2)) == "18:30:00"
    assert pit.match_time(hist_match("2024-08-23", 1, 2)) is None


def test_cutoff_accepts_date_objects():
    from datetime import date, datetime

    known = pit.matches_known_at(SEASON, date(2025, 10, 1))
    assert len(known) == 3

    known = pit.matches_known_at(SEASON, datetime(2025, 10, 1, 12, 0, 0))
    assert len(known) == 3


def test_invalid_cutoff_is_rejected_loudly():
    with pytest.raises(ValueError):
        pit.matches_known_at(SEASON, "2025")
    with pytest.raises(ValueError):
        pit.matches_known_at(SEASON, None)


# ---------------------------------------------------------------------------
# Schnitt relativ zu einem Zielspiel
# ---------------------------------------------------------------------------

def test_matches_for_fixture_excludes_the_fixture_itself():
    """
    Der unmittelbarste denkbare Leak: Ein Spiel sieht sein eigenes
    Ergebnis als Feature.
    """
    target = SEASON[3]  # 2025-10-01, match_id 104

    known = pit.matches_for_fixture(SEASON, target)

    assert all(m.get("match_id") != 104 for m in known)
    assert len(known) == 3


def test_matches_for_fixture_excludes_everything_after():
    target = SEASON[3]
    known = pit.matches_for_fixture(SEASON, target)

    assert all(m["date"] < "2025-10-01" for m in known)


def test_matches_for_fixture_uses_kickoff_when_available():
    fixtures = [
        live_match("2025-10-01T13:30:00Z", 5, 6, match_id=1),
        live_match("2025-10-01T18:30:00Z", 7, 8, match_id=2),
        live_match("2025-10-02T18:30:00Z", 9, 10, match_id=3),
    ]
    target = fixtures[1]

    known = pit.matches_for_fixture(fixtures, target)

    assert [m["id"] for m in known] == [1]


def test_fixture_without_date_is_rejected():
    with pytest.raises(ValueError):
        pit.matches_for_fixture(SEASON, {"home_id": 1, "away_id": 2})


# ---------------------------------------------------------------------------
# PointInTime
# ---------------------------------------------------------------------------

def test_point_in_time_slices_like_the_function():
    snapshot = PointInTime("2025-10-01", season=2025, competition="BL1")

    assert len(snapshot.slice(SEASON)) == 3


def test_point_in_time_for_fixture_is_strict():
    snapshot = PointInTime.for_fixture(SEASON[3], season=2025, competition="BL1")

    assert snapshot.inclusive is False
    assert snapshot.cutoff_date == "2025-10-01"
    assert len(snapshot.slice(SEASON)) == 3


def test_matches_through_date_reports_actual_basis():
    """
    Zeigt, worauf die Berechnung TATSAECHLICH beruhte - nicht nur, was
    erlaubt gewesen waere. Eine grosse Luecke zum Stichtag ist ein
    Hinweis auf fehlende Daten.
    """
    snapshot = PointInTime("2025-10-01")

    assert snapshot.matches_through_date(SEASON) == "2025-09-27"
    assert snapshot.matches_through_date([]) is None


def test_provenance_contains_what_a_later_audit_needs():
    snapshot = PointInTime("2025-10-01", season=2025, competition="BL1",
                           matchday=7)
    info = snapshot.provenance(SEASON)

    assert info["cutoff_date"] == "2025-10-01"
    assert info["season"] == 2025
    assert info["competition"] == "BL1"
    assert info["matchday"] == 7
    assert info["inclusive"] is False
    assert info["matches_used"] == 3
    assert info["matches_through_date"] == "2025-09-27"


def test_provenance_without_matches_omits_counts():
    info = PointInTime("2025-10-01").provenance()

    assert "matches_used" not in info
    assert info["cutoff_date"] == "2025-10-01"


# ---------------------------------------------------------------------------
# Zusicherung fuer Pipelines
# ---------------------------------------------------------------------------

def test_assert_no_future_data_passes_on_clean_slice():
    clean = pit.matches_known_at(SEASON, "2025-10-01")

    assert pit.assert_no_future_data(clean, "2025-10-01") is True


def test_assert_no_future_data_raises_on_leak():
    with pytest.raises(ValueError) as excinfo:
        pit.assert_no_future_data(SEASON, "2025-10-01")

    message = str(excinfo.value)
    assert "2025-10-02" in message or "2025-10-18" in message


def test_assert_no_future_data_tolerates_empty():
    assert pit.assert_no_future_data([], "2025-10-01") is True
    assert pit.assert_no_future_data(None, "2025-10-01") is True


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def test_team_matches_covers_home_and_away():
    result = pit.team_matches(SEASON, 1)

    assert len(result) == 3
    assert all(m["home_id"] == 1 or m["away_id"] == 1 for m in result)


def test_group_by_team_lists_a_match_for_both_sides():
    grouped = pit.group_by_team([hist_match("2025-09-13", 1, 2)])

    assert len(grouped[1]) == 1
    assert len(grouped[2]) == 1


def test_sort_chronologically_puts_undated_last():
    unsorted_matches = [
        hist_match("2025-10-01", 1, 2),
        {"home_id": 3, "away_id": 4},
        hist_match("2025-09-13", 5, 6),
    ]

    result = pit.sort_chronologically(unsorted_matches)

    assert pit.match_date(result[0]) == "2025-09-13"
    assert pit.match_date(result[1]) == "2025-10-01"
    assert pit.match_date(result[2]) is None


# ---------------------------------------------------------------------------
# Gegen echte Projektdaten
# ---------------------------------------------------------------------------

def test_works_against_real_historical_file():
    """
    Der Schnitt muss mit den tatsaechlich gespeicherten Dateien
    funktionieren, nicht nur mit Testdaten.
    """
    from src.data.historical_loader import load_season

    payload = load_season("BL1", 2024)
    if payload is None:
        pytest.skip("data/historical/BL1_2024.json liegt nicht vor")

    matches = payload["matches"]
    known = pit.matches_known_at(matches, "2024-12-31")

    assert known, "Erste Saisonhaelfte muss Spiele enthalten"
    assert len(known) < len(matches), "Rueckrunde darf nicht enthalten sein"
    assert all(pit.match_date(m) < "2024-12-31" for m in known)


def test_works_against_real_cl_file():
    from src.data.historical_loader import load_cl_matches

    matches = load_cl_matches(2025, stage="LEAGUE_STAGE")
    if not matches:
        pytest.skip("data/historical/CL_2025.json liegt nicht vor")

    known = pit.matches_known_at(matches, "2025-11-01")

    assert known
    assert all(pit.match_date(m) < "2025-11-01" for m in known)
    pit.assert_no_future_data(known, "2025-11-01")


def test_live_simulation_path_does_not_slice_by_cutoff():
    """
    Bewusste Abgrenzung: Die SCHNITT-Funktionen sind fuer Backtesting und
    spaeteres Training. Der Live-Simulationspfad rechnet gegen den
    aktuellen Stand, wo die Frage "was war damals bekannt?" nicht
    auftritt. Ihn jetzt umzubauen waere Regressionsrisiko ohne heutigen
    Nutzen.

    Erlaubt sind die reinen Lesehelfer (match_date, match_time): Sie
    lesen nur ein Datum aus einem Spiel und treffen keine Entscheidung
    darueber, was ein Feature sehen darf. strength_provider benutzt
    match_date fuer die Provenienzangabe matches_through_date - das ist
    Berichterstattung ueber die verwendeten Daten, kein Schnitt.

    Faellt dieser Test, wurde echtes Point-in-Time-Slicing in den
    Live-Pfad gezogen. Das ist moeglich, aber dann gehoert die Umstellung
    ausdruecklich getestet - insbesondere darauf, dass sie keine
    bestehenden Simulationsergebnisse veraendert.
    """
    import os
    import re

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    live_modules = [
        "src/predict/league_match_sim.py",
        "src/predict/season_sim.py",
        "src/predict/cl_match_sim.py",
        "src/predict/cl_season_sim.py",
        "src/features/strength_provider.py",
    ]

    # Funktionen, die tatsaechlich einen Zeitschnitt vornehmen.
    slicing_api = (
        "matches_known_at", "matches_for_fixture", "is_known_at",
        "PointInTime", "assert_no_future_data",
    )

    offenders = []
    for rel in live_modules:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        for name in slicing_api:
            if re.search(rf"\b{name}\b", source):
                offenders.append(f"{rel} -> {name}")

    assert not offenders, (
        f"Live-Pfad nimmt einen Point-in-Time-Schnitt vor: {offenders}. "
        f"Das ist moeglich, muss aber bewusst getestet werden."
    )
