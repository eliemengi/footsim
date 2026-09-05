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

from src.features.point_in_time import matches_known_at

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

#: Die Stufen der Profilkaskade, maschinenlesbar.
SOURCE_DOMESTIC = "domestic_pit"
SOURCE_CL_HISTORY = "cl_history_pit"
SOURCE_NEUTRAL = "neutral"
PROFILE_SOURCES = (SOURCE_DOMESTIC, SOURCE_CL_HISTORY, SOURCE_NEUTRAL)

#: Mindesttiefe eines Profils, damit die Zeile als auswertbar gilt.
#: Dieselbe Groessenordnung wie die Aufwaermgrenze der Ligen (sechs
#: Spieltage) und wie der Shrinkage-Parameter k=5 in team_profile.
MIN_PROFILE_MATCHES = 6

#: Die CL-Saisons, fuer die lokale Historie vorliegt.
DEFAULT_CL_SEASONS = (2023, 2024, 2025)


# ---------------------------------------------------------------------------
# Quellen laden - mit Zwischenspeicher, weil viele Partien denselben Tag teilen
# ---------------------------------------------------------------------------

class _Quellen:
    """
    Haelt die geladenen Saisondateien und die je Stichtag gebauten
    Profile fest.

    Ohne diesen Zwischenspeicher baute der Datensatz fuer jede der rund
    500 CL-Partien die Profile aller fuenf Ligen neu - obwohl sich viele
    Partien denselben Spieltag teilen.
    """

    def __init__(self):
        self._saisons = {}
        self._domestic = {}
        self._cl = {}
        self._cl_payloads = {}

    def domestic_payload(self, api_code, season):
        from src.data.historical_loader import load_season

        key = (api_code, season)
        if key not in self._saisons:
            self._saisons[key] = load_season(api_code, season)
        return self._saisons[key]

    def cl_payload(self, season):
        from src.data.historical_loader import load_cl_season

        if season not in self._cl_payloads:
            self._cl_payloads[season] = load_cl_season(season)
        return self._cl_payloads[season]

    def domestic_profiles(self, season, cutoff, seasons_back=3):
        """
        Top-5-Ligaprofile zum Stichtag, ueber alle fuenf Ligen vereinigt.

        Aufbau wie strength_provider._blend_top5_league_history_by_id -
        je Liga die verfuegbaren Saisons blenden, dann je Team das Profil
        mit der groesseren Datenbasis behalten. Der Unterschied ist der
        Stichtag: Hier wird JEDE Saison ueber cutoff gefiltert.
        """
        key = (season, cutoff)
        if key in self._domestic:
            return self._domestic[key]

        from src.data.historical_loader import (
            AVAILABLE_HISTORICAL_SEASONS, LEAGUE_CODES)
        from src.features.team_profile import blend_profiles, build_season_profiles

        # Neueste zuerst - blend_profiles gewichtet in dieser Reihenfolge.
        kandidaten = [s for s in sorted(AVAILABLE_HISTORICAL_SEASONS, reverse=True)
                      if s <= season][:seasons_back]

        vereinigt = {}
        for api_code in LEAGUE_CODES.values():
            je_saison = []
            for s in kandidaten:
                payload = self.domestic_payload(api_code, s)
                if not payload:
                    continue
                gebaut = build_season_profiles(payload, cutoff=cutoff)
                if gebaut["profiles"]:
                    je_saison.append(gebaut)

            if not je_saison:
                continue

            for team_id, profil in blend_profiles(je_saison).items():
                vorhanden = vereinigt.get(team_id)
                if vorhanden is None or (profil.get("matches_used", 0)
                                         > vorhanden.get("matches_used", 0)):
                    vereinigt[team_id] = profil

        self._domestic[key] = vereinigt
        return vereinigt

    def cl_history(self, season, cutoff):
        """
        Profile und Ligaschnitt aus FRUEHEREN CL-Partien.

        Gepoolt ueber alle CL-Saisons bis einschliesslich der laufenden,
        gefiltert auf das, was zum Stichtag bereits gespielt war. Damit
        stehen fuer eine Mannschaft ohne Top-5-Historie sowohl die
        Vorsaisons als auch die bisherigen Partien der laufenden Saison
        zur Verfuegung - und nichts darueber hinaus.
        """
        key = (season, cutoff)
        if key in self._cl:
            return self._cl[key]

        from src.features.team_profile import build_season_profiles

        gepoolt, teams = [], {}
        for s in sorted(DEFAULT_CL_SEASONS):
            if s > season:
                break
            payload = self.cl_payload(s)
            if not payload:
                continue
            gepoolt.extend(payload.get("matches") or [])
            for tid, info in (payload.get("teams") or {}).items():
                try:
                    teams[int(tid)] = info
                except (TypeError, ValueError):
                    continue

        # Ein einziger Filterpunkt fuer die gesamte CL-Historie.
        bekannt = [m for m in matches_known_at(gepoolt, cutoff)
                   if m.get("home_goals") is not None
                   and m.get("away_goals") is not None]

        gebaut = build_season_profiles({"matches": bekannt, "teams": teams})
        ergebnis = (gebaut["profiles"], gebaut["league_avg"], len(bekannt))
        self._cl[key] = ergebnis
        return ergebnis

    def team_names(self, season):
        payload = self.cl_payload(season) or {}
        namen = {}
        for tid, info in (payload.get("teams") or {}).items():
            try:
                namen[int(tid)] = (info or {}).get("name")
            except (TypeError, ValueError):
                continue
        return namen


