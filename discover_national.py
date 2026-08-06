#!/usr/bin/env python3
"""
discover_national.py - EIGENSTAENDIGE Verifikation der Nationalmannschaftsdaten.

Dieses Skript ist bewusst KOMPLETT unabhaengig vom Rest von FootSim:
  - Es importiert KEIN Projektmodul (kein player_compare_loader, kein
    apisports_api, nichts aus src/).
  - Es aendert NICHTS an der Anwendung.
  - Es schreibt nur eine einzige neue Datei: data/discovery/national_coverage.json
    (plus Rohantworten unter data/discovery/_raw/).

Es liest ausschliesslich den API-Key aus der .env und fragt die API direkt ab.

Zweck
-----
Feststellen, WAS dein API-Football-Tarif fuer A-Nationalmannschaften wirklich
liefert - als verifizierte Grundlage fuer den spaeteren Import. Konkret:
  - Welche Nationalmannschaftswettbewerbe existieren?
  - Welche League-ID hat jeder?
  - In welchen API-Seasons sind sie verfuegbar?
  - Welche coverage.players / statistics_players liegt je Season vor?
  - Welche eignen sich damit fuer den Scope "Nur Nationalmannschaft"?
  - Wie ordnen sich die Turniere den FootSim-Vereinssaisons zu?

Sparsam
-------
Ein Request pro gepruefter Season ueber /leagues?country=World.
Standard sind vier Seasons -> vier Requests. Rohantworten werden lokal unter
data/discovery/_raw/ zwischengespeichert; ein erneuter Lauf ohne --refresh
macht keine weiteren Requests.

Aufruf
------
    python discover_national.py                      # Seasons 2023-2026
    python discover_national.py --seasons 2024 2025
    python discover_national.py --refresh            # Cache ignorieren
"""

import argparse
import json
import os
import sys
import time

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # dotenv ist optional - der Key kann auch als Umgebungsvariable gesetzt sein.
    pass


# --- Konfiguration ---------------------------------------------------------

BASE_URL = "https://v3.football.api-sports.io"
API_KEY = os.getenv("APISPORTS_KEY") or os.getenv("API_FOOTBALL_KEY")

# FootSim-Vereinssaison -> API-Season-Zahl.
# API-Football benennt eine europaeische Saison 2025/26 als season=2025.
DEFAULT_SEASONS = (2023, 2024, 2025, 2026)

OUTPUT_DIR = os.path.join("data", "discovery")
RAW_DIR = os.path.join(OUTPUT_DIR, "_raw")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "national_coverage.json")

# Sekunden Pause zwischen echten Requests (sicher unter jedem Limit).
THROTTLE_SECONDS = 0.5


# --- Klassifikation (eigenstaendig, keine Projektabhaengigkeit) ------------

# Namensmarker, die einen Wettbewerb als VEREINSwettbewerb ausweisen, auch
# wenn der Name "world cup" enthaelt (FIFA Club World Cup!). Werden VOR den
# Nationalmannschaftsmarkern geprueft.
CLUB_MARKERS = (
    "club world cup",
    "club world",
    "friendlies clubs",
    "club friendlies",
)

# Namensmarker echter A-Nationalmannschaftswettbewerbe.
NATIONAL_MARKERS = (
    "world cup",            # inkl. "World Cup - Qualification ..."
    "euro championship",
    "european championship",
    "nations league",
    "friendlies",           # internationale Freundschaftsspiele
    "copa america",
    "africa cup",
    "afcon",
    "asian cup",
    "gold cup",
    "concacaf",
    "olympic",
    "confederations cup",
)

# Marker, die eine JUGEND-/Frauen-Auswahl kennzeichnen. Der Scope "Nur
# Nationalmannschaft" meint A-Nationalmannschaften; diese werden markiert,
# damit du sie in der Auswertung siehst und der spaetere Import sie bewusst
# ein- oder ausschliessen kann. Sie werden NICHT hart entfernt.
YOUTH_WOMEN_MARKERS = (
    "u17", "u-17", "u18", "u-18", "u19", "u-19", "u20", "u-20",
    "u21", "u-21", "u23", "u-23", "women", "féminin", "feminin",
)


