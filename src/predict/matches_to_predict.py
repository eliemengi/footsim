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

UCL_SECOND_LEG_CONTEXT = {
    "gala_liverpool": {
        "first_leg_home_team": "Galatasaray",
        "first_leg_away_team": "Liverpool",
        "first_leg_home_goals": 1,
        "first_leg_away_goals": 0,
        "second_leg_home_team": "Liverpool",
        "second_leg_away_team": "Galatasaray"
    },
    "newcastle_barcelona": {
        "first_leg_home_team": "Newcastle",
        "first_leg_away_team": "Barcelona",
        "first_leg_home_goals": 1,
        "first_leg_away_goals": 1,
        "second_leg_home_team": "Barcelona",
        "second_leg_away_team": "Newcastle"
    },
    "atletico_tottenham": {
        "first_leg_home_team": "Atletico",
        "first_leg_away_team": "Tottenham",
        "first_leg_home_goals": 5,
        "first_leg_away_goals": 2,
        "second_leg_home_team": "Tottenham",
        "second_leg_away_team": "Atletico"
    },
    "atalanta_bayern": {
        "first_leg_home_team": "Atalanta",
        "first_leg_away_team": "Bayern",
        "first_leg_home_goals": 1,
        "first_leg_away_goals": 6,
        "second_leg_home_team": "Bayern",
        "second_leg_away_team": "Atalanta"
    },
    "leverkusen_arsenal": {
        "first_leg_home_team": "Leverkusen",
        "first_leg_away_team": "Arsenal",
        "first_leg_home_goals": 1,
        "first_leg_away_goals": 1,
        "second_leg_home_team": "Arsenal",
        "second_leg_away_team": "Leverkusen"
    },
    "real_madrid_city": {
        "first_leg_home_team": "Real Madrid",
        "first_leg_away_team": "Man City",
        "first_leg_home_goals": 3,
        "first_leg_away_goals": 0,
        "second_leg_home_team": "Man City",
        "second_leg_away_team": "Real Madrid"
    },
    "bodo_sporting": {
        "first_leg_home_team": "Bodo Glimt",
        "first_leg_away_team": "Sporting",
        "first_leg_home_goals": 3,
        "first_leg_away_goals": 0,
        "second_leg_home_team": "Sporting",
        "second_leg_away_team": "Bodo Glimt"
    },
    "psg_chelsea": {
        "first_leg_home_team": "Paris",
        "first_leg_away_team": "Chelsea",
        "first_leg_home_goals": 5,
        "first_leg_away_goals": 2,
        "second_leg_home_team": "Chelsea",
        "second_leg_away_team": "Paris"
    },
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

MATCHES_TO_PREDICT = MATCHES_TO_PREDICT_CL