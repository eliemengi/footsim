"""
Big Game Rating V2: Zulassung, Gewichtung, Bewertung, Huerden (Block V2-BG).

Alle Tests laufen OHNE private Daten. Die Regeltests erzeugen ihre
Spielzeilen von Hand; die Listentests am Ende arbeiten auf einer
vollstaendig synthetischen Welt (tests/big_games_v2_welt.py) mit eigenen
Snapshots, eigenem Datensatz und eigenem oeffentlichen Artefakt.

Damit prueft die CI denselben Rechenweg wie der Entwicklerrechner - und
die Fail-Closed-Eigenschaft bleibt in TestFailClosed ausdruecklich
scharf gestellt.
"""

import json
import os

import pytest

from src.features import big_games as bg
from src.features import big_games_rules as rules
from src.features import big_games_score as score
from src.features import national_big_games as nbg
from tests.big_games_v2_welt import big_games_welt  # noqa: F401


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------

def club_match(stage="league", band=None, league_id=140, minutes=90,
               rating=7.0, goals=None, assists=None, strength=None, **rest):
    """Eine Vereins-Spielzeile in der Form des Datensatzes."""
    if strength is None:
        strength = 1.0 if band is None else 1.5 - (band / 100.0)
    return {
        "source": "club", "league_id": league_id, "stage": stage,
        "opponent_band": band, "minutes": minutes, "rating": rating,
        "strength": strength, "importance": bg.match_importance(stage),
        "goals": goals, "assists": assists, **rest,
    }


def national_match(stage="group", band=None, league_id=1, minutes=90,
                   rating=7.0, goals=None, assists=None, **rest):
    return {
        "source": "national", "league_id": league_id, "stage": stage,
        "opponent_band": band, "minutes": minutes, "rating": rating,
        "strength": nbg.national_opponent_strength(band),
        "importance": nbg.national_match_importance(league_id, stage),
        "goals": goals, "assists": assists, **rest,
    }


# ---------------------------------------------------------------------------
# 4./5./6. Gegnerhuerde, Runde und Gewicht
# ---------------------------------------------------------------------------

class TestGegnerhuerde:

    def test_die_stufen_sind_begrenzt(self):
        """Es gibt keine Stufe jenseits der belegten Listen."""
        assert bg.UEFA_RANK_BANDS[-1] == 30
        assert nbg.FIFA_RANK_BANDS[-1] == 20
        assert rules.clamp_uefa_max_rank(75) == 30
        assert rules.clamp_fifa_max_rank(40) == 20
        assert rules.clamp_uefa_max_rank(None) == bg.DEFAULT_UEFA_MAX_RANK
        assert rules.clamp_fifa_max_rank(None) == nbg.DEFAULT_FIFA_MAX_RANK

    @pytest.mark.parametrize("huerde", bg.UEFA_RANK_BANDS)
    def test_jede_uefa_stufe_ist_waehlbar(self, huerde):
        assert rules.clamp_uefa_max_rank(huerde) == huerde

    @pytest.mark.parametrize("huerde", nbg.FIFA_RANK_BANDS)
    def test_jede_fifa_stufe_ist_waehlbar(self, huerde):
        assert rules.clamp_fifa_max_rank(huerde) == huerde

    def test_das_band_bildet_den_rang_ab(self):
        assert bg.rank_band(1) == 5
        assert bg.rank_band(5) == 5
        assert bg.rank_band(6) == 10
        assert bg.rank_band(30) == 30
        assert bg.rank_band(31) is None
        assert bg.rank_band(None) is None

    def test_ein_ligaspiel_haengt_allein_am_gegner(self):
        spiel = club_match(stage="league", band=10)
        assert rules.resolve_match(spiel, 10, 20)["qualifies"] is True
        assert rules.resolve_match(spiel, 5, 20)["qualifies"] is False

    def test_eine_engere_huerde_entfernt_kein_rundenspiel(self):
        """Die zentrale Regel: Runde und Gegner sind unabhaengig."""
        for spiel in (club_match(stage="final", league_id=2, band=None),
                      national_match(stage="final", league_id=1, band=None)):
            eng = rules.resolve_match(spiel, 5, 5)
            assert eng["qualifies"] is True
            assert eng["reasons"] == ["stage"]

    def test_ausserhalb_der_huerde_gibt_es_keinen_elitebonus(self):
        """Zaehlen ja - aber ohne Staerkebonus, und nie mit Abzug."""
        spiel = club_match(stage="final", league_id=2, band=30, strength=1.45)
        weit = rules.resolve_match(spiel, 30, 20)
        eng = rules.resolve_match(spiel, 5, 20)
        assert weit["strength"] == pytest.approx(1.45)
        assert eng["qualifies"] is True
        assert eng["strength"] == rules.NEUTRAL_STRENGTH == 1.00
        assert eng["weight"] < weit["weight"]

    def test_die_huerde_veraendert_die_zugelassene_menge(self):
        spiele = [club_match(band=5), club_match(band=20), club_match(band=30)]
        assert len(rules.qualified_matches(spiele, 30, 20)) == 3
        assert len(rules.qualified_matches(spiele, 20, 20)) == 2
        assert len(rules.qualified_matches(spiele, 5, 20)) == 1


