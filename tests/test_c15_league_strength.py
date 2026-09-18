"""
Tests der Ligastaerke und des Freigabewegs (V2-C15).

WORUM ES GEHT
V2-C14 lehnte ab, weil ein grosses Segment schwer beschaedigt war:
Vereine aus Top-5-Ligen zu Hause gegen Vereine ausserhalb der Top 5.
Die Ursache war belegt: Die 16 Merkmale sind Verhaeltniswerte zur
eigenen Liga, und eine Liga zu beherrschen sieht darin aus wie
Weltklasse.

Der schaerfste Teil dieser Tests ist nicht die Messung. Es sind zwei
Beweise:

  1. Die Ligastaerke ist aus frueheren CL-Partien lernbar und aus
     nationalen Spielen NICHT. Waere das falsch, waere die zweite
     Stufe ein totes Merkmal.

  2. Kein Testergebnis beeinflusst die Parameter, aus denen seine
     eigene Vorhersage entsteht.
"""

import ast
import copy
import json
import pathlib

import pytest

from src.features import league_strength as ls
from src.ml import c15_league_strength as c15
from src.ml import c15_release as rel
from src.ml import cl_evaluate as ce
from src.ml import feature_groups as fg
from src.ml import model_registry as mr

WURZEL = pathlib.Path(__file__).resolve().parents[1]

VERTRAG_FINGERABDRUCK = (
    "c1a155fbf48c07f0e3f27bac0110f8032933c98be82e57c406307b6cde8f14b8")


# ===========================================================================
# 1  Der Vertrag
# ===========================================================================

def test_der_vertrag_steht_ohne_eine_einzige_messung():
    vertrag = c15.evaluation_contract()
    for pflicht in ("candidate", "controls", "league_strength",
                    "bound_contracts", "inventories", "folds", "metrics",
                    "bootstrap", "segments", "calibration", "thresholds",
                    "gates"):
        assert pflicht in vertrag, pflicht
    text = json.dumps(vertrag, ensure_ascii=False)
    for ergebnis in ("ci_high", "ci_low", "measured_values",
                     "result_fingerprint"):
        assert ergebnis not in text, ergebnis


def test_der_vertragsfingerabdruck_ist_der_gemessene():
    assert c15.contract_fingerprint() == VERTRAG_FINGERABDRUCK
    assert c15.contract_fingerprint() == c15.contract_fingerprint()


def test_die_vertragsdatei_liegt_vor_und_traegt_kein_ergebnis():
    pfad = WURZEL / c15.CONTRACT_PATH
    assert pfad.is_file()
    dokument = json.loads(pfad.read_text(encoding="utf-8"))
    assert dokument["frozen_before_measurement"] is True
    assert dokument["contract_fingerprint"] == VERTRAG_FINGERABDRUCK
    assert "decision" not in dokument and "measurement" not in dokument


def test_eine_geaenderte_modellform_aendert_den_fingerabdruck(monkeypatch):
    vorher = c15.contract_fingerprint()
    monkeypatch.setattr(ls, "FACTOR_MAX", 9.9)
    assert c15.contract_fingerprint() != vorher


def test_eine_geaenderte_regularisierung_aendert_den_fingerabdruck(
        monkeypatch):
    from src.ml import model as mdl

    vorher = c15.contract_fingerprint()
    monkeypatch.setattr(mdl, "ALPHA_CANDIDATES", (0.5,))
    assert c15.contract_fingerprint() != vorher


def test_eine_geaenderte_segmentgroesse_aendert_den_fingerabdruck(
        monkeypatch):
    vorher = c15.contract_fingerprint()
    monkeypatch.setattr(c15, "SEGMENT_MIN_SIZE", 99)
    assert c15.contract_fingerprint() != vorher


def test_eine_geaenderte_schwelle_aendert_den_fingerabdruck(monkeypatch):
    vorher = c15.contract_fingerprint()
    monkeypatch.setattr(ce, "SEVERE_DEGRADATION", 0.5)
    assert c15.contract_fingerprint() != vorher


def test_der_registryzustand_bewegt_den_vertrag_nicht(monkeypatch):
    vorher = c15.contract_fingerprint()
    monkeypatch.setattr(
        mr, "load_registry",
        lambda *a, **k: {"schema_version": 1,
                         "models": [{"model_id": "clm-erfunden"}]})
    assert c15.contract_fingerprint() == vorher


def test_ein_fremdes_ergebnis_wird_zurueckgewiesen():
    with pytest.raises(c15.ContractViolation):
        c15.assert_contract_matches({"contract_fingerprint": "falsch"})
    with pytest.raises(c15.ContractViolation):
        c15.assert_contract_matches({})
    assert c15.assert_contract_matches(
        {"contract_fingerprint": c15.contract_fingerprint()}) is True


def test_die_schwellen_stammen_aus_frueheren_vertraegen():
    from src.ml import c8_ablation as c8

    s = c15.evaluation_contract()["thresholds"]
    assert s["severe_degradation"] == ce.SEVERE_DEGRADATION
    assert s["min_reliable_n"] == ce.MIN_RELIABLE_N
    assert s["max_secondary_degradation"] == c8.MAX_SECONDARY_DEGRADATION
    assert (s["max_calibration_degradation"]
            == c8.MAX_CALIBRATION_DEGRADATION)


