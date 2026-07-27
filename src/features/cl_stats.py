"""
Ligenvergleich innerhalb eines Pokalwettbewerbs, vor allem der Champions League.

Grundgedanke:
Alle Vereine einer Liga werden fuer den Vergleich wie eine einzige Mannschaft
behandelt. Ihre Ergebnisse werden zusammengezaehlt und dann pro Spiel
normiert, damit Ligen mit unterschiedlich vielen Teilnehmern vergleichbar
bleiben. Vereine ohne Teilnahme tauchen nicht auf und verzerren nichts.

Das Modul rechnet nur. Es macht keine API Aufrufe.
"""


# ---------------------------------------------------------------------------
# Turnierphasen
# ---------------------------------------------------------------------------

# Die API kennt je nach Saison und Wettbewerb unterschiedliche Bezeichnungen.
# Hier werden sie auf eine einheitliche interne Reihenfolge gebracht.
STAGE_ALIASES = {
    "LEAGUE_STAGE":      "league",
    "GROUP_STAGE":       "league",
    "GROUPS":            "league",
    "PLAYOFFS":          "playoff",
    "PLAY_OFF_ROUND":    "playoff",
    "PLAYOFF_ROUND":     "playoff",
    "KNOCKOUT_PLAYOFFS": "playoff",
    "LAST_16":           "r16",
    "ROUND_OF_16":       "r16",
    "QUARTER_FINALS":    "qf",
    "QUARTER_FINAL":     "qf",
    "SEMI_FINALS":       "sf",
    "SEMI_FINAL":        "sf",
    "FINAL":             "final",
    "THIRD_PLACE":       "final",
}

# Reihenfolge der Phasen. Der Index dient gleichzeitig als Turniertiefe.
STAGE_ORDER = ["league", "playoff", "r16", "qf", "sf", "final"]

STAGE_LABELS = {
    "league":  "Ligaphase",
    "playoff": "Playoffs",
    "r16":     "Achtelfinale",
    "qf":      "Viertelfinale",
    "sf":      "Halbfinale",
    "final":   "Finale",
}

# Welche Phasen gehoeren zu welcher Auswahl im Frontend
PHASE_FILTERS = {
    "all":      STAGE_ORDER,
    "league":   ["league"],
    "knockout": ["playoff", "r16", "qf", "sf", "final"],
}

PHASE_LABELS = {
    "all":      "Komplette Saison",
    "league":   "Nur Ligaphase",
    "knockout": "Nur K o Phase",
}


def normalize_stage(raw_stage):
    """Wandelt die API Bezeichnung in eine interne Phase um."""
    if not raw_stage:
        return None
    return STAGE_ALIASES.get(str(raw_stage).upper())


# ---------------------------------------------------------------------------
# Zuordnung Verein zu Liga
# ---------------------------------------------------------------------------

def build_team_league_map(league_teams_by_code):
    """
    Baut aus den Vereinslisten der einzelnen Ligen eine Zuordnung
    team_id -> liga_code.

    league_teams_by_code: { "bl1": {team_id: {...}}, "pl": {...}, ... }
    """
    mapping = {}

    for league_code, teams in league_teams_by_code.items():
        for team_id in teams:
            # Erste Zuordnung gewinnt. Ein Verein kann nicht in zwei
            # nationalen Ligen gleichzeitig spielen.
            if team_id not in mapping:
                mapping[team_id] = league_code

    return mapping


# ---------------------------------------------------------------------------
# Kennzahlen je Liga
# ---------------------------------------------------------------------------

def _empty_counters():
    return {
        "matches": 0,
        "wins": 0,
        "draws": 0,
        "losses": 0,
        "goals_for": 0,
        "goals_against": 0,
        "clean_sheets": 0,
        "failed_to_score": 0,
        "biggest_win": None,
        # Duelle zweier Vereine derselben Liga. Sie werden aus beiden
        # Perspektiven gezaehlt, weshalb sie die Siegquote zwangslaeufig
        # in Richtung fuenfzig Prozent ziehen. Der Wert wird ausgewiesen,
        # damit das im Frontend nachvollziehbar bleibt.
        "intra_league_matches": 0,
    }


