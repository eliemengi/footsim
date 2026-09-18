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

#: C23: Die Antwort des heutigen Servers - mit ausgefuehrter Laufzahl und
#: dem tatsaechlich angewandten Ansatz. SIMULATIONSANTWORT oben bleibt
#: bewusst die alte Form ohne beides (alter Server / Rueckwaertstest).
C23_ANTWORT = dict(
    SIMULATIONSANTWORT,
    simulations=5000,
    top_scores=[{"score": "1:1", "count": 421}, {"score": "2:1", "count": 402},
                {"score": "1:0", "count": 384}, {"score": "2:0", "count": 375},
                {"score": "0:0", "count": 146}],
    ml={"mode": "active", "applied": True, "model_id": "intern-123",
        "effective_approach": "ml", "ml_fallback": "none",
        "league_stage_applied": True},
)

SAISONANTWORT = {
    "competition": "Champions League", "season": 2025,
    "mode": "simulate_remaining", "simulations": 1000,
    "fixtures_simulated": 36, "fixtures_fixed": 108, "teams_total": 2,
    "zones": {"direct_last": 8, "playoff_last": 24},
    "entries": [
        {"rank": 1, "team_id": 5, "team_name": "Heimteam", "crest": None,
         "expected_points": 18.2, "direct_pct": 80.0, "playoff_pct": 19.0,
         "eliminated_pct": 1.0, "top_seed_pct": 30.0},
        {"rank": 2, "team_id": 678, "team_name": "Gastteam", "crest": None,
         "expected_points": 11.4, "direct_pct": 20.0, "playoff_pct": 60.0,
         "eliminated_pct": 20.0, "top_seed_pct": 2.0},
    ],
    "ml": {"mode": "active", "effective_approach": "ml", "ml_fallback": "none",
           "ml_fixtures": 36, "fixtures_total": 36, "league_stage_applied": 36},
}

WAPPEN_HOST = "https://crests.football-data.org/"
#: Ein echtes, kleines PNG aus dem Projekt als Wappen.
WAPPEN_BILD = os.path.join(PROJECT_ROOT, "static", "icons", "icon-48.png")


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

    fremde_anfragen = []
    wappen_anfragen = []
    saison_anfragen = []
    zurueckgehalten = []
    einstellungen = {"antwort": SIMULATIONSANTWORT, "saison": SAISONANTWORT,
                     "zurueckhalten": False}

    def handler(route):
        anfrage = route.request
        # C23: Wappen vom zugelassenen Host - ein echtes PNG, oder 404
        # fuer ein absichtlich defektes Wappen. Kein Netzzugriff.
        if anfrage.url.startswith(WAPPEN_HOST):
            wappen_anfragen.append(anfrage.url)
            if anfrage.url.endswith("/broken.png"):
                route.fulfill(status=404, body="")
            else:
                route.fulfill(status=200, content_type="image/png",
                              body=open(WAPPEN_BILD, "rb").read())
            return
        if not anfrage.url.startswith(HOST):
            fremde_anfragen.append(anfrage.url)
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
            if einstellungen["zurueckhalten"]:
                # Spaete Antwort: Der Test beantwortet sie selbst, wenn
                # er so weit ist.
                zurueckgehalten.append(route)
                return
            _json(route, einstellungen["antwort"])
            return

        if pfad == "/api/cl-season-sim":
            saison_anfragen.append(abfrage)
            if einstellungen["zurueckhalten"]:
                zurueckgehalten.append(route)
                return
            _json(route, einstellungen["saison"])
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
    blatt.fremde_anfragen = fremde_anfragen
    blatt.wappen_anfragen = wappen_anfragen
    blatt.saison_anfragen = saison_anfragen
    blatt.zurueckgehalten = zurueckgehalten
    blatt.einstellungen = einstellungen
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

    def test_nur_die_cl_ligaphase_kennt_die_auswahl(self, seite):
        """GEAENDERT IN C23: Die Ligen-Saisonsimulation bleibt ohne
        Karten; die CL-Ligaphase hat dieselben drei wie das Einzelspiel."""
        assert seite.eval_on_selector(
            "#season-sim-controls",
            "node => node.querySelector('.cl-approach-card') === null")
        assert seite.eval_on_selector_all(
            "#cl-season-sim-controls .cl-approach-card",
            "karten => karten.map(k => k.dataset.approach)") == [
                "ml", "custom", "classic"]


# ---------------------------------------------------------------------------
# 2. Standardzustand und Umschalten
# ---------------------------------------------------------------------------

