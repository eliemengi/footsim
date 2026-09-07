# FootSim

> Fußball-Simulation und -Analyse: Spiele simulieren, Ligen vergleichen, Spieler gegenüberstellen und in Streudiagrammen einordnen — auf Basis echter Saisondaten.

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
Alle Werte stammen aus echten Saisondaten — keine geschätzten oder erfundenen
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
Gesamtminutenzahl **neu berechnet** — nicht gemittelt. Quoten entstehen aus
Zähler und Nenner, nicht als Mittelwert einzelner Quoten. Ratings werden
minutengewichtet zusammengeführt.

### Radar

Positionsabhängige Achsen (Torwart, Abwehr, Mittelfeld, Angriff) oder ein
positionsübergreifendes Profil, wenn Spieler verschiedener Gruppen verglichen
werden. Das Radar verschwindet dabei nie — es wechselt nur die Achsen und
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
Grund: Jeder Request liest den kompletten Pool und aggregiert neu — bei sieben
Filtern würde Automatik Requests für Zwischenzustände auslösen, die niemand
sehen wollte. Außerdem bliebe unklar, ob das gezeigte Bild zu den aktuellen
Filtern gehört.

| Zustand | Button |
|---|---|
| noch kein Plot | **Plot erstellen**, aktiv |
| Plot da, Filter unverändert | *Plot aktualisieren*, deaktiviert |
| Plot da, Filter geändert | **Plot aktualisieren**, aktiv — alte Punktwolke wird sichtbar abgeblendet |
| lädt gerade | deaktiviert, `aria-busy` |

Ein Doppelklick erzeugt keinen zweiten Request; veraltete Antworten werden
über einen Request-Zähler entwertet.

**Das Diagramm** hat Raster, beschriftete Skalen, Achsenlabels und eine
Regressionslinie (erst ab 8 Punkten — darunter wäre sie statistisch
bedeutungslos). Ligen sind farbcodiert mit Legende.

**Punkte sind anklickbar.** Ein Klick öffnet eine Detailkarte mit Name,
Verein, Liga, Position, Alter, Einsatzminuten, beiden Achsenwerten und dem
verwendeten Wettbewerbsumfang. Sie schließt über den Schließen-Button, Klick
außerhalb oder Escape — nie automatisch nach Zeit. Auf Mobil wird sie zum
festen Sheet über der Bottom-Navigation.

Im Radar gewählte Spieler sind automatisch hervorgehoben — über Farbe **und**
weiße Kontur und Größe, nie über Farbe allein. Die zusätzliche Spielersuche
steht unterhalb des Plots, ist als optional gekennzeichnet und erzeugt keinen
neuen Request — sie markiert nur bereits geladene Punkte.

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
Importjob befüllt — nie innerhalb eines Nutzerrequests. Plots und Perzentile
lesen nur diesen Pool und lösen selbst **keinen einzigen API-Aufruf** aus.

## Player Pool und Importlogik

Der Player Pool ist ein persistenter Datensatz, **kein Cache**. Der
Unterschied ist wesentlich: Ein abgelaufener Cache lädt sich selbst nach —
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

Keine separaten Pools je Modus — ein Wechsel des Wettbewerbsumfangs kostet
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
> ist ein einmaliger Neuimport nötig — der alte Pool kennt nur Ligadaten.
> `--report` weist darauf hin.

## Caching

| Ebene | Ort | Gültigkeit |
|---|---|---|
| API-Antworten (Ligen, Tabellen, Spieler) | `data/cache/` | je Endpunkt, abgeschlossene Saisons 1 Jahr |
| Spielerprofil (rohe API-Antwort, alle Wettbewerbe) | `data/cache/` | 1 Jahr / 24 h bei laufender Saison |
| Suchergebnisse | `data/cache/` | 6 Stunden |
| Scatter-Punktlisten | `data/cache/` | 1 Stunde, Schlüssel aus allen Filtern inkl. Scope |
| Player Pool | `data/player_pool/` | persistent, nur durch Import erneuert |

Der Cache ist dateibasiert und damit **workerübergreifend** — bei mehreren
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
Poolstatus — bewusst kein separater Metadaten-Endpunkt, weil das Frontend
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
Pool** — ohne ihn zeigt FootSim ehrliche Rohwerte mit einem entsprechenden
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

