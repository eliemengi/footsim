"""
Pure national-team Big Games rules.

This module deliberately owns only deterministic, domain-specific decisions.
It has no API, cache, file-system or Flask dependency.  A future loader gives
it one real fixture, exact API-Football team metadata and the already-resolved
FIFA ranking for the fixture year; the returned object is compatible with the
existing player-centric Big Games match shape.

Important boundary: a team name is never used to *identify* a national team.
Senior identity requires an exact API-Football ID with ``national is True`` in
trusted team metadata.  Text is used only as an additional fail-closed guard
when the provider explicitly labels a youth, Olympic, reserve or women's side.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping


# ---------------------------------------------------------------------------
# Public product constants
# ---------------------------------------------------------------------------

NATIONAL_SOURCE = "national"
FIFA_RANKING_SOURCE = "fifa"
NATIONAL_TIER = "national"

WORLD_CUP_COMPETITION_ID = 1
EURO_COMPETITION_ID = 4
AUTO_KNOCKOUT_COMPETITION_IDS = frozenset({
    WORLD_CUP_COMPETITION_ID,
    EURO_COMPETITION_ID,
})

FIFA_TOP_20_MAX_RANK = 20
FIFA_ELITE_MAX_RANK = 10

# Club opponent strength currently spans 1.00--1.50 and uses a continuous
# UEFA coefficient.  FIFA has only the approved two categorical tiers here,
# so deliberately smaller values keep a national fixture from dominating a
# comparable club performance solely because the sources use different scales.
FIFA_STRENGTH_UNKNOWN = 1.00
FIFA_STRENGTH_TOP_11_TO_20 = 1.04
FIFA_STRENGTH_TOP_1_TO_10 = 1.08

IMPORTANCE_BASE = 1.00

STAGE_GROUP = "group"
STAGE_ROUND_OF_32 = "round_of_32"
STAGE_ROUND_OF_16 = "round_of_16"
STAGE_QUARTERFINAL = "quarterfinal"
STAGE_SEMIFINAL = "semifinal"
STAGE_FINAL = "final"
STAGE_THIRD_PLACE = "third_place"
STAGE_UNKNOWN = "unknown"

NATIONAL_KNOCKOUT_STAGES = frozenset({
    STAGE_ROUND_OF_32,
    STAGE_ROUND_OF_16,
    STAGE_QUARTERFINAL,
    STAGE_SEMIFINAL,
    STAGE_FINAL,
})

# These are intentionally aligned with the modest existing club round scale;
# R32 is the new, explicit lower knockout step.  They apply only to World Cup
# and EURO knockout fixtures, never to another competition's knockout round.
NATIONAL_KNOCKOUT_IMPORTANCE = {
    STAGE_ROUND_OF_32: 1.05,
    STAGE_ROUND_OF_16: 1.08,
    STAGE_QUARTERFINAL: 1.10,
    STAGE_SEMIFINAL: 1.12,
    STAGE_FINAL: 1.15,
}

FINISHED_STATUSES = frozenset({"FT", "AET", "PEN"})


# ---------------------------------------------------------------------------
# Small validation helpers
# ---------------------------------------------------------------------------

def _positive_int(value):
    """Return a positive, exact integer identifier or ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
        return number if number > 0 else None
    return None


def _team_payload(team):
    """Accept a provider team object, with one harmless ``team`` wrapper."""
    if not isinstance(team, Mapping):
        return None
    nested = team.get("team")
    if isinstance(nested, Mapping) and "id" not in team:
        return nested
    return team


def _team_text(team):
    """Metadata text used only to reject explicit non-senior labels."""
    data = _team_payload(team)
    if data is None:
        return ""
    fields = ("name", "type", "category", "gender", "level", "squad")
    return " ".join(str(data.get(field) or "") for field in fields).lower()


_JUNIOR_OR_NON_SENIOR_MARKER = re.compile(
    r"(?:\bu\s*[- ]?\s*(?:17|18|19|20|21|22|23)\b"
    r"|\bunder\s*[- ]?\s*(?:17|18|19|20|21|22|23)\b"
    r"|\byouth\b|\bolympic(?:s)?\b|\breserves?\b"
    r"|\bwom[ae]n(?:'s)?\b|\bfemale\b|\bfrauen\b)"
)


def _has_non_senior_marker(team):
    return bool(_JUNIOR_OR_NON_SENIOR_MARKER.search(_team_text(team)))


