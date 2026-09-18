# V2 Release-Runbook: C20-Kandidat auf den VPS (Stand C22)

Stand: 2026-09-13, nach V2-C22. Lokal ist der Kandidat aktiv und die
lokale Anwendung laeuft mit V2. **Auf dem VPS ist nichts ausgefuehrt.**
Jeder Schritt mit Wirkung braucht eine eigene, ausdrueckliche Freigabe;
eine Freigabe fuer einen Schritt gilt nicht fuer den naechsten.
Reihenfolge: manueller Softwaretest, Freigabe, GitHub-Push, VPS.

Dieses Runbook ersetzt die C21-Fassung. Neu seit C22: Der Freigabeweg
prueft beide Nachweise und alle Dateiabhaengigkeiten selbst, kennt ein
automatisches Stopkriterium fuer die Modell-ID, und Modell und
Betriebsart werden in EINEM Schritt umgeschaltet, damit Einzelspiel und
Saisontabelle nicht auseinanderlaufen.

## 0. Was ausgeliefert werden soll

| Groesse | Wert |
| --- | --- |
| Kandidat | `clm-936ecce472696ccb-ls1c4f4e1d`, Stufe `approved`, Klasse `accepted_development_evidence` |
| Dateihash lokal | `9f2caf3a38e3385194e48311406844204e85a97e66ee1ef9c8ca949ab1f62479` (CRLF; auf dem VPS nach Checkout mit LF ein anderer Wert, siehe Abschnitt 3) |
| Inhaltshashes | `integrity/models_sha256` = `6977525c...`; kanonischer Inhalt ohne Baumetadaten = `fbb08050...` |
| Nachweise | C20-Match-Messung accepted (Kartenvertrag `16a24b04...`), C21-Saisonvalidierung accepted (Vertrag `5b687853...`, Foldmodelle `clm-be8db299253605dc-ls085040dc` und `clm-664cc4f2959fea76-ls0743a761`) |
| Lokale Registry nach C22 | Fingerabdruck `f79bc856...`, aktiv der Kandidat, Rueckfallziel `clm-3475c9aacef6fec9-lsa165be9c` |
| Zielbetriebsart | `FOOTSIM_ML_MODE=active`, `FOOTSIM_ML_WEIGHT=1.0` |

**Warum die Betriebsart dazugehoert.** Das Einzelspiel mit
`approach=ml` wendet das aktive Modell unabhaengig von der
Serverbetriebsart an. Seit C23 gilt dasselbe fuer die Saisontabelle:
`/api/cl-season-sim?approach=ml` (die Oberflaeche sendet den Ansatz in
beiden Pfaden ausdruecklich). Ohne `approach` folgen beide Endpunkte
weiterhin `FOOTSIM_ML_MODE`; das betrifft alte, noch zwischengespeicherte
Oberflaechen und jeden Aufruf ohne Ansatz. Die Betriebsart bleibt deshalb
Teil der Auslieferung: Ohne `active` zeigte ein alter Client V0. C21 hat
V2 genau im Zustand `active`, Gewicht 1,0 gemessen.

## 1. Spaeter benoetigte Eingaben

Nicht im Repository und hier nicht vorausgesetzt:

1. aktueller VPS-Host beziehungsweise IP und SSH-Zugang,
2. Name des Webdienstes (systemd) und Bestaetigung des Pfades
   (README nennt `/root/footsim` und `venv/bin/python`),
3. oeffentliche URL der Anwendung fuer den HTTP-Smoke-Test,
4. das bestehende Sicherungsverfahren der Datenbank (laut README
   PostgreSQL) samt Zugang,
5. ob auf dem VPS bereits eine Registry (`data/ml/model_registry.json`)
   liegt,
6. Python-Version auf dem VPS.

## 2. Die getrennten Freigaben