class TestRundeUndWettbewerb:

    def test_die_champions_league_steigert_sich_bis_zum_finale(self):
        vorher = None
        for stage in ("playoff", "round_of_16", "quarterfinal",
                      "semifinal", "final"):
            spiel = club_match(stage=stage, league_id=2, band=5)
            gewicht = rules.resolve_match(spiel, 5, 20)["weight"]
            if vorher is not None:
                assert gewicht > vorher, stage
            vorher = gewicht

    def test_europa_und_conference_wiegen_weniger_als_die_koenigsklasse(self):
        def gewicht(league_id):
            spiel = club_match(stage="semifinal", league_id=league_id, band=None)
            return rules.resolve_match(spiel, 30, 20)["weight"]
        assert gewicht(2) > gewicht(3) > gewicht(848)

    def test_ein_pokalfinale_zaehlt_immer(self):
        spiel = club_match(stage="final", league_id=81, band=None)
        assert rules.resolve_match(spiel, 5, 20)["qualifies"] is True

    def test_ein_pokalhalbfinale_braucht_den_gegner(self):
        """Ein Halbfinale ist nicht automatisch ein CL-Halbfinale."""
        schwach = club_match(stage="semifinal", league_id=81, band=None)
        stark = club_match(stage="semifinal", league_id=81, band=5)
        assert rules.resolve_match(schwach, 30, 20)["qualifies"] is False
        assert rules.resolve_match(stark, 5, 20)["qualifies"] is True

    def test_ein_supercup_zaehlt_bleibt_aber_unter_der_koenigsklasse(self):
        supercup = club_match(stage="final", league_id=556, band=None)
        cl_finale = club_match(stage="final", league_id=2, band=5)
        assert rules.resolve_match(supercup, 5, 20)["qualifies"] is True
        assert (rules.resolve_match(supercup, 30, 20)["weight"]
                < rules.resolve_match(cl_finale, 5, 20)["weight"])


class TestNationalmannschaften:

    def test_wm_halbfinale_und_finale_zaehlen_ohne_gegnerbonus(self):
        for stage in ("semifinal", "final"):
            spiel = national_match(stage=stage, league_id=1, band=None)
            ergebnis = rules.resolve_match(spiel, 30, 5)
            assert ergebnis["qualifies"] is True
            assert ergebnis["strength"] == 1.00

    def test_ein_starker_gegner_bringt_den_bonus(self):
        spiel = national_match(stage="semifinal", league_id=1, band=5)
        ergebnis = rules.resolve_match(spiel, 30, 20)
        assert ergebnis["qualifies"] is True
        assert ergebnis["strength"] > 1.00
        assert "opponent" in ergebnis["reasons"]

    # --- Die behobene Ungleichbehandlung ---------------------------------
    #
    # Vorher: ein nationales Pokalfinale qualifizierte sich immer ueber die
    # Runde, ein AFCON-FINALE gegen einen Gegner ausserhalb der FIFA-Top-20
    # dagegen ueberhaupt nicht.

    @pytest.mark.parametrize("competition_id", sorted(
        nbg.CONTINENTAL_CHAMPIONSHIP_COMPETITION_IDS))
    def test_ein_kontinentales_finale_zaehlt_auch_gegen_schwache_gegner(
            self, competition_id):
        spiel = national_match(stage="final", league_id=competition_id, band=None)
        assert rules.resolve_match(spiel, 30, 20)["qualifies"] is True

    @pytest.mark.parametrize("competition_id", sorted(
        nbg.CONTINENTAL_CHAMPIONSHIP_COMPETITION_IDS))
    def test_ein_kontinentales_halbfinale_zaehlt_ueber_die_runde(
            self, competition_id):
        spiel = national_match(stage="semifinal", league_id=competition_id,
                               band=None)
        assert rules.resolve_match(spiel, 30, 20)["qualifies"] is True

    def test_ein_kontinentales_achtelfinale_zaehlt_nicht_allein(self):
        """Nigeria - Uganda im Achtelfinale ist kein Big Game."""
        spiel = national_match(stage="round_of_16", league_id=6, band=None)
        assert rules.resolve_match(spiel, 30, 20)["qualifies"] is False

    def test_ein_kontinentales_achtelfinale_zaehlt_mit_starkem_gegner(self):
        spiel = national_match(stage="round_of_16", league_id=6, band=20)
        assert rules.resolve_match(spiel, 30, 20)["qualifies"] is True

    def test_ein_schwaecherer_gegner_wiegt_weniger_als_ein_top_gegner(self):
        schwach = national_match(stage="semifinal", league_id=6, band=None)
        stark = national_match(stage="semifinal", league_id=6, band=5)
        assert (rules.resolve_match(stark, 30, 20)["weight"]
                > rules.resolve_match(schwach, 30, 20)["weight"])

    def test_keine_konfoederation_wird_abgewertet(self):
        """
        Gleiche Runde, gleich starker Gegner, verschiedene Turniere:
        gleiches Gewicht. Es gibt bewusst keinen Prestigefaktor je
        Konfoederation - nur Runde und Gegnerstaerke entscheiden.
        """
        gewichte = {
            wettbewerb: rules.resolve_match(
                national_match(stage="final", league_id=wettbewerb, band=5),
                30, 20)["weight"]
            for wettbewerb in (1, 4, 6, 7, 9, 22)
        }
        assert len(set(round(g, 10) for g in gewichte.values())) == 1, gewichte


# ---------------------------------------------------------------------------
# 7. Tore und Vorlagen bestimmen die Rangfolge mit
# ---------------------------------------------------------------------------

def population(spieler):
    """(Liste fuer score_population, Zuordnung Name -> Ergebnis)."""
    eintraege = [
        {"player_id": i, "position": pos,
         "inputs": score.player_inputs(matches)}
        for i, (name, pos, matches) in enumerate(spieler)
    ]
    ergebnis = score.score_population(eintraege)
    return {spieler[i][0]: ergebnis[i] for i in range(len(spieler))}


