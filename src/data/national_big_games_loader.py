"""
Match-level loader for senior-national-team Big Games.

This module deliberately stays beside ``big_games_loader`` instead of
teaching the club/UEFA pipeline about FIFA rules.  It discovers a player's
national-team engagements for one selected FootSim season, obtains only the
real fixtures for those exact team/competition/API-season triples, classifies
them before requesting fixture-player statistics, and returns match objects
compatible with the existing Big Games aggregation.

The public entry point is ``get_player_national_big_games_season``.  The
result has the same season/availability/matches envelope as the club loader;
the caller can merge its ``matches`` with club matches by stable fixture ID.
No aggregate national-season values are used as match performances.
"""

from src.api import apisports_api
from src.api.apisports_api import (
    ApisportsRateLimit,
    ApisportsUnavailable,
    CURRENT_SEASON,
)
from src.data import fifa_rankings
from src.data.national_competitions import national_targets_for_footsim_season
from src.data.player_compare_loader import get_player_season_raw
from src.features import national_big_games
from src.utils.disk_cache import disk_cached_call


# The namespace is intentionally distinct from the club Big Games caches.
# National fixtures may have the same provider fixture/player IDs only within
# the global API namespace, but separate keys make source and invalidation
# behaviour explicit and prevent accidental coupling to UEFA results.
CACHE_NAMESPACE = "national_big_games:v2"

TTL_FIXTURES_FINISHED = 60 * 60 * 24 * 30
TTL_FIXTURES_CURRENT = 60 * 60 * 6
TTL_FIXTURE_PLAYERS = 60 * 60 * 24 * 30
TTL_TEAM_IDENTITY = 60 * 60 * 24 * 180
TTL_PLAYER_RESULT_FINISHED = 60 * 60 * 24 * 14
TTL_PLAYER_RESULT_CURRENT = 60 * 60 * 4
TTL_EMPTY_FIXTURES = 60 * 60


def season_label(season):
    """FootSim season label without importing the UEFA-specific module."""
    return f"{season}/{str(season + 1)[-2:]}"


def _as_positive_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        # IDs and seasons are identity dimensions, not quantities.  In
        # particular, accepting 1.9 as ``int(1.9) == 1`` would silently
        # point at the wrong provider team or season.
        return None
    return parsed if parsed > 0 else None


def _fixtures_ttl(api_season):
    return TTL_FIXTURES_FINISHED if api_season < CURRENT_SEASON else TTL_FIXTURES_CURRENT


def _result_ttl(footsim_season):
    return (TTL_PLAYER_RESULT_FINISHED if footsim_season < CURRENT_SEASON
            else TTL_PLAYER_RESULT_CURRENT)


def _fixture_year(raw_date):
    """Extract a calendar year from API-Football's ISO fixture date safely."""
    if not isinstance(raw_date, str) or len(raw_date) < 4:
        return None
    try:
        year = int(raw_date[:4])
    except ValueError:
        return None
    return year if 1900 <= year <= 2100 else None


def _normalise_team_info(raw_result, expected_team_id):
    """
    Select the exact requested provider team object from ``/teams?id=``.

    Team names are presentation metadata only.  The equality check is always
    on the API-Football numeric ID; an unexpected response is unusable rather
    than a reason to guess a similarly named national side.
    """
    expected_team_id = _as_positive_int(expected_team_id)
    if expected_team_id is None:
        return None

    candidates = raw_result if isinstance(raw_result, list) else []
    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        team = entry.get("team") or entry
        if not isinstance(team, dict):
            continue
        if _as_positive_int(team.get("id")) == expected_team_id:
            return dict(team)
    return None


def _team_identity(team_id):
    """Cached exact provider metadata used for the senior-team fail-closed guard."""
    team_id = _as_positive_int(team_id)
    if team_id is None:
        return None

    def loader():
        return _normalise_team_info(apisports_api.get_team_info(team_id), team_id)

    return disk_cached_call(
        key=f"{CACHE_NAMESPACE}:team_identity:{team_id}",
        ttl_seconds=TTL_TEAM_IDENTITY,
        loader=loader,
        source="api-football.com/teams",
        empty_ttl_seconds=TTL_EMPTY_FIXTURES,
    )


def _is_verified_senior_team(team):
    """Delegate explicit youth/women/reserve rejection to the pure domain guard."""
    return bool(national_big_games.is_senior_national_team(team))


def _team_season_fixtures(team_id, league_id, api_season):
    """Fetch a national team's one competition/API-season fixture list once."""
    def loader():
        return apisports_api.get_team_season_fixtures(team_id, league_id, api_season)

    return disk_cached_call(
        key=(f"{CACHE_NAMESPACE}:team_season_fixtures:"
             f"{team_id}:{league_id}:{api_season}"),
        ttl_seconds=_fixtures_ttl(api_season),
        loader=loader,
        source="api-football.com/fixtures",
        empty_ttl_seconds=TTL_EMPTY_FIXTURES,
    )


