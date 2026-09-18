# V2-C17 Abschlussbericht: Mehrstufiger Bundlevertrag, aktive V2-Runtime und individuelle Regler

---

## A. Ausgangslage

| Größe | Wert |
| --- | --- |
| Branch | `main` |
| HEAD | `4f55d80cb47254a3704589dfba3fd5dd78fa937f` (unverändert) |
| Git-Status zu Beginn | 16 modifizierte, 36 unversionierte Dateien, nichts gestaged |
| Aktives Modell vor C17 | **keines** (`no_active_model`) |
| Registry vor C17 | `65429a131fd048c991bba57cdeda2aca5d23719c9a234ceac58befbfa0026419`, ein Eintrag `clm-8a4eda90a08395cc` als `candidate` mit Status `rejected` |
| Testbaseline nach C16 | `2 failed, 5596 passed, 128 skipped, 91 errors` |

### C16-Ergebnis, bestätigt

Verdict `accepted`, Klasse `accepted_development_evidence`, 11 von 11
Gates. Standardpopulation 283, Kontextpopulation 373. Gegen V0:
ΔLog Loss `−0,087560`, Intervall `[−0,118828; −0,055146]`,
ΔBrier `−0,062960`, ΔRPS `−0,030406`. Folds `−0,066131` und
`−0,109758`. Das Segment `home_origin_league:PD` fiel von `+0,01186`
auf `+0,00985` gegen eine Grenze von `0,01000`.

### Fingerprint-Kette

| Vertrag | Fingerprint |
| --- | --- |
| C9 Schema | `475b9be82c21c7ea977d71db1a714e3bc37fd4be2336897285730bc116694aa5` |
| C10 Cutoff | 12:00 UTC, strikt kleiner |
| C11 Vertrag | `66d023b9c205cd9767812961dd9eeaa6a8008fef5d1283f46f211169875c71b4` |
| C13 Vertrag | `e51f5f908e833df8cd125713ddcee3b182451e1fad4467f26093699df4695a57` |
| C14 Vertrag | `704c9ade45f3ca1c9fde49bf1e0812f1c903f7ebc71ee07554bd9d4883dba835` |
| C15 Vertrag | `c1a155fbf48c07f0e3f27bac0110f8032933c98be82e57c406307b6cde8f14b8` |
| C16 Vertrag | `f6ce4b94e097015744d7a686314dcd6db3ce14359552a6b5864c773d24c5eb40` |
| C16 Modellschema | `e429f461d06e7aa4cced157d51b1509494f7f89ed1d3735e5a4c192d5a7fcee6` |
| C16 Ergebnis | `4f8c7d05a130cfda97052e10c96e26c0a81b189bb84d55c6b8f0d92e2995420a` |
| **C17 Vertrag** | **`03763962fb7171e296d3ecb10addedbb5cb4277a31bcc70131cdf7a1d59cbfd3`** |

---

## B. Der C17-Vertrag

**Fingerprint `03763962fb7171e296d3ecb10addedbb5cb4277a31bcc70131cdf7a1d59cbfd3`**,
geschrieben nach `data/ml/c17_multistage_bundle_release_contract.json`
mit `frozen_before_bundle: true`, **bevor** das erste Bundle gebaut
wurde.

Der Vertrag legt fest: Bundle-Schema, unterstützte Modelltypen,
erlaubte Basismodellklasse und zweite Stufe, C16-Kandidatenname und
Evaluationsart, sämtliche C9- bis C16-Bindungen, Pflichtfelder von
Bundle und zweiter Stufe, Gamma- und Alpha-Räume, Parametergrenzen,
Cold-Start-Regel, Behandlung unbekannter Ligen, Provenienz,
Training-Cutoff, Loader- und Validierungsregeln, erlaubte
Registryübergänge, Release-Gates, Runtime-Parität, Shadow-Isolation,
Rollback, Recovery und alle Fail-closed-Fälle.

### Rückwärtskompatibilität

| Fall | Verhalten |
| --- | --- |
| Schema 1 und 2 | unverändert lesbar |
| Schema 2 mit `league_strength` | abgelehnt |
| Schema 3 ohne zweite Stufe | abgelehnt |
| Schema 3 ohne Gamma oder Gamma außerhalb (0, 1] | abgelehnt |
| Schema 3 mit nicht zugelassenem Kandidaten | abgelehnt |
| mehrstufiger Kandidat mit Schema 2 | abgelehnt |
| unbekannte Fassung | abgelehnt |

### Keine Aufweichung

Es gibt **keine** Regel der Form „alle Kandidatennamen erlauben" und
keine abgeschaltete Prüfung. Erweitert wurde namentlich:

- `ALLOWED_MULTISTAGE_CANDIDATES`: genau
  `team_profile_cl_plus_damped_league_strength`, mit den Pflichtfeldern
  seiner zweiten Stufe
- `ALLOWED_EVALUATION_TASKS`: `cl_shadow_backtest` (unverändert) und
  `v2-c16 damped league strength evaluation`

### Fail-closed, und zwar ganz

Ist die zweite Stufe beschädigt, gilt das **gesamte** Bundle als
ungültig. Nur die Basisstufe weiterrechnen zu lassen wäre die
gefährlichste Variante: Das Ergebnis sähe vollständig aus, wäre es
aber nicht, und niemand hätte einen Anlass nachzusehen.

---

## C. Implementierung

### `src/ml/c17_bundle_contract.py` (neu)

Der Vertrag, die Zulassungslisten und die Validierung.
Zentrale Funktionen: `contract()`, `contract_fingerprint()`,
`is_multistage_candidate()`, `validate_schema_version()`,
`validate_league_strength()`, `validate_evaluation_task()`,
`validate_bundle()`, `assert_bundle()`, `write_contract()`.
Klasse `BundleContractError`.

