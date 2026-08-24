"""
Beschaffung der GO-4- und GO-5-Merkmale - einmal je Spiel, nie je Wurf.

WARUM EIN GEMEINSAMES MODUL
---------------------------
GO 4 und GO 5 sind getrennt aktivierbar und haben getrennte Konstanten,
Clamps und Modi. Sie teilen sich aber drei Dinge:

    Importance und Quality   GO 5 braucht sie, GO 4 erzeugt sie
    die Doppelzaehlungssperre einen Spieler darf nicht zugleich als
                             Zugang und als Ausfall wirken
    die gemeinsame Obergrenze aus go4.MAX_COMBINED_GO4_GO5

Diese drei Beruehrungspunkte gehoeren an genau eine Stelle. Zwei
Provider nebeneinander muessten sie duplizieren - und eine doppelte
Obergrenze ist keine Obergrenze.

GETRENNT BLEIBT GETRENNT
------------------------
Dass GO 4 hier Daten fuer GO 5 bereitstellt, macht GO 4 nicht aktiv.
Importance und Quality sind Messwerte; ob sie die Simulation
veraendern, entscheidet allein FOOTSIM_GO4_MODE. GO 5 auf active zu
setzen, waehrend GO 4 auf shadow steht, ist ein zulaessiger und
getesteter Zustand.

KEIN NETZZUGRIFF, KEINE SCHLEIFENARBEIT
---------------------------------------
Alles hier liest lokale Dateien: Spielerpool, Perzentil-Snapshots,
Transfer-Cache, Ausfall-Archiv. Der Snapshot entsteht EINMAL vor der
Monte-Carlo-Schleife; darin wird nur noch gelesen. Ein Test sperrt den
Socket-Aufbau und belegt das.
"""

import threading

from src.features import go4, go5
from src.features.squad_availability import (
    load_availability_snapshot, team_availability)


#: Prozessweiter Zwischenspeicher, wie in go3_provider.
_LEAGUE_CACHE = {}
_TRANSFER_CACHE = {}
_TEAM_CACHE = {}
_LOCK = threading.Lock()

MAX_TEAM_ENTRIES = 20000


def clear_cache():
    """
    Zwischenspeicher leeren. Loescht KEINE Daten auf der Platte.

    Fuer Tests und fuer den Fall, dass Pool oder Snapshots im laufenden
    Betrieb erneuert wurden.
    """
    with _LOCK:
        _LEAGUE_CACHE.clear()
        _TRANSFER_CACHE.clear()
        _TEAM_CACHE.clear()


def cache_stats():
    """Fuellstand des Zwischenspeichers - fuer die Diagnose."""
    with _LOCK:
        return {
            "leagues": len(_LEAGUE_CACHE),
            "transfer_sets": len(_TRANSFER_CACHE),
            "teams": len(_TEAM_CACHE),
            "max_teams": MAX_TEAM_ENTRIES,
        }


def _load_pool(league_code, season):
    """Spielerpool einer Liga und Saison. Fehlt er, ist das kein Fehler."""
    import json
    import os

    from src.utils.disk_cache import _PROJECT_ROOT

    pfad = os.path.join(_PROJECT_ROOT, "data", "player_pool",
                        f"pool_{league_code}_{season}.json")
    if not os.path.exists(pfad):
        return []
    try:
        with open(pfad, "r", encoding="utf-8") as datei:
            return (json.load(datei) or {}).get("players") or []
    except (OSError, ValueError):
        return []


