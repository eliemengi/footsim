"""
Der Early-V2-Vertrag (V2-C9).

WOZU DIESE DATEI EXISTIERT
--------------------------
C0 bis C8 haben 130 Modellmerkmale in 13 Familien gebaut, gemessen und
groesstenteils NICHT aufgenommen. Diese Information lag danach verteilt
in sechs Ablationsartefakten, mehreren Registries und einem
README-Abschnitt. Wer C10 baut, muesste sie erneut zusammensuchen - und
wuerde dabei zwangslaeufig Entscheidungen neu erfinden.

C9 fuehrt sie an EINER Stelle zusammen und trennt dabei vier Ebenen,
die bisher gedanklich verschwommen sind:

    1. was roh verfuegbar ist
    2. was sich technisch berechnen laesst
    3. was statistisch geprueft wurde
    4. was der finale Kandidat tatsaechlich benutzt

Ein Merkmal gelangt NICHT in Ebene 4, nur weil es Ebene 2 erreicht hat.
Genau das ist die Aussage dieser Datei, und sie ist maschinell
geprueft: selected_columns() faellt hart aus, sobald eine Familie mit
einem anderen Status als SELECTED hineinragt.

WAS HIER NICHT PASSIERT
-----------------------
Kein Training, keine Modellwahl, keine neue Ablation. C9 waehlt nichts
aus - es schreibt auf, was C3 bis C8 bereits entschieden haben, und
macht diese Entscheidungen pruefbar. Der ausgewaehlte Kandidat bleibt
V1 (team_profile_cl, 16 Merkmale), weil kein spaeterer Block etwas
anderes akzeptiert hat.

KEINE ZWEITE MERKMALSLISTE
--------------------------
Die Merkmalsnamen kommen ausnahmslos aus feature_groups.build_groups().
Diese Datei fuegt METADATEN hinzu, niemals Namen. Waere es anders,
gaebe es zwei Listen, die auseinanderlaufen koennen - und die zweite
wuerde irgendwann gewinnen, ohne dass es jemand bemerkt. Ein Test
haelt fest, dass jede Familie aus GROUP_ORDER hier einen Eintrag hat
und umgekehrt.
"""

import hashlib
import json

from src.ml import cl_evaluate as ce
from src.ml import dataset as ds
from src.ml import feature_groups as fg
from src.ml import model as mdl
from src.ml import persist as ps

#: Fassung des C9-Vertrags.
C9_VERSION = 1

#: Fassung des Registryformats.
REGISTRY_SCHEMA_VERSION = 1

#: Wohin das C9-Manifest gehoert.
MANIFEST_PATH = "data/ml/c9_early_v2_manifest_2023-2025.json"


# ---------------------------------------------------------------------------
# Statuswerte
# ---------------------------------------------------------------------------

#: In den finalen Kandidaten aufgenommen.
STATUS_SELECTED = "SELECTED"

#: Technisch fertig, PIT-sicher, gemessen - aber nicht aufgenommen.
#: Darf im Forschungsdatensatz stehen.
STATUS_EXPERIMENTAL = "EXPERIMENTAL"

#: Gemessen und verworfen: schlechter als die Kontrolle.
STATUS_REJECTED = "REJECTED"

#: Gemessen, Richtung stimmt, aber das Intervall schliesst die Null
#: nicht aus. Kein Beleg - und ein fehlender Beleg ist kein Beleg.
STATUS_INCONCLUSIVE = "INCONCLUSIVE"

#: Mangels Historie nicht bewertbar. Keine Metriken, mit Beweis.
STATUS_NOT_EVALUABLE = "NOT_EVALUABLE"

#: Infrastruktur ohne eigenes Merkmal (Sammler, Archiv, Crosswalk).
STATUS_INFRASTRUCTURE_ONLY = "INFRASTRUCTURE_ONLY"

#: Vergleichsmassstab, kein frei gewichtetes Merkmal.
STATUS_BASELINE_ONLY = "BASELINE_ONLY"

#: Genau diese sieben. Ein achter Wert waere ein neu erfundener Status
#: und macht jede Auswertung ueber die Bloecke hinweg unvergleichbar.
STATUSES = (STATUS_SELECTED, STATUS_EXPERIMENTAL, STATUS_REJECTED,
            STATUS_INCONCLUSIVE, STATUS_NOT_EVALUABLE,
            STATUS_INFRASTRUCTURE_ONLY, STATUS_BASELINE_ONLY)

#: Welche Status ein Merkmal in den finalen Kandidaten lassen.
#:
#: Nur einer. Die Liste steht hier als Konstante und nicht als
#: `== STATUS_SELECTED` im Code, damit eine spaetere Lockerung eine
#: sichtbare Aenderung an einer benannten Stelle ist und nicht eine
#: beilaeufige Bedingung in einer Schleife.
STATUSES_ALLOWED_IN_SELECTED = (STATUS_SELECTED,)

#: Welche Status im Forschungsdatensatz erscheinen duerfen.
#:
#: Auch REJECTED und INCONCLUSIVE - der Forschungsdatensatz ist zum
#: Weiterforschen da, und ein verworfenes Merkmal spaeter erneut
#: pruefen zu koennen ist sein Zweck. Nicht dabei: was gar kein
#: Merkmal ist (Infrastruktur, Baseline) und was nie beobachtet wurde
#: (NOT_EVALUABLE) - eine Spalte ohne Beobachtung ist keine Forschung,
#: sondern eine Spalte voller None.
STATUSES_ALLOWED_IN_RESEARCH = (STATUS_SELECTED, STATUS_EXPERIMENTAL,
                                STATUS_REJECTED, STATUS_INCONCLUSIVE)


# ---------------------------------------------------------------------------
# Point-in-Time-Klassen
# ---------------------------------------------------------------------------

#: Rueckwirkend rekonstruierbar: datierte Ereignisse, abgeschlossene
#: Zeitraeume. Fuer jede historische Partie berechenbar.
PIT_HISTORICAL = "historical_reconstructible"

#: Erst ab dem Sammelbeginn beobachtbar (V2-C6). Fuer eine Partie vor
#: dem ersten Snapshot gibt es keinen Wert - und darf keiner erfunden
#: werden.
PIT_SNAPSHOT_ONLY = "snapshot_only"

#: Kein Zeitbezug noetig: strukturelle Eigenschaft der Partie selbst.
PIT_STRUCTURAL = "structural"

PIT_CLASSES = (PIT_HISTORICAL, PIT_SNAPSHOT_ONLY, PIT_STRUCTURAL)


# ---------------------------------------------------------------------------
# Die Familienregistry
# ---------------------------------------------------------------------------

#: Eine Familie je Eintrag - Status, Herkunft, Zeitklasse, Begruendung.
#:
#: Die Reihenfolge folgt feature_groups.GROUP_ORDER und ist damit
#: dieselbe wie ueberall sonst. Die Schluessel sind die Gruppennamen;
#: ein Eintrag ohne Gruppe oder eine Gruppe ohne Eintrag laesst
#: validate_registry() hart fehlschlagen.
#:
#: "evidence" nennt das Artefakt, das die Entscheidung traegt. Ohne
#: diesen Verweis waere der Status eine Behauptung.
FAMILY_REGISTRY = {
    "profile": {
        "block": "C0/C2",
        "status": STATUS_SELECTED,
        "pit_class": PIT_HISTORICAL,
        "source": "data/historical - team_profile.build_season_profiles",
        "tracked": True,
        "runtime_available": True,
        "reason": ("Der einzige Merkmalssatz, der in einer Ablation "
                   "einen Gewinn mit Intervall unter null gezeigt hat. "
                   "Er IST der V1-Kandidat."),
        "evidence": "data/ml/ablation_2023-2025.json",
        "since_version": 1,
    },
    "profile_depth": {
        "block": "C2",
        "status": STATUS_REJECTED,
        "pit_class": PIT_HISTORICAL,
        "source": "data/historical - Zahl der genutzten Partien",
        "tracked": True,
        "runtime_available": True,
        "reason": ("matches_used beschreibt die QUELLE, nicht die "
                   "Mannschaft. Im Ligatraining 5..37, im geblendeten "
                   "CL-Stand 33..114 - das Modell lernte daran die "
                   "Herkunft der Zeile. Weglassen verbesserte die "
                   "Messung (-0,01376 auf -0,01615)."),
        "evidence": "data/ml/ablation_diagnostics_2023-2025.json",
        "since_version": 1,
    },
    "league_average": {
        "block": "C0/C2",
        "status": STATUS_EXPERIMENTAL,
        "pit_class": PIT_HISTORICAL,
        "source": "data/historical - derselbe Aufruf wie die Profile",
        "tracked": True,
        "runtime_available": True,
        "reason": ("Steckt bereits in der Baseline-Lambda-Rechnung. Als "
                   "zusaetzliches freies Merkmal brachte es in Stufe 2 "
                   "nichts, was team_profile_only nicht schon hatte."),
        "evidence": "data/ml/ablation_diagnostics_2023-2025.json",
        "since_version": 1,
    },
    "workload": {
        "block": "C3",
        "status": STATUS_REJECTED,
        "pit_class": PIT_HISTORICAL,
        "source": "match_timeline - workload.workload_features",
        "tracked": True,
        "runtime_available": True,
        "reason": ("Zwoelf von zwoelf Belastungsmerkmalen erwiesen sich "
                   "auf CL-Partien als konstant oder uninformativ; 19 "
                   "von 27 Spalten waren exakt kollinear. Die Variante "
                   "workload_only trug in der ersten Stufe nichts bei."),
        "evidence": "data/ml/c3_workload_ablation_2023-2025.json",
        "since_version": 2,
    },
    "workload_extra": {
        "block": "C3",
        "status": STATUS_REJECTED,
        "pit_class": PIT_HISTORICAL,
        "source": "match_timeline - workload.extra_time_minutes",
        "tracked": True,
        "runtime_available": True,
        "reason": ("extra_time_minutes ist exakt 30 x "
                   "extra_time_matches - per Konstruktion redundant. In "
                   "der Ligaphase gibt es keine Verlaengerung, also ist "
                   "das Merkmal dort konstant null."),
        "evidence": "data/ml/c3_workload_ablation_2023-2025.json",
        "since_version": 2,
    },
    "workload_difference": {
        "block": "C3",
        "status": STATUS_REJECTED,
        "pit_class": PIT_HISTORICAL,
        "source": "dataset.workload_difference_values",
        "tracked": True,
        "runtime_available": True,
        "reason": ("Rechnerisch keine neue Information gegenueber "
                   "workload - dieselbe Groesse vorzeichensymmetrisch "
                   "dargestellt. Faellt mit workload."),
        "evidence": "data/ml/c3_workload_ablation_2023-2025.json",
        "since_version": 2,
    },
    "schedule_strength": {
        "block": "C3",
        "status": STATUS_REJECTED,
        "pit_class": PIT_HISTORICAL,
        "source": "match_timeline - workload.schedule_strength",
        "tracked": True,
        "runtime_available": True,
        "reason": ("Teil der C3-Belastungsablation; kein Arm erreichte "
                   "ein Intervall unter null."),
        "evidence": "data/ml/c3_workload_ablation_2023-2025.json",
        "since_version": 2,
    },
    "form": {
        "block": "C4",
        "status": STATUS_INCONCLUSIVE,
        "pit_class": PIT_HISTORICAL,
        "source": "match_timeline - form.form_features",
        "tracked": True,
        "runtime_available": True,
        "reason": ("Richtung stimmt, kein Intervall schliesst die Null "
                   "aus. Ein fehlender Beleg ist kein Beleg."),
        "evidence": "data/ml/c4_form_ablation_2023-2025.json",
        "since_version": 3,
    },
    "form_opponent": {
        "block": "C4",
        "status": STATUS_INCONCLUSIVE,
        "pit_class": PIT_HISTORICAL,
        "source": "form.opponent_values mit PitStrengthAtDate",
        "tracked": True,
        "runtime_available": True,
        "reason": ("Wie form. Die Gegnerstaerke gilt zum Zeitpunkt der "
                   "DAMALIGEN Partie - PIT-sauber, aber ohne Beleg."),
        "evidence": "data/ml/c4_form_ablation_2023-2025.json",
        "since_version": 3,
    },
    "uefa": {
        "block": "C4",
        "status": STATUS_EXPERIMENTAL,
        "pit_class": PIT_HISTORICAL,
        "source": ("data/big_games/uefa_coefficients (GITIGNORIERT) - "
                   "uefa_strength.uefa_values"),
        "tracked": False,
        "runtime_available": False,
        "reason": ("Kein Intervall unter null. Zusaetzlich liegt die "
                   "Quelle ausserhalb der Versionsverwaltung: Der "
                   "Standardbau liest sie nicht "
                   "(INCLUDE_UEFA_BY_DEFAULT = False), damit ein "
                   "frischer Checkout denselben Datensatz erzeugt."),
        "evidence": "data/ml/c4_form_ablation_2023-2025.json",
        "since_version": 3,
    },
    "form_difference": {
        "block": "C4",
        "status": STATUS_INCONCLUSIVE,
        "pit_class": PIT_HISTORICAL,
        "source": "dataset.form_difference_values",
        "tracked": True,
        "runtime_available": True,
        "reason": "Wie form - abgeleitete Darstellung derselben Groessen.",
        "evidence": "data/ml/c4_form_ablation_2023-2025.json",
        "since_version": 3,
    },
    "match_context": {
        "block": "C5",
        "status": STATUS_REJECTED,
        "pit_class": PIT_STRUCTURAL,
        "source": "data/historical - match_context.context_values",
        "tracked": True,
        "runtime_available": True,
        "reason": ("Im Standardvertrag sind alle zwoelf Merkmale "
                   "konstant. Unter dem Kontextvertrag messbar, aber "
                   "deutlich schlechter als die Kontrolle desselben "
                   "Vertrags (+0,0234 gegenueber -0,0098). C8 hat "
                   "zusaetzlich geprueft, ob die Imputation schuld ist: "
                   "Die definitorische Null hilft, aber nur um "
                   "-0,00065. Die Merkmale sind das Problem."),
        "evidence": ("data/ml/c5_context_ablation_2023-2025.json, "
                     "data/ml/c8_model_class_ablation_2023-2025.json"),
        "since_version": 4,
    },
    "squad_history": {
        "block": "C7",
        "status": STATUS_INCONCLUSIVE,
        "pit_class": PIT_HISTORICAL,
        "source": ("data/cache + data/player_pool (GITIGNORIERT) - "
                   "squad_history.squad_history_values"),
        "tracked": False,
        "runtime_available": False,
        "reason": ("Erstmals zeigten ALLE Varianten in die richtige "
                   "Richtung, aber kein Intervall schloss die Null aus "
                   "und die Kalibrierung verschlechterte sich "
                   "durchgehend. C8 pruefte zusaetzlich eine "
                   "Transformation der Zaehlwerte - sie verschlechterte "
                   "das Ergebnis. Der Standardbau liest die Quellen "
                   "nicht (INCLUDE_SQUAD_HISTORY_BY_DEFAULT = False)."),
        "evidence": ("data/ml/c7_squad_history_ablation_2023-2025.json, "
                     "data/ml/c8_model_class_ablation_2023-2025.json"),
        "since_version": 5,
    },
}


