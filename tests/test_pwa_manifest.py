"""
Die Web-Voraussetzungen der Android-App (Trusted Web Activity).

WORUM ES GEHT
-------------
Bubblewrap liest das Manifest EINMAL zur Bauzeit und backt Name, Farben,
scope und start_url in die AAB. Ein Fehler im Manifest ist deshalb kein
Schoenheitsfehler, sondern wandert unveraendert in jede installierte App.

Drei Befunde standen am Anfang dieser Datei:

  1. scope fehlte vollstaendig. Ohne Angabe raet Bubblewrap aus
     start_url, und alles ausserhalb des geratenen Bereichs oeffnet als
     Custom Tab mit Adressleiste statt in der App.

  2. Es gab genau EINE Bilddatei - logofoot.png, 1024x1024, ein
     Megabyte -, im Manifest gleichzeitig als 192x192 UND als 512x512
     deklariert. Beide Angaben falsch. Zusaetzlich trug sie
     purpose "any maskable": ein Versprechen, dass das Motiv im inneren
     Sicherheitskreis liegt. Bei einem randlosen Logo stimmt das nicht.

  3. start_url war "/?lang={locale}". Die Sprache des Build-Rechners
     waere damit fuer alle Nutzer festgeschrieben worden.

Diese Tests halten die Korrekturen fest. Sie brauchen weder Datenbank
noch Netzwerk.
"""

import json
import os

import pytest

PROJEKT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BILDER = os.path.join(PROJEKT, "static", "images")

#: Fest verdrahtet - nach der ersten Veroeffentlichung unveraenderlich.
PAKET_ID = "de.footsim.app"

#: Ein gueltiger Fingerabdruck: 32 Hexpaare. Bewusst ein offensichtliches
#: Testmuster und kein echter Wert.
GUELTIGER_ABDRUCK = ":".join(["AB"] * 32)

#: Die aktuell gueltigen Icons. Das Suffix -v2 trennt sie von den ersten,
#: die noch aus der opaken Quelle stammten und einen doppelten
#: Hintergrund erzeugten.
ICON_192 = "icon-192-v2.png"
ICON_512 = "icon-512-v2.png"
ICON_MASKABLE = "icon-maskable-512-v2.png"
ALLE_ICONS = (ICON_192, ICON_512, ICON_MASKABLE)

#: background_color und theme_color des Manifests, als RGBA.
HINTERGRUND = (0x0D, 0x1B, 0x30, 255)

#: Ab welcher Deckkraft ein Pixel zum sichtbaren Motiv zaehlt.
#: Dieselbe Schwelle wie in build_pwa_icons.SICHTBAR_AB - die Quelle
#: traegt einen weichen Schein mit Alpha 1 bis 7, der mit blossem Auge
#: nicht zu sehen ist, fuer getbbox() aber zaehlt.
SICHTBAR_AB = 8


def _sichtbarer_kasten(rgba):
    """
    Bounding-Box des sichtbaren Motivs eines transparenten Icons.

    Bewusst nicht Image.getbbox(): Das zaehlt schon Alpha 1 mit und
    lieferte damit einen groesseren Kasten als das, was jemand sieht.
    """
    maske = rgba.getchannel("A").point(
        lambda wert: 255 if wert >= SICHTBAR_AB else 0)
    return maske.getbbox()


def _motiv_auf_hintergrund(rgba, hintergrund=HINTERGRUND[:3]):
    """
    Bounding-Box des Motivs auf einer vollflaechig gefuellten Flaeche.

    Beim maskable Icon ist jeder Pixel undurchsichtig, der Alphakanal
    sagt also nichts. Gesucht wird deshalb, was von der Hintergrundfarbe
    abweicht. Ein kleiner Abstand vom exakten Farbwert faengt die
    Kantenglaettung des skalierten Motivs ab.
    """
    breite, hoehe = rgba.size
    links, oben, rechts, unten = breite, hoehe, -1, -1

    for y in range(hoehe):
        for x in range(breite):
            pixel = rgba.getpixel((x, y))[:3]
            abstand = sum(abs(a - b) for a, b in zip(pixel, hintergrund))
            if abstand > 12:
                if x < links:
                    links = x
                if x > rechts:
                    rechts = x
                if y < oben:
                    oben = y
                if y > unten:
                    unten = y

    assert rechts >= 0, "kein Motiv gefunden - das Icon ist einfarbig"
    return (links, oben, rechts + 1, unten + 1)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APISPORTS_KEY", "test-key")
    monkeypatch.setenv("FOOTBALL_DATA_KEY", "test-key")
    import app as app_module

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def manifest_von(client, pfad="/manifest.json"):
    antwort = client.get(pfad)
    assert antwort.status_code == 200
    return antwort, antwort.get_json()


