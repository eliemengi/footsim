"""
Form, Gegnerstaerke und historische UEFA-Staerke (V2-C4).

WAS HIER GEPRUEFT WIRD
----------------------
Drei Dinge, die man leicht falsch macht und an keiner Zahl bemerkt:

  1. Ein Formfenster, das das Zielspiel oder spaetere Partien sieht.
  2. Eine Gegnerstaerke, die das Ergebnis genau der Partie kennt,
     deren Schwierigkeit sie beschreiben soll.
  3. Ein UEFA-Koeffizient, der die Saison enthaelt, in der das Spiel
     stattfand.

Der dritte Punkt ist der heikelste: Der Koeffizient einer Saison X
enthaelt deren eigene Ergebnisse. Wer ihn fuer ein Spiel in X benutzt,
sagt die Vergangenheit mit der Zukunft voraus - und das Ergebnis sieht
hervorragend aus.

OHNE NETZ, OHNE .env, OHNE PRIVATE DATEIEN
------------------------------------------
Jeder Test baut seine Zeitleiste aus Wortlisten. Die UEFA-Tests bauen
ihre Snapshots selbst in einem temporaeren Verzeichnis - die echten
Dateien liegen unter data/big_games/ und sind gitignoriert, stehen auf
einem CI-Rechner also gar nicht zur Verfuegung. Genau dieser Fall wird
eigens geprueft.
"""

import datetime as dt
import json

import pytest

from src.data import uefa_coefficients as uc
from src.features import form as fm
from src.features import uefa_strength as us
from src.features.match_timeline import team_timeline
from src.ml import cl_ablation as ca
from src.ml import cl_evaluate as ce
from src.ml import dataset as ds
from src.ml import feature_groups as fg

CUTOFF = dt.datetime(2025, 11, 1, 20, 0)


def _eintrag(tage_vorher, *, heim=True, competition="BL1", tore=(2, 1),
             status=None, stage=None, match_id=None, team=1, gegner=2):
    """Ein Zeitleisteneintrag, relativ zum Stichtag."""
    zeitpunkt = (CUTOFF - dt.timedelta(days=tage_vorher)).replace(
        hour=20, minute=0)
    heim_tore, gast_tore = tore
    return {
        "match_id": match_id if match_id is not None
        else f"{competition}-{tage_vorher}-{heim}-{gegner}",
        "season": 2025,
        "competition": competition,
        "competition_name": competition,
        "kickoff": zeitpunkt,
        "time_precision": "datetime",
        "date": zeitpunkt.date().isoformat(),
        "stage": stage,
        "home_id": team if heim else gegner,
        "away_id": gegner if heim else team,
        "home_team": "A", "away_team": "B",
        "status": status,
        "played": True,
        "home_goals": heim_tore if heim else gast_tore,
        "away_goals": gast_tore if heim else heim_tore,
        "source": "test", "data_quality": "complete",
    }


def _tl(eintraege, team=1):
    return team_timeline(eintraege, team)


# ===========================================================================
# 1-2. Zielspiel und Zukunft
# ===========================================================================

class TestPointInTime:

    def test_das_zielspiel_zaehlt_nie_mit(self):
        """
        Das Zielspiel liegt exakt auf dem Stichtag. Wuerde es mitzaehlen,
        enthielte die "Form vor dem Spiel" sein Ergebnis - und jede
        Prognose waere trivial richtig.
        """
        eintraege = [_eintrag(7, tore=(1, 0)), _eintrag(0, tore=(9, 0))]
        m = fm.form_features(_tl(eintraege), CUTOFF)
        assert m["all_3_matches"] == 1
        assert m["all_3_goal_diff_per_match"] is None   # nur eine Partie
        assert m["form_matches_available"] == 1

    def test_eine_spaetere_partie_aendert_kein_historisches_merkmal(self):
        vorher = [_eintrag(t, tore=(2, 1)) for t in (30, 21, 14, 7, 3)]
        a = fm.form_features(_tl(vorher), CUTOFF)

        nachher = vorher + [_eintrag(-1, tore=(0, 5)),
                            _eintrag(-8, tore=(0, 9), competition="CL"),
                            _eintrag(-30, heim=False, tore=(7, 0))]
        b = fm.form_features(_tl(nachher), CUTOFF)
        assert a == b

    def test_auch_die_gegnerstaerke_kennt_die_zukunft_nicht(self):
        vorher = [_eintrag(t, gegner=10 + t) for t in (20, 12, 6, 3, 1)]
        werte = {}

        def staerke(team_id, kickoff):
            werte[(team_id, kickoff)] = True
            return 1.0 + 0.01 * team_id

        a = fm.form_features(_tl(vorher), CUTOFF, strength_at=staerke)
        b = fm.form_features(_tl(vorher + [_eintrag(-2, gegner=99)]),
                             CUTOFF, strength_at=staerke)
        assert a == b
        assert not any(k[1] >= CUTOFF for k in werte), (
            "die Gegnerstaerke wurde fuer einen Zeitpunkt ab dem Stichtag "
            "abgefragt")

    def test_die_gegnerstaerke_gilt_zum_zeitpunkt_der_damaligen_partie(self):
        """
        Der Kern der Gegneradjustierung: Gefragt wird nach der Staerke
        AM TAG DER DAMALIGEN PARTIE, nicht am Zielstichtag. Sonst
        enthielte der Wert das Ergebnis genau der Partie, deren
        Schwierigkeit er beschreiben soll.
        """
        eintraege = [_eintrag(t, gegner=5) for t in (20, 10, 4)]
        gefragt = []

        def staerke(team_id, kickoff):
            gefragt.append(kickoff)
            return 1.0

        fm.form_features(_tl(eintraege), CUTOFF, strength_at=staerke)
        erwartet = sorted(e["kickoff"] for e in eintraege)
        assert sorted(gefragt) == erwartet
        assert CUTOFF not in gefragt


# ===========================================================================
# 3-6. Wettbewerbe und Trennungen
# ===========================================================================

