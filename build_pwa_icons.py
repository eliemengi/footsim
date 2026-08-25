"""
Erzeugt die PWA-/Android-Icons aus dem einen vorhandenen Logo.

AUFRUF
------
    py build_pwa_icons.py

WARUM ES DIESES SKRIPT GIBT
---------------------------
static/images/ enthielt genau eine Datei: logofoot.png, 1024x1024, rund
ein Megabyte. Das Manifest deklarierte sie gleichzeitig als 192x192 UND
als 512x512 - zwei Angaben, die beide nicht stimmten.

Fuer eine Trusted Web Activity ist das kein Schoenheitsfehler: Bubblewrap
liest das Manifest zur Bauzeit und erzeugt daraus die Launcher-Icons. Wer
falsche Groessen deklariert, bekommt unscharfe oder beschnittene Symbole
auf dem Startbildschirm.

DIE MASKABLE-RECHNUNG
---------------------
Android schneidet adaptive Icons je nach Hersteller kreisrund, als
Squircle oder abgerundet zu. Garantiert sichtbar bleibt nur ein Kreis mit
80 Prozent des Bilddurchmessers - die "safe zone".

    Sichere Kreisflaeche bei 512 px:  0.8 * 512      = 409.6 px
    Groesstes Quadrat darin:          409.6 / sqrt(2) = 289.6 px

logofoot.png ist vollflaechig opak und randlos (geprueft: getbbox()
liefert die volle Flaeche, Alpha durchgehend 255). Es hat also KEINEN
eigenen Sicherheitsrand. Jedes Quadrat groesser als rund 289 px wuerde an
den Ecken beschnitten.

Deshalb wird das Logo auf 288 px verkleinert und auf einer 512er Flaeche
in der Hintergrundfarbe des Manifests zentriert. Das wirkt zunaechst
klein, ist aber genau richtig: Auf einem runden Launcher fuellt es rund
70 Prozent der sichtbaren Kreisflaeche - der Wert, den Androids eigene
Gestaltungsrichtlinie fuer das Motiv eines adaptiven Icons vorsieht.

WAS HIER NICHT PASSIERT
-----------------------
Keine neue Bildgestaltung, kein anderes Logo, keine Farbaenderung am
Motiv. Es wird ausschliesslich skaliert und - fuer die maskable Fassung -
auf der bereits im Manifest festgelegten Hintergrundfarbe zentriert.
"""

import os
import sys

QUELLE = os.path.join("static", "images", "logofoot.png")
ZIEL_VERZEICHNIS = os.path.join("static", "images")

#: Hintergrundfarbe des Manifests (background_color / theme_color).
#: Der Rand des maskable Icons muss dieselbe Farbe tragen, sonst entsteht
#: beim Zuschneiden ein sichtbarer Rahmen.
HINTERGRUND = (0x0D, 0x1B, 0x30, 255)

#: Kantenlaenge des Motivs im maskable Icon. Siehe Rechnung im Modulkopf:
#: 512 * 0.8 / sqrt(2) = 289.6 - abgerundet auf 288.
MASKABLE_MOTIV = 288

#: (Dateiname, Kantenlaenge, maskable?)
ZIELE = [
    ("icon-192.png", 192, False),
    ("icon-512.png", 512, False),
    ("icon-maskable-512.png", 512, True),
]


def _oeffnen():
    from PIL import Image

    if not os.path.exists(QUELLE):
        raise SystemExit(f"Quelle fehlt: {QUELLE}")

    bild = Image.open(QUELLE).convert("RGBA")
    if bild.size != (1024, 1024):
        print(f"  Hinweis: Quelle ist {bild.size[0]}x{bild.size[1]}, "
              f"erwartet wurden 1024x1024.")
    return bild


def _normal(bild, kante):
    """Schlichte Verkleinerung auf die geforderte Kantenlaenge."""
    from PIL import Image

    return bild.resize((kante, kante), Image.LANCZOS)


def _maskable(bild, kante):
    """Motiv verkleinert und auf gefuellter Flaeche zentriert."""
    from PIL import Image

    flaeche = Image.new("RGBA", (kante, kante), HINTERGRUND)
    motiv_kante = round(MASKABLE_MOTIV * kante / 512)
    motiv = bild.resize((motiv_kante, motiv_kante), Image.LANCZOS)
    versatz = (kante - motiv_kante) // 2
    flaeche.paste(motiv, (versatz, versatz), motiv)
    return flaeche


def main():
    bild = _oeffnen()

    print(f"Quelle: {QUELLE} ({bild.size[0]}x{bild.size[1]}, "
          f"{os.path.getsize(QUELLE) / 1024:.0f} KB)")
    print()

    for name, kante, ist_maskable in ZIELE:
        ziel = os.path.join(ZIEL_VERZEICHNIS, name)
        ergebnis = _maskable(bild, kante) if ist_maskable else _normal(bild, kante)
        # optimize=True schrumpft die Datei ohne Qualitaetsverlust.
        ergebnis.save(ziel, format="PNG", optimize=True)
        art = "maskable" if ist_maskable else "any"
        print(f"  {name:26} {kante}x{kante}  {art:8} "
              f"{os.path.getsize(ziel) / 1024:6.1f} KB")

    print()
    print("Fertig. logofoot.png bleibt unveraendert als Quelle liegen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