class TestStandardUndUmschalten:

    def test_ml_prognose_ist_bei_cl_vorausgewaehlt(self, seite):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)

        assert seite.get_attribute(
            '#cl-approach .cl-approach-card[data-approach="ml"]', "aria-checked") == "true"
        assert seite.get_attribute(
            '#cl-approach .cl-approach-card[data-approach="custom"]', "aria-checked") == "false"
        assert not _sichtbar(seite, "#cl-factors")

    def test_individuell_blendet_genau_vier_regler_ein(self, seite):
        """
        GEAENDERT IN V2-C17: 'attack'/'defence' waren dieselbe Wirkung
        (siehe cl_custom_factors.py) und sind durch home_strength/
        away_strength/home_advantage/goal_level ersetzt; der
        ML-Einfluss-Regler ist ersatzlos entfallen.
        """
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('#cl-approach .cl-approach-card[data-approach="custom"]')

        assert _sichtbar(seite, "#cl-factors")
        assert seite.eval_on_selector_all(
            "#cl-factors .cl-factor-slider", "knoten => knoten.length") == 4
        for regler in ("home-strength", "away-strength", "home", "goal-level"):
            assert seite.is_visible(f"#cl-factor-{regler}")

    def test_zurueck_auf_ml_verbirgt_die_regler_wieder(self, seite):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('#cl-approach .cl-approach-card[data-approach="custom"]')
        seite.click('#cl-approach .cl-approach-card[data-approach="ml"]')

        assert not _sichtbar(seite, "#cl-factors")
        assert seite.get_attribute(
            '#cl-approach .cl-approach-card[data-approach="ml"]', "aria-checked") == "true"

    def test_die_auswahl_laesst_sich_mit_der_tastatur_bedienen(self, seite):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)

        seite.focus('#cl-approach .cl-approach-card[data-approach="ml"]')
        seite.keyboard.press("ArrowRight")
        assert seite.get_attribute(
            '#cl-approach .cl-approach-card[data-approach="custom"]', "aria-checked") == "true"

        seite.keyboard.press("ArrowLeft")
        assert seite.get_attribute(
            '#cl-approach .cl-approach-card[data-approach="ml"]', "aria-checked") == "true"

        # C23: drei Karten, rundum - und der Fokus wandert mit.
        seite.keyboard.press("ArrowLeft")
        assert seite.get_attribute(
            '#cl-approach .cl-approach-card[data-approach="classic"]',
            "aria-checked") == "true"
        assert seite.evaluate("() => document.activeElement.dataset.approach") == "classic"
        seite.keyboard.press("ArrowRight")
        assert seite.get_attribute(
            '#cl-approach .cl-approach-card[data-approach="ml"]', "aria-checked") == "true"
        # Roving tabindex: genau ein Tabstopp je Gruppe.
        assert seite.eval_on_selector_all(
            "#cl-approach .cl-approach-card",
            "k => k.map(n => n.tabIndex)") == [0, -1, -1]


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
        """
        GEAENDERT IN DER V2-C17-HAERTUNG: 'ml_weight' steht nicht mehr
        in der Nutzlast. Es gibt keinen ML-Regler mehr, der Wert liefern
        koennte, und cl_custom_factors.parse_options() weist das Feld
        fuer approach='custom' jetzt ohnehin ab, wenn es doch gesendet
        wuerde.
        """
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('#cl-approach .cl-approach-card[data-approach="custom"]')

        nutzlast = _simulieren(seite)
        assert nutzlast["approach"] == "custom"
        assert "ml_weight" not in nutzlast
        assert nutzlast["factors"] == {
            "home_strength": 1.0, "away_strength": 1.0,
            "home_advantage": 1.0, "goal_level": 1.0}

    @pytest.mark.parametrize("prozente,erwartet", [
        ((0, 0, 0, 0),
         {"home_strength": 1.0, "away_strength": 1.0,
          "home_advantage": 1.0, "goal_level": 1.0}),
        ((-30, -30, -50, -25),
         {"home_strength": 0.7, "away_strength": 0.7,
          "home_advantage": 0.5, "goal_level": 0.75}),
        ((30, 30, 50, 25),
         {"home_strength": 1.3, "away_strength": 1.3,
          "home_advantage": 1.5, "goal_level": 1.25}),
        ((10, -20, 25, 10),
         {"home_strength": 1.1, "away_strength": 0.8,
          "home_advantage": 1.25, "goal_level": 1.1}),
        # Genau die Stellen, an denen base + prozent/100 in Gleitkomma
        # sichtbar danebenliegt.
        ((-3, 7, -1, -2),
         {"home_strength": 0.97, "away_strength": 1.07,
          "home_advantage": 0.99, "goal_level": 0.98}),
    ])
    def test_alle_vier_regler_werden_korrekt_abgebildet(self, seite,
                                                        prozente, erwartet):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('#cl-approach .cl-approach-card[data-approach="custom"]')

        for regler_id, prozent in zip(
                ("cl-factor-home-strength", "cl-factor-away-strength",
                 "cl-factor-home", "cl-factor-goal-level"), prozente):
            _regler_setzen(seite, regler_id, prozent)

        nutzlast = _simulieren(seite)
        assert nutzlast["factors"] == erwartet
        assert "ml_weight" not in nutzlast

    def test_die_gesendeten_zahlen_tragen_keine_gleitkomma_artefakte(self, seite):
        """
        0.9700000000000001 waere gueltig, aber es stuende so im Request -
        und in jedem Protokoll dahinter.
        """
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('#cl-approach .cl-approach-card[data-approach="custom"]')

        for prozent in range(-30, 31):
            _regler_setzen(seite, "cl-factor-home-strength", prozent)
            roh = seite.evaluate("() => JSON.stringify(clApproachPayload())")
            wert = json.loads(roh)["factors"]["home_strength"]
            assert len(str(wert).split(".")[-1]) <= 2, (prozent, wert)

    def test_der_sichtbare_wert_folgt_dem_regler_sofort(self, seite):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('#cl-approach .cl-approach-card[data-approach="custom"]')

        _regler_setzen(seite, "cl-factor-home-strength", 12)
        assert seite.inner_text("#cl-factor-home-strength-value").strip() == "+12 %"

        _regler_setzen(seite, "cl-factor-home-strength", -12)
        assert seite.inner_text("#cl-factor-home-strength-value").strip() == "-12 %"

        # V2-C17: Jeder der vier Regler hat seinen Nullpunkt in der
        # Mitte und traegt deshalb ein Vorzeichen - anders als vorher
        # der entfallene ML-Einfluss-Regler ohne Mittelpunkt.
        _regler_setzen(seite, "cl-factor-goal-level", 15)
        assert seite.inner_text("#cl-factor-goal-level-value").strip() == "+15 %"

    def test_der_vorlesetext_traegt_die_einheit(self, seite):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('#cl-approach .cl-approach-card[data-approach="custom"]')
        _regler_setzen(seite, "cl-factor-home", -20)

        assert seite.get_attribute("#cl-factor-home", "aria-valuetext") == "-20 %"


