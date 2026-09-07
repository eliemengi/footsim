"""
Tests der Modellklassenerweiterung (V2-C8).

WAS HIER GEPRUEFT WIRD
Nicht, ob die Erweiterung das Modell verbessert - das ist eine
Messfrage, und die Ablation hat sie beantwortet. Geprueft wird, ob die
Erweiterung TUT, WAS SIE BEHAUPTET: dass eine Transformation ihre
Grenzen nur aus dem Trainingsbestand lernt, dass "nicht anwendbar" zu
einer Null und nicht zu einem Median wird, dass ein Kalibrator lieber
nichts tut als etwas Unsinniges, und dass keiner dieser Wege den
aeusseren Testbestand beruehrt.

Ein Test, der nur die Rueckgabe einer Funktion mit sich selbst
vergleicht, steht hier nicht. Jeder Test macht eine Aussage, die
falsch sein KANN.
"""

import ast
import math
import pathlib

import pytest

from src.ml import c8_ablation as c8
from src.ml import model as mdl
from src.ml import model_class as mc

WURZEL = pathlib.Path(__file__).resolve().parents[1]


# ===========================================================================
# 1  Transformationen
# ===========================================================================

def test_log1p_ist_bei_null_exakt_null():
    """
    Der Grund, log1p und nicht log zu nehmen.

    Ein Verein ohne Zugaenge traegt 0. log(0) ist undefiniert, log1p(0)
    ist exakt 0 - und torlose Fenster sind hier kein Randfall, sondern
    der Regelfall der 120-Tage-Spalten.
    """
    assert mc.apply_transform(0, mc.TRANSFORM_LOG1P) == 0.0
    assert mc.apply_transform(0, mc.TRANSFORM_SIGNED_LOG1P) == 0.0


def test_log1p_ist_streng_monoton():
    """
    Die Eigenschaft, die die ERSETZUNG des Rohwerts rechtfertigt.

    Waere log1p nicht streng monoton, ginge bei der Ersetzung Ordnung
    verloren und man muesste den Rohwert daneben behalten.
    """
    werte = [mc.apply_transform(x, mc.TRANSFORM_LOG1P)
             for x in range(0, 60)]
    assert all(a < b for a, b in zip(werte, werte[1:]))


def test_log1p_staucht_genau_den_oberen_bereich():
    """
    Der fachliche Zweck, nicht bloss die Formel.

    Gemessen wurde ein Medianversatz von 16 auf 32 zwischen Training
    und Test. Roh ist das der Faktor 2; nach log1p muss der Abstand
    deutlich kleiner sein - sonst braeuchte man die Transformation
    nicht.
    """
    roh = 32 / 16
    trans = (mc.apply_transform(32, mc.TRANSFORM_LOG1P)
             / mc.apply_transform(16, mc.TRANSFORM_LOG1P))
    assert trans < roh
    assert trans < 1.3


def test_signed_log1p_erhaelt_das_vorzeichen():
    """
    Nettotransfers laufen von -31 bis +19. Ein blosses log1p waere
    dafuer falsch - und wuerde nach der naechsten Regel abbrechen.
    """
    assert mc.apply_transform(-8, mc.TRANSFORM_SIGNED_LOG1P) < 0
    assert mc.apply_transform(8, mc.TRANSFORM_SIGNED_LOG1P) > 0
    assert (mc.apply_transform(-8, mc.TRANSFORM_SIGNED_LOG1P)
            == pytest.approx(-mc.apply_transform(8,
                                                 mc.TRANSFORM_SIGNED_LOG1P)))


def test_signed_log1p_ist_ueber_den_ganzen_bereich_monoton():
    werte = [mc.apply_transform(x, mc.TRANSFORM_SIGNED_LOG1P)
             for x in range(-31, 20)]
    assert all(a < b for a, b in zip(werte, werte[1:]))


def test_log1p_auf_negativem_wert_bricht_ab():
    """
    Ein negativer Zaehlwert ist ein Datenfehler.

    Ihn auf null zu heben waere eine stille Korrektur: Das Modell
    liefe weiter und niemand erfuehre, dass die Zaehlung kaputt ist.
    """
    with pytest.raises(ValueError, match="negativ"):
        mc.apply_transform(-1, mc.TRANSFORM_LOG1P)


def test_unbekannte_transformation_bricht_ab():
    with pytest.raises(ValueError, match="unbekannte Transformation"):
        mc.apply_transform(1.0, "wurzel")


def test_fehlende_werte_ueberleben_die_transformation():
    """
    Der Transformationsschritt formt, der Imputer fuellt.

    Wuerde hier ein None zu einer Null, waere das eine stille
    Imputation VOR dem Imputer - und mit einem Wert, den niemand
    gewaehlt hat.
    """
    assert mc.apply_transform(None, mc.TRANSFORM_LOG1P) is None
    assert math.isnan(mc.apply_transform(float("nan"), mc.TRANSFORM_LOG1P))


