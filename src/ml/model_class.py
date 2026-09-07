"""
Transformationen, Interaktionen und Kalibrierung (V2-C8).

WORUM ES GEHT
-------------
V2-C5 und V2-C7 haben zwei verschiedene Probleme derselben Modellklasse
sichtbar gemacht:

    C5  Die Kontextmerkmale SCHADEN. Ursache gemessen: Ein
        Aggregatstand existiert nur bei Rueckspielen. Im
        Kontexttestbestand tragen 22 von 146 Zeilen einen; der
        Median-Imputer fuellt die uebrigen 124 mit dem Median dieser
        22. Ein Ligaphasenspiel bekommt damit einen Aggregatstand, den
        es per Definition nicht hat - und das Modell rechnet mit ihm.

    C7  Die Transfermerkmale HELFEN im Punktschaetzer, aber die
        Kalibrierung leidet. Ursache gemessen: Die Zaehlwerte sind
        nicht nur schief (arrivals_120d: Schiefe +2,06), sie liegen im
        Test auf einer ANDEREN SKALA als im Training - Median 16 gegen
        32 bei arrivals_365d. Ein linear angepasster Koeffizient wird
        damit auf den doppelten Wertebereich extrapoliert.

Dieses Modul baut die beiden zugehoerigen Werkzeuge - und nur sie:

    FeatureTransform   log1p und foldlokale Quantilbegrenzung
    Interaktionen      definitorisch bedingte Produkte
    Kalibrierung       auf INNEREN Validierungsvorhersagen gelernt

WARUM ALS PIPELINE-SCHRITT UND NICHT ALS DATENSATZSPALTEN
---------------------------------------------------------
Eine Quantilgrenze ist ein GELERNTER Parameter. Als Datensatzspalte
muesste sie ueber alle Saisons zugleich gebildet werden - und damit
ueber den aeusseren Testfold hinweg. Als erster Schritt der Pipeline
wird sie von pipeline.fit() ausschliesslich auf dem Trainingsfold
gelernt und von pipeline.predict() unveraendert angewandt.

Das loest zugleich die Paritaetsfrage: Training und Laufzeit benutzen
dasselbe Pipelineobjekt. Es gibt keine zweite Fassung der Formel, die
auseinanderlaufen koennte - nicht weil jemand aufpasst, sondern weil es
sie nicht gibt.

WAS HIER NICHT PASSIERT
-----------------------
Keine neue Modellfamilie. Es bleibt bei PoissonRegressor mit
L2-Regularisierung, getrennten Heim-/Auswaertszielen und dem
Offset-Umweg ueber tore/lambda. C8 aendert, WAS hineingeht, und nicht,
WAS daraus rechnet.
"""

import math

#: Fassung des Transformations- und Kalibrierungsvertrags.
#:
#: 1  V2-C8: Erstfassung. log1p, vorzeichenbehaftetes log1p,
#:    foldlokale Quantilbegrenzung, definitorische Interaktionen,
#:    multiplikative und log-lineare Kalibrierung.
MODEL_CLASS_VERSION = 1

# ---------------------------------------------------------------------------
# Transformationen
# ---------------------------------------------------------------------------

#: Die drei zugelassenen Transformationen. Mehr nicht - eine offene
#: Liste waere eine Einladung zur Merkmalsexplosion.
TRANSFORM_IDENTITY = "identity"
TRANSFORM_LOG1P = "log1p"
TRANSFORM_SIGNED_LOG1P = "signed_log1p"

TRANSFORMS = (TRANSFORM_IDENTITY, TRANSFORM_LOG1P, TRANSFORM_SIGNED_LOG1P)

#: Bis zu welchem Quantil begrenzt wird.
#:
#: 0,99 laesst das oberste Prozent stehen, ohne dass ein einzelner
#: Ausreisser die Skalierung bestimmt. Der Wert ist VORAB festgelegt
#: und wird nicht nach Ergebnis nachjustiert; gelernt wird nur, WO
#: dieses Quantil im jeweiligen Trainingsfold liegt.
WINSOR_QUANTILE = 0.99


def _quantil(sortiert, q):
    """
    Das q-Quantil einer sortierten Liste.

    Bewusst ohne Interpolation: Zwei Laeufe auf demselben Bestand
    sollen denselben Wert ergeben, auch auf einer anderen
    numpy-Fassung.
    """
    if not sortiert:
        return None
    index = int(round(q * (len(sortiert) - 1)))
    return sortiert[min(max(index, 0), len(sortiert) - 1)]


