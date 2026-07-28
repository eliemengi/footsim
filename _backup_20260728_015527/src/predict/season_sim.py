"""
Saisonssimulation für FootSim.

Idee: Die Tabelle nach den bereits gespielten Spielen ist bekannt.
Für alle noch ausstehenden Partien wird jedes Ergebnis per Poisson
simuliert — das gleiche Modell wie bei Einzelspielen.
Nach vielen Durchläufen weiß man, wie oft jeder Verein auf welchem
Platz landet.

WICHTIG (Stand Bugfix-Runde):
- Teams werden ueber team_id verknuepft, nicht ueber Namen. In den
  Rohdaten hat derselbe Verein teils mehrere Namens-Keys.
- Rang, Anzeige-Nummer und Wahrscheinlichkeiten stammen alle aus
  DERSELBEN Simulation. Die alte API-Tabellenposition wird nur noch
  als Zusatzinfo (current_position) mitgegeben, nie als Sortier- oder
  Anzeige-Rang.
- Fehlt fuer ein Team die Staerke, faellt es NICHT stumm auf einen
  globalen Durchschnitt. Es bekommt den Liga-Durchschnitt der
  vorhandenen Teams und wird in data_source als 'league_fallback'
  markiert, damit man im Debug sieht, was echt ist und was geraten.

Das eigentliche Staerke-Modell (nur letzte Spiele) ist bewusst noch
NICHT umgebaut — das ist der naechste, gemeinsame Schritt. Diese Runde
behebt nur objektive Bugs.
"""

import random
import math
from collections import defaultdict

from src.features.team_strength import get_team_strengths_by_id


# Spieltage pro Liga
MATCHDAYS_TOTAL = {
    "bl1": 34,
    "pl":  38,
    "pd":  38,
    "sa":  38,
    "fl1": 34,
}

# Plätze die besondere Bedeutung haben je nach Liga
ZONE_CONFIGS = {
    "bl1": {"cl": 4, "el": 5, "ecl": 6, "relegation_playoff": 16, "relegation": [17, 18]},
    "pl":  {"cl": 4, "el": 5, "ecl": 6, "relegation": [18, 19, 20]},
    "pd":  {"cl": 4, "el": 5, "ecl": 6, "relegation": [18, 19, 20]},
    "sa":  {"cl": 4, "el": 5, "ecl": 6, "relegation": [18, 19, 20]},
    "fl1": {"cl": 3, "el": 4, "ecl": 5, "relegation_playoff": 16, "relegation": [17, 18]},
}


def _poisson(lmbda):
    l = math.exp(-lmbda)
    k, p = 0, 1.0
    while p > l:
        k += 1
        p *= random.random()
    return k - 1


def _expected_goals(home_str, away_str):
    """Direkt aus simulate_scores.py übernommen, damit beide Modelle identisch sind."""
    xh = (
        home_str["avg_goals_scored"] * 0.45
        + away_str["avg_goals_conceded"] * 0.25
        + home_str["points_per_game"] * 0.15
        + home_str["winrate"] * 0.35
        + 0.25
    )
    xa = (
        away_str["avg_goals_scored"] * 0.45
        + home_str["avg_goals_conceded"] * 0.25
        + away_str["points_per_game"] * 0.15
        + away_str["winrate"] * 0.35
    )
    return max(0.2, min(xh, 3.5)), max(0.2, min(xa, 3.5))


def _league_average_strength(resolved):
    """
    Durchschnittsstaerke aus den Teams, die ECHTE Daten haben.

    Wird als Fallback fuer Teams ohne eigene Daten benutzt. Damit ist der
    Fallback ligaabhaengig (er spiegelt genau die Teams dieser Simulation)
    statt einer globalen Konstante 1.3, die jedem Team dieselbe Staerke gab.
    """
    real = [s for s, src in resolved.values() if src == "history"]
    if not real:
        # Notnagel, falls gar kein Team echte Daten hat.
        return {"avg_goals_scored": 1.3, "avg_goals_conceded": 1.3,
                "points_per_game": 1.2, "winrate": 0.35}

    n = len(real)
    return {
        "avg_goals_scored":   sum(s["avg_goals_scored"] for s in real) / n,
        "avg_goals_conceded": sum(s["avg_goals_conceded"] for s in real) / n,
        "points_per_game":    sum(s["points_per_game"] for s in real) / n,
        "winrate":            sum(s["winrate"] for s in real) / n,
    }


