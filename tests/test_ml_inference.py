"""
Tests fuer die Laufzeitschicht des CL-Schattenmodells.

Diese Schicht hat eine einzige harte Zusage: Sie darf die bestehende
Simulation unter keinen Umstaenden beschaedigen. Ein fehlendes,
kaputtes oder unpassendes Modell muss zu brauchbaren Werten fuehren -
naemlich zur unveraenderten Baseline.

Deshalb wird jeder Fehlerfall ausdruecklich provoziert, und zu jedem
Rueckfall gehoert die Gegenprobe, dass die Baseline heil herauskommt.
"""

import json
import os

import pytest

from src.ml import cl_evaluate as cle
from src.ml import dataset as ds
from src.ml import feature_groups as fg
from src.ml import inference as inf
from src.ml import model as mdl
from src.ml import persist as ps

SPALTEN = fg.columns_for("team_profile_cl")


# ---------------------------------------------------------------------------
# Bausteine
# ---------------------------------------------------------------------------

def _profil(basis=1.0):
    return {feld: basis + 0.01 * i
            for i, feld in enumerate(ds.PROFILE_RATING_FELDER)}


def _merkmale(basis=1.0):
    """
    Merkmalswerte im Bereich echter Teamprofile.

    Angriff, Abwehr und Siegquote liegen bei realen Profilen um 1.0
    herum. Ein linearer Rampenwert weit ausserhalb dieses Bereichs
    wuerde die Korrektur regelmaessig an die Clampgrenze treiben - der
    Testbestand soll den Regelfall abbilden, nicht den Randfall.
    """
    return {spalte: basis + 0.005 * ((i % 7) - 3)
            for i, spalte in enumerate(SPALTEN)}


@pytest.fixture(autouse=True)
def _cache_leeren():
    """Jeder Test startet mit leerem Zwischenspeicher."""
    inf.reset_model_cache()
    yield
    inf.reset_model_cache()


@pytest.fixture(scope="module")
def echtes_bundle():
    if not os.path.exists(inf.DEFAULT_MODEL_PATH):
        pytest.skip("C4-Modellbundle nicht vorhanden")
    return inf.DEFAULT_MODEL_PATH


@pytest.fixture
def kopie(echtes_bundle, tmp_path):
    """Eine beschreibbare Kopie des echten Bundles."""
    ziel = tmp_path / "modell.json"
    ziel.write_text(open(echtes_bundle, encoding="utf-8").read(),
                    encoding="utf-8")
    return str(ziel)


def _veraendert(pfad, aenderung):
    with open(pfad, encoding="utf-8") as datei:
        daten = json.load(datei)
    aenderung(daten)
    with open(pfad, "w", encoding="utf-8") as datei:
        json.dump(daten, datei)
    return pfad


def _cl_zeilen():
    pfad = "data/ml/dataset_with_cl_2023-2025.json"
    if not os.path.exists(pfad):
        pytest.skip("CL-Datensatz nicht vorhanden")
    rows = json.load(open(pfad, encoding="utf-8"))["rows"]
    return cle.cl_rows(rows, 2025)


# ---------------------------------------------------------------------------
# 1. Modell laden und cachen
# ---------------------------------------------------------------------------

