"""
Spielbezogene Aktualisierung statt taeglichem Vollrefresh.

WORUM ES GEHT
-------------
Ein taeglicher Vollrefresh aller fuenf Ligen kostet rund 2.250 Abrufe -
bei einem Tageslimit von 7.500. Es geht, aber es ist Verschwendung: An
einem normalen Spieltag aendern sich die Werte von zwanzig Mannschaften,
nicht von hundert.

Diese Datei belegt die Gegenrechnung und, wichtiger, die Faelle, in denen
NICHT nachgeladen werden darf:

    abgebrochen   erzeugt keinen verlaesslichen Endstand
    verschoben    hat gar nicht stattgefunden
    laeuft noch   jeder Abruf waere sofort wieder veraltet

Der Fall "abgebrochen" ist nicht theoretisch. Am 22.08.2026 trugen elf
Real-Madrid-Spieler exakt 38 Minuten - ein Muster, das zu einem
Zwischenstand passt UND zu einem bei Minute 38 abgebrochenen Spiel. Wer
solche Partien als regulaer beendet behandelt, schreibt den Zwischenstand
fest und nennt ihn endgueltig.
"""

import pytest

from src.data import fixture_refresh as fr


def spiel(status="FT", heim=100, gast=200, liga=140,
          datum="2026-08-22T19:30:00+00:00"):
    """Ein Spiel in der Form, die /fixtures liefert."""
    return {
        "fixture": {"id": 1, "date": datum, "status": {"short": status}},
        "league": {"id": liga, "name": "La Liga", "season": 2026},
        "teams": {"home": {"id": heim, "name": f"Team {heim}"},
                  "away": {"id": gast, "name": f"Team {gast}"}},
    }


def kader(mitglieder_je_team):
    """Ein Ersatz fuer den Kaderindex."""
    def lookup(team_id, season):
        ids = mitglieder_je_team.get(team_id, [])
        return list(ids), f"Team {team_id}" if ids else None
    return lookup


# ---------------------------------------------------------------------------
# Statuszuordnung
# ---------------------------------------------------------------------------

class TestStatusZuordnung:
    """
    Die Zuordnung kommt aus live_api.STATUS_MAP. Diese Tests halten fest,
    dass sie fuer diesen Zweck richtig gelesen wird - nicht, dass es eine
    zweite Liste gibt.
    """

    @pytest.mark.parametrize("status", ["FT", "AET", "PEN"])
    def test_endzustaende_gelten_als_beendet(self, status):
        assert fr.fixture_phase(spiel(status=status)) in fr.FINAL_PHASES

    @pytest.mark.parametrize("status", ["1H", "2H", "ET", "P", "HT", "LIVE"])
    def test_laufende_zustaende_werden_erkannt(self, status):
        assert fr.fixture_phase(spiel(status=status)) in fr.RUNNING_PHASES

    @pytest.mark.parametrize("status", ["ABD", "SUSP", "PST", "CANC"])
    def test_abgebrochenes_gilt_nicht_als_regulaer_beendet(self, status):
        """
        Der entscheidende Fall. Ein bei Minute 38 abgebrochenes Spiel darf
        nicht wie ein regulaeres Spielende behandelt werden.
        """
        assert fr.fixture_phase(spiel(status=status)) not in fr.FINAL_PHASES

    def test_unbekannter_status_zerlegt_nichts(self):
        """Der Anbieter darf jederzeit einen neuen Code einfuehren."""
        phase = fr.fixture_phase(spiel(status="XYZ"))
        assert phase not in fr.FINAL_PHASES

    def test_fehlender_status_zerlegt_nichts(self):
        assert fr.fixture_phase({}) not in fr.FINAL_PHASES


# ---------------------------------------------------------------------------
# Wer muss nachgeladen werden
# ---------------------------------------------------------------------------

class TestBetroffeneMannschaften:

    def test_beide_mannschaften_eines_beendeten_spiels(self):
        betroffen = fr.teams_to_refresh([spiel(status="FT")])
        assert set(betroffen) == {100, 200}

    def test_abgebrochenes_spiel_loest_nichts_aus(self):
        assert fr.teams_to_refresh([spiel(status="ABD")]) == {}

    def test_verschobenes_spiel_loest_nichts_aus(self):
        assert fr.teams_to_refresh([spiel(status="PST")]) == {}

    def test_laufendes_spiel_loest_nichts_aus(self):
        """Waehrend eines Spiels waere jeder Abruf sofort veraltet."""
        assert fr.teams_to_refresh([spiel(status="1H")]) == {}

    def test_angesetztes_spiel_loest_nichts_aus(self):
        assert fr.teams_to_refresh([spiel(status="NS")]) == {}

    def test_fremde_liga_wird_ignoriert(self):
        """/fixtures?date= liefert die ganze Welt - gefiltert wird lokal."""
        assert fr.teams_to_refresh([spiel(liga=9999)]) == {}

    def test_alle_fuenf_ligen_zaehlen(self):
        spiele = [spiel(liga=lid, heim=lid, gast=lid + 1)
                  for lid in (78, 39, 140, 135, 61)]
        betroffen = fr.teams_to_refresh(spiele)
        assert len(betroffen) == 10

    def test_ein_beendetes_spiel_in_der_zukunft_wird_verworfen(self):
        """Ein Datenfehler des Anbieters darf keine 25 Abrufe ausloesen."""
        from datetime import datetime, timezone

        jetzt = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        betroffen = fr.teams_to_refresh(
            [spiel(status="FT", datum="2026-08-30T19:30:00+00:00")], now=jetzt)
        assert betroffen == {}

    def test_laufende_mannschaften_werden_getrennt_gefuehrt(self):
        laufend = fr.running_teams([spiel(status="2H")])
        assert set(laufend) == {100, 200}


