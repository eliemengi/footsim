"""
V2-C17-Haertung: Modustrennung zwischen V2-Prognose und eigener
Einschaetzung, bewiesen statt behauptet.

DER BEFUND, DEN DIESE DATEI FESTHAELT
--------------------------------------
Der V2-C17-Abschlussbericht behauptete eine strikte Trennung beider
Modi und "kein Blending". Zugleich blieb 'ml_weight' ein gueltiges
API-Feld, und cl_custom_factors.parse_ml_weight() akzeptierte fuer
approach='custom' jeden Wert zwischen 0,0 und 1,0. Nachgerechnet vor
dieser Haertung:

    approach='custom', keine Angaben
        -> inference.shadow_lambdas() lief TROTZDEM (Spy-Beweis unten,
           TestKeinLoaderInCustomModus). Nur sein Gewicht war 0 und
           damit rechnerisch neutral (faktor ** 0 = 1). 'applied' in
           der Antwort stand auf True.

    approach='custom', ml_weight=0.5, factors={...}
        -> ein ECHTER POST /api/simulate lieferte 200 und ein Lambda
           genau zwischen der individualisierten Baseline und der
           vollen ML-Korrektur - baseline_lambda_home=2.9928,
           final_lambda_home=2.9009 bei einem Testlauf gegen das seit
           V2-C17 aktive Modell. Das war der tatsaechliche, von aussen
           ueber die echte HTTP-Route erreichbare Blend-Kanal, den der
           Bericht ausschloss.

Der Widerspruch bestand also wirklich, nicht nur theoretisch. Diese
Datei haelt die Behebung fest: 'ml_weight' ist kein Requestfeld mehr,
fuer keinen Ansatz (siehe cl_custom_factors.parse_options()). Das
Gewicht ist eine reine Serverkonstante, aus 'approach' abgeleitet
(ML_WEIGHT_FOR_ML bzw. ML_WEIGHT_DEFAULT_CUSTOM), und approach='custom'
laedt seither ueberhaupt kein Modell mehr (ml_config() liefert Modus
'off', nicht 'active' mit Gewicht 0).
"""

import math
import os

import pytest

from src.ml import inference as inf
from src.predict import cl_custom_factors as ccf
from src.predict import cl_match_sim

SEASON = 2025
BAYERN, AJAX = 5, 678


@pytest.fixture(autouse=True)
def _saubere_umgebung():
    """Kein ML aus der Umgebung - C8A/C17 steuern ausschliesslich per Request."""
    alt = dict(os.environ)
    os.environ.pop("FOOTSIM_ML_MODE", None)
    os.environ.pop("FOOTSIM_ML_WEIGHT", None)
    inf.reset_model_cache()
    yield
    os.environ.clear()
    os.environ.update(alt)
    inf.reset_model_cache()


def _sim(options=None, simulations=150, home=BAYERN, away=AJAX):
    return cl_match_sim.simulate_cl_league_phase_match(
        home_team="Heim", away_team="Gast", home_id=home, away_id=away,
        season=SEASON, simulations=simulations, use_seed=True,
        options=options)


# ---------------------------------------------------------------------------
# 1. Die verbindliche Modussemantik (Frage 2 des Auftrags)
# ---------------------------------------------------------------------------

class TestModusSemantikMatrix:
    """
    Genau diese Tabelle muss gelten - nichts dazwischen, nichts daneben.

        ml      ml_weight=1.0  factors=neutral  Modell geladen
        custom  ml_weight=0.0  factors=frei     Modell NICHT geladen
    """

    def test_ml_modus(self):
        o = ccf.parse_options({"approach": "ml"})
        assert o["ml_weight"] == 1.0
        assert o["factors"] == ccf.NEUTRAL_FACTORS
        c = ccf.ml_config(o)
        assert c["mode"] == "active"
        assert c["weight"] == 1.0

    def test_individueller_modus(self):
        o = ccf.parse_options({"approach": "custom",
                               "factors": {"home_strength": 1.2}})
        assert o["ml_weight"] == 0.0
        assert o["factors"]["home_strength"] == 1.2
        c = ccf.ml_config(o)
        assert c["mode"] == "off"
        assert c["weight"] == 0.0

    def test_off_modus_ist_die_abwesenheit_von_approach(self):
        """
        Es gibt kein literales approach='off' im Vertrag - 'off' ist
        die Abwesenheit von 'approach'. ml_config(None) liefert
        deshalb None, und resolve_simulation_lambdas faellt dann auf
        die Umgebungssteuerung zurueck (Standard dort: ebenfalls off).
        """
        assert ccf.parse_options({}) is None
        assert ccf.parse_options({"competition": "cl"}) is None
        assert ccf.ml_config(None) is None

    @pytest.mark.parametrize("zwischenwert", [0.1, 0.25, 0.5, 0.75, 0.99])
    def test_kein_zwischenwert_ist_fuer_irgendeinen_ansatz_erreichbar(
            self, zwischenwert):
        for ansatz in (ccf.APPROACH_ML, ccf.APPROACH_CUSTOM):
            with pytest.raises(ccf.InvalidSimulationRequest):
                ccf.parse_options({"approach": ansatz,
                                   "ml_weight": zwischenwert})