class TestModellladen:

    def test_das_gueltige_modell_wird_geladen(self, echtes_bundle):
        bundle, modelle = inf.load_model(echtes_bundle)
        assert bundle["candidate"] == "team_profile_cl"
        assert set(modelle) == {"home", "away"}

    def test_der_standardpfad_ist_repo_relativ(self):
        assert os.path.isabs(inf.DEFAULT_MODEL_PATH)
        assert inf.DEFAULT_MODEL_PATH.replace("\\", "/").endswith(
            "data/ml/models/cl_shadow_model_v1.json")

    def test_der_standardpfad_haengt_nicht_am_arbeitsverzeichnis(self,
                                                                 tmp_path,
                                                                 monkeypatch):
        vorher = inf.DEFAULT_MODEL_PATH
        monkeypatch.chdir(tmp_path)
        import importlib

        neu = importlib.reload(inf)
        try:
            assert neu.DEFAULT_MODEL_PATH == vorher
        finally:
            importlib.reload(inf)

    def test_das_modell_wird_gecacht(self, echtes_bundle, monkeypatch):
        aufrufe = []
        echt = ps.load_bundle

        def zaehlend(pfad, **kwargs):
            aufrufe.append(pfad)
            return echt(pfad, **kwargs)

        monkeypatch.setattr(ps, "load_bundle", zaehlend)
        inf.load_model(echtes_bundle)
        inf.load_model(echtes_bundle)
        inf.load_model(echtes_bundle)
        assert len(aufrufe) == 1

    def test_der_cache_laesst_sich_zuruecksetzen(self, echtes_bundle,
                                                 monkeypatch):
        aufrufe = []
        echt = ps.load_bundle
        monkeypatch.setattr(ps, "load_bundle",
                            lambda p, **k: (aufrufe.append(p),
                                            echt(p, **k))[1])
        inf.load_model(echtes_bundle)
        inf.reset_model_cache()
        inf.load_model(echtes_bundle)
        assert len(aufrufe) == 2

    def test_auch_der_fehlschlag_wird_gecacht(self, tmp_path, monkeypatch):
        aufrufe = []
        echt = ps.load_bundle
        monkeypatch.setattr(ps, "load_bundle",
                            lambda p, **k: (aufrufe.append(p),
                                            echt(p, **k))[1])
        fehlt = str(tmp_path / "weg.json")
        for _ in range(3):
            with pytest.raises(ps.ModelBundleError):
                inf.load_model(fehlt)
        assert len(aufrufe) == 1

    def test_kein_laden_beim_import(self):
        """
        Ein fehlendes Bundle darf den Prozessstart nicht beruehren.
        Nach einem frischen Import ist der Cache leer.
        """
        import importlib

        neu = importlib.reload(inf)
        assert neu._CACHE == {}

    @pytest.mark.parametrize("pfad", [
        "https://example.test/modell.json",
        "file:///tmp/modell.json",
        "\\\\server\\freigabe\\modell.json",
    ])
    def test_entfernte_pfade_werden_abgelehnt(self, pfad):
        with pytest.raises(ps.ModelBundleError, match="entfernte"):
            inf.load_model(pfad)

    @pytest.mark.parametrize("pfad", ["modell.pkl", "modell.joblib",
                                      "modell.pickle"])
    def test_binaerformate_werden_abgelehnt(self, pfad):
        with pytest.raises(ps.ModelBundleError, match="json"):
            inf.load_model(pfad)

    def test_die_seiten_werden_richtig_zugeordnet(self, echtes_bundle):
        bundle, modelle = inf.load_model(echtes_bundle)
        assert list(modelle["home"].coef_) == \
            bundle["models"]["home"]["regressor"]["coef"]
        assert list(modelle["away"].coef_) == \
            bundle["models"]["away"]["regressor"]["coef"]


# ---------------------------------------------------------------------------
# 2. Merkmale
# ---------------------------------------------------------------------------

