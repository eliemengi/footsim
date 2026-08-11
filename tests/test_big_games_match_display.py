"""
Tests fuer die Tor-/Vorlagen-Anzeige je Spiel in "Ausgewertete Spiele"
(Big Games, Mikro-Fix nach F1.1).

Hintergrund: build_big_games_profile() hat die echte Vorlagenzahl je
Spiel schon immer aus den Einzelspielerwerten uebernommen und im
Vergleichsergebnis mitgeliefert (match.assists) - nur die Oberflaeche hat
sie nie angezeigt. Es wird hier also NICHTS neu beschafft oder
hergeleitet, nur sichtbar gemacht.

Abgedeckt:
  A) Backend: assists kommen unveraendert aus den echten Einzelspielerwerten
  B) Frontend: Renderregeln fuer ⚽/👟 je Kombination
  C) Bestehende Darstellung (Bewertung, Layout) bleibt unangetastet
"""

import json

import pytest

from src.data import big_games_loader as bgl
from src.data import uefa_coefficients as uc


# ===========================================================================
# A) Backend: reale Vorlagenzahl, keine Herleitung
# ===========================================================================

HOME_TEAM = 33
OPPONENT = 40  # Rang 2 im Testsnapshot


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path, monkeypatch):
    from src.utils import disk_cache
    monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path / "cache"))

    coeff_dir = tmp_path / "coeff"
    coeff_dir.mkdir()
    (coeff_dir / "uefa_coefficients_2021_22.json").write_text(json.dumps({
        "season": "2021/22",
        "status": "complete",
        "clubs": [
            {"rank": 1, "total_coefficient": 138.0, "apisports_team_id": 157},
            {"rank": 2, "total_coefficient": 134.0, "apisports_team_id": OPPONENT},
        ],
    }), encoding="utf-8")

    monkeypatch.setattr(uc, "COEFFICIENT_DIR", str(coeff_dir))
    uc.clear_cache()
    yield
    uc.clear_cache()


def make_fixture(fixture_id=1):
    return {
        "fixture": {"id": fixture_id, "date": "2021-10-24T15:00:00+00:00",
                    "status": {"short": "FT"}},
        "league": {"id": 39, "name": "Premier League", "round": "Regular Season - 10"},
        "teams": {"home": {"id": HOME_TEAM, "name": "Eigenes Team"},
                  "away": {"id": OPPONENT, "name": "Gegner"}},
    }


def make_player_stats(goals, assists, rating="7.5", minutes=90):
    return [{"team": {"id": HOME_TEAM},
             "players": [{"player": {"id": 874},
                          "statistics": [{"games": {"minutes": minutes, "rating": rating,
                                                    "position": "F"},
                                          "goals": {"total": goals, "assists": assists}}]}]}]


