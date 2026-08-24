"""
API-Sports (api-football.com) Zugriff für FootSim.

Zweck: Ergänzt football-data.org dort, wo dessen Free-Tier Lücken hat.
       Konkret: Spielerstatistiken, Top-Scorer mit Fotos, Verletzungen,
       sowie seit Live-Block A die Fixtures/Live-Daten (siehe live_api.py).

Plan-Limits (am Konto verifiziert, Stand August 2026):
    Plan "Pro", 7.500 Requests pro Tag

Frueher stand hier "Free-Plan, 100 Requests pro Tag". Das war seit dem
Upgrade veraltet und hat die Architektur unnoetig eingeschraenkt.

Trotz des groesseren Budgets wird hier weiterhin konsequent gecacht: ein
Cache-Miss soll genau einen externen Request kosten, nicht einen pro
Nutzer. Das ist eine Frage sauberen Server-Designs, nicht des Kontingents.
"""

import os
import requests
from dotenv import load_dotenv

from src.utils.cache import cached_call

load_dotenv()

APISPORTS_KEY = os.getenv("APISPORTS_KEY")
BASE_URL = "https://v3.football.api-sports.io"

# Saison in API-Sports Format: 4-stellige Jahreszahl des Saisonbeginns
# 2025 = Saison 2025/26
#
# Dieselbe Konvention benutzt football-data.org (siehe
# src/api/league_api.py: "Bei football-data.org bezeichnet 2026 die
# Saison 2026/27"). Eine Saisonzahl darf deshalb zwischen beiden
# Anbietern direkt weitergereicht werden - eine Umrechnung waere falsch.
#
# Monat, ab dem die neue Saison gezaehlt wird. Die europaeischen
# Topligen starten im Juli/August; das Sommer-Transferfenster laeuft
# bereits ab Juni/Juli (vgl. src/data/transfer_loader.py). Juli ist
# damit der frueheste Zeitpunkt, ab dem Anfragen sinnvollerweise die
# neue Saison meinen.
SEASON_START_MONTH = 7


def _coerce_season(value):
    """
    Prueft eine Saisonangabe und gibt sie als Jahreszahl zurueck.

    Akzeptiert wird, was sich verlustfrei als vierstellige Jahreszahl
    lesen laesst - also int und Ziffernstring, wie im Projekt ueblich.
    Alles andere ist ein Programmierfehler und soll auffallen, statt
    still einen falschen Provider-Request oder Cache-Key zu erzeugen.
    """
    try:
        year = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"Ungueltige Saison: {value!r}")

    if not 1900 <= year <= 2100:
        raise ValueError(f"Saison ausserhalb des gueltigen Bereichs: {year}")

    return year


def resolve_season(season=None, today=None):
    """
    Liefert die zu verwendende API-Sports-Saison.

    Ein ausdruecklich uebergebener Wert gewinnt IMMER. Nur wenn keiner
    vorliegt, wird aus dem Datum abgeleitet.

    Warum ueberhaupt eine Ableitung: Hier stand frueher die feste Zahl
    2025. Dadurch fragte FootSim im August 2026 Verletzungen und
    Torschuetzen der Saison 2025/26 ab, waehrend die Simulation bereits
    2026/27 rechnete. Ein fester Wert muesste jedes Jahr von Hand
    nachgezogen werden - und wurde es nicht.

    Bewusst KEIN Abruf bei football-data: dieses Modul soll fuer eine
    Jahreszahl keinen zweiten Anbieter (und keinen zweiten API-Schluessel)
    brauchen. Der Aufrufer, der es genau wissen muss, uebergibt die
    Saison ohnehin explizit - der Strength-Pfad tut das.

    today ist fuer Tests injizierbar, damit die Ableitung ohne
    Abhaengigkeit von der echten Uhr pruefbar bleibt.
    """
    if season is not None:
        return _coerce_season(season)

    if today is None:
        from datetime import date
        today = date.today()

    return today.year if today.month >= SEASON_START_MONTH else today.year - 1


# Bequemlichkeitswert fuer Aufrufer, die nur grob "laufende Saison"
# brauchen - vor allem TTL-Entscheidungen der Art
# "season < CURRENT_SEASON ? lange : kurze Lebensdauer".
#
# Bewusst KEIN fachlicher Zwang mehr: Der Wert wird beim Import einmal
# abgeleitet statt fest verdrahtet. Fuer TTL-Heuristik reicht das. Wer
# die Saison fachlich braucht, ruft resolve_season() auf oder uebergibt
# sie explizit - insbesondere der Simulations-/Strength-Pfad.
CURRENT_SEASON = resolve_season()

