"""
Der CLI-Erzeuger fuer die GO3-/GO4.5-Backtests.

WARUM ES IHN GIBT
-----------------
Die beiden Ergebnisdateien unter data/ hatten keinen committeten
Erzeuger: run_backtest() wurde ausschliesslich aus Tests aufgerufen, die
Aggregation ueber fuenf Ligen und mehrere Saisons stand nirgends im
Repository. Der bekannte Stand - GO3 mit 1,01598, GO4.5 mit 1,02044 -
war damit nicht nachrechenbar.

Diese Tests sichern die drei Eigenschaften, an denen das haengt:

    Gewichtung    LogLoss ist ein Mittelwert JE SPIEL. Ein ungewichteter
                  Mittelwert ueber Liga-Saisons zaehlte ein
                  Bundesligaspiel schwerer als ein englisches.

    Trennung      Zeitstempel und Git-Stand gehoeren ins Manifest, nie
                  in die Messergebnisse. Sonst sieht jeder Lauf
                  verschieden aus und Reproduzierbarkeit ist nicht
                  pruefbar.

    Schutz        Die vorhandenen Referenzdateien sind der einzige Beleg
                  fuer den bisherigen Messstand. Sie duerfen nicht
                  stillschweigend verschwinden.

Die meisten Tests arbeiten mit synthetischen Teilergebnissen. Der echte
Backtest ist zu langsam fuer eine Suite, die bei jedem Lauf mitlaeuft -
ein einziger kleiner Durchlauf steht als Kontaktprobe am Ende.
"""

import json
import os

import pytest

import run_backtests


def bins(*eintraege):
    """calibration_bins in der Form von _Accumulator.result()."""
    return [{"bin": grenze, "predicted": vorhergesagt,
             "observed": beobachtet, "n": anzahl}
            for grenze, vorhergesagt, beobachtet, anzahl in eintraege]


def teil(n, log_loss, brier=0.6, rps=0.2, **extra):
    """Ein Teilergebnis in der Form von _Accumulator.result()."""
    basis = {
        "n": n,
        "log_loss": log_loss,
        "brier": brier,
        "rps": rps,
        "accuracy_supplementary": 0.5,
        "calibration_error": 0.03,
        "calibration_bins": bins(("0.0-0.1", 0.05, 0.05, 3 * n)),
        "avg_probability_change": 0.0,
        "max_probability_change": 0.0,
        "clamp_rate": 0.0,
    }
    basis.update(extra)
    return basis


def lauf(league, season, **varianten):
    """Eine run_backtest()-Rueckgabe."""
    return {"league": league, "season": season, "skipped_warmup": 0,
            "variants": varianten}


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

