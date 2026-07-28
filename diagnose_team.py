"""
Vollstaendige Diagnose eines einzelnen Teams.

Beantwortet die Plausibilitaetsfragen aus dem Audit (Abschnitt 5):
Woher kommen die Werte eines Teams, wie stark wiegt welche Saison,
und was bedeutet das in erwarteten Toren gegen ein Durchschnittsteam?

Aufruf:
    py diagnose_team.py pd barcelona
    py diagnose_team.py pl arsenal
    py diagnose_team.py bl1 bayern

Der Namensvergleich ist ein einfaches Teilstring-Matching auf den
Tabellennamen der laufenden Saison.
"""

import sys

from app import LEAGUE_CONFIG
from src.api.league_api import get_standings, get_full_season_matches
from src.predict.fixture_plan import partition_season_matches
from src.data.historical_loader import LEAGUE_CODES, load_available_seasons
from src.features.team_profile import (
    build_season_profiles, season_weights, expected_goals, neutral_profile,
)
from src.features.strength_provider import get_league_strengths, normalize_name
from src.features.dynamic_weights import current_season_weight, DEFAULT_K


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    league_key = sys.argv[1].lower()
    fragment = normalize_name(" ".join(sys.argv[2:]))

    if league_key not in LEAGUE_CONFIG:
        print(f"Unbekannte Liga: {league_key} (bekannt: {', '.join(LEAGUE_CONFIG)})")
        sys.exit(1)

    config = LEAGUE_CONFIG[league_key]
    standings_data = get_standings(config["api_code"])
    table = standings_data.get("tables", {}).get("TOTAL", [])

    # Prioritaet: exakter Match > Wortanfang > Teilstring
    # Verhindert "RCD Espanyol de Barcelona" als Treffer fuer "barcelona"
    def _match_quality(r):
        n = normalize_name(r.get("team_name") or "")
        fn = normalize_name(r.get("team_full_name") or "")
        if n == fragment or fn == fragment:
            return 0                            # exakt
        words_n = n.split(); words_fn = fn.split()
        if fragment in words_n or fragment in words_fn:
            return 1                            # ganzes Wort
        if any(w.startswith(fragment) for w in words_n + words_fn):
            return 2                            # Wortanfang
        if fragment in n or fragment in fn:
            return 3                            # Teilstring
        return 99

    candidates = [(r, _match_quality(r)) for r in table]
    candidates = [(r, q) for r, q in candidates if q < 99]
    row = min(candidates, key=lambda x: x[1])[0] if candidates else None
    if row is None:
        print(f"Kein Team in der Tabelle passt zu '{' '.join(sys.argv[2:])}'.")
        print("Verfuegbar: " + ", ".join(r.get("team_name", "?") for r in table))
        sys.exit(1)

    team_id = row.get("team_id")
    team_name = row.get("team_name")

    print(f"\n=== Diagnose: {team_name} ({config['name']}) ===")
    print(f"  Team-ID (football-data): {team_id}")
    print(f"  Spiele laufende Saison:  {row.get('played', 0)}")

    # --- Rohwerte pro historischer Saison ---
    loaded = load_available_seasons(LEAGUE_CODES.get(league_key, config["api_code"]))
    print(f"\n  Geladene historische Saisons: {[s for s, _ in loaded] or 'KEINE'}")

    weights = season_weights(len(loaded)) if loaded else []
    for (season, payload), weight in zip(loaded, weights):
        profiles = build_season_profiles(payload)
        profile = profiles["profiles"].get(team_id)
        avg = profiles["league_avg"]
        print(f"\n  Saison {season}  (Gewicht {weight:.1%}, Ligaschnitt "
              f"H {avg['home_goals']:.2f} / A {avg['away_goals']:.2f}):")
        if profile is None:
            # Team fehlt in dieser Saison (z. B. abgestiegen).
            # Namenssuche nur als expliziter Hinweis auf ID-Wechsel,
            # NICHT als stiller Ersatz durch ein anderes Team.
            # Dieselbe Prioritaetslogik wie beim Tabellen-Lookup:
            # exakter Match > ganzes Wort > Wortanfang > Teilstring.
            # Verhindert dass "barcelona" auf "FC Barcelona" trifft,
            # wenn wir Espanyol (ID 80) untersuchen.
            def _hist_quality(p):
                n = normalize_name(p.get("team_name") or "")
                if n == fragment: return 0
                words = n.split()
                if fragment in words: return 1
                if any(w.startswith(fragment) for w in words): return 2
                if fragment in n: return 3
                return 99

            candidates = [(p, _hist_quality(p)) for p in profiles["profiles"].values()]
            best = min(candidates, key=lambda x: x[1], default=(None, 99))
            named, quality = best

            if quality == 99:
                named = None

            if named is not None:
                # Nur anzeigen wenn der Name wirklich zum gesuchten Fragment
                # passt — kein stiller Datenaustausch zwischen Teams.
                hint = (f"    (ID-Wechsel? Aehnlicher Name in dieser Saison: "
                        f"{named.get('team_name')}, ID {named.get('team_id')} - "
                        f"wird hier NICHT verwendet, da ID nicht uebereinstimmt)")
                print(hint)
            print("    -> in dieser Saison NICHT vorhanden (ID fehlt)")
            continue
        stats = profile.get("stats", {})
        print(f"    Spiele: {stats.get('matches', profile.get('matches_played', '?'))} "
              f"| Tore H/A: {stats.get('home_goals_for', '?')}/{stats.get('away_goals_for', '?')} "
              f"| Gegentore H/A: {stats.get('home_goals_against', '?')}/{stats.get('away_goals_against', '?')}")
        print(f"    attack_home  {profile['attack_home']:.3f}   "
              f"attack_away  {profile['attack_away']:.3f}")
        print(f"    defence_home {profile['defence_home']:.3f}   "
              f"defence_away {profile['defence_away']:.3f}"
              "   (kleiner = bessere Abwehr)")

    # --- Finales Profil ueber den Provider (inkl. aktueller Saison) ---
    raw = get_full_season_matches(config["api_code"])
    plan = partition_season_matches(raw)
    strengths = get_league_strengths(league_key, table, current_matches=plan["finished"])
    final = strengths["profiles"].get(team_id)
    cov = next((c for c in strengths["coverage"] if c["team_id"] == team_id), {})

    played = row.get("played", 0) or 0
    print(f"\n  Zuordnung:      matched_by={cov.get('matched_by')}  "
          f"fallback_level={cov.get('fallback_level')}  "
          f"data_source={cov.get('data_source')}")
    print(f"  Aufsteiger:     {cov.get('is_promoted')}   "
          f"Historie: {cov.get('has_history')}")
    print(f"  Gewichtung:     Historie {1 - current_season_weight(played):.1%} / "
          f"laufende Saison {current_season_weight(played):.1%} "
          f"(n={played}, k={DEFAULT_K})")

    if final:
        print(f"\n  FINALE WERTE:")
        print(f"    attack_home  {final['attack_home']:.3f}   "
              f"attack_away  {final['attack_away']:.3f}")
        print(f"    defence_home {final['defence_home']:.3f}   "
              f"defence_away {final['defence_away']:.3f}")
        if final.get("squad_modifier") is not None:
            print(f"    Squad-/Verletzungsmodifier: {final.get('squad_modifier')}")

        avg = strengths.get("league_avg", {"home_goals": 1.5, "away_goals": 1.2})
        neutral = neutral_profile()
        xh_home, xa_home = expected_goals(final, neutral, avg)
        xh_away, xa_away = expected_goals(neutral, final, avg)
        print(f"\n  Erwartete Tore gegen ein Durchschnittsteam:")
        print(f"    zuhause:  {xh_home:.2f} : {xa_home:.2f}")
        print(f"    auswaerts: {xa_away:.2f} : {xh_away:.2f}"
              f"   (Ligaschnitt: {avg['home_goals']:.2f} : {avg['away_goals']:.2f})")


if __name__ == "__main__":
    main()
