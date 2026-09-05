"""
Vertraege der Champions-League-Ansatzwahl (C8B).

WAS DIESE DATEI LEISTET - UND WAS NICHT
---------------------------------------
Sie laeuft in JEDEM Testlauf, ohne Browser, ohne Datenbank, ohne Netz.
Sie belegt drei Dinge:

    1. Die Oberflaeche traegt die Bestandteile, an denen C8B haengt -
       Markup, Uebersetzungen, Gestaltung.
    2. Die Skalen im Browsercode und die Grenzen im Backend sind
       DIESELBEN Zahlen. Laufen sie auseinander, faellt dieser Test,
       nicht erst ein Nutzer.
    3. Genau die Nutzlast, die das Frontend baut, wird vom Endpunkt
       angenommen - und die Ligen behalten ihren bisherigen Vertrag.

Sie belegt NICHT, dass die Regler im Browser wirklich rechnen. Das kann
nur ein Browser zeigen; dafuer gibt es tests/test_cl_approach_browser.py.
Beide Schichten zusammen sind der Nachweis, keine allein.
"""

import json
import os
import re

import pytest

from src.predict import cl_custom_factors as ccf

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SEASON = 2025
BAYERN, AJAX = 5, 678


def _lies(*teile):
    with open(os.path.join(PROJECT_ROOT, *teile), encoding="utf-8") as quelle:
        return quelle.read()


def _sw_block(script):
    """Genau der Service-Worker-Abschnitt, ohne den Rest der Datei."""
    start = script.index('if ("serviceWorker" in navigator) {')
    ende = script.index('window.addEventListener("load"', start)
    return script[start:ende]


@pytest.fixture(scope="module")
def html():
    return _lies("templates", "index.html")


@pytest.fixture(scope="module")
def script():
    return _lies("static", "script.js")


@pytest.fixture(scope="module")
def css():
    return _lies("static", "style.css")


@pytest.fixture(scope="module")
def kataloge():
    return {
        sprache: json.loads(_lies("static", "i18n", f"{sprache}.json"))
        for sprache in ("de", "en")
    }


def _reglerbloecke(script):
    """
    Liest CL_FACTOR_CONTROLS aus dem Browsercode aus.

    Bewusst am Quelltext und nicht an einer Kopie im Test: Eine Kopie
    wuerde genau dann noch stimmen, wenn das Original schon falsch ist.
    """
    start = script.index("const CL_FACTOR_CONTROLS = [")
    block = script[start:script.index("];", start)]
    eintraege = {}
    for zeile in re.findall(r"\{[^}]*\}", block):
        felder = dict(re.findall(
            r"(\w+):\s*(-?\d+|true|false|\"[^\"]*\")", zeile))
        name = felder["field"].strip('"')
        eintraege[name] = {
            "min": int(felder["min"]),
            "max": int(felder["max"]),
            "base": int(felder["base"]),
            "signed": felder["signed"] == "true",
            "inFactors": felder["inFactors"] == "true",
            "id": felder["id"].strip('"'),
        }
    return eintraege


# ---------------------------------------------------------------------------
# 1. Markup
# ---------------------------------------------------------------------------

