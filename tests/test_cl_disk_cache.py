"""
Tests fuer den worker-uebergreifenden Cache der Match-Loader.

Hintergrund
-----------
Unter Gunicorn laufen drei Worker, jeder mit eigenem Prozessspeicher.
Ein In-Memory-Cache wird deshalb bis zu dreimal gefuellt: dieselbe Saison
wird dreimal von football-data.org geholt. Genau dieses Problem war fuer
Tabellen, Saisoninfos und abgeschlossene Spiele schon einmal behoben
worden - fuer die CL-Loader bestand es weiterhin.

Betroffen waren:
    get_all_matches               (traegt die CL-Staerkeberechnung)
    get_cl_league_phase_matches
    get_cl_knockout_matches

Zusaetzlich abgesichert: Der Umstieg auf die Platte darf leere Antworten
nicht dauerhaft festschreiben. Eine noch nicht begonnene Saison oder ein
kurzer Ausfall der Quelle wuerde sonst den Neustart ueberleben.
"""

import json
import os

import pytest

import src.api.league_api as league_api
import src.utils.disk_cache as disk_cache
from src.utils.cache import (
    TTL_EMPTY_RESULT,
    TTL_MATCHES_FINISHED,
    TTL_MATCHES_UPCOMING,
)


def _raw_match(match_id, stage, matchday, season_start, home, away, hg=1, ag=0):
    return {
        "id": match_id,
        "stage": stage,
        "matchday": matchday,
        "status": "FINISHED",
        "utcDate": f"{season_start}-09-17T21:00:00Z",
        "season": {"startDate": f"{season_start}-08-01"},
        "homeTeam": {"id": home, "name": f"Club {home}", "crest": None},
        "awayTeam": {"id": away, "name": f"Club {away}", "crest": None},
        "score": {"fullTime": {"home": hg, "away": ag},
                  "regularTime": {}, "penalties": {}, "winner": "HOME_TEAM"},
    }


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """Eigener Cache-Ordner je Test, damit data/cache unberuehrt bleibt."""
    monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path))
    # Der In-Memory-Cache darf Ergebnisse nicht verschleiern.
    from src.utils import cache as memory_cache
    memory_cache.clear_all()
    return tmp_path


@pytest.fixture
def api_calls(monkeypatch):
    """Zaehlt HTTP-Zugriffe und liefert je nach Parametern passende Daten."""
    calls = []

    def fake_get_json(path, params=None):
        params = dict(params or {})
        calls.append((path, params))
        season = params.get("season", 2025)
        stage = params.get("stage")

        if stage == "LEAGUE_STAGE":
            return {"matches": [_raw_match(1, "LEAGUE_STAGE",
                                           params.get("matchday", 1),
                                           season, 5, 61)]}
        if stage:
            return {"matches": [_raw_match(2, stage, 1, season, 5, 66)]}

        return {"matches": [
            _raw_match(1, "LEAGUE_STAGE", 1, season, 5, 61),
            _raw_match(2, "LAST_16", 1, season, 5, 66),
        ]}

    monkeypatch.setattr(league_api, "_get_json", fake_get_json)
    monkeypatch.setattr(league_api, "resolve_season", lambda code, season=None: season or 2025)
    return calls


# ---------------------------------------------------------------------------
# Der eigentliche Punkt: ueberlebt der Cache einen Prozesswechsel?
# ---------------------------------------------------------------------------

def test_get_all_matches_survives_process_restart(isolated_cache, api_calls):
    """
    Simuliert den Gunicorn-Fall: Der In-Memory-Cache wird geleert (neuer
    Worker), die Platte bleibt. Es darf KEIN zweiter Request entstehen.
    """
    from src.utils import cache as memory_cache

    league_api.get_all_matches("CL", season=2025)
    assert len(api_calls) == 1

    memory_cache.clear_all()  # neuer Worker / Neustart

    league_api.get_all_matches("CL", season=2025)
    assert len(api_calls) == 1, (
        "Zweiter Worker hat erneut die API befragt - der Cache liegt "
        "weiterhin nur im Prozessspeicher"
    )


