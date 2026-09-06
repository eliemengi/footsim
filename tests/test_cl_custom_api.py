"""
API- und Integrationstests der individuellen CL-Simulation (C8A).

Der Schwerpunkt liegt auf drei Dingen, die sich still verletzen lassen:
Ein alter Request muss unveraendert antworten, die Liga darf von den
neuen Feldern nichts mitbekommen, und kein Request darf einem
nachfolgenden etwas hinterlassen.
"""

import math
import os

import pytest

from src.ml import inference as inf
from src.predict import cl_custom_factors as ccf
from src.predict import cl_match_sim

SEASON = 2025
BAYERN, AJAX = 5, 678

#: Derselbe Stichtag, den die Simulation ohne kickoff benutzt (V2-C1).
#: Er MUSS uebereinstimmen, sonst prueft der Cachetest einen anderen
#: Eintrag als den, den die Simulation anfasst.
from src.features.pit_profiles import runtime_cutoff  # noqa: E402

CUTOFF = runtime_cutoff()


@pytest.fixture(autouse=True)
def _saubere_umgebung():
    """Kein ML aus der Umgebung - C8A steuert ausschliesslich per Request."""
    alt = dict(os.environ)
    os.environ.pop("FOOTSIM_ML_MODE", None)
    os.environ.pop("FOOTSIM_ML_WEIGHT", None)
    inf.reset_model_cache()
    yield
    os.environ.clear()
    os.environ.update(alt)
    inf.reset_model_cache()


def _sim(options=None, simulations=800, home=BAYERN, away=AJAX):
    return cl_match_sim.simulate_cl_league_phase_match(
        home_team="Heim", away_team="Gast", home_id=home, away_id=away,
        season=SEASON, simulations=simulations, use_seed=True,
        options=options)


def _opts(**kwargs):
    return ccf.parse_options({"approach": "custom", **kwargs})


# ---------------------------------------------------------------------------
# 1. Alter Request
# ---------------------------------------------------------------------------

class TestAlterRequest:

    def test_ohne_optionen_bleibt_alles_beim_alten(self):
        r = _sim(None)
        assert r["ml"]["mode"] == "off"
        assert r["ml"]["applied"] is False
        assert r["ml"]["requested_approach"] is None
        assert r["ml"]["applied_approach"] == "environment_default"

    def test_die_lambdas_entsprechen_der_reinen_baseline(self):
        """
        expected_* ist auf zwei Stellen gerundet, ml.baseline_* auf
        vier - verglichen wird deshalb auf der groeberen Stufe.
        """
        r = _sim(None)
        assert r["expected_home_goals"] == round(
            r["ml"]["baseline_lambda_home"], 2)
        assert r["expected_away_goals"] == round(
            r["ml"]["baseline_lambda_away"], 2)
        assert r["ml"]["final_lambda_home"] == r["ml"]["baseline_lambda_home"]

    def test_neutrale_optionen_rechnen_dieselben_lambdas(self):
        """
        approach=custom mit neutralen Faktoren und Gewicht 0 muss
        dieselbe Torerwartung ergeben wie gar keine Optionen.
        """
        ohne = _sim(None)
        neutral = _sim(_opts())
        assert ohne["expected_home_goals"] == neutral["expected_home_goals"]
        assert ohne["expected_away_goals"] == neutral["expected_away_goals"]

    def test_die_bestehenden_felder_sind_vollstaendig(self):
        r = _sim(None)
        for feld in ("home_team", "away_team", "expected_home_goals",
                     "expected_away_goals", "home_win_probability",
                     "draw_probability", "away_win_probability",
                     "top_scores", "competition", "phase",
                     "home_resolution", "away_resolution", "ml"):
            assert feld in r, feld


# ---------------------------------------------------------------------------
# 2. approach=ml
# ---------------------------------------------------------------------------

