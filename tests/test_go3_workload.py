"""
Tests fuer GO 3: Zeitleiste, Belastung, Korrektur, Shadow-Modus, Backtest.

Gliederung
----------
    A  Zeitleiste und Deduplizierung
    B  Team-Crosswalk
    C  Belastungsmerkmale
    D  Verdichtungsstufen
    E  Datenqualitaet und Neutralitaet
    F  Korrektur, Clamping, Konstanten
    G  Snapshot, Cache, Shadow-Modus
    H  Backtest-Kennzahlen

Die Tests arbeiten mit gebauten Zeitleisten statt mit Echtdaten, wo es
um Regeln geht - sonst wuerde ein Test fehlschlagen, sobald eine
Historiedatei ergaenzt wird. Wo Echtdaten noetig sind, wird das
ausdruecklich benannt.
"""

import os
from datetime import datetime, timedelta

import pytest

from src.features import go3, go3_provider, match_timeline, workload
from src.features.go3 import (
    CONSTANTS, apply_modifier, compute_modifier, constants_report, current_mode)
from src.features.go3_backtest import (
    VARIANTS, _brier, _log_loss, _rps, outcome_probabilities)
from src.features.match_timeline import (
    build_timeline, coverage, matches_before, team_timeline)
from src.features.team_crosswalk import _normalize, build_crosswalk
from src.features.workload import (
    combined_quality, quality_weight, schedule_strength, workload_features)


BASIS = datetime(2025, 9, 1, 15, 0)


def spiel(tage, heim=1, gast=2, wettbewerb="BL1", stunde=None, praezise=True):
    """Ein Zeitleisteneintrag mit Abstand in Tagen zur Basis."""
    zeitpunkt = BASIS + timedelta(days=tage)
    if stunde is not None:
        zeitpunkt = zeitpunkt.replace(hour=stunde)
    return {
        "match_id": f"{wettbewerb}-{tage}-{heim}-{gast}",
        "season": 2025,
        "competition": wettbewerb,
        "competition_name": wettbewerb,
        "kickoff": zeitpunkt,
        "time_precision": "datetime" if praezise else "date",
        "date": zeitpunkt.date().isoformat(),
        "home_id": heim,
        "away_id": gast,
        "home_team": f"Team {heim}",
        "away_team": f"Team {gast}",
        "status": "FINISHED",
        "played": True,
        "home_goals": 1,
        "away_goals": 0,
        "source": "test",
        "data_quality": "complete",
    }


def zeitleiste(*eintraege):
    """Team-1-Sicht auf die uebergebenen Spiele."""
    return team_timeline(list(eintraege), 1)


# ---------------------------------------------------------------------------
# A  Zeitleiste
# ---------------------------------------------------------------------------

class TestA_Zeitleiste:

    def test_a1_matches_before_ist_strikt(self):
        """Ein Spiel zur Cutoff-Minute zaehlt NICHT als vorheriges Spiel."""
        tl = zeitleiste(spiel(-3), spiel(0))
        vorher = matches_before(tl, BASIS)
        assert len(vorher) == 1
        assert vorher[0]["kickoff"] < BASIS

    def test_a2_ohne_cutoff_keine_spiele(self):
        """Ohne Stichtag gibt es keine 'vorherigen' Spiele - nicht alle."""
        assert matches_before(zeitleiste(spiel(-3)), None) == []

    def test_a3_team_timeline_setzt_heim_und_gegner(self):
        tl = team_timeline([spiel(-3, heim=1, gast=2), spiel(-1, heim=2, gast=1)], 1)
        assert tl[0]["is_home"] is True and tl[0]["opponent_id"] == 2
        assert tl[1]["is_home"] is False and tl[1]["opponent_id"] == 2

    def test_a4_team_timeline_ignoriert_fremde_spiele(self):
        assert team_timeline([spiel(-3, heim=7, gast=8)], 1) == []

    def test_a5_chronologisch_sortiert(self):
        tl = team_timeline([spiel(-1), spiel(-5), spiel(-3)], 1)
        zeiten = [e["kickoff"] for e in tl]
        assert zeiten == sorted(zeiten)

    def test_a6_coverage_zaehlt_je_wettbewerb(self):
        c = coverage([spiel(-1), spiel(-2, wettbewerb="CL"), spiel(-3, wettbewerb="DFB")])
        assert c["matches_by_competition"] == {"BL1": 1, "CL": 1, "DFB": 1}
        assert c["has_leagues"] and c["has_champions_league"] and c["has_domestic_cups"]

    def test_a7_coverage_meldet_zeitgenauigkeit(self):
        c = coverage([spiel(-1, praezise=True), spiel(-2, praezise=False)])
        assert c["time_precision"] == {"datetime": 1, "date": 1}

    def test_a8_echte_zeitleiste_dedupliziert(self):
        """Echtdaten: dieselbe ID darf je Wettbewerb nur einmal vorkommen."""
        eintraege, _ = build_timeline([2025])
        schluessel = [(e["competition"], e["season"], e["match_id"]) for e in eintraege]
        assert len(schluessel) == len(set(schluessel))

    def test_a9_echte_zeitleiste_mischt_keine_saisons(self):
        eintraege, _ = build_timeline([2024])
        assert {e["season"] for e in eintraege} == {2024}

    def test_a10_echte_zeitleiste_nur_ausgetragene_spiele(self):
        eintraege, _ = build_timeline([2025])
        assert all(e["played"] for e in eintraege)
        assert all(e["home_goals"] is not None for e in eintraege)

    def test_a11_echte_zeitleiste_enthaelt_pokale(self):
        eintraege, _ = build_timeline([2025])
        wettbewerbe = {e["competition"] for e in eintraege}
        assert {"DFB", "FAC", "CDR", "CIT", "CDF"} <= wettbewerbe
        assert "CL" in wettbewerbe

    def test_a12_kickoff_ist_zeitzonenfrei(self):
        eintraege, _ = build_timeline([2025])
        assert all(e["kickoff"].tzinfo is None for e in eintraege)


