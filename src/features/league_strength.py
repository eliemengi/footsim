"""
Ligastaerke aus frueheren Champions-League-Begegnungen (V2-C15).

DAS PROBLEM, GEMESSEN IN V2-C14
-------------------------------
Die 16 eingefrorenen Profilmerkmale sind Verhaeltniswerte zur EIGENEN
nationalen Liga. Wer seine Liga beherrscht, sieht darin aus wie ein
Spitzenklub. Nachgemessen an 283 Testpartien:

    Merkmal            Top-5     Nicht-Top-5
    attack_away        1,248     1,434
    points_per_game    1,982     2,257
    win_rate           0,585     0,694

Nicht-Top-5-Vereine haben in JEDEM Merkmal die besseren Werte. Ihre
tatsaechliche Leistung in der Champions League:

    Nicht-Top-5 auswaerts   1,12 Tore   2,38 Gegentore
    Top-5 auswaerts         1,60 Tore   1,62 Gegentore

Die Folge war ein schwer verschlechtertes Segment
(`origin:top5_vs_other`, n=73, +0,01453) und damit die Ablehnung.

WARUM NATIONALE SPIELE DAS NICHT LOESEN KOENNEN
-----------------------------------------------
In einem nationalen Ligaspiel stammen beide Mannschaften aus DERSELBEN
Liga. Die Ligastaerkedifferenz ist dort strukturell null. Ein
Ligastaerkemerkmal, das nur auf nationalen Spielen angepasst wird,
bekommt kein Gewicht - es waere nicht schwach gemessen, sondern gar
nicht gemessen.

Deshalb entsteht die Ligastaerke hier ausschliesslich aus
Begegnungen, in denen verschiedene Ligen aufeinandertreffen: aus
frueheren Champions-League-Spielen.

DIE FORM
--------
Zweistufig. Stufe eins ist das unveraenderte nationale Basismodell und
liefert je Partie zwei Erwartungswerte. Stufe zwei korrigiert sie:

    lambda_heim' = lambda_heim * exp(a[liga_heim] + d[liga_gast])
    lambda_gast' = lambda_gast * exp(a[liga_gast] + d[liga_heim])

`a` ist die offensive, `d` die defensive Ligastaerke als
log-Multiplikator. Ein Wert von 0 bedeutet neutral.

Geschaetzt wird das mit genau derselben Technik wie das Basismodell:
PoissonRegressor ueber den Offset-Umweg, also Ziel `Tore / lambda` mit
Gewicht `lambda`. Das ist keine neue Modellklasse, sondern dieselbe
Klasse auf einer zweiten Stufe.

Der Heimvorteil steckt bereits in Stufe eins und wird hier NICHT noch
einmal modelliert. Jede Partie liefert zwei Beobachtungen, eine je
Seite, und beide Seiten tragen dieselben Ligaparameter in
unterschiedlicher Rolle.

IDENTIFIZIERBARKEIT
-------------------
Ohne Achsenabschnitt und mit reinen Indikatorspalten waere die Loesung
nur bis auf eine Konstante bestimmt: Man koennte auf alle `a` einen
Wert addieren und ihn von allen `d` abziehen, ohne eine einzige
Vorhersage zu aendern. Die Ridge-Strafe loest das eindeutig auf, weil
sie unter allen gleichwertigen Loesungen die mit der kleinsten Norm
waehlt. Die Regularisierung ist hier also nicht nur Vorsicht, sie ist
Teil der Definition.

COLD START
----------
Eine Liga ohne fruehere CL-Historie bekommt keine Spalte und damit den
Wert 0, also den Faktor 1. Das ist neutral und ausdruecklich kein
Bonus. Unbekannt heisst unbekannt.

ZEITLICHE TRENNUNG
------------------
Die Schaetzung sieht ausschliesslich CL-Partien aus Saisons, die
vollstaendig vor der Testsaison liegen. Ein Testspiel traegt niemals
zu seiner eigenen Korrektur bei.
"""

import math

