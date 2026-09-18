# V2-C15 Abschlussbericht: Ligastärke, Freigabeweg und Abschlussaudit

Stand: Abschluss des zweiten und finalen geplanten V2-Arbeitsblocks.

---

## A. Ausgangslage

| Größe | Wert |
| --- | --- |
| Branch | `main` |
| HEAD | `4f55d80cb47254a3704589dfba3fd5dd78fa937f` (unverändert) |
| Gestaged | nichts |
| C9-Schema-Fingerprint | `475b9be82c21c7ea977d71db1a714e3bc37fd4be2336897285730bc116694aa5` |
| C10-Cutoff | 12:00 UTC, strikt kleiner |
| C11-Vertragsfingerprint (neu, zustandsfrei) | `66d023b9c205cd9767812961dd9eeaa6a8008fef5d1283f46f211169875c71b4` |
| C11-Zustandsfingerprint (neu) | `314540e5ba33d4c30f55ca895ba904ded7dd6e723fd1eb54420592ad0ce518a5` |
| C13-Vertragsfingerprint | `e51f5f908e833df8cd125713ddcee3b182451e1fad4467f26093699df4695a57` |
| C13-Zustandsfingerprint | `75315a0c4858c2123e68039bf987f25dc87b4b55c6341a209a30c04b82189933` |
| C14-Vertragsfingerprint | `704c9ade45f3ca1c9fde49bf1e0812f1c903f7ebc71ee07554bd9d4883dba835` |
| C14-Result-Fingerprint | `9544301a05922388b426ef855d504445754c3115eb713fe821ff612570330343` |
| Registry vor C15 | ein Eintrag `clm-8a4eda90a08395cc`, Stage `candidate`, Evaluation `rejected` |
| Aktives Modell vor C15 | keines (`no_active_model`) |
| Runtime vor C15 | V0 bestimmt jede sichtbare Nutzerantwort |
| Bekannte Testbaseline | `2 failed, 5451 passed, 128 skipped, 91 errors` |

---

## B. Der eingefrorene C15-Vertrag

**Fingerprint `c1a155fbf48c07f0e3f27bac0110f8032933c98be82e57c406307b6cde8f14b8`**

Geschrieben nach `data/ml/c15_league_strength_contract_2023-2025.json`,
13.016 Bytes, mit `frozen_before_measurement: true`, **bevor** eine
einzige Zahl gerechnet wurde. Die Datei enthält weder `decision` noch
`measurement`; ein Test prüft das.

**Modellschema-Fingerprint:** `0bbb0f161cc259fe439daef32163c89c40a88af2628ce9c7c36e820d234099c2`

### Kandidat

- Name: `team_profile_cl_plus_league_strength`
- 16 Basismerkmale, identisch mit dem C14-Kandidaten
- Stufe 1: `poisson_offset_correction_linear`, nationale Trainingszeilen
- Stufe 2: `poisson_ridge_league_offsets`, ausschließlich frühere CL-Partien
- Alpha-Raum beider Stufen: `(0.01, 0.1, 1.0, 10.0, 100.0)`
- Faktorgrenzen Stufe 2: `[0.6, 1.6]`
- Mindestbeobachtungen Stufe 2: 40

### Kontrollen

- `v0_baseline`: die bestehende Poisson-Baseline, kein Modell
- `team_profile_cl`: der unveränderte C14-Ansatz
- Alle drei bewerten identische Match-IDs, Targets, Folds und Ausschlüsse

### Folds

- `cl_2024`: Training 2023, Test 2024/25
- `cl_2025`: Training 2023+2024, Test 2025/26
- Kontextfolds analog mit früheren CL-Partien im Training

### Metriken, Bootstrap, Kalibrierung

- Primär: 1X2 Log Loss, C15 gegen V0; zusätzlich C15 gegen C14
- Sekundär: Brier, RPS
- Ergänzend: Kalibrierungsfehler, Reliability-Bins, Wahrscheinlichkeits-
  verteilungen, Torerwartung, extreme Wahrscheinlichkeiten
- Bootstrap: gepaart je Partie, Seed 20260827, 2000 Iterationen
- Kalibrierung: keine zusätzliche, foldlokal, nie auf dem Testfold

### Schwellen, sämtlich importiert

| Schwelle | Wert | Quelle |
| --- | ---: | --- |
| `severe_degradation` | 0,01 | V2-C2B |
| `max_secondary_degradation` | 0,0 | V2-C8 |
| `max_calibration_degradation` | 0,25 | V2-C8 |
| `min_reliable_n` | 30 | V2-C2B |
| `segment_min_size` | 30 | V2-C2B/C8 |
| `fold_dominance_limit` | 0,9 | V2-C12 |
| `thin_evidence_max` | 20 | vorab in C15 festgelegt |

