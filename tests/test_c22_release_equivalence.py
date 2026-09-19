"""
V2-C22: der eingefrorene Aequivalenzvertrag und sein Vergleich.

Schnelle Tests ohne Modellbau. Referenz ist jeweils ein ECHTES,
gespeichertes Bundle; der "Neubau" ist eine Kopie, deren Zahlen so
verschoben werden, wie es eine andere numerische Umgebung nachgemessen
tut (relativ ~1e-11), oder so, wie es ein wirklich anderes Modell tut.
Jede Kopie traegt danach wieder die Kennungen, die ihr Inhalt ergibt -
sonst pruefte der Test die Kennung und nicht die Abweichung.

Die Referenzpopulation ist hier synthetisch (283 Zeilen mit den echten
Merkmalsnamen), damit die Vorhersagepruefung in Sekunden laeuft. Der
echte Weg ueber den vollen Datensatz laeuft in den Freigabetests.
"""

import copy
import json
import os
import random

import pytest

from src.ml import c16_release as rel
from src.ml import c22_release_equivalence as c22
from src.ml import persist as ps

ROOT = c22._repo_root()
KANDIDAT = "data/ml/models/clm-936ecce472696ccb-ls1c4f4e1d.json"

#: Der eingefrorene Fingerabdruck. Aendert sich eine Toleranz, ein Pfad
#: oder eine Regel, muss dieser Test bewusst angepasst werden.
VERTRAG_FINGERABDRUCK = (
    "93fa83c8dd353560c5f8566383ab5ada2819125a0dd125ea0f31208543e47839")


def _laden(relativ):
    with open(os.path.join(ROOT, relativ), encoding="utf-8") as datei:
        return json.load(datei)


def _kennung_neu(bundle):
    """Die Kennungen wieder aus dem (veraenderten) Inhalt ableiten."""
    bundle["integrity"]["models_sha256"] = ps.models_digest(bundle["models"])
    bundle["model_id"] = c22.recompute_model_id(bundle)
    return bundle


def _plattformneubau(referenz, faktor=1e-11):
    """So weit weg, wie es eine andere numerische Umgebung ist."""
    neu = copy.deepcopy(referenz)
    for i, seite in enumerate(("home", "away")):
        reg = neu["models"][seite]["regressor"]
        reg["coef"] = [v * (1 + faktor * (1 if (j + i) % 2 else -1))
                       for j, v in enumerate(reg["coef"])]
        reg["intercept"] *= (1 + faktor)
    for block in ("alpha", "gamma"):
        for kand in neu["league_strength"]["selection"][block]["candidates"]:
            kand["validation_deviance"] *= (1 + faktor)
    for kand in neu["training"]["selection"]["candidates"]:
        kand["inner_log_loss"] *= (1 + faktor)
    neu["created_at"] = "2026-09-19T00:00:00+00:00"
    neu["provenance"]["platform"] = "Linux"
    return _kennung_neu(neu)


@pytest.fixture(scope="module")
def referenz():
    return _laden(KANDIDAT)


@pytest.fixture(scope="module")
def zeilen(referenz):
    """283 synthetische CL-Zeilen der beiden Testsaisons."""
    zufall = random.Random(20260919)
    merkmale = referenz["features"]
    mittel = referenz["models"]["home"]["scaler"]["mean"]
    streuung = referenz["models"]["home"]["scaler"]["scale"]
    vereine = sorted(int(k) for k in
                     referenz["league_strength"]["team_leagues"])
    heraus = []
    for i in range(283):
        zeile = {f: m + s * zufall.uniform(-1.5, 1.5)
                 for f, m, s in zip(merkmale, mittel, streuung)}
        heim, gast = zufall.sample(vereine, 2)
        zeile.update(league="cl", season=2024 if i < 144 else 2025,
                     evaluation_eligible=True, date="2025-01-%02d" % (i % 28 + 1),
                     row_id="r%03d" % i, home_id=heim, away_id=gast,
                     baseline_lambda_home=zufall.uniform(0.6, 2.4),
                     baseline_lambda_away=zufall.uniform(0.5, 2.0))
        heraus.append(zeile)
    return heraus


