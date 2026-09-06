"""
Merkmalsgruppen und Ablationsvarianten.

WOZU DAS NOETIG IST
-------------------
Die Schattenauswertung hat gemessen, dass die gelernte Korrektur die
Baseline schlaegt: LogLoss -0,00944 ueber 2.924 Spiele, Bootstrap-
Intervall vollstaendig unter null. Was sie NICHT gemessen hat, ist
WOHER diese Verbesserung kommt.

Das ist keine akademische Frage. Die groessten Koeffizienten des
Modells liegen auf den Profilmerkmalen - also auf denselben Groessen,
aus denen die Baseline ihre Lambdas ohnehin schon bildet. Zwei sehr
verschiedene Erklaerungen passen auf denselben Befund:

    (A) Das Modell justiert nur die Gewichtung der Baseline nach. Dann
        ist die Verbesserung eine REKALIBRIERUNG, und weitere Merkmale
        derselben Art bringen wenig.

    (B) Die Belastungsmerkmale tragen echte Zusatzinformation, die die
        Baseline gar nicht kennt. Dann lohnt es, in diese Richtung
        weiterzubauen.

Ohne Trennung der Merkmalsmengen laesst sich zwischen beiden nicht
entscheiden - und die Entscheidung, ob als naechstes Formmerkmale
gebaut werden, haengt genau daran.

DIE GRUPPEN WERDEN ABGELEITET, NICHT ABGETIPPT
----------------------------------------------
Jede Gruppe entsteht aus denselben Konstanten, aus denen auch
dataset.build_schema() die Spalten baut - PROFILE_FELDER, LIGA_FELDER,
WORKLOAD_FELDER, SCHEDULE_FELDER. Eine handgepflegte Namensliste waere
die sicherste Art, bei der naechsten Schemaaenderung unbemerkt
auseinanderzulaufen: Die Ablation liefe weiter, nur eben ueber eine
andere Merkmalsmenge als die, die sie zu messen behauptet.

HARTES SCHEITERN STATT STILLEM UEBERGEHEN
-----------------------------------------
validate_groups() verlangt eine vollstaendige, ueberschneidungsfreie
Zerlegung der Modellmerkmale. Eine nicht zugeordnete Spalte, eine
doppelt zugeordnete Spalte oder ein Gruppeneintrag, den das Schema gar
nicht kennt, brechen ab.

Der Grund ist derselbe wie oben: Eine Ablation, die eine Spalte
stillschweigend uebergeht, misst nicht das, was in ihrem Ergebnis
steht. Ein Abbruch kostet eine Minute; ein falsch beschriftetes
Ergebnis kostet die naechste Entwurfsentscheidung.

CONGESTION_LEVEL IST DER BEKANNTE SONDERFALL
--------------------------------------------
WORKLOAD_FELDER enthaelt congestion_level. Die Spalte ist Text
("normal", "elevated", "high") und steht deshalb nicht in
model.feature_columns(). Sie wird hier NICHT stillschweigend
weggefiltert, sondern als not_modelled ausgewiesen - und es wird
geprueft, dass sie tatsaechlich auf der Ausschlussliste des Modells
steht. Faende sich dort eine Spalte, die aus einem anderen Grund fehlt,
faellt das auf.
"""

from src.ml import dataset as ds
from src.ml import model as mdl

#: Fassung der Gruppen- und Variantendefinition. Erhoehen, sobald sich
#: eine Gruppenzugehoerigkeit aendert - sonst liessen sich zwei
#: Ablationslaeufe spaeter nicht mehr auseinanderhalten.
#: 2  V2-C3: Die Gruppe workload_difference kam hinzu, und die
#:    Belastungsgruppe laesst sich ueber WORKLOAD_SUBGROUPS feiner
#:    aufteilen. Die BESTEHENDEN Gruppen und der V1-Kandidat sind
#:    unveraendert - erhoeht wurde, weil sich die Zerlegung geaendert
#:    hat und zwei Laeufe sonst nicht mehr auseinanderzuhalten waeren.
#: 3  V2-C4: vier weitere Gruppen (form, form_opponent, uefa,
#:    form_difference) und eine zweite Untergruppenebene fuer sie. Die
#:    BESTEHENDEN Gruppen und der V1-Kandidat sind erneut unveraendert.
SCHEMA_VERSION = 3

#: Beide Seiten tragen dieselben Merkmale. Dieselbe Reihenfolge wie in
#: dataset.build_schema().
SEITEN = ("home", "away")

#: Die Gruppen in fester Reihenfolge. Sie ist zugleich die
#: Berichtsreihenfolge.
GROUP_ORDER = ("profile", "profile_depth", "league_average", "workload",
               "workload_extra", "workload_difference", "schedule_strength",
               "form", "form_opponent", "uefa", "form_difference")

