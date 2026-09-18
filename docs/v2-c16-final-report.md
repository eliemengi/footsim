# V2-C16 Abschlussbericht: Gedämpfte Ligastärke und Freigabeentscheidung

---

## A. Ausgangslage

| Größe | Wert |
| --- | --- |
| Branch | `main` |
| HEAD | `4f55d80cb47254a3704589dfba3fd5dd78fa937f` (unverändert) |
| Git-Status zu Beginn | 15 modifizierte, 36 unversionierte Dateien, nichts gestaged |
| Aktives Modell vor C16 | **keines** (`no_active_model`) |
| Registry vor C16 | ein Eintrag `clm-8a4eda90a08395cc`, Stage `candidate`, Evaluation `rejected` |
| Testbaseline nach C15 | `2 failed, 5533 passed, 128 skipped, 91 errors` |

### Fingerprint-Kette

| Vertrag | Fingerprint |
| --- | --- |
| C9 Schema | `475b9be82c21c7ea977d71db1a714e3bc37fd4be2336897285730bc116694aa5` |
| C10 Cutoff | 12:00 UTC, strikt kleiner |
| C11 Vertrag (zustandsfrei) | `66d023b9c205cd9767812961dd9eeaa6a8008fef5d1283f46f211169875c71b4` |
| C11 Zustand | `314540e5ba33d4c30f55ca895ba904ded7dd6e723fd1eb54420592ad0ce518a5` |
| C13 Vertrag | `e51f5f908e833df8cd125713ddcee3b182451e1fad4467f26093699df4695a57` |
| C13 Zustand | `75315a0c4858c2123e68039bf987f25dc87b4b55c6341a209a30c04b82189933` |
| C14 Vertrag | `704c9ade45f3ca1c9fde49bf1e0812f1c903f7ebc71ee07554bd9d4883dba835` |
| C14 Ergebnis | `9544301a05922388b426ef855d504445754c3115eb713fe821ff612570330343` |
| C15 Vertrag | `c1a155fbf48c07f0e3f27bac0110f8032933c98be82e57c406307b6cde8f14b8` |
| C15 Modellschema | `0bbb0f161cc259fe439daef32163c89c40a88af2628ce9c7c36e820d234099c2` |
| **C16 Vertrag** | **`f6ce4b94e097015744d7a686314dcd6db3ce14359552a6b5864c773d24c5eb40`** |
| **C16 Modellschema** | **`e429f461d06e7aa4cced157d51b1509494f7f89ed1d3735e5a4c192d5a7fcee6`** |
| **C16 Ergebnis** | **`4f8c7d05a130cfda97052e10c96e26c0a81b189bb84d55c6b8f0d92e2995420a`** |

### Bestätigte C15-Ergebnisse und der einzige Blocker

C15 erreichte gegen V0 einen ΔLog Loss von `−0,095118` mit dem
Intervall `[−0,131169; −0,057305]`, beide Folds negativ
(`−0,066131` und `−0,125147`). Zehn von elf Gates waren erfüllt.

Der einzige Blocker: `no_severe_segment_damage`, verursacht durch
`home_origin_league:PD` mit n=36 und `+0,01186` gegen eine
eingefrorene Grenze von `0,01000`. Abstand zum Gate: `+0,00186`.

---

## B. Implementierung

### `src/features/league_strength.py` (geändert, 464 Zeilen)

**Zweck:** die Ligastärke-Komponente, jetzt mit globaler Dämpfung.

| Element | vorher | nachher |
| --- | --- | --- |
| `LeagueStrength.__init__` | `(attack, defence, diagnose)` | zusätzlich `gamma=1.0` |
| `LeagueStrength.factors` | `exp(a + d)` | `exp(gamma * (a + d))` |
| `LeagueStrength.with_gamma` | existierte nicht | neue Instanz mit anderer Dämpfung |
| `LeagueStrength.summary` | ohne Gamma | Gamma enthalten |
| `GAMMA_GRID` | existierte nicht | `(0.25, 0.50, 0.75, 1.00)` |
| `GAMMA_TOLERANCE` | existierte nicht | `1e-6` |
| `select_gamma` | existierte nicht | zeitliche innere Auswahl |

