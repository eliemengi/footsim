# V2-C20: Zeitliche Ligazuordnung und PD-Gate

Arbeitsblock auf dem C19-Stand. Auftrag war, zu klaeren, ob die in C19
abgelehnte Messung den tatsaechlichen Informationsstand vor Anstoss abbildet,
den Befund im spanischen Heimsegment exakt aufzuschluesseln und belegte Fehler
zu beheben. Ein `accepted` durfte ausschliesslich aus korrekter
Implementierung und unveraenderten Schutzanforderungen entstehen.

## Kurzfassung

1. **Der C19-Zeitvertrag war fehlerhaft.** Er begrenzte die Team-Liga-Karte
   eines Folds auf die letzte Trainingssaison und verwechselte dadurch eine
   fehlende lokale Saisondatei mit einer unbekannten Ligazugehoerigkeit. Der
   gesamte Unterschied zur akzeptierten Messung stammt aus 52 Partien, und in
   jeder davon fehlt nur die lokale Datei einer Trainingssaison.
2. **C20 korrigiert den Vertrag versioniert:** Die Karte reicht bis zur
   Vorhersagesaison. Mitgliedschaft dieser Saison steht vor Anstoss fest,
   spaetere Saisons und Spielergebnisse bleiben ausgeschlossen.
3. **Unter dem vorab eingefrorenen C20-Vertrag ist die Match-Evaluation
   `accepted`**, alle elf unveraenderten Gates erfuellt.
4. **Das PD-Heimsegment besteht nur knapp** (0,00015 unter der Grenze). Die
   Ursache ist eine echte Modellschwaeche: Die zweite Stufe hebt spanische
   Heimteams an, waehrend sie in der Stichprobe auffaellig oft verloren.
5. **Nicht releasebereit.** Die historische Saisonvalidierung fehlt, der
   Kandidat ist weder registriert noch aktiv.

---

## 1. Ausgangslage und Endzustand

| Groesse | Beginn | Ende |
| --- | --- | --- |
| Branch | `main` | `main` |
| HEAD | `4f55d80cb47254a3704589dfba3fd5dd78fa937f` | unveraendert |
| Gestagte Aenderungen | keine | keine |
| `git status --short` | 97 Eintraege | 107 Eintraege (mit diesem Bericht) |
| `git diff --stat` | 31 Dateien, 4528 Insertions, 645 Deletions | unveraendert |
| Registry-Fingerprint | `66345556ea317311fe3681700a2d4bf55d6f71a2fa303624145efe431a4f132a` | unveraendert |
| Aktives Modell | `clm-3475c9aacef6fec9-lsa165be9c` | unveraendert |
| Vollstaendige Suite | 2 failed, 5838 passed, 126 skipped, 91 errors | 2 failed, 5880 passed, 126 skipped, 91 errors |

`git diff --stat` bleibt unveraendert, weil alle Aenderungen dieses Blocks in
Dateien liegen, die bereits vor C20 unversioniert waren
(`src/ml/c16_release.py`, `tests/test_c16_damped_league_strength.py`) oder neu
sind.

### Verifikation der C19-Angaben

Gegen Artefakte, Code und Testausgaben geprueft: Paritaet 283 Partien bei
maximal 1,33e-15, Evaluation B mit Delta Log Loss -0,06487443 und Intervall
[-0,09491; -0,03469], zehn bestandene Gates, verletztes
`no_severe_segment_damage` durch `home_origin_league:PD`, Suite 2/5838/126/91,
Registry unveraendert, Kandidat nicht registriert. Alles bestaetigt.

**Abweichungen, die C19 nicht genannt hat:**

| Abweichung | Befund |
| --- | --- |
| Zaehlung `git status` | C19 nannte 96, tatsaechlich 97. Die Differenz ist der C19-Bericht selbst, geschrieben nach der Zaehlung. Harmlos. |
| **Veraltete Provenienz des C19-Kandidaten** | `clm-3475c9aacef6fec9-ls9cb9e0f6` wurde um 09:03 gebaut, der C19-Vertragstext um 09:41 korrigiert und das Artefakt neu geschrieben, der Kandidat aber nicht neu gebaut. Seine Provenienz traegt `35e9f9b9...`, Code und C19-Artefakt tragen `a1e94b02...`. Bewiesen: Mit dem damaligen Fingerabdruck entsteht der Kandidat bitgenau, die einzige Abweichung ist der veraltete Wert. **Ein C19-Fehler, in C20 gefunden.** Der Kandidat bleibt unveraendert liegen und ist ersetzt. |
| **Streu-Bundle im Modellverzeichnis** | `clm-3475c9aacef6fec9-ls34fd7f2d.json` entstand um 10:23 waehrend eines C19-Testlaufs. Ursache siehe Abschnitt 4. |

