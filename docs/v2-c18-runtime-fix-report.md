# V2-C18: Laufzeitreparatur, Paritätsnachweis und Ligazuordnungsdiagnose

Umsetzung von Fix 1, Fix 2 und Fix 3 aus dem forensischen Release-Blocker-Audit
der V2-Ligasimulation. Ziel war ausschließlich, das bereits evaluierte
C16-Modell technisch korrekt anzuwenden. Keine neue Modellsuche, keine
Änderung an Gamma, Alpha, Faktoren oder Akzeptanzgates, kein Neutraining,
kein neues Bundle, keine Registryänderung.

---

## A. Ausgangslage

| Größe | Wert |
| --- | --- |
| Branch | `main` |
| HEAD | `4f55d80cb47254a3704589dfba3fd5dd78fa937f` |
| Gestagte Änderungen | keine (`git diff --cached --stat` leer) |
| Einträge in `git status --short` | 80 |
| Runtime-Modus im Prozess | `off` (`FOOTSIM_ML_MODE` nicht gesetzt, `DEFAULT_MODE = off`) |
| Aktives Modell | `clm-3475c9aacef6fec9-lsa165be9c` |
| Registry-Fingerprint | `66345556ea317311fe3681700a2d4bf55d6f71a2fa303624145efe431a4f132a` |
| `validate_registry` | `[]` |
| Bundle SHA-256 | `b46c515e331fcc675e1c29898f844b80383ef1762f0d0225927f61f4f58cfc84` |
| Schema / Freigabestufe | 3 / `approved` |

Vertragsfingerprints im Bundle:

| Bindung | Wert |
| --- | --- |
| `c9_schema_fingerprint` | `475b9be82c21c7ea977d71db1a714e3bc37fd4be2336897285730bc116694aa5` |
| `c10_cutoff_hour` | `12` |
| `c13_contract_fingerprint` | `e51f5f908e833df8cd125713ddcee3b182451e1fad4467f26093699df4695a57` |
| `c14_contract_fingerprint` | `704c9ade45f3ca1c9fde49bf1e0812f1c903f7ebc71ee07554bd9d4883dba835` |
| `c15_contract_fingerprint` | `c1a155fbf48c07f0e3f27bac0110f8032933c98be82e57c406307b6cde8f14b8` |
| `c16_contract_fingerprint` | `f6ce4b94e097015744d7a686314dcd6db3ce14359552a6b5864c773d24c5eb40` |
| `c16_model_schema_fingerprint` | `e429f461d06e7aa4cced157d51b1509494f7f89ed1d3735e5a4c192d5a7fcee6` |
| `c16_result_fingerprint` | `4f8c7d05a130cfda97052e10c96e26c0a81b189bb84d55c6b8f0d92e2995420a` |
| `c17_contract_fingerprint` | `03763962fb7171e296d3ecb10addedbb5cb4277a31bcc70131cdf7a1d59cbfd3` |

Testbaseline aus dem jüngsten vorliegenden Bericht und dem zugehörigen Lauf:
**2 failed, 5751 passed, 126 skipped, 91 errors, Exit 1.**

---

## B. Umsetzung

### Der Identitätsvertrag

Profile einer nationalen Ligadatei entstehen im Namensraum ihres Providers.
`team_identity.translate_profiles` legt sie auf die football-data-Kennungen,
unter denen die Champions League geführt wird. Übersetzt wurde bisher nur der
**Dict-Schlüssel**. Das Feld `profil["team_id"]` blieb im Providerraum stehen.

Für die fünf Top-Ligen fällt das nicht auf, weil beide Räume dort dieselben
Zahlen benutzen. Für die 18 mit C13 ergänzten Ligen laufen sie auseinander.
`inference._ligastaerke_anwenden` liest die Vereinskennung aus dem **Profil**
und schlägt damit in der Ligakarte des Bundles nach, die football-data-Kennungen
trägt. Ergebnis: Ligazuordnung schlägt fehl, zweite Modellstufe fällt still aus.

Der Vertrag lautet ab jetzt ausnahmslos, für beide Provider ohne
Fallunterscheidung:

```
heraus[fd_id]["team_id"] == fd_id
```

Dieselbe Zusage gibt `strength_provider` für den nationalen Pfad bereits
(`merged["team_id"] = team_id`). Die Reparatur stellt also eine bestehende
Konvention her, sie erfindet keine neue.

### Betroffene Verbraucher, vor der Änderung geprüft

