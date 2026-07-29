"""
Zentrale Beschaffung der Teamstaerken.

Dieses Modul beantwortet genau eine Frage:
"Wie stark ist Team X in Liga Y zum jetzigen Zeitpunkt - und woher weiss
ich das?"

Es fuehrt zusammen, was die anderen Module liefern:

    historical_loader  -> Rohdaten abgeschlossener Saisons
    team_profile       -> Attack/Defence-Ratings daraus
    dynamic_weights    -> Mischung Historie / laufende Saison

Fallback-Kaskade
----------------
Fuer jedes Team wird der erste Treffer dieser Reihenfolge genommen. Die
erreichte Stufe wird als fallback_level mitgefuehrt, damit im Debug
sichtbar ist, wie belastbar der Wert ist:

    Stufe 0  Team-ID in der Historie gefunden          (bester Fall)
    Stufe 1  ueber normalisierten Namen / Alias gefunden
    Stufe 2  keine Historie, aber Spiele der laufenden Saison
    Stufe 3  Aufsteiger: empirisches Aufsteigerprofil der Liga
    Stufe 4  Liga-Neutralwert                          (letzter Ausweg)

Empirisches Aufsteigerprofil
----------------------------
Aufsteiger bekommen NICHT einfach den Ligadurchschnitt. Aus zwei
aufeinanderfolgenden Saisons laesst sich messen, wie Aufsteiger
tatsaechlich abschneiden: Wer in Saison N in der Liga spielte, aber in
Saison N-1 nicht, war ein Aufsteiger. Der Mittelwert genau dieser Teams
ist der Erwartungswert fuer kuenftige Aufsteiger.

Damit ist der Aufsteigerwert aus echten Daten abgeleitet und nicht
geraten. Fehlen die Daten fuer diese Rechnung, wird auf einen
konservativen Abschlag zurueckgegriffen, der als solcher markiert wird.
"""

import unicodedata
from collections import defaultdict

from src.data.historical_loader import (
    LEAGUE_CODES,
    AVAILABLE_HISTORICAL_SEASONS,
    load_available_seasons,
)
from src.features.team_profile import (
    build_season_profiles,
    blend_profiles,
    league_averages,
    neutral_profile,
    collect_team_stats,
    NEUTRAL_RATING,
)
from src.features.dynamic_weights import blend_profile, confidence_level
from src.utils.team_aliases import TEAM_ALIASES


# Wenn kein empirisches Aufsteigerprofil berechnet werden kann, gilt
# dieser Abschlag. Aufsteiger sind im Mittel schwaecher als der Rest der
# Liga - der Wert ist bewusst massvoll, damit sie nicht vorverurteilt
# werden. Wird nur bei fehlender Datengrundlage benutzt.
FALLBACK_PROMOTED_ATTACK = 0.88
FALLBACK_PROMOTED_DEFENCE = 1.14

# Ab dieser Anzahl beobachteter Aufsteiger gilt der empirische Mittelwert
# als voll belastbar. Darunter wird er anteilig Richtung Schaetzwert
# gezogen (siehe compute_promoted_profile). Drei entspricht der ueblichen
# Zahl von Aufsteigern pro Saison in den Top-Ligen.
PROMOTED_SAMPLE_TARGET = 3


def normalize_name(name):
    """
    Vereinheitlicht einen Teamnamen fuer den Vergleich.

    'FC Bayern München' -> 'bayern munchen'
    'Bayern'            -> 'bayern'

    Entfernt Akzente, Rechtsformen und Satzzeichen. Dient nur als
    Notbehelf, wenn keine Team-ID vorliegt. Die ID ist immer besser.
    """
    if not name:
        return ""

    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()

    for token in (" fc", "fc ", " cf", "cf ", " sc", "sc ", " ac", "ac ",
                  " bv", " sv", "sv ", " vfb", " vfl", " tsg", " rb ",
                  " 1. ", " calcio", " ssc", " as ", " ss ", " ogc",
                  " afc", " ufc", " club", " cd ", " rcd", " ca "):
        text = text.replace(token, " ")

    for ch in ".,-_'`&()/":
        text = text.replace(ch, " ")

    return " ".join(text.split())