# ---------------------------------------------------------------------------
# Lebensdauer
# ---------------------------------------------------------------------------

class TestGestaffelteLebensdauer:

    def test_waehrend_des_spiels_sehr_kurz(self):
        from src.api.live_api import PHASE_LIVE
        assert fr.profile_ttl(PHASE_LIVE) == fr.TTL_DURING_MATCH

    def test_in_der_halbzeit_ebenfalls_kurz(self):
        from src.api.live_api import PHASE_PAUSED
        assert fr.profile_ttl(PHASE_PAUSED) == fr.TTL_DURING_MATCH

    def test_kurz_nach_schlusspfiff_mittelkurz(self):
        from src.api.live_api import PHASE_FINISHED
        assert fr.profile_ttl(PHASE_FINISHED,
                              minutes_since_final=30) == fr.TTL_AFTER_MATCH

    def test_lange_nach_schlusspfiff_wieder_normal(self):
        from src.api.live_api import PHASE_FINISHED
        assert fr.profile_ttl(PHASE_FINISHED,
                              minutes_since_final=2000) == fr.TTL_IDLE

    def test_ohne_spielbezug_bleibt_es_bei_24_stunden(self):
        from src.api.live_api import PHASE_SCHEDULED
        assert fr.profile_ttl(PHASE_SCHEDULED) == fr.TTL_IDLE
        assert fr.TTL_IDLE == 24 * 60 * 60

    def test_abgeschlossene_saison_schlaegt_alles(self):
        from src.api.live_api import PHASE_LIVE
        assert fr.profile_ttl(PHASE_LIVE,
                              season_finished=True) == fr.TTL_FINISHED_SEASON

    def test_die_kurze_dauer_ist_wirklich_kuerzer(self):
        """Ohne das waere die ganze Staffelung wirkungslos."""
        assert fr.TTL_DURING_MATCH < fr.TTL_AFTER_MATCH < fr.TTL_IDLE


class TestVorlaeufigkeit:

    def test_waehrend_des_spiels_ist_alles_vorlaeufig(self):
        from src.api.live_api import PHASE_LIVE
        assert fr.is_provisional(PHASE_LIVE) is True

    def test_nach_einem_abbruch_ebenfalls(self):
        from src.api.live_api import PHASE_CANCELLED
        assert fr.is_provisional(PHASE_CANCELLED) is True

    def test_ein_regulaeres_spielende_ist_nicht_vorlaeufig(self):
        from src.api.live_api import PHASE_FINISHED
        assert fr.is_provisional(PHASE_FINISHED) is False


# ---------------------------------------------------------------------------
# Der Plan
# ---------------------------------------------------------------------------

class TestPlan:

    def test_ein_fixture_abruf_deckt_alle_ligen(self):
        """
        /fixtures?date= liefert alle Spiele eines Tages. Fuenf getrennte
        Ligaabfragen waeren vier Abrufe zu viel.
        """
        plan = fr.plan_post_match_refresh(
            [spiel()], 2026, squad_lookup=kader({100: [1], 200: [2]}))
        assert plan["requests_fixtures"] == 1

    def test_die_kosten_stehen_vor_der_ausfuehrung_fest(self):
        plan = fr.plan_post_match_refresh(
            [spiel()], 2026,
            squad_lookup=kader({100: list(range(25)),
                                200: list(range(100, 125))}))
        assert plan["requests_players"] == 50
        assert plan["requests_total"] == 51

    def test_ein_ruhetag_kostet_genau_einen_abruf(self):
        plan = fr.plan_post_match_refresh([], 2026, squad_lookup=kader({}))
        assert plan["requests_total"] == 1
        assert plan["player_ids"] == []

    def test_doppelte_spieler_werden_nur_einmal_gezaehlt(self):
        """Ein Spieler in zwei Kadern (Wechselfenster) kostet einen Abruf."""
        plan = fr.plan_post_match_refresh(
            [spiel()], 2026, squad_lookup=kader({100: [1, 2], 200: [2, 3]}))
        assert sorted(plan["player_ids"]) == [1, 2, 3]

    def test_fehlender_kader_wird_gemeldet_nicht_verschwiegen(self):
        plan = fr.plan_post_match_refresh(
            [spiel()], 2026, squad_lookup=kader({100: [1]}))
        assert plan["teams_without_squad"] == [200]

    def test_der_plan_fuehrt_nichts_aus(self):
        """
        Ein Plan ist eine Rechnung, keine Handlung. Der Kaderersatz wird
        nur gelesen, kein Abruf ausgeloest.
        """
        aufrufe = []

        def lookup(team_id, season):
            aufrufe.append(team_id)
            return [1], "Team"

        fr.plan_post_match_refresh([spiel()], 2026, squad_lookup=lookup)
        assert aufrufe == [100, 200]


