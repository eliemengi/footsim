"""
Point-in-Time-Zeilen fuer Champions-League-Partien.

WOZU
----
Der bisherige Trainingsdatensatz kennt ausschliesslich Ligaspiele. Ein
Modell daraus auf CL-Partien anzuwenden, waere eine Uebertragung ohne
Messung - und die Bereitschaftsanalyse hat gezeigt, wie weit die beiden
Bereiche auseinanderliegen. Dieses Modul erzeugt die Datengrundlage, auf
der sich diese Uebertragung spaeter PRUEFEN laesst.

Es trainiert nichts, misst nichts und aktiviert nichts.

DIE PROFILKASKADE - UND WARUM SIE ANDERS IST ALS BEI LIGEN
----------------------------------------------------------
Ein Ligaspiel hat es einfach: Beide Mannschaften spielen in derselben
Liga, also stammt ihr Profil aus derselben Saisondatei. In der Champions
League treffen Mannschaften aus verschiedenen Wettbewerben aufeinander,
und ein Teil von ihnen taucht in den fuenf Top-Ligen ueberhaupt nicht
auf. Nachgemessen an CL 2025/26: 14 von 36 Teilnehmern.

Deshalb eine ausdrueckliche Kaskade, deren Stufe je Team im Datensatz
festgehalten wird:

    domestic_pit      Blend der Top-5-Ligahistorie zum Stichtag
    cl_history_pit    Profil aus frueheren CL-Partien zum Stichtag
    neutral           neutral_profile - dokumentierter letzter Ausweg

Die Stufe steht als Spalte in jeder Zeile. Ohne sie liessen sich vier
nicht vergleichbare Datenquellen spaeter nicht mehr auseinanderhalten,
und jede Auswertung wuerde ueber sie hinwegmitteln.

POINT-IN-TIME OHNE AUSNAHME
---------------------------
Jede Quelle wird ueber denselben Stichtag gefiltert, und zwar mit
derselben Funktion, die auch der Ligapfad benutzt:

    point_in_time.matches_known_at(matches, cutoff)   inclusive=False

Ein Spiel am Stichtag selbst gilt dort als NICHT bekannt. Damit kann
weder die zu prognostizierende Partie in ihr eigenes Profil geraten noch
eine spaetere Partie derselben Saison.

Der Stichtag wird AUCH auf abgeschlossene Vorsaisons angewandt, obwohl
diese nachweislich vor Beginn der CL-Saison enden. Das kostet etwas
Rechenzeit und spart eine Beweisfuehrung: So haengt die Leckagefreiheit
an einer einzigen Filterstelle statt an einer Ueberlegung ueber
Saisonkalender.

WAS BEWUSST FEHLT
-----------------
Belastungs- und Gegnerhaertemerkmale. Die Zeitleiste kennt fuer
Mannschaften ausserhalb der Top-5-Ligen nur deren CL-Partien; die
Ruhezeiten waeren dadurch systematisch zu lang und die Spieldichte zu
niedrig. Ein plausibel aussehender, aber falscher Wert ist schlechter
als eine ehrliche Luecke - die Spalten bleiben None und tragen einen
Qualitaetsvermerk.

Ebenso fehlt eine Ligastaerke-Korrektur ueber UEFA-Koeffizienten. Sie
ist ein eigener Block und wuerde hier unbelegt einfliessen.
"""

from collections import Counter

from src.features.pit_profiles import (
    DEFAULT_CL_SEASONS,
    PROFILE_SOURCES,
    SOURCE_CL_HISTORY,
    SOURCE_DOMESTIC,
    SOURCE_NEUTRAL,
    PitProfileRepository,
    resolve_profile,
)

#: Die regulaere Phase. Sie ist der fachlich vergleichbare Teil: 2023
#: als Gruppenphase des alten 32er-Formats, ab 2024 als Ligaphase des
#: 36er-Formats. Beide sind Rundenspiele ohne K.-o.-Logik.
#:
#: Nachgemessen: GROUP_STAGE 96 (2023), LEAGUE_STAGE je 144 (2024, 2025).
REGULAR_STAGES = ("GROUP_STAGE", "LEAGUE_STAGE")

#: K.-o.-Partien werden mitgebaut, aber nicht als auswertbar markiert.
#: Verlaengerung, Elfmeterschiessen und die Abhaengigkeit vom Hinspiel
#: sind im Modell nicht abgebildet. Die Zeilen bleiben trotzdem im
#: Datensatz, damit eine spaetere K.-o.-Analyse nicht bei null anfaengt.
KNOCKOUT_NOTE = "K.-o.-Runde - Zwei-Leg- und Verlaengerungslogik nicht modelliert"