**Sicherheitswirkung:** Der Vorgabewert `gamma=1.0` ist exakt die
C15-Formel. Ein C15-Objekt rechnet damit unverändert; der C15-Vertrag
und sein Modellschema bleiben bitgleich.

### `src/ml/c16_damped_league_strength.py` (neu, 1116 Zeilen)

Vertrag, Messstrecke für vier Kandidaten, Entscheidung, Artefakt.

Zentrale Funktionen: `model_schema()`, `schema_fingerprint()`,
`evaluation_contract()`, `contract_fingerprint()`,
`assert_contract_matches()`, `write_contract()`, `evaluate_fold()`,
`run_measurement()`, `decide()`, `result_fingerprint()`,
`build_artifact()`, `write_artifact()`, `REASON_TEXTS`.

### `src/ml/c16_release.py` (neu, 612 Zeilen)

Bundlebau mit zweiter Stufe, Vorprüfung, transaktionale Freigabe,
Rollback und Recovery über den in V2-C15 gebauten Weg.

Zentrale Funktionen: `build_final_bundle()`, `write_bundle()`,
`preflight()`, `apply_release()`, `rollback()`, `recover()`,
`release()`.

### `src/ml/inference.py` (geändert, +71 Zeilen)

Neue Funktion `_ligastaerke_anwenden()` und ein Aufruf in
`shadow_lambdas()` nach den Stufe-1-Faktoren.

**Vorheriges Verhalten:** Es gab nur die nationale Basisstufe.
**Neues Verhalten:** Trägt das Bundle einen `league_strength`-Block,
werden die Korrekturfaktoren mit `exp(gamma * (a + d))` multipliziert.
Trägt es keinen, rechnet die Funktion Bit für Bit wie zuvor.

**Sicherheitswirkung:** Die zweite Stufe wird über das Bundle geführt,
nicht über einen Modulzustand. Damit kann sie kein älteres Modell
verändern, und ein Rollback auf ein älteres Bundle nimmt sie
vollständig zurück. Fehlt eine Team-ID oder ist eine Liga unbekannt,
bleibt die Partie unkorrigiert.

### `src/ml/feature_groups.py`, `run_ml.py`, `README.md`

Unverändert aus C15 übernommen beziehungsweise um `--evaluate-c16` und
`--release-c16` sowie den C16-Abschnitt ergänzt.

### Die exakte C16-Formel

```
lambda_heim' = lambda_heim * exp(gamma * (a[liga_heim] + d[liga_gast]))
lambda_gast' = lambda_gast * exp(gamma * (a[liga_gast] + d[liga_heim]))
```

`a` ist die offensive, `d` die defensive Ligastärke als
log-Multiplikator, `gamma` in (0, 1] die globale Dämpfung. Die Grenzen
`[0,6; 1,6]` greifen **nach** der Dämpfung.

### Gamma-Auswahl

Gitter `(0,25, 0,50, 0,75, 1,00)`, vor der Messung eingefroren, nach
Sichtung der Ergebnisse nicht erweitert.

Auswahl auf einer zeitlichen inneren Validierung innerhalb der
Trainingshistorie: bei einer Trainingssaison Teilung am mittleren
Spieldatum, bei mehreren Teilung nach Saison. Geschätzt wird auf dem
frühen Teil, bewertet auf dem späten. Kriterium ist die Poissondevianz.

**Tie-Break:** Liegen zwei Werte innerhalb `1e-6` gleichauf, gewinnt
das **kleinere** Gamma, also die vorsichtigere Wahl.

### Alpha-Auswahl

Unverändert aus C15: derselbe Raum `(0.01, 0.1, 1.0, 10.0, 100.0)`,
dieselbe zeitliche innere Teilung, bei Gleichstand gewinnt das größere
Alpha. Alpha wird zuerst gewählt, dann Gamma auf derselben inneren
Validierung. Sequentiell und nicht als Gitter über beide, weil zwanzig
Kombinationen eine Suche wären und vier eine Auswahl.