def classify(name):
    """
    Grobklassifikation eines Wettbewerbsnamens.

    Rueckgabe: "club" | "national" | "other"
    """
    n = (name or "").lower()
    if any(m in n for m in CLUB_MARKERS):
        return "club"
    if any(m in n for m in NATIONAL_MARKERS):
        return "national"
    return "other"


def is_youth_or_women(name):
    n = (name or "").lower()
    return any(m in n for m in YOUTH_WOMEN_MARKERS)


# --- API-Zugriff -----------------------------------------------------------

def _raw_path(season):
    return os.path.join(RAW_DIR, f"world_leagues_{season}.json")


def fetch_world_leagues(season, refresh=False):
    """
    /leagues?country=World&season=<season> - alle internationalen Wettbewerbe.

    Rohantwort wird lokal zwischengespeichert. Rueckgabe: Liste der
    /leagues-Eintraege. Wirft RuntimeError bei API-/Netzproblemen.
    """
    cached = _raw_path(season)
    if not refresh and os.path.exists(cached):
        with open(cached, encoding="utf-8") as f:
            return json.load(f)

    if not API_KEY:
        raise RuntimeError(
            "Kein API-Key gefunden. Erwarte APISPORTS_KEY in der .env."
        )

    url = f"{BASE_URL}/leagues"
    headers = {
        "x-rapidapi-key": API_KEY,
        "x-rapidapi-host": "v3.football.api-sports.io",
    }
    params = {"country": "World", "season": season}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=20)
    except requests.RequestException as e:
        raise RuntimeError(f"Netzwerkfehler bei Season {season}: {e}")

    if resp.status_code == 429:
        raise RuntimeError(f"Rate-Limit (HTTP 429) bei Season {season}")
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} bei Season {season}")

    data = resp.json()
    errors = data.get("errors")
    if errors:
        raise RuntimeError(f"API-Fehler bei Season {season}: {errors}")

    response = data.get("response", [])

    os.makedirs(RAW_DIR, exist_ok=True)
    with open(cached, "w", encoding="utf-8") as f:
        json.dump(response, f, ensure_ascii=False, indent=2)

    time.sleep(THROTTLE_SECONDS)
    return response


# --- Auswertung ------------------------------------------------------------

def coverage_for_season(entry, season):
    for s in entry.get("seasons") or []:
        if s.get("year") == season:
            return s.get("coverage") or {}
    return None


def analyse(seasons, refresh=False):
    competitions = {}   # league_id -> record
    errors = []

    for season in seasons:
        try:
            world = fetch_world_leagues(season, refresh=refresh)
        except RuntimeError as e:
            errors.append(str(e))
            print(f"  ! {e}")
            if "Rate-Limit" in str(e) or "429" in str(e):
                break
            continue

        n_nat = 0
        for entry in world:
            league = entry.get("league") or {}
            country = entry.get("country") or {}
            name = league.get("name")
            league_id = league.get("id")
            if league_id is None:
                continue

            if classify(name) != "national":
                continue

            coverage = coverage_for_season(entry, season)
            if coverage is None:
                continue

            players_flag = bool(coverage.get("players"))
            fixtures = coverage.get("fixtures") or {}
            stats_players_flag = bool(fixtures.get("statistics_players"))

            rec = competitions.setdefault(league_id, {
                "league_id": league_id,
                "name": name,
                "type_reported": league.get("type"),   # oft None beim Pro-Plan
                "country": country.get("name"),
                "is_youth_or_women": is_youth_or_women(name),
                "seasons": {},
            })
            rec["seasons"][str(season)] = {
                "players": players_flag,
                "statistics_players": stats_players_flag,
                "usable": players_flag and stats_players_flag,
            }
            n_nat += 1

        print(f"  Season {season}: {n_nat} A-/Nationalmannschaftswettbewerbe erfasst")

    return {
        "generated_for_seasons": list(seasons),
        "footsim_season_mapping": {
            "2023/24": 2023, "2024/25": 2024,
            "2025/26": 2025, "2026/27": 2026,
        },
        "competitions": competitions,
        "errors": errors,
    }


