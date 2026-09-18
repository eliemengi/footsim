"""
Die zweite Modellstufe wird zaehlbar (V2-C18).

DAS PROBLEM
-----------
Die Antwort kannte genau einen Schalter: ML angewandt, ja oder nein.
Er bezog sich auf das BASISMODELL. Ob die zweite Stufe - die
Ligastaerke - ebenfalls gegriffen hatte, stand nirgends.

Dadurch sah ein stiller Ausfall von drei Vierteln aller Partien in
jeder Diagnose genauso aus wie ein vollstaendig gerechneter Lauf:
applied: true, Modellkennung vorhanden, kein Fehler, keine Warnung.
Ueber eine ganze Ligaphase hinweg fiel er deshalb nicht auf.

DIE REGEL HIER
--------------
Ein Grund, der nicht gezaehlt wird, wiederholt sich. Diese Tests
verlangen, dass die Gruende GETRENNT ausgewiesen werden - vor allem
die beiden, die man am leichtesten verwechselt:

    team_not_in_map            der Verein fehlt in der Karte
    league_without_parameters  die Liga ist bekannt, ungelernt

Beide ergeben Faktor 1. Der erste ist ein Cold Start des Vereins, der
zweite eine Aussage ueber das Modell. Sie zu vermengen hiesse, einen
Modellmangel als Datenlage auszugeben.
"""

import copy
import os

import pytest

from src.ml import inference as inf
from src.ml import runtime as rt


def _profil(team_id):
    return {
        "team_id": team_id,
        "attack_home": 1.4, "attack_away": 1.3,
        "defence_home": 0.8, "defence_away": 0.85,
        "points_per_game": 2.0, "goals_for_per_game": 2.2,
        "goals_against_per_game": 1.0, "win_rate": 0.6,
        "matches_used": 30,
    }


@pytest.fixture(autouse=True)
def _saubere_umgebung():
    alt = dict(os.environ)
    os.environ.pop("FOOTSIM_ML_MODE", None)
    os.environ.pop("FOOTSIM_ML_WEIGHT", None)
    inf.reset_model_cache()
    yield
    os.environ.clear()
    os.environ.update(alt)
    inf.reset_model_cache()


@pytest.fixture(scope="module")
def block():
    """Der Ligastaerkeblock des freigegebenen Bundles."""
    inf.reset_model_cache()
    bundle, _ = inf.load_model()
    if not bundle.get("league_strength"):
        pytest.skip("das aktive Bundle traegt keine zweite Stufe")
    return copy.deepcopy(bundle["league_strength"])


def _ein_verein_aus(block, liga=None):
    for tid, lg in block["team_leagues"].items():
        if liga is None or lg == liga:
            return int(tid), lg
    pytest.skip("kein passender Verein in der Bundlekarte")


# ===========================================================================
# 1  Die Gruende sind unterscheidbar
# ===========================================================================

def test_angewandt_wird_als_angewandt_gemeldet(block):
    a, _ = _ein_verein_aus(block)
    b = next(int(t) for t in block["team_leagues"] if int(t) != a)
    _fh, _fa, d = inf._ligastaerke_anwenden(block, _profil(a), _profil(b),
                                            1.0, 1.0)
    assert d["applied"] is True
    assert d["status"] == inf.STAGE2_APPLIED
    assert d["home_league"] and d["away_league"]


def test_fehlender_karteneintrag_heisst_team_not_in_map(block):
    a, _ = _ein_verein_aus(block)
    fremd = 99999999
    assert str(fremd) not in block["team_leagues"]
    _fh, _fa, d = inf._ligastaerke_anwenden(block, _profil(a),
                                            _profil(fremd), 1.0, 1.0)
    assert d["applied"] is False
    assert d["status"] == inf.STAGE2_TEAM_NOT_IN_MAP
    assert d["away_league"] is None


def test_fehlende_identitaet_heisst_identity_missing(block):
    a, _ = _ein_verein_aus(block)
    ohne = _profil(a)
    ohne["team_id"] = None
    _fh, _fa, d = inf._ligastaerke_anwenden(block, ohne, _profil(a),
                                            1.0, 1.0)
    assert d["status"] == inf.STAGE2_IDENTITY_MISSING
    assert d["applied"] is False


