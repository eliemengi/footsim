# Wöchentliche Aktualisierung der Spielerdaten

**Status: vorbereitet, NICHT aktiviert.** Die beiden Unit-Dateien liegen
im Repository, sind aber weder auf den VPS kopiert noch aktiviert.

## Warum es das braucht

Der Spielervergleich beruht auf zwei Dateiarten:

- `data/player_pool/` — Spielerprofile je Liga und Saison (gitignored,
  muss pro Host erzeugt werden)
- `data/percentiles/percentiles_<saison>.json` — die Vergleichsverteilung

Beide veralten im Saisonverlauf. Ohne Aktualisierung bliebe der Stand
vom Importtag stehen, und zu Saisonbeginn bliebe er sogar dauerhaft
leer: Ein Pool, der im August mit null Spielern abgeschlossen wurde,
galt bisher als „vollständig" und wurde nie wieder angefasst.

## Was der Job tut

```
/root/footsim/venv/bin/python refresh_players.py --update-current
```

- löst die Saison **dynamisch** aus dem Datum auf
  (`apisports_api.resolve_season`) — kein Jahr in Cron oder Unit-Datei,
  das jeden Sommer nachgezogen werden müsste
- lädt fehlende Seiten nach, statt alles neu zu holen (Disk-Cache bleibt)
- überspringt eine Liga **nicht** nur deshalb, weil ihr Pool als
  „vollständig" markiert ist
- erneuert danach den Perzentil-Snapshot
- schreibt atomar (erst `.tmp`, dann umbenennen)
- ersetzt einen brauchbaren Snapshot **nie** durch einen leeren
- bricht bei Rate Limit mit Exit-Code 1 ab, ohne Daten zu beschädigen —
  der nächste Lauf setzt fort

Kein automatischer `git pull`. Kein Service-Neustart: Es werden nur
Datendateien atomar ersetzt, ein laufender Gunicorn-Worker sieht deshalb
nie einen halben Stand.

## Kosten

Fünf Ligen, paginiert. Ein vollständiger Erstimport liegt je nach
Kadergrößen bei etwa 25–40 Requests; eine wöchentliche Aktualisierung
darunter, weil bereits geladene Seiten aus dem Cache kommen. Der Plan
erlaubt 7.500 Requests pro Tag.

## Installation auf dem VPS — noch NICHT ausgeführt

```bash
# 1. Unit-Dateien kopieren
sudo cp /root/footsim/ops/footsim-players-refresh.service /etc/systemd/system/
sudo cp /root/footsim/ops/footsim-players-refresh.timer   /etc/systemd/system/

# 2. Syntax prüfen, bevor irgendetwas aktiviert wird
sudo systemd-analyze verify /etc/systemd/system/footsim-players-refresh.service
sudo systemctl daemon-reload

# 3. EINMAL manuell laufen lassen und zusehen
sudo systemctl start footsim-players-refresh.service
sudo journalctl -u footsim-players-refresh -f

# 4. Erst wenn dieser Lauf sauber war: Timer aktivieren
sudo systemctl enable --now footsim-players-refresh.timer

# 5. Kontrolle
systemctl list-timers footsim-players-refresh
```

## Zeitplan

`Mon *-*-* 04:15:00` mit `RandomizedDelaySec=45min` und
`Persistent=true`.

- **Montag früh:** die Wochenendspieltage sind ausgewertet, und um diese
  Zeit nutzt praktisch niemand die App.
- **RandomizedDelaySec:** der Job startet nicht sekundengenau. Das
  entzerrt den Zugriff auf den Anbieter und vermeidet, dass eine Störung
  immer exakt denselben Zeitpunkt trifft.
- **Persistent:** war der Server zur geplanten Zeit aus, wird der Lauf
  nachgeholt. Ohne das fiele eine ganze Woche aus.

## Secrets

Die Unit-Datei enthält **keine**. Der Prozess liest die vorhandene,
ignorierte `.env` aus dem `WorkingDirectory` — genau wie die Anwendung.
Kein `Environment=`, kein `EnvironmentFile=` mit Schlüsselwerten.

## Keine parallelen Importe

Zwei Sicherungen:

1. `refresh_players.py` hält ein eigenes Lock
   (`data/.players_refresh.lock`) und bricht ab, wenn bereits ein Import
   läuft.
2. `ExecCondition=` in der Unit prüft dieselbe Datei, bevor der Prozess
   überhaupt startet.

## Kontrolle im Betrieb

```bash
journalctl -u footsim-players-refresh --since "1 week ago"
/root/footsim/venv/bin/python refresh_players.py --report
```

Der Report unterscheidet ausdrücklich zwischen „Paginierung
abgeschlossen" und „Pool inhaltlich brauchbar". Er nennt außerdem, aus
welcher Saison der tatsächlich verwendete Referenzpool stammt.

## Rückbau

