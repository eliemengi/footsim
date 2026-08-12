"""
Big Games: Beschaffung und Zusammenfuehrung der Spieldaten (Block F1+).

Aufgabe
-------
Verbindet die drei Bausteine zu einem Ergebnis:

    src/data/uefa_coefficients.py   historische Gegnerstaerke (privat)
    src/features/big_games.py       das Modell (rein, ohne Netz)
    src/api/apisports_api.py        die Spieldaten

Ablauf je Spieler und Saison:

    1. In welchen VEREINSwettbewerben hat der Spieler gespielt?
       (eine bereits vorhandene, gecachte Antwort - kein neuer Request)
    2. Alle Spiele dieser Teams in diesen Wettbewerben holen.
    3. Je Spiel Gegner und Phase bestimmen und ENTSCHEIDEN, ob es ein
       Big Game ist - ohne dafuer einen einzigen Request auszugeben.
    4. NUR fuer die qualifizierten Spiele die Einzelspielerwerte holen.
    5. Zusammenfassen.

Schritt 3 vor Schritt 4 ist der entscheidende Punkt fuer das
Request-Budget: ein Spieler hat pro Saison typischerweise 40-60 Spiele,
aber nur eine Handvoll Big Games. Andersherum waere es ein Vielfaches an
Requests fuer Daten, die anschliessend verworfen wuerden.

Vereins- und Nationalfussball
-----------------------------
Die UEFA-spezifische Club-Pipeline bleibt unveraendert in diesem Modul:
Nationalmannschaftsbloecke werden bei ``player_club_engagements`` weiterhin
verworfen. F1+ fuegt daneben einen isolierten nationalen Fixture-Loader ein
(``national_big_games_loader``). Erst am kompatiblen Matchobjekt-Rand werden
beide Quellen ueber die stabile Fixture-ID zusammengefuehrt. Damit bleiben
UEFA- und FIFA-Regeln getrennt, waehrend ein Spieler eine gemeinsame,
chronologische Big-Games-Historie bekommt.

Vereinswechsel
--------------
Der Spieler behaelt seine stabile Player-ID, sein Verein wird je Spiel
aus den Spieldaten bestimmt. Ein Wechsel mitten in der Saison oder
zwischen zwei Saisons eines Mehrjahresvergleichs ergibt sich damit von
selbst - es wird nie "der aktuelle Verein" auf die Vergangenheit
zurueckprojiziert.
"""

from src.api import apisports_api
from src.api.apisports_api import (
    ApisportsUnavailable,
    ApisportsRateLimit,
    CURRENT_SEASON,
)
from src.data import live_player_search
from src.data import national_big_games_loader
from src.data import uefa_coefficients
from src.data.player_compare_loader import (
    get_player_season_raw,
    _infer_comp_type,
)
from src.features import big_games
from src.features import national_big_games
from src.utils.disk_cache import disk_cached_call


# Abgeschlossene Saisons aendern sich nicht mehr - Spielplan und
# Einzelspielerwerte einer Vorsaison sind endgueltig. Die laufende Saison
# bekommt eine kurze TTL, damit neue Spiele zeitnah erscheinen.
TTL_FIXTURES_FINISHED = 60 * 60 * 24 * 30     # 30 Tage
TTL_FIXTURES_CURRENT  = 60 * 60 * 6           # 6 Stunden

# Einzelspielerwerte eines ABGESCHLOSSENEN Spiels aendern sich praktisch
# nie mehr. Ein noch laufendes Spiel ist fuer Big Games ohnehin
# uninteressant (es wird erst nach Abpfiff ausgewertet).
TTL_FIXTURE_PLAYERS = 60 * 60 * 24 * 30       # 30 Tage

# Das fertige Ergebnis je Spieler und Saison. Kurz genug, damit eine
# nachgetragene Partie ankommt, lang genug, dass wiederholte Vergleiche
# desselben Spielers nichts kosten.
TTL_PLAYER_BIG_GAMES_FINISHED = 60 * 60 * 24 * 14   # 14 Tage
TTL_PLAYER_BIG_GAMES_CURRENT  = 60 * 60 * 4         # 4 Stunden