| Nr. | Schritt | Wirkung | Rueckweg |
| --- | --- | --- | --- |
| F1 | Commit lokal | Git-Historie | neuer Commit, der zuruecknimmt |
| F2 | Push nach GitHub | Stand liegt remote | Revert-Commit |
| F3 | VPS: nur lesen, sichern, Code aktualisieren, Neustart, Linux-Trockenlauf | neuer Code live, Betriebsart unveraendert | `git switch --detach <alter HEAD>`, Neustart |
| F4 | VPS: Aktivierung UND Betriebsart `active`, Neustart, HTTP-Smoke-Test | V2 in Einzelspiel und Saisontabelle | Betriebsart zurueck, `--release-c16 rollback`, Neustart |

## 3. F1: Commit-Umfang

Die vollstaendige, begruendete Liste steht im C22-Bericht
(`docs/v2-c22-local-release-report.md`, Abschnitt "Commit-Umfang").
Kurzfassung:

```bash
git status --porcelain
git add -u                                   # versionierte, geaenderte Dateien
git add src tests docs                       # neue Dateien in diesen Verzeichnissen
# Pflichtartefakte des Freigabewegs (fail-closed geprueft):
git add data/ml/c10_prediction_cutoff_contract_2023-2025.json \
        data/ml/c16_damped_league_strength_evaluation.json \
        data/ml/c17_multistage_bundle_release_contract.json \
        data/ml/c20_damped_league_strength_evaluation.json \
        data/ml/c21_season_validation_contract.json \
        data/ml/c21_season_validation.json \
        data/ml/models/clm-936ecce472696ccb-ls1c4f4e1d.json
git status --porcelain                       # lesen, nicht nur ausfuehren
git diff --cached --stat
```

Die Beleg- und Testartefakte (Vertraege und Messungen C11 bis C20, zwei
Vergleichsbundles) nennt der Bericht einzeln.

**Nicht committen:** `data/ml/model_registry.json`,
`data/ml/c15_registry_snapshot.json`, `data/ml/c15_release_journal.json`,
`data/ml/c16_damped_league_strength_release.json` (Laufzeitzustand dieses
Rechners), die Streu-Bundles `clm-3475c9aacef6fec9-ls34fd7f2d.json` und
`clm-3475c9aacef6fec9-ls1c4f4e1d.json`, `data/ml/dataset_*.json`,
`data/backtests/`, `data/snapshots/`, `data/cache/`,
`data/go*_backtest_result.json`, `data/percentiles/`, `.env`, lokale
Sicherungen.

**Zeilenenden.** Lokal gilt `core.autocrlf=true`; die Artefakte liegen
mit CRLF vor, der VPS checkt sie mit LF aus. Ihre Dateihashes sind dort
andere. Alle Vergleiche des Freigabewegs sind Inhaltshashes ueber den
gelesenen JSON-Inhalt (Modell-ID, Evaluationshash, Vertragsfingerabdruecke,
Integritaetshash, Feldvergleich des Bundles); den Dateihash im
Registryeintrag bildet der Freigabeweg auf dem VPS aus der dortigen Datei.

## 4. F3: Auf dem VPS zuerst nur lesen

```bash
cd /root/footsim                             # Pfad aus Eingabe 2
git status --porcelain                       # lokale Aenderungen an versionierten Dateien?
git status -sb
git stash list
git remote -v
git fetch origin
git log --oneline -1                         # Stand des Servers
git log --oneline origin/main..HEAD          # Commits nur auf dem VPS? -> Abbruch
git log --oneline HEAD..origin/main          # genau das kommt
ls -la data/ml data/ml/models
test -f data/ml/model_registry.json && echo "Registry vorhanden" || echo "keine Registry"
systemctl list-units --type=service | grep -i footsim
systemctl cat <webdienst> | grep -E 'WorkingDirectory|ExecStart|EnvironmentFile|FOOTSIM_ML_'
ls /etc/systemd/system/<webdienst>.service.d/ 2>/dev/null
grep -E '^FOOTSIM_ML_(MODE|WEIGHT)=' .env    # nur die beiden ML-Schalter
venv/bin/python --version
df -h . && free -m
```

**Abbruch** bei: geaenderten versionierten Dateien (kein `stash`, kein
`reset`, kein `checkout -- .`), Commits nur auf dem VPS, einem Stand, der
kein Vorgaenger von `origin/main` ist, einer vorhandenen Registry mit
unbekanntem Inhalt (erst sichern und nach dem Update mit
`venv/bin/python run_ml.py --registry show` lesen).

