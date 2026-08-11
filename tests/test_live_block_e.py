"""
Tests fuer Block LIVE E (finaler Feinschliff des Match Centers).

Abgedeckt:
  A) Halbzeit-/End-/Verlaengerungs-/Elfmeterschiessen-Stand (score-Block)
  B) Scoreboard-Darstellung bei AET/PEN (Frontend-Vertrag)
  C) Gelb-Rot als eigener Ereignistyp (zweite Gelbe Karte)
  D) Elfmetertor-Kennzeichnung (is_penalty)
  E) Partial-Failure-Haertung des Match Centers (weiche vs. harte Fehler)
  F) Cache-Strategie bei einem degradierten Payload
  G) Frontend-Vertraege: Gelb-Rot-/Elfmeter-Darstellung, neutrale
     Zustaende fuer nicht verfuegbare Tabs
  H) Mobile: Kader-Touch-Ziel bei 420px

Kein echter API-Request: alle Tests arbeiten auf synthetischen Antworten
im Format von /fixtures, /fixtures/events, /fixtures/lineups,
/fixtures/statistics und /fixtures/players - gleiches Muster wie
tests/test_live_block_b.py und tests/test_live_block_c.py.
"""

import os

import pytest

from src.api import live_api
from src.api.live_api import (
    EVENT_GOAL,
    EVENT_OWN_GOAL,
    EVENT_PENALTY_MISS,
    EVENT_YELLOW,
    EVENT_YELLOW_RED,
    EVENT_RED,
    PHASE_FINISHED,
    build_match_center,
    classify_event,
    normalize_event,
    _ttl_for_match,
    _is_degraded,
)
from src.utils.cache import (
    TTL_LIVE_MATCH_INPLAY,
    TTL_LIVE_MATCH_SCHEDULED,
    TTL_LIVE_MATCH_SETTLED,
    TTL_LIVE_MATCH_DEGRADED,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(PROJECT_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _script():
    return _read("static", "script.js")


def _css():
    return _read("static", "style.css")


HOME_ID = 49
AWAY_ID = 42


def make_raw_fixture(status="FT", elapsed=90, extra=None,
                     home_goals=2, away_goals=1, fixture_id=555,
                     score=None):
    """Wie tests/test_live_block_b.py::make_raw_fixture, plus score-Block."""
    return {
        "fixture": {
            "id": fixture_id,
            "date": "2026-08-11T20:30:00+02:00",
            "referee": "C. Kavanagh",
            "venue": {"id": 1, "name": "Stamford Bridge", "city": "London"},
            "status": {"long": "Match Finished", "short": status,
                       "elapsed": elapsed, "extra": extra},
        },
        "league": {
            "id": 2, "name": "UEFA Champions League", "country": "World",
            "logo": "https://x/l2.png", "round": "Final", "season": 2025,
        },
        "teams": {
            "home": {"id": HOME_ID, "name": "Chelsea", "logo": "https://x/49.png"},
            "away": {"id": AWAY_ID, "name": "Arsenal", "logo": "https://x/42.png"},
        },
        "goals": {"home": home_goals, "away": away_goals},
        "score": score,
    }


def make_raw_event(elapsed=17, extra=None, kind="Goal", detail="Normal Goal",
                   team_id=HOME_ID, player=("P1", 1), assist=("P2", 2)):
    """Wie tests/test_live_block_b.py::make_raw_event."""
    return {
        "time": {"elapsed": elapsed, "extra": extra},
        "team": {"id": team_id, "name": "Chelsea"},
        "player": {"id": player[1], "name": player[0]} if player else {"id": None, "name": None},
        "assist": {"id": assist[1], "name": assist[0]} if assist else {"id": None, "name": None},
        "type": kind,
        "detail": detail,
        "comments": None,
    }


def _patch_all(monkeypatch, calls=None, fixture=None, events=None, lineups=None,
               statistics=None, players=None):
    """
    Mockt alle fuenf Match-Center-Endpunkte - anders als _patch_provider in
    test_live_block_b.py wird hier auch get_fixture_players immer explizit
    gemockt, damit kein Test versehentlich einen echten Netzwerkaufruf
    ausloest (haengt sonst vom lokal gesetzten APISPORTS_KEY ab).
    """
    def _record(name, value):
        if calls is not None:
            calls.append(name)
        return value

    monkeypatch.setattr(
        live_api.apisports_api, "get_fixture_by_id",
        lambda fixture_id, timezone=None: _record(
            "fixture", [fixture if fixture is not None else make_raw_fixture()]),
    )
    monkeypatch.setattr(
        live_api.apisports_api, "get_fixture_events",
        lambda fixture_id: _record("events", events if events is not None else []),
    )
    monkeypatch.setattr(
        live_api.apisports_api, "get_fixture_lineups",
        lambda fixture_id: _record("lineups", lineups if lineups is not None else []),
    )
    monkeypatch.setattr(
        live_api.apisports_api, "get_fixture_statistics",
        lambda fixture_id: _record("statistics", statistics if statistics is not None else []),
    )
    monkeypatch.setattr(
        live_api.apisports_api, "get_fixture_players",
        lambda fixture_id: _record("players", players if players is not None else []),
    )


def _boom(fixture_id=None):
    raise live_api.ApisportsUnavailable("Quelle weg")


# ===========================================================================
# A) Score-Block (Halbzeit/Ende/Verlaengerung/Elfmeterschiessen)
# ===========================================================================

class TestScoreBlock:
    def test_normales_spiel_ohne_score_objekt(self):
        """Die meisten Antworten liefern trotzdem ein score-Objekt, aber
        ohne extratime/penalty - beide bleiben None, kein erfundener Wert."""
        raw = make_raw_fixture(status="FT", score={
            "halftime": {"home": 1, "away": 0},
            "fulltime": {"home": 2, "away": 1},
            "extratime": {"home": None, "away": None},
            "penalty": {"home": None, "away": None},
        })
        payload = build_match_center(raw, [], [], [])

        assert payload["score"]["halftime"] == {"home": 1, "away": 0}
        assert payload["score"]["fulltime"] == {"home": 2, "away": 1}
        assert payload["score"]["extratime"] is None
        assert payload["score"]["penalty"] is None

    def test_score_objekt_fehlt_komplett(self):
        """Aeltere/kaputte Antworten ohne score-Schluessel duerfen nicht crashen."""
        raw = make_raw_fixture(status="FT", score=None)
        payload = build_match_center(raw, [], [], [])

        assert payload["score"] == {
            "halftime": None, "fulltime": None, "extratime": None, "penalty": None,
        }

    def test_verlaengerung_ohne_elfmeterschiessen(self):
        raw = make_raw_fixture(status="AET", home_goals=3, away_goals=1, score={
            "halftime": {"home": 0, "away": 0},
            "fulltime": {"home": 1, "away": 1},
            "extratime": {"home": 3, "away": 1},
            "penalty": {"home": None, "away": None},
        })
        payload = build_match_center(raw, [], [], [])

        assert payload["fixture"]["status_short"] == "AET"
        assert payload["home"]["goals"] == 3
        assert payload["score"]["extratime"] == {"home": 3, "away": 1}
        assert payload["score"]["penalty"] is None

    def test_elfmeterschiessen_mit_ergebnis(self):
        """Am realen Fall verifiziert: PSG-Arsenal-Finale (fixture 1544371,
        Cache-Snapshot) endete 1:1 n.V. und wurde erst im Elfmeterschiessen
        entschieden - genau die Situation, die vor Block E nicht sichtbar war."""
        raw = make_raw_fixture(status="PEN", home_goals=1, away_goals=1, score={
            "halftime": {"home": 0, "away": 0},
            "fulltime": {"home": 1, "away": 1},
            "extratime": {"home": 1, "away": 1},
            "penalty": {"home": 5, "away": 4},
        })
        payload = build_match_center(raw, [], [], [])

        assert payload["home"]["goals"] == 1
        assert payload["away"]["goals"] == 1
        assert payload["score"]["penalty"] == {"home": 5, "away": 4}

    def test_elfmeterschiessen_status_ohne_penalty_block(self):
        """PEN-Status, aber der Provider liefert (noch) keinen penalty-Block -
        darf nicht crashen, penalty bleibt schlicht None."""
        raw = make_raw_fixture(status="PEN", score={
            "halftime": {"home": 0, "away": 0},
            "fulltime": {"home": 1, "away": 1},
            "extratime": {"home": 1, "away": 1},
            "penalty": None,
        })
        payload = build_match_center(raw, [], [], [])
        assert payload["score"]["penalty"] is None

    def test_einseitig_fehlender_wert_bleibt_erhalten(self):
        """Nur eine Seite gesetzt: Block bleibt (kein 0:0-Platzhalter fuer
        den kompletten Abschnitt), die fehlende Seite bleibt None."""
        raw = make_raw_fixture(status="PEN", score={
            "halftime": None, "fulltime": None, "extratime": None,
            "penalty": {"home": 5, "away": None},
        })
        payload = build_match_center(raw, [], [], [])
        assert payload["score"]["penalty"] == {"home": 5, "away": None}

    def test_kein_zusaetzlicher_request(self):
        """Der score-Block kommt aus derselben /fixtures?id=-Antwort wie
        Status und Tore - build_match_center ist eine reine Funktion ohne
        Netzwerk, das allein belegt es bereits strukturell."""
        source = _read("src", "api", "live_api.py")
        assert "def _normalize_score(" in source
        start = source.index("def _normalize_score(")
        block = source[start:source.index("def _normalize_match_detail(", start)]
        assert "apisports_api." not in block


# ===========================================================================
# B) Scoreboard-Frontend-Vertrag (AET/PEN)
# ===========================================================================

class TestScoreboardFrontend:
    def test_penalty_score_helper_existiert(self):
        script = _script()
        assert "function mcPenaltyScore(data)" in script

    def test_ohne_verwertbares_ergebnis_kein_wert(self):
        script = _script()
        start = script.index("function mcPenaltyScore(data)")
        block = script[start:start + 400]
        assert "if (!penalty) return null;" in block
        assert "return null" in block

    def test_penalty_zeile_nur_bei_pen_status(self):
        script = _script()
        start = script.index("function mcBuildScoreboard(data)")
        block = script[start:script.index("function mcPenaltyScore", start)]
        assert 'fixture.status_short === "PEN"' in block
        assert "mcPenaltyScore(data)" in block

    def test_grosser_spielstand_bleibt_unveraendert(self):
        """Die Elfmeterschiessen-Ergaenzung darf den regulaeren Stand
        (home/away.goals) nicht ersetzen - nur ergaenzen."""
        script = _script()
        start = script.index("function mcBuildScoreboard(data)")
        block = script[start:script.index("function mcPenaltyScore", start)]
        assert "data.home.goals" in block and "data.away.goals" in block

    def test_penalty_css_klasse_vorhanden(self):
        css = _css()
        assert ".mc-board-penalty" in css


# ===========================================================================
# C) Gelb-Rot (zweite Gelbe Karte)
# ===========================================================================

class TestGelbRot:
    def test_zweite_gelbe_wird_als_gelb_rot_erkannt(self):
        assert classify_event("Card", "Second Yellow card") == EVENT_YELLOW_RED

    def test_normale_gelbe_bleibt_gelb(self):
        assert classify_event("Card", "Yellow Card") == EVENT_YELLOW

    def test_direkte_rote_bleibt_rot(self):
        assert classify_event("Card", "Red Card") == EVENT_RED

    def test_normalize_event_setzt_gelb_rot_typ(self):
        event = normalize_event(make_raw_event(kind="Card", detail="Second Yellow card"))
        assert event["type"] == EVENT_YELLOW_RED
        assert event["player_in"] is None
        assert event["player_out"] is None

    def test_frontend_kennt_gelb_rot_icon(self):
        script = _script()
        assert '"yellow_red_card"' in script
        start = script.index("function mcEventIcon(type)")
        block = script[start:start + 500]
        assert 'if (type === "yellow_red_card")' in block

    def test_frontend_zeigt_gelb_rot_label(self):
        script = _script()
        start = script.index("function mcBuildEventRow(event, homeId)")
        block = script[start:script.index("function mcRenderEvents", start)]
        assert 'event.type === "yellow_red_card"' in block
        assert "Gelb-Rote Karte" in block

    def test_pitch_marker_zaehlt_gelb_rot_getrennt(self):
        """
        Bewusst korrigiert (Block LIVE E): die fruehere Fassung deutete
        zwei gezaehlte gelbe Karten (stats.yellow > 1) als Naeherung fuer
        Gelb-Rot. Das war falsch, weil der Provider eine zweite
        Verwarnung als eigenes Ereignis liefert. Jetzt gibt es einen
        echten yellowRed-Zaehler statt der Heuristik.
        """
        script = _script()
        start = script.index("function mcBuildEventMarkers(stats, options)")
        block = script[start:script.index("function mcShortName", start)]
        assert 'stats.yellow > 1 ? "Gelb-Rot" : "Gelbe Karte"' not in block
        assert "stats.yellowRed" in block

    def test_marker_css_klasse_vorhanden(self):
        css = _css()
        assert ".mc-pp-marker.is-yellowred" in css


# ===========================================================================
# D) Elfmetertor
# ===========================================================================

class TestElfmetertor:
    def test_verwandelter_elfmeter_setzt_is_penalty(self):
        event = normalize_event(make_raw_event(kind="Goal", detail="Penalty"))
        assert event["type"] == EVENT_GOAL
        assert event["is_penalty"] is True

    def test_normales_tor_bleibt_ohne_penalty_flag(self):
        event = normalize_event(make_raw_event(kind="Goal", detail="Normal Goal"))
        assert event["type"] == EVENT_GOAL
        assert event["is_penalty"] is False

    def test_eigentor_bleibt_unveraendert(self):
        event = normalize_event(make_raw_event(kind="Goal", detail="Own Goal"))
        assert event["type"] == EVENT_OWN_GOAL
        assert event["is_penalty"] is False

    def test_verschossener_elfmeter_bleibt_eigener_typ(self):
        """Missed Penalty ist bereits ein eigener Typ (EVENT_PENALTY_MISS) -
        die neue is_penalty-Kennzeichnung darf das nicht ueberschreiben
        oder verdoppeln, sie gilt nur fuer verwandelte Elfmeter."""
        event = normalize_event(make_raw_event(kind="Goal", detail="Missed Penalty"))
        assert event["type"] == EVENT_PENALTY_MISS
        assert event["is_penalty"] is False

    def test_unbekannter_typ_crasht_nicht(self):
        event = normalize_event(make_raw_event(kind="Nonsense", detail="Irgendwas"))
        assert event["is_penalty"] is False

    def test_frontend_zeigt_elfmeter_label(self):
        script = _script()
        start = script.index("function mcBuildEventRow(event, homeId)")
        block = script[start:script.index("function mcRenderEvents", start)]
        assert "event.is_penalty" in block
        assert "Elfmeter" in block


# ===========================================================================
# E) Partial-Failure-Haertung
# ===========================================================================

class TestPartialFailure:
    @pytest.fixture(autouse=True)
    def _isolierter_cache(self, tmp_path, monkeypatch):
        from src.utils import disk_cache
        monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path))

    def test_vollstaendiger_erfolg_setzt_alle_flags(self, monkeypatch):
        _patch_all(monkeypatch)
        payload = live_api.get_match_center(555)

        assert payload["events_available"] is True
        assert payload["lineups_available"] is True
        assert payload["statistics_available"] is True
        assert payload["player_stats_available"] is True
        assert payload["stale"] is False

    def test_events_schlaegt_fehl_match_center_bleibt_benutzbar(self, monkeypatch):
        _patch_all(monkeypatch)
        monkeypatch.setattr(live_api.apisports_api, "get_fixture_events", _boom)

        payload = live_api.get_match_center(555)

        assert payload is not None
        assert payload["events_available"] is False
        assert payload["events"] == []
        assert payload["lineups_available"] is True
        assert payload["statistics_available"] is True
        assert payload["player_stats_available"] is True
        assert payload["fixture"]["fixture_id"] == 555

    def test_lineups_schlaegt_fehl_match_center_bleibt_benutzbar(self, monkeypatch):
        _patch_all(monkeypatch)
        monkeypatch.setattr(live_api.apisports_api, "get_fixture_lineups", _boom)

        payload = live_api.get_match_center(555)

        assert payload is not None
        assert payload["lineups_available"] is False
        assert payload["home_lineup"] is None
        assert payload["away_lineup"] is None
        assert payload["events_available"] is True
        assert payload["statistics_available"] is True

    def test_statistics_schlaegt_fehl_match_center_bleibt_benutzbar(self, monkeypatch):
        _patch_all(monkeypatch)
        monkeypatch.setattr(live_api.apisports_api, "get_fixture_statistics", _boom)

        payload = live_api.get_match_center(555)

        assert payload is not None
        assert payload["statistics_available"] is False
        assert payload["statistics"] == []
        assert payload["events_available"] is True
        assert payload["lineups_available"] is True

    def test_player_enrichment_schlaegt_fehl_match_center_bleibt_benutzbar(self, monkeypatch):
        _patch_all(monkeypatch)
        monkeypatch.setattr(live_api.apisports_api, "get_fixture_players", _boom)

        payload = live_api.get_match_center(555)

        assert payload is not None
        assert payload["player_stats_available"] is False
        assert payload["events_available"] is True
        assert payload["lineups_available"] is True
        assert payload["statistics_available"] is True

    def test_fixture_schlaegt_fehl_bleibt_harter_fehler_ohne_cache(self, monkeypatch):
        """Regression: die Fixture selbst ist weiterhin kein weicher Fehler -
        ohne sie gibt es kein Match Center, unveraendert seit Block B."""
        _patch_all(monkeypatch)
        monkeypatch.setattr(live_api.apisports_api, "get_fixture_by_id", _boom)

        with pytest.raises(live_api.ApisportsUnavailable):
            live_api.get_match_center(555)

    def test_fixture_schlaegt_fehl_liefert_alten_stand(self, monkeypatch):
        """Regression: bei einem vorhandenen Cache-Eintrag faellt ein
        Fixture-Ausfall weiterhin auf stale=True zurueck, unveraendert."""
        _patch_all(monkeypatch)
        first = live_api.get_match_center(555)
        assert first["stale"] is False

        from src.utils import disk_cache
        key = "live_match:555"
        entry = disk_cache.read_entry(key)
        entry["meta"]["expires_at"] = "2000-01-01T00:00:00+00:00"
        disk_cache._write_atomic(disk_cache._path_for(key), entry)

        monkeypatch.setattr(live_api.apisports_api, "get_fixture_by_id", _boom)

        second = live_api.get_match_center(555)
        assert second["stale"] is True

    def test_unbekanntes_spiel_ueberspringt_die_vier_nebenrequests(self, monkeypatch):
        calls = []
        _patch_all(monkeypatch, calls=calls)
        monkeypatch.setattr(
            live_api.apisports_api, "get_fixture_by_id",
            lambda fixture_id, timezone=None: [],
        )

        assert live_api.get_match_center(999) is None
        assert calls == []

    def test_alle_vier_nebenendpunkte_schlagen_gleichzeitig_fehl(self, monkeypatch):
        """Auch im schlimmsten Fall (alle vier weich) bleibt die Fixture
        selbst sichtbar - kein 503, nur eine sehr duenne Antwort."""
        _patch_all(monkeypatch)
        for name in ("get_fixture_events", "get_fixture_lineups",
                    "get_fixture_statistics", "get_fixture_players"):
            monkeypatch.setattr(live_api.apisports_api, name, _boom)

        payload = live_api.get_match_center(555)

        assert payload is not None
        assert payload["events_available"] is False
        assert payload["lineups_available"] is False
        assert payload["statistics_available"] is False
        assert payload["player_stats_available"] is False
        assert payload["fixture"]["fixture_id"] == 555


