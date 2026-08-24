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

from datetime import datetime, timezone

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
    is_snapshot_usable,
    load_usable_snapshot,
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
    effective_pool_status,
    is_import_skippable,
    read_pool,
    write_pool,
    update_pool_status,
    evaluate_pool,
    STATUS_COMPLETE,
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
    """
    Ehrlicher Datenstand einer Saison.

    Der Report las frueher player["minutes"] - ein Feld, das ein
    Pooleintrag gar nicht hat. Deshalb stand dort dauerhaft "Spieler mit
    mindestens 1 Minute: 0", waehrend allein die Premier League 187 hatte.
    Die Einsatzzeit kommt jetzt aus player_pool.player_minutes(), der
    einzigen Stelle, die weiss, wo sie steht.

    Ausserdem werden drei Dinge getrennt ausgewiesen, die vorher zu einem
    Wort verschmolzen waren:

        Kaderabdeckung   Sind alle Vereine vertreten?
        Statistikreife   Haben die Spieler schon Minuten?
        Perzentilreife   Reichen die Minuten fuer eine Vergleichskohorte?

    Eine junge Saison hat vollstaendige Kader und fast keine Minuten. Das
    ist kein Fehler und darf nicht wie einer aussehen.
    """
    from src.data.player_pool import (
        STATUS_PROVIDER_INCOMPLETE, evaluate_pool, player_minutes, read_pool)

    print("=" * 78)
    print(f"  Spielerpool Saison {season}/{str(season + 1)[2:]}")
    print("=" * 78)

    rows = coverage_report(season, COMPARE_LEAGUE_CODES)

    print(f"  {'Liga':<18} {'Status':<20} {'Spieler':>7} {'Teams':>8} "
          f"{'Seiten':>8} {'mit Min.':>9}")
    print("  " + "-" * 74)

    gesamt_mit_minute = 0
    gesamt_ueber_schwelle = 0
    unvollstaendig = []

    for row in rows:
        label = COMPARE_LEAGUE_LABELS.get(row["league"], row["league"])
        pool = read_pool(row["league"], season)
        bewertung = evaluate_pool(pool, row["league"])

        mit_minute = 0
        ueber_schwelle = 0
        for spieler in (pool.get("players") or []):
            minuten = player_minutes(spieler) or 0
            if minuten > 0:
                mit_minute += 1
            if minuten >= DEFAULT_MIN_MINUTES:
                ueber_schwelle += 1
        gesamt_mit_minute += mit_minute
        gesamt_ueber_schwelle += ueber_schwelle

        status = row["status"]
        if status == "pending":
            anzeige = "nicht geladen"
        elif status == "error":
            anzeige = "FEHLER"
        elif bewertung["issues"]:
            anzeige = STATUS_PROVIDER_INCOMPLETE
        else:
            anzeige = status

        erwartet = bewertung["expected_teams"]
        teams = f"{bewertung['teams']}/{erwartet}" if erwartet else str(bewertung["teams"])
        seiten = f"{row['loaded_pages']}/{row['total_pages'] or '?'}"

        print(f"  {label:<18} {anzeige:<20} {bewertung['players']:>7} "
              f"{teams:>8} {seiten:>8} {mit_minute:>9}")

        if bewertung["issues"]:
            unvollstaendig.append((label, bewertung["issues"],
                                   row.get("kept_existing_pool"),
                                   row.get("rejected_reason")))

    print("  " + "-" * 74)

    vollstaendig = [r for r in rows
                    if r["status"] == "complete"
                    and not evaluate_pool(read_pool(r["league"], season),
                                          r["league"])["issues"]]
    print(f"  {len(vollstaendig)} von {len(rows)} Ligen inhaltlich vollstaendig")
    print(f"  Spieler mit mindestens 1 Minute (club_all):  {gesamt_mit_minute}")
    print(f"  Spieler ab {DEFAULT_MIN_MINUTES} Minuten:                    "
          f"{gesamt_ueber_schwelle}")

    if unvollstaendig:
        print()
        print("  Warum einzelne Ligen nicht vollstaendig sind:")
        for label, issues, behalten, grund in unvollstaendig:
            print(f"     {label}: {'; '.join(issues)}")
            if behalten:
                print(f"        -> neuer Anbieterstand verworfen ({grund}),"
                      f" bestehender Pool behalten")
        print()
        print("  Das ist in aller Regel eine Luecke beim Datenanbieter, kein")
        print("  Fehler in FootSim. Ein spaeterer Lauf holt die Daten nach.")

    # --- Perzentil-Snapshot ------------------------------------------------
    snapshot = load_snapshot(season)
    if snapshot:
        gruppen = len(snapshot.get("distributions") or {})
        nach_scope = snapshot.get("distributions_by_scope") or {}
        club_gruppen = sum(
            len(nach_scope.get(scope) or {}) for scope in ("club_all", "league"))

        if not is_snapshot_usable(snapshot):
            zustand = "noch keine belastbare Vergleichsverteilung"
        elif is_snapshot_complete(snapshot):
            zustand = "vollstaendig"
        else:
            zustand = "teilweise"

        print()
        print(f"  Perzentil-Snapshot: {zustand}")
        print(f"     erstellt {snapshot.get('created_at')}")
        print(f"     Positionsgruppen (Vereins-Scopes): {club_gruppen}")

        for scope in ("club_all", "league", "cl", "national", "all"):
            verteilungen = nach_scope.get(scope) or {}
            if not verteilungen:
                continue
            teile = ", ".join(
                f"{pos} {dist.get('player_count', 0)}"
                for pos, dist in sorted(verteilungen.items()))
            print(f"     {scope:9} {teile}")

        if not is_snapshot_usable(snapshot):
            print("     Grund: in den Vereinswettbewerben haben noch zu wenige")
            print(f"     Spieler die Mindestminute von {DEFAULT_MIN_MINUTES}"
                  " erreicht.")
    else:
        print()
        print("  Perzentil-Snapshot: nicht vorhanden")

    # --- Welcher Pool stellt tatsaechlich die Vergleichsgrundlage? ---------
    _, referenz_saison = load_usable_snapshot(season)
    if referenz_saison is None:
        print("  Referenzpool:       KEINER - Vergleich faellt auf Rohwerte zurueck")
    elif referenz_saison == season:
        print(f"  Referenzpool:       Saison {season}/{str(season + 1)[2:]}"
              " (eigener Stand)")
    else:
        print(f"  Referenzpool:       Saison {referenz_saison}/"
              f"{str(referenz_saison + 1)[2:]}"
              f"  -> Werte {season}/{str(season + 1)[2:]} gelten als VORLAEUFIG")

    # --- Diagnose: nicht zuordenbare Provider-Werte ------------------------
    from src.data.competition_taxonomy import unknown_competition_report
    from src.data.player_metrics import unknown_position_report

    unbekannte_positionen = unknown_position_report()
    if unbekannte_positionen:
        print()
        print("  Nicht zuordenbare Positionsangaben des Anbieters:")
        for wert, anzahl in list(unbekannte_positionen.items())[:10]:
            print(f"     {wert!r}: {anzahl}x")

    unbekannte_wettbewerbe = unknown_competition_report()
    if unbekannte_wettbewerbe:
        print()
        print("  Nicht eingeordnete Wettbewerbe (zaehlen NICHT als Pflichtspiel):")
        for wert, anzahl in list(unbekannte_wettbewerbe.items())[:10]:
            print(f"     {wert}: {anzahl}x")

    print()


