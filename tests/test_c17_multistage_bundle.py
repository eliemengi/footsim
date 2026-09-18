"""
Tests des mehrstufigen Bundlevertrags und der aktiven V2-Runtime
(V2-C17).

WORUM ES GEHT
V2-C16 war statistisch akzeptiert, liess sich aber nicht freigeben:
Der Bundlevertrag aus V2-C0B kannte nur einstufige Modelle und hat das
zweistufige Bundle korrekt fail-closed abgelehnt.

Der schaerfste Teil dieser Tests ist deshalb nicht die Freigabe,
sondern der Nachweis, dass die Erweiterung KEINE Aufweichung ist: Was
nicht namentlich zugelassen wurde, wird weiterhin abgelehnt, und eine
beschaedigte zweite Stufe macht das GANZE Bundle ungueltig.
"""

import copy
import json
import math
import pathlib

import pytest

from src.ml import c16_damped_league_strength as c16
from src.ml import c17_bundle_contract as c17
from src.ml import model_registry as mr
from src.ml import persist as ps

WURZEL = pathlib.Path(__file__).resolve().parents[1]

VERTRAG_FINGERABDRUCK = (
    "03763962fb7171e296d3ecb10addedbb5cb4277a31bcc70131cdf7a1d59cbfd3")


# ===========================================================================
# 1  Der Vertrag
# ===========================================================================

def test_der_vertrag_steht_und_ist_deterministisch():
    vertrag = c17.contract()
    for pflicht in ("schema", "allowed_multistage_candidates",
                    "allowed_evaluation_tasks", "required_bundle_fields",
                    "parameter_bounds", "loader_rules",
                    "allowed_registry_transitions", "release_gates",
                    "fail_closed_cases", "bound_contracts"):
        assert pflicht in vertrag, pflicht
    assert c17.contract_fingerprint() == c17.contract_fingerprint()


def test_der_vertragsfingerabdruck_ist_der_eingefrorene():
    assert c17.contract_fingerprint() == VERTRAG_FINGERABDRUCK


def test_die_vertragsdatei_liegt_vor_und_entstand_vor_dem_bundle():
    pfad = WURZEL / c17.CONTRACT_PATH
    assert pfad.is_file()
    dokument = json.loads(pfad.read_text(encoding="utf-8"))
    assert dokument["frozen_before_bundle"] is True
    assert dokument["contract_fingerprint"] == VERTRAG_FINGERABDRUCK


def test_eine_schemaaenderung_aendert_den_fingerabdruck(monkeypatch):
    vorher = c17.contract_fingerprint()
    monkeypatch.setattr(c17, "MULTISTAGE_SCHEMA_VERSION", 99)
    assert c17.contract_fingerprint() != vorher


def test_eine_kandidatenaenderung_aendert_den_fingerabdruck(monkeypatch):
    vorher = c17.contract_fingerprint()
    monkeypatch.setitem(c17.ALLOWED_MULTISTAGE_CANDIDATES, "erfunden",
                        {"stage_2": "x", "required_fields": (),
                         "source_block": "y"})
    assert c17.contract_fingerprint() != vorher


def test_eine_cutoffaenderung_aendert_den_fingerabdruck(monkeypatch):
    from src.features import prediction_cutoff as pc

    vorher = c17.contract_fingerprint()
    monkeypatch.setattr(pc, "CUTOFF_HOUR", 9)
    assert c17.contract_fingerprint() != vorher


def test_der_vertrag_bindet_das_c16_ergebnis():
    gebunden = c17.contract()["bound_contracts"]
    assert gebunden["c16_contract_fingerprint"] == (
        c16.contract_fingerprint())
    assert gebunden["c16_model_schema_fingerprint"] == (
        c16.schema_fingerprint())
    assert gebunden["c16_result_fingerprint"] == (
        "4f8c7d05a130cfda97052e10c96e26c0a81b189bb84d55c6b8f0d92e2995420a")


# ===========================================================================
# 2  Keine Aufweichung
# ===========================================================================

def test_die_zugelassenen_kandidaten_stehen_namentlich_fest():
    """
    DER KERNTEST DIESES BLOCKS.

    Eine Regel der Form "alle Kandidatennamen erlauben" waere keine
    Erweiterung, sondern das Abschalten der Pruefung.
    """
    assert set(c17.ALLOWED_MULTISTAGE_CANDIDATES) == {
        "team_profile_cl_plus_damped_league_strength"}
    assert c17.is_multistage_candidate(
        "team_profile_cl_plus_damped_league_strength")
    for fremd in ("team_profile_cl", "irgendwas", "", None):
        assert not c17.is_multistage_candidate(fremd)


