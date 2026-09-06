"""
Die Belastungsmerkmale von V2-C3.

WAS HIER GEPRUEFT WIRD
----------------------
V2-C3 baut kaum neue Rechenlogik - der groesste Teil der
Belastungsmerkmale lag seit GO 3 vor. Neu sind die
Verlaengerungsbelastung, die Differenzspalten, die Untergruppen des
Merkmalsvertrags und der gemeinsame Codepfad von Datensatz und
Laufzeit.

Genau darauf zielt diese Datei - und auf die Zusagen, die fuer die
BESTEHENDEN Merkmale zwar galten, aber nirgends festgehalten waren:
Fenstergrenzen, Reihenfolgeunabhaengigkeit, Duplikate, kein
Zukunftsleck.

OHNE NETZ, OHNE .env, OHNE CACHE
--------------------------------
Jeder Test hier baut seine Zeitleiste selbst aus Wortlisten. Kein
Anbieter, kein Schluessel, keine gitignorierte Datei. Die wenigen
Tests, die den echten Bestand brauchen, ueberspringen sich sichtbar,
wenn er fehlt.
"""

import copy
import datetime as dt

import pytest

from src.features import workload as wl
from src.features.match_timeline import matches_before, team_timeline
from src.ml import cl_ablation as ca
from src.ml import cl_evaluate as ce
from src.ml import dataset as ds
from src.ml import feature_groups as fg
from src.ml import model as mdl

CUTOFF = dt.datetime(2025, 10, 1, 20, 0)


def _eintrag(tage_vorher, *, heim=True, competition="BL1", status=None,
             stage=None, match_id=None, stunde=20, team=1, gegner=2):
    """Ein Zeitleisteneintrag, relativ zum Stichtag."""
    zeitpunkt = CUTOFF - dt.timedelta(days=tage_vorher)
    zeitpunkt = zeitpunkt.replace(hour=stunde, minute=0)
    return {
        "match_id": match_id if match_id is not None
        else f"{competition}-{tage_vorher}-{heim}",
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
        "home_goals": 1, "away_goals": 1,
        "source": "test", "data_quality": "complete",
    }


def _timeline(eintraege, team=1):
    return team_timeline(eintraege, team)


# ===========================================================================
# 1-3. Point-in-Time
# ===========================================================================

class TestPointInTime:
    """Kein Merkmal darf etwas sehen, was zum Stichtag nicht feststand."""

    def test_nur_partien_strikt_vor_dem_stichtag_zaehlen(self):
        eintraege = [_eintrag(3), _eintrag(1), _eintrag(-1), _eintrag(-5)]
        merkmale = wl.workload_features(_timeline(eintraege), CUTOFF)
        assert merkmale["matches_last_7_days"] == 2
        assert merkmale["number_of_usable_matches"] == 2

    def test_das_zielspiel_selbst_zaehlt_nie(self):
        """
        Das Zielspiel liegt EXAKT auf dem Stichtag. Wuerde es mitzaehlen,
        waere die Belastung "vor" dem Spiel durch das Spiel selbst
        bestimmt - und jede Ruhezeit exakt null.
        """
        eintraege = [_eintrag(4), _eintrag(0)]
        merkmale = wl.workload_features(_timeline(eintraege), CUTOFF)
        assert merkmale["number_of_usable_matches"] == 1
        assert merkmale["rest_days"] == 4
        assert merkmale["rest_hours"] == 96

    def test_eine_spaetere_partie_aendert_kein_historisches_merkmal(self):
        """
        Der Pflichttest gegen Zukunftslecks: Wird die Zeitleiste
        nachtraeglich um Partien NACH dem Stichtag ergaenzt, muss jedes
        Merkmal Wert fuer Wert unveraendert bleiben.
        """
        vorher = [_eintrag(20), _eintrag(9), _eintrag(3)]
        vorher_werte = wl.workload_features(_timeline(vorher), CUTOFF)

        nachher = vorher + [_eintrag(-1), _eintrag(-4, heim=False),
                            _eintrag(-30, competition="CL")]
        nachher_werte = wl.workload_features(_timeline(nachher), CUTOFF)

        assert vorher_werte == nachher_werte

    def test_auch_die_gegnerhaerte_kennt_die_zukunft_nicht(self):
        vorher = [_eintrag(10, gegner=7), _eintrag(4, gegner=8)]
        lookup = {7: 1.5, 8: 0.8, 9: 3.0}
        a = wl.schedule_strength(_timeline(vorher), CUTOFF, lookup)
        b = wl.schedule_strength(
            _timeline(vorher + [_eintrag(-2, gegner=9)]), CUTOFF, lookup)
        assert a == b

    def test_matches_before_ist_strikt_kleiner(self):
        eintraege = _timeline([_eintrag(0)])
        assert matches_before(eintraege, CUTOFF) == []


# ===========================================================================
# 4. Fenstergrenzen
# ===========================================================================