class TestMarkup:

    def test_die_auswahl_steht_im_panel_ausgewaehlt(self, html):
        """
        Nicht irgendwo auf der Seite: zwischen der Simulationszahl und
        dem Simulieren-Knopf, also dort, wo der Nutzer gerade hinschaut.
        """
        panel = html[html.index('<div id="sim-controls"'):]
        panel = panel[:panel.index('id="simulate-btn"')]

        assert 'id="cl-approach"' in panel
        assert 'id="cl-factors"' in panel
        assert panel.index('id="simulations"') < panel.index('id="cl-approach"')

    def test_beide_ansaetze_sind_eine_echte_radiogruppe(self, html):
        assert 'class="cl-approach-cards" role="radiogroup"' in html
        assert 'aria-labelledby="cl-approach-label"' in html
        assert html.count('data-approach="ml"') == 1
        assert html.count('data-approach="custom"') == 1
        assert html.count('role="radio"') >= 2
        assert 'aria-checked="true"' in html
        assert 'aria-checked="false"' in html

    def test_ml_ist_die_vorausgewaehlte_karte(self, html):
        karte = html[html.index('data-approach="ml"') - 400:
                     html.index('data-approach="ml"')]
        assert 'class="cl-approach-card active"' in karte
        assert 'aria-checked="true"' in karte

    def test_die_auswahl_ist_nicht_nur_an_der_farbe_erkennbar(self, html, css):
        """
        Rand und Hintergrund allein waeren eine reine Farbaussage. Der
        Haken traegt auch ohne Farbunterscheidung.
        """
        assert html.count('class="cl-approach-check"') == 2
        assert ".cl-approach-card.active .cl-approach-check" in css

    def test_es_gibt_genau_vier_regler_mit_beschriftung_und_anzeige(self, html):
        assert html.count('class="cl-factor-slider"') == 4
        assert html.count('type="range"') == 4
        for kennung, unten, oben in (("attack", -30, 30), ("defence", -30, 30),
                                     ("home", -50, 50), ("ml", 0, 100)):
            assert f'for="cl-factor-{kennung}"' in html
            assert f'id="cl-factor-{kennung}-value"' in html
            eingabe = html[html.index(f'id="cl-factor-{kennung}" type="range"'):]
            eingabe = eingabe[:eingabe.index(">")]
            assert f'min="{unten}"' in eingabe
            assert f'max="{oben}"' in eingabe
            assert 'value="0"' in eingabe

    def test_es_gibt_genau_einen_zuruecksetzen_knopf(self, html):
        assert html.count('id="cl-factor-reset"') == 1
        # Kein zweiter grosser Primaerknopf neben "Simulieren".
        assert 'id="cl-factor-reset" class="simulate-btn"' not in html

    def test_die_seed_zeile_ist_ansprechbar_geworden(self, html):
        assert 'class="controls checkbox-row" id="use-seed-row"' in html
        assert 'id="use-seed" type="checkbox"' in html

    def test_die_zweispaltige_zeile_faellt_ohne_checkbox_zusammen(self, html,
                                                                  css, script):
        """
        Sonst staende das Zahlenfeld auf halber Breite und daneben waere
        eine leere Haelfte.
        """
        assert 'class="sim-controls-row" id="sim-controls-row"' in html
        assert ".sim-controls-row.single-column {" in css
        # Umgeschaltet wird per Klasse aus dem Code, nicht per :has() -
        # den Selektor kennen aeltere WebViews nicht, und das Ergebnis
        # waere dort ein halbes Formular.
        assert 'classList.toggle("single-column", istCl)' in script

    def test_die_neue_oberflaeche_verspricht_nichts_unbelegtes(self, html,
                                                               kataloge):
        bereich = html[html.index('<div id="cl-approach"'):
                       html.index('id="simulate-btn"')]
        for wort in ("Monte Carlo", "monte carlo", "beste", "genaueste",
                     "garantiert", "exakt"):
            assert wort not in bereich

        for katalog in kataloge.values():
            texte = " ".join(wert for schluessel, wert in katalog.items()
                             if schluessel.startswith("clApproach."))
            for wort in ("Monte Carlo", "garantiert", "guaranteed",
                         "most accurate", "beste Prognose"):
                assert wort not in texte


# ---------------------------------------------------------------------------
# 2. Skalen - Browser und Backend muessen dieselben Zahlen meinen
# ---------------------------------------------------------------------------

