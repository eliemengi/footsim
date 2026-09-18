"""
Tests der gedaempften Ligastaerke (V2-C16).

WORUM ES GEHT
V2-C15 bestand zehn von elf Gates. Gescheitert ist eines, knapp:
`home_origin_league:PD` mit +0,01186 gegen eine Grenze von 0,01.

Der schaerfste Test dieses Blocks ist deshalb nicht die Messung,
sondern der Nachweis, dass C16 KEINE spanische Ausnahme ist: Die
Daempfung wirkt auf jede Liga mit demselben gamma, und das PD-Segment
entsteht aus derselben generischen Formel wie jedes andere.
"""

import ast
import json
import math
import pathlib
import random

import pytest

from src.features import league_strength as ls
from src.ml import c16_damped_league_strength as c16
from src.ml import c16_release as c16rel
from src.ml import cl_evaluate as ce

WURZEL = pathlib.Path(__file__).resolve().parents[1]

VERTRAG_FINGERABDRUCK = (
    "f6ce4b94e097015744d7a686314dcd6db3ce14359552a6b5864c773d24c5eb40")


# ===========================================================================
# 1  Der Vertrag
# ===========================================================================

def test_der_vertrag_steht_ohne_eine_einzige_messung():
    vertrag = c16.evaluation_contract()
    for pflicht in ("candidate", "controls", "damping", "alpha_selection",
                    "league_strength", "bound_contracts", "inventories",
                    "folds", "prediction_cutoff", "metrics", "bootstrap",
                    "segments", "calibration", "thresholds", "gates"):
        assert pflicht in vertrag, pflicht
    text = json.dumps(vertrag, ensure_ascii=False)
    for ergebnis in ("ci_high", "ci_low", "measured_values",
                     "result_fingerprint"):
        assert ergebnis not in text, ergebnis


def test_der_vertragsfingerabdruck_ist_der_gemessene():
    assert c16.contract_fingerprint() == VERTRAG_FINGERABDRUCK
    assert c16.contract_fingerprint() == c16.contract_fingerprint()


def test_die_vertragsdatei_liegt_vor_und_traegt_kein_ergebnis():
    pfad = WURZEL / c16.CONTRACT_PATH
    assert pfad.is_file()
    dokument = json.loads(pfad.read_text(encoding="utf-8"))
    assert dokument["frozen_before_measurement"] is True
    assert dokument["contract_fingerprint"] == VERTRAG_FINGERABDRUCK
    assert "decision" not in dokument and "measurement" not in dokument


def test_eine_aenderung_am_gammagitter_aendert_den_fingerabdruck(
        monkeypatch):
    vorher = c16.contract_fingerprint()
    monkeypatch.setattr(ls, "GAMMA_GRID", (0.1, 0.9))
    assert c16.contract_fingerprint() != vorher


def test_eine_aenderung_der_inneren_auswahlregel_aendert_ihn(monkeypatch):
    vorher = c16.contract_fingerprint()
    monkeypatch.setattr(ls, "GAMMA_TOLERANCE", 0.5)
    assert c16.contract_fingerprint() != vorher


def test_eine_gateaenderung_aendert_den_fingerabdruck(monkeypatch):
    vorher = c16.contract_fingerprint()
    monkeypatch.setattr(ce, "SEVERE_DEGRADATION", 0.5)
    assert c16.contract_fingerprint() != vorher


def test_der_registryzustand_bewegt_den_vertrag_nicht(monkeypatch):
    from src.ml import model_registry as mr

    vorher = c16.contract_fingerprint()
    monkeypatch.setattr(
        mr, "load_registry",
        lambda *a, **k: {"schema_version": 1,
                         "models": [{"model_id": "clm-erfunden"}]})
    assert c16.contract_fingerprint() == vorher


def test_ein_fremdes_ergebnis_wird_zurueckgewiesen():
    with pytest.raises(c16.ContractViolation):
        c16.assert_contract_matches({"contract_fingerprint": "falsch"})
    with pytest.raises(c16.ContractViolation):
        c16.assert_contract_matches({})
    assert c16.assert_contract_matches(
        {"contract_fingerprint": c16.contract_fingerprint()}) is True


def test_fluechtige_felder_beeinflussen_den_fingerabdruck_nicht():
    pfad = WURZEL / c16.ARTIFACT_PATH
    if not pfad.is_file():
        pytest.skip("C16 wurde noch nicht ausgefuehrt")
    artefakt = json.loads(pfad.read_text(encoding="utf-8"))
    veraendert = dict(artefakt, created_at="1999-01-01T00:00:00+00:00",
                      git_commit="abc123")
    assert (c16.result_fingerprint(veraendert)
            == c16.result_fingerprint(artefakt)
            == artefakt["result_fingerprint"])


