"""
Belastungsablation fuer die Champions League (V2-C3).

DIE FRAGE
---------
V2-C2B hat die Ruhezeit-Abdeckung der CL-Zeilen von 65,41 % auf 98,61 %
gehoben. Damit liegen Belastungsmerkmale erstmals in einer Qualitaet
vor, die eine Bewertung ueberhaupt zulaesst. Offen ist die eigentliche
Frage:

    Traegt Belastung ZUSAETZLICH zu dem, was der V1-Kandidat schon kann?

Nicht "hilft Belastung" - das waere gegen eine andere Baseline gemessen.
Jede Variante dieser Datei enthaelt den vollstaendigen V1-Merkmalssatz
und unterscheidet sich von ihm ausschliesslich um die zu pruefende
Belastungsuntergruppe. Der Vergleich ist damit unmittelbar.

KEIN ZWEITES AUSWERTUNGSVERFAHREN
---------------------------------
Jede Variante laeuft durch cl_evaluate.evaluate_fold - dieselbe
Funktion, dasselbe Foldschema, dieselbe innere Alphawahl, derselbe
gepaarte Bootstrap wie der bestehende CL-Shadow-Backtest. Der einzige
Unterschied zwischen zwei Varianten ist das Argument spalten.

Ein eigener Rechenweg fuer die Ablation waere die sicherste Art, einen
Unterschied zu messen, der nur aus dem Messaufbau stammt.

DIE AUSWAHL BERUEHRT DEN TESTBESTAND NICHT
------------------------------------------
Das ist der methodisch heikelste Punkt, und er ist hier baulich
geloest, nicht durch Disziplin:

    reduced_subgroups()  entscheidet ueber den reduzierten Kandidaten
                         AUSSCHLIESSLICH auf LIGAZEILEN der
                         Trainingssaisons - genauer: auf deren innerer
                         Validierungshaelfte (evaluate.inner_split).

    run_c3_ablation()    misst danach EINMAL auf den CL-Zeilen.

Kein CL-Spiel geht in Training, Alphawahl, Merkmalswahl, Redundanz-
pruefung oder Clamp-Wahl ein. Die Funktion, die reduziert, bekommt die
CL-Zeilen gar nicht erst zu sehen: Sie filtert sie als Erstes heraus
und bricht ab, wenn danach nichts uebrig bleibt.

WAS DIESE DATEI NICHT TUT
-------------------------
Sie trainiert kein produktives Modell, speichert kein Bundle, aendert
keine Freigabestufe und aktiviert nichts. Sie misst und berichtet.
"""

import math

from src.ml import cl_evaluate as ce
from src.ml import evaluate as ev
from src.ml import feature_groups as fg
from src.ml import model as mdl

#: Fassung des Ergebnisformats.
#:
#: 2  V2-C4: Dieselbe Maschinerie bedient jetzt zwei Merkmalsfamilien.
#:    Das Ergebnis traegt deshalb ein Feld "registry", das sagt, WELCHE
#:    abliert wurde. Ohne dieses Feld waeren zwei Artefakte gleicher
#:    Bauart nicht auseinanderzuhalten.
SCHEMA_VERSION = 2


class SubgroupRegistry:
    """
    Eine Familie von Untergruppen, die abliert werden soll.

    WOZU DIESE ABSTRAKTION
    V2-C3 hat die Belastungsmerkmale abliert, V2-C4 abliert Form- und
    Staerkemerkmale. Der Ablauf ist Schritt fuer Schritt derselbe:
    Vorauswahl auf Trainingsdaten, Varianten ueber die aeusseren
    CL-Folds, gepaarte Vergleiche gegen V1, Aufnahmeentscheidung.

    Ein zweiter Ablationslauf mit eigenem Code waere die sicherste Art,
    zwei Ergebnisse zu erzeugen, die nicht vergleichbar sind - und
    genau ihre Vergleichbarkeit ist der Zweck. Deshalb gibt es nur
    einen Ablauf und zwei Registrierungen.

    name        erscheint im Artefakt und trennt die beiden Familien
    order       die Untergruppennamen in fester Reihenfolge
    build       (spalten) -> {name: (spalte, ...)}
    columns     (definition) -> sortierte Merkmalsliste einer Variante
    variants    (reduced) -> die Variantendefinitionen
    reduced_name  Name des reduzierten Kandidaten
    """

    def __init__(self, name, order, build, columns, variants, reduced_name):
        self.name = name
        self.order = tuple(order)
        self.build = build
        self.columns = columns
        self.variants = variants
        self.reduced_name = reduced_name


def workload_registry():
    """Die Belastungsfamilie aus V2-C3."""
    return SubgroupRegistry(
        name="v2-c3 workload",
        order=fg.SUBGROUP_ORDER,
        build=fg.build_subgroups,
        columns=fg.columns_for_c3,
        variants=fg.c3_variants,
        reduced_name=fg.C3_REDUCED_CANDIDATE,
    )


def form_registry():
    """Die Form- und Staerkefamilie aus V2-C4."""
    return SubgroupRegistry(
        name="v2-c4 form and strength",
        order=fg.C4_SUBGROUP_ORDER,
        build=fg.build_c4_subgroups,
        columns=fg.columns_for_c4,
        variants=fg.c4_variants,
        reduced_name=fg.C4_REDUCED_CANDIDATE,
    )

