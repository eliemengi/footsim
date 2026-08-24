"""
Nationale Hauptpokale der fuenf Topligen als historische Match-Daten.

WARUM API-SPORTS UND NICHT FOOTBALL-DATA
---------------------------------------
Geprueft am 2026-08-22 mit einem einzelnen /competitions-Request: der
football-data.org-Tarif fuehrt genau 13 Wettbewerbe (BSA, ELC, PL, CL,
EC, FL1, BL1, SA, DED, PPL, CLI, PD, WC). Kein einziger nationaler
Hauptpokal ist darunter - als Pokale gibt es dort nur CL, EC, CLI und WC.
Damit scheidet Provider A fuer diese Daten aus; die IDs stammen deshalb
von API-Sports.

WOFUER DIESE DATEN GEDACHT SIND
-------------------------------
Als Grundlage fuer Rest Days und Fixture Congestion. Ein Team, das
mittwochs im Pokal gespielt hat, ist am Samstag nicht ausgeruht - ohne
Pokalspiele ist jede Belastungsrechnung unvollstaendig.

In diesem Durchgang werden die Daten NUR erfasst. Es entsteht kein
Congestion-Modifikator, keine Ratingaenderung und keine Pokalsimulation.

SCHEMA
------
Bewusst dasselbe Format wie data/historical/CL_<saison>.json, damit
historical_loader, congestion.py und spaetere Backtests keine zweite
Datenarchitektur lernen muessen.
"""

import json
import os
from datetime import datetime, timezone

from src.api.apisports_api import _get, ApisportsUnavailable, resolve_season


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HISTORICAL_DIR = os.path.join(_PROJECT_ROOT, "data", "historical")

#: Schema-Version der geschriebenen Dateien.
SCHEMA_VERSION = 1

#: Die fuenf nationalen Hauptpokale.
#:
#: Die IDs wurden am 2026-08-22 ueber /leagues?country=<Land>&type=cup
#: verifiziert - fuenf gezielte Requests, keine Annahme aus dem
#: Gedaechtnis. Jede Liga meldete dort mehrere Pokale; Jugend-, Frauen-
#: und Unterliga-Varianten (DFB Junioren Pokal 715, DFB Pokal Women 947,
#: Coppa Italia Primavera 704 / Serie C 891 / Serie D 892 / Women 1171)
#: sind bewusst NICHT enthalten.
#:
#: Ebenso ausdruecklich KEINE Supercups: GSC, USC und FACS existieren
#: bereits an anderer Stelle im Projekt und sind kein Ersatz fuer den
#: jeweiligen Hauptpokal - sie bestehen aus einem einzigen Spiel.
DOMESTIC_CUPS = {
    "dfb": {
        "code": "DFB",
        "name": "DFB-Pokal",
        "country": "Germany",
        "apisports_id": 81,
        "league_key": "bl1",
    },
    "fac": {
        "code": "FAC",
        "name": "FA Cup",
        "country": "England",
        "apisports_id": 45,
        "league_key": "pl",
    },
    "cdr": {
        "code": "CDR",
        "name": "Copa del Rey",
        "country": "Spain",
        "apisports_id": 143,
        "league_key": "pd",
    },
    "cit": {
        "code": "CIT",
        "name": "Coppa Italia",
        "country": "Italy",
        "apisports_id": 137,
        "league_key": "sa",
    },
    "cdf": {
        "code": "CDF",
        "name": "Coupe de France",
        "country": "France",
        "apisports_id": 66,
        "league_key": "fl1",
    },
}

#: Statuskuerzel, die ein endgueltiges Ergebnis bezeichnen.
#: Deckungsgleich mit team_profile.FINISHED_STATUSES.
FINISHED_STATUSES = frozenset({"FT", "AET", "PEN"})


def cup_config(cup_key):
    """Konfiguration eines Pokals. Wirft KeyError bei unbekanntem Schluessel."""
    return DOMESTIC_CUPS[cup_key]