def print_report(result):
    comps = result["competitions"]
    seasons = result["generated_for_seasons"]

    print()
    print("=" * 80)
    print("  Nationalmannschaftswettbewerbe - Coverage nach Season")
    print("=" * 80)

    if not comps:
        print("  Keine Nationalmannschaftswettbewerbe gefunden.")
        for e in result["errors"]:
            print("   !", e)
        return

    head = f"  {'Wettbewerb':34} {'ID':>5} {'Jgd/Fr':>7}  " + " ".join(f"{s:>5}" for s in seasons)
    print(head)
    print("  " + "-" * (len(head) - 2))

    usable = []
    for league_id, rec in sorted(comps.items(), key=lambda kv: (kv[1]["name"] or "")):
        cells = []
        for s in seasons:
            info = rec["seasons"].get(str(s))
            if not info:
                cells.append("  -  ")
            elif info["usable"]:
                cells.append("  J  ")
            elif info["players"]:
                cells.append("  p  ")
            else:
                cells.append("  .  ")
        yf = "ja" if rec["is_youth_or_women"] else ""
        row = f"  {(rec['name'] or '')[:34]:34} {league_id:>5} {yf:>7}  " + " ".join(cells)
        print(row)
        if any(rec["seasons"].get(str(s), {}).get("usable") for s in seasons):
            usable.append(rec)

    print("  " + "-" * (len(head) - 2))
    print("  Legende: J = Spielerstatistiken verfuegbar | p = nur Spielerliste |")
    print("           . = keine | - = Season nicht vorhanden")
    print("           Jgd/Fr = Jugend-/Frauenauswahl (fuer A-Team-Scope evtl. ausschliessen)")
    print()
    print(f"  {len(usable)} Wettbewerbe mit echten Spielerstatistiken (mind. eine Season):")
    for rec in usable:
        us = [s for s in seasons if rec["seasons"].get(str(s), {}).get("usable")]
        tag = " [Jugend/Frauen]" if rec["is_youth_or_women"] else ""
        print(f"    - {rec['name']} (id {rec['league_id']}): Seasons {', '.join(map(str, us))}{tag}")

    if result["errors"]:
        print()
        print("  Hinweise/Fehler:")
        for e in result["errors"]:
            print("   !", e)


def main():
    parser = argparse.ArgumentParser(
        description="Eigenstaendige Verifikation der Nationalmannschaftsdaten "
                    "von API-Football (aendert nichts an FootSim).",
    )
    parser.add_argument("--seasons", type=int, nargs="+", default=list(DEFAULT_SEASONS))
    parser.add_argument("--refresh", action="store_true",
                        help="Cache ignorieren und frisch von der API laden")
    args = parser.parse_args()

    if not API_KEY:
        print("  FEHLER: Kein API-Key gefunden.")
        print("  Erwartet wird APISPORTS_KEY in der .env des Projekts.")
        return 1

    print()
    print(f"  Discovery Nationalmannschaft")
    print(f"  Seasons: {', '.join(map(str, args.seasons))}")
    print(f"  Quelle:  {BASE_URL}/leagues?country=World  (ein Request je Season)")
    print()

    result = analyse(args.seasons, refresh=args.refresh)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print_report(result)

    print()
    print(f"  Auswertung gespeichert: {OUTPUT_PATH}")
    print(f"  Bitte den GESAMTEN Konsoleninhalt UND diese JSON-Datei zurueckschicken.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
