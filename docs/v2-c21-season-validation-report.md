# V2-C21: Historische Saisonvalidierung und Release-Vorbereitung

Arbeitsblock auf dem C20-Stand. Auftrag war, die beiden lokal vollstaendigen
Ligaphasen der Champions League mit zeitlich zulaessigen Foldmodellen ueber den
echten Saisonpfad nachzubauen, die Tabellenqualitaet von V2 gegen die
klassische Engine V0 unter einem vorab eingefrorenen Vertrag zu messen und die
Freigabe des C20-Kandidaten zustandsfrei vorzubereiten. Keine Modellaenderung,
keine echte Registryaenderung, keine Aktivierung.

## Kurzfassung

1. **Die Saisonvalidierung ist `accepted`.** Alle sechs vorab eingefrorenen
   Bedingungen sind erfuellt. Die primaere Groesse, der Zonen-RPS zum
   Saisonstart, sinkt mit V2 um 0,0424; verlangt war nur, dass er um weniger
   als 0,01 steigt. V2 ist in beiden Saisons und zu allen acht Stichtagen im
   Zonen-RPS besser als V0.
2. **Der Saisonpfad rechnet mit V2 exakt, was der Einzelspielpfad rechnet.**
   720 offene Partien ueber acht Stichtage, groesste Lambda-Abweichung 0,0.
   Kein technischer Befund. Ein Zaehlfehler im Saisonbericht wurde behoben;
   er betraf nur die Diagnose, nicht die Rechnung.
3. **Risikosignal auf Tabellenebene, vorab benannt und nicht gegatet:** Die
   Vereine aus PD und SA (je 9 Vereinssaisons) liegen mit V2 im Mittel leicht
   schlechter als mit V0 (+0,0044 bzw. +0,0129 Zonen-RPS). Das ist dieselbe
   Richtung wie die C20-Befunde im PD-Heim- und im SA-Gastsegment. Die
   Stichprobe liegt unter der Segmentmindestgroesse 30.
4. **Die Freigabe ist isoliert vollstaendig geprobt.** Der Trockenlauf baut
   genau den Kandidaten; die Aktivierung ueber den echten Freigabeweg setzt
   ihn aktiv, Laufzeit und HTTP-Schnittstelle melden Modell-ID und
   `applied = true`, der Rollback stellt den Vorzustand her. Die echte
   Registry ist unveraendert.
5. **Grenzen:** Beide Saisons sind Entwicklungsevidenz, keine unabhaengige
   Bestaetigung. Der gesamte Stand C10 bis C21 ist uncommittet; der VPS braucht
   deshalb zuerst ein vollstaendiges Code-Deployment. Die Saisontabelle bleibt
   dort ohne gesonderte Aenderung der Betriebsart bei V0.
6. **Status: `READY FOR RELEASE APPROVAL`.** Die reale Aktivierung bleibt
   deiner ausdruecklichen Freigabe vorbehalten.

---

## 1. Ausgangslage und Endzustand

| Groesse | Beginn | Ende |
| --- | --- | --- |
| Branch | `main` | `main` |
| HEAD | `4f55d80cb47254a3704589dfba3fd5dd78fa937f` | unveraendert |
| Gestagte Aenderungen | keine | keine |
| `git status --short` | 107 Eintraege | 115 Eintraege (mit diesem Bericht) |
| `git diff --stat` | 31 Dateien, 4528 Insertions, 645 Deletions | 31 Dateien, 4541 Insertions, 645 Deletions |
| Registry-Fingerprint | `66345556ea317311fe3681700a2d4bf55d6f71a2fa303624145efe431a4f132a` | unveraendert |
| Aktives Modell | `clm-3475c9aacef6fec9-lsa165be9c` | unveraendert |
| C20-Kandidat | `clm-936ecce472696ccb-ls1c4f4e1d`, SHA-256 `9f2caf3a...62479` | unveraendert, nicht registriert |
| Modellverzeichnis | 6 Dateien | dieselben 6 Dateien |
| Vollstaendige Suite | 2 failed, 5880 passed, 126 skipped, 91 errors | 2 failed, 5947 passed, 126 skipped, 91 errors |

Die +13 Insertions in `git diff --stat` sind die Korrektur in
`src/predict/cl_season_sim.py`. Alle anderen Dateien dieses Blocks sind neu.

**Verifikation der C20-Angaben** gegen Artefakte und Code: Kandidatenhash,
Bindung an die C20-Messung (Urteil accepted, Kartenvertrag `v2-c20.1`,
Fingerabdruck `16a24b04...`, Ergebnisfingerabdruck `721fc0d8...`),
PD-Heimsegment n = 36 bei +0,00985, SA-Gastsegment im Kontextbestand n = 47
bei +0,01196 (dort nicht gegatet), Suite 2/5880/126/91. Alles bestaetigt,
keine Abweichung.

---

## 2. Der eingefrorene Vertrag

`data/ml/c21_season_validation_contract.json`, Fassung `v2-c21.1`,
Fingerabdruck `5b687853edceec33963f95d011ca04fe097746adb8e6d1338d697da75eb2bc09`.
Eingefroren um 17:52:51 UTC, das Ergebnis entstand um 18:02:44 UTC. Vor dem
Einfrieren lief nur ein technischer Prototyp ohne Qualitaetsmetriken. Die
Messung prueft beim Start, dass der Vertrag im Code dem eingefrorenen
gleicht, und bricht sonst ab.