def apply_transform(wert, art):
    """
    Eine einzelne Transformation - die EINE Stelle.

    None und NaN bleiben, was sie sind. Sie hier zu ersetzen waere die
    stille Imputation, die der Vertrag an anderer Stelle verbietet -
    dafuer ist der Imputer da, und der sitzt danach.

    log1p ist fuer Zaehlwerte richtig und nicht bloss bequem: Er ist
    bei null exakt null, streng monoton und staucht genau den oberen
    Bereich, in dem Training und Test hier auseinanderlaufen.
    """
    if wert is None:
        return None
    if isinstance(wert, float) and math.isnan(wert):
        return wert
    wert = float(wert)

    if art == TRANSFORM_IDENTITY:
        return wert
    if art == TRANSFORM_LOG1P:
        # Ein negativer Zaehlwert ist ein Datenfehler. Ihn auf null zu
        # heben waere eine stille Korrektur - besser abbrechen.
        if wert < 0:
            raise ValueError(
                f"log1p auf negativem Zaehlwert: {wert!r} - diese "
                f"Transformation ist nur fuer nichtnegative Groessen "
                f"gedacht")
        return math.log1p(wert)
    if art == TRANSFORM_SIGNED_LOG1P:
        # Nettowerte sind vorzeichenbehaftet: -25 bis +19 gemessen.
        # sign(x) * log1p(|x|) erhaelt das Vorzeichen, ist bei null
        # exakt null und ueber den ganzen Bereich streng monoton.
        return math.copysign(math.log1p(abs(wert)), wert)
    raise ValueError(f"unbekannte Transformation: {art!r}")


class FeatureTransform:
    """
    Foldlokale Transformation der Merkmalsmatrix.

    sklearn-kompatibel (fit/transform), damit sie als ERSTER Schritt in
    dieselbe Pipeline passt, die auch Imputer, Skalierung und Regressor
    traegt. Damit lernt sie ihre Grenzen ausschliesslich in
    pipeline.fit() - also ausschliesslich auf dem Trainingsfold.

    spec: {spaltenname: transformationsart}
    winsor: Menge der Spalten, deren Oberkante begrenzt wird

    Die Reihenfolge ist Absicht: erst begrenzen, dann transformieren.
    Andersherum begrenzte man einen bereits gestauchten Wert, und die
    Grenze haette keine anschauliche Bedeutung mehr.
    """

    def __init__(self, columns, spec=None, winsor=(),
                 winsor_quantile=WINSOR_QUANTILE):
        self.columns = list(columns)
        self.spec = dict(spec or {})
        self.winsor = set(winsor)
        self.winsor_quantile = winsor_quantile
        self.bounds_ = {}
        self.fitted_ = False

    # -- sklearn-Schnittstelle -------------------------------------------

    def get_params(self, deep=True):                     # pragma: no cover
        return {"columns": self.columns, "spec": self.spec,
                "winsor": self.winsor,
                "winsor_quantile": self.winsor_quantile}

    def set_params(self, **params):                      # pragma: no cover
        for name, wert in params.items():
            setattr(self, name, wert)
        return self

    def fit(self, X, y=None, **kwargs):
        """
        Lernt die Obergrenzen - AUSSCHLIESSLICH aus X.

        X ist der Trainingsfold. Ein Ausreisser im aeusseren Testfold
        kann diese Grenzen deshalb nicht beeinflussen; ein Test haelt
        das fest.
        """
        import numpy as np

        werte = np.asarray(X, dtype=float)
        self.bounds_ = {}
        for i, spalte in enumerate(self.columns):
            if spalte not in self.winsor:
                continue
            spalte_werte = werte[:, i]
            endlich = sorted(float(w) for w in spalte_werte
                             if np.isfinite(w))
            grenze = _quantil(endlich, self.winsor_quantile)
            if grenze is not None:
                self.bounds_[spalte] = grenze
        self.fitted_ = True
        return self

    def transform(self, X):
        import numpy as np

        werte = np.array(X, dtype=float, copy=True)
        for i, spalte in enumerate(self.columns):
            grenze = self.bounds_.get(spalte)
            art = self.spec.get(spalte, TRANSFORM_IDENTITY)
            if grenze is None and art == TRANSFORM_IDENTITY:
                continue
            for zeile in range(werte.shape[0]):
                wert = werte[zeile, i]
                if not np.isfinite(wert):
                    continue                    # NaN bleibt NaN
                if grenze is not None and wert > grenze:
                    wert = grenze
                werte[zeile, i] = apply_transform(wert, art)
        return werte

    def fit_transform(self, X, y=None, **kwargs):
        return self.fit(X, y).transform(X)

    # -- Persistenz -------------------------------------------------------

    def to_dict(self):
        """Alles, was zur identischen Wiederherstellung noetig ist."""
        return {
            "model_class_version": MODEL_CLASS_VERSION,
            "columns": list(self.columns),
            "spec": dict(self.spec),
            "winsor": sorted(self.winsor),
            "winsor_quantile": self.winsor_quantile,
            "bounds": {k: float(v) for k, v in sorted(self.bounds_.items())},
            "fitted": bool(self.fitted_),
        }

    @classmethod
    def from_dict(cls, daten):
        objekt = cls(daten["columns"], daten.get("spec"),
                     daten.get("winsor", ()),
                     daten.get("winsor_quantile", WINSOR_QUANTILE))
        objekt.bounds_ = {k: float(v)
                          for k, v in (daten.get("bounds") or {}).items()}
        objekt.fitted_ = bool(daten.get("fitted"))
        return objekt


