"""
Point-in-Time-Lesezugriff auf das Snapshot-Archiv (V2-C6, fuer V2-C7).

WOZU
----
V2-C7 wird fragen: "Welcher Kader war fuer den FC Bayern am 12.
November 2025 bekannt?" Dieses Modul beantwortet genau das - und nichts
darueber hinaus. Es berechnet keine Kaderstaerke, bildet kein Merkmal
und kennt kein Modell. Es liest.

DER VERTRAG
-----------
1. Es wird ausschliesslich ein Snapshot zurueckgegeben, der STRIKT VOR
   dem Cutoff erhoben wurde. Nicht "zum Cutoff", nicht "am selben Tag".
   Ein Stand, der zur selben Sekunde wie der Anpfiff erhoben wurde,
   koennte bereits die Aufstellung enthalten.

   Das ist derselbe Vertrag wie in V2-C1
   (point_in_time.CUTOFF_INCLUSIVE = False), und er gilt hier ohne
   Ausnahme.

2. Fehlt ein Snapshot, kommt ein sichtbarer Fehlzustand zurueck -
   niemals ein leerer Kader und niemals eine Null. Ein leerer Kader
   hiesse "keine Spieler", und ein Modell, das das glaubt, sagt fuer
   diese Partie etwas sehr Falsches voraus.

3. Jede Antwort traegt ihre Herkunft: wann der Stand erhoben wurde, wie
   alt er zum Cutoff war und ob er aus einer Zeit stammt, in der
   ueberhaupt gesammelt wurde.

DAS ALTER IST TEIL DER ANTWORT
------------------------------
Ein Kaderstand von gestern ist etwas anderes als einer von vor drei
Monaten. Beides ist "der letzte bekannte Stand"; nur das zweite ist
mit Vorsicht zu geniessen. age_days steht deshalb in jeder Antwort,
und C7 kann daran entscheiden - statt es selbst auszurechnen und dabei
eine zweite Zeitlogik zu erfinden.
"""

from datetime import datetime, timezone

from src.data import availability_snapshots as av
from src.data import snapshot_archive as archive

#: Warum keine Daten vorliegen. Sichtbar statt stillschweigend leer.
MISSING_NO_HISTORY = "no_snapshot_before_cutoff"
MISSING_UNREADABLE = "snapshot_unreadable"

#: Ab welchem Alter ein Stand als veraltet gilt.
#:
#: Vierzehn Tage sind kein Naturgesetz, sondern eine Lesehilfe: Ein
#: Kader aendert sich zwischen zwei Transferperioden kaum, eine
#: Verletzungslage taeglich. Der Wert steht in der Antwort und
#: entscheidet nichts - C7 setzt seine eigene Grenze, wenn es eine
#: braucht.
STALE_AFTER_DAYS = 14


def _als_utc(zeitpunkt):
    """Ein Zeitpunkt als ISO-Text in UTC - fuer den Textvergleich."""
    if zeitpunkt is None:
        return None
    if isinstance(zeitpunkt, str):
        return zeitpunkt
    if isinstance(zeitpunkt, datetime):
        if zeitpunkt.tzinfo is None:
            zeitpunkt = zeitpunkt.replace(tzinfo=timezone.utc)
        return zeitpunkt.astimezone(timezone.utc).isoformat()
    return str(zeitpunkt)


def _parse(text):
    try:
        wert = datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None
    if wert.tzinfo is None:
        wert = wert.replace(tzinfo=timezone.utc)
    return wert.astimezone(timezone.utc)


def _fehlend(kind, key, cutoff, grund):
    return {
        "available": False,
        "missing_reason": grund,
        "kind": kind,
        "key": key,
        "cutoff": _als_utc(cutoff),
        "captured_at": None,
        "age_days": None,
        "is_stale": None,
        "payload": None,
        "provenance": None,
    }


def snapshot_before(kind, key, cutoff, archive_module=None):
    """
    Der juengste Snapshot STRIKT VOR dem Cutoff - oder ein Fehlzustand.

    Rueckgabe: dict mit available, payload, provenance, age_days.

    GLEICHER ZEITSTEMPEL
    Ein Snapshot mit captured_at == cutoff wird NICHT geliefert. Die
    Regel ist streng und absichtlich: Sie kostet im schlimmsten Fall
    einen Stand, verhindert aber, dass ein zur Anpfiffsekunde erhobener
    Kader in die Vorhersage derselben Partie geraet.

    MEHRERE SNAPSHOTS ZUM SELBEN ZEITPUNKT
    Es gewinnt der zuletzt geschriebene (hoechster Zaehlersuffix im
    Dateinamen) - festgelegt in
    snapshot_archive.latest_snapshot_before und dort getestet.
    """
    archive_module = archive_module or archive
    cutoff_text = _als_utc(cutoff)

    eintrag = archive_module.latest_snapshot_before(kind, cutoff_text, key=key)
    if eintrag is None:
        return _fehlend(kind, key, cutoff, MISSING_NO_HISTORY)

    meta = eintrag.get("meta") or {}
    payload = eintrag.get("payload")
    if payload is None:
        return _fehlend(kind, key, cutoff, MISSING_UNREADABLE)

    erhoben = _parse(meta.get("captured_at"))
    grenze = _parse(cutoff_text)
    alter = None
    if erhoben is not None and grenze is not None:
        alter = round((grenze - erhoben).total_seconds() / 86400.0, 3)

    return {
        "available": True,
        "missing_reason": None,
        "kind": kind,
        "key": key,
        "cutoff": cutoff_text,
        "captured_at": meta.get("captured_at"),
        "age_days": alter,
        "is_stale": (None if alter is None else alter > STALE_AFTER_DAYS),
        "payload": payload,
        "provenance": {
            "source": meta.get("source"),
            "endpoint": meta.get("endpoint"),
            "request_scope": meta.get("request_scope"),
            "snapshot_schema_version": meta.get("snapshot_schema_version"),
            "collector_version": meta.get("collector_version"),
            "content_fingerprint": meta.get("content_fingerprint"),
            "fetched_at": meta.get("fetched_at"),
            "fetched_at_meaning": meta.get("fetched_at_meaning"),
            "quality_notes": meta.get("quality_notes"),
        },
    }


