"""
national_competitions.py - Welche A-Nationalmannschaftswettbewerbe gehoeren zu
welcher FootSim-Saison, und wo liegen sie in der API?

Grundlage
---------
Dieses Modul kodiert AUSSCHLIESSLICH das, was die Discovery (discover_national.py)
gegen die echte API verifiziert hat: League-IDs, verfuegbare API-Seasons und das
coverage.players/statistics_players-Flag. Es werden KEINE IDs geraten.

Zwei fachliche Regeln, die hier zusammenkommen:

1. Modell A - Fussballsaison, nicht Kalenderjahr, nicht API-Season.
   Eine FootSim-Saison ist eine komplette Fussballsaison (z. B. 2025/26 =
   FootSim-Saison 2025). Ein internationales Turnier gehoert zu der
   FootSim-Saison, in deren Fussballsaison-ZEITRAUM es faellt - unabhaengig
   davon, unter welcher API-Season API-Football es speichert.

   Beispiele (allgemeine Regel, keine Einzelfaelle):
     - EM 2021 (verschobene EM 2020, gespielt Sommer 2021) -> FootSim 2020
     - WM 2022 (Winter 2022)                               -> FootSim 2021
     - EM 2024 (Sommer 2024)                               -> FootSim 2023
     - Copa America 2024 (Sommer 2024)                     -> FootSim 2023
     - WM 2026 (Sommer 2026)                               -> FootSim 2025

   Das Muster dahinter: Ein Sommerturnier NACH der Saison X/X+1 gehoert noch
   zu FootSim-Saison X. Ein Winterturnier innerhalb der Saison X/X+1 gehoert
   ebenfalls zu FootSim-Saison X. Laufende Wettbewerbe (Nations League,
   Qualifikationen, Friendlies) laufen ueber die Saison und gehoeren zu der
   FootSim-Saison, in der ihre API-Season startet.

2. Nur A-Nationalmannschaft.
   Vereinswettbewerbe (auch "CONCACAF Champions League", "FIFA Club World
   Cup") gehoeren NICHT hierher. Jugend- und Frauenwettbewerbe (U17..U23,
   Women) sind KEINE A-Nationalmannschaft und werden ausgeschlossen.

Struktur
--------
NATIONAL_COMPETITIONS: je Wettbewerb die verifizierten (api_season -> coverage)
Paare. usable=True heisst: statistics_players verfuegbar (echte Per-90-Werte
moeglich). Nur usable-Seasons werden importiert.

FOOTSIM_SEASON_OF_TOURNAMENT: ordnet je (league_id, api_season) die
FootSim-Saison zu. Das ist die konkrete Umsetzung von Modell A. Neue Turniere
werden hier ergaenzt - keine Jahres-Hardcodierung an anderer Stelle.
"""


# ---------------------------------------------------------------------------
# Verifizierte A-Nationalmannschaftswettbewerbe (Quelle: Discovery-Lauf)
# ---------------------------------------------------------------------------
# Nur Wettbewerbe, die in mindestens einer Season statistics_players=True
# hatten UND echte A-Nationalmannschaft sind. Klub- und Jugend-/Frauen-
# wettbewerbe sind bewusst NICHT enthalten.
#
# Feld "usable_seasons": die API-Seasons mit echten Spielerstatistiken (J).
# ---------------------------------------------------------------------------

NATIONAL_COMPETITIONS = {
    1:   {"name": "World Cup",                              "usable_seasons": [2022, 2026]},
    4:   {"name": "Euro Championship",                      "usable_seasons": [2020, 2024]},
    5:   {"name": "UEFA Nations League",                    "usable_seasons": [2024]},
    6:   {"name": "Africa Cup of Nations",                  "usable_seasons": [2023, 2025]},
    7:   {"name": "Asian Cup",                              "usable_seasons": [2023]},
    9:   {"name": "Copa America",                           "usable_seasons": [2024]},
    22:  {"name": "CONCACAF Gold Cup",                      "usable_seasons": [2023, 2025]},
    29:  {"name": "World Cup - Qualification Africa",       "usable_seasons": [2023]},
    30:  {"name": "World Cup - Qualification Asia",         "usable_seasons": [2026]},
    31:  {"name": "World Cup - Qualification CONCACAF",     "usable_seasons": [2026]},
    32:  {"name": "World Cup - Qualification Europe",       "usable_seasons": [2024]},
    34:  {"name": "World Cup - Qualification South America","usable_seasons": [2026]},
    37:  {"name": "World Cup - Qualification Intercontinental Play-offs",
                                                            "usable_seasons": [2026]},
    536: {"name": "CONCACAF Nations League",                "usable_seasons": [2023, 2024]},
    960: {"name": "Euro Championship - Qualification",      "usable_seasons": [2023]},
    # Friendlies laufen durchgehend und haben in allen gepruueften Seasons
    # Spielerstatistiken.
    10:  {"name": "Friendlies",                             "usable_seasons": [2023, 2024, 2025, 2026]},
}


