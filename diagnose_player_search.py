"""
Diagnose-Skript fuer die Spielersuche (Phase 3).

Aufruf auf dem VPS:
    cd /root/footsim
    venv/bin/python diagnose_player_search.py

Testet den kompletten Pfad:
    1. API-Key vorhanden?
    2. Verbindung zu API-Sports?
    3. /players?search= Endpoint erreichbar?
    4. player_compare_loader.search_players() funktioniert?
"""

import os
import sys
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()


def check(label, ok, detail=""):
    status = "✓" if ok else "✗"
    print(f"  {status}  {label}")
    if detail:
        print(f"     → {detail}")
    return ok


print("=" * 60)
print("  Diagnose: Spielersuche (Phase 3)")
print("=" * 60)
print()

# 1. API-Key
key = os.environ.get("APISPORTS_KEY", "")
if not check("APISPORTS_KEY in .env", bool(key), key[:8] + "..." if key else "FEHLT"):
    print("\nOhne API-Key kann nichts funktionieren. Bitte .env pruefen.")
    sys.exit(1)

# 2. Verbindung
from src.api.apisports_api import BASE_URL, _headers

print()
print(f"  BASE_URL: {BASE_URL}")

try:
    r = requests.get(f"{BASE_URL}/status", headers=_headers(), timeout=10)
    check("Verbindung zu API-Sports", r.status_code in (200, 401, 403),
          f"HTTP {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        sub = data.get("response", {}).get("subscription", {})
        check("Subscription aktiv", sub.get("active", False), str(sub))
        requests_info = data.get("response", {}).get("requests", {})
        check("Requests-Budget", True,
              f"{requests_info.get('current', '?')} / {requests_info.get('limit_day', '?')} heute")
except Exception as e:
    check("Verbindung zu API-Sports", False, str(e))
    sys.exit(1)

# 3. /players?search=
print()
try:
    r2 = requests.get(
        f"{BASE_URL}/players",
        headers=_headers(),
        params={"search": "messi", "season": 2025},
        timeout=20,
    )
    check("/players?search=messi&season=2025", r2.status_code == 200,
          f"HTTP {r2.status_code}")
    if r2.status_code == 200:
        data2 = r2.json()
        results = data2.get("results", 0)
        errors = data2.get("errors", {})
        check("Ergebnisse im Response", results > 0, f"{results} Treffer")
        if errors:
            check("Keine API-Fehler", False, str(errors))
        else:
            check("Keine API-Fehler", True)
        if data2.get("response"):
            first = data2["response"][0].get("player", {})
            print(f"\n  Erster Treffer: {first.get('name')} (ID {first.get('id')})")
    else:
        print(f"  Body: {r2.text[:300]}")
except Exception as e:
    check("/players?search= Endpoint", False, str(e))
    sys.exit(1)

# 4. search_players()
print()
try:
    from src.data.player_compare_loader import search_players
    results = search_players("messi", 2025)
    check("search_players('messi', 2025)", True, f"{len(results)} aufbereitete Treffer")
    if results:
        first = results[0]
        print(f"\n  Aufbereiteter Treffer:")
        print(f"    Name:      {first.get('name')}")
        print(f"    Team:      {first.get('team_name')}")
        print(f"    Liga:      {first.get('league_label')}")
        print(f"    Position:  {first.get('position_label')}")
        print(f"    Vergl.:    {first.get('comparable')}")
except Exception as e:
    check("search_players()", False, str(e))

# 5. /api/player-seasons vom Flask-Backend
print()
try:
    import app as flask_app
    client = flask_app.app.test_client()
    r3 = client.get("/api/player-seasons")
    data3 = r3.get_json()
    check("/api/player-seasons Route", r3.status_code == 200,
          f"{len(data3.get('seasons', []))} Saisons, current={data3.get('current_season')}")
except Exception as e:
    check("/api/player-seasons", False, str(e))

print()
print("=" * 60)
print("  Fertig")
print("=" * 60)
