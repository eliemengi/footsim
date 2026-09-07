"""
Struktureller Spielkontext: K.-o., Legs, Aggregat, neutraler Ort (V2-C5).

WAS HIER GEPRUEFT WIRD
----------------------
Drei Fehler, die plausible Zahlen erzeugen und deshalb niemandem
auffallen:

  1. Ein Hinspiel, das sein eigenes Rueckspiel kennt.
  2. Ein Aggregatstand mit gedrehtem Vorzeichen - lauter richtige
     Zahlen vor der falschen Mannschaft.
  3. Eine Null im Aggregat, die zugleich "Gleichstand" und
     "keine Information" heisst.

Dazu die Vertraege, die C5 nicht brechen darf: Ligaphase ist kein
K.-o., der regulaere Auswertungsbestand bleibt bei 238 Zeilen, und die
Modellmerkmale koennen sich nicht widersprechen.

OHNE NETZ, OHNE .env, OHNE PRIVATE DATEIEN
------------------------------------------
Jeder Test baut seine Partien aus Wortlisten.
"""

import json

import pytest

from src.features import match_context as mc
from src.ml import cl_ablation as ca
from src.ml import cl_dataset as cd
from src.ml import cl_evaluate as ce
from src.ml import dataset as ds
from src.ml import evaluate as ev
from src.ml import feature_groups as fg
from src.ml import model as mdl


def _partie(datum, stage, matchday, heim, gast, tore=(1, 0), season=2024,
            match_id=None):
    return {
        "match_id": match_id if match_id is not None
        else f"{stage}-{matchday}-{heim}-{gast}-{datum}",
        "season": season, "date": datum, "stage": stage,
        "matchday": matchday, "home_id": heim, "away_id": gast,
        "home_goals": tore[0], "away_goals": tore[1], "status": "FINISHED",
    }


#: Eine vollstaendige Zwei-Leg-Paarung. Das Hinspiel endet 3:1 fuer A.
HIN = _partie("2025-03-04", "QUARTER_FINALS", 1, 10, 20, (3, 1))
RUECK = _partie("2025-03-12", "QUARTER_FINALS", 2, 20, 10, (2, 0))
PAARUNG = [HIN, RUECK]


# ===========================================================================
# 1-2. Hinspiel und Rueckspiel
# ===========================================================================

class TestLegs:

    def test_das_hinspiel_kennt_kein_rueckspielergebnis(self):
        """
        Der Kern des Zukunftsschutzes. Das Rueckspiel liegt in der
        Liste; es darf trotzdem nicht in den Kontext des Hinspiels
        geraten.
        """
        werte = mc.context_values(HIN, PAARUNG)
        assert werte["match_type"] == mc.TYPE_KO_FIRST_LEG
        assert werte["aggregate_available"] == 0
        for feld in mc.AGGREGATE_FELDER:
            assert werte[feld] is None

    def test_das_rueckspiel_bekommt_genau_den_hinspielstand(self):
        werte = mc.context_values(RUECK, PAARUNG)
        assert werte["match_type"] == mc.TYPE_KO_SECOND_LEG
        assert werte["aggregate_available"] == 1
        assert werte["aggregate_legs_played"] == 1
        # Hinspiel 3:1 fuer Team 10. Im Rueckspiel ist Team 20 zu Hause.
        assert werte["aggregate_goals_for"] == 1.0
        assert werte["aggregate_goals_against"] == 3.0
        assert werte["aggregate_diff"] == -2.0
        assert werte["aggregate_lead"] == -1.0

    def test_die_perspektive_dreht_mit_dem_heimrecht(self):
        """
        Dieselbe Paarung, aber das Rueckspiel bei Team 10 statt bei
        Team 20. Alle Werte muessen ihr Vorzeichen tauschen - genau
        hier entsteht der Fehler, den niemand bemerkt.
        """
        anders = _partie("2025-03-12", "QUARTER_FINALS", 2, 10, 20, (0, 0))
        werte = mc.context_values(anders, [HIN, anders])
        assert werte["aggregate_goals_for"] == 3.0
        assert werte["aggregate_goals_against"] == 1.0
        assert werte["aggregate_diff"] == 2.0
        assert werte["aggregate_lead"] == 1.0
        assert werte["first_leg_was_home"] == 1

    def test_gleichstand_ist_kein_fehlender_wert(self):
        hin = _partie("2025-03-04", "LAST_16", 1, 10, 20, (2, 2))
        rueck = _partie("2025-03-12", "LAST_16", 2, 20, 10, (0, 0))
        werte = mc.context_values(rueck, [hin, rueck])
        assert werte["aggregate_diff"] == 0.0
        assert werte["aggregate_lead"] == 0.0
        assert werte["aggregate_available"] == 1

    def test_ein_rueckspiel_ohne_hinspiel_erfindet_keinen_stand(self):
        werte = mc.context_values(RUECK, [RUECK])
        assert werte["aggregate_available"] == 0
        assert werte["aggregate_diff"] is None

    def test_die_null_ist_von_der_luecke_unterscheidbar(self):
        """
        Der Missingness-Vertrag in einem Satz: aggregate_diff == 0
        heisst Gleichstand, aggregate_diff is None heisst keine
        Information. Beides zugleich in einer Null waere die
        Zweideutigkeit, die der Auftrag ausdruecklich verbietet.
        """
        hin = _partie("2025-03-04", "LAST_16", 1, 10, 20, (1, 1))
        rueck = _partie("2025-03-12", "LAST_16", 2, 20, 10, (0, 0))
        gleich = mc.context_values(rueck, [hin, rueck])
        ohne = mc.context_values(HIN, PAARUNG)
        assert gleich["aggregate_diff"] == 0.0
        assert gleich["aggregate_available"] == 1
        assert ohne["aggregate_diff"] is None
        assert ohne["aggregate_available"] == 0


