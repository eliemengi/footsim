"""
Der Snapshot-Sammler (V2-C6).

WAS HIER GEPRUEFT WIRD
----------------------
Ein Sammler, der taeglich unbeaufsichtigt laeuft, faellt nicht laut aus.
Er faellt leise aus: Er schreibt eine halbe Datei, wiederholt eine
Anfrage endlos, laeuft zweimal gleichzeitig, oder er meldet Erfolg,
obwohl er die Haelfte ausgelassen hat. Genau darauf zielt diese Datei.

Der heikelste Punkt ist der Zeitvertrag: fetched_at belegt "spaetestens
jetzt war das so", effective_at den von der Quelle behaupteten
Zeitpunkt. Wer das erste als das zweite ausgibt, erfindet Historie -
und zwar so, dass es plausibel aussieht.

OHNE NETZ, OHNE .env, OHNE DATENBANK
------------------------------------
Kein Test hier spricht mit einem Anbieter. Die Transportschicht wird
durch Attrappen ersetzt, das Archiv liegt in tmp_path.
"""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from src.data import availability_snapshots as av
from src.data import snapshot_archive as archive
from src.data import snapshot_collector as sc
from src.data import snapshot_reader as sr
from src.data import snapshot_scopes as ss

UTC = timezone.utc


# ===========================================================================
# Hilfsmittel
# ===========================================================================

@pytest.fixture
def archiv(tmp_path, monkeypatch):
    """Ein eigenes Archiv je Test - nie das echte."""
    monkeypatch.setattr(archive, "ARCHIVE_DIR", str(tmp_path / "snapshots"))
    return tmp_path / "snapshots"


def _squad_antwort(team_id=157, spieler=None):
    spieler = spieler if spieler is not None else [
        {"id": 1, "name": "A", "number": 1, "position": "Goalkeeper", "age": 25},
        {"id": 2, "name": "B", "number": 4, "position": "Defender", "age": 28},
    ]
    return {"response": [{"team": {"id": team_id, "name": f"Team {team_id}"},
                          "players": spieler}],
            "results": 1, "paging": {"current": 1, "total": 1}}


def _injury_antwort(eintraege=None, league=78, season=2025):
    eintraege = eintraege if eintraege is not None else [
        {"player": {"id": 10, "name": "P", "type": "Missing Fixture",
                    "reason": "Knee Injury"},
         "team": {"id": 157, "name": "T"},
         "fixture": {"id": 900, "date": "2025-10-01T18:30:00+00:00"},
         "league": {"id": league, "season": season}},
    ]
    return {"response": eintraege, "results": len(eintraege),
            "paging": {"current": 1, "total": 1}}


class FakeTransport:
    """
    Eine Transportattrappe mit Gedaechtnis.

    Sie zaehlt die Aufrufe je (endpoint, params) - damit laesst sich
    beweisen, dass eine Mannschaft nicht zweimal abgefragt wurde.
    """

    def __init__(self, antworten=None, standard=None, quota=None):
        self.antworten = antworten or {}
        self.standard = standard
        self.aufrufe = []
        self.quota = quota or {"x-ratelimit-requests-remaining": 7000,
                               "x-ratelimit-requests-limit": 7500}

    def __call__(self, endpoint, params):
        schluessel = (endpoint, tuple(sorted((k, str(v))
                                             for k, v in params.items())))
        self.aufrufe.append(schluessel)
        antwort = self.antworten.get(schluessel, self.standard)
        if isinstance(antwort, sc.TransportResult):
            return antwort
        if antwort is None:
            return sc.TransportResult(False, error="keine Attrappe hinterlegt",
                                      quota=self.quota)
        return sc.TransportResult(True, payload=antwort, status_code=200,
                                  quota=self.quota)

    def anzahl(self, endpoint=None):
        if endpoint is None:
            return len(self.aufrufe)
        return sum(1 for e, _ in self.aufrufe if e == endpoint)


class FakeResponse:
    """Eine HTTP-Antwortattrappe fuer request_with_retry."""

    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"response": []}
        self.headers = headers or {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, antworten):
        self.antworten = list(antworten)
        self.aufrufe = 0

    def get(self, url, headers=None, params=None, timeout=None):
        self.aufrufe += 1
        self.letzter_timeout = timeout
        naechste = self.antworten[min(self.aufrufe - 1,
                                      len(self.antworten) - 1)]
        if isinstance(naechste, Exception):
            raise naechste
        return naechste


def _scope(kind=av.KIND_SQUAD, team=157, league=78, season=2025):
    if kind == av.KIND_SQUAD:
        return sc.Scope(kind, av.ENDPOINT_SQUAD, {"team": team},
                        av.squad_key(team), f"team {team}", 60)
    return sc.Scope(kind, av.ENDPOINT_INJURIES,
                    {"league": league, "season": season},
                    av.availability_key(league, season), f"league {league}", 0)


# ===========================================================================
# 1-3. Snapshots, leer gegen kaputt
# ===========================================================================

class TestSammeln:

    def test_erfolgreicher_kadersnapshot(self, archiv):
        transport = FakeTransport(standard=_squad_antwort())
        ergebnis = sc.collect_scope(_scope(), transport=transport)

        assert ergebnis["outcome"] == sc.OUTCOME_STORED
        assert ergebnis["requests"] == 1
        gespeichert = archive.list_snapshots(av.KIND_SQUAD)
        assert len(gespeichert) == 1

        eintrag = archive.load_snapshot_file(gespeichert[0]["path"])
        assert eintrag["payload"]["team_id"] == 157
        assert eintrag["payload"]["player_count"] == 2
        assert eintrag["meta"]["endpoint"] == av.ENDPOINT_SQUAD

    def test_erfolgreicher_verfuegbarkeitssnapshot(self, archiv):
        transport = FakeTransport(standard=_injury_antwort())
        ergebnis = sc.collect_scope(_scope(av.KIND_AVAILABILITY),
                                    transport=transport)

        assert ergebnis["outcome"] == sc.OUTCOME_STORED
        eintrag = archive.load_snapshot_file(
            archive.list_snapshots(av.KIND_AVAILABILITY)[0]["path"])
        nutz = eintrag["payload"]
        assert nutz["entry_count"] == 1
        assert nutz["entries"][0]["absence_category"] == av.ABSENCE_INJURY
        assert nutz["entries"][0]["status"] == av.STATUS_OUT

    def test_leere_antwort_ist_kein_fehler(self, archiv):
        """
        Eine Liga ohne gemeldete Ausfaelle ist ein gueltiger Zustand.
        Ihn als Fehler zu fuehren waere der sicherste Weg, eine echte
        Stoerung zu uebersehen - bei zwanzig taeglichen "Fehlern"
        schaut niemand mehr hin.
        """
        transport = FakeTransport(standard={"response": [], "results": 0,
                                            "paging": {"current": 1,
                                                       "total": 1}})
        ergebnis = sc.collect_scope(_scope(av.KIND_AVAILABILITY),
                                    transport=transport)
        assert ergebnis["outcome"] == sc.OUTCOME_EMPTY
        assert ergebnis["errors"] == []
        assert archive.list_snapshots(av.KIND_AVAILABILITY) == []

    def test_anbieterfehler_ist_ein_fehler(self, archiv):
        transport = FakeTransport(
            standard=sc.TransportResult(False, error="HTTP 503",
                                        status_code=503))
        ergebnis = sc.collect_scope(_scope(), transport=transport)
        assert ergebnis["outcome"] == sc.OUTCOME_FAILED
        assert ergebnis["errors"] == ["HTTP 503"]
        assert archive.list_snapshots(av.KIND_SQUAD) == []

    def test_leer_und_kaputt_sind_verschiedene_ergebnisse(self):
        assert sc.OUTCOME_EMPTY != sc.OUTCOME_FAILED

    def test_antwort_ueber_eine_fremde_mannschaft_wird_verworfen(self, archiv):
        """
        Ein Snapshot mit dem angefragten Schluessel und fremden
        Spielern waere schlimmer als gar keiner - er saehe richtig aus.
        """
        transport = FakeTransport(standard=_squad_antwort(team_id=999))
        ergebnis = sc.collect_scope(_scope(team=157), transport=transport)
        assert ergebnis["outcome"] == sc.OUTCOME_EMPTY
        assert archive.list_snapshots(av.KIND_SQUAD) == []