#: Trennzeichen im Spaltennamen der Entwurfsmatrix. Bewusst ein
#: Zeichen, das in keinem Ligacode vorkommt.
_ATTACK = "attack:"
_DEFENCE = "defence:"

#: Grenzen des Ligafaktors. Sie liegen enger als die Korrekturgrenzen
#: des Basismodells (0,5 bis 2,0), weil hier eine ZWEITE Korrektur auf
#: eine bereits korrigierte Vorhersage trifft. Zwei Stufen, die je bis
#: zum Doppelten gehen duerfen, koennten sich zum Vierfachen
#: multiplizieren; das waere keine Korrektur mehr, sondern eine neue
#: Vorhersage.
FACTOR_MIN, FACTOR_MAX = 0.6, 1.6

#: Ab wie vielen Beobachtungen ueberhaupt geschaetzt wird. Darunter
#: bleibt die gesamte Komponente neutral, statt aus einer Handvoll
#: Partien eine Europakarte zu zeichnen.
MIN_OBSERVATIONS = 40


class LeagueStrength:
    """
    Die geschaetzte Ligastaerke eines Folds.

    Bewusst ein kleines, unveraenderliches Objekt: Es traegt die
    Parameter und die Diagnose, und es weiss, aus welchen Saisons es
    stammt. Wer es anwendet, kann nicht versehentlich einen anderen
    Informationsstand erwischen.
    """

    def __init__(self, attack=None, defence=None, diagnose=None,
                 gamma=1.0):
        self.attack = dict(attack or {})
        self.defence = dict(defence or {})
        self.diagnose = dict(diagnose or {})
        # V2-C16: Die globale Daempfung. 1.0 ist die unveraenderte
        # C15-Korrektur, kleinere Werte ziehen ALLE Ligafaktoren
        # gleichmaessig Richtung 1. Sie wirkt auf jede Liga gleich; es
        # gibt keinen ligaspezifischen Wert.
        self.gamma = float(gamma)

    # -- Anwendung --------------------------------------------------------

    def factors(self, home_league, away_league):
        """
        Die beiden Korrekturfaktoren einer Partie.

        Rueckgabe: (faktor_heim, faktor_gast). Eine unbekannte Liga
        traegt 0 bei und damit den Faktor 1.
        """
        a_h = self.attack.get(home_league, 0.0)
        a_a = self.attack.get(away_league, 0.0)
        d_h = self.defence.get(home_league, 0.0)
        d_a = self.defence.get(away_league, 0.0)

        # V2-C16: gamma daempft den GESAMTEN Exponenten, nicht einzelne
        # Ligen. Bei gamma = 1 ist das exakt die C15-Formel, bei
        # gamma -> 0 verschwindet die Korrektur vollstaendig. Die
        # Grenzen greifen wie bisher NACH der Daempfung.
        heim = math.exp(self.gamma * (a_h + d_a))
        gast = math.exp(self.gamma * (a_a + d_h))
        return (min(max(heim, FACTOR_MIN), FACTOR_MAX),
                min(max(gast, FACTOR_MIN), FACTOR_MAX))

    def is_cold_start(self, league):
        """Kennt die Schaetzung diese Liga ueberhaupt?"""
        return league not in self.attack and league not in self.defence

    def is_neutral(self):
        """Wurde ueberhaupt etwas geschaetzt?"""
        return not self.attack and not self.defence

    def with_gamma(self, gamma):
        """
        Dieselben Ligaparameter mit einer anderen Daempfung.

        Bewusst eine neue Instanz: Ein Objekt, dessen Daempfung sich
        nachtraeglich aendern laesst, koennte zwischen Auswahl und
        Anwendung ein anderes sein.
        """
        return LeagueStrength(self.attack, self.defence, self.diagnose,
                              gamma)

    def summary(self):
        """Die Parameter in berichtsfaehiger Form, ohne Rohdaten."""
        ligen = sorted(set(self.attack) | set(self.defence))
        return {
            "leagues": len(ligen),
            "gamma": self.gamma,
            "parameters": {
                liga: {"attack": round(self.attack.get(liga, 0.0), 5),
                       "defence": round(self.defence.get(liga, 0.0), 5)}
                for liga in ligen},
            "diagnostics": dict(self.diagnose),
        }