# ===========================================================================
# 3-5. Zukunft und Selbstleck
# ===========================================================================

class TestPointInTime:

    def test_eine_spaetere_partie_veraendert_den_kontext_nicht(self):
        spaeter = _partie("2025-04-20", "SEMI_FINALS", 1, 20, 30, (5, 0))
        a = mc.context_values(RUECK, PAARUNG)
        b = mc.context_values(RUECK, PAARUNG + [spaeter])
        assert a == b

    def test_ein_veraendertes_spaeteres_ergebnis_veraendert_nichts(self):
        geaendert = dict(RUECK, home_goals=9, away_goals=0)
        a = mc.context_values(HIN, PAARUNG)
        b = mc.context_values(HIN, [HIN, geaendert])
        assert a == b

    def test_das_zielspiel_geht_nie_in_seinen_eigenen_kontext_ein(self):
        """
        Selbstleck: Das Rueckspiel steht in der Liste seiner eigenen
        Saisonpartien. Sein Ergebnis darf den Aggregatstand VOR dem
        Anpfiff nicht beeinflussen.
        """
        a = mc.context_values(RUECK, PAARUNG)
        b = mc.context_values(dict(RUECK, home_goals=7, away_goals=7),
                              [HIN, dict(RUECK, home_goals=7, away_goals=7)])
        for feld in mc.AGGREGATE_FELDER:
            assert a[feld] == b[feld]

    def test_first_leg_of_nimmt_nur_frueheres(self):
        assert mc.first_leg_of(HIN, PAARUNG) is None
        assert mc.first_leg_of(RUECK, PAARUNG) is HIN

    def test_gleiches_datum_zaehlt_nicht_als_frueher(self):
        zwilling = _partie("2025-03-04", "QUARTER_FINALS", 2, 20, 10, (1, 1))
        assert mc.first_leg_of(zwilling, [HIN, zwilling]) is None

    def test_die_herleitung_zaehlt_nicht_die_partien_der_paarung(self):
        """
        Ein Hinspiel bleibt ein Hinspiel, auch wenn das Rueckspiel gar
        nicht in der Liste steht. Waere der Typ ueber die Anzahl der
        Partien hergeleitet, haette dasselbe Spiel je nach
        Listeninhalt einen anderen Typ - und das Hinspiel muesste
        wissen, dass spaeter noch etwas kommt.
        """
        assert mc.context_values(HIN, [HIN])["match_type"] \
            == mc.TYPE_KO_FIRST_LEG
        assert mc.context_values(HIN, PAARUNG)["match_type"] \
            == mc.TYPE_KO_FIRST_LEG


# ===========================================================================
# 6-7. Spieltypen
# ===========================================================================