```bash
sudo systemctl disable --now footsim-players-refresh.timer
sudo rm /etc/systemd/system/footsim-players-refresh.{service,timer}
sudo systemctl daemon-reload
```

Es entstehen keine Datenrückstände: Der Job schreibt ausschließlich in
`data/`, und die dortigen Dateien bleiben gültig.

---

# Spielbezogene Aktualisierung (`--post-match`)

**Status: implementiert und lokal getestet, NICHT auf dem VPS
eingerichtet.** Dieser Abschnitt beschreibt den Entwurf; er installiert
nichts.

## Warum zusätzlich zum wöchentlichen Lauf

Der wöchentliche Lauf hält den Pool vollständig. Er beantwortet aber
nicht die Frage, die am 24.08.2026 aufkam: *Warum stehen für Real
Madrid seit gestern 38 Minuten da?*

Bis dahin gab es genau zwei Möglichkeiten, und beide waren schlecht:

| Weg | Kosten | Problem |
|---|---:|---|
| bis zu 24 Stunden warten | 0 | der falsche Stand bleibt sichtbar |
| `--force --refetch-players` | ~450 | für zwei Spieler absurd |

`--post-match` ist der dritte Weg: **erst fragen, wer gespielt hat,
dann nur diese Spieler holen.**

## Kostenrechnung

`/fixtures?date=YYYY-MM-DD` liefert **alle** Spiele eines Tages
weltweit — ein einziger Abruf, nicht einer je Liga. Gefiltert wird
lokal auf die fünf Vergleichsligen.

| Fall | Requests |
|---|---:|
| Tag ohne Spiele | **1** |
| Spieltag, 10 Partien, 20 Mannschaften | ~500 |
| Wochenmittel | **~150** |
| täglicher Vollrefresh (zum Vergleich) | ~2.250 |
| Tageslimit des Tarifs | 7.500 |

## Was ausdrücklich NICHT nachgeladen wird

- **laufende Spiele** (`1H`, `2H`, `HT`, `ET`, `P`) — jeder Abruf wäre
  sofort wieder veraltet
- **abgebrochene Spiele** (`ABD`, `SUSP`) — sie erzeugen keinen
  verlässlichen Endstand
- **verschobene und abgesagte** (`PST`, `CANC`) — sie haben nicht
  stattgefunden

Die Statuszuordnung kommt aus `src/api/live_api.STATUS_MAP`. Es gibt
bewusst keine zweite Liste.

## Befehle

```bash
# Ansehen, ohne etwas zu schreiben
python refresh_players.py --season 2026 --post-match --dry-run

# Ausführen
python refresh_players.py --season 2026 --post-match

# Ein bestimmter Tag
python refresh_players.py --season 2026 --post-match --date 2026-08-22
```

Der Lauf ist **idempotent**: Zweimal hintereinander ausgeführt passiert
beim zweiten Mal nichts Zusätzliches, weil die frisch geholten Profile
dann innerhalb ihrer Lebensdauer liegen. Genau das braucht ein Timer.

## Entwurf für einen späteren Timer

**Nicht installieren, solange der wöchentliche Lauf nicht stabil
läuft.** Zwei Unit-Dateien, analog zu den vorhandenen:

`/etc/systemd/system/footsim-post-match.service`

```ini
[Unit]
Description=FootSim: Spielerdaten nach beendeten Spielen aktualisieren
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=footsim
WorkingDirectory=/root/footsim
EnvironmentFile=/root/footsim/.env
ExecStart=/root/footsim/venv/bin/python refresh_players.py --post-match
# Ein Lauf darf nie zwei Stunden blockieren.
TimeoutStartSec=3600
Nice=10
```

`/etc/systemd/system/footsim-post-match.timer`

```ini
[Unit]
Description=FootSim: spielbezogene Aktualisierung

[Timer]
# Nach den üblichen Anstoßzeiten, nicht während der Spiele.
OnCalendar=*-*-* 00:30:00
OnCalendar=*-*-* 06:30:00
Persistent=true
RandomizedDelaySec=900

[Install]
WantedBy=timers.target
```

Zweimal täglich reicht: Ein Spiel, das um 22:45 endet, ist um 00:30
verbucht; alles Frühere ohnehin. `Persistent=true` holt einen
verpassten Lauf nach einem Neustart nach.

## Was der Timer nicht leisten kann

Er sorgt dafür, dass FootSim einen **frischen** Providerstand hat. Er
sorgt **nicht** dafür, dass dieser Stand richtig ist.

Bei Real Madrid war die Partie seit 27 Stunden beendet, und der
Anbieter lieferte weiterhin 38 Minuten für elf Spieler. Kein Zeitplan
behebt das. Dagegen hilft nur, den Stand ehrlich als möglicherweise
vorläufig zu kennzeichnen — das tut `src/data/player_data_quality.py`.

FootSim korrigiert **niemals** eigenmächtig auf 90 Minuten.
