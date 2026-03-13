from flask import Flask, jsonify, render_template, request
import os
import requests

from src.predict.matches_to_predict import MATCHES_TO_PREDICT_CL, MATCHES_TO_PREDICT_EL
from src.predict.simulate_scores import simulate_selected_match
from src.api.football_api import get_bundesliga_matchday_match_options

app = Flask(__name__)

FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_API_KEY")
FOOTBALL_DATA_BASE_URL = "https://api.football-data.org/v4"

COMPETITION_CONFIG = {
    "cl": {
        "name": "Champions League",
        "api_code": "CL",
        "coming_soon_text": ""
    },
    "el": {
        "name": "Europa League",
        "api_code": "EL",
        "coming_soon_text": "Europa League wird bald freigeschaltet."
    },
    "bl1": {
        "name": "Bundesliga",
        "api_code": "BL1",
        "coming_soon_text": ""
    },
    "pl": {
        "name": "Premier League",
        "api_code": "PL",
        "coming_soon_text": "Premier League wird bald freigeschaltet."
    },
    "pd": {
        "name": "LaLiga",
        "api_code": "PD",
        "coming_soon_text": "LaLiga wird bald freigeschaltet."
    },
    "sa": {
        "name": "Serie A",
        "api_code": "SA",
        "coming_soon_text": "Serie A wird bald freigeschaltet."
    }
}

COMPETITION_MATCHES = {
    "cl": MATCHES_TO_PREDICT_CL,
    "el": MATCHES_TO_PREDICT_EL,
    "bl1": {},
    "pl": {},
    "pd": {},
    "sa": {}
}

BUNDESLIGA_ENABLED_MATCHDAY = 26
BUNDESLIGA_SEASON = 2025


def get_headers():
    if not FOOTBALL_DATA_API_KEY:
        return {}
    return {
        "X-Auth-Token": FOOTBALL_DATA_API_KEY
    }


def fetch_competition_emblem(api_code):
    if not FOOTBALL_DATA_API_KEY:
        return None

    try:
        response = requests.get(
            f"{FOOTBALL_DATA_BASE_URL}/competitions/{api_code}",
            headers=get_headers(),
            timeout=8
        )
        if response.ok:
            data = response.json()
            return data.get("emblem")
    except Exception:
        return None

    return None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/competitions", methods=["GET"])
def get_competitions():
    competitions = []

    for code, config in COMPETITION_CONFIG.items():
        matches = COMPETITION_MATCHES.get(code, {})
        available = len(matches) > 0

        if code == "bl1":
            available = True

        competitions.append({
            "code": code,
            "name": config["name"],
            "api_code": config["api_code"],
            "emblem": fetch_competition_emblem(config["api_code"]),
            "available": available,
            "coming_soon_text": config["coming_soon_text"]
        })

    return jsonify(competitions)


@app.route("/api/matchdays", methods=["GET"])
def get_matchdays():
    competition_code = request.args.get("competition", "").lower()

    if competition_code != "bl1":
        return jsonify([])

    matchdays = []

    for day in range(26, 35):
        matchdays.append({
            "matchday": day,
            "available": day == BUNDESLIGA_ENABLED_MATCHDAY,
            "label": f"Spieltag {day}",
            "message": "" if day == BUNDESLIGA_ENABLED_MATCHDAY else "Noch nicht verfügbar"
        })

    return jsonify(matchdays)


@app.route("/api/matches", methods=["GET"])
def get_matches():
    competition_code = request.args.get("competition", "cl").lower()

    if competition_code == "bl1":
        matchday = int(request.args.get("matchday", BUNDESLIGA_ENABLED_MATCHDAY))

        if matchday != BUNDESLIGA_ENABLED_MATCHDAY:
            return jsonify([])

        matches = get_bundesliga_matchday_match_options(
            matchday=matchday,
            season=BUNDESLIGA_SEASON
        )
        return jsonify(matches)

    competition_matches = COMPETITION_MATCHES.get(competition_code, {})
    matches = []

    for match_id, teams in competition_matches.items():
        home_team, away_team = teams
        matches.append({
            "id": match_id,
            "home_team": home_team,
            "away_team": away_team,
            "label": f"{home_team} vs {away_team}"
        })

    return jsonify(matches)


@app.route("/api/simulate", methods=["POST"])
def simulate():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Request Body fehlt"}), 400

    competition_code = data.get("competition", "cl")
    match_id = data.get("match_id")
    simulations = data.get("simulations", 5000)
    use_seed = data.get("use_seed", False)

    if not match_id:
        return jsonify({"error": "match_id fehlt"}), 400

    if competition_code != "cl":
        return jsonify({
            "error": "Aktuell ist nur Champions League Simulation freigeschaltet. Bundesliga lädt schon die Spiele, Simulation kommt als nächster Schritt."
        }), 400

    try:
        result = simulate_selected_match(
            match_id=match_id,
            simulations=simulations,
            use_seed=use_seed
        )
        return jsonify(result)

    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        return jsonify({"error": f"Interner Fehler: {str(error)}"}), 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)