# ---------------------------------------------------------------------------
# B  Crosswalk
# ---------------------------------------------------------------------------

class TestB_Crosswalk:

    def test_b1_normalisierung_faltet_akzente(self):
        assert _normalize("Atlético") == _normalize("Atletico")

    def test_b2_normalisierung_entfernt_rechtsform(self):
        assert _normalize("FC Bayern München") == _normalize("Bayern Munchen")

    def test_b3_leerer_name_ist_leer(self):
        assert _normalize(None) == "" and _normalize("") == ""

    def test_b4_unbekannte_liga_ordnet_nichts_zu(self):
        r = build_crosswalk("gibtsnicht", 2025, {1: "Bayern"})
        assert r["mapping"] == {} and r["mapped_count"] == 0

    def test_b5_leere_eingabe_ist_kein_fehler(self):
        r = build_crosswalk("bl1", 2025, {})
        assert r["mapping"] == {} and r["unmapped"] == []

    def test_b6_echte_ligen_ohne_mehrdeutigkeit(self):
        """Echtdaten: kein Verein darf falsch zusammengefuehrt werden."""
        from src.data.domestic_cup_loader import DOMESTIC_CUPS, load_cup_season
        for cup_key, cfg in DOMESTIC_CUPS.items():
            payload = load_cup_season(cup_key, 2025)
            if not payload:
                continue
            teams = {int(k): (v or {}).get("name")
                     for k, v in (payload.get("teams") or {}).items()}
            r = build_crosswalk(cfg["league_key"], 2025, teams)
            assert r["ambiguous"] == [], f"{cup_key}: {r['ambiguous']}"
            # Ein gemeldeter Konflikt ist KEIN Fehler, sondern die
            # gewollte Reaktion: der zweite Anwaerter wird abgelehnt
            # statt den ersten zu ueberschreiben. Gefordert ist, dass
            # die Zuordnung eindeutig BLEIBT.
            for eintrag in r["duplicates"]:
                abgelehnt = eintrag["apisports_ids"][1]
                assert abgelehnt not in r["mapping"], (
                    f"{cup_key}: abgelehnter Anwaerter {abgelehnt} "
                    "steht trotzdem in der Zuordnung")

    def test_b6b_unterklassige_werden_nicht_hineingeraten(self):
        """
        Ausdrueckliche Vorgabe: ein unterklassiger Pokalgegner darf
        niemals in ein Top-5-Team hineingeraten werden.

        "City of Liverpool", "United of Manchester" und "South
        Liverpool" sind echte FA-Cup-Teilnehmer aus dem Unterhaus. Eine
        Teilmengenregel in beide Richtungen hatte sie zuvor auf
        Liverpool bzw. Manchester United gezogen.
        """
        from src.data.domestic_cup_loader import load_cup_season
        payload = load_cup_season("fac", 2025)
        if not payload:
            pytest.skip("FA-Cup-Datei nicht vorhanden")

        teams = {int(k): (v or {}).get("name")
                 for k, v in (payload.get("teams") or {}).items()}
        r = build_crosswalk("pl", 2025, teams)

        namen = {i: (n or "").lower() for i, n in teams.items()}
        for as_id, fd_id in r["mapping"].items():
            name = namen.get(as_id, "")
            for koeder in ("city of liverpool", "united of manchester",
                           "south liverpool", "afc liverpool"):
                assert koeder not in name, (
                    f"{name!r} wurde faelschlich auf {fd_id} zugeordnet")

    def test_b7_zuordnung_ist_umkehrbar_eindeutig(self):
        r = build_crosswalk("bl1", 2025, {})
        assert len(r["reverse"]) == len(set(r["reverse"]))


# ---------------------------------------------------------------------------
# C  Belastungsmerkmale
# ---------------------------------------------------------------------------

