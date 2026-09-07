#!/usr/bin/env python
"""
Sammler fuer Kader- und Verfuegbarkeitsmomentaufnahmen (V2-C6).

    python collect_snapshots.py --daily
    python collect_snapshots.py --daily --dry-run
    python collect_snapshots.py --teams 157,165 --season 2026
    python collect_snapshots.py --leagues bl1,cl --kinds availability
    python collect_snapshots.py --daily --limit 5
    python collect_snapshots.py --coverage

WARUM EIN EIGENER PROZESS
-------------------------
Der Sammler haengt ausdruecklich NICHT am Flask-Webprozess. Unter
Gunicorn laufen mehrere Worker; ein an den Anwendungsstart gekoppelter
Sammler liefe bei jedem Neustart und in jedem Worker erneut. Die
Dateisperre faengt das ab, aber sie ist die zweite Verteidigungslinie -
die erste ist, ihn gar nicht erst dort aufzurufen.

Auf dem Server startet ihn ein systemd-Timer; die Vorlagen liegen in
deploy/systemd/.

EXIT-CODES
----------
    0   complete   alles Geplante bearbeitet, nichts fehlgeschlagen
    3   partial    etwas gesammelt, aber nicht alles
    4   failed     nichts Verwertbares gesammelt
    5   busy       ein anderer Lauf haelt die Sperre
    2   Aufrufsfehler

Ein unvollstaendiger Lauf meldet NICHT 0. Sonst haette ein Timer, der
jeden Tag brav "erfolgreich" meldet, monatelang die Haelfte der Daten
verloren, ohne dass es auffiele.
"""

import argparse
import io
import json
import os
import sys
from datetime import datetime, timezone

from src.data import availability_snapshots as av      # noqa: E402
from src.data import snapshot_collector as sc          # noqa: E402
from src.data import snapshot_reader as sr             # noqa: E402
from src.data import snapshot_scopes as scopes_mod     # noqa: E402

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_PARTIAL = 3
EXIT_FAILED = 4
EXIT_BUSY = 5

STATUS_TO_EXIT = {
    sc.RUN_COMPLETE: EXIT_OK,
    sc.RUN_PARTIAL: EXIT_PARTIAL,
    sc.RUN_FAILED: EXIT_FAILED,
}


def parse_liste(text):
    """"a,b , c" -> ["a", "b", "c"]. Leere Eintraege fallen weg."""
    return [teil.strip() for teil in str(text).split(",") if teil.strip()]


def parse_int_liste(text):
    werte = []
    for teil in parse_liste(text):
        try:
            werte.append(int(teil))
        except ValueError:
            raise argparse.ArgumentTypeError(f"keine Zahl: {teil!r}")
    return werte


def build_parser():
    parser = argparse.ArgumentParser(
        prog="collect_snapshots",
        description="Point-in-Time-Snapshots fuer Kader und Verfuegbarkeit")

    parser.add_argument("--daily", action="store_true",
                        help="vollstaendiger geplanter Tageslauf")
    parser.add_argument("--coverage", action="store_true",
                        help="nur berichten, was das Archiv bereits enthaelt")

    parser.add_argument("--teams", type=parse_int_liste, default=None,
                        help="gezielter Lauf: API-Sports-Team-IDs")
    parser.add_argument("--leagues", type=parse_liste, default=None,
                        help="gezielter Lauf: Ligaschluessel, z. B. bl1,cl")
    parser.add_argument("--season", type=int, default=None,
                        help="Saison (Standard: laufende)")
    parser.add_argument("--kinds", type=parse_liste, default=None,
                        help=f"Arten, Standard {','.join(av.SNAPSHOT_KINDS)}")

    parser.add_argument("--dry-run", action="store_true",
                        help="nichts schreiben, nur berichten was waere")
    parser.add_argument("--limit", type=int, default=None,
                        help="hoechstens so viele Scopes (Probemodus)")
    parser.add_argument("--quota-margin", type=int,
                        default=sc.QUOTA_SAFETY_MARGIN,
                        help="anhalten, wenn so wenige Tagesanfragen bleiben")
    parser.add_argument("--no-national", action="store_true",
                        help="die 18 nationalen Ligen aus V2-C2B auslassen")
    parser.add_argument("--report-dir", type=str, default=None,
                        help="Zielverzeichnis der Laufberichte")
    parser.add_argument("--no-report", action="store_true",
                        help="keinen Laufbericht schreiben")
    parser.add_argument("--json", action="store_true",
                        help="den Bericht als JSON auf die Standardausgabe")
    parser.add_argument("--ignore-lock", action="store_true",
                        help="ohne Sperre laufen - nur fuer Diagnose")
    return parser


# ---------------------------------------------------------------------------
# Ausgabe
# ---------------------------------------------------------------------------

def _zeile(text=""):
    print(text)


