# V2-C19: Bundleabdeckung schliessen und vollstaendige Laufzeitparitaet

Umsetzung des C19-Auftrags auf dem C18-Stand. Ziel war, die Team-Liga-Zuordnung
von Messung und Auslieferung auf einen gemeinsamen, zeitlich korrekten Vertrag
zu bringen, alle 283 Standardpartien ueber den echten Produktionspfad zu
vergleichen, ein validiertes Candidate-Bundle vorzubereiten und den
cacheabhaengigen FL1-Test deterministisch zu reparieren.

**Der Block hat sein technisches Ziel erreicht und dabei einen inhaltlichen
Blocker freigelegt.** Beides steht unten, in dieser Reihenfolge.

---

## A. Ausgangslage und Endzustand

| Groesse | Vorher | Nachher |
| --- | --- | --- |
| Branch / HEAD | `main` / `4f55d80cb47254a3704589dfba3fd5dd78fa937f` | unveraendert |
| Gestagte Aenderungen | keine | keine |
| `git status --short` | 86 Eintraege | 96 Eintraege |
| Aktives Modell | `clm-3475c9aacef6fec9-lsa165be9c` | unveraendert |
| Registry-Fingerprint | `66345556ea317311fe3681700a2d4bf55d6f71a2fa303624145efe431a4f132a` | unveraendert |
| Aktives Bundle SHA-256 | `b46c515e331fcc675e1c29898f844b80383ef1762f0d0225927f61f4f58cfc84` | unveraendert |
| `validate_registry` | `[]` | `[]` |
| Vollstaendige Suite | 3 failed, 5788 passed, 126 skipped, 91 errors | **2 failed, 5838 passed, 126 skipped, 91 errors** |

Vertragsfingerprints, alle unveraendert und weiterhin deckungsgleich mit den
Bindungen im aktiven Bundle:

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

Neu hinzugekommen:

| Groesse | Wert |
| --- | --- |
| C19-Vertragsfingerprint | `a1e94b02630e3d1ea6735d7926247c54cf7fee8350d8dca00a1cea3c8858cd5f` |
| Kandidaten-Modell-ID | `clm-3475c9aacef6fec9-ls9cb9e0f6` |
| Kandidaten-Bundle SHA-256 | `05d6cdf5d7ada260d26ed13b2b2c5d654047bd6adcd9ab97ba30a6ded2b0fb0d` |
| Kartenfingerabdruck bis 2023 | `cdf986861fdcd578165ed2f9f437591f4d038f79b28f6a9ad18a7e99d858ff21` |
| Kartenfingerabdruck bis 2024 | `73559dc24f6a1457ec3abca0e0ea5251f757f6931fb30e072eff77c2e20253a1` |
| Kartenfingerabdruck bis 2025 | `75447436939460ebdff04e27838d3a5461e1a4fd32b35c4d4ae7989c0c9f6c1e` |

---

## B. Geaenderte und neue Dateien