# ===========================================================================
# 2  FeatureTransform - Foldlokalitaet
# ===========================================================================

def test_winsorgrenze_stammt_nur_aus_dem_fit_bestand():
    """
    DER LEAKAGETEST DER TRANSFORMATION.

    Ein Ausreisser, der nur im Testbestand vorkommt, darf die Grenze
    nicht verschieben. Waere es anders, truege die Grenze Information
    ueber den Testbestand - und zwar unbemerkt, weil das Ergebnis
    plausibel aussaehe.
    """
    train = [[float(x)] for x in range(0, 100)]
    transform = mc.FeatureTransform(["a"], {"a": mc.TRANSFORM_IDENTITY},
                                    winsor=("a",))
    transform.fit(train)
    grenze = transform.bounds_["a"]

    transform.transform([[10_000.0]])
    assert transform.bounds_["a"] == grenze


def test_ausreisser_im_test_wird_auf_die_trainingsgrenze_gekappt():
    train = [[float(x)] for x in range(0, 100)]
    transform = mc.FeatureTransform(["a"], {"a": mc.TRANSFORM_IDENTITY},
                                    winsor=("a",))
    transform.fit(train)
    heraus = transform.transform([[10_000.0]])
    assert heraus[0][0] == pytest.approx(transform.bounds_["a"])


def test_winsorisierung_greift_vor_der_transformation():
    """
    Die Reihenfolge ist keine Geschmacksfrage.

    Erst kappen, dann transformieren: log1p(Grenze). Andersherum waere
    die Grenze eine Grenze im Logarithmus und haette keine
    Entsprechung in der Zaehlung.
    """
    train = [[float(x)] for x in range(0, 100)]
    transform = mc.FeatureTransform(["a"], {"a": mc.TRANSFORM_LOG1P},
                                    winsor=("a",))
    transform.fit(train)
    heraus = transform.transform([[10_000.0]])
    assert heraus[0][0] == pytest.approx(math.log1p(transform.bounds_["a"]))


def test_nicht_gelistete_spalten_bleiben_unveraendert():
    """Eine Transformation ohne Eintrag ist die Identitaet."""
    transform = mc.FeatureTransform(["a", "b"], {"a": mc.TRANSFORM_LOG1P})
    heraus = transform.fit_transform([[3.0, 3.0], [7.0, 7.0]])
    assert heraus[0][0] == pytest.approx(math.log1p(3.0))
    assert heraus[0][1] == 3.0


def test_nan_ueberlebt_auch_die_matrixtransformation():
    transform = mc.FeatureTransform(["a"], {"a": mc.TRANSFORM_LOG1P},
                                    winsor=("a",))
    heraus = transform.fit_transform([[1.0], [float("nan")], [3.0]])
    assert math.isnan(heraus[1][0])


def test_transform_rundreise_ueber_dict():
    """
    Bundlefaehigkeit.

    Ohne verlustfreie Serialisierung koennte eine transformierte
    Modellfassung nie gespeichert werden - und Training und Runtime
    liefen auseinander.
    """
    original = mc.FeatureTransform(["a", "b"], {"a": mc.TRANSFORM_LOG1P},
                                   winsor=("a",))
    original.fit([[float(x), 1.0] for x in range(50)])
    kopie = mc.FeatureTransform.from_dict(original.to_dict())

    daten = [[17.0, 2.0], [3.0, 4.0]]
    assert (kopie.transform(daten).tolist()
            == original.transform(daten).tolist())


def test_transform_traegt_die_fassungsnummer():
    """
    Ein Bundle ohne Fassungsnummer laesst sich spaeter nicht als
    veraltet erkennen.
    """
    transform = mc.FeatureTransform(["a"])
    assert transform.to_dict()["model_class_version"] == mc.MODEL_CLASS_VERSION


# ===========================================================================
# 3  Interaktionen - die Kernregel
# ===========================================================================

def test_indikator_null_ergibt_exakt_null_trotz_fehlendem_wert():
    """
    DER ZENTRALE C8-TEST.

    Ein Ligaphasenspiel hat keinen Aggregatstand. In C5 wurde daraus
    ein Medianwert - also eine erfundene Zahl fuer 85 Prozent der
    Zeilen. Hier wird daraus eine Null: eine bekannte Tatsache.
    """
    assert mc.interaction_value(None, 0) == 0.0
    assert mc.interaction_value(float("nan"), 0) == 0.0
    assert mc.interaction_value(float("nan"), 0.0) == 0.0


