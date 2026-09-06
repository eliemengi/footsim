"""
Nationale Ligahistorien der Champions-League-Teilnehmer ausserhalb der
fuenf Vergleichsligen (V2-C2B).

WOZU
----
V2-C2 hat die Belastungszeitleiste an die CL-Zeilen angebunden. Von
1006 Teamseiten bekamen 658 eine echte Ruhezeit - die uebrigen 348
nicht, mit genau einer Ursache: no_base_competition_in_timeline.

Ein Verein wie Benfica, PSV oder Celtic erscheint in der Zeitleiste
ausschliesslich mit seinen CL-Partien im Zweiwochentakt. Seine
Ligaspiele - der eigentliche Grundtakt - fehlten schlicht. Nachgemessen
ueber 2023-2025:

    mit nationaler Ligahistorie   Median  3,0 Ruhetage
    ohne                          Median 15,0 Ruhetage

Dieses Modul beschafft genau die fehlenden Ligen. Nicht mehr: Es
enthaelt kein Modell, keine Merkmale und keine Bewertung.

WARUM EIN EIGENES MODUL UND KEIN ZWEITER PROVIDER-LAYER
--------------------------------------------------------
Die Normalisierung, die Statusregeln und der atomare Schreibweg stammen
unveraendert aus domestic_cup_loader - dieselbe Quelle (API-Sports),
dasselbe Schema, dieselben Schutzmechanismen. Neu ist ausschliesslich
die Registrierung der Ligen und der Umstand, dass hier LIGEN statt
Pokale geladen werden (Spieltag statt Runde).

HERKUNFT DER LIGA-IDS
---------------------
Keine ID ist geraten. Jede wurde am 2026-09-06 ueber

    /leagues?team=<apisports_id>

aufgeloest - also aus der Mannschaft heraus, die sie braucht, und nicht
aus einer Landesliste, in der mehrere Wettbewerbe gleich heissen. Je
Verein blieb genau ein Wettbewerb vom Typ "League" mit Saisondaten in
2023-2025 uebrig; bei mehr als einem waere die Aufloesung fehlgeschlagen
statt zu raten.

SAISONSEMANTIK
--------------
API-Sports bezeichnet eine Saison mit ihrem Startjahr - dieselbe
Konvention wie FootSim. Nachgemessen an der Primeira Liga 2025:
308 Partien vom 2025-08-08 bis 2026-05-28.

Eine Ausnahme ist dokumentiert und bewusst nicht "korrigiert": Die
kasachische Premier League spielt im Kalenderjahr. Ihre Saison 2025
endet im November 2025, waehrend die CL-Ligaphase bis Januar 2026
laeuft. Fuer Kairats Januarpartien gibt es deshalb wirklich keinen
nationalen Vorlauf - das ist eine echte Winterpause und keine
Datenluecke. base_load_coverage weist sie als base_competition_stale
aus, statt eine erfundene Zahl zu liefern.
"""

import os
from datetime import datetime, timezone

from src.api.apisports_api import _get, ApisportsUnavailable
from src.data.domestic_cup_loader import (
    FINISHED_STATUSES,
    HISTORICAL_DIR,
    _normalize_match,
    is_finished,
)

#: Fassung des Ablageformats. Deckungsgleich mit domestic_cup_loader.
SCHEMA_VERSION = 1