def test_genau_ein_kandidat():
    """
    Mehrere Ligastaerkevarianten waeren verstecktes Modellshopping.
    """
    vertrag = c15.evaluation_contract()
    assert "genau einen" in vertrag["exactly_one_candidate"].lower()
    assert vertrag["candidate"]["name"] == fg.C15_CANDIDATE
    assert set(vertrag["controls"]) == {"v0", "c14_v2", "fairness"}


def test_das_c9_schema_bleibt_unveraendert():
    from src.ml import early_v2 as e9

    assert e9.schema_fingerprint() == (
        "475b9be82c21c7ea977d71db1a714e3bc37fd4be2336897285730bc116694aa5")
    assert c15.schema_fingerprint() != e9.schema_fingerprint()


def test_die_c15_gruppe_traegt_dieselben_spalten_aber_einen_eigenen_namen():
    """
    Die Ligastaerke ist eine Stufe, keine Spalte. Der eigene
    Schemafingerabdruck deckt trotzdem beides ab - sonst passte ein
    C14-Bundle zum C15-Modell, obwohl es etwas anderes rechnet.
    """
    assert (fg.columns_for(fg.C15_CANDIDATE)
            == fg.columns_for(fg.CL_PRIMARY_CANDIDATE))
    assert fg.C15_CANDIDATE != fg.CL_PRIMARY_CANDIDATE
    schema = c15.model_schema()
    assert len(schema["stages"]) == 2
    assert schema["stages"][1]["name"] == "league_strength"


# ===========================================================================
# 2  Die Modellform
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


def test_nationale_spiele_koennen_die_ligastaerke_nicht_lernen(
        alle_zeilen, ligakarte):
    """
    DER STRUKTURBEWEIS.

    In einem nationalen Ligaspiel stammen beide Mannschaften aus
    derselben Liga. Ein Ligastaerkemerkmal waere dort konstant und
    bekaeme kein Gewicht. Ohne diesen Nachweis waere die zweite Stufe
    moeglicherweise ein totes Merkmal.
    """
    national = ce.league_rows(alle_zeilen, [2023, 2024])
    assert national
    verschieden = [z for z in national
                   if (ligakarte.get(z.get("home_id"))
                       != ligakarte.get(z.get("away_id")))]
    assert verschieden == [], (
        "%d nationale Zeilen verbinden zwei Ligen" % len(verschieden))


def test_fruehere_cl_partien_koennen_sie_sehr_wohl_lernen(
        alle_zeilen, ligakarte):
    """Die Gegenprobe. Ohne sie waere der Test oben trivial erfuellbar."""
    for fold in ce.OUTER_FOLDS:
        historie = c15.league_history(alle_zeilen, fold["train_seasons"])
        assert historie
        verschieden = sum(
            1 for z in historie
            if (ligakarte.get(z.get("home_id"))
                and ligakarte.get(z.get("away_id"))
                and ligakarte.get(z.get("home_id"))
                != ligakarte.get(z.get("away_id"))))
        anteil = verschieden / len(historie)
        assert anteil >= 0.95, (fold["name"], anteil)


def test_die_entwurfsmatrix_hat_genau_ein_rangdefizit(alle_zeilen,
                                                     ligakarte):
    """
    Ohne Achsenabschnitt ist die Loesung nur bis auf eine Konstante
    bestimmt - man koennte auf alle Angriffswerte etwas addieren und
    es von allen Abwehrwerten abziehen. Genau EIN Defizit ist
    erwartet; mehr waere ein Modellfehler, weniger waere unmoeglich.
    """
    import numpy as np

    historie = c15.league_history(alle_zeilen,
                                  ce.OUTER_FOLDS[0]["train_seasons"])
    spalten, zeilen = set(), []
    for partie in historie:
        h = ligakarte.get(partie.get("home_id"))
        a = ligakarte.get(partie.get("away_id"))
        if not h or not a:
            continue
        for eigen, gegner in ((h, a), (a, h)):
            spalten.add("A:" + eigen)
            spalten.add("D:" + gegner)
            zeilen.append((eigen, gegner))
    spalten = sorted(spalten)
    index = {s: i for i, s in enumerate(spalten)}
    matrix = np.zeros((len(zeilen), len(spalten)))
    for i, (e, g) in enumerate(zeilen):
        matrix[i, index["A:" + e]] = 1
        matrix[i, index["D:" + g]] = 1
    assert len(spalten) - np.linalg.matrix_rank(matrix) == 1


def test_die_ligastaerke_hat_varianz():
    """Ein Parametersatz ohne Varianz waere eine teure Null."""
    zeilen = []
    for i in range(60):
        stark_heim = i % 2 == 0
        zeilen.append({
            "home_id": 1 if stark_heim else 2,
            "away_id": 2 if stark_heim else 1,
            "home_goals": 3 if stark_heim else 0,
            "away_goals": 0 if stark_heim else 3})
    lambdas = [(1.4, 1.1)] * len(zeilen)
    karte = {1: "STARK", 2: "SCHWACH"}
    staerke = ls.estimate(zeilen, lambdas, karte, alpha=0.01)
    assert staerke.diagnose["fitted"] is True
    assert staerke.attack["STARK"] > staerke.attack["SCHWACH"]


def test_cold_start_ist_neutral():
    staerke = ls.LeagueStrength({"PL": 0.3}, {"PL": -0.1})
    assert staerke.is_cold_start("XX1")
    assert staerke.factors("XX1", "YY1") == (1.0, 1.0)


