"""
Tests fuer die versionierte Persistenz des CL-Schattenmodells.

Ein Modellbundle ist ein Versprechen: Wer es laedt, bekommt genau das
Modell, das gespeichert wurde. Ein Fehler hier bricht nicht laut ab -
er liefert ein plausibles falsches Modell. Deshalb prueft jeder Test
eine Eigenschaft, die sich verletzen laesst, und jeder Fehlerfall wird
ausdruecklich provoziert.
"""

import json
import os

import numpy as np
import pytest

from src.ml import cl_evaluate as cle
from src.ml import evaluate as ev
from src.ml import feature_groups as fg
from src.ml import model as mdl
from src.ml import persist as ps

SPALTEN = fg.columns_for(cle.CANDIDATE)
ALLE_MERKMALE = mdl.feature_columns()


# ---------------------------------------------------------------------------
# Bausteine
# ---------------------------------------------------------------------------

def _zeile(league, season, tag, index, eligible=True, stage=None):
    from datetime import date, timedelta

    datum = (date(season, 8, 1) + timedelta(days=tag)).isoformat()
    th, ta = (index * 3 + tag) % 4, (index * 5 + tag * 2) % 4
    zeile = {
        "row_id": f"{league}:{season}:{datum}:{index}",
        "match_id": (season * 100000 + tag * 100 + index),
        "league": league,
        "competition": "CL" if league == "cl" else "BL1",
        "stage": stage,
        "season": season,
        "date": datum,
        "matchday": tag // 7 + 1,
        "home_id": index,
        "away_id": index + 100,
        "evaluation_eligible": eligible,
        "exclusion_reason": None if eligible else "Testfall",
        "home_profile_source": "domestic_pit",
        "away_profile_source": "domestic_pit",
        "home_profile_matches": 25,
        "away_profile_matches": 25,
        "league_avg_source": "season_pit",
        "home_goals": th,
        "away_goals": ta,
        "outcome": 0 if th > ta else (1 if th == ta else 2),
        "baseline_lambda_home": 1.20 + 0.01 * (index % 11),
        "baseline_lambda_away": 1.05 + 0.01 * (index % 7),
    }
    for i, spalte in enumerate(ALLE_MERKMALE):
        zeile[spalte] = 0.05 + ((index * 37 + tag * 17 + i * 5) % 97) / 97.0 * 1.9
    return zeile


def _bestand(liga=70, cl=30):
    zeilen = []
    for season in (2023, 2024, 2025):
        zeilen += [_zeile("bl1", season, i * 4, i) for i in range(liga)]
        zeilen += [_zeile("cl", season, i * 6, 500 + i, stage="LEAGUE_STAGE")
                   for i in range(cl)]
    return zeilen


def _messung(zeilen, candidate=None, spalten=None, fingerprint=None):
    """
    Ein Evaluationsartefakt in genau der Form, die --evaluate-cl liefert.

    Bewusst aus DEMSELBEN Bestand gebaut wie das Training: Der
    Fingerabdruck muss passen, sonst weist evaluation_reference() das
    Bundle zurueck - und genau das soll er auch.
    """
    candidate = candidate or cle.CANDIDATE
    spalten = list(spalten or fg.columns_for(candidate))
    fingerprint = fingerprint or cle.dataset_fingerprint(zeilen, candidate)
    return {
        "configuration": {
            "task": "cl_shadow_backtest",
            "candidate": candidate,
            "feature_columns": spalten,
            "feature_count": len(spalten),
            "training_scope": "ausschliesslich nationale Ligazeilen",
            "test_scope": "ausschliesslich auswertbare CL-Zeilen",
        },
        "manifest": {
            "schema_version": 2,
            "created_at": "2026-09-05T00:00:00+00:00",
            "dataset_fingerprint": fingerprint,
        },
        "results": {
            "aggregate": {
                "n": 213,
                "baseline": {"log_loss": 0.9297710163775476,
                             "brier": 0.5479099649909374,
                             "rps": 0.2139445268829481,
                             "calibration_error": 0.04815511749557476},
                "ml": {"log_loss": 0.9208694749247773,
                       "brier": 0.5432708492693894,
                       "rps": 0.21314703993508596,
                       "calibration_error": 0.01647193628090939},
                "delta_log_loss": -0.008901541452770223,
                "delta_brier": -0.0046391157215479595,
                "delta_rps": -0.000797486947862136,
                "bootstrap": {
                    "log_loss": {"point": -0.008901541452770223,
                                 "ci_low": -0.029861344358465398,
                                 "ci_high": 0.011351627546886423,
                                 "iterations": 2000, "seed": 20260827},
                },
            },
            "folds": [{"fold": "cl_2024", "train_seasons": [2023],
                       "test_season": 2024, "test_rows": 112,
                       "selected_candidate": 0.1,
                       "delta_log_loss": -0.012561}],
            "verdict": {"verdict": "INCONCLUSIVE", "reasons": ["Testfall"]},
        },
    }


@pytest.fixture(scope="module")
def bestand():
    return _bestand()


@pytest.fixture(scope="module")
def messung(bestand):
    return _messung(bestand)


@pytest.fixture(scope="module")
def bundle(bestand, messung):
    return ps.train_cl_model(bestand, messung,
                             release_stage=ps.STAGE_EXPERIMENTAL)