def season_file_path(cup_key, season):
    """Pfad der Historiendatei, analog zu historical_loader."""
    return os.path.join(HISTORICAL_DIR, f"{cup_config(cup_key)['code']}_{season}.json")


def _normalize_match(raw):
    """
    Ein API-Sports-Fixture in das gemeinsame Historienschema.

    Elfmeterschiessen wird getrennt gefuehrt: In einem Pokal entscheidet
    es die Runde, veraendert aber das Ergebnis nach 120 Minuten nicht.
    Wer Tore auswertet, darf Elfmeter nicht mitzaehlen; wer den
    Weiterkommenden sucht, braucht sie.
    """
    fixture = raw.get("fixture") or {}
    league = raw.get("league") or {}
    teams = raw.get("teams") or {}
    goals = raw.get("goals") or {}
    score = raw.get("score") or {}

    home = teams.get("home") or {}
    away = teams.get("away") or {}
    status = (fixture.get("status") or {}).get("short")
    penalty = score.get("penalty") or {}
    datum = fixture.get("date") or ""

    return {
        "match_id": fixture.get("id"),
        # Datum getrennt von der vollstaendigen Zeitangabe: congestion.py
        # und point_in_time.py rechnen mit dem Tag, fuer die Pause vor dem
        # Anpfiff wird die Uhrzeit gebraucht.
        "date": datum[:10] if datum else None,
        "kickoff": datum or None,
        "status": status,
        # In Pokalen gibt es keine Spieltagsnummern, sondern Runden.
        "stage": league.get("round"),
        "home_id": home.get("id"),
        "home_team": home.get("name"),
        "away_id": away.get("id"),
        "away_team": away.get("name"),
        "home_goals": goals.get("home"),
        "away_goals": goals.get("away"),
        "penalty_home": penalty.get("home"),
        "penalty_away": penalty.get("away"),
    }


def is_finished(match):
    """Ist dieses Spiel abgeschlossen und auswertbar?"""
    if match.get("home_goals") is None or match.get("away_goals") is None:
        return False
    status = match.get("status")
    if status is None:
        return False
    return str(status).upper() in FINISHED_STATUSES


def fetch_cup_season(cup_key, season=None):
    """
    Holt eine Pokalsaison beim Anbieter und normalisiert sie.

    Ein Request je Pokal und Saison. Wirft ApisportsUnavailable weiter -
    der Aufrufer entscheidet, ob ein Fehlschlag den vorhandenen Stand
    unangetastet lassen soll (save_cup_season tut genau das).
    """
    config = cup_config(cup_key)
    season = resolve_season(season)

    raw = _get("fixtures", params={
        "league": config["apisports_id"],
        "season": season,
    })

    matches = [_normalize_match(entry) for entry in (raw or [])]
    matches = [m for m in matches if m.get("match_id") is not None]
    matches.sort(key=lambda m: (m.get("date") or "", m.get("match_id") or 0))

    fertige = [m for m in matches if is_finished(m)]

    runden = {}
    for match in matches:
        runde = match.get("stage") or "UNKNOWN"
        runden[runde] = runden.get(runde, 0) + 1

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
            "league_key": config["league_key"],
            "competition_type": "cup",
            "season": season,
            "source": "api-football.com",
            "provider_competition_id": config["apisports_id"],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "matches": len(matches),
            "matches_finished": len(fertige),
            "teams": len(teams),
            "rounds": runden,
            # Ehrliche Coverage-Angabe: eine laufende Saison ist per
            # Definition unvollstaendig, und das soll man sehen.
            "coverage": "complete" if matches and len(fertige) == len(matches) else "partial",
        },
        "teams": teams,
        "matches": matches,
    }


