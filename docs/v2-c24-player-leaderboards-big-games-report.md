# V2-C24 / GO 2: Spieler-Bestenlisten und Big-Games-Datenfundament

Stand: 16.09.2026 (mit Korrektur nach dem manuellen Test). Umgesetzt und
lokal verifiziert. Nichts gestaged, committet, gepusht oder deployed.
Keine echte API-Massensammlung, kein einziger Anbieterabruf während der
Arbeit. Keine ML-, Modell- oder Registryänderung.

## 0. Korrektur nach dem manuellen Test (16.09.2026)

Der manuelle Test hat zwei Produktfehler gezeigt. Beide sind behoben.

| Befund aus dem manuellen Test | Korrektur |
| --- | --- |
| Es fehlte ein Knopf zum Erstellen; die Liste erschien allein durch einen Filterwechsel. | Primärer Knopf **Bestenliste erstellen** (EN *Generate leaderboard*) unter den Filtern. Ohne Klick entsteht keine Liste. Jeder Filterwechsel entfernt ein gezeigtes Ergebnis und verlangt einen neuen Klick. |
| Big Games wurde wie eine frei wählbare Statistik behandelt und zeigte als Hauptkennzahl „Anbieterbewertung (API-Football)“. | Bei Big Games gibt es keinen Kennzahl-Dropdown mehr. Die Rangfolge ist fest der **bestehende Big-Game-Score** aus `big_games.aggregate_big_games()`, sichtbar als „Big-Game-Score“ mit dem Satz „Leistung in großen Spielen, gewichtet nach Gegnerstärke und Spielbedeutung.“ Der Server weist eine normale Kennzahl bei `scope=big_games` mit 400 ab. |

Zwei weitere Befunde aus der Prüfung dieser Korrektur, beide behoben:

- **Hauptknopf im hellen Modus unlesbar.** `.simulate-btn` setzt die Schrift fest auf Schwarz, im hellen Modus ist `--accent` aber fast schwarz (`#1a1a1a`); beim Überfahren wurde Weiß auf Weiß. Das betraf alle Hauptknöpfe (Simulieren, Vergleichen). Jetzt weiße Schrift im hellen Modus, Hover schwarz: gemessener Kontrast 17,4:1 statt rund 1,2:1, Hover 21:1.
- **Erster Aufruf dauerte über eine Minute.** Eine lokal noch nicht zwischengespeicherte Profildatei kostete gemessen rund 19 ms (warm 0,3 ms), eine Saison hat rund 3.700 davon. Jetzt werden alle Datenbasen einer Saison in EINEM Durchlauf berechnet (jede Datei genau einmal gelesen) und im Plattencache abgelegt: erster Aufruf 12,4 s, jeder weitere 0,01 bis 0,04 s, nach einem Neustart 0,38 s.

Unverändert geblieben sind ausdrücklich: die Big-Games-Fachlogik
(Klassifikation, Gewichte, Aggregation, Mindestmenge), die historischen
UEFA-/FIFA-Snapshots als einzige Rangquelle, die normalen Bestenlisten
mit ihrem positionsbezogenen Kennzahl-Dropdown, Modell, Bundle und
Registry.

## 1. Ausgangszustand

| Größe | Wert |
| --- | --- |
| Branch / HEAD | `main` / `4f55d80cb47254a3704589dfba3fd5dd78fa937f` |
| git status | 127 Einträge (36 versioniert geändert, 91 unversioniert), nichts gestaged |
| `git diff --stat` | 36 Dateien, +6545/−802 (Stand nach C23, alle früheren Blöcke uncommittet) |
| `git diff --cached --stat` | leer |
| Aktives Modell | `clm-936ecce472696ccb-ls1c4f4e1d` |
| Bundle-SHA-256 | `9f2caf3a38e3385194e48311406844204e85a97e66ee1ef9c8ca949ab1f62479` |
| Registry-Fingerabdruck | `f79bc8566c18dfaa93e36f24df7432537f864b983e099f0d4c3dbfa2810b4b33` |
| Testbaseline (C23, volle Suite) | 2 failed, 6171 passed, 156 skipped, 91 errors |
| C23-Bericht | `docs/v2-c23-approaches-percent-logos-report.md` |

Vorgefundene Architektur, die wiederverwendet wird: Positions- und
Kennzahlenkatalog `src/data/player_metrics.py` (`POSITION_GROUPS`,
`METRICS` mit `direction`), Datenbasen `player_compare_loader.COMPETITION_SCOPES`,
Mindestminuten `percentile_engine.min_minutes_for_scope`, Pools
`src/data/player_pool.py`, Big Games `src/features/big_games.py`,
`src/data/big_games_loader.py`, `src/data/national_big_games_loader.py`.

## 2. Geänderte und neue Dateien

**Neu**

| Datei | Inhalt |
| --- | --- |
| `src/features/player_leaderboard.py` | Kennzahlkatalog je Position (Schlüssel aus `METRICS`), fester Big-Games-Rankingkey, Listenlängen, deterministische Sortierung, Deduplizierung, Populationen (einmal je Saison für alle Datenbasen) und Pool-Bestenliste |
| `src/data/big_games_dataset.py` | Datensatzvertrag (v2), Zeilenschema mit `big_game_score`, Kennzahlen aus Rohsummen, atomares Schreiben, Rangfolge fest nach dem Big-Game-Score, Snapshot-Gegenprüfung, Bestenliste nur aus vollständigen Datensätzen |
| `src/data/big_games_collector.py` | Sammler: Trockenlauf (Standard), Ausführung nur mit Budget, Sperre, Checkpoint, Fortsetzung, Messbericht, fail closed bei fehlendem Snapshot |
| `collect_big_games.py` | Kommandozeile des Sammlers |
| `tests/test_player_leaderboard.py` | 63 Tests: Katalog, Pool-Bestenliste, Route, Big-Games-Rangfolge, Auswahlkatalog, Zwischenspeicher, Gleichheit mit dem Einzelvergleich |
| `tests/test_big_games_dataset.py` | 46 Tests: Sammler, Budget, Checkpoint, Sperre, Datensatz, Score aus der Aggregation, Liste = Einzelvergleich, historische Snapshots, keine Sammlung über die Route, Cache-Tor |
| `tests/test_player_leaderboard_browser.py` | 39 Browsertests (Playwright, `--e2e`) |
| `docs/v2-c24-player-leaderboards-big-games-report.md` | dieser Bericht |