class TestSkalen:

    def test_es_sind_genau_die_vier_erwarteten_regler(self, script):
        regler = _reglerbloecke(script)
        assert set(regler) == {"attack", "defence", "home_advantage",
                               "ml_weight"}

    def test_die_drei_faktoren_treffen_die_backendgrenzen_exakt(self, script):
        regler = _reglerbloecke(script)
        for name, (unten, oben) in ccf.FACTOR_BOUNDS.items():
            eintrag = regler[name]
            assert eintrag["base"] == 1
            assert eintrag["inFactors"] is True
            assert (eintrag["base"] * 100 + eintrag["min"]) / 100 == unten
            assert (eintrag["base"] * 100 + eintrag["max"]) / 100 == oben

    def test_das_modellgewicht_trifft_die_backendgrenzen_exakt(self, script):
        eintrag = _reglerbloecke(script)["ml_weight"]
        assert eintrag["base"] == 0
        assert eintrag["inFactors"] is False
        assert eintrag["min"] / 100 == ccf.ML_WEIGHT_MIN
        assert eintrag["max"] / 100 == ccf.ML_WEIGHT_MAX

    def test_der_neutralstand_ist_bei_jedem_regler_null_prozent(self, script):
        """
        0 % muss bei jedem Regler den neutralen Backendwert ergeben -
        1,0 fuer die Faktoren und 0,0 fuer das Modellgewicht. Genau das
        ist der Zustand, in dem C8A bitgleich zur Baseline rechnet.
        """
        regler = _reglerbloecke(script)
        for name, eintrag in regler.items():
            assert eintrag["min"] <= 0 <= eintrag["max"]
            neutral = (eintrag["base"] * 100 + 0) / 100
            if eintrag["inFactors"]:
                assert neutral == ccf.NEUTRAL_FACTORS[name]
            else:
                assert neutral == ccf.ML_WEIGHT_DEFAULT_CUSTOM

    def test_nur_der_ml_regler_hat_keinen_nullpunkt_in_der_mitte(self, script):
        regler = _reglerbloecke(script)
        assert regler["ml_weight"]["signed"] is False
        for name in ("attack", "defence", "home_advantage"):
            assert regler[name]["signed"] is True
            assert regler[name]["min"] == -regler[name]["max"]

    def test_die_kennungen_stimmen_mit_dem_markup_ueberein(self, script, html):
        for eintrag in _reglerbloecke(script).values():
            assert f'id="{eintrag["id"]}" type="range"' in html
            assert f'id="{eintrag["id"]}-value"' in html

    def test_die_ansatznamen_sind_die_des_backends(self, script):
        assert f'const CL_APPROACH_ML = "{ccf.APPROACH_ML}";' in script
        assert f'const CL_APPROACH_CUSTOM = "{ccf.APPROACH_CUSTOM}";' in script


# ---------------------------------------------------------------------------
# 3. Browsercode: Isolation und Rechenweg
# ---------------------------------------------------------------------------

class TestBrowsercode:

    def test_die_neuen_felder_haengen_am_wettbewerbstyp(self, script):
        """
        Ein bloss verborgenes Feld wuerde weitersenden. Der Zusatz muss
        deshalb IM Champions-League-Zweig stehen.
        """
        assert 'if (state.competitionType === "cl") {\n            Object.assign(payload, clApproachPayload());' in script

    def test_die_nutzlast_wird_an_genau_einer_stelle_gebaut(self, script):
        assert script.count("function clApproachPayload()") == 1
        assert script.count("Object.assign(payload, clApproachPayload())") == 1

    def test_ml_sendet_niemals_faktoren_oder_gewicht(self, script):
        block = script[script.index("function clApproachPayload()"):]
        block = block[:block.index("\n}")]
        rueckgabe = block[:block.index("const nutzlast")]
        # Ohne Kommentarzeilen: dort stehen 'factors' und 'ml_weight'
        # ausdruecklich als Erklaerung, warum sie NICHT mitgehen.
        code = "\n".join(zeile for zeile in rueckgabe.splitlines()
                         if not zeile.strip().startswith("//"))
        assert "return { approach: CL_APPROACH_ML };" in code
        assert "factors" not in code
        assert "ml_weight" not in code

    def test_die_umrechnung_vermeidet_gleitkomma_artefakte(self, script):
        """
        base + prozent / 100 ergibt fuer -3 % den Wert 0.9700000000000001
        und der stuende woertlich im Request.
        """
        block = script[script.index("function clFactorBackendValue("):]
        block = block[:block.index("\n}")]
        assert "(regler.base * 100 + begrenzt) / 100" in block

    def test_der_seedhaken_wird_bei_der_cl_nicht_gelesen(self, script):
        assert 'use_seed: state.competitionType === "cl"\n            ? false\n            : el("use-seed").checked,' in script

    def test_der_zustand_faellt_bei_jedem_wettbewerbswechsel_zurueck(self, script):
        assert script.count("function clResetApproachState()") == 1
        # Einmal in selectCompetition, einmal in resetSimulationView.
        assert script.count("clResetApproachState();") == 2

    def test_die_oberflaeche_wird_vor_dem_einblenden_gesetzt(self, script):
        block = script[script.index("function selectMatch("):]
        block = block[:block.index("\n}")]
        assert block.index("applyClApproachUi();") < block.index("show(simControls);")

    def test_der_zustand_lebt_nur_im_browser(self, script):
        """
        Keine Speicherung, keine Serverbindung. Die Einstellungen gelten
        fuer diesen Browserzustand und diesen Request - sonst nichts.
        """
        block = script[script.index("/* ---------- 11a."):]
        block = block[:block.index("async function runSimulation()")]
        for verboten in ("localStorage", "sessionStorage", "document.cookie",
                         "fetch(", "indexedDB"):
            assert verboten not in block

    def test_ein_sprachwechsel_erneuert_die_prozentanzeigen(self, script):
        assert 'if (typeof clApproachRetranslate === "function") {' in script
        assert script.count("function clApproachRetranslate()") == 1


