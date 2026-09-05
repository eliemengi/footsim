"""
Tests fuer die kontrollierte Anbindung der ML-Kette an die CL-Simulation.

Diese Schicht ist die Grenze zur Produktion. Sie hat zwei Zusagen, die
nicht verhandelbar sind: Im Standardmodus rechnet FootSim bitgleich wie
zuvor, und ein Fehler im ML-Pfad darf niemals eine Prognose
verhindern.

Beides laesst sich verletzen, ohne dass eine Zahl auffaellig aussieht.
Deshalb wird jeder Fehlerfall provoziert und jeder Modus gegen die
unveraenderte Baseline geprueft.
"""

import json
import math
import os

import pytest

from src.ml import runtime as rt

BASIS = (1.5, 1.2)


def _profil(basis=1.0):
    from src.ml import dataset as ds

    return {feld: basis + 0.01 * i
            for i, feld in enumerate(ds.PROFILE_RATING_FELDER)}


def _aufloesen(basis=BASIS, environ=None, **kwargs):
    kwargs.setdefault("home_profile", _profil(1.0))
    kwargs.setdefault("away_profile", _profil(1.05))
    kwargs.setdefault("home_resolution", "domestic_history")
    kwargs.setdefault("away_resolution", "domestic_history")
    return rt.resolve_simulation_lambdas(basis[0], basis[1],
                                         environ=environ or {}, **kwargs)


# ---------------------------------------------------------------------------
# 1. Konfiguration
# ---------------------------------------------------------------------------

class TestKonfiguration:

    def test_der_standard_ist_off(self):
        assert rt.DEFAULT_MODE == "off"
        assert rt.current_config({})["mode"] == "off"

    def test_ohne_umgebung_bleibt_es_off(self):
        assert rt.current_config({"IRGENDWAS": "x"})["mode"] == "off"

    @pytest.mark.parametrize("wert,erwartet", [
        ("off", "off"), ("shadow", "shadow"), ("active", "active"),
        ("SHADOW", "shadow"), ("  active  ", "active"),
    ])
    def test_gueltige_modi(self, wert, erwartet):
        modus, grund = rt.parse_mode(wert)
        assert modus == erwartet and grund is None

    @pytest.mark.parametrize("wert", ["an", "on", "true", "1", "aktiv",
                                      "ACTIVE!", "shadow-mode", "x"])
    def test_ungueltige_modi_fuehren_auf_off(self, wert):
        """Wer sich vertippt, bekommt die Baseline - nicht das Modell."""
        modus, grund = rt.parse_mode(wert)
        assert modus == "off"
        assert grund == rt.REASON_MODE_INVALID

    @pytest.mark.parametrize("wert", [None, "", "   "])
    def test_fehlender_modus_ist_off_ohne_beschwerde(self, wert):
        assert rt.parse_mode(wert) == ("off", None)

    @pytest.mark.parametrize("wert,erwartet", [
        ("0.0", 0.0), ("0.5", 0.5), ("1.0", 1.0), ("1", 1.0),
        (0.25, 0.25), (0, 0.0), (1, 1.0), (" 0.75 ", 0.75),
    ])
    def test_gueltige_gewichte(self, wert, erwartet):
        gewicht, grund = rt.parse_weight(wert)
        assert gewicht == erwartet and grund is None

    @pytest.mark.parametrize("wert", [
        "50", "100", 50, 100, -0.1, 1.1, 2, "abc", "0,5", True, False,
        float("nan"), float("inf"), [0.5], {"w": 1},
    ])
    def test_ungueltige_gewichte(self, wert):
        gewicht, grund = rt.parse_weight(wert)
        assert gewicht == 0.0
        assert grund == rt.REASON_WEIGHT_INVALID

    @pytest.mark.parametrize("wert", [None, "", "  "])
    def test_fehlendes_gewicht(self, wert):
        assert rt.parse_weight(wert) == (0.0, rt.REASON_WEIGHT_MISSING)

    def test_50_wird_niemals_zu_0_5(self):
        """Der Tippfehler, der sonst still die volle Korrektur einschaltet."""
        assert rt.parse_weight("50")[0] != 0.5
        assert rt.parse_weight("50")[0] == 0.0
        assert rt.parse_weight(50)[1] == rt.REASON_WEIGHT_INVALID

    def test_in_off_wird_das_gewicht_nicht_geprueft(self):
        """Der Standardweg beruehrt die ML-Module nicht - auch nicht blend."""
        c = rt.current_config({"FOOTSIM_ML_WEIGHT": "voelliger unsinn"})
        assert c["mode"] == "off"
        assert c["weight"] == 0.0
        assert c["weight_reason"] is None
        assert c["raw_weight"] == "voelliger unsinn"

    def test_die_variablennamen_stehen_in_env_example(self):
        import pathlib

        text = (pathlib.Path(__file__).resolve().parents[1]
                / ".env.example").read_text(encoding="utf-8")
        assert rt.ENV_MODE in text
        assert rt.ENV_WEIGHT in text
        assert "INCONCLUSIVE" in text

    def test_env_example_enthaelt_keine_aktivierung(self):
        import pathlib

        text = (pathlib.Path(__file__).resolve().parents[1]
                / ".env.example").read_text(encoding="utf-8")
        assert f"{rt.ENV_MODE}=off" in text
        assert f"{rt.ENV_MODE}=active" not in text