#: Die Stufen der Profilkaskade und die verfuegbaren CL-Saisons stehen
#: seit V2-C1 in src/features/pit_profiles.py und werden oben importiert.
#: Sie bleiben hier unter denselben Namen erreichbar, weil Tests und
#: Auswertung sie von hier beziehen - aber es gibt nur noch EINE
#: Definition.

#: Mindesttiefe eines Profils, damit die Zeile als auswertbar gilt.
#: Dieselbe Groessenordnung wie die Aufwaermgrenze der Ligen (sechs
#: Spieltage) und wie der Shrinkage-Parameter k=5 in team_profile.
MIN_PROFILE_MATCHES = 6


# ---------------------------------------------------------------------------
# Quellen laden
# ---------------------------------------------------------------------------
#
# Seit V2-C1 steht die Profillogik in src/features/pit_profiles.py und
# wird von Datensatz UND Laufzeit gemeinsam benutzt. Frueher lag hier
# eine eigene Klasse _Quellen, deren Docstring selbst festhielt:
# "Aufbau wie strength_provider._blend_top5_league_history_by_id ... Der
# Unterschied ist der Stichtag." Genau diese zweite Fassung ist
# entfallen - mit ihr die Moeglichkeit, dass Training und Betrieb
# auseinanderlaufen.
#
# _Quellen bleibt als Name bestehen, weil dieser Modulcode und seine
# Tests ihn benutzen. Er ist jetzt nichts weiter als die Fabrik.

_Quellen = PitProfileRepository


# ---------------------------------------------------------------------------
# Auswertbarkeit
# ---------------------------------------------------------------------------

def _ausschlussgrund(stage, quellen, tiefen, min_matches):
    """
    Warum eine Zeile nicht ausgewertet wird - oder None.

    Die Gruende werden in fester Reihenfolge geprueft, damit dieselbe
    Zeile immer denselben Grund traegt. Ohne feste Reihenfolge waere die
    Angabe von der Auswertungsreihenfolge abhaengig und damit nicht
    reproduzierbar.
    """
    if stage not in REGULAR_STAGES:
        return KNOCKOUT_NOTE
    if SOURCE_NEUTRAL in quellen:
        return "mindestens eine Seite ohne jede Historie (neutral_profile)"
    if min(tiefen) < min_matches:
        return (f"Profiltiefe unter {min_matches} Partien "
                f"(duennste Seite: {min(tiefen)})")
    return None


# ---------------------------------------------------------------------------
# Zeilenbau
# ---------------------------------------------------------------------------

def _leere_belastung_seite(zeile, seite, grund, ds):
    # Seit V2-C3 fuellt ds.workload_values_for_side die Luecke selbst.
    # Diese Funktion bleibt als duenne Weiterleitung bestehen, weil
    # Tests sie benennen - sie ist keine zweite Fassung mehr.
    """
    Der Belastungsblock EINER Seite bleibt leer - mit Begruendung.

    Bis V2-C2 galt das pauschal fuer jede CL-Zeile und beide Seiten. Der
    Grund war richtig, aber zu grob: Fuer Mannschaften ausserhalb der
    Top-5-Ligen kennt die Zeitleiste nur deren CL-Partien, und daraus
    gerechnete Ruhezeiten waeren systematisch zu lang. Fuer die rund
    zwei Drittel der Seiten MIT Ligahistorie stimmte das aber nie - dort
    liegt die Belastung sauber vor.

    Der Vermerk nennt jetzt die Ursache (siehe
    match_timeline.base_load_coverage), statt alles unter einem
    einzigen "not_computed_for_cl" zu verbergen.
    """
    for feld in (ds.WORKLOAD_FELDER + ds.WORKLOAD_EXTRA_FELDER
                 + ds.SCHEDULE_FELDER):
        zeile[ds._spaltenname(seite, feld)] = None
    for feld in ds.QUALITAETS_FELDER + ds.SCHEDULE_QUALITAET:
        zeile[ds._spaltenname(seite, feld)] = grund
    for feld in ds.DIAGNOSE_FELDER:
        zeile[ds._spaltenname(seite, feld)] = None