### Innere Foldstruktur

| Fold | Historie | innere Anpassung | innere Validierung | Alpha | Gamma |
| --- | ---: | ---: | ---: | ---: | ---: |
| `cl_2024` | 109 Partien | 48 | 61 | 0,1 | **1,00** |
| `cl_2025` | 298 Partien | 109 | 189 | 0,01 | **0,75** |

Gemessene Gamma-Devianzen auf der inneren Validierung:

| Fold | 0,25 | 0,50 | 0,75 | 1,00 |
| --- | ---: | ---: | ---: | ---: |
| `cl_2024` | 1,25049 | 1,22392 | 1,20642 | **1,19771** |
| `cl_2025` | 1,43586 | 1,39376 | **1,38531** | 1,39661 |

### Cold Start, unbekannte Liga, Provenienz

Eine Liga ohne frühere CL-Historie bekommt keine Spalte und damit den
Wert 0, also den Faktor 1, unabhängig von Gamma. Getestet für jedes
Gamma des Gitters: unbekannt gegen unbekannt ergibt exakt
`(1.0, 1.0)`, endlich und deterministisch.

Eine unbekannte Liga bekommt keinen Bonus. Was auf sie wirkt, ist
ausschließlich die Stärke des bekannten Gegners.

Lässt sich für eine Seite keine Herkunftsliga bestimmen, bleibt die
Partie unkorrigiert. Die Ligazuordnung läuft ausschließlich über den
validierten C13-Crosswalk; rohe IDs werden nie providerübergreifend
gleichgesetzt.

### Warum es keine PD-Sonderregel gibt

Die Dämpfung ist **ein** Wert für alle Ligen. Vier Tests belegen das:

1. `test_kein_ligacode_in_der_modelllogik`: Kein Ligacode und kein
   Ländername kommt im Quelltext der Ligastärke vor.
2. `test_keine_vereinsnamen_in_der_modelllogik`: Keine Vereinsnamen.
3. `test_gamma_wirkt_auf_jede_liga_gleich`: Gleiche Parameter ergeben
   gleiche Faktoren, für jedes Gamma des Gitters.
4. `test_das_pd_verhalten_folgt_derselben_formel_wie_jede_liga`: PD und
   eine erfundene Liga `ZZ9` mit identischen Parametern bekommen
   identische Faktoren in beiden Rollen, und der Wert folgt exakt
   `exp(gamma * (a + d))`.

Zusätzlich prüft `test_kein_routing_nach_testsegment`, dass keine
`if`-Bedingung im Quelltext auf einen Segmentnamen verzweigt.

---

## C. Daten und Population

| Größe | Wert |
| --- | --- |
| Datensatzzeilen | 5756, davon 503 CL |
| Dataset-Fingerprint | `653040695b0511a260ddaead354ffc97f5550cdf844d3e37d22c6e98314838b7` |
| Reiner Target-Fingerprint | `bdf43891bbd19f4b70c8b0f5d2b3b1f892fc48360331506bf55d12b79bee95cf` |
| Standardpopulation | **283** (Vertragserwartung 283, bestätigt) |
| Kontextpopulation | **373** (Vertragserwartung 373, bestätigt) |
| Profilquellen | 1006 von 1006 `domestic_pit`, `cl_history_pit` 0, `neutral` 0 |
| Ausschlüsse | 21 CL-Spiele wegen Profiltiefe unter sechs, unverändert aus C13 |

| Fold | Testzeilen | Trainingszeilen | Ligahistorie |
| --- | ---: | ---: | ---: |
| `cl_2024` | 144 | 1361 | 109 |
| `cl_2025` | 139 | 2917 | 298 |

Keine Abweichung von den erwarteten Populationen. V0, C14, C15 und C16
bewerten identische Match-IDs, Targets, Folds und Ausschlüsse; dies
wird je Fold über `assert_paired` und im Test
`test_alle_vier_kandidaten_bewerten_dieselben_partien` geprüft.

