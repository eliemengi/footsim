"""
Tests fuer GO 4 (Kaderverfuegbarkeit) und GO 5 (Transferwirkung).

Gliederung nach Teil P des Auftrags:

    I   Player Identity und Crosswalk        (1-6)
    B   Importance                           (7-15)
    Q   Quality                              (16-22)
    A   Availability                         (23-37)
    T   Transfers                            (38-51)
    D   Decay                                (52-61)
    K   Kombination                          (62-73)
    S   Snapshots und Sicherheit             (74-80)
    R   Backtest                             (81-88)

Regelfaelle laufen gegen gebaute Daten statt gegen Echtdaten: Ein Test,
der bei jeder Poolaktualisierung anders ausgeht, prueft nicht die Regel,
sondern den Datenstand. Wo Echtdaten noetig sind, steht es dabei.
"""

import json
import os
from datetime import date, datetime

import pytest

from src.features import go4, go5, go45_provider
from src.features.player_identity import (
    build_player_index, build_team_name_index, identity_report,
    is_historical_squad_known, is_productive, normalize_player_name,
    resolve_player, resolve_player_by_name, resolve_team_name)
from src.features.player_importance import (
    IMPORTANCE_MAX, IMPORTANCE_MIN, build_peer_maxima, player_importance,
    position_group, role_score)
from src.features.player_quality import (
    MIN_METRICS_FOR_QUALITY, player_quality, replacement_quality)
from src.features.squad_availability import (
    EXPECTED_STARTERS, MAX_POSITION_LOSS, QUESTIONABLE_WEIGHT,
    group_pool_by_team, normalize_absences, normalize_status,
    position_availability, status_weight, team_availability)
from src.features.transfer_events import (
    build_team_index, normalize_transfer, normalize_type, parse_date,
    season_of, team_window_transfers, team_window_transfers_indexed,
    transfers_before)


# ---------------------------------------------------------------------------
# Bausteine
# ---------------------------------------------------------------------------

def spieler(pid, name="X. Test", position="Attacker", minuten=2000,
            lineups=22, appearances=25, **metriken):
    """Ein Poolspieler mit steuerbaren Metriken."""
    basis = {
        "rating": 7.0, "appearances": appearances, "lineups": lineups,
        "minutes": minuten, "goals": 10, "assists": 5,
        "goals_per90": 0.45, "assists_per90": 0.22, "shots_per90": 2.5,
        "goal_contributions_per90": 0.67, "key_passes_per90": 1.2,
        "passes_per90": 35.0, "dribbles_success_per90": 1.0,
        "tackles_per90": 1.5, "interceptions_per90": 1.2,
        "blocks_per90": 0.4, "duels_won_pct": 52.0,
        "saves_per90": 3.0, "conceded_per90": 1.2, "pass_accuracy_pct": 70.0,
    }
    basis.update(metriken)
    return {
        "player_id": pid, "name": name, "position": position,
        "team_name": "Testverein", "age": 26,
        "minutes_by_scope": {"league": minuten},
        "metrics_by_scope": {"league": dict(basis), "club_all": dict(basis)},
    }


def transfer(pid, datum, zu=1, von=2, art="Transfer", name="X. Test"):
    """Ein Rohtransfer im Providerformat."""
    return ({"id": pid, "name": name},
            {"date": datum, "type": art,
             "teams": {"in": {"id": zu, "name": f"Team {zu}"},
                       "out": {"id": von, "name": f"Team {von}"}}})


@pytest.fixture
def pool():
    """Ein kleiner Pool mit allen vier Positionsgruppen."""
    eintraege = []
    for i in range(40):
        eintraege.append(spieler(100 + i, f"A {i}", "Attacker"))
        eintraege.append(spieler(200 + i, f"D {i}", "Defender"))
        eintraege.append(spieler(300 + i, f"M {i}", "Midfielder"))
        eintraege.append(spieler(400 + i, f"G {i}", "Goalkeeper"))
    return eintraege


@pytest.fixture
def maxima(pool):
    return build_peer_maxima(pool)


# ---------------------------------------------------------------------------
# I  Player Identity und Crosswalk
# ---------------------------------------------------------------------------