| Baustein | Festlegung |
| --- | --- |
| Frage | Uebersetzt sich V2 in eine Ligaphasenprognose, die nicht schwer schlechter ist als V0? |
| Population | CL-Ligaphasen 2024/25 und 2025/26, je 144 Partien und 36 Vereine, lokale Saisondateien, kein Netz, keine Partie ausgeschlossen |
| Prognoseart A | Saisonstart: Stichtag vor der ersten Partie, 0 bekannte Ergebnisse, 144 simuliert |
| Prognoseart B | nach Spieltag 2, 4 und 6: bekannt ist, was vor dem Stichtag gespielt wurde, entschieden nach Datum, nicht nach Spieltag |
| Stichtag | C10: `prediction_cutoff(Datum)`, 12:00 des Tages |
| Profile | nur aus Partien vor dem Stichtag (`get_cl_team_strengths` mit historischem Stichtag) |
| Ziel | tatsaechliche Abschlusstabelle, mit derselben Rangfunktion wie die Simulation |
| V0 | aktuelle klassische Engine, `FOOTSIM_ML_MODE=off`, dieselben Profile |
| V2 | C20-Modell, je Saison das zeitlich zulaessige Foldbundle, aktiv in isolierter Registry, Gewicht 1,0 (entspricht `approach=ml`) |
| Simulation | 10.000 je Lauf, Seeds 21001, 21002, 21003 |
| Primaere Metrik | Zonen-RPS ueber drei geordnete Zonen (1 bis 8, 9 bis 24, 25 bis 36), A, beide Saisons gepoolt, Mittel ueber die Seeds |
| Sekundaer | Brier Top 8, Brier Top 24, Punkte-MAE, Spearman der Plaetze, Tore-MAE, Gesamttore |
| Fehlende Profile | produktive Kaskade; zweite Stufe nach C20: fehlender Verein neutral, Liga ohne Parameter mit Beitrag 0 |
| Tiebreaker | UEFA-Reihenfolge; Disziplinarpunkte und Koeffizient fehlen, deterministischer Rueckfall auf die Team-ID, gemeldet |
| Unsicherheit | Monte Carlo ueber die Seeds; Generalisierung mit zwei Saisons nicht schaetzbar, gepaarter Bootstrap ueber Vereine nur beschreibend |
| Risikodiagnosen | PD- und SA-Vereine, vorab benannt, nicht gegatet |
| Entscheidung | accepted genau dann, wenn S1 bis S6 erfuellt sind |

### Die Gates

| Gate | Bedingung | Herkunft der Schwelle |
| --- | --- | --- |
| S1 | Zonen-RPS(V2) minus Zonen-RPS(V0), A gepoolt, < 0,01 | `cl_evaluate.SEVERE_DEGRADATION` aus dem C16-Vertrag, uebernommen |
| S2 | dieselbe Differenz je Saison < 0,01 | dieselbe |
| S3 | Zonen-RPS, B gepoolt ueber alle sechs Stichtage, Differenz < 0,01 | dieselbe |
| S4 | Brier Top 8 und Top 24, A gepoolt, je Differenz < 0,01 | dieselbe |
| S5 | Spannweite der primaeren Differenz ueber die Seeds <= 0,002 | ein Fuenftel von S1, damit kein Entscheid vom Seed abhaengt |
| S6 | technische Integritaet: je Stichtag 144 Partien, 8 je Verein, bekannt plus offen vollstaendig; Saison- gleich Einzelspielpfad bis 1e-9; keine Profilquelle am oder nach dem Stichtag; echte Registry und Modellverzeichnis unveraendert | Toleranz wie C18 bis C20 |

Nichtunterlegenheit statt Ueberlegenheit, weil die Ueberlegenheit auf
Spielebene bereits mit elf Gates gemessen ist und 72 Vereinssaisons keinen
Ueberlegenheitsnachweis tragen. Gefragt war, ob die Tabelle schwer
schlechter wird; genau das war der Ausgangsbefund des forensischen Audits.

### Die fuenf Partien ausserhalb der Match-Evaluation

Die Match-Evaluation umfasst 283 der 288 Ligaphasenpartien. Die fehlenden
fuenf liegen alle in 2025/26 und fielen dort wegen einer Profiltiefe unter
sechs Partien heraus. Eine Tabelle ist ohne sie nicht berechenbar; hier sind
sie mit der produktiven Rueckfallsemantik mitsimuliert.

| Partie | Datum | Spieltag | Heim | Gast | Ergebnis | Profiltiefe Heim/Gast |
| --- | --- | ---: | --- | --- | ---: | ---: |
| 551991 | 2025-09-16 | 1 | Benfica (1903) | Qarabag (611) | 2:3 | 72 / 3 |
| 552031 | 2025-09-17 | 1 | Olympiakos (654) | Pafos (11034) | 0:0 | 3 / 2 |
| 551915 | 2025-09-30 | 2 | Pafos (11034) | Bayern (5) | 1:5 | 5 / 73 |
| 552039 | 2025-10-01 | 2 | Qarabag (611) | Kopenhagen (1876) | 2:0 | 5 / 43 |
| 551978 | 2025-10-01 | 2 | Arsenal (57) | Olympiakos (654) | 2:0 | 82 / 5 |

---

## 3. Technische Saisonfunktion

### Der Weg der Messung

- **Spielplan:** der produktive Planbauer `cl_fixture_plan`. Ihm wird fuer
  die Dauer des Aufrufs die lokale Saisondatei statt des Anbieters gereicht;
  Planlogik, Duplikatpruefung, Abdeckung und Status bleiben produktiv.
