"""
Individuelle Faktoren fuer die Champions-League-Einzelspielsimulation.

WAS HIER PASSIERT
-----------------
Ein Request darf drei fussballfachliche Groessen verstellen - Offensive,
Defensive und Heimvorteil - und den Einfluss der ML-Korrektur waehlen.
Dieses Modul prueft diese Angaben und wendet sie an. Mehr nicht: Es
rechnet keine Lambdas, keine Wahrscheinlichkeiten und keine Korrektur.
Dafuer bleiben team_profile.expected_goals und die C5/C6/C7-Kette
zustaendig.

DIE FAKTOREN WIRKEN AUF PROFILE, NICHT AUF LAMBDAS
--------------------------------------------------
Sie greifen VOR expected_goals() an. Das ist keine Geschmacksfrage:

    xh = avg_home * attack_home  * defence_away
    xa = avg_away * attack_away  * defence_home

Wer die fertigen Lambdas nachtraeglich skalierte, umginge die
XG-Grenzen und haette denselben Effekt zweimal im Spiel, sobald die
ML-Korrektur dazukommt - denn die liest ihre 16 Merkmale aus genau
diesen Profilen. So gilt stattdessen eine klare Reihenfolge:

    Profile -> individuelle Faktoren -> expected_goals -> ML -> Poisson

Die ML-Korrektur rechnet damit auf den INDIVIDUALISIERTEN Profilen.
Das ist gewollt: Wer die Offensive hochdreht, soll ein Modell sehen,
das diese Offensive kennt.

WARUM DIE DEFENSIVE GETEILT WIRD
--------------------------------
In den Profilen ist defence_* ein GEGNERISCHER Torfaktor: Ein hoher
Wert heisst "kassiert viel". Fuer einen Nutzerregler ist das
kontraintuitiv - dort heisst ein hoher Wert "starke Abwehr". Deshalb

    defence_custom = defence_original / defence_factor

Ein Faktor ueber 1,0 senkt damit den Torfaktor und also die Lambdas.
Die Uebersetzung steht an dieser einen Stelle und nirgends sonst.

WARUM DER HEIMVORTEIL DIE WURZEL BENUTZT
----------------------------------------
    avg_home * sqrt(f)      avg_away / sqrt(f)

Das Produkt beider Schnitte bleibt konstant. Ohne die Wurzel waere
"mehr Heimvorteil" heimlich auch "mehr Tore insgesamt" - zwei
Wirkungen an einem Regler, von denen der Nutzer nur eine erwartet.

STRENG STATT NACHSICHTIG
------------------------
Ein unbekannter Ansatz, ein unbekannter Faktor, ein Wert ausserhalb
der Grenzen: alles wird abgewiesen, nichts still zurechtgebogen. Der
bestehende Parameter simulations wird weiterhin geklammert - das ist
altes, dokumentiertes Verhalten und bleibt unangetastet. Fuer die
neuen Felder gilt die strengere Regel, weil ein still geklammerter
Reglerwert eine falsche Prognose erzeugt, die niemand bemerkt.
"""

import copy
import math

#: Die beiden Berechnungsansaetze.
APPROACH_ML = "ml"
APPROACH_CUSTOM = "custom"
APPROACHES = (APPROACH_ML, APPROACH_CUSTOM)

#: Name -> (minimum, maximum). Die Grenzen stammen aus der
#: C8-Analyse: Sie decken den fachlich sinnvollen Bereich ab und
#: bleiben weit innerhalb der Guardrails von team_profile
#: (RATING 0,35-2,2) und der XG-Grenzen (0,15-4,5).
FACTOR_BOUNDS = {
    "attack": (0.7, 1.3),
    "defence": (0.7, 1.3),
    "home_advantage": (0.5, 1.5),
}

#: Der neutrale Stand. Mit ihm muss die Rechnung bitgleich der
#: bestehenden Baseline entsprechen - ein Test haelt das fest.
NEUTRAL_FACTORS = {name: 1.0 for name in FACTOR_BOUNDS}

#: Grenzen des ML-Gewichts. Dieselbe Skala wie blend.py; eine
#: Prozentangabe rechnet die Oberflaeche um, nicht dieses Modul.
ML_WEIGHT_MIN, ML_WEIGHT_MAX = 0.0, 1.0