# ===========================================================================
# 4-5. Pagination und Dubletten
# ===========================================================================

class TestPaginationUndDubletten:

    def test_pagination_wird_vollstaendig_abgearbeitet(self, archiv):
        seite1 = {"response": [{"team": {"id": 157, "name": "T"},
                                "players": [{"id": 1, "name": "A"}]}],
                  "paging": {"current": 1, "total": 2}}
        seite2 = {"response": [{"team": {"id": 157, "name": "T"},
                                "players": [{"id": 2, "name": "B"}]}],
                  "paging": {"current": 2, "total": 2}}

        aufrufe = []

        def transport(endpoint, params):
            aufrufe.append(dict(params))
            nutz = seite1 if params.get("page", 1) == 1 else seite2
            return sc.TransportResult(True, payload=nutz, status_code=200)

        ergebnis = sc.collect_scope(_scope(), transport=transport)
        assert ergebnis["requests"] == 2
        assert ergebnis["pages"] == 2
        assert aufrufe[0].get("page") is None
        assert aufrufe[1]["page"] == 2

    def test_jede_seite_wird_genau_einmal_geholt(self, archiv):
        gesehen = []

        def transport(endpoint, params):
            seite = params.get("page", 1)
            gesehen.append(seite)
            return sc.TransportResult(
                True, status_code=200,
                payload={"response": [{"team": {"id": 157},
                                       "players": [{"id": seite}]}],
                         "paging": {"current": seite, "total": 3}})

        sc.collect_scope(_scope(), transport=transport)
        assert gesehen == [1, 2, 3]
        assert len(gesehen) == len(set(gesehen))

    def test_pagination_wird_nach_oben_begrenzt(self, archiv):
        """Ein fehlerhaftes paging darf keinen Endlosverbrauch ausloesen."""
        def transport(endpoint, params):
            return sc.TransportResult(
                True, status_code=200,
                payload={"response": [{"team": {"id": 157},
                                       "players": [{"id": 1}]}],
                         "paging": {"current": 1, "total": 9999}})

        ergebnis = sc.collect_scope(_scope(), transport=transport, max_pages=4)
        assert ergebnis["requests"] == 4
        assert any("begrenzt" in n for n in ergebnis["notes"])

    def test_ein_team_in_zwei_wettbewerben_wird_nur_einmal_geplant(self):
        """
        Bayern spielt in der Bundesliga UND in der Champions League.
        Zwei Anfragen fuer denselben Kader waeren verschwendetes
        Kontingent - und zwei Snapshots desselben Zustands.
        """
        teams = [{"team_id": 157, "label": "Bayern (bl1)", "priority": 60},
                 {"team_id": 157, "label": "Bayern (cl)", "priority": 50},
                 {"team_id": 165, "label": "Dortmund", "priority": 60}]
        plan = sc.plan_scopes(teams, [], 2025, kinds=(av.KIND_SQUAD,))

        assert len(plan) == 2
        bayern = [s for s in plan if s.params["team"] == 157]
        assert len(bayern) == 1
        # Der wichtigere Kontext gewinnt.
        assert bayern[0].priority == 50

    def test_doppelte_ligen_erzeugen_keine_doppelten_scopes(self):
        ligen = [{"league_id": 78, "label": "bl1", "priority": 0},
                 {"league_id": 78, "label": "bl1 nochmal", "priority": 10}]
        plan = sc.plan_scopes([], ligen, 2025, kinds=(av.KIND_AVAILABILITY,))
        assert len(plan) == 1

    def test_dubletten_im_kader_werden_gemeldet_nicht_behalten(self):
        antwort = [{"team": {"id": 157},
                    "players": [{"id": 1, "name": "A"},
                                {"id": 1, "name": "A nochmal"},
                                {"id": 2, "name": "B"}]}]
        nutz, beanstandungen = av.normalise_squad(antwort, team_id=157)
        assert nutz["player_count"] == 2
        assert any("doppelte" in b for b in beanstandungen)

    def test_dubletten_in_der_ausfallliste_werden_entfernt(self):
        eintrag = {"player": {"id": 10, "type": "Missing Fixture",
                              "reason": "Injury"},
                   "team": {"id": 157},
                   "fixture": {"id": 900, "date": "2025-10-01T18:30:00+00:00"}}
        nutz, beanstandungen = av.normalise_availability(
            [eintrag, dict(eintrag)], league_id=78, season=2025)
        assert nutz["entry_count"] == 1
        assert any("doppelter" in b for b in beanstandungen)


# ===========================================================================
# 6-9. Deduplizierung, Unveraenderlichkeit, Atomizitaet
# ===========================================================================

