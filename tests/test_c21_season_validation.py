"""
V2-C21: Historische Saisonvalidierung.

Die eigentliche Messung (zwei Saisons, acht Stichtage, zwei Modi, drei
Seeds, je 10.000 Simulationen) laeuft rund zwanzig Minuten und wird
nicht in jedem Testlauf wiederholt. Diese Datei prueft stattdessen:

  - dass der Vertrag vor der Messung eingefroren wurde und seither
    unveraendert ist,
  - die Bausteine der Messung einzeln (Stichtage, Plan, Tabelle,
    Metriken, Entscheidung),
  - dass das gespeicherte Ergebnis in sich stimmig ist und sein Urteil
    aus den gespeicherten Messwerten wieder entsteht,
  - dass die isolierte Aktivierung die echte Registry nicht beruehrt.
"""

import json
import os

import pytest

from src.ml import c21_season_validation as c21


ROOT = c21._repo_root()


def _pfad(relativ):
    return os.path.join(ROOT, relativ)


def _json(relativ):
    with open(_pfad(relativ), encoding="utf-8") as datei:
        return json.load(datei)


# ---------------------------------------------------------------------------
# 1. Der Vertrag
# ---------------------------------------------------------------------------

class TestVertrag:

    def test_der_eingefrorene_vertrag_passt_zum_code(self):
        artefakt = _json(c21.CONTRACT_PATH)
        assert artefakt["contract_fingerprint"] == c21.contract_fingerprint()
        assert artefakt["frozen_before_measurement"] is True

    def test_die_grenze_ist_uebernommen_und_nicht_neu_gewaehlt(self):
        from src.ml import cl_evaluate as ce
        schwellen = c21.contract()["thresholds"]
        assert schwellen["noninferiority_margin"] == ce.SEVERE_DEGRADATION
        assert "SEVERE_DEGRADATION" in schwellen["noninferiority_origin"]

    def test_die_mc_grenze_liegt_deutlich_unter_der_gate_grenze(self):
        assert c21.MC_STABILITY_LIMIT <= c21._noninferiority_margin() / 5

    def test_simulationen_und_seeds_sind_fest(self):
        vertrag = c21.contract()["simulation"]
        assert vertrag["simulations"] == 10000
        assert vertrag["seeds"] == [21001, 21002, 21003]

    def test_die_risikodiagnosen_sind_vorab_benannt_aber_kein_gate(self):
        risiko = c21.contract()["risk_diagnostics"]
        assert risiko["gated"] is False
        assert "PD" in " ".join(risiko["pre_registered"])
        assert "SA" in " ".join(risiko["pre_registered"])
        assert "not_equivalent" in risiko

    def test_der_vertrag_nennt_sich_entwicklungsevidenz(self):
        assert "Entwicklungsevidenz" in c21.contract()["evidence_class"]

    def test_die_fuenf_zusaetzlichen_partien_sind_benannt(self):
        text = c21.contract()["population"]["match_evaluation_overlap"]
        assert "283" in text and "fuenf" in text


# ---------------------------------------------------------------------------
# 2. Stichtage und Plan
# ---------------------------------------------------------------------------

