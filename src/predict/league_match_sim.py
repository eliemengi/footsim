"""
Einzelspielsimulation fuer Ligaspiele ueber das moderne Staerkemodell.

Warum ein eigenes Modul?
------------------------
Der alte Pfad (simulate_scores._simulate_direct_team_match) griff auf
team_matches.json zurueck - eine von main.py gepflegte Datei, die nur die
dort erfassten Teams enthaelt und ueber NAMEN matcht. Jedes neue oder
aufgestiegene Team fehlte darin, und die Simulation brach mit
"Teamdaten fehlen" ab. Genau das Muster:

    etabliert gegen etabliert   -> funktionierte
    Spiel mit Aufsteiger        -> ValueError

Dieser Pfad hier benutzt dieselbe Quelle wie die Saisonsimulation:
strength_provider.get_league_strengths mit der garantierten
Fallback-Kette (ID -> Alias/Name -> laufende Saison -> Aufsteigerprofil
-> Neutralwert). Ein Team ohne Historie fuehrt damit NIE zum Abbruch,
sondern zu einem konservativen Profil mit ausgewiesener Herkunft.

Die Zuordnung laeuft primaer ueber die team_id (Frontend liefert sie
mit), Namen sind nur Notbehelf.
"""

import random
from collections import Counter
from datetime import date, datetime, time as dtime

from src.api.league_api import get_standings, resolve_season
from src.predict.fixture_plan import build_season_plan
from src.features.strength_provider import (
    get_league_strengths,
    normalize_name,
    _alias_candidates,
)
from src.predict.poisson import poisson as _poisson
from src.features.team_profile import expected_goals, neutral_profile
from src.utils import cache
from src.features import go3_provider, go45_provider


def _resolve_profile(profiles, standings_rows, team_id, team_name):
    """
    Findet das Profil eines Teams. Reihenfolge:
      1. exakte team_id
      2. team_id ueber die Tabellenzeile mit gleichem Namen
      3. normalisierter Name / Alias gegen die Profil-Namen
      4. Neutralprofil (niemals None)
    Rueckgabe: (profil, resolution) - resolution beschreibt den Weg.
    """
    if team_id is not None and team_id in profiles:
        return profiles[team_id], "id"

    # Tabellenzeile ueber den Namen finden, dann deren ID benutzen.
    wanted = normalize_name(team_name)
    if wanted:
        for row in standings_rows:
            if normalize_name(row.get("team_name")) == wanted \
                    or normalize_name(row.get("team_full_name")) == wanted:
                rid = row.get("team_id")
                if rid in profiles:
                    return profiles[rid], "standings_name"

        # Aliase gegen die Profilnamen selbst.
        candidates = {normalize_name(c) for c in _alias_candidates(team_name)}
        for profile in profiles.values():
            names = {
                normalize_name(profile.get("team_name")),
                normalize_name(profile.get("short_name")),
            }
            if candidates & {n for n in names if n}:
                return profile, "alias"

    return neutral_profile(team_id, team_name), "neutral"


def _current_season_matches(api_code, season):
    """
    Die bereits abgeschlossenen Partien der laufenden Saison.

    Nutzt denselben Saisonplan wie die Saisonsimulation, damit beide Pfade
    auf identischer Grundlage rechnen.

    Anders als die Saisonsimulation scheitert eine Einzelspielsimulation
    hier aber NICHT, wenn der Spielplan unvollstaendig ist: Die
    Saisonsimulation braucht jede einzelne Restpartie und muss bei
    Luecken abbrechen. Ein einzelnes Spiel braucht nur die bisherige
    Form - fehlt sie, traegt eben allein die Historie, so wie vorher.
    Lieber ein etwas aermeres Ergebnis als gar keines.
    """
    try:
        plan = build_season_plan(api_code, season)
    except Exception:
        return []

    return plan.get("finished_matches") or []