**Geändert**

| Datei | Änderung |
| --- | --- |
| `src/utils/disk_cache.py` | optionales Abruftor `request_gate()` und Lesespeicher `read_memo()`; ohne gesetztes Tor bzw. außerhalb des Blocks exakt das bisherige Verhalten |
| `src/data/big_games_loader.py` | `_get_player_big_games_range` nimmt die Saisonbeschaffung als Parameter (Standard: bisherige gecachte Zugriffe); neu `compute_player_big_games_uncached()` und `dominant_position()` |
| `src/data/player_compare_loader.py` | `cached_season_raw_enriched()`: dieselbe angereicherte Profilantwort wie der Einzelvergleich, ausschließlich aus dem lokalen Cache; gemeinsame Hilfsfunktion `_merge_national_blocks()` |
| `app.py` | neue Routen `GET /api/player-leaderboard` und `GET /api/player-leaderboard-options`; Big Games erzwingt den Big-Game-Score; Populationen aller Datenbasen einer Saison in einem Durchlauf, im Speicher (10 Minuten) und im Plattencache (6 Stunden, Schlüssel mit Änderungskennung der Pooldateien) |
| `templates/index.html` | Umschalter unter der Datenbasis, Vergleichsbereich als `#pc-compare-area` zusammengefasst, Bestenlistenbereich `#pc-leaderboard` mit Knopf, festem Big-Games-Feld und Erklärzeile |
| `static/script.js` | Abschnitt 16a5: Ansichtswechsel, Erstellen ausschließlich per Knopf (Sperre gegen Doppelanfragen, Anfragenummer, Abbruch), Invalidierung bei Filterwechsel, Auswahlkatalog, Darstellung inklusive Big-Game-Score, Übernahme als A/B, Sprachwechsel |
| `static/style.css` | Umschalter (gleiche Tokens wie die Datenbasis), Listenzeilen, festes Big-Games-Feld, Mobil-Layout; keine neuen Farben. Zusätzlich der Kontrast der Hauptknöpfe im hellen Modus (Abschnitt 0) |
| `static/i18n/de.json`, `en.json` | 51 neue Texte je Sprache, ein ungenutzter entfernt (Zeilenende CRLF beibehalten) |
| `static/sw.js` | Cacheversion v39 auf v41 (v40 Bestenliste, v41 Korrektur) |
| `tests/test_player_data_repair.py` | `test_c68_…`: Präfixprüfung `"footsim-v3"` schlug allein durch v40 an; jetzt numerisch `> 31` wie die übrigen Versionstests |
| `README.md` | Abschnitt V2-C24 |

## 3. Tatsächliche UI-Struktur

Spielerbereich, Ansicht Radar, von oben nach unten:

1. Position (Mittelfeld, Sturm, Abwehr, Tor, Alle Positionen)
2. Datenbasis (Alle Vereinswettbewerbe … Big Games)
3. **neu:** Umschalter `Spielervergleich | Bestenliste` (EN `Player comparison | Leaderboard`), Standard Spielervergleich, Radiogruppe mit Pfeiltasten
4. Zeitraum (nur Big Games, gemeinsam für Vergleich und Liste)
5. Spielervergleich: unverändert Spieler A mit Saison und Suche, Tauschen, Spieler B, Vergleichen, Status, Ergebnis
   *oder* Bestenliste: Saison (nur normale Datenbasen), Kennzahl (nur normale Datenbasen) bzw. feste Rangfolge „Big-Game-Score“, Anzahl (Top 5/10/15/20/30), Knopf **Bestenliste erstellen**, Status, Rangliste

Im Spielervergleich gibt es keine Top-N-Auswahl. Beim Umschalten ändert
sich nur der Bereich ab Punkt 5; das Vergleichsergebnis wird in der
Bestenliste ausgeblendet und beim Zurückschalten wieder gezeigt.

**Ablauf:** Position, Datenbasis, Ansicht, Saison bzw. Zeitraum, Kennzahl
(außer Big Games), Anzahl - dann „Bestenliste erstellen“. Erst dieser
Klick lädt. Während des Ladens ist der Knopf gesperrt und die Statuszeile
sagt „Bestenliste wird erstellt …“; ein zweiter Klick erzeugt keine
zweite Anfrage. Ändert sich danach Position, Datenbasis, Saison,
Zeitraum, Kennzahl oder Anzahl, verschwindet die Liste und die
Statuszeile sagt „Auswahl geändert. Bitte erneut ‚Bestenliste erstellen‘
drücken.“ Es wird nichts automatisch nachgeladen. Der Knopf ist immer
sichtbar, auch wenn der Big-Games-Datensatz fehlt.

Listenzeile: Rang, Vereinswappen (28 px, sonst neutraler Platzhalter
gleicher Größe), Name (bricht um), Verein und Liga, Einsätze bzw. Big
Games und Minuten, Kennzahlwert, `Als Spieler A`, `Als Spieler B`
(mindestens 44 px hoch). Kopf: „Sortiert nach: …“, Hinweis bei „niedriger
ist besser“, Mindestmenge, Kennzeichen „Vorläufig“ und „Daten
unvollständig“ samt Nennung fehlender oder unvollständiger Ligen.

Übernahme: Spieler per Player-ID in Slot A oder B, Wechsel in den
Spielervergleich, Position und Datenbasis bleiben, bei normalen
Datenbasen übernimmt der Slot die Saison der Liste.

