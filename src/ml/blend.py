"""
Gewichtung zwischen Baseline und ML-Schattenkorrektur.

WAS DAS IST - UND WAS ES NICHT IST
----------------------------------
Die Rechenlogik eines spaeteren Reglers. Sie mischt die bestehende
mathematische Baseline mit der Korrektur aus C5 und liefert das
Ergebnis als Schattenwert. Sie aktiviert nichts, wird von keinem
produktiven Pfad aufgerufen und traegt in jeder Antwort
applied_to_production = False.

C3 bleibt INCONCLUSIVE. Dass sich ein Gewicht rechnen laesst, sagt
nichts darueber, ob es angewandt werden sollte.

DIE FORMEL
----------
    gewichteter_faktor = korrekturfaktor ** gewicht
    gewichtetes_lambda = baseline_lambda * gewichteter_faktor

Multiplikativ im Logarithmus, nicht additiv. Der Grund ist die Bauform
des Modells: Die Korrektur ist ein FAKTOR auf einem Poisson-Lambda,
kein Summand. Eine additive Mischung

    (1 - w) * baseline + w * shadow

waere zwar auch stetig, wuerde aber eine multiplikative Groesse in
eine lineare umdeuten. Bei w = 0,5 und einem Faktor von 4 ergaebe sie
das 2,5-fache statt des 2-fachen - und das 2-fache ist die halbe
Korrektur im Sinne des Modells.

DIE DREI EIGENSCHAFTEN, DIE DARAUS FOLGEN
-----------------------------------------
    w = 0    faktor ** 0 = 1        exakt die Baseline
    w = 1    faktor ** 1 = faktor   exakt das C5-Ergebnis
    w = 0,5  geometrische Mitte     sqrt(baseline * shadow)

Und weil faktor ** w fuer w zwischen 0 und 1 monoton zwischen 1 und
faktor laeuft, liegt jedes gewichtete Lambda zwischen Baseline und
vollem Schattenwert. Daraus folgt die Sicherheitsaussage dieses
Moduls: Liegen beide Endpunkte im gueltigen Bereich, liegt auch jeder
Zwischenwert darin. Die Lambdagrenze ist ein Netz, das bei gueltiger
Baseline nie greift - ein Test belegt das ueber echte CL-Zeilen.

WELCHER FAKTOR VERWENDET WIRD
-----------------------------
Der von C5 gemeldete correction_factor - also der TATSAECHLICH
angewandte, nach den Clamps. Nicht der Rohwert unter
clamps.raw_factor_*. Sonst ergaebe w = 1 nicht das C5-Ergebnis, und
die Endpunktzusage waere gebrochen.
"""

import math

from src.ml import model as mdl

#: Die Gewichtsskala. Ausschliesslich 0,0 bis 1,0 - eine Prozentangabe
#: rechnet die aufrufende Schicht um. Zwei Skalen im selben Modul
#: waeren die sichere Art, 50 fuer 0,5 zu halten.
MIN_WEIGHT, MAX_WEIGHT = 0.0, 1.0

#: Endpunkte und Zwischenwerte, an denen die Eigenschaften geprueft
#: werden. Hier, damit Test und Bericht dieselbe Reihe benutzen.
REFERENCE_WEIGHTS = (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0)

#: Gruende, die C6 selbst vergibt. Ein Grund aus C5 wird durchgereicht
#: und nicht ueberschrieben.
REASON_WEIGHT_INVALID = "weight_invalid"
REASON_SHADOW_INVALID = "shadow_result_invalid"
REASON_BASELINE_INVALID = "baseline_invalid"
REASON_FACTOR_INVALID = "correction_factor_invalid"
REASON_WEIGHTED_NON_FINITE = "weighted_non_finite"

BLEND_REASONS = (REASON_WEIGHT_INVALID, REASON_SHADOW_INVALID,
                 REASON_BASELINE_INVALID, REASON_FACTOR_INVALID,
                 REASON_WEIGHTED_NON_FINITE)

