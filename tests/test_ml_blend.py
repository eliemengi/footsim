"""
Tests fuer die Gewichtung zwischen Baseline und ML-Schatten.

Die Gewichtung hat zwei Zusagen, die jeder Aufrufer glauben koennen
muss: Gewicht 0 ist exakt die Baseline, und die zurueckgegebene
Gleichung lambda = baseline * faktor stimmt immer - auch wenn eine
Grenze gegriffen hat. Beides laesst sich verletzen, ohne dass eine Zahl
unplausibel aussieht.

Deshalb stehen hier Eigenschaftstests ueber eine Reihe von Gewichten
und nicht nur Stichproben an den Endpunkten.
"""

import json
import math
import os

import pytest

from src.ml import blend as bl
from src.ml import cl_evaluate as cle
from src.ml import inference as inf
from src.ml import model as mdl

GEWICHTE = bl.REFERENCE_WEIGHTS


# ---------------------------------------------------------------------------
# Bausteine
# ---------------------------------------------------------------------------

def schatten(basis_home=1.5, basis_away=1.2, faktor_home=1.2,
             faktor_away=0.8, status="shadow_prediction", grund=None):
    """Ein C5-Ergebnis in der Form, die inference.shadow_lambdas liefert."""
    return {
        "status": status,
        "baseline_lambda_home": basis_home,
        "baseline_lambda_away": basis_away,
        "correction_factor_home": faktor_home,
        "correction_factor_away": faktor_away,
        "shadow_lambda_home": (basis_home * faktor_home
                               if isinstance(basis_home, (int, float))
                               and isinstance(faktor_home, (int, float))
                               else None),
        "shadow_lambda_away": (basis_away * faktor_away
                               if isinstance(basis_away, (int, float))
                               and isinstance(faktor_away, (int, float))
                               else None),
        "model_id": "clm-test",
        "candidate": "team_profile_cl",
        "feature_count": 16,
        "fallback_reason": grund,
        "quality": {"confidence": "exploratory"},
        "clamps": {"clamped_home": False, "clamped_away": False},
        "applied_to_production": False,
        "release_stage": "experimental",
        "note": "Testfall",
    }


def _echte_zeilen(anzahl=None):
    pfad = "data/ml/dataset_with_cl_2023-2025.json"
    if not os.path.exists(pfad):
        pytest.skip("CL-Datensatz nicht vorhanden")
    if not os.path.exists(inf.DEFAULT_MODEL_PATH):
        pytest.skip("C4-Modellbundle nicht vorhanden")
    rows = json.load(open(pfad, encoding="utf-8"))["rows"]
    zeilen = cle.cl_rows(rows, 2025)
    return zeilen[:anzahl] if anzahl else zeilen


# ---------------------------------------------------------------------------
# 1. Die Endpunkte
# ---------------------------------------------------------------------------

