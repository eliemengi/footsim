"""
Tests fuer das Poisson-Korrekturmodell.

Anspruch an diese Tests: Jeder muss die behauptete Eigenschaft
tatsaechlich verletzen koennen. Ein Test, der nur prueft, ob eine
Funktion existiert und etwas zurueckgibt, belegt nichts.
"""

import ast
import math
import os

import pytest

from src.ml import dataset as ds
from src.ml import model as mdl

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Bausteine
# ---------------------------------------------------------------------------

def zeile(index=0, lam_home=1.5, lam_away=1.1, tore_home=1, tore_away=1,
          **ueberschreibungen):
    """
    Eine vollstaendige Datensatzzeile mit deterministischen Werten.

    Alle Merkmalsspalten werden gefuellt, damit ein Test, der ein
    einzelnes Merkmal veraendert, auch wirklich nur dieses veraendert.
    """
    daten = {
        "row_id": f"tst:2023:2023-08-{index % 28 + 1:02d}:1:2",
        "match_id": 1000 + index,
        "league": "bl1",
        "season": 2023,
        "date": f"2023-08-{index % 28 + 1:02d}",
        "matchday": index % 34 + 1,
        "home_id": 1,
        "away_id": 2,
        "evaluation_eligible": True,
        "home_goals": tore_home,
        "away_goals": tore_away,
        "outcome": (0 if tore_home > tore_away
                    else (1 if tore_home == tore_away else 2)),
        "baseline_lambda_home": lam_home,
        "baseline_lambda_away": lam_away,
    }
    for i, spalte in enumerate(mdl.feature_columns()):
        # Werte streuen, damit kein Merkmal versehentlich konstant ist.
        daten[spalte] = 0.1 * ((index * 7 + i * 3) % 19) + 0.05
    daten.update(ueberschreibungen)
    return daten


def zeilen(anzahl, **gemeinsam):
    return [zeile(i, **gemeinsam) for i in range(anzahl)]


# ---------------------------------------------------------------------------
# 1. Der Offset-Umweg
# ---------------------------------------------------------------------------

class TestOffsetUmweg:
    """
    Der Kern der Bauform. Wenn der Umweg nicht stimmt, stimmt nichts
    danach.
    """

    @staticmethod
    def _synthetisch(n=4000, seed=7):
        import numpy as np

        rng = np.random.default_rng(seed)
        X = rng.normal(size=(n, 3))
        beta = np.array([0.4, -0.25, 0.15])
        # Die Exposure haengt bewusst von X[:, 0] ab. Waere sie
        # unabhaengig, wuerde ein fehlender Offset nur den Intercept
        # verschieben - und der Gegenversuch weiter unten waere blind.
        t = np.exp(0.8 * X[:, 0]) * 1.2
        y = rng.poisson(t * np.exp(X @ beta)).astype(float)
        return X, y, t, beta

    def test_offset_umweg_trifft_die_echte_offset_mle(self):
        """
        Verhaeltnisziel mit Gewicht loest dasselbe Problem wie ein echter
        Offset.

        Gemessen wird nicht gegen das wahre beta - das waere nur
        Stichprobenstreuung -, sondern gegen die direkt optimierte
        Offset-Likelihood. Dieser Vergleich ist exakt.
        """
        import numpy as np
        from scipy.optimize import minimize
        from sklearn.linear_model import PoissonRegressor

        X, y, t, _ = self._synthetisch()

        def negative_loglikelihood(p):
            eta = p[0] + X @ p[1:]
            return float(np.sum(t * np.exp(eta) - y * (np.log(t) + eta)))

        referenz = minimize(negative_loglikelihood, np.zeros(4), method="BFGS",
                            options={"gtol": 1e-12, "maxiter": 10000}).x

        umweg = PoissonRegressor(alpha=0.0, max_iter=20000, tol=1e-12).fit(
            X, y / t, sample_weight=t)
        gefunden = np.concatenate([[umweg.intercept_], umweg.coef_])

        assert float(np.abs(referenz - gefunden).max()) < 1e-6

    def test_ohne_offset_verschluckt_der_koeffizient_die_exposure(self):
        """
        Der Gegenversuch. Ohne ihn koennte der Test oben auch dann gruen
        sein, wenn der Offset ueberhaupt nichts bewirkt.
        """
        import numpy as np
        from sklearn.linear_model import PoissonRegressor

        # Groesser als beim Gleichheitstest: Hier wird gegen das WAHRE
        # beta gemessen, und dafuer muss die Stichprobenstreuung klein
        # genug sein, um nicht selbst die Schranke zu reissen.
        X, y, t, beta = self._synthetisch(n=20000)

        mit = PoissonRegressor(alpha=0.0, max_iter=20000).fit(
            X, y / t, sample_weight=t)
        ohne = PoissonRegressor(alpha=0.0, max_iter=20000).fit(X, y)

        abweichung_mit = float(np.abs(mit.coef_ - beta).max())
        abweichung_ohne = float(np.abs(ohne.coef_ - beta).max())

        assert abweichung_mit < 0.02
        # Der erste Koeffizient schluckt die Exposure: 0.4 wird zu rund 1.2.
        assert abweichung_ohne > 0.5
        assert abweichung_ohne > 20 * abweichung_mit

    def test_sklearn_hat_keine_offset_schnittstelle(self):
        """
        Haelt die Behauptung aus dem Moduldocstring fest. Sollte eine
        kuenftige sklearn-Fassung einen Offset bekommen, schlaegt dieser
        Test fehl - und dann gehoert der Umweg ueberdacht, nicht der Test
        angepasst.
        """
        import inspect

        from sklearn.linear_model import PoissonRegressor

        namen = set(inspect.signature(PoissonRegressor.fit).parameters)
        assert namen == {"self", "X", "y", "sample_weight"}