# ---------------------------------------------------------------------------
# 4. Zuruecksetzen
# ---------------------------------------------------------------------------

class TestZuruecksetzen:

    def test_reset_stellt_alle_neutralwerte_wieder_her(self, seite):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('#cl-approach .cl-approach-card[data-approach="custom"]')

        for regler_id, prozent in (("cl-factor-home-strength", 25),
                                   ("cl-factor-away-strength", -25),
                                   ("cl-factor-home", 45),
                                   ("cl-factor-goal-level", 20)):
            _regler_setzen(seite, regler_id, prozent)

        seite.click("#cl-factor-reset")

        nutzlast = _simulieren(seite)
        assert nutzlast["factors"] == {
            "home_strength": 1.0, "away_strength": 1.0,
            "home_advantage": 1.0, "goal_level": 1.0}
        assert "ml_weight" not in nutzlast

    def test_reset_laesst_den_ansatz_stehen(self, seite):
        """
        Zuruecksetzen betrifft die Regler. Wer dabei aus dem individuellen
        Modus flaege, muesste ihn nach jedem Versuch neu waehlen.
        """
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('#cl-approach .cl-approach-card[data-approach="custom"]')
        seite.click("#cl-factor-reset")

        assert _sichtbar(seite, "#cl-factors")
        assert seite.get_attribute(
            '#cl-approach .cl-approach-card[data-approach="custom"]', "aria-checked") == "true"

    def test_reset_setzt_auch_die_sichtbaren_werte_zurueck(self, seite):
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('#cl-approach .cl-approach-card[data-approach="custom"]')
        _regler_setzen(seite, "cl-factor-goal-level", 20)
        seite.click("#cl-factor-reset")

        assert seite.inner_text("#cl-factor-goal-level-value").strip() == "0 %"
        assert seite.input_value("#cl-factor-goal-level") == "0"


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
        seite.click('#cl-approach .cl-approach-card[data-approach="custom"]')
        _regler_setzen(seite, "cl-factor-home-strength", 30)
        _regler_setzen(seite, "cl-factor-goal-level", 25)

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
        seite.click('#cl-approach .cl-approach-card[data-approach="custom"]')
        _regler_setzen(seite, "cl-factor-home-strength", 30)

        _wettbewerb_waehlen(seite, "bl1")
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)

        assert seite.get_attribute(
            '#cl-approach .cl-approach-card[data-approach="ml"]', "aria-checked") == "true"
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
        """GEAENDERT IN C23: drei Karten mit den vorgegebenen Texten,
        keine sichtbare "V2-Prognose"."""
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('#cl-approach .cl-approach-card[data-approach="custom"]')

        text = seite.inner_text("#cl-approach")
        for erwartet in ("Machine Learning",
                         "Trainiertes Modell auf Basis historischer Spieldaten.",
                         "Eigene Einschätzung", "Stelle die Faktoren selbst ein.",
                         "Klassische Simulation",
                         "Historische Teamwerte mit Monte-Carlo-Simulation.",
                         "Heimteam-Stärke", "Auswärtsteam-Stärke", "Heimvorteil",
                         "Torniveau", "Zurücksetzen"):
            assert erwartet in text
        assert "V2" not in seite.inner_text("body")

    def test_monte_carlo_steht_nur_bei_der_klassischen_simulation(self, seite):
        """GEAENDERT IN C23: Die klassische Karte beschreibt, was sie
        tut - eine Monte-Carlo-Simulation. Sonst steht das Wort nirgends."""
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('#cl-approach .cl-approach-card[data-approach="custom"]')

        for ansatz in ("ml", "custom"):
            karte = seite.inner_text(
                f'#cl-approach .cl-approach-card[data-approach="{ansatz}"]')
            assert "monte" not in karte.lower()
        assert "monte" not in seite.inner_text("#cl-factors").lower()
        assert "Monte-Carlo" in seite.inner_text(
            '#cl-approach .cl-approach-card[data-approach="classic"]')

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
        seite.click('#cl-approach .cl-approach-card[data-approach="custom"]')

        for regler in ("home-strength", "away-strength", "home", "goal-level"):
            assert seite.inner_text(f"#cl-factor-{regler}-value").strip() == "0 %"

    def test_die_englische_oberflaeche_ist_vollstaendig(self, seite):
        seite.goto(f"{HOST}/?lang=en")
        seite.wait_for_selector(".competition-card")
        seite.wait_for_function("() => document.documentElement.lang === 'en'")

        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('#cl-approach .cl-approach-card[data-approach="custom"]')

        text = seite.inner_text("#cl-approach")
        for erwartet in ("Machine learning",
                         "Trained model based on historical match data.",
                         "Your own assessment", "Set the factors yourself.",
                         "Classic simulation",
                         "Historical team ratings with Monte Carlo simulation.",
                         "Home team strength", "Away team strength",
                         "Home advantage", "Goal level", "Reset"):
            assert erwartet in text
        assert "V2" not in seite.inner_text("body")

        _regler_setzen(seite, "cl-factor-home-strength", 15)
        assert seite.inner_text("#cl-factor-home-strength-value").strip() == "+15 %"

    @pytest.mark.parametrize("breite,hoehe", [
        (1440, 900),   # breiter Desktop
        (390, 844),    # gewoehnliches Smartphone
        (320, 568),    # schmales Smartphone
    ])
    def test_nichts_laeuft_seitlich_aus_dem_panel(self, seite, breite, hoehe):
        seite.set_viewport_size({"width": breite, "height": hoehe})
        _wettbewerb_waehlen(seite, "cl")
        _partie_waehlen(seite)
        seite.click('#cl-approach .cl-approach-card[data-approach="custom"]')

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
        seite.click('#cl-approach .cl-approach-card[data-approach="custom"]')

        # Seit C23 steht dieselbe Gruppe auch im (hier verborgenen)
        # Ligaphasenreiter; gemessen wird das sichtbare Panel.
        hoehen = seite.evaluate(
            """() => Array.from(document.querySelectorAll(
                   "#sim-controls .cl-approach-card, #sim-controls .cl-factor-slider, "
                   + "#cl-factor-reset"))
                   .map(n => n.getBoundingClientRect().height)"""
        )
        assert hoehen and len(hoehen) == 3 + 4 + 1, hoehen
        assert min(hoehen) >= 44, hoehen

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