| Datei | Zweck |
| --- | --- |
| `src/ml/c19_league_map.py` | **neu.** Der Zuordnungsvertrag: Regeln, Fingerabdruecke, der zeitlich begrenzte Kartenbauer `build_team_league_map(upto_season)`, `map_fingerprint`, `bundle_map`, `classify`, Artefaktschreiber. |
| `src/ml/c16_release.py` | `build_final_bundle` friert die VOLLE Karte ein statt nur der CL-Trainingsteilnehmer und legt `team_leagues_provenance` daneben. `run_release` baut die Karte ueber C19 statt ueber `c14.team_league_map()`. |
| `src/ml/c16_damped_league_strength.py` | Additiv: `ligakarte` darf eine Funktion je Fold sein (`_karte_fuer`). Ein Dict bleibt zulaessig und aendert nichts. Notwendig fuer zeitlich korrekte Foldkarten. |
| `src/ml/c15_league_strength.py` | Ein Praezedenzfehler in `concentration`: `{A} \| {B} - {None}` band das Entfernen nur an die zweite Menge. Mit einer vollstaendig abdeckenden Karte fiel das nie auf; mit einer begrenzten Karte bricht `sorted()` ab, bevor das vorhandene `continue` greifen kann. Reine Reparatur, Semantik unveraendert. |
| `src/ml/inference.py` | `_ligastaerke_anwenden` folgt jetzt der gemessenen Cold-Start-Semantik (siehe Abschnitt E). |
| `tests/fixtures/fl1_frozen_season_306.json` | **neu.** Eingefrorener Ligue-1-Spielplan: 18 Vereine, 306 Paarungen, 34 Spieltage, jede gerichtete Paarung genau einmal, 17 Heimspiele je Verein. Kein Anbieterabzug, kein Cache. |
| `tests/test_c19_league_map.py` | **neu**, 24 Tests: Vertrag, zeitliche Begrenzung, Fingerabdruecke, Mehrdeutigkeit, Unbekannt-Semantik. |
| `tests/test_c19_bundle_coverage.py` | **neu**, 12 Tests: Bundle traegt die volle Karte, Provenienz, Ladevalidierung, struktureller Beweis unveraenderter Parameter, foldweise Zeitlichkeit, **vollstaendige 283er-Paritaet**. |
| `tests/test_c19_candidate_registration.py` | **neu**, 10 Tests: Trockenlauf der Registrierung, echte Registry unberuehrt, Freigabe bleibt fail-closed. |
| `tests/test_e2e_cached_data.py` | FL1-Tests auf die eingefrorene Fixture umgestellt, zwei Zustaende, plus ein Cachetest ohne die Annahme "Saison ungespielt". |
| `tests/test_c18_runtime_parity.py` | Drei Erwartungen auf den C19-Vertrag gebracht; der Lueckentest ist jetzt ein Waechter gegen das Wiederkuerzen der Karte. |
| `tests/test_c18_league_stage_diagnostics.py` | Eine Erwartung korrigiert, die der gemessenen Semantik widersprach. |
| `data/ml/c19_league_map_contract.json` | **neu.** Vertrag samt Karte je Obergrenze. |
| `data/ml/c19_runtime_parity.json` | **neu.** Paritaetsergebnis, Messvergleich, Kandidatenangaben. |
| `data/ml/models/clm-3475c9aacef6fec9-ls9cb9e0f6.json` | **neu.** Das Candidate-Bundle. Ueberschreibt nichts. |

Kein Test geloescht, keiner gelockert, kein Skip eingefuegt.

---

## C. Der Zuordnungsvertrag und seine zeitliche Provenienz

| Regel | Festlegung |
| --- | --- |
| Kanonischer Namensraum | football-data.org, Schluessel ganzzahlig |
| Quellen | ausschliesslich lokale Saisondateien der 23 nationalen Ligen, kein Netz |
| Provideraufloesung | `team_identity.to_football_data` ueber den geprueften Crosswalk |
| Verboten | numerische Gleichheit ueber Providergrenzen, Namensabgleich, Sonderregeln je Verein oder Liga |
| Zeitliche Regel | `upto_season` ist Pflichtargument ohne Standardwert; nur Saisons `s <= upto_season` werden gelesen |
| Widerspruch | derselbe Verein in mehr als einer Liga: kein Eintrag, gezaehlt als `ambiguous_leagues` |
| Unbekannter Verein | `team_not_in_map`, Lambdas unveraendert |
| Liga ohne gelernte Parameter | `league_without_parameters`, Beitrag 0, die bekannte Seite korrigiert weiter |
| Bindung | Evaluation, Bundle und Laufzeit benutzen dieselbe Funktion |

`upto_season` hat bewusst keinen Standardwert. Ein Vorgabewert waere hier die
gefaehrlichste Bequemlichkeit: Wer ihn vergisst, bekaeme stillschweigend die
neueste Karte und damit Wissen aus der Zukunft des Folds, den er gerade misst.

Die Laufzeit liest keine Ligadatei nach. Die Karte steht im Bundle; ein Test
haelt fest, dass `build_team_league_map` im Vorhersagepfad nicht aufgerufen
wird.

---

## D. Zuordnungszahlen

### Je Obergrenze

| Obergrenze | Dateien gelesen | Vereine | Mehrdeutig |
| ---: | ---: | ---: | ---: |
| bis 2023 | 15 | 114 | 0 |
| bis 2024 | 31 | 132 | 0 |
| bis 2025 | 47 | 146 | 0 |

Die Karte bis 2025 ist inhaltlich identisch mit der bisherigen
`c14.team_league_map()`. Damit ist belegt, dass sich fuer das
Produktionsbundle nichts an den Ligaparametern verschieben kann; die zeitliche
Begrenzung wirkt ausschliesslich auf die frueheren Folds.

### Im Bundle

