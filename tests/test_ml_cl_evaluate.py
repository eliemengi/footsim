"""
Tests fuer den Champions-League-Shadow-Backtest.

Dieser Backtest soll eine Entscheidung tragen: Traegt das Modell in der
Champions League oder nicht? Ein Fehler hier liefert keine
unplausible Zahl - er liefert eine plausible falsche. Deshalb prueft
jeder Test eine Eigenschaft, die sich tatsaechlich verletzen laesst,
und die Leckagetests arbeiten mit Beobachtern statt mit Zusicherungen.
"""

import json

import pytest

from src.ml import cl_evaluate as cle
from src.ml import dataset as ds
from src.ml import evaluate as ev
from src.ml import feature_groups as fg
from src.ml import model as mdl

SPALTEN = fg.columns_for(cle.CANDIDATE)

#: Alle Modellmerkmale, nicht nur die des Kandidaten. Eine Zeile mit
#: durchgaengig leeren Spalten laesst SimpleImputer diese fallen; die
#: Koeffizientenliste waere dann kuerzer als die Namensliste, und
#: model.coefficients() bricht ab. Das ist richtig so - der Testbestand
#: soll diesen Sonderfall nicht ausloesen, sondern den Regelfall pruefen.
ALLE_MERKMALE = mdl.feature_columns()


# ---------------------------------------------------------------------------
# Bausteine
# ---------------------------------------------------------------------------

def _zeile(league, season, tag, index, eligible=True, stage=None,
           quelle="domestic_pit", tiefe=25):
    from datetime import date, timedelta

    datum = (date(season, 8, 1) + timedelta(days=tag)).isoformat()
    th, ta = (index * 3 + tag) % 4, (index * 5 + tag * 2) % 4
    zeile = {
        "row_id": f"{league}:{season}:{datum}:{index}",
        "match_id": hash((league, season, tag, index)) % 10 ** 8,
        "league": league,
        "competition": "CL" if league == "cl" else "BL1",
        "stage": stage,
        "season": season,
        "date": datum,
        "matchday": tag // 7 + 1,
        "home_id": index,
        "away_id": index + 100,
        "evaluation_eligible": eligible,
        "exclusion_reason": None if eligible else "Testfall",
        "home_profile_source": quelle,
        "away_profile_source": quelle,
        "home_profile_matches": tiefe,
        "away_profile_matches": tiefe,
        "league_avg_source": "season_pit",
        "home_goals": th,
        "away_goals": ta,
        "outcome": 0 if th > ta else (1 if th == ta else 2),
        "baseline_lambda_home": 1.20 + 0.01 * (index % 11),
        "baseline_lambda_away": 1.05 + 0.01 * (index % 7),
    }
    for i, spalte in enumerate(ALLE_MERKMALE):
        zeile[spalte] = 0.05 + ((index * 37 + tag * 17 + i * 5) % 97) / 97.0 * 1.9
    return zeile


def _bestand(liga_anzahl=60, cl_anzahl=40):
    """Ligazeilen 2023-2025 plus CL-Zeilen 2023-2025."""
    zeilen = []
    for season in (2023, 2024, 2025):
        zeilen += [_zeile("bl1", season, i * 4, i) for i in range(liga_anzahl)]
        zeilen += [_zeile("cl", season, i * 6, 500 + i, stage="LEAGUE_STAGE")
                   for i in range(cl_anzahl)]
    return zeilen


@pytest.fixture(scope="module")
def bestand():
    return _bestand()


@pytest.fixture(scope="module")
def ergebnis(bestand):
    return cle.run_cl_evaluation(bestand)


# ---------------------------------------------------------------------------
# 1. Foldbildung
# ---------------------------------------------------------------------------