class TestBackendAssists:
    def _profile(self, monkeypatch, goals, assists):
        monkeypatch.setattr(bgl, "get_player_season_raw",
                            lambda pid, season: {"player": {"id": pid, "name": "Test"},
                                                 "statistics": [{"team": {"id": HOME_TEAM},
                                                                 "league": {"id": 39,
                                                                           "name": "Premier League"}}]})
        monkeypatch.setattr(bgl.apisports_api, "get_team_season_fixtures",
                            lambda t, l, s: [make_fixture()])
        monkeypatch.setattr(bgl.apisports_api, "get_fixture_players",
                            lambda f: make_player_stats(goals, assists))

        return bgl.build_big_games_profile(874, 2021, 2021)

    def test_vorlage_kommt_unveraendert_aus_den_einzelspielerwerten(self, monkeypatch):
        """
        Die zentrale Zusicherung: der Wert im Vergleichsergebnis ist exakt
        der Wert aus goals.assists der echten Einzelspielerwerte - keine
        Herleitung aus Toren, kein zusaetzlicher Request.
        """
        profile = self._profile(monkeypatch, goals=1, assists=2)
        assert profile["matches"][0]["assists"] == 2
        assert profile["matches"][0]["goals"] == 1

    def test_fehlende_vorlage_bleibt_none_nicht_null(self, monkeypatch):
        profile = self._profile(monkeypatch, goals=1, assists=None)
        assert profile["matches"][0]["assists"] is None

    def test_null_vorlagen_bleibt_null(self, monkeypatch):
        """Eine echte 0 (kein Assist) ist etwas anderes als 'nicht erhoben'."""
        profile = self._profile(monkeypatch, goals=0, assists=0)
        assert profile["matches"][0]["assists"] == 0
        assert profile["matches"][0]["goals"] == 0

    def test_kein_zusaetzlicher_request_fuer_vorlagen(self, monkeypatch):
        """
        Vorlagen stammen aus derselben get_fixture_players()-Antwort, die
        ohnehin fuer Tore/Minuten/Bewertung geholt wird - es gibt keinen
        eigenen Vorlagen-Request.
        """
        calls = []
        monkeypatch.setattr(bgl, "get_player_season_raw",
                            lambda pid, season: {"player": {"id": pid},
                                                 "statistics": [{"team": {"id": HOME_TEAM},
                                                                 "league": {"id": 39,
                                                                           "name": "Premier League"}}]})
        monkeypatch.setattr(bgl.apisports_api, "get_team_season_fixtures",
                            lambda t, l, s: [make_fixture()])

        def fake_players(fixture_id):
            calls.append(fixture_id)
            return make_player_stats(1, 1)

        monkeypatch.setattr(bgl.apisports_api, "get_fixture_players", fake_players)
        bgl.build_big_games_profile(874, 2021, 2021)
        assert calls == [1]


# ===========================================================================
# B) Frontend: Renderregeln
# ===========================================================================

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _script():
    with open(os.path.join(PROJECT_ROOT, "static", "script.js"), encoding="utf-8") as f:
        return f.read()


def _match_stats_block():
    script = _script()
    start = script.index("function bgBuildMatchList(player)")
    end = script.index("function bgBuildPlayerColumn", start)
    return script[start:end]


class TestFrontendContract:
    def test_torsymbol_bleibt_unveraendert(self):
        block = _match_stats_block()
        assert 'if (match.goals) stats.appendChild(make("span", "bg-match-goals", `${match.goals}⚽`));' in block

    def test_vorlagensymbol_vorhanden(self):
        block = _match_stats_block()
        assert "match.assists" in block
        assert "👟" in block

    def test_vorlage_nur_bei_echtem_wert_gerendert(self):
        """0 und null duerfen kein Symbol erzeugen (JS: 0 ist falsy)."""
        block = _match_stats_block()
        assert 'if (match.assists) stats.appendChild(' in block

    def test_kein_label_text(self):
        """Keine Beschriftung wie 'Tore:' oder 'Assists:' - nur die Icons."""
        block = _match_stats_block()
        assert "Tore:" not in block
        assert "Assists:" not in block
        assert "Vorlagen:" not in block

    def test_bewertung_bleibt_danach_und_unveraendert(self):
        block = _match_stats_block()
        goals_pos = block.index('"bg-match-goals", `${match.goals}')
        assists_pos = block.index('"bg-match-goals", `${match.assists}')
        rating_pos = block.index("bg-match-rating")
        assert goals_pos < assists_pos < rating_pos
        assert 'Number(match.rating).toFixed(1)' in block

    def test_keine_neue_zeile_kein_neuer_stats_container(self):
        """Tor- und Vorlagensymbol haengen im bestehenden .bg-match-stats-
        Container - keine zusaetzliche Zeile, keine groessere Karte."""
        block = _match_stats_block()
        assert block.count('make("div", "bg-match-stats")') == 1

    def test_keine_css_aenderung_noetig_gap_bereits_vorhanden(self):
        with open(os.path.join(PROJECT_ROOT, "static", "style.css"), encoding="utf-8") as f:
            css = f.read()
        start = css.index(".bg-match-stats {")
        block = css[start:css.index("}", start)]
        assert "gap:" in block