# ---------------------------------------------------------------------------
# Interaktionen
# ---------------------------------------------------------------------------

#: Die vorab festgelegten Interaktionen.
#:
#: Jede beantwortet eine fachliche Frage, und jede ersetzt einen
#: Rohwert, der ohne sie stillschweigend imputiert wuerde:
#:
#:   name       Name der neuen Spalte
#:   value      der Wert, der nur in bestimmten Zustaenden existiert
#:   indicator  der Zustandsindikator (0/1)
#:   why        die fachliche Begruendung
#:
#: KEINE Polynomterme, keine automatische Kreuzung aller Paare. Vier
#: Interaktionen, jede einzeln begruendet.
INTERACTION_SPECS = (
    {"name": "x_aggregate_diff_second_leg",
     "value": "aggregate_diff", "indicator": "is_second_leg",
     "why": ("Der Aggregatstand existiert NUR im Rueckspiel. Als "
             "Rohspalte wird er fuer 85 % der Zeilen mit dem Median der "
             "uebrigen 15 % gefuellt - ein Ligaphasenspiel bekommt "
             "einen Vorstand, den es nicht hat. Als Produkt ist er "
             "dort exakt null, und das ist die richtige Aussage: "
             "kein Vorstand, kein Beitrag.")},
    {"name": "x_aggregate_lead_second_leg",
     "value": "aggregate_lead", "indicator": "is_second_leg",
     "why": ("Fuehrung, Gleichstand oder Rueckstand vor dem Rueckspiel "
             "- dieselbe Begruendung, aber als Richtung statt als "
             "Betrag. Ein Verein mit drei Toren Vorsprung spielt "
             "anders als einer mit einem.")},
    {"name": "x_aggregate_goals_for_second_leg",
     "value": "aggregate_goals_for", "indicator": "is_second_leg",
     "why": ("Die eigenen Tore des Hinspiels aus Sicht des JETZIGEN "
             "Heimteams. Sie tragen die Perspektive, die "
             "aggregate_diff als Differenz verliert.")},
    {"name": "x_ko_round_knockout",
     "value": "ko_round_index", "indicator": "is_knockout",
     "why": ("Die Rundentiefe ist in der Ligaphase konstant null und "
             "traegt dort keine Information. Erst im K.-o. wird sie "
             "zur Ordinalskala von der Playoffrunde bis zum "
             "Endspiel.")},
)

#: Merkmale, die durch eine Interaktion ERSETZT werden.
#:
#: Sie duerfen nicht zusaetzlich aufgenommen werden - genau das war der
#: Fehler, den C5 gemessen hat. Der Rohwert bringt fuer die nicht
#: zutreffenden Zeilen einen imputierten Median mit, und die
#: Interaktion bringt dort eine ehrliche Null; beides zusammen sind
#: zwei Antworten auf dieselbe Frage.
INTERACTION_REPLACES = {
    "aggregate_diff", "aggregate_lead", "aggregate_goals_for",
    "aggregate_goals_against", "ko_round_index",
}

