"""
Loader fuer den Spielervergleich (Phase 3).

Abgrenzung zu player_stats_loader.py:
    player_stats_loader.py gehoert zum Transfervergleich und liefert eine
    schmale Sicht (Minuten, Tore, Assists, Rating) fuer eine ZIELLIGA.
    Dieses Modul wird davon bewusst NICHT abgeleitet, damit der bestehende
    Transfervergleich durch Phase 3 nicht regressieren kann.

Aufgabe hier:
    Vollstaendige Saisonstatistik eines Spielers in seiner Hauptliga,
    aufbereitet in derselben verschachtelten Struktur, die API-Sports
    verwendet. Dadurch kann player_metrics.compute_metric() direkt darauf
    arbeiten.

Wahl der Hauptliga (wichtige fachliche Entscheidung):
    Ein /players-Eintrag enthaelt mehrere statistics-Bloecke, je einen pro
    Wettbewerb (Liga, Pokal, Champions League) und teils pro Verein.

    Fuer den Vergleich wird ausschliesslich die LIGA mit den meisten
    Einsatzminuten ausgewertet, und innerhalb dieser Liga werden mehrere
    Vereinseintraege summiert (Vereinswechsel innerhalb derselben Liga).

    Begruendung: Der spaetere Perzentil-Referenzpool besteht aus
    Ligaspielern. Wuerde man Pokal- und Europapokalminuten hinzuaddieren,
    waere der Spielerwert nicht mehr mit dem Pool vergleichbar.
    Pokaldaten gehen dadurch verloren; das ist der bewusst gewaehlte Preis
    fuer einen fairen Vergleich.

Rate-Limit:
    Ein Request pro Spieler und Saison, danach dauerhaft im Disk-Cache.
    Abgeschlossene Saisons aendern sich nie mehr.
"""

import time

from src.api.apisports_api import (
    _get,
    LEAGUE_IDS,
    CURRENT_SEASON,
    ApisportsUnavailable,
)
from src.utils.disk_cache import disk_cached_call
from src.data.player_metrics import (
    POSITION_GROUPS,
    POSITION_GENERAL,
    POSITION_LABELS,
    compute_metric,
    metrics_for_position,
    describe_metric,
    GENERAL_METRICS,
)
from src.data.percentile_engine import (
    percentiles_for_player,
    describe_pool,
    is_snapshot_complete,
)


TTL_FINISHED_SEASON = 60 * 60 * 24 * 365   # 1 Jahr
TTL_CURRENT_SEASON  = 60 * 60 * 24         # 24 Stunden


# Ligen, die fuer den Vergleich und den spaeteren Perzentil-Pool zaehlen.
# Bewusst nur die Top-5, weil nur dort ein sinnvoller Referenzpool entsteht.
COMPARE_LEAGUE_CODES = ("bl1", "pl", "pd", "sa", "fl1")

COMPARE_LEAGUE_LABELS = {
    "bl1": "Bundesliga",
    "pl":  "Premier League",
    "pd":  "LaLiga",
    "sa":  "Serie A",
    "fl1": "Ligue 1",
}

COMPARE_LEAGUE_IDS = {
    LEAGUE_IDS[code]: code
    for code in COMPARE_LEAGUE_CODES
    if code in LEAGUE_IDS
}


# ---------------------------------------------------------------------------
# Wettbewerbsumfang (Phase 3.2)
# ---------------------------------------------------------------------------
#
# API-Sports liefert pro Spieler und Saison mehrere statistics-Bloecke, je
# einen pro Wettbewerb. Jeder Block SOLLTE league.type tragen:
#
#     "League"         nationale Liga
#     "Cup"            nationaler Pokal, Champions League, Europa League,
#                      Conference League, Supercups, Klub-WM
#     "International"  Nationalmannschaft: WM, EM, Nations League, Quali
#
# Wichtig: API-Sports fuehrt die Champions League als "Cup", nicht als
# "International". "International" bedeutet dort Nationalmannschaft.
#
# In der Praxis fehlt league.type beim Pro-Plan vollstaendig (None).
# _infer_comp_type() leitet den Typ dann aus Liga-ID und Liganame ab.

