"""
Regressionstests fuer die Champions-League-Ligaphasen-Simulation.

Abgedeckt:
  A) Fixture-Plan: nur LEAGUE_STAGE, keine Duplikate, Coverage
  B) full_resimulation: reale Paarungen bleiben, reale Ergebnisse NICHT
  C) simulate_remaining: reale Ergebnisse bleiben fix
  D) Tiebreaker, jede Stufe einzeln
  E) deterministischer letzter Fallback
  F) Empty State ohne LEAGUE_STAGE-Fixtures
  G) Domestic-Regression
  H) bestehender CL-Flow bleibt unberuehrt
"""

import os

import pytest


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APISPORTS_KEY", "test-key")
    monkeypatch.setenv("FOOTBALL_DATA_KEY", "test-key")
    import app as app_module
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Testdaten-Helfer
# ---------------------------------------------------------------------------

def _raw_match(match_id, home_id, away_id, stage="LEAGUE_STAGE",
               status="SCHEDULED", home_goals=None, away_goals=None, matchday=1):
    """Ein Match im Format, das get_all_matches() liefert."""
    return {
        "id": match_id,
        "stage": stage,
        "group": None,
        "matchday": matchday,
        "utc_date": "2025-09-16T19:00:00Z",
        "status": status,
        "home_id": home_id,
        "home_team": f"Team {home_id}",
        "home_crest": None,
        "away_id": away_id,
        "away_team": f"Team {away_id}",
        "away_crest": None,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "home_goals_regular": home_goals,
        "away_goals_regular": away_goals,
        "penalty_home": None,
        "penalty_away": None,
        "winner": None,
    }


def _round_robin_raw(n_teams=4, finished=True):
    """
    Kleine, vollstaendige Ligaphase: n Teams, jeder gegen jeden einmal.
    Damit hat jedes Team n-1 Partien - eine in sich stimmige Struktur,
    an der die datengetriebene Coverage-Pruefung greifen kann.
    """
    matches = []
    match_id = 1
    for home in range(1, n_teams + 1):
        for away in range(home + 1, n_teams + 1):
            matches.append(_raw_match(
                match_id, home, away,
                status="FINISHED" if finished else "SCHEDULED",
                home_goals=2 if finished else None,
                away_goals=1 if finished else None,
            ))
            match_id += 1
    return matches


def _patch_source(monkeypatch, raw_matches, season=2025):
    """Haengt get_all_matches/resolve_season im Fixture-Plan-Modul um."""
    import src.predict.cl_fixture_plan as plan_module
    monkeypatch.setattr(plan_module, "get_all_matches", lambda *a, **k: raw_matches)
    monkeypatch.setattr(plan_module, "resolve_season", lambda api_code, s=None: season)


NEUTRAL_RATINGS = {
    "attack_home": 1.0, "attack_away": 1.0,
    "defence_home": 1.0, "defence_away": 1.0,
    "matches_used": 10,
}


def _fake_strengths(team_ids):
    return {
        "domestic_by_id": {tid: dict(NEUTRAL_RATINGS, team_id=tid) for tid in team_ids},
        "cl_current_by_id": {},
        "league_avg": {"home_goals": 1.5, "away_goals": 1.2,
                       "total_goals": 2.7, "matches": 100},
    }


# ===========================================================================
# A) Fixture-Plan
# ===========================================================================

