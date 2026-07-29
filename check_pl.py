from src.data.historical_loader import load_season

pl_2024 = load_season('PL', 2024)
pl_2023 = load_season('PL', 2023)

print('=== PL 2024 Teams ===')
for tid, t in sorted(pl_2024['teams'].items(), key=lambda x: x[1]['name']):
    print(f"  ID={tid:<6} {t['name']}")

print()
print('=== PL 2023 Teams ===')
for tid, t in sorted(pl_2023['teams'].items(), key=lambda x: x[1]['name']):
    print(f"  ID={tid:<6} {t['name']}")

ids_2024 = set(pl_2024['teams'].keys())
ids_2023 = set(pl_2023['teams'].keys())

print()
print('=== Nur in 2024 (nicht in 2023) ===')
for tid in ids_2024 - ids_2023:
    print(f"  ID={tid} {pl_2024['teams'][tid]['name']}")

print()
print('=== Nur in 2023 (nicht in 2024) ===')
for tid in ids_2023 - ids_2024:
    print(f"  ID={tid} {pl_2023['teams'][tid]['name']}")
