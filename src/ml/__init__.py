"""
Machine-Learning-Vorbereitung fuer FootSim.

Dieses Paket enthaelt ausschliesslich den Weg von den historischen
Spielen zu einem Trainingsdatensatz. Es traineirt nichts, laedt kein
Modell und beruehrt den produktiven Simulationspfad nicht.

GRUNDREGEL
----------
Kein Modul hier rechnet Profile, Lambdas, Wahrscheinlichkeiten oder
Belastungsmerkmale selbst aus. Es ruft dieselben Funktionen auf, die
auch src/features/go3_backtest.py benutzt. Zwei Rechenwege waeren eine
sichere Quelle fuer Abweichungen zwischen dem, was ein Modell lernt, und
dem, wogegen es gemessen wird - und die faende niemand, weil beide fuer
sich plausibel aussehen.
"""