def _build_name_index(profiles):
    """Baut einen Suchindex normalisierter Namen auf Team-Profile."""
    index = {}
    for team_id, profile in profiles.items():
        for candidate in (profile.get("team_name"), profile.get("short_name")):
            key = normalize_name(candidate)
            if key and key not in index:
                index[key] = team_id
    return index


def _alias_candidates(team_name):
    """Alle Schreibweisen, unter denen ein Team bekannt sein koennte."""
    candidates = {team_name}

    mapped = TEAM_ALIASES.get(team_name)
    if mapped:
        candidates.add(mapped)

    # Auch die Rueckrichtung: steht der Name als Wert im Alias-Dict,
    # sind alle zugehoerigen Schluessel ebenfalls gueltige Schreibweisen.
    for key, value in TEAM_ALIASES.items():
        if value == team_name:
            candidates.add(key)

    return {c for c in candidates if c}


def compute_promoted_profile(season_profile_list):
    """
    Misst empirisch, wie Aufsteiger in dieser Liga abschneiden.

    season_profile_list: Saisonprofile, NEUESTE ZUERST.
    Benoetigt mindestens zwei Saisons: Teams, die in der neueren Saison
    vorkommen, in der aelteren aber nicht, waren Aufsteiger. Ihr
    Durchschnitt ist der Erwartungswert.

    Rueckgabe: (profil_dict, quelle) - quelle ist 'empirisch' oder
    'geschaetzt', damit der Ursprung nachvollziehbar bleibt.
    """
    if len(season_profile_list) < 2:
        return _estimated_promoted_profile(), "geschaetzt"

    newer = season_profile_list[0]["profiles"]
    older = season_profile_list[1]["profiles"]

    promoted_ids = [tid for tid in newer if tid not in older]

    if not promoted_ids:
        return _estimated_promoted_profile(), "geschaetzt"

    keys = ("attack_home", "attack_away", "defence_home", "defence_away",
            "points_per_game", "goals_for_per_game", "goals_against_per_game",
            "win_rate")

    profile = {
        "team_id": None,
        "team_name": "Aufsteiger (Ligamittel)",
        "short_name": None,
        "crest": None,
        "seasons_used": [season_profile_list[0].get("season")],
        "seasons_count": 1,
        "matches_used": sum(newer[tid]["matches_used"] for tid in promoted_ids),
        "sample_teams": len(promoted_ids),
    }

    for key in keys:
        profile[key] = sum(newer[tid][key] for tid in promoted_ids) / len(promoted_ids)

    # Kleine Stichprobe absichern.
    # Typisch steigen 2-3 Teams pro Saison auf. Liegt nur ein einzelnes
    # Team vor, ist dessen Saison zu einem grossen Teil Zufall - ein
    # ueberraschend starker Aufsteiger wuerde sonst zum Massstab fuer alle
    # kuenftigen. Deshalb dieselbe Shrinkage wie bei den Team-Ratings:
    # Richtung konservativer Schaetzung ziehen, gewichtet nach Stichprobe.
    sample = len(promoted_ids)
    if sample < PROMOTED_SAMPLE_TARGET:
        estimated = _estimated_promoted_profile()
        w_empirical = sample / PROMOTED_SAMPLE_TARGET
        for key in keys:
            profile[key] = (
                w_empirical * profile[key]
                + (1.0 - w_empirical) * estimated[key]
            )
        profile["shrunk_to_estimate"] = round(1.0 - w_empirical, 2)

    return profile, "empirisch"