#: Die nationalen Ligen der CL-Teilnehmer ausserhalb der Top 5.
#:
#: Ermittelt aus dem Bedarf, nicht aus einer Wunschliste: Es steht genau
#: das hier, was mindestens eine offene CL-Teamseite schliessen kann.
#: "sides" nennt, wie viele Seiten die Liga ueber alle Saisons betrifft -
#: die Zahl stammt aus dem Bedarfsaudit und macht nachvollziehbar,
#: warum eine Liga aufgenommen wurde.
NATIONAL_LEAGUES = {
    "pt1":  {"code": "PT1",  "name": "Primeira Liga",      "country": "Portugal",       "apisports_id": 94,  "sides": 64},
    "nl1":  {"code": "NL1",  "name": "Eredivisie",         "country": "Netherlands",    "apisports_id": 88,  "sides": 54},
    "be1":  {"code": "BE1",  "name": "Jupiler Pro League", "country": "Belgium",        "apisports_id": 144, "sides": 36},
    "at1":  {"code": "AT1",  "name": "Bundesliga",         "country": "Austria",        "apisports_id": 218, "sides": 22},
    "tr1":  {"code": "TR1",  "name": "Sueper Lig",         "country": "Turkey",         "apisports_id": 203, "sides": 18},
    "sco1": {"code": "SCO1", "name": "Premiership",        "country": "Scotland",       "apisports_id": 179, "sides": 16},
    "dk1":  {"code": "DK1",  "name": "Superliga",          "country": "Denmark",        "apisports_id": 119, "sides": 16},
    "cz1":  {"code": "CZ1",  "name": "Czech Liga",         "country": "Czech-Republic", "apisports_id": 345, "sides": 16},
    "ch1":  {"code": "CH1",  "name": "Super League",       "country": "Switzerland",    "apisports_id": 207, "sides": 14},
    "rs1":  {"code": "RS1",  "name": "Super Liga",         "country": "Serbia",         "apisports_id": 286, "sides": 14},
    "ua1":  {"code": "UA1",  "name": "Premier League",     "country": "Ukraine",        "apisports_id": 333, "sides": 14},
    "no1":  {"code": "NO1",  "name": "Eliteserien",        "country": "Norway",         "apisports_id": 103, "sides": 12},
    "gr1":  {"code": "GR1",  "name": "Super League 1",     "country": "Greece",         "apisports_id": 197, "sides": 10},
    "az1":  {"code": "AZ1",  "name": "Premyer Liqa",       "country": "Azerbaijan",     "apisports_id": 419, "sides": 10},
    "hr1":  {"code": "HR1",  "name": "HNL",                "country": "Croatia",        "apisports_id": 210, "sides": 8},
    "cy1":  {"code": "CY1",  "name": "1. Division",        "country": "Cyprus",         "apisports_id": 318, "sides": 8},
    "sk1":  {"code": "SK1",  "name": "Super Liga",         "country": "Slovakia",       "apisports_id": 332, "sides": 8},
    "kz1":  {"code": "KZ1",  "name": "Premier League",     "country": "Kazakhstan",     "apisports_id": 389, "sides": 8},
}

#: Genau die Liga-Saison-Kombinationen, die mindestens eine offene
#: CL-Teamseite schliessen. Aus dem Bedarfsaudit abgeleitet - es wird
#: nichts "vorsorglich" geladen.
REQUIRED_SEASONS = {
    "pt1":  (2023, 2024, 2025),
    "nl1":  (2023, 2024, 2025),
    "be1":  (2023, 2024, 2025),
    "at1":  (2023, 2024),
    "tr1":  (2023, 2025),
    "sco1": (2023, 2024),
    "dk1":  (2023, 2025),
    "cz1":  (2024, 2025),
    "ch1":  (2023, 2024),
    "rs1":  (2023, 2024),
    "ua1":  (2023, 2024),
    "no1":  (2025,),
    "gr1":  (2025,),
    "az1":  (2025,),
    "hr1":  (2024,),
    "cy1":  (2025,),
    "sk1":  (2024,),
    "kz1":  (2025,),
}

#: Untergrenze fuer eine plausible Ligasaison. Die kleinste hier
#: vertretene Liga spielt zehn Vereine in vierfacher Runde; alles unter
#: 90 Partien deutet auf eine abgebrochene Antwort hin und wird nicht
#: als vollstaendig gespeichert.
MIN_PLAUSIBLE_MATCHES = 90


def league_config(league_key):
    """Konfiguration einer Liga. Wirft KeyError bei unbekanntem Schluessel."""
    return NATIONAL_LEAGUES[league_key]


def season_file_path(league_key, season):
    """Pfad der Historiendatei, analog zu historical_loader."""
    return os.path.join(HISTORICAL_DIR,
                        f"{league_config(league_key)['code']}_{season}.json")


def has_season(league_key, season):
    """Liegt diese Ligasaison bereits lokal vor?"""
    return os.path.exists(season_file_path(league_key, season))


def required_targets(only_missing=True):
    """
    Die zu ladenden (league_key, season)-Paare.

    only_missing ueberspringt, was bereits auf der Platte liegt. Das ist
    der Standard: Eine abgeschlossene Ligasaison aendert sich nie mehr,
    und sie erneut zu holen kostet Kontingent ohne jeden Gewinn.
    """
    ziele = []
    for league_key in sorted(REQUIRED_SEASONS):
        for season in REQUIRED_SEASONS[league_key]:
            if only_missing and has_season(league_key, season):
                continue
            ziele.append((league_key, season))
    return ziele