def squad_before(team_id, cutoff, archive_module=None):
    """Der letzte bekannte Kader einer Mannschaft vor dem Cutoff."""
    return snapshot_before(av.KIND_SQUAD, av.squad_key(team_id), cutoff,
                           archive_module=archive_module)


def availability_before(league_id, season, cutoff, archive_module=None):
    """
    Die letzte bekannte Ausfallliste einer Liga-Saison vor dem Cutoff.

    ACHTUNG - ZWEI ZEITEBENEN
    Der Snapshot als Ganzes ist vor dem Cutoff ERHOBEN worden. Seine
    EINTRAEGE tragen aber eigene Gueltigkeitszeitpunkte (die Partie,
    bei der ein Spieler fehlte), und die koennen NACH dem Cutoff
    liegen: Eine am 1. November abgerufene Liste enthaelt auch die
    Partie vom 8. November, wenn der Anbieter sie schon fuehrt.

    Wer nur die zum Cutoff gueltigen Eintraege will, nimmt
    availability_entries_before() - diese Funktion liefert den
    Snapshot unveraendert.
    """
    return snapshot_before(av.KIND_AVAILABILITY,
                           av.availability_key(league_id, season), cutoff,
                           archive_module=archive_module)


def availability_entries_before(league_id, season, cutoff,
                                archive_module=None, team_id=None):
    """
    Die Ausfalleintraege, die zum Cutoff bereits GALTEN.

    Zwei Filter, beide noetig:

      1. Der Snapshot muss vor dem Cutoff erhoben worden sein.
      2. Der EINTRAG muss einen Gueltigkeitszeitpunkt vor dem Cutoff
         tragen.

    Der zweite ist der leicht zu vergessende. Ein Eintrag "Spieler P
    fehlt bei Partie F am 8. November" steht schon am 1. November in
    der Liste - er beschreibt aber ein Ereignis, das zum Cutoff des 1.
    November noch nicht eingetreten war. Ihn mitzuzaehlen hiesse, die
    Zukunft zu kennen.

    Eintraege OHNE Gueltigkeitszeitpunkt werden getrennt gezaehlt und
    nicht mitgeliefert: Ob sie galten, ist unbekannt, und unbekannt ist
    nicht dasselbe wie wahr.
    """
    stand = availability_before(league_id, season, cutoff,
                               archive_module=archive_module)
    if not stand["available"]:
        return dict(stand, entries=None, entries_total=0,
                    entries_effective_before_cutoff=0,
                    entries_after_cutoff=0, entries_without_effective_at=0)

    cutoff_text = _als_utc(cutoff)
    grenze = _parse(cutoff_text)

    passend, spaeter, ohne_zeit = [], 0, 0
    for eintrag in (stand["payload"].get("entries") or []):
        if team_id is not None and eintrag.get("team_id") != int(team_id):
            continue
        wirksam = _parse(eintrag.get("effective_at"))
        if wirksam is None:
            ohne_zeit += 1
            continue
        if grenze is not None and wirksam < grenze:
            passend.append(eintrag)
        else:
            spaeter += 1

    return dict(stand,
                entries=passend,
                entries_total=len(stand["payload"].get("entries") or []),
                entries_effective_before_cutoff=len(passend),
                entries_after_cutoff=spaeter,
                entries_without_effective_at=ohne_zeit)


def archive_window(kind):
    """
    Ab wann existiert fuer diese Art ueberhaupt Historie?

    Die Frage entscheidet, ab welchem Datum ein Backtest diese Daten
    benutzen DARF. Vor dem ersten Snapshot gibt es keine - und sie
    laesst sich rueckwirkend nicht beschaffen.
    """
    deckung = archive.archive_coverage(kind)
    return {
        "kind": kind,
        "snapshots": deckung["snapshots"],
        "keys": deckung["keys"],
        "earliest": deckung["earliest"],
        "latest": deckung["latest"],
        "usable_from": deckung["earliest"],
        "note": ("Vor 'usable_from' liegt keine gesammelte Historie vor. "
                 "Diese Luecke ist nicht nachtraeglich zu schliessen - der "
                 "Anbieter liefert Kader und Ausfaelle als aktuellen Stand, "
                 "nicht als Zeitreihe."),
    }
