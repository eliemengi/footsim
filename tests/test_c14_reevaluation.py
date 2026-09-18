"""
Tests der finalen Reevaluation (V2-C14).

WORUM ES GEHT
V2-C12 lehnte das Modell an zwei Bedingungen ab, von denen eine ein
Datenfehler war. V2-C13 hat ihn behoben. C14 misst, was uebrig bleibt.

Der schaerfste Teil dieser Tests ist nicht die Messung, sondern die
Reihenfolge: Der Vertrag muss vor der Messung vollstaendig stehen, und
kein Ergebnis darf ihn nachtraeglich bewegen. Ein Vertrag, der sich an
das Ergebnis anpasst, ist keiner.
"""

import ast
import json
import pathlib

import pytest

from src.ml import c14_reevaluation as c14
from src.ml import cl_evaluate as ce

WURZEL = pathlib.Path(__file__).resolve().parents[1]

#: Der Fingerabdruck, unter dem gemessen wurde. Er steht hier fest,
#: damit eine spaetere stille Vertragsaenderung auffaellt, statt
#: unbemerkt zu bleiben.
VERTRAG_FINGERABDRUCK = (
    "704c9ade45f3ca1c9fde49bf1e0812f1c903f7ebc71ee07554bd9d4883dba835")


# ===========================================================================
# 1  Der Vertrag
# ===========================================================================

def test_der_vertrag_steht_ohne_eine_einzige_messung():
    """
    DIE KERNZUSICHERUNG VON C14.

    Der Vertrag ist vollstaendig bildbar, ohne dass ein Datensatz
    gebaut oder ein Modell angepasst wurde. Waere er es nicht, koennte
    er nicht vor der Messung entstanden sein.
    """
    vertrag = c14.evaluation_contract()
    for pflicht in ("candidate", "bound_contracts", "inventories", "folds",
                    "metrics", "bootstrap", "segments", "missing_data",
                    "calibration", "thresholds", "gates"):
        assert pflicht in vertrag, pflicht

    text = json.dumps(vertrag, ensure_ascii=False)
    for ergebnisbegriff in ("delta_log_loss", "ci_high", "ci_low",
                            "measured_", "observed_frequency"):
        assert ergebnisbegriff not in text, ergebnisbegriff


def test_der_vertragsfingerabdruck_ist_der_gemessene():
    assert c14.contract_fingerprint() == VERTRAG_FINGERABDRUCK


def test_der_vertrag_ist_deterministisch():
    assert c14.contract_fingerprint() == c14.contract_fingerprint()


def test_eine_geaenderte_schwelle_aendert_den_fingerabdruck(monkeypatch):
    """Die Gegenprobe. Ein Fingerabdruck, der nie reagiert, ist keiner."""
    vorher = c14.contract_fingerprint()
    monkeypatch.setattr(ce, "SEVERE_DEGRADATION", 0.5)
    assert c14.contract_fingerprint() != vorher


def test_eine_geaenderte_segmentgroesse_aendert_den_fingerabdruck(
        monkeypatch):
    vorher = c14.contract_fingerprint()
    monkeypatch.setattr(c14, "SEGMENT_MIN_SIZE", 99)
    assert c14.contract_fingerprint() != vorher


def test_der_registryzustand_bewegt_den_vertrag_nicht(monkeypatch):
    """
    DIE LEHRE AUS C11.

    Dort steckten Regel und Zustand in einem Wert, und jede
    Modellregistrierung veraenderte ihn. C14 bindet ausdruecklich nur
    den unveraenderlichen C11-Vertragsteil.
    """
    from src.ml import model_registry as mr

    vorher = c14.contract_fingerprint()
    monkeypatch.setattr(
        mr, "load_registry",
        lambda *a, **k: {"schema_version": 1,
                         "models": [{"model_id": "clm-test"}]})
    assert c14.contract_fingerprint() == vorher


def test_ein_fremdes_ergebnis_wird_zurueckgewiesen():
    """
    Fail-closed. Ohne Fingerabdruck wird abgelehnt, nicht
    durchgewunken.
    """
    with pytest.raises(c14.ContractViolation):
        c14.assert_contract_matches({"contract_fingerprint": "falsch"})
    with pytest.raises(c14.ContractViolation):
        c14.assert_contract_matches({})
    assert c14.assert_contract_matches(
        {"contract_fingerprint": c14.contract_fingerprint()}) is True


