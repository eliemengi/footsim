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
    normalize_position,
    POSITION_GENERAL,
    POSITION_LABELS,
    compute_metric,
    metrics_for_position,
    describe_metric,
    GENERAL_METRICS,
)
from src.data.percentile_engine import (
    DEFAULT_MIN_MINUTES,
    percentiles_for_player,
    describe_pool,
    is_snapshot_complete,
    is_snapshot_usable,
    position_median,
    stabilize,
    current_weight,
    PROVISIONAL_BELOW_MINUTES,
)
from src.data.national_competitions import TOURNAMENT_SCOPE_LEAGUE_IDS
from src.data import competition_taxonomy as taxonomy
from src.data import player_names


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

#: Welche Wettbewerbskategorien in "Alle Vereinswettbewerbe" zaehlen.
#:
#: Genau die Pflichtspiele: Liga, nationaler Pokal, nationaler Supercup,
#: Europapokal, UEFA-Supercup und Klub-WM.
#:
#: Klubfreundschaftsspiele (league.id 667, "Friendlies Clubs", 2.723
#: Bloecke im lokalen Cache) sind bewusst NICHT dabei. Sie zaehlten
#: vorher mit, weil die Namensheuristik das Wort "Cup" nicht fand und auf
#: "cup" als sichere Voreinstellung zurueckfiel. Ein Testspiel gegen einen
#: Viertligisten mit halber Reservemannschaft verwaessert aber jede
#: Pro-90-Kennzahl und jedes Perzentil.
#:
#: Laenderspiel-Testspiele (league.id 10) bleiben davon unberuehrt: Sie
#: gehoeren in den Nationalmannschafts-Scope und werden dort weiterhin
#: nach der bestehenden Semantik gefuehrt.
_CLUB_SCOPE_CATEGORIES = frozenset(taxonomy.CLUB_COMPETITIVE)

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

    Die Einordnung kommt seit der Datenreparatur aus
    src/data/competition_taxonomy.py. Vorher wurde sie hier aus Liga-ID und
    Name erraten, mit einem nachweisbaren Fehlurteil: Supercups stehen in
    apisports_api.LEAGUE_IDS (weil man sie abrufen wollte, nicht weil sie
    Ligen waeren) und galten deshalb als "league". Da sie nicht zu den fuenf
    Vergleichsligen gehoeren, fielen sie anschliessend aus club_all heraus -
    aber nur die drei dort eingetragenen (Deutschland, England, UEFA). Die
    spanische, italienische und franzoesische Variante rutschte ueber die
    Namensheuristik als "cup" hinein. Sechs gleichartige Wettbewerbe, zwei
    verschiedene Ergebnisse.

    Wettbewerbsscharfe Scopes (cl, euro, world_cup) entscheiden weiterhin
    ALLEIN ueber die league.id. Die ID ist eindeutig; eine zusaetzliche
    Typpruefung koennte den Scope nur faelschlich leeren.
    """
    league = (entry or {}).get("league") or {}

    exact_ids = _SCOPE_EXACT_LEAGUE_IDS.get(scope)
    if exact_ids is not None:
        return league.get("id") in exact_ids

    kategorie = taxonomy.classify(league)

    if scope == SCOPE_LEAGUE:
        # Reiner Ligascope: nur die fuenf Vergleichsligen. Ein Supercup
        # gehoert ausdruecklich NICHT hierher.
        return (kategorie == taxonomy.DOMESTIC_LEAGUE
                and league.get("id") in COMPARE_LEAGUE_IDS)

    if scope == SCOPE_NATIONAL:
        return kategorie in taxonomy.NATIONAL_CATEGORIES

    vereins_pflichtspiel = kategorie in _CLUB_SCOPE_CATEGORIES
    if vereins_pflichtspiel and kategorie == taxonomy.DOMESTIC_LEAGUE:
        # Eine nationale Liga zaehlt nur, wenn es eine der fuenf ist -
        # sonst rutschten Spieler aus nicht unterstuetzten Ligen ueber
        # ihre Ligaspiele in den Pool.
        vereins_pflichtspiel = league.get("id") in COMPARE_LEAGUE_IDS

    if scope == SCOPE_CLUB_ALL:
        return vereins_pflichtspiel

    if scope == SCOPE_ALL:
        return vereins_pflichtspiel or kategorie in taxonomy.NATIONAL_CATEGORIES

    return vereins_pflichtspiel


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
        # Zentral normalisieren statt nur pruefen. Vorher fiel hier jede
        # Providervariante heraus - "Forward" ergab position=None, und daran
        # haengt das GESAMTE Radar (_player_percentiles bricht bei
        # position=None sofort ab). Real betroffen waren damit alle Spieler,
        # die der Anbieter als "Forward" fuehrt, nicht nur einzelne.
        result["games"]["position"] = normalize_position(
            (best_entry.get("games") or {}).get("position"))

    return result


def _scope_has_data(entries, stats, scope, league_code):
    """
    Gibt es fuer diesen Wettbewerbsumfang auswertbare Daten?

    Die Antwort haengt AM SCOPE, nicht an einer Ligabindung:

        league      nur die fuenf Vergleichsligen  -> Ligablock noetig
        club_all    alle Vereinspflichtspiele      -> jeder passende Block
        cl/euro/wm  genau dieser Wettbewerb        -> Block dieses Wettbewerbs
        national    Nationalmannschaft             -> jeder NM-Block
        all         Verein und Nationalmannschaft  -> jeder passende Block

    entries wurde von select_scope_entries() bereits auf den Scope
    gefiltert; Freundschaftsspiele sind ueber die Wettbewerbstaxonomie
    schon vorher ausgeschieden. Es bleibt zu pruefen, ob wirklich Inhalt
    vorliegt - ein Block ohne Einsatzminuten und ohne Einsaetze ist ein
    leerer Eintrag, kein Beleg.
    """
    if not entries:
        return False

    if scope == SCOPE_LEAGUE:
        # Der reine Ligascope verlangt weiterhin einen Ligablock. Ohne ihn
        # gibt es schlicht keine Ligadaten.
        if league_code is None:
            return False

    spiele = (stats or {}).get("games") or {}
    minuten = spiele.get("minutes")
    einsaetze = spiele.get("appearences")

    # Beides None heisst: der Anbieter fuehrt den Wettbewerb, aber ohne
    # Zahlen. Das ist kein auswertbarer Datensatz.
    if minuten is None and einsaetze is None:
        return False

    return (minuten or 0) > 0 or (einsaetze or 0) > 0


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
    team_id = None
    best_minutes = -1.0
    for item in entries:
        minutes = _to_number((item.get("games") or {}).get("minutes")) or 0.0
        if minutes > best_minutes:
            best_minutes = minutes
            team = item.get("team") or {}
            team_name = team.get("name")
            team_logo = team.get("logo")
            # Die stabile Team-ID wird mitgefuehrt, weil Teamnamen als
            # Zaehlgrundlage unbrauchbar sind: Derselbe Verein erscheint
            # je nach Antwort als "Bayern Muenchen" oder "FC Bayern
            # Muenchen", und die Poolpruefung zaehlte ihn dann doppelt.
            team_id = team.get("id")

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
        "team_id": team_id,

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

        # ZWEI GETRENNTE BEGRIFFE - frueher waren sie einer.
        #
        # data_available: Gibt es fuer DIESEN Wettbewerbsumfang echte
        #   Daten? Das ist die Frage, die Anzeige, Radar und Rohwerte
        #   steuert.
        #
        # in_league_cohort: Gehoert der Spieler zur Ligakohorte, aus der
        #   der Perzentilpool gebildet wird? Dafuer braucht es einen Block
        #   aus einer der fuenf Vergleichsligen.
        #
        # WARUM DIE TRENNUNG NOETIG WAR
        # -----------------------------
        # Vorher verlangte data_available fuer club_all zusaetzlich einen
        # Ligablock. Ein Spieler, der zu Saisonbeginn erst im Supercup
        # gespielt hatte, bekam deshalb data_available=False - und
        # get_player_season_profile() ueberschrieb daraufhin seine
        # bereits korrekt aggregierten Minuten mit null.
        #
        # An echten Daten nachgewiesen: Ein Bayern-Spieler hatte in
        # 2026/27 einen Block "league=529 Super Cup, 81 Minuten".
        # entry_matches_scope() liess ihn korrekt zu, aggregate_statistics()
        # rechnete korrekt 81 - und danach stand im Ergebnis 0.
        #
        # Ein Supercup, ein Pokal und ein Europapokalspiel sind
        # Pflichtspiele. Sie zaehlen. Ob der Spieler zusaetzlich fuer die
        # Vergleichskohorte taugt, ist eine andere Frage - und die
        # beantwortet jetzt in_league_cohort.
        "data_available": _scope_has_data(entries, stats, scope, league_code),
        "in_league_cohort": league_code is not None,

        # DER DRITTE BEGRIFF, der bisher fehlte: Wie belastbar ist dieser
        # Stand?
        #
        # data_available beantwortet "gibt es Daten?" mit ja oder nein.
        # Darunter verschwanden aber vier verschiedene Sachverhalte, die
        # am 24.08.2026 alle gleichzeitig auftraten:
        #
        #   Der Spieler hat wirklich wenig gespielt.
        #   Der Anbieter hat den Spielstand noch nicht fertig verbucht.
        #   Der Anbieter kennt den Verein fuer diese Saison noch gar nicht.
        #   Der Spieler stand im Kader, kam aber nicht zum Einsatz.
        #
        # Alle vier sahen fuer die Oberflaeche gleich aus, und in drei von
        # vier Faellen war "keine Einsaetze" schlicht falsch.
        #
        # Der Vermerk aendert KEINEN Wert. Liefert der Anbieter 38
        # Minuten, stehen dort 38 Minuten. Er sagt nur dazu, wie sicher
        # das ist.
        "data_quality": _profile_quality(raw_entry),
    }


def _profile_quality(raw):
    """
    Qualitaetsvermerk zur Rohantwort - additiv, ohne Migration.

    Aeltere Aufrufer, die das Feld nicht kennen, bleiben unberuehrt. Faellt
    die Einstufung aus irgendeinem Grund aus, liefert sie None statt eine
    Ausnahme bis in den Nutzerrequest zu tragen: Ein fehlender Hinweis ist
    aergerlich, eine kaputte Seite ist schlimmer.
    """
    try:
        from src.data.player_data_quality import (
            classify_profile_quality, quality_block,
        )

        zustand, grund = classify_profile_quality(raw)
        return quality_block(zustand, grund)
    except Exception:
        return None


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
        profil = build_player_profile({}, season, scope=scope)
        return apply_no_current_stats(profil, player_id, season)

    profil = build_player_profile(raw_entry, season, scope=scope)

    # Der Anbieter liefert fuer manche Spieler zu Saisonbeginn einen
    # Datensatz OHNE auswertbare Statistik. Dann ist raw_entry nicht leer,
    # das Profil aber trotzdem ohne Leistung - derselbe fachliche Fall.
    if not profil.get("data_available"):
        return apply_no_current_stats(profil, player_id, season)

    return profil


#: Zaehlbare Ereignisse der laufenden Saison. Fehlt der Statistiksatz,
#: sind sie echte Nullen - der Spieler HAT nichts erzielt.
COUNTING_STAT_PATHS = (
    ("games", "appearences"),
    ("games", "lineups"),
    ("games", "minutes"),
    ("goals", "total"),
    ("goals", "assists"),
    ("goals", "conceded"),
    ("goals", "saves"),
    ("shots", "total"),
    ("shots", "on"),
    ("cards", "yellow"),
    ("cards", "red"),
)


def apply_no_current_stats(profile, player_id, season):
    """
    Macht aus "kein Statistiksatz" einen ehrlichen Null-Datensatz.

    Nur fuer Spieler, deren aktuelle Vereinszugehoerigkeit BELEGT ist
    (current_squads.verify_current_team). Ohne Beleg bleibt das Profil
    unveraendert leer - dann wissen wir wirklich nichts ueber ihn.

    Was passiert:
      - zaehlbare Werte (Einsaetze, Minuten, Tore, Assists, Karten) -> 0
      - ratenbasierte Werte bleiben None: "0 Tore pro 90" waere bei null
        Minuten fachlich irrefuehrend, nicht bloss unbekannt
      - Vorjahreszahlen werden NICHT hierher kopiert

    Der Referenzwert fuer die Bewertung kommt getrennt aus dem
    Perzentil-Snapshot - siehe _player_percentiles.
    """
    from src.data.current_squads import verify_current_team

    beleg = verify_current_team(player_id, season)
    if not beleg:
        profile["availability_status"] = "unavailable"
        profile["has_current_stats"] = False
        profile["current_team_verified"] = False
        return profile

    stats = profile.get("stats") or {}
    for gruppe, feld in COUNTING_STAT_PATHS:
        block = stats.setdefault(gruppe, {})
        if isinstance(block, dict) and block.get(feld) is None:
            block[feld] = 0

    profile["stats"] = stats
    profile["minutes"] = 0
    profile["team_name"] = beleg["team_name"]
    profile["team_id"] = beleg["team_id"]
    profile["league_code"] = beleg["league_key"]
    profile["has_current_stats"] = False
    profile["current_team_verified"] = True
    profile["availability_status"] = "no_current_appearance"
    profile["source_type"] = "verified_squad"
    # data_available bleibt False: es gibt keine auswertbare Leistung.
    # Der Vergleich laeuft ueber die Referenz, nicht ueber diese Nullen.
    return profile


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


def _player_percentiles(profile, values, snapshot, baseline_values=None):
    """
    Perzentile eines einzelnen Spielers, immer gegen SEINE Positionsgruppe.

    Auch im allgemeinen Vergleich bleibt das so: die Tore eines Stuermers
    werden an Stuermern gemessen, die eines Aussenverteidigers an
    Verteidigern. Beide gegen dieselbe Gruppe zu messen waere unfair.

    FRUEHE SAISON
    -------------
    Frueher galt hier eine harte Sperre: unter der Mindestminutenzahl des
    Pools (450) gab es ueberhaupt kein Perzentil. Am ersten Spieltag war
    damit kein einziger Spieler vergleichbar - genau dann, wenn das
    Interesse am groessten ist.

    Die Sperre ist durch Regularisierung ersetzt. Gemessen wird nicht der
    rohe Pro-90-Wert, sondern ein zur Referenz gezogener Wert:

        gemessen = aktuell * w + referenz * (1 - w),  w = min/(min + k)

    Ein Tor aus 55 Minuten ergibt so keinen Weltklassewert mehr, bleibt
    aber sichtbar besser als gar kein Treffer. Mit jeder Einsatzminute
    verschiebt sich das Gewicht zur laufenden Saison.

    Die ROHWERTE bleiben davon voellig unberuehrt - stabilisiert wird nur,
    was gegen andere Spieler gemessen wird.

    Kein Perzentil gibt es weiterhin, wenn kein Snapshot vorliegt, der
    Spieler keine erkannte Position hat oder er noch keine Minute
    gespielt hat. Ohne Einsatzzeit gibt es nichts zu bewerten.
    """
    empty = {key: None for key in values}

    if not snapshot:
        return empty, None

    position = profile.get("position")
    if position not in POSITION_GROUPS:
        return empty, None

    minutes = profile.get("minutes") or 0
    if minutes <= 0:
        # Kein Einsatz - es waere unehrlich, daraus eine Leistung abzuleiten.
        return empty, "no_minutes"

    # Der Spielerwert wurde fuer profile["scope"] aggregiert. Das Perzentil
    # MUSS gegen die Verteilung desselben Scopes gemessen werden, sonst
    # verglichen wir z. B. club_all-Werte gegen eine reine Ligaverteilung.
    scope = profile.get("scope")

    gemessen = {}
    for key, wert in values.items():
        referenz = (baseline_values or {}).get(key)
        if referenz is None:
            referenz = position_median(snapshot, position, key, scope=scope)
        gemessen[key] = stabilize(wert, referenz, minutes)

    blocked = "provisional" if minutes < PROVISIONAL_BELOW_MINUTES else None
    return percentiles_for_player(snapshot, position, gemessen, scope=scope), blocked


#: Zustaende, die ein Spielerdatensatz in der laufenden Saison haben kann.
#:
#: current                normale, belastbare Saisonwerte
#: provisional            gespielt, aber unter der Stabilitaetsschwelle
#: no_current_appearance  Verein belegt, aber noch keine Minute
#: unavailable            keine belegbare Zugehoerigkeit - keine Aussage
AVAILABILITY_STATES = ("current", "provisional", "no_current_appearance", "unavailable")


def _availability_status(profile):
    """Leitet den Zustand aus dem Profil ab - eine Stelle, ein Vokabular."""
    vorgegeben = profile.get("availability_status")
    if vorgegeben in AVAILABILITY_STATES:
        return vorgegeben

    if not profile.get("data_available"):
        return "unavailable"

    minuten = profile.get("minutes") or 0
    if minuten <= 0:
        return "no_current_appearance"
    if minuten < PROVISIONAL_BELOW_MINUTES:
        return "provisional"
    return "current"


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
        # Radar ist in beiden Modi moeglich - aber nur, wenn BEIDE Spieler
        # im gewaehlten Wettbewerbsumfang ueberhaupt Daten haben.
        #
        # Vorher stand hier fest True. Hatte einer der beiden keine Daten,
        # entstand ein Radarrahmen mit Achsenbeschriftungen und ohne
        # Inhalt - eine Form, die Vergleichbarkeit behauptet, wo keine
        # ist. Bei zwei Spielern ohne Daten sogar ein voellig leeres
        # Gitter.
        #
        # Fehlende Daten sind eine normale Datenlage, kein Fehler. Sie
        # gehoeren als Hinweis dargestellt, nicht als leere Grafik.
        "radar_enabled": bool(
            (profile_a or {}).get("data_available")
            and (profile_b or {}).get("data_available")
        ),
        # Damit die Oberflaeche einen genauen Hinweis geben kann, WER
        # keine Daten hat - statt eines pauschalen "kein Vergleich".
        "data_available_a": bool((profile_a or {}).get("data_available")),
        "data_available_b": bool((profile_b or {}).get("data_available")),
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
        # Saison der ECHTEN Spielerwerte - nie die des Referenzpools.
        "data_season_a": profile_a.get("season"),
        "data_season_b": profile_b.get("season"),
        # Saison, aus der die Vergleichsverteilung stammt. Kann aelter
        # sein als data_season, wenn die laufende Saison noch keinen
        # brauchbaren Pool hat. Die UI darf beides nicht vermengen.
        "reference_season_a": (snapshot or {}).get("season"),
        "reference_season_b": (snapshot_b or {}).get("season"),
        # Wie belastbar die aktuelle Datenbasis ist.
        "minutes_a": profile_a.get("minutes") or 0,
        "minutes_b": profile_b.get("minutes") or 0,
        "current_weight_a": round(current_weight(profile_a.get("minutes") or 0), 3),
        "current_weight_b": round(current_weight(profile_b.get("minutes") or 0), 3),
        "provisional_a": 0 < (profile_a.get("minutes") or 0) < PROVISIONAL_BELOW_MINUTES,
        "provisional_b": 0 < (profile_b.get("minutes") or 0) < PROVISIONAL_BELOW_MINUTES,

        # GO 1.2: Herkunft und Belegbarkeit des aktuellen Datensatzes.
        #
        # has_current_stats trennt "hat diese Saison noch nichts gespielt"
        # von "wir kennen ihn gar nicht". current_team_verified sagt, ob die
        # Vereinszugehoerigkeit belegt ist oder nur vermutet waere - ohne
        # Beleg gibt FootSim keinen Verein aus.
        "has_current_stats_a": bool(profile_a.get("data_available")),
        "has_current_stats_b": bool(profile_b.get("data_available")),
        "current_team_verified_a": bool(profile_a.get("current_team_verified")),
        "current_team_verified_b": bool(profile_b.get("current_team_verified")),
        "source_type_a": profile_a.get("source_type") or "current_stats",
        "source_type_b": profile_b.get("source_type") or "current_stats",
        "availability_status_a": _availability_status(profile_a),
        "availability_status_b": _availability_status(profile_b),
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
    # Seit der Suchreparatur nur noch eine Weiterleitung: Die
    # massgebliche Fassung steht in src/data/player_names.py, damit
    # Pool, Kaderindex und Live-Suche garantiert dieselbe Vorstellung
    # von "gleicher Name" haben. Der Name bleibt als Weiterleitung
    # erhalten, weil bestehende Aufrufer ihn benutzen.
    return player_names.normalize_name(text)


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
    normalized = player_names.normalize_name(query)
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
        # Zentrale Namenslogik statt reinem Teilstringvergleich: Sie kennt
        # Interpunktion ("L.Diaz") und abgekuerzte Vornamen ("Luis Diaz"
        # gegen den Poolnamen "L. Diaz").
        if not player_names.matches(query, entry.get("name")):
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
    Spielersuche fuer den Radar - ueber ALLE Quellen zusammengefuehrt.

    WAS SICH GEAENDERT HAT
    ----------------------
    Frueher waren die Quellen exklusiv: Sobald der Pool irgendeinen
    Treffer lieferte, wurde zurueckgegeben und keine weitere Quelle mehr
    befragt. Das hat einen ganzen Spielertyp unsichtbar gemacht.

    Nachgewiesen an der Suche nach "diaz" in 2026/27: Der Saisonpool
    enthaelt sechs andere Spieler dieses Namens, also brach die Suche
    dort ab - waehrend der gesuchte Spieler im aktuellen Kaderindex
    stand und nie erreicht wurde. Betroffen war jeder aktuelle
    Kaderspieler, dessen Name auch nur EINEN Pooleintrag trifft.

    KOSTENORDNUNG
    -------------
    Zusammenfuehren heisst nicht "alles immer abfragen". Die beiden
    lokalen Quellen kosten nichts und werden deshalb IMMER gelesen:

        1. Saisonpool          Datei
        2. Aktueller Kader     ein Index, nach dem Bau aus dem Cache

    Die beiden teuren Quellen kosten Requests und laufen nur, wenn die
    lokalen nichts gefunden haben:

        3. Live-Suche beim Anbieter
        4. Historische Kandidaten mit Kaderpruefung

    Damit verschwindet die Verdeckung, ohne dass eine Suche teurer wird
    als vorher.

    Die Zusammenfuehrung erfolgt ueber die stabile player_id
    (player_names.dedupe_by_id). Gleichnamige Spieler bleiben getrennte
    Personen - zusammengefuehrt wird nur, was dieselbe ID hat.
    """
    gefunden = []

    for eintrag in search_players_in_pool(query, season) or []:
        if isinstance(eintrag, dict):
            eintrag.setdefault("source_type", "pool")
            gefunden.append(eintrag)

    # Aktuelle Kader: lokal, kostenlos nach dem einmaligen Indexbau.
    gefunden.extend(search_current_squads(query, season))

    if gefunden:
        return _rank_search_results(query, gefunden)

    # Ab hier kostet es Requests - deshalb erst, wenn lokal nichts da war.
    if len(player_names.normalize_name(query)) < MIN_QUERY_LENGTH:
        return []

    try:
        live = live_player_search.search_live(query, [season])
    except (ApisportsUnavailable, ApisportsRateLimit):
        # Ein Ausfall der Rueckfallebene darf die Suche nicht schlechter
        # machen, als sie ohne sie waere.
        live = []
    # Nur echte Eintraege uebernehmen. Eine Rueckfallebene darf die Suche
    # nicht zum Absturz bringen, wenn der Anbieter etwas Unerwartetes
    # liefert - dann fehlt eben diese Quelle.
    for eintrag in live or []:
        if isinstance(eintrag, dict):
            eintrag.setdefault("source_type", "live_search")
            gefunden.append(eintrag)

    if not gefunden:
        gefunden.extend(search_verified_without_stats(query, season))

    return _rank_search_results(query, gefunden)