# ---------------------------------------------------------------------------
# Das ausgelieferte Manifest
# ---------------------------------------------------------------------------

class TestManifestGrunddaten:

    def test_mime_bleibt_manifest_json(self, client):
        antwort, _ = manifest_von(client)
        assert antwort.headers["Content-Type"].startswith(
            "application/manifest+json")

    def test_name_und_kurzname(self, client):
        _, m = manifest_von(client)
        assert m["name"] == "FootSim"
        assert m["short_name"] == "FootSim"

    def test_start_url_ist_die_wurzel_ohne_sprache(self, client):
        """
        Der Kern der Reparatur: keine Sprache in der Start-URL.

        Bubblewrap backt diesen Wert in die AAB. Mit "/?lang=de" haetten
        Englischsprachige dauerhaft Deutsch gesehen.
        """
        _, m = manifest_von(client)
        assert m["start_url"] == "/"
        assert "lang=" not in m["start_url"]

    def test_scope_ist_gesetzt(self, client):
        _, m = manifest_von(client)
        assert m["scope"] == "/", "ohne scope raet Bubblewrap"

    def test_display_und_override(self, client):
        _, m = manifest_von(client)
        assert m["display"] == "standalone"
        assert m["display_override"][0] == "standalone"
        assert "minimal-ui" in m["display_override"]

    def test_farben_unveraendert(self, client):
        _, m = manifest_von(client)
        assert m["theme_color"] == "#0d1b30"
        assert m["background_color"] == "#0d1b30"

    def test_verknuepfungen_zeigen_auf_einen_gelesenen_parameter(self, client):
        """
        Vorher stand dort ?mode=, das im Frontend nirgends ausgewertet
        wurde - beide Verknuepfungen oeffneten wirkungslos die
        Startansicht.
        """
        _, m = manifest_von(client)
        ziele = [k["url"] for k in m["shortcuts"]]
        assert ziele == ["/?area=simulation", "/?area=compare"]

        quelle = open(os.path.join(PROJEKT, "static", "script.js"),
                      encoding="utf-8").read()
        assert 'AREA_QUERY_KEY = "area"' in quelle


class TestSpracheBleibtAutomatisch:
    """
    start_url traegt keine Sprache mehr - also muss der Server sie
    weiterhin selbst erkennen. Sonst waere die Reparatur ein Rueckschritt.
    """

    def test_deutsches_system_bekommt_deutsch(self, client):
        antwort = client.get("/manifest.json",
                             headers={"Accept-Language": "de-DE,de;q=0.9"})
        assert antwort.get_json()["lang"] == "de"

    def test_anderes_system_bekommt_englisch(self, client):
        for sprache in ("fr-FR,fr;q=0.9", "es-ES", "ja-JP", "en-US"):
            antwort = client.get("/manifest.json",
                                 headers={"Accept-Language": sprache})
            assert antwort.get_json()["lang"] == "en", sprache

    def test_ausdrueckliche_wahl_schlaegt_das_system(self, client):
        antwort = client.get("/manifest.json?lang=de",
                             headers={"Accept-Language": "en-US"})
        assert antwort.get_json()["lang"] == "de"


# ---------------------------------------------------------------------------
# Icons
# ---------------------------------------------------------------------------

