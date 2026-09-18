"""
Tests der finalen Evaluation (V2-C12).

WORUM ES GEHT
C12 entscheidet, ob das laufende Modell eine regulaere Freigabe
traegt. Der Wert der Entscheidung haengt vollstaendig an einer
Reihenfolge: erst der Vertrag, dann die Messung, dann das Urteil. Wer
die Schwellen nach dem Ergebnis waehlt, hat nichts gemessen.

Die schaerfsten Tests hier pruefen deshalb nicht das Ergebnis, sondern
die Reihenfolge - und dass jedes der vier Urteile ueberhaupt
erreichbar ist. Ein Gate, das immer dasselbe sagt, misst nichts.
"""

import json
import pathlib

import pytest

from src.ml import c12_evaluation as c12
from src.ml import cl_evaluate as ce
from src.ml import model_registry as mr

WURZEL = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Kunstmessungen fuer die Entscheidungsfaelle
# ---------------------------------------------------------------------------

def _messung(delta=-0.02, ci_low=-0.05, ci_high=-0.005, n=213,
             fold_deltas=(-0.02, -0.02), kalib_basis=0.048,
             kalib_ml=0.016, delta_brier=-0.004, delta_rps=-0.001,
             segmente=None):
    """
    Eine vollstaendige Kunstmessung.

    Von Hand und nicht aus einem echten Lauf: Ein Test, der den ganzen
    Datensatzbau braucht, prueft am Ende den Datensatzbau und nicht die
    Gates.
    """
    return {
        "candidate": ce.CANDIDATE,
        "feature_count": 16,
        "rows_evaluated": n,
        "folds": [{"fold": f"f{i}", "test_rows": n // len(fold_deltas),
                   "delta_log_loss": d}
                  for i, d in enumerate(fold_deltas)],
        "aggregate": {
            "n": n,
            "delta_log_loss": delta,
            "delta_brier": delta_brier,
            "delta_rps": delta_rps,
            "baseline": {"log_loss": 0.93, "brier": 0.548, "rps": 0.214,
                         "calibration_error": kalib_basis},
            "ml": {"log_loss": 0.93 + delta, "brier": 0.548 + delta_brier,
                   "rps": 0.214 + delta_rps,
                   "calibration_error": kalib_ml},
            "bootstrap": {"log_loss": {"point": delta, "ci_low": ci_low,
                                       "ci_high": ci_high}},
        },
        "segments": segmente if segmente is not None else {
            "season:2024": {"n": 112, "delta_log_loss": -0.01,
                            "interpretable": True,
                            "severely_worse": False},
        },
        "reliability": {"baseline": [], "ml": []},
        "exclusions": {},
    }


# ===========================================================================
# 1  Der Vertrag steht VOR der Messung
# ===========================================================================

def test_der_vertrag_ist_deterministisch():
    assert c12.contract_fingerprint() == c12.contract_fingerprint()
    assert len(c12.contract_fingerprint()) == 64


def test_der_vertrag_braucht_keine_messung():
    """
    Er laesst sich vollstaendig bilden, bevor irgendetwas gerechnet
    wurde. Genau das ist seine Aufgabe.
    """
    vertrag = c12.evaluation_contract()
    assert vertrag["gates"]["accepted"]
    assert vertrag["thresholds"]["min_reliable_n"] == ce.MIN_RELIABLE_N
    assert vertrag["no_untouched_holdout"] is True


def test_eine_geaenderte_schwelle_veraendert_den_fingerabdruck():
    """
    DER RIEGEL GEGEN DIE HAEUFIGSTE SELBSTTAEUSCHUNG.

    Erst messen, dann die Schwelle so legen, dass es passt. Wer das
    tut, bekommt einen anderen Vertragsfingerabdruck, und das Ergebnis
    passt nicht mehr dazu.
    """
    vorher = c12.contract_fingerprint()
    verbogen = c12.evaluation_contract()
    verbogen["thresholds"]["severe_fold_degradation"] = 0.5
    assert c12.contract_fingerprint(verbogen) != vorher


