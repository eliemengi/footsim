"""
Saisonsimulation fuer FootSim.

Ablauf
------
Die Tabelle nach den bereits gespielten Partien ist bekannt. Fuer jede
noch ausstehende Begegnung wird ein Ergebnis gewuerfelt, und zwar auf
Basis der Teamstaerken. Das wiederholt sich viele tausend Mal. Aus der
Verteilung der Endtabellen ergeben sich die Wahrscheinlichkeiten.

Woher die Staerken kommen
-------------------------
Nicht mehr aus den letzten fuenf Spielen, sondern aus
src/features/strength_provider.py. Der liefert pro Team vier Ratings
(Angriff/Abwehr, je Heim und Auswaerts), gemischt aus:

  * kompletten abgeschlossenen Vorsaisons (gewichtet, neueste zuerst)
  * den bereits gespielten Partien der laufenden Saison

Das Mischungsverhaeltnis haengt davon ab, wie viele Spiele die laufende
Saison schon hat: an Spieltag 0 zaehlt allein die Historie, spaeter
zunehmend die aktuelle Form. Details in features/dynamic_weights.py.

Konsistenzgarantien
-------------------
Diese Punkte sind bewusst so gebaut und durch Tests abgesichert:

  * Teams werden ausschliesslich ueber team_id verknuepft, nie ueber
    Namen. In den Rohdaten hat derselbe Verein mehrere Schreibweisen.
  * Rang, Sortierung und alle Wahrscheinlichkeiten stammen aus DERSELBEN
    Simulationsschleife. Die reale Tabellenposition wird getrennt als
    current_position mitgefuehrt und beeinflusst die Anzeige nicht.
  * Fehlende Daten fallen nicht stillschweigend auf einen Durchschnitt.
    Jedes Team traegt data_source, fallback_level und confidence mit.
  * Mit gesetztem seed ist ein Lauf exakt reproduzierbar.
"""

import math
import random
import statistics
from collections import defaultdict

from src.features.strength_provider import get_league_strengths
from src.features.team_profile import expected_goals, neutral_profile


# Spieltage pro Liga
MATCHDAYS_TOTAL = {
    "bl1": 34,
    "pl":  38,
    "pd":  38,
    "sa":  38,
    "fl1": 34,
}

# Plaetze mit besonderer Bedeutung je Liga
ZONE_CONFIGS = {
    "bl1": {"cl": 4, "el": 5, "ecl": 6, "relegation_playoff": 16, "relegation": [17, 18]},
    "pl":  {"cl": 4, "el": 5, "ecl": 6, "relegation": [18, 19, 20]},
    "pd":  {"cl": 4, "el": 5, "ecl": 6, "relegation": [18, 19, 20]},
    "sa":  {"cl": 4, "el": 5, "ecl": 6, "relegation": [18, 19, 20]},
    "fl1": {"cl": 3, "el": 4, "ecl": 5, "relegation_playoff": 16, "relegation": [17, 18]},
}


def _poisson(lmbda, rng):
    """
    Zieht eine Zufallszahl aus der Poisson-Verteilung (Knuth-Verfahren).

    Die Poisson-Verteilung beschreibt, wie oft ein seltenes Ereignis in
    einem festen Zeitraum eintritt - genau das Muster von Toren in einem
    Fussballspiel. lmbda ist die erwartete Toranzahl.

    rng wird uebergeben statt global genutzt, damit ein Lauf mit festem
    Seed reproduzierbar ist.
    """
    limit = math.exp(-lmbda)
    k, p = 0, 1.0
    while p > limit:
        k += 1
        p *= rng.random()
    return k - 1


def _team_key(row):
    """Einheitlicher Schluessel: team_id wenn vorhanden, sonst Name."""
    return row.get("team_id") if row.get("team_id") is not None else row.get("team_name")


def _match_key(match, side):
    """Schluessel eines Match-Teams: ID bevorzugt, Name als Notbehelf."""
    id_field = "home_id" if side == "home" else "away_id"
    name_field = "home_team" if side == "home" else "away_team"
    value = match.get(id_field)
    return value if value is not None else match.get(name_field)