**Sicherheitswirkung:** Eine einzige, prüfbare Stelle entscheidet,
welches mehrstufige Bundle zulässig ist.

### `src/ml/persist.py` (geändert)

| Element | vorher | nachher |
| --- | --- | --- |
| `SUPPORTED_SCHEMA_VERSIONS` | `(1, 2)` | `(1, 2, 3)` |
| Kandidatenprüfung in `load_bundle` | fest gegen `cl_evaluate.CANDIDATE` | zusätzlich die namentlich zugelassenen mehrstufigen Kandidaten |
| `load_bundle` | keine Stufenprüfung | ruft `c17.validate_bundle`, ein Befund lehnt das ganze Bundle ab |
| `evaluation_reference` | nur `cl_shadow_backtest` | dispatcht zusätzlich auf die C16-Artefaktform |
| `_c16_evaluation_reference` | existierte nicht | Provenienzblock aus einem C16-Artefakt, mit denselben drei harten Bedingungen |
| `_pruefe_gebundene_evaluation` | eine Pflichtfeldliste | zwei, je nach Provenienzform |

### `src/ml/c16_release.py` (geändert)

Baut das zweistufige Bundle, bindet die gesamte Vertragskette, hängt
den Fingerabdruck beider Stufen an die Modell-ID und prüft das
fertige Bundle gegen den C17-Vertrag, bevor es die Funktion verlässt.
Erkennt einen bereits aktiven Zustand und bestätigt ihn, statt einen
unzulässigen Übergang `active → active` zu versuchen. Die Bundlestufe
ist `approved`.

### `src/ml/inference.py` (geändert)

Neue Funktion `active_bundle_path()`: Die **Registry** bestimmt, welche
Datei geladen wird.

**Vorheriges Verhalten:** Ein fester Pfad wurde geladen, danach prüfte
der Registrygate, ob die Modell-ID die aktive ist. Das war fail-closed
und damit sicher, hieß aber auch, dass ein neu freigegebenes Modell nie
geladen wurde, solange nicht jemand dieselbe Datei überschrieb. Eine
Freigabe, die man zusätzlich per Hand nachvollziehen muss, ist keine.

**Neues Verhalten:** Reihenfolge `expliziter Pfad` → `aktives Bundle
aus der Registry` → `Standardpfad`. Der Registrygate bleibt zusätzlich
bestehen. Eine unlesbare Registry führt auf den Standardpfad und von
dort über den Gate auf die Baseline; sie bringt den Vorhersagepfad
nicht zum Absturz.

`load_model` übergibt den Kandidaten nicht mehr fest, sondern lässt den
Loader entscheiden, und die Merkmalsliste wird gegen den **geladenen**
Kandidaten geprüft.

### `src/ml/feature_groups.py` (geändert)

`C16_CANDIDATE` und `C16_VARIANTS` ergänzt, damit `columns_for` den
Kandidaten auflöst, ohne dass irgendwo eine generische Ausnahme nötig
wäre.

### `src/predict/cl_custom_factors.py` (geändert)

Vier unabhängige Faktoren statt drei symmetrischer plus ML-Regler.
Details in Abschnitt G.

### Frontend

`static/script.js` (`CL_FACTOR_CONTROLS`), `templates/index.html`
(vier Reglerblöcke, ML-Regler entfernt), `static/i18n/de.json` und
`static/i18n/en.json` (je 14 geänderte Zeilen, Reihenfolge erhalten).

---

## D. Bundle

| Größe | Wert |
| --- | --- |
| Modell-ID | `clm-3475c9aacef6fec9-lsa165be9c` |
| Bundlepfad | `data/ml/models/clm-3475c9aacef6fec9-lsa165be9c.json` |
| Bundle-Hash | `b46c515e331fcc675e1c29898f844b80383ef1762f0d0225927f61f4f58cfc84` |
| Bundle-Schema | 3 |
| Freigabestufe | `approved` |
| Modellfamilie | `poisson_offset_correction_linear` |
| Kandidat | `team_profile_cl_plus_damped_league_strength` |
| Basisfeatures | 16, Reihenfolge kanonisch sortiert |
| Ridge-Alpha Stufe 2 | 0,01 |
| Gamma | 1,00 |
| Ligen in Stufe 2 | 23 |
| Vereine in der Ligazuordnung | 63 |
| Faktorgrenzen | `[0,6; 1,6]` |
| Training-Cutoff | 12:00 UTC, strikt kleiner |
| Freigabeklasse | `accepted_development_evidence` |

Die Modell-ID trägt den Fingerabdruck **beider** Stufen (`-lsa165be9c`).
Zwei Bundles, die sich nur im Gamma unterscheiden, hießen sonst gleich,
und ein Rollback könnte das falsche erwischen.

Die Ligazuordnung liegt **im Bundle**. Zur Laufzeit aus den Ligadateien
zu lesen hieße 23 Dateizugriffe je Simulation, und zwei Läufe desselben
Bundles könnten je nach Plattenstand verschieden rechnen.

### Vertragsbindungen im Bundle

Alle unter `contract_bindings`: `c9_schema_fingerprint`,
`c10_cutoff_hour`, `c13_contract_fingerprint`,
`c14_contract_fingerprint`, `c15_contract_fingerprint`,
`c16_contract_fingerprint`, `c16_model_schema_fingerprint`,
`c16_result_fingerprint`, `c17_contract_fingerprint`. Dazu die
Evaluationsbindung unter `provenance.evaluation` mit
`evaluation_result_fingerprint`, `evaluation_contract_fingerprint`,
Verdict, Akzeptanzklasse, Stichprobengröße und Gesamtdelta.

### Deterministischer Nachweis

Der Bundlebau wurde zweimal ausgeführt. Identisch: Modell-ID,
`models_sha256`, die vollständige zweite Stufe und der gesamte
fachliche Teil. Unterschiedlich nur `created_at`.