class TestStichtage:

    @pytest.mark.parametrize("saison", c21.SEASONS)
    def test_der_saisonstart_liegt_vor_der_ersten_partie(self, saison):
        partien = c21.league_phase(saison)
        name, stichtag = c21.cutoffs(saison)[0]
        assert name == "A_season_start"
        assert stichtag.date().isoformat() == min(p["date"] for p in partien)
        assert stichtag.hour == 12

    @pytest.mark.parametrize("saison", c21.SEASONS)
    def test_die_stichtage_steigen_streng(self, saison):
        zeiten = [c for _n, c in c21.cutoffs(saison)]
        assert zeiten == sorted(zeiten)
        assert len(set(zeiten)) == len(zeiten) == 4

    @pytest.mark.parametrize("saison", c21.SEASONS)
    def test_zum_saisonstart_ist_kein_ergebnis_bekannt(self, saison):
        _n, stichtag = c21.cutoffs(saison)[0]
        plan = c21.plan_at(saison, stichtag)
        assert len(plan["fixtures"]) == 144
        assert plan["finished_matches"] == []
        assert len(plan["remaining_matches"]) == 144
        assert plan["coverage"]["ok"] is True

    @pytest.mark.parametrize("saison", c21.SEASONS)
    def test_bekannt_ist_genau_was_vor_dem_stichtag_lag(self, saison):
        partien = c21.league_phase(saison)
        for name, stichtag in c21.cutoffs(saison)[1:]:
            plan = c21.plan_at(saison, stichtag)
            grenze = stichtag.date().isoformat()
            erwartet = sum(1 for p in partien if p["date"] < grenze)
            assert len(plan["finished_matches"]) == erwartet, name
            assert all(m["utc_date"] < grenze
                       for m in plan["finished_matches"])
            assert all(m["utc_date"] >= grenze
                       for m in plan["remaining_matches"])

    def test_eine_verschobene_partie_bliebe_offen(self, monkeypatch):
        """Entschieden wird nach Datum, nicht nach Spieltag."""
        partien = c21.league_phase(2024)
        verschoben = [dict(p) for p in partien]
        md1 = next(p for p in verschoben if p["matchday"] == 1)
        md1["date"] = "2024-12-01"
        monkeypatch.setattr(c21, "league_phase", lambda s: verschoben)
        _n, stichtag = c21.cutoffs(2024)[1]
        plan = c21.plan_at(2024, stichtag)
        offen = {m["match_id"] for m in plan["remaining_matches"]}
        assert md1["match_id"] in offen


# ---------------------------------------------------------------------------
# 3. Die tatsaechliche Tabelle
# ---------------------------------------------------------------------------

class TestTatsaechlicheTabelle:

    @pytest.mark.parametrize("saison", c21.SEASONS)
    def test_36_vereine_und_vollstaendige_zonen(self, saison):
        tabelle, info = c21.actual_table(saison)
        assert len(tabelle) == 36
        assert sorted(z["position"] for z in tabelle.values()) == list(
            range(1, 37))
        zonen = [z["zone"] for z in tabelle.values()]
        assert (zonen.count(0), zonen.count(1), zonen.count(2)) == (8, 16, 12)
        assert set(info["zone_boundaries"]) == {"8", "24"}

    @pytest.mark.parametrize("saison", c21.SEASONS)
    def test_die_punkte_stimmen_mit_den_ergebnissen(self, saison):
        partien = c21.league_phase(saison)
        tabelle, _info = c21.actual_table(saison)
        punkte = sum(z["points"] for z in tabelle.values())
        erwartet = sum(2 if p["home_goals"] == p["away_goals"] else 3
                       for p in partien)
        assert punkte == erwartet

    @pytest.mark.parametrize("saison", c21.SEASONS)
    def test_die_tabelle_ist_nach_punkten_geordnet(self, saison):
        tabelle, _info = c21.actual_table(saison)
        reihe = sorted(tabelle.values(), key=lambda z: z["position"])
        assert all(a["points"] >= b["points"]
                   for a, b in zip(reihe, reihe[1:]))


# ---------------------------------------------------------------------------
# 4. Metriken und Entscheidung
# ---------------------------------------------------------------------------

