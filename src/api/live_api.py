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
    TTL_LIVE_MATCH_INPLAY,
    TTL_LIVE_MATCH_SCHEDULED,
    TTL_LIVE_MATCH_SETTLED,
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


# ===========================================================================
# Match Center (Block LIVE B)
# ===========================================================================
#
# Ein einzelnes Spiel in voller Tiefe: Stammdaten, Aufstellungen,
# Ereignisse, Statistiken. Vier Provider-Endpunkte werden serverseitig zu
# EINEM FootSim-Payload zusammengefuehrt und gemeinsam gecacht.
#
# Warum aggregiert und nicht vier Routen: im Match Center werden alle
# vier Aspekte zusammen betrachtet, ein Tabwechsel soll keinen Request
# ausloesen, und alle vier haben denselben Lebenszyklus (laeuft das Spiel
# noch?). Vier getrennte Routen haetten dieselbe Arbeit ins Frontend
# verschoben, ohne etwas zu sparen.
#
# Die Statusuebersetzung wird bewusst von der Tagesliste mitbenutzt
# (classify_status) - eine zweite, womoeglich abweichende Uebersetzung
# derselben Codes waere eine Fehlerquelle.


# Ereignistypen, so wie FootSim sie kennt. Der Provider liefert Typ und
# Detail getrennt ("Goal" + "Own Goal"); hier wird daraus ein Wert, den
# das Frontend direkt zum Rendern benutzen kann.
EVENT_GOAL         = "goal"
EVENT_OWN_GOAL     = "own_goal"
EVENT_PENALTY_MISS = "penalty_missed"
EVENT_YELLOW       = "yellow_card"
EVENT_RED          = "red_card"
EVENT_SUBSTITUTION = "substitution"
EVENT_VAR          = "var"
EVENT_OTHER        = "other"

# Statistiken, die FootSim in fester Reihenfolge zeigt. Der Provider
# liefert je Wettbewerb unterschiedlich viele - was fehlt, wird
# uebersprungen, was da ist, erscheint immer in dieser Reihenfolge.
#
# "core" trennt die sechs Kennzahlen, die praktisch immer vorliegen, von
# den ergaenzenden. Das Frontend kann damit die Kernwerte hervorheben,
# ohne die Reihenfolge selbst zu kennen.
STAT_DEFINITIONS = [
    ("Ball Possession",  "Ballbesitz",          True),
    ("Total Shots",      "Schüsse",             True),
    ("Shots on Goal",    "Schüsse aufs Tor",    True),
    ("Corner Kicks",     "Ecken",               True),
    ("Fouls",            "Fouls",               True),
    ("Offsides",         "Abseits",             True),
    ("Shots off Goal",   "Schüsse daneben",     False),
    ("Blocked Shots",    "Geblockte Schüsse",   False),
    ("Shots insidebox",  "Schüsse im Strafraum", False),
    ("Shots outsidebox", "Schüsse von außerhalb", False),
    ("Goalkeeper Saves", "Paraden",             False),
    ("Total passes",     "Pässe",               False),
    ("Passes accurate",  "Genaue Pässe",        False),
    ("Passes %",         "Passquote",           False),
    ("Yellow Cards",     "Gelbe Karten",        False),
    ("Red Cards",        "Rote Karten",         False),
    ("expected_goals",   "Expected Goals",      False),
]


