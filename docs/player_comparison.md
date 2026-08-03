# FootSim – Spielervergleich (Phase 3)

Erstellt: Phase 3, Etappe 1
Stand: Datenschicht fertig, Perzentile und UI folgen

---

## 1. Warum es dieses Modul überhaupt getrennt gibt

Es existierte bereits `src/data/player_stats_loader.py`. Der gehört zum
**Transfervergleich** und liefert eine bewusst schmale Sicht: Minuten, Tore,
Assists, Rating – bezogen auf eine *Zielliga*.

Für den Spielervergleich wurde dieser Loader **nicht erweitert**, sondern ein
eigener gebaut (`player_compare_loader.py`).

Grund: Der Transfervergleich läuft produktiv und wurde in Phase 1 aufwendig
stabilisiert. Jede Signaturänderung an `normalize_player_statistics()` hätte
ein Regressionsrisiko erzeugt, das dem Nutzen nicht entspricht. Zwei Loader
mit klarer Zuständigkeit sind billiger als ein Loader mit zwei Aufgaben.

**Regel:** `player_stats_loader.py` wird von Phase 3 nicht angefasst.

---

## 2. Module und Zuständigkeiten

| Datei | Zuständigkeit | API-Zugriff |
|---|---|---|
| `src/data/player_metrics.py` | Metrik-Katalog, Positionsgruppen, Per-90- und Quotenlogik | nein |
| `src/data/player_compare_loader.py` | Ligawahl, Aggregation, Profil, Vergleichsaufbau | ja (1 Request/Spieler/Saison) |
| `src/api/apisports_api.py` → `_get_full()` | paginierte API-Antworten inkl. `paging` | ja |

`player_metrics.py` enthält absichtlich **keinen** Netzwerkcode. Dadurch ist die
gesamte fachliche Logik ohne API testbar – das war die Voraussetzung dafür, die
Metrikregeln überhaupt sauber absichern zu können.

---

## 3. Die wichtigste Regel: None ist nicht 0

Ein fehlender Wert ist `None` und wird **niemals** stillschweigend zu `0`.

Beispiele:

- Ein Spieler ohne Dribbelversuche hat **keine** Dribbelquote – nicht 0 %.
- Ein Feldspieler hat **keine** Paradenzahl – nicht 0 Paraden.
- Ein Spieler mit 0 gewonnenen von 10 Duellen hat **echte** 0 % – das ist ein Wert, kein `None`.

Der Unterschied zwischen „unbekannt" und „null Ereignisse" ist fachlich
entscheidend. Wird er verwischt, entstehen falsche Perzentile und falsche
Radardiagramme.

Abgesichert durch Tests in `tests/test_player_comparison.py`.

---

## 4. Positionsgruppen

API-Sports liefert unter `statistics[n].games.position` **ausschließlich** vier
Werte:

```
Goalkeeper | Defender | Midfielder | Attacker
```

Es gibt **keine** Unterscheidung zwischen CB und RB, zwischen DM, CM und AM oder
zwischen Flügel und Mittelstürmer.

### Verworfene Alternative: feinere Gruppen ableiten

Denkbar wäre gewesen, aus Toren, Assists oder Rückennummern auf eine feinere
Rolle zu schließen. Das wurde bewusst **verworfen**: Es wäre geraten, nicht
gemessen. Vier korrekte Gruppen sind besser als sechs scheinpräzise.

Sollte API-Sports später genauere Positionsdaten liefern, ist die Erweiterung
lokal: `POSITION_GROUPS` und `RADAR_PROFILES` in `player_metrics.py` ergänzen.
Der Rest des Systems bleibt unverändert.

---

## 5. Metrik-Katalog

Jede Kennzahl in `METRICS` hat:

| Feld | Bedeutung |
|---|---|
| `key` | eindeutiger Bezeichner, auch i18n-Schlüssel |
| `label` | deutscher Anzeigename |
| `kind` | `per90`, `rate`, `total` oder `value` |
| `direction` | `higher_better` oder `lower_better` |
| `description` | Kurzdefinition für das Info-Icon im UI |
| `source` | Pfad im API-Objekt, z. B. `("tackles", "total")` |
| `numerator` / `denominator` | nur bei `kind == "rate"` |

