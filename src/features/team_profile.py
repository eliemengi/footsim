"""
Teamprofile aus vollstaendigen Saisondaten.

Kernidee
--------
Statt einer einzigen undurchsichtigen "Staerke 87" bekommt jedes Team vier
Kennzahlen, jeweils RELATIV zum Ligadurchschnitt:

    attack_home    Wie viele Tore schiesst das Team zuhause,
                   verglichen mit einem durchschnittlichen Heimteam?
    attack_away    dasselbe auswaerts
    defence_home   Wie viele Tore kassiert es zuhause,
                   verglichen mit einem durchschnittlichen Heimteam?
    defence_away   dasselbe auswaerts

1.0 bedeutet immer exakt Ligadurchschnitt.
1.4 im Angriff heisst: 40 % mehr Tore als der Durchschnitt.
0.7 in der Abwehr heisst: 30 % weniger Gegentore als der Durchschnitt.
Bei der Abwehr ist also KLEINER BESSER.

Daraus ergeben sich die erwarteten Tore eines Spiels als einfaches Produkt:

    xG_heim  = liga_schnitt_heimtore * attack_home(H) * defence_away(A)
    xG_gast  = liga_schnitt_gasttore * attack_away(A) * defence_home(H)

Der Heimvorteil steckt automatisch drin, weil der Ligaschnitt fuer
Heimtore hoeher ist als fuer Gasttore. Er muss nicht extra addiert werden.

Warum relativ und nicht absolut?
--------------------------------
Absolute Torwerte sind zwischen Ligen nicht vergleichbar: In der einen
Liga fallen im Schnitt 3.1 Tore pro Spiel, in der anderen 2.6. Ein Team
mit 1.6 Toren pro Spiel ist in der ersten Liga unterdurchschnittlich, in
der zweiten ueberdurchschnittlich. Die Normalisierung macht Teams
ligauebergreifend vergleichbar und ist die Voraussetzung dafuer, spaeter
Aufsteiger aus einer anderen Liga sinnvoll einzuordnen.

Shrinkage gegen kleine Stichproben
----------------------------------
Ein Team mit drei Spielen und 9 Toren haette rechnerisch ein Attack-Rating
von 3.0. Das ist Zufall, keine Staerke. Deshalb wird jedes Rating zum
Ligamittel (1.0) hin gezogen, und zwar umso staerker, je weniger Spiele
vorliegen:

    rating_final = (n * rating_roh + k * 1.0) / (n + k)

k ist die Regularisierungskonstante (Standard 5). Bei 34 Spielen ist der
Effekt gering, bei 3 Spielen dominiert er. Das ist dasselbe Prinzip wie
bei der dynamischen Saisongewichtung, nur auf der Ebene einzelner Ratings.
"""

from collections import defaultdict

from src.features.model_constants import domestic_league_avg_fallback


# Regularisierung fuer Attack/Defence-Ratings. Entspricht der Anzahl
# "fiktiver Durchschnittsspiele", die jedem Team hinzugerechnet werden.
DEFAULT_SHRINKAGE_K = 5.0

# Grenzen, damit ein Extremwert die Simulation nicht sprengt. Ein Team
# mit dreifacher Durchschnittsoffensive existiert im Profifussball nicht.
RATING_MIN = 0.35
RATING_MAX = 2.20

# Ohne jede Datengrundlage gilt exakt Ligadurchschnitt.
NEUTRAL_RATING = 1.0

# Geometrischer Abfall der Saisongewichtung: Jede aeltere Saison bekommt
# diesen Anteil der juengeren. Modellannahme, spaeter empirisch zu
# bestimmen - siehe src/features/model_constants.py.
SEASON_DECAY = 0.55

# Sicherheitsgrenzen fuer den Erwartungswert einer Partie. Guardrail,
# kein Modellparameter: Im Normalbetrieb greifen sie nie.
XG_MIN = 0.15
XG_MAX = 4.5


def _clamp(value, low=RATING_MIN, high=RATING_MAX):
    return max(low, min(value, high))


def _shrink(raw_rating, sample_size, k=DEFAULT_SHRINKAGE_K):
    """
    Zieht ein Rohrating zum Ligamittel, abhaengig von der Stichprobe.

    Wenige Spiele -> Ergebnis nahe 1.0 (Durchschnitt).
    Viele Spiele  -> Ergebnis nahe dem Rohwert.
    """
    if sample_size <= 0:
        return NEUTRAL_RATING
    return (sample_size * raw_rating + k * NEUTRAL_RATING) / (sample_size + k)


