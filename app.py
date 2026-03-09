from flask import Flask, jsonify, render_template, request

from src.predict.matches_to_predict import MATCHES_TO_PREDICT
from src.predict.simulate_scores import simulate_selected_match


app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/matches", methods=["GET"])
def get_matches():
    matches = []

    for match_id, teams in MATCHES_TO_PREDICT.items():
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

    if not data or "match_id" not in data:
        return jsonify({"error": "match_id fehlt"}), 400

    match_id = data["match_id"]
    simulations = data.get("simulations", 5000)
    use_seed = data.get("use_seed", False)

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