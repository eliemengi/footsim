"""
V2-C22: Die lokale V2-Anwendung, isoliert geprueft.

Die HTTP-Smoke-Tests gegen die laufende Anwendung stehen im Bericht.
Diese Datei haelt fest, was man gegen die laufende Anwendung nicht
pruefen darf oder nicht wiederholbar pruefen kann:

  - Serverbetriebsart active: Einzelspiel ohne `approach` und
    Saisonpfad wenden das freigegebene Modell an und nennen seine ID,
  - der Regler-Modus laedt auch dann kein Modell, wenn der Server auf
    active steht, und kein Clientfeld hebt die Trennung auf,
  - die Ligastufendiagnose trennt angewandte Korrektur, Liga ohne
    Parameter und fehlende Zuordnung, gerade fuer die fuenf bekannten
    offenen Vereine,
  - ein ungueltiges Bundle faellt kontrolliert auf V0 zurueck -
    ausschliesslich in einer isolierten Registry.

Alle Aktivierungen laufen ueber `c21.isolated_activation` in einem
temporaeren Verzeichnis; die echte Registry wird nicht beruehrt.
"""

import json
import os

import pytest

from src.ml import c20_temporal_map as c20
from src.ml import c21_release_readiness as rr
from src.ml import c21_season_validation as c21
from src.ml import model_registry as mr

ROOT = rr._repo_root()
KANDIDAT = rr.CANDIDATE_ID

#: Die fuenf Vereine ohne belegbare Zuordnung (C20, Abschnitt 7):
#: Fenerbahce, AEK, LASK, Viking, Sabah.
OFFENE_ZUORDNUNGEN = (613, 1899, 2016, 5720, 10233)


def _json(relativ):
    with open(os.path.join(ROOT, relativ), encoding="utf-8") as datei:
        return json.load(datei)


@pytest.fixture(scope="module")
def kandidat():
    if not os.path.isfile(os.path.join(ROOT, rr.CANDIDATE_PATH)):
        pytest.skip("der C20-Kandidat liegt nicht vor")
    return _json(rr.CANDIDATE_PATH)


@pytest.fixture(scope="module")
def evaluation():
    return _json(c20.EVALUATION_PATH)


@pytest.fixture
def aktiv(monkeypatch):
    """Serverbetriebsart wie im lokalen V2-Betrieb: active, Gewicht 1,0."""
    monkeypatch.setenv("FOOTSIM_ML_MODE", "active")
    monkeypatch.setenv("FOOTSIM_ML_WEIGHT", "1.0")


@pytest.fixture
def client(aktiv, monkeypatch):
    """
    Echter Testclient mit gueltigem CSRF-Token.

    Das Ratenlimit wird fuer die Dauer des Tests abgeschaltet, wie in
    tests/test_browser_smoke.py. Grund: Es zaehlt je Route und IP im
    Speicher des Testprozesses (100 je Stunde). Jeder CSRF-Aufbau laedt
    die Startseite; ohne diese Abschaltung verbrauchten die Tests dieser
    Datei das gemeinsame Budget, und spaetere Tests anderer Dateien
    bekamen 429 (so in der ersten vollstaendigen C22-Suite). Die Tests,
    die das Limit selbst pruefen, bleiben unberuehrt.
    """
    from tests.conftest import mit_csrf

    import app as app_module

    monkeypatch.setitem(app_module.app.config, "RATELIMIT_ENABLED", False)
    monkeypatch.setattr(app_module.limiter, "enabled", False)
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield mit_csrf(c)


def _cl(**extra):
    return {"competition": "cl", "home_team": "Heim", "away_team": "Gast",
            "home_id": 5, "away_id": 57, "season": 2025, "simulations": 300,
            "use_seed": True, **extra}


# ---------------------------------------------------------------------------
# 1. Serverbetriebsart active
# ---------------------------------------------------------------------------