class TestClFixturePlan:
    def test_nur_league_stage(self, monkeypatch):
        from src.predict.cl_fixture_plan import build_cl_league_phase_plan

        raw = _round_robin_raw(4) + [
            _raw_match(90, 1, 2, stage="PLAYOFFS", status="FINISHED",
                       home_goals=1, away_goals=0),
            _raw_match(91, 3, 4, stage="LAST_16", status="FINISHED",
                       home_goals=2, away_goals=2),
            _raw_match(92, 1, 3, stage="FINAL", status="SCHEDULED"),
        ]
        _patch_source(monkeypatch, raw)

        plan = build_cl_league_phase_plan(season=2025)

        assert len(plan["fixtures"]) == 6          # 4 Teams, jeder gegen jeden
        assert plan["coverage"]["other_stage_skipped"] == 3
        assert all(f["match_id"] not in (90, 91, 92) for f in plan["fixtures"])

    def test_duplikate_werden_verworfen(self, monkeypatch):
        from src.predict.cl_fixture_plan import build_cl_league_phase_plan

        raw = _round_robin_raw(4)
        raw.append(_raw_match(1, 1, 2, status="FINISHED", home_goals=9, away_goals=9))
        _patch_source(monkeypatch, raw)

        plan = build_cl_league_phase_plan(season=2025)

        assert len(plan["fixtures"]) == 6
        reasons = [i["reason"] for i in plan["invalid_matches"]]
        assert "duplicate_fixture_id" in reasons

    def test_fehlende_team_ids_werden_verworfen(self, monkeypatch):
        from src.predict.cl_fixture_plan import build_cl_league_phase_plan

        raw = _round_robin_raw(4)
        raw.append(_raw_match(50, None, 2))
        _patch_source(monkeypatch, raw)

        plan = build_cl_league_phase_plan(season=2025)
        assert "team_id_missing" in [i["reason"] for i in plan["invalid_matches"]]

    def test_coverage_ok_bei_vollstaendigem_plan(self, monkeypatch):
        from src.predict.cl_fixture_plan import build_cl_league_phase_plan

        _patch_source(monkeypatch, _round_robin_raw(4))
        plan = build_cl_league_phase_plan(season=2025)

        cov = plan["coverage"]
        assert cov["has_fixtures"] is True
        assert cov["ok"] is True
        assert cov["teams"] == 4
        assert cov["matches_per_team"] == 3
        assert cov["fixtures_total"] == 6

    def test_coverage_nicht_ok_bei_ungleicher_spielzahl(self, monkeypatch):
        from src.predict.cl_fixture_plan import build_cl_league_phase_plan

        raw = _round_robin_raw(4)
        raw.append(_raw_match(60, 1, 2, status="SCHEDULED"))  # 1 und 2 haben nun 4
        _patch_source(monkeypatch, raw)

        plan = build_cl_league_phase_plan(season=2025)
        assert plan["coverage"]["per_team_ok"] is False
        assert plan["coverage"]["ok"] is False

    def test_expected_matches_per_team_erkennt_teilauslosung(self, monkeypatch):
        """
        In sich stimmig (jedes Team 3 Partien), aber das CL-Format
        verlangt 8. Muss als unvollstaendig gemeldet werden.
        """
        from src.predict.cl_fixture_plan import build_cl_league_phase_plan

        _patch_source(monkeypatch, _round_robin_raw(4))
        plan = build_cl_league_phase_plan(season=2025, expected_matches_per_team=8)

        assert plan["coverage"]["per_team_ok"] is True
        assert plan["coverage"]["ok"] is False
        assert any("unvollstaendig" in p for p in plan["coverage"]["problems"])

    def test_finished_und_remaining_trennung(self, monkeypatch):
        from src.predict.cl_fixture_plan import build_cl_league_phase_plan

        raw = _round_robin_raw(4, finished=False)
        raw[0] = _raw_match(1, 1, 2, status="FINISHED", home_goals=3, away_goals=1)
        _patch_source(monkeypatch, raw)

        plan = build_cl_league_phase_plan(season=2025)

        assert len(plan["finished_matches"]) == 1
        assert len(plan["remaining_matches"]) == 5
        assert plan["finished_matches"][0]["home_goals"] == 3
        assert plan["remaining_matches"][0]["home_goals"] is None

    def test_finished_ohne_ergebnis_ist_invalid(self, monkeypatch):
        from src.predict.cl_fixture_plan import build_cl_league_phase_plan

        raw = [_raw_match(1, 1, 2, status="FINISHED", home_goals=None, away_goals=None)]
        _patch_source(monkeypatch, raw)

        plan = build_cl_league_phase_plan(season=2025)
        assert plan["fixtures"] == []
        assert "finished_without_score" in [i["reason"] for i in plan["invalid_matches"]]

    def test_leerer_plan_hat_has_fixtures_false(self, monkeypatch):
        from src.predict.cl_fixture_plan import build_cl_league_phase_plan

        _patch_source(monkeypatch, [])
        plan = build_cl_league_phase_plan(season=2026)

        assert plan["fixtures"] == []
        assert plan["coverage"]["has_fixtures"] is False
        assert plan["coverage"]["ok"] is False

    def test_nur_ko_fixtures_gilt_als_keine_ligaphase(self, monkeypatch):
        """2026/27 vor der Auslosung: keine LEAGUE_STAGE-Daten -> Empty State."""
        from src.predict.cl_fixture_plan import build_cl_league_phase_plan

        _patch_source(monkeypatch, [
            _raw_match(1, 1, 2, stage="PLAYOFFS"),
            _raw_match(2, 3, 4, stage="LAST_16"),
        ])
        plan = build_cl_league_phase_plan(season=2026)

        assert plan["coverage"]["has_fixtures"] is False
        assert plan["coverage"]["other_stage_skipped"] == 2