class TestMetriken:

    def test_rps_einer_sicheren_richtigen_prognose_ist_null(self):
        assert c21.rps([1.0, 0.0, 0.0], 0) == 0.0
        assert c21.rps([0.0, 0.0, 1.0], 2) == 0.0

    def test_rps_der_sicher_falschen_prognose_am_anderen_ende_ist_eins(self):
        assert c21.rps([1.0, 0.0, 0.0], 2) == pytest.approx(1.0)

    def test_rps_bestraft_die_nachbarzone_milder(self):
        assert c21.rps([0.0, 1.0, 0.0], 0) < c21.rps([0.0, 0.0, 1.0], 0)

    def test_zonenwahrscheinlichkeiten_werden_normiert(self):
        p = c21.zone_probabilities({"direct_pct": 30.1, "playoff_pct": 50.0,
                                    "eliminated_pct": 20.0})
        assert sum(p) == pytest.approx(1.0)

    def test_spearman_bei_identischer_ordnung(self):
        assert c21.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1)
        assert c21.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1)


class TestEntscheidung:

    GUT = {"delta_primary_pooled": -0.01, "delta_primary_by_season":
           {"2024": -0.02, "2025": 0.0}, "delta_updated_pooled": -0.01,
           "delta_brier_top8": 0.0, "delta_brier_top24": 0.0,
           "delta_primary_by_seed": [-0.010, -0.0105, -0.0098],
           "technical_ok": True}

    def test_alles_erfuellt_ist_accepted(self):
        assert c21.decide(dict(self.GUT))["verdict"] == "accepted"

    @pytest.mark.parametrize("feld,wert,gate", [
        ("delta_primary_pooled", 0.01, "S1_primary_noninferior"),
        ("delta_updated_pooled", 0.02, "S3_updated_forecasts_noninferior"),
        ("delta_brier_top8", 0.011, "S4_qualification_not_severely_worse"),
        ("technical_ok", False, "S6_technical_integrity"),
    ])
    def test_jedes_gate_kippt_das_urteil(self, feld, wert, gate):
        auswertung = dict(self.GUT, **{feld: wert})
        urteil = c21.decide(auswertung)
        assert urteil["verdict"] == "rejected"
        assert gate in urteil["failed_conditions"]

    def test_eine_schwer_schlechtere_saison_kippt_das_urteil(self):
        auswertung = dict(self.GUT, delta_primary_by_season={
            "2024": -0.05, "2025": 0.012})
        assert "S2_no_season_severely_worse" in c21.decide(
            auswertung)["failed_conditions"]

    def test_ein_seedabhaengiges_ergebnis_kippt_das_urteil(self):
        auswertung = dict(self.GUT, delta_primary_by_seed=[-0.01, -0.001])
        assert "S5_monte_carlo_stable" in c21.decide(
            auswertung)["failed_conditions"]

    def test_die_grenze_ist_strikt(self):
        """Genau auf der Grenze ist schon schwer verschlechtert."""
        auswertung = dict(self.GUT,
                          delta_primary_pooled=c21._noninferiority_margin())
        assert c21.decide(auswertung)["verdict"] == "rejected"


# ---------------------------------------------------------------------------
# 5. Das gespeicherte Ergebnis
# ---------------------------------------------------------------------------

