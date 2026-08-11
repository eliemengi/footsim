"""
Team-Detailseite (Block LIVE D2).

Zweck
-----
Ein Team im Detail, erreichbar durch Antippen von Heim- oder Auswaertsteam
im Match Center: Identitaet, aktuelle Tabellenposition im Wettbewerb des
geoeffneten Spiels, letzte und kommende Spiele, Kader, aktueller Trainer.

Bewusst NICHT team_profile.py
------------------------------
src/features/team_profile.py gehoert zum Simulationsmodell (Attack-/
Defence-Ratings, football-data.org-Team-ID-Raum) und hat mit dieser Datei
nichts zu tun ausser dem Wort "Team". Namenskollision bewusst vermieden.

Ein ID-Raum, kein Crosswalk
----------------------------
Alle Funktionen hier arbeiten ausschliesslich mit API-Football-IDs -
demselben Namensraum, den LIVE A bis D1 bereits durchgaengig verwenden
(home_id/away_id, lineup.team_id, league.id, league.season). Es gibt
bewusst KEIN Mapping zu football-data.org-Team-IDs: TEAM_ALIASES und
find_team_by_name() (src/utils/team_aliases.py, src/api/football_api.py)
sind fuer diese Seite weder noetig noch geeignet - beide sind
Namensheuristiken fuer einen anderen Zweck (Aufsteiger-Erkennung im
Simulationsmodell), keine belastbare Identitaetsloesung.

Caching: getrennt je Kategorie, nicht kombiniert
--------------------------------------------------
Anders als src/api/live_api.py::get_match_center() (VIER Provider-Calls
zu EINEM Cache-Eintrag, weil sie denselben Lebenszyklus teilen - laeuft
das Spiel noch?) haben Teamidentitaet, Tabelle, Spielplan und Kader
grundverschiedene Lebenszyklen. Ein Team wechselt sein Stadion praktisch
nie, aber die Tabelle aendert sich nach jedem Spieltag. Deshalb bekommt
hier JEDE Kategorie ihren EIGENEN disk_cached_call()-Eintrag mit eigener
TTL, statt sie wie beim Match Center zusammenzufassen.

Die Tabelle wird zusaetzlich bewusst je LIGA+SAISON gecacht, nicht je
Team: get_standings_table() liefert die komplette Tabelle, diese Datei
waehlt erst danach die gewuenschte Zeile aus. Oeffnen zwei Nutzer zwei
verschiedene Teams derselben Liga und Saison (z. B. beide Finalisten
eines Spiels), teilen sie sich denselben Cache-Eintrag.
"""

from src.api import apisports_api
from src.api.apisports_api import (
    ApisportsUnavailable,
    ApisportsRateLimit,
    TTL_STANDINGS,
)
from src.api.live_api import BERLIN, _kickoff_berlin, classify_status
from src.utils.disk_cache import disk_cached_call


# Teamidentitaet und Stadion aendern sich praktisch nie innerhalb einer
# Saison.
TTL_TEAM_INFO = 60 * 60 * 24 * 7            # 7 Tage

# Kommende Ansetzungen koennen sich verschieben (TV-Verlegung etc.).
TTL_TEAM_FIXTURES_NEXT = 60 * 60 * 4        # 4 Stunden

# Ein gespieltes Ergebnis aendert sich praktisch nie mehr nachtraeglich.
TTL_TEAM_FIXTURES_LAST = 60 * 60 * 24       # 24 Stunden

# Kaderaenderungen ausserhalb der Transferfenster sind die Ausnahme.
TTL_TEAM_SQUAD = 60 * 60 * 24 * 3           # 3 Tage

# Kuerzer als der Kader: Trainerentlassungen passieren ploetzlich, ein
# laengst gefeuerter Trainer waere ein sichtbarer, peinlicher Fehler.
TTL_TEAM_COACH = 60 * 60 * 24 * 2           # 2 Tage

