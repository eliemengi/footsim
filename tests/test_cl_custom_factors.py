"""
Tests fuer die individuellen Faktoren der CL-Einzelspielsimulation.

Zwei Zusagen muessen halten, und beide lassen sich verletzen, ohne dass
eine Zahl auffaellig aussieht:

  1. Neutrale Faktoren rechnen bitgleich die bestehende Baseline.
  2. Kein Request veraendert den prozessweiten Profilcache - sonst
     verfaelschte ein Nutzer stillschweigend die Simulationen aller
     anderen.

Deshalb steht zu jedem Reglereffekt eine Gegenprobe und zu jedem
Fehlerfall ein ausdruecklich provozierter Test.
"""

import copy
import math

import pytest

from src.features.team_profile import expected_goals
from src.predict import cl_custom_factors as ccf

NEUTRAL = ccf.NEUTRAL_FACTORS


def _profil(attack_h=1.10, attack_a=1.05, def_h=0.95, def_a=0.90):
    """Ein Profil mit Werten weit innerhalb der XG-Grenzen."""
    return {
        "team_id": 1, "team_name": "Test",
        "attack_home": attack_h, "attack_away": attack_a,
        "defence_home": def_h, "defence_away": def_a,
        "points_per_game": 1.8, "goals_for_per_game": 1.7,
        "goals_against_per_game": 1.1, "win_rate": 0.55,
        "matches_used": 30,
        "stats": {"matches": 30, "goals_for": 51},
    }


def _avg():
    return {"home_goals": 1.55, "away_goals": 1.25, "total_goals": 2.80,
            "matches": 100}


def _lambdas(faktoren):
    heim, gast, schnitt = ccf.apply_factors(_profil(), _profil(0.95, 0.90),
                                            _avg(), faktoren)
    return expected_goals(heim, gast, schnitt)


def _f(**kwargs):
    faktoren = dict(NEUTRAL)
    faktoren.update(kwargs)
    return faktoren


# ---------------------------------------------------------------------------
# 1. Neutralitaet
# ---------------------------------------------------------------------------

class TestNeutralitaet:

    def test_neutrale_faktoren_lassen_die_werte_unveraendert(self):
        heim, gast, schnitt = ccf.apply_factors(_profil(), _profil(),
                                                _avg(), NEUTRAL)
        assert heim == _profil()
        assert gast == _profil()
        assert schnitt == _avg()

    def test_neutrale_faktoren_ergeben_die_baseline_bitgleich(self):
        basis = expected_goals(_profil(), _profil(0.95, 0.90), _avg())
        assert _lambdas(NEUTRAL) == basis

    def test_der_neutrale_stand_ist_ueberall_eins(self):
        assert set(NEUTRAL) == set(ccf.FACTOR_BOUNDS)
        assert all(wert == 1.0 for wert in NEUTRAL.values())

    def test_is_neutral_erkennt_den_stand(self):
        assert ccf.is_neutral(NEUTRAL) is True
        assert ccf.is_neutral(_f(attack=1.1)) is False
        assert ccf.is_neutral({}) is True


# ---------------------------------------------------------------------------
# 2. Offensive
# ---------------------------------------------------------------------------

class TestOffensive:

    def test_hoeherer_faktor_hebt_beide_lambdas(self):
        basis = _lambdas(NEUTRAL)
        hoch = _lambdas(_f(attack=1.3))
        assert hoch[0] > basis[0]
        assert hoch[1] > basis[1]

    def test_niedrigerer_faktor_senkt_beide_lambdas(self):
        basis = _lambdas(NEUTRAL)
        tief = _lambdas(_f(attack=0.7))
        assert tief[0] < basis[0]
        assert tief[1] < basis[1]

    def test_die_wirkung_ist_genau_der_faktor(self):
        """Kein doppelter Durchgriff - beide Lambdas skalieren um f."""
        basis = _lambdas(NEUTRAL)
        for f in (0.7, 0.9, 1.1, 1.3):
            neu = _lambdas(_f(attack=f))
            assert neu[0] == pytest.approx(basis[0] * f, rel=1e-12)
            assert neu[1] == pytest.approx(basis[1] * f, rel=1e-12)

    def test_er_ist_monoton(self):
        werte = [_lambdas(_f(attack=f))[0] for f in (0.7, 0.85, 1.0, 1.15, 1.3)]
        assert werte == sorted(werte)