def is_senior_national_team(team):
    """
    Verify a senior national side from trusted provider metadata.

    API-Football's team endpoint supplies the exact team ID and ``national``
    flag.  A fixture's abbreviated team object alone is deliberately not
    enough: in that case this returns False instead of guessing from a name.
    """
    data = _team_payload(team)
    if data is None or _positive_int(data.get("id")) is None:
        return False
    if data.get("national") is not True:
        return False
    if data.get("senior") is False or data.get("is_senior") is False:
        return False
    if data.get("women") is True or data.get("is_women") is True:
        return False
    return not _has_non_senior_marker(data)


def normalize_fifa_rank(rank):
    """Normalise a provider ranking to a positive integer, otherwise None."""
    return _positive_int(rank)


def _ranking_for_opponent(opponent_ranking, opponent_id):
    """
    Extract a ranking only when an optionally supplied ranking ID matches.

    The FIFA loader can pass either a bare rank or a ranking row.  A row with
    an identity field must refer to this exact opponent; a mismatching row is
    neutral rather than silently applied to another team.
    """
    if opponent_ranking is None:
        return None
    if not isinstance(opponent_ranking, Mapping):
        return normalize_fifa_rank(opponent_ranking)

    identity = None
    for key in ("apisports_team_id", "team_id", "national_team_id"):
        if key in opponent_ranking:
            identity = _positive_int(opponent_ranking.get(key))
            if identity != opponent_id:
                return None
            break

    # A few callers naturally retain the provider's nested team shape.
    if identity is None and isinstance(opponent_ranking.get("team"), Mapping):
        nested_id = _positive_int(opponent_ranking["team"].get("id"))
        if nested_id is not None and nested_id != opponent_id:
            return None

    return normalize_fifa_rank(opponent_ranking.get("rank"))


# ---------------------------------------------------------------------------
# National stages and weighting
# ---------------------------------------------------------------------------

def _normalised_round_text(raw_round):
    if not isinstance(raw_round, str):
        return ""
    text = unicodedata.normalize("NFKD", raw_round).lower().strip()
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("-", " ").replace("_", " ").replace("/", " ")
    return " ".join(text.split())


def normalize_national_round(raw_round):
    """
    Map explicit provider round names to national-team stages.

    The checks intentionally do not use a generic ``"final" in text`` rule:
    it would turn semi-finals and quarter-finals into a final.  Third-place
    matches remain their own non-automatic stage because the product rule only
    names R32/R16/QF/SF/final as World Cup/EURO automatic qualifiers.
    """
    text = _normalised_round_text(raw_round)
    if not text:
        return STAGE_UNKNOWN

    if text in {"3rd place", "third place", "3rd place final", "third place final"}:
        return STAGE_THIRD_PLACE
    if text in {"round of 32", "round 32", "last 32", "1 16 finals", "1 16 final"}:
        return STAGE_ROUND_OF_32
    if text in {"round of 16", "round 16", "last 16", "8th finals", "8th final", "1 8 finals", "1 8 final"}:
        return STAGE_ROUND_OF_16
    if text in {"quarter final", "quarter finals", "quarterfinal", "quarterfinals"}:
        return STAGE_QUARTERFINAL
    if text in {"semi final", "semi finals", "semifinal", "semifinals"}:
        return STAGE_SEMIFINAL
    if text == "final":
        return STAGE_FINAL

    # Provider variants such as "Round of 16 - 1" retain the decisive prefix.
    if re.match(r"^round of 32(?:\s+\d+)?$", text) or re.match(r"^r\s*32$", text):
        return STAGE_ROUND_OF_32
    if re.match(r"^round of 16(?:\s+\d+)?$", text) or re.match(r"^r\s*16$", text):
        return STAGE_ROUND_OF_16
    if text.startswith("quarter final") or text.startswith("quarterfinal"):
        return STAGE_QUARTERFINAL
    if text.startswith("semi final") or text.startswith("semifinal"):
        return STAGE_SEMIFINAL
    if text.startswith("group stage") or re.match(r"^group\s+[a-z0-9]+(?:\s+\d+)?$", text):
        return STAGE_GROUP
    if text.startswith("league stage") or text.startswith("regular season"):
        return STAGE_GROUP
    return STAGE_UNKNOWN


def is_fifa_top20(rank):
    """Whether a FIFA rank qualifies a fixture through opponent strength."""
    value = normalize_fifa_rank(rank)
    return value is not None and value <= FIFA_TOP_20_MAX_RANK