# ---------------------------------------------------------------------------
# 4. Ligen und Saisonsimulationen bleiben unberuehrt
# ---------------------------------------------------------------------------

class TestIsolation:

    def test_keine_liga_datei_kennt_die_neuen_felder(self):
        for datei in ("league_match_sim.py", "season_sim.py",
                      "simulate_scores.py", "cl_season_sim.py"):
            quelle = _lies("src", "predict", datei)
            for feld in ("cl_custom_factors", "approach", "ml_weight",
                         "home_advantage"):
                assert feld not in quelle, (datei, feld)

    def test_die_saisonsimulationen_bekommen_keine_regler(self, html):
        for bereich in ('id="season-sim-controls"', 'id="cl-season-sim-controls"'):
            block = html[html.index(bereich):]
            block = block[:block.index("</div>\n\n                    <div id=")]
            assert "cl-approach" not in block
            assert "cl-factor" not in block

    def test_die_saison_endpunkte_kennen_kein_approach(self):
        app_py = _lies("app.py")
        for route in ("/api/season-simulate", "/api/cl-season-simulate"):
            if route not in app_py:
                continue
            block = app_py[app_py.index(route):]
            block = block[:block.index("\n@app.route", 1) if "\n@app.route" in block
                          else len(block)]
            assert "parse_simulation_options" not in block

    def test_nur_die_champions_league_darf_approach_senden(self):
        app_py = _lies("app.py")
        assert 'competition_code != "cl"' in app_py
        assert "'approach' wird nur fuer die Champions " in app_py


# ---------------------------------------------------------------------------
# 5. Uebersetzungen
# ---------------------------------------------------------------------------