---

## 2. Die belegte Ursache

### Drei Informationsstaende, dieselben Gates

| Variante | Karte eines Folds reicht bis | Verdict | Delta Log Loss | PD-Heimsegment |
| --- | --- | --- | ---: | ---: |
| A unbegrenzt | alle lokalen Saisons | `accepted` | -0,08755954 | +0,00985 |
| B (C19) | letzte Trainingssaison | **`rejected`** | -0,06487443 | **+0,03088** |
| C (C20) | Vorhersagesaison | `accepted` | -0,08755954 | +0,00985 |

### Die Kausalkette, gemessen

1. **Die Ligaparameter sind in allen drei Varianten bitgleich.** Die
   Parameterfingerabdruecke je Fold sind identisch (`cl_2024`
   `1eb65850fb5b...`, `cl_2025` `b6a1c6897066...`). Die Begrenzung aendert
   nichts an der Schaetzung, nur an der Anwendung.
2. **A und C sind auf allen 283 Zeilen identisch.** Keiner der 14 erst ab 2025
   bekannten Vereine kommt in einer Testpartie von 2024 vor; das Zukunftswissen
   von A war also wirkungslos.
3. **Der gesamte Unterschied A gegen B (0,02268511 im mittleren Delta Log
   Loss) stammt aus genau 52 Partien**, 26-mal auf der Heim-, 26-mal auf der
   Gastseite, jedes Mal wegen eines unter B unbekannten Vereins.
4. **In jedem dieser 52 Faelle fehlt nur die lokale Datei der
   Trainingssaison:**

| Fold | Liga | Partien | lokale Dateien |
| --- | --- | ---: | --- |
| `cl_2024` | CZ1 | 8 | 2024, 2025 |
| `cl_2024` | HR1 | 7 | 2024 |
| `cl_2024` | SK1 | 7 | 2024 |
| `cl_2025` | AZ1 | 6 | 2025 |
| `cl_2025` | CY1 | 5 | 2025 |
| `cl_2025` | GR1 | 5 | 2025 |
| `cl_2025` | KZ1 | 6 | 2025 |
| `cl_2025` | NO1 | 8 | 2025 |

Fuenfzehn der 23 nationalen Ligen haben lueckenhafte lokale Dateien.
Slovan Bratislava spielte 2023 in der slowakischen Liga; nur die lokale Datei
dafuer fehlt. B hat daraus "Liga unbekannt" gemacht.

### Einordnung jeder Hypothese

| Hypothese | Ergebnis | Beleg |
| --- | --- | --- |
| Implementierungsfehler | **ausgeschlossen** | Formel, Vorzeichen, Faktorgrenzen und Paritaet exakt; 283 Partien bei 1,33e-15 |
| Informationsstandsfehler | **bestaetigt, in C19; durch C20 behoben** | Kausalkette oben |
| Abdeckungsgrenze | **Ursache des C19-Fehlers**, unter C20 aufgeloest | alle 36 PD-Partien bekommen die zweite Stufe |
| Echter verbleibender Modellnachteil | **bestaetigt** | Abschnitt 5 |
| Leakage durch A | vorhanden, aber **wirkungslos** | A gleich C auf allen Zeilen |
| Parameterverschiebung durch die Kartengrenze | **ausgeschlossen** | identische Parameterfingerabdruecke |

---

## 3. Der zeitliche Zuordnungsvertrag

### Was vor Anstoss bekannt ist

| Information | zulaessig | Begruendung |
| --- | --- | --- |
| Spielergebnisse nach dem Stichtag | nein | Die Karte liest sie gar nicht: Sie entnimmt einer Saisondatei ausschliesslich die teilnehmenden Vereine, keine Tore, keinen Ausgang. |
| Ligamitgliedschaft einer spaeteren Saison | nein | steht vor Anstoss nicht fest (Auf- und Abstieg) |
| **Ligamitgliedschaft der Vorhersagesaison** | **ja** | steht mit dem veroeffentlichten Spielplan vor Saisonbeginn fest und damit vor jeder Ligaphasenpartie derselben Saison |
| Identitaet ueber den geprueften Crosswalk | ja | statische Metadaten, kein Leistungswert |

