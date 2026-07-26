"""
Kennzahlen fuer Ligenvergleiche.

Zweck von FootSim an dieser Stelle: Behauptungen ueber Ligen mit Zahlen
belegen oder widerlegen, statt sie zu diskutieren.

Alle Funktionen hier sind reine Berechnungen. Sie machen keine
API Aufrufe und lassen sich damit auch isoliert testen.
"""

import statistics


def _safe_divide(numerator, denominator, digits=2):
    if not denominator:
        return None
    return round(numerator / denominator, digits)


def _percent(part, whole, digits=1):
    if not whole:
        return None
    return round(100.0 * part / whole, digits)


def compute_match_metrics(matches):
    """
    Kennzahlen, die sich nur aus Einzelergebnissen berechnen lassen.

    matches: Liste aus league_api.get_finished_season_matches
    """
    total = len(matches)

    if total == 0:
        return {
            "matches_played": 0,
            "goals_total": 0,
            "goals_per_match": None,
            "home_wins": 0,
            "draws": 0,
            "away_wins": 0,
            "home_win_percent": None,
            "draw_percent": None,
            "away_win_percent": None,
            "home_goals_per_match": None,
            "away_goals_per_match": None,
            "home_advantage": None,
            "btts_percent": None,
            "over_2_5_percent": None,
            "over_3_5_percent": None,
            "clean_sheet_percent": None,
            "goalless_percent": None,
            "highest_scoring_match": None,
        }

    goals_home = 0
    goals_away = 0
    home_wins = 0
    draws = 0
    away_wins = 0
    btts = 0
    over_2_5 = 0
    over_3_5 = 0
    clean_sheets = 0
    goalless = 0

    top_match = None
    top_goals = -1

    for match in matches:
        home = match["home_goals"]
        away = match["away_goals"]
        combined = home + away

        goals_home += home
        goals_away += away

        if home > away:
            home_wins += 1
        elif home < away:
            away_wins += 1
        else:
            draws += 1

        if home > 0 and away > 0:
            btts += 1

        if combined > 2.5:
            over_2_5 += 1

        if combined > 3.5:
            over_3_5 += 1

        # Zu-Null-Spiel liegt vor, wenn mindestens eine Seite ohne Gegentor bleibt
        if home == 0 or away == 0:
            clean_sheets += 1

        if combined == 0:
            goalless += 1

        if combined > top_goals:
            top_goals = combined
            top_match = match

    goals_total = goals_home + goals_away

    home_percent = _percent(home_wins, total)
    away_percent = _percent(away_wins, total)

    return {
        "matches_played": total,
        "goals_total": goals_total,
        "goals_per_match": _safe_divide(goals_total, total),
        "home_wins": home_wins,
        "draws": draws,
        "away_wins": away_wins,
        "home_win_percent": home_percent,
        "draw_percent": _percent(draws, total),
        "away_win_percent": away_percent,
        "home_goals_per_match": _safe_divide(goals_home, total),
        "away_goals_per_match": _safe_divide(goals_away, total),
        "home_advantage": round(home_percent - away_percent, 1) if home_percent is not None and away_percent is not None else None,
        "btts_percent": _percent(btts, total),
        "over_2_5_percent": _percent(over_2_5, total),
        "over_3_5_percent": _percent(over_3_5, total),
        "clean_sheet_percent": _percent(clean_sheets, total),
        "goalless_percent": _percent(goalless, total),
        "highest_scoring_match": {
            "label": f"{top_match['home_team']} {top_match['home_goals']}:{top_match['away_goals']} {top_match['away_team']}",
            "goals": top_goals,
            "matchday": top_match.get("matchday"),
        } if top_match else None,
    }


def compute_balance_metrics(total_table):
    """
    Wie ausgeglichen ist eine Liga?

    Punkte pro Spiel statt absoluter Punkte, weil Ligen unterschiedlich
    weit fortgeschritten sein koennen und sonst nicht vergleichbar waeren.

    total_table: die TOTAL Tabelle aus league_api.get_standings
    """
    ppg_values = []

    for row in total_table:
        played = row.get("played") or 0
        if played > 0:
            ppg_values.append(row["points"] / played)

    if len(ppg_values) < 2:
        return {
            "teams": len(ppg_values),
            "ppg_top": None,
            "ppg_bottom": None,
            "ppg_spread": None,
            "ppg_stdev": None,
            "balance_score": None,
        }

    ppg_values.sort(reverse=True)
    top = ppg_values[0]
    bottom = ppg_values[-1]
    spread = top - bottom
    stdev = statistics.pstdev(ppg_values)

    # Balance Score von 0 bis 100. Hoeher bedeutet ausgeglichener.
    # Eine Standardabweichung von 0.8 Punkten pro Spiel gilt hier als
    # sehr unausgeglichen und ergibt den Wert 0.
    balance = max(0.0, min(100.0, (1 - (stdev / 0.8)) * 100))

    return {
        "teams": len(ppg_values),
        "ppg_top": round(top, 2),
        "ppg_bottom": round(bottom, 2),
        "ppg_spread": round(spread, 2),
        "ppg_stdev": round(stdev, 3),
        "balance_score": round(balance, 1),
    }


