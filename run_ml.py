"""
CLI fuer die ML-Vorbereitung.

AUFRUF
------
    py run_ml.py --build-dataset
    py run_ml.py --build-dataset --leagues bl1 --seasons 2024
    py run_ml.py --build-dataset --output data/ml/dataset_2023-2025.json

In dieser Phase gibt es genau eine Aufgabe: den Datensatz bauen. Es
wird kein Modell trainiert, kein Artefakt geladen und nichts am
produktiven Simulationspfad veraendert.

Ohne --output schreibt das Skript keine Datei, sondern fasst zusammen.
Mit --output schreibt es nur, wenn das Ziel frei ist oder --force
ausdruecklich gesetzt wurde.
"""

import argparse
import json
import os
import platform
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Git-Angaben aus dem Backtestlaeufer wiederverwenden. Zwei Fassungen
# derselben Funktion wuerden auseinanderlaufen, und genau dieses Feld
# musste im Backtestlaeufer bereits einmal korrigiert werden.
from run_backtests import git_arbeitsstand, git_commit  # noqa: E402
from src.ml import dataset as ds  # noqa: E402

#: Die Quellen, aus denen der Datensatz entsteht. Ausdruecklich im
#: Manifest, weil die Auswahl eine Entscheidung war: data/player_pool
#: steht in .gitignore und faellt deshalb aus.
DATENQUELLEN = ["data/historical"]


def build_payload(leagues, seasons, min_matchday, zeilen, diagnose):
    """
    Manifest, Schema und Zeilen - getrennt.

    Wie beim Backtestlaeufer: Alles Variable steht im Manifest, damit
    zwei Laeufe an rows und schema vergleichbar bleiben.
    """
    stand = git_arbeitsstand()
    schema = ds.build_schema()

    return {
        "manifest": {
            "schema_version": ds.SCHEMA_VERSION,
            "git_commit": git_commit(),
            "git_dirty": None if stand is None else stand["dirty"],
            "git_status": stand,
            "leagues": list(leagues),
            "seasons": list(seasons),
            "min_matchday": min_matchday,
            "total_rows": diagnose["total_rows"],
            "evaluation_eligible_rows": diagnose["evaluation_eligible_rows"],
            "warmup_rows": diagnose["warmup_rows"],
            "columns": list(ds.SPALTEN),
            "column_count": len(ds.SPALTEN),
            "data_sources": list(DATENQUELLEN),
            "excluded_sources": ["data/player_pool (gitignored, GO5)"],
            "created_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            "python_version": platform.python_version(),
            "platform": platform.system(),
        },
        "schema": schema,
        "rows": zeilen,
        "diagnostics": {
            "per_league_season": diagnose["per_league_season"],
            "skipped": diagnose["skipped"],
            "cold_start_rows": diagnose["cold_start_rows"],
            "neutral_profile_rows": diagnose["neutral_profile_rows"],
            "rows_without_outcome": diagnose["rows_without_outcome"],
            "missingness": ds.missingness(zeilen),
        },
    }


def print_summary(payload, kennzahlen, abdeckung):
    m = payload["manifest"]
    d = payload["diagnostics"]

    print()
    print(f"  Ligen            {', '.join(m['leagues'])}")
    print(f"  Saisons          {', '.join(str(s) for s in m['seasons'])}")
    print(f"  min_matchday     {m['min_matchday']}")
    print(f"  Quellen          {', '.join(m['data_sources'])}")
    print(f"  Spalten          {m['column_count']}")

    stand = m.get("git_status")
    if m.get("git_dirty"):
        print(f"  Git              {(m['git_commit'] or '?')[:12]}  DIRTY: "
              f"{len(stand['modified'])} geaendert, "
              f"{len(stand['untracked'])} unversioniert")
    else:
        print(f"  Git              {(m['git_commit'] or '?')[:12]}")

    print()
    print(f"  Zeilen gesamt              {m['total_rows']}")
    print(f"  davon auswertbar           {m['evaluation_eligible_rows']}")
    print(f"  davon Aufwaermphase        {m['warmup_rows']}")
    print(f"  mit Kaltstartprofil        {d['cold_start_rows']}")
    print(f"  mit neutralem Profil       {d['neutral_profile_rows']}")

    print()
    print(f"  {'Liga':6} {'Saison':>7} {'Zeilen':>7} {'auswertbar':>11} "
          f"{'Aufwaerm':>9} {'Kaltstart':>10}")
    for eintrag in d["per_league_season"]:
        print(f"  {eintrag['league']:6} {eintrag['season']:7} "
              f"{eintrag['rows']:7} {eintrag['evaluation_eligible']:11} "
              f"{eintrag['warmup']:9} {eintrag['cold_start_rows']:10}")

    fehlend = {s: n for s, n in d["missingness"].items() if n}
    print()
    if fehlend:
        print("  Spalten mit fehlenden Werten:")
        for spalte, anzahl in sorted(fehlend.items(),
                                     key=lambda p: (-p[1], p[0])):
            anteil = anzahl / m["total_rows"] * 100
            print(f"     {spalte:38} {anzahl:6} ({anteil:5.1f}%)")
    else:
        print("  Keine Spalte hat fehlende Werte.")

    if abdeckung:
        print()
        print("  Crosswalk-Abdeckung der Pokalspiele in der Zeitleiste:")
        print("  (Nenner: ALLE Partien der Datei inkl. Qualifikationsrunden.")
        print("   Amateurpaarungen sind im football-data-ID-Raum nicht")
        print("   vorhanden - das erklaert eine niedrige Quote, belegt aber")
        print("   NICHT, dass keine Erstligapartie fehlt.)")
        print(f"     {'Wettbewerb':12} {'in Dateien':>11} {'zugeordnet':>11} "
              f"{'Abdeckung':>10}")
        for eintrag in abdeckung:
            quote = ("-" if eintrag["coverage"] is None
                     else f"{eintrag['coverage'] * 100:9.1f}%")
            print(f"     {eintrag['competition']:12} "
                  f"{eintrag['matches_in_files']:11} "
                  f"{eintrag['matches_covered']:11} {quote:>10}")

    if kennzahlen:
        # Die bekannten Erwartungswerte gelten fuer den VOLLEN Umfang -
        # fuenf Ligen, drei Saisons. Bei einem Teillauf waeren sie ein
        # falscher Vergleich und werden deshalb nicht angezeigt.
        voll = (sorted(m["leagues"]) == sorted(ds.DEFAULT_LEAGUES)
                and sorted(m["seasons"]) == sorted(ds.DEFAULT_SEASONS))
        print()
        print("  Baseline ueber die auswertbaren Zeilen:")
        print(f"     n         {kennzahlen['n']}"
              f"{'   (erwartet 4380)' if voll else ''}")
        print(f"     LogLoss   {kennzahlen['log_loss']:.5f}"
              f"{'   (erwartet 1.01598)' if voll else ''}")
        print(f"     Brier     {kennzahlen['brier']:.5f}"
              f"{'   (erwartet 0.60821)' if voll else ''}")
        print(f"     RPS       {kennzahlen['rps']:.5f}"
              f"{'   (erwartet 0.20868)' if voll else ''}")


