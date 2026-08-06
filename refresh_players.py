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
Zwei Stufen pro Liga:

  1. Seiten-Abfrage /players?league=X&season=Y - findet heraus, WELCHE
     Spieler in der Liga sind (rund 26 bis 31 Seiten je Top-5-Liga).
  2. Fuer JEDEN gefundenen Spieler /players?id=&season= - holt SEINE
     vollstaendige Saison ueber ALLE Wettbewerbe (Liga, Pokal, Champions/
     Europa/Conference League, Supercup, Nationalmannschaft).

Erst dadurch enthaelt der Pool dieselben Daten wie der Radar. Wuerde nur die
Seiten-Abfrage genutzt, laege pro Spieler ausschliesslich der Liga-Block vor
und die Wettbewerbsumfaenge (club_all/league/national/all) waeren alle gleich.

Kosten: Der ERSTE vollstaendige Import kostet rund einen Request pro Spieler
(fuenf Top-5-Ligen zusammen ~2500 bis 3000 Spieler), verteilt mit sicherer
Drosselung. Er dauert daher deutlich laenger als eine Minute - plane besser
mit einer halben bis dreiviertel Stunde. Danach liegt jede Spielerantwort im
Disk-Cache (genau die, die auch der Radar fuellt); Folgelaeufe sind schnell.

Bricht der Lauf am Tageslimit der API ab, bleibt der Fortschritt erhalten:
Seiten sind seitenweise, Spielerantworten dauerhaft im Cache gesichert. Ein
erneuter Aufruf setzt fort und trifft die bereits geladenen Spieler im Cache.

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
    get_player_season_raw,
    get_player_season_raw_enriched,
    COMPARE_LEAGUE_CODES,
    COMPARE_LEAGUE_LABELS,
    COMPETITION_SCOPES,
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

# Sichere Drosselung: eine Pause nach jedem ECHTEN Spielerabruf (Cache-Miss).
# Zwei Requests pro Sekunde liegen deutlich unter jedem dokumentierten Limit.
# Cache-Treffer warten nie, Folgelaeufe sind dadurch nahezu ohne Pausen.
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
            # read_pool() liefert ein dict {league, season, pages_done,
            # players}. Die Alterskennung steht je Spieler, nicht auf der
            # obersten Ebene - deshalb den ERSTEN Spieler pruefen. (Vorher
            # griff der Report faelschlich mit [0] auf das dict zu und warf
            # am Ende eines sonst erfolgreichen Laufs einen KeyError: 0.)
            pool = read_pool(row["league"], season)
            players = (pool or {}).get("players") or []
            if players and "age" not in (players[0] or {}):
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