def test_eine_unbekannte_liga_bekommt_keinen_bonus():
    """
    Der unbekannten Liga wird der neutrale Wert 0 zugeordnet, nicht
    ein guenstiger. Was auf sie wirkt, ist ausschliesslich die Staerke
    des BEKANNTEN Gegners.
    """
    staerke = ls.LeagueStrength({"PL": 0.3}, {"PL": -0.1})
    heim, gast = staerke.factors("PL", "XX1")
    import math

    assert heim == pytest.approx(math.exp(0.3))
    assert gast == pytest.approx(math.exp(-0.1))
    assert gast < 1.0, "die unbekannte Liga darf nicht bevorzugt werden"


def test_zu_wenige_beobachtungen_bleiben_neutral():
    zeilen = [{"home_id": 1, "away_id": 2, "home_goals": 1,
               "away_goals": 0}] * 5
    staerke = ls.estimate(zeilen, [(1.2, 1.0)] * 5, {1: "A", 2: "B"},
                          alpha=1.0)
    assert staerke.is_neutral()
    assert staerke.diagnose["fitted"] is False
    assert staerke.factors("A", "B") == (1.0, 1.0)


def test_kleine_ligen_werden_staerker_geschrumpft():
    """
    Ein groesseres Alpha zieht die Parameter naeher an null. Ohne
    diese Wirkung waere die Regularisierung nur Dekoration.
    """
    zeilen, lambdas = [], []
    for i in range(60):
        zeilen.append({"home_id": 1, "away_id": 2, "home_goals": 3,
                       "away_goals": 0})
        lambdas.append((1.2, 1.2))
    karte = {1: "A", 2: "B"}
    schwach = ls.estimate(zeilen, lambdas, karte, alpha=0.01)
    stark = ls.estimate(zeilen, lambdas, karte, alpha=100.0)
    assert abs(stark.attack["A"]) < abs(schwach.attack["A"])


def test_die_faktoren_bleiben_in_ihren_grenzen():
    staerke = ls.LeagueStrength({"A": 9.0}, {"B": 9.0})
    heim, gast = staerke.factors("A", "B")
    assert heim <= ls.FACTOR_MAX
    staerke2 = ls.LeagueStrength({"A": -9.0}, {"B": -9.0})
    heim2, _ = staerke2.factors("A", "B")
    assert heim2 >= ls.FACTOR_MIN


def test_keine_vereinsnamen_im_quelltext():
    """
    Eine Sonderbehandlung nach Vereinsname waere kein Modell, sondern
    eine Liste von Ausnahmen.
    """
    quelle = (WURZEL / "src" / "features" / "league_strength.py").read_text(
        encoding="utf-8")
    baum = ast.parse(quelle)
    for knoten in ast.walk(baum):
        if (isinstance(knoten, (ast.Module, ast.ClassDef, ast.FunctionDef))
                and ast.get_docstring(knoten)):
            knoten.body = knoten.body[1:]
    code = ast.unparse(baum).lower()
    for name in ("bayern", "real madrid", "arsenal", "ajax", "celtic",
                 "sporting", "psv", "barcelona"):
        assert name not in code, name


def test_kein_hardcodierter_top5_bonus():
    quelle = (WURZEL / "src" / "features" / "league_strength.py").read_text(
        encoding="utf-8")
    for verboten in ('"BL1"', '"PL"', '"PD"', '"SA"', '"FL1"'):
        assert verboten not in quelle, verboten


# ===========================================================================
# 3  PIT und Leakage
# ===========================================================================

def test_ein_testergebnis_veraendert_die_ligastaerke_nicht(alle_zeilen,
                                                          ligakarte):
    """
    DER SCHARFE MANIPULATIONSTEST.

    Alle Testergebnisse werden auf 9:0 gesetzt. Bewegt sich auch nur
    ein Parameter, sieht die Ligastaerke Testdaten.
    """
    fold = ce.OUTER_FOLDS[0]
    original = c15.evaluate_fold(alle_zeilen, fold, ligakarte)

    test_ids = {z["row_id"]
                for z in ce.cl_rows(alle_zeilen, fold["test_season"])}
    manipuliert = [
        (dict(z, home_goals=9, away_goals=0, outcome=0)
         if z["row_id"] in test_ids else z)
        for z in alle_zeilen]
    danach = c15.evaluate_fold(manipuliert, fold, ligakarte)

    assert (original["league_strength"]["parameters"]
            == danach["league_strength"]["parameters"])


def test_ein_historienergebnis_veraendert_sie_sehr_wohl(alle_zeilen,
                                                        ligakarte):
    """
    Die Gegenprobe. Ohne sie waere der Test oben auch dann gruen, wenn
    die Schaetzung ueberhaupt nichts liest.
    """
    fold = ce.OUTER_FOLDS[0]
    original = c15.evaluate_fold(alle_zeilen, fold, ligakarte)

    hist_ids = {z["row_id"] for z
                in c15.league_history(alle_zeilen, fold["train_seasons"])}
    manipuliert = [
        (dict(z, home_goals=9, away_goals=0, outcome=0)
         if z["row_id"] in hist_ids else z)
        for z in alle_zeilen]
    danach = c15.evaluate_fold(manipuliert, fold, ligakarte)

    assert (original["league_strength"]["parameters"]
            != danach["league_strength"]["parameters"])


def test_die_historie_liegt_vollstaendig_vor_dem_testfold(alle_zeilen):
    for fold in ce.OUTER_FOLDS:
        historie = c15.league_history(alle_zeilen, fold["train_seasons"])
        test = ce.cl_rows(alle_zeilen, fold["test_season"])
        assert historie and test
        assert not ({z["row_id"] for z in historie}
                    & {z["row_id"] for z in test})
        assert max(z["date"] for z in historie) < min(z["date"]
                                                      for z in test)
        assert all(z["season"] in fold["train_seasons"] for z in historie)