class TestEndpunkte:

    def test_gewicht_null_ist_exakt_die_baseline(self):
        s = schatten()
        e = bl.blend_shadow_result(s, 0.0)
        assert e["weighted_lambda_home"] == s["baseline_lambda_home"]
        assert e["weighted_lambda_away"] == s["baseline_lambda_away"]
        assert e["weighted_factor_home"] == 1.0
        assert e["weighted_factor_away"] == 1.0

    def test_gewicht_eins_ist_das_volle_schattenergebnis(self):
        s = schatten()
        e = bl.blend_shadow_result(s, 1.0)
        assert e["weighted_lambda_home"] == pytest.approx(
            s["shadow_lambda_home"], abs=1e-12)
        assert e["weighted_factor_home"] == pytest.approx(
            s["correction_factor_home"], abs=1e-12)

    def test_gewicht_null_gilt_fuer_jeden_faktor(self):
        for faktor in (0.5, 0.8, 1.0, 1.3, 2.0):
            e = bl.blend_shadow_result(
                schatten(faktor_home=faktor, faktor_away=faktor), 0.0)
            assert e["weighted_lambda_home"] == 1.5
            assert e["weighted_lambda_away"] == 1.2

    def test_die_haelfte_ist_die_geometrische_mitte(self):
        s = schatten()
        e = bl.blend_shadow_result(s, 0.5)
        for seite in ("home", "away"):
            geo = math.sqrt(s[f"baseline_lambda_{seite}"]
                            * s[f"shadow_lambda_{seite}"])
            assert e[f"weighted_lambda_{seite}"] == pytest.approx(geo,
                                                                  abs=1e-12)

    @pytest.mark.parametrize("gewicht", [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0])
    @pytest.mark.parametrize("faktor", [0.5, 0.8, 1.2, 1.44, 2.0])
    def test_die_ausgefuehrte_formel_ist_die_geometrische(self, gewicht,
                                                          faktor):
        """
        Der ausdrueckliche Nachweis (C0B, Abschnitt 10): Was laeuft, ist

            lambda_blend = lambda_basis * korrekturfaktor ** gewicht

        und NICHT die lineare Interpolation. Beide stimmen nur an den
        Enden ueberein; dazwischen laufen sie auseinander, und genau
        dort haette eine falsche Dokumentation niemand bemerkt.
        """
        s = schatten(faktor_home=faktor, faktor_away=faktor)
        e = bl.blend_shadow_result(s, gewicht)

        for seite in ("home", "away"):
            basis = s[f"baseline_lambda_{seite}"]
            geometrisch = basis * (faktor ** gewicht)
            linear = (1 - gewicht) * basis + gewicht * basis * faktor
            assert e[f"weighted_lambda_{seite}"] == pytest.approx(
                geometrisch, abs=1e-12)
            if 0 < gewicht < 1 and faktor != 1.0:
                assert e[f"weighted_lambda_{seite}"] != pytest.approx(
                    linear, abs=1e-9)

    def test_die_haelfte_ist_nicht_das_arithmetische_mittel(self):
        """
        Die Gegenprobe zur Formelwahl: Eine additive Mischung ergaebe
        einen anderen Wert. Bei Faktor 4 waere sie 2,5 statt 2.
        """
        s = schatten(basis_home=1.0, faktor_home=4.0)
        e = bl.blend_shadow_result(s, 0.5)
        assert e["weighted_lambda_home"] == pytest.approx(2.0, abs=1e-12)
        arithmetisch = 0.5 * 1.0 + 0.5 * 4.0
        assert e["weighted_lambda_home"] != pytest.approx(arithmetisch)


# ---------------------------------------------------------------------------
# 2. Mathematische Eigenschaften
# ---------------------------------------------------------------------------