class TestGewichteteAggregation:

    def test_die_spielzahl_ist_das_gewicht(self):
        """
        Der Kern. Zwei Liga-Saisons mit sehr verschiedener Spielzahl:
        Das Ergebnis muss naeher an der groesseren liegen.

            (1.0 * 100 + 2.0 * 300) / 400 = 1.75
        """
        ergebnis = run_backtests.aggregate_variant([
            teil(100, 1.0),
            teil(300, 2.0),
        ])
        assert ergebnis["n"] == 400
        assert ergebnis["log_loss"] == pytest.approx(1.75)

    def test_ungewichtet_waere_etwas_anderes(self):
        """
        Die Gegenprobe, damit der Test oben nicht zufaellig besteht: Das
        ungewichtete Mittel derselben Zahlen waere 1.5, nicht 1.75.
        """
        ergebnis = run_backtests.aggregate_variant([
            teil(100, 1.0),
            teil(300, 2.0),
        ])
        assert ergebnis["log_loss"] != pytest.approx(1.5)

    def test_gleiche_spielzahl_ergibt_das_einfache_mittel(self):
        ergebnis = run_backtests.aggregate_variant([
            teil(200, 1.0),
            teil(200, 2.0),
        ])
        assert ergebnis["log_loss"] == pytest.approx(1.5)

    @pytest.mark.parametrize("feld", [
        "log_loss", "brier", "rps", "accuracy_supplementary",
        "avg_probability_change", "clamp_rate",
    ])
    def test_alle_mittelwertkennzahlen_werden_gewichtet(self, feld):
        a = teil(100, 1.0); a[feld] = 1.0
        b = teil(300, 1.0); b[feld] = 2.0
        ergebnis = run_backtests.aggregate_variant([a, b])
        assert ergebnis[feld] == pytest.approx(1.75), feld

    def test_max_probability_change_nimmt_das_maximum(self):
        """
        Eine groesste Einzelaenderung ist kein Mittelwert - sie zu
        mitteln wuerde den Ausreisser gerade verschwinden lassen, den
        sie sichtbar machen soll.
        """
        ergebnis = run_backtests.aggregate_variant([
            teil(100, 1.0, max_probability_change=0.05),
            teil(300, 1.0, max_probability_change=0.20),
        ])
        assert ergebnis["max_probability_change"] == pytest.approx(0.20)

    def test_fehlende_werte_verfaelschen_das_gewicht_nicht(self):
        """
        Traegt eine Teilmenge einen Wert nicht, darf sie nicht als Null
        einfliessen - sonst zoege ein fehlender Wert das Ergebnis nach
        unten, statt einfach nicht mitzuzaehlen.
        """
        ergebnis = run_backtests.aggregate_variant([
            teil(100, 1.0, clamp_rate=0.10),
            teil(300, 1.0, clamp_rate=None),
        ])
        assert ergebnis["clamp_rate"] == pytest.approx(0.10)

    def test_leere_eingabe_ergibt_nichts(self):
        assert run_backtests.aggregate_variant([]) is None
        assert run_backtests.aggregate_variant([None, None]) is None

    def test_teilmengen_ohne_spiele_zaehlen_nicht(self):
        ergebnis = run_backtests.aggregate_variant([
            teil(0, 99.0),
            teil(200, 1.0),
        ])
        assert ergebnis["n"] == 200
        assert ergebnis["log_loss"] == pytest.approx(1.0)

    def test_alle_varianten_werden_zusammengefuehrt(self):
        ergebnis = run_backtests.aggregate_all([
            lauf("bl1", 2024, baseline=teil(100, 1.0), full_go3=teil(100, 1.1)),
            lauf("pl", 2024, baseline=teil(300, 2.0), full_go3=teil(300, 2.1)),
        ])
        assert sorted(ergebnis) == ["baseline", "full_go3"]
        assert ergebnis["baseline"]["n"] == 400
        assert ergebnis["baseline"]["log_loss"] == pytest.approx(1.75)
        assert ergebnis["full_go3"]["log_loss"] == pytest.approx(1.85)