class TestSpieltypen:

    @pytest.mark.parametrize("stage", mc.LEAGUE_PHASE_STAGES)
    def test_die_ligaphase_ist_kein_ko(self, stage):
        werte = mc.context_values(_partie("2024-10-01", stage, 3, 1, 2), [])
        assert werte["match_type"] == mc.TYPE_LEAGUE_PHASE
        assert werte["is_knockout"] == 0.0
        assert werte["is_first_leg"] == 0.0
        assert werte["is_second_leg"] == 0.0
        assert werte["is_final"] == 0.0
        assert werte["ko_round_index"] == 0.0
        assert werte["aggregate_available"] == 0

    def test_das_alte_und_das_neue_format_gelten_beide_als_rundenphase(self):
        """
        2023 Gruppenphase, ab 2024 Ligaphase. Die neue Ligaphase darf
        nicht als K.-o.-Runde durchgehen - sie ist der Nachfolger der
        Gruppenphase, nicht der Achtelfinalrunde.
        """
        assert mc.is_league_phase("GROUP_STAGE")
        assert mc.is_league_phase("LEAGUE_STAGE")
        assert not mc.is_knockout_stage("GROUP_STAGE")
        assert not mc.is_knockout_stage("LEAGUE_STAGE")

    def test_die_playoffs_sind_eine_ko_runde(self):
        """
        Die Playoffrunde ist ab 2024 neu. Sie ist eine echte
        K.-o.-Runde mit Hin- und Rueckspiel und darf nicht mit der
        Ligaphase verwechselt werden, nur weil sie neu ist.
        """
        assert mc.is_knockout_stage("PLAYOFFS")
        assert mc.match_type("PLAYOFFS", 1) == mc.TYPE_KO_FIRST_LEG
        assert mc.match_type("PLAYOFFS", 2) == mc.TYPE_KO_SECOND_LEG

    def test_das_endspiel_ist_eine_einzelpartie(self):
        for matchday in (None, 0, 1, 2):
            werte = mc.context_values(
                _partie("2025-05-31", "FINAL", matchday, 10, 20), [])
            assert werte["match_type"] == mc.TYPE_FINAL, matchday
            assert werte["is_final"] == 1.0
            assert werte["is_first_leg"] == 0.0
            assert werte["is_second_leg"] == 0.0
            assert werte["aggregate_available"] == 0

    def test_eine_ko_partie_ohne_legkennung_ist_eine_einzelpartie(self):
        """
        Kommt im Bestand 2023-2025 nicht vor. Kaeme sie vor - ein
        pandemiebedingtes Einzelspiel etwa -, muss sie als solche
        gefuehrt werden statt stillschweigend als Hinspiel.
        """
        assert mc.match_type("LAST_16", None) == mc.TYPE_KO_SINGLE
        assert mc.match_type("LAST_16", 0) == mc.TYPE_KO_SINGLE
        werte = mc.context_values(
            _partie("2025-03-04", "LAST_16", None, 10, 20), [])
        assert werte["is_knockout"] == 1.0
        assert werte["aggregate_available"] == 0

    def test_eine_unbekannte_runde_wird_nicht_geraten(self):
        assert mc.match_type("SUPERCUP", 1) == mc.TYPE_UNKNOWN
        assert mc.ko_round_index("SUPERCUP") is None

    def test_die_rundentiefe_ist_geordnet(self):
        tiefen = [mc.ko_round_index(s) for s in
                  ("GROUP_STAGE", "PLAYOFFS", "LAST_16", "QUARTER_FINALS",
                   "SEMI_FINALS", "FINAL")]
        assert tiefen == [0, 1, 2, 3, 4, 5]
        assert tiefen == sorted(tiefen)

    def test_die_wahrheitswerte_koennen_sich_nicht_widersprechen(self):
        for stage in (list(mc.LEAGUE_PHASE_STAGES) + list(mc.KNOCKOUT_STAGES)):
            for matchday in (None, 0, 1, 2):
                werte = mc.context_values(
                    _partie("2025-03-04", stage, matchday, 10, 20), PAARUNG)
                assert mc.context_consistency(werte) == [], (stage, matchday)

    def test_die_konsistenzpruefung_faengt_einen_widerspruch(self):
        """
        Die Pruefung muss auch wirklich anschlagen - sonst waere sie
        eine Zierde.
        """
        kaputt = {"match_type": mc.TYPE_FINAL, "is_final": 1.0,
                  "is_first_leg": 1.0, "is_second_leg": 0.0,
                  "is_knockout": 1.0, "aggregate_available": 0}
        assert mc.context_consistency(kaputt)


# ===========================================================================
# 8-9. Neutraler Ort und Regelkontext
# ===========================================================================

