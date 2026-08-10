"""
Laedt vollstaendige, abgeschlossene Saisons von football-data.org.

Hintergrund:
Frueher stuetzte sich die Teamstaerke auf die letzten fuenf Spiele eines
Teams. Das ist zu wenig: Fuenf Spiele sind statistisches Rauschen, und zu
Saisonbeginn existieren sie gar nicht.

football-data.org liefert im vorhandenen Tarif komplette Saisons:

    BL1 306 Spiele / 18 Teams      PL  380 / 20
    PD  380 / 20                   SA  380 / 20
    FL1 305 / 18

Zurueck reichen die Daten bis zwei abgeschlossene Saisons (geprueft:
2024/25 und 2023/24 verfuegbar, 2022/23 nicht mehr im Tarif enthalten).

Dieses Modul holt diese Saisons EINMAL, normalisiert sie auf ein schlankes
Format und legt sie unter data/historical/ ab. Danach laeuft alles offline
aus der Datei; die API wird nicht erneut belastet.

Speicherformat pro Saison (data/historical/BL1_2024.json):

    {
      "meta": {"api_code": "BL1", "season": 2024, "matches": 306,
               "teams": 18, "fetched_at": "..."},
      "teams": {"5": {"id": 5, "name": "FC Bayern München"}, ...},
      "matches": [
        {"matchday": 1, "date": "2024-08-23",
         "home_id": 5, "away_id": 721, "home_goals": 3, "away_goals": 2},
        ...
      ]
    }

Die Match-Eintraege enthalten bewusst nur IDs, keine Namen: Namen stehen
einmal zentral in "teams". Das haelt die Datei klein und verhindert, dass
derselbe Verein unter zwei Schreibweisen auftaucht.
"""

import json
import os
from datetime import datetime, timezone

from src.api.league_api import _get_json


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HISTORICAL_DIR = os.path.join(_PROJECT_ROOT, "data", "historical")


# Die Ligen, fuer die historische Daten vorgehalten werden.
# Muss zu LEAGUE_CONFIG in app.py passen.
LEAGUE_CODES = {
    "bl1": "BL1",
    "pl": "PL",
    "pd": "PD",
    "sa": "SA",
    "fl1": "FL1",
}

# Wettbewerbe mit K.-o.-Struktur werden getrennt gefuehrt. Sie gehoeren
# bewusst NICHT in LEAGUE_CODES: Diese Liste steuert die Ligasimulation
# und die Aufsteiger-Erkennung, beides ergibt fuer die CL keinen Sinn.
CUP_CODES = {
    "cl": "CL",
}

# In der CL kollidieren Spieltagsnummern ueber Stages hinweg (matchday=1
# existiert in der Ligaphase UND im Achtelfinale). Deshalb wird fuer
# diese Wettbewerbe die Stage je Spiel mitgespeichert - ohne sie sind die
# Daten fuer Modellierung und Backtesting nicht sauber trennbar.
STAGED_COMPETITIONS = set(CUP_CODES.values())

# Abgeschlossene Saisons, die im aktuellen football-data.org-Tarif
# erreichbar sind. Neueste zuerst.
#
# WICHTIG: 2025 (Saison 2025/26) ist die UNMITTELBARE Vorsaison der
# laufenden Saison 2026/27 und seit deren Abschluss (Mai 2026) im Tarif
# verfuegbar. Ohne sie schlagen zwei Dinge fehl:
#   1. Die Aufsteiger-Erkennung (wer war letzte Saison dabei?) hat keine
#      Grundlage - Teams, die 2025/26 aufstiegen (z. B. HSV), wuerden
#      faelschlich weiterhin als Aufsteiger gefuehrt.
#   2. Die Staerken beruhen auf zwei Jahre alten Daten, obwohl die
#      juengste komplette Saison die aussagekraeftigste ist (Barcelona
#      und PSG etwa gewannen 2025/26 die Meisterschaft).
# Fehlende Dateien werden beim Laden stillschweigend uebersprungen -
# einmal `py refresh_historical.py` ausfuehren, dann liegt 2025 lokal vor.
AVAILABLE_HISTORICAL_SEASONS = [2025, 2024, 2023]


def _ensure_dir():
    os.makedirs(HISTORICAL_DIR, exist_ok=True)


