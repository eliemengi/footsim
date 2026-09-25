# -*- coding: utf-8 -*-
"""
PDF-Komprimierer: /tools/pdf/compress (Backend, Kompression, Oberflaeche).

Die Tests laufen OHNE Netzwerk, OHNE Datenbank und OHNE fremden Dienst.
Die Testdokumente entstehen hier: eine bildlastige PDF ueber Pillow und
eine echte Text-und-Vektor-PDF von Hand. Nur so ist pruefbar, was der
Kompressor verspricht - dass Bilder kleiner werden UND Text Text bleibt.

CSRF bleibt in allen Tests scharf gestellt. Der Client bedient den Schutz
ueber conftest.mit_csrf wie das echte Frontend; WTF_CSRF_ENABLED wird
NICHT abgeschaltet, denn genau dieser Schutz soll mitgeprueft werden.
"""

import io
import os
import random
import re
from pathlib import Path

import pytest
from pypdf import PdfReader

from tests.conftest import mit_csrf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROUTE = "/tools/pdf/compress"


def _read(*parts):
    return (PROJECT_ROOT.joinpath(*parts)).read_text(encoding="utf-8")


@pytest.fixture
def client():
    """
    Testclient mit scharfem CSRF-Schutz und ausgesetzter Ratenbegrenzung.

    Die Grenze liegt bei 12 Anfragen pro Stunde - eine Testdatei mit
    mehreren Faellen liefe sonst in 429 statt in die Pruefung. Dass die
    Begrenzung am Endpunkt haengt UND greift, prueft
    TestAbweisung.test_die_ratenbegrenzung_greift ausdruecklich.
    """
    os.environ.setdefault("DATABASE_URL", "sqlite://")
    os.environ.setdefault("SECRET_KEY", "test")
    import app as appmod
    from src.models.extensions import limiter

    appmod.app.config["TESTING"] = True
    vorher = limiter.enabled
    limiter.enabled = False
    try:
        with appmod.app.test_client() as c:
            yield mit_csrf(c, "/tools/pdf")
    finally:
        limiter.enabled = vorher


# ---------------------------------------------------------------------------
# Testdokumente
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def bild_pdf():
    """
    Fotoartige Seiten: Rauschen laesst sich nicht verlustfrei wegrechnen.

    Eine PDF aus Flaechenfarben waere wertlos - die waere schon durch die
    Stromkompression klein, und der Test wuerde nie zeigen, ob die
    Bildkompression ueberhaupt greift.
    """
    from PIL import Image, ImageDraw

    random.seed(11)
    seiten = []
    for _ in range(3):
        bild = Image.new("RGB", (1200, 900))
        pixel = bild.load()
        for y in range(0, 900, 2):
            for x in range(0, 1200, 2):
                farbe = (random.randint(0, 255), random.randint(0, 255),
                         random.randint(0, 255))
                for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
                    pixel[x + dx, y + dy] = farbe
        ImageDraw.Draw(bild).rectangle([40, 40, 500, 260], fill=(245, 245, 245))
        seiten.append(bild)

    puffer = io.BytesIO()
    seiten[0].save(puffer, "PDF", save_all=True, append_images=seiten[1:],
                   resolution=150.0)
    return puffer.getvalue()


