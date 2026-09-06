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

# Auf Modulebene, weil daraus SPALTENNAMEN entstehen. Die Feldlisten
# muessen dieselbe Quelle haben wie die Rechnung, sonst traegt der
# Datensatz Spalten, die niemand mehr fuellt. Kein Zirkel: form und
# uefa_strength kennen src.ml nicht.
from src.features.form import (FORM_METRICS, SCOPE_NAMES,
                               FORM_DEPTH_SUFFIX)
from src.features.uefa_strength import (UEFA_FELDER as _UEFA_FELDER,
                                        UEFA_QUALITAET as _UEFA_QUALITAET)

#: Liest der Datensatzbau die privaten UEFA-Dateien?
#:
#: NEIN, ausser der Aufrufer verlangt es ausdruecklich. data/big_games/
#: steht in .gitignore; ein Bestand, der von dort liest, ist aus einem
#: frischen Checkout nicht nachbaubar. Siehe uefa_strength.NoUefaLookup.
INCLUDE_UEFA_BY_DEFAULT = False

#: Fassung des Zeilenschemas. Erhoehen, sobald sich Spalten aendern -
#: sonst laesst sich ein alter Datensatz spaeter nicht mehr einordnen.
#:
#: 1 - nur Ligazeilen, 77 Spalten.
#: 2 - Champions-League-Zeilen kamen hinzu. Sieben neue Spalten, die
#:     JEDE Zeile traegt: competition, stage, exclusion_reason, je Seite
#:     profile_source und profile_matches, sowie league_avg_source.
#:     Die Zahlen der Ligazeilen sind unveraendert - die neuen Spalten
#:     beschreiben nur, woher eine Zeile stammt. Ein Test haelt die
#:     Bitgleichheit der alten Spalten fest.
SCHEMA_VERSION = 2

#: Herkunftsangaben. Sie sind KEINE Modellmerkmale: Sie beschreiben die
#: Datenquelle, nicht das Spiel. Genau diese Verwechslung hat bei
#: matches_used den Verteilungsbruch erzeugt, den feature_groups jetzt
#: ueber eine eigene Gruppe sichtbar macht.
HERKUNFT_FELDER = (
    "competition",
    "stage",
    "exclusion_reason",
    "league_avg_source",
)

#: Herkunft je Seite.
SEITEN_HERKUNFT = (
    ("profile_source", "str"),
    ("profile_matches", "int"),
)

#: Wie eine Ligazeile ihre Herkunftsfelder fuellt. Ausdrueckliche
#: Konstanten statt Literale im Zeilenbau - so steht an einer Stelle,
#: was "aus der eigenen Saison, Stichtag" bedeutet.
LEAGUE_PROFILE_SOURCE = "season_pit"
LEAGUE_AVG_SOURCE = "season_pit"

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

#: Aufteilung von PROFILE_FELDER nach dem, WAS sie beschreiben.
#:
#: Die Bewertungsfelder beschreiben die Mannschaft. matches_used
#: beschreibt dagegen, wie tief die Datenbasis ist - eine Eigenschaft
#: der Quelle, nicht des Fussballs. Genau daran ist die CL-Uebertragung
#: gescheitert: Im Ligatraining lief der Wert von 5 bis 37, der
#: geblendete CL-Stand liefert 33 bis 114, also 95 % ausserhalb.
#:
#: Die Trennung steht hier und nicht in feature_groups, damit sie
#: dieselbe Quelle hat wie die Spaltennamen selbst.
PROFILE_DEPTH_FELDER = ("matches_used",)
PROFILE_RATING_FELDER = tuple(f for f in PROFILE_FELDER
                              if f not in PROFILE_DEPTH_FELDER)

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

#: Verlaengerungsbelastung (V2-C3) - bewusst eine EIGENE Feldliste.
#:
#: WARUM NICHT EINFACH IN WORKLOAD_FELDER
#: Zwei Gruende, und beide zaehlen.
#:
#: Fachlich: Diese beiden Felder sind die einzigen Belastungsgroessen
#: mit einer wettbewerbsabhaengigen Datenlage. Fuer die K.-o.-Runden der
#: Champions League fuehrt die Quelle keinen Verlaengerungsstatus; dort
#: bleibt der Wert ehrlich unbekannt. Die Zaehlfenster haben dieses
#: Problem nicht - sie haengen nur am Kalendertag.
#:
#: Messtechnisch: WORKLOAD_FELDER bestimmt die Ablationsvariante
#: workload_only, deren Ergebnis (24 Merkmale) bereits berichtet ist.
#: Haette V2-C3 die Felder dort eingefuegt, traege dieselbe Variante
#: unter demselben Namen ploetzlich eine andere Merkmalsmenge - und
#: zwei Artefakte waeren nicht mehr vergleichbar, ohne dass es
#: auffiele.
WORKLOAD_EXTRA_FELDER = (
    "extra_time_matches_last_30_days",
    "extra_time_minutes_last_30_days",
)