class TestFolds:

    def test_die_folds_stehen_wie_festgelegt(self):
        assert [f["name"] for f in cle.OUTER_FOLDS] == ["cl_2024", "cl_2025"]
        assert [f["train_seasons"] for f in cle.OUTER_FOLDS] \
            == [[2023], [2023, 2024]]
        assert [f["test_season"] for f in cle.OUTER_FOLDS] == [2024, 2025]

    def test_keine_trainingssaison_liegt_nach_dem_test(self):
        for fold in cle.OUTER_FOLDS:
            assert max(fold["train_seasons"]) < fold["test_season"]

    def test_2023_ist_kein_fold(self):
        """
        Fuer CL 2023 gaebe es keine frueher liegende Ligasaison. Ein
        Fold daraus waere erfunden.
        """
        assert 2023 not in [f["test_season"] for f in cle.OUTER_FOLDS]
        assert 2023 in cle.SEASONS_WITHOUT_TRAINING

    def test_2023_wird_trotzdem_ausgewiesen(self, ergebnis):
        aus = ergebnis["exclusions"]["seasons_without_training_fold"]
        assert "2023" in aus
        assert aus["2023"] > 0, "die Saison wird stillschweigend verschwiegen"

    def test_training_ist_ausschliesslich_liga(self, bestand):
        for fold in cle.OUTER_FOLDS:
            training = cle.league_rows(bestand, fold["train_seasons"])
            assert training
            assert {z["league"] for z in training} == {"bl1"}

    def test_test_ist_ausschliesslich_cl(self, bestand):
        for fold in cle.OUTER_FOLDS:
            test = cle.cl_rows(bestand, fold["test_season"])
            assert test
            assert {z["league"] for z in test} == {"cl"}

    def test_nur_auswertbare_zeilen_kommen_in_den_test(self, bestand):
        zeilen = bestand + [_zeile("cl", 2024, 3, 999, eligible=False,
                                   stage="LAST_16")]
        ids = {z["row_id"] for z in cle.cl_rows(zeilen, 2024)}
        assert "cl:2024:2024-08-04:999" not in ids


# ---------------------------------------------------------------------------
# 2. Leckageschutz
# ---------------------------------------------------------------------------

class TestKeineLeckage:

    def test_kein_cl_spiel_im_training(self, bestand, monkeypatch):
        """
        Der wichtigste Test. league_rows filtert auf league != "cl" -
        faellt dieser Filter weg, traineirt das Modell auf genau den
        Spielen, die es gleich vorhersagen soll.
        """
        gesehen = []
        echt = mdl.fit_side

        def beobachtend(zeilen, seite, alpha, spalten=None):
            gesehen.extend(z["league"] for z in zeilen)
            return echt(zeilen, seite, alpha, spalten)

        monkeypatch.setattr(mdl, "fit_side", beobachtend)
        cle.run_cl_evaluation(bestand)

        assert gesehen, "fit_side wurde nie gerufen"
        assert "cl" not in set(gesehen), (
            f"CL-Zeilen im Training: {sorted(set(gesehen))}")

    def test_die_alphawahl_sieht_kein_cl_spiel(self, bestand, monkeypatch):
        echt = ev.select_candidate
        gesehen = []

        def beobachtend(fit_zeilen, val_zeilen, spalten, alphas=None):
            gesehen.extend(z["league"] for z in fit_zeilen)
            gesehen.extend(z["league"] for z in val_zeilen)
            if alphas is None:
                return echt(fit_zeilen, val_zeilen, spalten)
            return echt(fit_zeilen, val_zeilen, spalten, alphas)

        monkeypatch.setattr(ev, "select_candidate", beobachtend)
        cle.run_cl_evaluation(bestand)

        assert gesehen
        assert "cl" not in set(gesehen)

    def test_die_alphawahl_bleibt_in_ihren_trainingssaisons(self, bestand,
                                                            monkeypatch):
        echt = ev.select_candidate
        saisons = []

        def beobachtend(fit_zeilen, val_zeilen, spalten, alphas=None):
            saisons.append({z["season"] for z in fit_zeilen}
                           | {z["season"] for z in val_zeilen})
            if alphas is None:
                return echt(fit_zeilen, val_zeilen, spalten)
            return echt(fit_zeilen, val_zeilen, spalten, alphas)

        monkeypatch.setattr(ev, "select_candidate", beobachtend)
        cle.run_cl_evaluation(bestand)

        for fold, gesehen in zip(cle.OUTER_FOLDS, saisons):
            assert gesehen <= set(fold["train_seasons"])

    def test_training_und_test_teilen_keine_zeile(self, bestand):
        for fold in cle.OUTER_FOLDS:
            training = {z["row_id"] for z
                        in cle.league_rows(bestand, fold["train_seasons"])}
            test = {z["row_id"] for z in cle.cl_rows(bestand,
                                                     fold["test_season"])}
            assert not training & test

    def test_league_rows_filtert_cl_wirklich_heraus(self, bestand):
        """Gegenprobe: ohne Filter waeren CL-Zeilen dabei."""
        ohne_filter = ev.eligible_rows(bestand, [2023])
        mit_filter = cle.league_rows(bestand, [2023])
        assert len(ohne_filter) > len(mit_filter)
        assert any(z["league"] == "cl" for z in ohne_filter)
        assert not any(z["league"] == "cl" for z in mit_filter)


