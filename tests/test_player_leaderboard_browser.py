"""
Spieler-Bestenliste im echten Browser (Block C24, mit Korrektur).

Derselbe Harnisch wie tests/test_cl_approach_browser.py: Das Template wird
mit Jinja2 gerendert, die statischen Dateien kommen von der Platte, alle
API-Antworten werden ueber die Routenabfangung von Playwright geliefert.
Kein Server, keine Datenbank, kein Netz - jede fremde Anfrage wird
abgewiesen und mitgezaehlt.

Produktablauf seit der Korrektur: Filter setzen -> "Bestenliste erstellen"
druecken -> neues Ergebnis. Big Games haben keinen Kennzahl-Dropdown,
sondern die feste Rangfolge nach dem Big-Game-Score.

    python -m pytest tests/test_player_leaderboard_browser.py -q --e2e -m e2e
"""

import json
import os
from urllib.parse import parse_qs

import pytest

pytestmark = pytest.mark.e2e

pytest.importorskip(
    "playwright.sync_api",
    reason="Playwright ist nicht installiert - siehe tests/test_browser_smoke.py.",
)

from playwright.sync_api import sync_playwright  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = "http://footsim.test"
LOGO_HOST = "https://media.api-sports.io/"
LOGO_BILD = os.path.join(PROJECT_ROOT, "static", "icons", "icon-48.png")

INHALTSTYPEN = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".webmanifest": "application/manifest+json",
}

SAISONS = {
    "seasons": [
        {"season": 2026, "label": "2026/27", "is_current": True,
         "percentiles_available": False, "reference_season": 2025,
         "tournaments_available": {"euro": False, "world_cup": False},
         "tournaments_imported": {"euro": False, "world_cup": False}},
        {"season": 2025, "label": "2025/26", "is_current": False,
         "percentiles_available": True, "reference_season": 2025,
         "tournaments_available": {"euro": False, "world_cup": True},
         "tournaments_imported": {"euro": False, "world_cup": True}},
        {"season": 2024, "label": "2024/25", "is_current": False,
         "percentiles_available": True, "reference_season": 2024,
         "tournaments_available": {"euro": True, "world_cup": False},
         "tournaments_imported": {"euro": True, "world_cup": False}},
    ],
    "current_season": 2026,
    "min_query_length": 3,
    "leagues": [],
}

BIG_GAMES_SAISONS = {
    "available": True, "earliest_season": 2021, "latest_season": 2025,
    "max_span": 5,
    "seasons": [{"season": s, "label": f"{s}/{str(s + 1)[2:]}", "provisional": False}
                for s in range(2021, 2026)],
}

LANGER_NAME = ("Maximilian Alexander Konstantin von Hohenzollern-"
               "Sigmaringen-Brandenburg")

METRIKEN = {
    "all": [("rating", "Anbieterbewertung (API-Football)", "value", "higher_better")],
    "Attacker": [
        ("goal_contributions_per90", "Torbeteiligungen pro 90", "per90", "higher_better"),
        ("shots_on_per90", "Schüsse aufs Tor pro 90", "per90", "higher_better"),
        ("key_passes_per90", "Schlüsselpässe pro 90", "per90", "higher_better"),
    ],
    "Midfielder": [
        ("key_passes_per90", "Schlüsselpässe pro 90", "per90", "higher_better"),
        ("goal_contributions_per90", "Torbeteiligungen pro 90", "per90", "higher_better"),
    ],
    "Defender": [
        ("tackles_per90", "Tacklings pro 90", "per90", "higher_better"),
        ("interceptions_per90", "Abgefangene Bälle pro 90", "per90", "higher_better"),
        ("duels_won_pct", "Zweikampfquote", "rate", "higher_better"),
    ],
    "Goalkeeper": [
        ("saves_per90", "Paraden pro 90", "per90", "higher_better"),
        ("conceded_per90", "Gegentore pro 90", "per90", "lower_better"),
        ("rating", "Anbieterbewertung (API-Football)", "value", "higher_better"),
    ],
}