def test_ein_ergebnis_mit_fremdem_vertrag_wird_abgewiesen():
    with pytest.raises(c12.ContractViolation, match="Vertrag"):
        c12.assert_contract_matches({"contract_fingerprint": "0" * 64})


def test_ein_ergebnis_mit_passendem_vertrag_wird_angenommen():
    assert c12.assert_contract_matches(
        {"contract_fingerprint": c12.contract_fingerprint()})


def test_die_schwellen_stammen_aus_bestehenden_bloecken():
    """
    Sie werden importiert, nicht abgeschrieben. Eine hier neu
    erfundene Zahl waere die bequemste Art, ein Ergebnis zu bekommen.
    """
    from src.ml import c8_ablation as c8

    schwellen = c12.evaluation_contract()["thresholds"]
    assert schwellen["min_reliable_n"] == ce.MIN_RELIABLE_N
    assert schwellen["severe_fold_degradation"] == ce.SEVERE_DEGRADATION
    assert (schwellen["max_calibration_degradation"]
            == c8.MAX_CALIBRATION_DEGRADATION)
    assert (schwellen["max_secondary_degradation"]
            == c8.MAX_SECONDARY_DEGRADATION)


def test_der_vertrag_haelt_den_fehlenden_holdout_fest():
    vertrag = c12.evaluation_contract()
    offenlegung = vertrag["reused_data_disclosure"]
    assert offenlegung["seasons"] == [2023, 2024, 2025]
    assert "Entwicklungsevidenz" in offenlegung["consequence"]
    assert (offenlegung["acceptance_class_if_accepted"]
            == c12.ACCEPTANCE_CLASS_DEVELOPMENT)


def test_early_v2_wird_nicht_kuenstlich_unterschieden():
    """
    C9 hat als Selected ausschliesslich die Gruppe profile bestimmt.
    Early V2 ist damit numerisch V1, und der Vertrag sagt das, statt
    einen Unterschied zu erfinden.
    """
    from src.ml import early_v2 as e9

    kandidaten = c12.evaluation_contract()["candidates"]
    assert kandidaten["early_v2"]["identical_to_v1"] is True
    assert [f for f, m in e9.FAMILY_REGISTRY.items()
            if m["status"] == e9.STATUS_SELECTED] == ["profile"]


def test_die_challenger_sind_not_evaluated_mit_begruendung():
    """
    Ein nicht gebautes Modell ist kein gescheitertes Modell. Die
    Begruendung muss tragen, nicht bloss dastehen.
    """
    for eintrag in c12.evaluation_contract()["challengers_not_evaluated"]:
        assert eintrag["status"] == "not_evaluated"
        assert len(eintrag["reason"]) > 80


# ===========================================================================
# 2  Die vier Urteile sind alle erreichbar
# ===========================================================================

def test_ein_klarer_kandidat_ergibt_accepted():
    """
    Die Gegenprobe zu allen Ablehnungen. Ohne sie koennte das Gate
    immer ablehnen und saemtliche anderen Tests waeren trotzdem gruen.
    """
    urteil = c12.decide(_messung())
    assert urteil["verdict"] == c12.VERDICT_ACCEPTED
    assert urteil["acceptance_class"] == c12.ACCEPTANCE_CLASS_DEVELOPMENT


def test_ein_unsicherer_kandidat_ergibt_provisional_shadow():
    """
    Punktschaetzer gut, Intervall traegt keine Freigabe. Genau dafuer
    gibt es den Schattenbetrieb.
    """
    urteil = c12.decide(_messung(ci_high=+0.012))
    assert urteil["verdict"] == c12.VERDICT_PROVISIONAL_SHADOW
    assert any("Intervall" in g for g in urteil["reasons"])


def test_ein_schlechterer_kandidat_ergibt_rejected():
    urteil = c12.decide(_messung(delta=+0.02, ci_low=+0.005,
                                 ci_high=+0.04,
                                 fold_deltas=(+0.02, +0.02)))
    assert urteil["verdict"] == c12.VERDICT_REJECTED