Keine Schwelle wurde für C15 neu gewählt.

---

## C. Implementierung

### Neue Dateien

| Datei | Zeilen | Zweck |
| --- | ---: | --- |
| `src/features/league_strength.py` | 396 | Die Ligastärke-Komponente: Schätzung, Alphawahl, Anwendung |
| `src/ml/c15_league_strength.py` | ~1500 | Vertrag, Messung, Segmente, Entscheidung, Artefakt |
| `src/ml/c15_release.py` | ~470 | Vorprüfung, Transaktion, Journal, Rollback, Recovery |
| `tests/test_c15_league_strength.py` | ~940 | 81 Tests |
| `data/ml/c15_league_strength_contract_2023-2025.json` | | Der eingefrorene Vertrag |
| `data/ml/c15_league_strength_evaluation_2023-2025.json` | | Das Ergebnisartefakt |

### Geänderte Dateien

| Datei | Änderung | Zweck |
| --- | --- | --- |
| `src/ml/feature_groups.py` | `C15_CANDIDATE` und `C15_VARIANTS` ergänzt, in `all_variants()` aufgenommen | Eigene versionierte Gruppe neben `team_profile_cl` |
| `src/ml/model_registry.py` | `build_artifact` trennt Vertrag und Zustand | C11-Reparatur |
| `src/ml/c12_evaluation.py` | Accepted-Zweig gebaut statt `NotImplementedError` | C12-Reparatur |
| `run_ml.py` | `--evaluate-c15`, `--release-c15` | CLI |
| `README.md` | C15-Abschnitt | Dokumentation |
| `tests/test_c12_final_evaluation.py` | Zwei Tests auf den gebauten Zweig umgestellt | Folge der C12-Reparatur |

### Die Ligastärke, mathematisch

Für eine Partie zwischen einem Heimteam aus Liga `h` und einem
Auswärtsteam aus Liga `a`, mit den Erwartungswerten `lambda_heim` und
`lambda_gast` aus Stufe eins:

```
lambda_heim' = lambda_heim * exp(a[h] + d[a])
lambda_gast' = lambda_gast * exp(a[a] + d[h])
```

`a` ist die offensive, `d` die defensive Ligastärke als
log-Multiplikator. Der Wert 0 bedeutet neutral, also Faktor 1.

**Schätzung.** Jede frühere CL-Partie liefert zwei Beobachtungen, eine
je Seite. Die Entwurfsmatrix trägt je Liga eine Angriffs- und eine
Abwehrspalte; die Heimseitenzeile setzt `attack[h] = 1` und
`defence[a] = 1`, die Auswärtszeile umgekehrt. Ziel ist `Tore / lambda`
mit Gewicht `lambda`, was einer Poissonregression mit `log(lambda)` als
Offset entspricht. Das ist exakt der Offset-Umweg des Basismodells,
also keine neue Modellklasse. Der Heimvorteil steckt bereits in Stufe
eins und wird nicht doppelt modelliert.

**Identifizierbarkeit.** Ohne Achsenabschnitt ist die Lösung nur bis
auf eine Konstante bestimmt: Man könnte auf alle `a` einen Wert
addieren und ihn von allen `d` abziehen, ohne eine einzige Vorhersage
zu ändern. Die Ridge-Strafe wählt darunter die Lösung kleinster Norm.
Gemessenes Rangdefizit der Entwurfsmatrix: exakt 1, also genau die eine
erwartete Konstante.

**Regularisierung.** Alpha wird über eine zeitliche innere Teilung
ausschließlich innerhalb der Trainingshistorie gewählt, nach derselben
Regel wie im Basismodell: bei einer Trainingssaison Teilung am
mittleren Spieldatum, bei mehreren nach Saison. Kriterium ist die
Poissondevianz auf dem späteren Teil; bei Gleichstand gewinnt das
größere Alpha. Gewählt: 0,1 für `cl_2024`, 0,01 für `cl_2025`.

**Cold Start.** Eine Liga ohne frühere CL-Historie bekommt keine Spalte
und damit den Wert 0, also den Faktor 1. Getestet: unbekannt gegen
unbekannt ergibt exakt `(1.0, 1.0)`. Eine unbekannte Liga erhält
keinen Bonus; was auf sie wirkt, ist ausschließlich die Stärke des
bekannten Gegners.