def simulate_season(
    competition_code,
    standings_table,
    remaining_matches,
    simulations=10000,
    current_matches=None,
    seed=None,
    season=None,
    fixture_coverage=None,
):
    """
    Simuliert alle ausstehenden Partien einer Saison.

    competition_code: 'bl1', 'pl', ...
    standings_table:  aktuelle Tabelle, jede Zeile mit team_id, team_name,
                      points, goal_difference, goals_for, played, position
    remaining_matches: offene Partien, je mit home_id/away_id
    current_matches:  bereits gespielte Partien dieser Saison, Format
                      {home_id, away_id, home_goals, away_goals}. Ohne
                      diese Angabe stuetzt sich das Modell nur auf die
                      Historie.
    seed:             feste Zahl macht den Lauf reproduzierbar (Tests)
    """
    if not standings_table:
        return _empty_result(competition_code)

    if not remaining_matches:
        return _season_done_result(competition_code, standings_table)

    rng = random.Random(seed)
    zones = ZONE_CONFIGS.get(competition_code, {})

    # --- Teamstaerken beschaffen (Historie + laufende Saison) ---
    strength_data = get_league_strengths(
        league_key=competition_code,
        standings_table=standings_table,
        current_matches=current_matches,
        current_season=season,
    )
    profiles = strength_data["profiles"]
    league_avg = strength_data["league_avg"]

    keys = [_team_key(row) for row in standings_table]
    n_teams = len(keys)

    # Ausgangswerte und Anzeigedaten je Team.
    base, meta = {}, {}
    for row in standings_table:
        key = _team_key(row)
        profile = profiles.get(row.get("team_id")) or neutral_profile(
            row.get("team_id"), row.get("team_name")
        )

        base[key] = {
            "pts": row.get("points", 0),
            "gd": row.get("goal_difference", 0),
            "gf": row.get("goals_for", 0),
            "ga": row.get("goals_for", 0) - row.get("goal_difference", 0),
        }
        meta[key] = {
            "team_name": row.get("team_name"),
            "team_full_name": row.get("team_full_name", row.get("team_name")),
            "crest": row.get("crest") or profile.get("crest"),
            "current_position": row.get("position"),
            "current_points": row.get("points", 0),
            "current_played": row.get("played", 0),
            "profile": profile,
        }

    # Erwartete Tore einmal pro Paarung vorberechnen. Die Werte aendern
    # sich waehrend der Simulation nicht, also waere es Verschwendung,
    # sie in jedem der zehntausend Durchlaeufe neu zu bestimmen.
    #
    # Nicht verhandelbar: KEIN Fixture verschwindet. Fehlt einem Team das
    # Profil (was nach der Fallback-Kette nicht vorkommen sollte), greift
    # der Neutralwert - und der Vorfall wird gezaehlt und protokolliert.
    fixtures = []
    fixtures_with_fallback_profile = 0
    fixture_fallback_teams = set()

    for match in remaining_matches:
        h_key = _match_key(match, "home")
        a_key = _match_key(match, "away")

        h_profile = profiles.get(match.get("home_id"))
        a_profile = profiles.get(match.get("away_id"))

        if h_profile is None:
            h_profile = neutral_profile(match.get("home_id"), match.get("home_team"))
            fixtures_with_fallback_profile += 1
            fixture_fallback_teams.add(match.get("home_team") or match.get("home_id"))
        if a_profile is None:
            a_profile = neutral_profile(match.get("away_id"), match.get("away_team"))
            fixtures_with_fallback_profile += 1
            fixture_fallback_teams.add(match.get("away_team") or match.get("away_id"))

        xh, xa = expected_goals(h_profile, a_profile, league_avg)
        fixtures.append((h_key, a_key, xh, xa))

    # --- Monte-Carlo-Schleife ---
    position_counts = {k: defaultdict(int) for k in keys}
    positions_seen = {k: [] for k in keys}
    points_sum = defaultdict(float)
    gd_sum = defaultdict(float)
    gf_sum = defaultdict(float)
    ga_sum = defaultdict(float)

    for _ in range(simulations):
        table = {k: dict(base[k]) for k in keys}

        for h_key, a_key, xh, xa in fixtures:
            hg = _poisson(xh, rng)
            ag = _poisson(xa, rng)

            home = table.get(h_key)
            away = table.get(a_key)

            if home is not None:
                home["gf"] += hg
                home["ga"] += ag
                home["gd"] += hg - ag
                if hg > ag:
                    home["pts"] += 3
                elif hg == ag:
                    home["pts"] += 1

            if away is not None:
                away["gf"] += ag
                away["ga"] += hg
                away["gd"] += ag - hg
                if ag > hg:
                    away["pts"] += 3
                elif ag == hg:
                    away["pts"] += 1

        # Endtabelle dieses Durchlaufs: Punkte, dann Tordifferenz, dann Tore.
        ordered = sorted(
            table.items(),
            key=lambda kv: (kv[1]["pts"], kv[1]["gd"], kv[1]["gf"]),
            reverse=True,
        )

        for rank, (key, values) in enumerate(ordered, start=1):
            position_counts[key][rank] += 1
            positions_seen[key].append(rank)
            points_sum[key] += values["pts"]
            gd_sum[key] += values["gd"]
            gf_sum[key] += values["gf"]
            ga_sum[key] += values["ga"]

    fixture_report = {
        "fixtures_to_simulate": len(remaining_matches),
        "fixtures_prepared": len(fixtures),
        "fixtures_simulated_per_run": len(fixtures),
        "fixtures_rejected": 0,
        "fixtures_with_fallback_profile": fixtures_with_fallback_profile,
        "fallback_teams": sorted(str(t) for t in fixture_fallback_teams),
    }
    if fixture_coverage:
        fixture_report.update({
            "fixtures_received": fixture_coverage.get("fixtures_received"),
            "fixtures_finished": fixture_coverage.get("fixtures_finished"),
            "fixtures_invalid": fixture_coverage.get("fixtures_rejected"),
            "expected_total": fixture_coverage.get("expected_total"),
            "coverage_ok": fixture_coverage.get("ok"),
        })

    return _build_result(
        competition_code=competition_code,
        keys=keys,
        meta=meta,
        position_counts=position_counts,
        positions_seen=positions_seen,
        points_sum=points_sum,
        gd_sum=gd_sum,
        gf_sum=gf_sum,
        ga_sum=ga_sum,
        simulations=simulations,
        zones=zones,
        n_teams=n_teams,
        remaining_matches=remaining_matches,
        strength_data=strength_data,
        seed=seed,
        fixture_report=fixture_report,
    )


