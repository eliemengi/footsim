# V2-C22: Lokaler Release-Abschluss und Uebergabe zum manuellen Test

Arbeitsblock auf dem C21-Stand. Auftrag war, den Freigabeweg abschliessend
abzusichern, den akzeptierten C20-Kandidaten lokal ueber den bestehenden
Weg zu aktivieren, V2 in Einzelspiel und Ligaphasensimulation der lokalen
Anwendung wirksam zu machen und eine laufende Anwendung fuer den manuellen
Softwaretest zu hinterlassen. Nichts gestaged, committet, gepusht oder
deployed.

## Kurzfassung

1. **Der Freigabeweg verlangt jetzt beide Nachweise.** Neben der
   C20-Match-Messung muss die C21-Saisonfreigabe vorliegen, accepted sein
   und zu genau diesem Modellstand gehoeren: Beide Foldmodelle, auf denen
   C21 gemessen hat, muessen aus denselben Daten und derselben C20-Messung
   bitgleich wieder entstehen. Dazu fail-closed geprueft: die
   Dateiabhaengigkeiten C9, C10, C16, C17 (einschliesslich der indirekten
   C16-Abhaengigkeit des C17-Vertragsfingerabdrucks), eine vorhandene
   Bundledatei nur bei inhaltlicher Gleichheit mit dem Neubau, und auf
   Wunsch die erwartete Modell-ID (`--expect-model-id`).
2. **Lokal aktiviert.** `clm-936ecce472696ccb-ls1c4f4e1d` ist das einzige
   aktive Modell, das bisherige steht als Rueckfallziel in der Registry.
   Vorzustand gesichert, Rollback vor und nach der Umschaltung geprobt.
3. **V2 wirkt in beiden Pfaden der laufenden Anwendung.** Einzelspiel und
   Ligasimulation melden Modell-ID, Betriebsart `active` und `applied`.
   Der Regler-Modus laedt kein Modell.
4. **HTTP-Smoke-Test 25 von 25**, dazu isolierte Tests fuer den
   kontrollierten Rueckfall bei ungueltigem Bundle.
5. **Tests:** vollstaendige Suite 2 failed, 6013 passed, 126 skipped,
   91 errors, Exit 1; Failures und Errors nach Testidentitaet gleich C21,
   die 66 zusaetzlichen passed sind genau die neuen und erweiterten Tests.
6. **Grenzen unveraendert:** Entwicklungsevidenz, Restrisiko PD/SA, fuenf
   offene Zuordnungen, keine unabhaengige Bestaetigung.

---

## 1. Ausgangs- und Endzustand

| Groesse | Beginn C22 | Ende C22 |
| --- | --- | --- |
| Branch, HEAD | `main`, `4f55d80` | unveraendert |
| Gestagte Aenderungen | keine | keine |
| `git status --short` | 115 Eintraege | 119 Eintraege (vier neue Dateien, darunter dieser Bericht) |
| `git diff --stat` | 31 Dateien, 4541 Insertions, 645 Deletions | 31 Dateien, 4573 Insertions, 645 Deletions |
| Registry-Fingerabdruck | `66345556ea317311fe3681700a2d4bf55d6f71a2fa303624145efe431a4f132a` | `f79bc8566c18dfaa93e36f24df7432537f864b983e099f0d4c3dbfa2810b4b33` |
| Aktives Modell | `clm-3475c9aacef6fec9-lsa165be9c` | `clm-936ecce472696ccb-ls1c4f4e1d` |
| Wirksame Betriebsart | `off`, Gewicht 0,0 | laufende Anwendung: `active`, Gewicht 1,0 (prozessbezogen) |
| Modellverzeichnis | 6 Dateien | dieselben 6 Dateien, keine neue |
| Lokale Anwendung | nicht gestartet, Port 5000 frei | laeuft auf `http://127.0.0.1:5000` |
| Vollstaendige Suite | 2 failed, 5947 passed, 126 skipped, 91 errors | 2 failed, 6013 passed, 126 skipped, 91 errors |

Die +32 Insertions in `git diff --stat` stammen aus den beiden bereits
versionierten Dateien `run_ml.py` (Stopkriterium) und
`src/predict/cl_season_sim.py` (Modell-ID und Zuordnungen im
Saisonbericht). Alle anderen Aenderungen dieses Blocks liegen in Dateien,
die schon vor C22 unversioniert waren, oder in neuen Dateien.

**Neue und geaenderte Dateien in C22:**

