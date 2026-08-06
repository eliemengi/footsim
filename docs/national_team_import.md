# Nationalmannschafts-Import und die vier Wettbewerbsmodi

Dieses Dokument beschreibt, wie FootSim die vier Datenmodi (Scopes) fuer Radar,
Scatter und Perzentile mit echten, voneinander getrennten Daten fuellt.

## Die vier Modi

| Scope | Bedeutung | enthaelt |
|-------|-----------|----------|
| `league` | Nur Liga | ausschliesslich die heimische nationale Liga |
| `club_all` | Alle Vereinswettbewerbe | Liga + nationale Pokale + CL/EL/ECL + Supercups + FIFA Club World Cup |
| `national` | Nur Nationalmannschaft | ausschliesslich A-Nationalmannschaftswettbewerbe |
| `all` | Alle Wettbewerbe | `club_all` + `national` |

Absolute Werte werden summiert; Per-90-Werte und Quoten werden anschliessend
aus den aggregierten Rohwerten und Minuten neu berechnet (nie addiert oder
ungewichtet gemittelt). Diese Aggregation liegt in
`player_compare_loader.aggregate_statistics`.

## Woher die Daten kommen

Vereinsdaten (`league`, `club_all`) stammen aus `/players?id=&season=` und
liegen nach dem normalen `refresh_players.py --all` im Pool.

Nationalmannschaftsdaten sind der Zusatz. Grosse Turniere liegen bei
API-Football unter **eigenen** API-Seasons und eigenen League-IDs (z. B. EM
2024 = Liga 4 / Season 2024, WM 2026 = Liga 1 / Season 2026). Ein Abruf mit der
Vereinssaison allein erfasst sie nicht. Deshalb gibt es einen eigenen Schritt.

### Modell A: Fussballsaison, nicht Kalenderjahr

Ein Turnier gehoert zu der FootSim-Saison, in deren Fussballsaison-Zeitraum es
faellt - unabhaengig von der API-Season. Beispiele:

- EM 2024 (api 2024) -> FootSim 2023 (Saison 2023/24)
- Copa America 2024 (api 2024) -> FootSim 2023
- WM 2026 (api 2026) -> FootSim 2025 (Saison 2025/26)

Die Zuordnung steht zentral in
`src/data/national_competitions.py` (`FOOTSIM_SEASON_OF_TOURNAMENT`). Neue
Turniere werden dort mit einem Eintrag ergaenzt - keine Jahres-Hardcodierung an
anderer Stelle.

### Nur verifizierte Wettbewerbe

Welche Turniere ueberhaupt Spielerstatistiken liefern, wurde per
`discover_national.py` gegen die echte API geprueft. Nur Wettbewerbe mit
`statistics_players = true` und nur echte A-Nationalmannschaften stehen im
Register `NATIONAL_COMPETITIONS`. Ausgeschlossen sind:

- Vereinswettbewerbe (auch "CONCACAF Champions League", "FIFA Club World Cup"),
- Jugend- und Frauenwettbewerbe (U17..U23, Women).

## Ablauf des Imports

1. `refresh_players.py --all` - Vereinsdaten in den Pool (wie bisher).
2. `refresh_players.py --national` - reichert die **bereits vorhandenen**
   Pool-Spieler um Laenderspieldaten an:
   - sammelt die Spieler-IDs des Pools,
   - laedt die verifizierten Turniere der FootSim-Saison wettbewerbsbasiert
     (`/players?league=&season=`), beschraenkt auf genau diese IDs,
   - legt die Bloecke unter `data/national/national_<season>.json` ab,
   - baut jeden Pool-Eintrag mit angereicherter Rohantwort neu (`national`/`all`
     tragen jetzt echte Werte),
   - berechnet den Perzentil-Snapshot neu.

Es kommt **kein** neuer Spieler in den Pool. Der Pool bleibt der
Top-5-Ligen-Pool; nur die vorhandenen Spieler bekommen ihre NM-Werte.

## Konsistenz Radar / Scatter / Perzentile

Alle drei lesen dieselbe Basis. Zur Laufzeit fuegt
`get_player_season_raw_enriched` die gespeicherten NM-Bloecke an die
Vereins-Rohantwort an, bevor irgendein Scope aggregiert wird. Der Radar nutzt
diese Funktion (ueber `get_player_season_profile`), der Pool-Import ebenfalls.
Dadurch koennen die drei nicht auseinanderlaufen.

## Requests und Kosten

- Vereins-Import: ~1 Request je Pool-Spieler (einmalig, dann Disk-Cache).
- NM-Import: ~ (Seiten je Turnier) Requests. Ein Turnierkader ist klein,
  meist wenige Seiten; die Zielwettbewerbe einer FootSim-Saison summieren sich
  auf typischerweise einige Dutzend Requests. Alles gecacht - ein zweiter Lauf
  kostet nichts.
- Kein Import beim App-Start. Alles laeuft nur ueber `refresh_players.py`.

## Dateien

- `src/data/national_competitions.py` - Register + Modell-A-Zuordnung
- `src/data/national_import.py` - wettbewerbsbasierter Import + Laufzeitzugriff
- `player_compare_loader.get_player_season_raw_enriched` - Anreicherung
- `refresh_players.py --national` - Orchestrierung
- `data/national/national_<season>.json` - persistente NM-Bloecke (gitignored)