def test_die_innere_alphawahl_sieht_den_testfold_nie(alle_zeilen):
    for fold in ce.OUTER_FOLDS:
        historie = c15.league_history(alle_zeilen, fold["train_seasons"])
        frueh, spaet, _ = c15._innere_teilung(historie,
                                              fold["train_seasons"])
        test_ids = {z["row_id"]
                    for z in ce.cl_rows(alle_zeilen, fold["test_season"])}
        assert not ({z["row_id"] for z in frueh} & test_ids)
        assert not ({z["row_id"] for z in spaet} & test_ids)
        assert max(z["date"] for z in frueh) <= min(z["date"]
                                                    for z in spaet)


def test_die_zeilenreihenfolge_veraendert_nichts(alle_zeilen, ligakarte):
    import random

    fold = ce.OUTER_FOLDS[0]
    a = c15.evaluate_fold(alle_zeilen, fold, ligakarte)
    gemischt = list(alle_zeilen)
    random.Random(7).shuffle(gemischt)
    b = c15.evaluate_fold(gemischt, fold, ligakarte)
    assert (a["league_strength"]["parameters"]
            == b["league_strength"]["parameters"])
    assert a["c15"]["log_loss"] == b["c15"]["log_loss"]


def test_zwei_laeufe_liefern_dasselbe(alle_zeilen, ligakarte):
    fold = ce.OUTER_FOLDS[0]
    a = c15.evaluate_fold(alle_zeilen, fold, ligakarte)
    b = c15.evaluate_fold(alle_zeilen, fold, ligakarte)
    assert (a["league_strength"]["parameters"]
            == b["league_strength"]["parameters"])
    assert a["c15"]["log_loss"] == b["c15"]["log_loss"]


def test_c15_braucht_kein_netz_und_keine_env():
    for datei in ("src/features/league_strength.py",
                  "src/ml/c15_league_strength.py"):
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


def test_der_c10_stichtag_bleibt_unveraendert():
    from src.features import prediction_cutoff as pc

    assert pc.CUTOFF_HOUR == 12
    assert pc.CUTOFF_INCLUSIVE is False
    assert pc.assert_hours_match() is True


# ===========================================================================
# 4  Datenfairness
# ===========================================================================

def test_alle_drei_kandidaten_bewerten_dieselben_partien(alle_zeilen,
                                                         ligakarte):
    fold = ce.OUTER_FOLDS[0]
    e = c15.evaluate_fold(alle_zeilen, fold, ligakarte)
    assert e["v0"]["n"] == e["c14"]["n"] == e["c15"]["n"] == e["test_rows"]


def test_die_bestandsgroessen_entsprechen_dem_vertrag(alle_zeilen):
    vertrag = c15.evaluation_contract()
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


def test_keine_cl_history_profile_mehr(alle_zeilen):
    cl = [z for z in alle_zeilen if z.get("league") == "cl"]
    for zeile in cl:
        assert zeile["home_profile_source"] == "domestic_pit"
        assert zeile["away_profile_source"] == "domestic_pit"


def test_kein_spiel_wird_still_entfernt(alle_zeilen):
    cl = [z for z in alle_zeilen if z.get("league") == "cl"]
    for zeile in cl:
        if not (zeile.get("evaluation_eligible")
                or zeile.get("knockout_eligible")):
            assert zeile.get("exclusion_reason")


# ===========================================================================
# 5  Segmente
# ===========================================================================

def _zeile(**felder):
    grund = {"season": 2024, "is_knockout": 0, "outcome": 0,
             "home_id": 1, "away_id": 2,
             "home_profile_source": "domestic_pit",
             "away_profile_source": "domestic_pit",
             "home_profile_matches": 40, "away_profile_matches": 40}
    grund.update(felder)
    return grund


def test_die_segmente_sind_gerichtet_und_symmetrisch():
    schluessel = c15._segment_keys(_zeile(), {1: "PL", 2: "NL1"})
    assert "home_origin_league:PL" in schluessel
    assert "away_origin_league:NL1" in schluessel
    assert "origin:top5_vs_other" in schluessel
    assert any(k.startswith("home_profile_depth:") for k in schluessel)
    assert any(k.startswith("min_profile_depth:") for k in schluessel)


def test_die_evidenzsegmente_folgen_der_vorab_festgelegten_grenze():
    staerke = ls.LeagueStrength(
        {"PL": 0.1, "NL1": -0.1}, {"PL": 0.0, "NL1": 0.0},
        {"observations_per_league": {"PL": 200, "NL1": 5}})
    assert c15._evidenzklasse(staerke, "PL") == "strong"
    assert c15._evidenzklasse(staerke, "NL1") == "thin"
    assert c15._evidenzklasse(staerke, "XX1") == "cold_start"


def test_ueberlappende_segmente_zaehlen_als_ein_befund():
    n = 40
    eintraege = [(_zeile(), ["a:1", "b:1"]) for _ in range(n)]
    segmente = c15._segmente(eintraege, [1.0] * n, [1.5] * n)
    beschaedigt = [k for k, v in segmente.items() if v["severely_worse"]]
    assert len(beschaedigt) == 2
    assert len(c15.distinct_damage(segmente)) == 1