# ---------------------------------------------------------------------------
# Spielerbewertung (Block LIVE C)
# ---------------------------------------------------------------------------
#
# Die Bewertung stammt unveraendert von API-Football. FootSim rechnet
# KEINE eigene Bewertung aus - weder als Modell noch als Heuristik noch
# als Ersatzwert. Fehlt sie, fehlt sie.
#
# Warum die Einstufung hier und nicht im Frontend liegt:
# Sie ist eine fachliche Einordnung ("war das eine gute Leistung?"),
# keine Darstellungsfrage. Damit gehoert sie an dieselbe Stelle wie
# classify_status() und classify_event(), die ebenfalls Rohwerte des
# Providers auf FootSim-Begriffe abbilden. Das Frontend bekommt eine
# fertige Stufe und entscheidet nur noch ueber die Farbe - so gibt es
# genau eine Wahrheit, die ohne Browser testbar ist.
#
# Die Grenzen sind an echten Antworten kalibriert (218 Bewertungen aus je
# einem Spiel der sieben FootSim-Wettbewerbe, Bundesliga bis Europa
# League). Verteilung dieser Stichprobe: Minimum 5.3, Median 6.7,
# Maximum 9.5. Mit den Grenzen unten liegt der Median in "average" und
# die beiden Enden bleiben selten genug, um etwas zu bedeuten:
#
#     weak            6%    unter 6.0
#     below_average  17%    6.0 bis unter 6.5
#     average        47%    6.5 bis unter 7.2
#     good           23%    7.2 bis unter 8.0
#     excellent       6%    ab 8.0
#
# Eine frueher erwogene Staffelung (6.0/6.8/7.3/8.0) haette 48 Prozent
# aller Spieler als unterdurchschnittlich ausgewiesen, obwohl sie den
# Median enthielt - fachlich falsch und darum verworfen.

RATING_TIER_WEAK          = "weak"
RATING_TIER_BELOW_AVERAGE = "below_average"
RATING_TIER_AVERAGE       = "average"
RATING_TIER_GOOD          = "good"
RATING_TIER_EXCELLENT     = "excellent"

# (Untergrenze einschliesslich, Stufe) - absteigend geprueft.
RATING_TIERS = [
    (8.0, RATING_TIER_EXCELLENT),
    (7.2, RATING_TIER_GOOD),
    (6.5, RATING_TIER_AVERAGE),
    (6.0, RATING_TIER_BELOW_AVERAGE),
    (0.0, RATING_TIER_WEAK),
]


def parse_rating(raw):
    """
    Spielerbewertung als Zahl. None, wenn keine verwertbare vorliegt.

    Der Provider liefert die Bewertung als Zeichenkette und uneinheitlich
    formatiert ("7.2", aber auch "8" statt "8.0") - an echten Antworten
    geprueft. Deshalb wird defensiv geparst statt auf ein Format zu
    vertrauen.

    Werte ausserhalb der Skala 0 bis 10 werden verworfen: eine 47.0
    waere ein Datenfehler, und ihn als Spitzenleistung anzuzeigen waere
    schlimmer, als die Bewertung wegzulassen.
    """
    if raw is None or isinstance(raw, bool):
        return None

    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None

    if value != value:                      # NaN
        return None

    if not 0.0 <= value <= 10.0:
        return None

    return round(value, 1)


def classify_rating(rating):
    """
    Bildet eine Bewertung auf eine FootSim-Stufe ab. None bleibt None.

    Kein Standardwert: ohne Bewertung gibt es keine Stufe, und das
    Frontend zeigt dann schlicht kein Abzeichen.
    """
    if rating is None:
        return None

    for lower_bound, tier in RATING_TIERS:
        if rating >= lower_bound:
            return tier

    return RATING_TIER_WEAK


def _person(raw):
    """
    Spieler-/Trainerangabe auf {id, name} reduzieren.

    Die id ist die API-Football-Player-ID und damit derselbe Namensraum,
    den der FootSim-Spielerpool bereits benutzt. Sie bleibt erhalten,
    damit spaetere Spielerprofile ohne Umweg andocken koennen; hier wird
    bewusst KEINE eigene Identitaet erfunden.

    Rueckgabe None, wenn weder id noch Name vorliegen - "Assist: None"
    waere schlimmer als gar keine Assistangabe.
    """
    if not isinstance(raw, dict):
        return None

    person_id = raw.get("id")
    name = raw.get("name")

    if person_id is None and not name:
        return None

    return {"id": person_id, "name": name}