- **Profile:** `get_cl_team_strengths` mit historischem Stichtag.
- **Simulation, Tabelle, Tiebreaker:** `cl_season_sim.simulate_cl_league_phase`.
- **V2:** das Foldbundle wird in einem temporaeren Wurzelverzeichnis ueber
  `apply_release(dry_run=False)` aktiv gesetzt. Umgelenkt werden genau zwei
  Stellen: die Wurzel, von der `model_registry.active_entry` liest, und die
  Wurzel, unter der die Laufzeit das aktive Bundle aufloest. Registry-,
  Freigabe- und Stufenpruefung laufen unveraendert.

| Saison | Fold | Training | Modell | gamma | Liga-alpha | Vereine in der Karte | Karte bis |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| 2024/25 | `cl_2024` | 2023 | `clm-be8db299253605dc-ls085040dc` | 1,0 | 0,1 | 132 | 2024 |
| 2025/26 | `cl_2025` | 2023, 2024 | `clm-664cc4f2959fea76-ls0743a761` | 0,75 | 0,01 | 146 | 2025 |

Beide Foldbundles wurden in der isolierten Registry mit `applied` aktiv
gesetzt, und die Laufzeit meldete in jedem Lauf genau diese ID. Das auf
spaeteren Daten trainierte Produktionsmodell kam fuer keine Saison zum
Einsatz.

### Stichtage und Planintegritaet

| Saison, Stichtag | Stichtag | bekannt | simuliert | CL-Profilquelle bis |
| --- | --- | ---: | ---: | --- |
| 2024 A Saisonstart | 2024-09-17 12:00 | 0 | 144 | 2024-06-01 |
| 2024 B nach Spieltag 2 | 2024-10-22 12:00 | 36 | 108 | 2024-10-02 |
| 2024 B nach Spieltag 4 | 2024-11-26 12:00 | 72 | 72 | 2024-11-06 |
| 2024 B nach Spieltag 6 | 2025-01-21 12:00 | 108 | 36 | 2024-12-11 |
| 2025 A Saisonstart | 2025-09-16 12:00 | 0 | 144 | 2025-05-31 |
| 2025 B nach Spieltag 2 | 2025-10-21 12:00 | 36 | 108 | 2025-10-01 |
| 2025 B nach Spieltag 4 | 2025-11-25 12:00 | 72 | 72 | 2025-11-05 |
| 2025 B nach Spieltag 6 | 2026-01-20 12:00 | 108 | 36 | 2025-12-10 |

Zu jedem Stichtag: 144 Partien, 36 Vereine mit je 8 Partien, bekannt plus
offen gleich 144, kein bekanntes Ergebnis am oder nach dem Stichtag, keine
offene Partie davor, keine CL-Profilquelle am oder nach dem Stichtag.

Die tatsaechlichen Abschlusstabellen entstanden ohne Rueckfall auf die
Team-ID; an beiden Zonengrenzen (Platz 8/9 und 24/25) waren die Vereine nicht
in allen Kriterien gleich. 2025/26 war an Platz 24 extrem eng: fuenf Vereine
mit 9 Punkten auf den Plaetzen 23 bis 27, entschieden ueber die Tordifferenz.

### Paritaet Saisonpfad gegen Einzelspielpfad

Zu jedem Stichtag wurden alle offenen Partien einmal ueber den Saisonpfad und
einmal ueber `simulate_cl_league_phase_match` mit `kickoff = Stichtag`
gerechnet und die Lambdas je Partie verglichen.

| Stichtag | verglichen | groesste Abweichung |
| --- | ---: | ---: |
| 2024 A / B2 / B4 / B6 | 144 / 108 / 72 / 36 | 0,0 |
| 2025 A / B2 / B4 / B6 | 144 / 108 / 72 / 36 | 0,0 |
| **gesamt** | **720** | **0,0** (Toleranz 1e-9) |

In jedem V2-Lauf wirkte ML auf jede offene Partie, die zweite Stufe ebenso.
Davon mit vollen Ligaparametern bzw. mit einer Liga ohne Parameter
(Beitrag 0): 2024 zum Saisonstart 121 und 23, 2025 zum Saisonstart 107 und
37. In jedem V0-Lauf wirkte ML auf keine Partie.

### Befund und Korrektur im Saisonpfad

`cl_season_sim` zaehlte im Diagnoseblock `ml.league_stage` Partien mit dem
Zustand `league_without_parameters` als `not_applied`, obwohl die zweite
Stufe dort regulaer gewirkt hat (Beitrag 0 fuer eine Liga ohne Parameter,
C20-Semantik). Die Rechnung war richtig, der Bericht nicht. Korrigiert: Der
Bericht fuehrt jetzt `applied`, `applied_full_parameters`,
`applied_league_without_parameters` und `not_applied` getrennt. Bestehende
Tests gruen, das Modell unveraendert.

Die Messung selbst schrieb nichts in das echte Modellverzeichnis und
veraenderte die echte Registry nicht; beides prueft sie am Ende und zaehlt
eine Abweichung als technischen Befund.

---

## 4. Saison-Evaluation

Ergebnis: `data/ml/c21_season_validation.json`, gebunden an den
Vertragsfingerabdruck, Laufzeit 358 s.

### 4.1 Die Gates

| Gate | gemessen | Grenze | erfuellt |
| --- | ---: | ---: | :---: |
| S1 primaere Differenz, A gepoolt | **-0,04241** | < 0,01 | ja |
| S2 je Saison | 2024: -0,01945; 2025: -0,06536 | < 0,01 | ja |
| S3 aktualisierte Prognosen, B gepoolt | -0,01750 | < 0,01 | ja |
| S4 Brier Top 8 / Top 24, A gepoolt | -0,05671 / -0,02810 | < 0,01 | ja |
| S5 Spannweite ueber die Seeds | 0,00089 | <= 0,002 | ja |
| S6 technische Integritaet | keine Befunde | keine | ja |