class TestC_Belastung:

    def test_c1_pause_in_stunden(self):
        f = workload_features(zeitleiste(spiel(-3)), BASIS)
        assert f["rest_hours"] == 72
        assert f["rest_days"] == 3

    def test_c2_pause_rundet_kaufmaennisch(self):
        tl = zeitleiste(spiel(-3, stunde=14))     # 73 Stunden
        assert workload_features(tl, BASIS)["rest_hours"] == 73

    def test_c3_rest_days_rundet_ab(self):
        """49 Stunden sind zwei volle Tage, nicht drei."""
        tl = zeitleiste(spiel(-2, stunde=14))     # 49 Stunden
        f = workload_features(tl, BASIS)
        assert f["rest_hours"] == 49 and f["rest_days"] == 2

    def test_c4_ohne_vorspiel_keine_pause(self):
        f = workload_features([], BASIS)
        assert f["rest_hours"] is None
        assert f["rest_days"] is None
        assert f["short_rest_flag"] is False

    def test_c5_kurze_pause_wird_markiert(self):
        assert workload_features(zeitleiste(spiel(-2)), BASIS)["short_rest_flag"]
        assert not workload_features(zeitleiste(spiel(-4)), BASIS)["short_rest_flag"]

    def test_c6_fenster_ist_halboffen(self):
        """
        Fenstergrenzen: [cutoff - n Tage, cutoff).

        Die untere Grenze zaehlt MIT, die obere nicht. Ein Spiel genau
        sieben Tage vorher liegt also noch im Sieben-Tage-Fenster, das
        Zielspiel selbst nie. Dieselbe Festlegung wie in
        src/features/congestion.py - zwei verschiedene Fensterbegriffe
        im selben Projekt waeren eine sichere Fehlerquelle.
        """
        tl = zeitleiste(spiel(-8), spiel(-7), spiel(-6), spiel(0))
        f = workload_features(tl, BASIS)
        assert f["matches_last_7_days"] == 2      # -7 und -6, nicht -8, nicht 0
        assert f["matches_last_14_days"] == 3

    def test_c7_alle_vier_fenster_vorhanden(self):
        f = workload_features(zeitleiste(spiel(-1)), BASIS)
        for schluessel in ("matches_last_7_days", "matches_last_14_days",
                           "matches_last_21_days", "matches_last_30_days"):
            assert schluessel in f

    def test_c8_fenster_sind_monoton(self):
        tl = zeitleiste(*[spiel(-t) for t in (1, 5, 10, 18, 25)])
        f = workload_features(tl, BASIS)
        assert (f["matches_last_7_days"] <= f["matches_last_14_days"]
                <= f["matches_last_21_days"] <= f["matches_last_30_days"])

    def test_c9_auswaertsserie_zaehlt_rueckwaerts(self):
        tl = zeitleiste(spiel(-9, heim=1), spiel(-6, heim=2, gast=1),
                        spiel(-3, heim=3, gast=1))
        assert workload_features(tl, BASIS)["consecutive_away_matches"] == 2

    def test_c10_heimspiel_beendet_die_serie(self):
        tl = zeitleiste(spiel(-6, heim=2, gast=1), spiel(-3, heim=1))
        assert workload_features(tl, BASIS)["consecutive_away_matches"] == 0

    def test_c11_wettbewerbe_werden_gemeldet(self):
        tl = zeitleiste(spiel(-6), spiel(-3, wettbewerb="DFB"))
        assert workload_features(tl, BASIS)["competitions_included"] == ["BL1", "DFB"]

    def test_c12_zielspiel_zaehlt_nicht_mit(self):
        """Leakage-Kern: das Spiel am Stichtag darf nichts beitragen."""
        ohne = workload_features(zeitleiste(spiel(-3)), BASIS)
        mit = workload_features(zeitleiste(spiel(-3), spiel(0)), BASIS)
        assert ohne == mit

    def test_c13_spaetere_spiele_zaehlen_nicht(self):
        ohne = workload_features(zeitleiste(spiel(-3)), BASIS)
        mit = workload_features(zeitleiste(spiel(-3), spiel(+5)), BASIS)
        assert ohne == mit

    def test_c14_anzahl_nutzbarer_spiele(self):
        tl = zeitleiste(spiel(-9), spiel(-6), spiel(-3), spiel(+2))
        assert workload_features(tl, BASIS)["number_of_usable_matches"] == 3


# ---------------------------------------------------------------------------
# D  Verdichtungsstufen
# ---------------------------------------------------------------------------

