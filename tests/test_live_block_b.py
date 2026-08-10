"""
Tests fuer Block LIVE B (Match Center).

Abgedeckt:
  A) Validierung des fixture-Parameters
  B) Normalisierung der Stammdaten (Uebersicht)
  C) Normalisierung der Aufstellungen
  D) Normalisierung der Ereignisse (Tor, Eigentor, Karten, Wechsel,
     Nachspielzeit, Sortierung, unbekannte Typen)
  E) Normalisierung der Statistiken (null bleibt null, nie 0)
  F) Adaptive Cache-TTL und Cross-Worker-Verhalten
  G) Fehlerfaelle und leere Datenlagen
  H) Oberflaeche: Match Card oeffnet, Reiter, Zurueckweg, Polling

Kein echter API-Request: alle Tests arbeiten auf synthetischen Antworten
im Format von /fixtures, /fixtures/events, /fixtures/lineups und
/fixtures/statistics.
"""

import os

import pytest

from src.api import live_api
from src.api.live_api import (
    EVENT_GOAL,
    EVENT_OWN_GOAL,
    EVENT_YELLOW,
    EVENT_RED,
    EVENT_SUBSTITUTION,
    EVENT_OTHER,
    PHASE_LIVE,
    PHASE_SCHEDULED,
    PHASE_FINISHED,
    build_match_center,
    classify_event,
    normalize_event,
    normalize_events,
    normalize_lineup,
    normalize_lineups,
    normalize_statistics,
    _ttl_for_match,
)
from src.utils.cache import (
    TTL_LIVE_MATCH_INPLAY,
    TTL_LIVE_MATCH_SCHEDULED,
    TTL_LIVE_MATCH_SETTLED,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(PROJECT_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


HOME_ID = 49
AWAY_ID = 42


def make_raw_fixture(status="FT", elapsed=90, extra=None,
                     home_goals=2, away_goals=1, fixture_id=555,
                     referee="C. Kavanagh", venue=True):
    return {
        "fixture": {
            "id": fixture_id,
            "date": "2026-08-11T20:30:00+02:00",
            "referee": referee,
            "venue": {"id": 1, "name": "Stamford Bridge", "city": "London"} if venue else {},
            "status": {"long": "Match Finished", "short": status,
                       "elapsed": elapsed, "extra": extra},
        },
        "league": {
            "id": 39, "name": "Premier League", "country": "England",
            "logo": "https://x/l39.png", "round": "Regular Season - 38",
        },
        "teams": {
            "home": {"id": HOME_ID, "name": "Chelsea", "logo": "https://x/49.png"},
            "away": {"id": AWAY_ID, "name": "Arsenal", "logo": "https://x/42.png"},
        },
        "goals": {"home": home_goals, "away": away_goals},
    }


def make_raw_event(elapsed=17, extra=None, kind="Goal", detail="Normal Goal",
                   team_id=HOME_ID, player=("P1", 1), assist=("P2", 2)):
    return {
        "time": {"elapsed": elapsed, "extra": extra},
        "team": {"id": team_id, "name": "Chelsea"},
        "player": {"id": player[1], "name": player[0]} if player else {"id": None, "name": None},
        "assist": {"id": assist[1], "name": assist[0]} if assist else {"id": None, "name": None},
        "type": kind,
        "detail": detail,
        "comments": None,
    }


def make_raw_lineup(team_id=HOME_ID, formation="4-2-3-1"):
    return {
        "team": {"id": team_id, "name": "Chelsea", "logo": "https://x/49.png"},
        "formation": formation,
        "coach": {"id": 100, "name": "Trainer X", "photo": "https://x/c.png"},
        "startXI": [
            {"player": {"id": 11, "name": "Keeper", "number": 1, "pos": "G", "grid": "1:1"}},
            {"player": {"id": 12, "name": "Verteidiger", "number": 4, "pos": "D", "grid": "2:1"}},
        ],
        "substitutes": [
            {"player": {"id": 21, "name": "Bank A", "number": 30, "pos": "M", "grid": None}},
        ],
    }


def make_raw_statistics(team_id, values):
    return {
        "team": {"id": team_id, "name": "T", "logo": "https://x/t.png"},
        "statistics": [{"type": key, "value": value} for key, value in values.items()],
    }


# ===========================================================================
# A) Parametervalidierung
# ===========================================================================

class TestFixtureValidierung:
    @pytest.fixture
    def client(self):
        import app as app_module
        app_module.app.config["TESTING"] = True
        return app_module.app.test_client()

    @pytest.fixture(autouse=True)
    def _isolierter_cache(self, tmp_path, monkeypatch):
        from src.utils import disk_cache
        monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path))

    def test_fehlender_parameter(self, client):
        response = client.get("/api/live-match")
        assert response.status_code == 400
        assert "error" in response.get_json()

    def test_nicht_numerisch(self, client):
        assert client.get("/api/live-match?fixture=abc").status_code == 400

    def test_negativ_und_null(self, client):
        assert client.get("/api/live-match?fixture=-5").status_code == 400
        assert client.get("/api/live-match?fixture=0").status_code == 400

    def test_unbekanntes_spiel_ergibt_404(self, client, monkeypatch):
        monkeypatch.setattr(
            live_api.apisports_api, "get_fixture_by_id",
            lambda fixture_id, timezone=None: [],
        )
        response = client.get("/api/live-match?fixture=123456")
        assert response.status_code == 404

    def test_gueltige_anfrage(self, client, monkeypatch):
        _patch_provider(monkeypatch)
        response = client.get("/api/live-match?fixture=555")
        assert response.status_code == 200
        assert response.get_json()["fixture"]["fixture_id"] == 555