def test_die_schwellen_stammen_aus_frueheren_vertraegen():
    from src.ml import c8_ablation as c8

    s = c16.evaluation_contract()["thresholds"]
    assert s["severe_degradation"] == ce.SEVERE_DEGRADATION == 0.01
    assert s["min_reliable_n"] == ce.MIN_RELIABLE_N
    assert s["max_secondary_degradation"] == c8.MAX_SECONDARY_DEGRADATION
    assert (s["max_calibration_degradation"]
            == c8.MAX_CALIBRATION_DEGRADATION)


def test_die_segmentgrenze_bleibt_unveraendert():
    """
    Die Grenze von 0,01 ist der Grund, warum C15 scheiterte. Sie zu
    lockern waere die bequemste Art, C16 bestehen zu lassen.
    """
    assert ce.SEVERE_DEGRADATION == 0.01
    vertrag = c16.evaluation_contract()
    assert "nicht gelockert" in vertrag["no_gate_change"]
    assert "0,01" in vertrag["no_gate_change"]


# ===========================================================================
# 2  Keine ligaspezifische Sonderregel
# ===========================================================================

def test_kein_ligacode_in_der_modelllogik():
    """
    DER KERNTEST DIESES BLOCKS.

    Eine Sonderregel fuer PD waere keine Regel, sondern eine
    Anpassung an genau den Test, der sie ausgeloest hat.
    """
    quelle = (WURZEL / "src" / "features" / "league_strength.py").read_text(
        encoding="utf-8")
    for verboten in ('"PD"', "'PD'", '"BL1"', '"PL"', '"SA"', '"FL1"',
                     "spanien", "spain", "laliga"):
        assert verboten.lower() not in quelle.lower(), verboten


def test_keine_vereinsnamen_in_der_modelllogik():
    quelle = (WURZEL / "src" / "features" / "league_strength.py").read_text(
        encoding="utf-8")
    baum = ast.parse(quelle)
    for knoten in ast.walk(baum):
        if (isinstance(knoten, (ast.Module, ast.ClassDef, ast.FunctionDef))
                and ast.get_docstring(knoten)):
            knoten.body = knoten.body[1:]
    code = ast.unparse(baum).lower()
    for name in ("real madrid", "barcelona", "bayern", "arsenal", "ajax",
                 "atletico", "sevilla"):
        assert name not in code, name


def test_gamma_wirkt_auf_jede_liga_gleich():
    """
    Die Daempfung ist EIN Wert fuer alle. Ein ligaspezifisches gamma
    waere genau die Sonderregel, die C16 vermeiden soll.
    """
    staerke = ls.LeagueStrength({"PD": 0.4, "NL1": 0.4},
                                {"PD": 0.0, "NL1": 0.0})
    for gamma in ls.GAMMA_GRID:
        gedaempft = staerke.with_gamma(gamma)
        pd_faktor, _ = gedaempft.factors("PD", "XX1")
        nl_faktor, _ = gedaempft.factors("NL1", "XX1")
        assert pd_faktor == nl_faktor, (
            "gleiche Parameter muessen gleiche Faktoren ergeben")
        assert gedaempft.gamma == gamma


def test_das_pd_verhalten_folgt_derselben_formel_wie_jede_liga():
    """
    Der ausdrueckliche Nachweis aus dem C16-Auftrag.

    Zwei Ligen mit identischen Parametern bekommen identische
    Faktoren, und PD wird an keiner Stelle anders behandelt. Waere es
    anders, entstuende das PD-Ergebnis aus einer Sonderregel statt aus
    der generischen Formel.
    """
    staerke = ls.LeagueStrength({"PD": 0.3, "ZZ9": 0.3},
                                {"PD": -0.2, "ZZ9": -0.2}, gamma=0.75)

    # Beide Rollen, beide Seiten, gegen denselben Gegner.
    assert staerke.factors("PD", "PL") == staerke.factors("ZZ9", "PL")
    assert staerke.factors("PL", "PD") == staerke.factors("PL", "ZZ9")

    # Und der Wert folgt exakt exp(gamma * (a + d)).
    a, d = 0.3, -0.2
    erwartet = math.exp(0.75 * (a + d))
    heim, _ = staerke.factors("PD", "ZZ9")
    assert heim == pytest.approx(erwartet)