def test_indikator_eins_und_fehlender_wert_bleibt_fehlend():
    """
    Die Gegenprobe, und sie ist genauso wichtig.

    Ein Rueckspiel OHNE auffindbaren Aggregatstand ist ein echter
    Fehlwert - dafuer ist der Imputer da. Hier eine Null zu setzen
    hiesse, einen Gleichstand zu behaupten.
    """
    assert mc.interaction_value(None, 1) is None
    assert math.isnan(mc.interaction_value(float("nan"), 1))


def test_null_und_fehlend_sind_unterscheidbar():
    """
    Die Anforderung aus V2-C5, hier eingeloest.

    "0" darf nicht zugleich echter Gleichstand und fehlende
    Information heissen. Bei Indikator 1 sind es zwei verschiedene
    Ergebnisse.
    """
    echter_gleichstand = mc.interaction_value(0.0, 1)
    fehlt = mc.interaction_value(None, 1)
    assert echter_gleichstand == 0.0
    assert fehlt is None


def test_interaktion_ist_das_produkt_wenn_beides_da_ist():
    assert mc.interaction_value(3.0, 1) == 3.0
    assert mc.interaction_value(-2.0, 1) == -2.0


def test_fehlender_indikator_bleibt_fehlend():
    """Ohne Zustandsangabe ist auch das Produkt unbekannt."""
    assert mc.interaction_value(3.0, None) is None


def test_jede_interaktion_traegt_eine_begruendung():
    """
    Gegen die Merkmalsexplosion.

    Vier Interaktionen, jede mit einem Satz, warum es sie gibt. Eine
    automatische Kreuzung aller Paare koennte diesen Test nicht
    bestehen - und genau das ist der Zweck.
    """
    for spec in mc.INTERACTION_SPECS:
        assert spec["why"].strip()
        assert len(spec["why"]) > 40, spec["name"]


def test_keine_automatische_paarkreuzung():
    """
    Die Zahl der Interaktionen ist klein und steht fest.

    Bei 213 bis 303 Testpartien waere eine vollstaendige Kreuzung eine
    Uebung im Ueberanpassen.
    """
    assert len(mc.INTERACTION_SPECS) <= 6


def test_jede_interaktion_ersetzt_ihren_rohwert():
    """
    Interaktion UND Rohwert nebeneinander waere ein doppelter
    Freiheitsgrad - und der Rohwert braechte genau die Imputation
    zurueck, die die Interaktion vermeidet.
    """
    for spec in mc.INTERACTION_SPECS:
        assert spec["value"] in mc.INTERACTION_REPLACES, spec["name"]


def test_build_interaction_columns_liefert_je_zeile_einen_wert():
    zeilen = [{"aggregate_diff": 2.0, "is_second_leg": 1},
              {"aggregate_diff": None, "is_second_leg": 0},
              {"aggregate_diff": None, "is_second_leg": 1}]
    spalten = mc.build_interaction_columns(zeilen)
    werte = spalten["x_aggregate_diff_second_leg"]
    assert werte[0] == 2.0
    assert werte[1] == 0.0
    assert werte[2] is None


def test_interaction_variance_erkennt_eine_konstante_interaktion():
    """
    Eine Interaktion ohne Streuung kann nichts erklaeren. Sie zu
    behalten waere nicht falsch, aber der Bericht wuerde ein Merkmal
    auffuehren, das nie gewirkt hat.
    """
    zeilen = [{"aggregate_diff": 1.0, "is_second_leg": 0} for _ in range(10)]
    bericht = mc.interaction_variance(zeilen)
    assert bericht["x_aggregate_diff_second_leg"]["constant"] is True


# ===========================================================================
# 4  Kalibrierung
# ===========================================================================