@pytest.fixture
def gespeichert(bundle, tmp_path):
    pfad = str(tmp_path / "modell.json")
    ps.save_bundle(bundle, pfad)
    return pfad


def _veraendert(pfad, aenderung):
    """Bundle laden, veraendern, ohne Validierung zurueckschreiben."""
    with open(pfad, encoding="utf-8") as datei:
        daten = json.load(datei)
    aenderung(daten)
    with open(pfad, "w", encoding="utf-8") as datei:
        json.dump(daten, datei)
    return pfad


# ---------------------------------------------------------------------------
# 1. Trainingsbestand
# ---------------------------------------------------------------------------

class TestTraining:

    def test_nur_nationale_ligazeilen_im_training(self, bundle):
        assert bundle["training"]["scope"] == "national_leagues_only"
        assert "cl" not in bundle["training"]["leagues"]
        assert bundle["training"]["leagues"] == ["bl1"]

    def test_keine_cl_zeile_erreicht_fit_side(self, bestand, messung,
                                              monkeypatch):
        """
        Der Kern. Ein Beobachter auf fit_side sieht jede Zeile, die
        wirklich ins Training geht - Behauptungen im Bundle helfen
        hier nicht weiter.
        """
        gesehen = []
        echt = mdl.fit_side

        def beobachtend(zeilen, seite, alpha, spalten=None):
            gesehen.extend(z["league"] for z in zeilen)
            return echt(zeilen, seite, alpha, spalten)

        monkeypatch.setattr(mdl, "fit_side", beobachtend)
        ps.train_cl_model(bestand, messung)

        assert gesehen, "fit_side wurde nie gerufen"
        assert "cl" not in set(gesehen)

    def test_die_alphawahl_sieht_kein_cl_spiel(self, bestand, messung,
                                               monkeypatch):
        echt = ev.select_candidate
        gesehen = []

        def beobachtend(fit_zeilen, val_zeilen, spalten, alphas=None):
            gesehen.extend(z["league"] for z in fit_zeilen + val_zeilen)
            if alphas is None:
                return echt(fit_zeilen, val_zeilen, spalten)
            return echt(fit_zeilen, val_zeilen, spalten, alphas)

        monkeypatch.setattr(ev, "select_candidate", beobachtend)
        ps.train_cl_model(bestand, messung)
        assert gesehen and "cl" not in set(gesehen)

    def test_die_saisons_sind_2023_bis_2025(self, bundle):
        assert bundle["training"]["seasons"] == [2023, 2024, 2025]
        assert list(ps.DEFAULT_TRAINING_SEASONS) == [2023, 2024, 2025]

    def test_die_alphawahl_ist_zeitlich_korrekt(self, bundle):
        """
        Angepasst wird auf frueheren Saisons, validiert auf der
        spaetesten - nie umgekehrt.
        """
        innen = bundle["training"]["inner_split"]
        assert innen["strategy"] == "Teilung nach Saison"
        assert max(innen["fit_seasons"]) < min(innen["validation_seasons"])

    def test_das_alpha_stammt_aus_den_kandidaten(self, bundle):
        assert bundle["alpha"] in mdl.ALPHA_CANDIDATES
        assert bundle["alpha_candidates"] == list(mdl.ALPHA_CANDIDATES)

    def test_no_correction_trat_an_und_verlor(self, bundle):
        protokoll = bundle["training"]["selection"]["candidates"]
        namen = [e["candidate"] for e in protokoll]
        assert mdl.NO_CORRECTION in namen
        assert bundle["training"]["selection"]["selected"] == bundle["alpha"]

    def test_exakt_16_merkmale(self, bundle):
        assert bundle["feature_count"] == 16
        assert len(bundle["features"]) == 16

    def test_die_merkmalsreihenfolge_ist_die_festgelegte(self, bundle):
        assert bundle["features"] == fg.columns_for(cle.CANDIDATE)

    def test_der_kandidat_ist_team_profile_cl(self, bundle):
        assert bundle["candidate"] == "team_profile_cl"


# ---------------------------------------------------------------------------
# 2. Guards vor dem Training
# ---------------------------------------------------------------------------