# ---------------------------------------------------------------------------
# 2. Ziel, Gewicht und Positivitaet
# ---------------------------------------------------------------------------

class TestZielUndGewicht:

    def test_ziel_ist_tore_durch_lambda_und_gewicht_ist_lambda(self):
        ziel, gewicht = mdl.targets_and_weights(
            [zeile(0, lam_home=2.0, tore_home=3)], "home")
        assert ziel == [1.5]
        assert gewicht == [2.0]

    @pytest.mark.parametrize("schlecht", [0.0, -0.5, None, float("nan"),
                                          float("inf")])
    def test_unbrauchbares_lambda_bricht_kontrolliert_ab(self, schlecht):
        """
        Kein stilles Glaetten. Ein Lambda von null hiesse, die Baseline
        habe fuer diese Partie keine Vorhersage - dann darf auch keine
        Korrektur darauf aufbauen.
        """
        with pytest.raises(ValueError, match="baseline_lambda_home"):
            mdl.targets_and_weights([zeile(0, lam_home=schlecht)], "home")

    def test_ein_gueltiges_lambda_bricht_nicht_ab(self):
        """Gegenprobe: Der Test oben darf nicht einfach immer werfen."""
        ziel, gewicht = mdl.targets_and_weights([zeile(0, lam_home=1.7)],
                                                "home")
        assert gewicht == [1.7]

    def test_negative_tore_brechen_ab(self):
        with pytest.raises(ValueError, match="away_goals"):
            mdl.targets_and_weights([zeile(0, tore_away=-1)], "away")

    def test_fit_lehnt_nichtendliches_gewicht_ab(self):
        with pytest.raises(ValueError):
            mdl.fit_side([zeile(0, lam_home=float("inf"))], "home", 1.0)


# ---------------------------------------------------------------------------
# 3. Die Merkmalsliste
# ---------------------------------------------------------------------------

