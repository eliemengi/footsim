"""
Laufzeitschicht fuer das Champions-League-Schattenmodell.

WAS SIE TUT - UND WAS SIE AUSDRUECKLICH NICHT TUT
--------------------------------------------------
Sie laedt das versionierte Bundle aus C4, baut die 16 Merkmale eines
konkreten Spiels aus den vorliegenden Teamprofilen, rechnet die
Korrekturfaktoren und liefert daraus SCHATTEN-Lambdas.

Sie veraendert nichts. Die Baseline-Werte gehen unberuehrt wieder
heraus, jede Rueckgabe traegt applied_to_production = False, und kein
produktiver Pfad importiert dieses Modul. Wer die Schattenwerte
benutzen will, muss das in einem spaeteren Schritt ausdruecklich
entscheiden - C3 hat die Uebertragung auf die Champions League nicht
belegt (INCONCLUSIVE, delta LogLoss -0,00890, Intervall
[-0,02986, +0,01135] ueber 213 Spiele).

DER VERTRAG
-----------
Eine Rueckgabe hat immer dieselbe Form, ob das Modell gerechnet hat
oder nicht:

    status                 shadow_prediction | fallback
    baseline_lambda_*      unveraendert wie hereingegeben
    correction_factor_*    im Fallback exakt 1.0
    shadow_lambda_*        baseline * faktor, im Fallback = baseline
    fallback_reason        None oder ein stabiler Bezeichner
    applied_to_production  immer False

Der Aufrufer muss also keinen Fehlerfall unterscheiden, um sicher
weiterzurechnen. Genau darin liegt der Zweck: Ein fehlendes oder
kaputtes Modell darf die bestehende Simulation nicht beruehren.

WARUM DIE GRUENDE MASCHINENLESBAR SIND
--------------------------------------
fallback_reason kommt aus einer festen Liste, nicht aus einem
Meldungstext. Wer spaeter auswerten will, wie oft welcher Fall
eintritt, braucht einen stabilen Bezeichner; ein deutscher Satz
aendert sich bei der naechsten Umformulierung.

DIE MERKMALE STAMMEN AUS EINER QUELLE
-------------------------------------
dataset.profile_feature_values() bildet Profil auf Spalten ab - fuer
den Trainingsdatensatz und fuer diese Schicht dieselbe Funktion. Die
Reihenfolge kommt aus feature_groups.columns_for(); sie wird gegen die
Liste im Bundle geprueft, bevor gerechnet wird.
"""

import math
import os
import threading

from src.ml import dataset as ds
from src.ml import feature_groups as fg
from src.ml import model as mdl
from src.ml import persist as ps

#: Der Kandidat. Fest - diese Schicht bedient genau das Modell aus C4.
CANDIDATE = "team_profile_cl"

#: Das Standardbundle, repo-relativ aufgeloest.
#:
#: Bewusst ueber __file__ und nicht ueber das Arbeitsverzeichnis: Unter
#: Gunicorn, in Tests und im Cron-Lauf ist das cwd jeweils ein anderes,
#: und ein relativer Pfad zeigte dann irgendwohin.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
#: Der Name traegt seit C0B nicht mehr "shadow": Die Betriebsart steht
#: im Bundle (release_stage), nicht im Dateinamen. Ein Modell auf
#: experimental in einer Datei namens cl_shadow_model waere genau die
#: Sorte Widerspruch, die C0B beseitigt.
DEFAULT_MODEL_PATH = os.path.join(_REPO_ROOT, "data", "ml", "models",
                                  "cl_correction_model_v1.json")

#: Zulaessige Dateiendung. Ein Bundle ist JSON - eine .pkl oder .joblib
#: wird nicht geladen, auch nicht auf ausdruecklichen Wunsch.
ALLOWED_SUFFIX = ".json"

#: Schemata, die auf eine entfernte Quelle deuten. Geladen wird
#: ausschliesslich aus dem lokalen Dateisystem.
REMOTE_MARKERS = ("://", "\\\\")

#: Die Fallbackgruende. Feste Bezeichner, keine Meldungstexte.
REASON_MODEL_MISSING = "model_missing"
REASON_MODEL_INVALID = "model_invalid"
REASON_MODEL_INCOMPATIBLE = "model_incompatible"
REASON_FEATURES_MISSING = "features_missing"
REASON_FEATURES_INVALID = "features_invalid"
REASON_BASELINE_INVALID = "baseline_invalid"
REASON_PREDICTION_NON_FINITE = "prediction_non_finite"
REASON_PREDICTION_ERROR = "prediction_error"
REASON_PROFILE_QUALITY = "profile_quality_insufficient"