def test_kein_routing_nach_testsegment():
    """
    Kein Codepfad darf anhand eines Segmentnamens entscheiden, ob
    korrigiert wird.
    """
    for datei in ("src/features/league_strength.py",
                  "src/ml/c16_damped_league_strength.py"):
        quelle = (WURZEL / datei).read_text(encoding="utf-8")
        baum = ast.parse(quelle)
        for knoten in ast.walk(baum):
            if isinstance(knoten, ast.If):
                text = ast.unparse(knoten.test)
                assert "origin:" not in text, datei
                assert "home_origin_league" not in text, datei


# ===========================================================================
# 3  Die Daempfung
# ===========================================================================

def test_gamma_eins_ist_exakt_c15():
    """
    C15 liegt im Kandidatenraum und kann gewinnen. Waere es das
    nicht, waere C16 kein fairer Vergleich, sondern eine erzwungene
    Aenderung.
    """
    staerke = ls.LeagueStrength({"A": 0.3}, {"B": 0.1})
    ungedaempft = ls.LeagueStrength({"A": 0.3}, {"B": 0.1})
    assert staerke.with_gamma(1.0).factors("A", "B") == (
        ungedaempft.factors("A", "B"))
    assert 1.0 in ls.GAMMA_GRID


def test_kleineres_gamma_daempft_staerker():
    staerke = ls.LeagueStrength({"A": 0.4}, {"B": 0.2})
    werte = [staerke.with_gamma(g).factors("A", "B")[0]
             for g in (0.25, 0.5, 0.75, 1.0)]
    assert werte == sorted(werte), "kleineres Gamma muss naeher an 1 liegen"
    assert all(w > 1.0 for w in werte)


def test_gamma_gegen_null_hebt_die_korrektur_auf():
    staerke = ls.LeagueStrength({"A": 0.9}, {"B": 0.9}, gamma=1e-9)
    heim, gast = staerke.factors("A", "B")
    assert heim == pytest.approx(1.0)
    assert gast == pytest.approx(1.0)


def test_das_gammagitter_ist_eingefroren():
    assert ls.GAMMA_GRID == (0.25, 0.50, 0.75, 1.00)
    assert all(0 < g <= 1 for g in ls.GAMMA_GRID)
    vertrag = c16.evaluation_contract()
    assert vertrag["damping"]["grid"] == list(ls.GAMMA_GRID)


def test_der_tie_breaker_waehlt_das_kleinere_gamma():
    """
    Bei Gleichstand gewinnt die vorsichtigere Wahl. Ohne feste Regel
    haenge das Ergebnis am Gleitkommarauschen.
    """
    # Eine Staerke ohne Parameter liefert fuer jedes Gamma denselben
    # Faktor 1 und damit dieselbe Devianz.
    staerke = ls.LeagueStrength({}, {})
    zeilen = [{"home_id": 1, "away_id": 2, "home_goals": 1,
               "away_goals": 1} for _ in range(40)]
    lambdas = [(1.2, 1.1)] * 40
    gamma, protokoll = ls.select_gamma(staerke, zeilen, lambdas,
                                       {1: "A", 2: "B"})
    assert gamma == min(ls.GAMMA_GRID)
    assert "kleineres Gamma" in protokoll["tie_break"]


def test_die_grenzen_greifen_nach_der_daempfung():
    staerke = ls.LeagueStrength({"A": 9.0}, {"B": 9.0}, gamma=1.0)
    heim, _ = staerke.factors("A", "B")
    assert heim == ls.FACTOR_MAX
    gedaempft = staerke.with_gamma(0.25)
    heim2, _ = gedaempft.factors("A", "B")
    assert heim2 == ls.FACTOR_MAX, "auch gedaempft bleibt die Grenze"


def test_cold_start_bleibt_endlich_und_neutral():
    for gamma in ls.GAMMA_GRID:
        staerke = ls.LeagueStrength({"PL": 0.4}, {"PL": -0.1}, gamma=gamma)
        heim, gast = staerke.factors("XX1", "YY1")
        assert heim == 1.0 and gast == 1.0
        assert math.isfinite(heim) and math.isfinite(gast)
        assert staerke.is_cold_start("XX1")


def test_eine_unbekannte_liga_bekommt_keinen_bonus():
    staerke = ls.LeagueStrength({"PL": 0.3}, {"PL": -0.1}, gamma=0.5)
    heim, gast = staerke.factors("PL", "XX1")
    assert heim == pytest.approx(math.exp(0.5 * 0.3))
    assert gast == pytest.approx(math.exp(0.5 * -0.1))
    assert gast < 1.0


# ===========================================================================
# 4  Daten, Folds, PIT und Leakage
# ===========================================================================

@pytest.fixture(scope="module")
def alle_zeilen():
    from src.ml import dataset as ds

    zeilen, _ = ds.build_dataset(include_cl=True)
    return zeilen


@pytest.fixture(scope="module")
def ligakarte():
    from src.ml import c14_reevaluation as c14

    return c14.team_league_map()