# Nur diese Spielstatus gelten als gespielt. Ein abgesagtes oder
# verschobenes Spiel ist kein Big Game.
_FINISHED_STATUS = frozenset({"FT", "AET", "PEN"})


def _fixtures_ttl(season):
    return TTL_FIXTURES_FINISHED if season < CURRENT_SEASON else TTL_FIXTURES_CURRENT


def _result_ttl(season):
    return (TTL_PLAYER_BIG_GAMES_FINISHED if season < CURRENT_SEASON
            else TTL_PLAYER_BIG_GAMES_CURRENT)


# ---------------------------------------------------------------------------
# Schritt 1: Wo hat der Spieler gespielt?
# ---------------------------------------------------------------------------

def player_club_engagements(player_id, season):
    """
    Alle (team_id, league_id)-Paare eines Spielers in VEREINSwettbewerben.

    Quelle ist dieselbe gecachte /players?id=&season=-Antwort, die auch der
    normale Spielervergleich benutzt (get_player_season_raw) - bei einem
    bereits verglichenen Spieler kostet dieser Schritt null Requests.

    Nationalmannschaftsbloecke werden hier verworfen: F1 ist
    Vereinsfussball.
    """
    raw = get_player_season_raw(player_id, season)
    if not raw:
        return [], None

    player = raw.get("player") or {}
    engagements = []
    seen = set()

    for block in raw.get("statistics") or []:
        if not isinstance(block, dict):
            continue

        league = block.get("league") or {}
        team = block.get("team") or {}

        league_id = league.get("id")
        team_id = team.get("id")
        if league_id is None or team_id is None:
            continue

        # Nur Vereinswettbewerbe. _infer_comp_type() ist die bestehende,
        # getestete Einordnung des Spielervergleichs - bewusst
        # wiederverwendet statt einer zweiten, womoeglich abweichenden.
        if _infer_comp_type(league) == "international":
            continue

        key = (team_id, league_id)
        if key in seen:
            continue
        seen.add(key)

        engagements.append({
            "team_id": team_id,
            "team_name": team.get("name"),
            "team_logo": team.get("logo"),
            "league_id": league_id,
            "league_name": league.get("name"),
        })

    return engagements, player


# ---------------------------------------------------------------------------
# Schritt 2: Spiele holen
# ---------------------------------------------------------------------------

def _team_season_fixtures(team_id, league_id, season):
    """Alle Spiele eines Teams in einem Wettbewerb - gecacht auf der Platte."""
    def loader():
        return apisports_api.get_team_season_fixtures(team_id, league_id, season)

    return disk_cached_call(
        key=f"apisports:team_season_fixtures:{team_id}:{league_id}:{season}",
        ttl_seconds=_fixtures_ttl(season),
        loader=loader,
        source="api-football.com/fixtures",
    )


# ---------------------------------------------------------------------------
# Schritt 3: Ist das ein Big Game?
# ---------------------------------------------------------------------------