def _belastung_fuer_seite(zeile, seite, team_id, cutoff, eintraege,
                          staerke_lookup, ds):
    """
    Belastung und Gegnerhaerte einer Seite - oder eine begruendete Luecke.

    Seit V2-C3 laeuft die Rechnung ueber ds.workload_values_for_side -
    dieselbe Funktion, die auch der Ligapfad und die Laufzeit benutzen.
    Vorher stand hier eine zweite Fassung derselben Zuordnung; sie
    rief zwar dieselben Rechenfunktionen, war aber eigener Code und
    haette jederzeit auseinanderlaufen koennen, ohne dass es an einer
    Zahl auffaellt.
    """
    werte, grund = ds.workload_values_for_side(
        seite, team_id, cutoff, eintraege, staerke_lookup)
    zeile.update(werte)
    return grund


def build_cl_season(season, quellen=None, min_profile_matches=MIN_PROFILE_MATCHES,
                    include_uefa=None):
    """
    Alle Zeilen EINER CL-Saison.

    Der Ablauf spiegelt dataset.build_league_season: nach Datum
    gruppieren, je Stichtag die Profile neu bauen, dann je Partie
    rechnen. Die Lambdas entstehen ueber dieselbe Funktion
    (team_profile.expected_goals) und die Wahrscheinlichkeiten ueber
    dieselbe (go3_backtest.outcome_probabilities) wie im Ligapfad - eine
    zweite Rechenart waere die sicherste Quelle fuer Abweichungen, die
    niemand findet.

    Rueckgabe: (zeilen, diagnose) oder (None, grund).
    """
    from collections import defaultdict

    from src.features.go3_backtest import (
        _outcome_index, _team_strength_scalar, outcome_probabilities)
    from src.features.go3_provider import league_average_strength
    from src.features.team_profile import expected_goals
    from src.ml import dataset as ds

    quellen = quellen or _Quellen()
    payload = quellen.cl_payload(season)
    if not payload:
        return None, "keine CL-Saisondaten"

    alle = [m for m in (payload.get("matches") or [])
            if m.get("home_goals") is not None
            and m.get("away_goals") is not None and m.get("date")]
    if not alle:
        return None, "keine abgeschlossenen CL-Spiele"

    namen = quellen.team_names(season)
    nach_datum = defaultdict(list)
    for match in alle:
        nach_datum[match["date"]].append(match)

    zeilen = []
    diagnose = Counter()

    # Die wettbewerbsuebergreifende Zeitleiste EINMAL je Saison (V2-C2).
    # Vorsaison mit dabei, damit die ersten Spieltage nicht kuenstlich
    # ohne Vorgeschichte dastehen - dieselbe Fensterwahl wie im
    # Ligapfad (dataset.build_league_season).
    from src.features.match_timeline import build_timeline

    eintraege, _ = build_timeline([season - 1, season])

    # V2-C4: dieselben beiden Hilfsobjekte wie im Ligapfad. Sie leben
    # genau so lange wie dieser Saisonbau; ihre Zwischenspeicher tragen
    # den Stichtag im Schluessel.
    from src.features.pit_profiles import PitStrengthAtDate
    from src.features.uefa_strength import NoUefaLookup, UefaStrengthLookup

    staerke_zum_zeitpunkt = PitStrengthAtDate(repository=quellen,
                                              season=season)
    # Standard AUS - data/big_games/ ist gitignoriert, und ein Bestand,
    # der von dort liest, ist aus einem frischen Checkout nicht
    # nachbaubar. Siehe dataset.INCLUDE_UEFA_BY_DEFAULT.
    if include_uefa is None:
        include_uefa = ds.INCLUDE_UEFA_BY_DEFAULT
    uefa_lookup = UefaStrengthLookup() if include_uefa else NoUefaLookup()

    for datum in sorted(nach_datum):
        # EIN Stichtag je Spieltag - fuer beide Quellen derselbe.
        domestic = quellen.domestic_profiles(season, datum)
        cl_profile, cl_avg, cl_bekannt = quellen.cl_history(season, datum)
        cl_basis = len(cl_bekannt)

        # Ohne eine einzige frueher gespielte CL-Partie gibt es keinen
        # eigenen Ligaschnitt. Dann greift derselbe Schaetzwert, den
        # auch der produktive CL-Pfad benutzt - ausdruecklich markiert.
        schnitt, schnitt_quelle = cl_avg, "cl_history_pit"
        if not (schnitt or {}).get("matches"):
            from src.features.model_constants import cl_league_avg_fallback
            schnitt, schnitt_quelle = cl_league_avg_fallback(), "fallback_estimate"

        # Stichtag und Gegnerhaerte-Lookup - beides wie im Ligapfad.
        # Mittag, weil die CL-Historie keine Anstosszeiten fuehrt; die
        # Regel steht in match_timeline.FALLBACK_KICKOFF_HOUR.
        from datetime import datetime as _dt

        cutoff = _dt.fromisoformat(f"{datum}T12:00:00")

        staerke_lookup = {}
        for team_id, profil in {**cl_profile, **domestic}.items():
            wert = _team_strength_scalar(profil)
            if wert is not None:
                staerke_lookup[team_id] = wert
        league_average_strength(staerke_lookup)

        for match in nach_datum[datum]:
            ergebnis = _outcome_index(match)
            if ergebnis is None:
                diagnose["ohne_ergebnis"] += 1
                continue

            heim_id, gast_id = match.get("home_id"), match.get("away_id")
            heim_profil, heim_quelle, heim_tiefe = resolve_profile(
                heim_id, namen.get(heim_id), domestic, cl_profile)
            gast_profil, gast_quelle, gast_tiefe = resolve_profile(
                gast_id, namen.get(gast_id), domestic, cl_profile)

            stage = match.get("stage")
            grund = _ausschlussgrund(
                stage, (heim_quelle, gast_quelle),
                (heim_tiefe, gast_tiefe), min_profile_matches)

            xh, xa = expected_goals(heim_profil, gast_profil, schnitt)
            p = outcome_probabilities(xh, xa)

            zeile = {
                "row_id": ds._row_id("cl", season, datum, heim_id, gast_id),
                "match_id": match.get("match_id"),
                "league": "cl",
                "competition": "CL",
                "stage": stage,
                "season": season,
                "date": datum,
                "matchday": match.get("matchday"),
                "home_id": heim_id,
                "away_id": gast_id,
                "evaluation_eligible": grund is None,
                "exclusion_reason": grund,
                "home_profile_source": heim_quelle,
                "away_profile_source": gast_quelle,
                "home_profile_matches": heim_tiefe,
                "away_profile_matches": gast_tiefe,
                "league_avg_source": schnitt_quelle,
                "home_goals": match.get("home_goals"),
                "away_goals": match.get("away_goals"),
                "outcome": ergebnis,
                "baseline_lambda_home": xh,
                "baseline_lambda_away": xa,
                "baseline_p_home": p[0],
                "baseline_p_draw": p[1],
                "baseline_p_away": p[2],
            }

            ds._profil_werte("home", heim_profil, zeile)
            ds._profil_werte("away", gast_profil, zeile)
            for feld in ds.LIGA_FELDER:
                zeile[f"league_avg_{feld}"] = schnitt.get(feld)

            # Belastung je Seite - gerechnet, wo der Grundtakt der
            # Mannschaft bekannt ist, sonst mit begruendeter Luecke.
            for seite, team_id in (("home", heim_id), ("away", gast_id)):
                grund = _belastung_fuer_seite(
                    zeile, seite, team_id, cutoff, eintraege,
                    staerke_lookup, ds)
                diagnose[f"belastung_{grund}"] += 1

                # Form und UEFA-Staerke (V2-C4) - ueber dieselbe
                # Funktion wie der Ligapfad und die Laufzeit.
                zeile.update(ds.form_values_for_side(
                    seite, team_id, season, cutoff, eintraege,
                    uefa_lookup, strength_at=staerke_zum_zeitpunkt))
                diagnose["uefa_" + (zeile[ds._spaltenname(seite, "uefa_source")]
                                    or "unknown")] += 1

            # Erst NACH beiden Seiten und ueber dieselbe Funktion wie im
            # Ligapfad (V2-C3). Eine eigene Subtraktion hier waere die
            # unauffaelligste Art, ein Vorzeichen zu verdrehen.
            zeile.update(ds.workload_difference_values(zeile))
            zeile.update(ds.form_difference_values(zeile))

            zeilen.append(zeile)
            diagnose["eligible" if grund is None else "ausgeschlossen"] += 1
            diagnose[f"stage_{stage}"] += 1
            diagnose[f"quelle_{heim_quelle}"] += 1
            diagnose[f"quelle_{gast_quelle}"] += 1
            if cl_basis == 0:
                diagnose["ohne_cl_vorgeschichte"] += 1

    return zeilen, dict(diagnose)