class TestMerkmale:

    def test_es_sind_genau_16(self):
        assert len(inf.feature_columns()) == 16

    def test_die_reihenfolge_ist_die_des_trainings(self):
        assert inf.feature_columns() == fg.columns_for("team_profile_cl")

    def test_der_aufbau_nutzt_dieselbe_quelle_wie_der_datensatz(self):
        """
        Gegenprobe gegen zwei auseinanderlaufende Fassungen: Was die
        Laufzeit baut, muss der Datensatz genauso bauen.
        """
        heim, gast = _profil(1.0), _profil(2.0)
        gebaut = inf.build_feature_row(heim, gast)

        erwartet = {}
        erwartet.update(ds.profile_feature_values("home", heim,
                                                  ds.PROFILE_RATING_FELDER))
        erwartet.update(ds.profile_feature_values("away", gast,
                                                  ds.PROFILE_RATING_FELDER))
        assert gebaut == erwartet

    def test_alle_16_werden_gefuellt(self):
        zeile = inf.build_feature_row(_profil(), _profil(2.0))
        assert set(zeile) == set(SPALTEN)
        assert all(zeile[s] is not None for s in SPALTEN)

    def test_matches_used_bleibt_draussen(self):
        zeile = inf.build_feature_row(_profil(), _profil())
        assert not [s for s in zeile if s.endswith("matches_used")]
        assert not [s for s in SPALTEN if s.endswith("matches_used")]

    def test_keine_baseline_unter_den_merkmalen(self):
        """
        Die Baseline ist der Offset, kein Merkmal. Steht sie in der
        Matrix, kann das Modell sie beliebig ueberschreiben.
        """
        assert not [s for s in SPALTEN if "baseline" in s]

    def test_keine_ergebnisgroessen_unter_den_merkmalen(self):
        verboten = ("goals", "outcome", "result", "points_total")
        for spalte in SPALTEN:
            assert not spalte.endswith(("home_goals", "away_goals"))
            assert "outcome" not in spalte
        assert "goals_for_per_game" in " ".join(SPALTEN), (
            "Torquoten pro Spiel sind erlaubt - der Test darf sie nicht "
            "versehentlich mit ausschliessen")


# ---------------------------------------------------------------------------
# 3. Die Schattenrechnung
# ---------------------------------------------------------------------------

class TestSchattenrechnung:

    def test_der_regelfall_liefert_eine_vorhersage(self, echtes_bundle):
        e = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               home_profile_source="domestic_pit",
                               away_profile_source="domestic_pit",
                               model_path=echtes_bundle)
        assert e["status"] == "shadow_prediction"
        assert e["fallback_reason"] is None
        assert e["model_id"] == "clm-04b1f413c098f264"

    def test_shadow_ist_baseline_mal_faktor(self, echtes_bundle):
        e = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               model_path=echtes_bundle)
        assert e["shadow_lambda_home"] == pytest.approx(
            1.5 * e["correction_factor_home"], abs=1e-12)
        assert e["shadow_lambda_away"] == pytest.approx(
            1.2 * e["correction_factor_away"], abs=1e-12)

    def test_die_baseline_kommt_unveraendert_zurueck(self, echtes_bundle):
        e = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               model_path=echtes_bundle)
        assert e["baseline_lambda_home"] == 1.5
        assert e["baseline_lambda_away"] == 1.2

    def test_die_eingabedaten_werden_nicht_veraendert(self, echtes_bundle):
        merkmale = _merkmale()
        vorher = dict(merkmale)
        heim, gast = _profil(), _profil(2.0)
        heim_vorher, gast_vorher = dict(heim), dict(gast)

        inf.shadow_lambdas(1.5, 1.2, home_profile=heim, away_profile=gast,
                           features=merkmale, model_path=echtes_bundle)

        assert merkmale == vorher
        assert heim == heim_vorher and gast == gast_vorher

    def test_applied_to_production_ist_immer_false(self, echtes_bundle,
                                                   tmp_path):
        faelle = [
            inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               model_path=echtes_bundle),
            inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               model_path=str(tmp_path / "weg.json")),
            inf.shadow_lambdas(0, 1.2, features=_merkmale(),
                               model_path=echtes_bundle),
            inf.shadow_lambdas(1.5, 1.2, features={},
                               model_path=echtes_bundle),
        ]
        for e in faelle:
            assert e["applied_to_production"] is False
            assert e["shadow_only"] is True

    def test_die_antwort_hat_immer_dieselbe_form(self, echtes_bundle,
                                                 tmp_path):
        gut = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                                 model_path=echtes_bundle)
        schlecht = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                                      model_path=str(tmp_path / "weg.json"))
        assert set(gut) == set(schlecht)

    def test_die_profile_werden_verwendet_wenn_keine_merkmale_kommen(
            self, echtes_bundle):
        e = inf.shadow_lambdas(1.5, 1.2, home_profile=_profil(),
                               away_profile=_profil(1.1),
                               model_path=echtes_bundle)
        assert e["status"] == "shadow_prediction"

    def test_die_qualitaet_wird_mitgefuehrt(self, echtes_bundle):
        e = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               home_profile_source="domestic_pit",
                               away_profile_source="domestic_pit",
                               home_profile_matches=40,
                               away_profile_matches=35,
                               model_path=echtes_bundle)
        q = e["quality"]
        assert q["both_sides_domestic"] is True
        assert q["confidence"] == "exploratory"
        assert q["home_profile_matches"] == 40

    def test_die_c3_teilgruppe_wird_nicht_als_beleg_dargestellt(self,
                                                               echtes_bundle):
        e = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               model_path=echtes_bundle)
        hinweis = e["quality"]["c3_subgroup_note"]
        assert "KEIN Nachweis" in hinweis
        assert "explorative" in hinweis.lower()