# ---------------------------------------------------------------------------
# C23. Drei Ansaetze, gemeinsamer Zustand, ehrliche Ergebniszeile,
#      Prozente, spaete Antworten, Logos, Layout
# ---------------------------------------------------------------------------

LANGE_PARTIE = {
    "id": 7, "home_team": "Borussia Moenchengladbach 1900 e.V. Traditionsverein",
    "away_team": "Nogometni Klub Maribor Branik Stadion Ljudski vrt",
    "home_id": 18, "away_id": 999, "status": "SCHEDULED",
    "home_crest": WAPPEN_HOST + "18.png", "away_crest": WAPPEN_HOST + "broken.png",
}


def _cl_partie(seite, partie=None):
    _wettbewerb_waehlen(seite, "cl")
    _partie_waehlen(seite, partie)


def _ergebnis_abwarten(seite):
    seite.wait_for_selector("#result:not(.hidden)")


def _ligaphase_oeffnen(seite):
    seite.evaluate("() => switchTab('cl-season')")
    seite.wait_for_selector("#cl-season-sim-controls:not(.hidden)")


def _ligaphase_simulieren(seite):
    vorher = len(seite.saison_anfragen)
    seite.click("#cl-season-sim-btn")
    for _ in range(100):
        if len(seite.saison_anfragen) > vorher:
            return dict(p.split("=", 1) for p in seite.saison_anfragen[-1].split("&"))
        seite.wait_for_timeout(50)
    raise AssertionError("Die Seite hat keine Ligaphasensimulation abgesetzt.")


def _karte(gruppe, ansatz):
    return f'#{gruppe} .cl-approach-card[data-approach="{ansatz}"]'


def _gewaehlt(seite, gruppe):
    return seite.eval_on_selector_all(
        f"#{gruppe} .cl-approach-card",
        "k => k.filter(n => n.getAttribute('aria-checked') === 'true')"
        ".map(n => n.dataset.approach)")


class TestDreiAnsaetze:

    def test_classic_sendet_ausschliesslich_den_ansatz(self, seite):
        _cl_partie(seite)
        seite.click(_karte("cl-approach", "classic"))

        assert _gewaehlt(seite, "cl-approach") == ["classic"]
        assert not _sichtbar(seite, "#cl-factors")
        nutzlast = _simulieren(seite)
        assert nutzlast["approach"] == "classic"
        assert "factors" not in nutzlast and "ml_weight" not in nutzlast