#: Was jede Gruppe inhaltlich ist. Gehoert ins Ergebnisartefakt: Eine
#: Gruppe ohne Beschreibung laesst sich spaeter nicht mehr von einer
#: willkuerlichen Auswahl unterscheiden.
GROUP_DESCRIPTIONS = {
    "profile": "Teamprofil je Seite zum Stichtag - Angriff, Abwehr, "
               "Punkte, Tore, Siegquote "
               "(team_profile.build_season_profiles)",
    "profile_depth": "Tiefe der Datenbasis je Seite (matches_used). "
                     "Beschreibt die QUELLE, nicht die Mannschaft - und "
                     "haengt deshalb daran, wie das Profil gebaut wurde. "
                     "Im Ligatraining 5..37, im geblendeten CL-Stand "
                     "33..114; deshalb eine eigene Gruppe, die sich "
                     "gezielt weglassen laesst",
    "league_average": "Ligadurchschnitt zum Stichtag - Heim-, Auswaerts- "
                      "und Gesamttore sowie die Zahl bekannter Spiele "
                      "(derselbe Aufruf wie die Profile)",
    "workload": "Belastung je Seite - Ruhezeit, Spieldichte in vier "
                "Fenstern, Auswaertsserie, nutzbare Spiele "
                "(workload.workload_features). UNVERAENDERT seit der "
                "ersten Ablationsstufe, damit die Variante "
                "workload_only weiterhin dieselben 24 Merkmale "
                "bezeichnet",
    "workload_extra": "Verlaengerungsbelastung je Seite - Partien mit "
                      "Verlaengerung und die daraus zusaetzlich "
                      "gespielten Minuten der letzten 30 Tage. Eigene "
                      "Gruppe, weil dies die einzigen Belastungsfelder "
                      "mit wettbewerbsabhaengiger Datenlage sind",
    "workload_difference": "Belastungsdifferenz Heim minus Auswaerts "
                           "(dataset.workload_difference_values). "
                           "Rechnerisch keine neue Information, aber "
                           "eine vorzeichensymmetrische Darstellung "
                           "derselben - deshalb eine eigene, gezielt "
                           "weglassbare Gruppe",
    "form": "Kurzfristige Form je Seite - Punktequote und Tordifferenz "
            "ueber die letzten 3/5/8 Partien, dazu national, "
            "Champions League, Heim und Auswaerts getrennt "
            "(form.form_features)",
    "form_opponent": "Gegnerstaerke der juengsten fuenf Partien und die "
                     "daran gewichtete Punktequote. Die Staerke gilt zum "
                     "Zeitpunkt der DAMALIGEN Partie, nicht zum "
                     "Zielstichtag (form.opponent_values)",
    "uefa": "Historische UEFA-Staerke je Seite - Vereinskoeffizient, "
            "Rang und ein daraus abgeleiteter Landeswert. Massgeblich "
            "ist stets der Snapshot der VORSAISON "
            "(uefa_strength.uefa_values)",
    "form_difference": "Formdifferenz Heim minus Auswaerts ueber "
                       "Punktequote, Tordifferenz und "
                       "Vereinskoeffizient (dataset.form_difference_values)",
    "schedule_strength": "Gegnerhaerte je Seite - Staerke der juengsten "
                         "Gegner und die Zahl der dabei nutzbaren "
                         "bzw. unbewertbaren Gegner "
                         "(workload.schedule_strength)",
}


def _seitenspalten(felder):
    """Ein Feld je Seite, wie es dataset._spaltenname() bildet."""
    return tuple(f"{seite}_{feld}" for seite in SEITEN for feld in felder)


def build_raw_groups():
    """
    Die Gruppen VOR dem Abgleich mit der Modellmerkmalsliste.

    Rueckgabe: {gruppenname: (spalte, ...)} - sortiert, damit zwei
    Laeufe dieselbe Reihenfolge ergeben.

    Hier steht ausdruecklich noch alles drin, was aus den
    Schemakonstanten folgt - auch congestion_level, das im Modell
    nicht vorkommt. Die Trennung passiert erst in build_groups(), und
    sie passiert sichtbar.
    """
    roh = {
        "profile": _seitenspalten(ds.PROFILE_RATING_FELDER),
        "profile_depth": _seitenspalten(ds.PROFILE_DEPTH_FELDER),
        "league_average": tuple(f"league_avg_{feld}"
                                for feld in ds.LIGA_FELDER),
        "workload": _seitenspalten(ds.WORKLOAD_FELDER),
        "workload_extra": _seitenspalten(ds.WORKLOAD_EXTRA_FELDER),
        "workload_difference": tuple(ds._diffspaltenname(feld)
                                     for feld in ds.WORKLOAD_DIFF_FELDER),
        "form": _seitenspalten(ds.FORM_FELDER),
        "form_opponent": _seitenspalten(ds.FORM_OPPONENT_FELDER),
        "uefa": _seitenspalten(ds.UEFA_FELDER),
        "form_difference": tuple(ds._formdiffspaltenname(feld)
                                 for feld in ds.FORM_DIFF_FELDER),
        "schedule_strength": _seitenspalten(ds.SCHEDULE_FELDER),
    }
    return {name: tuple(sorted(roh[name])) for name in GROUP_ORDER}


def build_groups(spalten=None):
    """
    Die Gruppen, aufgeteilt in Modellmerkmale und Nichtmodellierte.

    Rueckgabe: {gruppenname: {"columns": (...), "not_modelled": (...)}}

    columns       geht ins Modell und ist Gegenstand der Ablation.
    not_modelled  gehoert fachlich zur Gruppe, steht aber nicht in
                  model.feature_columns() - derzeit ausschliesslich
                  congestion_level.

    Die zweite Liste bleibt bestehen, statt weggefiltert zu werden:
    Wer spaeter liest, dass workload 18 Merkmale hat, soll auch sehen,
    dass ein neunzehntes existiert und warum es fehlt.
    """
    spalten = set(spalten if spalten is not None else mdl.feature_columns())

    gruppen = {}
    for name, roh in build_raw_groups().items():
        gruppen[name] = {
            "columns": tuple(s for s in roh if s in spalten),
            "not_modelled": tuple(s for s in roh if s not in spalten),
        }
    return gruppen


