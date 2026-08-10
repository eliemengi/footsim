"""
Regressionstests fuer die Kaderwirkung (squad impact).

Hintergrund
-----------
Dieses Feature war ueber laengere Zeit vollstaendig wirkungslos, ohne dass
es jemand bemerkt hat:

    src/features/squad_impact.py importierte TTL_APISPORTS_INJURIES aus
    src/utils/cache.py - diese Konstante existierte dort nie.

Der ImportError wurde in strength_provider.get_league_strengths von einem
weit gefassten `except Exception` aufgefangen und als "keine Kaderdaten
verfuegbar" interpretiert. Die Simulation lief weiter, nur eben ohne den
dokumentierten Verletzungsmalus.

Diese Datei sichert drei Dinge ab:

  1. Das Modul laesst sich ueberhaupt importieren, und jeder Name, den es
     aus src.utils.cache zieht, existiert dort wirklich (AST-basiert, also
     auch fuer kuenftige neue Imports wirksam).
  2. Der vollstaendige Pfad wirkt tatsaechlich bis in die Teamprofile:
     get_league_strengths -> get_squad_impact -> Attack-Multiplikator ->
     squad_data_applied=True.
  3. Ein Programmierfehler wird NICHT mehr stillschweigend maskiert,
     waehrend ein echter Datenausfall weiterhin toleriert wird.

Die numerischen Modellannahmen (REPLACEMENT_FACTOR, MAX_ATTACK_PENALTY)
werden hier bewusst nur auf Konsistenz geprueft, nicht auf "Richtigkeit".
Sie sind Baseline-Hypothesen fuer eine spaetere empirische Kalibrierung.
"""

import ast
import os

import pytest

from tests.conftest import make_historical_payload, make_standings_table


# ---------------------------------------------------------------------------
# 1. Import-Integritaet - der eigentliche Bug
# ---------------------------------------------------------------------------

def test_squad_impact_module_imports_cleanly():
    """Der konkrete Bug: das Modul war nicht importierbar."""
    import src.features.squad_impact as squad_impact

    assert hasattr(squad_impact, "get_squad_impact")
    assert hasattr(squad_impact, "apply_impact")
    assert hasattr(squad_impact, "compute_team_impact")


def test_every_cache_name_imported_by_squad_impact_exists():
    """
    Generischer Schutz gegen die BUGKLASSE, nicht nur gegen den Einzelfall.

    Liest per AST alle `from src.utils.cache import ...`-Namen aus
    squad_impact.py und prueft, dass jeder davon im Cache-Modul definiert
    ist. Damit faellt ein kuenftiger Tippfehler sofort auf, auch wenn der
    Aufrufer ihn wieder wegfangen sollte.
    """
    import src.utils.cache as cache_module

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "src", "features", "squad_impact.py",
    )
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())

    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "src.utils.cache":
            imported.extend(alias.name for alias in node.names)

    assert imported, "squad_impact.py importiert nichts aus src.utils.cache"

    missing = [name for name in imported if not hasattr(cache_module, name)]
    assert not missing, (
        f"squad_impact.py importiert nicht existierende Namen aus "
        f"src.utils.cache: {missing}"
    )


def test_ttl_constant_matches_documented_budget():
    """
    Die TTL ist keine Modellannahme, sondern eine Budgetentscheidung:
    Jeder Abruf kostet zwei API-Sports-Requests. Der Modul-Docstring
    nennt zwoelf Stunden - Code und Doku duerfen nicht auseinanderlaufen.
    """
    from src.utils.cache import TTL_APISPORTS_INJURIES

    assert TTL_APISPORTS_INJURIES == 60 * 60 * 12


# ---------------------------------------------------------------------------
# 2. Rechenkern
# ---------------------------------------------------------------------------

def test_compute_team_impact_reduces_attack_for_missing_scorer():
    """
    Ein Spieler mit 30 % Toranteil faellt aus. Bei REPLACEMENT_FACTOR 0.5
    ergibt das einen Malus von 15 %, also Modifikator 0.85.
    """
    from src.features.squad_impact import compute_team_impact

    scorers = [
        {"player_id": 1, "player_name": "Ausfall", "team_id": 10, "goals": 12},
        {"player_id": 2, "player_name": "Fit", "team_id": 10, "goals": 28},
    ]
    injuries = [{"player_id": 1, "team_id": 10, "type": "Injury", "reason": "Knie"}]

    impact = compute_team_impact(scorers, injuries)

    assert impact[10]["attack_modifier"] == pytest.approx(0.85)
    assert impact[10]["missing_goal_share"] == pytest.approx(0.30)
    assert len(impact[10]["missing_players"]) == 1


