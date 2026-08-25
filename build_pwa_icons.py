"""
Erzeugt die PWA-/Android-Icons aus der transparenten Logoquelle.

AUFRUF
------
    py build_pwa_icons.py

WAS VORHER FALSCH WAR
---------------------
Die erste Fassung baute die Icons aus static/images/logofoot.png. Diese
Datei ist vollflaechig OPAK - nachgemessen: Alpha durchgehend 255, die
Alpha-Bounding-Box umfasst das ganze Bild, die Ecken tragen ein fast
schwarzes (1, 0, 1). Das Logo bringt also seine eigene dunkle Kachel mit.

Daraus entstanden zwei sichtbare Fehler:

  Doppelter Rahmen   Das maskable Icon legte eine zweite Flaeche in
                     #0D1B30 hinter eine Grafik, die bereits eine hatte.
                     Auf dem Launcher lagen zwei Quadrate uebereinander.

  Schwarzes Quadrat  Beim Start blitzte die eingebackene Kachel auf -
                     ein dunkles Rechteck vor dem eigentlichen Motiv.

WAS JETZT ANDERS IST
--------------------
Quelle ist logofoot-app-v2.png: 1254x1254, echtes RGBA, Alpha von 0 bis
255, alle vier Ecken vollstaendig transparent. Das Motiv steht frei.

  Normale Icons   behalten einen TRANSPARENTEN Hintergrund. Wer eine
                  Flaeche will, setzt sie selbst - Chrome, der Launcher
                  oder das Manifest. Genau eine Instanz entscheidet
                  ueber den Hintergrund, nicht zwei.

  Maskable        bekommt als einziges eine vollflaechige #0D1B30, weil
                  Android hier zuschneidet und ein transparenter Rand
                  sonst als Loch erschiene.

Das Motiv wird in beiden Faellen ueber seine Alpha-Bounding-Box
freigestellt und proportional zentriert. Es wird nie verzerrt und nie
beschnitten.

DIE SAFE-ZONE-RECHNUNG
----------------------
Android schneidet adaptive Icons je nach Hersteller kreisrund, als
Squircle oder abgerundet zu. Garantiert sichtbar bleibt nur ein Kreis
mit 80 Prozent des Bilddurchmessers.

    Sicherer Durchmesser bei 512 px:  0.8 * 512 = 409.6 px

Das Motiv ist NICHT quadratisch (1141x1035, siehe SICHTBAR_AB).
Entscheidend ist deshalb seine Diagonale: Passt sie in den Kreis, liegen
auch die vier Ecken der Bounding-Box darin, und nichts kann
abgeschnitten werden.

    skaliert so, dass  sqrt(breite^2 + hoehe^2) <= 409.6

Bei diesem Seitenverhaeltnis ergibt das 303x275 px. Auf einem runden
Launcher fuellt das Motiv damit rund drei Viertel der sichtbaren
Kreisbreite - der Anteil, den Androids Gestaltungsrichtlinie fuer das
Motiv eines adaptiven Icons vorsieht.

WAS HIER NICHT PASSIERT
-----------------------
Keine neue Bildgestaltung, kein anderes Logo, keine Farbaenderung am
Motiv. Es wird ausschliesslich freigestellt, skaliert und zentriert.

logofoot.png bleibt unangetastet - es gehoert weiterhin zur Website und
wird fuer die Android-Icons nicht mehr verwendet. Die alten
icon-*.png-Dateien werden nicht geloescht; die neuen tragen das Suffix
-v2 und stehen daneben.
"""

import math
import os
import sys

QUELLE = os.path.join("static", "images", "logofoot-app-v2.png")
ZIEL_VERZEICHNIS = os.path.join("static", "images")

#: Hintergrundfarbe des Manifests (background_color / theme_color).
#: Ausschliesslich fuer das maskable Icon - siehe Modulkopf.
HINTERGRUND = (0x0D, 0x1B, 0x30, 255)

#: Anteil des Bilddurchmessers, der bei jeder Maskenform sichtbar bleibt.
SAFE_ZONE_ANTEIL = 0.8