class TestD_Verdichtung:

    def test_d1_ein_pokalspiel_ergibt_niemals_high(self):
        """
        Ausdrueckliche Vorgabe: ein einzelnes normales Pokalspiel darf
        allein keine hohe Belastung erzeugen.
        """
        tl = zeitleiste(spiel(-20), spiel(-13), spiel(-3, wettbewerb="DFB"))
        assert workload_features(tl, BASIS)["congestion_level"] != "high"

    def test_d2_drei_spiele_in_sieben_tagen_sind_high(self):
        tl = zeitleiste(spiel(-20), spiel(-6), spiel(-4), spiel(-2))
        assert workload_features(tl, BASIS)["congestion_level"] == "high"

    def test_d3_zwei_spiele_mit_kurzer_pause_sind_high(self):
        tl = zeitleiste(spiel(-20), spiel(-5), spiel(-2))
        assert workload_features(tl, BASIS)["congestion_level"] == "high"

    def test_d4_zwei_spiele_mit_langer_pause_sind_elevated(self):
        tl = zeitleiste(spiel(-20), spiel(-14), spiel(-6), spiel(-4))
        assert workload_features(tl, BASIS)["congestion_level"] == "elevated"

    def test_d5_ruhige_wochen_sind_low(self):
        tl = zeitleiste(spiel(-30), spiel(-24), spiel(-16))
        assert workload_features(tl, BASIS)["congestion_level"] == "low"

    def test_d6_normalfall_ist_normal(self):
        tl = zeitleiste(spiel(-21), spiel(-14), spiel(-7))
        assert workload_features(tl, BASIS)["congestion_level"] == "normal"

    def test_d7_zu_wenige_spiele_ergeben_keine_stufe(self):
        """Nach zwei Spielen ist jede Aussage ueber Verdichtung geraten."""
        tl = zeitleiste(spiel(-10), spiel(-3))
        assert workload_features(tl, BASIS)["congestion_level"] is None

    def test_d8_stufe_ist_immer_aus_der_erlaubten_menge(self):
        tl = zeitleiste(*[spiel(-t) for t in range(1, 25)])
        stufe = workload_features(tl, BASIS)["congestion_level"]
        assert stufe in ("low", "normal", "elevated", "high", None)


# ---------------------------------------------------------------------------
# E  Datenqualitaet und Neutralitaet
# ---------------------------------------------------------------------------

class TestE_Qualitaet:

    def test_e1_ohne_daten_ist_unavailable(self):
        f = workload_features([], BASIS)
        assert f["data_quality"] == "unavailable"
        assert f["rest_data_quality"] == "unavailable"

    def test_e2_wenige_spiele_sind_fallback(self):
        assert workload_features(zeitleiste(spiel(-3)), BASIS)["data_quality"] == "fallback"

    def test_e3_genug_spiele_sind_complete(self):
        tl = zeitleiste(spiel(-21), spiel(-14), spiel(-7))
        assert workload_features(tl, BASIS)["data_quality"] == "complete"

    def test_e4_zaehlung_bleibt_complete_ohne_uhrzeit(self):
        """
        Ohne Anstosszeit sind die ZAEHLUNGEN weiterhin exakt - sie
        haengen nur am Kalendertag. Nur die Pause wird ungenauer.
        """
        tl = zeitleiste(spiel(-21, praezise=False), spiel(-14, praezise=False),
                        spiel(-7, praezise=False))
        f = workload_features(tl, BASIS)
        assert f["data_quality"] == "complete"
        assert f["rest_data_quality"] == "partial"

    def test_e5_echte_uhrzeit_ergibt_complete(self):
        tl = zeitleiste(spiel(-21), spiel(-14), spiel(-7))
        assert workload_features(tl, BASIS)["rest_data_quality"] == "complete"

    def test_e6_unavailable_wiegt_exakt_null(self):
        assert quality_weight("unavailable") == 0.0

    def test_e7_gewichte_sind_geordnet(self):
        assert (quality_weight("complete") > quality_weight("partial")
                > quality_weight("fallback") > quality_weight("unavailable"))

    def test_e8_kombination_nimmt_die_schlechteste(self):
        assert combined_quality("complete", "partial") == "partial"
        assert combined_quality("complete", "unavailable") == "unavailable"
        assert combined_quality("complete", "complete") == "complete"

    def test_e9_unbekannte_klasse_ist_neutral(self):
        assert quality_weight("phantasie") == 0.0

    def test_e10_ohne_staerkeliste_keine_planhaerte(self):
        s = schedule_strength(zeitleiste(spiel(-3)), BASIS, {})
        assert s["recent_opponent_strength"] is None
        assert s["schedule_strength_quality"] == "unavailable"

    def test_e11_planhaerte_mittelt_nur_bekannte_gegner(self):
        tl = zeitleiste(spiel(-9, gast=2), spiel(-6, gast=3), spiel(-3, gast=4))
        s = schedule_strength(tl, BASIS, {2: 1.0, 3: 2.0})
        assert s["number_of_usable_opponents"] == 2
        assert s["recent_opponent_strength"] == 1.5
        assert s["opponents_without_strength"] == 1
        assert s["schedule_strength_quality"] == "fallback"

    def test_e12_planhaerte_ohne_luecken_ist_complete(self):
        tl = zeitleiste(spiel(-9, gast=2), spiel(-6, gast=3), spiel(-3, gast=4))
        s = schedule_strength(tl, BASIS, {2: 1.0, 3: 1.0, 4: 1.0})
        assert s["schedule_strength_quality"] == "complete"

    def test_e13_planhaerte_ignoriert_spiele_nach_cutoff(self):
        tl = zeitleiste(spiel(-3, gast=2), spiel(+3, gast=9))
        s = schedule_strength(tl, BASIS, {2: 1.0, 9: 9.0})
        assert s["recent_opponent_strength"] == 1.0


