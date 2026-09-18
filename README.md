# FootSim

> Fußball-Simulation und -Analyse: Spiele simulieren, Ligen vergleichen, Spieler gegenüberstellen und in Streudiagrammen einordnen, alles auf Basis echter Saisondaten.

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue)]()
[![Tests](https://img.shields.io/badge/tests-4000%2B%20passing-brightgreen)]()
[![PWA](https://img.shields.io/badge/PWA-installierbar-blueviolet)]()

**Live:** [footsim.de](https://www.footsim.de)

---

## Inhalt

- [Über FootSim](#über-footsim)
- [Features](#features)
- [Der Spielerbereich](#der-spielerbereich)
- [Architektur](#architektur)
- [Player Pool und Importlogik](#player-pool-und-importlogik)
- [Caching](#caching)
- [API-Endpunkte](#api-endpunkte)
- [Projektstruktur](#projektstruktur)
- [Tech-Stack](#tech-stack)
- [Installation](#installation)
- [Player Pool befüllen](#player-pool-befüllen)
- [Datenquellen](#datenquellen)
- [PWA](#pwa)
- [Entwicklung](#entwicklung)
- [Champions-League-ML (Schattenbetrieb)](#champions-league-ml-schattenbetrieb)
- [Roadmap](#roadmap)
- [Lizenz](#lizenz)

---

## Über FootSim

FootSim vereint Monte-Carlo-Simulation, Ligavergleiche, Transferanalysen und
einen datenbasierten Spielervergleich in einer mobil-optimierten Anwendung.
Alle Werte stammen aus echten Saisondaten, keine geschätzten oder erfundenen
Kennzahlen. Fehlt ein Wert, wird das offen angezeigt statt mit einer Null
kaschiert.

Gebaut als PWA: installierbar auf dem Smartphone, Offline-Fallback für bereits
geladene Inhalte, native App-Anmutung auf Mobile.

## Features

| Bereich | Beschreibung | Status |
|---|---|---|
| **Spielsimulation** | Monte-Carlo-Simulation einzelner Partien mit Wahrscheinlichkeiten | ✅ |
| **Saisonsimulation** | Komplette Liga durchsimulieren, Meisterwahrscheinlichkeiten | ✅ |
| **Tabellen & Torjäger** | Aktuelle Tabellen und Torschützenlisten | ✅ |
| **Ligavergleich** | Bis zu fünf Ligen anhand realer Kennzahlen gegenüberstellen | ✅ |
| **Champions-League-Vergleich** | Ligen anhand ihrer CL-Performance vergleichen | ✅ |
| **Transfervergleich** | Sommertransfers zweier Quelligen in eine gemeinsame Zielliga | ✅ |
| **Spielervergleich – Radar** | Zwei Spieler positionsbasiert, mit Wettbewerbsumfang und Vergleichsrang | ✅ |
| **Spielervergleich – Plots** | Streudiagramm über hunderte Spieler, zwei frei wählbare Achsen | ✅ |
| **PDF Merge** | Werkzeug zum Zusammenführen von PDF-Dateien | ✅ |
| **PWA** | Installierbar, Offline-Fallback, Safe-Area-Unterstützung | ✅ |

## Der Spielerbereich

Der Spielerbereich beginnt mit einer Auswahl zwischen zwei Ansichten:

```
Bottom-Navigation "Spieler"
        │
        ├── Radar   → zwei Spieler im Detail vergleichen
        └── Plots   → viele Spieler auf zwei Kennzahlen einordnen
```

Beide Ansichten teilen sich Position, Saison und die gewählten Spieler.
Ein Wechsel verliert keine Einstellung.

### Wettbewerbsumfang

Radar und Plots verwenden dieselbe Wettbewerbslogik. Vier Modi:

| Modus | Enthält | Anmerkung |
|---|---|---|
| **Alle Vereinswettbewerbe** *(Standard)* | Liga, nationale Pokale, Champions/Europa/Conference League, Supercups | vollständigstes Saisonbild |
| Nur Liga | ausschließlich die nationale Liga | fairster Vergleich: gleiche Gegner, gleiche Anzahl Partien |
| Nur Nationalmannschaft | Länderspiele, WM, EM, Nations League | kleine Stichprobe, wird als solche gekennzeichnet |
| Alle Wettbewerbe | Verein + Nationalmannschaft | mischt sehr unterschiedliche Niveaus |

**Aggregation ist mathematisch korrekt umgesetzt:** Absolute Zähler werden
summiert, Per-90-Werte anschließend aus den summierten Rohwerten und der
Gesamtminutenzahl **neu berechnet**, nicht gemittelt. Quoten entstehen aus
Zähler und Nenner, nicht als Mittelwert einzelner Quoten. Ratings werden
minutengewichtet zusammengeführt.

### Radar

Positionsabhängige Achsen (Torwart, Abwehr, Mittelfeld, Angriff) oder ein
positionsübergreifendes Profil, wenn Spieler verschiedener Gruppen verglichen
werden. Das Radar verschwindet dabei nie; es wechselt nur die Achsen und
benennt den Modus deutlich.

Zusätzlich zum Rohwert zeigt jede Kennzahl einen **Vergleichsrang** gegenüber
einer Referenzgruppe (`87/100` = besser als 87 % der Vergleichsgruppe). Der
Fachbegriff „Perzentil" erscheint nur in Erklärtexten, nicht als
Hauptbotschaft.

### Plots

Ein Punkt = ein Spieler. Frei wählbare X- und Y-Achse aus 27 Kennzahlen,
Filter für Position, Wettbewerbsumfang, Ligen und Mindestminuten.

**Ablauf:**

```
Plots öffnen → X-Achse → Y-Achse → Datenbasis → Position
→ Ligen → Mindestminuten → [ Plot erstellen ] → Punktwolke
```

Der Plot entsteht über einen sichtbaren Primary-Button, nicht automatisch.
Grund: Jeder Request liest den kompletten Pool und aggregiert neu. Bei sieben
Filtern würde Automatik Requests für Zwischenzustände auslösen, die niemand
sehen wollte. Außerdem bliebe unklar, ob das gezeigte Bild zu den aktuellen
Filtern gehört.

| Zustand | Button |
|---|---|
| noch kein Plot | **Plot erstellen**, aktiv |
| Plot da, Filter unverändert | *Plot aktualisieren*, deaktiviert |
| Plot da, Filter geändert | **Plot aktualisieren**, aktiv; alte Punktwolke wird sichtbar abgeblendet |
| lädt gerade | deaktiviert, `aria-busy` |

Ein Doppelklick erzeugt keinen zweiten Request; veraltete Antworten werden
über einen Request-Zähler entwertet.

**Das Diagramm** hat Raster, beschriftete Skalen, Achsenlabels und eine
Regressionslinie (erst ab 8 Punkten, darunter wäre sie statistisch
bedeutungslos). Ligen sind farbcodiert mit Legende.

**Punkte sind anklickbar.** Ein Klick öffnet eine Detailkarte mit Name,
Verein, Liga, Position, Alter, Einsatzminuten, beiden Achsenwerten und dem
verwendeten Wettbewerbsumfang. Sie schließt über den Schließen-Button, Klick
außerhalb oder Escape, aber nie automatisch nach Zeit. Auf Mobil wird sie zum
festen Sheet über der Bottom-Navigation.

Im Radar gewählte Spieler sind automatisch hervorgehoben, und zwar über Farbe **und**
weiße Kontur und Größe, nie über Farbe allein. Die zusätzliche Spielersuche
steht unterhalb des Plots, ist als optional gekennzeichnet und erzeugt keinen
neuen Request; sie markiert nur bereits geladene Punkte.

## Screenshots

| Ansicht | Beschreibung |
|---|---|
| *(folgt)* | Startseite mit Simulation |
| *(folgt)* | Radar-Vergleich zweier Spieler |
| *(folgt)* | Streudiagramm mit hervorgehobenen Spielern |
| *(folgt)* | Detailkarte eines Spielerpunkts |
| *(folgt)* | Mobile-Ansicht |

## Architektur

```mermaid
flowchart TD
    Browser["Browser / PWA"] --> Flask["Flask (app.py)"]

    Flask --> Radar["Radar<br/>/api/player-compare"]
    Flask --> Scatter["Plots<br/>/api/player-scatter"]
    Flask --> Rest["Simulation, Ligen,<br/>Transfers"]

    Radar --> Loader["player_compare_loader.py<br/>Aggregation je Scope"]
    Scatter --> Pool["player_pool.py<br/>liest Pool, kein API-Call"]
    Radar --> Percentile["percentile_engine.py"]
    Percentile --> Pool

    Loader --> Cache["Disk-Cache<br/>data/cache/"]
    Rest --> Cache
    Cache --> APIs["football-data.org<br/>API-Sports"]

    Pool --> PoolFiles[("data/player_pool/")]
    Import["refresh_players.py<br/>gedrosselter Importjob"] --> PoolFiles
    Import --> APIs
```

**Kernprinzip:** Jeder externe API-Aufruf wird gecacht, bevor er in eine
Berechnung einfließt. Der Player Pool wird ausschließlich über einen separaten
Importjob befüllt, niemals innerhalb eines Nutzerrequests. Plots und Perzentile
lesen nur diesen Pool und lösen selbst **keinen einzigen API-Aufruf** aus.

## Player Pool und Importlogik

Der Player Pool ist ein persistenter Datensatz, **kein Cache**. Der
Unterschied ist wesentlich: Ein abgelaufener Cache lädt sich selbst nach,
beim Pool wären das 26–31 API-Requests pro Liga mitten im Nutzerrequest.
Deshalb löst ein veralteter Pool nichts aus; er gilt einfach als veraltet.

### Ein Pool, alle Wettbewerbsumfänge

Es gibt **einen** Pool pro Liga und Saison. Beim Import wird jeder Spieler
einmal abgerufen; aus derselben Rohantwort werden alle vier
Wettbewerbsumfänge berechnet und im Pooleintrag abgelegt:

```
data/player_pool/
├── status.json                Importstatus je Liga und Saison
├── pool_bl1_2025.json          Spieler mit Kennzahlen je Scope
├── pool_pl_2025.json
└── import.lock                 Schutz gegen parallele Importe
```

Keine separaten Pools je Modus. Ein Wechsel des Wettbewerbsumfangs kostet
dadurch **null zusätzliche API-Requests**.

### Import

```bash
python refresh_players.py --report                  # Status, ohne Requests
python refresh_players.py --league bl1 --season 2025
python refresh_players.py --all --season 2025       # ~140 Requests, ca. 1 Minute
```

Der Import ist gedrosselt (0,5 s zwischen Requests), fortsetzbar nach Abbruch
und durch ein PID-Lockfile gegen Doppelstarts geschützt. Ein Lock, der älter
als zwei Stunden ist, gilt als verwaist und wird überschrieben.

> **Hinweis:** Wurde vor der Wettbewerbsumfang-Erweiterung bereits importiert,
> ist ein einmaliger Neuimport nötig; der alte Pool kennt nur Ligadaten.
> `--report` weist darauf hin.

## Caching

| Ebene | Ort | Gültigkeit |
|---|---|---|
| API-Antworten (Ligen, Tabellen, Spieler) | `data/cache/` | je Endpunkt, abgeschlossene Saisons 1 Jahr |
| Spielerprofil (rohe API-Antwort, alle Wettbewerbe) | `data/cache/` | 1 Jahr / 24 h bei laufender Saison |
| Suchergebnisse | `data/cache/` | 6 Stunden |
| Scatter-Punktlisten | `data/cache/` | 1 Stunde, Schlüssel aus allen Filtern inkl. Scope |
| Player Pool | `data/player_pool/` | persistent, nur durch Import erneuert |

Der Cache ist dateibasiert und damit **workerübergreifend**. Bei mehreren
Gunicorn-Workern teilen sich alle Prozesse dieselben Daten.

## API-Endpunkte

| Endpunkt | Zweck | API-Requests |
|---|---|---|
| `GET /api/player-seasons` | wählbare Saisons, Ligen, Mindestlänge der Suche | keine |
| `GET /api/player-search` | Namenssuche ab 3 Zeichen | 5 (je Liga), 6 h gecacht |
| `GET /api/player-compare` | Radar-Vergleich zweier Spieler | 2, danach gecacht |
| `GET /api/player-scatter` | Punkte **und** alle Metadaten in einer Antwort | **keine** |

`/api/player-scatter` akzeptiert `x`, `y`, `position`, `leagues`, `season`,
`min_minutes` und `scope`. Die Antwort enthält zusätzlich den vollständigen
Achsenkatalog, alle Ligen, Positionen, Wettbewerbsumfänge sowie den
Poolstatus. Bewusst kein separater Metadaten-Endpunkt, weil das Frontend
beides für denselben Render-Schritt braucht.

## Projektstruktur

```
footsim/
├── app.py                       Flask-Routen, HTTP-Schicht
├── refresh_players.py           Gedrosselter Importjob für den Player Pool
├── src/
│   ├── api/
│   │   ├── apisports_api.py      API-Sports-Client
│   │   └── league_api.py         football-data.org-Client
│   ├── data/
│   │   ├── player_metrics.py     Metrikkatalog, Positionsgruppen, Per-90-Logik
│   │   ├── player_compare_loader.py  Scope-Aggregation, Suche, Vergleichsaufbau
│   │   ├── player_pool.py        Pool-Speicherung, Import, Scatter-Zugriff
│   │   ├── percentile_engine.py  Verteilungen und Vergleichsrang
│   │   └── transfer_loader.py    Transfervergleich
│   ├── features/                 Fachliche Berechnungen
│   ├── predict/                  Monte-Carlo-Simulation
│   └── utils/disk_cache.py       Workerübergreifender Dateicache
├── static/
│   ├── script.js                 Gesamte Frontend-Logik (Vanilla JS)
│   └── style.css                 Gesamtes Styling
├── templates/                    Jinja2-Templates
├── tests/                        über 4.000 automatisierte Tests
└── docs/player_comparison.md     Architekturdokumentation des Spielerbereichs
```

## Tech-Stack

| Bereich | Technologie |
|---|---|
| Backend | Python 3.9+, Flask, Gunicorn |
| Database | PostgreSQL, SQLite (local), UUIDv7 |
| ORM | SQLAlchemy, Flask-Migrate, Alembic |
| Frontend | Vanilla JavaScript, kein Framework |
| Darstellung | SVG (Radar und Streudiagramme) |
| Daten | football-data.org, API-Sports |
| Caching | Dateibasiert, workerübergreifend |
| Deployment | VPS, nginx, systemd |
| PWA | Service Worker, Web App Manifest |

## Installation

```bash
git clone https://github.com/eliemengi/footsim.git
cd footsim
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`.env` im Projektverzeichnis anlegen:

```env
FOOTBALL_API_KEY=dein_football-data.org_key
APISPORTS_KEY=dein_api-sports_key
```

Tests und Start:

```bash
pytest tests/ -q
python app.py
```

Die Anwendung läuft danach unter `http://127.0.0.1:5000`.

## Player Pool befüllen

Radar-Vergleiche funktionieren sofort. **Vergleichsrang und Plots brauchen den
Pool**. Ohne ihn zeigt FootSim ehrliche Rohwerte mit einem entsprechenden
Hinweis statt erfundener Werte.

```bash
python refresh_players.py --report
python refresh_players.py --all --season 2025
```

Auf dem Server:

```bash
cd /root/footsim
venv/bin/python refresh_players.py --all --season 2025
```

Der Import kostet etwa 140 API-Requests und dauert rund eine Minute.
Abgeschlossene Saisons müssen nur einmal geladen werden.

## Datenquellen

- **[football-data.org](https://www.football-data.org)**: Ligastruktur, Tabellen, Spielpläne
- **[API-Sports](https://www.api-football.com)**: Spielerstatistiken, Transfers

Beide APIs werden ausschließlich serverseitig angesprochen. Kein API-Key im
Frontend.

### Bekannte Grenzen der Datenquellen

Kennzahlen, die diese Quellen nicht liefern (etwa xG, xA, progressive Pässe,
PPDA oder Trackingdaten), existieren in FootSim **nicht** und werden auch nicht
geschätzt.

Weitere Einschränkungen, die bewusst nicht kaschiert werden:

- **Positionen** liefert API-Sports nur in vier Gruppen (Torhüter, Abwehr,
  Mittelfeld, Angriff). Feinere Rollen wie Innenverteidiger oder Sechser wären
  geraten, nicht gemessen; deshalb gibt es sie nicht.
- **`passes.accuracy`** kommt je nach Liga als Prozentwert oder als absolute
  Passanzahl. Werte außerhalb 0–100 werden verworfen statt als falsche Quote
  angezeigt.
- **Die Liga-Seitenabfrage** des Importjobs liefert teils nur den ligaeigenen
  Statistikblock. Dann sind „Alle Vereinswettbewerbe" und „Nur Liga" identisch,
  das ist korrekt und wird nicht künstlich aufgebauscht.
- **Fehlende Werte** bleiben leer und werden nie zu 0. Ein Spieler ohne
  Dribbelversuche hat keine Dribbelquote von 0 %, sondern gar keine.

## PWA

Installierbar über „Zum Startbildschirm hinzufügen". Updates kommen beim
nächsten Start automatisch, bedingt durch das Service-Worker-Lifecycle
gelegentlich erst beim übernächsten.

## Entwicklung

```bash
pytest tests/ -q                          # die vollständige Suite
pytest tests/test_player_scatter.py -v    # gezielt ein Modul
```

Architekturentscheidungen werden direkt bei der Umsetzung dokumentiert, nicht
nachträglich; siehe [`docs/player_comparison.md`](docs/player_comparison.md)
für den vollständigen Spielerbereich inklusive Aggregationsregeln,
Perzentillogik und Scatter-Architektur.

## Champions-League-ML (Schattenbetrieb)

FootSims Prognose beruht auf einem Poisson-Modell über Teamstärkeprofile.
Ergänzend existiert eine trainierte ML-Korrektur für die Champions League.
Sie ist **standardmäßig ausgeschaltet** und verändert ohne ausdrückliche
Konfiguration keine einzige Zahl.

### Was gebaut ist

| Schritt | Inhalt |
| --- | --- |
| Datensatz | Point-in-Time-Zeilen aus fünf Ligen (2023–2025) plus 503 Champions-League-Partien, streng ohne Zukunftswissen |
| Backtest | Training auf nationalen Ligaspielen, Test auf 213 CL-Partien, Walk-forward mit gepaartem Bootstrap |
| Modell | Versioniertes JSON-Bundle mit SHA-256-Integritätswert, 16 Teamprofilmerkmale |
| Inference | Laufzeitschicht mit strengem Loader und sicherem Rückfall auf die Baseline |
| Gewichtung | Geometrische Mischung: `λ = λ_baseline · Korrekturfaktor ^ Gewicht` |
| Integration | Eine Anbindungsstelle für Einzelspiel- und Saisonsimulation |
| Freigabe | Jedes Modellbundle trägt eine geprüfte Stufe: `shadow`, `experimental` oder `approved` |
| Provenienz | Fingerabdruck über Merkmale **und** Torergebnisse; Kennzahlen an das Messartefakt gebunden |

### Das Messergebnis ist INCONCLUSIVE

Der Backtest gegen echte Champions-League-Partien ergab:

```
Baseline  LogLoss 0.92977
ML        LogLoss 0.92087
delta            -0.00890     95-%-Intervall [-0.02986, +0.01135]
```

Der Punktschätzer ist besser, das Konfidenzintervall enthält aber die Null.
Über 213 Spiele lässt sich damit **nicht belegen**, dass das Modell in der
Champions League besser prognostiziert als die bestehende Berechnung. Beide
Testfolds zeigten in dieselbe Richtung und die Kalibrierung verbesserte sich
deutlich (0.048 → 0.016). Das sind Hinweise, kein Nachweis.

### Freigabestufe statt zweier Wahrheitswerte

Bis C0B trug jedes Bundle `shadow_only = true` und
`production_approved = false`, während dieselbe Korrektur über
`approach=ml` mit vollem Gewicht in die Nutzerprognose gerechnet wurde. Die
Metadaten sagten das eine, der Laufzeitpfad tat das andere.

An ihre Stelle tritt **ein** geprüftes Feld mit drei Stufen:

| Stufe | Bedeutung |
| --- | --- |
| `shadow` | darf gerechnet und protokolliert werden, verändert aber **kein** Nutzerergebnis |
| `experimental` | darf unter dem ausdrücklichen Produktvertrag aktiv wirken, ist aber nicht statistisch abschließend belegt |
| `approved` | vollständig freigegebene Modellgeneration |

Die Stufe ist kein Metadatum: Sie geht in die Modellkennung ein, der Loader
weist eine unbekannte Stufe ab, und `runtime.py` verweigert die Anwendung,
wenn sie den aktiven Betrieb nicht deckt.

**Das aktuelle Champions-League-Modell steht auf `experimental`.** In der
Oberfläche ist ML-Prognose der Standard; V0 bleibt bei jedem Fehler der
automatische Rückfall. Was hier ausdrücklich **nicht** behauptet wird: dass
die Verbesserung statistisch belegt oder das Modell uneingeschränkt
produktionsfreigegeben sei.

### Betriebsarten

Gesteuert über zwei Umgebungsvariablen, dokumentiert in
[`.env.example`](.env.example):

```bash
FOOTSIM_ML_MODE=off      # off | shadow | active
FOOTSIM_ML_WEIGHT=0.0    # 0.0 bis 1.0, nur in active wirksam
```

- **`off`**: Standard. Ausschließlich die bestehende Baseline. Es wird kein
  Modell geladen und keine ML-Funktion aufgerufen.
- **`shadow`**: Das Modell rechnet mit, die Diagnose steht in der
  API-Antwort, die Simulation benutzt weiterhin die Baseline.
- **`active`**: Die Simulation verwendet die gewichteten Werte, aber nur
  wenn Modell, Merkmale und Gewichtung alle getragen haben **und** die
  Freigabestufe des Bundles den aktiven Betrieb deckt.

Betriebsart und Freigabestufe sind zwei getrennte Bedingungen. Ein Bundle
auf `shadow` verändert auch in `active` kein Ergebnis; der Grund steht dann
als `model_stage_not_active` in der Antwort.

Das Gewicht läuft von `0.0` (reine Baseline) über `0.5` (geometrische
Mitte) bis `1.0` (volle Korrektur). Gemischt wird **geometrisch**, nicht
linear:

```
λ_blend = λ_baseline · Korrekturfaktor ^ Gewicht
```

Der Grund ist die Bauform des Modells: Die Korrektur ist ein Faktor auf
einem Poisson-λ, kein Summand. Eine lineare Interpolation ergäbe bei
Gewicht `0.5` und Faktor `4` das 2,5-fache statt des 2-fachen.

Eine Prozentangabe wie `50` wird
**nicht** als `0.5` gedeutet, sondern abgewiesen; ein Tippfehler soll
auffallen und nicht still die volle Korrektur einschalten.

### Sichere Rückfälle

Bei jedem Problem rechnet die Simulation mit der unveränderten Baseline und
liefert ein gültiges Ergebnis: fehlendes oder beschädigtes Modell, fehlende
Teamprofile, ungültiges Gewicht, Mannschaft ohne Historie, nicht
ausreichende Freigabestufe, unerwarteter Fehler in der ML-Kette. Der Grund
steht maschinenlesbar im Feld `ml` der Antwort.

Die nationalen Ligen und alle Nicht-CL-Wettbewerbe sind von der ML-Kette
vollständig unberührt.

### Lokal ausprobieren

```bash
# Datensatz mit Champions-League-Zeilen bauen
py run_ml.py --build-dataset --include-cl --output data/ml/dataset_with_cl.json

# Shadow-Backtest gegen echte CL-Partien
py run_ml.py --evaluate-cl --output data/ml/cl_shadow_backtest.json

# Modell trainieren und versioniert speichern.
# --evaluation ist Pflicht: Ein Bundle bekommt seine Kennzahlen
# ausschließlich aus einer echten, passenden Messung.
py run_ml.py --train-cl-model --dataset data/ml/dataset_with_cl.json \
             --evaluation data/ml/cl_shadow_backtest.json \
             --release-stage experimental \
             --model-output data/ml/models/cl_correction_model_v1.json

# Tests der gesamten ML-Kette
python -m pytest tests/test_ml_*.py -q
```

### Wählbare Berechnungsansätze (Backend)

> **Aktueller Stand:** drei Ansätze (`ml`, `custom`, `classic`) im
> Einzelspiel und in der Ligaphase, siehe Abschnitt V2-C23 weiter unten.
> Die folgenden zwei Abschnitte beschreiben den historischen Stand von
> C8A/C8B.

Die CL-Einzelspielsimulation nimmt seit C8A zwei optionale Ansätze
entgegen, **pro Request**, ohne dass eine Umgebungsvariable oder ein
anderer Nutzer davon berührt wird.

| `approach` | Bedeutung |
| --- | --- |
| *nicht gesetzt* | unverändertes bisheriges Verhalten, ML folgt der Umgebung |
| `ml` | volle ML-Korrektur, Faktoren neutral, ML-Gewicht `1.0` |
| `custom` | individuelle Faktoren, ML-Gewicht frei zwischen `0.0` und `1.0` |

Bei `custom` lassen sich drei fußballfachliche Größen verstellen:

| Faktor | Bereich | Standard | Wirkung |
| --- | --- | --- | --- |
| `attack` | 0.7 – 1.3 | 1.0 | multipliziert beide Angriffswerte |
| `defence` | 0.7 – 1.3 | 1.0 | höher = stärkere Abwehr, senkt beide Torerwartungen |
| `home_advantage` | 0.5 – 1.5 | 1.0 | verschiebt Heim gegen Auswärts, torneutral |
| `ml_weight` | 0.0 – 1.0 | 0.0 | Einfluss der ML-Korrektur |

Die Faktoren wirken auf **Kopien** der Teamprofile, bevor die
Torerwartung berechnet wird; der prozessweite Profilcache bleibt
unberührt. Die Rechenreihenfolge ist:

```
Profile → individuelle Faktoren → Torerwartung → ML-Korrektur → Simulation
```

Ungültige Werte werden serverseitig mit HTTP 400 abgewiesen, nicht
stillschweigend zurechtgebogen: Eine `50` wird nicht als `0.5` gedeutet.
Alle bestehenden Sicherheitsgrenzen und Rückfälle gelten unverändert
weiter; fällt die ML-Kette aus, rechnet die Simulation mit der
individualisierten Baseline.

Zwei Einschränkungen, die man kennen sollte: `attack` und `defence`
greifen im Torerwartungsmodell an derselben Größe an, und zwar beide gleich weit
zu verstellen hebt sich rechnerisch auf. Und die individuelle Steuerung
gilt zunächst **nur für CL-Einzelspiele**; die CL-Saisonsimulation und
die K.-o.-Runden sind davon nicht erfasst.

### Die Auswahl in der Oberfläche

Seit C8B ist die Auswahl sichtbar, ausschließlich bei der
**Champions-League-Einzelspielsimulation**, im Panel „Ausgewählt“ direkt
über dem Simulieren-Knopf. Bei jeder Liga bleibt dieser Bereich
unverändert; die neuen Felder erscheinen dort nicht und werden auch nicht
mitgesendet.

Zwei Karten stehen zur Wahl:

| Auswahl | Untertitel | Request |
| --- | --- | --- |
| **ML-Prognose** (Standard) | Historisch trainiertes mathematisches Modell | `approach: "ml"` |
| **Individuell** | Gewichte die Match-Faktoren selbst | `approach: "custom"` samt `factors` und `ml_weight` |

„Individuell“ blendet vier Regler ein. Sichtbar sind Prozentwerte, im
Request stehen die Backendwerte aus der Tabelle oben:

| Regler | Sichtbar | Neutral | Backendwert | Wirkung |
| --- | --- | --- | --- | --- |
| Offensive | −30 % … +30 % | 0 % | `attack` 0.7 – 1.3 | multipliziert beide Angriffswerte |
| Defensive | −30 % … +30 % | 0 % | `defence` 0.7 – 1.3 | höher = stärkere Abwehr, senkt beide Torerwartungen |
| Heimvorteil | −50 % … +50 % | 0 % | `home_advantage` 0.5 – 1.5 | verschiebt Heim gegen Auswärts, torneutral |
| ML-Einfluss | 0 % … 100 % | 0 % | `ml_weight` 0.0 – 1.0 | Gewicht der ML-Korrektur |

„Zurücksetzen“ stellt alle vier auf 0 % zurück. Die Einstellungen gelten
nur für den jeweiligen Browserzustand und den jeweiligen Request; sie
werden nirgends gespeichert und berühren keinen anderen Nutzer. Bei einem
Wettbewerbswechsel fallen sie auf den Standard zurück.

Bei der Champions League ist die Checkbox „Immer gleiches Ergebnis“
ausgeblendet und der Request trägt dort ausdrücklich `use_seed: false`;
für die Ligen bleibt sie sichtbar und wirksam.

Geprüft wird weiterhin ausschließlich serverseitig. Die Reglergrenzen
sind Bedienkomfort, keine Sicherheitszusage; sie liegen bewusst
innerhalb der Grenzen, die C8A durchsetzt.

**Was diese Auswahl nicht behauptet:** Dass „ML-Prognose“ nachweislich
genauer sei. Der Champions-League-Backtest ist unverändert nicht eindeutig
(siehe oben), das Modell steht auf `experimental`, und ein Liga-ML ist
nicht Bestandteil der fertigen CL-V1. Die Auswahl ist eine
Wahlmöglichkeit, keine Rangfolge.

### Die einheitliche Point-in-Time-Profilfabrik (V2-C1)

Bis V2-C1 gab es für dieselbe Frage (*wie stark war dieses Team zu
diesem Zeitpunkt?*) **zwei** Implementierungen: Der Trainingsdatensatz
baute jedes Profil zum Stichtag des Zielspiels, der Laufzeitpfad
(`_blend_top5_league_history_by_id`) blendete schlicht alle lokal
vorliegenden Saisons. Ein Profil für die Saison 2024 war zur Laufzeit
deshalb **identisch** mit dem für 2025.

Seit V2-C1 gibt es genau einen maßgeblichen Pfad:
[`src/features/pit_profiles.py`](src/features/pit_profiles.py). Datensatz
und Laufzeit rufen dieselbe Fabrik auf.

**Der Stichtag ist Pflichtbestandteil des Vertrags.** Es gibt keinen
Standardwert, kein „neueste Saison", kein `datetime.now()` tief in der
Rechnung. Braucht die Laufzeit „jetzt", bestimmt sie den Zeitpunkt am
Rand über `runtime_cutoff()` und reicht ihn herein; damit bleibt er in
Tests steuerbar.

| Fall | Stichtag |
| --- | --- |
| Trainingsdatensatz | Datum des Zielspiels |
| Historischer Backtest | Datum des jeweils simulierten Spiels |
| **Historische Nachsimulation** | **tatsächlicher Anstoß des Zielspiels** |
| Aktuelles/künftiges Spiel | `runtime_cutoff()`: heutiger Tag, 12 Uhr |

Für die Nachsimulation löst das Backend den Anstoß **selbst** auf
(`fixture_cutoff`), aus derselben lokalen Historie, aus der auch die
Profile entstehen. Der Client sendet dafür nichts Neues: Saison und
Mannschaften stehen ohnehin im Request. Einen Zeitpunkt vom Client
entgegenzunehmen hieße, eine fachliche Wahrheit von außen bestimmen zu
lassen; so gibt es **keine Manipulationsfläche**.

Aufgelöst wird über die Paarung (Saison, Heim-ID, Gast-ID). Innerhalb
der regulären Phase ist sie je Saison eindeutig, nachgemessen über
2023–2025. Trifft dieselbe Paarung später noch einmal im K.-o.
aufeinander, gewinnt die reguläre Phase; blieben nur K.-o.-Partien,
gewinnt die **früheste** (weniger Information, nie mehr). Steht die
Begegnung nicht in der Historie, ist sie künftig oder unbekannt. Dann
gilt „jetzt". Ein stilles Zurückfallen auf die komplette Saison gibt es
nicht.

Die Regel am Stichtag selbst stammt unverändert aus
`point_in_time.is_known_at`:

```
Anstoß < Stichtag     bekannt
Anstoß > Stichtag     unbekannt
gleicher Tag          nur mit Uhrzeiten auf beiden Seiten entscheidbar,
                      sonst gilt CUTOFF_INCLUSIVE = False
```

Ein Spiel **am** Stichtag gilt also als unbekannt. Das ist die
leak-sichere Wahl: Sonst trüge ein zu prognostizierendes Spiel zu seiner
eigenen Vorhersage bei.

Zwei zeitliche Grenzen wirken zusammen, und beide werden gebraucht: die
**Saisonobergrenze** (keine spätere Saison) und der **Stichtag**
innerhalb jeder Saison. Die erste allein ließe den Rest der laufenden
Saison durch, die zweite allein die kompletten Folgesaisons.

**Cache-Regel:** Jeder Zwischenspeicher trägt den Stichtag im Schlüssel,
sowohl in der Fabrik als auch im Simulations-Cache
(`cl_strengths:{season}:{cutoff}`). Ein Profil zum 01.10.2024 kann
dadurch nie durch einen Treffer für den 01.03.2025 ersetzt werden.

**Sichere Rückfälle:** Die Fabrik greift selbst nie auf das Netz zu. Sie
liest ausschließlich die versionierte Historie unter `data/historical/`.
Partien einer laufenden Saison, die lokal fehlen, holt die Laufzeit und
reicht sie herein, gefiltert werden auch sie mit demselben Stichtag.
Fehlt jede Quelle, bleiben die Profile leer und die bestehende
Neutralprofil-Kaskade greift; die Simulation liefert weiterhin ein
vollständiges Ergebnis.

**Provenienz:** Jede Antwort nennt `pit_cutoff`, `pit_season_ceiling`,
`cl_matches_known_at_cutoff` und `cutoff_inclusive`. `matches_through_date`
meldet seither das zuletzt **verwendete** Spiel statt des Rohbestands der
Datei.

Nachgewiesen ist die Parität: Für echte Zeilen des C1-Datensatzes liefert
der laufzeitnahe Pfad exakt dieselben Merkmalswerte und dieselbe
Profilherkunft wie der Datensatzpfad, siehe
[`tests/test_pit_profiles.py`](tests/test_pit_profiles.py).

#### Was V2-C1 noch offen lässt

- Der Schlüssel `cl_current_by_id` behält seinen Namen, obwohl er jetzt
  die gepoolte CL-Historie bis zum Stichtag enthält. Er steht im
  API-Vertrag und wird im Browser gelesen; die Umbenennung wäre eine
  sichtbare Vertragsänderung.
- Die Auflösung greift auf die **lokale** Historie zu. Eine Partie der
  laufenden Saison, die dort noch nicht steht, gilt als künftig und
  bekommt „jetzt"; für ein noch nicht gespieltes Spiel ist das richtig.
- V2-C1 bedeutet **kein** neues freigegebenes Modell und kein Deployment.
  Das Modell steht unverändert auf `experimental`, es wurde nicht neu
  trainiert und nicht hochgestuft.

### Belastungszeitleiste für Champions-League-Zeilen (V2-C2)

Bis V2-C2 trug **jede** der 503 CL-Zeilen in jedem Belastungsfeld `None`
und den Sammelvermerk `not_computed_for_cl`. Der Grund war fachlich
richtig, aber zu grob.

**Warum die Werte fehlten.** Die Zeitleiste liest fünf Ligen, die
Champions League und fünf nationale Pokale. Ein Verein aus einer anderen
Liga (Ajax, Benfica, PSV, Celtic) erscheint darin ausschließlich mit
seinen CL-Partien im Zweiwochentakt. Gemessen über 2023–2025:

| Gruppe | Seiten | Median Ruhetage | über 10 Tage |
| --- | ---: | ---: | ---: |
| mit nationaler Ligahistorie | 466 | 3,0 | 0 % |
| ohne | 302 | 15,0 | 90 % |

Eine daraus gerechnete Ruhezeit wäre plausibel aussehend und um etwa den
Faktor vier falsch.

**Was V2-C2 ändert.** Entschieden wird jetzt je **Seite** statt pauschal
je Zeile. `match_timeline.base_load_coverage()` prüft, ob eine Mannschaft
innerhalb von 45 Tagen vor dem Stichtag eine Partie in einem
Grundtakt-Wettbewerb hatte. Ist sie abgedeckt, rechnen dieselben
Funktionen wie im Ligapfad (`workload_features`, `schedule_strength`).
Ist sie es nicht, bleibt der Wert `None`, mit der Ursache im
Qualitätsfeld statt eines Sammelvermerks.

| Saison | Seiten | vorher | nachher | Quote |
| --- | ---: | ---: | ---: | ---: |
| 2023 | 250 | 0 | 166 | 66,40 % |
| 2024 | 378 | 0 | 246 | 65,08 % |
| 2025 | 378 | 0 | 246 | 65,08 % |
| **gesamt** | **1006** | **0** | **658** | **65,41 %** |

Median 3 Tage, 3 von 658 Werten über 10 Tage. Home und Away identisch.
Vorherige Partie stammt aus PD/PL/BL1/SA/FL1 sowie FA Cup, Copa del Rey,
Coupe de France und CL. Die Zeitleiste ist tatsächlich
wettbewerbsübergreifend.

**Cutoff-Regel:** unverändert die aus V2-C1. Nur Partien strikt vor dem
Stichtag zählen; das Zielspiel selbst nie. Die Abdeckungsprüfung schaut
ebenfalls ausschließlich zurück.

**Ruhezeitdefinition:** unverändert aus `workload.py` übernommen,
Stunden zwischen dem letzten Anstoß und dem Stichtag, daraus
`rest_days`. Fehlt eine Anstoßzeit, gilt 12 Uhr
(`FALLBACK_KICKOFF_HOUR`); die geringere Genauigkeit steht getrennt in
`rest_time_precision`. Ohne vorherige Partie bleibt der Wert `None` mit
`data_quality = "unavailable"`, kein erfundener Standardwert.

**Deduplizierung:** über `(competition, season, match_id)`. Dieselbe
Partie aus zwei Dateien erzeugt genau einmal Belastung.

**Crosswalk:** Pokaldaten kommen von API-Sports, Ligadaten von
football-data. `team_crosswalk` ordnet innerhalb einer Liga und Saison
zu; bleibt ein Name mehrdeutig, wird er **nicht** zugeordnet, sondern als
Konflikt gemeldet. Eine Partie ohne zuordenbare Mannschaft erzeugt keine
Belastung für einen falschen Verein.

### Die nationalen Ligen der übrigen CL-Teilnehmer (V2-C2B)

V2-C2 ließ 348 von 1006 Seiten (34,6 %) offen, mit **einer** Ursache:
`no_base_competition_in_timeline`. Betroffen waren 27 Vereine, deren
nationale Liga lokal nicht vorlag. V2-C2B beschafft genau diese Ligen.

**18 Ligen, 32 Liga-Saison-Kombinationen**, abgeleitet aus dem Bedarf,
nicht aus einer Wunschliste: Es wurde genau geladen, was mindestens eine
offene Teamseite schließt.

| Land | Liga | Saisons | Land | Liga | Saisons |
| --- | --- | --- | --- | --- | --- |
| Portugal | Primeira Liga | 23–25 | Serbien | Super Liga | 23, 24 |
| Niederlande | Eredivisie | 23–25 | Ukraine | Premier League | 23, 24 |
| Belgien | Jupiler Pro League | 23–25 | Norwegen | Eliteserien | 25 |
| Österreich | Bundesliga | 23, 24 | Griechenland | Super League 1 | 25 |
| Türkei | Süper Lig | 23, 25 | Aserbaidschan | Premyer Liqa | 25 |
| Schottland | Premiership | 23, 24 | Kroatien | HNL | 24 |
| Dänemark | Superliga | 23, 25 | Zypern | 1. Division | 25 |
| Tschechien | Czech Liga | 24, 25 | Slowakei | Super Liga | 24 |
| Schweiz | Super League | 23, 24 | Kasachstan | Premier League | 25 |

**Herkunft der Liga-IDs.** Keine ist geraten. Jede wurde über
`/leagues?team=<apisports_id>` aufgelöst, aus der Mannschaft heraus, die
sie braucht. Je Verein blieb genau ein Wettbewerb vom Typ „League" mit
Saisondaten übrig; bei mehr als einem wäre die Auflösung fehlgeschlagen.

**Crosswalk.** Die Ligadaten kommen von API-Sports, die CL-Daten von
football-data. Zugeordnet wurde **innerhalb derselben
Wettbewerbssaison**: die CL-Teilnehmerliste beider Anbieter gegeneinander.
20 der 27 Vereine lösten sich über die normalisierte Schreibweise oder die
Teilmengenregel eindeutig auf; die übrigen sieben tragen bei den Anbietern
verschiedene Namen und stehen einzeln und belegt in
`match_timeline.CL_PARTICIPANT_CROSSWALK`. Ein unscharfer Vergleich war
ausdrücklich nicht die Alternative: „Union St. Gilloise" und „Union
Berlin" stehen beide in der Teilnehmerliste. Gegengeprüft: Jede
API-Sports-ID taucht in der Teamliste ihrer Ligadatei wirklich auf.

**Coverage:**

| Saison | Seiten | V2-C2 | V2-C2B | Quote |
| --- | ---: | ---: | ---: | ---: |
| 2023 | 250 | 166 | 249 | 99,60 % |
| 2024 | 378 | 246 | 375 | 99,21 % |
| 2025 | 378 | 246 | 368 | 97,35 % |
| **gesamt** | **1006** | **658** | **992** | **98,61 %** |

Home und Away identisch, Median weiterhin 3 Ruhetage. Die vorherige
Partie stammt jetzt aus 27 verschiedenen Wettbewerben.

#### Die 14 verbleibenden Lücken

Alle tragen `base_competition_stale` und sind **echte Spielpausen**, keine
Datenlücken: Bodø/Glimt (Eliteserien, März–November) und Kairat
(kasachische Liga, Kalenderjahr) haben im Januar bis März schlicht keinen
Spielbetrieb; dazu Winterpausen in Dänemark, Österreich, der Slowakei und
Tschechien. Ihre Liga *ist* geladen; sie spielte zu diesem Zeitpunkt
nicht.

Ein erfundener Wert wäre hier besonders schädlich, weil er wie eine
normale Ruhezeit aussähe.

*C8B, C0B, C1, C2 und C2B sind lokal umgesetzt und nicht auf dem Server
ausgeliefert. V2-C2B liefert Daten und Timeline; es trainiert kein Modell,
bewertet kein Merkmal und stuft nichts hoch.*

### Belastungsmerkmale: gebaut, gemessen, nicht aufgenommen (V2-C3)

V2-C2B hat die Ruhezeit-Abdeckung auf 98,61 % gehoben. Damit war zum
ersten Mal messbar, was vorher nur behauptbar war: **Trägt Belastung
etwas bei, das die Teamprofile nicht schon wissen?**

Die Antwort dieses Blocks lautet **nein**, und das ist ein Ergebnis,
kein Scheitern. Der Kandidat bleibt unverändert `team_profile_cl` mit
seinen 16 Profilmerkmalen.

#### Die geprüften Merkmale

Alle Werte entstehen ausschließlich aus Partien **strikt vor** dem
Stichtag. Das Zielspiel selbst zählt nie mit.

| Merkmal | Bedeutung |
| --- | --- |
| `rest_hours` / `rest_days` | Stunden zwischen letztem Anpfiff und Stichtag; Tage daraus **abgerundet** |
| `short_rest_flag` | Pause unter 72 Stunden (`SHORT_REST_HOURS`) |
| `matches_last_7/14/21/30_days` | Pflichtspiele im Fenster, wettbewerbsübergreifend |
| `consecutive_away_matches` | unmittelbar vorangegangene Auswärtsspiele; die Serie bricht beim ersten Heimspiel |
| `extra_time_matches_last_30_days` | Partien mit Verlängerung in 30 Tagen |
| `extra_time_minutes_last_30_days` | die daraus zusätzlich gespielten Minuten (30 je Verlängerung) |
| `number_of_usable_matches` | überhaupt bekannte frühere Partien; beschreibt die *Quelle* |
| `workload_diff_*` | Differenz Heim minus Auswärts über Ruhezeit und alle vier Fenster |

**Fenstersemantik**, exakt und getestet: Die Grenze ist unten
geschlossen, oben offen: `cutoff − n Tage ≤ kickoff < cutoff`. Eine
Partie genau auf der unteren Grenze zählt **mit**, eine Sekunde davor
nicht mehr. Fehlt die Anstoßzeit, setzt die Zeitleiste Mittag an; das
verschiebt die Stundenzahl, nie die Zählung. Nicht ausgetragene Partien
stehen gar nicht erst in der Zeitleiste.

**Eine einzige Ruhezeitdefinition**, in `workload.py`. `rest_days`
entsteht aus `rest_hours` durch Abrunden. „Zwei volle Tage Pause" darf
nicht „49 Stunden" heißen. Lange echte Pausen werden **nicht** gedeckelt:
41 Tage nach einer Winterpause sind die Wahrheit, und ein Deckel würde
sie zu einer anderen machen.

#### Verlängerung: was die Quellen wirklich hergeben

Hier war zuerst zu klären, ob ein Merkmal überhaupt zulässig ist.
`None` heißt deshalb ausdrücklich **„nicht bekannt"**, nicht „keine
Verlängerung":

| Quelle | Status | Verlängerung ableitbar? |
| --- | --- | --- |
| Pokale, nationale Ligen (API-Sports) | `FT` / `AET` / `PEN` | **ja**, direkt |
| Top-5-Ligen (football-data) | keiner | **ja**: ein Ligaspiel dauert 90 Minuten, das ist die Regel |
| CL-Rundenphase | `FINISHED` | **ja**: Rundenspiele kennen keine Verlängerung |
| CL-K.-o.-Runden | `FINISHED` | **nein**: ehrlich unbekannt |

Auf den 476 ausgewerteten CL-Teamseiten ist der Wert zu **98,11 %**
vorhanden und dort **ausnahmslos `complete`**: Kein einziges Fenster
enthält eine CL-K.-o.-Partie, weil die Rundenphase im Januar endet und
die K.-o.-Runden im Februar beginnen. Die fehlenden 1,89 % sind exakt
die neun Seiten ohne nationalen Grundtakt aus V2-C2B.

#### Redundanz: der deutlichste Befund

Gerechnet auf 2.917 Ligazeilen der Trainingssaisons, **nie** auf
CL-Zeilen:

- **19 von 27** Belastungsspalten sind *exakt* aus den übrigen
  zusammensetzbar. Der Grund ist Konstruktion, nicht Zufall: `diff =
  home − away`, also ist jede dritte der drei Spalten überflüssig.
- `extra_time_minutes` und `extra_time_matches` korrelieren mit
  **r = 1,0000**: die Minuten sind das 30-Fache der Partien.
- `rest_days` gegen `rest_hours`: r = 0,998, **VIF 654** und **635**.
- Keine konstante, keine vollständig fehlende Spalte.

Ein nicht bestimmbarer VIF ist deshalb **keine Entwarnung**; das Feld
`vif_status` sagt in jedem Fall, warum er fehlt.

#### Die Ablation

Vierzehn Varianten, **alle** berichtet. Jede enthält den vollständigen
V1-Satz und unterscheidet sich von ihm nur um die geprüfte Untergruppe,
die Frage lautet „hilft es *zusätzlich*", nicht „hilft es".

Entscheidend ist die **gepaarte** Differenz gegen V1: Der Vergleich
gegen die ungelernte Baseline kann sie nicht beantworten, weil beide
Intervalle denselben großen gemeinsamen Anteil enthalten.

| Variante | Δ gepaart gegen V1 | 95-%-Intervall | Urteil |
| --- | ---: | --- | --- |
| `team_profile_cl` (V1) | – | – | Kontrolle |
| `+ short_rest` | −0,000499 | [−0,00416; +0,00319] | INCONCLUSIVE |
| `+ all_workload` | −0,000426 | [−0,01823; +0,01756] | INCONCLUSIVE |
| `+ matches_21d` | +0,000585 | [−0,00381; +0,00526] | REJECTED |
| `+ extra_time` | +0,000692 | [−0,01023; +0,01166] | REJECTED |
| `+ away_streak` | +0,000837 | [−0,00933; +0,01163] | REJECTED |
| `+ matches_30d` | +0,001427 | [−0,00567; +0,00896] | REJECTED |
| `+ timeline_depth` | +0,001568 | [−0,00907; +0,01238] | REJECTED |
| `+ congestion_windows` | +0,002224 | [−0,01003; +0,01505] | REJECTED |
| `+ matches_7d` | +0,002403 | [−0,00548; +0,01042] | REJECTED |
| `+ recovery` | +0,003463 | [−0,00894; +0,01775] | REJECTED |
| `+ reduced` | +0,003966 | [−0,00987; +0,01745] | REJECTED |
| `+ rest` | +0,004347 | [−0,00847; +0,01901] | REJECTED |
| `+ matches_14d` | +0,005023 | [−0,00555; +0,01577] | REJECTED |
| `+ difference` | +0,005082 | [−0,00714; +0,01754] | REJECTED |

**12 REJECTED, 2 INCONCLUSIVE, 0 ACCEPTED.** Zwölf Varianten machen V1
im Punktschätzer sogar *schlechter*.

**Die Auswahl berührte den Testbestand nicht.** Der reduzierte Kandidat
(`short_rest`, `matches_30d`, `extra_time`, `difference`) entstand
ausschließlich auf der inneren Validierungshälfte der **Liga**-Daten,
bevor ein CL-Ergebnis vorlag. Genau diese vier Untergruppen, die auf
Ligadaten am besten aussahen, werden auf CL-Partien **abgelehnt**
(+0,00397), der lehrreichste Einzelbefund des Blocks: Was auf
Ligaspielen trägt, trägt in der Champions League nicht.

#### Warum das kein „fast" ist

Der V1-Kandidat selbst steht bei n = 213 und einem Intervall von
[−0,0299; +0,0114], **rund 0,04 breit**. Ein Belastungseffekt müsste
diese Breite überwinden, um nachweisbar zu sein; die gemessenen Effekte
liegen bei 0,0005. Der Bestand ist um mehr als eine Größenordnung zu
klein, um die Frage zu entscheiden.

Deshalb heißen zwei Varianten INCONCLUSIVE und nicht REJECTED: Die
Unterscheidung ist keine Formalie. REJECTED schließt die Frage,
INCONCLUSIVE lässt sie offen, und offen ist sie hier.

#### Was bleibt

Alle Spalten bleiben im Datensatz, keine geht ins Modell. Der
Merkmalsvertrag `fg.SCHEMA_VERSION` steht auf 2; die Gruppe `workload`
ist dabei **unverändert** geblieben, damit die bereits berichtete
Variante `workload_only` weiterhin dieselben 24 Merkmale bezeichnet.
Die Verlängerungsfelder haben eine eigene Gruppe bekommen.

Artefakt: `data/ml/c3_workload_ablation_2023-2025.json`, mit
Featurevertrag, Fingerabdruck je Variante, Folddefinitionen, sämtlichen
Varianten, Konfidenzintervallen, Coverage und Redundanzdiagnostik.

*V2-C3 ist Analyse. Es ist kein finales V2-Modell und kein Deployment:
Es trainiert Kandidaten ausschließlich zur Messung, speichert kein
Bundle, aktiviert nichts und stuft nichts hoch. Das bestehende Modell
bleibt `experimental` und unverändert.*

### Form, Gegnerstärke und UEFA-Stärke (V2-C4)

Wieder gebaut, gemessen, und wieder **nichts aufgenommen**. Der
Kandidat bleibt `team_profile_cl` mit seinen 16 Profilmerkmalen.

#### Was V1 schon konnte

Der wichtigste Befund der Bestandsaufnahme: **V1 enthält bereits Form**,
nur nicht unter diesem Namen. `points_per_game`, `win_rate`,
`goals_for_per_game`, `goals_against_per_game` und die vier heim-/
auswärtsgetrennten Angriffs- und Abwehrwerte sind punktgenaue
Leistungsgrößen zum Stichtag, über bis zu drei Saisons geometrisch
geblendet. Heim-/Auswärtstrennung ist damit **schon da**.

Was fehlte, ist die *kurze* Sicht: die letzten drei bis acht Partien,
getrennt nach Wettbewerb, und die Frage, gegen wen gespielt wurde.

#### Formdefinitionen

| Größe | Bedeutung |
| --- | --- |
| `points_rate` | Punktequote in [0, 1], Sieg 1, Remis 0,5, Niederlage 0 |
| `goal_diff_per_match` | Tordifferenz je Partie |
| `<scope>_matches` | Tiefe der Betrachtung, **Qualitätsfeld, kein Modellmerkmal** |

**Fenster nach Partien, nicht nach Tagen.** Ein 30-Tage-Fenster ist im
Januar leer und im April voll. Für Belastung ist das richtig (C3), für
Form falsch: „die letzten fünf" ist über eine Winterpause hinweg
dieselbe Aussage.

Sieben vorab festgelegte Betrachtungen: `all_3`, `all_5`, `all_8`
(wettbewerbsübergreifend), `domestic_5`, `cl_5`, `home_5`, `away_5`.
Drei Fenstergrößen und nicht mehr, jede weitere ist eine zusätzliche
getestete Variante, ohne die Stichprobe zu vergrößern.

**Weitere Festlegungen, alle getestet:**

- **Erst filtern, dann abschneiden.** „Die letzten fünf Heimspiele" ist
  nicht „die Heimspiele unter den letzten fünf Partien".
- **Ergebnisregel:** Der Stand nach 90 bzw. 120 Minuten zählt. Ein
  **Elfmeterschießen ändert ihn nicht**, die Quellen führen die
  Schützentore in eigenen Feldern, und ein Schützenduell sagt über
  Spielstärke wenig. Eine im Schießen entschiedene Partie gilt als Remis.
- **Nationale Form ohne Pokale.** Ein 5:0 in Runde zwei gegen einen
  Viertligisten ist kein Formbeleg. In der *allgemeinen* Form zählt es
  mit, dort ist Gegnerstärke ein eigenes Merkmal.
- **Mindesttiefe 2.** Ein Mittelwert über eine Partie ist kein Formwert,
  sondern dieses eine Ergebnis. Darunter bleibt der Wert `None`.
- **Keine Alterung innerhalb des Fensters.** Eine zweite
  Abklingkonstante wäre ein freier Parameter, den diese Datenmenge nicht
  bestimmen kann, das Fenster *ist* die Gewichtung.

#### Gegnerstärke: welcher Stichtag gilt

Die naheliegende Abkürzung wäre, die Gegnerstärke zum Stichtag des
Zielspiels zu nehmen. Sie wäre sogar leckagefrei gegenüber der
Prognose. Sie wäre trotzdem falsch: Das Profil zum Dezemberstichtag
**enthält das Ergebnis genau der Septemberpartie, deren Schwierigkeit
es beschreiben soll**.

`PitStrengthAtDate` löst das mit dem Stichtag der *damaligen* Partie.
Kosten: rund zehn Millisekunden je zusätzlichem Stichtag, 548 davon im
gesamten Bestand, bezahlbar, also wurde die richtige Variante gebaut.

`adjusted_points_rate_5 = Σ(punkte·stärke) / Σ(stärke)`, eine mit der
Gegnerstärke gewichtete Punktequote, **parameterfrei**. Eine
Erwartungskurve „welche Punktzahl ist gegen diese Stärke normal" bräuchte
einen freien Parameter, den niemand gemessen hat.

#### UEFA: was die Quelle wirklich hergibt

**Ein Verbandskoeffizient liegt nicht vor.** Alle sechs Snapshots tragen
ausschließlich `uefa_club_coefficient_top40`. Die eigentlich gesuchte
„Stärke der nationalen Liga" ist in diesem Bestand nicht vorhanden, und
wurde nicht erfunden. Stattdessen zwei sauber getrennte Größen:

| Spalte | Was sie ist |
| --- | --- |
| `uefa_club_coefficient`, `uefa_club_rank` | der offizielle Vereinskoeffizient |
| `uefa_country_top40_strength` | ein **abgeleiteter** Landeswert: Summe der Top-40-Koeffizienten desselben Landes |

Der Name trägt `top40`, weil das die Schwäche ist: Ein Land mit acht
Klubs in den Top 40 bekommt mehr als eines mit einem, unabhängig von
der Breite seiner Liga. Das ist kein Verbandskoeffizient und heißt auch
nicht so.

**Der Stichtag ist der Kern.** Der Koeffizient einer Saison X enthält
deren *eigene* Ergebnisse, belegt in den Daten: Der Snapshot 2026/27
ist `provisional` und liegt durchgehend deutlich unter 2025/26 (Real
Madrid 114,5 gegen 144,5), weil die laufende Saison erst wenige Punkte
beigesteuert hat. Für ein Spiel *in* Saison X wäre er damit
Zukunftsinformation.

> **Regel ohne Ausnahme:** Für eine Partie der Saison X gilt der
> Snapshot der Saison **X − 1**.

Fehlende Werte bleiben `None` mit sichtbarem Grund, und die Gründe sind
unterscheidbar: `club_not_in_top40` ist eine Aussage über den *Verein*,
`no_snapshot_for_season` eine Lücke der *Umgebung*. Beides in ein
einziges `None` zu legen würde eine fehlende Datenquelle wie eine
Vereinseigenschaft aussehen lassen.

**Die UEFA-Dateien sind gitignoriert** (`data/big_games/`). Der
Datensatzbau liest sie deshalb **standardmäßig nicht**
(`INCLUDE_UEFA_BY_DEFAULT = False`), sonst wäre er aus einem frischen
Checkout nicht mehr reproduzierbar, und ein bestehender Guard-Test hat
genau das erzwungen. Wer sie einschaltet, weiß, dass sein Bestand ohne
die privaten Dateien nicht nachbaubar ist; das Artefakt hält es unter
`uefa_data_available` fest.

#### Coverage

Auf den 476 ausgewerteten CL-Teamseiten:

| Merkmal | CL | Ligatraining |
| --- | ---: | ---: |
| allgemeine, nationale, Heim-/Auswärtsform | 100,00 % | 100,00 % |
| `cl_5_*` | 90,76 % | 27,31 % |
| `opponent_strength_5` | 83,82 % | 100,00 % |
| `uefa_*` | 71,64 % | 28,55 % |

Die 19 Seiten ohne CL-Form sind erstmals qualifizierte Vereine, ihr
Wert bleibt `None`, niemals 0. Eine Null hieße „hat alle CL-Spiele
verloren" und wäre die schärfste denkbare Falschaussage über sie.

**Die rechte Spalte ist der wichtigste Befund.** UEFA liegt im Training
für 28,55 % der Seiten vor, im Test für 71,64 %; bei der CL-Form ist es
umgekehrt. Der Median-Imputer füllt im Training also die Mehrheit, im
Test die Minderheit. Das ist derselbe Verteilungsbruch, an dem in V2-C2
schon `profile_depth` gescheitert ist, und eine starke Vorab-Erwartung,
dass diese Merkmale nicht übertragen.

#### Redundanz

Auf 2.917 Ligazeilen der Trainingssaisons, nie auf CL-Zeilen. Von 41
Formspalten sind **6 exakt kollinear** und **22 tragen VIF ≥ 10**.

- `home_uefa_country_top40_strength` gegen `away_...`: **r = 1,0000**,
  in einem Ligaspiel kommen beide Teams aus demselben Land, der Wert ist
  dort nichts als „welche Liga ist das". In der CL unterscheidet er sich.
- `adjusted_points_rate_5` gegen `all_5_points_rate`: r = 0,954, die
  Gegneradjustierung bewegt wenig.
- `uefa_club_coefficient` gegen `uefa_club_rank`: r = −0,943.
- `all_5` gegen `domestic_5`: r = 0,92, für einen CL-Teilnehmer *ist*
  die allgemeine Form überwiegend die Ligaform.

#### Die Ablation

Sechzehn Varianten, **alle** berichtet. Jede enthält den vollständigen
V1-Satz; gemessen wird die **gepaarte** Differenz gegen V1.

| Variante | Δ gepaart gegen V1 | 95-%-Intervall | Urteil |
| --- | ---: | --- | --- |
| `team_profile_cl` (V1) | – | – | Kontrolle |
| `+ form_cl` | −0,007211 | [−0,02304; +0,00884] | INCONCLUSIVE |
| `+ form_competition_split` | −0,003700 | [−0,01894; +0,01240] | INCONCLUSIVE |
| `+ form_difference` | −0,002727 | [−0,00780; +0,00176] | INCONCLUSIVE |
| `+ form_opponent` | −0,000883 | [−0,01164; +0,00962] | INCONCLUSIVE |
| `+ form_all_8` | +0,001155 | [−0,00981; +0,01218] | REJECTED |
| `+ form_all_3` | +0,001762 | [−0,00548; +0,00755] | REJECTED |
| `+ form_venue` | +0,002901 | [−0,01372; +0,02031] | REJECTED |
| `+ form_all_5` | +0,003152 | [−0,00555; +0,01418] | REJECTED |
| `+ form_reduced` | +0,003214 | [−0,01655; +0,02514] | REJECTED |
| `+ form_windows` | +0,003627 | [−0,00847; +0,01541] | REJECTED |
| `+ uefa_club` | +0,003681 | [−0,00517; +0,01212] | REJECTED |
| `+ uefa_country` | +0,004311 | [−0,00905; +0,01884] | REJECTED |
| `+ form_domestic` | +0,004967 | [−0,00565; +0,01652] | REJECTED |
| `+ all_form` | +0,005397 | [−0,01568; +0,02864] | REJECTED |
| `+ uefa_all` | +0,008110 | [−0,00732; +0,02464] | REJECTED |

**11 REJECTED, 4 INCONCLUSIVE, 0 ACCEPTED.**

`form_cl` hat den besten Punktschätzer und ist in beiden Folds negativ
(−0,0242 / −0,0072), verfehlt das Gate aber deutlich: Das Intervall
reicht bis +0,0088. `form_difference` hat das **engste** Intervall des
ganzen Blocks und kommt der Signifikanz am nächsten.

**Die Auswahl berührte den Testbestand nicht.** Der reduzierte Kandidat
entstand auf der inneren Validierungshälfte der *Liga*-Daten: erst
Nutzenschwelle, dann Korrelation, dann eine VIF-Schleife bis unter 10.
Übrig blieben `form_all_3`, `form_venue`, `uefa_club`, `uefa_country`
mit **max VIF 8,42** und keiner exakten Abhängigkeit, sauber nach den
Vorgaben, und auf CL-Partien trotzdem **abgelehnt** (+0,00321).

Zum zweiten Mal nach C3 dasselbe Muster: *Was auf Ligaspielen trägt,
trägt in der Champions League nicht.*

#### Warum das erneut kein „fast" ist

V1 selbst steht bei n = 213 mit einem Intervall von [−0,0299; +0,0114],
**rund 0,04 breit**. Der beste C4-Effekt beträgt 0,007. Bei 16
getesteten Varianten ist ein einzelner Punktschätzer dieser Größe kein
Nachweis, sondern eine Beobachtung.

*V2-C4 ist Analyse. Es ist kein finales V2-Modell und kein Deployment:
Es trainiert Kandidaten ausschließlich zur Messung, speichert kein
Bundle, aktiviert nichts und stuft nichts hoch. Das bestehende Modell
bleibt `experimental` und bitgleich.*

### Spielkontext: K.-o., Legs, Aggregat, neutraler Ort (V2-C5)

Bis V2-C4 waren **119 K.-o.-Partien** aus der Auswertung ausgeschlossen,
mit der Begründung „Zwei-Leg- und Verlängerungslogik nicht modelliert".
C5 modelliert sie. **Alle 119 sind wieder nutzbar**, keine bleibt aus
fachlichen Gründen draußen.

Aufgenommen wird trotzdem nichts: Der Kandidat bleibt `team_profile_cl`.

#### Der kanonische Vertrag

Ein Feld, nicht vier Wahrheitswerte. `match_type` ist genau einer von
`league_phase`, `ko_first_leg`, `ko_second_leg`, `ko_single_match`,
`final`; die Modellspalten werden daraus **abgeleitet**. Vier
unabhängige Bools könnten sich widersprechen, „Finale und Hinspiel" ist
keine Partie, die es gibt, aber eine Kombination, die vier Bools
zulassen. Eine Konsistenzprüfung läuft über jede Zeile (0 Verstöße bei
5.756 Zeilen).

**Die Herleitung benutzt keine Zukunft.** Ob eine Partie Hin- oder
Rückspiel ist, kommt aus *ihren eigenen* Metadaten, `stage` und
`matchday` (1 = Hinspiel, 2 = Rückspiel; das Endspiel trägt je nach
Saison `None` oder `0`, dort entscheidet die Runde). Bequemer wäre
gewesen, die Partien einer Paarung zu zählen, dann hätte ein Hinspiel
wissen müssen, dass später ein Rückspiel folgt.

#### Aggregatstand: die Perspektive

Alle Werte gelten aus Sicht der Mannschaft, die **in dieser Partie** zu
Hause spielt. Im Rückspiel ist das die Mannschaft, die im Hinspiel
auswärts war; die Tore werden gedreht. Genau hier entsteht der Fehler,
den niemand bemerkt: Ein Vorzeichendreher ergibt lauter plausible Zahlen
mit der falschen Mannschaft davor.

Nachgerechnet am Viertelfinale 2024/25: Arsenal 3:0 Real Madrid im
Hinspiel → im Rückspiel bei Real steht `aggregate_goals_for = 0`,
`aggregate_goals_against = 3`, `aggregate_diff = −3`, `aggregate_lead =
−1`. Bei allen 58 Rückspielen war das aktuelle Heimteam im Hinspiel zu
Gast, der drehende Pfad ist also durchgängig belegt.

**Kein erfundener Stand.** Hinspiel, Einzelspiel und Endspiel haben
keinen Vorstand: alle vier Werte `None`, `aggregate_available = 0`. Eine
Null wäre zweideutig, sie hieße zugleich „Gleichstand" und „keine
Information".

#### Historische Regeln

| Regel | Behandlung |
| --- | --- |
| Auswärtstorregel | Vom UEFA-Exekutivkomitee am 24.06.2021 zur Saison 2021/22 gestrichen → `season < 2021`. Im Bestand 2023–2025 **konstant falsch** |
| Formatwechsel | 2023 Gruppenphase (96 Rundenspiele), ab 2024 Ligaphase (144) plus die neue Runde `PLAYOFFS`. Beide Rundenphasen sind `league_phase`, **nie** K.-o. |
| Hin-/Rückspiel gegen Einzelspiel | Über `matchday`; eine K.-o.-Partie ohne Legkennung gilt als Einzelspiel, nicht stillschweigend als Hinspiel |
| Endspiel | Einzelpartie auf neutralem Platz |
| Verlängerung / Elfmeterschießen | **Nicht ableitbar** (siehe unten) |

Die Auswärtstorregel ist reiner Regelkontext: Die Funktion bekommt die
Saison und sonst nichts. Sie aus dem Spielausgang abzuleiten wäre ein
Selbstleck.

#### Was die Quelle nicht hergibt

Die CL-Historie führt zu allen 503 Partien nur `date`, `match_id`,
`matchday`, `stage`, `status`, die beiden IDs und die beiden Torzahlen.

**Keine Spielstätte, keine Neutralitätsangabe.** `neutral_venue` ist
deshalb *abgeleitet*, nicht gemessen, und jede Zeile trägt ihre Herkunft
in `venue_source`. Die Regel ist an die **Runde** gebunden, nicht an eine
Jahreszahl, ein Endspiel im Stadion eines Finalisten (zuletzt 2012)
fiele so später als Abweichung auf, statt lautlos richtig zu wirken.
Grenze: Eine einzelne verlegte Partie wäre nicht erkennbar und liefe als
normales Heimspiel mit.

**Kein Verlängerungsstatus.** Alle 503 Partien tragen schlicht
`FINISHED`, weder `AET` noch `PEN`, keine Schützentore. Ob verlängert
wurde, ist daraus nicht ableitbar. Feststellbar wäre nur eine
Untergrenze: Eine über beide Legs ausgeglichene Paarung *muss* im
Elfmeterschießen entschieden worden sein. Im Bestand 2023–2025 gibt es
**0 solche Fälle**. Das ist ohnehin eine Aussage über das *Label* und
steht erst nach Spielende fest, sie wird ausdrücklich **nicht** als
Merkmal geführt.

Bleibt eine echte Label-Grenze: Ging ein Rückspiel in die Verlängerung,
enthält der erfasste Spielstand deren Tore, während die Baseline 90
Minuten modelliert. Diese Zeilen zu *entfernen* wäre schlechter als sie
zu behalten, der Ausschluss hinge am Ergebnis der Partie selbst und
wäre eine Selektion auf die Zielgröße.

#### Wiedergewonnene Zeilen

| | 2023 | 2024 | 2025 | Summe |
| --- | ---: | ---: | ---: | ---: |
| K.-o.-Partien | 29 | 45 | 45 | **119** |
| davon wiedergewonnen | 29 | 45 | 45 | **119** |
| weiterhin ausgeschlossen | 0 | 0 | 0 | **0** |

58 Hinspiele, 58 Rückspiele, 3 Endspiele. Alle 58 Paarungen tragen genau
zwei Partien, kein Einzelspiel und **keine mehrdeutige Paarung**. Keine
der 119 Zeilen scheitert an Profiltiefe oder neutralem Profil, der
Ausschluss lag allein an der fehlenden K.-o.-Logik.

`evaluation_eligible` bleibt bei **238** und bezeichnet weiterhin
ausschließlich die reguläre Phase. Die K.-o.-Zeilen bekommen ein eigenes
Kennzeichen `knockout_eligible`. Hätte C5 den bestehenden Bestand
erweitert, trügen der V1-Shadow-Backtest und die C3-/C4-Ablationen unter
demselben Namen plötzlich andere Zahlen.

#### Der Train/Test-Vertragsbruch

Der bestehende Vertrag trainiert auf nationalen Ligen. Ein Ligaspiel ist
nie ein Rückspiel, nie ein Endspiel, nie auf neutralem Platz und hat nie
einen Aggregatstand. Gemessen:

| | alter Vertrag | Kontextvertrag |
| --- | ---: | ---: |
| C5-Merkmale im Training konstant | **12 von 12** | 1 von 12 |
| Testzeilen | 101 | 146 |

Unter dem alten Vertrag sind die Merkmale nicht „schwach gemessen",
sondern **gar nicht** messbar. C5 deklariert deshalb einen zweiten
Vertrag: Training = nationale Ligen **plus** CL-Zeilen früherer Saisons,
Test = alle auswertbaren CL-Zeilen der Testsaison inklusive K.-o. Die
zeitliche Trennung bleibt unangetastet. `OUTER_FOLDS`, `league_rows()`
und `cl_rows()` sind Wort für Wort unverändert.

Einzig `away_goals_rule_active` bleibt auch dort konstant, alle drei
Saisons liegen nach der Abschaffung.

#### Die Ablation

Acht Varianten unter dem Kontextvertrag, n = 303.

| Variante | Δ gepaart gegen V1 | 95-%-Intervall | Urteil |
| --- | ---: | --- | --- |
| `team_profile_cl` (V1) | – | – | Kontrolle |
| `+ neutral_venue` | +0,001769 | [−0,00418; +0,00952] | REJECTED |
| `+ knockout_context` | +0,007864 | [+0,00052; +0,01480] | REJECTED |
| `+ leg_context` | +0,009211 | [+0,00039; +0,01866] | REJECTED |
| `+ aggregate_state` | +0,012399 | [+0,00090; +0,02573] | REJECTED |
| `+ knockout_structure` | +0,015473 | [+0,00412; +0,02766] | REJECTED |
| `+ tie_state` | +0,017928 | [+0,00383; +0,03373] | REJECTED |
| `+ all_context` | +0,023368 | [+0,00664; +0,04235] | REJECTED |

**7 REJECTED, 0 INCONCLUSIVE, 0 ACCEPTED.** Sechs der sieben Intervalle
liegen **vollständig über null**, die Merkmale sind nicht bloß nutzlos,
sie verschlechtern V1 nachweisbar. Brier und RPS zeigen dieselbe
Richtung; nur `neutral_venue` bleibt in allen drei Maßen neutral.

Die Vorauswahl auf den Trainingsdaten behielt **nichts**: Alle drei
messbaren Untergruppen verschlechterten schon die innere Validierung,
und `neutral_venue` fiel wegen der konstanten Regelspalte heraus.

#### Warum die Merkmale schaden

Kein Rätsel, sondern Bauart. Im Kontexttraining tragen **36 von 3.128
Zeilen (1,2 %)** einen Aggregatstand. Der Median-Imputer füllt die
übrigen 98,8 % mit dem Median der Rückspiele; die Standardisierung
danach macht aus den 36 echten Werten Ausreißer. Ein Ligaphasenspiel
bekommt so einen Aggregatstand, den es per Definition nicht hat.

Die Missingness ist hier nicht zufällig, sondern **definitorisch**: Ein
Aggregat existiert genau dann, wenn die Partie ein Rückspiel ist. Ein
lineares Modell ohne Interaktionsterm kann das nicht ausdrücken,
`aggregate_available` liegt genau deshalb als eigene Spalte bei, aber
ohne Produkt `aggregate × is_second_leg` bleibt sie wirkungslos. Das ist
der konkrete Ansatzpunkt für ein späteres Gesamttraining, nicht ein
Argument gegen die Merkmale an sich.

Die Redundanzdiagnostik zeigt zusätzlich zwei Identitäten **per
Konstruktion**: `aggregate_available ≡ is_second_leg` (r = 1,0000) und
`is_final ≡ neutral_venue` (r = 1,0000). Ohne Spielstättendaten ist
„neutraler Platz" kein eigenes Merkmal, sondern ein umbenanntes
`is_final`.

#### Bekannte Grenze der Messung

Im ersten Fold (`cl_ctx_2024`) teilt die innere Validierung die einzige
Trainingssaison am mittleren Spieldatum. Die K.-o.-Runden liegen
sämtlich in der zweiten Hälfte, die Anpasshälfte enthält deshalb keine
einzige Aggregatzeile, und die Alphawahl dieses Folds sieht die vier
Aggregatspalten nicht. Die äußere Anpassung sieht sie sehr wohl, und
Fold 2 (Teilung nach Saison) ist davon nicht betroffen. Die Einschränkung
steht hier, weil Fold 1 auch der Fold mit den deutlich schlechteren
Werten ist.

Artefakt: `data/ml/c5_context_ablation_2023-2025.json`, Kontextvertrag,
Cutoff-Regel, Regel- und Formatbehandlung, Zeileninventar, Coverage,
Folddefinitionen, Fingerprints je Variante, vollständige Metriken,
Bootstrap, Redundanz, Auswahlprotokoll und bekannte Grenzen.

*V2-C5 ist Analyse. Es ist kein finales V2-Modell und kein Deployment:
Es trainiert Kandidaten ausschließlich zur Messung, speichert kein
Bundle, aktiviert nichts und stuft nichts hoch. Das bestehende Modell
bleibt `experimental` und bitgleich.*

### Snapshot-Sammlung für Kader und Verfügbarkeit (V2-C6)

Ergebnisse lassen sich nachträglich holen. Kaderstände und Verletzungen
nicht: Wer heute fragt, wer dem FC Bayern am 12. November 2025 fehlte,
bekommt vom Anbieter den **heutigen** Stand. Diese Historie entsteht
nur, indem man sie ab jetzt sammelt.

C6 baut die Sammlung. Es berechnet keine Kaderstärke und fügt dem Modell
kein Merkmal hinzu; das ist Aufgabe von C7.

#### Die zwei Quellen und ihre sehr verschiedene Zeitsemantik

Nachgemessen am 06.09.2026 mit **vier** Requests:

| Endpunkt | Was er liefert | Gültigkeitszeitpunkt |
| --- | --- | --- |
| `/players/squads?team=X` | den Kader, **ohne jede Zeit- oder Saisonangabe** | **keiner** |
| `/injuries?league=X&season=Y` | 2832 Einträge für die Bundesliga 2025, **auf einer Seite**, jeder mit `fixture.date` | das Partiedatum |

Der Unterschied ist der Kern des Zeitvertrags:

- `fetched_at`: der Abruf. Belegt ausschließlich: *spätestens jetzt war
  das so.*
- `effective_at`: der von der Quelle behauptete Zeitpunkt.

Fehlt der zweite, bleibt er `None`. Er wird **niemals** aus dem ersten
erfunden. Ein Kadersnapshot trägt deshalb `effective_at: null` und
`effective_at_status: unknown_source_has_no_timestamp`. Eine
Kaderänderung „genau in dieser Sekunde" wäre erfundene Historie, und sie
sähe vollkommen plausibel aus.

#### Was „Availability" hier heißt und was nicht

Der Endpunkt heißt `injuries`, liefert aber mehr. Ausgezählt an einem
echten Snapshot (Bundesliga 2025, 2404 Einträge nach Deduplizierung):

| Kategorie | Anzahl |
| --- | ---: |
| `injury` | 2073 |
| `suspension` | 138 |
| `illness` | 86 |
| `fitness` | 70 |
| `personal` | 36 |
| `coach_decision` | 1 |

**Sperren sind enthalten**, aber als Freitext im selben Feld wie
Verletzungen (`Red Card`, `Yellow Cards`, `Suspended`), nicht als
eigener typisierter Wert. Die Normalisierung ordnet sie zu und behält
den Rohwert daneben; die Musterreihenfolge prüft Sperren **zuerst**,
sonst finge ein Verletzungsmuster einen Eintrag wie „Red card
Suspended" ein.

`fitness` ist eine eigene Kategorie („Lacking Match Fitness",
„Inactive"): als Verletzung geführt behauptete sie einen Schaden, unter
„other" verschwände ein häufiger, klar benannter Zustand.

Zusätzlich unterscheidet `status` zwischen `out` („Missing Fixture",
2266) und `doubtful` („Questionable", 138).

**Die Grenze, ausdrücklich:** Das ist keine vollständige
Verfügbarkeitslage. Ein Spieler ohne Eintrag ist **nicht belegt
einsatzbereit**; er ist nur nicht als Ausfall gemeldet.
Rotationsentscheidungen und nicht gemeldete Blessuren fehlen. Der Satz
steht in jedem Snapshot.

#### Archivformat

Kein neues Speichersystem: C6 benutzt das bestehende
`data/snapshots/<art>/<art>__<schlüssel>__<zeitstempel>.json` und
erweitert es um Fingerprint und strikten Lesevertrag.

- **Append-only.** Eine vorhandene Datei wird nie überschrieben; zwei
  Snapshots derselben Sekunde bekommen einen Zählersuffix.
- **Atomar.** Temporärdatei plus `os.replace`. Bricht das Schreiben ab,
  entsteht **keine** Enddatei, auch keine halbe.
- **Dedupliziert.** Ein Inhaltsfingerprint über die sortierten Nutzdaten
  entscheidet. Ändert sich nichts, wird nichts geschrieben; sonst
  entstünden 365 identische Kaderdateien pro Verein und Jahr.
- **Beschädigte Dateien** werden beim Auflisten übersprungen und
  **nicht** überschrieben.

Die Spielerliste wird nach ID sortiert abgelegt. Ohne feste Sortierung
ergäbe eine andere Reihenfolge beim Anbieter einen anderen Fingerprint,
und das Archiv behauptete eine Änderung, die keine ist.

#### Collector-CLI

```bash
python collect_snapshots.py --daily                 # geplanter Tageslauf
python collect_snapshots.py --daily --dry-run       # nichts schreiben
python collect_snapshots.py --daily --limit 5       # Probemodus
python collect_snapshots.py --teams 157,165         # gezielt
python collect_snapshots.py --leagues bl1,cl --kinds availability
python collect_snapshots.py --coverage              # was liegt im Archiv?
```

| Exit | Bedeutung |
| ---: | --- |
| 0 | `complete`: alles bearbeitet, nichts fehlgeschlagen |
| 3 | `partial`: gesammelt, aber nicht alles |
| 4 | `failed`: nichts Verwertbares |
| 5 | `busy`: ein anderer Lauf hält die Sperre |
| 2 | Aufrufsfehler |

Ein unvollständiger Lauf meldet **nicht** 0. Sonst stünde ein Timer, der
jeden Tag brav „erfolgreich" meldet, monatelang auf grün, während die
Hälfte der Historie fehlt.

#### Umfang und Priorisierung

Gemessener Tageslauf: **430 Scopes**: 24 Ligen für Ausfälle, 406 Teams
für Kader. Bei 7500 Tagesanfragen sind das 5,7 %.

Die Teamliste kostet fast nichts: 278 der 406 Teams stammen aus den
lokalen V2-C2B-Ligadateien (die API-Sports-IDs führen), **null
Requests**. Die übrigen kommen über den bestehenden Siebentagecache von
`/teams`.

Priorität, kleiner Wert zuerst:

| | Was | Warum |
| ---: | --- | --- |
| 0 | Ausfälle Top-5 + CL | eine Anfrage liefert eine ganze Saison |
| 10 | Ausfälle der übrigen nationalen Ligen | dito |
| 50 | Kader der CL-Teilnehmer | eine Anfrage je Verein |
| 60 | Kader der Top-5-Ligen | |
| 90 | Kader der übrigen nationalen Ligen | |

Bricht der Lauf ab, ist der wertvollere Teil gesichert. Ein Verein, der
in Bundesliga **und** Champions League spielt, wird genau einmal
abgefragt, dedupliziert über die tatsächlichen Anfrageparameter.

#### Kontingent, Wiederholung, Fehler

Der bestehende API-Client bleibt unberührt; C6 ergänzt nur, was ein
Livepfad nicht braucht:

- **Kontingentkopfzeilen** werden gelesen
  (`x-ratelimit-requests-remaining` und drei weitere). Der bestehende
  Client verwirft sie.
- **Kontrolliertes Anhalten** bei 500 verbleibenden Tagesanfragen
  (`--quota-margin`), damit der Webbetrieb Luft behält.
- **Wiederholt** wird bei Netzwerkfehler, 429 und 5xx: mit
  exponentiellem Backoff und Jitter, `Retry-After` wird beachtet und
  auf 30 s gedeckelt.
- **Nicht wiederholt** wird bei 400/401/403/404. Ein 404 wird beim
  zweiten Versuch nicht zu einem 200; Wiederholungen verbrauchen dort
  nur Kontingent.
- **Leer ≠ kaputt.** Eine Liga ohne gemeldete Ausfälle ist ein gültiger
  Zustand (`empty`), kein Fehler. Beides zu vermengen wäre der sicherste
  Weg, eine echte Störung zu übersehen.
- **Teilerfolg bleibt.** Jeder Snapshot wird sofort geschrieben; ein
  fehlgeschlagener Scope beendet den Lauf nicht.

#### Sperre

`O_CREAT|O_EXCL`: atomar auf **beiden** Betriebssystemen. `fcntl` gibt
es unter Windows nicht, `msvcrt` nicht unter Linux; die lokale
Entwicklung läuft unter Windows, der VPS unter Ubuntu.

Eine verwaiste Sperre wird übernommen, wenn sie älter als drei Stunden
ist **und** der eingetragene Prozess nachweislich nicht mehr läuft. Nur
nach Alter zu brechen würde einen langsamen, aber lebenden Lauf
abschießen; im Zweifel wird nicht übernommen.

#### Laufbericht

Jeder Lauf schreibt einen maschinenlesbaren Bericht nach
`data/snapshots/_runs/`, Start und Ende, Versionen, geplante gegen
tatsächlich abgefragte Scopes, ausgelassene mit Grund, Requests je
Endpunkt und Ergebnis, Retries, neue und unveränderte Snapshots, Fehler
je Scope, beobachtetes Kontingent, Coverage je Art mit Namen der nicht
erfassten Schlüssel, Fingerprint der Planung, und **keine Secrets**.

#### Der C7-Lesevertrag

```python
from src.data import snapshot_reader as sr

sr.squad_before(team_id, cutoff)                     # letzter Kader davor
sr.availability_entries_before(league_id, season, cutoff)
```

1. Nur Snapshots **strikt vor** dem Cutoff. Ein Stand mit
   `captured_at == cutoff` wird **nicht** geliefert; er könnte zur
   Anpfiffsekunde erhoben worden sein und bereits die Aufstellung
   enthalten. Derselbe Vertrag wie in V2-C1.
2. Fehlt ein Snapshot, kommt ein **sichtbarer** Fehlzustand
   (`available: False`, `missing_reason`), niemals ein leerer Kader und
   niemals eine Null.
3. Jede Antwort trägt Herkunft und `age_days`. Ein Kaderstand von
   gestern ist etwas anderes als einer von vor drei Monaten.
4. Bei mehreren Snapshots derselben Sekunde gewinnt der zuletzt
   geschriebene. Die Regel ist festgelegt und getestet.

**Zwei Zeitebenen bei Ausfällen.** Der Snapshot ist vor dem Cutoff
*erhoben*, seine Einträge beschreiben aber Partien, die danach liegen
können. `availability_entries_before()` filtert deshalb **zusätzlich**
nach `effective_at`; Einträge ohne Zeitpunkt werden getrennt gezählt und
nicht mitgeliefert; unbekannt ist nicht dasselbe wie wahr.

#### Betrieb auf dem VPS

Vorlagen in [`deploy/systemd/`](deploy/systemd/), Installations-,
Status-, Log- und Abschaltbefehle in
[`deploy/systemd/README.md`](deploy/systemd/README.md).

Täglich **04:30 UTC**, nach dem letzten europäischen Anpfiff des
Vortags und vor dem frühesten des laufenden Tages. Ausdrücklich UTC:
Eine Sommerzeitumstellung verschöbe sonst zweimal im Jahr den
Erhebungszeitpunkt. `Persistent=true` holt einen verpassten Lauf nach,
eine Lücke in dieser Historie lässt sich nicht nachträglich schließen.

Der Sammler hängt **nicht** an Gunicorn. Dort liefe er in jedem Worker
und bei jedem Neustart erneut. Die Dateisperre fängt das ab, ist aber
die zweite Verteidigungslinie.

**Der Timer ist vorbereitet, nicht aktiviert.**

#### Datenschutz und Speicherort

`data/snapshots/` ist gitignoriert, Rohdaten des Anbieters bleiben auf
dem Host. Das gilt auch für die Laufberichte: Sie tragen zwar keine
Rohdaten, aber Bezeichner, Kontingentstände und Fehlermeldungen genau
dieses Hosts. Zusammengeführt ergäben zwei Hosts eine Historie, die es
so nie gab.

Im Repository liegen stattdessen die **reproduzierbaren** Teile: Schema,
Sammlervertrag, Lesevertrag und die systemd-Vorlagen. Aus ihnen lässt
sich jede Sammlung nachvollziehen, nur eben nicht nachträglich
erzeugen.

*V2-C6 sammelt. Es trainiert kein Modell, aktiviert nichts und fügt dem
Modellvertrag kein Merkmal hinzu. Das bestehende Modell bleibt
`experimental` und bitgleich.*

### Kaderhistorie, Transfers und Vorsaisonstärke (V2-C7)

Erstmals in der V2-Reihe zeigen **alle** geprüften Varianten in die
richtige Richtung. Aufgenommen wird trotzdem nichts: Kein
Konfidenzintervall schließt die Null aus. Der Kandidat bleibt
`team_profile_cl`.

#### Zwei Informationsklassen: Codevertrag statt Absichtserklärung

| Klasse | Was | Verfügbar |
| --- | --- | --- |
| **A**: historisch rekonstruierbar | datierte Transferereignisse, abgeschlossene Vorsaisons | rückwirkend |
| **B**: erst seit C6 beobachtbar | Kader- und Verfügbarkeitssnapshots | ab `usable_from` |

`squad_history.data_class()` ordnet jeder Merkmalsfamilie ihre Klasse zu
und **bricht bei einer unbekannten ab**, ein stillschweigendes
„vermutlich Klasse A" ist genau die Annahme, die der Vertrag verhindert.
`class_b_is_usable()` entscheidet am *tatsächlichen* Archiv, nicht an
einer Zusicherung.

#### Was der Bestand hergibt: nachgemessen

| Quelle | Umfang | Grenze |
| --- | --- | --- |
| Transferereignisse (`data/cache/`) | 155 Dateien, 84.943 normalisierte Ereignisse, 24.404 Spieler, 3.346 Vereine | ein Datum je Wechsel, **keine** Unterscheidung Bekanntgabe/Wirksamkeit |
| Spielerpool (`data/player_pool/`) | 35 Dateien, 5 Ligen, Saisons 2020–2026 | **kein Datums- und kein Spieltagsfeld**, keine `team_id` |
| Snapshot-Archiv (C6) | 0 Kader-, 1 Verfügbarkeitssnapshot | jünger als jede CL-Partie |

Beide erstgenannten Quellen sind **gitignoriert**. Der Datensatzbau
liest sie deshalb nur auf ausdrückliche Anforderung
(`INCLUDE_SQUAD_HISTORY_BY_DEFAULT = False`), dieselbe Entscheidung wie
beim UEFA-Schalter in C4, und aus demselben Grund: Ein bestehender Test
verlangt, dass der Standardbau ausschließlich `data/historical` liest.

#### Der Stichtagsvertrag

Alle Transferfenster filtern **strikt vor** dem Spieltag. Ein Wechsel,
dessen einziges bekanntes Datum der Spieltag ist, geht *nicht* ein. Der
Anbieter unterscheidet nicht zwischen Bekanntgabe und Wirksamkeit, und
das ist die konservative Lesart.

Leistungswerte stammen ausschließlich aus **abgeschlossenen** Saisons
(≤ S−1). Der Pool ist eine Saisonaggregation ohne Datum; für ein Spiel
im Oktober der Saison S wäre er die Statistik einer Saison, die im Mai
darauf endet: die Vorhersage der Saison mit ihrem eigenen Ergebnis.

#### Spieleridentität

Primärschlüssel sind die API-Sports-`player_id` und `team_id`. Der Pool
trägt **keine** `team_id`, nur `team_name`. Eine Zuordnung über den
Namen findet deshalb *nicht* statt; die Verknüpfung läuft ausschließlich
über `player_id` (85,6 % Überschneidung mit der Transferhistorie).

Die CL-Historie stammt von football-data und trägt andere Kennungen.
`squad_crosswalk` baut die Brücke aus zwei Quellen, den 27 in C2B
einzeln geprüften Vereinen und den nationalen Pokaldateien für die
übrigen. Ergebnis: **63 von 63 CL-Vereinen aufgelöst, 0 Widersprüche, 0
doppelte Ziele.** Ein Widerspruch würde den Eintrag *entfernen*, nicht
überschreiben: Unbekannt ist besser als vielleicht falsch.

Zur Größenordnung der Gefahr: Eine naive Gleichsetzung beider
Nummernkreise „trifft" 55 von 63 Vereinen und liegt dabei durchweg
falsch.

#### Was nicht gebaut wurde, obwohl es naheliegt

**Keine Kadertiefe.** Die aus Transfers ableitbare Zugehörigkeit
überzählt systematisch: Sie sieht jeden Zugang, aber nur die
*gemeldeten* Abgänge; ein auslaufender Vertrag hinterlässt keinen
Eintrag. Nachgemessen: **Median 42** gegen rund 30 in einem echten
Einsatzkader. Sie läuft als Diagnose mit (`derived_membership_upper_bound`)
und ist **kein Modellmerkmal**; eine Zahl, die um ein Drittel
danebenliegt, wäre als „Kadertiefe" schlicht falsch.

Stattdessen misst C7, was ohne Mitgliedschaftsableitung auskommt: **wer
kam und ging, und wie stark waren diese Spieler in ihrer letzten
abgeschlossenen Saison.**

#### Merkmalsfamilien

| Untergruppe | Inhalt | Coverage (CL) |
| --- | --- | ---: |
| `transfer_volume` | Zu-/Abgänge in 365 und 120 Tagen, Leihen getrennt | 100,00 % |
| `transfer_balance` | Nettoveränderung beider Fenster | 100,00 % |
| `transfer_strength` | mittlere Vorsaisonbewertung der Wechsler und deren Differenz | 89,5–95,5 % |

Nur Spieler mit mindestens **270 Minuten** in einer abgeschlossenen
Saison gehen in die Stärkerechnung ein. Darunter ist eine Bewertung
kein Mittelwert, sondern ein Einzelereignis. Die Bewertung ist eine
**Anbietermeinung**, keine Messung; sie ist die einzige über alle
Positionen vergleichbare Größe.

#### Nicht bewertbar: mit Beweis

| Familie | Status | Grund |
| --- | --- | --- |
| `squad_snapshot` | `NOT_EVALUABLE` | 0 Kadersnapshots |
| `availability_impact` | `NOT_EVALUABLE` | einziger Snapshot vom 06.09.2026 |

Die späteste CL-Partie dieses Bestands liegt am **2026-05-30**, der
einzige Snapshot am **2026-09-06**. Jede Beobachtung liegt damit *nach*
jeder auszuwertenden Partie. Es werden bewusst **keine Metriken**
ausgewiesen, eine Zahl ohne Beobachtung wäre schlimmer als eine Lücke,
weil sie wie ein Ergebnis aussieht.

**Reevaluationskriterium:** erst mit CL-Partien, die *nach* dem
Sammelbeginn liegen. Konkret, sobald
`archive_window('squad').usable_from` vor dem Datum der auszuwertenden
Partien liegt und mindestens eine volle Saison gesammelt wurde. Dafür
muss der C6-Timer laufen; er ist vorbereitet und nicht aktiviert.

#### Die Ablation

Sechs Varianten, Vertrag und Gate wie C3/C4 (Training nationale Ligen,
Test CL-Reguläphase, n = 213).

| Variante | Δ gepaart gegen V1 | 95-%-Intervall | Brier | Urteil |
| --- | ---: | --- | ---: | --- |
| `team_profile_cl` (V1) | – | – | −0,00464 | Kontrolle |
| `+ all_squad_history` | **−0,009359** | [−0,02758; +0,00923] | −0,01076 | INCONCLUSIVE |
| `+ transfer_activity` | −0,005873 | [−0,02273; +0,01172] | −0,00882 | INCONCLUSIVE |
| `+ transfer_volume` | −0,005344 | [−0,02184; +0,01226] | −0,00862 | INCONCLUSIVE |
| `+ transfer_strength` | −0,005225 | [−0,01538; **+0,00489**] | −0,00777 | INCONCLUSIVE |
| `+ transfer_balance` | −0,003961 | [−0,01572; +0,00770] | −0,00785 | INCONCLUSIVE |
| `+ squad_reduced` | −0,003961 | [−0,01572; +0,00770] | −0,00785 | INCONCLUSIVE |

**6 INCONCLUSIVE, 0 REJECTED, 0 ACCEPTED.** Zum ersten Mal in der
V2-Reihe verbessert *jede* Variante den Punktschätzer, und Brier sowie
RPS zeigen dieselbe Richtung. `all_squad_history` ist in **beiden**
Folds negativ (−0,0182 / −0,0183): ungewöhnlich stabil.

Gegen eine Aufnahme sprechen zwei Dinge: Kein Intervall schließt die
Null aus, und die **Kalibrierung verschlechtert sich** durchgehend
(V1 0,0165 → 0,0215 bis 0,0431). `transfer_strength` hat das engste
Intervall und die geringste Kalibrierungseinbuße.

Die Vorauswahl auf Trainingsdaten behielt nur `transfer_balance`
(max VIF 1,47, keine exakte Abhängigkeit), dieselbe Variante kommt auf
CL-Partien auf −0,00396.

#### Aufnahmeentscheidung

**V1 bleibt unverändert.** Die C7-Merkmale sind technisch fertig,
PIT-sicher und vollständig getestet; sie werden als `experimental`
geführt und nicht aktiviert. Das Modellbundle bleibt bitgleich.

Artefakt: `data/ml/c7_squad_history_ablation_2023-2025.json`, mit
Quelleninventar, Zeit- und Cutoff-Verträgen, Identitätsdiagnostik,
Coverage, `NOT_EVALUABLE`-Begründungen samt Beweis, Fingerprints,
vollständigen Metriken, Redundanz und Reevaluationsbefehl.

#### Bekannte Grenzen

- Der Anbieter unterscheidet **nicht** zwischen Bekanntgabe- und
  Wirksamkeitsdatum eines Transfers.
- Leihenden und Vertragsdaten fehlen; eine Rückkehr ist nur sichtbar,
  wenn sie als eigenes Ereignis gemeldet wurde (3.886 von 84.943).
- Der Spielerpool deckt nur die fünf Top-Ligen, ein Spieler von
  außerhalb trägt keinen Vorsaisonwert und ist damit *unbekannt*, nicht
  schwach.
- Marktwerte werden nicht verwendet: Eine Ablösesumme ist ein
  Marktpreis, kein Leistungsmaß.

*V2-C7 ist Analyse. Es trainiert Kandidaten ausschließlich zur Messung,
speichert kein Bundle, aktiviert nichts und stuft nichts hoch. Das
bestehende Modell bleibt `experimental` und bitgleich.*

### Modellklasse, Interaktionen, Kalibrierung (V2-C8)

C3 bis C7 haben gezeigt, dass *mehr Merkmale* in derselben Modellklasse
wenig bringen. C8 fragt, ob die **Klasse** das Problem war, und
beantwortet die Frage mit **nein**, an drei Stellen einzeln nachgemessen.

**Kein Kandidat wird aufgenommen. Das Modellbundle bleibt bitgleich.**

#### Warum zwei Auswertungsverträge

Die zwölf C5-Kontextmerkmale sind im ursprünglichen Vertrag **konstant**
, gemessen, in Training *und* Test. Eine Interaktion auf einem
konstanten Merkmal ist ebenfalls konstant. Die Interaktionskandidaten
laufen deshalb unter dem **Kontextvertrag** (n = 303), die
Transformationskandidaten unter dem **Standardvertrag** (n = 213).

Jeder Kandidat wird ausschließlich gegen den V1-Kontrollarm **seines**
Vertrags gelesen, und beide Kontrollarme laufen im selben Lauf mit.
Zahlen über die Vertragsgrenze hinweg zu vergleichen wäre der bequemste
Weg zu einem falschen Ergebnis.

#### Die Kandidatenmatrix: vorab festgelegt

| Kandidat | Rolle | Vertrag | Was | Δ gepaart gegen Kontrolle | Urteil |
| --- | --- | --- | --- | ---: | --- |
| `M0_v1_control` | Kontrolle | Standard | unverändertes V1 | – | Kontrolle |
| `M1_c7_transformed` | Kandidat | Standard | C7 mit `log1p` | −0,006860 | INCONCLUSIVE |
| `M1c_…_calibrated` | Kandidat | Standard | M1 + Kalibrator | −0,008431 | INCONCLUSIVE |
| `M1r_c7_raw_control` | Kontrollarm | Standard | C7 **roh** | −0,009359 | – |
| `M0_v1_control_context` | Kontrolle | Kontext | unverändertes V1 | – | Kontrolle |
| `M2_c5_interactions` | Kandidat | Kontext | C5 als Interaktionen | +0,022717 | REJECTED |
| `M2r_c5_raw_control` | Kontrollarm | Kontext | C5 **roh** | +0,023368 | – |
| `M3_…_plus_interactions` | Kandidat | Kontext | M1 + M2 | +0,010467 | REJECTED |
| `M4_reduced` | Kandidat | Kontext | regelbasiert reduziert | +0,009176 | REJECTED |
| `M5_elastic_net_glm` | – | – | – | – | **NOT_EVALUATED** |

**0 ACCEPTED, 3 REJECTED, 2 INCONCLUSIVE, 1 NOT_EVALUATED.**

#### Eine unabhängige Bestätigung, ganz nebenbei

`M1r_c7_raw_control` ist V1 plus die rohen C7-Merkmale, also genau das,
was V2-C7 als `+ all_squad_history` gemessen hat. C7 berichtete
**−0,009359**; C8 misst **−0,009359**, auf sechs Nachkommastellen, durch
eine vollständig andere Codestrecke (`c8_ablation` statt `cl_ablation`)
und mit eigener Alphawahl. Das war kein Ziel dieses Blocks, aber es ist
der beste verfügbare Beleg dafür, dass beide Ablationsmaschinen
dasselbe rechnen.

#### Die drei isolierten Wirkungen: der eigentliche Befund

Die Zahlen gegen V1 vermengen zwei Dinge: die zusätzlichen Merkmale und
deren *Behandlung*. Erst der Vergleich Arm gegen eigenen Kontrollarm,
beide im selben Lauf, auf demselben Bestand, trennt beides.

| Wirkung | Vergleich | Δ LogLoss | Kalibrierungsfehler | Befund |
| --- | --- | ---: | --- | --- |
| **Transformation** | M1 gegen M1r | **+0,002499** | 0,0431 → 0,0526 | **verschlechtert beides** |
| **Kalibrierung** | M1c gegen M1 | −0,001570 | 0,0526 → **0,0273** | verbessert beides |
| **Interaktion** | M2 gegen M2r | −0,000651 | 0,0238 → 0,0225 | verbessert, aber winzig |

**Die Transformationshypothese war falsifizierbar und wurde falsifiziert.**
Der Anlass war real und nachgemessen, `arrivals_365d` hat im Training
Median 16, im Test 32, `arrivals_120d` trägt Schiefe +2,06, , aber
`log1p` verschlechtert Punktschätzer *und* Kalibrierung. Der lineare
Koeffizient kam mit dem Skalenversatz offenbar besser zurecht als die
gestauchte Skala. Das ist das Ergebnis; es wird nicht umgedeutet.

**Die Kalibrierung funktioniert wie entworfen** und halbiert den
Kalibrierungsfehler (0,0526 → 0,0273), reicht aber nicht an V1 heran
(0,0165). Sie repariert einen Schaden, den die zusätzlichen Merkmale
selbst angerichtet haben.

**Die definitorische Null ist besser als der imputierte Median**, die
C5-Diagnose war richtig. Nur ist der Effekt mit −0,00065 klein gegen den
Schaden der C5-Merkmale insgesamt: Beide C5-Arme liegen deutlich
schlechter als der V1-Kontrollarm desselben Vertrags (−0,009763). Die
Merkmale sind das Problem, nicht ihre Imputation.

#### Was gebaut wurde

**Transformationen** (`src/ml/model_class.py`), `log1p` für Zählwerte,
`sign(x)·log1p(|x|)` für Nettowerte, optionale Winsorisierung beim
99-%-Quantil. Die Grenzen werden **ausschließlich** im `fit()` des
Trainingsfolds gelernt; ein Test hält fest, dass ein Ausreißer im
Testbestand sie nicht verschiebt. `NaN` überlebt jede Transformation,
der Schritt **formt**, der Imputer **füllt**.

**Interaktionen**, vier, jede einzeln begründet, keine automatische
Paarkreuzung. Die zentrale Regel:

> Ist der Indikator null, ist das Produkt **exakt null**, auch bei
> fehlendem Wert. „Nicht anwendbar" ist kein fehlender Messwert,
> sondern eine bekannte Tatsache.

Genau hier trennt sich C8 von C5: Dort wurde aus der fehlenden Angabe
ein Medianwert für 85 % der Zeilen, hier wird aus ihr eine Null. Bei
Indikator **eins** und fehlendem Wert bleibt es `NaN`, das ist ein
echter Fehlwert, und dafür ist der Imputer da.

**Kalibrierung**, multiplikativ (Momentenschätzer, keine Iteration)
oder log-linear. Gelernt **nur** auf den Vorhersagen der *inneren*
Validierung. Fällt sicher zurück und nennt dabei immer einen Grund: zu
wenige Zeilen, keine Streuung, Faktor außerhalb [0,5; 2,0]. Die
Lambdagrenzen greifen **nach** der Kalibrierung erneut.

**Ein Codepfad.** `model.build_pipeline(alpha, transform)` ist die
einzige Stelle im gesamten `src/`-Baum, an der eine `Pipeline`
zusammengesetzt wird, ein Test prüft genau das per AST. Ohne
Transformation liefert sie unverändert `imputer → scaler → regressor`.
Mit Transformation steht diese **vor** dem Imputer: danach träfe sie
Medianwerte statt Messwerte.

#### Reihenfolge als Leakageschutz

Je äußerem Fold: Verträge wählen → Training **innen** teilen → Alpha auf
der inneren Validierung → Kalibrator auf **denselben** inneren
Vorhersagen → mit gewähltem Alpha auf dem **gesamten** Training
anpassen → **einmal** außen messen. Der äußere Test geht in keinen der
vorgelagerten Schritte ein; drei AST-Tests halten das fest.

#### M5: nicht ausgewertet, nicht gescheitert

`sklearn.PoissonRegressor` kennt nur eine L2-Strafe. Elastic Net
erforderte entweder `statsmodels` (im Projekt nicht vorhanden, neue
schwere Abhängigkeit) oder eine eigene IRLS-Implementierung mit
Koordinatenabstieg, neuer, ungetesteter numerischer Code im Kern der
Modellrechnung, bei 213 bis 303 Testpartien. **Reevaluation**, sobald
der Testbestand deutlich wächst und eine Sparsamkeitsstrafe über viele
Merkmale überhaupt etwas zu wählen hätte.

Ebenso wenig gebaut: Bäume, Boosting, neuronale Netze, automatische
Merkmalssuche. Bei dieser Bestandsgröße wäre ein großer Suchraum eine
Übung im Überanpassen.

#### Das Aufnahmegate

Zehn Bedingungen, alle vorab festgelegt: negatives gepaartes Delta gegen
die Kontrolle **desselben Vertrags**, gleiche Richtung in **beiden**
Folds, oberes 95-%-Bootstrapintervall unter null, Brier und RPS nicht
schlechter, Kalibrierungsfehler höchstens **25 %** über der Kontrolle,
kein Fold trägt über 90 % des Gewinns, alle Anpassungen konvergiert,
zusätzliche Merkmale nur bei negativem Delta, n ≥ 30.

Bestünden mehrere Kandidaten, gewönne **nicht** der beste
Punktschätzer, sondern der einfachste.

Die 25 % stehen vorab und nicht nachträglich: V1 erreicht 0,01647, ein
Viertel schlechter wäre 0,02059, C7 lag zwischen 0,0215 und 0,0431 und
scheiterte genau daran.

M1 und M1c verbessern den Punktschätzer in **beiden** Folds und
scheitern an zwei Bedingungen: Das Intervall schließt die Null nicht
aus ([−0,0286; +0,0123] für M1c), und die Kalibrierung liegt 66 % über
V1.

#### Reproduzierbarkeit

Zweimal gelaufen, identischer Ergebnisfingerabdruck
`c5f9f61c…3561aa`. Ausgeklammert ist ausschließlich `runtime_seconds`,
zwei Läufe liefern nie dieselbe Wanduhrzeit, aber sie müssen dieselben
Zahlen liefern; auch das prüft ein Test.

Artefakt: `data/ml/c8_model_class_ablation_2023-2025.json`, mit
Kandidatenmatrix samt Hypothesen, beiden Verträgen, je Kandidat einem
Datensatzfingerabdruck, Verteilungsdiagnose, Interaktionsvarianz,
Alphawahl je Fold, vollständigen Metriken, Bootstrapintervallen,
Gate-Bedingungen einzeln, isolierten Wirkungen und
`NOT_EVALUATED`-Begründung.

#### Bekannte Grenzen

- Zwei Auswertungsverträge; Zahlen über die Vertragsgrenze hinweg zu
  vergleichen ist unzulässig. Jeder Kandidat trägt seinen Vertrag im
  Ergebnis.
- n = 213 beziehungsweise 303. Breite Bootstrapintervalle sind hier eine
  Eigenschaft des Bestands, keine Schwäche des Verfahrens.
- Sechs Kandidaten gegen dieselbe Kontrolle, ohne Korrektur für
  multiples Testen, deshalb verlangt das Gate zusätzlich
  Richtungsgleichheit in beiden Folds.
- Der Kalibrator wird auf der inneren Validierung gelernt. Deren
  Verteilung ist die der nationalen Ligen, nicht die der CL, der Faktor
  ist auf den Testbestand *übertragen*, nicht dort gemessen.
- M1, M1c und M3 brauchen die gitignorierten C7-Quellen und sind ohne
  sie nicht reproduzierbar.

*V2-C8 ist Analyse. Es trainiert Kandidaten ausschließlich zur Messung,
speichert kein Bundle, aktiviert nichts und stuft nichts hoch. Das
bestehende Modell bleibt `experimental` und bitgleich.*

### Early-V2-Konsolidierung und Feature-Freeze (V2-C9)

C0 bis C8 haben **130 Modellmerkmale in 13 Familien** gebaut, gemessen
und größtenteils *nicht* aufgenommen. Diese Information lag danach
verteilt in sechs Ablationsartefakten, mehreren Registries und einem
README. C9 führt sie an einer Stelle zusammen, und misst dabei nichts
Neues.

**Der ausgewählte Kandidat bleibt V1 `team_profile_cl` mit 16
Merkmalen.**

#### Die zentrale Regel

> Ein Merkmal gelangt **nicht** in den finalen Kandidaten, nur weil es
> technisch existiert.

Das ist keine Absichtserklärung, sondern maschinell geprüft:
`selected_columns()` bricht ab, sobald eine Familie mit einem anderen
Status als `SELECTED` hineinragt. Sechs Tests greifen jede einzelne
nicht erlaubte Statusklasse an, ein siebter den anderen Weg hinein, das
Erweitern der Variantendefinition.

#### Vier Ebenen, sauber getrennt

| Ebene | Frage | Umfang |
| --- | --- | ---: |
| 1, roh verfügbar | Welche Quellen gibt es? | 6 Quellen |
| 2, technisch berechenbar | Was lässt sich PIT-sicher bauen? | 130 Merkmale |
| 3, statistisch geprüft | Was wurde gemessen? | 13 Familien |
| 4, zugelassen | Was benutzt der Kandidat? | **16 Merkmale** |

#### Status aller Familien

| Familie | Block | Status | Merkmale | Grund (gekürzt) |
| --- | --- | --- | ---: | --- |
| `profile` | C0/C2 | **SELECTED** | 16 | einziger Satz mit Intervall unter null |
| `profile_depth` | C2 | REJECTED | 2 | beschreibt die Quelle, nicht die Mannschaft |
| `league_average` | C0/C2 | EXPERIMENTAL | 4 | steckt schon in der Baseline |
| `workload` | C3 | REJECTED | 18 | 12/12 konstant oder uninformativ |
| `workload_extra` | C3 | REJECTED | 4 | per Konstruktion redundant |
| `workload_difference` | C3 | REJECTED | 5 | keine neue Information |
| `schedule_strength` | C3 | REJECTED | 6 | kein Arm unter null |
| `form` | C4 | INCONCLUSIVE | 28 | Richtung stimmt, Intervall nicht |
| `form_opponent` | C4 | INCONCLUSIVE | 4 | wie `form` |
| `uefa` | C4 | EXPERIMENTAL | 6 | kein Beleg; Quelle gitignoriert |
| `form_difference` | C4 | INCONCLUSIVE | 3 | wie `form` |
| `match_context` | C5 | REJECTED | 12 | im Standardvertrag konstant, im Kontextvertrag schlechter |
| `squad_history` | C7 | INCONCLUSIVE | 22 | alle Varianten richtig gerichtet, keine belegt |

Dazu sechs Bausteine **ohne** eigene Merkmalsspalte:
`baseline_lambda` (BASELINE\_ONLY), `team_crosswalk` und
`snapshot_infrastructure` (INFRASTRUCTURE\_ONLY), `squad_snapshot` und
`availability_impact` (NOT\_EVALUABLE), `model_class_extension`
(REJECTED). Sie zu führen ist der Unterschied zwischen „wurde nicht
gebaut" und „wurde gebaut und trägt kein Merkmal".

Jeder Status nennt ein **belegendes Artefakt**; ein Test verlangt es.
Ohne diesen Verweis wäre der Status eine Behauptung.

#### Eine Wahrheitsquelle, keine zweite Liste

Die Merkmalsnamen kommen ausnahmslos aus
`feature_groups.build_groups()`. `early_v2.py` fügt **Metadaten** hinzu,
niemals Namen, ein Test vergleicht beide Mengen. `validate_registry()`
bricht ab bei einer Gruppe ohne Eintrag, einem Eintrag ohne Gruppe,
einem unbekannten Status oder einem Status ohne Begründung.

#### Zwei Datensatzansichten

| | Research | Selected |
| --- | --- | --- |
| Merkmale | 102 (130 mit privaten Quellen) | **16** |
| enthält Verworfenes | ja, das ist der Zweck | nein |
| Zweck | Forschung, Ablation, Diagnostik | verbindlicher Eingang für C10 |

Beide nutzen **denselben** zentralen `build_dataset()`; `early_v2`
projiziert nur. Ein Test prüft per AST, dass es dort keinen zweiten
Datensatzbau gibt. Zeilenmenge, Zeilenidentität und Zielwerte sind in
beiden Ansichten identisch, nur die Merkmalsspalten unterscheiden sich.

Fehlt eine angeforderte Spalte, bricht die Projektion ab. Sie
stillschweigend mit `None` zu füllen hieße, eine Lücke als Messwert
auszugeben.

#### Gitignorierte Quellen fehlen sichtbar

`uefa` und `squad_history` liegen außerhalb der Versionsverwaltung. Aus
einem frischen Checkout gebaut, trüge jede ihrer Spalten in *jeder*
Zeile `None`. Sie erscheinen deshalb nur, wenn die Quelle ausdrücklich
angegeben wurde, eine Spalte, die aussieht wie ein Merkmal und keines
ist, ist die schlechtere Variante von „fehlt". Der **Kandidaten**\-
datensatz ist davon unberührt und aus jedem Checkout reproduzierbar.

#### Die geschlossene Fingerprint-Lücke

Der frühere Fingerprint erfasste die Torziele nicht durchgängig, ein
Datensatz mit vertauschten Ergebnissen hätte identisch ausgesehen. C9
trennt vier Hashes:

| Hash | Was ihn ändert |
| --- | --- |
| `target` | Tore, Ergebnis, Zeilenidentität |
| `research_dataset` / `selected_dataset` | zusätzlich Merkmalswerte, Baseline, Merkmals**menge** |
| `schema` | Gruppenzuschnitt, Status, Kandidat, Modellfamilie, Stichtagsregel, **ohne eine Datenzeile** |

Neu in der Identität: `home_id`, `away_id`, `matchday`,
`knockout_eligible`. Ohne die Team-IDs ließen sich in einer Zeile die
Mannschaften vertauschen, ohne dass sich der Hash ändert, und das wäre
eine andere Partie. Teamnamen stehen **nicht** drin: Ein umbenannter
Verein wäre sonst eine geänderte Datenlage.

Die Merkmalsreihenfolge ist kanonisch sortiert. Eine andere
*Reihenfolge* derselben Menge ist derselbe Stand, eine andere *Menge*
ein anderer. Zehn Tests greifen jede dieser Zusagen einzeln an.

#### Der Stichtag ist jetzt eine benannte Regel

Vor C9 stand `T12:00:00` als Zeichenkette mitten im Datensatzbau. Jetzt:
`dataset.PREDICTION_CUTOFF_HOUR = 12`, `CUTOFF_INCLUSIVE = False`,
`prediction_cutoff(datum)`. Ein Zeitvertrag, den man nur durch Codelesen
erfährt, lässt sich nicht zitieren und nicht testen.

**Bekannte Grenze, offen dokumentiert:** Das ist ein *Tages*stichtag,
kein Anstoßzeitpunkt, die Ligadateien führen kein verlässliches
Anstoßzeitfeld. Rest-Risiko: eine *fremde* Partie mit Anstoß vor 12:00
am Spieltag kann in Ligadurchschnitt oder Gegnerstärke eingehen. Die
beiden beteiligten Mannschaften sind ausgeschlossen, sie spielen nicht
zweimal am selben Tag.

#### Leak-Prüfung: Beweis statt Faustregel

Der erste Entwurf verbot Merkmalsnamen, die auf einen Zielwert enden,
und hätte damit `league_avg_home_goals` verworfen, den Ligadurchschnitt
über *andere* Partien. Ein Ausnahmeverzeichnis wäre die bequeme Lösung
gewesen; es würde einmal geprüft und danach geglaubt.

Stattdessen wird bei **jedem** Bau bewiesen: Gibt es (Liga, Datum)\-
Gruppen mit *verschiedenen* Zielwerten, in denen die Spalte konstant
bleibt, kann sie keine Funktion des zeileneigenen Ergebnisses sein. Im
echten Bestand: 1867 Gruppen, davon **1176 unterscheidend**. Findet sich
kein Beweis, lautet das Ergebnis `undecided` und zählt als Verstoß, was
nicht bewiesen werden kann, gilt nicht als bewiesen.

Eine gepflanzte Leckspalte wird erkannt (100 % Trefferquote, 0
unterscheidende Gruppen).

#### Manipulationstests

Ein sauberer Datensatz beweist *nicht*, dass die Zeitfilterung greift,
nur, dass sie diesmal nichts zu tun hatte. Deshalb wird zukünftige
Information absichtlich eingespeist:

- eine Partie **nach** dem Stichtag → Formmerkmale unverändert
- eine Partie **genau zum** Stichtag → zählt nicht (die Grenze ist strikt)
- ein Transfer **am Spieltag** → geht nicht ein
- ein Snapshot **nach** dem Stichtag → nicht gelesen
- ein Aggregat **im Hinspiel** → Verstoß
- ein Ausreißer **nur im Testfold** → verschiebt keine foldlokale Grenze
- doppelte `row_id` → erkannt

#### Kein unangetasteter Holdout, und das steht auch so im Manifest

Die Saisons **2023–2025 sind kein unangetasteter Testbestand**. Sie
haben die C2-Ablation, die C2B-Übertragung, die C3–C7-Merkmals\-
entscheidungen und die C8-Modellklasse getragen. Jede weitere Messung
auf ihnen ist höchstens konfirmatorisch für eine Hypothese, die aus
denselben Daten stammt.

| Einstufung | Blöcke |
| --- | --- |
| explorativ | C3, C4, C5, C7 |
| konfirmatorisch *innerhalb derselben Daten* | C8 |
| nur Regression | C9 |

Ein echter Holdout entsteht erst mit CL-Partien, die zum Zeitpunkt aller
bisherigen Entscheidungen noch nicht gespielt waren, also Saison
2026/27 aufwärts. Kein Umsortieren des bestehenden Bestands kann das
ersetzen.

#### Training–Runtime-Parität: verifiziert und offen

**Verifiziert:** Merkmalsnamen, Reihenfolge, Imputation, Skalierung,
keine Transformation, keine Interaktionen, Modellfamilie, Guardrails,
und dass `model.build_pipeline` die einzige Stelle ist, die eine
Pipeline zusammensetzt.

**Nicht verifizierbar, als Blocker dokumentiert:** Die Runtime führt
keinen ausdrücklichen `prediction_cutoff` mit. Beide Wege dürften in der
Praxis dasselbe liefern; nachweisen lässt es sich nicht, und eine
Vermutung gehört nicht in eine Paritätszusage. C9 baut den produktiven
Vorhersagepfad **nicht** um, das wäre ein Umbau in einem Block, der
ausdrücklich nichts aktiviert. Folgepunkt für C10–C12.

#### ML-Modus und individueller Modus bleiben getrennt

| | ML-Modus | Individueller Modus |
| --- | --- | --- |
| nutzt | ausschließlich den trainierten Kandidaten | vollständig manuelle Szenariosimulation |
| verboten | Nutzerregler, manuelle Faktoren, requestspezifische Änderung | jeder ML-Einfluss, ein ML-Gewicht |

Beide beantworten verschiedene Fragen: Ein Modell sagt, was zu erwarten
ist; eine Szenariosimulation sagt, was wäre wenn. Sie zu mischen ergibt
eine Zahl, die keine der beiden Fragen beantwortet.

**C9 baut den Reglervertrag nicht um**, das ist ein eigener Produkt-
und UI-Block nach V2-C12. C9 schreibt die Trennung nur auf, damit der
nächste Block sie nicht neu erfindet.

#### Reproduktion

```
python run_ml.py --freeze-c9 --output data/ml/c9_early_v2_manifest_2023-2025.json
```

Liest ausschließlich lokale Quellen, ruft keine API auf, trainiert
nichts, schreibt kein Bundle und verändert keine Datei außer der
angegebenen Ausgabe. Zweimal gelaufen, identischer Manifest\-
fingerprint `d432cf39…`. Ausgenommen sind nur Erzeugungszeitpunkt und
git-Block, Letzterer, weil der erste Lauf das Manifest schreibt und der
zweite sonst eine ungetrackte Datei mehr zählte.

Ebenfalls ausgenommen: `data/snapshots/_runs`, die Laufberichte des
C6-Sammlers. Sie sind Betriebsprotokoll, nicht Beobachtung, ein
zusätzlicher Sammellauf legt dort eine Datei ab, ohne dass sich eine
einzige gesammelte Beobachtung geändert hätte. Aufgefallen ist das nicht
am Schreibtisch, sondern beim Doppellauf *während* der Testsuite: Die
C6-Tests schreiben Laufberichte, und der Fingerprint wanderte zwischen
zwei Berechnungen.

`--source-fingerprints inventory` ist um Größenordnungen schneller
(6 s statt ~2 min über 27.000 Cache-Dateien) und **ausdrücklich kein**
Reproduktionsnachweis: Eine geänderte Zahl gleicher Länge bliebe
unsichtbar. Der Modus steht im Ergebnis, damit niemand die beiden
verwechselt.

#### Was C9 nicht getan hat

Nichts gemessen, kein Modell ausprobiert, keine Hyperparametersuche,
kein verworfenes Merkmal neu verpackt, keinen neuen Testfold erfunden.
Alle Statuswerte stammen aus C2 bis C8; C9 fasst zusammen und prüft auf
Widerspruchsfreiheit.

Technische V2-Fertigstellung und statistische Modellpromotion bleiben
**getrennte Begriffe**: Die V2-Infrastruktur ist deutlich größer
geworden, der ausgewählte statistische Kandidat ist weiterhin V1.

*V2-C9 friert ein. Es trainiert nichts, aktiviert nichts, stuft nichts
hoch und verändert weder Modellbundle noch `persist.py` oder
`inference.py`. Das bestehende Modell bleibt `experimental`.*

### Ein Prediction-Cutoff für Training, Replay und Runtime (V2-C10)

C9 hat einen Blocker offen gelassen: Der Stichtag wurde nicht
durchgängig geführt. C10 schließt ihn.

Die Regel lautet: Für eine Vorhersage dürfen nur Informationen
verwendet werden, die zum festgelegten `prediction_cutoff` bereits
verfügbar waren. Der Stichtag ist kein optionales Metadatenfeld,
sondern steuert, welche Daten überhaupt gelesen werden.

#### Der gemessene Fehler

Vor C10 gab es **vier** Stellen, die einen Stichtag bildeten, und sie
schrieben ihn unterschiedlich:

| Stelle | Form |
| --- | --- |
| `dataset.prediction_cutoff` | `datetime`, naiv, Spieltag 12:00 |
| `cl_dataset` | eigene `fromisoformat`-Zeile, gleiche Regel |
| `pit_profiles.runtime_cutoff` | ISO-Text, meist nur das Datum |
| `snapshot_reader._als_utc` | ISO-Text, teils mit Zonenanhang |

Ein Snapshot mit `captured_at = "2025-03-11T06:00:00+00:00"` liegt

```
vor  "2025-03-11T12:00:00"   ->  Training nimmt ihn
nach "2025-03-11"            ->  Laufzeit nimmt ihn nicht
```

Derselbe Match, derselbe Datenbestand, zwei Informationsstände. Der
Vergleich in `snapshot_archive` ist ein Textvergleich, und
`"2025-03-11"` ist ein Präfix des Stempels: kürzer heißt lexikografisch
kleiner. Das war kein Tippfehler in einer Zeile, sondern die Folge
davon, dass vier Stellen dasselbe Wort verschieden buchstabierten.

#### Der Vertrag

`src/ml/prediction_cutoff.py` bündelt die Regel in einer
unveränderlichen Klasse:

```python
PredictionCutoff.for_match_day("2025-03-11")   # historisches Spiel
PredictionCutoff.parse("2025-03-11T12:00:00")  # serialisiert
PredictionCutoff.at(datetime(...))             # bekannter Zeitpunkt
PredictionCutoff.now()                         # Rand der Laufzeit
```

Der kanonische Wert ist zeitzonenbehaftet und in UTC; nach außen geht
ISO 8601 mit `Z`. Ein naiver Zeitpunkt wird als UTC gelesen, nicht als
Ortszeit. Das ist die einzige Annahme des Vertrags und sie steht
ausdrücklich im Modulkopf: Intern rechnet das Projekt seit jeher in
naiver UTC, weil `match_timeline` jeden Zeitstempel umrechnet und die
Zone abstreift. Eine Ortszeitannahme hinge dagegen am Rechner, auf dem
der Prozess läuft.

#### Zwei Skalen, beide benannt

Der Bestand kennt zwei Genauigkeiten, und das lässt sich nicht
wegdefinieren:

| Zugriff | Format | Wofür |
| --- | --- | --- |
| `day_key()` | `2025-03-11` | Profilpfad. `data/historical` führt nur `date`; `point_in_time.match_time` sucht `utc_date`/`utcDate` und findet dort nichts |
| `instant_key()` | `2025-03-11T12:00:00` | Zeitleiste und Snapshotarchiv. Feste Länge, kein Zonenanhang, weil dort Texte verglichen werden |
| `iso()` | `2025-03-11T12:00:00Z` | Serialisierung, Artefakte, Metadaten |

Zwei benannte Zugriffe statt einer Funktion, die je nach Aufrufer etwas
anderes bedeutet. Wer die falsche wählt, tut es sichtbar.

#### Eine ungeschützte Kopplung, jetzt geprüft

Eine Partie ohne Anstoßzeit bekommt in der Zeitleiste den Zeitstempel
Tag@`FALLBACK_KICKOFF_HOUR`. Ihr eigener Stichtag liegt bei
Tag@`CUTOFF_HOUR`. Der Filter ist strikt kleiner, also fällt sie aus
ihrem eigenen Merkmalsfenster. Das gilt aber nur, solange beide
Stunden gleich sind, und beide Zahlen standen in verschiedenen Modulen,
ohne dass irgendetwas sie aneinander band.

Die CL-Historie führt **keine einzige** Anstoßzeit: 503 Partien, alle
ohne `kickoff`. Wäre die Rückfallstunde auf 11 gesunken, geriete jede
CL-Partie in ihre eigenen Merkmale. Ein solches Selbstleck fängt keine
Kennzahl auf, weil es wie ein sehr gutes Modell aussieht.
`assert_hours_match()` prüft die Gleichheit jetzt, und ein Test ruft
sie auf.

#### Fail closed

| Fall | Verhalten |
| --- | --- |
| Historisches Training oder Replay ohne Cutoff | `MissingCutoff` |
| Unbrauchbarer Cutoff (`None`, leer, `"morgen"`, Zahl) | `MissingCutoff` |
| Kein zulässiger Snapshot | definierter Fehlzustand, nie ein Snapshot nach dem Cutoff |
| Snapshot ohne lesbaren Zeitstempel | verworfen, nicht auf den Anfang der Zeitrechnung gesetzt |
| Live-Runtime ohne externen Cutoff | `PredictionCutoff.now()` einmalig am Rand |

Ein fehlender Stichtag darf nicht auf den neuesten Stand springen.
Genau dieser Rückfall wäre die stille Zeitreise: Das Ergebnis sähe
plausibel aus und benutzte Daten aus der Zukunft.

#### Nur noch eine Uhr

`PredictionCutoff.now()` ist die einzige Stelle, die die Systemuhr
liest. Vorher bestimmten `pit_profiles.runtime_cutoff` und
`league_match_sim` unabhängig voneinander den heutigen Tag. Zwei Uhren
im selben Request können über Mitternacht auseinanderfallen, und dann
rechnete dieselbe Simulation mit zwei Ständen. Ein AST-Test prüft, dass
in Dataset, CL-Dataset, PIT-Profilen und beiden Simulationspfaden kein
`date.today()` oder `datetime.now()` mehr steht.

#### Live-Cutoff und Replay-Cutoff

| Fall | Stichtag |
| --- | --- |
| Historisches Spiel | `fixture_cutoff()` löst den Spieltag aus der eigenen Historie auf |
| Künftiges Spiel | `runtime_cutoff()`, heutiger Tag um 12 Uhr |
| Saisonsimulation | **ein** `runtime_cutoff()` für den ganzen Lauf, am Rand bestimmt |

Die Saisonsimulation bestimmt den Stichtag **einmal** am Rand und löst
die Profile daraus auf; danach simuliert die Schleife nur noch. Damit
benutzen wiederholte Monte-Carlo-Läufe denselben Informationsstand, und
ein simuliertes Ergebnis fließt nicht in eine spätere simulierte Partie
ein. Es gibt keine Fortschreibung virtueller Informationen zwischen
simulierten Spielen.

Die Mittagsstunde sorgt zusätzlich dafür, dass derselbe Aufruf über den
Tag hinweg denselben Stichtag bekommt. Ein Stichtag, der mit jeder
Sekunde weiterläuft, wäre mit einer reproduzierbaren Simulation
unvereinbar.

#### Training und Runtime bauen denselben Vektor

Belegt, nicht behauptet:

| Prüfung | Ergebnis |
| --- | --- |
| Stichtag Training gegen Replay (3 Spieltage) | identisch, `2025-03-11T12:00:00Z` |
| Feature-Namen und Reihenfolge | identisch, 16 Spalten |
| Featurewerte | identisch (Toleranz 1e-12) |
| Missingness | identisch, fehlende Felder bleiben `None` |
| Profilfabrik | dieselbe: `pit_profiles.PitProfileRepository` und `resolve_profile` |
| Abbildung Profil zu Merkmal | dieselbe: `dataset.profile_feature_values` |

Die Parität ist strukturell, nicht zufällig: `cl_dataset` und die
Laufzeit importieren beide aus `pit_profiles`, und beide Pfade rufen
dieselbe Abbildungsfunktion. Zwei Fassungen derselben Zuordnung wären
die sicherste Art, ein Modell auf anders sortierte Werte anzuwenden,
und das fällt an keiner Zahl auf.

#### Leakage-Tests mit Manipulation

Ein sauberer Durchlauf beweist nur, dass der Filter diesmal nichts zu
tun hatte. Deshalb wird Information absichtlich eingespeist:

- Partie **nach** dem Stichtag: Zeitleistenausschnitt unverändert
- Partie **genau am** Stichtag: zählt nicht, die Grenze ist strikt
- dieselbe Partie **vor** den Stichtag gezogen: kommt an (Gegenprobe)
- Snapshot **nach** dem Stichtag hinzugefügt: frühere Auswahl unverändert
- Reihenfolge der Eingabedaten: ohne Wirkung
- Snapshot ohne lesbaren Zeitstempel: verworfen

#### Reproduktion

```
python run_ml.py --verify-c10 --output data/ml/c10_prediction_cutoff_contract_2023-2025.json
```

Prüft Stundenkopplung, Stichtagsparität und Featurevektor und schreibt
das Ergebnis. Schlägt eine der drei Prüfungen fehl, wird **nichts**
geschrieben: Ein Artefakt, das eine gebrochene Parität dokumentiert,
sähe aus wie ein Nachweis.

Zweimal gelaufen, identischer Vertragsfingerprint `75838f28…`.
Ausgenommen sind nur Erzeugungszeit und git-Stand. Der Lauf braucht
weder Netzwerk noch `.env` noch den Datensatz: Er prüft Verträge, keine
Zeilen.

#### Der C9-Freeze bleibt unangetastet

| Prüfung | Wert |
| --- | --- |
| C9-Manifest-Fingerprint | `d432cf39…`, unverändert |
| Schema-Fingerprint | `475b9be8…`, unverändert |
| Kandidat | `team_profile_cl` |
| Featuregruppe | `profile` |
| Featureanzahl | 16 |
| Modellklasse | `poisson_offset_correction_linear` |
| Schema-Version | 2 |

`dataset.prediction_cutoff` delegiert seit C10 an den gemeinsamen
Vertrag, liefert aber denselben Wert wie vorher. Ein Test prüft die
Bitgleichheit für mehrere Spieltage; ändert sich dieser Wert, ändert
sich der Datensatz und damit jeder in C9 eingefrorene Fingerprint.

#### Bekannte Grenzen

- Der Stichtag ist ein **Tagesstichtag um 12:00 UTC**, kein
  Anstoßzeitpunkt. `data/historical` führt keine Anstoßzeiten. Eine je
  Quelle unterschiedliche Regel wäre schlechter als eine einheitlich
  leicht zu frühe.
- Intern bleibt die Vergleichsskala naive UTC. Der kanonische Wert des
  Vertrags ist zeitzonenbehaftet; ein vollständiger Umbau träfe
  `point_in_time`, die Zeitleiste und den eingefrorenen C9-Stand.
- Die Parität ist für den **ausgewählten Kandidaten** belegt, also für
  die 16 Profilmerkmale. Forschungsmerkmale aus Zeitleiste und
  Snapshots teilen dieselbe Infrastruktur, sind aber nicht aktiviert
  und deshalb nicht Teil der Zusage.
- Es gibt weiterhin **keinen unangetasteten Holdout**. Die Saisons 2023
  bis 2025 haben alle bisherigen Entscheidungen getragen. C10 ändert
  daran nichts und behauptet keine unabhängige Bestätigung.

*V2-C10 verdrahtet die Zeit. Es trainiert kein Modell, wählt kein
Merkmal aus, aktiviert nichts und überschreibt kein Bundle. Der
ausgewählte Kandidat bleibt der V1-Stand aus C9.*

### Modellregistry und Freigabegate (V2-C11)

C11 ist die Sicherheitsschicht zwischen dem trainierten Modell und der
produktiven Simulation. Die Regel:

> Kein Modell wird produktiv, weil eine Datei entstanden ist. Es wird
> produktiv, weil jemand es ausdrücklich freigegeben hat und die
> Freigabe zu genau diesem Bundle passt.

#### Was vorher fehlte

Der Ladeweg endete bei einem festen Pfad:

```
inference.DEFAULT_MODEL_PATH
    data/ml/models/cl_correction_model_v1.json
```

Wer diese Datei ersetzt, ersetzt das Modell. Das Bundle trägt zwar
einen eigenen Integritätshash, aber der deckt nur den `models`-Block und
liegt *im* Bundle. Sein eigener Kommentar sagt es:

> schützt vor Beschädigung und vertauschten Dateien, nicht gegen einen
> Angreifer mit Schreibrecht

Dazu kam: `STAGES_ALLOWED_ACTIVE` enthält `experimental`, und das
vorhandene Bundle steht auf genau dieser Stufe. Es war eine
Umgebungsvariable von der Wirkung entfernt, ohne dass irgendwo
festgehalten war, *dass* es wirken soll.

#### Die vier Zustände

| Zustand | Bedeutung | Wirkung auf die Nutzerantwort |
| --- | --- | --- |
| `candidate` | registriert und geprüft | keine |
| `shadow` | rechnet mit, wird protokolliert | keine |
| `active` | bestimmt die Antwort | ja, genau eines |
| `rollback` | zuletzt aktiv, als Rückfallziel aufgehoben | keine |

#### Erlaubte Übergänge

```
(neu)      -> candidate
candidate  -> shadow
shadow     -> active        nur mit gültiger Freigabe
active     -> rollback      automatisch beim Wechsel
rollback   -> active        Rollback, Freigabe wird erneut geprüft
```

Ausdrücklich verboten, jeweils mit Begründung im Code:

| Übergang | Warum nicht |
| --- | --- |
| `candidate` zu `active` | ein nie im Schatten gelaufenes Modell wirkt nicht als erstes auf Nutzer |
| (neu) zu `active` | ein frisch registriertes Bundle wird nicht durch Registrierung aktiv |
| (neu) zu `shadow` | auch der Schattenlauf setzt eine Registrierung voraus |
| `rollback` zu `shadow` | ein Rückfallziel bleibt aufgehoben, bis es wieder aktiv wird |

#### Das Freigabegate

Eine Freigabe ist kein Schalter und kein Passwort, sondern eine
Prüfsumme über acht Tatsachen:

```
model_id, bundle_sha256, feature_schema_fingerprint,
c9_manifest_fingerprint, c10_contract_fingerprint,
evaluation_artifact, evaluation_status, transition
```

Ändert sich eine davon, ergibt dieselbe Rechnung ein anderes Zeichen,
und die Freigabe verfällt von selbst. Eine Freigabe für Bundle A kann
Bundle B nicht aktivieren, und eine Freigabe von gestern gilt nach einem
Bundlewechsel nicht mehr. Dazu ist eine lesbare Begründung Pflicht.

**Diese Grenze steht auch im Artefakt:** Das Zeichen *bindet*, es
*authentifiziert nicht*. Wer die CLI ausführen kann, kann ein Zeichen
erzeugen. Es verhindert das Versehen, nicht den Vorsatz. Ein
hartkodiertes Passwort im Repository wäre Sicherheitstheater und nicht
mehr wert.

Zusätzlich trägt nur der Evaluationsstatus `accepted` eine Aktivierung.
`rejected`, `inconclusive`, `not_evaluable`, `infrastructure_only`,
`pending` und `unknown` sind kein Beleg.

#### Bundle- und Vertragsprüfung

Die Registry nennt den erwarteten SHA-256 der **gesamten** Bundledatei,
nicht nur des `models`-Blocks. Der Unterschied ist der Punkt: Der
bundleeigene Hash wandert mit, wenn jemand die Datei austauscht, dieser
nicht.

Geprüft wird bei jedem Lesen: Schemafassung, Pflichtfelder, eindeutige
Modell-ID, bekannte Stufe, repo-relativer Pfad, vorhandenes Bundle,
Bundle-Hash, genau ein aktives Modell, gültiges Rückfallziel und für ein
aktives Modell zusätzlich Evaluationsstatus, Evaluationsartefakt und
Freigabe.

Absolute Pfade werden abgelehnt, in beiden Schreibweisen: Ein
Windows-Pfad fällt unter Linux nicht durch `os.path.isabs`.

#### Atomare Aktualisierung

```
1. vollständig validieren      ungültig wird gar nicht geschrieben
2. temporäre Datei im selben Verzeichnis
3. flush und fsync
4. os.replace                  ein Schritt, auf Windows und Linux
```

Ein Leser sieht die alte oder die neue Registry, nie eine halbe.
Schlägt Schritt 1 oder 2 fehl, bleibt die vorherige liegen. Die
temporäre Datei trägt `.tmp` und wird nie als Registry gelesen.

#### Fail closed

Jeder Zweifel endet ohne aktives Modell. Es gibt keinen Rückfall auf
"dann eben das neueste Bundle". Sechzehn Fälle sind geprüft, darunter:
fehlende Registry, beschädigtes JSON, unbekannte Schemafassung, zwei
aktive Modelle, fehlendes Bundle, abweichender Hash, fehlende Freigabe,
Freigabe für ein anderes Bundle, beschädigtes Rückfallziel.

Die Runtime hat für all das bereits einen getesteten Baselinepfad. C11
erfindet keinen neuen.

#### Runtime-Auswahl

`model_registry.active_entry()` ist der einzige Weg, auf dem ein Modell
in die Nutzerantwort gelangt. Die Prüfung steht **nach** der
bestehenden Stufenprüfung und kann nur ablehnen: Sie macht nichts
möglich, was vorher unmöglich war. Neue Rückfallgründe:
`model_not_active_in_registry` und `registry_unusable`.

Der `prediction_cutoff` aus C10 bleibt unberührt. Die Registry wählt das
Modell, nicht den Zeitpunkt.

#### Schattenisolation

Ein Schattenmodell darf dieselben zeitlich zulässigen Eingaben
bekommen, intern rechnen und getrennt protokolliert werden. Es darf die
sichtbare Antwort nicht verändern, sich nicht mit dem aktiven Ergebnis
mischen, die Zufallsfolge des aktiven Modells nicht berühren und bei
einem Fehler die Simulation nicht blockieren. Im Schattenmodus liefert
die Runtime die Baseline; der Schattenwert steht ausschließlich in der
Diagnose.

#### ML-Modus und Regler-Modus bleiben getrennt

Die Registry gehört zum ML-Zweig und wird nur dort gelesen. Der Import
steht in der Funktion, nicht am Modulkopf, damit ein Registryfehler den
individuellen Modus nicht berührt. Ein Test prüft, dass die
Ligasimulation weder `model_registry` noch `src.ml` kennt, und ein
weiterer, dass die Registry `ml_weight` nicht kennt: Die Gewichtung ist
eine Frage der Betriebsart, nicht der Modellauswahl.

#### CLI

```
python run_ml.py --registry show
python run_ml.py --registry validate
python run_ml.py --registry fingerprint

python run_ml.py --registry register --bundle data/ml/models/cl_correction_model_v1.json
python run_ml.py --registry register --bundle <pfad> --apply

python run_ml.py --registry shadow  --model-id <id> --apply
python run_ml.py --registry promote --model-id <id>
python run_ml.py --registry promote --model-id <id> --apply --approval-reason "..."

python run_ml.py --registry rollback
python run_ml.py --registry rollback --apply
```

Verändernde Aktionen laufen ohne `--apply` trocken und liefern dieselbe
Ablehnung wie der echte Lauf, nur ohne Folgen. Exit-Codes: `0` in
Ordnung, `1` fachlich abgelehnt, `2` falsch bedient. Ein Trainingslauf
schaltet die Registry niemals nebenbei um.

#### Sichere Rollback-Prozedur

```
python run_ml.py --registry show           welches Modell ist aktiv
python run_ml.py --registry rollback       Trockenlauf, prüft das Ziel
python run_ml.py --registry rollback --apply
python run_ml.py --registry validate       Ergebnis bestätigen
```

Der Rollback verlangt keine neue Freigabe, prüft die vorhandene aber
erneut. Ein Rückfallziel, dessen Freigabe nicht mehr passt, ist kein
Rückfallziel, und der Rollback wird abgelehnt. Das bisher aktive Modell
wird dabei zum neuen Rückfallziel.

#### Bestandsschutz für den vorgefundenen Stand

Beim Einschalten der Registry stellte sich heraus: Das vorhandene
Bundle war bereits aktiv. Seine Freigabestufe `experimental` deckt den
aktiven Betrieb, und über `approach=ml` wirkte es. Hätte die Registry es
auf `candidate` gesetzt, wäre ein laufendes Feature stillschweigend
ausgegangen, und die Oberfläche hätte weiter "ML" angezeigt bei
Baseline-Ergebnis. Genau das hat V2-C0B beseitigt, und ein bestehender
Test hält es fest:

> `approach='ml'` ist der Standard der Champions-League-Oberfläche. Er
> muss das Modell tatsächlich anwenden, sonst wäre die sichtbare
> Auswahl eine Behauptung.

Die Registry verzeichnet deshalb den Zustand, den sie vorfindet:
`clm-8a4eda90a08395cc` steht auf `active` mit dem Evaluationsstatus
`grandfathered_pre_c11`.

Dieser Status ist eng gefasst und ausdrücklich gekennzeichnet:

- er gilt nur für einen Eintrag mit `grandfathered: true` und einer
  Begründung von mindestens 30 Zeichen
- er trägt **keine neue** Aktivierung: `set_stage` verlangt dafür
  weiterhin `accepted`
- ein Bundlewechsel entwertet auch hier die Freigabe

**Er ist kein statistischer Beleg.** C9 hat keinen angenommenen
Kandidaten gefunden, und der gebundene Shadow-Backtest hat kein Gate
bestanden. Aufzulösen ist das in einem eigenen Block, entweder durch
reguläre Freigabe nach bestandenem Gate oder durch Außerbetriebnahme
des Bundles. Beides ist eine Produktentscheidung.

#### Was C11 nicht getan hat

**Es wurde kein V2-Modell neu freigegeben und keines neu aktiviert.**
Kein Bundle wurde überschrieben, keine Freigabe nach `accepted`
ausgestellt, kein Modell abgeschaltet. Der Standardmodus der Runtime
bleibt `off`.

Artefakt: `data/ml/c11_registry_release_gate_contract.json`,
Fingerprint zum Zeitpunkt von C11 `72aceaf4…`, zweimal gelaufen
identisch. Das Artefakt beschreibt den Registryzustand und wurde
deshalb nach der C12-Entscheidung neu erzeugt; es trägt seitdem
`045e76f4…`.

#### Bekannte Grenzen

- Das Freigabezeichen bindet, es authentifiziert nicht.
- Der Bundle-Hash erkennt eine spätere Änderung, verhindert sie nicht.
- Es ist kein V2-Modell regulär freigegeben. Das aktive Bundle steht
  unter Bestandsschutz, und es gibt keine Messung, die eine reguläre
  Freigabe tragen würde.
- Es gibt weiterhin **keinen unangetasteten Holdout**. Die Saisons 2023
  bis 2025 haben alle bisherigen Entscheidungen getragen.
- C11 baut den Weg. Ob je ein V2-Modell diesen Weg geht, entscheidet
  eine Messung, die es bisher nicht gibt.

*V2-C11 baut das Tor. Es trainiert nichts, misst nichts, gibt nichts
frei und aktiviert nichts. Das bestehende Verhalten der Simulation ist
unverändert.*

### Finale Evaluation und Freigabeentscheidung (V2-C12)

C11 hatte festgestellt, dass ein Modell produktiv wirkt, ohne dass je
jemand es freigegeben hat, und diesen Zustand als
`grandfathered_pre_c11` verzeichnet. C12 löst das auf, gegen Gates, die
vor der Messung feststanden.

**Ergebnis: `rejected`.** Das Modell bestimmt keine Nutzerantwort mehr.
Es gilt die bestehende Baseline.

#### Die Reihenfolge ist der ganze Wert

Erst der Vertrag, dann die Messung, dann die Entscheidung. Der Vertrag
trägt einen eigenen Fingerprint (`66cae83c…`), das Ergebnis nennt ihn,
und ein Ergebnis mit fremdem Vertragsfingerprint wird abgewiesen. Wer
Schwellen nach dem Ergebnis wählt, hat nichts gemessen, sondern eine
Rechtfertigung gebaut.

Die Schwellen sind nicht neu. Sie stammen sämtlich aus bereits
dokumentierten Blöcken und werden importiert, nicht abgeschrieben:

| Schwelle | Wert | Herkunft |
| --- | ---: | --- |
| `MIN_RELIABLE_N` | 30 | V2-C2B |
| `SEVERE_DEGRADATION` | 0,01 | V2-C2B |
| `MAX_CALIBRATION_DEGRADATION` | 0,25 | V2-C8 |
| `MAX_SECONDARY_DEGRADATION` | 0,0 | V2-C8 |
| Bootstrap-Seed und Iterationen | fest | V2-C2 |

#### Verglichene Kandidaten

| Kandidat | Was |
| --- | --- |
| V0 | die bestehende Poisson-Baseline aus Profil und Ligaschnitt |
| V1 | das laufende Modell `clm-8a4eda90a08395cc`, 16 Merkmale |
| Early V2 | die von C9 eingefrorene Auswahl, **numerisch identisch mit V1** |

C9 hat als Selected ausschließlich die Gruppe `profile` bestimmt. Early
V2 ist damit dieselben 16 Merkmale. Das steht so im Vertrag, statt einen
Unterschied zu erfinden.

Dixon-Coles und eine direkte 1X2-Regression sind `not_evaluated`, mit
Begründung: Beide wären neue Modellklassen mit eigenem Anpassungscode,
und C12 ist der Entscheidungs-, nicht der Baublock.

#### Die Messung

Zeitliche Folds, kein zufälliger Split, foldlokale Alphawahl und
foldlokales Preprocessing, `prediction_cutoff` je Partie aus V2-C10.

| Kennzahl | Baseline | Modell | Differenz |
| --- | ---: | ---: | ---: |
| LogLoss | 0,92977 | 0,92087 | **−0,008902** |
| Brier | 0,54791 | 0,54327 | −0,004639 |
| RPS | 0,21394 | 0,21315 | −0,000797 |
| Kalibrierungsfehler | 0,04816 | **0,01647** | −0,03168 |

95-%-Bootstrapintervall der LogLoss-Differenz: **[−0,029861; +0,011352]**

| Fold | n | ΔLogLoss |
| --- | ---: | ---: |
| `cl_2024` | 112 | −0,012561 |
| `cl_2025` | 101 | −0,004843 |

Auf den ersten Blick spricht alles für das Modell: alle drei
Punktschätzer besser, die Kalibrierung deutlich besser, beide Folds in
dieselbe Richtung.

#### Der Befund, der die Entscheidung trägt

Die Segmentauswertung zeigt etwas, das der Gesamtdurchschnitt verdeckt:

| Segment | n | ΔLogLoss |
| --- | ---: | ---: |
| `profile_source:domestic_pit` | 154 | −0,02596 |
| `profile_source:cl_history_pit` | 59 | **+0,03562** |
| `profile_depth:>=20` | 160 | −0,02572 |
| `profile_depth:<20` | 53 | **+0,04186** |

Die beiden auffälligen Segmente sind fast dieselbe Menge: 53 von 53
Partien mit dünnem Profil haben auch ein CL-History-Profil (Jaccard
0,90). Es ist ein Befund, nicht zwei.

Er trägt in **beiden** Folds:

| Fold | `cl_history_pit` | `domestic_pit` |
| --- | ---: | ---: |
| `cl_2024` | +0,05455 (n=33) | −0,04059 (n=79) |
| `cl_2025` | +0,01161 (n=26) | −0,01055 (n=75) |

Das Modell wurde auf nationalen Ligaprofilen trainiert. Auf
CL-Partien, deren Profil ebenfalls aus nationalen Ligen stammt,
überträgt es sich gut. Auf Partien, deren Profil aus der CL-Historie
kommt, überträgt es sich schlecht. Das ist genau die Grenze, die C2
schon bei `profile_depth` gefunden hatte, und der Grund, warum diese
Gruppe in C9 den Status `REJECTED` trägt.

28 Prozent der Testpartien sind betroffen, und die Verschlechterung ist
dort das Vierfache der Schwelle für einen schweren Einbruch.

#### Das Urteil

| Bedingung | Ergebnis |
| --- | --- |
| primärer LogLoss besser | ja |
| alle Folds gleiche Richtung | ja |
| kein Fold trägt den Gewinn allein | ja |
| Brier nicht schlechter | ja |
| RPS nicht schlechter | ja |
| Kalibrierung hält | ja |
| Stichprobe groß genug | ja |
| **oberes Intervall unter null** | **nein** |
| **kein schwer beschädigtes Segment** | **nein** |

Zwei Gates verfehlt, beide vorab festgelegt. Verdict: `rejected`.

#### Was daraus folgt

| | vor C12 | nach C12 |
| --- | --- | --- |
| Registry-Stufe | `active` | `candidate` |
| Evaluationsstatus | `grandfathered_pre_c11` | `rejected` |
| aktives Modell | `clm-8a4eda90a08395cc` | keines |
| Nutzerantwort | Modellkorrektur | bestehende Baseline |

Der Bestandsschutz ist aufgelöst und war damit kein Dauerzustand. Das
Bundle wurde nicht verändert; sein Hash in der Registry ist der der
vorgefundenen Datei. Ein Rollback bleibt technisch möglich: Der
vorherige Eintrag steht im Artefakt.

**Eine sichtbare Folge, die noch offen ist:** Die Oberfläche bietet
`approach=ml` weiterhin an, und dieser Weg liefert jetzt die Baseline.
Die API sagt das ehrlich (`applied: false` plus `fallback_reason`), und
Tests halten genau das fest. Ob die Auswahl in der Oberfläche bleiben
soll, ist eine Produktentscheidung für den Abschlussaudit.

#### Reproduktion

```
python run_ml.py --evaluate-c12
python run_ml.py --evaluate-c12 --apply --output data/ml/c12_final_evaluation_2023-2025.json --force
```

Ohne `--apply` läuft alles trocken und zeigt dieselbe Entscheidung ohne
Folgen. Zweimal gelaufen, identischer stabiler Fingerprint
`fde60b2e…` und identisches Verdict. Kein Netzwerk, keine `.env`, keine
Systemzeit im stabilen Ergebnis.

Artefakt: `data/ml/c12_final_evaluation_2023-2025.json`, gebunden an
C9 `d432cf39…`, C10 `75838f28…`, C11 `045e76f4…` und das
Merkmalsschema `475b9be8…`.

#### Bekannte Grenzen

- **Kein unangetasteter Holdout.** Die Saisons 2023 bis 2025 haben jede
  Entscheidung von C2 bis C11 getragen. Dieses Ergebnis ist
  Entwicklungsevidenz. Wäre das Urteil `accepted` gewesen, hätte es die
  Klasse `accepted_development_evidence` bekommen und nicht mehr.
- n = 213 Testpartien. Das Bootstrapintervall ist entsprechend breit.
- Die Segmentbefunde beruhen auf 53 bis 160 Partien. Groß genug zum
  Interpretieren, zu klein für eine feinere Auflösung.
- Eine prospektive Bestätigung braucht CL-Partien, die zum Zeitpunkt
  aller bisherigen Entscheidungen noch nicht gespielt waren, also Saison
  2026/27 aufwärts.

#### Technische Fertigstellung ist keine Freigabe

V2 ist nach C12 technisch fertig gebaut: PIT-Vertrag, Feature-Freeze,
Cutoff, Registry, Freigabegate, Evaluation. Das heißt nicht, dass ein
V2-Modell freigegeben wäre. Es ist keines, und die Messung sagt warum.

Ein separater Abschlussaudit steht noch aus. Bis dahin gilt V2 nicht als
produktionsfreigegeben.

*V2-C12 entscheidet. Es baut kein Modell, sucht kein Merkmal und
verändert kein Bundle. Die Entscheidung fiel gegen Gates, die vor der
Messung festgeschrieben waren.*


### Der nationale Profilpfad für alle vorhandenen Ligen (V2-C13)

V2-C2B lud 2023 bis 2025 achtzehn zusätzliche nationale Ligen, damit die
Belastungszeitleiste die vorherige Partie jedes CL-Vereins kennt. Das hat
funktioniert: 98,61 % Abdeckung.

Der **Profilpfad** wurde dabei nie umgestellt. Er las weiter genau fünf
Ligadateien, weil er über `historical_loader.LEAGUE_CODES` lief. Die
Daten lagen seit C2B auf der Platte, sie wurden nur an dieser einen
Stelle nicht gelesen.

Messbar war das an einer Zahl, die vorher wie ein Datenproblem aussah:

| Profilquelle | vor C13 | nach C13 |
| --- | ---: | ---: |
| `domestic_pit` | 658 | **1006** |
| `cl_history_pit` | 321 | 0 |
| `neutral` | 27 | 0 |

`cl_history_pit` heißt: Der Verein bekam sein Profil aus seinen eigenen
Champions-League-Partien, im Extremfall aus einer einzigen. In V2-C12
war genau diese Gruppe der Grund für das `rejected`.

**Die ID-Falle.** Die Ligadateien stammen von zwei Anbietern mit
getrennten Nummernkreisen. Nachgemessen an den 63 CL-Vereinen: **28 ihrer
football-data-Kennungen bezeichnen im API-Football-Namensraum einen
anderen Verein.**

| Kennung | football-data | API-Football |
| ---: | --- | --- |
| 57 | Arsenal | Ipswich |
| 64 | Liverpool | Hull City |
| 66 | Manchester United | Aston Villa |
| 498 | Sporting CP | Sampdoria |
| 732 | Celtic | Zaragoza |

Ein Profil über eine rohe Kennung würde die Ergebnisse eines fremden
Vereins tragen, und an den Zahlen wäre nichts auffällig. Genau dieser
Fehler ist im forensischen Audit vor C13 tatsächlich passiert, in einem
Analyseskript, und wurde von außen bemerkt statt von innen.

**Die Reihenfolge ist der ganze Schutz.** Es wird nie gefragt, ob eine
football-data-Kennung in einer API-Football-Datei vorkommt. Stattdessen
entstehen erst *alle* Profile im Namensraum ihrer Ligadatei, und danach
bleiben nur die, deren Kennung sich eindeutig zurückführen lässt. Eine
Zahl wird nie als Schlüssel wiederverwendet. Wer sich nicht zurückführen
lässt, bekommt kein nationales Profil; unbekannt ist besser als
vielleicht falsch.

Zeigen zwei Vereine auf dasselbe Ziel, fliegt das Ziel aus **beiden**
Richtungen. Ein Profil, das zwei Vereinen gehören könnte, gehört keinem.

**Jede Zuordnung ist einzeln belegt.** Eine Abdeckungszahl allein wäre
nach dem Zwischenfall im Audit kein Beleg mehr. Für alle 63 CL-Vereine
wird deshalb einzeln geprüft, dass das Profil aus einer Liga stammt, in
deren Teamliste der Verein wirklich steht, und dass der Name dort seiner
ist. Zwei Vereine heißen bei den Anbietern nachweislich verschieden und
stehen namentlich im Test: FC København gegen FC Copenhagen und Paphos
gegen Pafos.

**Was die Ligen beitragen.** Die großen Ligen liefern viele Vereine, die
kleinen wenige, und das ist richtig so: Aus der Eredivisie ist nur die
Handvoll CL-Teilnehmer gefragt, nicht die ganze Liga.

| Liga | übernommen | ohne Crosswalk verworfen |
| --- | ---: | ---: |
| PD, SA, PL, BL1, FL1 | 25 bis 26 je Liga | 0 |
| PT1 | 4 | 19 |
| NL1 | 3 | 26 |
| RS1, KZ1, NO1 | 1 je Liga | 13 bis 21 |

**Point in Time bleibt unangetastet.** Der Stichtag ist weiterhin 12:00
und strikt kleiner. Nachgemessen wächst die Profiltiefe monoton mit dem
Stichtag (Ajax, Saison 2025: 69, 75, 81, 87, 92 Partien), und eine später
angesetzte Partie verändert ein früheres Profil nicht.

Die API-Football-Dateien führen ein `kickoff`-Feld, die
football-data-Dateien nicht. `point_in_time` liest es **nicht**, und das
bleibt so: Ein zusätzliches Zeitfeld dort würde die Stichtagssemantik
aller Aufrufer verschieben, nicht nur die des Profilpfads. Die Folge ist
konservativ, Partien am Stichtag bleiben draußen.

**Pokale bleiben draußen.** Copa del Rey, Coppa Italia, Coupe de France,
DFB-Pokal und FA Cup liegen lokal vor und werden ausdrücklich nicht
gelesen. Ein Pokal ist kein Ligabetrieb: gemischte Ligaebenen, zwischen
einer und sieben Partien je Verein. Die Ligaliste steht ausgeschrieben
statt als Verzeichnisglob, damit der nächste heruntergeladene Wettbewerb
nicht stillschweigend hineinrutscht.

**Was übrig bleibt.** 21 von 503 Partien sind weiterhin weder auswertbar
noch K.-o.-fähig, alle mit demselben Grund: Profiltiefe unter sechs
Partien. Das sind echte Datenlücken, keine Zuordnungsfehler, und sie
werden nicht wegdefiniert.

| Größe | vor C13 | nach C13 |
| --- | ---: | ---: |
| auswertbar | 238 | **363** |
| K.-o.-fähig | 119 | 119 |
| weder noch | 146 | **21** |
| Testpartien Standardvertrag | 213 | **283** |
| Testpartien Kontextvertrag | 303 | **373** |

**Zwei Fingerabdrücke statt einem.** Das Artefakt trennt Regel und
Zustand. Der Vertragsfingerabdruck ändert sich nur, wenn jemand die
Ligaliste, die Ausschlüsse, die Identitätsregel oder die Stichtagsregel
anfasst. Der Zustandsfingerabdruck ändert sich, sobald neue Spieldaten
vorliegen, und das ist kein Vertragsbruch. In C11 steckte beides in einem
Wert, und man konnte nicht mehr unterscheiden, ob sich die Regel oder nur
die Belegung geändert hatte.

```bash
python run_ml.py --verify-c13
```

*V2-C13 repariert einen Datenpfad. Es trainiert kein Modell, bewertet
kein Merkmal und ändert die Registry nicht. Der C9-Schemafingerabdruck
ist unverändert, der C10-Stichtag unverändert, und das C12-Urteil bleibt
`rejected`, bis neu gemessen wird. Mehr Abdeckung ist nicht dasselbe wie
mehr Güte.*

### Finale Reevaluation auf den reparierten Profilen (V2-C14)

V2-C12 lehnte das Modell an genau zwei von zehn Bedingungen ab. Eine
davon war ein Datenfehler, und V2-C13 hat ihn behoben. C14 misst, was
davon übrig bleibt.

**Der Vertrag stand vor der Messung.** Fingerabdruck
`704c9ade45f3ca1c9fde49bf1e0812f1c903f7ebc71ee07554bd9d4883dba835`,
festgeschrieben in `data/ml/c14_reevaluation_contract_2023-2025.json`,
bevor eine einzige Zahl gerechnet wurde. Die Datei enthält kein
Ergebnis, und ein Ergebnis unter einem anderen Fingerabdruck wird
zurückgewiesen.

**Der Kandidat blieb eingefroren.** Dieselben 16 Merkmale, dieselbe
Modellklasse, derselbe Hyperparameterraum. Geändert haben sich nur die
Profilwerte, die C13 repariert hat. Hätten Daten und Modell gleichzeitig
gewechselt, wäre das Ergebnis nicht mehr lesbar gewesen: Niemand könnte
sagen, welche der beiden Änderungen es getragen hat. Das alte Bundle
wurde ausdrücklich nicht wiederverwendet, sondern die eingefrorene
Modellklasse je Fold neu angepasst.

**Ergebnis auf 283 zeitlich getrennten Testspielen:**

| Größe | C12 (213 Spiele) | C14 (283 Spiele) |
| --- | ---: | ---: |
| V0 Log Loss | 0,92977 | 1,02842 |
| V2 Log Loss | 0,92087 | 1,01679 |
| ΔLog Loss | −0,008902 | **−0,011628** |
| 95-Prozent-Intervall | [−0,0299; +0,0114] | **[−0,0263; +0,0033]** |
| ΔBrier | besser | −0,007087 |
| ΔRPS | besser | −0,002810 |
| Kalibrierungsfehler V0 | 0,04816 | 0,04325 |
| Kalibrierungsfehler V2 | 0,01647 | 0,03079 |

Der Effekt ist um knapp ein Drittel gewachsen, und die obere
Intervallgrenze ist von +0,0114 auf +0,0033 gefallen. Sie schließt die
Null weiterhin ein.

**Verdict: `rejected`.** Drei Bedingungen sind nicht erfüllt.

| Fold | C12 | C14 |
| --- | ---: | ---: |
| `cl_2024` | −0,012561 | **−0,025747** |
| `cl_2025` | −0,004843 | **+0,002999** |

Die Folds widersprechen sich jetzt. 2024 ist deutlich besser geworden,
2025 kippt knapp ins Negative.

#### Die Ursache, gemessen statt vermutet

Zwei Segmente verschlechtern sich schwer, und beide zeigen auf dieselbe
Sache:

| Segment | n | ΔLog Loss |
| --- | ---: | ---: |
| `origin:other_vs_other` | 35 | −0,04128 |
| `origin:top5_vs_top5` | 102 | −0,02077 |
| `origin:other_vs_top5` | 73 | −0,01080 |
| **`origin:top5_vs_other`** | **73** | **+0,01453** |

Schaden entsteht genau dann, wenn ein Verein aus einer Top-5-Liga zu
Hause gegen einen Verein außerhalb der Top 5 spielt. Der Grund steht in
den Profilwerten:

| Merkmal | Top-5-Vereine | Nicht-Top-5 | Differenz |
| --- | ---: | ---: | ---: |
| `attack_away` | 1,248 | 1,434 | **+0,186** |
| `attack_home` | 1,267 | 1,392 | +0,125 |
| `points_per_game` | 1,982 | 2,257 | **+0,275** |
| `win_rate` | 0,585 | 0,694 | +0,109 |
| `defence_away` | 0,867 | 0,771 | besser |

Nicht-Top-5-Vereine haben in **jedem einzelnen** Profilmerkmal die
besseren Werte. Ihre tatsächliche Leistung in der Champions League:

| Gruppe | Tore je Spiel | Gegentore |
| --- | ---: | ---: |
| Top-5 zu Hause | 2,14 | 1,10 |
| Top-5 auswärts | 1,60 | 1,62 |
| Nicht-Top-5 zu Hause | 1,54 | 1,94 |
| Nicht-Top-5 auswärts | **1,12** | **2,38** |

Die 16 eingefrorenen Merkmale sind Verhältniswerte zur **eigenen** Liga.
Wer die Eredivisie beherrscht, sieht darin aus wie ein Spitzenklub. Die
Ligastärke steckt in keinem einzigen von ihnen.

Vor C13 fiel das nicht auf, und der Grund ist unangenehm elegant: Genau
diese Vereine bekamen damals `cl_history`-Profile. Die waren flach und
oft aus einer Handvoll Partien gebaut, aber sie wurden an
Champions-League-Gegnern gemessen und lagen damit zufällig auf der
richtigen Skala. C13 hat die Tiefe repariert und dabei die Skala
freigelegt.

**Der Standardvertrag kann das strukturell nicht lernen.** Er trainiert
ausschließlich auf nationalen Ligen, und dort spielen nie zwei Vereine
verschiedener Ligen gegeneinander. Auch der Kontextvertrag, der frühere
CL-Partien mittrainiert, repariert es nicht (dort +0,01770): Ohne ein
Merkmal, das die Liga unterscheidbar macht, kann das Modell nicht darauf
bedingen.

#### Was sich erledigt hat

Die dünnen Profile. In C12 war `profile_depth:<20` eines der beiden
sperrenden Segmente. Nach C13 gilt das Gegenteil:

| Segment | n | ΔLog Loss |
| --- | ---: | ---: |
| dünnste Seite 6 bis 19 Partien | 41 | **−0,02394** |
| dünnste Seite ab 20 Partien | 242 | −0,00954 |

Dünne Profile schneiden jetzt **besser** ab als tiefe. Die C12-Sorge kam
aus den `cl_history`-Profilen, die es nicht mehr gibt. Shrinkage würde
ein Problem lösen, das keines mehr ist, und ist deshalb nicht der
nächste Schritt.

#### Was C14 gegenüber C12 nachgeschärft hat

C12 nannte im Vertrag das Segment `profile_source`, ohne festzulegen, ob
Heim-, Auswärtsseite oder beide gemeint sind. Die Umsetzung nahm dann die
Heimseite. Gemessen kehrte sich das Vorzeichen um, je nachdem welche
Seite man ansah: `+0,0398` gegen `−0,0361`. Diese Wahl entschied
faktisch über das Urteil und stand nicht im Vertrag.

C14 schreibt Seite und Symmetrie aus: gerichtete Segmente für Heim und
Gast, symmetrische für dünnste Seite und beide Seiten. Segmente mit
identischer Zeilenmenge bilden eine Gruppe und zählen als **ein** Befund,
damit derselbe Schaden nicht unter zwei Namen doppelt gewichtet wird.

#### Konzentration

Die fünf stärksten Vereine tragen 67,7 Prozent der Gesamtverbesserung.
Ohne sie bleibt das mittlere Delta mit −0,00376 negativ, und die Richtung
hält für jeden einzelnen weggelassenen Verein. Für diese Frage gibt es in
den freigegebenen Verträgen keine numerische Schwelle. Sie wird deshalb
als Risiko berichtet und **nicht** als nachträglich erfundenes Gate
verwendet.

#### Reproduzierbar

```bash
python run_ml.py --evaluate-c14
```

Zwei Läufe liefern denselben Ergebnisfingerabdruck
`9544301a05922388b426ef855d504445754c3115eb713fe821ff612570330343`,
dieselben Foldmetriken und dasselbe Verdict. Erstellungszeit und
git-Stand stehen im Artefakt, gehen aber in keinen Fingerabdruck ein. Der
Exit-Code ist `1`, solange das Verdict nicht `accepted` lautet.

*V2-C14 misst und entscheidet, es aktiviert nicht. Die Registry ist
unverändert, es gibt weiterhin kein aktives Modell, und V0 bestimmt jede
sichtbare Nutzerantwort. Kein Bundle wurde erzeugt. Die Saisons 2023 bis
2025 haben jede Entscheidung von C2 bis C13 getragen; dieses Ergebnis ist
Entwicklungsevidenz und keine unabhängige Bestätigung.*

### Ligastärke, Freigabeweg und Abschlussaudit (V2-C15)

V2-C13 reparierte die Daten, V2-C14 maß nach und lehnte ab. Der Grund
war diesmal kein Datenfehler, sondern ein Modellfehler mit klarer
Ursache.

#### Warum C13 allein nicht genügte

Die 16 eingefrorenen Merkmale sind Verhältniswerte zur **eigenen**
nationalen Liga. Wer seine Liga beherrscht, sieht darin aus wie ein
Spitzenklub:

| Merkmal | Top-5 | Nicht-Top-5 |
| --- | ---: | ---: |
| `attack_away` | 1,248 | 1,434 |
| `points_per_game` | 1,982 | 2,257 |
| `win_rate` | 0,585 | 0,694 |

Die tatsächliche Leistung in der Champions League ist umgekehrt:
Nicht-Top-5-Vereine erzielen auswärts 1,12 Tore bei 2,38 Gegentoren,
Top-5-Vereine 1,60 bei 1,62. In V2-C14 kostete genau das die Freigabe
(`origin:top5_vs_other`, n=73, `+0,01453`).

Vor C13 fiel es nicht auf, und der Grund ist unangenehm elegant: Diese
Vereine bekamen damals `cl_history`-Profile. Die waren flach, aber an
Champions-League-Gegnern gemessen und lagen damit zufällig auf der
richtigen Skala. C13 reparierte die Tiefe und legte die Skala frei.

#### Warum eine zweite Stufe und keine weitere Spalte

Ein Ligastärkemerkmal im bisherigen Trainingsbestand wäre ein **totes
Merkmal**. In einem nationalen Ligaspiel stammen beide Mannschaften aus
derselben Liga, die Ligastärkedifferenz ist strukturell null, und ein
Koeffizient darauf bekäme kein Gewicht.

Nachgemessen und im Artefakt hinterlegt:

| Bestand | Zeilen | davon mit zwei verschiedenen Herkunftsligen |
| --- | ---: | ---: |
| nationale Trainingszeilen | 2917 | **0** |
| frühere CL-Partien, Fold `cl_2024` | 109 | **109 (100 %)** |
| frühere CL-Partien, Fold `cl_2025` | 298 | 292 (98 %) |

Der Effekt ist genau dort identifizierbar, wo er geschätzt wird, und
nachweislich nirgends sonst.

#### Die Modellform

Zwei Stufen. Stufe eins ist das unveränderte nationale Basismodell.
Stufe zwei korrigiert seine Erwartungswerte:

```
lambda_heim' = lambda_heim * exp(a[liga_heim] + d[liga_gast])
lambda_gast' = lambda_gast * exp(a[liga_gast] + d[liga_heim])
```

`a` ist die offensive, `d` die defensive Ligastärke als
log-Multiplikator, 0 bedeutet neutral. Geschätzt wird mit derselben
Technik wie das Basismodell, also PoissonRegressor über den
Offset-Umweg. Das ist keine neue Modellklasse, sondern dieselbe Klasse
auf einer zweiten Stufe. Der Heimvorteil steckt bereits in Stufe eins
und wird nicht doppelt modelliert.

Beispielparameter aus Fold `cl_2024`:

| Liga | Angriff | Abwehr |
| --- | ---: | ---: |
| PL | +0,2763 | −0,0116 |
| PD | +0,2178 | −0,1123 |
| PT1 | +0,0704 | +0,0149 |
| SCO1 | −0,1158 | +0,1364 |
| AT1 | −0,1452 | +0,0161 |
| NL1 | −0,1608 | +0,0933 |

**Identifizierbarkeit.** Ohne Achsenabschnitt wäre die Lösung nur bis
auf eine Konstante bestimmt: Man könnte auf alle `a` einen Wert
addieren und ihn von allen `d` abziehen, ohne eine einzige Vorhersage
zu ändern. Die Ridge-Strafe wählt darunter die Lösung kleinster Norm.
Die Regularisierung ist hier also nicht nur Vorsicht, sie ist Teil der
Definition. Das Rangdefizit der Entwurfsmatrix beträgt gemessen exakt
1, also genau die eine erwartete Konstante.

**Cold Start.** Eine Liga ohne frühere CL-Historie bekommt keine Spalte
und damit den Wert 0, also den Faktor 1. Unbekannt heißt unbekannt und
ausdrücklich nicht bevorzugt.

**Regularisierung.** Alpha wird über eine zeitliche innere Teilung
ausschließlich innerhalb der Trainingshistorie gewählt, nach derselben
Regel wie im Basismodell: bei einer Trainingssaison Teilung am mittleren
Spieldatum, bei mehreren nach Saison. Der äußere Testfold wird nie
gesehen. Gewählt wurden 0,1 für Fold 1 und 0,01 für Fold 2.

#### Das Ergebnis

Standardbestand, 283 zeitlich getrennte Testspiele:

| Kandidat | Log Loss | Brier | RPS | Kalibrierung |
| --- | ---: | ---: | ---: | ---: |
| V0 | 1,02842 | 0,61870 | 0,24412 | 0,04346 |
| C14 | 1,01679 | 0,61162 | 0,24131 | 0,03340 |
| **C15** | **0,93330** | **0,55013** | **0,21113** | 0,03923 |

| Vergleich | ΔLog Loss | 95-Prozent-Intervall |
| --- | ---: | --- |
| C15 gegen V0 | **−0,095118** | **[−0,131169; −0,057305]** |
| C15 gegen C14 | −0,083490 | [−0,117933; −0,046764] |
| C14 gegen V0 | −0,011628 | [−0,026279; +0,003319] |

Beide Folds verbessern sich, und der in C14 problematische Fold kippt
deutlich ins Positive:

| Fold | C14 | C15 |
| --- | ---: | ---: |
| `cl_2024` | −0,025747 | −0,066131 |
| `cl_2025` | **+0,002999** | **−0,125147** |

Die beiden C14-Schadenssegmente sind repariert:

| Segment | n | C14 | C15 |
| --- | ---: | ---: | ---: |
| `origin:top5_vs_other` | 73 | **+0,01453** | **−0,19496** |
| `home_origin_league:PL` | 39 | **+0,01228** | **−0,21393** |
| `origin:top5_vs_top5` | 102 | −0,02077 | −0,03655 |
| `origin:other_vs_top5` | 73 | −0,01080 | −0,10572 |
| `origin:other_vs_other` | 35 | −0,04128 | −0,03545 |

Auch die Ligastärke-Evidenzklassen verbessern sich durchgehend, Cold
Start eingeschlossen (`−0,14285` bei n=55).

#### Verdict: `rejected`

Zehn von elf Gates sind erfüllt. Ein einziges nicht:

| Segment | n | V0 | C15 | Δ |
| --- | ---: | ---: | ---: | ---: |
| `home_origin_league:PD` | 36 | 0,84482 | 0,85668 | **+0,01186** |

Spanische Heimteams werden geringfügig schlechter. Die Schwelle für
schwere Segmentverschlechterung liegt bei `0,01`, importiert aus V2-C2B
und nicht für C15 gewählt. V0 ist auf diesem Segment mit 0,84482 der
stärkste Wert aller Herkunftssegmente, es gibt dort also wenig zu
gewinnen und etwas zu verlieren.

Sieben der acht Herkunftsliga-Segmente verbessern sich zwischen
`−0,03` und `−0,21`. Das ändert nichts am Urteil: Der Vertrag stand vor
der Messung, und die Schwelle wird nicht nachträglich verschoben, weil
das Ergebnis sonst gefiele.

**Kein Modell wurde aktiviert.** Die Registry ist unverändert, es gibt
weiterhin kein aktives Modell, und V0 bestimmt jede sichtbare
Nutzerantwort.

#### Konzentration

Die fünf stärksten Vereine tragen 28,7 Prozent der Verbesserung, gegen
67,7 Prozent in C14. Die Richtung hält ohne sie, für jeden einzeln
weggelassenen Verein und für jede einzeln weggelassene Liga. 66,4
Prozent aller Einzelspiele haben einen geringeren Verlust.

#### Drei technische Reparaturen, unabhängig vom Verdict

**Der C11-Vertrag ist jetzt zustandsfrei.** Der Vertragsfingerabdruck
wurde über das gesamte Artefakt gebildet, also einschließlich
`models_by_stage`, `active_model_id` und `registry_fingerprint`. Jede
Modellregistrierung bewegte ihn, und man konnte nicht mehr sehen, ob
sich die Regel geändert hatte oder nur die Belegung. Er deckt jetzt
ausschließlich die unveränderlichen Blöcke; der Zustand hat einen
eigenen `state_fingerprint`.

**Der Accepted-Pfad ist gebaut.** In `c12_evaluation.apply_decision`
stand ein `NotImplementedError`. Ein Freigabeweg, den nie jemand
gegangen ist, fällt genau dann aus, wenn man ihn zum ersten Mal
braucht. Er ist jetzt vollständig implementiert und durch synthetische
Fälle bewiesen, obwohl die aktuelle Messung ihn nicht auslöst.

Dabei kam ein echter Fehler ans Licht: Der Weg wollte direkt von
`candidate` nach `active`. Die Registry lehnte das zu Recht ab, denn
ein nie im Schatten gelaufenes Modell soll nicht mit seiner ersten
Ausführung die Nutzerantwort bestimmen. Der Freigabeweg geht deshalb
über `candidate`, `shadow` und `active`, und jeder Schritt trägt seine
eigene gebundene Freigabe.

**Artefakt und Registry laufen jetzt transaktional.** Vorher wurde erst
das Artefakt geschrieben und dann die Registry. Schlug der zweite
Schritt fehl, behauptete das Artefakt einen Zustand, den es nicht gab.
Jetzt gilt: alles prüfen, Vorzustand sichern, Registry schreiben,
erneut von der Platte validieren, und **erst danach** das
Releaseartefakt. Ein Journal hält den Fortschritt fest, und ein
Recovery liest daran ab, welcher Zustand gilt. Abbrüche an jeder
Schreibgrenze sind getestet.

**Rollback ist jetzt belegt statt behauptet.** V2-C12 setzte
`rollback_target = None` und meldete trotzdem `rollback_possible: true`.
Vor jeder Anwendung wird nun ein Vorzustand gesichert, und der Rollback
läuft über genau diesen Stand. Ein manipulierter oder unlesbarer
Rollbackstand scheitert fail-closed, und ein fachlich abgelehntes
Modell wird durch einen Rollback nicht wieder aktiv: Rollback ist
technische Wiederherstellung, kein Weg um ein Rejected herum.

**Die Gründeliste ist vollständig.** In C14 nannte sie drei von vier
fehlgeschlagenen Bedingungen, weil `no_single_fold_carries_all` keinen
Grundtext hatte. Jede Bedingung hat jetzt einen, und ein Test prüft,
dass Gate-Matrix und Gründeliste exakt übereinstimmen.

#### Reproduzierbar

```bash
python run_ml.py --evaluate-c15
python run_ml.py --release-c15 dry-run
```

Zwei Läufe liefern denselben Ergebnisfingerabdruck
`9f5bd6549d7210da6636f82e890e82c1bfe71e24fbbe2a1d7ca55d1d57415054`,
dieselben Foldmetriken und dasselbe Verdict. Der Exit-Code ist `1`,
solange das Verdict nicht `accepted` lautet. Der Freigabe-Trockenlauf
verweigert bei `rejected` mit Begründung.

*V2-C15 misst und entscheidet, es aktiviert nicht. Der individuelle
Regler-Modus bleibt vollständig getrennt und lädt kein Modell. Es gibt
keinen unangetasteten Holdout: Die Ligastärkeform wurde aus einer
C14-Diagnose auf denselben Saisons abgeleitet. Das ist
Entwicklungsevidenz und ausdrücklich keine unabhängige Bestätigung.*

### Gedämpfte Ligastärke und Freigabeentscheidung (V2-C16)

V2-C15 bestand zehn von elf Gates. Gescheitert ist genau eines, und
zwar knapp:

| Segment | n | ΔLog Loss | Grenze |
| --- | ---: | ---: | ---: |
| `home_origin_league:PD` | 36 | +0,01186 | 0,01000 |

Die Ligastärkekorrektur wirkt insgesamt stark und richtig, aber sie
überkorrigiert an einer Stelle über die eingefrorene Grenze.

#### Zweck der globalen Dämpfung

C16 baut ausdrücklich **keine** spanische Ausnahme. Kein `if league ==
"PD"`, kein eigener Faktor für eine im Test auffällige Liga, keine
Vereinsnamen in der Modelllogik, kein Routing nach Testsegment. Eine
Regel, die aus einem Testergebnis entsteht, ist keine Regel, sondern
eine Anpassung an genau diesen Test. Ebenso wenig wird die Grenze von
0,01 gelockert oder das Segment verkleinert.

Stattdessen wird die **gesamte** Korrektur global gedämpft:

```
lambda_heim' = lambda_heim * exp(gamma * (a[liga_heim] + d[liga_gast]))
lambda_gast' = lambda_gast * exp(gamma * (a[liga_gast] + d[liga_heim]))
```

`gamma` liegt in (0, 1] und wirkt auf **jede** Liga mit demselben Wert.
Bei `gamma = 1` ist das Wort für Wort die C15-Formel, die damit im
Kandidatenraum liegt und gewinnen kann.

Der Gedanke ist kein Ausweichen vor dem PD-Segment, sondern der übliche
Umgang mit einer aus wenigen Partien geschätzten Größe: Fold 1 schätzt
30 Ligaparameter aus 218 Beobachtungen. Eine Punktschätzung aus so
wenig Material ist im Mittel zu groß, und `gamma` ist die einfachste
generalisierte Form, sie zu schrumpfen. Dass davon auch PD profitiert,
ist eine Folge und nicht der Zweck.

#### Zeitliche Gamma-Auswahl

Vier vorab eingefrorene Werte: `(0,25, 0,50, 0,75, 1,00)`. Das Gitter
wird nach Sichtung der Ergebnisse nicht erweitert.

Gewählt wird auf einer zeitlichen inneren Validierung **innerhalb** der
Trainingshistorie, nach derselben Regel wie Alpha: bei einer
Trainingssaison Teilung am mittleren Spieldatum, bei mehreren Teilung
nach Saison. Geschätzt wird auf dem frühen Teil, bewertet auf dem
späten. Kriterium ist die Poissondevianz; bei Gleichstand innerhalb der
Toleranz gewinnt das **kleinere** Gamma, also die vorsichtigere Wahl.

Der äußere Testfold sieht weder Gamma noch Alpha noch die Grenzen. Das
ist nicht behauptet, sondern geprüft: Werden alle Testergebnisse auf
9:0 gesetzt, bleiben Gamma, Alpha und sämtliche Ligaparameter
identisch. Werden dagegen die Historienergebnisse verändert, bewegen
sie sich sehr wohl. Beide Prüfungen laufen für beide Folds.

Gewählt wurden **1,00** für `cl_2024` und **0,75** für `cl_2025`.

#### Unterschied zwischen C14, C15 und C16

| | C14 | C15 | C16 |
| --- | --- | --- | --- |
| Merkmale | 16 | 16 | 16 |
| Ligastärke | keine | ungedämpft | global gedämpft |
| neue Freiheitsgrade | keine | 2 je Liga | 2 je Liga plus **ein** globales Gamma |

#### Zentrale Messergebnisse

Standardbestand, 283 zeitlich getrennte Testspiele:

| Kandidat | Log Loss | Brier | RPS | Kalibrierung | Accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| V0 | 1,02842 | 0,61870 | 0,24412 | 0,04346 | 0,47350 |
| C14 | 1,01679 | 0,61162 | 0,24131 | 0,03340 | 0,49470 |
| C15 | 0,93330 | 0,55013 | 0,21113 | 0,03923 | 0,59717 |
| **C16** | **0,94086** | **0,55574** | **0,21371** | 0,04541 | 0,58657 |

| Vergleich | ΔLog Loss | 95-Prozent-Intervall |
| --- | ---: | --- |
| C16 gegen V0 | **−0,087560** | **[−0,118828; −0,055146]** |
| C16 gegen C14 | −0,075931 | [−0,104823; −0,044407] |
| C16 gegen C15 | +0,007558 | [+0,000693; +0,014013] |

Die Dämpfung kostet gegenüber C15 messbar etwas Gesamtgüte. Das ist der
bewusste Preis für die Stabilität und wird nicht schöngeredet.

| Fold | C15 | C16 | Gamma |
| --- | ---: | ---: | ---: |
| `cl_2024` | −0,066131 | −0,066131 | 1,00 |
| `cl_2025` | −0,125147 | −0,109758 | 0,75 |

Kontextbestand, 373 Spiele: ΔLog Loss −0,071891, ΔBrier −0,050251,
ΔRPS −0,024870.

Das blockierende Segment:

| Segment | n | C15 | C16 | Grenze |
| --- | ---: | ---: | ---: | ---: |
| `home_origin_league:PD` | 36 | +0,01186 | **+0,00985** | 0,01000 |

Es ist das einzige interpretierbare Segment mit positivem Delta.

Konzentration: Die fünf stärksten Vereine tragen 28,1 Prozent. Die
Richtung hält ohne sie, für jeden einzeln weggelassenen Verein und für
jede einzeln weggelassene Liga. 65,7 Prozent aller Einzelspiele haben
einen geringeren Verlust.

#### Gate-Ergebnis

**Alle elf Gates erfüllt. Verdict `accepted`.**

Die Grenze von 0,01 wurde nicht verändert. Der Vertrag stand mit dem
Fingerabdruck
`f6ce4b94e097015744d7a686314dcd6db3ce14359552a6b5864c773d24c5eb40`
fest, bevor eine Zahl gerechnet wurde.

#### Registry, aktives Modell und Fallback

**Es wurde trotzdem kein Modell aktiviert.**

Beim Bau des Freigabebundles zeigte sich eine echte Vertragsgrenze: Der
Bundlevertrag aus V2-C0B verlangt ein Evaluationsartefakt mit
`configuration.task == "cl_shadow_backtest"`, einen passenden
Kandidatennamen, und `load_bundle` prüft denselben Namen gegen
`cl_evaluate.CANDIDATE`. Ein **zweistufiges** C16-Modell erfüllt keine
dieser drei Bedingungen.

Sie gleichzeitig aufzuweichen wäre genau die Umgehung, gegen die V2-C11
und V2-C15 gebaut wurden. Der Freigabeweg scheitert deshalb fail-closed
mit klarem Grund, statt ein Bundle zu erzeugen, das der Loader später
ablehnt oder, schlimmer, ein halbes Modell mit dem Etikett eines
ganzen.

Die Registry ist unverändert, es gibt weiterhin kein aktives Modell,
und V0 bestimmt jede sichtbare Nutzerantwort. Der individuelle
Regler-Modus bleibt vollständig getrennt und lädt kein Modell.

Die Laufzeit ist auf die zweite Stufe bereits vorbereitet: Trägt ein
Bundle einen `league_strength`-Block, wendet `inference` die gedämpfte
Korrektur an; trägt es keinen, rechnet es Bit für Bit wie zuvor. Fehlt
eine Team-ID oder ist eine Liga unbekannt, bleibt die Partie
unkorrigiert. Damit nimmt ein Rollback auf ein älteres Bundle die
zweite Stufe vollständig zurück.

#### Fehlender unangetasteter Holdout

Die Dämpfungsform wurde aus einem C15-Ergebnis auf denselben Saisons
abgeleitet. Das ist Entwicklungsevidenz und ausdrücklich keine
unabhängige Bestätigung. Eine unabhängige Bestätigung wäre erst mit
Saison 2026/27 möglich.

#### Reproduzierbar

```bash
python run_ml.py --evaluate-c16
python run_ml.py --release-c16 dry-run
```

Zwei Läufe liefern denselben Ergebnisfingerabdruck
`4f8c7d05a130cfda97052e10c96e26c0a81b189bb84d55c6b8f0d92e2995420a`,
dieselben Gammawerte, dieselben Foldmetriken und dasselbe Verdict.

Rollback und Recovery laufen über den in V2-C15 gebauten
transaktionalen Weg (`--release-c16 rollback` und `--release-c16
recover`) und sind unverändert getestet.

#### Deploymentstatus

Der Code ist konsistent, getestet und ohne neue Regressionen. Es ist
kein Modell aktiv, daher wäre ein Deployment ein reines
Code-Deployment ohne Änderung der Nutzerantwort. Nichts wurde gestaged,
committet, gepusht oder deployed.

### Mehrstufiger Bundlevertrag, aktive V2-Runtime und individuelle Regler (V2-C17)

V2-C16 war statistisch akzeptiert, konnte aber nicht freigegeben werden:
Der Bundlevertrag aus V2-C0B kannte nur einstufige Modelle und hat das
zweistufige C16-Bundle korrekt fail-closed abgelehnt. C17 erweitert
diesen Vertrag ausdrücklich, gibt das Modell regulär frei und räumt
gleichzeitig die individuellen Regler auf.

#### Der C17-Bundlevertrag

Fingerabdruck
`03763962fb7171e296d3ecb10addedbb5cb4277a31bcc70131cdf7a1d59cbfd3`,
festgeschrieben in
`data/ml/c17_multistage_bundle_release_contract.json`, bevor das erste
Bundle gebaut wurde.

Die bestehenden Schranken wurden **nicht** gelockert. Es gibt keine
Ausnahme der Form „alle Kandidatennamen erlauben" und keine
abgeschaltete Prüfung. Erweitert wurde namentlich:

| Liste | Inhalt |
| --- | --- |
| `ALLOWED_MULTISTAGE_CANDIDATES` | `team_profile_cl_plus_damped_league_strength` mit den Pflichtfeldern seiner zweiten Stufe |
| `ALLOWED_EVALUATION_TASKS` | `cl_shadow_backtest` (unverändert) und `v2-c16 damped league strength evaluation` |

Was nicht in diesen Listen steht, wird abgelehnt.

#### Schema 3

| Regel | Verhalten |
| --- | --- |
| Schema 1 und 2 | bleiben unverändert lesbar |
| Schema 2 mit `league_strength` | abgelehnt, eine zweite Stufe gehört in Schema 3 |
| Schema 3 ohne zweite Stufe | abgelehnt |
| Schema 3 ohne Gamma oder mit Gamma außerhalb (0, 1] | abgelehnt |
| Schema 3 mit unzulässigem Kandidaten | abgelehnt |
| unbekannte Fassung | abgelehnt |

**Fail-closed, und zwar ganz.** Ist die zweite Stufe beschädigt, gilt
das **gesamte** Bundle als ungültig. Nur die Basisstufe weiterrechnen
zu lassen wäre die gefährlichste Variante: Das Ergebnis sähe
vollständig aus, wäre es aber nicht, und niemand hätte einen Anlass
nachzusehen.

#### Das freigegebene Modell

| Größe | Wert |
| --- | --- |
| Modell-ID | `clm-3475c9aacef6fec9-lsa165be9c` |
| Bundlepfad | `data/ml/models/clm-3475c9aacef6fec9-lsa165be9c.json` |
| Bundle-Hash | `b46c515e331fcc675e1c29898f844b80383ef1762f0d0225927f61f4f58cfc84` |
| Bundle-Schema | 3 |
| Freigabestufe | `approved` |
| Gamma | 1,00 |
| Ridge-Alpha der zweiten Stufe | 0,01 |
| Ligen | 23 |
| Vereine in der Ligazuordnung | 63 |
| Freigabeklasse | `accepted_development_evidence` |

Die Modell-ID trägt den Fingerabdruck **beider** Stufen. Zwei Bundles,
die sich nur im Gamma unterscheiden, hießen sonst gleich, und ein
Rollback könnte das falsche erwischen.

Die Ligazuordnung liegt **im Bundle**. Sie zur Laufzeit aus den
Ligadateien zu holen hieße, bei jeder Simulation 23 Dateien zu lesen,
und es hieße, dass zwei Läufe desselben Bundles je nach Plattenstand
verschieden rechnen könnten.

#### Registry-Aktivierung

Der Weg lief über `candidate`, `shadow`, `active`, jeder Schritt mit
eigener gebundener Freigabe. Ein nie im Schatten gelaufenes Modell soll
nicht mit seiner ersten Ausführung die Nutzerantwort bestimmen.

| Zeitpunkt | Registry-Fingerabdruck |
| --- | --- |
| vor C17 | `65429a131fd048c991bba57cdeda2aca5d23719c9a234ceac58befbfa0026419` |
| nach C17 | `66345556ea317311fe3681700a2d4bf55d6f71a2fa303624145efe431a4f132a` |

Der in V2-C12 abgelehnte Eintrag `clm-8a4eda90a08395cc` bleibt als
`candidate` mit dem Status `rejected` erhalten. Ein abgelehntes Modell
wird durch keine spätere Änderung aktiv.

#### Runtime

Bis C17 las die Laufzeit einen **festen** Dateipfad und prüfte
anschließend, ob die Modell-ID darin die aktive ist. Das war
fail-closed und damit sicher, hieß aber auch: Ein neu freigegebenes
Modell wurde nie geladen, solange nicht jemand dieselbe Datei
überschrieb. Eine Freigabe, die man zusätzlich per Hand nachvollziehen
muss, ist keine.

Jetzt bestimmt die Registry, **welche** Datei geladen wird, und bleibt
zugleich die Instanz, die anschließend prüft, ob es die richtige war.

Nachgemessen an Arsenal (PL) gegen Ajax (NL1), Baseline 1,60 zu 1,10:

| Paarung | Lambda Heim | Lambda Gast |
| --- | ---: | ---: |
| Arsenal zu Hause | 2,2242 | 0,8809 |
| Ajax zu Hause | 0,8709 | 2,2000 |

Die Ligastärke wirkt richtungsabhängig, wie gemessen. Die API meldet
`applied: true` mit der Modell-ID.

**V0 ist nur noch technischer Notfallpfad.** Er greift bei fehlendem
Bundle, falschem Hash, fehlender oder beschädigter zweiter Stufe,
fehlendem Gamma, unpassender Evaluation, beschädigter Registry,
mehreren aktiven Modellen, einem aktiven Modell ohne Freigabe und
unbekannter Schemafassung. In all diesen Fällen meldet die API
ehrlich `applied: false` mit Grund.

#### Rollback und Recovery

Praktisch nachgewiesen, nicht behauptet:

1. Vorzustand gesichert
2. Modell aktiviert, Registry von `65429a13…` auf `062d7377…`
3. Rollback ausgeführt, Registry exakt zurück auf `65429a13…`, kein
   aktives Modell
4. erneut aktiviert auf den heutigen Endzustand `66345556…`

Ein manipulierter oder unlesbarer Rollbackstand scheitert fail-closed,
und ein fachlich abgelehntes Modell wird durch einen Rollback nicht
wieder aktiv.

#### V2-Prognose und eigene Einschätzung

Die beiden Modi heißen jetzt **V2-Prognose** und **Eigene
Einschätzung**. Sie schließen einander aus: Im ML-Modus wirken keine
individuellen Regler, im individuellen Modus wird kein Modell geladen,
und es gibt keine Mischung.

**Der ML-Regler ist entfallen.** Er war fachlich falsch: ML ist eine
Modusauswahl und kein dosierbarer Anteil. Ein Prozentregler daneben
suggerierte eine Mischung, die es nicht gibt. Die Auswahl steht in den
beiden Karten darüber.

#### Die vier individuellen Regler

Vorher gab es drei Faktoren plus den ML-Regler. Zwei der drei waren
**dieselbe Wirkung**. Nachgerechnet an der Torerwartungsformel

```
xh = avg_h * attack_home(heim) * defence_away(gast)
xa = avg_a * attack_away(gast) * defence_home(heim)
```

multiplizierte `Offensive` die Angriffswerte in **beiden** Profilen und
`Defensive` teilte die Abwehrwerte in **beiden**. Beide
Erwartungswerte wurden damit mit demselben Wert `f/d` skaliert: Wer die
Offensive um 10 Prozent anhob, hätte ebenso die Defensive um 9 Prozent
senken können. Zwei Bedienelemente für eine Wirkung sind keine Wahl,
sondern eine Verwechslungsgelegenheit.

Das Modell hat genau **zwei** Freiheitsgrade. Die vier Regler sind
deshalb vier **Richtungen** darin, und keine zwei sind dieselbe:

| Regler (DE) | Regler (EN) | Backendparameter | Neutral | Min | Max | Wirkung |
| --- | --- | --- | ---: | ---: | ---: | --- |
| Heimteam-Stärke | Home team strength | `home_strength` | 1,0 | 0,7 | 1,3 | nur Heimtore |
| Auswärtsteam-Stärke | Away team strength | `away_strength` | 1,0 | 0,7 | 1,3 | nur Gasttore |
| Heimvorteil | Home advantage | `home_advantage` | 1,0 | 0,5 | 1,5 | verschiebt, Summe bleibt |
| Torniveau | Goal level | `goal_level` | 1,0 | 0,75 | 1,25 | beide, Verhältnis bleibt |

Gemessen an einer Beispielpartie, jeweils am oberen Anschlag:

| Regler | Heimtore | Gasttore |
| --- | ---: | ---: |
| Heimteam-Stärke | +30,0 % | +0,0 % |
| Auswärtsteam-Stärke | +0,0 % | +30,0 % |
| Heimvorteil | +16,2 % | −13,9 % |
| Torniveau | +25,0 % | +25,0 % |

Mehr Regler wären keine zusätzliche Fähigkeit, sondern nur weitere
Linearkombinationen derselben Ebene. Eine Remisneigung wäre ein echter
fünfter Freiheitsgrad, verlangte aber einen Abhängigkeitsterm, den das
Torerwartungsmodell nicht hat. Ihn nur für einen Regler zu erfinden
wäre unbelegte Modelllogik.

Jeder Regler hat seinen Nullpunkt in der Mitte, links weniger, rechts
mehr. Die Grenzen im Frontend sind Bedienbarkeit; geprüft wird
ausschließlich im Backend. Alle 81 Kombinationen der Extremwerte
liefern endliche, positive Erwartungswerte.

#### Fehlender unangetasteter Holdout

Das freigegebene Modell trägt die Klasse
`accepted_development_evidence`. Die Modellform wurde auf denselben
Saisons abgeleitet, auf denen sie gemessen wurde. Eine unabhängige
Bestätigung wäre erst mit Saison 2026/27 möglich.

#### Lokale Befehle

```bash
python run_ml.py --evaluate-c16
python run_ml.py --release-c16 dry-run
python run_ml.py --release-c16 apply
python run_ml.py --release-c16 rollback
python run_ml.py --release-c16 recover
```

#### Deploymentstatus

Nichts wurde gestaged, committet, gepusht oder deployed. Der lokale
Stand ist bereit für Elies Commit und Push; das VPS-Deployment folgt
danach als eigener Schritt.

#### Härtung: Modustrennung bewiesen statt behauptet (V2-C17-Härtung)

Der ursprüngliche C17-Bericht behauptete eine strikte Trennung von
V2-Prognose und eigener Einschätzung und "kein Blending". Zugleich
blieb `ml_weight` ein gültiges API-Feld, und `parse_ml_weight()`
akzeptierte für `approach=custom` jeden Wert zwischen 0,0 und 1,0. Der
Widerspruch wurde nachgerechnet, nicht nur vermutet:

* `approach=custom` ohne jede Angabe lud das aktive Modell TROTZDEM
  (`inference.shadow_lambdas()` lief). Nur sein Gewicht war 0 und
  damit rechnerisch neutral; `applied` in der Antwort stand auf
  `true`.
* `approach=custom, ml_weight=0.5` lieferte über einen echten
  `POST /api/simulate` den Status 200 und ein Lambda genau zwischen
  der individualisierten Baseline und der vollen ML-Korrektur
  (`baseline_lambda_home=2.9928`, `final_lambda_home=2.9009` in einem
  Testlauf). Das war ein tatsächlicher, von außen über die reguläre
  HTTP-Route erreichbarer Blend-Kanal zwischen V0/individuellen
  Faktoren und der V2-Korrektur.

**Die Behebung:** `ml_weight` ist für keinen Ansatz mehr ein
Requestfeld. `cl_custom_factors.parse_options()` weist es ab, sobald
es im Request steht, unabhängig von seinem Wert, auch für die vormals
gültigen 0,0 und 1,0. Das Gewicht ist jetzt eine reine
Serverkonstante, ausschließlich aus `approach` abgeleitet:

| Ansatz | Gewicht | Individuelle Faktoren | ML-Bundle |
| --- | --- | --- | --- |
| `ml` | 1,0 (fest) | neutral, erzwungen | geladen |
| `custom` | 0,0 (fest) | frei wählbar | NICHT geladen |
| kein `approach` gesetzt | Umgebung entscheidet (Standard: aus) | neutral | nicht geladen |

`cl_custom_factors.ml_config()` liefert für `custom` seither den Modus
`off` statt `active` mit Gewicht 0: `runtime.resolve_simulation_lambdas()`
überspringt den ML-Zweig in `off` vollständig, ruft
`inference.shadow_lambdas()` also gar nicht erst auf. Vorher stand für
beide Ansätze `active`, und ein aktiviertes Modell wurde bei jedem
individuellen Request geladen und gerechnet, nur sein Effekt war meist
neutral (`faktor ** 0 = 1`). Rechnerisch wirkungslos ist nicht
dasselbe wie nicht geladen.

**Bewiesen statt behauptet:**

* Spy auf `inference.shadow_lambdas`: `approach=custom` ruft ihn kein
  einziges Mal auf, `approach=ml` genau einmal je Request
  (`tests/test_c17_hardening_mode_separation.py`,
  `TestKeinLoaderInCustomModus`).
* Dieselbe Prüfung gegen das echte, aktive C16-Modell (nicht gemockt):
  `approach=custom` meldet `applied: false`, `mode: off`,
  `model_id: null`, trotz aktiver Registry
  (`TestManipulationsmatrix.test_custom_mit_aktiver_registry_wendet_trotzdem_nichts_an`).
* Über 20 Manipulationsversuche, jeder mit fail-closed 400: intermediäre
  Gewichte (0,1/0,25/0,5/0,75/0,99), Grenzwerte (-1/2), Typen (String,
  `null`, `NaN`, `Infinity`), Legacy-Faktoren `attack`/`defence`,
  `approach=ml` mit nicht-neutralen Faktoren, unbekannte und
  großgeschriebene Ansätze, fehlendes `approach` mit `ml_weight`.
* Echte HTTP-Route (`tests/test_cl_approach_ui.py`,
  `tests/test_cl_custom_api.py`): derselbe Request, der vorher 200 mit
  einem Blend lieferte, liefert jetzt 400 mit `ml_weight` in der
  Fehlermeldung, für alle zuvor gültigen Werte einschließlich 0,0 und
  1,0.
* Echter Browser (Playwright, `tests/test_cl_approach_browser.py`,
  38 Tests, `--e2e -m e2e`): vier Regler sichtbar nur im individuellen
  Modus, kein ML-Einfluss-Regler, Moduswechsel in beide Richtungen,
  Tastaturbedienung, Reset, deutsche und englische Übersetzung, kein
  horizontaler Überstand bei 1440×900/390×844/320×568, Bedienflächen
  mindestens 44px auf dem Handy. Diese Datei war seit der ursprünglichen
  C17-Reglerumstellung nicht mehr aktualisiert worden und prüfte bis zu
  dieser Härtung die alte Oberfläche (`attack`/`defence`/`ml_weight`);
  sie ist jetzt auf den aktuellen Vertrag gebracht.

**Freigabezustand unverändert:** Registry-Fingerprint weiterhin
`66345556ea317311fe3681700a2d4bf55d6f71a2fa303624145efe431a4f132a`,
aktives Modell weiterhin `clm-3475c9aacef6fec9-lsa165be9c`,
Bundle-Hash weiterhin `b46c515e331fcc675e1c29898f844b80383ef1762f0d0225927f61f4f58cfc84`,
`validate_registry` weiterhin ohne Befund. Diese Härtung hat
ausschließlich den Request- und Konfigurationspfad geändert, nicht das
C16-Modell, seine Evaluation oder die Registry selbst; keine neue
Freigabe und kein erneutes Training.

### Drei Berechnungsansätze, ehrliche Ergebniszeile, Prozente und Logos (V2-C23)

Die CL-Einzelspielsimulation und die CL-Ligaphasensimulation bieten
dieselben drei Karten an. Beide Tabs teilen einen Zustand: Die Wahl
überlebt den Tabwechsel, ein Wettbewerbswechsel setzt sie wie bisher auf
Machine Learning zurück.

| Karte (DE) | Karte (EN) | `approach` |
| --- | --- | --- |
| Machine Learning | Machine learning | `ml` |
| Eigene Einschätzung | Your own assessment | `custom` |
| Klassische Simulation | Classic simulation | `classic` |

#### Semantik je Ansatz und Pfad

Geprüft wird zentral in `src/predict/cl_custom_factors.py`:
`parse_options()` für den JSON-Body von `POST /api/simulate`,
`parse_season_options()` für die Query-Parameter von
`GET /api/cl-season-sim`. Beide liefern dieselbe Optionsform, und
`ml_config()` macht daraus für beide Pfade dieselbe Laufzeitkonfiguration.

| `approach` | Einzelspiel | Ligaphase | ML |
| --- | --- | --- | --- |
| `ml` | Faktoren neutral; `factors` und `ml_weight` verboten | nur `approach=ml` | aktiv, Gewicht 1,0, fail-closed |
| `custom` | `factors` mit bis zu vier Faktoren | optional `home_advantage` und `goal_level` | aus, kein Modell geladen |
| `classic` | `factors` und `ml_weight` verboten | nur `approach=classic` | aus, kein Modell geladen |
| nicht gesetzt | wie bisher: `FOOTSIM_ML_MODE` entscheidet | wie bisher: `FOOTSIM_ML_MODE` entscheidet | Umgebung (alte Clients) |

Die Oberfläche sendet den Ansatz immer ausdrücklich, in beiden Pfaden.
Die Umgebungssteuerung bleibt für Clients ohne `approach` erhalten.

**Heimvorteil und Torniveau** wirken in beiden Pfaden über dieselbe
Funktion (`_ligaschnitt_anpassen`) auf eine Kopie des Ligaschnitts:
Heimtore mal Wurzel(Heimvorteil) mal Torniveau, Gasttore geteilt durch
Wurzel(Heimvorteil) mal Torniveau. Sie werden genau einmal angewandt, und
der zwischengespeicherte Ligaschnitt bleibt unverändert.

**Heim- und Auswärtsteam-Stärke** gibt es nur im Einzelspiel. In der
Ligaphase ist jeder Verein viermal Heim- und viermal Gastteam; eine
globale "Heimteam-Stärke" hätte dort keine Bedeutung. Die Oberfläche
zeigt dort nur die zwei globalen Regler, das Backend weist die beiden
Teamfaktoren mit 400 ab.

**Abgewiesen mit 400:** unbekannter Ansatz, `ml_weight` bei jedem
Ansatz, `factors` bei `ml` und `classic`, Teamfaktoren und `factors` in
der Ligaphase, globale Faktoren ohne `approach=custom`, nicht endliche
Zahlen (`nan`, `inf`), Text statt Zahl, Werte außerhalb der Grenzen,
doppelte Query-Parameter. Die Abweisung erfolgt vor jeder Rechnung.

**Parität:** Für jede offene Partie zum selben Stichtag liefert die
Ligaphase dieselben Lambdas wie das Einzelspiel, gemessen für `ml`,
`classic` und `custom` mit globalen Faktoren (36 offene Partien nach
Spieltag 6 der Saison 2025/26, größte Abweichung 0,0). Neutrales
`custom` ist bitgleich `classic`.

#### Neue Antwortfelder (additiv)

`POST /api/simulate` (CL und Ligen):

| Feld | Bedeutung |
| --- | --- |
| `simulations` | tatsächlich ausgeführte Anzahl nach der Begrenzung auf 100 bis 50.000 |
| `ml.effective_approach` | `ml`, `custom` oder `classic`: was tatsächlich gerechnet hat (nur CL) |
| `ml.ml_fallback` | `none` oder `full` (ML gewünscht, aber nicht angewandt) |
| `ml.league_stage_applied` | ob die Ligakorrektur griff (`true`/`false`), sonst `null` |

Das ältere Feld `ml.applied_approach` bleibt unverändert (gewünschter
Ansatz oder `environment_default`); die Wahrheit steht in
`ml.effective_approach`.

`GET /api/cl-season-sim`:

| Feld | Bedeutung |
| --- | --- |
| `ml.requested_approach` | gewünschter Ansatz, `null` bei alten Clients |
| `ml.effective_approach` | tatsächlich wirksamer Ansatz; `null`, wenn keine Partie offen war |
| `ml.ml_fallback` | `none`, `partial` oder `full` |
| `ml.ml_fixtures`, `ml.fixtures_total` | offene Partien mit ML und insgesamt |
| `ml.league_stage_applied` | Anzahl der Partien mit Ligakorrektur |
| `ml.fallback_reasons` | Rückfallgründe mit Anzahl |

#### Ergebniszeile

Unter der Überschrift des Ergebnisses steht, was die Antwort meldet,
nicht was die Karte zeigt: "Berechnet mit: Machine Learning" (EN
"Calculated with: Machine learning"). Bei vollem Rückfall: "Machine
Learning war hier nicht verfügbar. Berechnet wurde klassisch." In der
Ligaphase wird ein teilweiser Rückfall mit Zahlen benannt ("… für 30 von
36 offenen Spielen …"). Eine fehlende Ligakorrektur ist kein ML-Ausfall
und wird als Zusatz genannt. Modell-IDs erscheinen nicht.

Ein Karten- oder Reglerwechsel setzt ein angezeigtes CL-Ergebnis zurück,
statt es neben der neuen Wahl stehen zu lassen. Antworten, die unter
einem älteren Ansatz oder von einer überholten Anfrage stammen, werden
verworfen.

#### Prozente der häufigsten Ergebnisse

Anteil = Anzahl geteilt durch `simulations` mal 100. Beispiel: 421 von
5.000 Läufen ergeben "8,4 % aller Simulationen" (EN "8.4% of all
simulations"), das häufigste Ergebnis zusätzlich "421 von 5.000
Simulationen". Vorher wurde durch die Summe der fünf angezeigten
Ergebnisse geteilt; mit den Zählungen 421/402/384/375/146 ergab das
24,4 %. Fehlt `simulations` oder ist es ungültig, erscheinen keine
Prozentwerte. 1X2, K.-o.-Analyse und Tabellen sind unverändert.

#### Mannschaftslogos

Im Panel "Ausgewählt" und in der Ergebnisüberschrift der CL stehen die
Wappen beider Vereine, im Ergebnis immer die der berechneten Partie.
Zugelassen sind nur die Hosts aus `src/api/auth.py`
(`ALLOWED_CREST_HOSTS`, per Test synchron gehalten), nur `https`, ohne
Zugangsdaten und Fremdport, höchstens 500 Zeichen. Fehlende, defekte oder
fremde Wappen werden zu einem neutralen Platzhalter derselben Größe
(40 px, im Auswahlpanel und mobil 32 px). Lange Namen brechen um.

#### Tests

`tests/test_cl_three_approaches.py` (Validierung, echte Parität,
Faktoren genau einmal, kein Modell bei `classic`/`custom`, voller
Rückfall über eine leere temporäre Registry, teilweiser Rückfall,
HTTP-Vertrag, Prozent-, Ergebniszeilen- und Wappenfunktionen aus dem
echten `script.js` in Node). Browser: `tests/test_cl_approach_browser.py`
mit `--e2e -m e2e` (drei Karten, Tabwechsel, späte Antworten, Logos,
Layout bei 1280, 375 und 320 px).

### Spieler-Bestenlisten und Big-Games-Datenfundament (V2-C24)

Im Spielerbereich (Radar) steht direkt unter der Datenbasis ein
Umschalter **Spielervergleich | Bestenliste**. Standard ist der
Spielervergleich; die A-gegen-B-Oberfläche ist unverändert. Die
Bestenliste ersetzt nur den Bereich darunter: Saison (bei Big Games der
gemeinsame Zeitraum), Kennzahl (nicht bei Big Games), Anzahl (Top 5, 10,
15, 20 oder 30, Standard 10) und der Knopf **Bestenliste erstellen**.
Eine Liste entsteht ausschließlich auf diesen Klick; jeder spätere
Filterwechsel entfernt das gezeigte Ergebnis, bis erneut geklickt wird.
Jede Zeile lässt sich über die Player-ID als Spieler A oder B übernehmen;
Position und Datenbasis bleiben dabei stehen.

**Keine Gesamtpunktzahl.** Sortiert wird immer nach einer benannten
Kennzahl aus dem bestehenden Katalog (`player_metrics.METRICS`):

| Position | Kennzahlen (erste = Standard) |
| --- | --- |
| Sturm | Torbeteiligungen pro 90, Schüsse aufs Tor pro 90, Schlüsselpässe pro 90 |
| Mittelfeld | Schlüsselpässe pro 90, Torbeteiligungen pro 90 |
| Abwehr | Tacklings pro 90, Abgefangene Bälle pro 90, Zweikampfquote |
| Tor | Paraden pro 90, Gegentore pro 90 (niedriger ist besser), Anbieterbewertung |
| Alle Positionen | nur die Anbieterbewertung (API-Football) |

Reihenfolge: Kennzahl nach Richtung, dann mehr Minuten, dann Name, dann
Player-ID. Ein fehlender Wert bleibt fehlend und wird nie zu 0.

**Normale Datenbasen** lesen ausschließlich lokale Daten. Die Ligapools
bestimmen die Population (eindeutig über die Player-ID), die Werte
entstehen aus der lokal gespeicherten Profilantwort mit derselben
Rechnung wie im Einzelvergleich (`build_player_profile`, `compute_metric`).
Die im Pool gespeicherten Kennzahlen werden bewusst nicht benutzt: Für
2025/26 wichen bei 1.106 von 3.715 Einträgen die club_all-Minuten von der
heutigen Wettbewerbseinordnung ab. Mindestzeit wie bei Perzentilen und
Plots (450 Minuten, EM/WM 270). Die laufende Saison ist als vorläufig
markiert, fehlende oder unvollständige Ligapools werden genannt.

**Big Games** haben keine wählbare Kennzahl. Die Rangfolge ist fest der
bestehende **Big-Game-Score** aus `big_games.aggregate_big_games()`,
derselbe Wert wie im Einzelvergleich: einsatzzeitgewichteter Mittelwert
aus Spielerbewertung mal Kontextgewicht des Spiels, gebildet nur ab
3 Big Games und 180 Minuten. Das Kontextgewicht ist Gegnerstärke mal
Spielbedeutung, die Gegnerstärke stammt ausschließlich aus den
historischen UEFA-Snapshots der Saison bzw. den FIFA-Snapshots des
Spieljahres; es wird keine eigene Rangliste berechnet. Eine Liste gibt es
nur, wenn für jede Saison des Zeitraums ein vollständiger Datensatz
vorliegt (`data/big_games/leaderboard/`, nicht versioniert) und dessen
Snapshots unverändert auf dem Server liegen. Sonst `available: false` mit
Grund. Der Datensatz entsteht über dieselbe Funktion wie der
Einzelvergleich (`big_games_loader.compute_player_big_games_uncached`).

**Sammler** (`collect_big_games.py`): Standard ist der Trockenlauf ohne
jeden Anbieterabruf. Echte Abrufe nur mit `--execute` und
`--max-provider-requests` (1 bis 500), mit Sperre, Checkpoint und
Fortsetzung; vorhandene Cacheeinträge werden nie erneut geladen.

`GET /api/player-leaderboard` mit `scope`, `position`, `season`
(bzw. `season_from`/`season_to` bei Big Games), `metric` (bei Big Games
nur `big_game_score` oder weggelassen), `limit`. Die Route liest nur
vorbereitete Daten und löst nie eine Sammlung aus.
`GET /api/player-leaderboard-options` liefert den Auswahlkatalog.
Unbekannte oder doppelte Parameter und unpassende Kombinationen ergeben
400 mit stabilem `error_key`. Die Antwort enthält `available`, `reason`,
`source`, `metric`, `direction`, `limit`, `rows`, `eligibility`,
`coverage`, `provisional`, `incomplete`, `allowed_metrics` und
`allowed_limits`; keine Rohantworten, keine Rangdaten der privaten
Snapshots, keine Pfade.

## Roadmap

- [ ] Unterpositionen (IV/AV/DM/ZOM/Flügel/Mittelstürmer), sobald eine belastbare Datenquelle vorliegt, Einstiegspunkt ist vorbereitet
- [ ] Vereins-Streudiagramme (Datengrundlage liegt bereits im Pool)
- [ ] Asymmetrischer Expertenvergleich im Radar (unterschiedlicher Wettbewerbsumfang je Spieler)
- [ ] Vollständiger heller Modus
- [ ] Mehrsprachigkeit (Deutsch/Englisch)
- [x] Sichtbare Auswahl zwischen ML-Prognose und individuellen Reglern in der CL-Einzelspielsimulation (C8B, lokal)
- [ ] Entscheidung über eine Aktivierung des ML-Ansatzes als Vorgabe, erst sinnvoll, wenn der Champions-League-Backtest die Übertragung belegt

## Lizenz

Siehe [`LICENSE`](LICENSE).
