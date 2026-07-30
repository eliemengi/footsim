from flask import Flask, jsonify, render_template, request, send_file
import os
import io
import tempfile
import shutil
import requests
from werkzeug.utils import secure_filename
from pypdf import PdfWriter, PdfReader
from PIL import Image

from src.predict.matches_to_predict import (
    MATCHES_TO_PREDICT_CL_RO16,
    MATCHES_TO_PREDICT_CL_QF,
    MATCHES_TO_PREDICT_CL_SF,
    MATCHES_TO_PREDICT_CL,
    MATCHES_TO_PREDICT_EL
)

from src.predict.simulate_scores import simulate_selected_match

from src.api.league_api import (
    ApiUnavailable,
    get_matchday_matches,
    get_season_info,
    get_current_season,
    is_current_season,
    get_standings,
    get_scorers,
    get_matchday_match_options,
    get_finished_season_matches,
    get_competition_teams,
    get_cup_matches,
)

from src.features.league_stats import build_league_profile, build_comparison
from src.features import cl_stats
from src.predict.season_sim import simulate_season
from src.predict.fixture_plan import build_season_plan
from src.predict.league_match_sim import simulate_league_match
from src.api import apisports_api
from src.api.apisports_api import ApisportsUnavailable, ApisportsRateLimit
from src.utils import cache
from src.utils.disk_cache import disk_cached_call, read_entry as disk_read_entry
from src.data import transfer_loader
from src.data.player_stats_loader import get_player_target_league_stats
from src.features import transfer_comparison

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024


# =============================================================================
#  KONFIGURATION
#
#  Das ist der einzige Block, den du im normalen Betrieb anfassen musst.
#  Alles darunter bleibt unveraendert.
# =============================================================================

# Wenn True, sind ALLE Spieltage sofort spielbar.
# Praktisch zum Testen oder wenn du die Sperre generell nicht mehr willst.
UNLOCK_ALL_MATCHDAYS = False

# Die Saison wird automatisch von football-data.org erkannt.
# Nur setzen, wenn du bewusst eine andere Saison erzwingen willst,
# zum Beispiel SEASON_OVERRIDE = 2025 fuer die Vorsaison.
SEASON_OVERRIDE = None

# Wie viele abgeschlossene Saisons zusaetzlich zur laufenden auswaehlbar sind.
# 1 bedeutet: laufende Saison plus die davor.
SEASON_HISTORY = 1

# Wettbewerb, dessen Saison als Bezugspunkt fuer die Auswahl dient.
SEASON_REFERENCE_CODE = "BL1"


LEAGUE_CONFIG = {
    "bl1": {
        "name": "Bundesliga",
        "api_code": "BL1",
        "country": "Deutschland",
        "total_matchdays": 34,

        # >>> HIER SPIELTAGE FREISCHALTEN <<<
        # Beispiele:
        #   [1]              nur Spieltag 1
        #   [1, 2, 3]        Spieltag 1 bis 3
        #   list(range(1, 6))  Spieltag 1 bis 5
        "unlocked_matchdays": [1],
    },
    "pl": {
        "name": "Premier League",
        "api_code": "PL",
        "country": "England",
        "total_matchdays": 38,
        "unlocked_matchdays": [1],
    },
    "pd": {
        "name": "LaLiga",
        "api_code": "PD",
        "country": "Spanien",
        "total_matchdays": 38,
        "unlocked_matchdays": [1],
    },
    "sa": {
        "name": "Serie A",
        "api_code": "SA",
        "country": "Italien",
        "total_matchdays": 38,
        "unlocked_matchdays": [1],
    },
    "fl1": {
        "name": "Ligue 1",
        "api_code": "FL1",
        "country": "Frankreich",
        "total_matchdays": 34,
        "unlocked_matchdays": [1],
    },
}


# Pokalwettbewerbe laufen ueber die manuell gepflegten Paarungen
# in src/predict/matches_to_predict.py und nicht ueber Spieltage.
CUP_CONFIG = {
    "cl": {
        "name": "Champions League",
        "api_code": "CL",
        "available": True,
        "coming_soon_text": "",
    },
    "el": {
        "name": "Europa League",
        "api_code": "EL",
        "available": False,
        "coming_soon_text": "Die Europa League wird spaeter freigeschaltet.",
    },
}

# =============================================================================
#  ENDE KONFIGURATION
# =============================================================================


COMPETITION_MATCHES = {
    "cl": MATCHES_TO_PREDICT_CL,
    "el": MATCHES_TO_PREDICT_EL,
}

CREST_BASE_URL = "https://crests.football-data.org"