def test_die_vertragsdatei_liegt_vor_und_traegt_kein_ergebnis():
    pfad = WURZEL / c14.CONTRACT_PATH
    assert pfad.is_file(), "der Vertrag wurde nicht festgeschrieben"
    dokument = json.loads(pfad.read_text(encoding="utf-8"))
    assert dokument["frozen_before_measurement"] is True
    assert dokument["contract_fingerprint"] == VERTRAG_FINGERABDRUCK
    assert "decision" not in dokument
    assert "measurement" not in dokument


def test_die_schwellen_stammen_aus_frueheren_vertraegen():
    """
    Keine Schwelle wurde fuer C14 gewaehlt. Eine hier erfundene waere
    die bequemste Art, ein Ergebnis zu bekommen.
    """
    from src.ml import c8_ablation as c8

    schwellen = c14.evaluation_contract()["thresholds"]
    assert schwellen["severe_degradation"] == ce.SEVERE_DEGRADATION
    assert schwellen["min_reliable_n"] == ce.MIN_RELIABLE_N
    assert (schwellen["max_secondary_degradation"]
            == c8.MAX_SECONDARY_DEGRADATION)
    assert (schwellen["max_calibration_degradation"]
            == c8.MAX_CALIBRATION_DEGRADATION)
    assert schwellen["segment_min_size"] == 30


def test_der_kandidat_bleibt_eingefroren():
    """
    C14 misst Daten, nicht Modelle. Wuerden beide gleichzeitig
    wechseln, waere das Ergebnis nicht mehr lesbar.
    """
    from src.ml import feature_groups as fg
    from src.ml import model as mdl

    kandidat = c14.evaluation_contract()["candidate"]
    assert kandidat["name"] == ce.CANDIDATE == "team_profile_cl"
    assert kandidat["feature_count"] == 16
    assert kandidat["features"] == sorted(fg.columns_for(ce.CANDIDATE))
    assert kandidat["alpha_candidates"] == list(mdl.ALPHA_CANDIDATES)
    assert kandidat["model_class"] == "poisson_offset_correction_linear"


# ===========================================================================
# 2  Datensatzidentitaet
# ===========================================================================

@pytest.fixture(scope="module")
def alle_zeilen():
    from src.ml import dataset as ds

    zeilen, _ = ds.build_dataset(include_cl=True)
    return zeilen


@pytest.fixture(scope="module")
def cl_zeilen(alle_zeilen):
    return [z for z in alle_zeilen if z.get("league") == "cl"]


def test_der_reine_zielfingerabdruck_ignoriert_die_auswertbarkeit():
    """
    DIE LEHRE AUS C13.

    Dort bewegte sich der C9-Zielfingerabdruck, obwohl kein einziges
    Tor anders war - weil `evaluation_eligible` mit im Hash steckt.
    Fuer die Frage "sind es dieselben Spiele mit denselben
    Ergebnissen?" ist das unbrauchbar.
    """
    basis = [{"row_id": "a", "match_id": 1, "league": "cl", "season": 2024,
              "date": "2024-09-17", "home_id": 5, "away_id": 64,
              "home_goals": 2, "away_goals": 1, "outcome": 0,
              "evaluation_eligible": True}]
    geaendert = [dict(basis[0], evaluation_eligible=False)]
    assert (c14.pure_target_fingerprint(basis)
            == c14.pure_target_fingerprint(geaendert))

    anderes_tor = [dict(basis[0], home_goals=3, outcome=0)]
    assert (c14.pure_target_fingerprint(basis)
            != c14.pure_target_fingerprint(anderes_tor))

    anderes_spiel = [dict(basis[0], match_id=2)]
    assert (c14.pure_target_fingerprint(basis)
            != c14.pure_target_fingerprint(anderes_spiel))


def test_der_reine_zielfingerabdruck_ignoriert_merkmalswerte():
    basis = [{"row_id": "a", "match_id": 1, "league": "cl", "season": 2024,
              "date": "2024-09-17", "home_id": 5, "away_id": 64,
              "home_goals": 2, "away_goals": 1, "outcome": 0,
              "home_attack_home": 1.2}]
    geaendert = [dict(basis[0], home_attack_home=9.9,
                      home_profile_source="neutral")]
    assert (c14.pure_target_fingerprint(basis)
            == c14.pure_target_fingerprint(geaendert))


def test_die_erwarteten_cl_zeilen_sind_da(cl_zeilen):
    assert len(cl_zeilen) == 503


