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

# Force MAIL_MOCK to true for all tests to prevent accidental real email sending
os.environ["MAIL_MOCK"] = "true"


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
    """
    Testdatenbank fuer PostgreSQL-Tests.

    SICHERHEITSSCHRANKEN
    Diese Fixture ruft drop_all() und DROP TABLE. Zielt sie je auf die
    falsche Datenbank, sind echte Daten weg. Deshalb drei Bedingungen,
    die ALLE erfuellt sein muessen - sonst wird uebersprungen statt
    geraten:

    1. Die URL muss 'footsim_db' enthalten (bestehende Pruefung).
    2. Die Ersetzung muss tatsaechlich etwas veraendert haben. Ohne diese
       Pruefung wuerde eine URL, in der die Ersetzung ins Leere laeuft,
       unbemerkt gegen die ENTWICKLUNGSDATENBANK arbeiten.
    3. Der Host muss lokal sein. Zeigt DATABASE_URL auf einen entfernten
       Server - etwa weil versehentlich die Produktionskonfiguration
       geladen wurde -, wird nichts angefasst. Ein Testlauf darf unter
       keinen Umstaenden eine entfernte Datenbank veraendern.
    """
    db_url = os.environ.get('DATABASE_URL', '')
    if not db_url or 'footsim_db' not in db_url:
        pytest.skip('No local PostgreSQL configured in DATABASE_URL')

    import re as _re
    host_match = _re.search(r'@([^/:]+)', db_url)
    host = host_match.group(1).lower() if host_match else ''
    if host not in ('localhost', '127.0.0.1', '::1', 'db', 'footsim_db'):
        pytest.skip(
            'DATABASE_URL zeigt auf einen nicht-lokalen Host - Tests legen '
            'dort keine Datenbank an und loeschen dort nichts.'
        )

    test_db_url = db_url.replace('footsim_db', 'footsim_test_db')
    if test_db_url == db_url:
        pytest.skip(
            'Der Testdatenbankname liesse sich nicht von der echten '
            'Datenbank unterscheiden - abgebrochen, statt gegen die '
            'Entwicklungsdatenbank zu arbeiten.'
        )

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


# ---------------------------------------------------------------------------
# Browsertests
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    """
    --e2e schaltet die Browsertests zu.

    Sie laufen bewusst nicht im Standardlauf mit: Sie starten einen
    echten Server, bauen die Testdatenbank neu auf und laden das
    app-Modul neu. Zusammen mit der uebrigen Suite im selben Prozess
    fuehrte das dazu, dass 50 Datenbanktests uebersprangen und zwei
    fielen - ein Testkonflikt, kein Anwendungsfehler.
    """
    parser.addoption(
        "--e2e", action="store_true", default=False,
        help="Browsertests (Playwright) mitlaufen lassen - eigener Lauf",
    )


def pytest_collection_modifyitems(config, items):
    """Ohne --e2e werden Browsertests sichtbar uebersprungen."""
    if config.getoption("--e2e"):
        return

    import pytest as _pytest

    grund = _pytest.mark.skip(
        reason="Browsertest - mit '--e2e' ausfuehren (siehe pytest.ini)"
    )
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(grund)


