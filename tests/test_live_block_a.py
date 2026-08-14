"""
Tests fuer Block LIVE A (Live Scores Core).

Abgedeckt:
  A) Statusabbildung: laufend, Pause, angesetzt, beendet, nicht stattgefunden
  B) Normalisierung einer API-Football-Antwort, inklusive Luecken
  C) Wettbewerbs-Whitelist (nur FootSim-Wettbewerbe, richtige Reihenfolge)
  D) Zeitzone Europe/Berlin inklusive Sommer-/Winterzeit
  E) Adaptive Cache-TTL und Cross-Worker-Verhalten auf der Platte
  F) Verhalten bei API-Fehlern (inklusive Notfall-Fallback auf alte Daten)
  G) Datumsvalidierung der Route
  H) Navigation mit vier Hauptbereichen, Live zwischen Vergleiche und Spieler

Kein echter API-Request: alle Tests arbeiten auf synthetischen Antworten
im Format von /fixtures?date=.
"""

import os

import pytest

from src.api import live_api
from src.api.live_api import (
    PHASE_SCHEDULED,
    PHASE_LIVE,
    PHASE_PAUSED,
    PHASE_FINISHED,
    PHASE_CANCELLED,
    PHASE_UNKNOWN,
    build_day,
    classify_status,
    normalize_fixture,
    _kickoff_berlin,
    _ttl_for_matches,
)
from src.utils.cache import (
    TTL_LIVE_MATCHES_INPLAY,
    TTL_LIVE_MATCHES_UPCOMING,
    TTL_LIVE_MATCHES_SETTLED,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(PROJECT_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


# Reihenfolge wie _live_competitions() sie baut (LEAGUE_CONFIG, dann CUP_CONFIG).
COMPETITIONS = {
    "bl1": 78,
    "pl": 39,
    "pd": 140,
    "sa": 135,
    "fl1": 61,
    "cl": 2,
    "el": 3,
    "gsc": 529,
    "usc": 531,
    "facs": 528,
}


def make_fixture(fixture_id=1, league_id=39, status="NS", elapsed=None,
                 home_goals=None, away_goals=None,
                 date="2026-08-11T18:00:00+02:00", extra=None):
    """Ein Fixture-Eintrag im Format von API-Football."""
    return {
        "fixture": {
            "id": fixture_id,
            "date": date,
            "status": {"long": "x", "short": status, "elapsed": elapsed, "extra": extra},
        },
        "teams": {
            "home": {"id": 49, "name": "Chelsea", "logo": "https://x/49.png"},
            "away": {"id": 42, "name": "Arsenal", "logo": "https://x/42.png"},
        },
        "goals": {"home": home_goals, "away": away_goals},
        "league": {
            "id": league_id,
            "name": "Premier League",
            "logo": "https://x/l39.png",
            "country": "England",
        },
    }


# ===========================================================================
# A) Statusabbildung
# ===========================================================================

class TestStatusabbildung:
    @pytest.mark.parametrize("code", ["1H", "2H", "ET", "P", "LIVE"])
    def test_laufende_status_sind_live(self, code):
        phase, label = classify_status(code)
        assert phase == PHASE_LIVE
        assert label

    @pytest.mark.parametrize("code", ["HT", "BT", "SUSP", "INT"])
    def test_unterbrochene_status_sind_paused(self, code):
        phase, _ = classify_status(code)
        assert phase == PHASE_PAUSED

    @pytest.mark.parametrize("code", ["NS", "TBD"])
    def test_angesetzte_status(self, code):
        phase, _ = classify_status(code)
        assert phase == PHASE_SCHEDULED

    @pytest.mark.parametrize("code", ["FT", "AET", "PEN"])
    def test_beendete_status(self, code):
        phase, _ = classify_status(code)
        assert phase == PHASE_FINISHED

    @pytest.mark.parametrize("code", ["PST", "CANC", "ABD", "AWD", "WO"])
    def test_nicht_stattgefundene_status(self, code):
        phase, _ = classify_status(code)
        assert phase == PHASE_CANCELLED

    def test_alle_geforderten_codes_sind_bekannt(self):
        """Kein Statuscode aus der Anforderung darf als unbekannt durchfallen."""
        for code in ["NS", "1H", "HT", "2H", "ET", "BT", "P", "SUSP", "INT",
                     "FT", "AET", "PEN", "PST", "CANC", "ABD", "AWD", "WO"]:
            phase, _ = classify_status(code)
            assert phase != PHASE_UNKNOWN, f"{code} wird nicht erkannt"

    def test_unbekannter_status_faellt_nicht_um(self):
        phase, label = classify_status("XYZ")
        assert phase == PHASE_UNKNOWN
        assert label == "XYZ"

    def test_fehlender_status_faellt_nicht_um(self):
        phase, label = classify_status(None)
        assert phase == PHASE_UNKNOWN
        assert label


# ===========================================================================
# B) Normalisierung
# ===========================================================================

class TestNormalisierung:
    def test_laufendes_spiel_hat_minute_und_stand(self):
        match = normalize_fixture(
            make_fixture(status="1H", elapsed=67, home_goals=2, away_goals=1)
        )
        assert match["phase"] == PHASE_LIVE
        assert match["is_live"] is True
        assert match["elapsed"] == 67
        assert match["home_goals"] == 2
        assert match["away_goals"] == 1

    def test_nachspielzeit_bleibt_erhalten(self):
        match = normalize_fixture(make_fixture(status="2H", elapsed=90, extra=3))
        assert match["elapsed"] == 90
        assert match["elapsed_extra"] == 3

    def test_angesetztes_spiel_hat_keinen_stand(self):
        match = normalize_fixture(make_fixture(status="NS"))
        assert match["phase"] == PHASE_SCHEDULED
        assert match["is_live"] is False
        assert match["home_goals"] is None
        assert match["away_goals"] is None
        assert match["kickoff_time"] == "18:00"

    def test_beendetes_spiel_zeigt_keine_spielminute(self):
        """
        Die Quelle liefert bei FT weiterhin elapsed=90. Das anzuzeigen
        wuerde ein beendetes Spiel wie ein laufendes aussehen lassen.
        """
        match = normalize_fixture(
            make_fixture(status="FT", elapsed=90, home_goals=2, away_goals=1)
        )
        assert match["phase"] == PHASE_FINISHED
        assert match["is_live"] is False
        assert match["elapsed"] is None
        assert match["home_goals"] == 2

    def test_pause_zeigt_keine_spielminute(self):
        match = normalize_fixture(make_fixture(status="HT", elapsed=45))
        assert match["phase"] == PHASE_PAUSED
        assert match["is_live"] is True
        assert match["elapsed"] is None

    def test_fixture_und_team_ids_bleiben_erhalten(self):
        """Diese IDs braucht LIVE B - sie duerfen nicht verloren gehen."""
        match = normalize_fixture(make_fixture(fixture_id=123456))
        assert match["fixture_id"] == 123456
        assert match["home_id"] == 49
        assert match["away_id"] == 42

    def test_eintrag_ohne_fixture_id_wird_verworfen(self):
        raw = make_fixture()
        raw["fixture"].pop("id")
        assert normalize_fixture(raw) is None

    def test_leerer_eintrag_wirft_nicht(self):
        assert normalize_fixture({}) is None
        assert normalize_fixture(None) is None
        assert normalize_fixture("kaputt") is None

    def test_fehlende_bloecke_werfen_nicht(self):
        """Eine unvollstaendige Antwort darf den Tag nicht unbrauchbar machen."""
        match = normalize_fixture({"fixture": {"id": 7}})
        assert match is not None
        assert match["fixture_id"] == 7
        assert match["home_name"] is None
        assert match["home_goals"] is None
        assert match["kickoff"] is None
        assert match["phase"] == PHASE_UNKNOWN


# ===========================================================================
# C) Whitelist und Gruppierung
# ===========================================================================

class TestWhitelist:
    def test_fremde_wettbewerbe_werden_gefiltert(self):
        raw = [
            make_fixture(fixture_id=1, league_id=39),     # Premier League
            make_fixture(fixture_id=2, league_id=117),    # Belarus, nicht FootSim
            make_fixture(fixture_id=3, league_id=1075),   # Usbekistan, nicht FootSim
        ]
        day = build_day(raw, COMPETITIONS, "2026-08-11")
        assert day["match_count"] == 1
        assert day["groups"][0]["matches"][0]["fixture_id"] == 1

    def test_gruppen_folgen_der_footsim_reihenfolge(self):
        """Nicht die Reihenfolge der API, sondern die der Konfiguration."""
        raw = [
            make_fixture(fixture_id=1, league_id=2),    # cl
            make_fixture(fixture_id=2, league_id=78),   # bl1
            make_fixture(fixture_id=3, league_id=39),   # pl
        ]
        day = build_day(raw, COMPETITIONS, "2026-08-11")
        assert [g["competition_code"] for g in day["groups"]] == ["bl1", "pl", "cl"]

    def test_competition_code_wird_gesetzt(self):
        day = build_day([make_fixture(league_id=78)], COMPETITIONS, "2026-08-11")
        assert day["groups"][0]["competition_code"] == "bl1"
        assert day["groups"][0]["matches"][0]["competition_code"] == "bl1"

    def test_super_cups_werden_erkannt(self):
        raw = [
            make_fixture(fixture_id=10, league_id=529),
            make_fixture(fixture_id=11, league_id=531),
            make_fixture(fixture_id=12, league_id=528),
        ]
        day = build_day(raw, COMPETITIONS, "2026-08-11")
        assert day["match_count"] == 3
        codes = [g["competition_code"] for g in day["groups"]]
        assert "gsc" in codes
        assert "usc" in codes
        assert "facs" in codes

    def test_spiele_innerhalb_gruppe_nach_anstoss_sortiert(self):
        raw = [
            make_fixture(fixture_id=1, date="2026-08-11T20:30:00+02:00"),
            make_fixture(fixture_id=2, date="2026-08-11T15:30:00+02:00"),
            make_fixture(fixture_id=3, date="2026-08-11T18:00:00+02:00"),
        ]
        day = build_day(raw, COMPETITIONS, "2026-08-11")
        ids = [m["fixture_id"] for m in day["groups"][0]["matches"]]
        assert ids == [2, 3, 1]

    def test_leerer_tag_ist_kein_fehler(self):
        day = build_day([], COMPETITIONS, "2026-08-11")
        assert day["groups"] == []
        assert day["match_count"] == 0
        assert day["live_count"] == 0

    def test_live_count_zaehlt_laufende_und_pausierte(self):
        raw = [
            make_fixture(fixture_id=1, status="1H"),
            make_fixture(fixture_id=2, status="HT"),
            make_fixture(fixture_id=3, status="FT"),
            make_fixture(fixture_id=4, status="NS"),
        ]
        day = build_day(raw, COMPETITIONS, "2026-08-11")
        assert day["match_count"] == 4
        assert day["live_count"] == 2

    def test_kaputte_eintraege_werden_uebersprungen(self):
        raw = [make_fixture(fixture_id=1), None, "kaputt", {}, {"league": {"id": 39}}]
        day = build_day(raw, COMPETITIONS, "2026-08-11")
        assert day["match_count"] == 1


# ===========================================================================
# D) Zeitzone
# ===========================================================================

class TestZeitzone:
    def test_sommerzeit_utc_wird_zu_berliner_zeit(self):
        """Mai: CEST, also UTC+2."""
        assert _kickoff_berlin("2026-05-24T15:00:00+00:00").strftime("%H:%M") == "17:00"

    def test_winterzeit_utc_wird_zu_berliner_zeit(self):
        """Januar: CET, also UTC+1. Kein fest verdrahteter Offset."""
        assert _kickoff_berlin("2026-01-15T15:00:00+00:00").strftime("%H:%M") == "16:00"

    def test_bereits_berliner_zeit_bleibt_unveraendert(self):
        assert _kickoff_berlin("2026-08-11T20:30:00+02:00").strftime("%H:%M") == "20:30"

    def test_z_suffix_wird_verstanden(self):
        """Python 3.9 kann 'Z' nicht selbst; das muss der Loader abfangen."""
        assert _kickoff_berlin("2026-05-24T15:00:00Z").strftime("%H:%M") == "17:00"

    def test_zeit_ohne_zonenangabe_gilt_als_utc(self):
        assert _kickoff_berlin("2026-05-24T15:00:00").strftime("%H:%M") == "17:00"

    def test_unbrauchbares_datum_liefert_none(self):
        assert _kickoff_berlin("kein datum") is None
        assert _kickoff_berlin("") is None
        assert _kickoff_berlin(None) is None

    def test_antwort_nennt_die_zeitzone(self):
        day = build_day([], COMPETITIONS, "2026-08-11")
        assert day["timezone"] == "Europe/Berlin"


# ===========================================================================
# E) Cache
# ===========================================================================

class TestCacheTTL:
    def test_laufendes_spiel_erzwingt_kurze_ttl(self):
        matches = [normalize_fixture(make_fixture(status="1H", elapsed=20))]
        assert _ttl_for_matches(matches) == TTL_LIVE_MATCHES_INPLAY

    def test_pause_zaehlt_ebenfalls_als_aktiv(self):
        matches = [normalize_fixture(make_fixture(status="HT"))]
        assert _ttl_for_matches(matches) == TTL_LIVE_MATCHES_INPLAY

    def test_nur_kommende_spiele_mittlere_ttl(self):
        matches = [normalize_fixture(make_fixture(status="NS"))]
        assert _ttl_for_matches(matches) == TTL_LIVE_MATCHES_UPCOMING

    def test_abgeschlossener_tag_lange_ttl(self):
        matches = [normalize_fixture(make_fixture(status="FT", elapsed=90))]
        assert _ttl_for_matches(matches) == TTL_LIVE_MATCHES_SETTLED

    def test_leerer_tag_wird_nicht_lange_festgehalten(self):
        """Eine Ansetzung koennte nachgetragen werden."""
        assert _ttl_for_matches([]) == TTL_LIVE_MATCHES_UPCOMING

    def test_ein_laufendes_spiel_dominiert_den_tag(self):
        matches = [
            normalize_fixture(make_fixture(fixture_id=1, status="FT", elapsed=90)),
            normalize_fixture(make_fixture(fixture_id=2, status="2H", elapsed=70)),
        ]
        assert _ttl_for_matches(matches) == TTL_LIVE_MATCHES_INPLAY


class TestCacheVerhalten:
    @pytest.fixture(autouse=True)
    def _isolierter_cache(self, tmp_path, monkeypatch):
        """Testet gegen ein eigenes Verzeichnis, nie gegen data/cache."""
        from src.utils import disk_cache
        monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path))

    def test_zweiter_aufruf_kostet_keinen_request(self, monkeypatch):
        """
        Der Kern des Cache-Versprechens: 100 Nutzer duerfen nicht 100
        Requests erzeugen.
        """
        calls = []

        def fake_fetch(date_str, timezone=None):
            calls.append(date_str)
            return [make_fixture(status="NS")]

        monkeypatch.setattr(live_api.apisports_api, "get_fixtures_by_date", fake_fetch)

        live_api.get_matches_for_date("2026-08-11", COMPETITIONS)
        live_api.get_matches_for_date("2026-08-11", COMPETITIONS)
        live_api.get_matches_for_date("2026-08-11", COMPETITIONS)

        assert len(calls) == 1

    def test_cache_liegt_auf_der_platte(self, tmp_path, monkeypatch):
        """
        Nicht im Prozessspeicher: unter Gunicorn haette sonst jeder der
        drei Worker seinen eigenen Stand.
        """
        monkeypatch.setattr(
            live_api.apisports_api, "get_fixtures_by_date",
            lambda date_str, timezone=None: [make_fixture()],
        )

        live_api.get_matches_for_date("2026-08-11", COMPETITIONS)

        written = list(tmp_path.glob("live_matches*.json"))
        assert len(written) == 1

    def test_cache_key_trennt_datum(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            live_api.apisports_api, "get_fixtures_by_date",
            lambda date_str, timezone=None: calls.append(date_str) or [],
        )

        live_api.get_matches_for_date("2026-08-11", COMPETITIONS)
        live_api.get_matches_for_date("2026-08-12", COMPETITIONS)

        assert calls == ["2026-08-11", "2026-08-12"]

    def test_cache_key_enthaelt_nichts_nutzerspezifisches(self):
        key = live_api._cache_key("2026-08-11", COMPETITIONS)
        assert key.startswith("live_matches:2026-08-11:")

    def test_geaenderte_wettbewerbe_nutzen_anderen_key(self):
        """Sonst wuerde ein nach altem Zuschnitt gefilterter Eintrag weiterleben."""
        a = live_api._cache_key("2026-08-11", COMPETITIONS)
        b = live_api._cache_key("2026-08-11", {"pl": 39})
        assert a != b