def classify_event(raw_type, raw_detail):
    """
    Bildet (type, detail) des Providers auf einen FootSim-Ereignistyp ab.

    Unbekannte Kombinationen ergeben EVENT_OTHER statt einer Exception:
    der Provider darf neue Typen einfuehren, ohne dass die Timeline
    zerbricht.
    """
    kind = (raw_type or "").strip().lower()
    detail = (raw_detail or "").strip().lower()

    if kind == "goal":
        if "own goal" in detail:
            return EVENT_OWN_GOAL
        if "missed penalty" in detail:
            return EVENT_PENALTY_MISS
        return EVENT_GOAL

    if kind == "card":
        if "yellow" in detail:
            return EVENT_YELLOW
        if "red" in detail:
            return EVENT_RED
        return EVENT_OTHER

    if kind == "subst":
        return EVENT_SUBSTITUTION

    if kind == "var":
        return EVENT_VAR

    return EVENT_OTHER


def _event_minute_label(elapsed, extra):
    """Spielminute als "73'" oder "90+4'". None, wenn keine Minute vorliegt."""
    if elapsed is None:
        return None
    if extra:
        return f"{elapsed}+{extra}'"
    return f"{elapsed}'"


def normalize_event(raw):
    """
    Ein Ereignis in FootSim-Form. None, wenn der Eintrag unbrauchbar ist.

    Zur Substitution: der Provider fuehrt den AUSGEWECHSELTEN Spieler in
    "player" und den EINGEWECHSELTEN in "assist". Das ist gegen echte
    Antworten geprueft. Damit im Frontend niemand raten muss, werden
    daraus die eindeutigen Felder player_out/player_in.
    """
    if not isinstance(raw, dict):
        return None

    time_block = raw.get("time") or {}
    elapsed = time_block.get("elapsed")
    extra = time_block.get("extra")

    event_type = classify_event(raw.get("type"), raw.get("detail"))

    team = raw.get("team") or {}
    player = _person(raw.get("player"))
    assist = _person(raw.get("assist"))

    event = {
        "type": event_type,
        "detail": raw.get("detail"),
        "comments": raw.get("comments"),

        "elapsed": elapsed,
        "extra": extra,
        "minute_label": _event_minute_label(elapsed, extra),

        # Teamzugehoerigkeit bleibt erhalten, damit die Timeline Heim und
        # Auswaerts unterscheiden kann.
        "team_id": team.get("id"),
        "team_name": team.get("name"),

        "player": player,
        "assist": None,
        "player_in": None,
        "player_out": None,
    }

    if event_type == EVENT_SUBSTITUTION:
        event["player_out"] = player
        event["player_in"] = assist
    else:
        # Nur echte Torvorlagen zeigen. Bei Karten liefert der Provider
        # ohnehin kein assist-Objekt mit Inhalt.
        if event_type in (EVENT_GOAL, EVENT_OWN_GOAL):
            event["assist"] = assist

    return event


def normalize_events(raw_events):
    """
    Alle Ereignisse, chronologisch nach Spielminute inklusive Nachspielzeit.

    Eintraege ohne Minute wandern ans Ende, statt die Reihenfolge der
    uebrigen zu stoeren.
    """
    events = []

    for raw in raw_events or []:
        event = normalize_event(raw)
        if event is not None:
            events.append(event)

    events.sort(key=lambda e: (
        e["elapsed"] is None,
        e["elapsed"] or 0,
        e["extra"] or 0,
    ))

    return events


def parse_grid(raw):
    """
    Zerlegt die Rasterangabe "Reihe:Spalte" in Zahlen.

    Rueckgabe {"row": int, "col": int} oder None, wenn die Angabe fehlt
    oder unbrauchbar ist. Reihe 1 ist die eigene Torlinie, die Spalte
    zaehlt innerhalb der Reihe.

    Bewusst streng: nur genau zwei positive Ganzzahlen werden akzeptiert.
    Ein halb verstandenes Raster wuerde Spieler an falsche Stellen
    setzen, und das waere schlimmer als der Rueckfall auf die Liste.
    """
    if not isinstance(raw, str):
        return None

    parts = raw.strip().split(":")
    if len(parts) != 2:
        return None

    try:
        row = int(parts[0])
        col = int(parts[1])
    except (TypeError, ValueError):
        return None

    if row < 1 or col < 1:
        return None

    return {"row": row, "col": col}


