"""
Vollstaendiger Saisonspielplan fuer die Saisonsimulation.

Warum dieses Modul existiert
----------------------------
Die Saisonsimulation braucht ALLE Spiele einer Saison - abgeschlossene
als reale Ergebnisse, offene als zu simulierende Fixtures. Frueher wurde
dafuer die Spieltag-Logik der Einzelspielansicht mitbenutzt. Die brach
beim ersten nicht komplett gespielten Spieltag ab, wodurch an Spieltag 0
nur 9 bzw. 10 Fixtures (ein einziger Spieltag) in der Simulation
landeten. Genau dieser Datenfluss ist hier sauber getrennt:

    Einzelspielansicht  -> get_matchday_matches (ein Spieltag, UI-Sperre)
    Saisonsimulation    -> build_season_plan    (die GESAMTE Saison)

Ein einziger API-Request (/competitions/{code}/matches?season=YYYY)
liefert alle 306 bzw. 380 Partien. Das Ergebnis liegt im Disk-Cache,
damit Neustarts und mehrere Gunicorn-Worker das Minutenlimit der API
nicht sprengen.

Fixture-Status
--------------
Jede Partie bekommt genau einen Status. Nichts verschwindet stillschweigend:

    finished            FINISHED/AWARDED mit Endergebnis -> reale Tabelle
    remaining           SCHEDULED/TIMED/POSTPONED/PAUSED/IN_PLAY/SUSPENDED
                        -> wird simuliert
    explicitly_invalid  fehlende Team-IDs, fehlendes Ergebnis trotz
                        FINISHED, o.ae. -> protokolliert mit Grund

Harte Validierung
-----------------
Vor der Simulation wird geprueft, ob der Spielplan vollstaendig ist:

    gesamt   : finished + remaining + invalid == n * (n - 1)
    pro Team : finished_i + remaining_i       == 2 * (n - 1)

Schlaegt das fehl, liefert coverage_ok=False mit Diagnosedaten. Der
Aufrufer (app.py) zeigt dann eine klare Fehlermeldung statt einer
serioes wirkenden, aber falschen Tabelle.
"""

from collections import defaultdict

from src.api.league_api import _get_json, resolve_season, ApiUnavailable
from src.utils.disk_cache import disk_cached_call
from src.utils.cache import TTL_MATCHES_UPCOMING


# Statuswerte von football-data.org, die als "noch zu spielen" gelten.
# POSTPONED bleibt eine offene Partie: sie wird nachgeholt und muss
# deshalb simuliert werden.
REMAINING_STATUSES = {
    "SCHEDULED", "TIMED", "POSTPONED", "PAUSED", "IN_PLAY", "SUSPENDED",
}

# Statuswerte, die ein verwertbares Endergebnis tragen.
FINISHED_STATUSES = {"FINISHED", "AWARDED"}


def _fetch_full_season(api_code, season):
    """Alle Spiele einer Saison, roh von der API. Ein einziger Request."""
    data = _get_json(
        f"/competitions/{api_code}/matches",
        params={"season": season},
    )
    return data.get("matches", [])


def load_full_season_matches(api_code, season=None):
    """
    Alle Spiele der Saison, ueber den Disk-Cache.

    Der Cache-Key entspricht bewusst dem Muster season_full_matches:CODE:JAHR,
    damit vorhandene Cache-Dateien weiterverwendet werden.
    """
    season = resolve_season(api_code, season)
    return disk_cached_call(
        key=f"season_full_matches:{api_code}:{season}",
        ttl_seconds=TTL_MATCHES_UPCOMING,
        loader=lambda: _fetch_full_season(api_code, season),
        source="football-data.org",
    ), season


