"""
Poisson-Korrekturmodell auf den bestehenden Baseline-Lambdas.

WAS DAS MODELL LERNT - UND WAS NICHT
------------------------------------
Es lernt NICHT, Fussball vorherzusagen. Die Baseline tut das bereits mit
einem LogLoss von 1,01598 ueber 4.380 Spiele. Gelernt wird ausschliesslich
ein multiplikativer Korrekturfaktor:

    lambda_ml = lambda_baseline * korrektur(merkmale)

Ohne Signal ist die Korrektur rund 1, und das Ergebnis IST die Baseline.
Ein Modell, das die Wahrscheinlichkeiten direkt lernt, muesste dagegen
aus 4.380 Spielen alles neu erarbeiten und koennte beliebig schlechter
werden.

DER OFFSET-UMWEG - UND WARUM ER NOETIG IST
------------------------------------------
Ein Poisson-GLM mit Offset waere der Lehrbuchweg:

    log(mu) = log(t) + x*beta

sklearn kennt das nicht. Nachgemessen an Version 1.6.1:

    PoissonRegressor.fit(self, X, y, sample_weight=None)

Kein offset, kein exposure, kein base_margin. Wer hier eine Offset-API
behauptet, irrt.

Der exakte Umweg fuehrt ueber die Poisson-Devianz. Fuer mu = t*exp(eta)
gilt:

    d(y, t*exp(eta)) = t * d(y/t, exp(eta))

Der Beweis ist eine Zeile Umformung: Setzt man y = t*(y/t) und
mu = t*exp(eta) in die Devianz 2*(y*log(y/mu) - (y-mu)) ein, laesst sich
t vollstaendig ausklammern.

Praktisch heisst das:

    Ziel    y / t        (hier: tore / baseline_lambda)
    Gewicht t            (hier: baseline_lambda)

Die gewichtete Devianz auf dem Verhaeltnis ist proportional zur
Offset-Devianz auf den Zaehlungen. Beide Optimierungen haben dieselbe
Loesung.

Nachgerechnet, nicht geglaubt: Auf synthetischen Daten wurde die echte
Offset-Poisson-MLE mit scipy direkt optimiert und mit dem Umweg
verglichen. Groesste Abweichung ueber Intercept und drei Koeffizienten:
4.3e-09. Das ist Optimierertoleranz, kein Unterschied. Der Test
test_offset_umweg_trifft_die_echte_offset_mle haelt das fest.

Der naive Weg - Zaehlungen direkt regressieren und den Offset weglassen -
ist dagegen genau dann grob verzerrt, wenn die Exposure mit den Merkmalen
zusammenhaengt. Und das ist hier der Normalfall: baseline_lambda entsteht
aus denselben Staerkeprofilen, aus denen auch die Merkmale stammen. Im
Gegenversuch wanderte ein wahrer Koeffizient von 0.40 auf 1.20, weil er
die Exposure mitgeschluckt hat. Der Test
test_ohne_offset_verschluckt_der_koeffizient_die_exposure zeigt das.

Eine Einschraenkung, damit die Aussage nicht groesser wird als der
Beweis: Das sample_weight ist noetig, damit der Umweg die Offset-Loesung
EXAKT trifft. Ein ungewichteter Fit auf dem Verhaeltnis ist nicht
automatisch falsch, sondern nur eine andere, weniger effiziente
Schaetzung.

ZWEI GETRENNTE MODELLE
----------------------
Eines fuer Heim-, eines fuer Auswaertstore. Der Heimvorteil steckt
bereits in den Baseline-Lambdas; die Modelle lernen nur die Abweichung
je Seite. Beide benutzen dieselbe Merkmalsliste - sonst waere ein
Vergleich ihrer Koeffizienten sinnlos.
"""

import math

#: Die fuenf Kandidaten, VORAB festgelegt. Sie werden nach Betrachtung
#: eines aeusseren Test-Folds nicht mehr geaendert - das waere
#: Optimierung auf die Zukunft.
#: An sklearn 1.6.1 geprueft: alle fuenf sind gueltig und liefern strikt
#: positive Vorhersagen.
ALPHA_CANDIDATES = (0.01, 0.1, 1.0, 10.0, 100.0)

#: Die unveraenderte Baseline als ausdruecklicher Kandidat. Ohne sie
#: waere die Modellwahl gezwungen, irgendein Alpha zu nehmen - auch
#: wenn keines besser ist als gar keine Korrektur.
NO_CORRECTION = "no_correction"

#: Konservative Grenzen, ebenfalls vorab festgelegt.
#: Ein Korrekturfaktor ausserhalb [0.5, 2.0] waere keine Korrektur mehr,
#: sondern eine Neuerfindung der Vorhersage.
CORRECTION_MIN, CORRECTION_MAX = 0.5, 2.0

