"""
Eine vollstaendig synthetische Big-Games-Welt fuer die V2-Tests.

WARUM ES DIESE WELT BRAUCHT
---------------------------
Die Bestenliste haengt an drei Dingen: den privaten UEFA-/FIFA-Snapshots,
einem vollstaendigen Datensatz und der Uebereinstimmung ihrer
Fingerabdruecke. Die Snapshots sind bewusst nicht versioniert
(.gitignore: "bleibt bewusst server-seitig und ungeteilt") und liegen auf
einem frischen Checkout deshalb NICHT vor.

Tests, die den echten Datensatz benutzten, liefen damit lokal gruen und
auf der CI in "snapshot_missing" - nicht weil die Anwendung falsch lag,
sondern weil sie voellig richtig fail-closed reagierte. Ein Test darf
diese Eigenschaft weder umgehen noch von privaten Dateien abhaengen.

Diese Welt baut stattdessen alles selbst: eigene Snapshots, eigenen
Datensatz, eigenes oeffentliches Artefakt - alles unterhalb von tmp_path.
Die CI prueft danach exakt denselben Rechenweg wie der
Entwicklerrechner, ohne eine einzige private Datei.

AUFBAU DER POPULATION (bewusst so gewaehlt)
-------------------------------------------
  * 30 "Stammspieler": 8 Partien gegen Band 5 (zaehlen unter JEDER
    Huerde) und 6 gegen Band 30 (fallen unter einer engen Huerde weg).
    Sie bleiben immer platzierbar, verlieren aber Big Games.
  * 10 "Randspieler": nur 2 Partien gegen Band 5, dafuer 10 gegen
    Band 30. Unter Top 30 platzierbar, unter Top 5 nicht mehr.

Damit sind beide Aussagen pruefbar, die die Gegnerhuerde tragen muss:
die Zahl der Zugelassenen SINKT, und dieselben Spieler behalten WENIGER
Big Games. Dazu kommen je zwei Nationalpartien, damit auch die
FIFA-Huerde etwas zu entscheiden hat.
"""

import json

import pytest

SAISON = 2025

#: Wappen von einem zugelassenen Host - safe_crest() verwirft alles andere.
WAPPEN = "https://media.api-sports.io/football/teams/33.png"

#: Band -> Gegnerstaerke. Groessenordnung echter Koeffizienten, aber
#: ausdruecklich kein echter Koeffizient.
_STAERKE = {5: 1.45, 10: 1.35, 15: 1.28, 20: 1.20, 25: 1.12, 30: 1.05}

STAMMSPIELER = 30
RANDSPIELER = 10
SPIELERZAHL = STAMMSPIELER + RANDSPIELER


def uefa_snapshot():
    """Top-40-Liste, deren Raenge genau die sechs Baender abdecken."""
    return {
        "season": "2025/26",
        "status": "complete",
        "clubs": [
            {"rank": rang,
             "total_coefficient": float(140 - rang * 2),
             "apisports_team_id": 9000 + rang}
            for rang in range(1, 41)
        ],
    }


def fifa_snapshot(jahr):
    """Top-20-Liste im Aufbau der echten FIFA-Snapshots."""
    return {
        "year": jahr,
        "snapshot_date": f"{jahr}-06-01",
        "ranking_type": "fifa_mens_world_ranking_top20",
        "status": "final",
        "source": "FIFA Men's World Ranking",
        "notes": None,
        "team_identity": {
            "id_scheme": "API-Football numeric team id",
            "id_source": "test fixture",
            "resolution_rule": "Exact numeric identity only",
            "unresolved_teams": [],
        },
        "teams": [
            {"rank": rang, "team_name": f"Land {rang}",
             "team_name_en": f"Land {rang}", "points": 2000.0 - rang,
             "apisports_team_id": 8000 + rang,
             "apisports_resolution_confidence": "high",
             "apisports_resolution_method": "exact test identity"}
            for rang in range(1, 21)
        ],
    }


def spiel(fixture_id, band, tag, quelle="club", minuten=90, note=7.0,
          tore=None, vorlagen=0, position="Midfielder"):
    """
    Eine Spielzeile in genau der Form, die der Datensatz speichert.

    Die Kodierung folgt dem echten Anbieter (an den gesammelten Daten
    geprueft): ein Spiel OHNE Tor traegt goals=None, ein Spiel ohne
    Vorlage dagegen ausdruecklich assists=0.
    """
    national = quelle == "national"
    if national:
        staerke = 1.08 if band and band <= 10 else 1.04 if band else 1.0
    else:
        staerke = _STAERKE.get(band, 1.0)
    # Gegner und Wettbewerb je Quelle - erst damit ist eine Partie
    # erzaehlbar (V4-Vertrag). Die Kennungen sind offensichtlich
    # synthetisch und stammen aus keiner echten Rangliste.
    gegner_id = (7000 + (band or 99)) if national else (9000 + (band or 99))
    return {
        "fixture_id": fixture_id,
        "date": f"2026-{1 + tag % 9:02d}-{10 + tag % 18:02d}T20:00:00+00:00",
        "source": quelle,
        "league_id": 1 if national else 140,
        "league_name": "World Cup" if national else "Premier League",
        "stage": "group" if national else "league",
        "opponent_band": band,
        "opponent_id": gegner_id,
        "opponent_name": f"Gegner {gegner_id}",
        "opponent_logo": WAPPEN,
        "is_home": fixture_id % 2 == 0,
        # Ergebnis aus eigener Sicht; bewusst wechselnd, damit ein Test
        # eine feste Richtung nicht zufaellig trifft.
        "goals_for": 2 if fixture_id % 3 else 1,
        "goals_against": 1 if fixture_id % 3 else 1,
        "own_team_id": 33,
        "own_team_name": "Eigenes Team",
        "own_team_logo": WAPPEN,
        "position": position,
        "minutes": minuten,
        "rating": note,
        "weight": staerke,
        "strength": staerke,
        "importance": 1.0,
        "goals": tore,
        "assists": vorlagen,
        "shots_total": 3,
        "shots_on": 2,
        "passes_key": 2,
        "passes_total": 40,
        "tackles": 1,
        "interceptions": 1,
        "duels_total": 10,
        "duels_won": 6,
        "dribbles_attempts": 2,
        "dribbles_success": 1,
        "saves": 3 if position == "Goalkeeper" else None,
        "goals_conceded": 1 if position == "Goalkeeper" else None,
    }


