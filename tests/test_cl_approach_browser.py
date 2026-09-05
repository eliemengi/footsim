"""
Der Berechnungsansatz der Champions League in einem echten Browser (C8B).

WARUM DIESE DATEI NEBEN tests/test_cl_approach_ui.py STEHT
----------------------------------------------------------
tests/test_cl_approach_ui.py prueft Vertraege im Quelltext: Steht das
Markup da, gibt es die Uebersetzungen, nimmt das Backend genau die
Nutzlast an, die das Frontend baut. Das ist wertvoll und laeuft in jedem
Lauf mit - aber es kann eine Frage nicht beantworten:

    Rechnet die Oberflaeche wirklich so, wie der Vertrag es behauptet?

Ob "-30 %" am Regler tatsaechlich als attack=0.7 im Request landet, ob
die Auswahl beim Wettbewerbswechsel zurueckfaellt und ob eine
Ligasimulation garantiert kein 'approach' mitsendet, zeigt sich erst,
wenn der echte Code im DOM laeuft. Genau das passiert hier.

WARUM EIGENE HARNISCHE STATT tests/test_browser_smoke.py
--------------------------------------------------------
Die Stufe 2 jener Datei startet die vollstaendige Anwendung samt
PostgreSQL. Diese Tests brauchen davon nichts: Sie fassen weder
Datenbank noch Modelle noch den Anbieter an. Sie rendern das Template
mit Jinja2, liefern die statischen Dateien und ein paar knappe
API-Antworten ueber die Routenabfangung von Playwright aus und fangen
den Simulationsaufruf ab, statt ihn auszufuehren.

Damit laufen sie ueberall, wo Playwright installiert ist - auch ohne
laufende Datenbank.

AUSFUEHREN
----------
    python -m pytest tests/test_cl_approach_browser.py -q --e2e -m e2e

Ohne --e2e ueberspringen sie sich sichtbar. Das ist wie im uebrigen
Projekt eine bewusste Entscheidung und KEINE Entwarnung: Ein
uebersprungener Lauf gehoert in den Abschlussbericht.
"""

import json
import os

import pytest

#: Browsertest - laeuft nur mit "--e2e" (siehe pytest.ini).
pytestmark = pytest.mark.e2e

pytest.importorskip(
    "playwright.sync_api",
    reason="Playwright ist nicht installiert - siehe tests/test_browser_smoke.py.",
)

from playwright.sync_api import sync_playwright  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Frei erfundener Host. Bewusst NICHT localhost oder 127.0.0.1: Beides
#: waere ein sicherer Kontext, und dann wuerde die Seite ihren Service
#: Worker registrieren wollen. Der haette hier nichts zu tun, koennte
#: aber Antworten aus einem vorherigen Test zwischenspeichern.
HOST = "http://footsim.test"

INHALTSTYPEN = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".webmanifest": "application/manifest+json",
}

#: Genau ein Wettbewerb je Art. Mehr braucht keiner dieser Tests, und
#: jede zusaetzliche Kachel waere eine zusaetzliche Fehlerquelle.
WETTBEWERBE = [
    {"code": "cl", "type": "cl", "name": "Champions League",
     "subtitle": "Ligaphase", "available": True, "emblem": None},
    {"code": "bl1", "type": "league", "name": "Bundesliga",
     "subtitle": "Spieltag 1", "available": True, "emblem": None},
]

PARTIE = {
    "id": 4242, "home_team": "Heimteam", "away_team": "Gastteam",
    "home_id": 5, "away_id": 678, "status": "SCHEDULED",
    "home_crest": None, "away_crest": None,
    "home_score": None, "away_score": None, "utc_date": None,
}

#: Eine Antwort in der Form, die renderResult() erwartet. Sie wird nie
#: gerechnet - der Simulationsaufruf wird abgefangen, bevor er den
#: Server erreichen koennte.
SIMULATIONSANTWORT = {
    "home_team": "Heimteam", "away_team": "Gastteam",
    "expected_home_goals": 1.8, "expected_away_goals": 1.1,
    "home_win_probability": 52.0, "draw_probability": 23.0,
    "away_win_probability": 25.0,
    "top_scores": [{"score": "2:1", "count": 900}],
    "competition": "Champions League", "phase": "league",
    "home_resolution": "domestic_history", "away_resolution": "domestic_history",
}


