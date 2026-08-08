"""
Manuell gepflegte Paarungen fuer Pokalwettbewerbe ohne eigenen
datengetriebenen Pfad.

Die Champions-League-Paarungen sind seit Phase 4.0 / Block B1 vollstaendig
datengetrieben (siehe src/features/strength_provider.get_cl_team_strengths
und src/predict/cl_match_sim.py) und haengen nicht mehr an dieser Datei.
Teams werden dort ueber football-data-Team-IDs identifiziert statt ueber
hier hinterlegte Klarnamen.

Nur die Europa-League-Paarungen bleiben hier bestehen. Die Europa League
ist aktuell nicht freigeschaltet (siehe CUP_CONFIG["el"]["available"] in
app.py) und wird deshalb noch nicht auf den datengetriebenen Pfad
umgestellt.
"""

MATCHES_TO_PREDICT_EL = {
    "roma_bologna_el": ("Roma", "Bologna"),
    "aston_villa_lille_el": ("Aston Villa", "Lille"),
    "real_betis_panathinaikos_el": ("Real Betis", "Panathinaikos"),
    "porto_stuttgart_el": ("Porto", "Stuttgart"),
    "lyon_celta_el": ("Lyon", "Celta"),
    "braga_ferencvaros_el": ("Braga", "Ferencvaros"),
    "freiburg_genk_el": ("Freiburg", "Genk"),
    "midtjylland_forest_el": ("Midtjylland", "Nottingham Forest"),
}

UEL_SECOND_LEG_CONTEXT = {
    "roma_bologna_el": {
        "first_leg_home_team": "Bologna",
        "first_leg_away_team": "Roma",
        "first_leg_home_goals": 1,
        "first_leg_away_goals": 1,
        "second_leg_home_team": "Roma",
        "second_leg_away_team": "Bologna"
    },
    "aston_villa_lille_el": {
        "first_leg_home_team": "Lille",
        "first_leg_away_team": "Aston Villa",
        "first_leg_home_goals": 0,
        "first_leg_away_goals": 1,
        "second_leg_home_team": "Aston Villa",
        "second_leg_away_team": "Lille"
    },
    "real_betis_panathinaikos_el": {
        "first_leg_home_team": "Panathinaikos",
        "first_leg_away_team": "Real Betis",
        "first_leg_home_goals": 1,
        "first_leg_away_goals": 0,
        "second_leg_home_team": "Real Betis",
        "second_leg_away_team": "Panathinaikos"
    },
    "porto_stuttgart_el": {
        "first_leg_home_team": "Stuttgart",
        "first_leg_away_team": "Porto",
        "first_leg_home_goals": 1,
        "first_leg_away_goals": 2,
        "second_leg_home_team": "Porto",
        "second_leg_away_team": "Stuttgart"
    },
    "lyon_celta_el": {
        "first_leg_home_team": "Celta",
        "first_leg_away_team": "Lyon",
        "first_leg_home_goals": 1,
        "first_leg_away_goals": 1,
        "second_leg_home_team": "Lyon",
        "second_leg_away_team": "Celta"
    },
    "braga_ferencvaros_el": {
        "first_leg_home_team": "Ferencvaros",
        "first_leg_away_team": "Braga",
        "first_leg_home_goals": 2,
        "first_leg_away_goals": 0,
        "second_leg_home_team": "Braga",
        "second_leg_away_team": "Ferencvaros"
    },
    "freiburg_genk_el": {
        "first_leg_home_team": "Genk",
        "first_leg_away_team": "Freiburg",
        "first_leg_home_goals": 1,
        "first_leg_away_goals": 0,
        "second_leg_home_team": "Freiburg",
        "second_leg_away_team": "Genk"
    },
    "midtjylland_forest_el": {
        "first_leg_home_team": "Nottingham Forest",
        "first_leg_away_team": "Midtjylland",
        "first_leg_home_goals": 0,
        "first_leg_away_goals": 1,
        "second_leg_home_team": "Midtjylland",
        "second_leg_away_team": "Nottingham Forest"
    },
}

# Generischer Pokal-Fallback fuer simulate_scores.simulate_selected_match.
# Zeigt auf die Europa League, solange kein spezifischerer Wettbewerbscode
# greift. Die Champions League nutzt diesen Pfad nicht mehr (siehe oben).
MATCHES_TO_PREDICT = MATCHES_TO_PREDICT_EL