**Urteil: `accepted`.** Negative Werte heissen: V2 besser als V0.

### 4.2 Prognoseart A: Saisonstart

| Metrik | 2024 V0 | 2024 V2 | 2025 V0 | 2025 V2 |
| --- | ---: | ---: | ---: | ---: |
| Zonen-RPS | 0,2136 | **0,1942** | 0,2052 | **0,1398** |
| Brier Top 8 | 0,2032 | **0,1668** | 0,1734 | **0,0964** |
| Brier Top 24 | 0,2241 | **0,2216** | 0,2370 | **0,1833** |
| Punkte-MAE | 4,60 | **4,38** | 4,21 | **3,29** |
| Spearman Platz | 0,128 | **0,424** | 0,033 | **0,634** |
| Tore-MAE je Verein | 4,69 | **4,07** | 4,14 | **3,51** |
| erwartete Gesamttore (tatsaechlich) | 494,1 (470) | **481,8** (470) | 500,5 (487) | 500,0 (487) |
| V2 besser im Zonen-RPS | | 20 von 36 Vereinen | | 27 von 36 Vereinen |

V0 ordnet die Vereine zum Saisonstart kaum (Spearman 0,13 und 0,03); V2
ordnet sie deutlich (0,42 und 0,63).

### 4.3 Prognoseart B: nach Spieltagen

| Stichtag | Zonen-RPS V0 | V2 | Differenz | Brier Top 8 V0 / V2 | Brier Top 24 V0 / V2 | Punkte-MAE V0 / V2 | Spearman V0 / V2 |
| --- | ---: | ---: | ---: | --- | --- | --- | --- |
| 2024 nach 2 | 0,1465 | 0,1334 | -0,0131 | 0,171 / 0,145 | 0,1218 / 0,1216 | 3,73 / 3,44 | 0,564 / 0,667 |
| 2024 nach 4 | 0,1142 | 0,1014 | -0,0129 | 0,163 / 0,135 | 0,0656 / **0,0676** | 2,78 / 2,55 | 0,701 / 0,763 |
| 2024 nach 6 | 0,0443 | 0,0398 | -0,0046 | 0,065 / 0,056 | 0,0232 / **0,0239** | 1,37 / 1,27 | 0,925 / 0,939 |
| 2025 nach 2 | 0,1779 | 0,1320 | -0,0459 | 0,168 / 0,116 | 0,1876 / 0,1477 | 3,56 / 2,66 | 0,473 / 0,749 |
| 2025 nach 4 | 0,1445 | 0,1270 | -0,0174 | 0,149 / 0,118 | 0,1398 / 0,1365 | 2,77 / 2,46 | 0,763 / 0,828 |
| 2025 nach 6 | 0,1421 | 0,1309 | -0,0112 | 0,147 / 0,126 | 0,1373 / 0,1359 | 1,96 / 1,85 | 0,856 / 0,868 |

Einzige Stellen, an denen V2 schlechter ist: Brier Top 24 in 2024 nach
Spieltag 4 (+0,0020) und 6 (+0,0007), beide weit unter der Grenze. Dass der
Zonen-RPS 2025 nach Spieltag 6 kaum unter dem Wert nach Spieltag 4 liegt,
ist die Enge der Tabelle (fuenf Vereine mit 9 Punkten um Platz 24), kein
Rechenfehler: V0 zeigt dasselbe Muster.

### 4.4 Verteilungen

| Groesse | 2024 | 2025 |
| --- | --- | --- |
| Streuung der Punkte, tatsaechlich | 5,51 | 5,03 |
| Streuung der erwarteten Punkte V0 / V2 | 2,01 / 2,62 | 1,61 / 2,45 |
| Spanne erwartete Punkte V0 / V2 / tatsaechlich | 7,0 bis 15,0 / 5,9 bis 16,6 / 0 bis 21 | 8,1 bis 14,6 / 5,0 bis 15,8 / 1 bis 24 |
| mittlerer Platzfehler V0 / V2 | 9,46 / 8,55 | 9,53 / 7,05 |

Erwartete Punkte sind Mittelwerte ueber 10.000 Simulationen und muessen
enger streuen als realisierte Punkte. V2 staucht die Tabelle weniger als V0,
beide bleiben deutlich unter der realisierten Streuung. Die Abweichung der
Gesamttore ist in beiden Engines positiv (V2 +11,8 und +13,0, V0 +24,1 und
+13,5).

### 4.5 Unsicherheit, getrennt

| Art | Groesse | Wert |
| --- | --- | --- |
| Monte Carlo | Spannweite der primaeren Differenz ueber drei Seeds | 0,00089 |
| Monte Carlo | groesste Spannweite des Zonen-RPS eines Laufs ueber die Seeds | 0,0017 |
| Generalisierung | Unterschied der primaeren Differenz zwischen den Saisons | 0,0459 (-0,0195 gegen -0,0654) |
| beschreibend | gepaarter Bootstrap ueber Vereine je Saison, 2000 Ziehungen | [-0,0719; -0,0138] |

Die Streuung zwischen den Saisons ist rund fuenfzigmal groesser als die
Monte-Carlo-Streuung. Das Urteil haengt nicht vom Seed ab; wie gross der
Vorteil in einer dritten Saison waere, laesst sich aus zwei Saisons nicht
sagen. Das Bootstrap-Intervall repliziert keine Saisons und ist kein
Konfidenzintervall der Generalisierung.