def _patch_provider(monkeypatch, fixture=None, events=None, lineups=None, statistics=None):
    monkeypatch.setattr(
        live_api.apisports_api, "get_fixture_by_id",
        lambda fixture_id, timezone=None: [fixture if fixture is not None else make_raw_fixture()],
    )
    monkeypatch.setattr(
        live_api.apisports_api, "get_fixture_events",
        lambda fixture_id: events if events is not None else [],
    )
    monkeypatch.setattr(
        live_api.apisports_api, "get_fixture_lineups",
        lambda fixture_id: lineups if lineups is not None else [],
    )
    monkeypatch.setattr(
        live_api.apisports_api, "get_fixture_statistics",
        lambda fixture_id: statistics if statistics is not None else [],
    )


# ===========================================================================
# B) Stammdaten / Uebersicht
# ===========================================================================

class TestStammdaten:
    def test_grundfelder(self):
        payload = build_match_center(make_raw_fixture(), [], [], [])
        fixture = payload["fixture"]

        assert fixture["fixture_id"] == 555
        assert fixture["phase"] == PHASE_FINISHED
        assert fixture["status_short"] == "FT"
        assert fixture["status_label"] == "Ende"
        assert fixture["referee"] == "C. Kavanagh"
        assert fixture["venue_name"] == "Stamford Bridge"
        assert fixture["venue_city"] == "London"
        assert fixture["round"] == "Regular Season - 38"

    def test_teams_und_stand(self):
        payload = build_match_center(make_raw_fixture(), [], [], [])
        assert payload["home"]["id"] == HOME_ID
        assert payload["home"]["goals"] == 2
        assert payload["away"]["goals"] == 1
        assert payload["league"]["name"] == "Premier League"

    def test_anstosszeit_in_berliner_zeit(self):
        payload = build_match_center(make_raw_fixture(), [], [], [])
        assert payload["fixture"]["kickoff_time"] == "20:30"

    def test_laufendes_spiel_hat_minute(self):
        raw = make_raw_fixture(status="2H", elapsed=73)
        payload = build_match_center(raw, [], [], [])
        fixture = payload["fixture"]

        assert fixture["phase"] == PHASE_LIVE
        assert fixture["is_live"] is True
        assert fixture["elapsed"] == 73
        assert fixture["minute_label"] == "73'"

    def test_beendetes_spiel_zeigt_keine_minute(self):
        """Wie in der Tagesliste: bei FT liefert die Quelle weiter 90."""
        payload = build_match_center(make_raw_fixture(status="FT", elapsed=90), [], [], [])
        assert payload["fixture"]["elapsed"] is None
        assert payload["fixture"]["minute_label"] is None

    def test_nachspielzeit_im_minutenlabel(self):
        raw = make_raw_fixture(status="2H", elapsed=90, extra=4)
        payload = build_match_center(raw, [], [], [])
        assert payload["fixture"]["minute_label"] == "90+4'"

    def test_angesetztes_spiel_ohne_stand(self):
        raw = make_raw_fixture(status="NS", elapsed=None,
                               home_goals=None, away_goals=None, referee=None)
        payload = build_match_center(raw, [], [], [])

        assert payload["fixture"]["phase"] == PHASE_SCHEDULED
        assert payload["home"]["goals"] is None
        assert payload["fixture"]["referee"] is None

    def test_ohne_stammdaten_kein_payload(self):
        assert build_match_center(None, [], [], []) is None
        assert build_match_center({}, [], [], []) is None
        assert build_match_center({"fixture": {}}, [], [], []) is None

    def test_fehlende_felder_werfen_nicht(self):
        payload = build_match_center({"fixture": {"id": 7}}, [], [], [])
        assert payload is not None
        assert payload["fixture"]["venue_name"] is None
        assert payload["home"]["name"] is None
        assert payload["league"]["name"] is None

    def test_statusuebersetzung_wird_geteilt(self):
        """
        Match Center und Tagesliste muessen dieselbe Uebersetzung nutzen -
        zwei Quellen fuer dieselben Codes waeren eine Fehlerquelle.
        """
        source = _read("src", "api", "live_api.py")
        assert source.count("STATUS_MAP = {") == 1
        assert "classify_status(status_short)" in source