class TestI_Identity:

    def test_i1_stabile_id_schlaegt_namen(self):
        """Die Provider-ID ist die Identitaet, nicht der Name."""
        r = resolve_player(4711, name="irgendwer")
        assert r["player_id"] == 4711
        assert r["confidence"] == "provider_id"
        assert is_productive(r["confidence"])

    def test_i2_gleichnamige_bleiben_getrennt(self):
        index = build_player_index([
            spieler(1, "T. Mueller", "Attacker"),
            spieler(2, "T. Mueller", "Defender"),
        ])
        assert "t mueller" in index["duplicate_names"]
        r = resolve_player_by_name(index, "T. Mueller")
        assert r["player_id"] is None
        assert r["reason"] == "ambiguous"

    def test_i2b_position_trennt_gleichnamige(self):
        index = build_player_index([
            spieler(1, "T. Mueller", "Attacker"),
            spieler(2, "T. Mueller", "Defender"),
        ])
        r = resolve_player_by_name(index, "T. Mueller", position="Defender")
        assert r["player_id"] == 2
        # Trotz Eindeutigkeit nur ein VORSCHLAG - der Pool fuehrt kein
        # Geburtsdatum.
        assert r["confidence"] == "suggested"
        assert not is_productive(r["confidence"])

    def test_i3_transfer_aendert_zuordnung_erst_ab_datum(self):
        events = [normalize_transfer(*transfer(1, "2025-08-01"))]
        assert transfers_before(events, "2025-07-31") == []
        assert len(transfers_before(events, "2025-08-02")) == 1

    def test_i4_jugendteam_wird_nicht_profiteam(self):
        index = build_team_name_index({1: "Bayern Muenchen", 2: "Bayern Muenchen II"})
        assert resolve_team_name(index, "Bayern Muenchen")["team_id"] == 1
        assert resolve_team_name(index, "Bayern Muenchen II")["team_id"] == 2

    def test_i5_nationalteam_wird_nicht_club(self):
        index = build_team_name_index({1: "Bayern Muenchen"})
        r = resolve_team_name(index, "Germany")
        assert r["team_id"] is None and r["reason"] == "no_match"

    def test_i6_unklarer_spieler_bleibt_neutral(self):
        r = resolve_player(None, name="Unbekannt")
        assert r["player_id"] is None
        assert not is_productive(r["confidence"])

    def test_i6b_mehrdeutiger_teamname_wird_nicht_zugeordnet(self):
        index = build_team_name_index({1: "FC Test", 2: "Test FC"})
        assert resolve_team_name(index, "FC Test")["reason"] == "ambiguous"

    def test_i6c_abgekuerzter_vorname_bleibt_erhalten(self):
        """"B. Oczipka" darf nicht zu "oczipka" verkuerzt werden."""
        assert normalize_player_name("B. Oczipka") == "b oczipka"
        assert normalize_player_name("B. Oczipka") != normalize_player_name("M. Oczipka")

    def test_i6d_historischer_kader_ohne_snapshot_ist_unbekannt(self):
        assert is_historical_squad_known(as_of=None) is True
        assert is_historical_squad_known(as_of="2024-11-12", has_snapshot=False) is False
        assert is_historical_squad_known(as_of="2024-11-12", has_snapshot=True) is True

    def test_i6e_diagnose_nennt_luecken(self, pool):
        bericht = identity_report(pool, squad_player_ids=[100, 999999],
                                  injury_player_ids=[100, 888888])
        assert bericht["pool_players"] == len(pool)
        assert bericht["squad_without_stats"] == 1
        assert bericht["injuries_without_stats"] == 1


# ---------------------------------------------------------------------------
# B  Importance
# ---------------------------------------------------------------------------

class TestB_Importance:

    def test_b7_stammspieler_wichtiger_als_joker(self, maxima):
        """
        Kernforderung: Bei sonst gleichen Daten hat der Stammspieler die
        groessere Rolle.
        """
        stamm = player_importance(spieler(1, minuten=3000, lineups=33,
                                          appearances=34), maxima, 3060, 34)
        joker = player_importance(spieler(2, minuten=300, lineups=1,
                                          appearances=20), maxima, 3060, 34)
        assert stamm["player_importance"] > joker["player_importance"]

    def test_b8_joker_mit_starken_per90_dominiert_nicht(self, maxima):
        """
        Ein Joker mit doppelt so guten per-90-Werten darf einen
        Stammspieler nicht ueberholen - Importance ist Rolle, nicht Guete.
        """
        stamm = player_importance(
            spieler(1, minuten=3000, lineups=33, appearances=34,
                    goals_per90=0.2, assists_per90=0.1,
                    goal_contributions_per90=0.3, shots_per90=1.0),
            maxima, 3060, 34)
        joker = player_importance(
            spieler(2, minuten=300, lineups=2, appearances=20,
                    goals_per90=1.5, assists_per90=1.0,
                    goal_contributions_per90=2.5, shots_per90=6.0),
            maxima, 3060, 34)
        assert stamm["player_importance"] > joker["player_importance"]

    def test_b9_torwart_positionsgerecht(self, maxima):
        r = player_importance(spieler(1, position="Goalkeeper"), maxima, 3060, 34)
        assert r["position_group"] == "Goalkeeper"
        assert "saves_per90" in r["metrics_used"]
        assert "goals_per90" not in r["metrics_used"]

    def test_b10_verteidiger_nicht_ueber_tore(self, maxima):
        r = player_importance(spieler(1, position="Defender"), maxima, 3060, 34)
        assert "goals_per90" not in r["metrics_used"]
        assert "tackles_per90" in r["metrics_used"]

    def test_b11_null_minuten_nutzt_referenz(self, maxima):
        r = player_importance(spieler(1, minuten=0, lineups=0, appearances=0),
                              maxima, 3060, 34, reference_importance=0.7,
                              reference_season=2024)
        assert r["current_weight"] == 0.0
        # Ohne eigene Minuten traegt die Referenz den Wert vollstaendig.
        assert r["player_importance"] == pytest.approx(0.7, abs=1e-6)

    def test_b12_mehr_minuten_erhoehen_aktuellen_anteil(self, maxima):
        wenig = player_importance(spieler(1, minuten=200), maxima, 3060, 34)
        viel = player_importance(spieler(2, minuten=2500), maxima, 3060, 34)
        assert viel["current_weight"] > wenig["current_weight"]

    def test_b13_keine_referenz_erzeugt_keinen_fantasiewert(self, maxima):
        r = player_importance(spieler(1), maxima, None, None)
        assert r["player_importance"] is None
        assert r["importance_quality"] == "unavailable"

    def test_b14_gleiche_daten_gleicher_wert(self, maxima):
        a = player_importance(spieler(1), maxima, 3060, 34)
        b = player_importance(spieler(1), maxima, 3060, 34)
        assert a["player_importance"] == b["player_importance"]

    def test_b15_wertebereich_wird_eingehalten(self, maxima, pool):
        for eintrag in pool:
            r = player_importance(eintrag, maxima, 3060, 34)
            if r["player_importance"] is not None:
                assert IMPORTANCE_MIN <= r["player_importance"] <= IMPORTANCE_MAX

    def test_b15b_fehlende_metrik_wird_nicht_zu_null(self, maxima):
        """
        Eine vom Anbieter nicht gefuehrte Metrik faellt aus der
        Gewichtung, statt den Spieler abzuwerten.
        """
        ohne = spieler(1, position="Defender")
        ohne["metrics_by_scope"]["league"].pop("blocks_per90")
        r = player_importance(ohne, maxima, 3060, 34)
        assert "blocks_per90" not in r["metrics_used"]
        assert r["player_importance"] is not None

    def test_b15c_rolle_wiegt_schwerer_als_beitrag(self):
        from src.features.player_importance import CONTRIBUTION_WEIGHT, ROLE_WEIGHT
        assert ROLE_WEIGHT > CONTRIBUTION_WEIGHT
        assert ROLE_WEIGHT + CONTRIBUTION_WEIGHT == pytest.approx(1.0)

    def test_b15d_ohne_kapazitaet_keine_rolle(self):
        assert role_score(1000, 10, 12, None, None) == (None, None, None)