def fetch_league_season(league_key, season):
    """
    Holt eine Ligasaison beim Anbieter und normalisiert sie.

    Ein Request je Liga und Saison - der Endpunkt liefert eine
    vollstaendige Ligasaison in einer Seite (nachgemessen: Primeira Liga
    2025, 308 Partien, paging total 1).

    Wirft ApisportsUnavailable weiter; der Aufrufer entscheidet, ob ein
    Fehlschlag den vorhandenen Stand unangetastet laesst
    (save_league_season tut genau das).
    """
    config = league_config(league_key)

    roh = _get("fixtures", params={"league": config["apisports_id"],
                                   "season": season})

    matches = [_normalize_match(eintrag) for eintrag in (roh or [])]
    matches = [m for m in matches if m.get("match_id") is not None]
    matches.sort(key=lambda m: (m.get("date") or "", m.get("match_id") or 0))

    fertige = [m for m in matches if is_finished(m)]

    teams = {}
    for match in matches:
        for seite in ("home", "away"):
            tid = match.get(f"{seite}_id")
            if tid is not None and tid not in teams:
                teams[tid] = {"name": match.get(f"{seite}_team")}

    return {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "code": config["code"],
            "name": config["name"],
            "country": config["country"],
            "competition_type": "league",
            "season": season,
            "source": "api-football.com",
            "provider_competition_id": config["apisports_id"],
            "provider_id_space": "apisports",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "matches": len(matches),
            "matches_finished": len(fertige),
            "teams": len(teams),
            "coverage": ("complete" if matches and len(fertige) == len(matches)
                         else "partial"),
        },
        "teams": teams,
        "matches": matches,
    }


def validate_payload(payload):
    """
    Prueft eine geholte Ligasaison, bevor sie gespeichert wird.

    Historische Anbieterdaten werden NICHT blind uebernommen. Geprueft
    wird auf die Fehler, die sich still fortpflanzen wuerden: doppelte
    Partien, ein Verein gegen sich selbst, fehlende Zeitangaben,
    abgeschlossene Spiele ohne Ergebnis und ein unplausibel kleiner
    Bestand.

    Rueckgabe: Liste von Beanstandungen. Leer heisst brauchbar.
    """
    matches = (payload or {}).get("matches") or []
    beanstandungen = []

    if len(matches) < MIN_PLAUSIBLE_MATCHES:
        beanstandungen.append(
            f"nur {len(matches)} Partien - unter der Plausibilitaetsgrenze "
            f"von {MIN_PLAUSIBLE_MATCHES}")

    gesehen = set()
    for match in matches:
        mid = match.get("match_id")
        if mid in gesehen:
            beanstandungen.append(f"doppelte match_id {mid}")
        gesehen.add(mid)

        if match.get("home_id") is not None \
                and match.get("home_id") == match.get("away_id"):
            beanstandungen.append(f"{mid}: Heim- und Auswaertsteam identisch")

        if not match.get("date"):
            beanstandungen.append(f"{mid}: ohne Datum")

        fertig = str(match.get("status") or "").upper() in FINISHED_STATUSES
        hat_tore = (match.get("home_goals") is not None
                    and match.get("away_goals") is not None)
        if fertig and not hat_tore:
            beanstandungen.append(f"{mid}: abgeschlossen ohne Ergebnis")
        if hat_tore and not fertig and match.get("status") not in (None, "PST",
                                                                   "SUSP"):
            beanstandungen.append(
                f"{mid}: Ergebnis bei Status {match.get('status')!r}")

    saison = (payload.get("meta") or {}).get("season")
    daten = sorted(m["date"] for m in matches if m.get("date"))
    if daten and saison is not None:
        if not (str(saison) in daten[0] or str(saison) in daten[-1]
                or str(saison + 1) in daten[-1]):
            beanstandungen.append(
                f"Saisonbereich {daten[0]}..{daten[-1]} passt nicht zu {saison}")

    # Mehr als fuenf gleichartige Meldungen helfen niemandem.
    return beanstandungen[:20]