# ===========================================================================
# B) + C) Simulationsmodi
# ===========================================================================

def _plan_from(monkeypatch, raw, season=2025):
    from src.predict.cl_fixture_plan import build_cl_league_phase_plan
    _patch_source(monkeypatch, raw, season=season)
    return build_cl_league_phase_plan(season=season)


class TestSimulationsModi:
    def test_auto_modus_abgeschlossene_saison_ist_full(self, monkeypatch):
        from src.predict.cl_season_sim import resolve_mode, MODE_FULL_RESIMULATION

        plan = _plan_from(monkeypatch, _round_robin_raw(4, finished=True))
        assert resolve_mode(plan) == MODE_FULL_RESIMULATION

    def test_auto_modus_laufende_saison_ist_remaining(self, monkeypatch):
        from src.predict.cl_season_sim import resolve_mode, MODE_SIMULATE_REMAINING

        raw = _round_robin_raw(4, finished=True)
        raw[0] = _raw_match(1, 1, 2, status="SCHEDULED")
        plan = _plan_from(monkeypatch, raw)

        assert resolve_mode(plan) == MODE_SIMULATE_REMAINING

    def test_expliziter_modus_gewinnt(self, monkeypatch):
        from src.predict.cl_season_sim import (
            resolve_mode, MODE_FULL_RESIMULATION, MODE_SIMULATE_REMAINING,
        )

        raw = _round_robin_raw(4, finished=True)
        raw[0] = _raw_match(1, 1, 2, status="SCHEDULED")
        plan = _plan_from(monkeypatch, raw)

        assert resolve_mode(plan, MODE_FULL_RESIMULATION) == MODE_FULL_RESIMULATION
        assert resolve_mode(plan, MODE_SIMULATE_REMAINING) == MODE_SIMULATE_REMAINING

    def test_full_resimulation_verwirft_reale_ergebnisse(self, monkeypatch):
        """
        Kernanforderung fuer die abgeschlossene Saison: die realen
        Paarungen bleiben, die realen Ergebnisse gehen NICHT als fixe
        Punkte in die Tabelle ein.
        """
        from src.predict.cl_season_sim import (
            simulate_cl_league_phase, MODE_FULL_RESIMULATION,
        )

        plan = _plan_from(monkeypatch, _round_robin_raw(4, finished=True))

        result = simulate_cl_league_phase(
            plan=plan, mode=MODE_FULL_RESIMULATION, simulations=200,
            season=2025, seed=1, strengths=_fake_strengths([1, 2, 3, 4]),
        )

        assert result["mode"] == MODE_FULL_RESIMULATION
        # Alle Partien werden neu gewuerfelt, keine wird uebernommen.
        assert result["fixtures_simulated"] == 6
        assert result["fixtures_fixed"] == 0
        # Kein Team startet mit realen Punkten.
        for entry in result["entries"]:
            assert entry["current_points"] == 0
            assert entry["current_played"] == 0

    def test_full_resimulation_behaelt_reale_paarungen(self, monkeypatch):
        from src.predict.cl_season_sim import (
            build_opponent_map, MODE_FULL_RESIMULATION, simulate_cl_league_phase,
        )

        plan = _plan_from(monkeypatch, _round_robin_raw(4, finished=True))
        opponents = build_opponent_map(plan["fixtures"])

        # Jedes Team behaelt exakt seine realen Gegner.
        assert sorted(opponents[1]) == [2, 3, 4]
        assert sorted(opponents[4]) == [1, 2, 3]

        result = simulate_cl_league_phase(
            plan=plan, mode=MODE_FULL_RESIMULATION, simulations=100,
            season=2025, seed=1, strengths=_fake_strengths([1, 2, 3, 4]),
        )
        assert result["teams_total"] == 4
        assert result["fixtures_total"] == 6

    def test_simulate_remaining_haelt_reale_ergebnisse_fix(self, monkeypatch):
        from src.predict.cl_season_sim import (
            simulate_cl_league_phase, MODE_SIMULATE_REMAINING,
        )

        # Team 1 gewinnt real 5:0 gegen 2, alle anderen Partien offen.
        raw = _round_robin_raw(4, finished=False)
        raw[0] = _raw_match(1, 1, 2, status="FINISHED", home_goals=5, away_goals=0)
        plan = _plan_from(monkeypatch, raw)

        result = simulate_cl_league_phase(
            plan=plan, mode=MODE_SIMULATE_REMAINING, simulations=200,
            season=2025, seed=1, strengths=_fake_strengths([1, 2, 3, 4]),
        )

        assert result["mode"] == MODE_SIMULATE_REMAINING
        assert result["fixtures_simulated"] == 5
        assert result["fixtures_fixed"] == 1

        by_name = {e["team_name"]: e for e in result["entries"]}
        assert by_name["Team 1"]["current_points"] == 3
        assert by_name["Team 1"]["current_played"] == 1
        assert by_name["Team 2"]["current_points"] == 0
        assert by_name["Team 2"]["current_played"] == 1
        # Team 3 hat real noch nicht gespielt.
        assert by_name["Team 3"]["current_played"] == 0

    def test_simulate_remaining_ohne_offene_spiele_wuerfelt_nichts(self, monkeypatch):
        from src.predict.cl_season_sim import (
            simulate_cl_league_phase, MODE_SIMULATE_REMAINING,
        )

        plan = _plan_from(monkeypatch, _round_robin_raw(4, finished=True))
        result = simulate_cl_league_phase(
            plan=plan, mode=MODE_SIMULATE_REMAINING, simulations=50,
            season=2025, seed=1, strengths=_fake_strengths([1, 2, 3, 4]),
        )

        assert result["fixtures_simulated"] == 0
        # Reale Endtabelle: jedes Heimteam hat 2:1 gewonnen.
        by_name = {e["team_name"]: e for e in result["entries"]}
        assert by_name["Team 1"]["current_points"] == 9   # 3 Heimsiege

    def test_ergebnis_enthaelt_zonen_und_wahrscheinlichkeiten(self, monkeypatch):
        from src.predict.cl_season_sim import simulate_cl_league_phase

        plan = _plan_from(monkeypatch, _round_robin_raw(4, finished=True))
        result = simulate_cl_league_phase(
            plan=plan, simulations=200, season=2025, seed=3,
            strengths=_fake_strengths([1, 2, 3, 4]),
        )

        assert result["zones"] == {"direct_last": 8, "playoff_last": 24}

        for entry in result["entries"]:
            assert 0.0 <= entry["top_seed_pct"] <= 100.0
            assert entry["direct_pct"] == 100.0   # nur 4 Teams, alle in 1-8
            assert entry["eliminated_pct"] == 0.0
            assert entry["expected_points"] >= 0
            assert entry["position_probs"]

        ranks = [e["rank"] for e in result["entries"]]
        assert ranks == [1, 2, 3, 4]

    def test_seed_macht_lauf_reproduzierbar(self, monkeypatch):
        from src.predict.cl_season_sim import simulate_cl_league_phase

        plan = _plan_from(monkeypatch, _round_robin_raw(4, finished=True))
        kwargs = dict(plan=plan, simulations=100, season=2025,
                      strengths=_fake_strengths([1, 2, 3, 4]))

        a = simulate_cl_league_phase(seed=42, **kwargs)
        b = simulate_cl_league_phase(seed=42, **kwargs)

        assert [e["expected_points"] for e in a["entries"]] == \
               [e["expected_points"] for e in b["entries"]]


