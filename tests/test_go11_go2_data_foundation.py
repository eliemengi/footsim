"""
GO 1.1 + GO 2: frueher Saisonvergleich, Snapshot-Gueltigkeit,
nationale Pokale und produktive CL-Historie.

WELCHE FEHLER DIESE TESTS FESTHALTEN
------------------------------------
GO 1.1
  a) is_snapshot_complete() prueste nur, ob alle fuenf Ligen BETEILIGT
     waren - nicht, ob dabei Daten herauskamen. So galt
     percentiles_2026.json mit 465 Bytes und NULL Positionsgruppen als
     vollstaendig.
  b) _player_percentiles() sperrte jeden Spieler unter 450 Minuten
     komplett aus. Am ersten Spieltag war damit niemand vergleichbar.

GO 2
  c) data/historical/CL_*.json lag ungenutzt herum, waehrend jeder
     CL-Request die API befragte - auch fuer laengst abgeschlossene
     Saisons.
  d) Es gab keinerlei nationale Pokaldaten, obwohl sie die Grundlage
     jeder Belastungsrechnung sind.

Kein Test loest einen echten Provider-Request aus.
"""

import json
import os

import pytest

from src.data import percentile_engine as pe
from src.data import domestic_cup_loader as cups


# ===========================================================================
# GO 1.1 - Snapshot-Gueltigkeit
# ===========================================================================

def _snapshot(distributions, season=2026, leagues=None):
    return {
        "season": season,
        "leagues": list(leagues or pe.REQUIRED_LEAGUES),
        "min_minutes": pe.DEFAULT_MIN_MINUTES,
        "distributions": distributions,
        "distributions_by_scope": {},
    }


def _gruppe(metriken=2):
    # Echte Snapshot-Struktur: je Metrik {"n": Stichprobe, "q": Quantile}.
    return {"player_count": 100,
            "metrics": {f"m{i}": {"n": 100, "q": [float(i)] * 101}
                        for i in range(metriken)}}


class TestSnapshotGueltigkeit:

    def test_leerer_snapshot_ist_unbrauchbar(self):
        assert pe.is_snapshot_usable(_snapshot({})) is False

    def test_snapshot_ohne_metriken_ist_unbrauchbar(self):
        leer = {"Attacker": {"player_count": 0, "metrics": {}},
                "Defender": {"player_count": 0, "metrics": {"m0": {"n": 0, "q": []}}}}
        assert pe.is_snapshot_usable(_snapshot(leer)) is False

    def test_eine_gefuellte_gruppe_genuegt(self):
        """
        Die Schwelle folgt dem bestehenden Vertrag: tests/test_player_pool.py
        baut gueltige Snapshots mit genau einer Positionsgruppe. Strenger
        zu sein wuerde gueltige Teilpools verwerfen - der leere Fall wird
        auch so zuverlaessig getrennt.
        """
        assert pe.is_snapshot_usable(_snapshot({"Attacker": _gruppe()})) is True

    def test_zwei_gefuellte_gruppen_sind_brauchbar(self):
        gut = {"Attacker": _gruppe(), "Defender": _gruppe()}
        assert pe.is_snapshot_usable(_snapshot(gut)) is True

    def test_vollstaendig_setzt_brauchbarkeit_voraus(self):
        """
        Der Kernfehler: alle fuenf Ligen beteiligt, aber nichts drin -
        das darf nicht mehr als vollstaendig gelten.
        """
        assert pe.is_snapshot_complete(_snapshot({})) is False

    def test_echter_leerer_2026_snapshot_wird_erkannt(self):
        """Gegen die tatsaechlich im Repo liegende Datei."""
        s26 = pe.load_snapshot(2026)
        if s26 is None:
            pytest.skip("percentiles_2026.json liegt lokal nicht vor")
        assert pe.is_snapshot_usable(s26) is False
        assert pe.is_snapshot_complete(s26) is False

    def test_echter_2025_snapshot_bleibt_brauchbar(self):
        s25 = pe.load_snapshot(2025)
        if s25 is None:
            pytest.skip("percentiles_2025.json liegt lokal nicht vor")
        assert pe.is_snapshot_usable(s25) is True
        assert pe.is_snapshot_complete(s25) is True

    def test_referenz_faellt_auf_letzte_gueltige_saison_zurueck(self):
        snapshot, referenz = pe.load_usable_snapshot(2026)
        if snapshot is None:
            pytest.skip("keine lokalen Snapshots vorhanden")
        assert referenz == 2025, f"Referenzsaison {referenz} statt 2025"
        assert pe.is_snapshot_usable(snapshot)

    def test_guter_snapshot_wird_nicht_durch_leeren_ersetzt(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pe, "PERCENTILE_DIR", str(tmp_path))

        gut = _snapshot({"Attacker": _gruppe(), "Defender": _gruppe()}, season=2099)
        pe.save_snapshot(gut, archive=False)

        leer = _snapshot({}, season=2099)
        pe.save_snapshot(leer, archive=False)

        wieder = pe.load_snapshot(2099)
        assert pe.is_snapshot_usable(wieder), (
            "Ein leeres Ergebnis hat den guten Stand ueberschrieben"
        )


