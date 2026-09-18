"""
V2-C19: Die Team-Liga-Zuordnung als EIN Vertrag.

WAS HIER FESTGEHALTEN WIRD
--------------------------
Bis C18 gab es zwei Karten mit derselben Bedeutung im Namen: Die
Messung nahm alle 146 Vereine der lokalen Ligadateien, das Bundle nur
die 63, die in den Trainings-CL-Partien vorkamen. Nachgemessen wandte
die Evaluation dadurch auf 188 von 283 Standardpartien einen
Ligafaktor an, den die Laufzeit gar nicht anwenden konnte.

Die Tests hier halten drei Dinge fest:

  1. Die Karte ist zeitlich begrenzt und traegt ihre Obergrenze im
     Fingerabdruck.
  2. Bundle und Messung benutzen dieselbe Karte.
  3. Ein unbekannter Verein ist etwas anderes als eine Liga ohne
     gelernte Parameter. Der erste laesst die Lambdas unveraendert,
     die zweite traegt 0 bei und laesst die bekannte Seite
     weiterkorrigieren - genau so hat apply_factors gemessen. Nur der
     erste Fall ist ein Grund, die Karte zu erweitern.
"""

import json
import os
import tempfile

import pytest

from src.ml import c19_league_map as c19


# ---------------------------------------------------------------------------
# 1. Der Vertrag
# ---------------------------------------------------------------------------

class TestVertrag:

    def test_fingerabdruck_ist_stabil(self):
        assert c19.contract_fingerprint() == c19.contract_fingerprint()

    def test_fingerabdruck_haengt_nicht_an_der_schluesselreihenfolge(self):
        vertrag = c19.contract()
        gedreht = dict(reversed(list(vertrag.items())))
        assert c19._stabil(vertrag) == c19._stabil(gedreht)

    def test_der_vertrag_benennt_den_kanonischen_namensraum(self):
        vertrag = c19.contract()
        assert vertrag["canonical_namespace"] == "football-data.org"
        assert vertrag["canonical_key_type"] == "int"

    def test_der_vertrag_verbietet_raten(self):
        verboten = c19.contract()["provider_resolution"]["forbidden"]
        text = " ".join(verboten).lower()
        assert "numerische gleichheit" in text
        assert "namensabgleich" in text or "fuzzy" in text

    def test_der_vertrag_bindet_alle_drei_wege(self):
        assert set(c19.contract()["binds"]) == {"evaluation", "bundle",
                                                "runtime"}

    def test_die_laufzeit_liest_keine_ligadatei(self):
        """
        Die Karte steht IM Bundle. Zwei Bundles duerfen nicht je nach
        Plattenstand verschieden rechnen.
        """
        quellen = c19.contract()["sources"]
        assert quellen["no_network"] is True
        assert "nicht" in quellen["no_live_file_at_runtime"].lower()

    def test_beide_unbekannt_faelle_sind_getrennt_benannt(self):
        """
        Und sie sind NICHT dasselbe: Ein fehlender Verein laesst die
        Lambdas unberuehrt, eine Liga ohne gelernte Werte traegt 0 bei
        und laesst die bekannte Seite weiterkorrigieren. Genau so hat
        apply_factors gemessen.
        """
        unbekannt = c19.contract()["unknown_semantics"]
        assert c19.UNKNOWN_TEAM in unbekannt
        assert c19.LEAGUE_WITHOUT_PARAMS in unbekannt
        assert unbekannt[c19.UNKNOWN_TEAM]["factor"] == 1.0
        ohne = unbekannt[c19.LEAGUE_WITHOUT_PARAMS]
        assert ohne["contribution"] == 0.0
        assert ohne["correction_still_applied"] is True
        assert unbekannt["identical_on_both_paths"] is True

    def test_die_laufzeit_rechnet_bei_fehlenden_ligawerten_weiter(self):
        """
        Der Fall, an dem C18 und die Messung auseinanderliefen.
        Geprueft am echten Verhalten, nicht nur am Vertragstext.
        """
        from src.features import league_strength as ls
        from src.ml import inference as inf

        block = {
            "gamma": 1.0,
            "attack": {"PL": 0.42}, "defence": {"PL": -0.5},
            "team_leagues": {"57": "PL", "777": "AZ1"},
            "factor_bounds": [ls.FACTOR_MIN, ls.FACTOR_MAX],
        }
        f_h, f_a, diagnose = inf._ligastaerke_anwenden(
            block, {"team_id": 57}, {"team_id": 777}, 1.0, 1.0)

        # Die bekannte Seite korrigiert weiter, die unbekannte traegt 0.
        assert diagnose["applied"] is True
        assert diagnose["status"] == c19.LEAGUE_WITHOUT_PARAMS
        assert f_h == pytest.approx(2.718281828459045 ** 0.42)
        assert f_a == pytest.approx(2.718281828459045 ** -0.5)

    def test_ein_fehlender_verein_laesst_dagegen_alles_unveraendert(self):
        from src.features import league_strength as ls
        from src.ml import inference as inf

        block = {
            "gamma": 1.0,
            "attack": {"PL": 0.42}, "defence": {"PL": -0.5},
            "team_leagues": {"57": "PL"},
            "factor_bounds": [ls.FACTOR_MIN, ls.FACTOR_MAX],
        }
        f_h, f_a, diagnose = inf._ligastaerke_anwenden(
            block, {"team_id": 57}, {"team_id": 999999}, 1.0, 1.0)
        assert (f_h, f_a) == (1.0, 1.0)
        assert diagnose["applied"] is False
        assert diagnose["status"] == c19.UNKNOWN_TEAM


