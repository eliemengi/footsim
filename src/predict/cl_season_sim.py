"""
Monte-Carlo-Simulation der Champions-League-Ligaphase.

Abgrenzung zu season_sim.py
---------------------------
season_sim.simulate_season ist auf nationale Ligen zugeschnitten:

  * ZONE_CONFIGS kennt nur bl1/pl/pd/sa/fl1 mit CL-/EL-/Abstiegsplaetzen,
  * sortiert wird nach (Punkte, Tordifferenz, Tore),
  * gespielte Partien sind IMMER fix, simuliert wird nur der Rest.

Die Ligaphase braucht an allen drei Punkten etwas anderes: eigene Zonen
(1-8 direkt ins Achtelfinale, 9-24 K.-o.-Play-offs, ab 25 ausgeschieden),
die offizielle UEFA-Tiebreak-Kaskade inklusive gegnerabhaengiger
Kriterien, und einen Modus, der eine bereits abgeschlossene Ligaphase
vollstaendig neu simuliert.

Zwei Modi
---------
full_resimulation
    ALLE Ligaphasen-Partien werden neu gewuerfelt, auch bereits
    gespielte. Die realen Paarungen und die reale Heim-/Auswaertsrolle
    bleiben erhalten, die realen Ergebnisse werden bewusst verworfen.
    Damit laesst sich eine abgeschlossene Saison als "was waere wenn"
    durchrechnen.

simulate_remaining
    Gespielte Partien bleiben mit ihrem echten Ergebnis stehen und
    bilden die Ausgangstabelle. Nur offene Partien werden gewuerfelt.
    Das ist dasselbe Prinzip wie bei der Domestic-Saisonsimulation.

Ohne ausdrueckliche Angabe entscheidet der Spielplan: Gibt es offene
Partien, wird simulate_remaining verwendet, sonst full_resimulation. So
ergibt sich fuer eine abgeschlossene Saison automatisch die vollstaendige
Neusimulation und fuer eine laufende die Restsimulation - ohne dass
irgendwo eine Jahreszahl im Code steht.

Datenbeschaffung
----------------
Saemtliche externen Daten (Spielplan, Teamstaerken) werden EINMAL vor
der Monte-Carlo-Schleife geladen. Innerhalb der Schleife findet kein
einziger API-Request statt - dasselbe Muster wie in season_sim.py.
"""

import random
import statistics
from collections import defaultdict

from src.features.pit_profiles import runtime_cutoff
from src.features.strength_provider import get_cl_team_strengths
from src.predict.poisson import poisson as _poisson
from src.features.team_profile import expected_goals
from src.ml.runtime import current_config as current_ml_config
from src.ml.runtime import resolve_simulation_lambdas
from src.predict.cl_match_sim import _resolve_cl_profile
from src.utils import cache


MODE_FULL_RESIMULATION = "full_resimulation"
MODE_SIMULATE_REMAINING = "simulate_remaining"
VALID_MODES = (MODE_FULL_RESIMULATION, MODE_SIMULATE_REMAINING)

# Zonen der Ligaphase im aktuellen 36er-Format. Bewusst als benannte
# Konstanten und nicht aus der Teamzahl abgeleitet: die Grenzen sind eine
# Regel der UEFA, keine Funktion der Teilnehmerzahl. Analog zu
# ZONE_CONFIGS in season_sim.py, wo die Domestic-Zonen ebenso stehen.
CL_ZONE_DIRECT_LAST = 8      # Plaetze 1-8: direkt im Achtelfinale
CL_ZONE_PLAYOFF_LAST = 24    # Plaetze 9-24: K.-o.-Play-offs, ab 25 raus

# Offizielle Reihenfolge der Ligaphasen-Kriterien, soweit aus unseren
# Daten exakt berechenbar. Disziplinarpunkte und UEFA-Klubkoeffizient
# fehlen bewusst - siehe _rank_table.
TIEBREAK_CRITERIA = (
    "points",
    "goal_difference",
    "goals_for",
    "away_goals",
    "wins",
    "away_wins",
    "opponents_points",
    "opponents_goal_difference",
    "opponents_goals_for",
)