# ===========================================================================
# C) Aufstellungen
# ===========================================================================

class TestAufstellungen:
    def test_grundfelder(self):
        lineup = normalize_lineup(make_raw_lineup())

        assert lineup["team_id"] == HOME_ID
        assert lineup["formation"] == "4-2-3-1"
        assert lineup["coach"]["name"] == "Trainer X"
        assert len(lineup["start_xi"]) == 2
        assert len(lineup["substitutes"]) == 1

    def test_spielerfelder(self):
        lineup = normalize_lineup(make_raw_lineup())
        keeper = lineup["start_xi"][0]

        assert keeper["id"] == 11
        assert keeper["name"] == "Keeper"
        assert keeper["number"] == 1
        assert keeper["pos"] == "G"

    def test_player_id_bleibt_erhalten(self):
        """
        API-Football-Player-IDs sind derselbe Namensraum wie der
        FootSim-Spielerpool - hier darf keine eigene Identitaet entstehen.
        """
        lineup = normalize_lineup(make_raw_lineup())
        assert all(p["id"] is not None for p in lineup["start_xi"])

    def test_grid_bleibt_fuer_spaeteres_spielfeld_erhalten(self):
        lineup = normalize_lineup(make_raw_lineup())
        assert lineup["start_xi"][0]["grid"] == "1:1"

    def test_zuordnung_zu_heim_und_auswaerts(self):
        payload = build_match_center(
            make_raw_fixture(), [],
            [make_raw_lineup(team_id=AWAY_ID), make_raw_lineup(team_id=HOME_ID)],
            [],
        )
        assert payload["home_lineup"]["team_id"] == HOME_ID
        assert payload["away_lineup"]["team_id"] == AWAY_ID

    def test_fehlende_aufstellung_ist_kein_fehler(self):
        payload = build_match_center(make_raw_fixture(status="NS"), [], [], [])
        assert payload["home_lineup"] is None
        assert payload["away_lineup"] is None

    def test_muellblock_wird_uebersprungen(self):
        assert normalize_lineups([None, "kaputt", {}, {"team": {}}]) == []

    def test_spieler_ohne_identitaet_wird_verworfen(self):
        raw = make_raw_lineup()
        raw["startXI"].append({"player": {"id": None, "name": None}})
        lineup = normalize_lineup(raw)
        assert len(lineup["start_xi"]) == 2


# ===========================================================================
# D) Ereignisse
# ===========================================================================