## 4. Finaler API-Vertrag

`GET /api/player-leaderboard`

| Parameter | Werte | Standard |
| --- | --- | --- |
| `scope` | `club_all`, `league`, `cl`, `euro`, `world_cup`, `national`, `all`, `big_games` | `club_all` |
| `position` | `Goalkeeper`, `Defender`, `Midfielder`, `Attacker`, `all` | `all` |
| `metric` | normale Datenbasen: nur die Kennzahlen der Position (Abschnitt 5). Bei `big_games` ausschließlich `big_game_score` oder weggelassen - eine normale Kennzahl ergibt 400 | erste der Position bzw. `big_game_score` |
| `limit` | `5`, `10`, `15`, `20`, `30` | `10` |
| `season` | 2020 bis laufende Saison; Pflicht bei normalen Datenbasen | – |
| `season_from`, `season_to` | Pflicht bei `big_games`, dieselbe Prüfung wie der Big-Games-Vergleich | – |

400 mit stabilem `error_key` (nie still korrigiert):
`unknownParameter`, `duplicateParameter`, `unknownScope`,
`unknownPosition`, `unknownMetric` (mit `allowed_metrics`),
`invalidLimit` (mit `allowed_limits`), `invalidSeason`,
`invalidCombination` (Zeitraum außerhalb von Big Games, `season` bei Big
Games).

Antwort: `available`, `reason`, `source` (`player_pool` |
`big_games_dataset`), `scope`, `scope_label`, `position`, `season` /
`season_label` bzw. `season_from` / `season_to` / `period_label`,
`metric` (Schlüssel, Label, Typ, Richtung, Erklärung), `direction`,
`limit`, `allowed_limits`, `allowed_metrics`, `rows`, `eligibility`,
`coverage`, `provisional`, `incomplete`, bei Big Games zusätzlich
`ranking_key` (`big_game_score`). Gründe für `available: false`:
`no_pool_data`, `tournament_not_in_season`, `no_eligible_players`,
`dataset_missing`, `dataset_incomplete`, `dataset_invalid`,
`snapshot_missing`, `snapshot_changed`.

`GET /api/player-leaderboard-options` liefert den Auswahlkatalog
(Kennzahlen je Position, Big-Games-Kennzahl, Listenlängen, Standard) -
reine Auskunft ohne Berechnung, damit die Oberfläche die Auswahl
anbieten kann, bevor eine Liste erstellt wird.

**Der öffentliche Knopf kann keine Sammlung auslösen.** Die Route liest
ausschließlich vorbereitete Daten: Pooldateien, lokale Profilantworten
und den fertigen Big-Games-Datensatz. Ein Test belegt, dass sie weder
`compute_player_big_games_uncached` noch den Sammler aufruft, keine Datei
schreibt und keinen Anbieterabruf macht. Der Datenaufbau bleibt allein
Sache von `collect_big_games.py`.

Keine Rohantworten, keine Pfade, keine Secrets, keine Rang- oder
Koeffizientenwerte der privaten Snapshots, keine Modell- oder
Registryangaben (per Test geprüft). Die Route macht keinen Anbieterabruf
(per Test mit scheiternden Anbieterfunktionen geprüft; im echten Browser
rief die Seite nur lokale Routen auf).

## 5. Datenbasen, Positionen, Kennzahlen, Top-N

Verfügbare Pool-Datenbasen: alle sieben aus `COMPETITION_SCOPES`. EM/WM
werden für Saisons ohne Turnier mit `tournament_not_in_season`
beantwortet (dieselbe Quelle wie die Ausgrauung im Radar).

| Position | Kennzahlen (erste = Standard) | Richtung |
| --- | --- | --- |
| Sturm | `goal_contributions_per90`, `shots_on_per90`, `key_passes_per90` | höher besser |
| Mittelfeld | `key_passes_per90`, `goal_contributions_per90` | höher besser |
| Abwehr | `tackles_per90`, `interceptions_per90`, `duels_won_pct` | höher besser |
| Tor | `saves_per90`, `conceded_per90`, `rating` | `conceded_per90` niedriger besser |
| Alle Positionen | `rating` („Anbieterbewertung (API-Football)“) | höher besser |

Alle Schlüssel stammen aus `METRICS`; kein eigener Score, keine
Mischformel. Top-N: 5, 10, 15, 20, 30, Standard 10.

Sortierung: Kennzahl gemäß Richtung → mehr Minuten → Name (ohne Akzente,
ohne Groß/klein) → Player-ID.

## 6. Werte, Deduplizierung, Abdeckung, fehlende Werte

**Wichtiger Befund während der Umsetzung.** Die im Pool gespeicherten
Kennzahlen stimmen nicht mehr mit der heutigen Wettbewerbseinordnung
überein. Für 2025/26 wichen bei 1.106 von 3.715 Pooleinträgen die
club_all-Minuten vom Ergebnis derselben Profilantwort ab (855 davon um
mindestens 90 Minuten). Unter anderem zählten dort U21- und U17-Länderspiele
noch als Vereinsspiele: Eine erste Pool-Rangliste hatte zwei
Juniorennationalspieler („Croatia U21“, „England U17“) auf Platz 1 und 2.

Deshalb gilt: **Der Pool bestimmt die Population, die Werte kommen aus der
lokal gespeicherten Profilantwort mit derselben Rechnung wie im
Einzelvergleich** (`cached_season_raw_enriched` → `build_player_profile`
→ `compute_metric`). Alle 3.715 Profilantworten 2025/26 liegen lokal.
Ergebnis im Test und im echten Browser: Kane 4.362 Minuten, 1,49
Torbeteiligungen pro 90, in Liste und Einzelvergleich identisch.

