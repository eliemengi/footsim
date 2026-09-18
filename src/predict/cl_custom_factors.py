"""
Individuelle Faktoren fuer die Champions-League-Einzelspielsimulation.

WAS HIER PASSIERT
-----------------
Ein Request darf vier fussballfachliche Groessen verstellen -
Heimteam-Staerke, Auswaertsteam-Staerke, Heimvorteil und Torniveau
(V2-C17, siehe FACTOR_BOUNDS weiter unten). Dieses Modul prueft diese
Angaben und wendet sie an. Mehr nicht: Es rechnet keine Lambdas, keine
Wahrscheinlichkeiten und keine Korrektur. Dafuer bleiben
team_profile.expected_goals und die C5/C6/C7-Kette zustaendig.

ML IST EINE MODUSAUSWAHL, KEIN DOSIERBARER ANTEIL (V2-C17-HARTUNG)
--------------------------------------------------------------------
approach='custom' waehlt die eigene Einschaetzung. Er laedt KEIN
Modell und wendet keine ML-Korrektur an - auch nicht anteilig. Ein
Request darf deshalb kein eigenes 'ml_weight' mehr mitschicken: Vor
dieser Haertung akzeptierte parse_ml_weight() jeden Wert zwischen 0,0
und 1,0 auch fuer 'custom', und ml_config() reichte ihn ungeprueft an
die Einstiegsfunktion der Runtime-Schicht durch (siehe runtime.py).
Ein Request mit approach='custom' und ml_weight=0.5 lud damit
tatsaechlich das aktive Modell und mischte seine Korrektur zur Haelfte
in die individualisierte Baseline - genau das Blending, das die beiden
Modi ausdruecklich nicht haben duerfen. Jetzt ist das Gewicht fuer
beide Ansaetze eine reine Serverkonstante (ML_WEIGHT_FOR_ML bzw.
ML_WEIGHT_DEFAULT_CUSTOM); ein
mitgesendetes 'ml_weight' wird unabhaengig von seinem Wert abgewiesen,
nicht stillschweigend ignoriert oder gekappt.

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

#: Die drei Berechnungsansaetze.
#:
#: 'classic' (seit dem Block "drei Simulationsansaetze") ist die
#: aktuelle klassische Engine ohne ML: dieselben Profile, derselbe
#: Stichtag, dieselbe Monte-Carlo-Simulation, keine Faktoren und keine
#: ML-Korrektur. Monte Carlo ist dabei das Simulationsverfahren ALLER
#: drei Ansaetze, nicht ein Merkmal des klassischen.
APPROACH_ML = "ml"
APPROACH_CUSTOM = "custom"
APPROACH_CLASSIC = "classic"
APPROACHES = (APPROACH_ML, APPROACH_CUSTOM, APPROACH_CLASSIC)

#: Name -> (minimum, maximum). Die Grenzen stammen aus der
#: C8-Analyse: Sie decken den fachlich sinnvollen Bereich ab und
#: bleiben weit innerhalb der Guardrails von team_profile
#: (RATING 0,35-2,2) und der XG-Grenzen (0,15-4,5).
#: V2-C17: VIER Regler, und jeder bewegt etwas anderes.
#:
#: DER FEHLER, DER HIER VERSCHWINDET
#: Bis C17 gab es `attack` und `defence`, beide symmetrisch auf BEIDE
#: Mannschaften angewandt. Nachgerechnet an der Formel:
#:
#:     xh = avg_h * attack_home(heim) * defence_away(gast)
#:     xa = avg_a * attack_away(gast) * defence_home(heim)
#:
#: Ein `attack` von f multiplizierte attack_* in beiden Profilen, ein
#: `defence` von d teilte defence_* in beiden. Beide Lambdas wurden
#: damit mit demselben Wert f/d skaliert. Die zwei Regler waren
#: dieselbe Wirkung, nur invers - wer die Offensive um 10 Prozent
#: anhob, haette ebenso die Defensive um 9 Prozent senken koennen.
#: Zwei Bedienelemente fuer eine Wirkung sind keine Wahl, sondern eine
#: Verwechslungsgelegenheit.
#:
#: DIE VIER RICHTUNGEN
#: Das Modell hat genau zwei Freiheitsgrade, xh und xa. Vier Regler
#: sind deshalb vier RICHTUNGEN in dieser Ebene, und keine zwei davon
#: sind dieselbe:
#:
#:     home_strength    xh hoch, xa unveraendert
#:     away_strength    xa hoch, xh unveraendert
#:     home_advantage   xh hoch, xa runter - Summe bleibt
#:     goal_level       beide hoch - Verhaeltnis bleibt
#:
#: Mehr Regler waeren keine zusaetzliche Faehigkeit, sondern nur
#: weitere Linearkombinationen derselben Ebene.
FACTOR_BOUNDS = {
    "home_strength": (0.7, 1.3),
    "away_strength": (0.7, 1.3),
    "home_advantage": (0.5, 1.5),
    "goal_level": (0.75, 1.25),
}

#: Der neutrale Stand. Mit ihm muss die Rechnung bitgleich der
#: bestehenden Baseline entsprechen - ein Test haelt das fest.
NEUTRAL_FACTORS = {name: 1.0 for name in FACTOR_BOUNDS}

#: Welche Faktoren fuer eine GANZE LIGAPHASE eine Bedeutung haben.
#:
#: home_strength und away_strength multiplizieren den Angriff des
#: Heim- bzw. Gastteams EINER Partie. Ueber 144 Paarungen mit
#: wechselnden Rollen gibt es kein "Heimteam" - jeder Verein ist
#: viermal Heim- und viermal Gastteam. Eine globale Anwendung waere
#: eine erfundene Semantik und wird deshalb abgewiesen, nicht geraten.
#:
#: home_advantage und goal_level wirken auf den Ligaschnitt und damit
#: auf jede Partie gleich. Genau diese zwei sind in der Ligaphase
#: zulaessig, mit denselben Grenzen und derselben Formel wie im
#: Einzelspiel (apply_league_factors).
SEASON_FACTOR_NAMES = ("home_advantage", "goal_level")
TEAM_FACTOR_NAMES = ("home_strength", "away_strength")

#: Das ML-Gewicht je Ansatz - reine Serverkonstanten (V2-C17-Haertung).
#:
#: Vor der Haertung war 'ml_weight' bei approach='custom' ein vom
#: Client gesetzter Wert zwischen 0,0 und 1,0: eine dosierbare Mischung
#: zwischen der individualisierten Baseline und der ML-Korrektur -
#: also genau das Blending, das die beiden Modi nicht haben duerfen.
#: Jetzt bestimmt ausschliesslich der Ansatz das Gewicht, und
#: parse_options() weist ein mitgesendetes 'ml_weight' fuer BEIDE
#: Ansaetze ab (siehe dort). Diese zwei Werte sind die einzigen, die
#: je vorkommen koennen.
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


def parse_options(data):
    """
    Die Simulationsoptionen eines Requests.

    Rueckgabe: None, wenn kein 'approach' gesetzt ist - dann bleibt
    alles beim bisherigen Verhalten samt der C7-Umgebungssteuerung.
    Sonst ein geprueftes Optionsobjekt.

    'ml_weight' ist KEIN Requestfeld mehr, fuer keinen der beiden
    Ansaetze (V2-C17-Haertung). Es wird bei approach='ml' UND bei
    approach='custom' abgewiesen, sobald es im Request steht -
    unabhaengig von seinem Wert, auch wenn er zufaellig dem
    serverseitig ohnehin geltenden Gewicht entspraeche. Das Gewicht
    ergibt sich ausschliesslich aus dem Ansatz:
    ML_WEIGHT_FOR_ML fuer 'ml', ML_WEIGHT_DEFAULT_CUSTOM fuer 'custom'.
    Ein stillschweigend ignorierter oder gekappter Clientwert waere
    hier die falsche Antwort - er koennte nie mehr etwas bewirken,
    saehe fuer den Aufrufer aber wie eine akzeptierte Eingabe aus.
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

    if ansatz == APPROACH_CLASSIC:
        for feld in ("factors", "ml_weight"):
            if feld in data:
                raise InvalidSimulationRequest(
                    f"'{feld}' ist mit approach='classic' nicht zulaessig - "
                    f"die klassische Simulation rechnet ohne eigene "
                    f"Faktoren und ohne ML.")
        return {"approach": APPROACH_CLASSIC,
                "factors": dict(NEUTRAL_FACTORS),
                "ml_weight": ML_WEIGHT_DEFAULT_CUSTOM}

    if "ml_weight" in data:
        raise InvalidSimulationRequest(
            "'ml_weight' ist mit approach='custom' nicht zulaessig - "
            "dieser Ansatz laedt kein Modell, das Gewicht ist immer 0.")

    return {"approach": APPROACH_CUSTOM,
            "factors": parse_factors(data.get("factors")),
            "ml_weight": ML_WEIGHT_DEFAULT_CUSTOM}