| Datei | Art | Grund |
| --- | --- | --- |
| `src/ml/c16_release.py` | geaendert | Nachweis C21, Dateiabhaengigkeiten, Inhaltsvergleich vorhandener Bundles, erwartete Modell-ID; Vergleichsfunktionen hierher verlegt |
| `src/ml/c21_season_validation.py` | geaendert | `release_evidence`: Saisonfreigabe als Nachweis, Foldmodelle neu gebaut; Vertrag unveraendert |
| `src/ml/c17_bundle_contract.py` | geaendert | C16-Artefakt gegen das Repository statt gegen das Arbeitsverzeichnis |
| `src/ml/c21_release_readiness.py` | geaendert | Proben zustandsunabhaengig (Vorzustand ueber echten Rollback), kopieren C21 und Vorzustand mit |
| `src/predict/cl_season_sim.py` | geaendert | `applied`, `model_id`, `model_ids`, `teams_not_in_map`, `leagues_without_parameters` im Saisonbericht |
| `run_ml.py` | geaendert | `--expect-model-id` |
| `tests/live_registry_state.py` | neu | autorisierter Registryzustand an einer Stelle |
| `tests/test_c22_release_gate.py` | neu | 40 Tests fuer den Freigabeweg |
| `tests/test_c22_local_activation.py` | neu | 21 Tests fuer den lokalen V2-Betrieb, Regler-Trennung, Diagnose, Rueckfall |
| sieben bestehende Testdateien | geaendert | Abschnitt 7 |
| `docs/v2-c21-release-runbook.md` | geaendert | auf den C22-Stand gebracht |
| `docs/v2-c22-local-release-report.md` | neu | dieser Bericht |

Ausserhalb von Git, lokaler Zustand: Registry, gesicherter Vorzustand,
Journal und Releaseartefakt, geschrieben vom Freigabeweg bei `apply`.

---

## 2. Kandidat, Hashes und Freigabebindungen

Getrennt geprueft, bevor irgendetwas umgeschaltet wurde:

| Pruefung | Ergebnis |
| --- | --- |
| Dateihash (Bytes, CRLF) | `9f2caf3a38e3385194e48311406844204e85a97e66ee1ef9c8ca949ab1f62479`, gleich dem C21-Wert |
| Dateihash mit LF normalisiert | `5923f0d2...` (so wird er nach einem Checkout unter Linux aussehen) |
| kanonischer Inhaltshash, gesamt | `1996fb33...` |
| kanonischer Inhaltshash ohne Baumetadaten | `fbb08050...` |
| `integrity/models_sha256` gespeichert und neu berechnet | beide `6977525c...` |
| Modell-ID | `clm-936ecce472696ccb-ls1c4f4e1d` |
| Loader (`persist.load_bundle`), C17-Vertragspruefung | angenommen, ohne Befund |
| Neubau durch den Freigabeweg gegen gespeicherte Datei | abweichend nur `created_at`, `provenance/git_status/porcelain`, `provenance/git_status/untracked`; alle modellrelevanten Felder gleich |
| Stufe, Klasse | `approved`, `accepted_development_evidence` |

Der Dateihash eines Neubaus unterscheidet sich, weil das Bundle Zeitpunkt
und Arbeitsbaum seines Baus festhaelt. Das wurde nicht pauschal als
harmlos gewertet: Die drei Felder sind einzeln benannt, und jede andere
Abweichung blockiert den Freigabeweg jetzt selbst (Abschnitt 3).

| Bindung im Bundle | gegen den Code jetzt |
| --- | --- |
| C9-Schema, C13, C14, C15, C16, C16-Modellschema | gleich |
| C17-Vertrag `03763962...` | gleich, und gleich dem eingefrorenen C17-Artefakt |
| C20-Kartenvertrag `16a24b04...` | gleich; Karte 146 Vereine bis Saison 2026 |
| `c16_result_fingerprint` | gleich dem Ergebnisfingerabdruck der C20-Messung `721fc0d8...`, Urteil accepted |
| `evaluation_sha256` | gleich dem Inhaltshash der C20-Messung |
| C21-Saisonfreigabe | accepted, Vertrag `5b687853...`, Foldmodelle `clm-be8db299253605dc-ls085040dc` und `clm-664cc4f2959fea76-ls0743a761` aus denselben Daten bitgleich wieder gebaut |

Keine unerklaerte Abweichung. Aktiviert wurde ausschliesslich dieser
Kandidat.

---

## 3. Der Freigabeweg, abschliessend abgesichert

Bis C21 las `c16_release.release()` nur die C20-Match-Messung. Die
C21-Saisonfreigabe und die Dateiabhaengigkeiten standen im Runbook. Jetzt
prueft der bestehende Release-Einstieg selbst, in dieser Reihenfolge, und
jede Pruefung verweigert ohne Schreibvorgang:

| Pruefung | wo | faellt auf bei |
| --- | --- | --- |
| C20-Messung accepted und an den Kartenvertrag gebunden | bestehend | unveraendert |
| Dateiabhaengigkeiten | `c16_release.dependency_findings` | fehlendem C9-Manifest, C10-Artefakt, C16-Messartefakt oder C17-Vertragsartefakt; C17-Fingerabdruck ungleich dem eingefrorenen (fehlendes oder veraendertes C16-Artefakt) |
| C21-Saisonfreigabe | `c21_season_validation.release_evidence` | fehlendem oder unlesbarem Vertrag oder Ergebnis; Vertrag ungleich Code oder nicht vor dem Ergebnis eingefroren; Ergebnis nicht an den Vertrag gebunden, nicht accepted, eine der Bedingungen S1 bis S6 verletzt, technische Befunde; anderem Kartenvertrag als C20; Foldmodell nicht aktiv gemessen, anderer Trainingsstand, oder Neubau mit anderer ID |
| erwartete Modell-ID | `release(expected_model_id=...)`, CLI `--expect-model-id` | Neubau mit anderer ID |
| vorhandene Bundledatei | `c16_release.bundle_mismatch` | Datei gleichen Namens, die in einem modellrelevanten Feld abweicht oder unlesbar ist (`blocked_by_bundle_mismatch`) |

Keine zweite Registry, keine parallele Freigabelogik: Alle Pruefungen
laufen vor dem unveraenderten `apply_release`. Kein alter Vertrag wurde
umgeschrieben; der eingefrorene C21-Vertrag und sein Fingerabdruck sind
unveraendert, `release_evidence` ist nicht Teil von `contract()`. Keine
Schutzschranke entfernt.

**Zwei Befunde, behoben:**

- `c17_bundle_contract` las das C16-Artefakt relativ zum
  Arbeitsverzeichnis. Aus einem anderen Verzeichnis entstand still ein
  anderer C17-Fingerabdruck. Jetzt gegen das Repository aufgeloest; Inhalt
  und Fingerabdruck des Vertrags unveraendert.
- Eine vorhandene Bundledatei wurde bis C21 nur am Namen erkannt und
  unbesehen registriert. Die Modell-ID deckt die Vertragsbindungen nicht
  ab; eine Datei gleichen Namens mit anderer Bindung waere durchgegangen.

Die Saisonsimulation meldet seit C22 zusaetzlich `applied`, `model_id`,
`model_ids` sowie im Ligastufenblock `teams_not_in_map` und
`leagues_without_parameters`. Bis C21 nannte sie weder das Modell noch die
Vereine ohne Zuordnung; beides war fuer die geforderte HTTP-Pruefung
noetig. Rein additiv, keine Rechenaenderung.

---

## 4. Lokale Aktivierung mit gesichertem Rueckweg

**Sicherung vor der Umschaltung**, ausserhalb des Repositorys im
Benutzerverzeichnis unter `FootSim-local-backups/c22-pre-activation-20260913T202434Z/`:
Registry, gesicherter Vorzustand, Journal, bisheriges Releaseartefakt und
alle sechs Modellbundles, jeweils mit SHA-256 im Manifest, dazu die
wirksame Betriebsart (`off`, Gewicht 0,0; keiner der beiden Schalter in der
Prozessumgebung gesetzt).

**Vor der Umschaltung, gegen den aktuellen Code:**

| Schritt | Ergebnis |
| --- | --- |
| Tests der Freigabe (141, darunter isolierter Trockenlauf und Aktivierung mit Rollback) | 141 passed, Exit 0 |
| isolierter Trockenlauf | `dry_run_ok`, vorhandene Datei inhaltsgleich, Saisonfreigabe gebunden |
| isolierte Aktivierung | `applied`; Neubau ohne vorhandene Datei weicht nur in Baumetadaten ab |
| Laufzeit danach | `approach=ml`: active, applied, Kandidat, zweite Stufe applied; ohne Ansatz: off |
| isolierter Rollback | `rolled_back`, wieder `clm-3475c9aacef6fec9-lsa165be9c`, Laufzeit wendet es an |
| echter CLI-Trockenlauf mit `--expect-model-id` | `dry_run_ok`, Exit 0, nichts geschrieben |

**Die Umschaltung:** `python run_ml.py --release-c16 apply --expect-model-id clm-936ecce472696ccb-ls1c4f4e1d`,
Exit 0, `Status: applied`. Protokoll: Dateiabhaengigkeiten vollstaendig,
C21-Saisonfreigabe gebunden, Bundle inhaltsgleich, Vorpruefung bestanden,
Vorzustand gesichert, `candidate -> shadow -> active`, Registry atomar
geschrieben und von der Platte erneut validiert, Releaseartefakt
geschrieben.

| Registry | vorher | nachher |
| --- | --- | --- |
| Fingerabdruck | `66345556...` | `f79bc856...` |
| `clm-8a4eda90a08395cc` | candidate, rejected | unveraendert |
| `clm-3475c9aacef6fec9-lsa165be9c` | active, accepted | rollback, accepted, Rueckfallziel |
| `clm-936ecce472696ccb-ls1c4f4e1d` | nicht registriert | active, accepted |
| aktive Modelle | 1 | 1 |
| Eintrag des Kandidaten | - | Bundlehash `9f2caf3a...`, Messung C20, C10-Fingerabdruck `75838f28...`, Freigabe fuer `active` verifiziert |

