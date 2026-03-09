import json
import os


RAW_MATCHES_PATH = "data/raw/team_matches.json"
RESULTS_PATH = "data/results/simulation_history.json"


def load_raw_team_matches():
    with open(RAW_MATCHES_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


def save_simulation_result(result):
    os.makedirs("data/results", exist_ok=True)

    history = []

    if os.path.exists(RESULTS_PATH):
        with open(RESULTS_PATH, "r", encoding="utf-8") as file:
            try:
                history = json.load(file)
            except json.JSONDecodeError:
                history = []

    history.append(result)

    with open(RESULTS_PATH, "w", encoding="utf-8") as file:
        json.dump(history, file, ensure_ascii=False, indent=4)