class TestAnsatzMl:

    def test_ml_wird_produktiv_angewandt(self):
        r = _sim(ccf.parse_options({"approach": "ml"}))
        assert r["ml"]["requested_approach"] == "ml"
        assert r["ml"]["applied_approach"] == "ml"
        assert r["ml"]["mode"] == "active"
        if r["ml"]["applied"]:
            assert r["ml"]["applied_weight"] == 1.0
            assert r["ml"]["model_id"]

    def test_die_lambdas_weichen_von_der_baseline_ab(self):
        r = _sim(ccf.parse_options({"approach": "ml"}))
        if not r["ml"]["applied"]:
            pytest.skip("ML-Kette nicht verfuegbar")
        assert (r["ml"]["final_lambda_home"]
                != r["ml"]["baseline_lambda_home"])

    def test_die_faktoren_bleiben_neutral(self):
        r = _sim(ccf.parse_options({"approach": "ml"}))
        assert r["ml"]["applied_factors"] == ccf.NEUTRAL_FACTORS


# ---------------------------------------------------------------------------
# 3. approach=custom
# ---------------------------------------------------------------------------

class TestAnsatzCustom:

    def test_ohne_ml_gewicht_bleibt_ml_wirkungslos(self):
        r = _sim(_opts())
        assert r["ml"]["applied_weight"] == 0.0
        assert r["ml"]["final_lambda_home"] == r["ml"]["baseline_lambda_home"]

    def test_das_gewicht_wird_uebernommen(self):
        r = _sim(_opts(ml_weight=1.0))
        if r["ml"]["applied"]:
            assert r["ml"]["applied_weight"] == 1.0

    def test_die_faktoren_stehen_in_der_antwort(self):
        r = _sim(_opts(factors={"attack": 1.2, "home_advantage": 0.8}))
        assert r["ml"]["applied_factors"] == {
            "attack": 1.2, "defence": 1.0, "home_advantage": 0.8}

    def test_offensive_hebt_die_baseline(self):
        basis = _sim(_opts())["ml"]["baseline_lambda_away"]
        hoch = _sim(_opts(factors={"attack": 1.3}))["ml"]["baseline_lambda_away"]
        assert hoch > basis

    def test_defensive_senkt_die_baseline(self):
        basis = _sim(_opts())["ml"]["baseline_lambda_away"]
        stark = _sim(_opts(factors={"defence": 1.3}))["ml"]["baseline_lambda_away"]
        assert stark < basis

    def test_heimvorteil_verschiebt_das_verhaeltnis(self):
        def verhaeltnis(f):
            r = _sim(_opts(factors={"home_advantage": f}))["ml"]
            return r["baseline_lambda_home"] / r["baseline_lambda_away"]

        assert verhaeltnis(1.5) > verhaeltnis(1.0) > verhaeltnis(0.5)

    def test_ml_gewicht_null_und_eins_unterscheiden_sich(self):
        null = _sim(_opts(ml_weight=0.0))
        eins = _sim(_opts(ml_weight=1.0))
        if eins["ml"]["applied"] and eins["ml"]["applied_weight"] == 1.0:
            assert (null["ml"]["final_lambda_home"]
                    != eins["ml"]["final_lambda_home"])


# ---------------------------------------------------------------------------
# 4. Ergebnisqualitaet
# ---------------------------------------------------------------------------

class TestErgebnis:

    FAELLE = [
        None,
        ccf.parse_options({"approach": "ml"}),
        ccf.parse_options({"approach": "custom"}),
        ccf.parse_options({"approach": "custom", "ml_weight": 1.0,
                           "factors": {"attack": 1.3, "defence": 0.7,
                                       "home_advantage": 1.5}}),
        ccf.parse_options({"approach": "custom", "ml_weight": 0.5,
                           "factors": {"attack": 0.7, "defence": 1.3,
                                       "home_advantage": 0.5}}),
    ]

    @pytest.mark.parametrize("options", FAELLE)
    def test_die_wahrscheinlichkeiten_sind_sauber(self, options):
        r = _sim(options)
        werte = [r["home_win_probability"], r["draw_probability"],
                 r["away_win_probability"]]
        for wert in werte:
            assert math.isfinite(wert)
            assert 0.0 <= wert <= 100.0
        assert sum(werte) == pytest.approx(100.0, abs=0.05)

    @pytest.mark.parametrize("options", FAELLE)
    def test_die_lambdas_bleiben_in_den_guardrails(self, options):
        from src.features import team_profile as tp

        r = _sim(options)
        for feld in ("expected_home_goals", "expected_away_goals"):
            assert tp.XG_MIN <= r[feld] <= tp.XG_MAX

    @pytest.mark.parametrize("options", FAELLE)
    def test_keine_negativen_tore(self, options):
        for eintrag in _sim(options)["top_scores"]:
            heim, gast = eintrag["score"].split(":")
            assert int(heim) >= 0 and int(gast) >= 0

    @pytest.mark.parametrize("options", FAELLE)
    def test_der_seed_bleibt_reproduzierbar(self, options):
        erst, zweit = _sim(options), _sim(options)
        assert erst["top_scores"] == zweit["top_scores"]
        assert erst["home_win_probability"] == zweit["home_win_probability"]