BIG_GAME_SCORE = {"key": "big_game_score", "label": "Big-Game-Score", "kind": "value",
                  "direction": "higher_better",
                  "description": "Leistung in großen Spielen, gewichtet nach "
                                 "Gegnerstärke und Spielbedeutung."}


def _meta(key, position):
    for k, label, kind, direction in METRIKEN[position]:
        if k == key:
            return {"key": k, "label": label, "kind": kind,
                    "direction": direction, "description": ""}
    return None


def optionen():
    return {
        "positions": {pos: [_meta(k, pos) for k, *_ in keys] for pos, keys in METRIKEN.items()},
        "big_games": {"metric": BIG_GAME_SCORE},
        "limits": [5, 10, 15, 20, 30],
        "default_limit": 10,
    }


def _zeilen(anzahl, position, praefix, wert_start=2.5):
    zeilen = []
    for i in range(anzahl):
        zeilen.append({
            "rank": i + 1, "player_id": 1000 + i,
            "name": LANGER_NAME if i == 1 else f"{praefix} {i + 1}",
            "team_name": "Verein mit einem sehr langen Namen FC" if i == 1 else f"Verein {i + 1}",
            "team_id": 500 + i,
            "team_logo": (None if i == 2 else
                          (LOGO_HOST + "football/teams/broken.png" if i == 3 else
                           LOGO_HOST + f"football/teams/{500 + i}.png")),
            "league": "bl1", "league_label": "Bundesliga",
            "position": "Attacker" if position == "all" else position,
            "minutes": 3000 - i * 50, "appearances": 34 - i,
            "value": round(wert_start - i * 0.05, 2),
        })
    return zeilen


def leaderboard_antwort(query, einstellungen=None):
    """Eine Antwort in der Form der echten Route, abhaengig von der Anfrage."""
    einstellungen = einstellungen or {}
    q = {k: v[0] for k, v in parse_qs(query).items()}
    position = q.get("position", "all")
    limit = int(q.get("limit", "10"))
    zeilenzahl = einstellungen.get("zeilen_ueberschuss") or limit

    if q.get("scope") == "big_games":
        basis = {"scope": "big_games", "position": position, "metric": BIG_GAME_SCORE,
                 "direction": "higher_better", "limit": limit, "ranking_key": "big_game_score",
                 "allowed_limits": [5, 10, 15, 20, 30], "allowed_metrics": [BIG_GAME_SCORE],
                 "source": "big_games_dataset", "season_from": int(q["season_from"]),
                 "season_to": int(q["season_to"]), "provisional": False,
                 "eligibility": {"min_matches": 3, "min_minutes": 180,
                                 "rule": "big_games_sufficient_sample"}}
        if not einstellungen.get("bg_verfuegbar"):
            return {**basis, "available": False, "reason": "dataset_missing", "rows": [],
                    "incomplete": True,
                    "coverage": {"seasons": [{"season": 2025, "dataset_status": "missing"}]}}
        return {**basis, "available": True, "reason": None, "incomplete": False,
                "rows": _zeilen(zeilenzahl, position, "Big-Game-Spieler", 9.87),
                "coverage": {"eligible": 412, "excluded_min_sample": 900}}

    metrik = q.get("metric") or METRIKEN[position][0][0]
    meta = _meta(metrik, position)
    season = int(q["season"])
    return {
        "scope": q.get("scope"), "position": position, "metric": meta,
        "direction": meta["direction"], "limit": limit,
        "allowed_limits": [5, 10, 15, 20, 30],
        "allowed_metrics": [_meta(k, position) for k, *_ in METRIKEN[position]],
        "source": "player_pool", "available": True, "reason": None,
        "rows": _zeilen(zeilenzahl, position, f"Spieler {metrik}"),
        "season": season, "season_label": f"{season}/{str(season + 1)[2:]}",
        "provisional": season >= 2026, "incomplete": season >= 2026,
        "eligibility": {"min_minutes": 450, "rule": "minutes_in_scope"},
        "coverage": {
            "leagues": [{"league": "bl1", "label": "Bundesliga"},
                        {"league": "pl", "label": "Premier League"}],
            "used_leagues": ["bl1", "pl"],
            "missing_leagues": ["bl1"] if season >= 2026 else [],
            "incomplete_leagues": ["bl1", "pl"] if season >= 2026 else [],
            "eligible": 511,
        },
    }


