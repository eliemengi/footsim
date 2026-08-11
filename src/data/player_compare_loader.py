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
    ApisportsRateLimit,
)
from src.utils.disk_cache import disk_cached_call
# Rueckfallebene der Radar-Suche (Block F1.1). Bewusst ein eigenes Modul:
# es kennt weder Pool noch Perzentile und kann sie dadurch nicht beruehren.
from src.data import live_player_search
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
from src.data.national_competitions import TOURNAMENT_SCOPE_LEAGUE_IDS


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

SCOPE_CLUB_ALL  = "club_all"     # Standard: Liga + Pokale + Europapokal
SCOPE_LEAGUE    = "league"       # nur nationale Liga
SCOPE_CL        = "cl"           # ausschliesslich UEFA Champions League
SCOPE_EURO      = "euro"         # ausschliesslich UEFA-Europameisterschaft
SCOPE_WORLD_CUP = "world_cup"    # ausschliesslich FIFA-Weltmeisterschaft
SCOPE_NATIONAL  = "national"     # nur Nationalmannschaft (alle Wettbewerbe)
SCOPE_ALL       = "all"          # Verein und Nationalmannschaft

COMPETITION_SCOPES = (
    SCOPE_CLUB_ALL, SCOPE_LEAGUE, SCOPE_CL,
    SCOPE_EURO, SCOPE_WORLD_CUP,
    SCOPE_NATIONAL, SCOPE_ALL,
)

DEFAULT_SCOPE = SCOPE_CLUB_ALL

SCOPE_LABELS = {
    SCOPE_CLUB_ALL:  "Alle Vereinswettbewerbe",
    SCOPE_LEAGUE:    "Nur Liga",
    SCOPE_CL:        "Champions League",
    SCOPE_EURO:      "Europameisterschaft",
    SCOPE_WORLD_CUP: "Weltmeisterschaft",
    SCOPE_NATIONAL:  "Nur Nationalmannschaft",
    SCOPE_ALL:       "Alle Wettbewerbe",
}

SCOPE_HINTS = {
    SCOPE_CLUB_ALL:  "Liga, nationale Pokale und europäische Wettbewerbe zusammen.",
    SCOPE_LEAGUE:    "Nur die nationale Liga. Der fairste Vergleich, weil alle "
                     "Spieler dieselbe Anzahl Partien und dieselben Gegner haben.",
    SCOPE_CL:        "Nur Champions League. Weniger Partien als eine Ligasaison, "
                     "dafür durchgehend hohes Gegnerniveau.",
    SCOPE_EURO:      "Nur die Endrunde der Europameisterschaft. Ein kurzes "
                     "Turnier – als kleine Stichprobe zu lesen.",
    SCOPE_WORLD_CUP: "Nur die Endrunde der Weltmeisterschaft. Ein kurzes "
                     "Turnier – als kleine Stichprobe zu lesen.",
    SCOPE_NATIONAL:  "Nur Länderspiele. Wenige Partien pro Saison, daher als "
                     "kleine Stichprobe zu lesen.",
    SCOPE_ALL:       "Verein und Nationalmannschaft zusammen. Mischt sehr "
                     "unterschiedliche Wettbewerbsniveaus.",
}

# Welche league.type-Werte gehoeren zu welchem Scope
_SCOPE_TYPES = {
    SCOPE_CLUB_ALL: ("league", "cup"),
    SCOPE_LEAGUE:   ("league",),
    # CL ist bei API-Sports ein "Cup", EM/WM sind "International". Der Typ
    # dient hier nur der Dokumentation - entschieden wird bei allen dreien
    # ueber die exakte ID (siehe _SCOPE_EXACT_LEAGUE_IDS).
    SCOPE_CL:        ("cup",),
    SCOPE_EURO:      ("international",),
    SCOPE_WORLD_CUP: ("international",),
    SCOPE_NATIONAL:  ("international",),
    SCOPE_ALL:       ("league", "cup", "international"),
}