## 5. Sicherung vor jeder Aenderung

```bash
cd /root/footsim
TS=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p /root/footsim-backup/$TS
git rev-parse HEAD > /root/footsim-backup/$TS/HEAD.txt
cp -a data/ml /root/footsim-backup/$TS/
systemctl cat <webdienst> > /root/footsim-backup/$TS/service-unit.txt
```

Datenbank nach dem bestehenden Verfahren (Eingabe 4). Unversionierte
Laufzeitdaten (`data/snapshots/`, `data/cache/`, Datenbank) beruehrt
`git merge --ff-only` nicht; wuerde ein eingehender Commit eine dort
unversioniert liegende Datei anlegen, bricht Git ab. Dann klaeren, nicht
erzwingen.

## 6. F3: Code aktualisieren und auf Linux trocken freigeben

```bash
git merge --ff-only origin/main              # bricht bei Divergenz ab
git diff --stat HEAD@{1} HEAD -- requirements.txt   # leer: kein pip install noetig
sudo systemctl restart <webdienst>
curl -s -o /dev/null -w "%{http_code}\n" <URL>/
venv/bin/python run_ml.py --release-c16 dry-run \
    --expect-model-id clm-936ecce472696ccb-ls1c4f4e1d; echo "exit=$?"
```

**Erwartung:** `exit=0`, im Protokoll "Dateiabhaengigkeiten C9, C10,
C16, C17 vollstaendig", "C21-Saisonfreigabe gebunden ... Foldmodelle
clm-be8db299253605dc-ls085040dc, clm-664cc4f2959fea76-ls0743a761 bitgleich
wieder gebaut", "Bundle lag bereits vor, inhaltsgleich mit dem Neubau"
(als Baumetadaten sind dort zusaetzlich Plattform-, Python- und
sklearn-Felder zulaessig), `Status: dry_run_ok`.

**Stopkriterien, jedes fuer sich: kein F4.**

- `exit` ungleich 0,
- `Status: refused` (fehlende Datei, C21 nicht gebunden, abweichende
  Modell-ID) oder `blocked_by_bundle_mismatch` (Datei gleichen Namens mit
  anderem Inhalt),
- eine andere Modell-ID. Der Freigabeweg baut das Modell immer neu; ob
  Linux in der letzten Gleitkommastelle dieselben Koeffizienten liefert,
  zeigt zuerst der Neubau der beiden Foldmodelle und dann die Modell-ID.

Nach dem Code-Update, aber vor F4 gilt: Betriebsart unveraendert; ohne
aktives Modell faellt `approach=ml` ueber den Registrygate auf V0 zurueck
(fail-closed).

## 7. F4: Modell und Betriebsart in einem Schritt

```bash
cd /root/footsim
venv/bin/python run_ml.py --release-c16 apply \
    --expect-model-id clm-936ecce472696ccb-ls1c4f4e1d; echo "exit=$?"
venv/bin/python run_ml.py --registry show
venv/bin/python run_ml.py --registry validate; echo "exit=$?"
venv/bin/python run_ml.py --release-c16 recover     # erwartet: complete
```

Danach die Betriebsart als systemd-Drop-in. Der Prozess erbt die Werte,
und `load_dotenv()` ueberschreibt vorhandene Prozessvariablen nicht; die
`.env` des Servers bleibt unberuehrt.

```bash
sudo systemctl edit <webdienst>
# eintragen:
#   [Service]
#   Environment=FOOTSIM_ML_MODE=active
#   Environment=FOOTSIM_ML_WEIGHT=1.0
sudo systemctl restart <webdienst>
systemctl show <webdienst> -p Environment | tr ' ' '\n' | grep FOOTSIM_ML_
```

## 8. HTTP-Smoke-Test: Einzelspiel UND Saisontabelle