# Kriterien, die uns nicht zuverlaessig vorliegen. Werden NICHT geraten.
TIEBREAK_MISSING = ("disciplinary_points", "uefa_club_coefficient")


def resolve_mode(plan, requested=None):
    """
    Bestimmt den Simulationsmodus.

    Eine ausdrueckliche, gueltige Angabe gewinnt. Sonst entscheidet der
    Spielplan: offene Partien -> Restsimulation, sonst vollstaendige
    Neusimulation. Rein datengetrieben, keine Saison-Sonderfaelle.
    """
    if requested in VALID_MODES:
        return requested
    return MODE_SIMULATE_REMAINING if plan.get("remaining_matches") else MODE_FULL_RESIMULATION


def _empty_row():
    return {
        "played": 0, "wins": 0, "draws": 0, "losses": 0,
        "gf": 0, "ga": 0, "gd": 0, "pts": 0,
        "away_goals": 0, "away_wins": 0,
    }


def _apply_result(table, home_id, away_id, home_goals, away_goals):
    """Traegt ein Ergebnis in beide Tabellenzeilen ein."""
    home = table.get(home_id)
    away = table.get(away_id)

    if home is not None:
        home["played"] += 1
        home["gf"] += home_goals
        home["ga"] += away_goals
        home["gd"] += home_goals - away_goals

    if away is not None:
        away["played"] += 1
        away["gf"] += away_goals
        away["ga"] += home_goals
        away["gd"] += away_goals - home_goals
        # Auswaertstore zaehlen nur fuer das Gastteam.
        away["away_goals"] += away_goals

    if home_goals > away_goals:
        if home is not None:
            home["wins"] += 1
            home["pts"] += 3
        if away is not None:
            away["losses"] += 1
    elif home_goals < away_goals:
        if away is not None:
            away["wins"] += 1
            away["away_wins"] += 1
            away["pts"] += 3
        if home is not None:
            home["losses"] += 1
    else:
        if home is not None:
            home["draws"] += 1
            home["pts"] += 1
        if away is not None:
            away["draws"] += 1
            away["pts"] += 1


def build_base_table(team_ids, finished_matches=None):
    """
    Ausgangstabelle vor der Simulation.

    Ohne finished_matches starten alle Teams bei null - das ist der
    Zustand fuer full_resimulation. Mit finished_matches entsteht der
    reale Zwischenstand fuer simulate_remaining.
    """
    table = {team_id: _empty_row() for team_id in team_ids}

    for match in finished_matches or []:
        _apply_result(
            table,
            match["home_id"], match["away_id"],
            match["home_goals"], match["away_goals"],
        )

    return table


def build_opponent_map(fixtures):
    """
    Gegnerliste je Team ueber die GESAMTE Ligaphase.

    Grundlage der gegnerabhaengigen Tiebreaker. Bewusst aus allen
    Fixtures gebaut, nicht nur aus den simulierten: die offiziellen
    Kriterien beziehen sich auf alle acht Ligaphasen-Gegner eines Teams,
    unabhaengig davon, welche Partien in diesem Lauf gewuerfelt wurden.
    """
    opponents = defaultdict(list)

    for fixture in fixtures:
        opponents[fixture["home_id"]].append(fixture["away_id"])
        opponents[fixture["away_id"]].append(fixture["home_id"])

    return dict(opponents)


