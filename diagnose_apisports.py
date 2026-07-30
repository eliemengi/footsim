"""
Diagnose: zeigt die ROHE API-Sports-Antwort, ohne Interpretation
durch unseren Wrapper.

Beweist oder widerlegt, ob tatsaechlich ein Rate-Limit vorliegt.
Verbraucht maximal 2 Requests (Status + ein Testendpoint).

Aufruf:
    python diagnose_apisports.py
"""

import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()

KEY = os.getenv("APISPORTS_KEY")
BASE_URL = "https://v3.football.api-sports.io"


def key_info():
    if not KEY:
        return "FEHLT"
    return f"vorhanden, Laenge {len(KEY)}, endet auf ...{KEY[-4:]}"


def raw_call(endpoint, params, label):
    """Ein Request, komplette Antwort ungefiltert ausgeben."""
    print("=" * 70)
    print(f"TEST: {label}")
    print(f"Endpoint : {BASE_URL}/{endpoint}")
    print(f"Parameter: {params}")
    print("-" * 70)

    headers = {
        "x-rapidapi-host": "v3.football.api-sports.io",
        "x-rapidapi-key": KEY,
    }

    try:
        response = requests.get(
            f"{BASE_URL}/{endpoint}",
            headers=headers,
            params=params,
            timeout=20,
        )
    except requests.RequestException as error:
        print(f"NETZWERKFEHLER: {error}")
        return None

    print(f"HTTP-Status: {response.status_code}")

    # Rate-Limit-Header von API-Sports, falls vorhanden
    for header in ("x-ratelimit-requests-limit",
                   "x-ratelimit-requests-remaining",
                   "X-RateLimit-Limit",
                   "X-RateLimit-Remaining",
                   "Retry-After"):
        if header in response.headers:
            print(f"Header {header}: {response.headers[header]}")

    try:
        data = response.json()
    except ValueError:
        print("Body ist kein JSON. Erste 500 Zeichen:")
        print(response.text[:500])
        return None

    print(f"errors  : {json.dumps(data.get('errors'), ensure_ascii=False)}")
    print(f"results : {data.get('results')}")
    print(f"paging  : {json.dumps(data.get('paging'), ensure_ascii=False)}")

    resp = data.get("response")
    if isinstance(resp, list):
        print(f"response: Liste mit {len(resp)} Eintraegen")
    elif isinstance(resp, dict):
        print("response: Objekt ->")
        print(json.dumps(resp, indent=2, ensure_ascii=False)[:1200])
    else:
        print(f"response: {resp!r}")

    print()
    return data


def main():
    print()
    print("#" * 70)
    print("API-SPORTS DIAGNOSE")
    print(f"APISPORTS_KEY: {key_info()}")
    print("#" * 70)
    print()

    # TEST 1: Status. Enthaelt die offiziellen Nutzungszaehler.
    # Das ist der entscheidende Beleg fuer oder gegen ein Rate-Limit.
    status = raw_call("status", {}, "Account-Status und Nutzungszaehler")

    if status and isinstance(status.get("response"), dict):
        requests_info = status["response"].get("requests") or {}
        subscription = status["response"].get("subscription") or {}
        print("=" * 70)
        print("AUSWERTUNG DER ZAEHLER")
        print("-" * 70)
        print(f"Plan          : {subscription.get('plan')}")
        print(f"Aktiv         : {subscription.get('active')}")
        print(f"Heute genutzt : {requests_info.get('current')}")
        print(f"Tageslimit    : {requests_info.get('limit_day')}")

        current = requests_info.get("current")
        limit = requests_info.get("limit_day")
        if isinstance(current, int) and isinstance(limit, int):
            print("-" * 70)
            if current >= limit:
                print("ERGEBNIS: Tageslimit IST erreicht. Rate-Limit belegt.")
            else:
                print(f"ERGEBNIS: Tageslimit NICHT erreicht "
                      f"({limit - current} Requests frei).")
                print("Ein 429 waere in diesem Fall NICHT die Ursache.")
        print()

    # TEST 2: Der Endpoint, den das Feature tatsaechlich zuerst aufruft.
    # Zeigt, was bei einem echten Feature-Request passiert.
    raw_call("teams", {"league": 39, "season": 2024},
             "Premier-League-Teams 2024 (erster Request des Features)")

    print("=" * 70)
    print("Fertig. Maximal 2 Requests verbraucht.")
    print("=" * 70)


if __name__ == "__main__":
    main()