# ---------------------------------------------------------------------------
# Q  Quality
# ---------------------------------------------------------------------------

def snapshot_mit(positionen):
    """Ein Perzentil-Snapshot im echten Projektformat."""
    verteilungen = {}
    for position, metriken in positionen.items():
        verteilungen[position] = {
            "player_count": 100,
            "metrics": {name: {"n": 100, "q": werte}
                        for name, werte in metriken.items()},
        }
    return {"season": 2025, "scope": "club_all",
            "distributions": verteilungen,
            "distributions_by_scope": {"club_all": verteilungen}}


def quantile(start=0.0, ende=1.0):
    return [start + (ende - start) * i / 100.0 for i in range(101)]


class TestQ_Quality:

    def test_q16_positionsvergleich_korrekt(self):
        snap = snapshot_mit({"Attacker": {
            "goals_per90": quantile(0, 1), "assists_per90": quantile(0, 1),
            "shots_per90": quantile(0, 5),
            "goal_contributions_per90": quantile(0, 2)}})
        stark = player_quality(spieler(1, goals_per90=0.95, minuten=3000), snap)
        schwach = player_quality(spieler(2, goals_per90=0.05, minuten=3000), snap)
        assert stark["player_quality"] > schwach["player_quality"]

    def test_q17_torwart_nur_gegen_passende_gruppe(self):
        snap = snapshot_mit({
            "Goalkeeper": {"saves_per90": quantile(0, 5),
                           "conceded_per90": quantile(0, 3),
                           "pass_accuracy_pct": quantile(0, 100)},
            "Attacker": {"goals_per90": quantile(0, 1)},
        })
        r = player_quality(spieler(1, position="Goalkeeper"), snap)
        assert r["position_group"] == "Goalkeeper"
        assert set(r["metrics_used"]) <= {"saves_per90", "conceded_per90",
                                          "pass_accuracy_pct"}

    def test_q18_verteidiger_nicht_gegen_angreifer(self):
        snap = snapshot_mit({"Attacker": {"goals_per90": quantile(0, 1)}})
        r = player_quality(spieler(1, position="Defender"), snap)
        # Es gibt keine Verteidigerverteilung - also keinen Wert.
        assert r["player_quality"] is None
        assert r["quality_data_status"] == "unavailable"

    def test_q19_unvollstaendige_coverage_senkt_status(self):
        snap = snapshot_mit({"Defender": {
            "tackles_per90": quantile(0, 4),
            "interceptions_per90": quantile(0, 4)}})
        r = player_quality(spieler(1, position="Defender"), snap)
        assert r["quality_data_status"] == "partial"

    def test_q20_fehlende_daten_neutral(self):
        r = player_quality(spieler(1), None)
        assert r["player_quality"] is None
        assert r["quality_data_status"] == "unavailable"

    def test_q21_zu_wenige_metriken_ergeben_keinen_wert(self):
        snap = snapshot_mit({"Attacker": {"goals_per90": quantile(0, 1)}})
        r = player_quality(spieler(1), snap)
        assert r["player_quality"] is None
        assert r["reason"] == "not_enough_metrics"
        assert MIN_METRICS_FOR_QUALITY == 2

    def test_q22_rohwerte_bleiben_unveraendert(self):
        """Stabilisierung veraendert die Einordnung, nie die Rohdaten."""
        eintrag = spieler(1, minuten=90, goals_per90=1.64)
        vorher = json.dumps(eintrag, sort_keys=True)
        snap = snapshot_mit({"Attacker": {
            "goals_per90": quantile(0, 1), "assists_per90": quantile(0, 1),
            "shots_per90": quantile(0, 5)}})
        player_quality(eintrag, snap)
        assert json.dumps(eintrag, sort_keys=True) == vorher

    def test_q22b_kleine_gruppe_ergibt_keinen_wert(self):
        snap = snapshot_mit({"Attacker": {"goals_per90": quantile(0, 1),
                                          "assists_per90": quantile(0, 1)}})
        snap["distributions_by_scope"]["club_all"]["Attacker"]["player_count"] = 5
        r = player_quality(spieler(1), snap)
        assert r["reason"] == "group_too_small"

    def test_q22c_ersatz_nur_aus_derselben_position(self):
        eintraege = {
            1: {"position_group": "Goalkeeper", "player_quality": 0.4, "minutes": 3000},
            2: {"position_group": "Attacker", "player_quality": 0.9, "minutes": 3000},
        }
        assert replacement_quality(eintraege, "Goalkeeper") == 0.4

    def test_q22d_ersatz_braucht_mindestminuten(self):
        eintraege = {1: {"position_group": "Goalkeeper",
                         "player_quality": 0.9, "minutes": 90}}
        assert replacement_quality(eintraege, "Goalkeeper", min_minutes=270) is None


# ---------------------------------------------------------------------------
# A  Availability
# ---------------------------------------------------------------------------

def kader(importance_werte, quality_werte=None):
    """Baut importance-/quality-Tabellen aus {pid: (position, wert)}."""
    imp = {}
    qual = {}
    for pid, (position, wert) in importance_werte.items():
        imp[pid] = {"player_id": pid, "player_name": f"P{pid}",
                    "position_group": position, "player_importance": wert,
                    "minutes": 2500}
        q = (quality_werte or {}).get(pid, 0.5)
        qual[pid] = {"player_id": pid, "player_name": f"P{pid}",
                     "position_group": position, "player_quality": q,
                     "minutes": 2500}
    return imp, qual