class TestIcons:
    """
    Die Icons entstehen aus logofoot-app-v2.png, NICHT aus logofoot.png.

    Die alte Quelle ist vollflaechig opak (Alpha durchgehend 255, Ecken
    fast schwarz). Sie brachte ihre eigene dunkle Kachel mit. Das
    maskable Icon legte eine zweite Flaeche dahinter - auf dem Launcher
    lagen zwei Quadrate uebereinander, und beim Start blitzte die
    eingebackene Kachel als schwarzes Rechteck auf.

    logofoot.png bleibt unangetastet: Sie gehoert weiterhin zur Website
    (Favicon, Kopfbereich) und wird fuer die App-Icons nicht mehr benutzt.
    """

    def test_manifest_nutzt_ausschliesslich_v2_dateien(self, client):
        _, m = manifest_von(client)
        quellen = [i["src"] for i in m["icons"]]
        quellen += [k["icons"][0]["src"] for k in m["shortcuts"]]

        for quelle in quellen:
            assert quelle.endswith("-v2.png"), (
                f"{quelle} zeigt noch auf die alte Fassung")
            assert "logofoot" not in quelle, (
                "eine Quelldatei gehoert nicht ins Manifest")

    def test_drei_getrennte_dateien(self, client):
        _, m = manifest_von(client)
        quellen = [i["src"] for i in m["icons"]]
        assert len(set(quellen)) == 3, "dieselbe Datei mehrfach deklariert"

    @pytest.mark.parametrize("name,kante", [
        (ICON_192, 192),
        (ICON_512, 512),
        (ICON_MASKABLE, 512),
    ])
    def test_datei_hat_wirklich_diese_kantenlaenge(self, name, kante):
        """
        Die urspruengliche Regression: Das Manifest deklarierte Groessen,
        die es nicht gab.
        """
        from PIL import Image

        pfad = os.path.join(BILDER, name)
        assert os.path.exists(pfad), f"{name} fehlt - build_pwa_icons.py laufen lassen"
        with Image.open(pfad) as bild:
            assert bild.size == (kante, kante), (
                f"{name} ist {bild.size[0]}x{bild.size[1]}, deklariert {kante}x{kante}")

    def test_deklarierte_groesse_stimmt_mit_der_datei(self, client):
        from PIL import Image

        _, m = manifest_von(client)
        for eintrag in m["icons"]:
            name = eintrag["src"].rsplit("/", 1)[-1]
            with Image.open(os.path.join(BILDER, name)) as bild:
                assert eintrag["sizes"] == f"{bild.size[0]}x{bild.size[1]}", name

    def test_any_und_maskable_sind_getrennt(self, client):
        """
        Ein Icon kann nicht beides sein: maskable verspricht einen
        Sicherheitsrand und einen Hintergrund, any soll gerade keinen
        haben.
        """
        _, m = manifest_von(client)
        zwecke = [i["purpose"] for i in m["icons"]]
        assert zwecke.count("any") == 2
        assert zwecke.count("maskable") == 1

    def test_icons_werden_ausgeliefert(self, client):
        for name in ALLE_ICONS:
            antwort = client.get(f"/static/images/{name}")
            assert antwort.status_code == 200, name
            assert antwort.headers["Content-Type"] == "image/png"


class TestNormaleIconsSindTransparent:
    """
    Der Kern der Korrektur: Die normalen Icons bringen KEINEN eigenen
    Hintergrund mehr mit. Wer eine Flaeche will - Chrome, der Launcher,
    das Manifest -, setzt sie selbst. Genau eine Instanz entscheidet
    darueber, nicht zwei.
    """

    @pytest.mark.parametrize("name,kante", [(ICON_192, 192), (ICON_512, 512)])
    def test_die_ecken_sind_vollstaendig_transparent(self, name, kante):
        from PIL import Image

        with Image.open(os.path.join(BILDER, name)) as bild:
            rgba = bild.convert("RGBA")
            for punkt in ((0, 0), (kante - 1, 0),
                          (0, kante - 1), (kante - 1, kante - 1)):
                assert rgba.getpixel(punkt)[3] == 0, (
                    f"{name} hat bei {punkt} eine undurchsichtige Ecke - "
                    f"das ist die eingebackene Kachel")

    @pytest.mark.parametrize("name", [ICON_192, ICON_512])
    def test_die_datei_hat_echte_transparenz(self, name):
        from PIL import Image

        with Image.open(os.path.join(BILDER, name)) as bild:
            alpha_min, alpha_max = bild.convert("RGBA").getchannel("A").getextrema()
            assert alpha_min == 0, f"{name} ist flachgerechnet"
            assert alpha_max == 255, f"{name} hat kein deckendes Motiv"

    @pytest.mark.parametrize("name,kante", [(ICON_192, 192), (ICON_512, 512)])
    def test_das_motiv_fuellt_die_flaeche_ohne_verzerrung(self, name, kante):
        """
        Proportional zentriert heisst: In einer Richtung beruehrt das
        Motiv den Rand, in der anderen bleibt symmetrisch Luft. Ein
        verzerrtes Motiv fuellte beide Richtungen, ein zu kleines keine.
        """
        from PIL import Image

        with Image.open(os.path.join(BILDER, name)) as bild:
            kasten = _sichtbarer_kasten(bild.convert("RGBA"))

        breite = kasten[2] - kasten[0]
        hoehe = kasten[3] - kasten[1]
        assert max(breite, hoehe) == kante, (
            f"{name}: Motiv {breite}x{hoehe} beruehrt keinen Rand")

        # Zentriert: die Raender der schmaleren Richtung sind gleich gross.
        assert abs(kasten[0] - (kante - kasten[2])) <= 1, "horizontal versetzt"
        assert abs(kasten[1] - (kante - kasten[3])) <= 1, "vertikal versetzt"


