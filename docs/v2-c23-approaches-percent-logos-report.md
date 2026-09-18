# V2-C23: Drei Simulationsansätze, korrekte Ergebnisprozente, Mannschaftslogos

Stand: 14.09.2026. Umgesetzt und verifiziert, lokal. Nichts gestaged,
committet, gepusht oder deployed. Kein Training, keine Reevaluation, kein
neues Bundle, keine neue Modell-ID, keine Registryänderung.

## 1. Ausgangszustand vor den Änderungen

Gemessen zu Beginn des Blocks, vor der ersten Änderung:

| Größe | Wert |
| --- | --- |
| Branch | `main` |
| HEAD | `4f55d80cb47254a3704589dfba3fd5dd78fa937f` |
| git status | 119 Einträge, nichts gestaged; `git diff --stat`: 31 Dateien, +4573/−645 |
| Aktives Modell | `clm-936ecce472696ccb-ls1c4f4e1d` |
| Bundle-Hash (Registry und Datei) | `9f2caf3a38e3385194e48311406844204e85a97e66ee1ef9c8ca949ab1f62479` |
| Registry-Fingerabdruck | `f79bc8566c18dfaa93e36f24df7432537f864b983e099f0d4c3dbfa2810b4b33` |
| Registry-Stufen | `clm-8a4eda90a08395cc` candidate, `clm-3475c9aacef6fec9-lsa165be9c` rollback, `clm-936ecce472696ccb-ls1c4f4e1d` active |
| Laufende Instanz | Port 5000, Python 3.9 mit Debug-Reloader, Betriebsart `active` (aus der Antwort gelesen), Antwort ohne `simulations` |
| Testbaseline | letzte vollständige Suite am Ende von C22: 2 failed, 6013 passed, 126 skipped, 91 errors |

Hinweis zur Zählung: Das Startskript zählte die unversionierten Einträge
mit `-like '??*'`; in PowerShell ist `?` dort ein Platzhalter, die Zahl
"untracked: 119" war deshalb die Gesamtzahl, nicht die der unversionierten
Einträge. Die Gesamtzahl 119 und die Diff-Statistik sind davon nicht
betroffen.

Die Testbaseline wurde zu Beginn von C23 nicht neu erhoben (eine volle
Suite dauert rund eine Stunde); Vergleichsgrundlage ist der letzte volle
Lauf aus C22 mit seinen Fehleridentitäten.

## 2. Geänderte und neue Dateien

