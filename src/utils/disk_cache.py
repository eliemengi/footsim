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


def write_entry(key, payload, ttl_seconds, source="unknown", extra_meta=None):
    """Schreibt einen Eintrag mit Metadaten auf die Platte."""
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

    with _lock:
        _write_atomic(_path_for(key), entry)

    return entry


def disk_cached_call(key, ttl_seconds, loader, source="unknown", extra_meta=None):
    """
    Gibt den gecachten Wert zurueck oder ruft loader auf und speichert ihn.

    Verhalten bei Fehlern im loader: Liegt ein abgelaufener Eintrag vor,
    wird dieser zurueckgegeben statt die Anwendung scheitern zu lassen.
    Lieber leicht veraltete Daten als eine kaputte Seite. Genau dieses
    Verhalten kennt der In-Memory-Cache auch.
    """
    entry = read_entry(key)

    if is_fresh(entry):
        return entry["payload"]

    try:
        payload = loader()
    except Exception:
        if entry is not None:
            # Notfall: abgelaufene Daten weiterverwenden.
            return entry["payload"]
        raise

    write_entry(key, payload, ttl_seconds, source=source, extra_meta=extra_meta)
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