def serie(n, rating, goals=0, assists=0, band=5, minutes=90):
    """
    n gleichartige Big Games; Tore/Vorlagen auf die ersten Spiele verteilt.

    Die Kodierung folgt dem echten Anbieter (an den gesammelten Daten
    geprueft): ein Spiel OHNE Tor traegt goals=None, ein Spiel ohne
    Vorlage dagegen ausdruecklich assists=0. Damit ist "nichts
    produziert" eine gemessene Null und kein fehlender Wert - genau der
    Unterschied, an dem die Bewertung haengt.
    """
    spiele = []
    for i in range(n):
        spiele.append(club_match(
            band=band, minutes=minutes, rating=rating,
            goals=1 if i < goals else None,
            assists=1 if i < assists else 0,
            shots_on=2, passes_key=2, passes_total=40, tackles=1,
            interceptions=1, duels_won=5, duels_total=10,
            dribbles_success=2, saves=None, goals_conceded=None))
    return spiele


class TestTorbeteiligungen:

    def test_tor_und_vorlage_zaehlen_gleich(self):
        """Ein Tor ist genau so viel wert wie eine Vorlage - 1:1."""
        nur_tore = score.player_inputs(serie(10, 7.0, goals=4))
        nur_vorlagen = score.player_inputs(serie(10, 7.0, assists=4))
        assert (nur_tore["metrics"][score.METRIC_GA]
                == pytest.approx(nur_vorlagen["metrics"][score.METRIC_GA]))

    def test_torbeteiligungen_veraendern_den_score(self):
        """Der Kern der Aenderung: G+A wirkt sich auf die Rangfolge aus."""
        feld = [(f"fuell{i}", "Attacker", serie(10, 7.0, goals=i % 4))
                for i in range(12)]
        mit = population(feld + [("mit", "Attacker", serie(10, 7.0, goals=6))])
        ohne = population(feld + [("ohne", "Attacker", serie(10, 7.0, goals=0))])
        assert mit["mit"]["score"] > ohne["ohne"]["score"]

    def test_zwei_torbeteiligungen_schlagen_eine_bessere_note(self):
        """
        DIE PRODUKTREGEL: objektives Ergebnis vor Anbieterbewertung.

        Spieler B: 1 Tor + 1 Vorlage bei Note 7,4
        Spieler A: keine Torbeteiligung bei Note 8,0
        -> B muss vorn liegen.
        """
        feld = [(f"fuell{i}", "Attacker", serie(10, 6.8 + (i % 5) * 0.2,
                                                goals=i % 3))
                for i in range(15)]
        ergebnis = population(feld + [
            ("A", "Attacker", serie(10, 8.0, goals=0, assists=0)),
            ("B", "Attacker", serie(10, 7.4, goals=1, assists=1)),
        ])
        assert ergebnis["B"]["score"] > ergebnis["A"]["score"]

    def test_die_bewertung_bleibt_sekundaer(self):
        """Keine Position darf die Anbieterbewertung dominieren lassen."""
        for position, profil in score.POSITION_PROFILES.items():
            anteil = profil.get(score.METRIC_RATING, 0.0)
            assert anteil <= score.MAX_RATING_SHARE, position
            assert abs(sum(profil.values()) - 1.0) < 1e-9, position


class TestPositionen:

    def test_jede_position_hat_ein_eigenes_profil(self):
        assert set(score.POSITION_PROFILES) == {
            "Attacker", "Midfielder", "Defender", "Goalkeeper"}
        assert score.profile_for("Attacker") != score.profile_for("Goalkeeper")

    def test_torhueter_brauchen_keine_torbeteiligungen(self):
        """Ein Torhueter kommt ueber Paraden und Gegentore nach oben."""
        feld = [(f"gk{i}", "Goalkeeper", [
            club_match(band=5, rating=6.8, saves=2, goals_conceded=2)
            for _ in range(10)]) for i in range(10)]
        stark = [club_match(band=5, rating=6.8, saves=6, goals_conceded=0)
                 for _ in range(10)]
        ergebnis = population(feld + [("stark", "Goalkeeper", stark)])
        assert ergebnis["stark"]["score"] > max(
            ergebnis[f"gk{i}"]["score"] for i in range(10))

    def test_verteidiger_kommen_ueber_defensivarbeit_nach_oben(self):
        feld = [(f"def{i}", "Defender", [
            club_match(band=5, rating=6.8, tackles=1, interceptions=1,
                       duels_won=3, duels_total=8, passes_total=40)
            for _ in range(10)]) for i in range(10)]
        stark = [club_match(band=5, rating=6.8, tackles=5, interceptions=4,
                            duels_won=9, duels_total=12, passes_total=60)
                 for _ in range(10)]
        ergebnis = population(feld + [("stark", "Defender", stark)])
        assert ergebnis["stark"]["score"] > max(
            ergebnis[f"def{i}"]["score"] for i in range(10))

    def test_gegentore_sind_umgekehrt_zu_lesen(self):
        assert score.METRIC_CONCEDED in score.LOWER_IS_BETTER


class TestNormalisierung:

    def test_median_und_mad_statt_mittelwert(self):
        lage, streuung = score.robust_center_scale([1, 2, 3, 4, 100])
        assert lage == 3
        assert streuung > 0
        # Der Ausreisser verschiebt die Lage nicht.
        assert lage == score.robust_center_scale([1, 2, 3, 4, 5])[0]

    def test_ohne_streuung_entscheidet_die_kennzahl_nichts(self):
        lage, streuung = score.robust_center_scale([7, 7, 7, 7])
        assert streuung == 0
        assert score.robust_z(9, lage, streuung) == 0.0

    def test_fehlende_werte_sind_neutral(self):
        assert score.robust_z(None, 5, 2) == 0.0

    def test_normalisiert_wird_innerhalb_der_position(self):
        """
        Ein Torhueterfeld mit hohen Noten darf die Angreifer nicht
        benachteiligen - beide werden an ihrer eigenen Gruppe gemessen.
        """
        torhueter = [(f"gk{i}", "Goalkeeper",
                      serie(10, 7.6, band=5)) for i in range(10)]
        angreifer = [(f"att{i}", "Attacker",
                      serie(10, 6.6, band=5)) for i in range(10)]
        ergebnis = population(torhueter + angreifer)
        gk = [ergebnis[f"gk{i}"]["score"] for i in range(10)]
        att = [ergebnis[f"att{i}"]["score"] for i in range(10)]
        # Beide Gruppen liegen um die Mitte der Skala, nicht auseinander.
        assert abs(sum(gk) / len(gk) - sum(att) / len(att)) < 5.0