| Datei | Änderung |
| --- | --- |
| `src/predict/cl_custom_factors.py` | Ansatz `classic`; `SEASON_FACTOR_NAMES`/`TEAM_FACTOR_NAMES`; eine gemeinsame Formel `_ligaschnitt_anpassen` für beide Pfade; `apply_league_factors`; `parse_season_options` (Query-Parameter, 400 bei allem Unzulässigen); `describe_match_approach` und `describe_season_approach` (was tatsächlich gerechnet hat) |
| `src/predict/cl_season_sim.py` | Parameter `options`; globale Faktoren einmal auf eine Kopie des Ligaschnitts; `ccf.ml_config(options) or current_ml_config()`; Zusammenfassung mit `requested_approach`, `effective_approach`, `ml_fallback`, `ml_fixtures`, `league_stage_applied`, `fallback_reasons` |
| `src/predict/cl_match_sim.py` | `simulations` in der Antwort; `effective_approach`, `ml_fallback`, `league_stage_applied` im `ml`-Block |
| `src/predict/league_match_sim.py` | `simulations` in der Antwort (additiv, sonst unverändert) |
| `app.py` | `/api/cl-season-sim` prüft über `parse_season_options(request.args)` und reicht `options` durch; sonst unverändert |
| `templates/index.html` | dritte Karte; dieselbe Kartengruppe mit zwei globalen Reglern in der Ligaphase; Ergebniszeilen `#result-approach` und `#cl-season-sim-approach`; `result-header-main` |
| `static/script.js` | drei Ansätze, gemeinsamer Zustand, Nutzlast der Ligaphase, Epoche und Anfragezähler gegen späte Antworten, Zurücksetzen bei Wechsel, Logos mit URL-Prüfung, ehrliche Ergebniszeile, neuer Prozentnenner; CL-Ligaphasensteuerung bleibt nach dem Ergebnis sichtbar |
| `static/style.css` | drei Spalten, unter 600 px gestapelt; Wappen 40/32 px, Platzhalter, umbrechende Namen, Ergebniszeile |
| `static/i18n/de.json`, `en.json` | neue und geänderte Texte (Karten, Ergebniszeile, Prozent) |
| `static/sw.js` | Cacheversion v38 auf v39 (neue Karte im HTML braucht das neue script.js beim ersten Aufruf) |
| `README.md` | Hinweis am historischen C8A/C8B-Abschnitt; neuer Abschnitt V2-C23 mit Semantik und API-Feldern |
| `docs/v2-c21-release-runbook.md` | Abschnitt 0 (Saisontabelle kennt jetzt `approach`, Umgebung bleibt für alte Clients) und Smoke-Test um den Ansatz ergänzt |
| `tests/test_cl_three_approaches.py` | neu, 146 Tests |
| `tests/test_cl_approach_browser.py` | Harnisch erweitert (Wappenhost, Ligaphasenroute, zurückhaltbare Antworten), Selektoren eindeutig, neue Klassen für C23 |
| `tests/test_cl_approach_ui.py`, `tests/test_cl_custom_api.py`, `tests/test_c22_local_activation.py` | Wächtertests auf den neuen Vertrag gebracht, jeweils mit Begründung im Test, keiner gelöscht oder gelockert |
| `tests/test_cl_season_sim.py` | Attrappen der Saisonroute nehmen `options` jetzt als Pflichtparameter; zusätzlich geprüft, dass ein Aufruf ohne `approach` `options=None` übergibt |
| `tests/test_ios_pdf_und_share.py` | Anker auf die neue Signatur `renderResult(data, partie, wettbewerbTyp)`; Prüfung unverändert |
| `docs/v2-c23-approaches-percent-logos-report.md` | dieser Bericht |

## 3. Rechnung je Ansatz und Pfad

**Einzelspiel** (`POST /api/simulate`, `cl_match_sim.simulate_cl_league_phase_match`):

1. Profile zum Stichtag der Partie (unverändert, C10/C1B).
2. Nur `custom`: `apply_factors` auf Kopien. Heimteam-Stärke multipliziert `attack_home` des Heimteams, Auswärtsteam-Stärke `attack_away` des Gastteams; Heimvorteil und Torniveau über `_ligaschnitt_anpassen` auf den Ligaschnitt.
3. `expected_goals` (Grenzen 0,15 und 4,5, unverändert).
4. `resolve_simulation_lambdas(config=ml_config(options))`: `ml` ergibt `active` mit Gewicht 1,0 (Basismodell plus Ligastufe, fail-closed); `custom` und `classic` ergeben `off`, der ML-Zweig wird nicht betreten.
5. Poisson-Monte-Carlo mit der geklemmten Laufzahl (100 bis 50.000).

**Ligaphase** (`GET /api/cl-season-sim`, `cl_season_sim.simulate_cl_league_phase`):

1. Plan: gespielte Partien fest, offene werden simuliert (unverändert).
2. Profile zum Laufzeitstichtag, einmal je Lauf.
3. Nur `custom`: `apply_league_factors` einmal auf eine Kopie des Ligaschnitts. Teamfaktoren kommen hier nicht an.
4. Je offener Partie einmal `expected_goals` und `resolve_simulation_lambdas` mit derselben Konfiguration wie im Einzelspiel.
5. Monte Carlo mit UEFA-Tiebreak-Kaskade (unverändert).

**Ohne `approach`** (alte Clients) entscheidet in beiden Pfaden weiter `FOOTSIM_ML_MODE`.