### Leakage-Nachweis

| Prüfung | `cl_2024` | `cl_2025` |
| --- | --- | --- |
| Testergebnisse auf 9:0 → Gamma unverändert | ja | ja |
| Testergebnisse auf 9:0 → Alpha unverändert | ja | ja |
| Testergebnisse auf 9:0 → Ligaparameter unverändert | ja | ja |
| Historienergebnisse geändert → Parameter ändern sich | ja | ja |
| Zeilenreihenfolge irrelevant | ja | ja |
| Zwei Läufe identisch | ja | ja |
| Keine Test-ID in Historie oder innerer Validierung | ja | ja |

---

## D. Ergebnisse

### Standardbestand, n = 283

| Kandidat | Log Loss | Brier | RPS | Kalibrierung | Accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| V0 | 1,02842 | 0,61870 | 0,24412 | 0,04346 | 0,47350 |
| C14 | 1,01679 | 0,61162 | 0,24131 | 0,03340 | 0,49470 |
| C15 | 0,93330 | 0,55013 | 0,21113 | 0,03923 | 0,59717 |
| **C16** | **0,94086** | **0,55574** | **0,21371** | 0,04541 | 0,58657 |

| Vergleich | ΔLog Loss | 95-Prozent-Intervall |
| --- | ---: | --- |
| **C16 gegen V0** | **−0,087560** | **[−0,118828; −0,055146]** |
| C16 gegen C14 | −0,075931 | [−0,104823; −0,044407] |
| C16 gegen C15 | **+0,007558** | [+0,000693; +0,014013] |
| C15 gegen V0 | −0,095118 | [−0,131169; −0,057305] |
| C14 gegen V0 | −0,011628 | [−0,026279; +0,003319] |

ΔBrier gegen V0: −0,062960. ΔRPS gegen V0: −0,030406.

Die Dämpfung kostet gegenüber C15 messbar Gesamtgüte, und das
Intervall dieses Verlusts schließt die Null aus. Das ist der bewusste
Preis für die Stabilität und wird nicht schöngeredet.

### Je Fold

| Fold | n | V0 | C14 | C15 | C16 | Δ gegen V0 | Gamma |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `cl_2024` | 144 | 1,00480 | 0,97905 | 0,93867 | 0,93867 | −0,066131 | 1,00 |
| `cl_2025` | 139 | 1,05288 | 1,05588 | 0,92774 | 0,94312 | −0,109758 | 0,75 |

Schlechtester Fold: `cl_2024` mit −0,066131, weiterhin deutlich
negativ. Foldstreuung: 0,043627.

### Kontextbestand, n = 373

ΔLog Loss −0,071891, ΔBrier −0,050251, ΔRPS −0,024870.
Folds: −0,052150 (Gamma 1,00) und −0,092168 (Gamma 0,75).

### Pflichtsegmente

| Segment | n | C15 | C16 |
| --- | ---: | ---: | ---: |
| `origin:top5_vs_other` | 73 | −0,19496 | −0,17771 |
| `origin:other_vs_top5` | 73 | −0,10572 | −0,10521 |
| `origin:top5_vs_top5` | 102 | −0,03655 | −0,02844 |
| `origin:other_vs_other` | 35 | −0,03545 | −0,03500 |
| `home_origin_league:PL` | 39 | −0,21393 | −0,18470 |
| `home_origin_league:SA` | 36 | −0,13708 | −0,11909 |
| `home_origin_league:BL1` | 36 | −0,08017 | −0,07705 |
| **`home_origin_league:PD`** | **36** | **+0,01186** | **+0,00985** |
| `league_evidence:cold_start` | 55 | −0,14285 | −0,13479 |
| `league_evidence:thin` | 122 | −0,11086 | −0,10506 |
| `league_evidence:strong` | 106 | −0,05223 | −0,04291 |
| `min_profile_depth:6-19` | 41 | −0,14627 | −0,13984 |
| `min_profile_depth:>=20` | 242 | −0,08645 | −0,07870 |

