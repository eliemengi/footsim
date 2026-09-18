"""
C23: Drei Berechnungsansaetze, ehrliche Ergebniszeile, korrekte Prozente.

Was diese Datei belegt
----------------------
1. Validierung: ml | custom | classic, zentral in cl_custom_factors -
   fuer das Einzelspiel (JSON) und die Ligaphase (Query-Parameter).
2. Echte Paritaet: Fuer jede offene Partie zum selben historischen
   Stichtag liefert die Ligaphase dieselben Lambdas wie das Einzelspiel -
   fuer ml, classic und custom mit globalen Faktoren. Keine Mocks der
   Rechnung; nur die Lambda-Entscheidung wird mitgeschrieben
   (c21._lambda_spion, derselbe Weg wie in der C21-Validierung).
3. Neutrales custom ist bitgleich classic; Heimvorteil und Torniveau
   wirken genau EINMAL, und der gemeinsame Ligaschnitt bleibt unberuehrt.
4. classic und custom laden kein Modell, auch nicht bei Server-active.
5. Die Ergebniswahrheit: Erfolg, voller Rueckfall (echte, leere
   Registry), teilweiser Rueckfall.
6. Der HTTP-Vertrag beider Endpunkte, einschliesslich alter Clients.
7. Die Browserfunktionen fuer Prozent, Ergebniszeile und Wappen-URL,
   ausgefuehrt in Node aus dem ECHTEN script.js (keine Kopie).

Alle Aktivierungen laufen isoliert in temporaeren Verzeichnissen
(c21.isolated_activation); die echte Registry wird nicht beruehrt.
"""

import contextlib
import copy
import functools
import json
import math
import os
import re
import shutil
import subprocess
import tempfile

import pytest
from werkzeug.datastructures import MultiDict

from src.predict import cl_custom_factors as ccf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEASON = 2025
HA, GL = 1.3, 0.85


def _lies(*teile):
    with open(os.path.join(ROOT, *teile), encoding="utf-8") as quelle:
        return quelle.read()


# ---------------------------------------------------------------------------
# 1. Validierung
# ---------------------------------------------------------------------------

class TestValidierungEinzelspiel:

    def test_classic_ist_ein_gueltiger_ansatz(self):
        optionen = ccf.parse_options({"approach": "classic"})
        assert optionen == {"approach": "classic",
                            "factors": dict(ccf.NEUTRAL_FACTORS),
                            "ml_weight": 0.0}

    @pytest.mark.parametrize("zusatz", [
        {"factors": {"goal_level": 1.1}},
        {"factors": {}},
        {"ml_weight": 0.0},
        {"ml_weight": 1.0},
    ])
    def test_classic_nimmt_weder_faktoren_noch_gewicht(self, zusatz):
        with pytest.raises(ccf.InvalidSimulationRequest):
            ccf.parse_options({"approach": "classic", **zusatz})

    @pytest.mark.parametrize("roh", [
        {"approach": "ML"}, {"approach": "v2"}, {"approach": ""},
        {"approach": 1}, {"approach": None, "factors": {}},
        {"approach": "custom", "factors": {"goal_level": float("nan")}},
        {"approach": "custom", "factors": {"goal_level": float("inf")}},
        {"approach": "custom", "factors": {"goal_level": "1.1"}},
        {"approach": "custom", "factors": {"goal_level": True}},
        {"approach": "custom", "factors": {"offense": 1.1}},
        {"approach": "custom", "ml_weight": 0.0},
        {"approach": "ml", "ml_weight": 1.0},
        {"approach": "ml", "factors": {"goal_level": 1.0}},
    ])
    def test_unzulaessiges_wird_abgewiesen(self, roh):
        with pytest.raises(ccf.InvalidSimulationRequest):
            ccf.parse_options(roh)

    def test_ml_config_je_ansatz(self):
        ml = ccf.ml_config(ccf.parse_options({"approach": "ml"}))
        assert (ml["mode"], ml["weight"]) == ("active", 1.0)
        for ansatz in ("custom", "classic"):
            konfig = ccf.ml_config(ccf.parse_options({"approach": ansatz}))
            assert (konfig["mode"], konfig["weight"]) == ("off", 0.0), ansatz
        # Alter Client: keine eigene Konfiguration, die Umgebung entscheidet.
        assert ccf.ml_config(None) is None