| Ort | Liest die Identität aus | Betroffen |
| --- | --- | --- |
| `inference._ligastaerke_anwenden` | Profil-Payload | **ja, einziger Verbraucher im CL/ML-Pfad** |
| `cl_dataset` Stärkelookup | Dict-Schlüssel | nein |
| `dataset` Stärkelookup | Dict-Schlüssel | nein |
| Merkmalsbau (`feature_groups`) | keine Team-ID | nein |
| API-Antwortpfad | keine Profil-Team-ID | nein |
| `strength_provider` (nationaler Pfad) | setzt sie selbst korrekt | nein |

Die Provider-ID wird **nicht** zusätzlich im Profil geführt: Kein Verbraucher
braucht sie, und eine zweite mitgeführte Kopie könnte vom geprüften Crosswalk
abweichen. Wer die Gegenrichtung benötigt, fragt `to_api_football`.

### Warum das keine Modelländerung ist

Geändert wurde ausschließlich, **welche Zahl** als Vereinsidentität an die
Ligakarte gereicht wird. Die Karte selbst, die Ligaparameter, Gamma, Alpha, die
Faktorgrenzen und das Basismodell sind unverändert. Das Bundle wurde nicht neu
gebaut, die Registry nicht angefasst, kein Gate berührt. Bundle-Hash und
Registry-Fingerprint sind vorher und nachher identisch.

### Geänderte und neue Dateien

| Datei | Zweck |
| --- | --- |
| `src/features/team_identity.py` | Fix 1. Neuer Helfer `_mit_kanonischer_id`; `translate_profiles` normalisiert die Payload-ID für beide Provider und kopiert dabei, statt in-place zu schreiben. |
| `src/ml/inference.py` | Fix 3. Sieben Zustandskonstanten der zweiten Stufe; `_ligastaerke_anwenden` unterscheidet die Gründe je Seite; `league_stage` im Rückgabevertrag. |
| `src/ml/runtime.py` | Fix 3. `STAGE2_ML_OFF` und `STAGE2_MODEL_UNAVAILABLE` (ohne ML-Import, damit `off` die ML-Module weiterhin nicht lädt); `league_stage` in jeder Antwort; Stufenstatus in `diagnostics`. |
| `src/predict/cl_season_sim.py` | Fix 3. `_liga_stufen_bericht`; Zählung **einmal je Paarung** vor der Monte-Carlo-Schleife; `league_stage` in `ml_summary`. |
| `src/predict/cl_match_sim.py` | Fix 3. `_liga_stufe_kurz`; additives Feld `ml.league_stage` in der Einzelspielantwort. |
| `tests/test_c18_identity_contract.py` | **neu**, 10 Tests zu Fix 1. |
| `tests/test_c18_runtime_parity.py` | **neu**, 9 Tests zu Fix 2. |
| `tests/test_c18_league_stage_diagnostics.py` | **neu**, 19 Tests zu Fix 3. |
| `tests/test_ml_runtime.py` | Erwartung `FELDER` um `league_stage` ergänzt. Der Vertrag dieses Tests ist "in jeder Betriebsart dieselben Felder", und genau das wird weiterhin geprüft, jetzt inklusive des neuen Feldes. |
| `tests/test_c13_national_profiles.py` | `test_football_data_ligen_werden_nicht_uebersetzt` präzisiert: statt `heraus == roh` jetzt Schlüsselgleichheit, `translated == 0`, `team_id == Schlüssel` und Unverändertheit der Eingabe. Das ist eine Verschärfung, keine Lockerung. |

Kein Test wurde gelöscht, gelockert oder stillgelegt.

---

## C. Vorher/Nachher am eingefrorenen Auditbestand

Bestand: Champions League 2026/27, Ligaphase, 36 Teams, 18 gespielte und
**126 offene** Partien, Stichtag `runtime_cutoff()`. Identisch mit dem Bestand,
auf dem der forensische Audit gemessen hat.

| Größe | Vorher | Nachher |
| --- | ---: | ---: |
| Teams mit abweichender Profil-ID | **10 von 36** | **0 von 36** |
| Offene Partien mit angewandter zweiter Stufe | **30 (23,8 %)** | **75 (59,5 %)** |
| Partien mit `league_unknown` | 96 | 51 |
| Gründe der verbleibenden Ausfälle | nicht unterscheidbar | ausschließlich `team_not_in_map` |
| Echte Cold Starts (Vereine ohne Bundle-Eintrag) | nicht ausgewiesen | 8 Vereine, getrennt gezählt |

