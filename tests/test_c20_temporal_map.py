"""
V2-C20: Der korrigierte zeitliche Zuordnungsvertrag.

DER BEFUND, DEN DIESE DATEI FESTHAELT
-------------------------------------
C19 begrenzte die Team-Liga-Karte eines Folds auf die letzte
Trainingssaison. Nachgemessen stammte der gesamte Unterschied zur
akzeptierten C16-Messung aus 52 Partien, und in jeder davon war die
Liga eines Vereins lokal nur fuer die Testsaison belegt - weil die
Datei der Trainingssaison fehlt, nicht weil die Mitgliedschaft
unbekannt war. C19 hat eine fehlende lokale Datei mit einer
unbekannten Ligazugehoerigkeit verwechselt.

Der korrigierte Vertrag laesst die Karte bis zur VORHERSAGESAISON
reichen. Ligamitgliedschaft dieser Saison steht mit dem Spielplan vor
Saisonbeginn fest; spaetere Saisons bleiben ausgeschlossen, Ergebnisse
liest die Karte ueberhaupt nicht.
"""

import json
import os

import pytest

from src.ml import c19_league_map as c19
from src.ml import c20_temporal_map as c20


# ---------------------------------------------------------------------------
# 1. Der Vertrag
# ---------------------------------------------------------------------------

class TestVertrag:

    def test_fingerabdruck_ist_stabil(self):
        assert c20.contract_fingerprint() == c20.contract_fingerprint()

    def test_der_eingefrorene_vertrag_passt_zum_code(self):
        with open(c20.CONTRACT_PATH, encoding="utf-8") as datei:
            artefakt = json.load(datei)
        assert artefakt["contract_fingerprint"] == c20.contract_fingerprint()
        assert artefakt["frozen_before_measurement"] is True

    def test_er_benennt_den_ersetzten_vertrag_mit_fingerabdruck(self):
        ersetzt = c20.contract()["supersedes"]
        assert ersetzt["contract_version"] == c19.CONTRACT_VERSION
        assert ersetzt["contract_fingerprint"] == c19.contract_fingerprint()
        assert ersetzt["c19_artifacts_untouched"] is True

    def test_das_c19_artefakt_ist_unveraendert(self):
        """Alte Vertragsartefakte werden nicht nachtraeglich geaendert."""
        with open(c19.ARTIFACT_PATH, encoding="utf-8") as datei:
            artefakt = json.load(datei)
        assert artefakt["contract_fingerprint"] == c19.contract_fingerprint()

    def test_ergebnisse_sind_nie_zulaessig(self):
        klassen = c20.contract()["information_classes"]
        ergebnisse = klassen["match_results_after_cutoff"]
        assert ergebnisse["admissible"] is False
        assert ergebnisse["used_by_map"] is False

    def test_spaetere_mitgliedschaft_ist_nicht_zulaessig(self):
        klassen = c20.contract()["information_classes"]
        assert klassen["league_membership_after_prediction_season"][
            "admissible"] is False

    def test_mitgliedschaft_der_vorhersagesaison_ist_zulaessig(self):
        klassen = c20.contract()["information_classes"]
        assert klassen["league_membership_of_prediction_season"][
            "admissible"] is True

    def test_die_karte_liest_nur_teilnehmer(self):
        liest = c20.contract()["map_builder"]["reads"].lower()
        assert "keine tore" in liest
        assert c20.contract()["map_builder"]["unchanged"] is True


# ---------------------------------------------------------------------------
# 2. Die Obergrenze
# ---------------------------------------------------------------------------

class TestObergrenze:

    def test_vorhersagesaison_folgt_auf_die_letzte_trainingssaison(self):
        assert c20.prediction_season([2023]) == 2024
        assert c20.prediction_season([2024, 2023]) == 2025
        assert c20.prediction_season((2023, 2024, 2025)) == 2026

    def test_ohne_trainingssaison_keine_vorhersagesaison(self):
        with pytest.raises(ValueError):
            c20.prediction_season([])

    def test_ein_fold_reicht_bis_zu_seiner_testsaison(self):
        assert c20.fold_upto({"name": "x", "train_seasons": [2023],
                              "test_season": 2024}) == 2024

    def test_ein_nicht_anschliessender_fold_wird_abgewiesen(self):
        """
        Die Regel ist fuer Luecken zwischen Training und Test nicht
        definiert. Das wird geprueft und nicht angenommen.
        """
        with pytest.raises(ValueError, match="folgt nicht"):
            c20.fold_upto({"name": "x", "train_seasons": [2023],
                           "test_season": 2025})

    def test_alle_messfolds_schliessen_an(self):
        from src.ml import cl_evaluate as ce
        for fold in list(ce.OUTER_FOLDS) + list(ce.CONTEXT_FOLDS):
            assert c20.fold_upto(fold) == fold["test_season"]

    def test_eine_foldkarte_liest_keine_spaetere_saison(self):
        from src.ml import cl_evaluate as ce
        for fold in ce.OUTER_FOLDS:
            diagnose = c20.fold_map_diagnosis(fold)
            assert max(diagnose["seasons_used"]) <= fold["test_season"]


