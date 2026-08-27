"""
Eine Zeile je historischem Ligaspiel - streng Point-in-Time.

WAS HIER ENTSTEHT
-----------------
Der Trainingsdatensatz fuer die erste ML-Messung. Jede Zeile beschreibt
eine Partie mit dem, was VOR ihrem Anpfiff bekannt war: die
Baseline-Lambdas, die Teamprofile beider Seiten, den Ligadurchschnitt
und die rohen Belastungsmerkmale aus GO3.

DIE WICHTIGSTE ENTWURFSENTSCHEIDUNG
-----------------------------------
Dieses Modul rechnet NICHTS selbst aus. Es ruft ausschliesslich:

    build_season_profiles(payload, cutoff=datum)   Profile und Ligaschnitt
    expected_goals(heim, gast, schnitt)            die Lambdas
    outcome_probabilities(xh, xa)                  1X2 aus den Lambdas
    build_timeline / team_timeline                 die Belastungschronologie
    workload_features(zeitleiste, cutoff)          Ruhe und Dichte
    schedule_strength(zeitleiste, cutoff, lookup)  Gegnerhaerte

Das sind dieselben Funktionen, die src/features/go3_backtest.py benutzt,
in derselben Reihenfolge und mit denselben Stichtagen. Eine eigene
Formel - und sei sie noch so naheliegend - wuerde bedeuten, dass das
Modell etwas anderes lernt als der Backtest misst.

GO3 STEHT HIER ALS MERKMAL, NICHT ALS KORREKTUR
-----------------------------------------------
Als fest vorgegebener multiplikativer Modifikator hat GO3 die Baseline
verschlechtert: +0,00042 LogLoss ueber 4.380 Spiele, in 13 von 15
Liga-Saisons schlechter. Hier stehen die Rohwerte - Ruhestunden,
Spieldichte, Gegnerhaerte - als Spalten. Ob und wie sie wirken, soll ein
Modell selbst entscheiden duerfen. Das ist eine andere Frage, und sie
ist offen.

WAS AUSDRUECKLICH FEHLT
-----------------------
GO5 und data/player_pool. Nicht aus fachlichen Gruenden, sondern weil
das Verzeichnis in .gitignore steht: Ein Datensatz daraus liesse sich
von niemandem sonst erzeugen, auch nicht in der CI. Quelle ist
ausschliesslich das getrackte data/historical.

Ebenso fehlen Skalierung, Imputation und kategoriale Kodierung. Sie
gehoeren in eine Pipeline, die je Trainings-Fold neu gefittet wird -
hier angewandt waeren sie Leakage ueber den zeitlichen Split hinweg.
"""

from collections import Counter, defaultdict
from datetime import datetime

#: Fassung des Zeilenschemas. Erhoehen, sobald sich Spalten aendern -
#: sonst laesst sich ein alter Datensatz spaeter nicht mehr einordnen.
SCHEMA_VERSION = 1

DEFAULT_LEAGUES = ["bl1", "pl", "pd", "sa", "fl1"]
DEFAULT_SEASONS = [2023, 2024, 2025]

#: Dieselbe Aufwaermgrenze wie im Backtest. Vor diesem Spieltag sind die
#: Profile fast reine Historie und die Belastungsfenster kaum gefuellt.
DEFAULT_MIN_MATCHDAY = 6

#: Numerische Felder des Point-in-Time-Profils.
#: Nachgemessen an build_season_profiles() - keine erfundenen Namen.
PROFILE_FELDER = (
    "attack_home",
    "attack_away",
    "defence_home",
    "defence_away",
    "points_per_game",
    "goals_for_per_game",
    "goals_against_per_game",
    "win_rate",
    # Der Kaltstartindikator: 0 bedeutet, dass ueber dieses Team zum
    # Stichtag nichts bekannt war - ein Aufsteiger am ersten Spieltag.
    "matches_used",
)