def _lambdas_und_tore(n, lam, faktor):
    """Ein Bestand, dessen Gesamttore genau faktor mal lam sind."""
    lambdas = [lam] * n
    gesamt = round(lam * faktor * n)
    tore = [1] * gesamt + [0] * (n - gesamt) if gesamt <= n else None
    if tore is None:                      # mehr Tore als Zeilen: verteilen
        tore = [gesamt // n] * n
        for i in range(gesamt % n):
            tore[i] += 1
    return lambdas, tore


def test_multiplikativer_faktor_setzt_die_gesamterwartung_gleich():
    """
    Der Momentenschaetzer, und er braucht keine Iteration.

    Nach der Kalibrierung muss die Summe der Erwartungswerte der Summe
    der Beobachtungen entsprechen - das ist die ganze Behauptung.
    """
    lambdas = [1.5] * 100
    tore = [2] * 100
    kal = mc.fit_calibrator(lambdas, tore, mc.CALIBRATION_MULTIPLICATIVE)
    assert sum(kal.apply(lambdas)) == pytest.approx(sum(tore))


def test_kalibrator_faellt_bei_zu_wenigen_zeilen_zurueck():
    """
    Ein aus zehn Spielen geschaetzter Faktor ist Rauschen mit
    Nachkommastellen. Lieber nichts tun.
    """
    kal = mc.fit_calibrator([1.5] * 10, [2] * 10,
                            mc.CALIBRATION_MULTIPLICATIVE)
    assert kal.mode == mc.CALIBRATION_NONE
    assert "Zeilen" in kal.fallback_reason


def test_kalibrator_faellt_bei_unsinnigem_faktor_zurueck():
    """
    Ein Faktor von 4 hiesse, das Modell laege um das Vierfache daneben.
    Das ist kein Kalibrierungsfall, das ist ein Fehler - und ihn
    stillschweigend wegzurechnen waere das Schlimmste.
    """
    kal = mc.fit_calibrator([0.5] * 100, [2] * 100,
                            mc.CALIBRATION_MULTIPLICATIVE)
    assert kal.mode == mc.CALIBRATION_NONE
    assert "ausserhalb" in kal.fallback_reason


def test_der_rueckfall_nennt_immer_einen_grund():
    """
    Ein stiller Rueckfall waere schlimmer als gar keiner: Das Artefakt
    zeigte "keine Kalibrierung" und niemand wuesste, ob sie nicht
    angefordert oder nicht schaetzbar war.
    """
    kal = mc.fit_calibrator([1.5] * 5, [2] * 5,
                            mc.CALIBRATION_MULTIPLICATIVE)
    assert kal.fallback_reason


def test_kalibrator_none_veraendert_nichts():
    kal = mc.LambdaCalibrator()
    assert kal.apply([1.0, 2.0, 3.0]) == [1.0, 2.0, 3.0]


def test_loglinear_faellt_unter_der_mindestzeilenzahl_auf_den_faktor_zurueck():
    """
    Eine Steigung hat einen Freiheitsgrad mehr als ein Faktor. Unter
    MIN_ROWS_FOR_SLOPE ist sie nicht stabil schaetzbar - der Rueckfall
    geht auf den multiplikativen Fall, nicht auf gar nichts.
    """
    n = mc.MIN_ROWS_FOR_SLOPE - 50
    kal = mc.fit_calibrator([1.5] * n, [2] * n, mc.CALIBRATION_LOGLINEAR)
    assert kal.mode == mc.CALIBRATION_MULTIPLICATIVE
    assert str(mc.MIN_ROWS_FOR_SLOPE) in kal.fallback_reason


def test_kalibrator_rundreise_ueber_dict():
    kal = mc.fit_calibrator([1.5] * 100, [2] * 100,
                            mc.CALIBRATION_MULTIPLICATIVE)
    kopie = mc.LambdaCalibrator.from_dict(kal.to_dict())
    assert kopie.apply([1.5]) == pytest.approx(kal.apply([1.5]))


def test_kalibrator_aus_leerem_dict_ist_neutral():
    """Ein altes Bundle ohne Kalibrierungsblock darf nicht abstuerzen."""
    assert mc.LambdaCalibrator.from_dict(None).mode == mc.CALIBRATION_NONE
    assert mc.LambdaCalibrator.from_dict({}).mode == mc.CALIBRATION_NONE


def test_kalibrierung_laesst_unsinnige_lambdas_unangetastet():
    """
    Ein Lambda von null oder negativ ist bereits ein Fehler. Ihn zu
    skalieren machte ihn nicht besser, sondern nur unauffaelliger.
    """
    kal = mc.LambdaCalibrator(mc.CALIBRATION_MULTIPLICATIVE, factor=1.5)
    assert kal.apply([0.0])[0] == 0.0
    assert kal.apply([-1.0])[0] == -1.0


# ===========================================================================
# 5  Pipeline - ein Codepfad fuer Training und Runtime
# ===========================================================================

def test_ohne_transform_ist_die_pipeline_unveraendert():
    """
    DER REGRESSIONSTEST FUER V1.

    Solange kein Kandidat aufgenommen ist, muss build_pipeline exakt
    dieselbe Schrittfolge liefern wie vor C8 - sonst haette C8 das
    bestehende Modell veraendert, ohne dass es jemand beschlossen hat.
    """
    pipeline = mdl.build_pipeline(1.0)
    assert [name for name, _ in pipeline.steps] == ["imputer", "scaler",
                                                    "regressor"]


def test_mit_transform_steht_dieser_an_erster_stelle():
    """
    Nach dem Imputer traefe die Transformation Medianwerte statt
    Messwerte.
    """
    transform = mc.FeatureTransform(["a"])
    pipeline = mdl.build_pipeline(1.0, transform)
    assert pipeline.steps[0][0] == mdl.TRANSFORM_STEP
    assert [name for name, _ in pipeline.steps][1:] == ["imputer", "scaler",
                                                        "regressor"]


def test_es_gibt_nur_eine_stelle_die_die_schrittfolge_baut():
    """
    Der Auftrag verlangt denselben zentralen Codepfad in Training und
    Runtime. Waere irgendwo eine zweite Pipeline zusammengesetzt,
    koennten die beiden auseinanderlaufen - und es fiele erst in der
    Produktion auf.
    """
    treffer = []
    for pfad in (WURZEL / "src").rglob("*.py"):
        quelle = pfad.read_text(encoding="utf-8")
        baum = ast.parse(quelle)
        for knoten in ast.walk(baum):
            if (isinstance(knoten, ast.Call)
                    and isinstance(knoten.func, ast.Name)
                    and knoten.func.id == "Pipeline"):
                treffer.append(pfad.relative_to(WURZEL).as_posix())
    assert treffer == ["src/ml/model.py"], treffer


def test_der_transformationsschritt_wird_im_fit_der_pipeline_angepasst():
    """
    Ein vorab angepasster Schritt waere genau das Leck, gegen das die
    Pipeline gebaut ist: Die Grenzen kaemen dann aus dem Bestand, auf
    dem jemand fit() zufaellig zuerst gerufen hat.
    """
    import numpy as np

    transform = mc.FeatureTransform(["a"], {"a": mc.TRANSFORM_IDENTITY},
                                    winsor=("a",))
    assert transform.fitted_ is False
    pipeline = mdl.build_pipeline(1.0, transform)
    X = np.array([[float(x)] for x in range(60)])
    y = np.ones(60)
    pipeline.fit(X, y, regressor__sample_weight=np.ones(60))
    assert pipeline.named_steps[mdl.TRANSFORM_STEP].fitted_ is True


# ===========================================================================
# 6  Kandidatenmatrix
# ===========================================================================

def test_jeder_kandidat_traegt_eine_hypothese():
    """
    Eine Variante ohne vorab formulierte Erwartung ist eine Suche, kein
    Versuch.
    """
    for kandidat in c8.candidate_matrix():
        assert len(kandidat["hypothesis"]) > 60, kandidat["name"]


def test_die_kontrolle_ist_der_unveraenderte_v1_kandidat():
    """
    Ohne einen Kontrollarm IM SELBEN LAUF waere jeder Vergleich einer
    gegen eine Zahl aus einem anderen Artefakt - anderer Bestand,
    andere sklearn-Fassung, andere Zufallsfolge.
    """
    from src.ml import feature_groups as fg

    m0 = c8.candidate_matrix()[0]
    assert m0["name"] == "M0_v1_control"
    assert set(m0["columns"]) == set(fg.columns_for(fg.C3_BASE_CANDIDATE))
    assert m0["interactions"] == ()
    assert m0["transform_spec"] == {}
    assert m0["calibration"] == mc.CALIBRATION_NONE


def test_interaktionskandidaten_laufen_unter_dem_kontextvertrag():
    """
    Die C5-Merkmale sind im Standardvertrag konstant - gemessen, in
    Training UND Test. Eine Interaktion darauf waere ebenfalls
    konstant, und der Kandidat maesse nichts.
    """
    for kandidat in c8.candidate_matrix():
        if kandidat["interactions"]:
            assert kandidat["contract"] == c8.CONTRACT_CONTEXT, kandidat["name"]


def test_transformationen_treffen_nur_zaehl_und_nettospalten():
    """
    Die Bewertungsspalten liegen zwischen 6,2 und 7,4 und sind
    praktisch symmetrisch. Sie zu transformieren waere Kosmetik ohne
    Anlass - und ein Freiheitsgrad mehr.
    """
    spec = c8.c7_transform_spec()
    for spalte, art in spec.items():
        if art == mc.TRANSFORM_IDENTITY:
            continue
        assert "rating" not in spalte, spalte


def test_nettospalten_nutzen_die_vorzeichenerhaltende_variante():
    """Nettotransfers werden negativ - ein blosses log1p braeche ab."""
    spec = c8.c7_transform_spec()
    for spalte, art in spec.items():
        if "net_transfers" in spalte:
            assert art == mc.TRANSFORM_SIGNED_LOG1P, spalte


def test_exakte_doppelspalten_sind_ausgeschlossen():
    """
    aggregate_available ist is_second_leg, neutral_venue ist is_final -
    beide mit r = 1,0000 in V2-C5 gemessen. Zwei Spalten fuer dieselbe
    Information sind ein Freiheitsgrad ohne Zugewinn.
    """
    basis = c8.c5_base_columns()
    for doppelt in mc.EXACT_DUPLICATES:
        assert doppelt not in basis


def test_im_bestand_konstante_spalten_sind_ausgeschlossen():
    """
    away_goals_rule_active: 2021 abgeschafft, Bestand ab 2023. Der
    Ausschluss steht mit Begruendung im Code, nicht nur im Bericht.
    """
    basis = c8.c5_base_columns()
    for spalte, grund in c8.CONSTANT_IN_RANGE.items():
        assert spalte not in basis
        assert len(grund) > 30


def test_kontrollarme_sind_als_solche_gekennzeichnet():
    """
    M1r ist V1 plus C7 roh - genau das hat C7 bereits geprueft. Ein
    Kontrollarm darf das Ergebnis erklaeren, aber nicht als C8-Erfolg
    gelten.
    """
    rollen = {k["name"]: k.get("role", "candidate")
              for k in c8.candidate_matrix()}
    assert rollen["M1r_c7_raw_control"] == "control"
    assert rollen["M2r_c5_raw_control"] == "control"
    assert rollen["M1_c7_transformed"] == "candidate"


def test_jede_isolierte_wirkung_hat_ihren_eigenen_kontrollarm():
    """
    Die Zahlen gegen M0 vermengen zwei Dinge: die zusaetzlichen
    Merkmale und deren Behandlung. Erst der Vergleich Arm gegen
    Kontrollarm trennt beides.
    """
    namen = {k["name"] for k in c8.candidate_matrix()}
    for spez in c8.ISOLATED_EFFECTS:
        assert spez["arm"] in namen, spez["effect"]
        assert spez["control"] in namen, spez["effect"]
        assert spez["arm"] != spez["control"]


# ===========================================================================
# 7  Gate
# ===========================================================================

def _ergebnis(delta_ll, kalib, folds, merkmale=20, brier=-0.01, rps=-0.01):
    return {
        "feature_count": merkmale,
        "folds": [{"fold": name, "delta_log_loss": wert}
                  for name, wert in folds],
        "aggregate": {"n": 213, "delta_log_loss": delta_ll,
                      "delta_brier": brier, "delta_rps": rps,
                      "ml": {"calibration_error": kalib}},
    }


def _kontrolle(kalib=0.016, folds=(("a", 0.0), ("b", 0.0))):
    return dict(_ergebnis(0.0, kalib, list(folds), merkmale=16, brier=0.0,
                          rps=0.0), name="M0_v1_control")


def test_ein_besserer_punktschaetzer_allein_genuegt_nicht():
    """
    DIE ENTSCHEIDENDE GATE-EIGENSCHAFT.

    Ein Kandidat mit klar negativem Delta, dessen Intervall die Null
    einschliesst, ist INCONCLUSIVE - nicht ACCEPTED. Genau hier wuerde
    ein zu nachgiebiges Gate Rauschen aufnehmen.
    """
    urteil = c8.check_gate(
        _ergebnis(-0.02, 0.017, [("a", -0.01), ("b", -0.01)]),
        _kontrolle(),
        {"log_loss": {"point": -0.02, "ci_low": -0.05, "ci_high": +0.01}})
    assert urteil["decision"] == c8.DECISION_INCONCLUSIVE


def test_ein_positives_delta_wird_abgelehnt():
    urteil = c8.check_gate(
        _ergebnis(+0.02, 0.017, [("a", +0.01), ("b", +0.01)]),
        _kontrolle(),
        {"log_loss": {"point": +0.02, "ci_low": +0.01, "ci_high": +0.04}})
    assert urteil["decision"] == c8.DECISION_REJECTED


def test_verschlechterte_kalibrierung_verhindert_die_aufnahme():
    """
    Der Befund aus C7, hier als Regel.

    Ein besserer LogLoss bei deutlich schlechterer Kalibrierung heisst:
    Das Modell trifft die Rangfolge besser und die Wahrscheinlichkeiten
    schlechter. Fuer eine Simulation ist das der falsche Tausch.
    """
    urteil = c8.check_gate(
        _ergebnis(-0.02, 0.05, [("a", -0.01), ("b", -0.01)]),
        _kontrolle(kalib=0.016),
        {"log_loss": {"point": -0.02, "ci_low": -0.05, "ci_high": -0.001}})
    assert urteil["conditions"]["calibration_acceptable"] is False
    assert urteil["decision"] != c8.DECISION_ACCEPTED


def test_ein_gewinn_aus_nur_einem_fold_verhindert_die_aufnahme():
    """
    Zwei aeussere Folds sind wenig. Traegt einer den ganzen Gewinn, ist
    es eine Saisoneigenschaft und keine Modelleigenschaft.
    """
    urteil = c8.check_gate(
        _ergebnis(-0.02, 0.017, [("a", -0.0001), ("b", -0.02)]),
        _kontrolle(),
        {"log_loss": {"point": -0.02, "ci_low": -0.05, "ci_high": -0.001}})
    assert urteil["conditions"]["no_single_season_dominance"] is False


def test_nicht_konvergierte_anpassung_wird_abgelehnt():
    """
    Ein nicht konvergiertes Modell hat kein Ergebnis, sondern einen
    Zwischenstand. Ihn zu bewerten waere Scheingenauigkeit.
    """
    ergebnis = _ergebnis(-0.02, 0.017, [("a", -0.01), ("b", -0.01)])
    ergebnis["folds"][0]["fit_diagnostics"] = {
        "home": {"converged": False}, "away": {"converged": True}}
    urteil = c8.check_gate(
        ergebnis, _kontrolle(),
        {"log_loss": {"point": -0.02, "ci_low": -0.05, "ci_high": -0.001}})
    assert urteil["decision"] == c8.DECISION_REJECTED


def test_ein_vollstaendig_bestandenes_gate_ergibt_accepted():
    """
    Die Gegenprobe: Das Gate ist streng, aber nicht unerfuellbar. Ohne
    diesen Test koennte es versehentlich immer ablehnen und niemand
    saehe es.
    """
    urteil = c8.check_gate(
        _ergebnis(-0.02, 0.017, [("a", -0.009), ("b", -0.011)]),
        _kontrolle(),
        {"log_loss": {"point": -0.02, "ci_low": -0.05, "ci_high": -0.001}})
    assert urteil["decision"] == c8.DECISION_ACCEPTED


def test_die_urteile_sind_genau_die_vier_erlaubten():
    erlaubt = {"ACCEPTED", "REJECTED", "INCONCLUSIVE", "NOT_EVALUATED"}
    assert {c8.DECISION_ACCEPTED, c8.DECISION_REJECTED,
            c8.DECISION_INCONCLUSIVE, c8.DECISION_NOT_EVALUATED} == erlaubt


def test_das_gate_nennt_bei_ablehnung_immer_einen_grund():
    urteil = c8.check_gate(
        _ergebnis(+0.02, 0.05, [("a", +0.01), ("b", +0.01)]),
        _kontrolle(),
        {"log_loss": {"point": +0.02, "ci_low": +0.01, "ci_high": +0.04}})
    assert urteil["reasons"]


def test_m5_ist_not_evaluated_und_nicht_negativ_ausgewertet():
    """
    Ein nicht durchgefuehrter Versuch ist kein gescheiterter Versuch.
    Die Begruendung muss im Artefakt stehen, samt Bedingung fuer eine
    spaetere Pruefung.
    """
    assert c8.M5_STATUS["status"] == c8.DECISION_NOT_EVALUATED
    assert len(c8.M5_STATUS["reason"]) > 80
    assert c8.M5_STATUS["would_reevaluate_when"]


# ===========================================================================
# 8  Leakage und Bestandsschutz
# ===========================================================================

def test_kein_baumverfahren_und_kein_neuronales_netz():
    """
    Der Auftrag schliesst sie aus, solange der Plan sie nicht verlangt.
    Bei 213 bis 303 Testpartien waere ein Ensemble aus hunderten
    Baeumen eine Uebung im Auswendiglernen.
    """
    verboten = ("RandomForest", "XGB", "LightGBM", "CatBoost",
                "GradientBoosting", "MLPRegressor", "torch",
                "tensorflow", "keras")
    for modul in ("model_class.py", "c8_ablation.py"):
        quelle = (WURZEL / "src" / "ml" / modul).read_text(encoding="utf-8")
        baum = ast.parse(quelle)
        # Docstrings entfernen: Eine Erwaehnung in der Begruendung ist
        # keine Verwendung.
        for knoten in ast.walk(baum):
            if (isinstance(knoten, (ast.Module, ast.ClassDef,
                                    ast.FunctionDef))
                    and ast.get_docstring(knoten)):
                knoten.body = knoten.body[1:]
        code = ast.unparse(baum)
        for begriff in verboten:
            assert begriff not in code, f"{modul}: {begriff}"


def test_keine_zufaelligen_aufteilungen():
    """
    Ein zufaelliger Split mischt spaetere Spiele ins Training. Das ist
    die haeufigste und unauffaelligste Form von Leakage in
    Zeitreihendaten.
    """
    quelle = (WURZEL / "src" / "ml" / "c8_ablation.py").read_text(
        encoding="utf-8")
    baum = ast.parse(quelle)
    code = ast.unparse(baum)
    for begriff in ("train_test_split", "KFold", "ShuffleSplit",
                    "random_state", "shuffle"):
        assert begriff not in code, begriff


def test_die_kalibrierung_wird_nie_auf_dem_aeusseren_test_gelernt():
    """
    DER LEAKAGETEST DER KALIBRIERUNG.

    fit_calibrator darf in run_fold nur mit den Vorhersagen der
    inneren Validierung gerufen werden. Ein Aufruf mit test_zeilen
    waere ein Modell, das seine eigene Pruefung mitgestaltet.
    """
    quelle = (WURZEL / "src" / "ml" / "c8_ablation.py").read_text(
        encoding="utf-8")
    baum = ast.parse(quelle)
    aufrufe = [k for k in ast.walk(baum)
               if isinstance(k, ast.Call)
               and getattr(k.func, "attr", None) == "fit_calibrator"]
    assert aufrufe, "kein fit_calibrator-Aufruf gefunden"
    for aufruf in aufrufe:
        code = ast.unparse(aufruf)
        assert "val_zeilen" in code, code
        assert "test_zeilen" not in code, code


def test_die_alphawahl_sieht_den_aeusseren_test_nicht():
    """
    Ein auf dem Testbestand gewaehltes Alpha ist eine Anpassung an
    genau die Daten, an denen gemessen wird.
    """
    quelle = (WURZEL / "src" / "ml" / "c8_ablation.py").read_text(
        encoding="utf-8")
    baum = ast.parse(quelle)
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.FunctionDef) and knoten.name == "_select_alpha":
            code = ast.unparse(knoten)
            assert "test_zeilen" not in code
            assert "test_rows" not in code
            break
    else:                                            # pragma: no cover
        pytest.fail("_select_alpha nicht gefunden")