Daraus folgt eine einzige Regel fuer Messung und Auslieferung:

```
upto_season = Vorhersagesaison = letzte Trainingssaison + 1
```

Im Fold ist das die Testsaison, im Produktionsbundle die Saison, fuer die es
freigegeben wird. Ein Fold, dessen Testsaison nicht unmittelbar folgt, wird
abgewiesen statt stillschweigend behandelt.

### Reihenfolge der Entscheidung

Die Regel wurde aus dieser Informationsklassen-Unterscheidung abgeleitet und
im Arbeitsverlauf festgehalten, **bevor** Variante C gemessen wurde. Die
Messung von C war explorativ. Der C20-Vertrag wurde danach als Artefakt
eingefroren, und erst **danach** lief die entscheidende Messung. C ist keine
Auswahl unter vielen Kandidaten, sondern die einzige Grenze, die weder
Zukunft liest noch Vorhandenes verschweigt.

### Vertragsstand

| Vertrag | Fingerabdruck | Status |
| --- | --- | --- |
| C13 | `e51f5f908e833df8cd125713ddcee3b182451e1fad4467f26093699df4695a57` | unveraendert |
| C14 | `704c9ade45f3ca1c9fde49bf1e0812f1c903f7ebc71ee07554bd9d4883dba835` | unveraendert |
| C15 | `c1a155fbf48c07f0e3f27bac0110f8032933c98be82e57c406307b6cde8f14b8` | unveraendert |
| C16 | `f6ce4b94e097015744d7a686314dcd6db3ce14359552a6b5864c773d24c5eb40` | unveraendert, Gates unveraendert |
| C16-Modellschema | `e429f461d06e7aa4cced157d51b1509494f7f89ed1d3735e5a4c192d5a7fcee6` | unveraendert |
| C17 | `03763962fb7171e296d3ecb10addedbb5cb4277a31bcc70131cdf7a1d59cbfd3` | unveraendert |
| C19 | `a1e94b02630e3d1ea6735d7926247c54cf7fee8350d8dca00a1cea3c8858cd5f` | unveraendert, Artefakt unberuehrt, durch C20 ersetzt |
| **C20** | `16a24b04a746b507997c2b6dee8c1e90d75cdd6c215b1175de7accade3f9ee35` | **neu, vor der Messung eingefroren** |

Der Kartenbauer selbst (`c19_league_map.build_team_league_map`) ist
unveraendert; C20 aendert ausschliesslich die Obergrenze, die an ihn geht.

---

## 4. Geaenderte und neue Dateien

| Datei | Zweck |
| --- | --- |
| `src/ml/c20_temporal_map.py` | **neu.** Vertrag, `prediction_season`, `fold_upto` mit Konsekutivitaetspruefung, `fold_map`, `production_map`, `comparison_resolvers` fuer den reproduzierbaren A/B/C-Vergleich, Artefaktschreiber, der nie ueberschreibt. |
| `src/ml/c16_release.py` | `build_final_bundle` nimmt Obergrenze und Vertrag ausdruecklich entgegen; ohne Angabe Bit fuer Bit der C19-Weg. Auf dem C20-Weg zusaetzlich die Bindung `c20_contract_fingerprint`. **`release` bindet jetzt die C20-Messung** und weist jedes Ergebnis ab, das nicht an den geltenden Zuordnungsvertrag gebunden ist. |
| `tests/test_c20_temporal_map.py` | **neu**, 24 Tests: Vertrag, Obergrenze, der C19-Defekt am echten Fall, Produktionskarte, C19-Reproduzierbarkeit, Kausalkette aus den Karten. |
| `tests/test_c20_candidate_parity.py` | **neu**, 17 Tests: entscheidende Messung, Kandidat, Registry-Trockenlauf, vollstaendige 283er-Paritaet. |
| `tests/test_c16_damped_league_strength.py` | Freigabe-Trockenlauf **isoliert** (siehe unten); Ablehnungstest auf den C20-Pfad; neuer Test gegen ein Ergebnis ohne Vertragsbindung. |
| `data/ml/c20_temporal_map_contract.json` | **neu**, eingefrorener Vertrag samt Fold- und Produktionskarten |
| `data/ml/c20_damped_league_strength_evaluation.json` | **neu**, entscheidende Messung |
| `data/ml/c20_runtime_parity.json` | **neu**, Paritaet ueber 283 Partien |
| `data/ml/c20_pd_diagnosis.json` | **neu**, PD-Diagnose mit Einzelpartien |
| `data/ml/models/clm-936ecce472696ccb-ls1c4f4e1d.json` | **neu**, C20-Kandidat |
| `data/ml/models/clm-3475c9aacef6fec9-ls1c4f4e1d.json` | **ungewollt entstanden**, siehe unten |

