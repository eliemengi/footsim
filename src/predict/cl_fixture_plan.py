"""
Fixture-Plan der Champions-League-Ligaphase.

Warum ein eigenes Modul neben fixture_plan.py?
----------------------------------------------
fixture_plan.build_season_plan ist auf das Format einer nationalen Liga
festgelegt. Seine Coverage-Pruefung rechnet mit einer Doppelrunde:

    gesamt   : n * (n - 1)
    pro Team : 2 * (n - 1)

Die CL-Ligaphase ist keine Doppelrunde. Im aktuellen Format spielen 36
Teams je acht Partien gegen acht VERSCHIEDENE Gegner (vier Heim, vier
Auswaerts) - 144 Spiele statt der 1260, die die Domestic-Formel fuer 36
Teams erwarten wuerde. Die Domestic-Validierung wuerde also jeden
CL-Spielplan als kaputt melden.

Dieses Modul filtert deshalb ausschliesslich auf stage == "LEAGUE_STAGE"
und validiert die Struktur AUS DEN DATEN heraus, statt 36/8/144 fest zu
verdrahten: Die Spiele pro Team werden als haeufigster Wert ueber alle
Teams bestimmt, danach muss jedes Team genau diesen Wert haben und die
Gesamtzahl der Partien dazu passen. Aendert die UEFA das Format, traegt
die Pruefung das mit.

Ergaenzend kann der Aufrufer expected_matches_per_team uebergeben (in
app.py stammt der Wert aus CL_LEAGUE_PHASE_CONFIG["total_matchdays"]).
Damit faellt auch ein in sich stimmiger, aber unvollstaendiger
Zwischenstand auf - etwa wenn nach einer Teilauslosung fuer jedes Team
erst vier der acht Partien veroeffentlicht sind.

Datenquelle ist get_all_matches("CL", ...). Diese Funktion bringt bereits
die CL-Saisonvalidierung und die 404-Behandlung mit: eine Saison ohne
Ligaphasendaten liefert dort eine leere Liste statt eines Fehlers. Ein
durchgereichtes ApiUnavailable ist deshalb immer ein echter technischer
Fehler und kein "noch keine Daten"-Fall.
"""

from collections import Counter, defaultdict

from src.api.league_api import get_all_matches, resolve_season


LEAGUE_STAGE = "LEAGUE_STAGE"

# Statuswerte mit verwertbarem Endergebnis.
FINISHED_STATUSES = {"FINISHED", "AWARDED"}

# Statuswerte, die eine noch offene Partie bezeichnen. POSTPONED gehoert
# dazu: die Partie wird nachgeholt und muss simuliert werden.
REMAINING_STATUSES = {
    "SCHEDULED", "TIMED", "POSTPONED", "PAUSED", "IN_PLAY", "SUSPENDED",
}


def build_cl_league_phase_plan(season=None, expected_matches_per_team=None):
    """
    Baut den vollstaendigen Ligaphasen-Spielplan einer CL-Saison.

    Rueckgabe:
    {
      "season": 2025,
      "fixtures":          [ alle Ligaphasen-Partien, gespielt wie offen ],
      "finished_matches":  [ Teilmenge mit Ergebnis ],
      "remaining_matches": [ Teilmenge ohne Ergebnis ],
      "invalid_matches":   [ {match_id, reason, ...} ],
      "teams":             { team_id: {"team_id", "team_name", "crest"} },
      "team_ids":          set,
      "played_matchdays":  hoechster Spieltag mit Ergebnis (0 wenn keiner),
      "coverage":          siehe _validate_coverage,
    }

    Jede Partie in "fixtures" traegt finished=True/False sowie home_goals/
    away_goals (None, solange nicht gespielt). Damit kann der Aufrufer
    dieselbe Liste sowohl fuer eine vollstaendige Neusimulation als auch
    fuer "nur die offenen Partien" verwenden.
    """
    resolved_season = resolve_season("CL", season)
    raw = get_all_matches("CL", season=resolved_season, only_finished=False)

    fixtures = []
    invalid = []
    teams = {}
    seen_match_ids = set()
    per_team = defaultdict(int)
    other_stage_skipped = 0
    played_matchdays = 0

    for match in raw or []:
        # Ausschliesslich Ligaphase. Playoffs, Achtelfinale und alle
        # weiteren K.-o.-Runden gehoeren nicht in diesen Plan.
        if match.get("stage") != LEAGUE_STAGE:
            other_stage_skipped += 1
            continue

        match_id = match.get("id")
        home_id = match.get("home_id")
        away_id = match.get("away_id")
        status = match.get("status")
        home_name = match.get("home_team")
        away_name = match.get("away_team")

        if home_id is None or away_id is None:
            invalid.append(_invalid(match_id, home_name, away_name, status,
                                    "team_id_missing"))
            continue

        if home_id == away_id:
            invalid.append(_invalid(match_id, home_name, away_name, status,
                                    "self_fixture"))
            continue

        if match_id is not None and match_id in seen_match_ids:
            invalid.append(_invalid(match_id, home_name, away_name, status,
                                    "duplicate_fixture_id"))
            continue

        home_goals = match.get("home_goals")
        away_goals = match.get("away_goals")
        has_score = home_goals is not None and away_goals is not None
        is_finished = status in FINISHED_STATUSES and has_score

        if status in FINISHED_STATUSES and not has_score:
            invalid.append(_invalid(match_id, home_name, away_name, status,
                                    "finished_without_score"))
            continue

        if not is_finished and status is not None and status not in REMAINING_STATUSES:
            # CANCELLED oder ein unbekannter Status: nicht simulieren,
            # aber sichtbar protokollieren statt still verschwinden lassen.
            invalid.append(_invalid(match_id, home_name, away_name, status,
                                    f"unhandled_status:{status}"))
            continue

        if match_id is not None:
            seen_match_ids.add(match_id)

        matchday = match.get("matchday")

        fixtures.append({
            "match_id": match_id,
            "matchday": matchday,
            "utc_date": match.get("utc_date"),
            "status": status or "SCHEDULED",
            "home_id": home_id,
            "away_id": away_id,
            "home_team": home_name or str(home_id),
            "away_team": away_name or str(away_id),
            "finished": is_finished,
            "home_goals": int(home_goals) if is_finished else None,
            "away_goals": int(away_goals) if is_finished else None,
        })

        per_team[home_id] += 1
        per_team[away_id] += 1

        teams.setdefault(home_id, {
            "team_id": home_id,
            "team_name": home_name or str(home_id),
            "crest": match.get("home_crest"),
        })
        teams.setdefault(away_id, {
            "team_id": away_id,
            "team_name": away_name or str(away_id),
            "crest": match.get("away_crest"),
        })

        if is_finished and matchday and matchday > played_matchdays:
            played_matchdays = matchday

    coverage = _validate_coverage(
        fixtures=fixtures,
        per_team=per_team,
        invalid=invalid,
        other_stage_skipped=other_stage_skipped,
        expected_matches_per_team=expected_matches_per_team,
    )

    return {
        "season": resolved_season,
        "fixtures": fixtures,
        "finished_matches": [f for f in fixtures if f["finished"]],
        "remaining_matches": [f for f in fixtures if not f["finished"]],
        "invalid_matches": invalid,
        "teams": teams,
        "team_ids": set(per_team.keys()),
        "played_matchdays": played_matchdays,
        "coverage": coverage,
    }