def test_cl_league_phase_survives_process_restart(isolated_cache, api_calls):
    from src.utils import cache as memory_cache

    league_api.get_cl_league_phase_matches(3, season=2025)
    memory_cache.clear_all()
    league_api.get_cl_league_phase_matches(3, season=2025)

    assert len(api_calls) == 1


def test_cl_knockout_survives_process_restart(isolated_cache, api_calls):
    from src.utils import cache as memory_cache

    league_api.get_cl_knockout_matches("LAST_16", season=2025)
    memory_cache.clear_all()
    league_api.get_cl_knockout_matches("LAST_16", season=2025)

    assert len(api_calls) == 1


def test_cache_files_actually_land_on_disk(isolated_cache, api_calls):
    league_api.get_all_matches("CL", season=2025)

    files = os.listdir(str(isolated_cache))
    assert any("all_matches" in name for name in files), files


# ---------------------------------------------------------------------------
# Key-Isolation: nichts darf ueber Grenzen hinweg vermischt werden
# ---------------------------------------------------------------------------

def test_seasons_are_isolated(isolated_cache, api_calls):
    league_api.get_all_matches("CL", season=2025)
    league_api.get_all_matches("CL", season=2024)

    assert len(api_calls) == 2
    assert api_calls[0][1]["season"] == 2025
    assert api_calls[1][1]["season"] == 2024


def test_competitions_are_isolated(isolated_cache, api_calls):
    league_api.get_all_matches("CL", season=2025)
    league_api.get_all_matches("BL1", season=2025)

    assert len(api_calls) == 2
    assert "/CL/" in api_calls[0][0]
    assert "/BL1/" in api_calls[1][0]


def test_only_finished_flag_is_part_of_the_key(isolated_cache, api_calls):
    """
    only_finished aendert den Inhalt grundlegend (mit vs. ohne noch nicht
    gespielte Partien). Beide Varianten duerfen sich nicht ueberschreiben.
    """
    league_api.get_all_matches("CL", season=2025, only_finished=True)
    league_api.get_all_matches("CL", season=2025, only_finished=False)

    assert len(api_calls) == 2


def test_matchdays_are_isolated(isolated_cache, api_calls):
    league_api.get_cl_league_phase_matches(1, season=2025)
    league_api.get_cl_league_phase_matches(2, season=2025)

    assert len(api_calls) == 2
    assert api_calls[0][1]["matchday"] == 1
    assert api_calls[1][1]["matchday"] == 2


def test_knockout_stages_are_isolated(isolated_cache, api_calls):
    league_api.get_cl_knockout_matches("LAST_16", season=2025)
    league_api.get_cl_knockout_matches("QUARTER_FINALS", season=2025)

    assert len(api_calls) == 2
    assert api_calls[0][1]["stage"] == "LAST_16"
    assert api_calls[1][1]["stage"] == "QUARTER_FINALS"


def test_league_phase_and_knockout_do_not_collide(isolated_cache, api_calls):
    """
    Der konkrete Kollisionsfall der CL: matchday=1 existiert in der
    Ligaphase UND im Achtelfinale. Die Keys tragen unterschiedliche
    Praefixe, deshalb darf sich nichts ueberschreiben.
    """
    phase = league_api.get_cl_league_phase_matches(1, season=2025)
    knockout = league_api.get_cl_knockout_matches("LAST_16", season=2025)

    assert phase[0]["stage"] == "LEAGUE_STAGE"
    assert knockout[0]["stage"] == "LAST_16"
    assert len(api_calls) == 2


# ---------------------------------------------------------------------------
# Leere Antworten duerfen nicht eingefroren werden
# ---------------------------------------------------------------------------