**Grenzen.** Der Ligafaktor ist auf `[0.6, 1.6]` begrenzt, enger als
die Korrekturgrenzen des Basismodells (0,5 bis 2,0), weil hier eine
zweite Korrektur auf eine bereits korrigierte Vorhersage trifft. Zwei
Stufen, die je bis zum Doppelten gehen dürften, könnten sich zum
Vierfachen multiplizieren.

### Geschätzte Parameter

Fold `cl_2024`, 15 Ligen aus 218 Beobachtungen, konvergiert:

| Liga | Angriff | Abwehr |
| --- | ---: | ---: |
| PL | +0,2763 | −0,0116 |
| PD | +0,2178 | −0,1123 |
| PT1 | +0,0704 | +0,0149 |
| SCO1 | −0,1158 | +0,1364 |
| AT1 | −0,1452 | +0,0161 |
| NL1 | −0,1608 | +0,0933 |

Fold `cl_2025`, 18 Ligen aus 596 Beobachtungen:

| Liga | Angriff | Abwehr |
| --- | ---: | ---: |
| PL | +0,4471 | −0,3738 |
| PD | +0,4183 | −0,1825 |
| FL1 | +0,2413 | −0,3657 |
| SCO1 | −0,2473 | +0,2424 |
| CH1 | −0,2890 | +0,0953 |
| AT1 | −0,5527 | +0,1659 |

### Die C11-Reparatur

`model_registry.build_artifact` bildete den Vertragsfingerprint über
das **gesamte** Artefakt minus Zeitstempel, also einschließlich
`models_by_stage`, `active_model_id`, `candidate_model_ids`,
`shadow_model_ids`, `registry_findings`, `registry_fingerprint` und
`rollback_target`. Jede Modellregistrierung bewegte ihn.

Ab jetzt deckt `contract_fingerprint` ausschließlich:
`schema_version`, `contract`, `release_gate`, `runtime_selection`,
`shadow_isolation`, `mode_separation`, `fail_closed_cases`,
`atomic_write`, `known_limits`.

Der Zustand bekommt `state_fingerprint`. Ein Test leert die Registry
und prüft: Vertrag unverändert, Zustand verändert.

### Die C12-Reparatur

`apply_decision` warf bei `accepted` ein `NotImplementedError`. Der
Zweig ist jetzt gebaut: Er erzeugt eine an alle Fingerprints gebundene
Freigabe, garantiert genau ein aktives Modell und **schreibt nichts**.
Die eigentliche Anwendung läuft über `c15_release.apply_release`.

### Die Transaktion

Reihenfolge in `apply_release`:

1. `preflight_ok`: Urteil, Vertragsbindung, Eintrag, Bundle-Hash,
   Merkmalsschema, C9/C10/C13/C14/C15-Bindungen, Registryvalidität
2. `snapshot_written`: Vorzustand sichern
3. Registryzustand vorbereiten, genau ein Active prüfen, validieren
4. `artifact_staged`: Releaseartefakt vorbereiten, noch nicht schreiben
5. `registry_written`: Registry atomar schreiben
6. `registry_revalidated`: von der Platte neu laden und validieren
7. `artifact_finalised`: **erst jetzt** das Releaseartefakt schreiben

Ein Journal hält den Fortschritt fest. `recover()` liest daran ab,
welcher Zustand gilt. Abbrüche nach jedem der vier ersten Schritte sind
parametrisiert getestet.

### Der Rollback

Vor jeder Anwendung wird ein Vorzustand nach
`data/ml/c15_registry_snapshot.json` gesichert. `rollback()` prüft
fail-closed:

- kein Vorzustand vorhanden → verweigert
- Vorzustand unvollständig → verweigert
- Fingerprint des Vorzustands stimmt nicht → verweigert (Manipulation)
- Vorzustand würde ein `rejected`-Modell aktivieren → verweigert
- Vorzustand nicht valide → verweigert
- unlesbarer Vorzustand → `ReleaseError`

Rollback ist technische Wiederherstellung, kein Weg um ein fachliches
Rejected herum.

### Die Gründeliste

C14 nannte drei von vier fehlgeschlagenen Bedingungen, weil
`no_single_fold_carries_all` keinen Grundtext hatte. `REASON_TEXTS`
deckt jetzt alle elf Bedingungen ab. Zwei Tests prüfen, dass
Gate-Matrix und Gründeliste exakt übereinstimmen und dass keine
bestandene Bedingung als Fehler auftaucht.

---

## D. Daten- und Leakage-Nachweis