ELF = {
    1: ("Goalkeeper", 0.9), 2: ("Goalkeeper", 0.3),
    11: ("Defender", 0.9), 12: ("Defender", 0.8), 13: ("Defender", 0.8),
    14: ("Defender", 0.7), 15: ("Defender", 0.4),
    21: ("Midfielder", 0.9), 22: ("Midfielder", 0.8), 23: ("Midfielder", 0.7),
    24: ("Midfielder", 0.6), 25: ("Midfielder", 0.4),
    31: ("Attacker", 0.9), 32: ("Attacker", 0.8), 33: ("Attacker", 0.4),
}


class TestA_Availability:

    def setup_method(self):
        self.imp, self.qual = kader(ELF)
        self.ids = list(ELF)

    def _mit(self, *pids, status="Injury"):
        ausfaelle = normalize_absences(
            [{"player_id": p, "type": status, "reason": "Test"} for p in pids])
        return team_availability(self.ids, self.imp, self.qual, ausfaelle,
                                 absences_known=True)

    def test_a23_angreifer_fehlt_trifft_angriff(self):
        r = self._mit(31)
        assert r["availability_attack"] < 1.0
        assert r["availability_defence"] == 1.0
        assert r["availability_goalkeeper"] == 1.0

    def test_a24_verteidiger_fehlt_trifft_abwehr(self):
        r = self._mit(11)
        assert r["availability_defence"] < 1.0
        assert r["availability_attack"] == 1.0

    def test_a25_torwart_fehlt_trifft_torwart(self):
        r = self._mit(1)
        assert r["availability_goalkeeper"] < 1.0
        assert r["availability_attack"] == 1.0

    def test_a26_mittelfeld_wirkt_auf_seinen_bereich(self):
        r = self._mit(21)
        assert r["availability_midfield"] < 1.0
        # Die Aufteilung auf Angriff und Abwehr passiert erst in go4,
        # nicht schon in der Verfuegbarkeit.
        assert r["availability_attack"] == 1.0

    def test_a27_guter_ersatz_reduziert_malus(self):
        gut = dict.fromkeys([], None)
        imp_a, qual_a = kader(ELF, {32: 0.95, 33: 0.95})
        imp_b, qual_b = kader(ELF, {32: 0.05, 33: 0.05})
        aus = normalize_absences([{"player_id": 31, "type": "Injury"}])
        mit_gutem = team_availability(self.ids, imp_a, qual_a, aus, absences_known=True)
        mit_schwachem = team_availability(self.ids, imp_b, qual_b, aus, absences_known=True)
        assert mit_gutem["availability_attack"] > mit_schwachem["availability_attack"]

    def test_a28_ausfaelle_bleiben_geclamped(self):
        r = self._mit(11, 12, 13, 14, 15)
        assert r["positions"]["Defender"]["loss"] <= MAX_POSITION_LOSS + 1e-9
        assert r["positions"]["Defender"]["clamped"] is True

    def test_a29_fraglich_nicht_wie_sicher_aus(self):
        sicher = self._mit(31, status="Injury")
        fraglich = self._mit(31, status="Questionable")
        assert fraglich["availability_attack"] > sicher["availability_attack"]
        assert status_weight("questionable") == pytest.approx(QUESTIONABLE_WEIGHT)

    def test_a30_keine_injury_daten_neutral(self):
        r = team_availability(self.ids, self.imp, self.qual, {}, absences_known=True)
        assert r["overall_availability"] == 1.0

    def test_a31_heutige_verletzung_nicht_rueckwirkend(self):
        """
        Ohne archivierten Stand gibt es keine Aussage - und ausdruecklich
        nicht "alle verfuegbar".
        """
        r = team_availability(self.ids, self.imp, self.qual, {},
                              as_of="2024-11-12", absences_known=False)
        assert r["available"] is False
        assert r["overall_availability"] is None
        assert r["data_quality"] == "unavailable"

    def test_a31b_pool_gruppierung_historisch_gesperrt(self, pool):
        assert group_pool_by_team(pool) != {}
        assert group_pool_by_team(pool, as_of="2024-11-12") == {}

    def test_a32_sperre_wird_erkannt(self):
        assert normalize_status("Missing Fixture", "Suspended") == "suspended"
        assert status_weight("suspended") == 1.0

    def test_a33_normale_verfuegbarkeit_neutral(self):
        r = team_availability(self.ids, self.imp, self.qual, {}, absences_known=True)
        mod = go4.compute_modifier(r)
        assert mod["attack_modifier"] == 0.0
        assert mod["defence_modifier"] == 0.0

    def test_a34_mehrere_ausfaelle_bleiben_begrenzt(self):
        r = self._mit(*self.ids)
        mod = go4.compute_modifier(r)
        grenze = go4.CONSTANTS["MAX_TOTAL_EFFECT"]["wert"]
        assert abs(mod["attack_modifier"]) <= grenze + 1e-9
        assert abs(mod["defence_modifier"]) <= grenze + 1e-9

    def test_a35_unbekannter_status_ist_kein_ausfall(self):
        assert normalize_status(None, None) == "unknown"
        assert status_weight("unknown") == 0.0
        ausfaelle = normalize_absences([{"player_id": 31, "type": None}])
        assert ausfaelle == {}

    def test_a36_schwerster_status_gewinnt(self):
        ausfaelle = normalize_absences([
            {"player_id": 31, "type": "Questionable"},
            {"player_id": 31, "type": "Missing Fixture", "reason": "Suspended"},
        ])
        assert ausfaelle[31]["status"] == "suspended"

    def test_a37_sollbesetzung_ist_dokumentiert(self):
        assert EXPECTED_STARTERS["Goalkeeper"] == 1
        assert sum(EXPECTED_STARTERS.values()) == 11

    def test_a37b_leere_position_ist_kein_verlust(self):
        r = position_availability([], {}, {}, {}, "Attacker")
        assert r["loss"] == 0.0
        assert r["data_quality"] == "unavailable"

    def test_a37c_ausfall_ohne_importance_bleibt_belegbar_gekennzeichnet(self):
        imp = {31: {"position_group": "Attacker", "player_importance": None,
                    "player_name": "P31", "minutes": 0}}
        qual = {31: {"position_group": "Attacker", "player_quality": None,
                     "minutes": 0}}
        aus = normalize_absences([{"player_id": 31, "type": "Injury"}])
        r = position_availability([31], imp, qual, aus, "Attacker")
        assert r["out_count"] == 1
        assert r["loss"] == 0.0            # nicht belegbar -> kein Betrag
        assert r["data_quality"] == "fallback"


