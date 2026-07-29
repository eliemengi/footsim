"""
Aufteilung und Validierung des Saisonspielplans.

Dieses Modul beantwortet zwei Fragen, bevor irgendetwas simuliert wird:

1. Welche Partien der Saison sind gespielt, welche stehen aus,
   welche fallen begruendet heraus?  -> partition_season_matches
2. Ist der Spielplan vollstaendig genug fuer eine serioese
   Saisonprognose?                    -> validate_fixture_coverage

Hintergrund: Ein frueherer Fehler liess die Saisonsimulation nach dem
ersten nicht fertig gespielten Spieltag abbrechen. An Spieltag 0 bekam
sie dadurch nur die 9 bzw. 10 Partien des ersten Spieltags und baute
daraus eine "Saisontabelle". Dieses Modul macht so etwas strukturell
unmoeglich: Es arbeitet ausschliesslich auf dem kompletten Saisonabruf,
und die Validierung verweigert eine Prognose, wenn die Zahlen nicht
aufgehen.

Status-Semantik (football-data.org):

    Ergebnis liegt vor    FINISHED, AWARDED   -> "finished"
    faellt ersatzlos aus  CANCELLED           -> "excluded" (dokumentiert)
    wird noch gespielt    alles andere        -> "remaining"
                          (SCHEDULED, TIMED, POSTPONED, SUSPENDED,
                           IN_PLAY, PAUSED, unbekannte Werte)

Unbekannte Statuswerte landen bewusst bei "remaining": Lieber ein Spiel
zu viel simulieren als eines stillschweigend verlieren. Kein Fixture
verschwindet ohne dokumentierten Grund - jede Partie endet in genau
einer der drei Listen.
"""

# Status, bei denen ein Endergebnis vorliegt.
RESULT_STATUSES = {"FINISHED", "AWARDED"}

# Status, bei denen die Partie ersatzlos entfaellt. Sie reduziert die
# erwartete Gesamtzahl nicht heimlich, sondern wird gezaehlt und im
# Coverage-Report ausgewiesen.
EXCLUDED_STATUSES = {"CANCELLED"}


def partition_season_matches(raw_matches):
    """
    Teilt die rohen Match-Objekte der API in drei Gruppen.

    raw_matches: Liste im football-data-Format (homeTeam, awayTeam,
                 status, score, matchday, utcDate)

    Rueckgabe:
    {
      "finished":  [ {home_id, away_id, home_goals, away_goals, matchday} ],
      "remaining": [ {home_team, away_team, home_id, away_id, matchday} ],
      "excluded":  [ {home_team, away_team, matchday, status, reason} ],
      "played_matchdays": hoechster Spieltag mit Endergebnis,
      "status_counts": { STATUS: Anzahl }
    }
    """
    finished, remaining, excluded = [], [], []
    played_matchdays = 0
    status_counts = {}

    for match in raw_matches or []:
        status = (match.get("status") or "UNBEKANNT").upper()
        status_counts[status] = status_counts.get(status, 0) + 1

        home_team = match.get("homeTeam") or {}
        away_team = match.get("awayTeam") or {}
        home_id = home_team.get("id")
        away_id = away_team.get("id")
        home_name = home_team.get("name") or ""
        away_name = away_team.get("name") or ""
        matchday = match.get("matchday")

        base_info = {
            "home_team": home_name,
            "away_team": away_name,
            "home_id": home_id,
            "away_id": away_id,
            "matchday": matchday,
            "status": status,
        }

        # Ohne Team-IDs ist die Partie nicht zuordenbar. Sie wird nicht
        # still verworfen, sondern als ausgeschlossen dokumentiert - die
        # Coverage-Pruefung schlaegt dann an.
        if home_id is None or away_id is None:
            excluded.append({**base_info, "reason": "missing_team_id"})
            continue

        if status in EXCLUDED_STATUSES:
            excluded.append({**base_info, "reason": "cancelled"})
            continue

        if status in RESULT_STATUSES:
            score = (match.get("score") or {}).get("fullTime") or {}
            home_goals = score.get("home")
            away_goals = score.get("away")

            # Ergebnis-Status ohne Ergebnis: Datenfehler der Quelle.
            # Dokumentieren statt raten.
            if home_goals is None or away_goals is None:
                excluded.append({**base_info, "reason": "result_status_without_score"})
                continue

            finished.append({
                "home_id": home_id,
                "away_id": away_id,
                "home_goals": int(home_goals),
                "away_goals": int(away_goals),
                "matchday": matchday,
            })
            if matchday:
                played_matchdays = max(played_matchdays, matchday)
            continue

        # Alles Uebrige gilt als noch zu spielen.
        remaining.append({
            "home_team": home_name,
            "away_team": away_name,
            "home_id": home_id,
            "away_id": away_id,
            "matchday": matchday,
        })

    return {
        "finished": finished,
        "remaining": remaining,
        "excluded": excluded,
        "played_matchdays": played_matchdays,
        "status_counts": status_counts,
    }


