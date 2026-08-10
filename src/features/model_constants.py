"""
Zentrale Stelle fuer Fallback-Torschnitte und die Einordnung aller
modellrelevanten Konstanten.

Warum dieses Modul existiert
----------------------------
Zwei Dinge liefen auseinander:

1. Der Fallback-Torschnitt fuer nationale Ligen stand doppelt im Code
   (team_profile.league_averages und strength_provider.get_league_strengths).
   Zwei Stellen mit demselben Zweck driften frueher oder spaeter
   auseinander - besonders sobald jemand anfaengt, sie zu kalibrieren.

2. Es war nicht erkennbar, welche Zahl im Modell was ist. Ein
   Heimvorteil-Schaetzwert und die Anzahl der Spieltage einer Liga sind
   beides "hartkodierte Zahlen", aber die eine gehoert spaeter empirisch
   bestimmt und die andere ist eine Verbandsregel, die man nicht
   optimiert.

WICHTIG: Domestic und CL bleiben bewusst GETRENNT
-------------------------------------------------
Beide beschreiben denselben Sachverhalt (Torschnitt ohne Datengrundlage),
aber fuer unterschiedliche Wettbewerbe. Die Champions League hat
historisch ein etwas offeneres Torniveau als der Schnitt der Top-5-Ligen.
Sie zu einer Konstante zusammenzufassen waere keine Vereinheitlichung,
sondern ein stiller Modellwechsel. Single Source of Truth heisst hier:
eine Definition je Wettbewerbstyp, nicht eine Definition insgesamt.

Die Zahlen selbst sind gegenueber dem Stand vor dieser Zentralisierung
unveraendert. Sie sind Baseline-Hypothesen, keine gemessenen Werte -
siehe die Einordnung unten.
"""


# ---------------------------------------------------------------------------
# Kategorien
# ---------------------------------------------------------------------------

# Modellannahme: bewusst gesetzt, spaeter empirisch zu bestimmen. Diese
# Werte duerfen NUR mit Belegen aus einem Backtest geaendert werden, nie
# nach Gefuehl.
CATEGORY_MODEL_PARAMETER = "model_parameter"

# Technischer Schutz gegen Ausreisser und Division durch Null. Nicht zu
# kalibrieren - hoechstens auf Plausibilitaet zu pruefen. Ein Guardrail
# darf das Ergebnis im Normalbetrieb gar nicht beruehren.
CATEGORY_GUARDRAIL = "guardrail"

# Wettbewerbsregel (DFL, UEFA). Aendert sich nur, wenn der Verband sie
# aendert. Diese Werte duerfen NIEMALS wie Modellparameter behandelt und
# schon gar nicht von einem Optimierer angefasst werden.
CATEGORY_COMPETITION_RULE = "competition_rule"

# Datenquelle/Budget: TTLs und Stichprobenschwellen. Technisch begruendet,
# nicht fussballerisch.
CATEGORY_DATA_POLICY = "data_policy"


# ---------------------------------------------------------------------------
# Fallback-Torschnitte (die eigentliche Zusammenfuehrung)
# ---------------------------------------------------------------------------

# Nationale Ligen. Greift nur, wenn ueberhaupt keine Spiele vorliegen -
# im Normalbetrieb also praktisch nie, weil data/historical/ gefuellt ist.
# Der implizite Heimvorteil steckt in der Differenz home_goals/away_goals.
DOMESTIC_LEAGUE_AVG_FALLBACK = {
    "home_goals": 1.5,
    "away_goals": 1.2,
    "total_goals": 2.7,
    "matches": 0,
}

# Champions League. Eigener Wert, weil das Torniveau historisch etwas
# hoeher liegt als im Schnitt der Top-5-Ligen. Greift nur, solange in der
# laufenden CL-Saison noch kein Spiel absolviert ist.
CL_LEAGUE_AVG_FALLBACK = {
    "home_goals": 1.55,
    "away_goals": 1.25,
    "total_goals": 2.80,
    "matches": 0,
}


def domestic_league_avg_fallback():
    """
    Fallback-Torschnitt fuer nationale Ligen, als frische Kopie.

    Bewusst eine Funktion statt der blanken Konstante: Aufrufer legen den
    Ligaschnitt in ihren Ergebnisdicts ab und veraendern ihn dort teils
    weiter. Ohne Kopie wuerde eine solche Aenderung auf den globalen Wert
    durchschlagen und alle spaeteren Simulationen desselben Prozesses
    still verfaelschen.
    """
    return dict(DOMESTIC_LEAGUE_AVG_FALLBACK)


def cl_league_avg_fallback():
    """Fallback-Torschnitt fuer die Champions League, als frische Kopie."""
    return dict(CL_LEAGUE_AVG_FALLBACK)