### Zwei im Block gefundene und behobene Fehler

**Der Freigabeweg band eine Messung unter der falschen Karte.** Nachdem ich
`release` auf die C20-Karte umgestellt hatte, las der Weg weiterhin das
C16-Ergebnis, das mit der unbegrenzten Karte A entstanden war. Ein echter
Release haette damit eine Freigabe uebernommen, ohne die Messung zu binden, auf
der sie beruht. Behoben: `release` liest die C20-Messung und verlangt deren
Bindung an den geltenden Vertrag. Beleg: Der Freigabeweg erzeugt jetzt
unabhaengig dieselbe Modell-ID wie der direkte Kandidatenbau.

**Ein Freigabetest schrieb in das echte Modellverzeichnis.**
`test_der_freigabeweg_traegt_das_zweistufige_bundle` lief ohne isoliertes
Wurzelverzeichnis. Der Freigabeweg schreibt das Bundle auch im Trockenlauf,
weil die Registryvalidierung Datei und Hash braucht. Jeder Testlauf legte so
ein nicht registriertes Bundle ab, waehrend der Test `wrote_anything is False`
pruefte; beides stimmte, nur meinte `wrote_anything` Registry und Zustand.
Daher stammen `clm-3475c9aacef6fec9-ls34fd7f2d.json` (C19-Lauf) und
`clm-3475c9aacef6fec9-ls1c4f4e1d.json` (C20-Regression vor der Isolierung).
Behoben: Der Test laeuft in einem temporaeren Verzeichnis mit Kopien von
Registry, Bundles und Ergebnis und prueft ausdruecklich, dass im echten
Verzeichnis keine Datei hinzukommt. Waehrend des abschliessenden Gesamtlaufs
blieb das Verzeichnis unveraendert.

Beide Streu-Bundles sind nicht registriert und wirkungslos. **Sie wurden nicht
geloescht**, weil keine bestehenden lokalen Dateien geloescht werden sollten.
Sie sollten nicht eingecheckt werden.

---

## 5. Das PD-Heimsegment

### Messwerte

| Groesse | Wert |
| --- | --- |
| n | 36 (je 2 Folds: 16 und 20) |
| Mittlerer Log Loss V0 | 0,84482 |
| Basismodell allein (Stufe 1) | 0,83105, also **-0,01377 gegen V0** |
| C20 mit zweiter Stufe | 0,85467, also **+0,00985 gegen V0** |
| C19 | 0,87570, also +0,03088 gegen V0 |
| Gate-Grenze (unveraendert) | 0,01 bei n >= 30 |
| **Abstand unter der Grenze** | **0,00015** |
| Kontextbestand, dasselbe Segment | n = 52, **-0,00666** (ML besser als V0) |

### Was die zweite Stufe hier tut

| | P(Heimsieg) | P(Remis) | P(Auswaertssieg) |
| --- | ---: | ---: | ---: |
| beobachtet | 0,556 | 0,083 | **0,361** |
| V0 | 0,530 | 0,196 | 0,275 |
| C20 | 0,583 | 0,180 | **0,237** |

Mittlere Lambdas Heim/Gast: V0 2,212 / 1,515, Basis 2,144 / 1,502,
**C20 2,401 / 1,421.** Das Basismodell ist in diesem Segment besser als V0;
erst die Ligastaerke hebt die spanischen Heimteams an und senkt die
Gegnerseite. Beobachtet wurden 36 Prozent Auswaertssiege, vorhergesagt 24
Prozent.

### Die fuenf Partien, in denen C19 und C20 sich unterscheiden