def test_die_profilquellen_entsprechen_dem_stand_nach_c13(cl_zeilen):
    import collections

    quellen = collections.Counter()
    for zeile in cl_zeilen:
        for seite in ("home", "away"):
            quellen[zeile.get(seite + "_profile_source")] += 1
    assert quellen["cl_history_pit"] == 0
    assert quellen["neutral"] == 0
    assert quellen["domestic_pit"] == 1006


def test_die_bestandsgroessen_entsprechen_dem_vertrag(alle_zeilen):
    """
    Der Vertrag nennt 283 und 373 als ERWARTUNG. Weicht die Messung
    ab, ist das ein Befund - der Vertrag wird nicht still angepasst.
    """
    vertrag = c14.evaluation_contract()

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


def test_die_beiden_bestaende_werden_nie_addiert(alle_zeilen):
    """
    Sie ueberlappen in der regulaeren Phase. 283 + 373 waere eine
    erfundene Stichprobe.
    """
    standard = set()
    for fold in ce.OUTER_FOLDS:
        standard |= {z["row_id"]
                     for z in ce.cl_rows(alle_zeilen, fold["test_season"])}
    kontext = set()
    for fold in ce.CONTEXT_FOLDS:
        kontext |= {z["row_id"] for z in
                    ce.context_rows(alle_zeilen, [fold["test_season"]])}
    assert standard < kontext, "der Standardbestand ist keine Teilmenge"
    assert len(kontext) - len(standard) == 90


def test_v0_und_v2_bewerten_dieselben_partien(alle_zeilen):
    """
    Gepaart oder gar nicht. Bewerteten die beiden verschiedene Spiele,
    waere jeder Vergleich wertlos.
    """
    from src.ml import evaluate as ev
    from src.ml import feature_groups as fg
    from src.ml import model as mdl

    spalten = fg.columns_for(ce.CANDIDATE)
    fold = ce.OUTER_FOLDS[0]
    test = ce.cl_rows(alle_zeilen, fold["test_season"])
    basis_p = ev.probabilities_for(mdl.baseline_lambdas(test))
    assert len(basis_p) == len(test)
    # assert_paired wirft, sobald Laenge oder Zuordnung nicht stimmen.
    assert ce.assert_paired(test, basis_p, basis_p) in (None, True)
    assert len({z["row_id"] for z in test}) == len(test)


def test_kein_spiel_wird_still_entfernt(cl_zeilen):
    """
    Jede nicht ausgewertete Partie nennt einen Grund. Ein stiller
    Ausschluss saehe aus wie ein fehlendes Spiel.
    """
    for zeile in cl_zeilen:
        if not (zeile.get("evaluation_eligible")
                or zeile.get("knockout_eligible")):
            assert zeile.get("exclusion_reason"), zeile["row_id"]


# ===========================================================================
# 3  Folds, PIT und Leakage
# ===========================================================================

def test_die_folds_sind_chronologisch():
    for fold in list(ce.OUTER_FOLDS) + list(ce.CONTEXT_FOLDS):
        assert all(s < fold["test_season"] for s in fold["train_seasons"])


def test_der_testfold_wird_nie_zur_auswahl_benutzt(alle_zeilen):
    """
    Die innere Teilung laeuft ausschliesslich auf dem
    Trainingsbestand. Saehe sie den Testfold, waere jede Alphawahl
    eine Anpassung an das Ergebnis.
    """
    from src.ml import evaluate as ev

    fold = ce.OUTER_FOLDS[1]
    training = ce.league_rows(alle_zeilen, fold["train_seasons"])
    fit_z, val_z, _ = ev.inner_split(
        training, {"train_seasons": fold["train_seasons"]},
        select=ce.league_rows)

    test_ids = {z["row_id"]
                for z in ce.cl_rows(alle_zeilen, fold["test_season"])}
    assert not ({z["row_id"] for z in fit_z} & test_ids)
    assert not ({z["row_id"] for z in val_z} & test_ids)
    for zeile in fit_z + val_z:
        assert zeile["season"] in fold["train_seasons"]
        assert zeile["league"] != "cl"


def test_das_training_des_standardvertrags_kennt_keine_cl_zeile(
        alle_zeilen):
    for fold in ce.OUTER_FOLDS:
        training = ce.league_rows(alle_zeilen, fold["train_seasons"])
        assert all(z["league"] != "cl" for z in training)


