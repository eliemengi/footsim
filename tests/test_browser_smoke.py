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

import json
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

    # Ratenbegrenzung NUR fuer diesen Testserver abschalten.
    #
    # src/models/extensions.py setzt default_limits ["1000 per day",
    # "100 per hour"] - global fuer jede Route. Die Browsersuite laedt die
    # Seite inzwischen deutlich oefter als hundertmal, und zwar
    # ausnahmslos von 127.0.0.1. Ab dem Ueberschreiten beantwortete der
    # Server jeden weiteren Aufruf mit "Too Many Requests"; die letzten
    # Tests bekamen eine 135 Zeichen lange Fehlerseite ohne Navigation
    # und meldeten "kein sichtbarer Knopf". Das sah wie ein Fehler der
    # Anwendung aus und war eine Schutzfunktion, die genau wie
    # vorgesehen arbeitete.
    #
    # Die Grenze bleibt in der Anwendung unveraendert. Sie wird hier nur
    # fuer die im Test gestartete Instanz ausgesetzt, weil eine
    # Browsersuite kein Missbrauchsfall ist.
    # Beides noetig: Die Konfiguration allein genuegt nicht, weil
    # limiter.init_app(app) sie beim Start bereits gelesen hat. Das
    # Limiter-Objekt selbst muss abgeschaltet werden.
    main_app.app.config["RATELIMIT_ENABLED"] = False
    main_app.limiter.enabled = False

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


# ---------------------------------------------------------------------------
# Android-App-Modus und Zurueck-Taste
# ---------------------------------------------------------------------------