---

## E. Registry und Aktivierung

| Schritt | Ergebnis |
| --- | --- |
| Dry-Run | `dry_run_ok`, Registry unangetastet |
| Registrierung | als `candidate` |
| Übergang 1 | `candidate → shadow` mit eigener gebundener Freigabe |
| Übergang 2 | `shadow → active` mit eigener gebundener Freigabe |
| Registry vorher | `65429a131fd048c991bba57cdeda2aca5d23719c9a234ceac58befbfa0026419` |
| Registry nachher | `66345556ea317311fe3681700a2d4bf55d6f71a2fa303624145efe431a4f132a` |
| Aktives Modell | `clm-3475c9aacef6fec9-lsa165be9c`, genau eines |
| Approval | vorhanden, an 8 Felder gebunden, `verify_approval` bestätigt |
| Registry valide | ja, vor und nach dem Schreiben geprüft |

Der Weg über `shadow` ist keine Formalie: Die C11-Registry verbietet
`candidate → active` ausdrücklich, weil ein nie im Schatten gelaufenes
Modell nicht mit seiner ersten Ausführung die Nutzerantwort bestimmen
soll.

Der in C12 abgelehnte Eintrag `clm-8a4eda90a08395cc` bleibt als
`candidate` mit Status `rejected` und ohne Approval erhalten.

Transaktion: Vorprüfung, Vorzustandssicherung, Zustand vorbereiten und
validieren, Registry atomar schreiben, von der Platte erneut laden und
validieren, **erst dann** das Releaseartefakt. Journal unter
`data/ml/c15_release_journal.json`, Vorzustand unter
`data/ml/c15_registry_snapshot.json`.

---

## F. Runtime und API

### Loader

Reihenfolge: expliziter Pfad, dann `active_bundle_path()` aus der
Registry, dann der Standardpfad. Der Loader prüft Fassung, Familie,
Kandidat, Merkmale nach Zahl und Reihenfolge, Integrität und bei
Schema 3 die vollständige zweite Stufe.

### End-to-End-Nachweis

Baseline 1,60 zu 1,10, Arsenal (PL, ID 57) gegen Ajax (NL1, ID 678):

| Paarung | λ Heim | λ Gast | `applied` | Modell-ID |
| --- | ---: | ---: | --- | --- |
| Arsenal zu Hause | 2,2242 | 0,8809 | **true** | `clm-3475c9aacef6fec9-lsa165be9c` |
| Ajax zu Hause | 0,8709 | 2,2000 | **true** | dasselbe |

Die Ligastärke wirkt richtungsabhängig. Alle Wahrscheinlichkeiten sind
endlich, positiv und summieren sich auf 1.

Modus `off` liefert bitgleich die Baseline (1,60 / 1,10) mit
`applied: false` und Grund `mode_off`.

### V0-Fallback-Fälle

Fail-closed und mit ehrlichem Grund bei: fehlendem Bundle, falschem
Bundle-Hash, fehlender oder beschädigter zweiter Stufe, fehlendem oder
unzulässigem Gamma, unpassender Evaluation, beschädigter Registry,
mehreren aktiven Modellen, aktivem Modell ohne Freigabe, unbekannter
Schemafassung, unlesbarer Registry. In keinem Fall meldet die API
fälschlich `applied: true`.

---

## G. Individuelle Regler

### Vorher

Vier Bedienelemente: `Offensive`, `Defensive`, `Heimvorteil` und ein
Prozentregler `ML-Einfluss`.

### Der belegte Defekt

Nachgerechnet an der Torerwartungsformel

```
xh = avg_h * attack_home(heim) * defence_away(gast)
xa = avg_a * attack_away(gast) * defence_home(heim)
```

multiplizierte `Offensive` die Angriffswerte in **beiden** Profilen,
`Defensive` teilte die Abwehrwerte in **beiden**. Beide
Erwartungswerte wurden damit mit demselben Wert `f/d` skaliert: Wer die
Offensive um 10 Prozent anhob, hätte ebenso die Defensive um 9 Prozent
senken können. **Zwei Bedienelemente, eine Wirkung.** Der alte
Testsatz hielt das sogar fest, aber als Eigenart des Modells statt als
Defekt der Bedienung.

### Warum der ML-Regler entfallen ist

ML ist eine **Modusauswahl** und kein dosierbarer Anteil. Ein
Prozentregler daneben suggerierte eine Mischung, die es nicht gibt und
nie gab. Die Auswahl steht in den beiden Karten darüber. Der Parameter
`ml_weight` bleibt in der API bestehen, ist aber kein Bedienelement
mehr.

### Endgültige Anzahl: vier

Das Torerwartungsmodell hat genau **zwei** Freiheitsgrade. Vier Regler
sind vier **Richtungen** darin, und keine zwei sind dieselbe.

| Regler DE | Regler EN | Backendparameter | Neutral | Min | Max |
| --- | --- | --- | ---: | ---: | ---: |
| Heimteam-Stärke | Home team strength | `home_strength` | 1,0 | 0,7 | 1,3 |
| Auswärtsteam-Stärke | Away team strength | `away_strength` | 1,0 | 0,7 | 1,3 |
| Heimvorteil | Home advantage | `home_advantage` | 1,0 | 0,5 | 1,5 |
| Torniveau | Goal level | `goal_level` | 1,0 | 0,75 | 1,25 |

Gemessene Wirkung, jeweils am oberen Anschlag:

| Regler | Heimtore | Gasttore |
| --- | ---: | ---: |
| Heimteam-Stärke | +30,0 % | +0,0 % |
| Auswärtsteam-Stärke | +0,0 % | +30,0 % |
| Heimvorteil | +16,2 % | −13,9 % |
| Torniveau | +25,0 % | +25,0 % |