class TestEigenschaften:

    def test_die_gleichung_stimmt_bei_jedem_gewicht(self):
        """lambda = baseline * faktor - die Zusage, auf die sich alles stuetzt."""
        s = schatten()
        for w in GEWICHTE:
            e = bl.blend_shadow_result(s, w)
            assert e["weighted_lambda_home"] == pytest.approx(
                e["baseline_lambda_home"] * e["weighted_factor_home"],
                abs=1e-12)
            assert e["weighted_lambda_away"] == pytest.approx(
                e["baseline_lambda_away"] * e["weighted_factor_away"],
                abs=1e-12)

    def test_faktor_ueber_eins_steigt_monoton(self):
        s = schatten(faktor_home=1.4, faktor_away=1.4)
        werte = [bl.blend_shadow_result(s, w)["weighted_lambda_home"]
                 for w in GEWICHTE]
        assert werte == sorted(werte)
        assert werte[0] < werte[-1]

    def test_faktor_unter_eins_faellt_monoton(self):
        s = schatten(faktor_home=0.7, faktor_away=0.7)
        werte = [bl.blend_shadow_result(s, w)["weighted_lambda_home"]
                 for w in GEWICHTE]
        assert werte == sorted(werte, reverse=True)
        assert werte[0] > werte[-1]

    def test_faktor_eins_veraendert_nichts(self):
        s = schatten(faktor_home=1.0, faktor_away=1.0)
        for w in GEWICHTE:
            e = bl.blend_shadow_result(s, w)
            assert e["weighted_lambda_home"] == pytest.approx(1.5, abs=1e-12)
            assert e["weighted_lambda_away"] == pytest.approx(1.2, abs=1e-12)

    def test_das_ergebnis_liegt_zwischen_baseline_und_schatten(self):
        for fh, fa in ((1.4, 0.7), (0.6, 1.9), (1.0, 1.0)):
            s = schatten(faktor_home=fh, faktor_away=fa)
            for w in GEWICHTE:
                e = bl.blend_shadow_result(s, w)
                for seite in ("home", "away"):
                    lo = min(s[f"baseline_lambda_{seite}"],
                             s[f"shadow_lambda_{seite}"])
                    hi = max(s[f"baseline_lambda_{seite}"],
                             s[f"shadow_lambda_{seite}"])
                    assert lo - 1e-12 <= e[f"weighted_lambda_{seite}"] \
                        <= hi + 1e-12

    def test_home_und_away_sind_unabhaengig(self):
        """Ein veraenderter Auswaertsfaktor darf die Heimseite nicht bewegen."""
        a = bl.blend_shadow_result(schatten(faktor_away=0.8), 0.5)
        b = bl.blend_shadow_result(schatten(faktor_away=1.9), 0.5)
        assert a["weighted_lambda_home"] == b["weighted_lambda_home"]
        assert a["weighted_lambda_away"] != b["weighted_lambda_away"]

    def test_vertauschte_seiten_ergeben_vertauschte_werte(self):
        gerade = bl.blend_shadow_result(
            schatten(1.5, 1.2, 1.3, 0.9), 0.5)
        getauscht = bl.blend_shadow_result(
            schatten(1.2, 1.5, 0.9, 1.3), 0.5)
        assert gerade["weighted_lambda_home"] == pytest.approx(
            getauscht["weighted_lambda_away"])
        assert gerade["weighted_lambda_away"] == pytest.approx(
            getauscht["weighted_lambda_home"])

    def test_dieselbe_eingabe_ergibt_dasselbe_ergebnis(self):
        s = schatten()
        for w in GEWICHTE:
            assert bl.blend_shadow_result(s, w) == bl.blend_shadow_result(s, w)

    def test_die_eingabe_wird_nicht_veraendert(self):
        s = schatten()
        vorher = json.dumps(s, sort_keys=True)
        for w in GEWICHTE:
            bl.blend_shadow_result(s, w)
        assert json.dumps(s, sort_keys=True) == vorher

    def test_stabil_an_den_gueltigen_grenzen(self):
        for basis in (mdl.LAMBDA_MIN, mdl.LAMBDA_MAX):
            for faktor in (mdl.CORRECTION_MIN, mdl.CORRECTION_MAX):
                s = schatten(basis, basis, faktor, faktor)
                # C5 haette den Schattenwert begrenzt - hier nachgebildet.
                s["shadow_lambda_home"] = min(max(basis * faktor,
                                                  mdl.LAMBDA_MIN),
                                              mdl.LAMBDA_MAX)
                s["shadow_lambda_away"] = s["shadow_lambda_home"]
                for w in GEWICHTE:
                    e = bl.blend_shadow_result(s, w)
                    assert math.isfinite(e["weighted_lambda_home"])
                    assert e["weighted_lambda_home"] > 0

    def test_die_reihe_hat_die_erwarteten_gewichte(self):
        s = schatten()
        reihe = bl.blend_series(s)
        assert [e["ml_weight"] for e in reihe] == list(GEWICHTE)
        assert reihe[0]["weighted_lambda_home"] == s["baseline_lambda_home"]
        assert reihe[-1]["weighted_lambda_home"] == pytest.approx(
            s["shadow_lambda_home"], abs=1e-12)


# ---------------------------------------------------------------------------
# 3. Gewichtspruefung
# ---------------------------------------------------------------------------

class TestGewicht:

    @pytest.mark.parametrize("w", [0.0, 0.001, 0.5, 0.999, 1.0, 0, 1])
    def test_gueltige_gewichte(self, w):
        assert bl.valid_weight(w) is True
        e = bl.blend_shadow_result(schatten(), w)
        assert e["status"] == "weighted_shadow"
        assert e["weight_valid"] is True

    @pytest.mark.parametrize("w", [
        None, True, False, "0.5", "", [0.5], {"w": 0.5},
        float("nan"), float("inf"), float("-inf"),
        -0.0001, -1, 1.0001, 2, 50, 100,
    ])
    def test_ungueltige_gewichte(self, w):
        assert bl.valid_weight(w) is False
        e = bl.blend_shadow_result(schatten(), w)
        assert e["status"] == "fallback"
        assert e["fallback_reason"] == bl.REASON_WEIGHT_INVALID
        assert e["weight_valid"] is False
        assert e["weighted_factor_home"] == 1.0
        assert e["weighted_factor_away"] == 1.0
        assert e["weighted_lambda_home"] == 1.5
        assert e["weighted_lambda_away"] == 1.2

    def test_ein_zu_grosses_gewicht_wird_nicht_still_geklammert(self):
        """
        Der Tippfehler 50 statt 0,5 darf nicht als volle ML-Korrektur
        durchgehen. Er muss auffallen.
        """
        e = bl.blend_shadow_result(schatten(), 50)
        assert e["status"] == "fallback"
        assert e["weighted_lambda_home"] == 1.5
        assert e["ml_weight"] == 50

    def test_das_uebergebene_gewicht_steht_in_der_antwort(self):
        for w in (0.25, 2.5, None):
            assert bl.blend_shadow_result(schatten(), w)["ml_weight"] == w \
                or w is None