def resolve_requested_season(raw_value):
    """
    Liest den Saisonparameter aus der Anfrage.

    Ohne Angabe gilt die laufende Saison. SEASON_OVERRIDE hat Vorrang,
    falls jemand bewusst eine Saison erzwingen will.
    """
    if SEASON_OVERRIDE is not None:
        return int(SEASON_OVERRIDE)

    if raw_value in (None, "", "current"):
        return None

    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def build_season_options():
    """
    Liste der auswaehlbaren Saisons.
    Die laufende steht vorn und ist die Voreinstellung.
    """
    current = get_current_season(SEASON_REFERENCE_CODE)

    options = []

    for offset in range(0, SEASON_HISTORY + 1):
        year = current - offset
        options.append({
            "season": year,
            "label": f"{year}/{str(year + 1)[2:]}",
            "is_current": offset == 0,
            "is_complete": offset > 0,
            "description": "Laufende Saison" if offset == 0 else "Abgeschlossen",
        })

    return options


def is_matchday_unlocked(competition_code, matchday, season=None):
    """
    Ein Spieltag ist spielbar, wenn er freigeschaltet wurde.

    Bei abgeschlossenen Saisons entfaellt die Sperre komplett. Dort sind
    alle Partien laengst gespielt, eine Sperre waere sinnlos.
    """
    config = LEAGUE_CONFIG.get(competition_code)
    if not config:
        return False

    if season is not None and not is_current_season(config["api_code"], season):
        return True

    if UNLOCK_ALL_MATCHDAYS:
        return True

    return matchday in config["unlocked_matchdays"]


def build_match_response(match_dict):
    matches = []

    for match_id, teams in match_dict.items():
        home_team, away_team = teams
        matches.append({
            "id": match_id,
            "home_team": home_team,
            "away_team": away_team,
            "label": f"{home_team} vs {away_team}"
        })

    return matches


def parse_league_codes(raw):
    """Liest die Ligaliste aus dem Parameter, entfernt Unbekanntes und Doppeltes."""
    codes = [c.strip().lower() for c in raw.split(",") if c.strip()]
    codes = [c for c in codes if c in LEAGUE_CONFIG]

    seen = set()
    return [c for c in codes if not (c in seen or seen.add(c))]


def api_error(error, status=503):
    return jsonify({
        "error": str(error),
        "code": "EXTERNAL_API_UNAVAILABLE"
    }), status