def _register_result(counters, goals_for, goals_against, opponent, own_team):
    counters["matches"] += 1
    counters["goals_for"] += goals_for
    counters["goals_against"] += goals_against

    if goals_against == 0:
        counters["clean_sheets"] += 1

    if goals_for == 0:
        counters["failed_to_score"] += 1

    if goals_for > goals_against:
        counters["wins"] += 1
        margin = goals_for - goals_against
        current = counters["biggest_win"]

        if current is None or margin > current["margin"]:
            counters["biggest_win"] = {
                "margin": margin,
                "label": f"{own_team} {goals_for}:{goals_against} {opponent}",
            }

    elif goals_for == goals_against:
        counters["draws"] += 1
    else:
        counters["losses"] += 1


def collect_league_results(matches, team_league_map, allowed_stages):
    """
    Zaehlt alle Ergebnisse pro Liga zusammen.

    Wichtig: Ein Spiel zaehlt fuer BEIDE beteiligten Ligen, jeweils aus
    der eigenen Perspektive. Treffen zwei Vereine derselben Liga
    aufeinander, wird das Spiel fuer diese Liga zweimal gezaehlt, einmal
    als Sieg und einmal als Niederlage. Das ist korrekt, weil sich Siege
    und Niederlagen dann gegenseitig aufheben und die Torbilanz stimmt.
    """
    per_league = {}
    stage_set = set(allowed_stages)

    for match in matches:
        stage = normalize_stage(match.get("stage"))

        if stage is None or stage not in stage_set:
            continue

        home_league = team_league_map.get(match.get("home_id"))
        away_league = team_league_map.get(match.get("away_id"))

        is_intra_league = (
            home_league is not None
            and away_league is not None
            and home_league == away_league
        )

        if home_league:
            counters = per_league.setdefault(home_league, _empty_counters())
            _register_result(
                counters,
                match["home_goals"],
                match["away_goals"],
                match.get("away_team") or "Gegner",
                match.get("home_team") or "Team",
            )
            if is_intra_league:
                counters["intra_league_matches"] += 1

        if away_league:
            counters = per_league.setdefault(away_league, _empty_counters())
            _register_result(
                counters,
                match["away_goals"],
                match["home_goals"],
                match.get("home_team") or "Gegner",
                match.get("away_team") or "Team",
            )
            if is_intra_league:
                counters["intra_league_matches"] += 1

    return per_league


# ---------------------------------------------------------------------------
# Turnierverlauf: wer kam wie weit
# ---------------------------------------------------------------------------

def collect_stage_participation(matches):
    """
    Ermittelt je Phase, welche Vereine daran teilgenommen haben.
    Rueckgabe: { "league": {team_ids}, "r16": {team_ids}, ... }
    """
    participation = {stage: set() for stage in STAGE_ORDER}

    for match in matches:
        stage = normalize_stage(match.get("stage"))

        if stage is None:
            continue

        for key in ("home_id", "away_id"):
            team_id = match.get(key)
            if team_id is not None:
                participation[stage].add(team_id)

    return participation


def find_winner(matches):
    """Ermittelt den Sieger des Finales, falls das Finale gespielt wurde."""
    finals = [m for m in matches if normalize_stage(m.get("stage")) == "final"]

    if not finals:
        return None

    # Bei mehreren Treffern das spaeteste Spiel nehmen
    final = sorted(finals, key=lambda m: m.get("utc_date") or "")[-1]

    winner = final.get("winner")

    if winner == "HOME_TEAM":
        return final.get("home_id")
    if winner == "AWAY_TEAM":
        return final.get("away_id")

    # Kein winner Feld: ueber Elfmeterschiessen oder Tore entscheiden
    pen_home = final.get("penalties_home")
    pen_away = final.get("penalties_away")

    if pen_home is not None and pen_away is not None and pen_home != pen_away:
        return final["home_id"] if pen_home > pen_away else final["away_id"]

    if final["home_goals"] != final["away_goals"]:
        return final["home_id"] if final["home_goals"] > final["away_goals"] else final["away_id"]

    return None


