"""
Woher der Sammler weiss, WAS er sammeln soll (V2-C6).

DIE FRAGE
---------
Der Sammler braucht zwei Listen: Ligen fuer die Ausfallabfrage und
Mannschaften fuer die Kaderabfrage. Beide muessen API-Sports-Kennungen
tragen - der Endpunkt /players/squads kennt keine anderen.

Das ist nicht selbstverstaendlich: Die Historie der fuenf Top-Ligen
stammt von football-data.org und traegt DEREN Kennungen. Wer sie
naiv einsetzt, fragt den falschen Verein ab und merkt es nie.

ZWEI QUELLEN, EINE DAVON KOSTENLOS
----------------------------------
    Nationale Ligen (V2-C2B)   data/historical/<CODE>_<saison>.json
        Diese 18 Dateien stammen von API-Sports und fuehren deren
        Team-Kennungen direkt im teams-Block. Kostet KEINE Anfrage.

    Top-5-Ligen und Champions League
        Ueber current_squads.league_team_ids(), also
        /teams?league=X&season=Y mit dem bestehenden Plattencache
        (sieben Tage). Rund sechs Anfragen je Woche - nicht je Lauf.

Ein eigener Auflösungspfad waere hier falsch gewesen: league_team_ids()
existiert seit dem Kadersuchindex, ist gecacht und liefert genau das
Richtige. Ein zweiter haette denselben Cache ein zweites Mal gefuellt.

PRIORITAETEN
------------
Kleiner Wert heisst frueher dran. Bei knappem Kontingent bricht der
Lauf hinten ab, also steht vorn, was am meisten traegt:

     0  Ausfaelle der Top-5 und der Champions League
    10  Ausfaelle der uebrigen nationalen Ligen
    50  Kader der Champions-League-Teilnehmer
    60  Kader der Top-5-Ligen
    90  Kader der uebrigen nationalen Ligen

Die Reihenfolge ist keine Geschmacksfrage. Eine Ligaabfrage liefert die
Ausfaelle einer ganzen Saison in EINER Anfrage (nachgemessen: 2832
Eintraege fuer die Bundesliga 2025), ein Kader kostet eine Anfrage je
Mannschaft. Wer zuerst die Ausfaelle holt, hat nach zwei Dutzend
Anfragen den groessten Teil des Informationswerts gesichert.
"""

import json
import os

from src.data import availability_snapshots as av

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
HISTORICAL_DIR = os.path.join(_PROJECT_ROOT, "data", "historical")

#: Die fuenf Ligen des Produkts.
TOP_LEAGUE_KEYS = ("bl1", "pl", "pd", "sa", "fl1")

#: Der europaeische Wettbewerb, um den die gesamte V2-Arbeit kreist.
CL_KEY = "cl"

#: Prioritaeten - siehe Modulkopf.
PRIORITY_AVAILABILITY_CORE = 0
PRIORITY_AVAILABILITY_NATIONAL = 10
PRIORITY_SQUAD_CL = 50
PRIORITY_SQUAD_TOP5 = 60
PRIORITY_SQUAD_NATIONAL = 90


def _als_int(wert):
    try:
        return int(wert)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Ligen
# ---------------------------------------------------------------------------

def core_leagues(league_ids=None):
    """
    Top-5 und Champions League - die Wettbewerbe des Produkts.

    Rueckgabe: Liste von {"league_id", "label", "priority", "key"}.
    """
    from src.api.apisports_api import LEAGUE_IDS

    league_ids = league_ids or LEAGUE_IDS
    ligen = []
    for key in list(TOP_LEAGUE_KEYS) + [CL_KEY]:
        lid = _als_int(league_ids.get(key))
        if lid is None:
            continue
        ligen.append({"league_id": lid, "key": key, "label": key,
                      "priority": PRIORITY_AVAILABILITY_CORE})
    return ligen


def national_leagues(registry=None):
    """
    Die 18 nationalen Ligen aus V2-C2B.

    Sie stehen im Plan, weil die Champions-League-Teilnehmer aus ihnen
    kommen: Ohne ihre Ausfaelle fehlte fuer zwei Drittel der
    CL-Mannschaften jede Verfuegbarkeitsangabe.
    """
    from src.data.national_league_loader import NATIONAL_LEAGUES

    registry = registry or NATIONAL_LEAGUES
    ligen = []
    for key in sorted(registry):
        cfg = registry[key] or {}
        lid = _als_int(cfg.get("apisports_id"))
        if lid is None:
            continue
        ligen.append({"league_id": lid, "key": key,
                      "label": cfg.get("name") or key,
                      "priority": PRIORITY_AVAILABILITY_NATIONAL})
    return ligen


# ---------------------------------------------------------------------------
# Mannschaften
# ---------------------------------------------------------------------------