# ---------------------------------------------------------------------------
# 2. Modus off
# ---------------------------------------------------------------------------

class TestModusOff:

    def test_die_baseline_kommt_unveraendert_zurueck(self):
        e = _aufloesen()
        assert (e["lambda_home"], e["lambda_away"]) == BASIS
        assert e["mode"] == "off"
        assert e["fallback_reason"] == rt.REASON_MODE_OFF

    def test_ml_wird_nicht_produktiv(self):
        assert _aufloesen()["ml_applied_to_production"] is False

    def test_es_wird_kein_ml_modul_geladen(self):
        """
        Die harte Zusage des Standardwegs. Ein eigener Prozess, damit
        vorher geladene Module das Ergebnis nicht verfaelschen.
        """
        import subprocess
        import sys

        code = (
            "import sys;"
            "from src.ml import runtime as rt;"
            "rt.resolve_simulation_lambdas(1.5,1.2,{'a':1},{'a':1},"
            "'domestic_history','domestic_history',environ={});"
            "print(','.join(m for m in ('src.ml.inference','src.ml.blend',"
            "'src.ml.persist','numpy','sklearn') if m in sys.modules))"
        )
        ergebnis = subprocess.run([sys.executable, "-c", code],
                                  capture_output=True, text=True,
                                  cwd=os.path.dirname(os.path.dirname(
                                      os.path.abspath(__file__))))
        assert ergebnis.returncode == 0, ergebnis.stderr
        assert ergebnis.stdout.strip() == "", (
            f"in off wurden Module geladen: {ergebnis.stdout.strip()}")

    def test_ein_unbekannter_modus_landet_auf_off(self):
        e = _aufloesen(environ={"FOOTSIM_ML_MODE": "aktiv"})
        assert e["mode"] == "off"
        assert e["fallback_reason"] == rt.REASON_MODE_INVALID
        assert (e["lambda_home"], e["lambda_away"]) == BASIS

    def test_ein_gewicht_ohne_modus_bleibt_wirkungslos(self):
        e = _aufloesen(environ={"FOOTSIM_ML_WEIGHT": "1.0"})
        assert (e["lambda_home"], e["lambda_away"]) == BASIS
        assert e["ml_applied_to_production"] is False


# ---------------------------------------------------------------------------
# 3. Modus shadow
# ---------------------------------------------------------------------------

class TestModusShadow:

    ENV = {"FOOTSIM_ML_MODE": "shadow", "FOOTSIM_ML_WEIGHT": "1.0"}

    def test_die_simulation_nutzt_weiterhin_die_baseline(self):
        e = _aufloesen(environ=self.ENV)
        assert (e["lambda_home"], e["lambda_away"]) == BASIS
        assert e["ml_applied_to_production"] is False
        assert e["fallback_reason"] == rt.REASON_SHADOW_ONLY

    def test_die_diagnose_wird_mitgeliefert(self):
        e = _aufloesen(environ=self.ENV)
        assert e["diagnostics"] is not None
        assert "shadow_status" in e["diagnostics"]
        assert "weighted_lambda_home" in e["diagnostics"]

    def test_die_diagnose_traegt_keine_nutzerdaten(self):
        e = _aufloesen(environ=self.ENV)
        text = json.dumps(e["diagnostics"], default=str)
        for verboten in ("@", "token", "password", "session", "cookie",
                         "C:\\", "/home/", "/Users/"):
            assert verboten not in text

    def test_auch_mit_gewicht_null_bleibt_es_die_baseline(self):
        e = _aufloesen(environ={"FOOTSIM_ML_MODE": "shadow",
                                "FOOTSIM_ML_WEIGHT": "0.0"})
        assert (e["lambda_home"], e["lambda_away"]) == BASIS

    def test_ein_ungueltiges_gewicht_stoppt_shadow_nicht(self):
        """In shadow wird ohnehin nichts angewandt - die Diagnose laeuft."""
        e = _aufloesen(environ={"FOOTSIM_ML_MODE": "shadow",
                                "FOOTSIM_ML_WEIGHT": "50"})
        assert (e["lambda_home"], e["lambda_away"]) == BASIS
        assert e["ml_applied_to_production"] is False