def print_summary(report, diagnose=None):
    """
    Die menschliche Zusammenfassung. Ohne Geheimnisse.

    Es werden ausschliesslich Zahlen, Bezeichner und die vier bekannten
    Kontingentkopfzeilen ausgegeben - niemals Kopfzeilen des Anbieters
    als Ganzes und niemals ein Schluessel.
    """
    _zeile()
    _zeile("=" * 68)
    _zeile(f"Sammellauf {report['status'].upper()}"
           + ("  (Probelauf, nichts geschrieben)" if report["dry_run"] else ""))
    _zeile("=" * 68)
    _zeile(f"  Beginn   {report['started_at']}")
    _zeile(f"  Ende     {report['finished_at']}  ({report['duration_seconds']} s)")
    _zeile(f"  Sammler  {report['collector_version']}  "
           f"Schema {report['snapshot_schema_version']}")
    if diagnose:
        for quelle in diagnose.get("sources", []):
            _zeile("  Quelle   %-34s %s"
                   % (quelle.get("source"), quelle.get("count")))
    _zeile()
    _zeile(f"  geplant      {report['planned_scopes']:5d}")
    _zeile(f"  bearbeitet   {report['attempted_scopes']:5d}")
    _zeile(f"  uebersprungen{report['skipped_scopes']:5d}")
    _zeile()
    _zeile(f"  neu gesichert   {report['snapshots_stored']:5d}")
    _zeile(f"  unveraendert    {report['snapshots_unchanged']:5d}")
    _zeile(f"  ohne Daten      {report['scopes_empty']:5d}")
    _zeile(f"  fehlgeschlagen  {report['scopes_failed']:5d}")
    _zeile()
    _zeile(f"  Anfragen        {report['requests_attempted']:5d}"
           f"   davon wiederholt {report['requests_retried']}")

    quota = report.get("observed_quota") or {}
    if quota:
        uebrig = quota.get("x-ratelimit-requests-remaining")
        grenze = quota.get("x-ratelimit-requests-limit")
        _zeile(f"  Kontingent      {uebrig} von {grenze} verbleibend")
    else:
        _zeile("  Kontingent      nicht beobachtet")

    if report.get("halted_reason"):
        _zeile(f"  ANGEHALTEN: {report['halted_reason']}")

    deckung = report.get("coverage") or {}
    if deckung:
        _zeile()
        _zeile("  Abdeckung:")
        for art, werte in sorted(deckung.items()):
            _zeile("    %-14s %4d von %4d  (%.1f %%)"
                   % (art, werte["covered"], werte["planned"],
                      werte["coverage_pct"]))

    if report.get("failures"):
        _zeile()
        _zeile("  Fehlgeschlagene Scopes:")
        for fehler in report["failures"][:10]:
            _zeile(f"    {fehler['kind']:<13} {fehler['label']}: "
                   f"{'; '.join(str(e) for e in fehler['errors'])}")
        if len(report["failures"]) > 10:
            _zeile(f"    ... und {len(report['failures']) - 10} weitere")
    _zeile()


def print_coverage():
    """Was liegt ueberhaupt im Archiv?"""
    _zeile()
    _zeile("=" * 68)
    _zeile("Archivbestand")
    _zeile("=" * 68)
    for art in av.SNAPSHOT_KINDS:
        fenster = sr.archive_window(art)
        _zeile(f"  {art}")
        _zeile(f"    Snapshots   {fenster['snapshots']}")
        _zeile(f"    Schluessel  {len(fenster['keys'])}")
        _zeile(f"    frueheste   {fenster['earliest'] or '-'}")
        _zeile(f"    juengste    {fenster['latest'] or '-'}")
        _zeile(f"    nutzbar ab  {fenster['usable_from'] or '(noch nichts)'}")
    _zeile()
    _zeile("  Vor 'nutzbar ab' existiert keine Historie. Diese Luecke")
    _zeile("  laesst sich nicht nachtraeglich schliessen - der Anbieter")
    _zeile("  liefert Kader und Ausfaelle als aktuellen Stand.")
    _zeile()
    return EXIT_OK


# ---------------------------------------------------------------------------
# Lauf
# ---------------------------------------------------------------------------

def _resolve_season(argument):
    if argument is not None:
        return argument
    from src.api.apisports_api import resolve_season

    return resolve_season()


def _leagues_from_keys(keys, league_ids=None):
    """Ligaschluessel -> Ligaeintraege. Unbekannte werden gemeldet."""
    from src.api.apisports_api import LEAGUE_IDS
    from src.data.national_league_loader import NATIONAL_LEAGUES

    league_ids = league_ids or LEAGUE_IDS
    ligen, unbekannt = [], []
    for key in keys:
        lid = league_ids.get(key)
        if lid is None:
            cfg = NATIONAL_LEAGUES.get(key) or {}
            lid = cfg.get("apisports_id")
        if lid is None:
            unbekannt.append(key)
            continue
        ligen.append({"league_id": int(lid), "key": key, "label": key,
                      "priority": scopes_mod.PRIORITY_AVAILABILITY_CORE})
    return ligen, unbekannt