```bash
BASE=<URL>
JAR=$(mktemp)
TOKEN=$(curl -s -c "$JAR" "$BASE/" | sed -n 's/.*name="csrf-token" content="\([^"]*\)".*/\1/p' | head -1)
spiel() {
  curl -s -b "$JAR" -H "Content-Type: application/json" -H "X-CSRFToken: $TOKEN" \
       -H "Referer: $BASE/" -d "$1" "$BASE/api/simulate" \
  | python3 -c "import json,sys; m=json.load(sys.stdin)['ml']; print(m['mode'], m['applied'], m['model_id'], m['league_stage']['status'])"
}
spiel '{"competition":"cl","home_team":"H","away_team":"G","home_id":5,"away_id":57,"season":2026,"simulations":1000,"use_seed":true,"approach":"ml"}'
spiel '{"competition":"cl","home_team":"H","away_team":"G","home_id":5,"away_id":57,"season":2026,"simulations":1000,"use_seed":true}'
spiel '{"competition":"cl","home_team":"H","away_team":"G","home_id":5,"away_id":57,"season":2026,"simulations":1000,"use_seed":true,"approach":"custom","factors":{"home_strength":1.1}}'
curl -s "$BASE/api/cl-season-sim?season=2026&simulations=2000" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); m=d['ml']; s=m['league_stage']; print(d['fixtures_total'], d['fixtures_fixed'], m['mode'], m['applied'], m['model_id'], m['fixtures_with_ml'], m['fixtures_total'], s['teams_not_in_map'])"
# C23: dieselbe Tabelle mit ausdruecklichem Ansatz, wie die Oberflaeche sie abruft.
for Q in "approach=ml" "approach=classic" "approach=custom&home_advantage=1.1&goal_level=0.9"; do
  curl -s "$BASE/api/cl-season-sim?season=2026&simulations=500&$Q" \
    | python3 -c "import json,sys; m=json.load(sys.stdin)['ml']; print(m['mode'], m['effective_approach'], m['ml_fallback'], m['ml_fixtures'], m['fixtures_total'])"
done
# C23: Teamstaerken sind in der Ligaphase unzulaessig -> 400.
curl -s -o /dev/null -w "%{http_code}\n" "$BASE/api/cl-season-sim?season=2026&approach=custom&home_strength=1.1"
rm -f "$JAR"
```

Zusaetzlich seit C23 (Zeilen nach der ersten Tabellenausgabe):

```
active ml none <n> <n>
off classic none 0 <n>
off custom none 0 <n>
400
```

Meldet `approach=ml` hier `classic full`, ist auf dem VPS kein Modell
wirksam (Registry oder Bundle pruefen), unabhaengig von der Betriebsart.

**Erwartung:**

```
active True clm-936ecce472696ccb-ls1c4f4e1d applied
active True clm-936ecce472696ccb-ls1c4f4e1d applied
off False None ml_off
144 <bekannte Partien> active True clm-936ecce472696ccb-ls1c4f4e1d <n> <n> [613, 1899, 2016, 5720, 10233]
```

**Stopkriterium:** Meldet die Saisontabelle `off` oder eine andere
Modell-ID, waehrend das Einzelspiel `active` meldet, ist die Betriebsart
nicht gesetzt. Dann ist F4 nicht abgeschlossen. Die Liste der Vereine ohne
Zuordnung bleibt, bis ein belegbarer Crosswalk existiert.

## 9. Rueckweg, in dieser Reihenfolge

1. **Betriebsart:** `sudo systemctl edit <webdienst>`, die beiden
   `Environment=`-Zeilen entfernen, `sudo systemctl restart <webdienst>`.
   Danach rechnet die Tabelle wieder V0.
2. **Registry:** `venv/bin/python run_ml.py --release-c16 rollback`, dann
   `--registry validate`. Das stellt den bei `apply` gesicherten
   Vorzustand her. War die Registry vorher leer, gibt es danach kein
   aktives Modell und `approach=ml` faellt auf V0 zurueck.
3. **Code**, falls noetig, ohne destruktive Befehle:
   `git switch --detach "$(cat /root/footsim-backup/<TS>/HEAD.txt)"`,
   Neustart. `git switch` bricht ab, wenn es lokale Aenderungen
   ueberschreiben wuerde. Kein `reset --hard`, kein `clean`, kein
   `push --force`.

Den Rollback aus einem aktivierten Zustand hat C22 in einer Kopie der
lokalen Registry mit dem echten Rollback geprobt.