def test_die_guardrails_greifen_nach_der_kalibrierung_erneut():
    """
    Die Kalibrierung koennte ein Lambda aus dem gueltigen Bereich
    schieben. Die Grenzen danach nicht erneut anzuwenden waere die
    einfachste Art, ein unsinniges Lambda in die Verteilung zu
    bekommen.
    """
    quelle = (WURZEL / "src" / "ml" / "c8_ablation.py").read_text(
        encoding="utf-8")
    baum = ast.parse(quelle)
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.FunctionDef) and knoten.name == "run_fold":
            code = ast.unparse(knoten)
            i_kal = code.index("kalibriert_home")
            i_clamp = code.index("LAMBDA_MIN")
            assert i_clamp > i_kal, "Grenzen greifen vor der Kalibrierung"
            break
    else:                                            # pragma: no cover
        pytest.fail("run_fold nicht gefunden")


def test_c8_veraendert_den_datensatzvertrag_nicht():
    """
    Eine Interaktion ist eine Modellentscheidung, kein Datum. Stuende
    sie im Datensatz, waere der C5-Vertrag nachtraeglich veraendert -
    und die C5-Ergebnisse nicht mehr reproduzierbar.
    """
    from src.ml import dataset as ds

    for spec in mc.INTERACTION_SPECS:
        assert spec["name"] not in ds.CONTEXT_FELDER
        assert spec["name"] not in ds.build_schema()