def _seite_rendern(locale="de"):
    """
    Rendert templates/index.html ohne Flask, Datenbank und Anbieter.

    Das Template kennt genau vier Jinja-Namen (t, url_for, csrf_token,
    locale) und ein Include. Alles davon laesst sich hier bereitstellen -
    der Umweg ueber die vollstaendige Anwendung waere nur eine weitere
    Abhaengigkeit, die ausfallen kann.
    """
    from jinja2 import Environment, FileSystemLoader

    from src.i18n import translate

    umgebung = Environment(
        loader=FileSystemLoader(os.path.join(PROJECT_ROOT, "templates")),
        autoescape=True,
    )
    umgebung.globals.update(
        t=lambda schluessel, **werte: translate(schluessel, locale, **werte),
        url_for=lambda _endpunkt, filename="": f"/static/{filename}",
        csrf_token=lambda: "testtoken",
        locale=locale,
    )
    return umgebung.get_template("index.html").render()


def _json(route, nutzlast, status=200):
    route.fulfill(status=status, content_type="application/json; charset=utf-8",
                  body=json.dumps(nutzlast))


class Aufzeichnung:
    """Sammelt die Simulationsaufrufe, die die Seite absetzt."""

    def __init__(self):
        self.nutzlasten = []

    @property
    def letzte(self):
        assert self.nutzlasten, "Es wurde keine Simulation abgeschickt."
        return self.nutzlasten[-1]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instanz = playwright.chromium.launch()
        yield instanz
        instanz.close()


@pytest.fixture
def seite(browser):
    """
    Die echte Seite mit echtem script.js - ohne Server und ohne Netz.

    Jede Anfrage laeuft durch den Handler. Was nicht ausdruecklich
    beantwortet wird, wird abgewiesen: Kein Test darf jemals einen
    externen Host erreichen oder Anbieterkontingent verbrauchen.
    """
    # Feste Browsersprache. initI18n() vergleicht die gewuenschte mit der
    # server-gerenderten Sprache und laedt bei Abweichung genau einmal
    # neu. Ohne feste Sprache haenge dieser Vergleich an der Voreinstellung
    # der Testmaschine - und der Harnisch waere anderswo rot.
    kontext = browser.new_context(locale="de-DE")
    blatt = kontext.new_page()

    seitenfehler = []
    blatt.on("pageerror", lambda fehler: seitenfehler.append(str(fehler)))

    aufzeichnung = Aufzeichnung()
    # Wie die echte Route: gerendert wird in der Sprache, die der Request
    # verlangt. Serviert man immer Deutsch, laedt die Seite bei ?lang=en
    # endlos neu.
    seiten = {sprache: _seite_rendern(sprache) for sprache in ("de", "en")}

    def handler(route):
        anfrage = route.request
        if not anfrage.url.startswith(HOST):
            route.abort()
            return

        rest = anfrage.url[len(HOST):]
        pfad, _, abfrage = rest.partition("?")
        pfad = pfad or "/"

        if pfad == "/":
            sprache = "en" if "lang=en" in abfrage else "de"
            route.fulfill(status=200, content_type="text/html; charset=utf-8",
                          body=seiten[sprache])
            return

        if pfad.startswith("/static/"):
            datei = os.path.join(PROJECT_ROOT, pfad.lstrip("/").replace("/", os.sep))
            if not os.path.isfile(datei):
                route.fulfill(status=404, body="")
                return
            endung = os.path.splitext(datei)[1]
            route.fulfill(
                status=200,
                content_type=INHALTSTYPEN.get(endung, "application/octet-stream"),
                body=open(datei, "rb").read(),
            )
            return

        if pfad == "/api/seasons":
            _json(route, [{"season": 2025, "label": "2025/26", "is_current": True}])
            return

        if pfad == "/api/competitions":
            _json(route, WETTBEWERBE)
            return

        if pfad == "/api/matches":
            _json(route, [PARTIE])
            return

        if pfad == "/api/simulate":
            aufzeichnung.nutzlasten.append(json.loads(anfrage.post_data))
            _json(route, SIMULATIONSANTWORT)
            return

        if pfad == "/api/auth/me":
            _json(route, {"authenticated": False}, status=401)
            return

        # Alles Uebrige - Spieltage, Tabellen, Torjaeger - braucht keiner
        # dieser Tests. Eine leere Liste haelt die Seite fehlerfrei.
        _json(route, [])

    blatt.route("**/*", handler)
    blatt.goto(f"{HOST}/")
    # Auf die Wettbewerbskacheln warten, nicht bloss auf das geladene
    # Skript: init() laedt Saisons und Wettbewerbe asynchron nach, und
    # state.competitions ist bis dahin leer.
    blatt.wait_for_selector(".competition-card")

    blatt.aufzeichnung = aufzeichnung
    blatt.seitenfehler = seitenfehler
    yield blatt

    assert not seitenfehler, f"JavaScript-Ausnahme auf der Seite: {seitenfehler}"
    kontext.close()