def compute_progression(participation, winner_id, team_league_map, league_codes):
    """
    Turniertiefe und Weiterkommensquote je Liga.

    Turniertiefe eines Vereins:
        1 = nur Ligaphase
        2 = Playoffs erreicht
        3 = Achtelfinale
        4 = Viertelfinale
        5 = Halbfinale
        6 = Finale
        7 = Titel gewonnen

    Weiterkommensquote:
        Anteil der K o Duelle, die Vereine dieser Liga ueberstanden haben.
        Ein Verein hat eine Runde ueberstanden, wenn er in der naechsten
        Phase wieder auftaucht. Das ist deutlich robuster, als Hin und
        Rueckspiel nachzurechnen, weil Verlaengerung und Elfmeterschiessen
        automatisch mit abgedeckt sind.
    """
    result = {}

    # Nur Phasen betrachten, die tatsaechlich gespielt wurden. Der Modus der
    # Champions League hat sich mehrfach geaendert, und in einer laufenden
    # Saison sind die spaeteren Runden noch gar nicht ausgetragen. Wuerde man
    # stur die naechste Phase aus der festen Liste nehmen, gaelte jedes
    # gewonnene Duell als verloren, sobald eine Runde fehlt.
    active_stages = [stage for stage in STAGE_ORDER if participation.get(stage)]

    for league_code in league_codes:
        depths = []
        ties_played = 0
        ties_won = 0

        # Alle Vereine dieser Liga, die ueberhaupt teilgenommen haben
        participants = {
            team_id
            for team_id, code in team_league_map.items()
            if code == league_code and any(team_id in participation[s] for s in STAGE_ORDER)
        }

        reached_counts = {stage: 0 for stage in STAGE_ORDER}

        for team_id in participants:
            depth = 0

            for index, stage in enumerate(STAGE_ORDER, start=1):
                if team_id in participation[stage]:
                    depth = index
                    reached_counts[stage] += 1

            if winner_id is not None and team_id == winner_id:
                depth = len(STAGE_ORDER) + 1

            depths.append(depth)

            # Duelle zaehlen: jede K o Runde, in der der Verein stand
            for index, stage in enumerate(active_stages):
                if stage == "league":
                    continue
                if team_id not in participation[stage]:
                    continue

                ties_played += 1

                is_last_played_stage = index == len(active_stages) - 1

                if stage == "final":
                    # Das Finale gilt nur mit dem Titel als gewonnen
                    if winner_id is not None and team_id == winner_id:
                        ties_won += 1
                elif is_last_played_stage:
                    # Runde laeuft noch, Ausgang offen. Nicht als
                    # bestrittenes Duell werten, sonst waere jedes
                    # noch nicht entschiedene Duell automatisch verloren.
                    ties_played -= 1
                else:
                    next_stage = active_stages[index + 1]
                    if team_id in participation[next_stage]:
                        ties_won += 1

        team_count = len(participants)

        result[league_code] = {
            "teams": team_count,
            "teams_in_knockout": sum(
                1 for team_id in participants
                if any(team_id in participation[s] for s in STAGE_ORDER[1:])
            ),
            "avg_depth": round(sum(depths) / team_count, 2) if team_count else None,
            "max_depth": max(depths) if depths else None,
            "ties_played": ties_played,
            "ties_won": ties_won,
            "advance_rate": round(100.0 * ties_won / ties_played, 1) if ties_played else None,
            "reached": {
                STAGE_LABELS[stage]: reached_counts[stage]
                for stage in STAGE_ORDER
            },
            "is_champion": winner_id is not None and winner_id in participants,
        }

    return result


# ---------------------------------------------------------------------------
# Profil je Liga zusammenbauen
# ---------------------------------------------------------------------------

def build_cup_profile(league_code, league_name, emblem, counters, progression):
    """Fasst Ergebnisse und Turnierverlauf zu einem Profil zusammen."""
    counters = counters or _empty_counters()
    progression = progression or {}

    matches = counters["matches"]
    points = counters["wins"] * 3 + counters["draws"]

    def per_match(value, digits=2):
        return round(value / matches, digits) if matches else None

    def percent(value, digits=1):
        return round(100.0 * value / matches, digits) if matches else None

    return {
        "code": league_code,
        "name": league_name,
        "emblem": emblem,
        "metrics": {
            "teams": progression.get("teams", 0),
            "teams_in_knockout": progression.get("teams_in_knockout", 0),
            "matches": matches,
            "intra_league_matches": counters["intra_league_matches"],
            "wins": counters["wins"],
            "draws": counters["draws"],
            "losses": counters["losses"],
            "points": points,
            "points_per_match": per_match(points),
            "win_percent": percent(counters["wins"]),
            "draw_percent": percent(counters["draws"]),
            "loss_percent": percent(counters["losses"]),
            "goals_for": counters["goals_for"],
            "goals_against": counters["goals_against"],
            "goals_for_per_match": per_match(counters["goals_for"]),
            "goals_against_per_match": per_match(counters["goals_against"]),
            "goal_difference": counters["goals_for"] - counters["goals_against"],
            "goal_difference_per_match": per_match(counters["goals_for"] - counters["goals_against"]),
            "clean_sheet_percent": percent(counters["clean_sheets"]),
            "failed_to_score_percent": percent(counters["failed_to_score"]),
            "avg_depth": progression.get("avg_depth"),
            "advance_rate": progression.get("advance_rate"),
            "ties_played": progression.get("ties_played", 0),
            "ties_won": progression.get("ties_won", 0),
        },
        "reached": progression.get("reached", {}),
        "is_champion": progression.get("is_champion", False),
        "biggest_win": counters.get("biggest_win"),
    }


