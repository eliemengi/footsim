"""
V2-C21: Zustandsfreie Release-Vorbereitung.

Die reale Freigabe des C20-Kandidaten ist ein eigener, ausdruecklich
autorisierter Schritt. Diese Datei prueft alles, was sich davor ohne
Wirkung auf den Produktionszustand pruefen laesst, mit denselben
Funktionen, die spaeter real laufen:

  - Trockenlauf des exakten Kandidaten, in einer Kopie des Zustands,
  - Aktivierung ueber apply_release und Rollback, ebenfalls in einer
    Kopie,
  - die Antwort der Laufzeit und der HTTP-Schnittstelle: Modell-ID und
    applied, mit und ohne approach=ml.

Die echte Registry und das echte Modellverzeichnis werden nur gelesen.
Die letzte Klasse prueft genau das.

Laufzeit: Trockenlauf und Aktivierung bauen je einmal das Bundle aus dem
vollen Datensatz, zusammen rund fuenf Minuten. Beide laufen je Modul nur
einmal.

GEAENDERT IN V2-C22
Beide Proben stellen in der Kopie zuerst den Vorzustand her (nach der
lokalen Aktivierung ueber den echten Rollback). Der Trockenlauf findet
die gespeicherte Kandidatendatei vor und muss sie gegen seinen Neubau
pruefen; die Aktivierung baut die Datei neu, wie auf einem VPS ohne
mitgelieferte Datei. Der Stand der echten Registry kommt aus
tests/live_registry_state.py.
"""

import json
import os

import pytest

from src.ml import c20_temporal_map as c20
from src.ml import c21_release_readiness as rr
from src.ml import c21_season_validation as c21
from src.ml import c22_release_equivalence as c22
from src.ml import model_registry as mr
from tests import live_registry_state as live

ROOT = rr._repo_root()
MODELLE = os.path.join(ROOT, "data", "ml", "models")

#: Das Modell, das vor der Aktivierung aktiv war und nach jedem
#: Rollback wieder aktiv sein muss.
VORZUSTAND_ID = live.PRE_C22_ACTIVE_ID

BAYERN, ARSENAL = rr.PROBE_MATCH["home_id"], rr.PROBE_MATCH["away_id"]


def _json(relativ):
    with open(os.path.join(ROOT, relativ), encoding="utf-8") as datei:
        return json.load(datei)


def _echter_zustand():
    return (mr.registry_fingerprint(mr.load_registry()),
            sorted(os.listdir(MODELLE)))


@pytest.fixture(scope="module")
def kandidat():
    if not os.path.isfile(os.path.join(ROOT, rr.CANDIDATE_PATH)):
        pytest.skip("der C20-Kandidat liegt nicht vor")
    return _json(rr.CANDIDATE_PATH)


@pytest.fixture(scope="module")
def evaluation():
    return _json(c20.EVALUATION_PATH)


@pytest.fixture(scope="module")
def zustand_vorher():
    return _echter_zustand()


# ---------------------------------------------------------------------------
# 1. Der Kandidat
# ---------------------------------------------------------------------------

class TestKandidat:

    def test_die_kandidatendatei_ist_die_aus_c20(self, kandidat):
        assert kandidat["model_id"] == rr.CANDIDATE_ID
        assert rr._sha(os.path.join(ROOT, rr.CANDIDATE_PATH)) == \
            rr.CANDIDATE_SHA256

    def test_die_c20_messung_ist_accepted_und_gebunden(self, evaluation):
        assert evaluation["decision"]["verdict"] == "accepted"
        assert evaluation["map_contract"]["contract_fingerprint"] == \
            c20.contract_fingerprint()

    def test_die_saisonvalidierung_ist_accepted(self):
        pfad = os.path.join(ROOT, c21.RESULT_PATH)
        if not os.path.isfile(pfad):
            pytest.skip("die C21-Messung liegt nicht vor")
        assert _json(c21.RESULT_PATH)["decision"]["verdict"] == "accepted"

    def test_die_echte_registry_steht_im_autorisierten_zustand(
            self, kandidat):
        """
        GEAENDERT IN V2-C22. Bis C21: "der Kandidat ist nicht in der
        echten Registry". Seit der autorisierten lokalen Aktivierung steht
        dort, was tests/live_registry_state.py nennt - exakt.
        """
        ids = [m["model_id"] for m in mr.load_registry()["models"]]
        assert (rr.CANDIDATE_ID in ids) is (live.ACTIVE_ID == rr.CANDIDATE_ID)
        assert mr.active_entry()[0]["model_id"] == live.ACTIVE_ID


