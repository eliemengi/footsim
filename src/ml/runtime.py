"""
Kontrollierte Verbindung der ML-Kette mit der echten CL-Simulation.

WAS HIER PASSIERT
-----------------
Die Simulation berechnet ihre Lambdas wie bisher ueber
team_profile.expected_goals(). Diese Schicht bekommt sie, ruft
gegebenenfalls C5 und C6, und gibt zurueck, WELCHE Lambdas die
Simulation tatsaechlich verwenden soll.

Sie ist die einzige Stelle, an der die ML-Kette den produktiven Pfad
beruehrt. Ohne sie muesste jede Route dieselbe Entscheidung selbst
treffen - und drei Kopien derselben Fallbacklogik waeren drei Orte,
an denen sie auseinanderlaufen kann.

DREI BETRIEBSARTEN
------------------
    off      Standard. Die Baseline, sonst nichts. Es wird kein
             Modell geladen und keine ML-Funktion aufgerufen.
    shadow   ML und Gewichtung laufen mit, die Simulation benutzt
             trotzdem die Baseline. Die Diagnose steht in der
             Rueckgabe.
    active   Die Simulation benutzt die gewichteten Lambdas - aber
             nur, wenn alles geklappt hat.

Der Standard ist off, und er bleibt es, solange nichts ausdruecklich
gesetzt wird. C3 hat die Uebertragung auf die Champions League nicht
belegt (INCONCLUSIVE, delta LogLoss -0,00890, Intervall
[-0,02986, +0,01135]). Eine Voreinstellung auf active waere eine
Behauptung, die diese Messung nicht traegt.

DIE ZEITSEMANTIK DER PROFILE
----------------------------
Fuer ein KOMMENDES Spiel ist alles, was der Staerkeprovider kennt,
per Definition Vergangenheit: abgeschlossene Ligasaisons und die
bisher gespielten Partien der laufenden. Es gibt hier also nichts aus
der Zukunft zu verhindern.

Was bleibt, ist ein anderer Unterschied, und der ist bekannt: Der
Provider liefert einen ueber mehrere Saisons GEBLENDETEN Stand,
trainiert wurde auf Point-in-Time-Profilen. Fuer die 16 Merkmale des
CL-Kandidaten wurde nachgemessen, dass sie dabei innerhalb der
Trainingsspanne bleiben - matches_used, das den Bruch verursachte,
gehoert dem Kandidaten nicht an. Der verbleibende Unterschied ist
dokumentiert und nicht wegdefiniert.
"""

import logging
import os

#: Die Betriebsarten.
MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ACTIVE = "active"
MODES = (MODE_OFF, MODE_SHADOW, MODE_ACTIVE)

#: Der Standard. Alles andere muss ausdruecklich gesetzt werden.
DEFAULT_MODE = MODE_OFF

#: Die Umgebungsvariablen.
ENV_MODE = "FOOTSIM_ML_MODE"
ENV_WEIGHT = "FOOTSIM_ML_WEIGHT"

#: Gruende, die diese Schicht selbst vergibt. Gruende aus C5 und C6
#: werden durchgereicht und nicht ueberschrieben.
REASON_MODE_OFF = "mode_off"
REASON_MODE_INVALID = "mode_invalid"
REASON_WEIGHT_MISSING = "weight_missing"
REASON_WEIGHT_INVALID = "weight_invalid"
REASON_SHADOW_ONLY = "shadow_mode"
REASON_BASELINE_INVALID = "baseline_invalid"
REASON_PROFILE_MISSING = "profile_missing"
REASON_UNEXPECTED_ERROR = "unexpected_ml_error"

RUNTIME_REASONS = (REASON_MODE_OFF, REASON_MODE_INVALID,
                   REASON_WEIGHT_MISSING, REASON_WEIGHT_INVALID,
                   REASON_SHADOW_ONLY, REASON_BASELINE_INVALID,
                   REASON_PROFILE_MISSING, REASON_UNEXPECTED_ERROR)

