"""
V2-C19: Der Kandidat wird vorbereitet, nicht aktiviert.

WORUM ES HIER GEHT
------------------
Das neue Bundle schliesst die Abdeckungsluecke, aber es ist damit noch
nichts freigegeben. Diese Datei haelt beides fest: dass eine spaetere
Registrierung vollstaendig durchlaufen WUERDE, und dass in diesem
Arbeitsblock nichts davon tatsaechlich passiert ist.

Alle Registryhandlungen laufen auf einer Kopie im Speicher oder in
einem temporaeren Verzeichnis. Die echte Registry wird ausschliesslich
gelesen, und ein Test prueft ausdruecklich, dass ihr Fingerabdruck
danach derselbe ist.
"""

import json
import os
import tempfile

import pytest

from src.ml import model_registry as mr
from tests import live_registry_state as live

NEUES_BUNDLE = "data/ml/models/clm-3475c9aacef6fec9-ls9cb9e0f6.json"
#: Das zur Zeit von C19 aktive Modell. Sein Bundle bleibt liegen.
AKTIVES_MODELL = live.PRE_C22_ACTIVE_ID
#: GEAENDERT IN V2-C22: Der Fingerabdruck der echten Registry ist der
#: jeweils autorisierte Zustand (tests/live_registry_state.py), nicht
#: mehr fest der von C19. Die Aussage dieser Datei bleibt: Ihre
#: Registryhandlungen veraendern die echte Registry nicht.
AKTIVER_FINGERABDRUCK = live.REGISTRY_FP


@pytest.fixture(scope="module")
def kandidat_bundle():
    if not os.path.isfile(NEUES_BUNDLE):
        pytest.skip("das C19-Kandidatenbundle liegt nicht vor")
    with open(NEUES_BUNDLE, encoding="utf-8") as datei:
        return json.load(datei)


class TestDasBundleAufDerPlatte:

    def test_es_ueberschreibt_das_aktive_bundle_nicht(self, kandidat_bundle):
        assert kandidat_bundle["model_id"] != AKTIVES_MODELL
        assert os.path.isfile(
            "data/ml/models/%s.json" % AKTIVES_MODELL)

    def test_es_traegt_die_volle_zuordnung(self, kandidat_bundle):
        block = kandidat_bundle["league_strength"]
        assert len(block["team_leagues"]) == block[
            "team_leagues_provenance"]["teams"]
        assert len(block["team_leagues"]) > 100

    def test_der_loader_nimmt_es_an(self, kandidat_bundle):
        from src.ml import persist as ps
        bundle, modelle = ps.load_bundle(NEUES_BUNDLE)
        assert bundle["model_id"] == kandidat_bundle["model_id"]
        assert set(modelle) == {"home", "away"}


class TestTrockenlaufDerRegistrierung:
    """
    Die Registrierung wird vollstaendig durchgerechnet - auf einer
    Kopie. `register_candidate` arbeitet ohnehin nicht in-place; der
    Test macht sichtbar, dass das so bleibt.
    """

    def test_die_registrierung_wuerde_durchlaufen(self, kandidat_bundle):
        from src.ml import c16_release as rel

        dokument = mr.load_registry()
        eintrag = rel._registry_eintrag(
            kandidat_bundle, NEUES_BUNDLE,
            "data/ml/c16_damped_league_strength_evaluation.json")
        assert eintrag["bundle_sha256"] == mr.bundle_sha256(NEUES_BUNDLE)

        neu = mr.register_candidate(dokument, eintrag)
        assert mr.validate_registry(neu) == []

        gefunden = [m for m in neu["models"]
                    if m["model_id"] == kandidat_bundle["model_id"]]
        assert len(gefunden) == 1
        assert gefunden[0]["stage"] == mr.STAGE_CANDIDATE

    def test_ein_kandidat_veraendert_keine_nutzerantwort(self):
        assert mr.STAGE_CANDIDATE not in mr.STAGES_AFFECTING_OUTPUT

    def test_die_registrierung_schreibt_nicht_in_die_echte_registry(
            self, kandidat_bundle):
        from src.ml import c16_release as rel

        vorher = mr.registry_fingerprint(mr.load_registry())
        eintrag = rel._registry_eintrag(
            kandidat_bundle, NEUES_BUNDLE,
            "data/ml/c16_damped_league_strength_evaluation.json")
        mr.register_candidate(mr.load_registry(), eintrag)
        nachher = mr.registry_fingerprint(mr.load_registry())

        assert vorher == nachher == AKTIVER_FINGERABDRUCK

    def test_der_sprung_auf_active_braucht_eine_freigabe(self,
                                                        kandidat_bundle):
        """
        Fail-closed: Ohne Freigabetoken wird aus einem Kandidaten kein
        aktives Modell. Geprueft auf der Kopie, nie auf dem Original.
        """
        from src.ml import c16_release as rel

        eintrag = rel._registry_eintrag(
            kandidat_bundle, NEUES_BUNDLE,
            "data/ml/c16_damped_league_strength_evaluation.json")
        neu = mr.register_candidate(mr.load_registry(), eintrag)

        with pytest.raises(mr.RegistryError):
            mr.set_stage(neu, kandidat_bundle["model_id"],
                         mr.STAGE_ACTIVE)


class TestIsolierteRegistryDatei:

    def test_schreiben_und_lesen_in_einem_temporaeren_verzeichnis(
            self, kandidat_bundle):
        from src.ml import c16_release as rel

        eintrag = rel._registry_eintrag(
            kandidat_bundle, NEUES_BUNDLE,
            "data/ml/c16_damped_league_strength_evaluation.json")
        neu = mr.register_candidate(mr.load_registry(), eintrag)

        with tempfile.TemporaryDirectory() as tmp:
            ziel = os.path.join(tmp, "registry.json")
            mr.write_registry(neu, pfad=ziel)
            assert os.path.isfile(ziel)
            with open(ziel, encoding="utf-8") as datei:
                gelesen = json.load(datei)
            assert mr.registry_fingerprint(gelesen) == \
                mr.registry_fingerprint(neu)

        # Und die echte Registry ist davon unberuehrt.
        assert mr.registry_fingerprint(
            mr.load_registry()) == AKTIVER_FINGERABDRUCK


class TestDasAktiveModellBleibt:
    """
    GEAENDERT IN V2-C22.

    Bis C21 hiess das: aktiv bleibt das Modell mit 63 Vereinen. Seit
    der autorisierten lokalen Aktivierung in C22 ist aktiv, was
    tests/live_registry_state.py nennt. Die Aussage ueber den
    C19-Kandidaten gilt unveraendert: Er ist vorbereitet, nie in Betrieb.
    """

    def test_active_zeigt_auf_das_autorisierte_bundle(self):
        eintrag, _grund = mr.active_entry()
        assert eintrag["model_id"] == live.ACTIVE_ID

    def test_die_laufzeit_laedt_das_autorisierte_bundle(self):
        from src.ml import inference as inf
        inf.reset_model_cache()
        bundle, _modelle = inf.load_model()
        assert bundle["model_id"] == live.ACTIVE_ID
        assert len(bundle["league_strength"]["team_leagues"]) == \
            live.ACTIVE_TEAMS

    def test_der_c19_kandidat_ist_nicht_in_betrieb(self, kandidat_bundle):
        eintrag, _grund = mr.active_entry()
        assert eintrag["model_id"] != kandidat_bundle["model_id"]
        ids = [m["model_id"] for m in mr.load_registry()["models"]]
        assert kandidat_bundle["model_id"] not in ids