@pytest.fixture(scope="module")
def text_pdf():
    """
    Eine echte Text-und-Vektor-PDF, von Hand gebaut.

    reportlab ist nicht im Projekt, und fuer den Zweck genuegt ein
    handgeschriebener Seitenbaum: Helvetica als Standardschrift, ein
    gefuelltes Rechteck und eine Linie als Vektorelemente.
    """
    text = "FootSim Kompressionstest"
    objekte = []
    inhalt_vorlage = (
        "0.2 0.4 0.9 rg\n"
        "72 600 200 80 re f\n"
        "BT /F1 24 Tf 72 700 Td ({text}) Tj ET\n"
        "0 0 0 RG 2 w 72 560 m 400 560 l S\n"
    )

    seiten_ids = [4, 6]
    objekte.append((1, b"<< /Type /Catalog /Pages 2 0 R >>"))
    kids = b" ".join(f"{i} 0 R".encode() for i in seiten_ids)
    objekte.append((2, b"<< /Type /Pages /Count 2 /Kids [" + kids + b"] >>"))
    objekte.append((3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))

    for nummer, seiten_id in enumerate(seiten_ids, start=1):
        objekte.append((seiten_id,
                        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                        b"/Resources << /Font << /F1 3 0 R >> >> /Contents "
                        + str(seiten_id + 1).encode() + b" 0 R >>"))
        strom = inhalt_vorlage.format(
            text=f"{text} Seite {nummer}").encode("latin-1")
        objekte.append((seiten_id + 1,
                        b"<< /Length " + str(len(strom)).encode() + b" >>\n"
                        b"stream\n" + strom + b"\nendstream"))

    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for nummer, koerper in sorted(objekte):
        offsets[nummer] = len(out)
        out += f"{nummer} 0 obj\n".encode() + koerper + b"\nendobj\n"

    start = len(out)
    hoechste = max(offsets) + 1
    out += f"xref\n0 {hoechste}\n".encode() + b"0000000000 65535 f \n"
    for nummer in range(1, hoechste):
        out += (f"{offsets[nummer]:010d} 00000 n \n".encode()
                if nummer in offsets else b"0000000000 65535 f \n")
    out += (f"trailer\n<< /Size {hoechste} /Root 1 0 R >>\n"
            f"startxref\n{start}\n%%EOF\n").encode()
    return bytes(out)


def komprimiere(client, daten, name="Bewerbung.pdf", level=None, feld="file"):
    form = {feld: (io.BytesIO(daten), name)}
    if level is not None:
        form["level"] = level
    return client.post(ROUTE, data=form, content_type="multipart/form-data")


# ---------------------------------------------------------------------------
# 1. Die Route
# ---------------------------------------------------------------------------

class TestRoute:

    def test_eine_gueltige_pdf_wird_angenommen(self, client, bild_pdf):
        antwort = komprimiere(client, bild_pdf)
        assert antwort.status_code == 200, antwort.get_data(as_text=True)[:200]
        assert antwort.headers["Content-Type"] == "application/pdf"

    def test_das_ergebnis_ist_wieder_eine_gueltige_pdf(self, client, bild_pdf):
        antwort = komprimiere(client, bild_pdf)
        ergebnis = PdfReader(io.BytesIO(antwort.data))
        assert len(ergebnis.pages) > 0

    def test_die_seitenzahl_bleibt_gleich(self, client, bild_pdf):
        """Eine stillschweigend verkuerzte PDF waere der schlimmste Ausgang."""
        vorher = len(PdfReader(io.BytesIO(bild_pdf)).pages)
        for stufe in ("schonend", "standard", "stark"):
            antwort = komprimiere(client, bild_pdf, level=stufe)
            assert antwort.status_code == 200, stufe
            assert len(PdfReader(io.BytesIO(antwort.data)).pages) == vorher, stufe
            assert antwort.headers["X-Total-Pages"] == str(vorher)

    def test_die_kopfzeilen_beschreiben_das_ergebnis(self, client, bild_pdf):
        antwort = komprimiere(client, bild_pdf, level="stark")
        kopf = antwort.headers

        original = int(kopf["X-Original-Bytes"])
        komprimiert = int(kopf["X-Compressed-Bytes"])
        gespart = int(kopf["X-Saved-Bytes"])

        assert original == len(bild_pdf)
        assert komprimiert == len(antwort.data)
        assert gespart == original - komprimiert
        # Die Prozentzahl muss zu den Bytes passen, nicht bloss da stehen.
        assert abs(float(kopf["X-Saved-Percent"])
                   - (gespart * 100.0 / original)) < 0.1
        assert kopf["X-Compress-Level"] == "stark"

    def test_der_dateiname_wird_gekennzeichnet(self, client, bild_pdf):
        antwort = komprimiere(client, bild_pdf, name="Bewerbung.pdf")
        assert "Bewerbung-komprimiert.pdf" in antwort.headers["Content-Disposition"]

    @pytest.mark.parametrize("eingabe,erwartet", [
        ("Bewerbung.pdf", "Bewerbung-komprimiert.pdf"),
        ("Bewerbung.PDF", "Bewerbung-komprimiert.pdf"),
        ("ohne endung", "ohne_endung-komprimiert.pdf"),
        ("../../etc/passwd.pdf", "etc_passwd-komprimiert.pdf"),
        ("", "dokument-komprimiert.pdf"),
        (".pdf", "dokument-komprimiert.pdf"),
    ])
    def test_der_ausgabename_wird_sicher_gebildet(self, eingabe, erwartet):
        import app as appmod
        assert appmod.pdf_build_compressed_name(eingabe) == erwartet

    def test_ohne_angabe_gilt_standard(self, client, bild_pdf):
        antwort = komprimiere(client, bild_pdf)
        assert antwort.headers["X-Compress-Level"] == "standard"