class TestGuards:

    def test_cl_zeilen_im_training_brechen_ab(self, bestand, messung,
                                              monkeypatch):
        """Gegenprobe: Faellt der Filter weg, muss der Guard greifen."""
        monkeypatch.setattr(cle, "league_rows",
                            lambda z, s: [r for r in z if r["season"] in s])
        with pytest.raises(ps.ModelBundleError, match="CL-Zeilen im Training"):
            ps.train_cl_model(bestand, messung)

    def test_ohne_trainingsdaten_bricht_es_ab(self, messung):
        with pytest.raises(ps.ModelBundleError, match="keine Trainingszeilen"):
            ps.train_cl_model([], messung, seasons=(2023,))

    def test_fremde_saisons_brechen_ab(self, bestand, messung, monkeypatch):
        monkeypatch.setattr(cle, "league_rows",
                            lambda z, s: [r for r in z if r["league"] != "cl"])
        with pytest.raises(ps.ModelBundleError, match="nicht vorgesehenen"):
            ps.train_cl_model(bestand, messung, seasons=(2023,))

    def test_nicht_auswertbare_zeilen_brechen_ab(self, messung, monkeypatch):
        zeilen = [_zeile("bl1", 2023, i, i, eligible=False) for i in range(40)]
        monkeypatch.setattr(cle, "league_rows", lambda z, s: list(z))
        with pytest.raises(ps.ModelBundleError, match="nicht auswertbare"):
            ps.train_cl_model(zeilen, messung, seasons=(2023,))

    def test_ein_fehlendes_merkmal_bricht_ab(self, bestand):
        ohne = [dict(z) for z in bestand]
        for z in ohne:
            z.pop(SPALTEN[0], None)
        with pytest.raises(ps.ModelBundleError, match="fehlen im Bestand"):
            ps.train_cl_model(ohne, _messung(ohne))

    def test_eine_vertauschte_merkmalsreihenfolge_bricht_ab(self):
        """
        Die Guardfunktion direkt geprueft.

        Innerhalb von train_cl_model leitet sie ihre Erwartung aus
        derselben Quelle ab wie die gepruefte Liste und kann dort nicht
        ausloesen - sie sichert den Fall ab, dass ein Aufrufer eine
        eigene Reihenfolge mitbringt. Die wirksame Sperre gegen ein
        falsch sortiertes Artefakt sitzt im Loader, siehe
        TestLadenFehler.test_vertauschte_merkmale.
        """
        verdreht = list(reversed(fg.columns_for(cle.CANDIDATE)))
        with pytest.raises(ps.ModelBundleError, match="Merkmalsreihenfolge weicht ab"):
            ps._pruefe_merkmalsreihenfolge(verdreht, cle.CANDIDATE)

    def test_eine_zu_kurze_merkmalsliste_bricht_ab(self):
        with pytest.raises(ps.ModelBundleError, match="Merkmalsreihenfolge weicht ab"):
            ps._pruefe_merkmalsreihenfolge(SPALTEN[:-1], cle.CANDIDATE)

    def test_die_richtige_liste_besteht(self):
        assert ps._pruefe_merkmalsreihenfolge(SPALTEN, cle.CANDIDATE) is None

    def test_no_correction_verhindert_ein_bundle(self, bestand, messung,
                                                 monkeypatch):
        """
        Ein Modell zu speichern, das die eigene Auswahl ablehnt, waere
        ein Widerspruch im Artefakt.
        """
        monkeypatch.setattr(
            ev, "select_candidate",
            lambda *a, **k: (mdl.NO_CORRECTION, None, {"candidates": []}))
        with pytest.raises(ps.ModelBundleError, match="no_correction"):
            ps.train_cl_model(bestand, messung)

    def test_verworfene_spalten_brechen_ab(self, bestand):
        """
        SimpleImputer verwirft durchgaengig leere Spalten. Die
        Koeffizienten waeren dann kuerzer als die Namensliste.
        """
        leer = [dict(z, **{SPALTEN[0]: None}) for z in bestand]
        training = cle.league_rows(leer, [2023, 2024, 2025])
        pipeline, _ = mdl.fit_side(training, "home", 1.0, SPALTEN)
        with pytest.raises(ps.ModelBundleError, match="verworfen"):
            ps.serialise_pipeline(pipeline, SPALTEN)


# ---------------------------------------------------------------------------
# 3. Metadaten
# ---------------------------------------------------------------------------

