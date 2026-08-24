"""
Integrationstest fuer den Wettbewerbsumfang-Fix.

Kernaussage, die hier bewiesen wird: Der Player-Pool wird NICHT mehr aus der
duennen Liga-Seiten-Abfrage gebaut (die pro Spieler nur den Liga-Block
liefert), sondern aus der vollstaendigen ID-Abfrage - derselben Quelle wie
der Radar. Dadurch enthalten club_all/league/national/all echte, voneinander
verschiedene Aggregate, und Pool, Scatter und Perzentile beruhen auf
identischen Rohdaten.

Kein echter API-Request: get_player_season_raw() wird durch eine synthetische
Rohantwort ersetzt, die je Spieler drei Wettbewerbsbloecke enthaelt
(nationale Liga + Champions League als Cup + Nationalmannschaft). Genau so
sieht eine echte /players?id=-Antwort aus.
"""

import pytest

import refresh_players
from src.data import player_pool
from src.data.player_pool import load_scatter_points, read_pool
from src.data.percentile_engine import (
    build_snapshot,
    distributions_for_scope,
    percentiles_for_player,
)


# --- Synthetische Rohantwort mit drei Wettbewerben je Spieler --------------

BL1_LEAGUE_ID = 78   # Bundesliga, type "League", eine der Vergleichsligen
CL_CUP_ID = 2        # Champions League, type "Cup"
NT_ID = 999          # Nationalmannschaft, type "International"


def _stat_block(league_id, league_type, minutes, goals, assists, name):
    return {
        "league": {"id": league_id, "name": name, "type": league_type,
                   "country": "x"},
        "team": {"id": 1, "name": "Test FC", "logo": None},
        "games": {"appearences": 20, "lineups": 18, "minutes": minutes,
                  "position": "Attacker", "rating": "7.00"},
        "shots": {"total": 40, "on": 15},
        "goals": {"total": goals, "conceded": None, "assists": assists,
                  "saves": None},
        "passes": {"total": 600, "key": 20, "accuracy": 82},
        "tackles": {"total": 15, "blocks": 2, "interceptions": 8},
        "duels": {"total": 150, "won": 80},
        "dribbles": {"attempts": 50, "success": 30},
        "fouls": {"drawn": 20, "committed": 15},
        "cards": {"yellow": 2, "red": 0},
        "penalty": {"saved": None, "scored": 1, "missed": 0},
    }


def _full_raw_for(player_id, league_goals):
    """
    Eine vollstaendige ID-Antwort: Liga (2000'), Champions League als Cup
    (600') und Nationalmannschaft (300'). Die Tore variieren je Spieler,
    damit eine echte Verteilung entsteht.
    """
    return {
        "player": {"id": player_id, "name": f"Spieler {player_id}", "age": 25,
                   "birth": {}},
        "statistics": [
            _stat_block(BL1_LEAGUE_ID, "League", 2000, league_goals, 6, "Bundesliga"),
            _stat_block(CL_CUP_ID, "Cup", 600, 4, 2, "UEFA Champions League"),
            _stat_block(NT_ID, "International", 300, 2, 1, "World Cup"),
        ],
    }


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    pool_dir = tmp_path / "player_pool"
    monkeypatch.setattr(player_pool, "POOL_DIR", str(pool_dir))
    monkeypatch.setattr(player_pool, "STATUS_PATH", str(pool_dir / "status.json"))
    monkeypatch.setattr(player_pool, "LOCK_PATH", str(pool_dir / "import.lock"))

    # 40 Spieler, damit eine Verteilung (MIN_POOL_SIZE = 30) zustande kommt.
    player_ids = list(range(1, 41))

    def fake_page(league_code, season, page=1):
        # Alle Spieler auf einer Seite - der Seiteninhalt braucht nur die ID.
        return {
            "response": [{"player": {"id": pid}} for pid in player_ids],
            "results": len(player_ids),
            "paging": {"current": 1, "total": 1},
        }

    def fake_raw(player_id, season, throttle_seconds=0.0):
        # Ligator variiert von 5..44 -> echte Streuung in goals_per90.
        return _full_raw_for(player_id, league_goals=4 + player_id)

    monkeypatch.setattr(refresh_players, "get_league_players_page", fake_page)
    monkeypatch.setattr(refresh_players, "get_player_season_raw", fake_raw)

    return player_ids


def _import(season=2024):
    """
    Fuehrt den Import der Testliga aus und liefert den Pool.

    Geprueft wird, dass der Lauf DURCHGELAUFEN ist und Spieler abgelegt
    hat - nicht, dass er "complete" heisst. Seit der Datenreparatur
    entscheidet ueber diesen Status die inhaltliche Ligaabdeckung, und
    die 40 synthetischen Spieler dieser Fixture in einem einzigen Verein
    sind bewusst keine vollstaendige Bundesliga. Der Gegenstand dieser
    Datei ist die Scope-Aggregation, nicht die Vollstaendigkeitspruefung -
    die hat ihre eigenen Tests in test_player_pool.py.
    """
    ok = refresh_players.import_one_league("bl1", season, force=True)
    assert ok is True
    status = player_pool.get_pool_status("bl1", season)
    assert status["status"] in (player_pool.STATUS_COMPLETE,
                                player_pool.STATUS_PROVIDER_INCOMPLETE)
    assert status["loaded_pages"] == status["total_pages"]
    pool = read_pool("bl1", season)
    assert pool["players"], "Import hat keine Spieler abgelegt"
    return pool