**Parität, gemessen** (echte Pläne, echte Profile, Stichtag `B_after_md6` = 20.01.2026 der Saison 2025/26, 36 offene Partien, Ligaphase gegen Einzelspiel mit `kickoff` = Stichtag):

| Ansatz | verglichen | größte Abweichung | Ergebnis |
| --- | ---: | ---: | --- |
| `classic` | 36 | 0,0 | ML nicht angewandt |
| `custom` (Heimvorteil 1,3, Torniveau 0,85) | 36 | 0,0 | ML nicht angewandt |
| `ml` (isolierte Aktivierung des Kandidaten) | 36 | 0,0 | ML auf 36 von 36, Ligastufe 36 von 36 |

Faktoren genau einmal: Beispielpartie 3 gegen 94, `classic` 2,122611/1,455684, `custom` 2,057126/1,085211. Verhältnis 0,969149111334 und 0,745499316411, erwartet sqrt(1,3)·0,85 = 0,969149111334 und 0,85/sqrt(1,3) = 0,745499316411. Doppelt angewandt stünde dort das Quadrat. Neutrales `custom` ist bitgleich `classic` (Ligaphase und Einzelspiel).

## 4. Reglersemantik, Validierung, Kompatibilität

| Regler | Einzelspiel | Ligaphase | Backendwert |
| --- | --- | --- | --- |
| Heimteam-Stärke | ja | nein (400) | `home_strength` 0,7 bis 1,3 |
| Auswärtsteam-Stärke | ja | nein (400) | `away_strength` 0,7 bis 1,3 |
| Heimvorteil | ja | ja | `home_advantage` 0,5 bis 1,5 |
| Torniveau | ja | ja | `goal_level` 0,75 bis 1,25 |

In der Ligaphase ist jeder Verein viermal Heim- und viermal Gastteam; eine
"Heimteam-Stärke" hätte dort keine Bedeutung. Die Oberfläche erklärt das
in einem Satz unter den Karten.

Abgewiesen mit 400, vor jeder Rechnung: unbekannter Ansatz, `ml_weight`
bei jedem Ansatz, `factors` bei `ml`/`classic`, Teamfaktoren und `factors`
in der Ligaphase, globale Faktoren ohne `custom`, `nan`/`inf`/Text/leere
Werte, Werte außerhalb der Grenzen, doppelte Query-Parameter, `NaN` im
JSON-Body. Die Meldungen nennen nur Parameter und Bereich.

Kompatibilität:

- Clients ohne `approach` rechnen wie bisher nach `FOOTSIM_ML_MODE`, in beiden Pfaden (getestet).
- Alle neuen Antwortfelder sind additiv. `ml.applied_approach` im Einzelspiel bleibt, wie es war (gewünschter Ansatz oder `environment_default`); die Wahrheit steht in `effective_approach`.
- Ligen (Bundesliga usw.) senden weiterhin keinen Ansatz und bekommen keinen; neu ist dort nur `simulations`.
- Wettbewerbswechsel setzt den Ansatz wie bisher auf Machine Learning zurück, jetzt in beiden Gruppen.

## 5. Prozentkorrektur

Ursache: Die Anzeige teilte durch die Summe der fünf angezeigten
Zählungen, die Antwort kannte die Laufzahl nicht.

Jetzt: Anteil = Anzahl / `simulations` · 100, `simulations` ist die
tatsächlich ausgeführte Zahl nach der Klemmung. Ohne gültigen Nenner
(fehlend, 0, negativ, keine Ganzzahl, Text) erscheinen keine Prozentwerte,
kein Rückfall auf die Top-5-Summe. Keine Zeile "Top 5 decken X %".

Gemessen:

- Test: 421 / 5.000 = 8,42 %, angezeigt "8,4 % aller Simulationen" und "421 von 5.000 Simulationen" (EN "8.4% of all simulations", "421 of 5,000 simulations"). Mit den Zählungen 421/402/384/375/146 lieferte die alte Formel 24,4 %.
- Laufende Anwendung (echte Simulation, 5.000 Läufe, Machine Learning): häufigstes Ergebnis 2:1 mit 498 Läufen, angezeigt "10,0 % aller Simulationen" und "498 von 5.000 Simulationen"; die fünf Zeilen summieren sich auf rund 41 %, nicht auf 100 %.
- Klemmung: 60.000 angefragt ergibt `simulations: 50000` (laufende Anwendung und Test), 50 ergibt 100.

1X2, K.-o.-Analyse und Tabellen sind unverändert.

## 6. Ergebnis- und Rückfallanzeige

| Lage | Anzeige (DE) |
| --- | --- |
| ML angewandt | Berechnet mit: Machine Learning |
| ML angewandt, Ligakorrektur fehlt | Berechnet mit: Machine Learning Die Ligakorrektur war für diese Partie nicht verfügbar. |
| Voller Rückfall | Machine Learning war hier nicht verfügbar. Berechnet wurde klassisch. |
| Klassisch / eigene Einschätzung | Berechnet mit: Klassische Simulation / Eigene Einschätzung |
| Ligaphase, teilweise | Machine Learning wurde für 30 von 36 offenen Spielen verwendet, die übrigen wurden klassisch berechnet. |
| Ligaphase, Ligakorrektur teilweise | Berechnet mit: Machine Learning Ligakorrektur bei 139 von 144 offenen Spielen. |
| Ligaphase ohne offene Spiele | Keine offenen Spiele: Die Tabelle beruht auf den gespielten Ergebnissen. |
| Alte Antwort ohne Feld | keine Zeile |

Grundlage ist ausschließlich die Serverantwort. Eine fehlende Ligastufe
gilt nicht als ML-Ausfall. Keine Modell-IDs in der Überschrift (getestet).

Echter voller Rückfall in der laufenden Anwendung: eine Partie mit einem
unbekannten Verein (ID 999999) zeigte "Machine Learning war hier nicht
verfügbar. Berechnet wurde klassisch." Im Test zusätzlich über eine leere,
temporäre Registry (echter Rückfallweg der Laufzeit) in Einzelspiel und
Ligaphase.

Ein Karten- oder Reglerwechsel blendet ein angezeigtes CL-Ergebnis aus
(Spiel und Ligaphase). Antworten einer überholten Anfrage oder eines
älteren Ansatzstands werden verworfen; Knopf und Fehlermeldung gehören nur
der neuesten Anfrage. Die CL-Ligaphasensteuerung bleibt nach dem Ergebnis
sichtbar, damit die Ansätze ohne Umweg vergleichbar sind.

## 7. Logos und Mobilprüfung

- Wappen im Panel "Ausgewählt" (32 px) und im Ergebniskopf (40 px, mobil 32 px), nur Champions League. Im Ergebnis stets die Wappen der berechneten Partie, auch wenn inzwischen eine andere gewählt ist (getestet).
- URL-Prüfung wie `src/api/auth.py`: nur `crests.football-data.org` und `media.api-sports.io` (per Test synchron mit `ALLOWED_CREST_HOSTS`), nur `https`, keine Zugangsdaten, kein Fremdport, höchstens 500 Zeichen; Rückfall auf die football-data-ID. `alt=""`, `referrerpolicy="no-referrer"`. Keine appweite CSP, keine Änderung anderer Logo-Komponenten.
- Fehlend, defekt (404) oder fremder Host ergibt einen neutralen Platzhalter derselben Größe; ein fremder Host wird gar nicht angefragt.

Browser (Playwright/Chromium, echtes Template und echtes script.js):

| Breite | Karten | Ergebniskopf | Überlauf |
| --- | --- | --- | --- |
| 1280 px | drei nebeneinander (beide Tabs) | Favoritenbox rechts, Wappen 40 px | keiner |
| 375 px | untereinander | Favoritenbox darunter, Wappen 32 px | keiner |
| 320 px | untereinander | lange Namen umbrochen, defektes Wappen als Platzhalter | keiner |

