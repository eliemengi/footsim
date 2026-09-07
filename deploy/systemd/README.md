# Snapshot-Sammler als systemd-Timer (V2-C6)

Vorlagen für den FootSim-VPS. **Nichts davon ist aktiviert** — die
Dateien liegen im Repository, die Installation ist ein bewusster
Handgriff.

## Was hier liegt

| Datei | Zweck |
| --- | --- |
| `footsim-snapshots.service` | einmaliger Lauf (`Type=oneshot`) |
| `footsim-snapshots.timer` | täglich 04:30 UTC, mit Nachholung |

Der Sammler läuft **nicht** unter Gunicorn. Wäre er an den Webdienst
gekoppelt, liefe er bei jedem Neustart und in jedem Worker erneut.

## Vor der Installation prüfen

Beide Pfade stammen aus der bestehenden Betriebsdokumentation im
Haupt-README (`cd /root/footsim`, `venv/bin/python`). Weichen sie auf
deinem Server ab, sind es genau zwei Zeilen in `.service`:

```bash
ls -la /root/footsim/collect_snapshots.py
ls -la /root/footsim/venv/bin/python
```

Antwortet eine davon mit „No such file", zuerst `WorkingDirectory` und
`ExecStart` anpassen.

## Installation

```bash
cd /root/footsim
git pull

# 1. Trockenlauf als der Benutzer, unter dem der Timer laufen wird.
#    Schreibt nichts und beweist, dass Umgebung und Schlüssel stimmen.
venv/bin/python collect_snapshots.py --daily --dry-run --limit 3

# 2. Units installieren
sudo cp deploy/systemd/footsim-snapshots.service /etc/systemd/system/
sudo cp deploy/systemd/footsim-snapshots.timer   /etc/systemd/system/
sudo systemctl daemon-reload

# 3. Einmal von Hand starten und zusehen
sudo systemctl start footsim-snapshots.service
sudo journalctl -u footsim-snapshots.service -n 60 --no-pager

# 4. Erst wenn Schritt 3 sauber war: Timer aktivieren
sudo systemctl enable --now footsim-snapshots.timer
```

## Status und Logs

```bash
# Wann läuft er das nächste Mal?
systemctl list-timers footsim-snapshots.timer

# Wie lief der letzte Lauf?
systemctl status footsim-snapshots.service

# Ausgabe des letzten Laufs
journalctl -u footsim-snapshots.service -n 100 --no-pager

# Nur die Läufe von heute
journalctl -u footsim-snapshots.service --since today --no-pager

# Live mitlesen
journalctl -u footsim-snapshots.service -f
```

Maschinenlesbare Berichte liegen unabhängig vom Journal:

```bash
ls -lt /root/footsim/data/snapshots/_runs/ | head
python -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['status'], d['snapshots_stored'], d['scopes_failed'])" \
  /root/footsim/data/snapshots/_runs/$(ls -t /root/footsim/data/snapshots/_runs | head -1)
```

## Abschalten

```bash
sudo systemctl disable --now footsim-snapshots.timer
systemctl list-timers footsim-snapshots.timer   # sollte leer sein
```

Der Dienst bleibt installiert und lässt sich weiter von Hand starten.
Vollständig entfernen:

```bash
sudo systemctl disable --now footsim-snapshots.timer
sudo rm /etc/systemd/system/footsim-snapshots.{service,timer}
sudo systemctl daemon-reload
```

## Exit-Codes

| Code | Bedeutung | systemd |
| ---: | --- | --- |
| 0 | `complete` — alles bearbeitet, nichts fehlgeschlagen | Erfolg |
| 3 | `partial` — gesammelt, aber nicht alles | Erfolg (`SuccessExitStatus`) |
| 4 | `failed` — nichts Verwertbares | **Fehler** |
| 5 | `busy` — ein anderer Lauf hält die Sperre | **Fehler** |
| 2 | Aufrufsfehler | **Fehler** |

`partial` gilt bewusst als Erfolg: Ein Teillauf hat echte Snapshots
gesichert. Die Unvollständigkeit steht im Laufbericht, nicht im
Dienststatus.

## Erholung nach Teilausfall

Der Sammler ist **idempotent**. Ein zweiter Lauf am selben Tag schreibt
nichts doppelt — unveränderte Zustände erkennt er am Fingerabdruck.

```bash
cd /root/footsim

# Was fehlt?
venv/bin/python collect_snapshots.py --coverage

# Fehlgeschlagene Scopes des letzten Laufs ansehen
python -c "import json,sys; d=json.load(open(sys.argv[1])); [print(f['kind'], f['label'], f['errors']) for f in d['failures']]" \
  data/snapshots/_runs/$(ls -t data/snapshots/_runs | head -1)

# Gezielt nachholen
venv/bin/python collect_snapshots.py --leagues bl1,cl --kinds availability
venv/bin/python collect_snapshots.py --teams 157,165
```

Hängt eine Sperre nach einem harten Absturz:

```bash
cat data/snapshots/collector.lock     # welcher Prozess, seit wann?
ps -p "$(python -c "import json;print(json.load(open('data/snapshots/collector.lock'))['pid'])")"
```

Läuft der Prozess nicht mehr, **übernimmt der nächste Lauf die Sperre
automatisch**, sobald sie älter als drei Stunden ist. Vorher von Hand
löschen ist nur nötig, wenn es eilt — und nur, wenn `ps` bestätigt, dass
der Prozess wirklich weg ist.

## Kontingent

Ein vollständiger Tageslauf kostet rund **300 Anfragen** (24 Ligen für
Ausfälle, der Rest Kader) bei einem Tageskontingent von 7500. Der
Sammler hält von sich aus bei 500 verbleibenden Anfragen an
(`--quota-margin`), damit der Webbetrieb Luft behält.

## Lokale Entwicklung unter Windows

Kein Produktionsweg, nur zum Ausprobieren:

```powershell
.venv312\Scripts\python.exe collect_snapshots.py --daily --dry-run --limit 3
```

Ein Windows-Aufgabenplaner-Eintrag wäre möglich, ist aber nicht der
Produktionsstandard und wird hier nicht gepflegt.