### Regeln

1. **Keine Kennzahl ohne nachweisbare Datenquelle.** Abgesichert durch
   `test_jede_metrik_hat_eine_datenquelle`.
2. **Kennzahlen, die API-Sports nicht liefert, existieren hier nicht.**
   Das betrifft ausdrücklich: xG, xA, progressive Pässe, progressive Carries,
   Pressures, Shot-Creating Actions, getrennte Luftzweikämpfe, Trackingdaten.
   Diese werden **nicht** geschätzt und **nicht** durch fachlich andere
   Kennzahlen ersetzt.
3. **Weniger, gut erklärte Kennzahlen schlagen viele unklare.** Auswahlkriterium
   war nicht „was liefert die API", sondern „was hilft beim Vergleich wirklich".

### Sonderfall `passes.accuracy`

API-Sports liefert dieses Feld **uneinheitlich**: in manchen Ligen als Prozentwert
(0–100), in anderen als absolute Anzahl angekommener Pässe. Ein Wert von 431 ist
offensichtlich keine Quote.

Lösung: `_plausible_percentage()` verwirft alles außerhalb 0–100 und gibt `None`
zurück. Lieber keine Passquote als eine falsche.

---

## 6. Radar-Profile

Pro Positionsgruppe sind **6 bis 8 Achsen** definiert. Die Obergrenze ist durch
einen Test abgesichert (`test_radar_profile_haben_hoechstens_acht_achsen`).

Begründung: Mehr Achsen werden auf einem Smartphone unlesbar und verbessern den
Vergleich nicht – sie verschlechtern ihn, weil das Auge keine Form mehr erkennt.

---

## 7. Wahl der Hauptliga

Ein `/players`-Eintrag enthält mehrere `statistics`-Blöcke: einen pro Wettbewerb
(Liga, Pokal, Champions League) und teils mehrere pro Verein.

**Entscheidung:** Ausgewertet wird ausschließlich die **Liga mit den meisten
Einsatzminuten**. Innerhalb dieser Liga werden mehrere Vereinseinträge summiert
(Vereinswechsel im Winter).

### Warum nicht alle Wettbewerbe summieren?

Der spätere Perzentil-Referenzpool besteht aus **Ligaspielern**. Würde man
Pokal- und Europapokalminuten hinzuaddieren, wäre der Spielerwert nicht mehr mit
dem Pool vergleichbar – das Perzentil wäre systematisch verzerrt.

**Preis dieser Entscheidung:** Pokal- und CL-Leistungen tauchen im Vergleich
nicht auf. Das ist bewusst gewählt und muss im UI erkennbar sein.

### Vergleichsligen

Nur die Top-5: `bl1`, `pl`, `pd`, `sa`, `fl1`. Nur dort entsteht ein sinnvoller
Referenzpool. Spielt ein Spieler in keiner davon, ist `data_available = False`.

---

## 8. Zwei Vergleichsmodi

`build_comparison()` entscheidet automatisch:

| Modus | Bedingung | Radar |
|---|---|---|
| `position` | beide Spieler in derselben Positionsgruppe | ja |
| `general` | unterschiedliche oder unbekannte Gruppen | **nein** |

Ein gemeinsames Radar über Torwart und Stürmer wäre fachlich irreführend –
die Achsen hätten für beide eine völlig andere Bedeutung. Im `general`-Modus
werden deshalb nur universell verständliche Grunddaten verglichen
(Einsätze, Minuten, Tore, Assists, Rating, Passquote, Zweikampfquote, Karten).

**Es gibt bewusst keinen Gesamtscore.** Unterschiedliche Rollen lassen sich
nicht auf eine einzige Zahl reduzieren, ohne zu lügen.

---

## 9. Perzentile und Referenzpool

### Warum ein eigener Importjob