# ===========================================================================
# F) Fehlerfaelle
# ===========================================================================

class TestFehlerfaelle:
    @pytest.fixture(autouse=True)
    def _isolierter_cache(self, tmp_path, monkeypatch):
        from src.utils import disk_cache
        monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path))

    def test_ohne_cache_wird_fehler_durchgereicht(self, monkeypatch):
        def boom(date_str, timezone=None):
            raise live_api.ApisportsUnavailable("Netzwerkfehler")

        monkeypatch.setattr(live_api.apisports_api, "get_fixtures_by_date", boom)

        with pytest.raises(live_api.ApisportsUnavailable):
            live_api.get_matches_for_date("2026-08-11", COMPETITIONS)

    def test_alter_stand_ueberlebt_einen_ausfall(self, monkeypatch):
        """
        Lieber ein als veraltet markierter Stand als eine leere Seite.
        """
        monkeypatch.setattr(
            live_api.apisports_api, "get_fixtures_by_date",
            lambda date_str, timezone=None: [make_fixture(status="1H", elapsed=30,
                                                          home_goals=1, away_goals=0)],
        )
        first = live_api.get_matches_for_date("2026-08-11", COMPETITIONS)
        assert first["stale"] is False
        assert first["match_count"] == 1

        # Eintrag kuenstlich altern lassen, damit neu geladen werden muss.
        from src.utils import disk_cache
        key = live_api._cache_key("2026-08-11", COMPETITIONS)
        entry = disk_cache.read_entry(key)
        entry["meta"]["expires_at"] = "2000-01-01T00:00:00+00:00"
        disk_cache._write_atomic(disk_cache._path_for(key), entry)

        def boom(date_str, timezone=None):
            raise live_api.ApisportsUnavailable("Quelle weg")

        monkeypatch.setattr(live_api.apisports_api, "get_fixtures_by_date", boom)

        second = live_api.get_matches_for_date("2026-08-11", COMPETITIONS)
        assert second["stale"] is True
        assert second["match_count"] == 1

    def test_rate_limit_ist_ein_eigener_fehlertyp(self, monkeypatch):
        def boom(date_str, timezone=None):
            raise live_api.ApisportsRateLimit("Limit")

        monkeypatch.setattr(live_api.apisports_api, "get_fixtures_by_date", boom)

        with pytest.raises(live_api.ApisportsRateLimit):
            live_api.get_matches_for_date("2026-08-11", COMPETITIONS)

    def test_muellantwort_ergibt_leeren_tag_statt_absturz(self, monkeypatch):
        monkeypatch.setattr(
            live_api.apisports_api, "get_fixtures_by_date",
            lambda date_str, timezone=None: ["kaputt", None, {}],
        )
        day = live_api.get_matches_for_date("2026-08-11", COMPETITIONS)
        assert day["match_count"] == 0