# ---------------------------------------------------------------------------
# 2. Der Feldvergleich
# ---------------------------------------------------------------------------

class TestFeldvergleich:

    def test_gleiche_dokumente_haben_keine_abweichung(self):
        assert rr.differing_fields({"a": [1, {"b": 2}]},
                                   {"a": [1, {"b": 2}]}) == []

    def test_jede_abweichung_wird_mit_pfad_gemeldet(self):
        a = {"created_at": "x", "provenance": {"git_commit": "1", "n": 3},
             "coef": [1.0, 2.0]}
        b = {"created_at": "y", "provenance": {"git_commit": "2", "n": 3},
             "coef": [1.0, 2.5]}
        assert rr.differing_fields(a, b) == [
            "coef[1]", "created_at", "provenance/git_commit"]

    def test_fehlende_schluessel_und_laengen_zaehlen(self):
        assert rr.differing_fields({"a": 1}, {"b": 1}) == ["a", "b"]
        assert rr.differing_fields({"l": [1]}, {"l": [1, 2]}) == ["l"]

    def test_als_baumetadaten_gilt_nur_die_bauumgebung(self):
        for pfad in ("created_at", "provenance/git_commit",
                     "provenance/git_status/porcelain",
                     "provenance/git_status/untracked",
                     "provenance/python_version",
                     "provenance/sklearn_version", "provenance/platform"):
            assert rr.is_build_metadata(pfad), pfad
        for pfad in ("models[0]", "league_strength/attack/PD",
                     "contract_bindings/c17_contract_fingerprint",
                     "provenance/dataset_fingerprint/sha256",
                     "provenance/evaluation/evaluation_sha256",
                     "integrity/models_sha256", "model_id", "alpha",
                     "provenance/git_commitment"):
            assert not rr.is_build_metadata(pfad), pfad


# ---------------------------------------------------------------------------
# 3. Trockenlauf des exakten Kandidaten
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def trockenlauf(kandidat, zustand_vorher):
    return rr.dry_run_candidate()