def test_widersprechende_folds_ergeben_rejected():
    urteil = c12.decide(_messung(fold_deltas=(-0.05, +0.01)))
    assert urteil["verdict"] == c12.VERDICT_REJECTED
    assert any("widersprechen" in g for g in urteil["reasons"])


def test_ein_schwer_beschaedigtes_segment_ergibt_rejected():
    """
    DER BEFUND, DEN DIE ECHTE MESSUNG GELIEFERT HAT.

    Ein guter Gesamtdurchschnitt darf eine schwere Verschlechterung in
    einem ausreichend grossen Segment nicht verdecken.
    """
    urteil = c12.decide(_messung(segmente={
        "gut": {"n": 160, "delta_log_loss": -0.03,
                "interpretable": True, "severely_worse": False},
        "schlecht": {"n": 53, "delta_log_loss": +0.042,
                     "interpretable": True, "severely_worse": True},
    }))
    assert urteil["verdict"] == c12.VERDICT_REJECTED
    assert any("Segmente" in g for g in urteil["reasons"])


def test_ein_zu_kleines_segment_kippt_das_urteil_nicht():
    """
    Einzelspiele sind kein Beleg. Ein Segment unter der Mindestgroesse
    wird ausgewiesen, aber nicht interpretiert.
    """
    urteil = c12.decide(_messung(segmente={
        "winzig": {"n": 8, "delta_log_loss": +0.9,
                   "interpretable": False, "severely_worse": False},
    }))
    assert urteil["verdict"] == c12.VERDICT_ACCEPTED


def test_zu_wenige_zeilen_ergeben_not_evaluable():
    urteil = c12.decide(_messung(n=12))
    assert urteil["verdict"] == c12.VERDICT_NOT_EVALUABLE


def test_ohne_folds_ergibt_not_evaluable():
    messung = _messung()
    messung["folds"] = []
    assert c12.decide(messung)["verdict"] == c12.VERDICT_NOT_EVALUABLE


def test_eine_eingebrochene_kalibrierung_verhindert_accepted():
    urteil = c12.decide(_messung(kalib_basis=0.016, kalib_ml=0.09))
    assert urteil["conditions"]["calibration_holds"] is False
    assert urteil["verdict"] != c12.VERDICT_ACCEPTED


@pytest.mark.parametrize("feld,wert", [("delta_brier", +0.01),
                                       ("delta_rps", +0.01)])
def test_eine_verschlechterte_zweitmetrik_ergibt_rejected(feld, wert):
    urteil = c12.decide(_messung(**{feld: wert}))
    assert urteil["verdict"] == c12.VERDICT_REJECTED


def test_ein_dominanter_fold_verhindert_accepted():
    """
    Zwei Folds sind wenig. Kommt der Gewinn fast vollstaendig aus
    einem, ist es eine Saisoneigenschaft.
    """
    urteil = c12.decide(_messung(fold_deltas=(-0.0399, -0.0001),
                                 delta=-0.02))
    assert urteil["conditions"]["no_single_fold_carries_all"] is False
    assert urteil["verdict"] != c12.VERDICT_ACCEPTED


def test_jedes_urteil_nennt_den_fehlenden_holdout():
    for messung in (_messung(), _messung(ci_high=+0.02),
                    _messung(delta=+0.05, fold_deltas=(+0.05, +0.05))):
        urteil = c12.decide(messung)
        assert "Entwicklungsevidenz" in urteil["holdout_caveat"]


def test_kein_einzelwert_umgeht_die_uebrigen_gates():
    """
    Ein sehr guter Punktschaetzer traegt keine Freigabe, wenn eine
    andere Bedingung faellt.
    """
    urteil = c12.decide(_messung(delta=-0.5, ci_high=+0.001))
    assert urteil["verdict"] != c12.VERDICT_ACCEPTED


def test_die_urteile_sind_genau_die_vier_erlaubten():
    assert set(c12.VERDICTS) == {"accepted", "provisional_shadow",
                                 "rejected", "not_evaluable"}


# ===========================================================================
# 3  Die Anwendung auf die Registry
# ===========================================================================