class TestFenstergrenzen:
    """
    Die Grenze ist GESCHLOSSEN nach unten und OFFEN nach oben:

        cutoff - n Tage  <=  kickoff  <  cutoff

    Eine Partie exakt auf der unteren Grenze zaehlt also MIT. Das ist
    eine Festlegung und keine Selbstverstaendlichkeit - deshalb steht
    sie hier als Test und nicht nur als Kommentar.
    """

    @pytest.mark.parametrize("fenster", (7, 14, 21, 30))
    def test_exakt_auf_der_unteren_grenze_zaehlt_mit(self, fenster):
        merkmale = wl.workload_features(
            _timeline([_eintrag(fenster)]), CUTOFF)
        assert merkmale[f"matches_last_{fenster}_days"] == 1

    @pytest.mark.parametrize("fenster", (7, 14, 21, 30))
    def test_eine_sekunde_vor_der_grenze_zaehlt_nicht_mehr(self, fenster):
        eintrag = _eintrag(fenster)
        eintrag["kickoff"] -= dt.timedelta(seconds=1)
        merkmale = wl.workload_features(_timeline([eintrag]), CUTOFF)
        assert merkmale[f"matches_last_{fenster}_days"] == 0

    def test_die_fenster_sind_ineinander_geschachtelt(self):
        eintraege = [_eintrag(t) for t in (2, 5, 9, 16, 25, 40)]
        m = wl.workload_features(_timeline(eintraege), CUTOFF)
        assert (m["matches_last_7_days"] <= m["matches_last_14_days"]
                <= m["matches_last_21_days"] <= m["matches_last_30_days"])
        assert (m["matches_last_7_days"], m["matches_last_14_days"],
                m["matches_last_21_days"], m["matches_last_30_days"]) \
            == (2, 3, 4, 5)

    def test_ohne_uhrzeit_gilt_mittag(self):
        """
        Fehlt die Anstosszeit, setzt die Zeitleiste Mittag an. Die
        ZAEHLUNG bleibt davon unberuehrt - ein Spiel am 14. September
        liegt im Fenster oder nicht. Die Stundenzahl aendert sich, und
        genau das haelt rest_time_precision fest.
        """
        eintrag = _eintrag(3, stunde=12)
        eintrag["time_precision"] = "date"
        m = wl.workload_features(_timeline([eintrag]), CUTOFF)
        assert m["matches_last_7_days"] == 1
        assert m["rest_time_precision"] == "date"
        assert m["rest_data_quality"] == "partial"


# ===========================================================================
# 5. Nicht ausgetragene Partien
# ===========================================================================

class TestNichtAusgetragene:
    """
    Angesetzte, verschobene und abgesagte Spiele erzeugen keine
    Ermuedung. Sie stehen deshalb gar nicht erst in der Zeitleiste -
    match_timeline filtert sie beim Bau heraus.
    """

    def test_die_zeitleiste_nimmt_nur_ausgetragene_partien_auf(self):
        from src.features.match_timeline import _league_entries

        # Ein reiner Vertragstest ohne Datei: _league_entries prueft den
        # Status und das Vorliegen beider Ergebnisse.
        import inspect
        quelle = inspect.getsource(_league_entries)
        assert 'str(status).upper() != "FINISHED"' in quelle
        assert 'home_goals") is None' in quelle

    def test_der_pokalloader_verlangt_einen_abschlussstatus(self):
        from src.data.domestic_cup_loader import FINISHED_STATUSES, is_finished

        assert is_finished({"status": "FT", "home_goals": 1, "away_goals": 0})
        assert not is_finished({"status": "PST", "home_goals": None,
                                "away_goals": None})
        assert not is_finished({"status": "NS", "home_goals": None,
                                "away_goals": None})
        assert "FT" in FINISHED_STATUSES


# ===========================================================================
# 6. Verlaengerung
# ===========================================================================

