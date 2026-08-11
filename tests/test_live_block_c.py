"""
Tests fuer Block LIVE C (Spielfeld, Spielerbewertungen, Ereignismarker).

Abgedeckt:
  A) Bewertung parsen (String, Ganzzahl, kaputt, ausserhalb der Skala)
  B) Bewertungsstufen und ihre Schwellenwerte
  C) Normalisierung der Einzelspielerwerte aus /fixtures/players
  D) Merge ueber die Player-ID in Startelf und Ersatzbank
  E) Rasterauswertung (parse_grid)
  F) Spielfeldreihen (build_pitch_rows) fuer beliebige Formationen
  G) Zusammenspiel im Payload und Provider-/Cache-Verhalten
  H) Oberflaeche: Spielfeld, Abzeichen, Marker, Rueckfall, Mobile

Kein echter API-Request: alle Tests arbeiten auf synthetischen Antworten
im Format von /fixtures/players und /fixtures/lineups. Die verwendeten
Strukturen und Wertebereiche sind an echten Antworten aus allen sieben
FootSim-Wettbewerben abgeglichen.
"""

import os

import pytest

from src.api import live_api
from src.api.live_api import (
    RATING_TIER_WEAK,
    RATING_TIER_BELOW_AVERAGE,
    RATING_TIER_AVERAGE,
    RATING_TIER_GOOD,
    RATING_TIER_EXCELLENT,
    build_match_center,
    build_pitch_rows,
    classify_rating,
    normalize_lineup,
    normalize_player_stats,
    parse_grid,
    parse_rating,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(PROJECT_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


HOME_ID = 49
AWAY_ID = 42


def make_player_entry(player_id, name="Spieler", photo="https://x/p.png",
                      rating="7.2", minutes=90, number=7, position="M",
                      goals=None, assists=None, yellow=0, red=0,
                      saves=None, captain=False, substitute=False,
                      statistics=True):
    """Ein Eintrag aus /fixtures/players, so wie der Provider ihn liefert."""
    entry = {
        "player": {"id": player_id, "name": name, "photo": photo},
    }

    if statistics:
        entry["statistics"] = [{
            "games": {
                "minutes": minutes, "number": number, "position": position,
                "rating": rating, "captain": captain, "substitute": substitute,
            },
            "goals": {"total": goals, "conceded": 0, "assists": assists, "saves": saves},
            "cards": {"yellow": yellow, "red": red},
        }]

    return entry


def make_players_response(team_id=HOME_ID, entries=None):
    return [{
        "team": {"id": team_id, "name": "Chelsea", "logo": "https://x/49.png"},
        "players": entries if entries is not None else [make_player_entry(11)],
    }]


def make_lineup_player(player_id, name="Spieler", number=7, pos="M", grid="2:1"):
    return {"player": {"id": player_id, "name": name, "number": number,
                       "pos": pos, "grid": grid}}


def make_raw_lineup(team_id=HOME_ID, formation="4-2-3-1",
                    start_xi=None, substitutes=None):
    return {
        "team": {"id": team_id, "name": "Chelsea", "logo": "https://x/49.png"},
        "formation": formation,
        "coach": {"id": 100, "name": "Trainer X", "photo": "https://x/c.png"},
        "startXI": start_xi if start_xi is not None else [
            make_lineup_player(11, "Keeper", 1, "G", "1:1"),
            make_lineup_player(12, "Verteidiger", 4, "D", "2:1"),
        ],
        "substitutes": substitutes if substitutes is not None else [
            make_lineup_player(21, "Bank A", 30, "M", None),
        ],
    }


def formation_lineup(rows):
    """
    Baut eine Startelf aus einer Reihenbeschreibung: rows = [1, 4, 2, 3, 1].

    Damit lassen sich beliebige Formationen aufbauen, ohne die
    Formationsangabe zu benutzen - genau wie die Engine selbst.
    """
    players = []
    player_id = 100

    for row_number, count in enumerate(rows, start=1):
        for column in range(1, count + 1):
            players.append(make_lineup_player(
                player_id, f"P{player_id}", player_id % 100, "M",
                f"{row_number}:{column}",
            ))
            player_id += 1

    return players


# ===========================================================================
# A) Bewertung parsen
# ===========================================================================

class TestRatingParsen:
    def test_kommazahl_als_string(self):
        assert parse_rating("7.2") == 7.2

    def test_ganzzahl_als_string(self):
        """Der Provider liefert "8" statt "8.0" - an echten Antworten geprueft."""
        assert parse_rating("8") == 8.0

    def test_zahl(self):
        assert parse_rating(6.5) == 6.5
        assert parse_rating(7) == 7.0

    def test_fehlende_bewertung(self):
        assert parse_rating(None) is None

    def test_kaputte_bewertung(self):
        for wert in ["", "  ", "keine", "7,2", "N/A", [], {}, object()]:
            assert parse_rating(wert) is None

    def test_bool_ist_keine_bewertung(self):
        """True wuerde sonst als 1.0 durchgehen."""
        assert parse_rating(True) is None
        assert parse_rating(False) is None

    def test_ausserhalb_der_skala_wird_verworfen(self):
        """Eine 47.0 waere ein Datenfehler und darf keine Spitzenleistung werden."""
        assert parse_rating("47") is None
        assert parse_rating("-1") is None
        assert parse_rating("10.5") is None

    def test_skalengrenzen_bleiben_gueltig(self):
        assert parse_rating("0") == 0.0
        assert parse_rating("10") == 10.0

    def test_wird_auf_eine_nachkommastelle_gerundet(self):
        assert parse_rating("7.26") == 7.3

    def test_nan_wird_verworfen(self):
        assert parse_rating(float("nan")) is None
        assert parse_rating("nan") is None


# ===========================================================================
# B) Bewertungsstufen
# ===========================================================================

class TestRatingStufen:
    def test_ohne_bewertung_keine_stufe(self):
        """Kein Standardwert - ohne Bewertung zeigt das Frontend nichts."""
        assert classify_rating(None) is None

    def test_stufen_an_den_schwellenwerten(self):
        assert classify_rating(5.9) == RATING_TIER_WEAK
        assert classify_rating(6.0) == RATING_TIER_BELOW_AVERAGE
        assert classify_rating(6.4) == RATING_TIER_BELOW_AVERAGE
        assert classify_rating(6.5) == RATING_TIER_AVERAGE
        assert classify_rating(7.1) == RATING_TIER_AVERAGE
        assert classify_rating(7.2) == RATING_TIER_GOOD
        assert classify_rating(7.9) == RATING_TIER_GOOD
        assert classify_rating(8.0) == RATING_TIER_EXCELLENT

    def test_raender_der_skala(self):
        assert classify_rating(0.0) == RATING_TIER_WEAK
        assert classify_rating(10.0) == RATING_TIER_EXCELLENT

    def test_median_der_echten_verteilung_ist_durchschnitt(self):
        """
        Der Median echter Bewertungen liegt bei 6.7 (218 Bewertungen aus je
        einem Spiel der sieben FootSim-Wettbewerbe). Er MUSS in der
        mittleren Stufe landen - eine Staffelung, die die Haelfte aller
        Spieler als unterdurchschnittlich ausweist, waere fachlich falsch.
        """
        assert classify_rating(6.7) == RATING_TIER_AVERAGE

    def test_schwellenwerte_stehen_nur_an_einer_stelle(self):
        """Keine verstreuten Zahlen: weder im Backend noch im Frontend."""
        source = _read("src", "api", "live_api.py")
        assert source.count("RATING_TIERS = [") == 1

        script = _read("static", "script.js")
        assert "rating_tier" in script
        # Das Frontend darf die Stufe nur benutzen, nie selbst berechnen.
        for schwelle in ["6.5", "7.2", "8.0", "6.0"]:
            assert f"rating >= {schwelle}" not in script
            assert f"rating > {schwelle}" not in script


# ===========================================================================
# C) Einzelspielerwerte normalisieren
# ===========================================================================

class TestPlayerStats:
    def test_grundfelder(self):
        stats = normalize_player_stats(make_players_response(entries=[
            make_player_entry(11, "Keeper", rating="7.5", minutes=90,
                              number=1, position="G", saves=4),
        ]))

        assert 11 in stats
        werte = stats[11]
        assert werte["minutes"] == 90
        assert werte["number"] == 1
        assert werte["position"] == "G"
        assert werte["rating"] == 7.5
        assert werte["rating_tier"] == RATING_TIER_GOOD
        assert werte["saves"] == 4
        assert werte["photo"] == "https://x/p.png"

    def test_tore_vorlagen_karten(self):
        stats = normalize_player_stats(make_players_response(entries=[
            make_player_entry(11, goals=2, assists=1, yellow=1, red=0),
        ]))

        assert stats[11]["goals"] == 2
        assert stats[11]["assists"] == 1
        assert stats[11]["yellow"] == 1
        assert stats[11]["red"] == 0

    def test_beide_teams_in_einer_antwort(self):
        """Ein Request liefert beide Mannschaften - kein Request je Team."""
        raw = make_players_response(HOME_ID, [make_player_entry(11)])
        raw += make_players_response(AWAY_ID, [make_player_entry(99)])

        stats = normalize_player_stats(raw)
        assert set(stats) == {11, 99}

    def test_bankspieler_ohne_einsatz(self):
        stats = normalize_player_stats(make_players_response(entries=[
            make_player_entry(11, rating=None, minutes=None, substitute=True),
        ]))

        assert stats[11]["rating"] is None
        assert stats[11]["rating_tier"] is None
        assert stats[11]["minutes"] is None
        assert stats[11]["started_on_bench"] is True

    def test_eingesetzter_spieler_ohne_bewertung(self):
        """Kommt real vor - Minuten ja, Bewertung nicht erhoben."""
        stats = normalize_player_stats(make_players_response(entries=[
            make_player_entry(11, rating=None, minutes=64),
        ]))

        assert stats[11]["minutes"] == 64
        assert stats[11]["rating"] is None
        assert stats[11]["rating_tier"] is None

    def test_kapitaen(self):
        stats = normalize_player_stats(make_players_response(entries=[
            make_player_entry(11, captain=True),
        ]))
        assert stats[11]["captain"] is True

    def test_fehlender_statistikblock(self):
        stats = normalize_player_stats(make_players_response(entries=[
            make_player_entry(11, statistics=False),
        ]))

        assert stats[11]["rating"] is None
        assert stats[11]["minutes"] is None
        assert stats[11]["photo"] == "https://x/p.png"

    def test_eintrag_ohne_id_wird_verworfen(self):
        """Ohne stabile ID bliebe nur der Name - und der ist unzuverlaessig."""
        stats = normalize_player_stats(make_players_response(entries=[
            make_player_entry(None, "Namenlos"),
            make_player_entry(11),
        ]))

        assert set(stats) == {11}

    def test_leere_und_kaputte_antwort(self):
        assert normalize_player_stats([]) == {}
        assert normalize_player_stats(None) == {}
        assert normalize_player_stats([None, "kaputt", {}, {"players": None}]) == {}

    def test_kaputte_spielereintraege_werden_uebersprungen(self):
        raw = make_players_response(entries=[None, "kaputt", {}, make_player_entry(11)])
        assert set(normalize_player_stats(raw)) == {11}

    def test_null_wird_nicht_zu_null_zahl(self):
        """Wie bei den Teamstatistiken: null heisst 'nicht erhoben'."""
        stats = normalize_player_stats(make_players_response(entries=[
            make_player_entry(11, goals=None, assists=None),
        ]))

        assert stats[11]["goals"] is None
        assert stats[11]["assists"] is None


# ===========================================================================
# D) Merge in die Aufstellung
# ===========================================================================

class TestMerge:
    def test_startelf_bekommt_matchwerte(self):
        stats = normalize_player_stats(make_players_response(entries=[
            make_player_entry(11, rating="8.2", minutes=90, goals=1),
        ]))

        lineup = normalize_lineup(make_raw_lineup(), stats)
        keeper = lineup["start_xi"][0]

        assert keeper["id"] == 11
        assert keeper["rating"] == 8.2
        assert keeper["rating_tier"] == RATING_TIER_EXCELLENT
        assert keeper["minutes"] == 90
        assert keeper["goals"] == 1
        assert keeper["photo"] == "https://x/p.png"

    def test_ersatzbank_bekommt_matchwerte(self):
        stats = normalize_player_stats(make_players_response(entries=[
            make_player_entry(21, rating="6.9", minutes=25),
        ]))

        lineup = normalize_lineup(make_raw_lineup(), stats)
        bank = lineup["substitutes"][0]

        assert bank["id"] == 21
        assert bank["rating"] == 6.9
        assert bank["minutes"] == 25

    def test_zuordnung_nur_ueber_die_id(self):
        """
        Gleicher Name, andere ID: es darf NICHTS zugeordnet werden.
        Namensheuristik ist ausdruecklich ausgeschlossen.
        """
        stats = normalize_player_stats(make_players_response(entries=[
            make_player_entry(999, "Keeper", rating="9.0"),
        ]))

        lineup = normalize_lineup(make_raw_lineup(), stats)
        assert lineup["start_xi"][0]["rating"] is None

    def test_ohne_player_stats_bleiben_felder_leer(self):
        lineup = normalize_lineup(make_raw_lineup())
        keeper = lineup["start_xi"][0]

        assert keeper["rating"] is None
        assert keeper["rating_tier"] is None
        assert keeper["photo"] is None
        assert keeper["minutes"] is None

    def test_player_id_bleibt_erhalten(self):
        """Ohne die ID koennte Block D keine Spielerprofile anhaengen."""
        stats = normalize_player_stats(make_players_response())
        lineup = normalize_lineup(make_raw_lineup(), stats)

        assert all(p["id"] is not None for p in lineup["start_xi"])
        assert all(p["id"] is not None for p in lineup["substitutes"])

    def test_fehlende_rueckennummer_kommt_aus_den_matchwerten(self):
        stats = normalize_player_stats(make_players_response(entries=[
            make_player_entry(11, number=17),
        ]))

        raw = make_raw_lineup(start_xi=[
            make_lineup_player(11, "Keeper", None, "G", "1:1"),
        ])

        assert normalize_lineup(raw, stats)["start_xi"][0]["number"] == 17

    def test_vorhandene_rueckennummer_wird_nicht_ueberschrieben(self):
        stats = normalize_player_stats(make_players_response(entries=[
            make_player_entry(11, number=99),
        ]))

        lineup = normalize_lineup(make_raw_lineup(), stats)
        assert lineup["start_xi"][0]["number"] == 1


# ===========================================================================
# E) Raster
# ===========================================================================

class TestGrid:
    def test_gueltiges_raster(self):
        assert parse_grid("2:3") == {"row": 2, "col": 3}
        assert parse_grid("1:1") == {"row": 1, "col": 1}

    def test_leerzeichen_stoeren_nicht(self):
        assert parse_grid(" 3:2 ") == {"row": 3, "col": 2}

    def test_fehlendes_raster(self):
        assert parse_grid(None) is None
        assert parse_grid("") is None

    def test_kaputtes_raster(self):
        for wert in ["2", "2:3:4", "a:b", "2:", ":3", "2;3", "2.5:1", 23, [], {}]:
            assert parse_grid(wert) is None

    def test_unplausible_werte(self):
        assert parse_grid("0:1") is None
        assert parse_grid("1:0") is None
        assert parse_grid("-1:2") is None


# ===========================================================================
# F) Spielfeldreihen
# ===========================================================================

class TestPitchRows:
    def _rows(self, formation_rows):
        lineup = normalize_lineup(make_raw_lineup(
            start_xi=formation_lineup(formation_rows)))
        return lineup["pitch_rows"]

    def test_442(self):
        assert [len(r) for r in self._rows([1, 4, 4, 2])] == [1, 4, 4, 2]

    def test_4231(self):
        assert [len(r) for r in self._rows([1, 4, 2, 3, 1])] == [1, 4, 2, 3, 1]

    def test_433(self):
        assert [len(r) for r in self._rows([1, 4, 3, 3])] == [1, 4, 3, 3]

    def test_352(self):
        assert [len(r) for r in self._rows([1, 3, 5, 2])] == [1, 3, 5, 2]

    def test_3421(self):
        assert [len(r) for r in self._rows([1, 3, 4, 2, 1])] == [1, 3, 4, 2, 1]

    def test_541(self):
        assert [len(r) for r in self._rows([1, 5, 4, 1])] == [1, 5, 4, 1]

    def test_unsymmetrische_formation(self):
        """Auch eine ungewoehnliche Aufteilung muss ohne Sonderfall gehen."""
        assert [len(r) for r in self._rows([1, 4, 1, 2, 2, 1])] == [1, 4, 1, 2, 2, 1]

    def test_reihen_von_der_eigenen_torlinie_nach_vorne(self):
        start_xi = [
            make_lineup_player(3, "Stuermer", 9, "F", "3:1"),
            make_lineup_player(1, "Keeper", 1, "G", "1:1"),
            make_lineup_player(2, "Verteidiger", 4, "D", "2:1"),
        ]

        lineup = normalize_lineup(make_raw_lineup(start_xi=start_xi))
        namen = [lineup["start_xi"][i]["name"] for row in lineup["pitch_rows"] for i in row]

        assert namen == ["Keeper", "Verteidiger", "Stuermer"]

    def test_spalten_innerhalb_einer_reihe_sortiert(self):
        start_xi = [
            make_lineup_player(3, "Dritter", 3, "D", "2:3"),
            make_lineup_player(1, "Erster", 1, "D", "2:1"),
            make_lineup_player(2, "Zweiter", 2, "D", "2:2"),
        ]

        lineup = normalize_lineup(make_raw_lineup(start_xi=start_xi))
        namen = [lineup["start_xi"][i]["name"] for i in lineup["pitch_rows"][0]]

        assert namen == ["Erster", "Zweiter", "Dritter"]

    def test_reihen_enthalten_indizes_nicht_kopien(self):
        """
        Indizes statt kopierter Spielerobjekte - sonst staende die
        Startelf zweimal im Payload und im Plattencache.
        """
        lineup = normalize_lineup(make_raw_lineup(start_xi=formation_lineup([1, 4])))

        for row in lineup["pitch_rows"]:
            for entry in row:
                assert isinstance(entry, int)

        alle = sorted(i for row in lineup["pitch_rows"] for i in row)
        assert alle == list(range(len(lineup["start_xi"])))

    def test_jeder_spieler_kommt_genau_einmal_vor(self):
        lineup = normalize_lineup(make_raw_lineup(start_xi=formation_lineup([1, 4, 2, 3, 1])))
        alle = [i for row in lineup["pitch_rows"] for i in row]

        assert len(alle) == 11
        assert len(set(alle)) == 11

    def test_ein_fehlendes_raster_kippt_das_ganze_team(self):
        """
        Sonst stuende ein Teil der Mannschaft auf dem Feld und der Rest
        nirgends. Dann lieber die Liste fuer alle.
        """
        start_xi = formation_lineup([1, 4])
        start_xi[2]["player"]["grid"] = None

        lineup = normalize_lineup(make_raw_lineup(start_xi=start_xi))
        assert lineup["pitch_rows"] is None
        assert lineup["has_pitch"] is False

    def test_kaputtes_raster_kippt_das_ganze_team(self):
        start_xi = formation_lineup([1, 4])
        start_xi[1]["player"]["grid"] = "kaputt"

        lineup = normalize_lineup(make_raw_lineup(start_xi=start_xi))
        assert lineup["has_pitch"] is False

    def test_doppelt_belegter_platz_wird_abgelehnt(self):
        start_xi = formation_lineup([1, 2])
        start_xi[2]["player"]["grid"] = start_xi[1]["player"]["grid"]

        lineup = normalize_lineup(make_raw_lineup(start_xi=start_xi))
        assert lineup["has_pitch"] is False

    def test_kein_spieler_geht_beim_rueckfall_verloren(self):
        start_xi = formation_lineup([1, 4, 2, 3, 1])
        start_xi[5]["player"]["grid"] = None

        lineup = normalize_lineup(make_raw_lineup(start_xi=start_xi))
        assert lineup["has_pitch"] is False
        assert len(lineup["start_xi"]) == 11

    def test_leere_startelf(self):
        lineup = normalize_lineup(make_raw_lineup(start_xi=[]))
        assert lineup["pitch_rows"] is None
        assert lineup["has_pitch"] is False

    def test_build_pitch_rows_direkt(self):
        assert build_pitch_rows([]) is None
        assert build_pitch_rows(None) is None

    def test_ersatzbank_braucht_kein_raster(self):
        """Ersatzspieler haben keines und duerfen das Feld nicht verhindern."""
        lineup = normalize_lineup(make_raw_lineup(
            start_xi=formation_lineup([1, 4, 2, 3, 1]),
            substitutes=[make_lineup_player(900, "Bank", 30, "M", None)],
        ))

        assert lineup["has_pitch"] is True
        assert len(lineup["substitutes"]) == 1

    def test_formationsangabe_wird_nicht_ausgewertet(self):
        """
        Dieselbe Startelf mit falscher, fehlender und absurder
        Formationsangabe muss identische Reihen ergeben - die Engine
        darf ausschliesslich das Raster benutzen.
        """
        start_xi = formation_lineup([1, 4, 2, 3, 1])
        referenz = None

        for formation in ["4-2-3-1", "3-5-2", None, "", "Unfug"]:
            lineup = normalize_lineup(make_raw_lineup(
                formation=formation, start_xi=start_xi))
            reihen = [len(r) for r in lineup["pitch_rows"]]

            if referenz is None:
                referenz = reihen
            assert reihen == referenz == [1, 4, 2, 3, 1]

    def test_keine_formationsspezifische_verzweigung(self):
        """Kein if formation == "4-3-3" - weder im Backend noch im Frontend."""
        for pfad in [("src", "api", "live_api.py"), ("static", "script.js")]:
            source = _read(*pfad)
            for formation in ["4-3-3", "4-2-3-1", "3-5-2", "4-4-2", "5-4-1", "3-4-2-1"]:
                assert f'"{formation}"' not in source
                assert f"'{formation}'" not in source


# ===========================================================================
# G) Payload und Provider
# ===========================================================================

def make_raw_fixture(status="FT", elapsed=90, fixture_id=555):
    return {
        "fixture": {
            "id": fixture_id,
            "date": "2026-08-11T20:30:00+02:00",
            "referee": "C. Kavanagh",
            "venue": {"id": 1, "name": "Stamford Bridge", "city": "London"},
            "status": {"long": "Match Finished", "short": status,
                       "elapsed": elapsed, "extra": None},
        },
        "league": {"id": 39, "name": "Premier League", "country": "England",
                   "logo": "https://x/l39.png", "round": "Regular Season - 38"},
        "teams": {
            "home": {"id": HOME_ID, "name": "Chelsea", "logo": "https://x/49.png"},
            "away": {"id": AWAY_ID, "name": "Arsenal", "logo": "https://x/42.png"},
        },
        "goals": {"home": 2, "away": 1},
    }


class TestPayload:
    def test_bewertungen_landen_im_payload(self):
        payload = build_match_center(
            make_raw_fixture(), [], [make_raw_lineup()], [],
            make_players_response(entries=[make_player_entry(11, rating="7.6")]),
        )

        assert payload["home_lineup"]["start_xi"][0]["rating"] == 7.6
        assert payload["home_lineup"]["start_xi"][0]["rating_tier"] == RATING_TIER_GOOD

    def test_spielfeld_landet_im_payload(self):
        payload = build_match_center(
            make_raw_fixture(), [],
            [make_raw_lineup(start_xi=formation_lineup([1, 4, 4, 2]))], [], [],
        )

        assert payload["home_lineup"]["has_pitch"] is True
        assert [len(r) for r in payload["home_lineup"]["pitch_rows"]] == [1, 4, 4, 2]

    def test_ohne_player_stats_bleibt_alles_gueltig(self):
        """Vier-Argumente-Aufruf muss weiter funktionieren."""
        payload = build_match_center(make_raw_fixture(), [], [make_raw_lineup()], [])

        assert payload is not None
        assert payload["home_lineup"]["start_xi"][0]["rating"] is None

    def test_angesetztes_spiel_ohne_alles(self):
        payload = build_match_center(make_raw_fixture(status="NS"), [], [], [], [])

        assert payload["home_lineup"] is None
        assert payload["events"] == []

    def test_beide_teams_bekommen_ihre_werte(self):
        raw_players = make_players_response(HOME_ID, [make_player_entry(11, rating="7.0")])
        raw_players += make_players_response(AWAY_ID, [make_player_entry(77, rating="8.4")])

        payload = build_match_center(
            make_raw_fixture(), [],
            [make_raw_lineup(HOME_ID, start_xi=[make_lineup_player(11, grid="1:1")]),
             make_raw_lineup(AWAY_ID, start_xi=[make_lineup_player(77, grid="1:1")])],
            [], raw_players,
        )

        assert payload["home_lineup"]["start_xi"][0]["rating"] == 7.0
        assert payload["away_lineup"]["start_xi"][0]["rating"] == 8.4


class TestProvider:
    @pytest.fixture(autouse=True)
    def _isolierter_cache(self, tmp_path, monkeypatch):
        from src.utils import disk_cache
        monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path))

    def _patch(self, monkeypatch, calls):
        monkeypatch.setattr(live_api.apisports_api, "get_fixture_by_id",
                            lambda f, timezone=None: calls.append("fixture") or [make_raw_fixture()])
        monkeypatch.setattr(live_api.apisports_api, "get_fixture_events",
                            lambda f: calls.append("events") or [])
        monkeypatch.setattr(live_api.apisports_api, "get_fixture_lineups",
                            lambda f: calls.append("lineups") or [make_raw_lineup()])
        monkeypatch.setattr(live_api.apisports_api, "get_fixture_statistics",
                            lambda f: calls.append("statistics") or [])
        monkeypatch.setattr(live_api.apisports_api, "get_fixture_players",
                            lambda f: calls.append("players") or make_players_response())

    def test_cache_miss_kostet_fuenf_requests(self, monkeypatch):
        calls = []
        self._patch(monkeypatch, calls)

        live_api.get_match_center(555)
        assert calls == ["fixture", "events", "lineups", "statistics", "players"]

    def test_zweiter_aufruf_kostet_keine_requests(self, monkeypatch):
        calls = []
        self._patch(monkeypatch, calls)

        live_api.get_match_center(555)
        live_api.get_match_center(555)
        live_api.get_match_center(555)

        assert len(calls) == 5

    def test_unbekanntes_spiel_spart_die_vier_folgerequests(self, monkeypatch):
        calls = []
        self._patch(monkeypatch, calls)
        monkeypatch.setattr(live_api.apisports_api, "get_fixture_by_id",
                            lambda f, timezone=None: [])

        assert live_api.get_match_center(999) is None
        assert calls == []

    def test_ausfall_beim_player_request_liefert_alten_stand(self, monkeypatch):
        calls = []
        self._patch(monkeypatch, calls)

        first = live_api.get_match_center(555)
        assert first["stale"] is False

        from src.utils import disk_cache
        key = "live_match:555"
        entry = disk_cache.read_entry(key)
        entry["meta"]["expires_at"] = "2000-01-01T00:00:00+00:00"
        disk_cache._write_atomic(disk_cache._path_for(key), entry)

        def boom(fixture_id):
            raise live_api.ApisportsUnavailable("Quelle weg")

        monkeypatch.setattr(live_api.apisports_api, "get_fixture_players", boom)

        second = live_api.get_match_center(555)
        assert second["stale"] is True

    def test_ohne_cache_wird_der_fehler_durchgereicht(self, monkeypatch):
        calls = []
        self._patch(monkeypatch, calls)

        def boom(fixture_id):
            raise live_api.ApisportsUnavailable("Quelle weg")

        monkeypatch.setattr(live_api.apisports_api, "get_fixture_players", boom)

        with pytest.raises(live_api.ApisportsUnavailable):
            live_api.get_match_center(555)

    def test_route_liefert_bewertungen_aus(self, monkeypatch):
        import app as app_module
        app_module.app.config["TESTING"] = True
        client = app_module.app.test_client()

        calls = []
        self._patch(monkeypatch, calls)
        monkeypatch.setattr(
            live_api.apisports_api, "get_fixture_players",
            lambda f: make_players_response(entries=[make_player_entry(11, rating="8.1")]),
        )

        body = client.get("/api/live-match?fixture=555").get_json()
        assert body["home_lineup"]["start_xi"][0]["rating"] == 8.1
        assert body["home_lineup"]["start_xi"][0]["rating_tier"] == RATING_TIER_EXCELLENT

    def test_provider_funktion_existiert(self):
        from src.api import apisports_api
        assert hasattr(apisports_api, "get_fixture_players")

    def test_provider_funktion_hat_keinen_eigenen_cache(self):
        """Der Match-Center-Cache deckt alle fuenf Endpunkte gemeinsam ab."""
        source = _read("src", "api", "apisports_api.py")
        start = source.index("def get_fixture_players(")
        block = source[start:start + 900]

        assert "cached_call" not in block
        assert "disk_cached" not in block
        assert 'fixtures/players' in block