def validate_groups(gruppen=None, spalten=None, schema=None):
    """
    Prueft, dass die Gruppen die Modellmerkmale vollstaendig zerlegen.

    Geprueft wird viererlei, und jeder Punkt bricht hart ab:

      1. Jede genannte Spalte existiert im Datensatzschema.
      2. Keine Spalte steht in zwei Gruppen.
      3. Jedes Modellmerkmal steht in genau einer Gruppe.
      4. Jede der Gruppe zugeordnete, aber nicht modellierte Spalte
         steht ausdruecklich auf der Ausschlussliste des Modells.

    Punkt 3 ist der eigentliche Zweck: Ohne ihn koennte ein neues
    Merkmal ins Schema wandern, in keiner Gruppe auftauchen und damit
    in JEDER Ablationsvariante fehlen - die Varianten waeren dann
    heimlich alle unvollstaendig, und der Vergleich mit
    all_existing_features waere keiner mehr.

    Rueckgabe: eine Zusammenfassung fuer das Ergebnisartefakt.
    Wirft ValueError, sobald etwas nicht aufgeht.
    """
    spalten = list(spalten if spalten is not None
                   else mdl.feature_columns())
    gruppen = gruppen if gruppen is not None else build_groups(spalten)

    schema = schema or ds.build_schema()
    bekannt = {eintrag["name"] for eintrag in schema}
    ausgeschlossen = {eintrag["column"]: eintrag["reason"]
                      for eintrag in mdl.excluded_columns(schema)}

    gesehen = {}
    for name in GROUP_ORDER:
        if name not in gruppen:
            raise ValueError(f"Merkmalsgruppe fehlt: {name}")
        eintrag = gruppen[name]
        for spalte in tuple(eintrag["columns"]) + tuple(eintrag["not_modelled"]):
            if spalte not in bekannt:
                raise ValueError(
                    f"Gruppe {name!r} nennt die Spalte {spalte!r}, die das "
                    f"Datensatzschema nicht kennt")
            if spalte in gesehen:
                raise ValueError(
                    f"Spalte {spalte!r} steht in zwei Gruppen: "
                    f"{gesehen[spalte]!r} und {name!r}")
            gesehen[spalte] = name

    unbekannte_gruppen = set(gruppen) - set(GROUP_ORDER)
    if unbekannte_gruppen:
        raise ValueError(
            f"unbekannte Merkmalsgruppen: {sorted(unbekannte_gruppen)}")

    zugeordnet = set()
    for name in GROUP_ORDER:
        zugeordnet.update(gruppen[name]["columns"])

    fehlend = sorted(set(spalten) - zugeordnet)
    if fehlend:
        raise ValueError(
            f"Modellmerkmale ohne Gruppe: {fehlend} - jede Ablationsvariante "
            f"wuerde sie stillschweigend auslassen")

    zuviel = sorted(zugeordnet - set(spalten))
    if zuviel:
        raise ValueError(
            f"als Modellmerkmal gefuehrt, aber nicht in "
            f"model.feature_columns(): {zuviel}")

    for name in GROUP_ORDER:
        for spalte in gruppen[name]["not_modelled"]:
            if spalte not in ausgeschlossen:
                raise ValueError(
                    f"Spalte {spalte!r} aus Gruppe {name!r} ist weder "
                    f"Modellmerkmal noch ausdruecklich ausgeschlossen")

    return {
        "group_order": list(GROUP_ORDER),
        "descriptions": dict(GROUP_DESCRIPTIONS),
        "columns": {name: list(gruppen[name]["columns"])
                    for name in GROUP_ORDER},
        "counts": {name: len(gruppen[name]["columns"])
                   for name in GROUP_ORDER},
        "not_modelled": {
            name: [{"column": spalte, "reason": ausgeschlossen[spalte]}
                   for spalte in gruppen[name]["not_modelled"]]
            for name in GROUP_ORDER},
        "total_model_features": len(spalten),
    }


# ---------------------------------------------------------------------------
# Varianten
# ---------------------------------------------------------------------------

#: Die Ablationsvarianten, VORAB festgelegt.
#:
#: no_correction ist die Kontrolle und keine Zierde: Sie muss ein Delta
#: von exakt null und ein Intervall [0, 0] liefern. Tut sie das nicht,
#: misst der Aufbau selbst etwas, und kein anderes Ergebnis dieser
#: Datei waere zu gebrauchen.
#:
#: profile_only und workload_only sind die eigentliche Frage. Ihre
#: Deltas addieren sich NICHT zwangslaeufig zum Delta von
#: all_existing_features - Merkmale koennen einander ersetzen oder
#: verstaerken. Der Vergleich ist deshalb ein Hinweis auf die Herkunft
#: der Verbesserung, keine Zerlegung in Summanden.
#: Die drei Betriebsarten einer Variante. Sie entscheiden, WAS
#: angepasst wird - nicht nur, welche Merkmale dabei sind.
#:
#: Ohne diese Unterscheidung waeren no_correction und intercept_only
#: nicht auseinanderzuhalten: Beide haben null Merkmale, aber das eine
#: passt gar nichts an, das andere einen Achsenabschnitt. Genau ihr
#: Unterschied ist die Diagnosefrage der zweiten Stufe.
MODE_BASELINE = "baseline"
MODE_INTERCEPT = "intercept"
MODE_FEATURES = "features"

VARIANTS = (
    {
        "name": "no_correction",
        "mode": MODE_BASELINE,
        "groups": (),
        "description": "keine Korrektur - die unveraenderte Baseline als "
                       "Kontrolle des Messaufbaus",
    },
    {
        "name": "profile_only",
        "mode": MODE_FEATURES,
        "groups": ("profile", "profile_depth", "league_average"),
        "description": "ausschliesslich Teamprofil- und "
                       "Ligadurchschnittsmerkmale - dieselben Groessen, "
                       "aus denen die Baseline ihre Lambdas bildet",
    },
    {
        "name": "workload_only",
        "mode": MODE_FEATURES,
        "groups": ("workload", "schedule_strength"),
        "description": "ausschliesslich Ruhe-, Belastungs- und "
                       "Gegnerstaerkemerkmale - Information, die in die "
                       "Baseline nicht eingeht",
    },
    {
        "name": "all_existing_features",
        "mode": MODE_FEATURES,
        "groups": GROUP_ORDER,
        "description": "der bisherige vollstaendige Merkmalssatz - der "
                       "Stand, den shadow_eval gemessen hat",
    },
)

VARIANT_ORDER = tuple(variante["name"] for variante in VARIANTS)


# ---------------------------------------------------------------------------
# Zweite Diagnosestufe
# ---------------------------------------------------------------------------