class TestErgebnis:

    @pytest.fixture(scope="class")
    def ergebnis(self):
        if not os.path.isfile(_pfad(c21.RESULT_PATH)):
            pytest.skip("die C21-Messung liegt nicht vor")
        return _json(c21.RESULT_PATH)

    def test_es_ist_an_den_eingefrorenen_vertrag_gebunden(self, ergebnis):
        assert ergebnis["contract_fingerprint"] == c21.contract_fingerprint()
        assert ergebnis["decision"]["contract_fingerprint"] == \
            c21.contract_fingerprint()

    def test_das_urteil_entsteht_aus_den_gespeicherten_messwerten(
            self, ergebnis):
        gemessen = ergebnis["decision"]["measured"]
        auswertung = {
            "delta_primary_pooled": gemessen["S1"],
            "delta_primary_by_season": gemessen["S2"],
            "delta_updated_pooled": gemessen["S3"],
            "delta_brier_top8": gemessen["S4"]["top8"],
            "delta_brier_top24": gemessen["S4"]["top24"],
            "delta_primary_by_seed": [0.0, gemessen["S5_range"]],
            "technical_ok": not gemessen["S6"],
        }
        neu = c21.decide(auswertung)
        assert neu["verdict"] == ergebnis["decision"]["verdict"]
        assert neu["failed_conditions"] == \
            ergebnis["decision"]["failed_conditions"]

    def test_alle_offenen_partien_wurden_auf_paritaet_geprueft(
            self, ergebnis):
        erwartet = 0
        for saison in c21.SEASONS:
            for _n, stichtag in c21.cutoffs(saison):
                erwartet += len(c21.plan_at(saison, stichtag)[
                    "remaining_matches"])
        assert ergebnis["parity"]["compared"] == erwartet
        assert ergebnis["parity"]["max_abs_diff"] <= c21.PARITY_TOLERANCE

    def test_jede_saison_nutzt_ihr_eigenes_foldmodell(self, ergebnis):
        bindung = ergebnis["binding"]
        assert bindung["2024"]["train_seasons"] == [2023]
        assert bindung["2025"]["train_seasons"] == [2023, 2024]
        assert bindung["2024"]["model_id"] != bindung["2025"]["model_id"]
        for saison in ("2024", "2025"):
            assert bindung[saison]["active_in_isolated_registry"] == \
                bindung[saison]["model_id"]
            assert bindung[saison]["isolated_release_status"] == "applied"
            assert bindung[saison]["map_upto_season"] == int(saison)

    def test_ml_wirkte_in_jedem_v2_lauf_auf_jede_offene_partie(
            self, ergebnis):
        for schluessel, zus in ergebnis["summary"].items():
            modus = schluessel.split("|")[-1]
            ml = zus["ml"]
            if modus == "active":
                assert ml["fixtures_with_ml"] == ml["fixtures_total"]
            else:
                assert ml["fixtures_with_ml"] == 0

    def test_zum_saisonstart_waren_keine_ergebnisse_bekannt(self, ergebnis):
        for saison in c21.SEASONS:
            log = ergebnis["cutoff_log"]["%s A_season_start" % saison]
            assert log["known_results"] == 0
            assert log["simulated"] == 144

    def test_die_risikodiagnosen_sind_ausgewiesen(self, ergebnis):
        risiko = ergebnis["risk_diagnostics"]
        for liga in ("PD", "SA"):
            assert risiko[liga]["team_seasons"] > 0
            assert risiko[liga]["interpretable"] is (
                risiko[liga]["team_seasons"] >= c21._segment_min_size())

    def test_keine_technischen_befunde(self, ergebnis):
        assert ergebnis["technical_findings"] == []


# ---------------------------------------------------------------------------
# 6. Isolation
# ---------------------------------------------------------------------------

class TestIsolation:

    def test_die_isolierte_aktivierung_beruehrt_nichts_echtes(self):
        from src.ml import c20_temporal_map as c20
        from src.ml import inference as inf
        from src.ml import model_registry as mr

        kandidat = _json("data/ml/models/clm-936ecce472696ccb-ls1c4f4e1d.json")
        evaluation = _json(c20.EVALUATION_PATH)
        modelle = _pfad("data/ml/models")
        registry_vorher = mr.registry_fingerprint(mr.load_registry())
        modelle_vorher = sorted(os.listdir(modelle))
        root_vorher = inf._REPO_ROOT

        with c21.isolated_activation(kandidat, evaluation) as iso:
            aktiv, _g = mr.active_entry()
            assert aktiv["model_id"] == kandidat["model_id"]
            assert iso["release"]["status"] == "applied"
            assert inf._REPO_ROOT != root_vorher

        assert inf._REPO_ROOT == root_vorher
        from tests import live_registry_state as live
        eintrag, _g = mr.active_entry()
        assert eintrag["model_id"] == live.ACTIVE_ID
        assert mr.registry_fingerprint(mr.load_registry()) == registry_vorher
        assert sorted(os.listdir(modelle)) == modelle_vorher