class TestUebersetzungen:

    ERWARTET = (
        "clApproach.heading", "clApproach.mlTitle", "clApproach.mlDescription",
        "clApproach.customTitle", "clApproach.customDescription",
        "clApproach.attack", "clApproach.defence", "clApproach.homeAdvantage",
        "clApproach.mlInfluence", "clApproach.reset", "clApproach.percent",
    )

    def test_alle_schluessel_stehen_in_beiden_katalogen(self, kataloge):
        for schluessel in self.ERWARTET:
            for sprache, katalog in kataloge.items():
                assert schluessel in katalog, (sprache, schluessel)
                assert katalog[schluessel].strip(), (sprache, schluessel)

    def test_die_deutschen_kerntexte_stehen_woertlich_so_da(self, kataloge):
        de = kataloge["de"]
        assert de["clApproach.mlTitle"] == "ML-Prognose"
        assert de["clApproach.mlDescription"] == \
            "Historisch trainiertes mathematisches Modell"
        assert de["clApproach.customTitle"] == "Individuell"
        assert de["clApproach.customDescription"] == \
            "Gewichte die Match-Faktoren selbst"
        assert de["clApproach.attack"] == "Offensive"
        assert de["clApproach.defence"] == "Defensive"
        assert de["clApproach.homeAdvantage"] == "Heimvorteil"
        assert de["clApproach.mlInfluence"] == "ML-Einfluss"
        assert de["clApproach.reset"] == "Zurücksetzen"

    def test_englisch_ist_uebersetzt_und_nicht_kopiert(self, kataloge):
        de, en = kataloge["de"], kataloge["en"]
        for schluessel in ("clApproach.mlTitle", "clApproach.mlDescription",
                           "clApproach.customTitle",
                           "clApproach.customDescription",
                           "clApproach.homeAdvantage", "clApproach.reset"):
            assert de[schluessel] != en[schluessel], schluessel

    def test_der_prozentbaustein_traegt_in_beiden_sprachen(self, kataloge):
        for katalog in kataloge.values():
            assert "{value}" in katalog["clApproach.percent"]
            assert "%" in katalog["clApproach.percent"]

    def test_die_oberflaeche_holt_jeden_text_aus_dem_katalog(self, html,
                                                             kataloge):
        bereich = html[html.index('<div id="cl-approach"'):
                       html.index('id="simulate-btn"')]
        verwendet = set(re.findall(r'data-i18n="(clApproach\.[^"]+)"', bereich))
        assert verwendet == set(self.ERWARTET) - {"clApproach.percent"}
        assert verwendet <= kataloge["en"].keys()


# ---------------------------------------------------------------------------
# 6. Gestaltung
# ---------------------------------------------------------------------------

class TestGestaltung:

    def test_die_neuen_klassen_sind_gestaltet(self, css):
        for auswahl in (".cl-approach {", ".cl-approach-cards {",
                        ".cl-approach-card {", ".cl-approach-card.active {",
                        ".cl-approach-check {", ".cl-factors {",
                        ".cl-factor-slider {", ".cl-factor-reset {"):
            assert auswahl in css, auswahl

    def test_es_kommt_keine_neue_farbwelt_dazu(self, css):
        """
        Der Hell-Modus traegt sich nur mit, solange alle Farben aus den
        bestehenden Tokens kommen. Ein fester Hexwert waere im hellen
        Modus falsch - und niemand saehe es im dunklen.
        """
        block = css[css.index(".cl-approach {"):css.index(".cl-factor-reset:focus-visible")]
        farben = re.findall(r"(?:color|background|border-color)\s*:\s*([^;]+);",
                            block)
        for wert in farben:
            wert = wert.strip()
            if wert in ("transparent", "inherit", "none"):
                continue
            assert "var(--" in wert, wert

    def test_der_regler_bekommt_eine_griffige_flaeche(self, css):
        block = css[css.index(".cl-factor-slider {"):]
        block = block[:block.index("}")]
        assert "height: 44px" in block
        assert "width: 100%" in block

    def test_appearance_none_bleibt_auf_die_neuen_regler_beschraenkt(self, css):
        """
        Ein globales input-Reset haette die Zahlenfelder und Haken der
        gesamten Anwendung mitgenommen.
        """
        for zeile in re.findall(r"[^\n{}]+\{[^}]*appearance:\s*none[^}]*\}", css):
            auswahl = zeile.split("{")[0].strip()
            assert "cl-factor-slider" in auswahl or "pc-" in auswahl \
                or auswahl.startswith("."), auswahl

    def test_die_mobile_fassung_ist_bedacht(self, css):
        assert ".cl-approach-card {\n        padding:" in css
        assert ".cl-factor-slider {\n        max-width: 100%;" in css

    def test_bewegungsarme_darstellung_wird_beruecksichtigt(self, css):
        block = css[css.index(".cl-approach {"):]
        block = block[:block.index("/* ============================================================\n   19.")]
        assert "@media (prefers-reduced-motion: reduce)" in block


# ---------------------------------------------------------------------------
# 7. Auslieferung
# ---------------------------------------------------------------------------