# ===========================================================================
# D) Tiebreaker, jede Stufe einzeln
# ===========================================================================

def _row(pts=0, gd=0, gf=0, away_goals=0, wins=0, away_wins=0,
         played=0, draws=0, losses=0, ga=0):
    return {
        "played": played, "wins": wins, "draws": draws, "losses": losses,
        "gf": gf, "ga": ga, "gd": gd, "pts": pts,
        "away_goals": away_goals, "away_wins": away_wins,
    }


def _rank(table, opponents=None):
    """Sortiert eine handgebaute Tabelle ueber die echte Ranking-Funktion."""
    from src.predict.cl_season_sim import _rank_table

    keys = sorted(table.keys())
    opponents = opponents or {k: [] for k in keys}
    fallback_keys = {k: str(k) for k in keys}
    return _rank_table(keys, table, opponents, fallback_keys)


class TestTiebreaker:
    def test_punkte_entscheiden_zuerst(self):
        table = {
            1: _row(pts=3, gd=99, gf=99, away_goals=99, wins=9, away_wins=9),
            2: _row(pts=6, gd=0, gf=0),
        }
        ordered, _ = _rank(table)
        assert ordered == [2, 1]

    def test_tordifferenz_bei_punktgleichheit(self):
        table = {
            1: _row(pts=6, gd=1, gf=99, away_goals=99, wins=9, away_wins=9),
            2: _row(pts=6, gd=5, gf=0),
        }
        ordered, _ = _rank(table)
        assert ordered == [2, 1]

    def test_erzielte_tore_bei_gleicher_tordifferenz(self):
        table = {
            1: _row(pts=6, gd=3, gf=5, away_goals=99, wins=9, away_wins=9),
            2: _row(pts=6, gd=3, gf=9, away_goals=0),
        }
        ordered, _ = _rank(table)
        assert ordered == [2, 1]

    def test_auswaertstore_bei_gleichen_toren(self):
        table = {
            1: _row(pts=6, gd=3, gf=9, away_goals=2, wins=9, away_wins=9),
            2: _row(pts=6, gd=3, gf=9, away_goals=6, wins=0, away_wins=0),
        }
        ordered, _ = _rank(table)
        assert ordered == [2, 1]

    def test_siege_bei_gleichen_auswaertstoren(self):
        table = {
            1: _row(pts=9, gd=3, gf=9, away_goals=4, wins=2, away_wins=9),
            2: _row(pts=9, gd=3, gf=9, away_goals=4, wins=3, away_wins=0),
        }
        ordered, _ = _rank(table)
        assert ordered == [2, 1]

    def test_auswaertssiege_bei_gleichen_siegen(self):
        table = {
            1: _row(pts=9, gd=3, gf=9, away_goals=4, wins=3, away_wins=1),
            2: _row(pts=9, gd=3, gf=9, away_goals=4, wins=3, away_wins=2),
        }
        ordered, _ = _rank(table)
        assert ordered == [2, 1]

    def test_gegnerpunkte_bei_sonst_gleichstand(self):
        identical = dict(pts=9, gd=3, gf=9, away_goals=4, wins=3, away_wins=2)
        table = {
            1: _row(**identical),
            2: _row(**identical),
            # Gegner: 3 ist schwach, 4 ist stark.
            3: _row(pts=0),
            4: _row(pts=12),
        }
        # Team 1 spielte gegen den schwachen 3, Team 2 gegen den starken 4.
        opponents = {1: [3], 2: [4], 3: [1], 4: [2]}
        ordered, _ = _rank(table, opponents)
        assert ordered.index(2) < ordered.index(1)

    def test_gegner_tordifferenz_bei_gleichen_gegnerpunkten(self):
        identical = dict(pts=9, gd=3, gf=9, away_goals=4, wins=3, away_wins=2)
        table = {
            1: _row(**identical),
            2: _row(**identical),
            3: _row(pts=6, gd=1, gf=5),
            4: _row(pts=6, gd=8, gf=5),
        }
        opponents = {1: [3], 2: [4], 3: [1], 4: [2]}
        ordered, _ = _rank(table, opponents)
        assert ordered.index(2) < ordered.index(1)

    def test_gegner_tore_bei_gleicher_gegner_tordifferenz(self):
        identical = dict(pts=9, gd=3, gf=9, away_goals=4, wins=3, away_wins=2)
        table = {
            1: _row(**identical),
            2: _row(**identical),
            3: _row(pts=6, gd=2, gf=4),
            4: _row(pts=6, gd=2, gf=11),
        }
        opponents = {1: [3], 2: [4], 3: [1], 4: [2]}
        ordered, _ = _rank(table, opponents)
        assert ordered.index(2) < ordered.index(1)

    def test_reihenfolge_der_kriterien_ist_dokumentiert(self):
        from src.predict.cl_season_sim import TIEBREAK_CRITERIA

        assert TIEBREAK_CRITERIA == (
            "points",
            "goal_difference",
            "goals_for",
            "away_goals",
            "wins",
            "away_wins",
            "opponents_points",
            "opponents_goal_difference",
            "opponents_goals_for",
        )


