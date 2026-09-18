"""
V2-C22: Der Freigabeweg verlangt beide Nachweise und seine Dateien.

Bis C21 las `c16_release.release()` nur die C20-Match-Messung. Die
C21-Saisonfreigabe, die Dateiabhaengigkeiten und die Gleichheit einer
vorhandenen Bundledatei mit dem Neubau standen im Runbook, nicht im
Code. Diese Datei haelt fest, dass jede dieser Bedingungen jetzt
fail-closed im Freigabeweg selbst geprueft wird:

  1. C21-Saisonfreigabe: vorhanden, accepted, an den eingefrorenen
     Vertrag und an genau diesen Modellstand gebunden,
  2. Dateiabhaengigkeiten C9, C10, C16, C17, inklusive der indirekten
     C16-Abhaengigkeit des C17-Vertragsfingerabdrucks,
  3. vorhandene Bundledatei nur bei inhaltlicher Gleichheit,
  4. erwartete Modell-ID als Stopkriterium.

Die teure Rechnung (Datensatz, Bundlebau) wird hier durch Attrappen
ersetzt, wo nur die Entscheidungslogik geprueft wird. Der echte Weg mit
echtem Neubau laeuft in tests/test_c21_release_readiness.py.
"""

import copy
import json
import os
import shutil

import pytest

from src.ml import c16_damped_league_strength as c16
from src.ml import c16_release as rel
from src.ml import c17_bundle_contract as c17
from src.ml import c20_temporal_map as c20
from src.ml import c21_season_validation as c21

ROOT = rel._repo_root()


def _json(relativ):
    with open(os.path.join(ROOT, relativ), encoding="utf-8") as datei:
        return json.load(datei)


def _schreiben(wurzel, relativ, dokument):
    ziel = os.path.join(str(wurzel), relativ)
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    with open(ziel, "w", encoding="utf-8") as datei:
        json.dump(dokument, datei)


@pytest.fixture(scope="module")
def vertrag():
    return _json(c21.CONTRACT_PATH)


@pytest.fixture(scope="module")
def ergebnis():
    return _json(c21.RESULT_PATH)


@pytest.fixture(scope="module")
def evaluation():
    return _json(c20.EVALUATION_PATH)


@pytest.fixture
def folds_wie_gemessen(monkeypatch, ergebnis):
    """
    Der Foldbau liefert die IDs, die C21 gemessen hat - ohne den
    Datensatz zu bauen. Dass der echte Neubau genau diese IDs ergibt,
    prueft der Trockenlauf in test_c21_release_readiness.py.
    """
    ids = {s: ergebnis["binding"][str(s)]["model_id"] for s in c21.SEASONS}
    monkeypatch.setattr(c21, "fold_bundle",
                        lambda s, z, e: {"model_id": ids[s]})
    return ids


def _nachweis(tmp_path, vertrag, ergebnis, evaluation):
    _schreiben(tmp_path, c21.CONTRACT_PATH, vertrag)
    _schreiben(tmp_path, c21.RESULT_PATH, ergebnis)
    return c21.release_evidence([], evaluation, repo_root=str(tmp_path))


# ---------------------------------------------------------------------------
# 1. Die C21-Saisonfreigabe
# ---------------------------------------------------------------------------