`--registry validate`: gueltig. `--release-c16 recover`: der letzte
Vorgang war vollstaendig. Der gesicherte Vorzustand traegt `66345556...`,
ein Rollback-Trockenlauf ist `dry_run_ok`. Nach der Aktivierung haben die
Freigabetests den Rollback aus dem aktivierten Zustand erneut in einer
Kopie ausgefuehrt. Keine Datei geloescht; drei bestehende Laufzeitdateien
(Vorzustand, Journal, Releaseartefakt) hat der Freigabeweg regulaer
ersetzt, ihre vorherigen Fassungen liegen in der Sicherung.

**Rueckweg lokal:** `python run_ml.py --release-c16 rollback` stellt
`66345556...` wieder her; Anwendung ohne die beiden Prozessvariablen neu
starten.

---

## 5. Wirksame Betriebsart

| Pfad | Steuerung | lokal jetzt |
| --- | --- | --- |
| Einzelspiel, `approach=ml` (Standard der Oberflaeche) | Request | Kandidat, applied |
| Einzelspiel ohne `approach` | Serverbetriebsart | `active`, Gewicht 1,0 |
| Ligasimulation (`/api/cl-season-sim`) | nur Serverbetriebsart | `active`, Gewicht 1,0 |
| Eigene Einschaetzung (`approach=custom`) | Request | `off`, kein Modell geladen |

Gesetzt ueber prozessbezogene Umgebungsvariablen beim Start
(`FOOTSIM_ML_MODE=active`, `FOOTSIM_ML_WEIGHT=1.0`). `load_dotenv()`
ueberschreibt vorhandene Prozessvariablen nicht; die `.env` wurde weder
geoeffnet noch geaendert. Beim Start und in jedem Testlauf laedt die
Anwendung sie selbst (`load_dotenv()` in `app.py` und `src/api/*`); die
Sicherung hat die beiden ML-Schalter ueber genau diesen Weg gelesen und nur
diese beiden festgehalten.

**Nicht dauerhaft.** Die Einstellung gilt fuer diesen Prozess. Nach einem
Neustart des Rechners oder der Anwendung ohne die beiden Variablen gilt
wieder `off`: Die Registry bleibt beim Kandidaten, Einzelspiele mit V2-
Prognose wenden ihn weiter an, die Ligasimulation rechnet dann V0. Neustart
mit V2, im Projektverzeichnis in PowerShell:

```powershell
$env:FOOTSIM_ML_MODE = "active"; $env:FOOTSIM_ML_WEIGHT = "1.0"; python app.py
```

Gilt fuer den geprueften Anwendungsbereich: Champions-League-Ligaphase.
V2 ist nicht fuer andere Wettbewerbe validiert; die nationalen Ligen
kennen weiterhin kein ML.

---

## 6. HTTP-Smoke-Test gegen die laufende Anwendung

Echte HTTP-Anfragen an `http://127.0.0.1:5000`, CSRF-Token aus der Seite
wie im Frontend, Sitzungscookie. Keine Tokens im Bericht. Ergebnis
**25 von 25**.

| Pruefung | Antwort |
| --- | --- |
| Startseite, CSRF-Token | 200, Token vorhanden |
| Einzelspiel Bayern gegen Arsenal, `approach=ml`, Saison 2026 | 200; `mode active`, `applied true`, `model_id clm-936ecce472696ccb-ls1c4f4e1d`, zweite Stufe `applied` (BL1, PL); Lambdas V0 2,2182 / 1,3588, V2 1,8360 / 1,4361; 45,8 / 23,4 / 30,8 % |
| dasselbe ohne `approach` | `mode active`, `applied true`, Kandidat, `applied_approach environment_default` |
| Eigene Einschaetzung mit Faktoren | `mode off`, `applied false`, `model_id null`, `ml_off` |
| `approach=custom` mit `ml_weight` | 400 |
| `approach=ml` mit `factors` | 400 |
| `approach=ml` mit `ml_weight` | 400 |
| unbekannter Ansatz | 400 |
| `approach=custom` plus fremde Felder `ml_mode`, `FOOTSIM_ML_MODE` | bleibt `off`, kein Modell |
| Ligasimulation 2026/27, 5000 Laeufe, mit Stoerparametern `approach=custom&ml_weight=0&ml_mode=off` | 200; Parameter ignoriert: `mode active`, `applied true`, `model_id` Kandidat, `model_ids` genau der Kandidat, ML auf 126 von 126 offenen Partien, Gewicht 1,0 |
| Paarungen | 144 Partien, 36 Vereine, Abdeckung ok, 18 fest plus 126 simuliert |
| bekannte Ergebnisse | 18 beendete Partien (Spieltag 1) im Plan; Punkte und Spiele aller 36 Vereine gleich der Nachrechnung aus dem Plan |
| Qualifikationswahrscheinlichkeiten | je Verein 100 %; Summen 799,9 / 1600,2 / 1200,0 (Soll 800 / 1600 / 1200) |
| Ligastufe im Saisonbericht | 93 von 126 mit vollen Parametern, 0 Liga ohne Parameter, 33 ohne Zuordnung; `teams_not_in_map` = 613, 1899, 2016, 5720, 10233 |
| Einzelspiel je offenem Verein gegen Bayern | alle fuenf: `team_not_in_map`, zweite Stufe nicht angewandt, `home_league null`, `away_league BL1`, Basismodell angewandt |

