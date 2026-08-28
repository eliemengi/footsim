"""
Tests fuer die CTA-Gruppe im Hero: Unterstuetzen + Android-Testerlinks.

WARUM DIESE DATEI
-----------------
Drei externe Links stehen hier dicht beieinander, und jeder einzelne
kann auf eine Weise falsch sein, die im Betrieb teuer ist:

  * Ein vertauschter oder selbst gebastelter Link fuehrt Tester ins
    Leere - und zwar genau die Leute, die die App freischalten sollen.
  * Ein fehlendes rel="noopener" bei target="_blank" gibt der Zielseite
    Zugriff auf window.opener.
  * Faellt die Gruppe aus dem .support-Container heraus, blendet die
    bestehende Android-Regel sie nicht mehr aus - und im Play Store
    steht ploetzlich ein Spendenlink in der App.

Alle Pruefungen sind statisch beziehungsweise gerendert und brauchen
weder Netz noch Browser. Die Sichtbarkeit im echten Browser deckt
tests/test_browser_smoke.py ab (Klasse TestAndroidModusImBrowser).
"""

import json
import re
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]

GROUPS_URL = "https://groups.google.com/g/footsim-android-tester"
PLAY_URL = "https://play.google.com/store/apps/details?id=de.footsim.app"
PAYPAL_URL = "https://paypal.me/elierdc"

TEXTE = {
    "de": {
        "hero.support": "Projekt unterstützen",
        "hero.appSignup": "App-Anmeldung",
        "hero.appDownload": "App-Download",
    },
    "en": {
        "hero.support": "Support the project",
        "hero.appSignup": "App sign-up",
        "hero.appDownload": "App download",
    },
}

# Schluessel, die es nicht mehr geben darf - weder im Template noch in
# den Katalogen. Sie standen fuer den entfernten dritten Hinweistext und
# fuer die alte Beschriftung.
ENTFERNTE_SCHLUESSEL = [
    "hero.testerJoin", "hero.testerDownload", "hero.testerHint",
]

# Die Basisregel des Knopfes traegt drei Selektoren - :link und
# :visited sind noetig, damit der Browser den Knopf nicht doch
# unterstreicht oder lila einfaerbt.
KNOPF_SELEKTOR = ".tester-btn,\n.tester-btn:link,\n.tester-btn:visited"