class TestMaskableIcon:

    def _bild(self):
        from PIL import Image

        return Image.open(os.path.join(BILDER, ICON_MASKABLE)).convert("RGBA")

    def test_die_ecken_tragen_genau_die_hintergrundfarbe(self):
        """
        Android schneidet hier zu. Ein transparenter Rand erschiene als
        Loch, eine andere Farbe als Rahmen.
        """
        bild = self._bild()
        for punkt in ((0, 0), (511, 0), (0, 511), (511, 511), (3, 3), (508, 508)):
            assert bild.getpixel(punkt) == HINTERGRUND, punkt

    def test_die_flaeche_ist_vollstaendig_undurchsichtig(self):
        alpha_min, _ = self._bild().getchannel("A").getextrema()
        assert alpha_min == 255, "das maskable Icon hat durchsichtige Stellen"

    def test_das_motiv_liegt_in_der_safe_zone(self):
        """
        Garantiert sichtbar bleibt ein Kreis mit 80 Prozent des
        Durchmessers. Das Motiv ist nicht quadratisch - entscheidend ist
        deshalb seine Diagonale: Passt sie in den Kreis, liegen auch die
        vier Ecken der Bounding-Box darin.
        """
        import math

        kasten = _motiv_auf_hintergrund(self._bild())
        breite = kasten[2] - kasten[0]
        hoehe = kasten[3] - kasten[1]
        diagonale = math.hypot(breite, hoehe)
        sicher = 512 * 0.8

        assert diagonale <= sicher, (
            f"Motiv {breite}x{hoehe}, Diagonale {diagonale:.0f} > {sicher:.0f} - "
            f"bei rundem Zuschnitt wuerden Teile abgeschnitten")

    def test_das_motiv_ist_zentriert(self):
        kasten = _motiv_auf_hintergrund(self._bild())
        mitte_x = (kasten[0] + kasten[2]) / 2
        mitte_y = (kasten[1] + kasten[3]) / 2
        assert abs(mitte_x - 256) <= 2, f"horizontal bei {mitte_x}"
        assert abs(mitte_y - 256) <= 2, f"vertikal bei {mitte_y}"

    def test_das_motiv_ist_nicht_verschwindend_klein(self):
        """
        Die Gegenprobe zur Safe-Zone-Regel: Ein winziges Motiv erfuellte
        sie muehelos und saehe trotzdem falsch aus.
        """
        kasten = _motiv_auf_hintergrund(self._bild())
        breite = kasten[2] - kasten[0]
        assert breite >= 250, f"Motiv nur {breite} px breit"


class TestQuelleBleibtGetrennt:

    def test_die_neue_quelle_hat_echte_transparenz(self):
        """
        Wird sie je flachgerechnet neu exportiert, kehrt der doppelte
        Hintergrund zurueck - deshalb steht die Zusicherung hier und
        nicht nur im Build-Skript.
        """
        from PIL import Image

        pfad = os.path.join(BILDER, "logofoot-app-v2.png")
        assert os.path.exists(pfad), "die App-Logoquelle fehlt"
        with Image.open(pfad) as bild:
            alpha_min, alpha_max = bild.convert("RGBA").getchannel("A").getextrema()
            assert (alpha_min, alpha_max) == (0, 255)

    def test_das_website_logo_bleibt_unveraendert_opak(self):
        """
        logofoot.png gehoert weiterhin zur Website. Diese Zusicherung
        haelt fest, dass die Trennung Absicht ist: Waere sie ploetzlich
        transparent, waere die Website-Darstellung angefasst worden.
        """
        from PIL import Image

        with Image.open(os.path.join(BILDER, "logofoot.png")) as bild:
            alpha_min, _ = bild.convert("RGBA").getchannel("A").getextrema()
            assert alpha_min == 255, "das Website-Logo wurde veraendert"

    def test_die_alten_icons_wurden_nicht_geloescht(self):
        """Sie werden nicht mehr referenziert, bleiben aber liegen."""
        for name in ("icon-192.png", "icon-512.png", "icon-maskable-512.png"):
            assert os.path.exists(os.path.join(BILDER, name)), name


# ---------------------------------------------------------------------------
# Keine zweite Wahrheit
# ---------------------------------------------------------------------------