def test_c8_fuegt_keine_modellmerkmale_hinzu():
    """
    Solange kein Kandidat aufgenommen ist, bleibt der Merkmalsvertrag
    unveraendert. Das Modellbundle bleibt damit bitgleich.
    """
    from src.ml import feature_groups as fg

    assert len(fg.columns_for(fg.C3_BASE_CANDIDATE)) == 16


def test_der_ergebnisfingerabdruck_ignoriert_nur_maschinenmessungen():
    """
    Zwei Laeufe liefern nie dieselbe Wanduhrzeit, aber sie muessen
    dieselben Zahlen liefern. Wuerde der Fingerabdruck mehr als die
    Laufzeit ausklammern, waere der Determinismusnachweis wertlos.
    """
    assert c8.NON_DETERMINISTIC_FIELDS == ("runtime_seconds",)
    a = {"x": 1.0, "runtime_seconds": 1.0}
    b = {"x": 1.0, "runtime_seconds": 99.0}
    c = {"x": 2.0, "runtime_seconds": 1.0}
    assert c8.result_fingerprint(a) == c8.result_fingerprint(b)
    assert c8.result_fingerprint(a) != c8.result_fingerprint(c)


def test_ein_fremder_erster_kandidat_bricht_ab():
    """
    Der Kontextkontrollarm entsteht aus dem ERSTEN Kandidaten. Truege
    der fremde Merkmale, waere jeder Kontextvergleich still falsch -
    und das Ergebnis saehe trotzdem plausibel aus.
    """
    matrix = list(c8.candidate_matrix())
    verdreht = [matrix[3]] + matrix
    with pytest.raises(ValueError, match="M0_v1_control"):
        c8.run_c8_ablation([], kandidaten=verdreht)