# ---------------------------------------------------------------------------
# 4. Fallbacks
# ---------------------------------------------------------------------------

class TestFallbacks:

    def test_ein_c5_fallback_wird_durchgereicht(self):
        s = schatten(status="fallback", grund="model_missing")
        e = bl.blend_shadow_result(s, 1.0)
        assert e["status"] == "fallback"
        assert e["fallback_reason"] == "model_missing"
        assert e["upstream_status"] == "fallback"
        assert e["weighted_factor_home"] == 1.0
        assert e["weighted_lambda_home"] == s["baseline_lambda_home"]

    @pytest.mark.parametrize("grund", list(inf.FALLBACK_REASONS))
    def test_jeder_c5_grund_bleibt_erhalten(self, grund):
        s = schatten(status="fallback", grund=grund)
        assert bl.blend_shadow_result(s, 0.5)["fallback_reason"] == grund

    def test_bei_c5_fallback_wird_niemals_ml_angewandt(self):
        s = schatten(status="fallback", grund="model_missing",
                     faktor_home=2.0, faktor_away=2.0)
        for w in GEWICHTE:
            e = bl.blend_shadow_result(s, w)
            assert e["weighted_factor_home"] == 1.0
            assert e["weighted_lambda_home"] == s["baseline_lambda_home"]

    def test_der_c5_fallback_hat_vorrang_vor_dem_gewicht(self):
        """
        Steht das Ergebnis ohnehin auf der Baseline, ist der
        urspruengliche Grund die nuetzlichere Auskunft. Damit der
        Tippfehler trotzdem sichtbar bleibt, steht weight_valid daneben.
        """
        s = schatten(status="fallback", grund="model_missing")
        e = bl.blend_shadow_result(s, 99)
        assert e["fallback_reason"] == "model_missing"
        assert e["weight_valid"] is False

    @pytest.mark.parametrize("basis", [0, -1.0, float("nan"), float("inf"),
                                       None, "1.5", True])
    def test_ungueltige_baseline(self, basis):
        s = schatten(basis_home=basis)
        e = bl.blend_shadow_result(s, 0.5)
        assert e["status"] == "fallback"
        assert e["fallback_reason"] == bl.REASON_BASELINE_INVALID
        assert e["usable"] is False
        assert e["weighted_factor_home"] == 1.0

    @pytest.mark.parametrize("faktor", [0, -1.0, float("nan"), float("inf"),
                                        None, "1.2", True])
    def test_ungueltiger_korrekturfaktor(self, faktor):
        s = schatten(faktor_home=faktor)
        e = bl.blend_shadow_result(s, 0.5)
        assert e["status"] == "fallback"
        assert e["fallback_reason"] == bl.REASON_FACTOR_INVALID
        assert e["weighted_lambda_home"] == s["baseline_lambda_home"]

    @pytest.mark.parametrize("eingabe", [None, "text", 42, [], {},
                                         {"status": "shadow_prediction"}])
    def test_unbrauchbares_schattenergebnis(self, eingabe):
        e = bl.blend_shadow_result(eingabe, 0.5)
        assert e["status"] == "fallback"
        assert e["fallback_reason"] == bl.REASON_SHADOW_INVALID
        assert e["usable"] is False

    def test_bei_gueltiger_baseline_ist_das_ergebnis_nutzbar(self):
        assert bl.blend_shadow_result(schatten(), 0.5)["usable"] is True

    def test_kein_nan_als_gueltiges_ergebnis(self):
        """NaN darf nie als brauchbarer gewichteter Wert erscheinen."""
        for basis in (float("nan"), float("inf")):
            e = bl.blend_shadow_result(schatten(basis_home=basis), 0.5)
            assert e["usable"] is False
            assert e["status"] == "fallback"

    def test_alle_gruende_sind_stabile_bezeichner(self):
        for grund in bl.BLEND_REASONS:
            assert grund.islower() and " " not in grund
        assert len(set(bl.BLEND_REASONS)) == len(bl.BLEND_REASONS)

    def test_ein_ueberlauf_wird_ohne_ausnahmefaenger_gefangen(self):
        """
        Die Rechnung kommt ohne try/except aus: Nach den Pruefungen
        kann die Potenz nicht fehlschlagen, und der einzige
        verbleibende Zahlenfall - ein Ueberlauf des Produkts bei sehr
        grosser Baseline - endet in inf und wird von der
        Ergebnispruefung gefangen.
        """
        s = schatten(basis_home=1e308, faktor_home=2.0)
        s["shadow_lambda_home"] = float("inf")
        e = bl.blend_shadow_result(s, 1.0)
        assert e["status"] == "fallback"
        assert e["fallback_reason"] == bl.REASON_WEIGHTED_NON_FINITE
        assert e["weighted_lambda_home"] == 1e308

    def test_die_rechnung_hat_keinen_pauschalen_ausnahmefaenger(self):
        """
        Gegenprobe zur Begruendung im Modul: Waere dort ein breiter
        except-Block, koennte er einen Programmierfehler still zu einem
        Fallback machen.
        """
        import inspect

        quelltext = inspect.getsource(bl.blend_shadow_result)
        assert "except Exception" not in quelltext
        assert "except BaseException" not in quelltext