#: Merkmale, die per Konstruktion identisch zu einem anderen sind.
#:
#: In V2-C5 gemessen: aggregate_available == is_second_leg (r = 1,0000)
#: und neutral_venue == is_final (r = 1,0000). Ohne Spielstaettendaten
#: ist "neutraler Platz" kein eigenes Merkmal, sondern ein umbenanntes
#: is_final. Sie als zusaetzliche Freiheitsgrade zu fuehren waere eine
#: exakte Doppelspalte.
EXACT_DUPLICATES = {
    "aggregate_available": "is_second_leg",
    "neutral_venue": "is_final",
}


def interaction_value(wert, indikator):
    """
    Das definitorisch bedingte Produkt.

    DIE REGEL, DIE ALLES ENTSCHEIDET
    Ist der Indikator null, ist das Ergebnis EXAKT NULL - unabhaengig
    davon, ob der Wert fehlt. "Nicht anwendbar" ist kein fehlender
    Messwert, sondern eine bekannte Tatsache: Dieses Spiel hat keinen
    Aggregatstand, also traegt der Aggregatstand nichts bei.

    Genau hier trennt sich C8 von C5: Dort wurde aus der fehlenden
    Angabe ein Medianwert, hier wird aus ihr eine Null.

    Ist der Indikator eins und der Wert fehlt, bleibt es NaN - das
    waere ein echter Fehlwert, und dafuer ist der Imputer zustaendig.
    """
    if indikator is None:
        return None
    if isinstance(indikator, float) and math.isnan(indikator):
        return float("nan")
    if float(indikator) == 0.0:
        return 0.0
    if wert is None:
        return None
    if isinstance(wert, float) and math.isnan(wert):
        return float("nan")
    return float(wert) * float(indikator)


def build_interaction_columns(zeilen, specs=INTERACTION_SPECS):
    """
    Die Interaktionsspalten fuer eine Zeilenliste.

    Rueckgabe: {spaltenname: [werte]}.

    Deterministisch und ohne gelernten Parameter - deshalb koennen sie
    vor der Pipeline berechnet werden. Sie stehen trotzdem NICHT im
    Datensatz: Eine Interaktion ist eine Modellentscheidung, kein
    Datum, und C5 bis C7 sollen davon unberuehrt bleiben.
    """
    spalten = {}
    for spec in specs:
        werte = []
        for zeile in zeilen:
            werte.append(interaction_value(zeile.get(spec["value"]),
                                           zeile.get(spec["indicator"])))
        spalten[spec["name"]] = werte
    return spalten


def interaction_variance(zeilen, specs=INTERACTION_SPECS):
    """
    Wie viele verschiedene Werte traegt jede Interaktion?

    Eine Interaktion ohne Varianz im Trainingsfold kann nichts
    erklaeren. Sie zu behalten waere nicht falsch, aber irrefuehrend -
    der Bericht wuerde ein Merkmal auffuehren, das nie gewirkt hat.
    Der Aufrufer entscheidet; diese Funktion stellt nur fest.
    """
    spalten = build_interaction_columns(zeilen, specs)
    bericht = {}
    for name, werte in spalten.items():
        endlich = {w for w in werte
                   if w is not None and not (isinstance(w, float)
                                             and math.isnan(w))}
        bericht[name] = {
            "distinct": len(endlich),
            "constant": len(endlich) <= 1,
            "missing": sum(1 for w in werte
                           if w is None or (isinstance(w, float)
                                            and math.isnan(w))),
            "rows": len(werte),
        }
    return bericht


# ---------------------------------------------------------------------------
# Kalibrierung
# ---------------------------------------------------------------------------

#: Die drei Kalibrierungsarten.
CALIBRATION_NONE = "none"
CALIBRATION_MULTIPLICATIVE = "multiplicative"
CALIBRATION_LOGLINEAR = "loglinear"

CALIBRATIONS = (CALIBRATION_NONE, CALIBRATION_MULTIPLICATIVE,
                CALIBRATION_LOGLINEAR)

#: Grenzen der gelernten Parameter.
#:
#: Ein Kalibrator, der Lambda halbiert oder verdoppelt, korrigiert
#: nicht mehr - er ersetzt das Modell. Die Grenzen entsprechen denen
#: der bestehenden Korrekturfaktoren (model.CORRECTION_MIN/MAX) und
#: sind bewusst dieselben: Es gibt keinen Grund, warum eine
#: nachgelagerte Kalibrierung mehr duerfte als das Modell selbst.
CALIBRATION_FACTOR_MIN, CALIBRATION_FACTOR_MAX = 0.5, 2.0
CALIBRATION_SLOPE_MIN, CALIBRATION_SLOPE_MAX = 0.5, 1.5