def _rank_search_results(query, eintraege, limit=25):
    """
    Doppelte zusammenfuehren und nach Trefferguete sortieren.

    Die Sortierung ist deterministisch: erst wie gut der Name passt, dann
    Einsatzminuten absteigend, dann Name und player_id. Ohne die letzten
    beiden haenge die Reihenfolge daran, in welcher Reihenfolge die
    Quellen gelesen wurden - und waere von Lauf zu Lauf verschieden.
    """
    eindeutig = player_names.dedupe_by_id(eintraege)
    eindeutig.sort(key=lambda e: player_names.sort_key(query, e))
    return eindeutig[:limit]


def cached_season_profile(player_id, season, scope=DEFAULT_SCOPE):
    """
    Spielerprofil AUS DEM CACHE - ohne jeden Netzabruf.

    Rueckgabe: (profil, herkunft) oder (None, None)

    Wozu das noetig ist: Die Suchergebnisse und das Vergleichsergebnis
    liefen frueher auf verschiedene Datenstaende hinaus. Die Suchkarte
    zeigte Minuten aus der Live-Suche, das Ergebnis rechnete aus dem
    Detailprofil - und beide waren zu verschiedenen Zeitpunkten gecacht.
    Der Nutzer sah dieselbe Person mit zwei verschiedenen Minutenzahlen.

    Diese Funktion loest das an der Wurzel: Die Suche fragt DIESELBE
    Quelle wie der Vergleich, nur ohne sie notfalls nachzuladen. Liegt
    nichts im Cache, gibt es hier nichts - dann bleibt die Suchkarte bei
    ihren Nullwerten, statt eine dritte Wahrheit zu erfinden.

    herkunft traegt den Erfassungszeitpunkt, damit die Antwort spaeter
    sagen kann, wie alt ihr Datenstand ist.
    """
    from src.utils.disk_cache import get_meta, read_entry

    schluessel = f"apisports:playerprofile:{player_id}:{season}"
    eintrag = read_entry(schluessel)
    if not eintrag:
        return None, None

    roh = eintrag.get("payload") or []
    if not roh:
        return None, None

    profil = build_player_profile(roh[0], season, scope=scope)
    meta = get_meta(schluessel) or {}
    herkunft = {
        "source": "apisports:playerprofile",
        "data_as_of": meta.get("fetched_at"),
    }
    return profil, herkunft


