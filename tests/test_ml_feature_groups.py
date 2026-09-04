"""
Tests fuer die Merkmalsgruppen der Ablation.

Die Gruppen entscheiden, WAS die Ablation misst. Ein Fehler hier faellt
nicht auf: Er produziert eine vollstaendig plausible Tabelle, in der
nur die Beschriftung nicht mehr zum Inhalt passt. Deshalb prueft jeder
Test hier eine Eigenschaft, die sich tatsaechlich verletzen laesst -
und die Fehlerfaelle werden ausdruecklich provoziert, statt auf ihr
Ausbleiben zu vertrauen.
"""

import pytest

from src.ml import dataset as ds
from src.ml import feature_groups as fg
from src.ml import model as mdl


# ---------------------------------------------------------------------------
# 1. Die Zerlegung geht auf
# ---------------------------------------------------------------------------

class TestZerlegung:

    def test_jedes_modellmerkmal_liegt_in_genau_einer_gruppe(self):
        spalten = mdl.feature_columns()
        gruppen = fg.build_groups(spalten)

        zaehler = {}
        for name in fg.GROUP_ORDER:
            for spalte in gruppen[name]["columns"]:
                zaehler.setdefault(spalte, []).append(name)

        mehrfach = {s: n for s, n in zaehler.items() if len(n) > 1}
        assert not mehrfach, f"Spalten in mehreren Gruppen: {mehrfach}"
        assert set(zaehler) == set(spalten)

    def test_die_summe_der_gruppen_ist_die_merkmalszahl(self):
        info = fg.validate_groups()
        assert sum(info["counts"].values()) == info["total_model_features"]
        assert info["total_model_features"] == len(mdl.feature_columns())

    def test_die_gruppengroessen_stehen_fest(self):
        """
        Nachgemessen am Schema: 9 Profilfelder je Seite, 4 Ligafelder,
        9 Belastungsfelder je Seite ohne congestion_level, 3
        Gegnerfelder je Seite.

        Der Test haelt eine Zahl fest, damit ein stilles Verschieben
        zwischen zwei Gruppen auffaellt - die Gesamtsumme allein wuerde
        das nicht bemerken.
        """
        info = fg.validate_groups()
        assert info["counts"] == {
            "profile": 2 * len(ds.PROFILE_FELDER),
            "league_average": len(ds.LIGA_FELDER),
            "workload": 2 * (len(ds.WORKLOAD_FELDER) - 1),
            "schedule_strength": 2 * len(ds.SCHEDULE_FELDER),
        }

    def test_die_gruppen_stammen_aus_den_schemakonstanten(self):
        """
        Die Gegenprobe zur abgetippten Namensliste: Ein zusaetzliches
        Feld in einer Schemakonstante MUSS in der Gruppe auftauchen.
        Taete es das nicht, waere die Gruppe hartkodiert und liefe bei
        der naechsten Schemaaenderung unbemerkt auseinander.
        """
        roh = fg.build_raw_groups()
        for feld in ds.PROFILE_FELDER:
            assert f"home_{feld}" in roh["profile"]
            assert f"away_{feld}" in roh["profile"]
        for feld in ds.LIGA_FELDER:
            assert f"league_avg_{feld}" in roh["league_average"]
        for feld in ds.WORKLOAD_FELDER:
            assert f"home_{feld}" in roh["workload"]
        for feld in ds.SCHEDULE_FELDER:
            assert f"away_{feld}" in roh["schedule_strength"]

    def test_keine_gruppe_ist_leer(self):
        info = fg.validate_groups()
        for name, anzahl in info["counts"].items():
            assert anzahl > 0, f"Gruppe {name} ist leer"

    def test_die_reihenfolge_ist_stabil(self):
        assert fg.build_groups() == fg.build_groups()
        assert fg.validate_groups() == fg.validate_groups()


# ---------------------------------------------------------------------------
# 2. Der bekannte Sonderfall bleibt sichtbar
# ---------------------------------------------------------------------------