def build_pitch_rows(start_xi):
    """
    Ordnet die Startelf zu Reihen, wie sie auf dem Spielfeld stehen.

    Rueckgabe: Liste von Reihen, je Reihe die INDIZES der Spieler in
    start_xi - von der eigenen Torlinie nach vorne, innerhalb der Reihe
    von links nach rechts. None, wenn sich keine verlaessliche
    Aufstellung bauen laesst; dann zeigt das Frontend die Liste.

    Indizes statt kopierter Spielerobjekte, damit die Startelf nicht
    zweimal im Payload und im Plattencache steht. Das Frontend liest
    lineup.start_xi[index].

    Vollstaendig generisch: ausgewertet wird ausschliesslich das Raster
    der einzelnen Spieler, NIE die Formationsangabe. Damit entstehen
    4-3-3, 4-2-3-1, 3-5-2, 3-4-2-1, 5-4-1 und auch unsymmetrische oder
    unbekannte Formationen ohne eine einzige formationsspezifische Zeile.

    Alles-oder-nichts je Team: fehlt auch nur bei einem Spieler das
    Raster, gilt die ganze Aufstellung als nicht darstellbar. Sonst
    stuende ein Teil der Mannschaft auf dem Feld und der Rest nirgends.

    Doppelt belegte Rasterplaetze werden ebenfalls abgelehnt: zwei
    Spieler auf derselben Position sind ein Datenfehler, den man nicht
    sinnvoll zeichnen kann.
    """
    if not start_xi:
        return None

    by_row = {}
    seen = set()

    for index, player in enumerate(start_xi):
        grid = parse_grid(player.get("grid"))
        if grid is None:
            return None

        slot = (grid["row"], grid["col"])
        if slot in seen:
            return None
        seen.add(slot)

        by_row.setdefault(grid["row"], []).append((grid["col"], index))

    rows = []
    for row_number in sorted(by_row):
        entries = sorted(by_row[row_number], key=lambda pair: pair[0])
        rows.append([index for _, index in entries])

    return rows


def _normalize_player_match_stats(raw_statistics):
    """
    Die Matchwerte eines Spielers aus /fixtures/players.

    Der Provider liefert je Spieler eine Liste mit einem Eintrag. Fehlt
    sie, liegen fuer diesen Spieler schlicht keine Werte vor.

    null bedeutet durchgehend "nicht erhoben" und wird NIE zu 0
    umgedeutet - dieselbe Regel wie bei den Teamstatistiken.
    """
    entries = raw_statistics if isinstance(raw_statistics, list) else []
    stats = entries[0] if entries and isinstance(entries[0], dict) else {}

    games = stats.get("games") or {}
    goals = stats.get("goals") or {}
    cards = stats.get("cards") or {}

    rating = parse_rating(games.get("rating"))

    return {
        "minutes": games.get("minutes"),
        "number": games.get("number"),
        "position": games.get("position"),
        "captain": bool(games.get("captain")),
        # substitute=True heisst "hat auf der Bank begonnen", nicht
        # "wurde eingewechselt" - der Einsatz ergibt sich aus minutes.
        "started_on_bench": bool(games.get("substitute")),

        "rating": rating,
        "rating_tier": classify_rating(rating),

        "goals": goals.get("total"),
        "assists": goals.get("assists"),
        "saves": goals.get("saves"),
        "yellow": cards.get("yellow"),
        "red": cards.get("red"),
    }