def test_der_kontextvertrag_trainiert_nur_auf_frueheren_cl_saisons(
        alle_zeilen):
    for fold in ce.CONTEXT_FOLDS:
        training = ce.context_training_rows(alle_zeilen,
                                            fold["train_seasons"])
        for zeile in training:
            assert zeile["season"] < fold["test_season"]


def test_c13_speist_keine_nationalen_testdaten_in_frueheres_training(
        alle_zeilen):
    """
    Die Pruefung, die C14 ausdruecklich verlangt.

    C13 hat 18 Ligadateien zusaetzlich angeschlossen. Die reine
    Existenz einer Datei darf keine zeitliche Berechtigung bedeuten:
    Kein Trainingsspiel darf am oder nach dem Testfold liegen.
    """
    for fold in ce.OUTER_FOLDS:
        training = ce.league_rows(alle_zeilen, fold["train_seasons"])
        test = ce.cl_rows(alle_zeilen, fold["test_season"])
        assert training and test
        spaetestes_training = max(z["date"] for z in training)
        fruehester_test = min(z["date"] for z in test)
        assert spaetestes_training < fruehester_test, (
            f"{fold['name']}: Training reicht bis "
            f"{spaetestes_training}, Test beginnt {fruehester_test}")


def test_der_c10_stichtag_bleibt_unveraendert():
    from src.features import prediction_cutoff as pc

    assert pc.CUTOFF_HOUR == 12
    assert pc.CUTOFF_INCLUSIVE is False
    assert pc.assert_hours_match() is True
    vertrag = c14.evaluation_contract()["bound_contracts"]
    assert vertrag["c10_cutoff_hour"] == 12
    assert vertrag["c10_inclusive"] is False


def test_der_c9_schemafreeze_bleibt_unveraendert():
    from src.ml import early_v2 as e9

    assert e9.schema_fingerprint() == (
        "475b9be82c21c7ea977d71db1a714e3bc37fd4be2336897285730bc116694aa5")
    assert len(e9.selected_columns()) == 16


def test_c14_liest_keine_snapshots_und_kein_netz():
    baum = ast.parse((WURZEL / "src" / "ml" / "c14_reevaluation.py")
                     .read_text(encoding="utf-8"))
    for knoten in ast.walk(baum):
        if (isinstance(knoten, (ast.Module, ast.ClassDef, ast.FunctionDef))
                and ast.get_docstring(knoten)):
            knoten.body = knoten.body[1:]
    code = ast.unparse(baum)
    for verboten in ("requests", "urllib", "socket", "httpx", "dotenv",
                     ".env", "snapshot_reader", "squad_availability"):
        assert verboten not in code, verboten


# ===========================================================================
# 4  Segmente
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
    """
    DER NACHGESCHAERFTE PUNKT AUS C12.

    Dort stand `profile_source` im Vertrag, ohne die Seite zu nennen,
    und die Umsetzung nahm die Heimseite. Gemessen kehrte sich das
    Vorzeichen um, je nachdem welche Seite man ansah.
    """
    schluessel = c14._segment_keys(_zeile())
    assert any(k.startswith("home_profile_source:") for k in schluessel)
    assert any(k.startswith("away_profile_source:") for k in schluessel)
    assert any(k.startswith("profile_source_pair:") for k in schluessel)
    assert any(k.startswith("home_profile_depth:") for k in schluessel)
    assert any(k.startswith("away_profile_depth:") for k in schluessel)
    assert any(k.startswith("min_profile_depth:") for k in schluessel)


def test_die_seite_steht_im_segmentnamen():
    """Wer den Namen liest, muss die Seite nicht raten."""
    schluessel = c14._segment_keys(
        _zeile(home_profile_matches=5, away_profile_matches=40))
    assert "home_profile_depth:<6" in schluessel
    assert "away_profile_depth:>=20" in schluessel
    assert "min_profile_depth:<6" in schluessel
    assert "profile_depth:asymmetric" in schluessel


def test_die_tiefenklassen_stehen_fest():
    assert c14._tiefenklasse(5) == "<6"
    assert c14._tiefenklasse(6) == "6-19"
    assert c14._tiefenklasse(19) == "6-19"
    assert c14._tiefenklasse(20) == ">=20"
    assert c14._tiefenklasse(None) == "unknown"