Der API-Sports-Endpunkt `/players` liefert **20 Einträge pro Seite**. Eine
Top-5-Liga hat rund 500–620 Spieler, also 26–31 Seiten. Für alle fünf Ligen
einer Saison sind das **136–149 Requests**. Mit sicherer Drosselung
(2 Requests/Sekunde) dauert das gut eine Minute.

Das gehört nicht in eine Nutzeranfrage. Deshalb: `refresh_players.py` als
CLI-Job, analog zu `refresh_historical.py`. Die Webanwendung **liest nur**,
sie importiert nie.

### Ablageorte

| Pfad | Inhalt | Im Git? |
|---|---|---|
| `data/player_pool/status.json` | Importstatus pro Liga+Saison | nein |
| `data/player_pool/pool_{liga}_{saison}.json` | Referenzdaten einer Liga | nein (zu groß) |
| `data/player_pool/import.lock` | Sperre gegen Doppelimporte | nein |
| `data/percentiles/percentiles_{saison}.json` | fertiger Snapshot | **ja** |

Der Snapshot ist mit rund 35 KB klein genug fürs Repository. Dadurch liegen
die Perzentile nach einem `git pull` auf dem Server sofort vor – dort muss
nichts importiert werden.

### Speicherformat: Quantil-Stützstellen

Statt aller Rohwerte werden pro Positionsgruppe und Kennzahl **101
Stützstellen** gespeichert (P0 bis P100).

Alternative wäre gewesen, alle Rohwerte abzulegen. Verworfen, weil der
Snapshot dann mehrere Megabyte groß und nicht mehr git-tauglich wäre. Eine
Auflösung von einem Prozentpunkt ist für ein Radar mehr als ausreichend.

### Gleichstände

Viele Kennzahlen häufen sich bei niedrigen Werten (etwa Blocks pro 90 bei
Offensivspielern). Deshalb wird der **Mid-Rank** verwendet: der Mittelwert aus
unterer und oberer Einordnung. Sonst ergäbe derselbe Wert je nach Rechenweg
einmal das 0. und einmal das 40. Perzentil.

### Mindestminuten

`DEFAULT_MIN_MINUTES = 450` – fünf volle Spiele.

Begründung: Darunter sind Per-90-Werte nicht belastbar. Ein Spieler mit 45
Minuten und einem Tor hätte 2,0 Tore/90 und würde jede Verteilung verzerren.

**Produktentscheidung, bewusst als MVP-Wert konfigurierbar gelassen.** Sobald
die ersten vollständigen Pools vorliegen, ist anhand der echten Verteilung zu
prüfen, ob 450 zu streng ist (Alternative 360) oder zu mild (Alternative 540).

Die Grenze gilt in **beide Richtungen**: Ein Spieler unter der Schwelle kommt
nicht in den Pool **und** bekommt selbst kein Perzentil
(`percentile_blocked_a = "below_min_minutes"`). Ihn einzuordnen würde eine
Belastbarkeit vortäuschen, die seine Stichprobe nicht hergibt.

### Mindestgröße der Gruppe

`MIN_POOL_SIZE = 30`. Darunter entsteht **keine** Verteilung – ein Perzentil
aus 12 Spielern wäre reines Rauschen.

### Vollständigkeit des Pools

Ein Snapshot entsteht **nur**, wenn alle fünf Ligen `complete` sind.
`is_snapshot_complete()` prüft das. Perzentile aus einem halb geladenen Pool
wären schlimmer als gar keine, weil sie Präzision vortäuschen.

Während eines laufenden Reimports bleibt der alte Snapshot aktiv. Er wird erst
ersetzt, wenn der neue vollständig berechnet ist – atomar über
`os.replace()`, damit ein parallel lesender Gunicorn-Worker nie eine halb
geschriebene Datei sieht.

### Vergleichsgruppe im allgemeinen Modus

Auch bei Torwart gegen Stürmer bekommt **jeder Spieler Perzentile gegen seine
eigene Positionsgruppe**. Die Tore eines Stürmers werden an Stürmern gemessen,
die eines Außenverteidigers an Verteidigern. Beide gegen dieselbe Gruppe zu
messen wäre unfair und irreführend.