class TestKalibrierungWirdGepoolt:
    """
    Der Kalibrierungsfehler ist KEIN Mittelwert je Spiel, sondern eine
    Summe von Absolutbetraegen ueber Wahrscheinlichkeitsbins. Der Betrag
    muss gebildet werden, NACHDEM die Beobachtungen je Bin
    zusammengefuehrt sind.
    """

    def test_entgegengesetzte_abweichungen_heben_sich_auf(self):
        """
        Der geforderte Gegenbeweis.

        Zwei gleich grosse Teilmengen weichen im selben Bin um genau
        dasselbe ab - eine nach oben, eine nach unten:

            A: vorhergesagt 0.30, beobachtet 0.40  ->  Fehler 0.10
            B: vorhergesagt 0.30, beobachtet 0.20  ->  Fehler 0.10

        Der gewichtete Mittelwert der Einzelfehler waere 0.10.
        Gepoolt ist die beobachtete Haeufigkeit aber (0.40+0.20)/2 = 0.30
        und damit exakt die vorhergesagte - der globale Fehler ist NULL.

        Die beiden Verfahren liefern hier 0.10 gegen 0.00. Genau deshalb
        ist die Gewichtung falsch.
        """
        a = teil(100, 1.0, calibration_error=0.10,
                 calibration_bins=bins(("0.3-0.4", 0.30, 0.40, 300)))
        b = teil(100, 1.0, calibration_error=0.10,
                 calibration_bins=bins(("0.3-0.4", 0.30, 0.20, 300)))

        gewichtet = (0.10 * 100 + 0.10 * 100) / 200
        ergebnis = run_backtests.aggregate_variant([a, b])

        assert gewichtet == pytest.approx(0.10)
        assert ergebnis["calibration_error"] == pytest.approx(0.0, abs=1e-9)
        assert ergebnis["calibration_error"] != pytest.approx(gewichtet)

    def test_gleichgerichtete_abweichungen_bleiben_erhalten(self):
        """
        Die Gegenprobe: Weichen beide in dieselbe Richtung ab, darf sich
        nichts aufheben.
        """
        a = teil(100, 1.0, calibration_bins=bins(("0.3-0.4", 0.30, 0.40, 300)))
        b = teil(100, 1.0, calibration_bins=bins(("0.3-0.4", 0.30, 0.40, 300)))

        ergebnis = run_backtests.aggregate_variant([a, b])
        assert ergebnis["calibration_error"] == pytest.approx(0.10)

    def test_bins_werden_ueber_ihre_beobachtungszahl_gewichtet(self):
        """
        Innerhalb eines Bins zaehlt die Beobachtungszahl, nicht die Zahl
        der Liga-Saisons.

            (0.40 * 100 + 0.20 * 300) / 400 = 0.25
            Fehler = |0.30 - 0.25| = 0.05
        """
        a = teil(100, 1.0, calibration_bins=bins(("0.3-0.4", 0.30, 0.40, 100)))
        b = teil(300, 1.0, calibration_bins=bins(("0.3-0.4", 0.30, 0.20, 300)))

        ergebnis = run_backtests.aggregate_variant([a, b])
        assert ergebnis["calibration_error"] == pytest.approx(0.05)

    def test_mehrere_bins_werden_ueber_ihre_groesse_gewichtet(self):
        """
            Bin A: |0.10 - 0.20| = 0.10 bei n=100
            Bin B: |0.60 - 0.60| = 0.00 bei n=300
            gesamt = (0.10 * 100 + 0.00 * 300) / 400 = 0.025
        """
        eintrag = teil(100, 1.0, calibration_bins=bins(
            ("0.1-0.2", 0.10, 0.20, 100),
            ("0.6-0.7", 0.60, 0.60, 300)))

        ergebnis = run_backtests.aggregate_variant([eintrag])
        assert ergebnis["calibration_error"] == pytest.approx(0.025)

    def test_die_zusammengefuehrten_bins_stehen_im_ergebnis(self):
        a = teil(100, 1.0, calibration_bins=bins(("0.3-0.4", 0.30, 0.40, 100)))
        b = teil(300, 1.0, calibration_bins=bins(("0.3-0.4", 0.30, 0.20, 300)))

        gepoolt = run_backtests.aggregate_variant([a, b])["calibration_bins"]
        assert len(gepoolt) == 1
        assert gepoolt[0]["bin"] == "0.3-0.4"
        assert gepoolt[0]["n"] == 400
        assert gepoolt[0]["observed"] == pytest.approx(0.25)

    def test_bins_verschiedener_grenzen_bleiben_getrennt(self):
        a = teil(100, 1.0, calibration_bins=bins(("0.1-0.2", 0.15, 0.15, 100)))
        b = teil(100, 1.0, calibration_bins=bins(("0.8-0.9", 0.85, 0.85, 100)))

        gepoolt = run_backtests.aggregate_variant([a, b])["calibration_bins"]
        assert [e["bin"] for e in gepoolt] == ["0.1-0.2", "0.8-0.9"]

    def test_ohne_bins_gibt_es_keinen_wert_und_einen_hinweis(self):
        """
        Still auf den falschen gewichteten Mittelwert zurueckzufallen
        waere schlimmer als keine Zahl - der Fehler bliebe unsichtbar.
        """
        a = teil(100, 1.0, calibration_error=0.10)
        b = teil(300, 1.0, calibration_error=0.20)
        b["calibration_bins"] = None

        ergebnis = run_backtests.aggregate_variant([a, b])
        assert ergebnis["calibration_error"] is None
        assert "calibration_bins" in ergebnis["calibration_note"]

    def test_der_einzelwert_wird_nicht_mehr_uebernommen(self):
        """
        calibration_error der Teilmenge wird ignoriert - massgeblich sind
        allein die Bins. Hier widersprechen sich beide absichtlich.
        """
        eintrag = teil(100, 1.0, calibration_error=0.99,
                       calibration_bins=bins(("0.3-0.4", 0.30, 0.30, 300)))

        ergebnis = run_backtests.aggregate_variant([eintrag])
        assert ergebnis["calibration_error"] == pytest.approx(0.0, abs=1e-9)

    def test_leere_bins_ergeben_keinen_wert(self):
        eintrag = teil(100, 1.0, calibration_bins=[])
        ergebnis = run_backtests.aggregate_variant([eintrag])
        assert ergebnis["calibration_error"] is None