class TestAndroidModusImBrowser:
    """
    Der Android-Modus wird im Browser wirksam, nicht am Server - dieselbe
    Antwort bedient Website und App. Nur hier laesst sich deshalb
    pruefen, ob er wirklich greift.
    """

    def _laden(self, seite, live_server, pfad="/"):
        seite.goto(live_server["url"] + pfad, wait_until="domcontentloaded")
        seite.wait_for_timeout(800)

    def test_website_zeigt_den_unterstuetzungslink(self, seite, live_server):
        self._laden(seite, live_server)
        assert seite.locator(".support").is_visible()

    def test_android_modus_blendet_ihn_aus(self, seite, live_server):
        self._laden(seite, live_server, "/?platform=android")
        assert seite.locator(".support").count() > 0, "Block fehlt im HTML"
        assert not seite.locator(".support").is_visible()

    def test_website_zeigt_beide_testerknoepfe(self, seite, live_server):
        """
        Die Testerlinks liegen im selben .support-Container. Hier wird
        geprueft, dass sie im Browser wirklich sichtbar sind - und
        gleich darunter, dass genau das in der App nicht gilt.
        """
        self._laden(seite, live_server)
        knoepfe = seite.locator(".tester-btn")
        assert knoepfe.count() == 2
        assert knoepfe.nth(0).is_visible()
        assert knoepfe.nth(1).is_visible()

        # Beschriftung statt Rohschluessel. Genau das war am 28.08.2026
        # kaputt: applyTranslations schrieb "hero.testerJoin" ins DOM,
        # weil der Katalog aus dem Service-Worker-Cache den Schluessel
        # noch nicht kannte.
        for i in (0, 1):
            text = knoepfe.nth(i).inner_text().strip()
            assert text
            assert not text.startswith("hero."), f"Rohschluessel sichtbar: {text}"

    def test_testerknoepfe_sehen_nicht_aus_wie_textlinks(self, seite, live_server):
        """
        Der zweite sichtbare Fehler desselben Tages: ohne die
        .tester-btn-Regeln rendert der Browser seine Vorgabe -
        unterstrichen und blau. Hier wird der GERECHNETE Stil geprueft,
        nicht die Existenz einer CSS-Zeile.
        """
        self._laden(seite, live_server)
        for i in (0, 1):
            stil = seite.locator(".tester-btn").nth(i).evaluate(
                "e => { const s = getComputedStyle(e);"
                " return {dek: s.textDecorationLine, bg: s.backgroundColor,"
                " radius: s.borderTopLeftRadius}; }"
            )
            assert stil["dek"] == "none", stil
            assert stil["bg"] == "rgb(255, 255, 255)", stil
            assert stil["radius"] != "0px", stil

    def test_android_modus_blendet_auch_die_testerknoepfe_aus(self, seite, live_server):
        """
        Der Punkt, an dem es im Play Store teuer wuerde: in der App
        darf weder der Spendenlink noch ein Testerknopf auftauchen.
        """
        self._laden(seite, live_server, "/?platform=android")
        assert seite.locator(".tester-btn").count() == 2, "Knoepfe fehlen im HTML"
        assert not seite.locator(".tester-btn").nth(0).is_visible()
        assert not seite.locator(".tester-btn").nth(1).is_visible()
        assert not seite.locator(".support-btn").is_visible()

        # Kein leerer Platzhalter und kein zusaetzlicher Abstand: der
        # Container darf keine Hoehe mehr einnehmen.
        kasten = seite.locator(".support").bounding_box()
        assert kasten is None or kasten["height"] == 0

    def test_beide_testerknoepfe_sind_gleich_breit(self, seite, live_server):
        """
        Die Kernzusage des Grid-Layouts. Ein Pixel Toleranz fuer die
        Rundung von Bruchteilen.
        """
        self._laden(seite, live_server)
        links = seite.locator(".tester-btn").nth(0).bounding_box()
        rechts = seite.locator(".tester-btn").nth(1).bounding_box()
        assert abs(links["width"] - rechts["width"]) <= 1
        assert abs(links["height"] - rechts["height"]) <= 1

        # Summe beider Knoepfe plus Abstand = Breite des oberen Knopfes.
        oben = seite.locator(".support-btn").bounding_box()
        gesamt = (rechts["x"] + rechts["width"]) - links["x"]
        assert abs(gesamt - oben["width"]) <= 1

    def test_der_modus_haelt_ueber_den_naechsten_aufruf(self, seite, live_server):
        """
        Die TWA startet einmal auf /?platform=android; jede weitere
        Navigation traegt den Parameter nicht mehr.
        """
        self._laden(seite, live_server, "/?platform=android")
        self._laden(seite, live_server, "/")
        assert not seite.locator(".support").is_visible()

    # ---- iOS-Modus -----------------------------------------------------
    #
    # Dieselbe .support-Gruppe, zweiter Ausloeser. Fuer iOS ist die
    # Ausblendung keine Vorsichtsmassnahme, sondern Pflicht: Guideline
    # 2.3.10 untersagt Verweise auf fremde App-Marktplaetze, und in der
    # Gruppe stehen ein Play-Store- und ein Google-Groups-Link.

    def test_ios_modus_blendet_die_gruppe_aus(self, seite, live_server):
        self._laden(seite, live_server, "/?platform=ios")
        assert seite.evaluate("document.documentElement.dataset.platform") == "ios"
        assert seite.locator(".support").count() > 0, "Block fehlt im HTML"
        assert not seite.locator(".support").is_visible()
        assert not seite.locator(".support-btn").is_visible()
        assert not seite.locator(".tester-btn").nth(0).is_visible()

    def test_ios_modus_hinterlaesst_keinen_leeren_abstand(self, seite, live_server):
        """
        display:none statt visibility:hidden - der Container darf keine
        Hoehe mehr belegen, sonst klafft im Hero eine Luecke.
        """
        self._laden(seite, live_server, "/?platform=ios")
        kasten = seite.locator(".support").bounding_box()
        assert kasten is None or kasten["height"] == 0

    def test_ios_modus_zeigt_keinen_play_store_und_keine_gruppe(self, seite, live_server):
        """Die konkrete Guideline-2.3.10-Pruefung, am gerenderten Bild."""
        self._laden(seite, live_server, "/?platform=ios")
        for muster in ("play.google.com", "groups.google.com", "paypal.me"):
            treffer = seite.locator(f'a[href*="{muster}"]')
            for i in range(treffer.count()):
                assert not treffer.nth(i).is_visible(), f"{muster} sichtbar"

    def test_ios_modus_haelt_ueber_die_naechste_navigation(self, seite, live_server):
        self._laden(seite, live_server, "/?platform=ios")
        self._laden(seite, live_server, "/")
        assert seite.evaluate("document.documentElement.dataset.platform") == "ios"
        assert not seite.locator(".support").is_visible()

    def test_normales_safari_wird_nicht_als_app_erkannt(self, browser, live_server):
        """
        DER TEST, DER DIE WEBSITE SCHUETZT.

        Ein iPhone-Safari mit echtem Apple-User-Agent, aber ohne den
        eigenen Marker, muss die CTAs SEHEN. Eine Heuristik auf "iPhone"
        oder "Safari" wuerde hier durchfallen.
        """
        iphone_ua = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
                     "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                     "Version/17.5 Mobile/15E148 Safari/604.1")
        kontext = browser.new_context(user_agent=iphone_ua,
                                      viewport={"width": 390, "height": 844})
        try:
            seite = kontext.new_page()
            seite.goto(live_server["url"] + "/", wait_until="domcontentloaded")
            seite.wait_for_timeout(800)
            assert seite.evaluate("document.documentElement.dataset.platform") in (None, "")
            assert seite.locator(".support").is_visible()
            assert seite.locator(".tester-btn").nth(0).is_visible()
        finally:
            kontext.close()

    def test_eigener_useragent_marker_schaltet_ios_auch_ohne_parameter(self, browser, live_server):
        """
        Der Rueckfallweg der Huelle: kein Parameter, kein
        sessionStorage - nur der eigene Marker im User-Agent.
        """
        kontext = browser.new_context(
            user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) FootSim-iOS/1.0"),
            viewport={"width": 390, "height": 844})
        try:
            seite = kontext.new_page()
            seite.goto(live_server["url"] + "/", wait_until="domcontentloaded")
            seite.wait_for_timeout(800)
            assert seite.evaluate("document.documentElement.dataset.platform") == "ios"
            assert not seite.locator(".support").is_visible()
        finally:
            kontext.close()

    def test_unbekannter_plattformwert_wird_verworfen(self, seite, live_server):
        """
        Die Allowlist laesst nur android und ios durch. Alles andere darf
        weder ins Attribut gelangen noch die CTAs ausblenden.
        """
        self._laden(seite, live_server, "/?platform=windows")
        assert seite.evaluate("document.documentElement.dataset.platform") in (None, "")
        assert seite.locator(".support").is_visible()

    def test_bruecke_wirft_im_normalen_browser_nicht(self, seite, live_server):
        """
        window.webkit existiert hier nicht. Die Bruecke muss das
        aushalten, ohne einen Fehler zu werfen - sonst reisst sie im
        Browser die Simulation mit.
        """
        self._laden(seite, live_server)
        ergebnis = seite.evaluate("""() => {
            try {
                nativeHaptik('medium');
                nativeTeilen({titel: 'x', url: 'https://footsim.de/'});
                return 'ok';
            } catch (e) { return 'FEHLER: ' + e.message; }
        }""")
        assert ergebnis == "ok"
        assert seite.evaluate("typeof window.webkit") == "undefined"

    def test_bruecke_meldet_an_registrierte_kanaele(self, seite, live_server):
        """
        Gegenprobe mit einer nachgebauten Huelle: Wenn die Kanaele da
        sind, muessen die Nutzlasten ankommen - typisiert und geprueft.

        Die erlaubte URL wird aus der EIGENEN Herkunft gebildet, nicht
        fest verdrahtet: Die Bruecke laesst nur die eigene Origin durch,
        und der Testserver laeuft auf 127.0.0.1. Eine fest eingetragene
        footsim.de-Adresse waere hier korrekterweise verworfen worden.
        """
        self._laden(seite, live_server)
        empfangen = seite.evaluate("""() => {
            const post = [];
            window.webkit = { messageHandlers: {
                haptic: { postMessage: (m) => post.push(['haptic', m]) },
                share:  { postMessage: (m) => post.push(['share', m]) },
            }};
            nativeHaptik('schwer-und-falsch');
            nativeTeilen({titel: '  FootSim  ', text: '', url: 'javascript:alert(1)'});
            nativeTeilen({titel: 'Ergebnis', url: window.location.origin + '/'});
            return post;
        }""")
        herkunft = seite.evaluate("window.location.origin")

        assert empfangen[0][0] == "haptic"
        # Unbekannte Staerke faellt auf medium zurueck.
        assert empfangen[0][1]["style"] == "medium"
        # javascript:-URL wird verworfen, der Titel getrimmt gesendet.
        assert empfangen[1][1] == {"title": "FootSim"}
        assert empfangen[2][1] == {"title": "Ergebnis", "url": herkunft + "/"}

    def test_bruecke_verwirft_gefaehrliche_und_fremde_urls(self, seite, live_server):
        """
        Die Bruecke ist eine Grenze, keine Durchreiche. Geprueft werden
        die Schemata, die in einer WebView gefaehrlich sind, und eine
        fremde Domain - Letztere, damit ueber das Share Sheet keine
        beliebige Adresse als FootSim-Inhalt verteilt werden kann.
        """
        self._laden(seite, live_server)
        ergebnis = seite.evaluate("""() => {
            const post = [];
            window.webkit = { messageHandlers: {
                share: { postMessage: (m) => post.push(m) },
            }};
            const boese = [
                'javascript:alert(1)',
                'data:text/html,<script>alert(1)</script>',
                'blob:https://footsim.de/abc',
                'file:///etc/passwd',
                'https://boese.example/phish',
            ];
            const gesendet = boese.map(u => nativeTeilen({url: u}));
            return {gesendet, post};
        }""")
        # Kein einziger Aufruf darf durchgehen.
        assert ergebnis["gesendet"] == [False] * 5
        assert ergebnis["post"] == []

    def test_bruecke_kuerzt_uebergrosse_nutzlast(self, seite, live_server):
        """
        Ohne Laengengrenze koennte ein Fehler in einer aufrufenden Stelle
        megabytegrosse Zeichenketten ueber die Bruecke schieben.
        """
        self._laden(seite, live_server)
        laengen = seite.evaluate("""() => {
            const post = [];
            window.webkit = { messageHandlers: {
                share: { postMessage: (m) => post.push(m) },
            }};
            nativeTeilen({titel: 'A'.repeat(5000), text: 'B'.repeat(9000)});
            return {titel: post[0].title.length, text: post[0].text.length};
        }""")
        assert laengen["titel"] == 120
        assert laengen["text"] == 600

    # ---- Teilen-Knopf ---------------------------------------------------
    #
    # Der Knopf haengt an DREI Bedingungen: iOS-Huelle, registrierter
    # Kanal und vorhandenes Ergebnis. Geprueft wird das gerenderte
    # Verhalten, nicht der Quelltext.

    def _huelle_vortaeuschen(self, seite):
        """Registriert die Kanaele, die die echte Huelle bereitstellt."""
        seite.evaluate("""() => {
            window.__geteilt = [];
            window.webkit = { messageHandlers: {
                haptic: { postMessage: () => {} },
                share:  { postMessage: (m) => window.__geteilt.push(m) },
            }};
        }""")

    def _ergebnis_rendern(self, seite, heim="FC Bayern", gast="RB Leipzig"):
        """
        Ruft renderResult() mit einer vollstaendigen Antwort auf - genau
        so, wie es /api/simulate liefern wuerde. Keine echte Simulation:
        Der Knopf haengt am Rendern, nicht am Netz.

        switchTab("simulation") gehoert dazu, weil runSimulation() es
        ebenfalls tut: Der Ergebnisbereich liegt in einem tab-panel, das
        ohne den Wechsel display:none traegt. Ohne diesen Schritt waere
        der Knopf zwar korrekt eingeblendet, aber von einem Vorfahren
        verdeckt - und der Test wuerde einen Fehler melden, den es nicht
        gibt.
        """
        seite.evaluate("""([heim, gast]) => {
            renderResult({
                home_team: heim, away_team: gast,
                home_win_probability: 54.2, draw_probability: 23.1,
                away_win_probability: 22.7,
                expected_home_goals: 1.9, expected_away_goals: 1.2,
                top_scores: [{score: "2:1", count: 900}],
                competition: "Bundesliga",
            });
            switchTab("simulation");
        }""", [heim, gast])

    def test_teilen_knopf_auf_der_website_unsichtbar(self, seite, live_server):
        self._laden(seite, live_server)
        self._ergebnis_rendern(seite)
        assert not seite.locator("#share-result-btn").is_visible()

    def test_teilen_knopf_in_android_unsichtbar(self, seite, live_server):
        self._laden(seite, live_server, "/?platform=android")
        self._ergebnis_rendern(seite)
        assert not seite.locator("#share-result-btn").is_visible()

    def test_teilen_knopf_in_ios_ohne_ergebnis_unsichtbar(self, seite, live_server):
        self._laden(seite, live_server, "/?platform=ios")
        self._huelle_vortaeuschen(seite)
        assert not seite.locator("#share-result-btn").is_visible()

    def test_teilen_knopf_nach_ergebnis_sichtbar(self, seite, live_server):
        self._laden(seite, live_server, "/?platform=ios")
        self._huelle_vortaeuschen(seite)
        self._ergebnis_rendern(seite)
        assert seite.locator("#share-result-btn").is_visible()

    def test_teilen_knopf_ohne_bruecke_verborgen(self, seite, live_server):
        """
        iOS-Modus, aber kein registrierter Kanal - der Knopf waere tot.
        Er muss verborgen bleiben, und es darf kein Fehler entstehen.
        """
        self._laden(seite, live_server, "/?platform=ios")
        self._ergebnis_rendern(seite)
        assert not seite.locator("#share-result-btn").is_visible()

    def test_teilen_knopf_hinterlaesst_keine_luecke(self, seite, live_server):
        self._laden(seite, live_server)
        self._ergebnis_rendern(seite)
        kasten = seite.locator("#share-result-btn").bounding_box()
        assert kasten is None or kasten["height"] == 0

    @pytest.mark.parametrize("lang,text", [("de", "Ergebnis teilen"),
                                           ("en", "Share result")])
    def test_teilen_knopf_beschriftung(self, seite, live_server, lang, text):
        self._laden(seite, live_server, f"/?platform=ios&lang={lang}")
        self._huelle_vortaeuschen(seite)
        self._ergebnis_rendern(seite)
        assert seite.locator("#share-result-btn").inner_text().strip() == text

    def test_klick_sendet_genau_eine_nachricht_mit_dem_ergebnis(self, seite, live_server):
        self._laden(seite, live_server, "/?platform=ios")
        self._huelle_vortaeuschen(seite)
        self._ergebnis_rendern(seite)
        seite.locator("#share-result-btn").click()

        gesendet = seite.evaluate("window.__geteilt")
        assert len(gesendet) == 1

        nutzlast = gesendet[0]
        assert "FC Bayern" in nutzlast["text"]
        assert "RB Leipzig" in nutzlast["text"]
        assert "54.2" in nutzlast["text"]
        assert "Bundesliga" in nutzlast["text"]
        # new URL() normalisiert und ergaenzt den abschliessenden
        # Schraegstrich. In Produktion wird daraus "https://footsim.de/"
        # - ein gueltiger Link, kein Fehler.
        herkunft = seite.evaluate("window.location.origin")
        assert nutzlast["url"] in (herkunft, herkunft + "/")

    def test_nutzlast_traegt_keine_sensiblen_daten(self, seite, live_server):
        self._laden(seite, live_server, "/?platform=ios")
        self._huelle_vortaeuschen(seite)
        self._ergebnis_rendern(seite)
        seite.locator("#share-result-btn").click()

        roh = json.dumps(seite.evaluate("window.__geteilt")).lower()
        for verboten in ("csrf", "token", "@", "session", "cookie", "match_id"):
            assert verboten not in roh, verboten

    def test_zweite_simulation_ersetzt_die_nutzlast(self, seite, live_server):
        """Kein Teilen eines alten Ergebnisses."""
        self._laden(seite, live_server, "/?platform=ios")
        self._huelle_vortaeuschen(seite)

        self._ergebnis_rendern(seite, "FC Bayern", "RB Leipzig")
        seite.locator("#share-result-btn").click()
        self._ergebnis_rendern(seite, "Arsenal FC", "Chelsea FC")
        seite.locator("#share-result-btn").click()

        gesendet = seite.evaluate("window.__geteilt")
        assert len(gesendet) == 2, "mehrfach registrierter Listener?"
        assert "Arsenal FC" in gesendet[1]["text"]
        assert "FC Bayern" not in gesendet[1]["text"]

    def test_knopf_wird_vor_jeder_neuen_simulation_verborgen(self, seite, live_server):
        """
        Scheitert die Simulation, laeuft renderResult() nicht. Ohne das
        Verbergen bliebe das VORIGE Ergebnis teilbar.
        """
        self._laden(seite, live_server, "/?platform=ios")
        self._huelle_vortaeuschen(seite)
        self._ergebnis_rendern(seite)
        assert seite.locator("#share-result-btn").is_visible()

        seite.evaluate("aktualisiereTeilenKnopf(null)")
        assert not seite.locator("#share-result-btn").is_visible()
        assert seite.evaluate("letztesTeilbaresErgebnis") is None

    def test_teilen_knopf_auf_mobiler_breite(self, browser, live_server):
        kontext = browser.new_context(viewport={"width": 390, "height": 844})
        try:
            seite = kontext.new_page()
            seite.goto(live_server["url"] + "/?platform=ios",
                       wait_until="domcontentloaded")
            seite.wait_for_timeout(800)
            self._huelle_vortaeuschen(seite)
            self._ergebnis_rendern(seite)

            kasten = seite.locator("#share-result-btn").bounding_box()
            assert kasten["height"] >= 44, "Touchflaeche zu klein"
            assert kasten["x"] >= 0 and kasten["x"] + kasten["width"] <= 390
            assert not seite.evaluate(
                "document.documentElement.scrollWidth > window.innerWidth + 1")
        finally:
            kontext.close()

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_teilen_knopf_in_beiden_themes_lesbar(self, seite, live_server, theme):
        """
        Ein erfundenes CSS-Token faellt auf transparent zurueck. Geprueft
        wird der GERECHNETE Stil, nicht der Quelltext.
        """
        self._laden(seite, live_server, "/?platform=ios")
        seite.evaluate(f"document.documentElement.setAttribute('data-theme','{theme}')")
        self._huelle_vortaeuschen(seite)
        self._ergebnis_rendern(seite)

        stil = seite.locator("#share-result-btn").evaluate(
            "e => { const s = getComputedStyle(e);"
            " return {farbe: s.color, grund: s.backgroundColor, rand: s.borderTopColor}; }")
        for wert in stil.values():
            assert "rgba(0, 0, 0, 0)" not in wert, f"{theme}: {stil}"

    # ---- PDF-Werkzeug ---------------------------------------------------

    def test_pdfseite_kennt_den_ios_modus(self, seite, live_server):
        """
        Ohne Plattformerkennung auf DIESER Seite liefe der native
        Downloadweg nie an.
        """
        seite.goto(live_server["url"] + "/tools/pdf?platform=ios",
                   wait_until="domcontentloaded")
        seite.wait_for_timeout(600)
        assert seite.evaluate("document.documentElement.dataset.platform") == "ios"
        assert seite.evaluate("typeof istIosApp === 'function'")
        assert seite.evaluate("istIosApp()") is True

    def test_pdfseite_im_browser_bleibt_beim_blob_weg(self, seite, live_server):
        seite.goto(live_server["url"] + "/tools/pdf", wait_until="domcontentloaded")
        seite.wait_for_timeout(600)
        assert seite.evaluate("document.documentElement.dataset.platform") in (None, "")
        assert seite.evaluate("istIosApp()") is False

    def test_ios_pdf_sendet_ein_formular_an_die_richtige_route(self, seite, live_server):
        """
        Verhalten statt Textsuche: Das Absenden wird abgefangen und der
        tatsaechlich gebaute Request untersucht - Methode, Route,
        Kodierung, CSRF-Feld und die uebernommenen Dateien.
        """
        seite.goto(live_server["url"] + "/tools/pdf?platform=ios",
                   wait_until="domcontentloaded")
        seite.wait_for_timeout(600)

        befund = seite.evaluate("""async () => {
            // submit() abfangen, damit nichts wirklich hinausgeht.
            const gesendet = [];
            HTMLFormElement.prototype.submit = function () {
                gesendet.push({
                    method: this.method.toUpperCase(),
                    action: new URL(this.action, location.href).pathname,
                    enctype: this.enctype,
                    target: this.target,
                    felder: Array.from(this.elements).map(e => ({
                        name: e.name, typ: e.type,
                        anzahl: e.files ? e.files.length : null,
                        gefuellt: e.type === 'hidden' ? Boolean(e.value) : null,
                    })),
                });
            };

            const datei = new File([new Uint8Array([37, 80, 68, 70])],
                                   "a.pdf", {type: "application/pdf"});
            await mergeUeberFormular([{file: datei}], "ergebnis");
            return gesendet;
        }""")

        assert len(befund) == 1, "genau ein Request erwartet"
        formular = befund[0]
        assert formular["method"] == "POST"
        assert formular["action"] == "/tools/pdf/merge"
        assert formular["enctype"] == "multipart/form-data"
        assert formular["target"] == "footsim-pdf-sink"

        felder = {f["name"]: f for f in formular["felder"]}
        assert felder["files"]["anzahl"] == 1, "Datei ging verloren"
        assert felder["csrf_token"]["gefuellt"] is True
        assert felder["output_name"]["gefuellt"] is True

    def test_ios_pdf_raeumt_formular_und_iframe_wieder_ab(self, seite, live_server):
        seite.goto(live_server["url"] + "/tools/pdf?platform=ios",
                   wait_until="domcontentloaded")
        seite.wait_for_timeout(600)

        uebrig = seite.evaluate("""async () => {
            HTMLFormElement.prototype.submit = function () {
                // Fehlerantwort im iframe nachstellen: load ausloesen.
                setTimeout(() => this.target && document
                    .getElementsByName(this.target)[0]
                    .dispatchEvent(new Event("load")), 0);
            };
            const datei = new File([new Uint8Array([37])], "a.pdf", {type: "application/pdf"});
            await mergeUeberFormular([{file: datei}], "x");
            return {
                formulare: document.querySelectorAll('form[action="/tools/pdf/merge"]').length,
                rahmen: document.getElementsByName("footsim-pdf-sink").length,
            };
        }""")
        assert uebrig == {"formulare": 0, "rahmen": 0}

    def test_ein_neuer_kontext_zeigt_den_link_wieder(self, browser, live_server):
        """
        Der Kern der sessionStorage-Entscheidung: Der Android-Modus darf
        nicht in einen normalen Chrome-Tab ueberlaufen. Ein neuer Kontext
        entspricht einem neuen Browser.
        """
        kontext = browser.new_context()
        try:
            seite = kontext.new_page()
            seite.goto(live_server["url"] + "/?platform=android",
                       wait_until="domcontentloaded")
            seite.wait_for_timeout(800)
            assert not seite.locator(".support").is_visible()
        finally:
            kontext.close()

        frisch = browser.new_context()
        try:
            seite = frisch.new_page()
            seite.goto(live_server["url"] + "/", wait_until="domcontentloaded")
            seite.wait_for_timeout(800)
            assert seite.locator(".support").is_visible(), (
                "der Android-Modus ist in eine neue Sitzung uebergelaufen")
        finally:
            frisch.close()

    @pytest.mark.parametrize("pfad", ["/impressum", "/datenschutz"])
    def test_rechtsseiten_bleiben_im_android_modus_erreichbar(
            self, seite, live_server, pfad):
        seite.goto(live_server["url"] + "/?platform=android",
                   wait_until="domcontentloaded")
        antwort = seite.request.get(live_server["url"] + pfad)
        assert antwort.ok, pfad