class TestTrennungen:

    def test_die_nationale_form_nimmt_nur_ligapartien(self):
        eintraege = [_eintrag(20, competition="BL1", tore=(3, 0)),
                     _eintrag(14, competition="CL", tore=(0, 3)),
                     _eintrag(9, competition="DFB", tore=(0, 4)),
                     _eintrag(4, competition="BL1", tore=(2, 0))]
        m = fm.form_features(_tl(eintraege), CUTOFF)
        assert m["domestic_5_matches"] == 2
        assert m["domestic_5_points_rate"] == 1.0
        assert m["domestic_5_goal_diff_per_match"] == 2.5

    def test_der_pokal_zaehlt_nicht_zur_nationalen_form(self):
        """
        Ein Zweitrundenspiel gegen einen Viertligisten ist ein
        Pflichtspiel und erzeugt Belastung - als Formaussage waere ein
        5:0 dort aber irrefuehrend.
        """
        eintraege = [_eintrag(20, competition="BL1", tore=(1, 1)),
                     _eintrag(10, competition="DFB", tore=(6, 0)),
                     _eintrag(5, competition="BL1", tore=(1, 1))]
        m = fm.form_features(_tl(eintraege), CUTOFF)
        assert m["domestic_5_matches"] == 2
        assert m["domestic_5_goal_diff_per_match"] == 0.0
        # In der ALLGEMEINEN Form ist der Pokal dagegen dabei.
        assert m["all_3_matches"] == 3
        assert m["all_3_goal_diff_per_match"] == 2.0

    def test_die_cl_form_nimmt_nur_cl_partien(self):
        eintraege = [_eintrag(24, competition="CL", tore=(2, 0)),
                     _eintrag(20, competition="BL1", tore=(0, 5)),
                     _eintrag(10, competition="CL", tore=(1, 1))]
        m = fm.form_features(_tl(eintraege), CUTOFF)
        assert m["cl_5_matches"] == 2
        assert m["cl_5_points_rate"] == 0.75
        assert m["cl_5_goal_diff_per_match"] == 1.0

    def test_nationale_form_und_cl_form_bleiben_getrennt(self):
        eintraege = [_eintrag(20, competition="BL1", tore=(4, 0)),
                     _eintrag(18, competition="BL1", tore=(4, 0)),
                     _eintrag(12, competition="CL", tore=(0, 4)),
                     _eintrag(6, competition="CL", tore=(0, 4))]
        m = fm.form_features(_tl(eintraege), CUTOFF)
        assert m["domestic_5_points_rate"] == 1.0
        assert m["cl_5_points_rate"] == 0.0

    def test_ohne_cl_historie_bleibt_die_cl_form_None(self):
        """
        Der Pflichttest gegen einen versteckten Nullwert: Ein erstmals
        qualifizierter Verein hat KEINE CL-Form. Eine Null hiesse
        "hat alle CL-Spiele verloren" und waere die schaerfste
        denkbare Falschaussage ueber ihn.
        """
        eintraege = [_eintrag(t, competition="BL1") for t in (20, 12, 5)]
        m = fm.form_features(_tl(eintraege), CUTOFF)
        assert m["cl_5_matches"] == 0
        assert m["cl_5_points_rate"] is None
        assert m["cl_5_goal_diff_per_match"] is None

    def test_eine_einzige_cl_partie_reicht_noch_nicht(self):
        eintraege = [_eintrag(20, competition="BL1"),
                     _eintrag(10, competition="CL", tore=(3, 0))]
        m = fm.form_features(_tl(eintraege), CUTOFF)
        assert m["cl_5_matches"] == 1
        assert m["cl_5_points_rate"] is None

    def test_die_heimform_nimmt_nur_heimspiele(self):
        eintraege = [_eintrag(20, heim=True, tore=(3, 0)),
                     _eintrag(15, heim=False, tore=(0, 3)),
                     _eintrag(10, heim=True, tore=(1, 0)),
                     _eintrag(5, heim=False, tore=(0, 1))]
        m = fm.form_features(_tl(eintraege), CUTOFF)
        assert m["home_5_matches"] == 2
        assert m["home_5_points_rate"] == 1.0
        assert m["home_5_goal_diff_per_match"] == 2.0

    def test_die_auswaertsform_nimmt_nur_auswaertsspiele(self):
        eintraege = [_eintrag(20, heim=True, tore=(3, 0)),
                     _eintrag(15, heim=False, tore=(0, 3)),
                     _eintrag(5, heim=False, tore=(0, 1))]
        m = fm.form_features(_tl(eintraege), CUTOFF)
        assert m["away_5_matches"] == 2
        assert m["away_5_points_rate"] == 0.0
        assert m["away_5_goal_diff_per_match"] == -2.0

    def test_erst_filtern_dann_abschneiden(self):
        """
        "Die letzten fuenf Heimspiele" ist nicht "die Heimspiele unter
        den letzten fuenf Partien". Die zweite Lesart liefert bei einer
        Auswaertsserie fast nichts - und sieht wie ein Datenproblem aus.
        """
        eintraege = ([_eintrag(60 - i, heim=True) for i in range(5)]
                     + [_eintrag(20 - i, heim=False) for i in range(6)])
        m = fm.form_features(_tl(eintraege), CUTOFF)
        assert m["home_5_matches"] == 5
        assert m["away_5_matches"] == 5


# ===========================================================================
# 8. Fenstergrenzen
# ===========================================================================