class TestEreignisse:
    def test_tor_mit_assist(self):
        event = normalize_event(make_raw_event(
            kind="Goal", detail="Normal Goal",
            player=("Palmer", 1), assist=("Enzo", 2),
        ))
        assert event["type"] == EVENT_GOAL
        assert event["player"]["name"] == "Palmer"
        assert event["assist"]["name"] == "Enzo"

    def test_tor_ohne_assist(self):
        event = normalize_event(make_raw_event(kind="Goal", assist=None))
        assert event["type"] == EVENT_GOAL
        assert event["assist"] is None

    def test_eigentor(self):
        event = normalize_event(make_raw_event(kind="Goal", detail="Own Goal"))
        assert event["type"] == EVENT_OWN_GOAL

    def test_gelbe_karte(self):
        event = normalize_event(make_raw_event(kind="Card", detail="Yellow Card", assist=None))
        assert event["type"] == EVENT_YELLOW
        assert event["assist"] is None

    def test_rote_karte(self):
        event = normalize_event(make_raw_event(kind="Card", detail="Red Card", assist=None))
        assert event["type"] == EVENT_RED

    def test_wechsel_semantik(self):
        """
        Am echten Spiel geprueft: player = ausgewechselt, assist =
        eingewechselt. Daraus werden die eindeutigen Felder
        player_out/player_in, damit im Frontend niemand raten muss.
        """
        event = normalize_event(make_raw_event(
            kind="subst", detail="Substitution 1",
            player=("Raus", 1), assist=("Rein", 2),
        ))
        assert event["type"] == EVENT_SUBSTITUTION
        assert event["player_out"]["name"] == "Raus"
        assert event["player_in"]["name"] == "Rein"

    def test_wechsel_setzt_kein_assist(self):
        event = normalize_event(make_raw_event(kind="subst", detail="Substitution 1"))
        assert event["assist"] is None

    def test_karte_hat_weder_in_noch_out(self):
        event = normalize_event(make_raw_event(kind="Card", detail="Yellow Card"))
        assert event["player_in"] is None
        assert event["player_out"] is None

    def test_minutenlabel_ohne_nachspielzeit(self):
        assert normalize_event(make_raw_event(elapsed=17))["minute_label"] == "17'"

    def test_minutenlabel_mit_nachspielzeit(self):
        event = normalize_event(make_raw_event(elapsed=90, extra=3))
        assert event["minute_label"] == "90+3'"
        assert event["elapsed"] == 90
        assert event["extra"] == 3

    def test_sortierung_nach_minute_und_nachspielzeit(self):
        raw = [
            make_raw_event(elapsed=90, extra=4),
            make_raw_event(elapsed=17),
            make_raw_event(elapsed=45, extra=2),
            make_raw_event(elapsed=45),
            make_raw_event(elapsed=90, extra=1),
        ]
        labels = [e["minute_label"] for e in normalize_events(raw)]
        assert labels == ["17'", "45'", "45+2'", "90+1'", "90+4'"]

    def test_eintrag_ohne_minute_wandert_ans_ende(self):
        raw = [make_raw_event(elapsed=None), make_raw_event(elapsed=10)]
        events = normalize_events(raw)
        assert events[0]["elapsed"] == 10
        assert events[1]["elapsed"] is None

    def test_teamzugehoerigkeit_bleibt_erhalten(self):
        event = normalize_event(make_raw_event(team_id=AWAY_ID))
        assert event["team_id"] == AWAY_ID

    def test_unbekannter_typ_crasht_nicht(self):
        event = normalize_event(make_raw_event(kind="Nonsense", detail="Irgendwas"))
        assert event["type"] == EVENT_OTHER
        assert event["detail"] == "Irgendwas"

    def test_var_wird_erkannt(self):
        assert classify_event("Var", "Goal cancelled") == "var"

    def test_muelleintraege_werden_uebersprungen(self):
        assert normalize_events([None, "kaputt", 5]) == []

    def test_leere_ereignisliste(self):
        assert normalize_events([]) == []
        assert normalize_events(None) == []


# ===========================================================================
# E) Statistiken
# ===========================================================================

class TestStatistiken:
    def test_kernwerte_in_fester_reihenfolge(self):
        stats = normalize_statistics([
            make_raw_statistics(HOME_ID, {
                "Ball Possession": "54%", "Total Shots": 14, "Shots on Goal": 6,
                "Corner Kicks": 7, "Fouls": 11, "Offsides": 2,
            }),
            make_raw_statistics(AWAY_ID, {
                "Ball Possession": "46%", "Total Shots": 10, "Shots on Goal": 4,
                "Corner Kicks": 3, "Fouls": 13, "Offsides": 1,
            }),
        ], HOME_ID, AWAY_ID)

        assert [s["label"] for s in stats] == [
            "Ballbesitz", "Schüsse", "Schüsse aufs Tor", "Ecken", "Fouls", "Abseits",
        ]
        assert all(s["core"] for s in stats)

    def test_heim_und_auswaerts_richtig_zugeordnet(self):
        stats = normalize_statistics([
            make_raw_statistics(AWAY_ID, {"Total Shots": 10}),
            make_raw_statistics(HOME_ID, {"Total Shots": 14}),
        ], HOME_ID, AWAY_ID)

        assert stats[0]["home"] == 14
        assert stats[0]["away"] == 10

    def test_null_bleibt_null_und_wird_nie_null_zahl(self):
        """
        null heisst "nicht erhoben". Daraus 0 zu machen waere eine
        Tatsachenbehauptung, die wir nicht haben.
        """
        stats = normalize_statistics([
            make_raw_statistics(HOME_ID, {"Total Shots": 14, "expected_goals": None}),
            make_raw_statistics(AWAY_ID, {"Total Shots": 10, "expected_goals": None}),
        ], HOME_ID, AWAY_ID)

        labels = [s["label"] for s in stats]
        assert "Expected Goals" not in labels, "Zeile ohne jeden Wert entfaellt"
        assert stats[0]["home"] == 14

    def test_einseitiger_wert_bleibt_erhalten(self):
        stats = normalize_statistics([
            make_raw_statistics(HOME_ID, {"Goalkeeper Saves": 3}),
            make_raw_statistics(AWAY_ID, {"Goalkeeper Saves": None}),
        ], HOME_ID, AWAY_ID)

        assert len(stats) == 1
        assert stats[0]["home"] == 3
        assert stats[0]["away"] is None

    def test_echte_null_bleibt_null(self):
        """0 Rote Karten ist ein echter Wert und darf nicht verschwinden."""
        stats = normalize_statistics([
            make_raw_statistics(HOME_ID, {"Red Cards": 0}),
            make_raw_statistics(AWAY_ID, {"Red Cards": 1}),
        ], HOME_ID, AWAY_ID)

        assert stats[0]["home"] == 0
        assert stats[0]["away"] == 1

    def test_ergaenzende_werte_sind_nicht_core(self):
        stats = normalize_statistics([
            make_raw_statistics(HOME_ID, {"Passes %": "86%"}),
            make_raw_statistics(AWAY_ID, {"Passes %": "83%"}),
        ], HOME_ID, AWAY_ID)

        assert stats[0]["core"] is False

    def test_leere_statistik(self):
        assert normalize_statistics([], HOME_ID, AWAY_ID) == []
        assert normalize_statistics(None, HOME_ID, AWAY_ID) == []

    def test_muellbloecke_werden_uebersprungen(self):
        assert normalize_statistics([None, "kaputt", {}], HOME_ID, AWAY_ID) == []