def validate_fixture_coverage(standings_table, finished, remaining, excluded):
    """
    Prueft, ob der Spielplan zur Ligastruktur passt.

    Grundlage ist die Doppelrunde: n Teams spielen n*(n-1) Partien,
    jedes Team 2*(n-1). Fuer jedes Team muss gelten:

        gespielt + offen + dokumentiert ausgeschlossen = 2*(n-1)

    Zusaetzlich darf kein Fixture ein Team referenzieren, das nicht in
    der Tabelle steht.

    Rueckgabe: Coverage-Dict mit complete=True/False und allen Zahlen,
    die noetig sind, um einen Fehlschlag nachzuvollziehen.
    """
    team_ids = [row.get("team_id") for row in standings_table or []]
    team_names = {row.get("team_id"): row.get("team_name") for row in standings_table or []}
    n = len(team_ids)

    expected_per_team = 2 * (n - 1) if n > 1 else 0
    expected_total = n * (n - 1) if n > 1 else 0

    per_team = {tid: {"finished": 0, "remaining": 0, "excluded": 0} for tid in team_ids}
    unknown_team_fixtures = []

    def count(fixture, kind, id_fields, name_fields):
        for id_field, name_field in zip(id_fields, name_fields):
            tid = fixture.get(id_field)
            if tid in per_team:
                per_team[tid][kind] += 1
            else:
                unknown_team_fixtures.append({
                    "kind": kind,
                    "team_id": tid,
                    "team_name": fixture.get(name_field),
                    "matchday": fixture.get("matchday"),
                })

    for fixture in finished:
        count(fixture, "finished", ("home_id", "away_id"), ("home_id", "away_id"))
    for fixture in remaining:
        count(fixture, "remaining", ("home_id", "away_id"), ("home_team", "away_team"))
    for fixture in excluded:
        # Ausgeschlossene tragen teils keine IDs (genau deshalb sind sie
        # ausgeschlossen). Sie zaehlen nur dort, wo eine ID vorliegt.
        for id_field in ("home_id", "away_id"):
            tid = fixture.get(id_field)
            if tid in per_team:
                per_team[tid]["excluded"] += 1

    per_team_problems = []
    for tid, counts in per_team.items():
        total = counts["finished"] + counts["remaining"] + counts["excluded"]
        if total != expected_per_team:
            per_team_problems.append({
                "team_id": tid,
                "team_name": team_names.get(tid),
                "finished": counts["finished"],
                "remaining": counts["remaining"],
                "excluded": counts["excluded"],
                "total": total,
                "expected": expected_per_team,
            })

    fixtures_received = len(finished) + len(remaining) + len(excluded)

    complete = (
        n > 1
        and not per_team_problems
        and not unknown_team_fixtures
        and fixtures_received == expected_total
    )

    return {
        "complete": complete,
        "teams": n,
        "expected_total_matches": expected_total,
        "expected_matches_per_team": expected_per_team,
        "fixtures_received": fixtures_received,
        "fixtures_finished": len(finished),
        "fixtures_to_simulate": len(remaining),
        "fixtures_excluded": len(excluded),
        "fixtures_unknown_team": len(unknown_team_fixtures),
        "excluded_details": excluded[:20],
        "unknown_team_details": unknown_team_fixtures[:20],
        "per_team_problems": per_team_problems[:25],
    }