`home_origin_league:PD` ist das **einzige** interpretierbare Segment
mit positivem Delta. Abstand zur Grenze: `−0,00015`.

### Konzentration

| Größe | C15 | C16 |
| --- | ---: | ---: |
| Anteil der fünf stärksten Vereine | 28,68 % | **28,06 %** |
| mittleres Delta ohne diese fünf | −0,06783 | −0,06299 |
| Richtung hält ohne sie | ja | ja |
| Leave-one-team-out Richtung hält | ja | **ja** |
| Leave-one-league-out Richtung hält | ja | **ja** |
| Anteil Spiele mit geringerem Loss | 66,43 % | **65,72 %** |

Schlechteste Leave-one-team-out: ohne Verein 930 bleibt Δ bei
−0,07929. Schlechteste Leave-one-league-out: ohne PL bleibt Δ bei
−0,06650.

---

## E. Gate-Entscheidung

| Gate | Schwelle | Messwert | Status | Begründung |
| --- | --- | ---: | --- | --- |
| `primary_better` | Δ < 0 | −0,087560 | bestanden | deutlich besser als V0 |
| `all_folds_same_direction` | alle < 0 | −0,066131 / −0,109758 | bestanden | beide Folds negativ |
| `no_single_fold_carries_all` | Anteil ≤ 0,9 | 0,376 | bestanden | kein Fold dominiert |
| `ci_excludes_zero` | obere Grenze < 0 | −0,055146 | bestanden | Intervall klar unter null |
| `brier_not_worse` | ≤ 0,0 | −0,062960 | bestanden | besser |
| `rps_not_worse` | ≤ 0,0 | −0,030406 | bestanden | besser |
| `calibration_holds` | ≤ V0 × 1,25 = 0,054328 | 0,045408 | bestanden | innerhalb der Toleranz |
| **`no_severe_segment_damage`** | keine Gruppe ≥ 0,01 | **keine** | **bestanden** | PD bei +0,00985 |
| `sample_large_enough` | n ≥ 30 | 283 | bestanden | |
| `no_fold_severely_worse` | jeder < 0,01 | max −0,066131 | bestanden | |
| `context_not_severely_damaged` | < 0,01 | −0,071891 | bestanden | |

**11 von 11 erfüllt.**

Zusätzlich geprüft, ohne numerisches Gate:

| Prüfung | Ergebnis |
| --- | --- |
| Kein Verein oder eine Liga erklärt den Vorteil | bestanden, 28,06 % |
| Leave-one-team-out und Leave-one-league-out vertretbar | bestanden, Richtung hält überall |
| PIT und Leakage | bestanden, beide Folds |
| Deterministisch reproduzierbar | bestanden, identischer Ergebnisfingerprint |
| Gegenüber C15 fachlich vertretbar | ja, mit dokumentiertem Güteverlust von +0,007558 |

### Verdict

**`accepted`**

Akzeptanzklasse: `accepted_development_evidence`.

---

## F. Bundle, Registry und Runtime

**Es wurde kein Modell aktiviert.** Die folgenden Schritte aus dem
Freigabeplan wurden **absichtlich nicht** ausgeführt:

| Schritt | Status |
| --- | --- |
| finales Modell trainieren | abgebrochen vor dem Bundlebau |
| Bundle erzeugen | **nein** |
| Modell-ID, Bundle-Hash | **keine** |
| Approval erzeugen | **nein** |
| Registry ändern | **nein** |
| Active-Übergang | **nein** |
| Runtime umschalten | **nein** |
| End-to-End-Simulation mit aktivem Modell | **nein** |

### Der Grund

Der Bundlevertrag aus V2-C0B verlangt drei Dinge, die ein
**zweistufiges** Modell nicht erfüllt:

1. `persist.evaluation_reference` verlangt
   `configuration.task == "cl_shadow_backtest"`. Das C16-Artefakt ist
   eine andere Evaluation, und es als Shadow-Backtest zu deklarieren
   wäre falsch.
