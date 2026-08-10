"""
Regressionstests fuer Block 1 (Navigation + Vergleichssystem).

Abgedeckt:
  A) Hauptnavigation hat noch genau drei Bereiche (Simulation, Vergleiche,
     Spieler) -- in Desktop- und Bottom-Navigation identisch.
  B) Ligavergleich und Transfervergleich sind keine eigenen Hauptbereiche
     mehr, sondern teilen sich den Bereich "compare" ueber einen
     internen Umschalter (.compare-section-switch).
  C) Alle bestehenden Bedienelemente von Liga- und Transfervergleich
     bleiben im Markup vollstaendig erhalten.
  D) script.js kennt die neuen Bereiche/Untermodi und den alten
     "transfers"-Hauptbereich nicht mehr.

Reine Markup-/Quelltext-Tests (kein Browser, kein DOM), analog zu den
bestehenden Tests in test_player_cl_scope.py.
"""

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(PROJECT_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class TestHauptnavigation:
    def test_genau_drei_hauptbereiche_desktop(self):
        html = _read("templates", "index.html")
        assert html.count('class="area-btn') == 3

    def test_genau_drei_hauptbereiche_mobil(self):
        html = _read("templates", "index.html")
        assert html.count('class="bottom-nav-btn') == 3

    def test_vergleiche_ersetzt_ligavergleich_und_transfers(self):
        html = _read("templates", "index.html")
        # Ein "Vergleiche"-Knopf pro Navigation (Desktop-Button + Bottom-Nav-Span).
        assert '<button type="button" class="area-btn" data-area="compare">Vergleiche</button>' in html
        assert "<span>Vergleiche</span>" in html
        # Die frueheren eigenstaendigen Hauptbereichs-Knoepfe gibt es nicht mehr.
        assert '<button type="button" class="area-btn" data-area="compare">Ligavergleich</button>' not in html
        assert '<button type="button" class="area-btn" data-area="transfers">Transfervergleich</button>' not in html
        assert "<span>Ligavergleich</span>" not in html
        assert "<span>Transfers</span>" not in html

    def test_kein_eigener_transfers_hauptbereich_mehr(self):
        html = _read("templates", "index.html")
        assert 'data-area="transfers"' not in html

    def test_verbleibende_bereiche_sind_simulation_compare_players(self):
        html = _read("templates", "index.html")
        for area in ("simulation", "compare", "players"):
            assert f'data-area="{area}"' in html

    def test_spieler_bleibt_eigener_bereich(self):
        html = _read("templates", "index.html")
        assert '<button type="button" class="area-btn" data-area="players">Spielervergleich</button>' in html
        assert "<span>Spieler</span>" in html


class TestVergleicheUntermodus:
    def test_compare_section_switch_vorhanden(self):
        html = _read("templates", "index.html")
        assert 'class="compare-section-switch"' in html
        assert html.count('class="compare-section-btn') == 2

    def test_beide_untermodi_haben_data_csection(self):
        html = _read("templates", "index.html")
        assert 'data-csection="league"' in html
        assert 'data-csection="transfer"' in html

    def test_liga_untermodus_ist_default_aktiv(self):
        html = _read("templates", "index.html")
        idx = html.index('data-csection="league" aria-current="page"')
        assert idx > -1

    def test_transfer_untermodus_startet_versteckt(self):
        html = _read("templates", "index.html")
        assert 'compare-wrap compare-area-section hidden" id="compare-section-transfer"' in html

    def test_nur_ein_top_level_app_area_fuer_compare(self):
        html = _read("templates", "index.html")
        assert html.count('id="mode-compare"') == 1
        assert 'id="mode-transfers"' not in html


class TestBestehendeFunktionenBleibenErhalten:
    def test_ligavergleich_bedienelemente_vorhanden(self):
        html = _read("templates", "index.html")
        for marker in (
            'id="compare-league-list"',
            'id="compare-btn"',
            'data-cmode="domestic"',
            'data-cmode="cup"',
            'id="phase-section"',
        ):
            assert marker in html

    def test_transfervergleich_bedienelemente_vorhanden(self):
        html = _read("templates", "index.html")
        for marker in (
            'id="tc-from-a"',
            'id="tc-from-b"',
            'id="tc-target"',
            'id="tc-season"',
            'id="transfer-compare-btn"',
            'id="tc-sort"',
        ):
            assert marker in html


class TestScriptJsKenntNeueStruktur:
    def test_areas_ohne_transfers(self):
        script = _read("static", "script.js")
        start = script.index("const AREAS = [")
        line = script[start:script.index("]", start)]
        assert '"transfers"' not in line
        assert '"compare"' in line
        assert '"players"' in line

    def test_switch_compare_section_existiert(self):
        script = _read("static", "script.js")
        assert "function switchCompareSection(section)" in script
        assert 'querySelectorAll(".compare-section-btn")' in script

    def test_tc_init_wird_bei_transfer_untermodus_ausgeloest(self):
        script = _read("static", "script.js")
        start = script.index("function switchCompareSection(section)")
        block = script[start:start + 1200]
        assert "tcInitControls()" in block

    def test_season_picker_sichtbarkeit_beruecksichtigt_untermodus(self):
        script = _read("static", "script.js")
        assert "function updateSeasonPickerVisibility()" in script
        assert 'state.compareSection === "league"' in script