# ===========================================================================
# E) Deterministischer letzter Fallback
# ===========================================================================

class TestDeterministischerFallback:
    def test_vollstaendiger_gleichstand_nutzt_fallback(self):
        identical = dict(pts=9, gd=3, gf=9, away_goals=4, wins=3, away_wins=2)
        table = {7: _row(**identical), 3: _row(**identical)}

        ordered, fallback_used = _rank(table)

        assert fallback_used is True
        # Stabil nach Team-ID, nicht zufaellig.
        assert ordered == [3, 7]

    def test_kein_fallback_wenn_kriterien_trennen(self):
        table = {
            1: _row(pts=9, gd=3, gf=9),
            2: _row(pts=6, gd=1, gf=4),
        }
        _, fallback_used = _rank(table)
        assert fallback_used is False

    def test_fallback_ist_reproduzierbar(self):
        identical = dict(pts=9, gd=3, gf=9, away_goals=4, wins=3, away_wins=2)
        table = {7: _row(**identical), 3: _row(**identical), 5: _row(**identical)}

        first, _ = _rank(table)
        second, _ = _rank(table)
        assert first == second == [3, 5, 7]

    def test_fehlende_kriterien_werden_benannt_statt_geraten(self):
        from src.predict.cl_season_sim import TIEBREAK_MISSING

        assert "disciplinary_points" in TIEBREAK_MISSING
        assert "uefa_club_coefficient" in TIEBREAK_MISSING

    def test_ergebnis_meldet_fallback_transparent(self, monkeypatch):
        from src.predict.cl_season_sim import simulate_cl_league_phase

        plan = _plan_from(monkeypatch, _round_robin_raw(4, finished=True))
        result = simulate_cl_league_phase(
            plan=plan, simulations=100, season=2025, seed=1,
            strengths=_fake_strengths([1, 2, 3, 4]),
        )

        assert "fallback_used" in result["tiebreak"]
        assert "fallback_runs" in result["tiebreak"]
        assert result["tiebreak"]["missing_criteria"]


