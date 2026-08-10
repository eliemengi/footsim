"""
Auswirkung von Kader und Ausfaellen auf die Teamstaerke.

Datenquelle ist API-Sports, das football-data.org an dieser Stelle
ergaenzt: Spielerstatistiken und Verletzungen gibt es dort nicht.

Budgetproblem und Loesung
-------------------------
Der API-Sports-Free-Plan erlaubt 100 Requests pro Tag. Kaderdaten je Team
abzufragen waere aussichtslos: 5 Ligen mal 20 Teams sind allein 100
Requests fuer einen einzigen Durchlauf.

Deshalb werden ausschliesslich LIGAWEITE Endpoints benutzt:

    /players/topscorers?league=X&season=Y   1 Request  -> beste Torschuetzen
    /injuries?league=X&season=Y             1 Request  -> alle Ausfaelle

Das sind 2 Requests pro Liga, also 10 fuer alle fuenf. Zusammen mit dem
persistenten Cache (12 Stunden) bleibt der Verbrauch bei etwa 20 Requests
pro Tag - ein Fuenftel des Budgets.

Wie der Modifikator entsteht
----------------------------
Nachvollziehbar in drei Schritten:

1. Aus den Torschuetzenlisten wird ermittelt, welchen Anteil ein Spieler
   an den Toren SEINES Teams hat. Ein Stuermer mit 12 von 40 Teamtoren
   traegt 30 % der Offensive.

2. Aus den Verletzungsdaten wird geprueft, welche dieser Spieler aktuell
   ausfallen.

3. Der Offensivwert des Teams wird um den fehlenden Toranteil reduziert,
   allerdings gedaempft: Ein Ausfall wird teilweise vom Ersatz aufgefangen.
   Der Daempfungsfaktor ist REPLACEMENT_FACTOR.

Beispiel: Faellt ein Spieler mit 30 % Toranteil aus, ergibt das bei einem
Daempfungsfaktor von 0.5 einen Malus von 15 % auf die Offensive.

Grenzen dieses Ansatzes
-----------------------
Erfasst werden nur Spieler, die in der Torschuetzenliste auftauchen, also
im Wesentlichen die Offensive. Ausfaelle von Verteidigern oder Torhuetern
bleiben unberuecksichtigt - dafuer waeren Kaderdaten je Team noetig, die
das Budget nicht hergibt. Der Defensivwert wird deshalb bewusst NICHT
angefasst, statt ihn auf duenner Basis zu raten.
"""

from collections import defaultdict

from src.utils.disk_cache import disk_cached_call
from src.utils.cache import TTL_APISPORTS_INJURIES


# Wie stark ein Ausfall aufgefangen wird. 0.0 hiesse, der Spieler ist
# unersetzlich; 1.0 hiesse, der Ersatz ist gleichwertig. 0.5 unterstellt,
# dass ein Ersatzspieler etwa die Haelfte der Leistung bringt.
REPLACEMENT_FACTOR = 0.5

# Obergrenze fuer den Malus. Auch wenn rechnerisch mehr herauskaeme,
# bricht eine Mannschaft nicht um mehr als diesen Anteil ein - der Rest
# des Kaders spielt weiter.
MAX_ATTACK_PENALTY = 0.25

# Verletzungstypen, die als echter Ausfall gelten. API-Sports meldet
# unter "type" teils auch Sperren und fragliche Einsaetze.
OUT_TYPES = {"missing fixture", "out", "injury", "suspended"}


def _empty_impact():
    return {
        "attack_modifier": 1.0,
        "missing_goal_share": 0.0,
        "missing_players": [],
        "data_available": False,
    }