# =============================================================================
#  SEITEN
# =============================================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/manifest.json")
def manifest():
    from flask import send_from_directory
    return send_from_directory("static", "manifest.json", mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    from flask import send_from_directory
    return send_from_directory("static", "sw.js", mimetype="application/javascript")


@app.route("/impressum")
def impressum():
    return render_template("impressum.html")


@app.route("/datenschutz")
def datenschutz():
    return render_template("datenschutz.html")


# =============================================================================
#  API: SAISONS
# =============================================================================

@app.route("/api/seasons", methods=["GET"])
def api_seasons():
    return jsonify(build_season_options())


# =============================================================================
#  API: WETTBEWERBE
# =============================================================================

@app.route("/api/competitions", methods=["GET"])
def get_competitions():
    season = resolve_requested_season(request.args.get("season"))

    competitions = []

    for code, config in LEAGUE_CONFIG.items():
        past_season = season is not None and not is_current_season(config["api_code"], season)

        if past_season:
            sub = "Saison abgeschlossen, alle Spieltage"
        elif UNLOCK_ALL_MATCHDAYS:
            sub = "Alle Spieltage verfuegbar"
        else:
            unlocked = config["unlocked_matchdays"]
            if not unlocked:
                sub = "Noch keine Spieltage freigeschaltet"
            elif len(unlocked) == 1:
                sub = f"Spieltag {unlocked[0]} verfuegbar"
            else:
                sub = f"Spieltag {min(unlocked)} bis {max(unlocked)} verfuegbar"

        competitions.append({
            "code": code,
            "name": config["name"],
            "country": config["country"],
            "type": "league",
            "emblem": f"{CREST_BASE_URL}/{config['api_code']}.png",
            "available": True,
            "subtitle": sub,
            "coming_soon_text": "",
        })

    for code, config in CUP_CONFIG.items():
        competitions.append({
            "code": code,
            "name": config["name"],
            "country": "Europa",
            "type": "cup",
            "emblem": f"{CREST_BASE_URL}/{config['api_code']}.png",
            "available": config["available"],
            "subtitle": "Verfuegbar" if config["available"] else "Bald verfuegbar",
            "coming_soon_text": config["coming_soon_text"],
        })

    return jsonify(competitions)


# =============================================================================
#  API: SPIELTAGE
# =============================================================================

@app.route("/api/matchdays", methods=["GET"])
def get_matchdays():
    """
    Liefert ALLE Spieltage der Saison.
    Gesperrte Spieltage sind sichtbar, aber nicht anwaehlbar.
    """
    competition_code = request.args.get("competition", "").lower()
    season = resolve_requested_season(request.args.get("season"))

    config = LEAGUE_CONFIG.get(competition_code)

    if not config:
        return jsonify([])

    try:
        info = get_season_info(config["api_code"])
        current = info.get("current_matchday") or 1
        is_running = is_current_season(config["api_code"], season)
    except ApiUnavailable:
        current = 1
        is_running = True

    matchdays = []

    for day in range(1, config["total_matchdays"] + 1):
        unlocked = is_matchday_unlocked(competition_code, day, season)

        matchdays.append({
            "matchday": day,
            "available": unlocked,
            "label": f"Spieltag {day}",
            "is_current": is_running and day == current,
            "message": "" if unlocked else "Noch nicht freigeschaltet",
        })

    return jsonify(matchdays)


# =============================================================================
#  API: SPIELE
# =============================================================================

@app.route("/api/matches", methods=["GET"])
def get_matches():
    competition_code = request.args.get("competition", "cl").lower()
    season = resolve_requested_season(request.args.get("season"))

    if competition_code in LEAGUE_CONFIG:
        config = LEAGUE_CONFIG[competition_code]

        try:
            matchday = int(request.args.get("matchday", 1))
        except (TypeError, ValueError):
            return jsonify({"error": "Ungueltiger Spieltag"}), 400

        if not is_matchday_unlocked(competition_code, matchday, season):
            return jsonify([])

        try:
            matches = get_matchday_match_options(
                competition_code=competition_code,
                api_code=config["api_code"],
                matchday=matchday,
                season=season,
            )
            return jsonify(matches)
        except ApiUnavailable as error:
            return api_error(error)

    if competition_code == "cl":
        knockout_round = request.args.get("round", "ro16").lower()

        rounds = {
            "ro16": MATCHES_TO_PREDICT_CL_RO16,
            "qf": MATCHES_TO_PREDICT_CL_QF,
            "sf": MATCHES_TO_PREDICT_CL_SF,
        }

        return jsonify(build_match_response(rounds.get(knockout_round, {})))

    return jsonify(build_match_response(COMPETITION_MATCHES.get(competition_code, {})))


# =============================================================================
#  API: TABELLE
# =============================================================================

@app.route("/api/standings", methods=["GET"])
def api_standings():
    competition_code = request.args.get("competition", "").lower()
    table_type = request.args.get("type", "TOTAL").upper()
    season = resolve_requested_season(request.args.get("season"))

    config = LEAGUE_CONFIG.get(competition_code)

    if not config:
        return jsonify({"error": "Fuer diesen Wettbewerb gibt es keine Tabelle"}), 400

    if table_type not in ("TOTAL", "HOME", "AWAY"):
        table_type = "TOTAL"

    try:
        standings = get_standings(config["api_code"], season=season)
    except ApiUnavailable as error:
        return api_error(error)

    tables = standings.get("tables") or {}
    rows = tables.get(table_type) or tables.get("TOTAL") or []

    return jsonify({
        "competition": config["name"],
        "season": standings.get("season"),
        "type": table_type,
        "available_types": [t for t in ("TOTAL", "HOME", "AWAY") if t in tables],
        "table": rows,
    })


# =============================================================================
#  API: TORJAEGER
# =============================================================================

@app.route("/api/scorers", methods=["GET"])
def api_scorers():
    competition_code = request.args.get("competition", "").lower()
    season = resolve_requested_season(request.args.get("season"))

    try:
        limit = min(int(request.args.get("limit", 20)), 50)
    except (TypeError, ValueError):
        limit = 20

    config = LEAGUE_CONFIG.get(competition_code)

    if not config:
        return jsonify({"error": "Fuer diesen Wettbewerb gibt es keine Torjaegerliste"}), 400

    try:
        data = get_scorers(config["api_code"], season=season, limit=limit)
    except ApiUnavailable as error:
        return api_error(error)

    return jsonify({
        "competition": config["name"],
        "season": data.get("season"),
        "scorers": data.get("scorers", []),
    })


# =============================================================================
#  API: LIGENVERGLEICH, NATIONAL
# =============================================================================

@app.route("/api/compare", methods=["GET"])
def api_compare():
    """
    Vergleicht zwei bis fuenf Ligen anhand echter Saisondaten.
    Aufruf: /api/compare?leagues=bl1,pd,sa&season=2025
    """
    codes = parse_league_codes(request.args.get("leagues", ""))
    season = resolve_requested_season(request.args.get("season"))

    if len(codes) < 2:
        return jsonify({"error": "Bitte mindestens zwei Ligen auswaehlen"}), 400

    if len(codes) > 5:
        return jsonify({"error": "Maximal fuenf Ligen gleichzeitig"}), 400

    profiles = []

    for code in codes:
        config = LEAGUE_CONFIG[code]

        try:
            standings = get_standings(config["api_code"], season=season)
            matches = get_finished_season_matches(config["api_code"], season=season)
        except ApiUnavailable as error:
            return api_error(error)

        profiles.append(
            build_league_profile(code, config["name"], standings, matches)
        )

    result = build_comparison(profiles)
    result["season"] = profiles[0].get("season") if profiles else None
    return jsonify(result)


# =============================================================================
#  API: LIGENVERGLEICH INNERHALB EINES POKALWETTBEWERBS
# =============================================================================

@app.route("/api/cup-compare", methods=["GET"])
def api_cup_compare():
    """
    Vergleicht Ligen anhand der Leistung ihrer Vereine in einem
    Pokalwettbewerb, in der Regel der Champions League.

    Aufruf: /api/cup-compare?leagues=bl1,pd,pl&phase=all&season=2025&cup=cl

    phase:
        all       komplette Saison, Ligaphase und K o Phase
        league    nur die Ligaphase
        knockout  nur die K o Phase
    """
    codes = parse_league_codes(request.args.get("leagues", ""))
    season = resolve_requested_season(request.args.get("season"))
    phase = (request.args.get("phase") or "all").lower()
    cup_code = (request.args.get("cup") or "cl").lower()

    if phase not in cl_stats.PHASE_FILTERS:
        phase = "all"

    cup = CUP_CONFIG.get(cup_code)

    if not cup:
        return jsonify({"error": "Unbekannter Wettbewerb"}), 400

    if len(codes) < 2:
        return jsonify({"error": "Bitte mindestens zwei Ligen auswaehlen"}), 400

    if len(codes) > 5:
        return jsonify({"error": "Maximal fuenf Ligen gleichzeitig"}), 400

    try:
        matches = get_cup_matches(cup["api_code"], season=season)
    except ApiUnavailable as error:
        return api_error(error)

    if not matches:
        return jsonify({
            "error": "Fuer diese Saison liegen noch keine gespielten Partien vor",
            "code": "NO_DATA"
        }), 404

    # Zuordnung Verein zu Liga fuer genau diese Saison aufbauen
    teams_by_league = {}

    for code in codes:
        config = LEAGUE_CONFIG[code]
        try:
            teams_by_league[code] = get_competition_teams(config["api_code"], season=season)
        except ApiUnavailable as error:
            return api_error(error)

    team_league_map = cl_stats.build_team_league_map(teams_by_league)

    allowed_stages = cl_stats.PHASE_FILTERS[phase]
    include_knockout = phase in ("all", "knockout")

    counters = cl_stats.collect_league_results(matches, team_league_map, allowed_stages)
    participation = cl_stats.collect_stage_participation(matches)
    winner_id = cl_stats.find_winner(matches)
    progression = cl_stats.compute_progression(participation, winner_id, team_league_map, codes)

    profiles = []

    for code in codes:
        config = LEAGUE_CONFIG[code]
        profiles.append(cl_stats.build_cup_profile(
            league_code=code,
            league_name=config["name"],
            emblem=f"{CREST_BASE_URL}/{config['api_code']}.png",
            counters=counters.get(code),
            progression=progression.get(code),
        ))

    # Ligen ohne einen einzigen Teilnehmer machen den Vergleich unbrauchbar
    without_teams = [p["name"] for p in profiles if p["metrics"]["teams"] == 0]

    result = cl_stats.build_cup_comparison(profiles, phase, include_knockout)
    result["cup"] = {"code": cup_code, "name": cup["name"]}
    result["season"] = season if season is not None else get_current_season(cup["api_code"])
    result["stages_played"] = [
        cl_stats.STAGE_LABELS[s]
        for s in cl_stats.STAGE_ORDER
        if participation.get(s)
    ]
    result["notice"] = (
        f"Ohne Teilnehmer in diesem Wettbewerb: {', '.join(without_teams)}"
        if without_teams else ""
    )

    return jsonify(result)


# =============================================================================
#  API: SIMULATION
# =============================================================================

@app.route("/api/simulate", methods=["POST"])
def simulate():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Request Body fehlt"}), 400

    competition_code = data.get("competition", "cl")
    match_id = data.get("match_id")
    simulations = data.get("simulations", 5000)
    use_seed = data.get("use_seed", False)
    leg_mode = data.get("leg_mode", "first")

    try:
        simulations = max(100, min(int(simulations), 50000))
    except (TypeError, ValueError):
        simulations = 5000

    try:
        if competition_code in LEAGUE_CONFIG:
            home_team = data.get("home_team")
            away_team = data.get("away_team")

            if not home_team or not away_team:
                return jsonify({"error": "home_team oder away_team fehlt"}), 400

            # Ligaspiele laufen ueber das moderne Staerkemodell mit
            # garantierter Fallback-Kette. Damit sind auch Aufsteiger
            # und neue Teams IMMER simulierbar - der alte Pfad ueber
            # team_matches.json kannte sie nicht und brach ab.
            config = LEAGUE_CONFIG[competition_code]
            result = simulate_league_match(
                competition_code=competition_code,
                api_code=config["api_code"],
                home_team=home_team,
                away_team=away_team,
                home_id=data.get("home_id"),
                away_id=data.get("away_id"),
                season=resolve_requested_season(data.get("season")),
                simulations=simulations,
                use_seed=use_seed,
            )
            return jsonify(result)

        if not match_id:
            return jsonify({"error": "match_id fehlt"}), 400

        if competition_code == "cl":
            result = simulate_selected_match(
                match_id=match_id,
                simulations=simulations,
                use_seed=use_seed,
                leg_mode=leg_mode
            )
            return jsonify(result)

        return jsonify({"error": "Aktuell nicht verfuegbar."}), 400

    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        return jsonify({"error": f"Interner Fehler: {str(error)}"}), 500


# =============================================================================
#  API: STATUS
# =============================================================================

@app.route("/api/status", methods=["GET"])
def api_status():
    """Kleine Diagnoseseite. Zeigt erkannte Saison und Cache Zustand."""
    seasons = {}

    for code, config in LEAGUE_CONFIG.items():
        info = get_season_info(config["api_code"])
        seasons[code] = {
            "name": config["name"],
            "season": info["season"],
            "current_matchday": info["current_matchday"],
            "auto_detected": info["auto_detected"],
            "unlocked_matchdays": config["unlocked_matchdays"],
        }

    return jsonify({
        "unlock_all": UNLOCK_ALL_MATCHDAYS,
        "season_override": SEASON_OVERRIDE,
        "season_history": SEASON_HISTORY,
        "season_options": build_season_options(),
        "leagues": seasons,
        "cache": cache.stats(),
    })



# =============================================================================
#  API: SAISONSIMULATION
# =============================================================================

@app.route("/api/season-sim", methods=["GET"])
def api_season_sim():
    """
    Simuliert den Ausgang einer Ligasaison.

    Ablauf:
      1. Aktuelle Tabelle holen (gespielte Punkte, Tordifferenz)
      2. Alle Spieltage durchgehen, noch nicht gespielte Partien sammeln
      3. season_sim.simulate_season aufrufen
      4. Ergebnis ans Frontend schicken

    Aufruf: /api/season-sim?competition=bl1&simulations=10000
    """
    competition_code = request.args.get("competition", "").lower()
    season = resolve_requested_season(request.args.get("season"))

    try:
        simulations = max(1000, min(int(request.args.get("simulations", 10000)), 50000))
    except (TypeError, ValueError):
        simulations = 10000

    config = LEAGUE_CONFIG.get(competition_code)
    if not config:
        return jsonify({"error": "Unbekannte Liga"}), 400

    try:
        # Tabelle holen
        standings_data = get_standings(config["api_code"], season=season)
        table = standings_data.get("tables", {}).get("TOTAL", [])

        if not table:
            return jsonify({"error": "Keine Tabellendaten verfügbar"}), 404

        total_matchdays = config["total_matchdays"]

        # Vollstaendigen Saisonplan laden: EIN API-Request liefert alle
        # 306 bzw. 380 Partien. Die Saisonsimulation haengt damit NICHT
        # mehr an der UI-Freischaltung einzelner Spieltage - die gilt
        # nur fuer die Einzelspielansicht.
        plan = build_season_plan(
            config["api_code"],
            season=season,
            expected_team_count=len(table),
        )

        coverage = plan["coverage"]

        # Harte Validierung VOR der Monte-Carlo-Simulation: Fuer jedes
        # Team muss gespielte + verbleibende Spiele die volle Doppelrunde
        # ergeben. Ist der Plan unvollstaendig, gibt es KEINE serioes
        # wirkende Tabelle, sondern eine klare Fehlermeldung.
        if not coverage["ok"]:
            return jsonify({
                "error": (
                    "Die vollständige Saisonprognose konnte nicht berechnet "
                    "werden, weil der Spielplan unvollständig ist."
                ),
                "fixture_coverage": coverage,
                "invalid_matches": plan["invalid_matches"][:20],
            }), 503

        result = simulate_season(
            competition_code=competition_code,
            standings_table=table,
            remaining_matches=plan["remaining_matches"],
            simulations=simulations,
            current_matches=plan["finished_matches"],
            season=plan["season"],
            fixture_coverage=coverage,
        )

        result["competition"] = config["name"]
        result["season"] = standings_data.get("season")
        result["played_matchdays"] = plan["played_matchdays"]
        result["total_matchdays"] = total_matchdays

        return jsonify(result)

    except ApiUnavailable as error:
        return api_error(error)
    except Exception as error:
        return jsonify({"error": f"Simulationsfehler: {str(error)}"}), 500


# =============================================================================
#  API: API-SPORTS SCORERS MIT FOTOS
# =============================================================================

@app.route("/api/player-scorers", methods=["GET"])
def api_player_scorers():
    """
    Torjäger mit Spielerfoto von API-Sports.
    Fällt sauber auf football-data.org Daten zurück wenn nicht verfügbar.
    """
    competition_code = request.args.get("competition", "").lower()
    season = resolve_requested_season(request.args.get("season"))

    try:
        limit = min(int(request.args.get("limit", 20)), 50)
    except (TypeError, ValueError):
        limit = 20

    config = LEAGUE_CONFIG.get(competition_code)
    if not config:
        return jsonify({"error": "Unbekannte Liga"}), 400

    # API-Sports Saison: bei season=None nehmen wir 2026 (aktuelle)
    apisports_season = (season - 1) if season else 2025

    try:
        scorers = apisports_api.get_top_scorers(
            competition_code,
            season=apisports_season,
            limit=limit,
        )
        return jsonify({
            "source": "api-sports",
            "competition": config["name"],
            "season": apisports_season,
            "scorers": scorers,
        })

    except ApisportsUnavailable as error:
        # Fallback auf football-data.org.
        # Wir bringen die Daten aufs gleiche Schema wie API-Sports,
        # damit das Frontend nur EIN Format kennen muss. Der einzige
        # echte Unterschied: football-data liefert keine Spielerfotos.
        try:
            data = get_scorers(config["api_code"], season=season, limit=limit)
            return jsonify({
                "source": "football-data",
                "competition": config["name"],
                "season": data.get("season"),
                "scorers": [
                    _normalize_footballdata_scorer(scorer)
                    for scorer in data.get("scorers", [])
                ],
            })
        except ApiUnavailable as fallback_error:
            return api_error(fallback_error)


def _normalize_footballdata_scorer(scorer):
    """
    Uebersetzt einen football-data-Torjaeger auf das API-Sports-Schema.

    So sieht das Frontend immer die gleichen Feldnamen, egal welche
    Quelle geantwortet hat. player_photo bleibt None, weil football-data
    keine Fotos liefert; das Frontend faengt das ueber Initialen ab.
    """
    return {
        "rank": scorer.get("rank"),
        "player_id": scorer.get("player_id"),
        "player_name": scorer.get("player_name"),
        "player_photo": None,
        "nationality": scorer.get("nationality"),
        "age": None,
        "position": scorer.get("position"),
        "team_id": scorer.get("team_id"),
        "team_name": scorer.get("team_name"),
        "team_logo": scorer.get("team_crest"),
        "goals": scorer.get("goals") or 0,
        "assists": scorer.get("assists"),
        "penalties": scorer.get("penalties"),
        "appearances": scorer.get("played_matches"),
        "minutes": None,
        "goals_per_match": scorer.get("goals_per_match"),
        "key_passes": None,
    }


# =============================================================================
#  API: VERLETZUNGEN UND SPERREN
# =============================================================================

@app.route("/api/injuries", methods=["GET"])
def api_injuries():
    competition_code = request.args.get("competition", "").lower()
    season = resolve_requested_season(request.args.get("season"))

    config = LEAGUE_CONFIG.get(competition_code)
    if not config:
        return jsonify({"error": "Unbekannte Liga"}), 400

    apisports_season = (season - 1) if season else 2025

    try:
        injuries = apisports_api.get_injuries(competition_code, season=apisports_season)
        return jsonify({
            "competition": config["name"],
            "season": apisports_season,
            "injuries": injuries,
        })
    except ApisportsUnavailable as error:
        return jsonify({"error": str(error), "injuries": []}), 503


# =============================================================================
#  API: API-SPORTS STATUS
# =============================================================================

@app.route("/api/apisports-status", methods=["GET"])
def api_apisports_status():
    usage = apisports_api.get_request_usage()
    if not usage:
        return jsonify({"available": False, "error": "API-Sports nicht erreichbar"})
    return jsonify({"available": True, **usage})


# =============================================================================
#  API: TRANSFER-VERGLEICH (Liga zu Liga)
# =============================================================================
#
#  Vergleicht zwei Transfergruppen unter denselben Zielbedingungen:
#      Quelliga A -> Zielliga   gegen   Quelliga B -> Zielliga
#  fuer einen bestimmten Saisonwechsel (Sommertransfers).
#
#  Rate-Limit-Schutz (API-Sports: 100 Requests/Tag):
#    1. Jeder einzelne API-Aufruf ist dauerhaft im Disk-Cache
#       (Teams, Transfers, Spielerstatistiken).
#    2. Das komplette Endergebnis wird zusaetzlich gecacht, damit
#       wiederholte Seitenaufrufe exakt 0 API-Requests kosten.
#    3. Faellt die API mitten im Lauf aus, wird ein evtl. vorhandenes
#       aelteres Endergebnis aus dem Cache ausgeliefert.

# Fruehestes Jahr, fuer das API-Sports im Free-Plan verlaesslich
# Transfer- und Statistikdaten liefert.
TRANSFER_COMPARE_MIN_SEASON = 2016

TTL_TRANSFER_COMPARE_FINISHED = 60 * 60 * 24 * 30   # 30 Tage
TTL_TRANSFER_COMPARE_CURRENT  = 60 * 60 * 24        # 24 Stunden


def _build_transfer_group_players(source_league, target_league, season):
    """
    Laedt die Transfers einer Quelliga und ergaenzt jeden Spieler um
    seine normalisierten Zielliga-Statistiken. Spieler-IDs werden
    dedupliziert geladen (kein N+1 fuer denselben Spieler).
    """
    transfers = transfer_loader.load_summer_transfers(
        source_league, target_league, season
    )

    stats_by_player = {}
    for transfer in transfers:
        player_id = transfer["player_id"]
        if player_id in stats_by_player:
            continue
        stats_by_player[player_id] = get_player_target_league_stats(
            player_id, season, target_league
        )

    enriched = []
    for transfer in transfers:
        stats = stats_by_player.get(transfer["player_id"]) or {}
        enriched.append({**transfer, **stats})

    return enriched


@app.route("/api/transfer-compare", methods=["GET"])
def api_transfer_compare():
    from_a = (request.args.get("from_a") or "").lower().strip()
    from_b = (request.args.get("from_b") or "").lower().strip()
    target = (request.args.get("to") or "").lower().strip()
    raw_season = request.args.get("season", "")

    supported = transfer_loader.SUPPORTED_LEAGUES

    # --- Parameter validieren -------------------------------------------
    for code, name in ((from_a, "from_a"), (from_b, "from_b"), (target, "to")):
        if code not in supported:
            return jsonify({
                "error": f"Unbekannter oder nicht unterstuetzter Ligacode "
                         f"fuer '{name}'. Erlaubt: {', '.join(supported)}"
            }), 400

    if from_a == from_b:
        return jsonify({
            "error": "Quelliga A und Quelliga B muessen unterschiedlich sein."
        }), 400

    if target in (from_a, from_b):
        return jsonify({
            "error": "Die Zielliga darf keiner der beiden Quelligen entsprechen."
        }), 400

    try:
        season = int(raw_season)
    except (TypeError, ValueError):
        return jsonify({"error": "Ungueltige Saison."}), 400

    if not (TRANSFER_COMPARE_MIN_SEASON <= season <= apisports_api.CURRENT_SEASON):
        return jsonify({
            "error": f"Saison muss zwischen {TRANSFER_COMPARE_MIN_SEASON} und "
                     f"{apisports_api.CURRENT_SEASON} liegen."
        }), 400

    # --- Ergebnis laden (Cache zuerst) ----------------------------------
    result_key = f"transfercompare:{from_a}:{from_b}:{target}:{season}"
    result_ttl = (
        TTL_TRANSFER_COMPARE_FINISHED
        if season < apisports_api.CURRENT_SEASON
        else TTL_TRANSFER_COMPARE_CURRENT
    )

    labels = transfer_loader.LEAGUE_LABELS

    def loader():
        players_a = _build_transfer_group_players(from_a, target, season)
        players_b = _build_transfer_group_players(from_b, target, season)
        return transfer_comparison.build_comparison_result(
            from_a, from_b, target, season,
            labels[from_a], labels[from_b], labels[target],
            players_a, players_b,
        )

    try:
        result = disk_cached_call(
            key=result_key,
            ttl_seconds=result_ttl,
            loader=loader,
            source="api-sports",
        )
        return jsonify(result)

    except ApisportsUnavailable as error:
        # Notfall: auch ein abgelaufenes Endergebnis ist besser als nichts.
        stale = disk_read_entry(result_key)
        if stale and stale.get("payload"):
            payload = stale["payload"]
            warnings = list(payload.get("warnings") or [])
            warnings.append(
                "Die Datenquelle ist momentan nicht erreichbar. "
                "Es werden zuletzt gespeicherte Daten angezeigt."
            )
            payload = {**payload, "warnings": warnings}
            return jsonify(payload)

        if isinstance(error, ApisportsRateLimit):
            return jsonify({
                "error": "Das taegliche Kontingent der Datenquelle ist "
                         "aufgebraucht. Bitte morgen erneut versuchen.",
                "detail": str(error),
            }), 429

        return jsonify({
            "error": "Diese Analyse kann momentan nicht geladen werden. "
                     "Bitte spaeter erneut versuchen.",
            "detail": str(error),
        }), 503

# =============================================================================
#  PDF MERGE TOOL
# =============================================================================

PDF_ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}
PDF_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png"}
PDF_MAX_FILES = 40