# ---------------------------------------------------------------------------
# 4. Fallbacks
# ---------------------------------------------------------------------------

class TestFallbacks:

    @staticmethod
    def _pruefe(e, grund, basis=(1.5, 1.2)):
        assert e["status"] == "fallback"
        assert e["fallback_reason"] == grund
        assert e["fallback_reason"] in inf.FALLBACK_REASONS
        assert e["correction_factor_home"] == 1.0
        assert e["correction_factor_away"] == 1.0
        assert e["shadow_lambda_home"] == basis[0]
        assert e["shadow_lambda_away"] == basis[1]
        assert e["applied_to_production"] is False

    def test_fehlendes_modell(self, tmp_path):
        e = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               model_path=str(tmp_path / "weg.json"))
        self._pruefe(e, inf.REASON_MODEL_MISSING)

    def test_kaputtes_json(self, tmp_path):
        pfad = tmp_path / "kaputt.json"
        pfad.write_text("{ kein json", encoding="utf-8")
        e = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               model_path=str(pfad))
        self._pruefe(e, inf.REASON_MODEL_INVALID)

    def test_falscher_hash(self, kopie):
        _veraendert(kopie, lambda d: d["integrity"].__setitem__(
            "models_sha256", "0" * 64))
        e = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               model_path=kopie)
        self._pruefe(e, inf.REASON_MODEL_INVALID)

    def test_inkompatible_schemafassung(self, kopie):
        _veraendert(kopie, lambda d: d.update(schema_version=99))
        e = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               model_path=kopie)
        self._pruefe(e, inf.REASON_MODEL_INCOMPATIBLE)

    def test_falscher_kandidat(self, kopie):
        _veraendert(kopie, lambda d: d.update(candidate="profile_only"))
        e = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               model_path=kopie)
        self._pruefe(e, inf.REASON_MODEL_INCOMPATIBLE)

    def test_vertauschte_merkmale_im_bundle(self, kopie):
        def tauschen(d):
            d["features"][0], d["features"][1] = (d["features"][1],
                                                  d["features"][0])

        _veraendert(kopie, tauschen)
        e = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               model_path=kopie)
        self._pruefe(e, inf.REASON_MODEL_INCOMPATIBLE)

    def test_fehlendes_merkmal(self, echtes_bundle):
        unvollstaendig = _merkmale()
        unvollstaendig.pop(SPALTEN[0])
        e = inf.shadow_lambdas(1.5, 1.2, features=unvollstaendig,
                               model_path=echtes_bundle)
        self._pruefe(e, inf.REASON_FEATURES_MISSING)

    def test_merkmal_ist_none(self, echtes_bundle):
        merkmale = _merkmale()
        merkmale[SPALTEN[3]] = None
        e = inf.shadow_lambdas(1.5, 1.2, features=merkmale,
                               model_path=echtes_bundle)
        self._pruefe(e, inf.REASON_FEATURES_MISSING)

    @pytest.mark.parametrize("wert", ["text", True, [1.0], {"a": 1}])
    def test_ungueltiger_merkmalswert(self, echtes_bundle, wert):
        merkmale = _merkmale()
        merkmale[SPALTEN[2]] = wert
        e = inf.shadow_lambdas(1.5, 1.2, features=merkmale,
                               model_path=echtes_bundle)
        self._pruefe(e, inf.REASON_FEATURES_INVALID)

    @pytest.mark.parametrize("wert", [float("nan"), float("inf"),
                                      float("-inf")])
    def test_nicht_endlicher_merkmalswert(self, echtes_bundle, wert):
        merkmale = _merkmale()
        merkmale[SPALTEN[5]] = wert
        e = inf.shadow_lambdas(1.5, 1.2, features=merkmale,
                               model_path=echtes_bundle)
        self._pruefe(e, inf.REASON_FEATURES_INVALID)

    @pytest.mark.parametrize("h,a", [
        (0, 1.2), (-1.0, 1.2), (1.5, 0), (1.5, -0.5),
        (float("nan"), 1.2), (float("inf"), 1.2), (None, 1.2),
        ("1.5", 1.2), (True, 1.2),
    ])
    def test_ungueltige_baseline(self, echtes_bundle, h, a):
        e = inf.shadow_lambdas(h, a, features=_merkmale(),
                               model_path=echtes_bundle)
        assert e["status"] == "fallback"
        assert e["fallback_reason"] == inf.REASON_BASELINE_INVALID
        # Die Baseline wird unveraendert durchgereicht - auch ein NaN,
        # das sich nicht mit == vergleichen laesst.
        assert e["shadow_lambda_home"] is h or e["shadow_lambda_home"] == h
        assert e["shadow_lambda_away"] is a or e["shadow_lambda_away"] == a

    def test_neutrales_profil_blockt(self, echtes_bundle):
        e = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               home_profile_source="neutral",
                               away_profile_source="domestic_pit",
                               model_path=echtes_bundle)
        self._pruefe(e, inf.REASON_PROFILE_QUALITY)

    def test_nicht_endliche_vorhersage(self, echtes_bundle, monkeypatch):
        _, modelle = inf.load_model(echtes_bundle)
        monkeypatch.setattr(modelle["home"], "predict",
                            lambda X: [float("nan")])
        e = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               model_path=echtes_bundle)
        self._pruefe(e, inf.REASON_PREDICTION_NON_FINITE)

    def test_nichtpositive_vorhersage(self, echtes_bundle, monkeypatch):
        _, modelle = inf.load_model(echtes_bundle)
        monkeypatch.setattr(modelle["away"], "predict", lambda X: [0.0])
        e = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               model_path=echtes_bundle)
        self._pruefe(e, inf.REASON_PREDICTION_NON_FINITE)

    def test_modellfehler_beim_rechnen(self, echtes_bundle, monkeypatch):
        def platzen(X):
            raise ValueError("Testfall")

        _, modelle = inf.load_model(echtes_bundle)
        monkeypatch.setattr(modelle["home"], "predict", platzen)
        e = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               model_path=echtes_bundle)
        self._pruefe(e, inf.REASON_PREDICTION_ERROR)

    def test_ein_programmierfehler_wird_nicht_verschluckt(self, echtes_bundle,
                                                          monkeypatch):
        """
        Die Grenze des Fangens: Erwartbare Zahlen- und Formfehler
        werden abgefangen, ein echter Programmierfehler bleibt
        sichtbar. Ein pauschales except Exception haette ihn still
        zu einem Fallback gemacht.
        """
        def platzen(X):
            raise AttributeError("das ist ein Programmierfehler")

        _, modelle = inf.load_model(echtes_bundle)
        monkeypatch.setattr(modelle["home"], "predict", platzen)
        with pytest.raises(AttributeError):
            inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               model_path=echtes_bundle)

    def test_alle_gruende_sind_bekannt(self):
        assert len(set(inf.FALLBACK_REASONS)) == len(inf.FALLBACK_REASONS)
        for grund in inf.FALLBACK_REASONS:
            assert grund.islower() and " " not in grund

    def test_kein_absoluter_pfad_in_der_rueckgabe(self, tmp_path):
        import re

        e = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               model_path=str(tmp_path / "weg.json"))
        text = json.dumps(e, ensure_ascii=False, default=str)
        treffer = re.findall(r"[A-Za-z]:[\\/][^\"]*|/home/[^\"]*|/Users/[^\"]*",
                             text)
        assert not treffer, f"Pfade in der Rueckgabe: {treffer[:3]}"

    def test_kein_stacktrace_in_der_rueckgabe(self, tmp_path):
        e = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               model_path=str(tmp_path / "weg.json"))
        text = json.dumps(e, ensure_ascii=False, default=str)
        for verboten in ("Traceback", "File \"", "line "):
            assert verboten not in text