# ---------------------------------------------------------------------------
# 10./11. Kleine Stichproben, Schrumpfung, Rate und Umfang
# ---------------------------------------------------------------------------

class TestZulassung:

    def test_die_schwelle_ist_fuenf_spiele_und_450_minuten(self):
        assert score.RANKING_MIN_BIG_GAMES == 5
        assert score.RANKING_MIN_MINUTES == 450

    @pytest.mark.parametrize("spiele,minuten,erwartet", [
        (1, 90, False),
        (3, 270, False),
        (4, 450, False),      # Spiele fehlen
        (5, 400, False),      # Minuten fehlen
        (5, 450, True),
        (10, 900, True),
    ])
    def test_zulassung(self, spiele, minuten, erwartet):
        assert score.is_rankable(spiele, minuten) is erwartet

    def test_ein_bis_drei_spiele_kommen_nicht_in_die_wertung(self):
        """Die Kunstfaelle aus der Analyse - sie duerfen nicht ranken."""
        for spiele, tore in ((1, 3), (3, 3)):
            eingaben = score.player_inputs(serie(spiele, 9.5, goals=tore))
            assert score.is_rankable(
                eingaben["matches"], eingaben["minutes"]) is False

    def test_zehn_und_zwanzig_spiele_werden_gewertet(self):
        for spiele, tore in ((10, 6), (20, 10)):
            eingaben = score.player_inputs(serie(spiele, 7.2, goals=tore))
            assert score.is_rankable(
                eingaben["matches"], eingaben["minutes"]) is True


class TestSchrumpfung:

    def test_der_faktor_folgt_n_durch_n_plus_k(self):
        assert score.SHRINKAGE_K == 8.0
        feld = [(f"f{i}", "Attacker", serie(10, 7.0, goals=i % 4))
                for i in range(10)]
        ergebnis = population(feld + [("knapp", "Attacker", serie(5, 9.5, goals=5))])
        teil = ergebnis["knapp"]
        erwartet = teil["weighted_90s"] / (teil["weighted_90s"] + score.SHRINKAGE_K)
        assert teil["shrinkage"] == pytest.approx(erwartet, abs=1e-3)

    def test_eine_kleine_stichprobe_wird_staerker_gezogen(self):
        feld = [(f"f{i}", "Attacker", serie(12, 7.0, goals=i % 4))
                for i in range(10)]
        ergebnis = population(feld + [
            ("klein", "Attacker", serie(5, 9.5, goals=5)),
            ("gross", "Attacker", serie(25, 9.5, goals=25)),
        ])
        assert ergebnis["klein"]["shrinkage"] < ergebnis["gross"]["shrinkage"]
        assert ergebnis["gross"]["score"] > ergebnis["klein"]["score"]


class TestRateUndUmfang:

    def test_die_mischung_ist_65_zu_35(self):
        assert score.RATE_SHARE == pytest.approx(0.65)
        assert score.VOLUME_SHARE == pytest.approx(0.35)
        assert score.RATE_SHARE + score.VOLUME_SHARE == pytest.approx(1.0)

    def test_umfang_wird_belohnt_aber_rettet_keine_schwaeche(self):
        feld = [(f"f{i}", "Attacker", serie(12, 7.0, goals=i % 5))
                for i in range(12)]
        ergebnis = population(feld + [
            ("viel_schwach", "Attacker", serie(30, 6.2, goals=0)),
            ("wenig_stark", "Attacker", serie(8, 7.8, goals=6)),
        ])
        # Viel Masse allein setzt sich nicht gegen klare Klasse durch.
        assert ergebnis["wenig_stark"]["score"] > ergebnis["viel_schwach"]["score"]

    def test_bei_gleicher_klasse_entscheidet_der_umfang(self):
        feld = [(f"f{i}", "Attacker", serie(12, 7.0, goals=i % 4))
                for i in range(12)]
        ergebnis = population(feld + [
            ("acht", "Attacker", serie(8, 7.5, goals=4)),
            ("zwanzig", "Attacker", serie(20, 7.5, goals=10)),
        ])
        assert ergebnis["zwanzig"]["score"] > ergebnis["acht"]["score"]


# ---------------------------------------------------------------------------
# Die vollstaendige Bestenliste - auf einer hermetischen Welt
# ---------------------------------------------------------------------------
#
# GEAENDERT FUER DIE CI: Bis hierher liefen diese Tests gegen den ECHTEN
# gesammelten Datensatz und uebersprangen sich, wenn er fehlte. Auf einem
# frischen Checkout liegt zwar das versionierte oeffentliche Artefakt vor,
# nicht aber die bewusst unversionierten UEFA-/FIFA-Snapshots - die Liste
# fiel dort also voellig richtig auf "snapshot_missing" zurueck, und die
# Tests scheiterten an der Umgebung statt an der Anwendung.
#
# Sie arbeiten jetzt auf einer selbstgebauten Welt (siehe
# tests/big_games_v2_welt.py): eigene Snapshots, eigener Datensatz,
# eigenes Artefakt, alles in tmp_path. Derselbe Rechenweg, ueberall.
#
# Dass eine Liste OHNE Snapshots geschlossen bleibt, pruefen die Tests in
# TestFailClosed weiter unten - ausdruecklich und unveraendert scharf.