#: Belastungsdifferenzen Heim minus Auswaerts (V2-C3).
#:
#: WARUM ES SIE UEBERHAUPT GIBT
#: Das Modell rechnet je Seite ein eigenes Lambda und sieht dabei beide
#: Seiten. Eine Differenz ist deshalb rechnerisch keine neue
#: Information - wohl aber eine andere Darstellung derselben: Sie ist
#: bei Vertauschung der Mannschaften exakt vorzeichensymmetrisch,
#: waehrend zwei Rohwerte es nur gemeinsam sind. Ob das dem Modell hilft
#: oder nur Kollinearitaet hinzufuegt, ist eine Messfrage - und genau
#: deshalb bilden diese Spalten eine eigene, gezielt weglassbare Gruppe.
#:
#: Fehlt EINE Seite, ist die Differenz unbekannt und bleibt None. Eine
#: Null waere hier der schlimmste Fall: Sie hiesse "beide gleich
#: belastet" und waere von einer echten Null nicht zu unterscheiden.
WORKLOAD_DIFF_FELDER = (
    "rest_hours",
    "matches_last_7_days",
    "matches_last_14_days",
    "matches_last_21_days",
    "matches_last_30_days",
)

#: Formmerkmale aus form.form_features() (V2-C4).
#:
#: Abgeleitet aus form.FORM_SCOPES und form.FORM_METRICS - NICHT
#: abgetippt. Eine zweite Namensliste waere die sicherste Art, bei der
#: naechsten Aenderung unbemerkt auseinanderzulaufen: Der Datensatz
#: traege dann Spalten, die die Formrechnung gar nicht mehr fuellt.
FORM_FELDER = tuple(f"{_scope}_{_metrik}"
                    for _scope in SCOPE_NAMES
                    for _metrik in FORM_METRICS)

#: Wie tief die jeweilige Formbetrachtung ist.
#:
#: KEIN Modellmerkmal, sondern Qualitaetsangabe. Dieselbe Lehre wie bei
#: profile_depth in V2-C2: Die Zahl beschreibt die QUELLE, nicht die
#: Mannschaft, und sie hat in der Champions League einen anderen
#: Wertebereich als im Ligatraining. Genau daran ist damals die
#: Uebertragung gescheitert.
FORM_DEPTH_FELDER = tuple(f"{_scope}_{FORM_DEPTH_SUFFIX}"
                          for _scope in SCOPE_NAMES) \
    + ("form_matches_available",)

#: Gegnerstaerke der juengsten Partien (V2-C4).
FORM_OPPONENT_FELDER = ("opponent_strength_5", "adjusted_points_rate_5")

#: Diagnose zur Gegnerstaerke - niemals Modellmerkmal.
FORM_OPPONENT_DIAGNOSE = ("opponent_strength_matches",
                          "opponents_without_strength_5")

#: Historische UEFA-Staerke (V2-C4).
UEFA_FELDER = _UEFA_FELDER
UEFA_QUALITAET = _UEFA_QUALITAET