# ---------------------------------------------------------------------------
# 5. Numerische Sicherheit
# ---------------------------------------------------------------------------

class TestNumerik:

    def test_die_clampgrenzen_stammen_aus_dem_modell(self, echtes_bundle):
        e = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               model_path=echtes_bundle)
        c = e["clamps"]
        assert c["correction_min"] == mdl.CORRECTION_MIN
        assert c["correction_max"] == mdl.CORRECTION_MAX
        assert c["lambda_min_allowed"] == mdl.LAMBDA_MIN
        assert c["lambda_max_allowed"] == mdl.LAMBDA_MAX

    def test_ein_extremer_faktor_wird_begrenzt(self, echtes_bundle,
                                               monkeypatch):
        _, modelle = inf.load_model(echtes_bundle)
        monkeypatch.setattr(modelle["home"], "predict", lambda X: [50.0])
        e = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               model_path=echtes_bundle)

        assert e["status"] == "shadow_prediction"
        assert e["clamps"]["clamped_home"] is True
        assert e["clamps"]["raw_factor_home"] == 50.0
        assert e["shadow_lambda_home"] <= mdl.LAMBDA_MAX
        assert e["clamps"]["raw_factor_home"] == 50.0
        assert e["correction_factor_home"] <= mdl.CORRECTION_MAX, (
            "berichtet wird der angewandte Faktor, der rohe steht "
            "unter clamps.raw_factor_home")
        assert e["shadow_lambda_home"] == pytest.approx(
            1.5 * e["correction_factor_home"], abs=1e-12)

    def test_ein_winziger_faktor_wird_begrenzt(self, echtes_bundle,
                                               monkeypatch):
        _, modelle = inf.load_model(echtes_bundle)
        monkeypatch.setattr(modelle["away"], "predict", lambda X: [1e-9])
        e = inf.shadow_lambdas(1.5, 1.2, features=_merkmale(),
                               model_path=echtes_bundle)
        assert e["clamps"]["clamped_away"] is True
        assert e["shadow_lambda_away"] >= mdl.LAMBDA_MIN

    def test_die_ergebnislambdas_sind_endlich_und_positiv(self,
                                                          echtes_bundle):
        for h, a in ((0.06, 0.06), (1.5, 1.2), (5.9, 5.9)):
            e = inf.shadow_lambdas(h, a, features=_merkmale(),
                                   model_path=echtes_bundle)
            import math
            assert math.isfinite(e["shadow_lambda_home"])
            assert math.isfinite(e["shadow_lambda_away"])
            assert e["shadow_lambda_home"] > 0
            assert e["shadow_lambda_away"] > 0

    def test_kein_clamp_bei_echten_daten(self, echtes_bundle):
        """
        Der Regelfall wird an ECHTEN Zeilen geprueft, nicht an
        erfundenen Werten: Nur echte Profile liegen zuverlaessig in der
        Verteilung, auf der das Modell angepasst wurde. Ein
        synthetischer Wert kann die Korrektur voellig zulaessig an die
        Grenze treiben - das waere kein Fehler, nur ein Randfall.
        """
        geklammert = 0
        zeilen = _cl_zeilen()
        for zeile in zeilen:
            e = inf.shadow_lambdas_for_row(zeile, model_path=echtes_bundle)
            assert e["status"] == "shadow_prediction"
            if e["clamps"]["clamped_home"] or e["clamps"]["clamped_away"]:
                geklammert += 1
        assert geklammert == 0, (
            f"{geklammert} von {len(zeilen)} echten CL-Zeilen wurden "
            f"geklammert - erwartet wird keine")


