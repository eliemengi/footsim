"""
Perzentil-Engine fuer den Spielervergleich (Phase 3, Etappe 2).

Dieses Modul enthaelt BEWUSST keinen API-Zugriff und kein Dateisystem-Schreiben
ausser dem Lesen und Schreiben fertiger Snapshots. Die eigentliche Mathematik
ist rein und ohne Netzwerk testbar.

Grundgedanke
------------
Ein Perzentil beantwortet die Frage: "Wie viel Prozent der vergleichbaren
Spieler sind schlechter als dieser Spieler?"

Damit das ehrlich ist, braucht es einen VOLLSTAENDIGEN Referenzpool. Ein
Perzentil aus halb geladenen Ligen waere schlimmer als gar keines, weil es
Praezision vortaeuscht, die nicht existiert.

Speicherformat: Quantil-Stuetzstellen
-------------------------------------
Statt alle Rohwerte aller Spieler zu speichern, wird pro Positionsgruppe und
Kennzahl eine Liste von 101 Stuetzstellen abgelegt (P0 bis P100).

Vorteile:
    - Der Snapshot ist klein genug fuer das Git-Repository und damit sofort
      nach dem Deployment verfuegbar, ohne dass auf dem Server importiert
      werden muss.
    - Der Lookup ist eine binaere Suche, unabhaengig von der Poolgroesse.
    - Die Aufloesung von einem Prozentpunkt ist fuer ein Radar mehr als genug.

Umgang mit Gleichstaenden
-------------------------
Viele Kennzahlen haben eine grosse Haeufung bei niedrigen Werten (etwa
Blocks pro 90 bei Offensivspielern). Deshalb wird der Mid-Rank verwendet:
der Mittelwert aus unterer und oberer Einordnung. Sonst wuerde derselbe Wert
je nach Rechenweg einmal das 0. und einmal das 40. Perzentil ergeben.
"""

import bisect
import json
import os
from datetime import datetime, timezone

from src.data.player_metrics import (
    METRICS,
    POSITION_GROUPS,
    RADAR_PROFILES,
    GENERAL_METRICS,
    LOWER_BETTER,
)


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

# Mindesteinsatzzeit fuer die Aufnahme in den Referenzpool.
#
# Produktentscheidung (MVP, siehe docs/player_comparison.md):
#   450 Minuten entsprechen fuenf vollen Spielen. Darunter sind Per-90-Werte
#   statistisch nicht belastbar: ein Spieler mit 45 Minuten und einem Tor
#   haette 2.0 Tore pro 90 und wuerde jede Verteilung verzerren.
#
# Bewusst konfigurierbar gelassen. Sobald die ersten vollstaendigen Pools
# vorliegen, ist anhand der echten Verteilung zu pruefen, ob 450 zu streng
# ist (Alternative: 360) oder zu mild (Alternative: 540).
DEFAULT_MIN_MINUTES = 450

# Unterhalb dieser Poolgroesse wird kein Perzentil berechnet.
# Bei sehr kleinen Gruppen waere ein Perzentil reines Rauschen.
MIN_POOL_SIZE = 30

# Anzahl der Stuetzstellen: P0 bis P100.
QUANTILE_STEPS = 101

# Ligen, die gemeinsam den Referenzpool bilden.
REQUIRED_LEAGUES = ("bl1", "pl", "pd", "sa", "fl1")

# Wettbewerbsumfaenge, fuer die je eine eigene Verteilung berechnet wird.
# Bewusst hier lokal definiert und NICHT aus player_compare_loader importiert:
# jenes Modul importiert bereits aus diesem hier, ein Rueckimport waere ein
# Zyklus. Die Werte muessen mit COMPETITION_SCOPES dort uebereinstimmen.
SNAPSHOT_SCOPES = ("club_all", "league", "national", "all")

# Standard-Scope: club_all. Er bildet weiterhin die Top-Level-Verteilung des
# Snapshots, damit aeltere Leser (die nur snapshot["distributions"] kennen)
# unveraendert funktionieren.
DEFAULT_SCOPE = "club_all"