# ===========================================================================
# H) Oberflaeche
# ===========================================================================

def _mc_block(name, ende):
    script = _read("static", "script.js")
    start = script.index(name)
    return script[start:script.index(ende, start)]


class TestSpielfeldOberflaeche:
    def test_spielfeld_wird_gebaut(self):
        script = _read("static", "script.js")
        assert "function mcBuildPitch(lineup, eventIndex)" in script

        css = _read("static", "style.css")
        assert ".mc-pitch {" in css

    def test_spielfeld_nutzt_die_reihen_vom_server(self):
        block = _mc_block("function mcBuildPitch(lineup, eventIndex)",
                          "function mcBuildPlayerRow")

        assert "lineup.pitch_rows" in block
        assert "lineup.start_xi[index]" in block
        # Keine eigene Rasterauswertung im Frontend.
        assert "grid" not in block

    def test_rueckfall_auf_die_liste_ohne_raster(self):
        block = _mc_block("function mcBuildLineupBlock(lineup, teamName, eventIndex)",
                          "function mcRenderLineups")

        assert "lineup.has_pitch" in block
        assert "mcBuildPitch(lineup, eventIndex)" in block
        assert "mcBuildPlayerRow" in block

    def test_reihen_sind_flexcontainer_ohne_positionsrechnung(self):
        css = _read("static", "style.css")
        start = css.index(".mc-pitch-rows {")
        block = css[start:css.index(".mc-pp-figure", start)]

        assert "display: flex" in block
        assert "column-reverse" in block
        assert "space-around" in block

    def test_spieler_ueberlappen_nicht(self):
        """
        Gleich breite, schrumpfbare Zellen statt absoluter Position -
        dadurch koennen sich zwei Spieler nicht denselben Platz teilen.
        """
        css = _read("static", "style.css")
        start = css.index(".mc-pp {")
        block = css[start:css.index(".mc-pp-figure", start)]

        assert "flex: 1 1 0" in block
        assert "min-width: 0" in block
        assert "position: absolute" not in block

    def test_langer_name_wird_gekuerzt(self):
        script = _read("static", "script.js")
        assert "function mcShortName(name)" in script

        css = _read("static", "style.css")
        start = css.index(".mc-pp-name {")
        block = css[start:start + 500]

        assert "text-overflow: ellipsis" in block
        assert "overflow: hidden" in block

    def test_vollstaendiger_name_bleibt_im_titel(self):
        block = _mc_block("function mcBuildPitchPlayer(player, stats)",
                          "function mcBuildPitch(lineup")
        assert "name.title = player.name" in block

    def test_fehlendes_bild_faellt_auf_initialen_zurueck(self):
        block = _mc_block("function mcBuildAvatar(player)", "function mcBuildEventMarkers")

        assert "mcInitials(player.name)" in block
        assert "photo.onerror" in block

    def test_player_id_bleibt_im_dom(self):
        """Block D haengt sich spaeter genau hier an."""
        block = _mc_block("function mcBuildPitchPlayer(player, stats)",
                          "function mcBuildPitch(lineup")
        assert "node.dataset.playerId = player.id" in block

    def test_mobile_regeln_vorhanden(self):
        css = _read("static", "style.css")
        start = css.index("@media (max-width: 420px)")
        block = css[start:]

        assert ".mc-pp-figure" in block
        assert ".mc-rating" in block