def classify_fixture(raw_fixture, own_team_id, season, snapshot):
    """
    Ordnet EIN Spiel aus Sicht eines Teams ein.

    Rein rechnerisch, ohne Netzzugriff: Gegner und Phase stehen bereits in
    der Spielliste. Genau deshalb kann die Zulassung entschieden werden,
    BEVOR fuer ein Spiel Einzelspielerwerte geholt werden.

    Rueckgabe None, wenn das Spiel unbrauchbar oder nicht gespielt ist.
    """
    if not isinstance(raw_fixture, dict):
        return None

    fixture = raw_fixture.get("fixture") or {}
    fixture_id = fixture.get("id")
    if fixture_id is None:
        return None

    status = ((fixture.get("status") or {}).get("short") or "").upper()
    if status not in _FINISHED_STATUS:
        return None

    teams = raw_fixture.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}

    if home.get("id") == own_team_id:
        opponent = away
        is_home = True
    elif away.get("id") == own_team_id:
        opponent = home
        is_home = False
    else:
        return None

    league = raw_fixture.get("league") or {}
    stage = big_games.normalize_round(league.get("round"))
    tier = big_games.competition_tier(league.get("id"))
    importance = big_games.match_importance(stage)

    # Gegnerstaerke IMMER aus dem Snapshot GENAU DIESER Saison. Es gibt
    # bewusst keinen Rueckfall auf eine andere Saison: ein Klub kann 2021
    # europaeische Spitze und 2025 Mittelmass gewesen sein.
    ranking = uefa_coefficients.lookup_team(season, opponent.get("id"))
    rank = ranking["rank"] if ranking else None
    coefficient = ranking["coefficient"] if ranking else None

    strength = big_games.opponent_strength(
        coefficient,
        snapshot.get("min_coefficient"),
        snapshot.get("max_coefficient"),
    )

    opponent_qualified = big_games.is_opponent_qualified(rank)
    importance_qualified = big_games.is_importance_qualified(stage, tier)

    return {
        "fixture_id": fixture_id,
        "date": fixture.get("date"),
        "is_home": is_home,
        "own_team_id": own_team_id,
        "opponent_id": opponent.get("id"),
        "opponent_name": opponent.get("name"),
        "opponent_logo": opponent.get("logo"),
        "league_id": league.get("id"),
        "league_name": league.get("name"),
        "round": league.get("round"),
        "stage": stage,
        "tier": tier,
        "opponent_rank": rank,
        "opponent_coefficient": coefficient,
        "strength": strength,
        "importance": importance,
        "weight": big_games.big_game_weight(strength, importance),
        "opponent_qualified": opponent_qualified,
        "importance_qualified": importance_qualified,
        # ODER-Verknuepfung: der Gegner ODER die Bedeutung genuegt.
        "is_big_game": opponent_qualified or importance_qualified,
        # Der gemeinsame F1+-Matchvertrag braucht die Herkunft fuer die
        # Anzeige. Die Klassifizierung selbst bleibt weiterhin rein UEFA-
        # spezifisch; FIFA-Werte werden niemals in diesen Pfad eingespeist.
        "source": "club",
        "ranking_source": "uefa",
    }


# ---------------------------------------------------------------------------
# Schritt 4: Einzelspielerwerte eines qualifizierten Spiels
# ---------------------------------------------------------------------------

def _fixture_players(fixture_id):
    """Einzelspielerwerte eines Spiels - gecacht, beide Teams in einem Request."""
    def loader():
        return apisports_api.get_fixture_players(fixture_id)

    return disk_cached_call(
        key=f"apisports:fixture_players:{fixture_id}",
        ttl_seconds=TTL_FIXTURE_PLAYERS,
        loader=loader,
        source="api-football.com/fixtures/players",
    )


# In den Einzelspielerwerten steht die Position als Kurzcode (G/D/M/F),
# im uebrigen Projekt dagegen ausgeschrieben (src/data/player_metrics.py,
# POSITION_GROUPS). Die Uebersetzung liegt seit F1.1 in
# live_player_search, damit Suche und Auswertung garantiert dieselbe
# Positionssprache sprechen - zwei Kopien waeren genau die Art von
# Abweichung, die den Positionsfilter stillschweigend leerlaufen laesst.
_normalize_position = live_player_search.normalize_position


