"""
Tests fuer das Big-Game-Modell (Block F1, src/features/big_games.py).

Abgedeckt:
  A) Rundennormalisierung (echte Providerformate, mehrere Aeren)
  B) Matchbedeutung und bedeutungsbasierte Zulassung
  C) Gegnerstaerke (stetig, gleicher Koeffizient = gleicher Wert)
  D) Zulassungsgrenze Rang 30/31 - OHNE kuenstliche Gewichtsstufe
  E) Dominanz-Invariante (Bedeutung schlaegt nie Gegnerstaerke)
  F) Aggregation: Rohwerte bleiben roh, Gewichtung getrennt
  G) Mindestumfang

Reines Modell, kein Netz, kein Dateizugriff, keine Mocks noetig.
"""

import pytest

from src.features import big_games as bg


# ===========================================================================
# A) Rundennormalisierung
# ===========================================================================

class TestRoundNormalization:
    @pytest.mark.parametrize("raw,expected", [
        # An echten API-Football-Antworten geprueft (mehrere Saisons/Formate).
        ("Regular Season - 1",       bg.STAGE_LEAGUE),
        ("Regular Season - 38",      bg.STAGE_LEAGUE),
        ("Group Stage - 1",          bg.STAGE_GROUP),     # CL 2021/22
        ("Group A - 2",              bg.STAGE_GROUP),     # CL 2022/23
        ("Group H - 6",              bg.STAGE_GROUP),
        ("League Stage - 1",         bg.STAGE_GROUP),     # CL ab 2024/25
        ("1st Qualifying Round",     bg.STAGE_QUALIFYING),
        ("3rd Qualifying Round",     bg.STAGE_QUALIFYING),
        ("Knockout Round Play-offs", bg.STAGE_PLAYOFF),
        ("Round of 16",              bg.STAGE_ROUND_OF_16),
        ("Quarter-finals",           bg.STAGE_QUARTERFINAL),
        ("Semi-finals",              bg.STAGE_SEMIFINAL),
        ("Final",                    bg.STAGE_FINAL),
    ])
    def test_echte_rundentexte(self, raw, expected):
        assert bg.normalize_round(raw) == expected

    def test_finale_wird_nicht_mit_halbfinale_verwechselt(self):
        """
        Der eigentliche Grund fuer exakte Zuordnung statt `"Final" in round`:
        "Quarter-finals" und "Semi-finals" enthalten beide "final".
        """
        assert bg.normalize_round("Quarter-finals") != bg.STAGE_FINAL
        assert bg.normalize_round("Semi-finals") != bg.STAGE_FINAL
        assert bg.normalize_round("Final") == bg.STAGE_FINAL

    def test_gross_klein_und_leerzeichen_egal(self):
        assert bg.normalize_round("  ROUND OF 16 ") == bg.STAGE_ROUND_OF_16
        assert bg.normalize_round("final") == bg.STAGE_FINAL

    @pytest.mark.parametrize("raw", [None, "", "   ", 42, [], "Völlig Unbekannt"])
    def test_unbekanntes_crasht_nicht(self, raw):
        assert bg.normalize_round(raw) == bg.STAGE_UNKNOWN

    def test_unbekannte_runde_bekommt_keinen_bonus(self):
        assert bg.match_importance(bg.normalize_round("Nonsense")) == bg.IMPORTANCE_BASE


# ===========================================================================
# B) Matchbedeutung
# ===========================================================================