class TestRatingBadgeOberflaeche:
    def test_kein_abzeichen_ohne_bewertung(self):
        block = _mc_block("function mcBuildRatingBadge(player, extraClass)",
                          "function mcInitials")

        assert "player.rating === null" in block
        assert "return null" in block

    def test_stufe_kommt_vom_server(self):
        block = _mc_block("function mcBuildRatingBadge(player, extraClass)",
                          "function mcInitials")

        assert "player.rating_tier" in block
        assert "mc-rating--" in block

    def test_alle_fuenf_stufen_haben_eine_farbe(self):
        css = _read("static", "style.css")
        for tier in ["weak", "below_average", "average", "good", "excellent"]:
            assert f".mc-rating--{tier}" in css

    def test_bewertung_immer_mit_nachkommastelle(self):
        """Die Quelle liefert auch "8" - angezeigt wird 8.0."""
        script = _read("static", "script.js")
        assert "function mcFormatRating(rating)" in script
        assert "toFixed(1)" in script

    def test_kein_erfundener_ersatzwert(self):
        script = _read("static", "script.js")
        for verboten in ["rating || 6", "rating || 0", "rating ?? 6", "rating ?? 0"]:
            assert verboten not in script


class TestEventMarkerOberflaeche:
    def test_zuordnung_ueber_die_player_id(self):
        block = _mc_block("function mcBuildPlayerEventIndex(events)",
                          "function mcFormatRating")

        assert "person.id" in block
        assert "index.set(person.id" in block
        # Keine Namensheuristik.
        assert "person.name" not in block

    def test_mehrfachereignisse_werden_gezaehlt(self):
        block = _mc_block("function mcBuildPlayerEventIndex(events)",
                          "function mcFormatRating")

        assert "own.goals += 1" in block
        assert "helper.assists += 1" in block

    def test_wechsel_zaehlt_nicht_doppelt(self):
        """
        Die Quelle fuehrt den ausgewechselten Spieler zusaetzlich unter
        "player". Wird der Zweig nicht vorher verlassen, zaehlt derselbe
        Wechsel zweimal.
        """
        block = _mc_block("function mcBuildPlayerEventIndex(events)",
                          "function mcFormatRating")

        sub_start = block.index('if (event.type === "substitution")')
        sub_block = block[sub_start:block.index("const own =")]

        assert "event.player_out" in sub_block
        assert "event.player_in" in sub_block
        assert "return;" in sub_block

    def test_eigentor_ist_unterscheidbar(self):
        block = _mc_block("function mcBuildEventMarkers(stats, options)",
                          "function mcShortName")

        assert "is-owngoal" in block
        assert "Eigentor" in block

        css = _read("static", "style.css")
        assert ".mc-pp-marker.is-owngoal" in css

    def test_alle_geforderten_marker_existieren(self):
        block = _mc_block("function mcBuildEventMarkers(stats, options)",
                          "function mcShortName")

        for klasse in ["is-goal", "is-owngoal", "is-assist", "is-yellow", "is-red",
                       "is-out", "is-in"]:
            assert klasse in block

    def test_keine_marker_ohne_ereignisse(self):
        block = _mc_block("function mcBuildEventMarkers(stats, options)",
                          "function mcShortName")
        assert "return count ? markers : null" in block

    def test_vorlage_nur_bei_regulaerem_tor(self):
        block = _mc_block("function mcBuildPlayerEventIndex(events)",
                          "function mcFormatRating")

        assist_start = block.index("const helper = bucketFor(event.assist)")
        vorher = block[:assist_start]
        assert 'if (event.type === "goal")' in vorher

    def test_minute_in_der_liste_aber_nicht_auf_dem_feld(self):
        script = _read("static", "script.js")
        assert "withMinutes: true" in script

        pitch_block = _mc_block("function mcBuildPitchPlayer(player, stats)",
                                "function mcBuildPitch")
        assert "withMinutes" not in pitch_block

    def test_ausgewechselter_startspieler_behaelt_seinen_platz(self):
        """
        Ein eingewechselter Spieler hat kein Raster und darf keine
        erfundene Position bekommen - er bleibt in der Bankliste.
        """
        block = _mc_block("function mcBuildPitch(lineup, eventIndex)",
                          "function mcBuildPlayerRow")

        assert "substitutes" not in block
        assert "player_in" not in block