# ---------------------------------------------------------------------------
# 1. Der eingefrorene Vertrag
# ---------------------------------------------------------------------------

class TestVertrag:

    def test_der_code_traegt_den_eingefrorenen_fingerabdruck(self):
        assert c22.contract_fingerprint() == VERTRAG_FINGERABDRUCK

    def test_das_artefakt_gleicht_dem_code_und_ist_eingefroren(self):
        dokument = _laden(c22.CONTRACT_PATH)
        assert dokument["contract_fingerprint"] == VERTRAG_FINGERABDRUCK
        assert dokument["contract"] == c22.contract()
        assert dokument["frozen_before_measurement"] is True
        assert dokument["schema_version"] == c22.CONTRACT_VERSION

    def test_die_toleranzen_sind_eng_und_liegen_ueber_dem_rauschen(self):
        """Die Trennung aus dem Beleg, nicht aus dem Ergebnis."""
        v = c22.contract()
        beleg = v["evidence_basis"]
        rauschen = beleg["observed_platform_noise"]
        for klasse in ("parameters", "selection_evidence"):
            t = v["tolerances"][klasse]
            assert t["rtol"] <= 1e-8 and t["atol"] <= 1e-9
            assert t["rtol"] > 100 * rauschen[
                "fitted_coefficients_max_relative"]
            assert t["atol"] >= 10 * beleg["stored_quantisation"][
                "league_strength_attack_defence"]
        t = v["tolerances"]["predictions"]
        assert t["rtol"] <= 1e-8
        assert t["rtol"] > 1000 * rauschen["lambda_max_relative"]
        assert beleg["genuinely_different_models_min_relative"] > 1e6 * t[
            "rtol"]

    def test_die_referenzartefakte_sind_die_autorisierten(self):
        ref = c22.contract()["reference_artifacts"]
        assert ref["candidate"]["model_id"] == (
            "clm-936ecce472696ccb-ls1c4f4e1d")
        assert ref["candidate"]["path"] == KANDIDAT
        assert ref["folds"]["measured_ids"] == {
            s: e["model_id"] for s, e in
            _laden("data/ml/c21_season_validation.json")["binding"].items()}

    def test_die_umgebung_entscheidet_keine_freigabe(self):
        """Die Referenzumgebung ist Nachweis, kein Schalter."""
        for modul in ("src/ml/c16_release.py", "src/ml/c21_season_validation.py",
                      "src/ml/c21_release_readiness.py"):
            with open(os.path.join(ROOT, modul), encoding="utf-8") as datei:
                assert "is_reference_environment" not in datei.read(), modul


# ---------------------------------------------------------------------------
# 2. Welche Regel fuer welchen Pfad
# ---------------------------------------------------------------------------