#: Die Stufe-2-Varianten, VORAB festgelegt.
#:
#: DIE FRAGE
#: Die erste Stufe hat gezeigt, dass die Verbesserung vollstaendig aus
#: profile_only stammt (-0,01446) und die Belastungsmerkmale nichts
#: beitragen. Offen blieb, WAS an profile_only wirkt. Drei Erklaerungen
#: sind mit dem Befund vertraeglich:
#:
#:   (A) eine einzige globale Zahl skaliert alle Lambdas nach - dann
#:       erreicht intercept_only schon fast alles
#:   (B) der Ligadurchschnitt traegt es - dann erreicht
#:       league_average_only fast alles
#:   (C) das Modell gewichtet die Teamstaerken wirklich neu - dann
#:       braucht es team_profile_only, und die beiden anderen bleiben
#:       weit zurueck
#:
#: Die Varianten sind so geschnitten, dass genau diese drei Faelle
#: auseinanderfallen. intercept_only ist dabei die Untergrenze jeder
#: denkbaren Rekalibrierung: weniger als eine Zahl geht nicht.
#:
#: profile_only und all_existing_features laufen unveraendert mit -
#: ohne sie waere die Stufe nicht an die erste anschlussfaehig.
DIAGNOSTIC_VARIANTS = (
    {
        "name": "intercept_only",
        "mode": MODE_INTERCEPT,
        "groups": (),
        "description": "kein einziges Merkmal - nur ein zusaetzlich "
                       "angepasster Achsenabschnitt auf dem bestehenden "
                       "Baseline-Offset; die Untergrenze jeder "
                       "Rekalibrierung",
    },
    {
        "name": "league_average_only",
        "mode": MODE_FEATURES,
        "groups": ("league_average",),
        "description": "ausschliesslich die vier Ligadurchschnitts"
                       "merkmale - eine ligabezogene Rekalibrierung ohne "
                       "jede Teaminformation",
    },
    {
        "name": "team_profile_only",
        "mode": MODE_FEATURES,
        "groups": ("profile", "profile_depth"),
        "description": "ausschliesslich die 18 Teamprofilmerkmale - "
                       "Teaminformation ohne den Ligadurchschnitt",
    },
    {
        "name": "profile_only",
        "mode": MODE_FEATURES,
        "groups": ("profile", "profile_depth", "league_average"),
        "description": "die bestehende Kombination aus Teamprofil und "
                       "Ligadurchschnitt - unveraendert als Referenz",
    },
    {
        "name": "all_existing_features",
        "mode": MODE_FEATURES,
        "groups": GROUP_ORDER,
        "description": "der vollstaendige Merkmalssatz - unveraendert als "
                       "Kontrollreferenz",
    },
)

DIAGNOSTIC_VARIANT_ORDER = tuple(variante["name"]
                                 for variante in DIAGNOSTIC_VARIANTS)


# ---------------------------------------------------------------------------
# Champions-League-Kandidat
# ---------------------------------------------------------------------------

#: Der Merkmalssatz, mit dem eine CL-Uebertragung spaeter gemessen wird.
#:
#: WARUM OHNE profile_depth
#: Gemessen, nicht vermutet. Auf Ligadaten kostet das Weglassen von
#: matches_used nichts:
#:
#:     mit    -0,01376   KI [-0,01803, -0,00970]
#:     ohne   -0,01615   KI [-0,02177, -0,01073]
#:     gepaart (ohne - mit)  -0,00239   KI [-0,00494, +0,00010]
#:
#: Das Intervall enthaelt die Null - es gibt keinen belastbaren
#: Unterschied, und der Punktschaetzer ist sogar besser.
#:
#: Auf CL-Partien loest das Weglassen dagegen den Verteilungsbruch auf.
#: Medianer Auswaertsfaktor, Liga gegen CL:
#:
#:     mit    1,045 -> 1,221   Drift +0,175
#:     ohne   1,042 -> 1,007   Drift -0,035
#:
#: Ein Merkmal, das nichts beitraegt und die Uebertragung verzerrt,
#: gehoert nicht in den Kandidaten. Die Spalte bleibt im Datensatz - sie
#: ist als Auswertungsgroesse nuetzlich, nur eben nicht als Merkmal.
CL_PRIMARY_CANDIDATE = "team_profile_cl"

CL_VARIANTS = (
    {
        "name": CL_PRIMARY_CANDIDATE,
        "mode": MODE_FEATURES,
        "groups": ("profile",),
        "description": "Teamprofil ohne Datentiefe - der CL-Kandidat. "
                       "Enthaelt ausschliesslich Groessen, die die "
                       "Mannschaft beschreiben, und keine, die von der "
                       "Bauart des Profils abhaengt",
    },
)

CL_VARIANT_ORDER = tuple(variante["name"] for variante in CL_VARIANTS)

# ---------------------------------------------------------------------------
# Belastungsuntergruppen (V2-C3)
# ---------------------------------------------------------------------------

#: Die Belastungsgruppen, feiner zerlegt.
#:
#: WOZU EINE ZWEITE EBENE
#: Die Gruppe "workload" umfasst zwanzig Spalten in einem Block. Eine
#: Ablation auf dieser Ebene kann nur "alles oder nichts" beantworten -
#: die Frage von V2-C3 lautet aber, WELCHES Belastungsmerkmal traegt.
#: Vier stark korrelierte Zaehlfenster gleichzeitig aufzunehmen, weil
#: der Block insgesamt hilft, waere genau der Fehler, den der
#: Redundanzteil verhindern soll.
#:
#: DIE ZERLEGUNG IST EINE ECHTE PARTITION
#: Die Untergruppen zerlegen "workload", "workload_extra" und
#: "workload_difference" vollstaendig und ueberschneidungsfrei. validate_subgroups() prueft
#: das und bricht ab, sobald eine Spalte fehlt oder doppelt steht -
#: sonst koennte eine Variante behaupten, "alle Belastungsmerkmale" zu
#: enthalten, und dabei eines auslassen.
#:
#: SCHEDULE_STRENGTH IST NICHT DABEI
#: Gegnerhaerte ist Gegnerstaerke, nicht Belastung. Sie gehoert
#: fachlich nach V2-C4 und bleibt hier ausdruecklich draussen, damit
#: ein C3-Ergebnis nicht heimlich ein C4-Merkmal mitmisst.
SUBGROUP_ORDER = ("rest", "short_rest", "matches_7d", "matches_14d",
                  "matches_21d", "matches_30d", "away_streak",
                  "extra_time", "timeline_depth", "difference")

