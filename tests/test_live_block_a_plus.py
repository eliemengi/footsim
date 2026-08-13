"""
Tests fuer LIVE A+ (Datumsnavigation + Auto-Refresh), aufbauend auf
Block LIVE A (tests/test_live_block_a.py, dort unveraendert getestet).

Abgedeckt:
  A) Erweiterte, dokumentierte Datumsgrenze statt starrem
     Gestern/Heute/Morgen-Fenster
  B) Konkrete Kalenderdaten (auch mehrere Wochen entfernt) werden
     akzeptiert, extreme Werte weiterhin abgelehnt
  C) Europe/Berlin bleibt die Grundlage der "heute"-Berechnung
  D) Frontend: Datumsnavigation ersetzt das alte starre Gestern/Heute/
     Morgen-Widget einheitlich (kein zweites, konkurrierendes System)
  E) Frontend: Auto-Refresh startet/stoppt nur unter den richtigen
     Bedingungen, genau ein Timer, Hintergrund-Refresh ohne Lade-Flackern
  F) Hauptnavigation unveraendert: Simulation | Vergleiche | Live | Spieler

Backend-Tests treiben echten Code (kein Mocking der Datumsarithmetik).
Frontend-Tests sind wie im Projekt ueblich Quelltext-Assertions auf
script.js/style.css (kein Browser/DOM verfuegbar).
"""