def spieler(index):
    """Eine Datensatzzeile. Siehe Aufbau der Population im Modulkopf."""
    from src.data import big_games_dataset as bgd

    position = ("Attacker", "Midfielder", "Defender", "Goalkeeper")[index % 4]
    # Die Note traegt die Rangfolge und bleibt in der Skala 0..10.
    note = round(6.4 + (index % 17) * 0.12, 2)
    stamm = index < STAMMSPIELER
    enge_partien = 8 if stamm else 2
    weite_partien = 6 if stamm else 10

    spiele = []
    nummer = index * 100
    for i in range(enge_partien):
        nummer += 1
        spiele.append(spiel(
            nummer, 5, i, note=note, position=position,
            tore=1 if i < (index % 4) else None,
            vorlagen=1 if i < (index % 3) else 0))
    for i in range(weite_partien):
        nummer += 1
        spiele.append(spiel(
            nummer, 30, i + 20, note=note, position=position,
            tore=1 if i == 0 else None))
    # Zwei Nationalpartien: sie haengen allein an der FIFA-Huerde.
    for i, band in enumerate((10, 20)):
        nummer += 1
        spiele.append(spiel(
            nummer, band, i + 40, quelle="national", note=note,
            position=position))

    return {
        "player_id": 500000 + index,
        "name": f"Spieler {index:02d}",
        "season": SAISON,
        "position": position,
        "pool_position": position,
        "league": "pl",
        "team_id": 33,
        "team_name": "Eigenes Team",
        "team_logo": WAPPEN,
        "fixture_ids": [s["fixture_id"] for s in spiele],
        "big_games": len(spiele),
        "minutes": sum(s["minutes"] for s in spiele),
        "raw_totals": {},
        "metrics": {},
        "rating": note,
        "big_game_score": None,
        "sufficient_sample": True,
        "missing": {},
        "matches": [bgd.compact_match(s) for s in spiele],
        "seasons": [{"season": SAISON, "available": True,
                     "provisional": False, "club_available": True,
                     "national_available": True,
                     "match_count": len(spiele)}],
    }


def baue(tmp_path, monkeypatch, mit_artefakt=True):
    """
    Richtet die Welt ein und gibt ein paar Eckdaten zurueck.

    mit_artefakt=False laesst das oeffentliche Artefakt bewusst weg -
    fuer Tests, die den privaten Weg allein pruefen wollen.
    """
    from src.data import big_games_dataset as bgd
    from src.data import big_games_public as bgp
    from src.data import fifa_rankings
    from src.data import uefa_coefficients as uc

    coeff_dir = tmp_path / "coeff"
    coeff_dir.mkdir()
    (coeff_dir / "uefa_coefficients_2025_26.json").write_text(
        json.dumps(uefa_snapshot()), encoding="utf-8")
    monkeypatch.setattr(uc, "COEFFICIENT_DIR", str(coeff_dir))
    uc.clear_cache()

    fifa_dir = tmp_path / "fifa"
    fifa_dir.mkdir()
    for jahr in (SAISON, SAISON + 1):
        (fifa_dir / f"fifa_rankings_{jahr}.json").write_text(
            json.dumps(fifa_snapshot(jahr)), encoding="utf-8")
    monkeypatch.setattr(fifa_rankings, "FIFA_RANKING_DIR", str(fifa_dir))
    fifa_rankings.clear_cache()

    monkeypatch.setattr(bgd, "DATASET_DIR", str(tmp_path / "leaderboard"))
    monkeypatch.setattr(bgp, "PUBLIC_DIR", str(tmp_path / "public"))
    bgd.clear_document_memo()

    zeilen = [spieler(i) for i in range(SPIELERZAHL)]
    dokument = bgd.build_dataset(
        SAISON,
        zeilen,
        population={"source": "test_fixture", "leagues": ["pl"],
                    "players": len(zeilen), "duplicate_pool_entries": 0},
        collector_meta={"source": "tests/big_games_v2_welt.py"},
        # Die Nationalpartien liegen im Kalenderjahr 2026.
        fifa_years=[SAISON + 1],
    )
    bgd.write_dataset(dokument)
    if mit_artefakt:
        bgp.build_from_dataset(SAISON)

    return {"season": SAISON, "spieler": len(zeilen), "tmp": tmp_path}


@pytest.fixture
def big_games_welt(tmp_path, monkeypatch):
    """Die Welt als Fixture - inklusive sauberem Aufraeumen danach."""
    from src.data import big_games_dataset as bgd
    from src.data import fifa_rankings
    from src.data import uefa_coefficients as uc

    daten = baue(tmp_path, monkeypatch)
    yield daten

    bgd.clear_document_memo()
    uc.clear_cache()
    fifa_rankings.clear_cache()