#: Uebersetzung der Laufzeit-Profilherkunft in die Sprache des
#: Datensatzes.
#:
#: Es ist DIESELBE Datenquelle, aber eine andere Zeitsemantik: Der
#: Datensatz baut Profile zum Stichtag, der Laufzeitprovider blendet
#: mehrere Saisons. Die Abbildung sagt "dieselbe Herkunft", nicht
#: "dasselbe Verfahren" - und genau dieser Unterschied ist der
#: bekannte, gemessene Domain-Shift.
RESOLUTION_TO_SOURCE = {
    "domestic_history": "domestic_pit",
    "cl_current_season": "cl_history_pit",
    "neutral": "neutral",
}

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

def parse_mode(wert):
    """
    Die Betriebsart aus einem Rohwert.

    Rueckgabe: (modus, grund). grund ist None, wenn die Angabe gueltig
    war. Ein unbekannter Wert fuehrt auf off - nicht auf active. Wer
    sich vertippt, bekommt die Baseline, nicht das Modell.
    """
    if wert is None or str(wert).strip() == "":
        return DEFAULT_MODE, None

    text = str(wert).strip().lower()
    if text in MODES:
        return text, None
    return DEFAULT_MODE, REASON_MODE_INVALID


def parse_weight(wert):
    """
    Das Gewicht aus einem Rohwert.

    Rueckgabe: (gewicht, grund). Nur 0,0 bis 1,0 sind gueltig; alles
    andere fuehrt auf 0,0 mit einem Grund.

    Ausdruecklich NICHT umgerechnet: Eine 50 wird nicht zu 0,5. Die
    Skala dieses Moduls ist dieselbe wie die von blend.py, und eine
    Prozentangabe gehoert in die Schicht, die sie anzeigt.
    """
    from src.ml import blend as bl

    if wert is None or (isinstance(wert, str) and wert.strip() == ""):
        return 0.0, REASON_WEIGHT_MISSING

    if isinstance(wert, bool):
        return 0.0, REASON_WEIGHT_INVALID

    if isinstance(wert, str):
        try:
            wert = float(wert.strip())
        except ValueError:
            return 0.0, REASON_WEIGHT_INVALID

    if not bl.valid_weight(wert):
        return 0.0, REASON_WEIGHT_INVALID
    return float(wert), None


def current_config(umgebung=None):
    """
    Modus und Gewicht aus der Umgebung.

    umgebung erlaubt es Tests, ohne os.environ zu arbeiten.
    """
    quelle = umgebung if umgebung is not None else os.environ
    modus, modus_grund = parse_mode(quelle.get(ENV_MODE))
    roh = quelle.get(ENV_WEIGHT)

    # In off wird das Gewicht nicht einmal geprueft. Das ist kein
    # Geiz, sondern die Zusage: Der Standardweg beruehrt die ML-Module
    # nicht - auch nicht blend.valid_weight(). Der Rohwert steht
    # trotzdem in der Antwort, damit eine Fehlkonfiguration sichtbar
    # bleibt, sobald jemand den Modus umstellt.
    if modus == MODE_OFF:
        return {"mode": modus, "mode_reason": modus_grund, "weight": 0.0,
                "weight_reason": None, "raw_weight": roh}

    gewicht, gewicht_grund = parse_weight(roh)
    return {
        "mode": modus,
        "mode_reason": modus_grund,
        "weight": gewicht,
        "weight_reason": gewicht_grund,
        "raw_weight": roh,
    }


# ---------------------------------------------------------------------------
# Antwortbau
# ---------------------------------------------------------------------------