Das UI muss immer benennen, welcher Pool verwendet wurde – `describe_pool()`
liefert dafür Saison, Ligen, Mindestminuten und Gruppengröße.

---

## 10. Sperre und Wiederaufnahme

**Lock:** `data/player_pool/import.lock` enthält PID und Startzeitpunkt. Ein
Lock, dessen Prozess nicht mehr läuft oder der älter als eine Stunde ist, gilt
als verwaist und wird übernommen. Sonst würde ein Absturz den Import dauerhaft
blockieren. Freigabe immer im `finally`-Zweig.

**Resume:** Bricht ein Lauf ab (Rate-Limit, Netzwerkfehler), bleiben die
geladenen Seiten erhalten. Ein erneuter Aufruf setzt fort. Bei ~30 Requests pro
Liga ist das den kleinen Mehraufwand wert. `--force` lädt bewusst alles neu.

**Testbarkeit:** `import_league()` bekommt den Seitenabruf als Parameter
injiziert. Dadurch ist der komplette Ablauf inklusive Abbruch und Wiederaufnahme
ohne Netzwerk testbar – und die Flask-Anwendung kann das Modul lesen, ohne je
einen Import auszulösen.

---

## 11. Regeln, die nicht verletzt werden dürfen

1. `player_stats_loader.py` (Transfervergleich) wird nicht verändert.
2. `_get()` in `apisports_api.py` wird nicht verändert – für Paginierung gibt es
   `_get_full()`.
3. Kein fehlender Wert wird zu 0.
4. Keine Kennzahl ohne API-Feld.
5. Kein gemeinsames Radar über verschiedene Positionsgruppen.
6. Kein vollständiger Ligaimport innerhalb eines Nutzerrequests.
7. Keine Perzentile aus einem unvollständigen Pool.
8. Kein Perzentil für Spieler unter der Mindestminutengrenze.
9. Radar: maximal 8 Achsen.
10. Jedes angezeigte Perzentil nennt seine Vergleichsgruppe.

---

## 12. Eine neue Kennzahl hinzufügen

1. In `METRICS` eintragen – mit `source` (oder `numerator`/`denominator`),
   `kind`, `direction` und einer verständlichen `description`.
2. Prüfen, dass das API-Feld in `SUMMABLE_FIELDS` oder `WEIGHTED_FIELDS`
   in `player_compare_loader.py` enthalten ist, sonst wird es nicht aggregiert.
3. Falls sie ins Radar soll: in `RADAR_PROFILES` der passenden Gruppe ergänzen
   und dabei die Obergrenze von 8 Achsen einhalten.
4. Test ergänzen.

Die bestehenden Tests fangen die häufigsten Fehler automatisch ab: fehlende
Datenquelle, Kennzahl nicht im Katalog, zu viele Radarachsen.

---

## 13. Importjob bedienen

```bash
# Stand ansehen (keine Requests)
py refresh_players.py --report --season 2024

# Eine Liga
py refresh_players.py --league bl1 --season 2024

# Alle fünf Ligen (~136-149 Requests, gut eine Minute)
py refresh_players.py --all --season 2024

# Nach Abbruch: setzt automatisch fort
py refresh_players.py --all --season 2024

# Alles neu laden
py refresh_players.py --all --season 2024 --force

# Nur den Snapshot neu berechnen (keine Requests)
py refresh_players.py --snapshot --season 2024

# Mit anderer Mindestminutengrenze experimentieren
py refresh_players.py --snapshot --season 2024 --min-minutes 360
```

Nach einem erfolgreichen Lauf gehört `data/percentiles/percentiles_{saison}.json`
ins Repository. Die Rohpools unter `data/player_pool/` bleiben lokal.

### Wo importieren?

Beides möglich. Lokal importieren und den Snapshot committen ist der ruhigere
Weg: der Server bekommt die fertigen Perzentile per `git pull`, ohne selbst
Requests zu verbrauchen.

