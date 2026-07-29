"""
Garantierte Staerkewerte fuer die Einzelspielsimulation.

Das Problem
-----------
Die Einzelspielsimulation (simulate_scores.py) bezieht ihre Werte aus
data/raw/team_matches.json - einer Datei mit 94 Teams, erzeugt aus einer
frueheren Saison. Teams, die seitdem neu in die Ligen kamen (vor allem
Aufsteiger), fehlen dort. Bisher endete jedes Spiel mit so einem Team in
einem ValueError ("Teamdaten fehlen").

Die Regel, die dieses Modul durchsetzt
--------------------------------------
Ein unbekanntes oder historisch nicht zuordenbares Team darf NIEMALS
dazu fuehren, dass ein Spiel abgelehnt wird. Fuer jeden angefragten
Teamnamen liefert ensure_team_strengths() garantiert einen Eintrag:

    Stufe 0  Eintrag existiert bereits in team_matches.json
    Stufe 1  Team ueber Name/Alias in den historischen Saisonprofilen
             gefunden -> Werte daraus abgeleitet
    Stufe 3  nicht gefunden -> empirisches Aufsteigerprofil der Ligen
    Stufe 4  keinerlei historische Basis -> neutraler Durchschnittswert

Die letzte Stufe ist nie None.

Format
------
Die synthetischen Eintraege haben exakt das Schema von
calculate_team_strength() in team_strength.py, damit der restliche
Simulationscode unveraendert funktioniert:

    avg_goals_scored, avg_goals_conceded, points_per_game,
    winrate, matches_used

Die historischen Profile fuehren all diese Kennzahlen bereits mit
(goals_for_per_game usw.) - es ist eine reine Uebersetzung, keine
Erfindung neuer Werte.
"""

import threading

from src.data.historical_loader import LEAGUE_CODES, load_available_seasons
from src.features.team_profile import (
    build_season_profiles,
    blend_profiles,
    neutral_profile,
)
from src.features.strength_provider import (
    normalize_name,
    _alias_candidates,
    compute_promoted_profile,
)


_lock = threading.Lock()
_cache = {"built": False, "by_name": {}, "promoted": None}


def _reset_cache():
    """Fuer Tests: erzwingt Neuaufbau des Namensindex."""
    with _lock:
        _cache["built"] = False
        _cache["by_name"] = {}
        _cache["promoted"] = None


def _build_index():
    """
    Baut einen Namensindex ueber die historischen Profile ALLER Ligen.

    Die Einzelspielansicht kennt nur Teamnamen, keine Liga - deshalb wird
    ligauebergreifend gesucht. Die Profile sind auf den jeweiligen
    Ligadurchschnitt normiert und dadurch vergleichbar (genau dafuer
    wurde die Normalisierung in team_profile.py gebaut).
    """
    by_name = {}
    promoted_profiles = []

    for api_code in LEAGUE_CODES.values():
        loaded = load_available_seasons(api_code)
        if not loaded:
            continue

        season_profiles = [build_season_profiles(p) for _, p in loaded]
        blended = blend_profiles(season_profiles)

        promoted, _source = compute_promoted_profile(season_profiles)
        promoted_profiles.append(promoted)

        for profile in blended.values():
            for candidate in (profile.get("team_name"), profile.get("short_name")):
                key = normalize_name(candidate)
                if key and key not in by_name:
                    by_name[key] = profile

    # Ligauebergreifender Aufsteiger-Mittelwert als vorletzte Stufe.
    if promoted_profiles:
        keys = ("attack_home", "attack_away", "defence_home", "defence_away",
                "points_per_game", "goals_for_per_game",
                "goals_against_per_game", "win_rate")
        promoted_avg = dict(promoted_profiles[0])
        for key in keys:
            promoted_avg[key] = sum(p[key] for p in promoted_profiles) / len(promoted_profiles)
        promoted_avg["matches_used"] = 0
    else:
        promoted_avg = None

    return by_name, promoted_avg


def _ensure_index():
    with _lock:
        if not _cache["built"]:
            by_name, promoted = _build_index()
            _cache["by_name"] = by_name
            _cache["promoted"] = promoted
            _cache["built"] = True
        return _cache["by_name"], _cache["promoted"]


def _to_legacy(profile, source):
    """Uebersetzt ein historisches Profil ins team_strength-Schema."""
    return {
        "avg_goals_scored": round(float(profile.get("goals_for_per_game", 1.35)), 3),
        "avg_goals_conceded": round(float(profile.get("goals_against_per_game", 1.35)), 3),
        "points_per_game": round(float(profile.get("points_per_game", 1.35)), 3),
        "winrate": round(float(profile.get("win_rate", 0.33)), 3),
        "matches_used": int(profile.get("matches_used", 0) or 0),
        "source": source,
    }


def resolve_profile_by_name(team_name):
    """
    Sucht ein historisches Profil ueber Name und Aliase.

    Rueckgabe: (profil, "historical") oder (None, None).
    """
    by_name, _promoted = _ensure_index()

    for candidate in _alias_candidates(team_name):
        key = normalize_name(candidate)
        profile = by_name.get(key)
        if profile:
            return profile, "historical"

    return None, None


def ensure_team_strengths(strengths, team_names):
    """
    Garantiert fuer jeden Namen in team_names einen Eintrag in strengths.

    Veraendert das Dict an Ort und Stelle und gibt zusaetzlich je Team
    zurueck, woher der Wert stammt - fuer Diagnose und API-Antwort.

    Rueckgabe: (strengths, info) mit
        info[name] = {"resolved_by": ..., "fallback_level": 0|1|3|4}
    """
    info = {}

    for name in team_names:
        if not name:
            continue

        if name in strengths:
            info[name] = {"resolved_by": "team_matches", "fallback_level": 0}
            continue

        profile, source = resolve_profile_by_name(name)
        if profile is not None:
            strengths[name] = _to_legacy(profile, "historical_profile")
            info[name] = {"resolved_by": "historical_profile", "fallback_level": 1}
            continue

        _by_name, promoted = _ensure_index()
        if promoted is not None:
            strengths[name] = _to_legacy(promoted, "promoted_profile")
            info[name] = {"resolved_by": "promoted_profile", "fallback_level": 3}
            continue

        # Absoluter Notfall: neutraler Durchschnitt. Nie None.
        strengths[name] = _to_legacy(neutral_profile(None, name), "neutral")
        info[name] = {"resolved_by": "neutral", "fallback_level": 4}

    return strengths, info