Die zehn zuvor falsch adressierten Profile und ihre wiederhergestellte
Ligazuordnung:

| Verein | Spielplan-ID | vormals Profil-ID | Liga jetzt |
| --- | ---: | ---: | --- |
| Sporting CP | 498 | 228 | PT1 |
| FC Porto | 503 | 212 | PT1 |
| Slavia Praha | 930 | 560 | CZ1 |
| Bodø/Glimt | 5721 | 327 | NO1 |
| Galatasaray | 610 | 645 | TR1 |
| PSV | 674 | 197 | NL1 |
| Feyenoord | 675 | 209 | NL1 |
| Shakhtar Donetsk | 1887 | 550 | UA1 |
| Slovan Bratislava | 7509 | 656 | SK1 |
| Club Brügge | 851 | 569 | BE1 |

Die acht verbleibenden Ausfälle sind echte Cold Starts, keine Fehladressierung:
Real Betis, AS Roma, Fenerbahçe, PAE AEK, LASK Linz, Viking FK, Como 1907,
Sabah FK stehen nicht in der Ligakarte des Bundles, weil sie in den
Trainingssaisons 2023 bis 2025 keine Champions League gespielt haben.

### Sechs konkrete Partien

| Partie | Ligen | Lambda vorher | Lambda nachher | Ligafaktor |
| --- | --- | --- | --- | --- |
| Slavia Praha gegen Arsenal | CZ1/PL | 2.16 / 1.29 | 1.29 / 2.06 | 0.600 / 1.600 |
| Galatasaray gegen Aston Villa | TR1/PL | 2.84 / 1.13 | 1.70 / 1.73 | 0.600 / 1.535 |
| Slavia Praha gegen Villarreal | CZ1/PD | 2.72 / 1.21 | 1.63 / 1.94 | 0.600 / 1.600 |
| Club Brügge gegen Liverpool | BE1/PL | 2.51 / 1.49 | 1.51 / 2.32 | 0.600 / 1.558 |
| Sporting CP gegen Manchester United | PT1/PL | 3.31 / 1.05 | 1.98 / 1.34 | 0.600 / 1.277 |
| Slovan Bratislava gegen Inter | SK1/SA | 2.09 / 2.10 | 1.26 / 2.63 | 0.600 / 1.251 |

Die 0.600 sind die untere Faktorgrenze aus dem Bundle (`factor_bounds`
`[0.6, 1.6]`), nicht ein gerechneter Wert. Sie greift, weil der ungedämpfte
Exponent bei diesen Ligapaarungen unter der Grenze liegt.

---

## D. Paritätsnachweis

### Aufbau

Verglichen wurde **fold-weise**. Je Fold entsteht ein eigenes Bundle, das
ausschließlich auf den Trainingssaisons dieses Folds gebaut ist. Das finale
Produktionsbundle hat spätere Saisons gesehen und wird ausdrücklich nicht
rückwirkend gegen frühere Foldvorhersagen gehalten. Beleg dafür ist der
Parameter selbst:

| Fold | Trainingssaisons | Testsaison | Gamma | Alpha | Vereine in der Karte | Testzeilen |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `cl_2024` | 2023 | 2024 | **1.00** | 0.1 | 32 | 144 |
| `cl_2025` | 2023, 2024 | 2025 | **0.75** | 0.1 | 49 | 139 |
| Produktionsbundle | 2023 bis 2025 | - | 1.00 | 0.01 | 63 | - |

Fold `cl_2025` trägt Gamma 0.75, das Produktionsbundle 1.00. Wäre versehentlich
das Produktionsmodell benutzt worden, stünden beide auf 1.00. Ein eigener Test
prüft genau das.

Jedes Foldbundle durchläuft `persist.load_bundle` und damit die vollständige
Ladevalidierung. Es gibt keine Umgehung einer Validierungsschranke. Die Bundles
entstehen in temporären Verzeichnissen; Produktionsbundle und Registry werden
nicht berührt.

Die Laufzeitseite läuft durch `inference.shadow_lambdas`, also durch
Merkmalsbau, Modellaufruf, zweite Stufe und Begrenzung. Kein Vergleich zweier
Hilfsfunktionen.

### Toleranz und Ergebnis