# ---------------------------------------------------------------------------
# Hilfsgriffe: der Zustand wird ueber die echten Funktionen gesetzt,
# nicht ueber state-Zuweisungen von aussen. Sonst wuerde der Test einen
# Zustand pruefen, den die Anwendung so nie erreicht.
# ---------------------------------------------------------------------------

def _wettbewerb_waehlen(seite, code):
    seite.evaluate(
        """(code) => {
            const wettbewerb = state.competitions.find(c => c.code === code);
            selectCompetition(wettbewerb, document.createElement("button"));
        }""",
        code,
    )
    seite.wait_for_timeout(50)


def _partie_waehlen(seite, partie=None):
    # Der Reiter "Spiele" oeffnet sich sonst erst ueber die Spieltagswahl,
    # die diese Tests nicht durchlaufen. Ohne ihn waere die Steuerung im
    # DOM, aber nicht sichtbar - und ein Klick auf "Simulieren" liefe ins
    # Leere.
    seite.evaluate("() => switchTab('fixtures')")
    seite.evaluate(
        """(partie) => selectMatch(partie, document.createElement("button"))""",
        partie or PARTIE,
    )


def _sichtbar(seite, auswahl):
    return seite.eval_on_selector(
        auswahl, "node => !node.classList.contains('hidden')")


def _simulieren(seite):
    """Klickt den echten Knopf und wartet auf den abgefangenen Aufruf."""
    vorher = len(seite.aufzeichnung.nutzlasten)
    seite.click("#simulate-btn")
    for _ in range(100):
        if len(seite.aufzeichnung.nutzlasten) > vorher:
            return seite.aufzeichnung.letzte
        seite.wait_for_timeout(50)
    raise AssertionError("Die Seite hat keinen Simulationsaufruf abgesetzt.")


def _regler_setzen(seite, regler_id, prozent):
    """Setzt einen Regler so, wie eine Nutzergeste es tut."""
    seite.eval_on_selector(
        f"#{regler_id}",
        """(node, wert) => {
            node.value = String(wert);
            node.dispatchEvent(new Event("input", { bubbles: true }));
        }""",
        prozent,
    )


# ---------------------------------------------------------------------------
# 1. Sichtbarkeit
# ---------------------------------------------------------------------------

class TestSichtbarkeit:

    def test_cl_einzelspiel_zeigt_die_auswahl(self, seite):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)

        assert _sichtbar(seite, "#sim-controls")
        assert _sichtbar(seite, "#cl-approach")

    def test_liga_einzelspiel_zeigt_die_auswahl_nicht(self, seite):
        _wettbewerb_waehlen(seite, "bl1")
        _partie_waehlen(seite)

        assert _sichtbar(seite, "#sim-controls")
        assert not _sichtbar(seite, "#cl-approach")

    def test_die_auswahl_steht_im_panel_ausgewaehlt(self, seite):
        """
        Sie darf nicht irgendwo eigenstaendig auftauchen - sonst waere sie
        beim Scrollen vom gewaehlten Spiel getrennt.
        """
        assert seite.eval_on_selector(
            "#cl-approach", "node => node.closest('#sim-controls') !== null")

    def test_die_saisonsimulationen_kennen_die_auswahl_nicht(self, seite):
        for bereich in ("#season-sim-controls", "#cl-season-sim-controls"):
            assert seite.eval_on_selector(
                bereich,
                "node => node.querySelector('.cl-approach-card') === null")


