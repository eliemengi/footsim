"""
Tests fuer die Ablation des Schattenmodells.

Die Ablation soll erklaeren, woher eine gemessene Verbesserung kommt.
Damit ihre Antwort etwas wert ist, muss zweierlei nachweisbar sein:
Sie benutzt dasselbe Walk-forward-Verfahren wie die Messung, die sie
erklaert - und sie schaut dabei in keinen Testbestand.

Beides laesst sich verletzen, ohne dass eine Zahl unplausibel wuerde.
Deshalb stehen hier Tests dafuer und nicht nur fuer die Form des
Ergebnisses.
"""

import pytest

from src.ml import ablation as ab
from src.ml import evaluate as ev
from src.ml import feature_groups as fg
from src.ml import model as mdl

SPALTEN = mdl.feature_columns()


# ---------------------------------------------------------------------------
# Bausteine
# ---------------------------------------------------------------------------

def _streuwert(index, tag, i):
    """
    Ein deterministischer, aber nicht trivial vorhersagbarer Wert.

    Bewusst kein random: Zwei Testlaeufe muessen dieselben Zahlen
    ergeben, sonst liesse sich Reproduzierbarkeit hier nicht pruefen.
    Bewusst auch nicht linear in tag - sonst wuerde jedes Merkmal das
    Ergebnis verraten und die Modellwahl haette nichts zu entscheiden.
    """
    roh = (index * 37 + tag * 17 + i * 5) % 97
    return 0.05 + (roh / 97.0) * 1.9


def zeile(season, tag, index):
    """Eine Zeile mit echter zeitlicher Ordnung innerhalb der Saison."""
    from datetime import date, timedelta

    datum = (date(season, 8, 1) + timedelta(days=tag)).isoformat()
    tore_home = (index * 3 + tag) % 4
    tore_away = (index * 5 + tag * 2) % 4

    daten = {
        "row_id": f"bl1:{season}:{datum}:{index}:{index + 100}",
        "match_id": None,
        "league": ["bl1", "pl", "sa"][index % 3],
        "season": season,
        "date": datum,
        "matchday": tag // 7 + 1,
        "home_id": index,
        "away_id": index + 100,
        "evaluation_eligible": True,
        "home_goals": tore_home,
        "away_goals": tore_away,
        "outcome": (0 if tore_home > tore_away
                    else (1 if tore_home == tore_away else 2)),
        "baseline_lambda_home": 1.20 + 0.01 * (index % 11),
        "baseline_lambda_away": 1.05 + 0.01 * (index % 7),
    }
    for i, spalte in enumerate(SPALTEN):
        daten[spalte] = _streuwert(index, tag, i)
    return daten


def saison(season, anzahl=60):
    return [zeile(season, tag=i * 4, index=i) for i in range(anzahl)]


@pytest.fixture(scope="module")
def zeilen():
    return saison(2023) + saison(2024) + saison(2025)


@pytest.fixture(scope="module")
def ergebnis(zeilen):
    """Ein vollstaendiger Ablationslauf - einmal je Modul."""
    return ab.run_ablation(zeilen)


def _variante(ergebnis, name):
    for eintrag in ergebnis["variants"]:
        if eintrag["variant"] == name:
            return eintrag
    raise AssertionError(f"Variante fehlt: {name}")


# ---------------------------------------------------------------------------
# 1. Die Kontrolle
# ---------------------------------------------------------------------------