def _registry_mit(stage, status, tmp_path):
    pfad = tmp_path / "data" / "ml" / "models"
    pfad.mkdir(parents=True, exist_ok=True)
    datei = pfad / "b.json"
    datei.write_text('{"model_id": "clm-x"}', encoding="utf-8")
    eintrag = {
        "model_id": "clm-x", "model_name": "team_profile_cl",
        "model_family": "poisson_offset_correction_linear",
        "bundle_schema_version": 2, "stage": stage,
        "bundle_path": "data/ml/models/b.json",
        "bundle_sha256": mr.bundle_sha256(str(datei)),
        "feature_schema_fingerprint": "f" * 64,
        "c9_manifest_fingerprint": "9" * 64,
        "c10_contract_fingerprint": "a" * 64,
        "evaluation_artifact": "data/ml/eval.json",
        "evaluation_status": status,
        "state_reason": "Kunsteintrag",
    }
    doc = mr.empty_registry()
    doc["models"] = [eintrag]
    return doc


def test_rejected_nimmt_das_modell_aus_dem_aktiven_betrieb(tmp_path):
    doc = _registry_mit(mr.STAGE_ACTIVE, mr.EVALUATION_GRANDFATHERED,
                        tmp_path)
    doc["models"][0]["grandfathered"] = True
    doc["models"][0]["grandfathered_reason"] = "x" * 40

    urteil = {"verdict": c12.VERDICT_REJECTED}
    neu, beschreibung = c12.apply_decision(urteil, "data/ml/c12.json",
                                           dokument=doc)
    assert beschreibung["to"] == mr.STAGE_CANDIDATE
    assert neu["models"][0]["evaluation_status"] == "rejected"
    assert mr.active_entry(neu, str(tmp_path))[0] is None


def test_provisional_shadow_setzt_auf_schatten(tmp_path):
    doc = _registry_mit(mr.STAGE_ACTIVE, mr.EVALUATION_GRANDFATHERED,
                        tmp_path)
    doc["models"][0]["grandfathered"] = True
    doc["models"][0]["grandfathered_reason"] = "x" * 40

    neu, beschreibung = c12.apply_decision(
        {"verdict": c12.VERDICT_PROVISIONAL_SHADOW},
        "data/ml/c12.json", dokument=doc)
    assert beschreibung["to"] == mr.STAGE_SHADOW
    assert mr.active_entry(neu, str(tmp_path))[0] is None


def test_der_bestandsschutz_verschwindet_bei_jeder_entscheidung(tmp_path):
    """
    grandfathered_pre_c11 darf kein Dauerzustand bleiben. Jede
    Entscheidung loest ihn auf.
    """
    for verdict in (c12.VERDICT_REJECTED, c12.VERDICT_PROVISIONAL_SHADOW,
                    c12.VERDICT_NOT_EVALUABLE):
        doc = _registry_mit(mr.STAGE_ACTIVE, mr.EVALUATION_GRANDFATHERED,
                            tmp_path)
        doc["models"][0]["grandfathered"] = True
        doc["models"][0]["grandfathered_reason"] = "x" * 40
        neu, _ = c12.apply_decision({"verdict": verdict},
                                    "data/ml/c12.json", dokument=doc)
        eintrag = neu["models"][0]
        assert eintrag["evaluation_status"] != mr.EVALUATION_GRANDFATHERED
        assert "grandfathered" not in eintrag
        assert "approval" not in eintrag


def test_eine_ausserbetriebnahme_braucht_das_belegende_artefakt(tmp_path):
    doc = _registry_mit(mr.STAGE_ACTIVE, mr.EVALUATION_GRANDFATHERED,
                        tmp_path)
    with pytest.raises(mr.RegistryError, match="Artefakt"):
        mr.retire(doc, "clm-x", evaluation_status="rejected",
                  evaluation_artifact=None, reason="x" * 40)


def test_eine_ausserbetriebnahme_braucht_eine_begruendung(tmp_path):
    doc = _registry_mit(mr.STAGE_ACTIVE, mr.EVALUATION_GRANDFATHERED,
                        tmp_path)
    with pytest.raises(mr.RegistryError, match="Begruendung"):
        mr.retire(doc, "clm-x", evaluation_status="rejected",
                  evaluation_artifact="data/ml/c12.json", reason="kurz")


