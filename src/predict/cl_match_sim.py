"""
Einzelspielsimulation fuer die Champions-League-Ligaphase (Block B1).

Warum ein eigenes Modul, getrennt von league_match_sim.py?
------------------------------------------------------------
league_match_sim.py ist an die fuenf nationalen Ligen gebunden: seine
Fallback-Kette (strength_provider.get_league_strengths) sucht
Team-Historie INNERHALB einer einzigen Liga und kennt eine
Aufsteiger-Stufe. Beides ergibt fuer die Champions League keinen
fachlichen Sinn - CL-Teilnehmer koennen aus jeder europaeischen Liga
kommen, nicht nur aus den fuenf von FootSim simulierten, und es gibt
keine Auf-/Abstiegsbeziehung zwischen CL und den Top-5-Ligen.

Die Fallback-Kette hier ist deshalb bewusst anders (siehe
strength_provider.get_cl_team_strengths fuer die Datengrundlage):

    Stufe 0  Team-ID in der geblendeten Historie EINER der fuenf
             Top-Ligen (deckt die meisten CL-Teilnehmer ab: Bayern,
             PSG, Real Madrid, ...)
    Stufe 1  keine Top-5-Liga-Historie, aber echte CL-Ergebnisse dieser
             Saison vorhanden (Bodoe/Glimt, Galatasaray, Qarabag, ...)
    Stufe 2  neutral_profile - letzter Ausweg

Ersetzt vollstaendig den alten Pfad in simulate_scores.py
(MATCHES_TO_PREDICT_CL-Dictionaries, Teams identifiziert ueber
Klarnamen wie "Bodo Glimt"). Teams werden hier ausschliesslich ueber
football-data-Team-IDs identifiziert. Nutzt dasselbe moderne
Staerkemodell (team_profile.expected_goals) wie die Ligen, nicht die
alte avg_goals_scored/winrate-Formel aus simulate_scores.py.

Deckt in Block B1 nur die Ligaphase ab (Einzelspiel, kein Hin-/
Rueckspiel-Aggregat). Die K.-o.-Phase mit ihrer Zwei-Leg-Logik folgt in
einem spaeteren Schritt, sobald echte Runden/Begegnungen in der
Oberflaeche abgebildet werden (Block B2).
"""

import random
from collections import Counter

from src.features.pit_profiles import (
    PitProfileRepository, fixture_cutoff, runtime_cutoff)
from src.features.strength_provider import get_cl_team_strengths
from src.predict.poisson import poisson as _poisson
from src.features.team_profile import expected_goals, neutral_profile
from src.ml.runtime import resolve_simulation_lambdas
from src.predict import cl_custom_factors as ccf
from src.utils import cache


def _resolve_cl_profile(strengths, team_id, team_name):
    """
    Loest ein Champions-League-Teamprofil auf.

    Reihenfolge:
      1. Team-ID in der Top-5-Liga-Historie (strengths["domestic_by_id"])
      2. Team-ID in den echten CL-Ergebnissen dieser Saison
         (strengths["cl_current_by_id"])
      3. Neutralprofil (niemals None)

    Rueckgabe: (profil, resolution) - resolution beschreibt den Weg und
    landet in der API-Antwort, damit im Frontend/Debug sichtbar ist, wie
    belastbar der Wert ist.
    """
    domestic = strengths["domestic_by_id"]
    cl_current = strengths["cl_current_by_id"]

    if team_id is not None and team_id in domestic:
        return domestic[team_id], "domestic_history"

    if team_id is not None and team_id in cl_current:
        return cl_current[team_id], "cl_current_season"

    return neutral_profile(team_id, team_name), "neutral"