class TestNoCorrection:
    """
    no_correction ist der Pruefstein des Messaufbaus. Liefert sie nicht
    exakt null, misst der Aufbau selbst etwas - und dann waere kein
    anderes Ergebnis dieser Datei zu gebrauchen.
    """

    def test_das_delta_ist_exakt_null(self, ergebnis):
        variante = _variante(ergebnis, "no_correction")
        zusammen = variante["aggregate"]
        for name in ("log_loss", "brier", "rps"):
            assert zusammen[f"delta_{name}"] == 0.0

    def test_ml_und_baseline_sind_dieselbe_zahl(self, ergebnis):
        zusammen = _variante(ergebnis, "no_correction")["aggregate"]
        for name in ("log_loss", "brier", "rps"):
            assert zusammen["ml"][name] == zusammen["baseline"][name]

    def test_das_intervall_ist_null_bis_null(self, ergebnis):
        intervall = _variante(ergebnis,
                              "no_correction")["aggregate"]["bootstrap"]
        for name in ("log_loss", "brier", "rps"):
            assert intervall[name]["ci_low"] == 0.0
            assert intervall[name]["ci_high"] == 0.0

    def test_es_wird_kein_modell_gewaehlt(self, ergebnis):
        variante = _variante(ergebnis, "no_correction")
        for eintrag in variante["selected_candidates"]:
            assert eintrag["selected"] == mdl.NO_CORRECTION

    def test_es_entstehen_keine_koeffizienten(self, ergebnis):
        variante = _variante(ergebnis, "no_correction")
        for fold in variante["folds"]:
            assert "coefficients" not in fold

    def test_sklearn_wird_gar_nicht_erst_aufgerufen(self, zeilen, monkeypatch):
        """
        Die Gegenprobe: Ohne Merkmale darf keine Anpassung stattfinden.
        Waere hier ein Sonderpfad noetig, der doch anpasst, wuerde die
        Kontrolle nur diesen Sonderpfad kontrollieren.
        """
        def verboten(*args, **kwargs):
            raise AssertionError("no_correction hat ein Modell angepasst")

        monkeypatch.setattr(mdl, "fit_side", verboten)

        variante = ab.run_variant(zeilen, fg.variant("no_correction"))
        assert variante["feature_count"] == 0
        assert variante["aggregate"]["delta_log_loss"] == 0.0

    def test_die_lambdas_bleiben_die_baseline(self, ergebnis):
        """Keine Korrektur heisst auch: keine Klammerung."""
        variante = _variante(ergebnis, "no_correction")
        for fold in variante["folds"]:
            assert fold["clamps"]["clamped_home"] == 0
            assert fold["clamps"]["clamped_away"] == 0
            assert fold["avg_probability_change"] == 0.0
            assert fold["max_probability_change"] == 0.0


# ---------------------------------------------------------------------------
# 2. Das Verfahren bleibt unveraendert
# ---------------------------------------------------------------------------

class TestVerfahrenUnveraendert:

    def test_die_aeusseren_folds_sind_die_bestehenden(self, ergebnis):
        for variante in ergebnis["variants"]:
            assert [f["fold"] for f in variante["folds"]] \
                == [f["name"] for f in ev.OUTER_FOLDS]
            assert [f["train_seasons"] for f in variante["folds"]] \
                == [f["train_seasons"] for f in ev.OUTER_FOLDS]
            assert [f["test_seasons"] for f in variante["folds"]] \
                == [f["test_seasons"] for f in ev.OUTER_FOLDS]

    def test_keine_spaetere_saison_liegt_im_training(self, ergebnis):
        for variante in ergebnis["variants"]:
            for fold in variante["folds"]:
                assert max(fold["train_seasons"]) < min(fold["test_seasons"])

    def test_die_ablation_benutzt_evaluate_fold(self, zeilen, monkeypatch):
        """
        Kein zweiter Rechenweg: Wird evaluate_fold ersetzt, muss die
        Ablation das merken. Sonst haette sie eine eigene Kopie des
        Verfahrens - genau das, was sie nicht haben soll.
        """
        aufrufe = []
        echt = ev.evaluate_fold

        def zaehlend(zeilen_, fold, spalten, alphas):
            aufrufe.append((fold["name"], tuple(spalten)))
            return echt(zeilen_, fold, spalten, alphas)

        monkeypatch.setattr(ev, "evaluate_fold", zaehlend)
        ab.run_variant(zeilen, fg.variant("profile_only"))

        assert [name for name, _ in aufrufe] == [f["name"]
                                                 for f in ev.OUTER_FOLDS]
        for _, spalten in aufrufe:
            assert list(spalten) == fg.columns_for("profile_only")

    def test_baseline_und_clamps_bleiben_dieselben(self, ergebnis):
        """
        Die Baseline ist ueber alle Varianten dieselbe Zahl - sie haengt
        nicht am Merkmalssatz. Waere sie es nicht, waeren die Deltas
        nicht vergleichbar.
        """
        werte = {variante["aggregate"]["baseline"]["log_loss"]
                 for variante in ergebnis["variants"]}
        assert len(werte) == 1

        for variante in ergebnis["variants"]:
            for fold in variante["folds"]:
                assert fold["clamps"]["correction_min"] == mdl.CORRECTION_MIN
                assert fold["clamps"]["correction_max"] == mdl.CORRECTION_MAX
                assert fold["clamps"]["lambda_min_allowed"] == mdl.LAMBDA_MIN
                assert fold["clamps"]["lambda_max_allowed"] == mdl.LAMBDA_MAX

    def test_alle_varianten_messen_dieselben_spiele(self, ergebnis):
        anzahlen = {variante["aggregate"]["n"]
                    for variante in ergebnis["variants"]}
        assert len(anzahlen) == 1