# ---------------------------------------------------------------------------
# 2. Was abgewiesen wird
# ---------------------------------------------------------------------------

class TestAbweisung:

    def test_ohne_datei_kein_ergebnis(self, client):
        antwort = client.post(ROUTE, data={}, content_type="multipart/form-data")
        assert antwort.status_code == 400
        assert "Keine Datei" in antwort.get_json()["error"]

    def test_mehrere_dateien_werden_abgewiesen(self, client, bild_pdf):
        antwort = client.post(
            ROUTE,
            data={"file": [(io.BytesIO(bild_pdf), "a.pdf"),
                           (io.BytesIO(bild_pdf), "b.pdf")]},
            content_type="multipart/form-data")
        assert antwort.status_code == 400
        assert "genau eine" in antwort.get_json()["error"]

    def test_ein_falscher_dateityp_wird_abgewiesen(self, client):
        from PIL import Image
        puffer = io.BytesIO()
        Image.new("RGB", (30, 30), (1, 2, 3)).save(puffer, format="PNG")
        antwort = komprimiere(client, puffer.getvalue(), name="bild.png")
        assert antwort.status_code == 400
        assert "Nur PDF" in antwort.get_json()["error"]

    def test_eine_beschaedigte_pdf_wird_abgewiesen(self, client):
        antwort = komprimiere(client, b"%PDF-1.4 kein xref, kein Seitenbaum",
                              name="kaputt.pdf")
        assert antwort.status_code == 400
        assert "Beschaedigte" in antwort.get_json()["error"]

    def test_eine_leere_datei_wird_abgewiesen(self, client):
        antwort = komprimiere(client, b"", name="leer.pdf")
        assert antwort.status_code == 400

    def test_eine_verschluesselte_pdf_wird_sauber_behandelt(self, client, text_pdf):
        """
        Mit Passwort darf es keinen Stacktrace geben, sondern eine
        verstaendliche Meldung - und kein Ergebnis.
        """
        from pypdf import PdfWriter
        schreiber = PdfWriter(clone_from=PdfReader(io.BytesIO(text_pdf)))
        schreiber.encrypt("geheim")
        puffer = io.BytesIO()
        schreiber.write(puffer)

        antwort = komprimiere(client, puffer.getvalue(), name="geheim.pdf")
        assert antwort.status_code == 400
        meldung = antwort.get_json()["error"]
        assert "passwortgeschuetzt" in meldung.lower()

    def test_der_endung_wird_nicht_geglaubt(self, client):
        """
        Eine als .pdf getarnte Fremddatei darf nicht in die Verarbeitung.
        Die Endung entscheidet das nicht - pypdf oeffnet die Datei
        wirklich, und erst das zaehlt.
        """
        from tests.test_audit_hardening import _minimal_fits_bytes

        antwort = komprimiere(client, _minimal_fits_bytes(), name="urlaub.pdf")
        assert antwort.status_code == 400
        assert "Beschaedigte" in antwort.get_json()["error"]

    def test_eine_unbekannte_stufe_wird_abgewiesen(self, client, bild_pdf):
        antwort = komprimiere(client, bild_pdf, level="brutal")
        assert antwort.status_code == 400
        assert "Komprimierungsstufe" in antwort.get_json()["error"]

    def test_keine_internen_pfade_in_fehlermeldungen(self, client):
        antwort = komprimiere(client, b"%PDF-1.4 kaputt", name="kaputt.pdf")
        text = antwort.get_data(as_text=True)
        for verboten in ("Traceback", "footsim_pdfcompress", "site-packages",
                         "C:\\", "/tmp/", ".py\"", "pypdf."):
            assert verboten not in text, verboten

    def test_ohne_csrf_token_kein_ergebnis(self, bild_pdf):
        """
        Der Schutz muss auch fuer den neuen Endpunkt gelten. Dieser Test
        laeuft ohne mit_csrf - also ohne Token.
        """
        import app as appmod
        original_testing = appmod.app.config.get("TESTING")
        original_csrf = appmod.app.config.get("WTF_CSRF_ENABLED")
        appmod.app.config["TESTING"] = False
        appmod.app.config["WTF_CSRF_ENABLED"] = True
        try:
            with appmod.app.test_client() as roh_client:
                roh_client.get("/tools/pdf")
                antwort = roh_client.post(
                    ROUTE,
                    data={"file": (io.BytesIO(bild_pdf), "a.pdf")},
                    content_type="multipart/form-data")
            assert antwort.status_code == 400
        finally:
            appmod.app.config["TESTING"] = original_testing
            appmod.app.config["WTF_CSRF_ENABLED"] = original_csrf

    def test_die_seitenobergrenze_gilt_auch_hier(self, client, monkeypatch, text_pdf):
        import app as appmod
        monkeypatch.setattr(appmod, "PDF_MAX_TOTAL_PAGES", 1)
        antwort = komprimiere(client, text_pdf, name="zwei_seiten.pdf")
        assert antwort.status_code == 400
        assert "Zu viele Seiten" in antwort.get_json()["error"]

    def test_die_uebertragungsgrenze_bleibt_unveraendert(self):
        """Der neue Endpunkt erbt MAX_CONTENT_LENGTH, er umgeht sie nicht."""
        import app as appmod
        assert appmod.app.config["MAX_CONTENT_LENGTH"] == 50 * 1024 * 1024

    def test_der_endpunkt_ist_ratenbegrenzt(self):
        quelle = _read("app.py")
        block = quelle[quelle.index('@app.route("/tools/pdf/compress"'):]
        block = block[:block.index("def pdf_compress_run")]
        assert "@limiter.limit(" in block

    def test_die_ratenbegrenzung_greift(self, text_pdf):
        """
        Nicht nur der Dekorator muss dastehen - er muss auch wirken.
        Dieser Test laeuft mit EINGESCHALTETER Begrenzung.
        """
        import app as appmod
        from src.models.extensions import limiter

        appmod.app.config["TESTING"] = True
        vorher = limiter.enabled
        limiter.enabled = True
        try:
            with appmod.app.test_client() as c:
                roh = mit_csrf(c, "/tools/pdf")
                codes = []
                # Die winzige Text-PDF wird abgewiesen (bereits optimiert)
                # und ist deshalb billig - gezaehlt wird sie trotzdem.
                for _ in range(14):
                    codes.append(komprimiere(roh, text_pdf, name="k.pdf").status_code)
        finally:
            limiter.enabled = vorher
            limiter.reset()

        assert 429 in codes, f"keine Begrenzung erreicht: {codes}"

    def test_der_endpunkt_ist_nicht_von_csrf_ausgenommen(self):
        quelle = _read("app.py")
        code = "\n".join(z for z in quelle.splitlines()
                         if not z.strip().startswith("#"))
        assert "csrf.exempt" not in code


