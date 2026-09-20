"""
Big Game Rating V2 - die Bewertung selbst (Block V2-BG).

WARUM EIN EIGENES MODUL
-----------------------
V1 rangierte ausschliesslich nach einem minutengewichteten Mittel aus
    Anbieterbewertung x Kontextgewicht.
Tore und Vorlagen standen im Datensatz, bestimmten die Rangfolge aber
NICHT. Die Pruefung an echten Daten (1.810 wertbare Spieler der Saison
2025/26) zeigte drei belegte Folgen:

    * 8 der Top 30 hatten 3 bis 4 Big Games - knapp ueber der alten
      Mindestmenge von 3 Spielen / 180 Minuten.
    * 10 der Top 30 waren Torhueter, obwohl Torhueter nur 7,7 % des
      wertbaren Feldes stellen. Ihre Einzelbewertungen liegen im Mittel
      hoeher (6,99 gegen 6,71-6,80) und streuen deutlich breiter
      (Standardabweichung 0,90 gegen 0,57-0,62). Eine reine
      Bewertungsformel belohnt genau diesen breiten rechten Rand.
    * Ein erfundener Spieler mit 3 Spielen zu je 9,5 erreichte 10,93 -
      mehr als jeder echte Spieler mit 20 konstant starken Spielen.

Dieses Modul beantwortet deshalb getrennt und nachrechenbar:

    1. Wer darf ueberhaupt platziert werden?        -> is_rankable()
    2. Was hat ein Spieler produziert?              -> player_inputs()
    3. Wie gut ist das fuer SEINE Position?         -> score_population()

Alle Stellschrauben stehen als benannte Konstanten oben. Es gibt keine
verstreuten Zahlen im Rechenweg - eine spaetere Neukalibrierung fasst
genau eine Tabelle an.

KEIN ML, KEINE ERFUNDENEN DATEN
-------------------------------
Es werden ausschliesslich Felder benutzt, die in den Einzelspielerwerten
des Anbieters wirklich stehen (siehe big_games_loader._extract_player_line).
xG, xA, PSxG, progressive Paesse, Ereigniszeitpunkte und ein verlaesslicher
Elfmeter-Anteil liegen NICHT vor und werden auch nicht geschaetzt.
"""

import statistics


# ---------------------------------------------------------------------------
# 1. Zulassung zur Rangliste
# ---------------------------------------------------------------------------
#
# Bewusst schaerfer als die Anzeigeschwelle des Einzelvergleichs
# (big_games.MIN_BIG_GAMES / MIN_BIG_GAME_MINUTES, weiterhin 3/180): ein
# Profil darf Rohwerte zeigen, eine offizielle Platzierung verlangt eine
# belastbare Grundlage. 450 Minuten sind fuenf volle Spiele.

RANKING_MIN_BIG_GAMES = 5
RANKING_MIN_MINUTES = 450


def is_rankable(match_count, minutes):
    """True, wenn ein Spieler offiziell platziert werden darf."""
    return ((match_count or 0) >= RANKING_MIN_BIG_GAMES
            and (minutes or 0) >= RANKING_MIN_MINUTES)


# ---------------------------------------------------------------------------
# 2. Mischung aus Qualitaet und Umfang
# ---------------------------------------------------------------------------
#
# Reine Rate belohnt es, wenige starke Spiele nicht durch weitere normale
# zu "verduennen"; reines Volumen belohnt blosses Dabeisein. Der Anteil
# folgt der empirischen Pruefung: ab etwa 30-35 % Volumen verschwinden die
# Kleinststichproben aus der Spitze, ohne dass reine Vielspieler sie
# uebernehmen.

RATE_SHARE = 0.65
VOLUME_SHARE = 0.35

#: Empirische Schrumpfung Richtung Positionsmittel, in gewichteten 90ern.
#: n/(n+k): bei 8 gewichteten 90ern zaehlt die eigene Rate zur Haelfte.
SHRINKAGE_K = 8.0