### 4.6 Wo V2 verliert

Groesste Verschlechterungen im Zonen-RPS zum Saisonstart: 2024 Girona
(PD, Platz 33, +0,166), RB Leipzig (BL1, Platz 32, +0,161), Real Madrid
(PD, Platz 11, +0,138), Feyenoord (NL1, Platz 19, +0,127); 2025 Club Brugge
(BE1, Platz 19, +0,282), Qarabag (AZ1, Platz 22, +0,202), Sporting (PT1,
Platz 7, +0,139), Villarreal (PD, Platz 35, +0,130). Groesste Gewinne: 2024
Salzburg (-0,220), Atletico (-0,213), Arsenal (-0,178), Aston Villa
(-0,152); 2025 Slavia Prag (-0,368), PSV (-0,300), Union Saint-Gilloise
(-0,294), Liverpool (-0,277). Muster: V2 verschiebt Vereine staerker nach
ihrer Herkunftsliga; wo ein Verein gegen seine Liga laeuft, verliert V2.
Die Namen stammen aus den Teamtabellen der lokalen Saisondateien.

---

## 5. PD und SA auf Tabellenebene

Vorab benannt, weil C20 zwei auffaellige Match-Segmente zeigte:
`home_origin_league:PD` (Standardbestand, gegatet, n = 36, +0,00985, knapp
unter der Grenze) und `away_origin_league:SA` (Kontextbestand, nicht
gegatet, n = 47, +0,01196). Ein Match-Segment ist keine Vereinsmenge: Heim-
und Auswaertsspiele desselben Vereins fallen in der Tabelle zusammen.
Berichtet werden deshalb Tabellenmetriken der Vereine dieser Ligen, nicht
als Ersatz der Match-Segmente.

| Liga | Vereinssaisons | Differenz Zonen-RPS | Differenz Punktefehler | V2 minus V0, erwartete Punkte | tatsaechlich minus V2 | tatsaechlich minus V0 | auswertbar |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| PD | 9 | **+0,0044** | -0,34 | +1,89 | -1,16 | +0,73 | nein (< 30) |
| SA | 9 | **+0,0129** | +0,02 | -0,16 | +2,71 | +2,56 | nein (< 30) |

**PD, Verein fuer Verein.** V2 hebt jeden spanischen Verein an (im Mittel
+1,9 erwartete Punkte). Das hilft, wo der Verein stark war, und schadet, wo
er es nicht war:

| Saison | Verein | Platz, Punkte | Zonen-RPS V0 | V2 |
| --- | --- | --- | ---: | ---: |
| 2024 | Barcelona | 2, 19 | 0,176 | **0,057** |
| 2024 | Atletico | 5, 18 | 0,426 | **0,213** |
| 2024 | Real Madrid | 11, 15 | **0,133** | 0,271 |
| 2024 | Girona | 33, 3 | **0,067** | 0,234 |
| 2025 | Barcelona | 5, 16 | 0,193 | **0,073** |
| 2025 | Real Madrid | 9, 15 | **0,064** | 0,073 |
| 2025 | Atletico | 14, 13 | 0,133 | **0,078** |
| 2025 | Athletic | 29, 8 | **0,116** | 0,219 |
| 2025 | Villarreal | 35, 1 | **0,234** | 0,364 |

**SA.** 2024 senkt das fruehe Foldmodell (Liga-alpha 0,1, gamma 1,0) die
italienischen Vereine ab und verliert bei Inter, Atalanta und Milan; 2025
hebt es sie leicht an und gewinnt bei Inter, Juventus und Atalanta. Beide
Engines unterschaetzen italienische Vereine um rund 2,6 Punkte.

**Einordnung.** Die Richtung stimmt mit C20 ueberein: Die zweite Stufe
behandelt eine Liga als Block und trifft Vereine, die gegen ihre Liga laufen.
Neun Vereinssaisons je Liga tragen keine Aussage; der Vertrag hat diese
Diagnosen deshalb vorab ausdruecklich nicht gegatet. Sie aendern das Urteil
nicht, bleiben aber das benannte Restrisiko fuer die Beobachtung in der
Ligaphase 2026/27.

---

## 6. Match-Evaluation (Stand C20, unveraendert)

`accepted` unter dem eingefrorenen C20-Vertrag, alle elf Gates erfuellt,
283 Partien, Delta Log Loss -0,08756. Knappstes Gate: PD-Heimsegment
+0,00985 gegen die Grenze 0,01. In C21 nicht neu gemessen und nicht
veraendert.

---

## 7. Release-Vorbereitung, zustandsfrei

Alles in temporaeren Wurzelverzeichnissen mit einer Kopie von Registry,
deren Bundles und der C20-Messung, ueber dieselben Funktionen, die spaeter
real laufen (`src/ml/c21_release_readiness.py`).

### 7.1 Trockenlauf des exakten Kandidaten

| Pruefung | Ergebnis |
| --- | --- |
| Status | `dry_run_ok`, "Trockenlauf beendet - nichts wurde geschrieben" |
| gebaute Modell-ID | `clm-936ecce472696ccb-ls1c4f4e1d`, gleich dem Kandidaten |
| gespeicherte Kandidatendatei | SHA-256 `9f2caf3a...`, gleich dem C20-Stand |
| Neubau gegen gespeicherten Kandidaten | abweichend nur `created_at`, `provenance/git_status/porcelain`, `provenance/git_status/untracked` |
| modellrelevante Felder (Koeffizienten, Ligastaerke, Karte, Bindungen, Datensatz- und Integritaetshash) | identisch |
| temporaere und echte Registry | unveraendert |
| Dauer | rund 146 s |