#: Standardgewicht je Ansatz.
ML_WEIGHT_FOR_ML = 1.0
ML_WEIGHT_DEFAULT_CUSTOM = 0.0

#: Profilfelder, die die Faktoren anfassen.
ATTACK_FIELDS = ("attack_home", "attack_away")
DEFENCE_FIELDS = ("defence_home", "defence_away")


class InvalidSimulationRequest(ValueError):
    """
    Eine fachlich ungueltige Nutzereingabe.

    Die Meldung ist fuer den Client bestimmt und nennt deshalb nur den
    betroffenen Parameter und den erlaubten Bereich - keine Pfade,
    keine Modellinterna, keine Stacktraces.
    """


# ---------------------------------------------------------------------------
# Pruefung
# ---------------------------------------------------------------------------

def _zahl(wert):
    """Echte, endliche Zahl - kein Wahrheitswert, kein Text."""
    return (isinstance(wert, (int, float)) and not isinstance(wert, bool)
            and math.isfinite(wert))


def _pruefe_faktor(name, wert):
    unten, oben = FACTOR_BOUNDS[name]
    if not _zahl(wert):
        raise InvalidSimulationRequest(
            f"Der Faktor '{name}' muss eine Zahl sein.")
    if not (unten <= wert <= oben):
        raise InvalidSimulationRequest(
            f"Der Faktor '{name}' muss zwischen {unten} und {oben} liegen.")
    return float(wert)


def parse_factors(roh):
    """
    Die drei Faktoren aus dem Request - vollstaendig und geprueft.

    Fehlt das Objekt, gilt der neutrale Stand. Fehlt ein einzelner
    Faktor, gilt fuer ihn 1,0. Ein unbekannter Schluessel wird
    abgewiesen und nicht stillschweigend ignoriert: Wer 'offense'
    statt 'attack' schreibt, soll das erfahren und nicht wundern,
    warum sich nichts tut.
    """
    if roh is None:
        return dict(NEUTRAL_FACTORS)
    if not isinstance(roh, dict):
        raise InvalidSimulationRequest("'factors' muss ein Objekt sein.")

    unbekannt = sorted(set(roh) - set(FACTOR_BOUNDS))
    if unbekannt:
        raise InvalidSimulationRequest(
            f"Unbekannte Faktoren: {', '.join(unbekannt)}. "
            f"Erlaubt sind: {', '.join(sorted(FACTOR_BOUNDS))}.")

    faktoren = dict(NEUTRAL_FACTORS)
    for name in FACTOR_BOUNDS:
        if name in roh:
            faktoren[name] = _pruefe_faktor(name, roh[name])
    return faktoren


def parse_ml_weight(wert, standard):
    if wert is None:
        return standard
    if not _zahl(wert):
        raise InvalidSimulationRequest("'ml_weight' muss eine Zahl sein.")
    if not (ML_WEIGHT_MIN <= wert <= ML_WEIGHT_MAX):
        raise InvalidSimulationRequest(
            f"'ml_weight' muss zwischen {ML_WEIGHT_MIN} und "
            f"{ML_WEIGHT_MAX} liegen.")
    return float(wert)