class TestGitArbeitsstand:
    """
    Ein Lauf mit geaendertem ODER unversioniertem Code darf niemals als
    sauber erscheinen. Die erste Fassung liess Eintraege mit doppeltem
    Fragezeichen aus - und meldete deshalb "sauber" fuer Laeufe, deren
    ausfuehrendes Skript im genannten Commit gar nicht enthalten war.
    """

    def _mit_status(self, monkeypatch, ausgabe):
        class Ergebnis:
            returncode = 0
            stdout = ausgabe

        monkeypatch.setattr(run_backtests.subprocess, "run",
                            lambda *a, **k: Ergebnis())
        return run_backtests.git_arbeitsstand()

    def test_sauberes_verzeichnis(self, monkeypatch):
        stand = self._mit_status(monkeypatch, "")
        assert stand["dirty"] is False
        assert stand["porcelain"] == []

    def test_unversionierte_datei_zaehlt_als_dirty(self, monkeypatch):
        """Die eigentliche Korrektur."""
        stand = self._mit_status(monkeypatch, "?? run_backtests.py\n")
        assert stand["dirty"] is True
        assert stand["untracked"] == ["run_backtests.py"]
        assert stand["modified"] == []

    def test_geaenderte_datei_zaehlt_als_dirty(self, monkeypatch):
        stand = self._mit_status(monkeypatch, " M src/features/go3.py\n")
        assert stand["dirty"] is True
        assert stand["modified"] == ["src/features/go3.py"]

    def test_vorgemerkte_datei_zaehlt_als_dirty(self, monkeypatch):
        stand = self._mit_status(monkeypatch, "A  neu.py\n")
        assert stand["dirty"] is True
        assert stand["staged"] == ["neu.py"]

    def test_beides_zusammen(self, monkeypatch):
        stand = self._mit_status(
            monkeypatch, " M app.py\n?? run_backtests.py\n?? tests/x.py\n")
        assert stand["dirty"] is True
        assert stand["modified"] == ["app.py"]
        assert stand["untracked"] == ["run_backtests.py", "tests/x.py"]

    def test_der_porcelain_status_bleibt_vollstaendig(self, monkeypatch):
        """Der Beleg gehoert ins Manifest, nicht nur die Aussage."""
        stand = self._mit_status(monkeypatch, " M app.py\n?? neu.py\n")
        assert stand["porcelain"] == [" M app.py", "?? neu.py"]

    def test_ohne_git_gibt_es_keine_behauptung(self, monkeypatch):
        def scheitert(*a, **k):
            raise OSError("kein git")

        monkeypatch.setattr(run_backtests.subprocess, "run", scheitert)
        assert run_backtests.git_arbeitsstand() is None

    def test_das_manifest_traegt_dirty_und_status(self):
        payload = run_backtests.build_payload(
            "go3", ["bl1"], [2024], 6,
            [lauf("bl1", 2024, baseline=teil(251, 1.0))], [])

        assert "git_dirty" in payload["manifest"]
        assert "git_status" in payload["manifest"]
        assert "git_clean" not in payload["manifest"], (
            "das alte, irrefuehrende Feld darf nicht zurueckkehren")

    def test_dieser_lauf_meldet_sich_selbst_als_dirty(self):
        """
        Solange run_backtests.py unversioniert ist, MUSS jedes Manifest
        dirty melden. Nach dem Commit wird dieser Test von selbst zur
        Aussage ueber ein sauberes Verzeichnis.
        """
        stand = run_backtests.git_arbeitsstand()
        if stand is None:
            pytest.skip("kein Git verfuegbar")

        verdaechtig = [p for p in stand["untracked"] + stand["modified"]
                       if p.endswith("run_backtests.py")]
        if verdaechtig:
            assert stand["dirty"] is True