def national_opponent_strength(rank):
    """
    Return the approved, intentionally modest FIFA opponent-strength tier.

    No continuous interpolation or strength is invented for a team outside the
    stored Top 20.  Such a team gets neutral context; it can still appear via
    World Cup/EURO knockout qualification.
    """
    value = normalize_fifa_rank(rank)
    if value is None or value > FIFA_TOP_20_MAX_RANK:
        return FIFA_STRENGTH_UNKNOWN
    if value <= FIFA_ELITE_MAX_RANK:
        return FIFA_STRENGTH_TOP_1_TO_10
    return FIFA_STRENGTH_TOP_11_TO_20


def is_world_cup_knockout(competition_id, stage):
    return (
        _positive_int(competition_id) == WORLD_CUP_COMPETITION_ID
        and stage in NATIONAL_KNOCKOUT_STAGES
    )


def is_euro_knockout(competition_id, stage):
    return (
        _positive_int(competition_id) == EURO_COMPETITION_ID
        and stage in NATIONAL_KNOCKOUT_STAGES
    )


def is_world_cup_or_euro_knockout(competition_id, stage):
    """Automatic qualification exists only for the two approved competitions."""
    return (
        _positive_int(competition_id) in AUTO_KNOCKOUT_COMPETITION_IDS
        and stage in NATIONAL_KNOCKOUT_STAGES
    )


def national_match_importance(competition_id, stage):
    """
    Context importance for an already verified national fixture.

    Other competitions intentionally remain neutral even if their provider
    round is a quarter-final: this pass grants no tournament-importance policy
    outside World Cup and EURO knockout matches.
    """
    if not is_world_cup_or_euro_knockout(competition_id, stage):
        return IMPORTANCE_BASE
    return NATIONAL_KNOCKOUT_IMPORTANCE.get(stage, IMPORTANCE_BASE)


def national_context_weight(opponent_rank, competition_id, stage):
    """Compatible ``strength * importance`` context weight for aggregation."""
    return national_opponent_strength(opponent_rank) * national_match_importance(
        competition_id, stage
    )


# ---------------------------------------------------------------------------
# Fixture perspective and classification
# ---------------------------------------------------------------------------

def resolve_opponent(raw_fixture, own_team_id):
    """
    Resolve home/away perspective through exact API-Football team IDs.

    Returns ``None`` when the own side is not exactly one of the two fixture
    teams.  It does not infer a team from a display name.
    """
    if not isinstance(raw_fixture, Mapping):
        return None
    own_id = _positive_int(own_team_id)
    teams = raw_fixture.get("teams")
    if own_id is None or not isinstance(teams, Mapping):
        return None

    home = _team_payload(teams.get("home"))
    away = _team_payload(teams.get("away"))
    if home is None or away is None:
        return None

    home_id = _positive_int(home.get("id"))
    away_id = _positive_int(away.get("id"))
    if home_id is None or away_id is None or home_id == away_id:
        return None

    if home_id == own_id:
        own_team, opponent = home, away
        own_side, opponent_side, is_home = "home", "away", True
    elif away_id == own_id:
        own_team, opponent = away, home
        own_side, opponent_side, is_home = "away", "home", False
    else:
        return None

    return {
        "own_team": own_team,
        "opponent": opponent,
        "own_team_id": own_id,
        "opponent_id": _positive_int(opponent.get("id")),
        "own_side": own_side,
        "opponent_side": opponent_side,
        "is_home": is_home,
    }


def _verified_senior_fixture_team(fixture_team, supplied_metadata):
    """Ensure supplied trusted metadata belongs to this exact fixture team."""
    fixture_data = _team_payload(fixture_team)
    metadata = _team_payload(supplied_metadata if supplied_metadata is not None else fixture_team)
    if fixture_data is None or metadata is None:
        return None
    fixture_id = _positive_int(fixture_data.get("id"))
    if fixture_id is None or _positive_int(metadata.get("id")) != fixture_id:
        return None

    # Fixture labels can expose an explicit youth/women side even when a caller
    # accidentally passed stale metadata for a generic senior team.  Reject it.
    if _has_non_senior_marker(fixture_data) or not is_senior_national_team(metadata):
        return None
    return metadata


def _fixture_id(raw_fixture):
    if not isinstance(raw_fixture, Mapping):
        return None
    fixture = raw_fixture.get("fixture")
    return _positive_int(fixture.get("id")) if isinstance(fixture, Mapping) else None


def _finished_fixture(raw_fixture):
    fixture = raw_fixture.get("fixture") if isinstance(raw_fixture, Mapping) else None
    status = fixture.get("status") if isinstance(fixture, Mapping) else None
    short = status.get("short") if isinstance(status, Mapping) else None
    return isinstance(short, str) and short.upper() in FINISHED_STATUSES


