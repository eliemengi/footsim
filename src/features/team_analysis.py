"""
Teamanalyse: Form, Heim-/Auswaertsbilanz, Power Ranking, Head-to-Head.

Dieses Modul ist die Datenschicht von Block A und die spaetere Basis fuer
Block B (Transfervergleich) und Block C (Teamvergleich). Deshalb sind alle
Funktionen bewusst so geschnitten, dass sie einzeln aufrufbar sind und
reine Dicts zurueckgeben - kein Flask, keine Requests, kein Rendering.

Datenquellen (alle bereits vorhanden, keine neuen API-Aufrufe):

    get_standings()            aktuelle Tabelle inkl. HOME/AWAY-Bloecken
    get_full_season_matches()  kompletter Spielplan der laufenden Saison
    partition_season_matches() Aufteilung in gespielt/offen
    get_league_strengths()     Staerkemodell (attack/defence home/away)
    load_available_seasons()   historische Saisons fuer Head-to-Head

Die Fixture-Eintraege aus partition_season_matches()["finished"] haben das
Format {home_id, away_id, home_goals, away_goals, matchday}.
"""

from src.data.historical_loader import (
    load_available_seasons,
    LEAGUE_CODES,
)


# ---------------------------------------------------------------------------
# Form
# ---------------------------------------------------------------------------

def get_team_form(team_id, finished_matches, last_n=5):
    """
    Form eines Teams aus den letzten N gespielten Partien.

    finished_matches: plan["finished"] aus partition_season_matches(),
                      chronologisch aufsteigend sortiert nach matchday.

    Rueckgabe:
    {
      "sequence":   ["W", "D", "L", ...]  (neueste zuerst),
      "matches":    [ {opponent_id, home, goals_for, goals_against,
                       result, matchday} ]  (neueste zuerst),
      "wins": 3, "draws": 1, "losses": 1,
      "goals_for": 9, "goals_against": 4,
      "points": 10,
      "form_score": 0.67,     # Punkte / max. Punkte, 0..1
      "sample_size": 5
    }

    form_score ist bewusst simpel (Punktquote der letzten N Spiele).
    Er ist damit erklaerbar und direkt mit anderen Teams vergleichbar.
    """
    played = []

    for match in finished_matches or []:
        home_id = match.get("home_id")
        away_id = match.get("away_id")
        if team_id not in (home_id, away_id):
            continue

        is_home = (team_id == home_id)
        goals_for = match.get("home_goals") if is_home else match.get("away_goals")
        goals_against = match.get("away_goals") if is_home else match.get("home_goals")

        if goals_for is None or goals_against is None:
            continue

        if goals_for > goals_against:
            result = "W"
        elif goals_for < goals_against:
            result = "L"
        else:
            result = "D"

        played.append({
            "opponent_id": away_id if is_home else home_id,
            "home": is_home,
            "goals_for": goals_for,
            "goals_against": goals_against,
            "result": result,
            "matchday": match.get("matchday"),
        })

    # Neueste zuerst: hoechster Spieltag vorne.
    played.sort(key=lambda m: (m["matchday"] or 0), reverse=True)
    recent = played[:last_n]

    wins = sum(1 for m in recent if m["result"] == "W")
    draws = sum(1 for m in recent if m["result"] == "D")
    losses = sum(1 for m in recent if m["result"] == "L")
    points = wins * 3 + draws
    max_points = len(recent) * 3

    return {
        "sequence": [m["result"] for m in recent],
        "matches": recent,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goals_for": sum(m["goals_for"] for m in recent),
        "goals_against": sum(m["goals_against"] for m in recent),
        "points": points,
        "form_score": round(points / max_points, 2) if max_points else 0.0,
        "sample_size": len(recent),
    }


# ---------------------------------------------------------------------------
# Heim- / Auswaertsbilanz
# ---------------------------------------------------------------------------

