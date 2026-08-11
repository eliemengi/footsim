"""
Tests fuer Block LIVE D1 (Spielerprofil aus dem Match Center).

Abgedeckt:
  A) season im Match-Center-Payload (live_api.py)
  B) LIVE-C-Spieler sind antippbar (script.js, Textvertraege)
  C) Navigation: kein Bereichswechsel, kein verlorener Match-Center-Zustand
  D) "Vergleichen" nutzt die bestehende Spielervergleich-Architektur
  E) Mobile/Markup-Vertraege
  F) Bestehende LIVE-B/C-Vertraege regressieren nicht

Backend-Tests gegen synthetische Provider-Antworten (kein echter Request),
Frontend-Tests als Textvertraege - dasselbe Muster wie
tests/test_live_block_b.py und tests/test_live_block_c.py.
"""

import os

import pytest

from src.api import live_api
from src.api.live_api import _parse_season, build_match_center


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(PROJECT_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


HOME_ID = 49
AWAY_ID = 42


def make_raw_fixture(season=2025, fixture_id=555):
    return {
        "fixture": {
            "id": fixture_id,
            "date": "2026-08-11T20:30:00+02:00",
            "referee": "C. Kavanagh",
            "venue": {"id": 1, "name": "Stamford Bridge", "city": "London"},
            "status": {"long": "Match Finished", "short": "FT",
                       "elapsed": 90, "extra": None},
        },
        "league": {"id": 39, "name": "Premier League", "country": "England",
                   "logo": "https://x/l39.png", "round": "Regular Season - 38",
                   "season": season},
        "teams": {
            "home": {"id": HOME_ID, "name": "Chelsea", "logo": "https://x/49.png"},
            "away": {"id": AWAY_ID, "name": "Arsenal", "logo": "https://x/42.png"},
        },
        "goals": {"home": 2, "away": 1},
    }


# ===========================================================================
# A) Saison im Match-Center-Payload
# ===========================================================================

class TestSeasonParsing:
    def test_ganzzahl(self):
        assert _parse_season(2025) == 2025

    def test_numerischer_string(self):
        assert _parse_season("2025") == 2025

    def test_fehlend(self):
        assert _parse_season(None) is None

    def test_kaputt(self):
        for wert in ["", "zwanzigfuenfundzwanzig", [], {}, object()]:
            assert _parse_season(wert) is None

    def test_bool_ist_keine_saison(self):
        assert _parse_season(True) is None


class TestSeasonImPayload:
    def test_season_im_league_block(self):
        payload = build_match_center(make_raw_fixture(season=2025), [], [], [])
        assert payload["league"]["season"] == 2025

    def test_fehlende_season_bricht_nichts(self):
        raw = make_raw_fixture()
        raw["league"]["season"] = None
        payload = build_match_center(raw, [], [], [])
        assert payload["league"]["season"] is None
        assert payload["fixture"]["fixture_id"] == 555

    def test_kaputte_season_bricht_nichts(self):
        raw = make_raw_fixture()
        raw["league"]["season"] = "nicht-numerisch"
        payload = build_match_center(raw, [], [], [])
        assert payload["league"]["season"] is None

    def test_kein_zusaetzlicher_request(self):
        """
        Die Saison kommt aus derselben, ohnehin bereits abgerufenen
        Fixture-Antwort - kein fuenfter Request nur fuer dieses Feld.
        """
        source = _read("src", "api", "live_api.py")
        start = source.index("def _normalize_match_detail")
        block = source[start:start + 2500]
        assert '"season": _parse_season(league.get("season"))' in block


# ===========================================================================
# B) LIVE-C-Spieler sind antippbar
# ===========================================================================

def _script():
    return _read("static", "script.js")


class TestSpielerAntippbar:
    def test_pitch_spieler_wird_tappable_gemacht(self):
        script = _script()
        start = script.index("function mcBuildPitchPlayer(player, stats)")
        block = script[start:script.index("function mcBuildPitch(lineup", start)]
        assert "mcMakeTappable(node, () => mcOpenPlayer(player))" in block

    def test_bankspieler_wird_tappable_gemacht(self):
        script = _script()
        start = script.index("function mcBuildPlayerRow(player, stats)")
        block = script[start:script.index("function mcBuildLineupBlock", start)]
        assert "mcMakeTappable(row, () => mcOpenPlayer(player))" in block

    def test_kein_button_element_fuer_verschachtelte_bloecke(self):
        """
        mc-pp und mc-player verschachteln div in div - ein <button> waere
        dafuer ungueltiges HTML. role=button + tabindex uebernimmt
        stattdessen die Bedienbarkeit.
        """
        script = _script()
        start = script.index("function mcMakeTappable(node, handler)")
        block = script[start:start + 700]
        assert 'setAttribute("role", "button")' in block
        assert 'setAttribute("tabindex", "0")' in block

    def test_tastatur_aktiviert_ebenfalls(self):
        script = _script()
        start = script.index("function mcMakeTappable(node, handler)")
        block = script[start:start + 700]
        assert '"Enter"' in block
        assert '" "' in block

    def test_stabile_player_id_ohne_namenssuche(self):
        script = _script()
        start = script.index("function mcOpenPlayer(player)")
        block = script[start:script.index("function mcBuildPitchPlayer", start)]
        assert "player.id" in block
        assert "player.name" not in block

    def test_saison_kommt_aus_dem_geladenen_payload(self):
        script = _script()
        start = script.index("function mcOpenPlayer(player)")
        block = script[start:script.index("function mcBuildPitchPlayer", start)]
        assert "mcState.data" in block
        assert "league.season" in block

    def test_ohne_id_kein_tap_handler(self):
        """Spieler ohne id() koennen nicht existieren, aber defensiv geprueft."""
        script = _script()
        start = script.index("function mcBuildPitchPlayer(player, stats)")
        block = script[start:script.index("function mcBuildPitch(lineup", start)]
        assert "if (player.id !== null && player.id !== undefined) {" in block


# ===========================================================================
# C) Navigation und Zustand
# ===========================================================================

class TestNavigation:
    def test_oeffnen_wechselt_den_bereich_nicht(self):
        """
        pdOpen() darf setActiveArea() NICHT aufrufen - das wuerde ueber
        dessen eigene Logik den Match-Center-Auto-Refresh stoppen und die
        Navigation auf "Spieler" umschalten (siehe setActiveArea()).
        """
        script = _script()
        start = script.index("function pdOpen(playerId, options)")
        block = script[start:script.index("function pdClose()", start)]
        assert "setActiveArea(" not in block

    def test_schliessen_wechselt_den_bereich_nicht(self):
        script = _script()
        start = script.index("function pdClose()")
        block = script[start:script.index("if (pdBackBtn)", start)]
        assert "setActiveArea(" not in block

    def test_oeffnen_versteckt_nur_den_aktiven_app_area_knoten(self):
        script = _script()
        start = script.index("function pdOpen(playerId, options)")
        block = script[start:script.index("function pdClose()", start)]
        assert 'querySelector(\n            `.app-area[data-area="${state.activeArea}"]`' \
            in block or '.app-area[data-area="${state.activeArea}"]' in block
        assert "hiddenAreaNode" in block

    def test_schliessen_stellt_den_bereich_wieder_her(self):
        script = _script()
        start = script.index("function pdClose()")
        block = script[start:script.index("if (pdBackBtn)", start)]
        assert "show(pdState.hiddenAreaNode)" in block

    def test_match_center_funktionen_werden_nicht_aufgerufen(self):
        """
        Kein mcClose()/mcStopAutoRefresh()/mcOpen() innerhalb von
        pdOpen()/pdClose() - der Match-Center-Zustand bleibt unberuehrt,
        weil er schlicht nie angefasst wird.
        """
        script = _script()
        open_start = script.index("function pdOpen(playerId, options)")
        open_block = script[open_start:script.index("function pdClose()", open_start)]
        close_start = script.index("function pdClose()")
        close_block = script[close_start:script.index("if (pdBackBtn)", close_start)]

        for verboten in ("mcClose(", "mcStopAutoRefresh(", "mcOpen("):
            assert verboten not in open_block
            assert verboten not in close_block

    def test_zurueck_knopf_vorhanden(self):
        html = _read("templates", "index.html")
        assert 'id="pd-back"' in html

        script = _script()
        assert 'pdBackBtn.addEventListener("click", pdClose)' in script

    def test_zurueck_beschriftung_kontextsensitiv(self):
        script = _script()
        start = script.index("function pdOpen(playerId, options)")
        block = script[start:script.index("function pdClose()", start)]
        assert 'pdState.returnTo === "live"' in block
        assert "Zurück zum Spiel" in block

    def test_kein_fuenfter_hauptbereich(self):
        """
        player-detail-view ist bewusst KEIN app-area - der
        Vier-Hauptbereiche-Vertrag bleibt unberuehrt.
        """
        html = _read("templates", "index.html")
        start = html.index('id="player-detail-view"')
        tag_line = html[start - 60:start + 40]
        assert "app-area" not in tag_line

        script = _script()
        start = script.index("const AREAS = [")
        line = script[start:script.index("]", start)]
        assert '"players"' in line and line.count('"') == 8

    def test_request_token_gegen_race_conditions(self):
        """Antwort zu Spieler A darf Spieler B nicht ueberschreiben."""
        script = _script()
        start = script.index("async function pdLoad(options)")
        block = script[start:script.index("function pdSetScope", start)]
        assert "++pdState.requestToken" in block
        assert "token !== pdState.requestToken" in block


# ===========================================================================
# D) "Vergleichen"
# ===========================================================================

class TestVergleichenIntegration:
    def test_knopf_vorhanden(self):
        html = _read("templates", "index.html")
        assert 'id="pd-compare-btn"' in html

        script = _script()
        assert 'pdCompareBtn.addEventListener("click", pdCompare)' in script

    def test_nutzt_bestehenden_pcstate(self):
        script = _script()
        start = script.index("async function pdCompare()")
        block = script[start:script.index("if (pdCompareBtn)", start)]
        assert "pcState[slot]" in block
        assert "pcSelectPlayer(slot," in block

    def test_kein_zweiter_vergleichsmechanismus(self):
        source_app = _read("app.py")
        # Keine zweite /api/... -compare-Route fuer D1.
        assert source_app.count('@app.route("/api/player-compare"') == 1
        assert '@app.route("/api/player-detail-compare"' not in source_app

    def test_wartet_auf_initialisierte_saisonauswahl(self):
        """
        Wie pcHandleInput() beim ersten Suchversuch: die Saisonauswahl
        muss stehen, bevor ein Slot befuellt wird.
        """
        script = _script()
        start = script.index("async function pdCompare()")
        block = script[start:script.index("if (pdCompareBtn)", start)]
        assert "await pcInitControls()" in block

    def test_wechselt_bewusst_in_den_spielerbereich(self):
        """
        Einzige gewollte Ausnahme: "Vergleichen" verlaesst den
        Live-Kontext absichtlich.
        """
        script = _script()
        start = script.index("async function pdCompare()")
        block = script[start:script.index("if (pdCompareBtn)", start)]
        assert 'setActiveArea("players")' in block
        assert 'pcSetMode("radar")' in block

    def test_schliesst_das_profil_vor_dem_wechsel(self):
        script = _script()
        start = script.index("async function pdCompare()")
        block = script[start:script.index("if (pdCompareBtn)", start)]
        assert "pdClose();" in block


# ===========================================================================
# E) Mobile / Markup
# ===========================================================================

class TestMobileUndMarkup:
    def test_scope_auswahl_nutzt_bestehendes_muster(self):
        html = _read("templates", "index.html")
        start = html.index('id="pd-scope-nav"')
        block = html[start:start + 600]
        assert "pc-scope-btn" in block
        assert 'data-scope="club_all"' in block
        assert 'data-scope="cl"' in block

    def test_avatar_wiederverwendet(self):
        """Derselbe Avatar-Baustein wie auf dem Pitch, nur groesser skaliert."""
        script = _script()
        start = script.index("function pdBuildHeader(data)")
        block = script[start:start + 400]
        assert "mcBuildAvatar(" in block

        css = _read("static", "style.css")
        assert ".pd-header .mc-pp-avatar" in css

    def test_mobile_breakpoints_vorhanden(self):
        css = _read("static", "style.css")
        assert "@media (max-width: 768px)" in css
        start = css.index(".pd-core-grid {")
        assert start > 0

        idx_420 = css.index("@media (max-width: 420px)", css.index(".pd-header {"))
        block = css[idx_420:idx_420 + 700]
        assert ".pd-core-grid" in block

    def test_lange_namen_brechen_nicht_das_layout(self):
        css = _read("static", "style.css")
        start = css.index(".pd-name {")
        block = css[start:start + 200]
        assert "overflow-wrap: anywhere" in block

    def test_kein_erfundenes_wert_bei_fehlender_bewertung(self):
        """pcFormatValue liefert "–" fuer null - wird auch hier verwendet."""
        script = _script()
        start = script.index("function pdBuildCoreGrid(coreStats)")
        block = script[start:start + 400]
        assert "pcFormatValue(" in block


# ===========================================================================
# F) Bestehende LIVE-B/C-Vertraege bleiben unveraendert
# ===========================================================================

class TestKeineRegression:
    def test_vier_reiter_unveraendert(self):
        html = _read("templates", "index.html")
        import re
        start = html.index('id="mc-tab-bar"')
        block = html[start:html.index("</div>", start)]
        assert re.findall(r'data-mctab="([a-z]+)"', block) == \
            ["overview", "lineups", "events", "stats"]

    def test_match_center_polling_unveraendert(self):
        script = _script()
        assert script.count("setInterval(") == 2

    def test_grid_engine_weiterhin_formationsfrei(self):
        source = _read("src", "api", "live_api.py")
        for formation in ("4-3-3", "4-2-3-1", "3-5-2"):
            assert f'"{formation}"' not in source

    def test_spielerbewertung_unveraendert_zentral(self):
        source = _read("src", "api", "live_api.py")
        assert source.count("RATING_TIERS = [") == 1
