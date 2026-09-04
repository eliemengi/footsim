"""
Ablation des Schattenmodells - woher kommt die gemessene Verbesserung?

DIE FRAGE
---------
shadow_eval hat -0,00944 LogLoss gegenueber der Baseline gemessen.
Diese Datei beantwortet, welcher Teil des Merkmalssatzes das traegt.

ZWEI STUFEN
-----------
Stufe 1 (feature_groups.VARIANTS) trennt Profil- von
Belastungsmerkmalen. Ergebnis: Die Verbesserung stammt vollstaendig aus
profile_only (-0,01446); die Belastungsmerkmale tragen nichts bei und
verwaessern den Effekt sogar.

Stufe 2 (feature_groups.DIAGNOSTIC_VARIANTS) zerlegt profile_only
weiter, weil die erste Stufe offenliess, WAS daran wirkt: ein blosser
Achsenabschnitt, der Ligadurchschnitt allein, die Teamprofile allein.
Hinzu kommen gepaarte Vergleiche ZWISCHEN Varianten - siehe
PAIRED_COMPARISONS.

DAS VERFAHREN BLEIBT UNANGETASTET
---------------------------------
Es wird KEIN zweites Auswertungsverfahren gebaut. Jede Variante laeuft
durch dieselbe Funktion, die auch die bisherige Auswertung benutzt:

    evaluate.evaluate_fold(zeilen, fold, spalten, alphas)

Der einzige Unterschied zwischen den Varianten ist das Argument
spalten. Damit gelten unveraendert:

    - dieselben aeusseren Folds (2023 -> 2024, 2023+2024 -> 2025)
    - dieselbe innere Alphawahl AUSSCHLIESSLICH im Trainingsfold
    - dieselbe Baseline, Modellform, Offsetrechnung und dieselben Clamps
    - dieselbe Aggregation nach Spielen und derselbe gepaarte Bootstrap

Ein eigener Rechenweg fuer die Ablation waere die sicherste Art, einen
Unterschied zu messen, der nur aus dem Messaufbau stammt.

NO_CORRECTION BRAUCHT KEINEN SONDERPFAD
---------------------------------------
Die Kontrolle laeuft mit einer leeren Merkmalsliste und einem leeren
Alphakandidatensatz durch dieselbe Funktion. select_candidate() misst
dann keinen einzigen Kandidaten, faellt auf model.NO_CORRECTION zurueck
und predict_lambdas() gibt die Baseline-Lambdas unveraendert heraus.
sklearn wird dabei nie aufgerufen.

Das ist ausdruecklich beabsichtigt: Eine Kontrolle, die durch eigenen
Code laeuft, kontrolliert nur diesen Code.

WAS DIE ANTEILE AUSSAGEN - UND WAS NICHT
----------------------------------------
attribution() setzt das Delta einer Teilmenge ins Verhaeltnis zum Delta
des vollen Satzes. Diese Anteile addieren sich NICHT zwangslaeufig zu
eins: Merkmale koennen einander ersetzen (dann summieren sie sich ueber
eins) oder erst gemeinsam wirken (dann darunter). Der Wert ist ein
Hinweis auf die Herkunft der Verbesserung, keine Zerlegung in Summanden
und keine Varianzaufteilung.
"""

from src.ml import evaluate as ev
from src.ml import feature_groups as fg
from src.ml import model as mdl

#: Fassung des Ablationsergebnisses.
#:
#: 1 - erste Stufe: results traegt comparison, attribution, variants.
#: 2 - zweite Stufe kam hinzu; results traegt zusaetzlich
#:     paired_comparisons und test_match_count.
#:
#: Erhoeht, weil sich die FORM geaendert hat, nicht die Zahlen. Ohne
#: die Erhoehung trugen zwei verschieden aufgebaute Artefakte dieselbe
#: Fassungsnummer, und ein spaeterer Leser haette nicht entscheiden
#: koennen, ob paired_comparisons fehlt oder nur leer ist.
SCHEMA_VERSION = 2

#: Der Massstab, gegen den die Anteile gerechnet werden.
REFERENZVARIANTE = "all_existing_features"

#: Unterhalb dieses Betrags gilt das Gesamtdelta als zu klein, um
#: Anteile daran sinnvoll zu bilden. 1e-6 liegt eine Groessenordnung
#: unter der fuenften Nachkommastelle, in der die Vergleiche
#: stattfinden - ein Quotient mit kleinerem Nenner waere Rauschen mit
#: Nachkommastellen.
MIN_NENNER = 1e-6