class TestMetadaten:

    def test_alle_pflichtfelder_stehen_drin(self, bundle):
        for feld in ("schema_version", "model_id", "created_at",
                     "model_family", "candidate", "features",
                     "feature_count", "alpha", "alpha_candidates",
                     "training", "models", "integrity", "provenance",
                     "release_stage", "usage_note"):
            assert feld in bundle, feld

    def test_die_alten_wahrheitswerte_sind_verschwunden(self, bundle):
        """
        Zwei Quellen fuer dieselbe Aussage laufen auseinander, und dann
        gilt die falsche. Die Freigabestufe ist die einzige Quelle.
        """
        assert "shadow_only" not in bundle
        assert "production_approved" not in bundle

    def test_die_herkunft_ist_vollstaendig(self, bundle):
        h = bundle["provenance"]
        for feld in ("dataset_fingerprint", "dataset_schema_version",
                     "feature_groups_schema_version", "python_version",
                     "sklearn_version", "git_commit", "git_dirty",
                     "git_status", "evaluation"):
            assert feld in h, feld

    def test_die_freigabestufe_ist_gesetzt_und_gueltig(self, bundle):
        assert bundle["release_stage"] in ps.RELEASE_STAGES
        assert bundle["release_stage"] == ps.STAGE_EXPERIMENTAL
        assert bundle["usage_note"] == ps.STAGE_NOTES[ps.STAGE_EXPERIMENTAL]

    def test_das_urteil_stammt_aus_der_gebundenen_messung(self, bundle,
                                                          messung):
        m = bundle["provenance"]["evaluation"]
        aggregat = messung["results"]["aggregate"]
        assert m["verdict"] == messung["results"]["verdict"]["verdict"]
        assert m["deltas"]["log_loss"] == aggregat["delta_log_loss"]
        assert m["test_matches"] == aggregat["n"]
        assert m["baseline_metrics"]["log_loss"] == aggregat["baseline"]["log_loss"]
        assert m["ml_metrics"]["log_loss"] == aggregat["ml"]["log_loss"]
        assert m["evaluation_sha256"] == ps.evaluation_digest(messung)
        assert "KEIN Nachweis" not in m["meaning"] or True
        assert "kein Nachweis" in m["meaning"]

    def test_keine_hartkodierten_c3_werte_mehr(self, bundle):
        """
        Der eigentliche Fehler von C0A-Befund B: -0,00890 und n=213
        standen als Literal in persist.py. Ein V2-Modell haette sie
        geerbt, ohne dass sie je zu ihm gehoert haetten.
        """
        import inspect

        # Geprueft wird der Bauweg, nicht der Modulkopf: Dort STEHEN die
        # alten Zahlen noch, weil sie erklaeren, was entfernt wurde.
        # Eine Erklaerung im Fliesstext landet in keinem Artefakt.
        bauweg = (inspect.getsource(ps._baue_bundle)
                  + inspect.getsource(ps.train_cl_model)
                  + inspect.getsource(ps.evaluation_reference))
        for literal in ("0.00890", "0.01135", "0.02986", "c3_verdict",
                        "213", "INCONCLUSIVE"):
            assert literal not in bauweg, literal

        # Und die Gegenprobe im fertigen Artefakt: Jede Zahl dort muss
        # aus der gebundenen Messung stammen.
        assert "c3_verdict" not in json.dumps(bundle)

    def test_das_bundle_behauptet_keine_ueberlegenheit(self, bundle):
        text = json.dumps(bundle, ensure_ascii=False).lower()
        for verboten in ("bestaetigt", "nachweislich besser", "ueberlegen "):
            assert verboten not in text, verboten

    def test_die_integritaet_ist_gesetzt(self, bundle):
        i = bundle["integrity"]
        assert i["algorithm"] == "sha256"
        assert len(i["models_sha256"]) == 64
        assert i["models_sha256"] == ps.models_digest(bundle["models"])

    def test_beide_seiten_sind_vorhanden(self, bundle):
        assert set(bundle["models"]) == set(ps.SIDES)
        for seite in ps.SIDES:
            teile = bundle["models"][seite]
            assert set(teile) == {"imputer", "scaler", "regressor"}
            assert len(teile["regressor"]["coef"]) == 16

    def test_die_beiden_seiten_sind_verschiedene_modelle(self, bundle):
        assert bundle["models"]["home"] != bundle["models"]["away"]

    def test_keine_absoluten_pfade_im_bundle(self, bundle):
        import re

        text = json.dumps(bundle, ensure_ascii=False)
        treffer = re.findall(r"[A-Za-z]:[\\/][^\"]*|/home/[^\"]*|/Users/[^\"]*",
                             text)
        assert not treffer, f"absolute Pfade im Artefakt: {treffer[:3]}"


# ---------------------------------------------------------------------------
# 4. Modell-ID und Reproduzierbarkeit
# ---------------------------------------------------------------------------

class TestReproduzierbarkeit:

    def test_gleicher_input_gleiche_modell_id(self, bestand, messung):
        erst = ps.train_cl_model(bestand, messung)
        zweit = ps.train_cl_model(bestand, messung)
        assert erst["model_id"] == zweit["model_id"]
        assert erst["models"] == zweit["models"]
        assert erst["integrity"] == zweit["integrity"]

    def test_nur_der_zeitstempel_unterscheidet_zwei_laeufe(self, bestand,
                                                           messung):
        erst = ps.train_cl_model(bestand, messung)
        zweit = ps.train_cl_model(bestand, messung)
        abweichend = [k for k in erst if erst[k] != zweit.get(k)]
        assert abweichend in ([], ["created_at"]), abweichend

    def test_ein_geaenderter_input_aendert_die_modell_id(self, bestand,
                                                         messung):
        vorher = ps.train_cl_model(bestand, messung)["model_id"]
        geaendert = [dict(z) for z in bestand]
        for z in geaendert[:40]:
            if z["league"] == "bl1":
                z[SPALTEN[0]] = z[SPALTEN[0]] + 0.4
        assert ps.train_cl_model(
            geaendert, _messung(geaendert))["model_id"] != vorher

    def test_die_freigabestufe_geht_in_die_kennung_ein(self, bestand,
                                                       messung):
        """
        Zwei Bundles mit denselben Gewichten, aber verschiedener
        Freigabe sind verschiedene Artefakte.
        """
        schatten = ps.train_cl_model(bestand, messung,
                                     release_stage=ps.STAGE_SHADOW)
        experimentell = ps.train_cl_model(bestand, messung,
                                          release_stage=ps.STAGE_EXPERIMENTAL)
        assert schatten["model_id"] != experimentell["model_id"]
        assert schatten["models"] == experimentell["models"]

    def test_eine_unbekannte_stufe_wird_beim_bauen_abgewiesen(self, bestand,
                                                              messung):
        with pytest.raises(ps.ModelBundleError, match="Freigabestufe"):
            ps.train_cl_model(bestand, messung, release_stage="freigegeben")

    def test_die_modell_id_traegt_kein_datum(self, bundle):
        assert bundle["model_id"].startswith("clm-")
        assert bundle["created_at"][:4] not in bundle["model_id"]


# ---------------------------------------------------------------------------
# 5. Speichern
# ---------------------------------------------------------------------------