# ===========================================================================
# F) Cache
# ===========================================================================

class TestCacheTTL:
    def test_laufendes_spiel_kurze_ttl(self):
        payload = build_match_center(make_raw_fixture(status="2H", elapsed=50), [], [], [])
        assert _ttl_for_match(payload) == TTL_LIVE_MATCH_INPLAY

    def test_halbzeit_zaehlt_als_aktiv(self):
        payload = build_match_center(make_raw_fixture(status="HT"), [], [], [])
        assert _ttl_for_match(payload) == TTL_LIVE_MATCH_INPLAY

    def test_angesetztes_spiel_mittlere_ttl(self):
        payload = build_match_center(make_raw_fixture(status="NS"), [], [], [])
        assert _ttl_for_match(payload) == TTL_LIVE_MATCH_SCHEDULED

    def test_beendetes_spiel_lange_ttl(self):
        payload = build_match_center(make_raw_fixture(status="FT"), [], [], [])
        assert _ttl_for_match(payload) == TTL_LIVE_MATCH_SETTLED

    def test_abgesagtes_spiel_lange_ttl(self):
        payload = build_match_center(make_raw_fixture(status="PST"), [], [], [])
        assert _ttl_for_match(payload) == TTL_LIVE_MATCH_SETTLED

    def test_match_ttls_sind_kuerzer_als_die_der_tagesliste(self):
        """
        Das Match Center zeigt zusaetzlich Ereignisse und Statistiken -
        ein Tor soll dort nicht spaeter ankommen als in der Liste.
        """
        from src.utils.cache import TTL_LIVE_MATCHES_INPLAY
        assert TTL_LIVE_MATCH_INPLAY <= TTL_LIVE_MATCHES_INPLAY


class TestCacheVerhalten:
    @pytest.fixture(autouse=True)
    def _isolierter_cache(self, tmp_path, monkeypatch):
        from src.utils import disk_cache
        monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path))
        self.tmp_path = tmp_path

    def test_zweiter_aufruf_kostet_keine_requests(self, monkeypatch):
        calls = []

        def counting_fixture(fixture_id, timezone=None):
            calls.append(fixture_id)
            return [make_raw_fixture()]

        monkeypatch.setattr(live_api.apisports_api, "get_fixture_by_id", counting_fixture)
        monkeypatch.setattr(live_api.apisports_api, "get_fixture_events", lambda f: [])
        monkeypatch.setattr(live_api.apisports_api, "get_fixture_lineups", lambda f: [])
        monkeypatch.setattr(live_api.apisports_api, "get_fixture_statistics", lambda f: [])

        live_api.get_match_center(555)
        live_api.get_match_center(555)
        live_api.get_match_center(555)

        assert len(calls) == 1

    def test_cache_liegt_auf_der_platte(self, monkeypatch):
        """Unter Gunicorn haette sonst jeder Worker seinen eigenen Stand."""
        _patch_provider(monkeypatch)
        live_api.get_match_center(555)

        assert len(list(self.tmp_path.glob("live_match__555*.json"))) == 1

    def test_unbekanntes_spiel_spart_die_drei_folgerequests(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            live_api.apisports_api, "get_fixture_by_id",
            lambda fixture_id, timezone=None: [],
        )
        monkeypatch.setattr(
            live_api.apisports_api, "get_fixture_events",
            lambda f: calls.append("events") or [],
        )
        monkeypatch.setattr(live_api.apisports_api, "get_fixture_lineups", lambda f: [])
        monkeypatch.setattr(live_api.apisports_api, "get_fixture_statistics", lambda f: [])

        assert live_api.get_match_center(999) is None
        assert calls == []


