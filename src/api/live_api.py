"""
Live-Spiele eines Kalendertags, gruppiert nach Wettbewerb.

Datenquelle ist API-Football. Bewusst NICHT football-data.org:
    - football-data liefert Spiele nur pro Wettbewerb und Spieltag,
      nicht ueber einen Datumsquerschnitt aller Wettbewerbe
    - die Live-Spielminute (elapsed) gibt es dort nicht

football-data.org bleibt fuer Tabellen, Torjaeger und die Simulation
unveraendert zustaendig. Hier wird nichts migriert.

Request-Zuschnitt
-----------------
Ein einziger Request pro Kalendertag holt ALLE Spiele weltweit
(/fixtures?date=...). Gefiltert wird danach in diesem Modul auf die
Wettbewerbe, die FootSim ueberhaupt kennt. Ein Request pro Liga waere
bei sieben Wettbewerben siebenmal so teuer, ohne mehr zu liefern.

Zeitzone
--------
Der Aufruf uebergibt Europe/Berlin an API-Football. Damit richtet sich
sowohl die Datumsgrenze als auch die zurueckgegebene Anstosszeit nach
deutscher Zeit, inklusive Sommer-/Winterzeit. Zusaetzlich wird beim
Formatieren noch einmal explizit nach Europe/Berlin konvertiert, damit
die Anzeige auch dann stimmt, wenn die Quelle einmal UTC liefert.
Nirgends wird ein UTC-Offset von Hand gerechnet.

Cache
-----
Der Cache liegt auf der Platte, nicht im Prozessspeicher: FootSim laeuft
produktiv mit mehreren Gunicorn-Workern, die sich einen In-Memory-Cache
NICHT teilen. Genau dieser Fehler ist im Projekt schon einmal aufgetreten
(siehe get_all_matches() in league_api.py).

Die TTL haengt vom Zustand des Tages ab (siehe _ttl_for_matches) und ist
deshalb erst nach dem Laden bekannt. Darum werden hier die Bausteine
read_entry/is_fresh/write_entry direkt benutzt statt disk_cached_call(),
das seine TTL vorab braucht.
"""

from datetime import datetime, timezone as dt_timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:                                   # pragma: no cover
    from backports.zoneinfo import ZoneInfo

from src.api import apisports_api
from src.api.apisports_api import (
    ApisportsUnavailable,
    ApisportsRateLimit,
    DISPLAY_TIMEZONE,
)
from src.utils.cache import (
    TTL_LIVE_MATCHES_INPLAY,
    TTL_LIVE_MATCHES_UPCOMING,
    TTL_LIVE_MATCHES_SETTLED,
)
from src.utils.disk_cache import read_entry, is_fresh, write_entry


BERLIN = ZoneInfo(DISPLAY_TIMEZONE)


# ---------------------------------------------------------------------------
# Statuskunde
# ---------------------------------------------------------------------------
#
# API-Football liefert je Spiel einen kurzen Statuscode. Die Codes werden
# hier auf wenige Phasen abgebildet, weil das Frontend nicht 18 Sonderfaelle
# kennen soll, sondern nur: laeuft gerade, Pause, angesetzt, vorbei,
# findet nicht statt.
#
# PHASE_LIVE und PHASE_PAUSED sind getrennt, obwohl beide "das Spiel ist
# im Gange" bedeuten: nur bei PHASE_LIVE ist die Spielminute sinnvoll
# anzuzeigen. In der Halbzeit waere "45'" irrefuehrend.

PHASE_SCHEDULED = "scheduled"
PHASE_LIVE      = "live"
PHASE_PAUSED    = "paused"
PHASE_FINISHED  = "finished"
PHASE_CANCELLED = "cancelled"
PHASE_UNKNOWN   = "unknown"

# short-Code -> (Phase, deutsches Label)
STATUS_MAP = {
    # --- angesetzt ---
    "TBD":  (PHASE_SCHEDULED, "Termin offen"),
    "NS":   (PHASE_SCHEDULED, "Angesetzt"),

    # --- laeuft, Spielminute aussagekraeftig ---
    "1H":   (PHASE_LIVE, "1. Halbzeit"),
    "2H":   (PHASE_LIVE, "2. Halbzeit"),
    "ET":   (PHASE_LIVE, "Verlängerung"),
    "P":    (PHASE_LIVE, "Elfmeterschießen"),
    "LIVE": (PHASE_LIVE, "Läuft"),

    # --- im Gange, aber gerade wird nicht gespielt ---
    "HT":   (PHASE_PAUSED, "Halbzeit"),
    "BT":   (PHASE_PAUSED, "Pause vor Verlängerung"),
    "SUSP": (PHASE_PAUSED, "Unterbrochen"),
    "INT":  (PHASE_PAUSED, "Unterbrochen"),

    # --- vorbei ---
    "FT":   (PHASE_FINISHED, "Ende"),
    "AET":  (PHASE_FINISHED, "Ende n.V."),
    "PEN":  (PHASE_FINISHED, "Ende i.E."),

    # --- findet nicht (regulaer) statt ---
    "PST":  (PHASE_CANCELLED, "Verschoben"),
    "CANC": (PHASE_CANCELLED, "Abgesagt"),
    "ABD":  (PHASE_CANCELLED, "Abgebrochen"),
    "AWD":  (PHASE_CANCELLED, "Gewertet"),
    "WO":   (PHASE_CANCELLED, "Kampflos"),
}