# ---------------------------------------------------------------------------
# 4. Modus active
# ---------------------------------------------------------------------------

class TestModusActive:

    @staticmethod
    def _env(gewicht):
        return {"FOOTSIM_ML_MODE": "active", "FOOTSIM_ML_WEIGHT": str(gewicht)}

    def test_gewicht_null_ist_exakt_die_baseline(self):
        e = _aufloesen(environ=self._env(0.0))
        assert e["lambda_home"] == BASIS[0]
        assert e["lambda_away"] == BASIS[1]
        assert e["applied_weight"] == 0.0

    def test_gewicht_eins_veraendert_die_lambdas(self):
        e = _aufloesen(environ=self._env(1.0))
        if e["ml_applied_to_production"]:
            assert (e["lambda_home"], e["lambda_away"]) != BASIS
            assert e["applied_weight"] == 1.0

    def test_zwischengewichte_liegen_zwischen_den_endpunkten(self):
        null = _aufloesen(environ=self._env(0.0))
        eins = _aufloesen(environ=self._env(1.0))
        if not eins["ml_applied_to_production"]:
            pytest.skip("ML-Kette nicht verfuegbar")

        for gewicht in (0.25, 0.5, 0.75):
            e = _aufloesen(environ=self._env(gewicht))
            for seite in ("home", "away"):
                lo = min(null[f"lambda_{seite}"], eins[f"lambda_{seite}"])
                hi = max(null[f"lambda_{seite}"], eins[f"lambda_{seite}"])
                assert lo - 1e-12 <= e[f"lambda_{seite}"] <= hi + 1e-12

    def test_die_lambdas_sind_endlich_und_positiv(self):
        for gewicht in (0.0, 0.25, 0.5, 0.75, 1.0):
            e = _aufloesen(environ=self._env(gewicht))
            assert math.isfinite(e["lambda_home"]) and e["lambda_home"] > 0
            assert math.isfinite(e["lambda_away"]) and e["lambda_away"] > 0

    @pytest.mark.parametrize("gewicht", ["50", "100", "-1", "abc", "1.5"])
    def test_ein_ungueltiges_gewicht_fuehrt_auf_die_baseline(self, gewicht):
        e = _aufloesen(environ=self._env(gewicht))
        assert (e["lambda_home"], e["lambda_away"]) == BASIS
        assert e["ml_applied_to_production"] is False
        assert e["fallback_reason"] == rt.REASON_WEIGHT_INVALID

    def test_ein_fehlendes_gewicht_fuehrt_auf_die_baseline(self):
        e = _aufloesen(environ={"FOOTSIM_ML_MODE": "active"})
        assert (e["lambda_home"], e["lambda_away"]) == BASIS
        assert e["fallback_reason"] == rt.REASON_WEIGHT_MISSING


# ---------------------------------------------------------------------------
# 5. Fallbacks
# ---------------------------------------------------------------------------

