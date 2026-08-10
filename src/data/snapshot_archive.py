"""
Zeitgestempeltes Archiv fuer modellrelevante Momentaufnahmen.

Das Problem
-----------
Alle bisherigen Persistenzschichten arbeiten nach dem Prinzip
"letzter Schreiber gewinnt": Perzentile werden neu berechnet und
ueberschreiben die alte Datei, Kaderdaten laufen ueber einen Cache mit
Ablaufzeit. Fuer den Livebetrieb ist das genau richtig - niemand will
veraltete Perzentile sehen.

Fuer spaeteres Training ist es fatal. Die Frage "welche Spieler fehlten
dem FC Bayern am 12. November 2025?" laesst sich aus einem
ueberschriebenen Stand nicht mehr beantworten. Und anders als
Spielergebnisse laesst sich dieser Zustand auch NICHT nachtraeglich von
der API holen: Beide Anbieter liefern Verletzungen als Momentaufnahme,
nicht als Historie.

Was hier NICHT passiert
-----------------------
Es wird nichts rekonstruiert. Kaderstaende, die wir heute nicht besitzen,
bleiben unbekannt - sie zu schaetzen waere erfundene Historie und im
Training schlimmer als eine Luecke, weil das Modell den erfundenen Werten
vertrauen wuerde.

Ab jetzt wird sauber gesammelt. Das ist der einzige Weg, in einem Jahr
eine echte Verfuegbarkeitshistorie zu haben.

Aufbau
------
    data/snapshots/<art>/<art>__<schluessel>__<zeitstempel>.json

Der "latest"-Zugriff bleibt dort, wo er heute liegt (z. B.
data/percentiles/percentiles_2025.json). Dieses Modul ergaenzt nur die
unveraenderliche Kopie daneben - bestehende Leser merken davon nichts.
"""

import json
import os
import re
import tempfile
from datetime import datetime, timezone


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ARCHIVE_DIR = os.path.join(_PROJECT_ROOT, "data", "snapshots")

# Formatkennung der abgelegten Huelle. Erhoehen, wenn sich die Struktur
# der Metadaten aendert, damit spaetere Leser alte Dateien erkennen.
ARCHIVE_VERSION = 1


def _utc_now():
    return datetime.now(timezone.utc)


def _safe(text):
    """Macht aus einem Schluessel einen sicheren Dateinamensteil."""
    cleaned = str(text).replace(":", "_")
    return re.sub(r"[^A-Za-z0-9._-]", "_", cleaned)


def _timestamp_for_filename(moment):
    # Doppelpunkte sind unter Windows in Dateinamen nicht erlaubt.
    return moment.strftime("%Y%m%dT%H%M%SZ")


def archive_dir_for(kind):
    return os.path.join(ARCHIVE_DIR, _safe(kind))


def _write_atomic(path, data):
    """
    Schreibt JSON atomar, damit ein parallel lesender Gunicorn-Worker nie
    eine halb geschriebene Datei sieht.
    """
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def archive_snapshot(kind, key, payload, source=None, extra_meta=None,
                     captured_at=None):
    """
    Legt eine unveraenderliche Kopie ab.

    kind:    Art der Momentaufnahme, z. B. "percentiles" oder "squad"
    key:     fachlicher Schluessel, z. B. "2025" oder "bl1_2025"
    payload: die zu sichernden Daten
    source:  woher die Daten stammen (Provider oder Modul)

    Rueckgabe: Pfad der geschriebenen Datei.

    Bereits vorhandene Archivdateien werden NIE ueberschrieben - genau
    das ist der Zweck. Faellt ein Aufruf zufaellig in dieselbe Sekunde
    wie ein frueherer, bekommt er einen Zaehlersuffix.
    """
    moment = captured_at or _utc_now()
    stamp = _timestamp_for_filename(moment)
    directory = archive_dir_for(kind)

    base = f"{_safe(kind)}__{_safe(key)}__{stamp}"
    path = os.path.join(directory, f"{base}.json")

    counter = 1
    while os.path.exists(path):
        path = os.path.join(directory, f"{base}_{counter}.json")
        counter += 1

    entry = {
        "meta": {
            "kind": kind,
            "key": str(key),
            "captured_at": moment.isoformat(),
            "source": source or "footsim",
            "archive_version": ARCHIVE_VERSION,
        },
        "payload": payload,
    }
    if extra_meta:
        entry["meta"].update(extra_meta)

    _write_atomic(path, entry)
    return path


def list_snapshots(kind, key=None):
    """
    Listet vorhandene Archivstaende, aelteste zuerst.

    Rueckgabe: Liste von {path, kind, key, captured_at, source}.
    Die Nutzdaten werden dabei NICHT geladen - ein Archiv kann gross
    werden, und meist will der Aufrufer erst den passenden Stand suchen.
    """
    directory = archive_dir_for(kind)
    if not os.path.isdir(directory):
        return []

    entries = []
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".json"):
            continue

        path = os.path.join(directory, filename)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                meta = (json.load(handle) or {}).get("meta") or {}
        except (OSError, ValueError):
            continue

        if key is not None and meta.get("key") != str(key):
            continue

        entries.append({
            "path": path,
            "kind": meta.get("kind"),
            "key": meta.get("key"),
            "captured_at": meta.get("captured_at"),
            "source": meta.get("source"),
        })

    entries.sort(key=lambda e: e.get("captured_at") or "")
    return entries


def load_snapshot_file(path):
    """Laedt eine Archivdatei. Rueckgabe: dict mit meta/payload, oder None."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            entry = json.load(handle)
    except (OSError, ValueError):
        return None

    if not isinstance(entry, dict) or "payload" not in entry:
        return None

    return entry


def snapshot_as_of(kind, cutoff, key=None):
    """
    Der juengste Stand, der zum Zeitpunkt cutoff bereits existierte.

    Das ist der Point-in-Time-Zugriff auf das Archiv: Fuer ein
    Trainingsbeispiel vom 12. November wird der Kaderstand gebraucht, der
    an diesem Tag galt - nicht der heutige.

    Gibt None zurueck, wenn zu diesem Zeitpunkt noch nichts gesammelt
    wurde. Das ist ein ehrliches "wissen wir nicht" und kein Fehler:
    Rueckwirkend laesst sich diese Luecke nicht schliessen.
    """
    cutoff_text = cutoff.isoformat() if hasattr(cutoff, "isoformat") else str(cutoff)

    candidates = [
        entry for entry in list_snapshots(kind, key=key)
        if (entry.get("captured_at") or "") <= cutoff_text
    ]

    if not candidates:
        return None

    return load_snapshot_file(candidates[-1]["path"])


def archive_coverage(kind):
    """
    Kennzahlen ueber das Archiv einer Art.

    Beantwortet die Frage, ab wann fuer diese Datenart ueberhaupt eine
    Historie existiert - und damit, ab wann ein Backtest sie benutzen
    darf.
    """
    entries = list_snapshots(kind)

    return {
        "kind": kind,
        "snapshots": len(entries),
        "keys": sorted({e["key"] for e in entries if e.get("key")}),
        "earliest": entries[0]["captured_at"] if entries else None,
        "latest": entries[-1]["captured_at"] if entries else None,
    }