class TestStatischesManifestWidersprichtNicht:
    """
    static/manifest.json wird nirgends ausgeliefert - massgeblich ist die
    Route in app.py. Die Datei bleibt als sprachneutrale Referenz
    bestehen, darf aber niemals etwas anderes behaupten.
    """

    def _statisch(self):
        with open(os.path.join(PROJEKT, "static", "manifest.json"),
                  encoding="utf-8") as f:
            return json.load(f)

    @pytest.mark.parametrize("feld", [
        "name", "short_name", "start_url", "scope", "display",
        "display_override", "background_color", "theme_color",
        "orientation", "categories", "icons",
    ])
    def test_strukturfeld_stimmt_mit_der_route_ueberein(self, client, feld):
        _, route = manifest_von(client)
        assert self._statisch()[feld] == route[feld], feld

    def test_verknuepfungsziele_stimmen_ueberein(self, client):
        _, route = manifest_von(client)
        assert [k["url"] for k in self._statisch()["shortcuts"]] == \
               [k["url"] for k in route["shortcuts"]]

    def test_die_datei_erklaert_ihren_zweck(self):
        assert "massgeblich" in self._statisch()["_comment"].lower()


# ---------------------------------------------------------------------------
# Service Worker
# ---------------------------------------------------------------------------

def _sw_quelle():
    with open(os.path.join(PROJEKT, "static", "sw.js"), encoding="utf-8") as f:
        return f.read()


class TestServiceWorker:

    def test_liegt_im_wurzelverzeichnis(self, client):
        """
        Der Geltungsbereich eines Service Workers reicht nie weiter als
        sein eigener Pfad. Unter /static/ koennte er die Startseite nicht
        behandeln.
        """
        antwort = client.get("/sw.js")
        assert antwort.status_code == 200
        assert antwort.headers["Content-Type"].startswith(
            "application/javascript")

    def test_skript_und_stylesheet_werden_revalidiert(self):
        """
        Die Aenderung, die fuer die App zaehlt.

        Vorher waren beide Cache-First, und die Cacheversion war die
        EINZIGE Garantie, dass eine Installation je etwas Neues sieht.
        In der TWA haette ein Nutzer mit altem Cache neue Auswertungen
        dauerhaft nicht gesehen - und ein Play-Update haette daran nichts
        geaendert, weil die App dieselbe Website laedt.
        """
        quelle = _sw_quelle()
        start = quelle.index("const REVALIDATE_PATHS")
        block = quelle[start:quelle.index("]", start)]

        assert '"/static/script.js"' in block
        assert '"/static/style.css"' in block
        # Die Uebersetzungen bleiben, was sie waren.
        assert '"/static/i18n/de.json"' in block
        assert '"/static/i18n/en.json"' in block

    def test_cacheversion_wurde_erhoeht(self):
        import re

        treffer = re.search(r'CACHE_NAME = "footsim-v(\d+)"', _sw_quelle())
        assert treffer, "CACHE_NAME nicht gefunden"
        assert int(treffer.group(1)) >= 33, (
            "geaenderte Assets brauchen eine neue Cacheversion")

    def test_api_bleibt_netz_only(self):
        quelle = _sw_quelle()
        assert "const isApi = API_ROUTES.some" in quelle
        start = quelle.index("const isApi = API_ROUTES.some")
        block = quelle[start:start + 320]
        assert "cache" not in block.lower().replace("caches.open", ""), (
            "API-Antworten duerfen nie in den Cache")

    def test_html_wird_weiterhin_nie_gecacht(self):
        """Die bestehende Sperre darf durch die Aenderung nicht wandern."""
        quelle = _sw_quelle()
        sperre = quelle.index('contentType.includes("text/html")')
        schreiben = quelle.index("cache.put(event.request")
        assert sperre < schreiben

    def test_offline_rueckfall_bleibt(self):
        quelle = _sw_quelle()
        assert "caches.match(`/offline?lang=" in quelle
        assert '"/offline?lang=de"' in quelle
        assert '"/offline?lang=en"' in quelle

    def test_die_startseite_bleibt_ungecacht(self):
        quelle = _sw_quelle()
        start = quelle.index("const STATIC_ASSETS")
        block = quelle[start:quelle.index("]", start)]
        assert '"/?lang=de"' not in block
        assert '"/?lang=en"' not in block

    def test_icons_sind_vorgecacht(self):
        quelle = _sw_quelle()
        start = quelle.index("const STATIC_ASSETS")
        block = quelle[start:quelle.index("]", start)]
        for name in ALLE_ICONS:
            assert name in block, name

    def test_der_cache_kennt_nur_die_aktuellen_icons(self):
        """
        Die alten Dateien bleiben auf der Platte liegen, gehoeren aber
        nicht mehr in den Cache - sonst laedt jede Installation zwei
        Icon-Saetze herunter, von denen einer nie benutzt wird.
        """
        quelle = _sw_quelle()
        start = quelle.index("const STATIC_ASSETS")
        block = quelle[start:quelle.index("]", start)]

        for veraltet in ("icon-192.png", "icon-512.png",
                         "icon-maskable-512.png"):
            assert f'"/static/images/{veraltet}"' not in block, veraltet