# ---------------------------------------------------------------------------
# F  Korrektur, Clamping, Konstanten
# ---------------------------------------------------------------------------

def merkmale(**kwargs):
    basis = {
        "rest_hours": 168, "congestion_level": "normal",
        "consecutive_away_matches": 0,
        "data_quality": "complete", "rest_data_quality": "complete",
    }
    basis.update(kwargs)
    return basis


class TestF_Korrektur:

    def test_f1_referenzpause_ergibt_exakt_null(self):
        r = compute_modifier(merkmale(), {"schedule_strength_quality": "unavailable"})
        assert r["modifier"] == 0.0

    def test_f2_fehlende_daten_ergeben_exakt_null(self):
        r = compute_modifier(
            merkmale(rest_hours=None, congestion_level=None,
                     data_quality="unavailable", rest_data_quality="unavailable"),
            {"schedule_strength_quality": "unavailable"})
        assert r["modifier"] == 0.0
        assert r["data_quality"] == "unavailable"

    def test_f3_kurze_pause_wirkt_negativ(self):
        r = compute_modifier(merkmale(rest_hours=72),
                             {"schedule_strength_quality": "unavailable"})
        assert r["modifier"] < 0

    def test_f4_lange_pause_gibt_keinen_bonus(self):
        """Ueber der Referenz ist der Effekt bewusst null, nicht positiv."""
        r = compute_modifier(merkmale(rest_hours=400),
                             {"schedule_strength_quality": "unavailable"})
        assert r["components"]["rest"] == 0.0

    def test_f5_hohe_verdichtung_wirkt_negativ(self):
        r = compute_modifier(merkmale(congestion_level="high"),
                             {"schedule_strength_quality": "unavailable"})
        assert r["components"]["congestion"] < 0

    def test_f6_ruhige_woche_wirkt_leicht_positiv(self):
        r = compute_modifier(merkmale(congestion_level="low"),
                             {"schedule_strength_quality": "unavailable"})
        assert r["components"]["congestion"] > 0

    def test_f7_erholung_wirkt_schwaecher_als_ermuedung(self):
        werte = CONSTANTS["CONGESTION_EFFECT"]["wert"]
        assert abs(werte["low"]) < abs(werte["high"])

    def test_f8_auswaertsserie_erst_ab_dem_zweiten_spiel(self):
        eins = compute_modifier(merkmale(consecutive_away_matches=1),
                                {"schedule_strength_quality": "unavailable"})
        zwei = compute_modifier(merkmale(consecutive_away_matches=2),
                                {"schedule_strength_quality": "unavailable"})
        assert eins["components"]["consecutive_away"] == 0.0
        assert zwei["components"]["consecutive_away"] < 0

    def test_f9_einzeleffekt_wird_begrenzt(self):
        r = compute_modifier(merkmale(rest_hours=-10000),
                             {"schedule_strength_quality": "unavailable"})
        grenze = CONSTANTS["MAX_SINGLE_EFFECT"]["wert"]
        assert abs(r["components"]["rest"]) <= grenze + 1e-9
        assert r["clamp_applied"] is True
        assert "rest" in r["clamped_parts"]

    def test_f10_gesamteffekt_wird_begrenzt(self):
        r = compute_modifier(
            merkmale(rest_hours=-10000, congestion_level="high",
                     consecutive_away_matches=50),
            {"schedule_strength_quality": "unavailable"})
        assert abs(r["modifier"]) <= CONSTANTS["MAX_TOTAL_EFFECT"]["wert"] + 1e-9
        assert "total" in r["clamped_parts"]

    def test_f11_gesamtgrenze_kleiner_als_summe_der_einzelgrenzen(self):
        assert (CONSTANTS["MAX_TOTAL_EFFECT"]["wert"]
                < 4 * CONSTANTS["MAX_SINGLE_EFFECT"]["wert"])

    def test_f12_qualitaet_daempft_den_effekt(self):
        voll = compute_modifier(merkmale(rest_hours=72),
                                {"schedule_strength_quality": "unavailable"})
        halb = compute_modifier(merkmale(rest_hours=72, rest_data_quality="partial"),
                                {"schedule_strength_quality": "unavailable"})
        assert abs(halb["components"]["rest"]) < abs(voll["components"]["rest"])

    def test_f13_winzige_effekte_werden_verworfen(self):
        r = compute_modifier(merkmale(rest_hours=167),
                             {"schedule_strength_quality": "unavailable"})
        assert r["modifier"] == 0.0

    def test_f14_apply_veraendert_das_original_nicht(self):
        profil = {"attack_home": 1.4, "attack_away": 1.1,
                  "defence_home": 0.8, "defence_away": 1.0}
        kopie = dict(profil)
        apply_modifier(profil, -0.02)
        assert profil == kopie

    def test_f15_muedigkeit_senkt_angriff_und_verschlechtert_abwehr(self):
        profil = {"attack_home": 1.0, "attack_away": 1.0,
                  "defence_home": 1.0, "defence_away": 1.0}
        neu = apply_modifier(profil, -0.02)
        assert neu["attack_home"] < 1.0
        # Groessere defence-Werte sind im Projekt schlechter.
        assert neu["defence_home"] > 1.0

    def test_f16_nullkorrektur_aendert_nichts(self):
        profil = {"attack_home": 1.4, "attack_away": 1.1,
                  "defence_home": 0.8, "defence_away": 1.0}
        assert apply_modifier(profil, 0.0) == profil

    def test_f17_jede_konstante_ist_dokumentiert(self):
        for name, eintrag in CONSTANTS.items():
            assert eintrag["zweck"], name
            assert eintrag["begruendung"], name
            assert len(eintrag["bereich"]) == 2, name

    def test_f18_jede_konstante_liegt_in_ihrem_bereich(self):
        for name, eintrag in CONSTANTS.items():
            unten, oben = eintrag["bereich"]
            wert = eintrag["wert"]
            werte = wert.values() if isinstance(wert, dict) else [wert]
            for w in werte:
                assert unten <= w <= oben, f"{name}: {w} nicht in [{unten}, {oben}]"

    def test_f19_konstantenbericht_ist_vollstaendig(self):
        bericht = constants_report()
        assert len(bericht) == len(CONSTANTS)
        assert all(z["justification"] for z in bericht)

    def test_f20_bericht_enthaelt_keine_pfade_oder_secrets(self):
        text = str(constants_report()).lower()
        for verboten in ("c:\\", "/root", "api_key", "token", "passwo", ".env"):
            assert verboten not in text