# ---------------------------------------------------------------------------
# 2. Standardzustand und Umschalten
# ---------------------------------------------------------------------------

class TestStandardUndUmschalten:

    def test_ml_prognose_ist_bei_cl_vorausgewaehlt(self, seite):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)

        assert seite.get_attribute(
            '.cl-approach-card[data-approach="ml"]', "aria-checked") == "true"
        assert seite.get_attribute(
            '.cl-approach-card[data-approach="custom"]', "aria-checked") == "false"
        assert not _sichtbar(seite, "#cl-factors")

    def test_individuell_blendet_genau_vier_regler_ein(self, seite):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('.cl-approach-card[data-approach="custom"]')

        assert _sichtbar(seite, "#cl-factors")
        assert seite.eval_on_selector_all(
            "#cl-factors .cl-factor-slider", "knoten => knoten.length") == 4
        for regler in ("attack", "defence", "home", "ml"):
            assert seite.is_visible(f"#cl-factor-{regler}")

    def test_zurueck_auf_ml_verbirgt_die_regler_wieder(self, seite):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('.cl-approach-card[data-approach="custom"]')
        seite.click('.cl-approach-card[data-approach="ml"]')

        assert not _sichtbar(seite, "#cl-factors")
        assert seite.get_attribute(
            '.cl-approach-card[data-approach="ml"]', "aria-checked") == "true"

    def test_die_auswahl_laesst_sich_mit_der_tastatur_bedienen(self, seite):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)

        seite.focus('.cl-approach-card[data-approach="ml"]')
        seite.keyboard.press("ArrowRight")
        assert seite.get_attribute(
            '.cl-approach-card[data-approach="custom"]', "aria-checked") == "true"

        seite.keyboard.press("ArrowLeft")
        assert seite.get_attribute(
            '.cl-approach-card[data-approach="ml"]', "aria-checked") == "true"


# ---------------------------------------------------------------------------
# 3. Nutzlast
# ---------------------------------------------------------------------------