SUBGROUP_FIELDS = {
    "rest": ("rest_hours", "rest_days"),
    "short_rest": ("short_rest_flag",),
    "matches_7d": ("matches_last_7_days",),
    "matches_14d": ("matches_last_14_days",),
    "matches_21d": ("matches_last_21_days",),
    "matches_30d": ("matches_last_30_days",),
    "away_streak": ("consecutive_away_matches",),
    "extra_time": ds.WORKLOAD_EXTRA_FELDER,
    "timeline_depth": ("number_of_usable_matches",),
}

SUBGROUP_DESCRIPTIONS = {
    "rest": "Ruhezeit vor dem Spiel in Stunden und in vollen Tagen "
            "(dieselbe Groesse in zwei Aufloesungen)",
    "short_rest": "kurze Regeneration - Pause unter "
                  "workload.SHORT_REST_HOURS (72 h)",
    "matches_7d": "Pflichtspiele in den letzten 7 Tagen",
    "matches_14d": "Pflichtspiele in den letzten 14 Tagen",
    "matches_21d": "Pflichtspiele in den letzten 21 Tagen",
    "matches_30d": "Pflichtspiele in den letzten 30 Tagen",
    "away_streak": "Zahl der unmittelbar vorangegangenen Auswaertsspiele "
                   "in Folge - die Serie bricht beim ersten Heimspiel",
    "extra_time": "Verlaengerungsbelastung der letzten 30 Tage: Partien "
                  "mit Verlaengerung und die daraus zusaetzlich "
                  "gespielten Minuten",
    "timeline_depth": "Zahl der ueberhaupt bekannten frueheren Partien - "
                      "beschreibt die QUELLE, nicht die Belastung",
    "difference": "Belastungsdifferenz Heim minus Auswaerts ueber "
                  "Ruhezeit und alle vier Zaehlfenster",
}

#: Untergruppen, die fachlich zusammengehoeren. Vorab festgelegt, damit
#: sie nicht nach Betrachtung der Einzelergebnisse zusammengestellt
#: werden koennen.
SUBGROUP_BUNDLES = {
    "congestion_windows": ("matches_7d", "matches_14d", "matches_21d",
                           "matches_30d"),
    "recovery": ("rest", "short_rest"),
    "all_workload": tuple(SUBGROUP_ORDER),
}


def build_subgroups(spalten=None):
    """
    Die Belastungsuntergruppen als Spaltenmengen.

    Rueckgabe: {name: (spalte, ...)} - sortiert, wie ueberall in dieser
    Datei, damit zwei Laeufe dieselbe Reihenfolge ergeben.
    """
    spalten = set(spalten if spalten is not None else mdl.feature_columns())

    unter = {}
    for name in SUBGROUP_ORDER:
        if name == "difference":
            roh = tuple(ds._diffspaltenname(feld)
                        for feld in ds.WORKLOAD_DIFF_FELDER)
        else:
            roh = _seitenspalten(SUBGROUP_FIELDS[name])
        unter[name] = tuple(sorted(sp for sp in roh if sp in spalten))
    return unter


def validate_subgroups(unter=None, gruppen=None, spalten=None):
    """
    Die Untergruppen muessen workload und workload_difference
    vollstaendig und ueberschneidungsfrei zerlegen.

    Derselbe Grund wie bei validate_groups(): Eine Variante, die eine
    Spalte stillschweigend uebergeht, misst nicht das, was in ihrem
    Namen steht. Ein Abbruch kostet eine Minute.
    """
    spalten = list(spalten if spalten is not None else mdl.feature_columns())
    gruppen = gruppen if gruppen is not None else build_groups(spalten)
    unter = unter if unter is not None else build_subgroups(spalten)

    soll = (set(gruppen["workload"]["columns"])
            | set(gruppen["workload_extra"]["columns"])
            | set(gruppen["workload_difference"]["columns"]))

    gesehen = {}
    for name in SUBGROUP_ORDER:
        if name not in unter:
            raise ValueError(f"Belastungsuntergruppe fehlt: {name}")
        for spalte in unter[name]:
            if spalte in gesehen:
                raise ValueError(
                    f"Spalte {spalte!r} steht in zwei Untergruppen: "
                    f"{gesehen[spalte]!r} und {name!r}")
            gesehen[spalte] = name

    fehlend = sorted(soll - set(gesehen))
    if fehlend:
        raise ValueError(
            f"Belastungsmerkmale ohne Untergruppe: {fehlend} - eine "
            f"Variante koennte behaupten, alle zu enthalten, und diese "
            f"auslassen")

    zuviel = sorted(set(gesehen) - soll)
    if zuviel:
        raise ValueError(
            f"Untergruppen nennen Spalten ausserhalb von workload, "
            f"workload_extra und workload_difference: {zuviel}")

    for name, mitglieder in SUBGROUP_BUNDLES.items():
        unbekannt = [m for m in mitglieder if m not in SUBGROUP_ORDER]
        if unbekannt:
            raise ValueError(
                f"Buendel {name!r} nennt unbekannte Untergruppen: "
                f"{unbekannt}")

    return {
        "subgroup_order": list(SUBGROUP_ORDER),
        "descriptions": dict(SUBGROUP_DESCRIPTIONS),
        "columns": {name: list(unter[name]) for name in SUBGROUP_ORDER},
        "counts": {name: len(unter[name]) for name in SUBGROUP_ORDER},
        "bundles": {name: list(mitglieder)
                    for name, mitglieder in sorted(SUBGROUP_BUNDLES.items())},
        "total_workload_features": len(soll),
    }


# ---------------------------------------------------------------------------
# Die Belastungsvarianten von V2-C3
# ---------------------------------------------------------------------------

#: Der unveraenderte V1-Kandidat. Er ist die Kontrollgruppe jeder
#: C3-Variante: Gemessen wird nicht "hilft Belastung", sondern "hilft
#: Belastung ZUSAETZLICH zu dem, was V1 schon kann".
C3_BASE_CANDIDATE = CL_PRIMARY_CANDIDATE