def _go45_snapshot(competition_code, api_code, season, home_id, away_id,
                   home_profile, away_profile, kickoff):
    """
    GO-4-/GO-5-Stand fuer diese Begegnung - oder None.

    Ausgelagert, damit simulate_league_match lesbar bleibt und der
    gesamte Block in EINEN Fehlerfang passt: Faellt hier etwas aus, muss
    die Vorhersage trotzdem herauskommen.

    Ausdruecklich KEIN Provider-Request. Die Ausfaelle werden hier nicht
    live geholt - dafuer gibt es capture_availability_snapshot, das
    getrennt und ausserhalb der Simulation laeuft. Ohne archivierten
    Stand bleibt die Verfuegbarkeit "unavailable" und damit neutral.
    """
    from src.features import go4, go5

    if go4.current_mode() == "off" and go5.current_mode() == "off":
        return None

    try:
        merkmale = go45_provider.league_player_features(competition_code, season)

        # football-data-IDs auf API-Sports-IDs bringen - ueber den
        # bestehenden GO-3-Crosswalk, nicht ueber einen zweiten.
        from src.features.go45_backtest import _apisports_ids_for_league
        fd_zu_as, bekannte = _apisports_ids_for_league(competition_code, season)

        ereignisse = (go45_provider.transfer_events_for(frozenset(bekannte))
                      if bekannte else {"events": []})

        # Kaderlisten aus dem Pool - nur fuer die laufende Saison
        # zulaessig, deshalb ueber den Vereinsnamen des Profils.
        kader = merkmale.get("squads_by_name") or {}

        from src.features.match_timeline import build_timeline, team_timeline
        eintraege, _ = build_timeline([season - 1, season])

        return go45_provider.safe_fixture_snapshot(
            _team_roster(kader, home_id, api_code, season),
            _team_roster(kader, away_id, api_code, season),
            merkmale,
            home_apisports_id=fd_zu_as.get(home_id),
            away_apisports_id=fd_zu_as.get(away_id),
            events=ereignisse.get("events") or [],
            cutoff_date=kickoff.date().isoformat(),
            season=season,
            competition_code=competition_code,
            home_timeline=team_timeline(eintraege, home_id),
            away_timeline=team_timeline(eintraege, away_id),
            cutoff=kickoff,
            home_profile=home_profile, away_profile=away_profile,
        )
    except Exception:
        # Eine Ergaenzung darf die Kernvorhersage nie verhindern.
        return None


def _team_roster(squads_by_name, team_id, api_code, season):
    """
    Die Spieler-IDs eines Teams aus dem Pool.

    Der Pool kennt nur Vereinsnamen, die Simulation nur IDs. Verbunden
    wird ueber die Teamliste der Historiedatei - dieselbe Quelle, aus der
    auch der GO-3-Crosswalk seine football-data-Namen nimmt.

    Findet sich kein Name, ist die Liste leer. GO 4 bleibt dann neutral,
    statt einen falschen Kader zu benutzen.
    """
    from src.data.historical_loader import load_season
    from src.features.team_crosswalk import _normalize

    payload = load_season(api_code, season)
    if not payload or team_id is None:
        return []

    info = (payload.get("teams") or {}).get(str(team_id)) or         (payload.get("teams") or {}).get(team_id) or {}
    name = info.get("name") or info.get("short_name")
    if not name:
        return []

    gesucht = _normalize(name)
    for pool_name, ids in (squads_by_name or {}).items():
        if _normalize(pool_name) == gesucht:
            return ids
    return []


