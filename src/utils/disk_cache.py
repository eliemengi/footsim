"""
Persistenter Cache auf der Festplatte.

Warum zusaetzlich zum bestehenden In-Memory-Cache (src/utils/cache.py)?

Der In-Memory-Cache lebt im Prozess. Er ist nach jedem
`systemctl restart footsim` leer, und unter Gunicorn hat jeder Worker
seinen eigenen. Fuer kleine, haeufig wechselnde Daten (Tabellen,
Spielplaene) ist das genau richtig.

Fuer grosse, selten wechselnde Daten ist es das Gegenteil von richtig:
Eine abgeschlossene Vorsaison mit 306 Spielen aendert sich nie mehr.
Die bei jedem Neustart erneut zu laden wuerde das Minutenlimit von
football-data.org (10 Requests/Minute) sofort sprengen.

Dieser Cache legt solche Daten als JSON unter data/cache/ ab. Jeder
Eintrag traegt Metadaten mit, damit spaeter nachvollziehbar ist, woher
er stammt und wann er geholt wurde:

    {
      "meta": {
        "key": "historical:BL1:2024",
        "fetched_at": "2026-07-28T10:15:00+00:00",
        "expires_at": "2026-08-11T10:15:00+00:00",
        "source": "football-data.org",
        "payload_version": 1
      },
      "payload": { ... }
    }

Verwendung:

    from src.utils.disk_cache import disk_cached_call
    from src.utils.cache import TTL_HISTORICAL_SEASON

    daten = disk_cached_call(
        key="historical:BL1:2024",
        ttl_seconds=TTL_HISTORICAL_SEASON,
        loader=lambda: hole_saison_von_der_api(),
        source="football-data.org",
    )

Der loader wird nur aufgerufen, wenn nichts Gueltiges auf der Platte liegt.
"""

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timedelta, timezone


# Basisverzeichnis fuer alle Cache-Dateien. Liegt bewusst unter data/,
# damit es zusammen mit den uebrigen Projektdaten versioniert werden kann.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_DIR = os.path.join(_PROJECT_ROOT, "data", "cache")

# Schuetzt Schreibvorgaenge, weil Gunicorn mit mehreren Threads arbeitet.
_lock = threading.Lock()

# Wird in die Metadaten geschrieben. Erhoehen, wenn sich das Format der
# gespeicherten Nutzdaten aendert. Alte Eintraege gelten dann als ungueltig
# und werden neu geladen, statt stillschweigend falsch interpretiert.
PAYLOAD_VERSION = 1


def _utc_now():
    return datetime.now(timezone.utc)


def _safe_filename(key):
    """
    Wandelt einen Cache-Key in einen sicheren Dateinamen.

    'historical:BL1:2024' wird zu 'historical__BL1__2024.json'.
    Alles, was kein Buchstabe, Ziffer, Punkt, Minus oder Unterstrich ist,
    wird ersetzt. Das verhindert, dass ein Key mit '/' oder '..' aus dem
    Cache-Verzeichnis ausbricht.
    """
    cleaned = key.replace(":", "__")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", cleaned)
    return f"{cleaned}.json"


def _path_for(key):
    return os.path.join(CACHE_DIR, _safe_filename(key))


def _ensure_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def _write_atomic(path, data):
    """
    Schreibt JSON atomar: erst in eine temporaere Datei, dann umbenennen.

    Ohne das koennte ein Absturz mitten im Schreiben eine halb geschriebene
    JSON-Datei hinterlassen, die beim naechsten Lesen einen Parser-Fehler
    ausloest. os.replace ist auf einem Dateisystem atomar.
    """
    _ensure_dir()
    fd, tmp_path = tempfile.mkstemp(dir=CACHE_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp_path, path)
    except Exception:
        # Temporaere Datei nicht liegen lassen.
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def read_entry(key):
    """
    Liest einen Eintrag roh von der Platte, ohne Ablauf zu pruefen.

    Rueckgabe: das komplette Dict mit 'meta' und 'payload', oder None,
    wenn die Datei fehlt oder unlesbar ist.
    """
    path = _path_for(key)
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as handle:
            entry = json.load(handle)
    except (json.JSONDecodeError, OSError):
        # Kaputte Datei behandeln wir wie 'nicht vorhanden'.
        return None

    if not isinstance(entry, dict) or "payload" not in entry:
        return None

    return entry