def print_diagnostics(season):
    """
    Technische Diagnose des Datenstands - rein lesend, ohne Netzzugriff.

    Beantwortet die Fragen, die bei der Fehlersuche immer wieder
    auftauchen, ohne dass jemand dafuer ein Wegwerfskript schreiben muss.
    Kein Request, keine Datei wird veraendert.
    """
    import glob
    import json
    import os
    from collections import Counter

    from src.data.competition_taxonomy import taxonomy_report
    from src.data.player_metrics import normalize_position, unknown_position_report
    from src.data.player_pool import (
        POOL_DIR, evaluate_pool, get_pool_status, player_minutes, read_pool)
    from src.features.big_games import SUPER_CUP_COMPETITION_IDS

    print("=" * 78)
    print(f"  Diagnose Saison {season}/{str(season + 1)[2:]}")
    print("=" * 78)

    # 1-3: Vollstaendigkeit und Teamabdeckung je Liga
    print("\n[1-3] Ligastatus und Teamabdeckung")
    for code in COMPARE_LEAGUE_CODES:
        pool = read_pool(code, season)
        b = evaluate_pool(pool, code)
        gespeichert = (get_pool_status(code, season) or {}).get("status", "pending")
        # Gespeicherter Stempel UND heutige Bewertung. Sie koennen
        # auseinandergehen: Eine Liga, die vor der Datenreparatur als
        # "complete" abgelegt wurde, traegt diesen Stempel weiter, bis sie
        # erneut importiert wird. Bestehende Dateien werden bewusst nicht
        # nachtraeglich umgeschrieben.
        marke = "" if gespeichert == b["status"] else f"  (gespeichert: {gespeichert})"
        print(f"     {code:4} {b['status']:20} Spieler={b['players']:4} "
              f"Teams={b['teams']:3}/{b['expected_teams']} "
              f"Abdeckung={b['team_coverage']} mitMin={b['with_minutes']}{marke}")
        for grund in b["issues"]:
            print(f"          - {grund}")

    # 4-5: Positionsangaben im Pool
    print("\n[4-5] Positionsangaben in den Pooldateien")
    roh = Counter()
    normalisiert = Counter()
    for code in COMPARE_LEAGUE_CODES:
        for spieler in (read_pool(code, season).get("players") or []):
            wert = spieler.get("position")
            roh[wert] += 1
            normalisiert[normalize_position(wert)] += 1
    for wert, anzahl in roh.most_common():
        ziel = normalize_position(wert)
        marke = "  ->" if ziel != wert else "    "
        print(f"     {str(wert)!r:16} {anzahl:>5} {marke} {ziel}")
    forwards = roh.get("Forward", 0)
    print(f"     Davon durch Normalisierung gerettet (Forward): {forwards}")
    unbekannt = unknown_position_report()
    print(f"     Nicht zuordenbar: {unbekannt or 'keine'}")

    # 6-7: Wettbewerbszuordnung
    print("\n[6-7] Wettbewerbstaxonomie")
    bericht = taxonomy_report()
    for schluessel in ("domestic_supercups", "continental_supercups",
                       "club_friendlies", "national_friendlies"):
        print(f"     {schluessel:22} {bericht[schluessel]}")
    print(f"     Supercups als Big Games: {sorted(SUPER_CUP_COMPETITION_IDS)}")
    if bericht["unknown_seen"]:
        print(f"     Nicht eingeordnet: {bericht['unknown_seen']}")

    # 8: Kader-Fallback
    print("\n[8] Kaderindex (aktuelle Kader als Suchebene)")
    from src.utils.disk_cache import get_meta

    meta = get_meta(f"apisports:squad_index:{season}")
    if meta:
        print(f"     vorhanden, erstellt {meta.get('fetched_at')}")
    else:
        print("     noch nicht gebaut (wird beim ersten Bedarf erzeugt,"
              " rund 96 Requests)")

    # 9: Alter des Detailcaches
    print("\n[9] Alter der Spielerdetail-Cachedateien")
    muster = os.path.join(os.path.dirname(POOL_DIR), "cache",
                          f"apisports__playerprofile__*__{season}.json")
    dateien = glob.glob(muster)
    if dateien:
        import datetime
        alter = sorted(os.path.getmtime(f) for f in dateien)
        jung = datetime.datetime.fromtimestamp(alter[-1])
        alt_ = datetime.datetime.fromtimestamp(alter[0])
        print(f"     {len(dateien)} Dateien, aelteste {alt_:%Y-%m-%d %H:%M}, "
              f"juengste {jung:%Y-%m-%d %H:%M}")
    else:
        print("     keine vorhanden")

    # 10: Datenrevisionen
    print("\n[10] Datenrevisionen der Pooldateien")
    for code in COMPARE_LEAGUE_CODES:
        pfad = os.path.join(POOL_DIR, f"pool_{code}_{season}.json")
        if not os.path.exists(pfad):
            print(f"     {code:4} keine Datei")
            continue
        import datetime
        stand = datetime.datetime.fromtimestamp(os.path.getmtime(pfad))
        pool = read_pool(code, season)
        rev = pool.get("revision") or {}
        print(f"     {code:4} Datei {stand:%Y-%m-%d %H:%M}  "
              f"revision={rev.get('data_as_of') or 'nicht vermerkt'}")

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

    # Der Aufbau selbst liegt in player_refetch.build_entry_from_raw, weil
    # der gezielte Einzelspielerrefresh denselben Eintrag erzeugen muss.
    # Zwei getrennte Aufbauwege waeren eine sichere Quelle fuer
    # Abweichungen zwischen "frisch importiert" und "gezielt erneuert" -
    # und die faende niemand, weil beide fuer sich plausibel aussehen.
    from src.data.player_refetch import build_entry_from_raw

    return build_entry_from_raw(source_raw, season, league_code)