def _stored_ttl_seconds(cache_dir, key_fragment):
    """Liest die tatsaechlich geschriebene Lebensdauer aus den Metadaten."""
    from datetime import datetime

    for name in os.listdir(str(cache_dir)):
        if key_fragment not in name:
            continue
        with open(os.path.join(str(cache_dir), name), encoding="utf-8") as fh:
            meta = json.load(fh)["meta"]
        fetched = datetime.fromisoformat(meta["fetched_at"])
        expires = datetime.fromisoformat(meta["expires_at"])
        return round((expires - fetched).total_seconds())
    raise AssertionError(f"Kein Cache-Eintrag mit {key_fragment} gefunden")


def test_empty_result_gets_short_ttl(isolated_cache, monkeypatch):
    """
    Eine noch nicht begonnene Saison liefert eine leere Liste. Die darf
    nicht 24 Stunden festgehalten werden, sonst bliebe der Wettbewerb
    kuenstlich lange leer, nachdem die Auslosung erfolgt ist.
    """
    monkeypatch.setattr(league_api, "_get_json", lambda *a, **k: {"matches": []})
    monkeypatch.setattr(league_api, "resolve_season", lambda code, season=None: 2026)

    result = league_api.get_all_matches("CL", season=2026)

    assert result == []
    assert _stored_ttl_seconds(isolated_cache, "all_matches") == TTL_EMPTY_RESULT


def test_non_empty_result_gets_full_ttl(isolated_cache, api_calls):
    league_api.get_all_matches("CL", season=2025, only_finished=True)

    assert _stored_ttl_seconds(isolated_cache, "all_matches") == TTL_MATCHES_FINISHED


def test_empty_league_phase_gets_short_ttl(isolated_cache, monkeypatch):
    monkeypatch.setattr(league_api, "_get_json", lambda *a, **k: {"matches": []})
    monkeypatch.setattr(league_api, "resolve_season", lambda code, season=None: 2026)

    league_api.get_cl_league_phase_matches(1, season=2026)

    assert _stored_ttl_seconds(isolated_cache, "cl_league_phase") == TTL_EMPTY_RESULT


def test_populated_league_phase_gets_upcoming_ttl(isolated_cache, api_calls):
    league_api.get_cl_league_phase_matches(1, season=2025)

    assert _stored_ttl_seconds(isolated_cache, "cl_league_phase") == TTL_MATCHES_UPCOMING


# ---------------------------------------------------------------------------
# Bestehende Semantik bleibt erhalten
# ---------------------------------------------------------------------------

def test_wrong_season_response_still_yields_empty(isolated_cache, monkeypatch):
    """
    football-data liefert bei unbekannter Saison still die laufende
    zurueck. Diese Absicherung darf durch den Cache-Wechsel nicht
    verloren gehen.
    """
    monkeypatch.setattr(league_api, "resolve_season", lambda code, season=None: 2026)
    monkeypatch.setattr(
        league_api, "_get_json",
        lambda *a, **k: {"matches": [_raw_match(1, "LEAGUE_STAGE", 1, 2025, 5, 61)]},
    )

    assert league_api.get_cl_league_phase_matches(1, season=2026) == []
    assert league_api.get_all_matches("CL", season=2026) == []


def test_api_404_still_yields_empty_for_cl(isolated_cache, monkeypatch):
    def boom(*args, **kwargs):
        raise league_api.ApiUnavailable("nicht gefunden", status_code=404)

    monkeypatch.setattr(league_api, "_get_json", boom)
    monkeypatch.setattr(league_api, "resolve_season", lambda code, season=None: 2026)

    assert league_api.get_cl_knockout_matches("LAST_16", season=2026) == []


def test_returned_payload_survives_json_roundtrip(isolated_cache, api_calls):
    """
    Der Disk-Cache serialisiert nach JSON. Was aus dem Cache kommt, muss
    inhaltlich dem entsprechen, was frisch geladen wurde.
    """
    from src.utils import cache as memory_cache

    fresh = league_api.get_all_matches("CL", season=2025)
    memory_cache.clear_all()
    cached = league_api.get_all_matches("CL", season=2025)

    assert fresh == cached
    assert cached[0]["home_id"] == 5
    assert cached[0]["stage"] == "LEAGUE_STAGE"