def season_file_path(api_code, season):
    return os.path.join(HISTORICAL_DIR, f"{api_code}_{season}.json")


def _normalize_matches(raw_matches, with_stages=False):
    """
    Bringt die API-Rohdaten auf das schlanke Speicherformat.

    Uebersprungen werden Spiele ohne Endergebnis (abgesagt, verschoben)
    und Spiele ohne Team-ID. Beides waere fuer die Statistik unbrauchbar.

    with_stages=True ergaenzt je Spiel match_id, stage und status. Das
    ist fuer Wettbewerbe mit K.-o.-Runden noetig (siehe
    STAGED_COMPETITIONS) und bleibt fuer Ligen bewusst abgeschaltet,
    damit deren bereits gespeicherte Dateien formatgleich bleiben.

    Fehlende Felder werden NICHT geraten: Liefert die API keine Stage,
    steht dort None.
    """
    teams = {}
    matches = []

    for raw in raw_matches:
        home = raw.get("homeTeam") or {}
        away = raw.get("awayTeam") or {}
        home_id = home.get("id")
        away_id = away.get("id")

        if home_id is None or away_id is None:
            continue

        score = (raw.get("score") or {}).get("fullTime") or {}
        home_goals = score.get("home")
        away_goals = score.get("away")

        if home_goals is None or away_goals is None:
            continue

        # Teamnamen zentral sammeln. Die Langform ist eindeutiger als
        # shortName und wird deshalb bevorzugt.
        for team_id, team in ((home_id, home), (away_id, away)):
            if team_id not in teams:
                teams[team_id] = {
                    "id": team_id,
                    "name": team.get("name") or team.get("shortName") or str(team_id),
                    "short_name": team.get("shortName") or team.get("name"),
                    "tla": team.get("tla"),
                    "crest": team.get("crest"),
                }

        entry = {
            "matchday": raw.get("matchday"),
            "date": (raw.get("utcDate") or "")[:10],
            "home_id": home_id,
            "away_id": away_id,
            "home_goals": int(home_goals),
            "away_goals": int(away_goals),
        }

        if with_stages:
            entry["match_id"] = raw.get("id")
            entry["stage"] = raw.get("stage")
            entry["status"] = raw.get("status")

        matches.append(entry)

    # Chronologisch sortieren: wichtig fuer Form-Berechnungen und spaeter Elo.
    matches.sort(key=lambda m: (m["date"], m["matchday"] or 0))

    return teams, matches


def fetch_season(api_code, season):
    """
    Holt eine komplette abgeschlossene Saison von der API.

    Ein einziger Request pro Saison und Wettbewerb. Wirft die Exception
    der API weiter, damit der Aufrufer entscheiden kann, wie er damit
    umgeht.

    Wettbewerbe aus STAGED_COMPETITIONS (aktuell die CL) bekommen
    zusaetzlich Stage, Match-ID und Status je Spiel sowie eine
    Stage-Uebersicht in den Metadaten. Ligen bleiben unveraendert.
    """
    with_stages = api_code in STAGED_COMPETITIONS

    data = _get_json(
        f"/competitions/{api_code}/matches",
        params={"season": season, "status": "FINISHED"},
    )
    raw_matches = data.get("matches", [])
    teams, matches = _normalize_matches(raw_matches, with_stages=with_stages)

    meta = {
        "api_code": api_code,
        "season": season,
        "matches": len(matches),
        "teams": len(teams),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "football-data.org",
    }

    if with_stages:
        # Welche Stages tatsaechlich enthalten sind, wird aus den Daten
        # abgeleitet und nicht vorausgesetzt. Das UEFA-Format hat sich
        # 2024/25 geaendert (Gruppenphase -> Ligaphase); die Datei soll
        # beides unveraendert abbilden koennen.
        stage_counts = {}
        for match in matches:
            stage = match.get("stage")
            if stage:
                stage_counts[stage] = stage_counts.get(stage, 0) + 1
        meta["competition_type"] = "cup"
        meta["stages"] = dict(sorted(stage_counts.items()))
    else:
        meta["competition_type"] = "league"

    return {
        "meta": meta,
        # JSON-Keys sind immer Strings. Beim Lesen wieder zu int wandeln.
        "teams": {str(tid): t for tid, t in teams.items()},
        "matches": matches,
    }