Zusätzlich gegen die laufende Anwendung auf Port 5000 (echtes Backend,
echte Wappen, frischer Browserkontext ohne Service Worker) bei 1280, 375
und 320 px: keine Seitenfehler, kein horizontaler Überlauf in Spiel- und
Ligaphasentab, Wappen geladen, Ligaphase klassisch gerechnet mit
"Berechnet mit: Klassische Simulation". Die Screenshots liegen nur im
Scratchpad der Sitzung, nicht im Repository.

## 8. Tests: Befehle, Ergebnisse, Exitcodes

| Befehl | Ergebnis | Exit |
| --- | --- | --- |
| `node --check static/script.js` | Syntax in Ordnung | 0 |
| `python -m pytest tests/test_cl_three_approaches.py -q` | 146 passed | 0 |
| `python -m pytest tests/test_cl_approach_ui.py tests/test_cl_custom_api.py tests/test_c22_local_activation.py tests/test_cl_custom_factors.py -q` | 323 passed | 0 |
| `python -m pytest tests/test_cl_season_sim.py tests/test_ml_runtime.py tests/test_ios_pdf_und_share.py tests/test_cl_three_approaches.py tests/test_cl_custom_api.py -q` (nach den Anpassungen) | 425 passed | 0 |
| Schnelle Regression, 31 Dateien (CL, ML-Laufzeit, Registry, i18n, PWA, Responsive, Navigation, Saisonsimulation u. a.) | 1674 passed, 40 errors; die 40 sind die bekannten Datenbankfehler der Baseline (5 `test_audit_hardening`, 35 `test_privacy_and_deletion`), keine Fehlschläge | 1 (nur durch die Baselinefehler) |
| `python -m pytest tests/test_cl_approach_browser.py -q --e2e -m e2e` | 68 passed (Chromium, 1280/375/320 px) | 0 |
| `python -m pytest tests/ -q -p no:cacheprovider -rfE` (volle Suite, genau einmal) | 2 failed, 6171 passed, 156 skipped, 91 errors in 51:38 | 1 |

Vergleich der vollen Suite mit C22 (2 failed, 6013 passed, 126 skipped,
91 errors): **identische Fehleridentitäten**, 93 gegen 93, keine neue und
keine verschwundene. Die zwei Fehlschläge sind die bekannten
(`test_go1_season_and_pit::…test_provider_ausfall_bleibt_neutral`,
`test_test_isolation::…test_umgekehrte_reihenfolge_aendert_nichts`), die
91 Fehler die Datenbanktests ohne lokale PostgreSQL. Die 30 zusätzlichen
Übersprungenen sind genau die 30 neuen Browsertests, die ohne `--e2e`
übersprungen werden; sie liefen separat (68 passed).

Ein erster, breiterer Regressionslauf mit den schweren Evaluationsdateien
(C12, C14, C15, C16, C21) wurde bei 14 % bewusst abgebrochen, weil dieselben
Dateien in der vollen Suite ohnehin laufen; es lief danach kein Prozess
parallel. Der schnelle Regressionslauf zeigte zunächst fünf neue
Fehlschläge, alle durch diesen Block verursacht und behoben:

- drei Saisonrouten-Tests mit Attrappen der alten Signatur (jetzt `options` als Pflichtparameter und geprüft),
- `test_ml_runtime::test_nur_die_cl_pfade_rufen_die_schicht`: mein neuer Docstring nannte `resolve_simulation_lambdas`; der Docstring ist umformuliert, der Wächter unverändert,
- `test_ios_pdf_und_share::test_genau_ein_listener`: Anker auf die neue `renderResult`-Signatur.

Laufende Anwendung (Port 5000), Smoke-Test am Ende: Startseite 200 mit
zwei klassischen Karten und ohne "V2-Prognose"; `ml`, `classic`,
`custom` und ohne Ansatz jeweils 200 mit `simulations: 5000` und
passendem `effective_approach`; 60.000 ergibt 50.000; sechs unzulässige
Ligaphasenaufrufe und drei unzulässige Einzelspielaufrufe jeweils 400.
Exit 0.