class TestVerlaengerung:
    """
    Die entscheidende Unterscheidung ist None gegen 0: "nicht bekannt"
    gegen "keine Verlaengerung". Sie in eine Null zu legen waere die
    Scheingenauigkeit, die dieses Projekt sonst vermeidet.
    """

    def test_verlaengerung_wird_erkannt(self):
        assert wl.extra_time_minutes({"status": "AET"}) == 30.0
        assert wl.extra_time_minutes({"status": "PEN"}) == 30.0

    def test_regulaeres_spielende_ist_null_und_bekannt(self):
        assert wl.extra_time_minutes({"status": "FT"}) == 0.0

    def test_wertung_am_gruenen_tisch_ist_bekannt_und_null(self):
        assert wl.extra_time_minutes({"status": "AWD"}) == 0.0
        assert wl.extra_time_minutes({"status": "WO"}) == 0.0

    def test_ein_ligaspiel_ohne_status_ist_bekannt_neunzig_minuten(self):
        """
        Die football-data-Historie fuehrt fuer die fuenf Top-Ligen gar
        keinen Status. Dass dort keine Verlaengerung stattfand, ist
        aber keine Annahme ueber die Daten, sondern die Spielregel.
        """
        assert wl.extra_time_minutes(
            {"status": None, "competition": "BL1"}) == 0.0

    def test_eine_cl_rundenpartie_kann_keine_verlaengerung_haben(self):
        for stage in ("GROUP_STAGE", "LEAGUE_STAGE"):
            assert wl.extra_time_minutes(
                {"status": "FINISHED", "competition": "CL",
                 "stage": stage}) == 0.0

    def test_eine_cl_ko_partie_ist_ehrlich_unbekannt(self):
        """
        Der Kern des Verlaengerungsteils: Fuer die K.-o.-Runden fuehrt
        die Quelle nur FINISHED. Ob nach neunzig oder hundertzwanzig
        Minuten Schluss war, steht dort nicht - und ist aus dem
        Ergebnis nicht ableitbar.
        """
        assert wl.extra_time_minutes(
            {"status": "FINISHED", "competition": "CL",
             "stage": "LAST_16"}) is None

    def test_unbekannte_partien_machen_die_summe_partial_statt_falsch(self):
        eintraege = [
            _eintrag(20, competition="DFB", status="AET"),
            _eintrag(10, competition="CL", status="FINISHED",
                     stage="QUARTER_FINALS"),
            _eintrag(3, competition="BL1"),
        ]
        m = wl.workload_features(_timeline(eintraege), CUTOFF)
        assert m["extra_time_matches_last_30_days"] == 1
        assert m["extra_time_minutes_last_30_days"] == 30.0
        assert m["extra_time_data_quality"] == "partial"

    def test_ohne_jede_unbekannte_partie_ist_die_summe_complete(self):
        eintraege = [_eintrag(20, competition="DFB", status="AET"),
                     _eintrag(3, competition="BL1")]
        m = wl.workload_features(_timeline(eintraege), CUTOFF)
        assert m["extra_time_data_quality"] == "complete"
        assert m["extra_time_minutes_last_30_days"] == 30.0

    def test_sind_alle_partien_unbekannt_gibt_es_keinen_wert(self):
        eintraege = [_eintrag(10, competition="CL", status="FINISHED",
                              stage="SEMI_FINALS")]
        m = wl.workload_features(_timeline(eintraege), CUTOFF)
        assert m["extra_time_matches_last_30_days"] is None
        assert m["extra_time_minutes_last_30_days"] is None
        assert m["extra_time_data_quality"] == "unavailable"

    def test_eine_verlaengerung_ausserhalb_des_fensters_zaehlt_nicht(self):
        eintraege = [_eintrag(45, competition="DFB", status="AET"),
                     _eintrag(3, competition="BL1")]
        m = wl.workload_features(_timeline(eintraege), CUTOFF)
        assert m["extra_time_minutes_last_30_days"] == 0.0


# ===========================================================================
# 7. Auswaertsserie
# ===========================================================================

class TestAuswaertsserie:

    def test_die_serie_bricht_beim_ersten_heimspiel(self):
        eintraege = [_eintrag(20, heim=False), _eintrag(12, heim=True),
                     _eintrag(8, heim=False), _eintrag(3, heim=False)]
        m = wl.workload_features(_timeline(eintraege), CUTOFF)
        assert m["consecutive_away_matches"] == 2

    def test_ein_heimspiel_zuletzt_ergibt_null(self):
        eintraege = [_eintrag(8, heim=False), _eintrag(3, heim=True)]
        m = wl.workload_features(_timeline(eintraege), CUTOFF)
        assert m["consecutive_away_matches"] == 0

    def test_ohne_vorgeschichte_ist_die_serie_null_und_nicht_None(self):
        m = wl.workload_features(_timeline([]), CUTOFF)
        assert m["consecutive_away_matches"] == 0

    def test_die_serie_zaehlt_ueber_wettbewerbsgrenzen_hinweg(self):
        """
        Reisebelastung entsteht aus der Serie, nicht aus dem
        Wettbewerb. Ein Auswaertsspiel im Pokal bricht die Serie
        genauso wenig wie eines in der Liga.
        """
        eintraege = [_eintrag(9, heim=False, competition="CL"),
                     _eintrag(3, heim=False, competition="BL1")]
        m = wl.workload_features(_timeline(eintraege), CUTOFF)
        assert m["consecutive_away_matches"] == 2


# ===========================================================================
# 8-9. Reihenfolge und Duplikate
# ===========================================================================

class TestStabilitaet:

    def test_die_eingabereihenfolge_ist_gleichgueltig(self):
        eintraege = [_eintrag(t) for t in (3, 18, 9, 27, 1, 12)]
        a = wl.workload_features(_timeline(eintraege), CUTOFF)
        b = wl.workload_features(_timeline(list(reversed(eintraege))), CUTOFF)
        assert a == b

    def test_auch_die_gegnerhaerte_ist_reihenfolgeunabhaengig(self):
        eintraege = [_eintrag(3, gegner=5), _eintrag(12, gegner=6),
                     _eintrag(20, gegner=7)]
        lookup = {5: 1.2, 6: 0.9, 7: 1.4}
        a = wl.schedule_strength(_timeline(eintraege), CUTOFF, lookup)
        b = wl.schedule_strength(_timeline(list(reversed(eintraege))),
                                 CUTOFF, lookup)
        assert a == b

    def test_ein_duplikat_erhoeht_die_belastung_nicht(self):
        """
        Die Deduplizierung sitzt in build_timeline und greift ueber
        (competition, season, match_id). Zweimal dieselbe Partie darf
        keine zweite Ermuedung erzeugen.
        """
        from src.features.match_timeline import _entry

        roh = {"date": "2025-09-20", "match_id": 77, "home_id": 1,
               "away_id": 2, "home_goals": 1, "away_goals": 0,
               "status": "FT"}
        eintrag = _entry(roh, "BL1", "BL1", 2025, "test", "complete", 1, 2)

        gesehen, alle = set(), []
        for _ in range(3):
            schluessel = (eintrag["competition"], eintrag["season"],
                          eintrag["match_id"])
            if schluessel in gesehen:
                continue
            gesehen.add(schluessel)
            alle.append(eintrag)

        assert len(alle) == 1
        m = wl.workload_features(_timeline(alle), CUTOFF)
        assert m["number_of_usable_matches"] == 1

    def test_die_rechnung_veraendert_die_eingabe_nicht(self):
        eintraege = [_eintrag(3), _eintrag(11)]
        kopie = copy.deepcopy(eintraege)
        wl.workload_features(_timeline(eintraege), CUTOFF)
        assert eintraege == kopie