class TestOrtUndRegel:

    def test_das_endspiel_gilt_als_neutral(self):
        neutral, quelle = mc.neutral_venue("FINAL")
        assert neutral is True
        assert quelle == mc.VENUE_SOURCE_FINAL_RULE

    def test_jede_andere_partie_gilt_als_nicht_neutral(self):
        for stage in ("LEAGUE_STAGE", "GROUP_STAGE", "PLAYOFFS", "LAST_16",
                      "QUARTER_FINALS", "SEMI_FINALS"):
            neutral, quelle = mc.neutral_venue(stage)
            assert neutral is False
            assert quelle == mc.VENUE_SOURCE_HOME_AWAY

    def test_eine_unbekannte_runde_bleibt_sichtbar_unbekannt(self):
        neutral, quelle = mc.neutral_venue("SUPERCUP")
        assert neutral is None
        assert quelle == mc.VENUE_SOURCE_UNKNOWN

    def test_die_herkunft_wandert_in_jede_zeile(self):
        werte = mc.context_values(_partie("2025-05-31", "FINAL", None, 1, 2), [])
        assert werte["venue_source"] == mc.VENUE_SOURCE_FINAL_RULE

    def test_die_neutralitaet_haengt_an_der_runde_und_nicht_am_jahr(self):
        """
        Ein Endspiel im Stadion eines Finalisten hat es gegeben (2012).
        Die Regel ist deshalb an die Runde gebunden - so faellt ein
        solcher Fall spaeter als Abweichung auf, statt lautlos richtig
        zu wirken.
        """
        import inspect

        quelle = inspect.getsource(mc.neutral_venue)
        assert "FINAL_STAGE" in quelle
        assert "2012" in quelle or "Finalisten" in quelle

    @pytest.mark.parametrize("season,aktiv", [
        (2019, True), (2020, True), (2021, False), (2022, False),
        (2023, False), (2025, False)])
    def test_die_auswaertstorregel_ist_saisonabhaengig(self, season, aktiv):
        assert mc.away_goals_rule_active(season) is aktiv

    def test_die_auswaertstorregel_kennt_das_ergebnis_nicht(self):
        """
        Reiner Regelkontext: Die Funktion bekommt die Saison und sonst
        nichts. Sie aus dem Spielausgang abzuleiten waere ein
        Selbstleck.
        """
        import inspect

        # Die schaerfste pruefbare Fassung: Die Funktion NIMMT nur die
        # Saison. Eine Textsuche waere hier untauglich - der
        # Funktionsname selbst enthaelt "away_goals".
        assert list(inspect.signature(
            mc.away_goals_rule_active).parameters) == ["season"]
        quelle = inspect.getsource(mc.away_goals_rule_active)
        for verboten in ("home_goals", "away_goals\"", "outcome",
                         "home_id", "away_id"):
            assert verboten not in quelle

    def test_die_regel_ist_im_vorliegenden_bestand_konstant(self):
        """
        Ein Befund, kein Versehen: Alle drei Saisons liegen nach der
        Abschaffung. Das Merkmal kann deshalb nichts erklaeren, und die
        Redundanzpruefung weist es als konstant aus.
        """
        werte = {mc.away_goals_rule_active(s) for s in (2023, 2024, 2025)}
        assert werte == {False}


# ===========================================================================
# 10. Verlaengerung und Elfmeterschiessen
# ===========================================================================

class TestVerlaengerung:

    def test_die_quelle_fuehrt_keinen_verlaengerungsstatus(self):
        """
        Die ehrliche Feststellung, als Test: Die CL-Historie kennt nur
        FINISHED. Ein Merkmal "ging in die Verlaengerung" waere hier
        reine Erfindung - und wird deshalb nicht gebaut.
        """
        assert not any("extra_time" in feld or "penalt" in feld
                       for feld in ds.CONTEXT_FELDER)

    def test_der_aggregatstand_stammt_aus_dem_hinspiel(self):
        """
        Hinspiele gehen nie in die Verlaengerung - die Regel kennt sie
        erst im Rueckspiel. Der Aggregatstand VOR dem Rueckspiel ist
        deshalb von der Verlaengerungsfrage gar nicht betroffen.
        """
        werte = mc.context_values(RUECK, PAARUNG)
        assert werte["aggregate_goals_for"] == 1.0
        assert werte["aggregate_legs_played"] == 1

    def test_ein_ausgeglichenes_aggregat_wird_nicht_zum_merkmal(self):
        """
        Aus einem ueber beide Legs ausgeglichenen Ergebnis liesse sich
        schliessen, dass verlaengert wurde. Das steht aber erst NACH
        dem Spiel fest - es waere ein Selbstleck und darf deshalb in
        keiner Merkmalsspalte auftauchen.
        """
        verdaechtig = ("went_to_extra_time", "decided_on_penalties",
                       "tie_level_after_both_legs")
        for feld in verdaechtig:
            assert feld not in ds.CONTEXT_FELDER
            assert feld not in {e["name"] for e in ds.build_schema()}


# ===========================================================================
# 11. Mehrdeutige Paarungen
# ===========================================================================