Hinweis zur Umgebung: `import app` und die Testläufe laden die Anwendung
und damit indirekt deren Konfiguration aus `.env`; die Datei wurde weder
geöffnet noch geändert, und es wurden keine Zugangsdaten ausgegeben.

## 9. Modell und Registry unverändert

| Größe | Start | Ende |
| --- | --- | --- |
| Registry-Fingerabdruck | `f79bc856…2810b4b33` | `f79bc8566c18dfaa93e36f24df7432537f864b983e099f0d4c3dbfa2810b4b33`, unverändert |
| Aktives Modell | `clm-936ecce472696ccb-ls1c4f4e1d` | unverändert |
| Bundle-Hash (Registry und Datei) | `9f2caf3a…f1b62479` | `9f2caf3a38e3385194e48311406844204e85a97e66ee1ef9c8ca949ab1f62479`, unverändert |
| `validate_registry` | | ohne Befund |
| Stufen | | unverändert (candidate, rollback, active wie oben) |
| `data/ml/models` | | 6 Dateien, jüngste vom 13.09.2026, keine neue |

Alle Aktivierungen in Tests liefen über `c21.isolated_activation` oder
eine leere Registry in einem temporären Verzeichnis.

## 10. Git-Endzustand

| Größe | Wert |
| --- | --- |
| Branch, HEAD | `main`, `4f55d80cb47254a3704589dfba3fd5dd78fa937f` (unverändert) |
| git status | 126 Einträge: 36 geänderte versionierte Dateien, 90 unversionierte |
| `git diff --stat` | 36 Dateien, +6545/−802 (enthält alle früheren, nicht committeten Blöcke) |
| `git diff --cached --stat` | leer, nichts gestaged |
| `git diff --check` | ohne Befund (Exit 0); die neuen unversionierten Dateien ebenfalls ohne Befund |
| Geheimnissuche | Diff und neue Dateien: keine Schlüssel, Tokens, Passwörter oder lokalen absoluten Pfade (einziger Treffer: `url.password` in der Wappenprüfung, Code) |
| U+2014 | README 0, dieser Bericht 0, alle neuen Texte 0 (`en.json` enthält 4 ältere Vorkommen aus früheren Blöcken, unverändert) |
| Neu in diesem Block versioniert geändert | `static/style.css`, `static/sw.js`, `tests/test_cl_season_sim.py`, `tests/test_ios_pdf_und_share.py` (die übrigen berührten Dateien waren schon vorher geändert) |
| Neu unversioniert | `tests/test_cl_three_approaches.py`, dieser Bericht |
| Berichtspfad | `docs/v2-c23-approaches-percent-logos-report.md` |

Zur Zählung: Der Startwert 119 und der Endwert 126 lassen sich nicht
restlos Datei für Datei gegeneinander aufrechnen, weil das Startskript
keine Dateiliste gespeichert hat (siehe Abschnitt 1). Geprüft ist: Außer
den beiden oben genannten neuen Dateien ist in diesem Block keine
unversionierte Datei entstanden oder geändert worden, außer dem bereits
vorhandenen Runbook und `tests/test_c22_local_activation.py`.

## 11. Verbleibende Pflichtmängel

Keine bekannten Pflichtmängel aus diesem Block.

Bewusste Entscheidungen und bekannte Grenzen, keine Mängel:

- Heim- und Auswärtsteam-Stärke gibt es in der Ligaphase nicht (Entscheidung A1 der Analyse); vereinsbezogene Regler wären ein eigenes Feature.
- Die CL-Ligaphasensteuerung bleibt nach einem Ergebnis sichtbar (vorher ausgeblendet), damit die Ansätze vergleichbar sind. Die Ligen-Saisonsimulation ist unverändert.
- `ml.applied_approach` im Einzelspiel behält seine alte Bedeutung (Wunsch oder `environment_default`); maßgeblich ist `effective_approach`.
- In der Ligaphase zählt `ml_fixtures` das Basismodell; die Ligakorrektur steht getrennt in `league_stage_applied`.
- Die vorhandene Ansatzwahl gilt wie seit C8B auch für CL-K.-o.-Einzelspiele; K.-o.-Analyse und Zahlen sind unverändert.
- Die Balkenbeschriftungen der 1X2-Wahrscheinlichkeiten wirken in den Screenshots der hellen Darstellung blass; das ist älter als dieser Block und nicht angefasst.

