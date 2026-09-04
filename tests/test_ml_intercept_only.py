"""
Tests fuer das merkmalsfreie Korrekturmodell.

intercept_only ist die Untergrenze jeder denkbaren Rekalibrierung: eine
einzige Zahl, die alle Baseline-Lambdas gemeinsam skaliert. Was die
Diagnosestufe darueber hinaus misst, ist der Beitrag echter Merkmale -
und diese Aussage haengt daran, dass die eine Zahl auch wirklich die
richtige ist.

Deshalb wird sie hier nicht geglaubt, sondern gegen eine direkt
optimierte Offset-Likelihood gerechnet.
"""

import math

import pytest

from src.ml import model as mdl


def zeile(index, lam_home=1.30, lam_away=1.10, tore_home=1, tore_away=1):
    return {
        "row_id": f"t:{index}",
        "baseline_lambda_home": lam_home,
        "baseline_lambda_away": lam_away,
        "home_goals": tore_home,
        "away_goals": tore_away,
    }


def bestand(n=40):
    """Ein Bestand mit streuenden Lambdas UND streuenden Toren."""
    zeilen = []
    for i in range(n):
        zeilen.append(zeile(
            i,
            lam_home=1.05 + 0.05 * (i % 9),
            lam_away=0.85 + 0.04 * (i % 7),
            tore_home=(i * 3) % 5,
            tore_away=(i * 2) % 4,
        ))
    return zeilen


# ---------------------------------------------------------------------------
# 1. Warum es den Sonderfall gibt
# ---------------------------------------------------------------------------

class TestSklearnLehntAb:

    @pytest.mark.parametrize("schritt", ["imputer", "scaler", "regressor"])
    def test_kein_pipelineschritt_nimmt_null_spalten(self, schritt):
        """
        Die Begruendung des Sonderfalls, nachgemessen statt behauptet.

        Faellt diese Einschraenkung in einer spaeteren sklearn-Fassung
        weg, faellt dieser Test - und dann gehoert der Sonderfall
        ueberprueft, statt weiter mitgeschleppt zu werden.
        """
        import numpy as np

        pipeline = mdl.build_pipeline(1.0)
        X = np.zeros((30, 0))
        y = np.full(30, 1.1)

        with pytest.raises(ValueError, match="0 feature"):
            if schritt == "regressor":
                pipeline.named_steps[schritt].fit(X, y)
            else:
                pipeline.named_steps[schritt].fit(X)


# ---------------------------------------------------------------------------
# 2. Die geschlossene Loesung ist die richtige
# ---------------------------------------------------------------------------

class TestGeschlosseneLoesung:

    def test_der_faktor_ist_tore_durch_lambdasumme(self):
        zeilen = bestand()
        modell, diagnose = mdl.fit_intercept_only(zeilen, "home")

        tore = sum(z["home_goals"] for z in zeilen)
        lambdas = sum(z["baseline_lambda_home"] for z in zeilen)

        assert modell.correction_factor == pytest.approx(tore / lambdas)
        assert diagnose["goals_total"] == pytest.approx(tore)
        assert diagnose["baseline_lambda_total"] == pytest.approx(lambdas)

    def test_sie_trifft_die_echte_offset_mle(self):
        """
        Der exakte Vergleich - dieselbe Beweisart wie beim
        Offset-Umweg des Modells.

        Gemessen wird gegen die direkt optimierte Likelihood
        sum(t*exp(b) - y*(log t + b)), nicht gegen eine Erwartung.
        """
        import numpy as np
        from scipy.optimize import minimize

        zeilen = bestand(80)
        y = np.array([z["home_goals"] for z in zeilen], dtype=float)
        t = np.array([z["baseline_lambda_home"] for z in zeilen], dtype=float)

        def negative_loglikelihood(p):
            return float(np.sum(t * np.exp(p[0]) - y * (np.log(t) + p[0])))

        referenz = minimize(negative_loglikelihood, np.zeros(1), method="BFGS",
                            options={"gtol": 1e-14, "maxiter": 10000}).x[0]

        modell, _ = mdl.fit_intercept_only(zeilen, "home")
        assert abs(referenz - modell.intercept_) < 1e-8

    def test_eine_perfekt_kalibrierte_baseline_ergibt_faktor_eins(self):
        """
        Die Gegenprobe: Stimmen die Lambdas mit den Toren ueberein,
        darf die Korrektur nichts tun. Ein Faktor ungleich eins waere
        hier ein Vorzeichen- oder Kehrwertfehler.
        """
        zeilen = [zeile(i, lam_home=2.0, tore_home=2) for i in range(25)]
        modell, _ = mdl.fit_intercept_only(zeilen, "home")

        assert modell.correction_factor == pytest.approx(1.0)
        assert modell.intercept_ == pytest.approx(0.0)

    def test_eine_zu_hohe_baseline_ergibt_einen_faktor_unter_eins(self):
        zeilen = [zeile(i, lam_home=2.0, tore_home=1) for i in range(25)]
        modell, _ = mdl.fit_intercept_only(zeilen, "home")
        assert modell.correction_factor == pytest.approx(0.5)

    def test_die_seiten_werden_getrennt_gerechnet(self):
        zeilen = [zeile(i, lam_home=2.0, tore_home=2,
                        lam_away=1.0, tore_away=2) for i in range(25)]

        heim, _ = mdl.fit_intercept_only(zeilen, "home")
        gast, _ = mdl.fit_intercept_only(zeilen, "away")

        assert heim.correction_factor == pytest.approx(1.0)
        assert gast.correction_factor == pytest.approx(2.0)

    def test_faktor_und_achsenabschnitt_passen_zueinander(self):
        modell, _ = mdl.fit_intercept_only(bestand(), "away")
        assert math.log(modell.correction_factor) == pytest.approx(
            modell.intercept_)