class TestArchivvertrag:

    def test_identischer_zustand_erzeugt_kein_duplikat(self, archiv):
        transport = FakeTransport(standard=_squad_antwort())
        erst = sc.collect_scope(_scope(), transport=transport)
        zweit = sc.collect_scope(_scope(), transport=transport)

        assert erst["outcome"] == sc.OUTCOME_STORED
        assert zweit["outcome"] == sc.OUTCOME_UNCHANGED
        assert len(archive.list_snapshots(av.KIND_SQUAD)) == 1

    def test_geaenderter_zustand_erzeugt_einen_neuen_snapshot(self, archiv):
        transport = FakeTransport(standard=_squad_antwort())
        sc.collect_scope(_scope(), transport=transport)

        transport.standard = _squad_antwort(spieler=[
            {"id": 1, "name": "A"}, {"id": 2, "name": "B"},
            {"id": 3, "name": "Neuzugang"}])
        zweit = sc.collect_scope(_scope(), transport=transport)

        assert zweit["outcome"] == sc.OUTCOME_STORED
        staende = archive.list_snapshots(av.KIND_SQUAD)
        assert len(staende) == 2
        assert staende[0]["captured_at"] <= staende[1]["captured_at"]

    def test_ein_frueherer_snapshot_wird_nie_ueberschrieben(self, archiv):
        moment = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
        erst = archive.archive_snapshot(av.KIND_SQUAD, "team_1", {"v": 1},
                                        captured_at=moment)
        inhalt_vorher = open(erst, encoding="utf-8").read()

        zweit = archive.archive_snapshot(av.KIND_SQUAD, "team_1", {"v": 2},
                                         captured_at=moment)
        assert erst != zweit
        assert open(erst, encoding="utf-8").read() == inhalt_vorher
        assert len(archive.list_snapshots(av.KIND_SQUAD, key="team_1")) == 2

    def test_der_schreibvorgang_ist_atomar(self, archiv):
        pfad = archive.archive_snapshot(av.KIND_SQUAD, "team_1", {"v": 1})
        assert os.path.exists(pfad)
        assert json.load(open(pfad, encoding="utf-8"))["payload"] == {"v": 1}
        verzeichnis = os.path.dirname(pfad)
        assert not [f for f in os.listdir(verzeichnis) if f.endswith(".tmp")]

    def test_ein_schreibabbruch_hinterlaesst_kein_halbes_artefakt(
            self, archiv, monkeypatch):
        """
        Der Kern der Atomizitaet: Bricht das Schreiben ab, darf KEINE
        Enddatei entstehen - auch keine halbe. Ein halbes JSON waere
        beim naechsten Lesen ein Fehler, den niemand einer Stoerung von
        vor drei Wochen zuordnet.
        """
        import src.data.snapshot_archive as sa

        original = sa.json.dump

        def platzt(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("Datentraeger voll")

        monkeypatch.setattr(sa.json, "dump", platzt)
        with pytest.raises(OSError):
            archive.archive_snapshot(av.KIND_SQUAD, "team_1", {"v": 1})

        verzeichnis = archive.archive_dir_for(av.KIND_SQUAD)
        vorhanden = os.listdir(verzeichnis) if os.path.isdir(verzeichnis) else []
        assert [f for f in vorhanden if f.endswith(".json")] == []
        assert [f for f in vorhanden if f.endswith(".tmp")] == []

    def test_eine_beschaedigte_datei_wird_gemeldet_nicht_ueberschrieben(
            self, archiv):
        pfad = archive.archive_snapshot(av.KIND_SQUAD, "team_1", {"v": 1})
        with open(pfad, "w", encoding="utf-8") as handle:
            handle.write("{kaputt")

        # Sie wird beim Auflisten uebersprungen ...
        assert archive.list_snapshots(av.KIND_SQUAD) == []
        # ... aber sie ist noch da. Ueberschreiben waere Datenverlust.
        assert os.path.exists(pfad)
        assert archive.load_snapshot_file(pfad) is None


class TestFingerabdruck:

    def test_der_fingerabdruck_ist_deterministisch(self):
        a = {"team_id": 1, "players": [{"id": 2}, {"id": 1}]}
        assert archive.content_fingerprint(a) == archive.content_fingerprint(a)

    def test_die_schluesselreihenfolge_aendert_ihn_nicht(self):
        assert archive.content_fingerprint({"a": 1, "b": 2}) \
            == archive.content_fingerprint({"b": 2, "a": 1})

    def test_ein_geaenderter_wert_aendert_ihn(self):
        assert archive.content_fingerprint({"a": 1}) \
            != archive.content_fingerprint({"a": 2})

    def test_die_spielerliste_wird_stabil_sortiert(self):
        """
        Ohne feste Sortierung ergaebe eine andere Reihenfolge beim
        Anbieter einen anderen Fingerabdruck - und das Archiv behauptete
        eine Aenderung, die keine ist.
        """
        vorwaerts, _ = av.normalise_squad(
            [{"team": {"id": 1}, "players": [{"id": 3}, {"id": 1}, {"id": 2}]}])
        rueckwaerts, _ = av.normalise_squad(
            [{"team": {"id": 1}, "players": [{"id": 2}, {"id": 1}, {"id": 3}]}])
        assert [p["player_id"] for p in vorwaerts["players"]] == [1, 2, 3]
        assert archive.content_fingerprint(vorwaerts) \
            == archive.content_fingerprint(rueckwaerts)

    def test_latest_fingerprint_liest_den_juengsten(self, archiv):
        archive.archive_snapshot(
            av.KIND_SQUAD, "team_1", {"v": 1},
            extra_meta={"content_fingerprint": "aaa"},
            captured_at=datetime(2026, 1, 1, tzinfo=UTC))
        archive.archive_snapshot(
            av.KIND_SQUAD, "team_1", {"v": 2},
            extra_meta={"content_fingerprint": "bbb"},
            captured_at=datetime(2026, 2, 1, tzinfo=UTC))
        assert archive.latest_fingerprint(av.KIND_SQUAD, "team_1") == "bbb"


# ===========================================================================
# 12-13. Zeitvertrag
# ===========================================================================

class TestZeitvertrag:

    def test_zeitstempel_sind_utc(self, archiv):
        transport = FakeTransport(standard=_squad_antwort())
        sc.collect_scope(_scope(), transport=transport)
        eintrag = archive.load_snapshot_file(
            archive.list_snapshots(av.KIND_SQUAD)[0]["path"])
        stempel = datetime.fromisoformat(eintrag["meta"]["captured_at"])
        assert stempel.tzinfo is not None
        assert stempel.utcoffset() == timedelta(0)

    def test_zwei_snapshots_derselben_sekunde_bekommen_eigene_dateien(
            self, archiv):
        moment = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
        a = archive.archive_snapshot(av.KIND_SQUAD, "k", {"v": 1},
                                     captured_at=moment)
        b = archive.archive_snapshot(av.KIND_SQUAD, "k", {"v": 2},
                                     captured_at=moment)
        assert a != b
        assert os.path.exists(a) and os.path.exists(b)

    def test_ein_kader_bekommt_kein_erfundenes_effective_at(self, archiv):
        """
        DER wichtigste Test dieser Datei.

        /players/squads liefert keine Zeitangabe - nachgemessen. Wer
        fetched_at als effective_at ausgibt, behauptet, der Kader habe
        sich in genau dieser Sekunde geaendert. Das ist erfundene
        Historie, und sie sieht vollkommen plausibel aus.
        """
        transport = FakeTransport(standard=_squad_antwort())
        sc.collect_scope(_scope(), transport=transport)
        eintrag = archive.load_snapshot_file(
            archive.list_snapshots(av.KIND_SQUAD)[0]["path"])

        assert eintrag["payload"]["effective_at"] is None
        assert eintrag["payload"]["effective_at_status"] \
            == av.EFFECTIVE_UNKNOWN_SQUAD
        assert eintrag["meta"]["fetched_at"] is not None
        assert eintrag["payload"]["effective_at"] != eintrag["meta"]["fetched_at"]

    def test_ein_ausfalleintrag_uebernimmt_das_partiedatum(self):
        nutz, _ = av.normalise_availability([
            {"player": {"id": 1, "type": "Missing Fixture", "reason": "Injury"},
             "team": {"id": 2},
             "fixture": {"id": 9, "date": "2025-10-01T18:30:00+00:00"}}],
            league_id=78, season=2025)
        eintrag = nutz["entries"][0]
        assert eintrag["effective_at"] == "2025-10-01T18:30:00+00:00"
        assert eintrag["effective_at_status"] == av.EFFECTIVE_FROM_SOURCE

    def test_ein_eintrag_ohne_partiedatum_bleibt_ohne_zeitpunkt(self):
        nutz, _ = av.normalise_availability([
            {"player": {"id": 1, "type": "Missing Fixture", "reason": "Injury"},
             "team": {"id": 2}, "fixture": {}}], league_id=78, season=2025)
        eintrag = nutz["entries"][0]
        assert eintrag["effective_at"] is None
        assert eintrag["effective_at_status"] == av.EFFECTIVE_UNKNOWN_MISSING
        assert nutz["entries_without_effective_at"] == 1

    def test_die_bedeutung_von_fetched_at_steht_im_snapshot(self, archiv):
        transport = FakeTransport(standard=_squad_antwort())
        sc.collect_scope(_scope(), transport=transport)
        eintrag = archive.load_snapshot_file(
            archive.list_snapshots(av.KIND_SQUAD)[0]["path"])
        text = eintrag["meta"]["fetched_at_meaning"]
        assert "spaetestens" in text.lower()
        assert "kein beginn" in text.lower()


# ===========================================================================
# 14-17. Netz: Timeout, Wiederholung, Retry-After, Kontingent
# ===========================================================================

class TestTransport:

    def test_ein_timeout_wird_gesetzt(self, monkeypatch):
        session = FakeSession([FakeResponse(200, {"response": []})])
        monkeypatch.setattr("src.api.apisports_api._headers", lambda: {})
        sc.request_with_retry("x", {}, session=session, sleeper=lambda s: None)
        assert session.letzter_timeout == sc.REQUEST_TIMEOUT_SECONDS

    def test_ein_netzwerkfehler_wird_wiederholt(self, monkeypatch):
        monkeypatch.setattr("src.api.apisports_api._headers", lambda: {})
        session = FakeSession([ConnectionError("weg"), ConnectionError("weg"),
                               FakeResponse(200, {"response": [1]})])
        ergebnis = sc.request_with_retry("x", {}, session=session,
                                         sleeper=lambda s: None)
        assert ergebnis.ok
        assert ergebnis.attempts == 3
        assert ergebnis.retried == 2

    def test_nach_erschoepften_versuchen_wird_aufgegeben(self, monkeypatch):
        monkeypatch.setattr("src.api.apisports_api._headers", lambda: {})
        session = FakeSession([ConnectionError("weg")])
        ergebnis = sc.request_with_retry("x", {}, session=session,
                                         max_retries=2,
                                         sleeper=lambda s: None)
        assert not ergebnis.ok
        assert session.aufrufe == 3          # Erstversuch plus zwei
        # Der Text nennt die Ausnahmeart, aber keine Kopfzeilen.
        assert "ConnectionError" in ergebnis.error

    def test_ein_dauerhafter_fehler_wird_nicht_wiederholt(self, monkeypatch):
        """
        Ein 404 wird beim zweiten Versuch nicht zu einem 200, ein 401
        schon gar nicht. Wiederholungen verbrauchen dort nur Kontingent.
        """
        monkeypatch.setattr("src.api.apisports_api._headers", lambda: {})
        for code in (400, 401, 403, 404):
            session = FakeSession([FakeResponse(code)])
            ergebnis = sc.request_with_retry("x", {}, session=session,
                                             sleeper=lambda s: None)
            assert not ergebnis.ok
            assert session.aufrufe == 1, code
            assert ergebnis.retried == 0

    @pytest.mark.parametrize("code", (429, 500, 502, 503))
    def test_transiente_fehler_werden_wiederholt(self, monkeypatch, code):
        monkeypatch.setattr("src.api.apisports_api._headers", lambda: {})
        session = FakeSession([FakeResponse(code),
                               FakeResponse(200, {"response": [1]})])
        ergebnis = sc.request_with_retry("x", {}, session=session,
                                         sleeper=lambda s: None)
        assert ergebnis.ok
        assert ergebnis.retried == 1

    def test_retry_after_wird_beachtet(self, monkeypatch):
        monkeypatch.setattr("src.api.apisports_api._headers", lambda: {})
        gewartet = []
        session = FakeSession([
            FakeResponse(429, headers={"Retry-After": "7"}),
            FakeResponse(200, {"response": [1]})])
        sc.request_with_retry("x", {}, session=session,
                              sleeper=gewartet.append)
        assert gewartet == [7.0]

    def test_retry_after_wird_nach_oben_begrenzt(self, monkeypatch):
        monkeypatch.setattr("src.api.apisports_api._headers", lambda: {})
        gewartet = []
        session = FakeSession([
            FakeResponse(429, headers={"Retry-After": "3600"}),
            FakeResponse(200, {"response": [1]})])
        sc.request_with_retry("x", {}, session=session,
                              sleeper=gewartet.append)
        assert gewartet == [sc.BACKOFF_MAX_SECONDS]

    def test_das_backoff_waechst_und_bleibt_begrenzt(self):
        import random

        rng = random.Random(1)
        werte = [sc._backoff(n, rng) for n in range(1, 10)]
        assert all(w <= sc.BACKOFF_MAX_SECONDS for w in werte)
        assert werte[0] < werte[3]

    def test_ein_kontingentfehler_mit_http_200_wird_erkannt(self, monkeypatch):
        """API-Sports meldet Limits teilweise im Body statt im Status."""
        monkeypatch.setattr("src.api.apisports_api._headers", lambda: {})
        session = FakeSession([FakeResponse(
            200, {"errors": {"requests": "limit reached"}})])
        ergebnis = sc.request_with_retry("x", {}, session=session,
                                         max_retries=1,
                                         sleeper=lambda s: None)
        assert not ergebnis.ok
        assert "Kontingent" in ergebnis.error

    def test_die_kontingentkopfzeilen_werden_gelesen(self):
        quota = sc.parse_quota({
            "X-RateLimit-requests-Limit": "7500",
            "x-ratelimit-requests-remaining": "6973",
            "x-rapidapi-key": "GEHEIM",
            "Server": "cloudflare"})
        assert quota["x-ratelimit-requests-limit"] == 7500
        assert quota["x-ratelimit-requests-remaining"] == 6973
        # NUR die vier bekannten Namen - alles andere bleibt draussen.
        assert set(quota) <= set(sc.QUOTA_HEADERS)
        assert "GEHEIM" not in json.dumps(quota)

    def test_unbrauchbare_kopfzeilen_werfen_nicht(self):
        assert sc.parse_quota({"x-ratelimit-remaining": "keine Zahl"}) \
            == {"x-ratelimit-remaining": None}
        assert sc.parse_quota(None) == {}


class TestKontingentgrenze:

    def test_der_lauf_stoppt_vor_der_kontingentgrenze(self, archiv):
        transport = FakeTransport(
            standard=_squad_antwort(),
            quota={"x-ratelimit-requests-remaining": 100,
                   "x-ratelimit-requests-limit": 7500})
        plan = [_scope(team=t) for t in (1, 2, 3, 4, 5)]

        bericht = sc.run_collection(plan, transport=transport,
                                    quota_margin=500)
        # Die erste Anfrage laeuft (die Quote ist vorher unbekannt),
        # danach greift die Grenze.
        assert bericht["attempted_scopes"] == 1
        assert bericht["skipped_scopes"] == 4
        assert "Kontingentgrenze" in bericht["halted_reason"]
        assert bericht["status"] == sc.RUN_PARTIAL

    def test_ohne_kontingentangabe_laeuft_er_weiter(self, archiv):
        transport = FakeTransport(standard=_squad_antwort(), quota={})
        plan = [_scope(team=t) for t in (1, 2, 3)]
        bericht = sc.run_collection(plan, transport=transport)
        assert bericht["attempted_scopes"] == 3
        assert bericht["halted_reason"] is None


# ===========================================================================
# 18-19. Teilerfolg und Wiederaufnahme
# ===========================================================================

class TestTeilerfolg:

    def test_ein_fehlgeschlagener_scope_zerstoert_die_uebrigen_nicht(
            self, archiv):
        gut = _squad_antwort(team_id=1)
        transport = FakeTransport(
            antworten={
                (av.ENDPOINT_SQUAD, (("team", "1"),)): gut,
                (av.ENDPOINT_SQUAD, (("team", "3"),)):
                    _squad_antwort(team_id=3),
            },
            standard=sc.TransportResult(False, error="HTTP 500",
                                        status_code=500))

        plan = [_scope(team=t) for t in (1, 2, 3)]
        bericht = sc.run_collection(plan, transport=transport)

        assert bericht["snapshots_stored"] == 2
        assert bericht["scopes_failed"] == 1
        assert bericht["status"] == sc.RUN_PARTIAL
        assert len(archive.list_snapshots(av.KIND_SQUAD)) == 2

    def test_jeder_snapshot_wird_sofort_geschrieben(self, archiv):
        """
        Nicht erst am Ende: Ein Abbruch nach dem zehnten von dreihundert
        Scopes soll zehn Snapshots hinterlassen, nicht null.
        """
        geschrieben = []

        def transport(endpoint, params):
            geschrieben.append(len(archive.list_snapshots(av.KIND_SQUAD)))
            return sc.TransportResult(
                True, payload=_squad_antwort(team_id=params["team"]),
                status_code=200)

        sc.run_collection([_scope(team=t) for t in (1, 2, 3)],
                          transport=transport)
        assert geschrieben == [0, 1, 2]

    def test_ein_lauf_ist_nach_abbruch_fortsetzbar(self, archiv):
        transport = FakeTransport(standard=None)
        transport.antworten = {
            (av.ENDPOINT_SQUAD, (("team", str(t)),)): _squad_antwort(team_id=t)
            for t in (1, 2, 3)}

        plan = [_scope(team=t) for t in (1, 2, 3)]
        erst = sc.run_collection(plan[:2], transport=transport)
        assert erst["attempted_scopes"] == 2

        erledigt = {s.identity() for s in plan[:2]}
        zweit = sc.run_collection(plan, transport=transport,
                                  already_done=erledigt)
        assert zweit["attempted_scopes"] == 1
        assert zweit["skipped_scopes"] == 2
        assert len(archive.list_snapshots(av.KIND_SQUAD)) == 3

    def test_ein_zweiter_lauf_am_selben_tag_schreibt_nichts_doppelt(
            self, archiv):
        transport = FakeTransport(standard=_squad_antwort())
        plan = [_scope()]
        sc.run_collection(plan, transport=transport)
        zweit = sc.run_collection(plan, transport=transport)
        assert zweit["snapshots_unchanged"] == 1
        assert zweit["snapshots_stored"] == 0
        assert len(archive.list_snapshots(av.KIND_SQUAD)) == 1


# ===========================================================================
# 20-21. Sperre
# ===========================================================================

class TestSperre:

    def test_ein_zweiter_paralleler_lauf_wird_verhindert(self, tmp_path):
        pfad = str(tmp_path / "collector.lock")
        erste = sc.CollectorLock(path=pfad).acquire()
        try:
            with pytest.raises(sc.CollectorBusy):
                sc.CollectorLock(path=pfad).acquire()
        finally:
            erste.release()

    def test_nach_der_freigabe_geht_es_wieder(self, tmp_path):
        pfad = str(tmp_path / "collector.lock")
        with sc.CollectorLock(path=pfad):
            pass
        zweite = sc.CollectorLock(path=pfad).acquire()
        zweite.release()
        assert not os.path.exists(pfad)

    def test_eine_frische_sperre_eines_toten_prozesses_bleibt_stehen(
            self, tmp_path):
        """
        Alter UND toter Prozess muessen zusammenkommen. Nur nach Alter
        zu brechen wuerde einen langsamen, aber lebenden Lauf
        abschiessen.
        """
        pfad = str(tmp_path / "collector.lock")
        with open(pfad, "w", encoding="utf-8") as handle:
            json.dump({"pid": 999999,
                       "started_at": datetime.now(UTC).isoformat()}, handle)

        sperre = sc.CollectorLock(path=pfad)
        verwaist, grund = sperre.stale_state()
        assert verwaist is False
        assert "alt" in grund
        with pytest.raises(sc.CollectorBusy):
            sperre.acquire()

    def test_eine_alte_sperre_eines_toten_prozesses_wird_uebernommen(
            self, tmp_path):
        pfad = str(tmp_path / "collector.lock")
        alt = datetime.now(UTC) - timedelta(seconds=sc.STALE_LOCK_SECONDS + 60)
        with open(pfad, "w", encoding="utf-8") as handle:
            json.dump({"pid": 999999, "started_at": alt.isoformat()}, handle)

        sperre = sc.CollectorLock(path=pfad)
        verwaist, grund = sperre.stale_state()
        assert verwaist is True
        sperre.acquire()
        try:
            assert sperre.takeover
            assert json.load(open(pfad, encoding="utf-8"))["pid"] == os.getpid()
        finally:
            sperre.release()

    def test_eine_sperre_des_eigenen_lebenden_prozesses_wird_nie_gebrochen(
            self, tmp_path):
        pfad = str(tmp_path / "collector.lock")
        alt = datetime.now(UTC) - timedelta(seconds=sc.STALE_LOCK_SECONDS + 60)
        with open(pfad, "w", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "started_at": alt.isoformat()},
                      handle)

        verwaist, grund = sc.CollectorLock(path=pfad).stale_state()
        assert verwaist is False
        assert "laeuft noch" in grund

    def test_eine_frische_unlesbare_sperre_blockiert(self, tmp_path):
        pfad = str(tmp_path / "collector.lock")
        with open(pfad, "w", encoding="utf-8") as handle:
            handle.write("{kaputt")
        verwaist, _ = sc.CollectorLock(path=pfad).stale_state()
        assert verwaist is False

    def test_die_sperre_traegt_prozess_und_zeit(self, tmp_path):
        pfad = str(tmp_path / "collector.lock")
        with sc.CollectorLock(path=pfad):
            inhalt = json.load(open(pfad, encoding="utf-8"))
        assert inhalt["pid"] == os.getpid()
        assert inhalt["collector_version"] == av.COLLECTOR_VERSION
        datetime.fromisoformat(inhalt["started_at"])

    def test_die_sperre_verlaesst_sich_nicht_auf_fcntl_oder_msvcrt(self):
        """
        Windows kennt kein fcntl, Linux kein msvcrt. Eine Sperre, die
        eines von beiden benutzt, greift genau auf der Haelfte der
        Umgebungen nicht - und zwar lautlos.
        """
        import ast
        import inspect

        # Die Docstrings ERKLAEREN, warum fcntl und msvcrt nicht
        # benutzt werden - eine Textsuche faende genau diese Erklaerung
        # und schluege fehl. Geprueft wird deshalb der ausfuehrbare
        # Code, ohne Dokumentation und Kommentare.
        baum = ast.parse(inspect.getsource(sc.CollectorLock))
        for knoten in ast.walk(baum):
            if isinstance(knoten, ast.Expr) and isinstance(
                    knoten.value, ast.Constant) and isinstance(
                        knoten.value.value, str):
                knoten.value.value = ""
        code = ast.unparse(baum)

        assert "fcntl" not in code
        assert "msvcrt" not in code
        assert "O_EXCL" in code


