"""
Test des wettbewerbsbasierten NM-Imports (import_national_for_season).

Prueft ohne echten API-Zugriff:
  - nur Pool-Spieler werden aufgenommen (Fremdspieler ignoriert),
  - Paginierung wird korrekt durchlaufen,
  - die geschriebene Datei hat die erwartete Struktur.
"""

import json
import pytest

from src.data import national_import
from src.data import national_competitions


def _player_block(pid, league_id, name, minutes):
    return {
        "player": {"id": pid, "name": f"P{pid}"},
        "statistics": [{
            "league": {"id": league_id, "name": name, "type": None},
            "games": {"minutes": minutes, "position": "Midfielder",
                      "appearences": 3, "lineups": 3},
            "goals": {"total": 1, "assists": 0},
        }],
    }


@pytest.fixture
def patched(tmp_path, monkeypatch):
    monkeypatch.setattr(national_import, "NATIONAL_DIR", str(tmp_path))
    national_import.clear_runtime_cache()

    # Nur EIN Zielwettbewerb fuer FootSim 2025: WM (id 1, api 2026).
    monkeypatch.setattr(
        national_competitions, "national_targets_for_footsim_season",
        lambda s: [{"league_id": 1, "api_season": 2026, "name": "World Cup"}],
    )
    # national_import importiert die Funktion direkt - auch dort patchen:
    monkeypatch.setattr(
        national_import, "national_targets_for_footsim_season",
        lambda s: [{"league_id": 1, "api_season": 2026, "name": "World Cup"}],
    )

    # Zwei Seiten simulierte WM-Spieler: Spieler 99 (im Pool), 500/501 (fremd).
    pages = {
        1: {"response": [_player_block(99, 1, "World Cup", 400),
                         _player_block(500, 1, "World Cup", 200)],
            "paging": {"current": 1, "total": 2}},
        2: {"response": [_player_block(501, 1, "World Cup", 100)],
            "paging": {"current": 2, "total": 2}},
    }

    def fake_fetch(league_id, api_season, page):
        return pages[page]

    monkeypatch.setattr(national_import, "_fetch_competition_page", fake_fetch)
    return tmp_path


def test_only_pool_players_imported(patched):
    # Pool enthaelt nur Spieler 99.
    result = national_import.import_national_for_season(2025, {99})

    assert "99" in result
    assert "500" not in result      # Fremdspieler ignoriert
    assert "501" not in result
    assert len(result["99"]) == 1
    assert result["99"][0]["league"]["id"] == 1


def test_national_file_written(patched):
    national_import.import_national_for_season(2025, {99})
    path = national_import.national_path(2025)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["footsim_season"] == 2025
    assert data["player_count"] == 1
    assert "99" in data["blocks_by_player"]


def test_get_national_blocks_roundtrip(patched):
    national_import.import_national_for_season(2025, {99})
    national_import.clear_runtime_cache()
    blocks = national_import.get_national_blocks(99, 2025)
    assert len(blocks) == 1
    assert blocks[0]["games"]["minutes"] == 400
    # Fremdspieler liefert nichts:
    assert national_import.get_national_blocks(500, 2025) == []


def test_paginierung_laedt_alle_seiten_ueber_40(tmp_path, monkeypatch):
    """
    Regressions-Sicherung fuer den 40-Seiten-Deckel: ein Turnier mit 63 Seiten
    (wie die WM 2026) muss VOLLSTAENDIG geladen werden. Ein Pool-Spieler, dessen
    Block erst auf Seite 55 steht (wie Haaland/Norwegen), darf nicht verloren
    gehen.
    """
    monkeypatch.setattr(national_import, "NATIONAL_DIR", str(tmp_path))
    national_import.clear_runtime_cache()

    monkeypatch.setattr(
        national_import, "national_targets_for_footsim_season",
        lambda s: [{"league_id": 1, "api_season": 2026, "name": "World Cup"}],
    )

    TOTAL_PAGES = 63
    HAALAND_ID = 1100
    HAALAND_PAGE = 55

    def fake_fetch(league_id, api_season, page):
        # Seite 1 meldet die echte Gesamtzahl. Haaland steht auf Seite 55.
        response = []
        if page == HAALAND_PAGE:
            response = [_player_block(HAALAND_ID, 1, "World Cup", 480)]
        return {"response": response, "paging": {"current": page, "total": TOTAL_PAGES}}

    monkeypatch.setattr(national_import, "_fetch_competition_page", fake_fetch)

    result = national_import.import_national_for_season(2025, {HAALAND_ID})

    assert str(HAALAND_ID) in result, "Spieler auf Seite 55 muss importiert werden"
    assert result[str(HAALAND_ID)][0]["games"]["minutes"] == 480


def test_safety_limit_schuetzt_vor_endlosschleife(tmp_path, monkeypatch, capsys):
    """
    Wenn die API eine unplausibel hohe Seitenzahl meldet, stoppt der Import am
    Safety-Limit und warnt - statt endlos zu laufen.
    """
    monkeypatch.setattr(national_import, "NATIONAL_DIR", str(tmp_path))
    monkeypatch.setattr(national_import, "PAGE_SAFETY_LIMIT", 10)
    national_import.clear_runtime_cache()

    monkeypatch.setattr(
        national_import, "national_targets_for_footsim_season",
        lambda s: [{"league_id": 1, "api_season": 2026, "name": "World Cup"}],
    )

    def fake_fetch(league_id, api_season, page):
        # Meldet absurd viele Seiten.
        return {"response": [], "paging": {"current": page, "total": 99999}}

    monkeypatch.setattr(national_import, "_fetch_competition_page", fake_fetch)
    national_import.import_national_for_season(2025, {1100})

    out = capsys.readouterr().out
    assert "WARNUNG" in out