def test_ein_kleines_segment_ist_kein_gate():
    zeilen = [_zeile() for _ in range(10)]
    segmente = c14._segmente(zeilen, [1.0] * 10, [2.0] * 10)
    for block in segmente.values():
        assert block["interpretable"] is False
        assert block["severely_worse"] is False
    assert c14.distinct_damage(segmente) == []


def test_ein_grosses_segment_ist_ein_gate():
    n = 40
    zeilen = [_zeile() for _ in range(n)]
    segmente = c14._segmente(zeilen, [1.0] * n, [1.5] * n)
    assert any(b["severely_worse"] for b in segmente.values())
    assert c14.distinct_damage(segmente)


def test_ueberlappende_segmente_zaehlen_als_ein_befund():
    """
    `phase:league` und `stage:LEAGUE_STAGE` koennen exakt dieselben
    Partien tragen. Denselben Schaden zweimal zu zaehlen waere eine
    erfundene Haeufung.
    """
    n = 40
    zeilen = [_zeile(stage="LEAGUE_STAGE") for _ in range(n)]
    segmente = c14._segmente(zeilen, [1.0] * n, [1.5] * n)

    beschaedigt = [k for k, v in segmente.items() if v["severely_worse"]]
    gruppen = c14.distinct_damage(segmente)
    assert len(beschaedigt) > len(gruppen), (
        "ohne Zusammenfassung waere jeder Name ein eigener Schaden")
    assert len(gruppen) == 1, gruppen


def test_verschiedene_zeilenmengen_bleiben_getrennte_befunde():
    """Die Gegenprobe: echte Ueberlappung, nicht jede Aehnlichkeit."""
    zeilen = ([_zeile(season=2024) for _ in range(40)]
              + [_zeile(season=2025) for _ in range(40)])
    n = len(zeilen)
    segmente = c14._segmente(zeilen, [1.0] * n, [1.5] * n)
    assert segmente["season:2024"]["overlap_group"] != (
        segmente["season:2025"]["overlap_group"])


# ===========================================================================
# 5  Entscheidungen
# ===========================================================================

def _messung(delta=-0.02, ci_low=-0.04, ci_high=-0.005,
             folds=(-0.02, -0.02), schaden=(), kontext_delta=-0.01,
             n=283, brier=-0.01, rps=-0.01,
             kalib_basis=0.05, kalib_ml=0.03):
    """Eine synthetische Messung - nur die Felder, die decide() liest."""
    return {
        "standard": {
            "aggregate": {
                "n": n,
                "delta_log_loss": delta,
                "delta_brier": brier,
                "delta_rps": rps,
                "bootstrap": {"log_loss": {"ci_low": ci_low,
                                           "ci_high": ci_high}},
                "baseline": {"calibration_error": kalib_basis},
                "ml": {"calibration_error": kalib_ml},
            },
            "folds": [{"fold": "f%d" % i, "delta_log_loss": d}
                      for i, d in enumerate(folds)],
            "distinct_damage": list(schaden),
        },
        "context": {"aggregate": {"delta_log_loss": kontext_delta}},
    }


def test_der_klare_gute_fall_wird_akzeptiert():
    urteil = c14.decide(_messung())
    assert urteil["verdict"] == c14.VERDICT_ACCEPTED
    assert all(urteil["conditions"].values())
    assert urteil["acceptance_class"] == (
        c14.ACCEPTANCE_CLASS_DEVELOPMENT)


def test_ein_eingeschlossenes_nullintervall_gibt_hoechstens_schatten():
    urteil = c14.decide(_messung(ci_high=+0.004))
    assert urteil["verdict"] == c14.VERDICT_PROVISIONAL_SHADOW
    assert urteil["conditions"]["ci_excludes_zero"] is False
    assert urteil["conditions"]["primary_better"] is True


def test_widersprechende_folds_fuehren_zur_ablehnung():
    urteil = c14.decide(_messung(folds=(-0.03, +0.01)))
    assert urteil["verdict"] == c14.VERDICT_REJECTED
    assert urteil["conditions"]["all_folds_same_direction"] is False


def test_ein_schweres_segment_verhindert_die_freigabe():
    urteil = c14.decide(_messung(schaden=("origin:top5_vs_other",)))
    assert urteil["verdict"] == c14.VERDICT_REJECTED
    assert urteil["conditions"]["no_severe_segment_damage"] is False