def league_player_features(league_code, season, reference_season=None):
    """
    Importance und Quality aller Spieler einer Liga - einmal je Liga.

    Das ist der teure Teil (Perzentileinordnung fuer mehrere hundert
    Spieler). Er wird genau einmal je Liga und Saison gerechnet und
    danach im Prozess gehalten.
    """
    if reference_season is None:
        reference_season = season - 1

    schluessel = (league_code, season, reference_season)
    with _LOCK:
        vorhanden = _LEAGUE_CACHE.get(schluessel)
    if vorhanden is not None:
        return vorhanden

    from src.features.player_importance import build_league_importance
    from src.features.player_quality import build_league_quality

    pool = _load_pool(league_code, season)
    referenz = _load_pool(league_code, reference_season)

    importance = build_league_importance(
        pool, league_code, season, referenz, reference_season)
    quality = build_league_quality(pool, season)

    paket = {
        "league": league_code,
        "season": season,
        "reference_season": reference_season,
        "importance": importance["players"],
        "quality": quality["players"],
        "importance_coverage": importance["coverage"],
        "quality_coverage": quality["coverage"],
        "snapshot_season": quality.get("snapshot_season"),
        "pool_size": len(pool),
        "squads_by_name": {},
    }

    # Kaderzuordnung nur fuer die laufende Saison - der Pool fuehrt den
    # heutigen Verein (siehe player_identity).
    from src.features.squad_availability import group_pool_by_team
    paket["squads_by_name"] = group_pool_by_team(pool)

    with _LOCK:
        _LEAGUE_CACHE[schluessel] = paket
    return paket


def transfer_events_for(known_team_ids=None):
    """Normalisierte Transferereignisse - einmal je Prozess."""
    schluessel = tuple(sorted(known_team_ids)) if known_team_ids else None
    with _LOCK:
        vorhanden = _TRANSFER_CACHE.get(schluessel)
    if vorhanden is not None:
        return vorhanden

    from src.features.transfer_events import load_transfer_events

    eintraege, diagnose = load_transfer_events(known_team_ids=known_team_ids)
    paket = {"events": eintraege, "diagnostics": diagnose}
    with _LOCK:
        _TRANSFER_CACHE[schluessel] = paket
    return paket


# ---------------------------------------------------------------------------
# Merkmale eines Teams
# ---------------------------------------------------------------------------

def team_go4_features(team_player_ids, league_features, competition_code,
                      season, as_of=None):
    """
    GO-4-Merkmale eines Teams: Verfuegbarkeit und Korrektur.

    as_of: Stichtag. Ist er gesetzt, wird der Ausfallstand
        AUSSCHLIESSLICH im Archiv gesucht. Gibt es keinen, ist die
        Verfuegbarkeit "unavailable" - nicht "alle da". Rueckwirkend
        wird nichts rekonstruiert.
    """
    if as_of is None:
        # Aktueller Stand: Ausfaelle muessten live geholt werden. Das
        # geschieht hier bewusst NICHT - ein Provider-Request in der
        # Simulation waere genau der verbotene Fall. Der Aufrufer
        # reicht die Ausfaelle herein oder es gibt keine Aussage.
        ausfaelle, zeitmarke, bekannt = {}, None, False
    else:
        ausfaelle, zeitmarke = load_availability_snapshot(
            competition_code, season, as_of)
        bekannt = ausfaelle is not None
        ausfaelle = ausfaelle or {}

    verfuegbarkeit = team_availability(
        team_player_ids,
        league_features["importance"], league_features["quality"],
        ausfaelle, as_of=as_of, snapshot_timestamp=zeitmarke,
        absences_known=bekannt)

    return {
        "availability": verfuegbarkeit,
        "modifier": go4.compute_modifier(verfuegbarkeit),
        "absent_player_ids": [s["player_id"]
                              for s in (verfuegbarkeit.get("unavailable_players") or [])],
    }


def team_go4_features_with_absences(team_player_ids, league_features,
                                    absences, as_of=None,
                                    snapshot_timestamp=None):
    """
    Wie team_go4_features, aber mit hereingereichtem Ausfallstand.

    Fuer den Live-Betrieb, in dem der Aufrufer die Ausfaelle bereits
    besitzt, und fuer Tests. Ein leerer, aber BEKANNTER Stand
    ("niemand fehlt") wird hier unterschieden von einem unbekannten -
    genau diese Unterscheidung traegt team_availability.
    """
    verfuegbarkeit = team_availability(
        team_player_ids,
        league_features["importance"], league_features["quality"],
        absences or {}, as_of=as_of, snapshot_timestamp=snapshot_timestamp,
        absences_known=absences is not None)

    return {
        "availability": verfuegbarkeit,
        "modifier": go4.compute_modifier(verfuegbarkeit),
        "absent_player_ids": [s["player_id"]
                              for s in (verfuegbarkeit.get("unavailable_players") or [])],
    }