#: Lambdas ausserhalb dieser Grenzen sind fuer ein Fussballspiel
#: unsinnig. 6.0 erwartete Tore einer Mannschaft kommen praktisch nicht
#: vor; 0.05 hiesse, ein Tor sei so gut wie ausgeschlossen.
LAMBDA_MIN, LAMBDA_MAX = 0.05, 6.0

#: Spalten mit Schema-Rolle "feature", die trotzdem NICHT ins Modell
#: gehen. Die Endung gilt je Seite.
#:
#: congestion_level ist Text ("normal", "elevated", "high"). Eine
#: Kodierung waere moeglich, gehoert aber in einen spaeteren Schritt -
#: hier wuerde sie unkontrolliert eine Ordnung unterstellen.
KATEGORIALE_ENDUNGEN = ("congestion_level",)


# ---------------------------------------------------------------------------
# Merkmalsauswahl
# ---------------------------------------------------------------------------

def feature_columns(schema=None):
    """
    Die Modellmerkmale - explizit, deterministisch, aus dem Schemavertrag.

    Massgeblich ist die Rolle im Dataset-Schema, nicht ein Namensmuster.
    Eine Spalte gelangt nur ins Modell, wenn sie ausdruecklich als
    "feature" gefuehrt ist UND nicht auf der Ausschlussliste steht.

    Die Baseline-Lambdas tragen die Rolle "baseline" und sind damit
    automatisch draussen: Sie sind der Offset, kein frei gewichtetes
    Merkmal. Waeren sie beides, koennte das Modell die Baseline
    beliebig ueberschreiben - genau das soll die Bauform verhindern.

    Sortiert, damit zwei Laeufe dieselbe Reihenfolge und damit dieselben
    Koeffizientenpositionen ergeben.
    """
    from src.ml.dataset import build_schema

    schema = schema or build_schema()
    namen = [e["name"] for e in schema
             if e["role"] == "feature"
             and not any(e["name"].endswith(endung)
                         for endung in KATEGORIALE_ENDUNGEN)]
    return sorted(namen)


def excluded_columns(schema=None):
    """
    Was nicht ins Modell darf - mit Begruendung.

    Gehoert ins Ergebnisartefakt: Ein Ausschluss ohne Begruendung laesst
    sich spaeter nicht mehr von einem Versehen unterscheiden.
    """
    from src.ml.dataset import build_schema

    schema = schema or build_schema()
    gruende = {
        "identifier": "Identifikator - ein Modell darf die Partie nicht "
                      "wiedererkennen",
        "target": "Zielgroesse",
        "baseline": "Offset-Grundlage bzw. Vergleichsmassstab, kein "
                    "frei gewichtetes Merkmal",
        "quality": "Textfeld - eine Kodierung gehoert in einen spaeteren "
                   "Schritt",
        "diagnostic": "reines Diagnosefeld",
    }

    ausgeschlossen = []
    for eintrag in schema:
        if eintrag["role"] in gruende:
            ausgeschlossen.append({"column": eintrag["name"],
                                   "reason": gruende[eintrag["role"]]})
        elif any(eintrag["name"].endswith(e) for e in KATEGORIALE_ENDUNGEN):
            ausgeschlossen.append({
                "column": eintrag["name"],
                "reason": "kategorialer Text - Kodierung erst in einem "
                          "spaeteren Schritt"})
    return sorted(ausgeschlossen, key=lambda e: e["column"])


# ---------------------------------------------------------------------------
# Matrizen
# ---------------------------------------------------------------------------

def _pruefe_endlich(werte, bezeichnung):
    for wert in werte:
        if wert is None:
            continue
        if isinstance(wert, bool):
            continue
        if not math.isfinite(wert):
            raise ValueError(
                f"{bezeichnung} enthaelt einen nicht endlichen Wert: {wert!r}")


def feature_matrix(zeilen, spalten):
    """
    Die Merkmalsmatrix als Liste von Listen.

    Fehlende Werte bleiben None und werden spaeter vom Imputer behandelt -
    hier NICHT ersetzt. Eine Imputation an dieser Stelle liefe ueber den
    gesamten Datensatz und damit ueber die zeitliche Grenze hinweg.

    Wahrheitswerte werden zu 0/1, weil sklearn keine bool-Spalten in
    einer Objektmatrix mag. Das ist eine Typwandlung, keine Kodierung.
    """
    matrix = []
    for zeile in zeilen:
        werte = []
        for spalte in spalten:
            wert = zeile.get(spalte)
            if isinstance(wert, bool):
                wert = 1.0 if wert else 0.0
            elif wert is not None and not isinstance(wert, (int, float)):
                raise TypeError(
                    f"Spalte {spalte} ist nicht numerisch: {wert!r} "
                    f"({type(wert).__name__}) - sie gehoert nicht in die "
                    f"Merkmalsliste")
            werte.append(None if wert is None else float(wert))
        matrix.append(werte)
    return matrix