# ---------------------------------------------------------------------------
# 3. Kandidat und Paarung
# ---------------------------------------------------------------------------

class TestKandidatUndPaarung:

    def test_der_kandidat_steht_vorab_fest(self, ergebnis):
        assert cle.CANDIDATE == "team_profile_cl"
        assert ergebnis["candidate"] == cle.CANDIDATE
        assert ergebnis["feature_columns"] == fg.columns_for(cle.CANDIDATE)
        assert ergebnis["feature_count"] == 16

    def test_der_kandidat_traegt_keine_datentiefe(self, ergebnis):
        assert not [s for s in ergebnis["feature_columns"]
                    if s.endswith("matches_used")]

    def test_die_paarungspruefung_akzeptiert_den_regelfall(self, bestand):
        test = cle.cl_rows(bestand, 2024)
        p = [(0.4, 0.3, 0.3)] * len(test)
        assert cle.assert_paired(test, p, p) is True

    def test_abweichende_groessen_brechen_ab(self, bestand):
        test = cle.cl_rows(bestand, 2024)
        p = [(0.4, 0.3, 0.3)] * len(test)
        with pytest.raises(ValueError, match="Stichprobengroessen"):
            cle.assert_paired(test, p, p[:-1])

    def test_falsche_reihenfolge_bricht_ab(self, bestand):
        test = cle.cl_rows(bestand, 2024)
        verdreht = list(reversed(test))
        p = [(0.4, 0.3, 0.3)] * len(test)
        with pytest.raises(ValueError, match="kanonische"):
            cle.assert_paired(verdreht, p, p)

    def test_doppelte_match_id_bricht_ab(self, bestand):
        test = cle.cl_rows(bestand, 2024)
        doppelt = test[:2] + [dict(test[0], row_id="zz")]
        doppelt = sorted(doppelt, key=lambda z: (z["date"], z["row_id"]))
        p = [(0.4, 0.3, 0.3)] * len(doppelt)
        with pytest.raises(ValueError, match="doppelte match_id"):
            cle.assert_paired(doppelt, p, p)


# ---------------------------------------------------------------------------
# 4. Vorzeichen, Bootstrap, Determinismus
# ---------------------------------------------------------------------------