# ---------------------------------------------------------------------------
# Digital Asset Links
# ---------------------------------------------------------------------------

class TestAssetLinks:

    def test_ohne_konfiguration_keine_erfundene_beziehung(self, client, monkeypatch):
        """
        Eine leere Liste waere eine Aussage - naemlich "keine App gehoert
        zu dieser Domain". Ein Platzhalter waere schlicht falsch. 404 ist
        beides nicht.
        """
        monkeypatch.delenv("ANDROID_ASSETLINKS_SHA256", raising=False)
        antwort = client.get("/.well-known/assetlinks.json")

        assert antwort.status_code == 404
        assert antwort.headers["Content-Type"].startswith("application/json")
        assert antwort.get_json()["error"] == "assetlinks_not_configured"

    def test_leere_variable_zaehlt_als_nicht_konfiguriert(self, client, monkeypatch):
        monkeypatch.setenv("ANDROID_ASSETLINKS_SHA256", "   ")
        assert client.get("/.well-known/assetlinks.json").status_code == 404

    def test_mit_gueltigem_abdruck(self, client, monkeypatch):
        monkeypatch.setenv("ANDROID_ASSETLINKS_SHA256", GUELTIGER_ABDRUCK)
        antwort = client.get("/.well-known/assetlinks.json")

        assert antwort.status_code == 200
        assert antwort.headers["Content-Type"].startswith("application/json")
        # Keine Weiterleitung - Android folgt keiner.
        assert "Location" not in antwort.headers

        eintrag = antwort.get_json()[0]
        assert eintrag["relation"] == ["delegate_permission/common.handle_all_urls"]
        assert eintrag["target"]["namespace"] == "android_app"
        assert eintrag["target"]["package_name"] == PAKET_ID
        assert eintrag["target"]["sha256_cert_fingerprints"] == [GUELTIGER_ABDRUCK]

    def test_mehrere_abdruecke_werden_unterstuetzt(self, client, monkeypatch):
        """
        Waehrend der Testphase muessen Upload-Key und der App-Signing-Key
        von Google gleichzeitig gelten.
        """
        zweiter = ":".join(["CD"] * 32)
        monkeypatch.setenv("ANDROID_ASSETLINKS_SHA256",
                           f"{GUELTIGER_ABDRUCK}, {zweiter}")
        abdruecke = client.get("/.well-known/assetlinks.json").get_json()[0][
            "target"]["sha256_cert_fingerprints"]
        assert abdruecke == [GUELTIGER_ABDRUCK, zweiter]

    def test_kleinschreibung_wird_normalisiert(self, client, monkeypatch):
        monkeypatch.setenv("ANDROID_ASSETLINKS_SHA256", GUELTIGER_ABDRUCK.lower())
        abdruecke = client.get("/.well-known/assetlinks.json").get_json()[0][
            "target"]["sha256_cert_fingerprints"]
        assert abdruecke == [GUELTIGER_ABDRUCK]

    def test_doppelte_werden_entfernt(self, client, monkeypatch):
        monkeypatch.setenv("ANDROID_ASSETLINKS_SHA256",
                           f"{GUELTIGER_ABDRUCK},{GUELTIGER_ABDRUCK}")
        abdruecke = client.get("/.well-known/assetlinks.json").get_json()[0][
            "target"]["sha256_cert_fingerprints"]
        assert len(abdruecke) == 1

    @pytest.mark.parametrize("ungueltig", [
        "nicht-hex",
        "AB:CD",                                  # zu kurz
        ":".join(["AB"] * 31),                    # ein Paar zu wenig
        ":".join(["AB"] * 33),                    # ein Paar zu viel
        ":".join(["ZZ"] * 32),                    # keine Hexziffern
        "AB" * 32,                                # ohne Doppelpunkte
        "AB;CD;" + ";".join(["AB"] * 30),         # falsches Trennzeichen
    ])
    def test_ungueltiges_format_wird_nicht_veroeffentlicht(
            self, client, monkeypatch, ungueltig):
        monkeypatch.setenv("ANDROID_ASSETLINKS_SHA256", ungueltig)
        antwort = client.get("/.well-known/assetlinks.json")
        assert antwort.status_code == 404, (
            f"{ungueltig!r} haette eine unpruefbare Beziehung veroeffentlicht")

    def test_gueltiges_ueberlebt_neben_ungueltigem(self, client, monkeypatch):
        monkeypatch.setenv("ANDROID_ASSETLINKS_SHA256",
                           f"kaputt,{GUELTIGER_ABDRUCK}")
        antwort = client.get("/.well-known/assetlinks.json")
        assert antwort.status_code == 200
        abdruecke = antwort.get_json()[0]["target"]["sha256_cert_fingerprints"]
        assert abdruecke == [GUELTIGER_ABDRUCK]

    def test_paket_id_ist_nicht_konfigurierbar(self, monkeypatch):
        """
        Eine Vertrauensbeziehung zum falschen Paket waere eine
        Sicherheitsluecke, kein Konfigurationsfehler.
        """
        import app as app_module

        assert app_module.ANDROID_PACKAGE_NAME == PAKET_ID
        monkeypatch.setenv("ANDROID_PACKAGE_NAME", "de.boeswillig.app")
        assert app_module.ANDROID_PACKAGE_NAME == PAKET_ID

    def test_kein_abdruck_im_quelltext(self):
        """
        Der Fingerabdruck ist nicht geheim, gehoert aber trotzdem nicht
        fest in den Code - er wechselt, und ein Platzhalter wird
        irgendwann versehentlich uebernommen.
        """
        import re

        quelle = open(os.path.join(PROJEKT, "app.py"), encoding="utf-8").read()
        # 32 Hexpaare irgendwo im Quelltext waeren ein verdrahteter Wert.
        assert not re.search(r"(?:[0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2}", quelle)

    def test_env_beispiel_dokumentiert_die_variable_ohne_wert(self):
        pfad = os.path.join(PROJEKT, ".env.example")
        zeilen = [z.strip() for z in open(pfad, encoding="utf-8")]
        treffer = [z for z in zeilen if z.startswith("ANDROID_ASSETLINKS_SHA256")]
        assert treffer, "Variable fehlt in .env.example"

        wert = treffer[0].split("=", 1)[1]
        # Projektkonvention (test_audit_hardening): Platzhalter in spitzen
        # Klammern, niemals ein benutzbarer Wert.
        assert wert.startswith("<") and wert.endswith(">"), wert
        # Und er darf nicht wie ein Fingerabdruck aussehen.
        import re as _re
        assert not _re.search(r"(?:[0-9A-Fa-f]{2}:){2}", wert)