# ---------------------------------------------------------------------------
# Vergleichstabelle
# ---------------------------------------------------------------------------

CUP_ROWS = [
    {"key": "teams",                     "label": "Teilnehmende Vereine",   "unit": "",   "better": None,  "group": "Teilnahme"},
    {"key": "teams_in_knockout",         "label": "Davon in der K o Phase", "unit": "",   "better": True,  "group": "Teilnahme"},
    {"key": "matches",                   "label": "Ausgetragene Spiele",    "unit": "",   "better": None,  "group": "Teilnahme"},
    {"key": "intra_league_matches",      "label": "Davon ligainterne Duelle", "unit": "",  "better": None,  "group": "Teilnahme"},

    {"key": "points_per_match",          "label": "Punkte pro Spiel",       "unit": "",   "better": True,  "group": "Leistung"},
    {"key": "win_percent",               "label": "Siegquote",              "unit": " %", "better": True,  "group": "Leistung"},
    {"key": "draw_percent",              "label": "Remisquote",             "unit": " %", "better": None,  "group": "Leistung"},
    {"key": "loss_percent",              "label": "Niederlagenquote",       "unit": " %", "better": False, "group": "Leistung"},

    {"key": "goals_for_per_match",       "label": "Erzielte Tore pro Spiel", "unit": "",  "better": True,  "group": "Tore"},
    {"key": "goals_against_per_match",   "label": "Gegentore pro Spiel",    "unit": "",   "better": False, "group": "Tore"},
    {"key": "goal_difference_per_match", "label": "Tordifferenz pro Spiel", "unit": "",   "better": True,  "group": "Tore"},
    {"key": "clean_sheet_percent",       "label": "Spiele ohne Gegentor",   "unit": " %", "better": True,  "group": "Tore"},
    {"key": "failed_to_score_percent",   "label": "Spiele ohne eigenes Tor", "unit": " %", "better": False, "group": "Tore"},
]

PROGRESSION_ROWS = [
    {"key": "avg_depth",    "label": "Durchschnittlich erreichte Runde", "unit": "",   "better": True},
    {"key": "advance_rate", "label": "Weiterkommensquote",               "unit": " %", "better": True},
    {"key": "ties_played",  "label": "Bestrittene K o Duelle",           "unit": "",   "better": None},
    {"key": "ties_won",     "label": "Davon ueberstanden",               "unit": "",   "better": True},
]


# Gewichtung fuer das Gesamtranking.
# Zwei Saetze, weil in der reinen Ligaphase noch niemand weitergekommen ist
# und die Turnierkennzahlen dort keine Aussage haetten.
RANKING_WEIGHTS_WITH_KNOCKOUT = {
    "advance_rate":              0.30,
    "win_percent":               0.25,
    "goal_difference_per_match": 0.20,
    "points_per_match":          0.15,
    "goals_for_per_match":       0.10,
}

RANKING_WEIGHTS_LEAGUE_ONLY = {
    "points_per_match":          0.35,
    "win_percent":               0.30,
    "goal_difference_per_match": 0.20,
    "goals_for_per_match":       0.15,
}


def _normalize_scores(profiles, metric_key):
    """
    Normiert eine Kennzahl auf eine Skala von 0 bis 100.

    Bezugspunkt ist der beste beobachtete Wert, nicht die Spanne zwischen
    bestem und schlechtestem. Sonst bekaeme bei nur zwei verglichenen Ligen
    die schlechtere zwangslaeufig eine Null, was den Abstand masslos
    uebertreiben wuerde.

    Negative Werte, etwa eine negative Tordifferenz, werden vorher nach
    oben verschoben, damit die Skala nicht kippt.
    """
    values = {}

    for profile in profiles:
        value = profile["metrics"].get(metric_key)
        if value is not None:
            values[profile["code"]] = float(value)

    if not values:
        return {}

    minimum = min(values.values())
    shift = -minimum if minimum < 0 else 0.0

    shifted = {code: value + shift for code, value in values.items()}
    maximum = max(shifted.values())

    if maximum <= 0:
        # Alle Werte gleich null: niemand hat einen Vorteil
        return {code: 50.0 for code in shifted}

    return {code: round(100.0 * value / maximum, 1) for code, value in shifted.items()}