**Eine eigene Annahme dieses Blocks war zu eng.** Die erste Fassung der
Pruefung liess als Baumetadaten nur Zeitpunkt und Commit zu. Der erste
Trockenlauf zeigte, dass das Bundle auch den Zustand des Arbeitsbaums
festhaelt, der sich seit C20 durch die C21-Dateien geaendert hat. Die
Pruefung beschreibt jetzt die Bauumgebung vollstaendig (Zeitpunkt, Commit,
Arbeitsbaum, Plattform, Bibliotheksversionen) und meldet jede andere
Abweichung einzeln. Ein Test haelt fest, dass Modellfelder nie als
Baumetadaten gelten.

### 7.2 Aktivierung und Rollback

| Schritt | Ergebnis |
| --- | --- |
| aktiv vorher | `clm-3475c9aacef6fec9-lsa165be9c` |
| `release(dry_run=False)` | `applied`, aktiv: `clm-936ecce472696ccb-ls1c4f4e1d` |
| Laufzeit mit `approach=ml` | `mode active`, `applied true`, Modell-ID des Kandidaten, zweite Stufe `applied` |
| Laufzeit ohne Ansatz | `mode off`, `applied false`, Modell-ID `null` |
| `rollback(dry_run=False)` | `rolled_back`, aktiv wieder `clm-3475c9aacef6fec9-lsa165be9c` |
| Laufzeit nach Rollback | `applied true`, Modell-ID `clm-3475c9aacef6fec9-lsa165be9c` |
| echte Registry, echtes Modellverzeichnis | unveraendert |

### 7.3 HTTP-Schnittstelle

`/api/simulate` mit echtem CSRF-Token (Projektkonvention `mit_csrf`), Bayern
gegen Arsenal, Kandidat isoliert aktiv:

| Request | Antwort `ml` |
| --- | --- |
| mit `approach: "ml"` | `mode active`, `applied true`, `model_id clm-936ecce472696ccb-ls1c4f4e1d`, `league_stage.status applied` |
| ohne `approach` | `mode off`, `applied false`, `model_id null` |
| nach dem isolierten Block, mit `approach: "ml"` | wieder `clm-3475c9aacef6fec9-lsa165be9c` aus der echten Registry |

### 7.4 Was der Freigabeweg liest

Ermittelt mit einem Dateiprotokoll ueber Trockenlauf, Aktivierung und
Laufzeitantwort. Aus dem Repository gelesene, unversionierte Dateien:

| Datei | gelesen von |
| --- | --- |
| `data/ml/c20_damped_league_strength_evaluation.json` | `release()`; ohne sie `refused` |
| `data/ml/c10_prediction_cutoff_contract_2023-2025.json` | Registryeintrag, Feld `c10_contract_fingerprint` |
| `data/ml/c16_damped_league_strength_evaluation.json` | C17-Vertragsfingerabdruck im Bundle, relativ zum Arbeitsverzeichnis |
| `.env` (gitignoriert) | `load_dotenv()` beim Import von `app.py` und `src/api/*`; Inhalt weder ausgegeben noch veraendert |

Die echte Registry und die echten Bundles las nur die Probe selbst (Kopie,
Feldvergleich, Fingerabdruckpruefung), nicht der Freigabeweg. Aktivierung und
Laufzeitantwort lasen keine weitere unversionierte Datei. Alle 65 gelesenen
`data/historical`-Dateien sind versioniert.

### 7.5 Befunde fuer das Deployment

| Befund | Folge |
| --- | --- |
| C10 bis C21 sind uncommittet, darunter Registry, Freigabeweg und zweite Stufe | Der VPS braucht zuerst ein vollstaendiges Code-Deployment. Welche Dateien committet werden, entscheidest du. |
| Die Saisontabelle (`/api/cl-season-sim`) kennt keinen `approach`, sie folgt nur `FOOTSIM_ML_MODE` | Nach der Aktivierung wirkt V2 fuer Einzelspiele mit `approach=ml` (Standard der Oberflaeche). Die Tabelle bleibt bei V0, bis die Betriebsart gesondert auf `active` mit Gewicht 1,0 gesetzt wird; genau in diesem Zustand hat C21 V2 gemessen. |
| `release()` baut das Modell immer neu und vergleicht die ID | Auf dem VPS entscheidet der Trockenlauf, ob Linux dieselben Koeffizienten liefert. Bibliotheken sind gepinnt (numpy 2.0.2, scikit-learn 1.6.1, scipy 1.13.1, wie beim Kandidaten). Weicht die ID ab, kein `apply`. |
| lokal `core.autocrlf=true`, Artefakte mit CRLF | Dateihashes unterscheiden sich auf dem VPS. Unkritisch: Alle Vergleiche des Freigabewegs sind Inhaltshashes. |
| vor der Aktivierung, mit neuem Code und ohne aktives Modell | `approach=ml` faellt ueber den Registrygate auf V0 zurueck, fail-closed |

### 7.6 Runbook und Smoke-Test

`docs/v2-c21-release-runbook.md`. Kern:

1. **F1 Commit, F2 Push, F3 VPS-Code mit Trockenlauf, F4 Aktivierung**,
   jeweils gesondert freigegeben; F5 Betriebsart ausdruecklich nicht Teil
   dieser Freigabe.