def _resolve_strengths(standings_table, strengths_by_id):
    """
    Ordnet jedem Team seine Staerke zu — ueber team_id.

    Rueckgabe: { team_id: (strength_dict, source) }
      source ist 'history' (echte Daten) oder 'league_fallback' (geraten).
    Zusaetzlich: fuer Teams, deren id fehlt, faellt der Key auf den
    Teamnamen zurueck, damit die Simulation trotzdem laeuft.
    """
    resolved = {}

    # Erste Runde: echte Daten per id.
    for row in standings_table:
        key = row.get("team_id")
        if key is None:
            key = row["team_name"]  # Notfall-Key

        strength = strengths_by_id.get(row.get("team_id"))
        if strength and strength.get("matches_used", 0) > 0:
            resolved[key] = (strength, "history")
        else:
            resolved[key] = (None, "league_fallback")

    # Zweite Runde: Liga-Durchschnitt fuer die Fallback-Teams einsetzen.
    league_avg = _league_average_strength(resolved)
    for key, (strength, source) in resolved.items():
        if strength is None:
            resolved[key] = (league_avg, "league_fallback")

    return resolved


def _team_key(row):
    """Einheitlicher Schluessel: team_id wenn vorhanden, sonst Name."""
    return row.get("team_id") if row.get("team_id") is not None else row["team_name"]


def _match_key(match, side):
    """Schluessel fuer ein Match-Team: id wenn vorhanden, sonst Name."""
    id_field = "home_id" if side == "home" else "away_id"
    name_field = "home_team" if side == "home" else "away_team"
    return match.get(id_field) if match.get(id_field) is not None else match.get(name_field)


def simulate_season(
    competition_code,
    standings_table,
    remaining_matches,
    simulations=10000,
):
    """
    Simuliert alle ausstehenden Partien einer Saison.

    standings_table: aktuelle Tabelle aus /api/standings, jede Zeile mit
        team_id, team_name, points, goal_difference, goals_for, played, position
    remaining_matches: noch nicht gespielte Spiele, je mit home_id/away_id
        (Fallback home_team/away_team).

    Rueckgabe: Ergebnisstruktur fuers Frontend. Rang, Anzeige und
    Wahrscheinlichkeiten stammen alle aus dieser einen Simulation.
    """
    if not remaining_matches:
        return _season_done_result(competition_code, standings_table)

    strengths_by_id = get_team_strengths_by_id()
    zones = ZONE_CONFIGS.get(competition_code, {})

    # Staerke pro Team ueber id aufloesen, inkl. Fallback-Markierung.
    resolved = _resolve_strengths(standings_table, strengths_by_id)

    # Einheitliche Team-Keys (id-basiert) und Basiswerte aus der Tabelle.
    keys = [_team_key(row) for row in standings_table]
    n_teams = len(keys)

    base = {}
    meta = {}   # key -> Anzeige-Infos (Name, Crest, aktuelle Position ...)
    for row in standings_table:
        k = _team_key(row)
        base[k] = {
            "pts": row["points"],
            "gd":  row["goal_difference"],
            "gf":  row["goals_for"],
        }
        meta[k] = {
            "team_name":        row["team_name"],
            "team_full_name":   row.get("team_full_name", row["team_name"]),
            "crest":            row.get("crest"),
            "current_position": row.get("position"),
            "current_points":   row["points"],
            "current_played":   row.get("played", 0),
            "data_source":      resolved.get(k, (None, "league_fallback"))[1],
        }

    position_counts = {k: defaultdict(int) for k in keys}
    # Fuer erwartete Punkte / Tordifferenz ueber alle Laeufe aggregieren.
    points_sum = defaultdict(float)
    gd_sum = defaultdict(float)

    for _ in range(simulations):
        sim_table = {k: dict(base[k]) for k in keys}

        for match in remaining_matches:
            h_key = _match_key(match, "home")
            a_key = _match_key(match, "away")

            h_str = resolved.get(h_key, (None, None))[0]
            a_str = resolved.get(a_key, (None, None))[0]

            # Falls ein Match-Team gar nicht in der Tabelle ist (sollte
            # nicht vorkommen), Liga-Durchschnitt nehmen.
            if h_str is None:
                h_str = _league_average_strength(resolved)
            if a_str is None:
                a_str = _league_average_strength(resolved)

            xh, xa = _expected_goals(h_str, a_str)
            hg = _poisson(xh)
            ag = _poisson(xa)

            if h_key in sim_table:
                sim_table[h_key]["gf"] += hg
                sim_table[h_key]["gd"] += hg - ag
                if hg > ag:
                    sim_table[h_key]["pts"] += 3
                elif hg == ag:
                    sim_table[h_key]["pts"] += 1

            if a_key in sim_table:
                sim_table[a_key]["gf"] += ag
                sim_table[a_key]["gd"] += ag - hg
                if ag > hg:
                    sim_table[a_key]["pts"] += 3
                elif ag == hg:
                    sim_table[a_key]["pts"] += 1

        # Endtabelle dieses Laufs sortieren: Punkte, Tordifferenz, Tore.
        ordered = sorted(
            sim_table.items(),
            key=lambda kv: (kv[1]["pts"], kv[1]["gd"], kv[1]["gf"]),
            reverse=True,
        )

        for rank, (k, vals) in enumerate(ordered, start=1):
            position_counts[k][rank] += 1
            points_sum[k] += vals["pts"]
            gd_sum[k] += vals["gd"]

    return _build_result(
        competition_code, keys, meta, position_counts,
        points_sum, gd_sum, simulations, zones, n_teams, remaining_matches,
        resolved,
    )


