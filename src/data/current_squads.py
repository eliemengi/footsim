"""
Verifizierte aktuelle Vereinszugehoerigkeit eines Spielers.

WOFUER
------
Zu Saisonbeginn liefert API-Football fuer viele Spieler noch KEINEN
Statistikdatensatz. Michael Olise und Lamine Yamal waren in 2026/27
deshalb schlicht nicht auffindbar, obwohl sie weiterhin aktiv sind: die
Suche kennt nur den Statistikpool, und wer dort fehlt, existiert fuer
FootSim nicht.

Die Loesung darf NICHT sein, den Vorjahresspieler einfach als aktuellen
auszugeben. Ein Spieler kann den Verein gewechselt haben, die Liga
verlassen haben oder die Karriere beendet haben. Ohne Beleg waere die
Anzeige geraten.

WIE VERIFIZIERT WIRD
--------------------
/players/squads?player=<id> liefert die Kaderlisten, in denen ein Spieler
steht - unabhaengig davon, ob er in dieser Saison schon gespielt hat.
Verifiziert am 2026-08-22:

    Olise (19617) -> Crystal Palace U23, France, France U23, Bayern (157)
    Yamal (386828) -> Spain, Barcelona (529)

Der Endpunkt liefert also auch Jugend- und Nationalmannschaften. Als
Beleg zaehlt deshalb ausschliesslich ein Team, das in dieser Saison
tatsaechlich in einer der fuenf FootSim-Ligen spielt. Alles andere wird
verworfen - lieber kein Treffer als ein falscher Verein.

KOSTEN
------
Ein Request je Liga fuer die Teamliste (fuenf insgesamt, sehr lange
gecacht) und ein Request je geprueftem Spieler. Die Pruefung laeuft nur
dann, wenn Statistikpool UND Live-Suche nichts gefunden haben - im
Regelbetrieb also gar nicht.
"""

from src.api.apisports_api import (
    _get,
    LEAGUE_IDS,
    ApisportsUnavailable,
    resolve_season,
)
from src.utils.disk_cache import disk_cached_call


#: Ligen, in denen ein Verein liegen muss, damit eine Zugehoerigkeit als
#: belegt gilt. Dieselben fuenf wie im Perzentil-Referenzpool.
VERIFIED_LEAGUES = ("bl1", "pl", "pd", "sa", "fl1")

#: Teamlisten aendern sich innerhalb einer Saison praktisch nicht.
TTL_LEAGUE_TEAMS = 60 * 60 * 24 * 7      # 7 Tage

#: Kaderzugehoerigkeit aendert sich nur im Transferfenster.
TTL_PLAYER_SQUADS = 60 * 60 * 24         # 24 Stunden


def league_team_ids(league_code, season=None):
    """
    Team-IDs einer Liga in dieser Saison.

    Rueckgabe: dict {team_id: team_name}. Leer, wenn die Liga fuer diese
    Saison (noch) nicht gefuehrt wird - das ist kein Fehler.
    """
    season = resolve_season(season)
    league_id = LEAGUE_IDS.get(league_code)
    if not league_id:
        return {}

    def loader():
        raw = _get("teams", params={"league": league_id, "season": season})
        teams = {}
        for eintrag in (raw or []):
            team = eintrag.get("team") or {}
            tid = team.get("id")
            if tid is not None:
                teams[int(tid)] = team.get("name")
        return teams

    try:
        gecacht = disk_cached_call(
            key=f"apisports:league_teams:{league_code}:{season}",
            ttl_seconds=TTL_LEAGUE_TEAMS,
            loader=loader,
            source="api-football.com/teams",
        )
    except ApisportsUnavailable:
        return {}

    # Schluessel koennen aus dem JSON-Cache als Text zurueckkommen.
    return {int(k): v for k, v in (gecacht or {}).items()}


def all_verified_teams(season=None):
    """
    Alle Teams der fuenf FootSim-Ligen dieser Saison.

    Rueckgabe: dict {team_id: {"name":, "league_key":}}
    """
    season = resolve_season(season)
    alle = {}
    for league_code in VERIFIED_LEAGUES:
        for tid, name in league_team_ids(league_code, season).items():
            alle.setdefault(tid, {"name": name, "league_key": league_code})
    return alle