def is_fresh(entry):
    """Prueft, ob ein gelesener Eintrag noch gueltig ist."""
    if not entry:
        return False

    meta = entry.get("meta") or {}

    # Formatwechsel macht alte Eintraege ungueltig.
    if meta.get("payload_version") != PAYLOAD_VERSION:
        return False

    expires_at = meta.get("expires_at")
    if not expires_at:
        return False

    try:
        expiry = datetime.fromisoformat(expires_at)
    except ValueError:
        return False

    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)

    return _utc_now() < expiry


#: Ist das Schreiben in diesem Lauf gesperrt?
#:
#: Gesetzt ausschliesslich ueber no_persist(). Gedacht fuer den
#: Diagnosemodus --dry-run: Er DARF den Anbieter fragen, aber er darf das
#: Ergebnis unter keinen Umstaenden festschreiben.
#:
#: Warum die Sperre hier unten sitzt und nicht beim Aufrufer: Ein
#: Diagnoselauf beruehrt mehrere Ebenen (Profil, Kaderindex, Fixtures),
#: und jede davon schreibt ueber genau diese eine Funktion. Eine Sperre
#: an der schmalsten Stelle ist beweisbar; ein Dutzend if-Abfragen bei den
#: Aufrufern waere es nicht - man muesste jede einzeln pruefen und koennte
#: eine vergessen.
_NO_PERSIST = False


def no_persist():
    """
    Sperrt jedes Schreiben in den Plattencache fuer die Dauer des Blocks.

    Verwendung:

        with disk_cache.no_persist():
            ...   # holt frisch, schreibt aber nichts

    Verschachtelung ist erlaubt; die Sperre wird am Ende auf den vorherigen
    Zustand zurueckgesetzt, auch wenn im Block eine Ausnahme auftritt.
    """
    import contextlib

    @contextlib.contextmanager
    def _sperre():
        global _NO_PERSIST
        vorher = _NO_PERSIST
        _NO_PERSIST = True
        try:
            yield
        finally:
            _NO_PERSIST = vorher

    return _sperre()


def is_persisting():
    """Darf gerade geschrieben werden?"""
    return not _NO_PERSIST


def write_entry(key, payload, ttl_seconds, source="unknown", extra_meta=None):
    """
    Schreibt einen Eintrag mit Metadaten auf die Platte.

    Unter no_persist() wird die Huelle gebaut und zurueckgegeben, aber
    NICHT geschrieben. Der Aufrufer bekommt dadurch dieselbe Struktur wie
    sonst und muss keinen Sonderfall kennen.
    """
    now = _utc_now()

    meta = {
        "key": key,
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=ttl_seconds)).isoformat(),
        "source": source,
        "payload_version": PAYLOAD_VERSION,
    }
    if extra_meta:
        meta.update(extra_meta)

    entry = {"meta": meta, "payload": payload}

    if _NO_PERSIST:
        entry["meta"]["persisted"] = False
        return entry

    with _lock:
        _write_atomic(_path_for(key), entry)

    return entry


#: Schluesselpraefixe, deren Cache in DIESEM Lauf uebergangen wird.
#:
#: Wird ausschliesslich von refresh_players.py mit --refetch-players
#: gesetzt und gilt nur fuer den laufenden Prozess. Kein Dauerzustand,
#: keine Datei wird geloescht - der alte Eintrag wird lediglich nicht
#: gelesen und anschliessend ueberschrieben.
#:
#: Warum es das braucht: --force laedt die Ligaseiten neu, aber der
#: Spielerdetailabruf laeuft ueber diesen Cache mit 24 Stunden Lebensdauer.
#: Ein Zwischenstand, der waehrend eines laufenden Spiels erfasst wurde
#: ("38 Minuten"), blieb dadurch auch nach --force bis zu einem Tag
#: stehen. Ohne diesen Schalter gab es keine Moeglichkeit, ihn gezielt zu
#: korrigieren, ausser den Cache zu loeschen - und das haette die
#: gespeicherten Anbieterantworten vernichtet, die als Beleg dienen.
_BYPASS_PREFIXES = set()


def bypass_prefixes(*prefixes):
    """
    Aktiviert das Umgehen des Caches fuer bestimmte Schluesselpraefixe.

    Wirkt nur im laufenden Prozess. Ein leerer Aufruf setzt zurueck.
    """
    _BYPASS_PREFIXES.clear()
    _BYPASS_PREFIXES.update(p for p in prefixes if p)
    return sorted(_BYPASS_PREFIXES)


def is_bypassed(key):
    """Soll dieser Schluessel in diesem Lauf frisch geholt werden?"""
    return any(str(key).startswith(prefix) for prefix in _BYPASS_PREFIXES)


def current_bypass_prefixes():
    """Die aktuell gesetzten Umgehungspraefixe."""
    return sorted(_BYPASS_PREFIXES)