def pdf_get_extension(filename):
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()


def pdf_is_allowed(filename):
    return pdf_get_extension(filename) in PDF_ALLOWED_EXTENSIONS


def pdf_is_image(filename):
    return pdf_get_extension(filename) in PDF_IMAGE_EXTENSIONS


def pdf_convert_image(image_path, target_path):
    """
    Wandelt ein Bild in eine einseitige PDF um.
    Unterstuetzt RGB, CMYK, RGBA, Palette und alle anderen Modi.
    Transparente PNGs kriegen weissen Hintergrund.
    """
    from PIL import ImageOps
    with Image.open(image_path) as image:
        # EXIF-Rotation beruecksichtigen (Handy-Fotos)
        image = ImageOps.exif_transpose(image)

        if image.mode == "CMYK":
            image_to_save = image.convert("RGB")
        elif image.mode in ("RGBA", "LA", "P"):
            converted = image.convert("RGBA")
            background = Image.new("RGB", converted.size, (255, 255, 255))
            background.paste(converted, mask=converted.split()[-1])
            image_to_save = background
        elif image.mode != "RGB":
            image_to_save = image.convert("RGB")
        else:
            image_to_save = image.copy()

        image_to_save.save(target_path, "PDF", resolution=150.0)


def pdf_build_output_name(raw_name):
    cleaned = secure_filename(raw_name or "merged")

    if not cleaned:
        cleaned = "merged"

    if cleaned.lower().endswith(".pdf"):
        cleaned = cleaned[:-4]

    return f"{cleaned}.pdf"