class TestServerbetriebsart:

    def test_einzelspiel_ohne_approach_folgt_dem_server(
            self, client, kandidat, evaluation):
        with c21.isolated_activation(kandidat, evaluation):
            antwort = client.post("/api/simulate", json=_cl())
        ml = antwort.get_json()["ml"]
        assert antwort.status_code == 200
        assert (ml["mode"], ml["applied"], ml["model_id"]) == (
            "active", True, KANDIDAT)

    def test_saisonpfad_nennt_modell_und_wirkung(self, aktiv, kandidat,
                                                 evaluation):
        from src.features.strength_provider import get_cl_team_strengths
        from src.predict import cl_season_sim as css

        _name, stichtag = c21.cutoffs(2025)[0]
        plan = c21.plan_at(2025, stichtag)
        staerken = get_cl_team_strengths(season=2025, cutoff=stichtag)
        with c21.isolated_activation(kandidat, evaluation):
            r = css.simulate_cl_league_phase(plan, simulations=20,
                                             season=2025, seed=1,
                                             strengths=staerken)
        ml = r["ml"]
        assert ml["mode"] == "active"
        assert ml["applied"] is True
        assert ml["model_id"] == KANDIDAT
        assert ml["model_ids"] == [KANDIDAT]
        assert ml["fixtures_with_ml"] == ml["fixtures_total"] == 144
        stufe = ml["league_stage"]
        # Alle Teilnehmer 2025/26 stehen in der Karte des Kandidaten, und
        # jede ihrer Ligen hat gelernte Parameter: Das Produktionsmodell
        # ist auf allen drei Saisons geschaetzt. (Die C21-Foldmodelle
        # kannten weniger Ligen; dort kam der Fall vor.)
        assert stufe["teams_not_in_map"] == []
        assert stufe["leagues_without_parameters"] == []
        assert stufe["applied_full_parameters"] == 144

    def test_saisonpfad_ohne_ml_nennt_kein_modell(self, monkeypatch):
        from src.features.strength_provider import get_cl_team_strengths
        from src.predict import cl_season_sim as css

        monkeypatch.setenv("FOOTSIM_ML_MODE", "off")
        _name, stichtag = c21.cutoffs(2025)[0]
        plan = c21.plan_at(2025, stichtag)
        staerken = get_cl_team_strengths(season=2025, cutoff=stichtag)
        ml = css.simulate_cl_league_phase(plan, simulations=5, season=2025,
                                          seed=1, strengths=staerken)["ml"]
        assert (ml["applied"], ml["model_id"], ml["model_ids"]) == (
            False, None, [])


# ---------------------------------------------------------------------------
# 2. Der Regler-Modus bleibt getrennt
# ---------------------------------------------------------------------------

class TestReglerTrennung:

    def test_regler_laedt_kein_modell_trotz_aktivem_server(
            self, client, kandidat, evaluation, monkeypatch):
        from src.ml import inference as inf

        geladen = []
        echt = inf.load_model

        def _zaehlend(*a, **kw):
            geladen.append(1)
            return echt(*a, **kw)

        monkeypatch.setattr(inf, "load_model", _zaehlend)
        with c21.isolated_activation(kandidat, evaluation):
            antwort = client.post("/api/simulate", json=_cl(
                approach="custom",
                factors={"home_strength": 1.1, "away_strength": 0.9}))
        ml = antwort.get_json()["ml"]
        assert antwort.status_code == 200
        assert (ml["mode"], ml["applied"], ml["model_id"]) == (
            "off", False, None)
        assert geladen == []

    @pytest.mark.parametrize("zusatz", [
        {"approach": "custom", "ml_weight": 0.5},
        {"approach": "ml", "factors": {"home_strength": 1.2}},
        {"approach": "ml", "ml_weight": 1.0},
        {"approach": "ml_force"},
    ])
    def test_unzulaessige_clientfelder_werden_abgewiesen(self, client,
                                                         zusatz):
        assert client.post("/api/simulate",
                           json=_cl(**zusatz)).status_code == 400

    def test_fremde_felder_heben_die_trennung_nicht_auf(
            self, client, kandidat, evaluation):
        with c21.isolated_activation(kandidat, evaluation):
            antwort = client.post("/api/simulate", json=_cl(
                approach="custom", factors={"home_strength": 1.0},
                ml_mode="active", FOOTSIM_ML_MODE="active"))
        ml = antwort.get_json()["ml"]
        assert antwort.status_code == 200
        assert ml["mode"] == "off"
        assert ml["model_id"] is None

    def test_der_saisonendpunkt_liest_keine_ml_parameter(self):
        """
        GEAENDERT IN C23: Der Endpunkt nimmt jetzt einen Ansatz an - aber
        nur ueber die zentrale Pruefung (cl_custom_factors.
        parse_season_options), die ml_weight ausdruecklich abweist. Der
        Endpunkt selbst liest weiterhin kein ML-Feld und keine Umgebung.
        Geprueft wird der Code ohne Kommentarzeilen; der Kommentar ueber
        dem Parseraufruf nennt den Ansatz beim Namen.
        """
        import inspect

        import app as app_module

        quelltext = inspect.getsource(app_module.api_cl_season_sim)
        code = "\n".join(zeile for zeile in quelltext.splitlines()
                         if not zeile.strip().startswith("#"))
        assert "parse_season_simulation_options(request.args)" in code
        for feld in ("approach", "ml_weight", "ml_mode", "FOOTSIM_ML"):
            assert feld not in code


