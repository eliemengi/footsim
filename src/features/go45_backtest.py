"""
Walk-Forward-Backtest fuer GO 4 und GO 5, mit getrennter Ablation.

DIE ZWEI FRAGEN
---------------
    GO 4   Verbessert Kaderverfuegbarkeit die Vorhersage?
    GO 5   Verbessert Transferwirkung die Vorhersage?

Sie werden GETRENNT beantwortet und erst danach gemeinsam. Ein
kombiniertes Ergebnis, das nicht sagt, welcher Teil es getragen hat,
taugt nicht als Grundlage fuer eine Aktivierung.

WARUM DER VORSAISON-POOL
------------------------
Die Spielerstatistiken im Pool sind SAISONSUMMEN. Wer sie fuer ein Spiel
im November heranzieht, benutzt Tore, die erst im Mai fallen werden -
das ist Leakage, und zwar eine besonders unauffaellige.

Deshalb gilt hier ohne Ausnahme: Fuer Spiele der Saison S werden
Importance und Quality aus dem Pool der Saison S-1 gebildet. Der ist
beim Anpfiff des ersten Spieltags vollstaendig bekannt. Das ist
gleichzeitig die inhaltlich richtige Groesse - GO 5 fragt ja gerade,
was ein Spieler MITBRINGT, nicht was er spaeter erreicht hat.

WARUM GO 4 HISTORISCH NICHT PRUEFBAR IST
----------------------------------------
Verfuegbarkeit braucht Ausfaelle, und Ausfaelle gibt es bei beiden
Anbietern ausschliesslich als Momentaufnahme. Im Archiv
(data/snapshots/) liegen zum Zeitpunkt dieser Umsetzung ausschliesslich
Perzentil-Staende und kein einziger Ausfallstand - vor GO 4 wurde
keiner gesammelt.

Heutige Verletzungen in Spiele von 2024 einzusetzen waere die genaue
Form von Leakage, die dieser Auftrag verbietet. Der Backtest gibt
deshalb fuer GO 4 keine historische Erfolgszahl aus. Er belegt
stattdessen, dass GO 4 ohne Ausfalldaten EXAKT neutral bleibt - und
genau das ist die pruefbare Aussage, die sich hier treffen laesst.

Die Sammlung beginnt mit diesem Auftrag
(squad_availability.capture_availability_snapshot). Ein aussagekraeftiger
GO-4-Backtest ist fruehestens moeglich, wenn genuegend Staende
vorliegen.
"""

from collections import defaultdict

from src.features.go3_backtest import (
    _Accumulator, _outcome_index, outcome_probabilities)


#: Die zu vergleichenden Konfigurationen.
#:
#: Jede nennt, was sie einschaltet. "baseline" ist das heutige Modell.
VARIANTS = {
    "baseline": {},
    # GO 4: ohne Ausfalldaten strukturell neutral. Die Variante laeuft
    # trotzdem mit, weil sie genau das belegen soll.
    "go4_availability": {"go4": True},
    "go4_availability_no_gk": {"go4": True, "skip_goalkeeper": True},
    # GO 5 ohne Decay - Kontrollvariante. Sie zeigt, was passiert, wenn
    # der Schutz gegen Doppelzaehlung fehlt.
    "go5_no_decay": {"go5": True, "no_decay": True},
    "go5_k2": {"go5": True, "k": 2.0},
    "go5_k3": {"go5": True, "k": 3.0},
    "go5_k4": {"go5": True, "k": 4.0},
    "go5_k6": {"go5": True, "k": 6.0},
    "go5_k8": {"go5": True, "k": 8.0},
    "go4_go5": {"go4": True, "go5": True},
}


def _league_features_cached(league_code, season, cache):
    """Importance und Quality aus dem VORSAISON-Pool (siehe Modulkopf)."""
    schluessel = (league_code, season)
    if schluessel in cache:
        return cache[schluessel]

    from src.features.go45_provider import league_player_features

    # Fuer Spiele der Saison S: Pool S-1, Referenz S-2.
    paket = league_player_features(league_code, season - 1, season - 2)
    cache[schluessel] = paket
    return paket