def test_die_bestandsgroessen_entsprechen_dem_vertrag(alle_zeilen):
    vertrag = c16.evaluation_contract()
    standard = []
    for fold in ce.OUTER_FOLDS:
        standard += ce.cl_rows(alle_zeilen, fold["test_season"])
    kontext = []
    for fold in ce.CONTEXT_FOLDS:
        kontext += ce.context_rows(alle_zeilen, [fold["test_season"]])
    assert len(standard) == vertrag["inventories"]["standard"][
        "expected_rows"] == 283
    assert len(kontext) == vertrag["inventories"]["context"][
        "expected_rows"] == 373


def test_alle_vier_kandidaten_bewerten_dieselben_partien(alle_zeilen,
                                                         ligakarte):
    fold = ce.OUTER_FOLDS[0]
    e = c16.evaluate_fold(alle_zeilen, fold, ligakarte)
    assert (e["v0"]["n"] == e["c14"]["n"] == e["c15"]["n"]
            == e["c16"]["n"] == e["test_rows"])


@pytest.mark.parametrize("fold_index", [0, 1])
def test_ein_testergebnis_veraendert_gamma_nicht(alle_zeilen, ligakarte,
                                                 fold_index):
    """
    DER SCHARFE MANIPULATIONSTEST FUER DEN NEUEN FREIHEITSGRAD.

    Gamma ist der einzige neue Parameter. Wuerde er sich mit den
    Testergebnissen bewegen, waere er auf dem Testfold gewaehlt.
    """
    fold = ce.OUTER_FOLDS[fold_index]
    original = c16.evaluate_fold(alle_zeilen, fold, ligakarte)

    test_ids = {z["row_id"]
                for z in ce.cl_rows(alle_zeilen, fold["test_season"])}
    manipuliert = [
        (dict(z, home_goals=9, away_goals=0, outcome=0)
         if z["row_id"] in test_ids else z)
        for z in alle_zeilen]
    danach = c16.evaluate_fold(manipuliert, fold, ligakarte)

    assert original["gamma"] == danach["gamma"]
    assert original["league_alpha"] == danach["league_alpha"]
    assert (original["parameter_fingerprint"]
            == danach["parameter_fingerprint"])


@pytest.mark.parametrize("fold_index", [0, 1])
def test_ein_historienergebnis_veraendert_die_parameter_sehr_wohl(
        alle_zeilen, ligakarte, fold_index):
    """Die Gegenprobe. Ohne sie waere der Test oben trivial erfuellbar."""
    from src.ml import c15_league_strength as c15

    fold = ce.OUTER_FOLDS[fold_index]
    original = c16.evaluate_fold(alle_zeilen, fold, ligakarte)

    hist_ids = {z["row_id"] for z
                in c15.league_history(alle_zeilen, fold["train_seasons"])}
    manipuliert = [
        (dict(z, home_goals=9, away_goals=0, outcome=0)
         if z["row_id"] in hist_ids else z)
        for z in alle_zeilen]
    danach = c16.evaluate_fold(manipuliert, fold, ligakarte)
    assert (original["parameter_fingerprint"]
            != danach["parameter_fingerprint"])


def test_die_zeilenreihenfolge_veraendert_nichts(alle_zeilen, ligakarte):
    fold = ce.OUTER_FOLDS[0]
    a = c16.evaluate_fold(alle_zeilen, fold, ligakarte)
    gemischt = list(alle_zeilen)
    random.Random(23).shuffle(gemischt)
    b = c16.evaluate_fold(gemischt, fold, ligakarte)
    assert a["parameter_fingerprint"] == b["parameter_fingerprint"]
    assert a["c16"]["log_loss"] == b["c16"]["log_loss"]
    assert a["gamma"] == b["gamma"]


def test_zwei_laeufe_liefern_dasselbe(alle_zeilen, ligakarte):
    fold = ce.OUTER_FOLDS[0]
    a = c16.evaluate_fold(alle_zeilen, fold, ligakarte)
    b = c16.evaluate_fold(alle_zeilen, fold, ligakarte)
    assert a["parameter_fingerprint"] == b["parameter_fingerprint"]
    assert a["c16"]["log_loss"] == b["c16"]["log_loss"]


def test_keine_testpartie_in_training_oder_innerer_validierung(
        alle_zeilen):
    from src.ml import c15_league_strength as c15

    for fold in ce.OUTER_FOLDS:
        test_ids = {z["row_id"]
                    for z in ce.cl_rows(alle_zeilen, fold["test_season"])}
        historie = c15.league_history(alle_zeilen, fold["train_seasons"])
        frueh, spaet, _ = c15._innere_teilung(historie,
                                              fold["train_seasons"])
        assert not ({z["row_id"] for z in historie} & test_ids)
        assert not ({z["row_id"] for z in frueh} & test_ids)
        assert not ({z["row_id"] for z in spaet} & test_ids)
        assert max(z["date"] for z in frueh) <= min(z["date"]
                                                    for z in spaet)