class TestErsatzbankUndTrainer:
    def test_bank_nutzt_die_bestehende_zeile(self):
        block = _mc_block("function mcBuildLineupBlock(lineup, teamName, eventIndex)",
                          "function mcRenderLineups")

        assert "Ersatzbank" in block
        assert "lineup.substitutes.forEach" in block

    def test_bank_bekommt_bewertung_und_marker(self):
        block = _mc_block("function mcBuildPlayerRow(player, stats)",
                          "function mcBuildLineupBlock")

        assert "mcBuildRatingBadge(player" in block
        assert "mcBuildEventMarkers(stats" in block

    def test_trainer_bleibt_erhalten(self):
        block = _mc_block("function mcBuildLineupBlock(lineup, teamName, eventIndex)",
                          "function mcRenderLineups")

        assert "Trainer" in block
        assert "lineup.coach" in block

    def test_bestehende_zeilenklassen_bleiben(self):
        """LIVE-B-Vertrag: die Listendarstellung behaelt ihre Struktur."""
        block = _mc_block("function mcBuildPlayerRow(player, stats)",
                          "function mcBuildLineupBlock")

        for klasse in ["mc-player-number", "mc-player-name", "mc-player-pos"]:
            assert klasse in block
        assert "dataset.playerId" in block


class TestKeinScopeUeberschuss:
    def test_kein_team_detail(self):
        """
        Team Detail ist Block D2 und ausdruecklich NICHT Teil von D1.

        Player Detail (Block D1, Spieler antippen aus dem Match Center)
        ist dagegen inzwischen umgesetzt - hier stand frueher eine Sperre
        genau dagegen ("Block D ist nicht Teil von Block C"). Diese Sperre
        war die Grenze von Block C und ist jetzt gegenstandslos; siehe
        tests/test_player_profile.py fuer die neuen D1-Vertraege.
        """
        script = _read("static", "script.js")
        source = _read("src", "api", "live_api.py")
        for verboten in ("/api/team-profile", "/api/team-detail", "teamOpen(",
                         "get_team_info", "get_team_standings"):
            assert verboten not in script
            assert verboten not in source

    def test_kein_eigenes_ratingmodell(self):
        source = _read("src", "api", "live_api.py")
        for verboten in ["def compute_rating", "def estimate_rating", "def predict_rating"]:
            assert verboten not in source

    def test_reiter_unveraendert(self):
        html = _read("templates", "index.html")
        import re

        start = html.index('id="mc-tab-bar"')
        block = html[start:html.index("</div>", start)]
        assert re.findall(r'data-mctab="([a-z]+)"', block) == \
            ["overview", "lineups", "events", "stats"]

    def test_polling_unveraendert(self):
        script = _read("static", "script.js")
        assert script.count("setInterval(") == 2

        start = script.index("const MC_REFRESH_INTERVAL_MS")
        line = script[start:script.index(";", start)]
        value = int("".join(ch for ch in line.split("=")[1] if ch.isdigit()))
        assert 20000 <= value <= 35000
