# FootSim – Transfer-Vergleich: Installations-Anleitung

Dieses Paket enthält das neue Feature **Liga-zu-Liga-Transfervergleich**.

## Enthaltene Dateien

NEU:
- `src/data/transfer_loader.py`        – lädt und filtert Sommertransfers
- `src/data/player_stats_loader.py`    – lädt/normalisiert Zielliga-Statistiken
- `src/features/transfer_comparison.py` – reine Vergleichslogik (300-Min-Schwelle)
- `tests/test_transfer_comparison.py`  – 29 Tests

GEÄNDERT (vollständige Dateien, einfach ersetzen):
- `app.py`               – neue Route `/api/transfer-compare` + Imports
- `templates/index.html` – dritter Untermodus "Transfer-Vergleich"
- `static/script.js`     – neues tc-Modul + erweiterter Untermodus-Handler
- `static/style.css`     – neue Sektion 13b (transfer-compare-Präfix)
- `static/sw.js`         – Cache-Version v2 → v3 (wichtig für PWA-Nutzer!)

## Lokal einspielen (Windows PowerShell)

Alle Befehle stehen unten im Chat – ZIP nach Downloads legen und kopieren.

## Danach

1. Lokal testen: `python -m pytest tests\ -q` → alle 103 Tests grün
2. Flask lokal starten und den neuen Tab prüfen
3. Per Git auf den VPS deployen, Gunicorn neu starten

## Wichtig zum API-Limit

Der ERSTE Lauf einer neuen Ligakombination kostet ca. 50–60 API-Sports-
Requests (Teams + Transfers + Spielerstatistiken). Danach liegt alles
dauerhaft in `data/cache/` und wiederholte Aufrufe kosten 0 Requests.
Empfehlung: am ersten Tag nur 1 Kombination testen (Limit: 100/Tag).