def split_home_away(team_id, finished_matches):
    """
    Heim- und Auswaertsbilanz aus den gespielten Partien der Saison.

    Bewusst aus den Fixtures gerechnet statt aus den HOME/AWAY-Bloecken
    der Standings-API: so funktioniert es auch dann, wenn die API fuer
    einen Wettbewerb keine getrennten Tabellen liefert, und die Werte
    sind garantiert konsistent mit der Formberechnung daneben.

    Rueckgabe: {"home": {...}, "away": {...}} mit jeweils
    played/wins/draws/losses/goals_for/goals_against/points.
    """
    def empty():
        return {"played": 0, "wins": 0, "draws": 0, "losses": 0,
                "goals_for": 0, "goals_against": 0, "points": 0}

    home, away = empty(), empty()

    for match in finished_matches or []:
        home_id = match.get("home_id")
        away_id = match.get("away_id")
        if team_id not in (home_id, away_id):
            continue

        hg = match.get("home_goals")
        ag = match.get("away_goals")
        if hg is None or ag is None:
            continue

        if team_id == home_id:
            side, gf, ga = home, hg, ag
        else:
            side, gf, ga = away, ag, hg

        side["played"] += 1
        side["goals_for"] += gf
        side["goals_against"] += ga

        if gf > ga:
            side["wins"] += 1
            side["points"] += 3
        elif gf < ga:
            side["losses"] += 1
        else:
            side["draws"] += 1
            side["points"] += 1

    return {"home": home, "away": away}


# ---------------------------------------------------------------------------
# Power Ranking
# ---------------------------------------------------------------------------

# Gewichtung des Power Scores. Summe = 1.0.
#
# Begruendung der Gewichte:
#   strength   0.45  Das Staerkemodell buendelt bereits mehrere Saisons
#                    plus laufende Saison - es ist die stabilste Groesse.
#   table      0.25  Die reale Punktquote der Saison: belohnt Teams, die
#                    tatsaechlich liefern, nicht nur auf dem Papier.
#   form       0.15  Kurzfristige Tendenz der letzten 5 Spiele.
#   attack     0.075 Feinschliff: Offensivstaerke relativ zur Liga.
#   defence    0.075 Feinschliff: Defensivstaerke relativ zur Liga.
POWER_WEIGHTS = {
    "strength": 0.45,
    "table": 0.25,
    "form": 0.15,
    "attack": 0.075,
    "defence": 0.075,
}


def compute_power_ranking(standings_table, strength_profiles, finished_matches):
    """
    Modellbasiertes Ranking einer Liga.

    standings_table:   TOTAL-Tabelle aus get_standings()
    strength_profiles: profiles-Dict aus get_league_strengths()
    finished_matches:  plan["finished"] fuer die Formberechnung

    Rueckgabe: Liste, absteigend nach score sortiert:
    [
      {rank, team_id, team_name, crest, score,
       attack_score, defence_score, form_score, table_score,
       strength_score, components: {...}}
    ]

    Alle Teilwerte sind auf 0..1 normalisiert, der Gesamtscore auf 0..100.
    Die Normalisierung erfolgt liga-intern (min/max), damit das Ranking
    die Unterschiede INNERHALB der Liga aufspannt.
    """
    if not standings_table:
        return []

    rows = []

    for row in standings_table:
        team_id = row.get("team_id")
        profile = strength_profiles.get(team_id) or {}

        attack = (profile.get("attack_home", 1.0) + profile.get("attack_away", 1.0)) / 2
        # Kleinere defence-Werte sind besser; fuer den Score invertieren.
        defence_raw = (profile.get("defence_home", 1.0) + profile.get("defence_away", 1.0)) / 2
        defence = 1.0 / defence_raw if defence_raw > 0 else 1.0

        played = row.get("played") or 0
        points = row.get("points") or 0
        table_quote = (points / (played * 3)) if played else 0.0

        form = get_team_form(team_id, finished_matches, last_n=5)

        rows.append({
            "team_id": team_id,
            "team_name": row.get("team_name"),
            "crest": row.get("crest"),
            "position": row.get("position"),
            "_attack": attack,
            "_defence": defence,
            "_table": table_quote,
            "_form": form["form_score"],
            "_strength": attack * defence,   # kombinierte Modellstaerke
            "form_sample": form["sample_size"],
        })

    def normalize(key):
        values = [r[key] for r in rows]
        lo, hi = min(values), max(values)
        span = hi - lo
        for r in rows:
            r[key + "_n"] = ((r[key] - lo) / span) if span > 0 else 0.5

    for key in ("_attack", "_defence", "_table", "_form", "_strength"):
        normalize(key)

    w = POWER_WEIGHTS
    for r in rows:
        score01 = (
            w["strength"] * r["_strength_n"]
            + w["table"] * r["_table_n"]
            + w["form"] * r["_form_n"]
            + w["attack"] * r["_attack_n"]
            + w["defence"] * r["_defence_n"]
        )
        r["score"] = round(score01 * 100, 1)

    rows.sort(key=lambda r: r["score"], reverse=True)

    result = []
    for rank, r in enumerate(rows, start=1):
        result.append({
            "rank": rank,
            "team_id": r["team_id"],
            "team_name": r["team_name"],
            "crest": r["crest"],
            "table_position": r["position"],
            "score": r["score"],
            "attack_score": round(r["_attack_n"] * 100, 1),
            "defence_score": round(r["_defence_n"] * 100, 1),
            "form_score": round(r["_form_n"] * 100, 1),
            "table_score": round(r["_table_n"] * 100, 1),
            "strength_score": round(r["_strength_n"] * 100, 1),
            "form_sample": r["form_sample"],
        })

    return result