def test_die_zugelassenen_evaluationsarten_stehen_namentlich_fest():
    assert set(c17.ALLOWED_EVALUATION_TASKS) == {
        "cl_shadow_backtest",
        "v2-c16 damped league strength evaluation"}
    assert c17.validate_evaluation_task("cl_shadow_backtest") == []
    assert c17.validate_evaluation_task("erfunden") != []


def test_ein_unbekannter_kandidat_darf_kein_schema_3_fuehren():
    bundle = {"schema_version": 3, "candidate": "team_profile_cl"}
    befunde = c17.validate_bundle(bundle)
    assert befunde
    assert any("zugelassen" in b for b in befunde)


def test_ein_schema_2_bundle_darf_keine_zweite_stufe_vortaeuschen():
    """
    Ein einstufiges Bundle mit league_strength-Block waere entweder
    ein Irrtum oder ein Versuch, die zweite Stufe an der Pruefung
    vorbeizuschmuggeln.
    """
    bundle = {"schema_version": 2, "candidate": "team_profile_cl",
              "league_strength": {"gamma": 1.0}}
    befunde = c17.validate_bundle(bundle)
    assert befunde
    assert any("Fassung 3" in b or "league_strength" in b
               for b in befunde)


def test_ein_mehrstufiger_kandidat_verlangt_schema_3():
    bundle = {"schema_version": 2,
              "candidate": "team_profile_cl_plus_damped_league_strength"}
    assert c17.validate_bundle(bundle)


def test_ein_schema_2_bundle_bleibt_unveraendert_gueltig():
    """Rueckwaertskompatibilitaet, ausdruecklich geprueft."""
    bundle = {"schema_version": 2, "candidate": "team_profile_cl"}
    assert c17.validate_bundle(bundle) == []
    assert 1 in ps.SUPPORTED_SCHEMA_VERSIONS
    assert 2 in ps.SUPPORTED_SCHEMA_VERSIONS
    assert 3 in ps.SUPPORTED_SCHEMA_VERSIONS


def test_eine_unbekannte_fassung_wird_abgelehnt():
    assert 99 not in ps.SUPPORTED_SCHEMA_VERSIONS


# ===========================================================================
# 3  Die zweite Stufe, vollstaendig geprueft
# ===========================================================================

def _gute_stufe():
    from src.features import league_strength as ls

    return {
        "stage": 2, "gamma": 1.0, "alpha": 0.01,
        "attack": {"PL": 0.4}, "defence": {"NL1": 0.1},
        "team_leagues": {"57": "PL", "678": "NL1"},
        "factor_bounds": [ls.FACTOR_MIN, ls.FACTOR_MAX],
    }


def _bundle(**aenderungen):
    # ERSETZEN, nicht zusammenfuehren: Ein Test, der ein Pflichtfeld
    # entfernt, bekaeme es sonst durch den Standard zurueck und
    # pruefte nichts.
    stufe = aenderungen.pop("stufe", None)
    if stufe is None:
        stufe = dict(_gute_stufe())
    bundle = {"schema_version": 3,
              "candidate": "team_profile_cl_plus_damped_league_strength",
              "league_strength": stufe}
    bundle.update(aenderungen)
    return bundle


def test_ein_vollstaendiges_bundle_wird_angenommen():
    assert c17.validate_bundle(_bundle()) == []
    assert c17.assert_bundle(_bundle()) is True


def test_eine_fehlende_zweite_stufe_wird_abgelehnt():
    bundle = _bundle()
    del bundle["league_strength"]
    befunde = c17.validate_bundle(bundle)
    assert any("zweite Stufe" in b for b in befunde)


@pytest.mark.parametrize("feld", ["attack", "defence", "gamma", "alpha",
                                  "team_leagues", "factor_bounds"])
def test_jedes_pflichtfeld_der_zweiten_stufe_wird_verlangt(feld):
    stufe = dict(_gute_stufe())
    del stufe[feld]
    befunde = c17.validate_bundle(_bundle(stufe=stufe))
    assert befunde, feld


@pytest.mark.parametrize("gamma", [0.0, -0.5, 1.5, 2.0, float("nan"),
                                   float("inf"), "1.0", None, True])
def test_ein_unzulaessiges_gamma_wird_abgelehnt(gamma):
    stufe = dict(_gute_stufe())
    stufe["gamma"] = gamma
    assert c17.validate_bundle(_bundle(stufe=stufe))