# ---------------------------------------------------------------------------
# 5. Numerik und Clamps
# ---------------------------------------------------------------------------

class TestNumerik:

    def test_die_grenzen_stammen_aus_dem_modellmodul(self):
        e = bl.blend_shadow_result(schatten(), 0.5)
        assert e["clamps"]["lambda_min_allowed"] == mdl.LAMBDA_MIN
        assert e["clamps"]["lambda_max_allowed"] == mdl.LAMBDA_MAX

    def test_bei_gueltiger_baseline_greift_kein_clamp(self):
        for fh, fa in ((mdl.CORRECTION_MIN, mdl.CORRECTION_MAX),
                       (mdl.CORRECTION_MAX, mdl.CORRECTION_MIN)):
            s = schatten(1.5, 1.2, fh, fa)
            for w in GEWICHTE:
                c = bl.blend_shadow_result(s, w)["clamps"]
                assert c["clamped_home"] is False
                assert c["clamped_away"] is False

    def test_eine_baseline_ausserhalb_der_grenzen_wird_begrenzt(self):
        """
        C5 verlangt von der Baseline nur "endlich und groesser null".
        Ein Lambda von 10,0 waere dort zulaessig und hier ausserhalb -
        dann greift das Netz, und die Gleichung muss trotzdem stimmen.
        """
        s = schatten(basis_home=10.0, faktor_home=1.5)
        s["shadow_lambda_home"] = 15.0
        e = bl.blend_shadow_result(s, 0.5)

        assert e["clamps"]["clamped_home"] is True
        assert e["weighted_lambda_home"] == mdl.LAMBDA_MAX
        assert e["weighted_lambda_home"] == pytest.approx(
            e["baseline_lambda_home"] * e["weighted_factor_home"], abs=1e-12)
        assert e["clamps"]["raw_weighted_lambda_home"] > mdl.LAMBDA_MAX

    def test_der_rohwert_bleibt_dokumentiert(self):
        s = schatten(basis_home=10.0, faktor_home=1.5)
        e = bl.blend_shadow_result(s, 1.0)
        assert e["clamps"]["raw_weighted_factor_home"] == pytest.approx(1.5)
        assert e["clamps"]["raw_weighted_lambda_home"] == pytest.approx(15.0)

    def test_die_upstream_clamps_werden_mitgefuehrt(self):
        e = bl.blend_shadow_result(schatten(), 0.5)
        assert e["clamps"]["upstream_clamps"] is not None

    def test_alle_ergebnisse_sind_endlich_und_positiv(self):
        for basis in (0.05, 0.5, 1.5, 5.9):
            for faktor in (0.5, 0.9, 1.0, 1.5, 2.0):
                s = schatten(basis, basis, faktor, faktor)
                s["shadow_lambda_home"] = min(max(basis * faktor,
                                                  mdl.LAMBDA_MIN),
                                              mdl.LAMBDA_MAX)
                s["shadow_lambda_away"] = s["shadow_lambda_home"]
                for w in GEWICHTE:
                    e = bl.blend_shadow_result(s, w)
                    for seite in ("home", "away"):
                        wert = e[f"weighted_lambda_{seite}"]
                        assert math.isfinite(wert) and wert > 0


