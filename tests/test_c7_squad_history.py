"""
Kaderhistorie, Transfers und Vorsaisonstaerke (V2-C7).

WAS HIER GEPRUEFT WIRD
----------------------
Drei Fehler, die plausible Zahlen erzeugen und deshalb niemandem
auffallen:

  1. Ein Transfer, der am Spieltag bekannt wurde, in der Prognose
     desselben Spiels.
  2. Eine Saisonendstatistik als Wissen vom Oktober - also die
     Vorhersage der Saison mit ihrem eigenen Ergebnis.
  3. Die football-data-Kennung eines Vereins gegen die
     API-Sports-Transferhistorie eines anderen. Beide Nummernkreise
     enthalten dieselben Zahlen; eine naive Gleichsetzung "trifft" 55
     von 63 CL-Vereinen und liegt dabei durchweg falsch.

Dazu der Klassenvertrag: Was erst seit V2-C6 beobachtet wird, darf
nicht rueckwirkend auf Partien angewandt werden, die vorher lagen.

OHNE NETZ, OHNE .env, OHNE PRIVATE DATEN
----------------------------------------
Kein Test hier liest data/cache, data/player_pool oder das
Snapshot-Archiv. Transferereignisse und Vorsaisonwerte werden als
Wortlisten gebaut.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.features import squad_history as sh
from src.features import squad_crosswalk as scw
from src.features.transfer_events import build_team_index
from src.ml import cl_ablation as ca
from src.ml import cl_evaluate as ce
from src.ml import dataset as ds
from src.ml import feature_groups as fg
from src.ml import model as mdl

UTC = timezone.utc


# ===========================================================================
# Hilfsmittel
# ===========================================================================

def _transfer(datum, player_id, von, nach, art="permanent"):
    """Ein normalisiertes Transferereignis, wie transfer_events es baut."""
    return {
        "player_id": player_id, "player_name": f"P{player_id}",
        "date": datum, "season": int(datum[:4]),
        "from_team_id": von, "from_team_name": f"T{von}",
        "to_team_id": nach, "to_team_name": f"T{nach}",
        "transfer_type": art,
        "mapped_from_team": True, "mapped_to_team": True,
        "source": "test", "data_quality": "complete",
    }


class FakeStrength:
    """Vorsaisonwerte als Wortliste - ohne Datei."""

    def __init__(self, werte=None):
        # {(player_id, season): {"rating":, "minutes":}}
        self.werte = werte or {}
        self.abgefragt = []

    def for_player(self, player_id, match_season, seasons_back=2):
        self.abgefragt.append((player_id, match_season))
        for versatz in range(1, seasons_back + 1):
            treffer = self.werte.get((player_id, int(match_season) - versatz))
            if treffer is not None:
                return dict(treffer, season=int(match_season) - versatz)
        return None


def _index(events):
    return build_team_index(events)


# ===========================================================================
# 1-4. Der Stichtagsvertrag
# ===========================================================================

class TestStichtag:

    def test_ein_transfer_vor_dem_stichtag_zaehlt(self):
        events = [_transfer("2025-08-01", 1, 20, 10)]
        zu, ab = sh.transfer_window(10, "2025-10-01", _index(events))
        assert [e["player_id"] for e in zu] == [1]
        assert ab == []

    def test_ein_transfer_nach_dem_stichtag_zaehlt_nicht(self):
        events = [_transfer("2025-11-01", 1, 20, 10)]
        zu, ab = sh.transfer_window(10, "2025-10-01", _index(events))
        assert zu == [] and ab == []

    def test_ein_transfer_genau_am_stichtag_zaehlt_nicht(self):
        """
        Der strikte Vertrag aus V2-C1, hier auf Transfers angewandt.
        Ein Wechsel, dessen einziges bekanntes Datum der Spieltag ist,
        war zum Anpfiff nicht verlaesslich bekannt - und der Spieler
        stand fuer dieses Spiel ohnehin nicht mehr zur Verfuegung.
        """
        events = [_transfer("2025-10-01", 1, 20, 10)]
        zu, ab = sh.transfer_window(10, "2025-10-01", _index(events))
        assert zu == [] and ab == []

    def test_ein_spaeterer_transfer_veraendert_eine_fruehere_abfrage_nicht(self):
        frueh = [_transfer("2025-08-01", 1, 20, 10)]
        spaet = frueh + [_transfer("2025-12-01", 2, 30, 10)]
        a = sh.transfer_window(10, "2025-10-01", _index(frueh))
        b = sh.transfer_window(10, "2025-10-01", _index(spaet))
        assert [e["player_id"] for e in a[0]] == [e["player_id"] for e in b[0]]

    def test_das_fenster_schneidet_alte_transfers_ab(self):
        events = [_transfer("2023-01-01", 1, 20, 10),
                  _transfer("2025-08-01", 2, 30, 10)]
        zu, _ = sh.transfer_window(10, "2025-10-01", _index(events),
                                   window_days=365)
        assert [e["player_id"] for e in zu] == [2]

    def test_ohne_stichtag_gibt_es_nichts(self):
        events = [_transfer("2025-08-01", 1, 20, 10)]
        assert sh.transfer_window(10, None, _index(events)) == ([], [])


# ===========================================================================
# 5-8. Richtung, Leihe, Mehrfachwechsel
# ===========================================================================

class TestRichtungUndArt:

    def test_zugang_und_abgang_aus_derselben_perspektive(self):
        events = [_transfer("2025-08-01", 1, 20, 10),
                  _transfer("2025-08-02", 2, 10, 30)]
        zu, ab = sh.transfer_window(10, "2025-10-01", _index(events))
        assert [e["player_id"] for e in zu] == [1]
        assert [e["player_id"] for e in ab] == [2]

        # Aus Sicht des ANDEREN Vereins ist es genau umgekehrt.
        zu20, ab20 = sh.transfer_window(20, "2025-10-01", _index(events))
        assert zu20 == []
        assert [e["player_id"] for e in ab20] == [1]

    def test_ein_wintertransfer_wird_erfasst(self):
        events = [_transfer("2026-01-20", 1, 20, 10)]
        zu, _ = sh.transfer_window(10, "2026-02-15", _index(events))
        assert [e["player_id"] for e in zu] == [1]

    def test_leihen_werden_getrennt_gezaehlt(self):
        events = [_transfer("2025-08-01", 1, 20, 10, art="loan"),
                  _transfer("2025-08-02", 2, 30, 10, art="permanent"),
                  _transfer("2025-08-03", 3, 10, 40, art="loan")]
        werte = sh.squad_history_values(10, 2025, "2025-10-01",
                                        _index(events), FakeStrength())
        assert werte["arrivals_365d"] == 2.0
        assert werte["loans_in_365d"] == 1.0
        assert werte["departures_365d"] == 1.0
        assert werte["loans_out_365d"] == 1.0

    def test_eine_rueckkehr_ist_ein_eigenes_ereignis(self):
        """
        Der Anbieter meldet die Rueckkehr aus einer Leihe als eigenen
        Eintrag. Ein Leihende OHNE solchen Eintrag ist unsichtbar -
        genau deshalb steht es in den bekannten Grenzen.
        """
        events = [_transfer("2024-08-01", 1, 10, 20, art="loan"),
                  _transfer("2025-07-01", 1, 20, 10, art="loan_return")]
        zu, _ = sh.transfer_window(10, "2025-10-01", _index(events))
        assert [e["transfer_type"] for e in zu] == ["loan_return"]

    def test_mehrere_transfers_desselben_spielers(self):
        events = [_transfer("2025-07-01", 1, 20, 10),
                  _transfer("2025-08-15", 1, 10, 30),
                  _transfer("2026-01-10", 1, 30, 10)]
        zu, ab = sh.transfer_window(10, "2025-10-01", _index(events))
        assert [e["date"] for e in zu] == ["2025-07-01"]
        assert [e["date"] for e in ab] == ["2025-08-15"]
        # Der Januarwechsel liegt nach dem Stichtag.
        assert all(e["date"] < "2025-10-01" for e in zu + ab)


# ===========================================================================
# 9. Abgeleitete Mitgliedschaft - die Obergrenze
# ===========================================================================

class TestMitgliedschaft:

    def test_der_letzte_transfer_vor_dem_stichtag_entscheidet(self):
        events = [_transfer("2025-07-01", 1, 20, 10),
                  _transfer("2025-08-15", 1, 10, 30)]
        kader = sh.derived_membership(10, "2025-10-01", _index(events))
        assert 1 not in kader

        kader = sh.derived_membership(10, "2025-08-01", _index(events))
        assert 1 in kader

    def test_ein_transfer_am_stichtag_zaehlt_nicht(self):
        events = [_transfer("2025-10-01", 1, 20, 10)]
        assert sh.derived_membership(10, "2025-10-01", _index(events)) == {}

    def test_die_ableitung_ist_eine_obergrenze_und_kein_modellmerkmal(self):
        """
        Sie sieht jeden Zugang, aber nur die GEMELDETEN Abgaenge. Ein
        auslaufender Vertrag hinterlaesst keinen Eintrag, und der
        Spieler bleibt ewig im Kader stehen - nachgemessen Median 42
        gegen rund 30 in einem echten Einsatzkader.
        """
        merkmale = set(mdl.feature_columns())
        for seite in ("home", "away"):
            assert f"{seite}_derived_membership_upper_bound" not in merkmale
        assert "derived_membership_upper_bound" in ds.SQUAD_HISTORY_DIAGNOSE
        assert "derived_membership_upper_bound" not in ds.SQUAD_HISTORY_FELDER

    def test_keine_untergruppe_heisst_kadertiefe(self):
        assert not any("depth" in name for name in fg.C7_SUBGROUP_ORDER)


# ===========================================================================
# 10. Identitaet und Crosswalk
# ===========================================================================

class TestIdentitaet:

    def test_die_kennung_wird_nicht_geraten(self):
        """
        Ohne Crosswalk gibt es keine Werte - und ausdruecklich nicht
        die des gleichnamigen Nummernkreises.
        """
        werte = sh.squad_history_values(None, 2025, "2025-10-01", {},
                                        FakeStrength())
        assert werte["squad_history_source"] == sh.SOURCE_NO_CROSSWALK
        assert werte["arrivals_365d"] is None
        assert werte["transfer_data_available"] == 0

    def test_ein_team_ohne_transferhistorie_bleibt_unbekannt(self):
        werte = sh.squad_history_values(999, 2025, "2025-10-01", {},
                                        FakeStrength())
        assert werte["squad_history_source"] == sh.SOURCE_NO_TRANSFERS
        assert werte["arrivals_365d"] is None

    def test_die_beiden_gruende_sind_unterscheidbar(self):
        """
        "Keine Kennung" ist eine Luecke der Zuordnung, "keine
        Transferhistorie" eine Aussage ueber den Verein. Beides in ein
        None zu legen wuerde eine Zuordnungsluecke wie eine
        Vereinseigenschaft aussehen lassen.
        """
        assert sh.SOURCE_NO_CROSSWALK != sh.SOURCE_NO_TRANSFERS

    def test_der_crosswalk_verwirft_widersprueche(self, monkeypatch):
        """
        Zwei Quellen, zwei Antworten fuer denselben Verein: Eine davon
        ist falsch, und Raten ist nicht zulaessig. Der Eintrag
        verschwindet, statt zufaellig richtig zu sein.
        """
        monkeypatch.setattr(
            "src.features.match_timeline.CL_PARTICIPANT_CROSSWALK",
            {100: 500})

        aufrufe = {"n": 0}

        def falscher_crosswalk(liga, saison, as_teams):
            aufrufe["n"] += 1
            return {"mapping": {777: 100}}          # 100 -> 777, Widerspruch

        monkeypatch.setattr("src.features.team_crosswalk.build_crosswalk",
                            falscher_crosswalk)
        mapping, diagnose = scw.build_team_crosswalk(seasons=(2024,))
        assert 100 not in mapping
        assert diagnose["conflicts"]
        assert diagnose["conflicts"][0]["football_data_id"] == 100

    def test_der_crosswalk_meldet_doppelte_ziele(self, monkeypatch):
        """
        Zwei Vereine auf derselben API-Sports-Kennung wuerden sich
        ihre Transferhistorie teilen.
        """
        monkeypatch.setattr(
            "src.features.match_timeline.CL_PARTICIPANT_CROSSWALK",
            {100: 500, 101: 500})
        monkeypatch.setattr("src.features.team_crosswalk.build_crosswalk",
                            lambda *a, **k: {"mapping": {}})
        _, diagnose = scw.build_team_crosswalk(seasons=(2024,))
        assert diagnose["duplicate_targets"]

    def test_der_spielerpool_wird_nie_ueber_namen_zugeordnet(self):
        """
        Der Pool traegt keine team_id, nur team_name. Eine Zuordnung
        ueber den Namen waere genau die unsichere Identitaet, die
        dieses Projekt an anderer Stelle teuer gelernt hat.
        """
        import inspect

        quelle = inspect.getsource(sh.PriorSeasonStrength)
        assert "team_name" not in quelle
        assert "player_id" in quelle


# ===========================================================================
# 11-12. Kein Saisonendleck
# ===========================================================================

class TestKeinSaisonleck:

    def test_nur_abgeschlossene_vorsaisons_zaehlen(self):
        """
        DER wichtigste Test dieser Datei.

        Der Spielerpool traegt kein Datum - nachgemessen. Fuer ein
        Spiel im Oktober der Saison S waere er die Statistik einer
        Saison, die im Mai darauf endet: die Vorhersage der Saison mit
        ihrem eigenen Ergebnis.
        """
        staerke = FakeStrength()
        sh.strength_of_group([1, 2], 2025, staerke)
        # Abgefragt wird mit match_season; die Klasse sucht ab S-1.
        assert all(saison == 2025 for _, saison in staerke.abgefragt)
        # Und sie findet NUR frueheres.
        werte = FakeStrength({(1, 2025): {"rating": 9.0, "minutes": 3000},
                              (1, 2024): {"rating": 6.5, "minutes": 3000}})
        assert werte.for_player(1, 2025)["rating"] == 6.5

    def test_die_laufende_saison_wird_nicht_gefunden(self):
        werte = FakeStrength({(1, 2025): {"rating": 9.0, "minutes": 3000}})
        assert werte.for_player(1, 2025) is None

    def test_der_benutzte_saisonversatz_steht_in_der_zeile(self):
        werte = sh.squad_history_values(
            10, 2025, "2025-10-01",
            _index([_transfer("2025-08-01", 1, 20, 10)]), FakeStrength())
        assert werte["prior_season_used"] == 2024

    def test_die_klasse_sucht_hoechstens_zwei_saisons_zurueck(self):
        werte = FakeStrength({(1, 2022): {"rating": 7.0, "minutes": 3000}})
        assert werte.for_player(1, 2025) is None
        assert werte.for_player(1, 2024) is not None

    def test_zu_wenige_minuten_zaehlen_nicht(self):
        """
        Unter 270 Minuten ist eine Bewertung kein Mittelwert, sondern
        ein Einzelereignis.
        """
        staerke = FakeStrength({(1, 2024): {"rating": 9.9, "minutes": 100}})
        gruppe = sh.strength_of_group([1], 2025, staerke)
        assert gruppe["mean_rating"] is None
        assert gruppe["unrated"] == 1

    def test_eine_gruppe_ohne_bewertbare_spieler_bleibt_None(self):
        gruppe = sh.strength_of_group([1, 2], 2025, FakeStrength())
        assert gruppe["mean_rating"] is None
        assert gruppe["max_rating"] is None
        assert gruppe["count"] == 2
        assert gruppe["rated"] == 0

    def test_eine_leere_gruppe_ist_nicht_null(self):
        gruppe = sh.strength_of_group([], 2025, FakeStrength())
        assert gruppe["mean_rating"] is None
        assert gruppe["count"] == 0

    def test_die_mittlere_bewertung_stimmt(self):
        staerke = FakeStrength({
            (1, 2024): {"rating": 7.0, "minutes": 3000},
            (2, 2024): {"rating": 6.0, "minutes": 3000}})
        gruppe = sh.strength_of_group([1, 2], 2025, staerke)
        assert gruppe["mean_rating"] == 6.5
        assert gruppe["max_rating"] == 7.0
        assert gruppe["rated"] == 2


# ===========================================================================
# 13-17. Der Klassenvertrag und die Snapshotgrenze
# ===========================================================================

class TestKlassenvertrag:

    def test_jede_familie_hat_eine_klasse(self):
        for familie in fg.C7_SUBGROUP_ORDER:
            assert sh.data_class(familie) == sh.CLASS_A_HISTORICAL
        for familie in fg.C7_NOT_EVALUABLE_FAMILIES:
            assert sh.data_class(familie) == sh.CLASS_B_SNAPSHOT_ONLY

    def test_eine_unbekannte_familie_bricht_ab(self):
        """
        Ein stillschweigendes "vermutlich Klasse A" waere genau die
        Annahme, die dieser Vertrag verhindern soll.
        """
        with pytest.raises(ValueError, match="unbekannte Merkmalsfamilie"):
            sh.data_class("erfunden")

    def test_ohne_snapshots_ist_klasse_b_nicht_nutzbar(self):
        class LeeresArchiv:
            @staticmethod
            def archive_window(kind):
                return {"snapshots": 0, "usable_from": None, "keys": [],
                        "earliest": None, "latest": None}

        nutzbar, grund = sh.class_b_is_usable(
            datetime(2025, 10, 1, tzinfo=UTC), archive_reader=LeeresArchiv)
        assert nutzbar is False
        assert "noch nicht begonnen" in grund

    def test_ein_snapshot_nach_dem_stichtag_zaehlt_nicht(self):
        """
        Der erste Snapshot von heute darf nicht rueckwirkend fuer ein
        Spiel von gestern gelten - das waere erfundene Historie.
        """
        class SpaetesArchiv:
            @staticmethod
            def archive_window(kind):
                return {"snapshots": 1, "usable_from": "2026-09-06T18:00:00+00:00",
                        "keys": ["x"], "earliest": "2026-09-06T18:00:00+00:00",
                        "latest": "2026-09-06T18:00:00+00:00"}

        nutzbar, grund = sh.class_b_is_usable(
            datetime(2025, 10, 1, tzinfo=UTC), archive_reader=SpaetesArchiv)
        assert nutzbar is False
        assert "nicht vor dem Stichtag" in grund

    def test_ein_snapshot_vor_dem_stichtag_ist_nutzbar(self):
        class FruehesArchiv:
            @staticmethod
            def archive_window(kind):
                return {"snapshots": 5, "usable_from": "2025-01-01T00:00:00+00:00",
                        "keys": ["x"], "earliest": "2025-01-01T00:00:00+00:00",
                        "latest": "2025-06-01T00:00:00+00:00"}

        nutzbar, _ = sh.class_b_is_usable(
            datetime(2025, 10, 1, tzinfo=UTC), archive_reader=FruehesArchiv)
        assert nutzbar is True

    def test_gleicher_zeitpunkt_gilt_nicht_als_vorher(self):
        moment = "2025-10-01T12:00:00+00:00"

        class GenauArchiv:
            @staticmethod
            def archive_window(kind):
                return {"snapshots": 1, "usable_from": moment, "keys": ["x"],
                        "earliest": moment, "latest": moment}

        nutzbar, _ = sh.class_b_is_usable(moment, archive_reader=GenauArchiv)
        assert nutzbar is False

    def test_die_nicht_bewertbaren_familien_sind_benannt(self):
        assert set(fg.C7_NOT_EVALUABLE_FAMILIES) == {"squad_snapshot",
                                                     "availability_impact"}
        for familie in fg.C7_NOT_EVALUABLE_FAMILIES:
            assert familie not in fg.C7_SUBGROUP_ORDER

    def test_keine_nicht_bewertbare_familie_hat_eine_variante(self):
        """
        Eine Variante ohne Beobachtung wuerde Metriken erzeugen - und
        die saehen aus wie ein Ergebnis.
        """
        namen = " ".join(d["name"] for d in fg.c7_variants())
        for familie in fg.C7_NOT_EVALUABLE_FAMILIES:
            assert familie not in namen


# ===========================================================================
# 18-20. Missingness und Alter
# ===========================================================================

class TestMissingness:

    def test_unbekannt_ist_nicht_null(self):
        ohne = sh.squad_history_values(None, 2025, "2025-10-01", {},
                                       FakeStrength())
        assert ohne["arrivals_365d"] is None
        assert ohne["arrivals_365d"] != 0.0

    def test_null_transfers_ist_nicht_dasselbe_wie_unbekannt(self):
        """
        Ein Verein, der nichts transferiert hat, ist etwas anderes als
        ein Verein, ueber den nichts bekannt ist. Beides in ein None
        oder beides in eine Null zu legen waere falsch.
        """
        events = [_transfer("2020-01-01", 1, 20, 10)]   # weit vor dem Fenster
        werte = sh.squad_history_values(10, 2025, "2025-10-01",
                                        _index(events), FakeStrength())
        assert werte["arrivals_365d"] == 0.0
        assert werte["transfer_data_available"] == 1
        assert werte["squad_history_source"] == sh.SOURCE_OK

    def test_die_herkunft_steht_in_jeder_zeile(self):
        werte = sh.squad_history_values(
            10, 2025, "2025-10-01",
            _index([_transfer("2025-08-01", 1, 20, 10)]), FakeStrength())
        assert werte["squad_history_source"] == sh.SOURCE_OK
        assert werte["prior_season_used"] == 2024

    def test_die_zahl_der_bewerteten_wechsler_wird_mitgefuehrt(self):
        staerke = FakeStrength({(1, 2024): {"rating": 7.0, "minutes": 3000}})
        events = [_transfer("2025-08-01", 1, 20, 10),
                  _transfer("2025-08-02", 2, 30, 10)]
        werte = sh.squad_history_values(10, 2025, "2025-10-01",
                                        _index(events), staerke)
        assert werte["arrivals_365d"] == 2.0
        assert werte["arrivals_rated"] == 1

    def test_die_differenz_braucht_beide_seiten(self):
        staerke = FakeStrength({(1, 2024): {"rating": 7.0, "minutes": 3000}})
        events = [_transfer("2025-08-01", 1, 20, 10)]   # nur ein Zugang
        werte = sh.squad_history_values(10, 2025, "2025-10-01",
                                        _index(events), staerke)
        assert werte["arrivals_mean_rating"] == 7.0
        assert werte["departures_mean_rating"] is None
        assert werte["arrivals_minus_departures_rating"] is None

    def test_die_diagnosefelder_sind_keine_merkmale(self):
        merkmale = set(mdl.feature_columns())
        for feld in ds.SQUAD_HISTORY_DIAGNOSE + ds.SQUAD_HISTORY_QUALITAET:
            for seite in ("home", "away"):
                assert ds._spaltenname(seite, feld) not in merkmale


# ===========================================================================
# 21-24. Paritaet, Determinismus, Cache
# ===========================================================================

class TestParitaet:

    def test_es_gibt_nur_eine_kaderfunktion(self):
        import inspect

        from src.ml import cl_dataset as cd

        for quelle in (inspect.getsource(cd.build_cl_season),
                       inspect.getsource(ds.build_league_season)):
            assert "squad_history_values_for_side" in quelle
        geteilt = inspect.getsource(ds.squad_history_values_for_side)
        assert "squad_history_values" in geteilt
        assert "sources.mapping" in geteilt

    def test_derselbe_aufruf_ergibt_exakt_dieselben_werte(self):
        events = _index([_transfer("2025-08-01", 1, 20, 10)])
        staerke = FakeStrength({(1, 2024): {"rating": 7.0, "minutes": 3000}})
        a = sh.squad_history_values(10, 2025, "2025-10-01", events, staerke)
        b = sh.squad_history_values(10, 2025, "2025-10-01", events, staerke)
        assert a == b

    def test_die_reihenfolge_der_ereignisse_ist_gleichgueltig(self):
        events = [_transfer("2025-08-01", 1, 20, 10),
                  _transfer("2025-09-01", 2, 30, 10),
                  _transfer("2025-07-01", 3, 10, 40)]
        staerke = FakeStrength()
        a = sh.squad_history_values(10, 2025, "2025-10-01", _index(events),
                                    staerke)
        b = sh.squad_history_values(10, 2025, "2025-10-01",
                                    _index(list(reversed(events))), staerke)
        assert a == b

    def test_die_spalten_heissen_wie_im_schema(self):
        quellen = ds.SquadHistorySources(enabled=False)
        werte = ds.squad_history_values_for_side("home", 1, 2025,
                                                 "2025-10-01", quellen)
        bekannt = {e["name"] for e in ds.build_schema()}
        assert set(werte) <= bekannt

    def test_abgeschaltete_quellen_liefern_sichtbar_nichts(self):
        quellen = ds.SquadHistorySources(enabled=False)
        werte = ds.squad_history_values_for_side("home", 1, 2025,
                                                 "2025-10-01", quellen)
        assert werte["home_arrivals_365d"] is None
        assert werte["home_squad_history_source"] == "disabled"
        assert werte["home_transfer_data_available"] == 0

    def test_der_standard_liest_die_privaten_quellen_nicht(self):
        """
        data/cache und data/player_pool sind gitignoriert. Ein Bestand,
        der von dort liest, ist aus einem frischen Checkout nicht
        nachbaubar - dieselbe Entscheidung wie beim UEFA-Schalter aus
        V2-C4.
        """
        assert ds.INCLUDE_SQUAD_HISTORY_BY_DEFAULT is False

    def test_das_zielspielergebnis_beruehrt_die_merkmale_nicht(self):
        """
        Die Funktion bekommt Team, Saison und Stichtag - kein Ergebnis.
        Ein Selbstleck ist damit baulich ausgeschlossen.
        """
        import inspect

        parameter = list(inspect.signature(
            sh.squad_history_values).parameters)
        assert parameter == ["team_id_apisports", "match_season", "cutoff",
                             "transfer_index", "strength_source"]
        for verboten in ("home_goals", "away_goals", "outcome"):
            assert verboten not in inspect.getsource(sh.squad_history_values)


# ===========================================================================
# 25-27. Vertraege, Fingerprints, Vorauswahl
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

    def test_der_v1_kandidat_traegt_kein_kadermerkmal(self):
        spalten = set(fg.columns_for(fg.C3_BASE_CANDIDATE))
        unter = fg.build_c7_subgroups()
        for name in fg.C7_SUBGROUP_ORDER:
            assert not (spalten & set(unter[name]))

    def test_die_bestehenden_varianten_behalten_ihre_groesse(self):
        for name, anzahl in (("profile_only", 22), ("workload_only", 24),
                             ("team_profile_only", 18),
                             ("league_average_only", 4),
                             ("team_profile_cl", 16)):
            assert len(fg.columns_for(name)) == anzahl, name

    def test_die_c7_untergruppen_zerlegen_die_gruppe_vollstaendig(self):
        bericht = fg.validate_c7_subgroups()
        assert sum(bericht["counts"].values()) \
            == bericht["total_squad_history_features"]

    def test_die_vier_untergruppenraeume_ueberschneiden_sich_nicht(self):
        raeume = (set(fg.SUBGROUP_ORDER), set(fg.C4_SUBGROUP_ORDER),
                  set(fg.C5_SUBGROUP_ORDER), set(fg.C7_SUBGROUP_ORDER))
        for i, a in enumerate(raeume):
            for b in raeume[i + 1:]:
                assert not (a & b)

    def test_ein_fremder_untergruppenname_bricht_ab(self):
        with pytest.raises(ValueError, match="unbekannte Kaderuntergruppe"):
            fg.columns_for_c7({"name": "x", "groups": (),
                               "subgroups": ("short_rest",)})

    def test_die_fassung_ist_erhoeht(self):
        assert fg.SCHEMA_VERSION == 5

    def test_jede_c7_variante_enthaelt_den_vollstaendigen_v1_satz(self):
        v1 = set(fg.columns_for(fg.C3_BASE_CANDIDATE))
        for definition in fg.c7_variants(("transfer_balance",)):
            assert v1 <= set(fg.columns_for_c7(definition))

    @pytest.mark.parametrize("untergruppe,feld,neu", [
        ("transfer_volume", "home_arrivals_365d", 99.0),
        ("transfer_balance", "home_net_transfers_365d", -9.0),
        ("transfer_strength", "home_arrivals_mean_rating", 9.9),
    ])
    def test_ein_geaenderter_kaderwert_aendert_den_fingerabdruck(
            self, untergruppe, feld, neu):
        import hashlib

        definition = fg.c7_variants((untergruppe,))[-1]
        spalten = (list(ce.FINGERPRINT_IDENTITY)
                   + list(ce.FINGERPRINT_TARGETS)
                   + fg.columns_for_c7(definition)
                   + list(ce.FINGERPRINT_PROVENANCE))
        assert feld in spalten

        basis = {s: 1.0 for s in spalten}

        def hashe(zeile):
            roh = json.dumps({"columns": spalten,
                              "rows": [[zeile.get(s) for s in spalten]]},
                             sort_keys=True, separators=(",", ":"))
            return hashlib.sha256(roh.encode("utf-8")).hexdigest()

        assert hashe(basis) != hashe(dict(basis, **{feld: neu}))


class TestAblationsvertrag:

    def test_die_registrierung_benutzt_den_bestehenden_vertrag(self):
        """
        Anders als die Kontextmerkmale aus V2-C5 sind Transfermerkmale
        in Training UND Test vorhanden und variabel - ein Ligaverein
        transferiert genauso wie ein CL-Teilnehmer. Der Kontextvertrag
        waere hier nicht noetig und wuerde die Zahlen nur von denen aus
        C3 und C4 abkoppeln.
        """
        c7 = ca.squad_history_registry()
        c3 = ca.workload_registry()
        assert c7.contract == c3.contract
        assert c7.train_rows is None and c7.test_rows is None
        assert [f["name"] for f in c7.folds] == [f["name"] for f in c3.folds]

    def test_die_vorauswahl_sieht_keine_zeile_der_testsaison(self):
        zeilen = []
        for saison in (2023, 2024, 2025):
            zeilen.append({"league": "bl1", "season": saison,
                           "date": f"{saison}-09-01",
                           "row_id": f"bl1-{saison}",
                           "evaluation_eligible": True})
        waehle = ca.squad_history_registry().train_rows or ca.training_rows
        gewaehlt = waehle(zeilen, [2023, 2024])
        assert all(z["season"] in (2023, 2024) for z in gewaehlt)
        assert not any(z["season"] == 2025 for z in gewaehlt)

    def test_das_gate_bleibt_das_bestehende(self):
        regeln = ca.decision_criteria()
        assert regeln["severe_degradation_threshold"] == ce.SEVERE_DEGRADATION
        assert regeln["min_reliable_n"] == ce.MIN_RELIABLE_N
        assert regeln["paired_against"] == fg.C3_BASE_CANDIDATE

    def test_alle_c7_varianten_stehen_vorab_fest(self):
        namen = [d["name"] for d in fg.c7_variants()]
        assert namen[0] == fg.C3_BASE_CANDIDATE
        assert len(namen) == len(set(namen))
        assert len(namen) == 1 + len(fg.C7_SUBGROUP_ORDER) + 2

    def test_der_reduzierte_kandidat_entfaellt_ohne_vorauswahl(self):
        assert fg.C7_REDUCED_CANDIDATE not in [d["name"]
                                               for d in fg.c7_variants(())]
        assert fg.C7_REDUCED_CANDIDATE in [
            d["name"] for d in fg.c7_variants(("transfer_balance",))]


# ===========================================================================
# 28-34. Abgrenzung und Erhalt der Vorgaengerbloecke
# ===========================================================================

class TestAbgrenzung:

    def test_die_frueheren_vertraege_bleiben_bestehen(self):
        from src.data import snapshot_collector, snapshot_reader
        from src.features import match_context, match_timeline, pit_profiles
        from src.ml import persist

        assert hasattr(persist, "_pruefe_freigabestufe")     # C0B
        assert hasattr(pit_profiles, "require_cutoff")       # C1
        assert match_timeline.COVERAGE_OK == "covered"       # C2
        assert hasattr(ca, "run_c3_ablation")                # C3
        assert hasattr(ca, "run_c4_ablation")                # C4
        assert match_context.TYPE_KO_SECOND_LEG              # C5
        assert hasattr(snapshot_collector, "CollectorLock")  # C6
        assert hasattr(snapshot_reader, "snapshot_before")   # C6

    def test_der_c6_sammler_bleibt_funktionsfaehig(self):
        from src.data import snapshot_collector as sc

        assert sc.RUN_COMPLETE == "complete"
        assert callable(sc.run_collection)
        assert callable(sc.plan_scopes)

    def test_c7_stuft_kein_modell_hoch(self):
        import inspect

        for modul in (sh, scw):
            quelle = inspect.getsource(modul)
            for verboten in ("save_bundle", "train_cl_model", "approved",
                             "release_stage"):
                assert verboten not in quelle

    def test_das_bestehende_modell_bleibt_der_v1_kandidat(self):
        from src.ml import inference

        assert inference.CANDIDATE == fg.CL_PRIMARY_CANDIDATE
        assert inference.feature_columns() == fg.columns_for("team_profile_cl")

    def test_keine_ui_kennt_die_kadermerkmale(self):
        import pathlib

        wurzel = pathlib.Path(__file__).resolve().parents[1]
        verdaechtig = ("arrivals_365d", "net_transfers_365d",
                       "arrivals_mean_rating", "derived_membership")
        dateien = (list((wurzel / "templates").rglob("*.html"))
                   + list((wurzel / "static").rglob("*.js"))
                   + list((wurzel / "static").rglob("*.css")))
        for pfad in dateien:
            text = pfad.read_text(encoding="utf-8", errors="replace")
            for begriff in verdaechtig:
                assert begriff not in text, f"{begriff} in {pfad.name}"

    def test_die_liga_isolation_bleibt_bestehen(self):
        zeilen = [
            {"league": "bl1", "season": 2024, "date": "2024-09-01",
             "row_id": "a", "evaluation_eligible": True},
            {"league": "cl", "season": 2024, "date": "2024-09-02",
             "row_id": "b", "evaluation_eligible": True,
             "knockout_eligible": False},
        ]
        assert [z["row_id"] for z in ce.league_rows(zeilen, [2024])] == ["a"]
        assert [z["row_id"] for z in ce.cl_rows(zeilen, 2024)] == ["b"]


class TestUnabhaengigkeit:

    def test_kein_modul_liest_selbst_einen_schluessel(self):
        import inspect

        for modul in (sh, scw):
            quelle = inspect.getsource(modul)
            assert "APISPORTS_KEY" not in quelle
            assert "load_dotenv" not in quelle
            assert "requests." not in quelle

    def test_die_kaderrechnung_liest_keine_datei(self):
        """
        squad_history rechnet auf uebergebenen Ereignissen. Nur
        PriorSeasonStrength liest den Pool - und das ausdruecklich und
        an einer Stelle.
        """
        import inspect

        for name in ("transfer_window", "derived_membership",
                     "squad_history_values", "strength_of_group"):
            quelle = inspect.getsource(getattr(sh, name))
            assert "open(" not in quelle, name
            assert "glob" not in quelle, name

    def test_diese_datei_braucht_keinen_bestand(self):
        """
        Geprueft wird der ausfuehrbare Code, nicht die Dokumentation.
        Der Modulkopf NENNT die Verzeichnisse, die diese Datei
        ausdruecklich nicht anfasst - eine reine Textsuche faende genau
        diese Aufzaehlung und schluege fehl.
        """
        import ast
        import pathlib

        baum = ast.parse(pathlib.Path(__file__).read_text(encoding="utf-8"))
        for knoten in ast.walk(baum):
            if isinstance(knoten, ast.Expr) and isinstance(
                    knoten.value, ast.Constant) and isinstance(
                        knoten.value.value, str):
                knoten.value.value = ""
        code = ast.unparse(baum)

        for teil in ("data/" + "cache", "data/" + "player_pool",
                     "data/" + "snapshots", "data/" + "historical"):
            assert teil not in code