| | vorher | nachher |
| --- | ---: | ---: |
| Vereine in `team_leagues` | 63 | **146** |
| hinzugekommen | | 83 |
| entfallen | | 0 |
| umgehaengt | | 0 |

### Im eingefrorenen Auditbestand (126 offene Partien der laufenden Ligaphase)

| Karte | zweite Stufe angewandt | `team_not_in_map` |
| --- | ---: | ---: |
| Bundlekarte vor C19 (63) | 75 (59,5 %) | 51 |
| C19-Karte (146) | **93 (73,8 %)** | 33 |

Die verbleibenden 33 stammen von fuenf Vereinen, die der **gepruefte Crosswalk**
nicht aufloest: Fenerbahce, PAE AEK, LASK Linz, Viking FK, Sabah FK. Sie zu
ergaenzen hiesse raten, und das verbietet der Vertrag. Drei zuvor fehlende
Vereine sind dazugekommen: AS Roma (SA), Real Betis (PD), Como 1907 (SA).

---

## E. Alle 283 Paritaetsfaelle

Toleranz **vor** dem Vergleich festgelegt: `1e-9`.

| Fold | Trainingssaisons | Test | Karte | Gamma | Basis-Alpha | Liga-Alpha | Zeilen |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `cl_2024` | 2023 | 2024 | 114 bis 2023 | 1.00 | 0.1 | 0.1 | 144 |
| `cl_2025` | 2023, 2024 | 2025 | 132 bis 2024 | 0.75 | 0.1 | 0.01 | 139 |

| Ergebnis | Wert |
| --- | ---: |
| Verglichene Partien | **283** |
| Zweite Stufe auf beiden Wegen angewandt | **228** |
| Auf beiden Wegen neutral (`team_not_in_map`) | **55** |
| Divergent | **0** |
| Profil-ID gleich der Partie-ID | 283 / 283 |
| Aufgeloeste Herkunftsliga auf beiden Wegen gleich | 283 / 283 |

**Keine Partie wurde als nicht vergleichbar entfernt.** Die 55 neutralen Faelle
sind kein Ausschluss: Beide Wege liefern dort dieselbe dokumentierte neutrale
Semantik, und der Test verlangt fuer jeden einzelnen ausdruecklich den Status
`team_not_in_map`.

Die Laufzeitseite laeuft durch `inference.shadow_lambdas` mit Profilen, die der
Produktionspfad selbst aufgeloest hat (`get_cl_team_strengths` zum historischen
Stichtag der Partie, dann `_resolve_cl_profile`), und mit einem Foldbundle, das
`persist.load_bundle` vollstaendig validiert hat. Keine vorbereiteten Profile.

### Maximale Abweichungen

| Groesse | Maximum |
| --- | ---: |
| Finale Lambdas | **1,33e-15** |
| Ligafaktoren | **0,0** |
| 1X2-Wahrscheinlichkeiten | **2,22e-16** |

Alles um zwoelf Groessenordnungen unter der Toleranz. Es gibt keine unerklaerte
Abweichung.

### Die Cold-Start-Semantik, die C19 freigelegt hat

Mit der groesseren Karte kommen Vereine vor, deren Liga bekannt ist, fuer die
das Modell aber nichts gelernt hat. `league_strength.apply_factors` behandelt
diesen Fall seit C15 als Beitrag 0 und laesst die BEKANNTE Seite
weiterkorrigieren. Die in C18 eingefuehrte Diagnose brach stattdessen die ganze
Korrektur ab.

Solange die Bundlekarte nur die 63 Vereine der CL-Trainingshistorie trug, kam
der Fall nie vor, und die C18-Paritaet war trotzdem gruen. Mit 146 Vereinen kam
er vor: **52 der 283 Partien haetten anders gerechnet als die akzeptierte
Messung.** Die Laufzeit folgt jetzt der Messung. Das war ein echter, bis dahin
unbemerkter Train-Serve-Unterschied und ist der zweite Fund dieses Blocks.

---

## F. Die beiden offenen C18-Fragen, an Artefakten geklaert

**Alpha.** Kein Widerspruch, sondern zwei verschiedene Parameter mit demselben
Namen auf verschiedenen Ebenen:

| | `bundle["alpha"]` (Basismodell) | `bundle["league_strength"]["alpha"]` (zweite Stufe) |
| --- | ---: | ---: |
| `cl_2024` | 0.1 | 0.1 |
| `cl_2025` | 0.1 | 0.01 |
| Produktion | 0.01 | 0.01 |