def parse_options(data):
    """
    Die Simulationsoptionen eines Requests.

    Rueckgabe: None, wenn kein 'approach' gesetzt ist - dann bleibt
    alles beim bisherigen Verhalten samt der C7-Umgebungssteuerung.
    Sonst ein geprueftes Optionsobjekt.

    Bei approach='ml' werden mitgesendete Faktoren oder ein eigenes
    Gewicht ABGEWIESEN statt ignoriert. Beides zugleich anzugeben ist
    ein Widerspruch, und ein stillschweigend verworfener Reglerwert
    waere schlimmer als eine klare Fehlermeldung.
    """
    if not isinstance(data, dict):
        raise InvalidSimulationRequest("Ungueltiger Request.")

    ansatz = data.get("approach")
    if ansatz is None:
        for feld in ("factors", "ml_weight"):
            if feld in data:
                raise InvalidSimulationRequest(
                    f"'{feld}' verlangt ein gesetztes 'approach'.")
        return None

    if not isinstance(ansatz, str) or ansatz not in APPROACHES:
        raise InvalidSimulationRequest(
            f"Unbekannter Ansatz. Erlaubt sind: {', '.join(APPROACHES)}.")

    if ansatz == APPROACH_ML:
        for feld in ("factors", "ml_weight"):
            if feld in data:
                raise InvalidSimulationRequest(
                    f"'{feld}' ist mit approach='ml' nicht zulaessig - "
                    f"dieser Ansatz rechnet mit neutralen Faktoren und "
                    f"vollem ML-Gewicht.")
        return {"approach": APPROACH_ML,
                "factors": dict(NEUTRAL_FACTORS),
                "ml_weight": ML_WEIGHT_FOR_ML}

    return {"approach": APPROACH_CUSTOM,
            "factors": parse_factors(data.get("factors")),
            "ml_weight": parse_ml_weight(data.get("ml_weight"),
                                         ML_WEIGHT_DEFAULT_CUSTOM)}


# ---------------------------------------------------------------------------
# Anwendung
# ---------------------------------------------------------------------------

def is_neutral(faktoren):
    """Sind alle drei Faktoren unveraendert?"""
    return all(faktoren.get(name, 1.0) == 1.0 for name in FACTOR_BOUNDS)


def apply_factors(home_profile, away_profile, league_avg, faktoren):
    """
    Wendet die Faktoren auf KOPIEN an.

    Rueckgabe: (heim, gast, schnitt) - immer neue Objekte.

    Die Profile stammen aus einem prozessweiten Zwischenspeicher
    (cache.cached_call auf "cl_strengths:{season}", 30 Minuten). Wer
    sie an Ort und Stelle veraenderte, verfaelschte damit still jede
    weitere Simulation desselben Prozesses - auch die anderer Nutzer.

    Kopiert wird tief. Eine flache Kopie wuerde hier zwar genuegen,
    weil ausschliesslich vier Gleitkommafelder der obersten Ebene neu
    gesetzt werden und das verschachtelte stats-Dict unberuehrt
    bleibt. Aber diese Zusicherung haengt daran, dass es so bleibt -
    und der Preis ist ein Kopiervorgang je Partie. Ein Test belegt,
    dass die Quellprofile samt ihrer verschachtelten Felder
    unveraendert bleiben.
    """
    heim = copy.deepcopy(home_profile)
    gast = copy.deepcopy(away_profile)
    schnitt = copy.deepcopy(league_avg)

    angriff = faktoren.get("attack", 1.0)
    abwehr = faktoren.get("defence", 1.0)
    heimvorteil = faktoren.get("home_advantage", 1.0)

    for profil in (heim, gast):
        for feld in ATTACK_FIELDS:
            if _zahl(profil.get(feld)):
                profil[feld] = profil[feld] * angriff
        for feld in DEFENCE_FIELDS:
            # Geteilt, nicht multipliziert - siehe Modulkopf.
            if _zahl(profil.get(feld)):
                profil[feld] = profil[feld] / abwehr

    wurzel = math.sqrt(heimvorteil)
    if _zahl(schnitt.get("home_goals")):
        schnitt["home_goals"] = schnitt["home_goals"] * wurzel
    if _zahl(schnitt.get("away_goals")):
        schnitt["away_goals"] = schnitt["away_goals"] / wurzel

    return heim, gast, schnitt


def ml_config(options):
    """
    Die C7-Konfiguration fuer diesen einen Request.

    Rueckgabe: None ohne Optionen - dann entscheidet weiterhin die
    Umgebung, und das bisherige Verhalten bleibt vollstaendig
    erhalten.

    Die Form entspricht runtime.current_config(). Sie wird als
    Argument durchgereicht und NICHT in os.environ geschrieben: Eine
    Umgebungsvariable gilt fuer den ganzen Prozess und damit fuer
    jeden parallelen Request.
    """
    if options is None:
        return None
    return {
        "mode": "active",
        "mode_reason": None,
        "weight": options["ml_weight"],
        "weight_reason": None,
        "raw_weight": options["ml_weight"],
    }