def _estimated_promoted_profile():
    """Konservative Schaetzung, wenn keine empirische Basis vorliegt."""
    profile = neutral_profile(None, "Aufsteiger (geschaetzt)")
    profile["attack_home"] = FALLBACK_PROMOTED_ATTACK
    profile["attack_away"] = FALLBACK_PROMOTED_ATTACK
    profile["defence_home"] = FALLBACK_PROMOTED_DEFENCE
    profile["defence_away"] = FALLBACK_PROMOTED_DEFENCE
    profile["points_per_game"] = 1.10
    profile["win_rate"] = 0.26
    profile["sample_teams"] = 0
    return profile


def build_current_season_profiles(finished_matches, teams_lookup=None):
    """
    Baut Profile aus den bereits gespielten Partien der LAUFENDEN Saison.

    finished_matches: Liste im Format des historical_loader
                      (home_id, away_id, home_goals, away_goals)
    Gibt None zurueck, wenn noch nichts gespielt wurde - dann traegt
    ausschliesslich die Historie.
    """
    if not finished_matches:
        return None

    payload = {
        "meta": {"season": "current", "api_code": None},
        "teams": teams_lookup or {},
        "matches": finished_matches,
    }
    return build_season_profiles(payload)


def get_league_strengths(
    league_key,
    standings_table,
    current_matches=None,
    seasons=None,
    use_squad_data=True,
    current_season=None,
):
    """
    Liefert fuer jedes Team der Tabelle ein einsatzbereites Profil.

    league_key:      'bl1', 'pl', ...
    standings_table: aktuelle Tabelle (mit team_id, team_name, played)
    current_matches: bereits gespielte Partien der laufenden Saison
                     (optional; ohne sie zaehlt nur die Historie)
    current_season:  Jahr der laufenden Saison (z. B. 2026). Wird fuer
                     die Aufsteiger-Erkennung gebraucht: Aufsteiger ist,
                     wer JETZT in der Liga spielt, aber in der
                     unmittelbaren Vorsaison (current_season - 1) nicht.

    Rueckgabe:
    {
      "profiles":   { team_id: profil },
      "league_avg": {...},
      "coverage":   [ {team_name, fallback_level, data_source, ...} ],
      "summary":    {...}
    }
    """
    api_code = LEAGUE_CODES.get(league_key, league_key.upper())
    seasons = seasons or AVAILABLE_HISTORICAL_SEASONS

    # 1. Historie laden und zu einem Gesamtprofil verschmelzen.
    loaded = load_available_seasons(api_code, seasons)
    season_profiles = [build_season_profiles(payload) for _, payload in loaded]
    historical = blend_profiles(season_profiles) if season_profiles else {}

    # Aufsteiger-Erkennung: NUR ueber die Teilnehmerliste der unmittelbaren
    # Vorsaison. "Keine Historie gefunden" ist ausdruecklich KEIN Beleg
    # fuer einen Aufstieg - das kann genauso ein Datenluecken- oder
    # Mapping-Problem sein. Liegt die Vorsaison lokal nicht vor, bleibt
    # der Status unbekannt (None) statt geraten.
    previous_season_team_ids = None
    previous_season_year = None
    if current_season is not None:
        previous_season_year = current_season - 1
        for loaded_season, payload in loaded:
            if loaded_season == previous_season_year:
                previous_season_team_ids = {
                    int(tid) for tid in (payload.get("teams") or {})
                }
                break

    # Ligadurchschnitt: bevorzugt aus der neuesten Historie-Saison.
    if season_profiles:
        league_avg = dict(season_profiles[0]["league_avg"])
    else:
        league_avg = {"home_goals": 1.50, "away_goals": 1.20,
                      "total_goals": 2.70, "matches": 0}

    name_index = _build_name_index(historical)
    promoted_profile, promoted_source = compute_promoted_profile(season_profiles)

    # 2. Profile der laufenden Saison, falls schon gespielt wurde.
    current_data = build_current_season_profiles(current_matches)
    current_profiles = current_data["profiles"] if current_data else {}

    # Ligadurchschnitt der laufenden Saison nutzen, sobald er belastbar ist.
    if current_data and current_data["league_avg"]["matches"] >= 20:
        league_avg = dict(current_data["league_avg"])

    profiles = {}
    coverage = []

    for row in standings_table:
        team_id = row.get("team_id")
        team_name = row.get("team_name") or ""
        played = row.get("played") or 0

        hist_profile = None
        fallback_level = 0
        data_source = "history_id"
        alias_used = None

        # --- Stufe 0: Treffer ueber Team-ID ---
        if team_id is not None and team_id in historical:
            hist_profile = historical[team_id]

        # --- Stufe 1: Treffer ueber normalisierten Namen / Alias ---
        if hist_profile is None:
            for candidate in _alias_candidates(team_name):
                key = normalize_name(candidate)
                match_id = name_index.get(key)
                if match_id is not None:
                    hist_profile = historical[match_id]
                    fallback_level = 1
                    data_source = "history_name"
                    alias_used = candidate
                    break

        has_historical_data = hist_profile is not None

        # Aufsteiger-Status: STRIKT getrennt von der Datenverfuegbarkeit.
        #   True   Team fehlt in der Teilnehmerliste der Vorsaison
        #   False  Team war in der Vorsaison dabei
        #   None   Vorsaison-Daten liegen nicht vor -> Status unbekannt
        # Ein Team KANN Aufsteiger sein und trotzdem aeltere
        # Erstliga-Historie besitzen (Wiederaufsteiger) - beides gilt.
        if previous_season_team_ids is not None and team_id is not None:
            is_promoted = team_id not in previous_season_team_ids
        else:
            is_promoted = None

        # --- Stufe 2: keine Historie, aber laufende Saison ---
        if hist_profile is None and team_id in current_profiles:
            fallback_level = 2
            data_source = "current_season_only"

        # --- Stufe 3: bestaetigter Aufsteiger ohne eigene Historie ---
        # Das empirische Aufsteigerprofil greift nur, wenn der Aufstieg
        # ueber die Vorsaison-Teilnehmerliste BELEGT ist. "Historie fehlt"
        # allein reicht nicht - dann waere jedes Datenloch ein Aufsteiger.
        if (hist_profile is None and team_id not in current_profiles
                and is_promoted is True):
            hist_profile = dict(promoted_profile)
            hist_profile["team_id"] = team_id
            hist_profile["team_name"] = team_name
            fallback_level = 3
            data_source = (
                "promoted_empirical" if promoted_source == "empirisch"
                else "promoted_estimated"
            )

        # --- Stufe 4: keine Daten, Aufstieg nicht belegbar -> Neutralwert ---
        if hist_profile is None and team_id not in current_profiles:
            hist_profile = neutral_profile(team_id, team_name)
            fallback_level = 4
            data_source = "league_neutral"

        # 3. Historie und laufende Saison nach Spielzahl mischen.
        curr_profile = current_profiles.get(team_id)
        merged = blend_profile(hist_profile, curr_profile, played)

        # Garantie der Fallback-Kette: Der letzte Schritt ist niemals None.
        if merged is None:
            merged = neutral_profile(team_id, team_name)
            fallback_level = 4
            data_source = "league_neutral"

        # Stammdaten aus der Tabelle haben Vorrang: sie sind aktuell.
        merged["team_id"] = team_id
        merged["team_name"] = team_name
        if row.get("crest"):
            merged["crest"] = row["crest"]

        confidence = confidence_level(
            matches_played=played,
            has_history=has_historical_data,
            fallback_level=fallback_level,
        )

        merged["data_source"] = data_source
        merged["fallback_level"] = fallback_level
        merged["alias_used"] = alias_used
        merged["confidence"] = confidence["score"]
        merged["confidence_level"] = confidence["level"]
        merged["season_data_available"] = bool(curr_profile)
        merged["is_promoted"] = is_promoted
        merged["has_historical_data"] = has_historical_data

        profiles[team_id] = merged

        coverage.append({
            "team_id": team_id,
            "team_name": team_name,
            "data_source": data_source,
            "fallback_level": fallback_level,
            "alias_used": alias_used,
            "matched_by_alias": alias_used is not None,
            "is_promoted": is_promoted,
            "has_historical_data": has_historical_data,
            "season_data_available": bool(curr_profile),
            "historical_seasons": merged.get("seasons_count", 0),
            "matches_used": merged.get("matches_used", 0),
            "current_matches_played": played,
            "confidence": confidence["score"],
            "confidence_level": confidence["level"],
        })

    # 4. Kaderwirkung aus API-Sports, falls verfuegbar.
    # Bewusst als letzter Schritt und streng optional: Faellt die Quelle
    # aus, bleibt alles andere unveraendert nutzbar.
    squad_applied = False
    if use_squad_data:
        try:
            from src.features.squad_impact import get_squad_impact, apply_impact

            impact = get_squad_impact(league_key)
            if impact:
                apply_impact(profiles, impact)
                squad_applied = True

                # Coverage nachtragen, damit der Einfluss sichtbar ist.
                for entry in coverage:
                    team_impact = impact.get(entry["team_id"])
                    entry["squad_modifier"] = (
                        team_impact.get("attack_modifier", 1.0) if team_impact else 1.0
                    )
                    entry["missing_players"] = (
                        team_impact.get("missing_players", []) if team_impact else []
                    )
        except Exception:
            # Kaderdaten sind eine Zugabe, kein Muss.
            squad_applied = False

    summary = _coverage_summary(coverage, len(loaded), promoted_source)
    summary["squad_data_applied"] = squad_applied
    summary["previous_season_available"] = previous_season_team_ids is not None
    summary["previous_season_year"] = previous_season_year
    summary["historical_season_years"] = [s for s, _ in loaded]

    return {
        "profiles": profiles,
        "league_avg": league_avg,
        "coverage": coverage,
        "summary": summary,
    }