class TestAggregationTrifftDenBekanntenStand:
    """
    Die Gewichtung wird an den echten Zahlen geprueft, nicht nur an
    ausgedachten. Grundlage sind die Spielzahlen der 15 Liga-Saisons.
    """

    #: (Liga, Saison, Spiele) - aus data/go3_backtest_result.json.
    SPIELZAHLEN = [
        ("bl1", 2023, 252), ("pl", 2023, 313), ("pd", 2023, 319),
        ("sa", 2023, 320), ("fl1", 2023, 252),
        ("bl1", 2024, 251), ("pl", 2024, 320), ("pd", 2024, 319),
        ("sa", 2024, 320), ("fl1", 2024, 251),
        ("bl1", 2025, 252), ("pl", 2025, 320), ("pd", 2025, 320),
        ("sa", 2025, 320), ("fl1", 2025, 251),
    ]

    def test_die_spielzahlen_summieren_sich_zu_4380(self):
        assert sum(n for _, _, n in self.SPIELZAHLEN) == 4380

    def test_zwei_saisons_ergeben_die_2924_der_go45_referenz(self):
        """
        Der Beleg fuer die abweichende Baseline: Die GO4.5-Referenz
        deckte 2024 und 2025 ab, die GO3-Referenz alle drei Saisons.
        Verschiedene Stichproben, verschiedene Zahlen - kein Fehler in
        der Rechnung.
        """
        zwei = sum(n for _, s, n in self.SPIELZAHLEN if s in (2024, 2025))
        assert zwei == 2924


# ---------------------------------------------------------------------------
# Aufbau der Ausgabe
# ---------------------------------------------------------------------------