# ===========================================================================
# 22-24. Probelauf, Grenze, Bericht
# ===========================================================================

class TestLaufmodi:

    def test_ein_probelauf_schreibt_nichts(self, archiv):
        transport = FakeTransport(standard=_squad_antwort())
        bericht = sc.run_collection([_scope()], transport=transport,
                                    dry_run=True)
        assert bericht["dry_run"] is True
        assert bericht["outcomes"].get(sc.OUTCOME_DRY_RUN) == 1
        assert archive.list_snapshots(av.KIND_SQUAD) == []

    def test_ein_probelauf_fragt_trotzdem_ab(self, archiv):
        """
        Sonst pruefte er nichts. Ein Trockenlauf soll beweisen, dass
        Umgebung, Schluessel und Antwortform stimmen.
        """
        transport = FakeTransport(standard=_squad_antwort())
        sc.run_collection([_scope()], transport=transport, dry_run=True)
        assert transport.anzahl() == 1

    def test_der_probemodus_haelt_seine_grenze_ein(self, archiv):
        transport = FakeTransport(standard=_squad_antwort())
        plan = [_scope(team=t) for t in range(1, 11)]
        bericht = sc.run_collection(plan, transport=transport, limit=3)
        assert bericht["attempted_scopes"] == 3
        assert bericht["skipped_scopes"] == 7
        assert transport.anzahl() == 3

    def test_der_bericht_unterscheidet_die_drei_zustaende(self, archiv):
        gut = FakeTransport(standard=_squad_antwort())
        vollstaendig = sc.run_collection([_scope()], transport=gut)
        assert vollstaendig["status"] == sc.RUN_COMPLETE

        teilweise = sc.run_collection(
            [_scope(team=1), _scope(team=2)],
            transport=FakeTransport(
                antworten={(av.ENDPOINT_SQUAD, (("team", "1"),)):
                           _squad_antwort(team_id=1)},
                standard=sc.TransportResult(False, error="HTTP 500")))
        assert teilweise["status"] == sc.RUN_PARTIAL

        gescheitert = sc.run_collection(
            [_scope()],
            transport=FakeTransport(
                standard=sc.TransportResult(False, error="HTTP 500")))
        assert gescheitert["status"] == sc.RUN_FAILED

    def test_der_bericht_enthaelt_die_pflichtfelder(self, archiv):
        transport = FakeTransport(standard=_squad_antwort())
        bericht = sc.run_collection([_scope()], transport=transport)
        for feld in ("run_report_version", "collector_version",
                     "snapshot_schema_version", "started_at", "finished_at",
                     "status", "planned_scopes", "attempted_scopes",
                     "skipped_scopes", "plan_fingerprint", "outcomes",
                     "requests_attempted", "requests_retried",
                     "requests_by_endpoint_and_outcome", "snapshots_stored",
                     "snapshots_unchanged", "scopes_empty", "scopes_failed",
                     "failures", "skipped", "observed_quota", "coverage"):
            assert feld in bericht, feld

    def test_der_bericht_weist_ausgelassene_scopes_mit_grund_aus(self, archiv):
        transport = FakeTransport(standard=_squad_antwort())
        bericht = sc.run_collection([_scope(team=1), _scope(team=2)],
                                    transport=transport, limit=1)
        assert len(bericht["skipped"]) == 1
        assert "Grenze" in bericht["skipped"][0]["reason"]

    def test_die_abdeckung_nennt_die_nicht_erfassten(self, archiv):
        transport = FakeTransport(
            antworten={(av.ENDPOINT_SQUAD, (("team", "1"),)):
                       _squad_antwort(team_id=1)},
            standard=sc.TransportResult(False, error="HTTP 500"))
        bericht = sc.run_collection([_scope(team=1), _scope(team=2)],
                                    transport=transport)
        deckung = bericht["coverage"][av.KIND_SQUAD]
        assert deckung["planned"] == 2
        assert deckung["covered"] == 1
        assert deckung["not_covered"] == [av.squad_key(2)]
        assert deckung["coverage_pct"] == 50.0

    def test_der_planfingerabdruck_ist_deterministisch(self):
        teams = [{"team_id": 2, "label": "B"}, {"team_id": 1, "label": "A"}]
        a = sc.plan_scopes(teams, [], 2025)
        b = sc.plan_scopes(list(reversed(teams)), [], 2025)
        assert sc.plan_fingerprint(a) == sc.plan_fingerprint(b)

    def test_der_bericht_wird_atomar_und_ohne_ueberschreiben_geschrieben(
            self, tmp_path):
        bericht = {"status": "complete"}
        moment = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
        a = sc.write_report(bericht, directory=str(tmp_path), now=moment)
        b = sc.write_report(bericht, directory=str(tmp_path), now=moment)
        assert a != b
        assert json.load(open(a, encoding="utf-8"))["status"] == "complete"
        assert not [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]

    def test_zwei_gleiche_laeufe_ergeben_denselben_bericht(self, archiv):
        """Determinismus: gleiche Eingabe, gleicher Bericht."""
        moment = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

        def lauf():
            return sc.run_collection([_scope()],
                                     transport=FakeTransport(
                                         standard=_squad_antwort()),
                                     dry_run=True, now=moment)

        a, b = lauf(), lauf()
        for feld in ("status", "plan_fingerprint", "outcomes",
                     "requests_attempted", "coverage", "planned_scopes"):
            assert a[feld] == b[feld], feld


