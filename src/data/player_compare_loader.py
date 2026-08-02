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

from src.api.apisports_api import (
    _get,
    LEAGUE_IDS,
    CURRENT_SEASON,
    ApisportsUnavailable,
)
from src.utils.disk_cache import disk_cached_call
from src.data.player_metrics import (
    POSITION_GROUPS,
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


def build_player_profile(raw_entry, season):
    """
    Baut aus einer rohen /players-Antwort ein vollstaendiges Spielerprofil.

    Reine Funktion ohne API-Zugriff, dadurch testbar.
    """
    entry = raw_entry or {}
    player = entry.get("player") or {}

    entries, league_id, league_code = pick_primary_league_entries(entry.get("statistics"))
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

        # True, sobald der Spieler in einer der Vergleichsligen gespielt hat
        "data_available": bool(entries),
    }


def get_player_season_profile(player_id, season):
    """
    Vollstaendiges Spielerprofil einer Saison.

    Genau ein API-Request pro Spieler und Saison, danach aus dem Disk-Cache.
    Der Cache-Key ist bewusst NICHT ligaabhaengig: die Antwort enthaelt
    ohnehin alle Wettbewerbe, dadurch profitieren andere Abfragen mit.
    """
    if not player_id:
        raise ApisportsUnavailable("player_id fehlt")

    def loader():
        return _get("players", params={"id": player_id, "season": season})

    raw = disk_cached_call(
        key=f"apisports:playerprofile:{player_id}:{season}",
        ttl_seconds=_season_ttl(season),
        loader=loader,
        source="api-sports",
    )

    if not raw:
        return build_player_profile({}, season)

    return build_player_profile(raw[0], season)


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

    return percentiles_for_player(snapshot, position, values), None


def build_comparison(profile_a, profile_b, snapshot=None, snapshot_b=None):
    """
    Baut das Vergleichsobjekt fuer zwei Spielerprofile.

    Zwei Modi:
        "position" - beide Spieler in derselben Positionsgruppe.
                     Ein gemeinsames Radar ist fachlich zulaessig.
        "general"  - unterschiedliche Positionsgruppen.
                     KEIN gemeinsames Radar, nur universelle Grunddaten,
                     damit kein irrefuehrender Gesamtvergleich entsteht.

    snapshot:   Perzentil-Snapshot fuer Spieler A (siehe percentile_engine).
    snapshot_b: Perzentil-Snapshot fuer Spieler B. Fehlt er, wird snapshot
                fuer beide verwendet.

                Zwei getrennte Snapshots sind noetig, weil ein Vergleich
                ueber Saisongrenzen erlaubt ist ("Musiala 2023/24 gegen
                Musiala 2025/26"). Jeder Spieler muss dann gegen den Pool
                SEINER Saison gemessen werden. Ihn gegen einen fremden
                Jahrgang einzuordnen waere schlicht falsch.

    Fehlt ein Snapshot, liefert FootSim ehrliche Rohwerte und meldet
    percentiles_available = False. Es werden niemals Perzentile geschaetzt
    oder aus einem unvollstaendigen Pool berechnet.
    """
    if snapshot_b is None:
        snapshot_b = snapshot
    position_a = profile_a.get("position")
    position_b = profile_b.get("position")

    comparable = (
        position_a is not None
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
        # Radar nur im Positionsmodus. Das Frontend muss das nicht selbst entscheiden.
        "radar_enabled": comparable,

        "percentiles_available": has_percentiles,
        "percentile_pool_complete": (
            is_snapshot_complete(snapshot) and is_snapshot_complete(snapshot_b)
        ),
        # Erklaertext je Spieler: ohne Angabe der Vergleichsgruppe
        # ist ein Perzentil wertlos.
        "pool_a": describe_pool(snapshot, position_a),
        "pool_b": describe_pool(snapshot_b, position_b),
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

    Die Saison ist Teil der Suche, nicht ein nachgelagerter Filter:
    "Musiala 2023/24" und "Musiala 2024/25" sind zwei verschiedene
    Statistikdatensaetze desselben Spielers.

    Ein API-Request pro Suchbegriff und Saison, danach 6 Stunden aus dem
    Cache. Der Suchbegriff wird normalisiert, damit "Kane", "kane " und
    "KANE" denselben Cache-Eintrag treffen.
    """
    normalized = (query or "").strip().lower()

    if len(normalized) < MIN_QUERY_LENGTH:
        return []

    def loader():
        return _get("players", params={"search": normalized, "season": season})

    raw = disk_cached_call(
        key=f"apisports:playersearch:{normalized}:{season}",
        ttl_seconds=TTL_SEARCH,
        loader=loader,
        source="api-sports",
    )

    results = []
    for entry in raw or []:
        try:
            results.append(_search_result_from_entry(entry, season))
        except Exception:
            # Ein einzelner kaputter Eintrag darf die ganze Suche nicht kippen.
            continue

    # Vergleichbare Spieler zuerst, danach nach Einsatzzeit.
    # Wer mehr gespielt hat, ist in aller Regel der gesuchte Spieler.
    results.sort(
        key=lambda item: (
            0 if item["comparable"] else 1,
            -(item["minutes"] or 0),
        )
    )

    return results