def import_one_league(league_code, season, force=False, refetch_players=False):
    """
    Importiert eine Liga - oder ueberspringt sie, wenn nichts zu tun ist.

    ZWEI GETRENNTE SCHALTER, DIE FRUEHER EINER WAREN
    ------------------------------------------------
        force            laedt die LIGASEITEN erneut
        refetch_players  laedt die SPIELERPROFILE erneut

    Sie beantworten verschiedene Fragen und duerfen sich deshalb nicht
    gegenseitig ersetzen. Genau das war der Fehler: --refetch-players
    setzte zwar den Profilcache-Bypass, aber der Skip weiter unten kannte
    nur force. Bei einer als vollstaendig vermerkten Liga kehrte die
    Funktion zurueck, bevor ein einziges Profil angefasst wurde - der
    Bypass war gesetzt und wurde nie benutzt. Der Befehl

        refresh_players.py --league pd --season 2026 --refetch-players

    war dadurch wirkungslos, ohne das zu melden.

    Der Skip nutzt jetzt ausserdem is_import_skippable(): Ein
    gespeicherter Vermerk allein genuegt nicht mehr, der Pool muss auch
    inhaltlich standhalten.
    """
    label = COMPARE_LEAGUE_LABELS.get(league_code, league_code)

    if not force and not refetch_players:
        stand = effective_pool_status(league_code, season)
        if stand["status"] == STATUS_COMPLETE:
            print(f"  {label:18} bereits vollstaendig, uebersprungen")
            return True
        if stand["stored"] == STATUS_COMPLETE:
            # Der Vermerk sagte fertig, der Inhalt widerspricht. Frueher
            # wurde hier stillschweigend uebersprungen.
            print(f"  {label:18} Vermerk sagt vollstaendig, der Inhalt nicht:")
            for problem in stand["issues"]:
                print(f"  {'':18}   {problem}")
            print(f"  {'':18} wird deshalb importiert")

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
            # resume ueberspringt bereits geladene Seiten - und damit auch
            # jeden Spielerabruf darauf. Fuer --refetch-players muss es
            # deshalb ebenfalls aus: Ein Profil laesst sich nur neu holen,
            # wenn der Lauf den Spieler ueberhaupt noch einmal sieht.
            # Ohne diese Zeile bliebe das Flag ein zweites Mal wirkungslos.
            resume=not force and not refetch_players,
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