# ---------------------------------------------------------------------------
# Anwendung
# ---------------------------------------------------------------------------

def is_neutral(faktoren):
    """Sind alle vier Faktoren unveraendert?"""
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

    heim_staerke = faktoren.get("home_strength", 1.0)
    gast_staerke = faktoren.get("away_strength", 1.0)
    heimvorteil = faktoren.get("home_advantage", 1.0)
    torniveau = faktoren.get("goal_level", 1.0)

    # Jeder Regler fasst genau den Term an, ueber den er wirkt.
    #
    #   attack_home des HEIMteams geht nur in xh ein,
    #   attack_away des GASTteams nur in xa.
    #
    # Damit bleibt die Wirkung getrennt und nachvollziehbar. Wuerde
    # man stattdessen die Abwehr des Gegners anfassen, waere das
    # rechnerisch dasselbe und im Kopf des Nutzers etwas anderes.
    if _zahl(heim.get("attack_home")):
        heim["attack_home"] = heim["attack_home"] * heim_staerke
    if _zahl(gast.get("attack_away")):
        gast["attack_away"] = gast["attack_away"] * gast_staerke

    # Heimvorteil verschiebt, ohne die Summe zu bewegen. Ohne die
    # Wurzel waere "mehr Heimvorteil" heimlich auch "mehr Tore".
    _ligaschnitt_anpassen(schnitt, heimvorteil, torniveau)

    return heim, gast, schnitt