# ---------------------------------------------------------------------------
# 3. Kein Blick in die Zukunft
# ---------------------------------------------------------------------------

class TestKeineLeckage:

    def test_die_alphawahl_sieht_kein_testspiel(self, zeilen, monkeypatch):
        """
        Der Kern der Zusage. Die Wahl darf ausschliesslich Zeilen der
        Trainingssaisons sehen; jede Testzeile darin waere eine
        Optimierung auf die Zukunft.
        """
        echt = ev.select_candidate
        gesehen = {}

        def beobachtend(fit_zeilen, val_zeilen, spalten, alphas=None):
            saisons = {z["season"] for z in fit_zeilen}
            saisons |= {z["season"] for z in val_zeilen}
            gesehen.setdefault("saisons", []).append(saisons)
            if alphas is None:
                return echt(fit_zeilen, val_zeilen, spalten)
            return echt(fit_zeilen, val_zeilen, spalten, alphas)

        monkeypatch.setattr(ev, "select_candidate", beobachtend)
        ab.run_variant(zeilen, fg.variant("all_existing_features"))

        for fold, saisons in zip(ev.OUTER_FOLDS, gesehen["saisons"]):
            assert saisons <= set(fold["train_seasons"]), (
                f"{fold['name']}: die Wahl sah {sorted(saisons)}, erlaubt "
                f"waren {fold['train_seasons']}")

    def test_die_innere_teilung_bleibt_im_training(self, ergebnis):
        for variante in ergebnis["variants"]:
            for fold, definition in zip(variante["folds"], ev.OUTER_FOLDS):
                innen = fold["inner_split"]
                for schluessel in ("fit_seasons", "validation_seasons"):
                    if schluessel in innen:
                        assert set(innen[schluessel]) \
                            <= set(definition["train_seasons"])

    def test_das_training_enthaelt_keine_testzeile(self, zeilen):
        for fold in ev.OUTER_FOLDS:
            training = ev.eligible_rows(zeilen, fold["train_seasons"])
            test = ev.eligible_rows(zeilen, fold["test_seasons"])
            assert not ({z["row_id"] for z in training}
                        & {z["row_id"] for z in test})


# ---------------------------------------------------------------------------
# 4. Aufbau des Ergebnisses
# ---------------------------------------------------------------------------