# ---------------------------------------------------------------------------
# 3. Defensive
# ---------------------------------------------------------------------------

class TestDefensive:

    def test_staerkere_defensive_senkt_die_lambdas(self):
        """Nutzerbedeutung: hoeherer Wert = bessere Abwehr = weniger Tore."""
        basis = _lambdas(NEUTRAL)
        stark = _lambdas(_f(defence=1.3))
        assert stark[0] < basis[0]
        assert stark[1] < basis[1]

    def test_schwaechere_defensive_hebt_die_lambdas(self):
        basis = _lambdas(NEUTRAL)
        schwach = _lambdas(_f(defence=0.7))
        assert schwach[0] > basis[0]
        assert schwach[1] > basis[1]

    def test_die_wirkung_ist_genau_der_kehrwert(self):
        basis = _lambdas(NEUTRAL)
        for f in (0.7, 0.9, 1.1, 1.3):
            neu = _lambdas(_f(defence=f))
            assert neu[0] == pytest.approx(basis[0] / f, rel=1e-12)
            assert neu[1] == pytest.approx(basis[1] / f, rel=1e-12)

    def test_das_profilfeld_wird_geteilt_nicht_multipliziert(self):
        heim, _, _ = ccf.apply_factors(_profil(), _profil(), _avg(),
                                       _f(defence=1.25))
        assert heim["defence_home"] == pytest.approx(0.95 / 1.25)
        assert heim["defence_away"] == pytest.approx(0.90 / 1.25)

    def test_er_ist_monoton_fallend(self):
        werte = [_lambdas(_f(defence=f))[0]
                 for f in (0.7, 0.85, 1.0, 1.15, 1.3)]
        assert werte == sorted(werte, reverse=True)


# ---------------------------------------------------------------------------
# 4. Offensive und Defensive teilen einen Freiheitsgrad
# ---------------------------------------------------------------------------

class TestOffensiveUndDefensiveZusammen:
    """
    Ein Befund, der festgehalten gehoert: In

        xh = avg_home * attack_home * defence_away

    stehen Angriff und Abwehr im SELBEN Produkt. Der Angriffsfaktor
    multipliziert, der Abwehrfaktor teilt - beide auf dieselbe Groesse.
    Werden sie gleich weit bewegt, heben sie sich exakt auf.

    Das ist kein Fehler der Umsetzung, sondern eine Eigenschaft des
    bestehenden Torerwartungsmodells. Es steht hier als Test, damit es
    niemand spaeter fuer einen Rechenfehler haelt - und damit C8B es
    bei der Reglerbeschriftung beruecksichtigen kann.
    """

    def test_gleiche_faktoren_heben_sich_exakt_auf(self):
        basis = _lambdas(NEUTRAL)
        for f in (0.7, 0.8, 1.2, 1.3):
            neu = _lambdas(_f(attack=f, defence=f))
            assert neu[0] == pytest.approx(basis[0], rel=1e-12)
            assert neu[1] == pytest.approx(basis[1], rel=1e-12)

    def test_massgeblich_ist_ihr_verhaeltnis(self):
        a = _lambdas(_f(attack=1.2, defence=1.0))
        b = _lambdas(_f(attack=1.2 * 0.8, defence=0.8))
        assert a[0] == pytest.approx(b[0], rel=1e-12)


# ---------------------------------------------------------------------------
# 5. Heimvorteil
# ---------------------------------------------------------------------------