# ===========================================================================
# G) Route
# ===========================================================================

class TestRoute:
    @pytest.fixture
    def client(self):
        import app as app_module
        app_module.app.config["TESTING"] = True
        return app_module.app.test_client()

    @pytest.fixture(autouse=True)
    def _isolierter_cache(self, tmp_path, monkeypatch):
        from src.utils import disk_cache
        monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path))

    def test_ungueltiges_datum_wird_abgelehnt(self, client):
        response = client.get("/api/live-matches?date=kein-datum")
        assert response.status_code == 400
        assert "error" in response.get_json()

    def test_datum_ausserhalb_des_fensters_wird_abgelehnt(self, client):
        response = client.get("/api/live-matches?date=1999-01-01")
        assert response.status_code == 400

    def test_gueltiges_datum_wird_akzeptiert(self, client, monkeypatch):
        import app as app_module
        monkeypatch.setattr(
            live_api.apisports_api, "get_fixtures_by_date",
            lambda date_str, timezone=None: [make_fixture(status="NS")],
        )
        heute = app_module._today_in_display_timezone().isoformat()

        response = client.get(f"/api/live-matches?date={heute}")
        assert response.status_code == 200

        data = response.get_json()
        assert data["date"] == heute
        assert data["is_today"] is True
        assert data["timezone"] == "Europe/Berlin"

    def test_ohne_datum_gilt_heute(self, client, monkeypatch):
        import app as app_module
        monkeypatch.setattr(
            live_api.apisports_api, "get_fixtures_by_date",
            lambda date_str, timezone=None: [],
        )
        response = client.get("/api/live-matches")
        assert response.status_code == 200
        assert response.get_json()["date"] == app_module._today_in_display_timezone().isoformat()

    def test_api_ausfall_gibt_sauberen_fehler(self, client, monkeypatch):
        def boom(date_str, timezone=None):
            raise live_api.ApisportsUnavailable("interner Providerfehler mit Details")

        monkeypatch.setattr(live_api.apisports_api, "get_fixtures_by_date", boom)

        response = client.get("/api/live-matches")
        assert response.status_code == 503

        data = response.get_json()
        assert data["groups"] == []
        # Keine Provider-Interna nach aussen.
        assert "interner Providerfehler" not in data["error"]

    def test_rate_limit_gibt_sauberen_fehler(self, client, monkeypatch):
        def boom(date_str, timezone=None):
            raise live_api.ApisportsRateLimit("Limit erreicht")

        monkeypatch.setattr(live_api.apisports_api, "get_fixtures_by_date", boom)

        response = client.get("/api/live-matches")
        assert response.status_code == 503
        assert "error" in response.get_json()

    def test_antwort_verraet_keinen_schluessel(self, client, monkeypatch):
        monkeypatch.setattr(
            live_api.apisports_api, "get_fixtures_by_date",
            lambda date_str, timezone=None: [make_fixture()],
        )
        body = client.get("/api/live-matches").get_data(as_text=True).lower()
        for verboten in ["apisports", "api-sports", "x-rapidapi", "rapidapi"]:
            assert verboten not in body