def import_single_national_competition(league_id, api_season, min_minutes,
                                       dry_run=False):
    """
    Importiert GENAU EINEN Nationalmannschaftswettbewerb.

    Warum getrennt von --national
    -----------------------------
    --national laedt alle Zielwettbewerbe einer FootSim-Saison. Fuer
    FootSim 2023 sind das neun (EM, Copa America, AFCON, Asian Cup, Gold
    Cup, Friendlies, drei Qualifikationen) - der vergleichbare Lauf fuer
    FootSim 2025 hat real 641 Seiten gekostet. Wer nur die EM-Endrunde
    braucht, darf dieses Budget nicht ausgeben muessen.

    Diese Funktion baut KEIN zweites Importsystem: sie ruft dasselbe
    import_national_for_season() mit einer expliziten Ein-Eintrag-Zielliste
    auf und nutzt damit unveraendert dessen Pagination, Disk-Cache und
    Rate-Limit-Verhalten. merge_existing=True schuetzt bereits vorhandene
    Wettbewerbe derselben Saison vor dem Ueberschreiben.

    Die FootSim-Zielsaison wird NICHT uebergeben, sondern aus
    FOOTSIM_SEASON_OF_TOURNAMENT abgeleitet. Es gibt genau eine Quelle fuer
    diese Zuordnung; ein manuell mitgegebener Wert koennte ihr
    widersprechen. Fehlt der Eintrag, bricht der Lauf ab - lieber gar kein
    Import als ein falsch einsortierter.
    """
    from src.data.national_competitions import (
        NATIONAL_COMPETITIONS, FOOTSIM_SEASON_OF_TOURNAMENT,
    )
    from src.data.national_import import (
        import_national_for_season, clear_runtime_cache,
    )
    from src.data.player_pool import read_pool, write_pool

    meta = NATIONAL_COMPETITIONS.get(league_id)
    if not meta:
        print(f"\n  Unbekannter Wettbewerb: league_id={league_id}")
        print(f"  Bekannt sind: {sorted(NATIONAL_COMPETITIONS)}")
        return None

    if api_season not in meta["usable_seasons"]:
        print(f"\n  {meta['name']} (id {league_id}) hat fuer api_season="
              f"{api_season} keine verifizierten Spielerstatistiken.")
        print(f"  Verifiziert sind: {meta['usable_seasons']}")
        return None

    footsim_season = FOOTSIM_SEASON_OF_TOURNAMENT.get((league_id, api_season))
    if footsim_season is None:
        print(f"\n  Keine FootSim-Saison fuer (league_id={league_id}, "
              f"api_season={api_season}) hinterlegt.")
        print("  Erst in FOOTSIM_SEASON_OF_TOURNAMENT eintragen.")
        return None

    target = {"league_id": league_id, "api_season": api_season,
              "name": meta["name"]}

    print(f"\n  Einzelimport Nationalmannschaftswettbewerb")
    print(f"  Wettbewerb : {meta['name']} (league_id={league_id})")
    print(f"  API-Season : {api_season}")
    print(f"  FootSim    : {footsim_season}/{str(footsim_season + 1)[2:]}")

    # Pool-Spieler der Zielsaison - nur fuer diese werden Bloecke behalten.
    pool_by_league = {}
    all_ids = set()
    for code in COMPARE_LEAGUE_CODES:
        if not is_pool_complete(code, footsim_season):
            print(f"\n  Liga {code} fuer Saison {footsim_season} nicht "
                  f"vollstaendig importiert.")
            print("  Erst den Vereins-Import dieser Saison abschliessen.")
            return None
        pool = read_pool(code, footsim_season)
        pool_by_league[code] = pool
        for p in pool.get("players") or []:
            if p.get("player_id") is not None:
                all_ids.add(p["player_id"])

    print(f"  Pool       : {len(all_ids)} Spieler")

    if dry_run:
        print("\n  --dry-run: es wird NICHTS geladen und NICHTS geschrieben.")
        print("  Geladen wuerde ausschliesslich dieser eine Wettbewerb")
        print(f"  (/players?league={league_id}&season={api_season}, paginiert).")
        print("  Bereits gecachte Seiten kosten dabei keinen Request.")
        return {"dry_run": True, "target": target,
                "footsim_season": footsim_season, "pool_players": len(all_ids)}

    def _progress_cb(lid, api_s, page, total):
        sys.stdout.write(f"\r  league={lid} season={api_s} Seite {page}/{total}   ")
        sys.stdout.flush()

    try:
        blocks_by_player = import_national_for_season(
            footsim_season, all_ids, progress=_progress_cb,
            targets=[target], merge_existing=True,
        )
    except ApisportsRateLimit as error:
        print(f"\n  ABBRUCH: {error}")
        print("  Geladene Seiten sind gecacht, ein erneuter Aufruf setzt fort.")
        return None
    except ApisportsUnavailable as error:
        print(f"\n  FEHLER: {error}")
        return None

    sys.stdout.write("\n")
    clear_runtime_cache()

    with_blocks = sum(
        1 for blocks in blocks_by_player.values()
        if any((b.get("league") or {}).get("id") == league_id for b in blocks)
    )
    print(f"  {with_blocks} Pool-Spieler haben Daten aus {meta['name']}")

    # Pooleintraege der Zielsaison neu aufbauen, damit die turnierscharfen
    # Scopes gefuellt werden. Laeuft ueber den lokalen Backfill - keine
    # weiteren Requests.
    print()
    backfill_missing_scopes(
        footsim_season, min_minutes,
        # Nur die von Nationalmannschaftsdaten abhaengigen Scopes erzwingen.
        force_scopes=("euro", "world_cup", "national", "all"),
    )

    return {"target": target, "footsim_season": footsim_season,
            "players_with_blocks": with_blocks}


