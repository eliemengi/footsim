"""
V2-C20: Entscheidende Messung, Kandidat und vollstaendige Paritaet.

Diese Datei haelt fest, was nach der Korrektur des Zeitvertrags gilt:

  - Die entscheidende Messung lief UNTER dem eingefrorenen C20-Vertrag
    und mit unveraenderten Gates.
  - Der Kandidat ist an genau diese Messung gebunden - nicht an die
    fruehere C16-Messung.
  - Evaluation und echter Produktionspfad stimmen auf allen 283
    Standardpartien ueberein.
  - Nichts davon hat die echte Registry beruehrt.

Ausdruecklich KEINE Aussage dieser Datei: dass das Modell unabhaengig
bestaetigt sei. Die 283 Partien sind mehrfach benutzte
Entwicklungsevidenz, kein unangetasteter Holdout.
"""

import json
import os
import tempfile

import pytest

from src.ml import c20_temporal_map as c20
from src.ml import model_registry as mr
from tests import live_registry_state as live

KANDIDAT = "data/ml/models/clm-936ecce472696ccb-ls1c4f4e1d.json"
#: Das zur Zeit von C20 aktive Modell; seine Datei bleibt die
#: Vergleichsgrundlage fuer die Modellparameter.
AKTIV = "data/ml/models/clm-3475c9aacef6fec9-lsa165be9c.json"
AKTIVE_ID = live.PRE_C22_ACTIVE_ID

#: Vorab festgelegt, wie in C18 und C19.
TOLERANZ = 1e-9


def _json(pfad):
    with open(pfad, encoding="utf-8") as datei:
        return json.load(datei)


@pytest.fixture(scope="module")
def evaluation():
    return _json(c20.EVALUATION_PATH)


@pytest.fixture(scope="module")
def kandidat():
    if not os.path.isfile(KANDIDAT):
        pytest.skip("der C20-Kandidat liegt nicht vor")
    return _json(KANDIDAT)


# ---------------------------------------------------------------------------
# 1. Die entscheidende Messung
# ---------------------------------------------------------------------------

class TestEntscheidendeMessung:

    def test_sie_lief_unter_dem_eingefrorenen_vertrag(self, evaluation):
        bindung = evaluation["map_contract"]
        assert bindung["contract_fingerprint"] == c20.contract_fingerprint()
        assert bindung["frozen_before_measurement"] is True
        vertrag = _json(c20.CONTRACT_PATH)
        assert vertrag["contract_fingerprint"] == bindung["contract_fingerprint"]

    def test_die_foldkarten_stammen_aus_dem_vertrag(self, evaluation):
        vertrag = _json(c20.CONTRACT_PATH)
        assert evaluation["map_contract"]["fold_maps"] == vertrag["fold_maps"]

    def test_der_ergebnisfingerabdruck_ist_reproduzierbar(self, evaluation):
        from src.ml import c16_damped_league_strength as c16
        assert c16.result_fingerprint(evaluation) == \
            evaluation["result_fingerprint"]

    def test_die_gates_sind_die_unveraenderten_c16_gates(self, evaluation):
        from src.ml import c16_damped_league_strength as c16
        assert evaluation["contract_fingerprint"] == c16.contract_fingerprint()
        assert set(evaluation["decision"]["conditions"]) == {
            "all_folds_same_direction", "brier_not_worse",
            "calibration_holds", "ci_excludes_zero",
            "context_not_severely_damaged", "no_fold_severely_worse",
            "no_severe_segment_damage", "no_single_fold_carries_all",
            "primary_better", "rps_not_worse", "sample_large_enough"}

    def test_das_urteil_und_seine_werte(self, evaluation):
        urteil = evaluation["decision"]
        assert urteil["verdict"] == "accepted"
        assert urteil["failed_conditions"] == []
        assert urteil["n"] == 283
        assert urteil["delta_log_loss"] == pytest.approx(-0.08755953954685936)

    def test_das_pd_segment_liegt_knapp_unter_der_schadensgrenze(
            self, evaluation):
        """
        Kein Bestehen mit Reserve. Das Heimsegment der spanischen Liga
        liegt 0,00015 unter der unveraenderten Grenze von 0,01. Der Test
        haelt die Knappheit fest, damit sie nicht als komfortabel
        missverstanden wird.
        """
        pd = evaluation["measurement"]["standard"]["segments"][
            "home_origin_league:PD"]
        assert pd["n"] == 36
        assert pd["severely_worse"] is False
        assert 0.0 < pd["delta_log_loss"] < 0.01
        assert 0.01 - pd["delta_log_loss"] < 0.001

    def test_der_kontextbefund_ist_benannt_und_kein_gate(self, evaluation):
        """
        Im Kontextbestand ist away_origin_league:SA schwer verschlechtert.
        Das stand schon in der akzeptierten C16-Messung. Der eingefrorene
        Vertrag prueft Segmente nur im Standardbestand; das Urteil bleibt
        davon unberuehrt, der Befund wird trotzdem ausgewiesen.
        """
        kontext = evaluation["measurement"]["context"]
        assert kontext["distinct_damage"] == ["away_origin_league:SA"]
        alt = _json("data/ml/c16_damped_league_strength_evaluation.json")
        assert alt["measurement"]["context"]["distinct_damage"] == \
            kontext["distinct_damage"]