@app.route("/tools/pdf", methods=["GET"])
def pdf_merge_page():
    return render_template("pdfmerge.html")


@app.route("/tools/pdf/merge", methods=["POST"])
def pdf_merge_run():
    uploaded_files = request.files.getlist("files")

    if not uploaded_files:
        return jsonify({"error": "Keine Dateien empfangen"}), 400

    if len(uploaded_files) > PDF_MAX_FILES:
        return jsonify({"error": f"Maximal {PDF_MAX_FILES} Dateien pro Merge"}), 400

    work_dir = tempfile.mkdtemp(prefix="footsim_pdfmerge_")

    try:
        writer = PdfWriter()
        merged_count = 0

        for position, uploaded in enumerate(uploaded_files):
            if not uploaded.filename or not pdf_is_allowed(uploaded.filename):
                continue

            extension = pdf_get_extension(uploaded.filename)
            source_path = os.path.join(work_dir, f"{position:03d}_input.{extension}")
            uploaded.save(source_path)

            if pdf_is_image(uploaded.filename):
                try:
                    converted_path = os.path.join(work_dir, f"{position:03d}_converted.pdf")
                    pdf_convert_image(source_path, converted_path)
                    writer.append(converted_path)
                except Exception:
                    return jsonify({
                        "error": f"Bild konnte nicht gelesen werden: {uploaded.filename}"
                    }), 400
            else:
                try:
                    reader = PdfReader(source_path)

                    if reader.is_encrypted:
                        if reader.decrypt("") == 0:
                            return jsonify({
                                "error": f"Passwortgeschuetzt: {uploaded.filename}"
                            }), 400

                    writer.append(reader)
                except Exception:
                    return jsonify({
                        "error": f"Beschaedigte oder ungueltige PDF: {uploaded.filename}"
                    }), 400

            merged_count += 1

        if merged_count == 0:
            return jsonify({"error": "Keine gueltigen Dateien dabei"}), 400

        total_pages = len(writer.pages)
        output_path = os.path.join(work_dir, "__output.pdf")

        writer.write(output_path)
        writer.close()

        with open(output_path, "rb") as output_file:
            pdf_bytes = output_file.read()

        response = send_file(
            io.BytesIO(pdf_bytes),
            as_attachment=True,
            download_name=pdf_build_output_name(request.form.get("output_name")),
            mimetype="application/pdf"
        )
        response.headers["X-Total-Pages"] = str(total_pages)
        return response

    except Exception as error:
        return jsonify({"error": f"Verarbeitung fehlgeschlagen: {str(error)}"}), 500

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@app.errorhandler(413)
def pdf_file_too_large(error):
    return jsonify({"error": "Dateien zu gross. Maximal 50 MB pro Merge."}), 413


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