# ---------------------------------------------------------------------------
# 2. Die Karte
# ---------------------------------------------------------------------------

class TestKarte:

    def test_obergrenze_ist_pflicht(self):
        """
        Ohne Obergrenze entstuende stillschweigend die neueste Karte -
        und ein Fold wuesste mehr als er darf.
        """
        with pytest.raises(ValueError, match="upto_season"):
            c19.build_team_league_map(None)

    def test_die_karte_waechst_mit_der_obergrenze(self):
        k23, d23 = c19.build_team_league_map(2023)
        k24, d24 = c19.build_team_league_map(2024)
        k25, d25 = c19.build_team_league_map(2025)

        assert d23["teams"] < d24["teams"] < d25["teams"]
        # Monoton: was frueher bekannt war, bleibt bekannt.
        assert set(k23) <= set(k24) <= set(k25)

    def test_fruehere_karten_kennen_spaetere_saisons_nicht(self):
        _k, d23 = c19.build_team_league_map(2023)
        assert d23["seasons_used"] == [2023]
        _k, d24 = c19.build_team_league_map(2024)
        assert d24["seasons_used"] == [2023, 2024]

    def test_die_obergrenze_gehoert_in_den_fingerabdruck(self):
        """
        Zwei Karten mit gleichem Inhalt, aber verschiedenem Zeitfenster
        sind nicht dieselbe Karte.
        """
        karte = {5: "BL1", 57: "PL"}
        assert (c19.map_fingerprint(karte, 2023)
                != c19.map_fingerprint(karte, 2024))

    def test_fingerabdruck_haengt_nicht_an_der_einfuegereihenfolge(self):
        a = {5: "BL1", 57: "PL"}
        b = {57: "PL", 5: "BL1"}
        assert (c19.map_fingerprint(a, 2025)
                == c19.map_fingerprint(b, 2025))

    def test_schluessel_sind_ganzzahlen_im_kanonischen_raum(self):
        karte, _d = c19.build_team_league_map(2025)
        assert karte
        assert all(isinstance(tid, int) for tid in karte)
        assert all(isinstance(liga, str) and liga for liga in karte.values())

    def test_keine_mehrdeutigkeit_im_vorliegenden_bestand(self):
        for saison in (2023, 2024, 2025):
            _k, d = c19.build_team_league_map(saison)
            assert d["ambiguous_count"] == 0, d["ambiguous_leagues"]

    def test_mehrdeutige_vereine_fliegen_heraus(self, monkeypatch):
        """
        Ein Verein in zwei Ligen ist ein Widerspruch der Quellen, keine
        Mehrheitsfrage. Synthetisch geprueft, weil der echte Bestand
        widerspruchsfrei ist.
        """
        from src.data import national_sources as ns

        monkeypatch.setattr(ns, "profile_source_codes", lambda: ["BL1", "PL"])
        monkeypatch.setattr(c19, "_stabil", c19._stabil)

        import src.data.historical_loader as hl
        monkeypatch.setattr(hl, "AVAILABLE_HISTORICAL_SEASONS", [2023])

        with tempfile.TemporaryDirectory() as tmp:
            def pfad(code, saison):
                return os.path.join(tmp, "%s_%s.json" % (code, saison))

            for code in ("BL1", "PL"):
                with open(pfad(code, 2023), "w", encoding="utf-8") as datei:
                    json.dump({"matches": [{"home_id": 4242, "away_id": 11}]},
                              datei)
            monkeypatch.setattr(hl, "season_file_path", pfad)

            karte, diagnose = c19.build_team_league_map(2023)

        assert 4242 not in karte
        assert diagnose["ambiguous_count"] >= 1
        assert "4242" in diagnose["ambiguous_leagues"]

    def test_bundle_map_hat_zeichenketten_als_schluessel(self):
        karte = {5: "BL1", 57: "PL"}
        gebunden = c19.bundle_map(karte)
        assert gebunden == {"5": "BL1", "57": "PL"}
        assert all(isinstance(k, str) for k in gebunden)

    def test_die_diagnose_nennt_ihre_herkunft(self):
        _k, d = c19.build_team_league_map(2025)
        assert d["contract_fingerprint"] == c19.contract_fingerprint()
        assert d["upto_season"] == 2025
        assert d["files_read"] > 0
        assert d["teams"] == sum(d["teams_per_league"].values())