| Größe | Wert |
| --- | --- |
| Datensatz | 5756 Zeilen, davon 503 CL |
| CL-Vereine | 63 (54 im Testbestand) |
| Dataset-Fingerprint | `653040695b0511a260ddaead354ffc97f5550cdf844d3e37d22c6e98314838b7` |
| Reiner Target-Fingerprint | `bdf43891bbd19f4b70c8b0f5d2b3b1f892fc48360331506bf55d12b79bee95cf` |
| Profilquellen | 1006 von 1006 `domestic_pit`, `cl_history_pit` 0, `neutral` 0 |
| Standardbestand | 283 (Vertragserwartung 283, bestätigt) |
| Kontextbestand | 373 (Vertragserwartung 373, bestätigt) |

### Identifizierbarkeit, gemessen

| Bestand | Zeilen | mit zwei verschiedenen Herkunftsligen |
| --- | ---: | ---: |
| nationale Trainingszeilen | 2917 | **0** |
| frühere CL-Partien Fold `cl_2024` | 109 | 109 (100 %) |
| frühere CL-Partien Fold `cl_2025` | 298 | 292 (98 %) |

### Foldgrenzen

| Fold | Historie bis | Test ab | getrennt |
| --- | --- | --- | --- |
| `cl_2024` | 2024-06-01 | 2024-09-17 | ja |
| `cl_2025` | 2025-05-31 | 2025-09-16 | ja |

Überschneidung Historie/Test: 0 Zeilen in beiden Folds.

### Manipulationstests

- **Alle Testergebnisse auf 9:0 gesetzt** → Ligastärkeparameter
  **identisch**. Kein Testergebnis beeinflusst seine eigene Vorhersage.
- **Alle Historienergebnisse auf 9:0 gesetzt** → Parameter **verändert**.
  Die Gegenprobe: Die Schätzung liest wirklich etwas.
- **Zeilenreihenfolge gemischt** → Parameter und Log Loss identisch.
- **Zwei Läufe** → identisch.
- Cold-Start neutral, unbekannte Liga ohne Bonus.
- Kein Netzimport, keine `.env`, keine Snapshots, keine UEFA-Daten in
  `league_strength.py` und `c15_league_strength.py`.
- Keine Vereinsnamen und keine Top-5-Ligacodes im Quelltext der
  Ligastärke.

---

## E. Vollständige Ergebnisse

### Standardbestand, n = 283

| Kandidat | Log Loss | Brier | RPS | Kalibrierungsfehler |
| --- | ---: | ---: | ---: | ---: |
| V0 | 1,02842 | 0,61870 | 0,24412 | 0,04346 |
| C14 | 1,01679 | 0,61162 | 0,24131 | 0,03340 |
| **C15** | **0,93330** | **0,55013** | **0,21113** | 0,03923 |

| Vergleich | ΔLog Loss | 95-Prozent-Intervall |
| --- | ---: | --- |
| C15 gegen V0 | **−0,095118** | **[−0,131169; −0,057305]** |
| C15 gegen C14 | −0,083490 | [−0,117933; −0,046764] |
| C14 gegen V0 | −0,011628 | [−0,026279; +0,003319] |

ΔBrier gegen V0: −0,068571. ΔRPS gegen V0: −0,032987.

### Je Fold

| Fold | n | V0 | C14 | C15 | Δ gegen V0 | Liga-Alpha |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `cl_2024` | 144 | 1,00480 | 0,97905 | 0,93867 | −0,066131 | 0,1 |
| `cl_2025` | 139 | 1,05288 | 1,05588 | 0,92774 | −0,125147 | 0,01 |

Beide Folds verbessern sich. Der in C14 problematische Fold `cl_2025`
kippt von `+0,002999` auf `−0,125147`.

### Kontextbestand, n = 373

ΔLog Loss −0,078024, ΔBrier −0,054652, ΔRPS −0,026983.

### Herkunftssegmente

| Segment | n | V0 | C15 | Δ | C14 zum Vergleich |
| --- | ---: | ---: | ---: | ---: | ---: |
| `origin:top5_vs_other` | 73 | 1,20 | 1,00 | **−0,19496** | **+0,01453** |
| `origin:other_vs_top5` | 73 | | | −0,10572 | −0,01080 |
| `origin:top5_vs_top5` | 102 | | | −0,03655 | −0,02077 |
| `origin:other_vs_other` | 35 | | | −0,03545 | −0,04128 |

### Herkunftsligen