# ---------------------------------------------------------------------------
# 2. Die Manipulationsmatrix (Auftrag Abschnitt 4)
# ---------------------------------------------------------------------------

class TestManipulationsmatrix:

    @pytest.mark.parametrize("payload", [
        {"approach": "ml", "ml_weight": 0.5},
        {"approach": "custom", "ml_weight": 0.5},
        {"approach": "ml", "ml_weight": 0.0},
        {"approach": "custom", "ml_weight": 1.0},
        {"approach": "custom", "ml_weight": -1},
        {"approach": "custom", "ml_weight": 2},
        {"approach": "custom", "ml_weight": "0.5"},
        {"approach": "custom", "ml_weight": None},
        {"approach": "custom", "ml_weight": float("nan")},
        {"approach": "custom", "ml_weight": float("inf")},
        {"approach": "custom", "ml_weight": float("-inf")},
        {"approach": "ml", "factors": {"home_strength": 1.2}},
        {"approach": "custom", "factors": {"attack": 1.2}},
        {"approach": "custom", "factors": {"defence": 1.2}},
        {"approach": "custom", "factors": {"offense": 1.2}},
        {"ml_weight": 0.5},
        {"factors": {"home_strength": 1.2}},
        {"approach": "off", "ml_weight": 0.5},
        {"approach": "shadow"},
        {"approach": "active"},
        {"approach": 1},
        {"approach": True},
    ])
    def test_jeder_manipulationsversuch_wird_abgewiesen(self, payload):
        with pytest.raises(ccf.InvalidSimulationRequest):
            ccf.parse_options(payload)

    def test_approach_ml_mit_nicht_neutralen_faktoren(self):
        with pytest.raises(ccf.InvalidSimulationRequest, match="nicht zulaessig"):
            ccf.parse_options({"approach": "ml",
                               "factors": {"home_strength": 1.3,
                                          "away_strength": 0.7}})

    def test_custom_mit_aktiver_registry_wendet_trotzdem_nichts_an(self):
        """
        Der wichtigste Fall: Ein Modell IST aktiv (siehe C17-
        Freigabe), und trotzdem darf 'custom' es nicht anwenden.
        """
        from src.ml import model_registry as mr

        aktiv, _ = mr.active_entry()
        if aktiv is None:
            pytest.skip("kein aktives Modell in dieser Umgebung")

        r = _sim(ccf.parse_options({"approach": "custom"}))
        assert r["ml"]["applied"] is False
        assert r["ml"]["mode"] == "off"
        assert r["ml"]["model_id"] is None

    def test_fehlendes_approach_plus_ml_weight(self):
        with pytest.raises(ccf.InvalidSimulationRequest, match="approach"):
            ccf.parse_options({"ml_weight": 0.5})

    def test_unbekanntes_approach(self):
        with pytest.raises(ccf.InvalidSimulationRequest, match="Ansatz"):
            ccf.parse_options({"approach": "unsinn"})

    @pytest.mark.parametrize("wert", ["x", 5, [1], True, None])
    def test_ungueltiger_requesttyp_insgesamt(self, wert):
        with pytest.raises(ccf.InvalidSimulationRequest):
            ccf.parse_options(wert)

    def test_duplikate_und_grossgeschriebene_ansaetze_greifen_nicht(self):
        """
        JSON-Objekte kennen keine doppelten Schluessel (der letzte
        gewinnt beim Parsen), und ein Ansatz wird nicht gross-/klein-
        unabhaengig erkannt - 'ML' ist nicht 'ml'.
        """
        for variante in ("ML", "Custom", " ml", "ml "):
            with pytest.raises(ccf.InvalidSimulationRequest):
                ccf.parse_options({"approach": variante})


# ---------------------------------------------------------------------------
# 3. Kein ML-Loader im individuellen Modus (Auftrag Abschnitt 4, Beweis)
# ---------------------------------------------------------------------------