class TestKennzahlen:

    def test_das_delta_ist_ml_minus_baseline(self, ergebnis):
        z = ergebnis["aggregate"]
        for name in ("log_loss", "brier", "rps"):
            assert z[f"delta_{name}"] == pytest.approx(
                z["ml"][name] - z["baseline"][name])

    def test_das_gilt_auch_je_fold(self, ergebnis):
        for fold in ergebnis["folds"]:
            if "error" in fold:
                continue
            for name in ("log_loss", "brier", "rps"):
                assert fold[f"delta_{name}"] == pytest.approx(
                    fold["ml"][name] - fold["baseline"][name])

    def test_der_bootstrap_ist_gepaart_und_gesetzt(self, ergebnis):
        for name in ("log_loss", "brier", "rps"):
            i = ergebnis["aggregate"]["bootstrap"][name]
            assert i["seed"] == ev.BOOTSTRAP_SEED
            assert i["iterations"] == ev.BOOTSTRAP_ITERATIONS
            assert i["ci_low"] <= i["point"] <= i["ci_high"]

    def test_zwei_laeufe_sind_identisch(self, bestand):
        erst = cle.run_cl_evaluation(bestand)
        zweit = cle.run_cl_evaluation(bestand)
        assert erst == zweit

    def test_die_clampstatistik_liegt_bei(self, ergebnis):
        for fold in ergebnis["folds"]:
            if "error" in fold:
                continue
            c = fold["clamps"]
            assert c["correction_min"] == mdl.CORRECTION_MIN
            assert c["correction_max"] == mdl.CORRECTION_MAX
            assert 0.0 <= c["clamp_rate_home"] <= 1.0
            assert 0.0 <= c["clamp_rate_away"] <= 1.0

    def test_die_mittleren_wahrscheinlichkeiten_summieren_sich(self, ergebnis):
        for fold in ergebnis["folds"]:
            if "error" in fold:
                continue
            for block in ("baseline", "ml", "observed"):
                werte = fold["mean_probabilities"][block]
                assert sum(werte.values()) == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 5. Aufschluesselung
# ---------------------------------------------------------------------------

class TestAufschluesselung:

    def test_es_gibt_alle_drei_aufschluesselungen(self, ergebnis):
        z = ergebnis["aggregate"]
        for feld in ("per_test_season", "per_profile_source",
                     "per_profile_depth"):
            assert z[feld]

    def test_die_herkunftsklassen_sind_die_geforderten(self):
        from src.ml.cl_dataset import (SOURCE_CL_HISTORY, SOURCE_DOMESTIC,
                                       SOURCE_NEUTRAL)

        beide = {"home_profile_source": SOURCE_DOMESTIC,
                 "away_profile_source": SOURCE_DOMESTIC}
        assert cle.profile_source_class(beide) == "beide Seiten domestic_pit"

        gemischt = {"home_profile_source": SOURCE_DOMESTIC,
                    "away_profile_source": SOURCE_CL_HISTORY}
        assert cle.profile_source_class(gemischt) \
            == "mind. eine Seite cl_history_pit"

        neutral = {"home_profile_source": SOURCE_NEUTRAL,
                   "away_profile_source": SOURCE_DOMESTIC}
        assert cle.profile_source_class(neutral) == "mind. eine Seite neutral"

    def test_neutral_gewinnt_gegen_cl_history(self):
        """Die schwaechste Quelle bestimmt die Klasse."""
        from src.ml.cl_dataset import SOURCE_CL_HISTORY, SOURCE_NEUTRAL

        zeile = {"home_profile_source": SOURCE_NEUTRAL,
                 "away_profile_source": SOURCE_CL_HISTORY}
        assert cle.profile_source_class(zeile) == "mind. eine Seite neutral"

    def test_die_tiefenklassen_folgen_den_grenzen(self):
        for tiefe, erwartet in ((6, "6-9"), (9, "6-9"), (10, "10-19"),
                                (19, "10-19"), (20, "20-39"), (39, "20-39"),
                                (40, "40+"), (114, "40+")):
            zeile = {"home_profile_matches": tiefe,
                     "away_profile_matches": tiefe + 5}
            assert cle.depth_class(zeile) == erwartet

    def test_die_duennste_seite_entscheidet(self):
        zeile = {"home_profile_matches": 100, "away_profile_matches": 7}
        assert cle.depth_class(zeile) == "6-9"

    def test_kleine_gruppen_werden_als_deskriptiv_markiert(self):
        zeilen = [_zeile("cl", 2024, i, i, stage="LEAGUE_STAGE")
                  for i in range(5)]
        gruppen = cle._gruppiere(zeilen, [1.0] * 5, [0.9] * 5,
                                 lambda z: "klein", "gruppe")
        assert gruppen[0]["n"] == 5
        assert gruppen[0]["reliable"] is False
        assert "nicht belastbar" in gruppen[0]["note"]

    def test_grosse_gruppen_werden_nicht_markiert(self):
        n = cle.MIN_RELIABLE_N + 5
        zeilen = [_zeile("cl", 2024, i, i, stage="LEAGUE_STAGE")
                  for i in range(n)]
        gruppen = cle._gruppiere(zeilen, [1.0] * n, [0.9] * n,
                                 lambda z: "gross", "gruppe")
        assert gruppen[0]["reliable"] is True
        assert gruppen[0]["note"] is None