Die Anwendung hat den Spielplan 2026/27 dabei selbst beim Anbieter
aufgefrischt (football-data.org, abgerufen 20:30:58 UTC), wie im
Normalbetrieb; keine erfundenen Werte, keine neuen Daten gekauft.

Hinweis zur Anzeige: `ml.status` lautet auch im aktiven Betrieb
`shadow_prediction`. Das ist der Status der Modellvorhersage selbst;
massgeblich fuer die Wirkung ist `applied`.

**Meine eigene Pruefannahme war einmal falsch:** Der erste Lauf verlangte
fuer die fuenf Vereine die Felder `home_status` und `away_status`, die der
Antwortvertrag des Einzelspiels (`cl_match_sim._liga_stufe_kurz`) bewusst
nicht fuehrt. Er traegt Zustand, Anwendung und die beiden Ligen; die
fehlende Seite erkennt man an der leeren Liga. Die Pruefung wurde auf
diesen Vertrag gestellt, nicht der Code auf die Pruefung.

**Isoliert, nicht gegen die laufende Anwendung** (`tests/test_c22_local_activation.py`):
Ein ungueltiges Bundle, einmal mit falschem Hash, einmal als
unlesbares JSON, faellt ueber den Registrygate kontrolliert zurueck: HTTP
200, `applied false`, ein Rueckfallgrund, finale Lambdas gleich den
V0-Lambdas, alle Nutzerzahlen gleich einem Lauf mit `off`. Der Regler-Modus
ruft `inference.load_model` auch bei Serverbetriebsart `active` nicht auf.

---

## 7. Tests

| Lauf | Ergebnis | Exit |
| --- | --- | ---: |
| neue Gate-Tests `test_c22_release_gate.py` | 40 passed | 0 |
| neue Aktivierungstests `test_c22_local_activation.py` (vor dem Ratenlimit-Fix) | 21 passed | 0 |
| vor der Umschaltung: Freigabe, Gate, C19, C20, C21, C16-Freigabeweg | 141 passed (10:19) | 0 |
| nach der Umschaltung: 44 ML- und CL-Dateien (C10 bis C22, `test_ml_*`, `test_cl_*`, PIT, E2E-Cache) | 6 failed, 2376 passed, 38 skipped; alle sechs aktivierungsbedingt, Abschnitt unten | 1 |
| dieselben sechs Stellen nach Korrektur, mit C19, C22 | 195 passed | 0 |
| vollstaendige Suite, erster Lauf | 2 failed, 6011 passed, 126 skipped, 93 errors (49:47) | 1 |
| Ratenlimit-Fix, betroffene Dateien zusammen | 131 passed | 0 |
| **vollstaendige Suite, final** | **2 failed, 6013 passed, 126 skipped, 91 errors** (55:08) | **1** |

Exit-Codes ohne Pipe erfasst, jede Suite regulaer zu Ende gelaufen.

| Vergleich final mit C21 | |
| --- | --- |
| passed | +66: 40 und 21 neue Tests, +3 in `test_c21_release_readiness.py`, +1 in `test_c20_candidate_parity.py`, +1 in `test_c19_candidate_registration.py` |
| failed | identisch: `test_go1_season_and_pit.py::TestSaisonWeitergabe::test_provider_ausfall_bleibt_neutral`, `test_test_isolation.py::TestReihenfolgeSpieltKeineRolle::test_umgekehrte_reihenfolge_aendert_nichts` |
| errors | 91, testidentitaetsgleich zu C21, ausschliesslich Datenbank- und Authentifizierungsinfrastruktur (PostgreSQL auf Port 5432 nicht erreichbar) |
| skipped | 126, unveraendert |

**Die zwei zusaetzlichen Errors des ersten vollstaendigen Laufs** waren
`test_cl_custom_api.py::TestFreigabestufeAmEndpunkt::test_die_antwort_verraet_keine_modellinterna`
und `::test_ein_defektes_modell_fuehrt_auf_v0`: Die Startseite antwortete
mit 429. Ursache war dieser Block: Das Ratenlimit zaehlt je Route und IP im
Speicher des Testprozesses (100 je Stunde), jeder CSRF-Aufbau laedt die
Startseite, und die neuen Tests verbrauchten das gemeinsame Budget. Behoben
in der Fixture der neuen Datei nach der Konvention aus
`test_browser_smoke.py` (Limit fuer die Dauer des Tests aus, per
`monkeypatch` zurueckgesetzt). Die Tests, die das Limit selbst pruefen,
sind unberuehrt; im finalen Lauf sind beide Errors weg.

Keine Testartefakte im echten Modellverzeichnis: vor und nach jedem Lauf
dieselben sechs Dateien.