class TestTrockenlauf:

    def test_er_besteht(self, trockenlauf):
        assert trockenlauf["status"] == "dry_run_ok"
        assert trockenlauf["wrote_anything"] is False

    def test_er_baut_genau_den_kandidaten(self, trockenlauf):
        """
        GEAENDERT IN V2-C22: Freigegeben wird immer der gespeicherte
        Kandidat. In der Referenzumgebung ist der Neubau bitgleich mit
        ihm; anderswo bestaetigt ihn der Neubau unter dem eingefrorenen
        Aequivalenzvertrag und traegt dabei eine eigene Modell-ID.
        """
        assert trockenlauf["model_id"] == rr.CANDIDATE_ID
        assert trockenlauf["stored_candidate_matches_c20"] is True
        if c22.is_reference_environment():
            assert trockenlauf["comparison_mode"] == "exact"
            assert trockenlauf["rebuilt_model_id"] in (None, rr.CANDIDATE_ID)
        else:
            assert trockenlauf["comparison_mode"] in ("exact", "equivalent")

    def test_er_startet_im_vorzustand(self, trockenlauf):
        assert trockenlauf["pre_activation"]["pre_activation_active"] == \
            VORZUSTAND_ID

    def test_die_vorhandene_datei_gleicht_dem_neubau(self, trockenlauf):
        """
        V2-C22: Die gespeicherte Kandidatendatei wird nur uebernommen,
        weil sie dem Neubau in jedem modellrelevanten Feld gleicht. Ihr
        Dateihash ist ein anderer als der eines Neubaus - Bauzeitpunkt
        und Zustand des Arbeitsbaums stehen im Bundle -, alles andere
        ist gleich: Koeffizienten, Ligakarte, Bindungen.

        In einer anderen numerischen Umgebung weichen zusaetzlich genau
        die Zahlenfelder ab, die der eingefrorene Aequivalenzvertrag
        nennt - innerhalb seiner Toleranz -, und die daraus abgeleiteten
        Kennungen. Kein anderes Feld.
        """
        assert trockenlauf["existing_file_used"] is True
        assert trockenlauf["model_fields_differing"] == []
        if c22.is_reference_environment():
            assert trockenlauf["comparison_mode"] == "exact"
            assert all(rr.is_build_metadata(p)
                       for p in trockenlauf["differing_fields"])
            return
        erlaubt = (set(trockenlauf["tolerated_fields"])
                   | set(trockenlauf["derived_identity_fields"]))
        assert all(rr.is_build_metadata(p) or p in erlaubt
                   for p in trockenlauf["differing_fields"])
        if trockenlauf["comparison_mode"] == "equivalent":
            bericht = trockenlauf["equivalence"]
            assert bericht["tolerance_contract_fingerprint"] == \
                c22.contract_fingerprint()
            assert bericht["structural_mismatches"] == []
            assert bericht["numerical_mismatches"] == []
            assert bericht["prediction"]["within_tolerance"] is True
            assert bericht["prediction"]["rows"] == 283

    def test_die_saisonfreigabe_ist_gebunden(self, trockenlauf):
        """V2-C22: C21 muss genau diese Foldmodelle gemessen haben."""
        nachweis = trockenlauf["season_evidence"]
        bindung = _json(c21.RESULT_PATH)["binding"]
        assert nachweis["verdict"] == "accepted"
        assert nachweis["fold_models"] == [
            bindung[str(s)]["model_id"] for s in c21.SEASONS]
        vergleiche = nachweis["fold_comparisons"]
        for s in c21.SEASONS:
            vergleich = vergleiche[str(s)]
            assert vergleich["reference_model_id"] == \
                bindung[str(s)]["model_id"]
            if c22.is_reference_environment():
                assert vergleich["mode"] == "exact", vergleich
            else:
                assert vergleich["mode"] in ("exact", "equivalent")

    def test_die_temporaere_registry_bleibt_im_trockenlauf_gleich(
            self, trockenlauf):
        assert trockenlauf["temporary_registry_unchanged"] is True
        assert trockenlauf["real_registry_unchanged"] is True


# ---------------------------------------------------------------------------
# 4. Aktivierung und Rollback, isoliert
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def probe(kandidat, zustand_vorher):
    return rr.activation_rollback_probe()


class TestAktivierungUndRollback:

    def test_ausgangspunkt_ist_der_vorzustand(self, probe):
        assert probe["pre_activation"]["start_active"] == live.ACTIVE_ID
        assert probe["active_before"] == VORZUSTAND_ID

    def test_die_freigabe_setzt_den_kandidaten_aktiv(self, probe):
        assert probe["release_status"] == "applied", probe["release_reason"]
        assert probe["active_after_release"] == rr.CANDIDATE_ID

    def test_ein_neubau_unterscheidet_sich_nur_in_den_baumetadaten(
            self, probe):
        """
        Der Neubau des Freigabewegs gegen die gespeicherte Datei: Er
        unterscheidet sich nur in der Bauumgebung.

        GEAENDERT IN V2-C22: Die Datei wird mitgeliefert und byte-genau
        gepinnt; der Freigabeweg ersetzt sie nie. Sie bleibt deshalb
        liegen und unveraendert, und der Vergleich ist der, den
        release() selbst gegen sie zieht. In einer anderen numerischen
        Umgebung weichen zusaetzlich nur die vom Aequivalenzvertrag
        tolerierten Zahlenfelder und die daraus abgeleiteten Kennungen ab.
        """
        assert probe["fresh_build_differing_fields"] is not None
        assert probe["fresh_build_model_fields_differing"] == []
        assert probe["stored_candidate_unchanged"] is True
        if c22.is_reference_environment():
            assert probe["fresh_build_mode"] == "exact"
            assert probe["fresh_build_only_build_metadata"] is True
            return
        assert probe["fresh_build_mode"] in ("exact", "equivalent")
        erlaubt = (set(probe["fresh_build_tolerated_fields"])
                   | set(probe["fresh_build_derived_identity_fields"]))
        assert all(rr.is_build_metadata(p) or p in erlaubt
                   for p in probe["fresh_build_differing_fields"])

    def test_die_laufzeit_wendet_danach_den_kandidaten_an(self, probe):
        antwort = probe["runtime_after_release_ml"]
        assert antwort["mode"] == "active"
        assert antwort["applied"] is True
        assert antwort["model_id"] == rr.CANDIDATE_ID
        assert antwort["league_stage"] == "applied"

    def test_ohne_approach_bleibt_die_standardbetriebsart_aus(self, probe):
        antwort = probe["runtime_after_release_off"]
        assert antwort["mode"] == "off"
        assert antwort["applied"] is False
        assert antwort["model_id"] is None

    def test_der_rollback_stellt_den_vorzustand_her(self, probe):
        assert probe["rollback_status"] == "rolled_back"
        assert probe["active_after_rollback"] == probe["active_before"]
        antwort = probe["runtime_after_rollback_ml"]
        assert antwort["applied"] is True
        assert antwort["model_id"] == VORZUSTAND_ID

    def test_echte_registry_und_modellverzeichnis_unberuehrt(self, probe):
        assert probe["real_registry_unchanged"] is True
        assert probe["real_models_dir_unchanged"] is True