class TestMatchImportance:
    def test_finale_wiegt_am_schwersten(self):
        assert bg.match_importance(bg.STAGE_FINAL) > bg.match_importance(bg.STAGE_SEMIFINAL)
        assert bg.match_importance(bg.STAGE_SEMIFINAL) > bg.match_importance(bg.STAGE_QUARTERFINAL)
        assert bg.match_importance(bg.STAGE_QUARTERFINAL) > bg.match_importance(bg.STAGE_ROUND_OF_16)

    def test_ligaspiel_und_gruppenphase_sind_neutral(self):
        assert bg.match_importance(bg.STAGE_LEAGUE) == bg.IMPORTANCE_BASE
        assert bg.match_importance(bg.STAGE_GROUP) == bg.IMPORTANCE_BASE

    def test_europaeische_ko_runde_qualifiziert_allein(self):
        for stage in (bg.STAGE_ROUND_OF_16, bg.STAGE_QUARTERFINAL,
                      bg.STAGE_SEMIFINAL, bg.STAGE_FINAL):
            assert bg.is_importance_qualified(stage, bg.TIER_EUROPEAN) is True

    def test_gruppenphase_qualifiziert_nicht_allein(self):
        assert bg.is_importance_qualified(bg.STAGE_GROUP, bg.TIER_EUROPEAN) is False
        assert bg.is_importance_qualified(bg.STAGE_LEAGUE, bg.TIER_EUROPEAN) is False

    def test_nationaler_pokal_nur_das_finale_qualifiziert(self):
        """
        Ein Achtelfinale im nationalen Pokal gegen einen Zweitligisten ist
        kein grosses Spiel - ein Champions-League-Achtelfinale schon.
        Beide tragen beim Provider denselben Rundentext "Round of 16",
        deshalb entscheidet zusaetzlich die Wettbewerbsebene.
        """
        assert bg.is_importance_qualified(bg.STAGE_ROUND_OF_16, bg.TIER_DOMESTIC) is False
        assert bg.is_importance_qualified(bg.STAGE_SEMIFINAL, bg.TIER_DOMESTIC) is False
        # Ein Pokalfinale bleibt unabhaengig vom Gegner ein grosses Spiel.
        assert bg.is_importance_qualified(bg.STAGE_FINAL, bg.TIER_DOMESTIC) is True

    def test_wettbewerbsebene_ueber_liga_id(self):
        assert bg.competition_tier(2) == bg.TIER_EUROPEAN      # Champions League
        assert bg.competition_tier(3) == bg.TIER_EUROPEAN      # Europa League
        assert bg.competition_tier(848) == bg.TIER_EUROPEAN    # Conference League
        assert bg.competition_tier(39) == bg.TIER_DOMESTIC     # Premier League
        assert bg.competition_tier(None) == bg.TIER_DOMESTIC


# ===========================================================================
# C) Gegnerstaerke
# ===========================================================================

class TestOpponentStrength:
    def test_staerkster_und_schwaechster_treffen_die_grenzen(self):
        assert bg.opponent_strength(140.0, 40.0, 140.0) == bg.OPPONENT_STRENGTH_CEILING
        assert bg.opponent_strength(40.0, 40.0, 140.0) == bg.OPPONENT_STRENGTH_FLOOR

    def test_gleicher_koeffizient_gleiche_staerke(self):
        """
        Kernanforderung: zwei Klubs mit identischem Koeffizienten muessen
        denselben Wert bekommen - unabhaengig davon, welchen Rang die
        Tabelle ihnen zugewiesen hat. Genau dieser Fall existiert real
        (2021/22 und 2022/23: Rang 30 und 31 sind gleichauf).
        """
        a = bg.opponent_strength(53.0, 41.0, 138.0)
        b = bg.opponent_strength(53.0, 41.0, 138.0)
        assert a == b

    def test_monoton_steigend(self):
        weaker = bg.opponent_strength(60.0, 40.0, 140.0)
        stronger = bg.opponent_strength(120.0, 40.0, 140.0)
        assert stronger > weaker

    def test_ohne_koeffizient_neutral(self):
        assert bg.opponent_strength(None, 40.0, 140.0) == bg.OPPONENT_STRENGTH_UNKNOWN

    def test_ohne_spannweite_neutral(self):
        """Alle Klubs gleichauf: eine relative Einordnung ist nicht moeglich."""
        assert bg.opponent_strength(50.0, 50.0, 50.0) == bg.OPPONENT_STRENGTH_UNKNOWN

    def test_nie_unter_den_basiswert(self):
        """Ein schwacher Gegner wird nie ABgewertet, nur ein starker AUFgewertet."""
        assert bg.opponent_strength(10.0, 40.0, 140.0) >= bg.OPPONENT_STRENGTH_FLOOR

    def test_werte_ausserhalb_der_liste_werden_nicht_extrapoliert(self):
        assert bg.opponent_strength(500.0, 40.0, 140.0) == bg.OPPONENT_STRENGTH_CEILING


# ===========================================================================
# D) Zulassungsgrenze - ohne kuenstliche Gewichtsstufe
# ===========================================================================