class TestPfadregeln:

    @pytest.mark.parametrize("pfad,klasse", [
        ("models/home/regressor/coef[3]", c22.KLASSE_PARAMETER),
        ("models/away/regressor/intercept", c22.KLASSE_PARAMETER),
        ("league_strength/attack/PL", c22.KLASSE_PARAMETER),
        ("league_strength/defence/AT1", c22.KLASSE_PARAMETER),
        ("league_strength/selection/gamma/candidates[2]/validation_deviance",
         c22.KLASSE_AUSWAHL),
        ("training/selection/candidates[1]/inner_log_loss", c22.KLASSE_AUSWAHL),
        ("training/selection/baseline_inner_log_loss", c22.KLASSE_AUSWAHL),
        ("model_id", c22.KLASSE_KENNUNG),
        ("integrity/models_sha256", c22.KLASSE_KENNUNG),
        ("created_at", c22.KLASSE_BAUMETADATEN),
        ("provenance/platform", c22.KLASSE_BAUMETADATEN),
        # Zahlen, die exakt bleiben
        ("models/home/imputer/statistics[0]", c22.KLASSE_STRUKTUR),
        ("models/home/scaler/mean[0]", c22.KLASSE_STRUKTUR),
        ("models/home/scaler/scale[0]", c22.KLASSE_STRUKTUR),
        # gewaehlte Werte sind Struktur, nicht Messwert
        ("alpha", c22.KLASSE_STRUKTUR),
        ("league_strength/gamma", c22.KLASSE_STRUKTUR),
        ("league_strength/alpha", c22.KLASSE_STRUKTUR),
        ("training/selection/selected", c22.KLASSE_STRUKTUR),
        ("league_strength/selection/gamma/selected", c22.KLASSE_STRUKTUR),
        ("league_strength/selection/alpha/candidates[0]/alpha",
         c22.KLASSE_STRUKTUR),
        ("features[0]", c22.KLASSE_STRUKTUR),
        ("contract_bindings/c17_contract_fingerprint", c22.KLASSE_STRUKTUR),
        ("provenance/dataset_fingerprint/sha256", c22.KLASSE_STRUKTUR),
        ("provenance/evaluation/evaluation_sha256", c22.KLASSE_STRUKTUR),
        ("league_strength/team_leagues/5", c22.KLASSE_STRUKTUR),
        ("training/seasons[0]", c22.KLASSE_STRUKTUR),
        # Nachbarpfade, die nur aehnlich aussehen
        ("models/home/regressor/coef", c22.KLASSE_STRUKTUR),
        ("league_strength/attack", c22.KLASSE_STRUKTUR),
        ("xmodels/home/regressor/intercept", c22.KLASSE_STRUKTUR),
    ])
    def test_klasse(self, pfad, klasse):
        assert c22.classify_path(pfad) == klasse

    def test_dieselben_pfade_wie_differing_fields(self, referenz):
        neu = _plattformneubau(referenz)
        assert c22.classify_differences(referenz, neu)["differing_fields"] \
            == rel.differing_fields(referenz, neu)


# ---------------------------------------------------------------------------
# 3. Die positiven Faelle
# ---------------------------------------------------------------------------

class TestAequivalent:

    def test_identisch_ist_bitgleich(self, referenz, zeilen):
        bericht = c22.compare_bundles(referenz, copy.deepcopy(referenz), zeilen)
        assert bericht["exact"] is True
        assert bericht["mode"] == c22.MODE_EXACT
        assert bericht["prediction"] is None

    def test_nur_baumetadaten_ist_bitgleich(self, referenz):
        neu = copy.deepcopy(referenz)
        neu["created_at"] = "2030-01-01T00:00:00+00:00"
        neu["provenance"]["platform"] = "Linux"
        neu["provenance"]["git_status"]["porcelain"] = 99
        bericht = c22.compare_bundles(referenz, neu)
        assert bericht["mode"] == c22.MODE_EXACT
        assert set(bericht["build_metadata"]) == {
            "created_at", "provenance/platform",
            "provenance/git_status/porcelain"}

    def test_plattformrauschen_ist_aequivalent(self, referenz, zeilen):
        """Das nachgemessene Mass: relativ 1e-11 in den Koeffizienten."""
        neu = _plattformneubau(referenz, 1e-11)
        assert neu["model_id"] != referenz["model_id"]
        bericht = c22.compare_bundles(referenz, neu, zeilen)
        assert bericht["mode"] == c22.MODE_EQUIVALENT, bericht["reason"]
        assert bericht["exact"] is False
        assert bericht["structural_mismatches"] == []
        assert bericht["numerical_mismatches"] == []
        assert set(bericht["derived_identity"]) == {
            "model_id", "integrity/models_sha256"}
        assert 0 < bericht["max_rel_difference"] < 1e-10
        assert bericht["prediction"]["rows"] == 283
        assert bericht["prediction"]["within_tolerance"] is True
        assert bericht["prediction"]["max_rel_difference"] < 1e-9
        assert bericht["tolerance_contract_fingerprint"] == \
            VERTRAG_FINGERABDRUCK
        assert bericht["reference_model_id"] == referenz["model_id"]
        assert bericht["rebuilt_model_id"] == neu["model_id"]

    def test_ein_gekippter_ligaparameter_ist_aequivalent(self, referenz,
                                                        zeilen):
        """Auf 10 Stellen gerundet kippt die letzte Stelle: 1e-10."""
        neu = copy.deepcopy(referenz)
        neu["league_strength"]["attack"]["PL"] = round(
            neu["league_strength"]["attack"]["PL"] + 1e-10, 10)
        bericht = c22.compare_bundles(referenz, _kennung_neu(neu), zeilen)
        assert bericht["mode"] == c22.MODE_EQUIVALENT, bericht["reason"]

    def test_lambdas_im_plattformmass_sind_innerhalb(self, referenz, zeilen):
        population = c22.reference_population(zeilen)
        neu = _plattformneubau(referenz, 1e-14)
        bericht = c22.compare_predictions(referenz, neu, population)
        assert bericht["within_tolerance"] is True
        assert bericht["max_rel_difference"] < 1e-12