# ===========================================================================
# G) Fehlerfaelle
# ===========================================================================

class TestFehlerfaelle:
    @pytest.fixture(autouse=True)
    def _isolierter_cache(self, tmp_path, monkeypatch):
        from src.utils import disk_cache
        monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path))

    def test_ohne_cache_wird_fehler_durchgereicht(self, monkeypatch):
        def boom(fixture_id, timezone=None):
            raise live_api.ApisportsUnavailable("Netzwerkfehler")

        monkeypatch.setattr(live_api.apisports_api, "get_fixture_by_id", boom)

        with pytest.raises(live_api.ApisportsUnavailable):
            live_api.get_match_center(555)

    def test_alter_stand_ueberlebt_einen_ausfall(self, monkeypatch):
        _patch_provider(monkeypatch, fixture=make_raw_fixture(status="2H", elapsed=30))
        first = live_api.get_match_center(555)
        assert first["stale"] is False

        from src.utils import disk_cache
        key = "live_match:555"
        entry = disk_cache.read_entry(key)
        entry["meta"]["expires_at"] = "2000-01-01T00:00:00+00:00"
        disk_cache._write_atomic(disk_cache._path_for(key), entry)

        def boom(fixture_id, timezone=None):
            raise live_api.ApisportsUnavailable("Quelle weg")

        monkeypatch.setattr(live_api.apisports_api, "get_fixture_by_id", boom)

        second = live_api.get_match_center(555)
        assert second["stale"] is True
        assert second["fixture"]["fixture_id"] == 555

    def test_route_meldet_ausfall_ohne_provider_details(self, monkeypatch):
        import app as app_module
        app_module.app.config["TESTING"] = True
        client = app_module.app.test_client()

        def boom(fixture_id, timezone=None):
            raise live_api.ApisportsUnavailable("interner Providerfehler mit Details")

        monkeypatch.setattr(live_api.apisports_api, "get_fixture_by_id", boom)

        response = client.get("/api/live-match?fixture=555")
        assert response.status_code == 503
        assert "interner Providerfehler" not in response.get_json()["error"]

    def test_route_meldet_rate_limit(self, monkeypatch):
        import app as app_module
        app_module.app.config["TESTING"] = True
        client = app_module.app.test_client()

        def boom(fixture_id, timezone=None):
            raise live_api.ApisportsRateLimit("Limit")

        monkeypatch.setattr(live_api.apisports_api, "get_fixture_by_id", boom)

        assert client.get("/api/live-match?fixture=555").status_code == 503

    def test_antwort_verraet_keinen_schluessel(self, monkeypatch):
        import app as app_module
        app_module.app.config["TESTING"] = True
        client = app_module.app.test_client()

        _patch_provider(monkeypatch)
        body = client.get("/api/live-match?fixture=555").get_data(as_text=True).lower()

        for verboten in ["x-rapidapi", "apisports_key", "v3.football.api-sports.io"]:
            assert verboten not in body

    def test_alle_teilbereiche_leer_ist_gueltig(self, monkeypatch):
        """Angesetztes Spiel: keine Aufstellung, keine Ereignisse, keine Statistik."""
        _patch_provider(monkeypatch, fixture=make_raw_fixture(
            status="NS", elapsed=None, home_goals=None, away_goals=None))

        payload = live_api.get_match_center(555)

        assert payload["events"] == []
        assert payload["statistics"] == []
        assert payload["home_lineup"] is None


# ===========================================================================
# H) Oberflaeche
# ===========================================================================

def _live_module_source():
    script = _read("static", "script.js")
    start = script.index("/* ---------- 16c. LIVE")
    end = script.index("/* ---------- 17. START")
    return script[start:end]