@pytest.mark.parametrize("gamma", [0.25, 0.5, 0.75, 1.0])
def test_jedes_gamma_des_gitters_ist_zulaessig(gamma):
    stufe = dict(_gute_stufe())
    stufe["gamma"] = gamma
    assert c17.validate_bundle(_bundle(stufe=stufe)) == []


def test_leere_ligaparameter_werden_abgelehnt():
    for feld in ("attack", "defence"):
        stufe = dict(_gute_stufe())
        stufe[feld] = {}
        assert c17.validate_bundle(_bundle(stufe=stufe))


def test_nicht_endliche_ligaparameter_werden_abgelehnt():
    stufe = dict(_gute_stufe())
    stufe["attack"] = {"PL": float("inf")}
    assert c17.validate_bundle(_bundle(stufe=stufe))


def test_eine_fehlende_ligazuordnung_wird_abgelehnt():
    stufe = dict(_gute_stufe())
    stufe["team_leagues"] = {}
    assert c17.validate_bundle(_bundle(stufe=stufe))


def test_veraenderte_faktorgrenzen_werden_abgelehnt():
    stufe = dict(_gute_stufe())
    stufe["factor_bounds"] = [0.1, 9.9]
    assert c17.validate_bundle(_bundle(stufe=stufe))


# ===========================================================================
# 4  Das freigegebene Bundle
# ===========================================================================

@pytest.fixture(scope="module")
def aktives_bundle():
    from src.ml import inference as inf

    eintrag, _ = mr.active_entry()
    if eintrag is None:
        pytest.skip("kein aktives Modell")
    bundle, _ = inf.load_model()
    return eintrag, bundle


def test_genau_ein_modell_ist_aktiv():
    dokument = mr.load_registry()
    aktiv = [m for m in dokument["models"]
             if m["stage"] == mr.STAGE_ACTIVE]
    assert len(aktiv) == 1, [m["model_id"] for m in aktiv]
    assert mr.validate_registry(dokument) == []


def test_das_aktive_modell_ist_das_c16_modell(aktives_bundle):
    eintrag, bundle = aktives_bundle
    assert bundle["candidate"] == c16.CANDIDATE
    assert bundle["schema_version"] == c17.MULTISTAGE_SCHEMA_VERSION
    assert eintrag["model_id"] == bundle["model_id"]
    assert eintrag["evaluation_status"] == mr.EVALUATION_ACCEPTED


def test_das_bundle_traegt_beide_stufen(aktives_bundle):
    _, bundle = aktives_bundle
    assert bundle["models"]["home"] and bundle["models"]["away"]
    stufe = bundle["league_strength"]
    assert stufe["attack"] and stufe["defence"]
    assert 0 < stufe["gamma"] <= 1
    assert stufe["team_leagues"]
    assert c17.validate_bundle(bundle) == []


def test_das_bundle_bindet_die_ganze_vertragskette(aktives_bundle):
    from src.ml import c13_contract as c13
    from src.ml import c14_reevaluation as c14
    from src.ml import c15_league_strength as c15
    from src.ml import early_v2 as e9

    _, bundle = aktives_bundle
    b = bundle["contract_bindings"]
    assert b["c9_schema_fingerprint"] == e9.schema_fingerprint()
    assert b["c13_contract_fingerprint"] == c13.contract_fingerprint()
    assert b["c14_contract_fingerprint"] == c14.contract_fingerprint()
    assert b["c15_contract_fingerprint"] == c15.contract_fingerprint()
    assert b["c16_contract_fingerprint"] == c16.contract_fingerprint()
    assert b["c17_contract_fingerprint"] == c17.contract_fingerprint()
    assert b["c10_cutoff_hour"] == 12


def test_der_bundlehash_stimmt_mit_der_registry(aktives_bundle):
    eintrag, _ = aktives_bundle
    pfad = WURZEL / eintrag["bundle_path"]
    assert pfad.is_file()
    assert mr.bundle_sha256(str(pfad)) == eintrag["bundle_sha256"]


def test_die_freigabe_ist_gebunden_und_gueltig(aktives_bundle):
    eintrag, _ = aktives_bundle
    assert eintrag.get("approval")
    gueltig, warum = mr.verify_approval(eintrag, eintrag["approval"],
                                        mr.STAGE_ACTIVE)
    assert gueltig, warum