SCOPE_CLUB_ALL = "club_all"      # Standard: Liga + Pokale + Europapokal
SCOPE_LEAGUE   = "league"        # nur nationale Liga
SCOPE_NATIONAL = "national"      # nur Nationalmannschaft
SCOPE_ALL      = "all"           # Verein und Nationalmannschaft

COMPETITION_SCOPES = (SCOPE_CLUB_ALL, SCOPE_LEAGUE, SCOPE_NATIONAL, SCOPE_ALL)

DEFAULT_SCOPE = SCOPE_CLUB_ALL

SCOPE_LABELS = {
    SCOPE_CLUB_ALL: "Alle Vereinswettbewerbe",
    SCOPE_LEAGUE:   "Nur Liga",
    SCOPE_NATIONAL: "Nur Nationalmannschaft",
    SCOPE_ALL:      "Alle Wettbewerbe",
}

SCOPE_HINTS = {
    SCOPE_CLUB_ALL: "Liga, nationale Pokale und europäische Wettbewerbe zusammen.",
    SCOPE_LEAGUE:   "Nur die nationale Liga. Der fairste Vergleich, weil alle "
                    "Spieler dieselbe Anzahl Partien und dieselben Gegner haben.",
    SCOPE_NATIONAL: "Nur Länderspiele. Wenige Partien pro Saison, daher als "
                    "kleine Stichprobe zu lesen.",
    SCOPE_ALL:      "Verein und Nationalmannschaft zusammen. Mischt sehr "
                    "unterschiedliche Wettbewerbsniveaus.",
}

# Welche league.type-Werte gehoeren zu welchem Scope
_SCOPE_TYPES = {
    SCOPE_CLUB_ALL: ("league", "cup"),
    SCOPE_LEAGUE:   ("league",),
    SCOPE_NATIONAL: ("international",),
    SCOPE_ALL:      ("league", "cup", "international"),
}


def _infer_comp_type(league):
    """
    Leitet den Wettbewerbstyp aus Liga-ID und Name ab, wenn API-Sports
    kein league.type-Feld liefert (bekanntes Verhalten beim Pro-Plan).

    Rueckgabe: "league", "cup" oder "international".

    Reihenfolge der Heuristiken:
      1. Bekannte Liga-ID -> "league" (sicher: unsere fuenf Vergleichsligen
         und alle anderen in LEAGUE_IDS eingetragenen Ligen)
      2. Bekannte Cup-ID (CL=2, EL=3, ECL=848) -> "cup"
      3. Name enthaelt Nationalmannschafts-Schluesselbegriffe -> "international"
         Ausnahme: "clubs" im Namen -> trotzdem "cup" (Klub-WM, Club Friendlies)
      4. Name enthaelt Cup-Schluesselbegriffe -> "cup"
      5. Alles andere: "cup" (sicherer als verwerfen; Pokal-/Supercup-Namen
         variieren stark je Land und Saison)
    """
    league_id = league.get("id")
    name = (league.get("name") or "").lower()

    # 1. Bekannte Liga-ID
    all_league_ids = set(LEAGUE_IDS.values())
    if league_id in all_league_ids:
        # Sonderfaelle: CL und EL sind in LEAGUE_IDS, aber Cups
        if league_id in _KNOWN_CUP_IDS:
            return "cup"
        return "league"

    # 2. Bekannte Cup-ID
    if league_id in _KNOWN_CUP_IDS:
        return "cup"

    # 3. Nationalmannschaft (Name-basiert)
    # "clubs" im Namen schliesst Klub-Freundschaftsspiele aus
    if "clubs" not in name:
        if any(h in name for h in _NATIONAL_NAME_HINTS):
            return "international"

    # 4. Cup-Name
    if any(h in name for h in _CUP_NAME_HINTS):
        return "cup"

    # 5. Unbekannt -> Cup (nicht verwerfen)
    return "cup"


# Bekannte Cup-IDs (Champions League, Europa League, Conference League)
_KNOWN_CUP_IDS = {2, 3, 848}

# Schluesselbegriffe fuer Nationalmannschaftswettbewerbe im Liganaamen
_NATIONAL_NAME_HINTS = (
    "friendlies",
    "world cup qualifying",
    "world cup",
    "european championship",
    "euro championship",
    "nations league",
    "africa cup",
    "copa america",
    "gold cup",
    "asian cup",
    "olympic",
    "afcon",
    "concacaf",
)