| Segment | n | V0 | C15 | Δ |
| --- | ---: | ---: | ---: | ---: |
| `home_origin_league:PL` | 39 | 0,90952 | 0,69559 | −0,21393 |
| `home_origin_league:SA` | 36 | 1,11798 | 0,98090 | −0,13708 |
| `away_origin_league:PL` | 40 | 1,08992 | 0,97811 | −0,11180 |
| `away_origin_league:PD` | 36 | 0,97064 | 0,87165 | −0,09899 |
| `home_origin_league:BL1` | 36 | 0,94124 | 0,86108 | −0,08017 |
| `away_origin_league:BL1` | 35 | 0,93469 | 0,88522 | −0,04947 |
| `away_origin_league:SA` | 36 | 1,15087 | 1,11915 | −0,03172 |
| **`home_origin_league:PD`** | **36** | **0,84482** | **0,85668** | **+0,01186** |

### Ligastärke-Evidenz

| Segment | n | Δ |
| --- | ---: | ---: |
| `league_evidence:cold_start` | 55 | −0,14285 |
| `league_evidence:thin` | 122 | −0,11086 |
| `league_evidence:strong` | 106 | −0,05223 |

### Profiltiefe

| Segment | n | Δ |
| --- | ---: | ---: |
| `min_profile_depth:6-19` | 41 | −0,14627 |
| `min_profile_depth:>=20` | 242 | −0,08645 |

### Konzentration

| Größe | C15 | C14 |
| --- | ---: | ---: |
| Anteil der fünf stärksten Vereine | **28,7 %** | 67,7 % |
| mittleres Delta ohne diese fünf | −0,06783 | −0,00376 |
| Richtung hält ohne sie | ja | ja |
| Leave-one-team-out Richtung hält | ja | ja |
| Leave-one-league-out Richtung hält | ja | nicht erhoben |
| Anteil Spiele mit geringerem Verlust | 66,4 % | nicht erhoben |

Schlechteste Liga-Auslassung: ohne PL bleibt Δ bei −0,06913 (n=204).

Die Konzentration ist ausdrücklich **kein Gate**, weil dafür in keinem
freigegebenen Vertrag eine Schwelle existiert.

---

## F. Gate-Matrix

| Gate | Schwelle | Messwert | Status | Quelle | Art |
| --- | --- | ---: | --- | --- | --- |
| `primary_better` | Δ < 0 | −0,095118 | erfüllt | C12 | Pflicht |
| `all_folds_same_direction` | alle < 0 | −0,066131 / −0,125147 | erfüllt | C12 | Pflicht |
| `no_single_fold_carries_all` | Anteil ≤ 0,9 | 0,53 | erfüllt | C12 | Pflicht |
| `ci_excludes_zero` | obere Grenze < 0 | −0,057305 | erfüllt | C12 | Pflicht |
| `brier_not_worse` | ≤ 0,0 | −0,068571 | erfüllt | C8 | Pflicht |
| `rps_not_worse` | ≤ 0,0 | −0,032987 | erfüllt | C8 | Pflicht |
| `calibration_holds` | ≤ V0 × 1,25 | 0,039231 gegen 0,043462 | erfüllt | C8 | Pflicht |
| **`no_severe_segment_damage`** | **keine Gruppe ≥ 0,01** | **`home_origin_league:PD` +0,01186** | **nicht erfüllt** | **C2B** | **Pflicht** |
| `sample_large_enough` | n ≥ 30 | 283 | erfüllt | C2B | Pflicht |
| `no_fold_severely_worse` | jeder < 0,01 | max −0,066131 | erfüllt | C2B | Pflicht |
| `context_not_severely_damaged` | < 0,01 | −0,078024 | erfüllt | C15-Vertrag | Pflicht |

**10 von 11 erfüllt.**

Gründeliste, vollständig und deckungsgleich mit der Gate-Matrix:

> ein grosses Pflichtsegment ist schwer verschlechtert
> (`['home_origin_league:PD']`)

---

## G. Verdict

**`rejected`**

### Begründung

Genau ein verpflichtendes Gate scheitert:
`home_origin_league:PD` mit n=36 und Δ `+0,01186` überschreitet die
Schwelle für schwere Segmentverschlechterung von `0,01`. Die Schwelle
stammt aus V2-C2B und wurde nicht für C15 gewählt. Der Vertrag stand
vor der Messung; die Schwelle wird nicht nachträglich verschoben, weil
das Ergebnis sonst gefiele.

Bemerkenswert an diesem Segment: V0 erreicht dort mit 0,84482 den
niedrigsten Log Loss aller Herkunftssegmente. Es gibt dort wenig zu
gewinnen und etwas zu verlieren.

### Die Sachlage im Übrigen

- **Ist V2 insgesamt besser als V0?** Ja, deutlich und statistisch
  abgesichert: −0,095118 mit einem Intervall, das die Null klar
  ausschließt.