def _ligaschnitt_anpassen(schnitt, heimvorteil, torniveau):
    """
    Die beiden globalen Faktoren auf einen Ligaschnitt - an Ort und
    Stelle, deshalb ausschliesslich auf bereits kopierten Objekten.

    EINE Formel fuer Einzelspiel und Ligaphase: apply_factors() und
    apply_league_factors() rufen beide genau diese Funktion. Zwei
    Fassungen koennten auseinanderlaufen, und die Paritaet zwischen
    beiden Pfaden hinge dann an einem Zufall.
    """
    wurzel = math.sqrt(heimvorteil)
    if _zahl(schnitt.get("home_goals")):
        schnitt["home_goals"] = schnitt["home_goals"] * wurzel * torniveau
    if _zahl(schnitt.get("away_goals")):
        schnitt["away_goals"] = schnitt["away_goals"] / wurzel * torniveau


def apply_league_factors(league_avg, faktoren):
    """
    Heimvorteil und Torniveau auf eine KOPIE des Ligaschnitts.

    Fuer die Ligaphase: Die Teamprofile bleiben unberuehrt, weil die
    beiden Teamfaktoren dort keine Bedeutung haben (siehe
    SEASON_FACTOR_NAMES). Der Ligaschnitt stammt aus demselben
    prozessweiten Zwischenspeicher wie im Einzelspiel und wird deshalb
    nie an Ort und Stelle veraendert.
    """
    schnitt = copy.deepcopy(league_avg)
    _ligaschnitt_anpassen(schnitt, faktoren.get("home_advantage", 1.0),
                          faktoren.get("goal_level", 1.0))
    return schnitt


# ---------------------------------------------------------------------------
# Die Ligaphase: Optionen aus den Query-Parametern
# ---------------------------------------------------------------------------

#: Parameter, die in der Ligaphase NIE zulaessig sind. Ein stilles
#: Ignorieren saehe aus wie eine angenommene Eingabe.
_SEASON_FORBIDDEN = ("ml_weight", "factors") + TEAM_FACTOR_NAMES


def _zahl_aus_text(name, roh):
    """Eine endliche Zahl aus einem Query-Parameter - oder abweisen."""
    if isinstance(roh, bool):
        raise InvalidSimulationRequest(
            f"Der Faktor '{name}' muss eine Zahl sein.")
    try:
        wert = float(str(roh).strip())
    except (TypeError, ValueError):
        raise InvalidSimulationRequest(
            f"Der Faktor '{name}' muss eine Zahl sein.")
    if not math.isfinite(wert):
        raise InvalidSimulationRequest(
            f"Der Faktor '{name}' muss eine endliche Zahl sein.")
    return wert


def _einzelwert(args, name):
    """Genau ein Wert je Parameter; doppelte Angaben werden abgewiesen."""
    if hasattr(args, "getlist") and len(args.getlist(name)) > 1:
        raise InvalidSimulationRequest(
            f"'{name}' darf nur einmal angegeben werden.")
    return args.get(name)