class TestAuslieferung:

    def test_die_cacheversion_wurde_erhoeht(self):
        """
        index.html kommt network-first, script.js aber
        stale-while-revalidate. Ohne Versionssprung staende die neue
        Auswahl beim ersten Aufruf nach einem Deployment sichtbar, aber
        unverdrahtet auf der Seite.
        """
        sw = _lies("static", "sw.js")
        treffer = re.search(r'CACHE_NAME = "footsim-v(\d+)"', sw)
        assert treffer, "CACHE_NAME nicht gefunden"
        assert int(treffer.group(1)) >= 38

    def test_es_gibt_keinen_zweiten_cache_mechanismus(self, html):
        assert "?v=" not in html
        assert "cachebust" not in html.lower()

    def test_ein_wechsel_des_workers_laedt_die_seite_neu(self, script):
        """
        C0B-Fix D. Ohne diesen Handler bleibt nach einem Deployment
        genau eine Navigation mit neuem HTML und altem JavaScript
        stehen - die Auswahl waere sichtbar, aber tot.
        """
        assert 'navigator.serviceWorker.addEventListener("controllerchange"' \
            in script
        assert "window.location.reload()" in script

    def test_der_erste_besuch_laedt_nicht_neu(self, script):
        """
        Ohne vorherigen Controller gibt es keinen alten Stand zu
        ersetzen. Ein Reload waere dort reine Verzoegerung.
        """
        block = _sw_block(script)
        assert "const hatteController = Boolean(" \
               "navigator.serviceWorker.controller);" in block
        assert "if (!hatteController || neuLadenLaeuft) return;" in block

    def test_es_gibt_genau_einen_reload_pro_seitenleben(self, script):
        block = _sw_block(script)
        assert block.count("window.location.reload()") == 1
        assert "neuLadenLaeuft = true;" in block

    def test_der_reload_braucht_keinen_zusaetzlichen_speicher(self, script):
        """
        Die Sprachwahl bleibt die einzige lokale Praeferenz in
        script.js (siehe test_player_routes). Ein Zeitstempel-Guard
        waere hier ohnehin gegenstandslos: Nach dem Reload ist der neue
        Worker bereits der Controller, ein zweites controllerchange
        folgt nicht.
        """
        block = _sw_block(script)
        for speicher in ("sessionStorage", "localStorage", "document.cookie"):
            assert speicher not in block, speicher

    def test_der_worker_uebernimmt_sofort(self):
        sw = _lies("static", "sw.js")
        assert "self.skipWaiting();" in sw
        assert "self.clients.claim();" in sw

    def test_script_und_stylesheet_bleiben_im_service_worker(self):
        sw = _lies("static", "sw.js")
        for pfad in ("/static/script.js", "/static/style.css",
                     "/static/i18n/de.json", "/static/i18n/en.json"):
            assert f'"{pfad}"' in sw


# ---------------------------------------------------------------------------
# 8. Der Endpunkt nimmt genau diese Nutzlast an
# ---------------------------------------------------------------------------