#: Oeffentliche Skala. 50 ist Positionsdurchschnitt, +-1 Streuungseinheit
#: sind 12 Punkte. Deterministisch und ohne Modellkennung.
SCORE_CENTER = 50.0
SCORE_SPREAD = 12.0
SCORE_MIN = 0.0
SCORE_MAX = 100.0


# ---------------------------------------------------------------------------
# 3. Positionsprofile
# ---------------------------------------------------------------------------
#
# Jede Position wird an ihrer eigenen Aufgabe gemessen. Die Gewichte je
# Position summieren sich auf 1.0.
#
# ZWEI PRODUKTREGELN, DIE HIER HARTE GRENZEN SIND:
#
#   * Tor und Vorlage sind GLEICH viel wert (1:1). Das erledigt bereits
#     big_games._goal_assist_contribution(); hier wird nie nachgewichtet.
#   * Die Anbieterbewertung ist SEKUNDAER. Sie enthaelt bereits viele der
#     Einzelereignisse und darf das objektive Ergebnis nicht ueberstimmen;
#     deshalb liegt ihr Gewicht ueberall bei hoechstens 0.25.
#
# "ga" ist fuer Angriff und Mittelfeld die groesste Einzelkomponente. Ein
# Beispiel, das als Test festgehalten ist: 1 Tor + 1 Vorlage bei
# Bewertung 7,4 schlaegt 0 Torbeteiligungen bei Bewertung 8,0.

METRIC_GA = "ga_per90"
METRIC_SHOTS_ON = "shots_on_per90"
METRIC_KEY_PASSES = "key_passes_per90"
METRIC_PASSES = "passes_per90"
METRIC_DRIBBLES = "dribbles_success_per90"
METRIC_DUELS_WON = "duels_won_per90"
METRIC_DEF_ACTIONS = "def_actions_per90"
METRIC_SAVES = "saves_per90"
METRIC_CONCEDED = "conceded_per90"
METRIC_RATING = "rating"

#: True bedeutet: kleinere Werte sind besser (nur Gegentore).
LOWER_IS_BETTER = frozenset({METRIC_CONCEDED})

POSITION_PROFILES = {
    "Attacker": {
        METRIC_GA:          0.55,
        METRIC_RATING:      0.20,
        METRIC_SHOTS_ON:    0.08,
        METRIC_KEY_PASSES:  0.08,
        METRIC_DRIBBLES:    0.05,
        METRIC_DUELS_WON:   0.04,
    },
    "Midfielder": {
        METRIC_GA:          0.42,
        METRIC_RATING:      0.20,
        METRIC_KEY_PASSES:  0.14,
        METRIC_DEF_ACTIONS: 0.09,
        METRIC_DUELS_WON:   0.09,
        METRIC_PASSES:      0.06,
    },
    "Defender": {
        METRIC_DEF_ACTIONS: 0.40,
        METRIC_RATING:      0.22,
        METRIC_DUELS_WON:   0.15,
        METRIC_GA:          0.13,
        METRIC_PASSES:      0.10,
    },
    "Goalkeeper": {
        METRIC_SAVES:       0.40,
        METRIC_CONCEDED:    0.30,
        METRIC_RATING:      0.25,
        METRIC_GA:          0.05,
    },
}

#: Ohne erkannte Position: die positionsuebergreifend fairste Mischung.
DEFAULT_PROFILE = POSITION_PROFILES["Midfielder"]

#: Hoechstanteil der Anbieterbewertung - als Vertrag pruefbar.
MAX_RATING_SHARE = 0.25


def profile_for(position):
    return POSITION_PROFILES.get(position, DEFAULT_PROFILE)


# ---------------------------------------------------------------------------
# 4. Eingangswerte eines Spielers
# ---------------------------------------------------------------------------