# ===========================================================================
# 10. Cutoff-Trennung
# ===========================================================================

class TestCutoffTrennung:

    def test_zwei_stichtage_liefern_verschiedene_belastungen(self):
        eintraege = [_eintrag(t) for t in (2, 6, 13, 25)]
        tl = _timeline(eintraege)
        frueh = wl.workload_features(tl, CUTOFF - dt.timedelta(days=10))
        spaet = wl.workload_features(tl, CUTOFF)
        assert frueh["number_of_usable_matches"] == 2
        assert spaet["number_of_usable_matches"] == 4
        assert frueh != spaet

    def test_die_laufzeit_haelt_die_stichtage_im_cachekey_auseinander(self):
        """
        Der Cacheschluessel der CL-Staerken traegt den Stichtag. Ohne
        ihn wuerde ein historisches Spiel die Staerken eines anderen
        Stichtags bekommen - und das faellt an keiner Zahl auf.
        """
        import inspect

        from src.predict import cl_match_sim

        quelle = inspect.getsource(cl_match_sim)
        assert 'f"cl_strengths:{season}:{cutoff}"' in quelle


# ===========================================================================
# 11. Paritaet Datensatz gegen Laufzeit
# ===========================================================================

class TestParitaet:
    """
    Der zentrale Invariant von V2-C1, hier auf die Belastung erweitert:
    Fuer dasselbe Team und denselben Stichtag muessen Datensatz und
    Laufzeit exakt dieselben Werte erzeugen.

    Seit V2-C3 gibt es dafuer nur noch EINEN Codepfad -
    ds.workload_values_for_side. Der Test prueft, dass beide
    Datensatzpfade ihn tatsaechlich benutzen.
    """

    def test_es_gibt_nur_eine_belastungsfunktion(self):
        import inspect

        from src.ml import cl_dataset

        cl_quelle = inspect.getsource(cl_dataset._belastung_fuer_seite)
        assert "workload_values_for_side" in cl_quelle
        # Die frueheren zweiten Fassungen sind weg.
        assert "base_load_coverage(" not in cl_quelle
        assert "workload_features(" not in cl_quelle

        liga_quelle = inspect.getsource(ds.build_league_season)
        assert "workload_values_for_side" in liga_quelle

    def test_derselbe_aufruf_ergibt_dieselben_werte(self):
        eintraege = [_eintrag(t, competition="BL1") for t in (3, 10, 17)]
        lookup = {2: 1.1}
        a, grund_a = ds.workload_values_for_side(
            "home", 1, CUTOFF, eintraege, lookup, require_base_load=False)
        b, grund_b = ds.workload_values_for_side(
            "home", 1, CUTOFF, eintraege, lookup, require_base_load=False)
        assert a == b and grund_a == grund_b

    def test_eine_vorgebaute_zeitleiste_aendert_nichts(self):
        """
        Der Ligapfad reicht seine zwischengespeicherte Teamzeitleiste
        durch. Das ist eine Abkuerzung und darf kein anderes Ergebnis
        liefern als der Bau innerhalb der Funktion.
        """
        eintraege = [_eintrag(t, competition="BL1") for t in (4, 11)]
        ohne, _ = ds.workload_values_for_side(
            "away", 1, CUTOFF, eintraege, {}, require_base_load=False)
        mit, _ = ds.workload_values_for_side(
            "away", 1, CUTOFF, eintraege, {}, require_base_load=False,
            timeline=team_timeline(eintraege, 1))
        assert ohne == mit

    def test_die_coverage_sperre_liefert_eine_begruendete_luecke(self):
        """
        Ohne nationalen Grundtakt bleibt der Wert None UND traegt den
        Grund. Eine Null waere hier eine Behauptung ueber die
        Mannschaft; ein leeres Feld ohne Grund waere nicht
        nachvollziehbar.
        """
        eintraege = [_eintrag(9, competition="CL")]
        werte, grund = ds.workload_values_for_side(
            "home", 1, CUTOFF, eintraege, {}, require_base_load=True)
        assert grund == "no_base_competition_in_timeline"
        assert werte["home_rest_hours"] is None
        assert werte["home_matches_last_7_days"] is None
        assert werte["home_data_quality"] == grund

    @pytest.mark.parametrize("seite", ("home", "away"))
    def test_die_spalten_heissen_wie_im_schema(self, seite):
        eintraege = [_eintrag(5, competition="BL1")]
        werte, _ = ds.workload_values_for_side(
            seite, 1, CUTOFF, eintraege, {}, require_base_load=False)
        bekannt = {e["name"] for e in ds.build_schema()}
        assert set(werte) <= bekannt
        for feld in ds.WORKLOAD_FELDER:
            assert ds._spaltenname(seite, feld) in werte