### Laufende Saison

Für abgeschlossene Saisons genügt ein einmaliger Import. Für die laufende
Saison ist ein wöchentlicher Lauf sinnvoll:

```bash
0 3 * * 1 cd /root/footsim && venv/bin/python refresh_players.py --all --season 2025
```

---

## 14. HTTP-Schnittstelle (Etappe 3)

Drei Routen in `app.py`. Bewusst schmal gehalten, damit der Monolith nicht weiter
wächst als nötig.

| Route | Zweck | API-Requests |
|---|---|---|
| `GET /api/player-seasons` | wählbare Saisons, Ligen, Mindestlänge der Suche | **0** |
| `GET /api/player-search?q=&season=` | Namenssuche | 1 (dann 6 h Cache) |
| `GET /api/player-compare?a=&b=&season_a=&season_b=` | Vergleich zweier Spieler | 2 (dann aus Cache) |

### Unterschiedliche Saisons sind erlaubt

`season_a` und `season_b` dürfen abweichen. „Musiala 2023/24 gegen Musiala 2025/26"
ist ein sinnvoller Vergleich. Jeder Spieler wird dann gegen den Perzentil-Pool
**seines eigenen Jahrgangs** gemessen – ein Snapshot pro Saison.

### Fehlerbehandlung

Rate-Limit und Ausfall der Datenquelle werden getrennt behandelt und liefern
verständliche Meldungen statt eines 500ers:

- `429` – Tageskontingent aufgebraucht
- `503` – Datenquelle nicht erreichbar
- `400` – ungültige Eingabe (zu kurz, unmögliche Saison, gleiche Spieler-ID)

### Warum die Suche schon alles mitliefert

`/api/player-search` gibt pro Treffer bereits Foto, Verein, Liga, Position,
Alter und Minuten zurück. Ein zweiter Request pro Treffer wäre bei zehn
Ergebnissen zehnmal so teuer. Wählt der Nutzer dann einen Spieler aus, trifft
der Statistikaufruf denselben Cache-Eintrag, den die Suche erzeugt hat.

---

## 15. Frontend (Etappen 4 bis 6)

Alles in `static/script.js` unter dem Präfix `pc`. Kein Framework, keine
neue Abhängigkeit.

### Suche

| Anforderung | Umsetzung |
|---|---|
| Entprellung | `clearTimeout` + `setTimeout` mit `PC_SEARCH_DELAY` |
| veraltete Antworten | `requestId` je Slot, alte Antworten werden verworfen |
| Tastatur | Pfeiltasten, Enter, Escape über `pcHandleKeydown` |
| Screenreader | `role="combobox"`, `aria-expanded`, `aria-controls`, `role="listbox"` |
| Zustände | Laden, keine Treffer, Fehler – jeweils eigener Text |

Nicht vergleichbare Spieler (keine Top-5-Liga in der Saison) erscheinen in der
Liste, aber als nicht auswählbar markiert. Sie stillschweigend wegzulassen wäre
verwirrend: der Nutzer würde den Spieler suchen und nicht finden.

### Radar

Echtes SVG über `createElementNS`, kein `innerHTML`. Skaliert über `viewBox`.

Sicherheitsregeln:
- Unter drei verwertbaren Achsen wird **kein** Radar gezeichnet, sondern ein
  Hinweis. Zwei Achsen ergeben keine Fläche, sondern eine Linie.
- Fehlende Perzentile werden nicht als Null gezeichnet.
- `role="img"` mit Beschriftung, die auf die Werteliste darunter verweist.

Das Radar ist **nie** die einzige Darstellung. Darunter steht immer die
vollständige Liste mit Rohwerten – zugänglich und ohne Farbwahrnehmung lesbar.

### Zusammenfassung

Rein deterministisch aus den angezeigten Zahlen. Kein Modell, keine KI.

Ein Vorsprung gilt ab **10 Perzentilpunkten** Abstand. Diese Schwelle wird dem
Nutzer im Text genannt, damit die Aussage nachvollziehbar bleibt.