Die C18-Foldtabelle nannte `bundle["alpha"]`, die frueheren C16-Berichte die
Ligastufe des Produktionsbundles. Beide Zahlen waren richtig, die C18-Tabelle
sagte nur nicht, welche Ebene sie meint.

**Faktorgrenzen.** Die in C18 genannten 1.631 und 1.648 waren **keine
angewandten Faktoren**. Sie stammten aus einer Diagnosezeile
`max(maxf, max(fh, fa), 1/min(fh, fa))`; der dritte Term ist der Kehrwert des
kleineren Faktors, also ein Mass fuer die Abweichung nach unten. `factors()`
begrenzt ausnahmslos auf `[0.6, 1.6]`, und `ls.FACTOR_MIN/FACTOR_MAX` stimmen
mit `factor_bounds` im Bundle ueberein. Kein Faktor hat je eine Grenze
ueberschritten. Das war ein Beschriftungsfehler im C18-Bericht, kein Defekt.

---

## G. Metriken, Gates und der Blocker

Die Messung wurde zweimal mit denselben, unveraenderten Gates gefahren.

| | Verdict | Delta Log Loss | 95-Prozent-Intervall | Folds | n |
| --- | --- | ---: | --- | --- | ---: |
| Akzeptiertes Artefakt | `accepted` | -0,08755954 | [-0,11882785; -0,05514556] | -0,066131 / -0,109758 | 283 |
| **A** unbegrenzte Karte | `accepted` | -0,08755954 | [-0,11882785; -0,05514556] | -0,066131 / -0,109758 | 283 |
| **B** zeitlich begrenzt | **`rejected`** | **-0,06487443** | [-0,09491105; -0,03468773] | -0,046725 / -0,083677 | 283 |

Variante A reproduziert das akzeptierte Ergebnis **bitgenau**. Das ist der
Beleg, dass die Messvorrichtung treu ist und der Unterschied in B nicht vom
Aufbau stammt.

Variante B ist die Messung unter dem C19-Vertrag, also mit je Fold nur dem
Wissen bis zur letzten Trainingssaison. Sie faellt durch **genau ein Gate**:

```
no_severe_segment_damage : ['home_origin_league:PD']
```

Alle uebrigen zehn Gates bleiben erfuellt. Der Vorteil bleibt vorhanden und
signifikant (Intervall schliesst die Null weiterhin aus), er schrumpft aber um
etwa ein Viertel, und ein Segment nimmt schweren Schaden.

**Warum B und nicht A massgeblich ist.** Das ausgelieferte Bundle friert seine
Karte zum Bauzeitpunkt ein und liest zur Laufzeit nichts nach. Ein Fold, der
2024 testet, verfuegt in der Produktion also ueber genau das Wissen, das B ihm
gibt, und nicht ueber das von A. A ueberschaetzt den Nutzen, weil dort jeder
Fold eine Karte benutzt, die es zu seinem Zeitpunkt noch nicht gab.

**Damit ist die C16-Acceptance nicht auf den C19-Stand uebertragbar.** Sie wird
hier ausdruecklich nicht uebertragen.

---

## H. Nachweis unveraenderter Modellparameter

Das Kandidatenbundle gegen das aktive Bundle, Feld fuer Feld:

| Feld | Ergebnis |
| --- | --- |
| `alpha`, `features`, `feature_count`, `candidate`, `schema_version` | identisch |
| `models` (Koeffizienten beider Seiten) | identisch |
| `league_strength.gamma`, `.alpha`, `.attack`, `.defence` | identisch |
| `.factor_bounds`, `.stage`, `.selection`, `.trained_on` | identisch |
| `contract_bindings`, `training` | identisch |
| **`league_strength.team_leagues`** | 63 auf 146 |
| **`league_strength.team_leagues_provenance`** | neu, additiv |

Genau zwei Schluessel unterscheiden sich, und ein Test haelt das fest. Die
Modell-ID belegt dasselbe strukturell: Der Basismodellteil
`clm-3475c9aacef6fec9` ist unveraendert, nur das Ligastufensuffix wechselt von
`lsa165be9c` auf `ls9cb9e0f6`.

Ein C10-Cutoff, ein Feature-Schema oder eine Hyperparametersuche wurde nicht
angefasst.

---

## I. Candidatenstatus und Registry