#: Formdifferenzen Heim minus Auswaerts (V2-C4).
#:
#: Bewusst NUR drei und nicht je Betrachtung eine: Differenzen sind
#: exakte Linearkombinationen der Rohspalten - V2-C3 hat das fuer die
#: Belastung gemessen (19 von 27 Spalten exakt kollinear). Drei
#: reichen, um die Frage "hilft die symmetrische Darstellung" zu
#: stellen; dreissig wuerden nur die Kollinearitaet vergroessern.
FORM_DIFF_FELDER = (
    "all_5_points_rate",
    "all_5_goal_diff_per_match",
    "uefa_club_coefficient",
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
    "extra_time_data_quality",
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


def _formdiffspaltenname(feld):
    """
    Der Spaltenname einer Formdifferenz.

    Eigenes Praefix aus demselben Grund wie bei den
    Belastungsdifferenzen: Eine Differenzspalte gehoert keiner Seite,
    und ein Name, der eine vortaeuscht, wuerde jede seitenweise
    Auswertung stillschweigend falsch gruppieren.
    """
    return f"form_diff_{feld}"


def _diffspaltenname(feld):
    """
    Der Spaltenname einer Belastungsdifferenz.

    Ausdruecklich mit eigenem Praefix statt "home_..."/"away_...": Eine
    Differenzspalte gehoert keiner Seite, und ein Name, der eine
    vortaeuscht, wuerde jede seitenweise Auswertung stillschweigend
    falsch gruppieren.
    """
    return f"workload_diff_{feld}"


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

    # Herkunft - Rolle "provenance", damit sie NIE Modellmerkmal wird.
    # Ein Modell, das aus competition oder profile_source lernt, lernt
    # die Datenbeschaffung auswendig, nicht den Fussball.
    hinzu("competition", "provenance", "str",
          "api_code der Quelldatei (BL1..FL1, CL)")
    hinzu("stage", "provenance", "str",
          "data/historical - nur Pokal-/CL-Dateien fuehren eine Stage")
    hinzu("exclusion_reason", "provenance", "str",
          "abgeleitet - warum evaluation_eligible False ist")
    hinzu("league_avg_source", "provenance", "str",
          "welcher Ligaschnitt in die Lambdas ging")
    for seite in ("home", "away"):
        hinzu(_spaltenname(seite, "profile_source"), "provenance", "str",
              "Stufe der Profilkaskade - siehe cl_dataset.PROFILE_SOURCES")
        hinzu(_spaltenname(seite, "profile_matches"), "provenance", "int",
              "Zahl der Partien, auf denen das Profil beruht")

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

    for feld in WORKLOAD_DIFF_FELDER:
        hinzu(_diffspaltenname(feld), "feature", "float",
              "dataset.workload_difference_values")

    for feld in FORM_DIFF_FELDER:
        hinzu(_formdiffspaltenname(feld), "feature", "float",
              "dataset.form_difference_values")

    for seite in ("home", "away"):
        for feld in WORKLOAD_FELDER:
            hinzu(_spaltenname(seite, feld), "feature", "mixed",
                  "workload.workload_features")
        for feld in WORKLOAD_EXTRA_FELDER:
            hinzu(_spaltenname(seite, feld), "feature", "float",
                  "workload.workload_features")
        for feld in SCHEDULE_FELDER:
            hinzu(_spaltenname(seite, feld), "feature", "float",
                  "workload.schedule_strength")
        for feld in FORM_FELDER:
            hinzu(_spaltenname(seite, feld), "feature", "float",
                  "form.form_features")
        for feld in FORM_OPPONENT_FELDER:
            hinzu(_spaltenname(seite, feld), "feature", "float",
                  "form.opponent_values")
        for feld in UEFA_FELDER:
            hinzu(_spaltenname(seite, feld), "feature", "float",
                  "uefa_strength.uefa_values")
        for feld in FORM_DEPTH_FELDER:
            hinzu(_spaltenname(seite, feld), "quality", "int",
                  "form.form_features")
        for feld in UEFA_QUALITAET:
            hinzu(_spaltenname(seite, feld), "quality", "str",
                  "uefa_strength.uefa_values")
        for feld in FORM_OPPONENT_DIAGNOSE:
            hinzu(_spaltenname(seite, feld), "diagnostic", "int",
                  "form.opponent_values")
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


def profile_feature_values(seite, profil, felder=PROFILE_FELDER):
    """
    Aus einem Teamprofil werden Merkmalsspalten - die EINE Stelle.

    Trainingsdatensatz und Laufzeit brauchen dieselbe Abbildung: dort
    ein Profil zum Stichtag, hier ein Profil zum Anpfiff. Zwei
    Fassungen derselben Zuordnung waeren die sicherste Art, ein Modell
    auf anders benannte oder anders sortierte Werte anzuwenden - und
    das faellt an keiner Zahl auf.

    Fehlende Felder bleiben None. Sie werden hier NICHT ersetzt: Was
    das Profil nicht hergibt, ist unbekannt, und die Entscheidung
    darueber gehoert an die Stelle, die den Bestand kennt.
    """
    return {_spaltenname(seite, feld): profil.get(feld) for feld in felder}


def _profil_werte(seite, profil, zeile):
    zeile.update(profile_feature_values(seite, profil))


def _workload_werte(seite, merkmale, haerte, zeile):
    for feld in WORKLOAD_FELDER + WORKLOAD_EXTRA_FELDER:
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


def workload_values_for_side(seite, team_id, cutoff, eintraege,
                             staerke_lookup, require_base_load=True,
                             timeline=None):
    """
    Der Belastungsblock EINER Seite - die EINE Stelle (V2-C3).

    Rueckgabe: (werte, grund). werte ist ein dict mit genau den
    Spalten, die auch im Datensatz stehen; grund ist die Coverage-
    Auskunft aus match_timeline.base_load_coverage (None, wenn die
    Sperre ausgeschaltet ist).

    WARUM DIESE FUNKTION EXISTIERT
    Bis V2-C3 lag die Zuordnung zweimal: einmal im Ligapfad
    (build_league_season) und einmal im CL-Pfad
    (cl_dataset._belastung_fuer_seite). Beide riefen zwar dieselben
    Rechenfunktionen, taten es aber in eigenem Code - und die Laufzeit
    haette eine dritte Fassung gebraucht. Drei Fassungen derselben
    Zuordnung sind die zuverlaessigste Art, Training und Betrieb
    auseinanderlaufen zu lassen, ohne dass es an einer Zahl auffaellt.

    Jetzt gibt es eine. Der Paritaetstest vergleicht die Werte aus
    einer fertigen Datensatzzeile mit einem direkten Aufruf dieser
    Funktion und verlangt exakte Gleichheit.

    require_base_load steuert die Coverage-Sperre. Der Ligapfad
    schaltet sie aus: Fuer eine Mannschaft aus einer der fuenf
    Top-Ligen ist der Grundtakt per Konstruktion bekannt - sie steht
    in der Liga, deren Datei gerade gelesen wird.

    timeline nimmt eine bereits gebaute Teamzeitleiste entgegen. Das
    ist ausschliesslich eine Abkuerzung fuer Aufrufer, die sie ohnehin
    zwischenspeichern; sie MUSS aus denselben Eintraegen stammen.
    Ohne Angabe wird sie hier gebaut.
    """
    from src.features.match_timeline import base_load_coverage, team_timeline
    from src.features.workload import schedule_strength, workload_features

    werte = {}
    grund = None

    if require_base_load:
        abgedeckt, grund = base_load_coverage(eintraege, team_id, cutoff)
        if not abgedeckt:
            # Kein Wert, aber eine Begruendung an jeder Qualitaets-
            # spalte. Eine Null waere hier eine Behauptung.
            for feld in (WORKLOAD_FELDER + WORKLOAD_EXTRA_FELDER
                         + SCHEDULE_FELDER):
                werte[_spaltenname(seite, feld)] = None
            for feld in QUALITAETS_FELDER + SCHEDULE_QUALITAET:
                werte[_spaltenname(seite, feld)] = grund
            for feld in DIAGNOSE_FELDER:
                werte[_spaltenname(seite, feld)] = None
            return werte, grund

    tl = team_timeline(eintraege, team_id) if timeline is None else timeline
    _workload_werte(seite, workload_features(tl, cutoff),
                    schedule_strength(tl, cutoff, staerke_lookup), werte)
    return werte, grund


def _form_werte(seite, merkmale, uefa, ziel):
    """Formwerte einer Seite in Spalten uebertragen - die EINE Zuordnung."""
    for feld in FORM_FELDER + FORM_OPPONENT_FELDER:
        ziel[_spaltenname(seite, feld)] = merkmale.get(feld)
    for feld in FORM_DEPTH_FELDER + FORM_OPPONENT_DIAGNOSE:
        ziel[_spaltenname(seite, feld)] = merkmale.get(feld)
    for feld in UEFA_FELDER + UEFA_QUALITAET:
        ziel[_spaltenname(seite, feld)] = uefa.get(feld)


def form_values_for_side(seite, team_id, season, cutoff, eintraege,
                         uefa_lookup, strength_at=None, timeline=None):
    """
    Der Formblock EINER Seite - die EINE Stelle (V2-C4).

    Rueckgabe: dict mit genau den Spalten, die auch im Datensatz
    stehen.

    Gebaut nach demselben Muster wie workload_values_for_side aus
    V2-C3, und aus demselben Grund: Datensatz und Laufzeit muessen
    denselben Codepfad benutzen. Eine zweite Fassung derselben
    Zuordnung ist die zuverlaessigste Art, Training und Betrieb
    auseinanderlaufen zu lassen, ohne dass es an einer Zahl auffaellt.
    Der Paritaetstest vergleicht eine fertige Datensatzzeile mit einem
    direkten Aufruf dieser Funktion und verlangt exakte Gleichheit.

    strength_at: Funktion (team_id, kickoff) -> Staerke oder None. Sie
    muss die Staerke des Gegners zum Zeitpunkt der DAMALIGEN Partie
    liefern, nicht zum Zielstichtag - siehe form.opponent_values.

    timeline: bereits gebaute Teamzeitleiste. Nur eine Abkuerzung fuer
    Aufrufer, die sie ohnehin zwischenspeichern; sie MUSS aus denselben
    Eintraegen stammen.
    """
    from src.features.form import form_features
    from src.features.match_timeline import team_timeline
    from src.features.uefa_strength import uefa_values

    tl = team_timeline(eintraege, team_id) if timeline is None else timeline
    merkmale = form_features(tl, cutoff, strength_at=strength_at)
    uefa = uefa_values(uefa_lookup, season, team_id)

    werte = {}
    _form_werte(seite, merkmale, uefa, werte)
    return werte


def form_difference_values(zeile, felder=FORM_DIFF_FELDER):
    """
    Die Formdifferenzen einer fertigen Zeile - die EINE Stelle.

    Fehlt eine der beiden Seiten, bleibt die Differenz None. Eine Null
    waere hier nicht "unbekannt", sondern die Aussage "beide gleich
    stark in Form".
    """
    werte = {}
    for feld in felder:
        heim = zeile.get(_spaltenname("home", feld))
        gast = zeile.get(_spaltenname("away", feld))
        if heim is None or gast is None:
            werte[_formdiffspaltenname(feld)] = None
        else:
            werte[_formdiffspaltenname(feld)] = float(heim) - float(gast)
    return werte


def workload_difference_values(zeile, felder=WORKLOAD_DIFF_FELDER):
    """
    Die Belastungsdifferenzen einer fertigen Zeile - die EINE Stelle.

    Wird von BEIDEN Datensatzpfaden gerufen (Liga und Champions League)
    und von der Laufzeit. Zwei Fassungen derselben Subtraktion waeren
    eine besonders unauffaellige Art, Training und Betrieb auseinander
    laufen zu lassen: Ein Vorzeichenfehler faellt an keiner Zahl auf.

    Fehlt eine der beiden Seiten, bleibt die Differenz None. Siehe
    WORKLOAD_DIFF_FELDER - eine Null waere hier nicht "unbekannt",
    sondern die Aussage "gleich belastet".
    """
    werte = {}
    for feld in felder:
        heim = zeile.get(_spaltenname("home", feld))
        gast = zeile.get(_spaltenname("away", feld))
        if heim is None or gast is None:
            werte[_diffspaltenname(feld)] = None
        else:
            werte[_diffspaltenname(feld)] = float(heim) - float(gast)
    return werte


def build_league_season(league_key, season, min_matchday=DEFAULT_MIN_MATCHDAY,
                        seasons_for_timeline=None,
                        include_uefa=INCLUDE_UEFA_BY_DEFAULT):
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

    # V2-C4: Gegnerstaerke zum Zeitpunkt der DAMALIGEN Partie und die
    # historische UEFA-Staerke. Beide Objekte leben genau so lange wie
    # dieser Saisonbau und tragen den Stichtag im Schluessel.
    from src.features.pit_profiles import PitStrengthAtDate
    from src.features.uefa_strength import NoUefaLookup, UefaStrengthLookup

    staerke_zum_zeitpunkt = PitStrengthAtDate(season=season)
    uefa_lookup = UefaStrengthLookup() if include_uefa else NoUefaLookup()

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
                # Herkunft. Reine Beschreibung - keine dieser Angaben
                # veraendert eine Zahl dieser Zeile.
                "competition": api_code,
                "stage": None,
                "exclusion_reason": (None if auswertbar
                                     else f"Aufwaermphase vor Spieltag "
                                          f"{min_matchday}"),
                "league_avg_source": LEAGUE_AVG_SOURCE,
                "home_profile_source": LEAGUE_PROFILE_SOURCE,
                "away_profile_source": LEAGUE_PROFILE_SOURCE,
                "home_profile_matches": heim_profil.get("matches_used") or 0,
                "away_profile_matches": gast_profil.get("matches_used") or 0,
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
                # Dieselbe Funktion wie im CL-Pfad und in der Laufzeit
                # (V2-C3). Ohne Coverage-Sperre: Beide Mannschaften
                # stehen in der Liga, deren Datei gerade gelesen wird -
                # ihr Grundtakt ist per Konstruktion bekannt.
                werte, _ = workload_values_for_side(
                    seite, team_id, cutoff, zeitleiste, lookup,
                    require_base_load=False,
                    timeline=zeitleiste_fuer(team_id))
                zeile.update(werte)

            for seite, team_id in (("home", heim_id), ("away", gast_id)):
                # Dieselbe Funktion wie im CL-Pfad und in der Laufzeit
                # (V2-C4).
                zeile.update(form_values_for_side(
                    seite, team_id, season, cutoff, zeitleiste,
                    uefa_lookup, strength_at=staerke_zum_zeitpunkt,
                    timeline=zeitleiste_fuer(team_id)))

            # Erst NACH beiden Seiten - die Differenzen brauchen beide.
            zeile.update(workload_difference_values(zeile))
            zeile.update(form_difference_values(zeile))

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
                  min_matchday=DEFAULT_MIN_MATCHDAY, include_cl=False,
                  include_uefa=INCLUDE_UEFA_BY_DEFAULT):
    """
    Der vollstaendige Datensatz ueber alle Ligen und Saisons.

    Die Reihenfolge ist fest: Liga, Saison, Datum, match_id. Ohne diese
    Sortierung waere ein Vergleich zweier Laeufe nicht moeglich - und
    Reproduzierbarkeit ist der ganze Zweck dieses Schrittes.

    include_cl haengt die Champions-League-Zeilen an. Standardmaessig
    AUS: Der bisherige Datensatz soll sich ohne ausdrueckliche Angabe
    nicht veraendern, und jeder Vergleich mit einem frueheren Lauf
    bleibt damit gueltig. Die Ligazeilen sind in beiden Faellen
    bitgleich - ein Test haelt das fest.

    Rueckgabe: (zeilen, diagnose).
    """
    leagues = list(leagues or DEFAULT_LEAGUES)
    seasons = list(seasons or DEFAULT_SEASONS)

    zeilen = []
    je_liga_saison = []
    uebersprungen = []
    gesamt = Counter()
    cl_diagnose = None

    for season in seasons:
        for league in leagues:
            teil, info = build_league_season(
                league, season, min_matchday, include_uefa=include_uefa)
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

    if include_cl:
        # Ausdruecklich das Schwestermodul und nicht das Paket: So bleibt
        # der Importguard in den Tests eng und meldet jede weitere
        # Quelle, die sich hier einschleicht.
        from src.ml.cl_dataset import DEFAULT_CL_SEASONS, build_cl_dataset

        cl_zeilen, cl_gesamt, cl_uebersprungen = build_cl_dataset(
            [s for s in seasons if s in DEFAULT_CL_SEASONS],
            include_uefa=include_uefa)
        zeilen.extend(cl_zeilen)
        uebersprungen.extend(cl_uebersprungen)
        cl_diagnose = {
            "rows": len(cl_zeilen),
            "evaluation_eligible": cl_gesamt.get("eligible", 0),
            "excluded": cl_gesamt.get("ausgeschlossen", 0),
            "per_stage": {k[len("stage_"):]: v for k, v in cl_gesamt.items()
                          if k.startswith("stage_")},
            "per_profile_source": {k[len("quelle_"):]: v
                                   for k, v in cl_gesamt.items()
                                   if k.startswith("quelle_")},
            "per_season": _cl_je_saison(cl_zeilen),
            "exclusion_reasons": dict(Counter(
                z["exclusion_reason"] for z in cl_zeilen
                if z["exclusion_reason"])),
            "rows_without_outcome": cl_gesamt.get("ohne_ergebnis", 0),
        }

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
        "champions_league": cl_diagnose,
    }
    return zeilen, diagnose


def _cl_je_saison(cl_zeilen):
    """CL-Zeilen nach Saison, Stage und Profilherkunft - fuer den Bericht."""
    je_saison = defaultdict(lambda: {"rows": 0, "eligible": 0,
                                     "stages": Counter(), "sources": Counter()})
    for zeile in cl_zeilen:
        eintrag = je_saison[zeile["season"]]
        eintrag["rows"] += 1
        eintrag["eligible"] += 1 if zeile["evaluation_eligible"] else 0
        eintrag["stages"][zeile["stage"]] += 1
        eintrag["sources"][zeile["home_profile_source"]] += 1
        eintrag["sources"][zeile["away_profile_source"]] += 1

    return [{"season": s, "rows": e["rows"],
             "evaluation_eligible": e["eligible"],
             "stages": dict(e["stages"]), "profile_sources": dict(e["sources"])}
            for s, e in sorted(je_saison.items())]


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
