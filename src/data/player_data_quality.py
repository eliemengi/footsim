"""
Wie belastbar ist der Datenstand eines Spielers?

WARUM ES DIESE DATEI GIBT
-------------------------
Am 24.08.2026 zeigte FootSim fuer elf Real-Madrid-Spieler exakt 38
Minuten - fuer die komplette Startelf, den Torwart eingeschlossen. Der
Wert kam so vom Anbieter, auch bei einem frischen Abruf lange nach dem
Spiel. Gleichzeitig lieferte derselbe Anbieter fuer Barcelona ueberhaupt
keine Vereinsdaten.

FootSim konnte beides nicht auseinanderhalten. Es gab genau zwei
Zustaende - Daten da oder nicht da - und darunter verschwanden vier
voellig verschiedene Sachverhalte:

    Der Spieler hat wirklich wenig gespielt.
    Der Anbieter hat den Spielstand noch nicht fertig verbucht.
    Der Anbieter kennt den Verein fuer diese Saison noch gar nicht.
    Der Spieler stand im Kader, kam aber nicht zum Einsatz.

WAS HIER AUSDRUECKLICH NICHT PASSIERT
-------------------------------------
Es wird nichts korrigiert. Liefert der Anbieter 38 Minuten, bleiben es
38 Minuten. FootSim darf niemals behaupten, jemand habe 90 gespielt,
wenn die Quelle 38 sagt - es darf nur dazusagen, dass dieser Stand
moeglicherweise vorlaeufig ist.

Aus demselben Grund ist eine auffaellig gleiche Minutenzahl innerhalb
einer Mannschaft ein WARNSIGNAL und kein Beweis. Sie entsteht auch bei
einem regulaer abgebrochenen Spiel, und dann waeren 38 Minuten die
korrekte Endzahl.
"""

from src.data.competition_taxonomy import is_club_competitive

#: Der Stand ist verwendbar und, soweit erkennbar, endgueltig.
QUALITY_CURRENT = "current_final_or_latest"

#: Es liegen Minuten vor, aber zu wenige fuer eine belastbare Einordnung.
#: WICHTIG: Das heisst NICHT "keine Daten". Der Spieler bleibt sichtbar,
#: vergleichbar und auffindbar - nur die Perzentileinordnung ist duenn.
QUALITY_LOW_SAMPLE = "low_sample"

#: Mehrere Spieler derselben Mannschaft tragen dieselbe ungewoehnliche
#: Minutenzahl. Ein Hinweis, kein Befund - und niemals ein Grund, Daten
#: zu verwerfen.
QUALITY_LIVE_SNAPSHOT = "possible_live_snapshot"

#: Der Anbieter liefert fuer diese Saison keinen Vereinsblock. Der
#: Spieler wird deshalb NICHT versteckt: Er bleibt ueber den Kaderindex
#: auffindbar und zeigt ehrlich, dass noch keine Vereinsdaten vorliegen.
QUALITY_PROVIDER_INCOMPLETE = "provider_incomplete"

#: Vereinsblock vorhanden, aber ohne Einsatz. Das ist eine Aussage, kein
#: Datenmangel.
QUALITY_NO_APPEARANCE = "no_current_appearance"

#: Der Abruf scheiterte, ein aelterer gueltiger Stand wurde weiterverwendet.
QUALITY_STALE_FALLBACK = "stale_fallback"

#: Der Abruf scheiterte und es gab nichts, worauf zurueckzufallen waere.
QUALITY_PROVIDER_ERROR = "provider_error"

#: Alle Zustaende, fuer Pruefungen und Anzeigen.
ALL_QUALITY_STATES = (
    QUALITY_CURRENT,
    QUALITY_LOW_SAMPLE,
    QUALITY_LIVE_SNAPSHOT,
    QUALITY_PROVIDER_INCOMPLETE,
    QUALITY_NO_APPEARANCE,
    QUALITY_STALE_FALLBACK,
    QUALITY_PROVIDER_ERROR,
)

#: Zustaende, bei denen ein Spieler trotzdem sichtbar und vergleichbar
#: bleibt. Das ist die ganze Liste bis auf den harten Abrufausfall -
#: absichtlich, denn Unsichtbarkeit war der urspruengliche Fehler.
VISIBLE_STATES = frozenset(ALL_QUALITY_STATES) - {QUALITY_PROVIDER_ERROR}

#: Ab wann eine Stichprobe fuer Perzentile taugt. Dieselbe Zahl wie
#: DEFAULT_MIN_MINUTES - hier nur zur Beschriftung, NIE zum Ausblenden.
LOW_SAMPLE_MINUTES = 450


def _club_blocks(raw):
    """
    Die Vereinswettbewerbsbloecke einer Rohantwort.

    Geht ueber die zentrale Taxonomie, nicht ueber eigene Namenslisten.
    Damit zaehlen Supercups mit (sie sind Pflichtspiele) und
    Freundschaftsspiele nicht - dieselbe Fachdefinition wie ueberall
    sonst im Projekt.
    """
    bloecke = []
    for block in (raw or {}).get("statistics") or []:
        if is_club_competitive((block or {}).get("league") or {}):
            bloecke.append(block)
    return bloecke


def club_minutes(raw):
    """
    Summe der Vereinsminuten einer Rohantwort.

    None-Minuten zaehlen als 0 - der Anbieter meint damit "nicht
    verbucht", nicht "null gespielt". Der Unterschied wird ueber
    classify_profile_quality() sichtbar, nicht ueber eine erfundene Zahl.
    """
    summe = 0
    for block in _club_blocks(raw):
        spiele = (block or {}).get("games") or {}
        summe += spiele.get("minutes") or 0
    return summe