# ===========================================================================
# 25-28. Der C7-Reader
# ===========================================================================

class TestReader:

    def _lege_an(self, key, wert, stunde):
        return archive.archive_snapshot(
            av.KIND_SQUAD, key, wert,
            extra_meta={"content_fingerprint": str(wert),
                        "endpoint": av.ENDPOINT_SQUAD,
                        "snapshot_schema_version": 1},
            captured_at=datetime(2026, 3, 1, stunde, 0, tzinfo=UTC))

    def test_nur_daten_strikt_vor_dem_cutoff(self, archiv):
        self._lege_an("team_1", {"v": "frueh"}, 10)
        self._lege_an("team_1", {"v": "spaet"}, 14)

        stand = sr.snapshot_before(av.KIND_SQUAD, "team_1",
                                   datetime(2026, 3, 1, 12, 0, tzinfo=UTC))
        assert stand["available"] is True
        assert stand["payload"]["v"] == "frueh"

    def test_ein_spaeterer_snapshot_veraendert_eine_fruehere_abfrage_nicht(
            self, archiv):
        self._lege_an("team_1", {"v": "frueh"}, 10)
        cutoff = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
        vorher = sr.snapshot_before(av.KIND_SQUAD, "team_1", cutoff)

        self._lege_an("team_1", {"v": "spaeter"}, 20)
        nachher = sr.snapshot_before(av.KIND_SQUAD, "team_1", cutoff)

        assert vorher["payload"] == nachher["payload"]
        assert vorher["captured_at"] == nachher["captured_at"]

    def test_gleicher_zeitstempel_zaehlt_nicht_als_bekannt(self, archiv):
        """
        Ein Stand, der zur Anpfiffsekunde erhoben wurde, koennte bereits
        die Aufstellung enthalten. Die Regel ist streng und
        absichtlich - derselbe Vertrag wie in V2-C1.
        """
        moment = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
        self._lege_an("team_1", {"v": "genau"}, 12)

        assert sr.snapshot_before(av.KIND_SQUAD, "team_1",
                                  moment)["available"] is False
        # Mit inclusive=True kaeme er - das ist die dokumentierte
        # Ausnahme und NICHT der Standard.
        assert archive.latest_snapshot_before(
            av.KIND_SQUAD, moment.isoformat(), key="team_1",
            inclusive=True) is not None

    def test_ein_fehlender_stand_bleibt_sichtbar_fehlend(self, archiv):
        stand = sr.snapshot_before(av.KIND_SQUAD, "team_1",
                                   datetime(2026, 3, 1, 12, 0, tzinfo=UTC))
        assert stand["available"] is False
        assert stand["missing_reason"] == sr.MISSING_NO_HISTORY
        assert stand["payload"] is None
        # KEINE neutrale Null und kein leerer Kader.
        assert stand["payload"] != {}
        assert stand["payload"] != []

    def test_der_stand_traegt_herkunft_und_alter(self, archiv):
        self._lege_an("team_1", {"v": 1}, 10)
        stand = sr.snapshot_before(av.KIND_SQUAD, "team_1",
                                   datetime(2026, 3, 3, 10, 0, tzinfo=UTC))
        assert stand["age_days"] == 2.0
        assert stand["is_stale"] is False
        assert stand["provenance"]["endpoint"] == av.ENDPOINT_SQUAD
        assert stand["provenance"]["snapshot_schema_version"] == 1

    def test_ein_alter_stand_wird_als_veraltet_gekennzeichnet(self, archiv):
        self._lege_an("team_1", {"v": 1}, 10)
        stand = sr.snapshot_before(
            av.KIND_SQUAD, "team_1",
            datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
            + timedelta(days=sr.STALE_AFTER_DAYS + 1))
        assert stand["is_stale"] is True

    def test_bei_gleichem_zeitstempel_gewinnt_der_zuletzt_geschriebene(
            self, archiv):
        moment = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
        archive.archive_snapshot(av.KIND_SQUAD, "team_1", {"v": "erst"},
                                 captured_at=moment)
        archive.archive_snapshot(av.KIND_SQUAD, "team_1", {"v": "zuletzt"},
                                 captured_at=moment)
        stand = sr.snapshot_before(av.KIND_SQUAD, "team_1",
                                   datetime(2026, 3, 1, 11, 0, tzinfo=UTC))
        assert stand["payload"]["v"] == "zuletzt"

    def test_der_zustandswechsel_wird_am_richtigen_punkt_sichtbar(self, archiv):
        self._lege_an("team_1", {"v": "alt"}, 8)
        self._lege_an("team_1", {"v": "neu"}, 16)

        for stunde, erwartet in ((9, "alt"), (15, "alt"), (17, "neu")):
            stand = sr.snapshot_before(
                av.KIND_SQUAD, "team_1",
                datetime(2026, 3, 1, stunde, 0, tzinfo=UTC))
            assert stand["payload"]["v"] == erwartet, stunde

    def test_squad_before_benutzt_den_richtigen_schluessel(self, archiv):
        self._lege_an(av.squad_key(157), {"v": 1}, 10)
        stand = sr.squad_before(157, datetime(2026, 3, 1, 12, 0, tzinfo=UTC))
        assert stand["available"] is True