# ---------------------------------------------------------------------------
# T  Transfers
# ---------------------------------------------------------------------------

class TestT_Transfers:

    def test_t38_zugang_erkannt(self):
        e = normalize_transfer(*transfer(1, "2025-07-01", zu=10, von=20))
        zu, ab = team_window_transfers([e], 10, "2025-08-01", 2025)
        assert len(zu) == 1 and ab == []

    def test_t39_abgang_erkannt(self):
        e = normalize_transfer(*transfer(1, "2025-07-01", zu=10, von=20))
        zu, ab = team_window_transfers([e], 20, "2025-08-01", 2025)
        assert zu == [] and len(ab) == 1

    def test_t40_leihe_unterschieden(self):
        assert normalize_type("Loan") == "loan"

    def test_t41_leihende_unterschieden(self):
        assert normalize_type("Return from loan") == "loan_return"
        assert normalize_type("Back from Loan") == "loan_return"

    def test_t42_zukuenftiger_transfer_wird_nicht_verwendet(self):
        e = normalize_transfer(*transfer(1, "2025-12-01", zu=10))
        assert team_window_transfers([e], 10, "2025-08-01", 2025) == ([], [])

    def test_t43_transfer_vor_zielspiel_wird_verwendet(self):
        e = normalize_transfer(*transfer(1, "2025-07-01", zu=10))
        zu, _ = team_window_transfers([e], 10, "2025-08-01", 2025)
        assert len(zu) == 1

    def test_t43b_transfer_am_spieltag_zaehlt_nicht(self):
        """Strikt vor dem Zielspiel - wer am Spieltag wechselt, spielt nicht."""
        e = normalize_transfer(*transfer(1, "2025-08-01", zu=10))
        assert team_window_transfers([e], 10, "2025-08-01", 2025) == ([], [])

    def test_t44_duplikat_wird_entfernt(self, tmp_path):
        from src.features.transfer_events import load_transfer_events
        inhalt = {"meta": {}, "payload": [{
            "player": {"id": 1, "name": "X"},
            "transfers": [
                {"date": "2025-07-01", "type": "Transfer",
                 "teams": {"in": {"id": 10}, "out": {"id": 20}}},
                {"date": "2025-07-01", "type": "N/A",
                 "teams": {"in": {"id": 10}, "out": {"id": 20}}},
            ]}]}
        pfad = tmp_path / "apisports__transfers__team__10.json"
        pfad.write_text(json.dumps(inhalt), encoding="utf-8")
        events, diag = load_transfer_events(cache_dir=str(tmp_path))
        assert len(events) == 1
        assert diag["duplicates"] == 1

    def test_t45_unbekanntes_team_neutral(self):
        e = normalize_transfer(*transfer(1, "2025-07-01", zu=999, von=998),
                               known_team_ids={10, 20})
        assert e["mapped_to_team"] is False and e["mapped_from_team"] is False
        imp, qual = kader({1: ("Attacker", 0.9)})
        r = go5.transfer_impact([e], [], imp, qual, 0)
        assert r["attack_modifier"] == 0.0
        assert r["transfers_without_evidence"] == 1

    def test_t46_importance_beeinflusst_wirkung(self):
        e = normalize_transfer(*transfer(1, "2025-07-01", zu=10))
        gross_i, gross_q = kader({1: ("Attacker", 0.9)}, {1: 0.9})
        klein_i, klein_q = kader({1: ("Attacker", 0.1)}, {1: 0.9})
        gross = go5.transfer_impact([e], [], gross_i, gross_q, 0)
        klein = go5.transfer_impact([e], [], klein_i, klein_q, 0)
        assert abs(gross["net_attack_transfer_impact"]) > abs(klein["net_attack_transfer_impact"])

    def test_t47_position_bestimmt_wirkungsbereich(self):
        e = normalize_transfer(*transfer(1, "2025-07-01", zu=10))
        imp_a, qual_a = kader({1: ("Attacker", 0.9)}, {1: 0.9})
        imp_d, qual_d = kader({1: ("Defender", 0.9)}, {1: 0.9})
        angreifer = go5.transfer_impact([e], [], imp_a, qual_a, 0)
        verteidiger = go5.transfer_impact([e], [], imp_d, qual_d, 0)
        assert angreifer["net_attack_transfer_impact"] > 0
        assert angreifer["net_defence_transfer_impact"] == 0
        assert verteidiger["net_defence_transfer_impact"] > 0
        assert verteidiger["net_attack_transfer_impact"] == 0

    def test_t48_kein_transfer_neutral(self):
        imp, qual = kader({1: ("Attacker", 0.9)})
        r = go5.transfer_impact([], [], imp, qual, 0)
        assert r["attack_modifier"] == 0.0 and r["defence_modifier"] == 0.0

    def test_t48b_abgang_eines_schwachen_spielers_schadet_nicht(self):
        """Kein pauschales "Abgang ist schlecht"."""
        e = normalize_transfer(*transfer(1, "2025-07-01", zu=20, von=10))
        imp, qual = kader({1: ("Attacker", 0.9)}, {1: 0.1})
        r = go5.transfer_impact([], [e], imp, qual, 0)
        # Ein unterdurchschnittlicher Stammspieler geht - das staerkt.
        assert r["net_attack_transfer_impact"] > 0

    def test_t48c_leihe_ist_nicht_automatisch_schlecht(self):
        leihe = normalize_transfer(*transfer(1, "2025-07-01", zu=10, art="Loan"))
        fest = normalize_transfer(*transfer(1, "2025-07-01", zu=10, art="Transfer"))
        imp, qual = kader({1: ("Attacker", 0.9)}, {1: 0.9})
        a = go5.transfer_impact([leihe], [], imp, qual, 0)
        b = go5.transfer_impact([fest], [], imp, qual, 0)
        assert a["attack_modifier"] == b["attack_modifier"]

    def test_t49_ohne_beleg_keine_wirkung(self):
        e = normalize_transfer(*transfer(1, "2025-07-01", zu=10))
        r = go5.transfer_impact([e], [], {}, {}, 0)
        assert r["attack_modifier"] == 0.0
        assert r["number_of_usable_transfers"] == 0

    def test_t50_saisonzuordnung_am_juli_schnitt(self):
        assert season_of(parse_date("2025-06-30")) == 2024
        assert season_of(parse_date("2025-07-01")) == 2025

    def test_t51_index_liefert_dasselbe_wie_der_volle_lauf(self):
        events = [normalize_transfer(*transfer(i, "2025-07-01", zu=10, von=20))
                  for i in range(1, 6)]
        index = build_team_index(events)
        assert (team_window_transfers_indexed(index, 10, "2025-08-01", 2025)
                == team_window_transfers(events, 10, "2025-08-01", 2025))

    def test_t51b_ohne_datum_kein_ereignis(self):
        assert normalize_transfer({"id": 1}, {"date": None, "teams": {}}) is None

    def test_t51c_ablosesumme_wird_nicht_uebernommen(self):
        e = normalize_transfer(*transfer(1, "2025-07-01", art="€ 45M"))
        assert e["transfer_type"] == "permanent"
        assert "45" not in json.dumps(e)