# ---------------------------------------------------------------------------
# 3. Fehlerfaelle
# ---------------------------------------------------------------------------

class TestFehlerfaelle:

    def test_ohne_ein_einziges_tor_bricht_es_ab(self):
        """log(0) waere -inf und wuerde stumm weitergereicht."""
        zeilen = [zeile(i, tore_home=0) for i in range(20)]
        with pytest.raises(ValueError, match="kein einziges Tor"):
            mdl.fit_intercept_only(zeilen, "home")

    def test_ein_unbrauchbares_lambda_bricht_ab(self):
        """
        Der Sonderfall umgeht die Pruefungen NICHT - er rechnet Ziel
        und Gewicht ueber dieselbe Funktion wie der Regelfall.
        """
        zeilen = bestand() + [zeile(99, lam_home=0.0)]
        with pytest.raises(ValueError, match="nicht strikt positiv"):
            mdl.fit_intercept_only(zeilen, "home")

    def test_ein_nicht_endlicher_achsenabschnitt_bricht_ab(self):
        with pytest.raises(ValueError, match="nicht endlicher"):
            mdl.InterceptOnlyModel(float("inf"))


# ---------------------------------------------------------------------------
# 4. Das Modell fuegt sich in den bestehenden Weg ein
# ---------------------------------------------------------------------------

class TestEinbindung:

    def test_leere_spaltenliste_fuehrt_in_den_sonderfall(self):
        modell, _ = mdl.fit_side(bestand(), "home", 1.0, [])
        assert isinstance(modell, mdl.InterceptOnlyModel)

    def test_none_bedeutet_weiterhin_die_volle_merkmalsliste(self):
        """
        Die Unterscheidung, an der alles haengt: None heisst "nimm die
        uebliche Liste", [] heisst "es soll keine geben". Ein
        `spalten or feature_columns()` haette beides verschmolzen.
        """
        zeilen = []
        for i, z in enumerate(bestand()):
            for spalte in mdl.feature_columns():
                z[spalte] = 0.1 * (i % 7) + 0.05
            zeilen.append(z)

        modell, _ = mdl.fit_side(zeilen, "home", 1.0, None)
        assert not isinstance(modell, mdl.InterceptOnlyModel)
        assert len(modell.named_steps["regressor"].coef_) \
            == len(mdl.feature_columns())

    def test_alpha_aendert_nichts(self):
        """
        PoissonRegressor bestraft nur coef_. Ohne Merkmale gibt es
        keines, also ist jedes Alpha dasselbe Modell. Genau darauf
        beruht, dass das Auswahlprotokoll fuer intercept_only fuenf
        identische Verluste zeigt.
        """
        zeilen = bestand()
        faktoren = {mdl.fit_side(zeilen, "home", alpha, [])[0].intercept_
                    for alpha in mdl.ALPHA_CANDIDATES}
        assert len(faktoren) == 1

    def test_predict_liefert_einen_konstanten_faktor(self):
        zeilen = bestand()
        modell, _ = mdl.fit_side(zeilen, "home", 1.0, [])
        faktoren = mdl.predict_factors(modell, zeilen, [])

        assert len(faktoren) == len(zeilen)
        assert len(set(faktoren)) == 1
        assert faktoren[0] == pytest.approx(modell.correction_factor)

    def test_die_koeffizientenausgabe_bleibt_leer(self):
        modell, _ = mdl.fit_side(bestand(), "home", 1.0, [])
        werte = mdl.coefficients(modell, [])

        assert werte["by_feature"] == []
        assert werte["top_positive"] == []
        assert werte["top_negative"] == []
        assert werte["intercept"] == pytest.approx(modell.intercept_)

    def test_eine_falsche_spaltenzahl_bricht_ab(self):
        """
        Die Gegenprobe zur stillen Fehlzuordnung: Wer dem
        merkmalsfreien Modell Spaltennamen unterschiebt, bekommt keine
        erfundene Zuordnung, sondern einen Abbruch.
        """
        modell, _ = mdl.fit_side(bestand(), "home", 1.0, [])
        with pytest.raises(ValueError, match="Koeffizienten"):
            mdl.coefficients(modell, ["home_win_rate"])

    def test_die_korrektur_skaliert_alle_lambdas_gleich(self):
        """
        Der fachliche Kern: eine einzige Zahl fuer alle Partien. Genau
        das macht intercept_only zur Untergrenze der Rekalibrierung.
        """
        zeilen = bestand()
        heim, _ = mdl.fit_side(zeilen, "home", 1.0, [])
        gast, _ = mdl.fit_side(zeilen, "away", 1.0, [])

        lambdas, statistik = mdl.apply_correction(
            zeilen,
            mdl.predict_factors(heim, zeilen, []),
            mdl.predict_factors(gast, zeilen, []))

        for zeile_, (lam_h, lam_a) in zip(zeilen, lambdas):
            assert lam_h == pytest.approx(
                zeile_["baseline_lambda_home"] * heim.correction_factor)
            assert lam_a == pytest.approx(
                zeile_["baseline_lambda_away"] * gast.correction_factor)

        assert statistik["raw_factor_home"]["min"] == pytest.approx(
            statistik["raw_factor_home"]["max"])

    def test_die_diagnose_nennt_die_rechenvorschrift(self):
        _, diagnose = mdl.fit_side(bestand(), "home", 1.0, [])
        assert "summe(tore)" in diagnose["closed_form"]
        assert diagnose["constant_features"] == []
        assert "alpha" in diagnose["alpha_note"]
