"""
Gemeinsame Bausteine der Testsuite.

Alles laeuft offline: Saisonspielplaene werden im football-data-Rohformat
erzeugt, historische Saisons als Dateien in ein Temp-Verzeichnis
geschrieben und die Loader per Monkeypatch dorthin umgebogen.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from src.data import historical_loader as hl  # noqa: E402
from src.features import fallback_strengths as fs  # noqa: E402
from src.predict import season_sim as ss  # noqa: E402


# ---------------------------------------------------------------------------
# Spielplan-Erzeugung (Doppelrunde, Kreis-Methode)
# ---------------------------------------------------------------------------

def round_robin_matchdays(team_ids):
    """Echte Spieltagsstruktur: (n-1)*2 Spieltage, jedes Team genau 1x pro Spieltag."""
    ids = list(team_ids)
    n = len(ids)
    assert n % 2 == 0, "Testligen brauchen gerade Teamzahl"
    arr = ids[:]
    first_half = []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = arr[i], arr[n - 1 - i]
            pairs.append((a, b) if r % 2 == 0 else (b, a))
        first_half.append(pairs)
        arr = [arr[0], arr[-1]] + arr[1:-1]
    second_half = [[(b, a) for a, b in rd] for rd in first_half]
    return first_half + second_half


def _goals(h, a, md):
    return (h * 7 + md) % 4, (a * 5 + md) % 3


def build_raw_season(team_ids, names=None, finished_matchdays=0,
                     postponed_indices=(), cancelled_indices=(),
                     missing_id_indices=()):
    """Roh-Matchliste im football-data-Format fuer eine komplette Saison."""
    names = names or {tid: f"Team {tid}" for tid in team_ids}
    raw = []
    idx = 0
    for md, pairs in enumerate(round_robin_matchdays(team_ids), start=1):
        for h, a in pairs:
            finished = md <= finished_matchdays
            hg, ag = _goals(h, a, md) if finished else (None, None)
            status = "FINISHED" if finished else "SCHEDULED"
            if idx in postponed_indices:
                status, hg, ag = "POSTPONED", None, None
            if idx in cancelled_indices:
                status, hg, ag = "CANCELLED", None, None
            home_id = None if idx in missing_id_indices else h
            raw.append({
                "status": status,
                "matchday": md,
                "homeTeam": {"id": home_id, "name": names[h]},
                "awayTeam": {"id": a, "name": names[a]},
                "score": {"fullTime": {"home": hg, "away": ag}},
            })
            idx += 1
    return raw


def standings_from(team_ids, names=None, finished=()):
    """Tabelle im Format der App-Routen, berechnet aus beendeten Partien."""
    names = names or {tid: f"Team {tid}" for tid in team_ids}
    rows = {tid: {"team_id": tid, "team_name": names[tid], "points": 0,
                  "played": 0, "goals_for": 0, "goals_against": 0,
                  "goal_difference": 0} for tid in team_ids}
    for m in finished:
        h, a = rows[m["home_id"]], rows[m["away_id"]]
        hg, ag = m["home_goals"], m["away_goals"]
        h["played"] += 1; a["played"] += 1
        h["goals_for"] += hg; h["goals_against"] += ag
        a["goals_for"] += ag; a["goals_against"] += hg
        if hg > ag: h["points"] += 3
        elif hg < ag: a["points"] += 3
        else: h["points"] += 1; a["points"] += 1
    for r in rows.values():
        r["goal_difference"] = r["goals_for"] - r["goals_against"]
    table = sorted(rows.values(), key=lambda r: (-r["points"], -r["goal_difference"]))
    for pos, r in enumerate(table, start=1):
        r["position"] = pos
    return table


# ---------------------------------------------------------------------------
# Historische Saisons als Dateien
# ---------------------------------------------------------------------------

def write_history(api_code, season, team_ids, names=None):
    """Schreibt eine komplette historische Saison im Speicherformat."""
    names = names or {tid: f"Team {tid}" for tid in team_ids}
    matches = []
    for md, pairs in enumerate(round_robin_matchdays(team_ids), start=1):
        for h, a in pairs:
            hg, ag = _goals(h, a, md)
            matches.append({"matchday": md, "home_id": h, "away_id": a,
                            "home_goals": hg, "away_goals": ag})
    payload = {
        "api_code": api_code,
        "season": season,
        "teams": {str(tid): {"name": names[tid], "short_name": names[tid]}
                  for tid in team_ids},
        "matches": matches,
    }
    path = hl.season_file_path(api_code, season)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


@pytest.fixture
def test_league(monkeypatch, tmp_path):
    """Isolierte Testliga 'testl' mit eigenem Historienverzeichnis."""
    monkeypatch.setattr(hl, "HISTORICAL_DIR", str(tmp_path))
    monkeypatch.setitem(hl.LEAGUE_CODES, "testl", "TESTL")
    if hasattr(ss, "ZONE_CONFIGS") and "testl" not in ss.ZONE_CONFIGS:
        sample = next(iter(ss.ZONE_CONFIGS.values()))
        monkeypatch.setitem(ss.ZONE_CONFIGS, "testl", sample)
    fs._reset_cache()
    yield {"api_code": "TESTL", "league_key": "testl", "write": write_history}
    fs._reset_cache()