def save_season(api_code, season, payload):
    _ensure_dir()
    path = season_file_path(api_code, season)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    return path


def load_season(api_code, season):
    """
    Liest eine gespeicherte Saison von der Platte.

    Rueckgabe: Dict mit meta/teams/matches, oder None wenn nicht vorhanden.
    Die Team-IDs werden dabei zurueck zu int gewandelt, damit sie zu den
    IDs aus der laufenden API-Abfrage passen.
    """
    path = season_file_path(api_code, season)
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return None

    if not isinstance(payload, dict) or "matches" not in payload:
        return None

    payload["teams"] = {
        int(tid): team for tid, team in (payload.get("teams") or {}).items()
    }
    return payload


def load_available_seasons(api_code, seasons=None):
    """
    Laedt alle lokal vorhandenen Saisons einer Liga.

    Rueckgabe: Liste von (season, payload), neueste Saison zuerst.
    Fehlende Saisons werden stillschweigend uebersprungen; der Aufrufer
    sieht an der Laenge der Liste, wie viel Historie tatsaechlich da ist.
    """
    seasons = seasons or AVAILABLE_HISTORICAL_SEASONS
    result = []

    for season in sorted(seasons, reverse=True):
        payload = load_season(api_code, season)
        if payload:
            result.append((season, payload))

    return result


def load_cl_season(season):
    """
    Liest eine gespeicherte Champions-League-Saison.

    Duenner benannter Wrapper um load_season, damit Aufrufer nicht den
    API-Code kennen muessen.
    """
    return load_season(CUP_CODES["cl"], season)


def load_cl_matches(season, stage=None):
    """
    Liefert die gespeicherten CL-Spiele einer Saison, optional nach Stage
    gefiltert.

    stage="LEAGUE_STAGE" liefert nur die Ligaphase - genau die Trennung,
    die die football-data-API ohne expliziten Filter nicht hergibt, weil
    Spieltagsnummern ueber Stages hinweg kollidieren.

    Rueckgabe: Liste von Matches (leer, wenn nichts lokal vorliegt).
    """
    payload = load_cl_season(season)
    if not payload:
        return []

    matches = payload.get("matches") or []
    if stage is None:
        return list(matches)

    return [m for m in matches if m.get("stage") == stage]


def available_cl_seasons():
    """Welche CL-Saisons lokal vorliegen, neueste zuerst."""
    if not os.path.isdir(HISTORICAL_DIR):
        return []

    api_code = CUP_CODES["cl"]
    seasons = []
    for filename in os.listdir(HISTORICAL_DIR):
        if not filename.startswith(f"{api_code}_") or not filename.endswith(".json"):
            continue
        stem = filename[len(api_code) + 1:-len(".json")]
        try:
            seasons.append(int(stem))
        except ValueError:
            continue

    return sorted(seasons, reverse=True)


def refresh_league(api_code, seasons=None, force=False, verbose=True):
    """
    Holt fehlende Saisons einer Liga und speichert sie.

    force=True laedt auch dann neu, wenn die Datei bereits existiert.
    Rueckgabe: Liste von Ergebnis-Dicts je Saison, fuer den Report.
    """
    seasons = seasons or AVAILABLE_HISTORICAL_SEASONS
    results = []

    for season in seasons:
        path = season_file_path(api_code, season)

        if os.path.exists(path) and not force:
            existing = load_season(api_code, season)
            meta = (existing or {}).get("meta", {})
            results.append({
                "api_code": api_code, "season": season, "status": "vorhanden",
                "matches": meta.get("matches", 0), "teams": meta.get("teams", 0),
            })
            if verbose:
                print(f"  {api_code} {season}: bereits vorhanden "
                      f"({meta.get('matches', 0)} Spiele)")
            continue

        try:
            payload = fetch_season(api_code, season)
            save_season(api_code, season, payload)
            meta = payload["meta"]
            results.append({
                "api_code": api_code, "season": season, "status": "geladen",
                "matches": meta["matches"], "teams": meta["teams"],
            })
            if verbose:
                print(f"  {api_code} {season}: {meta['matches']} Spiele, "
                      f"{meta['teams']} Teams geladen")
        except Exception as error:
            results.append({
                "api_code": api_code, "season": season, "status": "fehler",
                "error": str(error)[:120], "matches": 0, "teams": 0,
            })
            if verbose:
                print(f"  {api_code} {season}: FEHLER {str(error)[:80]}")

    return results