def run_variant(zeilen, definition, folds=ev.OUTER_FOLDS,
                alphas=mdl.ALPHA_CANDIDATES, gruppen=None, spalten=None):
    """
    Eine Variante ueber alle aeusseren Folds.

    Rueckgabe: ein Ergebnisblock je Variante, aufgebaut wie das
    Ergebnis von evaluate.run_evaluation() - Folds, Aggregat,
    Merkmalsliste -, ergaenzt um Name, Gruppen und Beschreibung.

    Der Schluessel _losses traegt die Verluste je Spiel ueber alle
    Folds hinweg. Er ist die Grundlage der gepaarten
    Variantenvergleiche und wird von run_ablation() entfernt, bevor das
    Ergebnis ins Artefakt geht.
    """
    name = definition["name"]
    merkmale = fg.columns_for(name, gruppen, spalten)
    modus = definition.get("mode", fg.MODE_FEATURES)

    # Die Betriebsart entscheidet, nicht die Merkmalszahl. Sonst waeren
    # no_correction und intercept_only nicht auseinanderzuhalten -
    # beide haben null Merkmale.
    #
    # baseline: ein leerer Kandidatensatz fuehrt select_candidate()
    #   auf no_correction, ohne dass hier ein Sonderfall entsteht.
    # intercept: alle Alphas treten an, obwohl sie mathematisch
    #   dasselbe Modell ergeben - dass ihre inneren Verluste identisch
    #   herauskommen, ist im Auswahlprotokoll nachpruefbar und damit
    #   ein Beleg statt einer Behauptung.
    kandidaten = () if modus == fg.MODE_BASELINE else tuple(alphas)

    if modus == fg.MODE_FEATURES and not merkmale:
        raise ValueError(
            f"Variante {name!r} ist als {fg.MODE_FEATURES!r} gefuehrt, "
            f"traegt aber kein Merkmal - gemeint war vermutlich "
            f"{fg.MODE_BASELINE!r} oder {fg.MODE_INTERCEPT!r}")
    if modus == fg.MODE_INTERCEPT and merkmale:
        raise ValueError(
            f"Variante {name!r} ist als {fg.MODE_INTERCEPT!r} gefuehrt, "
            f"traegt aber {len(merkmale)} Merkmale")

    ergebnisse = [ev.evaluate_fold(zeilen, fold, merkmale, kandidaten)
                  for fold in folds]
    zusammen = ev.aggregate(ergebnisse)

    # Vor dem Entfernen einsammeln: die Verluste je Spiel, in
    # Foldreihenfolge aneinandergehaengt. Dieselbe Reihenfolge fuer
    # jede Variante, weil evaluate_fold seinen Testbestand ueber
    # eligible_rows() deterministisch sortiert.
    verluste = {"log_loss": [], "brier": [], "rps": []}
    for fold in ergebnisse:
        intern = fold.get("_internal") or {}
        for schluessel in verluste:
            verluste[schluessel].extend(
                (intern.get("ml_losses") or {}).get(schluessel, []))

    # Derselbe Grund wie in run_evaluation(): Der interne Block traegt
    # Verlustlisten je Spiel, ist Grundlage der Aggregation und blaeht
    # das Artefakt sonst auf.
    for fold in ergebnisse:
        fold.pop("_internal", None)

    return {
        "_losses": verluste,
        "mode": modus,
        "variant": name,
        "description": definition["description"],
        "groups": list(definition["groups"]),
        "feature_columns": merkmale,
        "feature_count": len(merkmale),
        "alpha_candidates": list(kandidaten),
        "selected_candidates": [
            {"fold": fold.get("fold"),
             "selected": fold.get("selected_candidate"),
             "inner_log_loss": (fold.get("selection") or {}).get(
                 "selected_inner_log_loss"),
             "baseline_inner_log_loss": (fold.get("selection") or {}).get(
                 "baseline_inner_log_loss")}
            for fold in ergebnisse],
        "folds": ergebnisse,
        "aggregate": zusammen,
    }