def parse_season_options(args):
    """
    Die Simulationsoptionen der Ligaphase aus den Query-Parametern.

    Rueckgabe: None ohne 'approach' - dann bleibt es bei der bisherigen
    Serversteuerung ueber die Umgebung (alte Clients). Sonst dieselbe
    Form wie parse_options(), damit ml_config() und die Faktoranwendung
    fuer beide Simulationspfade dieselben sind.

    Zulaessig:
      approach=ml        ohne weitere Faktoren, volles ML-Gewicht
      approach=classic   ohne Faktoren, ML aus
      approach=custom    optional home_advantage und goal_level, ML aus

    Abgewiesen, jeweils mit 400: ein unbekannter Ansatz, ml_weight,
    factors, home_strength und away_strength (in der Ligaphase ohne
    Bedeutung), globale Faktoren ohne approach=custom, nicht endliche
    oder ausserhalb der Grenzen liegende Werte, doppelte Parameter.
    Andere Parameter (season, simulations, mode) gehoeren der Route.
    """
    ansatz = _einzelwert(args, "approach")
    vorhanden = [name for name in _SEASON_FORBIDDEN + SEASON_FACTOR_NAMES
                 if name in args]

    if ansatz is None:
        if vorhanden:
            raise InvalidSimulationRequest(
                f"'{vorhanden[0]}' verlangt ein gesetztes 'approach'.")
        return None

    if not isinstance(ansatz, str) or ansatz not in APPROACHES:
        raise InvalidSimulationRequest(
            f"Unbekannter Ansatz. Erlaubt sind: {', '.join(APPROACHES)}.")

    for name in ("ml_weight", "factors"):
        if name in args:
            raise InvalidSimulationRequest(
                f"'{name}' ist in der Ligaphase nicht zulaessig.")
    for name in TEAM_FACTOR_NAMES:
        if name in args:
            raise InvalidSimulationRequest(
                f"'{name}' gilt nur fuer ein einzelnes Spiel und ist in der "
                f"Ligaphase nicht zulaessig.")

    faktoren = dict(NEUTRAL_FACTORS)
    if ansatz != APPROACH_CUSTOM:
        for name in SEASON_FACTOR_NAMES:
            if name in args:
                raise InvalidSimulationRequest(
                    f"'{name}' verlangt approach='custom'.")
    else:
        for name in SEASON_FACTOR_NAMES:
            if name in args:
                faktoren[name] = _pruefe_faktor(
                    name, _zahl_aus_text(name, _einzelwert(args, name)))

    return {"approach": ansatz,
            "factors": faktoren,
            "ml_weight": (ML_WEIGHT_FOR_ML if ansatz == APPROACH_ML
                          else ML_WEIGHT_DEFAULT_CUSTOM)}


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

    approach='ml' ergibt 'active' mit vollem Gewicht - das ist der
    ganze Zweck des Ansatzes. approach='custom' ergibt 'off', NICHT
    'active' mit Gewicht 0 (V2-C17-Haertung): runtime.resolve_
    simulation_lambdas() ueberspringt den ML-Zweig in 'off' vollstaendig
    und ruft inference.shadow_lambdas() gar nicht erst auf. Vor dieser
    Aenderung stand hier fuer BEIDE Ansaetze 'active', und ein
    aktiviertes Modell wurde bei jedem individuellen Request geladen
    und gerechnet - nur sein Gewicht war meist 0 und damit rechnerisch
    wirkungslos (faktor ** 0 = 1). Rechnerisch wirkungslos ist nicht
    dasselbe wie "nicht geladen": Ein mitgesendetes Gewicht ungleich 0
    haette in genau diesem Pfad gegriffen. Diese Funktion nimmt gar
    nicht erst ein Gewicht aus dem Request entgegen - parse_options()
    weist es vorher ab.
    """
    if options is None:
        return None
    if options["approach"] == APPROACH_ML:
        return {
            "mode": "active",
            "mode_reason": None,
            "weight": ML_WEIGHT_FOR_ML,
            "weight_reason": None,
            "raw_weight": ML_WEIGHT_FOR_ML,
        }

    from src.ml import runtime as rt

    # 'custom' UND 'classic': off. Beide betreten den ML-Zweig nicht.
    return {
        "mode": rt.MODE_OFF,
        "mode_reason": None,
        "weight": ML_WEIGHT_DEFAULT_CUSTOM,
        "weight_reason": None,
        "raw_weight": ML_WEIGHT_DEFAULT_CUSTOM,
    }


# ---------------------------------------------------------------------------
# Was tatsaechlich gerechnet wurde
# ---------------------------------------------------------------------------
#
# Die Ergebniszeile der Oberflaeche ("Berechnet mit: ...") darf nicht aus
# der gewaehlten Karte abgeleitet werden, sondern aus der Antwort. Diese
# zwei Funktionen verdichten die vorhandenen Laufzeitdiagnosen zu genau
# dieser Aussage - an einer Stelle, testbar ohne Browser.
#
# Zwei Stufen, bewusst getrennt: Das Basismodell (ML angewandt ja/nein)
# und die zweite Stufe (Ligastaerke). Fehlt nur die Ligakorrektur, ist
# das KEIN ML-Ausfall - die Prognose stammt weiter aus dem Modell.

FALLBACK_NONE = "none"
FALLBACK_PARTIAL = "partial"
FALLBACK_FULL = "full"


def describe_match_approach(options, ml):
    """
    Der tatsaechlich angewandte Ansatz eines Einzelspiels.

    options: geprueftes Ergebnis von parse_options() oder None
    ml:      Laufzeitbefund der ML-Schicht (src/ml/runtime.py) fuer
             diese Partie; diese Funktion ruft die Schicht nicht selbst

    Rueckgabe: {"effective_approach", "ml_fallback",
                "league_stage_applied"}.
    """
    ansatz = (options or {}).get("approach")
    stufe = (ml or {}).get("league_stage") or {}
    if ansatz in (APPROACH_CUSTOM, APPROACH_CLASSIC):
        return {"effective_approach": ansatz,
                "ml_fallback": FALLBACK_NONE,
                "league_stage_applied": None}

    if (ml or {}).get("ml_applied_to_production"):
        return {"effective_approach": APPROACH_ML,
                "ml_fallback": FALLBACK_NONE,
                "league_stage_applied": bool(stufe.get("applied"))}

    # ML war gewuenscht (approach=ml oder Umgebung active) und hat nicht
    # getragen: vollstaendiger Rueckfall auf die klassische Rechnung.
    # Ohne ML-Wunsch (alte Clients, Umgebung off) ist das dagegen der
    # regulaere klassische Weg und kein Rueckfall.
    gewuenscht = ansatz == APPROACH_ML or (ml or {}).get("mode") == "active"
    return {"effective_approach": APPROACH_CLASSIC,
            "ml_fallback": FALLBACK_FULL if gewuenscht else FALLBACK_NONE,
            "league_stage_applied": None}


def describe_season_approach(options, ml_config, fixtures_with_ml,
                             fixtures_total, league_stage_applied):
    """
    Der tatsaechlich angewandte Ansatz einer Ligaphasensimulation.

    Anders als im Einzelspiel kann ML hier TEILWEISE wirken: Die
    Laufzeit entscheidet je Partie. Die Aussage folgt deshalb aus den
    Zaehlungen, nicht aus dem Wunsch.

    Rueckgabe: {"effective_approach", "ml_fallback", "ml_fixtures",
                "fixtures_total", "league_stage_applied"}.
    effective_approach ist None, wenn keine Partie offen war - dann
    wurde nichts simuliert, und es gibt keinen Ansatz zu behaupten.
    """
    ansatz = (options or {}).get("approach")
    ergebnis = {"ml_fixtures": fixtures_with_ml,
                "fixtures_total": fixtures_total,
                "league_stage_applied": league_stage_applied}

    if fixtures_total == 0:
        return dict(ergebnis, effective_approach=None,
                    ml_fallback=FALLBACK_NONE)
    if ansatz in (APPROACH_CUSTOM, APPROACH_CLASSIC):
        return dict(ergebnis, effective_approach=ansatz,
                    ml_fallback=FALLBACK_NONE)

    gewuenscht = (ansatz == APPROACH_ML
                  or (ml_config or {}).get("mode") == "active")
    if not gewuenscht:
        return dict(ergebnis, effective_approach=APPROACH_CLASSIC,
                    ml_fallback=FALLBACK_NONE)
    if fixtures_with_ml >= fixtures_total:
        return dict(ergebnis, effective_approach=APPROACH_ML,
                    ml_fallback=FALLBACK_NONE)
    if fixtures_with_ml == 0:
        return dict(ergebnis, effective_approach=APPROACH_CLASSIC,
                    ml_fallback=FALLBACK_FULL)
    return dict(ergebnis, effective_approach=APPROACH_ML,
                ml_fallback=FALLBACK_PARTIAL)