# ---------------------------------------------------------------------------
# 5. Die HTTP-Schnittstelle nach isolierter Aktivierung
# ---------------------------------------------------------------------------

class TestApi:

    @pytest.fixture
    def client(self, monkeypatch):
        """Echter Testclient mit gueltigem CSRF-Token (tests.conftest)."""
        from tests.conftest import mit_csrf

        import app as app_module

        monkeypatch.delenv("FOOTSIM_ML_MODE", raising=False)
        monkeypatch.delenv("FOOTSIM_ML_WEIGHT", raising=False)
        app_module.app.config["TESTING"] = True
        with app_module.app.test_client() as c:
            yield mit_csrf(c)

    @staticmethod
    def _cl(**extra):
        return {"competition": "cl", "home_team": "Heim",
                "away_team": "Gast", "home_id": BAYERN, "away_id": ARSENAL,
                "season": rr.PROBE_MATCH["season"], "simulations": 300,
                "use_seed": True, **extra}

    def test_approach_ml_meldet_den_kandidaten(self, client, kandidat,
                                               evaluation):
        with c21.isolated_activation(kandidat, evaluation):
            antwort = client.post("/api/simulate",
                                  json=self._cl(approach="ml"))
        assert antwort.status_code == 200
        ml = antwort.get_json()["ml"]
        assert ml["mode"] == "active"
        assert ml["applied"] is True
        assert ml["model_id"] == rr.CANDIDATE_ID
        assert ml["league_stage"]["status"] == "applied"

    def test_ohne_approach_wirkt_kein_modell(self, client, kandidat,
                                             evaluation):
        with c21.isolated_activation(kandidat, evaluation):
            antwort = client.post("/api/simulate", json=self._cl())
        assert antwort.status_code == 200
        ml = antwort.get_json()["ml"]
        assert ml["mode"] == "off"
        assert ml["applied"] is False
        assert ml["model_id"] is None

    def test_nach_dem_block_gilt_wieder_die_echte_registry(
            self, client, kandidat, evaluation):
        from src.ml import inference as inf

        echt_root, echt_entry = inf._REPO_ROOT, mr.active_entry
        with c21.isolated_activation(kandidat, evaluation):
            assert inf._REPO_ROOT != echt_root
        assert inf._REPO_ROOT == echt_root
        assert mr.active_entry is echt_entry
        antwort = client.post("/api/simulate", json=self._cl(approach="ml"))
        assert antwort.status_code == 200
        assert antwort.get_json()["ml"]["model_id"] == live.ACTIVE_ID


# ---------------------------------------------------------------------------
# 6. Nichts Echtes wurde veraendert
# ---------------------------------------------------------------------------

class TestZustand:

    def test_die_echte_registry_ist_die_autorisierte(self):
        assert mr.registry_fingerprint(mr.load_registry()) == \
            live.REGISTRY_FP
        eintrag, _g = mr.active_entry()
        assert eintrag["model_id"] == live.ACTIVE_ID

    def test_registry_und_modellverzeichnis_wie_vor_dem_modul(
            self, zustand_vorher):
        assert _echter_zustand() == zustand_vorher
