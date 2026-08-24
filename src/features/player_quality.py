"""
Player Quality: Wie gut ist ein Spieler, gemessen an seiner Position?

ABGRENZUNG
----------
Quality ist NICHT Importance. Importance fragt, wie gross die Rolle im
Team ist (player_importance.py); Quality fragt, wie gut die Leistung
gegenueber Spielern derselben Position ist. Ein Ergaenzungsspieler kann
hohe Quality und geringe Importance haben.

Quality ist ausserdem ausdruecklich NICHT:

    Marktwert          steht in keiner Quelle dieses Projekts
    Bekanntheit        ist keine Messgroesse
    Vereinsgroesse     waere ein Zirkelschluss - das Modell kennt die
                       Teamstaerke bereits
    Gesamtstaerke      waere eine erfundene Zahl ohne Bezugsgroesse

WORAUF SIE BERUHT
-----------------
Auf den vorhandenen Perzentil-Snapshots (data/percentiles/). Diese
werden hier NICHT nachgebaut - percentile_engine.percentile_of() und
apply_direction() erledigen die Einordnung, position_median() liefert
die Referenz, stabilize() die Frueh-Saison-Daempfung aus GO 1.1.

VERGLEICHSGRUPPE
----------------
Jeder Spieler wird ausschliesslich gegen SEINE Positionsgruppe
gemessen. Ein Torwart erscheint nie in der Verteilung der Angreifer.
Das ist keine Feinheit: Die Metriken sind gruppenweise voellig
verschieden, ein positionsuebergreifendes Perzentil waere bedeutungslos.

WENN DIE ABDECKUNG NICHT REICHT
-------------------------------
Dann gibt es kein Ergebnis, sondern "unavailable". Ein neutraler
Ersatzwert von 0.5 waere bequem und falsch - er saehe aus wie eine
Messung und ist keine.
"""

from src.data.percentile_engine import (
    apply_direction,
    current_weight,
    distributions_for_scope,
    load_usable_snapshot,
    percentile_of,
    position_median,
    stabilize,
)
from src.features.player_importance import (
    POSITION_METRICS,
    _safe,
    _scope,
    position_group,
)


#: Wertebereich der Quality. Dokumentiert und getestet.
QUALITY_MIN = 0.0
QUALITY_MAX = 1.0

#: Quality eines exakt durchschnittlichen Spielers seiner Position.
#: Entspricht Perzentil 50.
QUALITY_NEUTRAL = 0.5

#: Wie viele Metriken einer Positionsgruppe mindestens eingeordnet
#: werden koennen muessen, damit ein Wert entsteht.
#:
#: Zwei statt einer: Ein einzelnes Perzentil ist zu schmal, um daraus
#: "Qualitaet" zu nennen - ein Torwart, von dem nur die Gegentorquote
#: bekannt ist, wird durch die Abwehr vor ihm mitbewertet.
MIN_METRICS_FOR_QUALITY = 2

#: Wie viele Spieler in der Verteilung stehen muessen, damit die
#: Positionsgruppe als belastbar gilt.
MIN_GROUP_SIZE = 30

#: Vergleichsebene. "club_all" umfasst Liga und Europapokal und ist
#: damit die breiteste Vereinsbasis - Nationalspiele bleiben draussen,
#: weil dort andere Gegner und andere Rollen gelten.
DEFAULT_SCOPE = "club_all"


def _quantiles(snapshot, position, metric_key, scope=None):
    """Die 101 Quantile einer Metrik in einer Positionsgruppe."""
    verteilungen = distributions_for_scope(snapshot, scope)
    gruppe = verteilungen.get(position) or {}
    eintrag = (gruppe.get("metrics") or {}).get(metric_key)
    if isinstance(eintrag, dict):
        return eintrag.get("q"), eintrag.get("n")
    return eintrag, None