# Liga-IDs bei API-Sports
# Unveraenderte Eintraege fuer Simulation und bestehende Features:
LEAGUE_IDS = {
    "bl1": 78,    # Bundesliga
    "pl":  39,    # Premier League
    "pd":  140,   # LaLiga
    "sa":  135,   # Serie A
    "fl1": 61,    # Ligue 1
    "cl":  2,     # Champions League
    "el":  3,     # Europa League
    "gsc": 529,   # German Super Cup
    "usc": 531,   # UEFA Super Cup
    "facs": 528,  # FA Community Shield
    # Zusaetzliche Ligen fuer den Transfervergleich:
    "ned1": 88,   # Eredivisie
    "por1": 94,   # Primeira Liga
    "bel1": 144,  # Belgische Pro League
    "tur1": 203,  # Suepper Lig
    "aut1": 218,  # Oesterreichische Bundesliga
    "sui1": 207,  # Schweizer Super League
    "sco1": 179,  # Scottish Premiership
    "mls":  253,  # MLS
    "sau1": 307,  # Saudi Pro League
    "bra1": 71,   # Brasileirao Serie A
    "arg1": 128,  # Primera Division Argentina
    "mex1": 262,  # Liga MX
    "jpn1": 98,   # J1 League
    # Zweite und dritte Ligen:
    "bl2":  79,   # 2. Bundesliga
    "bl3":  80,   # 3. Liga
    "eng2": 40,   # Championship
    "eng3": 41,   # League One
    "eng4": 42,   # League Two
    "pd2":  141,  # LaLiga Hypermotion
    "sa2":  136,  # Serie B
    "fl2":  62,   # Ligue 2
}

# Cache-Zeiten. Bewusst lang: diese Daten aendern sich nicht im
# Minutentakt. Live-Daten haben eigene, kurze TTLs (src/utils/cache.py).
TTL_PLAYERS   = 60 * 60 * 6    # 6 Stunden
TTL_INJURIES  = 60 * 60 * 3    # 3 Stunden
TTL_STANDINGS = 60 * 60 * 2    # 2 Stunden


class ApisportsUnavailable(Exception):
    pass


class ApisportsRateLimit(ApisportsUnavailable):
    """Tages- oder Minutenlimit des API-Sports-Plans erreicht."""
    pass


def _headers():
    if not APISPORTS_KEY:
        return {}
    return {
        "x-rapidapi-host": "v3.football.api-sports.io",
        "x-rapidapi-key": APISPORTS_KEY,
    }


def _get(endpoint, params=None):
    if not APISPORTS_KEY:
        raise ApisportsUnavailable("APISPORTS_KEY fehlt in der .env")

    url = f"{BASE_URL}/{endpoint}"

    try:
        response = requests.get(url, headers=_headers(), params=params or {}, timeout=20)
    except requests.RequestException as e:
        raise ApisportsUnavailable(f"Netzwerkfehler: {e}")

    if response.status_code == 429:
        raise ApisportsRateLimit("API-Sports Rate Limit erreicht (HTTP 429)")

    if response.status_code != 200:
        raise ApisportsUnavailable(f"API-Sports: HTTP {response.status_code}")

    data = response.json()

    # API-Sports liefert Fehler im Body mit errors-Feld.
    # ACHTUNG: Auch Rate-Limit-Fehler kommen teils mit HTTP 200 im Body
    # (Schluessel 'requests' oder 'rateLimit').
    errors = data.get("errors", {})
    if errors:
        if isinstance(errors, dict) and ("requests" in errors or "rateLimit" in errors):
            raise ApisportsRateLimit(f"API-Sports Limit erreicht: {errors}")
        raise ApisportsUnavailable(f"API-Sports Fehler: {errors}")

    return data.get("response", [])