class TestGemeinsamerZustand:

    def test_die_wahl_ueberlebt_den_tabwechsel_in_beide_richtungen(self, seite):
        _cl_partie(seite)
        seite.click(_karte("cl-approach", "classic"))

        _ligaphase_oeffnen(seite)
        assert _gewaehlt(seite, "cl-season-approach") == ["classic"]

        seite.click(_karte("cl-season-approach", "custom"))
        seite.evaluate("() => switchTab('fixtures')")
        assert _gewaehlt(seite, "cl-approach") == ["custom"]
        assert _sichtbar(seite, "#cl-factors")

    def test_die_ligaphase_zeigt_nur_die_globalen_regler(self, seite):
        _cl_partie(seite)
        _ligaphase_oeffnen(seite)
        assert not _sichtbar(seite, "#cl-season-factors")
        seite.click(_karte("cl-season-approach", "custom"))

        assert _sichtbar(seite, "#cl-season-factors")
        sichtbar = seite.eval_on_selector_all(
            "#cl-season-factors .cl-factor-slider", "r => r.map(n => n.id)")
        assert sichtbar == ["cl-season-factor-home", "cl-season-factor-goal-level"]
        # Beschriftete Regler: genau die zwei globalen. Die Teamstaerken
        # kommen nur im Hinweis vor, der erklaert, warum sie fehlen.
        assert seite.eval_on_selector_all(
            "#cl-season-factors label", "k => k.map(n => n.textContent.trim())") == [
                "Heimvorteil", "Torniveau"]
        assert "nur in der Spielsimulation" in seite.inner_text("#cl-season-factors")

    def test_die_regler_sind_zwischen_den_tabs_synchron(self, seite):
        _cl_partie(seite)
        _ligaphase_oeffnen(seite)
        seite.click(_karte("cl-season-approach", "custom"))
        _regler_setzen(seite, "cl-season-factor-home", 20)
        assert seite.inner_text("#cl-season-factor-home-value").strip() == "+20 %"

        seite.evaluate("() => switchTab('fixtures')")
        assert seite.input_value("#cl-factor-home") == "20"
        assert seite.inner_text("#cl-factor-home-value").strip() == "+20 %"
        assert _simulieren(seite)["factors"]["home_advantage"] == 1.2

    def test_die_ligaphase_sendet_ansatz_und_nur_globale_faktoren(self, seite):
        _cl_partie(seite)
        _ligaphase_oeffnen(seite)
        assert _ligaphase_simulieren(seite)["approach"] == "ml"
        assert set(_ligaphase_simulieren(seite)) >= {"simulations", "approach"}

        seite.click(_karte("cl-season-approach", "custom"))
        _regler_setzen(seite, "cl-season-factor-home", 20)
        _regler_setzen(seite, "cl-season-factor-goal-level", -10)
        # Auch die Teamstaerke des Einzelspiels verstellen: Sie darf in der
        # Ligaphase trotzdem nicht mitgehen.
        seite.evaluate("() => { state.clFactorPercents.home_strength = 30; }")
        abfrage = _ligaphase_simulieren(seite)
        assert abfrage["approach"] == "custom"
        assert (abfrage["home_advantage"], abfrage["goal_level"]) == ("1.2", "0.9")
        for fremd in ("home_strength", "away_strength", "ml_weight", "factors"):
            assert fremd not in abfrage

        seite.click(_karte("cl-season-approach", "classic"))
        abfrage = _ligaphase_simulieren(seite)
        assert abfrage["approach"] == "classic"
        assert "home_advantage" not in abfrage and "goal_level" not in abfrage

    def test_ein_wettbewerbswechsel_setzt_beide_gruppen_zurueck(self, seite):
        """Die bestehende Regel bleibt: neuer Wettbewerb, Standardansatz."""
        _cl_partie(seite)
        seite.click(_karte("cl-approach", "classic"))
        _wettbewerb_waehlen(seite, "bl1")
        _wettbewerb_waehlen(seite, "cl")

        assert _gewaehlt(seite, "cl-approach") == ["ml"]
        assert _gewaehlt(seite, "cl-season-approach") == ["ml"]