# ---------------------------------------------------------------------------
# 5. Kein Zustandsleck
# ---------------------------------------------------------------------------

class TestKeinZustandsleck:

    def test_der_profilcache_wird_nicht_veraendert(self):
        """
        Der wichtigste Test. Ein Request mit Extremfaktoren darf den
        naechsten nicht beeinflussen - die Profile liegen 30 Minuten
        prozessweit im Zwischenspeicher.
        """
        vorher = _sim(None)
        _sim(_opts(factors={"attack": 1.3, "defence": 0.7,
                            "home_advantage": 1.5}))
        nachher = _sim(None)

        assert vorher["expected_home_goals"] == nachher["expected_home_goals"]
        assert vorher["expected_away_goals"] == nachher["expected_away_goals"]

    def test_die_gecachten_profile_bleiben_im_original(self):
        from src.features.strength_provider import get_cl_team_strengths
        from src.utils import cache

        strengths = cache.cached_call(
            key=f"cl_strengths:{SEASON}:{CUTOFF}", ttl_seconds=60 * 30,
            loader=lambda: get_cl_team_strengths(season=SEASON, cutoff=CUTOFF))
        vorher = dict(strengths["domestic_by_id"][BAYERN])
        schnitt_vorher = dict(strengths["league_avg"])

        _sim(_opts(factors={"attack": 1.3, "defence": 0.7,
                            "home_advantage": 1.5}))

        assert strengths["domestic_by_id"][BAYERN] == vorher
        assert strengths["league_avg"] == schnitt_vorher

    def test_aufeinanderfolgende_requests_beeinflussen_sich_nicht(self):
        folge = [None,
                 ccf.parse_options({"approach": "ml"}),
                 _opts(factors={"attack": 1.3}),
                 _opts(ml_weight=1.0),
                 None]
        ergebnisse = [_sim(o) for o in folge]
        assert (ergebnisse[0]["expected_home_goals"]
                == ergebnisse[-1]["expected_home_goals"])

    def test_os_environ_bleibt_unberuehrt(self):
        vorher = dict(os.environ)
        _sim(ccf.parse_options({"approach": "ml"}))
        _sim(_opts(ml_weight=1.0))
        assert dict(os.environ) == vorher

    def test_parallele_requests_bleiben_getrennt(self):
        """
        Zwei Konfigurationen gleichzeitig - jede muss ihr eigenes
        Ergebnis behalten.
        """
        import threading

        ergebnisse = {}

        def lauf(name, options):
            ergebnisse[name] = _sim(options, simulations=300)

        faeden = [
            threading.Thread(target=lauf, args=("neutral", _opts())),
            threading.Thread(target=lauf, args=("stark",
                                                _opts(factors={"attack": 1.3}))),
        ]
        for f in faeden:
            f.start()
        for f in faeden:
            f.join()

        assert (ergebnisse["stark"]["ml"]["baseline_lambda_away"]
                > ergebnisse["neutral"]["ml"]["baseline_lambda_away"])


# ---------------------------------------------------------------------------
# 6. Fallbacks
# ---------------------------------------------------------------------------