# TTL_STANDINGS kommt unveraendert aus apisports_api.py (dort bereits
# definiert, bislang aber von niemandem verwendet) - keine zweite,
# womoeglich abweichende Tabellen-TTL.


# ---------------------------------------------------------------------------
# Normalisierung
# ---------------------------------------------------------------------------

def normalize_team_info(raw_teams):
    """Stammdaten aus /teams?id=. None bei unbekannter Team-ID."""
    if not raw_teams:
        return None

    entry = raw_teams[0]
    if not isinstance(entry, dict):
        return None

    team = entry.get("team") or {}
    venue = entry.get("venue") or {}

    if team.get("id") is None:
        return None

    return {
        "id": team.get("id"),
        "name": team.get("name"),
        "logo": team.get("logo"),
        "country": team.get("country"),
        "founded": team.get("founded"),
        "venue_name": venue.get("name"),
        "venue_city": venue.get("city"),
    }


def find_standings_row(raw_standings, team_id):
    """
    Sucht die Zeile eines Teams in einer vollstaendigen Tabellenantwort.

    "standings" ist eine Liste von Gruppen (Liste von Listen), auch wenn
    es bei den meisten unserer Wettbewerbe nur eine einzige gibt. Alle
    Gruppen werden durchsucht, damit ein spaeter doch wieder eingefuehrtes
    klassisches Gruppenformat nicht stillschweigend leer bliebe.
    """
    if not raw_standings:
        return None

    league_block = raw_standings[0].get("league") or {}
    groups = league_block.get("standings") or []

    for group in groups:
        for row in group or []:
            if not isinstance(row, dict):
                continue
            if (row.get("team") or {}).get("id") == team_id:
                return row

    return None


def normalize_standings_row(row):
    """
    Eine Tabellenzeile fuers Frontend. None, wenn das Team in dieser
    Liga/Saison nicht auftaucht (z. B. gerade abgestiegen).

    "form" kommt fertig vom Provider (z. B. "DLDWL") - keine eigene
    Formberechnung aus Einzelspielen.

    "description" enthaelt bei CL/EL seit der Ligaphasen-Reform keine
    klassische Gruppenaussage mehr (z. B. "Promotion - Champions League
    (Play Offs: 1/16-finals)"). Wird unveraendert als Text durchgereicht,
    nicht als "Gruppe X" interpretiert - genau das waere falsche Semantik.
    """
    if not row:
        return None

    all_stats = row.get("all") or {}
    goals = all_stats.get("goals") or {}

    return {
        "rank": row.get("rank"),
        "points": row.get("points"),
        "goals_diff": row.get("goalsDiff"),
        "form": row.get("form"),
        "description": row.get("description"),
        "played": all_stats.get("played"),
        "wins": all_stats.get("win"),
        "draws": all_stats.get("draw"),
        "losses": all_stats.get("lose"),
        "goals_for": goals.get("for"),
        "goals_against": goals.get("against"),
    }


def normalize_team_fixture(raw, team_id):
    """
    Ein Spiel aus TEAM-Sicht: Gegner statt Heim-/Auswaertspaar.

    Bewusst eine eigene, kleinere Normalisierung statt live_api.
    normalize_fixture() wiederzuverwenden: die Tagesliste braucht die
    Heim-/Auswaerts-Perspektive fuer beide Teams gleichzeitig, eine
    Teamseite braucht die Gegner-Perspektive fuer GENAU dieses eine Team.
    Zeitzone (_kickoff_berlin) und Statusuebersetzung (classify_status)
    werden trotzdem von live_api.py wiederverwendet - eine zweite,
    womoeglich abweichende Uebersetzung derselben Codes waere eine
    Fehlerquelle, genau wie live_api.py selbst an anderer Stelle begruendet.
    """
    if not isinstance(raw, dict):
        return None

    fixture = raw.get("fixture") or {}
    fixture_id = fixture.get("id")
    if fixture_id is None:
        return None

    status = fixture.get("status") or {}
    phase, status_label = classify_status(status.get("short"))

    teams = raw.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    goals = raw.get("goals") or {}
    league = raw.get("league") or {}

    is_home = home.get("id") == team_id
    opponent = away if is_home else home

    kickoff = _kickoff_berlin(fixture.get("date"))

    return {
        "fixture_id": fixture_id,
        "kickoff": kickoff.isoformat() if kickoff else None,
        "kickoff_time": kickoff.strftime("%H:%M") if kickoff else None,
        "status_short": status.get("short"),
        "status_label": status_label,
        "phase": phase,
        "is_home": is_home,
        "opponent_id": opponent.get("id"),
        "opponent_name": opponent.get("name"),
        "opponent_logo": opponent.get("logo"),
        # Immer aus Sicht DIESES Teams, nicht aus Heim-/Auswaertssicht -
        # das erspart dem Frontend, bei jedem Eintrag erneut is_home
        # gegen die Tore abzugleichen.
        "team_goals": goals.get("home") if is_home else goals.get("away"),
        "opponent_goals": goals.get("away") if is_home else goals.get("home"),
        "league_name": league.get("name"),
        "league_logo": league.get("logo"),
    }