#: Felder, die ein C5-Ergebnis mitbringen muss.
REQUIRED_FIELDS = ("status", "baseline_lambda_home", "baseline_lambda_away",
                   "correction_factor_home", "correction_factor_away")


def _zahl(wert):
    """Endlich, numerisch und kein Wahrheitswert."""
    return (isinstance(wert, (int, float)) and not isinstance(wert, bool)
            and math.isfinite(wert))


def _positiv(wert):
    return _zahl(wert) and wert > 0


def valid_weight(gewicht):
    """
    Ein gueltiges Gewicht liegt in [0, 1] und ist eine echte Zahl.

    Ausserhalb wird NICHT stillschweigend begrenzt. Wer 50 statt 0,5
    uebergibt, hat sich vertippt; ein stilles Clampen auf 1,0 machte
    daraus die volle ML-Korrektur, und der Tippfehler faende sich nie
    wieder.
    """
    return _zahl(gewicht) and MIN_WEIGHT <= gewicht <= MAX_WEIGHT


# ---------------------------------------------------------------------------
# Antwortbau
# ---------------------------------------------------------------------------

def _antwort(status, gewicht, schatten, faktor_home, faktor_away,
             gewichtet_home, gewichtet_away, lambda_home, lambda_away,
             grund, usable, clamps, gewicht_gueltig):
    """
    Die Antwort - immer dieselbe Form, ob gerechnet wurde oder nicht.

    Die Metadaten aus C5 werden durchgereicht, nicht neu erfunden:
    Modellkennung, Kandidat und Qualitaet gehoeren zum Schattenergebnis
    und nicht zur Gewichtung.
    """
    return {
        "status": status,
        "ml_weight": gewicht,
        "weight_valid": gewicht_gueltig,
        "baseline_lambda_home": schatten.get("baseline_lambda_home"),
        "baseline_lambda_away": schatten.get("baseline_lambda_away"),
        "correction_factor_home": faktor_home,
        "correction_factor_away": faktor_away,
        "weighted_factor_home": gewichtet_home,
        "weighted_factor_away": gewichtet_away,
        "weighted_lambda_home": lambda_home,
        "weighted_lambda_away": lambda_away,
        "full_shadow_lambda_home": schatten.get("shadow_lambda_home"),
        "full_shadow_lambda_away": schatten.get("shadow_lambda_away"),
        "model_id": schatten.get("model_id"),
        "candidate": schatten.get("candidate"),
        "quality": schatten.get("quality") or {},
        "fallback_reason": grund,
        "upstream_status": schatten.get("status"),
        "upstream_fallback_reason": schatten.get("fallback_reason"),
        "clamps": clamps,
        "usable": usable,
        "applied_to_production": False,
        # Durchgereicht aus C5 (C0B). Diese Schicht mischt nur; ueber
        # die Anwendung entscheidet runtime.py anhand der Stufe.
        "release_stage": schatten.get("release_stage"),
        "note": "Gewichteter Korrekturwert. Ob er ein Nutzerergebnis "
                "veraendert, entscheidet die Betriebsart zusammen mit "
                "der Freigabestufe.",
    }


def _baseline_antwort(schatten, gewicht, grund, gewicht_gueltig=True,
                      usable=None):
    """
    Der Rueckfall: Faktor 1,0 auf beiden Seiten, Lambda = Baseline.

    Die Baseline wird durchgereicht, auch wenn sie selbst der Grund des
    Rueckfalls ist. usable sagt dann, ob mit dem Ergebnis gerechnet
    werden darf - bei unbrauchbarer Baseline ist es False, und der
    Aufrufer bekommt keine Zahl untergeschoben, die gueltig aussieht.
    """
    basis_home = schatten.get("baseline_lambda_home")
    basis_away = schatten.get("baseline_lambda_away")
    if usable is None:
        usable = _positiv(basis_home) and _positiv(basis_away)

    return _antwort("fallback", gewicht, schatten, 1.0, 1.0, 1.0, 1.0,
                    basis_home, basis_away, grund, usable, None,
                    gewicht_gueltig)