def _seite_rendern(locale="de"):
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


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instanz = playwright.chromium.launch()
        yield instanz
        instanz.close()


@pytest.fixture
def seite(browser):
    kontext = browser.new_context(locale="de-DE")
    blatt = kontext.new_page()

    seitenfehler = []
    konsolenfehler = []
    blatt.on("pageerror", lambda fehler: seitenfehler.append(str(fehler)))
    blatt.on("console", lambda m: konsolenfehler.append(m.text) if m.type == "error" else None)

    seiten = {sprache: _seite_rendern(sprache) for sprache in ("de", "en")}
    anfragen = []
    fremde = []
    zurueck = []
    einstellungen = {"zurueckhalten": False, "bg_verfuegbar": False, "zeilen_ueberschuss": None}

    def handler(route):
        anfrage = route.request
        if anfrage.url.startswith(LOGO_HOST):
            if anfrage.url.endswith("/broken.png"):
                route.fulfill(status=404, body="")
            else:
                route.fulfill(status=200, content_type="image/png",
                              body=open(LOGO_BILD, "rb").read())
            return
        if not anfrage.url.startswith(HOST):
            fremde.append(anfrage.url)
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
            route.fulfill(status=200,
                          content_type=INHALTSTYPEN.get(os.path.splitext(datei)[1],
                                                        "application/octet-stream"),
                          body=open(datei, "rb").read())
            return
        if pfad == "/api/player-seasons":
            _json(route, SAISONS)
            return
        if pfad == "/api/big-games-seasons":
            _json(route, BIG_GAMES_SAISONS)
            return
        if pfad == "/api/player-leaderboard-options":
            _json(route, optionen())
            return
        if pfad == "/api/player-leaderboard":
            anfragen.append(abfrage)
            if einstellungen["zurueckhalten"]:
                zurueck.append((route, abfrage))
                return
            _json(route, leaderboard_antwort(abfrage, einstellungen))
            return
        if pfad == "/api/auth/me":
            _json(route, {"authenticated": False}, status=401)
            return
        if pfad == "/api/seasons":
            _json(route, [{"season": 2025, "label": "2025/26", "is_current": True}])
            return
        _json(route, [])

    blatt.route("**/*", handler)
    blatt.goto(f"{HOST}/")
    blatt.wait_for_function("() => typeof setActiveArea === 'function'")

    blatt.anfragen = anfragen
    blatt.fremde = fremde
    blatt.zurueck = zurueck
    blatt.einstellungen = einstellungen
    blatt.seitenfehler = seitenfehler
    blatt.konsolenfehler = konsolenfehler
    yield blatt

    assert not seitenfehler, f"JavaScript-Ausnahme: {seitenfehler}"
    kontext.close()


def _spielerbereich(seite):
    seite.evaluate("() => setActiveArea('players')")
    seite.wait_for_function("() => pcState.ready === true")


def _sichtbar(seite, auswahl):
    return seite.eval_on_selector(
        auswahl, "n => !n.classList.contains('hidden') && n.offsetParent !== null")


def _bestenliste(seite):
    """Nur in die Ansicht wechseln - ohne etwas zu erstellen."""
    seite.click('.pc-view-btn[data-view="leaderboard"]')
    seite.wait_for_function("() => pcState.leaderboard.catalog !== null")