def _coverage_summary(coverage, historical_seasons_loaded, promoted_source):
    """Verdichtet die Coverage-Liste zu Kennzahlen fuer Frontend und Report."""
    total = len(coverage)
    if total == 0:
        return {
            "teams_total": 0, "teams_with_history": 0,
            "teams_without_history": 0, "teams_promoted": 0,
            "teams_promoted_unknown": 0,
            "teams_neutral": 0, "historical_seasons": historical_seasons_loaded,
            "avg_confidence": 0.0, "reliable": False,
            "promoted_source": promoted_source,
        }

    with_history = sum(1 for c in coverage if c.get("has_historical_data"))
    # Echte Aufsteiger: nur ueber die Vorsaison-Teilnehmerliste belegt.
    # Teams ohne Historie sind ein getrenntes Merkmal (Datenluecke),
    # sonst wuerden vier oder fuenf "Aufsteiger" angezeigt, wo real drei sind.
    promoted = sum(1 for c in coverage if c.get("is_promoted") is True)
    promoted_unknown = sum(1 for c in coverage if c.get("is_promoted") is None)
    without_history = total - with_history
    neutral = sum(1 for c in coverage if c["fallback_level"] >= 4)
    avg_conf = sum(c["confidence"] for c in coverage) / total

    return {
        "teams_total": total,
        "teams_with_history": with_history,
        "teams_without_history": without_history,
        "teams_promoted": promoted,
        "teams_promoted_unknown": promoted_unknown,
        "teams_neutral": neutral,
        "history_ratio": round(with_history / total, 2),
        "historical_seasons": historical_seasons_loaded,
        "avg_confidence": round(avg_conf, 2),
        # Belastbar, wenn kein Team im Notfall-Modus liegt und die
        # allermeisten Teams echte Historie haben.
        "reliable": (neutral == 0 and with_history / total >= 0.8),
        "promoted_source": promoted_source,
    }