# ---------------------------------------------------------------------------
# G  Snapshot, Cache, Shadow-Modus
# ---------------------------------------------------------------------------

class TestG_Snapshot:

    def setup_method(self):
        go3_provider.clear_cache()

    def teardown_method(self):
        go3_provider.clear_cache()
        os.environ.pop(go3.MODE_ENV_VAR, None)

    def test_g1_voreinstellung_ist_shadow(self):
        os.environ.pop(go3.MODE_ENV_VAR, None)
        assert current_mode() == "shadow"
        assert go3.DEFAULT_MODE == "shadow"

    def test_g2_modus_laesst_sich_setzen(self):
        os.environ[go3.MODE_ENV_VAR] = "active"
        assert current_mode() == "active"

    def test_g3_unsinniger_modus_faellt_auf_shadow_zurueck(self):
        os.environ[go3.MODE_ENV_VAR] = "vollgas"
        assert current_mode() == "shadow"

    def test_g4_shadow_laesst_die_profile_unveraendert(self):
        os.environ[go3.MODE_ENV_VAR] = "shadow"
        profil = {"attack_home": 1.4, "attack_away": 1.1,
                  "defence_home": 0.8, "defence_away": 1.0}
        s = go3_provider.fixture_snapshot(
            5, 4, datetime(2025, 11, 1, 12), [2025], "BL1",
            home_profile=profil, away_profile=dict(profil))
        assert s["applied"] is False
        assert s["adjusted_profiles"]["home"] == s["baseline_profiles"]["home"]

    def test_g5_off_laesst_die_profile_unveraendert(self):
        os.environ[go3.MODE_ENV_VAR] = "off"
        profil = {"attack_home": 1.4, "attack_away": 1.1,
                  "defence_home": 0.8, "defence_away": 1.0}
        s = go3_provider.fixture_snapshot(
            5, 4, datetime(2025, 11, 1, 12), [2025], "BL1",
            home_profile=profil, away_profile=dict(profil))
        assert s["applied"] is False
        assert s["adjusted_profiles"]["home"] == s["baseline_profiles"]["home"]

    def test_g6_shadow_rechnet_trotzdem(self):
        """Der Sinn von shadow: sichtbar, aber wirkungslos."""
        os.environ[go3.MODE_ENV_VAR] = "shadow"
        s = go3_provider.fixture_snapshot(
            5, 4, datetime(2025, 11, 1, 12), [2025], "BL1")
        assert s["home"]["workload"]["number_of_usable_matches"] > 0
        assert "modifier" in s["home"]["modifier"]

    def test_g7_snapshot_ist_reproduzierbar(self):
        a = go3_provider.fixture_snapshot(5, 4, datetime(2025, 11, 1, 12), [2025], "BL1")
        go3_provider.clear_cache()
        b = go3_provider.fixture_snapshot(5, 4, datetime(2025, 11, 1, 12), [2025], "BL1")
        assert a["home"]["modifier"] == b["home"]["modifier"]
        assert a["away"]["modifier"] == b["away"]["modifier"]

    def test_g8_cache_liefert_dasselbe_objekt(self):
        cutoff = datetime(2025, 11, 1, 12)
        a = go3_provider.team_features(5, cutoff, [2025], "BL1")
        b = go3_provider.team_features(5, cutoff, [2025], "BL1")
        assert a is b

    def test_g9_anderer_cutoff_ist_ein_anderer_eintrag(self):
        a = go3_provider.team_features(5, datetime(2025, 11, 1, 12), [2025], "BL1")
        b = go3_provider.team_features(5, datetime(2025, 12, 1, 12), [2025], "BL1")
        assert a is not b

    def test_g10_keine_netzabfrage_im_snapshot(self):
        """
        Kernvorgabe: keine Anbieterabfrage je Simulation. Der Test
        sperrt den Socket-Aufbau vollstaendig.
        """
        import socket
        original = socket.socket.connect

        def gesperrt(*args, **kwargs):
            raise AssertionError("GO 3 hat eine Netzverbindung aufgebaut")

        socket.socket.connect = gesperrt
        try:
            go3_provider.clear_cache()
            go3_provider.fixture_snapshot(
                5, 4, datetime(2025, 11, 1, 12), [2025], "BL1")
        finally:
            socket.socket.connect = original

    def test_g11_wiederholte_aufrufe_bleiben_billig(self):
        """Steht fuer die Monte-Carlo-Schleife: 2000 Aufrufe, kein Neuaufbau."""
        import time
        cutoff = datetime(2025, 11, 1, 12)
        go3_provider.fixture_snapshot(5, 4, cutoff, [2025], "BL1")
        start = time.time()
        for _ in range(2000):
            go3_provider.fixture_snapshot(5, 4, cutoff, [2025], "BL1")
        assert time.time() - start < 2.0

    def test_g12_shadow_bericht_nennt_beide_teams(self):
        s = go3_provider.fixture_snapshot(5, 4, datetime(2025, 11, 1, 12), [2025], "BL1")
        b = go3_provider.shadow_report(s)
        assert b["home"]["team_id"] == 5 and b["away"]["team_id"] == 4
        assert b["applied_to_simulation"] is False

    def test_g13_shadow_bericht_rechnet_die_verschiebung(self):
        s = go3_provider.fixture_snapshot(5, 4, datetime(2025, 11, 1, 12), [2025], "BL1")
        b = go3_provider.shadow_report(s)
        assert (round(b["home"]["modifier"] - b["away"]["modifier"], 6)
                == b["relative_shift"])

    def test_g14_shadow_bericht_stellt_wahrscheinlichkeiten_gegenueber(self):
        s = go3_provider.fixture_snapshot(5, 4, datetime(2025, 11, 1, 12), [2025], "BL1")
        b = go3_provider.shadow_report(
            s, {"home_win": 0.5, "draw": 0.3, "away_win": 0.2},
            {"home_win": 0.48, "draw": 0.31, "away_win": 0.21})
        assert b["probability_diffs"]["home_win"] == -0.02
        assert b["max_probability_change"] == 0.02

    def test_g15_bericht_enthaelt_keine_pfade(self):
        s = go3_provider.fixture_snapshot(5, 4, datetime(2025, 11, 1, 12), [2025], "BL1")
        text = str(go3_provider.shadow_report(s)).lower()
        for verboten in ("c:\\", "/root", "api_key", "traceback", ".env"):
            assert verboten not in text

    def test_g16_ligadurchschnitt_ohne_werte_ist_none(self):
        assert go3_provider.league_average_strength({}) is None
        assert go3_provider.league_average_strength({1: None}) is None

    def test_g17_ligadurchschnitt_mittelt(self):
        assert go3_provider.league_average_strength({1: 1.0, 2: 2.0}) == 1.5


