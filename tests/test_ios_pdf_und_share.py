"""
Statische Absicherung des iOS-PDF-Downloadwegs und des Teilen-Knopfes.

WARUM STATISCH UND NICHT NUR IM BROWSER
---------------------------------------
Das Verhalten selbst prueft tests/test_browser_smoke.py im echten
Browser - das ist der aussagekraeftigere Test. Diese Datei sichert die
Stellen ab, die im Browser NICHT beobachtbar sind:

  * dass der Vertrag zwischen Webseite und Swift-Huelle zusammenpasst
    (Route, Feldnamen, Kanalnamen) - die Huelle laeuft hier nicht mit
  * dass der Browserpfad unveraendert geblieben ist
  * dass bestimmte Dinge NICHT im Code stehen (Base64-Transport,
    blob-Download im iOS-Zweig)

Absichtlich KEINE Tests, die nur nach beliebigen Textfragmenten suchen.
Geprueft werden Strukturen: dass genau ein Formular gebaut wird, dass
das CSRF-Feld daran haengt, dass der iOS-Zweig vor dem fetch-Zweig
zurueckkehrt.
"""

import json
import re
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IOS_PROJEKT = Path(r"C:\Users\elieb\Documents\DevProjects\FootSim-iOS")


@pytest.fixture(scope="module")
def pdf_js():
    return (PROJECT_ROOT / "static" / "pdfmerge.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def script_js():
    return (PROJECT_ROOT / "static" / "script.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def index_html():
    return (PROJECT_ROOT / "templates" / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pdf_html():
    return (PROJECT_ROOT / "templates" / "pdfmerge.html").read_text(encoding="utf-8")


def _ios_zweig(quelltext):
    """Der Codeabschnitt, der nur im iOS-Modus laeuft."""
    start = quelltext.index("function mergeUeberFormular")
    ende = quelltext.index("async function mergeFiles")
    return quelltext[start:ende]


def _browser_zweig(quelltext):
    """Der Abschnitt ab dem klassischen FormData/fetch-Pfad."""
    return quelltext[quelltext.index("const formData = new FormData();"):]


# ---------------------------------------------------------------------------
# 1. Der iOS-Downloadweg
# ---------------------------------------------------------------------------

class TestIosDownloadweg:
    def test_gleiche_route_und_methode(self, pdf_js):
        """Keine zweite Backendroute - dieselbe wie im Browser."""
        assert 'const PDF_ROUTE = "/tools/pdf/merge";' in pdf_js
        zweig = _ios_zweig(pdf_js)
        assert 'formular.method = "POST"' in zweig
        assert "formular.action = PDF_ROUTE" in zweig

    def test_multipart_form_data(self, pdf_js):
        assert 'formular.enctype = "multipart/form-data"' in _ios_zweig(pdf_js)

    def test_csrf_feld_ist_am_formular(self, pdf_js):
        """
        Beim Formular-POST gibt es keinen X-CSRFToken-Header. Ohne das
        Feld antwortet CSRFProtect mit 400 - der Schutz wird NICHT
        umgangen, sondern anders bedient.
        """
        zweig = _ios_zweig(pdf_js)
        assert 'tokenFeld.name = "csrf_token"' in zweig
        assert "tokenFeld.value = csrfToken()" in zweig
        # Das Feld muss auch wirklich angehaengt werden.
        assert re.search(r"formular\.append\([^)]*tokenFeld[^)]*\)", zweig)

    def test_dateien_werden_vollstaendig_uebernommen(self, pdf_js):
        """
        DataTransfer ist der einzige Weg, eine FileList programmatisch zu
        fuellen. Fehlte er, ginge das Formular ohne Dateien raus.
        """
        zweig = _ios_zweig(pdf_js)
        assert "new DataTransfer()" in zweig
        assert "uebertrag.items.add(eintrag.file)" in zweig
        assert "dateiFeld.files = uebertrag.files" in zweig
        assert 'dateiFeld.name = "files"' in zweig
        assert "dateiFeld.multiple = true" in zweig

    def test_ausgabename_wird_mitgesendet(self, pdf_js):
        assert 'nameFeld.name = "output_name"' in _ios_zweig(pdf_js)

    def test_genau_ein_absenden(self, pdf_js):
        """Ein Request, nicht zwei."""
        assert pdf_js.count("formular.submit()") == 1

    def test_kein_blob_download_im_ios_zweig(self, pdf_js):
        zweig = _ios_zweig(pdf_js)
        assert "createObjectURL" not in zweig
        assert "showResult(" not in zweig

    def test_kein_base64_transport(self, pdf_js):
        """
        Grosse PDFs duerfen NICHT als Zeichenkette ueber die Bruecke.
        Base64 blaeht um ein Drittel auf und wuerde die Bruecke ueber
        ihre Zusicherung hinaus belasten.
        """
        for verboten in ("btoa(", "readAsDataURL", "base64", "FileReader"):
            assert verboten not in pdf_js, verboten

    def test_ios_zweig_kehrt_vor_dem_fetch_zurueck(self, pdf_js):
        """
        Struktur statt Textsuche: Der iOS-Zweig muss mit `return` enden,
        BEVOR der fetch-Pfad beginnt. Sonst liefe beides - zwei Requests.
        """
        start = pdf_js.index("if (istIosApp()) {")
        ende = pdf_js.index("const formData = new FormData();")
        assert "return;" in pdf_js[start:ende]

    def test_fehler_werden_verstaendlich_gemeldet(self, pdf_js):
        """
        Serverfehler (Rate Limit, Groesse, Dateityp) kommen als JSON im
        versteckten iframe an und muessen als Meldung erscheinen - nicht
        als rohe JSON-Seite im Fenster.
        """
        zweig = _ios_zweig(pdf_js)
        assert "rahmen.contentDocument" in zweig
        assert "JSON.parse(inhalt).error" in zweig
        assert 'rahmen.style.display = "none"' in zweig
        # Der Aufrufer zeigt die Meldung an.
        assert 'setStatus(fehler ? `Fehler: ${fehler}`' in pdf_js

    def test_nach_fehler_wieder_bedienbar(self, pdf_js):
        """Der Knopf muss in JEDEM Fall wieder freigegeben werden."""
        start = pdf_js.index("if (istIosApp()) {")
        ende = pdf_js.index("const formData = new FormData();")
        zweig = pdf_js[start:ende]
        assert "finally" in zweig
        assert "mergeBtn.disabled = false" in zweig

    def test_aufraeumen_von_formular_und_iframe(self, pdf_js):
        zweig = _ios_zweig(pdf_js)
        assert "rahmen.remove()" in zweig
        assert "formular.remove()" in zweig
        # Nur einmal aufloesen, sonst doppelte Meldungen.
        assert "if (erledigt) return;" in zweig


# ---------------------------------------------------------------------------
# 2. Keine Regression fuer Browser und Android
# ---------------------------------------------------------------------------

class TestKeineRegression:
    def test_browserpfad_nutzt_weiterhin_fetch_und_blob(self, pdf_js):
        zweig = _browser_zweig(pdf_js)
        assert 'await fetch("/tools/pdf/merge"' in zweig
        assert "URL.createObjectURL(blob)" in zweig
        assert "showResult(blobUrl" in zweig

    def test_browserpfad_sendet_weiterhin_den_csrf_header(self, pdf_js):
        assert '"X-CSRFToken": csrfMeta.content' in pdf_js

    def test_nur_ios_nimmt_den_neuen_weg(self, pdf_js):
        """
        Die Weiche haengt an data-platform="ios". Android setzt
        "android" und faellt damit in den unveraenderten Browserpfad.
        """
        assert 'getAttribute("data-platform") === "ios"' in pdf_js
        assert pdf_js.count("if (istIosApp())") == 1

    def test_pdfseite_nutzt_dieselbe_plattformerkennung(self, pdf_html):
        """
        Ohne Erkennung auf DIESER Seite gaebe es dort kein
        data-platform - der iOS-Zweig liefe nie. Als Include, nicht als
        Kopie: zwei Kopien wuerden auseinanderlaufen.
        """
        assert "{% include '_platform_detect.html' %}" in pdf_html
        assert "ERLAUBTE" not in pdf_html      # keine zweite Kopie


# ---------------------------------------------------------------------------
# 3. Vertrag zwischen Webseite und Swift-Huelle
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not IOS_PROJEKT.is_dir(), reason="iOS-Projekt nicht vorhanden")
class TestVertragMitDerHuelle:
    def _swift(self, name):
        return (IOS_PROJEKT / "FootSim" / name).read_text(encoding="utf-8")

    def test_beide_download_delegatepfade_existieren(self):
        wvc = self._swift("WebViewController.swift")
        assert "navigationResponse: WKNavigationResponse,\n                 didBecome download: WKDownload" in wvc
        assert "navigationAction: WKNavigationAction,\n                 didBecome download: WKDownload" in wvc

    def test_huelle_erkennt_content_disposition(self):
        """
        Der entscheidende Punkt: WKWebView KANN PDFs selbst anzeigen,
        canShowMIMEType ist fuer application/pdf also true. Ohne die
        Content-Disposition-Pruefung wuerde das fertige PDF im Fenster
        gerendert statt heruntergeladen.
        """
        wvc = self._swift("WebViewController.swift")
        assert 'value(forHTTPHeaderField: "Content-Disposition")' in wvc
        assert 'disposition.contains("attachment")' in wvc

    def test_sicherer_dateiname(self):
        wvc = self._swift("WebViewController.swift")
        assert "static func sichererDateiname" in wvc
        assert "lastPathComponent" in wvc

    def test_temporaere_datei_wird_aufgeraeumt(self):
        wvc = self._swift("WebViewController.swift")
        assert "completionWithItemsHandler" in wvc
        assert "removeItem(at: ziel.deletingLastPathComponent())" in wvc

    def test_ipad_popover_abgesichert(self):
        wvc = self._swift("WebViewController.swift")
        assert "popoverPresentationController" in wvc
        assert "popover.sourceView = view" in wvc

    def test_kanalnamen_stimmen_ueberein(self, script_js):
        """Web und Swift muessen dieselben Kanaele kennen."""
        web = set(re.findall(
            r'"([a-z]+)"',
            re.search(r"const NATIVE_KANAELE = \[([^\]]*)\]", script_js).group(1)))
        swift = set(re.findall(r"^\s*case (\w+)$",
                               self._swift("Config.swift"), re.M))
        assert web == swift == {"haptic", "share"}


# ---------------------------------------------------------------------------
# 4. Teilen-Knopf: Struktur und Payload
# ---------------------------------------------------------------------------

class TestTeilenKnopf:
    def test_knopf_startet_verborgen(self, index_html):
        """
        Das hidden-Attribut steht im Markup, nicht erst im JavaScript -
        so blitzt der Knopf auch dann nicht auf, wenn das Skript spaet
        kommt.
        """
        treffer = re.search(r'<button id="share-result-btn"[^>]*>', index_html)
        assert treffer, "Teilen-Knopf fehlt"
        assert "hidden" in treffer.group(0)
        assert 'type="button"' in treffer.group(0)

    def test_knopf_steht_im_ergebnisbereich_nicht_im_hero(self, index_html):
        hero_ende = index_html.index("</header>")
        knopf = index_html.index('id="share-result-btn"')
        ergebnis = index_html.index('<div id="result"')
        assert knopf > hero_ende, "Knopf liegt im Hero"
        assert knopf > ergebnis, "Knopf liegt ausserhalb des Ergebnisbereichs"

    @pytest.mark.parametrize("locale,text", [
        ("de", "Ergebnis teilen"), ("en", "Share result"),
    ])
    def test_beschriftung(self, locale, text):
        katalog = json.loads(
            (PROJECT_ROOT / "static" / "i18n" / f"{locale}.json").read_text(encoding="utf-8"))
        assert katalog["simulation.shareResult"] == text

    def test_hinweis_ist_neutral_formuliert(self):
        """
        Keine Erfolgszusage und keine ML-Behauptung im geteilten Text.
        """
        for locale in ("de", "en"):
            katalog = json.loads(
                (PROJECT_ROOT / "static" / "i18n" / f"{locale}.json").read_text(encoding="utf-8"))
            hinweis = katalog["simulation.shareNote"].lower()
            assert "keine vorhersage" in hinweis or "not a prediction" in hinweis
            for verboten in ("garant", "sicher", "guarantee", "machine learning", " ki "):
                assert verboten not in hinweis, verboten

    def test_sichtbarkeit_haengt_an_huelle_kanal_und_ergebnis(self, script_js):
        """Alle drei Bedingungen, nicht nur die Plattform."""
        block = script_js[script_js.index("function aktualisiereTeilenKnopf"):]
        block = block[:block.index("\nfunction renderResult")]
        assert "istNativeHuelle()" in block
        assert 'nativerKanal("share") !== null' in block
        assert "data !== null" in block

    def test_genau_ein_listener(self, script_js):
        """
        Registrierung auf Modulebene, nicht in renderResult - sonst
        oeffneten sich nach drei Simulationen drei Share Sheets.
        """
        assert script_js.count('getElementById("share-result-btn")') == 2
        renderresult = script_js[script_js.index("function renderResult(data)"):]
        renderresult = renderresult[:renderresult.index("\nfunction renderProbabilityBars")]
        assert "addEventListener" not in renderresult

    def test_neue_simulation_verwirft_das_alte_ergebnis(self, script_js):
        """
        Vor jedem Lauf wird der Knopf verborgen. Scheitert die
        Simulation, laeuft renderResult() nicht - ohne das bliebe das
        VORIGE Ergebnis teilbar.
        """
        start = script_js.index("nativeHaptik(\"medium\");")
        assert "aktualisiereTeilenKnopf(null);" in script_js[start:start + 800]

    def test_payload_enthaelt_mannschaften_und_verteilung(self, script_js):
        block = script_js[script_js.index("function baueTeilenNutzlast"):]
        block = block[:block.index("/** Blendet den Teilen-Knopf")]
        for feld in ("data.home_team", "data.away_team",
                     "data.home_win_probability", "data.draw_probability",
                     "data.away_win_probability"):
            assert feld in block, feld
        assert "simulation.shareNote" in block

    def test_payload_enthaelt_keine_sensiblen_felder(self, script_js):
        block = script_js[script_js.index("function baueTeilenNutzlast"):]
        block = block[:block.index("/** Blendet den Teilen-Knopf")]
        for verboten in ("csrf", "token", "email", "e_mail", "user_id",
                         "session", "match_id", "JSON.stringify(data)"):
            assert verboten not in block.lower(), verboten

    def test_keine_zweite_berechnung(self, script_js):
        """Geteilt wird das Angezeigte, nicht ein neuer Aufruf."""
        block = script_js[script_js.index("function baueTeilenNutzlast"):]
        block = block[:block.index("/** Blendet den Teilen-Knopf")]
        assert "fetch(" not in block
        assert "await" not in block


# ---------------------------------------------------------------------------
# 5. CSS des Knopfes
# ---------------------------------------------------------------------------

class TestKnopfDarstellung:
    @pytest.fixture(scope="class")
    def css(self):
        return (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")

    def _regel(self, css, selektor):
        treffer = re.search(r"(?m)^" + re.escape(selektor) + r"\s*\{([^}]*)\}", css)
        assert treffer, f"Regel fehlt: {selektor}"
        return treffer.group(1)

    def test_verborgen_ohne_luecke(self, css):
        """
        inline-flex schlaegt die Browservorgabe fuer [hidden]. Ohne diese
        Regel bliebe der Knopf trotz Attribut sichtbar - und im
        verborgenen Zustand entstuende sonst eine Luecke durch margin.
        """
        assert "display: none" in self._regel(css, ".share-result-btn[hidden]")

    def test_touchflaeche_gross_genug(self, css):
        regel = self._regel(css, ".share-result-btn")
        hoehe = re.search(r"min-height:\s*(\d+)px", regel)
        assert hoehe and int(hoehe.group(1)) >= 44

    def test_hover_active_focus(self, css):
        assert ".share-result-btn:hover" in css
        assert ".share-result-btn:active" in css
        assert "outline" in self._regel(css, ".share-result-btn:focus-visible")

    def test_nutzt_nur_vorhandene_themetokens(self, css):
        """
        Ein erfundenes Token faellt auf transparent zurueck - im dunklen
        Theme unsichtbarer Text auf unsichtbarem Grund.
        """
        regel = self._regel(css, ".share-result-btn")
        for token in re.findall(r"var\((--[a-z-]+)\)", regel):
            assert f"{token}:" in css, f"{token} ist nirgends definiert"

    def test_keine_plattformabhaengige_einblendung(self, css):
        """
        Sichtbarkeit gehoert ans Ergebnis, nicht an die Plattform allein.
        Eine Regel wie [data-platform="ios"] .share-result-btn { display:
        flex } wuerde den Knopf auch ohne Simulation zeigen.
        """
        assert 'data-platform="ios"] .share-result-btn' not in css