2. Auf dem VPS zuerst nur lesen: `git status --porcelain`, `git log -1`,
   Registry vorhanden, ML-Schalter, Dienstname. Abbruch bei lokalen
   Aenderungen an versionierten Dateien.
3. Sicherung von `data/ml` und HEAD, dann `git merge --ff-only`, Neustart,
   `run_ml.py --release-c16 dry-run` mit Stopkriterium Modell-ID.
4. `run_ml.py --release-c16 apply`, danach `--registry show` und `validate`.
5. Smoke-Test: `c21_release_readiness.runtime_answer('ml')` und `('off')`
   ohne Netz, dazu `/api/simulate` per curl mit CSRF-Token.
6. Rollback: `run_ml.py --release-c16 rollback`; Code zurueck nur mit
   `git switch --detach`, kein `reset --hard`.

Mitzuliefernde Artefakte: die C20-Messung, der C10-Vertrag, die C16-Messung
und empfohlen die Kandidatendatei. Nicht mitzuliefern: die lokale Registry,
die drei Streu-Bundles, das lokal aktive Bundle, erzeugte Daten, `.env`.

---

## 8. Geaenderte und neue Dateien

| Datei | Art | Inhalt |
| --- | --- | --- |
| `src/predict/cl_season_sim.py` | geaendert | Zaehlung der zweiten Stufe im Saisonbericht |
| `src/ml/c21_season_validation.py` | neu | Vertrag, Stichtage, Plan, tatsaechliche Tabelle, isolierte Aktivierung, Metriken, Entscheidung, Messablauf |
| `src/ml/c21_release_readiness.py` | neu | Trockenlauf, Aktivierung und Rollback isoliert, Feldvergleich, Laufzeitantwort |
| `tests/test_c21_season_validation.py` | neu | 44 Tests |
| `tests/test_c21_release_readiness.py` | neu | 23 Tests |
| `data/ml/c21_season_validation_contract.json` | neu | eingefrorener Vertrag |
| `data/ml/c21_season_validation.json` | neu | Messergebnis |
| `docs/v2-c21-release-runbook.md` | neu | Runbook und Smoke-Test |
| `docs/v2-c21-season-validation-report.md` | neu | dieser Bericht |

Kein Modellcode, kein Feature, kein Hyperparameter, keine Schwelle
veraendert. Kein bestehender Test geloescht oder abgeschwaecht.

---

## 9. Tests und Sicherheit

| Lauf | Ergebnis | Exit |
| --- | --- | ---: |
| Bestehende Saisontests nach der Zaehlkorrektur | 19 passed | 0 |
| `tests/test_c21_season_validation.py` und `tests/test_c21_release_readiness.py` | **67 passed** (330 s, davon Trockenlauf 152 s und Aktivierung 174 s) | 0 |
| Gezielte Regression, 9 Dateien (Saisonsimulation, C18-Diagnose und -Paritaet, C19-Abdeckung, C20-Kandidat und -Karte, Laufzeit, CL-API, Registry) | **422 passed** (12:43) | 0 |
| **Vollstaendige Suite** | **2 failed, 5947 passed, 126 skipped, 91 errors** (55:25) | **1** |

Exit-Codes ohne Pipe erfasst, die Suite regulaer zu Ende gelaufen.

| Vergleich mit C20 | |
| --- | --- |
| passed | +67, exakt die neuen Tests (44 + 23) |
| failed | identisch: `test_go1_season_and_pit.py::TestSaisonWeitergabe::test_provider_ausfall_bleibt_neutral` und `test_test_isolation.py::TestReihenfolgeSpieltKeineRolle::test_umgekehrte_reihenfolge_aendert_nichts` |
| errors | 91, testidentitaetsgleich zu C20, ausschliesslich Datenbank- und Authentifizierungsinfrastruktur |
| skipped | 126, unveraendert |

Kein Test geloescht, keiner abgeschwaecht, kein Skip eingefuehrt. Die zwei
neuen `skip`-Zweige greifen nur, wenn Kandidat oder C21-Ergebnis fehlen, wie
in `test_c20_candidate_parity.py`; in diesem Lauf griffen sie nicht.
Registry-Fingerprint und Modellverzeichnis waren auch nach der Suite
unveraendert.

| Pruefung | Ergebnis |
| --- | --- |
| C21-Vertragsfingerabdruck: Code, eingefrorenes Artefakt, Ergebnis | alle `5b687853...`, eingefroren vor dem Ergebnis |
| C20-Vertrag und -Messung | Fingerabdruck `16a24b04...` gebunden, Urteil accepted |
| Kandidatendatei | SHA-256 `9f2caf3a...`, unveraendert |
| Registry-Fingerprint | `66345556...`, unveraendert |
| Modellverzeichnis | dieselben 6 Dateien, kein Streu-Bundle entstanden |
| `git diff --cached` | leer |
| Secret-Scan ueber 114 geaenderte und neue Dateien | keine Treffer; README enthaelt nur die dokumentierten Platzhalter |
| Absolute lokale Pfade in neuen Artefakten, Doku, Code | keine |
| U+2014 in README und allen neuen Dateien | 0 |
| `git diff --check` | Exit 0, keine Leerzeichenfehler in neuen Dateien |
| `.env` | nicht gezielt gelesen, nicht veraendert; beim Import von der Anwendung geladen (7.4) |

Nichts gestaged, committet, gepusht oder deployed. Keine echte
Registryaenderung, keine Aktivierung, kein Freigabezeichen fuer die echte
Registry, keine Aenderung der Standardbetriebsart, keine Datei geloescht.
Alle Bundle- und Registryoperationen liefen in temporaeren Verzeichnissen.