class TestFallbacks:

    def test_fehlendes_modell_faellt_auf_die_baseline(self, monkeypatch):
        monkeypatch.setattr(inf, "DEFAULT_MODEL_PATH",
                            os.path.join("data", "ml", "models", "weg.json"))
        inf.reset_model_cache()
        r = _sim(ccf.parse_options({"approach": "ml"}))
        assert r["ml"]["applied"] is False
        assert r["ml"]["fallback_reason"] == "model_missing"
        assert r["ml"]["final_lambda_home"] == r["ml"]["baseline_lambda_home"]
        assert sum([r["home_win_probability"], r["draw_probability"],
                    r["away_win_probability"]]) == pytest.approx(100.0,
                                                                 abs=0.05)

    def test_beschaedigtes_modell_faellt_auf_die_baseline(self, monkeypatch,
                                                          tmp_path):
        kaputt = tmp_path / "kaputt.json"
        kaputt.write_text("{ kein json", encoding="utf-8")
        monkeypatch.setattr(inf, "DEFAULT_MODEL_PATH", str(kaputt))
        inf.reset_model_cache()
        r = _sim(ccf.parse_options({"approach": "ml"}))
        assert r["ml"]["fallback_reason"] == "model_invalid"
        assert r["ml"]["applied"] is False

    def test_unbekanntes_team_bekommt_ein_neutrales_profil(self):
        r = _sim(ccf.parse_options({"approach": "ml"}),
                 home=999999, away=999998)
        assert r["home_resolution"] == "neutral"
        assert r["ml"]["applied"] is False
        assert r["ml"]["fallback_reason"] == "profile_quality_insufficient"

    def test_die_faktoren_wirken_auch_im_fallback(self):
        """
        Ein ML-Ausfall darf die individuellen Faktoren nicht mit
        verschlucken - sie gehoeren zur Baseline, nicht zum Modell.
        """
        neutral = _sim(_opts(), home=999999, away=999998)
        stark = _sim(_opts(factors={"attack": 1.3}), home=999999, away=999998)
        assert (stark["ml"]["baseline_lambda_home"]
                > neutral["ml"]["baseline_lambda_home"])


# ---------------------------------------------------------------------------
# 7. Isolation
# ---------------------------------------------------------------------------

class TestIsolation:

    def test_die_route_weist_optionen_ausserhalb_der_cl_ab(self):
        from tests.conftest import mit_csrf

        import app as app_module

        app_module.app.config["TESTING"] = True
        client = mit_csrf(app_module.app.test_client())
        antwort = client.post("/api/simulate", json={
            "competition": "bl1", "home_team": "A", "away_team": "B",
            "home_id": 5, "away_id": 4, "approach": "custom",
            "factors": {"attack": 1.3}})
        assert antwort.status_code == 400
        assert "Champions" in antwort.get_json()["error"]

    def test_die_ligasimulation_kennt_die_faktoren_nicht(self):
        import pathlib

        wurzel = pathlib.Path(__file__).resolve().parents[1]
        for name in ("league_match_sim.py", "season_sim.py",
                     "simulate_scores.py"):
            text = (wurzel / "src" / "predict" / name).read_text(
                encoding="utf-8", errors="ignore")
            assert "cl_custom_factors" not in text, name

    def test_die_cl_saisonsimulation_bleibt_unveraendert(self):
        import pathlib

        text = (pathlib.Path(__file__).resolve().parents[1] / "src"
                / "predict" / "cl_season_sim.py").read_text(encoding="utf-8")
        assert "cl_custom_factors" not in text
        assert "approach" not in text

    def test_der_saisonendpunkt_kennt_keine_neuen_parameter(self):
        import inspect

        import app as app_module

        quelltext = inspect.getsource(app_module.api_cl_season_sim)
        for feld in ("approach", "factors", "ml_weight"):
            assert feld not in quelltext

    def test_use_seed_bleibt_erhalten(self):
        """C8A entfernt die Funktion nicht - das ist C8B und nur sichtbar."""
        import inspect

        quelltext = inspect.getsource(
            cl_match_sim.simulate_cl_league_phase_match)
        assert "use_seed" in quelltext
        assert "random.Random(42 if use_seed else None)" in quelltext