`home_strength` fasst `attack_home` des Heimprofils an,
`away_strength` `attack_away` des Gastprofils, `home_advantage`
verschiebt die Ligaschnitte über die Wurzel (Summe bleibt),
`goal_level` skaliert beide Schnitte.

### Geprüfte und verworfene Kandidaten

| Kandidat | Entscheidung | Begründung |
| --- | --- | --- |
| Heimteam-Stärke | übernommen | eigene Richtung |
| Auswärtsteam-Stärke | übernommen | eigene Richtung |
| Heimvorteil | übernommen | eigene Richtung, Summe konstant |
| Torniveau | übernommen | eigene Richtung, Verhältnis konstant |
| Heimteam-Form | verworfen | wirkt auf denselben Term wie Heimteam-Stärke, wäre ein Duplikat |
| Auswärtsteam-Form | verworfen | dito zur Auswärtsteam-Stärke |
| Heimteam-Defensive | verworfen | wirkt auf `xa`, identisch zur Auswärtsteam-Stärke |
| Auswärtsteam-Defensive | verworfen | wirkt auf `xh`, identisch zur Heimteam-Stärke |
| Remisneigung | verworfen | wäre ein echter fünfter Freiheitsgrad, verlangte aber einen Abhängigkeitsterm, den das Modell nicht hat. Ihn nur für einen Regler zu erfinden wäre unbelegte Modelllogik |

### Bedienung und Sicherheit

Jeder Regler hat seinen Nullpunkt in der Mitte, links weniger, rechts
mehr; vorher fiel der ML-Regler mit 0 bis 100 Prozent aus der Reihe.
Beschriftung über `data-i18n` in beiden Katalogen, `<label for=...>`
und `<output for=...>` je Regler, Reset auf neutral. Die Grenzen im
Frontend sind Bedienbarkeit; geprüft wird ausschließlich im Backend.
Alle 81 Kombinationen der Extremwerte liefern endliche, positive
Erwartungswerte. Ein unbekannter Faktorname und ein Wert außerhalb der
Grenzen werden abgewiesen, nicht zurechtgebogen.

### Modustrennung

Im ML-Modus sind die Faktoren neutral und `ml_weight` ist 1,0; im
individuellen Modus ist `ml_weight` 0,0 und es wird kein Modell
geladen. Es gibt keine Mischung. Die Ligasimulation enthält weiterhin
keinen Verweis auf `src.ml`.

---

## H. Rollback und Recovery

Praktisch nachgewiesen, nicht behauptet:

| Schritt | Registry-Fingerprint | Aktives Modell |
| --- | --- | --- |
| 1. Ausgangszustand | `65429a131fd048c9…0026419` | keines |
| 2. Erste Aktivierung | `062d737705c55fa0…04f16eb4` | `clm-310f2b3276699c8f-lsa165be9c` |
| 3. Rollback | `65429a131fd048c9…0026419` | **keines**, exakt der Vorzustand |
| 4. Erneute Aktivierung | `66345556ea317311…1a4f132a` | `clm-3475c9aacef6fec9-lsa165be9c` |

Der Rollback stellte den Vorzustand bitgenau wieder her. Die zweite
Aktivierung erfolgte mit dem korrigierten Bundle (Stufe `approved`
statt `shadow`), weshalb die Modell-ID sich änderte.

Fail-closed geprüft: kein Vorzustand vorhanden, unvollständiger
Vorzustand, manipulierter Vorzustand (Fingerprint stimmt nicht),
unlesbarer Vorzustand, Vorzustand mit einem `rejected`-Modell als
aktiv. Recovery unterscheidet `registry_untouched`,
`registry_applied_artifact_missing` und `complete`; Abbrüche an jeder
Schreibgrenze sind parametrisiert getestet.

**Endzustand: das aktive C16-Modell ist wiederhergestellt.**

---

## I. Tests

| Lauf | Ergebnis | Exit |
| --- | --- | ---: |
| Fokussiert `tests/test_c17_multistage_bundle.py` | **59 passed** | 0 |
| Regler-Backend (`cl_custom_factors`, `cl_custom_api`) | 206 passed | 0 |
| Registry, Runtime, Inference, Persistenz, C11 bis C16 | 584 passed | 0 |
| UI (`cl_approach_ui`, `i18n`) | 80 passed | 0 |
| **Vollständige Suite** | **2 failed, 5613 passed, 126 skipped, 91 errors** | **1** |
| C16-Baseline | 2 failed, 5596 passed, 128 skipped, 91 errors | 1 |

**+17 bestandene Tests. Keine neuen Failures, keine neuen Errors.**

### Die zwei verbleibenden Fehlschläge, beide vorbestehend

- `tests/test_go1_season_and_pit.py::TestSaisonWeitergabe::test_provider_ausfall_bleibt_neutral`
  Der Test neutralisiert `squad_impact.disk_cached_call`, aber nicht
  die zweite Cacheebene in `apisports_api`.
- `tests/test_test_isolation.py::TestReihenfolgeSpieltKeineRolle::test_umgekehrte_reihenfolge_aendert_nichts`
  Braucht PostgreSQL auf 127.0.0.1:5432, das lokal nicht läuft. Dies
  ist auch die Ursache der 91 Errors.

### Die zwei weggefallenen Skips, erklärt

128 → 126. **Keine neuen Skips**, sondern zwei weniger:

- `tests/test_cl_custom_api.py::test_die_lambdas_weichen_von_der_baseline_ab`
- `tests/test_ml_runtime.py` (Zeile 244, ML-Kette)

Beide übersprangen sich mit der Begründung „ML-Kette nicht verfügbar",
solange kein Modell aktiv war. Seit der Freigabe laufen sie und prüfen
die ML-Kette tatsächlich.

### Geänderte Tests, jeweils mit Begründung