def bypass(*prefixes):
    """
    Umgehung nur fuer die Dauer des Blocks, danach wieder wie vorher.

        with disk_cache.bypass("apisports:playerprofile:278:2026"):
            ...

    Der gezielte Einzelspielerrefresh braucht genau das: Er soll EIN
    Profil neu holen und nicht versehentlich den Rest des Laufs
    beeinflussen. bypass_prefixes() allein kann das nicht - es setzt die
    Menge global und kennt keinen Rueckweg.

    Ein vollstaendiger Schluessel ist dabei sein eigener Praefix, und ein
    Schluessel endet auf die Saison. "…:27:2026" trifft deshalb NICHT
    auch "…:278:2026" - die Abgrenzung ist eindeutig.
    """
    import contextlib

    @contextlib.contextmanager
    def _umgehung():
        vorher = set(_BYPASS_PREFIXES)
        _BYPASS_PREFIXES.clear()
        _BYPASS_PREFIXES.update(p for p in prefixes if p)
        try:
            yield sorted(_BYPASS_PREFIXES)
        finally:
            _BYPASS_PREFIXES.clear()
            _BYPASS_PREFIXES.update(vorher)

    return _umgehung()


def disk_cached_call(key, ttl_seconds, loader, source="unknown", extra_meta=None,
                     empty_ttl_seconds=None):
    """
    Gibt den gecachten Wert zurueck oder ruft loader auf und speichert ihn.

    Verhalten bei Fehlern im loader: Liegt ein abgelaufener Eintrag vor,
    wird dieser zurueckgegeben statt die Anwendung scheitern zu lassen.
    Lieber leicht veraltete Daten als eine kaputte Seite. Genau dieses
    Verhalten kennt der In-Memory-Cache auch.

    empty_ttl_seconds ist fuer den Umstieg von In-Memory auf Platte
    wichtig: Ein leeres Ergebnis bedeutet in der Regel "Saison hat noch
    nicht begonnen" oder "Quelle war gerade nicht erreichbar". Im
    fluechtigen Speicher war das harmlos, weil es den Neustart nicht
    ueberlebte. Auf der Platte wuerde es sonst mit voller TTL festgehalten
    und der Wettbewerb bliebe kuenstlich lange leer. Ist der Wert gesetzt,
    bekommen leere Ergebnisse diese kuerzere Lebensdauer.
    """
    entry = read_entry(key)

    # Umgehung nur, wenn ausdruecklich angefordert (siehe bypass_prefixes).
    # Der bestehende Eintrag bleibt als Notfallrueckfall erhalten - er wird
    # nur nicht als frisch akzeptiert.
    if is_fresh(entry) and not is_bypassed(key):
        return entry["payload"]

    try:
        payload = loader()
    except Exception:
        if entry is not None:
            # Notfall: abgelaufene Daten weiterverwenden.
            return entry["payload"]
        raise

    effective_ttl = ttl_seconds
    if empty_ttl_seconds is not None and not payload:
        effective_ttl = empty_ttl_seconds

    write_entry(key, payload, effective_ttl, source=source, extra_meta=extra_meta)
    return payload


def get_meta(key):
    """Nur die Metadaten eines Eintrags, fuer Diagnose-Ausgaben."""
    entry = read_entry(key)
    return (entry or {}).get("meta")


def invalidate(key):
    """Loescht einen einzelnen Eintrag."""
    path = _path_for(key)
    with _lock:
        if os.path.exists(path):
            try:
                os.remove(path)
                return True
            except OSError:
                return False
    return False


def list_entries():
    """
    Listet alle Cache-Eintraege mit Metadaten und Frische-Status.

    Nuetzlich fuer den Diagnose-Report: zeigt auf einen Blick, welche
    Daten lokal liegen und welche abgelaufen sind.
    """
    if not os.path.isdir(CACHE_DIR):
        return []

    entries = []
    for filename in sorted(os.listdir(CACHE_DIR)):
        if not filename.endswith(".json"):
            continue

        path = os.path.join(CACHE_DIR, filename)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (json.JSONDecodeError, OSError):
            entries.append({"file": filename, "readable": False})
            continue

        meta = raw.get("meta") or {}
        entries.append({
            "file": filename,
            "readable": True,
            "key": meta.get("key"),
            "source": meta.get("source"),
            "fetched_at": meta.get("fetched_at"),
            "expires_at": meta.get("expires_at"),
            "fresh": is_fresh(raw),
            "size_kb": round(os.path.getsize(path) / 1024, 1),
        })

    return entries