def _build_entry(page_raw, season, league_code, throttle_seconds=0.0,
                 with_national=False):
    """
    Wandelt einen Spieler der Liga-Seiten-Abfrage in einen Pooleintrag um.

    ENTSCHEIDENDE AENDERUNG (Wettbewerbsumfang-Fix):
    Die Liga-Seiten-Abfrage /players?league=X liefert pro Spieler nur den
    statistics-Block DIESER Liga. club_all, league, national und all waeren
    daraus alle identisch - der Pool haette nie Pokal-, Europapokal- oder
    Laenderspieldaten. Genau das war die Inkonsistenz gegenueber dem Radar.

    Deshalb wird der Spieler hier ueber SEINE ID nachgeladen:
    get_player_season_raw() holt /players?id=&season= - dieselbe Quelle,
    die auch der Radar nutzt - mit ALLEN Wettbewerbsbloecken. Aus dieser
    vollstaendigen Rohantwort werden alle vier Scopes gebaut. Pool und
    Radar beruhen dadurch auf identischen Rohdaten.

    Kosten: ein zusaetzlicher API-Request pro Spieler beim ERSTEN Import.
    Danach liegt die Rohantwort im Disk-Cache (dieselbe, die der Radar
    fuellt und liest), spaetere Laeufe kosten dafuer nichts. throttle_seconds
    drosselt ausschliesslich echte Netzabrufe (Cache-Miss).

    Ehrliche Degradierung: Liefert die ID-Abfrage nichts (sehr selten),
    faellt der Aufbau auf den Liga-Block der Seiten-Abfrage zurueck. Der
    Spieler geht dann mit reinen Ligadaten in den Pool statt zu fehlen.

    league_code: die Entdeckungsliga, wird als feste Ligakennung
    weitergereicht (siehe build_pool_entry).
    """
    player = (page_raw or {}).get("player") or {}
    player_id = player.get("id")

    # Vollstaendige Rohantwort (alle Wettbewerbe) ueber die Spieler-ID.
    # Ausnahmen (Rate-Limit, API nicht erreichbar) bewusst NICHT abfangen:
    # sie muessen bis import_one_league durchschlagen, damit der Lauf sauber
    # anhaelt und spaeter fortsetzen kann.
    #
    # with_national=True zieht zusaetzlich die gespeicherten Nationalmann-
    # schaftsbloecke bei (get_player_season_raw_enriched). Das nutzt der
    # NM-Anreicherungslauf, nachdem national_import die Turnierdaten abgelegt
    # hat. Der normale Vereins-Import laesst es False - er soll nicht von
    # NM-Daten abhaengen.
    full_raw = None
    if player_id is not None:
        if with_national:
            full_raw = get_player_season_raw_enriched(
                player_id, season, throttle_seconds=throttle_seconds
            )
        else:
            full_raw = get_player_season_raw(
                player_id, season, throttle_seconds=throttle_seconds
            )

    # Fallback auf den Liga-Block, falls die ID-Abfrage leer bleibt.
    source_raw = full_raw if full_raw else page_raw

    profile_by_scope = {}
    metrics_by_scope = {}

    for scope in COMPETITION_SCOPES:
        profile = build_player_profile(source_raw, season, scope=scope)
        profile_by_scope[scope] = profile
        if profile.get("data_available") and profile.get("position") is not None:
            metrics_by_scope[scope] = compute_player_metrics(profile, ALL_METRIC_KEYS)
        else:
            metrics_by_scope[scope] = {}

    # Ohne Vereinsdaten im Standard-Scope ist der Spieler fuer den Pool
    # nicht brauchbar - dieselbe Eignungspruefung wie zuvor, nur bezogen
    # auf club_all statt auf den impliziten Default.
    primary = profile_by_scope.get("club_all")
    if not primary or not primary.get("data_available") or primary.get("position") is None:
        return None

    return build_pool_entry(profile_by_scope, metrics_by_scope, league_code=league_code)