class TestMerkmalsliste:

    def test_keine_identifikatoren_ziele_diagnostik_oder_text(self):
        """
        Der Schemavertrag ist massgeblich, nicht ein Namensmuster.
        Faellt eine Rolle durch, ist es hier zu sehen.
        """
        schema = {e["name"]: e["role"] for e in ds.build_schema()}
        for spalte in mdl.feature_columns():
            assert schema[spalte] == "feature", spalte

    def test_bekannte_verbotene_spalten_sind_wirklich_draussen(self):
        """
        Die Rollenpruefung oben waere gruen, wenn das Schema selbst
        falsch waere. Diese Liste nennt die Spalten beim Namen.
        """
        merkmale = set(mdl.feature_columns())
        for verboten in ("row_id", "match_id", "league", "season", "date",
                         "matchday", "home_id", "away_id",
                         "evaluation_eligible", "home_goals", "away_goals",
                         "outcome", "baseline_lambda_home",
                         "baseline_lambda_away", "baseline_p_home",
                         "baseline_p_draw", "baseline_p_away",
                         "home_congestion_level", "away_congestion_level"):
            assert verboten not in merkmale, verboten

    def test_baseline_lambdas_sind_offset_und_kein_freies_merkmal(self):
        """
        Waeren sie beides, koennte das Modell die Baseline beliebig
        ueberschreiben - genau das soll die Bauform verhindern.
        """
        rollen = {e["name"]: e["role"] for e in ds.build_schema()}
        assert rollen["baseline_lambda_home"] == "baseline"
        assert rollen["baseline_lambda_away"] == "baseline"

    def test_liste_ist_sortiert_und_ueber_laeufe_stabil(self):
        erste = mdl.feature_columns()
        assert erste == sorted(erste)
        assert erste == mdl.feature_columns()
        assert len(erste) == len(set(erste))

    def test_jede_ausgeschlossene_spalte_hat_eine_begruendung(self):
        for eintrag in mdl.excluded_columns():
            assert eintrag["reason"].strip()

    def test_merkmale_und_ausgeschlossene_decken_das_schema_ab(self):
        """Keine Spalte darf unbemerkt zwischen beiden Listen liegen."""
        alle = {e["name"] for e in ds.build_schema()}
        abgedeckt = set(mdl.feature_columns()) | {
            e["column"] for e in mdl.excluded_columns()}
        assert alle == abgedeckt

    def test_textspalte_in_der_merkmalsliste_faellt_auf(self):
        """
        Belegt, dass die Matrix Text nicht stillschweigend durchlaesst.
        Ohne diese Pruefung koennte eine kategoriale Spalte unbemerkt ins
        Modell wandern.
        """
        with pytest.raises(TypeError, match="nicht numerisch"):
            mdl.feature_matrix([{"x": "high"}], ["x"])


# ---------------------------------------------------------------------------
# 4. Vorverarbeitung sieht nur das Training
# ---------------------------------------------------------------------------

class TestVorverarbeitung:

    def test_imputer_und_scaler_sehen_ausschliesslich_die_trainingszeilen(
            self, monkeypatch):
        """
        Der schaerfste Test des Moduls. Er zeichnet auf, WELCHE Matrix
        Imputer und Scaler beim fit tatsaechlich zu sehen bekommen, und
        vergleicht sie mit den Trainingszeilen.

        Eine globale Imputation vor dem Split waere hier sofort sichtbar:
        Die aufgezeichnete Zeilenzahl wuerde nicht mehr stimmen.
        """
        import numpy as np
        from sklearn.impute import SimpleImputer
        from sklearn.preprocessing import StandardScaler

        gesehen = {}
        for name, klasse in (("imputer", SimpleImputer),
                             ("scaler", StandardScaler)):
            original = klasse.fit

            def merken(selbst, X, *args, _name=name, _orig=original, **kwargs):
                gesehen[_name] = np.array(X, dtype=float, copy=True)
                return _orig(selbst, X, *args, **kwargs)

            monkeypatch.setattr(klasse, "fit", merken)

        training = zeilen(30)
        test = [zeile(500 + i, lam_home=3.0) for i in range(12)]
        spalten = mdl.feature_columns()

        pipeline, _ = mdl.fit_side(training, "home", 1.0, spalten)
        mdl.predict_factors(pipeline, test, spalten)

        assert gesehen["imputer"].shape[0] == len(training)
        assert gesehen["scaler"].shape[0] == len(training)

        erwartet = np.array(mdl.feature_matrix(training, spalten), dtype=float)
        assert np.allclose(gesehen["imputer"], erwartet, equal_nan=True)

    def test_der_median_stammt_aus_dem_training_nicht_aus_dem_test(self):
        """
        Direkt an der gelernten Statistik gemessen: Der Imputermedian muss
        der Trainingsmedian sein und darf sich nicht veraendern, wenn
        ganz andere Testdaten vorhergesagt werden.
        """
        spalten = ["a"]
        basis = {"baseline_lambda_home": 1.4, "home_goals": 1}
        training = [dict(basis, a=wert) for wert in (1.0, 2.0, 3.0)]
        test = [dict(basis, a=None), dict(basis, a=900.0)]

        pipeline, _ = mdl.fit_side(training, "home", 1.0, spalten)
        median = float(pipeline.named_steps["imputer"].statistics_[0])
        assert median == 2.0

        mdl.predict_factors(pipeline, test, spalten)
        assert float(pipeline.named_steps["imputer"].statistics_[0]) == 2.0

    def test_fehlende_werte_bleiben_bis_zum_imputer_erhalten(self):
        """
        feature_matrix darf nicht selbst ersetzen - das liefe ueber den
        gesamten Datensatz und damit ueber die zeitliche Grenze hinweg.
        """
        matrix = mdl.feature_matrix([{"a": None, "b": 2}], ["a", "b"])
        assert matrix == [[None, 2.0]]

    def test_konstante_und_leere_merkmale_werden_gemeldet(self):
        matrix = mdl.feature_matrix(
            [{"a": 1, "b": None, "c": 5}, {"a": 1, "b": None, "c": 9}],
            ["a", "b", "c"])
        assert mdl.constant_features(matrix, ["a", "b", "c"]) == ["a", "b"]
        assert mdl.fully_missing_features(matrix, ["a", "b", "c"]) == ["b"]

    def test_wahrheitswerte_werden_zu_null_und_eins(self):
        assert mdl.feature_matrix([{"a": True}, {"a": False}], ["a"]) \
            == [[1.0], [0.0]]