class TestHeimvorteil:

    def test_hoeherer_faktor_staerkt_das_heimteam(self):
        basis = _lambdas(NEUTRAL)
        hoch = _lambdas(_f(home_advantage=1.5))
        assert hoch[0] > basis[0]
        assert hoch[1] < basis[1]

    def test_niedrigerer_faktor_staerkt_das_auswaertsteam(self):
        basis = _lambdas(NEUTRAL)
        tief = _lambdas(_f(home_advantage=0.5))
        assert tief[0] < basis[0]
        assert tief[1] > basis[1]

    def test_eins_ist_neutral(self):
        assert _lambdas(_f(home_advantage=1.0)) == _lambdas(NEUTRAL)

    def test_das_produkt_der_schnitte_bleibt_stabil(self):
        """Die Wurzelformel haelt das Torniveau - kein doppelter Effekt."""
        original = _avg()["home_goals"] * _avg()["away_goals"]
        for f in (0.5, 0.75, 1.0, 1.25, 1.5):
            _, _, schnitt = ccf.apply_factors(_profil(), _profil(), _avg(),
                                              _f(home_advantage=f))
            produkt = schnitt["home_goals"] * schnitt["away_goals"]
            assert produkt == pytest.approx(original, rel=1e-12)

    def test_die_formel_ist_die_wurzel(self):
        _, _, schnitt = ccf.apply_factors(_profil(), _profil(), _avg(),
                                          _f(home_advantage=1.44))
        assert schnitt["home_goals"] == pytest.approx(1.55 * 1.2)
        assert schnitt["away_goals"] == pytest.approx(1.25 / 1.2)

    def test_das_verhaeltnis_waechst_monoton(self):
        werte = []
        for f in (0.5, 0.75, 1.0, 1.25, 1.5):
            xh, xa = _lambdas(_f(home_advantage=f))
            werte.append(xh / xa)
        assert werte == sorted(werte)

    def test_keine_division_durch_null(self):
        """Das Minimum ist 0.5 - sqrt(0.5) ist wohldefiniert und > 0."""
        unten, _ = ccf.FACTOR_BOUNDS["home_advantage"]
        assert unten > 0
        assert math.sqrt(unten) > 0
        _, _, schnitt = ccf.apply_factors(_profil(), _profil(), _avg(),
                                          _f(home_advantage=unten))
        assert all(math.isfinite(w) and w > 0
                   for w in (schnitt["home_goals"], schnitt["away_goals"]))


# ---------------------------------------------------------------------------
# 6. Keine Mutation der Quellen
# ---------------------------------------------------------------------------

class TestKeineMutation:

    def test_die_quellprofile_bleiben_unveraendert(self):
        heim, gast, schnitt = _profil(), _profil(0.9), _avg()
        vorher = (copy.deepcopy(heim), copy.deepcopy(gast),
                  copy.deepcopy(schnitt))
        ccf.apply_factors(heim, gast, schnitt,
                          _f(attack=1.3, defence=0.7, home_advantage=1.5))
        assert (heim, gast, schnitt) == vorher

    def test_auch_verschachtelte_felder_bleiben_unveraendert(self):
        """
        Die Kopie ist tief. Ein geteiltes stats-Dict waere ein Weg,
        ueber den ein Request spaeter doch den Cache beruehren koennte.
        """
        heim = _profil()
        kopie, _, _ = ccf.apply_factors(heim, _profil(), _avg(),
                                        _f(attack=1.2))
        kopie["stats"]["matches"] = 999
        assert heim["stats"]["matches"] == 30

    def test_die_rueckgabe_sind_neue_objekte(self):
        heim, gast, schnitt = _profil(), _profil(), _avg()
        a, b, c = ccf.apply_factors(heim, gast, schnitt, NEUTRAL)
        assert a is not heim and b is not gast and c is not schnitt

    def test_die_faktoren_werden_nicht_veraendert(self):
        faktoren = _f(attack=1.2)
        vorher = dict(faktoren)
        ccf.apply_factors(_profil(), _profil(), _avg(), faktoren)
        assert faktoren == vorher


# ---------------------------------------------------------------------------
# 7. Pruefung der Optionen
# ---------------------------------------------------------------------------