def test_der_c10_stichtag_bleibt_unveraendert():
    from src.features import prediction_cutoff as pc

    assert pc.CUTOFF_HOUR == 12
    assert pc.CUTOFF_INCLUSIVE is False
    assert pc.assert_hours_match() is True
    vertrag = c16.evaluation_contract()["prediction_cutoff"]
    assert vertrag["hour"] == 12 and vertrag["inclusive"] is False


def test_c16_braucht_kein_netz_und_keine_env():
    for datei in ("src/features/league_strength.py",
                  "src/ml/c16_damped_league_strength.py"):
        baum = ast.parse((WURZEL / datei).read_text(encoding="utf-8"))
        for knoten in ast.walk(baum):
            if (isinstance(knoten, (ast.Module, ast.ClassDef,
                                    ast.FunctionDef))
                    and ast.get_docstring(knoten)):
                knoten.body = knoten.body[1:]
        code = ast.unparse(baum)
        for verboten in ("requests", "urllib", "socket", "httpx",
                         "dotenv", "snapshot_reader", "uefa_"):
            assert verboten not in code, "%s: %s" % (datei, verboten)


def test_das_c9_schema_bleibt_unveraendert():
    from src.ml import early_v2 as e9

    assert e9.schema_fingerprint() == (
        "475b9be82c21c7ea977d71db1a714e3bc37fd4be2336897285730bc116694aa5")
    assert c16.schema_fingerprint() != e9.schema_fingerprint()


def test_das_c15_schema_bleibt_unveraendert():
    from src.ml import c15_league_strength as c15

    assert c15.contract_fingerprint() == (
        "c1a155fbf48c07f0e3f27bac0110f8032933c98be82e57c406307b6cde8f14b8")
    assert c15.schema_fingerprint() == (
        "0bbb0f161cc259fe439daef32163c89c40a88af2628ce9c7c36e820d234099c2")
    assert c16.schema_fingerprint() != c15.schema_fingerprint()


# ===========================================================================
# 5  Entscheidungen
# ===========================================================================

def _messung(delta=-0.088, ci_low=-0.119, ci_high=-0.055,
             folds=(-0.066, -0.110), schaden=(), kontext_delta=-0.072,
             n=283, brier=-0.063, rps=-0.030,
             kalib_basis=0.043, kalib_ml=0.045):
    return {
        "standard": {
            "aggregate": {
                "n": n, "delta_log_loss": delta,
                "delta_brier": brier, "delta_rps": rps,
                "bootstrap": {"log_loss": {"ci_low": ci_low,
                                           "ci_high": ci_high}},
                "baseline": {"calibration_error": kalib_basis},
                "ml": {"calibration_error": kalib_ml},
                "c16_vs_c14": {"delta_log_loss": -0.076},
                "c16_vs_c15": {"delta_log_loss": +0.0076},
            },
            "folds": [{"fold": "f%d" % i, "delta_log_loss": d}
                      for i, d in enumerate(folds)],
            "distinct_damage": list(schaden),
        },
        "context": {"aggregate": {"delta_log_loss": kontext_delta}},
    }


def test_der_gemessene_fall_wird_akzeptiert():
    urteil = c16.decide(_messung())
    assert urteil["verdict"] == c16.VERDICT_ACCEPTED
    assert all(urteil["conditions"].values())
    assert urteil["failed_conditions"] == []
    assert urteil["acceptance_class"] == c16.ACCEPTANCE_CLASS_DEVELOPMENT


def test_ein_schweres_segment_verhindert_die_freigabe():
    """Genau der C15-Fall. Er muss weiterhin blockieren."""
    urteil = c16.decide(_messung(schaden=("home_origin_league:PD",)))
    assert urteil["verdict"] == c16.VERDICT_REJECTED
    assert urteil["conditions"]["no_severe_segment_damage"] is False


def test_ein_eingeschlossenes_nullintervall_gibt_hoechstens_schatten():
    urteil = c16.decide(_messung(ci_high=+0.004))
    assert urteil["verdict"] == c16.VERDICT_PROVISIONAL_SHADOW


def test_widersprechende_folds_fuehren_zur_ablehnung():
    urteil = c16.decide(_messung(folds=(-0.11, +0.01)))
    assert urteil["verdict"] == c16.VERDICT_REJECTED