class TestNichtModellierte:

    def test_genau_congestion_level_faellt_heraus(self):
        info = fg.validate_groups()
        heraus = sorted(eintrag["column"]
                        for eintraege in info["not_modelled"].values()
                        for eintrag in eintraege)
        assert heraus == ["away_congestion_level", "home_congestion_level"]

    def test_es_wird_nicht_still_weggefiltert(self):
        """Die Spalte verschwindet nicht, sie wird ausgewiesen."""
        info = fg.validate_groups()
        eintraege = info["not_modelled"]["workload"]
        assert eintraege
        for eintrag in eintraege:
            assert eintrag["reason"], "Ausschluss ohne Begruendung"

    def test_die_begruendung_stammt_vom_modell(self):
        info = fg.validate_groups()
        gruende = {e["column"]: e["reason"]
                   for e in mdl.excluded_columns()}
        for eintraege in info["not_modelled"].values():
            for eintrag in eintraege:
                assert eintrag["reason"] == gruende[eintrag["column"]]

    def test_nicht_modellierte_stehen_in_keiner_variante(self):
        for name in fg.VARIANT_ORDER:
            spalten = fg.columns_for(name)
            assert not [s for s in spalten if s.endswith("congestion_level")]


# ---------------------------------------------------------------------------
# 3. Fehlerfaelle brechen ab, statt still durchzulaufen
# ---------------------------------------------------------------------------

class TestHartesScheitern:

    def test_ein_merkmal_ohne_gruppe_bricht_ab(self):
        """
        Der wichtigste Fehlerfall: Ein neues Schemamerkmal, das in
        keiner Gruppe steht, fehlte sonst in JEDER Variante - auch in
        all_existing_features. Der Vergleich waere dann keiner mehr.
        """
        spalten = mdl.feature_columns() + ["home_neues_merkmal"]
        gruppen = fg.build_groups(spalten)

        with pytest.raises(ValueError, match="ohne Gruppe"):
            fg.validate_groups(gruppen, spalten)

    def test_eine_doppelt_zugeordnete_spalte_bricht_ab(self):
        spalten = mdl.feature_columns()
        gruppen = fg.build_groups(spalten)
        doppelt = gruppen["profile"]["columns"][0]
        gruppen["workload"] = {
            "columns": gruppen["workload"]["columns"] + (doppelt,),
            "not_modelled": gruppen["workload"]["not_modelled"],
        }

        with pytest.raises(ValueError, match="in zwei Gruppen"):
            fg.validate_groups(gruppen, spalten)

    def test_eine_dem_schema_unbekannte_spalte_bricht_ab(self):
        spalten = mdl.feature_columns()
        gruppen = fg.build_groups(spalten)
        gruppen["profile"] = {
            "columns": gruppen["profile"]["columns"] + ("erfunden",),
            "not_modelled": (),
        }

        with pytest.raises(ValueError, match="Datensatzschema nicht kennt"):
            fg.validate_groups(gruppen, spalten)

    def test_eine_nicht_modellierte_ohne_ausschluss_bricht_ab(self):
        """
        not_modelled darf kein Sammelbecken werden. Wer eine Spalte
        dort ablegt, muss belegen koennen, dass das Modell sie
        ausdruecklich ausschliesst.
        """
        spalten = [s for s in mdl.feature_columns() if s != "home_win_rate"]
        gruppen = fg.build_groups(spalten)

        with pytest.raises(ValueError,
                           match="weder Modellmerkmal noch"):
            fg.validate_groups(gruppen, spalten)

    def test_eine_fehlende_gruppe_bricht_ab(self):
        gruppen = fg.build_groups()
        del gruppen["workload"]

        with pytest.raises(ValueError, match="Merkmalsgruppe fehlt"):
            fg.validate_groups(gruppen)

    def test_eine_unbekannte_gruppe_bricht_ab(self):
        gruppen = fg.build_groups()
        gruppen["fantasie"] = {"columns": (), "not_modelled": ()}

        with pytest.raises(ValueError, match="unbekannte Merkmalsgruppen"):
            fg.validate_groups(gruppen)

    def test_eine_unbekannte_variante_bricht_ab(self):
        with pytest.raises(ValueError, match="unbekannte Ablationsvariante"):
            fg.variant("gibt_es_nicht")
        with pytest.raises(ValueError, match="unbekannte Ablationsvariante"):
            fg.columns_for("gibt_es_nicht")

    def test_eine_variante_mit_unbekannter_gruppe_bricht_ab(self, monkeypatch):
        kaputt = ({"name": "kaputt", "groups": ("fantasie",),
                   "description": "Testfall"},)
        monkeypatch.setattr(fg, "VARIANTS", kaputt)

        with pytest.raises(ValueError, match="unbekannte Gruppe"):
            fg.columns_for("kaputt")