class TestSaisonfreigabe:

    def test_die_echten_artefakte_tragen(self, tmp_path, vertrag, ergebnis,
                                         evaluation, folds_wie_gemessen):
        ok, befunde, bericht = _nachweis(tmp_path, vertrag, ergebnis,
                                         evaluation)
        assert ok, befunde
        assert bericht["verdict"] == "accepted"
        assert bericht["fold_models"] == [folds_wie_gemessen[s]
                                          for s in c21.SEASONS]

    def test_ohne_ergebnis_keine_freigabe(self, tmp_path, vertrag,
                                         evaluation):
        _schreiben(tmp_path, c21.CONTRACT_PATH, vertrag)
        ok, befunde, _b = c21.release_evidence([], evaluation,
                                               repo_root=str(tmp_path))
        assert not ok
        assert "fehlt" in befunde[0]

    def test_ohne_vertrag_keine_freigabe(self, tmp_path, ergebnis,
                                        evaluation):
        _schreiben(tmp_path, c21.RESULT_PATH, ergebnis)
        ok, befunde, _b = c21.release_evidence([], evaluation,
                                               repo_root=str(tmp_path))
        assert not ok
        assert "Vertragsartefakt" in befunde[0]

    def test_ein_unlesbares_ergebnis_wird_abgewiesen(self, tmp_path, vertrag,
                                                     evaluation):
        _schreiben(tmp_path, c21.CONTRACT_PATH, vertrag)
        ziel = tmp_path / c21.RESULT_PATH
        ziel.write_text("{kein json", encoding="utf-8")
        ok, befunde, _b = c21.release_evidence([], evaluation,
                                               repo_root=str(tmp_path))
        assert not ok
        assert "unlesbar" in befunde[0]

    @pytest.mark.parametrize("aenderung,erwartet", [
        (lambda e: e["decision"].__setitem__("verdict", "rejected"),
         "nicht accepted"),
        (lambda e: e["decision"]["conditions"].__setitem__(
            "S3_updated_forecasts_noninferior", False),
         "S1 bis S6"),
        (lambda e: e["decision"].__setitem__(
            "failed_conditions", ["S5_monte_carlo_stable"]),
         "S1 bis S6"),
        (lambda e: e.__setitem__("contract_fingerprint", "0" * 64),
         "nicht an den geltenden"),
        (lambda e: e["decision"].__setitem__("contract_fingerprint",
                                             "0" * 64),
         "nicht an den geltenden"),
        (lambda e: e.__setitem__("technical_findings", ["Paritaet 1e-3"]),
         "technische Befunde"),
        (lambda e: e.__setitem__("created_at", "2000-01-01T00:00:00+00:00"),
         "vor dem Ergebnis"),
        (lambda e: e.__setitem__("schema_version", "v2-c21.0"),
         "Fassung"),
    ])
    def test_ein_veraendertes_ergebnis_wird_abgewiesen(
            self, tmp_path, vertrag, ergebnis, evaluation,
            folds_wie_gemessen, aenderung, erwartet):
        falsch = copy.deepcopy(ergebnis)
        aenderung(falsch)
        ok, befunde, _b = _nachweis(tmp_path, vertrag, falsch, evaluation)
        assert not ok
        assert any(erwartet in b for b in befunde), befunde

    def test_ein_veraenderter_vertrag_wird_abgewiesen(
            self, tmp_path, vertrag, ergebnis, evaluation,
            folds_wie_gemessen):
        falsch = copy.deepcopy(vertrag)
        falsch["contract_fingerprint"] = "0" * 64
        ok, befunde, _b = _nachweis(tmp_path, falsch, ergebnis, evaluation)
        assert not ok
        assert any("eingefrorene C21-Vertrag" in b for b in befunde)

    def test_ein_nicht_eingefrorener_vertrag_wird_abgewiesen(
            self, tmp_path, vertrag, ergebnis, evaluation,
            folds_wie_gemessen):
        falsch = copy.deepcopy(vertrag)
        falsch["frozen_before_measurement"] = False
        ok, befunde, _b = _nachweis(tmp_path, falsch, ergebnis, evaluation)
        assert not ok

    def test_eine_andere_c20_karte_wird_abgewiesen(
            self, tmp_path, vertrag, ergebnis, evaluation,
            folds_wie_gemessen):
        fremd = copy.deepcopy(evaluation)
        fremd["map_contract"]["contract_fingerprint"] = "0" * 64
        ok, befunde, _b = _nachweis(tmp_path, vertrag, ergebnis, fremd)
        assert not ok
        assert any("Zuordnungsvertrag" in b for b in befunde)

    def test_ein_fremdes_foldmodell_wird_abgewiesen(
            self, tmp_path, vertrag, ergebnis, evaluation,
            folds_wie_gemessen):
        """
        Der eigentliche Kern: Ein Saisonergebnis, das auf einem anderen
        Modellstand gemessen wurde, traegt eine andere Fold-ID.
        """
        falsch = copy.deepcopy(ergebnis)
        falsch["binding"]["2025"]["model_id"] = "clm-fremd-lsfremd"
        falsch["binding"]["2025"]["active_in_isolated_registry"] = \
            "clm-fremd-lsfremd"
        ok, befunde, _b = _nachweis(tmp_path, vertrag, falsch, evaluation)
        assert not ok
        assert any("derselbe Stand baut" in b for b in befunde)

    def test_ein_nicht_aktiv_gemessenes_foldmodell_wird_abgewiesen(
            self, tmp_path, vertrag, ergebnis, evaluation,
            folds_wie_gemessen):
        falsch = copy.deepcopy(ergebnis)
        falsch["binding"]["2024"]["isolated_release_status"] = "refused"
        ok, befunde, _b = _nachweis(tmp_path, vertrag, falsch, evaluation)
        assert not ok

    def test_ein_nicht_baubares_foldmodell_ist_ein_befund(
            self, tmp_path, vertrag, ergebnis, evaluation, monkeypatch):
        def _bricht(s, z, e):
            raise rel.ReleaseError("Bundlevertrag")
        monkeypatch.setattr(c21, "fold_bundle", _bricht)
        ok, befunde, _b = _nachweis(tmp_path, vertrag, ergebnis, evaluation)
        assert not ok
        assert any("nicht baubar" in b for b in befunde)

    def test_die_pruefung_veraendert_den_vertrag_nicht(self, vertrag):
        assert vertrag["contract_fingerprint"] == c21.contract_fingerprint()


