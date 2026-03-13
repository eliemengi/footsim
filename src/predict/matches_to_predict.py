MATCHES_TO_PREDICT_CL = {
    "gala_liverpool": ("Galatasaray", "Liverpool"),
    "newcastle_barcelona": ("Newcastle", "Barcelona"),
    "atletico_tottenham": ("Atletico", "Tottenham"),
    "atalanta_bayern": ("Atalanta", "Bayern"),
    "leverkusen_arsenal": ("Leverkusen", "Arsenal"),
    "real_madrid_city": ("Real Madrid", "Man City"),
    "bodo_sporting": ("Bodo Glimt", "Sporting"),
    "psg_chelsea": ("Paris", "Chelsea"),
}

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
        "first_leg_away_goals": 1
    },
    "aston_villa_lille_el": {
        "first_leg_home_team": "Lille",
        "first_leg_away_team": "Aston Villa",
        "first_leg_home_goals": 0,
        "first_leg_away_goals": 1
    },
    "real_betis_panathinaikos_el": {
        "first_leg_home_team": "Panathinaikos",
        "first_leg_away_team": "Real Betis",
        "first_leg_home_goals": 1,
        "first_leg_away_goals": 0
    },
    "porto_stuttgart_el": {
        "first_leg_home_team": "Stuttgart",
        "first_leg_away_team": "Porto",
        "first_leg_home_goals": 1,
        "first_leg_away_goals": 2
    },
    "lyon_celta_el": {
        "first_leg_home_team": "Celta",
        "first_leg_away_team": "Lyon",
        "first_leg_home_goals": 1,
        "first_leg_away_goals": 1
    },
    "braga_ferencvaros_el": {
        "first_leg_home_team": "Ferencvaros",
        "first_leg_away_team": "Braga",
        "first_leg_home_goals": 2,
        "first_leg_away_goals": 0
    },
    "freiburg_genk_el": {
        "first_leg_home_team": "Genk",
        "first_leg_away_team": "Freiburg",
        "first_leg_home_goals": 1,
        "first_leg_away_goals": 0
    },
    "midtjylland_forest_el": {
        "first_leg_home_team": "Nottingham Forest",
        "first_leg_away_team": "Midtjylland",
        "first_leg_home_goals": 0,
        "first_leg_away_goals": 1
    },
}

MATCHES_TO_PREDICT = MATCHES_TO_PREDICT_CL