def _get_full(endpoint, params=None):
    """
    Wie _get(), liefert aber die VOLLSTAENDIGE API-Antwort zurueck.

    Hintergrund (Phase 3):
        _get() gibt nur data["response"] zurueck. Fuer paginierte Endpunkte
        wie /players?league=X&season=Y geht dabei der paging-Block verloren,
        sodass ein Importer nicht wissen kann, wie viele Seiten es gibt.

    Rueckgabe:
        {
          "response": [...],          # Nutzdaten dieser Seite
          "results":  20,             # Anzahl Eintraege dieser Seite
          "paging":   {"current": 1, "total": 28},
        }

    Bewusst eine eigene Funktion statt einer Signaturaenderung an _get(),
    damit bestehende Aufrufer (Transfervergleich, Torjaeger, Verletzungen)
    unveraendert weiterlaufen.
    """
    if not APISPORTS_KEY:
        raise ApisportsUnavailable("APISPORTS_KEY fehlt in der .env")

    url = f"{BASE_URL}/{endpoint}"

    try:
        response = requests.get(url, headers=_headers(), params=params or {}, timeout=20)
    except requests.RequestException as e:
        raise ApisportsUnavailable(f"Netzwerkfehler: {e}")

    if response.status_code == 429:
        raise ApisportsRateLimit("API-Sports Rate Limit erreicht (HTTP 429)")

    if response.status_code != 200:
        raise ApisportsUnavailable(f"API-Sports: HTTP {response.status_code}")

    data = response.json()

    errors = data.get("errors", {})
    if errors:
        if isinstance(errors, dict) and ("requests" in errors or "rateLimit" in errors):
            raise ApisportsRateLimit(f"API-Sports Limit erreicht: {errors}")
        raise ApisportsUnavailable(f"API-Sports Fehler: {errors}")

    paging = data.get("paging") or {}

    return {
        "response": data.get("response", []),
        "results": data.get("results", 0),
        "paging": {
            "current": paging.get("current", 1),
            "total": paging.get("total", 1),
        },
    }


def get_league_players_page(league_code, season, page=1):
    """
    Eine Seite der Spielerliste einer Liga (20 Eintraege pro Seite).

    NUR fuer den Importjob gedacht (refresh_players.py), nicht fuer
    Nutzeranfragen: eine komplette Liga braucht rund 26 bis 31 Seiten.

    Kein Cache an dieser Stelle. Der Importer entscheidet selbst, was er
    persistiert, damit nicht hunderte Einzelseiten im Cache landen.
    """
    league_id = LEAGUE_IDS.get(league_code)
    if not league_id:
        raise ApisportsUnavailable(f"Unbekannte Liga: {league_code}")

    return _get_full("players", params={
        "league": league_id,
        "season": season,
        "page": page,
    })


# ---------------------------------------------------------------------------
# Fixtures (Basis fuer den Live-Bereich)
# ---------------------------------------------------------------------------

# API-Football rechnet Datumsgrenze UND die zurueckgegebenen Anstosszeiten
# in diese Zone um, inklusive Sommer-/Winterzeit. Damit muss FootSim
# nirgends selbst einen UTC-Offset rechnen.
DISPLAY_TIMEZONE = "Europe/Berlin"


def get_fixtures_by_date(date_str, timezone=DISPLAY_TIMEZONE):
    """
    Alle Spiele eines Kalendertags - weltweit, mit EINEM Request.

    Bewusst ohne Liga-Filter: ein Request pro Liga waere bei sieben
    Wettbewerben siebenmal so teuer. Gefiltert wird serverseitig im
    Aufrufer (src/api/live_api.py), der die FootSim-Wettbewerbe kennt.

    Bewusst ohne Cache: die TTL haengt davon ab, ob an diesem Tag noch
    gespielt wird. Das weiss erst der Aufrufer, nachdem er die Antwort
    gesehen hat. Gleiches Muster wie get_league_players_page().

    date_str: "YYYY-MM-DD", interpretiert in der uebergebenen Zeitzone.
    """
    return _get("fixtures", params={"date": date_str, "timezone": timezone})


# ---------------------------------------------------------------------------
# Einzelnes Spiel: Details, Ereignisse, Aufstellungen, Statistiken, Spieler
# ---------------------------------------------------------------------------
#
# Fuenf getrennte Endpunkte fuer dasselbe Spiel. Alle fuenf bewusst ohne
# eigenen Cache: das Match Center (src/api/live_api.py) fuehrt sie zu
# EINEM Payload zusammen und cacht diesen gemeinsam. Ein Cache je
# Teilaspekt waere fuenf Eintraege mit derselben Lebensdauer - mehr
# Verwaltung ohne Nutzen. Gleiches Muster wie get_fixtures_by_date().

def get_fixture_by_id(fixture_id, timezone=DISPLAY_TIMEZONE):
    """
    Stammdaten eines Spiels: Teams, Stand, Status, Stadion, Schiedsrichter.

    Rueckgabe ist eine Liste mit hoechstens einem Eintrag (so antwortet
    der Endpunkt), oder eine leere Liste bei unbekannter fixture id.
    """
    return _get("fixtures", params={"id": fixture_id, "timezone": timezone})