def group_size(snapshot, position, scope=None):
    """Wie viele Spieler die Verteilung dieser Positionsgruppe traegt."""
    verteilungen = distributions_for_scope(snapshot, scope)
    gruppe = verteilungen.get(position) or {}
    return gruppe.get("player_count") or 0


def player_quality(player, snapshot, scope=DEFAULT_SCOPE,
                   reference_snapshot=None, reference_season=None,
                   snapshot_season=None):
    """
    Quality eines Spielers.

    snapshot: Perzentil-Snapshot der laufenden Saison, oder der letzte
              nutzbare (load_usable_snapshot loest das auf).

    Frueh in der Saison wird jeder Rohwert ueber stabilize() zum
    Positionsmedian gezogen, bevor er eingeordnet wird - ein Stuermer
    mit einem Tor aus 55 Minuten haette sonst einen Pro-90-Wert von 1.64
    und damit ein Spitzenperzentil. Der ROHWERT bleibt unangetastet;
    stabilisiert wird nur, was gegen andere gemessen wird.

    Rueckgabe enthaelt immer alle Felder. Ohne Grundlage steht dort
    None und quality_data_status "unavailable".
    """
    gruppe = position_group(player)
    metrics = _scope(player, "league") or _scope(player, "club_all")
    minuten = (metrics or {}).get("minutes") or 0

    leer = {
        "player_id": player.get("player_id"),
        "player_name": player.get("name"),
        "position_group": gruppe,
        "player_quality": None,
        "quality_percentile": None,
        "quality_components": {},
        "quality_reference_season": reference_season,
        "quality_current_weight": round(current_weight(minuten), 6),
        "quality_data_status": "unavailable",
        "metrics_used": [],
        "minutes": minuten,
    }

    if not gruppe or not snapshot:
        leer["reason"] = "no_position" if not gruppe else "no_snapshot"
        return leer

    if group_size(snapshot, gruppe, scope) < MIN_GROUP_SIZE:
        # Zu duenne Vergleichsgruppe. Ein Perzentil gegen 12 Spieler
        # sagt nichts - dann lieber kein Wert.
        leer["reason"] = "group_too_small"
        return leer

    komponenten = {}
    verwendet = []
    perzentile = []

    for name, gewicht in POSITION_METRICS[gruppe]:
        roh = _safe(metrics, name)
        if roh is None:
            continue

        quantile, _ = _quantiles(snapshot, gruppe, name, scope)
        if not quantile:
            continue

        # GO-1.1-Stabilisierung: gegen den Positionsmedian ziehen,
        # gewichtet mit den bisherigen Minuten.
        median = position_median(snapshot, gruppe, name, scope)
        stabilisiert = stabilize(roh, median, minuten)

        wert = apply_direction(percentile_of(stabilisiert, quantile), name)
        if wert is None:
            continue

        komponenten[name] = wert
        verwendet.append(name)
        perzentile.append((wert, abs(gewicht)))

    if len(verwendet) < MIN_METRICS_FOR_QUALITY:
        leer["reason"] = "not_enough_metrics"
        leer["metrics_used"] = verwendet
        leer["quality_components"] = komponenten
        return leer

    gewicht_summe = sum(g for _, g in perzentile)
    mittel = sum(p * g for p, g in perzentile) / gewicht_summe

    vollstaendig = len(verwendet) == len(POSITION_METRICS[gruppe])
    status = "complete" if vollstaendig else "partial"

    return {
        "player_id": player.get("player_id"),
        "player_name": player.get("name"),
        "position_group": gruppe,
        "player_quality": round(max(QUALITY_MIN,
                                    min(QUALITY_MAX, mittel / 100.0)), 6),
        "quality_percentile": round(mittel, 2),
        "quality_components": komponenten,
        "quality_reference_season": (snapshot_season
                                     if snapshot_season is not None
                                     else reference_season),
        "quality_current_weight": round(current_weight(minuten), 6),
        "quality_data_status": status,
        "metrics_used": verwendet,
        "minutes": minuten,
    }