#: Ab welcher Deckkraft ein Pixel zum SICHTBAREN Motiv zaehlt.
#:
#: Die Quelle traegt einen weichen Schein um das Logo: 91.975 Pixel mit
#: Alpha 1 bis 7, also 0,4 bis 2,7 Prozent Deckkraft. Mit blossem Auge
#: ist davon nichts zu sehen, fuer Image.getbbox() zaehlt es trotzdem.
#:
#: Der Unterschied ist erheblich und asymmetrisch:
#:
#:     Alpha > 0   ->  (21, 33, 1214, 1246)   1193 x 1213
#:     Alpha >= 8  ->  (48, 96, 1189, 1131)   1141 x 1035
#:
#: Ueber die groessere Box gerechnet, geriete das Logo zu klein und
#: vertikal versetzt - unten laege es fast am Rand, oben bliebe eine
#: Luecke. Deshalb bestimmt die Schwelle die Box.
#:
#: Der Wert 8 ist nicht geraten: Zwischen Schwelle 8 und Schwelle 128
#: wandert die Box um hoechstens einen Pixel. Dort liegt also die
#: tatsaechliche Kante des Motivs, nicht irgendwo im Schein.
SICHTBAR_AB = 8

#: (Dateiname, Kantenlaenge, maskable?)
ZIELE = [
    ("icon-192-v2.png", 192, False),
    ("icon-512-v2.png", 512, False),
    ("icon-maskable-512-v2.png", 512, True),
]


def _quelle_laden():
    """
    Laedt die Quelle und besteht auf echter Transparenz.

    Ohne diese Pruefung wuerde ein versehentlich flachgerechnetes PNG
    genau den Fehler zurueckbringen, den diese Fassung behebt - und zwar
    unbemerkt, weil das Ergebnis auf den ersten Blick brauchbar aussieht.
    """
    from PIL import Image

    if not os.path.exists(QUELLE):
        raise SystemExit(f"ABBRUCH: Quelle fehlt: {QUELLE}")

    bild = Image.open(QUELLE).convert("RGBA")
    alpha_min, alpha_max = bild.getchannel("A").getextrema()

    if alpha_min != 0:
        raise SystemExit(
            f"ABBRUCH: {QUELLE} hat KEINE Transparenz "
            f"(Alpha min/max = {alpha_min}/{alpha_max}).\n"
            f"        Eine opake Quelle bringt ihre eigene Kachel mit - genau "
            f"das war der doppelte Hintergrund.\n"
            f"        Ein PNG mit echtem Alphakanal exportieren und erneut "
            f"versuchen."
        )

    bbox = sichtbare_bbox(bild)
    if bbox is None:
        raise SystemExit(f"ABBRUCH: {QUELLE} ist vollstaendig transparent.")

    return bild, bbox


def sichtbare_bbox(bild, schwelle=SICHTBAR_AB):
    """
    Die Bounding-Box des SICHTBAREN Motivs.

    Nicht Image.getbbox(): Das zaehlt jeden Pixel mit Alpha >= 1 und
    nimmt damit den unsichtbaren Schein rings um das Logo mit. Siehe die
    Begruendung bei SICHTBAR_AB.
    """
    maske = bild.getchannel("A").point(
        lambda wert: 255 if wert >= schwelle else 0)
    return maske.getbbox()


def _freistellen(bild, bbox):
    """Das sichtbare Motiv ohne den transparenten Rand der Quelle."""
    return bild.crop(bbox)


def _proportional(motiv, ziel_breite, ziel_hoehe):
    """
    Skaliert das Motiv so gross wie moeglich in den erlaubten Rahmen.

    Der kleinere der beiden Faktoren gewinnt - damit bleibt das
    Seitenverhaeltnis erhalten und nichts ragt heraus.
    """
    from PIL import Image

    faktor = min(ziel_breite / motiv.width, ziel_hoehe / motiv.height)
    breite = max(1, round(motiv.width * faktor))
    hoehe = max(1, round(motiv.height * faktor))
    return motiv.resize((breite, hoehe), Image.LANCZOS)