#: Der reduzierte Kandidat.
#:
#: Er steht hier als NAME, nicht als Merkmalsmenge: Welche Untergruppen
#: er traegt, entscheidet die Redundanz- und Nutzenpruefung auf den
#: TRAININGSDATEN - siehe cl_ablation.reduced_subgroups(). Eine hier
#: eingetragene Liste waere eine Vorwegnahme des Ergebnisses.
C3_REDUCED_CANDIDATE = "team_profile_cl_plus_reduced"


def _c3_variante(name, untergruppen, beschreibung):
    return {
        "name": name,
        "mode": MODE_FEATURES,
        "groups": ("profile",),
        "subgroups": tuple(untergruppen),
        "description": beschreibung,
    }


def c3_variants(reduced=()):
    """
    Alle Belastungsvarianten von V2-C3, in fester Reihenfolge.

    Die Liste ist VORAB festgelegt: der V1-Kandidat als Kontrolle, dann
    jede Untergruppe EINZELN, dann die drei fachlichen Buendel, zuletzt
    der reduzierte Kandidat.

    Genau diese Varianten werden gerechnet und ALLE berichtet - auch die
    erfolglosen. Eine nachtraegliche Auswahl unter ihnen waere die
    Ueberanpassung, die der Multiple-Testing-Teil ausschliessen soll.

    reduced: die Untergruppen des reduzierten Kandidaten, auf den
    TRAININGSDATEN bestimmt. Leer gelassen, entfaellt die Variante -
    ohne Vorauswahl gibt es nichts zu reduzieren.
    """
    varianten = [{
        "name": C3_BASE_CANDIDATE,
        "mode": MODE_FEATURES,
        "groups": ("profile",),
        "subgroups": (),
        "description": "der unveraenderte V1-Kandidat - die "
                       "Kontrollgruppe. Ohne ihn im selben Lauf waere "
                       "jede Verbesserung gegen eine Zahl aus einem "
                       "anderen Artefakt gemessen",
    }]

    for name in SUBGROUP_ORDER:
        varianten.append(_c3_variante(
            f"{C3_BASE_CANDIDATE}_plus_{name}", (name,),
            f"V1 zuzueglich {SUBGROUP_DESCRIPTIONS[name]}"))

    for buendel in ("recovery", "congestion_windows", "all_workload"):
        varianten.append(_c3_variante(
            f"{C3_BASE_CANDIDATE}_plus_{buendel}", SUBGROUP_BUNDLES[buendel],
            f"V1 zuzueglich des Buendels {buendel}: "
            + ", ".join(SUBGROUP_BUNDLES[buendel])))

    if reduced:
        varianten.append(_c3_variante(
            C3_REDUCED_CANDIDATE, tuple(reduced),
            "V1 zuzueglich der nach Redundanz- und Nutzenpruefung auf den "
            "TRAININGSDATEN verbliebenen Untergruppen: "
            + ", ".join(reduced)))

    return tuple(varianten)


C3_VARIANT_ORDER = tuple(v["name"] for v in c3_variants())


def columns_for_c3(definition, gruppen=None, spalten=None, unter=None):
    """
    Die Merkmalsspalten einer C3-Variante: Gruppen PLUS Untergruppen.

    Sortiert, wie columns_for() - die Koeffizientenpositionen haengen
    daran.
    """
    spalten = list(spalten if spalten is not None else mdl.feature_columns())
    gruppen = gruppen if gruppen is not None else build_groups(spalten)
    unter = unter if unter is not None else build_subgroups(spalten)
    validate_groups(gruppen, spalten)
    validate_subgroups(unter, gruppen, spalten)

    ausgewaehlt = []
    for name in definition["groups"]:
        if name not in GROUP_ORDER:
            raise ValueError(f"unbekannte Gruppe: {name!r}")
        ausgewaehlt.extend(gruppen[name]["columns"])
    for name in definition.get("subgroups", ()):
        if name not in SUBGROUP_ORDER:
            raise ValueError(
                f"unbekannte Belastungsuntergruppe: {name!r} - bekannt "
                f"sind {list(SUBGROUP_ORDER)}")
        ausgewaehlt.extend(unter[name])

    if len(set(ausgewaehlt)) != len(ausgewaehlt):
        raise ValueError(
            f"Variante {definition['name']!r} nennt eine Spalte doppelt")
    return sorted(ausgewaehlt)


# ---------------------------------------------------------------------------
# Formuntergruppen (V2-C4)
# ---------------------------------------------------------------------------

#: Die Formgruppen, feiner zerlegt - dieselbe Bauart wie bei den
#: Belastungsuntergruppen aus V2-C3 und aus demselben Grund: Eine
#: Ablation auf Gruppenebene koennte nur "alles oder nichts"
#: beantworten. Die Frage von V2-C4 lautet aber, WELCHE Formsicht
#: traegt - die allgemeine, die nationale, die europaeische oder die
#: ortsgebundene.
#:
#: Die Zerlegung ist eine echte Partition ueber form, form_opponent,
#: uefa und form_difference. validate_c4_subgroups() prueft das.
C4_SUBGROUP_ORDER = (
    "form_all_3", "form_all_5", "form_all_8",
    "form_domestic", "form_cl", "form_venue",
    "form_opponent", "uefa_club", "uefa_country", "form_difference",
)

#: Welche Formbetrachtungen (form.SCOPE_NAMES) in welche Untergruppe
#: gehen. Aus den Betrachtungsnamen abgeleitet, nicht abgetippt.
C4_SUBGROUP_SCOPES = {
    "form_all_3": ("all_3",),
    "form_all_5": ("all_5",),
    "form_all_8": ("all_8",),
    "form_domestic": ("domestic_5",),
    "form_cl": ("cl_5",),
    "form_venue": ("home_5", "away_5"),
}