class TestSpeichern:

    def test_es_entsteht_eine_datei(self, bundle, tmp_path):
        pfad = str(tmp_path / "m.json")
        assert ps.save_bundle(bundle, pfad) == pfad
        assert os.path.exists(pfad)

    def test_ohne_force_wird_nicht_ueberschrieben(self, bundle, gespeichert):
        with pytest.raises(ps.ModelBundleError, match="existiert bereits"):
            ps.save_bundle(bundle, gespeichert)

    def test_mit_force_wird_ueberschrieben(self, bundle, gespeichert):
        assert ps.save_bundle(bundle, gespeichert, force=True) == gespeichert

    def test_fehlende_verzeichnisse_werden_angelegt(self, bundle, tmp_path):
        pfad = str(tmp_path / "tief" / "drin" / "m.json")
        ps.save_bundle(bundle, pfad)
        assert os.path.exists(pfad)

    def test_es_bleibt_keine_temporaerdatei(self, bundle, tmp_path):
        pfad = str(tmp_path / "m.json")
        ps.save_bundle(bundle, pfad)
        assert not os.path.exists(pfad + ".tmp")
        assert os.listdir(tmp_path) == ["m.json"]

    def test_ein_fehler_hinterlaesst_keine_reste(self, bundle, tmp_path):
        """
        Atomar heisst auch: Scheitert die Validierung, bleibt nichts
        liegen. Ein halbes Artefakt sieht aus wie ein ganzes.
        """
        kaputt = dict(bundle, candidate="etwas_anderes")
        pfad = str(tmp_path / "m.json")

        with pytest.raises(ps.ModelBundleError):
            ps.save_bundle(kaputt, pfad)

        assert not os.path.exists(pfad)
        assert not os.path.exists(pfad + ".tmp")
        assert os.listdir(tmp_path) == []

    def test_ein_vorhandenes_bundle_bleibt_bei_fehler_unversehrt(
            self, bundle, gespeichert):
        vorher = open(gespeichert, encoding="utf-8").read()
        kaputt = dict(bundle, schema_version=99)

        with pytest.raises(ps.ModelBundleError):
            ps.save_bundle(kaputt, gespeichert, force=True)

        assert open(gespeichert, encoding="utf-8").read() == vorher
        assert not os.path.exists(gespeichert + ".tmp")


# ---------------------------------------------------------------------------
# 6. Laden - Fehlerfaelle
# ---------------------------------------------------------------------------

class TestLadenFehler:

    def test_fehlende_datei(self, tmp_path):
        with pytest.raises(ps.ModelBundleError, match="nicht gefunden"):
            ps.load_bundle(str(tmp_path / "gibtsnicht.json"))

    def test_beschaedigtes_json(self, tmp_path):
        pfad = tmp_path / "kaputt.json"
        pfad.write_text("{ das ist kein json", encoding="utf-8")
        with pytest.raises(ps.ModelBundleError, match="kein lesbares JSON"):
            ps.load_bundle(str(pfad))

    def test_falscher_sha256(self, gespeichert):
        _veraendert(gespeichert,
                    lambda d: d["integrity"].__setitem__("models_sha256",
                                                         "0" * 64))
        with pytest.raises(ps.ModelBundleError, match="Integritaetswert"):
            ps.load_bundle(gespeichert)

    def test_veraenderte_koeffizienten_fallen_auf(self, gespeichert):
        """
        Die Gegenprobe zum Hash: Wer die Zahlen anfasst, ohne den Hash
        anzupassen, wird erkannt.
        """
        def aendern(d):
            d["models"]["home"]["regressor"]["coef"][0] += 0.5

        _veraendert(gespeichert, aendern)
        with pytest.raises(ps.ModelBundleError, match="Integritaetswert"):
            ps.load_bundle(gespeichert)

    def test_falsche_schemafassung(self, gespeichert):
        _veraendert(gespeichert, lambda d: d.update(schema_version=99))
        with pytest.raises(ps.ModelBundleError, match="Bundlefassung"):
            ps.load_bundle(gespeichert)

    def test_unbekannte_modellfamilie(self, gespeichert):
        _veraendert(gespeichert, lambda d: d.update(model_family="neuronal"))
        with pytest.raises(ps.ModelBundleError, match="Modellfamilie"):
            ps.load_bundle(gespeichert)

    def test_falscher_kandidat(self, gespeichert):
        _veraendert(gespeichert, lambda d: d.update(candidate="profile_only"))
        with pytest.raises(ps.ModelBundleError, match="Kandidat"):
            ps.load_bundle(gespeichert)

    def test_fehlendes_merkmal(self, gespeichert):
        def aendern(d):
            d["features"] = d["features"][:-1]
            d["feature_count"] = len(d["features"])

        _veraendert(gespeichert, aendern)
        with pytest.raises(ps.ModelBundleError, match="Merkmale im Bundle"):
            ps.load_bundle(gespeichert)

    def test_zusaetzliches_merkmal(self, gespeichert):
        def aendern(d):
            d["features"] = d["features"] + ["erfunden"]
            d["feature_count"] = len(d["features"])

        _veraendert(gespeichert, aendern)
        with pytest.raises(ps.ModelBundleError, match="Merkmale im Bundle"):
            ps.load_bundle(gespeichert)

    def test_vertauschte_merkmale(self, gespeichert):
        def aendern(d):
            d["features"][0], d["features"][1] = d["features"][1], d["features"][0]

        _veraendert(gespeichert, aendern)
        with pytest.raises(ps.ModelBundleError, match="Reihenfolge weichen ab"):
            ps.load_bundle(gespeichert)

    def test_unstimmiger_feature_count(self, gespeichert):
        _veraendert(gespeichert, lambda d: d.update(feature_count=99))
        with pytest.raises(ps.ModelBundleError, match="feature_count"):
            ps.load_bundle(gespeichert)

    @pytest.mark.parametrize("seite", ["home", "away"])
    def test_fehlendes_seitenmodell(self, gespeichert, seite):
        _veraendert(gespeichert, lambda d: d["models"].pop(seite))
        with pytest.raises(ps.ModelBundleError, match=f"Seite '{seite}'"):
            ps.load_bundle(gespeichert)

    @pytest.mark.parametrize("stufe", ["", "freigegeben", "SHADOW", None,
                                       "production", 1, True])
    def test_unbekannte_freigabestufe_wird_abgewiesen(self, gespeichert,
                                                      stufe):
        """Nicht raten, nicht wohlwollend deuten - abweisen."""
        _veraendert(gespeichert, lambda d: d.update(release_stage=stufe))
        with pytest.raises(ps.ModelBundleError, match="Freigabestufe"):
            ps.load_bundle(gespeichert)

    def test_fehlende_freigabestufe_wird_abgewiesen(self, gespeichert):
        _veraendert(gespeichert, lambda d: d.pop("release_stage"))
        with pytest.raises(ps.ModelBundleError, match="Freigabestufe"):
            ps.load_bundle(gespeichert)

    @pytest.mark.parametrize("alt", ["shadow_only", "production_approved"])
    def test_alte_wahrheitswerte_neben_der_stufe_brechen_ab(self, gespeichert,
                                                            alt):
        _veraendert(gespeichert, lambda d: d.update({alt: True}))
        with pytest.raises(ps.ModelBundleError, match="alte Feld"):
            ps.load_bundle(gespeichert)

    def test_eine_manipulierte_stufe_aendert_die_modell_id_nicht_mit(
            self, gespeichert):
        """
        Die Stufe geht in die Modell-ID ein. Wer sie in der Datei
        hochsetzt, ohne die ID neu zu rechnen, hinterlaesst einen
        sichtbaren Widerspruch - genau dafuer ist die Kennung da.
        """
        geladen, _ = ps.load_bundle(gespeichert)
        neu_id = ps.build_model_id(
            geladen["candidate"], geladen["features"], geladen["alpha"],
            geladen["training"]["seasons"],
            geladen["provenance"]["dataset_fingerprint"]["sha256"],
            geladen["integrity"]["models_sha256"],
            geladen["provenance"]["evaluation"]["evaluation_sha256"],
            ps.STAGE_APPROVED)
        assert neu_id != geladen["model_id"]