class TestAusgabeaufbau:

    def _payload(self):
        return run_backtests.build_payload(
            "go3", ["bl1", "pl"], [2024], 6,
            [lauf("bl1", 2024, baseline=teil(251, 1.0)),
             lauf("pl", 2024, baseline=teil(320, 2.0))],
            [])

    def test_manifest_und_ergebnisse_sind_getrennt(self):
        """
        Ohne diese Trennung waere ein Reproduzierbarkeitsvergleich
        unmoeglich - der Zeitstempel allein liesse jeden Lauf
        verschieden aussehen.
        """
        payload = self._payload()
        assert set(payload) == {"manifest", "results"}
        assert "created_at" in payload["manifest"]
        assert "created_at" not in json.dumps(payload["results"])

    @pytest.mark.parametrize("feld", [
        "schema_version", "suite", "git_commit", "leagues", "seasons",
        "min_matchday", "matches_evaluated", "variants", "created_at",
        "python_version",
    ])
    def test_manifest_traegt_die_geforderten_felder(self, feld):
        assert feld in self._payload()["manifest"], feld

    def test_die_spielzahl_stammt_aus_der_baseline(self):
        assert self._payload()["manifest"]["matches_evaluated"] == 571

    def test_ergebnisse_sind_zwischen_zwei_aufrufen_gleich(self):
        """
        Derselbe Eingang muss denselben Ausgang ergeben - das Manifest
        ausgenommen, das absichtlich variiert.
        """
        a = self._payload()["results"]
        b = self._payload()["results"]
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_uebersprungene_kombinationen_bleiben_sichtbar(self):
        """Eine Luecke darf nicht wie eine Messung aussehen."""
        payload = run_backtests.build_payload(
            "go3", ["bl1"], [1999], 6,
            [lauf("bl1", 2024, baseline=teil(10, 1.0))],
            [{"league": "bl1", "season": 1999, "reason": "keine Saisondaten"}])
        assert payload["results"]["skipped"][0]["season"] == 1999
        assert payload["manifest"]["league_seasons_skipped"] == 1

    def test_go45_zusatzfelder_werden_uebernommen(self):
        """
        Abdeckung und Poolsaison erklaeren die Spielzahl und gehoeren
        deshalb ins Ergebnis, nicht nur in die Konsole.
        """
        roh = lauf("bl1", 2024, baseline=teil(251, 1.0))
        roh["player_pool_season"] = 2023
        roh["matches_without_team_mapping"] = 4
        payload = run_backtests.build_payload("go45", ["bl1"], [2024], 6,
                                              [roh], [])
        eintrag = payload["results"]["per_league_season"][0]
        assert eintrag["player_pool_season"] == 2023
        assert eintrag["matches_without_team_mapping"] == 4


# ---------------------------------------------------------------------------
# Schreiben
# ---------------------------------------------------------------------------

class TestSchreibschutz:

    def _payload(self):
        return run_backtests.build_payload(
            "go3", ["bl1"], [2024], 6,
            [lauf("bl1", 2024, baseline=teil(251, 1.0))], [])

    def test_schreibt_in_ein_freies_ziel(self, tmp_path):
        ziel = tmp_path / "ergebnis.json"
        assert run_backtests.write_payload(self._payload(), str(ziel), False)
        assert ziel.exists()
        assert json.loads(ziel.read_text(encoding="utf-8"))["manifest"]["suite"] == "go3"

    def test_ueberschreibt_nicht_ohne_force(self, tmp_path):
        """
        Die wichtigste Zusicherung dieser Datei: Die vorhandenen
        Referenzdateien sind der einzige Beleg fuer den bisherigen
        Messstand.
        """
        ziel = tmp_path / "vorhanden.json"
        ziel.write_text("URSPRUNG", encoding="utf-8")

        assert run_backtests.write_payload(self._payload(), str(ziel), False) is False
        assert ziel.read_text(encoding="utf-8") == "URSPRUNG"

    def test_ueberschreibt_mit_force(self, tmp_path):
        ziel = tmp_path / "vorhanden.json"
        ziel.write_text("URSPRUNG", encoding="utf-8")

        assert run_backtests.write_payload(self._payload(), str(ziel), True)
        assert ziel.read_text(encoding="utf-8") != "URSPRUNG"

    def test_legt_fehlende_verzeichnisse_an(self, tmp_path):
        ziel = tmp_path / "neu" / "tiefer" / "ergebnis.json"
        assert run_backtests.write_payload(self._payload(), str(ziel), False)
        assert ziel.exists()

    def test_hinterlaesst_keine_temporaerdatei(self, tmp_path):
        ziel = tmp_path / "ergebnis.json"
        run_backtests.write_payload(self._payload(), str(ziel), False)
        assert not (tmp_path / "ergebnis.json.tmp").exists()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestArgumente:

    def _args(self, argv):
        return run_backtests.build_parser().parse_args(argv)

    def test_suite_ist_pflicht(self):
        with pytest.raises(SystemExit):
            self._args([])

    def test_nur_bekannte_suiten(self):
        with pytest.raises(SystemExit):
            self._args(["--suite", "go99"])

    def test_standardwerte(self):
        args = self._args(["--suite", "go3"])
        assert args.leagues == ["bl1", "pl", "pd", "sa", "fl1"]
        assert args.seasons == [2023, 2024, 2025]
        assert args.min_matchday == 6
        assert args.output is None
        assert args.force is False

    def test_ligen_werden_zerlegt(self):
        assert self._args(["--suite", "go3", "--leagues", "bl1,pl"]).leagues \
            == ["bl1", "pl"]

    def test_leerraum_stoert_nicht(self):
        assert self._args(["--suite", "go3", "--leagues", " bl1 , pl "]).leagues \
            == ["bl1", "pl"]

    def test_saisons_werden_zu_zahlen(self):
        assert self._args(["--suite", "go3", "--seasons", "2024,2025"]).seasons \
            == [2024, 2025]

    def test_unsinnige_saison_wird_abgewiesen(self):
        with pytest.raises(SystemExit):
            self._args(["--suite", "go3", "--seasons", "zweitausend"])

    def test_leere_ligenliste_wird_abgewiesen(self):
        with pytest.raises(SystemExit):
            self._args(["--suite", "go3", "--leagues", " , "])

    def test_min_matchday_ist_eine_zahl(self):
        assert self._args(["--suite", "go3", "--min-matchday", "10"]).min_matchday == 10