def normalize_player_stats(raw_players):
    """
    Alle Einzelspielerwerte eines Spiels als {player_id: Werte}.

    Der Schluessel ist die API-Football-Player-ID - dieselbe stabile ID,
    die auch in Aufstellung und Ereignissen steht. Eintraege ohne ID
    werden verworfen: ohne sie liesse sich der Spieler nur ueber den
    Namen zuordnen, und Namensvergleiche sind bei Umschrift und
    Namensgleichheit unzuverlaessig.

    Das Spielerfoto kommt ausschliesslich aus dieser Antwort; die
    Aufstellung selbst enthaelt keines.
    """
    by_id = {}

    for team_block in raw_players or []:
        if not isinstance(team_block, dict):
            continue

        for entry in team_block.get("players") or []:
            if not isinstance(entry, dict):
                continue

            player = entry.get("player")
            if not isinstance(player, dict):
                continue

            player_id = player.get("id")
            if player_id is None:
                continue

            stats = _normalize_player_match_stats(entry.get("statistics"))
            stats["photo"] = player.get("photo")
            by_id[player_id] = stats

    return by_id


def _normalize_lineup_player(raw, stats_by_id=None):
    """
    Ein Eintrag aus startXI oder substitutes, angereichert um Matchwerte.

    Die Matchwerte werden ueber die API-Football-Player-ID zugeordnet,
    nie ueber den Namen. Liegen fuer einen Spieler keine vor (Spiel noch
    nicht angepfiffen, Bankspieler ohne Einsatz, Luecke beim Provider),
    bleiben die Felder None - ohne Ersatzwerte.
    """
    if not isinstance(raw, dict):
        return None

    player = raw.get("player")
    if not isinstance(player, dict):
        return None

    if player.get("id") is None and not player.get("name"):
        return None

    player_id = player.get("id")

    normalized = {
        "id": player_id,
        "name": player.get("name"),
        "number": player.get("number"),
        "pos": player.get("pos"),
        # grid ("Reihe:Spalte") - Grundlage des Spielfelds. Bleibt roh
        # erhalten, die Auswertung macht build_pitch_rows().
        "grid": player.get("grid"),

        "photo": None,
        "minutes": None,
        "rating": None,
        "rating_tier": None,
        "captain": False,
        "goals": None,
        "assists": None,
        "saves": None,
        "yellow": None,
        "red": None,
    }

    stats = (stats_by_id or {}).get(player_id)
    if stats:
        normalized.update({
            "photo": stats["photo"],
            "minutes": stats["minutes"],
            "rating": stats["rating"],
            "rating_tier": stats["rating_tier"],
            "captain": stats["captain"],
            "goals": stats["goals"],
            "assists": stats["assists"],
            "saves": stats["saves"],
            "yellow": stats["yellow"],
            "red": stats["red"],
        })

        # Die Rueckennummer fehlt in der Aufstellung gelegentlich, steht
        # aber in den Matchwerten - dann die vorhandene benutzen.
        if normalized["number"] is None:
            normalized["number"] = stats["number"]

    return normalized


def normalize_lineup(raw, stats_by_id=None):
    """Aufstellung eines Teams. None, wenn der Block unbrauchbar ist."""
    if not isinstance(raw, dict):
        return None

    team = raw.get("team") or {}
    if team.get("id") is None and not team.get("name"):
        return None

    start_xi = []
    for entry in raw.get("startXI") or []:
        player = _normalize_lineup_player(entry, stats_by_id)
        if player is not None:
            start_xi.append(player)

    substitutes = []
    for entry in raw.get("substitutes") or []:
        player = _normalize_lineup_player(entry, stats_by_id)
        if player is not None:
            substitutes.append(player)

    pitch_rows = build_pitch_rows(start_xi)

    return {
        "team_id": team.get("id"),
        "team_name": team.get("name"),
        "team_logo": team.get("logo"),
        "formation": raw.get("formation"),
        "coach": _person(raw.get("coach")),
        "start_xi": start_xi,
        "substitutes": substitutes,

        # Reihen von der eigenen Torlinie nach vorne, oder None. Das
        # Frontend entscheidet daran, ob es das Spielfeld oder die
        # Liste zeigt - es muss das Raster nicht selbst auswerten.
        "pitch_rows": pitch_rows,
        "has_pitch": pitch_rows is not None,
    }


def normalize_lineups(raw_lineups, stats_by_id=None):
    lineups = []

    for raw in raw_lineups or []:
        lineup = normalize_lineup(raw, stats_by_id)
        if lineup is not None:
            lineups.append(lineup)

    return lineups