def simulate_league_match(
    competition_code,
    api_code,
    home_team,
    away_team,
    home_id=None,
    away_id=None,
    season=None,
    simulations=5000,
    use_seed=False,
    kickoff=None,
):
    """
    Simuliert ein einzelnes Ligaspiel.

    Liefert dasselbe Antwortformat wie die alte Einzelspielsimulation
    (das Frontend bleibt unveraendert), ergaenzt um Herkunftsangaben.

    kickoff: Anstosszeitpunkt der Begegnung. Er ist der Stichtag fuer die
             Belastungsmerkmale - nur Spiele davor zaehlen. Ohne Angabe
             wird der heutige Tag, 12 Uhr, angesetzt. Bewusst NICHT die
             aktuelle Uhrzeit: die Simulation soll bei gleichem Startwert
             dasselbe Ergebnis liefern, und ein Stichtag, der mit jeder
             Sekunde weiterlaeuft, waere damit unvereinbar.
    """
    rng = random.Random(42 if use_seed else None)
    season = resolve_season(api_code, season)

    standings = get_standings(api_code, season=season)
    table = (standings.get("tables") or {}).get("TOTAL") or []

    # Die bereits gespielten Partien der laufenden Saison gehoeren in die
    # Staerkeberechnung. Frueher stand hier current_matches=None, waehrend
    # die Saisonsimulation dieselben Daten sehr wohl beruecksichtigte:
    # Dasselbe Spiel bekam dadurch je nach Einstiegspunkt unterschiedliche
    # Erwartungswerte, obwohl beide denselben Kenntnisstand hatten.
    #
    # Kein Leak: Es sind ausschliesslich abgeschlossene Partien, also
    # genau das, was zum Simulationszeitpunkt bekannt ist.
    #
    # Kein zusaetzlicher Request: load_full_season_matches liegt im
    # Disk-Cache unter demselben Schluessel, den die Saisonsimulation
    # ohnehin fuellt.
    current_matches = _current_season_matches(api_code, season)

    strength_key = f"league_strengths:{competition_code}:{season}:{len(current_matches)}"
    strength_data = cache.cached_call(
        key=strength_key,
        ttl_seconds=60 * 30,
        loader=lambda: get_league_strengths(
            league_key=competition_code,
            standings_table=table,
            current_matches=current_matches,
            current_season=season,
        ),
    )

    profiles = strength_data["profiles"]
    league_avg = strength_data["league_avg"]

    home_profile, home_resolution = _resolve_profile(profiles, table, home_id, home_team)
    away_profile, away_resolution = _resolve_profile(profiles, table, away_id, away_team)

    # --- GO 3: Belastung und Spielplanhaerte -----------------------------
    #
    # EINMAL hier, vor der Schleife. Der Snapshot wird danach nur noch
    # gelesen - in der Monte-Carlo-Schleife darf nichts nachgeladen
    # werden.
    #
    # Im Voreinstellungsmodus "shadow" veraendert das die Vorhersage
    # NICHT; die Werte erscheinen ausschliesslich in der Diagnose. Erst
    # "active" wirkt, und dafuer fehlt bislang der Beleg aus dem
    # Backtest (siehe src/features/go3_backtest.py).
    if kickoff is None:
        kickoff = datetime.combine(date.today(), dtime(12, 0))

    go3_lookup = {}
    for tid, prof in (profiles or {}).items():
        angriff = (prof.get("attack_home", 1.0) + prof.get("attack_away", 1.0)) / 2
        abwehr = (prof.get("defence_home", 1.0) + prof.get("defence_away", 1.0)) / 2
        if abwehr > 0:
            go3_lookup[tid] = angriff / abwehr

    go3_snapshot = go3_provider.safe_fixture_snapshot(
        home_id, away_id, kickoff, [season - 1, season], api_code,
        strength_lookup=go3_lookup,
        home_profile=home_profile, away_profile=away_profile,
    )
    if go3_snapshot and go3_snapshot["applied"]:
        home_profile = go3_snapshot["adjusted_profiles"]["home"] or home_profile
        away_profile = go3_snapshot["adjusted_profiles"]["away"] or away_profile

    # --- GO 4 und GO 5: Kaderverfuegbarkeit und Transferwirkung -----------
    #
    # Ebenfalls EINMAL hier, vor der Schleife. Beide Voreinstellungen sind
    # "shadow": Sie rechnen vollstaendig und erscheinen in der Diagnose,
    # veraendern die Vorhersage aber nicht. Der Backtest hat fuer keines
    # der beiden eine belastbare Verbesserung gezeigt
    # (src/features/go45_backtest.py).
    #
    # GO 4 und GO 5 sind getrennt schaltbar. Die gemeinsame Obergrenze
    # steht in go4.MAX_COMBINED_GO4_GO5 und wird in
    # go45_provider.combine() angewandt - genau einmal.
    go45_snapshot = _go45_snapshot(
        competition_code, api_code, season, home_id, away_id,
        home_profile, away_profile, kickoff)

    if go45_snapshot and go45_snapshot["applied"]:
        home_profile = go45_snapshot["home"]["adjusted_profile"] or home_profile
        away_profile = go45_snapshot["away"]["adjusted_profile"] or away_profile

    xh, xa = expected_goals(home_profile, away_profile, league_avg)

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
        # Herkunft der Werte, damit im Zweifel nachvollziehbar ist,
        # worauf die Prognose beruht.
        "model": "team_profile_v2",
        "home_data": {
            "resolution": home_resolution,
            "data_source": home_profile.get("data_source", "unknown"),
            "fallback_level": home_profile.get("fallback_level", 4),
            "is_promoted": home_profile.get("is_promoted"),
        },
        "away_data": {
            "resolution": away_resolution,
            "data_source": away_profile.get("data_source", "unknown"),
            "fallback_level": away_profile.get("fallback_level", 4),
            "is_promoted": away_profile.get("is_promoted"),
        },
        "go3": go3_provider.api_metadata(go3_snapshot),
        **go45_provider.api_metadata(go45_snapshot),
    }