# ---------------------------------------------------------------------------
# 6. Urteilslogik - vorab festgelegt
# ---------------------------------------------------------------------------

class TestUrteil:

    @staticmethod
    def _zusammen(delta, ci_low, ci_high, n=200):
        return {"n": n, "delta_log_loss": delta,
                "bootstrap": {"log_loss": {"point": delta, "ci_low": ci_low,
                                           "ci_high": ci_high}}}

    @staticmethod
    def _folds(*deltas):
        return [{"fold": f"f{i}", "delta_log_loss": d}
                for i, d in enumerate(deltas)]

    def test_pass_wenn_intervall_vollstaendig_unter_null(self):
        u = cle.verdict(self._zusammen(-0.02, -0.03, -0.01),
                        self._folds(-0.02, -0.02))
        assert u["verdict"] == "PASS"

    def test_inconclusive_wenn_intervall_die_null_enthaelt(self):
        u = cle.verdict(self._zusammen(-0.009, -0.03, +0.011),
                        self._folds(-0.012, -0.005))
        assert u["verdict"] == "INCONCLUSIVE"

    def test_fail_wenn_delta_nicht_negativ(self):
        u = cle.verdict(self._zusammen(+0.004, -0.01, +0.02),
                        self._folds(+0.004, +0.004))
        assert u["verdict"] == "FAIL"

    def test_fail_bei_schwerem_qualitaetsabfall_in_einem_fold(self):
        """Auch bei gutem Mittelwert."""
        u = cle.verdict(self._zusammen(-0.02, -0.03, -0.01),
                        self._folds(-0.05, +cle.SEVERE_DEGRADATION))
        assert u["verdict"] == "FAIL"
        assert any("Qualitaetsabfall" in g for g in u["reasons"])

    def test_vorzeichenwiderspruch_verhindert_pass(self):
        u = cle.verdict(self._zusammen(-0.02, -0.03, -0.01),
                        self._folds(-0.04, +0.005))
        assert u["verdict"] == "INCONCLUSIVE"
        assert any("widersprechen" in g for g in u["reasons"])

    def test_zu_kleine_stichprobe_ist_inconclusive(self):
        u = cle.verdict(self._zusammen(-0.02, -0.03, -0.01, n=10),
                        self._folds(-0.02, -0.02))
        assert u["verdict"] == "INCONCLUSIVE"

    def test_ohne_aggregat_ist_es_fail(self):
        assert cle.verdict(None, [])["verdict"] == "FAIL"

    def test_die_regeln_stehen_im_ergebnis(self, ergebnis):
        k = ergebnis["verdict"]["criteria"]
        assert k["severe_degradation_threshold"] == cle.SEVERE_DEGRADATION
        assert "vor der messung festgelegt" in k[
            "severe_degradation_rationale"].lower()
        assert k["min_reliable_n"] == cle.MIN_RELIABLE_N

    def test_das_urteil_ist_eines_der_drei(self, ergebnis):
        assert ergebnis["verdict"]["verdict"] in (
            "PASS", "INCONCLUSIVE", "FAIL")


# ---------------------------------------------------------------------------
# 7. Fingerabdruck und Ausschluesse
# ---------------------------------------------------------------------------