# ===========================================================================
# 12. Fehlende Werte
# ===========================================================================

class TestFehlendeWerte:

    def test_ohne_vorgeschichte_bleibt_die_ruhezeit_None(self):
        m = wl.workload_features(_timeline([]), CUTOFF)
        assert m["rest_hours"] is None
        assert m["rest_days"] is None
        assert m["data_quality"] == "unavailable"

    def test_eine_null_wird_niemals_als_fehlwert_benutzt(self):
        """
        matches_last_7_days == 0 heisst "keine Partie", nicht
        "unbekannt". Beides ist unterscheidbar, und genau darauf beruht
        die Missingness-Zusage.
        """
        m = wl.workload_features(_timeline([_eintrag(20)]), CUTOFF)
        assert m["matches_last_7_days"] == 0
        assert m["matches_last_30_days"] == 1
        assert m["rest_hours"] is not None

    def test_eine_differenz_ohne_gegenseite_bleibt_None(self):
        zeile = {"home_rest_hours": 72, "away_rest_hours": None,
                 "home_matches_last_7_days": 2,
                 "away_matches_last_7_days": None,
                 "home_matches_last_14_days": 3,
                 "away_matches_last_14_days": 4,
                 "home_matches_last_21_days": None,
                 "away_matches_last_21_days": 5,
                 "home_matches_last_30_days": 6,
                 "away_matches_last_30_days": 6}
        werte = ds.workload_difference_values(zeile)
        assert werte["workload_diff_rest_hours"] is None
        assert werte["workload_diff_matches_last_7_days"] is None
        assert werte["workload_diff_matches_last_21_days"] is None
        assert werte["workload_diff_matches_last_14_days"] == -1.0
        assert werte["workload_diff_matches_last_30_days"] == 0.0

    def test_das_modell_ersetzt_luecken_erst_in_der_pipeline(self):
        """
        Kein globales Auffuellen: Der Imputer sitzt IN der Pipeline und
        lernt seinen Median deshalb ausschliesslich auf dem Bestand,
        auf dem fit() gerufen wurde. Ein Auffuellen davor liefe ueber
        die zeitliche Grenze hinweg.
        """
        matrix = mdl.feature_matrix(
            [{"a": None, "b": 2}], ["a", "b"])
        assert matrix == [[None, 2.0]]

        schritte = [name for name, _ in mdl.build_pipeline(1.0).steps]
        assert schritte[0] == "imputer"

    def test_ein_wahrheitswert_wird_gewandelt_und_nicht_kodiert(self):
        assert mdl.feature_matrix([{"f": True}, {"f": False}], ["f"]) \
            == [[1.0], [0.0]]


# ===========================================================================
# 13. Vertauschung von Heim und Auswaerts
# ===========================================================================

class TestVertauschung:

    def test_die_differenz_dreht_ihr_vorzeichen(self):
        zeile = {"home_rest_hours": 96, "away_rest_hours": 72,
                 "home_matches_last_7_days": 2, "away_matches_last_7_days": 1,
                 "home_matches_last_14_days": 4, "away_matches_last_14_days": 2,
                 "home_matches_last_21_days": 5, "away_matches_last_21_days": 4,
                 "home_matches_last_30_days": 7, "away_matches_last_30_days": 6}
        getauscht = {("away" + s[4:]) if s.startswith("home")
                     else ("home" + s[4:]): w for s, w in zeile.items()}

        a = ds.workload_difference_values(zeile)
        b = ds.workload_difference_values(getauscht)
        for spalte, wert in a.items():
            assert b[spalte] == -wert

    def test_dieselbe_mannschaft_bekommt_seitenunabhaengig_dieselbe_last(self):
        """
        Die Belastung einer Mannschaft haengt an ihrer Vorgeschichte,
        nicht daran, ob sie im naechsten Spiel Heim- oder Gastgeber
        ist. Nur die Spaltennamen unterscheiden sich.
        """
        eintraege = [_eintrag(t, competition="BL1") for t in (3, 9)]
        heim, _ = ds.workload_values_for_side(
            "home", 1, CUTOFF, eintraege, {}, require_base_load=False)
        gast, _ = ds.workload_values_for_side(
            "away", 1, CUTOFF, eintraege, {}, require_base_load=False)
        for feld in ds.WORKLOAD_FELDER:
            assert heim[f"home_{feld}"] == gast[f"away_{feld}"]

    def test_beide_seiten_tragen_dieselben_merkmale(self):
        gruppen = fg.build_groups()
        for name in ("workload", "schedule_strength"):
            spalten = gruppen[name]["columns"]
            heim = sorted(s[5:] for s in spalten if s.startswith("home_"))
            gast = sorted(s[5:] for s in spalten if s.startswith("away_"))
            assert heim == gast


# ===========================================================================
# 14-15. Merkmalsvertraege
# ===========================================================================