def classify_national_fixture(raw_fixture, own_team_id, opponent_ranking=None,
                              own_team=None, opponent_team=None):
    """
    Classify one completed, verified senior-national-team fixture.

    ``opponent_ranking`` may be a bare rank or a FIFA loader row containing
    ``rank`` and optionally ``apisports_team_id``/``team_id``.  ``own_team``
    and ``opponent_team`` are trusted `/teams?id=` metadata; without them the
    fixture objects themselves must carry ``national is True``.  That strict
    default is intentional: an abbreviated fixture object cannot prove senior
    identity and therefore fails closed.

    A valid non-qualifying fixture returns a normalized object with
    ``is_big_game=False``.  Invalid, unfinished or ambiguous data returns
    ``None`` so a loader can skip only that point without breaking the profile.
    """
    if not isinstance(raw_fixture, Mapping) or _fixture_id(raw_fixture) is None:
        return None
    if not _finished_fixture(raw_fixture):
        return None

    perspective = resolve_opponent(raw_fixture, own_team_id)
    if perspective is None:
        return None

    verified_own = _verified_senior_fixture_team(
        perspective["own_team"], own_team
    )
    verified_opponent = _verified_senior_fixture_team(
        perspective["opponent"], opponent_team
    )
    if verified_own is None or verified_opponent is None:
        return None

    fixture = raw_fixture.get("fixture")
    fixture = fixture if isinstance(fixture, Mapping) else {}
    league = raw_fixture.get("league")
    league = league if isinstance(league, Mapping) else {}
    competition_id = _positive_int(league.get("id"))
    stage = normalize_national_round(league.get("round"))
    opponent_id = perspective["opponent_id"]
    opponent_rank = _ranking_for_opponent(opponent_ranking, opponent_id)

    ranking_qualified = is_fifa_top20(opponent_rank)
    knockout_qualified = is_world_cup_or_euro_knockout(competition_id, stage)
    qualification_reasons = []
    if ranking_qualified:
        qualification_reasons.append("fifa_top20_opponent")
    if knockout_qualified:
        qualification_reasons.append("world_cup_or_euro_knockout")

    strength = national_opponent_strength(opponent_rank)
    importance = national_match_importance(competition_id, stage)
    own_display = perspective["own_team"]
    opponent_display = perspective["opponent"]

    return {
        "fixture_id": _fixture_id(raw_fixture),
        "date": fixture.get("date"),
        "is_home": perspective["is_home"],
        "own_side": perspective["own_side"],
        "own_team_id": perspective["own_team_id"],
        "own_team_name": own_display.get("name") or verified_own.get("name"),
        "own_team_logo": own_display.get("logo") or verified_own.get("logo"),
        "opponent": {
            "id": opponent_id,
            "name": opponent_display.get("name") or verified_opponent.get("name"),
            "logo": opponent_display.get("logo") or verified_opponent.get("logo"),
            "side": perspective["opponent_side"],
        },
        "opponent_id": opponent_id,
        "opponent_name": opponent_display.get("name") or verified_opponent.get("name"),
        "opponent_logo": opponent_display.get("logo") or verified_opponent.get("logo"),
        "opponent_side": perspective["opponent_side"],
        "competition_id": competition_id,
        "competition_name": league.get("name"),
        # Existing Big Games display/aggregation calls these league fields.
        "league_id": competition_id,
        "league_name": league.get("name"),
        "round": league.get("round"),
        "stage": stage,
        "tier": NATIONAL_TIER,
        "opponent_rank": opponent_rank,
        "opponent_strength": strength,
        "strength": strength,
        "importance": importance,
        "weight": strength * importance,
        "ranking_qualified": ranking_qualified,
        "knockout_qualified": knockout_qualified,
        # Compatibility aliases make the shared match shape explicit without
        # reusing UEFA-specific vocabulary in the classification logic.
        "opponent_qualified": ranking_qualified,
        "importance_qualified": knockout_qualified,
        "qualification_reasons": qualification_reasons,
        "is_big_game": bool(qualification_reasons),
        "reason": None if qualification_reasons else "not_qualified",
        "source": NATIONAL_SOURCE,
        "ranking_source": FIFA_RANKING_SOURCE,
    }


# ---------------------------------------------------------------------------
# Shared aggregation helpers
# ---------------------------------------------------------------------------

def _non_negative_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def goal_assist_contribution(goals, assists):
    """Raw G+A with the fixed product rule: one goal equals one assist."""
    goal_value = _non_negative_number(goals)
    assist_value = _non_negative_number(assists)
    if goals is not None and goal_value is None:
        return None
    if assists is not None and assist_value is None:
        return None
    if goal_value is None and assist_value is None:
        return None
    return (goal_value or 0.0) + (assist_value or 0.0)