# Diese Phasen bedeuten: an diesem Tag kann sich der Spielstand noch
# jederzeit aendern. Danach richtet sich die kurze TTL.
ACTIVE_PHASES = (PHASE_LIVE, PHASE_PAUSED)


def classify_status(status_short):
    """
    Bildet einen API-Football-Statuscode auf (Phase, Label) ab.

    Unbekannte Codes fuehren bewusst NICHT zu einer Exception: die Quelle
    darf jederzeit einen neuen Code einfuehren, und ein einzelnes
    unbekanntes Spiel darf nicht die ganze Tagesuebersicht zerlegen.
    """
    if not status_short:
        return PHASE_UNKNOWN, "Unbekannt"

    return STATUS_MAP.get(status_short, (PHASE_UNKNOWN, status_short))


# ---------------------------------------------------------------------------
# Normalisierung
# ---------------------------------------------------------------------------

def _kickoff_berlin(raw_date):
    """
    Anstosszeit als datetime in Europe/Berlin, oder None.

    Verarbeitet sowohl "+02:00" als auch das seltenere "Z"-Suffix, das
    datetime.fromisoformat() unter Python 3.9 noch nicht versteht.
    """
    if not raw_date or not isinstance(raw_date, str):
        return None

    text = raw_date.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    # Ohne Zonenangabe ist UTC die einzig vertretbare Annahme.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)

    return parsed.astimezone(BERLIN)


def normalize_fixture(raw, competition_code=None):
    """
    Wandelt einen API-Football-Fixture-Eintrag in die FootSim-Form.

    Rueckgabe None, wenn der Eintrag unbrauchbar ist (keine fixture id).
    Alle uebrigen Felder duerfen fehlen, ohne dass es knallt - eine
    unvollstaendige Antwort soll den Tag nicht unbrauchbar machen.

    fixture_id sowie die API-Football-Team-IDs bleiben bewusst erhalten:
    das Match Center (LIVE B) und spaetere Teamprofile brauchen exakt
    diese IDs. Es wird hier keine eigene Identitaet erfunden.
    """
    if not isinstance(raw, dict):
        return None

    fixture = raw.get("fixture") or {}
    fixture_id = fixture.get("id")
    if fixture_id is None:
        return None

    status = fixture.get("status") or {}
    status_short = status.get("short")
    phase, status_label = classify_status(status_short)

    teams = raw.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}

    goals = raw.get("goals") or {}
    league = raw.get("league") or {}

    kickoff = _kickoff_berlin(fixture.get("date"))

    # Die Spielminute ist nur waehrend des laufenden Spiels aussagekraeftig.
    # Bei abgepfiffenen Spielen liefert die Quelle weiter 90 - das im
    # Frontend anzuzeigen wuerde ein beendetes Spiel wie ein laufendes
    # aussehen lassen.
    elapsed = status.get("elapsed") if phase == PHASE_LIVE else None

    return {
        "fixture_id": fixture_id,
        "kickoff": kickoff.isoformat() if kickoff else None,
        "kickoff_time": kickoff.strftime("%H:%M") if kickoff else None,

        "status_short": status_short,
        "status_long": status.get("long"),
        "status_label": status_label,
        "phase": phase,
        "is_live": phase in ACTIVE_PHASES,
        "elapsed": elapsed,
        "elapsed_extra": status.get("extra") if phase == PHASE_LIVE else None,

        "home_id": home.get("id"),
        "home_name": home.get("name"),
        "home_logo": home.get("logo"),
        "away_id": away.get("id"),
        "away_name": away.get("name"),
        "away_logo": away.get("logo"),

        # Kann null sein - vor dem Anpfiff und bei abgesagten Spielen.
        "home_goals": goals.get("home"),
        "away_goals": goals.get("away"),

        "league_id": league.get("id"),
        "league_name": league.get("name"),
        "league_logo": league.get("logo"),
        "league_country": league.get("country"),
        "competition_code": competition_code,
    }