# --- 1. Der Pool traegt echte, verschiedene Aggregate je Scope -------------

def test_pool_minuten_je_scope_unterscheiden_sich(isolated):
    pool = _import()
    entry = pool["players"][0]
    m = entry["minutes_by_scope"]

    assert m["league"] == 2000                 # nur nationale Liga
    assert m["club_all"] == 2600               # Liga + Champions League (Cup)
    assert m["national"] == 300                # nur Nationalmannschaft
    assert m["all"] == 2900                    # alles zusammen


def test_pool_kennzahlen_je_scope_unterscheiden_sich(isolated):
    pool = _import()
    entry = pool["players"][0]
    g = entry["metrics_by_scope"]

    # club_all zaehlt Champions-League-Tore mit, league nicht -> verschieden.
    assert g["club_all"]["goals_per90"] != g["league"]["goals_per90"]
    # national beruht nur auf 300 Laenderspielminuten -> wieder anders.
    assert g["national"]["goals_per90"] != g["league"]["goals_per90"]


def test_pool_league_code_ist_die_entdeckungsliga(isolated):
    pool = _import()
    assert all(e["league_code"] == "bl1" for e in pool["players"])


# --- 2. Der Snapshot hat je Scope eine eigene Verteilung -------------------

def test_snapshot_verteilungen_je_scope_verschieden(isolated):
    pool = _import()
    snapshot = build_snapshot(pool["players"], 2024, ["bl1"])

    club = distributions_for_scope(snapshot, "club_all")
    league = distributions_for_scope(snapshot, "league")

    assert "Attacker" in club and "Attacker" in league
    club_q = club["Attacker"]["metrics"]["goals_per90"]["q"]
    league_q = league["Attacker"]["metrics"]["goals_per90"]["q"]
    assert club_q != league_q, "club_all- und Ligaverteilung muessen sich unterscheiden"


def test_snapshot_national_ist_leer_wegen_zu_weniger_minuten(isolated):
    """
    300 Laenderspielminuten liegen unter der 450-Minuten-Grenze. Die
    Mindestminuten muessen sich auf DENSELBEN Scope beziehen - sonst
    rutschten Spieler ueber ihre Ligaminuten faelschlich in die
    Nationalmannschaftsverteilung.
    """
    pool = _import()
    snapshot = build_snapshot(pool["players"], 2024, ["bl1"])
    national = distributions_for_scope(snapshot, "national")
    assert national == {}


def test_snapshot_top_level_bleibt_club_all(isolated):
    """Rueckwaertskompatibilitaet: alte Leser sehen weiterhin club_all."""
    pool = _import()
    snapshot = build_snapshot(pool["players"], 2024, ["bl1"])
    assert snapshot["scope"] == "club_all"
    assert snapshot["distributions"] == \
        snapshot["distributions_by_scope"]["club_all"]


# --- 3. Scatter liest denselben Pool und reagiert auf den Scope ------------

def test_scatter_werte_folgen_dem_scope(isolated):
    _import(season=2024)

    club, used = load_scatter_points(
        2024, ["bl1"], "Attacker", 450, "goals_per90", "assists_per90",
        scope="club_all",
    )
    league, _ = load_scatter_points(
        2024, ["bl1"], "Attacker", 450, "goals_per90", "assists_per90",
        scope="league",
    )

    assert used == ["bl1"]
    assert club and league
    by_id_club = {p["id"]: p for p in club}
    by_id_league = {p["id"]: p for p in league}
    common = set(by_id_club) & set(by_id_league)
    assert common
    # Fuer mindestens einen Spieler weicht der club_all-x-Wert vom Liga-Wert ab.
    assert any(by_id_club[i]["x"] != by_id_league[i]["x"] for i in common)


# --- 4. Perzentile messen im gewaehlten Scope ------------------------------

def test_perzentil_nutzt_die_scope_verteilung(isolated):
    pool = _import()
    snapshot = build_snapshot(pool["players"], 2024, ["bl1"])

    # Ein und derselbe Rohwert, gemessen an zwei verschiedenen Verteilungen,
    # darf nicht dasselbe Perzentil ergeben - sonst waere der Scope wirkungslos.
    test_value = 0.30
    p_club = percentiles_for_player(
        snapshot, "Attacker", {"goals_per90": test_value}, scope="club_all"
    )["goals_per90"]
    p_league = percentiles_for_player(
        snapshot, "Attacker", {"goals_per90": test_value}, scope="league"
    )["goals_per90"]

    assert p_club is not None and p_league is not None
    assert p_club != p_league