def _parse_rating(raw):
    """
    Bewertung als Zahl. None, wenn keine verwertbare vorliegt.

    Werte ausserhalb der Skala 0 bis 10 werden verworfen - dieselbe Regel
    wie in src/api/live_api.py::parse_rating().
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value or not 0.0 <= value <= 10.0:
        return None
    return round(value, 2)


def _extract_player_line(raw_players, player_id):
    """
    Die Statistikzeile GENAU DIESES Spielers aus der Antwort eines Spiels.

    Zugeordnet wird ausschliesslich ueber die Player-ID, nie ueber den
    Namen. Rueckgabe None, wenn der Spieler nicht im Kader stand.
    """
    for team_block in raw_players or []:
        if not isinstance(team_block, dict):
            continue
        for entry in team_block.get("players") or []:
            if not isinstance(entry, dict):
                continue
            player = entry.get("player") or {}
            if player.get("id") != player_id:
                continue

            stats_list = entry.get("statistics") or []
            stats = stats_list[0] if stats_list and isinstance(stats_list[0], dict) else {}

            games = stats.get("games") or {}
            goals = stats.get("goals") or {}
            shots = stats.get("shots") or {}
            passes = stats.get("passes") or {}
            tackles = stats.get("tackles") or {}
            duels = stats.get("duels") or {}
            dribbles = stats.get("dribbles") or {}

            return {
                "minutes": games.get("minutes"),
                # Der Provider liefert die Bewertung als Zeichenkette
                # ("7.5", teils auch "8"). Hier einmal sauber in eine Zahl
                # gewandelt, damit weder das Modell noch das Frontend
                # spaeter parsen muss.
                "rating": _parse_rating(games.get("rating")),
                "position": _normalize_position(games.get("position")),
                "goals": goals.get("total"),
                "assists": goals.get("assists"),
                "saves": goals.get("saves"),
                "goals_conceded": goals.get("conceded"),
                "shots_total": shots.get("total"),
                "shots_on": shots.get("on"),
                "passes_total": passes.get("total"),
                "passes_key": passes.get("key"),
                "tackles": tackles.get("total"),
                "interceptions": tackles.get("interceptions"),
                "duels_total": duels.get("total"),
                "duels_won": duels.get("won"),
                "dribbles_attempts": dribbles.get("attempts"),
                "dribbles_success": dribbles.get("success"),
            }

    return None


# ---------------------------------------------------------------------------
# Oeffentlicher Einstiegspunkt
# ---------------------------------------------------------------------------

def _season_result(player_id, season):
    """Big Games eines Spielers in EINER Saison. Ohne Cache - siehe Aufrufer."""
    snapshot = uefa_coefficients.load_snapshot(season)

    if not snapshot["available"]:
        return {
            "season": season,
            "season_label": uefa_coefficients.season_label(season),
            "available": False,
            "reason": "no_coefficient_snapshot",
            "provisional": False,
            "matches": [],
        }

    engagements, _player = player_club_engagements(player_id, season)

    candidates = []
    for engagement in engagements:
        try:
            raw_fixtures = _team_season_fixtures(
                engagement["team_id"], engagement["league_id"], season
            )
        except (ApisportsUnavailable, ApisportsRateLimit):
            # Ein einzelner nicht ladbarer Wettbewerb darf die uebrigen
            # nicht mitreissen (gleiche Haltung wie das Match Center in
            # LIVE E): dieser Wettbewerb fehlt dann eben.
            continue

        for raw_fixture in raw_fixtures or []:
            classified = classify_fixture(
                raw_fixture, engagement["team_id"], season, snapshot
            )
            if classified is None or not classified["is_big_game"]:
                continue
            classified["own_team_name"] = engagement["team_name"]
            classified["own_team_logo"] = engagement["team_logo"]
            candidates.append(classified)

    # Erst JETZT - fuer die verbliebene Handvoll Spiele - die
    # Einzelspielerwerte holen.
    matches = []
    for candidate in candidates:
        try:
            raw_players = _fixture_players(candidate["fixture_id"])
        except (ApisportsUnavailable, ApisportsRateLimit):
            continue

        line = _extract_player_line(raw_players, player_id)
        if line is None:
            # Nicht im Kader - das Spiel war ein Big Game, aber nicht
            # seines. Es zaehlt nicht mit.
            continue

        matches.append({**candidate, **line})

    matches.sort(key=lambda m: (m.get("date") or "", m["fixture_id"]))

    return {
        "season": season,
        "season_label": uefa_coefficients.season_label(season),
        "available": True,
        "reason": None,
        "provisional": snapshot["provisional"],
        "matches": matches,
    }


def get_player_big_games_season(player_id, season):
    """Big Games eines Spielers in einer Saison - mit Plattencache."""
    def loader():
        return _season_result(player_id, season)

    return disk_cached_call(
        key=f"biggames:player_season:{player_id}:{season}",
        ttl_seconds=_result_ttl(season),
        loader=loader,
        source="footsim/big-games",
    )


def _combined_season_meta(season, club_result, national_result, matches):
    """Metadaten einer FootSim-Saison nach der F1+-Quellenzusammenfuehrung.

    ``available`` beschreibt die gemeinsame Big-Games-Auswertung: ein
    verifiziertes nationales Spiel bleibt also sichtbar, falls auf einem
    Host ein privater UEFA-Snapshot fehlt. Die quellenspezifischen Zustände
    bleiben separat im Payload, damit eine unvollständige Quelle nicht wie
    vollständige Abdeckung aussieht.
    """
    club_available = bool(club_result.get("available"))
    national_available = bool(national_result.get("available"))
    # Die vorhandene Clubquelle bewahrt den bisherigen F1-Vertrag. Eine
    # nationale Quelle ohne einen einzigen verifizierbaren Spieler-Fixture-
    # Treffer macht eine ansonsten nicht verfuegbare Saison nicht kuenstlich
    # "auswertbar"; liefert sie aber reale Matches, ist die gemeinsame
    # Auswertung natuerlich verfuegbar.
    available = club_available or bool(matches)

    return {
        "season": season,
        "season_label": (club_result.get("season_label")
                         or national_result.get("season_label")
                         or uefa_coefficients.season_label(season)),
        "available": available,
        # Rueckwaertskompatibel: wenn beide Quellen fehlen, bleibt der
        # bisherige Club-Grund die primaere Erklärung.
        "reason": None if available else (
            club_result.get("reason") or national_result.get("reason")
        ),
        "provisional": bool(club_result.get("provisional")) or bool(
            national_result.get("provisional")
        ),
        "match_count": len(matches),
        "club_available": club_available,
        "club_reason": club_result.get("reason"),
        "club_match_count": len(club_result.get("matches") or []),
        "national_available": national_available,
        "national_reason": national_result.get("reason"),
        "national_match_count": len(national_result.get("matches") or []),
        "national_unavailable_targets": (
            national_result.get("unavailable_targets") or []
        ),
        "national_unavailable_ranking_years": (
            national_result.get("unavailable_ranking_years") or []
        ),
    }


def _national_result_or_neutral(player_id, season):
    """Lade die Zusatzquelle, ohne einen Anbieterfehler zum App-Fehler zu machen."""
    try:
        return national_big_games_loader.get_player_national_big_games_season(
            player_id, season
        )
    except (ApisportsUnavailable, ApisportsRateLimit):
        return {
            "season": season,
            "season_label": uefa_coefficients.season_label(season),
            "available": False,
            "reason": "national_provider_unavailable",
            "provisional": False,
            "matches": [],
            "unavailable_targets": [],
            "unavailable_ranking_years": [],
        }


def _get_player_big_games_range(player_id, season_from, season_to):
    """
    Vereinheitlichte Big Games eines Spielers ueber einen Saisonbereich.

    Clubspiele bleiben an ihren historischen UEFA-Snapshot ihrer Saison
    gebunden. Nationale Spiele kommen aus dem getrennten F1+-Loader und
    nutzen ihren FIFA-Jahressnapshot. Beide liefern denselben normalisierten
    Matchvertrag; hier werden sie ausschliesslich ueber die stabile
    API-Football-Fixture-ID dedupliziert, chronologisch sortiert und EINMAL
    gemeinsam aggregiert.
    """
    seasons = []
    all_matches = []

    for season in range(season_from, season_to + 1):
        club_result = get_player_big_games_season(player_id, season)
        national_result = _national_result_or_neutral(player_id, season)
        season_matches = national_big_games.dedupe_fixtures(
            list(club_result.get("matches") or [])
            + list(national_result.get("matches") or [])
        )

        seasons.append(_combined_season_meta(
            season, club_result, national_result, season_matches
        ))
        all_matches.extend(season_matches)

    # Ein Fixture kann im Extremfall in zwei FootSim-Saisons entdeckt werden
    # (z. B. korrigierte Providerdaten). Die finale, periodenweite
    # Deduplizierung ist darum ebenso zwingend wie die pro Saison.
    all_matches = national_big_games.dedupe_fixtures(all_matches)
    all_matches.sort(key=lambda m: (m.get("date") or "", m["fixture_id"]))

    summary = big_games.aggregate_big_games(all_matches)

    return {
        "player_id": player_id,
        "season_from": season_from,
        "season_to": season_to,
        "seasons": seasons,
        "matches": all_matches,
        "summary": summary,
        "has_unavailable_seasons": any(not s["available"] for s in seasons),
        "has_provisional_seasons": any(s["provisional"] for s in seasons),
    }


# Rueckwaertskompatibler Name (wird von Tests und Skripten benutzt).
get_player_big_games = _get_player_big_games_range


# ---------------------------------------------------------------------------
# Positionsgerechte Kennzahlen
# ---------------------------------------------------------------------------
#
# Big Games darf nicht auf "wer hat die meisten Tore geschossen?"
# hinauslaufen. Welche Rohwerte gezeigt werden, richtet sich deshalb nach
# der Position - genau wie im bestehenden Radar (src/data/player_metrics.py,
# RADAR_PROFILES).
#
# Bewusst NUR Kennzahlen, die in den Einzelspielerwerten wirklich stehen
# (an echten Antworten geprueft). Es wird nichts erfunden, damit jede
# Position "symmetrisch" aussieht: fehlt ein Wert, fehlt er.

_METRIC_LABELS = {
    "goals":             "Tore",
    "assists":           "Vorlagen",
    "goal_assists":      "G+A",
    "shots_total":       "Schüsse",
    "shots_on":          "Schüsse aufs Tor",
    "passes_key":        "Schlüsselpässe",
    "passes_total":      "Pässe",
    "tackles":           "Zweikämpfe gewonnen (Tackles)",
    "interceptions":     "Abgefangene Bälle",
    "duels_total":       "Duelle",
    "duels_won":         "Gewonnene Duelle",
    "dribbles_attempts": "Dribblings",
    "dribbles_success":  "Erfolgreiche Dribblings",
    "saves":             "Paraden",
    "goals_conceded":    "Gegentore",
    "minutes":           "Minuten",
    "matches":           "Spiele",
}

_POSITION_METRICS = {
    "Attacker":   ("goals", "assists", "shots_on", "passes_key", "dribbles_success", "duels_won"),
    "Midfielder": ("goals", "assists", "passes_key", "passes_total", "duels_won", "interceptions"),
    "Defender":   ("duels_won", "tackles", "interceptions", "passes_total", "goals", "assists"),
    "Goalkeeper": ("saves", "goals_conceded", "passes_total", "duels_won"),
}

# Ohne bekannte Position: die positionsuebergreifend fairsten Werte.
_GENERAL_METRICS = ("goals", "assists", "passes_key", "duels_won", "minutes")


def _dominant_position(matches):
    """
    Position, auf der der Spieler in seinen Big Games ueberwiegend stand.

    Aus den Spielen selbst abgeleitet, nicht aus einem Saisonprofil: ein
    Spieler kann im Zeitraum die Rolle gewechselt haben, und fuer die
    Auswahl der Kennzahlen zaehlt, was er in DIESEN Spielen war.
    """
    counts = {}
    for match in matches:
        position = match.get("position")
        if position:
            counts[position] = counts.get(position, 0) + (match.get("minutes") or 0)
    if not counts:
        return None
    return max(counts, key=counts.get)


def _player_identity(player_id, seasons_meta, season_from, season_to):
    """
    Name, Foto und aktueller Verein des Spielers - fuer die Anzeige.

    Genommen wird die juengste Saison des Zeitraums, fuer die eine Antwort
    vorliegt: sie traegt das aktuellste Foto. Der VEREIN je Spiel kommt
    dagegen niemals von hier, sondern immer aus dem Spiel selbst.
    """
    for season in range(season_to, season_from - 1, -1):
        try:
            raw = get_player_season_raw(player_id, season)
        except (ApisportsUnavailable, ApisportsRateLimit):
            continue
        if not raw:
            continue
        player = raw.get("player") or {}
        if player.get("id") is not None or player.get("name"):
            return {
                "player_id": player.get("id", player_id),
                "name": player.get("name"),
                "photo": player.get("photo"),
                "nationality": player.get("nationality"),
                "age": player.get("age"),
            }
    return {"player_id": player_id, "name": None, "photo": None,
            "nationality": None, "age": None}


def build_big_games_profile(player_id, season_from, season_to):
    """
    Vollstaendiges Big-Games-Ergebnis eines Spielers fuer die Oberflaeche.

    Trennt ausdruecklich:
        raw      tatsaechlich erzielte Werte - unveraendert, ungewichtet
        context  Gegnerstaerke und Bedeutung
        score    kontextgewichtete Kennzahlen, klar als solche benannt

    Ein Tor bleibt in "raw" ein Tor. Die Gewichtung erscheint ausschliesslich
    in den ausdruecklich gekennzeichneten Feldern.
    """
    data = _get_player_big_games_range(player_id, season_from, season_to)
    matches = data["matches"]

    position = _dominant_position(matches)
    metric_keys = _POSITION_METRICS.get(position, _GENERAL_METRICS)

    raw = data["summary"]["raw"]
    metrics = [
        {"key": key, "label": _METRIC_LABELS.get(key, key), "value": raw.get(key)}
        for key in metric_keys
        if key in raw
    ]

    # Die Spiele fuer die Oberflaeche: nur was dargestellt wird. Der
    # Koeffizient des Gegners bleibt bewusst DRIN (er erklaert die
    # Gewichtung und macht sie nachvollziehbar), die vollstaendige
    # Rangliste verlaesst den Server dagegen nie.
    trimmed = [
        {
            "fixture_id": m["fixture_id"],
            "date": m.get("date"),
            # ``source`` und ``ranking_source`` sind abgeleitete, kleine
            # Anzeige-Metadaten. Die privaten UEFA-/FIFA-Listen selbst
            # verlassen weiterhin niemals den Server.
            "source": m.get("source", "club"),
            "ranking_source": m.get("ranking_source", "uefa"),
            "own_team_name": m.get("own_team_name"),
            "own_team_logo": m.get("own_team_logo"),
            "opponent_name": m.get("opponent_name"),
            "opponent_logo": m.get("opponent_logo"),
            "opponent_rank": m.get("opponent_rank"),
            "league_name": m.get("league_name"),
            "stage": m.get("stage"),
            "is_home": m.get("is_home"),
            "qualification_reasons": m.get("qualification_reasons") or [],
            # Nationale Matchkarten brauchen nur diese bereits abgeleiteten
            # Snapshot-Metadaten, nie das private Ranking selbst.
            "ranking_year": m.get("ranking_year"),
            "ranking_snapshot_date": m.get("ranking_snapshot_date"),
            "ranking_snapshot_status": m.get("ranking_snapshot_status"),
            "ranking_snapshot_available": m.get("ranking_snapshot_available"),
            "weight": round(m.get("weight") or 1.0, 3),
            "minutes": m.get("minutes"),
            "rating": m.get("rating"),
            "goals": m.get("goals"),
            "assists": m.get("assists"),
        }
        for m in matches
    ]

    return {
        **_player_identity(player_id, data["seasons"], season_from, season_to),
        "position": position,
        "season_from": season_from,
        "season_to": season_to,
        "seasons": data["seasons"],
        "has_unavailable_seasons": data["has_unavailable_seasons"],
        "has_provisional_seasons": data["has_provisional_seasons"],
        "summary": data["summary"],
        "metrics": metrics,
        "matches": trimmed,
        "match_count": len(trimmed),
    }


# ---------------------------------------------------------------------------
# Historische Spielersuche (ausdruecklich getrennt vom Top-5-Pool)
# ---------------------------------------------------------------------------

def search_big_games_players(query, season_from, season_to, league_codes=None):
    """
    Sucht einen Spieler im GESAMTEN gewaehlten Big-Games-Zeitraum.

    Frueher wurde nur eine einzelne Saison durchsucht (Block F1). Bei einem
    Zeitraum wie 2024/25-2025/26 fiel dadurch jeder Spieler heraus, der nur
    in der ERSTEN Saison in einem unserer Wettbewerbe stand und danach
    wechselte - obwohl seine Big Games dieser Saison sehr wohl ausgewertet
    werden. Genau dieser Widerspruch wird hier aufgeloest.

    Die Saisons werden absteigend durchsucht, damit ein Spieler mit seinem
    juengsten Verein des Zeitraums angezeigt wird. Zusammengefuehrt wird
    ausschliesslich ueber die stabile Player-ID.

    Befuellt keinen Pool und veraendert keine Vergleichspopulation - die
    eigentliche Arbeit macht src/data/live_player_search.py, das sich der
    normale Radar seit F1.1 als Rueckfallebene teilt.
    """
    if season_from > season_to:
        season_from, season_to = season_to, season_from

    seasons = range(season_to, season_from - 1, -1)

    if league_codes is None:
        return live_player_search.search_live(query, seasons)

    return live_player_search.search_live(query, seasons, league_codes)