FALLBACK_REASONS = (
    REASON_MODEL_MISSING, REASON_MODEL_INVALID, REASON_MODEL_INCOMPATIBLE,
    REASON_FEATURES_MISSING, REASON_FEATURES_INVALID, REASON_BASELINE_INVALID,
    REASON_PREDICTION_NON_FINITE, REASON_PREDICTION_ERROR,
    REASON_PROFILE_QUALITY,
)

#: Toleranz gegenueber der Stapelrechnung.
#:
#: model.predict_factors() bildet eine Matrix ueber viele Zeilen und
#: rechnet ein Matrixprodukt; diese Schicht rechnet eine Zeile. BLAS
#: darf dabei anders aufsummieren, und das Ergebnis unterscheidet sich
#: um bis zu ein ULP. Nachgemessen ueber 213 CL-Zeilen: groesste
#: Abweichung 2,2e-16.
#:
#: Die Grenze steht hier, damit ein Test sie pruefen kann, ohne exakte
#: Gleichheit zu behaupten, die es aus einem guten Grund nicht gibt.
BATCH_EQUIVALENCE_TOLERANCE = 1e-12

#: Profilherkuenfte, bei denen gar nicht erst gerechnet wird.
#:
#: Ein neutral_profile ist kein duennes Profil, sondern gar keines -
#: ein Einheitswert fuer eine unbekannte Mannschaft. C3 hat solche
#: Partien aus der Messung ausgeschlossen; eine Korrektur darauf waere
#: ausserhalb von allem, was je geprueft wurde.
BLOCKING_PROFILE_SOURCES = ("neutral",)

#: Herkuenfte, die C3 unterschiedlich gut abgedeckt hat. Reine
#: Begleitinformation - siehe _qualitaet().
_C3_SUBGROUP_NOTE = (
    "C3 hat nachtraeglich unterschiedliche Teilgruppen gesehen "
    "(beide Seiten domestic_pit -0,02077; mindestens eine Seite "
    "cl_history_pit +0,00201). Das ist eine explorative Beobachtung "
    "an einer im Nachhinein gebildeten Gruppe, KEIN Nachweis."
)


# ---------------------------------------------------------------------------
# Modellzugriff mit Zwischenspeicher
# ---------------------------------------------------------------------------

_CACHE = {}
_CACHE_LOCK = threading.Lock()


def reset_model_cache():
    """Leert den Zwischenspeicher - fuer Tests und nach einem Modellwechsel."""
    with _CACHE_LOCK:
        _CACHE.clear()


def _pruefe_pfad(pfad):
    """
    Ein Pfad muss lokal sein und auf .json enden.

    Kein Netzwerk, keine UNC-Freigabe, keine Binaerserialisierung. Das
    Bundleformat ist JSON und fuehrt beim Laden nichts aus - diese
    Eigenschaft soll nicht durch einen anderen Pfad verlorengehen.
    """
    text = str(pfad)
    for marker in REMOTE_MARKERS:
        if marker in text:
            raise ps.ModelBundleError(
                f"entfernte oder Netzwerkpfade sind nicht zulaessig: {text}",
                ps.KIND_INCOMPATIBLE)
    if not text.lower().endswith(ALLOWED_SUFFIX):
        raise ps.ModelBundleError(
            f"nur {ALLOWED_SUFFIX}-Bundles werden geladen, nicht {text}",
            ps.KIND_INCOMPATIBLE)
    return os.path.abspath(text)