def build_cl_dataset(seasons=DEFAULT_CL_SEASONS,
                     min_profile_matches=MIN_PROFILE_MATCHES,
                     include_uefa=None):
    """
    Alle CL-Zeilen ueber die angegebenen Saisons.

    Ein gemeinsamer _Quellen-Zwischenspeicher ueber alle Saisons: Die
    Ligadateien werden sonst je Saison erneut gelesen.
    """
    quellen = _Quellen()
    zeilen, uebersprungen = [], []
    gesamt = Counter()

    for season in sorted(seasons):
        teil, info = build_cl_season(season, quellen, min_profile_matches,
                                     include_uefa=include_uefa)
        if teil is None:
            uebersprungen.append({"competition": "CL", "season": season,
                                  "reason": info})
            continue
        zeilen.extend(teil)
        for schluessel, wert in info.items():
            gesamt[schluessel] += wert

    return zeilen, dict(gesamt), uebersprungen


# ---------------------------------------------------------------------------
# Abdeckungsbericht (V2-C2)
# ---------------------------------------------------------------------------

def workload_coverage_report(zeilen):
    """
    Wie vollstaendig ist die Belastungsangabe der CL-Zeilen?

    Reproduzierbar aus fertigen Zeilen gebaut - keine zweite Rechnung,
    kein zweiter Datenzugriff. Was hier steht, steht so auch im
    Datensatz.

    Die Quote ist bewusst nach SEITEN gezaehlt, nicht nach Zeilen: Eine
    Partie kann eine abgedeckte und eine nicht abgedeckte Mannschaft
    haben, und eine Zeilenquote wuerde das entweder schoenen oder
    unnoetig abwerten.

    Rueckgabe: dict mit Gesamtquote, Quote je Saison, Quote je Seite,
    Luecken nach Ursache und den auffaelligsten Mannschaften.
    """
    from collections import Counter, defaultdict

    gesamt = Counter()
    je_saison = defaultdict(Counter)
    je_seite = defaultdict(Counter)
    gruende = Counter()
    teams_ohne = Counter()
    wettbewerbe = Counter()
    ruhetage = []

    for zeile in zeilen:
        saison = zeile.get("season")
        for seite in ("home", "away"):
            gesamt["sides"] += 1
            je_saison[saison]["sides"] += 1
            je_seite[seite]["sides"] += 1

            wert = zeile.get(f"{seite}_rest_days")
            if wert is not None:
                gesamt["with_rest_days"] += 1
                je_saison[saison]["with_rest_days"] += 1
                je_seite[seite]["with_rest_days"] += 1
                ruhetage.append(wert)
                wettbewerbe[zeile.get(f"{seite}_previous_match_competition")] += 1
            else:
                grund = zeile.get(f"{seite}_data_quality") or "unknown"
                gruende[grund] += 1
                teams_ohne[zeile.get(f"{seite}_id")] += 1

    def _quote(zaehler):
        seiten = zaehler.get("sides") or 0
        return round(100.0 * zaehler.get("with_rest_days", 0) / seiten, 2) \
            if seiten else 0.0

    ruhetage.sort()
    mitte = (ruhetage[len(ruhetage) // 2] if ruhetage else None)

    return {
        "cl_rows": len(zeilen),
        "sides_total": gesamt["sides"],
        "sides_with_rest_days": gesamt["with_rest_days"],
        "sides_without_rest_days": gesamt["sides"] - gesamt["with_rest_days"],
        "coverage_pct": _quote(gesamt),
        "coverage_by_season": {s: {"sides": z["sides"],
                                   "with_rest_days": z["with_rest_days"],
                                   "coverage_pct": _quote(z)}
                               for s, z in sorted(je_saison.items())},
        "coverage_by_side": {s: {"sides": z["sides"],
                                 "with_rest_days": z["with_rest_days"],
                                 "coverage_pct": _quote(z)}
                             for s, z in sorted(je_seite.items())},
        "gaps_by_cause": dict(gruende.most_common()),
        "most_affected_teams": dict(teams_ohne.most_common(10)),
        "previous_match_competition": dict(wettbewerbe.most_common()),
        "rest_days_median": mitte,
        "rest_days_implausible_over_10": sum(1 for w in ruhetage if w > 10),
        "note": "Nach Seiten gezaehlt. Eine Luecke ist eine ehrliche "
                "Luecke: Fehlt der nationale Grundtakt einer Mannschaft, "
                "bleibt der Wert None statt eine plausibel aussehende, "
                "systematisch zu lange Ruhezeit zu tragen.",
    }