def search_current_squads(query, season, limit=25):
    """
    Spieler aus den aktuellen Kadern der fuenf Ligen.

    Liest den lokal gehaltenen Kaderindex (current_squads.squad_index).
    Nach dessen einmaligem Aufbau kostet diese Quelle nichts - deshalb
    wird sie bei JEDER Suche mitgelesen und nicht erst als letzte
    Rueckfallebene.

    Genau das war der Fehler vorher: Als letzte Ebene wurde sie nie
    erreicht, sobald der Saisonpool irgendeinen gleichnamigen Spieler
    lieferte. Ein Neuzugang, der noch keinen Poolstatistiksatz hat, blieb
    dadurch dauerhaft unsichtbar - obwohl das Teamprofil ihn zeigte.

    Die Eintraege tragen ausdruecklich Nullwerte und den Vermerk, dass
    keine Einsaetze vorliegen. Es werden KEINE Vorjahreszahlen
    eingesetzt: Der Spieler stand vielleicht in einer ganz anderen Liga.
    """
    from src.data.current_squads import search_squad_index

    if len(player_names.normalize_name(query)) < MIN_QUERY_LENGTH:
        return []

    # NUR fuer die laufende Saison.
    #
    # Der Index beschreibt den HEUTIGEN Kader. Ihn fuer eine vergangene
    # Saison zu befragen hiesse zu behaupten, ein Spieler habe damals bei
    # seinem heutigen Verein gespielt - genau die Sorte stiller
    # Rueckprojektion, die dieses Projekt an anderer Stelle bereits
    # ausdruecklich verbietet (siehe player_identity: der Spielerpool
    # fuehrt team_name als heutigen Verein und taugt deshalb nicht als
    # historische Kaderzuordnung).
    if season != CURRENT_SEASON:
        return []

    try:
        kandidaten = search_squad_index(query, season, limit=limit)
    except Exception:
        # Diese Quelle ist eine Ergaenzung. Faellt sie aus, ist die Suche
        # so gut wie vorher - aber sie faellt nicht aus.
        return []

    treffer = []
    for eintrag in kandidaten:
        ergebnis = {
            "player_id": eintrag["player_id"],
            "name": eintrag.get("name"),
            "position": eintrag.get("position"),
            "team_name": eintrag.get("team_name"),
            "league_code": eintrag.get("league_code"),
            "league_label": COMPARE_LEAGUE_LABELS.get(eintrag.get("league_code")),
            "season": season,
            "age": eintrag.get("age"),
            "minutes": 0,
            "comparable": True,
            "has_current_stats": False,
            "current_team_verified": True,
            "availability_status": "no_current_appearance",
            "source_type": "current_squad",
            "reference_season": None,
        }

        # Aus DEMSELBEN Cache anreichern, den auch der Vergleich liest.
        # Ohne das zeigte die Suchkarte null Minuten, waehrend das
        # Ergebnis anschliessend echte Pflichtspielminuten auswies -
        # etwa 81 Minuten aus einem Supercup. Zwei Ansichten, zwei
        # Wahrheiten. Kein Netzabruf: Was nicht im Cache liegt, bleibt
        # null.
        profil, herkunft = cached_season_profile(eintrag["player_id"], season)
        if profil and profil.get("data_available"):
            ergebnis["minutes"] = profil.get("minutes") or 0
            ergebnis["position"] = profil.get("position") or ergebnis["position"]
            ergebnis["has_current_stats"] = True
            ergebnis["availability_status"] = (
                "provisional" if (profil.get("minutes") or 0) < DEFAULT_MIN_MINUTES
                else "current")
            ergebnis["data_as_of"] = (herkunft or {}).get("data_as_of")
            ergebnis["data_source"] = (herkunft or {}).get("source")

        treffer.append(ergebnis)
    return treffer


