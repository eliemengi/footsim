# FootSim – Spielervergleich (Phase 3)

Erstellt: Phase 3, Etappe 1
Stand: Datenschicht fertig, Perzentile und UI folgen

---

## 1. Warum es dieses Modul überhaupt getrennt gibt

Es existierte bereits `src/data/player_stats_loader.py`. Der gehört zum
**Transfervergleich** und liefert eine bewusst schmale Sicht: Minuten, Tore,
Assists, Rating – bezogen auf eine *Zielliga*.

Für den Spielervergleich wurde dieser Loader **nicht erweitert**, sondern ein
eigener gebaut (`player_compare_loader.py`).

Grund: Der Transfervergleich läuft produktiv und wurde in Phase 1 aufwendig
stabilisiert. Jede Signaturänderung an `normalize_player_statistics()` hätte
ein Regressionsrisiko erzeugt, das dem Nutzen nicht entspricht. Zwei Loader
mit klarer Zuständigkeit sind billiger als ein Loader mit zwei Aufgaben.

**Regel:** `player_stats_loader.py` wird von Phase 3 nicht angefasst.

---

## 2. Module und Zuständigkeiten

| Datei | Zuständigkeit | API-Zugriff |
|---|---|---|
| `src/data/player_metrics.py` | Metrik-Katalog, Positionsgruppen, Per-90- und Quotenlogik | nein |
| `src/data/player_compare_loader.py` | Ligawahl, Aggregation, Profil, Vergleichsaufbau | ja (1 Request/Spieler/Saison) |
| `src/api/apisports_api.py` → `_get_full()` | paginierte API-Antworten inkl. `paging` | ja |

`player_metrics.py` enthält absichtlich **keinen** Netzwerkcode. Dadurch ist die
gesamte fachliche Logik ohne API testbar – das war die Voraussetzung dafür, die
Metrikregeln überhaupt sauber absichern zu können.

---

## 3. Die wichtigste Regel: None ist nicht 0

Ein fehlender Wert ist `None` und wird **niemals** stillschweigend zu `0`.

Beispiele:

- Ein Spieler ohne Dribbelversuche hat **keine** Dribbelquote – nicht 0 %.
- Ein Feldspieler hat **keine** Paradenzahl – nicht 0 Paraden.
- Ein Spieler mit 0 gewonnenen von 10 Duellen hat **echte** 0 % – das ist ein Wert, kein `None`.

Der Unterschied zwischen „unbekannt" und „null Ereignisse" ist fachlich
entscheidend. Wird er verwischt, entstehen falsche Perzentile und falsche
Radardiagramme.

Abgesichert durch Tests in `tests/test_player_comparison.py`.

---

## 4. Positionsgruppen

API-Sports liefert unter `statistics[n].games.position` **ausschließlich** vier
Werte:

```
Goalkeeper | Defender | Midfielder | Attacker
```

Es gibt **keine** Unterscheidung zwischen CB und RB, zwischen DM, CM und AM oder
zwischen Flügel und Mittelstürmer.

### Verworfene Alternative: feinere Gruppen ableiten

Denkbar wäre gewesen, aus Toren, Assists oder Rückennummern auf eine feinere
Rolle zu schließen. Das wurde bewusst **verworfen**: Es wäre geraten, nicht
gemessen. Vier korrekte Gruppen sind besser als sechs scheinpräzise.

Sollte API-Sports später genauere Positionsdaten liefern, ist die Erweiterung
lokal: `POSITION_GROUPS` und `RADAR_PROFILES` in `player_metrics.py` ergänzen.
Der Rest des Systems bleibt unverändert.

---

## 5. Metrik-Katalog

Jede Kennzahl in `METRICS` hat:

| Feld | Bedeutung |
|---|---|
| `key` | eindeutiger Bezeichner, auch i18n-Schlüssel |
| `label` | deutscher Anzeigename |
| `kind` | `per90`, `rate`, `total` oder `value` |
| `direction` | `higher_better` oder `lower_better` |
| `description` | Kurzdefinition für das Info-Icon im UI |
| `source` | Pfad im API-Objekt, z. B. `("tackles", "total")` |
| `numerator` / `denominator` | nur bei `kind == "rate"` |

### Regeln

1. **Keine Kennzahl ohne nachweisbare Datenquelle.** Abgesichert durch
   `test_jede_metrik_hat_eine_datenquelle`.
2. **Kennzahlen, die API-Sports nicht liefert, existieren hier nicht.**
   Das betrifft ausdrücklich: xG, xA, progressive Pässe, progressive Carries,
   Pressures, Shot-Creating Actions, getrennte Luftzweikämpfe, Trackingdaten.
   Diese werden **nicht** geschätzt und **nicht** durch fachlich andere
   Kennzahlen ersetzt.
3. **Weniger, gut erklärte Kennzahlen schlagen viele unklare.** Auswahlkriterium
   war nicht „was liefert die API", sondern „was hilft beim Vergleich wirklich".