# ===========================================================================
# F) Cache-Strategie bei degradiertem Payload
# ===========================================================================

class TestDegradedCache:
    @pytest.fixture(autouse=True)
    def _isolierter_cache(self, tmp_path, monkeypatch):
        from src.utils import disk_cache
        monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path))

    def test_is_degraded_erkennt_jeden_einzelnen_ausfall(self):
        vollstaendig = build_match_center(make_raw_fixture(), [], [], [])
        assert _is_degraded(vollstaendig) is False

        fuer_jede_kombination = [
            dict(events_available=False),
            dict(lineups_available=False),
            dict(statistics_available=False),
            dict(player_stats_available=False),
        ]
        for override in fuer_jede_kombination:
            degraded = build_match_center(make_raw_fixture(), [], [], [], **override)
            assert _is_degraded(degraded) is True

    def test_vollstaendiges_abgeschlossenes_spiel_behaelt_lange_ttl(self, monkeypatch):
        """Regression: ein VOLLSTAENDIGER Payload nutzt weiterhin die
        bestehende, zustandsabhaengige TTL (hier: TTL_LIVE_MATCH_SETTLED
        fuer FT) - Block E aendert daran nichts."""
        _patch_all(monkeypatch, fixture=make_raw_fixture(status="FT"))
        live_api.get_match_center(555)

        from src.utils import disk_cache
        meta = disk_cache.get_meta("live_match:555")
        assert meta is not None

        from datetime import datetime
        expires = datetime.fromisoformat(meta["expires_at"])
        fetched_at = datetime.fromisoformat(meta["fetched_at"])
        ttl_used = round((expires - fetched_at).total_seconds())
        assert ttl_used == TTL_LIVE_MATCH_SETTLED

    def test_degradiertes_abgeschlossenes_spiel_bekommt_kurze_ttl(self, monkeypatch):
        """
        Kernanforderung aus dem GO-Prompt: ein voruebergehender Ausfall
        eines Unterendpunkts darf bei einem abgepfiffenen Spiel NICHT
        mit TTL_LIVE_MATCH_SETTLED (3 Tage) eingefroren werden.
        """
        _patch_all(monkeypatch, fixture=make_raw_fixture(status="FT"))
        monkeypatch.setattr(live_api.apisports_api, "get_fixture_statistics", _boom)

        live_api.get_match_center(555)

        from src.utils import disk_cache
        from datetime import datetime
        meta = disk_cache.get_meta("live_match:555")
        expires = datetime.fromisoformat(meta["expires_at"])
        fetched_at = datetime.fromisoformat(meta["fetched_at"])
        ttl_used = round((expires - fetched_at).total_seconds())

        assert ttl_used == TTL_LIVE_MATCH_DEGRADED
        assert ttl_used < TTL_LIVE_MATCH_SETTLED

    def test_frischer_treffer_kostet_keine_requests_auch_nach_degradation(self, monkeypatch):
        """Ein noch frischer (wenn auch degradierter) Cache-Eintrag wird
        weiterhin direkt ausgeliefert - kein Request-Spam durch wiederholte
        Versuche innerhalb der kurzen Degraded-TTL."""
        calls = []
        _patch_all(monkeypatch, calls=calls, fixture=make_raw_fixture(status="FT"))
        monkeypatch.setattr(live_api.apisports_api, "get_fixture_statistics", _boom)

        first = live_api.get_match_center(555)
        second = live_api.get_match_center(555)

        assert first["statistics_available"] is False
        assert second["statistics_available"] is False
        assert calls.count("fixture") == 1

    def test_platten_cache_nicht_in_memory(self):
        """Weiterhin worker-safe: keine neue In-Memory-only-Schicht,
        derselbe Disk-Cache-Mechanismus wie der Rest des Match Centers."""
        source = _read("src", "api", "live_api.py")
        start = source.index("def get_match_center(fixture_id):")
        block = source[start:]
        assert "write_entry(" in block
        assert "read_entry(key)" in block