- **[football-data.org](https://www.football-data.org)** — Ligastruktur, Tabellen, Spielpläne
- **[API-Sports](https://www.api-football.com)** — Spielerstatistiken, Transfers

Beide APIs werden ausschließlich serverseitig angesprochen. Kein API-Key im
Frontend.

### Bekannte Grenzen der Datenquellen

Kennzahlen, die diese Quellen nicht liefern — etwa xG, xA, progressive Pässe,
PPDA oder Trackingdaten — existieren in FootSim **nicht** und werden auch nicht
geschätzt.

Weitere Einschränkungen, die bewusst nicht kaschiert werden:

- **Positionen** liefert API-Sports nur in vier Gruppen (Torhüter, Abwehr,
  Mittelfeld, Angriff). Feinere Rollen wie Innenverteidiger oder Sechser wären
  geraten, nicht gemessen — deshalb gibt es sie nicht.
- **`passes.accuracy`** kommt je nach Liga als Prozentwert oder als absolute
  Passanzahl. Werte außerhalb 0–100 werden verworfen statt als falsche Quote
  angezeigt.
- **Die Liga-Seitenabfrage** des Importjobs liefert teils nur den ligaeigenen
  Statistikblock. Dann sind „Alle Vereinswettbewerbe" und „Nur Liga" identisch —
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
nachträglich — siehe [`docs/player_comparison.md`](docs/player_comparison.md)
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
deutlich (0.048 → 0.016) — das sind Hinweise, kein Nachweis.

### Freigabestufe statt zweier Wahrheitswerte

Bis C0B trug jedes Bundle `shadow_only = true` und
`production_approved = false` — während dieselbe Korrektur über
`approach=ml` mit vollem Gewicht in die Nutzerprognose gerechnet wurde. Die
Metadaten sagten das eine, der Laufzeitpfad tat das andere.

An ihre Stelle tritt **ein** geprüftes Feld mit drei Stufen:

| Stufe | Bedeutung |
| --- | --- |
| `shadow` | darf gerechnet und protokolliert werden, verändert aber **kein** Nutzerergebnis |
| `experimental` | darf unter dem ausdrücklichen Produktvertrag aktiv wirken — nicht statistisch abschließend belegt |
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

- **`off`** — Standard. Ausschließlich die bestehende Baseline. Es wird kein
  Modell geladen und keine ML-Funktion aufgerufen.
- **`shadow`** — Das Modell rechnet mit, die Diagnose steht in der
  API-Antwort, die Simulation benutzt weiterhin die Baseline.
- **`active`** — Die Simulation verwendet die gewichteten Werte, aber nur
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
**nicht** als `0.5` gedeutet, sondern abgewiesen — ein Tippfehler soll
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

Die CL-Einzelspielsimulation nimmt seit C8A zwei optionale Ansätze
entgegen — **pro Request**, ohne dass eine Umgebungsvariable oder ein
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
Torerwartung berechnet wird — der prozessweite Profilcache bleibt
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
greifen im Torerwartungsmodell an derselben Größe an — beide gleich weit
zu verstellen hebt sich rechnerisch auf. Und die individuelle Steuerung
gilt zunächst **nur für CL-Einzelspiele**; die CL-Saisonsimulation und
die K.-o.-Runden sind davon nicht erfasst.

### Die Auswahl in der Oberfläche

Seit C8B ist die Auswahl sichtbar — ausschließlich bei der
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
nur für den jeweiligen Browserzustand und den jeweiligen Request — sie
werden nirgends gespeichert und berühren keinen anderen Nutzer. Bei einem
Wettbewerbswechsel fallen sie auf den Standard zurück.

Bei der Champions League ist die Checkbox „Immer gleiches Ergebnis“
ausgeblendet und der Request trägt dort ausdrücklich `use_seed: false`;
für die Ligen bleibt sie sichtbar und wirksam.

Geprüft wird weiterhin ausschließlich serverseitig. Die Reglergrenzen
sind Bedienkomfort, keine Sicherheitszusage — sie liegen bewusst
innerhalb der Grenzen, die C8A durchsetzt.

**Was diese Auswahl nicht behauptet:** Dass „ML-Prognose“ nachweislich
genauer sei. Der Champions-League-Backtest ist unverändert nicht eindeutig
(siehe oben), das Modell steht auf `experimental`, und ein Liga-ML ist
nicht Bestandteil der fertigen CL-V1. Die Auswahl ist eine
Wahlmöglichkeit, keine Rangfolge.

### Die einheitliche Point-in-Time-Profilfabrik (V2-C1)

Bis V2-C1 gab es für dieselbe Frage — *wie stark war dieses Team zu
diesem Zeitpunkt?* — **zwei** Implementierungen: Der Trainingsdatensatz
baute jedes Profil zum Stichtag des Zielspiels, der Laufzeitpfad
(`_blend_top5_league_history_by_id`) blendete schlicht alle lokal
vorliegenden Saisons. Ein Profil für die Saison 2024 war zur Laufzeit
deshalb **identisch** mit dem für 2025.

Seit V2-C1 gibt es genau einen maßgeblichen Pfad:
[`src/features/pit_profiles.py`](src/features/pit_profiles.py). Datensatz
und Laufzeit rufen dieselbe Fabrik auf.

**Der Stichtag ist Pflichtbestandteil des Vertrags.** Es gibt keinen
Standardwert — kein „neueste Saison", kein `datetime.now()` tief in der
Rechnung. Braucht die Laufzeit „jetzt", bestimmt sie den Zeitpunkt am
Rand über `runtime_cutoff()` und reicht ihn herein; damit bleibt er in
Tests steuerbar.

| Fall | Stichtag |
| --- | --- |
| Trainingsdatensatz | Datum des Zielspiels |
| Historischer Backtest | Datum des jeweils simulierten Spiels |
| **Historische Nachsimulation** | **tatsächlicher Anstoß des Zielspiels** |
| Aktuelles/künftiges Spiel | `runtime_cutoff()` — heutiger Tag, 12 Uhr |

Für die Nachsimulation löst das Backend den Anstoß **selbst** auf
(`fixture_cutoff`) — aus derselben lokalen Historie, aus der auch die
Profile entstehen. Der Client sendet dafür nichts Neues: Saison und
Mannschaften stehen ohnehin im Request. Einen Zeitpunkt vom Client
entgegenzunehmen hieße, eine fachliche Wahrheit von außen bestimmen zu
lassen; so gibt es **keine Manipulationsfläche**.

Aufgelöst wird über die Paarung (Saison, Heim-ID, Gast-ID). Innerhalb
der regulären Phase ist sie je Saison eindeutig — nachgemessen über
2023–2025. Trifft dieselbe Paarung später noch einmal im K.-o.
aufeinander, gewinnt die reguläre Phase; blieben nur K.-o.-Partien,
gewinnt die **früheste** (weniger Information, nie mehr). Steht die
Begegnung nicht in der Historie, ist sie künftig oder unbekannt — dann
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

**Cache-Regel:** Jeder Zwischenspeicher trägt den Stichtag im Schlüssel —
sowohl in der Fabrik als auch im Simulations-Cache
(`cl_strengths:{season}:{cutoff}`). Ein Profil zum 01.10.2024 kann
dadurch nie durch einen Treffer für den 01.03.2025 ersetzt werden.

**Sichere Rückfälle:** Die Fabrik greift selbst nie auf das Netz zu. Sie
liest ausschließlich die versionierte Historie unter `data/historical/`.
Partien einer laufenden Saison, die lokal fehlen, holt die Laufzeit und
reicht sie herein — gefiltert werden auch sie mit demselben Stichtag.
Fehlt jede Quelle, bleiben die Profile leer und die bestehende
Neutralprofil-Kaskade greift; die Simulation liefert weiterhin ein
vollständiges Ergebnis.

**Provenienz:** Jede Antwort nennt `pit_cutoff`, `pit_season_ceiling`,
`cl_matches_known_at_cutoff` und `cutoff_inclusive`. `matches_through_date`
meldet seither das zuletzt **verwendete** Spiel statt des Rohbestands der
Datei.

Nachgewiesen ist die Parität: Für echte Zeilen des C1-Datensatzes liefert
der laufzeitnahe Pfad exakt dieselben Merkmalswerte und dieselbe
Profilherkunft wie der Datensatzpfad — siehe
[`tests/test_pit_profiles.py`](tests/test_pit_profiles.py).

#### Was V2-C1 noch offen lässt

- Der Schlüssel `cl_current_by_id` behält seinen Namen, obwohl er jetzt
  die gepoolte CL-Historie bis zum Stichtag enthält. Er steht im
  API-Vertrag und wird im Browser gelesen; die Umbenennung wäre eine
  sichtbare Vertragsänderung.
- Die Auflösung greift auf die **lokale** Historie zu. Eine Partie der
  laufenden Saison, die dort noch nicht steht, gilt als künftig und
  bekommt „jetzt" — für ein noch nicht gespieltes Spiel ist das richtig.
- V2-C1 bedeutet **kein** neues freigegebenes Modell und kein Deployment.
  Das Modell steht unverändert auf `experimental`, es wurde nicht neu
  trainiert und nicht hochgestuft.

### Belastungszeitleiste für Champions-League-Zeilen (V2-C2)

Bis V2-C2 trug **jede** der 503 CL-Zeilen in jedem Belastungsfeld `None`
und den Sammelvermerk `not_computed_for_cl`. Der Grund war fachlich
richtig, aber zu grob.

**Warum die Werte fehlten.** Die Zeitleiste liest fünf Ligen, die
Champions League und fünf nationale Pokale. Ein Verein aus einer anderen
Liga — Ajax, Benfica, PSV, Celtic — erscheint darin ausschließlich mit
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
Ist sie es nicht, bleibt der Wert `None` — mit der Ursache im
Qualitätsfeld statt eines Sammelvermerks.

| Saison | Seiten | vorher | nachher | Quote |
| --- | ---: | ---: | ---: | ---: |
| 2023 | 250 | 0 | 166 | 66,40 % |
| 2024 | 378 | 0 | 246 | 65,08 % |
| 2025 | 378 | 0 | 246 | 65,08 % |
| **gesamt** | **1006** | **0** | **658** | **65,41 %** |

Median 3 Tage, 3 von 658 Werten über 10 Tage. Home und Away identisch.
Vorherige Partie stammt aus PD/PL/BL1/SA/FL1 sowie FA Cup, Copa del Rey,
Coupe de France und CL — die Zeitleiste ist tatsächlich
wettbewerbsübergreifend.

**Cutoff-Regel:** unverändert die aus V2-C1. Nur Partien strikt vor dem
Stichtag zählen; das Zielspiel selbst nie. Die Abdeckungsprüfung schaut
ebenfalls ausschließlich zurück.

**Ruhezeitdefinition:** unverändert aus `workload.py` übernommen —
Stunden zwischen dem letzten Anstoß und dem Stichtag, daraus
`rest_days`. Fehlt eine Anstoßzeit, gilt 12 Uhr
(`FALLBACK_KICKOFF_HOUR`); die geringere Genauigkeit steht getrennt in
`rest_time_precision`. Ohne vorherige Partie bleibt der Wert `None` mit
`data_quality = "unavailable"` — kein erfundener Standardwert.

**Deduplizierung:** über `(competition, season, match_id)`. Dieselbe
Partie aus zwei Dateien erzeugt genau einmal Belastung.

**Crosswalk:** Pokaldaten kommen von API-Sports, Ligadaten von
football-data. `team_crosswalk` ordnet innerhalb einer Liga und Saison
zu; bleibt ein Name mehrdeutig, wird er **nicht** zugeordnet, sondern als
Konflikt gemeldet. Eine Partie ohne zuordenbare Mannschaft erzeugt keine
Belastung für einen falschen Verein.

### Die nationalen Ligen der übrigen CL-Teilnehmer (V2-C2B)

V2-C2 ließ 348 von 1006 Seiten (34,6 %) offen — mit **einer** Ursache:
`no_base_competition_in_timeline`. Betroffen waren 27 Vereine, deren
nationale Liga lokal nicht vorlag. V2-C2B beschafft genau diese Ligen.

**18 Ligen, 32 Liga-Saison-Kombinationen** — abgeleitet aus dem Bedarf,
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
`/leagues?team=<apisports_id>` aufgelöst — aus der Mannschaft heraus, die
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
Tschechien. Ihre Liga *ist* geladen — sie spielte zu diesem Zeitpunkt
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

Die Antwort dieses Blocks lautet **nein** — und das ist ein Ergebnis,
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
| `number_of_usable_matches` | überhaupt bekannte frühere Partien — beschreibt die *Quelle* |
| `workload_diff_*` | Differenz Heim minus Auswärts über Ruhezeit und alle vier Fenster |

**Fenstersemantik**, exakt und getestet: Die Grenze ist unten
geschlossen, oben offen — `cutoff − n Tage ≤ kickoff < cutoff`. Eine
Partie genau auf der unteren Grenze zählt **mit**, eine Sekunde davor
nicht mehr. Fehlt die Anstoßzeit, setzt die Zeitleiste Mittag an; das
verschiebt die Stundenzahl, nie die Zählung. Nicht ausgetragene Partien
stehen gar nicht erst in der Zeitleiste.

**Eine einzige Ruhezeitdefinition**, in `workload.py`. `rest_days`
entsteht aus `rest_hours` durch Abrunden — „zwei volle Tage Pause" darf
nicht „49 Stunden" heißen. Lange echte Pausen werden **nicht** gedeckelt:
41 Tage nach einer Winterpause sind die Wahrheit, und ein Deckel würde
sie zu einer anderen machen.

#### Verlängerung — was die Quellen wirklich hergeben

Hier war zuerst zu klären, ob ein Merkmal überhaupt zulässig ist.
`None` heißt deshalb ausdrücklich **„nicht bekannt"**, nicht „keine
Verlängerung":

| Quelle | Status | Verlängerung ableitbar? |
| --- | --- | --- |
| Pokale, nationale Ligen (API-Sports) | `FT` / `AET` / `PEN` | **ja**, direkt |
| Top-5-Ligen (football-data) | keiner | **ja** — ein Ligaspiel dauert 90 Minuten, das ist die Regel |
| CL-Rundenphase | `FINISHED` | **ja** — Rundenspiele kennen keine Verlängerung |
| CL-K.-o.-Runden | `FINISHED` | **nein** — ehrlich unbekannt |

Auf den 476 ausgewerteten CL-Teamseiten ist der Wert zu **98,11 %**
vorhanden und dort **ausnahmslos `complete`**: Kein einziges Fenster
enthält eine CL-K.-o.-Partie, weil die Rundenphase im Januar endet und
die K.-o.-Runden im Februar beginnen. Die fehlenden 1,89 % sind exakt
die neun Seiten ohne nationalen Grundtakt aus V2-C2B.

#### Redundanz — der deutlichste Befund

Gerechnet auf 2.917 Ligazeilen der Trainingssaisons, **nie** auf
CL-Zeilen:

- **19 von 27** Belastungsspalten sind *exakt* aus den übrigen
  zusammensetzbar. Der Grund ist Konstruktion, nicht Zufall: `diff =
  home − away`, also ist jede dritte der drei Spalten überflüssig.
- `extra_time_minutes` und `extra_time_matches` korrelieren mit
  **r = 1,0000** — die Minuten sind das 30-Fache der Partien.
- `rest_days` gegen `rest_hours`: r = 0,998, **VIF 654** und **635**.
- Keine konstante, keine vollständig fehlende Spalte.

Ein nicht bestimmbarer VIF ist deshalb **keine Entwarnung**; das Feld
`vif_status` sagt in jedem Fall, warum er fehlt.

#### Die Ablation

Vierzehn Varianten, **alle** berichtet. Jede enthält den vollständigen
V1-Satz und unterscheidet sich von ihm nur um die geprüfte Untergruppe —
die Frage lautet „hilft es *zusätzlich*", nicht „hilft es".

Entscheidend ist die **gepaarte** Differenz gegen V1: Der Vergleich
gegen die ungelernte Baseline kann sie nicht beantworten, weil beide
Intervalle denselben großen gemeinsamen Anteil enthalten.

| Variante | Δ gepaart gegen V1 | 95-%-Intervall | Urteil |
| --- | ---: | --- | --- |
| `team_profile_cl` (V1) | — | — | Kontrolle |
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
(+0,00397) — der lehrreichste Einzelbefund des Blocks: Was auf
Ligaspielen trägt, trägt in der Champions League nicht.

#### Warum das kein „fast" ist

Der V1-Kandidat selbst steht bei n = 213 und einem Intervall von
[−0,0299; +0,0114] — **rund 0,04 breit**. Ein Belastungseffekt müsste
diese Breite überwinden, um nachweisbar zu sein; die gemessenen Effekte
liegen bei 0,0005. Der Bestand ist um mehr als eine Größenordnung zu
klein, um die Frage zu entscheiden.

Deshalb heißen zwei Varianten INCONCLUSIVE und nicht REJECTED: Die
Unterscheidung ist keine Formalie. REJECTED schließt die Frage,
INCONCLUSIVE lässt sie offen — und offen ist sie hier.

#### Was bleibt

Alle Spalten bleiben im Datensatz, keine geht ins Modell. Der
Merkmalsvertrag `fg.SCHEMA_VERSION` steht auf 2; die Gruppe `workload`
ist dabei **unverändert** geblieben, damit die bereits berichtete
Variante `workload_only` weiterhin dieselben 24 Merkmale bezeichnet.
Die Verlängerungsfelder haben eine eigene Gruppe bekommen.

Artefakt: `data/ml/c3_workload_ablation_2023-2025.json` — mit
Featurevertrag, Fingerabdruck je Variante, Folddefinitionen, sämtlichen
Varianten, Konfidenzintervallen, Coverage und Redundanzdiagnostik.

*V2-C3 ist Analyse. Es ist kein finales V2-Modell und kein Deployment:
Es trainiert Kandidaten ausschließlich zur Messung, speichert kein
Bundle, aktiviert nichts und stuft nichts hoch. Das bestehende Modell
bleibt `experimental` und unverändert.*

### Form, Gegnerstärke und UEFA-Stärke (V2-C4)

Wieder gebaut, gemessen — und wieder **nichts aufgenommen**. Der
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
| `points_rate` | Punktequote in [0, 1] — Sieg 1, Remis 0,5, Niederlage 0 |
| `goal_diff_per_match` | Tordifferenz je Partie |
| `<scope>_matches` | Tiefe der Betrachtung — **Qualitätsfeld, kein Modellmerkmal** |

**Fenster nach Partien, nicht nach Tagen.** Ein 30-Tage-Fenster ist im
Januar leer und im April voll. Für Belastung ist das richtig (C3), für
Form falsch: „die letzten fünf" ist über eine Winterpause hinweg
dieselbe Aussage.

Sieben vorab festgelegte Betrachtungen: `all_3`, `all_5`, `all_8`
(wettbewerbsübergreifend), `domestic_5`, `cl_5`, `home_5`, `away_5`.
Drei Fenstergrößen und nicht mehr — jede weitere ist eine zusätzliche
getestete Variante, ohne die Stichprobe zu vergrößern.

**Weitere Festlegungen, alle getestet:**

- **Erst filtern, dann abschneiden.** „Die letzten fünf Heimspiele" ist
  nicht „die Heimspiele unter den letzten fünf Partien".
- **Ergebnisregel:** Der Stand nach 90 bzw. 120 Minuten zählt. Ein
  **Elfmeterschießen ändert ihn nicht** — die Quellen führen die
  Schützentore in eigenen Feldern, und ein Schützenduell sagt über
  Spielstärke wenig. Eine im Schießen entschiedene Partie gilt als Remis.
- **Nationale Form ohne Pokale.** Ein 5:0 in Runde zwei gegen einen
  Viertligisten ist kein Formbeleg. In der *allgemeinen* Form zählt es
  mit — dort ist Gegnerstärke ein eigenes Merkmal.
- **Mindesttiefe 2.** Ein Mittelwert über eine Partie ist kein Formwert,
  sondern dieses eine Ergebnis. Darunter bleibt der Wert `None`.
- **Keine Alterung innerhalb des Fensters.** Eine zweite
  Abklingkonstante wäre ein freier Parameter, den diese Datenmenge nicht
  bestimmen kann — das Fenster *ist* die Gewichtung.

#### Gegnerstärke: welcher Stichtag gilt

Die naheliegende Abkürzung wäre, die Gegnerstärke zum Stichtag des
Zielspiels zu nehmen. Sie wäre sogar leckagefrei gegenüber der
Prognose. Sie wäre trotzdem falsch: Das Profil zum Dezemberstichtag
**enthält das Ergebnis genau der Septemberpartie, deren Schwierigkeit
es beschreiben soll**.

`PitStrengthAtDate` löst das mit dem Stichtag der *damaligen* Partie.
Kosten: rund zehn Millisekunden je zusätzlichem Stichtag, 548 davon im
gesamten Bestand — bezahlbar, also wurde die richtige Variante gebaut.

`adjusted_points_rate_5 = Σ(punkte·stärke) / Σ(stärke)` — eine mit der
Gegnerstärke gewichtete Punktequote, **parameterfrei**. Eine
Erwartungskurve „welche Punktzahl ist gegen diese Stärke normal" bräuchte
einen freien Parameter, den niemand gemessen hat.

#### UEFA: was die Quelle wirklich hergibt

**Ein Verbandskoeffizient liegt nicht vor.** Alle sechs Snapshots tragen
ausschließlich `uefa_club_coefficient_top40`. Die eigentlich gesuchte
„Stärke der nationalen Liga" ist in diesem Bestand nicht vorhanden — und
wurde nicht erfunden. Stattdessen zwei sauber getrennte Größen:

| Spalte | Was sie ist |
| --- | --- |
| `uefa_club_coefficient`, `uefa_club_rank` | der offizielle Vereinskoeffizient |
| `uefa_country_top40_strength` | ein **abgeleiteter** Landeswert: Summe der Top-40-Koeffizienten desselben Landes |

Der Name trägt `top40`, weil das die Schwäche ist: Ein Land mit acht
Klubs in den Top 40 bekommt mehr als eines mit einem — unabhängig von
der Breite seiner Liga. Das ist kein Verbandskoeffizient und heißt auch
nicht so.

**Der Stichtag ist der Kern.** Der Koeffizient einer Saison X enthält
deren *eigene* Ergebnisse — belegt in den Daten: Der Snapshot 2026/27
ist `provisional` und liegt durchgehend deutlich unter 2025/26 (Real
Madrid 114,5 gegen 144,5), weil die laufende Saison erst wenige Punkte
beigesteuert hat. Für ein Spiel *in* Saison X wäre er damit
Zukunftsinformation.

> **Regel ohne Ausnahme:** Für eine Partie der Saison X gilt der
> Snapshot der Saison **X − 1**.

Fehlende Werte bleiben `None` mit sichtbarem Grund — und die Gründe sind
unterscheidbar: `club_not_in_top40` ist eine Aussage über den *Verein*,
`no_snapshot_for_season` eine Lücke der *Umgebung*. Beides in ein
einziges `None` zu legen würde eine fehlende Datenquelle wie eine
Vereinseigenschaft aussehen lassen.

**Die UEFA-Dateien sind gitignoriert** (`data/big_games/`). Der
Datensatzbau liest sie deshalb **standardmäßig nicht**
(`INCLUDE_UEFA_BY_DEFAULT = False`) — sonst wäre er aus einem frischen
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

Die 19 Seiten ohne CL-Form sind erstmals qualifizierte Vereine — ihr
Wert bleibt `None`, niemals 0. Eine Null hieße „hat alle CL-Spiele
verloren" und wäre die schärfste denkbare Falschaussage über sie.

**Die rechte Spalte ist der wichtigste Befund.** UEFA liegt im Training
für 28,55 % der Seiten vor, im Test für 71,64 %; bei der CL-Form ist es
umgekehrt. Der Median-Imputer füllt im Training also die Mehrheit, im
Test die Minderheit. Das ist derselbe Verteilungsbruch, an dem in V2-C2
schon `profile_depth` gescheitert ist — und eine starke Vorab-Erwartung,
dass diese Merkmale nicht übertragen.

#### Redundanz

Auf 2.917 Ligazeilen der Trainingssaisons, nie auf CL-Zeilen. Von 41
Formspalten sind **6 exakt kollinear** und **22 tragen VIF ≥ 10**.

- `home_uefa_country_top40_strength` gegen `away_...`: **r = 1,0000** —
  in einem Ligaspiel kommen beide Teams aus demselben Land, der Wert ist
  dort nichts als „welche Liga ist das". In der CL unterscheidet er sich.
- `adjusted_points_rate_5` gegen `all_5_points_rate`: r = 0,954 — die
  Gegneradjustierung bewegt wenig.
- `uefa_club_coefficient` gegen `uefa_club_rank`: r = −0,943.
- `all_5` gegen `domestic_5`: r = 0,92 — für einen CL-Teilnehmer *ist*
  die allgemeine Form überwiegend die Ligaform.

#### Die Ablation

Sechzehn Varianten, **alle** berichtet. Jede enthält den vollständigen
V1-Satz; gemessen wird die **gepaarte** Differenz gegen V1.

| Variante | Δ gepaart gegen V1 | 95-%-Intervall | Urteil |
| --- | ---: | --- | --- |
| `team_profile_cl` (V1) | — | — | Kontrolle |
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
mit **max VIF 8,42** und keiner exakten Abhängigkeit — sauber nach den
Vorgaben, und auf CL-Partien trotzdem **abgelehnt** (+0,00321).

Zum zweiten Mal nach C3 dasselbe Muster: *Was auf Ligaspielen trägt,
trägt in der Champions League nicht.*

#### Warum das erneut kein „fast" ist

V1 selbst steht bei n = 213 mit einem Intervall von [−0,0299; +0,0114] —
**rund 0,04 breit**. Der beste C4-Effekt beträgt 0,007. Bei 16
getesteten Varianten ist ein einzelner Punktschätzer dieser Größe kein
Nachweis, sondern eine Beobachtung.

*V2-C4 ist Analyse. Es ist kein finales V2-Modell und kein Deployment:
Es trainiert Kandidaten ausschließlich zur Messung, speichert kein
Bundle, aktiviert nichts und stuft nichts hoch. Das bestehende Modell
bleibt `experimental` und bitgleich.*

### Spielkontext: K.-o., Legs, Aggregat, neutraler Ort (V2-C5)

Bis V2-C4 waren **119 K.-o.-Partien** aus der Auswertung ausgeschlossen —
mit der Begründung „Zwei-Leg- und Verlängerungslogik nicht modelliert".
C5 modelliert sie. **Alle 119 sind wieder nutzbar**, keine bleibt aus
fachlichen Gründen draußen.

Aufgenommen wird trotzdem nichts: Der Kandidat bleibt `team_profile_cl`.

#### Der kanonische Vertrag

Ein Feld, nicht vier Wahrheitswerte. `match_type` ist genau einer von
`league_phase`, `ko_first_leg`, `ko_second_leg`, `ko_single_match`,
`final`; die Modellspalten werden daraus **abgeleitet**. Vier
unabhängige Bools könnten sich widersprechen — „Finale und Hinspiel" ist
keine Partie, die es gibt, aber eine Kombination, die vier Bools
zulassen. Eine Konsistenzprüfung läuft über jede Zeile (0 Verstöße bei
5.756 Zeilen).

**Die Herleitung benutzt keine Zukunft.** Ob eine Partie Hin- oder
Rückspiel ist, kommt aus *ihren eigenen* Metadaten — `stage` und
`matchday` (1 = Hinspiel, 2 = Rückspiel; das Endspiel trägt je nach
Saison `None` oder `0`, dort entscheidet die Runde). Bequemer wäre
gewesen, die Partien einer Paarung zu zählen — dann hätte ein Hinspiel
wissen müssen, dass später ein Rückspiel folgt.

#### Aggregatstand — die Perspektive

Alle Werte gelten aus Sicht der Mannschaft, die **in dieser Partie** zu
Hause spielt. Im Rückspiel ist das die Mannschaft, die im Hinspiel
auswärts war; die Tore werden gedreht. Genau hier entsteht der Fehler,
den niemand bemerkt: Ein Vorzeichendreher ergibt lauter plausible Zahlen
mit der falschen Mannschaft davor.

Nachgerechnet am Viertelfinale 2024/25: Arsenal 3:0 Real Madrid im
Hinspiel → im Rückspiel bei Real steht `aggregate_goals_for = 0`,
`aggregate_goals_against = 3`, `aggregate_diff = −3`, `aggregate_lead =
−1`. Bei allen 58 Rückspielen war das aktuelle Heimteam im Hinspiel zu
Gast — der drehende Pfad ist also durchgängig belegt.

**Kein erfundener Stand.** Hinspiel, Einzelspiel und Endspiel haben
keinen Vorstand: alle vier Werte `None`, `aggregate_available = 0`. Eine
Null wäre zweideutig — sie hieße zugleich „Gleichstand" und „keine
Information".

#### Historische Regeln

| Regel | Behandlung |
| --- | --- |
| Auswärtstorregel | Vom UEFA-Exekutivkomitee am 24.06.2021 zur Saison 2021/22 gestrichen → `season < 2021`. Im Bestand 2023–2025 **konstant falsch** |
| Formatwechsel | 2023 Gruppenphase (96 Rundenspiele), ab 2024 Ligaphase (144) plus die neue Runde `PLAYOFFS`. Beide Rundenphasen sind `league_phase`, **nie** K.-o. |
| Hin-/Rückspiel gegen Einzelspiel | Über `matchday`; eine K.-o.-Partie ohne Legkennung gilt als Einzelspiel, nicht stillschweigend als Hinspiel |
| Endspiel | Einzelpartie auf neutralem Platz |
| Verlängerung / Elfmeterschießen | **Nicht ableitbar** — siehe unten |

Die Auswärtstorregel ist reiner Regelkontext: Die Funktion bekommt die
Saison und sonst nichts. Sie aus dem Spielausgang abzuleiten wäre ein
Selbstleck.

#### Was die Quelle nicht hergibt

Die CL-Historie führt zu allen 503 Partien nur `date`, `match_id`,
`matchday`, `stage`, `status`, die beiden IDs und die beiden Torzahlen.

**Keine Spielstätte, keine Neutralitätsangabe.** `neutral_venue` ist
deshalb *abgeleitet*, nicht gemessen, und jede Zeile trägt ihre Herkunft
in `venue_source`. Die Regel ist an die **Runde** gebunden, nicht an eine
Jahreszahl — ein Endspiel im Stadion eines Finalisten (zuletzt 2012)
fiele so später als Abweichung auf, statt lautlos richtig zu wirken.
Grenze: Eine einzelne verlegte Partie wäre nicht erkennbar und liefe als
normales Heimspiel mit.

**Kein Verlängerungsstatus.** Alle 503 Partien tragen schlicht
`FINISHED` — weder `AET` noch `PEN`, keine Schützentore. Ob verlängert
wurde, ist daraus nicht ableitbar. Feststellbar wäre nur eine
Untergrenze: Eine über beide Legs ausgeglichene Paarung *muss* im
Elfmeterschießen entschieden worden sein. Im Bestand 2023–2025 gibt es
**0 solche Fälle**. Das ist ohnehin eine Aussage über das *Label* und
steht erst nach Spielende fest — sie wird ausdrücklich **nicht** als
Merkmal geführt.

Bleibt eine echte Label-Grenze: Ging ein Rückspiel in die Verlängerung,
enthält der erfasste Spielstand deren Tore, während die Baseline 90
Minuten modelliert. Diese Zeilen zu *entfernen* wäre schlechter als sie
zu behalten — der Ausschluss hinge am Ergebnis der Partie selbst und
wäre eine Selektion auf die Zielgröße.

#### Wiedergewonnene Zeilen

| | 2023 | 2024 | 2025 | Summe |
| --- | ---: | ---: | ---: | ---: |
| K.-o.-Partien | 29 | 45 | 45 | **119** |
| davon wiedergewonnen | 29 | 45 | 45 | **119** |
| weiterhin ausgeschlossen | 0 | 0 | 0 | **0** |

58 Hinspiele, 58 Rückspiele, 3 Endspiele. Alle 58 Paarungen tragen genau
zwei Partien, kein Einzelspiel und **keine mehrdeutige Paarung**. Keine
der 119 Zeilen scheitert an Profiltiefe oder neutralem Profil — der
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

Einzig `away_goals_rule_active` bleibt auch dort konstant — alle drei
Saisons liegen nach der Abschaffung.

#### Die Ablation

Acht Varianten unter dem Kontextvertrag, n = 303.

| Variante | Δ gepaart gegen V1 | 95-%-Intervall | Urteil |
| --- | ---: | --- | --- |
| `team_profile_cl` (V1) | — | — | Kontrolle |
| `+ neutral_venue` | +0,001769 | [−0,00418; +0,00952] | REJECTED |
| `+ knockout_context` | +0,007864 | [+0,00052; +0,01480] | REJECTED |
| `+ leg_context` | +0,009211 | [+0,00039; +0,01866] | REJECTED |
| `+ aggregate_state` | +0,012399 | [+0,00090; +0,02573] | REJECTED |
| `+ knockout_structure` | +0,015473 | [+0,00412; +0,02766] | REJECTED |
| `+ tie_state` | +0,017928 | [+0,00383; +0,03373] | REJECTED |
| `+ all_context` | +0,023368 | [+0,00664; +0,04235] | REJECTED |

**7 REJECTED, 0 INCONCLUSIVE, 0 ACCEPTED.** Sechs der sieben Intervalle
liegen **vollständig über null** — die Merkmale sind nicht bloß nutzlos,
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
lineares Modell ohne Interaktionsterm kann das nicht ausdrücken —
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
sämtlich in der zweiten Hälfte — die Anpasshälfte enthält deshalb keine
einzige Aggregatzeile, und die Alphawahl dieses Folds sieht die vier
Aggregatspalten nicht. Die äußere Anpassung sieht sie sehr wohl, und
Fold 2 (Teilung nach Saison) ist davon nicht betroffen. Die Einschränkung
steht hier, weil Fold 1 auch der Fold mit den deutlich schlechteren
Werten ist.

Artefakt: `data/ml/c5_context_ablation_2023-2025.json` — Kontextvertrag,
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
kein Merkmal hinzu — das ist C7.

#### Die zwei Quellen und ihre sehr verschiedene Zeitsemantik

Nachgemessen am 06.09.2026 mit **vier** Requests:

| Endpunkt | Was er liefert | Gültigkeitszeitpunkt |
| --- | --- | --- |
| `/players/squads?team=X` | den Kader, **ohne jede Zeit- oder Saisonangabe** | **keiner** |
| `/injuries?league=X&season=Y` | 2832 Einträge für die Bundesliga 2025, **auf einer Seite**, jeder mit `fixture.date` | das Partiedatum |

Der Unterschied ist der Kern des Zeitvertrags:

- `fetched_at` — der Abruf. Belegt ausschließlich: *spätestens jetzt war
  das so.*
- `effective_at` — der von der Quelle behauptete Zeitpunkt.

Fehlt der zweite, bleibt er `None`. Er wird **niemals** aus dem ersten
erfunden. Ein Kadersnapshot trägt deshalb `effective_at: null` und
`effective_at_status: unknown_source_has_no_timestamp` — eine
Kaderänderung „genau in dieser Sekunde" wäre erfundene Historie, und sie
sähe vollkommen plausibel aus.

#### Was „Availability" hier heißt — und was nicht

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

**Sperren sind enthalten** — aber als Freitext im selben Feld wie
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
einsatzbereit** — er ist nur nicht als Ausfall gemeldet.
Rotationsentscheidungen und nicht gemeldete Blessuren fehlen. Der Satz
steht in jedem Snapshot.

#### Archivformat

Kein neues Speichersystem: C6 benutzt das bestehende
`data/snapshots/<art>/<art>__<schlüssel>__<zeitstempel>.json` und
erweitert es um Fingerprint und strikten Lesevertrag.

- **Append-only.** Eine vorhandene Datei wird nie überschrieben; zwei
  Snapshots derselben Sekunde bekommen einen Zählersuffix.
- **Atomar.** Temporärdatei plus `os.replace`. Bricht das Schreiben ab,
  entsteht **keine** Enddatei — auch keine halbe.
- **Dedupliziert.** Ein Inhaltsfingerprint über die sortierten Nutzdaten
  entscheidet. Ändert sich nichts, wird nichts geschrieben; sonst
  entstünden 365 identische Kaderdateien pro Verein und Jahr.
- **Beschädigte Dateien** werden beim Auflisten übersprungen und
  **nicht** überschrieben.

Die Spielerliste wird nach ID sortiert abgelegt — ohne feste Sortierung
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
| 0 | `complete` — alles bearbeitet, nichts fehlgeschlagen |
| 3 | `partial` — gesammelt, aber nicht alles |
| 4 | `failed` — nichts Verwertbares |
| 5 | `busy` — ein anderer Lauf hält die Sperre |
| 2 | Aufrufsfehler |

Ein unvollständiger Lauf meldet **nicht** 0. Sonst stünde ein Timer, der
jeden Tag brav „erfolgreich" meldet, monatelang auf grün, während die
Hälfte der Historie fehlt.

#### Umfang und Priorisierung

Gemessener Tageslauf: **430 Scopes** — 24 Ligen für Ausfälle, 406 Teams
für Kader. Bei 7500 Tagesanfragen sind das 5,7 %.

Die Teamliste kostet fast nichts: 278 der 406 Teams stammen aus den
lokalen V2-C2B-Ligadateien (die API-Sports-IDs führen) — **null
Requests**. Die übrigen kommen über den bestehenden Siebentagecache von
`/teams`.

Priorität — kleiner Wert zuerst:

| | Was | Warum |
| ---: | --- | --- |
| 0 | Ausfälle Top-5 + CL | eine Anfrage liefert eine ganze Saison |
| 10 | Ausfälle der übrigen nationalen Ligen | dito |
| 50 | Kader der CL-Teilnehmer | eine Anfrage je Verein |
| 60 | Kader der Top-5-Ligen | |
| 90 | Kader der übrigen nationalen Ligen | |

Bricht der Lauf ab, ist der wertvollere Teil gesichert. Ein Verein, der
in Bundesliga **und** Champions League spielt, wird genau einmal
abgefragt — dedupliziert über die tatsächlichen Anfrageparameter.

#### Kontingent, Wiederholung, Fehler

Der bestehende API-Client bleibt unberührt; C6 ergänzt nur, was ein
Livepfad nicht braucht:

- **Kontingentkopfzeilen** werden gelesen
  (`x-ratelimit-requests-remaining` und drei weitere). Der bestehende
  Client verwirft sie.
- **Kontrolliertes Anhalten** bei 500 verbleibenden Tagesanfragen
  (`--quota-margin`), damit der Webbetrieb Luft behält.
- **Wiederholt** wird bei Netzwerkfehler, 429 und 5xx — mit
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

`O_CREAT|O_EXCL` — atomar auf **beiden** Betriebssystemen. `fcntl` gibt
es unter Windows nicht, `msvcrt` nicht unter Linux; die lokale
Entwicklung läuft unter Windows, der VPS unter Ubuntu.

Eine verwaiste Sperre wird übernommen, wenn sie älter als drei Stunden
ist **und** der eingetragene Prozess nachweislich nicht mehr läuft. Nur
nach Alter zu brechen würde einen langsamen, aber lebenden Lauf
abschießen; im Zweifel wird nicht übernommen.

#### Laufbericht

Jeder Lauf schreibt einen maschinenlesbaren Bericht nach
`data/snapshots/_runs/` — Start und Ende, Versionen, geplante gegen
tatsächlich abgefragte Scopes, ausgelassene mit Grund, Requests je
Endpunkt und Ergebnis, Retries, neue und unveränderte Snapshots, Fehler
je Scope, beobachtetes Kontingent, Coverage je Art mit Namen der nicht
erfassten Schlüssel, Fingerprint der Planung — und **keine Secrets**.

#### Der C7-Lesevertrag

```python
from src.data import snapshot_reader as sr

sr.squad_before(team_id, cutoff)                     # letzter Kader davor
sr.availability_entries_before(league_id, season, cutoff)
```

1. Nur Snapshots **strikt vor** dem Cutoff. Ein Stand mit
   `captured_at == cutoff` wird **nicht** geliefert — er könnte zur
   Anpfiffsekunde erhoben worden sein und bereits die Aufstellung
   enthalten. Derselbe Vertrag wie in V2-C1.
2. Fehlt ein Snapshot, kommt ein **sichtbarer** Fehlzustand
   (`available: False`, `missing_reason`) — niemals ein leerer Kader und
   niemals eine Null.
3. Jede Antwort trägt Herkunft und `age_days`. Ein Kaderstand von
   gestern ist etwas anderes als einer von vor drei Monaten.
4. Bei mehreren Snapshots derselben Sekunde gewinnt der zuletzt
   geschriebene — festgelegt und getestet.

**Zwei Zeitebenen bei Ausfällen.** Der Snapshot ist vor dem Cutoff
*erhoben*, seine Einträge beschreiben aber Partien, die danach liegen
können. `availability_entries_before()` filtert deshalb **zusätzlich**
nach `effective_at`; Einträge ohne Zeitpunkt werden getrennt gezählt und
nicht mitgeliefert — unbekannt ist nicht dasselbe wie wahr.

#### Betrieb auf dem VPS

Vorlagen in [`deploy/systemd/`](deploy/systemd/), Installations-,
Status-, Log- und Abschaltbefehle in
[`deploy/systemd/README.md`](deploy/systemd/README.md).

Täglich **04:30 UTC** — nach dem letzten europäischen Anpfiff des
Vortags und vor dem frühesten des laufenden Tages. Ausdrücklich UTC:
Eine Sommerzeitumstellung verschöbe sonst zweimal im Jahr den
Erhebungszeitpunkt. `Persistent=true` holt einen verpassten Lauf nach —
eine Lücke in dieser Historie lässt sich nicht nachträglich schließen.

Der Sammler hängt **nicht** an Gunicorn. Dort liefe er in jedem Worker
und bei jedem Neustart erneut. Die Dateisperre fängt das ab, ist aber
die zweite Verteidigungslinie.

**Der Timer ist vorbereitet, nicht aktiviert.**

#### Datenschutz und Speicherort

`data/snapshots/` ist gitignoriert — Rohdaten des Anbieters bleiben auf
dem Host. Das gilt auch für die Laufberichte: Sie tragen zwar keine
Rohdaten, aber Bezeichner, Kontingentstände und Fehlermeldungen genau
dieses Hosts. Zusammengeführt ergäben zwei Hosts eine Historie, die es
so nie gab.

Im Repository liegen stattdessen die **reproduzierbaren** Teile: Schema,
Sammlervertrag, Lesevertrag und die systemd-Vorlagen. Aus ihnen lässt
sich jede Sammlung nachvollziehen — nur eben nicht nachträglich
erzeugen.

*V2-C6 sammelt. Es trainiert kein Modell, aktiviert nichts und fügt dem
Modellvertrag kein Merkmal hinzu. Das bestehende Modell bleibt
`experimental` und bitgleich.*

### Kaderhistorie, Transfers und Vorsaisonstärke (V2-C7)

Erstmals in der V2-Reihe zeigen **alle** geprüften Varianten in die
richtige Richtung. Aufgenommen wird trotzdem nichts: Kein
Konfidenzintervall schließt die Null aus. Der Kandidat bleibt
`team_profile_cl`.

#### Zwei Informationsklassen — als Codevertrag, nicht als Absichtserklärung

| Klasse | Was | Verfügbar |
| --- | --- | --- |
| **A** — historisch rekonstruierbar | datierte Transferereignisse, abgeschlossene Vorsaisons | rückwirkend |
| **B** — erst seit C6 beobachtbar | Kader- und Verfügbarkeitssnapshots | ab `usable_from` |

`squad_history.data_class()` ordnet jeder Merkmalsfamilie ihre Klasse zu
und **bricht bei einer unbekannten ab** — ein stillschweigendes
„vermutlich Klasse A" ist genau die Annahme, die der Vertrag verhindert.
`class_b_is_usable()` entscheidet am *tatsächlichen* Archiv, nicht an
einer Zusicherung.

#### Was der Bestand hergibt — nachgemessen

| Quelle | Umfang | Grenze |
| --- | --- | --- |
| Transferereignisse (`data/cache/`) | 155 Dateien, 84.943 normalisierte Ereignisse, 24.404 Spieler, 3.346 Vereine | ein Datum je Wechsel, **keine** Unterscheidung Bekanntgabe/Wirksamkeit |
| Spielerpool (`data/player_pool/`) | 35 Dateien, 5 Ligen, Saisons 2020–2026 | **kein Datums- und kein Spieltagsfeld**, keine `team_id` |
| Snapshot-Archiv (C6) | 0 Kader-, 1 Verfügbarkeitssnapshot | jünger als jede CL-Partie |

Beide erstgenannten Quellen sind **gitignoriert**. Der Datensatzbau
liest sie deshalb nur auf ausdrückliche Anforderung
(`INCLUDE_SQUAD_HISTORY_BY_DEFAULT = False`) — dieselbe Entscheidung wie
beim UEFA-Schalter in C4, und aus demselben Grund: Ein bestehender Test
verlangt, dass der Standardbau ausschließlich `data/historical` liest.

#### Der Stichtagsvertrag

Alle Transferfenster filtern **strikt vor** dem Spieltag. Ein Wechsel,
dessen einziges bekanntes Datum der Spieltag ist, geht *nicht* ein — der
Anbieter unterscheidet nicht zwischen Bekanntgabe und Wirksamkeit, und
das ist die konservative Lesart.

Leistungswerte stammen ausschließlich aus **abgeschlossenen** Saisons
(≤ S−1). Der Pool ist eine Saisonaggregation ohne Datum; für ein Spiel
im Oktober der Saison S wäre er die Statistik einer Saison, die im Mai
darauf endet — die Vorhersage der Saison mit ihrem eigenen Ergebnis.

#### Spieleridentität

Primärschlüssel sind die API-Sports-`player_id` und `team_id`. Der Pool
trägt **keine** `team_id`, nur `team_name` — eine Zuordnung über den
Namen findet deshalb *nicht* statt; die Verknüpfung läuft ausschließlich
über `player_id` (85,6 % Überschneidung mit der Transferhistorie).

Die CL-Historie stammt von football-data und trägt andere Kennungen.
`squad_crosswalk` baut die Brücke aus zwei Quellen — den 27 in C2B
einzeln geprüften Vereinen und den nationalen Pokaldateien für die
übrigen. Ergebnis: **63 von 63 CL-Vereinen aufgelöst, 0 Widersprüche, 0
doppelte Ziele.** Ein Widerspruch würde den Eintrag *entfernen*, nicht
überschreiben: Unbekannt ist besser als vielleicht falsch.

Zur Größenordnung der Gefahr: Eine naive Gleichsetzung beider
Nummernkreise „trifft" 55 von 63 Vereinen — und liegt dabei durchweg
falsch.

#### Was nicht gebaut wurde, obwohl es naheliegt

**Keine Kadertiefe.** Die aus Transfers ableitbare Zugehörigkeit
überzählt systematisch: Sie sieht jeden Zugang, aber nur die
*gemeldeten* Abgänge — ein auslaufender Vertrag hinterlässt keinen
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
Saison gehen in die Stärkerechnung ein — darunter ist eine Bewertung
kein Mittelwert, sondern ein Einzelereignis. Die Bewertung ist eine
**Anbietermeinung**, keine Messung; sie ist die einzige über alle
Positionen vergleichbare Größe.

#### Nicht bewertbar — mit Beweis

| Familie | Status | Grund |
| --- | --- | --- |
| `squad_snapshot` | `NOT_EVALUABLE` | 0 Kadersnapshots |
| `availability_impact` | `NOT_EVALUABLE` | einziger Snapshot vom 06.09.2026 |

Die späteste CL-Partie dieses Bestands liegt am **2026-05-30**, der
einzige Snapshot am **2026-09-06**. Jede Beobachtung liegt damit *nach*
jeder auszuwertenden Partie. Es werden bewusst **keine Metriken**
ausgewiesen — eine Zahl ohne Beobachtung wäre schlimmer als eine Lücke,
weil sie wie ein Ergebnis aussieht.

**Reevaluationskriterium:** erst mit CL-Partien, die *nach* dem
Sammelbeginn liegen — konkret, sobald
`archive_window('squad').usable_from` vor dem Datum der auszuwertenden
Partien liegt und mindestens eine volle Saison gesammelt wurde. Dafür
muss der C6-Timer laufen; er ist vorbereitet und nicht aktiviert.

#### Die Ablation

Sechs Varianten, Vertrag und Gate wie C3/C4 (Training nationale Ligen,
Test CL-Reguläphase, n = 213).

| Variante | Δ gepaart gegen V1 | 95-%-Intervall | Brier | Urteil |
| --- | ---: | --- | ---: | --- |
| `team_profile_cl` (V1) | — | — | −0,00464 | Kontrolle |
| `+ all_squad_history` | **−0,009359** | [−0,02758; +0,00923] | −0,01076 | INCONCLUSIVE |
| `+ transfer_activity` | −0,005873 | [−0,02273; +0,01172] | −0,00882 | INCONCLUSIVE |
| `+ transfer_volume` | −0,005344 | [−0,02184; +0,01226] | −0,00862 | INCONCLUSIVE |
| `+ transfer_strength` | −0,005225 | [−0,01538; **+0,00489**] | −0,00777 | INCONCLUSIVE |
| `+ transfer_balance` | −0,003961 | [−0,01572; +0,00770] | −0,00785 | INCONCLUSIVE |
| `+ squad_reduced` | −0,003961 | [−0,01572; +0,00770] | −0,00785 | INCONCLUSIVE |

**6 INCONCLUSIVE, 0 REJECTED, 0 ACCEPTED.** Zum ersten Mal in der
V2-Reihe verbessert *jede* Variante den Punktschätzer, und Brier sowie
RPS zeigen dieselbe Richtung. `all_squad_history` ist in **beiden**
Folds negativ (−0,0182 / −0,0183) — ungewöhnlich stabil.

Gegen eine Aufnahme sprechen zwei Dinge: Kein Intervall schließt die
Null aus, und die **Kalibrierung verschlechtert sich** durchgehend
(V1 0,0165 → 0,0215 bis 0,0431). `transfer_strength` hat das engste
Intervall und die geringste Kalibrierungseinbuße.

Die Vorauswahl auf Trainingsdaten behielt nur `transfer_balance`
(max VIF 1,47, keine exakte Abhängigkeit) — dieselbe Variante kommt auf
CL-Partien auf −0,00396.

#### Aufnahmeentscheidung

**V1 bleibt unverändert.** Die C7-Merkmale sind technisch fertig,
PIT-sicher und vollständig getestet; sie werden als `experimental`
geführt und nicht aktiviert. Das Modellbundle bleibt bitgleich.

Artefakt: `data/ml/c7_squad_history_ablation_2023-2025.json` — mit
Quelleninventar, Zeit- und Cutoff-Verträgen, Identitätsdiagnostik,
Coverage, `NOT_EVALUABLE`-Begründungen samt Beweis, Fingerprints,
vollständigen Metriken, Redundanz und Reevaluationsbefehl.

#### Bekannte Grenzen

- Der Anbieter unterscheidet **nicht** zwischen Bekanntgabe- und
  Wirksamkeitsdatum eines Transfers.
- Leihenden und Vertragsdaten fehlen; eine Rückkehr ist nur sichtbar,
  wenn sie als eigenes Ereignis gemeldet wurde (3.886 von 84.943).
- Der Spielerpool deckt nur die fünf Top-Ligen — ein Spieler von
  außerhalb trägt keinen Vorsaisonwert und ist damit *unbekannt*, nicht
  schwach.
- Marktwerte werden nicht verwendet: Eine Ablösesumme ist ein
  Marktpreis, kein Leistungsmaß.

*V2-C7 ist Analyse. Es trainiert Kandidaten ausschließlich zur Messung,
speichert kein Bundle, aktiviert nichts und stuft nichts hoch. Das
bestehende Modell bleibt `experimental` und bitgleich.*

### Modellklasse, Interaktionen, Kalibrierung (V2-C8)

C3 bis C7 haben gezeigt, dass *mehr Merkmale* in derselben Modellklasse
wenig bringen. C8 fragt, ob die **Klasse** das Problem war — und
beantwortet die Frage mit **nein**, an drei Stellen einzeln nachgemessen.

**Kein Kandidat wird aufgenommen. Das Modellbundle bleibt bitgleich.**

#### Warum zwei Auswertungsverträge

Die zwölf C5-Kontextmerkmale sind im ursprünglichen Vertrag **konstant**
— gemessen, in Training *und* Test. Eine Interaktion auf einem
konstanten Merkmal ist ebenfalls konstant. Die Interaktionskandidaten
laufen deshalb unter dem **Kontextvertrag** (n = 303), die
Transformationskandidaten unter dem **Standardvertrag** (n = 213).

Jeder Kandidat wird ausschließlich gegen den V1-Kontrollarm **seines**
Vertrags gelesen, und beide Kontrollarme laufen im selben Lauf mit.
Zahlen über die Vertragsgrenze hinweg zu vergleichen wäre der bequemste
Weg zu einem falschen Ergebnis.

#### Die Kandidatenmatrix — vorab festgelegt

| Kandidat | Rolle | Vertrag | Was | Δ gepaart gegen Kontrolle | Urteil |
| --- | --- | --- | --- | ---: | --- |
| `M0_v1_control` | Kontrolle | Standard | unverändertes V1 | — | Kontrolle |
| `M1_c7_transformed` | Kandidat | Standard | C7 mit `log1p` | −0,006860 | INCONCLUSIVE |
| `M1c_…_calibrated` | Kandidat | Standard | M1 + Kalibrator | −0,008431 | INCONCLUSIVE |
| `M1r_c7_raw_control` | Kontrollarm | Standard | C7 **roh** | −0,009359 | — |
| `M0_v1_control_context` | Kontrolle | Kontext | unverändertes V1 | — | Kontrolle |
| `M2_c5_interactions` | Kandidat | Kontext | C5 als Interaktionen | +0,022717 | REJECTED |
| `M2r_c5_raw_control` | Kontrollarm | Kontext | C5 **roh** | +0,023368 | — |
| `M3_…_plus_interactions` | Kandidat | Kontext | M1 + M2 | +0,010467 | REJECTED |
| `M4_reduced` | Kandidat | Kontext | regelbasiert reduziert | +0,009176 | REJECTED |
| `M5_elastic_net_glm` | — | — | — | — | **NOT_EVALUATED** |

**0 ACCEPTED, 3 REJECTED, 2 INCONCLUSIVE, 1 NOT_EVALUATED.**

#### Eine unabhängige Bestätigung, nebenbei

`M1r_c7_raw_control` ist V1 plus die rohen C7-Merkmale — also genau das,
was V2-C7 als `+ all_squad_history` gemessen hat. C7 berichtete
**−0,009359**; C8 misst **−0,009359**, auf sechs Nachkommastellen, durch
eine vollständig andere Codestrecke (`c8_ablation` statt `cl_ablation`)
und mit eigener Alphawahl. Das war kein Ziel dieses Blocks, aber es ist
der beste verfügbare Beleg dafür, dass beide Ablationsmaschinen
dasselbe rechnen.

#### Die drei isolierten Wirkungen — der eigentliche Befund

Die Zahlen gegen V1 vermengen zwei Dinge: die zusätzlichen Merkmale und
deren *Behandlung*. Erst der Vergleich Arm gegen eigenen Kontrollarm —
beide im selben Lauf, auf demselben Bestand — trennt beides.

| Wirkung | Vergleich | Δ LogLoss | Kalibrierungsfehler | Befund |
| --- | --- | ---: | --- | --- |
| **Transformation** | M1 gegen M1r | **+0,002499** | 0,0431 → 0,0526 | **verschlechtert beides** |
| **Kalibrierung** | M1c gegen M1 | −0,001570 | 0,0526 → **0,0273** | verbessert beides |
| **Interaktion** | M2 gegen M2r | −0,000651 | 0,0238 → 0,0225 | verbessert, aber winzig |

**Die Transformationshypothese war falsifizierbar und wurde falsifiziert.**
Der Anlass war real und nachgemessen — `arrivals_365d` hat im Training
Median 16, im Test 32, `arrivals_120d` trägt Schiefe +2,06 —, aber
`log1p` verschlechtert Punktschätzer *und* Kalibrierung. Der lineare
Koeffizient kam mit dem Skalenversatz offenbar besser zurecht als die
gestauchte Skala. Das ist das Ergebnis; es wird nicht umgedeutet.

**Die Kalibrierung funktioniert wie entworfen** und halbiert den
Kalibrierungsfehler (0,0526 → 0,0273) — reicht aber nicht an V1 heran
(0,0165). Sie repariert einen Schaden, den die zusätzlichen Merkmale
selbst angerichtet haben.

**Die definitorische Null ist besser als der imputierte Median** — die
C5-Diagnose war richtig. Nur ist der Effekt mit −0,00065 klein gegen den
Schaden der C5-Merkmale insgesamt: Beide C5-Arme liegen deutlich
schlechter als der V1-Kontrollarm desselben Vertrags (−0,009763). Die
Merkmale sind das Problem, nicht ihre Imputation.

#### Was gebaut wurde

**Transformationen** (`src/ml/model_class.py`) — `log1p` für Zählwerte,
`sign(x)·log1p(|x|)` für Nettowerte, optionale Winsorisierung beim
99-%-Quantil. Die Grenzen werden **ausschließlich** im `fit()` des
Trainingsfolds gelernt; ein Test hält fest, dass ein Ausreißer im
Testbestand sie nicht verschiebt. `NaN` überlebt jede Transformation —
der Schritt **formt**, der Imputer **füllt**.

**Interaktionen** — vier, jede einzeln begründet, keine automatische
Paarkreuzung. Die zentrale Regel:

> Ist der Indikator null, ist das Produkt **exakt null** — auch bei
> fehlendem Wert. „Nicht anwendbar" ist kein fehlender Messwert,
> sondern eine bekannte Tatsache.

Genau hier trennt sich C8 von C5: Dort wurde aus der fehlenden Angabe
ein Medianwert für 85 % der Zeilen, hier wird aus ihr eine Null. Bei
Indikator **eins** und fehlendem Wert bleibt es `NaN` — das ist ein
echter Fehlwert, und dafür ist der Imputer da.

**Kalibrierung** — multiplikativ (Momentenschätzer, keine Iteration)
oder log-linear. Gelernt **nur** auf den Vorhersagen der *inneren*
Validierung. Fällt sicher zurück und nennt dabei immer einen Grund: zu
wenige Zeilen, keine Streuung, Faktor außerhalb [0,5; 2,0]. Die
Lambdagrenzen greifen **nach** der Kalibrierung erneut.

**Ein Codepfad.** `model.build_pipeline(alpha, transform)` ist die
einzige Stelle im gesamten `src/`-Baum, an der eine `Pipeline`
zusammengesetzt wird — ein Test prüft genau das per AST. Ohne
Transformation liefert sie unverändert `imputer → scaler → regressor`.
Mit Transformation steht diese **vor** dem Imputer: danach träfe sie
Medianwerte statt Messwerte.

#### Reihenfolge als Leakageschutz

Je äußerem Fold: Verträge wählen → Training **innen** teilen → Alpha auf
der inneren Validierung → Kalibrator auf **denselben** inneren
Vorhersagen → mit gewähltem Alpha auf dem **gesamten** Training
anpassen → **einmal** außen messen. Der äußere Test geht in keinen der
vorgelagerten Schritte ein; drei AST-Tests halten das fest.

#### M5 — nicht ausgewertet, nicht gescheitert

`sklearn.PoissonRegressor` kennt nur eine L2-Strafe. Elastic Net
erforderte entweder `statsmodels` (im Projekt nicht vorhanden, neue
schwere Abhängigkeit) oder eine eigene IRLS-Implementierung mit
Koordinatenabstieg — neuer, ungetesteter numerischer Code im Kern der
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
Viertel schlechter wäre 0,02059 — C7 lag zwischen 0,0215 und 0,0431 und
scheiterte genau daran.

M1 und M1c verbessern den Punktschätzer in **beiden** Folds und
scheitern an zwei Bedingungen: Das Intervall schließt die Null nicht
aus ([−0,0286; +0,0123] für M1c), und die Kalibrierung liegt 66 % über
V1.

#### Reproduzierbarkeit

Zweimal gelaufen, identischer Ergebnisfingerabdruck
`c5f9f61c…3561aa`. Ausgeklammert ist ausschließlich `runtime_seconds` —
zwei Läufe liefern nie dieselbe Wanduhrzeit, aber sie müssen dieselben
Zahlen liefern; auch das prüft ein Test.

Artefakt: `data/ml/c8_model_class_ablation_2023-2025.json` — mit
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
  multiples Testen — deshalb verlangt das Gate zusätzlich
  Richtungsgleichheit in beiden Folds.
- Der Kalibrator wird auf der inneren Validierung gelernt. Deren
  Verteilung ist die der nationalen Ligen, nicht die der CL — der Faktor
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
README. C9 führt sie an einer Stelle zusammen — und misst dabei nichts
Neues.

**Der ausgewählte Kandidat bleibt V1 `team_profile_cl` mit 16
Merkmalen.**

#### Die zentrale Regel

> Ein Merkmal gelangt **nicht** in den finalen Kandidaten, nur weil es
> technisch existiert.

Das ist keine Absichtserklärung, sondern maschinell geprüft:
`selected_columns()` bricht ab, sobald eine Familie mit einem anderen
Status als `SELECTED` hineinragt. Sechs Tests greifen jede einzelne
nicht erlaubte Statusklasse an, ein siebter den anderen Weg hinein — das
Erweitern der Variantendefinition.

#### Vier Ebenen, sauber getrennt

| Ebene | Frage | Umfang |
| --- | --- | ---: |
| 1 — roh verfügbar | Welche Quellen gibt es? | 6 Quellen |
| 2 — technisch berechenbar | Was lässt sich PIT-sicher bauen? | 130 Merkmale |
| 3 — statistisch geprüft | Was wurde gemessen? | 13 Familien |
| 4 — zugelassen | Was benutzt der Kandidat? | **16 Merkmale** |

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
niemals Namen — ein Test vergleicht beide Mengen. `validate_registry()`
bricht ab bei einer Gruppe ohne Eintrag, einem Eintrag ohne Gruppe,
einem unbekannten Status oder einem Status ohne Begründung.

#### Zwei Datensatzansichten

| | Research | Selected |
| --- | --- | --- |
| Merkmale | 102 (130 mit privaten Quellen) | **16** |
| enthält Verworfenes | ja — das ist der Zweck | nein |
| Zweck | Forschung, Ablation, Diagnostik | verbindlicher Eingang für C10 |

Beide nutzen **denselben** zentralen `build_dataset()`; `early_v2`
projiziert nur. Ein Test prüft per AST, dass es dort keinen zweiten
Datensatzbau gibt. Zeilenmenge, Zeilenidentität und Zielwerte sind in
beiden Ansichten identisch — nur die Merkmalsspalten unterscheiden sich.

Fehlt eine angeforderte Spalte, bricht die Projektion ab. Sie
stillschweigend mit `None` zu füllen hieße, eine Lücke als Messwert
auszugeben.

#### Gitignorierte Quellen fehlen sichtbar

`uefa` und `squad_history` liegen außerhalb der Versionsverwaltung. Aus
einem frischen Checkout gebaut, trüge jede ihrer Spalten in *jeder*
Zeile `None`. Sie erscheinen deshalb nur, wenn die Quelle ausdrücklich
angegeben wurde — eine Spalte, die aussieht wie ein Merkmal und keines
ist, ist die schlechtere Variante von „fehlt". Der **Kandidaten**\-
datensatz ist davon unberührt und aus jedem Checkout reproduzierbar.

#### Die geschlossene Fingerprint-Lücke

Der frühere Fingerprint erfasste die Torziele nicht durchgängig — ein
Datensatz mit vertauschten Ergebnissen hätte identisch ausgesehen. C9
trennt vier Hashes:

| Hash | Was ihn ändert |
| --- | --- |
| `target` | Tore, Ergebnis, Zeilenidentität |
| `research_dataset` / `selected_dataset` | zusätzlich Merkmalswerte, Baseline, Merkmals**menge** |
| `schema` | Gruppenzuschnitt, Status, Kandidat, Modellfamilie, Stichtagsregel — **ohne eine Datenzeile** |

Neu in der Identität: `home_id`, `away_id`, `matchday`,
`knockout_eligible`. Ohne die Team-IDs ließen sich in einer Zeile die
Mannschaften vertauschen, ohne dass sich der Hash ändert — und das wäre
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
kein Anstoßzeitpunkt — die Ligadateien führen kein verlässliches
Anstoßzeitfeld. Rest-Risiko: eine *fremde* Partie mit Anstoß vor 12:00
am Spieltag kann in Ligadurchschnitt oder Gegnerstärke eingehen. Die
beiden beteiligten Mannschaften sind ausgeschlossen — sie spielen nicht
zweimal am selben Tag.

#### Leak-Prüfung: Beweis statt Faustregel

Der erste Entwurf verbot Merkmalsnamen, die auf einen Zielwert enden —
und hätte damit `league_avg_home_goals` verworfen, den Ligadurchschnitt
über *andere* Partien. Ein Ausnahmeverzeichnis wäre die bequeme Lösung
gewesen; es würde einmal geprüft und danach geglaubt.

Stattdessen wird bei **jedem** Bau bewiesen: Gibt es (Liga, Datum)\-
Gruppen mit *verschiedenen* Zielwerten, in denen die Spalte konstant
bleibt, kann sie keine Funktion des zeileneigenen Ergebnisses sein. Im
echten Bestand: 1867 Gruppen, davon **1176 unterscheidend**. Findet sich
kein Beweis, lautet das Ergebnis `undecided` und zählt als Verstoß — was
nicht bewiesen werden kann, gilt nicht als bewiesen.

Eine gepflanzte Leckspalte wird erkannt (100 % Trefferquote, 0
unterscheidende Gruppen).

#### Manipulationstests

Ein sauberer Datensatz beweist *nicht*, dass die Zeitfilterung greift —
nur, dass sie diesmal nichts zu tun hatte. Deshalb wird zukünftige
Information absichtlich eingespeist:

- eine Partie **nach** dem Stichtag → Formmerkmale unverändert
- eine Partie **genau zum** Stichtag → zählt nicht (die Grenze ist strikt)
- ein Transfer **am Spieltag** → geht nicht ein
- ein Snapshot **nach** dem Stichtag → nicht gelesen
- ein Aggregat **im Hinspiel** → Verstoß
- ein Ausreißer **nur im Testfold** → verschiebt keine foldlokale Grenze
- doppelte `row_id` → erkannt

#### Kein unangetasteter Holdout — und das steht so im Manifest

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
bisherigen Entscheidungen noch nicht gespielt waren — also Saison
2026/27 aufwärts. Kein Umsortieren des bestehenden Bestands kann das
ersetzen.

#### Training–Runtime-Parität: verifiziert und offen

**Verifiziert:** Merkmalsnamen, Reihenfolge, Imputation, Skalierung,
keine Transformation, keine Interaktionen, Modellfamilie, Guardrails,
und dass `model.build_pipeline` die einzige Stelle ist, die eine
Pipeline zusammensetzt.

**Nicht verifizierbar — als Blocker dokumentiert:** Die Runtime führt
keinen ausdrücklichen `prediction_cutoff` mit. Beide Wege dürften in der
Praxis dasselbe liefern; nachweisen lässt es sich nicht, und eine
Vermutung gehört nicht in eine Paritätszusage. C9 baut den produktiven
Vorhersagepfad **nicht** um — das wäre ein Umbau in einem Block, der
ausdrücklich nichts aktiviert. Folgepunkt für C10–C12.

#### ML-Modus und individueller Modus bleiben getrennt

| | ML-Modus | Individueller Modus |
| --- | --- | --- |
| nutzt | ausschließlich den trainierten Kandidaten | vollständig manuelle Szenariosimulation |
| verboten | Nutzerregler, manuelle Faktoren, requestspezifische Änderung | jeder ML-Einfluss, ein ML-Gewicht |

Beide beantworten verschiedene Fragen: Ein Modell sagt, was zu erwarten
ist; eine Szenariosimulation sagt, was wäre wenn. Sie zu mischen ergibt
eine Zahl, die keine der beiden Fragen beantwortet.

**C9 baut den Reglervertrag nicht um** — das ist ein eigener Produkt-
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
git-Block — Letzterer, weil der erste Lauf das Manifest schreibt und der
zweite sonst eine ungetrackte Datei mehr zählte.

Ebenfalls ausgenommen: `data/snapshots/_runs`, die Laufberichte des
C6-Sammlers. Sie sind Betriebsprotokoll, nicht Beobachtung — ein
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


## Roadmap

- [ ] Unterpositionen (IV/AV/DM/ZOM/Flügel/Mittelstürmer), sobald eine belastbare Datenquelle vorliegt — Einstiegspunkt ist vorbereitet
- [ ] Vereins-Streudiagramme (Datengrundlage liegt bereits im Pool)
- [ ] Asymmetrischer Expertenvergleich im Radar (unterschiedlicher Wettbewerbsumfang je Spieler)
- [ ] Vollständiger heller Modus
- [ ] Mehrsprachigkeit (Deutsch/Englisch)
- [x] Sichtbare Auswahl zwischen ML-Prognose und individuellen Reglern in der CL-Einzelspielsimulation (C8B, lokal)
- [ ] Entscheidung über eine Aktivierung des ML-Ansatzes als Vorgabe — erst sinnvoll, wenn der Champions-League-Backtest die Übertragung belegt

## Lizenz

Siehe [`LICENSE`](LICENSE).