# ---------------------------------------------------------------------------
# 3. Unbekannt ist nicht gleich unbekannt
# ---------------------------------------------------------------------------

class TestUnbekanntSemantik:

    ATTACK = {"PL": 0.4, "BL1": 0.27}
    DEFENCE = {"PL": -0.5, "BL1": -0.35}

    def test_verein_ohne_eintrag(self):
        liga, grund = c19.classify({"5": "BL1"}, 999999,
                                   self.ATTACK, self.DEFENCE)
        assert liga is None
        assert grund == c19.UNKNOWN_TEAM

    def test_verein_ohne_id(self):
        liga, grund = c19.classify({"5": "BL1"}, None,
                                   self.ATTACK, self.DEFENCE)
        assert liga is None
        assert grund == c19.UNKNOWN_TEAM

    def test_bekannte_liga_ohne_gelernte_parameter(self):
        """
        Der Fall, der vorher mit einem unbekannten Verein verwechselt
        wurde. Beide ergeben Faktor 1 und sind fachlich verschieden.
        """
        liga, grund = c19.classify({"777": "AZ1"}, 777,
                                   self.ATTACK, self.DEFENCE)
        assert liga == "AZ1"
        assert grund == c19.LEAGUE_WITHOUT_PARAMS

    def test_vollstaendig_aufloesbar(self):
        liga, grund = c19.classify({"5": "BL1"}, 5,
                                   self.ATTACK, self.DEFENCE)
        assert liga == "BL1"
        assert grund is None

    def test_ein_verein_ohne_cl_historie_ist_keine_unbekannte_liga(self):
        """
        Die fachliche Kernaussage von C19 in einem Satz.
        """
        karte, _d = c19.build_team_league_map(2025)
        # AS Roma spielte in den Trainingssaisons keine Champions
        # League und stand deshalb bis C18 nicht in der Bundlekarte.
        assert karte.get(100) == "SA"
        liga, grund = c19.classify(c19.bundle_map(karte), 100,
                                   {"SA": 0.0}, {"SA": -0.4})
        assert liga == "SA"
        assert grund is None