# ---------------------------------------------------------------------------
# 8. HTTP-Vertrag
# ---------------------------------------------------------------------------

class TestHttp:

    @pytest.fixture
    def client(self):
        """
        Echter Testclient MIT gueltigem CSRF-Token - nach der im
        Projekt etablierten Konvention (tests.conftest.mit_csrf).
        WTF_CSRF_ENABLED wird ausdruecklich nicht abgeschaltet: Das
        hat schon einmal verdeckt, ob die Route ueberhaupt erreichbar
        ist.
        """
        from tests.conftest import mit_csrf

        import app as app_module

        app_module.app.config["TESTING"] = True
        with app_module.app.test_client() as c:
            yield mit_csrf(c)

    @staticmethod
    def _cl(**extra):
        return {"competition": "cl", "home_team": "Heim", "away_team": "Gast",
                "home_id": BAYERN, "away_id": AJAX, "season": SEASON,
                "simulations": 300, "use_seed": True, **extra}

    def test_alter_cl_request_funktioniert(self, client):
        antwort = client.post("/api/simulate", json=self._cl())
        assert antwort.status_code == 200
        assert antwort.get_json()["ml"]["mode"] == "off"

    def test_approach_ml_wird_angenommen(self, client):
        antwort = client.post("/api/simulate", json=self._cl(approach="ml"))
        assert antwort.status_code == 200
        assert antwort.get_json()["ml"]["requested_approach"] == "ml"

    def test_approach_custom_wird_angenommen(self, client):
        antwort = client.post("/api/simulate", json=self._cl(
            approach="custom", ml_weight=0.5,
            factors={"attack": 1.1, "defence": 0.9}))
        assert antwort.status_code == 200
        daten = antwort.get_json()
        assert daten["ml"]["applied_factors"]["attack"] == 1.1

    @pytest.mark.parametrize("extra,muster", [
        ({"approach": "baseline"}, "Ansatz"),
        ({"approach": "custom", "factors": {"offense": 1.2}}, "Unbekannte"),
        ({"approach": "custom", "factors": "x"}, "Objekt"),
        ({"approach": "custom", "factors": {"attack": "1.2"}}, "Zahl"),
        ({"approach": "custom", "factors": {"attack": 1.4}}, "zwischen"),
        ({"approach": "custom", "ml_weight": 50}, "zwischen"),
        ({"approach": "ml", "ml_weight": 0.5}, "nicht zulaessig"),
        ({"factors": {"attack": 1.1}}, "approach"),
    ])
    def test_ungueltige_eingaben_ergeben_400(self, client, extra, muster):
        antwort = client.post("/api/simulate", json=self._cl(**extra))
        assert antwort.status_code == 400
        assert muster in antwort.get_json()["error"]

    def test_die_fehlermeldung_verraet_nichts_internes(self, client):
        antwort = client.post("/api/simulate",
                              json=self._cl(approach="unsinn"))
        text = antwort.get_json()["error"]
        for verboten in ("C:\\", "/home/", "Traceback", ".json", "coef"):
            assert verboten not in text

    def test_die_antwort_verraet_keine_modellinterna(self, client):
        import json as _json

        antwort = client.post("/api/simulate", json=self._cl(approach="ml"))
        text = _json.dumps(antwort.get_json())
        for verboten in ("coef", "intercept", "statistics", "scaler",
                         "C:\\", "/home/", "Traceback", "sha256"):
            assert verboten not in text


# ---------------------------------------------------------------------------
# Freigabestufe am Endpunkt (C0B)
# ---------------------------------------------------------------------------