- **Deduplizierung:** eindeutig über die Player-ID; liegt ein Spieler in zwei Ligapools, stammen beide Einträge aus derselben Profilantwort und werden nicht addiert. Kanonischer Eintrag: mehr Minuten im Scope, dann Ligareihenfolge. 2025/26: 121 doppelte Einträge.
- **Abdeckung je Antwort:** Ligen mit Status, genutzte, fehlende und unvollständige Ligen, berücksichtigte Spieler, entfernte Doppelte, abweichende Doppelte, Spieler ohne Daten im Scope, unter der Mindestzeit, ohne Kennzahl, ohne lokales Profil, zugelassene Spieler.
- **Fehlende Werte:** bleiben `None`, zählen als `missing_metric`, werden nie mit 0 sortiert. Eine echte Null bleibt eine Null.
- **Mindestzeit:** unverändert `min_minutes_for_scope` (450, EM/WM 270).
- **Laufende Saison:** `provisional`; 2026/27 ist zudem `incomplete` (Bundesliga-Pool leer, alle fünf Pools `provider_incomplete`) und liefert derzeit ehrlich `no_eligible_players`.

Messung 2025/26, Sturm, Alle Vereinswettbewerbe: 867 berücksichtigt, 100
ohne Daten im Scope, 256 unter 450 Minuten, 0 ohne Kennzahl, 0 ohne
Profil, 511 zugelassen.

Leistung: Die Population einer Saison und Datenbasis wird beim ersten
Aufruf berechnet (gemessen 4,7 bis 6,6 s) und zehn Minuten im Speicher
gehalten (Schlüssel mit Änderungskennung der Pooldateien). Jeder weitere
Positions-, Kennzahl- oder Top-N-Wechsel kostet unter 0,1 s.

## 7. Big-Games-Datensatz

Speicherort `data/big_games/leaderboard/` (unter dem bereits
ausgeschlossenen `data/big_games/`, also nie versioniert).

Datei `big_games_<saison>.json`:

| Feld | Inhalt |
| --- | --- |
| `schema_version`, `contract_version` | `1`, `big-games-leaderboard-v1` |
| `season`, `status`, `provisional`, `created_at` | nur `complete` wird geschrieben |
| `eligibility` | `min_matches` 3, `min_minutes` 180 (aus `big_games.py`) |
| `snapshots` | Fingerabdrücke (16 Hex) des UEFA-Snapshots der Saison und der benutzten FIFA-Jahre, nie der Inhalt |
| `population`, `collector` | Quelle, Ligen, Spielerzahl, Abrufzähler |
| `players[]` | `player_id`, `name`, `position` (dominante Big-Games-Position wie im Vergleich), `pool_position`, `league`, `team_id`/`team_name`/`team_logo`, `fixture_ids`, `big_games`, `minutes`, `raw_totals`, `metrics` (pro 90 und Quote), `rating`, `sufficient_sample`, `missing` (je Statistik: Zahl der Spiele ohne Wert), `matches` (kompakte Spielzeilen ohne Gegnerrang und Koeffizient), `seasons` |

Checkpoint `checkpoint_<saison>.json`: erledigte Spielerzeilen, Status,
Abrufsummen, Läufe. Sperre `collector.lock` (atomar angelegt; verwaist
nur über das Alter, ohne Prozessprüfung, wie beim Poolimport).

**Der Big-Game-Score, exakt wie im Code.** Die Liste erfindet nichts; sie
liest den Wert, den `big_games.aggregate_big_games()` ohnehin berechnet:

```
big_game_score = Σ(Bewertung × Kontextgewicht × Minuten) / Σ(Minuten)
                 über alle Big Games mit Bewertung und Einsatzzeit
```

- Er entsteht nur, wenn `has_sufficient_sample()` erfüllt ist: mindestens 3 gespielte Big Games UND 180 Minuten. Sonst ist er `None` - nie 0 und nie eine Ersatzzahl.
- `Kontextgewicht = Gegnerstärke × Spielbedeutung` (`big_game_weight`).
- Verein: Gegnerstärke `1,00 + 0,50 × Anteil des UEFA-Koeffizienten an der Spannweite DERSELBEN Saison` (`opponent_strength`, ohne Koeffizient neutral 1,00); Bedeutung 1,00 bis 1,15 je Phase (`match_importance`).
- Nationalmannschaft: Gegnerstärke 1,08 (FIFA 1 bis 10), 1,04 (11 bis 20), sonst 1,00; Bedeutung 1,05 bis 1,15 nur in K.-o.-Spielen von WM und EM (`national_context_weight`).
- Rohwerte bleiben roh: Tore werden nie gewichtet. Das Gewicht steckt ausschließlich im ausdrücklich benannten Score.

Sortiert wird nach diesem Score absteigend, danach mehr Big-Game-Minuten,
Name, Player-ID. Ausdrücklich NICHT nach der Anbieterbewertung: Ein Test
belegt, dass Durchschnittsnote und Score verschieden ordnen und die Liste
dem Score folgt.

**Liste = Einzelvergleich.** Jede Zeile entsteht aus
`big_games_loader.compute_player_big_games_uncached()`, derselben
Funktion, die der Einzelvergleich mit Cache aufruft: Profil →
Vereinswettbewerbe (Friendlies und Nationalteams ausgeschlossen) →
Spielpläne → Klassifikation mit dem UEFA-Snapshot der Saison bzw. dem
FIFA-Jahressnapshot → Einzelspielerwerte nur für qualifizierte Spiele →
Deduplizierung über die Fixture-ID → `aggregate_big_games`. Die Liste
rechnet pro 90 und Quote mit `player_metrics.per90`/`rate` aus genau
diesen Rohsummen. Getestet: gleiche Fixture-IDs, gleiche Rohsummen,
gleiche Bewertung, gleiche Mindestmengenaussage, gleiche Position,
gleicher Listenwert; auch mit Nationalspiel und doppelter Fixture.