def club_appearances(raw):
    """Summe der Vereinseinsaetze einer Rohantwort."""
    summe = 0
    for block in _club_blocks(raw):
        spiele = (block or {}).get("games") or {}
        summe += spiele.get("appearences") or 0
    return summe


def classify_profile_quality(raw, min_minutes=LOW_SAMPLE_MINUTES):
    """
    Welcher Qualitaetszustand beschreibt diese Rohantwort?

    Rueckgabe: (zustand, begruendung). Die Begruendung ist fuer Menschen
    gedacht und erscheint im CLI-Bericht.

    Die Reihenfolge der Pruefungen ist die inhaltliche Rangfolge: Erst
    die Frage, ob der Anbieter ueberhaupt etwas ueber den Verein weiss,
    dann ob es Einsaetze gab, dann wie belastbar die Menge ist.
    """
    if not raw:
        return QUALITY_PROVIDER_ERROR, "keine Antwort"

    bloecke = _club_blocks(raw)
    if not bloecke:
        gesamt = len((raw or {}).get("statistics") or [])
        if gesamt:
            return (QUALITY_PROVIDER_INCOMPLETE,
                    f"kein Vereinsblock ({gesamt} Bloecke, alle ausserhalb "
                    f"des Vereinsbereichs)")
        return QUALITY_PROVIDER_INCOMPLETE, "keine Wettbewerbsbloecke"

    einsaetze = club_appearances(raw)
    minuten = club_minutes(raw)

    if not einsaetze and not minuten:
        return QUALITY_NO_APPEARANCE, "im Kader, aber ohne Einsatz"

    if minuten < min_minutes:
        return (QUALITY_LOW_SAMPLE,
                f"{minuten} Vereinsminuten - unter {min_minutes}, "
                f"Einordnung noch duenn")

    return QUALITY_CURRENT, f"{minuten} Vereinsminuten in {len(bloecke)} Wettbewerben"


def detect_uniform_minutes(minuten_je_spieler, min_gruppe=5):
    """
    Tragen auffaellig viele Spieler einer Mannschaft dieselbe Minutenzahl?

    minuten_je_spieler: iterierbar mit Minutenwerten (None erlaubt).

    Rueckgabe: (verdacht, wert, anzahl). verdacht ist True, wenn
    mindestens min_gruppe Spieler exakt denselben Wert ungleich 0 und
    ungleich 90 tragen.

    WAS DAS BEDEUTET UND WAS NICHT
    ------------------------------
    Bei Real Madrid trugen elf Spieler exakt 38 Minuten, der Torwart
    eingeschlossen. Kein Feldspieler kann in einem regulaeren Spiel
    weniger haben als der durchspielende Torwart - das Muster passt zu
    einem Zwischenstand ODER zu einem bei Minute 38 abgebrochenen Spiel.

    Welches von beidem zutrifft, laesst sich aus den Minuten allein NICHT
    entscheiden. Deshalb ist das Ergebnis ein Hinweis, den die Oberflaeche
    anzeigen darf - und niemals ein Grund, Werte zu aendern oder zu
    verwerfen.

    90 ist ausgenommen, weil eine ganze Mannschaft mit 90 Minuten nach
    einem Spieltag voellig normal ist.
    """
    zaehler = {}
    for wert in minuten_je_spieler or []:
        if not wert or wert == 90:
            continue
        zaehler[wert] = zaehler.get(wert, 0) + 1

    if not zaehler:
        return False, None, 0

    wert, anzahl = max(zaehler.items(), key=lambda p: (p[1], p[0]))
    return anzahl >= min_gruppe, wert, anzahl


def quality_block(zustand, begruendung, fetched_at=None, source=None,
                  fixture_status=None, persisted=True):
    """
    Der additive Herkunfts- und Qualitaetsblock fuer Cache- und Pooleintraege.

    Bewusst additiv und ohne Migration: Aeltere Eintraege ohne diesen
    Block bleiben lesbar und melden schlicht nichts. Kein Konsument darf
    sich darauf verlassen, dass er da ist - deshalb liefert
    read_quality() unten einen sicheren Ersatzwert.
    """
    return {
        "cache_quality": zustand,
        "provisional": zustand in (QUALITY_LOW_SAMPLE, QUALITY_LIVE_SNAPSHOT,
                                   QUALITY_PROVIDER_INCOMPLETE,
                                   QUALITY_STALE_FALLBACK),
        "provisional_reason": begruendung,
        "data_as_of": fetched_at,
        "source": source,
        "fixture_status_at_fetch": fixture_status,
        "persisted": persisted,
    }


def read_quality(eintrag):
    """
    Der Qualitaetsblock eines Eintrags - oder ein ehrlicher Ersatzwert.

    Alte Pool- und Cachedateien kennen den Block nicht. Sie duerfen davon
    nicht kaputtgehen und sollen auch nicht faelschlich als geprueft
    gelten. Deshalb "nicht vermerkt" statt eines erfundenen Zustands.
    """
    block = (eintrag or {}).get("data_quality")
    if isinstance(block, dict) and block.get("cache_quality"):
        return block
    return {
        "cache_quality": None,
        "provisional": None,
        "provisional_reason": "nicht vermerkt (Eintrag aus aelterer Fassung)",
        "data_as_of": None,
        "source": None,
        "fixture_status_at_fetch": None,
        "persisted": True,
    }