def normalize_team_fixtures(raw_fixtures, team_id):
    fixtures = []
    for raw in raw_fixtures or []:
        fixture = normalize_team_fixture(raw, team_id)
        if fixture is not None:
            fixtures.append(fixture)
    return fixtures


def normalize_squad(raw_squad):
    """
    Aktueller Kader: Name, Nummer, Position, Alter, Foto, Player-ID.

    Die Player-ID bleibt erhalten, damit ein Kadereintrag direkt das
    bestehende D1-Spielerprofil oeffnen kann (/api/player-profile) - ohne
    sie waere nur eine Namenssuche moeglich, und die ist ausdruecklich
    nicht gewollt.
    """
    if not raw_squad:
        return []

    entry = raw_squad[0]
    if not isinstance(entry, dict):
        return []

    result = []
    for raw_player in entry.get("players") or []:
        if not isinstance(raw_player, dict) or raw_player.get("id") is None:
            continue
        result.append({
            "id": raw_player.get("id"),
            "name": raw_player.get("name"),
            "number": raw_player.get("number"),
            "position": raw_player.get("position"),
            "age": raw_player.get("age"),
            "photo": raw_player.get("photo"),
        })

    return result


def normalize_coach(raw_coach):
    """
    Nur der AKTUELLE Trainer, nicht die vollstaendige Karrierehistorie.

    "Aktuell" heisst: der career-Eintrag mit end=None. Bewusst nicht
    career[0] angenommen - auch wenn das in der Praxis meist der aktuelle
    Eintrag ist, ist end=None die einzige Angabe, die es wirklich sagt.
    """
    if not raw_coach:
        return None

    entry = raw_coach[0]
    if not isinstance(entry, dict):
        return None

    if entry.get("id") is None and not entry.get("name"):
        return None

    career = entry.get("career") or []
    current = next(
        (c for c in career if isinstance(c, dict) and c.get("end") is None),
        None,
    )

    return {
        "id": entry.get("id"),
        "name": entry.get("name"),
        "photo": entry.get("photo"),
        "age": entry.get("age"),
        "nationality": entry.get("nationality"),
        "since": current.get("start") if current else None,
    }


# ---------------------------------------------------------------------------
# Gecachte Kategorien
# ---------------------------------------------------------------------------

def get_team_identity(team_id):
    def loader():
        return apisports_api.get_team_info(team_id)

    raw = disk_cached_call(
        key=f"apisports:team_info:{team_id}",
        ttl_seconds=TTL_TEAM_INFO,
        loader=loader,
        source="api-football.com/teams",
    )
    return normalize_team_info(raw)


def get_team_standings(league_id, season, team_id):
    def loader():
        return apisports_api.get_standings_table(league_id, season)

    raw = disk_cached_call(
        key=f"apisports:standings:{league_id}:{season}",
        ttl_seconds=TTL_STANDINGS,
        loader=loader,
        source="api-football.com/standings",
    )
    return normalize_standings_row(find_standings_row(raw, team_id))