def simulate_cl_league_phase_match(
    home_team,
    away_team,
    home_id=None,
    away_id=None,
    season=None,
    simulations=5000,
    use_seed=False,
    options=None,
    kickoff=None,
):
    """
    Simuliert ein einzelnes Champions-League-Ligaphasenspiel.

    Liefert dasselbe Antwortformat wie league_match_sim.simulate_league_match
    (das Frontend braucht keine CL-Sonderbehandlung fuer die Grunddaten),
    ergaenzt um Herkunftsangaben je Team (home_resolution/away_resolution).

    options: geprueftes Ergebnis von cl_custom_factors.parse_options().
             Ohne Angabe bleibt alles beim bisherigen Verhalten - die
             Profile werden nicht angefasst und die ML-Betriebsart
             kommt weiterhin aus der Umgebung.

    kickoff: Anstosszeitpunkt der Begegnung und damit der Stichtag der
             Profile. Ausdrueckliche Angabe hat Vorrang; sie ist der
             Einstieg fuer Tests und fuer Aufrufer, die den Zeitpunkt
             bereits kennen.
    """
    rng = random.Random(42 if use_seed else None)

    # EINE Fabrik fuer diesen Request: Sie loest den Anstoss auf UND
    # baut danach die Profile. Zwei Instanzen laesen dieselbe
    # Saisondatei zweimal.
    repository = PitProfileRepository()

    # DER STICHTAG (V2-C1B)
    #
    # Reihenfolge, und zwar begruendet:
    #
    #   1. ausdruecklich uebergebener kickoff
    #   2. der ECHTE Anstoss dieser Begegnung aus der eigenen Historie
    #   3. der Laufzeitstichtag "jetzt"
    #
    # Stufe 2 schliesst die Luecke, die V2-C1 offen liess: Wer eine
    # bereits gespielte Partie nachsimuliert, bekam bis dahin den
    # heutigen Tag als Stichtag - und damit alle spaeteren Partien
    # derselben Saison, die es zum Anstoss noch gar nicht gab.
    #
    # Aufgeloest wird SERVERSEITIG aus derselben lokalen Historie, aus
    # der auch die Profile entstehen. Der Client schickt dafuer nichts
    # Neues: Saison und Mannschaften stehen ohnehin im Request. Einen
    # Zeitpunkt vom Client entgegenzunehmen hiesse, eine fachliche
    # Wahrheit von aussen bestimmen zu lassen.
    #
    # Steht die Begegnung nicht in der Historie, ist sie kuenftig oder
    # unbekannt - dann gilt "jetzt". Ein stilles Zurueckfallen auf die
    # komplette Saison gibt es nicht.
    cutoff = runtime_cutoff(
        kickoff
        or fixture_cutoff(season, home_id, away_id, repository=repository))

    # Der Stichtag gehoert in den Schluessel. Ohne ihn koennte ein
    # Profil zum 01.10.2024 durch einen Treffer fuer den 01.03.2025
    # ersetzt werden - genau die Verwechslung, die V2-C1 beseitigt.
    strength_key = f"cl_strengths:{season}:{cutoff}"
    strengths = cache.cached_call(
        key=strength_key,
        ttl_seconds=60 * 30,
        loader=lambda: get_cl_team_strengths(season=season, cutoff=cutoff,
                                             repository=repository),
    )

    home_profile, home_resolution = _resolve_cl_profile(strengths, home_id, home_team)
    away_profile, away_resolution = _resolve_cl_profile(strengths, away_id, away_team)

    league_avg = strengths["league_avg"]

    # Individuelle Faktoren (C8A) - ausschliesslich auf Kopien. Ohne
    # Optionen bleiben Profile und Ligaschnitt exakt die aus dem
    # Zwischenspeicher, und die Rechnung ist bitgleich wie zuvor.
    faktoren = (options or {}).get("factors") or ccf.NEUTRAL_FACTORS
    if options is not None:
        home_profile, away_profile, league_avg = ccf.apply_factors(
            home_profile, away_profile, league_avg, faktoren)

    basis_xh, basis_xa = expected_goals(home_profile, away_profile, league_avg)

    # ML-Anbindung (C7). Im Standardmodus off gibt diese Funktion die
    # Baselinewerte unveraendert zurueck und laedt kein Modell - die
    # Simulation rechnet dann bitgleich wie zuvor. Nur wenn der
    # Betreiber ausdruecklich active gesetzt hat UND die gesamte
    # ML-Kette getragen hat, kommen andere Lambdas heraus.
    # Die ML-Korrektur rechnet auf den INDIVIDUALISIERTEN Profilen -
    # sie liest ihre 16 Merkmale aus genau diesen Werten. Die
    # Konfiguration kommt bei gesetzten Optionen aus dem Request und
    # niemals aus os.environ.
    ml = resolve_simulation_lambdas(
        basis_xh, basis_xa,
        home_profile=home_profile, away_profile=away_profile,
        home_resolution=home_resolution, away_resolution=away_resolution,
        config=ccf.ml_config(options))
    xh, xa = ml["lambda_home"], ml["lambda_away"]

    home_wins = draws = away_wins = 0
    score_counter = Counter()

    for _ in range(simulations):
        hg = _poisson(xh, rng)
        ag = _poisson(xa, rng)
        score_counter[f"{hg}:{ag}"] += 1

        if hg > ag:
            home_wins += 1
        elif hg == ag:
            draws += 1
        else:
            away_wins += 1

    return {
        "home_team": home_team,
        "away_team": away_team,
        "expected_home_goals": round(xh, 2),
        "expected_away_goals": round(xa, 2),
        "home_win_probability": round(home_wins / simulations * 100, 2),
        "draw_probability": round(draws / simulations * 100, 2),
        "away_win_probability": round(away_wins / simulations * 100, 2),
        "top_scores": [
            {"score": score, "count": count}
            for score, count in score_counter.most_common(5)
        ],
        "competition": "Champions League",
        "phase": "league",
        "home_resolution": home_resolution,
        "away_resolution": away_resolution,
        # Additiv (C7). Bestehende Clients ignorieren das Feld; im
        # Standardmodus off steht hier lediglich, dass ML aus ist.
        "ml": {
            "mode": ml["mode"],
            "applied": ml["ml_applied_to_production"],
            "applied_weight": ml["applied_weight"],
            "status": ml["ml_status"],
            "fallback_reason": ml["fallback_reason"],
            "model_id": ml["model_id"],
            "baseline_lambda_home": round(ml["baseline_lambda_home"], 4),
            "baseline_lambda_away": round(ml["baseline_lambda_away"], 4),
            "final_lambda_home": round(ml["lambda_home"], 4),
            "final_lambda_away": round(ml["lambda_away"], 4),
            # Was der Request wollte und was tatsaechlich galt.
            "requested_approach": (options or {}).get("approach"),
            "applied_approach": ((options or {}).get("approach")
                                 or "environment_default"),
            "requested_weight": ml["requested_weight"],
            "applied_factors": dict(faktoren),
        },
    }