def test_ein_kleines_segment_ist_kein_gate():
    eintraege = [(_zeile(), ["klein"]) for _ in range(10)]
    segmente = c15._segmente(eintraege, [1.0] * 10, [2.0] * 10)
    assert segmente["klein"]["interpretable"] is False
    assert segmente["klein"]["severely_worse"] is False
    assert c15.distinct_damage(segmente) == []


# ===========================================================================
# 6  Entscheidungen
# ===========================================================================

def _messung(delta=-0.09, ci_low=-0.13, ci_high=-0.05,
             folds=(-0.07, -0.12), schaden=(), kontext_delta=-0.07,
             n=283, brier=-0.06, rps=-0.03,
             kalib_basis=0.043, kalib_ml=0.039):
    return {
        "standard": {
            "aggregate": {
                "n": n, "delta_log_loss": delta,
                "delta_brier": brier, "delta_rps": rps,
                "bootstrap": {"log_loss": {"ci_low": ci_low,
                                           "ci_high": ci_high}},
                "baseline": {"calibration_error": kalib_basis},
                "ml": {"calibration_error": kalib_ml},
                "c15_vs_c14": {"delta_log_loss": -0.08},
            },
            "folds": [{"fold": "f%d" % i, "delta_log_loss": d}
                      for i, d in enumerate(folds)],
            "distinct_damage": list(schaden),
        },
        "context": {"aggregate": {"delta_log_loss": kontext_delta}},
    }


def test_der_klare_gute_fall_wird_akzeptiert():
    urteil = c15.decide(_messung())
    assert urteil["verdict"] == c15.VERDICT_ACCEPTED
    assert all(urteil["conditions"].values())
    assert urteil["failed_conditions"] == []
    assert urteil["acceptance_class"] == c15.ACCEPTANCE_CLASS_DEVELOPMENT


def test_ein_eingeschlossenes_nullintervall_gibt_hoechstens_schatten():
    urteil = c15.decide(_messung(ci_high=+0.004))
    assert urteil["verdict"] == c15.VERDICT_PROVISIONAL_SHADOW


def test_widersprechende_folds_fuehren_zur_ablehnung():
    urteil = c15.decide(_messung(folds=(-0.12, +0.01)))
    assert urteil["verdict"] == c15.VERDICT_REJECTED


def test_ein_schweres_segment_verhindert_die_freigabe():
    urteil = c15.decide(_messung(schaden=("home_origin_league:PD",)))
    assert urteil["verdict"] == c15.VERDICT_REJECTED
    assert urteil["conditions"]["no_severe_segment_damage"] is False


def test_ein_beschaedigter_kontextbestand_verhindert_accepted():
    urteil = c15.decide(_messung(kontext_delta=+0.02))
    assert urteil["verdict"] == c15.VERDICT_REJECTED


def test_zu_wenige_daten_sind_nicht_auswertbar():
    assert c15.decide(_messung(n=10))["verdict"] == (
        c15.VERDICT_NOT_EVALUABLE)


def test_jede_fehlgeschlagene_bedingung_erscheint_in_den_gruenden():
    """
    DIE LEHRE AUS C14.

    Dort hatte `no_single_fold_carries_all` keinen Grundtext, und die
    Gruendeliste nannte drei von vier Ursachen. Eine unvollstaendige
    Begruendung sieht aus wie ein kleineres Problem.
    """
    urteil = c15.decide(_messung(folds=(-0.1799, -0.0001), delta=-0.09,
                                 ci_high=+0.01))
    fehlgeschlagen = urteil["failed_conditions"]
    assert fehlgeschlagen
    assert len(urteil["reasons"]) == len(fehlgeschlagen)
    for name in fehlgeschlagen:
        assert any(c15.REASON_TEXTS[name] in grund
                   for grund in urteil["reasons"]), name


def test_jede_bedingung_hat_einen_grundtext():
    urteil = c15.decide(_messung())
    for name in urteil["conditions"]:
        assert name in c15.REASON_TEXTS, name


def test_keine_bestandene_bedingung_erscheint_als_fehler():
    urteil = c15.decide(_messung(schaden=("x",)))
    for grund in urteil["reasons"]:
        assert c15.REASON_TEXTS["primary_better"] not in grund


def test_ein_ergebnis_kann_die_gates_nicht_ueberschreiben():
    messung = _messung(delta=+0.05, ci_low=+0.01, ci_high=+0.09)
    messung["verdict"] = c15.VERDICT_ACCEPTED
    messung["conditions"] = {"primary_better": True}
    urteil = c15.decide(messung)
    assert urteil["verdict"] == c15.VERDICT_REJECTED
    assert urteil["conditions"]["primary_better"] is False


def test_jedes_urteil_traegt_den_vertragsfingerabdruck():
    for messung in (_messung(), _messung(delta=+0.1), _messung(n=5)):
        assert (c15.decide(messung)["contract_fingerprint"]
                == VERTRAG_FINGERABDRUCK)


# ===========================================================================
# 7  Das Ergebnisartefakt
# ===========================================================================

@pytest.fixture(scope="module")
def artefakt():
    pfad = WURZEL / c15.ARTIFACT_PATH
    if not pfad.is_file():
        pytest.skip("C15 wurde noch nicht ausgefuehrt")
    return json.loads(pfad.read_text(encoding="utf-8"))