def teams_from_local_league_files(season, directory=None, registry=None):
    """
    Mannschaften aus den lokalen V2-C2B-Ligadateien - ohne jede Anfrage.

    Diese Dateien tragen API-Sports-Kennungen im teams-Block. Genau
    deshalb sind sie hier brauchbar und die football-data-Historie der
    Top-5-Ligen nicht.

    Faellt eine Saison, faellt auf die naechstaeltere vorhandene zurueck:
    Am 1. Juli ist die neue Saison beim Anbieter oft noch leer, die
    Mannschaften der Vorsaison sind aber weiterhin die richtige
    Naeherung fuer "wen sollten wir beobachten".
    """
    from src.data.national_league_loader import NATIONAL_LEAGUES

    directory = directory or HISTORICAL_DIR
    registry = registry or NATIONAL_LEAGUES

    mannschaften = {}
    for key in sorted(registry):
        cfg = registry[key] or {}
        code = cfg.get("code")
        if not code:
            continue

        for kandidat in (season, season - 1, season - 2):
            pfad = os.path.join(directory, f"{code}_{kandidat}.json")
            if not os.path.exists(pfad):
                continue
            try:
                with open(pfad, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, ValueError):
                continue

            for roh_id, info in (payload.get("teams") or {}).items():
                tid = _als_int(roh_id)
                if tid is None:
                    continue
                mannschaften.setdefault(tid, {
                    "team_id": tid,
                    "label": (info or {}).get("name") or f"team {tid}",
                    "priority": PRIORITY_SQUAD_NATIONAL,
                    "source": f"{code}_{kandidat}",
                })
            break

    return list(mannschaften.values())


def teams_from_api(league_keys, season, resolver=None):
    """
    Mannschaften einer Liga ueber den bestehenden, gecachten Weg.

    resolver ist einspeisbar, damit die Tests ohne Netz auskommen -
    der Standard ist current_squads.league_team_ids mit seinem
    Siebentagecache.
    """
    if resolver is None:
        from src.data.current_squads import league_team_ids as resolver

    prioritaet = {CL_KEY: PRIORITY_SQUAD_CL}
    mannschaften = {}
    for key in league_keys:
        try:
            gefunden = resolver(key, season) or {}
        except Exception:
            # Ein Anbieterausfall bei der Auflösung darf den Lauf nicht
            # beenden - die uebrigen Ligen und alle lokalen
            # Mannschaften bleiben sammelbar.
            continue
        for tid, name in gefunden.items():
            tid = _als_int(tid)
            if tid is None:
                continue
            vorrang = prioritaet.get(key, PRIORITY_SQUAD_TOP5)
            vorhanden = mannschaften.get(tid)
            if vorhanden is None or vorrang < vorhanden["priority"]:
                mannschaften[tid] = {
                    "team_id": tid,
                    "label": name or f"team {tid}",
                    "priority": vorrang,
                    "source": key,
                }
    return list(mannschaften.values())


# ---------------------------------------------------------------------------
# Der vollstaendige Plan
# ---------------------------------------------------------------------------

def discover(season, kinds=av.SNAPSHOT_KINDS, include_national=True,
             team_resolver=None, directory=None, league_ids=None,
             registry=None, teams=None, leagues=None):
    """
    Ligen und Mannschaften fuer einen Lauf.

    Rueckgabe: (teams, leagues, diagnose).

    teams/leagues koennen uebergeben werden - dann wird nichts
    ermittelt. Das ist der Weg fuer den gezielten Lauf ("nur diese
    Mannschaft") und fuer Tests.

    DUBLETTEN
    Eine Mannschaft, die in der Bundesliga UND in der Champions League
    spielt, steht in beiden Quellen. Hier gewinnt die kleinere
    Prioritaetszahl, also der wichtigere Kontext; die endgueltige
    Entdopplung ueber die tatsaechliche Anfrage macht
    snapshot_collector.plan_scopes.
    """
    diagnose = {"season": season, "sources": []}

    if leagues is None:
        leagues = core_leagues(league_ids=league_ids)
        diagnose["sources"].append(
            {"what": "leagues", "source": "LEAGUE_IDS", "count": len(leagues)})
        if include_national:
            national = national_leagues(registry=registry)
            leagues = leagues + national
            diagnose["sources"].append(
                {"what": "leagues", "source": "national_league_loader",
                 "count": len(national)})

    if teams is None:
        teams = {}
        if av.KIND_SQUAD in kinds:
            aus_api = teams_from_api(
                [CL_KEY] + list(TOP_LEAGUE_KEYS), season,
                resolver=team_resolver)
            diagnose["sources"].append(
                {"what": "teams", "source": "apisports /teams (7d cache)",
                 "count": len(aus_api)})
            for eintrag in aus_api:
                teams[eintrag["team_id"]] = eintrag

            if include_national:
                lokal = teams_from_local_league_files(
                    season, directory=directory, registry=registry)
                diagnose["sources"].append(
                    {"what": "teams", "source": "local V2-C2B league files",
                     "count": len(lokal), "requests": 0})
                for eintrag in lokal:
                    vorhanden = teams.get(eintrag["team_id"])
                    if vorhanden is None \
                            or eintrag["priority"] < vorhanden["priority"]:
                        teams[eintrag["team_id"]] = eintrag
        teams = list(teams.values())

    diagnose["teams"] = len(teams)
    diagnose["leagues"] = len(leagues)
    return teams, leagues, diagnose
