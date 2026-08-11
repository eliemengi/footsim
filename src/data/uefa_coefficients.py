"""
Historische UEFA-Klubkoeffizienten (Block F1, Gegnerstaerke).

Datenlage
---------
Die Snapshots liegen unter data/big_games/uefa_coefficients/ und enthalten
je Saison die UEFA-Top-40 mit Rang, Koeffizient und - entscheidend -
STABILEN numerischen Team-IDs beider im Projekt vorkommenden Namensraeume:

    footsim_team_id      football-data.org (historisch gewachsen)
    apisports_team_id    API-Football  <- der fuer F1 massgebliche

Die Dateien sind bewusst NICHT im Repository (siehe .gitignore,
data/big_games/). Sie wurden manuell aus UEFA-Veroeffentlichungen erfasst
und bleiben serverseitig. Sie werden NIE vollstaendig an das Frontend
ausgeliefert - das Frontend bekommt ausschliesslich das abgeleitete
Ergebnis eines konkreten Vergleichs.

Identitaet: ausschliesslich ueber stabile IDs
---------------------------------------------
In diesem Modul wird NIE ueber Namen aufgeloest. Kein Teilstring, kein
Stadtname, keine Namensaehnlichkeit. Grund ist ein realer Vorfall im
Projekt: "Barcelona" loeste ueber Teilstring-Suche auf "RCD Espanyol de
Barcelona" auf (Commit d0bfd03). Ein solcher Fehler wuerde hier bedeuten,
dass ein Klub den Koeffizienten eines voellig anderen Klubs erbt.

Deshalb: Nachschlagen geschieht ausschliesslich ueber
apisports_team_id. Ein Gegner, dessen ID nicht in der Liste steht, gilt
als "nicht in den Top 40" - nicht als "vermutlich dieser aehnlich
heissende Klub".

Saisonzuordnung
---------------
FootSim und API-Football bezeichnen eine Saison durchgaengig mit dem
Jahr ihres Beginns (CURRENT_SEASON = 2025 meint 2025/26; siehe
apisports_api.py und data/historical/BL1_2024.json). Diese Datei ist die
EINZIGE Stelle, die daraus einen Dateinamen bildet - der Rest der
Anwendung fragt nur mit der Ganzzahl an.
"""

import json
import os
import threading

# Projektwurzel: .../src/data/uefa_coefficients.py -> drei Ebenen hoch.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

COEFFICIENT_DIR = os.path.join(_PROJECT_ROOT, "data", "big_games", "uefa_coefficients")

# Aelteste Saison mit vorliegendem Snapshot. Bewusst als Konstante und
# nicht aus dem Verzeichnis abgeleitet: die Anwendung soll auch dann eine
# ehrliche Untergrenze melden koennen, wenn die privaten Dateien auf einem
# Host (noch) gar nicht liegen.
EARLIEST_COEFFICIENT_SEASON = 2021

# Snapshots werden nach dem ersten Lesen im Prozess gehalten. Das ist hier
# unbedenklich (sechs kleine, unveraenderliche Dateien) und bewusst KEIN
# Ersatz fuer den Plattencache: es wird nichts berechnet, nur geparst.
_CACHE = {}
_CACHE_LOCK = threading.Lock()


def season_label(season):
    """2021 -> "2021/22". Einzige Stelle, die dieses Format erzeugt."""
    return f"{season}/{str(season + 1)[-2:]}"


def snapshot_path(season):
    """Dateipfad des Snapshots einer Saison. Kein Zugriff, nur Pfadbildung."""
    return os.path.join(COEFFICIENT_DIR, f"uefa_coefficients_{season}_{str(season + 1)[-2:]}.json")


def _empty_snapshot(season, reason):
    """
    Neutraler Ersatzwert, wenn kein verwertbarer Snapshot vorliegt.

    Bewusst kein Fehler: fehlt die Saison, ist Big Games fuer sie nicht
    verfuegbar - die uebrige Anwendung (Spielervergleich, LIVE,
    Simulation) darf davon nicht beruehrt werden.
    """
    return {
        "season": season,
        "season_label": season_label(season),
        "available": False,
        "reason": reason,
        "provisional": False,
        "by_team_id": {},
        "min_coefficient": None,
        "max_coefficient": None,
        "club_count": 0,
    }