class TestNutzlast:

    def test_ml_sendet_approach_ml_und_sonst_nichts_neues(self, seite):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)

        nutzlast = _simulieren(seite)
        assert nutzlast["approach"] == "ml"
        # C8A weist beides neben approach='ml' mit 400 ab. Ein Frontend,
        # das es trotzdem mitschickt, waere schlicht kaputt.
        assert "factors" not in nutzlast
        assert "ml_weight" not in nutzlast

    def test_custom_sendet_den_vollstaendigen_vertrag(self, seite):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('.cl-approach-card[data-approach="custom"]')

        nutzlast = _simulieren(seite)
        assert nutzlast["approach"] == "custom"
        assert nutzlast["ml_weight"] == 0.0
        assert nutzlast["factors"] == {
            "attack": 1.0, "defence": 1.0, "home_advantage": 1.0}

    @pytest.mark.parametrize("prozente,erwartet", [
        ((0, 0, 0, 0),
         ({"attack": 1.0, "defence": 1.0, "home_advantage": 1.0}, 0.0)),
        ((-30, -30, -50, 0),
         ({"attack": 0.7, "defence": 0.7, "home_advantage": 0.5}, 0.0)),
        ((30, 30, 50, 100),
         ({"attack": 1.3, "defence": 1.3, "home_advantage": 1.5}, 1.0)),
        ((10, -20, 25, 50),
         ({"attack": 1.1, "defence": 0.8, "home_advantage": 1.25}, 0.5)),
        # Genau die Stellen, an denen base + prozent/100 in Gleitkomma
        # sichtbar danebenliegt.
        ((-3, 7, -1, 29),
         ({"attack": 0.97, "defence": 1.07, "home_advantage": 0.99}, 0.29)),
    ])
    def test_alle_vier_regler_werden_korrekt_abgebildet(self, seite,
                                                        prozente, erwartet):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('.cl-approach-card[data-approach="custom"]')

        for regler_id, prozent in zip(
                ("cl-factor-attack", "cl-factor-defence",
                 "cl-factor-home", "cl-factor-ml"), prozente):
            _regler_setzen(seite, regler_id, prozent)

        nutzlast = _simulieren(seite)
        faktoren, gewicht = erwartet
        assert nutzlast["factors"] == faktoren
        assert nutzlast["ml_weight"] == gewicht

    def test_die_gesendeten_zahlen_tragen_keine_gleitkomma_artefakte(self, seite):
        """
        0.9700000000000001 waere gueltig, aber es stuende so im Request -
        und in jedem Protokoll dahinter.
        """
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('.cl-approach-card[data-approach="custom"]')

        for prozent in range(-30, 31):
            _regler_setzen(seite, "cl-factor-attack", prozent)
            roh = seite.evaluate("() => JSON.stringify(clApproachPayload())")
            wert = json.loads(roh)["factors"]["attack"]
            assert len(str(wert).split(".")[-1]) <= 2, (prozent, wert)

    def test_der_sichtbare_wert_folgt_dem_regler_sofort(self, seite):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('.cl-approach-card[data-approach="custom"]')

        _regler_setzen(seite, "cl-factor-attack", 12)
        assert seite.inner_text("#cl-factor-attack-value").strip() == "+12 %"

        _regler_setzen(seite, "cl-factor-attack", -12)
        assert seite.inner_text("#cl-factor-attack-value").strip() == "-12 %"

        # Der ML-Einfluss hat keinen Nullpunkt in der Mitte und deshalb
        # auch kein Vorzeichen.
        _regler_setzen(seite, "cl-factor-ml", 40)
        assert seite.inner_text("#cl-factor-ml-value").strip() == "40 %"

    def test_der_vorlesetext_traegt_die_einheit(self, seite):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('.cl-approach-card[data-approach="custom"]')
        _regler_setzen(seite, "cl-factor-home", -20)

        assert seite.get_attribute("#cl-factor-home", "aria-valuetext") == "-20 %"


# ---------------------------------------------------------------------------
# 4. Zuruecksetzen
# ---------------------------------------------------------------------------

class TestZuruecksetzen:

    def test_reset_stellt_alle_neutralwerte_wieder_her(self, seite):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('.cl-approach-card[data-approach="custom"]')

        for regler_id, prozent in (("cl-factor-attack", 25),
                                   ("cl-factor-defence", -25),
                                   ("cl-factor-home", 45),
                                   ("cl-factor-ml", 80)):
            _regler_setzen(seite, regler_id, prozent)

        seite.click("#cl-factor-reset")

        nutzlast = _simulieren(seite)
        assert nutzlast["factors"] == {
            "attack": 1.0, "defence": 1.0, "home_advantage": 1.0}
        assert nutzlast["ml_weight"] == 0.0

    def test_reset_laesst_den_ansatz_stehen(self, seite):
        """
        Zuruecksetzen betrifft die Regler. Wer dabei aus dem individuellen
        Modus flaege, muesste ihn nach jedem Versuch neu waehlen.
        """
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('.cl-approach-card[data-approach="custom"]')
        seite.click("#cl-factor-reset")

        assert _sichtbar(seite, "#cl-factors")
        assert seite.get_attribute(
            '.cl-approach-card[data-approach="custom"]', "aria-checked") == "true"

    def test_reset_setzt_auch_die_sichtbaren_werte_zurueck(self, seite):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('.cl-approach-card[data-approach="custom"]')
        _regler_setzen(seite, "cl-factor-ml", 70)
        seite.click("#cl-factor-reset")

        assert seite.inner_text("#cl-factor-ml-value").strip() == "0 %"
        assert seite.input_value("#cl-factor-ml") == "0"