# ---------------------------------------------------------------------------
# 6. Integration gegen die echte C4-Rechnung
# ---------------------------------------------------------------------------

class TestIntegration:

    def test_die_runtime_rechnet_wie_das_c4_modell(self, echtes_bundle):
        """
        Der Nachweis mit echten Werten: dieselben Zeilen einmal als
        Stapel durch model.predict_factors, einmal einzeln durch die
        Laufzeitschicht.
        """
        zeilen = _cl_zeilen()
        _, modelle = ps.load_bundle(echtes_bundle)

        direkt_h = mdl.predict_factors(modelle["home"], zeilen, SPALTEN)
        direkt_a = mdl.predict_factors(modelle["away"], zeilen, SPALTEN)

        for zeile, dh, da in zip(zeilen, direkt_h, direkt_a):
            e = inf.shadow_lambdas_for_row(zeile, model_path=echtes_bundle)
            assert e["status"] == "shadow_prediction", zeile["row_id"]
            assert abs(e["correction_factor_home"] - dh) \
                <= inf.BATCH_EQUIVALENCE_TOLERANCE
            assert abs(e["correction_factor_away"] - da) \
                <= inf.BATCH_EQUIVALENCE_TOLERANCE

    def test_die_baseline_bleibt_ueber_alle_zeilen_unveraendert(self,
                                                                echtes_bundle):
        for zeile in _cl_zeilen():
            vorher = (zeile["baseline_lambda_home"],
                      zeile["baseline_lambda_away"])
            e = inf.shadow_lambdas_for_row(zeile, model_path=echtes_bundle)
            assert (e["baseline_lambda_home"], e["baseline_lambda_away"]) \
                == vorher
            assert (zeile["baseline_lambda_home"],
                    zeile["baseline_lambda_away"]) == vorher

    def test_shadow_ist_ueberall_baseline_mal_faktor(self, echtes_bundle):
        for zeile in _cl_zeilen():
            e = inf.shadow_lambdas_for_row(zeile, model_path=echtes_bundle)
            assert e["shadow_lambda_home"] == pytest.approx(
                zeile["baseline_lambda_home"] * e["correction_factor_home"],
                abs=1e-12)