# ---------------------------------------------------------------------------
# H  Backtest-Kennzahlen
# ---------------------------------------------------------------------------

class TestH_Backtest:

    def test_h1_wahrscheinlichkeiten_summieren_auf_eins(self):
        p = outcome_probabilities(1.5, 1.2)
        assert abs(sum(p) - 1.0) < 1e-9

    def test_h2_staerkeres_heimteam_gewinnt_haeufiger(self):
        h, d, a = outcome_probabilities(2.5, 0.8)
        assert h > a

    def test_h3_gleiche_erwartung_ist_symmetrisch(self):
        h, d, a = outcome_probabilities(1.4, 1.4)
        assert abs(h - a) < 1e-9

    def test_h4_log_loss_belohnt_sicherheit(self):
        assert _log_loss((0.9, 0.05, 0.05), 0) < _log_loss((0.4, 0.3, 0.3), 0)

    def test_h5_log_loss_bleibt_endlich(self):
        assert _log_loss((0.0, 0.0, 1.0), 0) < float("inf")

    def test_h6_brier_ist_null_bei_perfekter_vorhersage(self):
        assert _brier((1.0, 0.0, 0.0), 0) == 0.0

    def test_h7_rps_bestraft_den_ferneren_irrtum_staerker(self):
        """
        Statt eines Heimsiegs ein Unentschieden vorherzusagen ist
        weniger falsch als ein Auswaertssieg. Genau das unterscheidet
        den RPS vom Brier-Score.
        """
        nah = _rps((0.0, 1.0, 0.0), 0)
        fern = _rps((0.0, 0.0, 1.0), 0)
        assert nah < fern

    def test_h8_rps_ist_null_bei_perfekter_vorhersage(self):
        assert _rps((1.0, 0.0, 0.0), 0) == 0.0

    def test_h9_baseline_variante_ist_leer(self):
        assert VARIANTS["baseline"] == ()

    def test_h10_alle_ablationen_sind_teilmengen_der_vollen(self):
        voll = set(VARIANTS["full_go3"])
        for name, faktoren in VARIANTS.items():
            assert set(faktoren) <= voll, name

    def test_h11_backtest_liefert_alle_varianten(self):
        from src.features.go3_backtest import run_backtest
        r = run_backtest("bl1", 2024, [2023, 2024])
        assert r is not None
        assert set(r["variants"]) == set(VARIANTS)
        assert r["variants"]["baseline"]["n"] > 100

    def test_h12_backtest_ist_reproduzierbar(self):
        from src.features.go3_backtest import run_backtest
        a = run_backtest("bl1", 2024, [2023, 2024])
        b = run_backtest("bl1", 2024, [2023, 2024])
        assert a["variants"]["full_go3"] == b["variants"]["full_go3"]

    def test_h13_baseline_hat_keine_wahrscheinlichkeitsaenderung(self):
        from src.features.go3_backtest import run_backtest
        r = run_backtest("bl1", 2024, [2023, 2024])
        assert r["variants"]["baseline"]["avg_probability_change"] == 0.0

    def test_h14_alle_varianten_bewerten_dieselben_spiele(self):
        from src.features.go3_backtest import run_backtest
        r = run_backtest("bl1", 2024, [2023, 2024])
        anzahlen = {v["n"] for v in r["variants"].values() if v}
        assert len(anzahlen) == 1

    def test_h15_kalibrierung_wird_gemeldet(self):
        from src.features.go3_backtest import run_backtest
        r = run_backtest("bl1", 2024, [2023, 2024])
        b = r["variants"]["baseline"]
        assert b["calibration_error"] is not None
        assert b["calibration_bins"]


