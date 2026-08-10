"""
Tests fuer die persistente Champions-League-Historie.

Warum das noetig war
--------------------
data/historical/ enthielt ausschliesslich Ligadateien. Jede CL-Staerke
wurde bei Bedarf live nachgeladen. Fuer Backtesting ist das untauglich:
Ergebnisse waeren nicht reproduzierbar und jeder Trainingslauf wuerde
erneut die API belasten.

Die CL braucht dabei ein Feld, das Ligen nicht brauchen: die Stage.
In der Champions League kollidieren Spieltagsnummern ueber Stages hinweg
(matchday=1 gibt es in der Ligaphase UND im Achtelfinale). Ohne Stage
sind die Daten nicht sauber trennbar.

Diese Tests sichern ausserdem ab, dass die bestehende Ligahistorie durch
die Erweiterung nicht ihr Format aendert.
"""

import json
import os

import pytest

from src.data import historical_loader as hl


# ---------------------------------------------------------------------------
# Rohdaten-Fixtures im football-data.org-Format
# ---------------------------------------------------------------------------

def _raw_cl_match(match_id, stage, matchday, date, home, away, hg, ag,
                  status="FINISHED"):
    return {
        "id": match_id,
        "stage": stage,
        "matchday": matchday,
        "status": status,
        "utcDate": f"{date}T21:00:00Z",
        "homeTeam": {"id": home, "name": f"Club {home}", "shortName": f"C{home}",
                     "tla": f"C{home}", "crest": None},
        "awayTeam": {"id": away, "name": f"Club {away}", "shortName": f"C{away}",
                     "tla": f"C{away}", "crest": None},
        "score": {"fullTime": {"home": hg, "away": ag}},
    }


RAW_CL = [
    _raw_cl_match(1, "LEAGUE_STAGE", 1, "2024-09-17", 5, 61, 3, 1),
    _raw_cl_match(2, "LEAGUE_STAGE", 1, "2024-09-18", 66, 78, 0, 0),
    _raw_cl_match(3, "LEAGUE_STAGE", 8, "2025-01-29", 61, 5, 2, 2),
    _raw_cl_match(4, "LAST_16", 1, "2025-03-04", 5, 66, 1, 0),
    _raw_cl_match(5, "FINAL", 1, "2025-05-31", 5, 61, 2, 0),
]