Die Toleranz wurde **vor** dem Vergleich festgelegt: `1e-9`. Beide Seiten
rechnen dieselbe Formel auf denselben Gleitkommazahlen; eine echte
Übereinstimmung ist hier bitgleich, die Schranke lässt nur die Umordnung
einzelner Multiplikationen zu.

| Größe | Wert |
| --- | ---: |
| Verglichene Partien | **283** (Standardpopulation vollständig) |
| Davon vergleichbar (beide Vereine in der Bundlekarte) | **92** |
| Davon bitgleich | **92** |
| Abweichungen über Toleranz | **0** |
| **Größte gemessene Abweichung** | **0.0** |

Zusätzlich geprüft und erfüllt: In allen 92 Fällen meldet die Laufzeit
`status == applied`, und die auf beiden Wegen aufgelöste Herkunftsliga stimmt
je Mannschaft überein. Gleichheit allein genügte nicht, denn sie wäre auch
gegeben, wenn beide Seiten gar nichts angewandt hätten.

### Die verbleibende Differenz, benannt statt weggerechnet

Für 191 der 283 Partien ist kein Lambda-Vergleich möglich, und zwar aus genau
einem Grund: Die Evaluation schlägt die Liga in der **vollständigen** Karte
aller nationalen Ligadateien nach (`c14.team_league_map()`), das Bundle trägt
nur die Vereine, die in den Trainings-CL-Partien vorkamen.

| Fold | Nicht vergleichbar | Evaluation hätte ebenfalls neutral gelassen | Evaluation korrigierte wirksam | größter Faktor |
| --- | ---: | ---: | ---: | ---: |
| `cl_2024` | 105 | 1 | **104** | 1.631 |
| `cl_2025` | 86 | 2 | **84** | 1.648 |

**Das ist ein eigenständiger, bisher nicht dokumentierter Deckungs-Skew:** Die
C16-Evaluation maß ein Modell mit vollständiger Ligakenntnis, ausgeliefert wird
ein Modell mit Teilkenntnis. Auf 188 von 283 Partien wendete die Evaluation
einen echten Ligafaktor an, den die Laufzeit mit der Karte des Bundles nicht
anwenden kann.

Dieser Befund stammt **nicht** aus dem Laufzeitpfad und wird durch Fix 1 weder
verursacht noch behoben. Seine Schließung verlangt eine vollständigere
Bundle-Ligakarte und damit ein neues Bundle mit neuer Modell-ID, was in diesem
Block ausdrücklich verboten war. Die Tests rechnen diese Fälle nicht weg: Sie
trennen sie, zählen sie und verlangen für jeden einzelnen die ausdrückliche
Diagnose `team_not_in_map`.

### Weitere Paritätsprüfungen

| Prüfung | Ergebnis |
| --- | --- |
| Einzelspiel und Ligaphase liefern für dieselbe Partie, denselben Cutoff und dieselben Inputs dieselben Lambdas | erfüllt, 12 Partien geprüft |
| Ligakorrektur wird genau einmal angewandt (Spion auf `LeagueStrength.factors`) | genau 1 Aufruf |
| Faktor steht genau einmal im Lambda (nachgerechnet, nicht nur gezählt) | erfüllt |
| Bekannte Liga ohne gelernte Parameter wird nicht mit fehlendem Vereinseintrag verwechselt | `league_without_parameters` gegen `team_not_in_map`, getrennt |
| ML aus und individueller Modus laden kein Modell | `shadow_lambdas` null Aufrufe |
| Manuelle Regler beeinflussen den ML-Modus nicht | erfüllt, `ml_weight` weiterhin abgewiesen |
| Kein Netzzugriff, keine `.env` nötig | erfüllt, Betriebsart aus der Prozessumgebung, Standard `off` |

---

## E. Fix 3: die zweite Stufe ist zählbar

Unterschiedene Zustände:

| Zustand | Bedeutung |
| --- | --- |
| `applied` | zweite Stufe auf beide Seiten angewandt |
| `team_not_in_map` | Verein fehlt in der Ligakarte des Bundles (echter Cold Start) |
| `league_without_parameters` | Liga des Vereins bekannt, Modell kennt sie nicht |
| `identity_missing` | Profil trug keine verwertbare Team-ID |
| `stage_absent` | Bundle führt keine zweite Stufe |
| `not_run` | keine zweite Stufe gelaufen |
| `error` | unerwarteter Fehler |
| `ml_off` | ML deaktiviert (nur Laufzeit) |
| `model_unavailable` | kein Modell angewandt, fehlend oder abgelehnt |

