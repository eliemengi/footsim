"""
Tests fuer die auf den Player-Pool umgestellte Radar-Suche.

Kernpunkte:
  - Die Suche liest den Pool (keine API), findet Pool-Spieler,
  - ist akzent- und gross-/kleinschreibungs-insensitiv,
  - liefert die vom UI erwarteten Felder,
  - markiert Pool-Spieler immer als comparable.
"""

import pytest

from src.data import player_compare_loader as loader


def _pool_entry(pid, name, league_code="pl", position="Attacker",
                minutes=2000, team="Test FC", age=25):
    return {
        "player_id": pid,
        "name": name,
        "position": position,
        "league_code": league_code,
        "age": age,
        "team_name": team,
        "minutes_by_scope": {"club_all": minutes, "league": minutes,
                             "national": None, "all": minutes},
        "metrics_by_scope": {"club_all": {}, "league": {},
                             "national": {}, "all": {}},
    }


@pytest.fixture
def fake_pool(monkeypatch):
    players = [
        _pool_entry(1100, "E. Haaland", "pl", "Attacker", 2958),
        _pool_entry(278, "Kylian Mbappé", "pd", "Attacker", 2500),
        _pool_entry(184, "H. Kane", "bl1", "Attacker", 2382),
        _pool_entry(500, "J. Müller", "bl1", "Midfielder", 1200),
        _pool_entry(501, "K. Müller", "sa", "Defender", 900),
    ]
    monkeypatch.setattr(
        "src.data.player_pool.load_all_players",
        lambda season, codes: (players, ["bl1", "pl", "pd", "sa", "fl1"]),
    )
    return players


def test_findet_pool_spieler(fake_pool):
    r = loader.search_players("haaland", 2025)
    assert len(r) == 1
    assert r[0]["name"] == "E. Haaland"
    assert r[0]["comparable"] is True


def test_akzent_insensitiv(fake_pool):
    # "mbappe" ohne Akzent muss "Mbappé" finden.
    r = loader.search_players("mbappe", 2025)
    assert any(x["name"] == "Kylian Mbappé" for x in r)


def test_gross_klein_insensitiv(fake_pool):
    assert loader.search_players("HAALAND", 2025)
    assert loader.search_players("haaland", 2025)


def test_teilstring(fake_pool):
    # "müller" und "muller" finden beide Mueller-Eintraege.
    assert len(loader.search_players("muller", 2025)) == 2
    assert len(loader.search_players("müller", 2025)) == 2


def test_sortierung_nach_minuten(fake_pool):
    # Alle "a" enthaltenden Namen -> nach club_all-Minuten absteigend.
    r = loader.search_players("a", 2025)
    minutes = [x["minutes"] for x in r]
    assert minutes == sorted(minutes, reverse=True)


def test_erwartete_felder(fake_pool):
    r = loader.search_players("kane", 2025)[0]
    for key in ("player_id", "name", "team_name", "league_label",
                "position_label", "age", "minutes", "comparable", "season"):
        assert key in r
    assert r["league_label"] == "Bundesliga"
    assert r["position_label"] is not None
    assert r["season"] == 2025


def test_zu_kurze_anfrage(fake_pool):
    assert loader.search_players("ka", 2025) == []


def test_pool_spieler_immer_comparable(fake_pool):
    for x in loader.search_players("a", 2025):
        assert x["comparable"] is True