def _parse_snapshot(season, raw):
    """
    Wandelt den Dateiinhalt in die intern genutzte Form.

    Verworfen werden ausschliesslich Eintraege ohne vertrauenswuerdige
    apisports_team_id - fuer sie gibt es keine sichere Zuordnung, und
    Raten ist nicht zulaessig (siehe Modulkopf).
    """
    clubs = raw.get("clubs")
    if not isinstance(clubs, list) or not clubs:
        return _empty_snapshot(season, "empty_or_invalid")

    by_team_id = {}
    coefficients = []
    seen_ranks = set()

    for club in clubs:
        if not isinstance(club, dict):
            continue

        rank = club.get("rank")
        coefficient = club.get("total_coefficient")
        team_id = club.get("apisports_team_id")

        if not isinstance(rank, int) or rank in seen_ranks:
            # Doppelte oder unbrauchbare Raenge deuten auf eine kaputte
            # Datei hin - der betroffene Eintrag wird uebersprungen, statt
            # eine zweite Wahrheit fuer denselben Rang zuzulassen.
            continue
        seen_ranks.add(rank)

        if isinstance(coefficient, (int, float)) and not isinstance(coefficient, bool):
            coefficients.append(float(coefficient))

        if team_id is None:
            # Bewusst unaufgeloeste Klubs (z. B. Viktoria Plzen): sie
            # bleiben ohne Zuordnung und gelten spaeter schlicht als
            # "nicht in den Top 40".
            continue

        try:
            team_id = int(team_id)
        except (TypeError, ValueError):
            continue

        if team_id in by_team_id:
            # Zwei Eintraege mit derselben Team-ID waeren ein Datenfehler.
            # Der erste (bessere) Rang gewinnt, der zweite wird ignoriert.
            continue

        by_team_id[team_id] = {
            "rank": rank,
            "coefficient": float(coefficient) if isinstance(coefficient, (int, float))
                           and not isinstance(coefficient, bool) else None,
            "club_name": club.get("club_name"),
            "country": club.get("country"),
        }

    return {
        "season": season,
        "season_label": raw.get("season") or season_label(season),
        "available": True,
        "reason": None,
        # 2026/27 traegt status "provisional": die laufende Saison hat noch
        # kaum Punkte beigesteuert. Der Gesamtkoeffizient bleibt trotzdem
        # die gueltige rollierende Rangliste - eine 0.000 im Saisonanteil
        # bedeutet ausdruecklich NICHT, dass ein Klub schwach ist.
        "provisional": raw.get("status") == "provisional",
        "by_team_id": by_team_id,
        "min_coefficient": min(coefficients) if coefficients else None,
        "max_coefficient": max(coefficients) if coefficients else None,
        "club_count": len(seen_ranks),
    }


def load_snapshot(season):
    """
    Snapshot einer Saison. Immer ein Dict, nie eine Exception.

    Fehlende Datei, kaputtes JSON oder unlesbarer Inhalt ergeben einen
    neutralen, als nicht verfuegbar gekennzeichneten Snapshot. Big Games
    faellt fuer diese Saison sauber aus, der Rest der Anwendung laeuft
    unveraendert weiter.
    """
    with _CACHE_LOCK:
        cached = _CACHE.get(season)
    if cached is not None:
        return cached

    path = snapshot_path(season)

    if not os.path.exists(path):
        snapshot = _empty_snapshot(season, "missing_file")
    else:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            snapshot = (_parse_snapshot(season, raw) if isinstance(raw, dict)
                        else _empty_snapshot(season, "invalid_structure"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            snapshot = _empty_snapshot(season, "unreadable")

    with _CACHE_LOCK:
        _CACHE[season] = snapshot

    return snapshot


def clear_cache():
    """Verwirft die geparsten Snapshots. Nur fuer Tests und Wartung."""
    with _CACHE_LOCK:
        _CACHE.clear()


def has_season(season):
    """True, wenn fuer diese Saison ein verwertbarer Snapshot vorliegt."""
    return load_snapshot(season)["available"]


def available_seasons(first, last):
    """Alle Saisons im Bereich, fuer die ein Snapshot vorliegt."""
    return [season for season in range(first, last + 1) if has_season(season)]


def lookup_team(season, apisports_team_id):
    """
    Rang und Koeffizient eines Klubs in GENAU DIESER Saison.

    Ausschliesslich ueber die stabile API-Football-Team-ID. Rueckgabe None,
    wenn der Klub in dieser Saison nicht unter den Top 40 war, seine
    Identitaet nicht sicher aufgeloest werden konnte oder der Snapshot
    fehlt. None heisst immer "kein Rankingbonus", nie "nimm einen
    aehnlichen Klub".
    """
    if apisports_team_id is None:
        return None

    try:
        team_id = int(apisports_team_id)
    except (TypeError, ValueError):
        return None

    return load_snapshot(season)["by_team_id"].get(team_id)