def build_league_profile(competition_code, competition_name, standings, matches):
    """
    Fasst alles zu einem Profil je Liga zusammen.
    Das ist die Struktur, die das Frontend bekommt.
    """
    total_table = (standings.get("tables") or {}).get("TOTAL") or []

    match_metrics = compute_match_metrics(matches)
    balance_metrics = compute_balance_metrics(total_table)

    leader = total_table[0] if total_table else None

    return {
        "code": competition_code,
        "name": competition_name,
        "season": standings.get("season"),
        "emblem": standings.get("competition_emblem"),
        "leader": {
            "team_name": leader["team_name"],
            "crest": leader.get("crest"),
            "points": leader["points"],
            "played": leader["played"],
        } if leader else None,
        "metrics": match_metrics,
        "balance": balance_metrics,
    }


# Definition der Vergleichszeilen fuer das Frontend.
# higher_is_better steuert, welcher Wert farblich hervorgehoben wird.
# None bedeutet: es gibt kein besser oder schlechter, nur anders.
COMPARISON_ROWS = [
    {"key": "goals_per_match",     "label": "Tore pro Spiel",          "unit": "",   "higher_is_better": True,  "group": "Offensive"},
    {"key": "over_2_5_percent",    "label": "Spiele ueber 2,5 Tore",   "unit": "%",  "higher_is_better": True,  "group": "Offensive"},
    {"key": "over_3_5_percent",    "label": "Spiele ueber 3,5 Tore",   "unit": "%",  "higher_is_better": True,  "group": "Offensive"},
    {"key": "btts_percent",        "label": "Beide Teams treffen",     "unit": "%",  "higher_is_better": True,  "group": "Offensive"},
    {"key": "goalless_percent",    "label": "Torlose Spiele",          "unit": "%",  "higher_is_better": False, "group": "Offensive"},
    {"key": "clean_sheet_percent", "label": "Spiele mit einem Zu Null", "unit": "%", "higher_is_better": False, "group": "Defensive"},
    {"key": "home_win_percent",    "label": "Heimsiege",               "unit": "%",  "higher_is_better": None,  "group": "Ergebnisse"},
    {"key": "draw_percent",        "label": "Unentschieden",           "unit": "%",  "higher_is_better": None,  "group": "Ergebnisse"},
    {"key": "away_win_percent",    "label": "Auswaertssiege",          "unit": "%",  "higher_is_better": None,  "group": "Ergebnisse"},
    {"key": "home_advantage",      "label": "Heimvorteil",             "unit": "%P", "higher_is_better": None,  "group": "Ergebnisse"},
    {"key": "home_goals_per_match", "label": "Heimtore pro Spiel",     "unit": "",   "higher_is_better": None,  "group": "Ergebnisse"},
    {"key": "away_goals_per_match", "label": "Auswaertstore pro Spiel", "unit": "",  "higher_is_better": None,  "group": "Ergebnisse"},
    {"key": "matches_played",      "label": "Ausgewertete Spiele",     "unit": "",   "higher_is_better": None,  "group": "Datenbasis"},
]

BALANCE_ROWS = [
    {"key": "balance_score", "label": "Ausgeglichenheit",       "unit": "/100", "higher_is_better": True},
    {"key": "ppg_spread",    "label": "Abstand Erster zu Letzter", "unit": " P/Sp", "higher_is_better": False},
    {"key": "ppg_top",       "label": "Punkte pro Spiel Erster",  "unit": "",   "higher_is_better": None},
    {"key": "ppg_bottom",    "label": "Punkte pro Spiel Letzter", "unit": "",   "higher_is_better": None},
]


def build_comparison(profiles):
    """
    Baut die fertige Vergleichstabelle.

    Fuer jede Kennzahl wird ermittelt, welche Liga vorne liegt.
    Bei higher_is_better = None gibt es keinen Gewinner, die Zeile
    ist rein informativ.
    """
    rows = []

    for definition in COMPARISON_ROWS:
        values = {}

        for profile in profiles:
            values[profile["code"]] = profile["metrics"].get(definition["key"])

        rows.append(_build_row(definition, values, profiles))

    balance_rows = []

    for definition in BALANCE_ROWS:
        values = {}

        for profile in profiles:
            values[profile["code"]] = profile["balance"].get(definition["key"])

        balance_rows.append(_build_row(definition, values, profiles))

    return {
        "leagues": [
            {
                "code": p["code"],
                "name": p["name"],
                "emblem": p.get("emblem"),
                "season": p.get("season"),
                "leader": p.get("leader"),
            }
            for p in profiles
        ],
        "sections": [
            {"title": "Offensive", "rows": [r for r in rows if r["group"] == "Offensive"]},
            {"title": "Defensive", "rows": [r for r in rows if r["group"] == "Defensive"]},
            {"title": "Ergebnisse", "rows": [r for r in rows if r["group"] == "Ergebnisse"]},
            {"title": "Wettbewerb", "rows": balance_rows},
            {"title": "Datenbasis", "rows": [r for r in rows if r["group"] == "Datenbasis"]},
        ],
    }


def _build_row(definition, values, profiles):
    """Ermittelt fuer eine Kennzahl den Gewinner und formatiert die Zeile."""
    numeric = {code: value for code, value in values.items() if value is not None}

    winner = None

    if definition.get("higher_is_better") is True and numeric:
        winner = max(numeric, key=numeric.get)
    elif definition.get("higher_is_better") is False and numeric:
        winner = min(numeric, key=numeric.get)

    # Kein Gewinner markieren, wenn alle Ligen denselben Wert haben
    if winner is not None and len(set(numeric.values())) <= 1:
        winner = None

    return {
        "key": definition["key"],
        "label": definition["label"],
        "unit": definition.get("unit", ""),
        "group": definition.get("group", ""),
        "values": values,
        "winner": winner,
        "has_winner": winner is not None,
    }