def get_team_recent_fixtures(team_id, limit=5):
    def loader():
        return apisports_api.get_team_fixtures(team_id, last=limit)

    raw = disk_cached_call(
        key=f"apisports:team_fixtures_last:{team_id}:{limit}",
        ttl_seconds=TTL_TEAM_FIXTURES_LAST,
        loader=loader,
        source="api-football.com/fixtures",
    )
    return normalize_team_fixtures(raw, team_id)


def get_team_upcoming_fixtures(team_id, limit=5):
    def loader():
        return apisports_api.get_team_fixtures(team_id, next=limit)

    raw = disk_cached_call(
        key=f"apisports:team_fixtures_next:{team_id}:{limit}",
        ttl_seconds=TTL_TEAM_FIXTURES_NEXT,
        loader=loader,
        source="api-football.com/fixtures",
    )
    return normalize_team_fixtures(raw, team_id)


def get_team_squad_list(team_id):
    def loader():
        return apisports_api.get_team_squad(team_id)

    raw = disk_cached_call(
        key=f"apisports:team_squad:{team_id}",
        ttl_seconds=TTL_TEAM_SQUAD,
        loader=loader,
        source="api-football.com/players/squads",
    )
    return normalize_squad(raw)


def get_team_current_coach(team_id):
    def loader():
        return apisports_api.get_team_coach(team_id)

    raw = disk_cached_call(
        key=f"apisports:team_coach:{team_id}",
        ttl_seconds=TTL_TEAM_COACH,
        loader=loader,
        source="api-football.com/coachs",
    )
    return normalize_coach(raw)


# ---------------------------------------------------------------------------
# Oeffentlicher Einstiegspunkt
# ---------------------------------------------------------------------------

def _soft_call(loader, *args, fallback=None):
    """
    Ruft eine Kategorie ab; ein Providerausfall OHNE brauchbaren
    Cache-Rest fuehrt nur zu fallback, nicht zum Abbruch der gesamten
    Teamseite. disk_cached_call() liefert bei einem Ausfall bereits einen
    abgelaufenen Cache-Eintrag, falls vorhanden - dieser Fang greift nur,
    wenn wirklich gar nichts vorliegt.

    Bewusst NICHT fuer die Teamidentitaet selbst verwendet: ohne sie gibt
    es nichts Sinnvolles anzuzeigen, ein Ausfall dort soll als echter
    Fehler beim Aufrufer ankommen (503/429), nicht als leere Seite.
    """
    try:
        return loader(*args)
    except (ApisportsUnavailable, ApisportsRateLimit):
        return fallback


def build_team_detail(team_id, league_id=None, season=None):
    """
    Vollstaendige Team-Detailansicht.

    league_id/season sind optional: sie legen fest, gegen welchen
    Wettbewerb die Tabellenzeile gezogen wird - typischerweise der
    Wettbewerb des Spiels, aus dem heraus das Team geoeffnet wurde
    (siehe live_api.py, league.id/league.season sind dort bereits
    vorhanden). Fehlen sie, bleibt "standings" schlicht None - kein
    Fehler, nur eine fehlende Kategorie wie jede andere auch.

    Rueckgabe None, wenn schon die Teamidentitaet nicht geladen werden
    kann (unbekannte Team-ID oder Totalausfall des Providers).
    """
    identity = get_team_identity(team_id)
    if identity is None:
        return None

    standings = None
    if league_id is not None and season is not None:
        standings = _soft_call(get_team_standings, league_id, season, team_id)

    return {
        "team": identity,
        "standings": standings,
        "recent_fixtures": _soft_call(get_team_recent_fixtures, team_id, fallback=[]),
        "upcoming_fixtures": _soft_call(get_team_upcoming_fixtures, team_id, fallback=[]),
        "squad": _soft_call(get_team_squad_list, team_id, fallback=[]),
        "coach": _soft_call(get_team_current_coach, team_id),
    }
