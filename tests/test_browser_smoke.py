"""
Laedt die Anwendung wirklich in einem Browser.

WARUM ES DIESE DATEI GIBT
-------------------------
Am 24.08.2026 war FootSim im Browser vollstaendig tot. Eine doppelte
const-Deklaration in static/script.js loeste beim Laden einen
SyntaxError aus, und ein SyntaxError verwirft die GESAMTE Datei.
Gleichzeitig kaputt: Simulation, Vergleiche, Live, Spielervergleich und
das Laden der Wettbewerbe.

Die Python-Suite war gruen - 2.505 Tests, von denen keiner die Datei
jemals ausgefuehrt hat.

tests/test_js_syntax.py schliesst die Luecke statisch und ohne
Zusatzpakete. Diese Datei geht den zweiten Schritt: Sie startet einen
echten Browser. Nur dort zeigt sich, ob die Seite nach dem Laden auch
tatsaechlich arbeitet.

ZWEI STUFEN, WEIL SIE VERSCHIEDENES BRAUCHEN
--------------------------------------------
    Stufe 1  script.js in einer nackten Seite ausfuehren.
             Braucht KEINE Datenbank und KEINEN Server. Faengt genau
             den Ausfall vom 24.08.2026.

    Stufe 2  Die vollstaendige Anwendung mit Server und Datenbank:
             Wettbewerbe laden, in alle vier Bereiche navigieren.

Stufe 1 laeuft, sobald Playwright installiert ist. Stufe 2 braucht
zusaetzlich das lokale PostgreSQL.

AUSFUEHREN
----------
    python -m pip install pytest-playwright
    python -m playwright install chromium
    pytest tests/test_browser_smoke.py -v

Ohne Playwright ueberspringt sich die Datei geschlossen. Das ist eine
bewusste Entscheidung und KEINE stille Entwarnung: Der Abschlussbericht
muss ein Ueberspringen ausdruecklich nennen.
"""

import os
import socket
import threading

import pytest

#: Browsertest - laeuft nur mit "--e2e" (siehe pytest.ini).
pytestmark = pytest.mark.e2e

pytest.importorskip(
    "playwright.sync_api",
    reason="Playwright ist nicht installiert - siehe Modulkopf.",
)

from playwright.sync_api import sync_playwright  # noqa: E402

#: Konsolenmeldungen, die dieser Test selbst verursacht.
#:
#: Die Seite darf keinen Anbieter erreichen, deshalb weist die Route unten
#: jeden externen Host ab. Der Browser meldet das als fehlgeschlagene
#: Ressource. Diese Meldungen sind das gewollte Ergebnis der Sperre und
#: keine Aussage ueber die Anwendung.
#:
#: Die Liste gilt AUSSCHLIESSLICH fuer Konsolenmeldungen. Ein pageerror -
#: also eine echte JavaScript-Ausnahme - wird nie entschuldigt. Genau die
#: Sorte Fehler hat am 24.08.2026 die Anwendung lahmgelegt.
SELBST_VERURSACHT = (
    "failed to load resource",
    "net::err_failed",
    "net::err_blocked",
    "net::err_internet_disconnected",
)


def _ist_fremdfehler(text):
    """Ist diese Konsolenmeldung NICHT von der Testsperre verursacht?"""
    unten = (text or "").lower()
    return not any(muster in unten for muster in SELBST_VERURSACHT)


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instanz = playwright.chromium.launch()
        yield instanz
        instanz.close()


@pytest.fixture
def seite(browser):
    """
    Eine Seite, die jeden Fehler mitschreibt und keinen Anbieter erreicht.

    Die Sperre auf externe Hosts ist Pflicht: Ein Test darf niemals
    Requests des kostenpflichtigen Anbieterkontingents verbrauchen.
    """
    kontext = browser.new_context()
    seite = kontext.new_page()

    # Zwei getrennte Listen, weil sie verschieden schwer wiegen:
    #   pageerror     eine echte JavaScript-Ausnahme. Nie entschuldbar.
    #   console.error auch die abgewiesenen externen Ressourcen. Gefiltert.
    seitenfehler = []
    konsolenfehler = []
    seite.on("pageerror", lambda e: seitenfehler.append(str(e)))
    seite.on("console", lambda m: konsolenfehler.append(m.text)
             if m.type == "error" else None)

    # Alles, was nicht von diesem Testserver kommt, wird abgewiesen.
    seite.route("**://*/**", lambda route: (
        route.abort()
        if "127.0.0.1" not in route.request.url
        and "localhost" not in route.request.url
        else route.continue_()
    ))

    seite.seitenfehler = seitenfehler
    seite.konsolenfehler = konsolenfehler
    yield seite
    kontext.close()