class TestValidierungLigaphase:

    def test_ohne_ansatz_bleibt_es_bei_der_umgebung(self):
        assert ccf.parse_season_options(MultiDict({"season": "2025"})) is None

    @pytest.mark.parametrize("ansatz,gewicht", [("ml", 1.0), ("classic", 0.0),
                                                ("custom", 0.0)])
    def test_die_drei_ansaetze(self, ansatz, gewicht):
        optionen = ccf.parse_season_options(MultiDict({"approach": ansatz}))
        assert optionen == {"approach": ansatz,
                            "factors": dict(ccf.NEUTRAL_FACTORS),
                            "ml_weight": gewicht}

    def test_custom_nimmt_die_globalen_faktoren(self):
        optionen = ccf.parse_season_options(MultiDict({
            "approach": "custom", "home_advantage": "1.3", "goal_level": "0.85"}))
        assert optionen["factors"] == {"home_strength": 1.0, "away_strength": 1.0,
                                       "home_advantage": 1.3, "goal_level": 0.85}

    def test_die_grenzen_sind_die_des_einzelspiels(self):
        for name in ccf.SEASON_FACTOR_NAMES:
            unten, oben = ccf.FACTOR_BOUNDS[name]
            for wert in (unten, oben):
                ccf.parse_season_options(MultiDict({"approach": "custom",
                                                    name: str(wert)}))
            for wert in (unten - 0.01, oben + 0.01):
                with pytest.raises(ccf.InvalidSimulationRequest):
                    ccf.parse_season_options(MultiDict({"approach": "custom",
                                                        name: str(wert)}))

    @pytest.mark.parametrize("args", [
        {"approach": "bogus"},
        {"approach": "ML"},
        {"approach": "ml", "ml_weight": "1"},
        {"approach": "custom", "ml_weight": "0"},
        {"approach": "custom", "factors": "x"},
        {"approach": "custom", "home_strength": "1.2"},
        {"approach": "custom", "away_strength": "1.2"},
        {"approach": "ml", "home_advantage": "1.1"},
        {"approach": "classic", "goal_level": "1.1"},
        {"approach": "custom", "goal_level": "nan"},
        {"approach": "custom", "goal_level": "inf"},
        {"approach": "custom", "goal_level": "-inf"},
        {"approach": "custom", "goal_level": "abc"},
        {"approach": "custom", "goal_level": ""},
        {"home_advantage": "1.1"},
        {"ml_weight": "1"},
    ])
    def test_unzulaessiges_wird_abgewiesen(self, args):
        with pytest.raises(ccf.InvalidSimulationRequest):
            ccf.parse_season_options(MultiDict(args))

    def test_doppelte_parameter_werden_abgewiesen(self):
        with pytest.raises(ccf.InvalidSimulationRequest):
            ccf.parse_season_options(MultiDict([("approach", "ml"),
                                                ("approach", "classic")]))
        with pytest.raises(ccf.InvalidSimulationRequest):
            ccf.parse_season_options(MultiDict([("approach", "custom"),
                                                ("goal_level", "1.1"),
                                                ("goal_level", "0.9")]))


class TestFaktorformel:

    def test_eine_formel_fuer_beide_pfade(self):
        schnitt = {"home_goals": 1.61, "away_goals": 1.23, "extra": {"n": 1}}
        faktoren = dict(ccf.NEUTRAL_FACTORS, home_advantage=HA, goal_level=GL)
        _h, _a, aus_einzelspiel = ccf.apply_factors(
            {"attack_home": 1.0}, {"attack_away": 1.0}, schnitt, faktoren)
        aus_ligaphase = ccf.apply_league_factors(schnitt, faktoren)
        assert aus_einzelspiel == aus_ligaphase
        assert aus_ligaphase["home_goals"] == pytest.approx(
            1.61 * math.sqrt(HA) * GL, abs=1e-15)
        assert aus_ligaphase["away_goals"] == pytest.approx(
            1.23 / math.sqrt(HA) * GL, abs=1e-15)

    def test_die_ligaphase_veraendert_den_gemeinsamen_schnitt_nicht(self):
        schnitt = {"home_goals": 1.61, "away_goals": 1.23, "extra": {"n": 1}}
        vorher = copy.deepcopy(schnitt)
        neu = ccf.apply_league_factors(
            schnitt, dict(ccf.NEUTRAL_FACTORS, home_advantage=HA, goal_level=GL))
        assert schnitt == vorher
        assert neu is not schnitt and neu["extra"] is not schnitt["extra"]

    def test_teamfaktoren_wirken_in_der_ligaphase_nicht(self):
        schnitt = {"home_goals": 1.61, "away_goals": 1.23}
        mit = ccf.apply_league_factors(schnitt, dict(
            ccf.NEUTRAL_FACTORS, home_strength=1.3, away_strength=0.7))
        assert mit == schnitt


# ---------------------------------------------------------------------------
# 2. Laufzeit: echte Plaene, echte Profile, isolierte Registry
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def c21():
    from src.ml import c21_season_validation as modul
    return modul


@pytest.fixture(scope="module")
def kandidat():
    from src.ml import c21_release_readiness as rr
    pfad = os.path.join(ROOT, rr.CANDIDATE_PATH)
    if not os.path.isfile(pfad):
        pytest.skip("der freigegebene Kandidat liegt nicht vor")
    with open(pfad, encoding="utf-8") as datei:
        return json.load(datei)


@pytest.fixture(scope="module")
def evaluation():
    from src.ml import c20_temporal_map as c20
    with open(os.path.join(ROOT, c20.EVALUATION_PATH), encoding="utf-8") as datei:
        return json.load(datei)


@pytest.fixture(scope="module")
def stichtag_daten(c21):
    """Der letzte vorab festgelegte Stichtag 2025: Plan und Profile."""
    from src.features.strength_provider import get_cl_team_strengths

    try:
        _name, stichtag = c21.cutoffs(SEASON)[-1]
        plan = c21.plan_at(SEASON, stichtag)
    except (FileNotFoundError, OSError):
        pytest.skip("die lokale CL-Saisondatei liegt nicht vor")
    staerken = get_cl_team_strengths(season=SEASON, cutoff=stichtag)
    assert plan["remaining_matches"], "zum Stichtag muss etwas offen sein"
    return stichtag, plan, staerken


@contextlib.contextmanager
def _leere_registry():
    """
    Eine TEMPORAERE Registry ohne aktives Modell - der echte
    Rueckfallweg der Laufzeit (fail-closed), ohne die echte Registry zu
    lesen oder zu schreiben. Umgelenkt werden dieselben zwei Stellen wie
    in c21.isolated_activation.
    """
    from src.ml import inference as inf
    from src.ml import model_registry as mr

    echt_active_entry = mr.active_entry
    echt_root = inf._REPO_ROOT
    with tempfile.TemporaryDirectory() as wurzel:
        os.makedirs(os.path.join(wurzel, "data", "ml", "models"))
        mr.write_registry(mr.empty_registry(), repo_root=wurzel)
        mr.active_entry = functools.partial(echt_active_entry, repo_root=wurzel)
        inf._REPO_ROOT = wurzel
        inf.reset_model_cache()
        try:
            yield wurzel
        finally:
            mr.active_entry = echt_active_entry
            inf._REPO_ROOT = echt_root
            inf.reset_model_cache()