def targets_and_weights(zeilen, seite):
    """
    Verhaeltnisziel und Gewicht fuer eine Seite - der Offset-Umweg.

    seite: "home" oder "away".

    Rueckgabe: (ziel, gewicht). Beide Listen sind gleich lang wie zeilen.

    Ein nichtpositives oder fehlendes Lambda ist kein Randfall, den man
    stillschweigend glaettet: Es hiesse, die Baseline haette fuer diese
    Partie keine sinnvolle Vorhersage - und dann darf auch keine
    Korrektur darauf aufbauen.
    """
    lambda_spalte = f"baseline_lambda_{seite}"
    tor_spalte = f"{seite}_goals"

    ziel, gewicht = [], []
    for zeile in zeilen:
        lam = zeile.get(lambda_spalte)
        tore = zeile.get(tor_spalte)

        if lam is None or not isinstance(lam, (int, float)) \
                or not math.isfinite(lam) or lam <= 0:
            raise ValueError(
                f"{lambda_spalte} ist nicht strikt positiv: {lam!r} "
                f"(Zeile {zeile.get('row_id')})")
        if tore is None or not math.isfinite(tore) or tore < 0:
            raise ValueError(
                f"{tor_spalte} ist unbrauchbar: {tore!r} "
                f"(Zeile {zeile.get('row_id')})")

        ziel.append(tore / lam)
        gewicht.append(float(lam))

    _pruefe_endlich(ziel, "ratio_target")
    _pruefe_endlich(gewicht, "sample_weight")
    return ziel, gewicht


def constant_features(matrix, spalten):
    """
    Merkmale ohne Streuung im gegebenen Bestand.

    Sie sind nicht schaedlich - der Scaler laesst sie stehen und der
    Regressor bekommt Koeffizient null -, aber sie gehoeren berichtet.
    Ein Merkmal, das in einem Fold konstant ist, traegt dort nichts bei.
    """
    konstant = []
    for i, spalte in enumerate(spalten):
        werte = {zeile[i] for zeile in matrix if zeile[i] is not None}
        if len(werte) <= 1:
            konstant.append(spalte)
    return konstant


def fully_missing_features(matrix, spalten):
    """Merkmale, die im gegebenen Bestand ueberhaupt keinen Wert haben."""
    fehlend = []
    for i, spalte in enumerate(spalten):
        if all(zeile[i] is None for zeile in matrix):
            fehlend.append(spalte)
    return fehlend


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def build_pipeline(alpha):
    """
    Imputer, Skalierung und Poisson-Regression in einer Pipeline.

    Als Pipeline und nicht als drei Schritte: Nur so ist sichergestellt,
    dass Median und Skalierungsstatistik ausschliesslich aus dem Bestand
    stammen, auf dem fit() gerufen wurde. Wer vorher global imputiert,
    traegt Information des Testbestands ins Training - und merkt es nie.
    """
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import PoissonRegressor
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        # max_iter grosszuegig: Der lbfgs-Solver braucht bei kleinem
        # alpha mehr Schritte, und eine nicht konvergierte Anpassung
        # waere ein stiller Fehler.
        ("regressor", PoissonRegressor(alpha=alpha, max_iter=5000)),
    ])


def fit_side(zeilen, seite, alpha, spalten=None):
    """
    Trainiert das Korrekturmodell einer Seite.

    Rueckgabe: (pipeline, diagnose).
    """
    import numpy as np

    spalten = spalten or feature_columns()
    matrix = feature_matrix(zeilen, spalten)
    ziel, gewicht = targets_and_weights(zeilen, seite)

    diagnose = {
        "rows": len(zeilen),
        "constant_features": constant_features(matrix, spalten),
        "fully_missing_features": fully_missing_features(matrix, spalten),
    }

    X = np.array(matrix, dtype=float)   # None wird zu nan, das der Imputer kennt
    y = np.array(ziel, dtype=float)
    w = np.array(gewicht, dtype=float)

    if not np.isfinite(y).all():
        raise ValueError("ratio_target enthaelt NaN oder Inf")
    if not np.isfinite(w).all() or (w <= 0).any():
        raise ValueError("sample_weight enthaelt NaN, Inf oder Werte <= 0")

    pipeline = build_pipeline(alpha)
    pipeline.fit(X, y, regressor__sample_weight=w)
    return pipeline, diagnose