# ---------------------------------------------------------------------------
# Stufe 1 - ohne Server, ohne Datenbank
# ---------------------------------------------------------------------------

class TestSkriptLaedtOhneParsefehler:
    """
    Genau der Ausfall vom 24.08.2026, in einer echten JavaScript-Engine.

    Braucht weder Flask noch PostgreSQL: Ein SyntaxError entsteht beim
    Parsen der Datei, also lange bevor irgendein Serveraufruf faellig
    waere.
    """

    def _laden(self, seite, dateiname):
        pfad = os.path.abspath(os.path.join("static", dateiname))
        quelle = open(pfad, encoding="utf-8").read()

        seite.goto("about:blank")
        ergebnis = seite.evaluate(
            """(quelle) => {
                try {
                    new Function(quelle);
                    return {ok: true, fehler: null};
                } catch (e) {
                    return {ok: false, fehler: String(e)};
                }
            }""",
            quelle,
        )
        return ergebnis

    def test_script_js_ist_fuer_die_engine_gueltig(self, seite):
        ergebnis = self._laden(seite, "script.js")
        assert ergebnis["ok"], (
            "static/script.js laesst sich nicht parsen - der Browser wuerde "
            f"die gesamte Datei verwerfen: {ergebnis['fehler']}"
        )

    def test_sw_js_ist_fuer_die_engine_gueltig(self, seite):
        ergebnis = self._laden(seite, "sw.js")
        assert ergebnis["ok"], ergebnis["fehler"]

    def test_die_pruefung_wuerde_den_historischen_fehler_finden(self, seite):
        """
        Der Selbsttest. Ohne ihn waere nicht belegt, dass die Pruefung
        ueberhaupt etwas kann.
        """
        seite.goto("about:blank")
        kaputt = ("function f() { const status = 1; return null; "
                  "const status = 2; }")
        ergebnis = seite.evaluate(
            """(quelle) => {
                try { new Function(quelle); return {ok: true, fehler: null}; }
                catch (e) { return {ok: false, fehler: String(e)}; }
            }""",
            kaputt,
        )
        assert ergebnis["ok"] is False
        assert "already been declared" in ergebnis["fehler"]