def run(args, transport=None, now=None):
    """
    Der eigentliche Lauf. Rueckgabe: (exit_code, report).

    transport und now sind einspeisbar, damit die Tests ohne Netz und
    mit festen Zeitstempeln laufen koennen.
    """
    season = _resolve_season(args.season)
    kinds = tuple(args.kinds) if args.kinds else av.SNAPSHOT_KINDS

    unbekannte_arten = [k for k in kinds if k not in av.SNAPSHOT_KINDS]
    if unbekannte_arten:
        _zeile(f"Unbekannte Snapshotart: {unbekannte_arten} - bekannt sind "
               f"{list(av.SNAPSHOT_KINDS)}")
        return EXIT_USAGE, None

    teams = None
    leagues = None

    if args.teams:
        teams = [{"team_id": tid, "label": f"team {tid}",
                  "priority": scopes_mod.PRIORITY_SQUAD_TOP5}
                 for tid in args.teams]
    if args.leagues:
        leagues, unbekannt = _leagues_from_keys(args.leagues)
        if unbekannt:
            _zeile(f"Unbekannte Liga(en): {unbekannt}")
            return EXIT_USAGE, None

    # Beim gezielten Lauf wird NICHT zusaetzlich ermittelt: Wer
    # "--teams 157" sagt, will genau diese eine Mannschaft und nicht
    # noch vierhundert dazu.
    if args.teams and not args.leagues:
        leagues = []
    if args.leagues and not args.teams:
        teams = []

    teams, leagues, diagnose = scopes_mod.discover(
        season, kinds=kinds, include_national=not args.no_national,
        teams=teams, leagues=leagues)

    geplant = sc.plan_scopes(teams, leagues, season, kinds=kinds)
    if not geplant:
        _zeile("Nichts zu sammeln - der Plan ist leer.")
        return EXIT_USAGE, None

    _zeile(f"Sammellauf: {len(geplant)} Scopes, Saison {season}, "
           f"Arten {','.join(kinds)}"
           + ("  [PROBELAUF]" if args.dry_run else ""))
    if args.limit:
        _zeile(f"  Probemodus: hoechstens {args.limit} Scopes")

    report = sc.run_collection(
        geplant, transport=transport, dry_run=args.dry_run, limit=args.limit,
        quota_margin=args.quota_margin, now=now,
        spacing=sc.REQUEST_SPACING_SECONDS)
    report["scope_discovery"] = diagnose
    report["season"] = season
    report["kinds"] = list(kinds)

    if not args.no_report and not args.dry_run:
        pfad = sc.write_report(report, directory=args.report_dir)
        report["report_path"] = os.path.basename(pfad)

    return STATUS_TO_EXIT.get(report["status"], EXIT_FAILED), report


def main(argv=None, transport=None, now=None):
    args = build_parser().parse_args(argv)

    if args.coverage:
        return print_coverage()

    if not (args.daily or args.teams or args.leagues):
        _zeile("Nichts zu tun. --daily, --teams, --leagues oder --coverage "
               "angeben.")
        return EXIT_USAGE

    if args.limit is not None and args.limit <= 0:
        _zeile("--limit muss groesser als null sein.")
        return EXIT_USAGE

    sperre = None
    if not args.ignore_lock:
        sperre = sc.CollectorLock()
        try:
            sperre.acquire()
        except sc.CollectorBusy as fehler:
            _zeile(f"Sammellauf laeuft bereits: {fehler}")
            return EXIT_BUSY
        if sperre.takeover:
            _zeile(f"Verwaiste Sperre uebernommen: {sperre.takeover}")

    try:
        code, report = run(args, transport=transport, now=now)
    finally:
        if sperre is not None:
            sperre.release()

    if report is None:
        return code

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True,
                         default=str))
    else:
        print_summary(report, report.get("scope_discovery"))

    return code


def _force_utf8_stdout():
    """
    Die Konsole des Servers ist nicht zwingend UTF-8.

    Mannschaftsnamen tragen Umlaute und Akzente; ohne diese Umstellung
    bricht der Lauf beim ersten "Bayern München" ab - und zwar erst
    beim Bericht, also nach getaner Arbeit.

    BEWUSST NICHT AUF MODULEBENE
    Ein Import darf sys.stdout nicht ersetzen. Wer dieses Modul in
    einem Test oder aus einem anderen Programm importiert, bekaeme sonst
    seine eigene Ausgabe umgebogen - pytest etwa faengt stdout ab, und
    ein Austausch darunter zerreisst genau diese Aufzeichnung. Der
    Aufruf steht deshalb nur im Skriptpfad.
    """
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      errors="replace", line_buffering=True)


if __name__ == "__main__":                               # pragma: no cover
    _force_utf8_stdout()
    sys.exit(main())