| Fold | Heim | Gast (Liga) | Ergebnis | Log Loss V0 | C20 | C19 | Faktor C20 |
| --- | ---: | --- | --- | ---: | ---: | ---: | --- |
| `cl_2024` | 298 | 7509 (SK1) | Heimsieg | 1,048 | 0,671 | 0,954 | 1,2434 / 0,8938 |
| `cl_2024` | 78 | 7509 (SK1) | Heimsieg | 0,848 | 0,535 | 0,792 | 1,2434 / 0,8938 |
| `cl_2025` | 81 | 654 (GR1) | Heimsieg | 0,525 | 0,331 | 0,627 | 1,3685 / 0,8721 |
| `cl_2025` | 77 | 611 (AZ1) | Heimsieg | 1,181 | 0,644 | 1,035 | 1,3685 / 0,8721 |
| `cl_2025` | 78 | 5721 (NO1) | Auswaertssieg | 1,063 | 1,373 | 0,904 | 1,3685 / 0,8721 |

In allen fuenf ist die Gegnerliga unter C20 bekannt, hat im Foldmodell aber
keine gelernten Parameter (`league_without_parameters`): Sie traegt 0 bei, die
spanische Seite behaelt ihre Offsets. Unter C19 fehlte der Verein ganz, beide
Seiten blieben neutral. Vier der fuenf Partien endeten mit Heimsieg; die
Korrektur hilft dort, in der fuenften schadet sie.

### Explorative Teilgruppen

**Ausdruecklich explorativ**, nach der Messung gebildet, kleines n, keine
Grundlage fuer eine Sonderregel. Ein Verein, Villarreal (football-data 94),
traegt mit vier Heimspielen ohne Sieg (Remis, drei Niederlagen, +0,2514 je
Partie gegen V0) rund drei Viertel des Segmentschadens. Nach Gegnerliga
schaden die Korrekturen gegen FL1 (n = 6), SA (n = 5) und NL1 (n = 2), gegen PL
(n = 5) helfen sie. Keine dieser Gruppen ist gross genug fuer eine Aussage.

**Keine Partie wurde entfernt, keine Segmentseite geaendert, keine PD- oder
Vereinsregel eingefuehrt.**

---

## 6. Die entscheidende Messung unter C20

Vertrag vor der Messung eingefroren; das Messskript bricht ab, wenn Code und
eingefrorenes Artefakt abweichen. Standard- und Kontextbestand vollstaendig.

| Gate | Ergebnis | Messwert |
| --- | --- | --- |
| `primary_better` | erfuellt | -0,087560 |
| `ci_excludes_zero` | erfuellt | [-0,118828; -0,055146] |
| `all_folds_same_direction` | erfuellt | -0,066131 / -0,109758 |
| `no_single_fold_carries_all` | erfuellt | -0,066131 / -0,109758 |
| `no_fold_severely_worse` | erfuellt | max -0,066131 |
| `brier_not_worse` | erfuellt | -0,06296 |
| `rps_not_worse` | erfuellt | -0,03041 |
| `calibration_holds` | erfuellt | 0,045408 gegen 0,043462 |
| `context_not_severely_damaged` | erfuellt | -0,07189 |
| `no_severe_segment_damage` | erfuellt | keine (PD knapp, siehe oben) |
| `sample_large_enough` | erfuellt | n = 283 |

**Verdict `accepted`**, Ergebnisfingerabdruck
`721fc0d8cbe4c2e0f5a7f13242e1a195eef88e1c12283a1c43728fe4289b8be7`.
Weitere Werte: Delta gegen C14 -0,07593, Delta gegen C15 +0,00756.

**Negativer Befund, kein Gate:** Im Kontextbestand ist
`away_origin_league:SA` schwer verschlechtert (n = 47, V0 1,06074, ML 1,07270,
+0,01196). Das stand bereits identisch in der akzeptierten C16-Messung. Der
eingefrorene C16-Vertrag prueft Segmentschaden nur im Standardbestand; das
Urteil bleibt davon unberuehrt, der Befund wird hier trotzdem ausgewiesen.

**Einordnung:** Die Zahlen sind mit der urspruenglichen C16-Messung
identisch. Die 283 Partien sind mehrfach benutzte Entwicklungsevidenz, **kein
unangetasteter Holdout und keine unabhaengige Bestaetigung.**

---

## 7. Kandidat, Paritaet und Registry

### Der C20-Kandidat

