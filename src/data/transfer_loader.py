"""
Transfer-Loader fuer den Liga-zu-Liga-Transfervergleich.

Aufgabe:
    Findet alle Sommertransfers eines Saisonwechsels, die aus einer
    bestimmten Quelliga in eine bestimmte Zielliga fuehrten.

Saisonlogik (zentral definiert, siehe auch SEASON_SEMANTICS unten):
    season=2024 bedeutet bei API-Sports die Saison 2024/25.
    Der betrachtete Transferzeitraum ist der Sommer 2024 (Juni-August).
    Der Quellverein muss in der VORSAISON (season-1, also 2023/24)
    in der Quelliga gespielt haben.
    Der Zielverein muss in der Saison season (2024/25) in der
    Zielliga spielen.

Datenquellen (nur API-Sports):
    /teams?league=X&season=Y   -> Vereine einer Liga in einer Saison
    /transfers?team=X          -> alle Transfers eines Vereins

Rate-Limit-Schutz:
    API-Sports erlaubt nur 100 Requests pro Tag. Deshalb wird jeder
    einzelne API-Aufruf dauerhaft im Disk-Cache abgelegt
    (src/utils/disk_cache.py). Der Disk-Cache ueberlebt Gunicorn-
    Neustarts und gilt fuer alle Worker gemeinsam.
"""

from datetime import date

from src.api.apisports_api import _get, LEAGUE_IDS, CURRENT_SEASON, ApisportsUnavailable
from src.utils.disk_cache import disk_cached_call

# Dokumentation der Saisonsemantik, damit sie nirgendwo doppelt
# interpretiert werden muss.
SEASON_SEMANTICS = (
    "season=N bedeutet Saison N/N+1. Transferfenster: Sommer des Jahres N "
    "(Juni bis August). Quellverein: Liga-Mitglied in Saison N-1. "
    "Zielverein: Liga-Mitglied in Saison N."
)

# Sommerfenster: Monate, die als Sommertransfer gelten.
SUMMER_MONTHS = (6, 7, 8)

# Ligen, die als Quell- oder Zielliga waehlbar sind.
# CL und EL sind Wettbewerbe, keine Transfermaerkte, deshalb hier nicht.
SUPPORTED_LEAGUES = ("bl1", "pl", "pd", "sa", "fl1")

LEAGUE_LABELS = {
    "bl1": "Bundesliga",
    "pl":  "Premier League",
    "pd":  "La Liga",
    "sa":  "Serie A",
    "fl1": "Ligue 1",
}

# Cache-Zeiten in Sekunden.
# Abgeschlossene Saisons aendern sich nicht mehr, daher quasi permanent.
TTL_TEAMS_FINISHED = 60 * 60 * 24 * 365   # 1 Jahr
TTL_TEAMS_CURRENT  = 60 * 60 * 24 * 7     # 7 Tage (Auf-/Abstieg, neue Saison)
TTL_TRANSFERS      = 60 * 60 * 24 * 14    # 14 Tage (Liste waechst nur langsam)


def _teams_ttl(season):
    """Abgeschlossene Saisons duerfen praktisch ewig im Cache liegen."""
    if season < CURRENT_SEASON:
        return TTL_TEAMS_FINISHED
    return TTL_TEAMS_CURRENT


def get_league_teams(league_code, season):
    """
    Alle Vereine einer Liga in einer Saison.

    Rueckgabe: dict {team_id: {"name": ..., "logo": ...}}
    Die IDs sind API-Sports Team-IDs.
    """
    league_id = LEAGUE_IDS.get(league_code)
    if not league_id:
        raise ApisportsUnavailable(f"Unbekannte Liga: {league_code}")

    def loader():
        raw = _get("teams", params={"league": league_id, "season": season})
        teams = {}
        for entry in raw:
            team = entry.get("team") or {}
            team_id = team.get("id")
            if team_id is None:
                continue
            teams[str(team_id)] = {
                "name": team.get("name"),
                "logo": team.get("logo"),
            }
        return teams

    payload = disk_cached_call(
        key=f"apisports:teams:{league_code}:{season}",
        ttl_seconds=_teams_ttl(season),
        loader=loader,
        source="api-sports",
    )
    # JSON-Keys sind immer Strings; fuer Vergleiche normalisieren wir auf int.
    return {int(k): v for k, v in payload.items()}