# ===========================================================================
# GO 1.1 - Stabilisierung
# ===========================================================================

class TestStabilisierung:

    def test_gewicht_steigt_monoton_mit_den_minuten(self):
        minuten = [0, 1, 55, 90, 450, 900, 1800, 3000]
        gewichte = [pe.current_weight(m) for m in minuten]
        assert gewichte == sorted(gewichte)
        assert all(0.0 <= g <= 1.0 for g in gewichte)

    def test_null_minuten_ergibt_nur_referenz(self):
        assert pe.current_weight(0) == 0.0
        assert pe.stabilize(1.64, 0.45, 0) == pytest.approx(0.45)

    def test_bei_k_minuten_wiegen_beide_gleich(self):
        assert pe.current_weight(pe.SHRINKAGE_K) == pytest.approx(0.5)
        assert pe.stabilize(2.0, 1.0, pe.SHRINKAGE_K) == pytest.approx(1.5)

    def test_stabilisierter_wert_ist_weniger_extrem(self):
        """
        Ein Tor aus 55 Minuten ergibt roh 1.64 pro 90 - besser als jeder
        Weltklassestuermer ueber eine Saison. Das ist keine Leistung,
        sondern eine zu kleine Stichprobe.
        """
        roh, referenz = 1.64, 0.45
        stabil = pe.stabilize(roh, referenz, 55)
        assert referenz < stabil < roh
        assert stabil < 0.8, f"{stabil} ist immer noch unrealistisch hoch"

    def test_viele_minuten_lassen_die_aktuelle_saison_dominieren(self):
        roh, referenz = 1.20, 0.40
        stabil = pe.stabilize(roh, referenz, 3000)
        assert stabil > 0.85 * roh

    def test_ohne_referenz_bleibt_der_wert_unveraendert(self):
        assert pe.stabilize(1.5, None, 100) == 1.5

    def test_ohne_aktuellen_wert_gilt_die_referenz(self):
        assert pe.stabilize(None, 0.7, 100) == 0.7

    def test_ergebnis_ist_deterministisch(self):
        a = [pe.stabilize(1.3, 0.5, m) for m in (10, 100, 1000)]
        b = [pe.stabilize(1.3, 0.5, m) for m in (10, 100, 1000)]
        assert a == b

    def test_positionsmedian_kommt_aus_der_richtigen_gruppe(self):
        snapshot = _snapshot({
            "Attacker": {"player_count": 50, "metrics": {
                "goals_per90": {"n": 50, "q": [0.1] * 50 + [0.9] * 51}}},
            "Defender": {"player_count": 50, "metrics": {
                "goals_per90": {"n": 50, "q": [0.0] * 101}}},
        })
        stuermer = pe.position_median(snapshot, "Attacker", "goals_per90")
        verteidiger = pe.position_median(snapshot, "Defender", "goals_per90")

        assert stuermer == 0.9
        assert verteidiger == 0.0
        assert stuermer > verteidiger, "Positionen brauchen eigene Referenzen"

    def test_unbekannte_metrik_hat_keinen_median(self):
        assert pe.position_median(_snapshot({"Attacker": _gruppe()}),
                                  "Attacker", "gibtsnicht") is None