def build_league_quality(pool_players, season, scope=DEFAULT_SCOPE,
                         max_lookback=3):
    """
    Quality aller Spieler einer Liga.

    Der Snapshot wird ueber load_usable_snapshot() geholt: Ist der
    Snapshot der laufenden Saison noch leer - im August der Normalfall -
    weicht er auf die letzte brauchbare Saison aus und meldet, welche
    das war. Genau dafuer wurde die Funktion in GO 1.1 gebaut.

    Rueckgabe: {"players": {...}, "coverage": {...}}
    """
    geladen = load_usable_snapshot(season, max_lookback=max_lookback)
    snapshot = None
    quelle = None
    if geladen:
        # load_usable_snapshot liefert je nach Fassung den Snapshot
        # selbst oder ein Paar aus Snapshot und Saison.
        if isinstance(geladen, tuple):
            snapshot, quelle = geladen
        else:
            snapshot = geladen
            quelle = snapshot.get("season")

    ergebnis = {}
    zaehler = {"complete": 0, "partial": 0, "unavailable": 0}
    je_position = {}
    gruende = {}

    for spieler in pool_players or []:
        pid = spieler.get("player_id")
        if pid is None:
            continue
        eintrag = player_quality(spieler, snapshot, scope,
                                 snapshot_season=quelle)
        ergebnis[int(pid)] = eintrag

        status = eintrag["quality_data_status"]
        zaehler[status] = zaehler.get(status, 0) + 1

        gruppe = eintrag["position_group"] or "unknown"
        je_position.setdefault(gruppe, {"total": 0, "usable": 0})
        je_position[gruppe]["total"] += 1
        if eintrag["player_quality"] is not None:
            je_position[gruppe]["usable"] += 1

        grund = eintrag.get("reason")
        if grund:
            gruende[grund] = gruende.get(grund, 0) + 1

    verfuegbare_metriken = {}
    if snapshot:
        for gruppe in ("Goalkeeper", "Defender", "Midfielder", "Attacker"):
            vorhanden = []
            for name, _ in POSITION_METRICS.get(gruppe, ()):
                quantile, _n = _quantiles(snapshot, gruppe, name, scope)
                if quantile:
                    vorhanden.append(name)
            verfuegbare_metriken[gruppe] = vorhanden

    return {
        "season": season,
        "snapshot_season": quelle,
        "snapshot_available": snapshot is not None,
        "scope": scope,
        "players": ergebnis,
        "coverage": {
            "players": len(ergebnis),
            "by_status": zaehler,
            "by_position": je_position,
            "reasons_unavailable": gruende,
            "metrics_available_by_position": verfuegbare_metriken,
            "group_sizes": {
                g: group_size(snapshot, g, scope) if snapshot else 0
                for g in ("Goalkeeper", "Defender", "Midfielder", "Attacker")
            },
        },
    }


def replacement_quality(quality_entries, position, exclude_ids=(),
                        min_minutes=0):
    """
    Die beste sicher verfuegbare Quality auf einer Position.

    Fuer die Ersatzlogik in squad_availability: Faellt ein Spieler aus,
    faengt der beste verbleibende Spieler DERSELBEN Position den Ausfall
    teilweise auf.

    Positionsfremder Ersatz ist ausgeschlossen. Rueckgabe None, wenn
    kein bewerteter Ersatz vorhanden ist - der Aufrufer behandelt das
    dann konservativ, statt einen Wert anzunehmen.
    """
    ausgeschlossen = {int(p) for p in exclude_ids if p is not None}
    beste = None
    for pid, eintrag in (quality_entries or {}).items():
        if int(pid) in ausgeschlossen:
            continue
        if eintrag.get("position_group") != position:
            continue
        if (eintrag.get("minutes") or 0) < min_minutes:
            continue
        wert = eintrag.get("player_quality")
        if wert is None:
            continue
        if beste is None or wert > beste:
            beste = wert
    return beste