class TestOberflaeche:
    def test_match_card_ist_klickbar(self):
        script = _read("static", "script.js")
        start = script.index("function liveBuildMatchCard(match)")
        block = script[start:script.index("function liveBuildGroup", start)]

        assert 'make("button", "live-match")' in block
        assert "mcOpen(match.fixture_id)" in block

    def test_match_card_behaelt_ids(self):
        script = _read("static", "script.js")
        start = script.index("function liveBuildMatchCard(match)")
        block = script[start:script.index("function liveBuildGroup", start)]

        assert "dataset.fixtureId" in block
        assert "dataset.homeId" in block
        assert "dataset.awayId" in block

    def test_match_center_liegt_im_live_bereich(self):
        """Kein fuenfter Hauptbereich - Detailansicht innerhalb von mode-live."""
        html = _read("templates", "index.html")

        live_start = html.index('id="mode-live"')
        live_end = html.index('id="mode-players"')
        live_block = html[live_start:live_end]

        assert 'id="live-match-center"' in live_block
        assert 'id="live-list-view"' in live_block

    def test_vier_reiter_in_richtiger_reihenfolge(self):
        html = _read("templates", "index.html")
        start = html.index('id="mc-tab-bar"')
        block = html[start:html.index("</div>", start)]

        import re
        tabs = re.findall(r'data-mctab="([a-z]+)"', block)
        assert tabs == ["overview", "lineups", "events", "stats"]

    def test_uebersicht_ist_standardreiter(self):
        html = _read("templates", "index.html")
        assert 'class="tab-btn active" data-mctab="overview"' in html

        script = _read("static", "script.js")
        assert 'activeTab: "overview"' in script

    def test_reiter_nutzen_bestehendes_tab_muster(self):
        html = _read("templates", "index.html")
        start = html.index('id="mc-tab-bar"')
        assert 'class="tab-bar mc-tab-bar' in html[start - 60:start + 60]

    def test_reiterwechsel_loest_keinen_request_aus(self):
        script = _read("static", "script.js")
        start = script.index("function mcSetTab(tabName)")
        block = script[start:script.index("document.querySelectorAll(\"#mc-tab-bar", start)]

        assert "mcLoad" not in block
        assert "fetchJson" not in block

    def test_zurueck_button_vorhanden(self):
        html = _read("templates", "index.html")
        assert 'id="mc-back"' in html

        script = _read("static", "script.js")
        assert "mcBackBtn.addEventListener(\"click\", mcClose)" in script

    def test_zurueck_behaelt_das_gewaehlte_datum(self):
        """
        Die Liste wird nur verdeckt, nicht neu geladen - sie steht danach
        unveraendert auf dem vorher gewaehlten Tag.
        """
        script = _read("static", "script.js")
        start = script.index("function mcClose()")
        block = script[start:script.index("if (mcBackBtn)", start)]

        assert "show(mcListView)" in block
        assert "liveSetSelectedDate" not in block
        assert "liveLoad(" not in block

    def test_fehlende_daten_werden_neutral_gemeldet(self):
        script = _read("static", "script.js")
        for text in [
            "Aufstellungen noch nicht verfügbar.",
            "Noch keine Ereignisse.",
            "Statistiken noch nicht verfügbar.",
        ]:
            assert text in script

    def test_null_statistik_wird_als_strich_gezeigt(self):
        script = _read("static", "script.js")
        start = script.index("function mcBuildStatRow(stat)")
        block = script[start:script.index("function mcRenderStats", start)]

        assert 'stat.home === null' in block
        assert '"–"' in block

    def test_spieler_id_bleibt_in_der_oberflaeche(self):
        script = _read("static", "script.js")
        assert "dataset.playerId" in script