# ===========================================================================
# F) Route: Empty State, Coverage, Erfolg
# ===========================================================================

class TestClSeasonSimRoute:
    def test_empty_state_ohne_ligaphasen_fixtures(self, client, monkeypatch):
        import app as app_module

        monkeypatch.setattr(app_module, "build_cl_league_phase_plan", lambda **k: {
            "season": 2026, "fixtures": [], "finished_matches": [],
            "remaining_matches": [], "invalid_matches": [], "teams": {},
            "team_ids": set(), "played_matchdays": 0,
            "coverage": {"has_fixtures": False, "ok": False, "problems": []},
        })

        response = client.get("/api/cl-season-sim?season=2026")

        # Erwartbarer Zustand -> 200, kein Fehler.
        assert response.status_code == 200
        data = response.get_json()
        assert data["empty_state"] is True
        assert data["entries"] == []
        assert "2026/27" in data["empty_state_message"]

    def test_unvollstaendiger_plan_ist_echter_fehler(self, client, monkeypatch):
        import app as app_module

        monkeypatch.setattr(app_module, "build_cl_league_phase_plan", lambda **k: {
            "season": 2025, "fixtures": [{"x": 1}], "finished_matches": [],
            "remaining_matches": [], "invalid_matches": [], "teams": {},
            "team_ids": set(), "played_matchdays": 0,
            "coverage": {"has_fixtures": True, "ok": False,
                         "problems": ["Ligaphase unvollstaendig"]},
        })

        response = client.get("/api/cl-season-sim?season=2025")
        assert response.status_code == 503
        assert "fixture_coverage" in response.get_json()

    def test_erfolgreiche_simulation(self, client, monkeypatch):
        import app as app_module

        captured = {}

        def fake_sim(plan, mode, simulations, season):
            captured.update(mode=mode, simulations=simulations, season=season)
            return {"entries": [], "mode": "full_resimulation", "simulations": simulations}

        monkeypatch.setattr(app_module, "build_cl_league_phase_plan", lambda **k: {
            "season": 2025, "fixtures": [], "finished_matches": [],
            "remaining_matches": [], "invalid_matches": [], "teams": {},
            "team_ids": set(), "played_matchdays": 0,
            "coverage": {"has_fixtures": True, "ok": True, "problems": []},
        })
        monkeypatch.setattr(app_module, "simulate_cl_league_phase", fake_sim)

        response = client.get("/api/cl-season-sim?season=2025&simulations=5000")
        assert response.status_code == 200

        data = response.get_json()
        assert data["competition"] == "Champions League"
        assert data["season"] == 2025
        assert captured["simulations"] == 5000
        assert captured["mode"] is None      # ohne Angabe entscheidet der Plan

    def test_ungueltiger_modus_gibt_400(self, client):
        response = client.get("/api/cl-season-sim?season=2025&mode=erfinde-was")
        assert response.status_code == 400

    def test_gueltiger_modus_wird_durchgereicht(self, client, monkeypatch):
        import app as app_module

        captured = {}

        def fake_sim(plan, mode, simulations, season):
            captured["mode"] = mode
            return {"entries": []}

        monkeypatch.setattr(app_module, "build_cl_league_phase_plan", lambda **k: {
            "season": 2025, "fixtures": [], "finished_matches": [],
            "remaining_matches": [], "invalid_matches": [], "teams": {},
            "team_ids": set(), "played_matchdays": 0,
            "coverage": {"has_fixtures": True, "ok": True, "problems": []},
        })
        monkeypatch.setattr(app_module, "simulate_cl_league_phase", fake_sim)

        client.get("/api/cl-season-sim?season=2025&mode=full_resimulation")
        assert captured["mode"] == "full_resimulation"

    def test_simulationsanzahl_wird_begrenzt(self, client, monkeypatch):
        import app as app_module

        captured = {}

        def fake_sim(plan, mode, simulations, season):
            captured["simulations"] = simulations
            return {"entries": []}

        monkeypatch.setattr(app_module, "build_cl_league_phase_plan", lambda **k: {
            "season": 2025, "fixtures": [], "finished_matches": [],
            "remaining_matches": [], "invalid_matches": [], "teams": {},
            "team_ids": set(), "played_matchdays": 0,
            "coverage": {"has_fixtures": True, "ok": True, "problems": []},
        })
        monkeypatch.setattr(app_module, "simulate_cl_league_phase", fake_sim)

        client.get("/api/cl-season-sim?season=2025&simulations=999999")
        assert captured["simulations"] == 50000

        client.get("/api/cl-season-sim?season=2025&simulations=1")
        assert captured["simulations"] == 1000

    def test_technischer_fehler_bleibt_fehler(self, client, monkeypatch):
        import app as app_module

        def raise_error(**kwargs):
            raise app_module.ApiUnavailable("Rate Limit erreicht", status_code=429)

        monkeypatch.setattr(app_module, "build_cl_league_phase_plan", raise_error)

        response = client.get("/api/cl-season-sim?season=2025")
        assert response.status_code == 503


