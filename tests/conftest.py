"""
Gemeinsame Testgrundlage.

Zwei Datenquellen:
  1. Synthetische Mini-Ligen (deterministisch, kein Netzwerk) fuer
     Logik- und Invariantentests.
  2. Die im Disk-Cache liegenden ECHTEN Saisonplaene (PD und FL1,
     Saison 2026/27, je 380/306 Spiele) fuer End-to-End-Tests. Diese
     Tests laufen komplett offline.
"""

import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Synthetische Ligen
# ---------------------------------------------------------------------------

def make_round_robin_raw(team_ids, finished_matchdays=0,
                         goals=lambda h, a, md: (1, 1)):
    """
    Erzeugt rohe API-Spiele einer Doppelrunde (Format football-data.org).

    team_ids:           Liste der Team-IDs
    finished_matchdays: so viele Spieltage gelten als FINISHED
    goals(h, a, md):    Ergebnisfunktion fuer beendete Spiele
    """
    n = len(team_ids)
    rounds = n - 1
    matches = []

    # Rundenturnier per Kreisverfahren, dann Rueckrunde gespiegelt.
    rotation = list(team_ids)
    schedule = []
    for _ in range(rounds):
        pairs = []
        for i in range(n // 2):
            pairs.append((rotation[i], rotation[n - 1 - i]))
        schedule.append(pairs)
        rotation = [rotation[0]] + [rotation[-1]] + rotation[1:-1]

    match_id = 1000
    for half in (0, 1):
        for round_index, pairs in enumerate(schedule):
            matchday = half * rounds + round_index + 1
            for home, away in pairs:
                if half == 1:
                    home, away = away, home
                finished = matchday <= finished_matchdays
                hg, ag = goals(home, away, matchday) if finished else (None, None)
                matches.append({
                    "id": match_id,
                    "stage": "REGULAR_SEASON",
                    "matchday": matchday,
                    "status": "FINISHED" if finished else "SCHEDULED",
                    "utcDate": f"2026-08-{min(28, matchday):02d}T15:00:00Z",
                    "homeTeam": {"id": home, "name": f"Team {home}",
                                 "shortName": f"T{home}", "crest": None},
                    "awayTeam": {"id": away, "name": f"Team {away}",
                                 "shortName": f"T{away}", "crest": None},
                    "score": {"fullTime": {"home": hg, "away": ag}},
                })
                match_id += 1

    return matches


def make_standings_table(team_ids, played=0):
    """Minimale Tabellenzeilen im Format von get_standings()."""
    return [
        {
            "position": index + 1,
            "team_id": team_id,
            "team_name": f"Team {team_id}",
            "team_full_name": f"Team {team_id} FC",
            "crest": None,
            "played": played,
            "points": 0,
            "goals_for": 0,
            "goals_against": 0,
            "goal_difference": 0,
        }
        for index, team_id in enumerate(team_ids)
    ]


def make_historical_payload(team_ids, season, strong=None, weak=None):
    """
    Synthetische historische Saison im Format des historical_loader.

    strong: Team-IDs, die deutlich mehr Tore schiessen und weniger kassieren
    weak:   Team-IDs mit dem Gegenteil
    """
    strong = set(strong or [])
    weak = set(weak or [])

    def goals(home, away, matchday):
        # Leichter Heimvorteil wie in echten Ligen, sonst waere der
        # implizite Heimbonus des Modells nicht testbar.
        hg, ag = 2, 1
        if home in strong:
            hg += 2
        if away in strong:
            ag += 2
        if home in weak:
            ag += 1
            hg = max(0, hg - 1)
        if away in weak:
            hg += 1
            ag = max(0, ag - 1)
        return hg, ag

    raw = make_round_robin_raw(team_ids, finished_matchdays=2 * (len(team_ids) - 1),
                               goals=goals)

    teams = {}
    matches = []
    for m in raw:
        h, a = m["homeTeam"], m["awayTeam"]
        teams.setdefault(h["id"], {"id": h["id"], "name": h["name"],
                                   "short_name": h["shortName"], "crest": None})
        teams.setdefault(a["id"], {"id": a["id"], "name": a["name"],
                                   "short_name": a["shortName"], "crest": None})
        matches.append({
            "matchday": m["matchday"],
            "date": m["utcDate"][:10],
            "home_id": h["id"],
            "away_id": a["id"],
            "home_goals": m["score"]["fullTime"]["home"],
            "away_goals": m["score"]["fullTime"]["away"],
        })

    return {
        "meta": {"api_code": "TEST", "season": season,
                 "matches": len(matches), "teams": len(teams)},
        "teams": teams,
        "matches": matches,
    }


# ---------------------------------------------------------------------------
# Echte gecachte Saisondaten (offline)
# ---------------------------------------------------------------------------

def _load_cached(name):
    path = os.path.join(PROJECT_ROOT, "data", "cache", name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)["payload"]


@pytest.fixture(scope="session")
def cached_pd_matches():
    data = _load_cached("season_full_matches__PD__2026.json")
    if data is None:
        pytest.skip("Gecachte PD-Saisondaten fehlen")
    return data


@pytest.fixture(scope="session")
def cached_fl1_matches():
    data = _load_cached("season_full_matches__FL1__2026.json")
    if data is None:
        pytest.skip("Gecachte FL1-Saisondaten fehlen")
    return data


@pytest.fixture(scope="session")
def cached_pd_standings():
    data = _load_cached("standings__PD__2026.json")
    if data is None:
        pytest.skip("Gecachte PD-Tabelle fehlt")
    return data


# ---------------------------------------------------------------------------
# CSS-Hilfen fuer Markup-/Mobile-Tests
# ---------------------------------------------------------------------------
#
# Frueher wurde ein Media-Query-Block ueber css.rindex("@media ...") gesucht,
# also ueber das LETZTE Vorkommen in der Datei. Das hielt nur so lange, wie
# der jeweils gepruefte Block zufaellig der letzte seiner Art war - jeder
# spaeter angehaengte Abschnitt mit demselben Breakpoint liess die Tests
# fehlschlagen, obwohl die geprueften Regeln unveraendert vorhanden waren.
#
# Diese Helfer schneiden Media-Query-Bloecke exakt ueber Klammerzaehlung aus
# und pruefen ALLE Bloecke desselben Breakpoints. Die Aussage der Tests wird
# dadurch nicht schwaecher, sondern praeziser: "diese Regel steht in einem
# Block dieses Breakpoints" statt "... im letzten Block der Datei".

def css_media_blocks(css, query):
    """Alle Bloecke eines Media-Query, exakt bis zur passenden Klammer."""
    blocks = []
    start = 0

    while True:
        found = css.find(query, start)
        if found == -1:
            return blocks

        opening = css.find("{", found)
        if opening == -1:
            return blocks

        depth = 0
        for index in range(opening, len(css)):
            if css[index] == "{":
                depth += 1
            elif css[index] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(css[opening + 1:index])
                    break

        start = found + len(query)


def css_media_contains(css, query, selector):
    """True, wenn IRGENDEIN Block dieses Breakpoints den Selektor enthaelt."""
    return any(selector in block for block in css_media_blocks(css, query))

import os

@pytest.fixture(scope='function')
def isolated_db(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    monkeypatch.setenv('TESTING', '1')
    
    import importlib
    import app as main_app
    importlib.reload(main_app)
    
    with main_app.app.app_context():
        main_app.db.create_all()
        yield main_app.db
        main_app.db.session.remove()
        main_app.db.drop_all()

@pytest.fixture(scope='function')
def postgres_db(monkeypatch):
    db_url = os.environ.get('DATABASE_URL', '')
    if not db_url or 'footsim_db' not in db_url:
        pytest.skip('No local PostgreSQL configured in DATABASE_URL')
        
    test_db_url = db_url.replace('footsim_db', 'footsim_test_db')
    monkeypatch.setenv('DATABASE_URL', test_db_url)
    monkeypatch.setenv('TESTING', '1')
    
    import importlib
    import app as main_app
    importlib.reload(main_app)
    
    with main_app.app.app_context():
        from flask_migrate import upgrade
        
        # Clean state
        main_app.db.drop_all()
        main_app.db.session.execute(main_app.db.text("DROP TABLE IF EXISTS alembic_version CASCADE"))
        main_app.db.session.commit()
        
        upgrade()
        yield main_app.db
        
        main_app.db.session.remove()
        main_app.db.drop_all()
        main_app.db.session.execute(main_app.db.text("DROP TABLE IF EXISTS alembic_version CASCADE"))
        main_app.db.session.commit()