# ---------------------------------------------------------------------------
# 6. Vertrag und Metadaten
# ---------------------------------------------------------------------------

class TestVertrag:

    ERWARTETE_FELDER = (
        "status", "ml_weight", "weight_valid",
        "baseline_lambda_home", "baseline_lambda_away",
        "correction_factor_home", "correction_factor_away",
        "weighted_factor_home", "weighted_factor_away",
        "weighted_lambda_home", "weighted_lambda_away",
        "full_shadow_lambda_home", "full_shadow_lambda_away",
        "model_id", "candidate", "quality", "fallback_reason",
        "upstream_status", "upstream_fallback_reason", "clamps",
        "usable", "applied_to_production", "release_stage", "note",
    )

    def test_alle_felder_sind_vorhanden(self):
        e = bl.blend_shadow_result(schatten(), 0.5)
        for feld in self.ERWARTETE_FELDER:
            assert feld in e, feld

    def test_die_form_ist_im_fallback_dieselbe(self):
        gut = bl.blend_shadow_result(schatten(), 0.5)
        schlecht = bl.blend_shadow_result(schatten(), 99)
        assert set(gut) == set(schlecht) == set(self.ERWARTETE_FELDER)

    def test_die_metadaten_bleiben_erhalten(self):
        s = schatten()
        e = bl.blend_shadow_result(s, 0.5)
        assert e["model_id"] == s["model_id"]
        assert e["candidate"] == s["candidate"]
        assert e["quality"] == s["quality"]
        assert e["full_shadow_lambda_home"] == s["shadow_lambda_home"]

    @pytest.mark.parametrize("w", [0.0, 0.5, 1.0, 99, None])
    def test_applied_to_production_ist_immer_false(self, w):
        e = bl.blend_shadow_result(schatten(), w)
        assert e["applied_to_production"] is False
        assert "release_stage" in e

    def test_auch_bei_unbrauchbarer_eingabe(self):
        e = bl.blend_shadow_result(None, 0.5)
        assert e["applied_to_production"] is False
        assert "release_stage" in e


# ---------------------------------------------------------------------------
# 7. Integration mit echtem Modell und echten Daten
# ---------------------------------------------------------------------------

class TestIntegration:

    def test_endpunkte_ueber_echte_cl_zeilen(self):
        for zeile in _echte_zeilen():
            s = inf.shadow_lambdas_for_row(zeile)
            assert s["status"] == "shadow_prediction"

            null = bl.blend_shadow_result(s, 0.0)
            eins = bl.blend_shadow_result(s, 1.0)

            assert null["weighted_lambda_home"] == s["baseline_lambda_home"]
            assert null["weighted_lambda_away"] == s["baseline_lambda_away"]
            assert eins["weighted_lambda_home"] == pytest.approx(
                s["shadow_lambda_home"], abs=1e-12)
            assert eins["weighted_lambda_away"] == pytest.approx(
                s["shadow_lambda_away"], abs=1e-12)

    def test_die_intervalleigenschaft_gilt_auf_echten_daten(self):
        for zeile in _echte_zeilen(40):
            s = inf.shadow_lambdas_for_row(zeile)
            for e in bl.blend_series(s):
                for seite in ("home", "away"):
                    lo = min(s[f"baseline_lambda_{seite}"],
                             s[f"shadow_lambda_{seite}"])
                    hi = max(s[f"baseline_lambda_{seite}"],
                             s[f"shadow_lambda_{seite}"])
                    assert lo - 1e-12 <= e[f"weighted_lambda_{seite}"] \
                        <= hi + 1e-12

    def test_auf_echten_daten_greift_nie_ein_clamp(self):
        geklammert = 0
        for zeile in _echte_zeilen(40):
            s = inf.shadow_lambdas_for_row(zeile)
            for e in bl.blend_series(s):
                if e["clamps"]["clamped_home"] or e["clamps"]["clamped_away"]:
                    geklammert += 1
        assert geklammert == 0

    def test_die_gleichung_gilt_auf_echten_daten(self):
        for zeile in _echte_zeilen(40):
            s = inf.shadow_lambdas_for_row(zeile)
            for e in bl.blend_series(s):
                assert e["weighted_lambda_home"] == pytest.approx(
                    e["baseline_lambda_home"] * e["weighted_factor_home"],
                    abs=1e-12)

    def test_das_c5_ergebnis_wird_nicht_veraendert(self):
        zeile = _echte_zeilen(1)[0]
        s = inf.shadow_lambdas_for_row(zeile)
        vorher = json.dumps(s, sort_keys=True, default=str)
        bl.blend_series(s)
        assert json.dumps(s, sort_keys=True, default=str) == vorher

    def test_reproduzierbar_ueber_echte_daten(self):
        zeile = _echte_zeilen(1)[0]
        s = inf.shadow_lambdas_for_row(zeile)
        assert bl.blend_series(s) == bl.blend_series(s)


