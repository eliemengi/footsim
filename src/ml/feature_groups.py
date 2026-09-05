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
SCHEMA_VERSION = 1

#: Beide Seiten tragen dieselben Merkmale. Dieselbe Reihenfolge wie in
#: dataset.build_schema().
SEITEN = ("home", "away")

#: Die Gruppen in fester Reihenfolge. Sie ist zugleich die
#: Berichtsreihenfolge.
GROUP_ORDER = ("profile", "profile_depth", "league_average", "workload",
               "schedule_strength")

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
                "(workload.workload_features)",
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