def team_go5_features(team_apisports_id, league_features, events, cutoff_date,
                      season, timeline=None, cutoff=None,
                      excluded_player_ids=(), k=None):
    """
    GO-5-Merkmale eines Teams: Transferwirkung mit Decay.

    excluded_player_ids: von GO 4 als ausgefallen gefuehrte Spieler.
        Sie zaehlen hier nicht noch einmal.
    """
    from src.features.transfer_events import team_window_transfers

    if team_apisports_id is None or not events:
        return {"impact": go5.empty_impact("no_team_mapping"), "incoming": [],
                "outgoing": []}

    fenster = go5.CONSTANTS["TRANSFER_WINDOW_DAYS"]["wert"]
    zugaenge, abgaenge = team_window_transfers(
        events, team_apisports_id, cutoff_date, season, window_days=fenster)

    gespielt = None
    if timeline is not None and cutoff is not None:
        gespielt = go5.count_league_matches_before(timeline, cutoff, season)

    wirkung = go5.transfer_impact(
        zugaenge, abgaenge,
        league_features["importance"], league_features["quality"],
        season_matches_played=gespielt, k=k,
        excluded_player_ids=excluded_player_ids)

    return {"impact": wirkung, "incoming": zugaenge, "outgoing": abgaenge}


# ---------------------------------------------------------------------------
# Zusammenfuehrung
# ---------------------------------------------------------------------------

def combine(go4_modifier, go5_impact, go4_active, go5_active):
    """
    Die gemeinsame Wirkung beider Features - mit EINER Obergrenze.

    Nur was aktiv ist, geht ein. Steht GO 4 auf shadow und GO 5 auf
    active, traegt allein GO 5 zur Summe bei; die GO-4-Werte bleiben
    trotzdem vollstaendig in der Diagnose sichtbar.

    Rueckgabe: {"attack", "defence", "clamp_applied", "clamped_parts"}
    """
    a4 = (go4_modifier or {}).get("attack_modifier", 0.0) if go4_active else 0.0
    d4 = (go4_modifier or {}).get("defence_modifier", 0.0) if go4_active else 0.0
    a5 = (go5_impact or {}).get("attack_modifier", 0.0) if go5_active else 0.0
    d5 = (go5_impact or {}).get("defence_modifier", 0.0) if go5_active else 0.0

    angriff, a_clamp = go4.combined_clamp(a4, a5)
    abwehr, d_clamp = go4.combined_clamp(d4, d5)

    return {
        "attack": round(angriff, 6),
        "defence": round(abwehr, 6),
        "clamp_applied": bool(a_clamp or d_clamp),
        "clamped_parts": [n for n, c in (("attack", a_clamp),
                                         ("defence", d_clamp)) if c],
    }


