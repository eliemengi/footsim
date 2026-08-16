"""
Tests fuer Block LIVE D2 (Teamprofil aus dem Match Center, Kader -> D1).

Abgedeckt:
  A) Detail-View-Stack (openDetailView/closeDetailView) - generisch,
     unabhaengig von Spieler- oder Teamprofil
  B) LIVE-C-Teams sind antippbar (Anzeigetafel und Aufstellungskopf)
  C) Navigation: Match -> Team -> zurueck, Match -> Team -> Spieler ->
     zurueck -> Team -> zurueck -> Match
  D) Kader -> D1 Player Detail (bestehende Infrastruktur, keine zweite)
  E) Mobile/Markup-Vertraege
  F) Bestehende LIVE-A-D1-Vertraege regressieren nicht

Backend-Normalisierung/-Cache wird in tests/test_team_detail.py
abgedeckt. Diese Datei prueft ausschliesslich die Verdrahtung im
Frontend sowie die Navigations- und Bereichsvertraege - dasselbe Muster
wie tests/test_live_block_d1.py.
"""

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(PROJECT_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _script():
    return _read("static", "script.js")


# ===========================================================================
# A) Detail-View-Stack
# ===========================================================================

class TestDetailViewStack:
    def test_stack_existiert(self):
        script = _script()
        assert "const detailViewStack = [];" in script
        assert "function openDetailView(viewNode)" in script
        assert "function closeDetailView()" in script

    def test_oeffnen_versteckt_app_area_beim_ersten_mal(self):
        script = _script()
        start = script.index("function openDetailView(viewNode)")
        block = script[start:script.index("function closeDetailView()", start)]
        assert '.app-area[data-area="${state.activeArea}"]' in block

    def test_oeffnen_versteckt_vorherige_detailansicht_bei_verschachtelung(self):
        """
        Der Kernpunkt von D2: eine zweite Detailansicht (z. B. Spieler
        aus dem Kader) versteckt die ERSTE Detailansicht (Team), nicht
        erneut den urspruenglichen .app-area-Knoten.
        """
        script = _script()
        start = script.index("function openDetailView(viewNode)")
        block = script[start:script.index("function closeDetailView()", start)]
        assert "detailViewStack.length" in block
        assert "detailViewStack[detailViewStack.length - 1]" in block
        assert "detailViewStack.push(" in block

    def test_erneutes_oeffnen_derselben_ansicht_ist_no_op(self):
        """
        Ein zweiter Tap auf einen anderen Spieler, waehrend das Profil
        schon offen ist, darf den Stack nicht doppelt befuellen.
        """
        script = _script()
        start = script.index("function openDetailView(viewNode)")
        block = script[start:script.index("function closeDetailView()", start)]
        assert "if (top && top.view === viewNode) return;" in block

    def test_schliessen_stellt_das_davor_sichtbare_wieder_her(self):
        script = _script()
        start = script.index("function closeDetailView()")
        block = script[start:start + 400]
        assert "detailViewStack.pop()" in block
        assert "show(entry.hidden)" in block

    def test_schliessen_ohne_offene_ansicht_ist_sicher(self):
        script = _script()
        start = script.index("function closeDetailView()")
        block = script[start:start + 400]
        assert "if (!entry) return;" in block

    def test_kein_setActiveArea_im_stack(self):
        """
        Der generische Stack darf selbst keinen Bereichswechsel ausloesen -
        das bleibt eine bewusste Entscheidung der Aufrufer (z. B.
        "Vergleichen"), nicht des generischen Mechanismus.
        """
        script = _script()
        start = script.index("const detailViewStack = [];")
        block = script[start:script.index("function closeDetailView()", start) + 400]
        assert "setActiveArea(" not in block

    def test_spielerprofil_nutzt_den_stack(self):
        script = _script()
        assert "openDetailView(pdView)" in script
        assert "closeDetailView();" in script

    def test_teamprofil_nutzt_denselben_stack(self):
        script = _script()
        assert "openDetailView(tdView)" in script
        start = script.index("function tdClose()")
        block = script[start:start + 400]
        assert "closeDetailView()" in block


# ===========================================================================
# B) LIVE-C-Teams sind antippbar
# ===========================================================================

class TestTeamsAntippbar:
    def test_heimteam_auf_der_anzeigetafel_tappable(self):
        script = _script()
        start = script.index("function mcBuildScoreboard(data)")
        block = script[start:script.index("function mcInfoRow", start)]
        assert "mcMakeTappable(homeSide, () => mcOpenTeam(data.home.id))" in block

    def test_auswaertsteam_auf_der_anzeigetafel_tappable(self):
        script = _script()
        start = script.index("function mcBuildScoreboard(data)")
        block = script[start:script.index("function mcInfoRow", start)]
        assert "mcMakeTappable(awaySide, () => mcOpenTeam(data.away.id))" in block

    def test_aufstellungskopf_tappable(self):
        script = _script()
        start = script.index("function mcBuildLineupBlock(lineup, teamName, eventIndex)")
        block = script[start:script.index("function mcRenderLineups", start)]
        assert "mcMakeTappable(teamHeading, () => mcOpenTeam(lineup.team_id))" in block

    def test_stabile_team_id_ohne_namenssuche(self):
        script = _script()
        start = script.index("function mcOpenTeam(teamId)")
        block = script[start:script.index("function mcBuildScoreboard", start)]
        assert "teamId" in block
        assert "team.name" not in block
        assert "data.home.name" not in block

    def test_liga_und_saison_kommen_aus_dem_geladenen_payload(self):
        script = _script()
        start = script.index("function mcOpenTeam(teamId)")
        block = script[start:script.index("function mcBuildScoreboard", start)]
        assert "mcState.data" in block
        assert "league.id" in block
        assert "league.season" in block

    def test_kein_button_element_fuer_verschachtelte_bloecke(self):
        """Dieselbe Begruendung wie bei antippbaren Spielern (Block D1)."""
        script = _script()
        start = script.index("function mcBuildScoreboard(data)")
        block = script[start:script.index("function mcInfoRow", start)]
        assert "make(\"button\"" not in block


# ===========================================================================
# C) Navigation
# ===========================================================================

class TestNavigation:
    def test_oeffnen_wechselt_den_bereich_nicht(self):
        script = _script()
        start = script.index("function tdOpen(teamId, options)")
        block = script[start:script.index("function tdClose()", start)]
        assert "setActiveArea(" not in block

    def test_schliessen_wechselt_den_bereich_nicht(self):
        script = _script()
        start = script.index("function tdClose()")
        block = script[start:script.index("if (tdBackBtn)", start)]
        assert "setActiveArea(" not in block

    def test_match_center_funktionen_werden_nicht_aufgerufen(self):
        """
        Kein mcClose()/mcStopAutoRefresh()/mcOpen() innerhalb von
        tdOpen()/tdClose() - der Match-Center-Zustand bleibt unberuehrt.
        """
        script = _script()
        open_start = script.index("function tdOpen(teamId, options)")
        open_block = script[open_start:script.index("function tdClose()", open_start)]
        close_start = script.index("function tdClose()")
        close_block = script[close_start:script.index("if (tdBackBtn)", close_start)]

        for verboten in ("mcClose(", "mcStopAutoRefresh(", "mcOpen("):
            assert verboten not in open_block
            assert verboten not in close_block

    def test_zurueck_knopf_vorhanden(self):
        html = _read("templates", "index.html")
        assert 'id="td-back"' in html

        script = _script()
        assert 'tdBackBtn.addEventListener("click", tdClose)' in script

    def test_zurueck_beschriftung_kontextsensitiv(self):
        script = _script()
        start = script.index("function tdOpen(teamId, options)")
        block = script[start:script.index("function tdClose()", start)]
        assert 'tdState.returnTo === "live"' in block
        assert 't("team.backToMatch")' in block

    def test_spielerprofil_aus_team_kennzeichnet_rueckweg_zum_team(self):
        """
        Ein Kaderspieler antippen setzt returnTo: "team" - der
        Zurueck-Knopf des Spielerprofils zeigt dann "Zurück zum Team".
        """
        script = _script()
        start = script.index('returnTo: "team"')
        # Kommt aus tdBuildSquadEntry()
        block = script[max(0, start - 400):start + 50]
        assert "pdOpen(player.id" in block

        pd_open_start = script.index("function pdOpen(playerId, options)")
        pd_open_block = script[pd_open_start:script.index("function pdClose()", pd_open_start)]
        assert '"team"' in pd_open_block
        assert 't("profile.backToTeam")' in pd_open_block

    def test_kein_fuenfter_oder_sechster_hauptbereich(self):
        html = _read("templates", "index.html")
        start = html.index('id="team-detail-view"')
        tag_line = html[start - 60:start + 40]
        assert "app-area" not in tag_line

        script = _script()
        start = script.index("const AREAS = [")
        line = script[start:script.index("]", start)]
        assert line.count('"') == 8   # weiterhin genau vier Bereiche

    def test_request_token_gegen_race_conditions(self):
        script = _script()
        start = script.index("async function tdLoad(options)")
        block = script[start:script.index("function tdOpen", start)]
        assert "++tdState.requestToken" in block
        assert "token !== tdState.requestToken" in block


# ===========================================================================
# D) Kader -> D1 Player Detail
# ===========================================================================

class TestKaderIntegration:
    def test_kaderspieler_oeffnet_bestehendes_spielerprofil(self):
        script = _script()
        start = script.index("function tdBuildSquadEntry(player)")
        block = script[start:script.index("function tdBuildSquadSection", start)]
        assert "pdOpen(player.id" in block

    def test_kaderspieler_traegt_player_id_im_dom(self):
        script = _script()
        start = script.index("function tdBuildSquadEntry(player)")
        block = script[start:script.index("function tdBuildSquadSection", start)]
        assert "entry.dataset.playerId = player.id" in block

    def test_kein_request_pro_kaderspieler_beim_rendern(self):
        """
        Das Rendern des Kaders selbst darf keinen einzigen Player-Request
        ausloesen - erst der tatsaechliche Tap oeffnet ein Profil.
        """
        script = _script()
        start = script.index("function tdBuildSquadSection(squad)")
        block = script[start:script.index("function tdBuildCoachSection", start)]
        assert "fetchJson" not in block
        assert "/api/player-profile" not in block

    def test_keine_zweite_player_detail_implementierung(self):
        """
        team_detail.py und das Teamprofil-JS duerfen keine eigene
        Spielerprofil-Logik enthalten - alles laeuft ueber das
        bestehende pdOpen/pdLoad/pdRenderAll aus Block D1.
        """
        script = _script()
        start = script.index("/* ---------- 16g. TEAMPROFIL")
        end = script.index("/* ---------- 17. START")
        block = script[start:end]

        assert "function pdOpen" not in block
        assert "function pdLoad" not in block
        # "/api/player-profile" darf als Textnennung vorkommen (siehe
        # tdBuildSquadEntry()-Doku), aber kein eigener fetchJson-Aufruf
        # dorthin - der Kader ruft ausschliesslich pdOpen() auf.
        assert 'fetchJson(`/api/player-profile' not in block

    def test_kadereintrag_zeigt_nummer_und_position(self):
        script = _script()
        start = script.index("function tdBuildSquadEntry(player)")
        block = script[start:script.index("function tdBuildSquadSection", start)]
        assert "player.number" in block
        assert "player.position" in block


# ===========================================================================
# E) Mobile / Markup
# ===========================================================================

class TestMobileUndMarkup:
    def test_kachel_raster_wiederverwendet(self):
        """Dieselbe Optik wie die Kernwerte im Spielerprofil (D1)."""
        script = _script()
        start = script.index("function tdBuildStandingsTiles(standings)")
        block = script[start:script.index("function tdBuildFormRow", start)]
        assert 'make("div", "pd-core-grid")' in block
        assert 'make("div", "pd-core-tile")' in block

    def test_avatar_im_kader_wiederverwendet(self):
        script = _script()
        start = script.index("function tdBuildSquadEntry(player)")
        block = script[start:script.index("function tdBuildSquadSection", start)]
        assert "mcBuildAvatar(" in block

        css = _read("static", "style.css")
        assert ".td-squad-entry .mc-pp-avatar" in css

    def test_lange_namen_brechen_nicht_das_layout(self):
        css = _read("static", "style.css")
        start = css.index(".td-name {")
        block = css[start:start + 200]
        assert "overflow-wrap: anywhere" in block

        start = css.index(".td-fixture-opponent {")
        block = css[start:start + 250]
        assert "text-overflow: ellipsis" in block

    def test_mobile_breakpoints_vorhanden(self):
        from tests.conftest import css_media_contains
        css = _read("static", "style.css")
        assert css_media_contains(css, "@media (max-width: 768px)", ".td-logo")
        assert css_media_contains(css, "@media (max-width: 420px)", ".td-squad-grid")

    def test_keine_erfundenen_ergebnisse_bei_kommenden_spielen(self):
        script = _script()
        start = script.index("function tdBuildFixtureRow(fixture, kind)")
        block = script[start:script.index("function tdBuildFixtureSection", start)]
        assert 'kind === "recent"' in block
        assert "KEIN erfundenes Ergebnis" in block

    def test_leere_kategorien_neutral_behandelt(self):
        script = _script()
        for fn in ("tdBuildStandingsSection", "tdBuildSquadSection", "tdBuildCoachSection"):
            start = script.index(f"function {fn}(")
            block = script[start:start + 600]
            assert "mcBuildNote(" in block


# ===========================================================================
# F) Bestehende LIVE-A-D1-Vertraege bleiben unveraendert
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

    def test_vier_hauptbereiche_unveraendert(self):
        html = _read("templates", "index.html")
        assert html.count('class="area-btn') == 4
        assert html.count('class="bottom-nav-btn') == 4

    def test_spielerprofil_back_button_weiterhin_vorhanden(self):
        html = _read("templates", "index.html")
        assert 'id="pd-back"' in html

    def test_vergleichen_button_weiterhin_vorhanden(self):
        html = _read("templates", "index.html")
        assert 'id="pd-compare-btn"' in html

        script = _script()
        assert 'pdCompareBtn.addEventListener("click", pdCompare)' in script

    def test_grid_engine_weiterhin_formationsfrei(self):
        source = _read("src", "api", "live_api.py")
        for formation in ("4-3-3", "4-2-3-1", "3-5-2"):
            assert f'"{formation}"' not in source