def test_attack_penalty_is_capped():
    """Der Deckel ist ein Guardrail und muss greifen, auch bei Totalausfall."""
    from src.features.squad_impact import compute_team_impact, MAX_ATTACK_PENALTY

    scorers = [{"player_id": 1, "player_name": "Alles", "team_id": 10, "goals": 40}]
    injuries = [{"player_id": 1, "team_id": 10, "type": "Injury"}]

    impact = compute_team_impact(scorers, injuries)

    assert impact[10]["attack_modifier"] >= 1.0 - MAX_ATTACK_PENALTY


def test_apply_impact_touches_attack_but_never_defence():
    """
    Bewusste fachliche Grenze: Die Datengrundlage deckt nur die Offensive
    ab. Der Defensivwert darf deshalb nicht angefasst werden.
    """
    from src.features.squad_impact import apply_impact

    profiles = {
        10: {"attack_home": 1.20, "attack_away": 1.10,
             "defence_home": 0.90, "defence_away": 0.95},
    }
    impact = {10: {"attack_modifier": 0.8, "missing_players": []}}

    apply_impact(profiles, impact)

    assert profiles[10]["attack_home"] == pytest.approx(0.96)
    assert profiles[10]["attack_away"] == pytest.approx(0.88)
    assert profiles[10]["defence_home"] == pytest.approx(0.90)
    assert profiles[10]["defence_away"] == pytest.approx(0.95)
    assert profiles[10]["squad_modifier"] == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# 3. Disk-Cache-Pfad
# ---------------------------------------------------------------------------

def test_get_squad_impact_caches_on_disk_and_spares_the_api(tmp_path, monkeypatch):
    """
    Zwei Aufrufe duerfen nur EINEN Satz API-Requests ausloesen. Das ist
    der Kern des Budgetarguments im Modul-Docstring.
    """
    import src.utils.disk_cache as disk_cache
    import src.api.apisports_api as apisports
    from src.features.squad_impact import get_squad_impact

    monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path))

    calls = {"scorers": 0, "injuries": 0}

    def fake_scorers(competition_code, season=None, limit=None):
        calls["scorers"] += 1
        return {"scorers": [
            {"player_id": 1, "player_name": "A", "team_id": 10, "goals": 10},
            {"player_id": 2, "player_name": "B", "team_id": 10, "goals": 10},
        ]}

    def fake_injuries(competition_code, season=None):
        calls["injuries"] += 1
        return {"injuries": [{"player_id": 1, "team_id": 10, "type": "Injury"}]}

    monkeypatch.setattr(apisports, "get_top_scorers", fake_scorers)
    monkeypatch.setattr(apisports, "get_injuries", fake_injuries)

    first = get_squad_impact("bl1", season=2025)
    second = get_squad_impact("bl1", season=2025)

    assert first == second
    assert first[10]["attack_modifier"] == pytest.approx(0.75)
    assert calls == {"scorers": 1, "injuries": 1}


def test_cached_result_keeps_numeric_team_ids(tmp_path, monkeypatch):
    """
    Zweiter stiller Ausfallmodus, beim Schreiben dieser Tests gefunden.

    JSON kennt nur Zeichenketten als Objektschluessel. Ohne Normalisierung
    liefert der erste (frische) Aufruf {10: ...}, jeder spaetere Aufruf aus
    dem Disk-Cache aber {"10": ...}. apply_impact() sucht mit der
    numerischen team_id und findet dann nichts mehr: Die Kaderwirkung
    verschwindet ab dem ersten Cache-Treffer, waehrend
    squad_data_applied weiterhin True meldet.
    """
    import src.utils.disk_cache as disk_cache
    import src.api.apisports_api as apisports
    from src.features.squad_impact import get_squad_impact, apply_impact

    monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(apisports, "get_top_scorers", lambda *a, **k: {"scorers": [
        {"player_id": 1, "player_name": "A", "team_id": 10, "goals": 10},
        {"player_id": 2, "player_name": "B", "team_id": 10, "goals": 10},
    ]})
    monkeypatch.setattr(apisports, "get_injuries", lambda *a, **k: {"injuries": [
        {"player_id": 1, "team_id": 10, "type": "Injury"},
    ]})

    fresh = get_squad_impact("bl1", season=2025)
    from_cache = get_squad_impact("bl1", season=2025)

    assert all(isinstance(k, int) for k in fresh)
    assert all(isinstance(k, int) for k in from_cache), (
        "Team-IDs aus dem Disk-Cache muessen numerisch bleiben"
    )

    # Entscheidend: Der Effekt muss auch aus dem Cache heraus ankommen.
    profiles = {10: {"attack_home": 1.0, "attack_away": 1.0}}
    apply_impact(profiles, from_cache)
    assert profiles[10]["squad_modifier"] == pytest.approx(0.75)
    assert profiles[10]["attack_home"] == pytest.approx(0.75)