# ---------------------------------------------------------------------------
# 2. Der Kandidat
# ---------------------------------------------------------------------------

class TestKandidat:

    def test_er_besteht_die_ladevalidierung(self, kandidat):
        from src.ml import c17_bundle_contract as c17
        from src.ml import persist as ps
        geladen, modelle = ps.load_bundle(KANDIDAT)
        assert c17.validate_bundle(geladen) == []
        assert set(modelle) == {"home", "away"}

    def test_er_ist_an_die_c20_messung_gebunden(self, kandidat, evaluation):
        bindung = kandidat["contract_bindings"]
        assert bindung["c16_result_fingerprint"] == \
            evaluation["result_fingerprint"]
        assert bindung["c20_contract_fingerprint"] == \
            c20.contract_fingerprint()

    def test_seine_karte_folgt_dem_c20_vertrag(self, kandidat):
        from src.ml import c19_league_map as c19
        from src.ml import persist as ps
        karte, diagnose = c20.production_map(ps.DEFAULT_TRAINING_SEASONS)
        block = kandidat["league_strength"]
        spur = block["team_leagues_provenance"]
        assert block["team_leagues"] == c19.bundle_map(karte)
        assert spur["contract_fingerprint"] == c20.contract_fingerprint()
        assert spur["upto_season"] == c20.prediction_season(
            ps.DEFAULT_TRAINING_SEASONS)
        assert spur["map_fingerprint"] == diagnose["map_fingerprint"]

    def test_modellparameter_sind_die_des_aktiven_modells(self, kandidat):
        aktiv = _json(AKTIV)
        assert kandidat["models"] == aktiv["models"]
        assert kandidat["features"] == aktiv["features"]
        assert kandidat["alpha"] == aktiv["alpha"]
        for feld in ("gamma", "alpha", "attack", "defence",
                     "factor_bounds", "selection", "trained_on"):
            assert kandidat["league_strength"][feld] == \
                aktiv["league_strength"][feld], feld

    def test_er_ueberschreibt_nichts(self, kandidat):
        assert kandidat["model_id"] != AKTIVE_ID
        assert os.path.isfile(AKTIV)
        assert os.path.isfile(
            "data/ml/models/clm-3475c9aacef6fec9-ls9cb9e0f6.json")


# ---------------------------------------------------------------------------
# 3. Registry: vorbereitet, nicht aktiviert
# ---------------------------------------------------------------------------