class TestFingerabdruck:

    @staticmethod
    def _hash(zeilen):
        return cle.dataset_fingerprint(zeilen)["sha256"]

    # -- Umfang ------------------------------------------------------------

    def test_er_deckt_alle_geforderten_felder_ab(self):
        spalten = cle.fingerprint_columns()
        for pflicht in ("row_id", "outcome", "baseline_lambda_home",
                        "baseline_lambda_away", "evaluation_eligible",
                        "season", "league"):
            assert pflicht in spalten

    def test_er_deckt_jedes_merkmal_des_kandidaten_ab(self):
        spalten = cle.fingerprint_columns()
        for merkmal in fg.columns_for(cle.CANDIDATE):
            assert merkmal in spalten

    def test_er_deckt_die_herkunftsfelder_ab(self):
        spalten = cle.fingerprint_columns()
        for feld in ("home_profile_source", "away_profile_source",
                     "home_profile_matches", "away_profile_matches"):
            assert feld in spalten

    def test_die_spaltenreihenfolge_ist_deterministisch(self):
        assert cle.fingerprint_columns() == cle.fingerprint_columns()
        merkmale = fg.columns_for(cle.CANDIDATE)
        spalten = cle.fingerprint_columns()
        # Die Merkmale stehen als zusammenhaengender Block in genau der
        # Reihenfolge, die auch das Modell bekommt.
        start = spalten.index(merkmale[0])
        assert spalten[start:start + len(merkmale)] == merkmale

    def test_keine_spalte_steht_doppelt(self):
        spalten = cle.fingerprint_columns()
        assert len(spalten) == len(set(spalten))

    # -- Verhalten ---------------------------------------------------------

    def test_identischer_datensatz_ergibt_identischen_hash(self, bestand):
        kopie = [dict(z) for z in bestand]
        assert self._hash(kopie) == self._hash(bestand)
        assert cle.dataset_fingerprint(kopie) == cle.dataset_fingerprint(bestand)

    def test_geaenderte_zeilenreihenfolge_aendert_den_hash_nicht(self, bestand):
        assert self._hash(list(reversed(bestand))) == self._hash(bestand)

        gemischt = bestand[7:] + bestand[:7]
        assert self._hash(gemischt) == self._hash(bestand)

    @pytest.mark.parametrize("merkmal_index", [0, 5, 15])
    def test_ein_geaenderter_featurewert_aendert_den_hash(self, bestand,
                                                          merkmal_index):
        """
        Genau die Luecke der ersten Fassung: Sie erfasste keinen
        einzigen Merkmalswert. Zwei Bestaende mit gleichen Ergebnissen,
        aber verschiedenen Profilen trugen denselben Fingerabdruck.
        """
        merkmal = fg.columns_for(cle.CANDIDATE)[merkmal_index]
        geaendert = [dict(z) for z in bestand]
        geaendert[0][merkmal] = geaendert[0][merkmal] + 0.5
        assert self._hash(geaendert) != self._hash(bestand), merkmal

    def test_jedes_einzelne_merkmal_wird_erfasst(self, bestand):
        """Die Gegenprobe ueber ALLE 16 Merkmale, nicht nur drei."""
        basis = self._hash(bestand)
        for merkmal in fg.columns_for(cle.CANDIDATE):
            geaendert = [dict(z) for z in bestand]
            geaendert[0][merkmal] = geaendert[0][merkmal] + 0.5
            assert self._hash(geaendert) != basis, merkmal

    def test_eine_geaenderte_zielvariable_aendert_den_hash(self, bestand):
        geaendert = [dict(z) for z in bestand]
        geaendert[0]["outcome"] = (geaendert[0]["outcome"] + 1) % 3
        assert self._hash(geaendert) != self._hash(bestand)

    @pytest.mark.parametrize("spalte", ["baseline_lambda_home",
                                        "baseline_lambda_away"])
    def test_eine_geaenderte_baseline_aendert_den_hash(self, bestand, spalte):
        geaendert = [dict(z) for z in bestand]
        geaendert[0][spalte] = geaendert[0][spalte] + 0.1
        assert self._hash(geaendert) != self._hash(bestand)

    def test_geaenderte_eligibility_aendert_den_hash(self, bestand):
        """
        Sie entscheidet ueber Bestandszugehoerigkeit - eine Aenderung
        verschiebt die Messung, ohne einen Merkmalswert anzufassen.
        """
        geaendert = [dict(z) for z in bestand]
        geaendert[0]["evaluation_eligible"] = not geaendert[0][
            "evaluation_eligible"]
        assert self._hash(geaendert) != self._hash(bestand)

    @pytest.mark.parametrize("spalte,wert", [
        ("league", "pl"), ("season", 2099),
        ("home_profile_source", "cl_history_pit"),
        ("away_profile_matches", 999),
        ("exclusion_reason", "anderer Grund"),
    ])
    def test_herkunft_und_zugehoerigkeit_aendern_den_hash(self, bestand,
                                                          spalte, wert):
        geaendert = [dict(z) for z in bestand]
        geaendert[0][spalte] = wert
        assert self._hash(geaendert) != self._hash(bestand)

    def test_ein_nicht_gelesenes_feld_aendert_den_hash_nicht(self, bestand):
        """
        Die Gegenrichtung: matches_used steht ausdruecklich NICHT im
        Kandidaten und wird von diesem Backtest nicht gelesen. Wuerde
        es den Fingerabdruck bewegen, meldete er Unterschiede, die das
        Ergebnis nicht beruehren.
        """
        geaendert = [dict(z, home_matches_used=999) for z in bestand]
        assert self._hash(geaendert) == self._hash(bestand)

    def test_der_fingerabdruck_nennt_seinen_umfang(self, bestand):
        f = cle.dataset_fingerprint(bestand)
        assert f["rows"] == len(bestand)
        assert f["candidate"] == cle.CANDIDATE
        assert f["column_count"] == len(f["columns"]) > 20
        assert len(f["sha256"]) == 64

    def test_die_ausschluesse_werden_gezaehlt(self, bestand):
        zeilen = bestand + [_zeile("cl", 2024, 5, 998, eligible=False,
                                   stage="LAST_16")]
        aus = cle.excluded_summary(zeilen)
        assert aus["cl_rows_loaded"] == aus["cl_rows_eligible"] \
            + aus["cl_rows_excluded"]
        assert aus["cl_rows_excluded"] >= 1
        assert aus["exclusion_reasons"]