def player_squad_team_ids(player_id):
    """
    In welchen Kadern steht dieser Spieler?

    Rueckgabe: Liste von (team_id, team_name). Leer bei Fehler oder
    unbekanntem Spieler - ein Ausfall darf nie zu einer Behauptung werden.
    """
    def loader():
        raw = _get("players/squads", params={"player": int(player_id)})
        eintraege = []
        for eintrag in (raw or []):
            team = eintrag.get("team") or {}
            tid = team.get("id")
            if tid is not None:
                eintraege.append([int(tid), team.get("name")])
        return eintraege

    try:
        gecacht = disk_cached_call(
            key=f"apisports:player_squads:{player_id}",
            ttl_seconds=TTL_PLAYER_SQUADS,
            loader=loader,
            source="api-football.com/players/squads",
        )
    except ApisportsUnavailable:
        return []

    return [(int(t[0]), t[1]) for t in (gecacht or []) if t]


def verify_current_team(player_id, season=None):
    """
    Belegt, dass ein Spieler AKTUELL in einer FootSim-Liga unter Vertrag steht.

    Rueckgabe bei Beleg:
        {"team_id":, "team_name":, "league_key":, "verified": True,
         "source": "apisports_squad"}

    Sonst None. Das ist ein ehrliches "nicht belegbar" - der Aufrufer darf
    den Spieler dann NICHT als aktuellen Spieler ausgeben.

    Nationalmannschaften und Jugendteams zaehlen bewusst nicht: sie
    belegen keine Vereinszugehoerigkeit in einer der fuenf Ligen.
    """
    if player_id is None:
        return None

    erlaubt = all_verified_teams(season)
    if not erlaubt:
        # Ohne Teamliste laesst sich nichts belegen. Dann lieber gar keine
        # Aussage als eine ungeprüfte.
        return None

    for team_id, team_name in player_squad_team_ids(player_id):
        treffer = erlaubt.get(team_id)
        if treffer:
            return {
                "team_id": team_id,
                # Namen aus der Ligaliste bevorzugen: sie ist die
                # massgebliche Schreibweise dieser Saison.
                "team_name": treffer["name"] or team_name,
                "league_key": treffer["league_key"],
                "verified": True,
                "source": "apisports_squad",
            }

    return None


# ---------------------------------------------------------------------------
# Kaderindex fuer die Spielersuche
# ---------------------------------------------------------------------------
#
# DAS PROBLEM
# -----------
# Die dritte Suchebene (player_compare_loader.search_verified_without_stats)
# nimmt ihre Kandidaten aus den HISTORISCHEN Pools der fuenf Ligen. Wer
# vorher nicht in einer Top-5-Liga gespielt hat, kann dort nicht auftauchen -
# egal wie aktuell sein Vertrag ist.
#
# Real beobachtet: Ein Spieler wechselt von einem Verein ausserhalb der
# fuenf Ligen in die Bundesliga. Das Teamprofil zeigt ihn (es liest
# /players/squads), die Spielersuche findet ihn nicht (sie liest die alten
# Pools). Zwei Ansichten derselben Anwendung widersprechen sich.
#
# DIE LOESUNG
# -----------
# Ein Index ueber die aktuellen Kader ALLER Vereine der fuenf Ligen, gebaut
# aus derselben Quelle, die das Teamprofil benutzt. Damit ist jeder aktuell
# unter Vertrag stehende Spieler auffindbar, unabhaengig von seiner
# Vergangenheit.
#
# KOSTEN
# ------
# Ein Request je Verein, also rund 96 fuer alle fuenf Ligen - aber nur
# einmal, danach aus dem Plattencache. Der Index selbst wird zusaetzlich
# als EIN Cacheeintrag abgelegt, sodass eine Suche im Regelfall null
# Requests kostet. Er wird ausserdem erst als LETZTE Ebene befragt, wenn
# Pool und Live-Suche nichts gefunden haben.