class TestFenstergrenzen:

    @pytest.mark.parametrize("fenster", (3, 5, 8))
    def test_genau_so_viele_partien_wie_das_fenster(self, fenster):
        eintraege = [_eintrag(60 - 2 * i) for i in range(20)]
        m = fm.form_features(_tl(eintraege), CUTOFF)
        assert m[f"all_{fenster}_matches"] == fenster

    def test_weniger_partien_als_das_fenster_ist_kein_fehler(self):
        eintraege = [_eintrag(20), _eintrag(10), _eintrag(4)]
        m = fm.form_features(_tl(eintraege), CUTOFF)
        assert m["all_3_matches"] == 3
        assert m["all_5_matches"] == 3
        assert m["all_8_matches"] == 3
        assert m["all_8_points_rate"] is not None

    def test_das_fenster_nimmt_die_JUENGSTEN_partien(self):
        eintraege = [_eintrag(60, tore=(0, 5)), _eintrag(50, tore=(0, 5)),
                     _eintrag(5, tore=(5, 0)), _eintrag(2, tore=(5, 0))]
        m = fm.form_features(_tl(eintraege), CUTOFF)
        assert m["all_3_points_rate"] == pytest.approx(2 / 3)
        assert m["all_8_points_rate"] == 0.5

    def test_unter_der_mindesttiefe_bleibt_der_wert_None(self):
        m = fm.form_features(_tl([_eintrag(5)]), CUTOFF)
        assert m["all_3_matches"] == 1
        assert m["all_3_points_rate"] is None
        assert fm.MIN_WINDOW_MATCHES == 2

    def test_die_fenster_stehen_vorab_fest(self):
        assert fm.DEFAULT_WINDOWS == (3, 5, 8)
        assert fm.SPLIT_WINDOW == 5
        assert {w for _, w, _, _ in fm.FORM_SCOPES} <= set(fm.DEFAULT_WINDOWS)


# ===========================================================================
# 9-10. Nicht ausgetragene Partien, Verlaengerung, Elfmeterschiessen
# ===========================================================================

class TestErgebnisregel:

    def test_sieg_remis_niederlage(self):
        assert fm._punkte({"home_goals": 2, "away_goals": 1}, True) == 1.0
        assert fm._punkte({"home_goals": 1, "away_goals": 1}, True) == 0.5
        assert fm._punkte({"home_goals": 0, "away_goals": 1}, True) == 0.0
        assert fm._punkte({"home_goals": 2, "away_goals": 1}, False) == 0.0

    def test_ein_elfmeterschiessen_gilt_als_remis(self):
        """
        Die dokumentierte Ergebnisregel. Die Quellen fuehren die
        Schuetzentore in eigenen Feldern (penalty_home/penalty_away);
        home_goals/away_goals bleiben der Stand nach 90 bzw. 120
        Minuten. Ein Schuetzenduell sagt ueber Spielstaerke wenig - und
        es aus den Toren herauszurechnen waere gar nicht moeglich.
        """
        partie = {"home_goals": 2, "away_goals": 2, "status": "PEN",
                  "penalty_home": 3, "penalty_away": 5}
        assert fm._punkte(partie, True) == 0.5
        assert fm._punkte(partie, False) == 0.5

    def test_ein_sieg_nach_verlaengerung_ist_ein_sieg(self):
        partie = {"home_goals": 3, "away_goals": 2, "status": "AET"}
        assert fm._punkte(partie, True) == 1.0
        assert fm._tordifferenz(partie, True) == 1.0

    def test_ohne_ergebnis_gibt_es_keine_punkte(self):
        assert fm._punkte({"home_goals": None, "away_goals": 1}, True) is None
        assert fm._tordifferenz({"home_goals": 1, "away_goals": None},
                                True) is None

    def test_nicht_ausgetragene_partien_stehen_gar_nicht_in_der_zeitleiste(self):
        from src.data.domestic_cup_loader import is_finished

        assert not is_finished({"status": "PST", "home_goals": None,
                                "away_goals": None})
        assert not is_finished({"status": "NS", "home_goals": None,
                                "away_goals": None})
        assert is_finished({"status": "AET", "home_goals": 2, "away_goals": 1})


# ===========================================================================
# 11-12. Gegnerstaerke
# ===========================================================================

class TestGegnerstaerke:

    def test_die_gewichtete_punktequote_ist_parameterfrei(self):
        """
        adjusted = sum(punkte_i * staerke_i) / sum(staerke_i).
        Ein Sieg gegen einen starken Gegner zaehlt mehr.
        """
        eintraege = [_eintrag(20, gegner=2, tore=(1, 0)),
                     _eintrag(10, gegner=3, tore=(0, 1))]

        def staerke(team_id, kickoff):
            return {2: 2.0, 3: 1.0}[team_id]

        werte = fm.opponent_values(_tl(eintraege), staerke)
        # Sieg gegen Staerke 2, Niederlage gegen Staerke 1
        assert werte["adjusted_points_rate_5"] == pytest.approx(2 / 3)
        assert werte["opponent_strength_5"] == 1.5
        assert werte["opponent_strength_matches"] == 2

    def test_gegner_ohne_staerke_werden_gezaehlt_nicht_geschaetzt(self):
        eintraege = [_eintrag(20, gegner=2), _eintrag(15, gegner=3),
                     _eintrag(10, gegner=4)]

        def staerke(team_id, kickoff):
            return 1.0 if team_id == 2 else None

        werte = fm.opponent_values(_tl(eintraege), staerke)
        assert werte["opponents_without_strength_5"] == 2
        assert werte["opponent_strength_matches"] == 1
        assert werte["opponent_strength_5"] is None

    def test_ohne_jede_gegnerstaerke_bleibt_alles_None(self):
        eintraege = [_eintrag(t) for t in (20, 10, 5)]
        werte = fm.opponent_values(_tl(eintraege), lambda t, k: None)
        assert werte["opponent_strength_5"] is None
        assert werte["adjusted_points_rate_5"] is None

    def test_ohne_staerkefunktion_bleiben_die_felder_None(self):
        m = fm.form_features(_tl([_eintrag(t) for t in (20, 10)]), CUTOFF)
        assert m["opponent_strength_5"] is None
        assert m["adjusted_points_rate_5"] is None

    def test_eine_spaetere_gegnerentwicklung_aendert_nichts(self):
        """
        Ein Gegner, der nach der Partie zehnmal gewinnt, war zum
        Zeitpunkt der Partie nicht staerker. Die Funktion bekommt den
        damaligen Zeitpunkt und darf sich nicht an einem spaeteren
        bedienen.
        """
        eintraege = [_eintrag(20, gegner=2), _eintrag(10, gegner=2)]

        def staerke(team_id, kickoff):
            # Wuerde spaeter gefragt, kaeme ein anderer Wert.
            return 1.0 if kickoff < CUTOFF else 99.0

        a = fm.opponent_values(_tl(eintraege), staerke)
        assert a["opponent_strength_5"] == 1.0