| Punkt | Stand |
| --- | --- |
| Bundle auf der Platte | ja, unter neuer Modell-ID, ueberschreibt nichts |
| `persist.load_bundle` | angenommen, `release_stage` `approved`, Schema 3 |
| `c17_bundle_contract.validate_bundle` | keine Befunde |
| In der Registry registriert | **nein** |
| Trockenlauf der Registrierung | durchgerechnet, `validate_registry` ohne Befund |
| Sprung auf `active` ohne Freigabe | wird fail-closed abgewiesen |
| Echte Registry nach allen Tests | Fingerabdruck unveraendert |
| Aktives Modell | weiterhin `clm-3475c9aacef6fec9-lsa165be9c` mit 63 Vereinen |

Alle Registryhandlungen liefen auf Kopien im Speicher oder in temporaeren
Verzeichnissen. Ein Test prueft ausdruecklich, dass die Laufzeit weiterhin das
alte Bundle laedt.

---

## J. FL1-Testreparatur

Der Test verlangte 34 **offene** Partien je Verein und setzte damit voraus,
dass die Ligue-1-Saison nie beginnt. Gelesen wurde ein lebender, gitignorierter
Plattencache, der inzwischen 27 gespielte Partien enthaelt.

Repariert wurde die Testisolierung, nicht die Produktionsdaten:

| Test | Inhalt |
| --- | --- |
| `test_real_fl1_plan_has_306_fixtures` | eingefrorene Fixture, Zustand vor Saisonbeginn: 18 Vereine, 306 Paarungen, 0 gespielt, 34 offen und 34 gesamt je Verein |
| `test_fl1_plan_bleibt_vollstaendig_wenn_spieltage_gespielt_sind` | dieselbe Quelle mit drei gespielten Spieltagen: 27 gespielt, 279 offen, je Verein 3 + 31 = 34 |
| `test_fl1_plan_zaehlt_jede_paarung_genau_einmal` | 306 gerichtete Paarungen, 153 Begegnungen, 17 Heimspiele je Verein |
| `test_echter_fl1_cache_bleibt_in_sich_stimmig` | echter Cache, aber nur spielstandsunabhaengige Invarianten: 18 Vereine, 306 Fixtures, gespielt plus offen gleich 34 |

Keine Netzwerkzugriffe, kein Skip, keine geloeschte fachliche Aussage. Der
Cachezustand anderer Tests kann das Ergebnis nicht mehr beeinflussen.

---

## K. Tests und Exit-Codes

| Lauf | Ergebnis | Exit |
| --- | --- | ---: |
| `tests/test_c19_league_map.py` | 24 passed | 0 |
| `tests/test_c19_bundle_coverage.py` | 12 passed (davon die 283er-Paritaet) | 0 |
| `tests/test_c19_candidate_registration.py` | 10 passed | 0 |
| `tests/test_e2e_cached_data.py` | 8 passed | 0 |
| `tests/test_c18_runtime_parity.py` | 9 passed | 0 |
| `tests/test_c18_league_stage_diagnostics.py` | 19 passed | 0 |
| Gezielte Regression, 25 Dateien | 1564 passed, 3 failed (vor der Angleichung) | 1 |
| **Vollstaendige Suite, final** | **2 failed, 5838 passed, 126 skipped, 91 errors** | **1** |

Laufzeit der Schlussmessung 2091,94 s (34:51). Der Exit-Code wurde ohne Pipe
erfasst; eine `| tail`-Pipe meldet den Status von `tail` und damit faelschlich
immer 0.

### Vergleich der Fehleridentitaeten

| Test | C18 | C19 | Ursache |
| --- | --- | --- | --- |
| `test_go1_season_and_pit.py::TestSaisonWeitergabe::test_provider_ausfall_bleibt_neutral` | failed | failed | Baseline, Cacheebene `apisports_api`, Testreihenfolge-Artefakt |
| `test_test_isolation.py::TestReihenfolgeSpieltKeineRolle::test_umgekehrte_reihenfolge_aendert_nichts` | failed | failed | Baseline, PostgreSQL lokal nicht gestartet |
| `test_e2e_cached_data.py::test_real_fl1_plan_has_306_fixtures` | failed | **passed** | in diesem Block repariert |
| 91 Errors | 91 | 91 | identische Menge, ausschliesslich Datenbank- und Authentifizierungsinfrastruktur |