# ---------------------------------------------------------------------------
# Android-Modus: nur PayPal
# ---------------------------------------------------------------------------

class TestAndroidModus:
    """
    Der Modus darf genau eine Sache tun. Alles andere muss in Website und
    App identisch bleiben.
    """

    def _html(self, client, pfad="/"):
        antwort = client.get(pfad)
        assert antwort.status_code == 200
        return antwort.get_data(as_text=True)

    def test_die_website_zeigt_paypal_weiterhin(self, client):
        assert "paypal.me/elierdc" in self._html(client)

    def test_der_link_bleibt_auch_mit_platform_parameter_im_html(self, client):
        """
        Ausgeblendet wird im Browser, nicht am Server: Dieselbe Antwort
        bedient beide Faelle, damit kein zweiter Auslieferungspfad
        entsteht.
        """
        assert "paypal.me/elierdc" in self._html(client, "/?platform=android")

    def test_das_kopfskript_erkennt_den_parameter(self, client):
        html = self._html(client)
        assert "footsim-platform" in html
        assert "'platform'" in html or '"platform"' in html
        assert 'data-platform' in html

    def test_der_zustand_liegt_in_sessionstorage_nicht_localstorage(self, client):
        """
        TWA und Chrome teilen sich denselben Origin-Speicher. Ein
        dauerhafter Vermerk wuerde den Knopf auch im Browser entfernen.
        """
        html = self._html(client)
        start = html.index("footsim-platform")
        block = html[start - 600:start + 900]
        assert "sessionStorage" in block
        assert "localStorage.setItem('footsim-platform'" not in html

    def test_css_blendet_ausschliesslich_den_unterstuetzungsblock_aus(self):
        css = open(os.path.join(PROJEKT, "static", "style.css"),
                   encoding="utf-8").read()
        assert ':root[data-platform="android"] .support' in css

        start = css.index(':root[data-platform="android"]')
        block = css[start:css.index("}", start)]
        assert "display: none" in block

        # Genau eine Regel - der Modus darf nicht schleichend wachsen.
        assert css.count('[data-platform="android"]') == 1

    @pytest.mark.parametrize("pfad", [
        "/impressum", "/datenschutz", "/delete-account", "/offline",
    ])
    def test_rechts_und_hilfeseiten_bleiben_erreichbar(self, client, pfad):
        assert client.get(pfad).status_code == 200

    def test_kontakt_und_feedback_bleiben_im_html(self, client):
        html = self._html(client, "/?platform=android")
        for merkmal in ("/impressum", "/datenschutz"):
            assert merkmal in html, merkmal


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