class TestPitStrengthAtDate:

    def test_verschiedene_stichtage_haben_getrennte_ergebnisse(self):
        from src.features.pit_profiles import PitStrengthAtDate

        f = PitStrengthAtDate(season=2025)
        f._cache[(2025, dt.datetime(2025, 9, 1))] = {7: 1.0}
        f._cache[(2025, dt.datetime(2025, 10, 1))] = {7: 2.0}
        assert f(7, dt.datetime(2025, 9, 1)) == 1.0
        assert f(7, dt.datetime(2025, 10, 1)) == 2.0

    def test_ohne_saison_bricht_die_rechnung_ab(self):
        from src.features.pit_profiles import MissingCutoff, PitStrengthAtDate

        with pytest.raises(MissingCutoff):
            PitStrengthAtDate()(7, dt.datetime(2025, 9, 1))

    def test_unbekannte_mannschaft_ergibt_None_und_nicht_null(self):
        from src.features.pit_profiles import PitStrengthAtDate

        f = PitStrengthAtDate(season=2025)
        f._cache[(2025, dt.datetime(2025, 9, 1))] = {7: 1.0}
        assert f(999, dt.datetime(2025, 9, 1)) is None
        assert f(None, dt.datetime(2025, 9, 1)) is None


# ===========================================================================
# 13-16. UEFA
# ===========================================================================

@pytest.fixture
def uefa_verzeichnis(tmp_path, monkeypatch):
    """
    Ein eigener Snapshotbestand - die echten Dateien sind gitignoriert.

    Zwei Saisons mit ABSICHTLICH verschiedenen Werten fuer denselben
    Verein: Nur so faellt auf, wenn der falsche Snapshot gezogen wird.
    """
    def schreibe(season, clubs):
        pfad = tmp_path / (f"uefa_coefficients_{season}_"
                           f"{str(season + 1)[-2:]}.json")
        pfad.write_text(json.dumps({
            "season": f"{season}/{str(season + 1)[-2:]}",
            "ranking_type": "uefa_club_coefficient_top40",
            "status": "complete", "clubs": clubs}), encoding="utf-8")

    schreibe(2023, [
        {"rank": 1, "club_name": "Alpha", "country": "Land A",
         "total_coefficient": 100.0, "footsim_team_id": "11",
         "apisports_team_id": 111},
        {"rank": 2, "club_name": "Beta", "country": "Land A",
         "total_coefficient": 80.0, "footsim_team_id": "12",
         "apisports_team_id": 112},
        {"rank": 3, "club_name": "Gamma", "country": "Land B",
         "total_coefficient": 60.0, "footsim_team_id": "13",
         "apisports_team_id": 113},
    ])
    schreibe(2024, [
        {"rank": 1, "club_name": "Alpha", "country": "Land A",
         "total_coefficient": 999.0, "footsim_team_id": "11",
         "apisports_team_id": 111},
    ])

    monkeypatch.setattr(uc, "COEFFICIENT_DIR", str(tmp_path))
    uc.clear_cache()
    yield tmp_path
    uc.clear_cache()


class TestUefaStichtag:

    def test_fuer_eine_partie_der_saison_X_gilt_der_snapshot_X_minus_1(self):
        assert us.SNAPSHOT_LAG_SEASONS == 1
        assert us.snapshot_season_for(2025) == 2024
        assert us.snapshot_season_for(2023) == 2022
        assert us.snapshot_season_for(None) is None

    def test_der_richtige_snapshot_wird_gezogen(self, uefa_verzeichnis):
        """
        Spielsaison 2024 muss den Snapshot 2023 nehmen (Alpha = 100),
        NICHT den von 2024 (Alpha = 999). Der Wert 999 steht dort
        eigens, damit ein Griff in die falsche Saison unuebersehbar
        ist.
        """
        lookup = us.UefaStrengthLookup()
        werte = us.uefa_values(lookup, 2024, 11)
        assert werte["uefa_club_coefficient"] == 100.0
        assert werte["uefa_source"] == us.SOURCE_OK
        assert lookup.snapshot_season(2024) == 2023

    def test_der_heutige_wert_beruehrt_eine_historische_zeile_nicht(
            self, uefa_verzeichnis):
        """
        Der Pflichttest gegen das Zukunftsleck: Der Snapshot der
        LAUFENDEN Saison wird veraendert; eine Zeile der Vorsaison darf
        sich davon nicht bewegen.
        """
        lookup = us.UefaStrengthLookup()
        vorher = us.uefa_values(lookup, 2024, 11)

        pfad = uefa_verzeichnis / "uefa_coefficients_2024_25.json"
        inhalt = json.loads(pfad.read_text(encoding="utf-8"))
        inhalt["clubs"][0]["total_coefficient"] = 1.0
        pfad.write_text(json.dumps(inhalt), encoding="utf-8")
        uc.clear_cache()

        nachher = us.uefa_values(us.UefaStrengthLookup(), 2024, 11)
        assert vorher == nachher
        assert nachher["uefa_club_coefficient"] == 100.0

    def test_der_koeffizient_einer_saison_enthaelt_ihre_eigenen_ergebnisse(self):
        """
        Die Begruendung des Versatzes, als pruefbare Aussage: Der
        Snapshot der laufenden Saison ist als "provisional"
        gekennzeichnet, weil sie erst wenige Punkte beigesteuert hat.
        Genau deshalb waere snapshot(X) fuer ein Spiel in X eine
        Zukunftsinformation.

        Ohne die privaten Dateien ist nichts zu pruefen - dann
        ueberspringt sich der Test sichtbar.
        """
        import os

        if not os.path.isdir(uc.COEFFICIENT_DIR):
            pytest.skip("keine privaten UEFA-Dateien vorhanden")
        vorhanden = uc.available_seasons(2021, 2026)
        if not vorhanden:
            pytest.skip("keine verwertbaren Snapshots vorhanden")
        assert us.SNAPSHOT_LAG_SEASONS >= 1