class TestErgebniszeile:

    def test_berechnet_mit_machine_learning(self, seite):
        seite.einstellungen["antwort"] = C23_ANTWORT
        _cl_partie(seite)
        _simulieren(seite)
        _ergebnis_abwarten(seite)

        assert _sichtbar(seite, "#result-approach")
        assert seite.inner_text("#result-approach") == "Berechnet mit: Machine Learning"
        kopf = seite.inner_text("#result .result-header")
        assert "intern-123" not in kopf and "V2" not in kopf

    def test_voller_rueckfall_wird_ehrlich_benannt(self, seite):
        seite.einstellungen["antwort"] = dict(C23_ANTWORT, ml={
            "mode": "active", "applied": False, "effective_approach": "classic",
            "ml_fallback": "full", "league_stage_applied": None})
        _cl_partie(seite)
        _simulieren(seite)
        _ergebnis_abwarten(seite)

        assert seite.inner_text("#result-approach") == (
            "Machine Learning war hier nicht verfügbar. Berechnet wurde klassisch.")

    def test_die_zeile_folgt_der_antwort_nicht_der_karte(self, seite):
        """Gewaehlt ist ML, der Server meldet classic: Es gilt die Antwort."""
        seite.einstellungen["antwort"] = dict(C23_ANTWORT, ml={
            "mode": "off", "effective_approach": "classic", "ml_fallback": "none"})
        _cl_partie(seite)
        _simulieren(seite)
        _ergebnis_abwarten(seite)
        assert seite.inner_text("#result-approach") == (
            "Berechnet mit: Klassische Simulation")

    def test_eine_alte_antwort_ohne_feld_zeigt_keine_zeile(self, seite):
        _cl_partie(seite)
        _simulieren(seite)
        _ergebnis_abwarten(seite)
        assert not _sichtbar(seite, "#result-approach")

    def test_die_liga_zeigt_keine_zeile_und_keine_logos(self, seite):
        seite.einstellungen["antwort"] = C23_ANTWORT
        _wettbewerb_waehlen(seite, "bl1")
        _partie_waehlen(seite)
        _simulieren(seite)
        _ergebnis_abwarten(seite)
        assert not _sichtbar(seite, "#result-approach")
        assert seite.eval_on_selector_all("#match-title .match-crest", "k => k.length") == 0
        assert seite.eval_on_selector_all(
            "#selected-match-label .match-crest", "k => k.length") == 0

    def test_ligaphase_teilweise_und_steuerung_bleibt(self, seite):
        seite.einstellungen["saison"] = dict(SAISONANTWORT, ml={
            "mode": "active", "effective_approach": "ml", "ml_fallback": "partial",
            "ml_fixtures": 30, "fixtures_total": 36, "league_stage_applied": 30})
        _cl_partie(seite)
        _ligaphase_oeffnen(seite)
        _ligaphase_simulieren(seite)
        seite.wait_for_selector("#cl-season-sim-result:not(.hidden)")

        assert seite.inner_text("#cl-season-sim-approach") == (
            "Machine Learning wurde für 30 von 36 offenen Spielen verwendet, "
            "die übrigen wurden klassisch berechnet.")
        # Die Karten bleiben erreichbar - ein Wechsel setzt das Ergebnis zurueck.
        assert _sichtbar(seite, "#cl-season-sim-controls")
        seite.click(_karte("cl-season-approach", "classic"))
        assert not _sichtbar(seite, "#cl-season-sim-result")


class TestProzente:

    def test_421_von_5000_sind_8_4_prozent(self, seite):
        seite.einstellungen["antwort"] = C23_ANTWORT
        _cl_partie(seite)
        _simulieren(seite)
        _ergebnis_abwarten(seite)

        zeilen = seite.eval_on_selector_all(
            "#top-scores .score-sub", "k => k.map(n => n.textContent)")
        assert zeilen == ["8,4 % aller Simulationen", "8,0 % aller Simulationen",
                          "7,7 % aller Simulationen", "7,5 % aller Simulationen",
                          "2,9 % aller Simulationen"]
        assert seite.inner_text("#best-score-count") == "421 von 5.000 Simulationen"
        text = seite.inner_text("#result")
        assert "Top 5" not in text and "24,4" not in text
        # 1X2 bleibt, wie es war.
        assert "52" in seite.inner_text("#probability-bars")

    def test_ohne_nenner_keine_prozentwerte(self, seite):
        _cl_partie(seite)
        _simulieren(seite)
        _ergebnis_abwarten(seite)
        assert seite.eval_on_selector_all("#top-scores .score-sub", "k => k.length") == 0
        assert seite.inner_text("#best-score-count") == "900 von allen Simulationen"

    def test_englisch(self, seite):
        seite.goto(f"{HOST}/?lang=en")
        seite.wait_for_selector(".competition-card")
        seite.wait_for_function("() => document.documentElement.lang === 'en'")
        seite.einstellungen["antwort"] = C23_ANTWORT
        _cl_partie(seite)
        _simulieren(seite)
        _ergebnis_abwarten(seite)

        assert seite.eval_on_selector(
            "#top-scores .score-sub", "n => n.textContent") == "8.4% of all simulations"
        assert seite.inner_text("#best-score-count") == "421 of 5,000 simulations"
        assert seite.inner_text("#result-approach") == "Calculated with: Machine learning"