# Big Games intentionally use a stricter policy than the general senior-
# national-team import above.  Every ID here has an exact, already supported
# provider mapping in ``NATIONAL_COMPETITIONS``; Friendlies (10) remain
# available for ordinary national statistics but can never qualify as a Big
# Game.  New competition IDs must be reviewed and added explicitly rather
# than inheriting eligibility from the broader import registry.
NATIONAL_BIG_GAMES_COMPETITION_IDS = frozenset({
    1,    # FIFA World Cup
    4,    # UEFA EURO
    5,    # UEFA Nations League
    6,    # Africa Cup of Nations
    7,    # AFC Asian Cup
    9,    # Copa America
    22,   # CONCACAF Gold Cup
    29,   # FIFA World Cup qualification - Africa
    30,   # FIFA World Cup qualification - Asia
    31,   # FIFA World Cup qualification - CONCACAF
    32,   # FIFA World Cup qualification - Europe
    34,   # FIFA World Cup qualification - South America
    37,   # FIFA World Cup intercontinental play-offs
    536,  # CONCACAF Nations League
    960,  # UEFA EURO qualification
})


def is_big_games_competitive_national_competition(league_id):
    """Whether an exact supported senior competition may enter Big Games."""
    return league_id in NATIONAL_BIG_GAMES_COMPETITION_IDS


# ---------------------------------------------------------------------------
# Modell A: (league_id, api_season) -> FootSim-Saison
# ---------------------------------------------------------------------------
# Diese Tabelle ist die EINZIGE Stelle, an der die kalendarische Zuordnung
# gepflegt wird. Sie ordnet jedes verifizierte Turnier der Fussballsaison zu,
# in deren Zeitraum es faellt.
#
# Regelableitung (dokumentiert, damit kuenftige Eintraege konsistent sind):
#   - Sommerturnier nach Saison X/(X+1):      api_season -> FootSim X
#       EM 2024 (api 2024)         -> 2023      (Sommer 2024, nach 23/24)
#       Copa America 2024 (api 24) -> 2023
#       WM 2026 (api 2026)         -> 2025      (Sommer 2026, nach 25/26)
#   - Kontinentalturnier im Winter/Fruehjahr der Saison X/(X+1):
#       AFCON (api 2023, Jan 2024) -> 2023
#       Asian Cup (api 2023)       -> 2023
#       Gold Cup (api Sommer)      -> Saison davor
#   - Laufende Wettbewerbe (Nations League, Qualifikationen, Friendlies):
#       gehoeren zu der FootSim-Saison, in der ihre api_season beginnt.
#       api_season 2024 -> FootSim 2024 (Saison 24/25) usw.
#
# Wenn ein neues Turnier hinzukommt, wird hier EIN Eintrag ergaenzt.
# ---------------------------------------------------------------------------

FOOTSIM_SEASON_OF_TOURNAMENT = {
    # --- grosse Endrunden: Sommerturniere zaehlen zur davorliegenden Saison ---
    (4, 2024):  2023,   # EM 2024        -> FootSim 2023 (Saison 2023/24)
    (9, 2024):  2023,   # Copa America 2024 -> FootSim 2023
    (1, 2026):  2025,   # WM 2026        -> FootSim 2025 (Saison 2025/26)

    # --- historische Endrunden (Discovery-Lauf 2020-2022 verifiziert) --------
    # EM 2021 ist ein AUSNAHMEFALL und folgt KEINER Formel:
    # API-Football fuehrt die wegen COVID um ein Jahr verschobene EURO 2020
    # unter api_season=2020 (verifiziert: start=2019-03-21, end=2021-07-11 -
    # das Enddatum ist der Finaltermin in Wembley am 11.07.2021). Gespielt
    # wurde die Endrunde im Sommer 2021, also nach der Saison 2020/21.
    # Deshalb FootSim 2020. Eine generische "api_season - 1"-Regel wuerde
    # hier faelschlich 2019 ergeben - genau darum steht das Mapping explizit
    # in dieser Tabelle und wird nirgends berechnet.
    (4, 2020):  2020,   # EM 2021 (EURO 2020) -> FootSim 2020 (Saison 2020/21)

    # WM 2022 lag im Winter (20.11.-18.12.2022), also INNERHALB der Saison
    # 2022/23. Zaehlt zur FootSim-Saison 2022/23.
    (1, 2022):  2022,   # WM 2022        -> FootSim 2022 (Saison 2022/23)

    # --- Kontinentalturnier im Saisonverlauf ---
    (6, 2023):  2023,   # AFCON 2023/24 (Jan 2024)  -> FootSim 2023
    (6, 2025):  2025,   # AFCON 2025    -> FootSim 2025
    (7, 2023):  2023,   # Asian Cup 2023/24 (Jan 24)-> FootSim 2023
    (22, 2023): 2023,   # Gold Cup 2023 -> FootSim 2023 (Saison davor)
    (22, 2025): 2024,   # Gold Cup 2025 (Sommer 25) -> FootSim 2024 (Saison 24/25)

    # --- laufende Wettbewerbe: FootSim-Saison = Start-api_season ---
    (5, 2024):   2024,  # UEFA Nations League 24/25 -> FootSim 2024
    (536, 2023): 2023,  # CONCACAF Nations League
    (536, 2024): 2024,

    # WM-Qualifikationen: zur FootSim-Saison ihrer api_season
    (29, 2023):  2023,  # WM-Quali Afrika
    (30, 2026):  2025,  # WM-Quali Asien (Zyklus zur WM 2026) -> FootSim 2025
    (31, 2026):  2025,  # WM-Quali CONCACAF
    (32, 2024):  2024,  # WM-Quali Europa (Zyklus 2024ff) -> FootSim 2024
    (34, 2026):  2025,  # WM-Quali Suedamerika
    (37, 2026):  2025,  # WM-Quali interkont. Play-offs
    (960, 2023): 2023,  # EM-Quali (fuer EM 2024) -> FootSim 2023

    # Friendlies: FootSim-Saison = api_season (laufend, ganzjaehrig)
    (10, 2023):  2023,
    (10, 2024):  2024,
    (10, 2025):  2025,
    (10, 2026):  2025,  # Friendlies der api-2026-Fenster gehoeren zur WM-Saison 25/26
}