def _invalid(match_id, home_team, away_team, status, reason):
    return {
        "match_id": match_id,
        "home_team": home_team,
        "away_team": away_team,
        "status": status,
        "reason": reason,
    }


def _validate_coverage(fixtures, per_team, invalid, other_stage_skipped,
                       expected_matches_per_team=None):
    """
    Prueft, ob der Ligaphasen-Spielplan vollstaendig und in sich stimmig ist.

    Bewusst OHNE die Domestic-Doppelrundenformel und ohne feste 36/8/144.
    Der Sollwert je Team wird als haeufigster tatsaechlicher Wert bestimmt;
    daran muessen sich alle Teams und die Gesamtzahl messen lassen.

    has_fixtures trennt zwei grundverschiedene Zustaende, die der Aufrufer
    unterschiedlich behandeln muss:
        False -> noch nicht ausgelost, normaler Empty State
        True + ok=False -> Daten da, aber unvollstaendig: echter Fehlerfall
    """
    n_teams = len(per_team)
    problems = []

    if not fixtures:
        return {
            "has_fixtures": False,
            "ok": False,
            "teams": 0,
            "fixtures_total": 0,
            "fixtures_finished": 0,
            "fixtures_remaining": 0,
            "fixtures_rejected": len(invalid),
            "matches_per_team": 0,
            "expected_matches_per_team": expected_matches_per_team,
            "other_stage_skipped": other_stage_skipped,
            "per_team_ok": False,
            "total_ok": False,
            "problems": ["Keine Ligaphasen-Partien fuer diese Saison vorhanden."],
        }

    # Sollwert je Team aus den Daten ableiten statt festverdrahten.
    matches_per_team = Counter(per_team.values()).most_common(1)[0][0]

    off_teams = sorted(
        str(tid) for tid, count in per_team.items() if count != matches_per_team
    )
    per_team_ok = not off_teams
    if not per_team_ok:
        problems.append(
            f"{len(off_teams)} Teams haben nicht {matches_per_team} "
            f"Ligaphasen-Partien im Plan."
        )

    # n Teams mal m Partien zaehlt jede Begegnung doppelt.
    total_ok = (2 * len(fixtures) == n_teams * matches_per_team)
    if not total_ok:
        problems.append(
            f"Gesamtzahl der Partien ({len(fixtures)}) passt nicht zu "
            f"{n_teams} Teams mit je {matches_per_team} Spielen."
        )

    expected_ok = True
    if expected_matches_per_team is not None and matches_per_team != expected_matches_per_team:
        expected_ok = False
        problems.append(
            f"Ligaphase unvollstaendig: {matches_per_team} statt "
            f"{expected_matches_per_team} Partien je Team."
        )

    if invalid:
        problems.append(
            f"{len(invalid)} Partien mit Sonderstatus, siehe invalid_matches."
        )

    return {
        "has_fixtures": True,
        "ok": per_team_ok and total_ok and expected_ok and not invalid,
        "teams": n_teams,
        "fixtures_total": len(fixtures),
        "fixtures_finished": sum(1 for f in fixtures if f["finished"]),
        "fixtures_remaining": sum(1 for f in fixtures if not f["finished"]),
        "fixtures_rejected": len(invalid),
        "matches_per_team": matches_per_team,
        "expected_matches_per_team": expected_matches_per_team,
        "other_stage_skipped": other_stage_skipped,
        "per_team_ok": per_team_ok,
        "total_ok": total_ok,
        "problems": problems,
    }