def test_squad_impact_cache_key_separates_league_and_season(tmp_path, monkeypatch):
    """Kein Vermischen ueber Liga- oder Saisongrenzen hinweg."""
    import src.utils.disk_cache as disk_cache
    import src.api.apisports_api as apisports
    from src.features.squad_impact import get_squad_impact

    monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path))

    seen = []

    def fake_scorers(competition_code, season=None, limit=None):
        seen.append((competition_code, season))
        return {"scorers": [{"player_id": 1, "player_name": "A",
                             "team_id": 10, "goals": 10}]}

    monkeypatch.setattr(apisports, "get_top_scorers", fake_scorers)
    monkeypatch.setattr(apisports, "get_injuries", lambda *a, **k: {"injuries": []})

    get_squad_impact("bl1", season=2025)
    get_squad_impact("pl", season=2025)
    get_squad_impact("bl1", season=2024)

    assert seen == [("bl1", 2025), ("pl", 2025), ("bl1", 2024)]


# ---------------------------------------------------------------------------
# 4. Vollstaendiger Pfad bis in die Teamprofile
# ---------------------------------------------------------------------------

def _patch_history(monkeypatch, team_ids):
    """Synthetische Historie, damit der Test ohne data/historical auskommt."""
    import src.features.strength_provider as sp

    payload = make_historical_payload(team_ids, season=2025)
    monkeypatch.setattr(sp, "load_available_seasons", lambda *a, **k: [(2025, payload)])
    return payload


def test_get_league_strengths_actually_applies_squad_impact(monkeypatch):
    """
    Der eigentliche Regressionstest: Ende zu Ende muss die Kaderwirkung
    in den Profilen ankommen UND als angewandt gemeldet werden.
    """
    import src.features.strength_provider as sp
    import src.features.squad_impact as squad_impact

    team_ids = [10, 11, 12, 13]
    _patch_history(monkeypatch, team_ids)

    monkeypatch.setattr(
        squad_impact, "get_squad_impact",
        lambda *a, **k: {10: {"attack_modifier": 0.80,
                              "missing_players": [{"player_name": "Star"}]}},
    )

    standings = make_standings_table(team_ids, played=0)

    without = sp.get_league_strengths("bl1", standings, use_squad_data=False)
    with_squad = sp.get_league_strengths("bl1", standings, use_squad_data=True)

    assert without["summary"]["squad_data_applied"] is False
    assert with_squad["summary"]["squad_data_applied"] is True, (
        "Kaderwirkung wurde nicht angewandt - genau dieser stille Ausfall "
        "war der urspruengliche Bug"
    )

    base = without["profiles"][10]["attack_home"]
    reduced = with_squad["profiles"][10]["attack_home"]
    assert reduced == pytest.approx(base * 0.80)

    # Unbeteiligte Teams bleiben unveraendert.
    assert with_squad["profiles"][11]["attack_home"] == pytest.approx(
        without["profiles"][11]["attack_home"]
    )

    # Der Einfluss muss auch in der Coverage sichtbar sein.
    row = next(r for r in with_squad["coverage"] if r["team_id"] == 10)
    assert row["squad_modifier"] == pytest.approx(0.80)
    assert row["missing_players"]


# ---------------------------------------------------------------------------
# 5. Fehlerverhalten: laut bei Programmierfehlern, leise bei Datenausfall
# ---------------------------------------------------------------------------

def test_programming_error_is_not_masked(monkeypatch):
    """
    Ein ImportError im Kaderpfad darf NICHT mehr als "keine Kaderdaten"
    durchgehen. Genau diese Maskierung hat den Bug so lange verdeckt.
    """
    import builtins
    import src.features.strength_provider as sp

    team_ids = [10, 11, 12, 13]
    _patch_history(monkeypatch, team_ids)

    real_import = builtins.__import__

    def broken_import(name, *args, **kwargs):
        if name == "src.features.squad_impact":
            raise ImportError("simulierter Programmierfehler")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken_import)

    standings = make_standings_table(team_ids, played=0)

    with pytest.raises(ImportError):
        sp.get_league_strengths("bl1", standings, use_squad_data=True)


def test_data_outage_is_still_tolerated(monkeypatch):
    """
    Die gewollte Robustheit bleibt: Faellt die API aus, laeuft die
    Simulation ohne den Faktor weiter statt zu scheitern.
    """
    import src.features.strength_provider as sp
    import src.features.squad_impact as squad_impact

    team_ids = [10, 11, 12, 13]
    _patch_history(monkeypatch, team_ids)

    def exploding(*args, **kwargs):
        raise RuntimeError("API-Sports nicht erreichbar")

    monkeypatch.setattr(squad_impact, "get_squad_impact", exploding)

    standings = make_standings_table(team_ids, played=0)
    result = sp.get_league_strengths("bl1", standings, use_squad_data=True)

    assert result["summary"]["squad_data_applied"] is False
    assert result["profiles"], "Profile muessen trotzdem entstehen"