class TestErgebnisaufbau:

    def test_alle_vier_varianten_stehen_drin(self, ergebnis):
        assert [v["variant"] for v in ergebnis["variants"]] \
            == list(fg.VARIANT_ORDER)

    def test_die_vergleichstabelle_folgt_derselben_reihenfolge(self, ergebnis):
        assert [z["variant"] for z in ergebnis["comparison"]] \
            == list(fg.VARIANT_ORDER)

    def test_jede_variante_nennt_ihre_merkmale(self, ergebnis):
        for variante in ergebnis["variants"]:
            erwartet = fg.columns_for(variante["variant"])
            assert variante["feature_columns"] == erwartet
            assert variante["feature_count"] == len(erwartet)

    def test_alle_drei_kennzahlen_werden_verglichen(self, ergebnis):
        for zeile_ in ergebnis["comparison"]:
            for name in ("log_loss", "brier", "rps"):
                assert f"delta_{name}" in zeile_
                assert f"ml_{name}" in zeile_
                assert f"baseline_{name}" in zeile_

    def test_jede_variante_traegt_ein_bootstrap_intervall(self, ergebnis):
        for zeile_ in ergebnis["comparison"]:
            assert zeile_["log_loss_ci_low"] <= zeile_["delta_log_loss"] \
                <= zeile_["log_loss_ci_high"]
            assert zeile_["log_loss_interpretation"]

    def test_es_gibt_ergebnisse_je_fold_und_je_liga(self, ergebnis):
        for variante in ergebnis["variants"]:
            assert len(variante["folds"]) == len(ev.OUTER_FOLDS)
            for fold in variante["folds"]:
                assert fold["per_league"]
            assert variante["aggregate"]["per_league"]
            assert variante["aggregate"]["per_test_season"]

    def test_die_gewaehlten_alphas_sind_dokumentiert(self, ergebnis):
        erlaubt = set(mdl.ALPHA_CANDIDATES) | {mdl.NO_CORRECTION}
        for variante in ergebnis["variants"]:
            assert len(variante["selected_candidates"]) == len(ev.OUTER_FOLDS)
            for eintrag in variante["selected_candidates"]:
                assert eintrag["selected"] in erlaubt

    def test_koeffizienten_stehen_dort_wo_angepasst_wurde(self, ergebnis):
        for variante in ergebnis["variants"]:
            for fold in variante["folds"]:
                if fold["selected_candidate"] == mdl.NO_CORRECTION:
                    assert "coefficients" not in fold
                    continue
                for seite in ("home", "away"):
                    namen = [p["feature"] for p
                             in fold["coefficients"][seite]["by_feature"]]
                    assert namen == variante["feature_columns"]

    def test_die_gruppeninfo_liegt_bei(self, ergebnis):
        info = ergebnis["feature_groups"]
        assert info["group_order"] == list(fg.GROUP_ORDER)
        assert sum(info["counts"].values()) == info["total_model_features"]

    def test_der_interne_block_ist_entfernt(self, ergebnis):
        """Er traegt Verlustlisten je Spiel und blaeht das Artefakt auf."""
        for variante in ergebnis["variants"]:
            for fold in variante["folds"]:
                assert "_internal" not in fold


# ---------------------------------------------------------------------------
# 5. Reproduzierbarkeit
# ---------------------------------------------------------------------------

class TestReproduzierbarkeit:

    def test_zwei_laeufe_ergeben_dieselben_zahlen(self, zeilen):
        erst = ab.run_ablation(zeilen)["comparison"]
        zweit = ab.run_ablation(zeilen)["comparison"]
        assert erst == zweit

    def test_der_seed_steht_fest(self, ergebnis):
        for variante in ergebnis["variants"]:
            for intervall in variante["aggregate"]["bootstrap"].values():
                assert intervall["seed"] == ev.BOOTSTRAP_SEED
                assert intervall["iterations"] == ev.BOOTSTRAP_ITERATIONS

    def test_alle_varianten_teilen_denselben_seed(self, ergebnis):
        """
        Derselbe Seed heisst dieselben Ziehungen. Nur so unterscheiden
        sich zwei Intervalle wegen der Modelle und nicht wegen des
        Zufalls.
        """
        seeds = {intervall["seed"]
                 for variante in ergebnis["variants"]
                 for intervall in variante["aggregate"]["bootstrap"].values()}
        assert len(seeds) == 1


# ---------------------------------------------------------------------------
# 6. Die Anteilsrechnung
# ---------------------------------------------------------------------------