# ===========================================================================
# GO 1.1 - Vergleich ab der ersten Minute
# ===========================================================================

class TestFrueherVergleich:

    @pytest.fixture
    def snapshot(self):
        s = pe.load_snapshot(2025)
        if s is None:
            pytest.skip("percentiles_2025.json liegt lokal nicht vor")
        return s

    def test_spieler_mit_55_minuten_bekommt_perzentile(self, snapshot):
        from src.data.player_compare_loader import _player_percentiles

        profil = {"position": "Attacker", "minutes": 55, "scope": "club_all"}
        werte = {"goals_per90": 1.64}

        perzentile, hinweis = _player_percentiles(profil, werte, snapshot)

        assert hinweis == "provisional"
        assert any(v is not None for v in perzentile.values()), (
            "Unter 450 Minuten gab es frueher gar kein Perzentil"
        )

    def test_null_minuten_erfindet_keine_leistung(self, snapshot):
        from src.data.player_compare_loader import _player_percentiles

        profil = {"position": "Attacker", "minutes": 0, "scope": "club_all"}
        perzentile, hinweis = _player_percentiles(profil, {"goals_per90": 0.0}, snapshot)

        assert hinweis == "no_minutes"
        assert all(v is None for v in perzentile.values())

    def test_ab_der_schwelle_gilt_der_wert_nicht_mehr_als_vorlaeufig(self, snapshot):
        from src.data.player_compare_loader import _player_percentiles

        profil = {"position": "Attacker", "minutes": 900, "scope": "club_all"}
        _, hinweis = _player_percentiles(profil, {"goals_per90": 0.6}, snapshot)
        assert hinweis is None

    def test_vorjahresprofil_wird_der_positionsreferenz_vorgezogen(self, snapshot):
        from src.data.player_compare_loader import _player_percentiles

        profil = {"position": "Attacker", "minutes": 90, "scope": "club_all"}
        werte = {"goals_per90": 1.0}

        ohne, _ = _player_percentiles(profil, werte, snapshot)
        mit, _ = _player_percentiles(profil, werte, snapshot,
                                     baseline_values={"goals_per90": 5.0})

        gemeinsam = [k for k in ohne if ohne[k] is not None and mit.get(k) is not None]
        if not gemeinsam:
            pytest.skip("goals_per90 ist in diesem Snapshot nicht enthalten")

        assert mit["goals_per90"] > ohne["goals_per90"], (
            "Ein hoher individueller Basiswert muss das Perzentil heben"
        )

    def test_rohwerte_bleiben_unberuehrt(self, snapshot):
        from src.data.player_compare_loader import _player_percentiles

        werte = {"goals_per90": 1.64, "assists_per90": 0.9}
        original = dict(werte)

        _player_percentiles({"position": "Attacker", "minutes": 55,
                             "scope": "club_all"}, werte, snapshot)

        assert werte == original, "Die uebergebenen Rohwerte wurden veraendert"


# ===========================================================================
# GO 2 - Nationale Pokale
# ===========================================================================