# ---------------------------------------------------------------------------
# 3. Ligastufendiagnose auf dem freigegebenen Bundle
# ---------------------------------------------------------------------------

class TestLigastufendiagnose:

    @pytest.mark.parametrize("verein", OFFENE_ZUORDNUNGEN)
    def test_die_fuenf_offenen_zuordnungen(self, kandidat, verein):
        from src.ml import inference as inf

        block = kandidat["league_strength"]
        assert str(verein) not in block["team_leagues"]
        heim, gast, diagnose = inf._ligastaerke_anwenden(
            block, {"team_id": verein}, {"team_id": 5}, 1.1, 0.9)
        assert diagnose["status"] == "team_not_in_map"
        assert diagnose["home_status"] == "team_not_in_map"
        assert diagnose["away_status"] == "applied"
        assert diagnose["applied"] is False
        assert (heim, gast) == (1.1, 0.9)

    def test_im_kandidaten_hat_jede_zugeordnete_liga_parameter(
            self, kandidat):
        block = kandidat["league_strength"]
        parameter = set(block["attack"]) | set(block["defence"])
        assert set(block["team_leagues"].values()) <= parameter

    def test_liga_ohne_parameter_ist_etwas_anderes(self, kandidat):
        """
        Der Kaltstart einer LIGA (bekannt, aber ohne gelernte Parameter)
        bleibt vom fehlenden VEREIN unterscheidbar. Im Kandidaten kommt
        er nicht vor; geprueft an einer Kopie seines Blocks, der die
        Parameter der PL fehlen.
        """
        import copy

        from src.ml import inference as inf

        block = copy.deepcopy(kandidat["league_strength"])
        block["attack"].pop("PL")
        block["defence"].pop("PL")
        heim, _g, diagnose = inf._ligastaerke_anwenden(
            block, {"team_id": 57}, {"team_id": 5}, 1.0, 1.0)
        assert diagnose["home_status"] == "league_without_parameters"
        assert diagnose["status"] == "league_without_parameters"
        assert diagnose["applied"] is True

    def test_volle_korrektur(self, kandidat):
        from src.ml import inference as inf

        _h, _g, diagnose = inf._ligastaerke_anwenden(
            kandidat["league_strength"], {"team_id": 5}, {"team_id": 57},
            1.0, 1.0)
        assert (diagnose["status"], diagnose["applied"]) == ("applied", True)


# ---------------------------------------------------------------------------
# 4. Ungueltiges Bundle: kontrollierter Rueckfall, nur isoliert
# ---------------------------------------------------------------------------

class TestRueckfall:

    def _verfaelschen(self, wurzel, weise):
        pfad = os.path.join(wurzel, rr.CANDIDATE_PATH)
        if weise == "hash":
            with open(pfad, "a", encoding="utf-8") as datei:
                datei.write(" ")
        else:
            with open(pfad, "w", encoding="utf-8") as datei:
                datei.write("{kein gueltiges bundle")

    @pytest.mark.parametrize("weise", ["hash", "json"])
    def test_ungueltiges_bundle_faellt_auf_v0_zurueck(
            self, client, kandidat, evaluation, monkeypatch, weise):
        from src.ml import inference as inf

        with c21.isolated_activation(kandidat, evaluation) as iso:
            self._verfaelschen(iso["root"], weise)
            inf.reset_model_cache()
            mit = client.post("/api/simulate", json=_cl(approach="ml"))
        monkeypatch.setenv("FOOTSIM_ML_MODE", "off")
        ohne = client.post("/api/simulate", json=_cl())

        assert mit.status_code == 200 and ohne.status_code == 200
        ml = mit.get_json()["ml"]
        assert ml["applied"] is False
        assert ml["fallback_reason"]
        assert (ml["final_lambda_home"], ml["final_lambda_away"]) == (
            ml["baseline_lambda_home"], ml["baseline_lambda_away"])
        # Die Nutzerzahlen sind exakt die der klassischen Engine.
        for feld in ("home_win_probability", "draw_probability",
                     "away_win_probability", "expected_home_goals",
                     "expected_away_goals"):
            assert mit.get_json()[feld] == ohne.get_json()[feld], feld

    def test_die_echte_registry_bleibt_unberuehrt(self):
        from tests import live_registry_state as live

        assert mr.registry_fingerprint(mr.load_registry()) == \
            live.REGISTRY_FP