def _apisports_ids_for_league(league_key, season):
    """
    football-data-Team-ID -> API-Sports-Team-ID, ueber den GO-3-Crosswalk.

    Ohne diese Bruecke liesse sich ein Transfer (API-Sports-IDs) keinem
    Team der Simulation (football-data-IDs) zuordnen. Der Crosswalk wird
    hier BENUTZT und nicht nachgebaut.
    """
    from src.data.domestic_cup_loader import DOMESTIC_CUPS, load_cup_season
    from src.features.team_crosswalk import build_crosswalk

    for cfg in DOMESTIC_CUPS.values():
        if cfg["league_key"] != league_key:
            continue
        payload = load_cup_season(
            [k for k, v in DOMESTIC_CUPS.items() if v is cfg][0], season)
        if not payload:
            return {}, set()
        teams = {int(k): (v or {}).get("name")
                 for k, v in (payload.get("teams") or {}).items()}
        crosswalk = build_crosswalk(league_key, season, teams)
        return crosswalk["reverse"], set(teams)
    return {}, set()


def run_backtest(league_key, season, variants=None, min_matchday=6,
                 absences_by_date=None):
    """
    Walk-Forward-Backtest EINER Liga-Saison fuer GO 4 und GO 5.

    absences_by_date: {datum: {team_fd_id: {player_id: ausfall}}} -
        ausschliesslich fuer synthetische Pruefungen. Im Regelfall None,
        weil es keine historischen Ausfallstaende gibt. Es wird NIEMALS
        ein heutiger Stand eingesetzt.

    Rueckgabe: {variant: kennzahlen} plus Segmente und Abdeckung.
    """
    from datetime import datetime

    from src.data.historical_loader import LEAGUE_CODES, load_season
    from src.features.go45_provider import transfer_events_for
    from src.features.go4 import apply_modifier as go4_apply
    from src.features.go4 import compute_modifier as go4_compute
    from src.features.go5 import transfer_impact
    from src.features.match_timeline import build_timeline, team_timeline
    from src.features.squad_availability import team_availability
    from src.features.team_profile import (
        build_season_profiles, expected_goals, neutral_profile)
    from src.features.transfer_events import (
        build_team_index, team_window_transfers_indexed)

    variants = variants or VARIANTS
    api_code = LEAGUE_CODES.get(league_key)
    payload = load_season(api_code, season)
    if not payload:
        return None

    alle = [m for m in (payload.get("matches") or [])
            if m.get("home_goals") is not None and m.get("away_goals") is not None]
    if not alle:
        return None

    feature_cache = {}
    ligamerkmale = _league_features_cached(league_key, season, feature_cache)
    fd_zu_as, bekannte_as = _apisports_ids_for_league(league_key, season)

    ereignisse = transfer_events_for(frozenset(bekannte_as)) if bekannte_as else None
    events = (ereignisse or {}).get("events") or []

    transfer_index = build_team_index(events)

    zeitleiste, _ = build_timeline([season - 1, season])
    team_cache = {}

    def timeline_fuer(tid):
        if tid not in team_cache:
            team_cache[tid] = team_timeline(zeitleiste, tid)
        return team_cache[tid]

    # Kaderzuordnung: Der Pool der Vorsaison fuehrt den HEUTIGEN Verein.
    # Fuer die historische Kaderzugehoerigkeit ist er damit unbrauchbar
    # (siehe player_identity). Es gibt hier also bewusst KEINE
    # Kaderliste - GO 4 bleibt dadurch strukturell neutral, was die
    # Variante go4_availability genau belegen soll.
    kader_bekannt = False

    nach_datum = defaultdict(list)
    for m in alle:
        if m.get("date"):
            nach_datum[m["date"]].append(m)

    zaehler = {name: _Accumulator() for name in variants}
    segmente = defaultdict(lambda: defaultdict(_Accumulator))
    uebersprungen = 0
    ausgeschlossen_ohne_mapping = 0

    for datum in sorted(nach_datum):
        gebaut = build_season_profiles(payload, cutoff=datum)
        profile = gebaut["profiles"]
        schnitt = gebaut["league_avg"]

        gespielt_gesamt = schnitt.get("matches") or 0
        je_spieltag = (len(payload.get("teams") or {}) // 2) or 1
        if gespielt_gesamt < min_matchday * je_spieltag:
            uebersprungen += len(nach_datum[datum])
            continue

        cutoff = datetime.fromisoformat(f"{datum}T12:00:00")

        for match in nach_datum[datum]:
            ergebnis = _outcome_index(match)
            if ergebnis is None:
                continue

            heim_id, gast_id = match.get("home_id"), match.get("away_id")
            heim_profil = profile.get(heim_id) or neutral_profile(heim_id)
            gast_profil = profile.get(gast_id) or neutral_profile(gast_id)

            xh, xa = expected_goals(heim_profil, gast_profil, schnitt)
            basis_p = outcome_probabilities(xh, xa)

            heim_as = fd_zu_as.get(heim_id)
            gast_as = fd_zu_as.get(gast_id)
            if heim_as is None and gast_as is None:
                ausgeschlossen_ohne_mapping += 1

            # Ligaspiele vor dem Stichtag - der Nenner des Decays.
            from src.features.go5 import count_league_matches_before
            heim_n = count_league_matches_before(timeline_fuer(heim_id), cutoff, season)
            gast_n = count_league_matches_before(timeline_fuer(gast_id), cutoff, season)

            # Die Transfermenge haengt NICHT von k ab. Sie wird deshalb
            # einmal je Begegnung bestimmt und von allen k-Varianten
            # geteilt - sonst waere derselbe Fensterlauf zehnmal
            # gerechnet worden.
            transfermengen = {}
            for seite, as_id in (("home", heim_as), ("away", gast_as)):
                if as_id is not None:
                    transfermengen[seite] = team_window_transfers_indexed(
                        transfer_index, as_id, datum, season, window_days=365)
                else:
                    transfermengen[seite] = ([], [])

            for name, konfig in variants.items():
                a_heim = d_heim = a_gast = d_gast = 0.0
                clamp = False

                if konfig.get("go4"):
                    for seite, tid in (("home", heim_id), ("away", gast_id)):
                        ausfaelle = None
                        if absences_by_date:
                            ausfaelle = (absences_by_date.get(datum) or {}).get(tid)
                        verf = team_availability(
                            [], ligamerkmale["importance"], ligamerkmale["quality"],
                            ausfaelle or {}, as_of=datum,
                            absences_known=bool(ausfaelle) or kader_bekannt)
                        mod = go4_compute(verf)
                        if seite == "home":
                            a_heim += mod["attack_modifier"]
                            d_heim += mod["defence_modifier"]
                        else:
                            a_gast += mod["attack_modifier"]
                            d_gast += mod["defence_modifier"]
                        clamp = clamp or mod["clamp_applied"]

                if konfig.get("go5") and events:
                    for seite, as_id, n in (("home", heim_as, heim_n),
                                            ("away", gast_as, gast_n)):
                        if as_id is None:
                            continue
                        zu, ab = transfermengen[seite]
                        wirkung = transfer_impact(
                            zu, ab, ligamerkmale["importance"],
                            ligamerkmale["quality"],
                            season_matches_played=(0 if konfig.get("no_decay") else n),
                            k=konfig.get("k"))
                        if konfig.get("no_decay"):
                            # Kontrollvariante: voller Effekt ueber die
                            # ganze Saison, ohne Schutz gegen
                            # Doppelzaehlung.
                            pass
                        if seite == "home":
                            a_heim += wirkung["attack_modifier"]
                            d_heim += wirkung["defence_modifier"]
                        else:
                            a_gast += wirkung["attack_modifier"]
                            d_gast += wirkung["defence_modifier"]
                        clamp = clamp or wirkung["clamp_applied"]

                if not any((a_heim, d_heim, a_gast, d_gast)):
                    p = basis_p
                else:
                    nxh, nxa = expected_goals(
                        go4_apply(heim_profil, a_heim, d_heim),
                        go4_apply(gast_profil, a_gast, d_gast), schnitt)
                    p = outcome_probabilities(nxh, nxa)

                zaehler[name].add(p, ergebnis, basis_p, clamp)

                if name in ("baseline", "go5_k4", "go4_go5"):
                    fortschritt = ("start" if (heim_n or 0) < 5
                                   else "after5" if (heim_n or 0) < 10
                                   else "after10" if (heim_n or 0) < 20
                                   else "after20")
                    segmente[f"progress:{fortschritt}"][name].add(
                        p, ergebnis, basis_p, clamp)
                    segmente[f"competition:{league_key}"][name].add(
                        p, ergebnis, basis_p, clamp)

    return {
        "league": league_key,
        "season": season,
        "player_pool_season": season - 1,
        "skipped_warmup": uebersprungen,
        "matches_without_team_mapping": ausgeschlossen_ohne_mapping,
        "transfer_events": len(events),
        "squad_membership_known": kader_bekannt,
        "variants": {name: acc.result() for name, acc in zaehler.items()},
        "segments": {
            seg: {name: acc.result() for name, acc in inner.items()}
            for seg, inner in segmente.items()
        },
        "coverage": {
            "importance": ligamerkmale.get("importance_coverage", {}).get("players"),
            "quality_usable": sum(
                v.get("usable", 0) for v in
                (ligamerkmale.get("quality_coverage", {}).get("by_position") or {}).values()),
            "teams_mapped": len(fd_zu_as),
        },
    }