class TestNationalePokale:

    def test_fuenf_hauptpokale_mit_eindeutiger_id(self):
        assert set(cups.DOMESTIC_CUPS) == {"dfb", "fac", "cdr", "cit", "cdf"}

        ids = [c["apisports_id"] for c in cups.DOMESTIC_CUPS.values()]
        assert len(set(ids)) == 5, "IDs muessen eindeutig sein"

        laender = {c["country"] for c in cups.DOMESTIC_CUPS.values()}
        assert laender == {"Germany", "England", "Spain", "Italy", "France"}

    def test_keine_supercups_und_keine_nebenwettbewerbe(self):
        """
        Verifiziert am 2026-08-22: 715 (DFB Junioren), 947 (DFB Women),
        704/891/892/1171 (Coppa-Varianten) sind KEINE Hauptpokale.
        Supercups (GSC/USC/FACS) ebenfalls nicht.
        """
        ids = {c["apisports_id"] for c in cups.DOMESTIC_CUPS.values()}
        for verboten in (715, 947, 704, 891, 892, 1171, 528, 529, 531):
            assert verboten not in ids, f"Nebenwettbewerb {verboten} als Hauptpokal"

        namen = " ".join(c["name"].lower() for c in cups.DOMESTIC_CUPS.values())
        for wort in ("super", "junioren", "women", "primavera", "serie c"):
            assert wort not in namen

    def test_jeder_pokal_haengt_an_einer_topliga(self):
        keys = {c["league_key"] for c in cups.DOMESTIC_CUPS.values()}
        assert keys == {"bl1", "pl", "pd", "sa", "fl1"}

    def test_normalisierung_ins_gemeinsame_schema(self):
        roh = {
            "fixture": {"id": 1, "date": "2025-10-29T18:00:00+00:00",
                        "status": {"short": "AET"}},
            "league": {"round": "2nd Round"},
            "teams": {"home": {"id": 5, "name": "Bayern"},
                      "away": {"id": 9, "name": "Koeln"}},
            "goals": {"home": 2, "away": 2},
            "score": {"penalty": {"home": 5, "away": 4}},
        }
        m = cups._normalize_match(roh)

        assert m["match_id"] == 1
        assert m["date"] == "2025-10-29"
        assert m["kickoff"].startswith("2025-10-29T18:00")
        assert m["stage"] == "2nd Round"
        assert m["home_id"] == 5 and m["away_id"] == 9
        assert m["home_goals"] == 2 and m["away_goals"] == 2
        # Elfmeter getrennt: sie entscheiden die Runde, nicht das Ergebnis.
        assert m["penalty_home"] == 5 and m["penalty_away"] == 4

    def test_unfertige_spiele_gelten_nicht_als_ergebnis(self):
        assert cups.is_finished({"home_goals": 1, "away_goals": 0, "status": "FT"})
        assert cups.is_finished({"home_goals": 1, "away_goals": 1, "status": "PEN"})
        assert not cups.is_finished({"home_goals": None, "away_goals": None, "status": "NS"})
        assert not cups.is_finished({"home_goals": 1, "away_goals": 0, "status": "PST"})
        assert not cups.is_finished({"home_goals": 1, "away_goals": 0, "status": None})

    def test_leere_antwort_ueberschreibt_keine_gute_datei(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cups, "HISTORICAL_DIR", str(tmp_path))

        gut = {"meta": {"code": "DFB", "season": 2099},
               "teams": {}, "matches": [{"match_id": 1}]}
        pfad, geschrieben = cups.save_cup_season(gut)
        assert geschrieben

        leer = {"meta": {"code": "DFB", "season": 2099}, "teams": {}, "matches": []}
        _, geschrieben2 = cups.save_cup_season(leer)

        assert geschrieben2 is False
        with open(pfad, encoding="utf-8") as fh:
            assert json.load(fh)["matches"], "gute Datei wurde geleert"

    def test_schreiben_ist_atomar(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cups, "HISTORICAL_DIR", str(tmp_path))
        payload = {"meta": {"code": "CIT", "season": 2099},
                   "teams": {}, "matches": [{"match_id": 7}]}
        pfad, _ = cups.save_cup_season(payload)

        assert os.path.exists(pfad)
        assert not os.path.exists(pfad + ".tmp"), "Temporaerdatei blieb liegen"

    def test_payload_ohne_schema_wird_abgelehnt(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cups, "HISTORICAL_DIR", str(tmp_path))
        with pytest.raises(ValueError):
            cups.save_cup_season({"meta": {}, "matches": []})

    def test_gespeicherte_dateien_tragen_volle_provenienz(self):
        payload = cups.load_cup_season("dfb", 2025)
        if payload is None:
            pytest.skip("DFB_2025.json liegt lokal nicht vor")

        meta = payload["meta"]
        for feld in ("schema_version", "code", "name", "country", "season",
                     "source", "provider_competition_id", "fetched_at",
                     "matches", "matches_finished", "rounds", "coverage"):
            assert feld in meta, feld

        assert meta["source"] == "api-football.com"
        assert meta["provider_competition_id"] == 81

    def test_runden_bleiben_erhalten(self):
        matches = cups.load_cup_matches("dfb", 2025)
        if not matches:
            pytest.skip("keine DFB-Daten lokal")
        runden = {m["stage"] for m in matches}
        assert len(runden) >= 5, f"nur {len(runden)} Runden - Stage ging verloren"

    def test_coverage_report_zeigt_fehlendes_ehrlich(self):
        report = cups.coverage_report()
        assert len(report) == 5
        for zeile in report:
            assert "seasons" in zeile
            assert zeile["provider"] == "api-football.com"