def league_averages(matches):
    """
    Durchschnittliche Heim- und Gasttore der Liga.

    Basis fuer alle Normalisierungen. Wird aus genau den Spielen berechnet,
    die auch in die Teamprofile eingehen, damit beide zueinander passen.
    """
    if not matches:
        return domestic_league_avg_fallback()

    home_total = sum(m["home_goals"] for m in matches)
    away_total = sum(m["away_goals"] for m in matches)
    n = len(matches)

    return {
        "home_goals": home_total / n,
        "away_goals": away_total / n,
        "total_goals": (home_total + away_total) / n,
        "matches": n,
    }


def _empty_stats():
    return {
        "matches": 0, "home_matches": 0, "away_matches": 0,
        "goals_for": 0, "goals_against": 0,
        "home_goals_for": 0, "home_goals_against": 0,
        "away_goals_for": 0, "away_goals_against": 0,
        "wins": 0, "draws": 0, "losses": 0, "points": 0,
    }


def collect_team_stats(matches):
    """
    Zaehlt die Rohstatistik jedes Teams aus einer Spielliste.

    Rueckgabe: { team_id: stats_dict }
    Reine Zaehlarbeit, keine Bewertung. Die Trennung von Zaehlen und
    Bewerten macht beide Schritte einzeln testbar.
    """
    stats = defaultdict(_empty_stats)

    for match in matches:
        home_id = match["home_id"]
        away_id = match["away_id"]
        hg = match["home_goals"]
        ag = match["away_goals"]

        h = stats[home_id]
        a = stats[away_id]

        h["matches"] += 1
        h["home_matches"] += 1
        h["goals_for"] += hg
        h["goals_against"] += ag
        h["home_goals_for"] += hg
        h["home_goals_against"] += ag

        a["matches"] += 1
        a["away_matches"] += 1
        a["goals_for"] += ag
        a["goals_against"] += hg
        a["away_goals_for"] += ag
        a["away_goals_against"] += hg

        if hg > ag:
            h["wins"] += 1
            h["points"] += 3
            a["losses"] += 1
        elif hg < ag:
            a["wins"] += 1
            a["points"] += 3
            h["losses"] += 1
        else:
            h["draws"] += 1
            a["draws"] += 1
            h["points"] += 1
            a["points"] += 1

    return dict(stats)


def build_season_profiles(payload, shrinkage_k=DEFAULT_SHRINKAGE_K):
    """
    Erstellt aus einer geladenen Saison die Profile aller Teams.

    payload: Rueckgabe von historical_loader.load_season()
    Rueckgabe: {
        "season": 2024,
        "league_avg": {...},
        "profiles": { team_id: {attack_home, attack_away, defence_home,
                                defence_away, points_per_game, ..., stats} }
    }
    """
    matches = payload.get("matches", [])
    teams = payload.get("teams", {})
    avg = league_averages(matches)
    stats_by_team = collect_team_stats(matches)

    profiles = {}

    for team_id, stats in stats_by_team.items():
        hm = stats["home_matches"]
        am = stats["away_matches"]

        # Rohwerte: Tore pro Spiel im jeweiligen Kontext.
        raw_attack_home = (stats["home_goals_for"] / hm / avg["home_goals"]) if hm and avg["home_goals"] else NEUTRAL_RATING
        raw_attack_away = (stats["away_goals_for"] / am / avg["away_goals"]) if am and avg["away_goals"] else NEUTRAL_RATING

        # Wichtig: Was ein Heimteam kassiert, sind Gasttore. Deshalb wird
        # defence_home am Gasttor-Schnitt normalisiert und umgekehrt.
        raw_defence_home = (stats["home_goals_against"] / hm / avg["away_goals"]) if hm and avg["away_goals"] else NEUTRAL_RATING
        raw_defence_away = (stats["away_goals_against"] / am / avg["home_goals"]) if am and avg["home_goals"] else NEUTRAL_RATING

        team_info = teams.get(team_id, {})

        profiles[team_id] = {
            "team_id": team_id,
            "team_name": team_info.get("name") or str(team_id),
            "short_name": team_info.get("short_name"),
            "crest": team_info.get("crest"),

            "attack_home":  _clamp(_shrink(raw_attack_home, hm, shrinkage_k)),
            "attack_away":  _clamp(_shrink(raw_attack_away, am, shrinkage_k)),
            "defence_home": _clamp(_shrink(raw_defence_home, hm, shrinkage_k)),
            "defence_away": _clamp(_shrink(raw_defence_away, am, shrinkage_k)),

            "points_per_game": stats["points"] / stats["matches"] if stats["matches"] else 0.0,
            "goals_for_per_game": stats["goals_for"] / stats["matches"] if stats["matches"] else 0.0,
            "goals_against_per_game": stats["goals_against"] / stats["matches"] if stats["matches"] else 0.0,
            "win_rate": stats["wins"] / stats["matches"] if stats["matches"] else 0.0,

            "matches_used": stats["matches"],
            "stats": stats,
        }

    return {
        "season": payload.get("meta", {}).get("season"),
        "api_code": payload.get("meta", {}).get("api_code"),
        "league_avg": avg,
        "profiles": profiles,
    }