#: Numerische Felder des Point-in-Time-Ligadurchschnitts.
LIGA_FELDER = ("home_goals", "away_goals", "total_goals", "matches")

#: Rohe Belastungsmerkmale aus workload_features().
WORKLOAD_FELDER = (
    "rest_hours",
    "rest_days",
    "short_rest_flag",
    "matches_last_7_days",
    "matches_last_14_days",
    "matches_last_21_days",
    "matches_last_30_days",
    "consecutive_away_matches",
    "congestion_level",
    "number_of_usable_matches",
)

#: Gegnerhaerte aus schedule_strength().
SCHEDULE_FELDER = (
    "recent_opponent_strength",
    "number_of_usable_opponents",
    "opponents_without_strength",
)

#: Qualitaets- und Missingness-Angaben. Sie bleiben als Text stehen und
#: werden NICHT stillschweigend in Zahlen umgedeutet - "partial" ist
#: keine 0.5.
QUALITAETS_FELDER = (
    "data_quality",
    "rest_data_quality",
    "rest_time_precision",
)
SCHEDULE_QUALITAET = ("schedule_strength_quality",)

#: Felder, die zur Diagnose mitlaufen und NIEMALS Modellmerkmal werden.
#: Sie stehen im Datensatz, damit ein Befund nachvollziehbar bleibt.
DIAGNOSE_FELDER = (
    "previous_match_competition",
    "opponent_window_days",
)


def _spaltenname(seite, feld):
    return f"{seite}_{feld}"


def _row_id(league, season, datum, heim_id, gast_id):
    """
    Der stabile Zeilenschluessel.

    Ausdruecklich abgeleitet und nicht aus den Daten uebernommen: Die
    Ligadateien fuehren kein match_id. Die Zusammensetzung ist je Saison
    eindeutig - nachgemessen ueber alle 15 Liga-Saisons.
    """
    return f"{league}:{season}:{datum}:{heim_id}:{gast_id}"


def build_schema():
    """
    Die Spalten des Datensatzes mit ihrer Rolle.

    Die Rolle ist keine Zierde: Sie entscheidet, was spaeter ins Modell
    darf. Identifikatoren und Diagnosefelder duerfen es nie - ein Modell,
    das aus match_id lernt, lernt die Vergangenheit auswendig.
    """
    spalten = []

    def hinzu(name, rolle, typ, herkunft):
        spalten.append({"name": name, "role": rolle, "type": typ,
                        "source": herkunft})

    # row_id steht ZUERST und ist der Sortierschluessel.
    #
    # Warum es ihn braucht: Die Ligadateien fuehren KEIN match_id - ihre
    # Felder sind date, matchday, home_id, away_id und die Tore. Nur die
    # Pokal- und CL-Dateien tragen eines. Ohne eigenen Schluessel waere
    # die Sortierung von der Einlesereihenfolge abhaengig, und zwei
    # Laeufe waeren nicht vergleichbar.
    #
    # Nachgemessen: (liga, saison, heim, gast) ist je Saison eindeutig -
    # 305 Paarungen, 305 verschiedene. Das Datum kommt der Lesbarkeit
    # halber dazu.
    hinzu("row_id", "identifier", "str", "abgeleitet, siehe _row_id()")
    hinzu("match_id", "identifier", "int",
          "data/historical - bei Ligadateien nicht vorhanden (None)")
    for name, typ in (("league", "str"), ("season", "int"), ("date", "str"),
                      ("matchday", "int"), ("home_id", "int"),
                      ("away_id", "int")):
        hinzu(name, "identifier", typ, "data/historical")
    hinzu("evaluation_eligible", "identifier", "bool",
          "Aufwaermlogik wie go3_backtest.run_backtest")

    for name in ("home_goals", "away_goals"):
        hinzu(name, "target", "int", "data/historical")
    hinzu("outcome", "target", "int", "go3_backtest._outcome_index")

    for name in ("baseline_lambda_home", "baseline_lambda_away"):
        hinzu(name, "baseline", "float", "team_profile.expected_goals")
    for name in ("baseline_p_home", "baseline_p_draw", "baseline_p_away"):
        hinzu(name, "baseline", "float",
              "go3_backtest.outcome_probabilities")

    for seite in ("home", "away"):
        for feld in PROFILE_FELDER:
            hinzu(_spaltenname(seite, feld), "feature", "float",
                  "team_profile.build_season_profiles(cutoff=)")

    for feld in LIGA_FELDER:
        hinzu(f"league_avg_{feld}", "feature", "float",
              "team_profile.build_season_profiles(cutoff=)")

    for seite in ("home", "away"):
        for feld in WORKLOAD_FELDER:
            hinzu(_spaltenname(seite, feld), "feature", "mixed",
                  "workload.workload_features")
        for feld in SCHEDULE_FELDER:
            hinzu(_spaltenname(seite, feld), "feature", "float",
                  "workload.schedule_strength")
        for feld in QUALITAETS_FELDER:
            hinzu(_spaltenname(seite, feld), "quality", "str",
                  "workload.workload_features")
        for feld in SCHEDULE_QUALITAET:
            hinzu(_spaltenname(seite, feld), "quality", "str",
                  "workload.schedule_strength")
        for feld in DIAGNOSE_FELDER:
            hinzu(_spaltenname(seite, feld), "diagnostic", "mixed",
                  "workload.*")

    return spalten