# ---------------------------------------------------------------------------
# Isolation der Flask-Konfiguration
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _app_modul_fruh_laden():
    """
    Laedt das app-Modul einmal zu Sitzungsbeginn, falls moeglich.

    Nur damit die Konfigurationssicherung unten von Anfang an einen
    Bezugspunkt hat. Ohne das haette der allererste Test, der app
    importiert UND dabei die Konfiguration aendert, kein "vorher" - und
    genau seine Aenderung wuerde weiterlecken.

    Ein Fehlschlag ist kein Problem: Wer app nicht importieren kann,
    testet auch nichts an ihm.
    """
    try:
        import app  # noqa: F401
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _flask_konfiguration_isolieren():
    """
    Stellt app.config nach JEDEM Test wieder her.

    WARUM ES DAS BRAUCHT
    --------------------
    Sechs Testdateien setzten WTF_CSRF_ENABLED auf False und stellten es
    nie zurueck - alle auf demselben modulglobalen Flask-Objekt:

        test_auth.py, test_audit_hardening.py, test_email_verification.py,
        test_password_reset_token.py, test_privacy_and_deletion.py,
        test_security_hardening.py

    Alle sechs haengen an der postgres_db-Fixture. Lokal laeuft die durch,
    CSRF bleibt danach fuer den Rest der Sitzung aus, und jede spaeter
    laufende Datei erbt das. In der CI ueberspringt postgres_db - der
    Fixturekoerper laeuft nie, CSRF bleibt an, und dieselben POST-Tests
    antworten mit 400 auth.csrfError.

    Damit hing das Ergebnis an der Reihenfolge und an der Verfuegbarkeit
    einer Datenbank. Fuenf Tests fielen in der CI, die lokal gruen waren.

    Diese Sicherung setzt an der Ursache an statt an sechs Symptomen:
    Egal welche Fixture etwas aendert, nach dem Test gilt wieder der
    Ausgangszustand. Kuenftige Fixtures sind automatisch mit abgedeckt.

    Die Produktivlogik bleibt unberuehrt - CSRFProtect ist in app.py
    unveraendert aktiv.

    DAS RELOAD-PROBLEM
    ------------------
    Die erste Fassung hielt eine Referenz auf das config-dict und stellte
    dieses am Ende wieder her. Das reicht nicht: postgres_db ruft
    importlib.reload(app). Danach zeigt sys.modules["app"].app auf ein
    NEUES Flask-Objekt mit einem NEUEN config-dict - die Fixture schrieb
    ihren Stand in das alte, verwaiste dict zurueck, und die Aenderungen
    am neuen leckten weiter.

    Nachgewiesen mit einer Wegwerfprobe: Nach einer Fixture, die ueber
    postgres_db laeuft und CSRF abschaltet, sah der Folgetest weiterhin
    False.

    Deshalb wird das Ziel am ENDE erneut ueber das Modul aufgeloest. Beide
    Objekte entstehen aus derselben app.py; der gesicherte Stand ist der
    der Anwendung vor dem Test und gehoert auch auf ein neu gebautes
    Objekt. Was der Reload aus der Umgebung ableitet - allen voran die
    Datenbank-URL - wird damit ebenfalls zurueckgesetzt, und das ist
    richtig so: Wer die Testdatenbank braucht, geht ueber postgres_db,
    und die laedt ohnehin neu.
    """
    import sys

    app_modul = sys.modules.get("app")
    if app_modul is None or not hasattr(app_modul, "app"):
        yield
        return

    vorher = dict(app_modul.app.config)
    try:
        yield
    finally:
        # Erneut aufloesen statt die alte Referenz zu benutzen.
        aktuelles_modul = sys.modules.get("app")
        if aktuelles_modul is None or not hasattr(aktuelles_modul, "app"):
            return
        konfiguration = aktuelles_modul.app.config
        for schluessel in [k for k in konfiguration if k not in vorher]:
            del konfiguration[schluessel]
        konfiguration.update(vorher)


# ---------------------------------------------------------------------------
# CSRF im Test
# ---------------------------------------------------------------------------

def csrf_token_holen(client, pfad="/"):
    """
    Holt ein echtes CSRF-Token genau so, wie es der Browser tut.

    Die Seite liefert es im Meta-Tag, das Frontend liest es dort aus und
    schickt es als X-CSRFToken mit. Ein Test, der einen POST absetzt, muss
    denselben Weg gehen - sonst prueft er einen Ablauf, den es in der
    Anwendung nicht gibt.
    """
    import re

    seite = client.get(pfad)
    assert seite.status_code == 200, (
        f"{pfad} lieferte {seite.status_code} - ohne Seite kein Token")

    treffer = re.search(r'name="csrf-token" content="([^"]+)"',
                        seite.get_data(as_text=True))
    assert treffer, f"kein CSRF-Token in {pfad}"
    return treffer.group(1)


def mit_csrf(client, pfad="/"):
    """
    Ruestet einen Testclient so aus, dass seine POSTs ein echtes Token tragen.

    WARUM SO UND NICHT ANDERS
    -------------------------
    Die naheliegende Abkuerzung waere WTF_CSRF_ENABLED=False. Genau die
    hat den Fehler erzeugt, den diese Aenderung behebt - und sie haette
    zusaetzlich verdeckt, ob die Route ueberhaupt erreichbar ist.

    Der Schutz bleibt hier vollstaendig scharf: Ein falsches oder
    fehlendes Token wird weiterhin mit 400 abgewiesen. Der Client
    verhaelt sich lediglich wie das echte Frontend.

    Ein ausdruecklich gesetzter Header gewinnt, damit ein Test auch den
    Abweisungsfall pruefen kann.
    """
    token = csrf_token_holen(client, pfad)
    original_post = client.post

    def post(*args, **kwargs):
        kopfzeilen = dict(kwargs.pop("headers", None) or {})
        kopfzeilen.setdefault("X-CSRFToken", token)
        return original_post(*args, headers=kopfzeilen, **kwargs)

    client.post = post
    return client