# ---------------------------------------------------------------------------
# 4. Die Negativkontrollen A bis M: nichts davon wird aequivalent
# ---------------------------------------------------------------------------

def _veraendert(referenz, aenderung):
    neu = _plattformneubau(referenz)
    aenderung(neu)
    return _kennung_neu(neu)


def _tausche_merkmale(b):
    b["features"][0], b["features"][1] = b["features"][1], b["features"][0]


def _andere_liga(b):
    karte = b["league_strength"]["team_leagues"]
    verein = sorted(karte)[0]
    karte[verein] = "XX9" if karte[verein] != "XX9" else "XX8"


NEGATIVKONTROLLEN = {
    "A Koeffizient +1e-6": lambda b: b["models"]["home"]["regressor"][
        "coef"].__setitem__(0, b["models"]["home"]["regressor"]["coef"][0]
                            + 1e-6),
    "B Achsenabschnitt +1e-6": lambda b: b["models"]["away"][
        "regressor"].__setitem__("intercept", b["models"]["away"]["regressor"][
            "intercept"] + 1e-6),
    "C anderes Alpha": lambda b: b.__setitem__("alpha", 0.1),
    "D Merkmalsreihenfolge": _tausche_merkmale,
    "E Merkmalsname": lambda b: b["features"].__setitem__(0, "anderes_merkmal"),
    "F Trainingssaison": lambda b: b["training"].__setitem__(
        "seasons", [2023, 2024]),
    "G Datensatzfingerabdruck": lambda b: b["provenance"][
        "dataset_fingerprint"].__setitem__("sha256", "0" * 64),
    "H Vertragsfingerabdruck": lambda b: b["contract_bindings"].__setitem__(
        "c17_contract_fingerprint", "0" * 64),
    "I Vereins-Liga-Karte": _andere_liga,
    "J Foldteilung": lambda b: b["training"]["inner_split"].__setitem__(
        "fit_seasons", [2023]),
    "K Gamma": lambda b: b["league_strength"].__setitem__("gamma", 0.75),
    "L spuerbar andere Vorhersage": lambda b: b["models"]["home"][
        "regressor"].__setitem__("intercept", b["models"]["home"]["regressor"][
            "intercept"] + 1e-3),
    "Ligaparameter +1e-6": lambda b: b["league_strength"]["attack"].__setitem__(
        "PL", b["league_strength"]["attack"]["PL"] + 1e-6),
    "Skalierung exakt": lambda b: b["models"]["home"]["scaler"][
        "mean"].__setitem__(0, b["models"]["home"]["scaler"]["mean"][0]
                            * (1 + 1e-13)),
    "gewaehltes Gamma": lambda b: b["league_strength"]["selection"][
        "gamma"].__setitem__("selected", 0.75),
}