Saisonbericht, gezählt **einmal je offener Partie**, nicht je Monte-Carlo-Lauf:

```
off    : applied 0/126,  share 0.0,    reasons {ml_off: 126}
active : applied 75/126, share 0.5952, reasons {team_not_in_map: 51}
```

`applied: true` für das Basismodell behauptet nicht mehr, dass auch die zweite
Stufe gegriffen hat. Beides steht getrennt in der Antwort. Die bestehende
API-Semantik bleibt erhalten; `league_stage` ist additiv, der alte Schlüssel
`reason: "league_unknown"` bleibt für bestehende Leser bestehen. Es gibt keine
pauschale Produktionssperre anhand eines Prozentwerts. Echte Cold Starts werden
getrennt ausgewiesen und nicht als korrigierte Spiele gezählt.

---

## F. Tests und Sicherheit

### Neue fokussierte Tests

| Datei | Ergebnis |
| --- | --- |
| `tests/test_c18_identity_contract.py` | **10 passed** |
| `tests/test_c18_runtime_parity.py` | **9 passed** |
| `tests/test_c18_league_stage_diagnostics.py` | **19 passed** |

### Gezielte Regression

20 Dateien zu Identitäten, Crosswalk, PIT-Profilen, C10-Cutoff, C13, C15, C16,
C17-Bundle, Registry, Runtime, Inference, Einzelspiel, Ligaphase und
Modustrennung: **1444 passed, 0 failed**, Exit 0.

### Vollständige maßgebliche Suite

| Lauf | passed | failed | errors | skipped | Exit |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline | 5751 | 2 | 91 | 126 | 1 |
| **Nach der Reparatur** | **5788** | **3** | **91** | **126** | **1** |
| Differenz | +37 | +1 | 0 | 0 | - |

Laufzeit 2287,85 s (38:07). Der Exit-Code wurde ohne Pipe erfasst; eine
`| tail`-Pipe meldet den Status von `tail` und damit fälschlich immer 0.

Die Rechnung geht exakt auf: 5751 + 38 neue Tests = 5789 = 5788 passed plus ein
zuvor grüner Test, der jetzt fällt. Alle 38 neuen Tests bestehen.

**Fehleridentitäten, nicht nur Summen, gegen die Baseline verglichen:**

| Test | Status | Ursache |
| --- | --- | --- |
| `test_go1_season_and_pit.py::TestSaisonWeitergabe::test_provider_ausfall_bleibt_neutral` | Baseline-Fehler, unverändert | Cacheebene von `apisports_api`, Testreihenfolge-Artefakt der vollen Suite |
| `test_test_isolation.py::TestReihenfolgeSpieltKeineRolle::test_umgekehrte_reihenfolge_aendert_nichts` | Baseline-Fehler, unverändert | PostgreSQL lokal nicht gestartet |
| `test_e2e_cached_data.py::test_real_fl1_plan_has_306_fixtures` | **neu fehlschlagend** | siehe unten |
| 91 Errors | identisch zur Baseline | PostgreSQL lokal nicht gestartet |

Die 91 Errors wurden Testidentität für Testidentität abgeglichen: Die Mengen
sind deckungsgleich, keine neue und keine verschwundene. Sie verteilen sich
ausschließlich auf Datenbank- und Authentifizierungsinfrastruktur
(`test_privacy_and_deletion` 35, `test_email_verification` 16,
`test_password_reset_token` 10, `test_csrf_auth` 8, `test_security_hardening` 5,
`test_auth` 5, `test_audit_hardening` 5, `test_migration_upgrade_path` 4,
`test_migration_drift` 2, `test_db_models` 1).

### Der neue Fehlschlag, diagnostiziert

`test_real_fl1_plan_has_306_fixtures` prüft in Zeile 62, dass **jedes** der 18
Ligue-1-Teams noch 34 offene Partien hat, also dass die Saison nicht begonnen
hat. Gemessen hat jedes Team jetzt **31** offene Partien, weil der gelesene
Plattencache 27 abgeschlossene Partien (drei Spieltage) enthält. Teams,
Fixtures und Coverage stimmen weiterhin (18 / 306 / `ok`).

Belege, dass die Reparatur unbeteiligt ist:

* `src/predict/fixture_plan.py` importiert ausschließlich `collections`,
  `src.api.league_api`, `src.utils.disk_cache` und `src.utils.cache`. **Kein
  einziges in diesem Block geändertes Modul.**