def refresh_all(seasons=None, force=False, verbose=True):
    """
    Holt die Historie fuer alle konfigurierten Ligen.

    Request-Bedarf: 5 Ligen x 2 Saisons = 10 Requests, einmalig.
    football-data.org erlaubt 10 Requests pro Minute, deshalb wird
    zwischen den Aufrufen kurz gewartet.
    """
    import time

    seasons = seasons or AVAILABLE_HISTORICAL_SEASONS
    all_results = []

    if verbose:
        print(f"Historie wird geladen: {len(LEAGUE_CODES)} Ligen x "
              f"{len(seasons)} Saisons")

    first = True
    for api_code in LEAGUE_CODES.values():
        if verbose:
            print(f"\n{api_code}:")
        for season in seasons:
            # Ratenlimit einhalten: 10 Requests/Minute -> ~7 s Abstand.
            if not first:
                time.sleep(7)
            first = False
            all_results.extend(
                refresh_league(api_code, seasons=[season], force=force, verbose=verbose)
            )

    return all_results


def refresh_cl(seasons=None, force=False, verbose=True):
    """
    Holt die Champions-League-Historie und legt sie unter
    data/historical/CL_<season>.json ab.

    Nutzt bewusst dieselbe Mechanik wie die Ligen (refresh_league), damit
    es keine zweite, konkurrierende Ladelogik gibt. Der einzige
    Unterschied steckt in fetch_season, das fuer die CL zusaetzlich
    Stage, Match-ID und Status mitschreibt.
    """
    import time

    seasons = seasons or AVAILABLE_HISTORICAL_SEASONS
    api_code = CUP_CODES["cl"]
    results = []

    if verbose:
        print(f"\n{api_code}:")

    for index, season in enumerate(seasons):
        # Ratenlimit von football-data.org einhalten (10 Requests/Minute).
        if index > 0:
            time.sleep(7)
        results.extend(
            refresh_league(api_code, seasons=[season], force=force, verbose=verbose)
        )

    return results


def cl_coverage_report():
    """
    Zeigt, welche CL-Saisons lokal vorliegen, inklusive Stage-Verteilung.

    Die Stages stehen bewusst mit im Report: Ob eine Saison im alten
    Gruppenformat oder im ab 2024/25 gueltigen Ligaphasen-Format
    vorliegt, entscheidet darueber, wofuer sie ueberhaupt verwendbar ist.
    """
    api_code = CUP_CODES["cl"]
    report = []

    for season in AVAILABLE_HISTORICAL_SEASONS:
        payload = load_season(api_code, season)
        if payload:
            meta = payload.get("meta", {})
            report.append({
                "competition": "cl", "api_code": api_code, "season": season,
                "available": True,
                "matches": meta.get("matches", 0),
                "teams": meta.get("teams", 0),
                "stages": meta.get("stages", {}),
                "fetched_at": meta.get("fetched_at"),
            })
        else:
            report.append({
                "competition": "cl", "api_code": api_code, "season": season,
                "available": False, "matches": 0, "teams": 0,
                "stages": {}, "fetched_at": None,
            })

    return report


def coverage_report():
    """
    Zeigt, welche historischen Daten lokal vorliegen.

    Wird vom Diagnose-Skript benutzt und beantwortet die Frage:
    "Rechnet die Simulation mit echten Daten oder mit Fallbacks?"
    """
    report = []

    for key, api_code in LEAGUE_CODES.items():
        for season in AVAILABLE_HISTORICAL_SEASONS:
            payload = load_season(api_code, season)
            if payload:
                meta = payload.get("meta", {})
                report.append({
                    "league": key, "api_code": api_code, "season": season,
                    "available": True,
                    "matches": meta.get("matches", 0),
                    "teams": meta.get("teams", 0),
                    "fetched_at": meta.get("fetched_at"),
                })
            else:
                report.append({
                    "league": key, "api_code": api_code, "season": season,
                    "available": False, "matches": 0, "teams": 0,
                    "fetched_at": None,
                })

    return report