def _stat_lookup(raw_team_block):
    """Statistikliste eines Teams als {Typ: Wert}."""
    values = {}

    for entry in (raw_team_block or {}).get("statistics") or []:
        if not isinstance(entry, dict):
            continue
        stat_type = entry.get("type")
        if stat_type:
            values[stat_type] = entry.get("value")

    return values


def normalize_statistics(raw_statistics, home_id, away_id):
    """
    Statistiken als Zeilen "Heimwert - Bezeichnung - Auswaertswert".

    Zeilen, fuer die BEIDE Teams keinen Wert haben, entfallen ganz -
    eine Zeile "– Abseits –" traegt keine Information. Liefert nur eine
    Seite einen Wert, bleibt die Zeile erhalten und die andere Seite ist
    null; das Frontend zeigt dort einen Strich.

    null bedeutet ausdruecklich "nicht erhoben" und wird NIE zu 0
    umgedeutet - 0 waere eine Tatsachenbehauptung, die wir nicht haben.
    """
    by_team = {}

    for block in raw_statistics or []:
        if not isinstance(block, dict):
            continue
        team_id = (block.get("team") or {}).get("id")
        if team_id is not None:
            by_team[team_id] = _stat_lookup(block)

    home_values = by_team.get(home_id, {})
    away_values = by_team.get(away_id, {})

    rows = []

    for stat_type, label, is_core in STAT_DEFINITIONS:
        home_value = home_values.get(stat_type)
        away_value = away_values.get(stat_type)

        if home_value is None and away_value is None:
            continue

        rows.append({
            "key": stat_type,
            "label": label,
            "core": is_core,
            "home": home_value,
            "away": away_value,
        })

    return rows


def _normalize_match_detail(raw_fixture):
    """Stammdaten aus /fixtures?id= - Teams, Stand, Status, Ort, Schiedsrichter."""
    fixture = raw_fixture.get("fixture") or {}
    status = fixture.get("status") or {}
    venue = fixture.get("venue") or {}
    league = raw_fixture.get("league") or {}
    teams = raw_fixture.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    goals = raw_fixture.get("goals") or {}

    status_short = status.get("short")
    phase, status_label = classify_status(status_short)

    kickoff = _kickoff_berlin(fixture.get("date"))

    # Wie in der Tagesliste: die Minute ist nur waehrend des laufenden
    # Spiels aussagekraeftig, sonst liefert die Quelle weiterhin 90.
    elapsed = status.get("elapsed") if phase == PHASE_LIVE else None
    extra = status.get("extra") if phase == PHASE_LIVE else None

    return {
        "fixture": {
            "fixture_id": fixture.get("id"),
            "kickoff": kickoff.isoformat() if kickoff else None,
            "kickoff_time": kickoff.strftime("%H:%M") if kickoff else None,
            "status_short": status_short,
            "status_long": status.get("long"),
            "status_label": status_label,
            "phase": phase,
            "is_live": phase in ACTIVE_PHASES,
            "elapsed": elapsed,
            "extra": extra,
            "minute_label": _event_minute_label(elapsed, extra),
            "referee": fixture.get("referee"),
            "venue_name": venue.get("name"),
            "venue_city": venue.get("city"),
            "round": league.get("round"),
        },
        "league": {
            "id": league.get("id"),
            "name": league.get("name"),
            "logo": league.get("logo"),
            "country": league.get("country"),
        },
        "home": {
            "id": home.get("id"),
            "name": home.get("name"),
            "logo": home.get("logo"),
            "goals": goals.get("home"),
        },
        "away": {
            "id": away.get("id"),
            "name": away.get("name"),
            "logo": away.get("logo"),
            "goals": goals.get("away"),
        },
    }