# ===========================================================================
# G) Frontend: neutrale Zustaende fuer nicht verfuegbare Tabs
# ===========================================================================

class TestDegradedTabsFrontend:
    def test_events_tab_zeigt_neutralen_zustand(self):
        script = _script()
        start = script.index("function mcRenderEvents(data)")
        block = script[start:script.index("function mcStatShare", start)]
        assert "data.events_available === false" in block
        assert "nicht verfügbar" in block

    def test_lineups_tab_zeigt_neutralen_zustand(self):
        script = _script()
        start = script.index("function mcRenderLineups(data)")
        block = script[start:script.index("function mcEventIcon", start)]
        assert "data.lineups_available === false" in block
        assert "nicht verfügbar" in block

    def test_stats_tab_zeigt_neutralen_zustand(self):
        script = _script()
        start = script.index("function mcRenderStats(data)")
        block = script[start:script.index("function mcBuildNote", start)]
        assert "data.statistics_available === false" in block
        assert "nicht verfügbar" in block

    def test_nicht_verfuegbar_unterscheidet_sich_vom_normalzustand(self):
        """
        'derzeit nicht verfügbar' (Ausfall) und 'noch nicht verfügbar'
        (normaler Zustand vor Anpfiff/Veroeffentlichung) muessen zwei
        unterschiedliche Texte bleiben - sonst kann der Nutzer einen
        Ausfall nicht von einem ganz normalen Wartezustand unterscheiden.
        """
        script = _script()
        assert "derzeit nicht verfügbar" in script
        assert "noch nicht verfügbar" in script