class TestOptionen:

    def test_ohne_approach_gibt_es_keine_optionen(self):
        assert ccf.parse_options({"competition": "cl"}) is None
        assert ccf.parse_options({}) is None

    def test_ml_setzt_neutrale_faktoren_und_volles_gewicht(self):
        o = ccf.parse_options({"approach": "ml"})
        assert o["approach"] == "ml"
        assert o["factors"] == NEUTRAL
        assert o["ml_weight"] == 1.0

    def test_custom_beginnt_ohne_ml_einfluss(self):
        o = ccf.parse_options({"approach": "custom"})
        assert o["ml_weight"] == 0.0
        assert o["factors"] == NEUTRAL

    def test_custom_uebernimmt_die_angaben(self):
        o = ccf.parse_options({
            "approach": "custom", "ml_weight": 0.5,
            "factors": {"attack": 1.1, "home_advantage": 1.2}})
        assert o["ml_weight"] == 0.5
        assert o["factors"] == {"attack": 1.1, "defence": 1.0,
                                "home_advantage": 1.2}

    @pytest.mark.parametrize("ansatz", ["baseline", "ML", "", "auto", 1,
                                        True, None if False else "shadow"])
    def test_unbekannter_ansatz_wird_abgewiesen(self, ansatz):
        with pytest.raises(ccf.InvalidSimulationRequest, match="Ansatz"):
            ccf.parse_options({"approach": ansatz})

    @pytest.mark.parametrize("feld", ["factors", "ml_weight"])
    def test_zusatzfelder_ohne_approach_werden_abgewiesen(self, feld):
        with pytest.raises(ccf.InvalidSimulationRequest, match="approach"):
            ccf.parse_options({feld: {} if feld == "factors" else 0.5})

    @pytest.mark.parametrize("feld", ["factors", "ml_weight"])
    def test_zusatzfelder_bei_ml_werden_abgewiesen(self, feld):
        """
        Streng statt still: Ein mitgesendeter Reglerwert, der bei 'ml'
        verworfen wuerde, waere eine unsichtbare Enttaeuschung.
        """
        daten = {"approach": "ml",
                 feld: {"attack": 1.2} if feld == "factors" else 0.5}
        with pytest.raises(ccf.InvalidSimulationRequest, match="nicht zulaessig"):
            ccf.parse_options(daten)

    @pytest.mark.parametrize("roh", ["x", 5, [1], True])
    def test_factors_muss_ein_objekt_sein(self, roh):
        with pytest.raises(ccf.InvalidSimulationRequest, match="Objekt"):
            ccf.parse_options({"approach": "custom", "factors": roh})

    def test_unbekannter_faktor_wird_abgewiesen(self):
        with pytest.raises(ccf.InvalidSimulationRequest, match="Unbekannte"):
            ccf.parse_options({"approach": "custom",
                               "factors": {"offense": 1.2}})

    @pytest.mark.parametrize("name", list(ccf.FACTOR_BOUNDS))
    @pytest.mark.parametrize("wert", ["1.0", True, False, None, [1.0],
                                      {"v": 1}, float("nan"),
                                      float("inf"), float("-inf")])
    def test_ungueltiger_faktorwert(self, name, wert):
        with pytest.raises(ccf.InvalidSimulationRequest, match="Zahl"):
            ccf.parse_options({"approach": "custom", "factors": {name: wert}})

    @pytest.mark.parametrize("name,unten,oben", [
        (n, b[0], b[1]) for n, b in ccf.FACTOR_BOUNDS.items()])
    def test_grenzen_werden_eingehalten(self, name, unten, oben):
        for gueltig in (unten, 1.0, oben):
            o = ccf.parse_options({"approach": "custom",
                                   "factors": {name: gueltig}})
            assert o["factors"][name] == gueltig

        for ungueltig in (unten - 0.0001, oben + 0.0001, -1, 0, 99):
            with pytest.raises(ccf.InvalidSimulationRequest, match="zwischen"):
                ccf.parse_options({"approach": "custom",
                                   "factors": {name: ungueltig}})

    @pytest.mark.parametrize("wert", ["0.5", True, [0.5], float("nan"),
                                      float("inf")])
    def test_ungueltiges_ml_gewicht(self, wert):
        with pytest.raises(ccf.InvalidSimulationRequest, match="ml_weight"):
            ccf.parse_options({"approach": "custom", "ml_weight": wert})

    @pytest.mark.parametrize("wert", [-0.0001, 1.0001, 50, 100, -1])
    def test_ml_gewicht_ausserhalb_der_grenzen(self, wert):
        with pytest.raises(ccf.InvalidSimulationRequest, match="zwischen"):
            ccf.parse_options({"approach": "custom", "ml_weight": wert})

    def test_50_wird_niemals_zu_0_5(self):
        with pytest.raises(ccf.InvalidSimulationRequest):
            ccf.parse_options({"approach": "custom", "ml_weight": 50})

    def test_kein_stilles_clampen(self):
        """Ein Wert knapp ausserhalb wird abgewiesen, nicht gekappt."""
        with pytest.raises(ccf.InvalidSimulationRequest):
            ccf.parse_options({"approach": "custom",
                               "factors": {"attack": 1.31}})

    def test_die_fehlermeldung_verraet_nichts_internes(self):
        for daten in ({"approach": "x"},
                      {"approach": "custom", "factors": {"y": 1}},
                      {"approach": "custom", "ml_weight": 9}):
            try:
                ccf.parse_options(daten)
            except ccf.InvalidSimulationRequest as fehler:
                text = str(fehler)
                for verboten in ("C:\\", "/home/", "Traceback", "coef",
                                 "model", ".json"):
                    assert verboten not in text