def get_fixture_events(fixture_id):
    """Tore, Karten und Wechsel eines Spiels in zeitlicher Reihenfolge."""
    return _get("fixtures/events", params={"fixture": fixture_id})


def get_fixture_lineups(fixture_id):
    """
    Aufstellungen beider Teams: Formation, Startelf, Bank, Trainer.

    Vor der Aufstellungsveroeffentlichung antwortet der Endpunkt mit
    einer leeren Liste - das ist ein normaler Zustand, kein Fehler.
    """
    return _get("fixtures/lineups", params={"fixture": fixture_id})


def get_fixture_statistics(fixture_id):
    """
    Teamstatistiken eines Spiels (Ballbesitz, Schuesse, Ecken, ...).

    Vor dem Anpfiff leer. Einzelne Werte koennen je nach Wettbewerb
    null sein - das bedeutet "nicht erhoben", nicht "null".
    """
    return _get("fixtures/statistics", params={"fixture": fixture_id})


def get_fixture_players(fixture_id):
    """
    Einzelspielerstatistiken eines Spiels, inklusive Spielerbewertung.

    Liefert BEIDE Teams in einem einzigen Request - je Team ein Block mit
    allen eingesetzten und nicht eingesetzten Spielern. Ein Request je
    Team waere doppelt so teuer, ohne mehr zu liefern.

    Die Bewertung steht je Spieler unter statistics[0].games.rating und
    kommt als Zeichenkette ("7.2", "8"), nicht als Zahl. Sie ist null,
    solange ein Spieler nicht eingesetzt wurde, und fehlt vereinzelt auch
    bei eingesetzten Spielern. Beides ist ein normaler Zustand und wird
    in src/api/live_api.py defensiv behandelt - FootSim erfindet keine
    Bewertung.

    Vor dem Anpfiff antwortet der Endpunkt mit einer leeren Liste.
    """
    return _get("fixtures/players", params={"fixture": fixture_id})


# ---------------------------------------------------------------------------
# Team-Detailseite (Block LIVE D2)
# ---------------------------------------------------------------------------
#
# Fuenf getrennte Endpunkte, bewusst ALLE ohne eigenen Cache - genau wie
# bei den vier Match-Center-Endpunkten oben. Anders als beim Match Center
# fuehrt hier aber NICHT ein Aufrufer alle fuenf zu einem gemeinsamen
# Cache-Eintrag zusammen: Teamidentitaet, Tabelle, Spielplan und Kader
# haben grundverschiedene Lebenszyklen (siehe src/api/team_detail.py, wo
# jede Kategorie ihre eigene TTL bekommt). Die Tabelle wird dort zusaetzlich
# je Liga+Saison gecacht, nicht je Team - mehrere Teams derselben Liga
# teilen sich denselben Eintrag.
#
# Alle IDs sind API-Football-Team-/Liga-IDs, derselbe Namensraum, den
# LIVE A bis D1 bereits durchgaengig verwenden. Kein Crosswalk zu
# football-data.org noetig oder gewuenscht.

def get_team_info(team_id):
    """
    Stammdaten eines Teams: Name, Logo, Land, Gruendungsjahr, Stadion.

    Rueckgabe ist eine Liste mit hoechstens einem Eintrag, oder eine
    leere Liste bei unbekannter Team-ID.
    """
    return _get("teams", params={"id": team_id})


def get_standings_table(league_id, season):
    """
    Die VOLLSTAENDIGE Tabelle eines Wettbewerbs.

    Bewusst nicht team-spezifisch: der Aufrufer waehlt die gewuenschte
    Zeile selbst aus (siehe team_detail.py). So teilen sich alle Teams
    derselben Liga und Saison denselben Request und denselben spaeteren
    Cache-Eintrag, statt dass jedes Team einzeln die ganze Tabelle abruft.

    Bei der Champions/Europa League seit der Ligaphasen-Reform eine
    flache Tabelle mit allen Teilnehmern, keine klassischen Gruppen mehr -
    das wird hier nicht angenommen, sondern beim Auslesen defensiv
    behandelt.
    """
    return _get("standings", params={"league": league_id, "season": season})


