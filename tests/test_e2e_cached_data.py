"""
End-to-End-Tests mit den ECHTEN, im Disk-Cache liegenden Saisondaten
(La Liga und Ligue 1, Saison 2026/27). Komplett offline.

Diese Tests belegen mit realen API-Daten:
  * 380 bzw. 306 Fixtures im vollstaendigen Spielplan
  * 38 bzw. 34 Partien je Team, gespielte und offene zusammen
  * vollstaendige Monte-Carlo-Laeufe mit allen Invarianten
  * der urspruengliche Bug (nur 10 Fixtures) ist behoben
"""

import copy
import json
import os
from collections import defaultdict

import pytest

from src.predict import fixture_plan
from src.predict.season_sim import simulate_season

#: Ein eingefrorener, vollstaendiger Ligue-1-Spielplan (V2-C19).
#:
#: WARUM DIESE DATEI EXISTIERT
#: Der Test darunter prueft eine Aussage ueber den SPIELPLAN: 18
#: Vereine, 306 Paarungen, 34 Partien je Verein. Er las dafuer den
#: Plattencache der laufenden Saison - eine Datei, die sich mit jedem
#: Spieltag aendert. Solange die Saison noch nicht begonnen hatte,
#: stimmte "34 OFFENE Partien je Team" zufaellig mit "34 Partien je
#: Team" ueberein. Mit dem dritten Spieltag stimmte es nicht mehr, und
#: der Test wurde rot, ohne dass sich an der Software etwas geaendert
#: haette.
#:
#: Eine Aussage ueber den Spielplan darf nicht vom Spielstand
#: abhaengen. Deshalb liegt der Spielplan jetzt eingefroren daneben.
FROZEN_FL1 = os.path.join(os.path.dirname(__file__), "fixtures",
                          "fl1_frozen_season_306.json")


def _frozen_fl1(finished_matchdays=0):
    """
    Der eingefrorene Spielplan, wahlweise mit gespielten Spieltagen.

    finished_matchdays=0 ist der Zustand vor dem ersten Anpfiff,
    groessere Werte spielen die ersten n Spieltage mit festen
    Ergebnissen durch. Beide Zustaende stammen aus DERSELBEN Quelle;
    damit prueft der Test die Einteilung in gespielt und offen und
    nicht zwei verschiedene Spielplaene.
    """
    with open(FROZEN_FL1, encoding="utf-8") as datei:
        partien = copy.deepcopy(json.load(datei)["payload"])
    for partie in partien:
        if partie["matchday"] <= finished_matchdays:
            partie["status"] = "FINISHED"
            partie["score"] = {"winner": "HOME_TEAM", "duration": "REGULAR",
                               "fullTime": {"home": 2, "away": 1},
                               "halfTime": {"home": 1, "away": 0}}
    return partien


def plan_from_raw(raw_matches, api_code, expected_team_count):
    original = fixture_plan.load_full_season_matches
    fixture_plan.load_full_season_matches = lambda code, season=None: (raw_matches, 2026)
    try:
        return fixture_plan.build_season_plan(
            api_code, season=2026, expected_team_count=expected_team_count
        )
    finally:
        fixture_plan.load_full_season_matches = original


def test_real_pd_plan_has_380_fixtures(cached_pd_matches):
    plan = plan_from_raw(cached_pd_matches, "PD", 20)

    assert plan["coverage"]["teams"] == 20
    assert plan["coverage"]["fixtures_received"] == 380
    assert len(plan["remaining_matches"]) + len(plan["finished_matches"]) == 380
    assert plan["coverage"]["ok"] is True

    per_team = defaultdict(int)
    for match in plan["remaining_matches"]:
        per_team[match["home_id"]] += 1
        per_team[match["away_id"]] += 1
    for match in plan["finished_matches"]:
        per_team[match["home_id"]] += 1
        per_team[match["away_id"]] += 1

    assert len(per_team) == 20
    assert all(count == 38 for count in per_team.values())


def _je_team(plan):
    """Gespielte, offene und Gesamtpartien je Verein."""
    gespielt, offen = defaultdict(int), defaultdict(int)
    for match in plan["finished_matches"]:
        gespielt[match["home_id"]] += 1
        gespielt[match["away_id"]] += 1
    for match in plan["remaining_matches"]:
        offen[match["home_id"]] += 1
        offen[match["away_id"]] += 1
    teams = set(gespielt) | set(offen)
    return {tid: (gespielt[tid], offen[tid], gespielt[tid] + offen[tid])
            for tid in teams}


def test_real_fl1_plan_has_306_fixtures():
    """
    Der Spielplan vor dem ersten Anpfiff: 18 Vereine, 306 Paarungen,
    34 offene Partien je Verein.

    Quelle ist der eingefrorene Spielplan, nicht der Plattencache.
    """
    plan = plan_from_raw(_frozen_fl1(), "FL1", 18)

    assert plan["coverage"]["teams"] == 18
    assert plan["coverage"]["fixtures_received"] == 306
    assert plan["coverage"]["ok"] is True
    assert len(plan["finished_matches"]) == 0
    assert len(plan["remaining_matches"]) == 306

    je_team = _je_team(plan)
    assert len(je_team) == 18
    assert all(offen == 34 for _g, offen, _s in je_team.values())
    assert all(summe == 34 for _g, _o, summe in je_team.values())