#: Die reine Spaltenreihenfolge - zugleich die Reihenfolge in jeder Zeile.
SPALTEN = [eintrag["name"] for eintrag in build_schema()]


def _profil_werte(seite, profil, zeile):
    for feld in PROFILE_FELDER:
        zeile[_spaltenname(seite, feld)] = profil.get(feld)


def _workload_werte(seite, merkmale, haerte, zeile):
    for feld in WORKLOAD_FELDER:
        zeile[_spaltenname(seite, feld)] = merkmale.get(feld)
    for feld in SCHEDULE_FELDER:
        zeile[_spaltenname(seite, feld)] = haerte.get(feld)
    for feld in QUALITAETS_FELDER:
        zeile[_spaltenname(seite, feld)] = merkmale.get(feld)
    for feld in SCHEDULE_QUALITAET:
        zeile[_spaltenname(seite, feld)] = haerte.get(feld)
    for feld in DIAGNOSE_FELDER:
        wert = merkmale.get(feld)
        if wert is None:
            wert = haerte.get(feld)
        zeile[_spaltenname(seite, feld)] = wert


def build_league_season(league_key, season, min_matchday=DEFAULT_MIN_MATCHDAY,
                        seasons_for_timeline=None):
    """
    Alle Zeilen EINER Liga-Saison.

    Der Ablauf spiegelt go3_backtest.run_backtest Schritt fuer Schritt:
    nach Datum gruppieren, je Stichtag die Profile neu bauen, den
    Ligaschnitt aus DEMSELBEN Aufruf nehmen, dann je Partie rechnen.

    Der einzige Unterschied: Der Backtest ueberspringt die Aufwaermphase,
    hier bekommt sie evaluation_eligible=False und bleibt erhalten. So
    laesst sich spaeter beides auswerten, ohne den Datensatz neu zu bauen.

    Rueckgabe: (zeilen, diagnose) oder (None, grund) ohne Saisondaten.
    """
    from src.data.historical_loader import LEAGUE_CODES, load_season
    from src.features.go3_backtest import (
        _outcome_index, _team_strength_scalar, outcome_probabilities)
    from src.features.go3_provider import league_average_strength
    from src.features.match_timeline import build_timeline, team_timeline
    from src.features.team_profile import (
        build_season_profiles, expected_goals, neutral_profile)
    from src.features.workload import schedule_strength, workload_features

    api_code = LEAGUE_CODES.get(league_key)
    payload = load_season(api_code, season)
    if not payload:
        return None, "keine Saisondaten"

    alle = [m for m in (payload.get("matches") or [])
            if m.get("home_goals") is not None
            and m.get("away_goals") is not None]
    if not alle:
        return None, "keine abgeschlossenen Spiele"

    zeitleiste, _ = build_timeline(
        seasons_for_timeline or [season - 1, season])
    team_cache = {}

    def zeitleiste_fuer(team_id):
        if team_id not in team_cache:
            team_cache[team_id] = team_timeline(zeitleiste, team_id)
        return team_cache[team_id]

    nach_datum = defaultdict(list)
    for match in alle:
        if match.get("date"):
            nach_datum[match["date"]].append(match)

    zeilen = []
    diagnose = Counter()

    for datum in sorted(nach_datum):
        # Punkt-in-Zeit: build_season_profiles filtert selbst auf das, was
        # am Stichtag bekannt war. Ein Spiel am Stichtag gilt dort als
        # nicht bekannt - genau das braucht der Datensatz.
        gebaut = build_season_profiles(payload, cutoff=datum)
        profile = gebaut["profiles"]
        schnitt = gebaut["league_avg"]

        # Dieselbe Aufwaermrechnung wie im Backtest, Zeile fuer Zeile.
        gespielt = schnitt.get("matches") or 0
        je_spieltag = (len(payload.get("teams") or {}) // 2) or 1
        auswertbar = gespielt >= min_matchday * je_spieltag

        lookup = {}
        for team_id, profil in profile.items():
            wert = _team_strength_scalar(profil)
            if wert is not None:
                lookup[team_id] = wert
        league_average_strength(lookup)   # gleicher Aufruf wie im Backtest

        cutoff = datetime.fromisoformat(f"{datum}T12:00:00")

        for match in nach_datum[datum]:
            ergebnis = _outcome_index(match)
            if ergebnis is None:
                diagnose["ohne_ergebnis"] += 1
                continue

            heim_id, gast_id = match.get("home_id"), match.get("away_id")
            heim_profil = profile.get(heim_id) or neutral_profile(heim_id)
            gast_profil = profile.get(gast_id) or neutral_profile(gast_id)

            if profile.get(heim_id) is None or profile.get(gast_id) is None:
                diagnose["neutrales_profil"] += 1

            xh, xa = expected_goals(heim_profil, gast_profil, schnitt)
            p = outcome_probabilities(xh, xa)

            zeile = {
                "row_id": _row_id(league_key, season, datum, heim_id, gast_id),
                # Ehrlich None, wo die Quelle nichts liefert - nicht
                # ersatzweise mit row_id gefuellt.
                "match_id": match.get("match_id"),
                "league": league_key,
                "season": season,
                "date": datum,
                "matchday": match.get("matchday"),
                "home_id": heim_id,
                "away_id": gast_id,
                "evaluation_eligible": auswertbar,
                "home_goals": match.get("home_goals"),
                "away_goals": match.get("away_goals"),
                "outcome": ergebnis,
                "baseline_lambda_home": xh,
                "baseline_lambda_away": xa,
                "baseline_p_home": p[0],
                "baseline_p_draw": p[1],
                "baseline_p_away": p[2],
            }

            _profil_werte("home", heim_profil, zeile)
            _profil_werte("away", gast_profil, zeile)
            for feld in LIGA_FELDER:
                zeile[f"league_avg_{feld}"] = schnitt.get(feld)

            for seite, team_id in (("home", heim_id), ("away", gast_id)):
                tl = zeitleiste_fuer(team_id)
                _workload_werte(seite, workload_features(tl, cutoff),
                                schedule_strength(tl, cutoff, lookup), zeile)

            zeilen.append(zeile)
            diagnose["eligible" if auswertbar else "warmup"] += 1

            # Kaltstart: ueber mindestens eine Seite war zum Stichtag
            # nichts bekannt. Das ist der Aufsteiger am ersten Spieltag.
            if not (heim_profil.get("matches_used") or 0) \
                    or not (gast_profil.get("matches_used") or 0):
                diagnose["kaltstart"] += 1

    return zeilen, dict(diagnose)


def crosswalk_coverage(seasons):
    """
    Wie viele Pokalspiele finden ihren Weg in die Belastungszeitleiste?

    Reine Diagnose. build_timeline uebersetzt Pokalspiele ueber
    team_crosswalk auf football-data-IDs und laesst aus, was sich nicht
    sicher zuordnen laesst - lieber eine Luecke als ein falsch
    zugeschriebenes Spiel. Wie gross diese Luecke ist, stand bisher
    nirgends.

    Der Crosswalk wird hier NICHT veraendert.
    """
    import glob
    import json
    import os

    from src.features.match_timeline import build_timeline

    zeitleiste, _ = build_timeline(list(seasons))

    # Ein Eintrag je SPIEL, nicht je Team - nachgemessen: 917 Eintraege
    # fuer 917 Bundesligaspiele. team_timeline() filtert diese gemeinsame
    # Liste spaeter je Mannschaft.
    #
    # Der erste Entwurf hier teilte durch zwei und halbierte damit jede
    # Abdeckungszahl. Gezaehlt wird deshalb ueber match_id.
    je_wettbewerb = defaultdict(set)
    for eintrag in zeitleiste:
        je_wettbewerb[eintrag.get("competition")].add(eintrag.get("match_id"))

    # Nur die Pokalwettbewerbe - Ligen und CL teilen ohnehin den ID-Raum.
    pokale = ("DFB", "FAC", "CDR", "CIT", "CDF")
    abdeckung = []
    for kuerzel in pokale:
        vorhanden = 0
        for pfad in sorted(glob.glob(
                os.path.join("data", "historical", f"{kuerzel}_*.json"))):
            saison = int(os.path.basename(pfad).split("_")[1].split(".")[0])
            if saison not in seasons:
                continue
            with open(pfad, encoding="utf-8") as datei:
                daten = json.load(datei)
            vorhanden += sum(
                1 for m in (daten.get("matches") or [])
                if m.get("home_goals") is not None
                and m.get("away_goals") is not None)

        zugeordnet = len(je_wettbewerb.get(kuerzel, ()))
        abdeckung.append({
            "competition": kuerzel,
            "matches_in_files": vorhanden,
            "matches_covered": zugeordnet,
            "coverage": (round(zugeordnet / vorhanden, 4)
                         if vorhanden else None),
            # ZUR DEUTUNG - und die ist mit Vorsicht zu geniessen.
            #
            # Der Nenner sind ALLE Partien der Datei, einschliesslich der
            # Qualifikationsrunden mit Amateurvereinen. Die tauchen im
            # football-data-ID-Raum nicht auf und koennen deshalb gar
            # nicht zugeordnet werden. Das ERKLAERT eine niedrige Quote
            # plausibel - es BELEGT aber nicht, dass keine relevante
            # Partie fehlt.
            #
            # Der aussagekraeftige Nenner waere "Partien mit mindestens
            # einem Erstligisten". Er laesst sich ohne den Crosswalk
            # selbst nicht bestimmen, und genau den soll diese Zahl ja
            # beurteilen. Solange das offen ist, gilt: Die Quote ist ein
            # Hinweis, kein Freispruch. Eine gezielte Pruefung an
            # einzelnen Erstligavereinen waere der naechste Schritt -
            # sie gehoert nicht in diesen Auftrag.
            "denominator_note": ("alle Partien der Datei inkl. Qualifikation - "
                                 "erklaert eine niedrige Quote, belegt aber "
                                 "keine Vollstaendigkeit fuer Erstligisten"),
        })
    return abdeckung


def missingness(zeilen):
    """Wie viele Zeilen tragen je Spalte keinen Wert?"""
    fehlend = Counter()
    for zeile in zeilen:
        for spalte in SPALTEN:
            if zeile.get(spalte) is None:
                fehlend[spalte] += 1
    return {spalte: fehlend.get(spalte, 0) for spalte in SPALTEN}


def build_dataset(leagues=None, seasons=None,
                  min_matchday=DEFAULT_MIN_MATCHDAY):
    """
    Der vollstaendige Datensatz ueber alle Ligen und Saisons.

    Die Reihenfolge ist fest: Liga, Saison, Datum, match_id. Ohne diese
    Sortierung waere ein Vergleich zweier Laeufe nicht moeglich - und
    Reproduzierbarkeit ist der ganze Zweck dieses Schrittes.

    Rueckgabe: (zeilen, diagnose).
    """
    leagues = list(leagues or DEFAULT_LEAGUES)
    seasons = list(seasons or DEFAULT_SEASONS)

    zeilen = []
    je_liga_saison = []
    uebersprungen = []
    gesamt = Counter()

    for season in seasons:
        for league in leagues:
            teil, info = build_league_season(league, season, min_matchday)
            if teil is None:
                uebersprungen.append({"league": league, "season": season,
                                      "reason": info})
                continue
            zeilen.extend(teil)
            je_liga_saison.append({
                "league": league, "season": season,
                "rows": len(teil),
                "evaluation_eligible": info.get("eligible", 0),
                "warmup": info.get("warmup", 0),
                "cold_start_rows": info.get("kaltstart", 0),
                "neutral_profile_rows": info.get("neutrales_profil", 0),
            })
            for schluessel, wert in info.items():
                gesamt[schluessel] += wert

    # row_id ist eindeutig, also ist die Reihenfolge vollstaendig
    # bestimmt - unabhaengig von der Einlesereihenfolge.
    zeilen.sort(key=lambda z: (z["league"], z["season"], z["date"],
                               z["row_id"]))

    diagnose = {
        "total_rows": len(zeilen),
        "evaluation_eligible_rows": sum(
            1 for z in zeilen if z["evaluation_eligible"]),
        "warmup_rows": sum(1 for z in zeilen if not z["evaluation_eligible"]),
        "cold_start_rows": gesamt.get("kaltstart", 0),
        "neutral_profile_rows": gesamt.get("neutrales_profil", 0),
        "rows_without_outcome": gesamt.get("ohne_ergebnis", 0),
        "per_league_season": je_liga_saison,
        "skipped": uebersprungen,
    }
    return zeilen, diagnose


def baseline_metrics(zeilen, nur_eligible=True):
    """
    Die Baseline-Kennzahlen des Datensatzes.

    Die Probe aufs Exempel: Rechnet man sie ueber die auswertbaren Zeilen,
    muessen wieder die bekannten Werte herauskommen - LogLoss 1,01598,
    Brier 0,60821, RPS 0,20868. Weicht etwas ab, stimmt der Datensatz
    nicht mit dem Backtest ueberein, und alles Weitere waere Messung
    gegen eine Fiktion.

    Bewusst ueber dieselben Funktionen wie der Backtest.
    """
    from src.features.go3_backtest import _brier, _log_loss, _rps

    passend = [z for z in zeilen
               if z["evaluation_eligible"] or not nur_eligible]
    if not passend:
        return None

    summe_ll = summe_brier = summe_rps = 0.0
    for zeile in passend:
        p = (zeile["baseline_p_home"], zeile["baseline_p_draw"],
             zeile["baseline_p_away"])
        ziel = zeile["outcome"]
        summe_ll += _log_loss(p, ziel)
        summe_brier += _brier(p, ziel)
        summe_rps += _rps(p, ziel)

    anzahl = len(passend)
    return {
        "n": anzahl,
        "log_loss": summe_ll / anzahl,
        "brier": summe_brier / anzahl,
        "rps": summe_rps / anzahl,
    }