class TestAttribution:

    def test_der_anteil_ist_das_verhaeltnis_der_deltas(self):
        vergleich = [
            {"variant": "profile_only", "delta_log_loss": -0.006},
            {"variant": "workload_only", "delta_log_loss": -0.002},
            {"variant": "all_existing_features", "delta_log_loss": -0.010},
        ]
        zuordnung = ab.attribution(vergleich)
        anteile = {e["variant"]: e["share_of_reference"]
                   for e in zuordnung["shares"]}
        assert anteile["profile_only"] == pytest.approx(0.6)
        assert anteile["workload_only"] == pytest.approx(0.2)

    def test_die_referenz_taucht_nicht_unter_den_anteilen_auf(self):
        vergleich = [
            {"variant": "profile_only", "delta_log_loss": -0.006},
            {"variant": "all_existing_features", "delta_log_loss": -0.010},
        ]
        zuordnung = ab.attribution(vergleich)
        assert [e["variant"] for e in zuordnung["shares"]] == ["profile_only"]

    def test_ohne_verbesserung_wird_nichts_aufgeteilt(self):
        """An einer Nichtverbesserung ist nichts aufzuteilen."""
        vergleich = [
            {"variant": "profile_only", "delta_log_loss": -0.001},
            {"variant": "all_existing_features", "delta_log_loss": +0.004},
        ]
        zuordnung = ab.attribution(vergleich)
        assert zuordnung["shares"] is None
        assert "keine" in zuordnung["note"] or "nicht" in zuordnung["note"]

    def test_ein_verschwindendes_delta_ergibt_keinen_quotienten(self):
        vergleich = [
            {"variant": "profile_only", "delta_log_loss": -1e-9},
            {"variant": "all_existing_features", "delta_log_loss": -1e-9},
        ]
        assert ab.attribution(vergleich)["shares"] is None

    def test_ohne_referenz_gibt_es_keine_zuordnung(self):
        assert ab.attribution([{"variant": "profile_only",
                                "delta_log_loss": -0.01}]) is None

    def test_die_einschraenkung_steht_im_ergebnis(self, ergebnis):
        """
        Die Anteile addieren sich nicht zwangslaeufig zu eins. Wer die
        Tabelle liest, muss das mitgeliefert bekommen - sonst liest er
        eine Zerlegung, wo nur ein Hinweis steht.
        """
        zuordnung = ergebnis["attribution"]
        assert zuordnung is not None
        assert "nicht" in zuordnung["note"].lower()

    def test_eine_unbekannte_variante_bricht_ab(self, zeilen):
        with pytest.raises(ValueError, match="unbekannte Ablationsvariante"):
            ab.run_variant(zeilen, {"name": "gibt_es_nicht", "groups": (),
                                    "description": "-"})


# ---------------------------------------------------------------------------
# 7. Zweite Diagnosestufe und gepaarte Variantenvergleiche
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def diagnose(zeilen):
    """Ein vollstaendiger Lauf der zweiten Stufe - einmal je Modul."""
    return ab.run_ablation(zeilen, varianten=fg.DIAGNOSTIC_VARIANTS,
                           paare=ab.PAIRED_COMPARISONS)


class TestDiagnosestufe:

    def test_alle_fuenf_varianten_laufen(self, diagnose):
        assert [v["variant"] for v in diagnose["variants"]] \
            == list(fg.DIAGNOSTIC_VARIANT_ORDER)

    def test_die_merkmalszahlen_stimmen_exakt(self, diagnose):
        erwartet = {"intercept_only": 0, "league_average_only": 4,
                    "team_profile_only": 18, "profile_only": 22,
                    "all_existing_features": 46}
        gemessen = {v["variant"]: v["feature_count"]
                    for v in diagnose["variants"]}
        assert gemessen == erwartet

    def test_jede_variante_traegt_genau_ihre_spalten(self, diagnose):
        for variante in diagnose["variants"]:
            assert variante["feature_columns"] \
                == fg.columns_for(variante["variant"])

    def test_intercept_only_passt_wirklich_etwas_an(self, zeilen, monkeypatch):
        """
        Der Unterschied zu no_correction, an dem die ganze Stufe haengt.
        Wird die geschlossene Loesung nicht gerufen, faellt das hier auf.
        """
        gerufen = []
        echt = mdl.fit_intercept_only

        def zaehlend(zeilen_, seite):
            gerufen.append(seite)
            return echt(zeilen_, seite)

        monkeypatch.setattr(mdl, "fit_intercept_only", zaehlend)
        ab.run_variant(zeilen, fg.variant("intercept_only"))

        assert gerufen, "intercept_only hat keine Anpassung ausgeloest"
        assert set(gerufen) == {"home", "away"}

    def test_intercept_only_bekommt_alle_alphas_zur_wahl(self, diagnose):
        variante = _variante(diagnose, "intercept_only")
        assert variante["alpha_candidates"] == list(mdl.ALPHA_CANDIDATES)

    def test_fuer_intercept_only_sind_alle_alphas_gleichwertig(self, diagnose):
        """
        Der Beleg statt der Behauptung: Ohne coef_ gibt es nichts zu
        bestrafen, also muessen alle Alphas denselben inneren Verlust
        ergeben. Das Auswahlprotokoll zeigt es.
        """
        variante = _variante(diagnose, "intercept_only")
        for fold in variante["folds"]:
            verluste = {round(e["inner_log_loss"], 12)
                        for e in fold["selection"]["candidates"]
                        if e["candidate"] != mdl.NO_CORRECTION
                        and "inner_log_loss" in e}
            assert len(verluste) == 1, (
                f"{fold['fold']}: die Alphas ergeben verschiedene Verluste")

    def test_intercept_only_hat_keine_merkmalskoeffizienten(self, diagnose):
        variante = _variante(diagnose, "intercept_only")
        for fold in variante["folds"]:
            if "coefficients" not in fold:
                continue
            for seite in ("home", "away"):
                assert fold["coefficients"][seite]["by_feature"] == []

    def test_die_betriebsart_steht_im_ergebnis(self, diagnose):
        modi = {v["variant"]: v["mode"] for v in diagnose["variants"]}
        assert modi["intercept_only"] == fg.MODE_INTERCEPT
        assert modi["profile_only"] == fg.MODE_FEATURES


