"""
Importiert die Spieler-Referenzdaten fuer den Spielervergleich.

Aufruf:
    py refresh_players.py --report
    py refresh_players.py --league bl1 --season 2024
    py refresh_players.py --all --season 2024
    py refresh_players.py --all --season 2024 --force
    py refresh_players.py --snapshot --season 2024

Was passiert
------------
Fuer jede Liga werden alle Seiten des API-Sports-Endpunkts /players geholt.
API-Sports liefert 20 Spieler pro Seite, eine Top-5-Liga hat rund 500 bis 620
Spieler. Das sind 26 bis 31 Requests pro Liga, also rund 136 bis 149 fuer alle
fuenf Ligen einer Saison.

Zwischen den Requests wird bewusst gewartet, damit das Sekundenlimit der API
nicht erreicht wird. Ein vollstaendiger Lauf ueber fuenf Ligen dauert daher
gut eine Minute.

Genau deshalb laeuft dieser Import NICHT in der Webanwendung. Kein Nutzer soll
auf einen Ligaimport warten. Die Anwendung liest ausschliesslich das Ergebnis.

Wiederaufnahme
--------------
Bricht ein Lauf ab, bleiben die bereits geladenen Seiten erhalten. Ein
erneuter Aufruf setzt fort, statt von vorn zu beginnen. Mit --force wird
bewusst alles neu geladen.

Ergebnis
--------
    data/player_pool/pool_{liga}_{saison}.json   Referenzdaten (nicht im Git)
    data/percentiles/percentiles_{saison}.json   Snapshot (gehoert ins Git)

Der Snapshot wird erst erzeugt, wenn ALLE fuenf Ligen vollstaendig vorliegen.
Perzentile aus einem halb geladenen Pool waeren irrefuehrend.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

from src.api.apisports_api import (
    get_league_players_page,
    CURRENT_SEASON,
    ApisportsRateLimit,
    ApisportsUnavailable,
)
from src.data.player_compare_loader import (
    build_player_profile,
    compute_player_metrics,
    COMPARE_LEAGUE_CODES,
    COMPARE_LEAGUE_LABELS,
)
from src.data.player_metrics import METRICS
from src.data.percentile_engine import (
    build_snapshot,
    save_snapshot,
    load_snapshot,
    is_snapshot_complete,
    DEFAULT_MIN_MINUTES,
    REQUIRED_LEAGUES,
)
from src.data import player_pool
from src.data.player_pool import (
    acquire_lock,
    release_lock,
    import_league,
    build_pool_entry,
    coverage_report,
    load_all_players,
    is_pool_complete,
)


ALL_METRIC_KEYS = list(METRICS.keys())

# Sichere Drosselung: zwei Requests pro Sekunde liegen deutlich unter jedem
# dokumentierten Limit und machen den Lauf trotzdem ertraeglich kurz.
THROTTLE_SECONDS = 0.5


# ---------------------------------------------------------------------------
# Ausgabe
# ---------------------------------------------------------------------------

def print_report(season):
    print("=" * 70)
    print(f"  Spielerpool Saison {season}/{str(season + 1)[2:]}")
    print("=" * 70)

    rows = coverage_report(season, COMPARE_LEAGUE_CODES)

    for row in rows:
        label = COMPARE_LEAGUE_LABELS.get(row["league"], row["league"])
        status = row["status"]

        if status == "complete":
            print(f"  {label:18} vollstaendig   "
                  f"{row['player_count'] or 0:4} Spieler   "
                  f"{row['total_pages'] or 0:3} Seiten")
        elif status == "in_progress":
            print(f"  {label:18} unvollstaendig "
                  f"{row['loaded_pages']}/{row['total_pages'] or '?'} Seiten")
        elif status == "error":
            print(f"  {label:18} FEHLER         "
                  f"{row['loaded_pages']}/{row['total_pages'] or '?'} Seiten")
        else:
            print(f"  {label:18} nicht geladen")

    print("-" * 70)

    done = [r for r in rows if r["status"] == "complete"]
    print(f"  {len(done)} von {len(rows)} Ligen vollstaendig")

    snapshot = load_snapshot(season)
    if snapshot:
        complete = "vollstaendig" if is_snapshot_complete(snapshot) else "TEILWEISE"
        print(f"  Perzentil-Snapshot: {complete}, erstellt {snapshot.get('created_at')}")
        for position, dist in (snapshot.get("distributions") or {}).items():
            print(f"     {position:12} {dist.get('player_count', 0):4} Spieler, "
                  f"{len(dist.get('metrics') or {}):2} Kennzahlen")
    else:
        print("  Perzentil-Snapshot: nicht vorhanden")

    # Phase 3.1: Pooleintraege enthalten jetzt zusaetzlich age und team_name
    # als Filterdimensionen. Ein vor Phase 3.1 importierter Pool hat sie nicht.
    # Fuer Perzentile ist das egal, fuer spaetere Auswertungen nicht.
    if done:
        from src.data.player_pool import read_pool
        stale = []
        for row in rows:
            if row["status"] != "complete":
                continue
            entries = read_pool(row["league"], season)
            if entries and "age" not in (entries[0] or {}):
                stale.append(COMPARE_LEAGUE_LABELS.get(row["league"], row["league"]))
        if stale:
            print()
            print("  Hinweis: folgende Pools stammen aus der Zeit vor Phase 3.1")
            print("  und enthalten age/team_name noch nicht:")
            print(f"     {', '.join(stale)}")
            print("  Perzentile funktionieren weiterhin. Fuer spaetere Filter")
            print(f"  einmalig neu laden:  --all --season {season} --force")

    print()


def _progress(league_code, season, done, total):
    label = COMPARE_LEAGUE_LABELS.get(league_code, league_code)
    bar_width = 30
    filled = int(bar_width * done / total) if total else 0
    bar = "#" * filled + "." * (bar_width - filled)
    sys.stdout.write(f"\r  {label:18} [{bar}] {done:3}/{total}")
    sys.stdout.flush()
    if done == total:
        sys.stdout.write("\n")


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def _build_entry(raw_entry, season):
    """
    Wandelt einen rohen /players-Eintrag in einen Pooleintrag um.

    Es werden ALLE bekannten Kennzahlen berechnet, nicht nur die aktuell im
    Radar verwendeten. Dadurch muss der Pool nicht neu importiert werden,
    wenn ein Radar-Profil spaeter geaendert wird.
    """
    profile = build_player_profile(raw_entry, season)

    if not profile.get("data_available"):
        return None
    if profile.get("position") is None:
        return None

    values = compute_player_metrics(profile, ALL_METRIC_KEYS)
    return build_pool_entry(profile, values)


def import_one_league(league_code, season, force=False):
    label = COMPARE_LEAGUE_LABELS.get(league_code, league_code)

    if not force and is_pool_complete(league_code, season):
        print(f"  {label:18} bereits vollstaendig, uebersprungen")
        return True

    def fetch_page(page):
        return get_league_players_page(league_code, season, page=page)

    def build_entry(raw):
        return _build_entry(raw, season)

    try:
        import_league(
            league_code, season,
            fetch_page=fetch_page,
            build_entry=build_entry,
            throttle_seconds=THROTTLE_SECONDS,
            resume=not force,
            progress=_progress,
        )
        return True

    except ApisportsRateLimit as error:
        print(f"\n  {label:18} ABBRUCH: {error}")
        print("  Der bisherige Fortschritt wurde gespeichert.")
        print("  Spaeter erneut aufrufen, der Lauf setzt automatisch fort.")
        return False

    except ApisportsUnavailable as error:
        print(f"\n  {label:18} FEHLER: {error}")
        return False


def build_and_save_snapshot(season, min_minutes):
    """
    Baut den Perzentil-Snapshot, sofern alle erforderlichen Ligen vorliegen.

    Ein unvollstaendiger Pool erzeugt bewusst KEINEN Snapshot. Lieber gar
    keine Perzentile als Perzentile, die nur aussehen wie Top-5-Werte.
    """
    players, used = load_all_players(season, COMPARE_LEAGUE_CODES)
    missing = [code for code in REQUIRED_LEAGUES if code not in used]

    if missing:
        labels = ", ".join(COMPARE_LEAGUE_LABELS.get(c, c) for c in missing)
        print(f"  Kein Snapshot: es fehlen noch {labels}")
        print("  Perzentile werden erst aus einem vollstaendigen Pool berechnet.")
        return None

    snapshot = build_snapshot(players, season, used, min_minutes=min_minutes)
    path = save_snapshot(snapshot)

    total = sum(d.get("player_count", 0) for d in snapshot["distributions"].values())
    print(f"  Snapshot gespeichert: {path}")
    print(f"  {total} Spieler mit mindestens {min_minutes} Minuten in "
          f"{len(snapshot['distributions'])} Positionsgruppen")

    return snapshot


# ---------------------------------------------------------------------------
# Einstieg
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Importiert Spieler-Referenzdaten fuer den Spielervergleich."
    )
    parser.add_argument("--season", type=int, default=CURRENT_SEASON,
                        help=f"Saison als Startjahr, Standard {CURRENT_SEASON}")
    parser.add_argument("--league", type=str,
                        help="einzelne Liga: " + ", ".join(COMPARE_LEAGUE_CODES))
    parser.add_argument("--all", action="store_true",
                        help="alle fuenf Vergleichsligen importieren")
    parser.add_argument("--report", action="store_true",
                        help="nur den aktuellen Stand anzeigen")
    parser.add_argument("--snapshot", action="store_true",
                        help="nur den Perzentil-Snapshot neu berechnen")
    parser.add_argument("--force", action="store_true",
                        help="bereits geladene Ligen erneut vollstaendig laden")
    parser.add_argument("--min-minutes", type=int, default=DEFAULT_MIN_MINUTES,
                        help=f"Mindestspielzeit fuer den Pool, Standard {DEFAULT_MIN_MINUTES}")

    args = parser.parse_args()
    season = args.season

    if args.report:
        print_report(season)
        return 0

    if args.snapshot:
        print(f"\n  Perzentil-Snapshot fuer Saison {season}\n")
        build_and_save_snapshot(season, args.min_minutes)
        print()
        return 0

    if not args.all and not args.league:
        parser.print_help()
        print("\n  Hinweis: --all oder --league angeben, oder --report fuer den Stand.\n")
        return 1

    if args.league and args.league not in COMPARE_LEAGUE_CODES:
        print(f"\n  Unbekannte Liga: {args.league}")
        print(f"  Moeglich sind: {', '.join(COMPARE_LEAGUE_CODES)}\n")
        return 1

    targets = list(COMPARE_LEAGUE_CODES) if args.all else [args.league]

    acquired, existing = acquire_lock()
    if not acquired:
        print("\n  Es laeuft bereits ein Import.")
        print(f"  Gestartet: {existing.get('started_at')} (PID {existing.get('pid')})")
        print("  Warte, bis dieser Lauf beendet ist.\n")
        return 1

    try:
        print(f"\n  Import Saison {season}/{str(season + 1)[2:]}")
        print(f"  Ligen: {', '.join(targets)}")
        print(f"  Drosselung: {THROTTLE_SECONDS}s zwischen den Requests\n")

        all_ok = True
        for code in targets:
            if not import_one_league(code, season, force=args.force):
                all_ok = False
                break

        print()
        if all_ok:
            build_and_save_snapshot(season, args.min_minutes)

        print()
        print_report(season)

        return 0 if all_ok else 1

    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