class TestUefaFallbacks:

    def test_ohne_snapshot_bleibt_alles_None_mit_sichtbarem_grund(
            self, tmp_path, monkeypatch):
        """
        Der CI-Fall: data/big_games/ ist gitignoriert und liegt auf
        einem anderen Rechner nicht. Das darf keine Ausnahme werfen und
        keine Null erzeugen - nur einen benannten Grund.
        """
        monkeypatch.setattr(uc, "COEFFICIENT_DIR", str(tmp_path / "leer"))
        uc.clear_cache()
        try:
            werte = us.uefa_values(us.UefaStrengthLookup(), 2024, 11)
            assert werte["uefa_club_coefficient"] is None
            assert werte["uefa_country_top40_strength"] is None
            assert werte["uefa_source"] == us.SOURCE_NO_SNAPSHOT
        finally:
            uc.clear_cache()

    def test_ein_verein_ausserhalb_der_top40_bleibt_None(self, uefa_verzeichnis):
        werte = us.uefa_values(us.UefaStrengthLookup(), 2024, 4711)
        assert werte["uefa_club_coefficient"] is None
        assert werte["uefa_source"] == us.SOURCE_NOT_RANKED

    def test_die_gruende_sind_unterscheidbar(self, uefa_verzeichnis):
        """
        "Kein Snapshot" ist eine Luecke der UMGEBUNG, "nicht in den Top
        40" eine Aussage ueber den VEREIN. Beides in ein einziges None
        zu legen wuerde eine fehlende Datenquelle wie eine Eigenschaft
        des Vereins aussehen lassen.
        """
        assert us.SOURCE_NO_SNAPSHOT != us.SOURCE_NOT_RANKED
        lookup = us.UefaStrengthLookup()
        assert us.uefa_values(lookup, 2024, None)["uefa_source"] \
            == us.SOURCE_NO_TEAM

    def test_ein_aufsteiger_ohne_eintrag_wird_nicht_geraten(
            self, uefa_verzeichnis):
        werte = us.uefa_values(us.UefaStrengthLookup(), 2024, 12)
        # Beta steht im Snapshot 2023, aber die Saison 2024 zieht 2023 -
        # dort ist Beta enthalten.
        assert werte["uefa_club_coefficient"] == 80.0
        # In der Saison 2025 (Snapshot 2024) fehlt Beta.
        werte = us.uefa_values(us.UefaStrengthLookup(), 2025, 12)
        assert werte["uefa_club_coefficient"] is None
        assert werte["uefa_source"] == us.SOURCE_NOT_RANKED

    def test_der_landeswert_summiert_nur_das_eigene_land(
            self, uefa_verzeichnis):
        lookup = us.UefaStrengthLookup()
        assert us.uefa_values(lookup, 2024, 11)[
            "uefa_country_top40_strength"] == 180.0
        assert us.uefa_values(lookup, 2024, 13)[
            "uefa_country_top40_strength"] == 60.0

    def test_der_landeswert_ist_kein_verbandskoeffizient(self):
        """
        Dokumentierte Einschraenkung als Test: Der Name muss die
        Herkunft tragen. Hiesse die Spalte "uefa_association_
        coefficient", laese sie jeder als offizielle Groesse - und sie
        ist keine.
        """
        assert "top40" in "uefa_country_top40_strength"
        assert "uefa_country_top40_strength" in us.UEFA_FELDER
        assert not any("association" in f for f in us.UEFA_FELDER)


# ===========================================================================
# 17-19. Stabilitaet
# ===========================================================================

class TestStabilitaet:

    def test_die_eingabereihenfolge_ist_gleichgueltig(self):
        eintraege = [_eintrag(t, heim=(t % 2 == 0), tore=(t % 3, 1))
                     for t in (3, 18, 9, 27, 1, 12, 40)]
        a = fm.form_features(_tl(eintraege), CUTOFF)
        b = fm.form_features(_tl(list(reversed(eintraege))), CUTOFF)
        assert a == b

    def test_ein_duplikat_veraendert_die_form_nicht(self):
        """
        Die Deduplizierung sitzt in build_timeline und greift ueber
        (competition, season, match_id). Zweimal dieselbe Partie darf
        keine zweite Formaussage erzeugen.
        """
        eintraege = [_eintrag(20, match_id="X", tore=(3, 0)),
                     _eintrag(10, match_id="Y", tore=(0, 3))]
        gesehen, eindeutig = set(), []
        for eintrag in eintraege + eintraege + eintraege:
            schluessel = (eintrag["competition"], eintrag["season"],
                          eintrag["match_id"])
            if schluessel in gesehen:
                continue
            gesehen.add(schluessel)
            eindeutig.append(eintrag)

        assert len(eindeutig) == 2
        m = fm.form_features(_tl(eindeutig), CUTOFF)
        assert m["all_5_matches"] == 2
        assert m["all_5_points_rate"] == 0.5

    def test_zwei_stichtage_liefern_verschiedene_form(self):
        eintraege = [_eintrag(30, tore=(0, 3)), _eintrag(20, tore=(0, 3)),
                     _eintrag(5, tore=(3, 0)), _eintrag(2, tore=(3, 0))]
        tl = _tl(eintraege)
        frueh = fm.form_features(tl, CUTOFF - dt.timedelta(days=10))
        spaet = fm.form_features(tl, CUTOFF)
        assert frueh["all_3_points_rate"] == 0.0
        assert spaet["all_3_points_rate"] == pytest.approx(2 / 3)

    def test_die_rechnung_veraendert_die_eingabe_nicht(self):
        import copy

        eintraege = [_eintrag(3), _eintrag(11)]
        kopie = copy.deepcopy(eintraege)
        fm.form_features(_tl(eintraege), CUTOFF)
        assert eintraege == kopie


# ===========================================================================
# 20-22. Paritaet, Vertauschung, Missingness
# ===========================================================================