#: Bausteine ohne eigene Merkmalsspalte.
#:
#: Sie gehoeren ins Inventar, aber nicht in die Merkmalsregistry - eine
#: Spalte haben sie nicht. Sie hier zu fuehren ist der Unterschied
#: zwischen "wurde nicht gebaut" und "wurde gebaut und traegt kein
#: Merkmal".
NON_FEATURE_COMPONENTS = {
    "baseline_lambda": {
        "block": "C0",
        "status": STATUS_BASELINE_ONLY,
        "what": ("Poisson-Erwartungswerte je Seite aus Profil und "
                 "Ligaschnitt. Grundlage des Offsettricks - Ziel ist "
                 "tore / baseline_lambda, Gewicht ist baseline_lambda."),
        "why_not_a_feature": ("Der Vergleichsmassstab kann nicht "
                              "zugleich ein frei gewichtetes Merkmal "
                              "sein. Das Modell korrigiert ihn, es "
                              "lernt ihn nicht."),
    },
    "team_crosswalk": {
        "block": "C2B/C7",
        "status": STATUS_INFRASTRUCTURE_ONLY,
        "what": ("Bruecke zwischen football-data- und "
                 "API-Sports-Kennungen (squad_crosswalk, "
                 "team_crosswalk). 63 von 63 CL-Vereinen aufgeloest, "
                 "0 Widersprueche."),
        "why_not_a_feature": ("Eine Identitaetszuordnung ist kein "
                              "Merkmal. Ein Widerspruch ENTFERNT den "
                              "Eintrag, statt ihn zu ueberschreiben."),
    },
    "snapshot_infrastructure": {
        "block": "C6",
        "status": STATUS_INFRASTRUCTURE_ONLY,
        "what": ("Sammler, Archiv, Leser und systemd-Einheiten fuer "
                 "Kader- und Verfuegbarkeitssnapshots "
                 "(snapshot_collector, snapshot_archive, "
                 "snapshot_reader, deploy/systemd)."),
        "why_not_a_feature": ("C6 sammelt. Der Timer ist vorbereitet "
                              "und ausdruecklich NICHT aktiviert."),
    },
    "squad_snapshot": {
        "block": "C6/C7",
        "status": STATUS_NOT_EVALUABLE,
        "what": "Kadergroesse und -zusammensetzung zum Stichtag.",
        "why_not_a_feature": ("0 Kadersnapshots im Archiv. Eine Zahl "
                              "ohne Beobachtung waere schlimmer als "
                              "eine Luecke, weil sie wie ein Ergebnis "
                              "aussieht."),
    },
    "availability_impact": {
        "block": "C6/C7",
        "status": STATUS_NOT_EVALUABLE,
        "what": "Ausfaelle, Sperren und deren Gewicht zum Stichtag.",
        "why_not_a_feature": ("Der einzige Verfuegbarkeitssnapshot ist "
                              "juenger als JEDE auszuwertende Partie. "
                              "Jede Beobachtung laege nach dem "
                              "Stichtag, den sie erklaeren soll."),
    },
    "model_class_extension": {
        "block": "C8",
        "status": STATUS_REJECTED,
        "what": ("Transformationen (log1p, signed log1p), vier "
                 "begruendete Interaktionen, zwei "
                 "Kalibrierungsverfahren, staerkere Regularisierung "
                 "(model_class.py)."),
        "why_not_a_feature": ("Kein Kandidat bestand das Gate. Die "
                              "Transformation verschlechterte das "
                              "Ergebnis, die Kalibrierung erreichte V1 "
                              "nicht. Der Code bleibt vorhanden und "
                              "getestet, aber unbenutzt: "
                              "build_pipeline(alpha) ohne Transform "
                              "liefert unveraendert die V1-Schrittfolge."),
    },
}


# ---------------------------------------------------------------------------
# Validierung
# ---------------------------------------------------------------------------

def validate_registry(gruppen=None):
    """
    Die Registry gegen die tatsaechlichen Merkmalsgruppen pruefen.

    Bricht ab bei:
      - einer Gruppe ohne Registryeintrag
      - einem Registryeintrag ohne Gruppe
      - einem unbekannten Status
      - einer unbekannten Zeitklasse
      - einem Eintrag ohne Begruendung oder ohne Evidenzverweis

    Das ist der Kern des C9-Versprechens. Eine Familie, die hier
    durchrutscht, waere eine Familie ohne dokumentierte Entscheidung -
    und genau die wuerde spaeter versehentlich mitgenommen.
    """
    gruppen = gruppen if gruppen is not None else fg.build_groups()

    fehlend = [g for g in fg.GROUP_ORDER if g not in FAMILY_REGISTRY]
    if fehlend:
        raise ValueError(
            f"Merkmalsgruppen ohne C9-Registryeintrag: {fehlend}. Jede "
            f"Gruppe braucht einen Status, sonst gelangt sie ohne "
            f"dokumentierte Entscheidung in einen Datensatz.")

    ueberzaehlig = [g for g in FAMILY_REGISTRY if g not in fg.GROUP_ORDER]
    if ueberzaehlig:
        raise ValueError(
            f"C9-Registryeintraege ohne Merkmalsgruppe: {ueberzaehlig}. "
            f"Ein Eintrag ohne Gruppe ist eine zweite, abweichende "
            f"Merkmalsliste.")

    for name, eintrag in sorted(FAMILY_REGISTRY.items()):
        if eintrag["status"] not in STATUSES:
            raise ValueError(
                f"Familie {name!r} traegt den unbekannten Status "
                f"{eintrag['status']!r} - erlaubt sind {list(STATUSES)}")
        if eintrag["pit_class"] not in PIT_CLASSES:
            raise ValueError(
                f"Familie {name!r} traegt die unbekannte Zeitklasse "
                f"{eintrag['pit_class']!r}")
        if not eintrag.get("reason", "").strip():
            raise ValueError(
                f"Familie {name!r} hat keine Begruendung - ein Status "
                f"ohne Begruendung ist eine Behauptung")
        if not eintrag.get("evidence", "").strip():
            raise ValueError(
                f"Familie {name!r} nennt kein Artefakt als Beleg")

    for name, eintrag in sorted(NON_FEATURE_COMPONENTS.items()):
        if eintrag["status"] not in STATUSES:
            raise ValueError(
                f"Baustein {name!r} traegt den unbekannten Status "
                f"{eintrag['status']!r}")
        if name in FAMILY_REGISTRY:
            raise ValueError(
                f"{name!r} steht in beiden Registries - ein Baustein "
                f"ist entweder eine Merkmalsfamilie oder keine")

    return True