@pytest.mark.usefixtures("big_games_welt")
class TestVollstaendigeBestenliste:

    def test_die_vollstaendige_saison_ist_verfuegbar(self):
        from src.data import big_games_dataset as bgd
        ergebnis = bgd.big_games_leaderboard(2025, 2025, "all", 20)
        assert ergebnis["available"] is True, ergebnis.get("reason")
        assert len(ergebnis["rows"]) == 20

    def test_die_liste_traegt_tore_und_vorlagen(self):
        from src.data import big_games_dataset as bgd
        ergebnis = bgd.big_games_leaderboard(2025, 2025, "all", 10)
        for zeile in ergebnis["rows"]:
            assert "goals" in zeile and "assists" in zeile
            assert zeile["big_games"] >= score.RANKING_MIN_BIG_GAMES
            assert zeile["minutes"] >= score.RANKING_MIN_MINUTES
            # Angezeigt wird eine echte Note, kein Rechenwert ueber 10.
            assert zeile["rating"] is None or 0 <= zeile["rating"] <= 10

    def test_die_laenge_der_liste_wird_eingehalten(self):
        from src.data import big_games_dataset as bgd
        for limit in (5, 10, 15, 20, 30):
            ergebnis = bgd.big_games_leaderboard(2025, 2025, "all", limit)
            assert len(ergebnis["rows"]) <= limit

    def test_eine_engere_huerde_rechnet_wirklich_neu(self):
        """
        Nicht nur ein anderes Etikett: weniger zugelassene Spieler UND
        weniger Big Games bei denselben Spielern.
        """
        from src.data import big_games_dataset as bgd
        weit = bgd.big_games_leaderboard(2025, 2025, "all", 20,
                                         uefa_max_rank=30, fifa_max_rank=20)
        eng = bgd.big_games_leaderboard(2025, 2025, "all", 20,
                                        uefa_max_rank=5, fifa_max_rank=5)
        assert eng["coverage"]["eligible"] < weit["coverage"]["eligible"]
        assert eng["opponent_cutoffs"]["uefa_max_rank"] == 5
        assert eng["opponent_cutoffs"]["fifa_max_rank"] == 5

        weit_bg = {z["player_id"]: z["big_games"] for z in weit["rows"]}
        eng_bg = {z["player_id"]: z["big_games"] for z in eng["rows"]}
        gemeinsam = set(weit_bg) & set(eng_bg)
        assert gemeinsam, "kein gemeinsamer Spieler zum Vergleich"
        assert all(eng_bg[p] <= weit_bg[p] for p in gemeinsam)
        assert any(eng_bg[p] < weit_bg[p] for p in gemeinsam)

    def test_die_reihenfolge_ist_deterministisch(self):
        from src.data import big_games_dataset as bgd
        erst = bgd.big_games_leaderboard(2025, 2025, "all", 20)
        zweit = bgd.big_games_leaderboard(2025, 2025, "all", 20)
        assert [z["player_id"] for z in erst["rows"]] == \
               [z["player_id"] for z in zweit["rows"]]

    def test_ein_fehlender_datensatz_bleibt_nicht_verfuegbar(self, monkeypatch):
        """Die Sicherheitseigenschaft bleibt: kein Datensatz, keine Liste."""
        from src.data import big_games_dataset as bgd
        from src.data import big_games_public as bgp
        monkeypatch.setattr(bgd, "dataset_path", lambda s: "/nicht/vorhanden.json")
        monkeypatch.setattr(bgp, "public_path", lambda s: "/nicht/vorhanden.json")
        ergebnis = bgd.big_games_leaderboard(2025, 2025, "all", 20)
        assert ergebnis["available"] is False
        assert ergebnis["reason"] == bgd.REASON_DATASET_MISSING
        assert ergebnis["rows"] == []

    def test_ein_unvollstaendiger_zeitraum_bleibt_geschlossen(self):
        """Eine Saison ohne Datensatz macht den ganzen Zeitraum ungueltig."""
        from src.data import big_games_dataset as bgd
        ergebnis = bgd.big_games_leaderboard(2024, 2025, "all", 20)
        assert ergebnis["available"] is False
        assert ergebnis["rows"] == []

    def test_das_oeffentliche_artefakt_ergibt_dieselbe_liste(self):
        from src.data import big_games_dataset as bgd
        from src.data import big_games_public as bgp

        privat = bgd.big_games_leaderboard(2025, 2025, "all", 20)
        echt = bgd.dataset_path
        bgd.dataset_path = lambda s: echt(s) + ".fehlt"
        try:
            oeffentlich = bgd.big_games_leaderboard(2025, 2025, "all", 20)
        finally:
            bgd.dataset_path = echt

        assert oeffentlich["available"] is True, oeffentlich.get("reason")
        assert ([(z["rank"], z["player_id"], z["value"]) for z in privat["rows"]]
                == [(z["rank"], z["player_id"], z["value"])
                    for z in oeffentlich["rows"]])

    def test_das_artefakt_enthaelt_keine_raenge(self):
        """Die privaten Listen bleiben privat - nur Baender sind drin."""
        from src.data import big_games_public as bgp
        import json
        with open(bgp.public_path(2025), encoding="utf-8") as datei:
            roh = json.load(datei)
        assert "opponent_rank" not in roh.get("match_fields", [])
        assert "opponent_coefficient" not in roh.get("match_fields", [])
        assert "opponent_band" in roh.get("match_fields", [])
        baender = set(bg.UEFA_RANK_BANDS) | set(nbg.FIFA_RANK_BANDS) | {None}
        stelle = roh["match_fields"].index("opponent_band")
        for spieler in roh["players"][:200]:
            for spiel in spieler["matches"]:
                assert spiel[stelle] in baender


# ---------------------------------------------------------------------------
# Fail closed: ohne belegte Grundlage gibt es keine Liste
# ---------------------------------------------------------------------------
#
# Diese Klasse haelt genau die Eigenschaft fest, an der die CI die
# frueheren Tests hat scheitern lassen - und die dabei voellig richtig
# gearbeitet hat: Fehlen die privaten Snapshots, bleibt die Bestenliste
# zu. Sie darf durch keinen Testaufbau umgangen werden.