@pytest.fixture
def historical_dir(tmp_path, monkeypatch):
    """Isoliert alle Schreibvorgaenge, damit data/historical unberuehrt bleibt."""
    monkeypatch.setattr(hl, "HISTORICAL_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def fake_api(monkeypatch):
    """Ersetzt den HTTP-Zugriff. Kein Test darf ins Netz gehen."""
    calls = []

    def fake_get_json(path, params=None):
        calls.append((path, dict(params or {})))
        if "/CL/" in path:
            return {"matches": list(RAW_CL)}
        return {"matches": []}

    monkeypatch.setattr(hl, "_get_json", fake_get_json)
    return calls


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_cl_is_not_treated_as_a_league():
    """
    LEAGUE_CODES steuert Ligasimulation und Aufsteiger-Erkennung. Die CL
    hat dort nichts verloren, sonst wuerde sie als Liga simuliert.
    """
    assert "cl" not in hl.LEAGUE_CODES
    assert "CL" not in hl.LEAGUE_CODES.values()
    assert hl.CUP_CODES["cl"] == "CL"
    assert "CL" in hl.STAGED_COMPETITIONS


def test_cl_season_carries_stage_match_id_and_status(fake_api):
    payload = hl.fetch_season("CL", 2024)

    assert payload["meta"]["api_code"] == "CL"
    assert payload["meta"]["season"] == 2024
    assert payload["meta"]["source"] == "football-data.org"
    assert payload["meta"]["competition_type"] == "cup"
    assert payload["meta"]["fetched_at"]

    for match in payload["matches"]:
        assert "stage" in match
        assert "match_id" in match
        assert "status" in match
        assert match["home_id"] is not None
        assert match["away_id"] is not None

    stages = {m["stage"] for m in payload["matches"]}
    assert stages == {"LEAGUE_STAGE", "LAST_16", "FINAL"}


def test_stage_summary_is_derived_from_data_not_assumed(fake_api):
    """
    Das UEFA-Format hat sich 2024/25 geaendert. Die Stage-Uebersicht muss
    deshalb aus den tatsaechlichen Daten entstehen, nicht aus einer
    hartkodierten Erwartung.
    """
    payload = hl.fetch_season("CL", 2024)

    assert payload["meta"]["stages"] == {
        "FINAL": 1,
        "LAST_16": 1,
        "LEAGUE_STAGE": 3,
    }


def test_matches_are_sorted_chronologically(fake_api):
    payload = hl.fetch_season("CL", 2024)
    dates = [m["date"] for m in payload["matches"]]
    assert dates == sorted(dates)


def test_no_invented_data_for_missing_fields(monkeypatch):
    """
    Fehlende Felder werden NICHT geraten. Liefert die API keine Stage,
    steht dort None - keine Approximation.
    """
    incomplete = [{
        "id": 99,
        "matchday": None,
        "status": "FINISHED",
        "utcDate": "2024-09-17T21:00:00Z",
        "homeTeam": {"id": 5, "name": "Club 5"},
        "awayTeam": {"id": 61, "name": "Club 61"},
        "score": {"fullTime": {"home": 1, "away": 0}},
    }]
    monkeypatch.setattr(hl, "_get_json", lambda *a, **k: {"matches": incomplete})

    payload = hl.fetch_season("CL", 2024)

    assert len(payload["matches"]) == 1
    assert payload["matches"][0]["stage"] is None
    assert payload["matches"][0]["matchday"] is None
    assert payload["meta"]["stages"] == {}


def test_matches_without_result_or_team_id_are_skipped(monkeypatch):
    raw = [
        _raw_cl_match(1, "LEAGUE_STAGE", 1, "2024-09-17", 5, 61, 3, 1),
        # Abgesagt: kein Ergebnis
        _raw_cl_match(2, "LEAGUE_STAGE", 1, "2024-09-17", 66, 78, None, None),
        # Kaputter Datensatz: keine Team-ID
        {"id": 3, "stage": "LEAGUE_STAGE", "matchday": 1, "status": "FINISHED",
         "utcDate": "2024-09-17T21:00:00Z",
         "homeTeam": {}, "awayTeam": {"id": 78},
         "score": {"fullTime": {"home": 1, "away": 1}}},
    ]
    monkeypatch.setattr(hl, "_get_json", lambda *a, **k: {"matches": raw})

    payload = hl.fetch_season("CL", 2024)

    assert payload["meta"]["matches"] == 1
    assert payload["matches"][0]["match_id"] == 1


def test_empty_api_response_yields_empty_but_valid_payload(monkeypatch):
    """Eine noch nicht begonnene Saison darf keinen Absturz erzeugen."""
    monkeypatch.setattr(hl, "_get_json", lambda *a, **k: {"matches": []})

    payload = hl.fetch_season("CL", 2026)

    assert payload["meta"]["matches"] == 0
    assert payload["meta"]["teams"] == 0
    assert payload["meta"]["stages"] == {}
    assert payload["matches"] == []
    assert payload["teams"] == {}


# ---------------------------------------------------------------------------
# Speichern und erneut laden
# ---------------------------------------------------------------------------

def test_save_and_reload_roundtrip(historical_dir, fake_api):
    payload = hl.fetch_season("CL", 2024)
    path = hl.save_season("CL", 2024, payload)

    assert os.path.basename(path) == "CL_2024.json"
    assert os.path.exists(path)

    reloaded = hl.load_cl_season(2024)

    assert reloaded is not None
    assert reloaded["meta"]["matches"] == payload["meta"]["matches"]
    assert len(reloaded["matches"]) == len(payload["matches"])
    # Team-IDs muessen beim Lesen wieder numerisch sein, sonst passen sie
    # nicht zu den IDs aus der laufenden API-Abfrage.
    assert all(isinstance(tid, int) for tid in reloaded["teams"])


def test_stored_file_is_valid_json_with_expected_top_level_keys(historical_dir, fake_api):
    hl.save_season("CL", 2024, hl.fetch_season("CL", 2024))

    with open(os.path.join(str(historical_dir), "CL_2024.json"), encoding="utf-8") as fh:
        raw = json.load(fh)

    assert set(raw.keys()) == {"meta", "teams", "matches"}


def test_load_missing_season_returns_none(historical_dir):
    assert hl.load_cl_season(1999) is None
    assert hl.load_cl_matches(1999) == []


def test_load_corrupt_file_returns_none(historical_dir):
    path = os.path.join(str(historical_dir), "CL_2024.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{kaputt")

    assert hl.load_cl_season(2024) is None


# ---------------------------------------------------------------------------
# Stage-Filter - der eigentliche Mehrwert gegenueber der Live-API
# ---------------------------------------------------------------------------

def test_stage_filter_separates_league_phase_from_knockout(historical_dir, fake_api):
    hl.save_season("CL", 2024, hl.fetch_season("CL", 2024))

    league_phase = hl.load_cl_matches(2024, stage="LEAGUE_STAGE")
    last16 = hl.load_cl_matches(2024, stage="LAST_16")
    everything = hl.load_cl_matches(2024)

    assert len(league_phase) == 3
    assert len(last16) == 1
    assert len(everything) == 5
    assert all(m["stage"] == "LEAGUE_STAGE" for m in league_phase)


def test_matchday_one_exists_in_two_different_stages(historical_dir, fake_api):
    """
    Der konkrete Grund, warum die Stage mitgespeichert werden muss:
    matchday=1 kommt in Ligaphase und Achtelfinale vor.
    """
    hl.save_season("CL", 2024, hl.fetch_season("CL", 2024))

    matchday_one = [m for m in hl.load_cl_matches(2024) if m["matchday"] == 1]
    stages = {m["stage"] for m in matchday_one}

    assert len(stages) > 1, "Ohne Stage waeren diese Spiele nicht trennbar"


def test_available_cl_seasons_lists_stored_files(historical_dir, fake_api):
    hl.save_season("CL", 2024, hl.fetch_season("CL", 2024))
    hl.save_season("CL", 2023, hl.fetch_season("CL", 2023))

    assert hl.available_cl_seasons() == [2024, 2023]


# ---------------------------------------------------------------------------
# Keine Regression der Ligahistorie
# ---------------------------------------------------------------------------

def test_league_matches_keep_their_original_shape(monkeypatch):
    """
    Die Ligadateien duerfen ihr Match-Format nicht aendern: Stage,
    match_id und status gehoeren dort NICHT hinein.
    """
    raw = [{
        "id": 1, "matchday": 1, "status": "FINISHED",
        "utcDate": "2024-08-23T18:30:00Z",
        "homeTeam": {"id": 5, "name": "Bayern"},
        "awayTeam": {"id": 721, "name": "Leipzig"},
        "score": {"fullTime": {"home": 3, "away": 2}},
    }]
    monkeypatch.setattr(hl, "_get_json", lambda *a, **k: {"matches": raw})

    payload = hl.fetch_season("BL1", 2024)

    assert set(payload["matches"][0].keys()) == {
        "matchday", "date", "home_id", "away_id", "home_goals", "away_goals",
    }
    assert payload["meta"]["competition_type"] == "league"
    assert "stages" not in payload["meta"]


def test_real_domestic_files_still_load(monkeypatch):
    """
    Die echten, im Repo liegenden Ligadateien muessen unveraendert
    lesbar bleiben - sie wurden vor dieser Erweiterung geschrieben.
    """
    payload = hl.load_season("BL1", 2024)
    if payload is None:
        pytest.skip("data/historical/BL1_2024.json liegt nicht vor")

    assert payload["matches"]
    assert all(isinstance(tid, int) for tid in payload["teams"])
    # Alte Dateien kennen competition_type nicht - das darf nicht stoeren.
    assert "matches" in payload["meta"]


def test_refresh_cl_writes_expected_filename(historical_dir, fake_api):
    results = hl.refresh_cl(seasons=[2024], force=True, verbose=False)

    assert len(results) == 1
    assert results[0]["status"] == "geladen"
    assert results[0]["api_code"] == "CL"
    assert os.path.exists(os.path.join(str(historical_dir), "CL_2024.json"))


def test_refresh_cl_skips_existing_without_force(historical_dir, fake_api):
    hl.refresh_cl(seasons=[2024], force=True, verbose=False)
    calls_before = len(fake_api)

    results = hl.refresh_cl(seasons=[2024], force=False, verbose=False)

    assert results[0]["status"] == "vorhanden"
    assert len(fake_api) == calls_before, "Kein zweiter API-Request noetig"


def test_cl_coverage_report_shape(historical_dir, fake_api):
    hl.refresh_cl(seasons=[2024], force=True, verbose=False)

    rows = hl.cl_coverage_report()
    found = {r["season"]: r for r in rows}

    assert found[2024]["available"] is True
    assert found[2024]["stages"]
    assert all(r["competition"] == "cl" for r in rows)