class TestBereichsHistory:
    """
    Ohne History-Eintraege haette die Android-Zurueck-Taste aus JEDEM
    Bereich sofort die App geschlossen.

    Geprueft wird hier die Struktur im Quelltext; das tatsaechliche
    Verhalten im Browser deckt tests/test_browser_smoke.py ab.
    """

    def _js(self):
        return open(os.path.join(PROJEKT, "static", "script.js"),
                    encoding="utf-8").read()

    @staticmethod
    def _ohne_kommentare(block):
        """
        Nur die Anweisungen, ohne Zeilenkommentare.

        Ohne das pruefen die Zusicherungen unten den Fliesstext der
        Begruendungen mit - und ein Kommentar, der "pushState" erwaehnt,
        laesst einen Test umfallen, obwohl der Code stimmt. Genau das ist
        beim ersten Lauf dieser Datei passiert.
        """
        zeilen = []
        for zeile in block.split("\n"):
            ohne = zeile.split("//")[0]
            if ohne.strip():
                zeilen.append(ohne)
        return "\n".join(zeilen)

    def test_es_gibt_einen_eigenen_navigationsweg(self):
        quelle = self._js()
        assert "function navigateToArea(" in quelle
        assert "function setActiveArea(" in quelle

    def test_die_knoepfe_navigieren_statt_nur_umzuschalten(self):
        quelle = self._js()
        assert "navigateToArea(button.dataset.area)" in quelle
        assert "click\", () => setActiveArea(button.dataset.area)" not in quelle

    def test_derselbe_bereich_erzeugt_keinen_zweiten_eintrag(self):
        quelle = self._js()
        start = quelle.index("function navigateToArea(")
        block = quelle[start:quelle.index("\n}", start)]
        assert "state.activeArea === area" in block
        assert "return" in block

    def test_popstate_schaltet_um_ohne_neuen_eintrag(self):
        quelle = self._js()
        start = quelle.index('addEventListener("popstate"')
        block = self._ohne_kommentare(quelle[start:quelle.index("});", start)])
        assert "setActiveArea(" in block
        assert "pushState" not in block, "popstate darf keinen Eintrag erzeugen"

    def test_der_seitenaufbau_erzeugt_keinen_extra_eintrag(self):
        quelle = self._js()
        start = quelle.index("async function init()")
        block = self._ohne_kommentare(quelle[start:quelle.index("\n}", start)])
        assert "replaceState" in block
        assert "pushState" not in block

    def test_einmalige_auth_parameter_wandern_nicht_mit(self):
        """
        Ein Rueckstellungstoken gehoert in genau einen Seitenaufruf und
        nicht in jeden weiteren History-Eintrag.
        """
        quelle = self._js()
        start = quelle.index("TRANSIENT_QUERY_KEYS")
        block = quelle[start:quelle.index("]", start)]
        for schluessel in ("reset_token", "verify_error", "verified"):
            assert schluessel in block, schluessel

    def test_sprache_und_plattform_bleiben_erhalten(self):
        """
        areaHistoryUrl darf lang und platform nicht wegwerfen - sonst
        faellt die App beim ersten Bereichswechsel aus dem Android-Modus.
        """
        quelle = self._js()
        start = quelle.index("function areaHistoryUrl(")
        block = self._ohne_kommentare(quelle[start:quelle.index("\n}", start)])

        # Geloescht wird ausschliesslich die Liste der einmaligen
        # Parameter - kein weiterer Schluessel darf zusaetzlich fallen.
        assert "TRANSIENT_QUERY_KEYS.forEach" in block
        assert block.count("searchParams.delete") == 1
        assert '"lang"' not in block and "'lang'" not in block
        assert '"platform"' not in block and "'platform'" not in block

    def test_nur_bekannte_bereiche_werden_angenommen(self):
        quelle = self._js()
        for funktion in ("function navigateToArea(", "function areaFromUrl("):
            start = quelle.index(funktion)
            block = quelle[start:quelle.index("\n}", start)]
            assert "AREAS.includes(" in block, funktion