C4_SUBGROUP_DESCRIPTIONS = {
    "form_all_3": "allgemeine Form der letzten 3 Partien "
                  "(wettbewerbsuebergreifend)",
    "form_all_5": "allgemeine Form der letzten 5 Partien",
    "form_all_8": "allgemeine Form der letzten 8 Partien",
    "form_domestic": "nationale Wettbewerbsform der letzten 5 Ligapartien - "
                     "ohne Pokale, deren Gegnerklasse die Aussage "
                     "verfaelschen wuerde",
    "form_cl": "Champions-League-Form der letzten 5 CL-Partien, ueber "
               "Saisongrenzen hinweg gepoolt",
    "form_venue": "Heimform und Auswaertsform getrennt, je letzte 5 "
                  "Partien am jeweiligen Ort",
    "form_opponent": "mittlere Staerke der zuletzt bespielten Gegner und "
                     "die daran gewichtete Punktequote",
    "uefa_club": "UEFA-Vereinskoeffizient und -Rang der Vorsaison",
    "uefa_country": "abgeleitete Landesstaerke aus den Top-40-Klubs "
                    "desselben Landes - ausdruecklich KEIN "
                    "Verbandskoeffizient",
    "form_difference": "Formdifferenz Heim minus Auswaerts",
}

#: Fachlich begruendete Buendel, vorab festgelegt.
C4_SUBGROUP_BUNDLES = {
    "form_windows": ("form_all_3", "form_all_5", "form_all_8"),
    "form_competition_split": ("form_domestic", "form_cl"),
    "uefa_all": ("uefa_club", "uefa_country"),
    "all_form": tuple(C4_SUBGROUP_ORDER),
}


def build_c4_subgroups(spalten=None):
    """Die Formuntergruppen als Spaltenmengen."""
    spalten = set(spalten if spalten is not None else mdl.feature_columns())

    unter = {}
    for name in C4_SUBGROUP_ORDER:
        if name in C4_SUBGROUP_SCOPES:
            felder = tuple(f"{scope}_{metrik}"
                           for scope in C4_SUBGROUP_SCOPES[name]
                           for metrik in ds.FORM_METRICS)
            roh = _seitenspalten(felder)
        elif name == "form_opponent":
            roh = _seitenspalten(ds.FORM_OPPONENT_FELDER)
        elif name == "uefa_club":
            roh = _seitenspalten(("uefa_club_coefficient", "uefa_club_rank"))
        elif name == "uefa_country":
            roh = _seitenspalten(("uefa_country_top40_strength",))
        elif name == "form_difference":
            roh = tuple(ds._formdiffspaltenname(feld)
                        for feld in ds.FORM_DIFF_FELDER)
        else:                                            # pragma: no cover
            raise ValueError(f"unbekannte Formuntergruppe: {name!r}")
        unter[name] = tuple(sorted(sp for sp in roh if sp in spalten))
    return unter


def validate_c4_subgroups(unter=None, gruppen=None, spalten=None):
    """
    Die Formuntergruppen muessen form, form_opponent, uefa und
    form_difference vollstaendig und ueberschneidungsfrei zerlegen.
    """
    spalten = list(spalten if spalten is not None else mdl.feature_columns())
    gruppen = gruppen if gruppen is not None else build_groups(spalten)
    unter = unter if unter is not None else build_c4_subgroups(spalten)

    soll = set()
    for name in ("form", "form_opponent", "uefa", "form_difference"):
        soll |= set(gruppen[name]["columns"])

    gesehen = {}
    for name in C4_SUBGROUP_ORDER:
        if name not in unter:
            raise ValueError(f"Formuntergruppe fehlt: {name}")
        for spalte in unter[name]:
            if spalte in gesehen:
                raise ValueError(
                    f"Spalte {spalte!r} steht in zwei Formuntergruppen: "
                    f"{gesehen[spalte]!r} und {name!r}")
            gesehen[spalte] = name

    fehlend = sorted(soll - set(gesehen))
    if fehlend:
        raise ValueError(
            f"Formmerkmale ohne Untergruppe: {fehlend} - eine Variante "
            f"koennte behaupten, alle zu enthalten, und diese auslassen")

    zuviel = sorted(set(gesehen) - soll)
    if zuviel:
        raise ValueError(
            f"Formuntergruppen nennen Spalten ausserhalb ihrer Gruppen: "
            f"{zuviel}")

    for name, mitglieder in C4_SUBGROUP_BUNDLES.items():
        unbekannt = [m for m in mitglieder if m not in C4_SUBGROUP_ORDER]
        if unbekannt:
            raise ValueError(
                f"Buendel {name!r} nennt unbekannte Untergruppen: {unbekannt}")

    return {
        "subgroup_order": list(C4_SUBGROUP_ORDER),
        "descriptions": dict(C4_SUBGROUP_DESCRIPTIONS),
        "columns": {name: list(unter[name]) for name in C4_SUBGROUP_ORDER},
        "counts": {name: len(unter[name]) for name in C4_SUBGROUP_ORDER},
        "bundles": {name: list(m)
                    for name, m in sorted(C4_SUBGROUP_BUNDLES.items())},
        "total_form_features": len(soll),
    }


#: Der reduzierte C4-Kandidat. Wie in V2-C3 steht hier nur der NAME:
#: Welche Untergruppen er traegt, entscheidet die Redundanz- und
#: Nutzenpruefung auf den Trainingsdaten.
C4_REDUCED_CANDIDATE = "team_profile_cl_plus_form_reduced"