## 12. Entscheidung zum manuellen Test

**Bereit für Elies manuellen Test, lokal.** Alle Pflichtpunkte sind
umgesetzt und belegt, die volle Suite zeigt dieselben Fehleridentitäten
wie die Baseline, Browser- und Smoke-Tests sind grün, Modell, Bundle und
Registry sind unverändert. Das ist keine Freigabe für den VPS; die
Auslieferung bleibt ein eigener Schritt nach dem Runbook.

Worauf beim manuellen Test zu achten ist (lokal, Port 5000):

- Beim ersten Aufruf lädt die Seite einmal neu (Service Worker v39); danach sind die drei Karten da.
- Drei Karten in "Spiele" und in "Liga-Simulation", Wahl bleibt beim Tabwechsel.
- Karte wechseln nach einem Ergebnis: Ergebnis verschwindet, statt umetikettiert zu werden.
- Ergebniszeile unter der Überschrift; bei einem Verein ohne Daten der Rückfallhinweis.
- Prozentwerte gegen die Laufzahl: Anzahl / Simulationen, die fünf Zeilen ergeben zusammen weniger als 100 %.
- Logos in "Ausgewählt" und im Ergebnis, Desktop und Handy, lange Namen.
- Ligaphase mit "Eigene Einschätzung": nur Heimvorteil und Torniveau.

## Schätzung der verbleibenden GO-Blöcke

Nach heutigem Stand, ohne erfundene Mindestzahl und ohne Zusage einer
Freigabe. Implementierung und Betrieb sind getrennt.

| Schritt | Art | Inhalt | Abhängigkeiten | Modell, Denkstufe |
| --- | --- | --- | --- | --- |
| GO 2: Bestenliste | Implementierung | Bestenlisten für alle Pool-Datenbasen ohne Anbieterabruf; Navigation; Route `GET /api/player-leaderboard` (Top 5/10/15/20); Übernahme in den Vergleich. Big Games: Sammel-CLI mit Kontingentgrenze und Deduplizierung, versionierter serverseitiger Datensatz, Rangbildung (Einzelkennzahl pro 90 je Position, Mindestmenge), ehrlicher Hinweis, solange Daten fehlen | Entscheidungen D1, D2, E2 bis E5 aus der Analyse; für eine Pilotsaison im Block zusätzlich E1 | Opus 5, High. Ohne den Big-Games-Teil reicht Sonnet 5, High. Teilbar in 2a (Pool und Oberfläche) und 2b (Big Games), wenn der Diff zu groß wird; nicht zwingend |
| Big-Games-Datensammlung | Betrieb, kein Implementierungsblock | rund 1.400 bis 1.600 API-Sports-Abrufe je Saison, 8.500 bis 10.000 für sechs Saisons, verteilt über 2 bis 4 Tage im geteilten Tageskontingent von 7.500; danach rund 50 je Woche | GO 2 (Sammler), Freigabe E1 für den Kontingentverbrauch | Überwachung, Sonnet 5 niedrig oder manuell |
| Auslieferung auf den VPS | Betrieb nach Runbook | Freigaben F1 bis F4, Smoke-Test mit und ohne `approach` (Runbook Abschnitt 8) | Elies Commit und Push; getrennte Entscheidung | begleitend Sonnet 5 oder Opus 5, Medium |

Die Big-Games-Bestenliste ist erst nach der Datensammlung ehrlich
anzeigbar. Bis dahin kann GO 2 die Pool-Bestenlisten liefern und bei Big
Games sichtbar "noch nicht verfügbar" melden.