class TestReaderVerfuegbarkeit:

    def _lege_an(self, eintraege, stunde=10):
        nutz, _ = av.normalise_availability(eintraege, league_id=78,
                                            season=2025)
        return archive.archive_snapshot(
            av.KIND_AVAILABILITY, av.availability_key(78, 2025), nutz,
            captured_at=datetime(2026, 3, 1, stunde, 0, tzinfo=UTC))

    def test_eintraege_nach_dem_cutoff_werden_gefiltert(self, archiv):
        """
        Die zweite Zeitebene, die man leicht vergisst: Der Snapshot ist
        vor dem Cutoff ERHOBEN, aber seine Eintraege koennen Partien
        NACH dem Cutoff beschreiben. Sie mitzuzaehlen hiesse, die
        Zukunft zu kennen.
        """
        self._lege_an([
            {"player": {"id": 1, "type": "Missing Fixture", "reason": "Injury"},
             "team": {"id": 157},
             "fixture": {"id": 1, "date": "2026-02-01T18:00:00+00:00"}},
            {"player": {"id": 2, "type": "Missing Fixture", "reason": "Injury"},
             "team": {"id": 157},
             "fixture": {"id": 2, "date": "2026-04-01T18:00:00+00:00"}},
        ], stunde=10)

        stand = sr.availability_entries_before(
            78, 2025, datetime(2026, 3, 1, 12, 0, tzinfo=UTC))
        assert stand["available"] is True
        assert stand["entries_total"] == 2
        assert stand["entries_effective_before_cutoff"] == 1
        assert stand["entries_after_cutoff"] == 1
        assert [e["player_id"] for e in stand["entries"]] == [1]

    def test_eintraege_ohne_zeitpunkt_werden_nicht_mitgeliefert(self, archiv):
        self._lege_an([
            {"player": {"id": 1, "type": "Missing Fixture", "reason": "Injury"},
             "team": {"id": 157}, "fixture": {}},
        ], stunde=10)
        stand = sr.availability_entries_before(
            78, 2025, datetime(2026, 3, 1, 12, 0, tzinfo=UTC))
        assert stand["entries"] == []
        assert stand["entries_without_effective_at"] == 1

    def test_nach_team_gefiltert_werden_kann(self, archiv):
        self._lege_an([
            {"player": {"id": 1, "type": "Missing Fixture", "reason": "Injury"},
             "team": {"id": 157},
             "fixture": {"id": 1, "date": "2026-02-01T18:00:00+00:00"}},
            {"player": {"id": 2, "type": "Missing Fixture", "reason": "Injury"},
             "team": {"id": 165},
             "fixture": {"id": 2, "date": "2026-02-02T18:00:00+00:00"}},
        ], stunde=10)
        stand = sr.availability_entries_before(
            78, 2025, datetime(2026, 3, 1, 12, 0, tzinfo=UTC), team_id=157)
        assert [e["player_id"] for e in stand["entries"]] == [1]

    def test_ohne_snapshot_bleibt_der_fehlzustand_sichtbar(self, archiv):
        stand = sr.availability_entries_before(
            78, 2025, datetime(2026, 3, 1, 12, 0, tzinfo=UTC))
        assert stand["available"] is False
        assert stand["entries"] is None
        assert stand["missing_reason"] == sr.MISSING_NO_HISTORY

    def test_das_archivfenster_nennt_den_nutzbaren_beginn(self, archiv):
        leer = sr.archive_window(av.KIND_AVAILABILITY)
        assert leer["snapshots"] == 0
        assert leer["usable_from"] is None

        self._lege_an([], stunde=10)
        gefuellt = sr.archive_window(av.KIND_AVAILABILITY)
        assert gefuellt["snapshots"] == 1
        assert gefuellt["usable_from"] is not None