2. Dieselbe Funktion verlangt, dass der Kandidatenname des Artefakts
   dem des Trainings entspricht. Der C16-Kandidat heißt
   `team_profile_cl_plus_damped_league_strength`.
3. `persist.load_bundle` prüft denselben Namen beim Laden gegen
   `cl_evaluate.CANDIDATE`. Die Runtime würde ein C16-Bundle ablehnen.

Diese drei Schranken gleichzeitig aufzuweichen wäre genau die
Umgehung, gegen die V2-C11 und V2-C15 gebaut wurden. Der Freigabeweg
scheitert deshalb **fail-closed** mit klarem Grund:

```
Status: blocked_by_bundle_contract
Grund : Der Bundlevertrag aus V2-C0B deckt noch kein zweistufiges
        Modell ab. Ein C16-Bundle verlangt eine erweiterte Provenienz-
        und Loaderregel; sie wird nicht nebenbei aufgeweicht, sondern
        braucht einen eigenen eingefrorenen Vertrag.
```

### Was bereits vorbereitet ist

- `c16_release.build_final_bundle()` baut das zweistufige Bundle
  vollständig, sobald der Vertrag es zulässt.
- `c16_release.preflight()` prüft unter anderem, dass ein als C16
  etikettiertes Bundle die zweite Stufe wirklich trägt. Ein Bundle
  ohne `league_strength` oder ohne Gamma wird abgelehnt; das ist
  getestet.
- `inference._ligastaerke_anwenden()` wendet die zweite Stufe an,
  sobald ein Bundle sie trägt, und bleibt sonst wirkungslos. Drei
  Tests decken Anwendung, unbekannte Liga und fehlende Team-ID ab.
- Rollback, Recovery und Transaktion laufen unverändert über den in
  V2-C15 gebauten, getesteten Weg.

### Aktueller Runtime-Zustand

Kein aktives Modell, Shadow leer, V0 bestimmt jede sichtbare
Nutzerantwort, API meldet `applied: false` mit ehrlichem
Fallbackgrund, der individuelle Regler-Modus bleibt getrennt und lädt
kein Modell.

---

## G. Tests

| Lauf | Ergebnis | Exit |
| --- | --- | ---: |
| Fokussiert `tests/test_c16_damped_league_strength.py` | **63 passed** | 0 |
| Regressionen (26 Dateien) | **1641 passed, 2 skipped** | 0 |
| **Vollständige Suite** | **2 failed, 5596 passed, 128 skipped, 91 errors** | **1** |
| C15-Baseline | 2 failed, 5533 passed, 128 skipped, 91 errors | 1 |

**+63 bestandene Tests**, identische Fehler-, Skip- und Errorzahl.

### Verbleibende Fehlschläge, beide vorbestehend

- `tests/test_go1_season_and_pit.py::TestSaisonWeitergabe::test_provider_ausfall_bleibt_neutral`
  Der Test neutralisiert `squad_impact.disk_cached_call`, aber nicht
  die zweite Cacheebene in `apisports_api`.
- `tests/test_test_isolation.py::TestReihenfolgeSpieltKeineRolle::test_umgekehrte_reihenfolge_aendert_nichts`
  Braucht PostgreSQL auf 127.0.0.1:5432, das lokal nicht läuft. Dies
  ist auch die Ursache der 91 Errors.

**Keine neuen Skips.** Die 128 Skips sind unverändert. **Kein Test
gelöscht, kein Gate gelockert.**

---

## H. README und Sicherheit

| Prüfung | Ergebnis |
| --- | --- |
| README-Em-Dashes vorher | **0** |
| README-Em-Dashes nachher | **0** |
| Secret-Scan über alle C16-Dateien | nur die Suchliste des Sicherheitstests selbst |
| `.env` gelesen oder verändert | nein, unverändert seit dem 21. August |
| Netzwerkzugriffe | keine |
| API-Kauf | keiner |
| Absolute lokale Pfade in Artefakten | keine |
| Rohdaten oder Featurevektoren in Artefakten | keine |
| Bestehende Dateien gelöscht | keine |
| `git diff --check` | sauber, Exit 0 |