class TestBetriebsartWirdGeprueft:

    def test_features_ohne_merkmal_bricht_ab(self, zeilen):
        with pytest.raises(ValueError, match="kein Merkmal"):
            ab.run_variant(zeilen, {"name": "no_correction",
                                    "mode": fg.MODE_FEATURES,
                                    "groups": (), "description": "-"})

    def test_intercept_mit_merkmalen_bricht_ab(self, zeilen):
        with pytest.raises(ValueError, match="traegt aber"):
            ab.run_variant(zeilen, {"name": "profile_only",
                                    "mode": fg.MODE_INTERCEPT,
                                    "groups": ("profile",),
                                    "description": "-"})


class TestPaarvergleiche:

    def test_die_drei_geforderten_paare_stehen_fest(self):
        assert ab.PAIRED_COMPARISONS == (
            ("profile_only", "all_existing_features"),
            ("profile_only", "intercept_only"),
            ("profile_only", "team_profile_only"))

    def test_alle_paare_werden_berichtet(self, diagnose):
        gemessen = [(e["variant"], e["reference"])
                    for e in diagnose["paired_comparisons"]]
        assert gemessen == list(ab.PAIRED_COMPARISONS)

    def test_das_vorzeichen_ist_erste_minus_zweite(self):
        """
        Die Vorzeichenkonvention, an der jede Deutung haengt. Hier
        gegen von Hand gesetzte Verluste geprueft, nicht gegen einen
        Lauf - ein Vorzeichendreher bliebe sonst unsichtbar.
        """
        verluste = {
            "besser": {"log_loss": [1.0, 1.0, 1.0, 1.0]},
            "schlechter": {"log_loss": [1.5, 1.5, 1.5, 1.5]},
        }
        eintrag = ab.paired_variant_comparison("besser", "schlechter",
                                               verluste)
        assert eintrag["delta_log_loss"] == pytest.approx(-0.5)

        umgekehrt = ab.paired_variant_comparison("schlechter", "besser",
                                                 verluste)
        assert umgekehrt["delta_log_loss"] == pytest.approx(+0.5)

    def test_gleiche_verluste_ergeben_ein_intervall_um_null(self):
        verluste = {"a": {"log_loss": [1.0, 1.2, 0.9, 1.1]},
                    "b": {"log_loss": [1.0, 1.2, 0.9, 1.1]}}
        eintrag = ab.paired_variant_comparison("a", "b", verluste)
        assert eintrag["delta_log_loss"] == 0.0
        assert eintrag["bootstrap"]["ci_low"] == 0.0
        assert eintrag["bootstrap"]["ci_high"] == 0.0

    def test_das_delta_stimmt_mit_den_aggregaten_ueberein(self, diagnose):
        """
        Die Gegenprobe: Die gepaarte Differenz muss der Differenz der
        beiden Mittelwerte entsprechen. Weichen sie ab, ist die Paarung
        verrutscht.
        """
        nach_name = {v["variant"]: v["aggregate"]["ml"]["log_loss"]
                     for v in diagnose["variants"]}
        for eintrag in diagnose["paired_comparisons"]:
            erwartet = (nach_name[eintrag["variant"]]
                        - nach_name[eintrag["reference"]])
            assert eintrag["delta_log_loss"] == pytest.approx(erwartet)

    def test_das_intervall_umschliesst_den_punktschaetzer(self, diagnose):
        for eintrag in diagnose["paired_comparisons"]:
            intervall = eintrag["bootstrap"]
            assert intervall["ci_low"] <= eintrag["delta_log_loss"] \
                <= intervall["ci_high"]

    def test_der_seed_ist_derselbe_wie_ueberall(self, diagnose):
        for eintrag in diagnose["paired_comparisons"]:
            assert eintrag["bootstrap"]["seed"] == ev.BOOTSTRAP_SEED
            assert eintrag["bootstrap"]["iterations"] \
                == ev.BOOTSTRAP_ITERATIONS

    def test_die_konvention_steht_bei_jedem_vergleich(self, diagnose):
        for eintrag in diagnose["paired_comparisons"]:
            assert eintrag["variant"] in eintrag["delta_convention"]
            assert eintrag["reference"] in eintrag["delta_convention"]
            assert "negativ" in eintrag["delta_convention"]

    def test_alle_vergleiche_beruhen_auf_denselben_spielen(self, diagnose):
        anzahlen = {e["n"] for e in diagnose["paired_comparisons"]}
        assert len(anzahlen) == 1
        assert anzahlen.pop() == diagnose["test_match_count"]

    def test_eine_fehlende_variante_bricht_ab(self):
        with pytest.raises(ValueError, match="fehlt die Variante"):
            ab.paired_variant_comparison("a", "b", {"a": {"log_loss": [1.0]}})

    def test_verschieden_lange_verlustlisten_brechen_ab(self):
        verluste = {"a": {"log_loss": [1.0, 1.0]},
                    "b": {"log_loss": [1.0]}}
        with pytest.raises(ValueError, match="Paarung waere nicht definiert"):
            ab.paired_variant_comparison("a", "b", verluste)

    def test_eine_falsche_spielzahl_bricht_ab(self):
        verluste = {"a": {"log_loss": [1.0, 1.0]},
                    "b": {"log_loss": [1.2, 1.2]}}
        with pytest.raises(ValueError, match="passen nicht zur"):
            ab.paired_variant_comparison("a", "b", verluste, laenge=99)

    def test_die_spielreihenfolge_ist_die_der_auswertung(self, zeilen):
        reihenfolge = ab.evaluation_row_order(zeilen)
        erwartet = []
        for fold in ev.OUTER_FOLDS:
            erwartet.extend(z["row_id"] for z
                            in ev.eligible_rows(zeilen, fold["test_seasons"]))
        assert reihenfolge == erwartet
        assert len(reihenfolge) == len(set(reihenfolge))

    def test_ohne_paare_gibt_es_keine_vergleiche(self, ergebnis):
        """Die erste Stufe bleibt unveraendert."""
        assert ergebnis["paired_comparisons"] == []

    def test_die_verlustlisten_stehen_nicht_im_ergebnis(self, diagnose):
        for variante in diagnose["variants"]:
            assert "_losses" not in variante

    def test_zwei_laeufe_ergeben_dieselben_vergleiche(self, zeilen):
        erst = ab.run_ablation(zeilen, varianten=fg.DIAGNOSTIC_VARIANTS,
                               paare=ab.PAIRED_COMPARISONS)
        zweit = ab.run_ablation(zeilen, varianten=fg.DIAGNOSTIC_VARIANTS,
                                paare=ab.PAIRED_COMPARISONS)
        assert erst["paired_comparisons"] == zweit["paired_comparisons"]