# ---------------------------------------------------------------------------
# Einordnung aller modellrelevanten Konstanten
# ---------------------------------------------------------------------------

def describe_constants():
    """
    Liefert die Einordnung jeder modellrelevanten Konstante.

    Die Werte werden hier NICHT wiederholt, sondern aus ihren Modulen
    importiert. Damit kann diese Uebersicht nicht von der Wirklichkeit
    abweichen - ein Test prueft genau das.

    Die Importe stehen absichtlich in der Funktion: team_profile
    importiert dieses Modul, ein Import auf Modulebene waere zirkulaer.

    Rueckgabe: Liste von Dicts mit name, value, module, category, note.
    """
    from src.features import team_profile, dynamic_weights, strength_provider
    from src.features import squad_impact
    from src.predict import season_sim, cl_season_sim

    return [
        # --- Modellparameter: spaeter empirisch zu bestimmen ---------------
        {
            "name": "DEFAULT_K",
            "value": dynamic_weights.DEFAULT_K,
            "module": "src.features.dynamic_weights",
            "category": CATEGORY_MODEL_PARAMETER,
            "note": "Blend Historie vs. laufende Saison, n/(n+k). Der "
                    "wirksamste Einzelparameter des Modells: Er entscheidet "
                    "in jeder Liga-Simulation, wie schnell die aktuelle "
                    "Saison die Historie ueberstimmt.",
        },
        {
            "name": "SEASON_DECAY",
            "value": team_profile.SEASON_DECAY,
            "module": "src.features.team_profile",
            "category": CATEGORY_MODEL_PARAMETER,
            "note": "Geometrische Gewichtung aelterer Saisons. Bestimmt, wie "
                    "lange eine starke Vorsaison nachwirkt.",
        },
        {
            "name": "DEFAULT_SHRINKAGE_K",
            "value": team_profile.DEFAULT_SHRINKAGE_K,
            "module": "src.features.team_profile",
            "category": CATEGORY_MODEL_PARAMETER,
            "note": "Regularisierung der Attack/Defence-Ratings. Wirkt vor "
                    "allem bei Aufsteigern und zu Saisonbeginn.",
        },
        {
            "name": "FALLBACK_PROMOTED_ATTACK",
            "value": strength_provider.FALLBACK_PROMOTED_ATTACK,
            "module": "src.features.strength_provider",
            "category": CATEGORY_MODEL_PARAMETER,
            "note": "Aufsteiger-Schaetzwert, nur ohne empirisches Profil.",
        },
        {
            "name": "FALLBACK_PROMOTED_DEFENCE",
            "value": strength_provider.FALLBACK_PROMOTED_DEFENCE,
            "module": "src.features.strength_provider",
            "category": CATEGORY_MODEL_PARAMETER,
            "note": "Gegenstueck zu FALLBACK_PROMOTED_ATTACK.",
        },
        {
            "name": "PROMOTED_SAMPLE_TARGET",
            "value": strength_provider.PROMOTED_SAMPLE_TARGET,
            "module": "src.features.strength_provider",
            "category": CATEGORY_MODEL_PARAMETER,
            "note": "Ab wie vielen beobachteten Aufsteigern der empirische "
                    "Mittelwert als voll belastbar gilt.",
        },
        {
            "name": "REPLACEMENT_FACTOR",
            "value": squad_impact.REPLACEMENT_FACTOR,
            "module": "src.features.squad_impact",
            "category": CATEGORY_MODEL_PARAMETER,
            "note": "Wie stark ein Ersatzspieler den Ausfall auffaengt. "
                    "Schwer isolierbar - eher Kandidat fuer ein gelerntes "
                    "Modell als fuer eine feste Zahl.",
        },
        {
            "name": "DOMESTIC_LEAGUE_AVG_FALLBACK",
            "value": DOMESTIC_LEAGUE_AVG_FALLBACK,
            "module": "src.features.model_constants",
            "category": CATEGORY_MODEL_PARAMETER,
            "note": "Torschnitt ohne Datengrundlage, nationale Ligen. "
                    "Enthaelt implizit den Heimvorteil.",
        },
        {
            "name": "CL_LEAGUE_AVG_FALLBACK",
            "value": CL_LEAGUE_AVG_FALLBACK,
            "module": "src.features.model_constants",
            "category": CATEGORY_MODEL_PARAMETER,
            "note": "Wie oben, aber fuer die Champions League. Bewusst "
                    "getrennt: anderes Torniveau.",
        },

        # --- Guardrails: schuetzen, nicht modellieren ----------------------
        {
            "name": "RATING_MIN",
            "value": team_profile.RATING_MIN,
            "module": "src.features.team_profile",
            "category": CATEGORY_GUARDRAIL,
            "note": "Untergrenze fuer Attack/Defence-Ratings.",
        },
        {
            "name": "RATING_MAX",
            "value": team_profile.RATING_MAX,
            "module": "src.features.team_profile",
            "category": CATEGORY_GUARDRAIL,
            "note": "Obergrenze. Dreifache Durchschnittsoffensive gibt es "
                    "im Profifussball nicht.",
        },
        {
            "name": "XG_MIN",
            "value": team_profile.XG_MIN,
            "module": "src.features.team_profile",
            "category": CATEGORY_GUARDRAIL,
            "note": "Untergrenze fuer lambda. Verhindert entartete "
                    "Poisson-Ziehungen.",
        },
        {
            "name": "XG_MAX",
            "value": team_profile.XG_MAX,
            "module": "src.features.team_profile",
            "category": CATEGORY_GUARDRAIL,
            "note": "Obergrenze fuer lambda.",
        },
        {
            "name": "MAX_ATTACK_PENALTY",
            "value": squad_impact.MAX_ATTACK_PENALTY,
            "module": "src.features.squad_impact",
            "category": CATEGORY_GUARDRAIL,
            "note": "Deckel fuer den Ausfall-Malus. Eine Mannschaft bricht "
                    "nicht um mehr als diesen Anteil ein.",
        },
        {
            "name": "NEUTRAL_RATING",
            "value": team_profile.NEUTRAL_RATING,
            "module": "src.features.team_profile",
            "category": CATEGORY_GUARDRAIL,
            "note": "Definition des Ligadurchschnitts. Per Konstruktion 1.0, "
                    "keine Stellschraube.",
        },

        # --- Wettbewerbsregeln: niemals optimieren -------------------------
        {
            "name": "MATCHDAYS_TOTAL",
            "value": season_sim.MATCHDAYS_TOTAL,
            "module": "src.predict.season_sim",
            "category": CATEGORY_COMPETITION_RULE,
            "note": "Spieltage je Liga. Ligastruktur, keine Annahme.",
        },
        {
            "name": "ZONE_CONFIGS",
            "value": season_sim.ZONE_CONFIGS,
            "module": "src.predict.season_sim",
            "category": CATEGORY_COMPETITION_RULE,
            "note": "Europapokal- und Abstiegsplaetze. ACHTUNG: Der fuenfte "
                    "CL-Platz haengt am UEFA-Koeffizienten und kann sich "
                    "je Saison verschieben - jaehrlich pruefen.",
        },
        {
            "name": "CL_ZONE_DIRECT_LAST",
            "value": cl_season_sim.CL_ZONE_DIRECT_LAST,
            "module": "src.predict.cl_season_sim",
            "category": CATEGORY_COMPETITION_RULE,
            "note": "Plaetze 1-8 der Ligaphase: direkt ins Achtelfinale.",
        },
        {
            "name": "CL_ZONE_PLAYOFF_LAST",
            "value": cl_season_sim.CL_ZONE_PLAYOFF_LAST,
            "module": "src.predict.cl_season_sim",
            "category": CATEGORY_COMPETITION_RULE,
            "note": "Plaetze 9-24: Playoff. Ab 25 ausgeschieden.",
        },
        {
            "name": "TIEBREAK_CRITERIA",
            "value": cl_season_sim.TIEBREAK_CRITERIA,
            "module": "src.predict.cl_season_sim",
            "category": CATEGORY_COMPETITION_RULE,
            "note": "Offizielle UEFA-Kaskade. Disziplinarpunkte und "
                    "Klubkoeffizient fehlen bewusst und werden nicht "
                    "geschaetzt, sondern im Ergebnis ausgewiesen.",
        },

        # --- Datenpolitik --------------------------------------------------
        {
            "name": "CURRENT_LEAGUE_AVG_MIN_MATCHES",
            "value": strength_provider.CURRENT_LEAGUE_AVG_MIN_MATCHES,
            "module": "src.features.strength_provider",
            "category": CATEGORY_DATA_POLICY,
            "note": "Ab wie vielen Spielen der Ligaschnitt der laufenden "
                    "Saison den historischen ersetzt.",
        },
    ]


def constants_by_category(category):
    """Alle Konstanten einer Kategorie."""
    return [c for c in describe_constants() if c["category"] == category]


def calibratable_constants():
    """
    Die Konstanten, die eine spaetere Kalibrierung anfassen DARF.

    Alles andere ist Guardrail, Wettbewerbsregel oder Datenpolitik und
    bleibt unberuehrt. Diese Funktion ist die vorgesehene Schnittstelle
    fuer einen kuenftigen Parameter-Sweep.
    """
    return constants_by_category(CATEGORY_MODEL_PARAMETER)