class TestMehrdeutigkeit:

    def test_der_paarungsschluessel_ist_richtungsunabhaengig(self):
        assert mc.tie_key(2024, "LAST_16", 10, 20) \
            == mc.tie_key(2024, "LAST_16", 20, 10)

    def test_verschiedene_runden_sind_verschiedene_paarungen(self):
        assert mc.tie_key(2024, "LAST_16", 10, 20) \
            != mc.tie_key(2024, "QUARTER_FINALS", 10, 20)

    def test_verschiedene_saisons_sind_verschiedene_paarungen(self):
        assert mc.tie_key(2023, "LAST_16", 10, 20) \
            != mc.tie_key(2024, "LAST_16", 10, 20)

    def test_ohne_kennung_gibt_es_keinen_schluessel(self):
        assert mc.tie_key(2024, "LAST_16", None, 20) is None
        assert mc.tie_key(2024, "LAST_16", 10, None) is None

    def test_bei_mehreren_frueheren_partien_gewinnt_die_juengste(self):
        frueh = _partie("2025-02-01", "LAST_16", 1, 10, 20, (9, 0))
        spaet = _partie("2025-03-04", "LAST_16", 1, 10, 20, (1, 0))
        rueck = _partie("2025-03-12", "LAST_16", 2, 20, 10, (0, 0))
        assert mc.first_leg_of(rueck, [frueh, spaet, rueck]) is spaet

    def test_eine_ko_zeile_ohne_hinspiel_wird_begruendet_ausgeschlossen(self):
        grund = cd._knockout_ausschlussgrund(
            {"match_type": mc.TYPE_KO_SECOND_LEG, "aggregate_available": 0},
            [], ("domestic_pit", "domestic_pit"), (20, 20), 6)
        assert grund == cd.KO_REASON_NO_AGGREGATE

    def test_eine_widerspruechliche_zeile_wird_ausgeschlossen(self):
        grund = cd._knockout_ausschlussgrund(
            {"match_type": mc.TYPE_KO_FIRST_LEG, "aggregate_available": 0},
            ["Endspiel und zugleich Leg"], ("domestic_pit", "domestic_pit"),
            (20, 20), 6)
        assert grund.startswith(cd.KO_REASON_INCONSISTENT)

    def test_eine_ko_zeile_mit_duennem_profil_faellt_wie_bisher_aus(self):
        """
        C5 gibt nicht einfach alle 119 Zeilen frei: Dieselben
        fachlichen Huerden wie fuer die regulaere Phase gelten weiter.
        """
        grund = cd._knockout_ausschlussgrund(
            {"match_type": mc.TYPE_KO_FIRST_LEG, "aggregate_available": 0},
            [], ("domestic_pit", "domestic_pit"), (20, 3), 6)
        assert "Profiltiefe" in grund

    def test_eine_saubere_ko_zeile_wird_freigegeben(self):
        assert cd._knockout_ausschlussgrund(
            {"match_type": mc.TYPE_KO_FIRST_LEG, "aggregate_available": 0},
            [], ("domestic_pit", "domestic_pit"), (20, 20), 6) is None


# ===========================================================================
# 12. Paritaet Dataset gegen Runtime
# ===========================================================================

class TestParitaet:

    def test_es_gibt_nur_eine_kontextfunktion(self):
        import inspect

        for quelle in (inspect.getsource(cd.build_cl_season),
                       inspect.getsource(ds.build_league_season)):
            assert "context_values_for_match" in quelle
        geteilt = inspect.getsource(ds.context_values_for_match)
        assert "context_values" in geteilt
        assert "context_consistency" in geteilt

    def test_derselbe_aufruf_ergibt_exakt_dieselben_werte(self):
        a, va = ds.context_values_for_match(RUECK, PAARUNG)
        b, vb = ds.context_values_for_match(RUECK, PAARUNG)
        assert a == b and va == vb == []

    def test_die_spalten_heissen_wie_im_schema(self):
        werte, _ = ds.context_values_for_match(RUECK, PAARUNG)
        bekannt = {e["name"] for e in ds.build_schema()}
        assert set(werte) <= bekannt
        for feld in ds.CONTEXT_FELDER:
            assert feld in werte

    def test_die_werte_sind_exakt_gleich_ohne_toleranz(self):
        """
        Kein Float-Vergleich mit Toleranz: Der Kontext besteht aus
        Indikatoren und ganzzahligen Toren. Waere hier eine Toleranz
        noetig, liefe irgendwo eine zweite Rechnung.
        """
        a, _ = ds.context_values_for_match(RUECK, PAARUNG)
        b, _ = ds.context_values_for_match(RUECK, list(reversed(PAARUNG)))
        for feld in ds.CONTEXT_FELDER:
            assert a[feld] == b[feld] or (a[feld] is None and b[feld] is None)

    def test_ein_ligaspiel_laeuft_durch_dieselbe_funktion(self):
        import inspect

        quelle = inspect.getsource(ds.build_league_season)
        assert "LEAGUE_PHASE_STAGE_MARKER" in quelle
        werte, verstoesse = ds.context_values_for_match(
            {"stage": ds.LEAGUE_PHASE_STAGE_MARKER, "matchday": None,
             "season": 2024, "home_id": 1, "away_id": 2,
             "date": "2024-10-01"}, ())
        assert verstoesse == []
        assert werte["is_knockout"] == 0.0
        assert werte["aggregate_available"] == 0


# ===========================================================================
# 13. Fingerprints
# ===========================================================================