def _fixture_players(fixture_id):
    """Fixture-player data has its own national cache namespace."""
    def loader():
        return apisports_api.get_fixture_players(fixture_id)

    return disk_cached_call(
        key=f"{CACHE_NAMESPACE}:fixture_players:{fixture_id}",
        ttl_seconds=TTL_FIXTURE_PLAYERS,
        loader=loader,
        source="api-football.com/fixtures/players",
    )


def _block_matches_target(block, target, require_explicit_api_season=False):
    """
    Check one player statistics block against an exact national target.

    ``/players?id=&season=`` already scopes its returned blocks to that API
    season, so old provider responses without ``league.season`` remain usable
    there.  Imported fallback blocks are not request-scoped; for them an
    explicit matching ``league.season`` is required, especially because
    Friendlies reuse league ID 10 across years.
    """
    if not isinstance(block, dict):
        return False
    league = block.get("league") or {}
    if _as_positive_int(league.get("id")) != _as_positive_int(target.get("league_id")):
        return False

    api_season = target.get("api_season")
    block_season = league.get("season")
    if block_season is None:
        return not require_explicit_api_season
    return _as_positive_int(block_season) == _as_positive_int(api_season)


def _engagement_from_block(block, target, source):
    """Convert an exact player-statistics block into a fixture-discovery key."""
    if not isinstance(block, dict):
        return None
    team = block.get("team") or {}
    team_id = _as_positive_int(team.get("id"))
    league_id = _as_positive_int(target.get("league_id"))
    api_season = _as_positive_int(target.get("api_season"))
    if team_id is None or league_id is None or api_season is None:
        return None
    league = block.get("league") or {}
    return {
        "team_id": team_id,
        "team_name": team.get("name"),
        "team_logo": team.get("logo"),
        "league_id": league_id,
        "league_name": league.get("name") or target.get("name"),
        "api_season": api_season,
        "source": source,
    }


def _discover_national_engagements(player_id, footsim_season):
    """
    Resolve exact national team/competition/API-season engagements.

    The current local ``national_<season>.json`` is used only as a carefully
    keyed fallback for profile data.  Primary discovery is the provider's
    player profile queried for every verified target API season, which gives
    historical coverage even where no local import file exists.
    """
    targets = national_targets_for_footsim_season(footsim_season)
    engagements = []
    unavailable_targets = []
    seen = set()

    # Imported blocks may supplement a cache-missed/stale player profile but
    # never replace its exact (team, league, API-season) identity.
    try:
        from src.data.national_import import get_national_blocks
        imported_blocks = get_national_blocks(player_id, footsim_season)
    except Exception:
        # The import file is strictly an optional discovery supplement.  A
        # malformed/private-missing local payload must not suppress provider
        # profile discovery or break Player Comparison.
        imported_blocks = []

    for target in targets:
        api_season = target["api_season"]
        profile_blocks = []
        try:
            raw_profile = get_player_season_raw(player_id, api_season)
            if raw_profile:
                profile_blocks = raw_profile.get("statistics") or []
        except (ApisportsUnavailable, ApisportsRateLimit):
            unavailable_targets.append({
                "league_id": target["league_id"],
                "api_season": api_season,
                "reason": "player_profile_unavailable",
            })

        sources = (
            (profile_blocks, "player_profile", False),
            (imported_blocks, "national_import", True),
        )
        for blocks, source, require_explicit_api_season in sources:
            for block in blocks:
                if not _block_matches_target(
                    block, target,
                    require_explicit_api_season=require_explicit_api_season,
                ):
                    continue
                engagement = _engagement_from_block(block, target, source)
                if engagement is None:
                    continue
                key = (
                    engagement["team_id"], engagement["league_id"],
                    engagement["api_season"],
                )
                if key in seen:
                    continue
                seen.add(key)
                engagements.append(engagement)

    return engagements, targets, unavailable_targets


def player_national_engagements(player_id, footsim_season):
    """Public convenience accessor returning only exact national engagements."""
    engagements, _targets, _unavailable = _discover_national_engagements(
        player_id, footsim_season
    )
    return engagements


def _fixture_matches_engagement(raw_fixture, engagement):
    """Defensive exact competition/API-season check on a fixture response."""
    if not isinstance(raw_fixture, dict):
        return False
    league = raw_fixture.get("league") or {}
    if _as_positive_int(league.get("id")) != engagement["league_id"]:
        return False
    fixture_season = league.get("season")
    if fixture_season is None:
        # The endpoint was requested with this exact season, so absence is
        # acceptable.  A contradictory value, however, must never leak in.
        return True
    return _as_positive_int(fixture_season) == engagement["api_season"]