def _ttl_for_matches(matches):
    """
    TTL nach Tageszustand. Siehe Konstanten in src/utils/cache.py.

    Ein leerer Tag wird wie ein Tag mit kommenden Spielen behandelt: es
    koennte eine Ansetzung nachgetragen werden, und ihn stundenlang als
    leer festzuhalten waere der unangenehmere Fehler.
    """
    if any(match["phase"] in ACTIVE_PHASES for match in matches):
        return TTL_LIVE_MATCHES_INPLAY

    if any(match["phase"] == PHASE_SCHEDULED for match in matches):
        return TTL_LIVE_MATCHES_UPCOMING

    if not matches:
        return TTL_LIVE_MATCHES_UPCOMING

    return TTL_LIVE_MATCHES_SETTLED


def build_day(raw_fixtures, competitions, date_str):
    """
    Filtert, normalisiert und gruppiert die Rohantwort eines Tages.

    competitions: {FootSim-Code: API-Football-League-ID}, in Anzeige-
                  reihenfolge. Die Gruppen kommen in genau dieser
                  Reihenfolge zurueck, nicht in der Reihenfolge der API.

    Reine Funktion ohne Netzwerk und ohne Cache - damit ist sie ohne
    Mocking testbar.
    """
    wanted = {}
    for code, league_id in competitions.items():
        if league_id is not None:
            wanted[league_id] = code

    groups_by_league = {}

    for raw in raw_fixtures or []:
        if not isinstance(raw, dict):
            continue

        league_id = (raw.get("league") or {}).get("id")
        if league_id not in wanted:
            continue

        match = normalize_fixture(raw, competition_code=wanted[league_id])
        if match is None:
            continue

        group = groups_by_league.get(league_id)
        if group is None:
            group = {
                "league_id": league_id,
                "league_name": match["league_name"],
                "league_logo": match["league_logo"],
                "league_country": match["league_country"],
                "competition_code": match["competition_code"],
                "matches": [],
            }
            groups_by_league[league_id] = group

        group["matches"].append(match)

    # Innerhalb einer Gruppe nach Anstoss sortieren; Spiele ohne Zeit
    # ans Ende, damit sie die Reihenfolge nicht durcheinanderbringen.
    for group in groups_by_league.values():
        group["matches"].sort(key=lambda m: (m["kickoff"] is None, m["kickoff"] or ""))

    # Gruppen in FootSim-Reihenfolge, nicht in API-Reihenfolge.
    ordered_groups = [
        groups_by_league[league_id]
        for league_id in competitions.values()
        if league_id in groups_by_league
    ]

    all_matches = [m for group in ordered_groups for m in group["matches"]]

    return {
        "date": date_str,
        "timezone": DISPLAY_TIMEZONE,
        "groups": ordered_groups,
        "match_count": len(all_matches),
        "live_count": sum(1 for m in all_matches if m["is_live"]),
        "stale": False,
    }


# ---------------------------------------------------------------------------
# Oeffentlicher Einstiegspunkt
# ---------------------------------------------------------------------------

def _cache_key(date_str, competitions):
    """
    Ein Eintrag je Kalendertag und Wettbewerbsauswahl.

    Die Liga-IDs gehen in den Key ein, damit eine geaenderte
    Wettbewerbskonfiguration nicht still einen nach altem Zuschnitt
    gefilterten Eintrag weiterverwendet.

    Der Key enthaelt bewusst NICHTS Nutzerspezifisches: alle Besucher
    teilen sich denselben Eintrag, sonst waere der Cache wirkungslos.
    """
    ids = "-".join(str(i) for i in sorted(i for i in competitions.values() if i is not None))
    return f"live_matches:{date_str}:{ids}"


def get_matches_for_date(date_str, competitions):
    """
    Spiele eines Kalendertags, gruppiert nach Wettbewerb.

    date_str:     "YYYY-MM-DD", interpretiert in Europe/Berlin
    competitions: {FootSim-Code: API-Football-League-ID}, Anzeigereihenfolge

    Faellt die Quelle aus, wird ein vorhandener - auch abgelaufener -
    Cache-Eintrag mit stale=True ausgeliefert. Lieber eine Anzeige mit
    dem Hinweis "gerade nicht aktualisierbar" als eine leere Seite.
    Gibt es gar keinen Eintrag, wird die Exception durchgereicht, damit
    die Route einen sauberen Fehler ausgeben kann.
    """
    key = _cache_key(date_str, competitions)
    entry = read_entry(key)

    if is_fresh(entry):
        return entry["payload"]

    try:
        raw_fixtures = apisports_api.get_fixtures_by_date(date_str)
    except (ApisportsUnavailable, ApisportsRateLimit):
        if entry is not None:
            stale_payload = dict(entry["payload"])
            stale_payload["stale"] = True
            return stale_payload
        raise

    payload = build_day(raw_fixtures, competitions, date_str)

    write_entry(
        key,
        payload,
        ttl_seconds=_ttl_for_matches(
            [m for group in payload["groups"] for m in group["matches"]]
        ),
        source="api-football.com/fixtures",
    )

    return payload