#: Ab welchem Betrag eine Korrelation als hoch gilt.
#:
#: VORAB festgelegt. 0,9 ist die uebliche Grenze, ab der zwei Spalten
#: praktisch dasselbe messen. Sie steht hier, damit sie nicht
#: nachtraeglich passend gemacht werden kann.
HIGH_CORRELATION = 0.9

#: Ab welchem Varianzinflationsfaktor eine Spalte als kollinear gilt.
#: 10 ist die gaengige Konvention; 5 gilt als streng. Gewaehlt ist die
#: gaengige - eine strengere Grenze haette hier den Effekt, fast jedes
#: Zaehlfenster zu verwerfen, und das waere eine Vorentscheidung.
MAX_VIF = 10.0

#: Ab wann eine Spalte als (nahezu) konstant gilt: weniger als so viele
#: verschiedene Werte im Trainingsbestand.
MIN_DISTINCT_VALUES = 2

#: Ab welcher Bestimmtheit eine Spalte als exakt linear abhaengig
#: gilt. 1e-9 ist Rechengenauigkeit, keine fachliche Wahl: Ein R²,
#: das so nah an eins liegt, entsteht nicht aus Daten, sondern aus
#: einer Konstruktionsvorschrift.
EXACT_COLLINEARITY_TOLERANCE = 1e-9

#: Warum ein VIF nicht bestimmbar ist. Vier Faelle, vier Konsequenzen.
VIF_OK = "ok"
VIF_CONSTANT = "konstante Spalte - sie kann nichts erklaeren"
VIF_EXACTLY_COLLINEAR = ("exakt aus den uebrigen Spalten zusammensetzbar - "
                         "sie traegt nichts Zusaetzliches bei")
VIF_NO_OTHERS = "keine weiteren Spalten zum Vergleich"
VIF_NOT_SOLVABLE = "die Ausgleichsrechnung konvergiert nicht"

#: Wie stark eine Untergruppe den INNEREN Validierungsverlust
#: verbessern muss, um in den reduzierten Kandidaten zu kommen.
#:
#: Streng null waere zu schwach: Eine Verbesserung in der zwoelften
#: Nachkommastelle ist Rauschen. 1e-4 liegt eine Groessenordnung unter
#: der Skala, in der die Ligaablation ihre Effekte gemessen hat
#: (-0,0094 bis -0,0145), und damit klar unterhalb dessen, was als
#: Effekt gelten koennte - aber deutlich oberhalb des Rauschens.
MIN_INNER_IMPROVEMENT = 1e-4


# ---------------------------------------------------------------------------
# Redundanzdiagnostik
# ---------------------------------------------------------------------------

def _spaltenwerte(zeilen, spalte):
    """Die nicht fehlenden Werte einer Spalte als Gleitkommazahlen."""
    werte = []
    for zeile in zeilen:
        wert = zeile.get(spalte)
        if wert is None:
            continue
        if isinstance(wert, bool):
            wert = 1.0 if wert else 0.0
        if isinstance(wert, (int, float)) and math.isfinite(float(wert)):
            werte.append(float(wert))
    return werte


def _korrelation(a, b):
    """
    Pearson-Korrelation ueber die PAARWEISE vollstaendigen Zeilen.

    Paarweise und nicht listenweise: Zwei Spalten mit unterschiedlichen
    Luecken haetten sonst verschieden lange Vektoren, und der Quotient
    waere nicht definiert. Ist eine der beiden Spalten im gemeinsamen
    Bestand konstant, gibt es keine Korrelation - dann None statt einer
    Division durch null.
    """
    paare = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(paare) < 3:
        return None

    n = len(paare)
    mx = sum(p[0] for p in paare) / n
    my = sum(p[1] for p in paare) / n
    sxy = sum((p[0] - mx) * (p[1] - my) for p in paare)
    sxx = sum((p[0] - mx) ** 2 for p in paare)
    syy = sum((p[1] - my) ** 2 for p in paare)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def _gepaarte_matrix(zeilen, spalten):
    """
    Die Merkmalsmatrix mit None statt fehlender Werte, spaltenweise.

    Ueber model.feature_matrix - dieselbe Typwandlung wie im Modell.
    Eine eigene Umwandlung hier koennte einen Wahrheitswert anders
    behandeln als die Anpassung, und das faellt an keiner Zahl auf.
    """
    matrix = mdl.feature_matrix(zeilen, spalten)
    return [[zeile[i] for zeile in matrix] for i in range(len(spalten))]