# Schluesselbegriffe fuer Vereinspokale / Europapokal im Liganamen
_CUP_NAME_HINTS = (
    "champions league",
    "europa league",
    "conference league",
    "super cup",
    "supercup",
    "supercoppa",
    "club world cup",
    "pokal",
    "cup",
    "copa",
    "coppa",
    "coupe",
    "fa cup",
    "league cup",
    "carabao",
    "trophee",
    "trophy",
    "shield",
    "supercopa",
    "superliga",
)


def normalize_scope(scope):
    """Unbekannte oder fehlende Angaben fallen auf den Standard zurueck."""
    scope = (scope or "").strip().lower()
    return scope if scope in COMPETITION_SCOPES else DEFAULT_SCOPE


def entry_matches_scope(entry, scope):
    """
    Prueft, ob ein statistics-Block zum gewaehlten Wettbewerbsumfang gehoert.

    Zusaetzliche Bedingung bei Vereinswettbewerben: der Block muss zu einer
    unserer Vergleichsligen gehoeren ODER ein Pokal-/Europapokalwettbewerb
    sein. Sonst wuerden Spieler aus nicht unterstuetzten Ligen ueber ihre
    Pokalspiele in den Pool rutschen.

    Fehlt league.type (bekanntes Verhalten beim API-Sports Pro-Plan), leitet
    _infer_comp_type() den Typ aus Liga-ID und Liganame ab.
    """
    league = (entry or {}).get("league") or {}
    comp_type = (league.get("type") or "").strip().lower()

    if not comp_type:
        comp_type = _infer_comp_type(league)

    allowed = _SCOPE_TYPES.get(scope, _SCOPE_TYPES[DEFAULT_SCOPE])
    if comp_type not in allowed:
        return False

    # Nationalmannschaft: keine Ligabindung noetig
    if comp_type == "international":
        return True

    # Nationale Liga: nur unsere fuenf Vergleichsligen
    if comp_type == "league":
        return league.get("id") in COMPARE_LEAGUE_IDS

    # Pokal und Europapokal: immer zulaessig, sie haben eigene IDs
    return True


# Felder, die ueber mehrere Eintraege derselben Liga summiert werden.
SUMMABLE_FIELDS = (
    ("games",    "appearences"),
    ("games",    "lineups"),
    ("games",    "minutes"),
    ("shots",    "total"),
    ("shots",    "on"),
    ("goals",    "total"),
    ("goals",    "conceded"),
    ("goals",    "assists"),
    ("goals",    "saves"),
    ("passes",   "total"),
    ("passes",   "key"),
    ("tackles",  "total"),
    ("tackles",  "blocks"),
    ("tackles",  "interceptions"),
    ("duels",    "total"),
    ("duels",    "won"),
    ("dribbles", "attempts"),
    ("dribbles", "success"),
    ("fouls",    "drawn"),
    ("fouls",    "committed"),
    ("cards",    "yellow"),
    ("cards",    "red"),
    ("penalty",  "saved"),
    ("penalty",  "scored"),
    ("penalty",  "missed"),
)

# Felder, die als minutengewichteter Durchschnitt zusammengefasst werden.
# Eine Summe waere hier fachlich falsch (Rating 7.1 + 7.3 ist nicht 14.4).
WEIGHTED_FIELDS = (
    ("games",  "rating"),
    ("passes", "accuracy"),
)


def _season_ttl(season):
    if season < CURRENT_SEASON:
        return TTL_FINISHED_SEASON
    return TTL_CURRENT_SEASON


