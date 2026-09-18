#!/usr/bin/env python
"""
Sammler fuer den Big-Games-Datensatz der Bestenliste (Block C24).

    python collect_big_games.py --season 2025
        Trockenlauf (Standard): KEIN Anbieterabruf. Misst, was lokal schon
        vorliegt und welche Abrufe fehlen.

    python collect_big_games.py --season 2025 --execute --max-provider-requests 200
        Echter Lauf mit hartem Budget (1 bis 500). Fortsetzbar ueber den
        Checkpoint; der Datensatz entsteht erst, wenn die Population
        vollstaendig ist.

    python collect_big_games.py --season 2025 --report pfad.json
        Bericht zusaetzlich als Datei.

EXIT-CODES
----------
    0   Trockenlauf beendet, oder Datensatz vollstaendig geschrieben
    3   Ausfuehrung beendet, Population aber noch unvollstaendig
    5   ein anderer Sammler haelt die Sperre
    2   Aufrufsfehler (z. B. --execute ohne Budget) - vor jedem Abruf
"""

import argparse
import json
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--season", type=int, required=True,
                        help="Saison als Startjahr, z. B. 2025 fuer 2025/26")
    parser.add_argument("--execute", action="store_true",
                        help="echte Anbieterabrufe erlauben (nur mit Budget)")
    parser.add_argument("--max-provider-requests", type=int, default=None,
                        help="Abrufbudget dieses Laufs, 1 bis 500")
    parser.add_argument("--max-players", type=int, default=None,
                        help="hoechstens so viele offene Spieler bearbeiten")
    parser.add_argument("--report", type=str, default=None,
                        help="Bericht zusaetzlich als JSON-Datei schreiben")
    args = parser.parse_args(argv)

    from src.data import big_games_collector as collector

    try:
        report = collector.run(
            args.season,
            execute=args.execute,
            max_provider_requests=args.max_provider_requests,
            max_players=args.max_players,
        )
    except collector.CollectorLocked as error:
        print(f"Sperre belegt: {error}", file=sys.stderr)
        return 5
    except collector.CollectorError as error:
        print(f"Aufrufsfehler: {error}", file=sys.stderr)
        return 2

    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            handle.write(text)

    if report["mode"] == collector.MODE_EXECUTE and not report.get("dataset_written"):
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
