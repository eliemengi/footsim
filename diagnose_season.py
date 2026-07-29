"""
Diagnose der Saisonsimulation - reale Tests je Liga.

Aufruf (auf dem VPS oder lokal mit API-Key):

    py diagnose_season.py            alle Ligen
    py diagnose_season.py pd         nur La Liga
    py diagnose_season.py pd --sims 5000

Gibt je Liga aus:
    Teamanzahl, Fixture-Coverage (gesamt und je Team), Aufsteiger,
    Fallback-Verteilung, uebersprungene/fehlgeschlagene Fixtures,
    danach eine komplette Saisonsimulation mit Prognosetabelle.

Erwartung fuer eine gesunde Liga:
    uebersprungene Fixtures = 0, fehlgeschlagene Fixtures = 0,
    Coverage ok = True, jedes Team 34 bzw. 38 Spiele im Plan.
"""

import sys
import time

from src.api.league_api import get_standings, ApiUnavailable
from src.predict.fixture_plan import build_season_plan
from src.predict.season_sim import simulate_season

LEAGUES = {
    "bl1": ("BL1", "Bundesliga"),
    "pl":  ("PL",  "Premier League"),
    "pd":  ("PD",  "La Liga"),
    "sa":  ("SA",  "Serie A"),
    "fl1": ("FL1", "Ligue 1"),
}


def diagnose_league(key, api_code, name, simulations):
    print(f"\n{'=' * 70}")
    print(f"  {name} ({api_code})")
    print("=" * 70)

    try:
        standings = get_standings(api_code)
    except ApiUnavailable as error:
        print(f"  TABELLE NICHT VERFUEGBAR: {error}")
        return False

    table = (standings.get("tables") or {}).get("TOTAL") or []
    season = standings.get("season")
    print(f"  Saison: {season} | Teams laut Tabelle: {len(table)}")

    try:
        plan = build_season_plan(api_code, season=season,
                                 expected_team_count=len(table))
    except ApiUnavailable as error:
        print(f"  SPIELPLAN NICHT VERFUEGBAR: {error}")
        return False

    cov = plan["coverage"]
    print(f"  Fixtures gesamt:     {cov['fixtures_received']} "
          f"(erwartet {cov['expected_total']})")
    print(f"  davon beendet:       {cov['fixtures_finished']}")
    print(f"  davon offen:         {cov['fixtures_to_simulate']}")
    print(f"  ungueltig/Sonder:    {cov['fixtures_rejected']}")
    print(f"  Spiele je Team:      {cov['expected_per_team']} | "
          f"je Team vollstaendig: {cov['per_team_ok']}")
    print(f"  COVERAGE OK:         {cov['ok']}")
    for problem in cov["problems"]:
        print(f"    ! {problem}")
    for invalid in plan["invalid_matches"][:5]:
        print(f"    ungueltig: {invalid}")

    if not cov["ok"]:
        print("  -> Simulation wird NICHT ausgefuehrt (Plan unvollstaendig).")
        return False

    start = time.time()
    result = simulate_season(
        competition_code=key,
        standings_table=table,
        remaining_matches=plan["remaining_matches"],
        simulations=simulations,
        current_matches=plan["finished_matches"],
        season=season,
        fixture_coverage=cov,
    )
    elapsed = time.time() - start

    quality = result["data_quality"]
    report = result["fixture_report"]
    print(f"\n  Simulation: {simulations} Durchlaeufe in {elapsed:.1f}s")
    print(f"  Historie-Saisons: {quality['historical_season_years']} | "
          f"Vorsaison verfuegbar: {quality['previous_season_available']}")
    print(f"  Teams mit Historie: {quality['teams_with_history']}"
          f"/{quality['teams_total']} | echte Aufsteiger: "
          f"{quality['teams_promoted']} | Status unbekannt: "
          f"{quality['teams_promoted_unknown']} | Neutralwert: "
          f"{quality['teams_neutral']}")
    print(f"  Fixtures simuliert je Durchlauf: "
          f"{report['fixtures_simulated_per_run']} | uebersprungen: "
          f"{report['fixtures_rejected']} | Notprofil noetig: "
          f"{report['fixtures_with_fallback_profile']}")

    print(f"\n  {'Rg':>2} {'Team':<22} {'Ø Pkt':>6} {'Meister':>8} "
          f"{'CL':>6} {'Abstieg':>8}  Quelle")
    for entry in result["entries"]:
        promoted = " [Aufsteiger]" if entry["is_promoted"] is True else ""
        print(f"  {entry['rank']:>2} {entry['team_name']:<22} "
              f"{entry['expected_points']:>6} {entry['champion_pct']:>7}% "
              f"{entry['cl_pct']:>5}% {entry['relegation_pct']:>7}%  "
              f"{entry['data_source']}{promoted}")

    ok = (report["fixtures_rejected"] == 0
          and report["fixtures_simulated_per_run"] == cov["fixtures_to_simulate"])
    print(f"\n  ERGEBNIS: {'OK' if ok else 'PROBLEME - siehe oben'}")
    return ok


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    simulations = 2000
    if "--sims" in sys.argv:
        simulations = int(sys.argv[sys.argv.index("--sims") + 1])

    keys = args or list(LEAGUES.keys())
    results = {}

    for key in keys:
        if key not in LEAGUES:
            print(f"Unbekannte Liga: {key}")
            continue
        api_code, name = LEAGUES[key]
        results[key] = diagnose_league(key, api_code, name, simulations)

    print(f"\n{'=' * 70}")
    print("  ZUSAMMENFASSUNG")
    print("=" * 70)
    for key, ok in results.items():
        print(f"  {LEAGUES[key][1]:<18} {'OK' if ok else 'FEHLER'}")


if __name__ == "__main__":
    main()