def save_cup_season(payload, overwrite_empty=False):
    """
    Schreibt eine Pokalsaison atomar.

    Zwei Sicherungen:

    1. Ein LEERES Ergebnis ueberschreibt niemals eine vorhandene gute
       Datei. Eine kurze Anbieterstoerung oder eine noch nicht gestartete
       Saison darf gesammelte Historie nicht vernichten.
    2. Erst in eine temporaere Datei, dann umbenennen - ein parallel
       lesender Prozess sieht nie einen halben Stand.

    Rueckgabe: (pfad, geschrieben)
    """
    meta = payload.get("meta") or {}
    code = meta.get("code")
    season = meta.get("season")

    if not code or season is None:
        raise ValueError("Payload ohne code/season - Schema unvollstaendig")

    os.makedirs(HISTORICAL_DIR, exist_ok=True)
    path = os.path.join(HISTORICAL_DIR, f"{code}_{season}.json")

    if not payload.get("matches") and not overwrite_empty:
        if os.path.exists(path):
            return path, False

    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    os.replace(temp_path, path)

    return path, True


def load_cup_season(cup_key, season):
    """Laedt eine gespeicherte Pokalsaison. None, wenn nichts vorliegt."""
    path = season_file_path(cup_key, season)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def load_cup_matches(cup_key, season, finished_only=True):
    """
    Spiele einer gespeicherten Pokalsaison.

    finished_only=True ist der Standard: fuer Belastungsrechnungen zaehlt,
    was tatsaechlich gespielt wurde. Angesetzte oder abgesagte Partien
    erzeugen keine Ermuedung.
    """
    payload = load_cup_season(cup_key, season)
    if not payload:
        return []

    matches = payload.get("matches") or []
    if not finished_only:
        return list(matches)

    return [m for m in matches if is_finished(m)]


def refresh_cup(cup_key, season=None, verbose=True):
    """
    Holt eine Pokalsaison und legt sie ab. Idempotent und wiederholbar.

    Rueckgabe: Ergebnisbericht als dict.
    """
    config = cup_config(cup_key)
    season = resolve_season(season)

    try:
        payload = fetch_cup_season(cup_key, season)
    except ApisportsUnavailable as error:
        if verbose:
            print(f"  {config['code']} {season}: nicht abrufbar ({error})")
        return {
            "cup": cup_key, "code": config["code"], "season": season,
            "ok": False, "written": False, "reason": str(error),
        }

    path, written = save_cup_season(payload)
    meta = payload["meta"]

    if verbose:
        hinweis = "" if written else "  (vorhandene Datei behalten)"
        print(f"  {config['code']} {season}: {meta['matches']} Spiele, "
              f"{meta['matches_finished']} beendet, {len(meta['rounds'])} Runden, "
              f"Coverage {meta['coverage']}{hinweis}")

    return {
        "cup": cup_key, "code": config["code"], "season": season,
        "ok": True, "written": written, "path": path,
        "matches": meta["matches"], "matches_finished": meta["matches_finished"],
        "rounds": len(meta["rounds"]), "coverage": meta["coverage"],
    }


def coverage_report():
    """
    Welche Pokalsaisons liegen lokal vor?

    Zeigt fehlende Daten ehrlich an, statt eine vollstaendige Abdeckung
    zu behaupten.
    """
    zeilen = []
    for cup_key, config in DOMESTIC_CUPS.items():
        vorhanden = []
        if os.path.isdir(HISTORICAL_DIR):
            praefix = f"{config['code']}_"
            for name in sorted(os.listdir(HISTORICAL_DIR)):
                if name.startswith(praefix) and name.endswith(".json"):
                    try:
                        vorhanden.append(int(name[len(praefix):-5]))
                    except ValueError:
                        continue

        zeilen.append({
            "cup": cup_key,
            "code": config["code"],
            "name": config["name"],
            "country": config["country"],
            "provider": "api-football.com",
            "provider_competition_id": config["apisports_id"],
            "seasons": sorted(vorhanden),
        })

    return zeilen