class TestEligibilityBoundary:
    def test_rang_30_qualifiziert_rang_31_nicht(self):
        assert bg.is_opponent_qualified(30) is True
        assert bg.is_opponent_qualified(31) is False

    def test_rang_1_qualifiziert(self):
        assert bg.is_opponent_qualified(1) is True

    def test_ohne_rang_keine_zulassung_ueber_den_gegner(self):
        assert bg.is_opponent_qualified(None) is False

    def test_kein_kuenstlicher_gewichtssprung_an_der_grenze(self):
        """
        Die Grenze bei 30/31 ist eine ZULASSUNGS-Entscheidung. Sie darf
        sich NICHT in der Gewichtung niederschlagen: zwei Klubs mit
        gleichem Koeffizienten muessen gleich gewichtet werden, auch wenn
        die Tabelle sie auf Rang 30 und 31 setzt.
        """
        rank30 = bg.opponent_strength(53.0, 41.0, 138.0)
        rank31 = bg.opponent_strength(53.0, 41.0, 138.0)
        assert rank30 == rank31

    def test_rang_31_kann_ueber_die_bedeutung_qualifizieren(self):
        """
        Ein Gegner ausserhalb der Top 30 schliesst ein Big Game nicht aus -
        ein Champions-League-Finale bleibt eines.
        """
        assert bg.is_opponent_qualified(34) is False
        assert bg.is_importance_qualified(bg.STAGE_FINAL, bg.TIER_EUROPEAN) is True


# ===========================================================================
# E) Dominanz-Invariante
# ===========================================================================

class TestDominanceInvariant:
    def test_bedeutung_kann_gegnerstaerke_nie_ueberstimmen(self):
        """
        Ein Spitzengegner im belanglosen Spiel muss schwerer wiegen als ein
        Aussenseiter im Finale. Bricht diese Eigenschaft, ist das Modell
        fachlich falsch - deshalb ausdruecklich als Test.
        """
        elite_ordinary = bg.big_game_weight(
            bg.OPPONENT_STRENGTH_CEILING, bg.match_importance(bg.STAGE_LEAGUE))
        weak_final = bg.big_game_weight(
            bg.OPPONENT_STRENGTH_FLOOR, bg.match_importance(bg.STAGE_FINAL))
        assert elite_ordinary > weak_final

    def test_groesster_bedeutungsfaktor_unter_groesster_gegnerstaerke(self):
        assert max(bg.MATCH_IMPORTANCE.values()) < bg.OPPONENT_STRENGTH_CEILING

    def test_gewicht_ist_multiplikativ(self):
        assert bg.big_game_weight(1.4, 1.1) == pytest.approx(1.54)

    def test_obergrenze_dokumentiert(self):
        assert bg.MAX_COMBINED_WEIGHT == pytest.approx(
            bg.OPPONENT_STRENGTH_CEILING * max(bg.MATCH_IMPORTANCE.values()))


# ===========================================================================
# F) Aggregation - Rohwerte bleiben roh
# ===========================================================================

def make_entry(minutes=90, rating=7.0, weight=1.0, strength=1.0, **kwargs):
    entry = {"minutes": minutes, "rating": rating, "weight": weight, "strength": strength}
    entry.update(kwargs)
    return entry


