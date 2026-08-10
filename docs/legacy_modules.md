# Legacy-Module: Status und Begründung

Stand: August 2026, erstellt während der Datenfundament-Phase vor der ML-Arbeit.

Diese Module sind **absichtlich unangetastet geblieben**. Sie werden hier
dokumentiert, damit niemand sie für aktiv hält — und damit eine spätere
Entfernung eine bewusste Entscheidung ist statt eines Bauchgefühls.

Grundsatz für diese Phase: Entfernen nur, wenn eindeutig feststeht, dass
nichts sie erreicht, und wenn die Entfernung für die aktuelle Arbeit
nötig ist. Beides traf hier nicht zu.

## Nicht mehr erreichbar vom Live-Pfad

| Modul | Status | Belege |
|---|---|---|
| `src/predict/simulate_scores.py` | Tot | Nicht in `app.py` importiert. Enthält das alte lineare xG-Modell sowie die einzige Zwei-Leg-/Verlängerungs-/Elfmeterlogik des Projekts. Ein bestehender Test prüft ausdrücklich, dass `app.py` es *nicht* importiert. |
| `src/features/team_strength.py` | Tot | Einziger Importeur ist `simulate_scores.py`, das selbst tot ist. Liest `data/raw/team_matches.json`. |
| `src/features/fallback_strengths.py` | Tot | Kein aktiver Importeur gefunden. |
| `data/raw/team_matches.json` | Verwaist | Wird nur von `team_strength.py` gelesen, nur von `main.py` geschrieben. |
| `main.py` | Verwaist | Eigenständiges CLI-Skript, nicht Teil der Flask-App. Abgelöst durch `refresh_historical.py` und `refresh_players.py`. |
| `src/features/team_analysis.py` | Verwaist | Kein Caller aus `app.py`. Enthält `POWER_WEIGHTS` (Power-Ranking) und `get_team_form(last_n=5)`. Reines Analytics-Modul ohne Einfluss auf die Simulation. |

**Warum nicht entfernt:** `simulate_scores.py` enthält als einziges Modul
eine Zwei-Leg-Logik mit Verlängerung und Elfmeterschießen. Die
CL-K.-o.-Simulation ist noch nicht umgesetzt; wird sie angegangen, ist
dieser Code die naheliegende Vorlage. `team_analysis.py` wäre bei einer
Reaktivierung ein sauberer ML-Kandidat, weil `POWER_WEIGHTS` fünf freie
Gewichte enthält, die sich gegen tatsächliche Endplatzierungen
optimieren ließen.

## Teilweise aktiv

| Modul | Status | Belege |
|---|---|---|
| `src/predict/matches_to_predict.py` | Anzeige-Fallback | `app.py:211` baut `COMPETITION_MATCHES = {"el": MATCHES_TO_PREDICT_EL}`, gelesen in `app.py:545` als Fallback für Wettbewerbe ohne `_resolve_competition_config`-Eintrag. Liefert statische EL-Fixtures zur Anzeige, wird aber nie simuliert: `/api/simulate` hat keinen `"el"`-Zweig. |
| `src/utils/team_aliases.py` | Aktiv (nur Domestic) | Von `strength_provider.py` als Stufe-1-Fallback der Namensauflösung genutzt. Für die CL **ungenutzt** — `get_cl_team_strengths()` löst ausschließlich über football-data-Team-IDs auf. |
| `static/script.js:1382–1385` | Unerreichbar | `match_id`/`leg_mode`-Payload, greift nur bei `competitionType` weder `"league"` noch `"cl"` (= EL). EL ist `available: False`; das Backend hat für diesen Fall keinen Simulate-Zweig. Vorverdrahtet für eine spätere EL-Aktivierung. |

## In dieser Phase bereinigt

| Was | Warum es sicher war |
|---|---|
| Doppelte Definition von `get_competition_teams` in `league_api.py` | Die Funktion war zweimal definiert (Zeile 373 und 602). Python ließ stillschweigend die zweite gewinnen. Die zweite liefert ein **Superset** der Felder (zusätzlich `country`/`country_code`) — jeder Aufrufer der ersten wäre auch von der zweiten bedient worden. Die erste war damit nachweislich toter Code; ihre Entfernung ändert zur Laufzeit nichts. Ein AST-Test verhindert eine erneute Doppeldefinition. |
| Vier identische `_poisson`-Kopien | Zusammengeführt in `src/predict/poisson.py`. Vor der Zusammenführung wurde belegt, dass alle vier bei identischem Seed dieselbe Zahlenfolge liefern; diese Folgen sind in `tests/test_poisson_sampler.py` als Referenz festgeschrieben. |

## Offene Altlasten außerhalb dieser Phase

- `app.py.bak`, `app.py.bak2`, `app.py.bak3`, `static/*.bak*`,
  `templates/*.bak*`, `_backup_20260728_015527/` — Sicherungskopien im
  Arbeitsverzeichnis. Nicht angefasst; eine Bereinigung gehört in einen
  eigenen, bewusst freigegebenen Schritt.
- `src/api/football_api.py` — laut Modul-Docstring von `league_api.py`
  der „gewachsene Bestand", der von `main.py` genutzt wird und
  unangetastet bleiben soll.