def test_ein_angenommenes_modell_wird_nicht_ausser_betrieb_genommen(
        tmp_path):
    doc = _registry_mit(mr.STAGE_ACTIVE, mr.EVALUATION_ACCEPTED
                        if hasattr(mr, "EVALUATION_ACCEPTED") else "accepted",
                        tmp_path)
    with pytest.raises(mr.RegistryError, match="angenommenes"):
        mr.retire(doc, "clm-x", evaluation_status=mr.EVALUATION_ACCEPTED,
                  evaluation_artifact="data/ml/c12.json",
                  reason="x" * 40)


def test_accepted_wird_nicht_stillschweigend_angewandt(tmp_path):
    """
    Der accepted-Zweig verlangt eine regulaere Freigabe ueber
    build_approval und set_stage. Ihn abzukuerzen hiesse, das
    Freigabegate aus C11 zu umgehen.

    GEAENDERT IN V2-C15, und die Aenderung ist der Fortschritt.

    Vorher pruefte dieser Test, dass der Zweig ein
    NotImplementedError wirft. Das war damals ehrlich: Der Weg war
    nicht gebaut, und ein halb gebauter Freigabeweg waere gefaehrlicher
    gewesen als gar keiner.

    Inzwischen ist er gebaut, und die Zusicherung wandert dorthin, wo
    sie hingehoert: Der Zweig bereitet einen Zustand vor und SCHREIBT
    NICHTS. Er erzeugt eine an alle Fingerabdruecke gebundene
    Freigabe, er garantiert genau ein aktives Modell, und er laesst
    die uebergebene Registry unangetastet. Wer wirklich aktivieren
    will, geht ueber c15_release mit Vorpruefung, Vorzustandssicherung
    und erneuter Validierung.
    """
    doc = _registry_mit(mr.STAGE_SHADOW, mr.EVALUATION_ACCEPTED,
                        tmp_path)
    vorher = mr.registry_fingerprint(doc)

    neu, beschreibung = c12.apply_decision(
        {"verdict": c12.VERDICT_ACCEPTED}, "data/ml/c12.json",
        dokument=doc)

    # Der uebergebene Stand bleibt unberuehrt - es wurde nichts
    # geschrieben, nur vorbereitet.
    assert mr.registry_fingerprint(doc) == vorher
    assert beschreibung["to"] == mr.STAGE_ACTIVE
    assert beschreibung["approval_bound"] is True

    aktiv = [m for m in neu["models"] if m["stage"] == mr.STAGE_ACTIVE]
    assert len(aktiv) == 1, "genau ein aktives Modell, nie mehr"
    assert aktiv[0].get("approval"), "ohne gebundene Freigabe keine Stufe"


def test_der_accepted_zweig_wirft_nicht_mehr(tmp_path):
    """
    Die Gegenprobe zur Aenderung oben.

    Ein Freigabeweg, den nie jemand gegangen ist, faellt genau dann
    aus, wenn man ihn zum ersten Mal braucht.
    """
    doc = _registry_mit(mr.STAGE_SHADOW, mr.EVALUATION_ACCEPTED,
                        tmp_path)
    neu, _ = c12.apply_decision({"verdict": c12.VERDICT_ACCEPTED},
                                "data/ml/c12.json", dokument=doc)
    assert neu is not None


def test_nach_der_entscheidung_bleibt_die_registry_gueltig(tmp_path):
    doc = _registry_mit(mr.STAGE_ACTIVE, mr.EVALUATION_GRANDFATHERED,
                        tmp_path)
    doc["models"][0]["grandfathered"] = True
    doc["models"][0]["grandfathered_reason"] = "x" * 40
    neu, _ = c12.apply_decision({"verdict": c12.VERDICT_REJECTED},
                                "data/ml/c12.json", dokument=doc)
    assert mr.validate_registry(neu, str(tmp_path)) == []