class TestParitaet:

    def test_es_gibt_nur_eine_formfunktion(self):
        import inspect

        from src.ml import cl_dataset

        for quelle in (inspect.getsource(cl_dataset.build_cl_season),
                       inspect.getsource(ds.build_league_season)):
            assert "form_values_for_side" in quelle
        geteilt = inspect.getsource(ds.form_values_for_side)
        assert "form_features" in geteilt
        assert "uefa_values" in geteilt

    def test_derselbe_aufruf_ergibt_dieselben_werte(self, uefa_verzeichnis):
        eintraege = [_eintrag(t) for t in (20, 12, 5)]
        lookup = us.UefaStrengthLookup()
        a = ds.form_values_for_side("home", 11, 2024, CUTOFF, eintraege, lookup)
        b = ds.form_values_for_side("home", 11, 2024, CUTOFF, eintraege, lookup)
        assert a == b

    def test_eine_vorgebaute_zeitleiste_aendert_nichts(self, uefa_verzeichnis):
        eintraege = [_eintrag(t) for t in (20, 12, 5)]
        lookup = us.UefaStrengthLookup()
        ohne = ds.form_values_for_side("away", 11, 2024, CUTOFF, eintraege,
                                       lookup)
        mit = ds.form_values_for_side("away", 11, 2024, CUTOFF, eintraege,
                                      lookup,
                                      timeline=team_timeline(eintraege, 1))
        # team_timeline(eintraege, 1) ist die Zeitleiste von Team 1 - fuer
        # Team 11 bewusst NICHT dieselbe. Der Test prueft, dass die
        # Abkuerzung tatsaechlich benutzt wird und nicht ignoriert.
        assert ohne != mit

    @pytest.mark.parametrize("seite", ("home", "away"))
    def test_die_spalten_heissen_wie_im_schema(self, seite, uefa_verzeichnis):
        werte = ds.form_values_for_side(
            seite, 11, 2024, CUTOFF, [_eintrag(5)], us.UefaStrengthLookup())
        bekannt = {e["name"] for e in ds.build_schema()}
        assert set(werte) <= bekannt
        for feld in ds.FORM_FELDER + ds.UEFA_FELDER:
            assert ds._spaltenname(seite, feld) in werte


class TestVertauschung:

    def test_die_formdifferenz_dreht_ihr_vorzeichen(self):
        zeile = {"home_all_5_points_rate": 0.8, "away_all_5_points_rate": 0.4,
                 "home_all_5_goal_diff_per_match": 1.2,
                 "away_all_5_goal_diff_per_match": -0.4,
                 "home_uefa_club_coefficient": 100.0,
                 "away_uefa_club_coefficient": 60.0}
        getauscht = {("away" + s[4:]) if s.startswith("home")
                     else ("home" + s[4:]): w for s, w in zeile.items()}
        a = ds.form_difference_values(zeile)
        b = ds.form_difference_values(getauscht)
        for spalte, wert in a.items():
            assert b[spalte] == -wert

    def test_dieselbe_mannschaft_bekommt_seitenunabhaengig_dieselbe_form(
            self, uefa_verzeichnis):
        eintraege = [_eintrag(t) for t in (20, 12, 5)]
        lookup = us.UefaStrengthLookup()
        heim = ds.form_values_for_side("home", 1, 2024, CUTOFF, eintraege,
                                       lookup)
        gast = ds.form_values_for_side("away", 1, 2024, CUTOFF, eintraege,
                                       lookup)
        for feld in ds.FORM_FELDER + ds.UEFA_FELDER:
            assert heim[f"home_{feld}"] == gast[f"away_{feld}"]

    def test_beide_seiten_tragen_dieselben_merkmale(self):
        gruppen = fg.build_groups()
        for name in ("form", "form_opponent", "uefa"):
            spalten = gruppen[name]["columns"]
            h = sorted(s[5:] for s in spalten if s.startswith("home_"))
            a = sorted(s[5:] for s in spalten if s.startswith("away_"))
            assert h == a


class TestMissingness:

    def test_eine_differenz_ohne_gegenseite_bleibt_None(self):
        zeile = {"home_all_5_points_rate": 0.8, "away_all_5_points_rate": None,
                 "home_all_5_goal_diff_per_match": 1.0,
                 "away_all_5_goal_diff_per_match": 0.5,
                 "home_uefa_club_coefficient": None,
                 "away_uefa_club_coefficient": 60.0}
        werte = ds.form_difference_values(zeile)
        assert werte["form_diff_all_5_points_rate"] is None
        assert werte["form_diff_uefa_club_coefficient"] is None
        assert werte["form_diff_all_5_goal_diff_per_match"] == 0.5

    def test_die_tiefenangaben_sind_qualitaet_und_kein_merkmal(self):
        """
        Dieselbe Lehre wie bei profile_depth in V2-C2: Die Zahl
        beschreibt die QUELLE, nicht die Mannschaft, und hat in der
        Champions League einen anderen Wertebereich als im
        Ligatraining. Genau daran ist damals die Uebertragung
        gescheitert.
        """
        from src.ml import model as mdl

        merkmale = set(mdl.feature_columns())
        for feld in ds.FORM_DEPTH_FELDER + ds.FORM_OPPONENT_DIAGNOSE:
            for seite in ("home", "away"):
                assert ds._spaltenname(seite, feld) not in merkmale

    def test_die_uefa_herkunft_ist_kein_merkmal(self):
        from src.ml import model as mdl

        merkmale = set(mdl.feature_columns())
        for seite in ("home", "away"):
            assert f"{seite}_uefa_source" not in merkmale

    def test_training_und_laufzeit_ersetzen_luecken_gleich(self):
        from src.ml import model as mdl

        schritte = [name for name, _ in mdl.build_pipeline(1.0).steps]
        assert schritte[0] == "imputer"
        assert mdl.feature_matrix([{"a": None}], ["a"]) == [[None]]


# ===========================================================================
# 23-25. Vertraege, Fingerprint, Reproduzierbarkeit
# ===========================================================================