def _saison_optionen(**args):
    return ccf.parse_season_options(MultiDict(args))


def _saison_lambdas(c21, plan, staerken, optionen):
    from src.predict import cl_season_sim as css

    with c21._lambda_spion() as log:
        ergebnis = css.simulate_cl_league_phase(
            plan, simulations=1, season=SEASON, seed=0, strengths=staerken,
            options=optionen)
    return {(e["home_id"], e["away_id"]): e for e in log}, ergebnis


def _einzel_lambdas(c21, plan, stichtag, optionen):
    from src.predict import cl_match_sim as cms

    heraus = {}
    for f in plan["remaining_matches"]:
        with c21._lambda_spion() as log:
            antwort = cms.simulate_cl_league_phase_match(
                str(f["home_id"]), str(f["away_id"]),
                home_id=f["home_id"], away_id=f["away_id"], season=SEASON,
                simulations=1, use_seed=True, kickoff=stichtag,
                options=optionen)
        assert len(log) == 1
        heraus[(f["home_id"], f["away_id"])] = dict(log[0], antwort=antwort)
    return heraus


def _max_abweichung(saison, einzel):
    assert set(saison) == set(einzel)
    return max(max(abs(saison[k]["lambda_home"] - einzel[k]["lambda_home"]),
                   abs(saison[k]["lambda_away"] - einzel[k]["lambda_away"]))
               for k in einzel)


class TestParitaet:
    """Ligaphase und Einzelspiel rechnen je offener Partie dasselbe."""

    def test_classic(self, c21, stichtag_daten, monkeypatch):
        # Umgebung active: Der ausdrueckliche Ansatz muss sie schlagen.
        monkeypatch.setenv("FOOTSIM_ML_MODE", "active")
        stichtag, plan, staerken = stichtag_daten
        saison, ergebnis = _saison_lambdas(c21, plan, staerken,
                                           _saison_optionen(approach="classic"))
        einzel = _einzel_lambdas(c21, plan, stichtag,
                                 ccf.parse_options({"approach": "classic"}))
        assert len(einzel) == len(plan["remaining_matches"])
        assert _max_abweichung(saison, einzel) <= c21.PARITY_TOLERANCE
        assert not any(e["applied"] for e in saison.values())
        assert ergebnis["ml"]["effective_approach"] == "classic"

    def test_custom_mit_globalen_faktoren(self, c21, stichtag_daten):
        stichtag, plan, staerken = stichtag_daten
        saison, ergebnis = _saison_lambdas(
            c21, plan, staerken,
            _saison_optionen(approach="custom", home_advantage=str(HA),
                             goal_level=str(GL)))
        einzel = _einzel_lambdas(c21, plan, stichtag, ccf.parse_options({
            "approach": "custom",
            "factors": {"home_advantage": HA, "goal_level": GL}}))
        assert _max_abweichung(saison, einzel) <= c21.PARITY_TOLERANCE
        assert ergebnis["ml"]["effective_approach"] == "custom"
        assert ergebnis["ml"]["fixtures_with_ml"] == 0

    def test_ml(self, c21, stichtag_daten, kandidat, evaluation, monkeypatch):
        # Umgebung off: Der ausdrueckliche Ansatz schaltet ML trotzdem ein.
        monkeypatch.setenv("FOOTSIM_ML_MODE", "off")
        stichtag, plan, staerken = stichtag_daten
        with c21.isolated_activation(kandidat, evaluation):
            saison, ergebnis = _saison_lambdas(c21, plan, staerken,
                                               _saison_optionen(approach="ml"))
            einzel = _einzel_lambdas(c21, plan, stichtag,
                                     ccf.parse_options({"approach": "ml"}))
        assert _max_abweichung(saison, einzel) <= c21.PARITY_TOLERANCE
        assert all(e["applied"] for e in saison.values())
        assert all(e["applied"] for e in einzel.values())
        assert {e["model_id"] for e in saison.values()} == {kandidat["model_id"]}
        ml = ergebnis["ml"]
        assert (ml["mode"], ml["effective_approach"], ml["ml_fallback"]) == (
            "active", "ml", "none")
        assert ml["ml_fixtures"] == ml["fixtures_total"] == len(einzel)
        assert ml["requested_approach"] == "ml"
        # Einzelspielantworten: dieselbe Wahrheit je Partie.
        for e in einzel.values():
            assert e["antwort"]["ml"]["effective_approach"] == "ml"
            assert e["antwort"]["ml"]["ml_fallback"] == "none"