# Absoluter Pfad, gleiche Begruendung wie in player_pool.py: der Importjob
# laeuft per Cron aus einem beliebigen Arbeitsverzeichnis, die Anwendung
# unter Gunicorn aus einem anderen. Beide muessen dieselbe Datei sehen.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PERCENTILE_DIR = os.path.join(_PROJECT_ROOT, "data", "percentiles")


# ---------------------------------------------------------------------------
# Verteilung aufbauen
# ---------------------------------------------------------------------------

def build_quantiles(values):
    """
    Baut 101 Quantil-Stuetzstellen aus einer Werteliste.

    values: Liste von Zahlen. None-Werte muessen vorher entfernt sein.
    Rueckgabe: aufsteigend sortierte Liste mit QUANTILE_STEPS Eintraegen
               oder None, wenn die Stichprobe zu klein ist.
    """
    clean = sorted(v for v in values if v is not None)

    if len(clean) < MIN_POOL_SIZE:
        return None

    last_index = len(clean) - 1
    quantiles = []

    for step in range(QUANTILE_STEPS):
        # Lineare Interpolation zwischen den beiden Nachbarwerten
        position = step / (QUANTILE_STEPS - 1) * last_index
        lower = int(position)
        upper = min(lower + 1, last_index)
        weight = position - lower
        value = clean[lower] * (1 - weight) + clean[upper] * weight
        quantiles.append(round(value, 4))

    return quantiles


def percentile_of(value, quantiles):
    """
    Ordnet einen Wert in eine Quantil-Verteilung ein.

    Rueckgabe: Perzentil von 0 bis 100, oder None wenn keine Einordnung
    moeglich ist. Ein None bedeutet immer "nicht bestimmbar", nie 0.
    """
    if value is None or not quantiles:
        return None

    # Untere und obere Einordnung, dann Mid-Rank gegen Gleichstaende
    low = bisect.bisect_left(quantiles, value)
    high = bisect.bisect_right(quantiles, value)

    # bisect_right zeigt hinter das letzte passende Element
    rank = (low + max(high - 1, low)) / 2.0

    percentile = rank / (QUANTILE_STEPS - 1) * 100.0
    return int(round(max(0.0, min(100.0, percentile))))


def apply_direction(percentile, metric_key):
    """
    Dreht das Perzentil bei Kennzahlen, bei denen ein niedriger Wert besser ist.

    Beispiel Gegentore pro 90: Wer wenige kassiert, soll ein HOHES Perzentil
    bekommen, weil im Radar aussen immer "besser" bedeutet.
    """
    if percentile is None:
        return None
    metric = METRICS.get(metric_key)
    if metric is None:
        return percentile
    if metric["direction"] == LOWER_BETTER:
        return 100 - percentile
    return percentile


# ---------------------------------------------------------------------------
# Snapshot bauen
# ---------------------------------------------------------------------------

def relevant_metric_keys(position):
    """
    Alle Kennzahlen, fuer die eine Positionsgruppe Perzentile braucht.

    Das sind die Radar-Achsen plus die allgemeinen Kennzahlen, damit auch
    der positionsuebergreifende Vergleich Einordnungen zeigen kann.
    """
    keys = list(RADAR_PROFILES.get(position, []))
    for key in GENERAL_METRICS:
        if key not in keys:
            keys.append(key)
    return keys


def build_distributions(pool_entries, min_minutes, scope):
    """
    Baut die Verteilungen aller Positionsgruppen fuer EINEN Wettbewerbsumfang.

    Rueckgabe: dict position -> {"player_count", "metrics": {key -> {n, q}}}.
    Positionen ohne belastbare Verteilung fehlen bewusst, statt eine
    schlechte Verteilung vorzutaeuschen.

    Reine Funktion ohne Dateizugriff.
    """
    eligible = [
        entry for entry in pool_entries
        if entry.get("position") in POSITION_GROUPS
        and ((entry.get("minutes_by_scope") or {}).get(scope) or 0) >= min_minutes
    ]

    distributions = {}

    for position in POSITION_GROUPS:
        players = [e for e in eligible if e.get("position") == position]
        if not players:
            continue

        per_metric = {}
        for metric_key in relevant_metric_keys(position):
            values = []
            for player in players:
                value = (player.get("metrics_by_scope") or {}).get(scope, {}).get(metric_key)
                if value is not None:
                    values.append(float(value))

            quantiles = build_quantiles(values)
            if quantiles is None:
                # Zu wenige valide Werte: kein Perzentil statt eines schlechten
                continue

            per_metric[metric_key] = {
                "n": len(values),
                "q": quantiles,
            }

        if per_metric:
            distributions[position] = {
                "player_count": len(players),
                "metrics": per_metric,
            }

    return distributions