def get_team_fixtures(team_id, last=None, next=None):
    """
    Letzte oder kommende Spiele eines Teams.

    Genau einer der beiden Parameter wird gesetzt - das ist Sache des
    Aufrufers, hier keine eigene Fallunterscheidung, damit diese Funktion
    ein duenner Durchreicher bleibt wie die uebrigen Endpunkt-Wrapper.
    """
    params = {"team": team_id}
    if last is not None:
        params["last"] = last
    if next is not None:
        params["next"] = next
    return _get("fixtures", params=params)


def get_team_squad(team_id):
    """
    Aktueller Kader eines Teams: Name, Nummer, Position, Alter, Foto.

    Kein Saisonbezug - der Endpunkt liefert immer den aktuellen Kader,
    unabhaengig von einem season-Parameter. Enthaelt bewusst KEINE
    Saisonstatistik je Spieler; die liefert bei Bedarf der bestehende
    D1-Endpunkt /api/player-profile ueber dieselbe Player-ID.
    """
    return _get("players/squads", params={"team": team_id})


def get_team_coach(team_id):
    """
    Trainerhistorie eines Teams, ANFUEHREND mit dem aktuellen Trainer.

    Der Endpunkt liefert zusaetzlich eine lange career-Liste; die wird
    hier unveraendert durchgereicht, aber team_detail.py normalisiert
    daraus bewusst nur den aktuellen Eintrag - eine vollstaendige
    Trainerkarriere gehoert nicht auf eine schlanke Teamseite.
    """
    return _get("coachs", params={"team": team_id})


def get_team_season_fixtures(team_id, league_id, season):
    """
    ALLE Spiele eines Teams in einem Wettbewerb und einer Saison.

    Anders als get_team_fixtures() (relatives "letzte/naechste N", fuer die
    Teamseite) liefert dieser Endpunkt den vollstaendigen Saisonquerschnitt.
    Big Games (Block F1) braucht genau das: erst mit der kompletten
    Spielliste laesst sich entscheiden, welche Partien ueberhaupt
    qualifizieren - und zwar OHNE je Spiel einen eigenen Request.

    Bewusst ohne eigenen Cache: der Aufrufer (src/data/big_games_loader.py)
    cacht die Antwort mit einer saisonabhaengigen TTL, weil nur er weiss,
    ob die Saison abgeschlossen ist. Gleiches Muster wie
    get_fixtures_by_date() und get_league_players_page().
    """
    return _get("fixtures", params={
        "team": team_id,
        "league": league_id,
        "season": season,
    })


def search_players_in_league(query, league_id, season):
    """
    Spielersuche innerhalb GENAU EINES Wettbewerbs und einer Saison.

    API-Football verlangt bei /players?search= zwingend zusaetzlich league
    oder team - eine reine Namenssuche ueber alle Wettbewerbe gibt es nicht
    (an echten Antworten geprueft: sonst Fehler "The League or Team field is
    required with the Search field").

    Bewusst getrennt von search_player() oben: jene Funktion sucht in der
    AKTUELLEN Saison und wird vom Transfervergleich benutzt. Diese hier
    dient der historischen Big-Games-Suche (Block F1) und laesst Saison und
    Wettbewerb ausdruecklich offen.

    Rueckgabe: die rohe Antwortliste. Normalisierung und Deduplizierung je
    Spieler-ID macht der Aufrufer, der ueber mehrere Wettbewerbe hinweg
    zusammenfuehrt.
    """
    return _get("players", params={
        "search": query,
        "league": league_id,
        "season": season,
    })


# ---------------------------------------------------------------------------
# Torjäger mit Fotos
# ---------------------------------------------------------------------------