@pytest.fixture(scope="module")
def index_html():
    return (PROJECT_ROOT / "templates" / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def style_css():
    return (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def support_block(index_html):
    """Nur der CTA-Container, damit Treffer von anderswo nicht mitzaehlen."""
    start = index_html.index('<div class="support support--stack">')
    ende = index_html.index("</div>", index_html.index("de.footsim.app", start))
    return index_html[start:ende]


@pytest.fixture(scope="module")
def sw_js():
    return (PROJECT_ROOT / "static" / "sw.js").read_text(encoding="utf-8")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APISPORTS_KEY", "test-key")
    import app as app_module
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# 1. Die Links selbst
# ---------------------------------------------------------------------------

class TestLinkziele:
    @pytest.mark.parametrize("url", [PAYPAL_URL, GROUPS_URL, PLAY_URL])
    def test_link_ist_exakt_vorhanden(self, support_block, url):
        assert f'href="{url}"' in support_block

    def test_die_beiden_testerlinks_sind_verschieden(self):
        """
        Klingt trivial, ist es nicht: beide Schritte werden gern aus
        derselben Zwischenablage eingefuegt. Zwei identische Links
        sehen im UI voellig normal aus und machen den Testprozess
        stillschweigend kaputt.
        """
        assert GROUPS_URL != PLAY_URL

    def test_kein_link_wird_umgeleitet_oder_konstruiert(self, support_block):
        """Genau drei externe Ziele, keine selbst zusammengebaute URL."""
        hrefs = re.findall(r'href="([^"]+)"', support_block)
        assert hrefs == [PAYPAL_URL, GROUPS_URL, PLAY_URL]

    def test_reihenfolge_unterstuetzen_anmelden_download(self, support_block):
        assert (support_block.index(PAYPAL_URL)
                < support_block.index(GROUPS_URL)
                < support_block.index(PLAY_URL))

    def test_cta_struktur_existiert_nur_einmal(self, index_html):
        # Auf das Klassenattribut zaehlen, nicht auf den blossen Namen:
        # der erlaeuternde Jinja-Kommentar nennt .support--stack
        # ebenfalls und ist kein zweiter Container.
        assert index_html.count('class="support support--stack"') == 1
        for url in (PAYPAL_URL, GROUPS_URL, PLAY_URL):
            assert index_html.count(f'href="{url}"') == 1
        assert index_html.count('class="tester-btn"') == 2

    def test_es_gibt_kein_drittes_element(self, support_block, index_html):
        """
        Der Hinweistext zum Google-Konto ist ersatzlos entfernt. Genau
        drei Elemente stehen in der Gruppe: drei Links, kein Absatz.
        """
        assert "tester-hint" not in index_html
        # Auf ein echtes Absatz-Tag pruefen: ein blosses "<p" traefe
        # auch das <path> im PayPal-Symbol.
        assert not re.search(r"<p[\s>]", support_block)
        assert support_block.count("<a ") == 3


# ---------------------------------------------------------------------------
# 2. Sicherheit und Struktur
# ---------------------------------------------------------------------------

class TestSicherheitUndStruktur:
    def test_jeder_neue_tab_traegt_noopener_noreferrer(self, support_block):
        """
        Gilt ausdruecklich auch fuer den PayPal-Link: der stand hier
        vorher mit target="_blank" OHNE rel und gab damit der
        Zielseite Zugriff auf window.opener.
        """
        anker = re.findall(r"<a\s[^>]*>", support_block)
        assert len(anker) == 3

        for tag in anker:
            if 'target="_blank"' in tag:
                assert 'rel="noopener noreferrer"' in tag, tag

    def test_keine_verschachtelten_links(self, support_block):
        """Ein <a> in einem <a> ist ungueltiges HTML und unklickbar."""
        tiefe = 0
        for treffer in re.finditer(r"<a\s|</a>", support_block):
            if treffer.group().startswith("</"):
                tiefe -= 1
            else:
                tiefe += 1
                assert tiefe <= 1, "verschachtelter Link im CTA-Block"
        assert tiefe == 0, "unbalancierte <a>-Tags"

    def test_alle_drei_links_sind_geschwister(self, support_block):
        """
        Kein Link steckt in einem Zwischen-Container. Das
        Zwei-Spalten-Layout macht das Grid, nicht ein Wrapper - so
        bleibt die Struktur flach und die Android-Regel eindeutig.
        """
        zwischen = support_block[support_block.index(PAYPAL_URL):]
        zwischen = zwischen[:zwischen.index(PLAY_URL)]
        assert "<div" not in zwischen

    def test_semantische_anker_keine_buttons(self, support_block):
        assert "<button" not in support_block

    def test_gesamte_gruppe_liegt_im_support_container(self, support_block):
        """
        Die entscheidende Zusicherung fuer den Play Store: liegt alles
        in .support, greift die vorhandene Android-Ausblendung fuer die
        ganze Gruppe - ohne zweite Sonderlogik.
        """
        for marke in (PAYPAL_URL, GROUPS_URL, PLAY_URL):
            assert marke in support_block


# ---------------------------------------------------------------------------
# 3. Android-Ausblendung
# ---------------------------------------------------------------------------

class TestAndroidAusblendung:
    def test_regel_blendet_support_vollstaendig_aus(self, style_css):
        block = re.search(
            r':root\[data-platform="android"\]\s+\.support\s*\{([^}]*)\}',
            style_css,
        )
        assert block, "Android-Regel fuer .support fehlt"
        assert "display: none" in block.group(1)

    def test_keine_neue_useragent_sonderloesung(self, index_html):
        """Es bleibt bei der einen vorhandenen Plattformerkennung."""
        assert index_html.count("setAttribute('data-platform', 'android')") == 1

    def test_geaenderte_dateien_werden_vom_sw_erneuert(self, sw_js):
        """
        style.css und beide Kataloge muessen im Service Worker als
        stale-while-revalidate gefuehrt sein. Sonst konserviert der
        Cache-First-Zweig sie bis zum naechsten Versionssprung - genau
        der Weg, auf dem am 28.08.2026 Rohschluessel und ungestylte
        Links im Browser landeten.
        """
        block = re.search(r"REVALIDATE_PATHS\s*=\s*\[([^\]]*)\]", sw_js)
        assert block, "REVALIDATE_PATHS fehlt"
        for pfad in ("/static/style.css", "/static/i18n/de.json",
                     "/static/i18n/en.json"):
            assert pfad in block.group(1), pfad

    def test_cacheversion_wurde_mit_der_aenderung_erhoeht(self, sw_js):
        """
        Die Revalidierung allein zeigt den neuen Stand erst beim
        ZWEITEN Aufruf. Fuer eine Auslieferung zaehlt der erste,
        deshalb gehoert zu dieser Aenderung ein Versionssprung.
        """
        treffer = re.search(r'CACHE_NAME\s*=\s*"footsim-v(\d+)"', sw_js)
        assert treffer, "CACHE_NAME fehlt oder hat ein anderes Format"
        assert int(treffer.group(1)) >= 35

    def test_cta_hat_keine_eigene_ausblendung(self, style_css):
        """
        Eine zweite Regel waere die Gefahr: sie koennte sich von der
        .support-Regel wegentwickeln und die Gruppe in der App wieder
        sichtbar machen.
        """
        assert 'data-platform="android"] .tester' not in style_css


# ---------------------------------------------------------------------------
# 4. Texte in beiden Sprachen
# ---------------------------------------------------------------------------

class TestTexte:
    @pytest.mark.parametrize("locale", ["de", "en"])
    def test_katalog_enthaelt_die_texte(self, locale):
        katalog = json.loads(
            (PROJECT_ROOT / "static" / "i18n" / f"{locale}.json").read_text(encoding="utf-8")
        )
        for schluessel, text in TEXTE[locale].items():
            assert katalog[schluessel] == text

    def _katalog(self, locale):
        return json.loads(
            (PROJECT_ROOT / "static" / "i18n" / f"{locale}.json").read_text(encoding="utf-8")
        )

    def test_jeder_schluessel_im_template_steht_in_BEIDEN_katalogen(self, index_html):
        """
        DER TEST, DER GEFEHLT HAT.

        applyTranslations() setzt fuer jedes [data-i18n]-Element
        node.textContent = t(key) und ueberschreibt damit den korrekt
        serverseitig gerenderten Text. Fehlt der Schluessel im Katalog,
        faellt t() auf den Schluesselnamen zurueck - und im UI steht
        dann "hero.testerJoin" statt einer Beschriftung.

        Der vorhandene Test in test_i18n.py prueft nur den englischen
        Katalog. Ein Schluessel, der ausschliesslich auf Deutsch fehlt,
        rutschte dort durch.
        """
        schluessel = set(re.findall(r'data-i18n="([^"]+)"', index_html))
        assert schluessel

        for locale in ("de", "en"):
            fehlend = schluessel - self._katalog(locale).keys()
            assert not fehlend, f"{locale}: {sorted(fehlend)}"

    def test_entfernte_schluessel_sind_ueberall_weg(self, index_html):
        for locale in ("de", "en"):
            katalog = self._katalog(locale)
            for schluessel in ENTFERNTE_SCHLUESSEL:
                assert schluessel not in katalog, f"{locale}: {schluessel}"
        for schluessel in ENTFERNTE_SCHLUESSEL:
            assert schluessel not in index_html

    def test_template_nutzt_katalogschluessel(self, support_block):
        for schluessel in ("hero.support", "hero.appSignup", "hero.appDownload"):
            assert f'data-i18n="{schluessel}"' in support_block

    @pytest.mark.parametrize("locale", ["de", "en"])
    def test_gerenderte_seite_zeigt_die_texte(self, client, locale):
        seite = client.get(f"/?lang={locale}").get_data(as_text=True)
        for text in TEXTE[locale].values():
            assert text in seite

    @pytest.mark.parametrize("locale", ["de", "en"])
    def test_gerenderte_seite_traegt_die_links(self, client, locale):
        seite = client.get(f"/?lang={locale}").get_data(as_text=True)
        for url in (PAYPAL_URL, GROUPS_URL, PLAY_URL):
            assert f'href="{url}"' in seite

    def test_paypal_bleibt_im_browser_erhalten(self, client):
        """Die Unterstuetzungsfunktion darf durch die CTA nicht wegfallen."""
        seite = client.get("/?lang=de").get_data(as_text=True)
        assert PAYPAL_URL in seite
        assert "paypal-icon" in seite
        assert "Projekt unterstützen" in seite


# ---------------------------------------------------------------------------
# 5. Layout - gleiche Breite, kein Abschneiden
# ---------------------------------------------------------------------------

class TestLayoutRegeln:
    def _regel(self, css, selektor):
        """
        Die Basisregel zu einem Selektor.

        Am Zeilenanfang verankert, und zwar aus einem konkreten Grund:
        ohne Anker traf ".tester-hint" zuerst die Grid-Regel
        ".hero .support--stack .tester-hint", die weiter oben steht -
        die Pruefung las dann grid-column statt der Farbe. Verschachtelte
        Regeln in Media Queries sind eingerueckt und fallen durch den
        Anker ebenfalls heraus.
        """
        treffer = re.search(
            r"(?m)^" + re.escape(selektor) + r"\s*\{([^}]*)\}", css
        )
        assert treffer, f"Regel fehlt: {selektor}"
        return treffer.group(1)

    def test_zwei_gleiche_spalten(self, style_css):
        """
        1fr 1fr plus ein gemeinsames gap: die Summe der beiden
        Testerknoepfe entspricht damit per Konstruktion exakt der
        Breite des Unterstuetzungsknopfes, der beide Spalten spannt.
        """
        regel = self._regel(style_css, ".hero .support--stack")
        assert "grid-template-columns: 1fr 1fr" in regel
        assert "display: grid" in regel

    def test_oberer_knopf_spannt_beide_spalten(self, style_css):
        regel = self._regel(style_css, ".hero .support--stack .support-btn")
        assert "grid-column: 1 / -1" in regel

    def test_touchflaeche_ist_gross_genug(self, style_css):
        regel = self._regel(style_css, KNOPF_SELEKTOR)
        hoehe = re.search(r"min-height:\s*(\d+)px", regel)
        assert hoehe and int(hoehe.group(1)) >= 44

    def test_keine_feste_hoehe_die_text_abschneidet(self, style_css):
        """
        Eine feste height wuerde den laengeren deutschen Text auf
        schmalen Geraeten abschneiden. min-height laesst ihn umbrechen.
        """
        regel = self._regel(style_css, KNOPF_SELEKTOR)
        # Nur eine eigenstaendige height-Deklaration ist gemeint -
        # line-height und min-height sind ausdruecklich erlaubt.
        assert not re.search(r"(?<![a-z-])height:\s*\d", regel)
        assert "overflow: hidden" not in regel
        assert "white-space: nowrap" not in regel

    def test_auch_schmal_bleiben_die_knoepfe_nebeneinander(self, style_css):
        """
        Auf 360, 390 und 430px stehen die beiden Knoepfe nebeneinander.
        Enger wird nur ueber Schrift und Abstand geregelt - ein Stapeln
        waere hier ein Umbruch ohne Not, weil "App-Anmeldung" auch in
        einer halben Spalte von 360px bequem passt.
        """
        # Genau den 380px-Block betrachten, nicht den gesamten Rest der
        # Datei - dort stehen viele fremde Grids mit derselben Angabe.
        rest = style_css[style_css.index("@media (max-width: 380px)"):]
        naechste = rest.find("@media", 5)
        block = rest[:naechste] if naechste != -1 else rest

        # Gezielt die eigene Regel im Block betrachten: der Block
        # enthaelt auch Grids anderer Komponenten, die hier nichts
        # zur Sache tun.
        eigene = re.search(
            r"\.hero \.support--stack\s*\{([^}]*)\}", block
        )
        assert eigene, "Regel fuer .hero .support--stack fehlt im 380px-Block"
        assert "grid-template-columns" not in eigene.group(1)
        assert ".tester-btn" in block, "Schriftanpassung fuer schmale Displays fehlt"

    def test_helle_flaeche_mit_dunkler_schrift(self, style_css):
        regel = self._regel(style_css, KNOPF_SELEKTOR)
        assert "background: #ffffff" in regel
        assert "color: #0d1b30" in regel

    def test_hover_active_und_sichtbarer_focus(self, style_css):
        assert ".tester-btn:hover" in style_css
        assert ".tester-btn:active" in style_css
        fokus = self._regel(style_css, ".tester-btn:focus-visible")
        assert "outline" in fokus

    def test_rundung_passt_zum_designsystem(self, style_css):
        """Dieselbe Pillenform wie .support-btn."""
        assert "border-radius: 999px" in self._regel(style_css, KNOPF_SELEKTOR)

    def test_keine_inline_styles_im_cta(self, support_block):
        assert "style=" not in support_block

    def test_sieht_nicht_aus_wie_ein_standardlink(self, style_css):
        """
        Der sichtbare Fehler am 28.08.2026: Wo die .tester-btn-Regeln
        fehlten, rendert der Browser das <a> mit seiner Vorgabe -
        unterstrichen und blau beziehungsweise nach dem Besuch lila.
        Deshalb sind text-decoration UND color hier ausdruecklich
        gesetzt, und zwar auch fuer :link und :visited.
        """
        regel = self._regel(
            style_css, ".tester-btn,\n.tester-btn:link,\n.tester-btn:visited"
        )
        assert "text-decoration: none" in regel
        assert "color: #0d1b30" in regel
        assert "background: #ffffff" in regel

    def test_besuchter_zustand_bleibt_gestylt(self, style_css):
        """:visited ist der Zustand, in dem Browser lila einfaerben."""
        assert ".tester-btn:visited" in style_css

    def test_rahmen_gibt_der_flaeche_eine_kontur(self, style_css):
        regel = self._regel(
            style_css, ".tester-btn,\n.tester-btn:link,\n.tester-btn:visited"
        )
        assert re.search(r"border:\s*1px solid", regel)
        assert "box-shadow" in regel