def _erstellen(seite):
    vorher = len(seite.anfragen)
    seite.click("#pc-lb-generate")
    for _ in range(150):
        if len(seite.anfragen) > vorher:
            break
        seite.wait_for_timeout(30)
    else:
        raise AssertionError("keine Bestenlistenanfrage nach dem Klick")
    if not seite.einstellungen["zurueckhalten"]:
        seite.wait_for_selector("#pc-lb-result .pc-lb-row, #pc-lb-result .pc-lb-unavailable")


def _letzte_anfrage(seite):
    assert seite.anfragen, "keine Bestenlistenanfrage"
    return {k: v[0] for k, v in parse_qs(seite.anfragen[-1]).items()}


def _zeilenzahl(seite):
    return seite.eval_on_selector_all("#pc-lb-result .pc-lb-row", "r => r.length")


# ---------------------------------------------------------------------------
# Struktur und Standard
# ---------------------------------------------------------------------------

class TestStruktur:

    def test_standard_ist_der_spielervergleich(self, seite):
        _spielerbereich(seite)
        assert seite.get_attribute('.pc-view-btn[data-view="compare"]', "aria-checked") == "true"
        assert _sichtbar(seite, "#pc-compare-area")
        assert not _sichtbar(seite, "#pc-leaderboard")
        assert _sichtbar(seite, "#pc-search-a") and _sichtbar(seite, "#pc-search-b")
        assert not _sichtbar(seite, "#pc-lb-limit")
        assert seite.anfragen == []

    def test_der_umschalter_steht_direkt_unter_der_datenbasis(self, seite):
        _spielerbereich(seite)
        reihenfolge = seite.evaluate("""() => {
            const pos = (a, b) => a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING;
            const datenbasis = document.querySelector('.pc-scope-nav').closest('.pc-scope-block');
            const umschalter = document.getElementById('pc-view-nav').closest('.pc-scope-block');
            const zeitraum = document.getElementById('bg-period-block');
            const slotA = document.querySelector('.pc-slot[data-slot="a"]');
            return {
                naechstesElement: datenbasis.nextElementSibling === umschalter,
                vorZeitraum: Boolean(pos(umschalter, zeitraum)),
                vorSlots: Boolean(pos(umschalter, slotA)),
            };
        }""")
        assert reihenfolge == {"naechstesElement": True, "vorZeitraum": True, "vorSlots": True}

    def test_ohne_klick_keine_liste(self, seite):
        _spielerbereich(seite)
        _bestenliste(seite)
        seite.wait_for_timeout(300)
        assert seite.anfragen == []
        assert _zeilenzahl(seite) == 0
        assert not _sichtbar(seite, "#pc-compare-area")
        assert not _sichtbar(seite, "#pc-result-panel")
        assert _sichtbar(seite, "#pc-lb-generate")
        assert seite.inner_text("#pc-lb-generate") == "Bestenliste erstellen"
        assert "„Bestenliste erstellen“ drücken" in seite.inner_text("#pc-lb-status")

    def test_der_knopf_steht_unter_den_filtern(self, seite):
        _spielerbereich(seite)
        _bestenliste(seite)
        lage = seite.evaluate("""() => {
            const knopf = document.getElementById('pc-lb-generate').getBoundingClientRect();
            const filter = document.querySelector('.pc-lb-controls').getBoundingClientRect();
            return {unter: knopf.top >= filter.bottom - 1, hoehe: knopf.height};
        }""")
        assert lage["unter"] is True and lage["hoehe"] >= 44

    def test_tastaturbedienung_des_umschalters(self, seite):
        _spielerbereich(seite)
        seite.focus('.pc-view-btn[data-view="compare"]')
        seite.keyboard.press("ArrowRight")
        assert seite.get_attribute('.pc-view-btn[data-view="leaderboard"]', "aria-checked") == "true"
        seite.keyboard.press("ArrowLeft")
        assert seite.get_attribute('.pc-view-btn[data-view="compare"]', "aria-checked") == "true"


# ---------------------------------------------------------------------------
# Erstellen, Top-N, Invalidierung
# ---------------------------------------------------------------------------