def national_targets_for_footsim_season(footsim_season):
    """
    Liefert die zu importierenden (league_id, api_season, name)-Tripel fuer
    eine FootSim-Saison.

    Verwendet AUSSCHLIESSLICH verifizierte, nutzbare Turnier/Season-Paare und
    ordnet sie ueber FOOTSIM_SEASON_OF_TOURNAMENT (Modell A) der FootSim-Saison
    zu. Ein Paar ohne Eintrag in der Mapping-Tabelle wird bewusst ignoriert -
    lieber nichts importieren als falsch zuordnen.

    Rueckgabe: Liste von dicts {league_id, api_season, name}, stabil sortiert.
    """
    targets = []
    for league_id, meta in NATIONAL_COMPETITIONS.items():
        for api_season in meta["usable_seasons"]:
            mapped = FOOTSIM_SEASON_OF_TOURNAMENT.get((league_id, api_season))
            if mapped == footsim_season:
                targets.append({
                    "league_id": league_id,
                    "api_season": api_season,
                    "name": meta["name"],
                })
    targets.sort(key=lambda t: (t["league_id"], t["api_season"]))
    return targets


# ---------------------------------------------------------------------------
# Turnierscharfe Player-Analytics-Scopes
# ---------------------------------------------------------------------------
#
# Anders als der Sammel-Scope "national" (alle A-Laenderspiele zusammen)
# beziehen sich diese Scopes auf GENAU EIN Turnier. Die Zuordnung
# Scope -> league_id steht hier, weil dieses Modul ohnehin die einzige
# Stelle ist, an der Turnier-IDs und Saisonzuordnung gepflegt werden.
#
# WM und EM finden - anders als die Champions League - nicht in jedem
# Saisonzyklus statt. Welche FootSim-Saisons ein Turnier haben, ergibt sich
# ausschliesslich aus FOOTSIM_SEASON_OF_TOURNAMENT. Es wird nirgends aus
# Jahreszahlen gerechnet.

TOURNAMENT_SCOPE_LEAGUE_IDS = {
    "euro":       4,
    "world_cup":  1,
}


def footsim_seasons_for_tournament_scope(scope):
    """
    FootSim-Saisons, in denen das Turnier dieses Scopes stattgefunden hat.

    Rueckgabe: frozenset von FootSim-Saisonjahren (leer bei unbekanntem Scope).
    """
    league_id = TOURNAMENT_SCOPE_LEAGUE_IDS.get(scope)
    if league_id is None:
        return frozenset()

    return frozenset(
        footsim_season
        for (lid, _api_season), footsim_season in FOOTSIM_SEASON_OF_TOURNAMENT.items()
        if lid == league_id
    )


def tournament_scope_availability(footsim_season):
    """
    Welche Turnier-Scopes gibt es in dieser FootSim-Saison ueberhaupt?

    Rueckgabe: {scope: bool}. Das Frontend blendet damit Scopes aus, deren
    Turnier in der gewaehlten Saison schlicht nicht stattfand - ein
    fachlicher Zustand, kein Fehler.

    Ausdruecklich NICHT dasselbe wie "es liegen Daten vor": ob ein Turnier
    stattfand, ist unabhaengig davon, ob FootSim es schon importiert hat.
    """
    return {
        scope: footsim_season in footsim_seasons_for_tournament_scope(scope)
        for scope in TOURNAMENT_SCOPE_LEAGUE_IDS
    }


def all_national_league_ids():
    """Menge aller bekannten A-Nationalmannschafts-League-IDs."""
    return set(NATIONAL_COMPETITIONS.keys())


def is_national_competition(league_id):
    """True, wenn die Liga-ID ein verifizierter A-Nationalmannschafts-Wettbewerb ist."""
    return league_id in NATIONAL_COMPETITIONS