# ---------------------------------------------------------------------------
# 3. Die Kompression selbst
# ---------------------------------------------------------------------------

class TestKompression:

    def test_standard_macht_eine_bildlastige_pdf_kleiner(self, client, bild_pdf):
        antwort = komprimiere(client, bild_pdf, level="standard")
        assert antwort.status_code == 200
        assert len(antwort.data) < len(bild_pdf)

    def test_stark_ist_nicht_groesser_als_standard(self, client, bild_pdf):
        standard = komprimiere(client, bild_pdf, level="standard")
        stark = komprimiere(client, bild_pdf, level="stark")
        assert standard.status_code == 200 and stark.status_code == 200
        assert len(stark.data) <= len(standard.data)

    def test_schonend_liefert_eine_gueltige_datei(self, client, bild_pdf):
        """
        Schonend rechnet nur verlustfrei. Es darf dabei kleiner werden
        oder als 'bereits optimiert' abgewiesen werden - beides ist
        ehrlich. Was NICHT passieren darf: eine kaputte Datei.
        """
        antwort = komprimiere(client, bild_pdf, level="schonend")
        assert antwort.status_code in (200, 400)

        if antwort.status_code == 200:
            assert len(antwort.data) <= len(bild_pdf)
            assert len(PdfReader(io.BytesIO(antwort.data)).pages) == 3
        else:
            assert antwort.get_json().get("already_optimized") is True

    def test_schonend_laesst_die_bilder_unangetastet(self, bild_pdf, tmp_path):
        """Die schonende Stufe darf keine Bildqualitaet kosten."""
        import app as appmod

        quelle = tmp_path / "quelle.pdf"
        quelle.write_bytes(bild_pdf)
        ziel = tmp_path / "ziel.pdf"
        appmod.pdf_compress_document(str(quelle), str(ziel), "schonend")

        vorher = PdfReader(str(quelle)).pages[0].images[0].data
        nachher = PdfReader(str(ziel)).pages[0].images[0].data
        assert nachher == vorher

    def test_standard_schreibt_die_bilder_wirklich_neu(self, bild_pdf, tmp_path):
        import app as appmod

        quelle = tmp_path / "quelle.pdf"
        quelle.write_bytes(bild_pdf)
        ziel = tmp_path / "ziel.pdf"
        appmod.pdf_compress_document(str(quelle), str(ziel), "standard")

        vorher = PdfReader(str(quelle)).pages[0].images[0]
        nachher = PdfReader(str(ziel)).pages[0].images[0]
        assert len(nachher.data) < len(vorher.data)
        # Dieselbe Bildgroesse - Standard rechnet NICHT herunter.
        assert nachher.image.size == vorher.image.size

    def test_stark_rechnet_sehr_grosse_bilder_herunter(self, bild_pdf, tmp_path):
        import app as appmod

        quelle = tmp_path / "quelle.pdf"
        quelle.write_bytes(bild_pdf)
        ziel = tmp_path / "ziel.pdf"
        appmod.pdf_compress_document(str(quelle), str(ziel), "stark")

        nachher = PdfReader(str(ziel)).pages[0].images[0]
        assert max(nachher.image.size) <= appmod.PDF_COMPRESS_LEVELS["stark"]["max_edge"]

    def test_text_und_vektoren_bleiben_erhalten(self, client, text_pdf):
        """
        DER KERNVERTRAG GEGEN RASTERISIERUNG.

        Nach der Kompression muss der Text noch extrahierbar sein, die
        Schrift referenziert und die Vektoroperatoren im Inhaltsstrom
        vorhanden. Waere seitenweise rasterisiert worden, faellt genau
        das hier auf.
        """
        import app as appmod

        # Ueber die reine Funktion, damit auch der Fall "nicht kleiner"
        # pruefbar bleibt - der Vertrag gilt unabhaengig von der Groesse.
        import tempfile
        verzeichnis = tempfile.mkdtemp()
        try:
            quelle = os.path.join(verzeichnis, "q.pdf")
            ziel = os.path.join(verzeichnis, "z.pdf")
            with open(quelle, "wb") as datei:
                datei.write(text_pdf)

            for stufe in ("schonend", "standard", "stark"):
                appmod.pdf_compress_document(quelle, ziel, stufe)
                seite = PdfReader(ziel).pages[0]

                assert "FootSim Kompressionstest" in seite.extract_text(), stufe
                assert "/F1" in str(seite["/Resources"]["/Font"]), stufe

                strom = seite.get_contents().get_data()
                assert b" re " in strom and b" l " in strom, stufe
                # Kein eingebettetes Bild - nichts wurde rasterisiert.
                assert len(list(seite.images)) == 0, stufe
        finally:
            import shutil
            shutil.rmtree(verzeichnis, ignore_errors=True)

    def test_ein_nicht_kleineres_ergebnis_gilt_nicht_als_erfolg(self, client, text_pdf):
        """
        Die winzige Text-PDF wird durch den Writer groesser. Dann darf
        weder eine Datei noch eine Prozentzahl geliefert werden.
        """
        antwort = komprimiere(client, text_pdf, name="Vertrag.pdf")
        assert antwort.status_code == 400
        daten = antwort.get_json()
        assert daten["already_optimized"] is True
        assert "bereits stark optimiert" in daten["error"]
        assert "X-Saved-Percent" not in antwort.headers
        assert antwort.headers["Content-Type"].startswith("application/json")

    def test_bilder_mit_transparenz_werden_uebersprungen(self, tmp_path):
        """
        JPEG kennt keinen Alphakanal. Ein Ersetzen wuerde die Transparenz
        stillschweigend durch eine Farbe ersetzen - solche Bilder bleiben
        deshalb unveraendert, statt das Dokument zu verfaelschen.
        """
        import app as appmod
        from PIL import Image
        from pypdf import PdfWriter

        assert "RGBA" in appmod.PDF_COMPRESS_SKIP_MODES
        assert "LA" in appmod.PDF_COMPRESS_SKIP_MODES
        assert "P" in appmod.PDF_COMPRESS_SKIP_MODES
        # Bitonale Scans werden durch JPEG groesser, nicht kleiner.
        assert "1" in appmod.PDF_COMPRESS_SKIP_MODES

    def test_ein_einzelnes_bild_kostet_nicht_das_dokument(self, bild_pdf, tmp_path,
                                                          monkeypatch):
        """
        Schlaegt das Ersetzen EINES Bildes fehl, muss der Rest des
        Dokuments unversehrt herauskommen.
        """
        import app as appmod

        original_replace = None
        aufrufe = {"n": 0}

        def kaputtes_replace(self, new_image, **kwargs):
            aufrufe["n"] += 1
            raise ValueError("Bild kann nicht ersetzt werden")

        from pypdf._page import ImageFile
        monkeypatch.setattr(ImageFile, "replace", kaputtes_replace)

        quelle = tmp_path / "quelle.pdf"
        quelle.write_bytes(bild_pdf)
        ziel = tmp_path / "ziel.pdf"

        seiten = appmod.pdf_compress_document(str(quelle), str(ziel), "standard")

        assert aufrufe["n"] > 0, "der Fehlerfall wurde nicht ausgeloest"
        assert seiten == 3
        ergebnis = PdfReader(str(ziel))
        assert len(ergebnis.pages) == 3
        assert len(ergebnis.pages[0].images) == 1

    def test_die_drei_stufen_sind_die_angebotenen(self):
        import app as appmod
        assert set(appmod.PDF_COMPRESS_LEVELS) == {"schonend", "standard", "stark"}
        assert appmod.PDF_COMPRESS_DEFAULT_LEVEL == "standard"
        # Schonend fasst Bilder nicht an, die anderen beiden schon.
        assert appmod.PDF_COMPRESS_LEVELS["schonend"]["quality"] is None
        assert 75 <= appmod.PDF_COMPRESS_LEVELS["standard"]["quality"] <= 80
        assert 50 <= appmod.PDF_COMPRESS_LEVELS["stark"]["quality"] <= 60

    def test_keine_temporaeren_dateien_bleiben_zurueck(self, client, bild_pdf):
        import glob
        import tempfile

        muster = os.path.join(tempfile.gettempdir(), "footsim_pdfcompress_*")
        vorher = set(glob.glob(muster))

        assert komprimiere(client, bild_pdf).status_code == 200
        assert komprimiere(client, b"%PDF kaputt", name="k.pdf").status_code == 400

        assert set(glob.glob(muster)) == vorher

    def test_kein_netzwerkdienst_im_spiel(self):
        """Lokal verarbeitet - kein externer Dienst, keine Anfrage."""
        quelle = _read("app.py")
        block = quelle[quelle.index("#  PDF KOMPRIMIEREN"):
                       quelle.index("# SPIELERVERGLEICH (Phase 3)")]
        for verboten in ("requests.", "urlopen", "urllib", "socket",
                         "subprocess", "ghostscript", "Ghostscript",
                         "http://", "https://"):
            assert verboten not in block, verboten