# ---------------------------------------------------------------------------
# Der oeffentliche Vertrag
# ---------------------------------------------------------------------------

def blend_shadow_result(shadow_result, ml_weight):
    """
    Gewichtet ein C5-Schattenergebnis zwischen Baseline und voller Korrektur.

    shadow_result   die vollstaendige Rueckgabe von
                    inference.shadow_lambdas(). Sie wird gelesen und
                    NICHT veraendert.
    ml_weight       0,0 bis 1,0. 0,0 ist die Baseline, 1,0 das volle
                    C5-Ergebnis.

    Rueckgabe: siehe _antwort(). Diese Funktion wirft bei erwartbaren
    Daten- und Zahlenfehlern nicht - sie faellt auf die Baseline
    zurueck. Ein Programmierfehler bleibt sichtbar.

    REIHENFOLGE DER PRUEFUNGEN
    Ein Rueckfall aus C5 hat Vorrang vor einem ungueltigen Gewicht:
    Steht das Ergebnis ohnehin auf der Baseline, aendert kein Gewicht
    daran etwas, und der urspruengliche Grund ist die nuetzlichere
    Auskunft. Damit der Aufrufer seinen Tippfehler trotzdem bemerkt,
    steht weight_valid in jeder Antwort.
    """
    if not isinstance(shadow_result, dict) or any(
            feld not in shadow_result for feld in REQUIRED_FIELDS):
        leer = shadow_result if isinstance(shadow_result, dict) else {}
        return _baseline_antwort(leer, ml_weight, REASON_SHADOW_INVALID,
                                 valid_weight(ml_weight), usable=False)

    gewicht_gueltig = valid_weight(ml_weight)

    # 1. C5 ist bereits zurueckgefallen - der Grund bleibt erhalten.
    if shadow_result.get("status") != "shadow_prediction":
        return _baseline_antwort(
            shadow_result, ml_weight,
            shadow_result.get("fallback_reason") or REASON_SHADOW_INVALID,
            gewicht_gueltig)

    # 2. Das Gewicht selbst.
    if not gewicht_gueltig:
        return _baseline_antwort(shadow_result, ml_weight,
                                 REASON_WEIGHT_INVALID, False)

    basis_home = shadow_result["baseline_lambda_home"]
    basis_away = shadow_result["baseline_lambda_away"]
    if not (_positiv(basis_home) and _positiv(basis_away)):
        return _baseline_antwort(shadow_result, ml_weight,
                                 REASON_BASELINE_INVALID, True, usable=False)

    faktor_home = shadow_result["correction_factor_home"]
    faktor_away = shadow_result["correction_factor_away"]
    if not (_positiv(faktor_home) and _positiv(faktor_away)):
        return _baseline_antwort(shadow_result, ml_weight,
                                 REASON_FACTOR_INVALID, True)

    # 3. Rechnen - ohne Ausnahmebehandlung, und zwar begruendet.
    #
    #    An dieser Stelle sind Faktor, Baseline und Gewicht bereits als
    #    endliche Zahlen groesser null geprueft, und das Gewicht liegt
    #    in [0, 1]. Damit gilt 0 < faktor ** w <= max(1, faktor): Die
    #    Potenz kann weder ueberlaufen noch komplex werden. Ein
    #    try/except haette hier nur eine Zeile abgedeckt, die nicht
    #    fehlschlagen kann - und dabei einen echten Programmierfehler
    #    mitverschluckt.
    #
    #    Der einzige verbleibende Zahlenfall ist ein Ueberlauf des
    #    PRODUKTS bei einer sehr grossen Baseline. Er endet in inf und
    #    wird von der Pruefung darunter gefangen, nicht von einem
    #    Ausnahmefaenger. Ein Test belegt das.
    #
    #    float() steht bewusst davor: Es loest eine Ganzzahl oder einen
    #    Zahlen-Subtyp in einen einfachen Gleitkommawert auf, sodass
    #    hier kein fremder Operator zur Ausfuehrung kommt.
    gewichtet_home = float(faktor_home) ** float(ml_weight)
    gewichtet_away = float(faktor_away) ** float(ml_weight)
    lambda_home = float(basis_home) * gewichtet_home
    lambda_away = float(basis_away) * gewichtet_away

    if not (_positiv(gewichtet_home) and _positiv(gewichtet_away)
            and _positiv(lambda_home) and _positiv(lambda_away)):
        return _baseline_antwort(shadow_result, ml_weight,
                                 REASON_WEIGHTED_NON_FINITE, True)

    # 4. Die Lambdagrenze als Netz.
    #
    #    Sie greift bei gueltiger Baseline nie: faktor ** w laeuft fuer
    #    w in [0, 1] monoton zwischen 1 und faktor, also liegt das
    #    gewichtete Lambda zwischen Baseline und vollem Schattenwert.
    #    C5 hat den Schattenwert bereits begrenzt; liegt auch die
    #    Baseline im Bereich, liegt alles dazwischen darin.
    #
    #    Sie steht trotzdem hier, weil C5 an die Baseline nur die
    #    Bedingung "endlich und groesser null" stellt. Ein Lambda von
    #    10,0 waere dort zulaessig und hier ausserhalb.
    geklammert_home = min(max(lambda_home, mdl.LAMBDA_MIN), mdl.LAMBDA_MAX)
    geklammert_away = min(max(lambda_away, mdl.LAMBDA_MIN), mdl.LAMBDA_MAX)
    wurde_geklammert = (geklammert_home != lambda_home
                        or geklammert_away != lambda_away)

    # Nach einer Begrenzung wird der TATSAECHLICH wirksame Faktor
    # gemeldet. Sonst stimmte die Gleichung
    # lambda = baseline * faktor nicht mehr, und genau darauf verlaesst
    # sich jeder Aufrufer.
    effektiv_home = geklammert_home / float(basis_home)
    effektiv_away = geklammert_away / float(basis_away)

    clamps = {
        "lambda_min_allowed": mdl.LAMBDA_MIN,
        "lambda_max_allowed": mdl.LAMBDA_MAX,
        "clamped_home": geklammert_home != lambda_home,
        "clamped_away": geklammert_away != lambda_away,
        "raw_weighted_factor_home": gewichtet_home,
        "raw_weighted_factor_away": gewichtet_away,
        "raw_weighted_lambda_home": lambda_home,
        "raw_weighted_lambda_away": lambda_away,
        "upstream_clamps": shadow_result.get("clamps"),
        "note": ("bei gueltiger Baseline greift diese Grenze nicht - "
                 "das gewichtete Lambda liegt stets zwischen Baseline "
                 "und vollem Schattenwert"),
    }

    return _antwort("weighted_shadow", ml_weight, shadow_result,
                    faktor_home, faktor_away,
                    effektiv_home if wurde_geklammert else gewichtet_home,
                    effektiv_away if wurde_geklammert else gewichtet_away,
                    geklammert_home, geklammert_away, None, True, clamps,
                    True)


def blend_series(shadow_result, weights=REFERENCE_WEIGHTS):
    """
    Dieselbe Partie ueber mehrere Gewichte - fuer Nachweis und Bericht.

    Rueckgabe: Liste von Ergebnissen in der Reihenfolge der Gewichte.
    Kein Zustand, keine Zwischenspeicherung: Jeder Eintrag entsteht
    ueber denselben Weg wie ein Einzelaufruf.
    """
    return [blend_shadow_result(shadow_result, gewicht)
            for gewicht in weights]