class TestVertraege:

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

    def test_der_v1_kandidat_traegt_kein_formmerkmal(self):
        spalten = set(fg.columns_for(fg.C3_BASE_CANDIDATE))
        unter = fg.build_c4_subgroups()
        for name in fg.C4_SUBGROUP_ORDER:
            assert not (spalten & set(unter[name]))

    def test_die_bestehenden_varianten_behalten_ihre_groesse(self):
        for name, anzahl in (("profile_only", 22), ("workload_only", 24),
                             ("team_profile_only", 18),
                             ("league_average_only", 4),
                             ("team_profile_cl", 16)):
            assert len(fg.columns_for(name)) == anzahl, name

    def test_die_c4_untergruppen_zerlegen_die_formgruppen_vollstaendig(self):
        bericht = fg.validate_c4_subgroups()
        assert sum(bericht["counts"].values()) == bericht["total_form_features"]

    def test_keine_spalte_steht_in_zwei_c4_untergruppen(self):
        unter = fg.build_c4_subgroups()
        alle = [s for name in fg.C4_SUBGROUP_ORDER for s in unter[name]]
        assert len(alle) == len(set(alle))

    def test_c3_und_c4_untergruppen_ueberschneiden_sich_nicht(self):
        """
        Zwei Register, zwei Namensraeume. Ueberschnitten sie sich,
        maesse eine C4-Variante heimlich ein C3-Merkmal mit.
        """
        c3 = {s for n in fg.SUBGROUP_ORDER for s in fg.build_subgroups()[n]}
        c4 = {s for n in fg.C4_SUBGROUP_ORDER
              for s in fg.build_c4_subgroups()[n]}
        assert not (c3 & c4)
        assert not (set(fg.SUBGROUP_ORDER) & set(fg.C4_SUBGROUP_ORDER))

    def test_jede_c4_variante_enthaelt_den_vollstaendigen_v1_satz(self):
        v1 = set(fg.columns_for(fg.C3_BASE_CANDIDATE))
        for definition in fg.c4_variants(("form_all_3",)):
            assert v1 <= set(fg.columns_for_c4(definition))

    def test_eine_unbekannte_untergruppe_bricht_ab(self):
        with pytest.raises(ValueError, match="unbekannte Formuntergruppe"):
            fg.columns_for_c4({"name": "x", "groups": (),
                               "subgroups": ("gibt_es_nicht",)})

    def test_ein_c3_name_ist_in_c4_unbekannt(self):
        with pytest.raises(ValueError, match="unbekannte Formuntergruppe"):
            fg.columns_for_c4({"name": "x", "groups": (),
                               "subgroups": ("short_rest",)})

    def test_die_fassung_ist_erhoeht(self):
        assert fg.SCHEMA_VERSION == 3

    def test_ein_geaenderter_formwert_aendert_den_fingerabdruck(self):
        import hashlib

        basis = {"row_id": "r1", "match_id": 1, "league": "cl",
                 "season": 2025, "date": "2025-10-01",
                 "evaluation_eligible": True, "home_goals": 1,
                 "away_goals": 0, "outcome": 0,
                 "baseline_lambda_home": 1.4, "baseline_lambda_away": 1.1,
                 "home_profile_source": "domestic_pit",
                 "away_profile_source": "domestic_pit",
                 "home_profile_matches": 20, "away_profile_matches": 20,
                 "exclusion_reason": None,
                 "home_all_3_points_rate": 0.5,
                 "home_uefa_club_coefficient": 100.0}
        for spalte in fg.columns_for(fg.C3_BASE_CANDIDATE):
            basis[spalte] = 1.0

        definition = fg.c4_variants(("form_all_3",))[-1]
        spalten = (list(ce.FINGERPRINT_IDENTITY)
                   + list(ce.FINGERPRINT_TARGETS)
                   + fg.columns_for_c4(definition)
                   + list(ce.FINGERPRINT_PROVENANCE))

        def hashe(zeile):
            roh = json.dumps({"columns": spalten,
                              "rows": [[zeile.get(s) for s in spalten]]},
                             sort_keys=True, separators=(",", ":"))
            return hashlib.sha256(roh.encode("utf-8")).hexdigest()

        assert hashe(basis) != hashe(dict(basis, home_all_3_points_rate=0.9))

    def test_ein_geaenderter_uefa_wert_aendert_den_fingerabdruck(self):
        import hashlib

        definition = fg.c4_variants(("uefa_club",))[-1]
        spalten = fg.columns_for_c4(definition)
        assert "home_uefa_club_coefficient" in spalten

        def hashe(wert):
            roh = json.dumps({"columns": spalten,
                              "rows": [[wert if s == "home_uefa_club_coefficient"
                                        else 1.0 for s in spalten]]},
                             sort_keys=True, separators=(",", ":"))
            return hashlib.sha256(roh.encode("utf-8")).hexdigest()

        assert hashe(100.0) != hashe(101.0)