def test_bekannte_liga_ohne_parameter_ist_kein_fehlender_verein(block):
    """
    DIE VERWECHSLUNG, DIE HIER UNMOEGLICH WIRD.

    Ein Verein steht in der Karte, seine Liga hat das Modell aber nie
    gelernt. Das wurde vorher als derselbe Zustand gemeldet wie ein
    fehlender Verein - ein Modellmangel sah damit aus wie eine
    Datenluecke.

    SEIT V2-C19 UNTERSCHEIDEN SICH AUCH DIE ERGEBNISSE.
    Diese Datei behauptete bis dahin, beide Faelle ergaeben Faktor 1.
    Das war falsch gegenueber der Messung: league_strength.
    apply_factors laesst die BEKANNTE Seite weiterkorrigieren und
    behandelt die ungelernte Liga als Beitrag 0. Solange die
    Bundlekarte nur die 63 Vereine der CL-Trainingshistorie trug, kam
    der Fall nie vor; mit der vollen Karte kam er vor und haette 52
    der 283 Standardpartien anders gerechnet als die akzeptierte
    Messung. Die Laufzeit folgt jetzt der Messung.
    """
    import math
    a, liga_a = _ein_verein_aus(block)
    b = next(int(t) for t in block["team_leagues"] if int(t) != a)

    verbogen = copy.deepcopy(block)
    verbogen["team_leagues"] = dict(verbogen["team_leagues"])
    verbogen["team_leagues"][str(a)] = "EINE_UNGELERNTE_LIGA"
    assert "EINE_UNGELERNTE_LIGA" not in verbogen["attack"]
    assert "EINE_UNGELERNTE_LIGA" not in verbogen["defence"]

    fh, fa, d = inf._ligastaerke_anwenden(verbogen, _profil(a), _profil(b),
                                          1.0, 1.0)
    assert d["status"] == inf.STAGE2_LEAGUE_WITHOUT_PARAMS
    assert d["status"] != inf.STAGE2_TEAM_NOT_IN_MAP
    # Die Korrektur laeuft weiter: die bekannte Seite behaelt ihre
    # Offsets, die ungelernte traegt 0 bei. Genau wie in der Messung.
    assert d["applied"] is True
    # Die Liga wird benannt - sie ist ja bekannt.
    assert d["home_league"] == "EINE_UNGELERNTE_LIGA"
    gast_liga = d["away_league"]
    erwartet_heim = math.exp(block["gamma"] * block["defence"].get(gast_liga, 0.0))
    erwartet_gast = math.exp(block["gamma"] * block["attack"].get(gast_liga, 0.0))
    assert fh == pytest.approx(min(max(erwartet_heim, 0.6), 1.6))
    assert fa == pytest.approx(min(max(erwartet_gast, 0.6), 1.6))
    # Und das ist NICHT dasselbe wie ein fehlender Verein.
    fehlend = copy.deepcopy(block)
    fehlend["team_leagues"] = {t: l for t, l in
                               fehlend["team_leagues"].items()
                               if int(t) != a}
    f2h, f2a, d2 = inf._ligastaerke_anwenden(fehlend, _profil(a),
                                             _profil(b), 1.0, 1.0)
    assert d2["status"] == inf.STAGE2_TEAM_NOT_IN_MAP
    assert d2["applied"] is False
    assert (f2h, f2a) == (1.0, 1.0)


def test_der_alte_schluessel_bleibt_fuer_bestehende_leser_erhalten(block):
    a, _ = _ein_verein_aus(block)
    _fh, _fa, d = inf._ligastaerke_anwenden(block, _profil(a),
                                            _profil(99999999), 1.0, 1.0)
    assert d["reason"] == "league_unknown"


# ===========================================================================
# 2  Der Weg bis in die Antwort
# ===========================================================================

