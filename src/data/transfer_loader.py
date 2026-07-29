"""
Transfer-Loader fuer den Liga-zu-Liga-Transfervergleich.

Saisonlogik (zentral definiert):
    season=2024 bedeutet bei API-Sports die Saison 2024/25.
    Transferzeitraum: Sommer 2024 (Juni-August).
    Quellverein: Liga-Mitglied in Saison season-1 (2023/24).
    Zielverein: Liga-Mitglied in Saison season (2024/25).

API-Strategie (Rate-Limit: 100 Requests/Tag):
    EINE Anfrage pro Zielliga+Saison:
        GET /transfers?league=X&season=Y
    liefert ALLE Transfers in diese Liga fuer diese Saison.
    Frueherer Ansatz (1 Request pro Verein = 20 Requests) war zu teuer.

    Zusaetzlich: je 1 Request fuer Teams der Ziel- und Quelliga.
    -> Insgesamt 3 Requests fuer den kompletten ersten Lauf.
"""

from datetime import date

from src.api.apisports_api import _get, LEAGUE_IDS, CURRENT_SEASON, ApisportsUnavailable
from src.utils.disk_cache import disk_cached_call

SUMMER_MONTHS = (6, 7, 8)
SUPPORTED_LEAGUES = ("bl1", "pl", "pd", "sa", "fl1")
LEAGUE_LABELS = {
    "bl1": "Bundesliga",
    "pl":  "Premier League",
    "pd":  "La Liga",
    "sa":  "Serie A",
    "fl1": "Ligue 1",
}

TTL_TEAMS_FINISHED    = 60 * 60 * 24 * 365
TTL_TEAMS_CURRENT     = 60 * 60 * 24 * 7
TTL_TRANSFERS_LEAGUE  = 60 * 60 * 24 * 14


def _teams_ttl(season):
    return TTL_TEAMS_FINISHED if season < CURRENT_SEASON else TTL_TEAMS_CURRENT


def get_league_teams(league_code, season):
    """Alle Vereine einer Liga in einer Saison. -> dict {team_id: {name, logo}}"""
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
    return {int(k): v for k, v in payload.items()}


def get_league_transfers(target_league_code, season):
    """
    ALLE Transfers IN eine Liga fuer eine Saison -- 1 einziger API-Request.

    GET /transfers?league=X&season=Y liefert alle Wechsel
    in Vereine dieser Liga fuer diesen Saisonzeitraum.
    """
    league_id = LEAGUE_IDS.get(target_league_code)
    if not league_id:
        raise ApisportsUnavailable(f"Unbekannte Liga: {target_league_code}")

    def loader():
        return _get("transfers", params={"league": league_id, "season": season})

    return disk_cached_call(
        key=f"apisports:transfers:league:{target_league_code}:{season}",
        ttl_seconds=TTL_TRANSFERS_LEAGUE,
        loader=loader,
        source="api-sports",
    )


def parse_transfer_date(raw_date):
    if not raw_date or not isinstance(raw_date, str):
        return None
    try:
        parts = raw_date.split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return None


def is_summer_transfer(transfer_date, season):
    if transfer_date is None:
        return False
    return transfer_date.year == season and transfer_date.month in SUMMER_MONTHS


def filter_summer_transfers(raw_transfer_entries, target_team_ids, source_team_ids,
                            season, source_league, target_league):
    """
    Reine Filterlogik ohne API-Zugriff (testbar).

    Bei mehreren Sommerwechseln desselben Spielers zaehlt der spaeteste
    Wechsel in die Zielliga.
    """
    best_per_player = {}

    for entry in raw_transfer_entries or []:
        player = entry.get("player") or {}
        player_id = player.get("id")
        if player_id is None:
            continue

        for move in entry.get("transfers") or []:
            teams = move.get("teams") or {}
            team_in  = teams.get("in")  or {}
            team_out = teams.get("out") or {}

            in_id  = team_in.get("id")
            out_id = team_out.get("id")
            if in_id is None or out_id is None:
                continue

            if in_id not in target_team_ids:
                continue
            if out_id not in source_team_ids:
                continue

            move_date = parse_transfer_date(move.get("date"))
            if not is_summer_transfer(move_date, season):
                continue

            candidate = {
                "player_id":       player_id,
                "player_name":     player.get("name"),
                "from_team_id":    out_id,
                "from_team_name":  team_out.get("name"),
                "from_team_logo":  team_out.get("logo"),
                "to_team_id":      in_id,
                "to_team_name":    team_in.get("name"),
                "to_team_logo":    team_in.get("logo"),
                "transfer_date":   move_date.isoformat(),
                "transfer_type":   move.get("type") or "Unbekannt",
                "source_league":   source_league,
                "target_league":   target_league,
            }

            existing = best_per_player.get(player_id)
            if existing is None or candidate["transfer_date"] > existing["transfer_date"]:
                best_per_player[player_id] = candidate

    return sorted(best_per_player.values(), key=lambda t: (t["player_name"] or ""))


def load_summer_transfers(source_league, target_league, season):
    """
    Alle Sommertransfers Quelliga -> Zielliga fuer einen Saisonwechsel.

    Ablauf (nur 3 API-Requests total, alle gecacht):
        1. Teams der Zielliga in der Saison        (1 Request)
        2. Teams der Quelliga in der Vorsaison     (1 Request)
        3. Alle Transfers in die Zielliga          (1 Request)
        4. Filtern                                 (keine Requests)
    """
    target_teams = get_league_teams(target_league, season)
    source_teams = get_league_teams(source_league, season - 1)

    target_ids = set(target_teams.keys())
    source_ids = set(source_teams.keys())

    all_entries = get_league_transfers(target_league, season)

    return filter_summer_transfers(
        all_entries, target_ids, source_ids,
        season, source_league, target_league,
    )