def get_team_transfers(team_id):
    """
    Alle bekannten Transfers eines Vereins (rohe API-Antwort).

    Der Endpoint /transfers?team=X liefert die komplette Historie
    des Vereins, unabhaengig von der Saison. Gefiltert wird spaeter.
    """
    def loader():
        return _get("transfers", params={"team": team_id})

    return disk_cached_call(
        key=f"apisports:transfers:team:{team_id}",
        ttl_seconds=TTL_TRANSFERS,
        loader=loader,
        source="api-sports",
    )


def parse_transfer_date(raw_date):
    """'2024-07-01' -> date-Objekt oder None bei kaputten Daten."""
    if not raw_date or not isinstance(raw_date, str):
        return None
    try:
        parts = raw_date.split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return None


def is_summer_transfer(transfer_date, season):
    """Liegt das Datum im Sommerfenster des Saisonjahres?"""
    if transfer_date is None:
        return False
    return transfer_date.year == season and transfer_date.month in SUMMER_MONTHS


def filter_summer_transfers(raw_transfer_entries, target_team_ids, source_team_ids,
                            season, source_league, target_league):
    """
    Reine Filterlogik, ohne API-Zugriff (dadurch testbar).

    raw_transfer_entries: Liste im API-Sports-Format:
        {"player": {...}, "transfers": [{"date", "type", "teams": {"in", "out"}}]}
    target_team_ids: set der Team-IDs der Zielliga in der Saison
    source_team_ids: set der Team-IDs der Quelliga in der Vorsaison

    Rueckgabe: Liste normalisierter Transferobjekte.
    Doppelte Eintraege pro Spieler werden dedupliziert; bei mehreren
    Sommerwechseln desselben Spielers zaehlt der SPAETESTE Wechsel in
    die Zielliga (der Spieler beendet den Sommer dort).
    """
    best_per_player = {}

    for entry in raw_transfer_entries or []:
        player = entry.get("player") or {}
        player_id = player.get("id")
        if player_id is None:
            continue

        for move in entry.get("transfers") or []:
            teams = move.get("teams") or {}
            team_in = teams.get("in") or {}
            team_out = teams.get("out") or {}

            in_id = team_in.get("id")
            out_id = team_out.get("id")
            if in_id is None or out_id is None:
                continue

            # Wechsel muss IN einen Zielliga-Verein und AUS einem
            # Quelliga-Verein (Vorsaison) erfolgen.
            if in_id not in target_team_ids:
                continue
            if out_id not in source_team_ids:
                continue

            move_date = parse_transfer_date(move.get("date"))
            if not is_summer_transfer(move_date, season):
                continue

            candidate = {
                "player_id": player_id,
                "player_name": player.get("name"),
                "from_team_id": out_id,
                "from_team_name": team_out.get("name"),
                "from_team_logo": team_out.get("logo"),
                "to_team_id": in_id,
                "to_team_name": team_in.get("name"),
                "to_team_logo": team_in.get("logo"),
                "transfer_date": move_date.isoformat(),
                "transfer_type": move.get("type") or "Unbekannt",
                "source_league": source_league,
                "target_league": target_league,
            }

            existing = best_per_player.get(player_id)
            if existing is None or candidate["transfer_date"] > existing["transfer_date"]:
                best_per_player[player_id] = candidate

    return sorted(best_per_player.values(), key=lambda t: (t["player_name"] or ""))


def load_summer_transfers(source_league, target_league, season):
    """
    Alle Sommertransfers Quelliga -> Zielliga fuer einen Saisonwechsel.

    Ablauf:
        1. Vereine der Zielliga in der Saison holen (1 Request, gecacht)
        2. Vereine der Quelliga in der Vorsaison holen (1 Request, gecacht)
        3. Pro Zielliga-Verein die Transferliste holen (je 1 Request, gecacht)
        4. Filtern und deduplizieren (reine Logik, keine Requests)
    """
    target_teams = get_league_teams(target_league, season)
    source_teams = get_league_teams(source_league, season - 1)

    target_ids = set(target_teams.keys())
    source_ids = set(source_teams.keys())

    all_entries = []
    for team_id in sorted(target_ids):
        try:
            all_entries.extend(get_team_transfers(team_id) or [])
        except ApisportsUnavailable:
            # Einzelner Verein nicht ladbar (z. B. Limit mitten im Lauf):
            # Fehler nach oben reichen, damit die Route sauber antworten
            # kann. Bereits gecachte Vereine sind nicht verloren, sie
            # liegen auf der Platte und beschleunigen den naechsten Lauf.
            raise

    return filter_summer_transfers(
        all_entries, target_ids, source_ids,
        season, source_league, target_league,
    )