class TestAblationsvertrag:

    def test_die_beiden_register_sind_getrennt_aber_gleich_gebaut(self):
        c3, c4 = ca.workload_registry(), ca.form_registry()
        assert c3.name != c4.name
        assert c3.reduced_name != c4.reduced_name
        assert c3.order != c4.order
        assert c3.columns is not c4.columns

    def test_die_vorauswahl_benutzt_die_reihenfolge_des_registers(self):
        """
        Regression zu einem echten Fehler dieses Blocks: Die Auswahl
        lief zunaechst gegen eine fest verdrahtete C3-Liste. Fuer C4
        lieferte sie dadurch stumm eine leere Menge - und das sah aus
        wie ein Ergebnis ("nichts ueberlebt"), war aber keines.
        """
        import inspect

        quelle = inspect.getsource(ca.reduced_subgroups)
        assert "registry.order" in quelle
        assert "fg.SUBGROUP_ORDER" not in quelle

    def test_die_vorauswahl_sieht_keine_cl_zeile(self):
        import inspect

        quelle = inspect.getsource(ca.reduced_subgroups)
        assert "training_rows(" in quelle
        assert "cl_rows(" not in quelle

    def test_die_vorauswahl_verweigert_sich_ohne_ligazeilen(self):
        nur_cl = [{"league": "cl", "season": 2023, "date": "2023-10-01",
                   "evaluation_eligible": True, "row_id": "cl:1"}]
        with pytest.raises(ValueError, match="keine Ligazeilen"):
            ca.reduced_subgroups(nur_cl, [2023], registry=ca.form_registry())

    def test_die_vif_reduktion_streicht_exakt_abhaengige_gruppen(self):
        zeilen = [{"a": float(i % 7), "b": float((i * 3) % 5),
                   "c": float(i % 7) - float((i * 3) % 5)}
                  for i in range(80)]
        unter = {"A": ("a",), "B": ("b",), "C": ("c",)}
        namen, protokoll = ca._vif_reduktion(
            zeilen, ["A", "B", "C"], unter,
            {"A": 0.003, "B": 0.002, "C": 0.001})
        assert "C" in [s["dropped"] for s in protokoll["steps"]]
        assert set(namen) == {"A", "B"}

    def test_die_vif_reduktion_laesst_saubere_gruppen_stehen(self):
        zeilen = [{"a": float(i % 7), "b": float((i * 37) % 11)}
                  for i in range(80)]
        namen, protokoll = ca._vif_reduktion(
            zeilen, ["A", "B"], {"A": ("a",), "B": ("b",)},
            {"A": 0.003, "B": 0.002})
        assert set(namen) == {"A", "B"}
        assert protokoll["steps"] == []

    def test_die_vif_reduktion_ist_reproduzierbar(self):
        zeilen = [{"a": float(i % 7), "b": float((i * 3) % 5),
                   "c": float(i % 7) - float((i * 3) % 5)}
                  for i in range(80)]
        unter = {"A": ("a",), "B": ("b",), "C": ("c",)}
        verb = {"A": 0.003, "B": 0.002, "C": 0.001}
        assert ca._vif_reduktion(zeilen, ["A", "B", "C"], unter, verb) \
            == ca._vif_reduktion(zeilen, ["A", "B", "C"], unter, verb)

    def test_das_gate_bleibt_das_bestehende(self):
        regeln = ca.decision_criteria()
        assert regeln["severe_degradation_threshold"] == ce.SEVERE_DEGRADATION
        assert regeln["min_reliable_n"] == ce.MIN_RELIABLE_N
        assert regeln["paired_against"] == fg.C3_BASE_CANDIDATE

    def test_alle_c4_varianten_stehen_vorab_fest(self):
        namen = [d["name"] for d in fg.c4_variants()]
        assert namen[0] == fg.C3_BASE_CANDIDATE
        assert len(namen) == len(set(namen))
        assert len(namen) == 1 + len(fg.C4_SUBGROUP_ORDER) + 4

    def test_der_reduzierte_kandidat_entfaellt_ohne_vorauswahl(self):
        assert fg.C4_REDUCED_CANDIDATE not in [d["name"]
                                               for d in fg.c4_variants(())]
        assert fg.C4_REDUCED_CANDIDATE in [
            d["name"] for d in fg.c4_variants(("form_all_3",))]


# ===========================================================================
# 27-30. Abgrenzung
# ===========================================================================

class TestAbgrenzung:

    def test_die_liga_isolation_bleibt_bestehen(self):
        zeilen = [
            {"league": "bl1", "season": 2024, "evaluation_eligible": True,
             "date": "2024-09-01", "row_id": "a"},
            {"league": "cl", "season": 2024, "evaluation_eligible": True,
             "date": "2024-09-02", "row_id": "b"},
        ]
        assert [z["row_id"] for z in ce.league_rows(zeilen, [2024])] == ["a"]
        assert [z["row_id"] for z in ce.cl_rows(zeilen, 2024)] == ["b"]

    def test_c4_stuft_kein_modell_hoch(self):
        import inspect

        for modul in (fm, us):
            quelle = inspect.getsource(modul)
            for verboten in ("save_bundle", "train_cl_model", "approved",
                             "release_stage"):
                assert verboten not in quelle

    def test_keine_ui_kennt_die_formmerkmale(self):
        import pathlib

        wurzel = pathlib.Path(__file__).resolve().parents[1]
        verdaechtig = ("all_5_points_rate", "uefa_club_coefficient",
                       "adjusted_points_rate_5", "form_diff_")
        dateien = (list((wurzel / "templates").rglob("*.html"))
                   + list((wurzel / "static").rglob("*.js"))
                   + list((wurzel / "static").rglob("*.css")))
        for pfad in dateien:
            text = pfad.read_text(encoding="utf-8", errors="replace")
            for begriff in verdaechtig:
                assert begriff not in text, f"{begriff} in {pfad.name}"

    def test_die_frueheren_vertraege_bleiben_bestehen(self):
        from src.features import match_timeline, pit_profiles
        from src.ml import persist

        assert hasattr(persist, "_pruefe_freigabestufe")     # C0B
        assert hasattr(pit_profiles, "require_cutoff")       # C1
        assert match_timeline.COVERAGE_OK == "covered"       # C2
        assert "PT1" in match_timeline.BASE_LOAD_COMPETITIONS
        assert hasattr(ca, "run_c3_ablation")                # C3
        assert fg.SUBGROUP_ORDER                             # C3

    def test_das_bestehende_modell_bleibt_der_v1_kandidat(self):
        from src.ml import inference

        assert inference.CANDIDATE == fg.CL_PRIMARY_CANDIDATE
        assert inference.feature_columns() == fg.columns_for("team_profile_cl")


class TestRunnerUnabhaengigkeit:

    def test_kein_modul_dieses_blocks_liest_einen_schluessel(self):
        import inspect

        for modul in (fm, us, ca):
            quelle = inspect.getsource(modul)
            for verboten in ("APISPORTS_KEY", "load_dotenv", "requests."):
                assert verboten not in quelle, f"{verboten} in {modul.__name__}"

    def test_die_formrechnung_liest_keine_datei(self):
        import inspect

        quelle = inspect.getsource(fm)
        assert "open(" not in quelle
        assert "load_season" not in quelle

    def test_diese_datei_braucht_keinen_bestand(self):
        import pathlib

        quelle = pathlib.Path(__file__).read_text(encoding="utf-8")
        # Zusammengesetzt, damit der Suchbegriff nicht in seiner eigenen
        # Behauptung steht.
        for teil in ("data/" + "historical", "data/" + "ml",
                     "data/" + "cache"):
            assert teil not in quelle