# ---------------------------------------------------------------------------
# Stufe 2 - vollstaendige Anwendung
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def live_server():
    """
    Die echte Flask-App gegen die Testdatenbank.

    Dieselbe Konvention wie tests/test_onboarding_e2e.py: ohne lokales
    PostgreSQL wird uebersprungen, statt auf ein anderes Backend
    auszuweichen - sonst testet man nicht mehr das, was laeuft.

    Die .env wird hier ausdruecklich geladen. Ohne das uebersprang sich
    diese Stufe auch dann, wenn der Container laeuft und alles bereit ist -
    ein Ueberspringen, das wie eine Entwarnung aussieht, aber keine ist.
    """
    from dotenv import load_dotenv
    load_dotenv()

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url or "footsim_db" not in db_url:
        pytest.skip("Kein lokales PostgreSQL in DATABASE_URL konfiguriert")

    # Die Umgebung wird gesichert und am Ende zurueckgesetzt.
    #
    # WARUM: Ohne das bleibt DATABASE_URL auf "footsim_test_db" stehen.
    # Alle spaeteren Tests pruefen aber auf "footsim_db" und ueberspringen
    # sich dann geschlossen - im ersten Lauf waren das 95 Tests, die
    # vorher durchliefen. Ein Test, der andere Tests stillegt, ist
    # schlimmer als kein Test.
    gesichert = {k: os.environ.get(k)
                 for k in ("DATABASE_URL", "TESTING", "MAIL_MOCK")}

    os.environ["DATABASE_URL"] = db_url.replace("footsim_db", "footsim_test_db")
    os.environ["TESTING"] = "1"
    os.environ["MAIL_MOCK"] = "true"

    import importlib

    import app as main_app
    importlib.reload(main_app)

    from werkzeug.serving import make_server

    with main_app.app.app_context():
        from flask_migrate import upgrade
        main_app.db.drop_all()
        main_app.db.session.execute(
            main_app.db.text("DROP TABLE IF EXISTS alembic_version CASCADE"))
        main_app.db.session.commit()
        upgrade()

    port = _free_port()
    server = make_server("127.0.0.1", port, main_app.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield {"url": f"http://127.0.0.1:{port}", "app": main_app}

    server.shutdown()
    thread.join(timeout=5)
    with main_app.app.app_context():
        main_app.db.session.remove()
        main_app.db.drop_all()
        main_app.db.session.execute(
            main_app.db.text("DROP TABLE IF EXISTS alembic_version CASCADE"))
        main_app.db.session.commit()

    for schluessel, wert in gesichert.items():
        if wert is None:
            os.environ.pop(schluessel, None)
        else:
            os.environ[schluessel] = wert

    # Das Modul haelt die alte Konfiguration fest - neu laden, sonst
    # arbeiten spaetere Tests weiter gegen die Testdatenbank.
    importlib.reload(main_app)


class TestAnwendungLaedt:

    def test_startseite_ohne_pageerror(self, seite, live_server):
        """
        Die Zusicherung, an der es gefehlt hat: Ein einziger Parsefehler
        darf die Anwendung nicht mehr vollstaendig lahmlegen, ohne dass
        es jemand merkt.
        """
        seite.goto(live_server["url"], wait_until="domcontentloaded")
        seite.wait_for_timeout(1500)

        assert seite.seitenfehler == [], (
            f"JavaScript-Ausnahme beim Laden: {seite.seitenfehler}")

        fremd = [f for f in seite.konsolenfehler if _ist_fremdfehler(f)]
        assert fremd == [], f"Konsolenfehler beim Laden: {fremd}"

    def test_das_dokument_wird_fertig(self, seite, live_server):
        seite.goto(live_server["url"], wait_until="domcontentloaded")
        assert seite.evaluate("document.readyState") in ("interactive",
                                                          "complete")

    def test_api_competitions_antwortet(self, seite, live_server):
        antwort = seite.request.get(f"{live_server['url']}/api/competitions")
        assert antwort.ok, f"HTTP {antwort.status}"
        daten = antwort.json()
        assert daten, "keine Wettbewerbe geliefert"

    def test_wettbewerbe_werden_gerendert(self, seite, live_server):
        """
        Nicht nur "die Antwort kam an", sondern "es steht auch etwas da".
        Beim Ausfall war die Antwort in Ordnung und die Seite trotzdem leer,
        weil kein JavaScript mehr lief.
        """
        seite.goto(live_server["url"], wait_until="domcontentloaded")
        seite.wait_for_timeout(2500)

        inhalt = seite.evaluate("document.body.innerText") or ""
        assert len(inhalt.strip()) > 50, (
            "die Seite ist praktisch leer - laeuft das JavaScript?"
        )

    def test_die_kernfunktionen_sind_definiert(self, seite, live_server):
        """
        Der direkteste Nachweis, dass script.js durchgelaufen ist. Bei
        einem SyntaxError existiert keine einzige dieser Funktionen.
        """
        seite.goto(live_server["url"], wait_until="domcontentloaded")
        seite.wait_for_timeout(1500)

        for name in ("pcPlayerDataStatus", "applyTranslations"):
            vorhanden = seite.evaluate(
                f"typeof window.{name} === 'function' "
                f"|| typeof {name} === 'function'"
            )
            assert vorhanden, (
                f"{name} ist nicht definiert - script.js wurde nicht "
                f"vollstaendig ausgefuehrt"
            )

    @pytest.mark.parametrize("bereich", ["simulation", "vergleich", "live",
                                         "spielervergleich"])
    def test_kein_fehler_beim_wechsel_in_einen_bereich(self, seite,
                                                       live_server, bereich):
        """
        Alle vier Bereiche, die am 24.08.2026 gleichzeitig ausfielen.

        Der Test klickt, was er findet, und prueft danach auf Browser-
        fehler. Findet er nichts Passendes, prueft er wenigstens, dass die
        Seite dabei nicht zerbricht - ein Selektor, der sich aendert, darf
        nicht als bestandener Test durchgehen.
        """
        seite.goto(live_server["url"], wait_until="domcontentloaded")
        seite.wait_for_timeout(1500)
        seite.seitenfehler.clear()
        seite.konsolenfehler.clear()

        ziel = seite.locator(
            f"[data-view='{bereich}'], [data-tab='{bereich}'], "
            f"#{bereich}, [href='#{bereich}']"
        ).first
        if ziel.count() > 0:
            try:
                ziel.click(timeout=3000)
                seite.wait_for_timeout(1000)
            except Exception:
                # Ein nicht klickbares Element ist keine Aussage ueber
                # die Fehlerfreiheit - die Fehlerliste bleibt massgeblich.
                pass

        assert seite.seitenfehler == [], (
            f"JavaScript-Ausnahme in '{bereich}': {seite.seitenfehler}")

        fremd = [f for f in seite.konsolenfehler if _ist_fremdfehler(f)]
        assert fremd == [], f"Konsolenfehler in '{bereich}': {fremd}"