### Sonderfall `passes.accuracy`

API-Sports liefert dieses Feld **uneinheitlich**: in manchen Ligen als Prozentwert
(0–100), in anderen als absolute Anzahl angekommener Pässe. Ein Wert von 431 ist
offensichtlich keine Quote.

Lösung: `_plausible_percentage()` verwirft alles außerhalb 0–100 und gibt `None`
zurück. Lieber keine Passquote als eine falsche.

---

## 6. Radar-Profile

Pro Positionsgruppe sind **6 bis 8 Achsen** definiert. Die Obergrenze ist durch
einen Test abgesichert (`test_radar_profile_haben_hoechstens_acht_achsen`).

Begründung: Mehr Achsen werden auf einem Smartphone unlesbar und verbessern den
Vergleich nicht – sie verschlechtern ihn, weil das Auge keine Form mehr erkennt.

---

## 7. Wahl der Hauptliga

Ein `/players`-Eintrag enthält mehrere `statistics`-Blöcke: einen pro Wettbewerb
(Liga, Pokal, Champions League) und teils mehrere pro Verein.

**Entscheidung:** Ausgewertet wird ausschließlich die **Liga mit den meisten
Einsatzminuten**. Innerhalb dieser Liga werden mehrere Vereinseinträge summiert
(Vereinswechsel im Winter).

### Warum nicht alle Wettbewerbe summieren?

Der spätere Perzentil-Referenzpool besteht aus **Ligaspielern**. Würde man
Pokal- und Europapokalminuten hinzuaddieren, wäre der Spielerwert nicht mehr mit
dem Pool vergleichbar – das Perzentil wäre systematisch verzerrt.

**Preis dieser Entscheidung:** Pokal- und CL-Leistungen tauchen im Vergleich
nicht auf. Das ist bewusst gewählt und muss im UI erkennbar sein.

### Vergleichsligen

Nur die Top-5: `bl1`, `pl`, `pd`, `sa`, `fl1`. Nur dort entsteht ein sinnvoller
Referenzpool. Spielt ein Spieler in keiner davon, ist `data_available = False`.

---

## 8. Zwei Vergleichsmodi

`build_comparison()` entscheidet automatisch:

| Modus | Bedingung | Radar |
|---|---|---|
| `position` | beide Spieler in derselben Positionsgruppe | ja |
| `general` | unterschiedliche oder unbekannte Gruppen | **nein** |

Ein gemeinsames Radar über Torwart und Stürmer wäre fachlich irreführend –
die Achsen hätten für beide eine völlig andere Bedeutung. Im `general`-Modus
werden deshalb nur universell verständliche Grunddaten verglichen
(Einsätze, Minuten, Tore, Assists, Rating, Passquote, Zweikampfquote, Karten).

**Es gibt bewusst keinen Gesamtscore.** Unterschiedliche Rollen lassen sich
nicht auf eine einzige Zahl reduzieren, ohne zu lügen.

---

## 9. Was in Etappe 1 noch fehlt

`build_comparison()` liefert `percentiles_available: False`.

Perzentile brauchen einen **vollständigen Referenzpool** (alle Spieler aller
fünf Ligen einer Saison). Dieser wird in Etappe 2 durch einen separaten
Importjob aufgebaut – nicht innerhalb eines Nutzerrequests.

Bis dahin zeigt FootSim ehrliche Rohwerte statt erfundener Perzentile.

---

## 10. Regeln, die nicht verletzt werden dürfen

1. `player_stats_loader.py` (Transfervergleich) wird nicht verändert.
2. `_get()` in `apisports_api.py` wird nicht verändert – für Paginierung gibt es
   `_get_full()`.
3. Kein fehlender Wert wird zu 0.
4. Keine Kennzahl ohne API-Feld.
5. Kein gemeinsames Radar über verschiedene Positionsgruppen.
6. Kein vollständiger Ligaimport innerhalb eines Nutzerrequests.
7. Keine Perzentile aus einem unvollständigen Pool.
8. Radar: maximal 8 Achsen.

---

## 11. Eine neue Kennzahl hinzufügen

1. In `METRICS` eintragen – mit `source` (oder `numerator`/`denominator`),
   `kind`, `direction` und einer verständlichen `description`.
2. Prüfen, dass das API-Feld in `SUMMABLE_FIELDS` oder `WEIGHTED_FIELDS`
   in `player_compare_loader.py` enthalten ist, sonst wird es nicht aggregiert.
3. Falls sie ins Radar soll: in `RADAR_PROFILES` der passenden Gruppe ergänzen
   und dabei die Obergrenze von 8 Achsen einhalten.
4. Test ergänzen.

Die bestehenden Tests fangen die häufigsten Fehler automatisch ab: fehlende
Datenquelle, Kennzahl nicht im Katalog, zu viele Radarachsen.