**Mindestmenge:** der im Code tatsächlich implementierte Vertrag
`big_games.MIN_BIG_GAMES = 3` und `MIN_BIG_GAME_MINUTES = 180`
(`has_sufficient_sample`), für Liste und Vergleich derselbe. Ob eine
öffentliche Rangliste eine höhere Schwelle (zum Beispiel 5 Spiele / 450
Minuten, wie in der Analyse vorgeschlagen) haben soll, ist eine offene
Produktentscheidung; sie wurde nicht eigenmächtig geändert.

**Verfügbarkeit:** nur wenn für jede Saison des Zeitraums ein
vollständiger Datensatz vorliegt. Heute liegt keiner vor; die Route
antwortet `available: false`, `reason: dataset_missing`, mit Abdeckung.
Die Oberfläche zeigt „Bestenliste derzeit nicht verfügbar“ mit
Erklärung, keine leere Tabelle und keine Liste aus einzelnen Caches.

**Historische Snapshots sind verbindlich (fail closed).** Der Datensatz
speichert den Fingerabdruck des UEFA-Snapshots seiner Saison und der
benutzten FIFA-Jahre. Beim Lesen wird gegengeprüft: Fehlt der Snapshot
heute, antwortet die Route `snapshot_missing`; wurde er ersetzt,
`snapshot_changed` - in beiden Fällen ohne Liste. Eine neue, aktuelle
Rangliste einer anderen Saison verändert einen historischen Datensatz
dagegen nicht (eigener Test). Fehlt beim Sammeln der Snapshot, gilt kein
Spieler als erledigt und es entsteht kein Datensatz; `build_dataset()`
verweigert ihn zusätzlich. Es wird nie eine Top-30 oder Top-20 selbst
berechnet, nie ein anderes Jahr eingesetzt und nie eine Rangliste
abgerufen - belegt durch einen Test, der jede Funktion des
Koeffizientenmoduls mitschreibt (nur Lesen des gespeicherten Snapshots),
Netzverbindungen sperrt und die Snapshotdateien vorher/nachher
byteweise vergleicht.

## 8. Sammler

`python collect_big_games.py --season 2025` → Trockenlauf.

- **Kein Netz im Trockenlauf, technisch erzwungen:** Während des Laufs sitzt `disk_cache.request_gate` vor jedem Nachladen und weist jeden Loader vor seinem Aufruf ab. Zusätzlich im Messlauf: Socketverbindungen gesperrt und gezählt, Ergebnis 0 Versuche.
- **Ausführung** nur mit `--execute` und `--max-provider-requests` 1 bis 500; `None`, 0, negativ, über 500, `True` oder Text brechen vor dem ersten Abruf ab (Exit 2). Harte Obergrenze `MAX_REQUESTS_PER_RUN = 500`.
- **Cache zuerst:** vorhandene Einträge, auch abgelaufene, werden benutzt und nie erneut geladen. Dieselbe Fixture wird für alle Spieler genau einmal geholt (gemeinsamer Schlüssel).
- **Budgetende:** Checkpoint sauber gespeichert, Status `incomplete`, kein Datensatz; der nächste Lauf setzt fort, bereits Geholtes wird nicht erneut geladen (getestet).
- **Fehlerhafte Antwort:** der Spieler bleibt offen, der fehlerhafte Schlüssel wird im selben Lauf nicht wiederholt; ein späterer Lauf holt nur das Fehlende (getestet).
- **Sperre:** ein zweiter Sammler bricht vor jedem Abruf ab (Exit 5).
- **Vollständigkeit:** ein Spieler zählt erst als erledigt, wenn während seiner Rechnung nichts gefehlt hat oder fehlgeschlagen ist; der Datensatz entsteht erst, wenn die gesamte Population erledigt ist, und wird atomar geschrieben.
- **Fail closed bei fehlendem Snapshot (Korrektur):** Fehlt der UEFA-Snapshot der Saison, ein benutztes FIFA-Jahr oder eine Nationalteamquelle, gilt der Spieler als offen (`uefa_snapshot_missing`, `fifa_snapshot_missing`, `national_source_incomplete`) - sonst stünde er mit scheinbar null Big Games im Datensatz.

**So läuft die Sammlung für 2025/26:**

```bash
python collect_big_games.py --season 2025                        # Trockenlauf, kein Netz
python collect_big_games.py --season 2025 --execute --max-provider-requests 500
```

Der zweite Befehl wird so oft wiederholt, bis der Bericht
`"dataset_written": true` meldet (Exit 0; Exit 3 heißt: noch offen,
Checkpoint geschrieben). Jeder Lauf setzt über
`data/big_games/leaderboard/checkpoint_2025.json` genau dort fort, wo der
vorige endete, und lädt nichts erneut, was lokal schon liegt. Nach dem
letzten Lauf liegt `big_games_2025.json` mit `status: complete`; damit ist
der Datensatz freigegeben, und der Knopf „Bestenliste erstellen“ liefert
ab dem nächsten Klick eine echte Top 5/10/15/20/30 - ohne Neustart und
ohne weiteren Schritt.

## 9. Trockenlauf 2025/26 (einziger Lauf, ohne Netz)

Befehl: Sammler im Trockenlauf mit gesperrten Sockets, Dauer 7,6 s,
**0 Netzversuche, 0 Anbieterabrufe, keine Datei geschrieben**
(`data/big_games/` danach unverändert: nur `fifa_rankings/`,
`uefa_coefficients/`).

**GEMESSEN**