def search_verified_without_stats(query, season, max_candidates=8):
    """
    Findet Spieler, die in dieser Saison noch keinen Statistiksatz haben.

    Kandidaten kommen aus dem letzten nutzbaren HISTORISCHEN Pool. Jeder
    einzelne wird danach gegen den aktuellen Kader geprueft
    (current_squads.verify_current_team). Nur wer dort steht, wird
    ausgegeben - und zwar mit echten Nullwerten fuer die laufende Saison,
    niemals mit den Vorjahreszahlen.

    max_candidates begrenzt die Pruefung: jede kostet einen Request. Bei
    einer breiten Suche wie "mar" waeren sonst hunderte faellig.
    """
    from src.data.current_squads import verify_current_team
    from src.data.percentile_engine import load_usable_snapshot
    from src.data.player_pool import load_all_players

    normalized = _fold_accents(query)
    if len(normalized) < MIN_QUERY_LENGTH:
        return []

    # Woher die Kandidaten stammen duerfen: die letzte Saison mit einem
    # brauchbaren Pool VOR der angefragten.
    _, referenz = load_usable_snapshot(season - 1)
    if referenz is None:
        return []

    kandidaten, _ = load_all_players(referenz, COMPARE_LEAGUE_CODES)

    treffer = []
    geprueft = 0
    gesehen = set()

    for entry in kandidaten:
        if geprueft >= max_candidates:
            break
        if normalized not in _fold_accents(entry.get("name")):
            continue

        pid = entry.get("player_id")
        if pid is None or pid in gesehen:
            continue
        gesehen.add(pid)

        geprueft += 1
        beleg = verify_current_team(pid, season)
        if not beleg:
            # Nicht belegbar: Vereinswechsel, Ligaabgang oder Karriereende.
            # Dann wird er NICHT als aktueller Spieler ausgegeben.
            continue

        result = _search_result_from_pool_entry(entry)
        result["season"] = season
        # Alles, was aus der Vorsaison stammt, wird ueberschrieben.
        result["team_name"] = beleg["team_name"]
        result["league_code"] = beleg["league_key"]
        result["league_label"] = COMPARE_LEAGUE_LABELS.get(beleg["league_key"])
        result["minutes"] = 0
        result["comparable"] = True
        result["has_current_stats"] = False
        result["current_team_verified"] = True
        result["availability_status"] = "no_current_appearance"
        result["source_type"] = "verified_squad"
        result["reference_season"] = referenz
        treffer.append(result)

    # Ohne Einsatzzeit gibt es keine sinnvolle Reihenfolge - alphabetisch.
    treffer.sort(key=lambda item: _fold_accents(item.get("name")))
    return treffer


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


