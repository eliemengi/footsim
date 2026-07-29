"""Aufsteigerstatus strikt getrennt von Datenverfuegbarkeit (Audit §4)."""
from src.features.strength_provider import get_league_strengths
from tests.conftest import standings_from


def _cov(result, team_id):
    return next(c for c in result["coverage"] if c["team_id"] == team_id)


def test_aufsteiger_erkennung_nutzt_nur_die_vorsaison(test_league):
    ids_2024 = [1, 2, 3, 4, 5, 6]
    ids_2025 = [1, 2, 3, 4, 5, 7]           # 6 stieg ab, 7 stieg auf
    names = {i: f"Klub {i}" for i in range(1, 9)}
    names[6] = "Traditionsverein"
    test_league["write"]("TESTL", 2024, ids_2024, names)
    test_league["write"]("TESTL", 2025, ids_2025, names)

    # aktuelle Saison: 6 kehrt zurueck ("Koeln-Fall"), 8 ist komplett neu
    current = [1, 2, 3, 4, 6, 8]
    table = standings_from(current, names={i: names[i] for i in current})
    result = get_league_strengths("testl", table, use_squad_data=False)

    etabliert = _cov(result, 1)
    assert etabliert["is_promoted"] is False
    assert etabliert["has_history"] is True
    assert etabliert["fallback_level"] == 0

    rueckkehrer = _cov(result, 6)            # nicht in Vorsaison 2025 -> Aufsteiger
    assert rueckkehrer["is_promoted"] is True
    assert rueckkehrer["has_history"] is True  # hat aber eigene 2024er-Daten!
    assert rueckkehrer["fallback_level"] == 0

    neuling = _cov(result, 8)
    assert neuling["is_promoted"] is True
    assert neuling["has_history"] is False
    assert neuling["fallback_level"] == 3
    assert neuling["data_source"].startswith("promoted")


def test_fehlende_historie_macht_kein_team_zum_aufsteiger(test_league):
    ids = [1, 2, 3, 4, 5, 6]
    names = {i: f"Klub {i}" for i in ids}
    test_league["write"]("TESTL", 2024, ids, names)
    test_league["write"]("TESTL", 2025, ids, names)

    # Klub 2 kommt mit FALSCHER ID aus der Tabelle (Mapping-Problem),
    # aber der Name existiert in der Vorsaison -> kein Aufsteiger.
    table = standings_from([1, 999, 3, 4, 5, 6],
                           names={1: "Klub 1", 999: "Klub 2", 3: "Klub 3",
                                  4: "Klub 4", 5: "Klub 5", 6: "Klub 6"})
    result = get_league_strengths("testl", table, use_squad_data=False)

    kaputt = _cov(result, 999)
    assert kaputt["is_promoted"] is False       # Name in Vorsaison gefunden
    assert kaputt["fallback_level"] == 1        # Historie ueber Namen aufgeloest
    assert kaputt["matched_by"] == "name"


def test_aufsteigerzahl_entspricht_der_realitaet_nicht_der_datenlage(test_league):
    ids_2024 = [1, 2, 3, 4, 5, 6]
    ids_2025 = [1, 2, 3, 4, 5, 6]
    names = {i: f"Klub {i}" for i in range(1, 9)}
    test_league["write"]("TESTL", 2024, ids_2024, names)
    test_league["write"]("TESTL", 2025, ids_2025, names)

    current = [1, 2, 3, 4, 7, 8]                 # genau zwei echte Aufsteiger
    table = standings_from(current, names={i: names[i] for i in current})
    result = get_league_strengths("testl", table, use_squad_data=False)

    assert result["summary"]["teams_promoted"] == 2
    assert result["summary"]["previous_season"] == 2025


def test_ohne_vorsaisondaten_ist_der_status_ehrlich_unbekannt(test_league):
    # keine Dateien geschrieben -> keine Referenzsaison
    table = standings_from([1, 2, 3, 4])
    result = get_league_strengths("testl", table, use_squad_data=False)
    for cov in result["coverage"]:
        assert cov["is_promoted"] is None
        assert cov["data_source"] in ("no_history_data", "current_season_only")