# ===========================================================================
# H) Mobile: Kader-Touch-Ziel
# ===========================================================================

class TestMobileTouchTarget:
    def _squad_block(self):
        """
        Der 420px-Block, der die Kaderkacheln enthaelt.

        Bewusst ueber den Inhalt gesucht statt ueber "der letzte Block der
        Datei": es gibt inzwischen mehrere 420px-Bloecke (Block F1 hat
        eigene ergaenzt), und die Kaderregel steht weiterhin in ihrem
        eigenen.
        """
        from tests.conftest import css_media_blocks
        blocks = css_media_blocks(_css(), "@media (max-width: 420px)")
        matching = [b for b in blocks if ".td-squad-entry .mc-pp-avatar" in b]
        assert matching, "Kein 420px-Block enthaelt die Kaderkachel-Regel"
        return matching[0]

    def test_kader_avatar_bei_420px_naeher_am_touch_richtwert(self):
        block = self._squad_block()
        assert ".td-squad-entry .mc-pp-avatar" in block
        assert "width: 38px" not in block

    def test_kein_horizontaler_overflow_durch_die_aenderung(self):
        """Das Grid bleibt auto-fill/1fr-basiert - eine groessere
        Mindestbreite kann keine feste Gesamtbreite sprengen."""
        block = self._squad_block()
        assert "grid-template-columns: repeat(auto-fill, minmax(" in block