class TestHauptprogramm:

    def test_ohne_output_wird_nichts_geschrieben(self, tmp_path, monkeypatch):
        """
        Die Zusicherung, die einen versehentlichen Lauf harmlos macht.
        """
        geschrieben = []
        monkeypatch.setattr(run_backtests, "write_payload",
                            lambda *a, **k: geschrieben.append(a) or True)
        monkeypatch.setattr(run_backtests, "run_suite",
                            lambda *a, **k: ([lauf("bl1", 2024,
                                                   baseline=teil(251, 1.0))], []))

        code = run_backtests.main(["--suite", "go3", "--leagues", "bl1",
                                   "--seasons", "2024", "--quiet"])
        assert code == 0
        assert geschrieben == [], "ohne --output darf nichts geschrieben werden"

    def test_force_ohne_output_wird_abgewiesen(self):
        assert run_backtests.main(["--suite", "go3", "--force"]) == 2

    def test_negativer_min_matchday_wird_abgewiesen(self):
        assert run_backtests.main(["--suite", "go3", "--min-matchday", "-1"]) == 2

    def test_ohne_daten_endet_es_mit_fehlercode(self, monkeypatch):
        monkeypatch.setattr(run_backtests, "run_suite", lambda *a, **k: ([], []))
        assert run_backtests.main(["--suite", "go3", "--leagues", "bl1",
                                   "--seasons", "1999", "--quiet"]) == 1

    def test_mit_output_entsteht_eine_datei(self, tmp_path, monkeypatch):
        monkeypatch.setattr(run_backtests, "run_suite",
                            lambda *a, **k: ([lauf("bl1", 2024,
                                                   baseline=teil(251, 1.0))], []))
        ziel = tmp_path / "ergebnis.json"
        code = run_backtests.main(["--suite", "go3", "--leagues", "bl1",
                                   "--seasons", "2024", "--quiet",
                                   "--output", str(ziel)])
        assert code == 0 and ziel.exists()

    def test_vorhandenes_ziel_beendet_mit_fehlercode(self, tmp_path, monkeypatch):
        monkeypatch.setattr(run_backtests, "run_suite",
                            lambda *a, **k: ([lauf("bl1", 2024,
                                                   baseline=teil(251, 1.0))], []))
        ziel = tmp_path / "ergebnis.json"
        ziel.write_text("URSPRUNG", encoding="utf-8")

        code = run_backtests.main(["--suite", "go3", "--leagues", "bl1",
                                   "--seasons", "2024", "--quiet",
                                   "--output", str(ziel)])
        assert code == 1
        assert ziel.read_text(encoding="utf-8") == "URSPRUNG"


# ---------------------------------------------------------------------------
# Referenzdateien
# ---------------------------------------------------------------------------