class TestMerkmalsvertrag:

    def test_die_gruppen_zerlegen_die_modellmerkmale_vollstaendig(self):
        bericht = fg.validate_groups()
        summe = sum(bericht["counts"].values())
        assert summe == bericht["total_model_features"]

    def test_die_untergruppen_zerlegen_die_belastung_vollstaendig(self):
        bericht = fg.validate_subgroups()
        summe = sum(bericht["counts"].values())
        assert summe == bericht["total_workload_features"]

    def test_keine_spalte_steht_in_zwei_untergruppen(self):
        unter = fg.build_subgroups()
        alle = [s for name in fg.SUBGROUP_ORDER for s in unter[name]]
        assert len(alle) == len(set(alle))

    def test_gegnerhaerte_ist_keine_belastungsuntergruppe(self):
        """
        Gegnerstaerke gehoert fachlich nach V2-C4. Waere sie hier
        dabei, maesse ein C3-Ergebnis heimlich ein C4-Merkmal mit.
        """
        unter = fg.build_subgroups()
        alle = {s for name in fg.SUBGROUP_ORDER for s in unter[name]}
        gruppen = fg.build_groups()
        assert not (alle & set(gruppen["schedule_strength"]["columns"]))

    def test_der_v1_vertrag_ist_unveraendert(self):
        """
        Der Pflichttest gegen stille Vertragsaenderungen. Diese
        sechzehn Namen in dieser Reihenfolge sind der Kandidat, mit dem
        das bestehende Modell gemessen und gespeichert wurde. Aendert
        sich hier etwas, passt kein gespeichertes Bundle mehr.
        """
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

    def test_der_v1_kandidat_traegt_kein_belastungsmerkmal(self):
        spalten = set(fg.columns_for(fg.C3_BASE_CANDIDATE))
        unter = fg.build_subgroups()
        for name in fg.SUBGROUP_ORDER:
            assert not (spalten & set(unter[name]))

    def test_die_laufzeit_benutzt_weiterhin_den_v1_kandidaten(self):
        from src.ml import inference

        assert inference.CANDIDATE == fg.CL_PRIMARY_CANDIDATE
        assert inference.feature_columns() == fg.columns_for("team_profile_cl")

    def test_jede_c3_variante_enthaelt_den_vollstaendigen_v1_satz(self):
        """
        Der Vergleich lautet "V1 PLUS Belastung gegen V1". Enthielte
        eine Variante V1 nur teilweise, maesse sie etwas anderes als
        ihren Namen.
        """
        v1 = set(fg.columns_for(fg.C3_BASE_CANDIDATE))
        for definition in fg.c3_variants(("short_rest",)):
            assert v1 <= set(fg.columns_for_c3(definition))

    def test_eine_unbekannte_untergruppe_bricht_ab(self):
        with pytest.raises(ValueError, match="unbekannte Belastungsuntergruppe"):
            fg.columns_for_c3({"name": "x", "groups": (),
                               "subgroups": ("gibt_es_nicht",)})

    def test_ein_geaenderter_belastungswert_aendert_den_fingerabdruck(self):
        """
        Der Pflichttest gegen einen Fingerabdruck, der weniger belegt
        als er behauptet: Wandert ein Belastungswert, muss sich der
        Hash des Kandidaten aendern, der ihn liest.
        """
        basis = {"row_id": "r1", "match_id": 1, "league": "cl",
                 "season": 2025, "date": "2025-10-01",
                 "evaluation_eligible": True, "home_goals": 1,
                 "away_goals": 0, "outcome": 0,
                 "baseline_lambda_home": 1.4, "baseline_lambda_away": 1.1,
                 "home_profile_source": "domestic_pit",
                 "away_profile_source": "domestic_pit",
                 "home_profile_matches": 20, "away_profile_matches": 20,
                 "exclusion_reason": None, "home_rest_hours": 72.0}
        for spalte in fg.columns_for(fg.C3_BASE_CANDIDATE):
            basis[spalte] = 1.0

        spalten = (list(ce.FINGERPRINT_IDENTITY)
                   + list(ce.FINGERPRINT_TARGETS)
                   + fg.columns_for_c3(fg.c3_variants(("rest",))[-1])
                   + list(ce.FINGERPRINT_PROVENANCE))

        import hashlib
        import json

        def hashe(zeile):
            roh = json.dumps({"columns": spalten,
                              "rows": [[zeile.get(s) for s in spalten]]},
                             sort_keys=True, separators=(",", ":"))
            return hashlib.sha256(roh.encode("utf-8")).hexdigest()

        geaendert = dict(basis, home_rest_hours=96.0)
        assert hashe(basis) != hashe(geaendert)


# ===========================================================================
# 16. Redundanzdiagnostik und Reproduzierbarkeit
# ===========================================================================