# ---------------------------------------------------------------------------
# 5. Grenzen
# ---------------------------------------------------------------------------

class TestGrenzen:

    def test_der_korrekturfaktor_wird_auf_das_intervall_begrenzt(self):
        eingabe = zeilen(3, lam_home=1.0, lam_away=1.0)
        lambdas, statistik = mdl.apply_correction(
            eingabe, [0.1, 1.0, 9.0], [9.0, 1.0, 0.1])

        assert lambdas[0][0] == pytest.approx(mdl.CORRECTION_MIN)
        assert lambdas[1][0] == pytest.approx(1.0)
        assert lambdas[2][0] == pytest.approx(mdl.CORRECTION_MAX)
        assert statistik["clamped_home"] == 2
        assert statistik["clamp_rate_home"] == pytest.approx(2 / 3)

    def test_die_klammer_zaehlt_je_seite_getrennt(self):
        """
        Ein gemeinsamer Zaehler wuerde verbergen, dass nur eine Seite aus
        dem Ruder laeuft.
        """
        eingabe = zeilen(2, lam_home=1.0, lam_away=1.0)
        _, statistik = mdl.apply_correction(eingabe, [9.0, 9.0], [1.0, 1.0])
        assert statistik["clamped_home"] == 2
        assert statistik["clamped_away"] == 0
        assert statistik["clamp_rate_away"] == 0.0

    def test_auch_das_lambda_selbst_wird_begrenzt(self):
        """
        Ein Faktor innerhalb der Grenzen kann auf einem grossen
        Baseline-Lambda trotzdem einen unsinnigen Wert erzeugen.
        """
        eingabe = zeilen(1, lam_home=4.0, lam_away=0.05)
        lambdas, statistik = mdl.apply_correction(eingabe, [2.0], [0.5])
        assert lambdas[0][0] == pytest.approx(mdl.LAMBDA_MAX)
        assert lambdas[0][1] >= mdl.LAMBDA_MIN
        assert statistik["clamped_home"] == 1

    def test_die_verteilung_der_rohfaktoren_wird_berichtet(self):
        """
        Die Rohfaktoren, nicht die begrenzten - sonst waere die
        Klammerquote nicht nachvollziehbar.
        """
        eingabe = zeilen(3, lam_home=1.0, lam_away=1.0)
        _, statistik = mdl.apply_correction(
            eingabe, [0.1, 1.0, 9.0], [1.0, 1.0, 1.0])
        assert statistik["raw_factor_home"]["min"] == pytest.approx(0.1)
        assert statistik["raw_factor_home"]["max"] == pytest.approx(9.0)
        assert statistik["final_lambda_home"]["max"] \
            == pytest.approx(mdl.CORRECTION_MAX)

    @pytest.mark.parametrize("kaputt", [float("nan"), float("inf"),
                                        float("-inf")])
    def test_nicht_endlicher_faktor_bricht_kontrolliert_ab(self, kaputt):
        """Niemals stillschweigend auf die Baseline zurueckfallen."""
        with pytest.raises(ValueError, match="nicht endlicher"):
            mdl.apply_correction(zeilen(1), [kaputt], [1.0])

    def test_nan_vorhersage_bricht_kontrolliert_ab(self):
        class KaputtesModell:
            def predict(self, X):
                import numpy as np
                return np.full(len(X), float("nan"))

        with pytest.raises(ValueError, match="NaN oder Inf"):
            mdl.predict_factors(KaputtesModell(), zeilen(2))

    def test_unpassende_faktorlaenge_bricht_ab(self):
        with pytest.raises(ValueError, match="passen nicht zusammen"):
            mdl.apply_correction(zeilen(3), [1.0], [1.0])


