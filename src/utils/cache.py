"""
Einfacher In-Memory Cache mit Ablaufzeit.

Hintergrund:
football-data.org erlaubt im Free Plan nur 10 Requests pro Minute.
Ohne Cache wuerde jeder Klick im Frontend einen externen Request ausloesen.
Bei drei gleichzeitigen Nutzern waere das Limit sofort erreicht.

Verwendung:

    from src.utils.cache import cached_call

    daten = cached_call(
        key="standings_bl1_2026",
        ttl_seconds=1800,
        loader=lambda: hole_daten_von_der_api()
    )

Der loader wird nur aufgerufen, wenn nichts Gueltiges im Cache liegt.
"""

import time
import threading


# Struktur: { key: (ablaufzeitpunkt, wert) }
_store = {}

# Schuetzt den Store, weil Gunicorn mit mehreren Threads arbeiten kann
_lock = threading.Lock()


# Empfohlene Cache-Zeiten in Sekunden.
# Diese Werte sind bewusst grosszuegig, weil sich die Daten selten aendern.
TTL_SEASON_INFO = 60 * 60 * 6      # 6 Stunden  - Saison und aktueller Spieltag
TTL_STANDINGS = 60 * 30            # 30 Minuten - Tabellen
TTL_SCORERS = 60 * 60              # 60 Minuten - Torjaeger
TTL_MATCHES_UPCOMING = 60 * 60 * 2  # 2 Stunden  - Spielplan kommender Spieltage
TTL_MATCHES_FINISHED = 60 * 60 * 24  # 24 Stunden - abgeschlossene Spieltage
TTL_TEAM_FORM = 60 * 60 * 3        # 3 Stunden  - Formdaten eines Teams
TTL_TEAMS = 60 * 60 * 24 * 7       # 7 Tage     - Vereinsliste einer Saison
TTL_CUP_MATCHES = 60 * 60 * 2      # 2 Stunden  - Pokalspiele mit Phasenangabe
TTL_SEASON_DONE = 60 * 60 * 24 * 30  # 30 Tage  - abgeschlossene Saisons

# Leere Antworten (Saison noch nicht gestartet, Quelle kurz nicht
# erreichbar) werden nur kurz festgehalten. Auf der Platte ueberlebt ein
# leeres Ergebnis sonst den Neustart und der Wettbewerb bliebe kuenstlich
# lange leer. Siehe empty_ttl_seconds in src/utils/disk_cache.py.
TTL_EMPTY_RESULT = 60 * 15         # 15 Minuten - leere Antworten

# API-Sports-Kaderdaten (Torschuetzen + Ausfaelle). Bewusst lang, weil
# jeder Abruf zwei Requests vom knappen API-Sports-Budget kostet und sich
# Verletzungsmeldungen nicht im Minutentakt aendern. Siehe
# src/features/squad_impact.py, das diesen Wert mit dem Disk-Cache nutzt.
TTL_APISPORTS_INJURIES = 60 * 60 * 12  # 12 Stunden - Kaderwirkung


def cached_call(key, ttl_seconds, loader):
    """
    Gibt den gecachten Wert zurueck oder ruft loader auf und speichert das Ergebnis.

    Wenn der loader eine Exception wirft, wird ein eventuell vorhandener
    abgelaufener Wert als Notfall-Fallback zurueckgegeben. Lieber leicht
    veraltete Daten anzeigen als eine kaputte Seite.
    """
    now = time.time()

    with _lock:
        entry = _store.get(key)

    if entry is not None:
        expires_at, value = entry
        if now < expires_at:
            return value

    try:
        value = loader()
    except Exception:
        # Notfall: abgelaufenen Wert weiterverwenden, falls vorhanden
        if entry is not None:
            return entry[1]
        raise

    with _lock:
        _store[key] = (now + ttl_seconds, value)

    return value


def invalidate(key):
    """Einen einzelnen Eintrag verwerfen."""
    with _lock:
        _store.pop(key, None)


def invalidate_prefix(prefix):
    """Alle Eintraege verwerfen, deren Key mit prefix beginnt."""
    with _lock:
        for key in [k for k in _store if k.startswith(prefix)]:
            _store.pop(key, None)


def clear_all():
    """Kompletten Cache leeren."""
    with _lock:
        _store.clear()


def stats():
    """Kleiner Einblick fuer Debugging und die Statusseite."""
    now = time.time()

    with _lock:
        total = len(_store)
        alive = sum(1 for expires_at, _ in _store.values() if now < expires_at)
        keys = sorted(_store.keys())

    return {
        "entries_total": total,
        "entries_valid": alive,
        "entries_expired": total - alive,
        "keys": keys
    }