# Scopes, die auf GENAU EINEN Wettbewerb eingegrenzt sind.
#
# Die vier urspruenglichen Scopes sind Typ-Buckets ("alle Cups", "alle
# Laenderspiele"). Ein Scope wie "nur Champions League" laesst sich damit
# nicht ausdruecken: die CL liegt im selben Bucket wie DFB-Pokal, FA Cup,
# Europa League und Conference League. Deshalb dieser zweite, exakte
# Mechanismus - eine Menge erlaubter league.id je Scope.
#
# Bewusst als Tabelle und nicht als if-Kette: jeder weitere turnierscharfe
# Scope braucht nur einen Eintrag, keine neue Verzweigung in
# entry_matches_scope().
#
# EM und WM sind der Grund, warum die Typ-Buckets allein nicht genuegen:
# league_id 4 (EM) und 1 (WM) liegen im selben "international"-Bucket wie
# Nations League (5), saemtliche Qualifikationen (29-37, 960) und
# Friendlies (10). Nur die exakte ID trennt die Endrunde sauber ab.
_SCOPE_EXACT_LEAGUE_IDS = {
    SCOPE_CL:        frozenset({LEAGUE_IDS["cl"]}),
    SCOPE_EURO:      frozenset({TOURNAMENT_SCOPE_LEAGUE_IDS["euro"]}),
    SCOPE_WORLD_CUP: frozenset({TOURNAMENT_SCOPE_LEAGUE_IDS["world_cup"]}),
}

# Scopes, die keine Bindung an eine der fuenf Vergleichsligen verlangen.
# Ein reiner Champions-League-, EM- oder WM-Wert ist auch dann gueltig, wenn
# der Spieler in keiner unserer fuenf Ligen Minuten hat (die Perzentile
# dieser Scopes stammen ohnehin aus dem jeweiligen Wettbewerbspool, nicht
# aus einem Ligapool).
_SCOPES_WITHOUT_LEAGUE_BINDING = (
    SCOPE_CL, SCOPE_EURO, SCOPE_WORLD_CUP, SCOPE_NATIONAL, SCOPE_ALL,
)