class TestErstellen:

    def test_klick_laedt_die_liste_mit_den_standardwerten(self, seite):
        _spielerbereich(seite)
        _bestenliste(seite)
        _erstellen(seite)
        q = _letzte_anfrage(seite)
        assert q == {"scope": "club_all", "position": "all", "limit": "10",
                     "metric": "rating", "season": "2025"}
        assert _zeilenzahl(seite) == 10
        assert seite.is_enabled("#pc-lb-generate")

    def test_doppelklick_erzeugt_keine_doppelanfrage(self, seite):
        _spielerbereich(seite)
        _bestenliste(seite)
        seite.einstellungen["zurueckhalten"] = True
        seite.dblclick("#pc-lb-generate")
        seite.click("#pc-lb-generate", force=True)
        seite.wait_for_timeout(300)
        assert len(seite.anfragen) == 1
        assert not seite.is_enabled("#pc-lb-generate")
        assert "Bestenliste wird erstellt" in seite.inner_text("#pc-lb-status")
        route, q = seite.zurueck.pop()
        _json(route, leaderboard_antwort(q))
        seite.wait_for_selector("#pc-lb-result .pc-lb-row")
        assert seite.is_enabled("#pc-lb-generate")

    @pytest.mark.parametrize("anzahl", ["5", "10", "15", "20", "30"])
    def test_top_n(self, seite, anzahl):
        _spielerbereich(seite)
        _bestenliste(seite)
        seite.select_option("#pc-lb-limit", anzahl)
        _erstellen(seite)
        assert _letzte_anfrage(seite)["limit"] == anzahl
        assert _zeilenzahl(seite) == int(anzahl)

    def test_top_30_zeigt_hoechstens_30(self, seite):
        _spielerbereich(seite)
        _bestenliste(seite)
        seite.einstellungen["zeilen_ueberschuss"] = 45
        seite.select_option("#pc-lb-limit", "30")
        _erstellen(seite)
        assert _zeilenzahl(seite) == 30

    def test_top_n_optionen_sind_genau_die_erlaubten(self, seite):
        _spielerbereich(seite)
        werte = seite.eval_on_selector_all("#pc-lb-limit option", "o => o.map(n => n.value)")
        assert werte == ["5", "10", "15", "20", "30"]
        assert seite.input_value("#pc-lb-limit") == "10"

    @pytest.mark.parametrize("aenderung", ["limit", "metric", "season", "position", "scope"])
    def test_filterwechsel_entfernt_das_alte_ergebnis(self, seite, aenderung):
        _spielerbereich(seite)
        _bestenliste(seite)
        _erstellen(seite)
        assert _zeilenzahl(seite) == 10
        anzahl = len(seite.anfragen)

        if aenderung == "limit":
            seite.select_option("#pc-lb-limit", "5")
        elif aenderung == "metric":
            seite.click('#pc-radar-view .pc-position-btn[data-position="Goalkeeper"]')
            seite.wait_for_timeout(100)
            _erstellen(seite)
            anzahl = len(seite.anfragen)
            seite.select_option("#pc-lb-metric", "conceded_per90")
        elif aenderung == "season":
            seite.select_option("#pc-lb-season", "2024")
        elif aenderung == "position":
            seite.click('#pc-radar-view .pc-position-btn[data-position="Defender"]')
        else:
            seite.click('#pc-radar-view .pc-scope-btn[data-scope="league"]')

        seite.wait_for_timeout(250)
        assert _zeilenzahl(seite) == 0
        assert len(seite.anfragen) == anzahl         # keine automatische Neuberechnung
        assert "erneut" in seite.inner_text("#pc-lb-status")

        _erstellen(seite)
        assert len(seite.anfragen) == anzahl + 1
        assert _zeilenzahl(seite) > 0

    def test_kennzahl_und_richtung(self, seite):
        _spielerbereich(seite)
        _bestenliste(seite)
        seite.click('#pc-radar-view .pc-position-btn[data-position="Goalkeeper"]')
        seite.wait_for_function("() => document.querySelectorAll('#pc-lb-metric option').length === 3")
        seite.select_option("#pc-lb-metric", "conceded_per90")
        _erstellen(seite)
        assert _letzte_anfrage(seite)["metric"] == "conceded_per90"
        assert "Gegentore" in seite.inner_text(".pc-lb-heading")
        assert "niedrigerer Wert" in seite.inner_text("#pc-lb-result")

    def test_vorlaeufige_saison(self, seite):
        _spielerbereich(seite)
        _bestenliste(seite)
        seite.select_option("#pc-lb-season", "2026")
        _erstellen(seite)
        text = seite.inner_text("#pc-lb-result")
        assert "Vorläufig" in text and "Daten unvollständig" in text