def backfill_missing_scopes(season, min_minutes, league_codes=None, scopes=None,
                            force_scopes=None):
    """
    Ergaenzt Wettbewerbsumfaenge, die in BEREITS vorhandenen Pooleintraegen
    fehlen - OHNE einen einzigen externen API-Request.

    Wozu das noetig ist
    --------------------
    COMPETITION_SCOPES kann wachsen (z. B. um "cl"), wenn ein neuer
    Wettbewerbsumfang eingefuehrt wird. Pools, die VOR dieser Erweiterung
    importiert wurden, kennen den neuen Scope-Schluessel nicht - fuer sie
    ist minutes_by_scope["cl"] schlicht nicht vorhanden, nicht None und
    nicht 0. load_scatter_points() liest genau dieses fehlende Feld und
    verwirft dadurch JEDEN Spieler, unabhaengig von min_minutes.

    Ein normaler Reimport (_build_entry -> get_player_season_raw) wuerde das
    zwar reparieren, ruft dafuer aber pro Spieler mit abgelaufenem
    Rohdaten-Cache (TTL 24h fuer die laufende Saison) einen ECHTEN Request
    auf - bei mehreren tausend Pool-Spielern und einem Tageslimit von etwa
    100 Requests nicht vertretbar.

    Deshalb hier ein bewusst anderer Pfad: die bereits gecachte
    /players?id=&season=-Rohantwort wird DIREKT von der Platte gelesen
    (disk_cache.read_entry), unter Umgehung von get_player_season_raw() und
    damit ohne dessen TTL-Pruefung. Eine leicht veraltete Rohantwort ist
    fuer eine reine Nachaggregation unproblematisch - ein fehlender Scope
    dagegen schon. Fehlt der Rohcache fuer einen Spieler komplett (nie
    geladen), bleibt der neue Scope fuer ihn leer statt erfunden zu werden;
    das ist fachlich korrekt, weil dann tatsaechlich nichts bekannt ist.

    Nationalmannschaftsbloecke
    --------------------------
    Turnierscharfe Scopes (euro, world_cup) liegen NICHT in der
    Vereins-Rohantwort: grosse Endrunden fuehrt API-Football unter eigenen
    api_seasons, die /players?id=&season=<Vereinssaison> gar nicht erfasst.
    Sie stehen stattdessen in data/national/national_<season>.json, gelegt
    vom NM-Import. Diese Bloecke werden hier genauso an die Rohantwort
    angehaengt wie zur Laufzeit in
    player_compare_loader.get_player_season_raw_enriched() - dieselbe
    Reihenfolge, dieselbe Deduplizierung ueber league.id. Nur dadurch sehen
    Pool/Scatter exakt das, was der Radar sieht.

    Auch das ist ein reiner Dateizugriff (get_national_blocks liest die
    lokale JSON-Datei, gecacht je Prozess) - weiterhin 0 Requests.

    Rueckgabe: dict league_code -> {"players", "updated", "cache_missing",
    "already_complete"}, oder None, wenn keine Liga vollstaendig vorliegt.
    """
    from src.utils.disk_cache import read_entry as disk_read_entry
    from src.data.player_pool import read_pool, write_pool
    from src.data.national_import import get_national_blocks

    league_codes = list(league_codes or COMPARE_LEAGUE_CODES)
    scopes = list(scopes or COMPETITION_SCOPES)

    print(f"\n  Scope-Backfill Saison {season}/{str(season + 1)[2:]} "
          f"(rein lokal, keine API-Requests)")

    report = {}
    any_complete = False

    for code in league_codes:
        if not is_pool_complete(code, season):
            print(f"  {COMPARE_LEAGUE_LABELS.get(code, code):18} "
                  f"nicht vollstaendig importiert - uebersprungen")
            continue

        any_complete = True
        pool = read_pool(code, season)
        players = pool.get("players") or []

        updated = cache_missing = already_complete = 0

        for entry in players:
            minutes_by_scope = entry.setdefault("minutes_by_scope", {})
            metrics_by_scope = entry.setdefault("metrics_by_scope", {})

            # Neu zu berechnen ist alles, was noch fehlt - plus die in
            # force_scopes ausdruecklich genannten. Letzteres braucht der
            # Einzelimport: nach frisch importierten Turnierdaten stehen
            # euro/world_cup zwar schon (leer) im Eintrag, muessen aber neu
            # aggregiert werden. Bewusst NICHT pauschal alle Scopes: club_all
            # und league bleiben so garantiert exakt so, wie der urspruengliche
            # Import sie berechnet hat.
            missing = [s for s in scopes if s not in minutes_by_scope]
            for scope in force_scopes or ():
                if scope in scopes and scope not in missing:
                    missing.append(scope)
            if not missing:
                already_complete += 1
                continue

            player_id = entry.get("player_id")
            cached = disk_read_entry(
                f"apisports:playerprofile:{player_id}:{season}"
            ) if player_id is not None else None

            payload = (cached or {}).get("payload") or []
            raw_entry = payload[0] if payload else None

            # Turnierbloecke (EM/WM) anhaengen - exakt wie
            # get_player_season_raw_enriched() es zur Laufzeit tut.
            national_blocks = (
                get_national_blocks(player_id, season)
                if player_id is not None else []
            )
            if national_blocks:
                if raw_entry is None:
                    raw_entry = {"player": {"id": player_id}, "statistics": []}
                existing = raw_entry.get("statistics") or []
                existing_ids = {
                    (block.get("league") or {}).get("id") for block in existing
                }
                merged = list(existing)
                for block in national_blocks:
                    if (block.get("league") or {}).get("id") in existing_ids:
                        continue
                    merged.append(block)
                raw_entry = dict(raw_entry)
                raw_entry["statistics"] = merged

            if raw_entry is None:
                cache_missing += 1
                continue

            for scope in missing:
                profile = build_player_profile(raw_entry, season, scope=scope)
                minutes_by_scope[scope] = profile.get("minutes")
                if profile.get("data_available") and profile.get("position") is not None:
                    values = compute_player_metrics(profile, ALL_METRIC_KEYS)
                    metrics_by_scope[scope] = {
                        k: v for k, v in values.items() if v is not None
                    }
                else:
                    metrics_by_scope[scope] = {}
            updated += 1

        write_pool(pool)
        report[code] = {
            "players": len(players),
            "updated": updated,
            "cache_missing": cache_missing,
            "already_complete": already_complete,
        }
        print(f"  {COMPARE_LEAGUE_LABELS.get(code, code):18} "
              f"{updated:4} ergaenzt, {cache_missing:4} ohne Rohcache, "
              f"{already_complete:4} bereits vollstaendig "
              f"(von {len(players)} Spielern)")

    if not any_complete:
        print("  Keine Liga vollstaendig importiert - nichts zu ergaenzen.")
        return None

    print()
    build_and_save_snapshot(season, min_minutes)
    return report


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

def run_update_current(min_minutes):
    """
    Betriebsmodus fuer die woechentliche Aktualisierung.

    Unterschied zu --all: Dieser Modus ueberspringt eine Liga NICHT nur
    deshalb, weil ihr Pool als "vollstaendig" markiert ist. Genau daran
    scheiterte die Aktualisierung bisher - ein Pool, der zu Saisonbeginn
    mit null Spielern abgeschlossen wurde, blieb sonst fuer immer leer.

    Unterschied zu --force: Es wird nicht alles neu geholt. Bereits
    geladene Seiten bleiben im Disk-Cache; nachgeladen wird, was fehlt.

    Sicherungen:
      - Saison dynamisch (kein Jahr in Cron oder Unit-Datei)
      - vorhandenes Locking, keine parallelen Importe
      - unterbrochene Laeufe setzen beim naechsten Aufruf fort
      - ein Rate Limit beendet den Lauf mit Exit-Code 1, ohne Daten zu
        beschaedigen
      - save_snapshot() ersetzt einen brauchbaren Stand nie durch einen leeren
    """
    from src.api.apisports_api import resolve_season, ApisportsRateLimit

    season = resolve_season()
    print("=" * 70)
    print(f"  Aktualisierung der laufenden Saison {season}/{str(season + 1)[2:]}")
    print("=" * 70)

    acquired, existing = acquire_lock()
    if not acquired:
        print("  Es laeuft bereits ein Import.")
        print(f"  Gestartet: {existing.get('started_at')} (PID {existing.get('pid')})")
        return 1

    fehler = 0
    try:
        for league_code in COMPARE_LEAGUE_CODES:
            label = COMPARE_LEAGUE_LABELS.get(league_code, league_code)
            try:
                # force=False: bereits geladene Seiten bleiben aus dem
                # Cache, nachgeholt wird nur, was fehlt.
                import_one_league(league_code, season, force=False)
            except ApisportsRateLimit as error:
                print(f"  {label}: Tageslimit erreicht ({error})")
                print("  Lauf wird beendet. Der naechste Aufruf setzt fort.")
                return 1
            except Exception as error:
                # Eine einzelne Liga darf die uebrigen nicht mitreissen.
                print(f"  {label}: uebersprungen ({type(error).__name__}: {error})")
                fehler += 1

        build_and_save_snapshot(season, min_minutes)
    finally:
        release_lock()

    print_report(season)
    return 1 if fehler == len(COMPARE_LEAGUE_CODES) else 0