class TestFallbacks:

    ENV = {"FOOTSIM_ML_MODE": "active", "FOOTSIM_ML_WEIGHT": "1.0"}

    @pytest.mark.parametrize("basis", [(0, 1.2), (-1.0, 1.2), (1.5, 0),
                                       (float("nan"), 1.2),
                                       (float("inf"), 1.2), (None, 1.2)])
    def test_ungueltige_baseline(self, basis):
        e = _aufloesen(basis=basis, environ=self.ENV)
        assert e["fallback_reason"] == rt.REASON_BASELINE_INVALID
        assert e["usable"] is False
        assert e["ml_applied_to_production"] is False

    @pytest.mark.parametrize("fehlt", ["home_profile", "away_profile"])
    def test_fehlendes_teamprofil(self, fehlt):
        e = _aufloesen(environ=self.ENV, **{fehlt: None})
        assert e["fallback_reason"] == rt.REASON_PROFILE_MISSING
        assert (e["lambda_home"], e["lambda_away"]) == BASIS

    def test_neutrales_profil_blockt(self):
        """C5 lehnt eine Korrektur ohne Profil ab - das muss durchschlagen."""
        e = _aufloesen(environ=self.ENV, home_resolution="neutral")
        assert e["ml_applied_to_production"] is False
        assert (e["lambda_home"], e["lambda_away"]) == BASIS
        assert e["fallback_reason"] == "profile_quality_insufficient"

    def test_fehlendes_modell(self, monkeypatch):
        from src.ml import inference as inf

        monkeypatch.setattr(inf, "DEFAULT_MODEL_PATH",
                            os.path.join("data", "ml", "models", "weg.json"))
        inf.reset_model_cache()
        try:
            e = _aufloesen(environ=self.ENV)
            assert e["ml_applied_to_production"] is False
            assert (e["lambda_home"], e["lambda_away"]) == BASIS
            assert e["fallback_reason"] == "model_missing"
        finally:
            inf.reset_model_cache()

    def test_beschaedigtes_modell(self, monkeypatch, tmp_path):
        from src.ml import inference as inf

        kaputt = tmp_path / "kaputt.json"
        kaputt.write_text("{ kein json", encoding="utf-8")
        monkeypatch.setattr(inf, "DEFAULT_MODEL_PATH", str(kaputt))
        inf.reset_model_cache()
        try:
            e = _aufloesen(environ=self.ENV)
            assert e["ml_applied_to_production"] is False
            assert (e["lambda_home"], e["lambda_away"]) == BASIS
            assert e["fallback_reason"] == "model_invalid"
        finally:
            inf.reset_model_cache()

    def test_ein_unerwarteter_fehler_stoppt_die_simulation_nicht(self,
                                                                 monkeypatch):
        """
        Die letzte Sicherheitsgrenze. Sie ist ausdruecklich breit -
        dies ist die Grenze zur produktiven Simulation, und ein
        Programmierfehler in der ML-Kette darf einem Nutzer nicht die
        Prognose zerstoeren. Sie wird geloggt, nicht verschwiegen.
        """
        from src.ml import inference as inf

        def platzen(*args, **kwargs):
            raise RuntimeError("unerwartet")

        monkeypatch.setattr(inf, "shadow_lambdas", platzen)
        e = _aufloesen(environ=self.ENV)
        assert e["fallback_reason"] == rt.REASON_UNEXPECTED_ERROR
        assert (e["lambda_home"], e["lambda_away"]) == BASIS
        assert e["ml_applied_to_production"] is False

    def test_alle_gruende_sind_stabile_bezeichner(self):
        for grund in rt.RUNTIME_REASONS:
            assert grund.islower() and " " not in grund
        assert len(set(rt.RUNTIME_REASONS)) == len(rt.RUNTIME_REASONS)

    def test_keine_pfade_in_der_rueckgabe(self):
        import re

        e = _aufloesen(environ=self.ENV)
        text = json.dumps(e, default=str)
        treffer = re.findall(r"[A-Za-z]:[\\/][^\"]*|/home/[^\"]*|/Users/[^\"]*",
                             text)
        assert not treffer, f"Pfade in der Rueckgabe: {treffer[:3]}"


# ---------------------------------------------------------------------------
# 6. Vertrag und Seiteneffekte
# ---------------------------------------------------------------------------

class TestVertrag:

    FELDER = ("lambda_home", "lambda_away", "baseline_lambda_home",
              "baseline_lambda_away", "mode", "requested_weight",
              "applied_weight", "ml_status", "fallback_reason", "model_id",
              "ml_applied_to_production", "usable", "diagnostics")

    @pytest.mark.parametrize("env", [
        {}, {"FOOTSIM_ML_MODE": "shadow"},
        {"FOOTSIM_ML_MODE": "active", "FOOTSIM_ML_WEIGHT": "0.5"},
        {"FOOTSIM_ML_MODE": "quatsch"},
    ])
    def test_die_form_ist_in_jedem_modus_dieselbe(self, env):
        e = _aufloesen(environ=env)
        assert set(e) == set(self.FELDER)

    def test_die_baseline_steht_immer_in_der_antwort(self):
        for env in ({}, {"FOOTSIM_ML_MODE": "shadow"},
                    {"FOOTSIM_ML_MODE": "active", "FOOTSIM_ML_WEIGHT": "1.0"}):
            e = _aufloesen(environ=env)
            assert (e["baseline_lambda_home"],
                    e["baseline_lambda_away"]) == BASIS

    def test_die_eingabeprofile_werden_nicht_veraendert(self):
        heim, gast = _profil(1.0), _profil(1.05)
        vorher = (dict(heim), dict(gast))
        rt.resolve_simulation_lambdas(
            1.5, 1.2, home_profile=heim, away_profile=gast,
            home_resolution="domestic_history",
            away_resolution="domestic_history",
            environ={"FOOTSIM_ML_MODE": "active", "FOOTSIM_ML_WEIGHT": "1.0"})
        assert (heim, gast) == vorher

    def test_dieselbe_eingabe_ergibt_dasselbe_ergebnis(self):
        env = {"FOOTSIM_ML_MODE": "active", "FOOTSIM_ML_WEIGHT": "0.5"}
        assert _aufloesen(environ=env) == _aufloesen(environ=env)