Zwischenzeitlich fiel `test_c18_league_stage_diagnostics::test_bekannte_liga_ohne_parameter_ist_kein_fehlender_verein`,
weil er die in Abschnitt E beschriebene, ueberholte Cold-Start-Semantik
festhielt. Er wurde auf die gemessene Semantik gebracht und um die Gegenprobe
erweitert; die Schlussmessung lief danach vollstaendig durch.

**Keine neuen unerklaerten Failures, Errors oder Skips.**

---

## L. Sicherheit und Git

| Pruefung | Ergebnis |
| --- | --- |
| `git diff --check` | Exit 0, nur LF/CRLF-Normalisierungshinweise |
| `git status --short` | 96 Eintraege (86 vorher plus 7 neue Dateien, ein neues Verzeichnis, zwei neu geaenderte Quelldateien) |
| `git diff --stat` | 31 Dateien, 4528 Insertions, 645 Deletions |
| `git diff --cached --stat` | leer, nichts gestaged |
| Secret-Scan neuer und geaenderter Dateien | keine Treffer |
| Altes Bundle SHA-256 | unveraendert |
| Registry-Fingerprint und `validate_registry` | unveraendert, ohne Befund |
| Alle acht Vertragsfingerprints | unveraendert |
| Alte Vertragsartefakte (C16-Evaluation, C16-Vertrag, C17-Vertrag) | unveraendert |
| README U+2014 | 0 |
| `.env` | nicht gelesen, nicht veraendert |
| Absolute lokale Pfade in Artefakten | keine |

Kein Commit, kein Push, kein Deployment, keine geloeschte Datei, keine
geloeschte Forschungsdatei.

---

## M. Was noch fehlt

**Abgeschlossen und belegt:**

* Ein gemeinsamer, zeitlich korrekter Zuordnungsvertrag fuer Messung, Bundle
  und Laufzeit.
* Alle 283 Standardpartien ueber den echten Produktionspfad verglichen, null
  Divergenzen, maximale Abweichung 1,33e-15.
* Ein vollstaendig validiertes Candidate-Bundle, vorbereitet und nicht
  aktiviert.
* Der FL1-Test ist deterministisch und faellt nicht mehr mit dem Kalender.

**Blocker, in dieser Reihenfolge:**

1. **Die zeitlich korrekte Messung lehnt das Modell ab.** Verdict `rejected`,
   Gate `no_severe_segment_damage`, Segment `home_origin_league:PD`. Ohne
   Klaerung darf aus dem Kandidaten kein aktives Modell werden, und die
   historische Saisonvalidierung haette keine gueltige Messgrundlage. Zu
   klaeren ist zuerst, woher der Schaden im spanischen Heimsegment kommt: ob
   die begrenzte Karte dort systematisch die Gegnerseite unbekannt macht und
   die Korrektur dadurch einseitig wird, oder ob die Daempfung fuer dieses
   Segment schlicht nicht traegt. Das ist eine Messfrage, keine
   Parameterjustierung, und ausdruecklich keine Einladung, das Gate zu
   lockern.
2. **Die verbleibenden fuenf nicht aufloesbaren Vereine.** 33 der 126 offenen
   Partien bleiben dadurch unkorrigiert. Das ist eine Crosswalk-Frage und
   verlangt eine belegbare Quelle, kein Raten.
3. **Historische Saisonvalidierung.** Unveraendert offen. Es gibt weiterhin
   keinen End-to-End-Backtest ganzer Ligaphasen und kein Tabellen-Gate.

**Vorgeschlagene naechste Auftraege:**

| Block | Inhalt | Denkstufe |
| --- | --- | --- |
| 1 | Segmentschaden `home_origin_league:PD` unter der zeitlich korrekten Karte diagnostizieren und entscheiden, ob das Modell in dieser Form traegt | Ultra High |
| 2 | Erst danach: historische Saisonvalidierung mit Tabellen-Gate | Ultra High |
| 3 | Crosswalk-Abdeckung fuer die fuenf offenen Vereine, falls eine belegbare Quelle existiert | Medium |

Block 2 setzt Block 1 voraus. Eine Saisonvalidierung auf einem Modell, dessen
zeitlich korrekte Messung `rejected` lautet, misst nichts Entscheidbares.

**Kein Push, kein Deployment, kein neues Active-Modell.** Die historische
Saisonvalidierung und die abschliessende Release-Entscheidung stehen aus, und
vor beiden steht jetzt der Segmentschaden aus Abschnitt G.

---

**NOT READY FOR SEASON VALIDATION**