class TestRegistryTrockenlauf:
    """
    GEAENDERT IN V2-C22. Der Kandidat ist inzwischen ueber den regulaeren
    Freigabeweg registriert und aktiv. Der Trockenlauf der Registrierung
    laeuft deshalb gegen den Vorzustand - die Registry, gegen die C20
    geprueft hat. Sie liegt als der Vorzustand vor, den der Freigabeweg
    bei `apply` gesichert hat, und ihr Fingerabdruck ist gepinnt.
    """

    def _eintrag(self, kandidat):
        from src.ml import c16_release as rel
        return rel._registry_eintrag(kandidat, KANDIDAT, c20.EVALUATION_PATH)

    def _vorzustand(self, kandidat):
        dokument = mr.load_registry()
        if not any(m["model_id"] == kandidat["model_id"]
                   for m in dokument["models"]):
            return dokument
        from src.ml import c15_release as base
        stand = base.load_snapshot()
        assert stand is not None, "der gesicherte Vorzustand fehlt"
        assert stand["saved_at_registry_fingerprint"] == \
            live.PRE_C22_REGISTRY_FP
        assert mr.registry_fingerprint(stand["registry"]) == \
            live.PRE_C22_REGISTRY_FP
        return stand["registry"]

    def test_die_registrierung_wuerde_durchlaufen(self, kandidat):
        eintrag = self._eintrag(kandidat)
        assert eintrag["bundle_sha256"] == mr.bundle_sha256(KANDIDAT)
        neu = mr.register_candidate(self._vorzustand(kandidat), eintrag)
        assert mr.validate_registry(neu) == []

    def test_ohne_freigabe_wird_nichts_aktiv(self, kandidat):
        neu = mr.register_candidate(self._vorzustand(kandidat),
                                    self._eintrag(kandidat))
        with pytest.raises(mr.RegistryError):
            mr.set_stage(neu, kandidat["model_id"], mr.STAGE_ACTIVE)

    def test_der_kandidat_ist_regulaer_aktiv(self, kandidat):
        """V2-C22: registriert, aktiv, Freigabe an sein Bundle gebunden."""
        assert live.ACTIVE_ID == kandidat["model_id"]
        eintrag, _grund = mr.active_entry()
        assert eintrag["model_id"] == kandidat["model_id"]
        assert eintrag["bundle_sha256"] == mr.bundle_sha256(KANDIDAT)
        assert eintrag["evaluation_artifact"] == c20.EVALUATION_PATH
        ok, grund = mr.verify_approval(eintrag, eintrag["approval"],
                                       mr.STAGE_ACTIVE)
        assert ok, grund
        # Ein zweites Registrieren desselben Modells wird abgewiesen.
        with pytest.raises(mr.RegistryError):
            mr.register_candidate(mr.load_registry(),
                                  self._eintrag(kandidat))

    def test_isoliert_schreiben_und_die_echte_registry_bleibt(self, kandidat):
        """
        GEAENDERT IN V2-C22: Die echte Registry steht im jeweils
        autorisierten Zustand (tests/live_registry_state.py). Dass das
        isolierte Schreiben sie nicht beruehrt, pruefen vorher gleich
        nachher.
        """
        vorher = mr.registry_fingerprint(mr.load_registry())
        neu = mr.register_candidate(self._vorzustand(kandidat),
                                    self._eintrag(kandidat))
        with tempfile.TemporaryDirectory() as tmp:
            ziel = os.path.join(tmp, "registry.json")
            mr.write_registry(neu, pfad=ziel)
            assert mr.registry_fingerprint(_json(ziel)) == \
                mr.registry_fingerprint(neu)
        assert mr.registry_fingerprint(mr.load_registry()) == vorher \
            == live.REGISTRY_FP
        eintrag, _grund = mr.active_entry()
        assert eintrag["model_id"] == live.ACTIVE_ID


# ---------------------------------------------------------------------------
# 4. Vollstaendige Paritaet unter dem C20-Vertrag
# ---------------------------------------------------------------------------