# ---------------------------------------------------------------------------
# 8. Die bestehende Ligaauswertung bleibt unberuehrt
# ---------------------------------------------------------------------------

class TestLigaauswertungUnveraendert:

    def test_die_ligafolds_sind_unveraendert(self):
        assert [f["train_seasons"] for f in ev.OUTER_FOLDS] \
            == [[2023], [2023, 2024]]
        assert [f["test_seasons"] for f in ev.OUTER_FOLDS] \
            == [[2024], [2025]]

    def test_der_cl_backtest_hat_eigene_folds(self):
        """Zwei Verfahren, zwei Definitionen - keine Ueberschreibung."""
        assert cle.OUTER_FOLDS is not ev.OUTER_FOLDS
        assert "test_season" in cle.OUTER_FOLDS[0]
        assert "test_seasons" in ev.OUTER_FOLDS[0]

    def test_die_ligaauswertung_laeuft_weiterhin(self, bestand):
        """
        Gegenprobe: Der bestehende Weg muss auf reinen Ligazeilen
        unveraendert durchlaufen.
        """
        liga = [z for z in bestand if z["league"] != "cl"]
        ergebnis = ev.run_evaluation(liga)
        assert ergebnis["aggregate"]["n"] > 0
        assert ergebnis["feature_columns"] == mdl.feature_columns()


# ---------------------------------------------------------------------------
# 9. CLI-Schutz des CL-Backtests
# ---------------------------------------------------------------------------

