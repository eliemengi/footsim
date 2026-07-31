"""
Diagnose v2: patcht requests.get direkt (nicht Session.get).
Loggt jeden ausgehenden HTTP-Request an football-data.org.
"""
import sys, os, time, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import requests as req_module

original_requests_get = req_module.get
call_log = []
start_ref = [time.time()]

def logging_requests_get(url, **kwargs):
    t0 = time.time()
    response = original_requests_get(url, **kwargs)
    elapsed = time.time() - t0
    ts = time.time() - start_ref[0]

    entry = {"n": len(call_log)+1, "ts": round(ts,3), "url": url,
             "params": kwargs.get("params",{}), "status": response.status_code,
             "elapsed": round(elapsed,3)}
    call_log.append(entry)

    flag = " <-- 429 RATE LIMIT!" if response.status_code == 429 else ""
    path = url.replace("https://api.football-data.org/v4","")
    print(f"  #{entry['n']:02d} | +{entry['ts']:6.3f}s | HTTP {entry['status']} | {entry['elapsed']:.3f}s | {path}{flag}")
    return response

req_module.get = logging_requests_get

# Cache leeren fuer echten Kaltstart
cache_dir = "data/cache"
deleted = []
for pattern in ["*BL1*", "*PL*", "*bl1*", "*pl*"]:
    for f in glob.glob(os.path.join(cache_dir, pattern)):
        os.remove(f)
        deleted.append(os.path.basename(f))
print(f"Cache geloescht: {len(deleted)} Dateien")
print()

print("=" * 70)
print("KALTSTART: Ligavergleich BL1 vs PL")
print("=" * 70)
start_ref[0] = time.time()

from src.api.league_api import get_standings, get_finished_season_matches, ApiUnavailable

for code, api_code in [("bl1", "BL1"), ("pl", "PL")]:
    print(f"\n--- {api_code} ---")
    try:
        t0 = time.time()
        s = get_standings(api_code)
        print(f"  get_standings OK ({time.time()-t0:.3f}s)")
    except ApiUnavailable as e:
        print(f"  get_standings FEHLER: {e}")
    try:
        t0 = time.time()
        m = get_finished_season_matches(api_code)
        print(f"  get_finished_season_matches OK ({time.time()-t0:.3f}s)")
    except ApiUnavailable as e:
        print(f"  get_finished_season_matches FEHLER: {e}")

print()
print("=" * 70)
print("ZUSAMMENFASSUNG")
print("=" * 70)
if not call_log:
    print("KEINE HTTP-Requests aufgezeichnet (alles aus Cache geladen)")
    print("-> Das bedeutet: der Disk-Cache wurde NICHT vollstaendig geloescht")
    print("   oder die Daten kommen aus einem anderen Cache-Layer.")
else:
    print(f"{'#':<4} {'Zeit':>8} {'Status':<6} {'Dauer':>7}  Endpoint")
    print("-" * 70)
    for e in call_log:
        path = e["url"].replace("https://api.football-data.org/v4","")
        flag = " <-- 429!" if e["status"] == 429 else ""
        print(f"#{e['n']:<3} +{e['ts']:>6.3f}s  {e['status']:<6} {e['elapsed']:>5.3f}s  {path}{flag}")

    rate_limits = [e for e in call_log if e["status"] == 429]
    print()
    if rate_limits:
        print(f"429 aufgetreten bei Request #{rate_limits[0]['n']}: {rate_limits[0]['url']}")
    else:
        print("Kein 429 aufgetreten.")

    print()
    print("Zeitabstaende zwischen Requests:")
    for i in range(1, len(call_log)):
        gap = call_log[i]["ts"] - call_log[i-1]["ts"]
        print(f"  #{call_log[i-1]['n']} -> #{call_log[i]['n']}: {gap*1000:.0f}ms")