def build_snapshot(pool_entries, season, leagues, min_minutes=DEFAULT_MIN_MINUTES,
                   scopes=SNAPSHOT_SCOPES):
    """
    Baut aus einem Spielerpool einen Perzentil-Snapshot mit EINER Verteilung
    JE Wettbewerbsumfang.

    pool_entries: Liste von Pooleintraegen im scope-bewussten Schema
                  (siehe player_pool.build_pool_entry): "position",
                  "minutes_by_scope" und "metrics_by_scope".

    scopes: welche Wettbewerbsumfaenge berechnet werden. Standard: alle vier
            (club_all, league, national, all). Fuer jeden Scope wird die
            Mindestminutengrenze GEGEN DIE MINUTEN DESSELBEN SCOPES geprueft -
            ein Spieler mit 3000 Ligaminuten, aber nur 200 Laenderspielminuten
            zaehlt in der Ligaverteilung, nicht in der Nationalmannschafts-
            verteilung.

    Der Snapshot traegt zusaetzlich eine Top-Level-Verteilung fuer den
    Standard-Scope (club_all) unter dem alten Schluessel "distributions".
    Dadurch funktionieren aeltere Leser unveraendert, waehrend
    "distributions_by_scope" die vollstaendige, scope-bewusste Sicht liefert.

    Warum ueberhaupt vier Verteilungen: Radar, Scatter und Perzentile teilen
    sich jetzt dieselbe Datenbasis. Waehlt der Nutzer "Nur Liga", muss der
    Spielerwert (Ligaaggregat) gegen eine Ligaverteilung gemessen werden;
    waehlt er "Alle Vereinswettbewerbe", gegen eine club_all-Verteilung.
    Ohne je Scope eigene Stuetzstellen waere genau das nicht moeglich.

    Reine Funktion ohne Dateizugriff, dadurch testbar.
    """
    # Reihenfolge stabil halten, Standard-Scope garantiert enthalten.
    scope_list = list(scopes) if scopes else [DEFAULT_SCOPE]
    if DEFAULT_SCOPE not in scope_list:
        scope_list = [DEFAULT_SCOPE] + scope_list

    distributions_by_scope = {
        scope: build_distributions(pool_entries, min_minutes, scope)
        for scope in scope_list
    }

    return {
        "season": season,
        # Top-Level-Scope bleibt der Standard - Rueckwaertskompatibilitaet.
        "scope": DEFAULT_SCOPE,
        "scopes": scope_list,
        "leagues": sorted(leagues),
        "min_minutes": min_minutes,
        "min_pool_size": MIN_POOL_SIZE,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # Alt: eine einzelne Verteilung (club_all). Bleibt fuer bestehende
        # Leser erhalten.
        "distributions": distributions_by_scope.get(DEFAULT_SCOPE, {}),
        # Neu: alle Verteilungen, nach Wettbewerbsumfang.
        "distributions_by_scope": distributions_by_scope,
    }


# ---------------------------------------------------------------------------
# Snapshot lesen und anwenden
# ---------------------------------------------------------------------------

def snapshot_path(season):
    return os.path.join(PERCENTILE_DIR, f"percentiles_{season}.json")


def load_snapshot(season):
    """
    Laedt den Perzentil-Snapshot einer Saison.

    Rueckgabe: dict oder None. Ein fehlender Snapshot ist kein Fehler,
    sondern bedeutet schlicht, dass noch keine Perzentile verfuegbar sind.
    """
    path = snapshot_path(season)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def save_snapshot(snapshot):
    """
    Schreibt einen Snapshot atomar.

    Erst in eine temporaere Datei, dann umbenennen. Dadurch sieht ein
    parallel lesender Gunicorn-Worker nie eine halb geschriebene Datei.
    """
    os.makedirs(PERCENTILE_DIR, exist_ok=True)
    path = snapshot_path(snapshot["season"])
    temp_path = path + ".tmp"

    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, ensure_ascii=False, separators=(",", ":"))

    os.replace(temp_path, path)
    return path