class TestCliEvaluateCl:

    def _run_ml(self):
        import run_ml
        return run_ml

    def test_evaluate_cl_schliesst_die_anderen_aufgaben_aus(self, capsys):
        run_ml = self._run_ml()
        for andere in ("--evaluate", "--ablate", "--diagnose",
                       "--build-dataset"):
            assert run_ml.main(["--evaluate-cl", andere]) == 2
            assert "Je Lauf eine Aufgabe" in capsys.readouterr().out

    def test_ohne_aufgabe_wird_evaluate_cl_mit_angeboten(self, capsys):
        run_ml = self._run_ml()
        assert run_ml.main([]) == 2
        assert "--evaluate-cl" in capsys.readouterr().out

    def test_dataset_nur_mit_evaluate_cl(self, capsys):
        run_ml = self._run_ml()
        assert run_ml.main(["--build-dataset", "--dataset", "x.json"]) == 2
        assert "--dataset" in capsys.readouterr().out

    def test_force_ohne_output_wird_abgewiesen(self, capsys):
        run_ml = self._run_ml()
        assert run_ml.main(["--evaluate-cl", "--force"]) == 2
        assert "--force" in capsys.readouterr().out

    def test_ein_datensatz_ohne_cl_zeilen_bricht_ab(self, tmp_path):
        run_ml = self._run_ml()
        pfad = tmp_path / "ohne_cl.json"
        pfad.write_text(json.dumps({
            "manifest": {"schema_version": ds.SCHEMA_VERSION},
            "rows": [{"row_id": "a", "league": "bl1"}],
        }), encoding="utf-8")

        with pytest.raises(ValueError, match="keine CL-Zeilen"):
            run_ml.load_dataset_rows(str(pfad))

    def test_eine_falsche_datensatzfassung_bricht_ab(self, tmp_path):
        run_ml = self._run_ml()
        pfad = tmp_path / "alt.json"
        pfad.write_text(json.dumps({
            "manifest": {"schema_version": 1},
            "rows": [{"row_id": "a", "league": "cl"}],
        }), encoding="utf-8")

        with pytest.raises(ValueError, match="Datensatzfassung"):
            run_ml.load_dataset_rows(str(pfad))

    def test_ein_leerer_datensatz_bricht_ab(self, tmp_path):
        run_ml = self._run_ml()
        pfad = tmp_path / "leer.json"
        pfad.write_text(json.dumps({"manifest": {}, "rows": []}),
                        encoding="utf-8")
        with pytest.raises(ValueError, match="keine Zeilen"):
            run_ml.load_dataset_rows(str(pfad))


class TestArtefakt:

    def test_das_artefakt_traegt_die_geforderten_felder(self, bestand,
                                                        ergebnis):
        import run_ml

        payload = run_ml.build_cl_evaluation_payload(
            ["bl1"], [2023, 2024, 2025], 6, bestand, ergebnis,
            {"kind": "in_process"})

        m, k, r = payload["manifest"], payload["configuration"], payload["results"]
        assert m["schema_version"] == cle.SCHEMA_VERSION
        assert m["dataset_schema_version"] == ds.SCHEMA_VERSION
        assert m["dataset_fingerprint"]["sha256"]
        assert m["created_at"] and "git_commit" in m and "git_dirty" in m
        assert k["task"] == "cl_shadow_backtest"
        assert k["mode"] == "shadow"
        assert k["candidate"] == cle.CANDIDATE
        assert k["feature_columns"] == fg.columns_for(cle.CANDIDATE)
        assert k["outer_folds"] and k["alpha_candidates"]
        assert k["bootstrap_seed"] == ev.BOOTSTRAP_SEED
        assert k["decision_rules"]["severe_degradation_threshold"] \
            == cle.SEVERE_DEGRADATION
        assert r["verdict"]["verdict"] in ("PASS", "INCONCLUSIVE", "FAIL")
        assert r["exclusions"]["cl_rows_loaded"] > 0

    def test_der_fingerabdruck_steht_im_artefakt(self, bestand, ergebnis):
        import run_ml

        payload = run_ml.build_cl_evaluation_payload(
            ["bl1"], [2023], 6, bestand, ergebnis, {"kind": "in_process"})
        assert payload["manifest"]["dataset_fingerprint"] \
            == cle.dataset_fingerprint(bestand)