def _rank_table(keys, table, opponents, fallback_keys):
    """
    Sortiert eine Ligaphasen-Tabelle nach der offiziellen Kaskade.

    Reihenfolge (alle absteigend):
        Punkte -> Tordifferenz -> erzielte Tore -> Auswaertstore ->
        Siege -> Auswaertssiege -> Punkte der Gegner ->
        Tordifferenz der Gegner -> Tore der Gegner

    Danach fehlen offiziell noch Disziplinarpunkte und der UEFA-
    Klubkoeffizient. Beides liegt uns nicht vor und wird NICHT geschaetzt.
    Statt einer zufaelligen Reihenfolge greift ein deterministischer
    Schluessel (stabile Team-ID), damit derselbe Lauf immer dasselbe
    Ergebnis liefert. Wo er tatsaechlich den Ausschlag gab, wird das
    gemeldet statt verschwiegen.

    Rueckgabe: (sortierte_keys, fallback_noetig)
    """
    ranking_keys = {}

    for key in keys:
        row = table[key]

        opp_points = opp_gd = opp_gf = 0
        for opponent in opponents.get(key, ()):
            opp_row = table.get(opponent)
            if opp_row is None:
                continue
            opp_points += opp_row["pts"]
            opp_gd += opp_row["gd"]
            opp_gf += opp_row["gf"]

        # Negiert, damit aufsteigendes Sortieren absteigende Rangfolge ergibt.
        ranking_keys[key] = (
            -row["pts"],
            -row["gd"],
            -row["gf"],
            -row["away_goals"],
            -row["wins"],
            -row["away_wins"],
            -opp_points,
            -opp_gd,
            -opp_gf,
        )

    ordered = sorted(keys, key=lambda k: (ranking_keys[k], fallback_keys[k]))

    # Griff der Fallback? Nur dann, wenn zwei benachbarte Teams in ALLEN
    # berechenbaren Kriterien exakt gleich sind.
    fallback_needed = False
    previous = None
    for key in ordered:
        current = ranking_keys[key]
        if previous is not None and current == previous:
            fallback_needed = True
            break
        previous = current

    return ordered, fallback_needed


def simulate_cl_league_phase(
    plan,
    mode=None,
    simulations=10000,
    season=None,
    seed=None,
    strengths=None,
):
    """
    Simuliert die Ligaphase vielfach und verdichtet die Ergebnisse.

    plan: Rueckgabe von cl_fixture_plan.build_cl_league_phase_plan()
    mode: einer aus VALID_MODES, sonst wird er aus dem Plan abgeleitet
    strengths: nur fuer Tests, um die Staerkebeschaffung zu umgehen
    """
    mode = resolve_mode(plan, mode)
    rng = random.Random(seed)

    fixtures = plan["fixtures"]
    team_ids = sorted(plan["team_ids"])

    if mode == MODE_FULL_RESIMULATION:
        # Reale Paarungen behalten, reale Ergebnisse verwerfen.
        fixtures_to_simulate = fixtures
        base = build_base_table(team_ids)
    else:
        fixtures_to_simulate = plan["remaining_matches"]
        base = build_base_table(team_ids, plan["finished_matches"])

    # --- Alles Externe EINMAL beschaffen, vor der Schleife ---
    if strengths is None:
        # Eine Saisonsimulation rechnet vom HEUTIGEN Kenntnisstand aus
        # weiter: Die bereits gespielten Partien stehen im Plan, die
        # restlichen werden simuliert. Der Stichtag ist deshalb "jetzt"
        # und wird - wie im Einzelspiel - am Rand bestimmt und in den
        # Schluessel aufgenommen.
        cutoff = runtime_cutoff()
        strengths = cache.cached_call(
            key=f"cl_strengths:{season}:{cutoff}",
            ttl_seconds=60 * 30,
            loader=lambda: get_cl_team_strengths(season=season, cutoff=cutoff),
        )

    league_avg = strengths["league_avg"]
    teams = plan["teams"]

    profiles = {}
    resolutions = {}
    for team_id in team_ids:
        team_name = (teams.get(team_id) or {}).get("team_name")
        profile, resolution = _resolve_cl_profile(strengths, team_id, team_name)
        profiles[team_id] = profile
        resolutions[team_id] = resolution

    # Erwartete Tore je Paarung einmal vorberechnen. Sie aendern sich
    # waehrend der Laeufe nicht.
    #
    # Die ML-Anbindung (C7) sitzt in derselben Schleife: einmal je
    # Paarung, nicht je Simulationslauf. Im Standardmodus off gibt
    # resolve_simulation_lambdas die Baselinewerte unveraendert zurueck
    # und laedt kein Modell - die Tabelle entsteht dann bitgleich wie
    # zuvor. Es ist dieselbe Funktion wie in cl_match_sim; eine zweite
    # Fassung der Entscheidung waere ein zweiter Ort, an dem sie
    # auseinanderlaufen kann.
    ml_config = current_ml_config()
    prepared = []
    ml_angewandt = 0
    for fixture in fixtures_to_simulate:
        home_id = fixture["home_id"]
        away_id = fixture["away_id"]
        xh, xa = expected_goals(profiles[home_id], profiles[away_id], league_avg)
        ml = resolve_simulation_lambdas(
            xh, xa,
            home_profile=profiles[home_id], away_profile=profiles[away_id],
            home_resolution=resolutions.get(home_id),
            away_resolution=resolutions.get(away_id),
            config=ml_config)
        if ml["ml_applied_to_production"]:
            ml_angewandt += 1
        prepared.append((home_id, away_id, ml["lambda_home"],
                         ml["lambda_away"]))

    opponents = build_opponent_map(fixtures)

    # Deterministischer letzter Schluessel: stabile Team-ID.
    fallback_keys = {team_id: str(team_id) for team_id in team_ids}

    # --- Monte Carlo ---
    position_counts = {tid: defaultdict(int) for tid in team_ids}
    positions_seen = {tid: [] for tid in team_ids}
    points_sum = defaultdict(float)
    gd_sum = defaultdict(float)
    gf_sum = defaultdict(float)
    ga_sum = defaultdict(float)
    wins_sum = defaultdict(float)
    fallback_runs = 0

    for _ in range(simulations):
        table = {tid: dict(base[tid]) for tid in team_ids}

        for home_id, away_id, xh, xa in prepared:
            _apply_result(table, home_id, away_id, _poisson(xh, rng), _poisson(xa, rng))

        ordered, fallback_needed = _rank_table(team_ids, table, opponents, fallback_keys)
        if fallback_needed:
            fallback_runs += 1

        for rank, team_id in enumerate(ordered, start=1):
            row = table[team_id]
            position_counts[team_id][rank] += 1
            positions_seen[team_id].append(rank)
            points_sum[team_id] += row["pts"]
            gd_sum[team_id] += row["gd"]
            gf_sum[team_id] += row["gf"]
            ga_sum[team_id] += row["ga"]
            wins_sum[team_id] += row["wins"]

    return _build_result(
        plan=plan,
        mode=mode,
        team_ids=team_ids,
        teams=teams,
        profiles=profiles,
        resolutions=resolutions,
        base=base,
        position_counts=position_counts,
        positions_seen=positions_seen,
        points_sum=points_sum,
        gd_sum=gd_sum,
        gf_sum=gf_sum,
        ga_sum=ga_sum,
        wins_sum=wins_sum,
        simulations=simulations,
        fixtures_simulated=len(prepared),
        fallback_runs=fallback_runs,
        league_avg=league_avg,
        seed=seed,
        ml_summary={
            "mode": ml_config["mode"],
            "fixtures_with_ml": ml_angewandt,
            "fixtures_total": len(prepared),
            "applied_weight": (ml_config["weight"] if ml_angewandt else 0.0),
        },
    )