# ---------------------------------------------------------------------------
# Big Games
# ---------------------------------------------------------------------------

class TestBigGames:

    def test_kein_kennzahl_dropdown_sondern_big_game_score(self, seite):
        _spielerbereich(seite)
        seite.click('#pc-radar-view .pc-scope-btn[data-scope="big_games"]')
        _bestenliste(seite)
        assert not _sichtbar(seite, "#pc-lb-metric-field")
        assert not _sichtbar(seite, "#pc-lb-season-field")
        assert _sichtbar(seite, "#pc-lb-bg-metric")
        assert seite.inner_text("#pc-lb-bg-metric .pc-lb-fixed-name") == "Big-Game-Score"
        assert "gewichtet nach Gegnerstärke und Spielbedeutung" in seite.inner_text("#pc-lb-bg-hint")
        assert "Anbieterbewertung" not in seite.inner_text("#pc-leaderboard")
        assert _sichtbar(seite, "#pc-lb-generate")
        assert _sichtbar(seite, "#bg-period-block")
        assert seite.anfragen == []

    def test_ohne_datensatz_bleibt_der_knopf_mit_hinweis(self, seite):
        _spielerbereich(seite)
        seite.click('#pc-radar-view .pc-scope-btn[data-scope="big_games"]')
        _bestenliste(seite)
        _erstellen(seite)
        q = _letzte_anfrage(seite)
        assert q["scope"] == "big_games" and "metric" not in q and "season" not in q
        assert q["season_from"] == "2025" and q["season_to"] == "2025"
        assert _zeilenzahl(seite) == 0
        text = seite.inner_text("#pc-lb-result")
        assert "Bestenliste derzeit nicht verfügbar" in text
        assert _sichtbar(seite, "#pc-lb-generate") and seite.is_enabled("#pc-lb-generate")
        for technisch in ("dataset", "fixture", "cache", "provider", "API-Football", "C24"):
            assert technisch.lower() not in text.lower()

    def test_vollstaendiger_datensatz_wird_nach_score_angezeigt(self, seite):
        seite.einstellungen["bg_verfuegbar"] = True
        _spielerbereich(seite)
        seite.click('#pc-radar-view .pc-position-btn[data-position="Attacker"]')
        seite.click('#pc-radar-view .pc-scope-btn[data-scope="big_games"]')
        _bestenliste(seite)
        seite.select_option("#pc-lb-limit", "15")
        _erstellen(seite)
        assert _zeilenzahl(seite) == 15
        assert seite.inner_text(".pc-lb-heading") == "Sortiert nach: Big-Game-Score"
        erste = seite.eval_on_selector("#pc-lb-result .pc-lb-row",
                                       "z => ({wert: z.querySelector('.pc-lb-value').textContent,"
                                       " fakten: z.querySelector('.pc-lb-facts').textContent})")
        assert erste["wert"] == "9,87"
        assert "Big Games" in erste["fakten"] and "Minuten" in erste["fakten"]
        assert "Anbieterbewertung" not in seite.inner_text("#pc-leaderboard")

    def test_uebernahme_aus_big_games(self, seite):
        seite.einstellungen["bg_verfuegbar"] = True
        _spielerbereich(seite)
        seite.click('#pc-radar-view .pc-scope-btn[data-scope="big_games"]')
        _bestenliste(seite)
        _erstellen(seite)
        seite.click("#pc-lb-result .pc-lb-row:nth-child(1) .pc-lb-adopt-a")
        assert seite.evaluate("() => [pcState.view, pcState.scope, pcState.a.player.player_id]") == [
            "compare", "big_games", 1000]