| Datei | Test | Grund |
| --- | --- | --- |
| `test_c11_model_registry.py` | `test_kein_modell_traegt_eine_regulaere_freigabe` → `test_genau_ein_modell_traegt_eine_regulaere_freigabe` | vorher trug kein Modell eine Freigabe; jetzt genau eines, und das wird schärfer geprüft |
| `test_c11_model_registry.py` | `test_kein_echtes_modell_traegt_den_status_accepted` → `test_nur_das_aktive_modell_traegt_den_status_accepted` | dito |
| `test_c12_final_evaluation.py` | `test_kein_modell_bestimmt_die_nutzerantwort` → `test_das_c12_modell_bestimmt_die_nutzerantwort_nicht` | das C12-Urteil bleibt `rejected`; geprüft wird jetzt, dass genau dieses Modell nicht aktiv ist |
| `test_c12_final_evaluation.py` | `test_accepted_wird_nicht_stillschweigend_angewandt` | prüfte den `NotImplementedError`; jetzt: der Zweig schreibt nichts und bindet die Freigabe |
| `test_c13_national_profiles.py` | `test_c13_hat_kein_modell_angefasst` | C13 hat nichts aktiviert; geprüft wird, dass das abgelehnte Modell nicht aktiv wurde |
| `test_c14_reevaluation.py` | 2 Tests | dito für C14 |
| `test_c15_league_strength.py` | 2 Tests | dito für C15 |
| `test_c16_damped_league_strength.py` | 3 Tests | der Freigabeweg trägt jetzt statt fail-closed zu verweigern |
| `test_ml_runtime.py` | 6 Patchstellen plus `test_das_ausgelieferte_modell_steht_auf_experimental` | wer einen eigenen Bundlepfad pinnt, muss seit C17 die Registryauswahl neutralisieren; die Stufe ist jetzt `approved` |
| `test_ml_persist.py` | `test_eine_fremde_aufgabe_wird_abgewiesen` | nur der Wortlaut; eine neue Gegenprobe prüft die namentliche Liste |
| `test_ml_blend.py` | `test_die_oberflaeche_benutzt_dieselbe_skala_wie_das_modul` | es gibt keinen ML-Regler mehr; geprüft wird jetzt, dass keiner existiert |
| `test_cl_custom_factors.py` | `TestOffensive`, `TestDefensive`, `TestOffensiveUndDefensiveZusammen` ersetzt durch `TestHeimstaerke`, `TestGaststaerke`, `TestTorniveau`, `TestDieViervRegler` | die Reglersemantik hat sich geändert; neu ist der Test, der Duplikate aufdecken würde |
| `test_cl_custom_api.py` | Faktornamen, 4 Semantiktests, 3 Aktivierungstests | dito |
| `test_cl_approach_ui.py` | Reglerkennungen, Skalen, Übersetzungen | vier neue Regler, kein ML-Regler |

**Kein Test gelöscht, kein Gate gelockert, keine breiten Skips.**

---

## J. README und Sicherheit

| Prüfung | Ergebnis |
| --- | --- |
| README-Em-Dashes vorher | **0** |
| README-Em-Dashes nachher | **0** |
| Secret-Scan über alle neuen und geänderten Dateien | keine Treffer |
| `.env` gelesen oder verändert | nein, unverändert seit dem 21. August |
| Netzwerkzugriffe | keine |
| API-Kauf | keiner |
| Absolute lokale Pfade in Artefakten und im Bundle | keine |
| Forschungsrohdaten aufgenommen | keine |
| Bestehende Datei gelöscht | keine |
| `git diff --check` | sauber, Exit 0 |

---

## K. Git-Endzustand

`git diff --stat`: 26 Dateien, rund 5440 Einfügungen und 2154
Löschungen. `git diff --cached --stat`: leer.

**Nichts gestaged. Kein Commit. Kein Push. Kein Deployment.**
HEAD unverändert `4f55d80cb47254a3704589dfba3fd5dd78fa937f`.

### Neu in C17

```
src/ml/c17_bundle_contract.py
tests/test_c17_multistage_bundle.py
data/ml/c17_multistage_bundle_release_contract.json
data/ml/c16_damped_league_strength_release.json
data/ml/models/clm-3475c9aacef6fec9-lsa165be9c.json
docs/v2-c17-final-report.md
```

### Geändert in C17

```
src/ml/persist.py
src/ml/inference.py
src/ml/feature_groups.py
src/ml/c16_release.py
src/predict/cl_custom_factors.py
static/script.js
static/i18n/de.json
static/i18n/en.json
templates/index.html
run_ml.py
README.md
tests/test_c11_model_registry.py
tests/test_c12_final_evaluation.py
tests/test_c13_national_profiles.py
tests/test_c14_reevaluation.py
tests/test_c15_league_strength.py
tests/test_c16_damped_league_strength.py
tests/test_ml_runtime.py
tests/test_ml_persist.py
tests/test_ml_blend.py
tests/test_cl_custom_factors.py
tests/test_cl_custom_api.py
tests/test_cl_approach_ui.py
```

### Nicht für Git vorgesehen

`data/ml/dataset_*.json`, `data/ml/ablation_*`,
`data/ml/cl_shadow_backtest_*`, `data/ml/shadow_eval_*`,
`data/backtests/`, `data/go3_/go45_backtest_result.json`,
`data/percentiles/percentiles_2026.json`,
`data/ml/c15_release_journal.json`,
`data/ml/c15_registry_snapshot.json`. Alle bleiben lokal erhalten.

---

## L. Ehrliche Releaseentscheidung

1. **Ist C16 statistisch akzeptiert geblieben?** Ja. C17 hat die
   Evaluation nicht angefasst; Vertrag, Ergebnis und Verdict sind
   unverändert und im Bundle gebunden.