* Die Einteilung in gespielt und offen erfolgt allein über den Status der
  Partie, ohne Datumsbezug.
* Die Datenquelle ist `data/cache/season_full_matches__FL1__2026.json`, ein
  gitignorierter, lebender Plattencache, keine versionierte Testfixture. Sein
  Inhalt hat sich seit dem Baselinelauf geändert.

Der Test wurde **nicht** angefasst. Er kodiert eine Annahme über den Spielstand
einer laufenden Saison und wird ohne eingefrorene Fixture mit jedem
Spieltagsfortschritt erneut fallen. Das ist eine eigenständige Testfragilität
und gehört nicht in diesen Block.

### Sicherheit und Git

| Prüfung | Ergebnis |
| --- | --- |
| `git diff --check` | Exit 0, nur LF/CRLF-Normalisierungshinweise |
| `git status --short` | 85 Einträge (80 vorher plus 3 neue Testdateien plus 2 neu geänderte Quelldateien) |
| `git diff --stat` | 30 Dateien, 4371 Insertions, 637 Deletions |
| `git diff --cached --stat` | leer, nichts gestaged |
| Secret-Scan neuer und geänderter Dateien | keine Treffer |
| Bundle SHA-256 | unverändert |
| Registry-Fingerprint | unverändert, `validate_registry` ohne Befund |
| Vertragsfingerprints | alle neun unverändert |
| README U+2014 | 0 |
| `.env` | nicht gelesen, nicht verändert |

Kein Commit, kein Push, kein Deployment. Keine lokale Datei gelöscht.

---

## G. Was noch fehlt

**Abgeschlossen in diesem Block:**

* Fix 1, der Identitätsvertrag, mit Regressionsschutz auf dem echten Bestand.
* Fix 2, der Paritätsnachweis auf der vollständigen Standardpopulation, mit
  fold-eigenen Modellen und bitgleichem Ergebnis auf allen vergleichbaren
  Partien.
* Fix 3, die zählbare Diagnose der zweiten Stufe in Einzelspiel und Saisonlauf.

**Offen, nach Dringlichkeit:**

1. **Vollständigere Bundle-Ligakarte.** Neu belegt und beziffert: Auf 188 von
   283 Evaluationspartien wendete die Evaluation einen Ligafaktor an, den die
   ausgelieferte Karte nicht anwenden kann. Im aktuellen Spielplan bleiben
   dadurch 51 von 126 offenen Partien unkorrigiert. Das ist ein
   Train-Serve-Deckungsunterschied und verlangt ein neues Bundle mit neuer
   Modell-ID und gebundener Reevaluation. **Dieser Punkt ist damit nicht mehr
   optional, sondern belegt notwendig** und sollte vor der Saisonvalidierung
   entschieden werden, weil er deren Messgrundlage verändert.
2. **Historische Saisonvalidierung.** Weiterhin offen. Es existiert nach wie vor
   kein End-to-End-Backtest ganzer Ligaphasen und kein Tabellen-Gate.
3. **Testfragilität `test_real_fl1_plan_has_306_fixtures`.** Klein, aber
   dauerhaft rot, solange die Annahme "Saison nicht begonnen" gegen einen
   lebenden Cache geprüft wird.

**Vorgeschlagene weitere Aufträge, aus dem tatsächlichen Endzustand geschätzt:**

| Block | Inhalt | Denkstufe |
| --- | --- | --- |
| 1 | Bundle-Ligakarte vollständig bilden, neues Bundle, neue Modell-ID, gebundene Reevaluation, Registryentscheidung | Ultra High |
| 2 | End-to-End-Saisonvalidierung, Tabellen-Gate im Vertrag verankern | Ultra High |
| 3 | Eingefrorene Fixture für die betroffene Cachedatei, klein und isoliert | Medium |

Ob Block 1 und Block 2 zusammengelegt werden können, hängt davon ab, ob die
neue Karte die Registry berührt. Solange sie ein neues Bundle erzeugt, sind es
zwei getrennte Entscheidungen und damit zwei Blöcke.

**Keine Freigabe für ein VPS-Deployment mit aktivem ML.** Die Laufzeit wendet
das Modell jetzt technisch korrekt an, aber das ausgelieferte Modell deckt
nachweislich weniger Partien ab als das gemessene, und eine Saison- oder
Tabellenvalidierung gibt es weiterhin nicht.

---

**RUNTIME FIX VERIFIED, READY FOR SEASON VALIDATION**