# ---------------------------------------------------------------------------
# 7. Wirkung auf die echte Simulation
# ---------------------------------------------------------------------------

class TestSimulation:

    @staticmethod
    def _simulate(environ, seed=True, simulations=2000):
        from src.predict import cl_match_sim

        alt = dict(os.environ)
        os.environ.pop("FOOTSIM_ML_MODE", None)
        os.environ.pop("FOOTSIM_ML_WEIGHT", None)
        os.environ.update(environ)
        try:
            return cl_match_sim.simulate_cl_league_phase_match(
                home_team="Bayern", away_team="Ajax", home_id=5, away_id=678,
                season=2025, simulations=simulations, use_seed=seed)
        finally:
            os.environ.clear()
            os.environ.update(alt)

    def test_off_liefert_ein_vollstaendiges_ergebnis(self):
        r = self._simulate({})
        assert r["competition"] == "Champions League"
        assert r["ml"]["mode"] == "off"
        assert r["ml"]["applied"] is False

    def test_die_wahrscheinlichkeiten_sind_sauber(self):
        for env in ({}, {"FOOTSIM_ML_MODE": "shadow"},
                    {"FOOTSIM_ML_MODE": "active", "FOOTSIM_ML_WEIGHT": "1.0"}):
            r = self._simulate(env)
            werte = [r["home_win_probability"], r["draw_probability"],
                     r["away_win_probability"]]
            for wert in werte:
                assert math.isfinite(wert)
                assert 0.0 <= wert <= 100.0
            assert sum(werte) == pytest.approx(100.0, abs=0.05)

    def test_off_und_shadow_liefern_dasselbe_ergebnis(self):
        """Shadow darf das Produktionsergebnis nicht beruehren."""
        ohne = self._simulate({})
        schatten = self._simulate({"FOOTSIM_ML_MODE": "shadow",
                                   "FOOTSIM_ML_WEIGHT": "1.0"})
        for feld in ("expected_home_goals", "expected_away_goals",
                     "home_win_probability", "draw_probability",
                     "away_win_probability", "top_scores"):
            assert ohne[feld] == schatten[feld], feld

    def test_active_mit_gewicht_null_gleicht_off(self):
        ohne = self._simulate({})
        null = self._simulate({"FOOTSIM_ML_MODE": "active",
                               "FOOTSIM_ML_WEIGHT": "0.0"})
        assert ohne["expected_home_goals"] == null["expected_home_goals"]
        assert ohne["expected_away_goals"] == null["expected_away_goals"]
        assert ohne["home_win_probability"] == null["home_win_probability"]

    def test_der_seed_macht_das_ergebnis_reproduzierbar(self):
        for env in ({}, {"FOOTSIM_ML_MODE": "active",
                         "FOOTSIM_ML_WEIGHT": "1.0"}):
            erst = self._simulate(env)
            zweit = self._simulate(env)
            assert erst["top_scores"] == zweit["top_scores"]
            assert erst["home_win_probability"] == zweit["home_win_probability"]

    def test_keine_negativen_tore(self):
        r = self._simulate({"FOOTSIM_ML_MODE": "active",
                            "FOOTSIM_ML_WEIGHT": "1.0"})
        for eintrag in r["top_scores"]:
            heim, gast = eintrag["score"].split(":")
            assert int(heim) >= 0 and int(gast) >= 0

    def test_ein_unbekanntes_team_bringt_nichts_zum_absturz(self):
        r = self._simulate({"FOOTSIM_ML_MODE": "active",
                            "FOOTSIM_ML_WEIGHT": "1.0"})
        assert r is not None
        from src.predict import cl_match_sim

        unbekannt = cl_match_sim.simulate_cl_league_phase_match(
            home_team="Erfundenes Team", away_team="Anderes Team",
            home_id=999999, away_id=999998, season=2025,
            simulations=200, use_seed=True)
        assert unbekannt["home_resolution"] == "neutral"
        assert unbekannt["ml"]["applied"] is False

    def test_ein_fehlendes_modell_bringt_nichts_zum_absturz(self, monkeypatch):
        from src.ml import inference as inf

        monkeypatch.setattr(inf, "DEFAULT_MODEL_PATH", "data/ml/models/weg.json")
        inf.reset_model_cache()
        try:
            r = self._simulate({"FOOTSIM_ML_MODE": "active",
                                "FOOTSIM_ML_WEIGHT": "1.0"})
            assert r["ml"]["applied"] is False
            assert r["ml"]["fallback_reason"] == "model_missing"
            assert sum([r["home_win_probability"], r["draw_probability"],
                        r["away_win_probability"]]) == pytest.approx(100.0,
                                                                     abs=0.05)
        finally:
            inf.reset_model_cache()

    def test_die_antwort_bleibt_rueckwaertskompatibel(self):
        """Bestehende Felder bleiben; ml kommt additiv hinzu."""
        r = self._simulate({})
        for feld in ("home_team", "away_team", "expected_home_goals",
                     "expected_away_goals", "home_win_probability",
                     "draw_probability", "away_win_probability",
                     "top_scores", "competition", "phase",
                     "home_resolution", "away_resolution"):
            assert feld in r, feld
        assert "ml" in r