def test_das_bundle_traegt_keine_geheimnisse_und_keine_pfade(
        aktives_bundle):
    _, bundle = aktives_bundle
    text = json.dumps(bundle, ensure_ascii=False)
    for verboten in ("C:\\\\", "/home/", "AppData", "api_key",
                     "APISPORTS_KEY", "secret", "password"):
        assert verboten.lower() not in text.lower(), verboten


# ===========================================================================
# 5  Runtime und Fail-closed
# ===========================================================================

def test_die_runtime_waehlt_das_bundle_aus_der_registry():
    """
    Bis C17 las die Laufzeit einen festen Pfad. Ein neu freigegebenes
    Modell wurde damit nie geladen - eine Freigabe, die man von Hand
    nachvollziehen muss, ist keine.
    """
    from src.ml import inference as inf

    eintrag, _ = mr.active_entry()
    if eintrag is None:
        pytest.skip("kein aktives Modell")
    pfad = inf.active_bundle_path()
    assert pfad is not None
    assert eintrag["model_id"] in pfad


def test_ohne_aktives_modell_gilt_der_standardpfad(monkeypatch):
    from src.ml import inference as inf

    monkeypatch.setattr(mr, "active_entry", lambda *a, **k: (None, "x"))
    assert inf.active_bundle_path() is None


def test_eine_unlesbare_registry_bringt_die_runtime_nicht_zum_absturz(
        monkeypatch):
    from src.ml import inference as inf

    def kaputt(*a, **k):
        raise RuntimeError("Registry unlesbar")

    monkeypatch.setattr(mr, "active_entry", kaputt)
    assert inf.active_bundle_path() is None


def test_die_zweite_stufe_wirkt_nur_mit_bundleblock():
    """
    Ein Bundle ohne `league_strength` rechnet Bit fuer Bit wie zuvor.
    Damit nimmt ein Rollback auf ein aelteres Bundle die zweite Stufe
    vollstaendig zurueck.
    """
    from src.ml import inference as inf

    from src.features import league_strength as ls

    heim, gast, diagnose = inf._ligastaerke_anwenden(
        _gute_stufe(), {"team_id": 57}, {"team_id": 678}, 1.0, 1.0)
    assert diagnose["applied"] is True
    # exp(0.5) = 1.6487 liegt ueber der Faktorgrenze und wird geklammert.
    # Genau das soll die Grenze leisten.
    assert heim == pytest.approx(min(math.exp(0.4 + 0.1), ls.FACTOR_MAX))
    assert heim <= ls.FACTOR_MAX

    # Eine kleinere Daempfung bleibt unterhalb der Grenze und zeigt die
    # Formel unverfaelscht.
    stufe = dict(_gute_stufe())
    stufe["gamma"] = 0.5
    heim2, _, d2 = inf._ligastaerke_anwenden(
        stufe, {"team_id": 57}, {"team_id": 678}, 1.0, 1.0)
    assert d2["applied"] is True
    assert heim2 == pytest.approx(math.exp(0.5 * (0.4 + 0.1)))


def test_eine_unbekannte_liga_bleibt_neutral():
    from src.ml import inference as inf

    heim, gast, diagnose = inf._ligastaerke_anwenden(
        _gute_stufe(), {"team_id": 57}, {"team_id": 99999}, 1.2, 0.9)
    assert diagnose["applied"] is False
    assert (heim, gast) == (1.2, 0.9)


def test_die_end_to_end_simulation_wendet_beide_stufen_an():
    """
    Der eigentliche Beweis: dieselbe Partie, beide Richtungen, und
    die Ligastaerke wirkt richtungsabhaengig.
    """
    from src.ml import runtime as rt

    if mr.active_entry()[0] is None:
        pytest.skip("kein aktives Modell")

    def profil(tid):
        return {"team_id": tid, "attack_home": 1.35, "attack_away": 1.15,
                "defence_home": 0.80, "defence_away": 0.95,
                "points_per_game": 2.1, "goals_for_per_game": 2.2,
                "goals_against_per_game": 0.9, "win_rate": 0.68,
                "matches_used": 40}

    umgebung = {"FOOTSIM_ML_MODE": "active", "FOOTSIM_ML_WEIGHT": "1.0"}
    a = rt.resolve_simulation_lambdas(1.60, 1.10, profil(57), profil(678),
                                      "domestic_history",
                                      "domestic_history",
                                      environ=umgebung)
    b = rt.resolve_simulation_lambdas(1.60, 1.10, profil(678), profil(57),
                                      "domestic_history",
                                      "domestic_history",
                                      environ=umgebung)

    assert a["ml_applied_to_production"] is True
    assert a["model_id"] == mr.active_entry()[0]["model_id"]
    assert not a["fallback_reason"]
    assert (round(a["lambda_home"], 6), round(a["lambda_away"], 6)) != (
        round(b["lambda_home"], 6), round(b["lambda_away"], 6))
    for wert in (a["lambda_home"], a["lambda_away"]):
        assert math.isfinite(wert) and wert > 0