def is_snapshot_complete(snapshot):
    """
    Prueft, ob ein Snapshot auf allen erforderlichen Ligen beruht.

    Nur dann darf von "Top-5-Ligen-Perzentilen" gesprochen werden.
    """
    if not snapshot:
        return False
    leagues = set(snapshot.get("leagues") or [])
    return set(REQUIRED_LEAGUES).issubset(leagues)


def distributions_for_scope(snapshot, scope=None):
    """
    Waehlt die Verteilungen eines Scopes aus dem Snapshot.

    Faellt in dieser Reihenfolge zurueck:
      1. distributions_by_scope[scope], wenn vorhanden
      2. Top-Level distributions (Standard-Scope, alte Snapshots)

    Dadurch funktioniert ein alter Snapshot ohne distributions_by_scope
    weiterhin - er verhaelt sich wie ein reiner club_all-Snapshot.
    """
    if not snapshot:
        return {}

    by_scope = snapshot.get("distributions_by_scope")
    if by_scope and scope in by_scope:
        return by_scope.get(scope) or {}

    if scope and by_scope is not None and scope not in by_scope:
        # Scope wurde nie berechnet (z. B. leerer national-Pool): bewusst
        # keine fremde Verteilung unterschieben.
        return {}

    return snapshot.get("distributions") or {}


def describe_pool(snapshot, position, scope=None):
    """
    Baut den Erklaertext, der im UI unter jedem Perzentil stehen muss.

    Ein Perzentil ohne Angabe der Vergleichsgruppe ist wertlos. Die
    Gruppengroesse bezieht sich auf den gewaehlten Wettbewerbsumfang.
    """
    if not snapshot:
        return None

    distribution = distributions_for_scope(snapshot, scope).get(position)
    if not distribution:
        return None

    season = snapshot.get("season")
    season_label = f"{season}/{str(season + 1)[2:]}" if season else "?"

    return {
        "season": season,
        "season_label": season_label,
        "leagues": snapshot.get("leagues") or [],
        "min_minutes": snapshot.get("min_minutes"),
        "player_count": distribution.get("player_count"),
        "complete": is_snapshot_complete(snapshot),
    }


def percentiles_for_player(snapshot, position, metric_values, scope=None):
    """
    Berechnet die Perzentile eines Spielers.

    metric_values: dict metric_key -> Rohwert (oder None)
    scope:         Wettbewerbsumfang, dessen Verteilung als Vergleichsgruppe
                   dient. Ohne Angabe wird die Top-Level-Verteilung genutzt
                   (Standard-Scope / alte Snapshots).
    Rueckgabe:     dict metric_key -> Perzentil (oder None)

    Ein Perzentil entsteht nur, wenn:
        - ein Snapshot vorliegt,
        - die Positionsgruppe darin enthalten ist,
        - fuer die Kennzahl eine Verteilung existiert,
        - der Spieler einen Rohwert hat.
    In allen anderen Faellen: None. Nie ein geschaetzter Wert.

    Wichtig: Der Rohwert MUSS fuer denselben Scope berechnet worden sein wie
    die hier gewaehlte Verteilung. Sonst misst man z. B. einen club_all-Wert
    an einer reinen Ligaverteilung - genau die Inkonsistenz, die diese
    Erweiterung beseitigt.
    """
    result = {key: None for key in metric_values}

    if not snapshot or not position:
        return result

    distribution = distributions_for_scope(snapshot, scope).get(position)
    if not distribution:
        return result

    metrics = distribution.get("metrics") or {}

    for key, value in metric_values.items():
        entry = metrics.get(key)
        if not entry:
            continue
        raw_percentile = percentile_of(value, entry.get("q"))
        result[key] = apply_direction(raw_percentile, key)

    return result