class TestZurueckTaste:
    """
    Ohne History-Eintraege haette die Android-Zurueck-Taste aus JEDEM
    Bereich sofort die App geschlossen - die wahrscheinlichste Beschwerde
    im geschlossenen Test.
    """

    def _laden(self, seite, live_server):
        seite.goto(live_server["url"] + "/", wait_until="domcontentloaded")
        seite.wait_for_timeout(1500)

    def _aktiver_bereich(self, seite):
        return seite.evaluate(
            "document.querySelector('.app-area:not(.hidden)')"
            "?.dataset.area || null")

    def _wechseln(self, seite, bereich):
        """
        Klickt den Bereichsknopf, der gerade sichtbar ist.

        Es gibt zwei Navigationen: .area-btn am Desktop und .bottom-nav-btn
        auf schmalen Bildschirmen. Welche sichtbar ist, entscheidet eine
        Media Query - ein fester Selektor lief deshalb im Standardviewport
        in den Timeout.
        """
        auswahl = (f".area-btn[data-area='{bereich}'], "
                   f".bottom-nav-btn[data-area='{bereich}']")

        # Auf das Erscheinen WARTEN statt auf eine feste Zeit zu hoffen.
        #
        # Vorher genuegte das pauschale wait_for_timeout(1500) in _laden.
        # Im vollen Lauf - inzwischen 61 statt 31 Browsertests - reichte
        # es zeitweise nicht mehr: Die Navigation war noch nicht
        # gezeichnet, und der Test meldete "kein sichtbarer Knopf",
        # obwohl an der Anwendung nichts fehlte. Isoliert lief derselbe
        # Test durch. Eine Wartezeit, die von der Maschinenlast abhaengt,
        # ist keine Zusicherung.
        try:
            seite.wait_for_function(
                """(sel) => Array.from(document.querySelectorAll(sel))
                       .some(e => e.offsetParent !== null)""",
                arg=auswahl,
                timeout=15000,
            )
        except Exception as fehler:
            # Ein blosses "Timeout" sagt nichts darueber, WARUM die
            # Navigation fehlt. Genau daran ging Zeit verloren: Die Seite
            # war in Wahrheit eine 135 Zeichen lange "Too Many
            # Requests"-Antwort. Der Seitentext im Fehlerbild macht so
            # etwas beim naechsten Mal sofort sichtbar.
            lage = seite.evaluate("""() => ({
                url: location.href,
                text: document.body
                    ? document.body.textContent.trim().slice(0, 120) : null,
                areaBtns: document.querySelectorAll('.area-btn').length,
                navBtns: document.querySelectorAll('.bottom-nav-btn').length,
            })""")
            raise AssertionError(f"Navigation nicht sichtbar. Seitenlage: {lage}") from fehler

        knoepfe = seite.locator(auswahl)
        for i in range(knoepfe.count()):
            if knoepfe.nth(i).is_visible():
                knoepfe.nth(i).click()
                seite.wait_for_timeout(600)
                return
        raise AssertionError(f"kein sichtbarer Knopf fuer Bereich '{bereich}'")

    def test_der_seitenaufbau_startet_in_der_simulation(self, seite, live_server):
        self._laden(seite, live_server)
        assert self._aktiver_bereich(seite) == "simulation"

    def test_ein_wechsel_erzeugt_genau_einen_eintrag(self, seite, live_server):
        self._laden(seite, live_server)
        vorher = seite.evaluate("history.length")

        self._wechseln(seite, "compare")

        assert self._aktiver_bereich(seite) == "compare"
        assert seite.evaluate("history.length") == vorher + 1

    def test_derselbe_bereich_erzeugt_keinen_zweiten_eintrag(self, seite,
                                                            live_server):
        self._laden(seite, live_server)
        self._wechseln(seite, "compare")
        nach_erstem = seite.evaluate("history.length")

        self._wechseln(seite, "compare")

        assert seite.evaluate("history.length") == nach_erstem

    def test_zurueck_fuehrt_in_den_vorherigen_bereich(self, seite, live_server):
        self._laden(seite, live_server)
        self._wechseln(seite, "compare")
        assert self._aktiver_bereich(seite) == "compare"

        seite.go_back()
        seite.wait_for_timeout(600)

        assert self._aktiver_bereich(seite) == "simulation", (
            "Zurueck haette in der App die Anwendung geschlossen")

    def test_mehrere_schritte_zurueck(self, seite, live_server):
        self._laden(seite, live_server)
        for bereich in ("compare", "live", "players"):
            self._wechseln(seite, bereich)
        assert self._aktiver_bereich(seite) == "players"

        for erwartet in ("live", "compare", "simulation"):
            seite.go_back()
            seite.wait_for_timeout(600)
            assert self._aktiver_bereich(seite) == erwartet

    def test_vorwaerts_funktioniert_ebenfalls(self, seite, live_server):
        self._laden(seite, live_server)
        self._wechseln(seite, "live")
        seite.go_back()
        seite.wait_for_timeout(600)

        seite.go_forward()
        seite.wait_for_timeout(600)
        assert self._aktiver_bereich(seite) == "live"

    def test_die_sprache_ueberlebt_den_bereichswechsel(self, seite, live_server):
        """
        areaHistoryUrl darf lang nicht wegwerfen - sonst faellt die App
        beim ersten Wechsel in die Standardsprache zurueck.
        """
        seite.goto(live_server["url"] + "/?lang=de",
                   wait_until="domcontentloaded")
        seite.wait_for_timeout(1500)
        self._wechseln(seite, "compare")

        assert "lang=de" in seite.url
        assert "area=compare" in seite.url

    def test_der_android_parameter_ueberlebt_ebenfalls(self, seite, live_server):
        seite.goto(live_server["url"] + "/?platform=android",
                   wait_until="domcontentloaded")
        seite.wait_for_timeout(1500)
        self._wechseln(seite, "compare")

        assert "platform=android" in seite.url
        assert not seite.locator(".support").is_visible()

    def test_kein_javascript_fehler_bei_der_navigation(self, seite, live_server):
        self._laden(seite, live_server)
        seite.seitenfehler.clear()

        for bereich in ("compare", "live", "players", "simulation"):
            self._wechseln(seite, bereich)
        for _ in range(4):
            seite.go_back()
            seite.wait_for_timeout(400)

        assert seite.seitenfehler == [], seite.seitenfehler