def _format_minutes(minuten):
    """Minuten je Wettbewerbsumfang kompakt darstellen."""
    if minuten is None:
        return "kein Stand vorhanden"
    if not minuten:
        return "keine Vereinsdaten"
    return "  ".join(f"{scope}={wert}"
                     for scope, wert in sorted(minuten.items())
                     if wert is not None)


def run_targeted_refetch(season, player_ids=None, team_ids=None,
                         dry_run=False, min_minutes=DEFAULT_MIN_MINUTES):
    """
    Gezielter Neuabruf einzelner Spieler oder Vereine.

    Der Gegenentwurf zum Ligarefresh: Wer zwei Werte pruefen will, soll
    zwei Requests bezahlen und nicht 450. Der Ligaweg bleibt daneben
    bestehen - er ist fuer den Erstimport gedacht, nicht fuer Korrekturen.

    Rueckgabe: Exitcode. Ungleich null, wenn KEIN einziger Spieler
    erfolgreich war - ein Teilfehler allein reicht dafuer nicht, sonst
    waere ein Lauf mit neunundneunzig Erfolgen und einem Ausfall
    insgesamt "gescheitert".
    """
    from src.data.player_refetch import (
        normalize_ids, refetch_many, resolve_player, team_player_ids,
    )

    ids, abgewiesen = normalize_ids(player_ids)
    team_ids, team_abgewiesen = normalize_ids(team_ids)
    abgewiesen += team_abgewiesen

    # Vereine ueber den gecachten Kaderindex aufloesen.
    for team_id in team_ids:
        mitglieder, teamname = team_player_ids(team_id, season)
        if not mitglieder:
            print(f"\n  Verein {team_id}: im Kaderindex der Saison {season} "
                  f"nicht gefunden.")
            print("     Der Index wird nur gelesen, nicht gebaut - ein Aufbau "
                  "kostet rund 100 Requests.")
            print("     Erst 'refresh_players.py --update-current' ausfuehren, "
                  "dann erneut versuchen.")
            continue
        print(f"\n  Verein {team_id} ({teamname or 'unbenannt'}): "
              f"{len(mitglieder)} Spieler im Kaderindex")
        ids.extend(pid for pid in mitglieder if pid not in ids)

    if not ids:
        print("\n  Keine gueltige Spieler-ID.")
        for roh, grund in abgewiesen:
            print(f"     {roh!r}: {grund}")
        return 1

    print(f"\n  Gezielter Refresh, Saison {season}/{str(season + 1)[2:]}")
    print(f"  Spieler: {len(ids)}")
    print(f"  Erwarteter Aufwand: {len(ids)} Requests "
          f"(ein Profil je Spieler)")
    if dry_run:
        print("  --dry-run: Der Anbieter wird gefragt, aber es wird NICHTS")
        print("             geschrieben - weder Cache noch Pool noch Status.")
    else:
        print("  Es wird KEINE Cachedatei geloescht. Eine ungueltige Antwort")
        print("  ersetzt nichts, der bisherige Stand bleibt dann erhalten.")

    for roh, grund in abgewiesen:
        print(f"  Abgewiesen: {roh!r} ({grund})")

    # Vorher aufloesen, damit der Bericht auch bei einem Ausfall Namen zeigt.
    for pid in ids:
        herkunft = resolve_player(pid, season)
        if herkunft.get("source") is None:
            print(f"  Hinweis: Spieler {pid} ist lokal unbekannt - er wird "
                  f"abgerufen, sein Pooleintrag laesst sich aber nicht zuordnen.")

    print()
    ergebnisse, zusammenfassung = refetch_many(
        ids, season, dry_run=dry_run, throttle_seconds=THROTTLE_SECONDS,
    )

    for e in ergebnisse:
        print(f"  Spieler {e['player_id']}  {e['name'] or 'unbekannt'}")
        print(f"     Verein          {e['team_name'] or 'nicht aufgeloest'}"
              f"   Liga {e['league_code'] or '-'}"
              f"   (Quelle: {e['resolved_from'] or 'keine'})")
        print(f"     Cache vorher    {e['old_fetched_at'] or 'kein Eintrag'}")
        print(f"     Cache nachher   {e['new_fetched_at'] or 'unveraendert'}")
        print(f"     Minuten vorher  {_format_minutes(e['old_minutes'])}")
        print(f"     Minuten nachher {_format_minutes(e['new_minutes'])}")
        print(f"     Veraendert      {'ja' if e['changed'] else 'nein'}")
        print(f"     Qualitaet       {e['quality']} - {e['quality_reason']}")
        print(f"     Pool aktualisiert {'ja' if e['pool_updated'] else 'nein'}")
        if e["error"]:
            print(f"     FEHLER          {e['error']}")
            print(f"     {'':16}Der vorhandene Stand bleibt unveraendert.")
        print()

    print("  Zusammenfassung")
    print(f"     angefragt          {zusammenfassung['angefragt']}")
    print(f"     erfolgreich        {zusammenfassung['erfolgreich']}")
    print(f"     fehlgeschlagen     {zusammenfassung['fehlgeschlagen']}")
    print(f"     Werte veraendert   {zusammenfassung['veraendert']}")
    print(f"     Pool aktualisiert  {zusammenfassung['pool_aktualisiert']}")
    print(f"     API-Requests       {zusammenfassung['requests']}")
    if zusammenfassung["abgebrochen"]:
        print("     ABGEBROCHEN wegen Rate Limit - spaeter erneut aufrufen.")

    if dry_run:
        print("     persistiert        nein")
        return 0

    # Der Snapshot haengt an den Pooldaten. Er wird nur dann neu berechnet,
    # wenn sich wirklich etwas geaendert hat - und ausschliesslich lokal,
    # ohne einen einzigen weiteren Anbieterabruf.
    if zusammenfassung["pool_aktualisiert"]:
        print()
        print("  Pool veraendert - Perzentil-Snapshot wird neu berechnet")
        print("  (rein lokal, keine API-Requests).")
        build_and_save_snapshot(season, min_minutes)

    return 0 if zusammenfassung["erfolgreich"] else 1