def fixture_snapshot(home_team_ids, away_team_ids, league_features,
                     home_apisports_id=None, away_apisports_id=None,
                     events=None, cutoff_date=None, season=None,
                     competition_code=None, as_of=None,
                     home_absences=None, away_absences=None,
                     home_timeline=None, away_timeline=None, cutoff=None,
                     home_profile=None, away_profile=None, k=None):
    """
    Der vollstaendige GO-4-/GO-5-Stand fuer EINE Begegnung.

    Einmal vor der Simulation gebaut, danach unveraendert weitergereicht.
    Enthaelt beide Staende - Ausgangswerte und korrigierte - damit der
    Schattenmodus vergleichen kann und der aktive Modus nichts
    nachrechnen muss.
    """
    go4_modus = go4.current_mode()
    go5_modus = go5.current_mode()
    go4_aktiv = go4_modus == "active"
    go5_aktiv = go5_modus == "active"

    seiten = {}
    for name, team_ids, as_id, ausfaelle, timeline, profil in (
        ("home", home_team_ids, home_apisports_id, home_absences,
         home_timeline, home_profile),
        ("away", away_team_ids, away_apisports_id, away_absences,
         away_timeline, away_profile),
    ):
        if go4_modus == "off":
            go4_teil = {"availability": {"available": False, "reason": "mode_off"},
                        "modifier": go4.compute_modifier(None),
                        "absent_player_ids": []}
        elif ausfaelle is not None or as_of is None:
            go4_teil = team_go4_features_with_absences(
                team_ids, league_features, ausfaelle, as_of=as_of)
        else:
            go4_teil = team_go4_features(
                team_ids, league_features, competition_code, season, as_of)

        if go5_modus == "off":
            go5_teil = {"impact": go5.empty_impact("mode_off"),
                        "incoming": [], "outgoing": []}
        else:
            go5_teil = team_go5_features(
                as_id, league_features, events, cutoff_date, season,
                timeline=timeline, cutoff=cutoff,
                # Die Doppelzaehlungssperre: Wer als ausgefallen gilt,
                # wirkt nicht zusaetzlich als Transfer.
                excluded_player_ids=go4_teil["absent_player_ids"], k=k)

        zusammen = combine(go4_teil["modifier"], go5_teil["impact"],
                           go4_aktiv, go5_aktiv)

        korrigiert = profil
        if profil is not None:
            if zusammen["attack"] or zusammen["defence"]:
                korrigiert = go4.apply_modifier(
                    profil, zusammen["attack"], zusammen["defence"])
            else:
                korrigiert = dict(profil)

        seiten[name] = {
            "go4": go4_teil,
            "go5": go5_teil,
            "combined": zusammen,
            "baseline_profile": profil,
            "adjusted_profile": korrigiert,
        }

    return {
        "go4_mode": go4_modus,
        "go5_mode": go5_modus,
        "go4_applied": go4_aktiv,
        "go5_applied": go5_aktiv,
        "applied": go4_aktiv or go5_aktiv,
        "home": seiten["home"],
        "away": seiten["away"],
        "league_coverage": {
            "pool_size": league_features.get("pool_size"),
            "snapshot_season": league_features.get("snapshot_season"),
            "importance": league_features.get("importance_coverage"),
            "quality": league_features.get("quality_coverage"),
        },
    }


# ---------------------------------------------------------------------------
# API- und Diagnosedaten
# ---------------------------------------------------------------------------

def _go4_block(seite):
    """Die zeigbaren GO-4-Felder einer Mannschaft."""
    verf = seite["go4"]["availability"]
    mod = seite["go4"]["modifier"]
    block = {
        "attack_modifier": mod["attack_modifier"],
        "defence_modifier": mod["defence_modifier"],
        "goalkeeper_modifier": mod["goalkeeper_modifier"],
        "data_quality": mod["data_quality"],
        "clamp_applied": mod["clamp_applied"],
        "reason": mod.get("reason"),
        "available": bool(verf.get("available")),
        "snapshot_timestamp": verf.get("snapshot_timestamp"),
        "as_of": verf.get("as_of"),
    }
    if verf.get("available"):
        block.update({
            "availability_attack": verf["availability_attack"],
            "availability_midfield": verf["availability_midfield"],
            "availability_defence": verf["availability_defence"],
            "availability_goalkeeper": verf["availability_goalkeeper"],
            "overall_availability": verf["overall_availability"],
            "unavailable_players": [
                {"player_id": s["player_id"], "player_name": s["player_name"],
                 "status": s["status"], "importance": s["importance"]}
                for s in (verf.get("unavailable_players") or [])
            ],
            "unavailable_importance": verf.get("unavailable_importance"),
            "replacement_quality": {
                pos: (verf["positions"].get(pos) or {}).get("replacement_quality")
                for pos in ("Goalkeeper", "Defender", "Midfielder", "Attacker")
            },
        })
    return block