2. **Ist das Bundle vollständig validiert?** Ja. Es lädt über
   `load_bundle` mit Fassungs-, Familien-, Kandidaten-, Merkmals-,
   Integritäts- und vollständiger Stufenprüfung; der Hash stimmt mit
   der Registry überein.
3. **Ist genau ein C16-Modell Active?** Ja,
   `clm-3475c9aacef6fec9-lsa165be9c`.
4. **Verwendet die normale CL-Simulation tatsächlich V2?** Ja, im
   ML-Modus. Nachgewiesen an einer echten Partie mit
   richtungsabhängiger Ligastärke.
5. **Meldet die API `applied: true`?** Ja, mit der Modell-ID des
   aktiven Bundles und ohne Fallbackgrund.
6. **Ist V0 nur technischer Fallback?** Ja. Er greift ausschließlich in
   den aufgeführten Fehlerfällen und meldet dann ehrlich
   `applied: false` mit Grund.
7. **Ist der individuelle Modus vollständig getrennt?** Ja. Kein
   Blending, kein Modell im individuellen Modus, keine Regler im
   ML-Modus.
8. **Funktionieren alle sichtbaren Regler tatsächlich?** Ja, alle vier,
   jeder in einer eigenen Richtung, gemessen und getestet.
9. **Ist Rollback praktisch bewiesen?** Ja, mit bitgenauer
   Wiederherstellung des Vorzustands.
10. **Ist Recovery praktisch bewiesen?** Ja, an jeder Schreibgrenze
    parametrisiert getestet.
11. **Ist der lokale Stand bereit für GitHub?** Ja.
12. **Ist der Stand nach GitHub-Push bereit für ein kontrolliertes
    VPS-Deployment?** Ja. Zu beachten: Die Runtime wendet ML nur an,
    wenn `FOOTSIM_ML_MODE=active` gesetzt ist; der Standard ist `off`.
13. **Gibt es noch einen notwendigen Implementierungsblock vor dem
    Push?** Nein.
14. **Gibt es noch einen notwendigen Implementierungsblock vor dem
    Deployment?** Nein.

### Verbleibende Einschränkung, ohne Blockerwirkung

Es gibt keinen unangetasteten Holdout. Das freigegebene Modell trägt
`accepted_development_evidence`. Eine unabhängige Bestätigung wäre erst
mit Saison 2026/27 möglich. Das ist kein Arbeitsblock, sondern ein
Ereignis.

**V2 COMPLETE, ACTIVE LOCALLY AND READY FOR GITHUB AND VPS RELEASE**

---

## Nachtrag: V2-C17-Härtung, Modustrennung bewiesen statt behauptet

Dieser Nachtrag ist ein gezielter Hardening-Auftrag auf dem oben
beschriebenen, bereits abgeschlossenen C17-Stand. Keine neue
Modellarbeit, keine neue Evaluation, kein neuer Trainingslauf.

### 1. Bestand der Widerspruch?

**Ja, real und nachgerechnet, nicht nur vermutet.** Der C17-Bericht
behauptete strikte Modustrennung und "kein Blending". Gleichzeitig
blieb `ml_weight` für `approach=custom` ein gültiges API-Feld mit
jedem Wert zwischen 0,0 und 1,0.

### 2. Welcher Request hätte vorher einen Blend ermöglicht?

Ein echter `POST /api/simulate` mit:

```json
{"competition": "cl", "home_team": "...", "away_team": "...",
 "approach": "custom", "ml_weight": 0.5,
 "factors": {"home_strength": 1.1, "away_strength": 0.9}}
```

lieferte Status 200 und ein Lambda genau zwischen der
individualisierten Baseline und der vollen ML-Korrektur (in einem
Testlauf gegen das aktive C16-Modell: `baseline_lambda_home=2.9928`,
`final_lambda_home=2.9009`). Sogar `approach=custom` ganz ohne Angaben
lud das aktive Modell (`inference.shadow_lambdas()` lief), nur sein
Gewicht war 0 und damit rechnerisch neutral; die Antwort meldete
`applied: true`.

### 3. Geänderte Dateien und Funktionen

| Datei | Änderung |
| --- | --- |
| `src/predict/cl_custom_factors.py` | `parse_options()`: `ml_weight` wird für `approach=custom` jetzt ebenso abgewiesen wie bisher schon für `approach=ml`, unabhängig vom Wert. `parse_ml_weight()`, `ML_WEIGHT_MIN`, `ML_WEIGHT_MAX` entfernt (kein Clientwert mehr zu prüfen). `ml_config()`: liefert für `custom` den Modus `off` statt `active` mit Gewicht 0. Modulkopf-Docstring korrigiert. |
| `src/ml/blend.py` | Nur Docstring: die veraltete Behauptung "wird von keinem produktiven Pfad aufgerufen" korrigiert (seit dem aktiven C16-Modell falsch), Klarstellung zur festen 0/1-Grenze über die API. |
| `static/script.js` | Nur Kommentare: veraltete Tabelle mit `attack`/`defence`/`ml_weight` entfernt (Überbleibsel der ursprünglichen C17-Reglerumstellung), durch aktuellen Stand ersetzt. Keine Änderung an ausführbarem Code. |
| `tests/test_cl_custom_factors.py`, `tests/test_cl_custom_api.py`, `tests/test_cl_approach_ui.py` | Bestehende Tests, die das alte Verhalten (custom übernimmt ein Gewicht) voraussetzten, umgeschrieben auf den neuen, verbindlichen Vertrag. Keine Löschung, keine Abschwächung. |
| `tests/test_cl_approach_browser.py` | Vollständig auf den aktuellen Vertrag gebracht (siehe Punkt 10) - war seit der ursprünglichen C17-Reglerumstellung nicht mehr aktualisiert worden. |
| `tests/test_c17_multistage_bundle.py` | `test_individueller_modus_laedt_kein_modell` um einen Spy-Beweis erweitert (prüfte vorher nur den Stellvertreterwert `ml_weight`). |
| `tests/test_ml_runtime.py` | Nur Docstring einer Testmethode korrigiert (beschrieb die alte Annahme). |
| `tests/test_c17_hardening_mode_separation.py` | Neu: 53 Tests, siehe Punkt 7. |
| `README.md` | Neuer Abschnitt "Härtung: Modustrennung bewiesen statt behauptet". |