import os
from datetime import date, timedelta

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(PROJECT_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _live_module_source():
    """
    Nur der Live-Abschnitt von script.js (Abschnitt 16c bis vor 17).
    Andere Features (z. B. eine unabhaengige Touch-Geste woanders im
    Frontend, oder dieser Docstring hier) sollen Assertions ueber "kein
    Touch-Code"/"kein Provider-Name im Frontend" nicht faelschlich
    zum Scheitern bringen.
    """
    script = _read("static", "script.js")
    start = script.index("/* ---------- 16c. LIVE")
    end = script.index("/* ---------- 17. START")
    return script[start:end]


# ===========================================================================
# A) + B) Datumsgrenze
# ===========================================================================

class TestErweiterteDatumsgrenze:
    @pytest.fixture
    def app_module(self):
        import app as app_module
        return app_module

    def test_fenster_ist_deutlich_groesser_als_gestern_heute_morgen(self, app_module):
        """
        Die alte harte Grenze war 7 Tage (passend zu Gestern/Heute/
        Morgen). LIVE A+ erlaubt freie Navigation - das Fenster muss
        das klar ueberschreiten.
        """
        assert app_module.LIVE_DATE_WINDOW_DAYS > 7

    def test_mehrere_wochen_zurueck_werden_akzeptiert(self, app_module):
        today = app_module._today_in_display_timezone()
        requested = (today - timedelta(days=21)).isoformat()

        resolved, error = app_module._resolve_live_date(requested)

        assert error is None
        assert resolved.isoformat() == requested

    def test_mehrere_wochen_voraus_werden_akzeptiert(self, app_module):
        today = app_module._today_in_display_timezone()
        requested = (today + timedelta(days=21)).isoformat()

        resolved, error = app_module._resolve_live_date(requested)

        assert error is None
        assert resolved.isoformat() == requested

    def test_konkretes_kalenderdatum_wird_direkt_uebernommen(self, app_module):
        """Beispiel aus der Anforderung: heute + 17 Tage direkt anspringen."""
        today = app_module._today_in_display_timezone()
        target = today + timedelta(days=17)

        resolved, error = app_module._resolve_live_date(target.isoformat())

        assert error is None
        assert resolved == target

    def test_grenze_des_fensters_wird_noch_akzeptiert(self, app_module):
        today = app_module._today_in_display_timezone()
        edge = today + timedelta(days=app_module.LIVE_DATE_WINDOW_DAYS)

        resolved, error = app_module._resolve_live_date(edge.isoformat())

        assert error is None
        assert resolved == edge

    def test_ein_tag_ausserhalb_des_fensters_wird_abgelehnt(self, app_module):
        today = app_module._today_in_display_timezone()
        beyond = today + timedelta(days=app_module.LIVE_DATE_WINDOW_DAYS + 1)

        resolved, error = app_module._resolve_live_date(beyond.isoformat())

        assert resolved is None
        assert error is not None

    def test_extrem_weit_entfernte_daten_bleiben_abgelehnt(self, app_module):
        """Das Fenster ist grosszuegiger, aber nicht unbegrenzt."""
        for extreme in ["1999-01-01", "2099-12-31", "1900-06-15"]:
            resolved, error = app_module._resolve_live_date(extreme)
            assert resolved is None, extreme
            assert error is not None, extreme

    def test_muellwerte_werden_weiterhin_sauber_abgelehnt(self, app_module):
        for garbage in ["kein-datum", "2026-13-40", "", "   ", "gestern"]:
            resolved, error = app_module._resolve_live_date(garbage or None)
            if not garbage or not garbage.strip():
                # Leerer Wert bedeutet "heute", das ist kein Fehlerfall.
                continue
            assert resolved is None, garbage
            assert error is not None, garbage

    def test_route_akzeptiert_ein_datum_mehrere_wochen_voraus(self, app_module, monkeypatch):
        from src.api import live_api

        monkeypatch.setattr(
            live_api.apisports_api, "get_fixtures_by_date",
            lambda date_str, timezone=None: [],
        )

        app_module.app.config["TESTING"] = True
        client = app_module.app.test_client()

        today = app_module._today_in_display_timezone()
        target = (today + timedelta(days=28)).isoformat()

        response = client.get(f"/api/live-matches?date={target}")

        assert response.status_code == 200
        assert response.get_json()["date"] == target

    def test_fensterbreite_ist_ein_dokumentierter_konstanter_wert(self):
        """Keine verstreute magische Zahl - ein benannter, kommentierter Wert."""
        source = _read("app.py")
        assert "LIVE_DATE_WINDOW_DAYS = 60" in source


# ===========================================================================
# C) Zeitzone bleibt Grundlage
# ===========================================================================

class TestZeitzoneBleibtMassgeblich:
    def test_heute_kommt_aus_europe_berlin(self):
        import app as app_module
        from src.api import live_api

        # Dieselbe Zonenquelle wie live_api, nicht eine zweite,
        # potenziell abweichende Berechnung.
        assert str(live_api.BERLIN) == "Europe/Berlin"
        assert isinstance(app_module._today_in_display_timezone(), date)

    def test_app_verwendet_live_api_zeitzone_nicht_eigene(self):
        source = _read("app.py")
        assert "datetime.now(live_api.BERLIN)" in source


# ===========================================================================
# D) Frontend: einheitliche Datumsnavigation
# ===========================================================================

class TestFrontendDatumsnavigation:
    def test_kein_zweites_konkurrierendes_datumssystem(self):
        """
        Das alte relative dayOffset-Modell (-1/0/1) darf nicht neben dem
        neuen absoluten selectedDate weiterleben.
        """
        script = _read("static", "script.js")
        assert "dayOffset" not in script
        assert "liveDateForOffset" not in script
        assert "liveSetDay(" not in script

    def test_selected_date_ist_die_einzige_datumsquelle(self):
        script = _read("static", "script.js")
        assert "selectedDate" in script
        assert "function liveSetSelectedDate(isoDate)" in script

    def test_pfeile_verschieben_um_einen_tag(self):
        script = _read("static", "script.js")
        assert "liveShiftDate(liveState.selectedDate, -1)" in script
        assert "liveShiftDate(liveState.selectedDate, 1)" in script

    def test_streifen_ist_nativ_scrollbar_kein_touch_handler(self):
        """
        Swipe soll ueber natives horizontales Scrollen laufen, nicht
        ueber eigene touchstart/touchmove-Logik im Live-Modul. Andere
        Features im Frontend duerfen eigene Touch-Handler haben - das
        ist hier nicht das Thema, deshalb nur im Live-Abschnitt geprueft.
        """
        live_source = _live_module_source()
        assert "touchstart" not in live_source
        assert "touchmove" not in live_source
        assert "touchend" not in live_source

        css = _read("static", "style.css")
        assert "overflow-x: auto" in css

    def test_streifen_erkennt_settle_ohne_dauerpolling(self):
        script = _read("static", "script.js")
        assert 'addEventListener("scroll"' in script
        assert "LIVE_STRIP_SETTLE_DELAY_MS" in script

    def test_kalender_nutzt_native_showpicker_mit_fallback(self):
        script = _read("static", "script.js")
        assert "liveCalendarInput.showPicker" in script
        assert "liveCalendarInput.click()" in script

    def test_kalender_input_wird_bei_tageswechsel_synchronisiert(self):
        script = _read("static", "script.js")
        assert "liveCalendarInput.value = isoDate" in script


# ===========================================================================
# E) Auto-Refresh
# ===========================================================================

class TestAutoRefresh:
    def test_intervall_liegt_im_geforderten_rahmen(self):
        script = _read("static", "script.js")
        start = script.index("const LIVE_REFRESH_INTERVAL_MS")
        line = script[start:script.index(";", start) + 1]
        value = int("".join(ch for ch in line.split("=")[1] if ch.isdigit()))
        assert 45000 <= value <= 60000

    def test_listen_timer_entsteht_nur_im_eigenen_scheduler(self):
        """
        Der Timer der Tagesliste darf ausschliesslich in
        liveScheduleAutoRefresh() entstehen - nirgendwo sonst im Code
        wird liveState.refreshTimer gesetzt.

        Die Gesamtzahl der setInterval-Stellen prueft
        tests/test_live_block_b.py, seit das Match Center einen zweiten,
        eigenen Timer mitbringt.
        """
        script = _read("static", "script.js")
        assert script.count("liveState.refreshTimer = setInterval(") == 1
        assert script.count("liveState.refreshTimer =") == 2  # setzen + auf null zuruecksetzen

    def test_schedule_raeumt_immer_zuerst_auf(self):
        """
        liveScheduleAutoRefresh() muss liveStopAutoRefresh() als ersten
        Schritt rufen - sonst koennten zwei Timer nebeneinander laufen.
        """
        script = _read("static", "script.js")
        start = script.index("function liveScheduleAutoRefresh(data)")
        block = script[start:start + 300]
        assert "liveStopAutoRefresh();" in block
        # Der Aufruf muss vor der naechsten Funktionsdefinition/dem
        # naechsten Codepfad stehen, nicht irgendwo tief im Timer-Callback.
        assert block.index("liveStopAutoRefresh();") < block.index("if (!liveShouldAutoRefresh")

    def test_bedingungen_pruefen_bereich_tag_liveCount_und_sichtbarkeit(self):
        script = _read("static", "script.js")
        start = script.index("function liveShouldAutoRefresh(data)")
        block = script[start:script.index("}", script.index("{", start)) + 1]

        assert 'state.activeArea === "live"' in block
        assert "data.is_today === true" in block
        assert "data.live_count" in block
        assert 'document.visibilityState === "visible"' in block

    def test_verlassen_von_live_stoppt_auto_refresh(self):
        """setActiveArea() muss ausserhalb von 'live' explizit stoppen."""
        script = _read("static", "script.js")
        start = script.index('if (area === "live") {')
        block = script[start:start + 200]
        assert "liveInit();" in block
        assert "liveStopAutoRefresh();" in block

    def test_tageswechsel_stoppt_den_alten_timer(self):
        script = _read("static", "script.js")
        start = script.index("function liveSetSelectedDate(isoDate)")
        block = script[start:script.index("function liveRenderStrip", start)]
        assert "liveStopAutoRefresh();" in block

    def test_sichtbarkeitswechsel_pausiert_und_setzt_fort(self):
        script = _read("static", "script.js")
        assert 'addEventListener("visibilitychange"' in script
        start = script.index('addEventListener("visibilitychange"')
        block = script[start:start + 600]
        assert "liveStopAutoRefresh();" in block
        assert 'background: true' in block

    def test_vergangene_und_zukuenftige_tage_werden_nicht_gepollt(self):
        """
        is_today ist Teil der Startbedingung - ein Tag, der nicht heute
        ist, kann liveShouldAutoRefresh() nie erfuellen.
        """
        script = _read("static", "script.js")
        start = script.index("function liveShouldAutoRefresh(data)")
        block = script[start:script.index("}", script.index("{", start)) + 1]
        assert "data.is_today === true" in block

    def test_kein_laufendes_spiel_verhindert_polling(self):
        script = _read("static", "script.js")
        start = script.index("function liveShouldAutoRefresh(data)")
        block = script[start:script.index("}", script.index("{", start)) + 1]
        assert "live_count" in block and "> 0" in block

    def test_hintergrund_refresh_ueberspringt_ladeanzeige(self):
        """
        Kein "Spiele werden geladen"-Text bei jedem automatischen Tick -
        sonst flackert die Seite alle 45-60 Sekunden.
        """
        script = _read("static", "script.js")
        start = script.index("async function liveLoad(options)")
        block = script[start:script.index("try {", start)]
        assert "if (!background) {" in block
        assert 'liveSetStatus(t("live.loading"))' in block

    def test_hintergrund_fehler_zerstoert_sichtbare_seite_nicht(self):
        script = _read("static", "script.js")
        start = script.index("async function liveLoad(options)")
        block = script[start:start + 3000]
        catch_index = block.index("} catch (error) {")
        assert "if (!background) {" in block[catch_index:]

    def test_auto_refresh_nutzt_die_bestehende_live_route(self):
        """
        Kein direkter API-Football-Zugriff aus dem Frontend - weder beim
        ersten Laden noch beim Auto-Refresh. Erklaerende Kommentare, die
        den Provider beim Namen nennen, sind erlaubt; hier geht es um
        tatsaechliche Netzwerkziele/Schluessel.
        """
        live_source = _live_module_source()
        assert "v3.football.api-sports.io" not in live_source
        assert "x-rapidapi" not in live_source.lower()
        assert "APISPORTS_KEY" not in live_source

        # Jeder Fetch im Live-Modul geht gegen eine eigene FootSim-Route.
        # Seit LIVE B sind das zwei: die Tagesliste und das Match Center.
        import re
        targets = re.findall(r"fetchJson\(`([^`]+)`", live_source)
        assert len(targets) == live_source.count("fetchJson(")
        assert all(target.startswith("/api/") for target in targets), targets


# ===========================================================================
# F) Hauptnavigation unveraendert
# ===========================================================================

class TestNavigationUnveraendert:
    def test_reihenfolge_bleibt_simulation_vergleiche_live_spieler(self):
        html = _read("templates", "index.html")

        positions = []
        start = 0
        while True:
            found = html.find('class="area-btn', start)
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

    def test_weiterhin_genau_vier_hauptbereiche(self):
        html = _read("templates", "index.html")
        assert html.count('class="area-btn') == 4
        assert html.count('class="bottom-nav-btn') == 4