class TestFailClosed:

    def test_ohne_snapshots_bleibt_die_liste_zu(self, tmp_path, monkeypatch):
        """
        Der Fall der CI: ein Datensatz liegt vor, die historischen
        Snapshots fehlen. Dann ist die Rangfolge nicht belegbar.
        """
        from tests import big_games_v2_welt as welt
        from src.data import big_games_dataset as bgd
        from src.data import fifa_rankings
        from src.data import uefa_coefficients as uc

        welt.baue(tmp_path, monkeypatch)
        # Der Datensatz bleibt liegen, nur die Snapshots verschwinden.
        monkeypatch.setattr(uc, "COEFFICIENT_DIR", str(tmp_path / "weg"))
        monkeypatch.setattr(fifa_rankings, "FIFA_RANKING_DIR", str(tmp_path / "weg"))
        uc.clear_cache()
        fifa_rankings.clear_cache()

        ergebnis = bgd.big_games_leaderboard(2025, 2025, "all", 20)
        assert ergebnis["available"] is False
        assert ergebnis["reason"] == bgd.REASON_SNAPSHOT_MISSING
        assert ergebnis["rows"] == []

    def test_ein_ausgetauschter_snapshot_schliesst_die_liste(
            self, tmp_path, monkeypatch):
        """Ein anderer Snapshot als der, mit dem gebaut wurde: fail closed."""
        import json

        from tests import big_games_v2_welt as welt
        from src.data import big_games_dataset as bgd
        from src.data import uefa_coefficients as uc

        welt.baue(tmp_path, monkeypatch)

        veraendert = welt.uefa_snapshot()
        veraendert["clubs"][0]["total_coefficient"] = 999.0
        (tmp_path / "coeff" / "uefa_coefficients_2025_26.json").write_text(
            json.dumps(veraendert), encoding="utf-8")
        uc.clear_cache()

        ergebnis = bgd.big_games_leaderboard(2025, 2025, "all", 20)
        assert ergebnis["available"] is False
        assert ergebnis["reason"] == bgd.REASON_SNAPSHOT_CHANGED
        assert ergebnis["rows"] == []

    def test_ohne_datensatz_bleibt_die_liste_zu(self, tmp_path, monkeypatch):
        """Snapshots allein genuegen nicht - der Datensatz muss vorliegen."""
        from tests import big_games_v2_welt as welt
        from src.data import big_games_dataset as bgd
        from src.data import big_games_public as bgp

        welt.baue(tmp_path, monkeypatch, mit_artefakt=False)
        monkeypatch.setattr(bgd, "DATASET_DIR", str(tmp_path / "leer"))
        monkeypatch.setattr(bgp, "PUBLIC_DIR", str(tmp_path / "leer"))
        bgd.clear_document_memo()

        ergebnis = bgd.big_games_leaderboard(2025, 2025, "all", 20)
        assert ergebnis["available"] is False
        assert ergebnis["reason"] == bgd.REASON_DATASET_MISSING
        assert ergebnis["rows"] == []


# ---------------------------------------------------------------------------
# Detailauszug: die Begruendung einer Bestenlistenzeile
# ---------------------------------------------------------------------------
#
# Die eine Aussage, die diese Klasse traegt: die Detailansicht zeigt GENAU
# die Partien, die die Liste gezaehlt hat. Beide gehen durch
# qualified_player_matches - deshalb ist die Gleichheit keine Zusicherung,
# die jemand pflegen muss, sondern eine Folge davon, dass es nur einen
# Rechenweg gibt.