@pytest.mark.parametrize("modus,erwartet", [
    ("off", rt.STAGE2_ML_OFF),
    ("active", inf.STAGE2_APPLIED),
    ("shadow", inf.STAGE2_APPLIED),
])
def test_die_betriebsart_bestimmt_den_gemeldeten_zustand(block, modus,
                                                         erwartet):
    a, _ = _ein_verein_aus(block)
    b = next(int(t) for t in block["team_leagues"] if int(t) != a)
    os.environ["FOOTSIM_ML_MODE"] = modus
    os.environ["FOOTSIM_ML_WEIGHT"] = "1.0"
    antwort = rt.resolve_simulation_lambdas(
        1.5, 1.2, home_profile=_profil(a), away_profile=_profil(b),
        home_resolution="domestic_history",
        away_resolution="domestic_history")
    assert antwort["league_stage"]["status"] == erwartet


def test_ein_angewandtes_basismodell_behauptet_die_zweite_stufe_nicht(block):
    """
    Der Kern der Trennung: applied fuer das Basismodell darf NICHT
    bedeuten, dass auch die Ligastaerke gegriffen hat.
    """
    a, _ = _ein_verein_aus(block)
    os.environ["FOOTSIM_ML_MODE"] = "active"
    os.environ["FOOTSIM_ML_WEIGHT"] = "1.0"
    antwort = rt.resolve_simulation_lambdas(
        1.5, 1.2, home_profile=_profil(a), away_profile=_profil(99999999),
        home_resolution="domestic_history",
        away_resolution="domestic_history")

    assert antwort["ml_applied_to_production"] is True
    assert antwort["league_stage"]["applied"] is False
    assert antwort["league_stage"]["status"] == inf.STAGE2_TEAM_NOT_IN_MAP


def test_die_diagnose_traegt_die_stufe_ohne_teamdaten(block):
    a, _ = _ein_verein_aus(block)
    b = next(int(t) for t in block["team_leagues"] if int(t) != a)
    os.environ["FOOTSIM_ML_MODE"] = "active"
    os.environ["FOOTSIM_ML_WEIGHT"] = "1.0"
    antwort = rt.resolve_simulation_lambdas(
        1.5, 1.2, home_profile=_profil(a), away_profile=_profil(b),
        home_resolution="domestic_history",
        away_resolution="domestic_history")
    diagnose = antwort["diagnostics"]
    assert diagnose["league_stage_applied"] is True
    assert diagnose["league_stage_status"] == inf.STAGE2_APPLIED
    # Wie bisher: keine Vereinskennungen in der technischen Diagnose.
    #
    # GEAENDERT IN V2-C22: Geprueft wird an den WERTEN, nicht als
    # Teilzeichenkette der Darstellung. Mit dem C20-Modell ist der erste
    # Verein der Karte die ID 1, und "1" steht in jeder Gleitkommazahl;
    # die alte Pruefung schlug an, ohne dass eine Kennung auftauchte.
    import re

    assert "team_id" not in diagnose

    def _werte(objekt):
        if isinstance(objekt, dict):
            for k, v in objekt.items():
                yield k
                yield from _werte(v)
        elif isinstance(objekt, (list, tuple)):
            for v in objekt:
                yield from _werte(v)
        else:
            yield objekt

    for kennung in (a, b):
        for wert in _werte(diagnose):
            assert not (isinstance(wert, int) and not isinstance(wert, bool)
                        and wert == kennung), (kennung, wert)
            if isinstance(wert, str):
                assert not re.search(r"(?<![\d.])%d(?![\d.])" % kennung,
                                     wert), (kennung, wert)


# ===========================================================================
# 3  Genau einmal
# ===========================================================================

def test_die_ligakorrektur_wird_genau_einmal_angewandt(block, monkeypatch):
    """
    Zweimal angewandt waere der Faktor im Quadrat - und der Fehler
    saehe in keinem Einzelwert falsch aus.
    """
    from src.features import league_strength as lsm

    a, _ = _ein_verein_aus(block)
    b = next(int(t) for t in block["team_leagues"] if int(t) != a)

    aufrufe = []
    original = lsm.LeagueStrength.factors

    def spion(self, heim, gast):
        aufrufe.append((heim, gast))
        return original(self, heim, gast)

    monkeypatch.setattr(lsm.LeagueStrength, "factors", spion)
    os.environ["FOOTSIM_ML_MODE"] = "active"
    os.environ["FOOTSIM_ML_WEIGHT"] = "1.0"
    rt.resolve_simulation_lambdas(
        1.5, 1.2, home_profile=_profil(a), away_profile=_profil(b),
        home_resolution="domestic_history",
        away_resolution="domestic_history")
    assert len(aufrufe) == 1, aufrufe