# ---------------------------------------------------------------------------
# Leakage - quer durch alle Bereiche
# ---------------------------------------------------------------------------

class TestLeakage:

    def test_l1_kein_merkmal_kennt_die_zukunft(self):
        """
        Dieselbe Zeitleiste, einmal mit und einmal ohne spaetere Spiele:
        jedes einzelne Merkmal muss identisch sein.
        """
        vergangenheit = [spiel(-21), spiel(-14), spiel(-7)]
        zukunft = [spiel(+1), spiel(+8), spiel(+15, wettbewerb="CL")]
        ohne = workload_features(zeitleiste(*vergangenheit), BASIS)
        mit = workload_features(zeitleiste(*(vergangenheit + zukunft)), BASIS)
        assert ohne == mit

    def test_l2_planhaerte_kennt_die_zukunft_nicht(self):
        vergangenheit = [spiel(-21, gast=2), spiel(-14, gast=3), spiel(-7, gast=4)]
        zukunft = [spiel(+7, gast=9)]
        lookup = {2: 1.0, 3: 1.0, 4: 1.0, 9: 99.0}
        ohne = schedule_strength(zeitleiste(*vergangenheit), BASIS, lookup)
        mit = schedule_strength(zeitleiste(*(vergangenheit + zukunft)), BASIS, lookup)
        assert ohne == mit

    def test_l3_korrektur_kennt_die_zukunft_nicht(self):
        vergangenheit = [spiel(-21), spiel(-14), spiel(-7)]
        ohne = compute_modifier(workload_features(zeitleiste(*vergangenheit), BASIS))
        mit = compute_modifier(
            workload_features(zeitleiste(*(vergangenheit + [spiel(+1)])), BASIS))
        assert ohne == mit

    def test_l4_frueherer_cutoff_sieht_hoechstens_weniger(self):
        tl = zeitleiste(*[spiel(-t) for t in (28, 21, 14, 7, 3)])
        frueher = workload_features(tl, BASIS - timedelta(days=10))
        spaeter = workload_features(tl, BASIS)
        assert (frueher["number_of_usable_matches"]
                <= spaeter["number_of_usable_matches"])