def _beobachtungen(zeilen, lambdas, ligakarte):
    """
    Je Partie zwei Beobachtungen, eine je Seite.

    Verworfen wird eine Seite nur dann, wenn ihre Liga unbekannt ist
    oder das Basislambda nicht brauchbar - beides waere ein Befund und
    kein Randfall, den man glaetten darf.
    """
    spalten = set()
    roh = []
    verworfen = {"unbekannte_liga": 0, "unbrauchbares_lambda": 0}

    for zeile, (lam_h, lam_a) in zip(zeilen, lambdas):
        liga_h = ligakarte.get(zeile.get("home_id"))
        liga_a = ligakarte.get(zeile.get("away_id"))
        if not liga_h or not liga_a:
            verworfen["unbekannte_liga"] += 2
            continue

        for seite, lam, liga_eigen, liga_gegner in (
                ("home", lam_h, liga_h, liga_a),
                ("away", lam_a, liga_a, liga_h)):
            tore = zeile.get(seite + "_goals")
            if (lam is None or not math.isfinite(lam) or lam <= 0
                    or tore is None or not math.isfinite(tore) or tore < 0):
                verworfen["unbrauchbares_lambda"] += 1
                continue
            spalten.add(_ATTACK + liga_eigen)
            spalten.add(_DEFENCE + liga_gegner)
            roh.append((liga_eigen, liga_gegner, float(tore), float(lam)))

    return sorted(spalten), roh, verworfen


def estimate(zeilen, lambdas, ligakarte, alpha):
    """
    Die Ligastaerke aus genau diesen Partien.

    zeilen    CL-Partien, ausschliesslich aus frueheren Saisons
    lambdas   die Vorhersagen des Basismodells fuer eben diese Partien
    ligakarte Vereins-ID zu Ligacode
    alpha     Ridge-Staerke, vom Aufrufer vorab bestimmt

    Rueckgabe: LeagueStrength.

    Die Reihenfolge der Spalten ist sortiert und damit unabhaengig
    davon, in welcher Reihenfolge die Partien hereinkommen. Zwei
    Laeufe liefern dieselben Parameter.
    """
    from sklearn.linear_model import PoissonRegressor

    spalten, roh, verworfen = _beobachtungen(zeilen, lambdas, ligakarte)

    if len(roh) < MIN_OBSERVATIONS or not spalten:
        return LeagueStrength(diagnose={
            "fitted": False,
            "reason": ("zu wenige Beobachtungen: %d, noetig sind %d"
                       % (len(roh), MIN_OBSERVATIONS)),
            "observations": len(roh),
            "dropped": verworfen,
            "alpha": alpha,
        })

    index = {name: i for i, name in enumerate(spalten)}
    matrix, ziel, gewicht = [], [], []
    for liga_eigen, liga_gegner, tore, lam in roh:
        zeile = [0.0] * len(spalten)
        zeile[index[_ATTACK + liga_eigen]] = 1.0
        zeile[index[_DEFENCE + liga_gegner]] = 1.0
        matrix.append(zeile)
        # Derselbe Offset-Umweg wie im Basismodell: Verhaeltnisziel
        # mit Lambda als Gewicht ist aequivalent zu einer
        # Poissonregression mit log(lambda) als Offset.
        ziel.append(tore / lam)
        gewicht.append(lam)

    modell = PoissonRegressor(alpha=alpha, fit_intercept=False,
                              max_iter=5000)
    modell.fit(matrix, ziel, sample_weight=gewicht)

    attack, defence = {}, {}
    for name, wert in zip(spalten, modell.coef_):
        if name.startswith(_ATTACK):
            attack[name[len(_ATTACK):]] = float(wert)
        else:
            defence[name[len(_DEFENCE):]] = float(wert)

    import collections
    partien_je_liga = collections.Counter()
    for liga_eigen, liga_gegner, _, _ in roh:
        partien_je_liga[liga_eigen] += 1

    return LeagueStrength(attack, defence, {
        "fitted": True,
        "observations": len(roh),
        "matches": len(roh) // 2,
        "columns": len(spalten),
        "alpha": alpha,
        "converged": bool(getattr(modell, "n_iter_", 0) < 5000),
        "dropped": verworfen,
        "observations_per_league": dict(sorted(partien_je_liga.items())),
        "identification": (
            "Ohne Achsenabschnitt waere die Loesung nur bis auf eine "
            "Konstante bestimmt. Die Ridge-Strafe waehlt darunter die "
            "Loesung kleinster Norm und macht sie damit eindeutig."),
    })