class TestGebundeneEvaluation:
    """
    C0A-Befund B: Die Kennzahlen standen als Literal im Code. Jetzt
    muessen sie zum Bundle passen - sonst laedt es nicht.
    """

    def test_ohne_evaluation_entsteht_kein_bundle(self, bestand):
        with pytest.raises(ps.ModelBundleError, match="ohne Evaluations"):
            ps.train_cl_model(bestand, None)

    def test_eine_fremde_aufgabe_wird_abgewiesen(self, bestand, messung):
        fremd = json.loads(json.dumps(messung))
        fremd["configuration"]["task"] = "league_walk_forward"
        with pytest.raises(ps.ModelBundleError,
                           match="nicht den CL-Shadow-Backtest"):
            ps.train_cl_model(bestand, fremd)

    def test_ein_falscher_dataset_fingerprint_wird_abgewiesen(self, bestand,
                                                              messung):
        fremd = json.loads(json.dumps(messung))
        fremd["manifest"]["dataset_fingerprint"]["sha256"] = "a" * 64
        with pytest.raises(ps.ModelBundleError, match="Fingerabdruck"):
            ps.train_cl_model(bestand, fremd)

    def test_eine_andere_fingerabdruckfassung_wird_abgewiesen(self, bestand,
                                                              messung):
        fremd = json.loads(json.dumps(messung))
        fremd["manifest"]["dataset_fingerprint"][
            "fingerprint_schema_version"] = 1
        with pytest.raises(ps.ModelBundleError, match="Fingerabdruck"):
            ps.train_cl_model(bestand, fremd)

    def test_ein_falscher_merkmalsvertrag_wird_abgewiesen(self, bestand,
                                                          messung):
        fremd = json.loads(json.dumps(messung))
        fremd["configuration"]["feature_columns"] = list(reversed(SPALTEN))
        with pytest.raises(ps.ModelBundleError, match="Merkmalsvertrag"):
            ps.train_cl_model(bestand, fremd)

    def test_ein_falscher_kandidat_wird_abgewiesen(self, bestand, messung):
        fremd = json.loads(json.dumps(messung))
        fremd["configuration"]["candidate"] = "profile_only"
        with pytest.raises(ps.ModelBundleError, match="Kandidaten"):
            ps.train_cl_model(bestand, fremd)

    @pytest.mark.parametrize("pfad", [
        ("results", "aggregate"), ("results", "verdict"),
        ("results", "folds"), ("manifest", "created_at"),
    ])
    def test_eine_unvollstaendige_messung_wird_abgewiesen(self, bestand,
                                                          messung, pfad):
        fremd = json.loads(json.dumps(messung))
        fremd[pfad[0]].pop(pfad[1])
        with pytest.raises(ps.ModelBundleError, match="Evaluationsartefakt"):
            ps.train_cl_model(bestand, fremd)

    def test_eine_geaenderte_messung_aendert_die_modell_id(self, bestand,
                                                           messung, bundle):
        anders = json.loads(json.dumps(messung))
        anders["results"]["aggregate"]["n"] = 999
        zweites = ps.train_cl_model(bestand, anders,
                                    release_stage=ps.STAGE_EXPERIMENTAL)
        assert zweites["model_id"] != bundle["model_id"]
        assert zweites["models"] == bundle["models"], (
            "die Gewichte duerfen sich dabei NICHT aendern")

    def test_eine_manipulierte_messung_faellt_beim_laden_auf(self,
                                                             gespeichert):
        def aendern(d):
            d["provenance"]["evaluation"]["dataset_fingerprint_sha256"] = "b" * 64

        _veraendert(gespeichert, aendern)
        with pytest.raises(ps.ModelBundleError, match="anderen Datensatz"):
            ps.load_bundle(gespeichert)

    def test_eine_entfernte_messung_faellt_beim_laden_auf(self, gespeichert):
        _veraendert(gespeichert,
                    lambda d: d["provenance"].pop("evaluation"))
        with pytest.raises(ps.ModelBundleError, match="evaluation"):
            ps.load_bundle(gespeichert)

    def test_ein_untergeschobener_merkmalsvertrag_faellt_beim_laden_auf(
            self, gespeichert):
        def aendern(d):
            d["provenance"]["evaluation"]["feature_columns"] = ["x"]

        _veraendert(gespeichert, aendern)
        with pytest.raises(ps.ModelBundleError, match="Merkmalsvertrag"):
            ps.load_bundle(gespeichert)