def feature_registry(gruppen=None, spalten=None):
    """
    Ein Eintrag je MERKMAL - die eine Wahrheitsquelle.

    Die Namen kommen ausschliesslich aus feature_groups.build_groups().
    Diese Funktion erfindet keinen Namen; sie reichert an.

    Rueckgabe: Liste von dicts in DETERMINISTISCHER Reihenfolge -
    Familien in GROUP_ORDER, darin die Spalten sortiert. Die
    Koeffizientenpositionen haengen an dieser Reihenfolge, also darf sie
    nicht von einer Mengeniteration abhaengen.
    """
    spalten = list(spalten if spalten is not None else mdl.feature_columns())
    gruppen = gruppen if gruppen is not None else fg.build_groups(spalten)
    validate_registry(gruppen)

    ausgewaehlt = set(selected_columns(gruppen, spalten))

    untergruppen = _untergruppen_index(spalten)

    eintraege = []
    gesehen = {}
    for familie in fg.GROUP_ORDER:
        meta = FAMILY_REGISTRY[familie]
        for spalte in sorted(gruppen[familie]["columns"]):
            if spalte in gesehen:
                raise ValueError(
                    f"Merkmal {spalte!r} steht in zwei Familien: "
                    f"{gesehen[spalte]!r} und {familie!r}. Ein Merkmal "
                    f"mit zwei Familien haette zwei Status.")
            gesehen[spalte] = familie
            eintraege.append({
                "name": spalte,
                "family": familie,
                "subgroup": untergruppen.get(spalte),
                "side": _seite(spalte),
                "block": meta["block"],
                "pit_class": meta["pit_class"],
                "source": meta["source"],
                "tracked_source": meta["tracked"],
                "runtime_available": meta["runtime_available"],
                "status": meta["status"],
                "in_selected": spalte in ausgewaehlt,
                "in_research": (meta["status"]
                                in STATUSES_ALLOWED_IN_RESEARCH),
                "since_version": meta["since_version"],
                "missingness": _missingness(familie, spalte),
            })
    return eintraege


def _seite(spalte):
    """
    Zu welcher Mannschaft ein Merkmal gehoert.

    match_context ist die Ausnahme: Ob eine Partie ein Rueckspiel ist,
    ist eine Eigenschaft des SPIELS. Ein home_-Praefix taeuschte dort
    eine Zugehoerigkeit vor, die es nicht gibt.
    """
    if spalte.startswith("home_"):
        return "home"
    if spalte.startswith("away_"):
        return "away"
    return "match"





def _untergruppen_index(spalten=None):
    """
    {spalte: untergruppe} ueber alle vier Untergruppenebenen.

    Einmal gebaut statt je Spalte gesucht: feature_registry() fragt
    130-mal, und vier verschachtelte Schleifen je Frage waeren
    quadratisch ohne Anlass.

    Die erste Ebene, die eine Spalte kennt, gewinnt. Die vier Ebenen
    zerlegen verschiedene Familien und ueberschneiden sich daher nicht;
    faenden sie es doch, waere die frueheste Definition die aeltere und
    damit die, auf die sich bestehende Artefakte beziehen.
    """
    index = {}
    for bauer in (getattr(fg, "build_subgroups", None),
                  getattr(fg, "build_c4_subgroups", None),
                  getattr(fg, "build_c5_subgroups", None),
                  getattr(fg, "build_c7_subgroups", None)):
        if bauer is None:                                # pragma: no cover
            continue
        for name, eintrag in bauer(spalten).items():
            # Die vier Bauer liefern unterschiedliche Formen: C3 gibt
            # ein Tupel von Spalten, die spaeteren ein dict mit
            # "columns". Beides hier zu behandeln ist ehrlicher, als
            # eine der Fassungen umzuschreiben - sie sind Teil des
            # bestehenden, getesteten Vertrags ihrer Bloecke.
            spalten_der_gruppe = (eintrag["columns"]
                                  if isinstance(eintrag, dict) else eintrag)
            for spalte in spalten_der_gruppe:
                index.setdefault(spalte, name)
    return index


#: Wie ein fehlender Wert je Familie zu lesen ist.
#:
#: Das ist keine Formalie. In C5 bedeutete ein fehlender Aggregatstand
#: "diese Partie hat definitionsgemaess keinen" - der Medianimputer
#: machte daraus eine Zahl. Wer die Semantik nicht mitschreibt, kann
#: den Unterschied spaeter nicht mehr sehen.
MISSINGNESS_UNKNOWN = "unknown"
MISSINGNESS_NOT_APPLICABLE = "not_applicable"
MISSINGNESS_NONE_EXPECTED = "none_expected"

MISSINGNESS_BY_FAMILY = {
    "profile": MISSINGNESS_UNKNOWN,
    "profile_depth": MISSINGNESS_UNKNOWN,
    "league_average": MISSINGNESS_UNKNOWN,
    "workload": MISSINGNESS_UNKNOWN,
    "workload_extra": MISSINGNESS_UNKNOWN,
    "workload_difference": MISSINGNESS_UNKNOWN,
    "schedule_strength": MISSINGNESS_UNKNOWN,
    "form": MISSINGNESS_UNKNOWN,
    "form_opponent": MISSINGNESS_UNKNOWN,
    "uefa": MISSINGNESS_UNKNOWN,
    "form_difference": MISSINGNESS_UNKNOWN,
    "match_context": MISSINGNESS_NOT_APPLICABLE,
    "squad_history": MISSINGNESS_UNKNOWN,
}


def _missingness(familie, spalte):
    """
    Die Missingness-Semantik eines Merkmals.

    Die Aggregatspalten sind der Sonderfall, um den es geht: Ein
    Ligaphasenspiel HAT keinen Aggregatstand. Das ist eine bekannte
    Tatsache, kein fehlender Messwert - und der Unterschied entscheidet,
    ob eine Null oder ein Median richtig waere.
    """
    if familie == "match_context" and spalte.startswith("aggregate_"):
        return MISSINGNESS_NOT_APPLICABLE
    if familie == "match_context":
        return MISSINGNESS_NONE_EXPECTED
    return MISSINGNESS_BY_FAMILY[familie]


# ---------------------------------------------------------------------------
# Die beiden Datensatzansichten
# ---------------------------------------------------------------------------

#: Der final zugelassene Kandidat.
#:
#: Bewusst als Verweis auf feature_groups und nicht als eigene Liste.
#: Eine hier wiederholte Merkmalsaufzaehlung waere die zweite Liste,
#: die diese Datei gerade verhindern soll.
SELECTED_CANDIDATE = fg.C3_BASE_CANDIDATE


def selected_columns(gruppen=None, spalten=None):
    """
    Genau die Merkmale des finalen Kandidaten - geprueft.

    Die Liste kommt aus fg.columns_for(); diese Funktion fuegt die
    Statuspruefung hinzu. Ragte je ein REJECTED-, INCONCLUSIVE-,
    NOT_EVALUABLE- oder INFRASTRUCTURE_ONLY-Merkmal hinein - etwa weil
    jemand einer Variante eine Gruppe hinzufuegt -, bricht der Aufruf
    ab, statt ein stillschweigend groesseres Modell zu liefern.
    """
    spalten = list(spalten if spalten is not None else mdl.feature_columns())
    gruppen = gruppen if gruppen is not None else fg.build_groups(spalten)

    ausgewaehlt = fg.columns_for(SELECTED_CANDIDATE, gruppen, spalten)

    familie_von = {}
    for familie in fg.GROUP_ORDER:
        for spalte in gruppen[familie]["columns"]:
            familie_von[spalte] = familie

    verstoesse = []
    for spalte in ausgewaehlt:
        familie = familie_von.get(spalte)
        if familie is None:
            verstoesse.append((spalte, "ohne Familie"))
            continue
        status = FAMILY_REGISTRY[familie]["status"]
        if status not in STATUSES_ALLOWED_IN_SELECTED:
            verstoesse.append((spalte, f"{familie} ist {status}"))

    if verstoesse:
        raise ValueError(
            f"Der Kandidat {SELECTED_CANDIDATE!r} enthaelt Merkmale, "
            f"die nicht aufgenommen sind: {verstoesse}. Ein Merkmal "
            f"gelangt nicht in den finalen Kandidaten, nur weil es "
            f"technisch existiert.")

    return list(ausgewaehlt)


#: Familien, deren Quelle NICHT in der Versionsverwaltung liegt.
#:
#: Sie sind der Grund, warum research_columns() einen Parameter braucht.
#: Aus einem frischen Checkout gebaut, traegt jede dieser Spalten in
#: JEDER Zeile None. Sie trotzdem in den Forschungsdatensatz zu legen
#: waere die stille Ersatzdatenerzeugung, die der Auftrag verbietet -
#: nur eben mit None statt mit einer erfundenen Zahl. Eine Spalte, die
#: aussieht wie ein Merkmal und keines ist, ist die schlechtere
#: Variante von "fehlt".
OPTIONAL_SOURCE_FAMILIES = {
    "uefa": {
        "path": "data/big_games/uefa_coefficients",
        "switch": "include_uefa",
        "default": ds.INCLUDE_UEFA_BY_DEFAULT,
    },
    "squad_history": {
        "path": "data/cache + data/player_pool",
        "switch": "include_squad_history",
        "default": ds.INCLUDE_SQUAD_HISTORY_BY_DEFAULT,
    },
}


def research_columns(gruppen=None, spalten=None, optional_sources=()):
    """
    Die technisch tragfaehigen Forschungsmerkmale.

    optional_sources nennt die gitignorierten Quellen, die beim Bau
    TATSAECHLICH gelesen wurden - etwa ("uefa", "squad_history"). Was
    nicht genannt ist, bleibt draussen: Eine Spalte, die in jeder Zeile
    None traegt, ist kein Forschungsmerkmal, sondern eine Luecke mit
    Ueberschrift.

    Enthalten ist ausdruecklich auch Verworfenes. Der
    Forschungsdatensatz ist zum Weiterforschen da, und ein spaeter
    erneut pruefbares REJECTED ist sein Zweck - anders als beim
    Kandidaten, wo derselbe Status hart ausschliesst.
    """
    spalten = list(spalten if spalten is not None else mdl.feature_columns())
    gruppen = gruppen if gruppen is not None else fg.build_groups(spalten)
    validate_registry(gruppen)

    unbekannt = [q for q in optional_sources
                 if q not in OPTIONAL_SOURCE_FAMILIES]
    if unbekannt:
        raise ValueError(
            f"unbekannte optionale Quellen: {unbekannt} - bekannt sind "
            f"{sorted(OPTIONAL_SOURCE_FAMILIES)}")

    heraus = []
    for familie in fg.GROUP_ORDER:
        if (FAMILY_REGISTRY[familie]["status"]
                not in STATUSES_ALLOWED_IN_RESEARCH):
            continue
        if (familie in OPTIONAL_SOURCE_FAMILIES
                and familie not in optional_sources):
            continue
        heraus.extend(gruppen[familie]["columns"])
    return sorted(heraus)


# ---------------------------------------------------------------------------
# Zeilenidentitaet und Fingerabdruecke
# ---------------------------------------------------------------------------