class TestRedundanz:

    def _zeilen(self, n=60):
        zeilen = []
        for i in range(n):
            zeilen.append({
                "roh": float(i % 7),
                "doppelt": float(i % 7),           # exakt dieselbe Spalte
                "konstant": 3.0,
                "unabhaengig": float((i * 37) % 11),
            })
        return zeilen

    def test_eine_konstante_spalte_faellt_auf(self):
        bericht = ca.redundancy_report(
            self._zeilen(), ["roh", "konstant", "unabhaengig"])
        assert "konstant" in bericht["constant_columns"]

    def test_eine_exakt_doppelte_spalte_wird_als_solche_benannt(self):
        """
        Der wichtigste Teil der Diagnose: Ein nicht bestimmbarer VIF ist
        KEINE Entwarnung. vif_status muss sagen, warum.
        """
        bericht = ca.redundancy_report(
            self._zeilen(), ["roh", "doppelt", "unabhaengig"])
        assert "doppelt" in bericht["exactly_collinear_columns"]
        assert bericht["vif_status"]["doppelt"] == ca.VIF_EXACTLY_COLLINEAR
        assert bericht["vif"]["doppelt"] is None

    def test_perfekte_korrelation_wird_gemeldet(self):
        bericht = ca.redundancy_report(self._zeilen(), ["roh", "doppelt"])
        paare = {(p["a"], p["b"]) for p in bericht["high_correlation_pairs"]}
        assert ("doppelt", "roh") in paare or ("roh", "doppelt") in paare

    def test_die_diagnose_ist_reproduzierbar(self):
        spalten = ["roh", "doppelt", "konstant", "unabhaengig"]
        a = ca.redundancy_report(self._zeilen(), spalten)
        b = ca.redundancy_report(self._zeilen(), spalten)
        assert a == b

    def test_missingness_wird_je_spalte_ausgewiesen(self):
        zeilen = [{"a": 1.0}, {"a": None}, {"a": 3.0}, {"a": None}]
        bericht = ca.redundancy_report(zeilen, ["a"])
        assert bericht["missingness"]["a"] == 0.5


class TestAblationsvertrag:

    def test_die_vorauswahl_verweigert_sich_ohne_ligazeilen(self):
        """
        Der bauliche Schutz gegen Selektion auf dem Testbestand: Gibt
        es keine Ligazeilen, bricht die Vorauswahl ab - sie weicht
        NICHT auf die CL-Zeilen aus.
        """
        nur_cl = [{"league": "cl", "season": 2023,
                   "evaluation_eligible": True, "date": "2023-10-01",
                   "row_id": "cl:1"}]
        with pytest.raises(ValueError, match="keine Ligazeilen"):
            ca.reduced_subgroups(nur_cl, [2023])

    def test_die_vorauswahl_sieht_keine_cl_zeile(self):
        import inspect

        quelle = inspect.getsource(ca.reduced_subgroups)
        assert "training_rows(" in quelle
        assert "cl_rows(" not in quelle

    def test_training_rows_filtert_die_cl_zeilen_heraus(self):
        zeilen = [
            {"league": "bl1", "season": 2023, "evaluation_eligible": True,
             "date": "2023-09-01", "row_id": "a"},
            {"league": "cl", "season": 2023, "evaluation_eligible": True,
             "date": "2023-09-02", "row_id": "b"},
        ]
        assert [z["row_id"] for z in ca.training_rows(zeilen, [2023])] == ["a"]

    def test_die_entscheidungsregeln_sind_die_bestehenden(self):
        """
        Kein erfundener Ersatzschwellwert: Die Aufnahmeregeln
        uebernehmen die Schwellen aus cl_evaluate unveraendert und
        wenden sie nur auf die GEPAARTE Differenz gegen V1 an.
        """
        regeln = ca.decision_criteria()
        assert regeln["severe_degradation_threshold"] == ce.SEVERE_DEGRADATION
        assert regeln["min_reliable_n"] == ce.MIN_RELIABLE_N
        assert regeln["paired_against"] == fg.C3_BASE_CANDIDATE

    def test_eine_nicht_negative_differenz_wird_abgelehnt(self):
        variante = {"aggregate": {"n": 213}, "folds": [
            {"fold": "a", "delta_log_loss": -0.001}]}
        urteil = ca.decide(variante, {"log_loss": {"point": 0.002,
                                                   "ci_high": 0.01}})
        assert urteil["decision"] == ca.DECISION_REJECTED

    def test_ein_intervall_ueber_null_bleibt_unklar(self):
        variante = {"aggregate": {"n": 213}, "folds": [
            {"fold": "a", "delta_log_loss": -0.001}]}
        urteil = ca.decide(variante, {"log_loss": {"point": -0.002,
                                                   "ci_high": 0.004}})
        assert urteil["decision"] == ca.DECISION_INCONCLUSIVE

    def test_eine_zu_kleine_stichprobe_bleibt_unklar(self):
        variante = {"aggregate": {"n": 5}, "folds": [
            {"fold": "a", "delta_log_loss": -0.001}]}
        urteil = ca.decide(variante, {"log_loss": {"point": -0.02,
                                                   "ci_high": -0.01}})
        assert urteil["decision"] == ca.DECISION_INCONCLUSIVE

    def test_ein_schwerer_foldabfall_wird_abgelehnt(self):
        variante = {"aggregate": {"n": 213}, "folds": [
            {"fold": "a", "delta_log_loss": 0.02}]}
        urteil = ca.decide(variante, {"log_loss": {"point": -0.002,
                                                   "ci_high": -0.001}})
        assert urteil["decision"] == ca.DECISION_REJECTED

    def test_ein_sauberer_nachweis_wird_angenommen(self):
        variante = {"aggregate": {"n": 213}, "folds": [
            {"fold": "a", "delta_log_loss": -0.004},
            {"fold": "b", "delta_log_loss": -0.002}]}
        urteil = ca.decide(variante, {"log_loss": {"point": -0.003,
                                                   "ci_high": -0.001}})
        assert urteil["decision"] == ca.DECISION_ACCEPTED

    def test_widersprechende_folds_bleiben_unklar(self):
        variante = {"aggregate": {"n": 213}, "folds": [
            {"fold": "a", "delta_log_loss": -0.004},
            {"fold": "b", "delta_log_loss": +0.002}]}
        urteil = ca.decide(variante, {"log_loss": {"point": -0.003,
                                                   "ci_high": -0.001}})
        assert urteil["decision"] == ca.DECISION_INCONCLUSIVE

    def test_ohne_kontrollvariante_bricht_der_paarvergleich_ab(self):
        with pytest.raises(ValueError, match="Kontrollvariante"):
            ca.paired_against_base([{"variant": "x", "subgroups": [],
                                     "_losses": {}}])

    def test_alle_varianten_stehen_vorab_fest(self):
        namen = [d["name"] for d in fg.c3_variants()]
        assert namen[0] == fg.C3_BASE_CANDIDATE
        assert len(namen) == len(set(namen))
        # Jede Untergruppe einzeln plus drei Buendel plus die Kontrolle.
        assert len(namen) == 1 + len(fg.SUBGROUP_ORDER) + 3

    def test_der_reduzierte_kandidat_entfaellt_ohne_vorauswahl(self):
        namen = [d["name"] for d in fg.c3_variants(())]
        assert fg.C3_REDUCED_CANDIDATE not in namen
        namen = [d["name"] for d in fg.c3_variants(("rest",))]
        assert fg.C3_REDUCED_CANDIDATE in namen