def _fixture_id(raw_fixture):
    if not isinstance(raw_fixture, dict):
        return None
    return _as_positive_int((raw_fixture.get("fixture") or {}).get("id"))


def _classify_fixture(raw_fixture, engagement, own_team, opponent_team):
    """
    Classify a single senior fixture and return a compatible normalized object.

    FIFA lookup uses the fixture's calendar year exactly.  A missing private
    snapshot yields ``None`` and leaves ranking qualification neutral; the
    pure domain classifier can still admit an eligible World Cup/EURO knockout.
    """
    perspective = national_big_games.resolve_opponent(raw_fixture, engagement["team_id"])
    if not isinstance(perspective, dict):
        return None
    opponent = perspective.get("opponent")
    if not isinstance(opponent, dict):
        return None
    opponent_id = _as_positive_int(perspective.get("opponent_id"))
    if opponent_id is None:
        return None

    fixture = raw_fixture.get("fixture") or {}
    ranking_year = _fixture_year(fixture.get("date"))
    ranking = (fifa_rankings.lookup_team(ranking_year, opponent_id)
               if ranking_year is not None else None)
    snapshot = (fifa_rankings.load_snapshot(ranking_year)
                if ranking_year is not None else None)

    classified = national_big_games.classify_national_fixture(
        raw_fixture,
        engagement["team_id"],
        opponent_ranking=ranking,
        own_team=own_team,
        opponent_team=opponent_team,
    )
    if not isinstance(classified, dict) or not classified.get("is_big_game"):
        return None

    teams = raw_fixture.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    is_home = _as_positive_int(home.get("id")) == engagement["team_id"]
    own_fixture_team = home if is_home else away
    league = raw_fixture.get("league") or {}

    # Values from the pure classifier are the source of eligibility and
    # weight semantics.  This layer only adds API shape/display metadata.
    return {
        **classified,
        "fixture_id": _fixture_id(raw_fixture),
        "date": fixture.get("date"),
        "is_home": is_home,
        "own_team_id": engagement["team_id"],
        "own_team_name": own_fixture_team.get("name") or engagement.get("team_name"),
        "own_team_logo": own_fixture_team.get("logo") or engagement.get("team_logo"),
        "opponent_id": opponent_id,
        "opponent_name": opponent.get("name"),
        "opponent_logo": opponent.get("logo"),
        "league_id": engagement["league_id"],
        "league_name": league.get("name") or engagement.get("league_name"),
        "round": league.get("round"),
        "tier": "national",
        "source": "national",
        "ranking_source": "fifa",
        "ranking_year": ranking_year,
        "ranking_snapshot_date": (snapshot or {}).get("snapshot_date"),
        "ranking_snapshot_status": (snapshot or {}).get("status"),
        "ranking_snapshot_available": bool((snapshot or {}).get("available")),
        "ranking_provisional": bool((snapshot or {}).get("provisional")),
        "opponent_coefficient": None,
    }


def _extract_player_line(raw_players, player_id):
    """Reuse the established API-Football line normalization lazily.

    The import is intentionally local: when the existing club loader imports
    this module to merge domains, module initialization stays acyclic while
    both domains continue to produce identical statistics keys.
    """
    from src.data.big_games_loader import _extract_player_line as extract_line
    return extract_line(raw_players, player_id)