def weighted_goal_assist_contribution(goals, assists, context_weight=1.0):
    """Context-weighted G+A while retaining exactly equal goal/assist value."""
    contribution = goal_assist_contribution(goals, assists)
    weight = _non_negative_number(context_weight)
    if contribution is None or weight is None:
        return None
    return contribution * weight


def _stable_fixture_id(item):
    if not isinstance(item, Mapping):
        return None
    direct = _positive_int(item.get("fixture_id"))
    if direct is not None:
        return direct
    fixture = item.get("fixture")
    return _positive_int(fixture.get("id")) if isinstance(fixture, Mapping) else None


def _unique_reasons(*reason_lists):
    merged = []
    for reasons in reason_lists:
        if not isinstance(reasons, (list, tuple, set, frozenset)):
            continue
        for reason in reasons or []:
            if reason not in merged:
                merged.append(reason)
    return merged


def dedupe_fixtures(fixtures):
    """
    Stable fixture-ID deduplication for the combined club/national match list.

    The first normalized object remains canonical.  Duplicate eligibility
    paths union their reasons and boolean qualification flags; missing scalar
    metadata is filled from the later object.  Neither input object is mutated.
    Entries without a stable fixture ID are skipped rather than guessed.
    """
    if fixtures is None:
        return []
    try:
        iterator = iter(fixtures)
    except TypeError:
        return []

    deduped = []
    by_fixture_id = {}

    for item in iterator:
        fixture_id = _stable_fixture_id(item)
        if fixture_id is None or not isinstance(item, Mapping):
            continue
        incoming = dict(item)
        incoming["fixture_id"] = fixture_id

        existing_index = by_fixture_id.get(fixture_id)
        if existing_index is None:
            by_fixture_id[fixture_id] = len(deduped)
            deduped.append(incoming)
            continue

        existing = deduped[existing_index]
        for key, value in incoming.items():
            if existing.get(key) is None and value is not None:
                existing[key] = value

        existing["ranking_qualified"] = bool(existing.get("ranking_qualified")) or bool(
            incoming.get("ranking_qualified")
        )
        existing["knockout_qualified"] = bool(existing.get("knockout_qualified")) or bool(
            incoming.get("knockout_qualified")
        )
        existing["opponent_qualified"] = bool(existing.get("opponent_qualified")) or bool(
            incoming.get("opponent_qualified")
        )
        existing["importance_qualified"] = bool(existing.get("importance_qualified")) or bool(
            incoming.get("importance_qualified")
        )
        existing["is_big_game"] = bool(existing.get("is_big_game")) or bool(
            incoming.get("is_big_game")
        )
        existing["qualification_reasons"] = _unique_reasons(
            existing.get("qualification_reasons"), incoming.get("qualification_reasons")
        )

    return deduped


# Clear future-loader alias; both names enforce the same stable-ID policy.
dedupe_fixture_matches = dedupe_fixtures


__all__ = [
    "AUTO_KNOCKOUT_COMPETITION_IDS",
    "EURO_COMPETITION_ID",
    "FIFA_ELITE_MAX_RANK",
    "FIFA_RANKING_SOURCE",
    "FIFA_STRENGTH_TOP_1_TO_10",
    "FIFA_STRENGTH_TOP_11_TO_20",
    "FIFA_STRENGTH_UNKNOWN",
    "FIFA_TOP_20_MAX_RANK",
    "FINISHED_STATUSES",
    "IMPORTANCE_BASE",
    "NATIONAL_KNOCKOUT_IMPORTANCE",
    "NATIONAL_KNOCKOUT_STAGES",
    "NATIONAL_SOURCE",
    "NATIONAL_TIER",
    "STAGE_FINAL",
    "STAGE_GROUP",
    "STAGE_QUARTERFINAL",
    "STAGE_ROUND_OF_16",
    "STAGE_ROUND_OF_32",
    "STAGE_SEMIFINAL",
    "STAGE_THIRD_PLACE",
    "STAGE_UNKNOWN",
    "WORLD_CUP_COMPETITION_ID",
    "classify_national_fixture",
    "dedupe_fixture_matches",
    "dedupe_fixtures",
    "goal_assist_contribution",
    "is_euro_knockout",
    "is_fifa_top20",
    "is_senior_national_team",
    "is_world_cup_knockout",
    "is_world_cup_or_euro_knockout",
    "national_context_weight",
    "national_match_importance",
    "national_opponent_strength",
    "normalize_fifa_rank",
    "normalize_national_round",
    "resolve_opponent",
    "weighted_goal_assist_contribution",
]