def _zentrieren(motiv, flaeche):
    """Setzt das Motiv mittig auf die Flaeche, alphabewusst."""
    versatz = ((flaeche.width - motiv.width) // 2,
               (flaeche.height - motiv.height) // 2)
    flaeche.alpha_composite(motiv, versatz)
    return flaeche


def _normal(motiv, kante):
    """
    Normales Icon: freigestelltes Motiv auf transparentem Grund.

    Kein Hintergrund - das ist der Kern der Korrektur. Die Flaeche
    bestimmt der Anzeigekontext, nicht die Datei.
    """
    from PIL import Image

    flaeche = Image.new("RGBA", (kante, kante), (0, 0, 0, 0))
    return _zentrieren(_proportional(motiv, kante, kante), flaeche)


def _maskable(motiv, kante):
    """
    Maskable Icon: Motiv in der Safe Zone, vollflaechiger Hintergrund.

    Die Diagonale des Motivs muss in den sicheren Kreis passen - siehe
    die Rechnung im Modulkopf. Aus der erlaubten Diagonale ergibt sich
    ueber das Seitenverhaeltnis die zulaessige Breite und Hoehe.
    """
    from PIL import Image

    sichere_diagonale = kante * SAFE_ZONE_ANTEIL
    eigene_diagonale = math.hypot(motiv.width, motiv.height)
    faktor = sichere_diagonale / eigene_diagonale

    erlaubte_breite = motiv.width * faktor
    erlaubte_hoehe = motiv.height * faktor

    flaeche = Image.new("RGBA", (kante, kante), HINTERGRUND)
    return _zentrieren(
        _proportional(motiv, erlaubte_breite, erlaubte_hoehe), flaeche)


def main():
    bild, bbox = _quelle_laden()
    motiv = _freistellen(bild, bbox)

    print(f"Quelle: {QUELLE}")
    print(f"  Bild            {bild.width}x{bild.height}, "
          f"{os.path.getsize(QUELLE) / 1024:.0f} KB")
    print(f"  Alpha min/max   {bild.getchannel('A').getextrema()}")
    print(f"  Alpha-BBox      {bbox}")
    print(f"  Motiv           {motiv.width}x{motiv.height}")
    print()

    for name, kante, ist_maskable in ZIELE:
        ziel = os.path.join(ZIEL_VERZEICHNIS, name)
        ergebnis = (_maskable(motiv, kante) if ist_maskable
                    else _normal(motiv, kante))
        ergebnis.save(ziel, format="PNG", optimize=True)

        gezeichnet = sichtbare_bbox(ergebnis)
        breite = gezeichnet[2] - gezeichnet[0]
        hoehe = gezeichnet[3] - gezeichnet[1]
        art = "maskable" if ist_maskable else "any"
        zusatz = ""
        if ist_maskable:
            # Beim maskable Icon ist die gesamte Flaeche undurchsichtig,
            # deshalb sagt getbbox() dort nichts ueber das Motiv aus.
            diagonale = math.hypot(*_maskable_motivmass(motiv, kante))
            zusatz = (f"  Motiv {_maskable_motivmass(motiv, kante)[0]}x"
                      f"{_maskable_motivmass(motiv, kante)[1]}, "
                      f"Diagonale {diagonale:.0f} <= {kante * SAFE_ZONE_ANTEIL:.0f}")
        else:
            zusatz = f"  gezeichnet {breite}x{hoehe}"

        print(f"  {name:28} {kante}x{kante}  {art:8} "
              f"{os.path.getsize(ziel) / 1024:6.1f} KB{zusatz}")

    print()
    print("Fertig. logofoot.png und die alten icon-*.png bleiben unveraendert.")
    return 0


def _maskable_motivmass(motiv, kante):
    """Die tatsaechliche Motivgroesse im maskable Icon - fuer den Bericht."""
    faktor = (kante * SAFE_ZONE_ANTEIL) / math.hypot(motiv.width, motiv.height)
    skaliert = _proportional(motiv, motiv.width * faktor, motiv.height * faktor)
    return skaliert.width, skaliert.height


if __name__ == "__main__":
    sys.exit(main())