def test_ein_beschaedigter_kontextbestand_verhindert_accepted():
    urteil = c16.decide(_messung(kontext_delta=+0.02))
    assert urteil["verdict"] == c16.VERDICT_REJECTED


def test_zu_wenige_daten_sind_nicht_auswertbar():
    assert c16.decide(_messung(n=10))["verdict"] == (
        c16.VERDICT_NOT_EVALUABLE)


def test_eine_einbrechende_kalibrierung_verhindert_accepted():
    urteil = c16.decide(_messung(kalib_basis=0.03, kalib_ml=0.09))
    assert urteil["conditions"]["calibration_holds"] is False
    assert urteil["verdict"] != c16.VERDICT_ACCEPTED


def test_jede_fehlgeschlagene_bedingung_erscheint_in_den_gruenden():
    urteil = c16.decide(_messung(folds=(-0.1799, -0.0001), delta=-0.09,
                                 ci_high=+0.01))
    fehlgeschlagen = urteil["failed_conditions"]
    assert fehlgeschlagen
    assert len(urteil["reasons"]) == len(fehlgeschlagen)
    for name in fehlgeschlagen:
        assert any(c16.REASON_TEXTS[name] in grund
                   for grund in urteil["reasons"]), name


def test_jede_bedingung_hat_einen_grundtext():
    for name in c16.decide(_messung())["conditions"]:
        assert name in c16.REASON_TEXTS, name


def test_ein_ergebnis_kann_die_gates_nicht_ueberschreiben():
    messung = _messung(delta=+0.05, ci_low=+0.01, ci_high=+0.09)
    messung["verdict"] = c16.VERDICT_ACCEPTED
    messung["conditions"] = {"primary_better": True}
    urteil = c16.decide(messung)
    assert urteil["verdict"] == c16.VERDICT_REJECTED
    assert urteil["conditions"]["primary_better"] is False


def test_es_gibt_genau_vier_urteile():
    assert len(c16.VERDICTS) == 4
    vertrag = c16.evaluation_contract()
    assert "fuenfte Klasse" in vertrag["gates"]["no_new_verdict_class"]


def test_jedes_urteil_traegt_den_vertragsfingerabdruck():
    for messung in (_messung(), _messung(delta=+0.1), _messung(n=5)):
        assert (c16.decide(messung)["contract_fingerprint"]
                == VERTRAG_FINGERABDRUCK)


# ===========================================================================
# 6  Das Ergebnisartefakt
# ===========================================================================

@pytest.fixture(scope="module")
def artefakt():
    pfad = WURZEL / c16.ARTIFACT_PATH
    if not pfad.is_file():
        pytest.skip("C16 wurde noch nicht ausgefuehrt")
    return json.loads(pfad.read_text(encoding="utf-8"))


def test_das_artefakt_bindet_alle_vertraege(artefakt):
    from src.ml import c13_contract as c13
    from src.ml import c14_reevaluation as c14
    from src.ml import c15_league_strength as c15
    from src.ml import early_v2 as e9

    assert artefakt["contract_fingerprint"] == VERTRAG_FINGERABDRUCK
    assert artefakt["contract_frozen_before_measurement"] is True
    g = artefakt["bound_contracts"]
    assert g["c9_schema_fingerprint"] == e9.schema_fingerprint()
    assert g["c13_contract_fingerprint"] == c13.contract_fingerprint()
    assert g["c14_contract_fingerprint"] == c14.contract_fingerprint()
    assert g["c15_contract_fingerprint"] == c15.contract_fingerprint()
    assert artefakt["verdict"] in c16.VERDICTS


def test_das_artefakt_nennt_gamma_je_fold(artefakt):
    for fold in artefakt["measurement"]["standard"]["folds"]:
        assert fold["gamma"] in ls.GAMMA_GRID
        assert fold["league_alpha"] is not None
        assert fold["gamma_selection"]["candidates"]
        assert fold["parameter_fingerprint"]


def test_das_artefakt_enthaelt_keine_geheimnisse_und_keine_pfade(artefakt):
    text = json.dumps(artefakt, ensure_ascii=False)
    for verboten in ("C:\\\\", "/home/", "Users\\\\", "api_key",
                     "APISPORTS_KEY", "secret", "password", "Bearer"):
        assert verboten.lower() not in text.lower(), verboten


def test_das_artefakt_hat_die_registry_nicht_veraendert(artefakt):
    assert artefakt["registry"]["changed_by_evaluation"] is False


def test_das_artefakt_nennt_das_fehlende_holdout(artefakt):
    grenzen = " ".join(artefakt["known_limits"]).lower()
    assert "holdout" in grenzen
    assert "2026/27" in " ".join(artefakt["known_limits"])