# ---------------------------------------------------------------------------
# 5. Liga-Isolation und Zustandslecks
# ---------------------------------------------------------------------------

class TestIsolation:

    def test_liga_request_traegt_keines_der_neuen_felder(self, seite):
        _wettbewerb_waehlen(seite, "bl1")
        _partie_waehlen(seite)

        nutzlast = _simulieren(seite)
        for feld in ("approach", "factors", "ml_weight"):
            assert feld not in nutzlast

    def test_liga_request_bleibt_im_bisherigen_vertrag(self, seite):
        _wettbewerb_waehlen(seite, "bl1")
        _partie_waehlen(seite)

        nutzlast = _simulieren(seite)
        assert set(nutzlast) == {"competition", "simulations", "use_seed",
                                 "home_team", "away_team", "home_id", "away_id"}
        assert nutzlast["competition"] == "bl1"

    def test_ein_wechsel_zur_liga_traegt_nichts_mit(self, seite):
        """
        Der eigentliche Leckpfad: in der CL etwas verstellen, wechseln,
        simulieren. Die Felder sind dann unsichtbar - im Request duerfen
        sie trotzdem nicht auftauchen.
        """
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('.cl-approach-card[data-approach="custom"]')
        _regler_setzen(seite, "cl-factor-attack", 30)
        _regler_setzen(seite, "cl-factor-ml", 100)

        _wettbewerb_waehlen(seite, "bl1")
        _partie_waehlen(seite)

        nutzlast = _simulieren(seite)
        for feld in ("approach", "factors", "ml_weight"):
            assert feld not in nutzlast

    def test_der_wechsel_setzt_den_ansatz_zurueck(self, seite):
        """
        Zurueck in der Champions League muss wieder der Standard gelten -
        sonst rechnet ein spaeteres Spiel stillschweigend mit den Reglern
        eines frueheren.
        """
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('.cl-approach-card[data-approach="custom"]')
        _regler_setzen(seite, "cl-factor-attack", 30)

        _wettbewerb_waehlen(seite, "bl1")
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)

        assert seite.get_attribute(
            '.cl-approach-card[data-approach="ml"]', "aria-checked") == "true"
        assert not _sichtbar(seite, "#cl-factors")

        nutzlast = _simulieren(seite)
        assert nutzlast["approach"] == "ml"
        assert "factors" not in nutzlast


# ---------------------------------------------------------------------------
# 6. Immer gleiches Ergebnis
# ---------------------------------------------------------------------------

class TestSeedCheckbox:

    def test_bei_der_liga_bleibt_sie_sichtbar_und_wirksam(self, seite):
        _wettbewerb_waehlen(seite, "bl1")
        _partie_waehlen(seite)

        assert _sichtbar(seite, "#use-seed-row")
        seite.check("#use-seed")
        assert _simulieren(seite)["use_seed"] is True

    def test_bei_der_champions_league_ist_sie_verborgen(self, seite):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)

        assert not _sichtbar(seite, "#use-seed-row")

    def test_ein_alter_haken_beeinflusst_den_cl_request_nicht(self, seite):
        """
        Genau der stille Fehler: In der Liga angehakt, dann zur Champions
        League gewechselt. Die Checkbox ist verborgen, ihr Zustand aber
        noch da.
        """
        _wettbewerb_waehlen(seite, "bl1")
        _partie_waehlen(seite)
        seite.check("#use-seed")

        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)

        assert _simulieren(seite)["use_seed"] is False


# ---------------------------------------------------------------------------
# 7. Sprache und Darstellung
# ---------------------------------------------------------------------------