# ---------------------------------------------------------------------------
# 3. Der Defekt, den C20 behebt
# ---------------------------------------------------------------------------

class TestDerC19Defekt:

    FOLD_2024 = {"name": "cl_2024", "train_seasons": [2023],
                 "test_season": 2024}

    def test_eine_fehlende_datei_ist_keine_unbekannte_liga(self):
        """
        Slovan Bratislava (football-data 7509) spielte in der
        slowakischen Liga. Lokal liegt die SK1-Datei nur fuer 2024 vor.
        C19 kannte den Verein im Fold 2024 deshalb nicht - C20 kennt
        ihn, weil 2024 die Vorhersagesaison dieses Folds ist.
        """
        from src.data.historical_loader import season_file_path
        import pathlib

        assert not pathlib.Path(season_file_path("SK1", 2023)).is_file()
        assert pathlib.Path(season_file_path("SK1", 2024)).is_file()

        c19_karte, _d = c19.build_team_league_map(2023)
        assert 7509 not in c19_karte
        assert c20.fold_map(self.FOLD_2024).get(7509) == "SK1"

    def test_c20_kennt_im_fold_2024_jede_liga_die_c19_verlor(self):
        """
        Waechter gegen das Wiedereinfuehren des C19-Defekts: Jeder
        Verein, der unter C19 im Fold 2024 fehlte, aber in einer
        Ligadatei der Testsaison steht, ist unter C20 bekannt.
        """
        c19_karte, _d = c19.build_team_league_map(2023)
        c20_karte = c20.fold_map(self.FOLD_2024)
        test_karte, _d = c19.build_team_league_map(2024)
        verloren = set(test_karte) - set(c19_karte)
        assert verloren, "ohne Differenz waere dieser Test blind"
        assert verloren <= set(c20_karte)

    def test_die_karte_eines_folds_enthaelt_keine_zukunftssaison(self):
        k2024 = c20.fold_map(self.FOLD_2024)
        k2025, _d = c19.build_team_league_map(2025)
        k2024_voll, _d = c19.build_team_league_map(2024)
        assert k2024 == k2024_voll
        erst_2025 = set(k2025) - set(k2024_voll)
        assert erst_2025, "ohne spaetere Vereine waere dieser Test blind"
        assert not (erst_2025 & set(k2024))


# ---------------------------------------------------------------------------
# 4. Produktion
# ---------------------------------------------------------------------------

class TestProduktion:

    def test_die_produktionskarte_reicht_bis_zur_vorhersagesaison(self):
        from src.ml import persist as ps
        _karte, diagnose = c20.production_map(ps.DEFAULT_TRAINING_SEASONS)
        assert diagnose["upto_season"] == c20.prediction_season(
            ps.DEFAULT_TRAINING_SEASONS)

    def test_sie_sagt_ehrlich_welche_saisons_gelesen_wurden(self):
        """
        Fuer die Vorhersagesaison liegt lokal noch keine Ligadatei vor.
        Die Diagnose muss das zeigen, statt eine Abdeckung zu
        behaupten, die es nicht gibt.
        """
        from src.data.historical_loader import AVAILABLE_HISTORICAL_SEASONS
        from src.ml import persist as ps
        _karte, diagnose = c20.production_map(ps.DEFAULT_TRAINING_SEASONS)
        assert diagnose["seasons_used"] == sorted(
            s for s in AVAILABLE_HISTORICAL_SEASONS
            if s <= diagnose["upto_season"])


# ---------------------------------------------------------------------------
# 5. Der C19-Standardweg bleibt bitgenau
# ---------------------------------------------------------------------------

