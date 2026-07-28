"""
Einmaliges Diagnose-Skript: prueft, welche Ligen football-data.org
vollstaendig liefert und wie weit die Saison-Historie zurueckreicht.

Aufruf:
    py check_season_depth.py

Ergebnis wird nur ausgegeben, nicht gespeichert.
"""
import sys
sys.path.insert(0, ".")

from src.api.league_api import _get_json

print("=" * 60)
print("  Ligen-Abdeckung Saison 2025/26")
print("=" * 60)

for code in ["BL1", "PL", "PD", "SA", "FL1"]:
    try:
        data = _get_json(
            f"/competitions/{code}/matches",
            params={"season": 2025, "status": "FINISHED"},
        )
        matches = data.get("matches", [])
        teams = set()
        for m in matches:
            teams.add((m.get("homeTeam") or {}).get("name"))
            teams.add((m.get("awayTeam") or {}).get("name"))
        print(f"  {code:5} {len(matches):4} Spiele, {len(teams):2} Teams")
    except Exception as e:
        print(f"  {code:5} FEHLER: {e}")

print()
print("=" * 60)
print("  Saison-Tiefe Bundesliga (wie weit zurueck?)")
print("=" * 60)

for season in [2024, 2023, 2022, 2021]:
    try:
        data = _get_json(
            "/competitions/BL1/matches",
            params={"season": season, "status": "FINISHED"},
        )
        n = len(data.get("matches", []))
        print(f"  Saison {season}/{str(season + 1)[2:]}: {n} Spiele")
    except Exception as e:
        print(f"  Saison {season}/{str(season + 1)[2:]}: NICHT VERFUEGBAR ({str(e)[:70]})")

print()
print("Fertig.")