def _build_result(plan, mode, team_ids, teams, profiles, resolutions, base,
                  position_counts, positions_seen, points_sum, gd_sum,
                  gf_sum, ga_sum, wins_sum, simulations, fixtures_simulated,
                  fallback_runs, league_avg, seed, ml_summary=None):
    n_teams = len(team_ids)
    entries = []

    # Wie viele der eigenen Partien sind in diesem Modus noch offen?
    games_open = defaultdict(int)
    if mode == MODE_SIMULATE_REMAINING:
        for fixture in plan["remaining_matches"]:
            games_open[fixture["home_id"]] += 1
            games_open[fixture["away_id"]] += 1

    for team_id in team_ids:
        counts = position_counts.get(team_id, {})
        info = teams.get(team_id) or {}
        profile = profiles.get(team_id) or {}
        start = base.get(team_id) or _empty_row()

        def pct_range(low, high):
            total = sum(counts.get(p, 0) for p in range(low, high + 1))
            return round(100.0 * total / simulations, 1)

        expected_pos = (
            sum(pos * cnt for pos, cnt in counts.items()) / simulations
            if counts else n_teams
        )
        seen = positions_seen.get(team_id) or []
        median_pos = statistics.median(seen) if seen else expected_pos

        entries.append({
            "team_id": team_id,
            "team_name": info.get("team_name") or str(team_id),
            "crest": info.get("crest"),

            # Realer Ausgangsstand. Bei full_resimulation ist er bewusst
            # leer: dort startet jedes Team wieder bei null.
            "current_points": start["pts"],
            "current_played": start["played"],
            "games_remaining": games_open.get(team_id, 0),

            "expected_position": round(expected_pos, 1),
            "median_position": round(median_pos, 1),
            "expected_points": round(points_sum.get(team_id, 0) / simulations, 1),
            "expected_wins": round(wins_sum.get(team_id, 0) / simulations, 1),
            "expected_gd": round(gd_sum.get(team_id, 0) / simulations, 1),
            "expected_goals_for": round(gf_sum.get(team_id, 0) / simulations, 1),
            "expected_goals_against": round(ga_sum.get(team_id, 0) / simulations, 1),

            "top_seed_pct": round(100.0 * counts.get(1, 0) / simulations, 1),
            "direct_pct": pct_range(1, CL_ZONE_DIRECT_LAST),
            "playoff_pct": pct_range(CL_ZONE_DIRECT_LAST + 1, CL_ZONE_PLAYOFF_LAST),
            "eliminated_pct": pct_range(CL_ZONE_PLAYOFF_LAST + 1, n_teams),

            # Herkunft der Staerkewerte, damit sichtbar bleibt, worauf die
            # Prognose beruht - dieselbe Semantik wie bei der
            # Einzelspielsimulation (cl_match_sim._resolve_cl_profile).
            "resolution": resolutions.get(team_id),
            "matches_used": profile.get("matches_used", 0),
            "attack_home": round(profile.get("attack_home", 1.0), 2),
            "attack_away": round(profile.get("attack_away", 1.0), 2),
            "defence_home": round(profile.get("defence_home", 1.0), 2),
            "defence_away": round(profile.get("defence_away", 1.0), 2),

            "position_probs": {
                str(pos): round(100.0 * cnt / simulations, 1)
                for pos, cnt in sorted(counts.items())
                if cnt / simulations >= 0.005
            },
        })

    # EINE Sortierung nach erwartetem Endplatz, danach wird der angezeigte
    # Rang vergeben. So laufen Reihenfolge und Nummer nie auseinander.
    entries.sort(key=lambda e: (e["expected_position"], -e["expected_points"]))
    for rank, entry in enumerate(entries, start=1):
        entry["rank"] = rank

    resolution_counts = defaultdict(int)
    for resolution in resolutions.values():
        resolution_counts[resolution] += 1

    return {
        "competition_code": "cl",
        "phase": "league",
        "mode": mode,
        "simulations": simulations,
        "seed": seed,
        "teams_total": n_teams,
        "fixtures_total": len(plan["fixtures"]),
        "fixtures_simulated": fixtures_simulated,
        "fixtures_fixed": len(plan["fixtures"]) - fixtures_simulated,
        "played_matchdays": plan.get("played_matchdays", 0),
        "entries": entries,
        "zones": {
            "direct_last": CL_ZONE_DIRECT_LAST,
            "playoff_last": CL_ZONE_PLAYOFF_LAST,
        },
        "tiebreak": {
            "criteria": list(TIEBREAK_CRITERIA),
            "missing_criteria": list(TIEBREAK_MISSING),
            "fallback_used": fallback_runs > 0,
            "fallback_runs": fallback_runs,
        },
        "league_avg": {
            "home_goals": round(league_avg.get("home_goals", 0), 2),
            "away_goals": round(league_avg.get("away_goals", 0), 2),
            "total_goals": round(league_avg.get("total_goals", 0), 2),
        },
        "data_quality": {
            "teams_total": n_teams,
            "teams_domestic_history": resolution_counts.get("domestic_history", 0),
            "teams_cl_current": resolution_counts.get("cl_current_season", 0),
            "teams_neutral": resolution_counts.get("neutral", 0),
        },
        "fixture_coverage": plan.get("coverage", {}),
        # Additiv (C7). Im Standardmodus off steht hier nur, dass ML aus
        # ist; bestehende Clients ignorieren das Feld.
        "ml": ml_summary or {"mode": "off", "fixtures_with_ml": 0,
                             "fixtures_total": fixtures_simulated,
                             "applied_weight": 0.0},
    }