#: Der fertige Index aendert sich nur im Transferfenster.
TTL_SQUAD_INDEX = 60 * 60 * 24        # 24 Stunden


def _squad_members(team_id):
    """Kadermitglieder eines Vereins - ueber den bestehenden Teamcache."""
    from src.api.team_detail import get_team_squad_list

    try:
        return get_team_squad_list(team_id) or []
    except ApisportsUnavailable:
        return []


def build_squad_index(season=None):
    """
    Alle aktuellen Kaderspieler der fuenf Ligen.

    Rueckgabe: Liste von
        {"player_id", "name", "position", "team_id", "team_name",
         "league_code", "age", "number"}

    Die Position wird ueber die zentrale Normalisierung gefuehrt
    (player_metrics.normalize_position), damit der Positionsfilter der
    Suche dieselbe Sprache spricht wie der Rest des Projekts.
    """
    from src.data.player_metrics import normalize_position

    season = resolve_season(season)
    teams = all_verified_teams(season)
    if not teams:
        return []

    eintraege = []
    gesehen = set()

    for team_id, info in sorted(teams.items()):
        for mitglied in _squad_members(team_id):
            pid = mitglied.get("player_id") or mitglied.get("id")
            if pid is None:
                continue
            pid = int(pid)
            # Ein Spieler kann in zwei Kadern stehen (Wechsel im Fenster).
            # Der erste Treffer gewinnt; die Reihenfolge ist ueber die
            # sortierten Team-IDs stabil und damit reproduzierbar.
            if pid in gesehen:
                continue
            gesehen.add(pid)

            eintraege.append({
                "player_id": pid,
                "name": mitglied.get("name"),
                "position": normalize_position(mitglied.get("position")),
                "team_id": team_id,
                "team_name": info.get("name"),
                "league_code": info.get("league_key"),
                "age": mitglied.get("age"),
                "number": mitglied.get("number"),
            })

    return eintraege


def squad_index(season=None):
    """
    Der Kaderindex, gecacht.

    Faellt der Aufbau aus, wird eine leere Liste geliefert - eine Suche
    ohne diese Ebene ist schlechter, aber funktioniert. Ein Ausfall darf
    nie eine Ausnahme bis in den Nutzerrequest tragen.
    """
    season = resolve_season(season)

    def loader():
        return build_squad_index(season)

    try:
        return disk_cached_call(
            key=f"apisports:squad_index:{season}",
            ttl_seconds=TTL_SQUAD_INDEX,
            loader=loader,
            source="api-football.com/players/squads",
        ) or []
    except ApisportsUnavailable:
        return []


def search_squad_index(query, season=None, limit=12):
    """
    Aktuelle Kaderspieler, deren Name die Suchanfrage enthaelt.

    Reine Namenssuche IM INDEX - kein Request je Tastendruck. Die
    Identitaet bleibt die stabile player_id des Anbieters; gleichnamige
    Spieler bleiben dadurch getrennte Personen und werden beide geliefert,
    statt zusammengefuehrt zu werden.
    """
    from src.data import player_names

    if not player_names.normalize_name(query):
        return []

    treffer = []
    for eintrag in squad_index(season):
        # Dieselbe zentrale Namenslogik wie im Pool - sonst faende der
        # Kaderindex Schreibweisen, die der Pool nicht findet, und
        # umgekehrt.
        if player_names.matches(query, eintrag.get("name")):
            treffer.append(eintrag)
            if len(treffer) >= limit:
                break

    treffer.sort(key=lambda e: player_names.sort_key(query, e))
    return treffer


def squad_index_coverage(season=None):
    """Wie viele Vereine und Spieler deckt der Index ab? Fuer die Diagnose."""
    eintraege = squad_index(season)
    vereine = {e.get("team_id") for e in eintraege}
    je_liga = {}
    for e in eintraege:
        lk = e.get("league_code") or "?"
        je_liga[lk] = je_liga.get(lk, 0) + 1
    return {
        "season": resolve_season(season),
        "players": len(eintraege),
        "teams": len(vereine),
        "by_league": je_liga,
        "with_position": sum(1 for e in eintraege if e.get("position")),
    }