class TestC19Reproduzierbarkeit:
    """
    C20 erweitert build_final_bundle um einen ausdruecklichen Vertrag.
    Ohne diese Angabe muss der Weg Bit fuer Bit der C19-Weg bleiben.

    DABEI GEFUNDEN
    Der C19-Kandidat clm-3475c9aacef6fec9-ls9cb9e0f6 laesst sich mit
    dem heutigen C19-Code NICHT bitgenau bauen. Grund ist nicht C20:
    Der Kandidat wurde in C19 gebaut, BEVOR der C19-Vertragstext zur
    Cold-Start-Semantik korrigiert wurde. Seine Provenienz traegt den
    Fingerabdruck 35e9f9b9..., Code und C19-Artefakt tragen a1e94b02...
    Der Kandidat bleibt als historisches Artefakt unveraendert liegen
    und ist durch den C20-Kandidaten ersetzt.
    """

    ALTER_FINGERABDRUCK = (
        "35e9f9b912eef2faa94bf884a118b240ae6bae0826ae15dc7c71b9423f1bb971")
    C19_KANDIDAT = "data/ml/models/clm-3475c9aacef6fec9-ls9cb9e0f6.json"

    @pytest.fixture(scope="class")
    def bauteile(self):
        from src.ml import dataset as ds
        from src.ml import persist as ps

        with open("data/ml/c16_damped_league_strength_evaluation.json",
                  encoding="utf-8") as datei:
            artefakt = json.load(datei)
        zeilen, _d = ds.build_dataset(include_cl=True)
        karte, _k = c19.build_team_league_map(
            max(ps.DEFAULT_TRAINING_SEASONS))
        return zeilen, karte, artefakt

    def test_der_standardweg_traegt_genau_die_c19_provenienz(self, bauteile):
        from src.ml import c16_release as rel

        zeilen, karte, artefakt = bauteile
        bundle, _diag = rel.build_final_bundle(zeilen, karte, artefakt)
        spur = bundle["league_strength"]["team_leagues_provenance"]
        assert sorted(spur) == ["contract_fingerprint", "map_fingerprint",
                                "note", "source", "teams", "upto_season"]
        assert spur["contract_fingerprint"] == c19.contract_fingerprint()
        assert "c20_contract_fingerprint" not in bundle["contract_bindings"]

    def test_mit_dem_damaligen_vertrag_entsteht_der_c19_kandidat_bitgenau(
            self, bauteile, monkeypatch):
        """
        Der Beweis, dass C20 den Standardweg nicht veraendert hat: Mit
        dem zum Bauzeitpunkt gueltigen Fingerabdruck entsteht exakt das
        Bundle, das auf der Platte liegt.
        """
        from src.ml import c16_release as rel

        zeilen, karte, artefakt = bauteile
        monkeypatch.setattr(c19, "contract_fingerprint",
                            lambda: self.ALTER_FINGERABDRUCK)
        bundle, _diag = rel.build_final_bundle(zeilen, karte, artefakt)

        with open(self.C19_KANDIDAT, encoding="utf-8") as datei:
            platte = json.load(datei)
        assert bundle["model_id"] == platte["model_id"]
        assert bundle["league_strength"] == platte["league_strength"]

    def test_der_c19_kandidat_traegt_einen_veralteten_vertrag(self):
        """
        Festgehalten, damit niemand spaeter annimmt, der C19-Kandidat
        sei an den finalen C19-Vertrag gebunden.
        """
        with open(self.C19_KANDIDAT, encoding="utf-8") as datei:
            platte = json.load(datei)
        spur = platte["league_strength"]["team_leagues_provenance"]
        assert spur["contract_fingerprint"] == self.ALTER_FINGERABDRUCK
        assert spur["contract_fingerprint"] != c19.contract_fingerprint()


# ---------------------------------------------------------------------------
# 6. Die Kausalkette, aus den Karten nachgeprueft
# ---------------------------------------------------------------------------

class TestKausalkette:
    """
    Ohne Modell nachpruefbar: JEDER Verein einer Standardpartie, den
    der C19-Vertrag nicht kannte, gehoert zu einer Liga, deren lokale
    Datei fuer die Trainingssaisons fehlt und fuer die Testsaison
    vorliegt. Genau das ist der Defekt - und kein einziger Fall
    beruht auf einer tatsaechlich unbekannten Mitgliedschaft.
    """

    def test_jeder_c19_ausfall_ist_eine_dateiluecke(self):
        import pathlib

        from src.data.historical_loader import season_file_path
        from src.ml import cl_evaluate as ce
        from src.ml import dataset as ds

        zeilen, _d = ds.build_dataset(include_cl=True)
        faelle = 0
        for fold in ce.OUTER_FOLDS:
            c19_karte, _k = c19.build_team_league_map(
                max(fold["train_seasons"]))
            c20_karte = c20.fold_map(fold)
            for zeile in ce.cl_rows(zeilen, fold["test_season"]):
                for feld in ("home_id", "away_id"):
                    tid = zeile[feld]
                    if tid in c19_karte or tid not in c20_karte:
                        continue
                    faelle += 1
                    liga = c20_karte[tid]
                    for saison in fold["train_seasons"]:
                        assert not pathlib.Path(
                            season_file_path(liga, saison)).is_file(), (
                            tid, liga, saison)
                    assert pathlib.Path(season_file_path(
                        liga, fold["test_season"])).is_file()
        assert faelle > 0, "ohne Faelle waere dieser Test blind"

    def test_das_diagnoseartefakt_nennt_die_kausalkette(self):
        with open("data/ml/c20_pd_diagnosis.json", encoding="utf-8") as datei:
            diagnose = json.load(datei)
        kette = diagnose["causal_chain"]
        assert kette["parameters_identical_across_variants"] is True
        assert kette["a_equals_c_on_all_rows"] is True
        assert kette["rows_differing_a_vs_b"] == 52
        varianten = diagnose["variants"]
        assert varianten["B_c19_training_end"]["verdict"] == "rejected"
        assert varianten["C_c20_prediction_season"]["verdict"] == "accepted"
        fps = {name: v["fold_parameter_fingerprints"]
               for name, v in varianten.items()}
        assert len({json.dumps(f, sort_keys=True) for f in fps.values()}) == 1