def test_eine_schlechtere_primaermetrik_wird_abgelehnt():
    urteil = c14.decide(_messung(delta=+0.01, ci_low=-0.01, ci_high=+0.03))
    assert urteil["verdict"] == c14.VERDICT_REJECTED
    assert urteil["conditions"]["primary_better"] is False


def test_ein_schwer_beschaedigter_kontextbestand_verhindert_accepted():
    """
    Die einzige Kontextbedingung, die sperrt - und sie stand vor der
    Messung im Vertrag.
    """
    urteil = c14.decide(_messung(kontext_delta=+0.02))
    assert urteil["verdict"] == c14.VERDICT_REJECTED
    assert urteil["conditions"]["context_not_severely_damaged"] is False


def test_ein_leicht_schlechterer_kontext_sperrt_nicht():
    urteil = c14.decide(_messung(kontext_delta=+0.002))
    assert urteil["verdict"] == c14.VERDICT_ACCEPTED


def test_zu_wenige_daten_sind_nicht_auswertbar():
    urteil = c14.decide(_messung(n=10))
    assert urteil["verdict"] == c14.VERDICT_NOT_EVALUABLE
    urteil = c14.decide({"standard": {"aggregate": {}, "folds": []},
                         "context": {}})
    assert urteil["verdict"] == c14.VERDICT_NOT_EVALUABLE


def test_ein_einbrechender_kalibrierungswert_verhindert_accepted():
    urteil = c14.decide(_messung(kalib_basis=0.03, kalib_ml=0.09))
    assert urteil["conditions"]["calibration_holds"] is False
    assert urteil["verdict"] != c14.VERDICT_ACCEPTED


def test_schlechterer_brier_oder_rps_wird_abgelehnt():
    assert c14.decide(_messung(brier=+0.01))["verdict"] == (
        c14.VERDICT_REJECTED)
    assert c14.decide(_messung(rps=+0.01))["verdict"] == (
        c14.VERDICT_REJECTED)


def test_ein_dominierender_fold_verhindert_accepted():
    """Zwei Folds sind wenig. Traegt einer alles, ist es die Saison."""
    urteil = c14.decide(_messung(folds=(-0.0399, -0.0001), delta=-0.02))
    assert urteil["conditions"]["no_single_fold_carries_all"] is False


def test_jedes_urteil_traegt_den_vertragsfingerabdruck():
    for messung in (_messung(), _messung(delta=+0.01), _messung(n=5)):
        urteil = c14.decide(messung)
        assert urteil["contract_fingerprint"] == VERTRAG_FINGERABDRUCK
        assert c14.assert_contract_matches(urteil) is True


def test_ein_ergebnis_kann_die_gates_nicht_ueberschreiben():
    """
    Ein Messergebnis, das eine Bedingung mitliefert, darf sie nicht
    setzen. Die Bedingungen entstehen ausschliesslich aus den Zahlen.
    """
    messung = _messung(delta=+0.05, ci_low=+0.01, ci_high=+0.09)
    messung["conditions"] = {"primary_better": True}
    messung["verdict"] = c14.VERDICT_ACCEPTED
    urteil = c14.decide(messung)
    assert urteil["verdict"] == c14.VERDICT_REJECTED
    assert urteil["conditions"]["primary_better"] is False


# ===========================================================================
# 6  Konzentration
# ===========================================================================

def test_die_konzentration_ist_ausdruecklich_kein_gate():
    zeilen = [_zeile(home_id=i, away_id=i + 100) for i in range(40)]
    k = c14.concentration(zeilen, [1.0] * 40, [0.9] * 40)
    assert k["is_a_gate"] is False
    assert "keine numerische Schwelle" in k["why_not_a_gate"]
    assert k["top_n_share"] is not None


def test_die_konzentration_findet_einen_dominierenden_verein():
    zeilen = [_zeile(home_id=1, away_id=2) for _ in range(35)]
    basis = [1.0] * 35
    ml = [1.0] * 35
    ml[0] = 0.0                                   # ein einziger Ausreisser
    k = c14.concentration(zeilen, basis, ml)
    assert k["top_contributors"][0]["team_id"] in (1, 2)
    assert k["top_n_share"] is not None


# ===========================================================================
# 7  Das Ergebnisartefakt
# ===========================================================================

@pytest.fixture(scope="module")
def artefakt():
    pfad = WURZEL / c14.ARTIFACT_PATH
    if not pfad.is_file():
        pytest.skip("C14 wurde noch nicht ausgefuehrt")
    return json.loads(pfad.read_text(encoding="utf-8"))