# ---------------------------------------------------------------------------
# Head-to-Head
# ---------------------------------------------------------------------------

def get_head_to_head(league_key, team_a_id, team_b_id, current_finished=None):
    """
    Direkte Duelle zweier Teams.

    Quellen: alle lokal vorhandenen historischen Saisons der Liga
    (data/historical/) plus optional die gespielten Partien der
    laufenden Saison (current_finished aus partition_season_matches).

    Es werden NUR lokal vorhandene Daten verwendet - kein API-Aufruf.
    Die Antwort weist deshalb explizit aus, welche Saisons eingeflossen
    sind, damit das Frontend die Datenbasis ehrlich benennen kann.

    Rueckgabe:
    {
      "matches_considered": 6,
      "seasons_considered": [2026, 2025, 2024, 2023],
      "wins_a": 3, "wins_b": 2, "draws": 1,
      "goals_a": 11, "goals_b": 9,
      "avg_goals_per_match": 3.3,
      "last_meetings": [ {season, matchday, home_id, away_id,
                          home_goals, away_goals, winner_id|None} ]
    }
    """
    api_code = LEAGUE_CODES.get(league_key, league_key.upper())
    meetings = []

    # Historische Saisons (data/historical/{API}_{Saison}.json)
    for season, payload in load_available_seasons(api_code):
        for match in payload.get("matches", []):
            pair = {match.get("home_id"), match.get("away_id")}
            if pair != {team_a_id, team_b_id}:
                continue
            meetings.append({
                "season": season,
                "matchday": match.get("matchday"),
                "home_id": match.get("home_id"),
                "away_id": match.get("away_id"),
                "home_goals": match.get("home_goals"),
                "away_goals": match.get("away_goals"),
            })

    # Laufende Saison
    current_season_marker = None
    for match in current_finished or []:
        pair = {match.get("home_id"), match.get("away_id")}
        if pair != {team_a_id, team_b_id}:
            continue
        current_season_marker = "laufend"
        meetings.append({
            "season": "laufend",
            "matchday": match.get("matchday"),
            "home_id": match.get("home_id"),
            "away_id": match.get("away_id"),
            "home_goals": match.get("home_goals"),
            "away_goals": match.get("away_goals"),
        })

    wins_a = wins_b = draws = goals_a = goals_b = 0

    for m in meetings:
        hg, ag = m.get("home_goals"), m.get("away_goals")
        if hg is None or ag is None:
            continue

        a_is_home = (m["home_id"] == team_a_id)
        a_goals = hg if a_is_home else ag
        b_goals = ag if a_is_home else hg

        goals_a += a_goals
        goals_b += b_goals

        if a_goals > b_goals:
            wins_a += 1
            m["winner_id"] = team_a_id
        elif b_goals > a_goals:
            wins_b += 1
            m["winner_id"] = team_b_id
        else:
            draws += 1
            m["winner_id"] = None

    # Neueste zuerst: laufende Saison vor Historie, dann Spieltag.
    def sort_key(m):
        season = m["season"]
        season_rank = 9999 if season == "laufend" else season
        return (season_rank, m.get("matchday") or 0)

    meetings.sort(key=sort_key, reverse=True)

    total = wins_a + wins_b + draws
    seasons_considered = sorted(
        {m["season"] for m in meetings if m["season"] != "laufend"},
        reverse=True,
    )
    if current_season_marker:
        seasons_considered.insert(0, current_season_marker)

    return {
        "matches_considered": total,
        "seasons_considered": seasons_considered,
        "wins_a": wins_a,
        "wins_b": wins_b,
        "draws": draws,
        "goals_a": goals_a,
        "goals_b": goals_b,
        "avg_goals_per_match": (
            round((goals_a + goals_b) / total, 1) if total else 0.0
        ),
        "last_meetings": meetings[:10],
    }