class TestSpaeteAntworten:

    def test_ein_ansatzwechsel_waehrend_der_rechnung_verwirft_die_antwort(self, seite):
        seite.einstellungen["zurueckhalten"] = True
        _cl_partie(seite)
        _simulieren(seite)
        seite.click(_karte("cl-approach", "classic"))

        _json(seite.zurueckgehalten.pop(), C23_ANTWORT)
        seite.wait_for_timeout(300)
        assert not _sichtbar(seite, "#result")
        # Der Knopf ist wieder frei - die Anfrage war die neueste.
        assert seite.is_enabled("#simulate-btn")

    def test_eine_neuere_anfrage_gewinnt(self, seite):
        seite.einstellungen["zurueckhalten"] = True
        _cl_partie(seite)
        seite.evaluate("() => { runSimulation(); runSimulation(); }")
        for _ in range(100):
            if len(seite.zurueckgehalten) == 2:
                break
            seite.wait_for_timeout(50)
        alt, neu = seite.zurueckgehalten
        _json(neu, dict(C23_ANTWORT, home_team="Neu"))
        _json(alt, dict(C23_ANTWORT, home_team="Alt"))
        seite.wait_for_timeout(300)
        titel = seite.eval_on_selector("#match-title", "n => n.textContent")
        assert "Neu" in titel and "Alt" not in titel

    def test_ein_angezeigtes_ergebnis_wird_nie_umetikettiert(self, seite):
        seite.einstellungen["antwort"] = C23_ANTWORT
        _cl_partie(seite)
        _simulieren(seite)
        _ergebnis_abwarten(seite)

        seite.evaluate("() => switchTab('fixtures')")
        seite.click(_karte("cl-approach", "custom"))
        assert not _sichtbar(seite, "#result")
        assert _sichtbar(seite, "#sim-empty")

    def test_ein_reglerzug_setzt_das_ergebnis_ebenfalls_zurueck(self, seite):
        seite.einstellungen["antwort"] = C23_ANTWORT
        _cl_partie(seite)
        seite.click(_karte("cl-approach", "custom"))
        _simulieren(seite)
        _ergebnis_abwarten(seite)

        seite.evaluate("() => switchTab('fixtures')")
        _regler_setzen(seite, "cl-factor-goal-level", 10)
        assert not _sichtbar(seite, "#result")

    def test_ligaphase_spaete_antwort_nach_wechsel(self, seite):
        seite.einstellungen["zurueckhalten"] = True
        _cl_partie(seite)
        _ligaphase_oeffnen(seite)
        _ligaphase_simulieren(seite)
        seite.click(_karte("cl-season-approach", "classic"))

        _json(seite.zurueckgehalten.pop(), SAISONANTWORT)
        seite.wait_for_timeout(300)
        assert not _sichtbar(seite, "#cl-season-sim-result")
        assert seite.is_enabled("#cl-season-sim-btn")


class TestWappen:

    @staticmethod
    def _wappen(seite, ort):
        return seite.eval_on_selector_all(
            f"{ort} .match-crest",
            """k => k.map(n => ({
                tag: n.tagName.toLowerCase(),
                platzhalter: n.classList.contains('match-crest-placeholder'),
                src: n.getAttribute('src'), alt: n.getAttribute('alt'),
                geladen: n.tagName === 'IMG' ? (n.complete && n.naturalWidth > 0) : null,
                breite: n.getBoundingClientRect().width,
                hoehe: n.getBoundingClientRect().height}))""")

    def test_logos_in_auswahl_und_ergebnis(self, seite):
        seite.einstellungen["antwort"] = C23_ANTWORT
        _cl_partie(seite, dict(PARTIE, home_crest=WAPPEN_HOST + "5.png"))
        seite.wait_for_function(
            "() => Array.from(document.querySelectorAll('#selected-match-label img'))"
            ".every(i => i.complete)")

        auswahl = self._wappen(seite, "#selected-match-label")
        assert [w["src"] for w in auswahl] == [WAPPEN_HOST + "5.png",
                                               WAPPEN_HOST + "678.png"]
        assert all(w["geladen"] and w["alt"] == "" for w in auswahl)
        assert all((w["breite"], w["hoehe"]) == (32, 32) for w in auswahl)
        text = seite.eval_on_selector("#selected-match-label", "n => n.textContent")
        assert " ".join(text.split()) == "Heimteam gegen Gastteam"

        _simulieren(seite)
        _ergebnis_abwarten(seite)
        seite.wait_for_function(
            "() => Array.from(document.querySelectorAll('#match-title img'))"
            ".every(i => i.complete)")
        kopf = self._wappen(seite, "#match-title")
        assert [w["src"] for w in kopf] == [WAPPEN_HOST + "5.png",
                                            WAPPEN_HOST + "678.png"]
        assert all((w["breite"], w["hoehe"]) == (40, 40) for w in kopf)

    def test_defekt_fehlend_und_fremd_ergeben_den_platzhalter(self, seite):
        _cl_partie(seite, dict(PARTIE, home_crest=WAPPEN_HOST + "broken.png",
                               away_crest="https://evil.example/x.png"))
        seite.wait_for_function(
            "() => document.querySelectorAll("
            "'#selected-match-label .match-crest-placeholder').length === 2")
        wappen = self._wappen(seite, "#selected-match-label")
        assert all(w["platzhalter"] and w["tag"] == "span" for w in wappen)
        assert all((w["breite"], w["hoehe"]) == (32, 32) for w in wappen)
        assert not any("evil.example" in url for url in seite.fremde_anfragen)
        # Kein kaputtes Bildsymbol irgendwo im Kopf.
        assert seite.eval_on_selector_all(
            "#selected-match-label img", "k => k.length") == 0

        _cl_partie(seite, dict(PARTIE, home_crest=None, home_id=None,
                               away_crest=None, away_id=None))
        wappen = self._wappen(seite, "#selected-match-label")
        assert [w["platzhalter"] for w in wappen] == [True, True]

    def test_die_logos_gehoeren_zur_berechneten_partie(self, seite):
        seite.einstellungen["zurueckhalten"] = True
        _cl_partie(seite, dict(PARTIE, home_crest=WAPPEN_HOST + "5.png"))
        _simulieren(seite)
        # Waehrend der Rechnung eine andere Partie waehlen.
        _partie_waehlen(seite, dict(PARTIE, id=99, home_team="Andere",
                                    home_crest=WAPPEN_HOST + "86.png",
                                    home_id=86))
        _json(seite.zurueckgehalten.pop(), C23_ANTWORT)
        _ergebnis_abwarten(seite)

        kopf = self._wappen(seite, "#match-title")
        assert kopf[0]["src"] == WAPPEN_HOST + "5.png"