def write_payload(payload, pfad, force):
    """Schreibt den Datensatz - niemals stillschweigend ueber Bestehendes."""
    if os.path.exists(pfad) and not force:
        print()
        print(f"  ABBRUCH: {pfad} existiert bereits.")
        print("  Es wurde NICHTS geschrieben.")
        print("  Zum bewussten Ersetzen: --force, sonst anderen Pfad waehlen.")
        return False

    os.makedirs(os.path.dirname(os.path.abspath(pfad)), exist_ok=True)

    # Atomar: erst vollstaendig danebenschreiben, dann ersetzen.
    temporaer = pfad + ".tmp"
    with open(temporaer, "w", encoding="utf-8") as datei:
        json.dump(payload, datei, indent=2, ensure_ascii=False, sort_keys=True)
        datei.write("\n")
    os.replace(temporaer, pfad)

    print()
    print(f"  Geschrieben: {pfad} ({os.path.getsize(pfad) / 1024 / 1024:.1f} MB)")
    return True


def parse_liste(wert):
    teile = [t.strip() for t in str(wert).split(",") if t.strip()]
    if not teile:
        raise argparse.ArgumentTypeError("leere Liste")
    return teile


def parse_saisons(wert):
    teile = []
    for roh in str(wert).split(","):
        roh = roh.strip()
        if not roh:
            continue
        try:
            teile.append(int(roh))
        except ValueError:
            raise argparse.ArgumentTypeError(f"keine Saison: {roh!r}")
    if not teile:
        raise argparse.ArgumentTypeError("keine Saison angegeben")
    return teile


def build_parser():
    parser = argparse.ArgumentParser(
        description="ML-Vorbereitung fuer FootSim.")
    parser.add_argument("--build-dataset", action="store_true",
                        dest="build_dataset",
                        help="den Point-in-Time-Datensatz erzeugen")
    parser.add_argument("--leagues", type=parse_liste,
                        default=list(ds.DEFAULT_LEAGUES),
                        help="Ligen, kommagetrennt (Standard: "
                             + ",".join(ds.DEFAULT_LEAGUES) + ")")
    parser.add_argument("--seasons", type=parse_saisons,
                        default=list(ds.DEFAULT_SEASONS),
                        help="Saisons, kommagetrennt (Standard: "
                             + ",".join(str(s) for s in ds.DEFAULT_SEASONS) + ")")
    parser.add_argument("--min-matchday", type=int,
                        default=ds.DEFAULT_MIN_MATCHDAY, dest="min_matchday",
                        help="Grenze fuer evaluation_eligible "
                             f"(Standard: {ds.DEFAULT_MIN_MATCHDAY})")
    parser.add_argument("--output", type=str, default=None,
                        help="Zieldatei. Ohne diese Angabe wird NICHTS "
                             "geschrieben.")
    parser.add_argument("--force", action="store_true",
                        help="eine vorhandene Zieldatei ersetzen")
    parser.add_argument("--no-coverage", action="store_true",
                        dest="no_coverage",
                        help="die Crosswalk-Diagnose ueberspringen")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    if not args.build_dataset:
        print("\n  Nichts zu tun. --build-dataset angeben.\n")
        return 2
    if args.min_matchday < 0:
        print("  --min-matchday darf nicht negativ sein.")
        return 2
    if args.force and not args.output:
        print("  --force ergibt ohne --output keinen Sinn.")
        return 2

    print(f"\n  Datensatz: {len(args.leagues)} Ligen x {len(args.seasons)} Saisons")
    if not args.output:
        print("  Kein --output: es wird nichts geschrieben.")

    zeilen, diagnose = ds.build_dataset(
        args.leagues, args.seasons, args.min_matchday)

    if not zeilen:
        print("\n  Keine einzige Zeile entstanden.")
        return 1

    payload = build_payload(args.leagues, args.seasons, args.min_matchday,
                            zeilen, diagnose)
    kennzahlen = ds.baseline_metrics(zeilen)
    abdeckung = (None if args.no_coverage
                 else ds.crosswalk_coverage(args.seasons))

    print_summary(payload, kennzahlen, abdeckung)

    if args.output:
        if not write_payload(payload, args.output, args.force):
            return 1

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