def predict_factors(pipeline, zeilen, spalten=None):
    """Die ungeklammerten Korrekturfaktoren."""
    import numpy as np

    spalten = spalten or feature_columns()
    X = np.array(feature_matrix(zeilen, spalten), dtype=float)
    faktoren = pipeline.predict(X)

    if not np.isfinite(faktoren).all():
        raise ValueError("das Modell hat NaN oder Inf vorhergesagt")
    return [float(f) for f in faktoren]


# ---------------------------------------------------------------------------
# Clamps
# ---------------------------------------------------------------------------

def apply_correction(zeilen, faktoren_home, faktoren_away):
    """
    Wendet die Korrektur an und begrenzt sie.

    Die Grenzen greifen VOR der Wahrscheinlichkeitsberechnung - danach
    waere die Verteilung bereits aus einem unsinnigen Lambda entstanden.

    Rueckgabe: (lambdas, statistik). lambdas ist eine Liste von
    (lambda_home, lambda_away).
    """
    if len(faktoren_home) != len(zeilen) or len(faktoren_away) != len(zeilen):
        raise ValueError("Faktoren und Zeilen passen nicht zusammen")

    lambdas = []
    roh = {"home": [], "away": []}
    endgueltig = {"home": [], "away": []}
    geklammert = {"home": 0, "away": 0}

    for zeile, fh, fa in zip(zeilen, faktoren_home, faktoren_away):
        for seite, faktor in (("home", fh), ("away", fa)):
            if not math.isfinite(faktor):
                raise ValueError(
                    f"nicht endlicher Korrekturfaktor fuer {seite}: {faktor!r}")
            roh[seite].append(faktor)

        werte = {}
        for seite, faktor in (("home", fh), ("away", fa)):
            begrenzt = min(max(faktor, CORRECTION_MIN), CORRECTION_MAX)
            lam = zeile[f"baseline_lambda_{seite}"] * begrenzt
            lam_begrenzt = min(max(lam, LAMBDA_MIN), LAMBDA_MAX)
            if begrenzt != faktor or lam_begrenzt != lam:
                geklammert[seite] += 1
            endgueltig[seite].append(lam_begrenzt)
            werte[seite] = lam_begrenzt

        lambdas.append((werte["home"], werte["away"]))

    anzahl = len(zeilen) or 1
    statistik = {
        "correction_min": CORRECTION_MIN,
        "correction_max": CORRECTION_MAX,
        "lambda_min_allowed": LAMBDA_MIN,
        "lambda_max_allowed": LAMBDA_MAX,
    }
    for seite in ("home", "away"):
        statistik[f"clamped_{seite}"] = geklammert[seite]
        statistik[f"clamp_rate_{seite}"] = geklammert[seite] / anzahl
        statistik[f"raw_factor_{seite}"] = _verteilung(roh[seite])
        statistik[f"final_lambda_{seite}"] = _verteilung(endgueltig[seite])
    return lambdas, statistik


def _verteilung(werte):
    """Min, Median, Mittel und Max - fuer den Bericht."""
    if not werte:
        return None
    sortiert = sorted(werte)
    mitte = len(sortiert) // 2
    median = (sortiert[mitte] if len(sortiert) % 2
              else (sortiert[mitte - 1] + sortiert[mitte]) / 2)
    return {
        "min": sortiert[0],
        "median": median,
        "mean": sum(sortiert) / len(sortiert),
        "max": sortiert[-1],
    }


def baseline_lambdas(zeilen):
    """
    Die Lambdas des Kandidaten no_correction.

    Ausdruecklich als eigene Funktion: Sie muss die Baseline
    zifferngenau reproduzieren, und genau das prueft ein Test.
    """
    return [(z["baseline_lambda_home"], z["baseline_lambda_away"])
            for z in zeilen]


def coefficients(pipeline, spalten=None):
    """
    Intercept und Koeffizienten je Merkmal.

    Sie beziehen sich auf die SKALIERTEN Merkmale - der Scaler steht in
    derselben Pipeline. Ein Koeffizient ist damit die Wirkung einer
    Standardabweichung, nicht einer Einheit.

    Und er beschreibt einen beobachteten historischen Zusammenhang, keine
    Ursache. Das Modell verwendet ein Merkmal; es erklaert nicht, warum.
    """
    spalten = spalten or feature_columns()
    regressor = pipeline.named_steps["regressor"]
    paare = [{"feature": name, "coefficient": float(wert)}
             for name, wert in zip(spalten, regressor.coef_)]
    nach_groesse = sorted(paare, key=lambda p: p["coefficient"])

    return {
        "intercept": float(regressor.intercept_),
        "by_feature": sorted(paare, key=lambda p: p["feature"]),
        "top_negative": nach_groesse[:10],
        "top_positive": list(reversed(nach_groesse[-10:])),
        "near_zero": [p for p in paare if abs(p["coefficient"]) < 1e-4],
    }