class TestSpracheUndDarstellung:

    def test_die_texte_stehen_auf_deutsch_in_der_oberflaeche(self, seite):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('.cl-approach-card[data-approach="custom"]')

        text = seite.inner_text("#cl-approach")
        for erwartet in ("ML-Prognose",
                         "Historisch trainiertes mathematisches Modell",
                         "Individuell", "Gewichte die Match-Faktoren selbst",
                         "Offensive", "Defensive", "Heimvorteil",
                         "ML-Einfluss", "Zurücksetzen"):
            assert erwartet in text

    def test_monte_carlo_steht_nirgends_in_der_neuen_oberflaeche(self, seite):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('.cl-approach-card[data-approach="custom"]')

        assert "monte carlo" not in seite.inner_text("#cl-approach").lower()

    def test_die_prozentanzeige_ist_nach_dem_laden_uebersetzt(self, seite):
        """
        Der Regler wird beim Parsen von script.js gezeichnet - da ist der
        Sprachkatalog noch nicht geladen, und t() faellt auf den
        lesbar gemachten Schluessel zurueck ("Percent"). Erst der
        Nachzieher in applyTranslations() macht daraus "0 %". Faellt der
        Aufruf weg, steht hier woertlich der Schluesselrest.
        """
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('.cl-approach-card[data-approach="custom"]')

        for regler in ("attack", "defence", "home", "ml"):
            assert seite.inner_text(f"#cl-factor-{regler}-value").strip() == "0 %"

    def test_die_englische_oberflaeche_ist_vollstaendig(self, seite):
        seite.goto(f"{HOST}/?lang=en")
        seite.wait_for_selector(".competition-card")
        seite.wait_for_function("() => document.documentElement.lang === 'en'")

        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('.cl-approach-card[data-approach="custom"]')

        text = seite.inner_text("#cl-approach")
        for erwartet in ("ML forecast",
                         "Mathematical model trained on historical data",
                         "Custom", "Weight the match factors yourself",
                         "Attack", "Defence", "Home advantage",
                         "ML influence", "Reset"):
            assert erwartet in text

        _regler_setzen(seite, "cl-factor-attack", 15)
        assert seite.inner_text("#cl-factor-attack-value").strip() == "+15 %"

    @pytest.mark.parametrize("breite,hoehe", [
        (1440, 900),   # breiter Desktop
        (390, 844),    # gewoehnliches Smartphone
        (320, 568),    # schmales Smartphone
    ])
    def test_nichts_laeuft_seitlich_aus_dem_panel(self, seite, breite, hoehe):
        seite.set_viewport_size({"width": breite, "height": hoehe})
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('.cl-approach-card[data-approach="custom"]')

        ueberstand = seite.evaluate(
            """() => {
                const panel = document.getElementById("sim-controls");
                const rahmen = panel.getBoundingClientRect();
                const knoten = panel.querySelectorAll(
                    "#cl-approach, .cl-approach-card, .cl-factor-slider, "
                    + "#cl-factor-reset");
                return Array.from(knoten)
                    .map(n => {
                        const r = n.getBoundingClientRect();
                        return Math.max(rahmen.left - r.left, r.right - rahmen.right);
                    })
                    .filter(wert => wert > 1);
            }"""
        )
        assert ueberstand == [], ueberstand

    @pytest.mark.parametrize("breite", [390, 320])
    def test_die_bedienflaechen_bleiben_auf_dem_handy_gross_genug(self, seite,
                                                                  breite):
        seite.set_viewport_size({"width": breite, "height": 844})
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('.cl-approach-card[data-approach="custom"]')

        hoehen = seite.evaluate(
            """() => Array.from(document.querySelectorAll(
                   ".cl-approach-card, .cl-factor-slider, #cl-factor-reset"))
                   .map(n => n.getBoundingClientRect().height)"""
        )
        assert hoehen and min(hoehen) >= 44, hoehen

    def test_lange_vereinsnamen_sprengen_das_panel_nicht(self, seite):
        seite.set_viewport_size({"width": 320, "height": 568})
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite, {
            "id": 1, "home_team": "Borussia Moenchengladbach 1900 e.V.",
            "away_team": "Nogometni Klub Maribor Branik Stadion",
            "home_id": 18, "away_id": 999, "status": "SCHEDULED",
        })

        assert seite.evaluate(
            """() => document.documentElement.scrollWidth
                     <= document.documentElement.clientWidth + 1"""
        )
