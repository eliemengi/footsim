"""
Big-Games-Datensatz OHNE Netz aus dem lokalen Cache neu bauen (V2).

WOZU
----
Mit V2 aendern sich Spielfelder (Gegnerband, Phase) und der Vertrag des
Datensatzes. Ein nach V1 gesammelter Datensatz traegt diese Felder nicht
und wird deshalb - richtigerweise - nicht mehr angenommen.

Neu SAMMELN waere dafuer der falsche Weg: die Spieldaten selbst haben
sich nicht geaendert, nur ihre Auswertung. Dieses Werkzeug rechnet
deshalb ausschliesslich aus dem, was lokal bereits liegt.

GARANTIE: KEIN EINZIGER ANBIETERABRUF
-------------------------------------
Es laeuft mit genau dem Tor des Sammlers im Trockenlauf
(RequestGate(execute=False, max_requests=0)):

    * vorhandener Eintrag -> wird benutzt, auch wenn seine Frist abgelaufen
      ist (disk_cache faellt bei einem Fehler im Loader auf den
      vorhandenen Eintrag zurueck)
    * fehlender Eintrag   -> wird abgewiesen, nie geladen

Am Ende wird ausgegeben, wie viele Abrufe stattgefunden haben. Diese Zahl
MUSS 0 sein; andernfalls bricht das Werkzeug ab, bevor es schreibt.

AUFRUF
------
    python rebuild_big_games_dataset.py --season 2025
    python rebuild_big_games_dataset.py --season 2025 --limit 50   (Probe)
"""

import argparse
import sys
import time

from src.data import big_games_dataset as dataset
from src.data.big_games_collector import RequestGate, season_population, source_problem
from src.data.big_games_loader import compute_player_big_games_uncached
from src.utils import disk_cache


def rebuild(season, limit=None, verbose=True):
    population, used_leagues, duplicate_entries = season_population(season)
    player_ids = sorted(population)
    if limit:
        player_ids = player_ids[:limit]

    gate = RequestGate(execute=False, max_requests=0)
    rows = []
    fifa_years = set()
    ohne_daten = 0
    fehler = {}
    started = time.time()

    with disk_cache.request_gate(gate), disk_cache.read_memo():
        for index, player_id in enumerate(player_ids, 1):
            gate.begin_player()
            try:
                result = compute_player_big_games_uncached(player_id, season, season)
            except Exception as error:      # ein Spieler darf den Lauf nie beenden
                fehler[type(error).__name__] = fehler.get(type(error).__name__, 0) + 1
                result = None

            problem = source_problem(result) if result is not None else None
            if result is None or problem:
                ohne_daten += 1
            else:
                row = dataset.build_player_row(population[player_id], season, result)
                rows.append(row)
                for match in row["matches"]:
                    if match.get("source") == "national" and match.get("date"):
                        fifa_years.add(int(str(match["date"])[:4]))

            if verbose and index % 250 == 0:
                print(f"  {index}/{len(player_ids)} Spieler, "
                      f"{gate.used} Abrufe, {len(rows)} Zeilen "
                      f"({time.time() - started:.0f}s)", flush=True)

    if gate.used:
        raise SystemExit(
            f"ABBRUCH: {gate.used} Anbieterabrufe stattgefunden - "
            "es wird nichts geschrieben.")

    print(f"\nSpieler verarbeitet: {len(player_ids)}")
    print(f"Zeilen gebaut:       {len(rows)}")
    print(f"Ohne verwertbare Daten: {ohne_daten}")
    print(f"Fehler: {fehler or 'keine'}")
    print(f"Anbieterabrufe: {gate.used} (muss 0 sein)")
    print(f"Aus abgelaufenen, lokal vorhandenen Eintraegen: {len(gate.stale_keys)}")
    print(f"Lokal fehlende Eintraege (abgewiesen): {len(gate.missing_keys)}")
    print(f"Dauer: {time.time() - started:.0f}s")

    if limit:
        print("\n--limit gesetzt: Probelauf, es wird NICHT geschrieben.")
        return rows

    document = dataset.build_dataset(
        season,
        rows,
        population={
            "source": "top5_player_pools",
            "leagues": used_leagues,
            "players": len(player_ids),
            "duplicate_pool_entries": duplicate_entries,
        },
        collector_meta={
            "rebuilt_offline": True,
            "source": "local_cache_only",
            "provider_requests": gate.used,
        },
        fifa_years=sorted(fifa_years),
    )
    dataset.write_dataset(document)
    print(f"\nGeschrieben: {dataset.dataset_path(season)}")
    print(f"Vertrag: {document['contract_version']}")
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=dataset.PILOT_SEASON)
    parser.add_argument("--limit", type=int, default=None,
                        help="Nur die ersten N Spieler, ohne zu schreiben.")
    args = parser.parse_args(argv)
    rebuild(args.season, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