- **Ist V2 besser als C14 und V1?** Ja, −0,083490 gegenüber C14, mit
  eigenem Intervall [−0,117933; −0,046764].
- **Zeigen beide Folds dieselbe Richtung?** Ja, erstmals seit C12.
- **Schließt das Intervall die Null aus?** Ja.
- **Gibt es eine große beschädigte Gruppe?** Eine, knapp:
  `home_origin_league:PD`, n=36, +0,01186 gegen eine Schwelle von 0,01.
  Die beiden C14-Schadenssegmente sind repariert.
- **Ist das Ergebnis auf wenige Vereine konzentriert?** Deutlich
  weniger als in C14: 28,7 Prozent statt 67,7, Richtung hält in jeder
  Auslassungsprobe.

### Einschränkungen

Es gibt keinen unangetasteten Holdout. Die Ligastärkeform wurde aus
einer C14-Diagnose auf denselben Saisons abgeleitet. Das ist
Entwicklungsevidenz und ausdrücklich keine unabhängige Bestätigung.
Zwei äußere Folds sind wenig. Fold 1 schätzt aus nur 109 früheren
CL-Partien über 15 Ligen.

---

## H. Releasezustand

| Größe | Wert |
| --- | --- |
| Bundle erzeugt | **nein** (Verdict nicht `accepted`) |
| Modell-ID | keine neue |
| Bundle-Hash | keiner |
| Approval | keine erteilt |
| Registry vorher | ein `candidate`, Evaluation `rejected` |
| Registry nachher | **unverändert** |
| Aktives Modell | **keines** (`no_active_model`) |
| Shadow | leer |
| Fallback | V0, unverändert wirksam |
| Runtime-Parität | unverändert, `league_match_sim` enthält kein `src.ml` |
| API | meldet weiterhin `applied: false` mit ehrlichem Fallbackgrund |
| UI | unverändert |
| Reglertrennung | unverändert, lädt kein Modell |

Der Freigabe-Trockenlauf verweigert mit zwei Befunden: das Urteil ist
nicht `accepted`, und das Merkmalsschema des vorhandenen Kandidaten ist
das C14-Schema, nicht das C15-Schema.

Der Accepted-Pfad, die Transaktion, das Recovery und der Rollback sind
vollständig implementiert und **synthetisch bewiesen**, obwohl die
Messung sie nicht auslöst.

---

## I. Tests

| Lauf | Ergebnis | Exit |
| --- | --- | ---: |
| Fokussiert `tests/test_c15_league_strength.py` | 81 passed | 0 |
| Regressionen (25 Dateien) | 1576 passed, 2 skipped, 1 failed → nach Korrektur grün | 1 |
| Regressionen nach Korrektur (`test_c12_final_evaluation.py`) | 50 passed | 0 |
| **Vollständige Suite** | **2 failed, 5533 passed, 128 skipped, 91 errors** | **1** |
| C14-Baseline | 2 failed, 5451 passed, 128 skipped, 91 errors | 1 |

**+82 bestandene Tests** (81 C15 plus ein neuer C12-Test), identische
Fehler-, Skip- und Errorzahl.

### Verbleibende Fehlschläge, beide vorbestehend

- `tests/test_go1_season_and_pit.py::TestSaisonWeitergabe::test_provider_ausfall_bleibt_neutral`
  Der Test neutralisiert `squad_impact.disk_cached_call`, aber nicht
  die zweite Cacheebene in `apisports_api`.
- `tests/test_test_isolation.py::TestReihenfolgeSpieltKeineRolle::test_umgekehrte_reihenfolge_aendert_nichts`
  Braucht PostgreSQL auf 127.0.0.1:5432, das lokal nicht läuft. Dies
  ist auch die Ursache der 91 Errors.

### Geänderte Tests, mit Begründung

`tests/test_c12_final_evaluation.py::test_accepted_wird_nicht_stillschweigend_angewandt`
prüfte, dass der Accepted-Zweig ein `NotImplementedError` wirft. Das
war ehrlich, solange der Weg nicht gebaut war. Nach der Reparatur
wandert die Zusicherung dorthin, wo sie hingehört: Der Zweig bereitet
einen Zustand vor und **schreibt nichts**, er erzeugt eine gebundene
Freigabe, und er garantiert genau ein aktives Modell. Ein zweiter Test
`test_der_accepted_zweig_wirft_nicht_mehr` ist als Gegenprobe
hinzugekommen.

---

## J. Sicherheit und README