# ---------------------------------------------------------------------------
# 4. Die Varianten sagen, was sie sagen sollen
# ---------------------------------------------------------------------------

class TestVarianten:

    def test_die_vier_geforderten_varianten_stehen_fest(self):
        assert list(fg.VARIANT_ORDER) == [
            "no_correction", "profile_only", "workload_only",
            "all_existing_features"]

    def test_no_correction_hat_keine_merkmale(self):
        assert fg.columns_for("no_correction") == []

    def test_profile_only_traegt_profil_und_ligaschnitt(self):
        spalten = fg.columns_for("profile_only")
        info = fg.validate_groups()
        erwartet = sorted(info["columns"]["profile"]
                          + info["columns"]["league_average"])
        assert spalten == erwartet

    def test_workload_only_traegt_belastung_und_gegnerhaerte(self):
        spalten = fg.columns_for("workload_only")
        info = fg.validate_groups()
        erwartet = sorted(info["columns"]["workload"]
                          + info["columns"]["schedule_strength"])
        assert spalten == erwartet

    def test_die_beiden_teilmengen_ueberschneiden_sich_nicht(self):
        profil = set(fg.columns_for("profile_only"))
        belastung = set(fg.columns_for("workload_only"))
        assert not profil & belastung

    def test_die_beiden_teilmengen_ergeben_zusammen_den_vollen_satz(self):
        profil = set(fg.columns_for("profile_only"))
        belastung = set(fg.columns_for("workload_only"))
        voll = set(fg.columns_for("all_existing_features"))
        assert profil | belastung == voll

    def test_all_existing_features_ist_die_modellmerkmalsliste(self):
        """
        Der Anschluss an den bisherigen Stand: Diese Variante MUSS
        genau das messen, was shadow_eval gemessen hat. Weicht sie ab,
        vergleicht die Ablation gegen eine andere Zahl als die, die sie
        erklaeren soll.
        """
        assert fg.columns_for("all_existing_features") == mdl.feature_columns()

    def test_jede_variante_hat_eine_beschreibung(self):
        for definition in fg.VARIANTS:
            assert definition["description"].strip()

    def test_die_spaltenliste_ist_sortiert_und_stabil(self):
        for name in fg.VARIANT_ORDER:
            spalten = fg.columns_for(name)
            assert spalten == sorted(spalten)
            assert spalten == fg.columns_for(name)


# ---------------------------------------------------------------------------
# 5. Die zweite Diagnosestufe
# ---------------------------------------------------------------------------