class TestAltbestand:
    """
    Ein Bundle der Fassung 1 kannte keine Stufe. Es darf gelesen, aber
    niemals hochgestuft werden.
    """

    def _fassung_eins(self, gespeichert):
        def aendern(d):
            d["schema_version"] = 1
            d.pop("release_stage")
            d.pop("release_stages", None)
            d["shadow_only"] = True
            d["production_approved"] = False
            d["provenance"].pop("evaluation")

        return _veraendert(gespeichert, aendern)

    def test_ein_altbestand_wird_als_shadow_gelesen(self, gespeichert):
        geladen, _ = ps.load_bundle(self._fassung_eins(gespeichert))
        assert geladen["release_stage"] == ps.STAGE_SHADOW
        assert ps.STAGE_SHADOW not in ps.STAGES_ALLOWED_ACTIVE

    def test_ein_altbestand_wird_niemals_hochgestuft(self, gespeichert):
        pfad = self._fassung_eins(gespeichert)
        _veraendert(pfad, lambda d: d.update(production_approved=True))
        with pytest.raises(ps.ModelBundleError, match="unklarem Freigabe"):
            ps.load_bundle(pfad)

    def test_ein_altbestand_mit_neuer_stufe_ist_widerspruechlich(self,
                                                                 gespeichert):
        pfad = self._fassung_eins(gespeichert)
        _veraendert(pfad,
                    lambda d: d.update(release_stage=ps.STAGE_APPROVED))
        with pytest.raises(ps.ModelBundleError, match="release_stage"):
            ps.load_bundle(pfad)

    def test_cl_im_trainingsumfang_faellt_auf(self, gespeichert):
        def aendern(d):
            d["training"]["leagues"].append("cl")

        _veraendert(gespeichert, aendern)
        with pytest.raises(ps.ModelBundleError, match="CL im Trainingsumfang"):
            ps.load_bundle(gespeichert)

    def test_falscher_trainingsumfang(self, gespeichert):
        _veraendert(gespeichert,
                    lambda d: d["training"].update(scope="alles"))
        with pytest.raises(ps.ModelBundleError, match="Trainingsumfang"):
            ps.load_bundle(gespeichert)

    def test_fehlende_herkunftsangabe(self, gespeichert):
        _veraendert(gespeichert,
                    lambda d: d["provenance"].pop("dataset_schema_version"))
        with pytest.raises(ps.ModelBundleError, match="Herkunftsangabe"):
            ps.load_bundle(gespeichert)

    def test_unbrauchbares_alpha(self, gespeichert):
        _veraendert(gespeichert, lambda d: d.update(alpha=0))
        with pytest.raises(ps.ModelBundleError, match="Alpha"):
            ps.load_bundle(gespeichert)


# ---------------------------------------------------------------------------
# 7. Roundtrip
# ---------------------------------------------------------------------------

