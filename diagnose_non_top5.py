"""
Diagnose-Skript: findet die genaue Exception fuer nicht-Top5-Ligen.
Laedt eine Kombination mit ned1 durch den kompletten Pfad.
Ausgabe: genaue Funktion, Endpoint, Parameter, Fehlertext.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import requests as _requests
import traceback

# Patch _get um jeden Request sichtbar zu machen
from src.api import apisports_api as aa

original_get = aa._get

call_count = [0]

def verbose_get(endpoint, params=None):
    call_count[0] += 1
    print(f"\n--- API-Request #{call_count[0]} ---")
    print(f"Endpoint : {endpoint}")
    print(f"Parameter: {params}")

    try:
        result = original_get(endpoint, params=params)
        print(f"Ergebnis : {len(result)} Eintraege")
        return result
    except Exception as e:
        print(f"EXCEPTION: {type(e).__name__}: {e}")
        raise

aa._get = verbose_get

# Auch in transfer_loader patchen (importiert _get direkt)
from src.data import transfer_loader as tl
tl._get = verbose_get

from src.data.transfer_loader import load_summer_transfers

print("=" * 60)
print("TEST A: Funktionierende Kombination (pl als Quelliga)")
print("=" * 60)
try:
    result = load_summer_transfers("pl", "pd", 2024)
    print(f"\nERGEBNIS: {len(result)} Transfers gefunden")
except Exception as e:
    print(f"\nFEHLER: {type(e).__name__}: {e}")

print()
print("=" * 60)
print("TEST B: Nicht-Top5 Quelliga (ned1 = Eredivisie)")
print("=" * 60)
call_count[0] = 0
try:
    result = load_summer_transfers("ned1", "pd", 2024)
    print(f"\nERGEBNIS: {len(result)} Transfers gefunden")
except Exception as e:
    print(f"\nFEHLER: {type(e).__name__}: {e}")
    traceback.print_exc()

print()
print("=" * 60)
print("TEST C: Nicht-Top5 als Zielliga (ned1 = Eredivisie)")
print("=" * 60)
call_count[0] = 0
try:
    result = load_summer_transfers("bl1", "ned1", 2024)
    print(f"\nERGEBNIS: {len(result)} Transfers gefunden")
except Exception as e:
    print(f"\nFEHLER: {type(e).__name__}: {e}")
    traceback.print_exc()

print()
print("=" * 60)
print("TEST D: Championship als Zielliga (eng2)")
print("=" * 60)
call_count[0] = 0
try:
    result = load_summer_transfers("bl1", "eng2", 2024)
    print(f"\nERGEBNIS: {len(result)} Transfers gefunden")
except Exception as e:
    print(f"\nFEHLER: {type(e).__name__}: {e}")
    traceback.print_exc()