def test_das_artefakt_bindet_den_vertrag(artefakt):
    assert artefakt["contract_fingerprint"] == VERTRAG_FINGERABDRUCK
    assert artefakt["contract_frozen_before_measurement"] is True
    assert artefakt["verdict"] in c14.VERDICTS


def test_das_artefakt_bindet_alle_vorvertraege(artefakt):
    from src.ml import c13_contract as c13
    from src.ml import early_v2 as e9

    gebunden = artefakt["bound_contracts"]
    assert gebunden["c9_schema_fingerprint"] == e9.schema_fingerprint()
    assert (gebunden["c13_contract_fingerprint"]
            == c13.contract_fingerprint())
    assert gebunden["c10_cutoff_hour"] == 12


def test_der_ergebnisfingerabdruck_ignoriert_zeit_und_git(artefakt):
    """
    Zwei Laeufe mit denselben Eingaben muessen denselben fachlichen
    Wert liefern. Sonst waere jede Aussage ueber Reproduzierbarkeit
    wertlos.
    """
    veraendert = dict(artefakt, created_at="1999-01-01T00:00:00+00:00",
                      git_commit="abc123")
    assert (c14.result_fingerprint(veraendert)
            == c14.result_fingerprint(artefakt)
            == artefakt["result_fingerprint"])


def test_das_artefakt_enthaelt_keine_geheimnisse_und_keine_pfade(artefakt):
    text = json.dumps(artefakt, ensure_ascii=False)
    for verboten in ("C:\\\\", "/home/", "Users\\\\", "api_key",
                     "APISPORTS_KEY", "secret", "password", "Bearer"):
        assert verboten.lower() not in text.lower(), verboten


def test_das_artefakt_nennt_das_fehlende_holdout(artefakt):
    grenzen = " ".join(artefakt["known_limits"]).lower()
    assert "holdout" in grenzen
    assert artefakt["decision"]["holdout_caveat"]


# ===========================================================================
# 8  Registry und Modustrennung
# ===========================================================================

def test_das_c14_urteil_hat_nichts_aktiviert():
    """
    GEAENDERT IN V2-C17.

    C14 endete mit `rejected` und hat nichts aktiviert. Aktiviert
    wurde spaeter das C16-Modell. Geprueft wird deshalb, dass kein
    Modell im Schatten haengt und ein aktives Modell eine gueltige
    Freigabe traegt.
    """
    from src.ml import model_registry as mr

    dokument = mr.load_registry()
    assert mr.shadow_entries() == []
    for modell in dokument.get("models") or []:
        assert modell["stage"] in (mr.STAGE_CANDIDATE, mr.STAGE_ACTIVE,
                                   mr.STAGE_ROLLBACK)
        if modell["stage"] == mr.STAGE_ACTIVE:
            assert modell.get("approval")
            assert modell["evaluation_status"] == mr.EVALUATION_ACCEPTED


def test_c14_erzeugt_ohne_accepted_kein_bundle(artefakt):
    """
    Ein Releasebundle ohne Freigabe waere eine Behauptung, die spaeter
    jemand fuer eine Entscheidung haelt.
    """
    if artefakt["verdict"] == c14.VERDICT_ACCEPTED:
        pytest.skip("bei accepted wird ein Kandidatenbundle erwartet")
    assert artefakt["registry"]["bundle_created"] is False
    assert artefakt["registry"]["changed_by_c14"] is False
    assert artefakt["registry"]["active_model"] is None


def test_die_ligasimulation_kennt_weiterhin_kein_ml():
    """Die Modustrennung, unveraendert seit V2-C10."""
    quelle = (WURZEL / "src" / "predict" / "league_match_sim.py").read_text(
        encoding="utf-8")
    assert "src.ml" not in quelle


def test_der_registrygate_bleibt_der_entscheider():
    """
    GEAENDERT IN V2-C17.

    C14 misst und aktiviert nichts - das gilt weiterhin. Ob ein
    Modell die Antwort bestimmt, entscheidet ausschliesslich die
    Registry, und ein aktives Modell muss dort eine Freigabe tragen.
    """
    from src.ml import model_registry as mr
    from src.ml import runtime

    assert hasattr(runtime, "REASON_NOT_ACTIVE_IN_REGISTRY")
    eintrag, grund = mr.active_entry()
    if eintrag is None:
        assert grund == "no_active_model"
    else:
        assert eintrag.get("approval")