### Ehrlichkeit bei fehlenden Daten

Der Hinweiskasten über dem Vergleich unterscheidet vier Fälle:

1. **Kein Snapshot** – „Rohwerte stimmen, nur die Einordnung fehlt"
2. **Unvollständiger Pool** – Warnung, dass nicht alle fünf Ligen geladen sind
3. **Spieler unter Mindestminuten** – wird benannt, Rohwerte bleiben sichtbar
4. **Alles vorhanden** – Erklärung, was P75 konkret bedeutet

---

## 16. Testabdeckung

| Datei | Tests | Ebene |
|---|---|---|
| `test_player_comparison.py` | 48 | Metriken, Positionen, Aggregation |
| `test_player_pool.py` | 45 | Quantile, Import, Lock, Snapshot |
| `test_player_routes.py` | 30 | Suche, HTTP-Routen, Frontend-Konsistenz |

Die dritte Gruppe ist ungewöhnlich für Python-Tests: sie prüft, ob HTML, CSS und
JavaScript zusammenpassen. Damit wird eine Fehlerklasse abgefangen, die zur
Laufzeit still bleibt – eine ID im JavaScript, die im HTML nicht existiert,
liefert einfach `null` und bricht erst später an unerwarteter Stelle ab.

Konkret abgesichert:
- jede `el("pc-…")`-ID existiert im HTML
- Suchfelder haben Label und vollständige ARIA-Auszeichnung
- Entprellung und Race-Condition-Schutz sind implementiert
- Radar nutzt echtes SVG
- Service-Worker-Version wurde erhöht
- kein `localStorage` oder `sessionStorage` im Frontend

---

## 14. Phase 3.1 – Positionslogik, General-Radar, Scatter-Vorbereitung

### 14.1 Das Radar verschwindet nie mehr

Bis Phase 3 galt: unterschiedliche Positionen → kein Radar, nur eine Tabelle.
Das war fachlich sauber, aber als Produkt schlecht: der Nutzer bekam ohne
erkennbaren Grund eine andere Darstellung.

**Neue Regel:** `radar_enabled` ist immer `True`. Was sich ändert, sind die
Achsen — nicht die Existenz des Radars.

| Fall | `mode` | `radar_profile` |
|---|---|---|
| gleiche Positionsgruppe | `position` | die jeweilige Position |
| unterschiedliche oder unbekannte Gruppe | `general` | `POSITION_GENERAL` |

`build_comparison()` liefert zusätzlich `radar_profile` und
`radar_profile_label`, damit das Frontend die Überschrift nicht selbst
herleiten muss.

### 14.2 POSITION_GENERAL ist keine Position

`POSITION_GENERAL = "General"` steht **nicht** in `POSITION_GROUPS`.

Das ist wichtig: stünde es dort, würden zwei Spieler mit unbekannter Position
von `same_position_group()` fälschlich als vergleichbar gemeldet. Es bezeichnet
ausschließlich ein Radar-Profil, keine Spielerposition.

Abgesichert durch `test_general_ist_keine_echte_position`.

### 14.3 Das General-Profil enthält keine Saisonsummen

```
goals_per90 · assists_per90 · passes_per90
pass_accuracy_pct · duels_won_pct · rating
```

Alle Einträge sind `per90`, `rate` oder `value` — bewusst **keine** absoluten
Werte wie `minutes`, `goals` oder `appearances`.

Grund: Ein Spieler mit 3000 Minuten hätte bei absoluten Werten allein durch
Einsatzzeit die größere Radarfläche als ein gleichwertiger Spieler mit 1500
Minuten. Das Radar würde Verfügbarkeit messen statt Qualität.

Zwei Tests sichern das ab: `test_general_profil_enthaelt_keine_absoluten_saisonwerte`
und `test_general_profil_taugt_fuer_jede_position`.

### 14.4 GENERAL_METRICS ist ein Alias

```python
GENERAL_METRICS = RADAR_PROFILES[POSITION_GENERAL]
```