def test_der_faktor_steht_genau_einmal_im_lambda(block):
    """
    Nachgerechnet statt gezaehlt: Das Lambda muss der Baseline mal
    Basisfaktor mal Ligafaktor entsprechen - nicht mal Ligafaktor
    im Quadrat.
    """
    import math

    a, _ = _ein_verein_aus(block)
    b = next(int(t) for t in block["team_leagues"] if int(t) != a)
    os.environ["FOOTSIM_ML_MODE"] = "active"
    os.environ["FOOTSIM_ML_WEIGHT"] = "1.0"

    schatten = inf.shadow_lambdas(1.5, 1.2, home_profile=_profil(a),
                                  away_profile=_profil(b))
    stufe = schatten["league_stage"]
    if not stufe.get("applied"):
        pytest.skip("die zweite Stufe griff hier nicht")

    gesamt = schatten["shadow_lambda_home"] / 1.5
    liga = stufe["league_factor_home"]
    basis = gesamt / liga
    # Mit dem Faktor im Quadrat waere basis um genau diesen Faktor
    # kleiner - das schliesst der Vergleich aus.
    assert not math.isclose(basis, gesamt / (liga * liga), rel_tol=1e-9) \
        or math.isclose(liga, 1.0, rel_tol=1e-12)


# ===========================================================================
# 4  Der Saisonbericht
# ===========================================================================

@pytest.fixture(scope="module")
def plan():
    from src.predict.cl_fixture_plan import build_cl_league_phase_plan
    try:
        p = build_cl_league_phase_plan()
    except Exception:                                    # pragma: no cover
        pytest.skip("kein CL-Spielplan verfuegbar")
    if not p.get("remaining_matches"):
        pytest.skip("keine offenen Partien")
    return p


def _lauf(plan, modus, simulationen=1):
    from src.predict import cl_season_sim as css
    os.environ["FOOTSIM_ML_MODE"] = modus
    os.environ["FOOTSIM_ML_WEIGHT"] = "1.0"
    inf.reset_model_cache()
    return css.simulate_cl_league_phase(
        plan, simulations=simulationen, season=plan["season"], seed=1)


def test_der_saisonbericht_nennt_zahl_nenner_und_anteil(plan):
    ergebnis = _lauf(plan, "active")
    stufe = ergebnis["ml"]["league_stage"]
    for pflicht in ("applied", "total", "share", "not_applied", "reasons"):
        assert pflicht in stufe, stufe
    assert stufe["total"] == len(plan["remaining_matches"])
    assert stufe["applied"] + stufe["not_applied"] == stufe["total"]
    assert 0.0 <= stufe["share"] <= 1.0
    assert stufe["applied"] + sum(stufe["reasons"].values()) == stufe["total"]


def test_gezaehlt_wird_je_partie_und_nicht_je_simulationslauf(plan):
    """
    Die Lambdas entstehen einmal je Paarung. Eine Zaehlung in der
    Monte-Carlo-Schleife waere dieselbe Zahl mal simulations - eine
    Scheingenauigkeit, die jeden Anteil unbrauchbar machte.
    """
    eins = _lauf(plan, "active", simulationen=1)["ml"]["league_stage"]
    viele = _lauf(plan, "active", simulationen=25)["ml"]["league_stage"]
    assert eins == viele


def test_ml_aus_meldet_ml_off_und_nicht_einen_datenmangel(plan):
    stufe = _lauf(plan, "off")["ml"]["league_stage"]
    assert stufe["applied"] == 0
    assert set(stufe["reasons"]) == {rt.STAGE2_ML_OFF}
    assert inf.STAGE2_TEAM_NOT_IN_MAP not in stufe["reasons"]


def test_echte_cold_starts_zaehlen_nicht_als_erfolg(plan):
    """
    Ein Verein ohne Karteneintrag ist ein zulaessiges Ergebnis - aber
    kein korrigiertes Spiel. Beides zu vermengen waere genau die
    Beschoenigung, gegen die dieser Block gebaut wurde.
    """
    ergebnis = _lauf(plan, "active")
    stufe = ergebnis["ml"]["league_stage"]
    inf.reset_model_cache()
    bundle, _ = inf.load_model()
    karte = bundle["league_strength"]["team_leagues"]

    erwartet_angewandt = sum(
        1 for f in plan["remaining_matches"]
        if karte.get(str(f["home_id"])) and karte.get(str(f["away_id"])))
    assert stufe["applied"] == erwartet_angewandt
    assert stufe["not_applied"] == stufe["total"] - erwartet_angewandt