class TestFingerprint:

    def _hash(self, spalten, zeile):
        import hashlib

        roh = json.dumps({"columns": spalten,
                          "rows": [[zeile.get(s) for s in spalten]]},
                         sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(roh.encode("utf-8")).hexdigest()

    def _basis(self):
        zeile = {"row_id": "r1", "match_id": 1, "league": "cl",
                 "season": 2025, "date": "2025-03-12",
                 "evaluation_eligible": False, "home_goals": 2,
                 "away_goals": 0, "outcome": 0,
                 "baseline_lambda_home": 1.4, "baseline_lambda_away": 1.1,
                 "home_profile_source": "domestic_pit",
                 "away_profile_source": "domestic_pit",
                 "home_profile_matches": 20, "away_profile_matches": 20,
                 "exclusion_reason": None}
        for spalte in fg.columns_for(fg.C3_BASE_CANDIDATE):
            zeile[spalte] = 1.0
        zeile.update({"aggregate_diff": -2.0, "aggregate_lead": -1.0,
                      "aggregate_goals_for": 1.0,
                      "aggregate_goals_against": 3.0,
                      "aggregate_available": 1.0, "is_knockout": 1.0,
                      "is_second_leg": 1.0, "is_first_leg": 0.0,
                      "is_final": 0.0, "ko_round_index": 3.0,
                      "neutral_venue": 0.0, "away_goals_rule_active": 0.0})
        return zeile

    def _spalten(self, untergruppe):
        definition = fg.c5_variants((untergruppe,))[-1]
        return (list(ce.FINGERPRINT_IDENTITY) + list(ce.FINGERPRINT_TARGETS)
                + fg.columns_for_c5(definition)
                + list(ce.FINGERPRINT_PROVENANCE))

    @pytest.mark.parametrize("untergruppe,feld,neu", [
        ("aggregate_state", "aggregate_diff", 3.0),
        ("aggregate_state", "aggregate_lead", 1.0),
        ("aggregate_state", "aggregate_available", 0.0),
        ("knockout_context", "ko_round_index", 5.0),
        ("leg_context", "is_second_leg", 0.0),
        ("neutral_venue", "neutral_venue", 1.0),
    ])
    def test_ein_geaenderter_kontextwert_aendert_den_fingerabdruck(
            self, untergruppe, feld, neu):
        spalten = self._spalten(untergruppe)
        basis = self._basis()
        assert feld in spalten, feld
        assert self._hash(spalten, basis) \
            != self._hash(spalten, dict(basis, **{feld: neu}))

    def test_jede_vorab_festgelegte_variante_liest_eine_andere_menge(self):
        """
        Die acht vorab festgelegten Varianten muessen sich in ihrer
        Spaltenmenge unterscheiden - sonst maessen zwei Zeilen der
        Ablationstabelle dasselbe unter zwei Namen.

        Der reduzierte Kandidat ist ausgenommen: Bleibt aus der
        Vorauswahl genau eine Untergruppe uebrig, IST er die
        entsprechende Einzelvariante. Das ist kein Fehler, sondern die
        Aussage "die Reduktion hat auf diese eine Gruppe gefuehrt".
        """
        mengen = {d["name"]: tuple(fg.columns_for_c5(d))
                  for d in fg.c5_variants()}
        assert len(set(mengen.values())) == len(mengen)

    def test_der_reduzierte_kandidat_darf_einer_einzelvariante_gleichen(self):
        reduziert = fg.c5_variants(("aggregate_state",))[-1]
        einzeln = next(d for d in fg.c5_variants()
                       if d["name"].endswith("_plus_aggregate_state"))
        assert reduziert["name"] == fg.C5_REDUCED_CANDIDATE
        assert fg.columns_for_c5(reduziert) == fg.columns_for_c5(einzeln)


# ===========================================================================
# 14-15. Bestehende Vertraege
# ===========================================================================

class TestBestehendeVertraege:

    def test_der_regulaere_auswertungsbestand_bleibt_unveraendert(self):
        """
        evaluation_eligible bezeichnet weiterhin ausschliesslich die
        regulaere Phase. Wuerde C5 ihn erweitern, traegen der
        V1-Shadow-Backtest und die C3-/C4-Ablationen unter demselben
        Namen ploetzlich andere Zahlen.
        """
        zeilen = [
            {"league": "cl", "season": 2024, "date": "2024-09-01",
             "row_id": "a", "evaluation_eligible": True,
             "knockout_eligible": False},
            {"league": "cl", "season": 2024, "date": "2025-03-01",
             "row_id": "b", "evaluation_eligible": False,
             "knockout_eligible": True},
        ]
        assert [z["row_id"] for z in ce.cl_rows(zeilen, 2024)] == ["a"]
        assert [z["row_id"] for z in ce.context_rows(zeilen, [2024])] \
            == ["a", "b"]

    def test_die_alten_folds_sind_unangetastet(self):
        assert ce.OUTER_FOLDS == (
            {"name": "cl_2024", "train_seasons": [2023], "test_season": 2024},
            {"name": "cl_2025", "train_seasons": [2023, 2024],
             "test_season": 2025})

    def test_der_kontextvertrag_ist_zeitlich_sauber(self):
        for fold in ce.CONTEXT_FOLDS:
            assert max(fold["train_seasons"]) < fold["test_season"]

    def test_league_rows_nimmt_keine_cl_zeile(self):
        zeilen = [
            {"league": "bl1", "season": 2023, "date": "2023-09-01",
             "row_id": "a", "evaluation_eligible": True},
            {"league": "cl", "season": 2023, "date": "2023-09-02",
             "row_id": "b", "evaluation_eligible": True,
             "knockout_eligible": False},
        ]
        assert [z["row_id"] for z in ce.league_rows(zeilen, [2023])] == ["a"]

    def test_der_kontexttrainingsbestand_enthaelt_beide_quellen(self):
        zeilen = [
            {"league": "bl1", "season": 2023, "date": "2023-09-01",
             "row_id": "a", "evaluation_eligible": True},
            {"league": "cl", "season": 2023, "date": "2023-09-02",
             "row_id": "b", "evaluation_eligible": True,
             "knockout_eligible": False},
            {"league": "cl", "season": 2023, "date": "2024-03-02",
             "row_id": "c", "evaluation_eligible": False,
             "knockout_eligible": True},
        ]
        assert [z["row_id"] for z in ce.context_training_rows(zeilen, [2023])] \
            == ["a", "b", "c"]

    def test_der_v1_vertrag_ist_unveraendert(self):
        assert fg.columns_for("team_profile_cl") == [
            "away_attack_away", "away_attack_home",
            "away_defence_away", "away_defence_home",
            "away_goals_against_per_game", "away_goals_for_per_game",
            "away_points_per_game", "away_win_rate",
            "home_attack_away", "home_attack_home",
            "home_defence_away", "home_defence_home",
            "home_goals_against_per_game", "home_goals_for_per_game",
            "home_points_per_game", "home_win_rate",
        ]

    def test_die_bestehenden_varianten_behalten_ihre_groesse(self):
        for name, anzahl in (("profile_only", 22), ("workload_only", 24),
                             ("team_profile_only", 18),
                             ("league_average_only", 4),
                             ("team_profile_cl", 16)):
            assert len(fg.columns_for(name)) == anzahl, name

    def test_der_v1_kandidat_traegt_kein_kontextmerkmal(self):
        spalten = set(fg.columns_for(fg.C3_BASE_CANDIDATE))
        assert not (spalten & set(ds.CONTEXT_FELDER))

    def test_die_frueheren_vertraege_bleiben_bestehen(self):
        from src.features import match_timeline, pit_profiles
        from src.ml import persist

        assert hasattr(persist, "_pruefe_freigabestufe")     # C0B
        assert hasattr(pit_profiles, "require_cutoff")       # C1
        assert match_timeline.COVERAGE_OK == "covered"       # C2
        assert hasattr(ca, "run_c3_ablation")                # C3
        assert hasattr(ca, "run_c4_ablation")                # C4
        assert fg.SUBGROUP_ORDER and fg.C4_SUBGROUP_ORDER

    def test_die_drei_untergruppenraeume_ueberschneiden_sich_nicht(self):
        c3 = set(fg.SUBGROUP_ORDER)
        c4 = set(fg.C4_SUBGROUP_ORDER)
        c5 = set(fg.C5_SUBGROUP_ORDER)
        assert not (c3 & c4) and not (c3 & c5) and not (c4 & c5)

    def test_ein_fremder_untergruppenname_bricht_ab(self):
        with pytest.raises(ValueError, match="unbekannte Kontextuntergruppe"):
            fg.columns_for_c5({"name": "x", "groups": (),
                               "subgroups": ("short_rest",)})

    def test_die_kontextspalten_haben_kein_seitenpraefix(self):
        """
        Der Kontext gehoert der PARTIE, nicht einer Mannschaft. Ein
        home_/away_-Praefix wuerde eine Seitenzugehoerigkeit
        vortaeuschen, die es nicht gibt.

        away_goals_rule_active ist die eine Ausnahme, und sie ist
        keine: "away goals" ist der Name der REGEL, kein Hinweis auf
        die Gastmannschaft. Sie steht namentlich hier, damit die
        Ausnahme sichtbar bleibt und nicht als Luecke im Test.
        """
        ausnahme = {"away_goals_rule_active"}
        for feld in ds.CONTEXT_FELDER:
            if feld in ausnahme:
                continue
            assert not feld.startswith(("home_", "away_")), feld

        # Und die Ausnahme ist wirklich zeilenweise: Es gibt keine
        # zweite Fassung fuer die andere Seite.
        assert "home_goals_rule_active" not in ds.CONTEXT_FELDER

    def test_die_kontextgruppe_zerlegt_sich_vollstaendig(self):
        bericht = fg.validate_c5_subgroups()
        assert sum(bericht["counts"].values()) \
            == bericht["total_context_features"]

    def test_die_fassung_ist_mindestens_die_von_c5(self):
        """
        C5 hat die Fassung auf 4 gehoben, C7 auf 5. Geprueft wird die
        Untergrenze: Ein sinkender Wert waere ein Fehler, ein
        steigender der Normalfall.
        """
        assert fg.SCHEMA_VERSION >= 4

    def test_die_eligibility_spalten_sind_keine_merkmale(self):
        merkmale = set(mdl.feature_columns())
        for spalte in ("evaluation_eligible", "knockout_eligible",
                       "knockout_exclusion_reason", "match_type",
                       "venue_source"):
            assert spalte not in merkmale


class TestInnererSplit:

    def test_der_selektor_ist_waehlbar_und_faellt_auf_das_alte_zurueck(self):
        zeilen = [
            {"season": 2023, "date": "2023-09-01", "row_id": "a",
             "evaluation_eligible": True},
            {"season": 2023, "date": "2023-11-01", "row_id": "b",
             "evaluation_eligible": False},
        ]
        fit, val, _ = ev.inner_split(zeilen, {"train_seasons": [2023]})
        assert [z["row_id"] for z in fit + val] == ["a"]

        alle = lambda z, s: [x for x in z if x["season"] in set(s)]  # noqa: E731
        fit, val, _ = ev.inner_split(zeilen, {"train_seasons": [2023]},
                                     select=alle)
        assert sorted(z["row_id"] for z in fit + val) == ["a", "b"]


# ===========================================================================
# 16-18. Abgrenzung
# ===========================================================================

class TestAbgrenzung:

    def test_c5_stuft_kein_modell_hoch(self):
        import inspect

        quelle = inspect.getsource(mc)
        for verboten in ("save_bundle", "train_cl_model", "approved",
                         "release_stage"):
            assert verboten not in quelle

    def test_keine_ui_kennt_die_kontextmerkmale(self):
        import pathlib

        wurzel = pathlib.Path(__file__).resolve().parents[1]
        verdaechtig = ("aggregate_diff", "aggregate_lead", "is_second_leg",
                       "ko_round_index", "neutral_venue")
        dateien = (list((wurzel / "templates").rglob("*.html"))
                   + list((wurzel / "static").rglob("*.js"))
                   + list((wurzel / "static").rglob("*.css")))
        for pfad in dateien:
            text = pfad.read_text(encoding="utf-8", errors="replace")
            for begriff in verdaechtig:
                assert begriff not in text, f"{begriff} in {pfad.name}"

    def test_die_registrierungen_tragen_ihren_vertrag(self):
        c3, c4, c5 = (ca.workload_registry(), ca.form_registry(),
                      ca.context_registry())
        assert c3.contract == c4.contract
        assert c5.contract != c3.contract
        assert c5.train_rows is not None and c5.test_rows is not None
        assert c3.train_rows is None and c3.test_rows is None

    def test_das_gate_bleibt_das_bestehende(self):
        regeln = ca.decision_criteria()
        assert regeln["severe_degradation_threshold"] == ce.SEVERE_DEGRADATION
        assert regeln["min_reliable_n"] == ce.MIN_RELIABLE_N
        assert regeln["paired_against"] == fg.C3_BASE_CANDIDATE

    def test_alle_c5_varianten_stehen_vorab_fest(self):
        namen = [d["name"] for d in fg.c5_variants()]
        assert namen[0] == fg.C3_BASE_CANDIDATE
        assert len(namen) == len(set(namen))
        assert len(namen) == 1 + len(fg.C5_SUBGROUP_ORDER) + 3

    def test_der_reduzierte_kandidat_entfaellt_ohne_vorauswahl(self):
        assert fg.C5_REDUCED_CANDIDATE not in [d["name"]
                                               for d in fg.c5_variants(())]
        assert fg.C5_REDUCED_CANDIDATE in [
            d["name"] for d in fg.c5_variants(("aggregate_state",))]


class TestRunnerUnabhaengigkeit:

    def test_das_kontextmodul_liest_keine_datei(self):
        import inspect

        quelle = inspect.getsource(mc)
        assert "open(" not in quelle
        assert "load_season" not in quelle
        for verboten in ("APISPORTS_KEY", "load_dotenv", "requests."):
            assert verboten not in quelle

    def test_diese_datei_braucht_keinen_bestand(self):
        import pathlib

        quelle = pathlib.Path(__file__).read_text(encoding="utf-8")
        for teil in ("data/" + "historical", "data/" + "ml",
                     "data/" + "cache", "data/" + "big_games"):
            assert teil not in quelle