class TestNegativkontrollen:

    @pytest.mark.parametrize("name", sorted(NEGATIVKONTROLLEN))
    def test_wird_abgewiesen(self, referenz, zeilen, name):
        neu = _veraendert(referenz, NEGATIVKONTROLLEN[name])
        bericht = c22.compare_bundles(referenz, neu, zeilen)
        assert bericht["equivalent"] is False, name
        assert bericht["mode"] == c22.MODE_REFUSED
        assert bericht["structural_mismatches"] or bericht[
            "numerical_mismatches"], name

    def test_L_die_vorhersagepruefung_greift_selbst(self, referenz, zeilen):
        """Unabhaengig von den Parametern: 1e-6 im Achsenabschnitt ist
        in den Lambdas sichtbar und liegt ausserhalb."""
        neu = copy.deepcopy(referenz)
        neu["models"]["home"]["regressor"]["intercept"] += 1e-6
        bericht = c22.compare_predictions(
            referenz, neu, c22.reference_population(zeilen))
        assert bericht["within_tolerance"] is False
        assert bericht["max_rel_difference"] > 1e-7

    def test_eine_nicht_nachrechenbare_kennung_wird_abgewiesen(
            self, referenz, zeilen):
        neu = _plattformneubau(referenz)
        neu["model_id"] = "clm-0000000000000000-ls00000000"
        bericht = c22.compare_bundles(referenz, neu, zeilen)
        assert bericht["equivalent"] is False
        assert "passt nicht zum Inhalt" in bericht["reason"]

    def test_ohne_referenzpopulation_kein_nachweis(self, referenz):
        bericht = c22.compare_bundles(referenz, _plattformneubau(referenz))
        assert bericht["equivalent"] is False
        assert "Referenzpopulation" in bericht["reason"]

    def test_eine_andere_populationsgroesse_wird_abgewiesen(self, referenz,
                                                            zeilen):
        bericht = c22.compare_bundles(referenz, _plattformneubau(referenz),
                                      zeilen[:-1])
        assert bericht["equivalent"] is False
        assert "282 statt 283" in bericht["reason"]

    def test_eine_fremde_attrappe_ist_strukturell_anders(self, referenz):
        bericht = c22.compare_bundles(referenz, {"model_id": "clm-x-lsy"})
        assert bericht["equivalent"] is False
        assert bericht["structural_mismatches"]

    def test_M_ein_falscher_bundle_hash_wird_abgewiesen(self, tmp_path):
        ziel = tmp_path / KANDIDAT
        ziel.parent.mkdir(parents=True)
        inhalt = open(os.path.join(ROOT, KANDIDAT), "rb").read()
        ziel.write_bytes(inhalt.replace(b"approved", b"approveD", 1))
        bundle, _pfad, befunde = c22.load_reference_candidate(str(tmp_path))
        assert bundle is None
        assert "SHA-256" in befunde[0]

    def test_M_ein_fehlendes_referenzbundle_wird_abgewiesen(self, tmp_path):
        bundle, _pfad, befunde = c22.load_reference_candidate(str(tmp_path))
        assert bundle is None
        assert "fehlt" in befunde[0]

    def test_M_das_echte_referenzbundle_wird_geladen(self):
        bundle, _pfad, befunde = c22.load_reference_candidate(ROOT)
        assert befunde == []
        assert bundle["model_id"] == "clm-936ecce472696ccb-ls1c4f4e1d"


# ---------------------------------------------------------------------------
# 5. Kennung aus dem Inhalt
# ---------------------------------------------------------------------------