def _canonical_season_year(season_val):
    if not season_val:
        return None
    s = str(season_val)
    parts = s.replace("-", "/").split("/")
    if parts:
        last = parts[-1].strip()
        if last.isdigit() and len(last) == 4:
            return int(last)
    return None

def normalize_trophies(raw_trophies):
    """
    Gruppiert gewonnene Titel nach Wettbewerb.

    Reine Funktion ohne API-Zugriff, dadurch testbar. Nur Eintraege mit
    place == "Winner" zaehlen; Platzierungen wie "2nd Place" werden
    verworfen, nicht als schwaechere Trophaee dargestellt.

    Saisonangaben werden auf das Endjahr normalisiert (z.B. '2022/2023' -> 2023).
    Eintraege ohne ermittelbares Jahr (z.B. season=None) werden ignoriert, da
    diese beim Provider in der Regel undatierte Duplikate von bereits erfassten
    Trophäen darstellen.

    Rueckgabe: absteigend nach Anzahl sortierte Liste von
    {league, country, count, seasons}.
    """
    grouped = {}
    seen = set()

    for entry in raw_trophies or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("place") != TROPHY_WINNER_PLACE:
            continue

        league = entry.get("league")
        if not league:
            continue

        season = entry.get("season")
        canonical_year = _canonical_season_year(season)
        
        # Ignoriere Eintraege ohne Jahr, um Duplikate zu vermeiden
        if not canonical_year:
            continue
            
        identity = (league.strip().lower(), canonical_year)
        if identity in seen:
            continue
        seen.add(identity)

        bucket = grouped.setdefault(
            league, {"country": entry.get("country"), "count": 0, "seasons": []})
        bucket["count"] += 1
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