### Geaenderte bestehende Tests und warum

Sieben bestehende Testdateien sagten "die echte Registry steht im Zustand
von C19/C20" oder "nur ein Modell traegt je eine Freigabe". Nach der
ausdruecklich freigegebenen Aktivierung waeren diese Aussagen falsch, ohne
dass etwas schiefging. Keine wurde abgeschwaecht oder uebersprungen:

| Datei | vorher | jetzt |
| --- | --- | --- |
| neu `tests/live_registry_state.py` | fuenf verstreute Pins auf `66345556...` | EIN Ort fuer den autorisierten Zustand, exakt gepinnt: aktiv der Kandidat, `f79bc856...`; der Vorzustand ebenfalls benannt |
| `test_c19_candidate_registration.py` | aktiv bleibt das 63-Vereine-Modell | aktiv ist das autorisierte Modell mit 146 Vereinen; neu: der C19-Kandidat ist weder aktiv noch registriert |
| `test_c20_candidate_parity.py` | Registrierungstrockenlauf gegen die Live-Registry | gegen den gesicherten Vorzustand mit gepinntem Fingerabdruck (dieselbe Registry, gegen die C20 prueft); neu: der Kandidat ist regulaer aktiv, Freigabe verifiziert, zweite Registrierung abgewiesen |
| `test_c21_release_readiness.py` | Proben gegen die Live-Kopie, "Kandidat nicht registriert" | Proben stellen zuerst den Vorzustand her; zusaetzlich Saisonfreigabe gebunden, vorhandene Datei inhaltsgleich, Neubau nur Baumetadaten |
| `test_c21_season_validation.py` | aktiv nach Isolation `clm-3475...` | aktiv nach Isolation das autorisierte Modell |
| `test_c16_damped_league_strength.py` | Kopie ohne C21-Artefakte | Kopie ueber `copy_release_state`, sonst verweigert der neue Nachweis zu Recht |
| `test_c11_model_registry.py` (2 Tests) | genau ein Modell mit Freigabe, genau eines accepted | genau EIN aktives Modell mit gueltiger Freigabe; jede weitere Freigabe und jedes weitere accepted nur beim eingetragenen Rueckfallziel auf `rollback`, dessen Freigabe ebenfalls traegt; `rollback` bestimmt keine Nutzerantwort |
| `test_c18_league_stage_diagnostics.py` (1 Test) | Vereins-ID als Teilzeichenkette der Darstellung | an den Werten geprueft; mit dem neuen Modell ist der erste Verein die ID 1, und "1" steht in jeder Gleitkommazahl |

---

## 8. Sicherheitspruefungen

| Pruefung | Ergebnis |
| --- | --- |
| `git diff --check` | Exit 0 |
| `git status --short` | 119 Eintraege |
| `git diff --stat` | 31 Dateien, 4573 Insertions, 645 Deletions |
| `git diff --cached --stat` | leer |
| Secret-Scan ueber 118 geaenderte und neue Dateien | keine Treffer; README nur mit den dokumentierten Platzhaltern |
| Registry | `--registry validate` gueltig, genau ein aktives Modell, Freigabe verifiziert, `recover` complete |
| Bundle | `persist.load_bundle` angenommen, C17-Vertragspruefung ohne Befund, `dependency_findings` leer |
| HTTP-Smoke nach der finalen Suite | erneut 25 von 25 |
| U+2014 in README und allen neuen und geaenderten Dateien | 0 |
| absolute lokale Pfade in persistierten Artefakten | keine; einziger Treffer ist die vorhandene Negativpruefung in `test_c11_model_registry.py` |
| `.env` | nicht gezielt geoeffnet, nicht veraendert; indirekt geladen durch die Anwendung beim Start, in jedem Testlauf und beim Sichern der Betriebsart (Abschnitt 5) |
| Zugangsdaten, Tokens | nicht ausgegeben; das CSRF-Token der Smoke-Tests steht nirgends im Bericht |

Nichts gestaged, committet oder gepusht, der VPS nicht beruehrt. Keine
Datei geloescht; die Sicherung liegt ausserhalb des Repositorys.

---

## 9. Commit-Umfang fuer die spaetere, gesondert freigegebene Uebergabe

Nichts davon ist ausgefuehrt. Die Liste ist ein Vorschlag; entschieden
wird bei der Freigabe.

### Anwendungscode

Geaendert, versioniert: `README.md`, `run_ml.py`,
`src/data/snapshot_archive.py`, `src/features/pit_profiles.py`,
`src/ml/blend.py`, `src/ml/cl_dataset.py`, `src/ml/dataset.py`,
`src/ml/feature_groups.py`, `src/ml/inference.py`, `src/ml/persist.py`,
`src/ml/runtime.py`, `src/predict/cl_custom_factors.py`,
`src/predict/cl_match_sim.py`, `src/predict/cl_season_sim.py`,
`src/predict/league_match_sim.py`, `static/i18n/de.json`,
`static/i18n/en.json`, `static/script.js`, `templates/index.html`.