def build_match_center(raw_fixture, raw_events, raw_lineups, raw_statistics,
                       raw_players=None):
    """
    Fuehrt die fuenf Provider-Antworten zu einem FootSim-Payload zusammen.

    Reine Funktion ohne Netzwerk und ohne Cache - dadurch ohne Mocking
    testbar, genau wie build_day().

    Rueckgabe None, wenn die Stammdaten fehlen: ohne Teams und Status
    gibt es kein Match Center. Fehlende Aufstellungen, Ereignisse,
    Statistiken oder Einzelspielerwerte sind dagegen normale Zustaende
    (Spiel noch nicht angepfiffen) und ergeben schlicht leere Listen
    beziehungsweise Spieler ohne Matchwerte.

    raw_players ist bewusst der letzte Parameter mit Standardwert: so
    bleiben bestehende Aufrufe mit vier Argumenten gueltig.
    """
    if not isinstance(raw_fixture, dict):
        return None

    detail = _normalize_match_detail(raw_fixture)

    if detail["fixture"]["fixture_id"] is None:
        return None

    stats_by_id = normalize_player_stats(raw_players)
    lineups = normalize_lineups(raw_lineups, stats_by_id)
    home_id = detail["home"]["id"]
    away_id = detail["away"]["id"]

    # Aufstellungen in Heim-/Auswaertsreihenfolge, nicht in
    # Provider-Reihenfolge - das Frontend soll nicht selbst suchen.
    lineups_by_team = {lineup["team_id"]: lineup for lineup in lineups}

    return {
        **detail,
        "home_lineup": lineups_by_team.get(home_id),
        "away_lineup": lineups_by_team.get(away_id),
        "events": normalize_events(raw_events),
        "statistics": normalize_statistics(raw_statistics, home_id, away_id),
        "stale": False,
    }


def _ttl_for_match(payload):
    """TTL nach Spielzustand. Siehe Konstanten in src/utils/cache.py."""
    phase = payload["fixture"]["phase"]

    if phase in ACTIVE_PHASES:
        return TTL_LIVE_MATCH_INPLAY

    if phase == PHASE_SCHEDULED:
        return TTL_LIVE_MATCH_SCHEDULED

    return TTL_LIVE_MATCH_SETTLED


def get_match_center(fixture_id):
    """
    Alle Daten eines Spiels fuer das Match Center.

    fixture_id: API-Football fixture id (int)

    Kostet bei einem Cache-Miss fuenf Provider-Requests und schreibt genau
    einen Cache-Eintrag. Alle Nutzer teilen sich diesen Eintrag ueber
    alle Gunicorn-Worker hinweg (Platte, nicht Prozessspeicher). Der
    fuenfte Request (Einzelspielerwerte) liefert beide Teams auf einmal -
    es gibt bewusst keinen Request je Team und erst recht keinen je
    Spieler.

    Faellt die Quelle aus, wird ein vorhandener - auch abgelaufener -
    Eintrag mit stale=True ausgeliefert, wie bei der Tagesliste.
    Rueckgabe None, wenn es das Spiel nicht gibt.
    """
    key = f"live_match:{fixture_id}"
    entry = read_entry(key)

    if is_fresh(entry):
        return entry["payload"]

    try:
        fixtures = apisports_api.get_fixture_by_id(fixture_id)

        # Unbekannte fixture id: der Endpunkt antwortet mit einer leeren
        # Liste. Dann sind die vier uebrigen Requests sinnlos.
        if not fixtures:
            return None

        raw_fixture = fixtures[0]

        raw_events = apisports_api.get_fixture_events(fixture_id)
        raw_lineups = apisports_api.get_fixture_lineups(fixture_id)
        raw_statistics = apisports_api.get_fixture_statistics(fixture_id)
        raw_players = apisports_api.get_fixture_players(fixture_id)

    except (ApisportsUnavailable, ApisportsRateLimit):
        if entry is not None:
            stale_payload = dict(entry["payload"])
            stale_payload["stale"] = True
            return stale_payload
        raise

    payload = build_match_center(raw_fixture, raw_events, raw_lineups, raw_statistics,
                                 raw_players)

    if payload is None:
        return None

    write_entry(
        key,
        payload,
        ttl_seconds=_ttl_for_match(payload),
        source="api-football.com/fixtures+events+lineups+statistics",
    )

    return payload
