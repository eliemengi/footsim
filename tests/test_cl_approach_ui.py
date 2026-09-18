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

    def test_die_ligaphase_hat_dieselbe_auswahl_vor_dem_knopf(self, html):
        """C23: dieselben drei Karten auch in der CL-Ligaphase, zwischen
        der Laufzahl und dem Simulieren-Knopf."""
        panel = html[html.index('<div id="cl-season-sim-controls"'):]
        panel = panel[:panel.index('id="cl-season-sim-btn"')]

        assert 'id="cl-season-approach"' in panel
        assert 'id="cl-season-factors"' in panel
        assert (panel.index('id="cl-season-simulations"')
                < panel.index('id="cl-season-approach"'))

    def test_drei_ansaetze_sind_in_beiden_tabs_eine_echte_radiogruppe(self, html):
        """GEAENDERT IN C23: drei statt zwei Karten, und die Gruppe steht
        zweimal - Spielsimulation und Ligaphase. Jede Gruppe ist fuer sich
        eine vollstaendige Radiogruppe."""
        assert html.count('class="cl-approach-cards" role="radiogroup"') == 2
        assert 'aria-labelledby="cl-approach-label"' in html
        assert 'aria-labelledby="cl-season-approach-label"' in html
        for gruppe, ende in (('<div id="cl-approach"', 'id="cl-factors"'),
                             ('<div id="cl-season-approach"', 'id="cl-season-factors"')):
            block = html[html.index(gruppe):]
            block = block[:block.index(ende)]
            for ansatz in ("ml", "custom", "classic"):
                assert block.count(f'data-approach="{ansatz}"') == 1, (gruppe, ansatz)
            assert block.count('role="radio"') == 3, gruppe
            assert block.count('aria-checked="true"') == 1, gruppe
            assert block.count('aria-checked="false"') == 2, gruppe
        assert html.count('data-approach=') == 6

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
        assert html.count('class="cl-approach-check"') == 6
        assert html.count('class="cl-approach-check" aria-hidden="true"') == 6
        assert ".cl-approach-card.active .cl-approach-check" in css

    def test_es_gibt_genau_vier_regler_mit_beschriftung_und_anzeige(self, html):
        """Spielsimulation: vier Regler. Dazu kommen (C23) genau zwei in
        der Ligaphase - siehe den folgenden Test."""
        match = html[html.index('<div id="cl-factors"'):html.index('id="cl-factor-reset"')]
        assert match.count('class="cl-factor-slider"') == 4
        assert html.count('class="cl-factor-slider"') == 6
        assert html.count('type="range"') == 6
        for kennung, unten, oben in (("home-strength", -30, 30),
                                     ("away-strength", -30, 30),
                                     ("home", -50, 50),
                                     ("goal-level", -25, 25)):
            assert f'for="cl-factor-{kennung}"' in html
            assert f'id="cl-factor-{kennung}-value"' in html
            eingabe = html[html.index(f'id="cl-factor-{kennung}" type="range"'):]
            eingabe = eingabe[:eingabe.index(">")]
            assert f'min="{unten}"' in eingabe
            assert f'max="{oben}"' in eingabe
            assert 'value="0"' in eingabe

    def test_die_ligaphase_hat_nur_die_globalen_regler(self, html):
        """C23: Heimvorteil und Torniveau mit denselben Grenzen wie im
        Einzelspiel; Heim- und Auswaertsteam-Staerke fehlen dort."""
        block = html[html.index('<div id="cl-season-factors"'):
                     html.index('id="cl-season-factor-reset"')]
        assert block.count('class="cl-factor-slider"') == 2
        assert "strength" not in block
        assert 'data-i18n="clApproach.seasonTeamFactorsNote"' in block
        for kennung, unten, oben in (("home", -50, 50), ("goal-level", -25, 25)):
            assert f'for="cl-season-factor-{kennung}"' in block
            assert f'id="cl-season-factor-{kennung}-value"' in block
            eingabe = block[block.index(f'id="cl-season-factor-{kennung}" type="range"'):]
            eingabe = eingabe[:eingabe.index(">")]
            assert f'min="{unten}"' in eingabe
            assert f'max="{oben}"' in eingabe
            assert 'value="0"' in eingabe

    def test_es_gibt_genau_einen_zuruecksetzen_knopf(self, html):
        """Je Gruppe genau einer (C23: Spielsimulation und Ligaphase)."""
        assert html.count('id="cl-factor-reset"') == 1
        assert html.count('id="cl-season-factor-reset"') == 1
        # Kein zweiter grosser Primaerknopf neben "Simulieren".
        assert 'id="cl-factor-reset" class="simulate-btn"' not in html
        assert 'id="cl-season-factor-reset" class="simulate-btn"' not in html

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
        """
        GEAENDERT IN C23: "Monte Carlo" ist jetzt belegt - aber nur an
        EINER Stelle. Die klassische Simulation ist wortwoertlich eine
        Monte-Carlo-Simulation historischer Teamwerte (Poissonziehungen
        in cl_match_sim/cl_season_sim), und die Kartenbeschreibung ist
        vorgegeben. Ueberall sonst bleibt das Wort verboten, ebenso jede
        Guete- oder Garantieaussage.
        """
        for start, ende in (('<div id="cl-approach"', 'id="simulate-btn"'),
                            ('<div id="cl-season-approach"', 'id="cl-season-sim-btn"')):
            bereich = html[html.index(start):html.index(ende)]
            for wort in ("Monte Carlo", "monte carlo", "beste", "genaueste",
                         "garantiert", "exakt", "V2"):
                assert wort not in bereich, (start, wort)

        for katalog in kataloge.values():
            texte = " ".join(wert for schluessel, wert in katalog.items()
                             if schluessel.startswith(("clApproach.", "resultApproach."))
                             and schluessel != "clApproach.classicDescription")
            for wort in ("Monte Carlo", "Monte-Carlo", "garantiert",
                         "guaranteed", "most accurate", "beste Prognose", "V2"):
                assert wort not in texte, wort
            klassisch = katalog["clApproach.classicDescription"]
            assert "Monte" in klassisch
            for wort in ("garantiert", "guaranteed", "beste", "best", "exakt"):
                assert wort not in klassisch