Neu: `src/data/national_sources.py`, `src/features/league_strength.py`,
`src/features/prediction_cutoff.py`, `src/features/team_identity.py`,
`src/ml/c10_contract.py`, `src/ml/c12_evaluation.py`,
`src/ml/c13_contract.py`, `src/ml/c14_reevaluation.py`,
`src/ml/c15_league_strength.py`, `src/ml/c15_release.py`,
`src/ml/c16_damped_league_strength.py`, `src/ml/c16_release.py`,
`src/ml/c17_bundle_contract.py`, `src/ml/c19_league_map.py`,
`src/ml/c20_temporal_map.py`, `src/ml/c21_release_readiness.py`,
`src/ml/c21_season_validation.py`, `src/ml/model_registry.py`.

### Tests und Dokumentation

Geaendert: die zwoelf bereits versionierten Testdateien aus `git status`.
Neu: alle `tests/test_c1*.py`, `tests/test_c2*.py`,
`tests/live_registry_state.py`, `tests/fixtures/fl1_frozen_season_306.json`,
`docs/v2-c15-*` bis `docs/v2-c22-*`.

### Pflichtartefakte des Freigabewegs (fail-closed geprueft)

| Datei | Grund |
| --- | --- |
| `data/ml/c10_prediction_cutoff_contract_2023-2025.json` | Registryeintrag und Freigabezeichen |
| `data/ml/c16_damped_league_strength_evaluation.json` | Ergebnisfingerabdruck im C17-Vertrag |
| `data/ml/c17_multistage_bundle_release_contract.json` | eingefrorener C17-Fingerabdruck |
| `data/ml/c20_damped_league_strength_evaluation.json` | Match-Nachweis |
| `data/ml/c21_season_validation_contract.json` | Saisonvertrag |
| `data/ml/c21_season_validation.json` | Saisonnachweis |
| `data/ml/models/clm-936ecce472696ccb-ls1c4f4e1d.json` | der Kandidat; der Freigabeweg prueft ihn gegen seinen Neubau |

Das C9-Manifest ist bereits versioniert.

### Beleg- und Testartefakte (empfohlen)

Die eingefrorenen Vertraege und Urteile der Bloecke C11 bis C20. Mehrere
Testdateien lesen sie ueber ihre `ARTIFACT_PATH`- und `CONTRACT_PATH`-
Konstanten; ohne sie ueberspringen oder scheitern Teile der Suite auf einem
frischen Checkout: `data/ml/c11_registry_release_gate_contract.json`,
`data/ml/c12_final_evaluation_2023-2025.json`,
`data/ml/c13_national_profile_contract_2023-2025.json`,
`data/ml/c14_reevaluation_2023-2025.json`,
`data/ml/c14_reevaluation_contract_2023-2025.json`,
`data/ml/c15_league_strength_contract_2023-2025.json`,
`data/ml/c15_league_strength_evaluation_2023-2025.json`,
`data/ml/c16_damped_league_strength_contract.json`,
`data/ml/c19_league_map_contract.json`,
`data/ml/c20_temporal_map_contract.json`, `data/ml/c20_runtime_parity.json`,
`data/ml/c20_pd_diagnosis.json`, `data/ml/cl_shadow_backtest_2023-2025.json`,
dazu zwei Vergleichsbundles, auf die Tests namentlich zeigen:
`clm-3475c9aacef6fec9-lsa165be9c.json` (bisher aktiv, lokal Rueckfallziel)
und `clm-3475c9aacef6fec9-ls9cb9e0f6.json` (C19-Kandidat).

Optional, reine Messausgaben frueherer Ablationen, von keinem Test
gelesen: `data/ml/ablation_2023-2025.json`,
`data/ml/ablation_diagnostics_2023-2025.json`.

### Ausgeschlossen

| Datei | Grund |
| --- | --- |
| `data/ml/model_registry.json`, `data/ml/c15_registry_snapshot.json`, `data/ml/c15_release_journal.json`, `data/ml/c16_damped_league_strength_release.json` | Laufzeitzustand dieses Rechners; der VPS erzeugt seinen eigenen |
| `data/ml/models/clm-3475c9aacef6fec9-ls34fd7f2d.json`, `.../clm-3475c9aacef6fec9-ls1c4f4e1d.json` | Streu-Bundles aus Entwicklungslaeufen, nirgends referenziert |
| `data/ml/dataset_2023-2025.json` (16 MB), `data/ml/dataset_with_cl_2023-2025.json` (19 MB), `data/ml/shadow_eval_2023-2025.json`, `data/ml/c19_runtime_parity.json` | erzeugte Daten beziehungsweise nicht referenziert; Tests ueberspringen sichtbar, wenn der Datensatz fehlt |
| `data/backtests/`, `data/snapshots/`, `data/cache/`, `data/go3_backtest_result.json`, `data/go45_backtest_result.json`, `data/percentiles/` | Laufzeit- oder Experimentdaten |
| `.env`, lokale Sicherungen | Zugangsdaten beziehungsweise nicht fuer Git |

