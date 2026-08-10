"""
Ziehung von Toranzahlen aus der Poisson-Verteilung.

Diese Funktion stand vier Mal wortgleich im Projekt: in
league_match_sim, season_sim, cl_match_sim und cl_season_sim. Vier
Kopien derselben zwoelf Zeilen sind heute kein Fehler, aber ein Risiko:
Sobald das Modell erweitert wird - etwa auf eine bivariate Verteilung,
die Heim- und Auswaertstore korreliert - muesste die Aenderung an vier
Stellen konsistent nachgezogen werden. Wird eine vergessen, rechnen zwei
Simulationspfade unterschiedlich, ohne dass ein Test das bemerkt.

Verhalten unveraendert
----------------------
Dies ist eine reine Zusammenfuehrung. Die vier Kopien waren
algorithmisch identisch; bei gleichem Seed liefern sie dieselbe Folge.
tests/test_poisson_sampler.py schreibt Referenzfolgen fest, die aus der
Implementierung VOR der Zusammenfuehrung stammen.
"""

import math


def poisson(lmbda, rng):
    """
    Zieht eine Zufallszahl aus der Poisson-Verteilung (Knuth-Verfahren).

    Die Poisson-Verteilung beschreibt, wie oft ein seltenes Ereignis in
    einem festen Zeitraum eintritt - genau das Muster von Toren in einem
    Fussballspiel. lmbda ist die erwartete Toranzahl.

    rng wird uebergeben statt global genutzt, damit ein Lauf mit festem
    Seed reproduzierbar ist.
    """
    limit = math.exp(-lmbda)
    k, p = 0, 1.0
    while p > limit:
        k += 1
        p *= rng.random()
    return k - 1