class TestKeinLoaderInCustomModus:

    def test_custom_ruft_shadow_lambdas_kein_einziges_mal_auf(self, monkeypatch):
        aufrufe = []
        monkeypatch.setattr(inf, "shadow_lambdas",
                            lambda *a, **kw: aufrufe.append(1))

        for optionen in (
                ccf.parse_options({"approach": "custom"}),
                ccf.parse_options({"approach": "custom",
                                   "factors": {"home_strength": 1.3,
                                              "away_strength": 0.7,
                                              "home_advantage": 1.5,
                                              "goal_level": 1.25}}),
        ):
            _sim(optionen)

        assert aufrufe == []

    def test_ml_ruft_shadow_lambdas_genau_einmal_je_request_auf(self, monkeypatch):
        aufrufe = []
        orig = inf.shadow_lambdas

        def spy(*a, **kw):
            aufrufe.append(1)
            return orig(*a, **kw)

        monkeypatch.setattr(inf, "shadow_lambdas", spy)
        _sim(ccf.parse_options({"approach": "ml"}))
        assert len(aufrufe) == 1

    def test_ohne_approach_ruft_die_umgebung_das_verhalten_ab(self, monkeypatch):
        """
        Kein 'approach' im Request heisst: die Umgebung entscheidet
        (Standard 'off', siehe runtime.py). Auch hier darf ohne
        ausdrueckliches active kein Loader laufen.
        """
        aufrufe = []
        monkeypatch.setattr(inf, "shadow_lambdas",
                            lambda *a, **kw: aufrufe.append(1))
        _sim(None)
        assert aufrufe == []


# ---------------------------------------------------------------------------
# 4. Kein erreichbarer Blend zwischen Baseline und Modell
# ---------------------------------------------------------------------------

class TestKeinBlendZwischenBaselineUndModell:
    """
    blend.py ist fuer Zwischenwerte gebaut (REFERENCE_WEIGHTS 0.1 .. 0.9)
    - das ist weiterhin richtig und bleibt fuer FOOTSIM_ML_WEIGHT (ein
    Betreiber-Diagnosewert, kein Requestfeld) gueltig. Ueber die API
    darf davon nichts mehr ankommen.
    """

    @pytest.mark.parametrize("factors", [
        None,
        {"home_strength": 1.3},
        {"away_strength": 0.7},
        {"home_advantage": 1.5},
        {"goal_level": 1.25},
        {"home_strength": 1.1, "away_strength": 0.9,
         "home_advantage": 1.2, "goal_level": 1.1},
    ])
    def test_custom_lambda_ist_immer_exakt_die_individualisierte_baseline(
            self, factors):
        r = _sim(ccf.parse_options({"approach": "custom", "factors": factors}
                                   if factors else {"approach": "custom"}))
        assert r["ml"]["final_lambda_home"] == r["ml"]["baseline_lambda_home"]
        assert r["ml"]["final_lambda_away"] == r["ml"]["baseline_lambda_away"]
        assert r["ml"]["applied"] is False

    def test_kein_reference_weight_von_blend_py_ist_ueber_die_api_erreichbar(self):
        """
        Fuer jeden Wert, den blend.REFERENCE_WEIGHTS als gueltiges
        Zwischengewicht fuehrt, muss die Anfrage abgewiesen werden -
        sie darf nie als Requestwert ankommen.
        """
        from src.ml import blend as bl

        for gewicht in bl.REFERENCE_WEIGHTS:
            if gewicht in (0.0, 1.0):
                continue
            with pytest.raises(ccf.InvalidSimulationRequest):
                ccf.parse_options({"approach": "custom", "ml_weight": gewicht})
            with pytest.raises(ccf.InvalidSimulationRequest):
                ccf.parse_options({"approach": "ml", "ml_weight": gewicht})


# ---------------------------------------------------------------------------
# 5. Legacy-Payloads
# ---------------------------------------------------------------------------

class TestLegacyPayloads:

    def test_alte_attack_defence_felder_werden_abgewiesen(self):
        for feld in ("attack", "defence"):
            with pytest.raises(ccf.InvalidSimulationRequest, match="Unbekannte"):
                ccf.parse_options({"approach": "custom",
                                   "factors": {feld: 1.1}})

    def test_ein_gespeicherter_alter_ml_regler_wert_wird_verworfen(self):
        """
        Ein Browsertab mit altem, gecachtem script.js koennte noch
        einen ml_weight-Reglerwert senden. Er wird nicht stillschweigend
        ignoriert (das saehe fuer den Client wie Erfolg aus) und nicht
        angewandt - er wird sichtbar mit 400 abgewiesen.
        """
        with pytest.raises(ccf.InvalidSimulationRequest, match="ml_weight"):
            ccf.parse_options({"approach": "custom", "ml_weight": 0.42,
                               "factors": {"home_strength": 1.1}})

    def test_unbekannte_zusatzfelder_im_request_stoeren_nicht(self):
        """
        Ein voellig unbekanntes Feld (weder factors noch ml_weight)
        ist kein Vertragsbruch - nur die zwei benannten Sonderfelder
        werden geprueft.
        """
        o = ccf.parse_options({"approach": "custom", "irgendwas": 123})
        assert o["approach"] == "custom"