def load_model(pfad=None):
    """
    Laedt das Bundle - hoechstens einmal je Pfad.

    Rueckgabe: (bundle, modelle). Wirft ModelBundleError.

    Auch der FEHLSCHLAG wird zwischengespeichert. Ohne das versuchte
    jede Simulation eines fehlenden Modells erneut die Platte, und ein
    dauerhaft fehlendes Bundle kostete bei jedem Spiel einen
    Dateizugriff.

    Das Schloss umschliesst auch das Laden. Zwei Anfragen koennten sonst
    gleichzeitig lesen; das waere nicht falsch, aber unnoetig. Geladen
    wird ausserdem NIE beim Import - eine fehlende Datei darf den
    Prozessstart nicht beruehren.
    """
    aufgeloest = _pruefe_pfad(pfad or DEFAULT_MODEL_PATH)

    with _CACHE_LOCK:
        if aufgeloest in _CACHE:
            bundle, modelle, fehler = _CACHE[aufgeloest]
            if fehler is not None:
                raise fehler
            return bundle, modelle

        try:
            bundle, modelle = ps.load_bundle(aufgeloest, candidate=CANDIDATE)
        except ps.ModelBundleError as fehler:
            _CACHE[aufgeloest] = (None, None, fehler)
            raise

        _CACHE[aufgeloest] = (bundle, modelle, None)
        return bundle, modelle


# ---------------------------------------------------------------------------
# Merkmale
# ---------------------------------------------------------------------------

def feature_columns():
    """Die 16 Merkmale in festgelegter Reihenfolge."""
    return fg.columns_for(CANDIDATE)


def build_feature_row(home_profile, away_profile):
    """
    Die Merkmalswerte eines Spiels aus beiden Teamprofilen.

    Ueber dataset.profile_feature_values() - dieselbe Abbildung, die
    auch der Trainingsdatensatz benutzt. Es werden ausschliesslich
    Bewertungsfelder gelesen: Angriff, Abwehr, Punkte, Tore,
    Siegquote. Kein matches_used (es steht nicht im Kandidaten), kein
    Ergebnis, kein Wert, der erst nach dem Anpfiff feststeht.
    """
    zeile = {}
    zeile.update(ds.profile_feature_values("home", home_profile or {},
                                           ds.PROFILE_RATING_FELDER))
    zeile.update(ds.profile_feature_values("away", away_profile or {},
                                           ds.PROFILE_RATING_FELDER))
    return zeile


def _pruefe_merkmale(zeile, spalten):
    """
    Rueckgabe: (werte, grund). grund ist None, wenn alles passt.

    Getrennt gemeldet: Ein FEHLENDES Merkmal ist ein anderer Fall als
    ein unbrauchbarer Wert. Das erste heisst, das Profil gibt es nicht
    her; das zweite, dass etwas anderes schiefgelaufen ist.
    """
    werte = []
    for spalte in spalten:
        if spalte not in zeile or zeile[spalte] is None:
            return None, REASON_FEATURES_MISSING
        wert = zeile[spalte]
        if isinstance(wert, bool) or not isinstance(wert, (int, float)):
            return None, REASON_FEATURES_INVALID
        if not math.isfinite(wert):
            return None, REASON_FEATURES_INVALID
        werte.append(float(wert))
    return werte, None


# ---------------------------------------------------------------------------
# Antwortbau
# ---------------------------------------------------------------------------

def _antwort(status, basis_home, basis_away, faktor_home, faktor_away,
             lambda_home, lambda_away, grund=None, bundle=None,
             qualitaet=None, clamps=None):
    return {
        "status": status,
        "baseline_lambda_home": basis_home,
        "baseline_lambda_away": basis_away,
        "correction_factor_home": faktor_home,
        "correction_factor_away": faktor_away,
        "shadow_lambda_home": lambda_home,
        "shadow_lambda_away": lambda_away,
        "model_id": (bundle or {}).get("model_id"),
        "candidate": CANDIDATE,
        "feature_count": len(feature_columns()),
        "fallback_reason": grund,
        "quality": qualitaet or {},
        "clamps": clamps,
        "applied_to_production": False,
        # Die Freigabestufe des geladenen Bundles (C0B). Diese Schicht
        # rechnet nur; ob die Stufe eine Anwendung deckt, entscheidet
        # runtime.py. Ohne Bundle steht hier None - dann gab es nichts
        # anzuwenden.
        "release_stage": (bundle or {}).get("release_stage"),
        "note": "Berechneter Korrekturwert. Ob er ein Nutzerergebnis "
                "veraendert, entscheidet die Betriebsart zusammen mit "
                "der Freigabestufe.",
    }


def _fallback(grund, basis_home, basis_away, qualitaet=None, bundle=None):
    """
    Der sichere Rueckfall: Faktor 1.0, Lambda = Baseline.

    Die Baseline-Werte werden durchgereicht, nicht neu berechnet - und
    auch dann, wenn sie selbst der Grund des Rueckfalls sind. Der
    Aufrufer bekommt zurueck, was er hereingegeben hat, und kann ohne
    Fallunterscheidung weiterrechnen.
    """
    return _antwort("fallback", basis_home, basis_away, 1.0, 1.0,
                    basis_home, basis_away, grund, bundle, qualitaet)