class TestWettbewerbsKonfiguration:
    def test_whitelist_kommt_aus_bestehender_konfiguration(self):
        """
        Keine zweite Liga-Liste: die Codes kommen aus LEAGUE_CONFIG und
        CUP_CONFIG, die IDs aus apisports_api.LEAGUE_IDS.
        """
        import app as app_module
        from src.api import apisports_api

        competitions = app_module._live_competitions()

        for code, league_id in competitions.items():
            assert code in app_module.LEAGUE_CONFIG or code in app_module.CUP_CONFIG
            assert league_id == apisports_api.LEAGUE_IDS[code]

    def test_alle_fuenf_ligen_und_cl_sind_dabei(self):
        import app as app_module
        competitions = app_module._live_competitions()
        for code in ["bl1", "pl", "pd", "sa", "fl1", "cl"]:
            assert code in competitions

    def test_reihenfolge_beginnt_mit_den_ligen(self):
        import app as app_module
        codes = list(app_module._live_competitions().keys())
        assert codes[:5] == ["bl1", "pl", "pd", "sa", "fl1"]


# ===========================================================================
# H) Navigation und Oberflaeche
# ===========================================================================

class TestNavigation:
    def test_vier_hauptbereiche_desktop(self):
        html = _read("templates", "index.html")
        assert html.count('class="area-btn') == 4

    def test_vier_hauptbereiche_mobil(self):
        html = _read("templates", "index.html")
        assert html.count('class="bottom-nav-btn') == 4

    def test_live_liegt_zwischen_vergleiche_und_spieler(self):
        """Reihenfolge in beiden Navigationen: Simulation, Vergleiche, Live, Spieler."""
        html = _read("templates", "index.html")

        for marker in ['class="area-btn', 'class="bottom-nav-btn']:
            positions = []
            start = 0
            while True:
                found = html.find(marker, start)
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

            assert areas == ["simulation", "compare", "live", "players"], marker

    def test_spieler_bleibt_rechts_aussen(self):
        html = _read("templates", "index.html")
        assert html.rindex('data-area="players"') > html.rindex('data-area="live"')

    def test_live_bereich_existiert(self):
        html = _read("templates", "index.html")
        assert 'id="mode-live"' in html
        assert 'data-area="live"' in html

    def test_keine_fuenfte_hauptnavigation(self):
        html = _read("templates", "index.html")
        assert html.count('class="bottom-nav-btn') == 4

    def test_datumsnavigation_vorhanden(self):
        html = _read("templates", "index.html")
        assert 'id="live-date-strip"' in html
        assert 'id="live-prev-day"' in html
        assert 'id="live-next-day"' in html

    def test_kalender_ist_natives_date_input(self):
        """Kein Datepicker-Framework - ein echtes <input type="date">."""
        html = _read("templates", "index.html")
        assert 'id="live-calendar-input"' in html
        assert 'type="date"' in html
        assert 'id="live-calendar-btn"' in html

    def test_areas_kennt_live(self):
        script = _read("static", "script.js")
        start = script.index("const AREAS = [")
        line = script[start:script.index("]", start)]
        for area in ['"simulation"', '"compare"', '"live"', '"players"']:
            assert area in line

    def test_frontend_nutzt_die_live_route(self):
        script = _read("static", "script.js")
        assert "/api/live-matches?date=" in script

    def test_frontend_rechnet_datum_in_berliner_zeit(self):
        """
        Sonst haetten Nutzer ausserhalb Deutschlands einen anderen
        Cache-Key fuer denselben Spieltag.
        """
        script = _read("static", "script.js")
        assert 'timeZone: "Europe/Berlin"' in script

    def test_match_karte_traegt_ids_fuer_live_b(self):
        script = _read("static", "script.js")
        assert "dataset.fixtureId" in script
        assert "dataset.homeId" in script
        assert "dataset.awayId" in script

    def test_live_stile_vorhanden(self):
        css = _read("static", "style.css")
        for selector in [".live-match", ".live-badge", ".live-date-chip", ".live-group"]:
            assert selector in css

    def test_leerer_zustand_startet_versteckt(self):
        """
        Waehrend des ersten Ladens waere "Keine Spiele" eine Falschaussage.
        """
        html = _read("templates", "index.html")
        assert 'id="live-empty" class="empty-state hidden"' in html
        assert 'id="live-groups" class="live-groups hidden"' in html

    def test_ladefehler_zeigt_nicht_den_leeren_zustand(self):
        """
        Ein Ladefehler heisst nicht "keine Spiele" - wir wissen es nur nicht.

        Seit LIVE A+ gilt das nur fuer regulaere (nicht-Hintergrund-)
        Ladevorgaenge; ein fehlgeschlagener Auto-Refresh-Tick veraendert
        die sichtbare Seite ueberhaupt nicht (siehe test_live_block_a_plus.py).
        """
        script = _read("static", "script.js")
        start = script.index("async function liveLoad(options)")
        block = script[start:script.index("/* ---------- 16c1.", start)]
        catch_part = block[block.index("} catch (error) {"):]
        assert "hide(liveEmpty)" in catch_part
        assert "show(liveEmpty)" not in catch_part

    def test_service_worker_haelt_api_vom_cache_fern(self):
        """Sonst wuerden Live-Daten im Browsercache einfrieren."""
        sw = _read("static", "sw.js")
        assert '"/api/"' in sw