# ---------------------------------------------------------------------------
# 2. Skalen - Browser und Backend muessen dieselben Zahlen meinen
# ---------------------------------------------------------------------------

class TestSkalen:

    def test_es_sind_genau_die_vier_erwarteten_regler(self, script):
        regler = _reglerbloecke(script)
        assert set(regler) == {"home_strength", "away_strength",
                               "home_advantage", "goal_level"}

    def test_die_vier_faktoren_treffen_die_backendgrenzen_exakt(self, script):
        regler = _reglerbloecke(script)
        for name, (unten, oben) in ccf.FACTOR_BOUNDS.items():
            eintrag = regler[name]
            assert eintrag["base"] == 1
            assert eintrag["inFactors"] is True
            assert (eintrag["base"] * 100 + eintrag["min"]) / 100 == unten
            assert (eintrag["base"] * 100 + eintrag["max"]) / 100 == oben

    def test_es_gibt_keinen_ml_regler_mehr(self, script):
        """
        GEAENDERT IN V2-C17.

        Der ML-Einfluss war ein Prozentregler und damit fachlich
        falsch: ML ist eine Modusauswahl, kein dosierbarer Anteil.
        Die Auswahl steht in den beiden Karten darueber; ein Regler
        daneben suggerierte eine Mischung, die es nicht gibt.
        """
        regler = _reglerbloecke(script)
        assert "ml_weight" not in regler
        assert not any("ml" in name for name in regler)
        for eintrag in regler.values():
            assert eintrag["inFactors"] is True, (
                "jeder sichtbare Regler ist ein echter Faktor")

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

    def test_jeder_regler_hat_seinen_nullpunkt_in_der_mitte(self, script):
        """
        GEAENDERT IN V2-C17.

        Vorher fiel der ML-Regler aus der Reihe: Er lief von 0 bis 100
        Prozent und hatte keinen neutralen Mittelpunkt. Seit er
        entfallen ist, gilt fuer JEDEN sichtbaren Regler dieselbe
        Bedienlogik - Mitte ist neutral, links weniger, rechts mehr.
        """
        regler = _reglerbloecke(script)
        assert len(regler) == 4
        for name, eintrag in regler.items():
            assert eintrag["signed"] is True, name
            assert eintrag["min"] == -eintrag["max"], name
            assert eintrag["base"] == 1, name

    def test_die_kennungen_stimmen_mit_dem_markup_ueberein(self, script, html):
        for eintrag in _reglerbloecke(script).values():
            assert f'id="{eintrag["id"]}" type="range"' in html
            assert f'id="{eintrag["id"]}-value"' in html

    def test_die_ansatznamen_sind_die_des_backends(self, script):
        assert f'const CL_APPROACH_ML = "{ccf.APPROACH_ML}";' in script
        assert f'const CL_APPROACH_CUSTOM = "{ccf.APPROACH_CUSTOM}";' in script
        assert f'const CL_APPROACH_CLASSIC = "{ccf.APPROACH_CLASSIC}";' in script
        assert ccf.APPROACHES == ("ml", "custom", "classic")

    def test_die_ligaphase_kennt_genau_die_globalen_regler(self, script):
        """C23: seasonId nur bei den Faktoren, die das Backend in der
        Ligaphase annimmt (ccf.SEASON_FACTOR_NAMES)."""
        start = script.index("const CL_FACTOR_CONTROLS = [")
        block = script[start:script.index("];", start)]
        mit_saison = set()
        for zeile in re.findall(r"\{[^}]*\}", block):
            name = re.search(r'field:\s*"([^"]+)"', zeile).group(1)
            saison = re.search(r'seasonId:\s*("([^"]+)"|null)', zeile)
            assert saison, name
            if saison.group(2):
                mit_saison.add(name)
        assert mit_saison == set(ccf.SEASON_FACTOR_NAMES)


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
        # GEAENDERT IN C23: Derselbe Zweig traegt ml UND classic - alles
        # ausser custom sendet ausschliesslich den Ansatz.
        assert "if (state.clApproach !== CL_APPROACH_CUSTOM) {" in code
        assert "return { approach: state.clApproach };" in code
        assert "factors" not in code
        assert "ml_weight" not in code

    def test_die_ligaphase_sendet_den_ansatz_ausdruecklich(self, script):
        """C23: Ohne approach folgte der Server seiner Umgebung, und die
        Tabelle rechnete womoeglich anders als die gewaehlte Karte."""
        block = script[script.index("function clSeasonApproachParams()"):]
        block = block[:block.index("\n}")]
        assert "new URLSearchParams({ approach: state.clApproach })" in block
        assert "if (state.clApproach === CL_APPROACH_CUSTOM) {" in block
        assert "regler.seasonId" in block
        assert "ml_weight" not in block
        assert "factors" not in block
        lauf = script[script.index("async function runClSeasonSim()"):]
        lauf = lauf[:lauf.index("\n}")]
        assert "clSeasonApproachParams().toString()" in lauf

    def test_spaete_antworten_ueberschreiben_nichts(self, script):
        """C23: Eine Antwort, die vor einem Ansatzwechsel oder vor einer
        neueren Anfrage angefordert wurde, wird verworfen."""
        for funktion, zaehler, darstellen in (
                ("async function runSimulation()", "state.simRequestSeq",
                 "renderResult(data"),
                ("async function runClSeasonSim()", "state.clSeasonRequestSeq",
                 "if (data.empty_state)")):
            block = script[script.index(funktion):]
            block = block[:block.index("\n}")]
            assert f"const anfrage = ++{zaehler};" in block
            assert "const epoche = state.clApproachEpoch;" in block
            assert (f"if (anfrage !== {zaehler} || epoche !== state.clApproachEpoch) {{"
                    in block)
            # Die Pruefung steht direkt nach dem Abruf und VOR jeder
            # Darstellung.
            abruf = block.index("await fetchJson(")
            pruefung = block.index(f"if (anfrage !== {zaehler}")
            assert abruf < pruefung < block.index(darstellen)
            # Knopf und Fehlermeldung gehoeren nur der neuesten Anfrage.
            assert block.count(f"if (anfrage === {zaehler})") == 2

    def test_ein_ansatzwechsel_setzt_das_ergebnis_zurueck(self, script):
        """C23: Ein altes Ergebnis darf nie unter einer anders gewaehlten
        Karte stehen bleiben."""
        block = script[script.index("function clSetApproach("):]
        block = block[:block.index("\n}")]
        assert "clInvalidateResults();" in block
        inval = script[script.index("function clInvalidateResults()"):]
        inval = inval[:inval.index("\n}")]
        assert "state.clApproachEpoch += 1;" in inval
        assert "hide(resultBox);" in inval
        assert "hide(clSeasonSimResult);" in inval
        # Reglerzug und Zuruecksetzen sind ebenfalls eine andere Rechnung.
        assert script.count("clInvalidateResults();") >= 3

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
        """GEAENDERT IN C23: cl_season_sim.py ist aus dieser Liste
        herausgenommen - die CL-Ligaphase nimmt den Ansatz jetzt an. Ihr
        Vertrag steht im folgenden Test und in
        test_cl_custom_api::test_die_cl_saisonsimulation_nutzt_nur_die_
        zentrale_ansatzlogik. Die nationalen Ligen bleiben unberuehrt."""
        for datei in ("league_match_sim.py", "season_sim.py",
                      "simulate_scores.py"):
            quelle = _lies("src", "predict", datei)
            for feld in ("cl_custom_factors", "approach", "ml_weight",
                         "home_advantage"):
                assert feld not in quelle, (datei, feld)

    def test_die_cl_ligaphase_kennt_nur_die_globalen_faktoren(self):
        quelle = _lies("src", "predict", "cl_season_sim.py")
        for feld in ("ml_weight", "home_strength", "away_strength"):
            assert feld not in quelle, feld

    def test_nur_die_cl_ligaphase_bekommt_regler(self, html):
        """GEAENDERT IN C23: Die Ligen-Saisonsimulation bleibt ohne
        Ansatzwahl; die CL-Ligaphase bekommt dieselben drei Karten und
        die beiden globalen Regler."""
        block = html[html.index('id="season-sim-controls"'):]
        block = block[:block.index("</div>\n\n                    <div id=")]
        assert "cl-approach" not in block
        assert "cl-factor" not in block

        block = html[html.index('id="cl-season-sim-controls"'):]
        block = block[:block.index('id="cl-season-sim-result"')]
        assert 'id="cl-season-approach"' in block
        assert 'id="cl-season-factor-home"' in block
        assert 'id="cl-season-factor-goal-level"' in block
        for fremd in ("home-strength", "away-strength", 'id="cl-factor-'):
            assert fremd not in block, fremd

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
        "clApproach.classicTitle", "clApproach.classicDescription",
        "clApproach.homeStrength", "clApproach.awayStrength", "clApproach.homeAdvantage",
        "clApproach.goalLevel", "clApproach.reset", "clApproach.percent",
        "clApproach.seasonTeamFactorsNote",
    )

    ERGEBNISZEILE = (
        "resultApproach.computedWith", "resultApproach.mlFallback",
        "resultApproach.noLeagueStage", "resultApproach.seasonPartial",
        "resultApproach.seasonLeagueStage", "resultApproach.noOpenFixtures",
    )

    def test_alle_schluessel_stehen_in_beiden_katalogen(self, kataloge):
        for schluessel in self.ERWARTET + self.ERGEBNISZEILE:
            for sprache, katalog in kataloge.items():
                assert schluessel in katalog, (sprache, schluessel)
                assert katalog[schluessel].strip(), (sprache, schluessel)

    def test_die_deutschen_kerntexte_stehen_woertlich_so_da(self, kataloge):
        """GEAENDERT IN C23: die vorgegebenen Kartentexte, ohne "V2"."""
        de = kataloge["de"]
        assert de["clApproach.mlTitle"] == "Machine Learning"
        assert de["clApproach.mlDescription"] == \
            "Trainiertes Modell auf Basis historischer Spieldaten."
        assert de["clApproach.customTitle"] == "Eigene Einschätzung"
        assert de["clApproach.customDescription"] == \
            "Stelle die Faktoren selbst ein."
        assert de["clApproach.classicTitle"] == "Klassische Simulation"
        assert de["clApproach.classicDescription"] == \
            "Historische Teamwerte mit Monte-Carlo-Simulation."
        assert de["clApproach.homeStrength"] == "Heimteam-Stärke"
        assert de["clApproach.awayStrength"] == "Auswärtsteam-Stärke"
        assert de["clApproach.homeAdvantage"] == "Heimvorteil"
        assert de["clApproach.goalLevel"] == "Torniveau"
        assert de["clApproach.reset"] == "Zurücksetzen"
        assert de["resultApproach.computedWith"] == "Berechnet mit: {approach}"
        assert de["resultApproach.mlFallback"] == \
            "Machine Learning war hier nicht verfügbar. Berechnet wurde klassisch."

    def test_die_englischen_kerntexte_stehen_woertlich_so_da(self, kataloge):
        en = kataloge["en"]
        assert en["clApproach.mlTitle"] == "Machine learning"
        assert en["clApproach.mlDescription"] == \
            "Trained model based on historical match data."
        assert en["clApproach.customTitle"] == "Your own assessment"
        assert en["clApproach.customDescription"] == "Set the factors yourself."
        assert en["clApproach.classicTitle"] == "Classic simulation"
        assert en["clApproach.classicDescription"] == \
            "Historical team ratings with Monte Carlo simulation."
        assert en["resultApproach.computedWith"] == "Calculated with: {approach}"

    def test_kein_katalog_nennt_interne_namen(self, kataloge):
        """C23: keine sichtbare "V2-Prognose", keine Modell-IDs."""
        for sprache, katalog in kataloge.items():
            for schluessel in self.ERWARTET + self.ERGEBNISZEILE:
                wert = katalog[schluessel]
                for intern in ("V2", "candidate", "Kandidat", "bundle",
                               "model_id", "c14-", "c16-", "c20-"):
                    assert intern not in wert, (sprache, schluessel, intern)
            assert "V2-Prognose" not in json.dumps(katalog, ensure_ascii=False)
            assert "V2 forecast" not in json.dumps(katalog, ensure_ascii=False)

    def test_die_platzhalter_der_ergebniszeile_passen(self, kataloge):
        for katalog in kataloge.values():
            assert "{approach}" in katalog["resultApproach.computedWith"]
            assert {"{ml}", "{total}"} <= set(
                re.findall(r"\{\w+\}", katalog["resultApproach.seasonPartial"]))
            assert {"{applied}", "{total}"} <= set(
                re.findall(r"\{\w+\}", katalog["resultApproach.seasonLeagueStage"]))

    def test_englisch_ist_uebersetzt_und_nicht_kopiert(self, kataloge):
        de, en = kataloge["de"], kataloge["en"]
        for schluessel in ("clApproach.mlTitle", "clApproach.mlDescription",
                           "clApproach.customTitle",
                           "clApproach.customDescription",
                           "clApproach.classicTitle",
                           "clApproach.classicDescription",
                           "clApproach.seasonTeamFactorsNote",
                           "clApproach.homeAdvantage", "clApproach.reset") \
                + self.ERGEBNISZEILE:
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
        assert verwendet == set(self.ERWARTET) - {
            "clApproach.percent", "clApproach.seasonTeamFactorsNote"}
        assert verwendet <= kataloge["en"].keys()

        # C23: Die Ligaphase verwendet dieselben Kartentexte, dazu den
        # Hinweis, aber keine Teamstaerken.
        bereich = html[html.index('<div id="cl-season-approach"'):
                       html.index('id="cl-season-sim-btn"')]
        verwendet = set(re.findall(r'data-i18n="(clApproach\.[^"]+)"', bereich))
        assert verwendet == set(self.ERWARTET) - {
            "clApproach.percent", "clApproach.homeStrength",
            "clApproach.awayStrength"}
        assert verwendet <= kataloge["de"].keys() & kataloge["en"].keys()


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

    def test_drei_spalten_und_unter_600px_untereinander(self, css):
        """C23: drei Karten nebeneinander, unter 600px gestapelt."""
        assert (".cl-approach-cards {\n    display: grid;\n"
                "    grid-template-columns: repeat(3, minmax(0, 1fr));") in css
        block = css[css.index("@media (max-width: 600px) {"):]
        block = block[:block.index("\n}\n")]
        assert ".cl-approach-cards {\n        grid-template-columns: 1fr;" in block

    def test_logos_und_ergebniszeile_sind_gestaltet(self, css):
        """C23: feste Wappengroesse, Platzhalter derselben Groesse,
        umbrechende Namen, schrumpfende linke Kopfspalte - und nur Farben
        aus den Tokens."""
        for auswahl in (".match-heading-teams {", ".match-heading-team {",
                        ".match-heading-name {", ".match-crest {",
                        ".match-crest-placeholder {", ".result-header-main {",
                        ".result-approach {"):
            assert auswahl in css, auswahl
        wappen = css[css.index(".match-crest {"):]
        wappen = wappen[:wappen.index("}")]
        assert "width: 40px" in wappen and "height: 40px" in wappen
        assert "object-fit: contain" in wappen
        name = css[css.index(".match-heading-name {"):]
        assert "overflow-wrap: anywhere" in name[:name.index("}")]
        kopf = css[css.index(".result-header-main {"):]
        assert "min-width: 0" in kopf[:kopf.index("}")]

        block = css[css.index("/* ---------- Mannschaftslogos und ehrliche"):
                    css.index(".result-approach {")]
        for wert in re.findall(r"(?:color|background|border(?:-color)?)\s*:\s*([^;]+);",
                               block):
            wert = wert.strip()
            if wert in ("transparent", "inherit", "none"):
                continue
            assert "var(--" in wert, wert

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

    @pytest.mark.parametrize("faktoren", [
        {"home_strength": 1.0, "away_strength": 1.0, "home_advantage": 1.0, "goal_level": 1.0},
        {"home_strength": 0.7, "away_strength": 0.7, "home_advantage": 0.5, "goal_level": 0.75},
        {"home_strength": 1.3, "away_strength": 1.3, "home_advantage": 1.5, "goal_level": 1.25},
        {"home_strength": 1.1, "away_strength": 0.8, "home_advantage": 1.25, "goal_level": 1.1},
        {"home_strength": 0.97, "away_strength": 1.07, "home_advantage": 0.99, "goal_level": 0.98},
    ])
    def test_jede_reglerstellung_wird_angenommen(self, client, faktoren):
        antwort = client.post("/api/simulate", json=self._cl(
            approach="custom", factors=faktoren))
        assert antwort.status_code == 200
        assert antwort.get_json()["ml"]["applied_factors"] == faktoren
        assert antwort.get_json()["ml"]["applied"] is False

    @pytest.mark.parametrize("gewicht", [0.0, 0.1, 0.29, 0.5, 0.75, 0.99, 1.0,
                                         -1, 2, 50])
    def test_ml_gewicht_wird_ueber_die_echte_api_abgewiesen(self, client,
                                                             gewicht):
        """
        GEAENDERT IN DER V2-C17-HAERTUNG.

        Bis hierher akzeptierte genau dieser Request (approach='custom'
        mit einer Reglerstellung PLUS 'ml_weight') jeden Gewichtswert
        zwischen 0 und 1 und lieferte 200 - das war der tatsaechliche,
        ueber die echte HTTP-API von aussen erreichbare Blend-Kanal
        zwischen der individualisierten Baseline und der vollen
        ML-Korrektur (siehe test_jede_reglerstellung_wird_angenommen
        oben, vorher parametrisiert mit genau diesen Gewichten). Jetzt
        lehnt dieselbe Route denselben Request mit 400 ab, fuer jeden
        Wert - auch fuer 0,0 und 1,0, die vorher gueltig waren.
        """
        antwort = client.post("/api/simulate", json=self._cl(
            approach="custom",
            factors={"home_strength": 1.1, "away_strength": 0.8,
                     "home_advantage": 1.25, "goal_level": 1.1},
            ml_weight=gewicht))
        assert antwort.status_code == 400
        assert "ml_weight" in antwort.get_json()["error"]

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
                                            factors={"home_strength": 9.9}))
        assert antwort.status_code == 400
        text = antwort.get_json()["error"]
        for verboten in ("Traceback", "/", "\\", ".py", "sklearn", "numpy"):
            assert verboten not in text