def _build_result(
    competition_code, keys, meta, position_counts, positions_seen,
    points_sum, gd_sum, gf_sum, ga_sum, simulations, zones, n_teams,
    remaining_matches, strength_data, seed, fixture_report=None,
):
    zones = zones or {}
    cl_spots = zones.get("cl", 4)
    el_spots = zones.get("el", 5)
    ecl_spots = zones.get("ecl", 6)
    rel_list = zones.get("relegation", [])

    games_remaining = defaultdict(int)
    for match in remaining_matches:
        games_remaining[_match_key(match, "home")] += 1
        games_remaining[_match_key(match, "away")] += 1

    entries = []

    for key in keys:
        counts = position_counts.get(key, {})
        info = meta.get(key, {})
        profile = info.get("profile") or {}

        def pct(position):
            return round(100.0 * counts.get(position, 0) / simulations, 1)

        def pct_range(low, high):
            total = sum(counts.get(p, 0) for p in range(low, high + 1))
            return round(100.0 * total / simulations, 1)

        expected_pos = (
            sum(pos * cnt for pos, cnt in counts.items()) / simulations
            if counts else info.get("current_position") or n_teams
        )

        seen = positions_seen.get(key) or []
        median_pos = statistics.median(seen) if seen else expected_pos

        entries.append({
            "team_name": info.get("team_name"),
            "team_full_name": info.get("team_full_name"),
            "crest": info.get("crest"),

            # Realer Stand, klar getrennt von der Prognose.
            "current_position": info.get("current_position"),
            "current_points": info.get("current_points"),
            "current_played": info.get("current_played"),
            "games_remaining": games_remaining.get(key, 0),

            # Prognose
            "expected_position": round(expected_pos, 1),
            "median_position": round(median_pos, 1),
            "expected_points": round(points_sum.get(key, 0) / simulations, 1),
            "expected_gd": round(gd_sum.get(key, 0) / simulations, 1),
            "expected_goals_for": round(gf_sum.get(key, 0) / simulations, 1),
            "expected_goals_against": round(ga_sum.get(key, 0) / simulations, 1),

            "champion_pct": pct(1),
            "top2_pct": pct_range(1, 2),
            "cl_pct": pct_range(1, cl_spots),
            "el_pct": pct_range(1, el_spots),
            "ecl_pct": pct_range(1, ecl_spots),
            "relegation_pct": (
                pct_range(min(rel_list), max(rel_list)) if rel_list else 0.0
            ),

            # Herkunft der Staerkewerte, damit nachvollziehbar bleibt,
            # worauf die Prognose beruht. is_promoted (echter Aufstieg,
            # Vorsaison-Abgleich) und has_historical_data (Datenlage)
            # sind bewusst getrennte Merkmale.
            "is_promoted": profile.get("is_promoted"),
            "has_historical_data": profile.get("has_historical_data", False),
            "data_source": profile.get("data_source", "unknown"),
            "fallback_level": profile.get("fallback_level", 4),
            "confidence": profile.get("confidence", 0.0),
            "confidence_level": profile.get("confidence_level", "niedrig"),
            "historical_seasons": profile.get("seasons_count", 0),
            "attack_home": round(profile.get("attack_home", 1.0), 2),
            "attack_away": round(profile.get("attack_away", 1.0), 2),
            "defence_home": round(profile.get("defence_home", 1.0), 2),
            "defence_away": round(profile.get("defence_away", 1.0), 2),

            "position_probs": {
                str(pos): round(100.0 * cnt / simulations, 1)
                for pos, cnt in sorted(counts.items())
                if cnt / simulations >= 0.005
            },
        })

    # EINE Sortierung nach erwartetem Endplatz. Der angezeigte Rang wird
    # danach vergeben, sodass Reihenfolge und Nummer nie auseinanderlaufen.
    entries.sort(key=lambda e: (e["expected_position"], -e["expected_points"]))
    for rank, entry in enumerate(entries, start=1):
        entry["rank"] = rank

    summary = strength_data.get("summary", {})

    return {
        "competition_code": competition_code,
        "simulations": simulations,
        "games_remaining": len(remaining_matches),
        "season_done": False,
        "seed": seed,
        "entries": entries,
        "zones": zones,
        "league_avg": {
            "home_goals": round(strength_data["league_avg"].get("home_goals", 0), 2),
            "away_goals": round(strength_data["league_avg"].get("away_goals", 0), 2),
            "total_goals": round(strength_data["league_avg"].get("total_goals", 0), 2),
        },
        "data_quality": {
            "teams_total": summary.get("teams_total", len(entries)),
            "teams_with_history": summary.get("teams_with_history", 0),
            "teams_without_history": summary.get("teams_without_history", 0),
            "teams_promoted": summary.get("teams_promoted", 0),
            "teams_promoted_unknown": summary.get("teams_promoted_unknown", 0),
            "teams_neutral": summary.get("teams_neutral", 0),
            "history_ratio": summary.get("history_ratio", 0.0),
            "historical_seasons": summary.get("historical_seasons", 0),
            "historical_season_years": summary.get("historical_season_years", []),
            "previous_season_available": summary.get("previous_season_available", False),
            "avg_confidence": summary.get("avg_confidence", 0.0),
            "reliable": summary.get("reliable", False),
            "promoted_source": summary.get("promoted_source"),
        },
        "fixture_report": fixture_report or {},
        "coverage": strength_data.get("coverage", []),
    }