# ---------------------------------------------------------------------------
# Uebernahme, Sprache, Logos
# ---------------------------------------------------------------------------

class TestUebernahme:

    @pytest.mark.parametrize("slot", ["a", "b"])
    def test_spieler_wird_ueber_die_id_uebernommen(self, seite, slot):
        _spielerbereich(seite)
        seite.click('#pc-radar-view .pc-position-btn[data-position="Attacker"]')
        seite.click('#pc-radar-view .pc-scope-btn[data-scope="league"]')
        _bestenliste(seite)
        _erstellen(seite)
        seite.click(f"#pc-lb-result .pc-lb-row:nth-child(1) .pc-lb-adopt-{slot}")
        zustand = seite.evaluate(f"""() => ({{
            view: pcState.view, id: pcState.{slot}.player && pcState.{slot}.player.player_id,
            saison: pcState.{slot}.season, position: pcState.position, scope: pcState.scope,
        }})""")
        assert zustand == {"view": "compare", "id": 1000, "saison": 2025,
                           "position": "Attacker", "scope": "league"}

    def test_englisch(self, seite):
        seite.goto(f"{HOST}/?lang=en")
        seite.wait_for_function("() => document.documentElement.lang === 'en'")
        _spielerbereich(seite)
        assert seite.inner_text('.pc-view-btn[data-view="leaderboard"]') == "Leaderboard"
        _bestenliste(seite)
        assert seite.inner_text("#pc-lb-generate") == "Generate leaderboard"
        _erstellen(seite)
        text = seite.eval_on_selector("#pc-leaderboard", "n => n.textContent")
        for erwartet in ("Metric", "Top 10", "As player A", "As player B"):
            assert erwartet in text, erwartet
        seite.click('#pc-radar-view .pc-scope-btn[data-scope="big_games"]')
        assert seite.inner_text("#pc-lb-bg-metric .pc-lb-fixed-name") == "Big Game Score"
        assert "weighted by opponent strength and match importance" in seite.inner_text("#pc-lb-bg-hint")

    def test_logos_platzhalter_und_lange_namen(self, seite):
        seite.set_viewport_size({"width": 1280, "height": 900})
        _spielerbereich(seite)
        _bestenliste(seite)
        _erstellen(seite)
        seite.wait_for_function(
            "() => document.querySelectorAll('#pc-lb-result .match-crest-placeholder').length >= 2")
        wappen = seite.eval_on_selector_all(
            "#pc-lb-result .pc-lb-row .pc-lb-crest > *",
            "k => k.map(n => ({platzhalter: n.classList.contains('match-crest-placeholder'),"
            " w: n.getBoundingClientRect().width}))")
        assert wappen[2]["platzhalter"] and wappen[3]["platzhalter"]
        assert all(w["w"] == 28 for w in wappen)
        assert seite.evaluate("""() => {
            const zeile = document.querySelectorAll('#pc-lb-result .pc-lb-row')[1];
            return zeile.scrollWidth <= zeile.clientWidth + 1;
        }""")


# ---------------------------------------------------------------------------
# Spaete Antworten
# ---------------------------------------------------------------------------