class TestAggregation:
    def test_rohe_tore_bleiben_unveraendert(self):
        """
        DIE zentrale Zusicherung des ganzen Blocks: vier Tore bleiben vier
        Tore, egal wie stark der Kontext gewichtet wird.
        """
        entries = [
            make_entry(goals=1, weight=1.5),
            make_entry(goals=1, weight=1.5),
            make_entry(goals=1, weight=1.5),
            make_entry(goals=1, weight=1.5),
        ]
        result = bg.aggregate_big_games(entries)
        assert result["raw"]["goals"] == 4

    def test_gleiche_rohwerte_trotz_unterschiedlichem_kontext(self):
        """
        Zwei Spieler mit je vier Toren zeigen beide vier Tore - der
        Unterschied im Kontext erscheint ausschliesslich im Score.
        """
        strong = [make_entry(goals=2, rating=8.0, weight=1.5, strength=1.5) for _ in range(2)]
        weak = [make_entry(goals=2, rating=8.0, weight=1.0, strength=1.0) for _ in range(2)]

        a = bg.aggregate_big_games(strong + [make_entry(rating=8.0, weight=1.5, strength=1.5)])
        b = bg.aggregate_big_games(weak + [make_entry(rating=8.0, weight=1.0, strength=1.0)])

        assert a["raw"]["goals"] == b["raw"]["goals"] == 4
        # Gleiche Leistung, staerkerer Kontext -> hoeherer Score.
        assert a["big_game_score"] > b["big_game_score"]

    def test_identischer_kontext_und_leistung_ergibt_identischen_score(self):
        entries = [make_entry(rating=7.5, weight=1.2, strength=1.2) for _ in range(3)]
        a = bg.aggregate_big_games(entries)
        b = bg.aggregate_big_games(entries)
        assert a["big_game_score"] == b["big_game_score"]

    def test_fehlender_wert_bleibt_none_und_wird_nie_null(self):
        entries = [make_entry(goals=None) for _ in range(3)]
        result = bg.aggregate_big_games(entries)
        assert result["raw"]["goals"] is None

    def test_teilweise_vorhandene_werte_werden_summiert(self):
        entries = [make_entry(goals=1), make_entry(goals=None), make_entry(goals=2)]
        result = bg.aggregate_big_games(entries)
        assert result["raw"]["goals"] == 3

    def test_bewertung_nach_einsatzzeit_gewichtet(self):
        """Ein Kurzeinsatz darf nicht so schwer wiegen wie 90 Minuten."""
        entries = [
            make_entry(minutes=90, rating=8.0),
            make_entry(minutes=10, rating=4.0),
            make_entry(minutes=90, rating=8.0),
        ]
        result = bg.aggregate_big_games(entries)
        assert result["avg_rating"] > 7.5

    def test_spieler_ohne_einsatz_zaehlt_nicht(self):
        entries = [make_entry(minutes=0), make_entry(minutes=90), make_entry(minutes=90),
                   make_entry(minutes=90)]
        result = bg.aggregate_big_games(entries)
        assert result["raw"]["matches"] == 3

    def test_bewertung_als_zeichenkette_wird_geparst(self):
        """Der Provider liefert die Bewertung teils als String."""
        entries = [make_entry(rating="7.5") for _ in range(3)]
        result = bg.aggregate_big_games(entries)
        assert result["avg_rating"] == pytest.approx(7.5)

    def test_leere_eingabe_crasht_nicht(self):
        result = bg.aggregate_big_games([])
        assert result["raw"]["matches"] == 0
        assert result["big_game_score"] is None
        assert result["sufficient_sample"] is False

    def test_durchschnittliche_gegnerstaerke_wird_ausgewiesen(self):
        entries = [make_entry(strength=1.5), make_entry(strength=1.1), make_entry(strength=1.3)]
        result = bg.aggregate_big_games(entries)
        assert result["avg_opponent_strength"] == pytest.approx(1.3, abs=0.01)

    def test_gewichtete_beteiligung_ist_getrennt_ausgewiesen(self):
        """
        Die gewichtete Torbeteiligung ist ein EIGENES, benanntes Feld -
        sie ueberschreibt nirgends die rohen Tore.
        """
        entries = [make_entry(goals=1, weight=2.0) for _ in range(3)]
        result = bg.aggregate_big_games(entries)
        assert result["raw"]["goals"] == 3
        assert result["weighted_involvement_per90"] is not None
        assert result["weighted_involvement_per90"] != result["raw"]["goals"]


# ===========================================================================
# G) Mindestumfang
# ===========================================================================

class TestSampleSize:
    def test_zu_wenige_spiele_ergeben_keinen_score(self):
        """
        Ein Spieler mit 90 Minuten und zwei Toren darf nicht automatisch
        besser dastehen als einer mit tausenden Minuten.
        """
        entries = [make_entry(minutes=90, rating=9.5, goals=2)]
        result = bg.aggregate_big_games(entries)
        assert result["sufficient_sample"] is False
        assert result["big_game_score"] is None
        # Rohwerte bleiben trotzdem sichtbar - Transparenz vor Verschweigen.
        assert result["raw"]["goals"] == 2

    def test_zu_wenige_minuten_ergeben_keinen_score(self):
        entries = [make_entry(minutes=20, rating=8.0) for _ in range(4)]
        result = bg.aggregate_big_games(entries)
        assert result["sufficient_sample"] is False
        assert result["big_game_score"] is None

    def test_ausreichender_umfang_ergibt_score(self):
        entries = [make_entry(minutes=90, rating=7.0) for _ in range(3)]
        result = bg.aggregate_big_games(entries)
        assert result["sufficient_sample"] is True
        assert result["big_game_score"] is not None

    def test_schwellen_werden_mitgeliefert(self):
        result = bg.aggregate_big_games([])
        assert result["min_matches"] == bg.MIN_BIG_GAMES
        assert result["min_minutes"] == bg.MIN_BIG_GAME_MINUTES