def _antwort(lambda_home, lambda_away, basis_home, basis_away, modus,
             angefordert, angewandt, ml_status, grund, model_id,
             ml_produktiv, usable, diagnose=None):
    """
    Der Vertrag - immer dieselbe Form, in jeder Betriebsart.

    lambda_home/away sind die Werte, mit denen die Simulation
    weiterrechnet. In off und shadow sind das ausnahmslos die
    Baselinewerte.
    """
    return {
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "baseline_lambda_home": basis_home,
        "baseline_lambda_away": basis_away,
        "mode": modus,
        "requested_weight": angefordert,
        "applied_weight": angewandt,
        "ml_status": ml_status,
        "fallback_reason": grund,
        "model_id": model_id,
        "ml_applied_to_production": ml_produktiv,
        "usable": usable,
        "diagnostics": diagnose,
    }


def _baseline(basis_home, basis_away, modus, angefordert, grund,
              ml_status="not_run", model_id=None, diagnose=None,
              usable=None):
    """Die Baseline durchreichen - Gewicht 0, ML nicht produktiv."""
    if usable is None:
        usable = _brauchbar(basis_home) and _brauchbar(basis_away)
    return _antwort(basis_home, basis_away, basis_home, basis_away, modus,
                    angefordert, 0.0, ml_status, grund, model_id, False,
                    usable, diagnose)


def _brauchbar(wert):
    import math

    return (isinstance(wert, (int, float)) and not isinstance(wert, bool)
            and math.isfinite(wert) and wert > 0)


def _diagnose(schatten, gewichtet):
    """
    Kompakte technische Diagnose - ohne Nutzerdaten.

    Bewusst nur Zahlen, Zustaende und die Modellkennung. Keine
    Team-IDs, keine Anfrage, keine Pfade. Was hier steht, darf ohne
    weitere Pruefung in ein Log.
    """
    if schatten is None:
        return None
    diagnose = {
        "shadow_status": schatten.get("status"),
        "shadow_fallback_reason": schatten.get("fallback_reason"),
        "correction_factor_home": schatten.get("correction_factor_home"),
        "correction_factor_away": schatten.get("correction_factor_away"),
        "shadow_lambda_home": schatten.get("shadow_lambda_home"),
        "shadow_lambda_away": schatten.get("shadow_lambda_away"),
        "profile_confidence": (schatten.get("quality") or {}).get("confidence"),
    }
    if gewichtet is not None:
        diagnose.update({
            "blend_status": gewichtet.get("status"),
            "blend_fallback_reason": gewichtet.get("fallback_reason"),
            "weighted_factor_home": gewichtet.get("weighted_factor_home"),
            "weighted_factor_away": gewichtet.get("weighted_factor_away"),
            "weighted_lambda_home": gewichtet.get("weighted_lambda_home"),
            "weighted_lambda_away": gewichtet.get("weighted_lambda_away"),
        })
    return diagnose


# ---------------------------------------------------------------------------
# Die Integrationsstelle
# ---------------------------------------------------------------------------