def _season_result(player_id, footsim_season):
    """Uncached national result for one selected FootSim season."""
    engagements, targets, unavailable_targets = _discover_national_engagements(
        player_id, footsim_season
    )
    if not targets:
        return {
            "season": footsim_season,
            "season_label": season_label(footsim_season),
            "available": False,
            "reason": "no_national_targets",
            "provisional": False,
            "matches": [],
            "unavailable_targets": [],
            "unavailable_ranking_years": [],
        }

    candidates_by_fixture = {}
    unavailable_ranking_years = set()
    provisional = False

    for engagement in engagements:
        try:
            own_team = _team_identity(engagement["team_id"])
        except (ApisportsUnavailable, ApisportsRateLimit):
            continue
        if not _is_verified_senior_team(own_team):
            # No exact verified senior identity: never guess from the name.
            continue

        try:
            raw_fixtures = _team_season_fixtures(
                engagement["team_id"], engagement["league_id"], engagement["api_season"]
            )
        except (ApisportsUnavailable, ApisportsRateLimit):
            unavailable_targets.append({
                "league_id": engagement["league_id"],
                "api_season": engagement["api_season"],
                "reason": "fixtures_unavailable",
            })
            continue

        for raw_fixture in raw_fixtures or []:
            if not _fixture_matches_engagement(raw_fixture, engagement):
                continue
            fixture_id = _fixture_id(raw_fixture)
            if fixture_id is None:
                continue

            # Surface coverage honestly even if a group-stage fixture is
            # ultimately skipped because the unavailable ranking cannot make
            # it qualify.  A missing private source is never mistaken for a
            # weak opponent and never prevents a WC/EURO knockout from using
            # its independent automatic qualification.
            fixture_date = (raw_fixture.get("fixture") or {}).get("date")
            fixture_ranking_year = _fixture_year(fixture_date)
            if fixture_ranking_year is not None:
                fixture_snapshot = fifa_rankings.load_snapshot(fixture_ranking_year)
                if not fixture_snapshot.get("available"):
                    unavailable_ranking_years.add(fixture_ranking_year)
                provisional = provisional or bool(fixture_snapshot.get("provisional"))

            perspective = national_big_games.resolve_opponent(
                raw_fixture, engagement["team_id"]
            )
            opponent_id = (
                perspective.get("opponent_id") if isinstance(perspective, dict) else None
            )
            opponent_id = _as_positive_int(opponent_id)
            if opponent_id is None:
                continue
            try:
                opponent_team = _team_identity(opponent_id)
            except (ApisportsUnavailable, ApisportsRateLimit):
                continue
            if not _is_verified_senior_team(opponent_team):
                continue

            candidate = _classify_fixture(raw_fixture, engagement, own_team, opponent_team)
            if candidate is None:
                continue

            # A fixture can be discovered twice only through duplicate
            # source blocks.  Stable provider fixture identity is decisive;
            # classification itself already carries both qualifying reasons.
            candidates_by_fixture.setdefault(fixture_id, candidate)

    matches = []
    for fixture_id in sorted(candidates_by_fixture):
        candidate = candidates_by_fixture[fixture_id]
        try:
            raw_players = _fixture_players(fixture_id)
        except (ApisportsUnavailable, ApisportsRateLimit):
            continue
        line = _extract_player_line(raw_players, player_id)
        if line is None:
            continue
        matches.append({**candidate, **line})

    matches.sort(key=lambda match: (match.get("date") or "", match["fixture_id"]))
    return {
        "season": footsim_season,
        "season_label": season_label(footsim_season),
        # Targets are product-verified even where a player has no appearance.
        # Per-target provider failures are exposed below rather than making
        # the whole Player Comparison unavailable.
        "available": True,
        "reason": None,
        "provisional": provisional,
        "matches": matches,
        "unavailable_targets": unavailable_targets,
        "unavailable_ranking_years": sorted(unavailable_ranking_years),
    }


def get_player_national_big_games_season(player_id, footsim_season):
    """National Big Games for one FootSim season, cached independently."""
    player_id = _as_positive_int(player_id)
    footsim_season = _as_positive_int(footsim_season)
    if player_id is None or footsim_season is None:
        return {
            "season": footsim_season,
            "season_label": None,
            "available": False,
            "reason": "invalid_input",
            "provisional": False,
            "matches": [],
            "unavailable_targets": [],
            "unavailable_ranking_years": [],
        }

    return disk_cached_call(
        key=f"{CACHE_NAMESPACE}:player_footsim_season:{player_id}:{footsim_season}",
        ttl_seconds=_result_ttl(footsim_season),
        loader=lambda: _season_result(player_id, footsim_season),
        source="footsim/national-big-games",
    )


def get_player_national_big_games(player_id, season_from, season_to):
    """Return compatible national matches across the existing Big-Games period."""
    start = _as_positive_int(season_from)
    end = _as_positive_int(season_to)
    if start is None or end is None:
        return {
            "player_id": player_id,
            "season_from": season_from,
            "season_to": season_to,
            "seasons": [],
            "matches": [],
            "has_unavailable_seasons": True,
            "has_provisional_seasons": False,
        }
    if start > end:
        start, end = end, start

    seasons = []
    matches_by_fixture = {}
    for footsim_season in range(start, end + 1):
        result = get_player_national_big_games_season(player_id, footsim_season)
        seasons.append({
            "season": footsim_season,
            "season_label": result.get("season_label"),
            "available": result.get("available", False),
            "reason": result.get("reason"),
            "provisional": result.get("provisional", False),
            "match_count": len(result.get("matches") or []),
            "unavailable_targets": result.get("unavailable_targets") or [],
            "unavailable_ranking_years": result.get("unavailable_ranking_years") or [],
        })
        for match in result.get("matches") or []:
            fixture_id = _fixture_id({"fixture": {"id": match.get("fixture_id")}})
            if fixture_id is not None:
                matches_by_fixture.setdefault(fixture_id, match)

    matches = sorted(
        matches_by_fixture.values(),
        key=lambda match: (match.get("date") or "", match["fixture_id"]),
    )
    return {
        "player_id": player_id,
        "season_from": start,
        "season_to": end,
        "seasons": seasons,
        "matches": matches,
        "has_unavailable_seasons": any(not item["available"] for item in seasons),
        "has_provisional_seasons": any(item["provisional"] for item in seasons),
    }