def run_post_match(season, date_str=None, max_players=600, dry_run=False,
                   min_minutes=DEFAULT_MIN_MINUTES):
    """
    Spielbezogene Aktualisierung: nur wer gespielt hat, wird neu geholt.

    Der Gegenentwurf zum taeglichen Vollrefresh. Statt 2.250 Abrufe fuer
    alle fuenf Ligen kostet ein normaler Spieltag rund 500, ein Tag ohne
    Spiele genau einen. Der Lauf ist idempotent und darf deshalb spaeter
    von einem Timer wiederholt ausgefuehrt werden - siehe
    ops/players-refresh.md.

    Der Plan wird IMMER zuerst gerechnet und angezeigt. Wer 500 Abrufe
    ausloest, soll das vorher sehen und nicht hinterher im Kontostand
    entdecken.
    """
    from src.data.fixture_refresh import run_post_match_refresh

    tag = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"\n  Spielbezogene Aktualisierung, Saison "
          f"{season}/{str(season + 1)[2:]}")
    print(f"  Stichtag: {tag}")
    print("  Ein Fixture-Abruf deckt alle fuenf Ligen ab.")
    if dry_run:
        print("  --dry-run: es wird NICHTS geschrieben.")
    print()

    try:
        plan, ergebnisse, zusammenfassung = run_post_match_refresh(
            season, date_str=tag, dry_run=dry_run, max_players=max_players,
        )
    except Exception as fehler:
        print(f"  Fixture-Abruf gescheitert: {fehler}")
        print("  Es wurde nichts veraendert. Spaeter erneut versuchen.")
        return 1

    print(f"  Mannschaften mit beendetem Spiel: {len(plan['teams'])}")
    if plan["teams"]:
        print(f"     {plan['teams']}")
    if plan["running_teams"]:
        print(f"  Mannschaften im laufenden Spiel: {plan['running_teams']}")
        print("     Sie werden NICHT geholt - ein Zwischenstand waere")
        print("     sofort wieder veraltet.")
    if plan["teams_without_squad"]:
        print(f"  Ohne Kaderindex, uebersprungen: {plan['teams_without_squad']}")
        print("     'refresh_players.py --update-current' baut ihn auf.")
    if plan.get("gekuerzt_auf"):
        print(f"  Auf {plan['gekuerzt_auf']} Spieler begrenzt "
              f"(von {plan['requests_players']}).")

    print()
    print(f"  Geplante Requests: {plan['requests_total']} "
          f"(1 Fixtures + {plan['requests_players']} Profile)")
    print(f"  Zum Vergleich, ein Vollrefresh: rund "
          f"{len(COMPARE_LEAGUE_CODES) * 450} Requests")
    print()

    if not ergebnisse:
        print("  Nichts zu tun.")
        return 0

    veraendert = [e for e in ergebnisse if e["changed"]]
    print(f"  Bearbeitet         {zusammenfassung['bearbeitet']}")
    print(f"  Erfolgreich        {zusammenfassung['erfolgreich']}")
    print(f"  Fehlgeschlagen     {zusammenfassung['fehlgeschlagen']}")
    print(f"  Werte veraendert   {len(veraendert)}")
    print(f"  Pool aktualisiert  {zusammenfassung['pool_aktualisiert']}")
    print(f"  API-Requests       {zusammenfassung['requests'] + 1}")
    if zusammenfassung["abgebrochen"]:
        print("  ABGEBROCHEN wegen Rate Limit - spaeter erneut aufrufen.")

    for e in veraendert[:20]:
        print(f"     {e['player_id']:>7}  {(e['name'] or '?')[:24]:24}  "
              f"{_format_minutes(e['old_minutes'])}  ->  "
              f"{_format_minutes(e['new_minutes'])}")

    if not dry_run and zusammenfassung["pool_aktualisiert"]:
        print()
        print("  Pool veraendert - Perzentil-Snapshot wird neu berechnet")
        print("  (rein lokal, keine API-Requests).")
        build_and_save_snapshot(season, min_minutes)

    return 0


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
    parser.add_argument("--backfill-scopes", action="store_true",
                        help="fehlende Wettbewerbsumfaenge (z. B. neu eingefuehrtes "
                             "'cl') in vorhandenen Pooleintraegen ergaenzen - "
                             "ausschliesslich aus bereits gecachten Rohantworten, "
                             "keine API-Requests")
    parser.add_argument("--national-competition", type=int, metavar="LEAGUE_ID",
                        help="GENAU EINEN Nationalmannschaftswettbewerb importieren "
                             "(z. B. 4 = EM, 1 = WM). Braucht --api-season. Die "
                             "FootSim-Zielsaison wird aus dem hinterlegten Mapping "
                             "abgeleitet. Laedt bewusst NICHT die uebrigen "
                             "Wettbewerbe der Saison.")
    parser.add_argument("--api-season", type=int, metavar="YEAR",
                        help="API-Sports-Season des Wettbewerbs, z. B. 2024 fuer "
                             "die EM 2024. Nur mit --national-competition.")
    parser.add_argument("--dry-run", action="store_true",
                        help="mit --national-competition: nur anzeigen, was geladen "
                             "wuerde - ohne Request und ohne Schreiben")
    parser.add_argument("--update-current", action="store_true",
                        help="Laufende Saison aktualisieren (Betriebsmodus fuer "
                             "den woechentlichen Timer). Loest die Saison "
                             "dynamisch auf, laedt fehlende Seiten nach und "
                             "erneuert den Snapshot - ohne alles neu zu holen.")
    parser.add_argument("--diagnose", action="store_true",
                        help="Technische Diagnose des Datenstands. Rein "
                             "lesend, kein API-Request.")
    parser.add_argument("--refetch-players", action="store_true",
                        help="Spielerdetails frisch vom Anbieter holen, statt "
                             "den 24-Stunden-Cache zu benutzen. Teuer - nur "
                             "verwenden, wenn ein waehrend eines Spiels "
                             "erfasster Zwischenstand korrigiert werden soll. "
                             "Loescht keine Datei.")
    parser.add_argument("--refetch-player", action="append", type=int,
                        metavar="PLAYER_ID", dest="refetch_player",
                        help="GENAU DIESEN Spieler frisch holen - ein Request "
                             "je Spieler statt rund 450 fuer eine ganze Liga. "
                             "Mehrfach angebbar. Die Liga muss nicht genannt "
                             "werden, sie wird lokal aufgeloest. Mit --dry-run "
                             "wird nur verglichen und nichts geschrieben.")
    parser.add_argument("--refetch-team", action="append", type=int,
                        metavar="TEAM_ID", dest="refetch_team",
                        help="alle Spieler dieses Vereins frisch holen, "
                             "aufgeloest ueber den gecachten Kaderindex. "
                             "Mehrfach angebbar. Rund 25 Requests je Verein.")
    parser.add_argument("--post-match", action="store_true",
                        dest="post_match",
                        help="nur die Spieler der Mannschaften erneuern, deren "
                             "Spiel heute regulaer zu Ende ging. Ein einziger "
                             "Fixture-Abruf deckt alle fuenf Ligen ab; ein Tag "
                             "ohne Spiele kostet genau einen Request. Fuer den "
                             "regelmaessigen Betrieb gedacht.")
    parser.add_argument("--date", type=str, metavar="YYYY-MM-DD",
                        help="Stichtag fuer --post-match, Standard heute")
    parser.add_argument("--max-players", type=int, default=600,
                        help="Obergrenze fuer --post-match, Standard 600")
    parser.add_argument("--force", action="store_true",
                        help="bereits geladene Ligen erneut vollstaendig laden")
    parser.add_argument("--min-minutes", type=int, default=DEFAULT_MIN_MINUTES,
                        help=f"Mindestspielzeit fuer den Pool, Standard {DEFAULT_MIN_MINUTES}")

    args = parser.parse_args()
    season = args.season

    if args.report:
        print_report(season)
        return 0

    if args.diagnose:
        print_diagnostics(season)
        return 0

    if args.post_match:
        if args.dry_run:
            return run_post_match(season, args.date, args.max_players,
                                  dry_run=True, min_minutes=args.min_minutes)
        acquired, existing = acquire_lock()
        if not acquired:
            print("\n  Es laeuft bereits ein Import.")
            print(f"  Gestartet: {existing.get('started_at')} "
                  f"(PID {existing.get('pid')})")
            return 1
        try:
            return run_post_match(season, args.date, args.max_players,
                                  dry_run=False, min_minutes=args.min_minutes)
        finally:
            release_lock()

    # Der gezielte Refresh steht bewusst VOR der Pruefung auf --all/--league:
    # Er braucht keine Liga, das ist sein ganzer Zweck.
    if args.refetch_player or args.refetch_team:
        if args.dry_run:
            # Ein Diagnoselauf schreibt nichts und braucht deshalb auch
            # keine Sperre - er darf neben einem laufenden Import stehen.
            return run_targeted_refetch(
                season, player_ids=args.refetch_player,
                team_ids=args.refetch_team, dry_run=True,
                min_minutes=args.min_minutes)

        acquired, existing = acquire_lock()
        if not acquired:
            print("\n  Es laeuft bereits ein Import.")
            print(f"  Gestartet: {existing.get('started_at')} "
                  f"(PID {existing.get('pid')})")
            return 1
        try:
            return run_targeted_refetch(
                season, player_ids=args.refetch_player,
                team_ids=args.refetch_team, dry_run=False,
                min_minutes=args.min_minutes)
        finally:
            release_lock()

    if args.snapshot:
        print(f"\n  Perzentil-Snapshot fuer Saison {season}\n")
        build_and_save_snapshot(season, args.min_minutes)
        print()
        return 0

    if args.national_competition is not None:
        if args.api_season is None:
            print("\n  --national-competition braucht zusaetzlich --api-season.")
            print("  Beispiel: --national-competition 4 --api-season 2024\n")
            return 1

        if args.dry_run:
            result = import_single_national_competition(
                args.national_competition, args.api_season, args.min_minutes,
                dry_run=True,
            )
            print()
            return 0 if result else 1

        acquired, existing = acquire_lock()
        if not acquired:
            print("\n  Es laeuft bereits ein Import.")
            print(f"  Gestartet: {existing.get('started_at')} (PID {existing.get('pid')})")
            return 1
        try:
            result = import_single_national_competition(
                args.national_competition, args.api_season, args.min_minutes,
            )
            print()
            return 0 if result else 1
        finally:
            release_lock()

    if args.backfill_scopes:
        acquired, existing = acquire_lock()
        if not acquired:
            print("\n  Es laeuft bereits ein Import.")
            print(f"  Gestartet: {existing.get('started_at')} (PID {existing.get('pid')})")
            return 1
        try:
            report = backfill_missing_scopes(season, args.min_minutes)
            print()
            print_report(season)
            return 0 if report is not None else 1
        finally:
            release_lock()

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

    if args.update_current:
        return run_update_current(args.min_minutes)

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

        if args.refetch_players:
            # Wirkt NUR in diesem Prozess und NUR fuer die Spielerprofile.
            # Es wird keine Datei geloescht: Der bestehende Eintrag bleibt
            # liegen und dient weiterhin als Notfallrueckfall, falls der
            # Anbieter waehrend des Laufs ausfaellt. Er wird lediglich
            # nicht mehr als frisch akzeptiert und danach ueberschrieben.
            from src.utils import disk_cache

            aktiv = disk_cache.bypass_prefixes("apisports:playerprofile:")
            print()
            print("  --refetch-players ist aktiv.")
            print(f"     Umgangene Cacheschluessel: {', '.join(aktiv)}")
            print(f"     Erwarteter Aufwand: grob {len(targets) * 450} Requests"
                  f" ({len(targets)} Ligen)")
            print("     Es wird KEINE Cachedatei geloescht.")
            print("     Bei Rate Limit bricht der Lauf ab und setzt spaeter fort.")

        all_ok = True
        for code in targets:
            if not import_one_league(code, season, force=args.force,
                                     refetch_players=args.refetch_players):
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