def test_das_artefakt_bindet_alle_vertraege(artefakt):
    from src.ml import c13_contract as c13
    from src.ml import c14_reevaluation as c14
    from src.ml import early_v2 as e9

    assert artefakt["contract_fingerprint"] == VERTRAG_FINGERABDRUCK
    assert artefakt["contract_frozen_before_measurement"] is True
    g = artefakt["bound_contracts"]
    assert g["c9_schema_fingerprint"] == e9.schema_fingerprint()
    assert g["c13_contract_fingerprint"] == c13.contract_fingerprint()
    assert g["c14_contract_fingerprint"] == c14.contract_fingerprint()
    assert artefakt["verdict"] in c15.VERDICTS


def test_das_artefakt_traegt_den_identifizierbarkeitsnachweis(artefakt):
    nachweis = artefakt["identifiability"]
    assert nachweis["national_rows_with_two_leagues"] == 0
    assert nachweis["learnable_from_national_matches"] is False
    for name, block in nachweis["per_fold_cl_history"].items():
        assert block["cross_league_share"] >= 0.95, name


def test_der_ergebnisfingerabdruck_ignoriert_zeit_und_git(artefakt):
    veraendert = dict(artefakt, created_at="1999-01-01T00:00:00+00:00",
                      git_commit="abc123")
    assert (c15.result_fingerprint(veraendert)
            == c15.result_fingerprint(artefakt)
            == artefakt["result_fingerprint"])


def test_das_artefakt_enthaelt_keine_geheimnisse_und_keine_pfade(artefakt):
    text = json.dumps(artefakt, ensure_ascii=False)
    for verboten in ("C:\\\\", "/home/", "Users\\\\", "api_key",
                     "APISPORTS_KEY", "secret", "password", "Bearer"):
        assert verboten.lower() not in text.lower(), verboten


def test_das_artefakt_hat_die_registry_nicht_veraendert(artefakt):
    assert artefakt["registry"]["changed_by_evaluation"] is False


# ===========================================================================
# 8  Der C11-Vertrag, jetzt zustandsfrei
# ===========================================================================

def test_der_c11_vertragsfingerabdruck_haengt_nicht_am_zustand():
    """
    DER REPARIERTE C11-FEHLER.

    Der Vertragsfingerabdruck wurde ueber das GESAMTE Artefakt
    gebildet, also einschliesslich models_by_stage und
    active_model_id. Jede Registrierung bewegte ihn, und man konnte
    nicht mehr sehen, ob sich die Regel oder nur die Belegung
    geaendert hatte.
    """
    dokument = mr.load_registry()
    a = mr.build_artifact(dokument)

    leer = copy.deepcopy(dokument)
    leer["models"] = []
    b = mr.build_artifact(leer)

    assert a["contract_fingerprint"] == b["contract_fingerprint"]
    assert a["state_fingerprint"] != b["state_fingerprint"]


def test_der_c11_vertragsteil_enthaelt_keinen_zustand():
    artefakt = mr.build_artifact()
    for feld in artefakt["contract_fingerprint_covers"]:
        assert feld not in artefakt["state_fingerprint_covers"]
    for zustand in ("active_model_id", "models_by_stage",
                    "registry_fingerprint", "rollback_target"):
        assert zustand in artefakt["state_fingerprint_covers"]
        assert zustand not in artefakt["contract_fingerprint_covers"]


def test_der_c11_vertrag_selbst_ist_zustandsfrei():
    text = json.dumps(mr.contract(), sort_keys=True)
    assert "models" not in text
    assert "clm-" not in text


# ===========================================================================
# 9  Der Freigabeweg
# ===========================================================================

def _bundle(tmp_path, model_id="clm-c15test"):
    verzeichnis = tmp_path / "data" / "ml" / "models"
    verzeichnis.mkdir(parents=True, exist_ok=True)
    pfad = verzeichnis / ("%s.json" % model_id)
    pfad.write_text(json.dumps({"model_id": model_id,
                                "schema_version": 2}),
                    encoding="utf-8")
    return pfad


def _eintrag(tmp_path, model_id="clm-c15test", stage=mr.STAGE_CANDIDATE):
    pfad = _bundle(tmp_path, model_id)
    return {
        "model_id": model_id,
        "model_name": fg.C15_CANDIDATE,
        "model_family": "poisson_offset_correction_linear",
        "bundle_schema_version": 2,
        "stage": stage,
        "bundle_path": "data/ml/models/%s.json" % model_id,
        "bundle_sha256": mr.bundle_sha256(str(pfad)),
        "feature_schema_fingerprint": c15.schema_fingerprint(),
        "c9_manifest_fingerprint": rel._c9_manifest_fingerprint(),
        "c10_contract_fingerprint": rel._artefakt_feld(
            None, "data/ml/c10_prediction_cutoff_contract_2023-2025.json",
            "contract_fingerprint"),
        "evaluation_artifact": c15.ARTIFACT_PATH,
        "evaluation_status": "accepted",
        "state_reason": "Kunsteintrag fuer den Freigabetest",
    }


def _accepted_urteil():
    return c15.decide(_messung())


@pytest.fixture
def bereit(tmp_path):
    """Ein Kandidat, der eine Freigabe technisch tragen wuerde."""
    eintrag = _eintrag(tmp_path)
    dokument = mr.empty_registry()
    dokument["models"] = [eintrag]
    return eintrag, dokument


def test_der_accepted_pfad_ist_vollstaendig_gebaut(bereit, tmp_path):
    """
    DER REPARIERTE C12-FEHLER.

    Hier stand ein NotImplementedError. Ein Freigabeweg, den nie
    jemand gegangen ist, faellt genau dann aus, wenn man ihn zum
    ersten Mal braucht. Er wird deshalb synthetisch bewiesen, auch
    wenn die echte Messung ihn nicht ausloest.
    """
    eintrag, dokument = bereit
    ergebnis = rel.apply_release(
        _accepted_urteil(), eintrag, {}, eintrag["bundle_path"],
        repo_root=str(tmp_path), dokument=dokument, dry_run=True)
    assert ergebnis["status"] == "dry_run_ok", ergebnis.get("findings")
    assert ergebnis["wrote_anything"] is False