# ---------------------------------------------------------------------------
# 8. Die C7-Konfiguration
# ---------------------------------------------------------------------------

class TestMlConfig:

    def test_ohne_optionen_gibt_es_keine_konfiguration(self):
        assert ccf.ml_config(None) is None

    def test_ml_ergibt_active_mit_vollem_gewicht(self):
        c = ccf.ml_config(ccf.parse_options({"approach": "ml"}))
        assert c["mode"] == "active"
        assert c["weight"] == 1.0
        assert c["weight_reason"] is None

    def test_custom_uebernimmt_das_gewicht(self):
        c = ccf.ml_config(ccf.parse_options({"approach": "custom",
                                             "ml_weight": 0.25}))
        assert c["mode"] == "active"
        assert c["weight"] == 0.25

    def test_die_form_passt_zur_runtime(self):
        from src.ml import runtime as rt

        c = ccf.ml_config(ccf.parse_options({"approach": "ml"}))
        assert set(c) == set(rt.current_config({}))

    def test_os_environ_wird_nicht_beruehrt(self):
        import os

        vorher = dict(os.environ)
        ccf.ml_config(ccf.parse_options({"approach": "custom",
                                         "ml_weight": 1.0}))
        assert dict(os.environ) == vorher


# ---------------------------------------------------------------------------
# 9. Kombinationen und Guardrails
# ---------------------------------------------------------------------------

class TestKombinationen:

    @pytest.mark.parametrize("a", [0.7, 1.0, 1.3])
    @pytest.mark.parametrize("d", [0.7, 1.0, 1.3])
    @pytest.mark.parametrize("h", [0.5, 1.0, 1.5])
    def test_jede_kombination_bleibt_endlich_und_positiv(self, a, d, h):
        xh, xa = _lambdas(_f(attack=a, defence=d, home_advantage=h))
        assert math.isfinite(xh) and xh > 0
        assert math.isfinite(xa) and xa > 0

    def test_die_xg_grenzen_gelten_weiterhin(self):
        from src.features import team_profile as tp

        for a in (0.7, 1.3):
            for d in (0.7, 1.3):
                for h in (0.5, 1.5):
                    xh, xa = _lambdas(_f(attack=a, defence=d,
                                         home_advantage=h))
                    assert tp.XG_MIN <= xh <= tp.XG_MAX
                    assert tp.XG_MIN <= xa <= tp.XG_MAX

    def test_extremwerte_sprengen_nichts(self):
        """Selbst ein sehr starkes Profil bleibt in den Grenzen."""
        from src.features import team_profile as tp

        stark = _profil(tp.RATING_MAX, tp.RATING_MAX,
                        tp.RATING_MAX, tp.RATING_MAX)
        heim, gast, schnitt = ccf.apply_factors(
            stark, stark, _avg(), _f(attack=1.3, defence=0.7,
                                     home_advantage=1.5))
        xh, xa = expected_goals(heim, gast, schnitt)
        assert tp.XG_MIN <= xh <= tp.XG_MAX
        assert tp.XG_MIN <= xa <= tp.XG_MAX

    def test_die_grenzen_liegen_innerhalb_der_guardrails(self):
        """
        Kein Reglerwert darf die Sicherheitsgrenzen erreichen koennen -
        die Guardrails sollen im Normalbetrieb gar nicht greifen.
        """
        from src.features import team_profile as tp

        for name, (unten, oben) in ccf.FACTOR_BOUNDS.items():
            assert 0 < unten <= 1.0 <= oben
            assert oben < tp.RATING_MAX