# ===========================================================================
# G) Domestic-Regression
# ===========================================================================

class TestDomesticRegression:
    def test_domestic_season_sim_route_unveraendert(self, client, monkeypatch):
        import app as app_module

        captured = {}

        def fake_sim(**kwargs):
            captured.update(kwargs)
            return {"entries": [], "competition_code": "bl1"}

        monkeypatch.setattr(app_module, "get_standings", lambda api_code, season=None: {
            "season": 2025, "competition": "Bundesliga",
            "tables": {"TOTAL": [{"team_id": 5, "team_name": "Bayern"}]},
        })
        monkeypatch.setattr(app_module, "build_season_plan", lambda *a, **k: {
            "season": 2025, "finished_matches": [], "remaining_matches": [],
            "invalid_matches": [], "team_ids": set(), "played_matchdays": 0,
            "coverage": {"ok": True},
        })
        monkeypatch.setattr(app_module, "simulate_season", fake_sim)

        response = client.get("/api/season-sim?competition=bl1&season=2025")
        assert response.status_code == 200
        assert captured["competition_code"] == "bl1"

    def test_domestic_fixture_plan_nutzt_weiter_doppelrunde(self):
        """
        Die Domestic-Coverage-Formel darf durch den CL-Plan nicht
        veraendert worden sein.
        """
        from src.predict.fixture_plan import _validate_coverage

        coverage = _validate_coverage(
            team_ids={1, 2, 3},
            finished=[], remaining=[], invalid=[],
            per_team_finished={}, per_team_remaining={},
        )
        # 3 Teams -> Doppelrunde erwartet 3*2 = 6 Partien
        assert coverage["expected_total"] == 6
        assert coverage["expected_per_team"] == 4

    def test_domestic_season_sim_zonen_unveraendert(self):
        from src.predict.season_sim import ZONE_CONFIGS

        assert ZONE_CONFIGS["bl1"]["cl"] == 4
        assert ZONE_CONFIGS["pl"]["relegation"] == [18, 19, 20]

    def test_cl_sim_nutzt_eigene_module(self):
        """CL und Domestic bleiben getrennte Codepfade."""
        import src.predict.season_sim as domestic
        import src.predict.cl_season_sim as cl

        assert not hasattr(domestic, "simulate_cl_league_phase")
        assert not hasattr(cl, "ZONE_CONFIGS")


