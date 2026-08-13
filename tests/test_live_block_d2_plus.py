"""
Tests fuer Block LIVE D2+ (Club Facts im Teamprofil, Erfolge im
Spielerprofil).

Abgedeckt:
  A) Team Detail: Club-Facts-Kacheln, Stadionbild
  B) Player Detail: Erfolge-Abschnitt
  C) Mobile/Markup-Vertraege
  D) Bestehende D1/D2-Vertraege regressieren nicht

Backend-Normalisierung wird in tests/test_team_detail.py
(TestTeamInfo, Club-Facts-Tests) und tests/test_player_trophies.py
abgedeckt. Diese Datei prueft ausschliesslich die Frontend-Verdrahtung -
dasselbe Muster wie tests/test_live_block_d2.py.
"""

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(PROJECT_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _script():
    return _read("static", "script.js")


# ===========================================================================
# A) Team Detail: Club Facts
# ===========================================================================

class TestClubFacts:
    def test_facts_grid_existiert(self):
        script = _script()
        assert "function tdBuildFactsGrid(team)" in script

    def test_facts_grid_wiederverwendet_pd_core_grid(self):
        """Dieselbe Kachel-Optik wie die Kernwerte im Spielerprofil - kein neues Muster."""
        script = _script()
        start = script.index("function tdBuildFactsGrid(team)")
        block = script[start:script.index("function tdBuildStandingsTiles", start)]
        assert 'make("div", "pd-core-grid")' in block
        assert 'make("div", "pd-core-tile")' in block

    def test_nur_vorhandene_werte_werden_gezeigt(self):
        script = _script()
        start = script.index("function tdBuildFactsGrid(team)")
        block = script[start:script.index("function tdBuildStandingsTiles", start)]
        assert "if (team.founded)" in block
        assert "if (team.venue_name)" in block

    def test_leere_facts_liefern_kein_leeres_element(self):
        script = _script()
        start = script.index("function tdBuildFactsGrid(team)")
        block = script[start:script.index("function tdBuildStandingsTiles", start)]
        assert "if (!tiles.length) return null;" in block

    def test_adresse_nur_als_tooltip_nicht_als_eigene_kachel(self):
        script = _script()
        start = script.index("function tdBuildFactsGrid(team)")
        block = script[start:script.index("function tdBuildStandingsTiles", start)]
        assert "team.venue_address" in block
        assert "valueNode.title = title" in block

    def test_kapazitaet_wird_formatiert(self):
        script = _script()
        assert "function tdFormatCapacity(capacity)" in script
        assert "toLocaleString(activeIntlLocale())" in script

    def test_kein_erfundener_wert_bei_fehlender_kapazitaet(self):
        script = _script()
        start = script.index("function tdFormatCapacity(capacity)")
        block = script[start:start + 300]
        assert "capacity === null" in block
        assert "return null" in block

    def test_facts_im_render_verdrahtet(self):
        script = _script()
        start = script.index("function tdRenderAll(data)")
        block = script[start:script.index("async function tdLoad", start)]
        assert "tdBuildFactsGrid(data.team)" in block


class TestStadionbild:
    def test_venue_image_funktion_existiert(self):
        script = _script()
        assert "function tdBuildVenueImage(url)" in script

    def test_fehlendes_bild_liefert_nichts(self):
        script = _script()
        start = script.index("function tdBuildVenueImage(url)")
        block = script[start:start + 200]
        assert "if (!url) return null;" in block

    def test_kaputtes_bild_entfernt_sich_selbst_statt_leere_flaeche(self):
        """
        Anders als crest() (visibility:hidden): bei einem Stadionbild
        dieser Groesse waere eine leere, aber weiterhin eingenommene
        Flaeche deutlich sichtbar kaputt - deshalb komplettes Entfernen.
        """
        script = _script()
        start = script.index("function tdBuildVenueImage(url)")
        block = script[start:script.index("function tdFormatCapacity", start)]
        assert "img.onerror = () => { wrap.remove(); };" in block

    def test_lazy_loading(self):
        script = _script()
        start = script.index("function tdBuildVenueImage(url)")
        block = script[start:script.index("function tdFormatCapacity", start)]
        assert 'img.loading = "lazy";' in block

    def test_im_render_verdrahtet_vor_den_facts(self):
        script = _script()
        start = script.index("function tdRenderAll(data)")
        block = script[start:script.index("async function tdLoad", start)]

        image_pos = block.index("tdBuildVenueImage(")
        facts_pos = block.index("tdBuildFactsGrid(")
        assert image_pos < facts_pos

    def test_kein_hero_keine_absolute_positionierung(self):
        css = _read("static", "style.css")
        start = css.index(".td-venue-image {")
        block = css[start:start + 200]
        assert "position: absolute" not in block
        assert "position: fixed" not in block
        assert "height: 140px" in block


# ===========================================================================
# B) Player Detail: Erfolge
# ===========================================================================

class TestErfolge:
    def test_abschnitt_existiert(self):
        script = _script()
        assert "function pdBuildTrophiesSection(trophies)" in script
        assert "function pdBuildTrophyRow(trophy)" in script

    def test_ohne_titel_entfaellt_der_abschnitt(self):
        script = _script()
        start = script.index("function pdBuildTrophiesSection(trophies)")
        block = script[start:start + 300]
        assert "if (!trophies || !trophies.length) return null;" in block

    def test_land_als_tooltip(self):
        script = _script()
        start = script.index("function pdBuildTrophyRow(trophy)")
        block = script[start:script.index("function pdBuildTrophiesSection", start)]
        assert "label.title = trophy.country" in block

    def test_anzahl_wird_angezeigt(self):
        script = _script()
        start = script.index("function pdBuildTrophyRow(trophy)")
        block = script[start:script.index("function pdBuildTrophiesSection", start)]
        assert "trophy.count" in block

    def test_erfolge_unabhaengig_vom_scope_immer_angehaengt(self):
        """
        Trophies sind saisonunabhaengig - werden ausserhalb des
        hasAnyCoreValue-Zweigs angehaengt, der nur die scope-abhaengigen
        Saisonwerte betrifft.
        """
        script = _script()
        start = script.index("function pdRenderAll(data)")
        block = script[start:script.index("async function pdLoad", start)]

        trophies_pos = block.index("pdBuildTrophiesSection(")
        show_pos = block.index("show(pdStatsBox);")
        assert trophies_pos < show_pos

    def test_reiht_sich_in_bestehendes_mc_info_muster_ein(self):
        script = _script()
        start = script.index("function pdBuildTrophyRow(trophy)")
        block = script[start:script.index("function pdBuildTrophiesSection", start)]
        assert 'make("div", "mc-info-row")' in block


# ===========================================================================
# C) Mobile / Markup
# ===========================================================================

class TestMobileUndMarkup:
    def test_mobile_breakpoints_fuer_venue_image(self):
        from tests.conftest import css_media_contains
        css = _read("static", "style.css")
        assert css_media_contains(css, "@media (max-width: 768px)", ".td-venue-image")
        assert css_media_contains(css, "@media (max-width: 420px)", ".td-venue-image")

    def test_keine_horizontale_scrollgefahr(self):
        css = _read("static", "style.css")
        start = css.index(".td-venue-image {")
        block = css[start:start + 200]
        assert "width: 100%" in block

    def test_lange_wettbewerbsnamen_brechen_um(self):
        """
        mc-info-label hat kein eigenes overflow-wrap, aber die Zeile
        selbst (mc-info-row) begrenzt die Breite ueber flex/space-between -
        ein sehr langer Name wird ueber denselben Mechanismus wie die
        bestehenden mc-info-value-Zeilen behandelt (overflow-wrap: anywhere).
        """
        css = _read("static", "style.css")
        start = css.index(".mc-info-value {")
        block = css[start:start + 200]
        assert "overflow-wrap: anywhere" in block


# ===========================================================================
# D) Bestehende D1/D2-Vertraege bleiben unveraendert
# ===========================================================================

class TestKeineRegression:
    def test_team_detail_navigation_unveraendert(self):
        script = _script()
        start = script.index("function tdOpen(teamId, options)")
        block = script[start:script.index("function tdClose()", start)]
        assert "setActiveArea(" not in block
        assert "openDetailView(tdView)" in block

    def test_player_detail_navigation_unveraendert(self):
        script = _script()
        start = script.index("function pdOpen(playerId, options)")
        block = script[start:script.index("function pdClose()", start)]
        assert "setActiveArea(" not in block
        assert "openDetailView(pdView)" in block

    def test_kader_oeffnet_weiterhin_bestehendes_player_detail(self):
        script = _script()
        start = script.index("function tdBuildSquadEntry(player)")
        block = script[start:script.index("function tdBuildSquadSection", start)]
        assert "pdOpen(player.id" in block

    def test_standings_sharing_unveraendert(self):
        source = _read("src", "api", "team_detail.py")
        assert 'key=f"apisports:standings:{league_id}:{season}"' in source

    def test_vier_hauptbereiche_unveraendert(self):
        html = _read("templates", "index.html")
        assert html.count('class="area-btn') == 4
        assert html.count('class="bottom-nav-btn') == 4

    def test_kein_team_statistics_endpoint(self):
        source_api = _read("src", "api", "apisports_api.py")
        source_team = _read("src", "api", "team_detail.py")
        assert "teams/statistics" not in source_api
        assert "teams/statistics" not in source_team

    def test_kein_vereinstitel_endpoint_fuer_teams(self):
        """
        /trophies unterstuetzt laut API-Football-Dokumentation nur
        player/players/coach/coachs, nicht team - deshalb darf
        team_detail.py keinen trophies-Aufruf enthalten.
        """
        source = _read("src", "api", "team_detail.py")
        assert "trophies" not in source.lower()