# ---------------------------------------------------------------------------
# 8. Das Artefakt beschriftet, was wirklich gerechnet wurde
# ---------------------------------------------------------------------------

class TestArtefaktaufbau:
    """
    Die Schicht zwischen Rechnung und Datei. Ein Fehler hier veraendert
    keine Zahl - er haengt ihr das falsche Etikett um, und das faellt
    beim Lesen des Artefakts nicht mehr auf.
    """

    def _run_ml(self):
        import run_ml
        return run_ml

    def test_die_fassung_unterscheidet_die_beiden_formen(self):
        """
        Stufe 1 und Stufe 2 haben verschiedene results-Bloecke. Traegen
        beide dieselbe Fassungsnummer, kann ein spaeterer Leser nicht
        entscheiden, ob paired_comparisons fehlt oder nur leer ist.
        """
        assert ab.SCHEMA_VERSION >= 2

    def test_das_ergebnis_traegt_beide_neuen_schluessel(self, diagnose):
        assert "paired_comparisons" in diagnose
        assert "test_match_count" in diagnose

    def test_die_erste_stufe_traegt_sie_ebenfalls_nur_leer(self, ergebnis):
        """Gleiche Form, leerer Inhalt - nicht fehlender Schluessel."""
        assert ergebnis["paired_comparisons"] == []
        assert ergebnis["test_match_count"] > 0

    def test_das_artefakt_nennt_die_gerechneten_varianten(self, diagnose):
        run_ml = self._run_ml()
        payload = run_ml.build_ablation_payload(
            ["bl1"], [2023, 2024, 2025], 6, [], diagnose,
            varianten=fg.DIAGNOSTIC_VARIANTS, aufgabe="ablation_diagnostics",
            paare=ab.PAIRED_COMPARISONS)

        assert payload["configuration"]["variant_order"] \
            == list(fg.DIAGNOSTIC_VARIANT_ORDER)
        assert [z["variant"] for z in payload["results"]["comparison"]] \
            == list(fg.DIAGNOSTIC_VARIANT_ORDER)

    def test_eine_falsche_variantenliste_bricht_ab(self, diagnose):
        """
        Der eigentliche Fehlerfall: Ergebnis der Diagnosestufe, aber
        Variantenliste der ersten Stufe. Das Artefakt waere vollstaendig
        plausibel und vollstaendig falsch beschriftet.
        """
        run_ml = self._run_ml()
        with pytest.raises(ValueError, match="ankuendigen"):
            run_ml.build_ablation_payload(
                ["bl1"], [2023], 6, [], diagnose, varianten=fg.VARIANTS)

    def test_die_paarvergleiche_stehen_in_beiden_bloecken(self, diagnose):
        run_ml = self._run_ml()
        payload = run_ml.build_ablation_payload(
            ["bl1"], [2023], 6, [], diagnose,
            varianten=fg.DIAGNOSTIC_VARIANTS, paare=ab.PAIRED_COMPARISONS)

        angekuendigt = [(e["variant"], e["reference"])
                        for e in payload["configuration"]["paired_comparisons"]]
        gemessen = [(e["variant"], e["reference"])
                    for e in payload["results"]["paired_comparisons"]]
        assert angekuendigt == list(ab.PAIRED_COMPARISONS)
        assert gemessen == angekuendigt

    def test_die_aufgabe_steht_im_artefakt(self, diagnose):
        run_ml = self._run_ml()
        payload = run_ml.build_ablation_payload(
            ["bl1"], [2023], 6, [], diagnose,
            varianten=fg.DIAGNOSTIC_VARIANTS, aufgabe="ablation_diagnostics")
        assert payload["configuration"]["task"] == "ablation_diagnostics"
        assert payload["configuration"]["mode"] == "shadow"

    def test_ein_merkmalsfreies_modell_bricht_die_ausgabe_nicht(self, capsys):
        """
        Wird intercept_only gewaehlt, gibt es Koeffizienten ohne
        Merkmale. Die Ausgabe muss den Achsenabschnitt nennen, statt
        eine leere Zeile zu drucken, die wie ein Fehler aussieht.
        """
        run_ml = self._run_ml()
        variante = {
            "variant": "intercept_only",
            "folds": [{"fold": "fold_1", "coefficients": {
                "home": {"by_feature": [], "intercept": -0.0137},
                "away": {"by_feature": [], "intercept": +0.0253},
            }}],
        }
        run_ml._print_koeffizienten([variante])

        ausgabe = capsys.readouterr().out
        assert "nur Achsenabschnitt" in ausgabe
        assert "-0.0137" in ausgabe
        assert "Faktor" in ausgabe


class TestCliAufgaben:

    def _run_ml(self):
        import run_ml
        return run_ml

    def test_diagnose_und_ablate_schliessen_sich_aus(self, capsys):
        run_ml = self._run_ml()
        assert run_ml.main(["--ablate", "--diagnose"]) == 2
        assert "Je Lauf eine Aufgabe" in capsys.readouterr().out

    def test_ohne_aufgabe_wird_diagnose_mit_angeboten(self, capsys):
        run_ml = self._run_ml()
        assert run_ml.main([]) == 2
        assert "--diagnose" in capsys.readouterr().out

    def test_force_ohne_output_wird_auch_hier_abgewiesen(self, capsys):
        run_ml = self._run_ml()
        assert run_ml.main(["--diagnose", "--force"]) == 2
        assert "--force" in capsys.readouterr().out