# ---------------------------------------------------------------------------
# 8. Isolation
# ---------------------------------------------------------------------------

class TestIsolation:

    def test_die_ligasimulation_kennt_kein_ml(self):
        import pathlib

        wurzel = pathlib.Path(__file__).resolve().parents[1]
        for name in ("league_match_sim.py", "season_sim.py",
                     "simulate_scores.py", "poisson.py"):
            pfad = wurzel / "src" / "predict" / name
            if not pfad.exists():
                continue
            text = pfad.read_text(encoding="utf-8", errors="ignore")
            assert "src.ml" not in text, name

    def test_app_py_bindet_ml_nicht_direkt_an(self):
        """
        Die Anbindung sitzt an EINER Stelle in der Simulation, nicht in
        den Routen. Sonst gaebe es mehrere Orte, an denen dieselbe
        Entscheidung auseinanderlaufen kann.
        """
        import pathlib

        text = (pathlib.Path(__file__).resolve().parents[1]
                / "app.py").read_text(encoding="utf-8", errors="ignore")
        assert "src.ml" not in text

    def test_nur_die_cl_pfade_rufen_die_schicht(self):
        import pathlib

        wurzel = pathlib.Path(__file__).resolve().parents[1]
        rufer = []
        for pfad in (wurzel / "src").rglob("*.py"):
            if pfad.match("*/ml/*"):
                continue
            text = pfad.read_text(encoding="utf-8", errors="ignore")
            if "resolve_simulation_lambdas" in text:
                rufer.append(pfad.name)
        assert sorted(rufer) == ["cl_match_sim.py", "cl_season_sim.py"]

    def test_die_produktion_erreicht_ml_nur_ueber_die_runtime(self):
        """
        C5 und C6 duerfen weiterhin nicht direkt aus dem Produktivpfad
        gerufen werden - der einzige Weg fuehrt ueber src/ml/runtime.py.
        """
        import pathlib

        wurzel = pathlib.Path(__file__).resolve().parents[1]
        for pfad in list((wurzel / "src").rglob("*.py")) + [wurzel / "app.py"]:
            if pfad.match("*/ml/*"):
                continue
            text = pfad.read_text(encoding="utf-8", errors="ignore")
            assert "ml.inference" not in text, pfad.name
            assert "ml.blend" not in text, pfad.name

    def test_keine_ui_kennt_die_gewichtung(self):
        import pathlib

        wurzel = pathlib.Path(__file__).resolve().parents[1]
        for ordner in ("templates", "static"):
            for pfad in (wurzel / ordner).rglob("*"):
                if not pfad.is_file() or pfad.suffix not in (".html", ".js"):
                    continue
                text = pfad.read_text(encoding="utf-8", errors="ignore")
                for verboten in ("FOOTSIM_ML_MODE", "ml_weight",
                                 "weighted_lambda"):
                    assert verboten not in text, f"{verboten} in {pfad.name}"