def c4_variants(reduced=()):
    """
    Alle Formvarianten von V2-C4, in fester Reihenfolge.

    VORAB festgelegt: der V1-Kandidat als Kontrolle, dann jede
    Untergruppe EINZELN, dann die vier fachlichen Buendel, zuletzt der
    reduzierte Kandidat. Alle werden gerechnet und alle berichtet.
    """
    varianten = [{
        "name": C3_BASE_CANDIDATE,
        "mode": MODE_FEATURES,
        "groups": ("profile",),
        "subgroups": (),
        "description": "der unveraenderte V1-Kandidat - die "
                       "Kontrollgruppe. Ohne ihn im selben Lauf waere "
                       "jede Verbesserung gegen eine Zahl aus einem "
                       "anderen Artefakt gemessen",
    }]

    for name in C4_SUBGROUP_ORDER:
        varianten.append(_c3_variante(
            f"{C3_BASE_CANDIDATE}_plus_{name}", (name,),
            f"V1 zuzueglich {C4_SUBGROUP_DESCRIPTIONS[name]}"))

    for buendel in ("form_windows", "form_competition_split", "uefa_all",
                    "all_form"):
        varianten.append(_c3_variante(
            f"{C3_BASE_CANDIDATE}_plus_{buendel}",
            C4_SUBGROUP_BUNDLES[buendel],
            f"V1 zuzueglich des Buendels {buendel}: "
            + ", ".join(C4_SUBGROUP_BUNDLES[buendel])))

    if reduced:
        varianten.append(_c3_variante(
            C4_REDUCED_CANDIDATE, tuple(reduced),
            "V1 zuzueglich der nach Redundanz- und Nutzenpruefung auf den "
            "TRAININGSDATEN verbliebenen Formuntergruppen: "
            + ", ".join(reduced)))

    return tuple(varianten)


C4_VARIANT_ORDER = tuple(v["name"] for v in c4_variants())


def columns_for_c4(definition, gruppen=None, spalten=None, unter=None):
    """
    Die Merkmalsspalten einer C4-Variante: Gruppen PLUS Formuntergruppen.

    Getrennt von columns_for_c3, weil die Untergruppennamen aus zwei
    verschiedenen Registern stammen. Ein gemeinsamer Namensraum waere
    bequemer und genau deshalb gefaehrlich: Ein Tippfehler koennte
    stillschweigend die Untergruppe des anderen Blocks treffen.
    """
    spalten = list(spalten if spalten is not None else mdl.feature_columns())
    gruppen = gruppen if gruppen is not None else build_groups(spalten)
    unter = unter if unter is not None else build_c4_subgroups(spalten)
    validate_groups(gruppen, spalten)
    validate_c4_subgroups(unter, gruppen, spalten)

    ausgewaehlt = []
    for name in definition["groups"]:
        if name not in GROUP_ORDER:
            raise ValueError(f"unbekannte Gruppe: {name!r}")
        ausgewaehlt.extend(gruppen[name]["columns"])
    for name in definition.get("subgroups", ()):
        if name not in C4_SUBGROUP_ORDER:
            raise ValueError(
                f"unbekannte Formuntergruppe: {name!r} - bekannt sind "
                f"{list(C4_SUBGROUP_ORDER)}")
        ausgewaehlt.extend(unter[name])

    if len(set(ausgewaehlt)) != len(ausgewaehlt):
        raise ValueError(
            f"Variante {definition['name']!r} nennt eine Spalte doppelt")
    return sorted(ausgewaehlt)


def all_variants():
    """
    Alle bekannten Varianten beider Stufen.

    Bewusst eine Funktion und kein eingefrorenes Modultupel: Ein zur
    Ladezeit gebautes ALL_VARIANTS wuerde eine spaetere Ersetzung von
    VARIANTS - etwa im Test - stillschweigend ignorieren und dabei
    vorgeben, weiterhin den gueltigen Stand zu kennen.
    """
    return tuple(VARIANTS) + tuple(DIAGNOSTIC_VARIANTS) + tuple(CL_VARIANTS)


def check_variant_consistency(varianten=None):
    """
    Ein Variantenname darf nicht zwei Bedeutungen haben.

    profile_only und all_existing_features stehen in beiden Saetzen.
    Sie muessen dort exakt dieselbe Merkmalsmenge und dieselbe
    Betriebsart bezeichnen - sonst waeren die Zahlen der beiden
    Artefakte nicht vergleichbar, und genau darauf beruht der Anschluss
    der zweiten Stufe an die erste.

    Rueckgabe: {name: definition}. Wirft ValueError bei Widerspruch.
    """
    nach_name = {}
    for eintrag in (varianten if varianten is not None else all_variants()):
        vorher = nach_name.get(eintrag["name"])
        if vorher is not None and (
                tuple(vorher["groups"]) != tuple(eintrag["groups"])
                or vorher.get("mode") != eintrag.get("mode")):
            raise ValueError(
                f"die Variante {eintrag['name']!r} ist zweimal verschieden "
                f"definiert: {tuple(vorher['groups'])}/{vorher.get('mode')} "
                f"gegen {tuple(eintrag['groups'])}/{eintrag.get('mode')}")
        nach_name[eintrag["name"]] = eintrag
    return nach_name


def variant(name):
    """Die Variantendefinition - oder ein Abbruch bei unbekanntem Namen."""
    varianten = all_variants()
    for eintrag in varianten:
        if eintrag["name"] == name:
            return eintrag
    bekannt = sorted({e["name"] for e in varianten})
    raise ValueError(
        f"unbekannte Ablationsvariante: {name!r} - bekannt sind {bekannt}")


def columns_for(name, gruppen=None, spalten=None):
    """
    Die Merkmalsspalten einer Variante.

    Sortiert und ueber Laeufe stabil - dieselbe Zusage wie
    model.feature_columns(), aus demselben Grund: Die
    Koeffizientenpositionen haengen daran.

    no_correction liefert eine LEERE Liste. Das ist kein Randfall,
    sondern der Weg, auf dem die Kontrolle ohne eigenen Codepfad
    auskommt: Ohne Merkmale gibt es nichts anzupassen, und
    evaluate_fold faellt ueber select_candidate von selbst auf
    model.NO_CORRECTION zurueck.
    """
    definition = variant(name)
    spalten = list(spalten if spalten is not None else mdl.feature_columns())
    gruppen = gruppen if gruppen is not None else build_groups(spalten)
    validate_groups(gruppen, spalten)

    ausgewaehlt = []
    for gruppenname in definition["groups"]:
        if gruppenname not in GROUP_ORDER:
            raise ValueError(
                f"Variante {name!r} nennt die unbekannte Gruppe "
                f"{gruppenname!r} - bekannt sind {list(GROUP_ORDER)}")
        ausgewaehlt.extend(gruppen[gruppenname]["columns"])

    return sorted(ausgewaehlt)