def _num(value):
    """Zahl oder None. None bleibt None und wird NIE zu 0 umgedeutet."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _sum_present(matches, field, weighted=True):
    """
    Kontextgewichtete Summe ueber die vorhandenen Werte eines Feldes.

    Rueckgabe None, wenn KEIN einziger Wert vorlag: dann ist die Kennzahl
    fuer diesen Spieler nicht erhoben, und eine 0 waere eine Behauptung,
    die die Daten nicht hergeben. Ein fehlender Wert verschiebt spaeter
    nichts - er landet neutral auf dem Positionsmittel.
    """
    total = 0.0
    seen = False
    for match in matches:
        value = _num(match.get(field))
        if value is None:
            continue
        seen = True
        total += value * (match.get("weight") or 1.0) if weighted else value
    return total if seen else None


def _goal_assists(matches):
    """Kontextgewichtete Torbeteiligungen. Tor und Vorlage zaehlen 1:1."""
    from src.features.big_games import _goal_assist_contribution

    total = 0.0
    seen = False
    for match in matches:
        contribution = _goal_assist_contribution(
            match.get("goals"), match.get("assists"))
        if contribution is None:
            continue
        seen = True
        total += contribution * (match.get("weight") or 1.0)
    return total if seen else None


def _def_actions(matches):
    """Tackles plus abgefangene Baelle, kontextgewichtet."""
    total = 0.0
    seen = False
    for match in matches:
        tackles = _num(match.get("tackles"))
        interceptions = _num(match.get("interceptions"))
        if tackles is None and interceptions is None:
            continue
        seen = True
        total += ((tackles or 0.0) + (interceptions or 0.0)) * (
            match.get("weight") or 1.0)
    return total if seen else None


def _per90(total, minutes):
    if total is None or not minutes:
        return None
    return total / (minutes / 90.0)


def player_inputs(matches):
    """
    Die Eingangswerte EINES Spielers aus seinen bereits qualifizierten Spielen.

    Erwartet je Spiel mindestens ``minutes`` und ``weight``; alle
    Statistikfelder duerfen fehlen. Zurueck kommen ausschliesslich
    kontextgewichtete Raten je 90 Minuten plus der Umfang.

    Der Kontext steckt im Zaehler (jedes Ereignis zaehlt so viel, wie das
    Spiel wog), der Umfang im Nenner (echte Minuten). Damit bleibt die
    Rate vergleichbar, waehrend ``weighted_90s`` den erlebten Kontext als
    eigene Groesse traegt.
    """
    played = [m for m in matches if (m.get("minutes") or 0) > 0]
    minutes = sum(m.get("minutes") or 0 for m in played)
    rated = [(_num(m.get("rating")), m.get("minutes") or 0, m.get("weight") or 1.0)
             for m in played if _num(m.get("rating")) is not None]
    rated_minutes = sum(m for _r, m, _w in rated)

    weighted_90s = sum(
        (m.get("minutes") or 0) * (m.get("weight") or 1.0) for m in played) / 90.0

    return {
        "matches": len(played),
        "minutes": minutes,
        "weighted_90s": weighted_90s,
        # Die ECHTE Durchschnittsbewertung, nur nach Einsatzzeit gewichtet
        # und ohne Kontextfaktor - allein fuer die Anzeige. Die Bewertung
        # in "metrics" ist kontextgewichtet und kann deshalb ueber 10
        # liegen; als angezeigte "Note" waere das schlicht falsch.
        "avg_rating": (sum(r * m for r, m, _w in rated) / rated_minutes
                       if rated_minutes else None),
        "metrics": {
            METRIC_GA:          _per90(_goal_assists(played), minutes),
            METRIC_SHOTS_ON:    _per90(_sum_present(played, "shots_on"), minutes),
            METRIC_KEY_PASSES:  _per90(_sum_present(played, "passes_key"), minutes),
            METRIC_PASSES:      _per90(_sum_present(played, "passes_total"), minutes),
            METRIC_DRIBBLES:    _per90(_sum_present(played, "dribbles_success"), minutes),
            METRIC_DUELS_WON:   _per90(_sum_present(played, "duels_won"), minutes),
            METRIC_DEF_ACTIONS: _per90(_def_actions(played), minutes),
            METRIC_SAVES:       _per90(_sum_present(played, "saves"), minutes),
            METRIC_CONCEDED:    _per90(_sum_present(played, "goals_conceded"), minutes),
            # Die Bewertung ist bereits ein Mittelwert je Spiel: sie wird
            # nach Einsatzzeit gemittelt und mit dem Kontext gewichtet,
            # nicht aufsummiert.
            METRIC_RATING: (
                sum(r * w * m for r, m, w in rated) / rated_minutes
                if rated_minutes else None),
        },
    }


# ---------------------------------------------------------------------------
# 5. Robuste Normalisierung innerhalb der Position
# ---------------------------------------------------------------------------
#
# Fussballdaten sind schief: wenige Spieler mit sehr hohen Werten ziehen
# Mittelwert und Standardabweichung mit. Median und MAD tun das nicht -
# deshalb hier Median/MAD statt Mittelwert/Standardabweichung.
#
# 1.4826 ist der uebliche Faktor, der den MAD einer Normalverteilung auf
# deren Standardabweichung bringt; damit bleibt eine Einheit ungefaehr
# das, was man von einem z-Wert erwartet.

MAD_TO_SIGMA = 1.4826


def robust_center_scale(values):
    """
    (Median, robuste Streuung) einer Werteliste.

    Ist der MAD 0 - etwa weil fast alle denselben Wert haben -, wird auf
    die Standardabweichung ausgewichen. Ist auch die 0, gibt es keine
    Streuung: dann ist jede Abweichung 0 und die Kennzahl entscheidet
    nichts. Das ist richtig so und keine Notloesung.
    """
    present = [v for v in values if v is not None]
    if not present:
        return 0.0, 0.0
    center = statistics.median(present)
    mad = statistics.median([abs(v - center) for v in present]) * MAD_TO_SIGMA
    if mad > 0:
        return center, mad
    if len(present) > 1:
        spread = statistics.pstdev(present)
        if spread > 0:
            return center, spread
    return center, 0.0


def robust_z(value, center, scale):
    """Abweichung in robusten Streuungseinheiten. Fehlt der Wert: 0."""
    if value is None or not scale:
        return 0.0
    return (value - center) / scale


#: Grenze je Einzelkennzahl. Ein einzelner Extremwert (etwa ein Torhueter
#: mit sehr wenigen Gegentoren) soll eine Position nicht allein
#: entscheiden; die Grenze liegt weit ausserhalb des normalen Feldes.
Z_CLAMP = 3.0

#: Eigene, engere Grenze fuer den UMFANG.
#:
#: Der Umfang misst Verlaesslichkeit, nicht Klasse - und sein Nutzen
#: saettigt: der Unterschied zwischen 5 und 15 Big Games sagt viel, der
#: zwischen 20 und 30 fast nichts mehr. Ohne diese engere Grenze konnte
#: blosse Masse fehlende Klasse ausgleichen: ein Spieler mit 30 schwachen
#: Einsaetzen ohne eine einzige Torbeteiligung zog am Umfangsanschlag
#: (0.35 x 3.0 = 1.05) an einem deutlich staerkeren Spieler mit acht
#: Einsaetzen vorbei. Die Qualitaet bleibt bei +-3 und behaelt damit das
#: letzte Wort.
VOLUME_Z_CLAMP = 2.0


def _clamp(value, low, high):
    return max(low, min(high, value))


# ---------------------------------------------------------------------------
# 6. Die Bewertung einer ganzen Population
# ---------------------------------------------------------------------------

def score_population(players):
    """
    Bewertet eine Population gemeinsam und gibt je Spieler die Zerlegung zurueck.

    players: Liste von Dicts mit
        player_id  stabile Kennung
        position   GK/DEF/MID/ATT in der Projektschreibweise
        inputs     Ergebnis von player_inputs()

    Der Rechenweg, in dieser Reihenfolge:

        1. Je Position und Kennzahl Median und robuste Streuung bilden.
        2. Jede Kennzahl eines Spielers in Streuungseinheiten umrechnen
           (Gegentore mit umgekehrtem Vorzeichen), begrenzen, mit dem
           Positionsgewicht multiplizieren und aufsummieren -> Qualitaet.
        3. Die Qualitaet Richtung Positionsmittel schrumpfen. Im
           Streuungsraum ist dieses Mittel per Definition 0, deshalb ist
           die Schrumpfung genau n/(n+k).
        4. Den Umfang (gewichtete 90er) ebenfalls innerhalb der Position
           normalisieren - ein Torhueter soll nicht deshalb vorn liegen,
           weil Torhueter mehr durchspielen.
        5. Beides mischen und auf die oeffentliche Skala legen.

    Normalisiert wird IMMER innerhalb der Position, auch wenn die Liste
    danach positionsuebergreifend angezeigt wird. Genau das nimmt der
    Position ihren strukturellen Vorteil.
    """
    by_position = {}
    for player in players:
        by_position.setdefault(player.get("position"), []).append(player)

    results = {}
    for position, group in by_position.items():
        profile = profile_for(position)

        # Schritt 1: Lage und Streuung je Kennzahl in dieser Position.
        statistik = {}
        for metric in profile:
            statistik[metric] = robust_center_scale(
                [p["inputs"]["metrics"].get(metric) for p in group])
        volumen_lage, volumen_streuung = robust_center_scale(
            [p["inputs"]["weighted_90s"] for p in group])

        for player in group:
            inputs = player["inputs"]

            # Schritt 2: gewichtete Summe der normalisierten Kennzahlen.
            beitraege = {}
            qualitaet = 0.0
            for metric, gewicht in profile.items():
                center, scale = statistik[metric]
                z = robust_z(inputs["metrics"].get(metric), center, scale)
                if metric in LOWER_IS_BETTER:
                    z = -z
                z = _clamp(z, -Z_CLAMP, Z_CLAMP)
                beitraege[metric] = gewicht * z
                qualitaet += gewicht * z

            # Schritt 3: Schrumpfung Richtung Positionsmittel (= 0).
            n = inputs["weighted_90s"]
            schrumpfung = n / (n + SHRINKAGE_K) if (n + SHRINKAGE_K) else 0.0
            geschrumpft = qualitaet * schrumpfung

            # Schritt 4: Umfang, innerhalb der Position normalisiert und
            # enger begrenzt als die Qualitaet (siehe VOLUME_Z_CLAMP).
            volumen = _clamp(
                robust_z(inputs["weighted_90s"], volumen_lage, volumen_streuung),
                -VOLUME_Z_CLAMP, VOLUME_Z_CLAMP)

            # Schritt 5: mischen und auf die oeffentliche Skala legen.
            gesamt = RATE_SHARE * geschrumpft + VOLUME_SHARE * volumen
            score = _clamp(SCORE_CENTER + SCORE_SPREAD * gesamt,
                           SCORE_MIN, SCORE_MAX)

            results[player["player_id"]] = {
                "score": round(score, 2),
                "quality_z": round(qualitaet, 4),
                "shrunk_quality_z": round(geschrumpft, 4),
                "volume_z": round(volumen, 4),
                "shrinkage": round(schrumpfung, 4),
                "weighted_90s": round(n, 3),
                "contributions": {k: round(v, 4) for k, v in beitraege.items()},
            }
    return results


__all__ = [
    "RANKING_MIN_BIG_GAMES", "RANKING_MIN_MINUTES", "is_rankable",
    "RATE_SHARE", "VOLUME_SHARE", "SHRINKAGE_K",
    "SCORE_CENTER", "SCORE_SPREAD", "SCORE_MIN", "SCORE_MAX",
    "POSITION_PROFILES", "DEFAULT_PROFILE", "MAX_RATING_SHARE", "profile_for",
    "LOWER_IS_BETTER", "Z_CLAMP", "VOLUME_Z_CLAMP",
    "METRIC_GA", "METRIC_SHOTS_ON", "METRIC_KEY_PASSES", "METRIC_PASSES",
    "METRIC_DRIBBLES", "METRIC_DUELS_WON", "METRIC_DEF_ACTIONS",
    "METRIC_SAVES", "METRIC_CONCEDED", "METRIC_RATING",
    "player_inputs", "robust_center_scale", "robust_z", "score_population",
]