def _kennzahlen(variante):
    """Die Vergleichszeile einer Variante - oder None ohne Aggregat."""
    zusammen = variante.get("aggregate")
    if not zusammen:
        return None

    bootstrap = zusammen.get("bootstrap") or {}
    zeile = {
        "variant": variante["variant"],
        "mode": variante.get("mode"),
        "groups": list(variante["groups"]),
        "feature_count": variante["feature_count"],
        "n": zusammen["n"],
        "selected_candidates": [eintrag["selected"]
                                for eintrag in variante["selected_candidates"]],
    }
    for name in ("log_loss", "brier", "rps"):
        zeile[f"baseline_{name}"] = zusammen["baseline"][name]
        zeile[f"ml_{name}"] = zusammen["ml"][name]
        zeile[f"delta_{name}"] = zusammen[f"delta_{name}"]

    intervall = bootstrap.get("log_loss")
    if intervall:
        zeile["log_loss_ci_low"] = intervall["ci_low"]
        zeile["log_loss_ci_high"] = intervall["ci_high"]
        zeile["log_loss_interpretation"] = intervall["interpretation"]

    zeile["calibration_error_baseline"] = zusammen["baseline"][
        "calibration_error"]
    zeile["calibration_error_ml"] = zusammen["ml"]["calibration_error"]
    return zeile


def comparison(varianten):
    """Die Vergleichstabelle - eine Zeile je Variante, feste Reihenfolge."""
    zeilen = []
    for variante in varianten:
        zeile = _kennzahlen(variante)
        if zeile is not None:
            zeilen.append(zeile)
    return zeilen


def attribution(vergleich, referenz=REFERENZVARIANTE):
    """
    Anteil jeder Teilmenge am Delta des vollen Merkmalssatzes.

    Rueckgabe: None, solange der volle Satz die Baseline nicht
    verbessert - an einer Nichtverbesserung ist nichts aufzuteilen, und
    ein Quotient waere hier bestenfalls verwirrend.

    Die Einschraenkung aus dem Modulkopf gilt und steht deshalb auch im
    Ergebnis: Die Anteile addieren sich nicht zwangslaeufig zu eins.
    """
    nach_name = {zeile["variant"]: zeile for zeile in vergleich}
    voll = nach_name.get(referenz)
    if voll is None:
        return None

    gesamt = voll["delta_log_loss"]
    if gesamt is None or gesamt >= 0 or abs(gesamt) < MIN_NENNER:
        return {
            "reference": referenz,
            "reference_delta_log_loss": gesamt,
            "shares": None,
            "note": "der volle Merkmalssatz verbessert die Baseline nicht "
                    "belastbar - es gibt keinen Effekt aufzuteilen",
        }

    anteile = []
    for zeile in vergleich:
        if zeile["variant"] == referenz:
            continue
        delta = zeile["delta_log_loss"]
        # Das +0.0 faengt die negative Null ab: 0.0 geteilt durch ein
        # negatives Gesamtdelta ergibt -0.0, und "-0.0%" im Bericht
        # liest sich wie ein Vorzeichenfehler.
        anteile.append({
            "variant": zeile["variant"],
            "delta_log_loss": delta,
            "share_of_reference": (None if delta is None
                                   else delta / gesamt + 0.0),
        })

    return {
        "reference": referenz,
        "reference_delta_log_loss": gesamt,
        "shares": anteile,
        "note": "Anteil = delta_variante / delta_referenz. Die Anteile "
                "addieren sich NICHT zwangslaeufig zu eins: Merkmale "
                "koennen einander ersetzen oder erst gemeinsam wirken. "
                "Der Wert weist auf die Herkunft der Verbesserung hin "
                "und zerlegt sie nicht in Summanden.",
    }


# ---------------------------------------------------------------------------
# Gepaarte Vergleiche ZWISCHEN Varianten
# ---------------------------------------------------------------------------

#: Die Paarvergleiche der zweiten Diagnosestufe, vorab festgelegt.
#:
#: Gelesen wird jedes Paar als "erste gegen zweite": Ein negatives
#: Delta heisst, die ERSTE ist besser. Damit gilt dieselbe
#: Vorzeichenrichtung wie ueberall sonst - negativ ist besser.
#:
#: Warum es diese Vergleiche ueberhaupt braucht: Der Bootstrap der
#: Vergleichstabelle misst jede Variante gegen die BASELINE. Aus zwei
#: solchen Intervallen laesst sich nicht ablesen, ob sich die beiden
#: Varianten voneinander unterscheiden - ihre Intervalle koennen
#: ueberlappen, obwohl die gepaarte Differenz eindeutig ist. Genau
#: diese Luecke stand am Ende der ersten Stufe offen.
PAIRED_COMPARISONS = (
    ("profile_only", "all_existing_features"),
    ("profile_only", "intercept_only"),
    ("profile_only", "team_profile_only"),
)


def evaluation_row_order(zeilen, folds=ev.OUTER_FOLDS):
    """
    Die Reihenfolge der Testspiele ueber alle Folds.

    Ueber dieselbe Funktion wie evaluate_fold - eine zweite Sortierung
    waere die sicherste Art, zwei Verlustlisten falsch zu paaren und es
    nie zu merken.
    """
    reihenfolge = []
    for fold in folds:
        reihenfolge.extend(z["row_id"] for z
                           in ev.eligible_rows(zeilen, fold["test_seasons"]))
    return reihenfolge