class TestEndpunkt:
    """
    Die Gegenprobe zur Frontend-Seite: Was clApproachPayload() baut, muss
    der Endpunkt annehmen. Eine Abweichung faellt hier auf und nicht erst
    als 400 vor dem Nutzer.
    """

    @pytest.fixture
    def client(self):
        from tests.conftest import mit_csrf

        import app as app_module

        app_module.app.config["TESTING"] = True
        with app_module.app.test_client() as verbindung:
            yield mit_csrf(verbindung)

    @staticmethod
    def _cl(**extra):
        return {"competition": "cl", "home_team": "Heim", "away_team": "Gast",
                "home_id": BAYERN, "away_id": AJAX, "season": SEASON,
                "simulations": 200, "use_seed": False, **extra}

    def test_die_ml_nutzlast_wird_angenommen(self, client):
        antwort = client.post("/api/simulate", json=self._cl(approach="ml"))
        assert antwort.status_code == 200
        assert antwort.get_json()["ml"]["requested_approach"] == "ml"

    @pytest.mark.parametrize("faktoren,gewicht", [
        ({"attack": 1.0, "defence": 1.0, "home_advantage": 1.0}, 0.0),
        ({"attack": 0.7, "defence": 0.7, "home_advantage": 0.5}, 0.0),
        ({"attack": 1.3, "defence": 1.3, "home_advantage": 1.5}, 1.0),
        ({"attack": 1.1, "defence": 0.8, "home_advantage": 1.25}, 0.5),
        ({"attack": 0.97, "defence": 1.07, "home_advantage": 0.99}, 0.29),
    ])
    def test_jede_reglerstellung_wird_angenommen(self, client, faktoren,
                                                 gewicht):
        antwort = client.post("/api/simulate", json=self._cl(
            approach="custom", factors=faktoren, ml_weight=gewicht))
        assert antwort.status_code == 200
        assert antwort.get_json()["ml"]["applied_factors"] == faktoren

    def test_die_reglergrenzen_liegen_innerhalb_der_erlaubten(self, script):
        """
        Kein Reglerende darf eine 400 ausloesen. Sonst waere der letzte
        Zentimeter des Reglers eine Fehlermeldung.
        """
        for name, eintrag in _reglerbloecke(script).items():
            for prozent in (eintrag["min"], 0, eintrag["max"]):
                wert = (eintrag["base"] * 100 + prozent) / 100
                if eintrag["inFactors"]:
                    ccf.parse_options({"approach": "custom",
                                       "factors": {name: wert}})
                else:
                    ccf.parse_options({"approach": "custom",
                                       "ml_weight": wert})

    def test_ein_ligarequest_ohne_die_neuen_felder_bleibt_gueltig(self, client,
                                                                   monkeypatch):
        """
        Geprueft wird ausschliesslich der Request-Vertrag: Ein Liga-
        Request ohne 'approach' muss C8B unveraendert erreichen und darf
        von den neuen Feldern nichts spueren.

        simulate_league_match wird deshalb gemockt. Ungemockt haengt der
        Aufruf an get_standings() fuer die AKTUELLE Saison (kein
        'season' im Request -> resolve_requested_season(None) ->
        laufende Saison) - das braucht echte Providerdaten oder einen
        gefuellten Disk-Cache. Auf einem frischen Checkout ohne
        data/cache/ (gitignored) und ohne Netzzugriff wirft das eine
        Ausnahme, die app.py bewusst breit abfaengt und korrekt als 500
        beantwortet (siehe app.py, except Exception: ... 500). Das ist
        seit jeher gewolltes Verhalten des Endpunkts, kein Fehler, den
        dieser Test aufdecken soll - er pruefte damit versehentlich
        Live-Providerverfuegbarkeit statt des C8B-Vertrags. Auf einer
        Maschine mit gefuelltem lokalem Cache blieb das unbemerkt; ein
        frischer CI-Runner deckte es zuverlaessig auf.
        """
        import app as app_module

        erhalten = {}

        def fake_simulate_league_match(**kwargs):
            erhalten.update(kwargs)
            return {"home_team": kwargs["home_team"],
                   "away_team": kwargs["away_team"]}

        monkeypatch.setattr(app_module, "simulate_league_match",
                            fake_simulate_league_match)

        antwort = client.post("/api/simulate", json={
            "competition": "bl1", "home_team": "Heim", "away_team": "Gast",
            "home_id": 5, "away_id": 4, "simulations": 200, "use_seed": True})

        assert antwort.status_code == 200
        # Der eigentliche C8B-Vertrag: keines der neuen Felder erreicht
        # den Liga-Simulator, weder als eigenes Argument noch versteckt.
        for feld in ("approach", "factors", "ml_weight", "options"):
            assert feld not in erhalten, feld

    def test_ein_ligarequest_mit_approach_wird_abgewiesen(self, client):
        antwort = client.post("/api/simulate", json={
            "competition": "bl1", "home_team": "Heim", "away_team": "Gast",
            "home_id": 5, "away_id": 4, "simulations": 200,
            "approach": "custom"})
        assert antwort.status_code == 400
        assert "Champions" in antwort.get_json()["error"]

    def test_die_fehlermeldung_zeigt_nichts_internes(self, client):
        antwort = client.post("/api/simulate",
                              json=self._cl(approach="custom",
                                            factors={"attack": 9.9}))
        assert antwort.status_code == 400
        text = antwort.get_json()["error"]
        for verboten in ("Traceback", "/", "\\", ".py", "sklearn", "numpy"):
            assert verboten not in text