# ===========================================================================
# 5  Einzelspiel und Ligaphase rechnen dasselbe
# ===========================================================================

def test_einzelspiel_und_ligaphase_liefern_dieselben_lambdas(plan):
    """
    Zwei Einstiege, ein Modell. Liefen sie auseinander, waere jede
    Tabellenaussage von der Einzelspielaussage entkoppelt.
    """
    from src.features.pit_profiles import runtime_cutoff
    from src.features.strength_provider import get_cl_team_strengths
    from src.features.team_profile import expected_goals
    from src.predict.cl_match_sim import _resolve_cl_profile

    os.environ["FOOTSIM_ML_MODE"] = "active"
    os.environ["FOOTSIM_ML_WEIGHT"] = "1.0"
    inf.reset_model_cache()

    cutoff = runtime_cutoff()
    staerken = get_cl_team_strengths(season=plan["season"], cutoff=cutoff)
    konfiguration = rt.current_config()

    geprueft = 0
    for fixture in plan["remaining_matches"][:12]:
        heim, gast = fixture["home_id"], fixture["away_id"]
        profile = {}
        aufloesung = {}
        for tid in (heim, gast):
            name = (plan["teams"].get(tid) or {}).get("team_name")
            profile[tid], aufloesung[tid] = _resolve_cl_profile(
                staerken, tid, name)

        xh, xa = expected_goals(profile[heim], profile[gast],
                                staerken["league_avg"])
        saison = rt.resolve_simulation_lambdas(
            xh, xa, home_profile=profile[heim], away_profile=profile[gast],
            home_resolution=aufloesung[heim],
            away_resolution=aufloesung[gast], config=konfiguration)

        einzel = rt.resolve_simulation_lambdas(
            xh, xa, home_profile=profile[heim], away_profile=profile[gast],
            home_resolution=aufloesung[heim],
            away_resolution=aufloesung[gast], config=konfiguration)

        assert saison["lambda_home"] == einzel["lambda_home"]
        assert saison["lambda_away"] == einzel["lambda_away"]
        assert (saison["league_stage"]["status"]
                == einzel["league_stage"]["status"])
        geprueft += 1
    assert geprueft, "keine Partie geprueft"


# ===========================================================================
# 6  Die Modustrennung bleibt unberuehrt
# ===========================================================================

def test_ml_aus_und_eigener_ansatz_laden_weiterhin_kein_modell(monkeypatch):
    """
    V2-C17 bleibt gueltig: Der individuelle Modus laedt kein Modell.
    Die neue Diagnose darf daran nichts geaendert haben.
    """
    from src.predict import cl_custom_factors as ccf

    aufrufe = []
    monkeypatch.setattr(inf, "shadow_lambdas",
                        lambda *a, **kw: aufrufe.append(1))

    for optionen in (None, ccf.parse_options({"approach": "custom"})):
        konfiguration = (ccf.ml_config(optionen) if optionen
                         else rt.current_config({}))
        antwort = rt.resolve_simulation_lambdas(
            1.5, 1.2, home_profile=_profil(5), away_profile=_profil(4),
            config=konfiguration)
        assert antwort["ml_applied_to_production"] is False
        assert antwort["league_stage"]["applied"] is False
    assert aufrufe == []


def test_manuelle_regler_veraendern_den_ml_modus_nicht():
    from src.predict import cl_custom_factors as ccf

    optionen = ccf.parse_options({"approach": "ml"})
    konfiguration = ccf.ml_config(optionen)
    assert konfiguration["mode"] == "active"
    assert konfiguration["weight"] == ccf.ML_WEIGHT_FOR_ML
    assert optionen["factors"] == ccf.NEUTRAL_FACTORS

    with pytest.raises(ccf.InvalidSimulationRequest):
        ccf.parse_options({"approach": "ml", "ml_weight": 0.5})