Keine zweite Liste. Radar und Detailtabelle müssen zwingend dieselben
Kennzahlen zeigen — zwei getrennte Listen würden auseinanderlaufen, sobald
jemand nur eine davon anpasst.

### 14.5 Torwart-Profil geändert

`rating` wurde durch `fouls_committed_per90` ersetzt. `rating` ist bereits im
General-Profil enthalten und als eigene Achse im Positionsradar wenig
aussagekräftig — es ist ein Aggregat, keine Einzelfähigkeit.

### 14.6 Positionslogik in der Suche

Der Nutzer wählt **keine** Position aus. Der Ablauf:

1. Spieler A suchen und wählen → seine Position wird zur Referenz
2. Bei Spieler B werden weiterhin **alle** Treffer angezeigt
3. Treffer derselben Gruppe stehen oben, tragen eine farbige Kante links
   und das Label „gleiche Position"
4. Vor dem ersten abweichenden Treffer steht eine Trennlinie:
   „Andere Position · allgemeiner Vergleich"

Abweichende Positionen werden **nicht** ausgeblendet oder gesperrt. Wer sie
wählt, bekommt automatisch den allgemeinen Vergleich — mit deutlicher
Beschriftung über dem Radar.

### 14.7 Tausch-Button

`pcSwapPlayers()` vertauscht Spieler und Saison beider Slots. Rein im Frontend,
kein API-Request — an den Daten ändert sich nichts, nur an ihrer Zuordnung zu
Farbe und Reihenfolge.

Zwei Details, die leicht übersehen werden:
- Laufende Suchanfragen werden über `requestId++` entwertet, sonst überschreibt
  eine spät eintreffende Antwort den gerade getauschten Zustand.
- Ein bereits sichtbares Ergebnis wird verworfen, weil es zur neuen Reihenfolge
  nicht mehr passt.

### 14.8 Scatter-Vorbereitung

`build_pool_entry()` speichert zusätzlich `age` und `team_name`.

Beide werden für Perzentile **nicht** gebraucht. Sie liegen im Pool, damit ein
späterer Scatter-Plot nach Alter und Verein filtern kann, ohne den Pool neu zu
importieren — das kostet rund 140 API-Requests je Saison.

Damit sind alle geplanten Filterdimensionen im Pool vorhanden:

| Dimension | Quelle |
|---|---|
| X-Achse, Y-Achse | jede Kennzahl aus `METRICS` |
| Liga | `league_code` |
| Saison | Dateiname des Pools |
| Position | `position` |
| Alter | `age` |
| Minuten | `minutes` |
| Team | `team_name` |

Ein Scatter-Endpunkt liest künftig nur den vorhandenen Pool. Kein neuer
API-Zugriff, keine Strukturänderung.

**Altbestand:** Ein vor Phase 3.1 importierter Pool hat `age`/`team_name` nicht.
`refresh_players.py --report` erkennt das und weist darauf hin. Perzentile
funktionieren weiterhin; für die Filterdimensionen ist einmalig
`--all --season <jahr> --force` nötig.

---

## 15. Phase 3.1 UX-Fix – Positionsnavigation und verständliche Sprache

### 15.1 Positionsgruppe ist der erste Schritt

Über der Suche steht eine Tablist mit fünf Optionen: Mittelfeld, Sturm,
Abwehr, Tor, Alle Positionen. Voreingestellt ist Mittelfeld.

Die Auswahl ist **kein Filter zur Zierde**, sondern bestimmt:
- welche Treffer in beiden Suchfeldern erscheinen
- welches Radarprofil der Vergleich verwendet

Vorher konnte der Nutzer unbeabsichtigt Kane gegen Hakimi vergleichen. Jetzt
ist ein positionsübergreifender Vergleich eine bewusste Entscheidung.

### 15.2 Gefiltert wird im Frontend – bewusst

Die Alternative wäre ein `position`-Parameter an `/api/player-search` gewesen.
Dagegen sprach der Cache:

Der Suchcache-Schlüssel lautet
`apisports:playersearch:{query}:{season}:{league}`. Ein Positionsparameter
müsste dort hinein, sonst lieferte der Cache falsche Treffer. Damit würde
dieselbe Suche für jede Positionsgruppe erneut gegen API-Sports laufen —
fünf Liga-Requests pro Gruppe statt einmal für alle.

Die Suchantwort enthält `position` bereits je Treffer. `pcFilterByPosition()`
reduziert sie im Frontend. Ein Wechsel der Positionsgruppe kostet dadurch
**null** zusätzliche API-Requests.

Das entspricht dem SC-Freiburg-Prinzip: einmal abrufen, cachen, danach
filtern.

### 15.3 Wechsel der Gruppe verwirft die Auswahl

Andernfalls bliebe ein Mittelfeld-Radar sichtbar, während oben „Sturm" aktiv
ist. `pcSetPosition()` ruft `pcResetSelection()` und meldet:

> Auswahl zurückgesetzt, weil du eine andere Positionsgruppe gewählt hast.

Wichtig dabei: `requestId++` je Slot entwertet laufende Suchen. Ohne das
poppt nach dem Wechsel noch eine Trefferliste der alten Gruppe auf.

### 15.4 Freier Vergleich erzwingt das General-Radar

`build_comparison(..., force_general=True)`, ausgelöst durch `?mode=general`
an `/api/player-compare`.

Ohne diesen Parameter hinge die Darstellung davon ab, ob der Nutzer im freien
Modus zufällig zwei Mittelfeldspieler gewählt hat — das Radar würde ohne
erkennbaren Grund die Achsen wechseln.

### 15.5 „Perzentil" verschwindet aus der Oberfläche

Der Fachbegriff steht nur noch in Erklärtexten und in dieser Dokumentation.

| vorher | jetzt |
|---|---|
| `P87` | `87/100`, Tooltip „Besser als 87 % der Vergleichsgruppe" |
| „Ohne Perzentile" | „Vergleichsrang noch nicht verfügbar" |
| „(ohne Perzentile)" im Saison-Dropdown | „(nur Rohwerte)" |
| „Was ein Perzentil hier bedeutet" | „Wie der Vergleichsrang zu lesen ist" |

Der Hinweis bei fehlendem Pool sieht nicht mehr wie ein Fehler aus:

> Aktuell siehst du die reinen Saisonwerte. Für die Einordnung gegenüber
> anderen Spielern fehlen noch vorbereitete Vergleichsdaten.

### 15.6 Texte liegen zentral in PC_TEXT

Das i18n-System aus Phase 2.1 wurde zurückgerollt; es gibt kein `t()`.
Damit neue Texte nicht wieder über die ganze Datei verstreut werden, liegen
sie gebündelt in `PC_TEXT` in `static/script.js`.

Wird i18n später erneut eingeführt, muss nur dieses Objekt gegen
Übersetzungsaufrufe getauscht werden — die Aufrufer bleiben unverändert.

### 15.7 Mehr als zwei Spieler: bewusst in Phase 3.2

`PC_SLOTS = ["a", "b"]` wurde eingeführt, damit neue Logik über die Slots
iteriert statt `a` und `b` hart zu adressieren. `pcResetSelection()` und
`pcSwapPlayers()` nutzen das bereits.

Die vollständige Mehrspielerfunktion bleibt aber Phase 3.2, weil sie
gleichzeitig betrifft:

- **Farben** — zwei feste Konstanten müssten zu einer Palette werden
- **Radarflächen** — bei vier Spielern überlagern sich die Flächen
  unlesbar; es bräuchte Umriss-Modus oder Ein-/Ausblenden je Spieler
- **Detailbalken** — das zweizeilige Layout müsste zu n Zeilen werden
- **Zusammenfassung** — „A liegt vorne bei…" ist ein Paarvergleich und
  funktioniert bei vier Spielern nicht mehr
- **Layout** — vier Suchslots passen mobil nicht nebeneinander

Das ist ein eigener Umbau, keine Erweiterung. Eine halbfertige Variante wäre
schlechter als die stabile Zwei-Spieler-Funktion.