#: Was eine Zeile eindeutig macht.
#:
#: Gegenueber cl_evaluate.FINGERPRINT_IDENTITY kamen home_id, away_id,
#: matchday und knockout_eligible hinzu. Der Grund ist keine
#: Vollstaendigkeitsliebe: Ohne die Team-IDs koennte man in einer Zeile
#: die Mannschaften vertauschen, ohne dass sich der Fingerabdruck
#: aendert - und genau das waere eine andere Partie.
#:
#: Die Teamnamen stehen ABSICHTLICH nicht hier. Sie sind ergaenzend und
#: schreibweisenabhaengig; ein umbenannter Verein wuerde sonst als
#: geaenderte Datenlage erscheinen.
IDENTITY_FIELDS = ("row_id", "match_id", "league", "season", "date",
                   "matchday", "home_id", "away_id",
                   "evaluation_eligible", "knockout_eligible")

#: Die Zielgroessen - vollstaendig.
#:
#: DIE LUECKE, DIE C9 SCHLIESST
#: Ein Fingerabdruck ohne Tore aendert sich nicht, wenn jemand die
#: Zielwerte vertauscht. Der Datensatz saehe identisch aus und jede
#: Kennzahl waere eine andere. home_goals und away_goals gehen deshalb
#: eigenstaendig in einen zweiten, getrennten Hash.
TARGET_FIELDS = ("home_goals", "away_goals", "outcome")

#: Der Vergleichsmassstab. Kein Merkmal, aber Teil der Eingabe: Er
#: bestimmt Ziel und Gewicht des Offsettricks.
BASELINE_FIELDS = ("baseline_lambda_home", "baseline_lambda_away")


def _hash_zeilen(zeilen, felder, praefix):
    """
    Ein Hash ueber genau diese Felder, in genau dieser Reihenfolge.

    Sortiert nach row_id: Der Wert wird damit unabhaengig von der
    Einlesereihenfolge, weil row_id eindeutig ist. Die Feldliste geht
    MIT in den Hash - sonst koennte ein Wert der einen Feldmenge
    zufaellig einem der anderen gleichen.

    repr() und nicht str(): 1 und 1.0 sind verschiedene Werte, und ein
    stiller Typwechsel ist genau die Art Aenderung, die ein
    Fingerabdruck zeigen soll.
    """
    h = hashlib.sha256()
    h.update(("%s|v%d|%s\n" % (praefix, REGISTRY_SCHEMA_VERSION,
                               "|".join(felder))).encode("utf-8"))
    for zeile in sorted(zeilen, key=lambda z: str(z.get("row_id"))):
        h.update(("|".join("" if zeile.get(f) is None else repr(zeile.get(f))
                           for f in felder) + "\n").encode("utf-8"))
    return h.hexdigest()


def target_fingerprint(zeilen):
    """
    Nur die Ziele, nur die Identitaet.

    Eigenstaendig und nicht bloss als Teil des Gesamthashes: So laesst
    sich beantworten, OB sich die Ziele geaendert haben - und nicht nur,
    dass sich irgendetwas geaendert hat.
    """
    return _hash_zeilen(zeilen, IDENTITY_FIELDS + TARGET_FIELDS, "c9-target")


def dataset_fingerprint(zeilen, spalten):
    """
    Identitaet, Ziele, Baseline und die tatsaechlich genutzten Werte.

    Die Merkmalsreihenfolge geht mit ein und ist kanonisch (sortiert).
    Damit gilt: Zwei Laeufe mit derselben Merkmalsmenge liefern
    denselben Wert, unabhaengig davon, in welcher Reihenfolge der
    Aufrufer sie uebergeben hat - und eine andere MENGE liefert einen
    anderen Wert.
    """
    felder = (list(IDENTITY_FIELDS) + list(TARGET_FIELDS)
              + list(BASELINE_FIELDS) + sorted(spalten))
    return _hash_zeilen(zeilen, felder, "c9-dataset")