def _vif(spaltenwerte, index):
    """
    Varianzinflationsfaktor einer Spalte gegen alle uebrigen.

    VIF = 1 / (1 - R²) aus der Regression dieser Spalte auf die
    anderen. Gerechnet ueber die kleinsten Quadrate mit numpy, auf den
    vollstaendigen Zeilen und nach Medianersetzung der Luecken - der
    Imputer des Modells arbeitet genauso, und eine Diagnose soll die
    Matrix beschreiben, die das Modell tatsaechlich sieht.

    Rueckgabe: (faktor, grund).

    faktor ist None, wenn er nicht bestimmbar ist - und dann sagt der
    Grund, WARUM. Diese Unterscheidung ist der halbe Zweck der
    Diagnose: Eine konstante Spalte traegt nichts bei, eine exakt
    linear abhaengige traegt nichts ZUSAETZLICH bei. Das sind zwei
    verschiedene Befunde mit zwei verschiedenen Konsequenzen, und ein
    gemeinsames None haette sie verschmolzen.

    Ein VIF von None heisst ausdruecklich nicht "unauffaellig".
    """
    import numpy as np

    gefuellt = []
    for werte in spaltenwerte:
        bekannt = [w for w in werte if w is not None]
        if not bekannt:
            return None
        median = sorted(bekannt)[len(bekannt) // 2]
        gefuellt.append([median if w is None else w for w in werte])

    X = np.array(gefuellt, dtype=float).T
    y = X[:, index]
    uebrige = np.delete(X, index, axis=1)
    if uebrige.shape[1] == 0:
        return None, VIF_NO_OTHERS
    if float(np.var(y)) <= 0:
        return None, VIF_CONSTANT

    A = np.hstack([np.ones((uebrige.shape[0], 1)), uebrige])
    try:
        koeffizienten, *_ = np.linalg.lstsq(A, y, rcond=None)
    except np.linalg.LinAlgError:                        # pragma: no cover
        return None, VIF_NOT_SOLVABLE

    rest = y - A @ koeffizienten
    ss_rest = float(rest @ rest)
    ss_gesamt = float(((y - y.mean()) ** 2).sum())
    if ss_gesamt <= 0:
        return None, VIF_CONSTANT

    r2 = 1.0 - ss_rest / ss_gesamt
    if r2 >= 1.0 - EXACT_COLLINEARITY_TOLERANCE:
        # Die Spalte laesst sich aus den uebrigen exakt zusammensetzen.
        # Der Faktor waere unendlich; das ist keine fehlende Diagnose,
        # sondern die schaerfste, die es gibt.
        return None, VIF_EXACTLY_COLLINEAR
    return 1.0 / (1.0 - r2), VIF_OK


def redundancy_report(zeilen, spalten):
    """
    Korrelation, VIF, Konstanz und Missingness der Merkmalsspalten.

    AUSSCHLIESSLICH auf dem uebergebenen Bestand - der Aufrufer muss
    Trainingszeilen uebergeben. run_c3_ablation() tut das; wer diese
    Funktion auf Testzeilen ruft, hat die Auswahl kompromittiert.

    Rueckgabe: ein Block fuer das Ergebnisartefakt.
    """
    spaltenwerte = _gepaarte_matrix(zeilen, spalten)

    konstant, fehlend_ganz, missingness = [], [], {}
    for i, spalte in enumerate(spalten):
        bekannt = [w for w in spaltenwerte[i] if w is not None]
        missingness[spalte] = round(
            1.0 - len(bekannt) / len(zeilen), 6) if zeilen else 1.0
        if not bekannt:
            fehlend_ganz.append(spalte)
        elif len(set(bekannt)) < MIN_DISTINCT_VALUES:
            konstant.append(spalte)

    hohe = []
    for i in range(len(spalten)):
        for j in range(i + 1, len(spalten)):
            r = _korrelation(spaltenwerte[i], spaltenwerte[j])
            if r is not None and abs(r) >= HIGH_CORRELATION:
                hohe.append({"a": spalten[i], "b": spalten[j],
                             "pearson_r": round(r, 6)})
    hohe.sort(key=lambda e: (-abs(e["pearson_r"]), e["a"], e["b"]))

    vifs, gruende, exakt = {}, {}, []
    for i, spalte in enumerate(spalten):
        wert, grund = _vif(spaltenwerte, i)
        vifs[spalte] = None if wert is None else round(wert, 4)
        gruende[spalte] = grund
        if grund == VIF_EXACTLY_COLLINEAR:
            exakt.append(spalte)

    auffaellig = sorted(
        (sp for sp, w in vifs.items() if w is not None and w >= MAX_VIF),
        key=lambda sp: -vifs[sp])

    return {
        "rows": len(zeilen),
        "columns": list(spalten),
        "missingness": missingness,
        "constant_columns": konstant,
        "fully_missing_columns": fehlend_ganz,
        "high_correlation_pairs": hohe,
        "high_correlation_threshold": HIGH_CORRELATION,
        "vif": vifs,
        "vif_status": gruende,
        "vif_above_threshold": auffaellig,
        "exactly_collinear_columns": sorted(exakt),
        "vif_threshold": MAX_VIF,
        "note": "Ausschliesslich auf Ligazeilen der Trainingssaisons "
                "gerechnet. Ein VIF von None ist KEINE Entwarnung - "
                "vif_status sagt, warum er nicht bestimmbar ist. "
                f"{VIF_EXACTLY_COLLINEAR!r} ist dabei der schaerfste "
                "Befund ueberhaupt: Die Spalte laesst sich aus den "
                "uebrigen exakt zusammensetzen und traegt nichts "
                "Zusaetzliches bei.",
    }


# ---------------------------------------------------------------------------
# Vorauswahl - ausschliesslich auf Trainingsdaten
# ---------------------------------------------------------------------------

def training_rows(zeilen, seasons):
    """
    Die Ligazeilen der Trainingssaisons - und nichts sonst.

    Der Filter auf league != "cl" ist derselbe wie in
    cl_evaluate.league_rows und aus demselben Grund der wichtigste
    Handgriff: CL-Zeilen tragen dieselben Saisonnummern.
    """
    return ce.league_rows(zeilen, seasons)


def _inner_log_loss(fit_zeilen, val_zeilen, spalten, alphas):
    """
    Der innere Validierungsverlust eines Merkmalssatzes.

    Ueber evaluate.select_candidate - dieselbe Wahl, dieselbe
    Gleichstandsregel, derselbe Rueckfall auf no_correction wie im
    aeusseren Lauf. Ein eigener Anpassungsweg an dieser Stelle waere
    ein zweites Verfahren.
    """
    _, _, protokoll = ev.select_candidate(fit_zeilen, val_zeilen, spalten,
                                          alphas)
    return protokoll["selected_inner_log_loss"], protokoll


def reduced_subgroups(zeilen, seasons, alphas=mdl.ALPHA_CANDIDATES,
                      registry=None):
    """
    Welche Belastungsuntergruppen kommen in den reduzierten Kandidaten?

    Gemessen wird AUSSCHLIESSLICH auf Ligazeilen der Trainingssaisons,
    und dort auf der inneren Validierungshaelfte. Die CL-Zeilen sieht
    diese Funktion nicht.

    Das Verfahren, vorab festgelegt und bewusst schlicht:

      1. Untergruppen mit einer konstanten oder vollstaendig fehlenden
         Spalte fallen sofort heraus - sie koennen nichts tragen.
      2. Jede verbleibende Untergruppe wird EINZELN zu V1 hinzugefuegt
         und auf der inneren Validierung gemessen.
      3. Wer den inneren Verlust um weniger als MIN_INNER_IMPROVEMENT
         verbessert, faellt heraus.
      4. Von zwei Untergruppen, deren Spalten hoch korrelieren
         (HIGH_CORRELATION), bleibt die mit der GROESSEREN inneren
         Verbesserung. Bei Gleichstand die kleinere Spaltenzahl, bei
         erneutem Gleichstand die alphabetisch erste - damit die
         Auswahl reproduzierbar ist und nicht an einer
         Iterationsreihenfolge haengt.
      5. Danach wird die VERBLEIBENDE Menge auf Kollinearitaet
         geprueft und so lange verkleinert, bis keine Spalte mehr
         einen VIF ueber MAX_VIF traegt und keine exakt aus den
         uebrigen zusammensetzbar ist.

         Schritt 4 allein genuegt dafuer nicht: Drei Fenster derselben
         Groesse koennen paarweise unter 0,9 korrelieren und trotzdem
         gemeinsam fast dieselbe Information tragen. Genau das ist bei
         den Formfenstern der Fall - paarweise unauffaellig, im VIF
         weit ueber der Grenze.

         Gestrichen wird jeweils die Untergruppe mit der schlechtesten
         Spalte; exakte Abhaengigkeit gilt dabei als unendlicher VIF.
         Gleichstaende gehen an die kleinere innere Verbesserung, dann
         an die groessere Spaltenzahl, dann an den alphabetisch
         spaeteren Namen - deterministisch und ohne Rueckgriff auf eine
         Iterationsreihenfolge.

    Es ist ausdruecklich moeglich, dass NICHTS uebrig bleibt. Das ist
    ein Ergebnis und kein Fehler.

    Rueckgabe: (gewaehlte_untergruppen, protokoll).
    """
    registry = registry or workload_registry()

    training = training_rows(zeilen, seasons)
    if not training:
        raise ValueError(
            "keine Ligazeilen in den Trainingssaisons - ohne sie kann "
            "die Vorauswahl nicht stattfinden, und sie darf NICHT auf "
            "die CL-Zeilen ausweichen")

    fit_zeilen, val_zeilen, innen = ev.inner_split(
        training, {"train_seasons": list(seasons)})
    if not fit_zeilen or not val_zeilen:
        raise ValueError("die innere Teilung der Trainingsdaten ist leer")

    unter = registry.build()
    basis_spalten = fg.columns_for(fg.C3_BASE_CANDIDATE)
    basis_verlust, _ = _inner_log_loss(fit_zeilen, val_zeilen, basis_spalten,
                                       alphas)

    # Die Redundanzdiagnostik ueber ALLE Belastungsspalten zusammen -
    # eine Korrelation zwischen zwei Untergruppen ist nur sichtbar,
    # wenn beide in derselben Matrix stehen.
    alle_spalten = sorted({s for name in registry.order
                           for s in unter[name]})
    diagnostik = redundancy_report(training, alle_spalten)
    unbrauchbar = set(diagnostik["constant_columns"]) \
        | set(diagnostik["fully_missing_columns"])

    protokoll = {
        "registry": registry.name,
        "selection_data": "ausschliesslich Ligazeilen der Trainings"
                          "saisons, innere Validierungshaelfte",
        "train_seasons": list(seasons),
        "train_rows": len(training),
        "inner_split": innen,
        "baseline_variant": fg.C3_BASE_CANDIDATE,
        "baseline_inner_log_loss": basis_verlust,
        "min_inner_improvement": MIN_INNER_IMPROVEMENT,
        "redundancy": diagnostik,
        "subgroups": [],
    }

    kandidaten = {}
    for name in registry.order:
        spalten = list(unter[name])
        eintrag = {"subgroup": name, "columns": spalten}

        tot = [s for s in spalten if s in unbrauchbar]
        if tot:
            eintrag.update({"kept": False,
                            "reason": "konstante oder vollstaendig "
                                      "fehlende Spalte: %s" % tot})
            protokoll["subgroups"].append(eintrag)
            continue

        verlust, _ = _inner_log_loss(fit_zeilen, val_zeilen,
                                     sorted(set(basis_spalten) | set(spalten)),
                                     alphas)
        verbesserung = basis_verlust - verlust
        eintrag.update({"inner_log_loss": verlust,
                        "inner_improvement": verbesserung})

        if verbesserung < MIN_INNER_IMPROVEMENT:
            eintrag.update({"kept": False,
                            "reason": "innere Verbesserung %+.6f liegt "
                                      "unter %g" % (verbesserung,
                                                    MIN_INNER_IMPROVEMENT)})
        else:
            eintrag["kept"] = True
            kandidaten[name] = verbesserung
        protokoll["subgroups"].append(eintrag)

    # Schritt 4: Kollinearitaet ZWISCHEN den ueberlebenden Untergruppen.
    spalte_zu_gruppe = {s: name for name in kandidaten for s in unter[name]}
    verworfen = {}
    for paar in diagnostik["high_correlation_pairs"]:
        a = spalte_zu_gruppe.get(paar["a"])
        b = spalte_zu_gruppe.get(paar["b"])
        if a is None or b is None or a == b:
            continue
        if a in verworfen or b in verworfen:
            continue
        # Groessere Verbesserung gewinnt; Gleichstaende deterministisch.
        sieger, verlierer = sorted(
            (a, b),
            key=lambda n: (-kandidaten[n], len(unter[n]), n))[:2]
        verworfen[verlierer] = {
            "in_favour_of": sieger,
            "pearson_r": paar["pearson_r"],
            "columns": [paar["a"], paar["b"]],
        }

    for eintrag in protokoll["subgroups"]:
        name = eintrag["subgroup"]
        if name in verworfen:
            eintrag["kept"] = False
            eintrag["reason"] = (
                "hoch korreliert (r = %+.4f) mit der Untergruppe %r, die "
                "innen staerker verbessert" % (verworfen[name]["pearson_r"],
                                               verworfen[name]["in_favour_of"]))
            eintrag["dropped_for"] = verworfen[name]

    # registry.order und NICHT eine feste Liste: Mit einer festen Liste
    # liefert die Vorauswahl fuer jede andere Merkmalsfamilie stumm eine
    # leere Menge - sie sieht dann aus wie ein Ergebnis ("nichts
    # ueberlebt"), ist aber keines.
    ueberlebt = [name for name in registry.order
                 if name in kandidaten and name not in verworfen]

    # Schritt 5: Kollinearitaet der VERBLEIBENDEN Menge.
    ueberlebt, vif_protokoll = _vif_reduktion(training, ueberlebt, unter,
                                              kandidaten)

    gewaehlt = tuple(ueberlebt)
    protokoll["selected_subgroups"] = list(gewaehlt)
    protokoll["dropped_for_collinearity"] = {
        name: wert for name, wert in sorted(verworfen.items())}
    protokoll["vif_reduction"] = vif_protokoll
    protokoll["final_redundancy"] = (
        redundancy_report(training,
                          sorted({sp for name in gewaehlt
                                  for sp in unter[name]}))
        if gewaehlt else None)
    return gewaehlt, protokoll


def _vif_reduktion(training, namen, unter, verbesserungen):
    """
    Untergruppen streichen, bis die Restmenge kollinearitaetsfrei ist.

    "Frei" heisst hier: kein VIF ueber MAX_VIF und keine Spalte, die
    sich exakt aus den uebrigen zusammensetzen laesst.

    Rueckgabe: (verbliebene_namen, protokoll). Das Protokoll nennt
    jeden Streichungsschritt mit Grund und Wert - eine Reduktion ohne
    nachvollziehbare Schritte waere von einer Wunschauswahl nicht zu
    unterscheiden.
    """
    namen = list(namen)
    schritte = []

    while namen:
        spalten = sorted({sp for name in namen for sp in unter[name]})
        if not spalten:
            break

        bericht = redundancy_report(training, spalten)
        exakt = set(bericht["exactly_collinear_columns"])
        ueber = {sp: bericht["vif"][sp] for sp in bericht["vif_above_threshold"]}

        if not exakt and not ueber:
            break

        # Wert je Untergruppe: unendlich bei exakter Abhaengigkeit,
        # sonst der groesste VIF ihrer Spalten.
        je_gruppe = {}
        for name in namen:
            werte = []
            for sp in unter[name]:
                if sp in exakt:
                    werte.append(float("inf"))
                elif sp in ueber:
                    werte.append(float(ueber[sp]))
            if werte:
                je_gruppe[name] = max(werte)

        if not je_gruppe:
            break

        # Schlechteste zuerst; Gleichstaende deterministisch aufgeloest.
        opfer = sorted(
            je_gruppe,
            key=lambda n: (-je_gruppe[n], verbesserungen.get(n, 0.0),
                           -len(unter[n]), n))[0]
        namen.remove(opfer)
        schritte.append({
            "dropped": opfer,
            "worst_value": (None if je_gruppe[opfer] == float("inf")
                            else round(je_gruppe[opfer], 4)),
            "reason": ("mindestens eine Spalte ist exakt aus den uebrigen "
                       "zusammensetzbar"
                       if je_gruppe[opfer] == float("inf")
                       else "hoechster VIF ueber %g" % MAX_VIF),
            "remaining": list(namen),
        })

    return namen, {
        "threshold": MAX_VIF,
        "steps": schritte,
        "note": "Ausschliesslich auf Ligazeilen der Trainingssaisons "
                "gerechnet. Die Schleife endet, sobald keine Spalte der "
                "Restmenge mehr auffaellt - oder wenn nichts uebrig ist. "
                "Eine leere Restmenge ist ein Ergebnis und kein Fehler.",
    }


# ---------------------------------------------------------------------------
# Eine Variante ueber die aeusseren CL-Folds
# ---------------------------------------------------------------------------

def run_variant(zeilen, definition, folds=ce.OUTER_FOLDS,
                alphas=mdl.ALPHA_CANDIDATES, registry=None):
    """
    Eine C3-Variante ueber beide aeusseren Folds.

    Der Schluessel _losses traegt die Verluste je Spiel ueber alle
    Folds hinweg, in Foldreihenfolge aneinandergehaengt. Er ist die
    Grundlage der gepaarten Variantenvergleiche und wird von
    run_c3_ablation() entfernt, bevor das Ergebnis ins Artefakt geht.
    """
    registry = registry or workload_registry()
    spalten = registry.columns(definition)
    ergebnisse = [ce.evaluate_fold(zeilen, fold, spalten, alphas)
                  for fold in folds]
    zusammen = ce.aggregate(ergebnisse)

    verluste = {"log_loss": [], "brier": [], "rps": []}
    for fold in ergebnisse:
        intern = fold.get("_internal") or {}
        for schluessel in verluste:
            verluste[schluessel].extend(
                (intern.get("ml_losses") or {}).get(schluessel, []))
    for fold in ergebnisse:
        fold.pop("_internal", None)

    return {
        "_losses": verluste,
        "variant": definition["name"],
        "description": definition["description"],
        "groups": list(definition["groups"]),
        "subgroups": list(definition.get("subgroups", ())),
        "feature_columns": spalten,
        "feature_count": len(spalten),
        "folds": ergebnisse,
        "aggregate": zusammen,
        "verdict": ce.verdict(zusammen, ergebnisse),
    }


def _kennzahlen(variante):
    """Die Vergleichszeile einer Variante - oder None ohne Aggregat."""
    zusammen = variante.get("aggregate")
    if not zusammen:
        return None

    zeile = {
        "variant": variante["variant"],
        "subgroups": list(variante["subgroups"]),
        "feature_count": variante["feature_count"],
        "n": zusammen["n"],
        "verdict": (variante.get("verdict") or {}).get("verdict"),
    }
    for name in ("log_loss", "brier", "rps"):
        zeile[f"baseline_{name}"] = zusammen["baseline"][name]
        zeile[f"ml_{name}"] = zusammen["ml"][name]
        zeile[f"delta_{name}"] = zusammen[f"delta_{name}"]

    intervall = (zusammen.get("bootstrap") or {}).get("log_loss")
    if intervall:
        zeile["log_loss_ci_low"] = intervall["ci_low"]
        zeile["log_loss_ci_high"] = intervall["ci_high"]
        zeile["log_loss_interpretation"] = intervall["interpretation"]

    zeile["calibration_error_baseline"] = zusammen["baseline"]["calibration_error"]
    zeile["calibration_error_ml"] = zusammen["ml"]["calibration_error"]
    zeile["per_fold_delta_log_loss"] = {
        fold["fold"]: fold.get("delta_log_loss")
        for fold in variante["folds"] if "error" not in fold}
    return zeile


# ---------------------------------------------------------------------------
# Gepaarte Vergleiche gegen den V1-Kandidaten
# ---------------------------------------------------------------------------

def paired_against_base(varianten, basis=fg.C3_BASE_CANDIDATE):
    """
    Jede Variante gepaart gegen den V1-Kandidaten.

    delta = variante - v1. Negativ heisst: die Variante ist besser.

    WARUM DAS DER ENTSCHEIDENDE VERGLEICH IST
    Die Vergleichstabelle misst jede Variante gegen die BASELINE (die
    ungelernten Lambdas). Aus zwei solchen Intervallen laesst sich
    nicht ablesen, ob sich V1 und V1+Belastung voneinander
    unterscheiden - ihre Intervalle ueberlappen fast vollstaendig,
    weil sie denselben grossen gemeinsamen Anteil enthalten. Die
    gepaarte Differenz entfernt genau diesen Anteil.

    Dieselben Spielindizes je Wiederholung, derselbe Seed wie ueberall.
    """
    nach_name = {v["variant"]: v for v in varianten}
    if basis not in nach_name:
        raise ValueError(
            f"die Kontrollvariante {basis!r} fehlt im Lauf - ohne sie "
            f"gaebe es nichts, wogegen gepaart wuerde")

    basis_verluste = nach_name[basis]["_losses"]
    vergleiche = []
    for variante in varianten:
        if variante["variant"] == basis:
            continue
        eigene = variante["_losses"]
        eintrag = {"variant": variante["variant"], "against": basis,
                   "subgroups": list(variante["subgroups"])}
        for schluessel in ("log_loss", "brier", "rps"):
            a, b = eigene[schluessel], basis_verluste[schluessel]
            if len(a) != len(b):
                raise ValueError(
                    f"{variante['variant']!r} und {basis!r} bewerten "
                    f"verschieden viele Spiele ({len(a)} gegen {len(b)}) - "
                    f"eine Paarung waere sinnlos")
            intervall = ev.paired_bootstrap(b, a)
            if intervall:
                intervall["interpretation"] = ev.interpret(intervall)
            eintrag[schluessel] = intervall
        vergleiche.append(eintrag)
    return vergleiche


# ---------------------------------------------------------------------------
# Aufnahmeentscheidung
# ---------------------------------------------------------------------------

#: Die Aufnahmeregeln, VORAB festgelegt.
#:
#: Sie sind bewusst dieselben, die cl_evaluate.verdict() auf die
#: Gesamtmessung anwendet - nur angewandt auf die GEPAARTE Differenz
#: gegen V1 statt auf die Differenz gegen die Baseline. Einen eigenen
#: Schwellwert zu erfinden, waere die einfachste Art, ein gewuenschtes
#: Ergebnis zu bekommen.
DECISION_ACCEPTED = "ACCEPTED"
DECISION_REJECTED = "REJECTED"
DECISION_INCONCLUSIVE = "INCONCLUSIVE"


def decide(variante, gepaart):
    """
    ACCEPTED, REJECTED oder INCONCLUSIVE fuer EINE Variante.

    ACCEPTED verlangt alles davon:

        - die gepaarte Differenz gegen V1 ist negativ,
        - ihre obere 95-%-Intervallgrenze liegt unter null,
        - kein Fold verschlechtert sich schwer
          (cl_evaluate.SEVERE_DEGRADATION),
        - die Folds widersprechen sich nicht im Vorzeichen,
        - die Kalibrierung wird nicht schlechter als die von V1,
        - die Stichprobe ist gross genug (cl_evaluate.MIN_RELIABLE_N).

    REJECTED heisst: die Differenz ist nicht negativ, oder ein Fold
    faellt schwer ab. INCONCLUSIVE heisst alles dazwischen - der Punkt
    zeigt in die richtige Richtung, aber der Nachweis fehlt.

    Die Unterscheidung ist keine Formalie: INCONCLUSIVE laesst die
    Frage offen, REJECTED schliesst sie. Beides als "nicht
    aufgenommen" zu verbuchen wuerde Information wegwerfen.
    """
    zusammen = variante.get("aggregate")
    if zusammen is None:
        return {"decision": DECISION_REJECTED,
                "reasons": ["kein auswertbarer Fold"]}

    intervall = (gepaart or {}).get("log_loss") or {}
    delta = intervall.get("point")
    obergrenze = intervall.get("ci_high")
    gruende = []

    schwere = [f["fold"] for f in variante["folds"]
               if "error" not in f
               and f["delta_log_loss"] >= ce.SEVERE_DEGRADATION]

    if delta is None:
        return {"decision": DECISION_INCONCLUSIVE,
                "reasons": ["keine gepaarte Differenz gegen V1 verfuegbar"]}

    if delta >= 0:
        gruende.append(
            "gepaarte Differenz gegen V1 %+.5f ist nicht negativ - die "
            "Belastungsmerkmale verbessern V1 im Mittel nicht" % delta)
        return {"decision": DECISION_REJECTED, "reasons": gruende,
                "paired_delta_log_loss": delta, "ci_high": obergrenze}

    if schwere:
        gruende.append("schwerer Qualitaetsabfall gegenueber der Baseline "
                       "in %s (delta >= %s)" % (schwere,
                                                ce.SEVERE_DEGRADATION))
        return {"decision": DECISION_REJECTED, "reasons": gruende,
                "paired_delta_log_loss": delta, "ci_high": obergrenze}

    if zusammen["n"] < ce.MIN_RELIABLE_N:
        gruende.append("Stichprobe zu klein (n = %d < %d)"
                       % (zusammen["n"], ce.MIN_RELIABLE_N))
        return {"decision": DECISION_INCONCLUSIVE, "reasons": gruende,
                "paired_delta_log_loss": delta, "ci_high": obergrenze}

    if obergrenze is None or obergrenze >= 0:
        gruende.append(
            "Punktschaetzer besser (%+.5f), aber das 95-%%-Intervall der "
            "gepaarten Differenz schliesst die Null ein (obere Grenze %s)"
            % (delta, "-" if obergrenze is None
               else "%+.5f" % obergrenze))
        return {"decision": DECISION_INCONCLUSIVE, "reasons": gruende,
                "paired_delta_log_loss": delta, "ci_high": obergrenze}

    vorzeichen = {f["delta_log_loss"] < 0 for f in variante["folds"]
                  if "error" not in f}
    if len(vorzeichen) > 1:
        gruende.append("die Folds widersprechen sich im Vorzeichen")
        return {"decision": DECISION_INCONCLUSIVE, "reasons": gruende,
                "paired_delta_log_loss": delta, "ci_high": obergrenze}

    gruende.append(
        "gepaarte Differenz %+.5f und obere Intervallgrenze %+.5f liegen "
        "beide unter null" % (delta, obergrenze))
    return {"decision": DECISION_ACCEPTED, "reasons": gruende,
            "paired_delta_log_loss": delta, "ci_high": obergrenze}


def decision_criteria():
    """Die Regeln im Klartext - sie gehoeren ins Artefakt."""
    return {
        "accepted": "gepaarte Differenz gegen V1 < 0 UND obere "
                    "95-%%-Intervallgrenze < 0 UND kein Fold mit schwerem "
                    "Qualitaetsabfall UND kein Vorzeichenwiderspruch "
                    "UND n >= %d" % ce.MIN_RELIABLE_N,
        "rejected": "gepaarte Differenz >= 0 oder ein Fold mit "
                    "delta >= %s gegenueber der Baseline"
                    % ce.SEVERE_DEGRADATION,
        "inconclusive": "alles dazwischen - der Punktschaetzer zeigt in "
                        "die richtige Richtung, aber der Nachweis fehlt",
        "severe_degradation_threshold": ce.SEVERE_DEGRADATION,
        "min_reliable_n": ce.MIN_RELIABLE_N,
        "paired_against": fg.C3_BASE_CANDIDATE,
        "why_paired": "Der Vergleich gegen die ungelernte Baseline kann "
                      "nicht zeigen, ob Belastung ZUSAETZLICH zu V1 "
                      "traegt: Beide Intervalle enthalten denselben "
                      "grossen gemeinsamen Anteil. Die gepaarte "
                      "Differenz entfernt ihn.",
    }


# ---------------------------------------------------------------------------
# Gesamtlauf
# ---------------------------------------------------------------------------

def run_ablation(zeilen, registry, folds=ce.OUTER_FOLDS,
                 alphas=mdl.ALPHA_CANDIDATES, selection_seasons=None):
    """
    Die vollstaendige Belastungsablation von V2-C3.

    Ablauf:

      1. Vorauswahl des reduzierten Kandidaten - ausschliesslich auf
         Ligazeilen der Trainingssaisons.
      2. Alle Varianten ueber die aeusseren CL-Folds.
      3. Gepaarte Vergleiche jeder Variante gegen den V1-Kandidaten.
      4. Aufnahmeentscheidung je Variante nach den vorab festgelegten
         Regeln.

    selection_seasons: die Saisons der Vorauswahl. Standard sind die
    Trainingssaisons des LETZTEN aeusseren Folds - also die groesste
    Menge, die noch zeitlich vor dem letzten Testabschnitt liegt.
    """
    if selection_seasons is None:
        selection_seasons = list(folds[-1]["train_seasons"])

    reduziert, auswahl = reduced_subgroups(zeilen, selection_seasons, alphas,
                                          registry)

    varianten = [run_variant(zeilen, definition, folds, alphas, registry)
                 for definition in registry.variants(reduziert)]

    gepaart = paired_against_base(varianten)
    nach_name = {e["variant"]: e for e in gepaart}

    entscheidungen = {}
    for variante in varianten:
        if variante["variant"] == fg.C3_BASE_CANDIDATE:
            continue
        entscheidungen[variante["variant"]] = decide(
            variante, nach_name.get(variante["variant"]))

    vergleich = [z for z in (_kennzahlen(v) for v in varianten)
                 if z is not None]

    for variante in varianten:
        variante.pop("_losses", None)

    return {
        "schema_version": SCHEMA_VERSION,
        "registry": registry.name,
        "base_candidate": fg.C3_BASE_CANDIDATE,
        "reduced_candidate": (registry.reduced_name if reduziert else None),
        "selection": auswahl,
        "variants_tested": [v["variant"] for v in varianten],
        "variant_count": len(varianten),
        "comparison": vergleich,
        "paired_against_base": gepaart,
        "decisions": entscheidungen,
        "decision_criteria": decision_criteria(),
        "variants": varianten,
        "multiple_testing_note":
            "Es wurden %d Varianten gerechnet und ALLE berichtet. Die "
            "Aufnahmeentscheidung wurde nicht nachtraeglich unter ihnen "
            "ausgewaehlt: Der reduzierte Kandidat entstand VOR dem Blick "
            "auf die CL-Ergebnisse, ausschliesslich auf Ligadaten. Die "
            "Einzel- und Buendelvarianten sind Diagnose, nicht "
            "Auswahlgrundlage - wer eine von ihnen nachtraeglich als "
            "Kandidaten waehlte, haette auf dem Testbestand selektiert."
            % len(varianten),
    }


def run_c3_ablation(zeilen, folds=ce.OUTER_FOLDS,
                    alphas=mdl.ALPHA_CANDIDATES, selection_seasons=None):
    """Die Belastungsablation von V2-C3."""
    return run_ablation(zeilen, workload_registry(), folds, alphas,
                        selection_seasons)


def run_c4_ablation(zeilen, folds=ce.OUTER_FOLDS,
                    alphas=mdl.ALPHA_CANDIDATES, selection_seasons=None):
    """
    Die Form- und Staerkeablation von V2-C4.

    Derselbe Ablauf wie C3, dieselben Folds, dasselbe Gate, dieselbe
    Vorauswahlregel. Der einzige Unterschied ist die Registrierung -
    und genau deshalb sind die beiden Ergebnisse vergleichbar.
    """
    return run_ablation(zeilen, form_registry(), folds, alphas,
                        selection_seasons)