# ===========================================================================
# 4  Der tatsaechliche Stand nach C12
# ===========================================================================

def test_das_c12_artefakt_existiert_und_nennt_seinen_vertrag():
    pfad = WURZEL / "data" / "ml" / "c12_final_evaluation_2023-2025.json"
    assert pfad.exists()
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    assert daten["contract_fingerprint"] == c12.contract_fingerprint()
    c12.assert_contract_matches(daten)


def test_das_artefakt_bindet_alle_vertragsfingerabdruecke():
    pfad = WURZEL / "data" / "ml" / "c12_final_evaluation_2023-2025.json"
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    gebunden = daten["bound_fingerprints"]
    for name in ("c9_manifest", "c10_contract", "c11_contract",
                 "feature_schema"):
        assert gebunden[name] and len(gebunden[name]) == 64, name


def test_das_verdict_ist_eines_der_vier():
    pfad = WURZEL / "data" / "ml" / "c12_final_evaluation_2023-2025.json"
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    assert daten["verdict"] in c12.VERDICTS


def test_der_bestandsschutz_ist_aufgeloest():
    """
    DIE ZENTRALE ZUSICHERUNG DIESES BLOCKS.

    grandfathered_pre_c11 war ein Uebergangszustand. Nach C12 gibt es
    ihn nicht mehr, und die Entscheidung steht im Artefakt.
    """
    doc = mr.load_registry()
    for eintrag in doc.get("models") or []:
        assert (eintrag["evaluation_status"]
                != mr.EVALUATION_GRANDFATHERED)
        assert "grandfathered" not in eintrag

    pfad = WURZEL / "data" / "ml" / "c12_final_evaluation_2023-2025.json"
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    assert daten["grandfathered_resolution"]["resolved"] is True


def test_das_c12_modell_bestimmt_die_nutzerantwort_nicht():
    """
    GEAENDERT IN V2-C17.

    Das C12-Urteil war rejected, und daran hat sich nichts geaendert.
    Vorher bedeutete das "gar kein aktives Modell"; seit C17 ist ein
    ANDERES, spaeter freigegebenes Modell aktiv.

    Die Zusicherung wandert deshalb auf den Punkt, um den es hier
    immer ging: Das in C12 abgelehnte Bundle bestimmt keine
    Nutzerantwort. Ein abgelehntes Modell darf durch keine spaetere
    Aenderung aktiv werden.
    """
    doc = mr.load_registry()
    abgelehnt = [e for e in doc.get("models") or []
                 if e.get("evaluation_status") == "rejected"]
    assert abgelehnt, "der C12-Eintrag sollte erhalten bleiben"
    for eintrag in abgelehnt:
        assert eintrag["stage"] != mr.STAGE_ACTIVE
        assert "approval" not in eintrag

    eintrag, grund = mr.active_entry()
    if eintrag is not None:
        assert eintrag["evaluation_status"] == mr.EVALUATION_ACCEPTED
        assert eintrag["model_id"] not in {
            e["model_id"] for e in abgelehnt}


def test_die_registry_ist_nach_c12_gueltig():
    assert mr.validate_registry(mr.load_registry()) == []


def test_das_bundle_wurde_nicht_veraendert():
    """
    C12 hat entschieden, nicht umgebaut. Die Datei ist dieselbe.
    """
    doc = mr.load_registry()
    for eintrag in doc.get("models") or []:
        pfad = WURZEL / eintrag["bundle_path"]
        assert pfad.is_file()
        assert mr.bundle_sha256(str(pfad)) == eintrag["bundle_sha256"]


def test_die_c9_auswahl_ist_unveraendert():
    from src.ml import early_v2 as e9

    assert e9.SELECTED_CANDIDATE == "team_profile_cl"
    assert len(e9.selected_columns()) == 16
    manifest = json.loads(
        (WURZEL / "data" / "ml"
         / "c9_early_v2_manifest_2023-2025.json").read_text(
            encoding="utf-8"))
    assert e9.schema_fingerprint() == manifest["fingerprints"]["schema"]