# ---------------------------------------------------------------------------
# 2. Die Dateiabhaengigkeiten
# ---------------------------------------------------------------------------

class TestDateiabhaengigkeiten:

    def test_im_repository_ist_alles_vorhanden(self):
        assert rel.dependency_findings() == []

    def test_fehlt_das_c16_artefakt_faellt_es_zweifach_auf(self,
                                                          monkeypatch):
        monkeypatch.setattr(c16, "ARTIFACT_PATH",
                            "data/ml/gibt_es_nicht_c16.json")
        befunde = rel.dependency_findings()
        assert any("C16-Messartefakt fehlt" in b for b in befunde)
        assert any("C17-Vertragsfingerabdruck" in b for b in befunde)

    def test_ein_veraendertes_c16_artefakt_faellt_auf(self, monkeypatch,
                                                      tmp_path):
        """Manipuliert statt fehlend: der C17-Fingerabdruck verraet es."""
        falsch = _json(c16.ARTIFACT_PATH)
        falsch["result_fingerprint"] = "0" * 64
        ziel = tmp_path / "c16_manipuliert.json"
        ziel.write_text(json.dumps(falsch), encoding="utf-8")
        monkeypatch.setattr(c16, "ARTIFACT_PATH", str(ziel))
        befunde = rel.dependency_findings()
        assert befunde == ["der C17-Vertragsfingerabdruck weicht vom "
                           "eingefrorenen ab (C16-Messartefakt fehlt oder "
                           "wurde veraendert?)"]

    def test_fehlt_das_c10_artefakt_wird_es_benannt(self, monkeypatch):
        from src.ml import c10_contract as c10
        monkeypatch.setattr(c10, "ARTIFACT_PATH",
                            "data/ml/gibt_es_nicht_c10.json")
        befunde = rel.dependency_findings()
        assert any("C10-Vertragsartefakt" in b for b in befunde)

    def test_fehlt_das_c17_artefakt_wird_es_benannt(self, monkeypatch):
        monkeypatch.setattr(c17, "CONTRACT_PATH",
                            "data/ml/gibt_es_nicht_c17.json")
        befunde = rel.dependency_findings()
        assert any("C17-Vertragsartefakt fehlt" in b for b in befunde)

    def test_der_c17_fingerabdruck_haengt_nicht_am_arbeitsverzeichnis(
            self, monkeypatch, tmp_path):
        """
        Bis C21 las C17 das C16-Artefakt relativ zum Arbeitsverzeichnis;
        aus einem anderen Verzeichnis entstand still ein anderer
        Fingerabdruck.
        """
        erwartet = _json(c17.CONTRACT_PATH)["contract_fingerprint"]
        monkeypatch.chdir(tmp_path)
        assert c17.contract_fingerprint() == erwartet

    def test_der_kandidat_traegt_denselben_c17_fingerabdruck(self):
        kandidat = _json("data/ml/models/clm-936ecce472696ccb-ls1c4f4e1d"
                         ".json")
        assert kandidat["contract_bindings"]["c17_contract_fingerprint"] == \
            c17.contract_fingerprint()