def _brauchbares_lambda(wert):
    return (isinstance(wert, (int, float)) and not isinstance(wert, bool)
            and math.isfinite(wert) and wert > 0)


def _qualitaet(home_source, away_source, home_matches, away_matches):
    """
    Herkunft und Tiefe als Begleitinformation.

    Ausdruecklich als exploratory markiert: Die C3-Teilgruppen wurden
    NACH der Messung gebildet. Sie taugen als Hinweis fuer die
    Entscheidung in C6/C7, nicht als Beleg.
    """
    quellen = [s for s in (home_source, away_source) if s]
    return {
        "home_profile_source": home_source,
        "away_profile_source": away_source,
        "home_profile_matches": home_matches,
        "away_profile_matches": away_matches,
        "both_sides_domestic": (bool(quellen) and len(quellen) == 2
                                and set(quellen) == {"domestic_pit"}),
        "confidence": "exploratory",
        "c3_subgroup_note": _C3_SUBGROUP_NOTE,
    }


# ---------------------------------------------------------------------------
# Der oeffentliche Vertrag
# ---------------------------------------------------------------------------

def shadow_lambdas(baseline_lambda_home, baseline_lambda_away,
                   home_profile=None, away_profile=None,
                   home_profile_source=None, away_profile_source=None,
                   home_profile_matches=None, away_profile_matches=None,
                   features=None, model_path=None):
    """
    Schatten-Lambdas fuer EIN Spiel - oder ein sicherer Rueckfall.

    baseline_lambda_*   die bestehenden Werte. Sie werden gelesen,
                        nie veraendert und unveraendert
                        zurueckgegeben.
    *_profile           Teamprofile, aus denen die 16 Merkmale
                        entstehen. Alternativ kann ueber features
                        eine fertige Merkmalszeile uebergeben werden.
    *_profile_source    Herkunft je Seite - entscheidet ueber den
                        Qualitaetsrueckfall und begleitet die Antwort.
    model_path          ausdruecklicher Bundlepfad; ohne Angabe das
                        Standardbundle.

    Diese Funktion wirft nicht. Jeder erwartbare Fehler wird zu einem
    Rueckfall mit Faktor 1.0 - der Aufrufer bekommt in jedem Fall
    brauchbare Werte.
    """
    # 1. Die Baseline zuerst. Ist sie unbrauchbar, gibt es nichts zu
    #    korrigieren, und der Rueckfall kann sie nur durchreichen.
    if not (_brauchbares_lambda(baseline_lambda_home)
            and _brauchbares_lambda(baseline_lambda_away)):
        return _fallback(REASON_BASELINE_INVALID, baseline_lambda_home,
                         baseline_lambda_away)

    qualitaet = _qualitaet(home_profile_source, away_profile_source,
                           home_profile_matches, away_profile_matches)

    # 2. Ein neutrales Profil ist keine duenne Datenbasis, sondern gar
    #    keine. C3 hat solche Partien nicht gemessen.
    if any(q in BLOCKING_PROFILE_SOURCES
           for q in (home_profile_source, away_profile_source) if q):
        return _fallback(REASON_PROFILE_QUALITY, baseline_lambda_home,
                         baseline_lambda_away, qualitaet)

    # 3. Modell holen. Der strenge Loader wirft; hier wird die Art des
    #    Problems in einen Rueckfallgrund uebersetzt.
    try:
        bundle, modelle = load_model(model_path)
    except ps.ModelBundleError as fehler:
        grund = {ps.KIND_MISSING: REASON_MODEL_MISSING,
                 ps.KIND_INCOMPATIBLE: REASON_MODEL_INCOMPATIBLE}.get(
                     getattr(fehler, "kind", None), REASON_MODEL_INVALID)
        return _fallback(grund, baseline_lambda_home, baseline_lambda_away,
                         qualitaet)

    # 4. Die Merkmalsliste des Bundles muss die erwartete sein. Der
    #    Loader prueft das bereits; hier steht die Gegenprobe, weil
    #    diese Schicht die Reihenfolge selbst benutzt.
    spalten = feature_columns()
    if list(bundle.get("features") or []) != spalten:
        return _fallback(REASON_MODEL_INCOMPATIBLE, baseline_lambda_home,
                         baseline_lambda_away, qualitaet, bundle)

    zeile = features if features is not None else build_feature_row(
        home_profile, away_profile)
    werte, grund = _pruefe_merkmale(zeile, spalten)
    if grund is not None:
        return _fallback(grund, baseline_lambda_home, baseline_lambda_away,
                         qualitaet, bundle)

    # 5. Rechnen. Erwartbare Zahlen- und Formfehler werden gefangen;
    #    ein Programmierfehler soll dagegen sichtbar bleiben.
    try:
        faktor_home = float(modelle["home"].predict([werte])[0])
        faktor_away = float(modelle["away"].predict([werte])[0])
    except (ps.ModelBundleError, ValueError, TypeError, IndexError,
            KeyError, ArithmeticError):
        return _fallback(REASON_PREDICTION_ERROR, baseline_lambda_home,
                         baseline_lambda_away, qualitaet, bundle)

    if not (math.isfinite(faktor_home) and math.isfinite(faktor_away)):
        return _fallback(REASON_PREDICTION_NON_FINITE, baseline_lambda_home,
                         baseline_lambda_away, qualitaet, bundle)
    if faktor_home <= 0 or faktor_away <= 0:
        return _fallback(REASON_PREDICTION_NON_FINITE, baseline_lambda_home,
                         baseline_lambda_away, qualitaet, bundle)

    # 6. Begrenzen ueber die BESTEHENDE Funktion, nicht ueber eine
    #    zweite Fassung derselben Regel. apply_correction kennt beide
    #    Grenzen und zaehlt mit, wann sie greifen.
    kunstzeile = {"baseline_lambda_home": float(baseline_lambda_home),
                  "baseline_lambda_away": float(baseline_lambda_away)}
    lambdas, statistik = mdl.apply_correction([kunstzeile], [faktor_home],
                                              [faktor_away])
    lambda_home, lambda_away = lambdas[0]

    if not (_brauchbares_lambda(lambda_home)
            and _brauchbares_lambda(lambda_away)):
        return _fallback(REASON_PREDICTION_NON_FINITE, baseline_lambda_home,
                         baseline_lambda_away, qualitaet, bundle)

    # correction_factor_* ist der TATSAECHLICH angewandte Faktor, nicht
    # der rohe. Nur so gilt fuer jeden Aufrufer ausnahmslos
    #
    #     shadow_lambda = baseline_lambda * correction_factor
    #
    # auch dann, wenn eine Grenze gegriffen hat. Wer den ungeklammerten
    # Wert braucht, findet ihn unter clamps.raw_factor_*.
    effektiv_home = lambda_home / float(baseline_lambda_home)
    effektiv_away = lambda_away / float(baseline_lambda_away)

    clamps = {
        "correction_min": statistik["correction_min"],
        "correction_max": statistik["correction_max"],
        "lambda_min_allowed": statistik["lambda_min_allowed"],
        "lambda_max_allowed": statistik["lambda_max_allowed"],
        "clamped_home": bool(statistik["clamped_home"]),
        "clamped_away": bool(statistik["clamped_away"]),
        "raw_factor_home": faktor_home,
        "raw_factor_away": faktor_away,
    }

    return _antwort("shadow_prediction", baseline_lambda_home,
                    baseline_lambda_away, effektiv_home, effektiv_away,
                    lambda_home, lambda_away, None, bundle, qualitaet,
                    clamps)


def shadow_lambdas_for_row(zeile, model_path=None):
    """
    Bequemlichkeit fuer eine Datensatzzeile.

    Nimmt Baseline, Merkmale und Herkunft aus einer Zeile, wie sie
    cl_dataset erzeugt. Damit laesst sich die Laufzeitschicht gegen
    denselben Bestand pruefen, auf dem C3 gemessen hat - ohne die
    Profile noch einmal aufzuloesen.
    """
    return shadow_lambdas(
        zeile.get("baseline_lambda_home"), zeile.get("baseline_lambda_away"),
        home_profile_source=zeile.get("home_profile_source"),
        away_profile_source=zeile.get("away_profile_source"),
        home_profile_matches=zeile.get("home_profile_matches"),
        away_profile_matches=zeile.get("away_profile_matches"),
        features={s: zeile.get(s) for s in feature_columns()},
        model_path=model_path)