def test_ein_rejected_urteil_wird_abgelehnt(bereit, tmp_path):
    eintrag, dokument = bereit
    urteil = c15.decide(_messung(schaden=("x",)))
    ergebnis = rel.apply_release(
        urteil, eintrag, {}, eintrag["bundle_path"],
        repo_root=str(tmp_path), dokument=dokument, dry_run=True)
    assert ergebnis["status"] == "refused"
    assert "accepted" in ergebnis["reason"]


def test_ein_falscher_bundlehash_blockiert(bereit, tmp_path):
    eintrag, dokument = bereit
    kaputt = dict(eintrag, bundle_sha256="0" * 64)
    ok, befunde = rel.preflight(_accepted_urteil(), kaputt,
                                kaputt["bundle_path"], str(tmp_path),
                                dokument)
    assert ok is False
    assert any("Bundle-Hash" in b for b in befunde)


def test_ein_falsches_merkmalsschema_blockiert(bereit, tmp_path):
    eintrag, dokument = bereit
    kaputt = dict(eintrag, feature_schema_fingerprint="f" * 64)
    ok, befunde = rel.preflight(_accepted_urteil(), kaputt,
                                kaputt["bundle_path"], str(tmp_path),
                                dokument)
    assert ok is False
    assert any("Merkmalsschema" in b for b in befunde)


def test_ein_fehlendes_bundle_blockiert(bereit, tmp_path):
    eintrag, dokument = bereit
    ok, befunde = rel.preflight(_accepted_urteil(), eintrag,
                                "data/ml/models/gibtsnicht.json",
                                str(tmp_path), dokument)
    assert ok is False
    assert any("Bundle fehlt" in b for b in befunde)


def test_ein_fremder_vertragsfingerabdruck_blockiert(bereit, tmp_path):
    eintrag, dokument = bereit
    urteil = dict(_accepted_urteil(), contract_fingerprint="0" * 64)
    ok, befunde = rel.preflight(urteil, eintrag, eintrag["bundle_path"],
                                str(tmp_path), dokument)
    assert ok is False
    assert any("Vertrag" in b for b in befunde)


def test_der_trockenlauf_schreibt_nichts(bereit, tmp_path):
    eintrag, dokument = bereit
    ziel = tmp_path / "data" / "ml"
    vorher = sorted(p.name for p in ziel.iterdir())
    rel.apply_release(_accepted_urteil(), eintrag, {},
                      eintrag["bundle_path"], repo_root=str(tmp_path),
                      dokument=dokument, dry_run=True)
    nachher = sorted(p.name for p in ziel.iterdir())
    assert vorher == nachher


def test_die_anwendung_erzeugt_genau_ein_aktives_modell(bereit, tmp_path):
    eintrag, dokument = bereit
    ergebnis = rel.apply_release(
        _accepted_urteil(), eintrag, {}, eintrag["bundle_path"],
        repo_root=str(tmp_path), dokument=dokument, dry_run=False)
    assert ergebnis["status"] == "applied", ergebnis.get("reason")

    frisch = mr.load_registry(repo_root=str(tmp_path))
    aktiv = [m for m in frisch["models"]
             if m["stage"] == mr.STAGE_ACTIVE]
    assert len(aktiv) == 1
    assert aktiv[0]["model_id"] == eintrag["model_id"]
    assert (tmp_path / rel.RELEASE_ARTIFACT_PATH).is_file()


@pytest.mark.parametrize("schritt", ["preflight_ok", "snapshot_written",
                                     "artifact_staged",
                                     "registry_written"])
def test_ein_absturz_an_jeder_schreibgrenze_bleibt_aufloesbar(
        bereit, tmp_path, schritt):
    """
    DER REPARIERTE TRANSAKTIONSFEHLER.

    C12 schrieb Artefakt und Registry nacheinander. Brach der zweite
    Schritt ab, behauptete das Artefakt einen Zustand, den es nicht
    gab. Hier wird an jeder Grenze abgebrochen und geprueft, dass das
    Recovery den Zustand richtig benennt.
    """
    eintrag, dokument = bereit
    with pytest.raises(rel.ReleaseError):
        rel.apply_release(_accepted_urteil(), eintrag, {},
                          eintrag["bundle_path"], repo_root=str(tmp_path),
                          dokument=dokument, dry_run=False,
                          fail_after=schritt)

    zustand = rel.recover(repo_root=str(tmp_path))
    if schritt == "registry_written":
        assert zustand["status"] == "registry_applied_artifact_missing"
    else:
        assert zustand["status"] == "registry_untouched"


def test_kein_artefakt_behauptet_einen_nicht_angewendeten_zustand(
        bereit, tmp_path):
    eintrag, dokument = bereit
    with pytest.raises(rel.ReleaseError):
        rel.apply_release(_accepted_urteil(), eintrag, {},
                          eintrag["bundle_path"], repo_root=str(tmp_path),
                          dokument=dokument, dry_run=False,
                          fail_after="registry_written")
    assert not (tmp_path / rel.RELEASE_ARTIFACT_PATH).is_file(), (
        "das Releaseartefakt darf erst NACH der Registry entstehen")