def get_top_scorers(competition_code, season=None, limit=20):
    """
    Torjäger einer Liga mit Spielerfoto, Team-Logo und Statistiken.

    Rückgabe: Liste von Einträgen, sofort fürs Frontend nutzbar.

    season=None loest die laufende Saison auf. Der Standardwert steht
    bewusst NICHT in der Signatur: dort waere er beim Import einmalig
    gebunden und ein langlaufender Prozess wuerde ihn ueber den
    Saisonwechsel hinweg festhalten.
    """
    season = resolve_season(season)
    league_id = LEAGUE_IDS.get(competition_code)
    if not league_id:
        raise ApisportsUnavailable(f"Unbekannte Liga: {competition_code}")

    def loader():
        raw = _get("players/topscorers", params={"league": league_id, "season": season})

        result = []

        for index, entry in enumerate(raw[:limit], start=1):
            player = entry.get("player") or {}
            stats_list = entry.get("statistics") or [{}]
            stats = stats_list[0] if stats_list else {}

            team = stats.get("team") or {}
            games = stats.get("games") or {}
            goals = stats.get("goals") or {}
            passes = stats.get("passes") or {}

            result.append({
                "rank": index,
                "player_id": player.get("id"),
                "player_name": player.get("name"),
                "player_photo": player.get("photo"),
                "nationality": player.get("nationality"),
                "age": player.get("age"),
                "position": player.get("position"),
                "team_id": team.get("id"),
                "team_name": team.get("name"),
                "team_logo": team.get("logo"),
                "goals": goals.get("total") or 0,
                "assists": goals.get("assists"),
                "penalties": goals.get("conceded"),
                "appearances": games.get("appearences"),
                "minutes": games.get("minutes"),
                "goals_per_match": (
                    round((goals.get("total") or 0) / games["appearences"], 2)
                    if games.get("appearences") else None
                ),
                "key_passes": passes.get("key"),
            })

        return result

    return cached_call(
        key=f"apisports:scorers:{competition_code}:{season}:{limit}",
        ttl_seconds=TTL_PLAYERS,
        loader=loader,
    )


# ---------------------------------------------------------------------------
# Verletzungen und Sperren
# ---------------------------------------------------------------------------

def get_injuries(competition_code, season=None):
    """
    Aktuelle Verletzungen und Sperren einer Liga.

    Nur Spieler mit aktivem Status werden zurückgegeben.

    season=None loest die laufende Saison auf; siehe get_top_scorers zur
    Begruendung, warum der Standard nicht in der Signatur steht.
    """
    season = resolve_season(season)
    league_id = LEAGUE_IDS.get(competition_code)
    if not league_id:
        raise ApisportsUnavailable(f"Unbekannte Liga: {competition_code}")

    def loader():
        raw = _get("injuries", params={"league": league_id, "season": season})

        result = []

        for entry in raw:
            player = entry.get("player") or {}
            team = entry.get("team") or {}
            fixture = entry.get("fixture") or {}

            result.append({
                "player_id": player.get("id"),
                "player_name": player.get("name"),
                "player_photo": player.get("photo"),
                "team_id": team.get("id"),
                "team_name": team.get("name"),
                "team_logo": team.get("logo"),
                "reason": player.get("reason"),
                "type": player.get("type"),
                "fixture_date": fixture.get("date"),
            })

        return result

    return cached_call(
        key=f"apisports:injuries:{competition_code}:{season}",
        ttl_seconds=TTL_INJURIES,
        loader=loader,
    )


# ---------------------------------------------------------------------------
# Spielersuche
# ---------------------------------------------------------------------------

def search_player(name, team_id=None, season=None):
    """
    Sucht einen Spieler nach Name.
    Rückgabe: erste Treffer-Liste, unverarbeitet.
    """
    season = resolve_season(season)
    params = {"search": name, "season": season}
    if team_id:
        params["team"] = team_id

    raw = _get("players", params=params)

    result = []

    for entry in raw[:10]:
        player = entry.get("player") or {}
        stats_list = entry.get("statistics") or [{}]
        stats = stats_list[0] if stats_list else {}
        team = stats.get("team") or {}

        result.append({
            "player_id": player.get("id"),
            "player_name": player.get("name"),
            "player_photo": player.get("photo"),
            "nationality": player.get("nationality"),
            "age": player.get("age"),
            "position": player.get("position"),
            "team_name": team.get("name"),
            "team_logo": team.get("logo"),
        })

    return result


# ---------------------------------------------------------------------------
# Tagesverbrauch überwachen
# ---------------------------------------------------------------------------

def get_request_usage():
    """
    Prüft wie viele Requests des Tageskontingents noch übrig sind.
    Das Limit wird aus der Antwort gelesen, nicht angenommen.
    Dieser Aufruf selbst verbraucht einen Request.
    """
    try:
        response = requests.get(
            f"{BASE_URL}/status",
            headers=_headers(),
            timeout=15
        )

        if response.status_code != 200:
            return None

        data = response.json()
        response_body = data.get("response") or {}
        sub = response_body.get("requests") or {}
        plan = (response_body.get("subscription") or {}).get("plan")

        used = sub.get("current") or 0
        limit = sub.get("limit_day") or 0

        return {
            "used": used,
            "limit": limit,
            "remaining": limit - used,
            "plan": plan,
        }

    except Exception:
        return None