# ---------------------------------------------------------------------------
# 6. Die Baseline als Kandidat
# ---------------------------------------------------------------------------

class TestBaselineKandidat:

    def test_baseline_lambdas_geben_die_eingabe_zifferngenau_zurueck(self):
        """
        Kein Rundungsschritt, keine Umrechnung. Wuerde hier auch nur die
        letzte Stelle wandern, waere der Vergleich ML gegen Baseline
        verfaelscht.
        """
        eingabe = [zeile(0, lam_home=1.234567890123, lam_away=0.987654321098)]
        assert mdl.baseline_lambdas(eingabe) == [
            (1.234567890123, 0.987654321098)]

    def test_ein_faktor_von_eins_veraendert_das_lambda_nicht(self):
        eingabe = [zeile(0, lam_home=1.3, lam_away=1.1)]
        lambdas, _ = mdl.apply_correction(eingabe, [1.0], [1.0])
        assert lambdas == [(1.3, 1.1)]


# ---------------------------------------------------------------------------
# 7. Koeffizienten
# ---------------------------------------------------------------------------

class TestKoeffizienten:

    def test_ein_eintrag_je_merkmal_und_sortierte_extremwerte(self):
        spalten = mdl.feature_columns()
        pipeline, _ = mdl.fit_side(zeilen(60), "home", 1.0, spalten)
        koeffizienten = mdl.coefficients(pipeline, spalten)

        assert len(koeffizienten["by_feature"]) == len(spalten)
        assert {e["feature"] for e in koeffizienten["by_feature"]} \
            == set(spalten)
        assert len(koeffizienten["top_positive"]) <= 10
        assert len(koeffizienten["top_negative"]) <= 10

        positive = [e["coefficient"] for e in koeffizienten["top_positive"]]
        assert positive == sorted(positive, reverse=True)
        negative = [e["coefficient"] for e in koeffizienten["top_negative"]]
        assert negative == sorted(negative)
        assert math.isfinite(koeffizienten["intercept"])


# ---------------------------------------------------------------------------
# 8. Abgrenzung
# ---------------------------------------------------------------------------

def importe(pfad):
    """
    Ueber den Syntaxbaum, nicht ueber Textsuche. Ein Treffer im Docstring
    wuerde sonst als Zugriff gelten - dieser Fehler ist in diesem Projekt
    schon dreimal passiert.
    """
    baum = ast.parse(open(pfad, encoding="utf-8").read())
    namen = set()
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Import):
            namen.update(a.name for a in knoten.names)
        elif isinstance(knoten, ast.ImportFrom) and knoten.module:
            namen.add(knoten.module)
    return namen


class TestAbgrenzung:

    @pytest.mark.parametrize("datei", ["src/ml/model.py", "src/ml/evaluate.py"])
    def test_kein_zugriff_auf_pool_cache_oder_grossspiele(self, datei):
        pfad = os.path.join(WURZEL, datei)
        quelle = open(pfad, encoding="utf-8").read()

        for verboten in ("player_pool", "data/cache", "big_games"):
            for zeilentext in quelle.splitlines():
                if verboten not in zeilentext:
                    continue
                # Eine Erwaehnung in einer Begruendung ist erlaubt, ein
                # echter Dateizugriff nicht.
                assert "open(" not in zeilentext, zeilentext
                assert "load" not in zeilentext.lower(), zeilentext

        for modul in importe(pfad):
            assert "player_pool" not in modul
            assert "big_games" not in modul

    def test_das_modell_beruehrt_den_produktiven_pfad_nicht(self):
        """
        model.py darf nichts aus der Flask-Anwendung importieren.
        Andernfalls waere ein Schattenmodell keines mehr.
        """
        for modul in importe(os.path.join(WURZEL, "src/ml/model.py")):
            assert not modul.startswith("app")
            assert not modul.startswith("src.routes")
            assert not modul.startswith("src.models")