def _build_result(
    competition_code, keys, meta, position_counts,
    points_sum, gd_sum, simulations, zones, n_teams, remaining_matches,
    resolved,
):
    zones = zones or {}
    cl_spots = zones.get("cl", 4)
    el_spots = zones.get("el", 5)
    ecl_spots = zones.get("ecl", 6)
    rel_list = zones.get("relegation", [])

    # Wie viele Restspiele hat jedes Team? (id-basiert gezaehlt)
    games_remaining = defaultdict(int)
    for match in remaining_matches:
        games_remaining[_match_key(match, "home")] += 1
        games_remaining[_match_key(match, "away")] += 1

    entries = []
    for k in keys:
        counts = position_counts.get(k, {})
        info = meta.get(k, {})

        def pct(pos):
            return round(100.0 * counts.get(pos, 0) / simulations, 1)

        def pct_range(lo, hi):
            total = sum(counts.get(p, 0) for p in range(lo, hi + 1))
            return round(100.0 * total / simulations, 1)

        expected_pos = (
            sum(pos * cnt for pos, cnt in counts.items()) / simulations
            if counts else info.get("current_position", n_teams)
        )

        entries.append({
            "team_name":         info.get("team_name"),
            "team_full_name":    info.get("team_full_name"),
            "crest":             info.get("crest"),
            "current_position":  info.get("current_position"),
            "current_points":    info.get("current_points"),
            "current_played":    info.get("current_played"),
            "games_remaining":   games_remaining.get(k, 0),
            "expected_position": round(expected_pos, 1),
            "expected_points":   round(points_sum.get(k, 0) / simulations, 1),
            "expected_gd":       round(gd_sum.get(k, 0) / simulations, 1),
            "champion_pct":      pct(1),
            "top2_pct":          pct_range(1, 2),
            "cl_pct":            pct_range(1, cl_spots),
            "el_pct":            pct_range(1, el_spots),
            "ecl_pct":           pct_range(1, ecl_spots),
            "relegation_pct":    pct_range(min(rel_list), max(rel_list)) if rel_list else 0.0,
            "data_source":       info.get("data_source", "league_fallback"),
            "position_probs":    {
                str(pos): round(100.0 * cnt / simulations, 1)
                for pos, cnt in sorted(counts.items())
                if cnt / simulations >= 0.005
            },
        })

    # EINE Sortierung: nach erwartetem Endplatz. Der angezeigte Rang wird
    # DANACH vergeben, sodass Listenreihenfolge und Rang-Nummer immer
    # uebereinstimmen (Bugfix: kein Rueckgriff mehr auf API-position).
    entries.sort(key=lambda e: (e["expected_position"], -e["expected_points"]))
    for rank, entry in enumerate(entries, start=1):
        entry["rank"] = rank

    # Datenqualitaet: Anteil Teams mit echten Daten. Steuert den Warnhinweis.
    total = len(entries)
    real = sum(1 for e in entries if e["data_source"] == "history")
    fallback = total - real
    data_quality = {
        "teams_total":     total,
        "teams_real":      real,
        "teams_fallback":  fallback,
        "real_ratio":      round(real / total, 2) if total else 0.0,
        "reliable":        (fallback == 0),
    }

    return {
        "competition_code": competition_code,
        "simulations": simulations,
        "games_remaining": len(remaining_matches),
        "season_done": False,
        "entries": entries,
        "zones": zones,
        "data_quality": data_quality,
    }


def _season_done_result(competition_code, standings_table):
    """Saison ist abgeschlossen, gibt die fixe Abschlusstabelle zurück."""
    entries = []

    for row in standings_table:
        pos = row.get("position")
        entries.append({
            "rank":              pos,
            "team_name":         row["team_name"],
            "team_full_name":    row.get("team_full_name", row["team_name"]),
            "crest":             row.get("crest"),
            "current_position":  pos,
            "current_points":    row["points"],
            "current_played":    row.get("played", 0),
            "games_remaining":   0,
            "expected_position": pos,
            "expected_points":   row["points"],
            "expected_gd":       row.get("goal_difference", 0),
            "champion_pct":      100.0 if pos == 1 else 0.0,
            "top2_pct":          100.0 if (pos or 99) <= 2 else 0.0,
            "cl_pct":            None,
            "el_pct":            None,
            "ecl_pct":           None,
            "relegation_pct":    None,
            "data_source":       "final_table",
            "position_probs":    {str(pos): 100.0},
        })

    entries.sort(key=lambda e: e["rank"] if e["rank"] is not None else 99)

    return {
        "competition_code": competition_code,
        "simulations": 0,
        "games_remaining": 0,
        "season_done": True,
        "entries": entries,
        "zones": ZONE_CONFIGS.get(competition_code, {}),
        "data_quality": {"teams_total": len(entries), "teams_real": len(entries),
                         "teams_fallback": 0, "real_ratio": 1.0, "reliable": True},
    }