# ---------------------------------------------------------------------------
# 8. Produktionsgrenze
# ---------------------------------------------------------------------------

class TestKeineProduktion:

    def test_kein_produktivmodul_importiert_die_gewichtung(self):
        """
        Seit C7 wird die Gewichtung produktiv genutzt - aber nur ueber
        src/ml/runtime.py. Ein direkter Import aus einem Simulations-
        oder Routenmodul waere ein zweiter Zugang mit eigener
        Fallbacklogik.
        """
        import pathlib

        wurzel = pathlib.Path(__file__).resolve().parents[1]
        verdaechtig = []
        for pfad in list((wurzel / "src").rglob("*.py")) + [wurzel / "app.py"]:
            if pfad.match("*/ml/*") or pfad.name.startswith("test_"):
                continue
            text = pfad.read_text(encoding="utf-8", errors="ignore")
            if "ml.blend" in text or "from src.ml import blend" in text:
                verdaechtig.append(str(pfad.relative_to(wurzel)))
        assert not verdaechtig, f"Produktivimport gefunden: {verdaechtig}"

    def test_die_oberflaeche_rechnet_die_gewichtung_nicht_selbst(self):
        """
        Seit C8B nennt das Frontend das Feld ml_weight - es baut damit
        den Request, den C8A ohnehin verlangt. Das ist gewollt und war
        der Anlass, diesen Waechter zu schaerfen statt ihn zu loeschen.

        Verboten bleibt, worum es hier von Anfang an ging: eine ZWEITE
        Gewichtungsrechnung im Browser. Die Namen unten gehoeren zum
        Innenleben von blend.py und inference.py; taucht einer davon in
        einer Vorlage oder einem Skript auf, rechnet dort jemand die
        Lambdas nach - und dann gibt es zwei Wahrheiten.
        """
        import pathlib

        wurzel = pathlib.Path(__file__).resolve().parents[1]
        for ordner in ("templates", "static"):
            for pfad in (wurzel / ordner).rglob("*"):
                if not pfad.is_file() or pfad.suffix not in (".html", ".js"):
                    continue
                text = pfad.read_text(encoding="utf-8", errors="ignore")
                for verboten in ("weighted_lambda", "ml.blend",
                                 "blend_shadow_result", "correction_factor",
                                 "lambda_home", "lambda_away"):
                    assert verboten not in text, f"{verboten} in {pfad.name}"

    def test_die_oberflaeche_benutzt_dieselbe_skala_wie_das_modul(self):
        """
        Der Regler zeigt Prozent, der Request traegt 0,0 bis 1,0. Genau
        an dieser Naht entsteht sonst der Fehler, 50 fuer 0,5 zu halten -
        valid_weight(50) ist falsch, und das muss so bleiben.
        """
        import pathlib
        import re

        skript = (pathlib.Path(__file__).resolve().parents[1]
                  / "static" / "script.js").read_text(encoding="utf-8")
        block = skript[skript.index("const CL_FACTOR_CONTROLS = ["):]
        block = block[:block.index("];")]
        zeile = next(z for z in block.splitlines() if "ml_weight" in z)
        unten = int(re.search(r"min:\s*(-?\d+)", zeile).group(1))
        oben = int(re.search(r"max:\s*(-?\d+)", zeile).group(1))
        assert (unten / 100, oben / 100) == (bl.MIN_WEIGHT, bl.MAX_WEIGHT)

    def test_die_gewichtung_kennt_nur_eine_skala(self):
        """
        Kein Prozentwert im Kernmodul. Eine spaetere UI rechnet um -
        zwei Skalen im selben Modul waeren die sichere Art, 50 fuer
        0,5 zu halten.
        """
        assert (bl.MIN_WEIGHT, bl.MAX_WEIGHT) == (0.0, 1.0)
        assert bl.valid_weight(100) is False
        assert bl.valid_weight(50) is False