---

## I. Git-Endzustand

`git diff --stat`: 2914 Einfügungen, 279 Löschungen in 16 Dateien.
`git diff --cached --stat`: leer.

**Nichts gestaged. Kein Commit. Kein Push. Kein Deployment.**
HEAD unverändert `4f55d80cb47254a3704589dfba3fd5dd78fa937f`.

### Neue C16-Dateien

```
src/ml/c16_damped_league_strength.py
src/ml/c16_release.py
tests/test_c16_damped_league_strength.py
data/ml/c16_damped_league_strength_contract.json
data/ml/c16_damped_league_strength_evaluation.json
docs/v2-c16-final-report.md
```

### Geänderte Dateien in C16

```
src/features/league_strength.py
src/ml/inference.py
run_ml.py
README.md
```

---

## J. Verbleibende Arbeitsblöcke

Nach dem tatsächlichen C16-Endzustand ist **genau ein** weiterer
Implementierungsblock erforderlich.

### Block 1 von 1: Zweistufiger Bundlevertrag und Aktivierung

**Präziser Name:** V2-C17, Mehrstufiger Bundlevertrag, Freigabe und
Runtime-Aktivierung.

**Konkretes Ziel:** Das bereits akzeptierte C16-Modell so freigeben,
dass es die sichtbare Champions-League-Simulation bestimmt, ohne eine
der bestehenden Schranken aufzuweichen.

**Notwendiger Scope:**

1. Einen eigenen, vor der Umsetzung eingefrorenen Vertrag für
   mehrstufige Bundles: welche Evaluationsarten ein Bundle binden
   dürfen, wie ein Kandidatenname geprüft wird, welche
   Bundle-Schemafassung welche Stufen tragen darf.
2. `persist.evaluation_reference` um eine benannte, gleich strenge
   Evaluationsart erweitern, statt die bestehende umzudeuten.
3. `persist.load_bundle` und `inference.load_model` um den
   C16-Kandidatennamen und Bundle-Schema 3 erweitern, mit
   Rückwärtskompatibilität für Schema 2.
4. `persist.save_bundle`-Validierung auf die zweite Stufe ausdehnen.
5. Finales C16-Modell trainieren, Bundle erzeugen, Hash und Modell-ID
   bilden.
6. Freigabe über den bestehenden transaktionalen Weg
   `candidate → shadow → active`.
7. Runtime-Parität nachweisen: dieselbe Partie muss im Training und
   zur Laufzeit dieselben Lambdas ergeben.
8. End-to-End-Simulation eines echten CL-Spiels mit aktivem Modell.
9. Rollback-Probe vor und nach der Umschaltung, danach den
   freigegebenen Zustand wiederherstellen.
10. API- und UI-Wahrheit prüfen: `applied: true`, Modell-ID, Version,
    Provenienz.
11. Vollständiger Abschlussaudit.

**Erwartete Dateien und Systeme:** `src/ml/persist.py`,
`src/ml/inference.py`, `src/ml/c17_bundle_contract.py` (neu),
`src/ml/c16_release.py`, `tests/test_c17_multistage_bundle.py` (neu),
`data/ml/c17_*.json`, `README.md`, `docs/v2-c17-final-report.md`.

**Abhängigkeiten:** C16-Evaluation (`accepted`, liegt vor),
C11-Registry, C15-Transaktionsweg. Keine neuen Daten, kein API-Abo.

**Definition of Done:**
- Vertrag vor der Umsetzung eingefroren
- Bundle mit beiden Stufen erzeugt, geladen und validiert
- genau ein aktives Modell in der Registry
- Runtime wendet C16 an, API meldet `applied: true`
- V0 nur noch technischer Fail-closed-Fallback
- Regler-Modus unverändert getrennt
- Rollback end-to-end bewiesen, Endzustand wiederhergestellt
- keine neue Regression gegenüber `2 failed, 5596 passed, 128 skipped, 91 errors`
- README weiterhin null Em-Dashes