def _to_number(value):
    """Lokale Zahlkonvertierung. None bleibt None, wird nie zu 0."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().rstrip("%").strip()
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _empty_stats():
    """Leeres Statistikgeruest mit None-Werten, nicht mit Nullen."""
    result = {}
    for section, field in SUMMABLE_FIELDS + WEIGHTED_FIELDS:
        result.setdefault(section, {})[field] = None
    result.setdefault("games", {})["position"] = None
    return result


def pick_primary_league_entries(raw_entries):
    """
    Waehlt die Liga mit den meisten Minuten und gibt deren Eintraege zurueck.

    Reine Funktion ohne API-Zugriff, dadurch direkt testbar.

    Rueckgabe: (entries, league_id, league_code) oder ([], None, None)
    """
    minutes_by_league = {}

    for stats in raw_entries or []:
        league = stats.get("league") or {}
        league_id = league.get("id")
        if league_id not in COMPARE_LEAGUE_IDS:
            continue
        games = stats.get("games") or {}
        minutes = _to_number(games.get("minutes")) or 0.0
        minutes_by_league[league_id] = minutes_by_league.get(league_id, 0.0) + minutes

    if not minutes_by_league:
        return [], None, None

    primary_id = max(minutes_by_league, key=lambda k: minutes_by_league[k])

    entries = [
        stats for stats in raw_entries or []
        if (stats.get("league") or {}).get("id") == primary_id
    ]

    return entries, primary_id, COMPARE_LEAGUE_IDS.get(primary_id)


def select_scope_entries(raw_entries, scope):
    """
    Waehlt alle statistics-Bloecke aus, die zum Wettbewerbsumfang gehoeren.

    Ersetzt pick_primary_league_entries() aus Phase 3. Der Unterschied:
    frueher wurde genau EINE Liga gewaehlt (die mit den meisten Minuten) und
    alles andere verworfen. Jetzt entscheidet der Scope, welche Bloecke
    zusammengefasst werden.

    Rueckgabe: (entries, primary_league_id, primary_league_code)

    Die Primaerliga wird weiterhin bestimmt, aber nur noch fuer die Anzeige
    (Liga-Label im Spielerkopf, Ligafilter im Scatter). Fuer die Zahlen
    zaehlen alle Bloecke des Scopes.
    """
    scope = normalize_scope(scope)

    matching = [
        entry for entry in (raw_entries or [])
        if entry_matches_scope(entry, scope)
    ]

    if not matching:
        return [], None, None

    # Primaerliga = die Vergleichsliga mit den meisten Minuten.
    # Bei "nur Nationalmannschaft" gibt es keine, das ist in Ordnung.
    minutes_by_league = {}
    for entry in matching:
        league = entry.get("league") or {}
        league_id = league.get("id")
        if league_id not in COMPARE_LEAGUE_IDS:
            continue
        games = entry.get("games") or {}
        minutes = _to_number(games.get("minutes")) or 0.0
        minutes_by_league[league_id] = minutes_by_league.get(league_id, 0.0) + minutes

    if minutes_by_league:
        primary_id = max(minutes_by_league, key=lambda k: minutes_by_league[k])
        return matching, primary_id, COMPARE_LEAGUE_IDS.get(primary_id)

    return matching, None, None


def describe_scope_entries(entries):
    """
    Fasst zusammen, aus welchen Wettbewerben die Zahlen stammen.

    Das UI muss dem Nutzer zeigen koennen, worauf ein Wert beruht -
    besonders bei kleinen Stichproben wie Laenderspielen.
    """
    result = []
    for entry in entries or []:
        league = entry.get("league") or {}
        games = entry.get("games") or {}
        minutes = _to_number(games.get("minutes")) or 0
        result.append({
            "league_id": league.get("id"),
            "name": league.get("name"),
            "type": (league.get("type") or "").lower(),
            "country": league.get("country"),
            "minutes": int(minutes),
            "appearances": _to_number(games.get("appearences")) or 0,
        })
    # Nach Einsatzzeit sortiert: der wichtigste Wettbewerb zuerst
    result.sort(key=lambda item: -item["minutes"])
    return result


def aggregate_statistics(entries):
    """
    Fasst mehrere statistics-Bloecke derselben Liga zu einem Datensatz zusammen.

    Reine Funktion ohne API-Zugriff.

    None-Behandlung: Ein Feld bleibt None, wenn KEIN Eintrag einen Wert
    liefert. Sobald mindestens ein Eintrag eine Zahl hat, wird ueber die
    bekannten Werte summiert. So wird "unbekannt" nie zu "null".
    """
    result = _empty_stats()

    if not entries:
        return result

    # --- summierbare Felder ---
    for section, field in SUMMABLE_FIELDS:
        total = None
        for stats in entries:
            value = _to_number((stats.get(section) or {}).get(field))
            if value is None:
                continue
            total = value if total is None else total + value
        result[section][field] = None if total is None else int(total)

    # --- minutengewichtete Felder ---
    for section, field in WEIGHTED_FIELDS:
        weighted_sum = 0.0
        weight_total = 0.0
        for stats in entries:
            value = _to_number((stats.get(section) or {}).get(field))
            minutes = _to_number((stats.get("games") or {}).get("minutes")) or 0.0
            if value is None or minutes <= 0:
                continue
            weighted_sum += value * minutes
            weight_total += minutes
        if weight_total > 0:
            result[section][field] = round(weighted_sum / weight_total, 2)
        else:
            result[section][field] = None

    # --- Position aus dem Eintrag mit den meisten Minuten ---
    best_entry = None
    best_minutes = -1.0
    for stats in entries:
        minutes = _to_number((stats.get("games") or {}).get("minutes")) or 0.0
        if minutes > best_minutes:
            best_minutes = minutes
            best_entry = stats

    if best_entry is not None:
        position = (best_entry.get("games") or {}).get("position")
        result["games"]["position"] = position if position in POSITION_GROUPS else None

    return result


def build_player_profile(raw_entry, season, scope=None):
    """
    Baut aus einer rohen /players-Antwort ein vollstaendiges Spielerprofil.

    scope bestimmt, welche Wettbewerbe in die Zahlen einfliessen.
    Ohne Angabe gilt DEFAULT_SCOPE (alle Vereinswettbewerbe).

    Reine Funktion ohne API-Zugriff, dadurch testbar.
    """
    entry = raw_entry or {}
    player = entry.get("player") or {}
    scope = normalize_scope(scope)

    entries, league_id, league_code = select_scope_entries(entry.get("statistics"), scope)
    stats = aggregate_statistics(entries)

    # Verein aus dem Eintrag mit den meisten Minuten derselben Liga
    team_name = None
    team_logo = None
    best_minutes = -1.0
    for item in entries:
        minutes = _to_number((item.get("games") or {}).get("minutes")) or 0.0
        if minutes > best_minutes:
            best_minutes = minutes
            team = item.get("team") or {}
            team_name = team.get("name")
            team_logo = team.get("logo")

    birth = player.get("birth") or {}

    return {
        "player_id": player.get("id"),
        "name": player.get("name"),
        "firstname": player.get("firstname"),
        "lastname": player.get("lastname"),
        "photo": player.get("photo"),
        "age": player.get("age"),
        "nationality": player.get("nationality"),
        "height": player.get("height"),
        "weight": player.get("weight"),
        "birth_date": birth.get("date"),

        "season": season,
        "league_code": league_code,
        "league_id": league_id,
        "league_label": COMPARE_LEAGUE_LABELS.get(league_code),
        "team_name": team_name,
        "team_logo": team_logo,

        "position": stats["games"].get("position"),
        "minutes": stats["games"].get("minutes"),

        # Rohstruktur bleibt erhalten, damit compute_metric() darauf arbeiten kann
        "stats": stats,

        # Welcher Wettbewerbsumfang zugrunde liegt und woraus er besteht.
        # Das UI braucht beides: den Namen fuer die Ueberschrift, die Liste
        # fuer die Transparenz bei kleinen Stichproben (Laenderspiele).
        "scope": scope,
        "scope_label": SCOPE_LABELS.get(scope),
        "competitions": describe_scope_entries(entries),
        "competition_count": len(entries),

        # data_available = True bedeutet: der Spieler hat in einer unserer
        # fuenf Vergleichsligen gespielt (für club_all/league-Scopes).
        # Nur Cup-Minuten genuegen nicht - ein reiner CL-Spieler ohne
        # Bundesliga-/Premier-League-etc.-Einsatz ist fuer den Pool
        # nicht vergleichbar, weil der Referenzpool aus Ligaspielern besteht.
        # Fuer national-/all-Scopes gilt diese Einschraenkung nicht.
        "data_available": bool(entries) and (
            league_code is not None
            or scope in (SCOPE_NATIONAL, SCOPE_ALL)
        ),
    }


def get_player_season_raw(player_id, season, throttle_seconds=0.0):
    """
    Rohe /players?id=&season=-Antwort eines Spielers, mit ALLEN Wettbewerben.

    Genau EIN API-Request pro Spieler und Saison, danach dauerhaft aus dem
    Disk-Cache. Der Cache-Key enthaelt bewusst KEINEN Scope: gecacht wird die
    vollstaendige Rohantwort (Liga, Pokal, Champions/Europa/Conference League,
    Supercup, Nationalmannschaft). Ein Wechsel des Wettbewerbsumfangs kostet
    dadurch keinen einzigen zusaetzlichen Request.

    Genau diese eine Funktion ist ab jetzt die gemeinsame Datenquelle von
    Radar UND Player-Pool. Dadurch koennen Radar, Scatter und Perzentile
    nicht mehr auseinanderlaufen: Sie beruhen alle auf derselben Rohantwort.

    throttle_seconds: Pause NACH einem echten Netzabruf. Sie greift nur beim
    Cache-Miss (der loader laeuft nur dann), damit der Massenimport das
    Sekundenlimit der API nicht reisst. Ein Cache-Hit wartet nie.

    Rueckgabe: der erste Eintrag der Rohantwort (dict mit "player" und
    "statistics") oder None, wenn API-Sports fuer die Saison nichts liefert.
    """
    if not player_id:
        raise ApisportsUnavailable("player_id fehlt")

    def loader():
        result = _get("players", params={"id": player_id, "season": season})
        # Nur nach einem tatsaechlichen Netzabruf drosseln (loader laeuft
        # ausschliesslich beim Cache-Miss).
        if throttle_seconds:
            time.sleep(throttle_seconds)
        return result

    raw = disk_cached_call(
        key=f"apisports:playerprofile:{player_id}:{season}",
        ttl_seconds=_season_ttl(season),
        loader=loader,
        source="api-sports",
    )

    return raw[0] if raw else None


def get_player_season_profile(player_id, season, scope=None):
    """
    Vollstaendiges Spielerprofil einer Saison fuer einen Wettbewerbsumfang.

    Duenne Huelle um get_player_season_raw(): holt die vollstaendige
    Rohantwort (ein Request, danach Cache) und aggregiert sie fuer den
    gewaehlten Scope. Radar und Pool teilen sich dadurch dieselbe Quelle.
    """
    raw_entry = get_player_season_raw(player_id, season)

    if not raw_entry:
        return build_player_profile({}, season, scope=scope)

    return build_player_profile(raw_entry, season, scope=scope)


def compute_player_metrics(profile, metric_keys):
    """
    Berechnet eine Liste von Kennzahlen fuer ein Spielerprofil.

    Rueckgabe: dict metric_key -> Zahl oder None.
    Ein None bedeutet immer "nicht bekannt", niemals "null Ereignisse".
    """
    stats = profile.get("stats") or {}
    minutes = profile.get("minutes")

    values = {}
    for key in metric_keys:
        values[key] = compute_metric(key, stats, minutes)
    return values


def _player_percentiles(profile, values, snapshot):
    """
    Perzentile eines einzelnen Spielers, immer gegen SEINE Positionsgruppe.

    Auch im allgemeinen Vergleich bleibt das so: die Tore eines Stuermers
    werden an Stuermern gemessen, die eines Aussenverteidigers an
    Verteidigern. Beide gegen dieselbe Gruppe zu messen waere unfair.

    Kein Perzentil gibt es, wenn:
        - kein Snapshot vorliegt,
        - der Spieler keine erkannte Position hat,
        - seine Einsatzzeit unter der Mindestgrenze des Pools liegt.

    Der dritte Fall ist wichtig: Ein Spieler mit 120 Minuten waere selbst
    nicht im Referenzpool. Ihn trotzdem einzuordnen wuerde eine Belastbarkeit
    vortaeuschen, die seine Stichprobe nicht hergibt.
    """
    empty = {key: None for key in values}

    if not snapshot:
        return empty, None

    position = profile.get("position")
    if position not in POSITION_GROUPS:
        return empty, None

    minutes = profile.get("minutes") or 0
    min_minutes = snapshot.get("min_minutes") or 0
    if minutes < min_minutes:
        return empty, "below_min_minutes"

    # Der Spielerwert wurde fuer profile["scope"] aggregiert. Das Perzentil
    # MUSS gegen die Verteilung desselben Scopes gemessen werden, sonst
    # verglichen wir z. B. club_all-Werte gegen eine reine Ligaverteilung.
    scope = profile.get("scope")
    return percentiles_for_player(snapshot, position, values, scope=scope), None


def build_comparison(profile_a, profile_b, snapshot=None, snapshot_b=None,
                     force_general=False):
    """
    Baut das Vergleichsobjekt fuer zwei Spielerprofile.

    Zwei Modi:
        "position" - beide Spieler in derselben Positionsgruppe.
                     Radar mit den positionsspezifischen Kennzahlen.
        "general"  - unterschiedliche Positionsgruppen.
                     Radar mit dem General-Profil: nur Kennzahlen, die fuer
                     jeden Spieler dieselbe Bedeutung haben, alle pro 90
                     Minuten oder als Quote. Das Radar verschwindet nie,
                     aber das UI muss den Modus deutlich benennen.

    snapshot:   Perzentil-Snapshot fuer Spieler A (siehe percentile_engine).
    snapshot_b: Perzentil-Snapshot fuer Spieler B. Fehlt er, wird snapshot
                fuer beide verwendet.

                Zwei getrennte Snapshots sind noetig, weil ein Vergleich
                ueber Saisongrenzen erlaubt ist ("Musiala 2023/24 gegen
                Musiala 2025/26"). Jeder Spieler muss dann gegen den Pool
                SEINER Saison gemessen werden. Ihn gegen einen fremden
                Jahrgang einzuordnen waere schlicht falsch.

    force_general: erzwingt das General-Profil, auch wenn beide Spieler
                dieselbe Position haben. Wird vom freien Vergleichsmodus
                gesetzt.

    Fehlt ein Snapshot, liefert FootSim ehrliche Rohwerte und meldet
    percentiles_available = False. Es werden niemals Perzentile geschaetzt
    oder aus einem unvollstaendigen Pool berechnet.
    """
    if snapshot_b is None:
        snapshot_b = snapshot
    position_a = profile_a.get("position")
    position_b = profile_b.get("position")

    # force_general kommt aus dem freien Vergleichsmodus der Oberflaeche.
    # Dort waehlt der Nutzer bewusst positionsuebergreifend - dann duerfen
    # auch zwei zufaellig gleiche Positionen kein positionsspezifisches
    # Radar erzeugen, sonst wechselt die Darstellung ohne erkennbaren Grund.
    comparable = (
        not force_general
        and position_a is not None
        and position_a == position_b
        and position_a in POSITION_GROUPS
    )

    if comparable:
        mode = "position"
        metric_keys = metrics_for_position(position_a)
    else:
        mode = "general"
        metric_keys = list(GENERAL_METRICS)

    values_a = compute_player_metrics(profile_a, metric_keys)
    values_b = compute_player_metrics(profile_b, metric_keys)

    percentiles_a, blocked_a = _player_percentiles(profile_a, values_a, snapshot)
    percentiles_b, blocked_b = _player_percentiles(profile_b, values_b, snapshot_b)

    has_percentiles = any(v is not None for v in percentiles_a.values()) \
        or any(v is not None for v in percentiles_b.values())

    metrics = []
    for key in metric_keys:
        meta = describe_metric(key)
        if meta is None:
            continue
        metrics.append({
            **meta,
            "value_a": values_a.get(key),
            "value_b": values_b.get(key),
            "percentile_a": percentiles_a.get(key),
            "percentile_b": percentiles_b.get(key),
        })

    return {
        "mode": mode,
        "position": position_a if comparable else None,
        "position_a": position_a,
        "position_b": position_b,
        "metrics": metrics,
        # Radar ist in BEIDEN Modi aktiv. Im general-Modus zeigt es das
        # positionsuebergreifende Profil. Das Frontend muss nur noch den
        # Modus beschriften, nicht selbst entscheiden ob gezeichnet wird.
        "radar_enabled": True,
        # Welches Profil dem Radar zugrunde liegt: eine der vier Positionen
        # oder POSITION_GENERAL. Ermoeglicht dem UI die richtige Ueberschrift.
        "radar_profile": position_a if comparable else POSITION_GENERAL,
        "radar_profile_label": POSITION_LABELS.get(
            position_a if comparable else POSITION_GENERAL
        ),

        "percentiles_available": has_percentiles,
        "percentile_pool_complete": (
            is_snapshot_complete(snapshot) and is_snapshot_complete(snapshot_b)
        ),
        # Erklaertext je Spieler: ohne Angabe der Vergleichsgruppe
        # ist ein Perzentil wertlos. Die Gruppengroesse bezieht sich auf
        # den Wettbewerbsumfang des jeweiligen Spielers.
        "pool_a": describe_pool(snapshot, position_a, scope=profile_a.get("scope")),
        "pool_b": describe_pool(snapshot_b, position_b, scope=profile_b.get("scope")),
        # "below_min_minutes", falls die Einsatzzeit fuer eine Einordnung
        # nicht ausreicht. Das UI muss das benennen, nicht verschweigen.
        "percentile_blocked_a": blocked_a,
        "percentile_blocked_b": blocked_b,
    }


# ---------------------------------------------------------------------------
# Spielersuche
# ---------------------------------------------------------------------------

TTL_SEARCH = 60 * 60 * 6      # 6 Stunden
MIN_QUERY_LENGTH = 3          # API-Sports verlangt mindestens 3 Zeichen


def _search_result_from_entry(entry, season):
    """
    Baut einen kompakten Treffer fuer die Suchliste.

    Der Suchtreffer enthaelt bereits alles, was die Trefferliste anzeigen
    muss. Ein zweiter Statistikaufruf ist erst noetig, wenn der Nutzer den
    Spieler tatsaechlich auswaehlt - und selbst der kommt dann aus dem
    Cache, weil die Suche dieselbe API-Antwort erzeugt hat.
    """
    profile = build_player_profile(entry, season)

    return {
        "player_id": profile["player_id"],
        "name": profile["name"],
        "photo": profile["photo"],
        "age": profile["age"],
        "nationality": profile["nationality"],
        "season": season,
        "team_name": profile["team_name"],
        "team_logo": profile["team_logo"],
        "league_code": profile["league_code"],
        "league_label": profile["league_label"],
        "position": profile["position"],
        "position_label": POSITION_LABELS.get(profile["position"]),
        "minutes": profile["minutes"],
        # False bedeutet: Spieler hat in dieser Saison in keiner der fuenf
        # Vergleichsligen gespielt. Er wird trotzdem angezeigt, aber als
        # nicht auswaehlbar markiert. Ihn stillschweigend wegzulassen waere
        # verwirrend ("warum finde ich den nicht?").
        "comparable": profile["data_available"],
    }


def search_players(query, season):
    """
    Sucht Spieler nach Namensbestandteil fuer eine bestimmte Saison.

    API-Sports v3 verlangt bei /players?search= zwingend auch einen
    league- oder team-Parameter. Deshalb wird die Suche fuer jede der
    fuenf Vergleichsligen separat abgeschickt und die Ergebnisse werden
    zusammengefuehrt.

    Je Liga ein API-Request, gecacht 6 Stunden. Dieselbe Suche kostet
    beim ersten Aufruf 5 Requests (alle Ligen), danach 0 (alles im Cache).

    Der Suchbegriff wird normalisiert, damit "Kane", "kane " und "KANE"
    denselben Cache-Eintrag treffen.
    """
    normalized = (query or "").strip().lower()

    if len(normalized) < MIN_QUERY_LENGTH:
        return []

    # Alle Treffer je Liga sammeln. Spieler-ID als Deduplizierungsschluessel:
    # Ein Spieler der in einer Saison den Verein innerhalb derselben Liga
    # gewechselt hat, koennte in mehreren Eintraegen auftauchen.
    seen_ids = set()
    merged = []

    for league_code in COMPARE_LEAGUE_CODES:
        league_id = LEAGUE_IDS.get(league_code)
        if not league_id:
            continue

        def loader(lid=league_id):
            return _get("players", params={
                "search": normalized,
                "season": season,
                "league": lid,
            })

        try:
            raw = disk_cached_call(
                key=f"apisports:playersearch:{normalized}:{season}:{league_code}",
                ttl_seconds=TTL_SEARCH,
                loader=loader,
                source="api-sports",
            )
        except Exception:
            # Eine nicht erreichbare Liga darf die gesamte Suche nicht kippen.
            continue

        for entry in raw or []:
            try:
                player = (entry.get("player") or {})
                pid = player.get("id")
                if pid in seen_ids:
                    continue
                seen_ids.add(pid)
                merged.append(_search_result_from_entry(entry, season))
            except Exception:
                continue

    # Vergleichbare Spieler zuerst, danach nach Einsatzzeit.
    merged.sort(
        key=lambda item: (
            0 if item["comparable"] else 1,
            -(item["minutes"] or 0),
        )
    )

    return merged