# ---------------------------------------------------------------------------
# Profilaufloesung
# ---------------------------------------------------------------------------

def resolve_profile(team_id, team_name, domestic, cl_profiles):
    """
    Die Kaskade fuer EIN Team.

    Rueckgabe: (profil, quelle, tiefe).

    tiefe ist die Zahl der Partien, auf denen das Profil beruht - bei
    neutral_profile null. Sie geht NICHT als Modellmerkmal in den
    Datensatz (siehe feature_groups: Merkmalstiefe ist eine Eigenschaft
    der Datenherkunft, keine des Fussballs), wohl aber als
    Auswertungsgroesse.
    """
    from src.features.team_profile import neutral_profile

    profil = domestic.get(team_id)
    if profil is not None:
        return profil, SOURCE_DOMESTIC, profil.get("matches_used") or 0

    profil = cl_profiles.get(team_id)
    if profil is not None:
        return profil, SOURCE_CL_HISTORY, profil.get("matches_used") or 0

    return neutral_profile(team_id, team_name), SOURCE_NEUTRAL, 0


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

def _leere_belastung(zeile, spaltenname, felder, qualitaet, schedule_qualitaet,
                     diagnose_felder):
    """
    Belastungs- und Gegnerhaerteblock einer CL-Zeile.

    Alle Werte bleiben None. Der Grund steht im Modulkopf: Fuer
    Mannschaften ausserhalb der Top-5-Ligen kennt die Zeitleiste nur
    deren CL-Partien, und daraus berechnete Ruhezeiten waeren
    systematisch zu lang. Der Qualitaetsvermerk macht die Luecke
    auffindbar, statt sie als Zahl zu tarnen.
    """
    for seite in ("home", "away"):
        for feld in felder:
            zeile[spaltenname(seite, feld)] = None
        for feld in qualitaet + schedule_qualitaet:
            zeile[spaltenname(seite, feld)] = "not_computed_for_cl"
        for feld in diagnose_felder:
            zeile[spaltenname(seite, feld)] = None


def build_cl_season(season, quellen=None, min_profile_matches=MIN_PROFILE_MATCHES):
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

    from src.features.go3_backtest import _outcome_index, outcome_probabilities
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

    for datum in sorted(nach_datum):
        # EIN Stichtag je Spieltag - fuer beide Quellen derselbe.
        domestic = quellen.domestic_profiles(season, datum)
        cl_profile, cl_avg, cl_basis = quellen.cl_history(season, datum)

        # Ohne eine einzige frueher gespielte CL-Partie gibt es keinen
        # eigenen Ligaschnitt. Dann greift derselbe Schaetzwert, den
        # auch der produktive CL-Pfad benutzt - ausdruecklich markiert.
        schnitt, schnitt_quelle = cl_avg, "cl_history_pit"
        if not (schnitt or {}).get("matches"):
            from src.features.model_constants import cl_league_avg_fallback
            schnitt, schnitt_quelle = cl_league_avg_fallback(), "fallback_estimate"

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

            _leere_belastung(zeile, ds._spaltenname, ds.WORKLOAD_FELDER
                             + ds.SCHEDULE_FELDER, ds.QUALITAETS_FELDER,
                             ds.SCHEDULE_QUALITAET, ds.DIAGNOSE_FELDER)

            zeilen.append(zeile)
            diagnose["eligible" if grund is None else "ausgeschlossen"] += 1
            diagnose[f"stage_{stage}"] += 1
            diagnose[f"quelle_{heim_quelle}"] += 1
            diagnose[f"quelle_{gast_quelle}"] += 1
            if cl_basis == 0:
                diagnose["ohne_cl_vorgeschichte"] += 1

    return zeilen, dict(diagnose)


def build_cl_dataset(seasons=DEFAULT_CL_SEASONS,
                     min_profile_matches=MIN_PROFILE_MATCHES):
    """
    Alle CL-Zeilen ueber die angegebenen Saisons.

    Ein gemeinsamer _Quellen-Zwischenspeicher ueber alle Saisons: Die
    Ligadateien werden sonst je Saison erneut gelesen.
    """
    quellen = _Quellen()
    zeilen, uebersprungen = [], []
    gesamt = Counter()

    for season in sorted(seasons):
        teil, info = build_cl_season(season, quellen, min_profile_matches)
        if teil is None:
            uebersprungen.append({"competition": "CL", "season": season,
                                  "reason": info})
            continue
        zeilen.extend(teil)
        for schluessel, wert in info.items():
            gesamt[schluessel] += wert

    return zeilen, dict(gesamt), uebersprungen