#: Ab wie vielen Beobachtungen eine Steigung geschaetzt werden darf.
#:
#: Zwei Parameter aus wenigen Dutzend Partien sind kein Kalibrator,
#: sondern eine zweite Anpassung an das Rauschen. Unterhalb dieser
#: Grenze wird sicher auf den multiplikativen Fall zurueckgefallen.
MIN_ROWS_FOR_SLOPE = 200


class LambdaCalibrator:
    """
    Eine nachgelagerte Korrektur der Lambdas.

    WORAUF SIE GELERNT WIRD
    Ausschliesslich auf den INNEREN Validierungsvorhersagen des
    Trainingsfolds. Der aeussere Testfold wird nie angefasst - er ist
    die einzige unangetastete Groesse des ganzen Verfahrens, und eine
    Kalibrierung darauf waere die eleganteste Art, sich selbst zu
    betruegen.

    DIE ZWEI FORMEN
        multiplicative  lambda' = c * lambda
                        Ein Faktor. Er korrigiert einen systematischen
                        Niveauversatz und sonst nichts.

        loglinear       log(lambda') = a + b * log(lambda)
                        Zusaetzlich eine Steigung. Sie korrigiert, wenn
                        das Modell hohe Lambdas anders verfehlt als
                        niedrige - genau der Fall, den C7 gezeigt hat.

    Beide sind in c bzw. (a, b) begrenzt und fallen bei instabiler
    Schaetzung sicher auf "keine Kalibrierung" zurueck.
    """

    def __init__(self, mode=CALIBRATION_NONE, factor=1.0, intercept=0.0,
                 slope=1.0, fallback_reason=None, rows=0):
        self.mode = mode
        self.factor = factor
        self.intercept = intercept
        self.slope = slope
        self.fallback_reason = fallback_reason
        self.rows = rows

    # -- Anwendung --------------------------------------------------------

    def apply(self, lambdas):
        """
        Die Kalibrierung anwenden.

        Sie ersetzt die bestehenden Grenzen NICHT: apply_correction
        klammert danach unveraendert weiter. Diese Funktion liefert nur
        einen anderen Ausgangswert.
        """
        if self.mode == CALIBRATION_NONE:
            return [float(l) for l in lambdas]

        ergebnis = []
        for lam in lambdas:
            lam = float(lam)
            if lam <= 0 or not math.isfinite(lam):
                ergebnis.append(lam)
                continue
            if self.mode == CALIBRATION_MULTIPLICATIVE:
                neu = lam * self.factor
            else:
                neu = math.exp(self.intercept + self.slope * math.log(lam))
            ergebnis.append(neu if math.isfinite(neu) else lam)
        return ergebnis

    # -- Persistenz -------------------------------------------------------

    def to_dict(self):
        return {"mode": self.mode, "factor": float(self.factor),
                "intercept": float(self.intercept), "slope": float(self.slope),
                "fallback_reason": self.fallback_reason, "rows": self.rows,
                "model_class_version": MODEL_CLASS_VERSION}

    @classmethod
    def from_dict(cls, daten):
        if not daten:
            return cls()
        return cls(daten.get("mode", CALIBRATION_NONE),
                   daten.get("factor", 1.0), daten.get("intercept", 0.0),
                   daten.get("slope", 1.0), daten.get("fallback_reason"),
                   daten.get("rows", 0))


