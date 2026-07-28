"""
Prueft, welche API-Sports-Daten mit dem vorhandenen Tarif abrufbar sind.

Aufruf:
    py check_apisports.py           # Budget + Torschuetzen + Verletzungen
    py check_apisports.py --usage   # nur das Budget, kostet nichts extra

Das Skript ist bewusst sparsam: Es prueft eine einzige Liga (Bundesliga)
und verbraucht dabei hoechstens drei Requests. Erst wenn hier alles
funktioniert, lohnt es sich, die Kaderauswertung fuer alle Ligen
einzuschalten.

Hintergrund: Der Free-Plan erlaubt 100 Requests pro Tag. Die
Kaderauswertung in src/features/squad_impact.py braucht zwei Requests je
Liga und Zwoelfstundenfenster, also rund 20 pro Tag fuer alle fuenf Ligen.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

from src.api.apisports_api import (
    get_request_usage,
    get_top_scorers,
    get_injuries,
    LEAGUE_IDS,
    CURRENT_SEASON,
)
from src.features.squad_impact import compute_team_impact


def show_usage(label=""):
    try:
        usage = get_request_usage()
        print(f"  Requests {label}: {usage.get('used')} von {usage.get('limit')} "
              f"benutzt, {usage.get('remaining')} frei")
        return usage
    except Exception as error:
        print(f"  Budget nicht abrufbar: {error}")
        return None


def main():
    flags = set(sys.argv[1:])

    print("=" * 68)
    print("  API-Sports Verfuegbarkeitspruefung")
    print("=" * 68)
    print(f"  Saison laut Konfiguration: {CURRENT_SEASON}")
    print(f"  Bekannte Liga-IDs: {LEAGUE_IDS}")
    print()

    usage_before = show_usage("vorher")

    if "--usage" in flags:
        print("=" * 68)
        return

    print()
    print("-" * 68)
    print("  Test 1: Torschuetzen Bundesliga")
    print("-" * 68)

    scorers = []
    try:
        data = get_top_scorers("bl1", season=CURRENT_SEASON, limit=40)
        scorers = data.get("scorers", []) if isinstance(data, dict) else (data or [])
        print(f"  Ergebnis: {len(scorers)} Spieler")

        for entry in scorers[:5]:
            print(f"    {entry.get('player_name'):<26} "
                  f"{entry.get('goals', 0):>2} Tore  "
                  f"{entry.get('team_name')}")

        if scorers:
            has_photo = sum(1 for s in scorers if s.get("player_photo"))
            print(f"  Mit Foto: {has_photo} von {len(scorers)}")
    except Exception as error:
        print(f"  FEHLER: {error}")

    print()
    print("-" * 68)
    print("  Test 2: Verletzungen Bundesliga")
    print("-" * 68)

    injuries = []
    try:
        data = get_injuries("bl1", season=CURRENT_SEASON)
        injuries = data.get("injuries", []) if isinstance(data, dict) else (data or [])
        print(f"  Ergebnis: {len(injuries)} Meldungen")

        for entry in injuries[:5]:
            print(f"    {str(entry.get('player_name')):<26} "
                  f"{str(entry.get('type')):<18} {entry.get('team_name')}")
    except Exception as error:
        print(f"  FEHLER: {error}")

    print()
    print("-" * 68)
    print("  Test 3: Berechnete Kaderwirkung")
    print("-" * 68)

    if not scorers:
        print("  Nicht moeglich, es fehlen die Torschuetzendaten.")
    else:
        impact = compute_team_impact(scorers, injuries)
        if not impact:
            print("  Keine Auswirkung berechenbar.")
        else:
            affected = {tid: e for tid, e in impact.items()
                        if e["attack_modifier"] < 1.0}
            print(f"  Teams in der Auswertung: {len(impact)}")
            print(f"  davon durch Ausfaelle geschwaecht: {len(affected)}")

            for team_id, entry in sorted(
                affected.items(), key=lambda kv: kv[1]["attack_modifier"]
            )[:6]:
                names = ", ".join(p["player_name"] for p in entry["missing_players"])
                print(f"    Team {team_id}: Faktor {entry['attack_modifier']:.2f} "
                      f"(fehlend: {names})")

    print()
    usage_after = show_usage("nachher")

    if usage_before and usage_after:
        used = (usage_after.get("used", 0) or 0) - (usage_before.get("used", 0) or 0)
        print(f"  Dieser Durchlauf hat {used} Request(s) gekostet.")

    print("=" * 68)
    print()
    print("  Bewertung:")
    if scorers and injuries:
        print("    Beide Quellen liefern Daten. Die Kaderauswertung kann")
        print("    eingeschaltet bleiben (Standard).")
    elif scorers:
        print("    Torschuetzen ja, Verletzungen nein. Die Kaderauswertung")
        print("    laeuft dann ohne Ausfallberuecksichtigung.")
    else:
        print("    Keine verwertbaren Daten. Die Simulation arbeitet weiter")
        print("    ausschliesslich mit football-data.org, was voellig genuegt.")
    print("=" * 68)


if __name__ == "__main__":
    main()