| Größe | Wert |
| --- | --- |
| Population (eindeutige Spieler, 5 Ligapools) | 3.594 (3.715 Einträge, 121 doppelt) |
| Spieler vollständig aus lokalen Daten | 16 |
| Spieler mit fehlenden Daten | 3.578 |
| Eindeutige Vereine mit Vereinswettbewerben | 575 |
| Team-Saison-Spielpläne benötigt | 1.065 (20 lokal, 1.045 fehlen) |
| Profile API-Saison 2025 | 3.594 vorhanden (10 frisch, übrige abgelaufen, aber gültig) |
| Profile API-Saison 2026 (für die Nationalspielsuche) | 820 vorhanden, 2.774 fehlen |
| Nationalteams: Identität | 113 benötigt, 70 fehlen |
| Nationalteams: Spielpläne | 113 benötigt, 106 fehlen |
| Qualifizierte Vereinsspiele aus lokalen Spielplänen | 86 (85 Einzelspielerwerte lokal, 1 fehlt) |
| Qualifizierte Nationalspiele aus lokalen Spielplänen | 17 (alle lokal) |
| Abgelaufene, aber benutzte Einträge | 4.533 |
| Fehlende Schlüssel gesamt | **3.996** (2.774 Profile, 1.045 Vereinsspielpläne, 106 Nationalspielpläne, 70 Nationalteamidentitäten, 1 Einzelspielerwerte) |
| Spieler mit unvollständiger Quelle (Korrekturlauf) | 2.950 `national_source_incomplete`; kein einziges `uefa_snapshot_missing` oder `fifa_snapshot_missing` - die historischen Snapshots 2021 bis 2026 liegen vollständig vor |

**ABGELEITET**

- Die 3.996 fehlenden Schlüssel sind eine Untergrenze: Einzelspielerwerte der Big Games in den 1.045 fehlenden Spielplänen sind erst nach deren Abruf bekannt; ebenso Nationalteams, die erst aus den 2.774 fehlenden Profilen hervorgehen.
- Unter den benötigten Spielplänen sind auch Jugendnationalwettbewerbe, zum Beispiel Liga 850 (U21-EM-Qualifikation, 38 Team-Saisons) und 886 (U17). Sie passieren den Vereinsfilter des bestehenden Einzelvergleichs, verursachen Abrufe, erzeugen aber keine Big Games (Gegner ohne UEFA-Rang). Nicht geändert, siehe Abschnitt 14.

**GESCHÄTZT**

- Zusätzliche Einzelspielerwerte-Abrufe nach dem Laden der Spielpläne: grob 600 bis 1.000 (Top-5-Ligaspiele gegen UEFA-Top-30, Europapokal, Pokalfinals, Supercups, Klub-WM, WM 2026 und Qualifikation gegen FIFA-Top-20; über beide Mannschaften dedupliziert).
- Gesamtbedarf Pilotsaison 2025/26: **rund 4.600 bis 5.000 Abrufe**, also etwa 10 Ausführungen à 500. Das liegt deutlich über der Analyse-Schätzung von 1.400 bis 1.600 je Saison: Die Semantik des Einzelvergleichs verlangt die Spielpläne *jedes* Vereinswettbewerbs *jedes* Spielers (575 Vereine, auch Leihvereine und Pokale) und die Profile der API-Saison 2026 für die Nationalspielsuche.

Keine Schätzung ist hier als Messwert ausgegeben.

## 10. Tests: Befehle, Ergebnisse, Exitcodes

| Befehl | Ergebnis | Exit |
| --- | --- | --- |
Die Korrektur wurde erneut vollständig geprüft; die Zahlen dieser Tabelle sind die Ergebnisse **nach** der Korrektur.

| Befehl | Ergebnis | Exit |
| --- | --- | --- |
| `node --check static/script.js` und `node --check static/sw.js` | ohne Befund | 0 |
| `python -m pytest tests/test_player_leaderboard.py -q` | 63 passed | 0 |
| `python -m pytest tests/test_big_games_dataset.py -q` | 46 passed | 0 |
| `python -m pytest tests/test_player_leaderboard_browser.py -q --e2e -m e2e` | 39 passed | 0 |
| Regressionsblock, 30 Dateien (neue C24-Tests, Big Games inkl. national, Spielervergleich, Pool, Pool-Scopes, Plots, Spielerrouten, Datenreparatur, C23, `test_js_syntax`, i18n, PWA, Hero, Responsive, Navigation) | 1459 passed | 0 |
| Browserblock `test_player_leaderboard_browser.py`, `test_cl_approach_browser.py`, `test_browser_smoke.py` mit `--e2e -m e2e` | 168 passed | 0 |
| **Volle Suite** `python -m pytest tests/ -q -p no:cacheprovider -rfE` (genau einmal nach der Korrektur, 1:10:18) | **1 failed, 6372 passed, 195 skipped, 0 errors** | **1** |

Einordnung:

- Der Regressionsblock lief diesmal vollständig grün (1459 passed, Exit 0); die zuvor 5 Fehler aus `test_audit_hardening.py` entfielen, weil lokal eine PostgreSQL lief. Aus demselben Grund lief auch der Browserblock ohne Fehler durch (168 passed statt 97 passed / 58 errors), einschließlich `test_browser_smoke.py` Stufe 2.
- Kein Test wurde gelöscht, übersprungen oder gelockert. Einzige Anpassung eines bestehenden Tests: `test_player_data_repair.py::test_c68_…` (Abschnitt 2).
- **Volle Suite nach der Korrektur gegen die C24-Baseline** (2 failed, 6261 passed, 182 skipped, 91 errors): **keine neue Fehleridentität.** Die 91 Fehler sind entfallen, weil diesmal eine lokale PostgreSQL lief; +111 passed setzen sich aus diesen 91 Datenbanktests und den 20 neuen Python-Tests der Korrektur zusammen (Route 56 → 63, Datensatz 34 → 46). Von den zwei bekannten Fehlschlägen blieb einer: `test_go1_season_and_pit.py::TestSaisonWeitergabe::test_provider_ausfall_bleibt_neutral`. Der zweite (`test_test_isolation::…test_umgekehrte_reihenfolge_aendert_nichts`) lief diesmal grün; er ist reihenfolgeabhängig und wird von der geänderten Reihenfolge der Datenbanktests beeinflusst. Kein Fehlschlag betrifft C24-Code.
- Zum Vergleich der Lauf **vor** der Korrektur: 90 Python-Tests (56 + 34), 26 Browsertests, Regressionsblock 1435 passed / 5 errors, Browserblock 97 passed / 58 errors, volle Suite 2 failed, 6261 passed, 182 skipped, 91 errors.
- Volle Suite C24 gegen C23 (2 failed, 6171 passed, 156 skipped, 91 errors): identische Fehleridentitäten, 93 gegen 93, keine neue und keine verschwundene. Die zwei Fehlschläge sind die bekannten (`test_go1_season_and_pit::…test_provider_ausfall_bleibt_neutral`, `test_test_isolation::…test_umgekehrte_reihenfolge_aendert_nichts`), die 91 Fehler die Datenbanktests ohne lokale PostgreSQL.
- Trockenlauf: siehe Abschnitt 9 (Exit 0, 0 Netzversuche).