@pytest.mark.usefixtures("big_games_welt")
class TestDetailauszug:

    def _detail(self, player_id, uefa=30, fifa=20):
        from src.data import big_games_dataset as bgd
        return bgd.player_match_details(2025, 2025, player_id,
                                        uefa_max_rank=uefa, fifa_max_rank=fifa)

    def _liste(self, uefa=30, fifa=20, limit=30):
        from src.data import big_games_dataset as bgd
        return bgd.big_games_leaderboard(2025, 2025, "all", limit,
                                         uefa_max_rank=uefa, fifa_max_rank=fifa)

    def test_die_partien_sind_erzaehlbar(self):
        """Gegen wen, wo, wie ausgegangen - sonst ist es nur eine Zahl."""
        zeile = self._liste()["rows"][0]
        detail = self._detail(zeile["player_id"])
        assert detail["available"] is True, detail.get("reason")
        assert detail["matches"]

        for partie in detail["matches"]:
            assert partie["opponent_name"]
            assert partie["competition"]
            assert partie["is_home"] in (True, False)
            assert partie["goals_for"] is not None
            assert partie["goals_against"] is not None
            assert partie["minutes"]
            assert partie["date"]

    @pytest.mark.parametrize("uefa,fifa", [(30, 20), (20, 20), (5, 10), (5, 5)])
    def test_die_zahl_stimmt_mit_der_zeile_ueberein(self, uefa, fifa):
        """
        DER KERNVERTRAG. Die Zeile sagt "N Big Games" - der Auszug zeigt
        genau diese N Partien, unter JEDER Huerde.
        """
        liste = self._liste(uefa, fifa)
        assert liste["rows"], "Bestenliste ist leer - Test waere wertlos"
        for zeile in liste["rows"][:8]:
            detail = self._detail(zeile["player_id"], uefa, fifa)
            assert detail["available"] is True
            assert len(detail["matches"]) == zeile["big_games"]
            assert detail["summary"]["big_games"] == zeile["big_games"]

    def test_eine_engere_huerde_laesst_partien_wegfallen(self):
        weit = self._liste(30, 20)
        spieler = weit["rows"][0]["player_id"]
        viele = self._detail(spieler, 30, 20)
        wenige = self._detail(spieler, 5, 5)
        assert len(wenige["matches"]) < len(viele["matches"])
        # Es verschwinden nur Partien, es kommen keine dazu.
        weite_ids = {m["fixture_id"] for m in viele["matches"]}
        enge_ids = {m["fixture_id"] for m in wenige["matches"]}
        assert enge_ids.issubset(weite_ids)

    def test_die_summen_stammen_aus_derselben_liste(self):
        zeile = self._liste()["rows"][0]
        detail = self._detail(zeile["player_id"])
        summe = detail["summary"]
        assert summe["minutes"] == sum(m["minutes"] for m in detail["matches"])
        assert summe["matches_with_goal_contribution"] == sum(
            1 for m in detail["matches"]
            if (m["goals"] or 0) > 0 or (m["assists"] or 0) > 0)

    def test_neueste_partie_zuerst(self):
        zeile = self._liste()["rows"][0]
        daten = [m["date"] for m in self._detail(zeile["player_id"])["matches"]]
        assert daten == sorted(daten, reverse=True)

    def test_kein_big_game_score_im_auszug(self):
        """
        Der Score entsteht aus der ganzen Population. Ihn hier einzeln
        nachzurechnen hiesse, die komplette Liste neu zu bauen.
        """
        zeile = self._liste()["rows"][0]
        detail = self._detail(zeile["player_id"])
        assert "value" not in detail["summary"]
        assert "big_game_score" not in json.dumps(detail)

    def test_der_auszug_gibt_keine_privaten_rangdaten_preis(self):
        zeile = self._liste()["rows"][0]
        text = json.dumps(self._detail(zeile["player_id"]))
        for verboten in ("opponent_rank", "opponent_coefficient", "coefficient",
                         "strength", "weight", "importance", "opponent_band"):
            assert verboten not in text, verboten

    def test_ein_unbekannter_spieler_erfindet_nichts(self):
        detail = self._detail(999999999)
        assert detail["available"] is False
        assert detail["reason"] == "player_not_in_dataset"
        assert detail["matches"] == []

    def test_ohne_snapshots_bleibt_der_auszug_zu(self, tmp_path, monkeypatch):
        from src.data import fifa_rankings
        from src.data import uefa_coefficients as uc

        spieler = self._liste()["rows"][0]["player_id"]
        monkeypatch.setattr(uc, "COEFFICIENT_DIR", str(tmp_path / "weg"))
        monkeypatch.setattr(fifa_rankings, "FIFA_RANKING_DIR", str(tmp_path / "weg"))
        uc.clear_cache()
        fifa_rankings.clear_cache()

        detail = self._detail(spieler)
        assert detail["available"] is False
        assert detail["reason"] == "snapshot_missing"
        assert detail["matches"] == []


# ---------------------------------------------------------------------------
# Big-Game-Definition: kontextuell gegen streng
# ---------------------------------------------------------------------------
#
# Die Trennung behebt eine Bedeutungsluecke. Bisher liess eine gewaehlte
# Huerde ("FIFA Top 5") auch Partien gegen Gegner AUSSERHALB der Top 5
# mitzaehlen, sobald die Runde gross genug war. Kontextuell ist das
# richtig - ein WM-Achtelfinale bleibt ein grosses Spiel. Unter einer
# ausdruecklich gewaehlten Gegnergrenze ist es aber eine falsche
# Behauptung. Deshalb zwei Modi, aber ein Rechenweg.