def build_season_plan(api_code, season=None, expected_team_count=None):
    """
    Baut den vollstaendigen Saisonplan mit Statuszuordnung und Validierung.

    Rueckgabe:
    {
      "season": 2026,
      "finished_matches":  [ {home_id, away_id, home_goals, away_goals,
                              matchday} ],          # fuer Form/Tabelle
      "remaining_matches": [ {home_team, away_team, home_id, away_id,
                              matchday, status} ],  # fuer die Simulation
      "invalid_matches":   [ {match_id, home_team, away_team, reason,
                              status} ],
      "team_ids":          set gefundener Team-IDs,
      "played_matchdays":  hoechster Spieltag mit mindestens einem
                           beendeten Spiel (0 vor Saisonstart),
      "coverage": {
          "fixtures_received": 380, "fixtures_finished": 0,
          "fixtures_to_simulate": 380, "fixtures_rejected": 0,
          "expected_total": 380, "teams": 20,
          "per_team_ok": True, "total_ok": True, "ok": True,
          "problems": [],
      },
    }
    """
    raw_matches, season = load_full_season_matches(api_code, season)

    finished = []
    remaining = []
    invalid = []
    team_ids = set()
    played_matchdays = 0

    per_team_finished = defaultdict(int)
    per_team_remaining = defaultdict(int)

    for match in raw_matches:
        # Nur die Ligaphase zaehlt. BL1-Relegation o.ae. haette einen
        # anderen stage-Wert und wuerde die 306/380-Rechnung verfaelschen.
        stage = match.get("stage")
        if stage and stage != "REGULAR_SEASON":
            continue

        home = match.get("homeTeam") or {}
        away = match.get("awayTeam") or {}
        home_id = home.get("id")
        away_id = away.get("id")
        status = match.get("status")
        matchday = match.get("matchday")

        if home_id is None or away_id is None:
            invalid.append({
                "match_id": match.get("id"),
                "home_team": home.get("name"),
                "away_team": away.get("name"),
                "status": status,
                "reason": "team_id_missing",
            })
            continue

        team_ids.add(home_id)
        team_ids.add(away_id)

        if status in FINISHED_STATUSES:
            score = (match.get("score") or {}).get("fullTime") or {}
            home_goals = score.get("home")
            away_goals = score.get("away")

            if home_goals is None or away_goals is None:
                invalid.append({
                    "match_id": match.get("id"),
                    "home_team": home.get("name"),
                    "away_team": away.get("name"),
                    "status": status,
                    "reason": "finished_without_score",
                })
                continue

            finished.append({
                "home_id": home_id,
                "away_id": away_id,
                "home_goals": int(home_goals),
                "away_goals": int(away_goals),
                "matchday": matchday,
            })
            per_team_finished[home_id] += 1
            per_team_finished[away_id] += 1
            if matchday and matchday > played_matchdays:
                played_matchdays = matchday

        elif status in REMAINING_STATUSES or status is None:
            remaining.append({
                "home_team": home.get("name") or "",
                "away_team": away.get("name") or "",
                "home_id": home_id,
                "away_id": away_id,
                "home_crest": home.get("crest"),
                "away_crest": away.get("crest"),
                "matchday": matchday,
                "status": status or "SCHEDULED",
            })
            per_team_remaining[home_id] += 1
            per_team_remaining[away_id] += 1

        else:
            # CANCELLED oder ein unbekannter Status: nicht simulieren,
            # aber sichtbar protokollieren.
            invalid.append({
                "match_id": match.get("id"),
                "home_team": home.get("name"),
                "away_team": away.get("name"),
                "status": status,
                "reason": f"unhandled_status:{status}",
            })

    coverage = _validate_coverage(
        team_ids=team_ids,
        finished=finished,
        remaining=remaining,
        invalid=invalid,
        per_team_finished=per_team_finished,
        per_team_remaining=per_team_remaining,
        expected_team_count=expected_team_count,
    )

    return {
        "season": season,
        "finished_matches": finished,
        "remaining_matches": remaining,
        "invalid_matches": invalid,
        "team_ids": team_ids,
        "played_matchdays": played_matchdays,
        "coverage": coverage,
    }


def _validate_coverage(team_ids, finished, remaining, invalid,
                       per_team_finished, per_team_remaining,
                       expected_team_count=None):
    """
    Fixture-Coverage-Pruefung: Zaehlt die TATSAECHLICHEN Spiele, statt
    Spieltag x Spiele-pro-Spieltag anzunehmen. Verschobene Partien
    verfaelschen die Rechnung dadurch nicht.
    """
    n = len(team_ids)
    problems = []

    if expected_team_count is not None and n != expected_team_count:
        problems.append(
            f"Teamanzahl im Spielplan ({n}) weicht von der Tabelle "
            f"({expected_team_count}) ab."
        )

    expected_total = n * (n - 1) if n > 1 else 0
    expected_per_team = 2 * (n - 1) if n > 1 else 0

    total_accounted = len(finished) + len(remaining) + len(invalid)
    total_ok = (total_accounted == expected_total)
    if not total_ok:
        problems.append(
            f"Gesamtzahl der Spiele ({total_accounted}) entspricht nicht "
            f"der Doppelrunde ({expected_total})."
        )

    per_team_ok = True
    for team_id in team_ids:
        have = per_team_finished.get(team_id, 0) + per_team_remaining.get(team_id, 0)
        if have != expected_per_team:
            per_team_ok = False
            problems.append(
                f"Team {team_id}: {have} statt {expected_per_team} Spiele "
                f"im Plan."
            )

    # Ungueltige Spiele machen den Plan nicht automatisch unbrauchbar,
    # solange die Gesamtrechnung aufgeht - aber sie werden benannt.
    if invalid:
        problems.append(f"{len(invalid)} Spiele mit Sonderstatus, siehe invalid_matches.")

    return {
        "fixtures_received": total_accounted,
        "fixtures_finished": len(finished),
        "fixtures_to_simulate": len(remaining),
        "fixtures_rejected": len(invalid),
        "expected_total": expected_total,
        "expected_per_team": expected_per_team,
        "teams": n,
        "total_ok": total_ok,
        "per_team_ok": per_team_ok,
        "ok": total_ok and per_team_ok,
        "problems": problems,
    }