# ===========================================================================
# Normalisierung
# ===========================================================================

class TestNormalisierung:

    @pytest.mark.parametrize("roh,erwartet", [
        ("Red Card", av.ABSENCE_SUSPENSION),
        ("Yellow Cards", av.ABSENCE_SUSPENSION),
        ("Red card Suspended", av.ABSENCE_SUSPENSION),
        ("Suspended", av.ABSENCE_SUSPENSION),
        ("Knee Injury", av.ABSENCE_INJURY),
        ("Sprained ankle", av.ABSENCE_INJURY),
        ("Muscle bruise", av.ABSENCE_INJURY),
        ("Cruciate ligament stretch", av.ABSENCE_INJURY),
        ("Groin operation", av.ABSENCE_INJURY),
        ("Back trouble", av.ABSENCE_INJURY),
        ("Wound", av.ABSENCE_INJURY),
        ("Illness", av.ABSENCE_ILLNESS),
        ("Appendicitis", av.ABSENCE_ILLNESS),
        ("Stomach complaints", av.ABSENCE_ILLNESS),
        ("Lacking Match Fitness", av.ABSENCE_FITNESS),
        ("Inactive", av.ABSENCE_FITNESS),
        ("Personal reasons", av.ABSENCE_PERSONAL),
        (None, av.ABSENCE_UNKNOWN),
        ("", av.ABSENCE_UNKNOWN),
    ])
    def test_die_gruende_werden_richtig_kategorisiert(self, roh, erwartet):
        assert av.normalise_absence_reason(roh) == erwartet

    def test_eine_sperre_wird_nie_als_verletzung_gefuehrt(self):
        """
        Die Reihenfolge der Muster entscheidet. Sperren zuerst - sonst
        faenge ein Verletzungsmuster einen Eintrag wie "Red card
        Suspended" ein, und das Modell haelte eine Sperre fuer einen
        koerperlichen Schaden.
        """
        for text in ("Red Card", "Yellow Cards", "Red card Suspended"):
            assert av.normalise_absence_reason(text) == av.ABSENCE_SUSPENSION

    def test_ein_unbekannter_grund_wird_sichtbar(self):
        assert av.normalise_absence_reason("Zeitreiseunfall") \
            == av.ABSENCE_OTHER

    def test_der_rohwert_bleibt_erhalten(self):
        nutz, _ = av.normalise_availability([
            {"player": {"id": 1, "type": "Questionable",
                        "reason": "Jumpers knee"},
             "team": {"id": 2},
             "fixture": {"id": 9, "date": "2025-10-01T18:30:00+00:00"}}])
        eintrag = nutz["entries"][0]
        assert eintrag["raw_reason"] == "Jumpers knee"
        assert eintrag["raw_type"] == "Questionable"
        assert eintrag["status"] == av.STATUS_DOUBTFUL

    @pytest.mark.parametrize("roh,erwartet", [
        ("Missing Fixture", av.STATUS_OUT),
        ("Questionable", av.STATUS_DOUBTFUL),
        ("Etwas Neues", av.STATUS_UNKNOWN),
        (None, av.STATUS_UNKNOWN),
    ])
    def test_der_status_wird_richtig_uebersetzt(self, roh, erwartet):
        assert av.normalise_availability_status(roh) == erwartet

    def test_ein_spieler_ohne_kennung_wird_verworfen_nicht_geraten(self):
        nutz, beanstandungen = av.normalise_squad(
            [{"team": {"id": 1},
              "players": [{"name": "Ohne ID"}, {"id": 5, "name": "Mit ID"}]}])
        assert nutz["player_count"] == 1
        assert any("ohne Kennung" in b for b in beanstandungen)

    def test_ein_entfernter_spieler_wird_nicht_als_ausfall_gefuehrt(self):
        """
        Wer aus dem Kader verschwindet, ist nicht belegt verletzt - er
        ist verkauft, verliehen oder abgemeldet. Der Kadersnapshot
        stellt nur fest, wer DRIN ist.
        """
        nutz, _ = av.normalise_squad(
            [{"team": {"id": 1}, "players": [{"id": 5}]}])
        assert set(nutz) == {"team_id", "team_name", "player_count",
                             "players", "effective_at", "effective_at_status"}
        assert "unavailable" not in json.dumps(nutz)
        assert "injured" not in json.dumps(nutz)