def test_fl1_plan_bleibt_vollstaendig_wenn_spieltage_gespielt_sind():
    """
    Derselbe Spielplan mit drei gespielten Spieltagen.

    Die Gesamtzahl je Verein bleibt 34, die Aufteilung verschiebt sich.
    Genau diese Unterscheidung fehlte vorher: Der alte Test verlangte
    34 OFFENE Partien und setzte damit voraus, dass die Saison nie
    beginnt.
    """
    plan = plan_from_raw(_frozen_fl1(finished_matchdays=3), "FL1", 18)

    assert plan["coverage"]["teams"] == 18
    assert plan["coverage"]["fixtures_received"] == 306
    assert plan["coverage"]["ok"] is True
    assert len(plan["finished_matches"]) == 27
    assert len(plan["remaining_matches"]) == 279

    je_team = _je_team(plan)
    assert len(je_team) == 18
    assert all(gespielt == 3 for gespielt, _o, _s in je_team.values())
    assert all(offen == 31 for _g, offen, _s in je_team.values())
    assert all(summe == 34 for _g, _o, summe in je_team.values())


def test_fl1_plan_zaehlt_jede_paarung_genau_einmal():
    """
    306 gerichtete Paarungen, 153 Begegnungen, jede zweimal mit
    getauschtem Heimrecht. Ohne diese Pruefung koennte ein Plan die
    richtige ANZAHL haben und trotzdem falsch sein.
    """
    plan = plan_from_raw(_frozen_fl1(), "FL1", 18)
    gerichtet = [(m["home_id"], m["away_id"])
                 for m in plan["remaining_matches"]]

    assert len(gerichtet) == 306
    assert len(set(gerichtet)) == 306
    begegnungen = {tuple(sorted(paar)) for paar in gerichtet}
    assert len(begegnungen) == 153

    heimspiele = defaultdict(int)
    for heim, _gast in gerichtet:
        heimspiele[heim] += 1
    assert all(anzahl == 17 for anzahl in heimspiele.values())


def test_echter_fl1_cache_bleibt_in_sich_stimmig(cached_fl1_matches):
    """
    Der echte Plattencache, geprueft auf das, was unabhaengig vom
    Spielstand gilt.

    Bewusst OHNE die Annahme "Saison ungespielt": Dieser Test soll die
    Anbieterdaten gegen die Planlogik halten und nicht gegen den
    Kalender. Was er prueft, muss an jedem Spieltag der Saison gelten.
    """
    plan = plan_from_raw(cached_fl1_matches, "FL1", 18)

    assert plan["coverage"]["teams"] == 18
    assert plan["coverage"]["fixtures_received"] == 306
    assert plan["coverage"]["ok"] is True

    je_team = _je_team(plan)
    assert len(je_team) == 18
    assert all(summe == 34 for _g, _o, summe in je_team.values())
    assert (len(plan["finished_matches"])
            + len(plan["remaining_matches"])) == 306


def test_real_pd_regression_not_only_matchday_one(cached_pd_matches):
    """
    Direkter Regressionstest gegen den Original-Bug: Vorher landeten
    exakt 10 Fixtures (ein Spieltag) in der Simulation.
    """
    plan = plan_from_raw(cached_pd_matches, "PD", 20)
    assert len(plan["remaining_matches"]) != 10
    assert len(plan["remaining_matches"]) == 380


def test_real_pd_full_season_simulation(cached_pd_matches, cached_pd_standings):
    """Vollstaendiger Monte-Carlo-Lauf auf echten La-Liga-Daten."""
    plan = plan_from_raw(cached_pd_matches, "PD", 20)
    table = cached_pd_standings["tables"]["TOTAL"]

    result = simulate_season(
        competition_code="pd",
        standings_table=table,
        remaining_matches=plan["remaining_matches"],
        simulations=300,
        current_matches=plan["finished_matches"],
        seed=1,
        season=2026,
        fixture_coverage=plan["coverage"],
    )

    assert result["games_remaining"] == 380
    assert len(result["entries"]) == 20

    # Raenge lueckenlos 1..20
    assert [e["rank"] for e in result["entries"]] == list(range(1, 21))

    # Meisterwahrscheinlichkeit summiert sich auf 100
    total = sum(e["champion_pct"] for e in result["entries"])
    assert abs(total - 100.0) < 1.5

    # Jedes Team: 38 offene Spiele, erwartete Punkte im gueltigen Bereich
    for entry in result["entries"]:
        assert entry["games_remaining"] == 38
        assert 0 <= entry["expected_points"] <= 114
        assert entry["expected_position"] is not None

    # Kein Fixture verschwunden
    report = result["fixture_report"]
    assert report["fixtures_simulated_per_run"] == 380
    assert report["fixtures_rejected"] == 0
    assert report["coverage_ok"] is True


def test_real_pd_barcelona_and_real_madrid_are_top(cached_pd_matches,
                                                   cached_pd_standings):
    """
    Plausibilitaet nach dem Fix: Barcelona (2x Meister in Folge) und
    Real Madrid gehoeren nach dem historischen Modell in die Spitzengruppe,
    nicht auf Rang 5 oder tiefer. Kein Hardcode - nur eine Warnschwelle.
    """
    plan = plan_from_raw(cached_pd_matches, "PD", 20)
    table = cached_pd_standings["tables"]["TOTAL"]

    result = simulate_season(
        competition_code="pd",
        standings_table=table,
        remaining_matches=plan["remaining_matches"],
        simulations=400,
        current_matches=plan["finished_matches"],
        seed=3,
        season=2026,
        fixture_coverage=plan["coverage"],
    )

    ranks = {
        (e.get("team_full_name") or e["team_name"]): e["rank"]
        for e in result["entries"]
    }
    barcelona = next((r for name, r in ranks.items()
                      if "Barcelona" in name or "Barça" in name), None)
    real = next((r for name, r in ranks.items() if "Real Madrid" in name), None)

    assert barcelona is not None and barcelona <= 3, f"Barcelona auf Rang {barcelona}"
    assert real is not None and real <= 4, f"Real Madrid auf Rang {real}"
