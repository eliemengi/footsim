"""
FootSim - API Diagnose

Prueft, ob dein API Key funktioniert, welche Saison football-data.org
gerade als aktuell fuehrt und wie weit jede Liga ist.

Aufruf im Projektordner mit aktiviertem venv:

    py check_api.py

Verbraucht etwa fuenf bis sechs Requests von deinem Tageslimit.
"""

import os
import sys
import time
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("FOOTBALL_API_KEY")
BASE_URL = "https://api.football-data.org/v4"

LEAGUES = [
    ("bl1", "BL1", "Bundesliga"),
    ("pl",  "PL",  "Premier League"),
    ("pd",  "PD",  "LaLiga"),
    ("sa",  "SA",  "Serie A"),
    ("fl1", "FL1", "Ligue 1"),
]


def line(char="-", width=68):
    print(char * width)


def main():
    print()
    line("=")
    print("  FootSim API Diagnose")
    line("=")
    print()

    if not API_KEY:
        print("  FEHLER: FOOTBALL_API_KEY nicht gefunden.")
        print("  Pruefe, ob die Datei .env im Projektordner liegt und")
        print("  eine Zeile FOOTBALL_API_KEY=... enthaelt.")
        sys.exit(1)

    print(f"  API Key gefunden: {API_KEY[:6]}...{API_KEY[-4:]}")
    print()

    headers = {"X-Auth-Token": API_KEY}
    results = []
    suggested = {}

    for code, api_code, name in LEAGUES:
        try:
            response = requests.get(
                f"{BASE_URL}/competitions/{api_code}",
                headers=headers,
                timeout=20
            )
        except requests.RequestException as error:
            print(f"  {name:18} NETZWERKFEHLER  {error}")
            results.append(False)
            continue

        if response.status_code == 429:
            print(f"  {name:18} RATE LIMIT erreicht, kurz warten und neu starten")
            results.append(False)
            time.sleep(7)
            continue

        if response.status_code == 403:
            print(f"  {name:18} NICHT IM PLAN enthalten")
            results.append(False)
            continue

        if response.status_code != 200:
            print(f"  {name:18} FEHLER  HTTP {response.status_code}")
            results.append(False)
            continue

        data = response.json()
        season = data.get("currentSeason") or {}

        start = season.get("startDate") or "?"
        matchday = season.get("currentMatchday")
        season_year = start[:4] if len(start) >= 4 else "?"

        try:
            label = f"{season_year}/{str(int(season_year) + 1)[2:]}"
        except ValueError:
            label = season_year

        print(f"  {name:18} Saison {label}   aktueller Spieltag: {matchday}   ab {start}")

        results.append(True)

        if matchday:
            suggested[code] = matchday

        # Freundlich zum Rate Limit bleiben
        time.sleep(1)

    print()
    line()

    if not any(results):
        print("  Keine Liga konnte geladen werden. Pruefe API Key und Internetverbindung.")
        print()
        return

    print()
    print("  VORSCHLAG FUER app.py")
    line()
    print("  Wenn du alle bisher gespielten Spieltage freischalten willst,")
    print("  setze in app.py bei LEAGUE_CONFIG jeweils:")
    print()

    for code, api_code, name in LEAGUES:
        if code in suggested:
            current = suggested[code]
            if current <= 1:
                value = "[1]"
            else:
                value = f"list(range(1, {current + 1}))"
            print(f'    "{code}": ...  "unlocked_matchdays": {value},   # {name}, aktuell Spieltag {current}')

    print()
    print("  Alternativ in app.py ganz oben setzen:")
    print()
    print("    UNLOCK_ALL_MATCHDAYS = True")
    print()
    print("  Dann sind alle Spieltage sofort spielbar.")
    print()
    line("=")
    print()


if __name__ == "__main__":
    main()