# ---------------------------------------------------------------------------
# D  Decay
# ---------------------------------------------------------------------------

class TestD_Decay:

    def test_d52_n0_ist_maximal(self):
        assert go5.lambda_transfer(0) == 1.0

    def test_d53_n1_kleiner_gleich_n0(self):
        assert go5.lambda_transfer(1) <= go5.lambda_transfer(0)

    def test_d54_n5_kleiner(self):
        assert go5.lambda_transfer(5) < go5.lambda_transfer(1)

    def test_d55_n10_kleiner(self):
        assert go5.lambda_transfer(10) < go5.lambda_transfer(5)

    def test_d56_n20_kleiner(self):
        assert go5.lambda_transfer(20) < go5.lambda_transfer(10)

    def test_d57_n34_nahezu_neutral(self):
        assert go5.lambda_transfer(34) < 0.15

    def test_d58_monoton_fallend(self):
        werte = [go5.lambda_transfer(n) for n in range(0, 40)]
        assert all(a >= b for a, b in zip(werte, werte[1:]))

    def test_d59_keine_division_durch_null(self):
        assert go5.lambda_transfer(0, k=0) > 0
        assert go5.lambda_transfer(0, k=-5) > 0
        assert go5.lambda_transfer(0, k=None) == 1.0

    def test_d60_andere_saison_zaehlt_nicht_mit(self):
        from src.features.match_timeline import team_timeline
        eintraege = []
        for tag, saison in ((1, 2024), (2, 2024), (3, 2025)):
            eintraege.append({
                "match_id": f"m{tag}", "season": saison, "competition": "BL1",
                "kickoff": datetime(2025, 3, tag, 15, 0),
                "date": f"2025-03-0{tag}", "home_id": 1, "away_id": 2,
                "time_precision": "datetime", "played": True,
            })
        tl = team_timeline(eintraege, 1)
        assert go5.count_league_matches_before(tl, datetime(2025, 4, 1), 2025) == 1
        assert go5.count_league_matches_before(tl, datetime(2025, 4, 1), 2024) == 2

    def test_d60b_pokalspiele_zaehlen_nicht(self):
        from src.features.match_timeline import team_timeline
        eintraege = [{
            "match_id": f"m{i}", "season": 2025, "competition": comp,
            "kickoff": datetime(2025, 3, i + 1, 15, 0), "date": "2025-03-01",
            "home_id": 1, "away_id": 2, "time_precision": "datetime",
            "played": True,
        } for i, comp in enumerate(("BL1", "DFB", "CL", "BL1"))]
        tl = team_timeline(eintraege, 1)
        assert go5.count_league_matches_before(tl, datetime(2025, 4, 1), 2025) == 2

    def test_d61_fehlendes_n_sicherer_rueckfall(self):
        assert go5.lambda_transfer(None) == 1.0
        assert go5.lambda_transfer("unsinn") == 1.0

    def test_d61b_k_transfer_kleiner_als_in_season_blend(self):
        """
        Der Transfereffekt muss schneller verschwinden, als die laufende
        Saison dieselbe Veraenderung selbst abbildet.
        """
        from src.features.dynamic_weights import DEFAULT_K
        assert go5.CONSTANTS["K_TRANSFER"]["wert"] < DEFAULT_K

    def test_d61c_decay_daempft_die_wirkung(self):
        e = normalize_transfer(*transfer(1, "2025-07-01", zu=10))
        imp, qual = kader({1: ("Attacker", 0.9)}, {1: 0.95})
        frueh = go5.transfer_impact([e], [], imp, qual, 0)
        spaet = go5.transfer_impact([e], [], imp, qual, 30)
        assert abs(spaet["attack_modifier"]) < abs(frueh["attack_modifier"])


# ---------------------------------------------------------------------------
# K  Kombination
# ---------------------------------------------------------------------------