class TestKennung:

    @pytest.mark.parametrize("datei", sorted(
        f for f in os.listdir(os.path.join(ROOT, "data", "ml", "models"))
        if f.startswith("clm-")))
    def test_jedes_gespeicherte_bundle_ist_nachrechenbar(self, datei):
        bundle = _laden("data/ml/models/%s" % datei)
        assert c22.recompute_model_id(bundle) == bundle["model_id"]
        assert c22.identity_findings(bundle, datei) == []

    def test_eine_veraenderte_zahl_aendert_die_kennung(self, referenz):
        neu = copy.deepcopy(referenz)
        neu["models"]["home"]["regressor"]["coef"][0] *= (1 + 1e-15)
        assert c22.recompute_model_id(neu) != referenz["model_id"]
        assert c22.identity_findings(neu, "x")

    def test_die_linie_haengt_an_kandidat_und_evaluation(self, referenz):
        neu = _plattformneubau(referenz)
        assert c22.same_lineage(referenz, neu)
        neu["provenance"]["evaluation"]["evaluation_sha256"] = "0" * 64
        assert not c22.same_lineage(referenz, neu)


# ---------------------------------------------------------------------------
# 6. Die Entscheidung im Freigabeweg
# ---------------------------------------------------------------------------

class _Geschrieben(Exception):
    """Der bisherige Weg haette ein Bundle geschrieben."""


@pytest.fixture
def freigabe(monkeypatch, tmp_path, zeilen):
    """
    Der echte release()-Ablauf auf einer echten Kopie des
    Freigabezustands. Ersetzt werden nur die teuren Schritte - Datensatz,
    Saisonnachweis, Karte und Bundlebau - wie in test_c22_release_gate.
    """
    from src.ml import c20_temporal_map as c20
    from src.ml import c21_release_readiness as rr
    from src.ml import c21_season_validation as c21
    from src.ml import dataset as ds

    rr.copy_release_state(str(tmp_path))
    monkeypatch.setattr(ds, "build_dataset", lambda **kw: (zeilen, {}))
    monkeypatch.setattr(c21, "release_evidence", lambda z, e, repo_root: (
        True, [], {"fold_models": ["a", "b"], "verdict": "accepted",
                   "fold_comparisons": {}}))
    monkeypatch.setattr(c20, "production_map", lambda s: ({}, {
        "teams": 0, "upto_season": 2026, "seasons_used": [],
        "map_fingerprint": "f" * 64}))
    neubau = {}

    def bauen(*a, **kw):
        return copy.deepcopy(neubau["bundle"]), {
            "gamma": 1.0, "league_alpha": 0.01, "leagues": 0,
            "teams_mapped": 0}

    monkeypatch.setattr(rel, "build_final_bundle", bauen)

    def nicht_schreiben(bundle, pfad):
        raise _Geschrieben(pfad)

    monkeypatch.setattr(rel, "write_bundle", nicht_schreiben)
    modelle = tmp_path / "data" / "ml" / "models"
    return {"root": tmp_path, "neubau": neubau,
            "vorher": sorted(os.listdir(modelle)), "modelle": modelle}