def fit_calibrator(lambdas, tore, mode=CALIBRATION_MULTIPLICATIVE):
    """
    Einen Kalibrator auf Validierungsvorhersagen anpassen.

    lambdas: die vorhergesagten Erwartungswerte
    tore:    die tatsaechlich gefallenen Tore

    DER MULTIPLIKATIVE FALL
    c = sum(tore) / sum(lambdas). Das ist der Momentenschaetzer der
    Poisson-Verteilung und braucht keine Iteration: Er setzt die
    Gesamterwartung auf die Gesamtbeobachtung.

    DER LOG-LINEARE FALL
    Eine gewichtete Ausgleichsgerade von log(lambda) auf
    log((tore + 0.5) / lambda) ... genauer: auf den beobachteten
    log-Erwartungswert. Die 0,5 ist die uebliche Stetigkeitskorrektur -
    ohne sie waere log(0) fuer jedes torlose Spiel undefiniert, und
    torlose Spiele sind kein Randfall.

    Faellt sicher zurueck, wenn die Schaetzung nicht traegt: zu wenige
    Zeilen, keine Streuung, ein Parameter ausserhalb der Grenzen.
    """
    paare = [(float(l), float(t)) for l, t in zip(lambdas, tore)
             if l is not None and t is not None and float(l) > 0
             and math.isfinite(float(l)) and math.isfinite(float(t))]

    if mode == CALIBRATION_NONE:
        return LambdaCalibrator(CALIBRATION_NONE, rows=len(paare))

    if len(paare) < 30:
        return LambdaCalibrator(
            CALIBRATION_NONE, rows=len(paare),
            fallback_reason=f"nur {len(paare)} verwertbare Zeilen")

    summe_lambda = sum(l for l, _ in paare)
    summe_tore = sum(t for _, t in paare)
    if summe_lambda <= 0:
        return LambdaCalibrator(CALIBRATION_NONE, rows=len(paare),
                                fallback_reason="Lambdasumme ist null")

    faktor = summe_tore / summe_lambda
    if not math.isfinite(faktor) or faktor <= 0:
        return LambdaCalibrator(CALIBRATION_NONE, rows=len(paare),
                                fallback_reason="Faktor nicht endlich")
    if not (CALIBRATION_FACTOR_MIN <= faktor <= CALIBRATION_FACTOR_MAX):
        return LambdaCalibrator(
            CALIBRATION_NONE, rows=len(paare),
            fallback_reason=(f"Faktor {faktor:.4f} ausserhalb "
                             f"[{CALIBRATION_FACTOR_MIN}, "
                             f"{CALIBRATION_FACTOR_MAX}]"))

    if mode == CALIBRATION_MULTIPLICATIVE:
        return LambdaCalibrator(CALIBRATION_MULTIPLICATIVE, factor=faktor,
                                rows=len(paare))

    # Log-linear.
    if len(paare) < MIN_ROWS_FOR_SLOPE:
        return LambdaCalibrator(
            CALIBRATION_MULTIPLICATIVE, factor=faktor, rows=len(paare),
            fallback_reason=(f"{len(paare)} Zeilen unter "
                             f"{MIN_ROWS_FOR_SLOPE} - Steigung nicht "
                             f"geschaetzt"))

    x = [math.log(l) for l, _ in paare]
    y = [math.log((t + 0.5) / 1.0) for _, t in paare]

    mx = sum(x) / len(x)
    my = sum(y) / len(y)
    sxx = sum((xi - mx) ** 2 for xi in x)
    if sxx <= 1e-12:
        return LambdaCalibrator(
            CALIBRATION_MULTIPLICATIVE, factor=faktor, rows=len(paare),
            fallback_reason="log(lambda) ohne Streuung")

    sxy = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    steigung = sxy / sxx
    achsenabschnitt = my - steigung * mx

    if not (math.isfinite(steigung) and math.isfinite(achsenabschnitt)):
        return LambdaCalibrator(
            CALIBRATION_MULTIPLICATIVE, factor=faktor, rows=len(paare),
            fallback_reason="Ausgleichsgerade nicht endlich")
    if not (CALIBRATION_SLOPE_MIN <= steigung <= CALIBRATION_SLOPE_MAX):
        return LambdaCalibrator(
            CALIBRATION_MULTIPLICATIVE, factor=faktor, rows=len(paare),
            fallback_reason=(f"Steigung {steigung:.4f} ausserhalb "
                             f"[{CALIBRATION_SLOPE_MIN}, "
                             f"{CALIBRATION_SLOPE_MAX}]"))

    # Gegenprobe: Der Kalibrator muss die Gesamterwartung treffen.
    probe = LambdaCalibrator(CALIBRATION_LOGLINEAR,
                             intercept=achsenabschnitt, slope=steigung,
                             rows=len(paare))
    summe_neu = sum(probe.apply([l for l, _ in paare]))
    if summe_neu <= 0 or not math.isfinite(summe_neu):
        return LambdaCalibrator(
            CALIBRATION_MULTIPLICATIVE, factor=faktor, rows=len(paare),
            fallback_reason="kalibrierte Lambdasumme nicht brauchbar")
    verhaeltnis = summe_neu / summe_tore if summe_tore else None
    if verhaeltnis is not None and not (0.5 <= verhaeltnis <= 2.0):
        return LambdaCalibrator(
            CALIBRATION_MULTIPLICATIVE, factor=faktor, rows=len(paare),
            fallback_reason=(f"kalibrierte Gesamterwartung um Faktor "
                             f"{verhaeltnis:.3f} daneben"))

    return probe