def build_scorer_share(scorers):
    """
    Ermittelt je Spieler seinen Anteil an den Toren seines Teams.

    scorers: Liste aus apisports_api.get_top_scorers(), jeweils mit
             player_id, player_name, team_id, goals

    Rueckgabe: { player_id: {"team_id", "player_name", "goals", "share"} }

    Wichtig: Der Anteil bezieht sich auf die Tore, die in der Liste
    auftauchen, nicht auf alle Teamtore. Er ist damit eine Obergrenze der
    tatsaechlichen Bedeutung. Da nur die besten Torschuetzen gelistet
    sind, deckt die Liste den Grossteil der Offensive ab.
    """
    if not scorers:
        return {}

    team_goals = defaultdict(int)
    for entry in scorers:
        team_id = entry.get("team_id")
        goals = entry.get("goals") or 0
        if team_id is not None:
            team_goals[team_id] += goals

    shares = {}
    for entry in scorers:
        player_id = entry.get("player_id")
        team_id = entry.get("team_id")
        goals = entry.get("goals") or 0

        if player_id is None or team_id is None:
            continue

        total = team_goals.get(team_id, 0)
        share = (goals / total) if total > 0 else 0.0

        shares[player_id] = {
            "team_id": team_id,
            "player_name": entry.get("player_name"),
            "goals": goals,
            "share": share,
        }

    return shares


def collect_absences(injuries):
    """
    Filtert aus den Verletzungsmeldungen die echten Ausfaelle.

    injuries: Liste aus apisports_api.get_injuries()
    Rueckgabe: { player_id: {"team_id", "player_name", "reason"} }

    Fragliche Einsaetze ("questionable") werden bewusst ignoriert: Sie
    wuerden das Ergebnis verwaessern, weil die meisten dieser Spieler
    letztlich auflaufen.
    """
    if not injuries:
        return {}

    absent = {}

    for entry in injuries:
        player_id = entry.get("player_id")
        if player_id is None:
            continue

        raw_type = (entry.get("type") or entry.get("reason") or "").strip().lower()

        # Nur eindeutige Ausfaelle beruecksichtigen.
        if raw_type and not any(token in raw_type for token in OUT_TYPES):
            continue

        absent[player_id] = {
            "team_id": entry.get("team_id"),
            "player_name": entry.get("player_name"),
            "reason": entry.get("reason") or entry.get("type"),
        }

    return absent


def compute_team_impact(scorers, injuries):
    """
    Berechnet je Team, wie sehr Ausfaelle die Offensive schwaechen.

    Rueckgabe: { team_id: {attack_modifier, missing_goal_share,
                           missing_players, data_available} }

    attack_modifier ist ein Faktor um 1.0: 0.9 bedeutet 10 Prozent
    weniger Offensivkraft. Er wird spaeter auf attack_home und
    attack_away multipliziert.
    """
    shares = build_scorer_share(scorers)
    absent = collect_absences(injuries)

    if not shares:
        return {}

    impact = {}

    # Grundzustand: jedes Team in der Torschuetzenliste ist unbeeintraechtigt.
    for info in shares.values():
        team_id = info["team_id"]
        if team_id not in impact:
            impact[team_id] = {
                "attack_modifier": 1.0,
                "missing_goal_share": 0.0,
                "missing_players": [],
                "data_available": True,
            }

    # Fehlende Torschuetzen aufaddieren.
    for player_id, absence in absent.items():
        info = shares.get(player_id)
        if not info:
            # Spieler taucht nicht in der Torschuetzenliste auf, sein
            # Ausfall ist offensiv nicht messbar.
            continue

        team_id = info["team_id"]
        entry = impact.setdefault(team_id, {
            "attack_modifier": 1.0, "missing_goal_share": 0.0,
            "missing_players": [], "data_available": True,
        })

        entry["missing_goal_share"] += info["share"]
        entry["missing_players"].append({
            "player_name": info["player_name"],
            "goals": info["goals"],
            "share": round(info["share"], 3),
            "reason": absence.get("reason"),
        })

    # Aus dem fehlenden Toranteil den Faktor bilden.
    for entry in impact.values():
        penalty = entry["missing_goal_share"] * (1.0 - REPLACEMENT_FACTOR)
        penalty = min(penalty, MAX_ATTACK_PENALTY)
        entry["attack_modifier"] = round(1.0 - penalty, 3)
        entry["missing_goal_share"] = round(entry["missing_goal_share"], 3)

    return impact