def import_one_league(league_code, season, force=False):
    label = COMPARE_LEAGUE_LABELS.get(league_code, league_code)

    if not force and is_pool_complete(league_code, season):
        print(f"  {label:18} bereits vollstaendig, uebersprungen")
        return True

    def fetch_page(page):
        return get_league_players_page(league_code, season, page=page)

    def build_entry(raw):
        # Die Drosselung sitzt jetzt am Spielerabruf (ein Request je Spieler),
        # nicht mehr am Seitenabruf. Deshalb wird sie hier weitergereicht.
        return _build_entry(raw, season, league_code,
                            throttle_seconds=THROTTLE_SECONDS)

    try:
        import_league(
            league_code, season,
            fetch_page=fetch_page,
            build_entry=build_entry,
            # Kein zusaetzliches Warten je Seite: die relevante Drosselung
            # geschieht pro Spielerabruf in build_entry.
            throttle_seconds=0,
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


def enrich_pool_with_national(season, min_minutes):
    """
    Reichert die bereits importierten Pool-Spieler um Nationalmannschaftsdaten
    an und baut Pool-Eintraege und Snapshot neu.

    Ablauf:
      1. Alle vorhandenen Pool-Spieler der fuenf Ligen sammeln (ihre IDs).
      2. national_import: die verifizierten Turniere der FootSim-Saison
         wettbewerbsbasiert laden, beschraenkt auf genau diese Spieler-IDs.
         Ergebnis wird unter data/national/national_<season>.json abgelegt.
      3. Jeden Pool-Spieler mit with_national=True neu aufbauen - jetzt tragen
         die Scopes national/all echte Laenderspieldaten.
      4. Snapshot neu berechnen (die national-Verteilung ist danach gefuellt).

    Es kommt KEIN neuer Spieler in den Pool. Nur die vier Scopes der
    vorhandenen Spieler werden vervollstaendigt.
    """
    from src.data.national_import import (
        import_national_for_season, clear_runtime_cache,
    )
    from src.data.player_pool import read_pool, write_pool

    print(f"\n  Nationalmannschafts-Anreicherung Saison {season}/{str(season + 1)[2:]}")

    # 1. Pool-Spieler-IDs sammeln
    pool_by_league = {}
    all_ids = set()
    for code in COMPARE_LEAGUE_CODES:
        if not is_pool_complete(code, season):
            print(f"  Liga {code} nicht vollstaendig - erst Vereins-Import abschliessen.")
            return None
        pool = read_pool(code, season)
        pool_by_league[code] = pool
        for p in pool.get("players") or []:
            if p.get("player_id") is not None:
                all_ids.add(p["player_id"])

    print(f"  {len(all_ids)} Pool-Spieler, suche Laenderspieldaten in verifizierten Turnieren")

    # 2. NM-Turniere laden (nur fuer diese Spieler)
    def _nat_progress(league_id, api_season, page, total):
        sys.stdout.write(f"\r  NM league={league_id} season={api_season} "
                         f"Seite {page}/{total}   ")
        sys.stdout.flush()

    try:
        blocks_by_player = import_national_for_season(
            season, all_ids, progress=_nat_progress,
        )
    except ApisportsRateLimit as error:
        print(f"\n  ABBRUCH: {error}")
        print("  Bisher geladene Turnierseiten sind gecacht, erneut aufrufen setzt fort.")
        return None
    except ApisportsUnavailable as error:
        print(f"\n  FEHLER: {error}")
        return None

    sys.stdout.write("\n")
    clear_runtime_cache()  # frisch geschriebene Datei einlesen
    n_with_national = len(blocks_by_player)
    print(f"  {n_with_national} Pool-Spieler haben Laenderspieldaten erhalten")

    # 3. Pool-Eintraege neu bauen (with_national=True)
    for code in COMPARE_LEAGUE_CODES:
        pool = pool_by_league[code]
        players = pool.get("players") or []
        rebuilt = []
        for p in players:
            pid = p.get("player_id")
            entry = _build_entry(
                {"player": {"id": pid}}, season, code,
                throttle_seconds=0.0, with_national=True,
            )
            # entry kann None sein, wenn club_all unerwartet leer ist -
            # dann alten Eintrag behalten (kein Datenverlust).
            rebuilt.append(entry if entry else p)
        pool["players"] = rebuilt
        write_pool(pool)
        print(f"  {COMPARE_LEAGUE_LABELS.get(code, code):18} neu aufgebaut ({len(rebuilt)} Spieler)")

    # 4. Snapshot neu
    print()
    build_and_save_snapshot(season, min_minutes)
    return True



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
    parser.add_argument("--national", action="store_true",
                        help="Nationalmannschaftsdaten der vorhandenen Pool-Spieler "
                             "importieren und Scopes national/all vervollstaendigen")
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

    if args.national:
        acquired, existing = acquire_lock()
        if not acquired:
            print("\n  Es laeuft bereits ein Import.")
            print(f"  Gestartet: {existing.get('started_at')} (PID {existing.get('pid')})")
            return 1
        try:
            ok = enrich_pool_with_national(season, args.min_minutes)
            print()
            print_report(season)
            return 0 if ok else 1
        finally:
            release_lock()

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