**Abbruchkriterien:**
- Die Runtime-Parität scheitert, also weicht die Laufzeitvorhersage
  von der Messung ab. Dann keine Aktivierung.
- Das Bundle lässt sich nicht validiert laden.
- Der Rollback stellt den Vorzustand nicht nachweisbar wieder her.
- Eine bestehende Schranke ließe sich nur durch Aufweichen erfüllen.

**Kombinierbar?** Nein. Der Block berührt den Bundlevertrag **und**
den Live-Vorhersagepfad. Beides zusammen ist bereits das Maximum, was
in einem Block verantwortbar ist; etwas hinzuzunehmen wäre genau die
Bündelung riskanter Themen, die vermieden werden soll.

**Empfohlenes Modell:** Claude Opus.

**Empfohlene Denkstufe:** **Ultra High.**

**Warum:** Der Block ändert einen eingefrorenen Vertrag und den Pfad,
der Nutzerergebnisse bestimmt. Genau an dieser Stelle sind in C11, C12
und C15 die Fehler entstanden, die später repariert werden mussten:
ein nie gegangener Accepted-Pfad, eine unbewiesene Rollbackzusage, ein
Fingerprint, der Vertrag und Zustand vermischte. Die Arbeit ist nicht
umfangreich, aber jede einzelne Entscheidung darin ist eine
Vertrauensentscheidung.

**GitHub-Push danach möglich?** Ja.

**VPS-Deployment danach möglich?** Ja, mit aktivem Modell.

### Ausdrücklich keine weiteren Implementierungsblöcke

Nach C17 ist V2 technisch abgeschlossen, statistisch entschieden,
auditiert, GitHub-bereit und deploybar.

### Nicht-Implementierungsarbeit

**Unabhängige Bestätigung mit Saison 2026/27.** Das ist kein
Arbeitsblock, sondern ein Ereignis: Sobald genügend Spiele der Saison
2026/27 vorliegen, kann das dann bereits freigegebene Modell auf einem
Bestand gemessen werden, der keine Entscheidung getragen hat. Erst
dieses Ergebnis wäre eine unabhängige Bestätigung statt
Entwicklungsevidenz. Bis dahin bleibt der Vermerk im Artefakt stehen.

**Optional, nicht erforderlich:** die zwei vorbestehenden
Testfehlschläge beheben (zweite Cacheebene in `apisports_api`, lokale
PostgreSQL-Instanz). Beide sind Infrastruktur und blockieren weder
Release noch Deployment.

### Sequenz bis zum verifizierten VPS-Betrieb

1. **Jetzt:** C16 ist evaluiert und akzeptiert, nichts aktiviert.
2. **C17 (Opus, Ultra High):** Bundlevertrag, Freigabe, Aktivierung,
   Audit.
3. **Elie:** Prüfung des C17-Berichts, dann stagen, committen, pushen.
4. **Elie:** VPS-Deployment.
5. **Nach dem Deployment:** verifizieren, dass die API `applied: true`
   mit der erwarteten Modell-ID meldet und eine Beispielsimulation die
   erwarteten Wahrscheinlichkeiten liefert.
6. **Später, ohne Eile:** unabhängige Bestätigung mit Saison 2026/27.

---

## K. Endstatus

Der einzige verbleibende Blocker vor dem finalen Release-Audit:

| Blocker | Gemessener Abstand |
| --- | --- |
| Der C0B-Bundlevertrag deckt kein zweistufiges Modell ab | kein statistischer Abstand, eine Vertragslücke. Drei benannte Schranken (`configuration.task`, Kandidatenprüfung in `evaluation_reference`, Kandidatenprüfung in `load_bundle`) müssen ausdrücklich erweitert werden. |

Statistisch ist kein Abstand mehr offen: **alle elf Gates sind
erfüllt**, das knappste mit `+0,00985` gegen `0,01000`.

**V2-C16 NOT YET READY FOR FINAL RELEASE AUDIT**