class TestFaktorenGenauEinmal:

    def test_neutrales_custom_ist_bitgleich_classic(self, c21, stichtag_daten):
        _stichtag, plan, staerken = stichtag_daten
        custom, _r = _saison_lambdas(c21, plan, staerken,
                                     _saison_optionen(approach="custom"))
        klassisch, _r = _saison_lambdas(c21, plan, staerken,
                                        _saison_optionen(approach="classic"))
        assert custom.keys() == klassisch.keys()
        for k in custom:
            assert custom[k]["lambda_home"] == klassisch[k]["lambda_home"]
            assert custom[k]["lambda_away"] == klassisch[k]["lambda_away"]

    def test_neutrales_custom_ist_im_einzelspiel_bitgleich_classic(
            self, c21, stichtag_daten):
        stichtag, plan, _staerken = stichtag_daten
        klein = dict(plan, remaining_matches=plan["remaining_matches"][:6])
        custom = _einzel_lambdas(c21, klein, stichtag,
                                 ccf.parse_options({"approach": "custom"}))
        klassisch = _einzel_lambdas(c21, klein, stichtag,
                                    ccf.parse_options({"approach": "classic"}))
        for k in custom:
            assert custom[k]["lambda_home"] == klassisch[k]["lambda_home"]
            assert custom[k]["lambda_away"] == klassisch[k]["lambda_away"]

    def test_heimvorteil_und_torniveau_wirken_genau_einmal(self, c21,
                                                            stichtag_daten):
        """
        xG ist linear im Ligaschnitt. Wirken die Faktoren genau einmal,
        ist das Verhaeltnis custom/classic je unbegrenzter Partie exakt
        sqrt(HA)*GL (Heim) und GL/sqrt(HA) (Gast). Doppelt angewandt
        stuende dort das Quadrat.
        """
        from src.features.team_profile import XG_MAX, XG_MIN

        _stichtag, plan, staerken = stichtag_daten
        vorher = copy.deepcopy(staerken["league_avg"])
        custom, _r = _saison_lambdas(
            c21, plan, staerken,
            _saison_optionen(approach="custom", home_advantage=str(HA),
                             goal_level=str(GL)))
        klassisch, _r = _saison_lambdas(c21, plan, staerken,
                                        _saison_optionen(approach="classic"))
        assert staerken["league_avg"] == vorher

        geprueft = 0
        for k, c in custom.items():
            b = klassisch[k]
            werte = (c["lambda_home"], c["lambda_away"],
                     b["lambda_home"], b["lambda_away"])
            if any(not (XG_MIN < w < XG_MAX) for w in werte):
                continue
            assert c["lambda_home"] / b["lambda_home"] == pytest.approx(
                math.sqrt(HA) * GL, rel=1e-12)
            assert c["lambda_away"] / b["lambda_away"] == pytest.approx(
                GL / math.sqrt(HA), rel=1e-12)
            geprueft += 1
        assert geprueft >= len(custom) // 2


class TestKeinModellOhneMl:

    @pytest.mark.parametrize("args", [{"approach": "classic"},
                                      {"approach": "custom"},
                                      {"approach": "custom",
                                       "home_advantage": "1.2",
                                       "goal_level": "0.9"}])
    def test_ligaphase(self, c21, stichtag_daten, kandidat, evaluation,
                       monkeypatch, args):
        from src.ml import inference as inf

        monkeypatch.setenv("FOOTSIM_ML_MODE", "active")
        monkeypatch.setenv("FOOTSIM_ML_WEIGHT", "1.0")
        geladen = []
        echt = inf.load_model

        def zaehlend(*a, **kw):
            geladen.append(1)
            return echt(*a, **kw)

        monkeypatch.setattr(inf, "load_model", zaehlend)
        _stichtag, plan, staerken = stichtag_daten
        with c21.isolated_activation(kandidat, evaluation):
            _log, ergebnis = _saison_lambdas(c21, plan, staerken,
                                             _saison_optionen(**args))
        assert geladen == []
        ml = ergebnis["ml"]
        assert (ml["mode"], ml["fixtures_with_ml"], ml["model_id"]) == (
            "off", 0, None)
        assert ml["effective_approach"] == args["approach"]
        assert ml["fallback_reasons"] == {}


# ---------------------------------------------------------------------------
# 3. Ergebniswahrheit
# ---------------------------------------------------------------------------