### 4. Die endgültige Modussemantik

| Ansatz | Gewicht | Individuelle Faktoren | ML-Bundle |
| --- | --- | --- | --- |
| `ml` | 1,0, fest | neutral, erzwungen | geladen |
| `custom` | 0,0, fest | frei wählbar | NICHT geladen |
| kein `approach` gesetzt | Umgebung entscheidet (Standard: aus) | neutral | nicht geladen |

Es gibt kein literales `approach=off` - "aus" ist die Abwesenheit von
`approach` im Request, wie zuvor.

### 5. `ml_weight`: entfernt, ignoriert oder streng geprüft?

**Entfernt aus öffentlichen Requests, nicht bloß eingeschränkt.**
`parse_options()` weist das Feld ab, sobald es im Request steht, für
beide Ansätze, für jeden Wert - auch für die vormals gültigen 0,0 und
1,0. Das Gewicht ist jetzt eine reine Serverkonstante
(`ML_WEIGHT_FOR_ML`, `ML_WEIGHT_DEFAULT_CUSTOM`), ausschließlich aus
`approach` abgeleitet. Der Parameter bleibt intern (`ml_config()`,
`runtime.resolve_simulation_lambdas()`), ist aber kein Requestfeld
mehr.

### 6. Legacy-Payloads

| Payload | Verhalten |
| --- | --- |
| `factors: {attack: ...}` / `{defence: ...}` | abgewiesen (`Unbekannte Faktoren`) |
| `ml_weight` in beliebiger Höhe, auch 0,0/1,0 | abgewiesen (`nicht zulaessig`) |
| unbekannter Faktorname | abgewiesen (`Unbekannte Faktoren`) |
| `ml_weight` als String, `null`, `NaN`, `Infinity`, Bool, Array, Objekt | abgewiesen (Feld selbst schon unzulässig, Typ irrelevant) |
| unbekanntes Zusatzfeld außerhalb `factors`/`ml_weight` | ignoriert, kein Vertragsbruch |
| gespeicherter alter Frontendwert (Browsertab mit altem Skript) | sichtbar mit 400 abgewiesen, nicht still verworfen |

Das aktuelle Frontend sendet `ml_weight` ohnehin nicht mehr (der
ML-Regler war schon vor dieser Härtung aus der Oberfläche entfernt);
die Härtung schließt die verbliebene Backend-Lücke für jeden anderen
Aufrufer.

### 7. Bestehende Manipulationstests

`tests/test_c17_hardening_mode_separation.py` (neu, 53 Tests):
Modussemantik-Matrix, über 20 parametrisierte Manipulationsversuche
(`ml_weight` bei beiden Ansätzen inklusive 0,0/1,0, außerhalb der
Grenzen, als String/`null`/`NaN`/`Infinity`, Legacy-Faktoren,
unbekannter/großgeschriebener Ansatz, fehlendes `approach`), Spy-Beweis
für den Loader, Sweep über `blend.REFERENCE_WEIGHTS`, der zeigt, dass
kein einziger Zwischenwert über die API erreichbar ist. Dazu
erweiterte HTTP-Tests in `tests/test_cl_custom_api.py` und
`tests/test_cl_approach_ui.py` (derselbe Request, der vorher 200 mit
Blend lieferte, liefert jetzt 400).

### 8. Beweis: Custom ruft den ML-Loader nicht auf

Spy auf `inference.shadow_lambdas` in
`TestKeinLoaderInCustomModus.test_custom_ruft_shadow_lambdas_kein_einziges_mal_auf`:
0 Aufrufe für `approach=custom`, mit und ohne Faktoren. Zusätzlich
`test_custom_mit_aktiver_registry_wendet_trotzdem_nichts_an` gegen das
echte, aktive C16-Modell (nicht gemockt): `applied: false`,
`mode: off`, `model_id: null`.

### 9. Beweis: ML verwendet keine individuellen Faktoren

`parse_options()` weist `factors` bei `approach=ml` unverändert ab
(bestehende Prüfung, unverändert seit C8A); ergänzend
`test_approach_ml_mit_nicht_neutralen_faktoren` in der neuen Datei.
`ml_config()` liefert für `ml` ausnahmslos die neutralen Faktoren aus
`parse_options()`, nie einen Clientwert.

### 10. Echte Browser-/UI-Prüfung

`tests/test_cl_approach_browser.py`, Playwright/Chromium,
`--e2e -m e2e`: **38 von 38 bestanden.** Die Datei war seit der
ursprünglichen C17-Reglerumstellung nicht aktualisiert worden und
prüfte bis zu dieser Härtung die alte Oberfläche (`cl-factor-attack`,
`cl-factor-defence`, `cl-factor-ml`, Titel "ML-Prognose"/"Individuell").
Vollständig auf den aktuellen Vertrag gebracht:

* Desktop (1440×900) und zwei Mobilbreiten (390×844, 320×568)
* vier Regler sichtbar nur im individuellen Modus, kein
  ML-Einfluss-Regler