# ===========================================================================
# H) Bestehender CL-Flow bleibt unberuehrt
# ===========================================================================

def _read(*parts):
    with open(os.path.join(PROJECT_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class TestBestehenderClFlow:
    def test_bestehende_cl_routen_existieren_weiter(self, client):
        import app as app_module

        rules = {str(rule) for rule in app_module.app.url_map.iter_rules()}
        for route in ("/api/standings", "/api/scorers", "/api/matches",
                      "/api/cl-stages", "/api/cl-knockout", "/api/simulate",
                      "/api/season-sim", "/api/cl-season-sim"):
            assert route in rules

    def test_ligasimulation_tab_nur_in_der_ligaphase(self):
        src = _read("static", "script.js")
        start = src.find("function showTabsFor")
        assert start > -1
        block = src[start:start + 1800]

        # In der Ligaphase sichtbar, in der K.-o.-Phase und bei Domestic nicht.
        assert "show(clSeasonBtn)" in block
        assert block.count("hide(clSeasonBtn)") == 3

    def test_tab_und_panel_im_html(self):
        src = _read("templates", "index.html")
        assert 'data-tab="cl-season"' in src
        assert 'id="tab-cl-season"' in src
        assert 'id="cl-season-sim-table"' in src

    def test_frontend_sendet_explizite_saison(self):
        src = _read("static", "script.js")
        start = src.find("async function runClSeasonSim")
        assert start > -1
        block = src[start:start + 1200]
        assert "withExplicitSeason(" in block
        assert "/api/cl-season-sim" in block

    def test_frontend_behandelt_empty_state_nicht_als_fehler(self):
        src = _read("static", "script.js")
        start = src.find("async function runClSeasonSim")
        block = src[start:start + 1600]
        assert "data.empty_state" in block
        assert "empty_state_message" in block

    def test_keine_neuen_css_klassen_erfunden(self):
        """Die CL-Ligasimulation nutzt ausschliesslich vorhandenes Styling."""
        css = _read("static", "style.css")
        script = _read("static", "script.js")

        start = script.find("function renderClSeasonTable")
        block = script[start:script.find("function clResolutionMarker", start)]

        for cls in ("season-row", "season-row-left", "season-row-pos",
                    "season-crest", "season-team-name", "season-team-sub",
                    "season-row-right", "pct-chip", "zone-cl", "zone-el",
                    "zone-rel"):
            assert cls in block, f"{cls} nicht im Render-Block"
            assert cls in css, f"{cls} fehlt im vorhandenen CSS"

    def test_ucl_tabellenzonen_unveraendert(self):
        """Der frueher gebaute Tabellenfix darf nicht angefasst worden sein."""
        script = _read("static", "script.js")
        start = script.find("function positionClass")
        block = script[start:start + 800]

        assert 'competitionType === "cl"' in block
        assert "position <= 8" in block
        assert "position <= 24" in block