| Groesse | Wert |
| --- | --- |
| Modell-ID | `clm-936ecce472696ccb-ls1c4f4e1d` |
| SHA-256 | `9f2caf3a38e3385194e48311406844204e85a97e66ee1ef9c8ca949ab1f62479` |
| Ladevalidierung | `persist.load_bundle` angenommen, `validate_bundle` ohne Befund |
| Gebunden an | C20-Messung (`c16_result_fingerprint` = `721fc0d8...`), C20-Vertrag (`c20_contract_fingerprint` = `16a24b04...`) |
| Karte | 146 Vereine, bis Vorhersagesaison 2026, gelesen 2023 bis 2025 |
| Koeffizienten, Merkmale, Alpha | identisch zum aktiven Modell |
| Gamma, Alpha, Attack, Defence, Faktorgrenzen | identisch zum aktiven Modell |

Auch der Basisteil der Modell-ID hat sich geaendert. Das ist gewollt:
`build_model_id` bezieht die gebundene Evaluation mit ein ("zwei Bundles mit
denselben Gewichten, aber verschiedenem Messergebnis sind verschiedene
Artefakte"). `models_sha256`, also die Koeffizienten, ist identisch.

Fuer die laufende Saison 2026 liegen lokal noch keine nationalen Ligadateien
vor. Die Produktionskarte sagt das ausdruecklich (`seasons_used` 2023 bis
2025). Fuer die 36 aktuellen Teilnehmer aendert das nichts: Alle 31 ueber den
geprueften Crosswalk aufloesbaren Vereine sind bekannt.

### Vollstaendige Paritaet

| Groesse | Wert |
| --- | ---: |
| Partien | **283** |
| zweite Stufe angewandt | **283** (228 mit vollen Werten, 55 mit Liga ohne Parameter) |
| neutral | 0 |
| divergent | **0** |
| Profil-ID gleich Partie-ID | 283 / 283 |
| Herkunftsliga auf beiden Wegen gleich | 283 / 283 |
| maximale Abweichung Lambdas | **1,33e-15** |
| maximale Abweichung Faktoren | 0,0 |
| maximale Abweichung 1X2 | 2,22e-16 |

Toleranz vorab 1e-9. Je Fold ein eigenes Bundle aus nur dessen
Trainingssaisons; das Produktionsmodell wird nicht rueckwirkend auf fruehere
Folds angewandt. Laufzeitseite ueber den echten Produktionspfad:
Profilaufloesung zum historischen Stichtag, Merkmalsbau, validiertes Laden,
zweite Stufe.

### Registry

| Punkt | Stand |
| --- | --- |
| Kandidat registriert | **nein** |
| Trockenlauf der Registrierung | durchgerechnet, `validate_registry` ohne Befund |
| Sprung auf `active` ohne Freigabe | fail-closed abgewiesen |
| Isoliertes Schreiben | in temporaerem Verzeichnis geprueft |
| Echte Registry | unveraendert, `66345556...` |
| Aktives Modell | weiterhin `clm-3475c9aacef6fec9-lsa165be9c` mit 63 Vereinen |

### Die fuenf nicht zuordenbaren Vereine

Fenerbahce (613), PAE AEK (1899), LASK Linz (2016), Viking FK (5720), Sabah FK
(10233) stehen in ihren Ligadateien unter API-Football-IDs (611, 575, 1026,
759, 13976). Die einzige Verbindung zu ihren football-data-IDs waere ein
Namensabgleich, und selbst die Namen weichen ab ("Sabah FK" gegen "Sabah FA",
"PAE AEK" gegen "AEK Athens FC"). Die Bruecke speist sich nur aus 27
handverifizierten CL-Eintraegen und den Pokalen der fuenf Top-Ligen. **Kein
zulaessiger Beleg; sichtbar offen gelassen.** Im Auditbestand bleiben dadurch
33 von 126 offenen Partien ohne zweite Stufe.

---

## 8. Tests und Sicherheit

| Lauf | Ergebnis | Exit |
| --- | --- | ---: |
| `tests/test_c20_temporal_map.py` | 24 passed | 0 |
| `tests/test_c20_candidate_parity.py` | 17 passed | 0 |
| Freigabetests `test_c16_damped_league_strength.py` | 3 passed | 0 |
| Gezielte Regression, 28 Dateien (C10 bis C20, Identitaet, PIT, Persistenz, Inference, Runtime, Einzelspiel, Ligaphase, Modustrennung, Fixture-Plan) | **1620 passed** | 0 |
| Vollstaendige Suite, Code vor der Freigabekorrektur (ersetzt) | 2 failed, 5879 passed, 126 skipped, 91 errors | 1 |
| **Vollstaendige Suite, final** | **2 failed, 5880 passed, 126 skipped, 91 errors** | **1** |

Finale Laufzeit 2563,51 s (42:43). Exit-Codes ohne Pipe erfasst.

| Vergleich mit C19 | |
| --- | --- |
| passed | +42, exakt die neuen Tests (24 + 17 + 1) |
| failed | identisch: `test_go1_season_and_pit.py::TestSaisonWeitergabe::test_provider_ausfall_bleibt_neutral` und `test_test_isolation.py::TestReihenfolgeSpieltKeineRolle::test_umgekehrte_reihenfolge_aendert_nichts` |
| errors | 91, **testidentitaetsgleich** zu C19, ausschliesslich Datenbank- und Authentifizierungsinfrastruktur |
| skipped | 126, unveraendert |

Kein Test geloescht, keiner abgeschwaecht, kein Skip eingefuehrt. Eine
eigene, zu grobe Testannahme dieses Blocks (C19-Kandidat bitgenau baubar) wurde
durch die belegbare, staerkere Aussage ersetzt.

| Pruefung | Ergebnis |
| --- | --- |
| `git diff --check` | Exit 0 |
| `git diff --cached --stat` | leer |
| Secret-Scan neuer und geaenderter Dateien | keine Treffer |
| Absolute lokale Pfade in Artefakten | keine (einziger Treffer ist eine vorhandene Negativpruefung im Test) |
| Aktives Bundle, C19-Kandidat | Hashes unveraendert |
| C16-Evaluationsartefakt, C17-Vertragsartefakt | unveraendert |
| Vertragsfingerprints C13 bis C17 | wie im aktiven Bundle gebunden |
| README U+2014 | 0 |
| `.env` | nicht gelesen, nicht veraendert |

Nichts gestaged, committet, gepusht oder deployed. Keine Registry veraendert,
kein Modell aktiviert, keine lokale Datei geloescht.

---

## 9. Stand in fuenf getrennten Kategorien

| Kategorie | Stand |
| --- | --- |
| **1. Technische Reparatur** | **abgeschlossen.** Zeitvertrag korrigiert, Freigabeweg bindet die richtige Messung, Freigabetest isoliert, Paritaet vollstaendig. |
| **2. Match-Evaluation** | **bestanden**, unter dem eingefrorenen C20-Vertrag mit unveraenderten Gates, aber **knapp**: PD-Heimsegment 0,00015 unter der Grenze. Entwicklungsevidenz, keine unabhaengige Bestaetigung. |
| **3. Historische Saisonvalidierung** | **offen.** Es gibt weiterhin keinen End-to-End-Test ganzer Ligaphasen und kein Tabellen-Gate. |
| **4. GitHub-bereit** | **technisch als Entwicklungsstand ja.** Die Tests sind gruen bis auf die bekannten Baseline-Faelle, keine Secrets, der Standardmodus ist `off`; ein Push aktiviert nichts. Welche unversionierten Datenartefakte eingecheckt werden, entscheidest du; die beiden Streu-Bundles sollten es nicht. Keine Release-Aussage. |
| **5. VPS-bereit mit aktivem ML** | **nein.** Saisonvalidierung fehlt, der Kandidat ist weder registriert noch aktiv. Das heute aktive Modell traegt nur 63 Vereine und korrigiert im Auditbestand 75 statt 93 von 126 Partien. |

---

## 10. Aufwandsschaetzung

Abgeleitet aus dem jetzt verifizierten Zustand, ohne Zielzahl.

**Insgesamt drei Arbeitsbloecke bis zur belegten Release-Bereitschaft,
einschliesslich C20, also zwei verbleibende.** Das gilt unter der Bedingung,
dass die Saisonvalidierung besteht. Faellt sie durch, kommt ein bedingter
Block hinzu, und die Bereitschaft haengt dann an Daten, die es erst mit der
laufenden Saison gibt.

| Block | Pflicht | Inhalt | Abhaengigkeit | Abnahme | Modell |
| --- | --- | --- | --- | --- | --- |
| **C21 Saisonvalidierung** | ja | Tabellen-Gate VOR der Messung einfrieren (Rangkorrelation zur Abschlusstabelle, Kalibrierung erwarteter Punkte, Brier und Kalibrierung fuer Top 8 und Top 24, V0 gegen C20); Ligaphasen CL 2024 und 2025 (lokal vollstaendig, je 144 Partien, 36 Teams) mit den Foldmodellen rekonstruieren; Saisonpfad auf Paritaet mit dem Einzelspielpfad pruefen; die bekannten Schwaechen (PD-Heim, SA-Gast im Kontext) auf Tabellenebene gezielt auswerten | keine | eingefrorener Vertrag, reproduzierbares Artefakt, eindeutiges Verdict, ehrliche Einordnung als Entwicklungsevidenz (dieselben Saisons wie die Match-Evaluation) | Opus 5, Ultra High |
| **C22 Freigabe und Aktivierung** | ja, nur nach bestandenem C21 | Registrierung und Aktivierung des C20-Kandidaten ueber den regulaeren C11-Weg mit deiner ausdruecklichen Freigabe; isolierter Rollback- und Recovery-Probelauf; Laufzeit-Smoke-Test auf dem aktuellen Spielplan; VPS-Runbook mit Umgebung und Ruecknahme | C21 bestanden, deine Zustimmung | Registryuebergang mit Freigabetoken, Rollback geprobt, keine stille Rueckfallwirkung, Deployment-Checkliste | Opus 5, High |
| C21b Modellnachfolger | nur wenn C21 ablehnt | eine vorab festgelegte Hypothese, etwa "die zweite Stufe hebt Heimteams starker Ligen systematisch an", mit zeitlich getrennter Auswahl; pruefbar erst auf der Ligaphase 2026/27 | Ergebnis von C21, neue Daten | vorab festgelegte Hypothese, neue Evaluation vor jeder Aktivierung | Opus 5, Ultra High |
| Crosswalk fuer die fuenf Vereine | optional | nur mit belegbarer, nicht namensbasierter Quelle | eine solche Quelle | eindeutige, zeitlich zulaessige Zuordnung | Sonnet 5, Medium |
| Testhygiene der zwei Baseline-Fehler | optional | Cacheebene von `apisports_api`; PostgreSQL-abhaengige Tests | keine | gruene Suite ohne Datenbank oder saubere Kennzeichnung | Sonnet 5, Medium |

**Zusammenlegen:** C21 und C22 nicht, weil die Aktivierung vom Urteil der
Saisonvalidierung und von deiner Zustimmung abhaengt; ein gemeinsamer Block
wuerde die Aktivierung vorwegnehmen. Die zustandsfreien Teile von C22
(Runbook, isolierter Probelauf) koennten in C21 mitlaufen, ohne Qualitaet zu
verlieren. Die beiden optionalen Bloecke lassen sich zusammenlegen.

**Unsicherheit:** Die Zahl haengt an genau einer Entscheidung, dem Verdict von
C21. Das knappe PD-Segment und der Kontextbefund im SA-Gastsegment erhoehen
das Risiko, dass sich auf Tabellenebene ein Schaden zeigt. Faellt C21 durch,
ist eine belastbare Aussage erst nach der Ligaphase 2026/27 (Januar 2027)
moeglich.

---

## Status

**C20 ABGESCHLOSSEN: ZEITVERTRAG KORRIGIERT UND GEBUNDEN, MATCH-EVALUATION
KNAPP BESTANDEN, NICHT RELEASEBEREIT.**

Naechste Schritte:

1. **C21 historische Saisonvalidierung** mit vorab eingefrorenem
   Tabellen-Gate, besonders auf das PD-Heimsegment und das SA-Gastsegment
   gerichtet.
2. **Erst bei bestandenem C21:** C22 Registrierung, Aktivierung mit deiner
   Freigabe, Rollback-Probe und VPS-Runbook.
3. Bis dahin **kein aktives ML auf dem VPS**: Das heute aktive Modell traegt
   die unvollstaendige Karte.
4. Die beiden Streu-Bundles `clm-3475c9aacef6fec9-ls34fd7f2d.json` und
   `clm-3475c9aacef6fec9-ls1c4f4e1d.json` beim Einchecken auslassen.