def paired_variant_comparison(name_a, name_b, verluste, laenge=None):
    """
    Gepaarter Bootstrap zwischen zwei Varianten.

    delta = a - b. Negativ heisst: a ist besser als b.

    Entscheidend ist wieder die PAARUNG: In jeder Wiederholung werden
    dieselben Spielindizes fuer beide Varianten gezogen. Die Varianten
    unterscheiden sich nur im Modell, nicht im Bestand - zwei
    unabhaengige Ziehungen wuerden diesen gemeinsamen Anteil als
    Rauschen behandeln und das Intervall unbrauchbar weit machen.

    Derselbe Seed wie ueberall: Zwei Vergleiche unterscheiden sich
    dadurch wegen der Modelle und nicht wegen des Zufalls.
    """
    for name in (name_a, name_b):
        if name not in verluste:
            raise ValueError(
                f"fuer den Paarvergleich fehlt die Variante {name!r} - "
                f"vorhanden sind {sorted(verluste)}")

    a = verluste[name_a]["log_loss"]
    b = verluste[name_b]["log_loss"]
    if len(a) != len(b):
        raise ValueError(
            f"{name_a} hat {len(a)} Spiele, {name_b} hat {len(b)} - "
            f"eine Paarung waere nicht definiert")
    if laenge is not None and len(a) != laenge:
        raise ValueError(
            f"{name_a}/{name_b} tragen {len(a)} Spiele, der Testbestand "
            f"umfasst {laenge} - die Verluste passen nicht zur "
            f"Spielreihenfolge")

    # paired_bootstrap rechnet ml - basis. b ist hier die Bezugsgroesse,
    # a die verglichene - so ergibt sich delta = a - b.
    intervall = ev.paired_bootstrap(b, a)
    if intervall:
        intervall = dict(intervall)
        intervall["interpretation"] = ev.interpret(intervall)

    return {
        "variant": name_a,
        "reference": name_b,
        "n": len(a),
        "delta_log_loss": (None if not intervall else intervall["point"]),
        "bootstrap": intervall,
        "delta_convention": f"delta = {name_a} - {name_b}; negativ bedeutet "
                            f"{name_a} besser",
    }


def paired_comparisons(varianten, paare=PAIRED_COMPARISONS, laenge=None):
    """Alle geforderten Paarvergleiche, in fester Reihenfolge."""
    verluste = {variante["variant"]: variante["_losses"]
                for variante in varianten if "_losses" in variante}
    return [paired_variant_comparison(a, b, verluste, laenge)
            for a, b in paare]


def run_ablation(zeilen, folds=ev.OUTER_FOLDS, alphas=mdl.ALPHA_CANDIDATES,
                 varianten=fg.VARIANTS, paare=()):
    """
    Die vollstaendige Ablation.

    Die Gruppen werden EINMAL gebaut und geprueft, bevor die erste
    Variante rechnet. Ein Abbruch soll vor der teuren Rechnung stehen,
    nicht danach - und vor allem nicht erst bei der dritten Variante,
    wenn die ersten beiden schon Zahlen geliefert haben, die dann
    niemand mehr richtig einordnen kann.

    paare: Paarvergleiche zwischen Varianten. Ohne Angabe keine - die
    erste Stufe kam ohne sie aus, und ein stillschweigend
    hinzugekommener Block wuerde ihr Artefakt veraendern.
    """
    spalten = mdl.feature_columns()
    gruppen = fg.build_groups(spalten)
    gruppeninfo = fg.validate_groups(gruppen, spalten)
    fg.check_variant_consistency()

    ergebnisse = [run_variant(zeilen, definition, folds, alphas,
                              gruppen, spalten)
                  for definition in varianten]

    reihenfolge = evaluation_row_order(zeilen, folds)
    vergleiche = paired_comparisons(ergebnisse, paare, len(reihenfolge)) \
        if paare else []

    vergleich = comparison(ergebnisse)

    # Die Verlustlisten haben ihren Zweck erfuellt. Sie tragen einen
    # Wert je Spiel und Variante und gehoeren nicht ins Artefakt.
    for variante in ergebnisse:
        variante.pop("_losses", None)

    return {
        "feature_groups": gruppeninfo,
        "variants": ergebnisse,
        "comparison": vergleich,
        "attribution": attribution(vergleich),
        "paired_comparisons": vergleiche,
        "test_match_count": len(reihenfolge),
    }