### VPS

`docs/v2-c21-release-runbook.md` ist auf den C22-Stand gebracht: Pruefung
lokaler VPS-Aenderungen und Divergenz, Sicherung von Modellzustand,
Dienstkonfiguration und Datenbank, vollstaendige Artefaktliste,
Linux-Trockenlauf mit `--expect-model-id` und Stopkriterien, Code-,
Modell- und Betriebsartumschaltung (Betriebsart als systemd-Drop-in, damit
die Saisontabelle nicht bei V0 bleibt), HTTP-Smoke-Test fuer Einzelspiel
und Saisontabelle, Rueckweg fuer Betriebsart, Registry und Code. Kein alter
VPS-Wert vorausgesetzt; benoetigte Eingaben: Host und SSH-Zugang,
Dienstname, Pfad, URL, Datenbanksicherung, vorhandene Registry,
Python-Version.

---

## 10. Verbleibende Grenzen

- **Entwicklungsevidenz.** C20 und C21 messen auf denselben Saisons, auf
  denen die Modellform entstand. Keine unabhaengige Bestaetigung; frueheste
  Moeglichkeit ist die Ligaphase 2026/27 mit vorab eingefrorenem Vertrag,
  auswertbar nach dem letzten Spieltag Ende Januar 2027.
- **Korrektur zu C21:** Dort stand, die Ligaphase 2026/27 beginne "in
  wenigen Tagen". Der Spielplan der Anwendung zeigt 18 beendete Partien
  seit dem 8. September 2026. Eine prospektive Saisonstartprognose ist
  damit nicht mehr moeglich; eine rueckblickende, unabhaengige Messung
  bleibt es.
- **PD und SA.** Auf Tabellenebene im Mittel leicht schlechter als V0
  (+0,0044 und +0,0129 Zonen-RPS, je 9 Vereinssaisons), dieselbe Richtung
  wie die C20-Segmente. Nicht gegatet, weil unter der Mindestgroesse.
- **Fuenf offene Zuordnungen.** Fenerbahce, AEK, LASK, Viking und Sabah
  bleiben ohne zweite Stufe; in der laufenden Ligaphase betrifft das 33 von
  126 offenen Partien. Kein belegbarer Crosswalk.
- **Rueckfallziel.** Das Rueckfallziel ist das bisherige Modell mit der
  63-Vereine-Karte, das C20 als unvollstaendig beschrieben hat. Ein
  Rollback ist technisch gueltig, faellt fachlich aber auf diesen Stand
  zurueck.
- **Betriebsart lokal nicht dauerhaft** (Abschnitt 5).
- **Browsertests** (Playwright, eigener Lauf mit `--e2e`) liefen nicht;
  sie bauen eine Testdatenbank neu auf. Die statische Pruefung
  `test_js_syntax` lief in der Suite mit.

---

## 11. Ist die lokale Implementierung abgeschlossen?

> Ist die lokale Implementierung jetzt vollstaendig abgeschlossen, sodass
> vor meinem manuellen Test kein weiterer zwingender GO-Implementierungsblock
> offen ist?

**Ja.** Aus eigener Pruefung:

- Der Freigabeweg verlangt beide Nachweise und seine Dateien fail-closed
  und ist mit 40 eigenen Tests abgesichert.
- Der akzeptierte Kandidat ist lokal ueber diesen Weg aktiv, genau ein
  aktives Modell, Vorzustand gesichert, Rollback geprobt.
- V2 wirkt in der laufenden Anwendung in Einzelspiel und Ligasimulation,
  die HTTP-Antworten nennen Modell-ID, Betriebsart und `applied`; der
  Regler-Modus bleibt getrennt; die fuenf offenen Zuordnungen sind
  ausgewiesen; der Rueckfall bei ungueltigem Bundle ist isoliert belegt.
- Die vollstaendige Suite zeigt keine neue Failure und keinen neuen Error
  gegenueber C21.

Was noch aussteht, ist kein Implementierungsblock: dein manueller
Softwaretest, danach die gesondert freizugebenden Schritte Commit, Push und
VPS nach dem Runbook. Ein weiterer Block wird erst noetig, wenn der
manuelle Test einen Fehler findet oder der Linux-Trockenlauf auf dem VPS
eine andere Modell-ID baut. Unabhaengig davon bleiben zeitgebunden bzw.
datenabhaengig: die Bestaetigung auf der Ligaphase 2026/27 (ab Ende
Januar 2027) und ein Crosswalk fuer die fuenf Vereine, sobald eine
belegbare Quelle existiert. Die zwei alten Failures und die 91
Datenbank-Errors der Suite bestehen unveraendert seit mindestens C19 und
haengen an fehlender Testinfrastruktur, nicht an diesem Stand.

---

## Status

`READY FOR ELIE'S MANUAL SOFTWARE TEST`