class TestParitaet:

    def test_alle_283_partien_ueber_den_produktionspfad(self, evaluation):
        from src.features import league_strength as ls
        from src.features.pit_profiles import PitProfileRepository
        from src.features.strength_provider import get_cl_team_strengths
        from src.ml import c16_release as rel
        from src.ml import cl_evaluate as ce
        from src.ml import dataset as ds
        from src.ml import evaluate as ev
        from src.ml import feature_groups as fg
        from src.ml import inference as inf
        from src.ml import persist as ps
        from src.predict.cl_match_sim import _resolve_cl_profile

        zeilen, _d = ds.build_dataset(include_cl=True)
        spalten = fg.columns_for(fg.C15_CANDIDATE)
        repository = PitProfileRepository()
        gesamt = angewandt = 0
        max_lambda = max_faktor = 0.0

        for fold in evaluation["measurement"]["standard"]["folds"]:
            definition = {"name": fold["fold"],
                          "train_seasons": fold["train_seasons"],
                          "test_season": fold["test_season"]}
            karte = c20.fold_map(definition)
            upto = c20.fold_upto(definition)
            test = ce.cl_rows(zeilen, fold["test_season"])
            bundle, _diag = rel.build_final_bundle(
                zeilen, karte, evaluation,
                seasons=tuple(fold["train_seasons"]),
                map_upto_season=upto, map_contract=c20)
            block = bundle["league_strength"]
            staerke = ls.LeagueStrength(block["attack"], block["defence"],
                                        gamma=block["gamma"])

            with tempfile.TemporaryDirectory() as tmp:
                pfad = os.path.join(tmp, bundle["model_id"] + ".json")
                with open(pfad, "w", encoding="utf-8") as datei:
                    json.dump(bundle, datei, ensure_ascii=False)
                geladen, modelle = ps.load_bundle(pfad)
                basis, _s = ev.predict_lambdas(geladen["alpha"], modelle,
                                               test, spalten)
                soll, _k = ls.apply_factors(staerke, test, basis, karte)
                inf.reset_model_cache()

                for zeile, (soll_h, soll_a) in zip(test, soll):
                    gesamt += 1
                    quellen = get_cl_team_strengths(
                        season=zeile["season"],
                        cutoff=ds.prediction_cutoff(zeile["date"]),
                        repository=repository)
                    heim, _ = _resolve_cl_profile(quellen, zeile["home_id"],
                                                  None)
                    gast, _ = _resolve_cl_profile(quellen, zeile["away_id"],
                                                  None)
                    assert heim["team_id"] == zeile["home_id"]
                    assert gast["team_id"] == zeile["away_id"]

                    ergebnis = inf.shadow_lambdas(
                        zeile["baseline_lambda_home"],
                        zeile["baseline_lambda_away"],
                        home_profile=heim, away_profile=gast,
                        model_path=pfad)
                    stufe = ergebnis["league_stage"]
                    liga_h = karte.get(zeile["home_id"])
                    liga_a = karte.get(zeile["away_id"])
                    assert stufe["home_league"] == liga_h
                    assert stufe["away_league"] == liga_a
                    assert bool(stufe["applied"]) == bool(liga_h and liga_a)
                    if stufe["applied"]:
                        angewandt += 1
                        f_h, f_a = staerke.factors(liga_h, liga_a)
                        max_faktor = max(
                            max_faktor,
                            abs(stufe["league_factor_home"] - f_h),
                            abs(stufe["league_factor_away"] - f_a))
                    max_lambda = max(
                        max_lambda,
                        abs(ergebnis["shadow_lambda_home"] - soll_h),
                        abs(ergebnis["shadow_lambda_away"] - soll_a))

        assert gesamt == 283
        # Unter C20 kennt jede Foldkarte beide Vereine jeder
        # Standardpartie - die 55 Faelle, die C19 neutral liess, wirken.
        assert angewandt == 283
        assert max_lambda <= TOLERANZ, max_lambda
        assert max_faktor <= TOLERANZ, max_faktor

    def test_das_paritaetsartefakt_nennt_dieselben_zahlen(self):
        artefakt = _json("data/ml/c20_runtime_parity.json")
        assert artefakt["contract_fingerprint"] == c20.contract_fingerprint()
        summe = artefakt["totals"]
        assert summe["matches"] == 283
        assert summe["divergent"] == 0
        assert summe["stage_applied"] == 283
        assert summe["profile_id_ok"] == 283
        assert summe["league_equal"] == 283
        assert artefakt["max_deviation"]["lambda"] <= TOLERANZ