class TestFreigabestufeAmEndpunkt:
    """
    Die Produktentscheidung, an der Aussenkante geprueft: ML-Prognose
    bleibt der Standard der Oberflaeche und wirkt wirklich - aber nur,
    solange die Freigabestufe des Modells das deckt.
    """

    @pytest.fixture
    def client(self):
        from tests.conftest import mit_csrf

        import app as app_module

        app_module.app.config["TESTING"] = True
        with app_module.app.test_client() as c:
            yield mit_csrf(c)

    @staticmethod
    def _cl(**extra):
        return {"competition": "cl", "home_team": "Heim", "away_team": "Gast",
                "home_id": BAYERN, "away_id": AJAX, "season": SEASON,
                "simulations": 200, "use_seed": True, **extra}

    def test_das_ausgelieferte_modell_ist_experimentell(self):
        from src.ml import inference as inf
        from src.ml import persist as ps

        bundle, _ = inf.load_model()
        assert bundle["release_stage"] == ps.STAGE_EXPERIMENTAL

    def test_die_ui_vorauswahl_wirkt_wirklich(self, client):
        """
        approach='ml' ist der Standard der Champions-League-Oberflaeche.
        Er muss das Modell tatsaechlich anwenden - sonst waere die
        sichtbare Auswahl eine Behauptung.
        """
        daten = client.post("/api/simulate",
                            json=self._cl(approach="ml")).get_json()
        assert daten["ml"]["applied"] is True
        assert daten["ml"]["applied_weight"] == 1.0
        assert daten["ml"]["fallback_reason"] is None
        assert daten["ml"]["model_id"]

    def test_ein_schattenmodell_veraendert_nichts(self, client, tmp_path,
                                                  monkeypatch):
        """
        Der Kern des C0B-Fixes. Vorher rechnete ein als 'nur Schatten'
        gekennzeichnetes Modell mit vollem Gewicht in die Prognose.
        """
        import json
        import shutil

        from src.ml import inference as inf
        from src.ml import persist as ps

        ziel = str(tmp_path / "schatten.json")
        shutil.copyfile(inf.DEFAULT_MODEL_PATH, ziel)
        with open(ziel, encoding="utf-8") as datei:
            bundle = json.load(datei)
        bundle["release_stage"] = ps.STAGE_SHADOW
        bundle["model_id"] = ps.build_model_id(
            bundle["candidate"], bundle["features"], bundle["alpha"],
            bundle["training"]["seasons"],
            bundle["provenance"]["dataset_fingerprint"]["sha256"],
            bundle["integrity"]["models_sha256"],
            bundle["provenance"]["evaluation"]["evaluation_sha256"],
            ps.STAGE_SHADOW)
        with open(ziel, "w", encoding="utf-8") as datei:
            json.dump(bundle, datei)

        monkeypatch.setattr(inf, "DEFAULT_MODEL_PATH", ziel)
        inf.reset_model_cache()
        try:
            daten = client.post("/api/simulate",
                                json=self._cl(approach="ml")).get_json()
        finally:
            inf.reset_model_cache()

        ml = daten["ml"]
        assert ml["applied"] is False
        assert ml["fallback_reason"] == "model_stage_not_active"
        assert ml["final_lambda_home"] == ml["baseline_lambda_home"]
        assert ml["final_lambda_away"] == ml["baseline_lambda_away"]
        # Und die Simulation liefert trotzdem ein vollstaendiges Ergebnis.
        summe = (daten["home_win_probability"] + daten["draw_probability"]
                 + daten["away_win_probability"])
        assert abs(summe - 100.0) < 0.05

    def test_ein_defektes_modell_fuehrt_auf_v0(self, client, tmp_path,
                                               monkeypatch):
        from src.ml import inference as inf

        kaputt = tmp_path / "kaputt.json"
        kaputt.write_text("{ das ist kein JSON", encoding="utf-8")
        monkeypatch.setattr(inf, "DEFAULT_MODEL_PATH", str(kaputt))
        inf.reset_model_cache()
        try:
            daten = client.post("/api/simulate",
                                json=self._cl(approach="ml")).get_json()
        finally:
            inf.reset_model_cache()

        ml = daten["ml"]
        assert ml["applied"] is False
        assert ml["fallback_reason"] == "model_invalid"
        assert ml["final_lambda_home"] == ml["baseline_lambda_home"]

    def test_die_antwort_verraet_keine_modellinterna(self, client):
        import json as _json

        text = _json.dumps(client.post("/api/simulate",
                                       json=self._cl(approach="ml")).get_json())
        for verboten in ("coef", "intercept", "scaler", "sha256",
                         "release_stage", "evaluation", ".json"):
            assert verboten not in text, verboten