# ---------------------------------------------------------------------------
# 3. Vorhandene Bundledatei gegen Neubau
# ---------------------------------------------------------------------------

class TestBundlevergleich:

    BUNDLE = {"model_id": "clm-x-lsy", "alpha": 0.1, "models": {"home": [1.0]},
              "contract_bindings": {"c17_contract_fingerprint": "a"},
              "created_at": "2026-01-01T00:00:00+00:00",
              "provenance": {"git_commit": "1",
                             "git_status": {"porcelain": 3},
                             "dataset_fingerprint": {"sha256": "d"}}}

    def test_nur_baumetadaten_ist_kein_befund(self):
        neu = copy.deepcopy(self.BUNDLE)
        neu["created_at"] = "2026-09-13T00:00:00+00:00"
        neu["provenance"]["git_status"]["porcelain"] = 9
        alle, modell = rel.bundle_mismatch(self.BUNDLE, neu)
        assert set(alle) == {"created_at", "provenance/git_status/porcelain"}
        assert modell == []

    @pytest.mark.parametrize("pfad", [
        ("alpha",), ("models", "home"),
        ("contract_bindings", "c17_contract_fingerprint"),
        ("provenance", "dataset_fingerprint", "sha256")])
    def test_jedes_modellfeld_ist_ein_befund(self, pfad):
        neu = copy.deepcopy(self.BUNDLE)
        ziel = neu
        for schritt in pfad[:-1]:
            ziel = ziel[schritt]
        ziel[pfad[-1]] = "anders"
        _alle, modell = rel.bundle_mismatch(self.BUNDLE, neu)
        assert modell == ["/".join(pfad)]

    def test_tupel_im_neubau_sind_keine_abweichung(self):
        neu = copy.deepcopy(self.BUNDLE)
        neu["models"]["home"] = (1.0,)
        assert rel.bundle_mismatch(self.BUNDLE, neu) == ([], [])


# ---------------------------------------------------------------------------
# 4. Die Entscheidungslogik von release()
# ---------------------------------------------------------------------------

@pytest.fixture
def freigabeweg(monkeypatch, tmp_path):
    """
    Der echte release()-Ablauf mit Attrappen fuer Datensatz, Karte,
    Saisonnachweis und Bundlebau. Die C20-Messung liegt als echte Kopie
    im temporaeren Wurzelverzeichnis.
    """
    from src.ml import dataset as ds

    ziel = tmp_path / c20.EVALUATION_PATH
    ziel.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(os.path.join(ROOT, c20.EVALUATION_PATH), ziel)

    aufrufe = {"dataset": 0}

    def _datensatz(**kw):
        aufrufe["dataset"] += 1
        return [], {}

    monkeypatch.setattr(ds, "build_dataset", _datensatz)
    monkeypatch.setattr(c20, "production_map", lambda s: ({}, {
        "teams": 0, "upto_season": 2026, "seasons_used": [],
        "map_fingerprint": "f" * 64}))
    monkeypatch.setattr(c21, "release_evidence", lambda z, e, repo_root: (
        True, [], {"fold_models": ["a", "b"], "verdict": "accepted"}))
    gebaut = copy.deepcopy(TestBundlevergleich.BUNDLE)
    monkeypatch.setattr(rel, "build_final_bundle", lambda *a, **kw: (
        copy.deepcopy(gebaut), {"gamma": 1.0, "league_alpha": 0.1,
                                "leagues": 0, "teams_mapped": 0}))
    return {"root": tmp_path, "calls": aufrufe, "bundle": gebaut}