def resolve_simulation_lambdas(baseline_lambda_home, baseline_lambda_away,
                               home_profile=None, away_profile=None,
                               home_resolution=None, away_resolution=None,
                               config=None, environ=None):
    """
    Welche Lambdas soll die Simulation verwenden?

    baseline_lambda_*   die von expected_goals() berechneten Werte.
                        Sie werden gelesen und nie veraendert.
    *_profile           die von _resolve_cl_profile() gelieferten
                        Teamprofile.
    *_resolution        deren Herkunft ("domestic_history",
                        "cl_current_season", "neutral").
    config              vorgefertigte Konfiguration; ohne Angabe aus
                        der Umgebung.

    Diese Funktion wirft nicht. Ein Fehler im ML-Pfad fuehrt auf die
    Baseline, damit die Simulation in jedem Fall ein Ergebnis liefert.
    """
    einstellung = config or current_config(environ)
    modus = einstellung["mode"]
    angefordert = einstellung["weight"]

    # 1. off - der Standard. Hier wird nichts geladen und nichts
    #    gerechnet: kein Import der ML-Module, kein Modellzugriff.
    if modus == MODE_OFF:
        grund = einstellung["mode_reason"] or REASON_MODE_OFF
        return _baseline(baseline_lambda_home, baseline_lambda_away,
                         modus, angefordert, grund)

    # 2. Die Baseline muss brauchbar sein, sonst gibt es nichts zu
    #    korrigieren.
    if not (_brauchbar(baseline_lambda_home)
            and _brauchbar(baseline_lambda_away)):
        return _baseline(baseline_lambda_home, baseline_lambda_away, modus,
                         angefordert, REASON_BASELINE_INVALID, usable=False)

    # 3. Ohne Profile kann C5 keine Merkmale bauen. Nichts erfinden.
    if not home_profile or not away_profile:
        return _baseline(baseline_lambda_home, baseline_lambda_away, modus,
                         angefordert, REASON_PROFILE_MISSING)

    # 4. Ein ungueltiges Gewicht ist in active ein Abbruchgrund. In
    #    shadow laeuft die Diagnose trotzdem - dort wird ohnehin
    #    nichts angewandt.
    gewicht_grund = einstellung["weight_reason"]
    if modus == MODE_ACTIVE and gewicht_grund:
        return _baseline(baseline_lambda_home, baseline_lambda_away, modus,
                         angefordert, gewicht_grund)

    # 5. ML rechnen. Der Import steht hier und nicht oben, damit der
    #    Standardweg off die ML-Module gar nicht erst laedt.
    #
    #    Der breite Ausnahmefaenger ist Absicht und die einzige Stelle
    #    im ML-Zweig, an der einer steht: Dies ist die Grenze zur
    #    produktiven Simulation. Ein Programmierfehler in der ML-Kette
    #    darf einem Nutzer nicht die Champions-League-Prognose
    #    zerstoeren. Er wird geloggt, nicht verschwiegen.
    try:
        from src.ml import blend as bl
        from src.ml import inference as inf

        schatten = inf.shadow_lambdas(
            baseline_lambda_home, baseline_lambda_away,
            home_profile=home_profile, away_profile=away_profile,
            home_profile_source=RESOLUTION_TO_SOURCE.get(home_resolution,
                                                         home_resolution),
            away_profile_source=RESOLUTION_TO_SOURCE.get(away_resolution,
                                                         away_resolution))

        gewicht = 0.0 if gewicht_grund else angefordert
        gewichtet = bl.blend_shadow_result(schatten, gewicht)
    except Exception:                                  # pragma: no cover
        logger.exception("ML-Pfad fehlgeschlagen - Simulation nutzt Baseline")
        return _baseline(baseline_lambda_home, baseline_lambda_away, modus,
                         angefordert, REASON_UNEXPECTED_ERROR)

    diagnose = _diagnose(schatten, gewichtet)
    model_id = schatten.get("model_id")

    # 6. shadow - gerechnet, aber nicht angewandt.
    if modus == MODE_SHADOW:
        return _baseline(baseline_lambda_home, baseline_lambda_away, modus,
                         angefordert, REASON_SHADOW_ONLY,
                         schatten.get("status"), model_id, diagnose)

    # 7. active - anwenden, aber nur wenn beide Stufen getragen haben.
    if (schatten.get("status") != "shadow_prediction"
            or gewichtet.get("status") != "weighted_shadow"
            or not gewichtet.get("usable")):
        grund = (gewichtet.get("fallback_reason")
                 or schatten.get("fallback_reason"))
        return _baseline(baseline_lambda_home, baseline_lambda_away, modus,
                         angefordert, grund, schatten.get("status"),
                         model_id, diagnose)

    lambda_home = gewichtet["weighted_lambda_home"]
    lambda_away = gewichtet["weighted_lambda_away"]
    if not (_brauchbar(lambda_home) and _brauchbar(lambda_away)):
        return _baseline(baseline_lambda_home, baseline_lambda_away, modus,
                         angefordert, REASON_BASELINE_INVALID,
                         schatten.get("status"), model_id, diagnose)

    return _antwort(lambda_home, lambda_away, baseline_lambda_home,
                    baseline_lambda_away, modus, angefordert,
                    gewichtet["ml_weight"], schatten.get("status"), None,
                    model_id, True, True, diagnose)
