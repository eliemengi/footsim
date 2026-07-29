from src.data.historical_loader import load_season
from src.features.team_profile import build_season_profiles

interesting = [66, 57, 64, 65, 67, 73]

for year in [2025, 2024, 2023]:
    payload = load_season('PL', year)
    if payload is None:
        print(f'=== PL {year} | NICHT VORHANDEN ===')
        continue
    data = build_season_profiles(payload)
    profiles = data['profiles']
    avg = data['league_avg']
    hg = round(avg['home_goals'], 2)
    ag = round(avg['away_goals'], 2)
    print(f'=== PL {year} | Liga-Schnitt Heim:{hg} Gast:{ag} ===')
    for tid in interesting:
        if tid in profiles:
            p = profiles[tid]
            ah = round(p['attack_home'], 2)
            aa = round(p['attack_away'], 2)
            dh = round(p['defence_home'], 2)
            da = round(p['defence_away'], 2)
            print(f'  {p["team_name"]:<28} att_h={ah}  att_a={aa}  def_h={dh}  def_a={da}')
    print()