def build_ranking(profiles, include_knockout):
    """
    Gewichtetes Gesamtranking der verglichenen Ligen.

    Jede Kennzahl wird auf 0 bis 100 normiert und dann mit ihrem Gewicht
    verrechnet. Die verwendeten Gewichte werden mit ausgeliefert, damit im
    Frontend nachvollziehbar ist, wie das Ergebnis zustande kommt.
    """
    weights = RANKING_WEIGHTS_WITH_KNOCKOUT if include_knockout else RANKING_WEIGHTS_LEAGUE_ONLY

    normalized = {key: _normalize_scores(profiles, key) for key in weights}

    scored = []

    for profile in profiles:
        code = profile["code"]
        total = 0.0
        used_weight = 0.0
        breakdown = []

        for key, weight in weights.items():
            score = normalized.get(key, {}).get(code)

            if score is None:
                continue

            total += score * weight
            used_weight += weight

            breakdown.append({
                "key": key,
                "label": _label_for(key),
                "weight_percent": round(weight * 100),
                "raw": profile["metrics"].get(key),
                "score": score,
            })

        # Fehlende Kennzahlen sollen keine Liga bestrafen
        final_score = round(total / used_weight, 1) if used_weight else 0.0

        scored.append({
            "code": code,
            "name": profile["name"],
            "emblem": profile.get("emblem"),
            "score": final_score,
            "is_champion": profile.get("is_champion", False),
            "teams": profile["metrics"].get("teams", 0),
            "breakdown": breakdown,
        })

    scored.sort(key=lambda entry: entry["score"], reverse=True)

    for position, entry in enumerate(scored, start=1):
        entry["position"] = position

    return {
        "entries": scored,
        "weights": [
            {"label": _label_for(key), "weight_percent": round(weight * 100)}
            for key, weight in weights.items()
        ],
        "basis": "mit K o Phase" if include_knockout else "nur Ligaphase",
    }


def _label_for(metric_key):
    for row in CUP_ROWS + PROGRESSION_ROWS:
        if row["key"] == metric_key:
            return row["label"]
    return metric_key


def _build_row(definition, profiles):
    values = {p["code"]: p["metrics"].get(definition["key"]) for p in profiles}
    numeric = {code: value for code, value in values.items() if value is not None}

    winner = None

    if definition.get("better") is True and numeric:
        winner = max(numeric, key=numeric.get)
    elif definition.get("better") is False and numeric:
        winner = min(numeric, key=numeric.get)

    if winner is not None and len(set(numeric.values())) <= 1:
        winner = None

    return {
        "key": definition["key"],
        "label": definition["label"],
        "unit": definition.get("unit", ""),
        "group": definition.get("group", ""),
        "values": values,
        "winner": winner,
    }


def build_cup_comparison(profiles, phase, include_knockout):
    """Baut die komplette Antwort fuer das Frontend."""
    sections = []

    for title in ["Teilnahme", "Leistung", "Tore"]:
        rows = [_build_row(d, profiles) for d in CUP_ROWS if d["group"] == title]
        if rows:
            sections.append({"title": title, "rows": rows})

    if include_knockout:
        sections.append({
            "title": "Turnierverlauf",
            "rows": [_build_row(d, profiles) for d in PROGRESSION_ROWS],
        })

    return {
        "phase": phase,
        "phase_label": PHASE_LABELS.get(phase, phase),
        "include_knockout": include_knockout,
        "leagues": [
            {
                "code": p["code"],
                "name": p["name"],
                "emblem": p.get("emblem"),
                "teams": p["metrics"].get("teams", 0),
                "is_champion": p.get("is_champion", False),
                "biggest_win": p.get("biggest_win"),
            }
            for p in profiles
        ],
        "sections": sections,
        "reached": [
            {"code": p["code"], "name": p["name"], "stages": p.get("reached", {})}
            for p in profiles
        ] if include_knockout else [],
        "ranking": build_ranking(profiles, include_knockout),
    }