# ===========================================================================
# 7  Der Freigabeweg
# ===========================================================================

def test_der_freigabeweg_traegt_das_zweistufige_bundle(tmp_path):
    """
    GEAENDERT IN V2-C17.

    In C16 scheiterte dieser Weg fail-closed, weil der Bundlevertrag
    aus V2-C0B kein zweistufiges Modell kannte. Das war richtig: Drei
    Schranken gleichzeitig aufzuweichen waere die Umgehung gewesen,
    gegen die V2-C11 und V2-C15 gebaut wurden.

    V2-C17 hat den Vertrag ausdruecklich erweitert - namentlich, nicht
    generisch. Der Weg traegt jetzt, und der Trockenlauf laesst die
    Registry unangetastet.

    GEAENDERT IN V2-C20: ISOLIERT.

    Bis hierher lief dieser Trockenlauf gegen das echte Repository. Der
    Freigabeweg schreibt das Bundle aber auch im Trockenlauf - das ist
    gewollt, weil die Registryvalidierung die Datei und ihren Hash
    braucht. Die Folge: Jeder Testlauf legte ein nicht registriertes
    Bundle in das echte Modellverzeichnis, waehrend der Test
    `wrote_anything is False` pruefte. Beides stimmte, nur meinte
    `wrote_anything` Registry und Zustand, nicht die Platte.

    Jetzt laeuft der Weg in einem temporaeren Wurzelverzeichnis mit
    einer Kopie der Registry, ihrer Bundles und des Ergebnisses. Und es
    wird ausdruecklich geprueft, dass im echten Modellverzeichnis keine
    Datei hinzukommt.

    GEAENDERT IN V2-C22: Der Freigabeweg verlangt zusaetzlich die
    C21-Saisonfreigabe. Die Kopie entsteht deshalb ueber dieselbe
    Funktion wie die Release-Probe (`copy_release_state`), die auch
    C21-Vertrag und -Ergebnis mitnimmt.
    """
    import os

    from src.ml import c21_release_readiness as rr
    from src.ml import model_registry as mr

    echt_vorher = set(os.listdir("data/ml/models"))
    dokument = mr.load_registry()
    rr.copy_release_state(str(tmp_path))

    ergebnis = c16rel.release(dry_run=True, repo_root=str(tmp_path))
    assert ergebnis["status"] in ("dry_run_ok", "already_active"), (
        ergebnis.get("reason"))
    assert ergebnis["wrote_anything"] is False
    assert ergebnis["model_id"] == "clm-936ecce472696ccb-ls1c4f4e1d"

    # Das Bundle liegt im temporaeren Verzeichnis, nicht im echten.
    assert (tmp_path / "data" / "ml" / "models"
            / ("%s.json" % ergebnis["model_id"])).is_file()
    assert set(os.listdir("data/ml/models")) == echt_vorher
    # Und die echte Registry ist unberuehrt.
    assert mr.registry_fingerprint(mr.load_registry()) ==         mr.registry_fingerprint(dokument)


def test_die_evaluation_selbst_veraendert_die_registry_nicht():
    """
    GEAENDERT IN V2-C17.

    Die Evaluation aktiviert weiterhin nichts - das steht im
    Artefakt und wird darunter geprueft. Aktiviert wird
    ausschliesslich ueber den ausdruecklichen Freigabeweg, und
    genau das ist in C17 geschehen.
    """
    from src.ml import model_registry as mr

    assert mr.shadow_entries() == []
    eintrag, _ = mr.active_entry()
    if eintrag is not None:
        assert eintrag.get("approval"), (
            "ein aktives Modell ohne Freigabe waere ein Befund")


def test_der_freigabeweg_verweigert_ohne_accepted(monkeypatch, tmp_path):
    """
    Ohne accepted passiert nichts - unabhaengig vom Bundlevertrag.

    Seit V2-C20 liest der Freigabeweg das Ergebnis unter dem geltenden
    Zuordnungsvertrag; das abgelehnte Ergebnis liegt deshalb dort.
    """
    from src.ml import c20_temporal_map as c20

    pfad = tmp_path / c20.EVALUATION_PATH
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps({"decision": {"verdict": "rejected"}}),
                    encoding="utf-8")
    ergebnis = c16rel.release(dry_run=True, repo_root=str(tmp_path))
    assert ergebnis["status"] == "refused"
    assert "accepted" in ergebnis["reason"]