# ===========================================================================
# Planung
# ===========================================================================

class TestPlanung:

    def test_verfuegbarkeit_kommt_vor_kadern(self):
        """
        Eine Ligaabfrage liefert die Ausfaelle einer ganzen Saison in
        EINER Anfrage, ein Kader kostet eine je Mannschaft. Bricht der
        Lauf ab, soll der wertvollere Teil gesichert sein.
        """
        plan = sc.plan_scopes(
            [{"team_id": 1, "label": "T", "priority": 60}],
            [{"league_id": 78, "label": "L", "priority": 0}], 2025)
        assert plan[0].kind == av.KIND_AVAILABILITY
        assert plan[-1].kind == av.KIND_SQUAD

    def test_die_reihenfolge_ist_reproduzierbar(self):
        teams = [{"team_id": t, "label": f"T{t}", "priority": 60}
                 for t in (5, 1, 3)]
        a = [s.key for s in sc.plan_scopes(teams, [], 2025)]
        b = [s.key for s in sc.plan_scopes(list(reversed(teams)), [], 2025)]
        assert a == b

    def test_nur_die_gewuenschten_arten_werden_geplant(self):
        plan = sc.plan_scopes([{"team_id": 1}], [{"league_id": 78}], 2025,
                              kinds=(av.KIND_AVAILABILITY,))
        assert {s.kind for s in plan} == {av.KIND_AVAILABILITY}

    def test_teams_kommen_ohne_anfrage_aus_den_lokalen_ligadateien(
            self, tmp_path):
        """
        Die V2-C2B-Dateien tragen API-Sports-Kennungen. Sie zu lesen
        kostet nichts - im Gegensatz zu /teams je Liga.
        """
        (tmp_path / "XX1_2025.json").write_text(json.dumps({
            "teams": {"11": {"name": "Alpha"}, "12": {"name": "Beta"}}}),
            encoding="utf-8")
        registry = {"xx1": {"code": "XX1", "name": "X-Liga",
                            "apisports_id": 999}}
        teams = ss.teams_from_local_league_files(
            2025, directory=str(tmp_path), registry=registry)
        assert sorted(t["team_id"] for t in teams) == [11, 12]

    def test_eine_fehlende_saison_faellt_auf_die_vorsaison_zurueck(
            self, tmp_path):
        (tmp_path / "XX1_2024.json").write_text(json.dumps({
            "teams": {"11": {"name": "Alpha"}}}), encoding="utf-8")
        registry = {"xx1": {"code": "XX1", "apisports_id": 999}}
        teams = ss.teams_from_local_league_files(
            2025, directory=str(tmp_path), registry=registry)
        assert [t["team_id"] for t in teams] == [11]
        assert teams[0]["source"] == "XX1_2024"

    def test_ein_ausfall_der_teamaufloesung_beendet_den_lauf_nicht(self):
        def kaputt(key, season):
            raise RuntimeError("Anbieter weg")

        assert ss.teams_from_api(["bl1"], 2025, resolver=kaputt) == []

    def test_die_wichtigere_liga_gewinnt_bei_doppelten_teams(self):
        def resolver(key, season):
            return {157: "Bayern"}

        teams = ss.teams_from_api(["cl", "bl1"], 2025, resolver=resolver)
        assert len(teams) == 1
        assert teams[0]["priority"] == ss.PRIORITY_SQUAD_CL

    def test_discover_liefert_eine_nachvollziehbare_diagnose(self, tmp_path):
        teams, leagues, diagnose = ss.discover(
            2025, team_resolver=lambda k, s: {}, directory=str(tmp_path),
            registry={})
        assert diagnose["teams"] == len(teams)
        assert diagnose["leagues"] == len(leagues)
        assert any(q["source"] == "LEAGUE_IDS" for q in diagnose["sources"])


# ===========================================================================
# 29-31. Geheimnisse, Unabhaengigkeit
# ===========================================================================

class TestGeheimnisse:

    def test_kein_schluessel_im_bericht(self, archiv, monkeypatch):
        monkeypatch.setenv("APISPORTS_KEY", "SUPERGEHEIM123")
        transport = FakeTransport(
            standard=_squad_antwort(),
            quota={"x-ratelimit-requests-remaining": 7000})
        bericht = sc.run_collection([_scope()], transport=transport)
        assert "SUPERGEHEIM123" not in json.dumps(bericht, default=str)

    def test_kein_schluessel_im_snapshot(self, archiv, monkeypatch):
        monkeypatch.setenv("APISPORTS_KEY", "SUPERGEHEIM123")
        transport = FakeTransport(standard=_squad_antwort())
        sc.collect_scope(_scope(), transport=transport)
        inhalt = open(archive.list_snapshots(av.KIND_SQUAD)[0]["path"],
                      encoding="utf-8").read()
        assert "SUPERGEHEIM123" not in inhalt
        assert "x-rapidapi-key" not in inhalt.lower()

    def test_der_anfrageumfang_enthaelt_nur_parameter(self, archiv):
        transport = FakeTransport(standard=_squad_antwort())
        sc.collect_scope(_scope(team=157), transport=transport)
        eintrag = archive.load_snapshot_file(
            archive.list_snapshots(av.KIND_SQUAD)[0]["path"])
        assert eintrag["meta"]["request_scope"] == {"team": 157}

    def test_eine_netzwerkausnahme_traegt_keine_kopfzeilen(self, monkeypatch):
        monkeypatch.setattr("src.api.apisports_api._headers",
                            lambda: {"x-rapidapi-key": "GEHEIM"})
        session = FakeSession([ConnectionError("Verbindung zu ... GEHEIM")])
        ergebnis = sc.request_with_retry("x", {}, session=session,
                                         max_retries=0,
                                         sleeper=lambda s: None)
        assert not ergebnis.ok
        assert "GEHEIM" not in ergebnis.error


class TestUnabhaengigkeit:

    def test_der_sammler_braucht_kein_flask(self):
        import inspect

        for modul in (sc, av, sr, ss):
            quelle = inspect.getsource(modul)
            assert "flask" not in quelle.lower(), modul.__name__
            assert "app.py" not in quelle, modul.__name__

    def test_der_sammler_braucht_keine_datenbank(self):
        import inspect

        for modul in (sc, av, sr, ss):
            quelle = inspect.getsource(modul)
            for verboten in ("sqlalchemy", "psycopg2", "db.session"):
                assert verboten not in quelle.lower(), modul.__name__

    def test_kein_modul_liest_selbst_einen_schluessel(self):
        import inspect

        for modul in (sc, av, sr, ss):
            quelle = inspect.getsource(modul)
            assert "APISPORTS_KEY" not in quelle, modul.__name__
            assert "load_dotenv" not in quelle, modul.__name__

    def test_diese_datei_braucht_keinen_bestand(self):
        import pathlib

        quelle = pathlib.Path(__file__).read_text(encoding="utf-8")
        for teil in ("data/" + "historical", "data/" + "cache",
                     "data/" + "big_games", "data/" + "player_pool"):
            assert teil not in quelle

    def test_der_sammler_trainiert_kein_modell(self):
        import inspect

        for modul in (sc, av, sr, ss):
            quelle = inspect.getsource(modul)
            for verboten in ("fit_side", "train_cl_model", "save_bundle",
                             "release_stage", "feature_columns"):
                assert verboten not in quelle, modul.__name__