#: Die drei Referenzdateien liegen bewusst NUR lokal.
#:
#: Sie belegen den bisherigen Messstand, sind aber unversioniert und
#: werden es bleiben: Die beiden Backtestergebnisse haben keinen
#: committeten Erzeuger mehr (der Codestand, der sie hervorbrachte,
#: existiert nicht), und percentiles_2026.json ist ein entarteter
#: Snapshot mit drei statt einundzwanzig Positionsgruppen.
#:
#: Die Tests unten pruefen sie deshalb nur, WENN sie vorhanden sind. Im
#: frischen Checkout - also in der CI - ueberspringen sie sich mit
#: sichtbarer Begruendung. Sie an ein Artefakt zu binden, das absichtlich
#: nicht im Repository liegt, waere ein Test, der bei jedem anderen
#: rot leuchtet.
REFERENZDATEIEN = (
    "data/go3_backtest_result.json",
    "data/go45_backtest_result.json",
    "data/percentiles/percentiles_2026.json",
)


class TestReferenzdateienBleibenUnberuehrt:
    """
    Die drei Dateien belegen den bisherigen Messstand. Sie werden von
    diesem Auftrag ausdruecklich nicht angefasst.
    """

    @pytest.mark.parametrize("pfad", REFERENZDATEIEN)
    def test_die_referenz_ist_lesbar_wenn_sie_vorliegt(self, pfad):
        if not os.path.exists(pfad):
            pytest.skip(f"{pfad} liegt auf diesem Host nicht vor "
                        f"(unversionierte lokale Referenz)")

        with open(pfad, encoding="utf-8") as datei:
            assert json.load(datei), f"{pfad} ist leer"

    def test_die_bekannten_kennzahlen_stehen_unveraendert_darin(self):
        """
        Der eigentliche Zweck: Solange die Dateien lokal liegen, muessen
        sie die bekannten Zahlen tragen. Verschiebt sich hier etwas, ist
        der Bezugspunkt verlorengegangen.
        """
        fehlend = [p for p in REFERENZDATEIEN[:2] if not os.path.exists(p)]
        if fehlend:
            pytest.skip(f"unversionierte lokale Referenz fehlt: {fehlend}")

        with open("data/go3_backtest_result.json", encoding="utf-8") as datei:
            go3 = json.load(datei)["aggregate"]["baseline"]
        with open("data/go45_backtest_result.json", encoding="utf-8") as datei:
            go45 = json.load(datei)["baseline"]

        assert round(go3["log_loss"], 5) == 1.01598
        assert go3["n"] == 4380
        assert round(go45["log_loss"], 5) == 1.02044
        assert go45["n"] == 2924


# ---------------------------------------------------------------------------
# Kontaktprobe mit dem echten Backtest
# ---------------------------------------------------------------------------

class TestEchterKleinerLauf:
    """
    Ein einziger echter Durchlauf. Alles darueber waere zu langsam fuer
    eine Suite, die bei jedem Lauf mitlaeuft - der vollstaendige Lauf
    ueber 15 Liga-Saisons dauert Minuten.
    """

    def test_eine_liga_saison_reproduziert_die_referenz(self):
        """
        bl1 2024 steht in data/go3_backtest_result.json mit 251 Spielen
        und einem Delta von +0.000552. Beides muss herauskommen.
        """
        laeufe, uebersprungen = run_backtests.run_suite(
            "go3", ["bl1"], [2024], 6)

        assert uebersprungen == []
        assert len(laeufe) == 1

        varianten = laeufe[0]["variants"]
        assert varianten["baseline"]["n"] == 251

        delta = varianten["full_go3"]["log_loss"] - varianten["baseline"]["log_loss"]
        assert delta == pytest.approx(0.000552, abs=5e-6)

    def test_zwei_laeufe_liefern_dasselbe(self):
        a, _ = run_backtests.run_suite("go3", ["bl1"], [2024], 6)
        b, _ = run_backtests.run_suite("go3", ["bl1"], [2024], 6)
        assert a[0]["variants"] == b[0]["variants"]