class TestDiagnosevarianten:

    def test_die_fuenf_geforderten_varianten_stehen_fest(self):
        assert list(fg.DIAGNOSTIC_VARIANT_ORDER) == [
            "intercept_only", "league_average_only", "team_profile_only",
            "profile_only", "all_existing_features"]

    def test_intercept_only_traegt_kein_einziges_merkmal(self):
        assert fg.columns_for("intercept_only") == []
        assert fg.variant("intercept_only")["groups"] == ()

    def test_intercept_only_ist_nicht_no_correction(self):
        """
        Beide haben null Merkmale. Nur die Betriebsart trennt sie - und
        genau ihr Unterschied ist die Frage der Diagnosestufe.
        """
        assert fg.variant("intercept_only")["mode"] == fg.MODE_INTERCEPT
        assert fg.variant("no_correction")["mode"] == fg.MODE_BASELINE
        assert fg.variant("intercept_only")["mode"] \
            != fg.variant("no_correction")["mode"]

    def test_league_average_only_traegt_genau_die_vier_ligamerkmale(self):
        spalten = fg.columns_for("league_average_only")
        info = fg.validate_groups()
        assert spalten == sorted(info["columns"]["league_average"])
        assert len(spalten) == len(ds.LIGA_FELDER) == 4
        assert all(s.startswith("league_avg_") for s in spalten)

    def test_team_profile_only_traegt_genau_die_18_profilmerkmale(self):
        spalten = fg.columns_for("team_profile_only")
        info = fg.validate_groups()
        assert spalten == sorted(info["columns"]["profile"])
        assert len(spalten) == 2 * len(ds.PROFILE_FELDER) == 18
        assert not [s for s in spalten if s.startswith("league_avg_")]

    def test_die_beiden_teilmengen_ergeben_profile_only(self):
        """
        Der Schnitt, auf dem die ganze Diagnose beruht: Wenn
        team_profile_only und league_average_only zusammen nicht genau
        profile_only sind, misst der Vergleich etwas anderes als
        behauptet.
        """
        team = set(fg.columns_for("team_profile_only"))
        liga = set(fg.columns_for("league_average_only"))
        assert not team & liga
        assert team | liga == set(fg.columns_for("profile_only"))

    def test_keine_diagnosevariante_traegt_workloadmerkmale(self):
        info = fg.validate_groups()
        verboten = set(info["columns"]["workload"]) \
            | set(info["columns"]["schedule_strength"])
        for name in ("intercept_only", "league_average_only",
                     "team_profile_only", "profile_only"):
            assert not set(fg.columns_for(name)) & verboten

    def test_profile_only_bedeutet_in_beiden_stufen_dasselbe(self):
        """
        Der Anschluss an die erste Stufe. Waeren die Merkmalsmengen
        verschieden, waeren die Zahlen der beiden Artefakte nicht
        vergleichbar - und der Vergleich ist der Zweck der Uebung.
        """
        for name in ("profile_only", "all_existing_features"):
            aus_stufe1 = [v for v in fg.VARIANTS if v["name"] == name][0]
            aus_stufe2 = [v for v in fg.DIAGNOSTIC_VARIANTS
                          if v["name"] == name][0]
            assert tuple(aus_stufe1["groups"]) == tuple(aus_stufe2["groups"])
            assert aus_stufe1["mode"] == aus_stufe2["mode"]

    def test_widerspruechliche_definitionen_brechen_ab(self, monkeypatch):
        monkeypatch.setattr(fg, "DIAGNOSTIC_VARIANTS", (
            {"name": "profile_only", "mode": fg.MODE_FEATURES,
             "groups": ("workload",), "description": "Testfall"},))

        with pytest.raises(ValueError, match="zweimal verschieden"):
            fg.check_variant_consistency()

    def test_die_saubere_definition_besteht_die_pruefung(self):
        namen = fg.check_variant_consistency()
        assert "profile_only" in namen
        assert "intercept_only" in namen

    def test_jede_diagnosevariante_hat_beschreibung_und_modus(self):
        for definition in fg.DIAGNOSTIC_VARIANTS:
            assert definition["description"].strip()
            assert definition["mode"] in (fg.MODE_BASELINE, fg.MODE_INTERCEPT,
                                          fg.MODE_FEATURES)

    def test_all_variants_liest_den_aktuellen_stand(self, monkeypatch):
        """
        Kein eingefrorenes Modultupel: Eine Ersetzung muss durchschlagen,
        sonst behauptet die Namensaufloesung einen Stand, den es nicht
        mehr gibt.
        """
        monkeypatch.setattr(fg, "DIAGNOSTIC_VARIANTS", ())
        namen = [v["name"] for v in fg.all_variants()]
        assert "intercept_only" not in namen
        assert "no_correction" in namen