def _go5_block(seite):
    """Die zeigbaren GO-5-Felder einer Mannschaft."""
    wirkung = seite["go5"]["impact"]
    return {
        "attack_modifier": wirkung["attack_modifier"],
        "defence_modifier": wirkung["defence_modifier"],
        "net_attack_impact": wirkung["net_attack_transfer_impact"],
        "net_defence_impact": wirkung["net_defence_transfer_impact"],
        "incoming_impact": {
            "attack": wirkung["incoming_attack_impact"],
            "defence": wirkung["incoming_defence_impact"],
            "goalkeeper": wirkung["incoming_goalkeeper_impact"],
        },
        "outgoing_impact": {
            "attack": wirkung["outgoing_attack_impact"],
            "defence": wirkung["outgoing_defence_impact"],
            "goalkeeper": wirkung["outgoing_goalkeeper_impact"],
        },
        "lambda_transfer": wirkung["lambda_transfer"],
        "season_matches_played": wirkung["season_matches_played"],
        "k_transfer": wirkung["k_transfer"],
        "relevant_transfers": wirkung["number_of_usable_transfers"],
        "transfers_seen": wirkung["transfers_seen"],
        "by_transfer_type": wirkung["by_transfer_type"],
        "excluded_as_absent": wirkung["transfers_excluded_as_absent"],
        "data_quality": wirkung["transfer_data_quality"],
        "clamp_applied": wirkung["clamp_applied"],
        "reason": wirkung.get("reason"),
    }


def api_metadata(snapshot):
    """
    Der GO-4-/GO-5-Block fuer die API-Antwort.

    BEWUSST OHNE Pfade, Umgebungswerte, Schluessel, Anbieterantworten
    und Stacktraces. Wirft nicht: Eine fehlende Datenlage ist ein
    Zustand, kein Fehler, und darf keinen HTTP 500 erzeugen.
    """
    if not snapshot:
        return {
            "go4": {"mode": go4.current_mode(), "applied": False,
                    "available": False, "reason": "no_snapshot"},
            "go5": {"mode": go5.current_mode(), "applied": False,
                    "available": False, "reason": "no_snapshot"},
        }

    try:
        return {
            "go4": {
                "mode": snapshot["go4_mode"],
                "applied": snapshot["go4_applied"],
                "available": True,
                "home": _go4_block(snapshot["home"]),
                "away": _go4_block(snapshot["away"]),
            },
            "go5": {
                "mode": snapshot["go5_mode"],
                "applied": snapshot["go5_applied"],
                "available": True,
                "home": _go5_block(snapshot["home"]),
                "away": _go5_block(snapshot["away"]),
            },
            "combined": {
                "home": snapshot["home"]["combined"],
                "away": snapshot["away"]["combined"],
                "max_combined_effect": go4.CONSTANTS["MAX_COMBINED_GO4_GO5"]["wert"],
            },
            "coverage": snapshot.get("league_coverage"),
        }
    except (KeyError, TypeError):
        return {
            "go4": {"mode": go4.current_mode(), "applied": False,
                    "available": False, "reason": "incomplete_snapshot"},
            "go5": {"mode": go5.current_mode(), "applied": False,
                    "available": False, "reason": "incomplete_snapshot"},
        }


def safe_fixture_snapshot(*args, **kwargs):
    """
    fixture_snapshot, das im Fehlerfall None liefert statt zu werfen.

    GO 4 und GO 5 sind Ergaenzungen. Fallen sie aus, muss die Simulation
    trotzdem ein vollstaendiges Ergebnis liefern - ohne Korrektur. Eine
    funktionierende Vorhersage wegen einer fehlenden Nebenangabe zu
    verweigern waere die schlechtere Wahl.
    """
    try:
        return fixture_snapshot(*args, **kwargs)
    except Exception:
        return None