def test_der_standardmodus_bleibt_bitgleich_v0():
    from src.ml import runtime as rt

    e = rt.resolve_simulation_lambdas(
        1.60, 1.10, {"team_id": 57}, {"team_id": 678},
        "domestic_history", "domestic_history", environ={})
    assert e["ml_applied_to_production"] is False
    assert (e["lambda_home"], e["lambda_away"]) == (1.60, 1.10)


# ===========================================================================
# 6  Die individuellen Regler
# ===========================================================================

def test_es_gibt_genau_vier_regler_und_keinen_ml_regler():
    from src.predict import cl_custom_factors as ccf

    assert set(ccf.FACTOR_BOUNDS) == {
        "home_strength", "away_strength", "home_advantage", "goal_level"}
    assert "ml_weight" not in ccf.FACTOR_BOUNDS


def test_der_ml_regler_ist_aus_der_oberflaeche_verschwunden():
    skript = (WURZEL / "static" / "script.js").read_text(encoding="utf-8")
    block = skript[skript.index("const CL_FACTOR_CONTROLS = ["):]
    block = block[:block.index("];")]
    assert "ml_weight" not in block

    html = (WURZEL / "templates" / "index.html").read_text(
        encoding="utf-8")
    assert "cl-factor-ml" not in html
    assert "clApproach.mlInfluence" not in html


def test_ml_modus_ignoriert_die_individuellen_regler():
    from src.predict import cl_custom_factors as ccf

    optionen = ccf.parse_options({"approach": "ml"})
    assert optionen["factors"] == ccf.NEUTRAL_FACTORS
    assert optionen["ml_weight"] == ccf.ML_WEIGHT_FOR_ML


def test_individueller_modus_laedt_kein_modell(monkeypatch):
    """
    ERWEITERT IN DER V2-C17-HAERTUNG.

    ml_weight == 0,0 allein bewies das bis dahin NICHT: Vor der
    Haertung setzte ml_config() fuer 'custom' den Modus 'active' mit
    Gewicht 0, und runtime.resolve_simulation_lambdas() lud das Modell
    in diesem Modus TROTZDEM - nur sein rechnerischer Effekt war
    neutral (faktor ** 0 = 1). Der Spy unten prueft das tatsaechliche
    Verhalten (inference.shadow_lambdas wird aufgerufen oder nicht)
    statt nur den Stellvertreterwert 'ml_weight'.
    """
    from src.ml import inference as inf
    from src.predict import cl_custom_factors as ccf
    from src.predict import cl_match_sim

    optionen = ccf.parse_options({"approach": "custom"})
    assert optionen["ml_weight"] == ccf.ML_WEIGHT_DEFAULT_CUSTOM == 0.0

    aufrufe = []
    monkeypatch.setattr(inf, "shadow_lambdas",
                        lambda *a, **kw: aufrufe.append(1))
    cl_match_sim.simulate_cl_league_phase_match(
        home_team="Heim", away_team="Gast", home_id=5, away_id=678,
        season=2025, simulations=50, use_seed=True, options=optionen)
    assert aufrufe == [], (
        "approach='custom' hat inference.shadow_lambdas aufgerufen - "
        "der ML-Loader lief trotz individuellem Modus an")


def test_das_backend_prueft_die_grenzen_unabhaengig_vom_frontend():
    from src.predict import cl_custom_factors as ccf

    for name, (unten, oben) in ccf.FACTOR_BOUNDS.items():
        for wert in (unten - 0.01, oben + 0.01, 99.0, -1.0):
            with pytest.raises(ccf.InvalidSimulationRequest):
                ccf.parse_factors({name: wert})


def test_ein_unbekannter_regler_wird_abgewiesen():
    from src.predict import cl_custom_factors as ccf

    with pytest.raises(ccf.InvalidSimulationRequest, match="Unbekannt"):
        ccf.parse_factors({"erfunden": 1.0})
    with pytest.raises(ccf.InvalidSimulationRequest):
        ccf.parse_factors({"ml_weight": 1.0})
