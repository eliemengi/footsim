from src.data.historical_loader import load_season
from src.features.team_profile import build_season_profiles

LIGEN = ['BL1', 'PL', 'PD', 'SA', 'FL1']

for api_code in LIGEN:
    print(f'{"="*70}')
    print(f'  {api_code}')
    print(f'{"="*70}')
    
    profiles_by_year = {}
    for year in [2025, 2024, 2023]:
        payload = load_season(api_code, year)
        if payload is None:
            print(f'  {year}: NICHT VORHANDEN')
            continue
        data = build_season_profiles(payload)
        profiles_by_year[year] = data['profiles']
    
    if 2025 not in profiles_by_year or 2024 not in profiles_by_year:
        print('  Vergleich nicht moeglich')
        continue
    
    p2025 = profiles_by_year[2025]
    p2024 = profiles_by_year[2024]
    
    print(f'  {"Team":<28} {"att_h 25":>8} {"att_h 24":>8} {"Diff":>8}  Bewertung')
    print(f'  {"-"*65}')
    
    changes = []
    for tid, p in p2025.items():
        if tid in p2024:
            diff = round(p["attack_home"] - p2024[tid]["attack_home"], 2)
            changes.append((diff, p["team_name"], p["attack_home"], p2024[tid]["attack_home"]))
    
    for diff, name, v25, v24 in sorted(changes, key=lambda x: x[0]):
        flag = ''
        if diff <= -0.15:
            flag = '  << STARK SCHLECHTER'
        elif diff >= 0.15:
            flag = '  >> STARK BESSER'
        print(f'  {name:<28} {v25:>8.2f} {v24:>8.2f} {diff:>+8.2f}{flag}')
    print()