def _normalize_team_keys(impact):
    """
    Stellt sicher, dass die Team-IDs Zahlen sind.

    Notwendig wegen des Disk-Caches: JSON kennt nur Zeichenketten als
    Objektschluessel. Frisch berechnet kaeme {10: ...} zurueck, aus dem
    Cache gelesen aber {"10": ...}. apply_impact() schlaegt mit der
    numerischen team_id aus der Tabelle nach und faende danach nichts
    mehr - die Kaderwirkung waere ab dem ersten Cache-Treffer still
    verschwunden, waehrend squad_data_applied weiterhin True meldet.

    IDs, die sich nicht in eine Zahl wandeln lassen, bleiben unveraendert
    erhalten, statt sie zu verwerfen.
    """
    if not isinstance(impact, dict):
        return {}

    normalized = {}
    for team_id, entry in impact.items():
        try:
            normalized[int(team_id)] = entry
        except (TypeError, ValueError):
            normalized[team_id] = entry

    return normalized


def get_squad_impact(competition_code, season=None):
    """
    Holt Torschuetzen und Ausfaelle einer Liga und berechnet die Wirkung.

    Kostet zwei API-Sports-Requests, danach zwoelf Stunden aus dem
    persistenten Cache. Schlaegt der Abruf fehl, wird ein leeres Ergebnis
    zurueckgegeben - die Simulation laeuft dann ohne diesen Faktor
    weiter, statt auszufallen.

    Die Rueckgabe hat garantiert numerische Team-IDs als Schluessel,
    unabhaengig davon, ob sie frisch berechnet oder aus dem Disk-Cache
    gelesen wurde.
    """
    # Import bewusst hier, damit ein fehlender API-Schluessel nicht schon
    # beim Laden des Moduls stoert.
    try:
        from src.api.apisports_api import (
            get_top_scorers,
            get_injuries,
            CURRENT_SEASON,
            ApisportsUnavailable,
        )
    except ImportError:
        return {}

    season = season or CURRENT_SEASON
    cache_key = f"squad_impact:{competition_code}:{season}"

    def loader():
        scorers, injuries = [], []

        try:
            data = get_top_scorers(competition_code, season=season, limit=40)
            scorers = data.get("scorers", []) if isinstance(data, dict) else (data or [])
        except Exception:
            scorers = []

        try:
            data = get_injuries(competition_code, season=season)
            injuries = data.get("injuries", []) if isinstance(data, dict) else (data or [])
        except Exception:
            injuries = []

        return compute_team_impact(scorers, injuries)

    try:
        cached = disk_cached_call(
            key=cache_key,
            ttl_seconds=TTL_APISPORTS_INJURIES,
            loader=loader,
            source="api-sports",
        )
    except Exception:
        return {}

    return _normalize_team_keys(cached)


def apply_impact(profiles, impact):
    """
    Wendet die Kaderwirkung auf fertige Teamprofile an.

    Veraendert ausschliesslich die Angriffswerte. Die Abwehr bleibt
    unberuehrt, weil die Datengrundlage dafuer nicht ausreicht (siehe
    Modulbeschreibung). Lieber einen Faktor weglassen als ihn erfinden.

    Die Profile werden an Ort und Stelle ergaenzt und zusaetzlich mit
    squad_modifier markiert, damit im Debug sichtbar bleibt, was
    angepasst wurde.
    """
    if not impact:
        return profiles

    for team_id, profile in profiles.items():
        entry = impact.get(team_id)
        if not entry:
            profile["squad_modifier"] = 1.0
            profile["missing_players"] = []
            continue

        modifier = entry.get("attack_modifier", 1.0)
        profile["attack_home"] = profile.get("attack_home", 1.0) * modifier
        profile["attack_away"] = profile.get("attack_away", 1.0) * modifier
        profile["squad_modifier"] = modifier
        profile["missing_players"] = entry.get("missing_players", [])

    return profiles