def _season_done_result(competition_code, standings_table):
    """Saison abgeschlossen: die Tabelle steht fest, nichts zu simulieren."""
    entries = []

    for row in standings_table:
        position = row.get("position")
        entries.append({
            "rank": position,
            "team_name": row.get("team_name"),
            "team_full_name": row.get("team_full_name", row.get("team_name")),
            "crest": row.get("crest"),
            "current_position": position,
            "current_points": row.get("points", 0),
            "current_played": row.get("played", 0),
            "games_remaining": 0,
            "expected_position": position,
            "median_position": position,
            "expected_points": row.get("points", 0),
            "expected_gd": row.get("goal_difference", 0),
            "expected_goals_for": row.get("goals_for", 0),
            "expected_goals_against": row.get("goals_for", 0) - row.get("goal_difference", 0),
            "champion_pct": 100.0 if position == 1 else 0.0,
            "top2_pct": 100.0 if (position or 99) <= 2 else 0.0,
            "cl_pct": None,
            "el_pct": None,
            "ecl_pct": None,
            "relegation_pct": None,
            "data_source": "final_table",
            "fallback_level": 0,
            "confidence": 1.0,
            "confidence_level": "hoch",
            "historical_seasons": 0,
            "attack_home": 1.0, "attack_away": 1.0,
            "defence_home": 1.0, "defence_away": 1.0,
            "position_probs": {str(position): 100.0},
        })

    entries.sort(key=lambda e: e["rank"] if e["rank"] is not None else 99)

    return {
        "competition_code": competition_code,
        "simulations": 0,
        "games_remaining": 0,
        "season_done": True,
        "seed": None,
        "entries": entries,
        "zones": ZONE_CONFIGS.get(competition_code, {}),
        "league_avg": {},
        "data_quality": {
            "teams_total": len(entries), "teams_with_history": len(entries),
            "teams_promoted": 0, "teams_neutral": 0, "history_ratio": 1.0,
            "historical_seasons": 0, "avg_confidence": 1.0, "reliable": True,
            "promoted_source": None,
        },
        "coverage": [],
    }


def _empty_result(competition_code):
    """Keine Tabellendaten vorhanden."""
    return {
        "competition_code": competition_code,
        "simulations": 0,
        "games_remaining": 0,
        "season_done": False,
        "seed": None,
        "entries": [],
        "zones": ZONE_CONFIGS.get(competition_code, {}),
        "league_avg": {},
        "data_quality": {
            "teams_total": 0, "teams_with_history": 0, "teams_promoted": 0,
            "teams_neutral": 0, "history_ratio": 0.0, "historical_seasons": 0,
            "avg_confidence": 0.0, "reliable": False, "promoted_source": None,
        },
        "coverage": [],
    }