def test_der_freigabeweg_verweigert_ein_ergebnis_ohne_vertragsbindung(
        tmp_path):
    """
    V2-C20: Ein accepted-Urteil genuegt nicht. Es muss unter dem
    Zuordnungsvertrag entstanden sein, den das Bundle tragen wird.
    Genau das fehlte dem C16-Ergebnis: Es wurde mit einer unbegrenzten
    Karte gemessen. Liegt es am Platz des C20-Ergebnisses, wird es
    abgewiesen statt uebernommen.
    """
    import shutil

    from src.ml import c20_temporal_map as c20

    ziel = tmp_path / c20.EVALUATION_PATH
    ziel.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(c16.ARTIFACT_PATH, ziel)

    ergebnis = c16rel.release(dry_run=True, repo_root=str(tmp_path))
    assert ergebnis["status"] == "refused"
    assert "Zuordnungsvertrag" in ergebnis["reason"]


def test_die_vorpruefung_blockiert_ein_bundle_ohne_zweite_stufe(tmp_path):
    """
    Ein C15-Bundle mit C16-Etikett waere ein halbes Modell. Die
    Vorpruefung muss das erkennen.
    """
    from src.ml import model_registry as mr

    verzeichnis = tmp_path / "data" / "ml" / "models"
    verzeichnis.mkdir(parents=True, exist_ok=True)
    bundle_datei = verzeichnis / "clm-halb.json"
    bundle_datei.write_text(json.dumps({"model_id": "clm-halb",
                                        "schema_version": 3}),
                            encoding="utf-8")

    eintrag = {
        "model_id": "clm-halb",
        "bundle_path": "data/ml/models/clm-halb.json",
        "bundle_sha256": mr.bundle_sha256(str(bundle_datei)),
        "feature_schema_fingerprint": c16.schema_fingerprint(),
        "stage": mr.STAGE_CANDIDATE,
    }
    dokument = mr.empty_registry()
    dokument["models"] = [eintrag]
    urteil = c16.decide(_messung())

    ok, befunde = c16rel.preflight(urteil, eintrag,
                                   eintrag["bundle_path"], str(tmp_path),
                                   dokument)
    assert ok is False
    assert any("zweite Stufe" in b for b in befunde)


# ===========================================================================
# 8  Runtime
# ===========================================================================

def test_die_runtime_wendet_die_ligastaerke_nur_mit_bundleblock_an():
    """
    Ein Bundle ohne `league_strength` rechnet Bit fuer Bit wie zuvor.
    Damit kann die zweite Stufe kein aelteres Modell veraendern.
    """
    from src.ml import inference as inf

    heim, gast, diagnose = inf._ligastaerke_anwenden(
        {"attack": {"PL": 0.4}, "defence": {"NL1": 0.1}, "gamma": 0.75,
         "team_leagues": {"57": "PL", "678": "NL1"}},
        {"team_id": 57}, {"team_id": 678}, 1.0, 1.0)
    assert diagnose["applied"] is True
    assert heim == pytest.approx(math.exp(0.75 * (0.4 + 0.1)))
    assert diagnose["home_league"] == "PL"


def test_die_runtime_bleibt_neutral_bei_unbekannter_liga():
    from src.ml import inference as inf

    heim, gast, diagnose = inf._ligastaerke_anwenden(
        {"attack": {"PL": 0.4}, "defence": {}, "gamma": 1.0,
         "team_leagues": {"57": "PL"}},
        {"team_id": 57}, {"team_id": 99999}, 1.0, 1.0)
    assert diagnose["applied"] is False
    assert diagnose["reason"] == "league_unknown"
    assert (heim, gast) == (1.0, 1.0)


def test_die_runtime_bleibt_neutral_ohne_team_id():
    from src.ml import inference as inf

    heim, gast, diagnose = inf._ligastaerke_anwenden(
        {"attack": {"PL": 0.4}, "defence": {}, "gamma": 1.0,
         "team_leagues": {"57": "PL"}},
        {}, {}, 1.2, 0.9)
    assert diagnose["applied"] is False
    assert (heim, gast) == (1.2, 0.9)


def test_der_registrygate_bleibt_der_entscheider():
    """
    GEAENDERT IN V2-C17, siehe oben. Der Gate bleibt, sein Ergebnis
    hat sich geaendert.
    """
    from src.ml import model_registry as mr
    from src.ml import runtime

    assert hasattr(runtime, "REASON_NOT_ACTIVE_IN_REGISTRY")
    eintrag, grund = mr.active_entry()
    if eintrag is None:
        assert grund == "no_active_model"
    else:
        assert eintrag["evaluation_status"] == mr.EVALUATION_ACCEPTED


def test_die_ligasimulation_kennt_weiterhin_kein_ml():
    quelle = (WURZEL / "src" / "predict" / "league_match_sim.py").read_text(
        encoding="utf-8")
    assert "src.ml" not in quelle