class TestLayout:

    @pytest.mark.parametrize("breite,nebeneinander", [(1280, True), (375, False),
                                                      (320, False)])
    def test_drei_karten_nebeneinander_oder_gestapelt(self, seite, breite,
                                                      nebeneinander):
        seite.set_viewport_size({"width": breite, "height": 900})
        _cl_partie(seite)

        for gruppe in ("cl-approach", "cl-season-approach"):
            if gruppe == "cl-season-approach":
                _ligaphase_oeffnen(seite)
            rahmen = seite.eval_on_selector_all(
                f"#{gruppe} .cl-approach-card",
                "k => k.map(n => { const r = n.getBoundingClientRect();"
                " return [r.left, r.top, r.width, r.height]; })")
            assert len(rahmen) == 3
            obere = [round(r[1]) for r in rahmen]
            linke = [round(r[0]) for r in rahmen]
            if nebeneinander:
                assert len(set(obere)) == 1, (gruppe, rahmen)
                assert linke == sorted(linke) and len(set(linke)) == 3
            else:
                assert len(set(linke)) == 1, (gruppe, rahmen)
                assert obere == sorted(obere) and len(set(obere)) == 3
            assert seite.evaluate(
                "() => document.documentElement.scrollWidth"
                " <= document.documentElement.clientWidth + 1"), (gruppe, breite)

    @pytest.mark.parametrize("breite,wappen,favorit_rechts", [
        (1280, 40, True), (375, 32, False), (320, 32, False)])
    def test_ergebniskopf_mit_langen_namen(self, seite, breite, wappen,
                                           favorit_rechts):
        seite.set_viewport_size({"width": breite, "height": 900})
        seite.einstellungen["antwort"] = dict(
            C23_ANTWORT, home_team=LANGE_PARTIE["home_team"],
            away_team=LANGE_PARTIE["away_team"])
        _cl_partie(seite, LANGE_PARTIE)
        _simulieren(seite)
        _ergebnis_abwarten(seite)
        seite.wait_for_function(
            "() => document.querySelectorAll('#match-title .match-crest').length === 2"
            " && Array.from(document.querySelectorAll('#match-title img'))"
            ".every(i => i.complete)")

        messung = seite.evaluate(
            """() => {
                const rechteck = s => document.querySelector(s).getBoundingClientRect();
                const panel = rechteck("#result");
                const haupt = rechteck("#result .result-header-main");
                const box = rechteck("#result .top-pick-box");
                const ueberstand = Array.from(document.querySelectorAll(
                        "#result .result-header *"))
                    .map(n => n.getBoundingClientRect())
                    .filter(r => r.width > 0)
                    .filter(r => r.right > panel.right + 1 || r.left < panel.left - 1)
                    .length;
                return {
                    ueberstand,
                    seite: document.documentElement.scrollWidth
                           <= document.documentElement.clientWidth + 1,
                    boxRechts: box.left >= haupt.right - 1 && box.top < haupt.bottom,
                    boxUnten: box.top >= haupt.bottom - 1,
                    wappen: Array.from(document.querySelectorAll("#match-title .match-crest"))
                        .map(n => [n.getBoundingClientRect().width,
                                   n.getBoundingClientRect().height]),
                    platzhalter: document.querySelectorAll(
                        "#match-title .match-crest-placeholder").length,
                };
            }""")
        assert messung["ueberstand"] == 0, messung
        assert messung["seite"], messung
        assert messung["wappen"] == [[wappen, wappen], [wappen, wappen]], messung
        # Das defekte Gastwappen ist zum Platzhalter geworden.
        assert messung["platzhalter"] == 1
        if favorit_rechts:
            assert messung["boxRechts"], messung
        else:
            assert messung["boxUnten"], messung

    def test_ligaphase_bei_320px(self, seite):
        seite.set_viewport_size({"width": 320, "height": 700})
        _cl_partie(seite)
        _ligaphase_oeffnen(seite)
        seite.click(_karte("cl-season-approach", "custom"))
        _ligaphase_simulieren(seite)
        seite.wait_for_selector("#cl-season-sim-result:not(.hidden)")
        assert seite.evaluate(
            "() => document.documentElement.scrollWidth"
            " <= document.documentElement.clientWidth + 1")