| Prüfung | Ergebnis |
| --- | --- |
| Secret-Scan über alle C15-Dateien | nur die Suchliste des Sicherheitstests selbst |
| Absolute lokale Pfade in Artefakten | keine |
| Netzimporte in C15-Modulen | keine |
| `.env` gelesen oder verändert | nein, unverändert seit dem 21. August |
| Rohdaten oder Featurevektoren in Artefakten | keine, nur Merkmalsnamen und aggregierte Parameter |
| Forschungsdateien gelöscht | keine |
| KI-Attribution | keine |
| README-Em-Dashes | **0** |
| `git diff --check` | sauber, Exit 0 |

---

## K. Git-Endzustand

- `git status --short`: 15 modifizierte, 36 unversionierte Dateien
- `git diff --stat`: 2556 Einfügungen, 279 Löschungen in 15 Dateien
- `git diff --cached --stat`: leer
- Nichts gestaged, kein Commit, kein Push, kein Deployment
- HEAD unverändert `4f55d80cb47254a3704589dfba3fd5dd78fa937f`

### Für Git vorgesehen

**Quellcode und Tests, geändert:**

```
README.md
run_ml.py
src/data/snapshot_archive.py
src/features/pit_profiles.py
src/ml/cl_dataset.py
src/ml/dataset.py
src/ml/feature_groups.py
src/ml/runtime.py
src/predict/league_match_sim.py
tests/test_cl_custom_api.py
tests/test_ml_cl_dataset.py
tests/test_ml_dataset.py
tests/test_ml_runtime.py
tests/test_pit_profiles.py
tests/test_pit_runtime_cutoff.py
tests/test_c12_final_evaluation.py
```

**Quellcode und Tests, neu:**

```
src/data/national_sources.py
src/features/league_strength.py
src/features/prediction_cutoff.py
src/features/team_identity.py
src/ml/c10_contract.py
src/ml/c12_evaluation.py
src/ml/c13_contract.py
src/ml/c14_reevaluation.py
src/ml/c15_league_strength.py
src/ml/c15_release.py
src/ml/model_registry.py
tests/test_c10_prediction_cutoff.py
tests/test_c11_model_registry.py
tests/test_c12_final_evaluation.py
tests/test_c13_national_profiles.py
tests/test_c14_reevaluation.py
tests/test_c15_league_strength.py
docs/v2-c15-final-report.md
```

**Verträge und Entscheidungsnachweise, neu (klein, nachvollziehbar,
gehören in die Historie):**

```
data/ml/c10_prediction_cutoff_contract_2023-2025.json
data/ml/c11_registry_release_gate_contract.json
data/ml/c12_final_evaluation_2023-2025.json
data/ml/c13_national_profile_contract_2023-2025.json
data/ml/c14_reevaluation_contract_2023-2025.json
data/ml/c14_reevaluation_2023-2025.json
data/ml/c15_league_strength_contract_2023-2025.json
data/ml/c15_league_strength_evaluation_2023-2025.json
data/ml/model_registry.json
```

### Bewusst NICHT für Git vorgesehen

| Datei | Grund |
| --- | --- |
| `data/ml/dataset_2023-2025.json` | großer generierter Datensatz, jederzeit reproduzierbar |
| `data/ml/dataset_with_cl_2023-2025.json` | dito |
| `data/ml/ablation_2023-2025.json` | Forschungsartefakt aus C2/C3 |
| `data/ml/ablation_diagnostics_2023-2025.json` | dito |
| `data/ml/cl_shadow_backtest_2023-2025.json` | Forschungsartefakt |
| `data/ml/shadow_eval_2023-2025.json` | Forschungsartefakt |
| `data/backtests/` | lokale Laufergebnisse |
| `data/go3_backtest_result.json` | lokales Laufergebnis |
| `data/go45_backtest_result.json` | lokales Laufergebnis |
| `data/percentiles/percentiles_2026.json` | generiert |
| `data/ml/c15_release_journal.json` | Laufzeitjournal, entsteht nur bei echter Freigabe |
| `data/ml/c15_registry_snapshot.json` | Laufzeitsicherung, dito |

Keine dieser Dateien wird gelöscht; sie bleiben lokal erhalten.

### Commitvorschlag

Ein Commit für die Datenreparatur und die Modellarbeit, ein zweiter für
die Registryhärtung. Alternativ ein einziger Commit, weil die Blöcke
aufeinander aufbauen:

```
feat: repair national profile path and add league strength stage

V2-C13 bis V2-C15.

C13 schliesst den nationalen PIT-Profilpfad an alle 23 vorhandenen
Ligen an. Die Daten lagen seit C2B lokal vor, wurden aber nur an
dieser einen Stelle nicht gelesen. cl_history_pit faellt von 321 auf
0 Teamseiten, der Testbestand waechst von 213 auf 283.

C14 misst nach und lehnt ab. Die Ursache ist belegt: Die 16 Merkmale
sind Verhaeltniswerte zur eigenen Liga und tragen keine Ligastaerke.

C15 fuegt eine zweite Modellstufe hinzu, die die Ligastaerke
ausschliesslich aus frueheren Champions-League-Begegnungen schaetzt.
Ergebnis auf 283 Testspielen: LogLoss -0,095 gegen V0, Intervall
[-0,1312; -0,0573], beide Folds besser, die beiden C14-Schadenssegmente
repariert. Zehn von elf Gates erfuellt; home_origin_league:PD
ueberschreitet die Segmentschwelle knapp, deshalb Verdict rejected und
keine Aktivierung.

Zusaetzlich drei Technikreparaturen: der C11-Vertragsfingerprint ist
jetzt zustandsfrei, der Accepted-Freigabeweg ist gebaut und
transaktional abgesichert, und der Rollback laeuft ueber einen
gesicherten Vorzustand statt ueber eine Behauptung.
```

### Deployment-Checkliste

1. `git status --short` prüfen, nur die oben genannten Dateien stagen
2. `git diff --check` erneut ausführen
3. Vollständige Testsuite laufen lassen und mit
   `2 failed, 5533 passed, 128 skipped, 91 errors` vergleichen
4. Auf dem VPS: `python run_ml.py --evaluate-c15` reproduzieren und den
   Result-Fingerprint `9f5bd654...` vergleichen
5. `python run_ml.py --release-c15 dry-run` muss `refused` liefern
6. Prüfen, dass `data/ml/model_registry.json` kein aktives Modell führt
7. Prüfen, dass die API `applied: false` mit Fallbackgrund meldet
8. Deployment ist ein reines Code-Deployment ohne Modellaktivierung

---

## L. Ehrliches Endergebnis

**V2 REJECTED, NOT READY FOR ACTIVE RELEASE**

---

## Erklärung in einfacher Sprache

**Ist C15 besser als V0?** Ja, deutlich. Der Log Loss fällt von 1,028
auf 0,933. Das Konfidenzintervall schließt die Null klar aus.

**Ist C15 besser als C14 und die bisherige V1?** Ja. C14 lag bei
−0,0116 gegen V0, C15 bei −0,0951. Das ist rund das Achtfache.

**Wie groß ist die Verbesserung?** −0,095 Log Loss, −0,069 Brier,
−0,033 RPS. In 66,4 Prozent aller Einzelspiele ist der Verlust
geringer.

**Ist die Richtung in beiden Folds besser?** Ja, erstmals: −0,066 und
−0,125. In C14 war ein Fold noch schlechter als V0.

**Schließt das Konfidenzintervall null aus?** Ja: [−0,1312; −0,0573].

**Gibt es weiterhin eine große beschädigte Mannschaftsgruppe?** Eine,
knapp: spanische Heimteams, 36 Spiele, +0,01186 gegen eine Schwelle von
0,01. Die beiden Gruppen, an denen C14 scheiterte, sind repariert und
verbessern sich jetzt um −0,195 und −0,214.

**Ist V2 als Active registriert?** Nein. Es gibt kein aktives Modell.

**Wird V2 im normalen ML-Modus angewendet?** Nein. Die Registry führt
kein aktives Modell, also antwortet die Anwendung mit V0 und meldet
ehrlich `applied: false`.

**Was passiert bei einem technischen ML-Ausfall?** V0 übernimmt. Dieser
Fallback ist unverändert wirksam und war es die ganze Zeit.

**Bleibt der individuelle Regler-Modus getrennt?** Ja, vollständig. Er
lädt kein Modell, und die Ligasimulation enthält keinen Verweis auf
`src.ml`.

**Kann der Stand nach Prüfung auf GitHub gepusht werden?** Ja. Der Code
ist konsistent, getestet und ohne neue Regressionen. Nichts wurde
gestaged oder committet, das übernimmt Elie.

**Kann V2 anschließend produktiv auf dem VPS laufen?** Der Code ja, das
Modell nein. Ein Deployment würde ausschließlich Code ausliefern; die
Nutzerantwort bliebe V0, weil kein Modell freigegeben ist.

**Welche manuellen Schritte fehlen vor dem Deployment?** Stagen,
committen, pushen und deployen. Eine Modellaktivierung ist nicht
möglich und wäre ohne ein `accepted`-Urteil auch nicht zulässig.