class TestErgebniswahrheit:

    def test_voller_rueckfall_in_der_ligaphase(self, c21, stichtag_daten):
        _stichtag, plan, staerken = stichtag_daten
        with _leere_registry():
            _log, ergebnis = _saison_lambdas(c21, plan, staerken,
                                             _saison_optionen(approach="ml"))
        ml = ergebnis["ml"]
        assert ml["mode"] == "active"
        assert ml["fixtures_with_ml"] == 0
        assert (ml["effective_approach"], ml["ml_fallback"]) == ("classic", "full")
        assert sum(ml["fallback_reasons"].values()) == ml["fixtures_total"]

    def test_voller_rueckfall_im_einzelspiel(self, c21, stichtag_daten):
        stichtag, plan, _staerken = stichtag_daten
        klein = dict(plan, remaining_matches=plan["remaining_matches"][:2])
        with _leere_registry():
            einzel = _einzel_lambdas(c21, klein, stichtag,
                                     ccf.parse_options({"approach": "ml"}))
        for e in einzel.values():
            ml = e["antwort"]["ml"]
            assert ml["applied"] is False
            assert (ml["effective_approach"], ml["ml_fallback"]) == (
                "classic", "full")

    def test_teilweiser_rueckfall_wird_gezaehlt(self, c21, stichtag_daten,
                                                 kandidat, evaluation,
                                                 monkeypatch):
        """
        Die Laufzeit entscheidet je Partie. Hier faellt jede dritte
        Partie kontrolliert zurueck (die Laufzeit wird fuer sie mit
        mode=off gerufen, also ueber ihren eigenen Rueckfallweg); die
        Zusammenfassung muss das als TEILWEISE ausweisen, nicht als
        Erfolg und nicht als vollen Rueckfall.
        """
        from src.predict import cl_season_sim as css

        echt = css.resolve_simulation_lambdas
        zaehler = {"n": 0}

        def teilweise(*a, **kw):
            zaehler["n"] += 1
            if zaehler["n"] % 3 == 0:
                ergebnis = echt(*a, **dict(kw, config=dict(kw["config"], mode="off")))
                return dict(ergebnis, fallback_reason="test_partial")
            return echt(*a, **kw)

        monkeypatch.setattr(css, "resolve_simulation_lambdas", teilweise)
        _stichtag, plan, staerken = stichtag_daten
        with c21.isolated_activation(kandidat, evaluation):
            ergebnis = css.simulate_cl_league_phase(
                plan, simulations=1, season=SEASON, seed=0, strengths=staerken,
                options=_saison_optionen(approach="ml"))
        ml = ergebnis["ml"]
        gesamt = ml["fixtures_total"]
        assert 0 < ml["ml_fixtures"] < gesamt
        assert ml["ml_fixtures"] == gesamt - gesamt // 3
        assert (ml["effective_approach"], ml["ml_fallback"]) == ("ml", "partial")
        assert ml["fallback_reasons"] == {"test_partial": gesamt // 3}

    @pytest.mark.parametrize("optionen,ml,erwartet", [
        ({"approach": "custom"}, {}, ("custom", "none", None)),
        ({"approach": "classic"}, {"ml_applied_to_production": False,
                                   "mode": "off"}, ("classic", "none", None)),
        ({"approach": "ml"}, {"ml_applied_to_production": True,
                              "league_stage": {"applied": True}},
         ("ml", "none", True)),
        # Nur die Ligakorrektur fehlt: KEIN ML-Ausfall.
        ({"approach": "ml"}, {"ml_applied_to_production": True,
                              "league_stage": {"applied": False,
                                               "status": "team_not_in_map"}},
         ("ml", "none", False)),
        ({"approach": "ml"}, {"ml_applied_to_production": False,
                              "mode": "active"}, ("classic", "full", None)),
        # Alter Client, Umgebung off: regulaer klassisch, kein Rueckfall.
        (None, {"ml_applied_to_production": False, "mode": "off"},
         ("classic", "none", None)),
        # Alter Client, Umgebung active, Modell traegt nicht: Rueckfall.
        (None, {"ml_applied_to_production": False, "mode": "active"},
         ("classic", "full", None)),
    ])
    def test_einzelspiel_zusammenfassung(self, optionen, ml, erwartet):
        aus = ccf.describe_match_approach(optionen, ml)
        assert (aus["effective_approach"], aus["ml_fallback"],
                aus["league_stage_applied"]) == erwartet

    @pytest.mark.parametrize("optionen,modus,mit_ml,gesamt,erwartet", [
        ({"approach": "ml"}, "active", 144, 144, ("ml", "none")),
        ({"approach": "ml"}, "active", 100, 144, ("ml", "partial")),
        ({"approach": "ml"}, "active", 0, 144, ("classic", "full")),
        ({"approach": "classic"}, "off", 0, 144, ("classic", "none")),
        ({"approach": "custom"}, "off", 0, 144, ("custom", "none")),
        (None, "off", 0, 144, ("classic", "none")),
        (None, "active", 144, 144, ("ml", "none")),
        ({"approach": "ml"}, "active", 0, 0, (None, "none")),
    ])
    def test_ligaphase_zusammenfassung(self, optionen, modus, mit_ml, gesamt,
                                       erwartet):
        aus = ccf.describe_season_approach(optionen, {"mode": modus}, mit_ml,
                                           gesamt, mit_ml)
        assert (aus["effective_approach"], aus["ml_fallback"]) == erwartet
        assert (aus["ml_fixtures"], aus["fixtures_total"]) == (mit_ml, gesamt)


# ---------------------------------------------------------------------------
# 4. HTTP-Vertrag
# ---------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    """Testclient mit CSRF; Ratenlimit aus (siehe test_c22_local_activation)."""
    from tests.conftest import mit_csrf

    import app as app_module

    monkeypatch.setitem(app_module.app.config, "RATELIMIT_ENABLED", False)
    monkeypatch.setattr(app_module.limiter, "enabled", False)
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as verbindung:
        yield mit_csrf(verbindung)


@pytest.fixture
def saison_endpunkt(monkeypatch, stichtag_daten):
    """
    /api/cl-season-sim mit dem historischen Plan und den Profilen des
    Stichtags statt des Anbieters. Die Rechnung selbst bleibt die echte;
    mitgeschrieben wird nur, welche Optionen ankamen.
    """
    import app as app_module
    from src.predict import cl_season_sim as css

    _stichtag, plan, staerken = stichtag_daten
    angekommen = []

    def simulieren(**kw):
        angekommen.append(kw.get("options"))
        return css.simulate_cl_league_phase(strengths=staerken, seed=3, **kw)

    monkeypatch.setattr(app_module, "build_cl_league_phase_plan",
                        lambda season, expected_matches_per_team: plan)
    monkeypatch.setattr(app_module, "simulate_cl_league_phase", simulieren)
    return angekommen


def _cl(**extra):
    return {"competition": "cl", "home_team": "Heim", "away_team": "Gast",
            "home_id": 5, "away_id": 57, "season": SEASON, "simulations": 300,
            "use_seed": True, **extra}


class TestHttpLigaphase:

    def test_classic_schlaegt_die_umgebung(self, client, saison_endpunkt,
                                           monkeypatch):
        monkeypatch.setenv("FOOTSIM_ML_MODE", "active")
        antwort = client.get(
            "/api/cl-season-sim?simulations=20&season=2025&approach=classic")
        assert antwort.status_code == 200
        ml = antwort.get_json()["ml"]
        assert (ml["mode"], ml["effective_approach"], ml["requested_approach"],
                ml["fixtures_with_ml"]) == ("off", "classic", "classic", 0)
        assert saison_endpunkt[-1]["approach"] == "classic"

    def test_custom_reicht_die_globalen_faktoren_durch(self, client,
                                                        saison_endpunkt):
        antwort = client.get("/api/cl-season-sim?simulations=20&season=2025"
                             "&approach=custom&home_advantage=1.2&goal_level=0.9")
        assert antwort.status_code == 200
        assert antwort.get_json()["ml"]["effective_approach"] == "custom"
        assert saison_endpunkt[-1]["factors"] == {
            "home_strength": 1.0, "away_strength": 1.0,
            "home_advantage": 1.2, "goal_level": 0.9}

    def test_alter_client_ohne_ansatz_folgt_der_umgebung(self, client,
                                                          saison_endpunkt,
                                                          monkeypatch):
        monkeypatch.setenv("FOOTSIM_ML_MODE", "off")
        antwort = client.get("/api/cl-season-sim?simulations=20&season=2025")
        assert antwort.status_code == 200
        ml = antwort.get_json()["ml"]
        assert saison_endpunkt[-1] is None
        assert (ml["mode"], ml["requested_approach"],
                ml["effective_approach"], ml["ml_fallback"]) == (
            "off", None, "classic", "none")

    def test_ml_schlaegt_eine_umgebung_off(self, client, saison_endpunkt,
                                           kandidat, evaluation, c21,
                                           monkeypatch):
        monkeypatch.setenv("FOOTSIM_ML_MODE", "off")
        with c21.isolated_activation(kandidat, evaluation):
            antwort = client.get(
                "/api/cl-season-sim?simulations=20&season=2025&approach=ml")
        ml = antwort.get_json()["ml"]
        assert antwort.status_code == 200
        assert (ml["mode"], ml["effective_approach"], ml["model_id"]) == (
            "active", "ml", kandidat["model_id"])
        assert ml["ml_fixtures"] == ml["fixtures_total"] > 0

    @pytest.mark.parametrize("query", [
        "approach=bogus", "approach=ml&ml_weight=1",
        "approach=custom&home_strength=1.2", "approach=custom&away_strength=0.8",
        "approach=classic&home_advantage=1.1", "approach=ml&goal_level=1.1",
        "approach=custom&goal_level=nan", "approach=custom&goal_level=inf",
        "approach=custom&home_advantage=9", "home_advantage=1.1",
        "approach=ml&approach=classic", "approach=custom&factors=x",
    ])
    def test_unzulaessiges_ist_400(self, client, saison_endpunkt, query):
        antwort = client.get("/api/cl-season-sim?simulations=20&season=2025&" + query)
        assert antwort.status_code == 400
        text = antwort.get_json()["error"]
        for verboten in ("Traceback", ".py", "\\"):
            assert verboten not in text
        # Abgewiesen VOR jeder Rechnung.
        assert saison_endpunkt == []


class TestHttpEinzelspiel:

    def test_classic_liefert_anzahl_und_ansatz(self, client, monkeypatch):
        monkeypatch.setenv("FOOTSIM_ML_MODE", "active")
        antwort = client.post("/api/simulate", json=_cl(approach="classic"))
        daten = antwort.get_json()
        assert antwort.status_code == 200
        assert daten["simulations"] == 300
        assert (daten["ml"]["mode"], daten["ml"]["effective_approach"],
                daten["ml"]["ml_fallback"]) == ("off", "classic", "none")
        assert sum(e["count"] for e in daten["top_scores"]) <= 300

    @pytest.mark.parametrize("angefragt,erwartet", [(60000, 50000), (50, 100),
                                                    (5000, 5000)])
    def test_die_ausgefuehrte_anzahl_respektiert_die_grenzen(self, client,
                                                              angefragt,
                                                              erwartet):
        antwort = client.post("/api/simulate", json=_cl(
            approach="classic", simulations=angefragt))
        assert antwort.status_code == 200
        assert antwort.get_json()["simulations"] == erwartet

    @pytest.mark.parametrize("zusatz", [
        {"approach": "classic", "factors": {"goal_level": 1.1}},
        {"approach": "classic", "ml_weight": 0.0},
        {"approach": "custom", "ml_weight": 0.0},
        {"approach": "ml", "factors": {"goal_level": 1.0}},
        {"approach": "v2"},
    ])
    def test_unzulaessiges_ist_400(self, client, zusatz):
        assert client.post("/api/simulate", json=_cl(**zusatz)).status_code == 400

    def test_nicht_endliche_zahlen_im_json_sind_400(self, client):
        roh = json.dumps(_cl(approach="custom", factors={"goal_level": 1.0}))
        roh = roh.replace('"goal_level": 1.0', '"goal_level": NaN')
        assert "NaN" in roh
        antwort = client.post("/api/simulate", data=roh,
                              content_type="application/json")
        assert antwort.status_code == 400

    def test_die_ligen_liefern_die_anzahl_ebenfalls(self):
        quelle = _lies("src", "predict", "league_match_sim.py")
        assert '"simulations": simulations,' in quelle
        assert '"simulations": simulations,' in _lies("src", "predict",
                                                      "cl_match_sim.py")


# ---------------------------------------------------------------------------
# 5. Browserfunktionen aus dem echten script.js, ausgefuehrt in Node
# ---------------------------------------------------------------------------

NODE = shutil.which("node")

JS_FUNKTIONEN = ("catalogValue", "humanizeKey", "t", "activeIntlLocale",
                 "clApproachTitle", "clMatchApproachText",
                 "clSeasonApproachText", "validSimulationCount",
                 "topScoreSharePercent", "formatSharePercent",
                 "clSafeCrestUrl")
JS_KONSTANTEN = ("CL_APPROACH_ML", "CL_APPROACH_CUSTOM", "CL_APPROACH_CLASSIC",
                 "CL_CREST_HOSTS", "CL_CREST_MAX_URL_LENGTH")


def _js_funktion(script, name):
    """Der Quelltext einer Funktion auf oberster Ebene, klammergenau."""
    start = script.index("\nfunction %s(" % name) + 1
    klammer = script.index("(", start)
    tiefe = 0
    for i in range(klammer, len(script)):
        if script[i] == "(":
            tiefe += 1
        elif script[i] == ")":
            tiefe -= 1
            if tiefe == 0:
                break
    rumpf = script.index("{", i)
    tiefe = 0
    for j in range(rumpf, len(script)):
        if script[j] == "{":
            tiefe += 1
        elif script[j] == "}":
            tiefe -= 1
            if tiefe == 0:
                return script[start:j + 1]
    raise AssertionError("Funktion %s nicht abgeschlossen" % name)


def _js_konstante(script, name):
    treffer = re.search(r"^const %s = [^\n]+;$" % name, script, re.M)
    assert treffer, name
    return treffer.group(0)


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    if NODE is None:
        pytest.skip("node ist nicht installiert")
    script = _lies("static", "script.js")
    teile = [_js_konstante(script, n) for n in JS_KONSTANTEN]
    teile += [_js_funktion(script, n) for n in JS_FUNKTIONEN]
    kataloge = {s: json.loads(_lies("static", "i18n", "%s.json" % s))
                for s in ("de", "en")}
    ordner = tmp_path_factory.mktemp("js")

    def auswerten(sprache, ausdruecke):
        programm = "\n".join([
            "const activeLocale = %s;" % json.dumps(sprache),
            "const activeTranslations = %s;" % json.dumps(kataloge[sprache]),
            "const englishTranslations = %s;" % json.dumps(kataloge["en"]),
            *teile,
            "const aus = {};",
            *["aus[%s] = (%s);" % (json.dumps(k), v)
              for k, v in ausdruecke.items()],
            "process.stdout.write(JSON.stringify(aus));",
        ])
        datei = ordner / ("lauf_%s.js" % sprache)
        datei.write_text(programm, encoding="utf-8")
        lauf = subprocess.run([NODE, str(datei)], capture_output=True,
                              text=True, encoding="utf-8", timeout=60)
        assert lauf.returncode == 0, lauf.stderr
        return json.loads(lauf.stdout)

    return auswerten


class TestProzente:

    def test_421_von_5000_sind_8_42_prozent(self, js):
        aus = js("de", {
            "roh": "topScoreSharePercent(421, 5000)",
            "de": 't("simulation.scoreShare", '
                  '{ percent: formatSharePercent(topScoreSharePercent(421, 5000)) })',
            "runs": 't("simulation.ofRuns", { count: (421).toLocaleString("de-DE"), '
                    'total: (5000).toLocaleString("de-DE") })',
        })
        assert aus["roh"] == pytest.approx(8.42, abs=1e-12)
        assert aus["de"] == "8,4 % aller Simulationen"
        assert aus["runs"] == "421 von 5.000 Simulationen"

    def test_englisch(self, js):
        aus = js("en", {
            "en": 't("simulation.scoreShare", '
                  '{ percent: formatSharePercent(topScoreSharePercent(421, 5000)) })',
            "runs": 't("simulation.ofRuns", { count: "421", total: "5,000" })',
        })
        assert aus["en"] == "8.4% of all simulations"
        assert aus["runs"] == "421 of 5,000 simulations"

    def test_keine_normalisierung_auf_die_top_fuenf(self, js):
        """Frueher: 421 / Summe der fuenf Zeilen = 24,4 %. Jetzt der
        Anteil an ALLEN Laeufen - die Zeilen summieren nicht auf 100."""
        zaehlungen = [421, 402, 384, 375, 146]
        aus = js("de", {"p": "[%s].map(c => topScoreSharePercent(c, 5000))"
                        % ",".join(map(str, zaehlungen))})
        assert aus["p"] == pytest.approx([c / 5000 * 100 for c in zaehlungen])
        assert sum(aus["p"]) < 100
        assert aus["p"][0] != pytest.approx(421 / sum(zaehlungen) * 100)

    @pytest.mark.parametrize("nenner", ["undefined", "null", "0", "-5", "12.5",
                                        '"5000"', "NaN", "Infinity"])
    def test_ohne_gueltigen_nenner_kein_prozentwert(self, js, nenner):
        aus = js("de", {"p": "topScoreSharePercent(421, %s)" % nenner,
                        "n": "validSimulationCount(%s)" % nenner})
        assert aus["p"] is None
        assert aus["n"] is None

    def test_die_darstellung_faellt_nicht_auf_die_top_fuenf_zurueck(self):
        script = _lies("static", "script.js")
        block = script[script.index("function renderTopScores("):]
        block = block[:block.index("\n}")]
        assert "topScoreSharePercent(entry.count, simulations)" in block
        assert "if (prozent !== null)" in block
        assert ".reduce(" not in block
        for katalog in ("de", "en"):
            text = _lies("static", "i18n", "%s.json" % katalog)
            for verboten in ("Top 5 decken", "Top 5 cover", "der Fälle",
                             "of outcomes"):
                assert verboten not in text, (katalog, verboten)


class TestErgebniszeile:

    @pytest.mark.parametrize("sprache,ml,erwartet", [
        ("de", {"effective_approach": "ml", "ml_fallback": "none",
                "league_stage_applied": True}, "Berechnet mit: Machine Learning"),
        ("de", {"effective_approach": "classic", "ml_fallback": "none"},
         "Berechnet mit: Klassische Simulation"),
        ("de", {"effective_approach": "custom", "ml_fallback": "none"},
         "Berechnet mit: Eigene Einschätzung"),
        ("de", {"effective_approach": "classic", "ml_fallback": "full"},
         "Machine Learning war hier nicht verfügbar. Berechnet wurde klassisch."),
        ("de", {"effective_approach": "ml", "ml_fallback": "none",
                "league_stage_applied": False},
         "Berechnet mit: Machine Learning Die Ligakorrektur war für diese "
         "Partie nicht verfügbar."),
        ("en", {"effective_approach": "ml", "ml_fallback": "none",
                "league_stage_applied": True}, "Calculated with: Machine learning"),
        ("en", {"effective_approach": "classic", "ml_fallback": "full"},
         "Machine learning was not available here. The classic simulation "
         "was used instead."),
        # Alte Antwort ohne das Feld: lieber keine Zeile als eine geratene.
        ("de", {"mode": "active", "applied": True}, ""),
        ("de", None, ""),
    ])
    def test_einzelspiel(self, js, sprache, ml, erwartet):
        aus = js(sprache, {"z": "clMatchApproachText(%s)" % json.dumps(ml)})
        assert aus["z"] == erwartet

    @pytest.mark.parametrize("sprache,ml,erwartet", [
        ("de", {"effective_approach": "ml", "ml_fallback": "none",
                "ml_fixtures": 144, "fixtures_total": 144,
                "league_stage_applied": 144}, "Berechnet mit: Machine Learning"),
        ("de", {"effective_approach": "ml", "ml_fallback": "partial",
                "ml_fixtures": 100, "fixtures_total": 144,
                "league_stage_applied": 100},
         "Machine Learning wurde für 100 von 144 offenen Spielen verwendet, "
         "die übrigen wurden klassisch berechnet."),
        ("de", {"effective_approach": "classic", "ml_fallback": "full",
                "ml_fixtures": 0, "fixtures_total": 144,
                "league_stage_applied": 0},
         "Machine Learning war hier nicht verfügbar. Berechnet wurde klassisch."),
        # Ligakorrektur nur teilweise: KEIN ML-Ausfall, aber eine Zahl.
        ("de", {"effective_approach": "ml", "ml_fallback": "none",
                "ml_fixtures": 144, "fixtures_total": 144,
                "league_stage_applied": 139},
         "Berechnet mit: Machine Learning Ligakorrektur bei 139 von 144 "
         "offenen Spielen."),
        ("de", {"effective_approach": None, "ml_fallback": "none",
                "ml_fixtures": 0, "fixtures_total": 0,
                "league_stage_applied": 0},
         "Keine offenen Spiele: Die Tabelle beruht auf den gespielten Ergebnissen."),
        ("en", {"effective_approach": "ml", "ml_fallback": "partial",
                "ml_fixtures": 1000, "fixtures_total": 1440,
                "league_stage_applied": 0},
         "Machine learning was used for 1,000 of 1,440 open matches; the rest "
         "were calculated with the classic simulation."),
    ])
    def test_ligaphase(self, js, sprache, ml, erwartet):
        aus = js(sprache, {"z": "clSeasonApproachText(%s)" % json.dumps(ml)})
        assert aus["z"] == erwartet

    def test_keine_modell_id_im_kopf(self, js):
        ml = {"effective_approach": "ml", "ml_fallback": "none",
              "league_stage_applied": True,
              "model_id": "c20-candidate-xyz", "model_ids": ["c20-candidate-xyz"]}
        aus = js("de", {"z": "clMatchApproachText(%s)" % json.dumps(ml)})
        assert "c20" not in aus["z"] and "candidate" not in aus["z"]


class TestWappen:

    def test_die_hostliste_ist_die_des_servers(self):
        from src.api import auth

        script = _lies("static", "script.js")
        liste = re.search(r"const CL_CREST_HOSTS = \[([^\]]*)\];", script).group(1)
        hosts = set(re.findall(r'"([^"]+)"', liste))
        assert hosts == set(auth.ALLOWED_CREST_HOSTS)
        assert ("const CL_CREST_MAX_URL_LENGTH = %d;" % auth.MAX_CREST_URL_LENGTH
                in script)

    @pytest.mark.parametrize("url,team_id,erwartet", [
        ("https://crests.football-data.org/5.png", None,
         "https://crests.football-data.org/5.png"),
        ("https://media.api-sports.io/football/teams/157.png", None,
         "https://media.api-sports.io/football/teams/157.png"),
        (None, 57, "https://crests.football-data.org/57.png"),
        ("", 57, "https://crests.football-data.org/57.png"),
        (None, None, None),
        (None, 0, None),
        (None, "abc", None),
        ("http://crests.football-data.org/5.png", None, None),
        ("https://evil.example/5.png", None, None),
        ("https://crests.football-data.org.evil.example/5.png", None, None),
        # Zugangsdaten in der URL: Platzhalter in spitzen Klammern, damit
        # test_audit_hardening die getrackte Datei nicht als DSN mit
        # Zugangsdaten meldet. Die URL parst weiterhin mit gesetztem
        # username/password und scheitert allein an dieser Pruefung.
        ("https://<user>:<password>@crests.football-data.org/5.png", None, None),
        ("https://crests.football-data.org:8443/5.png", None, None),
        ("javascript:alert(1)", None, None),
        ("data:image/png;base64,AAAA", None, None),
        ("https://crests.football-data.org/" + "a" * 600 + ".png", None, None),
        ("kein url", None, None),
    ])
    def test_nur_zugelassene_urls(self, js, url, team_id, erwartet):
        aus = js("de", {"u": "clSafeCrestUrl(%s, %s)" % (json.dumps(url),
                                                        json.dumps(team_id))})
        assert aus["u"] == erwartet

    def test_ein_defektes_bild_wird_zum_platzhalter(self):
        script = _lies("static", "script.js")
        block = _js_funktion(script, "clCrestNode")
        assert 'img.alt = "";' in block
        assert 'img.referrerPolicy = "no-referrer";' in block
        assert 'img.addEventListener("error", () => { img.replaceWith(platzhalter()); }' in block
        assert '"match-crest match-crest-placeholder"' in block
        assert "if (!url) return platzhalter();" in block

    def test_der_ergebniskopf_nutzt_die_berechnete_partie(self):
        script = _lies("static", "script.js")
        lauf = script[script.index("async function runSimulation()"):]
        lauf = lauf[:lauf.index("\n}")]
        assert "const partie = state.selectedMatch;" in lauf
        assert "renderResult(data, partie, wettbewerbTyp);" in lauf
        kopf = script[script.index("function renderResult("):]
        kopf = kopf[:kopf.index("\n}")]
        assert "clRenderMatchHeading(titel, {" in kopf
        assert "...partie, home_team: data.home_team, away_team: data.away_team," in kopf