def select_alpha(fit_zeilen, fit_lambdas, val_zeilen, val_lambdas,
                 ligakarte, kandidaten):
    """
    Alpha ueber eine ZEITLICHE innere Teilung waehlen.

    Dieselbe Regel wie im Basismodell und aus demselben Grund: Der
    aeussere Testfold darf die Wahl nicht sehen. Bewertet wird auf dem
    spaeteren Teil der Trainingshistorie, nie auf Testdaten.

    Rueckgabe: (alpha, protokoll).
    """
    protokoll = []
    bestes, bester_verlust = None, None

    for alpha in kandidaten:
        staerke = estimate(fit_zeilen, fit_lambdas, ligakarte, alpha)
        verlust = _poisson_deviance(staerke, val_zeilen, val_lambdas,
                                    ligakarte)
        protokoll.append({"alpha": alpha, "validation_deviance": verlust,
                          "fitted": staerke.diagnose.get("fitted", False)})
        if verlust is None:
            continue
        # Bei Gleichstand gewinnt das GROESSERE Alpha - dieselbe
        # Konvention wie im Basismodell, weil staerkere Regularisierung
        # bei knapper Datenlage die vorsichtigere Wahl ist.
        if bester_verlust is None or verlust < bester_verlust - 1e-12:
            bestes, bester_verlust = alpha, verlust
        elif abs(verlust - bester_verlust) <= 1e-12 and alpha > bestes:
            bestes = alpha

    return bestes, {"candidates": protokoll, "selected": bestes,
                    "criterion": "Poissondevianz auf dem spaeteren Teil "
                                 "der Trainingshistorie",
                    "tie_break": "groesseres Alpha gewinnt"}


#: Die zulaessigen Daempfungen (V2-C16). Vorab eingefroren und
#: bewusst klein: Vier Werte auf einer inneren Validierung sind eine
#: Auswahl, zwanzig waeren eine Suche.
GAMMA_GRID = (0.25, 0.50, 0.75, 1.00)

#: Ab welchem Unterschied zwei Daempfungen als verschieden gelten.
#: Darunter entscheidet der Tie-Breaker, damit die Wahl nicht am
#: Gleitkommarauschen haengt.
GAMMA_TOLERANCE = 1e-6


def select_gamma(staerke, val_zeilen, val_lambdas, ligakarte,
                 grid=GAMMA_GRID, toleranz=GAMMA_TOLERANCE):
    """
    Die Daempfung auf der INNEREN Validierung waehlen.

    Bewertet wird ausschliesslich auf dem spaeteren Teil der
    Trainingshistorie. Der aeussere Testfold wird nie gesehen; er
    darf weder Gamma noch Alpha noch die Grenzen beeinflussen.

    TIE-BREAK
    Liegen zwei Daempfungen innerhalb der Toleranz gleichauf, gewinnt
    die KLEINERE. Das ist die vorsichtigere Wahl: Weniger Korrektur
    heisst weniger Vertrauen in eine aus wenigen Partien geschaetzte
    Groesse. Die Regel steht vorab im Vertrag und nicht in der
    Auswertung.

    Rueckgabe: (gamma, protokoll).
    """
    protokoll = []
    bestes, bester_verlust = None, None

    for gamma in grid:
        verlust = _poisson_deviance(staerke.with_gamma(gamma), val_zeilen,
                                    val_lambdas, ligakarte)
        protokoll.append({"gamma": gamma, "validation_deviance": verlust})
        if verlust is None:
            continue
        if bester_verlust is None or verlust < bester_verlust - toleranz:
            bestes, bester_verlust = gamma, verlust
        elif abs(verlust - bester_verlust) <= toleranz and gamma < bestes:
            bestes = gamma

    return bestes, {
        "candidates": protokoll,
        "selected": bestes,
        "grid": list(grid),
        "criterion": ("Poissondevianz auf dem spaeteren Teil der "
                      "Trainingshistorie"),
        "tolerance": toleranz,
        "tie_break": "kleineres Gamma gewinnt - die vorsichtigere Wahl",
    }


