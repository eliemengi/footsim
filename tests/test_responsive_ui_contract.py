"""Statische Verträge für den gezielten Responsive-Polish.

Browser-Screenshots bleiben für die endgültige Sichtprüfung nötig. Diese
Tests schützen die kleinen, bewusst bereichsspezifischen CSS-Korrekturen davor,
bei späteren Refactorings wieder in globale Regeln zurückzufallen.
"""

import os


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(PROJECT_ROOT, *parts), encoding="utf-8") as source:
        return source.read()


def _final_polish_css():
    css = _read("static", "style.css")
    marker = "FINAL POLISH: gezielte Responsive-Korrekturen"
    return css[css.index(marker):]


class TestSimulationTabs:
    def test_long_league_tabs_use_controlled_i18n_line_markup(self):
        html = _read("templates", "index.html")

        assert 'data-tab="season"' in html
        assert 'data-tab="cl-season"' in html
        assert 'data-tab="simulation"' in html
        assert 'class="league-tab-label"' in html
        assert 'class="league-tab-full-label"' in html
        assert 'data-i18n="tabs.season.line1"' in html
        assert 'data-i18n="tabs.season.line2"' in html
        assert 'data-i18n="tabs.leagueSimulation.line1"' in html
        assert 'data-i18n="tabs.leagueSimulation.line2"' in html
        assert 'data-i18n="tabs.matchSimulation.line1"' in html
        assert 'data-i18n="tabs.matchSimulation.line2"' in html

    def test_tab_fix_is_scoped_to_league_result_tabs_and_keeps_touch_size(self):
        css = _final_polish_css()

        assert "#tab-bar .tab-btn" in css
        assert "min-height: 44px" in css
        assert "#tab-bar .league-tab-label" in css
        assert "#tab-bar .league-tab-full-label" in css
        assert ".league-tab-label > span" in css
        assert "\n    .tab-bar {" not in css
        assert ".mc-tab-bar" not in css


class TestStandingsMobileContract:
    def test_mobile_standings_scroll_only_inside_its_own_container(self):
        css = _final_polish_css()

        assert "#table-content.table-content" in css
        assert "overflow-x: auto" in css
        assert "overscroll-behavior-x: contain" in css
        assert "#table-content .standings-table" in css
        assert "min-width: 520px" in css
        assert "max-width: none" in css
        assert "table-layout: auto" in css

    def test_mobile_standings_restore_every_data_column_inside_local_scroll(self):
        css = _final_polish_css()

        assert "thead th:nth-child(4)" in css
        assert "tbody td:nth-child(6)" in css
        assert "display: table-cell" in css


class TestPlayerComparisonDesktopContract:
    def test_only_player_comparison_gets_desktop_one_column_override(self):
        css = _final_polish_css()

        assert "@media (min-width: 1001px)" in css
        assert "#mode-players.compare-wrap" in css
        assert "grid-template-columns: minmax(0, 1fr)" in css
        assert "#mode-players > .pc-mode-select" in css
        assert "width: min(100%, 360px)" in css
        assert "#mode-players > #pc-radar-view" in css
        assert "\n    .compare-wrap {" not in css


class TestLiveNavigationIdentity:
    def test_live_nav_has_a_static_decorative_dot_without_changing_text_color(self):
        html = _read("templates", "index.html")
        css = _final_polish_css()

        assert 'class="bottom-nav-btn" data-area="live"' in html
        assert '.bottom-nav-btn[data-area="live"]::after' in css
        assert "background: var(--accent-red)" in css
        assert "pointer-events: none" in css
        assert "animation:" not in css
        assert '.bottom-nav-btn[data-area="live"] {' not in css