class TestK_Kombination:

    def teardown_method(self):
        for var in (go4.MODE_ENV_VAR, go5.MODE_ENV_VAR):
            os.environ.pop(var, None)
        go45_provider.clear_cache()

    def test_k62_getrennt_aktivierbar(self):
        os.environ[go4.MODE_ENV_VAR] = "active"
        os.environ[go5.MODE_ENV_VAR] = "shadow"
        assert go4.current_mode() == "active"
        assert go5.current_mode() == "shadow"

    def test_k63_voreinstellung_ist_shadow(self):
        os.environ.pop(go4.MODE_ENV_VAR, None)
        os.environ.pop(go5.MODE_ENV_VAR, None)
        assert go4.current_mode() == "shadow"
        assert go5.current_mode() == "shadow"
        assert go4.DEFAULT_MODE == "shadow" and go5.DEFAULT_MODE == "shadow"

    def test_k64_go5_active_aktiviert_go4_nicht(self):
        os.environ[go5.MODE_ENV_VAR] = "active"
        os.environ.pop(go4.MODE_ENV_VAR, None)
        assert go5.current_mode() == "active"
        assert go4.current_mode() == "shadow"

        zusammen = go45_provider.combine(
            {"attack_modifier": -0.02, "defence_modifier": -0.02},
            {"attack_modifier": 0.01, "defence_modifier": 0.0},
            go4_active=False, go5_active=True)
        assert zusammen["attack"] == 0.01     # nur GO 5 traegt bei

    def test_k65_gleicher_spieler_nicht_doppelt(self):
        e = normalize_transfer(*transfer(1, "2025-07-01", zu=10))
        imp, qual = kader({1: ("Attacker", 0.9)}, {1: 0.9})
        ohne = go5.transfer_impact([e], [], imp, qual, 0)
        mit = go5.transfer_impact([e], [], imp, qual, 0, excluded_player_ids=[1])
        assert ohne["attack_modifier"] != 0.0
        assert mit["attack_modifier"] == 0.0
        assert mit["transfers_excluded_as_absent"] == 1

    def test_k66_kombinierter_clamp(self):
        zusammen = go45_provider.combine(
            {"attack_modifier": -0.05, "defence_modifier": -0.05},
            {"attack_modifier": -0.03, "defence_modifier": -0.03},
            go4_active=True, go5_active=True)
        grenze = go4.CONSTANTS["MAX_COMBINED_GO4_GO5"]["wert"]
        assert abs(zusammen["attack"]) <= grenze + 1e-9
        assert zusammen["clamp_applied"] is True

    def test_k66b_kombinierte_grenze_kleiner_als_summe(self):
        einzeln = (go4.CONSTANTS["MAX_TOTAL_EFFECT"]["wert"]
                   + go5.CONSTANTS["MAX_SINGLE_EFFECT"]["wert"])
        assert go4.CONSTANTS["MAX_COMBINED_GO4_GO5"]["wert"] < einzeln

    def test_k67_go3_bleibt_unberuehrt(self):
        """GO 4 und GO 5 aendern die GO-3-Voreinstellung nicht."""
        from src.features import go3
        os.environ[go4.MODE_ENV_VAR] = "active"
        os.environ[go5.MODE_ENV_VAR] = "active"
        os.environ.pop(go3.MODE_ENV_VAR, None)
        assert go3.current_mode() == "shadow"

    def test_k68_unsinniger_modus_faellt_auf_shadow(self):
        os.environ[go4.MODE_ENV_VAR] = "vollgas"
        os.environ[go5.MODE_ENV_VAR] = "sofort"
        assert go4.current_mode() == "shadow"
        assert go5.current_mode() == "shadow"

    def test_k69_off_ist_exakt_neutral(self):
        zusammen = go45_provider.combine(
            {"attack_modifier": -0.02, "defence_modifier": -0.02},
            {"attack_modifier": 0.01, "defence_modifier": 0.01},
            go4_active=False, go5_active=False)
        assert zusammen["attack"] == 0.0 and zusammen["defence"] == 0.0

    def test_k70_apply_veraendert_das_original_nicht(self):
        profil = {"attack_home": 1.4, "attack_away": 1.1,
                  "defence_home": 0.8, "defence_away": 1.0}
        kopie = dict(profil)
        go4.apply_modifier(profil, -0.02, -0.02)
        go5.apply_modifier(profil, -0.02, -0.02)
        assert profil == kopie

    def test_k71_schlechtere_abwehr_erhoeht_defence_werte(self):
        profil = {"attack_home": 1.0, "attack_away": 1.0,
                  "defence_home": 1.0, "defence_away": 1.0}
        neu = go4.apply_modifier(profil, -0.02, -0.02)
        assert neu["attack_home"] < 1.0
        assert neu["defence_home"] > 1.0

    def test_k72_konstanten_sind_dokumentiert(self):
        for tabelle in (go4.CONSTANTS, go5.CONSTANTS):
            for name, eintrag in tabelle.items():
                assert eintrag["zweck"], name
                assert eintrag["begruendung"], name
                unten, oben = eintrag["bereich"]
                assert unten <= eintrag["wert"] <= oben, name

    def test_k73_berichte_enthalten_keine_pfade(self):
        text = json.dumps([go4.constants_report(), go5.constants_report()]).lower()
        for verboten in ("c:" + chr(92), "/root", "api_key", "secret", ".env"):
            assert verboten not in text


# ---------------------------------------------------------------------------
# S  Snapshots und Sicherheit
# ---------------------------------------------------------------------------