## 11. Browserprüfung

- Harnisch (echtes Template und echtes `script.js`, API per Routenabfangung, kein Netz): **39 passed**, darunter Standard Spielervergleich, Lage des Umschalters direkt unter der Datenbasis, Knopf unter den Filtern (≥ 44 px), **ohne Klick keine Liste und keine Anfrage**, Doppelklick erzeugt genau eine Anfrage, Top 5/10/15/20/30, mehr als 30 gelieferte Zeilen werden auf 30 gekürzt, jeder Filterwechsel (Anzahl, Kennzahl, Saison, Position, Datenbasis) entfernt das Ergebnis ohne Neuberechnung und ein erneuter Klick erzeugt es neu, Big Games ohne Kennzahl-Dropdown mit festem „Big-Game-Score“ und ohne das Wort „Anbieterbewertung“, vollständiger Big-Games-Datensatz wird nach Score angezeigt, Übernahme als A und als B per ID (auch aus Big Games), DE und EN, fehlendes und defektes Wappen (Platzhalter 28 px), lange Namen, späte Antworten (Filter-, Ansicht- und Datenbasiswechsel während der Anfrage), 1280/375/320 für normale Datenbasen UND Big Games ohne Überlauf, keine Konsolen- und Seitenfehler.
- Echte Anwendung (eigens gestarteter Entwicklungsserver, danach beendet; echte Pools und Profile; frischer Browserkontext ohne Service Worker) bei 1280, 375 und 320 px: vor dem Klick keine Anfrage und keine Liste, Knopf sichtbar; nach dem Klick 30 Zeilen (Sturm/Torbeteiligungen: 1. H. Kane 1,49, 2. M. Taremi 1,36, 3. O. Dembélé 1,32); Filterwechsel entfernt das Ergebnis ohne neue Anfrage; Big Games ohne Kennzahl-Dropdown, festes Feld „Big-Game-Score“, Hinweistext, Knopf bleibt bedienbar, Ergebnis „Bestenliste derzeit nicht verfügbar“; kein horizontaler Überlauf; keine Seiten- oder Konsolenfehler; aufgerufen wurden nur lokale Routen.
- Zeiten in der echten Anwendung: erster Klick je Saison 12,4 s (alle Datenbasen in einem Durchlauf), jeder weitere Aufruf 0,01 bis 0,04 s, nach einem Serverneustart 0,38 s.
- Kontrast des Hauptknopfs gemessen: hell 17,4:1, dunkel 18,8:1, Hover 21:1.

## 12. Sicherheit, Modell, Git

| Größe | Vorher | Nachher |
| --- | --- | --- |
| Aktives Modell | `clm-936ecce472696ccb-ls1c4f4e1d` | unverändert |
| Bundle-SHA-256 | `9f2caf3a38e3385194e48311406844204e85a97e66ee1ef9c8ca949ab1f62479` | unverändert (Registry und Datei) |
| Registry-Fingerabdruck | `f79bc8566c18dfaa93e36f24df7432537f864b983e099f0d4c3dbfa2810b4b33` | unverändert, `validate_registry` ohne Befund |
| `data/ml/models` | 6 Dateien | 6 Dateien, keine neue |
| Branch / HEAD | `main` / `4f55d80` | unverändert |
| git status | 127 Einträge (36 / 91) | 139 Einträge (40 versioniert geändert, 99 unversioniert) |
| `git diff --stat` | 36 Dateien, +6545/−802 | 40 Dateien, +8053/−815 (enthält alle früheren, uncommitteten Blöcke) |
| `git diff --cached --stat` | leer | leer |
| `git diff --check` | – | ohne Befund (Exit 0), neue Dateien ebenfalls |

Neu in diesem Block versioniert geändert: `src/data/big_games_loader.py`,
`src/data/player_compare_loader.py`, `src/utils/disk_cache.py`,
`tests/test_player_data_repair.py`. Weitere C24-Änderungen an bereits
vorher geänderten Dateien: `app.py`, `templates/index.html`,
`static/script.js`, `static/style.css`, `static/sw.js`, beide Kataloge,
`README.md`. Neu unversioniert: die acht Dateien aus Abschnitt 2.

- Geheimnissuche über Diff und neue Dateien: keine Schlüssel, Tokens, Passwörter, Datenbank-URLs oder lokalen absoluten Pfade. Die einzigen Treffer des Hex-Musters sind Commit-, Bundle- und Registryprüfsummen in `README.md` und diesem Bericht. `.env` weder geöffnet noch ausgegeben (die Anwendung lädt sie beim Start selbst).
- U+2014: README 0, dieser Bericht 0, alle neuen Dateien 0. In `static/i18n/en.json` stehen 4 Gedankenstriche, alle unverändert aus `HEAD` (keiner in den neuen Bestenlistenschlüsseln).
- Bundle und Registry auch nach Dateidatum unberührt: beide zuletzt am 13.09.2026 geschrieben, vor diesem Block.
- Nichts gestaged, nichts committet, nichts gepusht, nichts deployed.
- Keine API-Massensammlung, kein einziger Anbieterabruf; kein Datensatz und kein Checkpoint geschrieben (`data/big_games/` enthält weiterhin nur `fifa_rankings/` und `uefa_coefficients/`).
- Der für die Browserprüfung gestartete Entwicklungsserver ist beendet (Port 5000 frei); kein Test-, Browser- oder Sammlerprozess läuft mehr.
- Berichtspfad: `docs/v2-c24-player-leaderboards-big-games-report.md`.