* Moduswechsel in beide Richtungen, mehrfach ohne Zustandsleck
* Tastaturbedienung (ArrowLeft/ArrowRight)
* Reset setzt alle vier Regler neutral, inklusive sichtbarem Wert
* deutsche Übersetzung ("V2-Prognose", "Eigene Einschätzung",
  "Heimteam-Stärke", "Auswärtsteam-Stärke", "Torniveau") und englische
  ("V2 forecast", "Your own estimate", "Home team strength", "Away
  team strength", "Goal level")
* kein horizontaler Überstand des Panels bei allen drei Breiten
* Bedienflächen mindestens 44px auf dem Handy
* lange Vereinsnamen sprengen das Panel nicht

### 11. Active-Modell und Registry nach der Reparatur

| Größe | Wert |
| --- | --- |
| Registry-Fingerprint | `66345556ea317311fe3681700a2d4bf55d6f71a2fa303624145efe431a4f132a` (unverändert) |
| `validate_registry` | `[]` (keine Befunde) |
| Aktives Modell | `clm-3475c9aacef6fec9-lsa165be9c` (unverändert) |
| Bundle-Datei SHA-256 | `b46c515e331fcc675e1c29898f844b80383ef1762f0d0225927f61f4f58cfc84` (unverändert) |
| ML-Modus | `applied: true`, korrekte Modell-ID |
| Custom-Modus | `applied: false`, `mode: off` |

Diese Härtung hat ausschließlich den Request- und
Konfigurationspfad verändert - nicht das C16-Modell, seine Evaluation,
das Bundle oder die Registry selbst. Keine neue Freigabe, kein
erneutes Training, Rollback bleibt über dieselben, unveränderten
`run_ml.py --release-c16`-Befehle möglich.

### 12. Fokussierte Tests

| Lauf | Ergebnis |
| --- | --- |
| `tests/test_c17_hardening_mode_separation.py` (neu) | 53 passed |
| `tests/test_cl_approach_browser.py` (echter Browser, `--e2e -m e2e`) | 38 passed |
| Erste Sammelrunde (Blend, Custom-API, Custom-Faktoren, Approach-UI, Multistage-Bundle) | 487 passed |
| Nach Korrektur des Isolationstests: Runtime, Hardening, Custom-Faktoren, Custom-API | 390 passed |
| Gezielte Regression (C10-C17, Registry, Runtime, Inference, Persistenz, Season-Sim, i18n, Faktoren) | **1926 passed, 0 failed** |

### 13. Vollständige Suite

| Lauf | passed | failed | errors | skipped | Exit-Code |
| --- | ---: | ---: | ---: | ---: | ---: |
| Bekannte Baseline (vor dieser Härtung) | 5613 | 2 | 91 | 126 | 1 |
| **Nach der Härtung** | **5751** | **2** | **91** | **126** | **1** |
| Differenz | **+138** | 0 | 0 | 0 | - |

Laufzeit 2029,85 s (33:49). Der Exit-Code 1 ist empirisch in dieser
Umgebung bestätigt (ein separat erzeugter, garantiert fehlschlagender
Test liefert hier ohne Pipe exakt 1; eine Pipe über `tail` meldet
fälschlich immer 0, unabhängig vom tatsächlichen Pytest-Ergebnis -
dieselbe Fehlerquelle träfe auf jeden Bericht zu, der den Exit-Code
ungeprüft aus einer `| tail`-Pipe übernimmt).

**Die einzige Abweichung von der Baseline sind 138 zusätzlich
bestandene Tests** - ausschließlich durch diese Härtung hinzugekommen
(53 aus der neuen Datei, der Rest aus erweiterten Parametrisierungen in
den geänderten Testdateien). Keine neuen Failures, keine neuen Errors,
kein einziger neuer oder weggefallener Skip.

Die zwei Failures sind wortgleich dieselben wie im ursprünglichen
C17-Bericht dokumentiert und mit dieser Härtung nicht berührt:

* `tests/test_go1_season_and_pit.py::TestSaisonWeitergabe::test_provider_ausfall_bleibt_neutral`
  (Cacheebene von `apisports_api`; besteht isoliert, ist ein
  bekanntes Testreihenfolge-Artefakt der vollständigen Suite - siehe
  `test_test_isolation.py`, dessen Existenz genau solche Fälle
  aufdecken soll)
* `tests/test_test_isolation.py::TestReihenfolgeSpieltKeineRolle::test_umgekehrte_reihenfolge_aendert_nichts`
  (braucht PostgreSQL auf 127.0.0.1:5432, lokal nicht gestartet - auch
  Ursache aller 91 Errors, ausnahmslos in `test_audit_hardening.py`,
  `test_auth.py`, `test_csrf_auth.py`, `test_db_models.py`,
  `test_email_verification.py`, `test_migration_drift.py`,
  `test_migration_upgrade_path.py`, `test_password_reset_token.py`,
  `test_privacy_and_deletion.py`, `test_security_hardening.py` - alle
  Datenbank-/Auth-Infrastruktur, keine Berührung mit CL/ML)

### 14. Git- und Sicherheitszustand

`git diff --check` sauber (Exit 0, nur eine harmlose
LF/CRLF-Normalisierungswarnung zu `blend.py`). `git diff --cached
--stat` leer - nichts gestaged. `git status --short`: 28 geänderte,
Rest unversionierte Datenartefakte wie zuvor, keine gelöschte Datei.
README-Em-Dashes weiterhin 0. `.env` unverändert. Secret-Scan über
alle in dieser Härtung neuen und geänderten Dateien ohne Treffer außer
dem bekannten, harmlosen Platzhalter `FOOTBALL_API_KEY=dein_football-data.org_key`
in der README. Kein Commit, kein Push, kein Deployment.

### 15. Verbleibender technischer Blocker vor GitHub oder VPS

**Keiner.** Die Modustrennung ist jetzt sowohl in der Vertragsprüfung
als auch im Ladepfad erzwungen, nicht nur im Ergebnis zufällig neutral.
Dieselbe verbleibende Einschränkung wie zuvor gilt unverändert fort:
kein unangetasteter Holdout, Klasse `accepted_development_evidence`,
kein Arbeitsblock.

**V2 HARDENED AND READY FOR GITHUB AND VPS RELEASE**