def schema_fingerprint():
    """
    Der Vertrag selbst - ohne eine einzige Zeile Daten.

    Er aendert sich, wenn sich Gruppenzuschnitt, Status, Kandidat oder
    Modellfamilie aendern. Zwei Laeufe mit gleichem Datenfingerabdruck,
    aber verschiedenem Schemafingerabdruck sind NICHT vergleichbar,
    auch wenn die Zahlen es nahelegen.
    """
    nutzlast = {
        "c9_version": C9_VERSION,
        "registry_schema_version": REGISTRY_SCHEMA_VERSION,
        "dataset_schema_version": ds.SCHEMA_VERSION,
        "feature_group_schema_version": fg.SCHEMA_VERSION,
        "model_schema_version": ps.MODEL_SCHEMA_VERSION,
        "model_family": ps.MODEL_FAMILY,
        "selected_candidate": SELECTED_CANDIDATE,
        "group_order": list(fg.GROUP_ORDER),
        "family_status": {k: v["status"]
                          for k, v in sorted(FAMILY_REGISTRY.items())},
        "family_pit_class": {k: v["pit_class"]
                             for k, v in sorted(FAMILY_REGISTRY.items())},
        "identity_fields": list(IDENTITY_FIELDS),
        "target_fields": list(TARGET_FIELDS),
        "baseline_fields": list(BASELINE_FIELDS),
        "cutoff_hour": ds.PREDICTION_CUTOFF_HOUR,
        "cutoff_inclusive": ds.CUTOFF_INCLUSIVE,
    }
    roh = json.dumps(nutzlast, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Die beiden Ansichten
# ---------------------------------------------------------------------------

#: Was jede Zeile beider Ansichten traegt - unabhaengig von den
#: Merkmalen. Identitaet, Ziele und Baseline sind in Research und
#: Selected IDENTISCH; nur die Merkmalsspalten unterscheiden sich.
#:
#: Genau deshalb laesst sich die Zeilenidentitaet zwischen beiden
#: Ansichten vergleichen - und ein Test tut das.
VIEW_COMMON_FIELDS = (tuple(IDENTITY_FIELDS) + tuple(TARGET_FIELDS)
                      + tuple(BASELINE_FIELDS))

VIEW_RESEARCH = "research"
VIEW_SELECTED = "selected"
VIEWS = (VIEW_RESEARCH, VIEW_SELECTED)


def project(zeilen, spalten):
    """
    Eine Ansicht aus den Zeilen des ZENTRALEN Datensatzbaus.

    Keine zweite Pipeline. Die Zeilen kommen aus dataset.build_dataset()
    wie ueberall sonst; hier wird ausschliesslich ausgewaehlt. Zwei
    unabhaengig entwickelte Baustrecken waeren die sicherste Art, zwei
    verschiedene Datensaetze denselben Namen tragen zu lassen.

    Fehlt eine angeforderte Spalte in einer Zeile, bricht der Aufruf ab.
    Sie stillschweigend mit None zu fuellen hiesse, eine Luecke als
    Messwert auszugeben.
    """
    felder = list(VIEW_COMMON_FIELDS) + sorted(spalten)
    heraus = []
    for zeile in zeilen:
        fehlend = [f for f in felder if f not in zeile]
        if fehlend:
            raise ValueError(
                f"Zeile {zeile.get('row_id')!r} fehlen die Spalten "
                f"{fehlend[:5]} - eine fehlende Spalte wird nicht "
                f"ergaenzt, sondern gemeldet")
        heraus.append({f: zeile[f] for f in felder})
    return heraus


def build_views(zeilen, optional_sources=()):
    """
    Beide Ansichten aus EINEM Zeilenbestand.

    Rueckgabe: {"research": [...], "selected": [...], "meta": {...}}.

    Die Zeilenmenge ist in beiden Ansichten dieselbe - es wird nicht
    gefiltert, nur projiziert. Wer eine Ansicht auf weniger Zeilen
    baute, koennte die beiden spaeter nicht mehr gegeneinanderhalten.
    """
    forschung = research_columns(optional_sources=optional_sources)
    ausgewaehlt = selected_columns()

    fremd = [s for s in ausgewaehlt if s not in forschung]
    if fremd:
        raise ValueError(
            f"Der Kandidat nutzt Merkmale, die der Forschungsdatensatz "
            f"nicht kennt: {fremd}. Selected muss eine TEILMENGE von "
            f"Research sein, sonst beschreiben die beiden Ansichten "
            f"verschiedene Welten.")

    return {
        VIEW_RESEARCH: project(zeilen, forschung),
        VIEW_SELECTED: project(zeilen, ausgewaehlt),
        "meta": {
            "rows": len(zeilen),
            "research_features": len(forschung),
            "selected_features": len(ausgewaehlt),
            "optional_sources": sorted(optional_sources),
            "selected_is_subset_of_research": True,
            "same_row_set": True,
        },
    }


# ---------------------------------------------------------------------------
# Der Feature-Freeze
# ---------------------------------------------------------------------------

def feature_freeze(optional_sources=()):
    """
    Der eingefrorene Kandidatenvertrag fuer C10.

    Alles, was C10 braucht, um dasselbe Modell zu bauen, ohne eine
    einzige Merkmalsentscheidung neu zu treffen - und alles, was noetig
    ist, um zu erkennen, dass es NICHT dasselbe Modell ist.

    Die Ausschlussgruende stehen mit drin. Ein Freeze, der nur sagt,
    was drin ist, laedt dazu ein, das Fehlende fuer ein Versehen zu
    halten.
    """
    ausgewaehlt = selected_columns()

    ausgeschlossen = {}
    for familie in fg.GROUP_ORDER:
        meta = FAMILY_REGISTRY[familie]
        if meta["status"] in STATUSES_ALLOWED_IN_SELECTED:
            continue
        ausgeschlossen[familie] = {
            "status": meta["status"],
            "reason": meta["reason"],
            "evidence": meta["evidence"],
            "block": meta["block"],
        }
    for name, meta in sorted(NON_FEATURE_COMPONENTS.items()):
        ausgeschlossen[name] = {
            "status": meta["status"],
            "reason": meta["why_not_a_feature"],
            "evidence": None,
            "block": meta["block"],
        }

    return {
        "candidate": SELECTED_CANDIDATE,
        "c9_version": C9_VERSION,
        "model_family": ps.MODEL_FAMILY,
        "model_schema_version": ps.MODEL_SCHEMA_VERSION,
        "features": list(ausgewaehlt),
        "feature_count": len(ausgewaehlt),
        "feature_order": ("sortiert (fg.columns_for) - die "
                          "Koeffizientenpositionen haengen daran"),
        "included_families": {
            familie: {"status": FAMILY_REGISTRY[familie]["status"],
                      "reason": FAMILY_REGISTRY[familie]["reason"],
                      "evidence": FAMILY_REGISTRY[familie]["evidence"]}
            for familie in fg.GROUP_ORDER
            if FAMILY_REGISTRY[familie]["status"]
            in STATUSES_ALLOWED_IN_SELECTED},
        "excluded": ausgeschlossen,
        "imputation": ("SimpleImputer(strategy='median'), foldlokal in "
                       "derselben Pipeline angepasst"),
        "scaling": "StandardScaler, foldlokal",
        "transformation": ("KEINE. model_class.py existiert und ist "
                           "getestet, aber build_pipeline(alpha) ohne "
                           "transform liefert unveraendert die "
                           "V1-Schrittfolge (V2-C8: die Transformation "
                           "verschlechterte das Ergebnis)."),
        "interactions": ("KEINE. Die vier C8-Interaktionen sind "
                         "implementiert und verworfen."),
        "regularisation": {
            "penalty": "L2 (sklearn PoissonRegressor)",
            "alpha_candidates": list(mdl.ALPHA_CANDIDATES),
            "selected_on": "innere Validierung, nie auf dem aeusseren Test",
            "tie_break": "bei Gleichstand gewinnt das groessere Alpha",
        },
        "calibration": ("KEINE. Die C8-Kalibrierung ist implementiert "
                        "und erreichte V1 nicht."),
        "guardrails": {
            "correction": [mdl.CORRECTION_MIN, mdl.CORRECTION_MAX],
            "lambda": [mdl.LAMBDA_MIN, mdl.LAMBDA_MAX],
        },
        "cutoff": {
            "hour": ds.PREDICTION_CUTOFF_HOUR,
            "inclusive": ds.CUTOFF_INCLUSIVE,
            "rule": ("Jede Beobachtung muss STRIKT vor dem Stichtag "
                     "liegen. Der Stichtag ist der Spieltag um "
                     f"{ds.PREDICTION_CUTOFF_HOUR:02d}:00."),
        },
        "optional_sources_used": sorted(optional_sources),
        "schema_fingerprint": schema_fingerprint(),
    }


# ---------------------------------------------------------------------------
# Point-in-Time-Invarianten
# ---------------------------------------------------------------------------

#: Was ein Zielwert ist und deshalb NIE ein Merkmal sein darf.
#:
#: Die Liste ist kurz und trotzdem noetig: Der teuerste Fehler dieser
#: Art ist nicht der offensichtliche (home_goals als Merkmal), sondern
#: der abgeleitete - eine Spalte, die aus dem Ergebnis errechnet wurde
#: und harmlos heisst.
TARGET_DERIVED_FORBIDDEN = ("home_goals", "away_goals", "outcome",
                            "result", "final_score", "goal_difference")


#: Wie viele unterscheidende Gruppen den Beweis tragen muessen.
#:
#: Eine genuegt logisch: Wo zwei Partien desselben Spieltags
#: verschiedene Ergebnisse haben und die Spalte denselben Wert traegt,
#: haengt sie nicht am zeileneigenen Ergebnis. Verlangt werden trotzdem
#: mehrere, damit ein einzelner Datenfehler den Beweis nicht traegt.
#:
#: Zur Groessenordnung im echten Bestand: 1867 (Liga, Datum)-Gruppen,
#: davon 1176 mit unterschiedlichen Heimtoren. Der Beweis ist dort
#: reichlich belegt - und auf einem Spielzeugbestand aus drei Zeilen
#: eben nicht, was richtig ist.
MIN_DISCRIMINATING_GROUPS = 3


def suspicious_target_names(spalten):
    """
    Merkmale, deren NAME nach einem Zielwert aussieht.

    Nur ein Verdacht, kein Urteil. Der Name allein reicht nicht:
    league_avg_home_goals endet auf "home_goals" und ist trotzdem der
    Ligadurchschnitt ueber ANDERE Partien. Ein reines Namensverbot
    haette hier zwei richtige Merkmale verworfen - oder waere per
    Ausnahmeliste entschaerft worden, was denselben Verdacht spaeter
    stillschweigend durchgelassen haette.
    """
    verdaechtig = []
    for spalte in spalten:
        if spalte in TARGET_FIELDS:
            verdaechtig.append((spalte, "ist selbst eine Zielgroesse",
                                "certain"))
            continue
        for verboten in TARGET_DERIVED_FORBIDDEN:
            if spalte == verboten:
                verdaechtig.append((spalte, f"heisst wie {verboten}",
                                    "certain"))
                break
            if spalte.endswith("_" + verboten):
                verdaechtig.append((spalte, f"endet auf {verboten}",
                                    "by_name"))
                break
    return verdaechtig


def exonerate_aggregate(zeilen, spalte, ziel):
    """
    Belegt, dass eine verdaechtige Spalte ein Aggregat ist - oder nicht.

    DER BEWEIS, NICHT DIE FAUSTREGEL
    Gesucht wird eine (Liga, Datum)-Gruppe, in der mindestens zwei
    Partien mit VERSCHIEDENEN Zielwerten liegen und die Spalte
    trotzdem denselben Wert traegt. Findet sich eine, kann die Spalte
    keine Funktion des zeileneigenen Zielwerts sein - sonst muesste sie
    dort variieren. Das ist ein Beweis und keine Wahrscheinlichkeit.

    Die frueher benutzte Trefferquote war eine Faustregel und
    versagte, wo sie am wenigsten versagen darf: Auf wenigen Zeilen
    gleicht ein konstantes Aggregat dem Zielwert schnell in einem
    Drittel der Faelle, ohne dass irgendetwas leckt. Sie wird weiterhin
    BERICHTET, weil sie beim Lesen hilft - entschieden wird an ihr
    nicht mehr.

    Findet sich keine unterscheidende Gruppe, lautet das Ergebnis
    "unentschieden", nicht "entlastet". Was nicht bewiesen werden kann,
    gilt nicht als bewiesen.
    """
    gruppen = {}
    treffer = 0
    bewertet = 0
    for zeile in zeilen:
        wert = zeile.get(spalte)
        if wert is None:
            continue
        schluessel = (zeile.get("league"), zeile.get("date"))
        eintrag = gruppen.setdefault(schluessel, {"werte": set(),
                                                  "ziele": set()})
        eintrag["werte"].add(round(float(wert), 9))
        zielwert = zeile.get(ziel)
        if zielwert is not None:
            eintrag["ziele"].add(float(zielwert))
            bewertet += 1
            if abs(float(wert) - float(zielwert)) < 1e-9:
                treffer += 1

    uneinheitlich = sum(1 for e in gruppen.values() if len(e["werte"]) > 1)

    # Die entscheidende Zahl: Gruppen, in denen die Zielwerte
    # auseinandergehen und der Spaltenwert trotzdem einer bleibt.
    unterscheidend = sum(1 for e in gruppen.values()
                         if len(e["ziele"]) > 1 and len(e["werte"]) == 1)

    quote = (100.0 * treffer / bewertet) if bewertet else 0.0
    konstant = uneinheitlich == 0

    if konstant and unterscheidend >= MIN_DISCRIMINATING_GROUPS:
        urteil = "exonerated"
    elif not konstant:
        urteil = "violation"
    else:
        urteil = "undecided"

    return {
        "column": spalte,
        "target": ziel,
        "groups_with_multiple_values": uneinheitlich,
        "constant_within_league_and_date": konstant,
        "discriminating_groups": unterscheidend,
        "equals_target_pct": round(quote, 3),
        "rows_evaluated": bewertet,
        "verdict": urteil,
        "exonerated": urteil == "exonerated",
    }


def check_no_target_leak(spalten, zeilen=None):
    """
    Kein Zielwert und nichts daraus Abgeleitetes unter den Merkmalen.

    Ohne zeilen wird nur der Name geprueft - dann bleibt jeder Verdacht
    ein Verstoss, weil nichts ihn entkraeften kann. Mit zeilen wird ein
    reiner Namensverdacht am Bestand nachgeprueft.

    Rueckgabe: (verstoesse, entlastungen).
    """
    verstoesse = []
    entlastungen = []

    for spalte, grund, art in suspicious_target_names(spalten):
        if art == "certain":
            verstoesse.append((spalte, grund))
            continue
        if zeilen is None:
            verstoesse.append(
                (spalte, grund + " - ohne Zeilen nicht entkraeftbar"))
            continue

        ziel = next((z for z in TARGET_FIELDS if spalte.endswith("_" + z)),
                    None)
        if ziel is None:                                 # pragma: no cover
            verstoesse.append((spalte, grund))
            continue

        befund = exonerate_aggregate(zeilen, spalte, ziel)
        if befund["exonerated"]:
            entlastungen.append(befund)
        else:
            verstoesse.append(
                (spalte, f"{grund} und am Bestand nicht entlastet "
                         f"({befund['verdict']}): konstant je Liga/Datum="
                         f"{befund['constant_within_league_and_date']}, "
                         f"unterscheidende Gruppen="
                         f"{befund['discriminating_groups']}, gleicht dem "
                         f"Ziel in {befund['equals_target_pct']} % der "
                         f"Zeilen"))

    return verstoesse, entlastungen


def check_rows_pit(zeilen, spalten):
    """
    Die Zeilen selbst gegen die Zeitinvarianten pruefen.

    Was hier NICHT geprueft wird: ob die Merkmalsberechnung intern
    sauber gefiltert hat - das tun die Tests der jeweiligen Bloecke mit
    manipulierten Eingaben. Hier geht es um das, was am fertigen
    Datensatz noch sichtbar ist.

    Rueckgabe: Bericht mit einem Befund je Invariante.
    """
    bericht = {}

    verstoesse, entlastungen = check_no_target_leak(spalten, zeilen)
    bericht["target_leak"] = {
        "violations": verstoesse,
        "violation_count": len(verstoesse),
        "exonerated": entlastungen,
        "checked_columns": len(spalten),
        "rule": ("Ein Namensverdacht wird am Bestand BEWIESEN oder "
                 "nicht: Gibt es Gruppen (Liga, Datum) mit "
                 "verschiedenen Zielwerten, in denen die Spalte "
                 "konstant bleibt, kann sie nicht am zeileneigenen "
                 "Ergebnis haengen. Ohne solchen Beweis bleibt der "
                 "Verdacht bestehen."),
    }

    # Saisongrenzen: Jede Zeile traegt genau eine Saison, und der
    # Stichtag muss in dieser Saison liegen. Ein Datum aus einer
    # spaeteren Saison in einer frueheren Zeile waere die deutlichste
    # Form von Leakage.
    verstoesse = []
    for zeile in zeilen:
        season, datum = zeile.get("season"), zeile.get("date")
        if season is None or not datum:
            continue
        jahr = int(str(datum)[:4])
        # Eine Saison X laeuft von Sommer X bis Fruehjahr X+1.
        if jahr not in (int(season), int(season) + 1):
            verstoesse.append((zeile.get("row_id"), season, datum))
    bericht["season_bounds"] = {
        "violations": verstoesse[:20],
        "violation_count": len(verstoesse),
        "rule": ("das Spieldatum liegt im Saisonjahr oder im Folgejahr "
                 "- eine Saison X laeuft von Sommer X bis Fruehjahr X+1"),
    }

    # Der Aggregatstand existiert ausschliesslich bei Rueckspielen.
    # Ein Hinspiel mit Aggregat waere ein Blick auf das eigene Ergebnis.
    verstoesse = []
    for zeile in zeilen:
        if zeile.get("aggregate_available") in (None, 0, False):
            continue
        if zeile.get("is_second_leg") in (None, 0, False):
            verstoesse.append((zeile.get("row_id"),
                               zeile.get("aggregate_available"),
                               zeile.get("is_second_leg")))
    bericht["aggregate_only_in_second_leg"] = {
        "violations": verstoesse[:20],
        "violation_count": len(verstoesse),
        "rule": ("ein Aggregatstand existiert nur im Rueckspiel; im "
                 "Hinspiel waere er das eigene, noch nicht gespielte "
                 "Ergebnis"),
    }

    # Zeilenidentitaet: row_id muss eindeutig sein. Zwei Zeilen mit
    # demselben Schluessel machen jeden Fingerabdruck bedeutungslos,
    # weil die Sortierung sie nicht mehr trennt.
    gesehen = {}
    doppelt = []
    for zeile in zeilen:
        schluessel = zeile.get("row_id")
        if schluessel in gesehen:
            doppelt.append(schluessel)
        gesehen[schluessel] = True
    bericht["row_id_unique"] = {
        "duplicates": doppelt[:20],
        "duplicate_count": len(doppelt),
        "rows": len(zeilen),
        "distinct": len(gesehen),
    }

    # Die Identitaetsfelder muessen belegt sein - eine Zeile ohne
    # Team-ID liesse sich mit einer anderen verwechseln.
    unvollstaendig = []
    for zeile in zeilen:
        for feld in ("row_id", "league", "season", "date",
                     "home_id", "away_id"):
            if zeile.get(feld) in (None, ""):
                unvollstaendig.append((zeile.get("row_id"), feld))
                break
    bericht["identity_complete"] = {
        "violations": unvollstaendig[:20],
        "violation_count": len(unvollstaendig),
    }

    bericht["ok"] = all(
        not bericht[k].get("violations") and not bericht[k].get("duplicates")
        for k in ("target_leak", "season_bounds",
                  "aggregate_only_in_second_leg", "row_id_unique",
                  "identity_complete"))
    return bericht


#: Die Invarianten, die NICHT am fertigen Datensatz sichtbar sind.
#:
#: Sie werden mit manipulierten Eingaben getestet, nicht am Bestand
#: gemessen - ein sauberer Datensatz beweist nicht, dass die Filterung
#: greift, sondern nur, dass sie diesmal nichts zu tun hatte. Der
#: Verweis steht hier, damit das Manifest nicht so aussieht, als sei
#: die Liste der Invarianten vollstaendig gemessen.
INVARIANTS_TESTED_BY_MANIPULATION = (
    {"invariant": "zukuenftige Partie beeinflusst die Form nicht",
     "test": "tests/test_c9_early_v2.py::test_zukuenftige_partie_wird_"
             "aus_der_form_ausgeschlossen"},
    {"invariant": "Transfer am Spieltag beeinflusst das Zielspiel nicht",
     "test": "tests/test_c9_early_v2.py::test_transfer_am_spieltag_"
             "geht_nicht_ein"},
    {"invariant": "Snapshot nach dem Stichtag wird nicht verwendet",
     "test": "tests/test_c9_early_v2.py::test_snapshot_nach_dem_"
             "stichtag_wird_nicht_gelesen"},
    {"invariant": "eine spaetere Saison beeinflusst eine fruehere nicht",
     "test": "tests/test_c9_early_v2.py::test_spaetere_saison_"
             "beeinflusst_fruehere_nicht"},
    {"invariant": "ein Crosswalkkonflikt entfernt den Eintrag",
     "test": "tests/test_c9_early_v2.py::test_crosswalkkonflikt_"
             "entfernt_den_eintrag"},
    {"invariant": "foldlokale Parameter sehen den Testfold nicht",
     "test": "tests/test_c9_early_v2.py::test_foldlokale_grenzen_"
             "sehen_den_testfold_nicht"},
)


# ---------------------------------------------------------------------------
# Quellen
# ---------------------------------------------------------------------------

#: Die Datenquellen von Early V2 - Ort, Zeitsemantik, Verfuegbarkeit.
#:
#: "observed_at" ist die entscheidende Spalte dieser Tabelle: Nur wo
#: eine Quelle selbst sagt, WANN sie beobachtet wurde, laesst sich ein
#: Stichtag ohne Annahme durchsetzen. Ueberall sonst tritt das
#: Spieldatum an ihre Stelle - das ist zulaessig, aber es ist eine
#: Annahme und muss als solche dastehen.
SOURCE_INVENTORY = {
    "historical_matches": {
        "path": "data/historical",
        "tracked": True,
        "provider": "football-data.org",
        "identifiers": "match_id, home_id, away_id (football-data)",
        "time_fields": "utcDate bzw. date",
        "observed_at": False,
        "cutoff_rule": ("Spieldatum um "
                        f"{ds.PREDICTION_CUTOFF_HOUR:02d}:00, strikt davor"),
        "used_for": ("Profile, Ligaschnitt, Zeitleiste, Form, "
                     "Belastung, Spielkontext, Zielwerte"),
        "runtime_available": True,
    },
    "national_leagues": {
        "path": "data/national",
        "tracked": True,
        "provider": "football-data.org / API-Sports",
        "identifiers": "je Datei, ueber Crosswalk verbunden",
        "time_fields": "date",
        "observed_at": False,
        "cutoff_rule": "wie historical_matches",
        "used_for": "zusaetzliche Ligazeilen und Zeitleisteneintraege",
        "runtime_available": True,
    },
    "uefa_coefficients": {
        "path": "data/big_games/uefa_coefficients",
        "tracked": False,
        "provider": "UEFA-Koeffizienten (abgeleitet)",
        "identifiers": "Vereinsname, ueber Crosswalk aufgeloest",
        "time_fields": "Saison des Snapshots",
        "observed_at": False,
        "cutoff_rule": ("Snapshot der VORSAISON (X-1) fuer Saison X - "
                        "der Koeffizient der laufenden Saison steht erst "
                        "danach fest"),
        "used_for": "Familie uefa (EXPERIMENTAL, standardmaessig aus)",
        "runtime_available": False,
    },
    "transfer_events": {
        "path": "data/cache",
        "tracked": False,
        "provider": "API-Sports",
        "identifiers": "player_id, team_id (API-Sports)",
        "time_fields": "ein Datum je Wechsel",
        "observed_at": False,
        "cutoff_rule": ("strikt vor dem Spieltag. Der Anbieter "
                        "unterscheidet NICHT zwischen Bekanntgabe und "
                        "Wirksamkeit - die konservative Lesart schliesst "
                        "den Spieltag selbst aus"),
        "used_for": "Familie squad_history (INCONCLUSIVE, standardmaessig aus)",
        "runtime_available": False,
    },
    "player_pool": {
        "path": "data/player_pool",
        "tracked": False,
        "provider": "API-Sports",
        "identifiers": "player_id (KEINE team_id)",
        "time_fields": "KEINE - reine Saisonaggregation",
        "observed_at": False,
        "cutoff_rule": ("ausschliesslich ABGESCHLOSSENE Saisons "
                        "(<= S-1). Ohne Datum waere die laufende Saison "
                        "die Vorhersage mit ihrem eigenen Ergebnis"),
        "used_for": "Vorsaisonstaerke der Wechsler",
        "runtime_available": False,
    },
    "snapshot_archive": {
        "path": "data/snapshots",
        "tracked": False,
        "provider": "API-Sports ueber den C6-Sammler",
        "identifiers": "team_id, fixture_id (API-Sports)",
        "time_fields": "fetched_at und effective_at",
        "observed_at": True,
        "cutoff_rule": ("snapshot_before() liest STRIKT vor dem "
                        "Stichtag; zweite Zeitebene ueber effective_at"),
        "used_for": ("NICHTS im Modell - squad_snapshot und "
                     "availability_impact sind NOT_EVALUABLE"),
        "runtime_available": True,
    },
}


#: Zwei Staerken von Quellfingerabdruck.
#:
#: CONTENT hasht jedes Byte. Nur er belegt, dass ein zweiter Lauf
#: dieselben Eingaben sah - und nur er gehoert ins Manifest.
#:
#: INVENTORY hasht Pfade und Groessen. Er ist um Groessenordnungen
#: schneller und fuer Tests gedacht, die bloss wissen muessen, ob sich
#: der Bestand strukturell geaendert hat. Er ist AUSDRUECKLICH kein
#: Reproduktionsnachweis: Eine geaenderte Zahl gleicher Laenge bliebe
#: unsichtbar. Der Modus steht deshalb im Ergebnis, damit niemand die
#: beiden verwechselt.
FINGERPRINT_CONTENT = "content"
FINGERPRINT_INVENTORY = "inventory"


#: Verzeichnisse, die zu einer Quelle gehoeren, aber keine Quelldaten
#: enthalten.
#:
#: data/snapshots/_runs sammelt die Laufberichte des C6-Sammlers. Sie
#: sind Betriebsprotokoll, nicht Beobachtung: Ein zusaetzlicher Lauf
#: aendert dort eine Datei, ohne dass sich eine einzige gesammelte
#: Beobachtung geaendert haette.
#:
#: Aufgefallen ist das beim Doppellauf waehrend der Testsuite - die
#: C6-Tests schreiben Laufberichte, und der Manifestfingerabdruck
#: wanderte zwischen zwei Berechnungen. Ein Fingerabdruck, der auf
#: Protokollrauschen reagiert, kann die Frage "sind das dieselben
#: Daten" nicht beantworten.
SOURCE_EXCLUDED_DIRS = ("_runs",)


def _ist_ausgeschlossen(relativer_pfad):
    """Liegt der Pfad in einem ausgeschlossenen Unterverzeichnis?"""
    teile = relativer_pfad.replace("\\", "/").split("/")
    return any(teil in SOURCE_EXCLUDED_DIRS for teil in teile[:-1])


def _datei_fingerprint(pfad, muster="*.json", modus=FINGERPRINT_CONTENT):
    """
    Ein Hash ueber ein Quellverzeichnis.

    Die relativen Dateinamen gehen MIT ein: Eine geloeschte Datei
    aendert den Bestand, auch wenn die uebrigen Inhalte gleich bleiben.

    Fehlt das Verzeichnis, ist das kein Fehler, sondern ein Befund -
    genau so sieht ein frischer Checkout ohne die privaten Quellen aus.

    Zur Groessenordnung: data/cache traegt rund 27.000 Dateien und
    222 MB; ein Inhaltshash darueber dauert Minuten. Das ist fuer ein
    Freeze-Artefakt vertretbar und fuer einen Test nicht - daher der
    Modus.
    """
    import glob
    import os

    if not os.path.isdir(pfad):
        return {"present": False, "files": 0, "sha256": None,
                "mode": modus}

    dateien = []
    for datei in sorted(glob.glob(os.path.join(pfad, "**", muster),
                                  recursive=True)):
        relativ = os.path.relpath(datei, pfad).replace("\\", "/")
        if _ist_ausgeschlossen(relativ):
            continue
        dateien.append((relativ, datei))

    h = hashlib.sha256()
    h.update((modus + "|" + muster + "|"
              + ",".join(SOURCE_EXCLUDED_DIRS)).encode("utf-8"))
    for relativ, datei in dateien:
        h.update(relativ.encode("utf-8"))
        if modus == FINGERPRINT_CONTENT:
            with open(datei, "rb") as strom:
                for block in iter(lambda: strom.read(65536), b""):
                    h.update(block)
        else:
            h.update(str(os.path.getsize(datei)).encode("utf-8"))
    return {"present": True, "files": len(dateien),
            "sha256": h.hexdigest(), "mode": modus,
            "excluded_dirs": list(SOURCE_EXCLUDED_DIRS)}


def source_fingerprints(modus=FINGERPRINT_CONTENT):
    """
    Ein Fingerabdruck je Quellverzeichnis.

    Nicht der Inhalt selbst - das Manifest darf keine Rohdatenkopie
    sein. Nur die Aussage: Dieser Lauf sah genau diesen Bestand.
    """
    if modus not in (FINGERPRINT_CONTENT, FINGERPRINT_INVENTORY):
        raise ValueError(f"unbekannter Fingerabdruckmodus: {modus!r}")
    return {name: dict(_datei_fingerprint(meta["path"], modus=modus),
                       path=meta["path"], tracked=meta["tracked"])
            for name, meta in sorted(SOURCE_INVENTORY.items())}


# ---------------------------------------------------------------------------
# Vertragstexte, die ins Manifest gehoeren
# ---------------------------------------------------------------------------

#: Der Befehl, der diesen Stand erzeugt.
BUILD_COMMAND = "python run_ml.py --freeze-c9 --output " + MANIFEST_PATH

#: Die bekannte Grenze der Stichtagsregel - gemessen, nicht vermutet.
#:
#: Der Stichtag liegt am Spieltag um 12:00. Eine FREMDE Partie, die
#: am selben Tag vor 12:00 angepfiffen wurde, geht damit ein, auch wenn
#: das Zielspiel frueher begann. Die beiden beteiligten Mannschaften
#: sind davon nicht betroffen - sie koennen nicht zweimal am selben Tag
#: spielen. Betroffen waeren allenfalls Ligadurchschnitt und
#: Gegnerstaerke, und auch die nur bei Vormittagsanstoessen.
KNOWN_CUTOFF_LIMIT = (
    "Der Stichtag ist ein Tagesstichtag um 12:00, kein Anstosszeitpunkt. "
    "Die Ligadateien fuehren kein verlaessliches Anstosszeitfeld, deshalb "
    "waere eine je Quelle unterschiedliche Regel schlechter als eine "
    "einheitlich leicht zu fruehe. Rest-Risiko: eine fremde Partie mit "
    "Anstoss vor 12:00 am Spieltag kann in Ligadurchschnitt oder "
    "Gegnerstaerke eingehen. Die beiden beteiligten Mannschaften sind "
    "ausgeschlossen - sie spielen nicht zweimal am selben Tag.")

#: Die Artefakte, die die Statusentscheidungen tragen.
#:
#: Ohne diese Liste waere jeder Status in FAMILY_REGISTRY eine
#: Behauptung, die man glauben muesste.
EVIDENCE_ARTIFACTS = {
    "C2_stage1": "data/ml/ablation_2023-2025.json",
    "C2_stage2": "data/ml/ablation_diagnostics_2023-2025.json",
    "C2B_shadow": "data/ml/cl_shadow_backtest_2023-2025.json",
    "C3_workload": "data/ml/c3_workload_ablation_2023-2025.json",
    "C4_form": "data/ml/c4_form_ablation_2023-2025.json",
    "C5_context": "data/ml/c5_context_ablation_2023-2025.json",
    "C7_squad_history": "data/ml/c7_squad_history_ablation_2023-2025.json",
    "C8_model_class": "data/ml/c8_model_class_ablation_2023-2025.json",
}

#: Der ehrliche Stand zum Holdout.
#:
#: Das ist der unbequemste Abschnitt dieser Datei und deshalb der
#: wichtigste. Die Saisons 2023 bis 2025 wurden ueber acht Bloecke
#: hinweg wiederholt angesehen - fuer Merkmalsentscheidungen,
#: Modellwahl und Gate-Schwellen. Sie sind kein unangetasteter
#: Testbestand mehr, und sie so zu nennen waere die bequemste Luege
#: dieses Projekts.
HOLDOUT_STATUS = {
    "has_untouched_holdout": False,
    "seasons_used_for_decisions": [2023, 2024, 2025],
    "why": (
        "Dieselben Saisons trugen die C2-Ablation, die C2B-Uebertragung, "
        "die C3- bis C7-Merkmalsentscheidungen und die C8-Modellklasse. "
        "Jede spaetere Messung auf ihnen ist damit hoechstens "
        "konfirmatorisch fuer eine Hypothese, die aus denselben Daten "
        "stammt."),
    "classification": {
        "exploratory": (
            "C3, C4, C5, C7 - Merkmalsfamilien wurden anhand dieser "
            "Saisons ausgewaehlt oder verworfen"),
        "confirmatory_within_the_same_data": (
            "C8 - die Modellklasse wurde gegen vorab festgelegte "
            "Kandidaten und ein vorab festgelegtes Gate geprueft, aber "
            "auf demselben Bestand"),
        "regression_only": (
            "C9 - hier wird nichts mehr gemessen, sondern der Stand "
            "eingefroren"),
    },
    "what_would_create_a_real_holdout": (
        "Erst Champions-League-Partien einer Saison, die zum Zeitpunkt "
        "aller bisherigen Entscheidungen noch nicht gespielt war - also "
        "die Saison 2026/27 aufwaerts. Kein Umsortieren des bestehenden "
        "Bestands kann das ersetzen."),
    "reevaluation_trigger": (
        "Sobald data/historical eine CL-Saison enthaelt, deren Partien "
        "saemtlich nach dem Datum dieses Manifests liegen."),
}

#: Die Trennung der beiden Betriebsarten - als Vertrag, nicht als
#: Absichtserklaerung.
#:
#: C9 baut sie NICHT um; das ist ein eigener spaeterer Auftrag. C9
#: schreibt sie auf, damit der naechste Block sie nicht neu erfindet.
MODE_SEPARATION = {
    "ml_mode": {
        "uses": "ausschliesslich den trainierten ML-Kandidaten",
        "forbidden": [
            "individuelle Nutzerregler",
            "manuelle Faktoren in den ML-Eingaben",
            "requestspezifische Veraenderung der ML-Prognose",
        ],
    },
    "individual_mode": {
        "uses": "eine vollstaendig manuelle Szenariosimulation",
        "forbidden": [
            "ML-Einfluss",
            "ein ML-Gewicht - fachlich dort nicht vorgesehen",
        ],
    },
    "status_in_c9": (
        "NICHT umgebaut. Der bestehende sichtbare und serverseitige "
        "Reglervertrag bleibt unveraendert; eine Aenderung waere ein "
        "eigener Produkt- und UI-Block nach V2-C12."),
    "why_it_matters": (
        "Beide Ansaetze beantworten verschiedene Fragen. Ein ML-Modell "
        "sagt, was zu erwarten ist; eine Szenariosimulation sagt, was "
        "waere wenn. Sie zu mischen ergibt eine Zahl, die keine der "
        "beiden Fragen beantwortet."),
}

#: Was dieser Stand NICHT leistet.
KNOWN_LIMITS = [
    "Kein unangetasteter Holdout. Siehe holdout_status - die Saisons "
    "2023 bis 2025 haben alle bisherigen Entscheidungen getragen.",

    "Der Stichtag ist ein Tagesstichtag um 12:00, kein Anstosszeitpunkt. "
    "Siehe cutoff_contract.known_limit.",

    "Zwei Merkmalsfamilien (uefa, squad_history) stammen aus "
    "gitignorierten Quellen. Aus einem frischen Checkout gebaut, "
    "enthaelt der Forschungsdatensatz sie NICHT - er ist dann kleiner, "
    "aber nicht falsch. Der Kandidatendatensatz ist davon unberuehrt.",

    "Die Runtime rechnet ohne ausdruecklichen prediction_cutoff. Siehe "
    "runtime_parity - die Merkmalsberechnung ist identisch, die "
    "Zeitsemantik der Runtime aber nicht nachweisbar dieselbe.",

    "Das Manifest belegt einen Stand; es dupliziert ihn nicht. Ohne die "
    "Quellverzeichnisse laesst sich aus ihm allein kein Datensatz "
    "rekonstruieren - das ist Absicht.",

    "C9 hat nichts gemessen. Alle Statuswerte stammen aus C2 bis C8; "
    "diese Datei fasst zusammen und prueft auf Widerspruchsfreiheit.",
]


def runtime_parity_report():
    """
    Was zwischen Training und Runtime nachweislich gleich ist - und was
    nicht.

    Der ehrliche Teil steht unten: Die Runtime kennt keinen
    ausdruecklichen Stichtag. Solange das so ist, laesst sich die
    Zeitsemantik nicht als identisch NACHWEISEN, auch wenn sie es
    vermutlich ist. Ein "vermutlich" gehoert nicht in eine
    Paritaetszusage.
    """
    return {
        "verified": {
            "feature_names": ("inference.feature_columns() und "
                              "fg.columns_for(SELECTED_CANDIDATE) "
                              "liefern dieselbe Liste - beide rufen "
                              "dieselbe Funktion, es gibt keine zweite "
                              "Merkmalsliste in der Runtime"),
            "feature_order": ("beide sortiert - die "
                              "Koeffizientenpositionen stimmen ueberein"),
            "imputation": "SimpleImputer(median) in derselben Pipeline",
            "scaling": "StandardScaler in derselben Pipeline",
            "transformation": "keine, auf beiden Seiten",
            "interactions": "keine, auf beiden Seiten",
            "model_family": ps.MODEL_FAMILY,
            "guardrails": {
                "correction": [mdl.CORRECTION_MIN, mdl.CORRECTION_MAX],
                "lambda": [mdl.LAMBDA_MIN, mdl.LAMBDA_MAX],
            },
            "pipeline_construction": ("model.build_pipeline ist die "
                                      "einzige Stelle, die eine Pipeline "
                                      "zusammensetzt"),
        },
        "not_verifiable": {
            "prediction_cutoff": (
                "Die Runtime berechnet Merkmale zum Abrufzeitpunkt und "
                "fuehrt keinen ausdruecklichen prediction_cutoff mit. "
                "Der Trainingspfad setzt ihn auf den Spieltag um "
                f"{ds.PREDICTION_CUTOFF_HOUR:02d}:00. Beide duerften in "
                "der Praxis dasselbe Ergebnis liefern - nachweisen "
                "laesst es sich nicht."),
        },
        "blocker": True,
        "why_not_fixed_in_c9": (
            "Ein Runtime-Umbau ist kein Datensatzvertrag. Ihn hier "
            "mitzuerledigen hiesse, den produktiven Vorhersagepfad in "
            "einem Block zu aendern, der ausdruecklich nichts aktiviert."),
        "follow_up": (
            "C10 bis C12: einen ausdruecklichen prediction_cutoff durch "
            "inference und runtime fuehren und gegen den Trainingspfad "
            "vergleichen. Erst dann ist historische Runtime-Paritaet "
            "eine Aussage statt einer Vermutung."),
    }


# ---------------------------------------------------------------------------
# Das Manifest
# ---------------------------------------------------------------------------

#: Felder, die eine Messung der MASCHINE oder des Augenblicks sind.
#:
#: Sie gehoeren ins Manifest - ein Erzeugungszeitpunkt ist nuetzlich -,
#: duerfen aber nicht in den fachlichen Reproduktionsfingerabdruck.
#: Sonst waere jeder zweite Lauf per Definition ein anderer Stand, und
#: der Nachweis "zweimal dasselbe" nicht fuehrbar.
#:
#: Der GESAMTE git-Block faellt heraus, nicht nur einzelne Felder. Der
#: Grund ist beim ersten Doppellauf sichtbar geworden: Der erste Lauf
#: schreibt das Manifest, der Arbeitsbaum hat danach eine ungetrackte
#: Datei mehr, und der zweite Lauf zaehlt 47 statt 46. Ein Manifest,
#: das seine eigene Wirkung auf den Arbeitsbaum mithasht, kann per
#: Konstruktion nie zweimal gleich sein.
#:
#: Der Commit steht weiterhin IM Manifest - er ist nuetzlich -, nur
#: eben nicht im Hash: Derselbe Datenstand kann aus zwei Commits
#: entstehen, und der Fingerabdruck soll die Daten beschreiben.
MANIFEST_VOLATILE_FIELDS = ("created_at", "runtime_seconds", "git")


def manifest_fingerprint(manifest):
    """
    Der fachliche Fingerabdruck des Manifests.

    Ausgenommen sind ausschliesslich MANIFEST_VOLATILE_FIELDS. Alles
    andere - Merkmalslisten, Status, Quellhashes, Foldvertraege - muss
    ein zweiter Lauf reproduzieren.

    Der git-Block ist vollstaendig ausgenommen - siehe
    MANIFEST_VOLATILE_FIELDS.
    """
    def _saeubern(wert):
        if isinstance(wert, dict):
            return {k: _saeubern(v) for k, v in sorted(wert.items())
                    if k not in MANIFEST_VOLATILE_FIELDS}
        if isinstance(wert, list):
            return [_saeubern(v) for v in wert]
        return wert

    roh = json.dumps(_saeubern(manifest), sort_keys=True,
                     ensure_ascii=False, default=repr)
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()


def _git_zustand():
    """HEAD und Sauberkeit des Arbeitsbaums - ohne Pfadangaben."""
    import subprocess

    def _lauf(*befehl):
        try:
            fertig = subprocess.run(befehl, capture_output=True, text=True,
                                    timeout=30)
        except Exception:                                # pragma: no cover
            return None
        return fertig.stdout.strip() if fertig.returncode == 0 else None

    kopf = _lauf("git", "rev-parse", "HEAD")
    status = _lauf("git", "status", "--porcelain")
    return {
        "git_commit": kopf,
        # Nur die ANZAHL, nicht die Dateinamen: Ein Manifest, das den
        # Arbeitsbaum auflistet, verraet lokale Pfade und private
        # Artefaktnamen.
        "git_dirty": bool(status),
        "git_dirty_entries": (len(status.splitlines()) if status else 0),
    }


def build_manifest(zeilen, optional_sources=(),
                   source_mode=FINGERPRINT_CONTENT):
    """
    Das reproduzierbare C9-Manifest.

    zeilen: der Bestand aus dataset.build_dataset() - derselbe zentrale
    Bau wie ueberall.

    Was hier NICHT hineingeht: vollstaendige Merkmalsvektoren,
    Rohdatenkopien, absolute Pfade, Geheimnisse. Das Manifest belegt
    einen Stand, es dupliziert ihn nicht.
    """
    import platform
    import sys as _sys

    validate_registry()

    forschung = research_columns(optional_sources=optional_sources)
    ausgewaehlt = selected_columns()
    registry = feature_registry()

    ansichten = build_views(zeilen, optional_sources)
    pit = check_rows_pit(zeilen, forschung)

    saisons = sorted({z.get("season") for z in zeilen
                      if z.get("season") is not None})
    wettbewerbe = sorted({str(z.get("league")) for z in zeilen
                          if z.get("league")})

    fehlend = {}
    for spalte in forschung:
        leer = sum(1 for z in zeilen if z.get(spalte) is None)
        if leer:
            fehlend[spalte] = round(100.0 * leer / len(zeilen), 2)

    familien = {}
    for familie in fg.GROUP_ORDER:
        meta = FAMILY_REGISTRY[familie]
        spalten_der_familie = [r["name"] for r in registry
                               if r["family"] == familie]
        familien[familie] = {
            "status": meta["status"],
            "block": meta["block"],
            "pit_class": meta["pit_class"],
            "source": meta["source"],
            "tracked_source": meta["tracked"],
            "runtime_available": meta["runtime_available"],
            "reason": meta["reason"],
            "evidence": meta["evidence"],
            "since_version": meta["since_version"],
            "feature_count": len(spalten_der_familie),
            "in_research": all(r["in_research"] for r in registry
                               if r["family"] == familie),
            "in_selected": any(r["in_selected"] for r in registry
                               if r["family"] == familie),
        }

    manifest = {
        "manifest_schema": {
            "name": "footsim-c9-early-v2-manifest",
            "version": REGISTRY_SCHEMA_VERSION,
        },
        "c9_version": C9_VERSION,
        "created_at": _jetzt(),
        "environment": {
            "python": _sys.version.split()[0],
            "platform": platform.system(),
            "packages": _paketversionen(),
        },
        "build_command": BUILD_COMMAND,
        "git": _git_zustand(),

        "sources": {
            "inventory": {name: dict(meta) for name, meta
                          in sorted(SOURCE_INVENTORY.items())},
            "fingerprints": source_fingerprints(source_mode),
            "fingerprint_mode": source_mode,
            "optional_sources_used": sorted(optional_sources),
            "optional_source_families": {
                k: dict(v) for k, v in sorted(
                    OPTIONAL_SOURCE_FAMILIES.items())},
        },

        "dataset": {
            "rows": len(zeilen),
            "seasons": saisons,
            "competitions": wettbewerbe,
            "evaluation_eligible": sum(1 for z in zeilen
                                       if z.get("evaluation_eligible")),
            "knockout_eligible": sum(1 for z in zeilen
                                     if z.get("knockout_eligible")),
            "missingness_pct": fehlend,
            "identity_fields": list(IDENTITY_FIELDS),
            "target_fields": list(TARGET_FIELDS),
            "baseline_fields": list(BASELINE_FIELDS),
        },

        "views": {
            VIEW_RESEARCH: {
                "features": forschung,
                "feature_count": len(forschung),
                "purpose": ("Forschung, Ablation, Diagnostik. KEINE "
                            "automatische Produktivfreigabe."),
                "contains_rejected": True,
                "dataset_fingerprint": dataset_fingerprint(zeilen, forschung),
            },
            VIEW_SELECTED: {
                "features": ausgewaehlt,
                "feature_count": len(ausgewaehlt),
                "purpose": ("verbindlicher Eingang fuer C10 - keine "
                            "erneute freie Merkmalsauswahl"),
                "contains_rejected": False,
                "dataset_fingerprint": dataset_fingerprint(zeilen,
                                                           ausgewaehlt),
            },
            "row_identity_stable": True,
            "selected_is_subset_of_research": True,
            "meta": ansichten["meta"],
        },

        "fingerprints": {
            "schema": schema_fingerprint(),
            "target": target_fingerprint(zeilen),
            "research_dataset": dataset_fingerprint(zeilen, forschung),
            "selected_dataset": dataset_fingerprint(zeilen, ausgewaehlt),
            "what_changes_them": {
                "target": ("jede Aenderung an home_goals, away_goals, "
                           "outcome oder an der Zeilenidentitaet"),
                "dataset": ("zusaetzlich jede Aenderung an einem "
                            "genutzten Merkmalswert, an der Baseline "
                            "oder an der MerkmalsMENGE"),
                "schema": ("jede Aenderung an Gruppenzuschnitt, Status, "
                           "Kandidat, Modellfamilie oder Stichtagsregel "
                           "- ohne eine einzige Datenzeile"),
                "feature_order": ("kanonisch sortiert; die Reihenfolge "
                                  "der Uebergabe aendert den Wert NICHT, "
                                  "eine andere Merkmalsmenge schon"),
            },
        },

        "families": familien,
        "non_feature_components": {k: dict(v) for k, v
                                   in sorted(NON_FEATURE_COMPONENTS.items())},
        "feature_freeze": feature_freeze(optional_sources),

        "cutoff_contract": {
            "hour": ds.PREDICTION_CUTOFF_HOUR,
            "inclusive": ds.CUTOFF_INCLUSIVE,
            "rule": ("jede Beobachtung STRIKT vor dem Stichtag; der "
                     "Stichtag ist der Spieltag um "
                     f"{ds.PREDICTION_CUTOFF_HOUR:02d}:00"),
            "known_limit": KNOWN_CUTOFF_LIMIT,
        },

        "folds": {
            "outer": [dict(f) for f in ce.OUTER_FOLDS],
            "context": [dict(f) for f in ce.CONTEXT_FOLDS],
            "inner": ("evaluate.inner_split - Fold 1 am mittleren "
                      "Spieldatum, Fold 2 nach Saison. Nie zufaellig."),
            "min_reliable_n": ce.MIN_RELIABLE_N,
        },

        "pit_checks": pit,
        "invariants_tested_by_manipulation": [
            dict(e) for e in INVARIANTS_TESTED_BY_MANIPULATION],

        "evidence": EVIDENCE_ARTIFACTS,
        "holdout_status": HOLDOUT_STATUS,
        "mode_separation": MODE_SEPARATION,
        "runtime_parity": runtime_parity_report(),
        "known_limits": KNOWN_LIMITS,
    }

    manifest["manifest_fingerprint"] = manifest_fingerprint(manifest)
    manifest["fingerprint_excludes"] = list(MANIFEST_VOLATILE_FIELDS)
    return manifest


def _jetzt():
    import datetime

    return datetime.datetime.now(
        datetime.timezone.utc).isoformat(timespec="seconds")


def _paketversionen():
    """Die Fassungen, die das Ergebnis beeinflussen koennen."""
    versionen = {}
    for name in ("sklearn", "numpy", "scipy"):
        try:
            modul = __import__(name)
        except ImportError:                              # pragma: no cover
            versionen[name] = None
            continue
        versionen[name] = getattr(modul, "__version__", None)
    return versionen