# ===========================================================================
# 10  Rollback
# ===========================================================================

def test_der_rollback_stellt_den_vorzustand_wieder_her(bereit, tmp_path):
    eintrag, dokument = bereit
    rel.apply_release(_accepted_urteil(), eintrag, {},
                      eintrag["bundle_path"], repo_root=str(tmp_path),
                      dokument=dokument, dry_run=False)
    nachher = mr.load_registry(repo_root=str(tmp_path))
    assert any(m["stage"] == mr.STAGE_ACTIVE for m in nachher["models"])

    probe = rel.rollback(repo_root=str(tmp_path), dry_run=True)
    assert probe["status"] == "dry_run_ok"

    zurueck = rel.rollback(repo_root=str(tmp_path), dry_run=False)
    assert zurueck["status"] == "rolled_back"
    wieder = mr.load_registry(repo_root=str(tmp_path))
    assert not any(m["stage"] == mr.STAGE_ACTIVE
                   for m in wieder["models"])


def test_ein_rollback_ohne_vorzustand_wird_verweigert(tmp_path):
    ergebnis = rel.rollback(repo_root=str(tmp_path), dry_run=False)
    assert ergebnis["status"] == "refused"
    assert "Vorzustand" in ergebnis["reason"]


def test_ein_beschaedigter_rollbackstand_scheitert(bereit, tmp_path):
    eintrag, dokument = bereit
    rel.save_snapshot(dokument, repo_root=str(tmp_path))
    pfad = tmp_path / rel.SNAPSHOT_PATH
    inhalt = json.loads(pfad.read_text(encoding="utf-8"))
    inhalt["registry"]["models"][0]["model_id"] = "clm-manipuliert"
    pfad.write_text(json.dumps(inhalt), encoding="utf-8")

    ergebnis = rel.rollback(repo_root=str(tmp_path), dry_run=False)
    assert ergebnis["status"] == "refused"
    assert "veraendert" in ergebnis["reason"]


def test_ein_abgelehntes_modell_wird_durch_rollback_nicht_aktiv(tmp_path):
    """
    Rollback ist technische Wiederherstellung, kein Weg um ein
    fachliches Rejected herum.
    """
    eintrag = _eintrag(tmp_path, "clm-abgelehnt", mr.STAGE_ACTIVE)
    eintrag["evaluation_status"] = "rejected"
    dokument = mr.empty_registry()
    dokument["models"] = [eintrag]
    rel.save_snapshot(dokument, repo_root=str(tmp_path))

    ergebnis = rel.rollback(repo_root=str(tmp_path), dry_run=False)
    assert ergebnis["status"] == "refused"
    assert "abgelehnt" in ergebnis["reason"]


def test_ein_unlesbarer_vorzustand_scheitert_fail_closed(tmp_path):
    ziel = tmp_path / rel.SNAPSHOT_PATH
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text("{kein json", encoding="utf-8")
    with pytest.raises(rel.ReleaseError):
        rel.load_snapshot(repo_root=str(tmp_path))


# ===========================================================================
# 11  Runtime und Modustrennung
# ===========================================================================

def test_der_registrygate_bleibt_der_entscheider():
    """
    GEAENDERT IN V2-C17.

    Vorher gab es kein aktives Modell, und dieser Test hielt das fest.
    Seit C17 ist ein regulaer freigegebenes Modell aktiv. Die
    Zusicherung, um die es hier ging, gilt unveraendert: Ohne
    gueltigen Registryeintrag bestimmt kein Modell die Antwort.
    """
    from src.ml import runtime

    assert hasattr(runtime, "REASON_NOT_ACTIVE_IN_REGISTRY")
    eintrag, grund = mr.active_entry()
    if eintrag is None:
        assert grund == "no_active_model"
    else:
        assert eintrag["evaluation_status"] == mr.EVALUATION_ACCEPTED
        assert eintrag.get("approval")


def test_das_c15_urteil_hat_nichts_aktiviert():
    """
    GEAENDERT IN V2-C17.

    C15 endete mit `rejected` und hat nichts aktiviert - daran
    aendert sich nichts. Aktiviert wurde spaeter das C16-Modell, und
    zwar ueber den regulaeren Weg. Der Test prueft deshalb, dass kein
    Modell im Schatten haengen geblieben ist und dass ein aktives
    Modell eine Freigabe traegt.
    """
    dokument = mr.load_registry()
    assert mr.shadow_entries() == []
    for modell in dokument.get("models") or []:
        assert modell["stage"] in (mr.STAGE_CANDIDATE, mr.STAGE_ACTIVE,
                                   mr.STAGE_ROLLBACK)
        if modell["stage"] == mr.STAGE_ACTIVE:
            assert modell.get("approval")
            assert modell["evaluation_status"] == mr.EVALUATION_ACCEPTED


def test_die_ligasimulation_kennt_weiterhin_kein_ml():
    quelle = (WURZEL / "src" / "predict" / "league_match_sim.py").read_text(
        encoding="utf-8")
    assert "src.ml" not in quelle


def test_die_ligastaerke_liegt_ausserhalb_von_src_ml():
    """
    Sie ist ein Merkmalsbaustein, kein ML-Modul. Laege sie in src/ml,
    koennte der Vorhersagepfad sie nicht benutzen, ohne die
    Schichtentrennung zu brechen.
    """
    assert (WURZEL / "src" / "features" / "league_strength.py").is_file()
    assert not (WURZEL / "src" / "ml" / "league_strength.py").exists()
