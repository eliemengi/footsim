"""
Laedt die historischen Saisondaten fuer alle Ligen herunter.

Aufruf:
    py refresh_historical.py             # laedt, was noch fehlt
    py refresh_historical.py --force     # laedt alles neu
    py refresh_historical.py --report    # zeigt nur, was vorhanden ist

Was passiert:
Fuer jede der fuenf Ligen werden die abgeschlossenen Saisons 2024/25 und
2023/24 von football-data.org geholt und unter data/historical/ als JSON
abgelegt. Das sind insgesamt 10 Requests, einmalig.

Zwischen den Requests wird bewusst gewartet, weil football-data.org im
vorhandenen Tarif 10 Requests pro Minute erlaubt. Der Durchlauf dauert
deshalb rund eine Minute.

Danach arbeitet die Saisonsimulation offline aus diesen Dateien. Die
Dateien gehoeren ins Git-Repository, damit sie beim Deployment auf dem
Server sofort vorliegen und dort keine Requests anfallen.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

from src.data.historical_loader import (
    refresh_all,
    coverage_report,
    AVAILABLE_HISTORICAL_SEASONS,
    LEAGUE_CODES,
    HISTORICAL_DIR,
)


def print_report():
    print("=" * 68)
    print("  Vorhandene historische Daten")
    print("=" * 68)

    rows = coverage_report()
    available = [r for r in rows if r["available"]]

    for row in rows:
        if row["available"]:
            print(f"  {row['api_code']:4} {row['season']}/{str(row['season'] + 1)[2:]}  "
                  f"{row['matches']:4} Spiele  {row['teams']:2} Teams")
        else:
            print(f"  {row['api_code']:4} {row['season']}/{str(row['season'] + 1)[2:]}  "
                  f"FEHLT")

    print("-" * 68)
    print(f"  {len(available)} von {len(rows)} Saisondateien vorhanden")

    if len(available) < len(rows):
        print("  Fehlende Daten holen:  py refresh_historical.py")
    else:
        print("  Alles vollstaendig.")
    print("=" * 68)


def main():
    args = set(sys.argv[1:])

    if "--report" in args:
        print_report()
        return

    force = "--force" in args

    print("=" * 68)
    print("  FootSim: historische Saisondaten laden")
    print("=" * 68)
    print(f"  Ligen:   {', '.join(LEAGUE_CODES.values())}")
    print(f"  Saisons: {', '.join(str(s) for s in AVAILABLE_HISTORICAL_SEASONS)}")
    print(f"  Ziel:    {HISTORICAL_DIR}")
    print(f"  Requests: {len(LEAGUE_CODES) * len(AVAILABLE_HISTORICAL_SEASONS)} "
          f"(mit Pausen wegen Ratenlimit, dauert etwa eine Minute)")
    if force:
        print("  Modus:   --force, vorhandene Dateien werden ueberschrieben")
    print("=" * 68)

    results = refresh_all(force=force, verbose=True)

    loaded = [r for r in results if r["status"] == "geladen"]
    existing = [r for r in results if r["status"] == "vorhanden"]
    failed = [r for r in results if r["status"] == "fehler"]

    print()
    print("=" * 68)
    print(f"  Neu geladen:  {len(loaded)}")
    print(f"  Schon da:     {len(existing)}")
    print(f"  Fehlgeschlagen: {len(failed)}")

    if failed:
        print()
        print("  Fehler im Detail:")
        for row in failed:
            print(f"    {row['api_code']} {row['season']}: {row.get('error')}")

    total_matches = sum(r["matches"] for r in results)
    print(f"  Spiele insgesamt: {total_matches}")
    print("=" * 68)

    if not failed:
        print()
        print("  Fertig. Naechster Schritt:")
        print("    py diagnose_strengths.py bl1")


if __name__ == "__main__":
    main()