# ---------------------------------------------------------------------------
# 4. Der Merger bleibt unangetastet
# ---------------------------------------------------------------------------

class TestMergerBleibt:

    def test_die_merge_route_gibt_es_weiterhin(self, client):
        from PIL import Image
        puffer = io.BytesIO()
        Image.new("RGB", (40, 30), (9, 9, 9)).save(puffer, format="PNG")
        puffer.seek(0)

        antwort = client.post("/tools/pdf/merge",
                              data={"files": (puffer, "echt.png")},
                              content_type="multipart/form-data")
        assert antwort.status_code == 200, antwort.get_data(as_text=True)[:200]
        assert antwort.headers["Content-Type"] == "application/pdf"

    def test_die_seite_traegt_beide_werkzeuge(self, client):
        seite = client.get("/tools/pdf")
        assert seite.status_code == 200
        text = seite.get_data(as_text=True)
        assert 'id="merge-view"' in text
        assert 'id="compress-view"' in text
        assert 'name="csrf-token"' in text

    def test_die_bestehenden_elemente_bleiben(self):
        """
        Der Merge haengt an diesen IDs - im JavaScript und in den
        Browsertests. Sie duerfen durch das zweite Werkzeug nicht
        verschwinden oder doppelt werden.
        """
        html = _read("templates", "pdfmerge.html")
        for kennung in ('id="dropzone"', 'id="file-input"', 'id="merge-btn"',
                        'id="clear-btn"', 'id="output-name"',
                        'id="reverse-order"', 'id="download-link"',
                        'id="new-merge-btn"', 'id="status"'):
            assert html.count(kennung) == 1, kennung

    def test_der_ios_downloadweg_bleibt_beim_merge(self):
        js = _read("static", "pdfmerge.js")
        assert 'const PDF_ROUTE = "/tools/pdf/merge";' in js
        assert js.count("formular.submit()") == 1
        assert js.count("if (istIosApp())") == 1