class TestVeralteteTarifangaben:
    """
    Der Free-Plan-Hinweis (100 Requests/Tag) war seit dem Upgrade auf
    Pro falsch und hat die Architektur unnoetig eingeschraenkt.

    Geprueft wird, dass keine Stelle das alte Limit noch als geltende
    Tatsache behauptet. Ein Hinweis, dass die Angabe frueher falsch war,
    ist ausdruecklich erlaubt - er erklaert, warum sich Cache-Zuschnitte
    an manchen Stellen konservativ lesen.
    """

    def test_apisports_modul_dokumentiert_den_pro_plan(self):
        source = _read("src", "api", "apisports_api.py")
        assert "7.500" in source or "7500" in source
        assert "Pro" in source

    def test_rate_limit_meldung_behauptet_kein_tageslimit_mehr(self):
        source = _read("src", "api", "apisports_api.py")
        assert 'ApisportsRateLimit("API-Sports Tageslimit erreicht (100 Requests/Tag)")' not in source

    def test_request_usage_nimmt_kein_limit_an(self):
        """Das Limit wird aus der Antwort gelesen, nicht als 100 angenommen."""
        source = _read("src", "api", "apisports_api.py")
        assert 'sub.get("limit_day", 100)' not in source

    def test_squad_impact_behauptet_kein_100er_limit_mehr(self):
        source = _read("src", "features", "squad_impact.py")
        assert "Free-Plan erlaubt 100 Requests" not in source

    def test_app_behauptet_kein_100er_limit_mehr(self):
        source = _read("app.py")
        assert "API-Sports: 100 Requests/Tag" not in source
