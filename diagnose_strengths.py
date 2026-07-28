"""
Zeigt, worauf die Teamstaerken einer Liga tatsaechlich beruhen.

Aufruf:
    py diagnose_strengths.py bl1
    py diagnose_strengths.py pl --weights

Beantwortet die Frage: Rechnet die Simulation mit echten Daten oder mit
Fallbacks? Fuer jedes Team werden Datenquelle, Fallback-Stufe und
Confidence ausgegeben, dazu die berechneten Angriffs- und Abwehrwerte.

Fallback-Stufen:
    0  Team-ID in der Historie gefunden        (bester Fall)
    1  ueber Namen/Alias gefunden
    2  nur Daten der laufenden Saison
    3  Aufsteiger, empirisches Ligaprofil
    4  Neutralwert                             (schlechtester Fall)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

from src.api.league_api import get_standings
from src.features.strength_provider import get_league_strengths
from src.features.dynamic_weights import weight_table
from src.data.historical_loader import LEAGUE_CODES


LEAGUE_NAMES = {
    "bl1": "Bundesliga",
    "pl": "Premier League",
    "pd": "LaLiga",
    "sa": "Serie A",
    "fl1": "Ligue 1",
}


def print_weights():
    print()
    print("=" * 72)
    print("  Gewichtung Historie / laufende Saison")
    print("=" * 72)
    print(f"  {'gespielt':>9}  {'aktuelle Saison':>16}  {'Historie':>10}")
    print("-" * 72)
    for row in weight_table(34):
        print(f"  {row['matches_played']:>9}  {row['current_pct']:>15.1f} %  "
              f"{row['historical_pct']:>8.1f} %")
    print("=" * 72)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}

    league = (args[0] if args else "bl1").lower()

    if league not in LEAGUE_CODES:
        print(f"Unbekannte Liga: {league}")
        print(f"Moeglich: {', '.join(LEAGUE_CODES)}")
        return

    api_code = LEAGUE_CODES[league]
    name = LEAGUE_NAMES.get(league, league)

    print("=" * 72)
    print(f"  Staerke-Diagnose: {name} ({api_code})")
    print("=" * 72)

    try:
        standings_data = get_standings(api_code)
        table = standings_data.get("tables", {}).get("TOTAL", [])
    except Exception as error:
        print(f"  Tabelle konnte nicht geladen werden: {error}")
        return

    if not table:
        print("  Keine Tabellendaten verfuegbar.")
        return

    result = get_league_strengths(league, table)
    coverage = result["coverage"]
    profiles = result["profiles"]
    summary = result["summary"]
    avg = result["league_avg"]

    print(f"  Ligaschnitt: {avg.get('home_goals', 0):.2f} Heimtore, "
          f"{avg.get('away_goals', 0):.2f} Gasttore pro Spiel")
    print(f"  Historische Saisons geladen: {summary.get('historical_seasons', 0)}")
    print(f"  Aufsteigerprofil: {summary.get('promoted_source', 'unbekannt')}")
    print()

    header = (f"  {'Team':<24}{'ATT_H':>6}{'ATT_A':>6}{'DEF_H':>6}{'DEF_A':>6}"
              f"{'Sp':>4}{'Lv':>3}  {'Quelle':<20}{'Konfidenz':<10}")
    print(header)
    print("-" * 72)

    for entry in sorted(coverage, key=lambda c: c["fallback_level"]):
        profile = profiles.get(entry["team_id"], {})
        name_short = (entry["team_name"] or "")[:23]
        print(f"  {name_short:<24}"
              f"{profile.get('attack_home', 0):>6.2f}"
              f"{profile.get('attack_away', 0):>6.2f}"
              f"{profile.get('defence_home', 0):>6.2f}"
              f"{profile.get('defence_away', 0):>6.2f}"
              f"{entry['matches_used']:>4}"
              f"{entry['fallback_level']:>3}  "
              f"{entry['data_source']:<20}"
              f"{entry['confidence']:.2f} {entry['confidence_level']}")

        if entry.get("alias_used"):
            print(f"    (ueber Alias gefunden: {entry['alias_used']})")

    print("-" * 72)
    print(f"  Teams gesamt:          {summary['teams_total']}")
    print(f"  mit echter Historie:   {summary['teams_with_history']}")
    print(f"  als Aufsteiger:        {summary['teams_promoted']}")
    print(f"  auf Neutralwert:       {summary['teams_neutral']}")
    print(f"  mittlere Konfidenz:    {summary['avg_confidence']:.2f}")
    print(f"  Datenlage belastbar:   {'ja' if summary['reliable'] else 'nein'}")
    print("=" * 72)

    if summary["teams_neutral"] > 0:
        print()
        print("  ACHTUNG: Teams auf Neutralwert bedeuten fehlende Daten.")
        print("  Pruefen:  py refresh_historical.py --report")

    if "--weights" in flags:
        print_weights()


if __name__ == "__main__":
    main()
