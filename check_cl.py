"""
FootSim - Champions League Datenpruefung

Beantwortet die Frage, ob football-data.org fuer eine Saison die
K o Runden mit Phasenangabe liefert. Genau davon haengt ab, ob der
Ligenvergleich innerhalb der Champions League funktioniert.

Aufruf im Projektordner mit aktiviertem venv:

    py check_cl.py            prueft die Vorsaison
    py check_cl.py 2026       prueft eine bestimmte Saison

Verbraucht etwa zwei Requests.
"""

import os
import sys
import requests
from collections import Counter
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("FOOTBALL_API_KEY")
BASE_URL = "https://api.football-data.org/v4"

# Muss zu STAGE_ALIASES in src/features/cl_stats.py passen
BEKANNTE_PHASEN = {
    "LEAGUE_STAGE": "Ligaphase",
    "GROUP_STAGE": "Gruppenphase",
    "GROUPS": "Gruppenphase",
    "PLAYOFFS": "Playoffs",
    "PLAY_OFF_ROUND": "Playoffs",
    "PLAYOFF_ROUND": "Playoffs",
    "KNOCKOUT_PLAYOFFS": "Playoffs",
    "LAST_16": "Achtelfinale",
    "ROUND_OF_16": "Achtelfinale",
    "QUARTER_FINALS": "Viertelfinale",
    "QUARTER_FINAL": "Viertelfinale",
    "SEMI_FINALS": "Halbfinale",
    "SEMI_FINAL": "Halbfinale",
    "FINAL": "Finale",
    "THIRD_PLACE": "Spiel um Platz drei",
}


def line(char="-", width=70):
    print(char * width)


def hole(pfad, params=None):
    response = requests.get(
        f"{BASE_URL}{pfad}",
        headers={"X-Auth-Token": API_KEY},
        params=params,
        timeout=25,
    )

    if response.status_code == 429:
        print("  Rate Limit erreicht. Bitte eine Minute warten und erneut starten.")
        sys.exit(1)

    if response.status_code == 403:
        print("  Dieser Datenpunkt ist im aktuellen API Plan nicht enthalten.")
        sys.exit(1)

    if response.status_code != 200:
        print(f"  Fehler: HTTP {response.status_code}")
        sys.exit(1)

    return response.json()


def main():
    print()
    line("=")
    print("  FootSim - Champions League Datenpruefung")
    line("=")
    print()

    if not API_KEY:
        print("  FEHLER: FOOTBALL_API_KEY nicht gefunden. Liegt die .env im Ordner?")
        sys.exit(1)

    # Saison bestimmen
    if len(sys.argv) > 1:
        try:
            saison = int(sys.argv[1])
        except ValueError:
            print("  Ungueltige Saison. Beispiel: py check_cl.py 2025")
            sys.exit(1)
    else:
        info = hole("/competitions/CL")
        start = (info.get("currentSeason") or {}).get("startDate", "")
        aktuell = int(start[:4]) if len(start) >= 4 else 2026
        saison = aktuell - 1
        print(f"  Laufende Champions League Saison: {aktuell}/{str(aktuell + 1)[2:]}")
        print(f"  Geprueft wird die Vorsaison:      {saison}/{str(saison + 1)[2:]}")
        print()

    daten = hole("/competitions/CL/matches", {"season": saison, "status": "FINISHED"})
    spiele = daten.get("matches", [])

    if not spiele:
        print(f"  Keine beendeten Spiele fuer die Saison {saison} gefunden.")
        print("  Der Champions League Vergleich ist fuer diese Saison nicht moeglich.")
        print()
        return

    print(f"  Gefundene beendete Spiele: {len(spiele)}")
    print()

    phasen = Counter(m.get("stage") or "OHNE_ANGABE" for m in spiele)

    line()
    print("  GEFUNDENE PHASEN")
    line()

    unbekannt = []

    for phase, anzahl in phasen.most_common():
        if phase in BEKANNTE_PHASEN:
            print(f"    {BEKANNTE_PHASEN[phase]:22} {anzahl:>4} Spiele    (API: {phase})")
        else:
            print(f"    NICHT ERKANNT          {anzahl:>4} Spiele    (API: {phase})")
            unbekannt.append(phase)

    print()
    line()

    ko_phasen = [p for p in phasen if p in BEKANNTE_PHASEN and BEKANNTE_PHASEN[p] != "Ligaphase"
                 and BEKANNTE_PHASEN[p] != "Gruppenphase"]

    hat_finale = any(BEKANNTE_PHASEN.get(p) == "Finale" for p in phasen)

    if ko_phasen and hat_finale:
        print("  ERGEBNIS: Alles vorhanden.")
        print("  Ligaphase und K o Runden sind da, das Finale ebenfalls.")
        print("  Der Champions League Vergleich funktioniert fuer diese Saison")
        print("  in allen drei Varianten: Komplett, Ligaphase und K o Phase.")
    elif ko_phasen:
        print("  ERGEBNIS: K o Runden vorhanden, aber kein Finale.")
        print("  Der Vergleich funktioniert, der Titelgewinner wird jedoch")
        print("  nicht ausgewiesen.")
    else:
        print("  ERGEBNIS: Nur Ligaphase vorhanden.")
        print("  Der Vergleich funktioniert nur mit der Einstellung Ligaphase.")

    if unbekannt:
        print()
        print("  ACHTUNG: Unbekannte Phasenbezeichnungen gefunden:")
        for phase in unbekannt:
            print(f"    {phase}")
        print()
        print("  Diese Spiele werden aktuell uebersprungen. Schick mir die")
        print("  Bezeichnungen, dann ergaenze ich sie in cl_stats.py.")

    # Stichprobe fuer das Finale
    finale = [m for m in spiele if m.get("stage") == "FINAL"]

    if finale:
        spiel = finale[-1]
        heim = (spiel.get("homeTeam") or {}).get("name")
        gast = (spiel.get("awayTeam") or {}).get("name")
        ergebnis = (spiel.get("score") or {}).get("fullTime") or {}
        sieger = (spiel.get("score") or {}).get("winner")

        print()
        line()
        print("  STICHPROBE FINALE")
        line()
        print(f"    {heim} {ergebnis.get('home')}:{ergebnis.get('away')} {gast}")
        print(f"    Siegerfeld der API: {sieger}")

        if sieger in ("HOME_TEAM", "AWAY_TEAM"):
            gewinner = heim if sieger == "HOME_TEAM" else gast
            print(f"    Erkannter Titelgewinner: {gewinner}")
        else:
            print("    Titelgewinner wird ueber Tore und Elfmeter bestimmt")

    print()
    line("=")
    print()


if __name__ == "__main__":
    main()