def test_der_c10_cutoff_ist_unveraendert():
    from src.features import prediction_cutoff as pc
    from src.ml import dataset as ds

    assert pc.CUTOFF_HOUR == 12
    assert pc.CUTOFF_INCLUSIVE is False
    assert pc.assert_hours_match() is True
    assert ds.prediction_cutoff("2025-03-11").hour == 12


# ===========================================================================
# 5  Reproduzierbarkeit
# ===========================================================================

def test_das_artefakt_hat_einen_stabilen_fingerabdruck():
    pfad = WURZEL / "data" / "ml" / "c12_final_evaluation_2023-2025.json"
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    assert len(daten["stable_fingerprint"]) == 64
    assert daten["fingerprint_excludes"] == list(c12.VOLATILE_FIELDS)


def test_der_fingerabdruck_ignoriert_zeit_und_commit():
    import copy

    pfad = WURZEL / "data" / "ml" / "c12_final_evaluation_2023-2025.json"
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    ohne = {k: v for k, v in daten.items()
            if k not in ("stable_fingerprint", "fingerprint_excludes")}

    verbogen = copy.deepcopy(ohne)
    verbogen["created_at"] = "1999-01-01T00:00:00+00:00"
    verbogen["git_commit"] = "0" * 40

    assert (c12._stabiler_fingerabdruck(ohne)
            == c12._stabiler_fingerabdruck(verbogen))


def test_die_entscheidung_ist_bei_gleicher_messung_gleich():
    messung = _messung(ci_high=+0.012)
    assert (c12.decide(messung)["verdict"]
            == c12.decide(messung)["verdict"])


def test_c12_braucht_kein_netz_und_keine_env():
    import ast

    baum = ast.parse((WURZEL / "src" / "ml" / "c12_evaluation.py"
                      ).read_text(encoding="utf-8"))
    importiert = set()
    for knoten in baum.body:
        if isinstance(knoten, ast.Import):
            for name in knoten.names:
                importiert.add(name.name.split(".")[0])
        elif isinstance(knoten, ast.ImportFrom) and knoten.module:
            importiert.add(knoten.module.split(".")[0])
    assert not (importiert & {"requests", "urllib", "socket", "httpx",
                              "dotenv", "os"})


def test_das_artefakt_enthaelt_keine_geheimnisse_und_keine_pfade():
    pfad = WURZEL / "data" / "ml" / "c12_final_evaluation_2023-2025.json"
    roh = pfad.read_text(encoding="utf-8")
    tief = roh.lower()
    for verboten in ("api_key", "apikey", "secret", "token", "password",
                     "bearer"):
        assert verboten not in tief, verboten
    assert "c:\\users" not in tief
    assert "/home/" not in roh


def test_das_artefakt_speichert_keine_merkmalsvektoren():
    """
    Es belegt einen Stand, es dupliziert ihn nicht.
    """
    pfad = WURZEL / "data" / "ml" / "c12_final_evaluation_2023-2025.json"
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    assert "rows" not in daten["measurement"]
    assert pfad.stat().st_size < 2_000_000


# ===========================================================================
# 6  Modustrennung bleibt
# ===========================================================================

def test_der_individuelle_modus_laedt_kein_modell():
    for name in ("league_match_sim.py", "season_sim.py",
                 "simulate_scores.py", "poisson.py"):
        pfad = WURZEL / "src" / "predict" / name
        if pfad.exists():
            text = pfad.read_text(encoding="utf-8")
            assert "src.ml" not in text, name
            assert "c12_evaluation" not in text, name


def test_c12_beruehrt_den_reglerpfad_nicht():
    import ast

    baum = ast.parse((WURZEL / "src" / "ml" / "c12_evaluation.py"
                      ).read_text(encoding="utf-8"))
    for knoten in ast.walk(baum):
        if (isinstance(knoten, (ast.Module, ast.ClassDef, ast.FunctionDef))
                and ast.get_docstring(knoten)):
            knoten.body = knoten.body[1:]
    code = ast.unparse(baum)
    assert "ml_weight" not in code
    assert "custom_factors" not in code