# ===========================================================================
# GO 2 - Produktive CL-Historie
# ===========================================================================

class TestClHistorie:

    def test_abgeschlossene_saison_kommt_aus_der_lokalen_datei(self, monkeypatch):
        from src.features import strength_provider as sp

        def darf_nicht(*args, **kwargs):
            raise AssertionError("Live-API trotz vorhandener lokaler Historie")

        monkeypatch.setattr(sp, "get_all_matches", darf_nicht)

        result = sp.get_cl_team_strengths(season=2025)
        prov = result["provenance"]

        assert prov["cl_source"] == "local_history"
        assert prov["source"].startswith("local:")
        assert prov["cl_source_detail"]["file"] == "CL_2025.json"
        assert prov["sample_size"] > 100
        assert result["cl_current_by_id"], "keine CL-Profile erzeugt"

    def test_live_fallback_bei_fehlender_datei(self, monkeypatch):
        from src.features import strength_provider as sp
        from src.data import historical_loader

        monkeypatch.setattr(historical_loader, "load_cl_season", lambda s: None)
        monkeypatch.setattr(sp, "get_all_matches",
                            lambda code, season=None, only_finished=True: [])

        result = sp.get_cl_team_strengths(season=2025)
        assert result["provenance"]["cl_source"] in ("live_api", "none")

    def test_leere_lokale_datei_blockiert_den_live_pfad_nicht(self, monkeypatch):
        from src.features import strength_provider as sp
        from src.data import historical_loader

        monkeypatch.setattr(historical_loader, "load_cl_season",
                            lambda s: {"meta": {}, "matches": []})
        gerufen = {}

        def fake_live(code, season=None, only_finished=True):
            gerufen["ja"] = True
            return []

        monkeypatch.setattr(sp, "get_all_matches", fake_live)
        sp.get_cl_team_strengths(season=2025)

        assert gerufen.get("ja"), "leere Datei haette den Live-Fallback ausloesen muessen"

    def test_gleiche_matches_ergeben_gleiche_staerken(self, monkeypatch):
        """
        GO 2 wechselt die Datenquelle, nicht das Modell. Bei identischem
        Matchdatensatz muessen lokaler und Live-Pfad dasselbe liefern.
        """
        from src.features import strength_provider as sp
        from src.data import historical_loader

        lokal = sp.get_cl_team_strengths(season=2025)

        matches = (historical_loader.load_cl_season(2025) or {}).get("matches") or []
        if not matches:
            pytest.skip("keine lokale CL-Historie")

        monkeypatch.setattr(historical_loader, "load_cl_season", lambda s: None)
        monkeypatch.setattr(sp, "get_all_matches",
                            lambda code, season=None, only_finished=True: matches)

        live = sp.get_cl_team_strengths(season=2025)

        assert lokal["cl_current_by_id"] == live["cl_current_by_id"]
        assert lokal["league_avg"] == live["league_avg"]
