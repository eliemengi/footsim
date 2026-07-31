"""
Diagnose-Skript: Loggt jeden ausgehenden Request bei einem Kaltstart-Ligavergleich.
Zeigt: Zeitstempel, URL, HTTP-Status, Antwortzeit, Reihenfolge, Cache-Status.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import src.api.league_api as la
import requests as req_module

original_get = req_module.Session.get
call_log = []
start_time = time.time()

def logging_get(self, url, **kwargs):
    t0 = time.time()
    response = original_get(self, url, **kwargs)
    elapsed = time.time() - t0
    ts = time.time() - start_time

    entry = {
        "n": len(call_log) + 1,
        "ts": round(ts, 3),
        "url": url,
        "params": kwargs.get("params", {}),
        "status": response.status_code,
        "elapsed": round(elapsed, 3),
    }
    call_log.append(entry)

    status_str = f"HTTP {response.status_code}"
    if response.status_code == 429:
        status_str = f"\033[91mHTTP 429 RATE LIMIT\033[0m"
    elif response.status_code == 200:
        status_str = f"\033[92mHTTP 200\033[0m"

    print(f"  #{entry['n']:02d} | +{entry['ts']:6.3f}s | {status_str} | {entry['elapsed']:.3f}s | {url}")
    if kwargs.get("params"):
        print(f"         params: {kwargs['params']}")
    return response

req_module.Session.get = logging_get

# Cache-Dateien fuer bl1 und pl loeschen damit wirklich Kaltstart simuliert wird
import glob, json, os as os2
cache_dir = "data/cache"
deleted = []
for pattern in ["*BL1*", "*PL*", "*bl1*", "*pl*"]:
    for f in glob.glob(os2.path.join(cache_dir, pattern)):
        os2.remove(f)
        deleted.append(os2.path.basename(f))
if deleted:
    print(f"Cache-Dateien geloescht (Kaltstart-Simulation): {deleted}")
else:
    print("Keine Cache-Dateien fuer BL1/PL gefunden (bereits leer)")
print()

print("=" * 70)
print("KALTSTART: Ligavergleich bl1 vs pl")
print("=" * 70)
start_time = time.time()

from src.api.league_api import get_standings, get_finished_season_matches, ApiUnavailable

for code, api_code in [("bl1", "BL1"), ("pl", "PL")]:
    print(f"\n--- {code.upper()} ---")
    try:
        t0 = time.time()
        standings = get_standings(api_code)
        print(f"  get_standings({api_code}) OK in {time.time()-t0:.3f}s")
    except ApiUnavailable as e:
        print(f"  get_standings({api_code}) FEHLER: {e}")

    try:
        t0 = time.time()
        matches = get_finished_season_matches(api_code)
        print(f"  get_finished_season_matches({api_code}) OK in {time.time()-t0:.3f}s")
    except ApiUnavailable as e:
        print(f"  get_finished_season_matches({api_code}) FEHLER: {e}")

print()
print("=" * 70)
print("ZUSAMMENFASSUNG")
print("=" * 70)
print(f"{'#':<4} {'Zeit':>8} {'Status':<8} {'Dauer':>7}  URL")
print("-" * 70)
for e in call_log:
    flag = " <-- 429!" if e["status"] == 429 else ""
    path = e["url"].replace("https://api.football-data.org/v4", "")
    print(f"#{e['n']:<3} +{e['ts']:>6.3f}s  {e['status']:<8} {e['elapsed']:>5.3f}s  {path}{flag}")

print()
parallel = []
for i in range(len(call_log)):
    for j in range(i+1, len(call_log)):
        gap = call_log[j]["ts"] - call_log[i]["ts"]
        if gap < 0.1:
            parallel.append((call_log[i]["n"], call_log[j]["n"], gap))

if parallel:
    print("Gleichzeitige Requests (<100ms Abstand):")
    for a, b, gap in parallel:
        print(f"  Request #{a} und #{b} (Abstand: {gap*1000:.0f}ms)")
else:
    print("Keine parallelen Requests (<100ms Abstand) gefunden.")