class TestAusfuehrung:

    def test_nur_betroffene_spieler_werden_geholt(self):
        geholt = []

        def refetch(ids, season, dry_run=False):
            geholt.extend(ids)
            return [], {"angefragt": len(ids), "bearbeitet": len(ids),
                        "erfolgreich": len(ids), "fehlgeschlagen": 0,
                        "pool_aktualisiert": 0, "veraendert": 0,
                        "requests": len(ids), "abgebrochen": False,
                        "dry_run": dry_run}

        fr.run_post_match_refresh(
            2026, fixtures=[spiel()], refetch=refetch,
            squad_lookup=kader({100: [1, 2], 200: [3]}))

        assert sorted(geholt) == [1, 2, 3]

    def test_ohne_beendete_spiele_wird_gar_nicht_abgerufen(self):
        def darf_nicht(*args, **kwargs):
            raise AssertionError("es wurde abgerufen, obwohl nichts anlag")

        plan, ergebnisse, zus = fr.run_post_match_refresh(
            2026, fixtures=[spiel(status="NS")], refetch=darf_nicht,
            squad_lookup=kader({}))

        assert zus["requests"] == 0
        assert ergebnisse == []

    def test_die_obergrenze_schuetzt_vor_dem_sonderfall(self):
        """
        Liefert der Anbieter versehentlich hundert beendete Spiele, soll
        ein Lauf nicht das Tageslimit aufbrauchen.
        """
        geholt = []

        def refetch(ids, season, dry_run=False):
            geholt.extend(ids)
            return [], {"angefragt": len(ids), "bearbeitet": len(ids),
                        "erfolgreich": 0, "fehlgeschlagen": 0,
                        "pool_aktualisiert": 0, "veraendert": 0,
                        "requests": len(ids), "abgebrochen": False,
                        "dry_run": dry_run}

        plan, _, _ = fr.run_post_match_refresh(
            2026, fixtures=[spiel()], refetch=refetch,
            squad_lookup=kader({100: list(range(50)), 200: []}),
            max_players=10)

        assert len(geholt) == 10
        assert plan["gekuerzt_auf"] == 10

    def test_dry_run_wird_durchgereicht(self):
        gesehen = {}

        def refetch(ids, season, dry_run=False):
            gesehen["dry_run"] = dry_run
            return [], {"angefragt": 0, "bearbeitet": 0, "erfolgreich": 0,
                        "fehlgeschlagen": 0, "pool_aktualisiert": 0,
                        "veraendert": 0, "requests": 0, "abgebrochen": False,
                        "dry_run": dry_run}

        fr.run_post_match_refresh(
            2026, fixtures=[spiel()], refetch=refetch, dry_run=True,
            squad_lookup=kader({100: [1], 200: []}))

        assert gesehen["dry_run"] is True

    def test_zweimal_hintereinander_ist_unproblematisch(self):
        """
        Idempotenz - die Voraussetzung dafuer, dass ein Timer das spaeter
        stur alle paar Stunden ausfuehren darf.
        """
        laeufe = []

        def refetch(ids, season, dry_run=False):
            laeufe.append(list(ids))
            return [], {"angefragt": len(ids), "bearbeitet": len(ids),
                        "erfolgreich": len(ids), "fehlgeschlagen": 0,
                        "pool_aktualisiert": 0, "veraendert": 0,
                        "requests": len(ids), "abgebrochen": False,
                        "dry_run": dry_run}

        for _ in range(2):
            fr.run_post_match_refresh(
                2026, fixtures=[spiel()], refetch=refetch,
                squad_lookup=kader({100: [1], 200: [2]}))

        assert laeufe[0] == laeufe[1]


class TestKostenrechnung:

    def test_deutlich_guenstiger_als_ein_vollrefresh(self):
        kosten = fr.estimate_daily_cost()
        assert kosten["requests_je_tag_im_mittel"] < kosten["vollrefresh_taeglich"]

    def test_bleibt_unter_dem_tageslimit(self):
        kosten = fr.estimate_daily_cost()
        assert kosten["requests_je_spieltag"] < kosten["tageslimit"]

    def test_ein_ruhetag_kostet_einen_abruf(self):
        assert fr.estimate_daily_cost()["requests_je_ruhetag"] == 1
