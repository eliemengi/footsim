"""
Tests fuer den zusammengefuehrten Poisson-Sampler.

Die Funktion stand vier Mal wortgleich im Projekt (league_match_sim,
season_sim, cl_match_sim, cl_season_sim). Vier Kopien sind heute kein
Fehler, aber ein Risiko: Sobald das Modell erweitert wird - etwa auf eine
bivariate Verteilung, die Heim- und Auswaertstore korreliert - muesste
die Aenderung an vier Stellen konsistent nachgezogen werden. Wird eine
vergessen, rechnen zwei Simulationspfade unterschiedlich, ohne dass ein
Test das bemerkt.

Der Beweis, dass die Zusammenfuehrung nichts veraendert hat
-----------------------------------------------------------
REFERENCE_SEQUENCES wurde aus der Implementierung VOR der
Zusammenfuehrung erzeugt, indem alle vier Kopien mit identischem Seed
laufen gelassen und ihre Ausgaben verglichen wurden - sie waren
deckungsgleich. Diese Folgen sind hier als Literale festgeschrieben.
Weicht der gemeinsame Sampler davon ab, hat sich das Verhalten der
Simulation geaendert.
"""

import random

import pytest

from src.predict.poisson import poisson


# Erzeugt mit random.Random(42), 20 Ziehungen je Lambda, aus dem Stand
# VOR der Zusammenfuehrung. Nicht anpassen, ohne den Grund zu belegen.
REFERENCE_SEQUENCES = {
    0.15: (0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    1.35: (1, 1, 3, 1, 0, 1, 0, 2, 2, 2, 0, 2, 0, 4, 2, 3, 1, 0, 1, 0),
    2.8: (1, 2, 2, 1, 2, 3, 2, 3, 2, 2, 6, 4, 2, 1, 3, 1, 4, 3, 4, 0),
    4.5: (2, 4, 2, 2, 5, 5, 1, 11, 2, 2, 3, 5, 3, 7, 5, 5, 5, 3, 4, 5),
}


@pytest.mark.parametrize("lmbda,expected", sorted(REFERENCE_SEQUENCES.items()))
def test_behaviour_is_unchanged(lmbda, expected):
    """Der eigentliche Beweis: identische Folge wie vor dem Refactoring."""
    rng = random.Random(42)
    produced = tuple(poisson(lmbda, rng) for _ in range(20))

    assert produced == expected


def test_all_simulation_paths_use_the_same_function():
    """
    Nach der Zusammenfuehrung darf es keine zweite Implementierung mehr
    geben - sonst waere genau nichts gewonnen.
    """
    from src.predict import cl_match_sim, cl_season_sim, league_match_sim, season_sim

    functions = {
        league_match_sim._poisson,
        season_sim._poisson,
        cl_match_sim._poisson,
        cl_season_sim._poisson,
    }

    assert functions == {poisson}


def test_no_local_copy_remains():
    """AST-Schutz gegen ein spaeteres Wiedereinschleichen einer Kopie."""
    import ast
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    offenders = []

    for name in ("league_match_sim", "season_sim", "cl_match_sim", "cl_season_sim"):
        path = os.path.join(root, "src", "predict", f"{name}.py")
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_poisson":
                offenders.append(name)

    assert not offenders, f"Lokale Poisson-Kopie wieder aufgetaucht: {offenders}"


# ---------------------------------------------------------------------------
# Eigenschaften der Verteilung
# ---------------------------------------------------------------------------

def test_never_returns_negative():
    rng = random.Random(7)
    assert all(poisson(0.15, rng) >= 0 for _ in range(500))


def test_mean_approximates_lambda():
    """
    Grundeigenschaft der Poisson-Verteilung: Der Erwartungswert ist
    lambda. Faengt einen fehlerhaften Sampler ab, den feste Referenzfolgen
    allein nicht auffallen liessen.
    """
    for lmbda in (0.5, 1.5, 3.0):
        rng = random.Random(1234)
        draws = [poisson(lmbda, rng) for _ in range(20000)]
        mean = sum(draws) / len(draws)

        assert mean == pytest.approx(lmbda, rel=0.05)


def test_seeded_runs_are_reproducible():
    """Voraussetzung fuer use_seed in der Simulation."""
    first = [poisson(1.4, random.Random(99)) for _ in range(5)]
    second = [poisson(1.4, random.Random(99)) for _ in range(5)]

    assert first == second


def test_different_seeds_differ():
    a = tuple(poisson(2.0, random.Random(1)) for _ in range(30))
    b = tuple(poisson(2.0, random.Random(2)) for _ in range(30))

    assert a != b


# ---------------------------------------------------------------------------
# Die entfernte Doppeldefinition
# ---------------------------------------------------------------------------

def test_competition_teams_defined_only_once():
    """
    get_competition_teams stand zweimal in league_api.py. Python liess
    stillschweigend die zweite gewinnen; die erste war toter Code mit
    abweichendem Cache-Key und fehlendem country-Feld.
    """
    import ast
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "src", "api", "league_api.py")

    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())

    definitions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_competition_teams"
    ]

    assert len(definitions) == 1


def test_surviving_competition_teams_keeps_country():
    """
    Die erhaltene Version liefert ein Superset der entfernten: dieselben
    Felder plus country/country_code. Ohne die laesst sich ein CL-Verein
    keiner nationalen Liga zuordnen.
    """
    import inspect

    from src.api.league_api import get_competition_teams

    source = inspect.getsource(get_competition_teams)

    assert '"country"' in source
    assert '"country_code"' in source
    assert 'key=f"competition_teams:' in source