class TestFreigabeweg:

    ID = "clm-936ecce472696ccb-ls1c4f4e1d"

    def _lauf(self, freigabe, bundle, erwartet=None):
        freigabe["neubau"]["bundle"] = bundle
        return rel.release(dry_run=True, repo_root=str(freigabe["root"]),
                           expected_model_id=erwartet)

    @pytest.mark.parametrize("erwartet", [ID, None])
    def test_ein_aequivalenter_neubau_bestaetigt_das_gespeicherte_bundle(
            self, freigabe, referenz, erwartet):
        neu = _plattformneubau(referenz)
        r = self._lauf(freigabe, neu, erwartet)
        assert r["status"] in ("dry_run_ok", "already_active"), r["reason"]
        assert r["model_id"] == self.ID
        vergleich = r["bundle_comparison"]
        assert vergleich["mode"] == "equivalent"
        assert vergleich["reference_model_id"] == self.ID
        assert vergleich["rebuilt_model_id"] == neu["model_id"]
        assert vergleich["model_fields_differing"] == []
        assert vergleich["equivalence"]["tolerance_contract_fingerprint"] \
            == VERTRAG_FINGERABDRUCK
        # Nichts geschrieben: kein Bundle unter der Neubau-ID, das
        # gespeicherte byte-genau unveraendert.
        assert sorted(os.listdir(freigabe["modelle"])) == freigabe["vorher"]
        from src.ml import c21_release_readiness as rr
        assert rr._sha(str(freigabe["root"] / KANDIDAT)) == \
            rr.CANDIDATE_SHA256
        assert any("bleibt das Artefakt" in z for z in r["log"])

    @pytest.mark.parametrize("erwartet", [ID, None])
    def test_ein_anderes_modell_wird_verweigert_und_nie_geschrieben(
            self, freigabe, referenz, erwartet):
        neu = _veraendert(referenz, NEGATIVKONTROLLEN["A Koeffizient +1e-6"])
        r = self._lauf(freigabe, neu, erwartet)
        assert r["status"] == "refused"
        assert r["wrote_anything"] is False
        assert "nicht aequivalent" in r["reason"] or "erwartet war" in r[
            "reason"]
        assert r["bundle_comparison"]["mode"] == "refused"
        assert sorted(os.listdir(freigabe["modelle"])) == freigabe["vorher"]

    def test_ohne_gespeichertes_referenzbundle_wird_verweigert(
            self, freigabe, referenz):
        (freigabe["root"] / KANDIDAT).unlink()
        r = self._lauf(freigabe, _plattformneubau(referenz), self.ID)
        assert r["status"] == "refused"
        assert "fehlt" in r["reason"]
        assert not (freigabe["root"] / KANDIDAT).exists()

    def test_ein_manipuliertes_referenzbundle_wird_verweigert(
            self, freigabe, referenz):
        ziel = freigabe["root"] / KANDIDAT
        ziel.write_bytes(ziel.read_bytes().replace(b"approved", b"approveD",
                                                   1))
        r = self._lauf(freigabe, _plattformneubau(referenz), self.ID)
        assert r["status"] == "refused"
        assert "SHA-256" in r["reason"]

    def test_eine_fremde_erwartete_id_bleibt_das_stopkriterium(
            self, freigabe, referenz):
        r = self._lauf(freigabe, _plattformneubau(referenz),
                       "clm-0000000000000000-ls00000000")
        assert r["status"] == "refused"
        assert "erwartet war" in r["reason"]
        assert "bundle_comparison" not in r

    def test_ein_bitgleicher_neubau_geht_den_bisherigen_weg(
            self, freigabe, referenz):
        """Die gespeicherte Datei liegt vor: bitgleich uebernommen."""
        r = self._lauf(freigabe, copy.deepcopy(referenz), self.ID)
        assert r["status"] in ("dry_run_ok", "already_active"), r["reason"]
        assert r["bundle_comparison"]["mode"] == "exact"
        assert r["bundle_comparison"]["existing_file"] is True

    def test_ein_bitgleicher_neubau_ohne_datei_wird_geschrieben(
            self, freigabe, referenz):
        """Nur bitgleich darf eine fehlende Datei neu entstehen."""
        (freigabe["root"] / KANDIDAT).unlink()
        with pytest.raises(_Geschrieben):
            self._lauf(freigabe, copy.deepcopy(referenz), self.ID)

    def test_eine_andere_linie_geht_den_bisherigen_weg(self, freigabe,
                                                      referenz):
        """Eine neue Messung: der Vertrag gilt nur fuer diese Linie."""
        neu = copy.deepcopy(referenz)
        neu["provenance"]["evaluation"]["evaluation_sha256"] = "0" * 64
        neu["model_id"] = c22.recompute_model_id(neu)
        with pytest.raises(_Geschrieben):
            self._lauf(freigabe, neu, None)