class TestBigGameDefinition:

    def _wm_achtelfinale_gegen_schwachen_gegner(self):
        """WM-K.o. gegen einen Gegner ohne Band - der strittige Fall."""
        return national_match(stage="round_of_16", league_id=1, band=None)

    def test_ohne_angabe_gilt_kontextuell(self):
        """Bestehende Aufrufer duerfen sich nicht veraendern."""
        assert rules.DEFAULT_MODE == rules.MODE_CONTEXTUAL
        assert rules.normalize_mode(None) == rules.MODE_CONTEXTUAL
        spiel = self._wm_achtelfinale_gegen_schwachen_gegner()
        assert rules.resolve_match(spiel, 5, 5)["qualifies"] is True

    def test_kontextuell_laesst_die_runde_qualifizieren(self):
        spiel = self._wm_achtelfinale_gegen_schwachen_gegner()
        ergebnis = rules.resolve_match(spiel, 5, 5, rules.MODE_CONTEXTUAL)
        assert ergebnis["qualifies"] is True
        assert ergebnis["reasons"] == ["stage"]

    def test_streng_laesst_dieselbe_partie_herausfallen(self):
        """Der Kern der Trennung: dieselbe Partie, andere Frage."""
        spiel = self._wm_achtelfinale_gegen_schwachen_gegner()
        ergebnis = rules.resolve_match(spiel, 5, 5, rules.MODE_STRICT)
        assert ergebnis["qualifies"] is False
        # Die Begruendung bleibt wahr: es WAR ein K.-o.-Spiel. Nur
        # qualifiziert sie hier eben nicht mehr.
        assert ergebnis["reasons"] == ["stage"]

    @pytest.mark.parametrize("band,erwartet", [
        (5, True), (10, False), (20, False), (30, False), (None, False)])
    def test_streng_verein_haengt_allein_am_band(self, band, erwartet):
        spiel = club_match(stage="final", league_id=2, band=band)
        assert rules.resolve_match(
            spiel, 5, 5, rules.MODE_STRICT)["qualifies"] is erwartet

    @pytest.mark.parametrize("band,erwartet", [
        (5, True), (10, False), (20, False), (None, False)])
    def test_streng_national_haengt_allein_am_band(self, band, erwartet):
        spiel = national_match(stage="final", league_id=1, band=band)
        assert rules.resolve_match(
            spiel, 5, 5, rules.MODE_STRICT)["qualifies"] is erwartet

    def test_streng_folgt_der_gewaehlten_stufe(self):
        spiel = club_match(stage="league", band=10)
        assert rules.resolve_match(spiel, 5, 5, rules.MODE_STRICT)["qualifies"] is False
        assert rules.resolve_match(spiel, 10, 5, rules.MODE_STRICT)["qualifies"] is True
        assert rules.resolve_match(spiel, 30, 5, rules.MODE_STRICT)["qualifies"] is True

    def test_die_runde_rettet_im_strengen_modus_niemanden(self):
        """Ueber JEDE qualifizierende Runde hinweg geprueft."""
        for stage in ("round_of_16", "quarterfinal", "semifinal", "final"):
            spiel = club_match(stage=stage, league_id=2, band=None)
            assert rules.resolve_match(spiel, 30, 20)["qualifies"] is True
            assert rules.resolve_match(
                spiel, 30, 20, rules.MODE_STRICT)["qualifies"] is False

    def test_die_gewichtung_bleibt_in_beiden_modi_dieselbe(self):
        """
        Der Modus entscheidet ueber die Zulassung, nicht ueber den Wert.
        Eine in beiden Modi zugelassene Partie muss identisch wiegen -
        sonst waeren die beiden Listen nicht mehr vergleichbar.
        """
        spiel = club_match(stage="final", league_id=2, band=5)
        a = rules.resolve_match(spiel, 5, 5, rules.MODE_CONTEXTUAL)
        b = rules.resolve_match(spiel, 5, 5, rules.MODE_STRICT)
        assert a["qualifies"] is True and b["qualifies"] is True
        for feld in ("weight", "strength", "importance", "factor"):
            assert a[feld] == b[feld], feld

    def test_die_menge_wird_nur_kleiner_nie_groesser(self):
        spiele = [club_match(band=5), club_match(band=20),
                  club_match(stage="final", league_id=2, band=None),
                  national_match(stage="final", league_id=1, band=None)]
        kontext = rules.qualified_matches(spiele, 5, 5)
        streng = rules.qualified_matches(spiele, 5, 5, rules.MODE_STRICT)
        # Band 20 faellt unter der Huerde 5 in BEIDEN Modi weg; die
        # beiden Endspiele ohne Band ueberleben nur kontextuell.
        assert len(kontext) == 3
        assert len(streng) == 1          # allein die Partie gegen Band 5
        assert streng[0]["opponent_band"] == 5

    def test_nur_die_beiden_modi_gelten(self):
        assert rules.is_valid_mode("contextual")
        assert rules.is_valid_mode("strict")
        for unsinn in ("streng", "", "STRICT", "kontextuell", None):
            assert not rules.is_valid_mode(unsinn), unsinn


@pytest.mark.usefixtures("big_games_welt")
class TestDefinitionAufDerBestenliste:
    """Zulassung, Bestenliste und Auszug muessen denselben Modus sehen."""

    def _liste(self, mode, uefa=30, fifa=20, limit=30):
        from src.data import big_games_dataset as bgd
        return bgd.big_games_leaderboard(2025, 2025, "all", limit,
                                         uefa_max_rank=uefa, fifa_max_rank=fifa,
                                         mode=mode)

    def _detail(self, player_id, mode, uefa=30, fifa=20):
        from src.data import big_games_dataset as bgd
        return bgd.player_match_details(2025, 2025, player_id,
                                        uefa_max_rank=uefa, fifa_max_rank=fifa,
                                        mode=mode)

    def test_der_wirksame_modus_steht_in_der_antwort(self):
        assert self._liste(None)["opponent_cutoffs"]["big_game_mode"] == "contextual"
        assert self._liste("strict")["opponent_cutoffs"]["big_game_mode"] == "strict"
        spieler = self._liste(None)["rows"][0]["player_id"]
        assert self._detail(
            spieler, "strict")["opponent_cutoffs"]["big_game_mode"] == "strict"

    def test_streng_laesst_nie_mehr_spieler_zu_als_kontextuell(self):
        kontext = self._liste("contextual")["coverage"]["eligible"]
        streng = self._liste("strict")["coverage"]["eligible"]
        assert streng <= kontext

    @pytest.mark.parametrize("mode", [None, "contextual", "strict"])
    def test_zeile_und_auszug_stimmen_in_jedem_modus_ueberein(self, mode):
        """Derselbe Kernvertrag wie oben - jetzt je Definition."""
        liste = self._liste(mode)
        assert liste["rows"], "Bestenliste ist leer - Test waere wertlos"
        for zeile in liste["rows"][:8]:
            detail = self._detail(zeile["player_id"], mode)
            assert detail["available"] is True, detail.get("reason")
            assert len(detail["matches"]) == zeile["big_games"]
            assert detail["summary"]["big_games"] == zeile["big_games"]

    def test_streng_ist_immer_eine_teilmenge(self):
        for zeile in self._liste("contextual")["rows"][:5]:
            kontext = self._detail(zeile["player_id"], "contextual")
            streng = self._detail(zeile["player_id"], "strict")
            k_ids = {m["fixture_id"] for m in kontext["matches"]}
            s_ids = {m["fixture_id"] for m in streng["matches"]}
            assert s_ids.issubset(k_ids)

    def test_die_mindestmenge_bleibt_unveraendert(self):
        """
        Die strengere Frage darf die Huerde nicht aufweichen, nur damit
        bekannte Namen wieder auftauchen.
        """
        for mode in ("contextual", "strict"):
            liste = self._liste(mode)
            assert liste["eligibility"]["min_matches"] == score.RANKING_MIN_BIG_GAMES
            assert liste["eligibility"]["min_minutes"] == score.RANKING_MIN_MINUTES
            for zeile in liste["rows"]:
                assert zeile["big_games"] >= score.RANKING_MIN_BIG_GAMES
                assert zeile["minutes"] >= score.RANKING_MIN_MINUTES