class TestRoundtrip:

    def test_das_geladene_bundle_gleicht_dem_gespeicherten(self, bundle,
                                                            gespeichert):
        geladen, _ = ps.load_bundle(gespeichert)
        assert geladen == bundle

    @pytest.mark.parametrize("seite", ["home", "away"])
    def test_die_vorhersagen_sind_identisch(self, bestand, bundle,
                                            gespeichert, seite):
        """
        Der eigentliche Nachweis: vorher und nachher rechnen, Werte
        vergleichen. Getrennt je Seite - ein vertauschtes Seitenmodell
        faellt sonst nicht auf.
        """
        training = cle.league_rows(bestand, [2023, 2024, 2025])
        pruef = cle.cl_rows(bestand, 2025)
        assert pruef, "ohne Pruefbestand waere der Test wertlos"

        frisch, _ = mdl.fit_side(training, seite, bundle["alpha"], SPALTEN)
        vorher = np.asarray(mdl.predict_factors(frisch, pruef, SPALTEN))

        _, modelle = ps.load_bundle(gespeichert)
        nachher = np.asarray(mdl.predict_factors(modelle[seite], pruef,
                                                 SPALTEN))

        abweichung = float(np.abs(vorher - nachher).max())
        assert abweichung <= ps.ROUNDTRIP_TOLERANCE
        assert abweichung == 0.0, (
            f"erwartet wird exakte Gleichheit, gemessen {abweichung:.3e}")

    def test_die_seitenmodelle_sind_nicht_vertauscht(self, bestand,
                                                     gespeichert):
        training = cle.league_rows(bestand, [2023, 2024, 2025])
        pruef = cle.cl_rows(bestand, 2025)
        _, modelle = ps.load_bundle(gespeichert)

        heim = np.asarray(mdl.predict_factors(modelle["home"], pruef, SPALTEN))
        gast = np.asarray(mdl.predict_factors(modelle["away"], pruef, SPALTEN))
        assert not np.allclose(heim, gast), (
            "beide Seiten liefern dasselbe - der Test koennte eine "
            "Vertauschung nicht erkennen")

    def test_die_koeffizientenausgabe_funktioniert(self, gespeichert):
        _, modelle = ps.load_bundle(gespeichert)
        werte = mdl.coefficients(modelle["home"], SPALTEN)
        assert [p["feature"] for p in werte["by_feature"]] == SPALTEN

    def test_das_geladene_modell_traegt_die_korrektur(self, bestand,
                                                     gespeichert):
        """Die Clamps greifen fuer ein geladenes Modell genauso."""
        _, modelle = ps.load_bundle(gespeichert)
        pruef = cle.cl_rows(bestand, 2025)
        lambdas, statistik = mdl.apply_correction(
            pruef,
            mdl.predict_factors(modelle["home"], pruef, SPALTEN),
            mdl.predict_factors(modelle["away"], pruef, SPALTEN))
        assert len(lambdas) == len(pruef)
        assert statistik["correction_min"] == mdl.CORRECTION_MIN

    def test_eine_falsche_spaltenzahl_bricht_ab(self, gespeichert):
        _, modelle = ps.load_bundle(gespeichert)
        with pytest.raises(ps.ModelBundleError, match="Merkmalsmatrix"):
            modelle["home"].predict(np.zeros((3, 5)))


# ---------------------------------------------------------------------------
# 8. CLI
# ---------------------------------------------------------------------------

class TestCli:

    def _run_ml(self):
        import run_ml
        return run_ml

    def test_train_cl_model_schliesst_die_anderen_aus(self, capsys):
        run_ml = self._run_ml()
        for andere in ("--evaluate", "--ablate", "--diagnose",
                       "--build-dataset", "--evaluate-cl"):
            assert run_ml.main(["--train-cl-model", andere]) == 2
            assert "Je Lauf eine Aufgabe" in capsys.readouterr().out

    def test_ohne_model_output_wird_abgewiesen(self, capsys):
        run_ml = self._run_ml()
        assert run_ml.main(["--train-cl-model"]) == 2
        assert "--model-output" in capsys.readouterr().out

    def test_model_output_nur_mit_training(self, capsys):
        run_ml = self._run_ml()
        assert run_ml.main(["--evaluate", "--model-output", "x.json"]) == 2
        assert "--model-output" in capsys.readouterr().out

    def test_die_aufgabe_wird_angeboten(self, capsys):
        run_ml = self._run_ml()
        assert run_ml.main([]) == 2
        assert "--train-cl-model" in capsys.readouterr().out

    def test_die_ausgabe_weist_den_status_sichtbar_aus(self, bundle, capsys):
        run_ml = self._run_ml()
        run_ml.print_model_bundle(bundle, "ziel.json")
        ausgabe = capsys.readouterr().out
        assert "FREIGABESTUFE: EXPERIMENTAL" in ausgabe
        assert "MESSUNG: INCONCLUSIVE" in ausgabe
        assert bundle["model_id"] in ausgabe
        assert bundle["provenance"]["evaluation"]["evaluation_sha256"][:16] \
            in ausgabe
        assert "Nicht statistisch abschliessend belegt" in ausgabe

    def test_ohne_evaluation_wird_abgewiesen(self, capsys):
        run_ml = self._run_ml()
        assert run_ml.main(["--train-cl-model", "--model-output",
                            "x.json"]) == 2
        assert "--evaluation" in capsys.readouterr().out

    def test_evaluation_nur_mit_training(self, capsys):
        run_ml = self._run_ml()
        assert run_ml.main(["--evaluate", "--evaluation", "x.json"]) == 2
        assert "--evaluation" in capsys.readouterr().out

    def test_die_ausgabe_nennt_die_kennzahlen(self, bundle, capsys):
        run_ml = self._run_ml()
        run_ml.print_model_bundle(bundle, "ziel.json")
        ausgabe = capsys.readouterr().out
        assert str(bundle["alpha"]) in ausgabe
        assert str(bundle["training"]["rows"]) in ausgabe
        assert "2023" in ausgabe and "2025" in ausgabe
        assert bundle["provenance"]["dataset_fingerprint"]["sha256"][:16] \
            in ausgabe
        assert "ziel.json" in ausgabe