class TestSpaeteAntworten:

    def test_filterwechsel_waehrend_der_anfrage(self, seite):
        _spielerbereich(seite)
        _bestenliste(seite)
        seite.einstellungen["zurueckhalten"] = True
        _erstellen(seite)
        seite.select_option("#pc-lb-limit", "5")
        route, q = seite.zurueck.pop()
        try:
            _json(route, leaderboard_antwort(q))
        except Exception:
            pass   # bereits abgebrochen - genau das ist gewollt
        seite.wait_for_timeout(250)
        assert _zeilenzahl(seite) == 0
        assert seite.is_enabled("#pc-lb-generate")

        seite.einstellungen["zurueckhalten"] = False
        _erstellen(seite)
        assert _letzte_anfrage(seite)["limit"] == "5" and _zeilenzahl(seite) == 5

    def test_ansichtswechsel_waehrend_der_anfrage(self, seite):
        _spielerbereich(seite)
        _bestenliste(seite)
        seite.einstellungen["zurueckhalten"] = True
        _erstellen(seite)
        seite.click('.pc-view-btn[data-view="compare"]')
        route, q = seite.zurueck.pop()
        try:
            _json(route, leaderboard_antwort(q))
        except Exception:
            pass
        seite.wait_for_timeout(250)
        seite.click('.pc-view-btn[data-view="leaderboard"]')
        assert _zeilenzahl(seite) == 0
        assert seite.is_enabled("#pc-lb-generate")

    def test_datenbasiswechsel_waehrend_der_anfrage(self, seite):
        _spielerbereich(seite)
        _bestenliste(seite)
        seite.einstellungen["zurueckhalten"] = True
        _erstellen(seite)
        seite.click('#pc-radar-view .pc-scope-btn[data-scope="big_games"]')
        route, q = seite.zurueck.pop()
        try:
            _json(route, leaderboard_antwort(q))
        except Exception:
            pass
        seite.wait_for_timeout(250)
        assert _zeilenzahl(seite) == 0
        assert _sichtbar(seite, "#pc-lb-bg-metric")


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

class TestLayout:

    @pytest.mark.parametrize("breite", [1280, 375, 320])
    @pytest.mark.parametrize("scope", ["club_all", "big_games"])
    def test_kein_ueberlauf_und_bedienbar(self, seite, breite, scope):
        seite.set_viewport_size({"width": breite, "height": 900})
        seite.einstellungen["bg_verfuegbar"] = True
        _spielerbereich(seite)
        if scope == "big_games":
            seite.click('#pc-radar-view .pc-scope-btn[data-scope="big_games"]')
        _bestenliste(seite)
        seite.select_option("#pc-lb-limit", "30")
        _erstellen(seite)
        assert _zeilenzahl(seite) == 30
        messung = seite.evaluate("""() => {
            const rechteck = s => Array.from(document.querySelectorAll(s))
                .filter(n => n.offsetParent !== null).map(n => n.getBoundingClientRect());
            const panel = document.querySelector('#pc-leaderboard').getBoundingClientRect();
            const knoepfe = rechteck('#pc-lb-result .pc-lb-adopt');
            const felder = rechteck('#pc-leaderboard select, .pc-view-btn, #pc-lb-generate');
            const zeilen = Array.from(document.querySelectorAll('#pc-lb-result .pc-lb-row'));
            return {
                seite: document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
                knopfhoehe: Math.min(...knoepfe.map(r => r.height)),
                feldhoehe: Math.min(...felder.map(r => r.height)),
                ueberstand: zeilen.filter(z => z.scrollWidth > z.clientWidth + 1).length,
                ausserhalb: knoepfe.filter(r => r.right > panel.right + 1 || r.left < panel.left - 1).length,
            };
        }""")
        assert messung["seite"], messung
        assert messung["knopfhoehe"] >= 44, messung
        assert messung["feldhoehe"] >= 44, messung
        assert messung["ueberstand"] == 0, messung
        assert messung["ausserhalb"] == 0, messung

    def test_keine_konsolenfehler(self, seite):
        _spielerbereich(seite)
        _bestenliste(seite)
        _erstellen(seite)
        seite.select_option("#pc-lb-limit", "5")
        _erstellen(seite)
        relevant = [m for m in seite.konsolenfehler
                    if "net::ERR_FAILED" not in m and "Failed to load resource" not in m]
        assert relevant == [], relevant