def _poisson_deviance(staerke, zeilen, lambdas, ligakarte):
    """
    Die Poissondevianz der korrigierten Vorhersagen.

    Dieselbe Groesse, die auch die Anpassung minimiert. Eine andere
    Kennzahl hier waere ein zweiter Massstab und damit eine zweite
    Gelegenheit, die Wahl zu verschieben.
    """
    summe, anzahl = 0.0, 0
    for zeile, (lam_h, lam_a) in zip(zeilen, lambdas):
        liga_h = ligakarte.get(zeile.get("home_id"))
        liga_a = ligakarte.get(zeile.get("away_id"))
        if not liga_h or not liga_a:
            continue
        f_h, f_a = staerke.factors(liga_h, liga_a)
        for lam, faktor, tore in ((lam_h, f_h, zeile.get("home_goals")),
                                  (lam_a, f_a, zeile.get("away_goals"))):
            if (lam is None or not math.isfinite(lam) or lam <= 0
                    or tore is None):
                continue
            mu = max(lam * faktor, 1e-9)
            if tore > 0:
                summe += 2.0 * (tore * math.log(tore / mu) - (tore - mu))
            else:
                summe += 2.0 * mu
            anzahl += 1
    return None if not anzahl else summe / anzahl


def apply_factors(staerke, zeilen, lambdas, ligakarte):
    """
    Die Korrektur anwenden und begrenzen.

    Rueckgabe: (lambdas, statistik). Die Grenzen greifen VOR der
    Wahrscheinlichkeitsberechnung; danach waere die Verteilung bereits
    aus einem unsinnigen Wert entstanden.
    """
    from src.ml.model import LAMBDA_MAX, LAMBDA_MIN

    heraus = []
    geklammert = 0
    kalt = 0
    faktoren = {"home": [], "away": []}

    for zeile, (lam_h, lam_a) in zip(zeilen, lambdas):
        liga_h = ligakarte.get(zeile.get("home_id"))
        liga_a = ligakarte.get(zeile.get("away_id"))

        if not liga_h or not liga_a:
            kalt += 1
            heraus.append((lam_h, lam_a))
            faktoren["home"].append(1.0)
            faktoren["away"].append(1.0)
            continue

        if staerke.is_cold_start(liga_h) or staerke.is_cold_start(liga_a):
            kalt += 1

        f_h, f_a = staerke.factors(liga_h, liga_a)
        faktoren["home"].append(f_h)
        faktoren["away"].append(f_a)

        neu = []
        for lam, faktor in ((lam_h, f_h), (lam_a, f_a)):
            wert = lam * faktor
            begrenzt = min(max(wert, LAMBDA_MIN), LAMBDA_MAX)
            if begrenzt != wert:
                geklammert += 1
            neu.append(begrenzt)
        heraus.append(tuple(neu))

    def verteilung(werte):
        if not werte:
            return None
        geordnet = sorted(werte)
        return {"min": round(geordnet[0], 5),
                "median": round(geordnet[len(geordnet) // 2], 5),
                "max": round(geordnet[-1], 5)}

    return heraus, {
        "factor_min_allowed": FACTOR_MIN,
        "factor_max_allowed": FACTOR_MAX,
        "lambda_min_allowed": LAMBDA_MIN,
        "lambda_max_allowed": LAMBDA_MAX,
        "clamped_lambdas": geklammert,
        "cold_start_matches": kalt,
        "factor_home": verteilung(faktoren["home"]),
        "factor_away": verteilung(faktoren["away"]),
    }