def _infer_comp_type(league):
    """
    Leitet den Wettbewerbstyp aus Liga-ID und Name ab, wenn API-Sports
    kein league.type-Feld liefert (bekanntes Verhalten beim Pro-Plan).

    Rueckgabe: "league", "cup" oder "international".

    Reihenfolge der Heuristiken:
      1. Bekannte Liga-ID -> "league" (sicher: unsere fuenf Vergleichsligen
         und alle anderen in LEAGUE_IDS eingetragenen Ligen)
      2. Bekannte Cup-ID (CL=2, EL=3, ECL=848) -> "cup"
      3. Vereinsmarker im Namen (z. B. "club world cup") -> "cup".
         Steht bewusst VOR der Nationalmannschafts-Pruefung, weil
         "Club World Cup" den Begriff "world cup" enthaelt.
      4. Name enthaelt Nationalmannschafts-Schluesselbegriffe -> "international"
      5. Name enthaelt Cup-Schluesselbegriffe -> "cup"
      6. Alles andere: "cup" (sicherer als verwerfen; Pokal-/Supercup-Namen
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

    # 3. Vereinsmarker im Namen schlagen JEDE Nationalmannschafts-Heuristik.
    # Kritischer Fall: "FIFA Club World Cup" enthaelt "world cup" und wuerde
    # sonst faelschlich als international eingestuft. "club" (Singular) genuegt
    # als Marker - frueher wurde nur auf "clubs" (Plural) geprueft, wodurch die
    # Klub-WM durchrutschte. Auch "Friendlies Clubs" wird so korrekt zu cup.
    if any(marker in name for marker in _CLUB_NAME_MARKERS):
        return "cup"

    # 4. Nationalmannschaft (Name-basiert)
    if any(h in name for h in _NATIONAL_NAME_HINTS):
        return "international"

    # 5. Cup-Name
    if any(h in name for h in _CUP_NAME_HINTS):
        return "cup"

    # 6. Unbekannt -> Cup (nicht verwerfen)
    return "cup"


# Bekannte Cup-IDs (Champions League, Europa League, Conference League)
_KNOWN_CUP_IDS = {2, 3, 848}

# Namensmarker, die einen Wettbewerb eindeutig als VEREINSwettbewerb
# ausweisen - auch wenn der Name Nationalmannschafts-Begriffe enthaelt.
# "club world cup" enthaelt "world cup", ist aber ein Vereinswettbewerb und
# muss zu cup (club_all), nicht zu international. Diese Marker werden VOR den
# _NATIONAL_NAME_HINTS geprueft.
_CLUB_NAME_MARKERS = (
    "club world cup",
    "club world",
    "friendlies clubs",
    "club friendlies",
)

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

    Wettbewerbsscharfe Scopes (z. B. "cl") entscheiden ALLEIN ueber die
    league.id. Die ID ist eindeutig; eine zusaetzliche Typpruefung koennte
    den Scope nur faelschlich leeren, falls API-Sports den Typ eines Tages
    abweichend meldet.
    """
    league = (entry or {}).get("league") or {}

    exact_ids = _SCOPE_EXACT_LEAGUE_IDS.get(scope)
    if exact_ids is not None:
        return league.get("id") in exact_ids

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
        # Fuer cl-/national-/all-Scopes gilt diese Einschraenkung nicht:
        # dort ist die Vergleichsgruppe der jeweilige Wettbewerbspool.
        #
        # Fuer den cl-Scope heisst False damit genau eine Sache: der Spieler
        # hat in dieser Saison keinen Champions-League-Einsatz. Es wird
        # NICHT auf Liga- oder Pokaldaten ausgewichen.
        "data_available": bool(entries) and (
            league_code is not None
            or scope in _SCOPES_WITHOUT_LEAGUE_BINDING
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


def get_player_season_raw_enriched(player_id, season, throttle_seconds=0.0):
    """
    Wie get_player_season_raw(), aber ergaenzt die Rohantwort um die
    gespeicherten Nationalmannschaftsbloecke dieser FootSim-Saison.

    Hintergrund: /players?id=&season=<FootSim-Saison> liefert die Vereins-
    UND die in DERSELBEN api-season liegenden NM-Bloecke. Grosse Turniere
    (EM 2024, WM 2026, Copa 2024 ...) liegen aber in ANDEREN api-seasons und
    fehlen deshalb. Der NM-Import (national_import) hat sie wettbewerbsbasiert
    beschafft und je FootSim-Saison abgelegt. Hier werden sie an die
    Rohantwort angehaengt, bevor irgendein Scope aggregiert wird.

    Dadurch gilt fuer JEDEN Konsumenten (Radar wie Pool): dieselbe Rohbasis,
    dieselbe Scope-Aggregation, konsistente vier Modi.

    Deduplizierung: Ein NM-Block, den die id-Antwort bereits enthaelt (gleiche
    league.id), wird nicht doppelt angehaengt.
    """
    base = get_player_season_raw(player_id, season, throttle_seconds=throttle_seconds)

    # Lazy-Import vermeidet jeden Zyklus zwischen den Datenmodulen.
    from src.data.national_import import get_national_blocks
    national_blocks = get_national_blocks(player_id, season)
    if not national_blocks:
        return base

    if not base:
        # Spieler hat keine Vereins-id-Antwort in dieser Saison, aber NM-Daten.
        # (Bei Pool-Spielern selten; dann trotzdem ein valides Geruest bauen.)
        base = {"player": {"id": player_id}, "statistics": []}

    existing = base.get("statistics") or []
    existing_league_ids = {
        (e.get("league") or {}).get("id") for e in existing
    }

    merged = list(existing)
    for block in national_blocks:
        lid = (block.get("league") or {}).get("id")
        if lid in existing_league_ids:
            continue
        merged.append(block)

    # Flache Kopie mit ersetzter statistics-Liste (base nicht mutieren).
    enriched = dict(base)
    enriched["statistics"] = merged
    return enriched


def get_player_season_profile(player_id, season, scope=None):
    """
    Vollstaendiges Spielerprofil einer Saison fuer einen Wettbewerbsumfang.

    Nutzt die um Nationalmannschaftsbloecke angereicherte Rohantwort, damit
    Radar und Pool dieselbe Datenbasis haben. Ein Request fuer die Vereins-
    daten (danach Cache); die NM-Bloecke kommen ohne weiteren Request aus dem
    gespeicherten NM-Import.
    """
    raw_entry = get_player_season_raw_enriched(player_id, season)

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


def _search_result_from_pool_entry(entry):
    """
    Baut einen Suchtreffer aus einem Pool-Eintrag.

    Der Pool-Eintrag (player_pool.build_pool_entry) enthaelt bereits alles,
    was die Trefferliste und der anschliessende Vergleich brauchen:
    player_id, name, position, league_code, age, team_name. Die Label-Felder
    werden aus den vorhandenen Codes abgeleitet - dieselben Maps wie im
    API-Pfad, damit die Anzeige identisch aussieht.

    photo/nationality/team_logo liegen NICHT im Pool. Sie sind reine
    Anzeige-Extras: Das UI blendet das Foto per if-Abfrage aus, wenn keins da
    ist. Der Vergleich braucht sie ohnehin nicht - er laeuft ueber player_id.

    comparable ist bei einem Pool-Spieler immer True: Er ist per Definition
    ein Top-5-Ligen-Spieler mit aggregierten Scope-Daten. Genau das war die
    Bedeutung von comparable im API-Pfad (data_available in club_all).
    """
    league_code = entry.get("league_code")
    position = entry.get("position")

    return {
        "player_id": entry.get("player_id"),
        "name": entry.get("name"),
        "photo": None,                     # nicht im Pool, UI blendet aus
        "age": entry.get("age"),
        "nationality": None,               # nicht im Pool
        "season": None,                    # wird unten gesetzt
        "team_name": entry.get("team_name"),
        "team_logo": None,                 # nicht im Pool
        "league_code": league_code,
        "league_label": COMPARE_LEAGUE_LABELS.get(league_code),
        "position": position,
        "position_label": POSITION_LABELS.get(position),
        "minutes": (entry.get("minutes_by_scope") or {}).get("club_all"),
        # Ein Pool-Spieler ist immer vergleichbar.
        "comparable": True,
    }


def _fold_accents(text):
    """
    Entfernt Akzente/Diakritika fuer die Suche: "Mbappé" -> "mbappe".

    Nutzer tippen Namen ohne Akzente. Die fruehere API-Suche war
    akzent-insensitiv; die Pool-Suche muss das ebenso sein, sonst findet
    "mbappe" den Eintrag "Mbappé" nicht. Reine Standardbibliothek.
    """
    import unicodedata
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    return without_marks.lower().strip()


def search_players_in_pool(query, season):
    """
    Sucht Spieler nach Namensbestandteil im lokalen Player-Pool.

    Dies ist die robuste Datenquelle fuer die Radar-Suche: dieselbe, die auch
    der Scatter nutzt. Kein API-Request, kein Tageslimit, keine sproede
    /players?search=-Logik. Radar und Scatter kennen dadurch zwangslaeufig
    dieselbe Spielermenge.

    Die Suche ist akzent-insensitiv ("mbappe" findet "Mbappé"), damit sie sich
    wie die fruehere API-Suche verhaelt.

    Bindung: Es werden nur Spieler gefunden, fuer die ein Pool der Saison
    importiert wurde. Das ist dieselbe Bindung, die der Scatter schon hat -
    ohne importierten Pool gibt es fuer eine Saison ohnehin keine Scope-Daten
    und keinen Vergleich.

    Rueckgabe: Liste von Suchtreffern, vergleichbare zuerst (hier alle),
    danach nach Einsatzzeit (club_all-Minuten) absteigend.
    """
    normalized = _fold_accents(query)
    if len(normalized) < MIN_QUERY_LENGTH:
        return []

    # Lokaler Import vermeidet einen Modulzyklus (player_pool importiert
    # nichts aus diesem Modul, aber der Import bleibt bewusst lokal und
    # billig - er wird nur bei einer Suche gebraucht).
    from src.data.player_pool import load_all_players

    players, _used = load_all_players(season, COMPARE_LEAGUE_CODES)

    seen_ids = set()
    merged = []
    for entry in players:
        name = _fold_accents(entry.get("name"))
        if normalized not in name:
            continue
        pid = entry.get("player_id")
        if pid in seen_ids:
            continue
        seen_ids.add(pid)
        result = _search_result_from_pool_entry(entry)
        result["season"] = season
        merged.append(result)

    # Nach Einsatzzeit absteigend (alle sind vergleichbar).
    merged.sort(key=lambda item: -(item["minutes"] or 0))
    return merged


def search_players(query, season):
    """
    Spielersuche fuer den Radar.

    ERSTE WAHL bleibt der lokale Player-Pool (search_players_in_pool). Grund
    unveraendert: Die fruehere reine API-Suche (/players?search=&league=) war
    die Ursache von Suchausfaellen ("keine Spieler gefunden"),
    Timing-Effekten ("erst nach erneutem Tippen") und einem Totalausfall bei
    erschoepftem Tageslimit. Der Pool ist lokal, schnell und limitunabhaengig,
    und er definiert zugleich die Vergleichspopulation.

    RUECKFALLEBENE seit Block F1.1: findet der Pool nichts, wird EINMAL live
    beim Anbieter nachgesehen (src/data/live_player_search.py). Damit sind
    auch historische Spieler und Wechsler direkt vergleichbar, die in der
    gewaehlten Saison in einem FootSim-Wettbewerb gespielt haben, aber nicht
    im lokal importierten Pool stehen.

    Ausdruecklich NICHT betroffen: der Pool selbst, die Perzentil-Kohorte und
    die Scatter/Plot-Population. Hier wird nur GESUCHT - es wird nichts in
    den Pool geschrieben und keine Population erweitert. Ein live gefundener
    Spieler erscheint dadurch nie in den Plots.

    Die Reihenfolge ist wichtig: solange der Pool liefert, entsteht kein
    einziger zusaetzlicher Request. Der Rueckfall kostet nur dort etwas, wo
    die Suche vorher schlicht leer blieb.
    """
    pool_results = search_players_in_pool(query, season)
    if pool_results:
        return pool_results

    # Dieselbe Mindestlaenge wie im Pool-Pfad: eine zu kurze Eingabe darf
    # keinen Netzabruf ausloesen (der Pool-Pfad bricht dafuer oben ab).
    if len(_fold_accents(query)) < MIN_QUERY_LENGTH:
        return []

    try:
        return live_player_search.search_live(query, [season])
    except (ApisportsUnavailable, ApisportsRateLimit):
        # Ein Ausfall der Rueckfallebene darf die Suche nicht schlechter
        # machen, als sie ohne sie waere: dann eben kein Treffer.
        return []


# ---------------------------------------------------------------------------
# Erfolge (Block LIVE D2+)
# ---------------------------------------------------------------------------
#
# /trophies?player= liefert laut offizieller API-Football-Dokumentation
# NUR fuer player/players/coach/coachs - NICHT fuer team. Vereinstitel
# ("6x Meister") lassen sich damit nicht ermitteln und werden hier bewusst
# NICHT erfunden oder hardcodiert.
#
# Saisonunabhaengig: anders als get_player_season_profile() gibt es hier
# keinen season-Parameter - die Antwort deckt die gesamte bekannte
# Karriere ab. Deshalb auch ein eigener, langer TTL statt einer der
# beiden bestehenden Saison-TTLs oben: Titel aendern sich extrem selten,
# und ein neuer Titel muss nicht binnen 24 Stunden sichtbar sein.

TTL_PLAYER_TROPHIES = 60 * 60 * 24 * 14   # 14 Tage

# Der Provider liefert "place" u.a. als "Winner" oder "2nd Place" (an
# echten Antworten geprueft). Nur "Winner" ist ein tatsaechlich
# gewonnener Titel - alles andere waere eine falsche Behauptung, wenn
# es als Trophaee gezaehlt wuerde.
TROPHY_WINNER_PLACE = "Winner"


def normalize_trophies(raw_trophies):
    """
    Gruppiert gewonnene Titel nach Wettbewerb.

    Reine Funktion ohne API-Zugriff, dadurch testbar. Nur Eintraege mit
    place == "Winner" zaehlen; Platzierungen wie "2nd Place" werden
    verworfen, nicht als schwaechere Trophaee dargestellt.

    "count" zaehlt JEDEN Winner-Eintrag, auch wenn sein season-Feld
    fehlt - an echten Antworten geprueft: Mbappes achter Ligue-1-Titel
    hat season=None, ist aber ein genauso echter Titel wie die anderen
    sieben. Nur die "seasons"-Liste (fuer eine spaetere aufklappbare
    Saisonhistorie) bleibt zwangslaeufig auf die Eintraege mit
    bekannter Saison beschraenkt - die Zaehlung selbst nicht.

    Rueckgabe: absteigend nach Anzahl sortierte Liste von
    {league, country, count, seasons}.
    """
    grouped = {}

    for entry in raw_trophies or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("place") != TROPHY_WINNER_PLACE:
            continue

        league = entry.get("league")
        if not league:
            continue

        bucket = grouped.setdefault(
            league, {"country": entry.get("country"), "count": 0, "seasons": []})
        bucket["count"] += 1

        season = entry.get("season")
        if season:
            bucket["seasons"].append(season)

    result = [
        {
            "league": league,
            "country": data["country"],
            "count": data["count"],
            "seasons": sorted(data["seasons"]),
        }
        for league, data in grouped.items()
    ]

    result.sort(key=lambda trophy: -trophy["count"])
    return result


def get_player_trophies(player_id, throttle_seconds=0.0):
    """
    Gruppierte Erfolge eines Spielers.

    Ein Request pro Spieler, danach 14 Tage aus dem Disk-Cache - derselbe
    Cache-Mechanismus wie bei den Saisonprofilen, nur mit eigenem,
    laengerem TTL und ohne Saisonbezug im Schluessel.
    """
    if not player_id:
        raise ApisportsUnavailable("player_id fehlt")

    def loader():
        result = _get("trophies", params={"player": player_id})
        if throttle_seconds:
            time.sleep(throttle_seconds)
        return result

    raw = disk_cached_call(
        key=f"apisports:trophies:{player_id}",
        ttl_seconds=TTL_PLAYER_TROPHIES,
        loader=loader,
        source="api-sports",
    )

    return normalize_trophies(raw)