class TestMatchCenterPolling:
    def test_eigener_state_getrennt_von_livestate(self):
        script = _read("static", "script.js")
        assert "const mcState = {" in script
        assert "refreshTimer: null" in script

    def test_genau_zwei_setinterval_stellen(self):
        """
        Eine fuer die Tagesliste, eine fuer das Match Center - mehr darf
        es nicht geben, sonst laufen Timer unkontrolliert parallel.
        """
        script = _read("static", "script.js")
        assert script.count("setInterval(") == 2

    def test_schedule_raeumt_immer_zuerst_auf(self):
        script = _read("static", "script.js")
        start = script.index("function mcScheduleAutoRefresh(data)")
        block = script[start:start + 300]

        assert block.index("mcStopAutoRefresh();") < block.index("if (!mcShouldAutoRefresh")

    def test_bedingungen_fuer_polling(self):
        script = _read("static", "script.js")
        start = script.index("function mcShouldAutoRefresh(data)")
        block = script[start:script.index("}", script.index("{", start)) + 1]

        assert 'state.activeArea === "live"' in block
        assert "mcState.open" in block
        assert "is_live === true" in block
        assert 'document.visibilityState === "visible"' in block

    def test_beendetes_spiel_wird_nicht_gepollt(self):
        """is_live ist Teil der Bedingung - ein FT-Spiel erfuellt sie nie."""
        script = _read("static", "script.js")
        start = script.index("function mcShouldAutoRefresh(data)")
        block = script[start:script.index("}", script.index("{", start)) + 1]
        assert "data.fixture.is_live === true" in block

    def test_schliessen_stoppt_den_timer(self):
        script = _read("static", "script.js")
        start = script.index("function mcClose()")
        block = script[start:script.index("if (mcBackBtn)", start)]
        assert "mcStopAutoRefresh();" in block

    def test_bereichswechsel_stoppt_beide_timer(self):
        script = _read("static", "script.js")
        start = script.index('if (area === "live") {')
        block = script[start:start + 260]

        assert "liveStopAutoRefresh();" in block
        assert "mcStopAutoRefresh();" in block

    def test_sichtbarkeitswechsel_stoppt_beide_timer(self):
        script = _read("static", "script.js")
        start = script.index('addEventListener("visibilitychange"')
        block = script[start:start + 700]

        assert "liveStopAutoRefresh();" in block
        assert "mcStopAutoRefresh();" in block

    def test_liste_pausiert_solange_das_match_center_offen_ist(self):
        """
        Sonst liefen beide Timer parallel und die verdeckte Liste wuerde
        unnoetig Requests erzeugen.
        """
        script = _read("static", "script.js")
        start = script.index("function liveShouldAutoRefresh(data)")
        block = script[start:script.index("}", script.index("{", start)) + 1]
        assert "!mcState.open" in block

    def test_oeffnen_stoppt_das_listen_polling(self):
        script = _read("static", "script.js")
        start = script.index("function mcOpen(fixtureId)")
        block = script[start:script.index("function mcClose()", start)]
        assert "liveStopAutoRefresh();" in block

    def test_zurueck_nimmt_listen_polling_wieder_auf(self):
        script = _read("static", "script.js")
        start = script.index("function mcClose()")
        block = script[start:script.index("if (mcBackBtn)", start)]
        assert "liveScheduleAutoRefresh(liveState.lastData)" in block

    def test_hintergrund_refresh_ohne_ladeanzeige(self):
        script = _read("static", "script.js")
        start = script.index("async function mcLoad(options)")
        block = script[start:script.index("try {", start)]
        assert "if (!background) mcSetStatus" in block

    def test_hintergrundfehler_laesst_ansicht_stehen(self):
        script = _read("static", "script.js")
        start = script.index("async function mcLoad(options)")
        block = script[start:script.index("function mcOpen", start)]
        catch_part = block[block.index("} catch (error) {"):]
        assert "if (!background) {" in catch_part

    def test_request_token_gegen_race_conditions(self):
        """Antwort zu Spiel A darf Spiel B nicht ueberschreiben."""
        script = _read("static", "script.js")
        start = script.index("async function mcLoad(options)")
        block = script[start:script.index("function mcOpen", start)]

        assert "++mcState.requestToken" in block
        assert "token !== mcState.requestToken" in block

    def test_intervall_passt_zur_server_ttl(self):
        script = _read("static", "script.js")
        start = script.index("const MC_REFRESH_INTERVAL_MS")
        line = script[start:script.index(";", start)]
        value = int("".join(ch for ch in line.split("=")[1] if ch.isdigit()))
        assert 20000 <= value <= 35000


class TestNavigationUnveraendert:
    def test_weiterhin_genau_vier_hauptbereiche(self):
        html = _read("templates", "index.html")
        assert html.count('class="area-btn') == 4
        assert html.count('class="bottom-nav-btn') == 4

    def test_reihenfolge_unveraendert(self):
        html = _read("templates", "index.html")

        positions = []
        start = 0
        while True:
            found = html.find('class="bottom-nav-btn', start)
            if found == -1:
                break
            positions.append(found)
            start = found + 1

        areas = []
        for pos in positions:
            snippet = html[pos:pos + 200]
            for area in ["simulation", "compare", "live", "players"]:
                if f'data-area="{area}"' in snippet:
                    areas.append(area)
                    break

        assert areas == ["simulation", "compare", "live", "players"]

    def test_areas_liste_unveraendert(self):
        script = _read("static", "script.js")
        start = script.index("const AREAS = [")
        line = script[start:script.index("]", start)]
        assert line.count('"') == 8, "genau vier Bereiche"


class TestKeinLiveC:
    def test_kein_spielfeld_diagramm(self):
        """
        Das grafische Spielfeld ist ausdruecklich LIVE C. grid darf im
        Payload liegen, aber nicht visuell ausgewertet werden.
        """
        css = _read("static", "style.css")
        assert ".mc-pitch" not in css

        script = _read("static", "script.js")
        assert "mcBuildPitch" not in script

    def test_grid_bleibt_aber_erhalten(self):
        source = _read("src", "api", "live_api.py")
        assert '"grid": player.get("grid")' in source