---

## 10. Stand in sechs getrennten Kategorien

| Kategorie | Stand |
| --- | --- |
| **1. Technische Saisonfunktion** | **belegt.** Echter Saisonpfad mit isolierter Registry und Foldbundles, Planintegritaet an allen acht Stichtagen, 720 von 720 offenen Partien paritaetisch mit dem Einzelspielpfad, keine technischen Befunde. Ein Diagnose-Zaehlfehler behoben. |
| **2. Match-Evaluation** | **bestanden** (C20), alle elf Gates, knapp im PD-Heimsegment. Entwicklungsevidenz. |
| **3. Saison-Evaluation** | **bestanden** (`accepted`), S1 bis S6, deutlich: V2 zu allen acht Stichtagen besser im Zonen-RPS. Vorab benanntes, nicht gegatetes Restrisiko bei PD- und SA-Vereinen. Entwicklungsevidenz. |
| **4. Entwicklungsfreigabe** | **erteilt im Sinne der Vertraege.** Beide Messungen unter vorab eingefrorenen Vertraegen bestanden; der Kandidat traegt `release_stage approved` mit der Klasse Entwicklungsevidenz. |
| **5. Unabhaengige Bestaetigung** | **nicht vorhanden.** Beide Saisons sind dieselben, auf denen die Match-Evaluation und die Modellform entstanden. Frueheste unabhaengige Pruefung: Ligaphase 2026/27, abgeschlossen Ende Januar 2027. |
| **6. Aktivierungs- und Deploymentbereitschaft** | **bereit zur Freigabe.** Trockenlauf, Aktivierung, Laufzeit, HTTP und Rollback isoliert bestanden; Runbook mit Stopkriterien liegt vor. Nicht ausgefuehrt. Auf dem VPS zuerst Code-Deployment (F1 bis F3), Stopkriterium Modell-ID im VPS-Trockenlauf. |

---

## 11. Aufwandsschaetzung

Abgeleitet aus dem jetzt verifizierten Zustand, ohne Zielzahl.

**Bis zur aktiven Freigabe bleibt ein Pflichtblock**, dazu ein zeitgebundener
Block fuer die unabhaengige Bestaetigung.

| Block | Pflicht | Inhalt | Abhaengigkeit | Abnahme | Modell |
| --- | --- | --- | --- | --- | --- |
| **C22 Freigabe und Deployment** | ja | Commitumfang festlegen und committen (F1), Push (F2), VPS nur lesend pruefen, sichern, Code aktualisieren, Trockenlauf mit Stopkriterium (F3), `apply` (F4), Smoke-Test 7a und 7b, Rollbackweg bereithalten | deine Freigaben F1 bis F4 | Modell-ID im VPS-Trockenlauf gleich, `applied` im Smoke-Test, Registry validiert, Rollback dokumentiert | Opus 5, High |
| C23 Bestaetigung auf 2026/27 | fuer eine unabhaengige Aussage | Vertrag wie C21 fuer die Ligaphase 2026/27 vorab einfrieren, Modell unveraendert; Auswertung nach dem letzten Spieltag | Spielplan und Ergebnisse 2026/27; Auswertung ab Ende Januar 2027 | eingefrorener Vertrag vor der Auswertung, Urteil ohne Aenderung | Opus 5, High |
| F5 Standardbetriebsart | optional, eigene Entscheidung | `FOOTSIM_ML_MODE=active`, Gewicht 1,0, damit auch die Saisontabelle V2 zeigt | C22 | Smoke-Test der Tabelle, Rueckweg `off` | Sonnet 5, Medium |
| Beobachtung PD und SA | empfohlen | Tabellenmetriken der PD- und SA-Vereine in 2026/27 getrennt mitfuehren | C23 | vorab festgelegte Auswertung | im C23 enthalten |
| Testhygiene der Baseline-Fehler | optional | die zwei bekannten Fehler und die 91 datenbankabhaengigen Fehler sauber kennzeichnen oder beheben | keine | gruene Suite ohne Datenbank oder klare Kennzeichnung | Sonnet 5, Medium |

**Zusammenlegen:** C22 nicht mit C23; C23 kann erst nach dem letzten
Spieltag 2026/27 urteilen. Unabhaengig ist die Messung, weil Modell und
Vertrag vor den Daten feststehen, auch wenn sie wie C21 rueckblickend mit
historischen Stichtagen rechnet. Staerker waere eine zusaetzlich vor dem
ersten Anpfiff mit Zeitstempel eingefrorene Saisonstartprognose: Die beiden
gemessenen Ligaphasen begannen am 17.09.2024 und am 16.09.2025, nach diesem
Rhythmus beginnt 2026/27 in wenigen Tagen; der Spielplan 2026/27 liegt lokal
nicht vor (nur `CL_2023` bis `CL_2025`). F5 kann in C22 mitlaufen, wenn du
es freigibst.

**Unsicherheit:** C22 haengt an einem lokal nicht pruefbaren Punkt, der
Modell-ID im VPS-Trockenlauf. Weicht sie ab, kommt ein kurzer Block hinzu
(Ursache Plattform oder Daten klaeren, gegebenenfalls den Freigabeweg eine
vorhandene, inhaltsgleich gepruefte Kandidatendatei uebernehmen lassen).

---

## Status

Die reale Aktivierung bleibt deiner ausdruecklichen Freigabe vorbehalten,
getrennt nach Commit, Push, VPS-Code und Aktivierung.

`READY FOR RELEASE APPROVAL`