## 13. Rechtefrage

Aus dem Repository nicht geklärt und deshalb ein **organisatorischer
Releasepunkt**: ob die Bedingungen von API-Football öffentliche
Ranglisten auf Basis ihrer Einzelspielerwerte und Bewertungen erlauben
und wie die Quelle zu nennen ist. Umgesetzt ist das Vorsichtige: kein
Export, keine Rohantworten im Browser, Bewertungen ausdrücklich als
„Anbieterbewertung (API-Football)“ benannt, die privaten UEFA- und
FIFA-Listen verlassen den Server nicht. Die Big-Games-Liste zeigt keine
Anbieterbewertung, sondern den daraus abgeleiteten Big-Game-Score. Eine
rechtliche Freigabe wird hier nicht behauptet.

## 14. Offene Punkte

Keine offenen Pflichtprobleme dieses Blocks. Bekannt und bewusst offen:

1. **Big-Games-Bestenliste ohne Daten.** Technisch fertig, sichtbar als „derzeit nicht verfügbar“; der Knopf bleibt vorhanden. Sie wird erst mit der Datensammlung (gemessene Untergrenze 3.996, geschätzt 4.600 bis 5.000 Abrufe für 2025/26) und deiner Freigabe des Kontingents verfügbar. Die Befehle dafür stehen in Abschnitt 8.
2. **Pool-Kennzahlen veraltet.** 1.106 von 3.715 Pooleinträgen 2025/26 folgen noch der alten Wettbewerbseinordnung. Die Bestenliste umgeht das (Werte aus den Profilen), die **Plots lesen weiterhin die Poolwerte** und können deshalb von Liste und Einzelvergleich abweichen. Abhilfe wäre ein Neuaufbau der Pools aus den lokalen Profilen (kein Anbieterabruf); nicht Teil dieses Blocks.
3. **Jugendwettbewerbe im Big-Games-Vereinsfilter.** U21/U17-Qualifikationen (z. B. Liga 850, 886) passieren den Vereinsfilter des bestehenden Einzelvergleichs und verursachen Spielplanabrufe ohne Big-Games-Ertrag. Eine Änderung würde die Semantik des Einzelvergleichs ändern und ist eine eigene Entscheidung.
4. **Mindestmenge Big Games.** Umgesetzt ist der bestehende Vertrag (3 Spiele, 180 Minuten). Ob eine öffentliche Rangliste eine höhere Schwelle bekommt, bleibt Produktentscheidung.
5. **Erster Klick je Saison** dauert rund 12 s, solange die Profildateien noch nicht im Plattencache stehen (danach 0,01 bis 0,4 s, auch nach einem Neustart). Auf einem Server mit schnellerem Dateisystem ist der erste Lauf kürzer; gemessen wurde lokal unter Windows.
6. **Rechtefrage** (Abschnitt 13) als organisatorischer Releasepunkt.
7. **Browser-Smoke Stufe 2** braucht eine lokale PostgreSQL. Beim Korrekturlauf war sie vorhanden, deshalb lief die Stufe mit (168 passed). Ohne Datenbank bleibt der bekannte Infrastrukturfehler bestehen; kein Codefehler.

## 15. Darf Elie den manuellen Test beginnen?

**Ja, lokal.** Die beiden Beanstandungen aus dem letzten manuellen Test
sind behoben und belegt: Es gibt den Hauptknopf „Bestenliste erstellen“,
ohne Klick entsteht keine Liste und keine Anfrage, und Big Games ist
keine frei wählbare Kennzahlenliste mehr, sondern die feste Rangfolge
nach dem bestehenden `big_game_score` aus `aggregate_big_games()`.
Ebenfalls erfüllt und belegt: Umschalter unter der Datenbasis, Standard
Spielervergleich, A/B-Vergleich unverändert, Bestenliste ersetzt nur den
unteren Bereich, Top 5/10/15/20/30 (Maximum 30), positionsabhängige
Kennzahlen bei den normalen Datenbasen, Pool-Listen ohne Anbieterzugriff,
Übernahme als A/B, ehrliche Behandlung unvollständiger Saisons, keine
Big-Games-Liste aus Einzelcaches, historische UEFA-/FIFA-Snapshots als
verbindliche Quelle mit fail closed, sicherer idempotenter Sammler,
Trockenlauf 2025/26 ohne Netz, identische Werte in Liste und
Einzelvergleich, keine neue C23-/C24-Regression, DE/EN vollständig,
1280/375/320 geprüft, Modell/Bundle/Registry unverändert, nichts gestaged
oder veröffentlicht, keine Massensammlung. Das ist keine Freigabe für
den VPS und keine Freigabe der Big-Games-Datensammlung.

Worauf beim manuellen Test zu achten ist: Spieler → Radar → Umschalter
„Bestenliste“; Filter einstellen und **„Bestenliste erstellen“ klicken**
(vorher erscheint bewusst nichts); der erste Klick je Saison dauert
einige Sekunden, danach ist es sofort; jeder Filterwechsel leert das
Ergebnis und erwartet einen neuen Klick; Position und Kennzahl wechseln;
„Als Spieler A/B“ übernehmen und vergleichen; Datenbasis Big Games zeigt
kein Kennzahlenfeld, sondern „Big-Game-Score“ mit Erklärung und nach dem
Klick den Hinweis „Bestenliste derzeit nicht verfügbar“, solange der
Datensatz fehlt; Saison 2026/27 ist vorläufig und hat derzeit noch keine
Spieler mit 450 Minuten.