# ---------------------------------------------------------------------------
# Team Summary (Aggregation fuer /api/team-detail)
# ---------------------------------------------------------------------------

def get_team_summary(team_id, standings_table, strength_profiles,
                     finished_matches, power_ranking=None):
    """
    Buendelt alle Analysebausteine eines Teams fuer das Frontend.

    Alle Argumente sind bereits geladene Datenstrukturen - diese Funktion
    macht selbst keinen API-Aufruf. Der Aufrufer (die Route) entscheidet,
    was geladen wird; das haelt die Funktion testbar und wiederverwendbar
    (Block B/C rufen sie mit denselben Strukturen auf).

    Rueckgabe: ein Dict mit season_stats, per_game, form, home_away,
    strength und power - oder None, wenn das Team nicht in der
    Tabelle steht.
    """
    row = next(
        (r for r in standings_table or [] if r.get("team_id") == team_id),
        None,
    )
    if row is None:
        return None

    played = row.get("played") or 0
    profile = strength_profiles.get(team_id) or {}

    power_entry = None
    if power_ranking:
        power_entry = next(
            (p for p in power_ranking if p.get("team_id") == team_id),
            None,
        )

    return {
        "team_id": team_id,
        "team_name": row.get("team_name"),
        "team_full_name": row.get("team_full_name"),
        "crest": row.get("crest"),

        "season_stats": {
            "position": row.get("position"),
            "played": played,
            "won": row.get("won") or 0,
            "draw": row.get("draw") or 0,
            "lost": row.get("lost") or 0,
            "points": row.get("points") or 0,
            "goals_for": row.get("goals_for") or 0,
            "goals_against": row.get("goals_against") or 0,
            "goal_difference": row.get("goal_difference") or 0,
        },

        "per_game": {
            "points": round((row.get("points") or 0) / played, 2) if played else 0.0,
            "goals_for": round((row.get("goals_for") or 0) / played, 2) if played else 0.0,
            "goals_against": round((row.get("goals_against") or 0) / played, 2) if played else 0.0,
        },

        "form": get_team_form(team_id, finished_matches),
        "home_away": split_home_away(team_id, finished_matches),

        "strength": {
            "attack_home": round(profile.get("attack_home", 1.0), 2),
            "attack_away": round(profile.get("attack_away", 1.0), 2),
            "defence_home": round(profile.get("defence_home", 1.0), 2),
            "defence_away": round(profile.get("defence_away", 1.0), 2),
            "confidence_level": profile.get("confidence_level"),
            "is_promoted": bool(profile.get("is_promoted")),
            "data_source": profile.get("data_source"),
        },

        "power": power_entry,
    }