def season_weights(n_seasons, decay=SEASON_DECAY):
    """
    Gewichte fuer mehrere Saisons, neueste zuerst.

    Geometrischer Abfall: jede aeltere Saison bekommt den Anteil `decay`
    der vorherigen. Bei decay=0.55 und zwei Saisons ergibt das rund
    65 % / 35 %, bei drei Saisons rund 55 % / 30 % / 16 %.

    Warum geometrisch statt fester Prozentwerte? Weil die Zahl der
    verfuegbaren Saisons je nach Tarif schwankt. Die Formel liefert immer
    eine sinnvolle, auf 1 normierte Verteilung, egal ob eine, zwei oder
    fuenf Saisons vorliegen.
    """
    if n_seasons <= 0:
        return []

    raw = [decay ** i for i in range(n_seasons)]
    total = sum(raw)
    return [w / total for w in raw]


def blend_profiles(season_profile_list, decay=SEASON_DECAY):
    """
    Verschmilzt mehrere Saisonprofile zu einem historischen Gesamtprofil.

    season_profile_list: Ergebnisse von build_season_profiles(),
                         NEUESTE SAISON ZUERST.

    Teams, die nicht in allen Saisons vorkommen (Auf-/Absteiger), werden
    nur ueber die Saisons gemittelt, in denen sie tatsaechlich gespielt
    haben. Die Gewichte werden dafuer neu normiert, damit ein Team mit nur
    einer Saison nicht faelschlich Richtung Ligamittel gezogen wird.
    """
    if not season_profile_list:
        return {}

    weights = season_weights(len(season_profile_list), decay=decay)
    rating_keys = ("attack_home", "attack_away", "defence_home", "defence_away")
    extra_keys = ("points_per_game", "goals_for_per_game",
                  "goals_against_per_game", "win_rate")

    # Sammeln, in welchen Saisons jedes Team vorkommt.
    per_team = defaultdict(list)   # team_id -> [(weight, profile, season)]
    for weight, season_data in zip(weights, season_profile_list):
        season = season_data.get("season")
        for team_id, profile in season_data["profiles"].items():
            per_team[team_id].append((weight, profile, season))

    blended = {}

    for team_id, entries in per_team.items():
        total_weight = sum(w for w, _, _ in entries)
        if total_weight <= 0:
            continue

        merged = {
            "team_id": team_id,
            "team_name": entries[0][1]["team_name"],
            "short_name": entries[0][1].get("short_name"),
            "crest": entries[0][1].get("crest"),
            "seasons_used": [s for _, _, s in entries],
            "seasons_count": len(entries),
            "matches_used": sum(p["matches_used"] for _, p, _ in entries),
        }

        for key in rating_keys + extra_keys:
            merged[key] = sum(w * p[key] for w, p, _ in entries) / total_weight

        blended[team_id] = merged

    return blended


def expected_goals(home_profile, away_profile, league_avg):
    """
    Erwartete Tore beider Teams fuer eine Partie.

    Das ist die zentrale Formel des Modells und bewusst simpel gehalten:

        xG_heim = Ligaschnitt_Heimtore * Angriff_Heim * Abwehr_Gast
        xG_gast = Ligaschnitt_Gasttore * Angriff_Gast * Abwehr_Heim

    Jeder Faktor ist einzeln erklaerbar und einzeln pruefbar. Der
    Heimvorteil ist implizit enthalten, weil Ligaschnitt_Heimtore
    groesser ist als Ligaschnitt_Gasttore.
    """
    xh = (
        league_avg["home_goals"]
        * home_profile["attack_home"]
        * away_profile["defence_away"]
    )
    xa = (
        league_avg["away_goals"]
        * away_profile["attack_away"]
        * home_profile["defence_home"]
    )

    # Sicherheitsgrenzen: verhindert absurde Erwartungswerte.
    return max(XG_MIN, min(xh, XG_MAX)), max(XG_MIN, min(xa, XG_MAX))


def neutral_profile(team_id=None, team_name=None):
    """Profil eines exakt durchschnittlichen Teams. Letzte Fallback-Stufe."""
    return {
        "team_id": team_id,
        "team_name": team_name or "Unbekannt",
        "short_name": team_name,
        "crest": None,
        "attack_home": NEUTRAL_RATING,
        "attack_away": NEUTRAL_RATING,
        "defence_home": NEUTRAL_RATING,
        "defence_away": NEUTRAL_RATING,
        "points_per_game": 1.35,
        "goals_for_per_game": 1.35,
        "goals_against_per_game": 1.35,
        "win_rate": 0.33,
        "seasons_used": [],
        "seasons_count": 0,
        "matches_used": 0,
    }