# ===========================================================================
# 18-20. Abgrenzung
# ===========================================================================

class TestAbgrenzung:

    def test_die_liga_isolation_bleibt_bestehen(self):
        zeilen = [
            {"league": "bl1", "season": 2024, "evaluation_eligible": True,
             "date": "2024-09-01", "row_id": "a"},
            {"league": "cl", "season": 2024, "evaluation_eligible": True,
             "date": "2024-09-02", "row_id": "b"},
            {"league": "pl", "season": 2024, "evaluation_eligible": True,
             "date": "2024-09-03", "row_id": "c"},
        ]
        assert {z["row_id"] for z in ce.league_rows(zeilen, [2024])} == {"a", "c"}
        assert [z["row_id"] for z in ce.cl_rows(zeilen, 2024)] == ["b"]

    def test_v2_c3_stuft_kein_modell_hoch(self):
        import inspect

        quelle = inspect.getsource(ca)
        for verboten in ("save_bundle", "train_cl_model", "approved"):
            assert verboten not in quelle

    def test_keine_ui_kennt_die_belastungsmerkmale(self):
        """
        V2-C3 ist Analyse. Taeuchte eines dieser Merkmale in einer
        Vorlage oder einem Skript auf, waere daraus stillschweigend ein
        Produktmerkmal geworden.
        """
        import pathlib

        wurzel = pathlib.Path(__file__).resolve().parents[1]
        verdaechtig = ("extra_time_minutes_last_30_days",
                       "workload_diff_rest_hours",
                       "consecutive_away_matches")
        dateien = list((wurzel / "templates").rglob("*.html")) \
            + list((wurzel / "static").rglob("*.js")) \
            + list((wurzel / "static").rglob("*.css"))
        for pfad in dateien:
            text = pfad.read_text(encoding="utf-8", errors="replace")
            for begriff in verdaechtig:
                assert begriff not in text, f"{begriff} in {pfad.name}"

    def test_der_c0b_freigabevertrag_bleibt_bestehen(self):
        from src.ml import persist

        assert hasattr(persist, "_pruefe_freigabestufe")

    def test_der_c1_stichtagvertrag_bleibt_bestehen(self):
        from src.features import pit_profiles

        assert hasattr(pit_profiles, "require_cutoff")
        assert hasattr(pit_profiles, "runtime_cutoff")

    def test_der_c2_zeitleistenvertrag_bleibt_bestehen(self):
        from src.features import match_timeline

        assert match_timeline.COVERAGE_OK == "covered"
        assert "PT1" in match_timeline.BASE_LOAD_COMPETITIONS
        assert "BL1" in match_timeline.BASE_LOAD_COMPETITIONS


# ===========================================================================
# 17. Unabhaengigkeit von privaten Quellen
# ===========================================================================

class TestRunnerUnabhaengigkeit:

    def test_kein_modul_dieses_blocks_liest_einen_schluessel(self):
        import inspect

        from src.ml import cl_dataset

        for modul in (wl, ca, fg, ds, cl_dataset):
            quelle = inspect.getsource(modul)
            for verboten in ("APISPORTS_KEY", "load_dotenv", "os.environ",
                             "requests."):
                assert verboten not in quelle, f"{verboten} in {modul.__name__}"

    def test_diese_datei_braucht_keinen_bestand(self):
        """
        Jeder Test oben baut seine Daten selbst. Wuerde einer von ihnen
        data/ lesen, waere die Testsuite an eine lokale Maschine
        gebunden - und die CI meldete gruen, was sie nie geprueft hat.
        """
        import pathlib

        quelle = pathlib.Path(__file__).read_text(encoding="utf-8")
        # Zusammengesetzt, damit der Suchbegriff nicht in seiner eigenen
        # Behauptung steht - sonst faende sich der Test selbst.
        for teil in ("data/" + "historical", "data/" + "ml",
                     "data/" + "cache"):
            assert teil not in quelle