def save_league_season(payload, overwrite_empty=False):
    """
    Schreibt eine Ligasaison atomar.

    Drei Sicherungen, jede gegen einen realen Fall:

    1. Ein LEERES Ergebnis ueberschreibt niemals eine vorhandene gute
       Datei. Eine kurze Anbieterstoerung darf gesammelte Historie nicht
       vernichten.
    2. Eine beanstandete Antwort ebenso wenig - validate_payload laeuft
       VOR dem Schreiben.
    3. Erst in eine temporaere Datei, dann umbenennen. Ein parallel
       lesender Prozess sieht nie einen halben Stand.

    Rueckgabe: (pfad, geschrieben, beanstandungen).
    """
    import json
    import tempfile

    meta = (payload or {}).get("meta") or {}
    code = meta.get("code")
    season = meta.get("season")
    league_key = next((k for k, v in NATIONAL_LEAGUES.items()
                       if v["code"] == code), None)
    if league_key is None:
        raise ValueError(f"unbekannter Ligacode {code!r}")

    pfad = season_file_path(league_key, season)
    matches = payload.get("matches") or []

    if not matches and not overwrite_empty and os.path.exists(pfad):
        return pfad, False, ["leere Antwort - vorhandene Datei bleibt"]

    beanstandungen = validate_payload(payload)
    if beanstandungen and os.path.exists(pfad):
        return pfad, False, beanstandungen

    os.makedirs(os.path.dirname(os.path.abspath(pfad)), exist_ok=True)
    handle, temporaer = tempfile.mkstemp(
        dir=os.path.dirname(os.path.abspath(pfad)), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as datei:
            json.dump(payload, datei, ensure_ascii=False, indent=1,
                      sort_keys=True)
            datei.write("\n")
        os.replace(temporaer, pfad)
    except Exception:
        if os.path.exists(temporaer):
            os.remove(temporaer)
        raise

    return pfad, True, beanstandungen


def load_league_season(league_key, season):
    """Eine gespeicherte Ligasaison - oder None."""
    import json

    pfad = season_file_path(league_key, season)
    if not os.path.exists(pfad):
        return None
    try:
        with open(pfad, encoding="utf-8") as datei:
            return json.load(datei)
    except (OSError, json.JSONDecodeError):
        return None


def refresh(only_missing=True, verbose=True, targets=None):
    """
    Holt die fehlenden Ligasaisons - wiederaufnehmbar.

    Ein Fehlschlag bei einer Liga bricht den Lauf NICHT ab: Die uebrigen
    werden weiter geholt, und ein erneuter Aufruf setzt genau dort an,
    wo etwas fehlt. Ohne das muesste nach jeder Stoerung alles neu
    geladen werden - und das kostet Kontingent fuer Daten, die bereits
    auf der Platte liegen.

    Rueckgabe: Bericht als dict.
    """
    ziele = targets if targets is not None else required_targets(only_missing)
    bericht = {"attempted": 0, "written": 0, "skipped_existing": 0,
               "failed": [], "rejected": [], "files": []}

    if only_missing and targets is None:
        bericht["skipped_existing"] = sum(
            1 for k in REQUIRED_SEASONS for s in REQUIRED_SEASONS[k]
            if has_season(k, s))

    for league_key, season in ziele:
        bericht["attempted"] += 1
        config = league_config(league_key)
        try:
            payload = fetch_league_season(league_key, season)
        except ApisportsUnavailable as fehler:
            bericht["failed"].append({"league": league_key, "season": season,
                                      "error": str(fehler)[:200]})
            if verbose:
                print(f"  FEHLER {config['code']} {season}: {fehler}")
            continue

        pfad, geschrieben, beanstandungen = save_league_season(payload)
        if geschrieben:
            bericht["written"] += 1
            bericht["files"].append({
                "file": os.path.basename(pfad),
                "league": config["name"], "country": config["country"],
                "season": season,
                "matches": payload["meta"]["matches"],
                "matches_finished": payload["meta"]["matches_finished"],
                "teams": payload["meta"]["teams"],
            })
            if verbose:
                print(f"  {config['code']} {season}: "
                      f"{payload['meta']['matches']} Partien, "
                      f"{payload['meta']['teams']} Teams -> "
                      f"{os.path.basename(pfad)}")
        else:
            bericht["rejected"].append({"league": league_key, "season": season,
                                        "reasons": beanstandungen})
            if verbose:
                print(f"  ABGELEHNT {config['code']} {season}: "
                      f"{beanstandungen[:2]}")

        if beanstandungen and geschrieben and verbose:
            print(f"     Hinweise: {beanstandungen[:2]}")

    return bericht


def coverage_report():
    """Welche geforderten Ligasaisons liegen vor, welche fehlen?"""
    vorhanden, fehlend = [], []
    for league_key in sorted(REQUIRED_SEASONS):
        config = league_config(league_key)
        for season in REQUIRED_SEASONS[league_key]:
            payload = load_league_season(league_key, season)
            eintrag = {"league": config["name"], "country": config["country"],
                       "code": config["code"], "season": season}
            if payload:
                eintrag["matches"] = (payload.get("meta") or {}).get("matches")
                vorhanden.append(eintrag)
            else:
                fehlend.append(eintrag)
    return {"present": vorhanden, "missing": fehlend,
            "required": sum(len(v) for v in REQUIRED_SEASONS.values()),
            "present_count": len(vorhanden), "missing_count": len(fehlend)}