class TestS_Snapshots:

    def test_s74_archiv_schreibt_atomar(self, tmp_path, monkeypatch):
        import src.data.snapshot_archive as archiv
        monkeypatch.setattr(archiv, "ARCHIVE_DIR", str(tmp_path))
        pfad = archiv.archive_snapshot(
            kind="availability", key="bl1_2025",
            payload={"absences": {"1": {"status": "out"}}}, source="test")
        assert os.path.exists(pfad)
        assert not [p for p in os.listdir(tmp_path / "availability")
                    if p.endswith(".tmp")]

    def test_s75_leerer_stand_wird_nicht_archiviert(self, monkeypatch):
        """Ein leerer Ausfallstand darf keinen guten verdraengen."""
        import src.features.squad_availability as sa

        monkeypatch.setattr("src.api.apisports_api.get_injuries",
                            lambda *a, **k: [])
        monkeypatch.setattr("src.api.apisports_api.resolve_season",
                            lambda s=None: 2025)
        ergebnis = sa.capture_availability_snapshot("bl1", 2025)
        assert ergebnis["entries"] == 0
        assert ergebnis["archived_to"] is None

    def test_s76_historische_staende_bleiben_erhalten(self, tmp_path, monkeypatch):
        import src.data.snapshot_archive as archiv
        monkeypatch.setattr(archiv, "ARCHIVE_DIR", str(tmp_path))
        erst = archiv.archive_snapshot(kind="availability", key="bl1_2025",
                                       payload={"n": 1}, source="test")
        zweit = archiv.archive_snapshot(kind="availability", key="bl1_2025",
                                        payload={"n": 2}, source="test")
        assert erst != zweit
        assert os.path.exists(erst) and os.path.exists(zweit)

    def test_s77_kein_snapshot_ergibt_none(self):
        from src.features.squad_availability import load_availability_snapshot
        ausfaelle, zeitmarke = load_availability_snapshot("bl1", 1999, "1999-01-01")
        assert ausfaelle is None and zeitmarke is None

    def test_s78_keine_secrets_in_den_fixtures(self):
        text = json.dumps([spieler(1), transfer(1, "2025-01-01")[1]]).lower()
        for verboten in ("api_key", "secret", "token", "passwo"):
            assert verboten not in text

    def test_s79_api_block_ohne_stacktrace(self):
        block = go45_provider.api_metadata(None)
        text = json.dumps(block).lower()
        assert "traceback" not in text
        assert block["go4"]["available"] is False
        assert block["go5"]["available"] is False

    def test_s80_kaputter_snapshot_erzeugt_keinen_fehler(self):
        block = go45_provider.api_metadata({"go4_mode": "shadow"})
        assert block["go4"]["reason"] == "incomplete_snapshot"

    def test_s80b_safe_snapshot_faengt_ausfaelle(self):
        assert go45_provider.safe_fixture_snapshot(None, None, None) is None


# ---------------------------------------------------------------------------
# R  Backtest
# ---------------------------------------------------------------------------

class TestR_Backtest:

    def test_r81_alle_varianten_bewerten_dieselben_spiele(self):
        from src.features.go45_backtest import run_backtest
        r = run_backtest("bl1", 2025)
        assert r is not None
        anzahlen = {v["n"] for v in r["variants"].values() if v}
        assert len(anzahlen) == 1

    def test_r82_backtest_nutzt_den_vorsaison_pool(self):
        """
        Poolstatistiken sind Saisonsummen. Fuer Spiele der Saison S darf
        nur der Pool S-1 herangezogen werden.
        """
        from src.features.go45_backtest import run_backtest
        r = run_backtest("bl1", 2025)
        assert r["player_pool_season"] == 2024

    def test_r83_ohne_ausfalldaten_ist_go4_exakt_neutral(self):
        """
        Die zentrale historische Aussage: Ohne archivierte Ausfaelle
        veraendert GO 4 nichts. Keine heutigen Verletzungen in alten
        Spielen.
        """
        from src.features.go45_backtest import run_backtest
        r = run_backtest("bl1", 2025)
        basis = r["variants"]["baseline"]
        go4_variante = r["variants"]["go4_availability"]
        assert go4_variante["log_loss"] == basis["log_loss"]
        assert go4_variante["avg_probability_change"] == 0.0
        assert r["squad_membership_known"] is False

    def test_r84_ablationen_sind_getrennt(self):
        from src.features.go45_backtest import VARIANTS
        assert VARIANTS["baseline"] == {}
        assert VARIANTS["go4_availability"].get("go4") is True
        assert VARIANTS["go4_availability"].get("go5") is None
        assert VARIANTS["go5_k4"].get("go5") is True
        assert VARIANTS["go5_k4"].get("go4") is None

    def test_r85_lambda_sensitivitaet_ist_reproduzierbar(self):
        a = [go5.lambda_transfer(n, k=k) for k in (2, 3, 4, 6, 8) for n in range(10)]
        b = [go5.lambda_transfer(n, k=k) for k in (2, 3, 4, 6, 8) for n in range(10)]
        assert a == b

    def test_r86_backtest_meldet_ausgeschlossene_spiele(self):
        from src.features.go45_backtest import run_backtest
        r = run_backtest("bl1", 2025)
        assert "skipped_warmup" in r
        assert "matches_without_team_mapping" in r
        assert r["coverage"]["teams_mapped"] > 0

    def test_r87_gate_entscheidung_ist_deterministisch(self):
        from src.features.go45_backtest import run_backtest
        a = run_backtest("bl1", 2025)
        b = run_backtest("bl1", 2025)
        assert a["variants"]["go5_k4"] == b["variants"]["go5_k4"]

    def test_r88_negatives_gate_aktiviert_nichts(self):
        """
        Der Backtest hat fuer keines der beiden Features eine belastbare
        Verbesserung gezeigt. Beide Voreinstellungen muessen deshalb
        shadow sein - dieser Test schlaegt fehl, sobald jemand das
        aendert, ohne den Backtest zu wiederholen.
        """
        os.environ.pop(go4.MODE_ENV_VAR, None)
        os.environ.pop(go5.MODE_ENV_VAR, None)
        assert go4.DEFAULT_MODE == "shadow"
        assert go5.DEFAULT_MODE == "shadow"
        assert go4.current_mode() == "shadow"
        assert go5.current_mode() == "shadow"