# ---------------------------------------------------------------------------
# 5. Die Oberflaeche
# ---------------------------------------------------------------------------

class TestOberflaeche:

    def test_der_werkzeugwechsel_ist_da(self):
        html = _read("templates", "pdfmerge.html")
        assert 'id="tool-merge-btn"' in html
        assert 'id="tool-compress-btn"' in html
        assert "PDF zusammenf" in html
        assert "PDF komprimieren" in html

    def test_alle_drei_stufen_stehen_zur_wahl(self):
        html = _read("templates", "pdfmerge.html")
        for wert in ("schonend", "standard", "stark"):
            assert f'value="{wert}"' in html, wert
        for beschriftung in ("Schonend", "Standard", "Stark"):
            assert f"<strong>{beschriftung}</strong>" in html, beschriftung

    def test_standard_ist_vorausgewaehlt(self):
        html = _read("templates", "pdfmerge.html")
        treffer = re.search(r'value="standard"[^>]*checked', html)
        assert treffer, "Standard ist nicht vorausgewaehlt"
        # Und genau eine Stufe ist vorausgewaehlt.
        assert len(re.findall(r'name="compress-level"[^>]*checked', html)) == 1

    def test_die_stufen_sind_erklaert(self):
        html = _read("templates", "pdfmerge.html")
        assert "Maximale Qualit" in html
        assert "Balance" in html
        assert "st\u00e4rker komprimiert" in html

    def test_nur_eine_pdf_zur_auswahl(self):
        """Der Kompressor nimmt genau eine Datei - kein multiple."""
        html = _read("templates", "pdfmerge.html")
        block = html[html.index('id="c-dropzone"'):html.index('id="c-add-btn"')]
        assert 'accept=".pdf"' in block
        assert "multiple" not in block

    def test_die_anfrage_geht_an_den_neuen_endpunkt(self):
        js = _read("static", "pdfmerge.js")
        assert 'const COMPRESS_ROUTE = "/tools/pdf/compress";' in js
        block = js[js.index("async function compressPdf("):]
        assert "await fetch(COMPRESS_ROUTE" in block
        assert 'formData.append("file", compressFile)' in block
        assert 'formData.append("level", level)' in block

    def test_das_csrf_token_wird_mitgeschickt(self):
        js = _read("static", "pdfmerge.js")
        block = js[js.index("async function compressPdf("):]
        assert '"X-CSRFToken": csrfMeta.content' in block

    def test_das_ergebnis_zeigt_vorher_und_nachher(self):
        html = _read("templates", "pdfmerge.html")
        for kennung in ('id="c-before"', 'id="c-after"', 'id="c-saved"'):
            assert kennung in html, kennung

        js = _read("static", "pdfmerge.js")
        block = js[js.index("function cShowResult("):]
        assert "cBefore.textContent = formatSize(originalBytes)" in block
        assert "cAfter.textContent = formatSize(compressedBytes)" in block
        assert "kleiner" in block

    def test_die_prozentzahl_kommt_vom_server(self):
        """
        Der Browser kennt die Ergebnisgroesse nur aus der Antwort. Eine
        eigene Schaetzung waere eine erfundene Zahl.
        """
        js = _read("static", "pdfmerge.js")
        block = js[js.index("function savedPercent("):]
        assert 'headers.get("X-Saved-Percent")' in block

    def test_der_downloadname_endet_auf_komprimiert(self):
        js = _read("static", "pdfmerge.js")
        assert "-komprimiert.pdf" in js

    def test_der_wartezustand_ist_beschriftet(self):
        js = _read("static", "pdfmerge.js")
        assert "PDF wird komprimiert" in js

    def test_ein_stufenwechsel_entwertet_das_alte_ergebnis(self):
        """
        Nach einem Wechsel zeigte die Box sonst eine Ersparnis, die zu
        einer anderen Stufe gehoert.
        """
        js = _read("static", "pdfmerge.js")
        block = js[js.index('document.querySelectorAll(\'input[name="compress-level"]\')'):]
        assert "cResultBox.classList.add(\"hidden\")" in block

    def test_der_knopf_wird_immer_wieder_freigegeben(self):
        js = _read("static", "pdfmerge.js")
        block = js[js.index("async function compressPdf("):]
        assert "finally" in block
        assert "compressBtn.disabled = false" in block

    def test_die_fehlermeldung_des_servers_wird_gezeigt(self):
        js = _read("static", "pdfmerge.js")
        block = js[js.index("async function compressPdf("):]
        assert "errorData.error" in block
        assert "cSetStatus(error.message)" in block

    def test_das_stylesheet_kennt_die_neuen_bausteine(self):
        css = _read("static", "pdfmerge.css")
        for regel in (".tool-switch", ".tool-switch-btn", ".level-option",
                      ".compress-compare", ".compress-saved"):
            assert regel in css, regel

    def test_die_neuen_bausteine_sind_auch_mobil_bedacht(self):
        css = _read("static", "pdfmerge.css")
        block = css[css.index("@media (max-width: 768px)"):]
        assert ".tool-switch-btn" in block
        assert ".compress-compare" in block