class TestReleaseEntscheidung:

    def test_fehlende_abhaengigkeit_bricht_vor_dem_datensatz_ab(
            self, freigabeweg, monkeypatch):
        monkeypatch.setattr(c16, "ARTIFACT_PATH",
                            "data/ml/gibt_es_nicht_c16.json")
        r = rel.release(dry_run=True, repo_root=str(freigabeweg["root"]))
        assert r["status"] == "refused"
        assert "C16-Messartefakt" in r["reason"]
        assert freigabeweg["calls"]["dataset"] == 0
        assert r["wrote_anything"] is False

    def test_ohne_saisonfreigabe_keine_freigabe(self, freigabeweg,
                                               monkeypatch):
        monkeypatch.setattr(c21, "release_evidence", lambda z, e, repo_root: (
            False, ["das C21-Urteil lautet 'rejected', nicht accepted"], {}))
        r = rel.release(dry_run=True, repo_root=str(freigabeweg["root"]))
        assert r["status"] == "refused"
        assert r["reason"].startswith("C21-Saisonfreigabe")
        assert not (freigabeweg["root"] / rel.BUNDLE_DIR).exists()

    def test_ohne_c21_artefakte_im_echten_ablauf_keine_freigabe(
            self, freigabeweg, monkeypatch):
        """Mit dem echten Nachweis: Die Kopie traegt kein C21-Ergebnis."""
        monkeypatch.setattr(c21, "release_evidence", _ECHTER_NACHWEIS)
        r = rel.release(dry_run=True, repo_root=str(freigabeweg["root"]))
        assert r["status"] == "refused"
        assert "C21" in r["reason"]

    def test_eine_andere_modell_id_wird_abgewiesen(self, freigabeweg):
        r = rel.release(dry_run=True, repo_root=str(freigabeweg["root"]),
                        expected_model_id="clm-936ecce472696ccb-ls1c4f4e1d")
        assert r["status"] == "refused"
        assert "erwartet war" in r["reason"]
        assert not (freigabeweg["root"] / rel.BUNDLE_DIR).exists()

    def test_eine_abweichende_vorhandene_datei_blockiert(self, freigabeweg):
        vorhanden = copy.deepcopy(freigabeweg["bundle"])
        vorhanden["contract_bindings"]["c17_contract_fingerprint"] = "fremd"
        _schreiben(freigabeweg["root"], "data/ml/models/clm-x-lsy.json",
                   vorhanden)
        r = rel.release(dry_run=True, repo_root=str(freigabeweg["root"]))
        assert r["status"] == "blocked_by_bundle_mismatch"
        assert r["bundle_comparison"]["model_fields_differing"] == [
            "contract_bindings/c17_contract_fingerprint"]
        assert r["wrote_anything"] is False
        assert not (freigabeweg["root"] / "data" / "ml"
                    / "model_registry.json").exists()

    def test_eine_unlesbare_vorhandene_datei_blockiert(self, freigabeweg):
        ziel = freigabeweg["root"] / "data" / "ml" / "models"
        ziel.mkdir(parents=True, exist_ok=True)
        (ziel / "clm-x-lsy.json").write_text("{kaputt", encoding="utf-8")
        r = rel.release(dry_run=True, repo_root=str(freigabeweg["root"]))
        assert r["status"] == "blocked_by_bundle_mismatch"


#: Beim Import festgehalten, bevor eine Attrappe ihn ersetzt.
_ECHTER_NACHWEIS = c21.release_evidence


# ---------------------------------------------------------------------------
# 5. Die CLI reicht das Stopkriterium durch
# ---------------------------------------------------------------------------

def test_die_cli_reicht_die_erwartete_modell_id_durch(monkeypatch):
    import run_ml

    gesehen = {}

    def _release(dry_run=True, repo_root=None, expected_model_id=None):
        gesehen.update(dry_run=dry_run, expected=expected_model_id)
        return {"status": "dry_run_ok", "log": [], "model_id": "x"}

    monkeypatch.setattr(rel, "release", _release)

    class _Args:
        release_c16 = "dry-run"
        expect_model_id = "clm-936ecce472696ccb-ls1c4f4e1d"

    assert run_ml._release_c16(_Args()) == 0
    assert gesehen == {"dry_run": True,
                       "expected": "clm-936ecce472696ccb-ls1c4f4e1d"}


def test_blockiert_ist_fuer_die_cli_ein_fehler(monkeypatch):
    import run_ml

    monkeypatch.setattr(rel, "release", lambda **kw: {
        "status": "blocked_by_bundle_mismatch", "log": [], "reason": "x"})

    class _Args:
        release_c16 = "apply"
        expect_model_id = None

    assert run_ml._release_c16(_Args()) == 1