# ---------------------------------------------------------------------------
# 7. Keine Produktionsanbindung
# ---------------------------------------------------------------------------

class TestKeineProduktion:

    def test_kein_produktivmodul_importiert_die_inference(self):
        """
        Die harte Grenze von C5: Die Schicht existiert, wird aber von
        nichts aufgerufen.
        """
        import pathlib

        wurzel = pathlib.Path(__file__).resolve().parents[1]
        verdaechtig = []
        for pfad in list((wurzel / "src").rglob("*.py")) + [wurzel / "app.py"]:
            if pfad.match("*/ml/*") or pfad.name.startswith("test_"):
                continue
            text = pfad.read_text(encoding="utf-8", errors="ignore")
            if "ml.inference" in text or "from src.ml import inference" in text:
                verdaechtig.append(str(pfad.relative_to(wurzel)))
        assert not verdaechtig, f"Produktivimport gefunden: {verdaechtig}"

    def test_die_vorlagen_kennen_die_schicht_nicht(self):
        import pathlib

        wurzel = pathlib.Path(__file__).resolve().parents[1]
        for ordner in ("templates", "static"):
            for pfad in (wurzel / ordner).rglob("*"):
                if not pfad.is_file() or pfad.suffix not in (".html", ".js"):
                    continue
                text = pfad.read_text(encoding="utf-8", errors="ignore")
                assert "shadow_lambda" not in text
                assert "ml.inference" not in text

    def test_das_bundle_bleibt_unfreigegeben(self, echtes_bundle):
        bundle, _ = inf.load_model(echtes_bundle)
        assert bundle["shadow_only"] is True
        assert bundle["production_approved"] is False
