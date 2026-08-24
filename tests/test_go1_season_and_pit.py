"""
GO 1: Saisonkorrektheit und Point-in-Time-Haertung.

WELCHEN FEHLER DIESE TESTS FESTHALTEN
-------------------------------------
A) Saisonbruch im Strength-Pfad

   get_league_strengths(..., current_season=2026) kannte die Saison,
   reichte sie aber nicht weiter:

       strength_provider:  get_squad_impact(league_key)        # ohne Saison
       squad_impact:       season = season or CURRENT_SEASON   # -> 2025
       apisports_api:      CURRENT_SEASON = 2025               # fest verdrahtet

   In EINER Staerkeberechnung trafen damit football-data-Saison 2026 und
   API-Sports-Saison 2025 aufeinander: die Liga rechnete 2026/27, die
   Ausfaelle und Torschuetzen stammten aus 2025/26. Seit der frueher
   defekte Import repariert ist, laeuft das Feature - und war dadurch
   nicht mehr wirkungslos, sondern falsch wirksam.

B) Point-in-Time nur durch Zuruf

   build_season_profiles() filterte nicht selbst. Die historische
   Korrektheit hing daran, dass jeder Aufrufer sauber vorgefiltert hat.

Alle Tests laufen ohne echte Provider-Requests.
"""

import datetime

import pytest

from src.api import apisports_api
from src.features import squad_impact, strength_provider, team_profile


# ---------------------------------------------------------------------------
# Testdaten
# ---------------------------------------------------------------------------

def _match(match_id, date, home_id, away_id, home_goals=2, away_goals=1,
           status=None, matchday=1):
    entry = {
        "match_id": match_id,
        "date": date,
        "matchday": matchday,
        "home_id": home_id,
        "away_id": away_id,
        "home_goals": home_goals,
        "away_goals": away_goals,
    }
    if status is not None:
        entry["status"] = status
    return entry


def _payload(matches, season=2025):
    return {
        "meta": {"season": season, "api_code": "BL1"},
        "teams": {1: {"name": "Team 1"}, 2: {"name": "Team 2"}},
        "matches": matches,
    }


def _standings():
    return [
        {"team_id": 1, "team_name": "Team 1", "played": 3},
        {"team_id": 2, "team_name": "Team 2", "played": 3},
    ]


# ===========================================================================
# A - Saison wird explizit durchgereicht
# ===========================================================================

class TestSaisonWeitergabe:

    def test_strength_pfad_reicht_die_saison_an_die_kaderwirkung(self, monkeypatch):
        """
        Der Kerntest fuer GO 1.

        Vor dem Fix kam hier None an und squad_impact fiel auf den festen
        Modulwert 2025 zurueck.
        """
        gesehen = {}

        def spy(competition_code, season=None, as_of=None):
            gesehen["season"] = season
            gesehen["as_of"] = as_of
            return {}

        monkeypatch.setattr(squad_impact, "get_squad_impact", spy)
        monkeypatch.setattr(strength_provider, "load_available_seasons",
                            lambda api_code, seasons: [])

        strength_provider.get_league_strengths(
            league_key="bl1",
            standings_table=_standings(),
            current_season=2026,
        )

        assert gesehen["season"] == 2026, (
            f"Kaderwirkung wurde mit Saison {gesehen['season']} geladen, "
            f"waehrend die Liga 2026/27 rechnet"
        )

    def test_eine_simulation_fuer_2025_verwendet_weiterhin_2025(self, monkeypatch):
        """Gegenprobe: der Fix darf nicht einfach 2026 erzwingen."""
        gesehen = {}
        monkeypatch.setattr(squad_impact, "get_squad_impact",
                            lambda c, season=None, as_of=None: gesehen.setdefault("s", season) or {})
        monkeypatch.setattr(strength_provider, "load_available_seasons",
                            lambda api_code, seasons: [])

        strength_provider.get_league_strengths(
            league_key="bl1", standings_table=_standings(), current_season=2025)

        assert gesehen["s"] == 2025

    def test_torschuetzen_und_verletzungen_bekommen_die_saison(self, monkeypatch):
        """Die Saison muss bis zu den beiden Provider-Aufrufen durchreichen."""
        from src.utils import cache

        aufrufe = {}

        def fake_get(endpoint, params=None):
            aufrufe[endpoint] = params
            return []

        monkeypatch.setattr(apisports_api, "_get", fake_get)
        monkeypatch.setattr(apisports_api, "APISPORTS_KEY", "test-key")

        # cached_call ist prozessweit. Ohne diesen Schnitt koennte ein
        # frueherer Test denselben Schluessel gefuellt haben und der
        # Loader liefe hier gar nicht erst an.
        cache.invalidate("apisports:scorers:bl1:2026:20")
        cache.invalidate("apisports:injuries:bl1:2026")

        apisports_api.get_top_scorers("bl1", season=2026)
        apisports_api.get_injuries("bl1", season=2026)

        assert aufrufe["players/topscorers"]["season"] == 2026
        assert aufrufe["injuries"]["season"] == 2026

    def test_cache_keys_trennen_die_saisons(self, monkeypatch):
        """
        2025 und 2026 duerfen sich niemals denselben Eintrag teilen -
        sonst liefert eine 2026er-Anfrage stillschweigend 2025er-Daten.
        """
        keys = []

        def spy(key, ttl_seconds, loader, **kwargs):
            keys.append(key)
            return {}

        monkeypatch.setattr(squad_impact, "disk_cached_call", spy)

        squad_impact.get_squad_impact("bl1", season=2025)
        squad_impact.get_squad_impact("bl1", season=2026)

        assert keys == ["squad_impact:bl1:2025", "squad_impact:bl1:2026"]
        assert len(set(keys)) == 2

    def test_expliziter_wert_wird_nie_vom_fallback_ueberschrieben(self):
        # Auch wenn das Datum eine andere Saison ergaebe.
        assert apisports_api.resolve_season(2019, today=datetime.date(2026, 8, 22)) == 2019

    def test_dynamischer_fallback_fuer_august_2026(self):
        """Der im Auftrag geforderte Kontrollfall."""
        assert apisports_api.resolve_season(today=datetime.date(2026, 8, 22)) == 2026

    @pytest.mark.parametrize("tag,erwartet", [
        (datetime.date(2026, 6, 30), 2025),   # vor dem Saisonstart
        (datetime.date(2026, 7, 1), 2026),    # erster Tag der neuen Zaehlung
        (datetime.date(2026, 12, 31), 2026),  # Winter derselben Saison
        (datetime.date(2027, 5, 20), 2026),   # Saisonende im Folgejahr
    ])
    def test_fallback_folgt_der_startjahr_konvention(self, tag, erwartet):
        assert apisports_api.resolve_season(today=tag) == erwartet

    def test_current_season_ist_kein_fester_wert_mehr(self):
        """
        Der alte Hardcode 2025 darf nicht zurueckkehren. CURRENT_SEASON
        bleibt als Bequemlichkeitswert fuer TTL-Heuristik erhalten, wird
        aber abgeleitet.
        """
        from pathlib import Path
        quelle = (Path(__file__).parent.parent / "src" / "api" / "apisports_api.py").read_text(encoding="utf-8")
        code = "\n".join(l for l in quelle.splitlines() if not l.strip().startswith("#"))

        assert "CURRENT_SEASON = 2025" not in code
        assert "CURRENT_SEASON = resolve_season()" in code
        # Keine Signatur bindet den Wert mehr beim Import.
        assert "season=CURRENT_SEASON" not in code

    def test_ungueltige_saison_faellt_auf(self):
        """Ein Tippfehler darf keinen falschen Cache-Key erzeugen."""
        for kaputt in ("zweitausend", None.__class__, 12, 99999):
            with pytest.raises(ValueError):
                apisports_api.resolve_season(kaputt)

    def test_ziffernstring_wird_akzeptiert(self):
        assert apisports_api.resolve_season("2026") == 2026

    def test_provider_ausfall_bleibt_neutral(self, monkeypatch):
        """Ohne API-Schluessel laeuft die Simulation weiter, nur ohne Faktor."""
        def boom(key, ttl_seconds, loader, **kwargs):
            return loader()

        monkeypatch.setattr(squad_impact, "disk_cached_call", boom)
        monkeypatch.setattr(apisports_api, "APISPORTS_KEY", None)

        assert squad_impact.get_squad_impact("bl1", season=2026) == {}


# ===========================================================================
# B - Point-in-Time
# ===========================================================================

class TestPointInTime:

    def test_ohne_cutoff_bleibt_das_ergebnis_unveraendert(self):
        """
        Rueckwaertskompatibilitaet: cutoff=None muss exakt dasselbe
        liefern wie vor GO 1.
        """
        matches = [
            _match(1, "2025-08-10", 1, 2),
            _match(2, "2025-09-10", 2, 1),
            _match(3, "2025-10-10", 1, 2),
        ]
        payload = _payload(matches)

        ohne = team_profile.build_season_profiles(payload)
        explizit_none = team_profile.build_season_profiles(payload, cutoff=None)

        assert ohne == explizit_none
        # Beide Teams stehen in allen drei Partien.
        assert ohne["profiles"][1]["matches_used"] == 3
        assert ohne["profiles"][2]["matches_used"] == 3

    def test_spiel_vor_dem_stichtag_zaehlt(self):
        payload = _payload([_match(1, "2025-08-10", 1, 2)])
        result = team_profile.build_season_profiles(payload, cutoff="2025-09-01")
        assert result["profiles"][1]["matches_used"] == 1

    def test_spiel_nach_dem_stichtag_wird_ausgeschlossen(self):
        payload = _payload([
            _match(1, "2025-08-10", 1, 2),
            _match(2, "2025-10-10", 1, 2),
        ])
        result = team_profile.build_season_profiles(payload, cutoff="2025-09-01")
        assert result["profiles"][1]["matches_used"] == 1

    def test_spiel_am_stichtag_folgt_der_pit_semantik(self):
        """
        point_in_time behandelt ein Spiel am Stichtag ohne Uhrzeit als
        NICHT bekannt. Genau dadurch kann ein zu prognostizierendes Spiel
        nicht Teil seines eigenen Profils werden.
        """
        payload = _payload([_match(1, "2025-09-01", 1, 2)])
        result = team_profile.build_season_profiles(payload, cutoff="2025-09-01")
        assert result["profiles"] == {}

    def test_zielspiel_ist_nicht_teil_seines_eigenen_profils(self):
        payload = _payload([
            _match(1, "2025-08-10", 1, 2),
            _match(99, "2025-09-01", 1, 2, home_goals=5, away_goals=0),
        ])
        result = team_profile.build_season_profiles(payload, cutoff="2025-09-01")

        assert result["profiles"][1]["matches_used"] == 1
        assert result["profiles"][1]["stats"]["goals_for"] == 2

    def test_unfertiges_spiel_gilt_nicht_als_ergebnis(self):
        payload = _payload([
            _match(1, "2025-08-10", 1, 2),
            _match(2, "2025-08-15", 1, 2, home_goals=None, away_goals=None),
        ])
        result = team_profile.build_season_profiles(payload, cutoff="2025-09-01")
        assert result["profiles"][1]["matches_used"] == 1

    def test_nicht_abgeschlossener_status_wird_verworfen(self):
        payload = _payload([
            _match(1, "2025-08-10", 1, 2, status="FINISHED"),
            _match(2, "2025-08-15", 1, 2, status="SCHEDULED"),
        ])
        result = team_profile.build_season_profiles(payload, cutoff="2025-09-01")
        assert result["profiles"][1]["matches_used"] == 1

    def test_assert_no_future_data_erkennt_eingeschleuste_zukunft(self):
        from src.features.point_in_time import assert_no_future_data

        vergangenheit = [_match(1, "2025-08-10", 1, 2)]
        assert_no_future_data(vergangenheit, "2025-09-01")

        # Die vorhandene Funktion meldet den Verstoss als ValueError mit
        # Fundstellen - bewusst laut statt still.
        with pytest.raises(ValueError, match="nach dem Stichtag"):
            assert_no_future_data(
                vergangenheit + [_match(2, "2025-10-10", 1, 2)], "2025-09-01")

    def test_matches_through_date_liegt_nie_nach_dem_stichtag(self, monkeypatch):
        monkeypatch.setattr(strength_provider, "load_available_seasons",
                            lambda api_code, seasons: [])
        monkeypatch.setattr(squad_impact, "get_squad_impact",
                            lambda c, season=None, as_of=None: {})

        result = strength_provider.get_league_strengths(
            league_key="bl1",
            standings_table=_standings(),
            current_matches=[
                _match(1, "2025-08-10", 1, 2),
                _match(2, "2025-10-10", 1, 2),
            ],
            current_season=2025,
            cutoff="2025-09-01",
        )

        prov = result["summary"]["provenance"]
        assert prov["matches_through_date"] <= "2025-09-01"
        assert prov["cutoff"] == "2025-09-01"


# ===========================================================================
# B6 - Historische Kaderdaten duerfen nicht leaken
# ===========================================================================

class TestHistorischeKaderdaten:

    def test_ohne_snapshot_bleibt_neutral_und_kein_provider_aufruf(self, monkeypatch):
        """
        Der wichtigste Leakage-Schutz: ein Backtest darf sich heutige
        Verletzungen nicht per Live-Request beschaffen.
        """
        def darf_nicht(*args, **kwargs):
            raise AssertionError("Live-Provider-Aufruf in historischer Berechnung")

        monkeypatch.setattr(squad_impact, "disk_cached_call", darf_nicht)
        monkeypatch.setattr(apisports_api, "_get", darf_nicht)

        from src.data import snapshot_archive
        monkeypatch.setattr(snapshot_archive, "snapshot_as_of",
                            lambda kind, cutoff, key=None: None)

        impact = squad_impact.get_squad_impact("bl1", season=2026, as_of="2025-11-12")
        assert impact == {}

    def test_nur_ein_zum_stichtag_vorhandener_stand_wird_verwendet(self, monkeypatch):
        gesehen = {}

        def fake_snapshot_as_of(kind, cutoff, key=None):
            gesehen["kind"] = kind
            gesehen["cutoff"] = cutoff
            gesehen["key"] = key
            return {"payload": {"impact": {"5": {"attack_modifier": 0.9}}}}

        from src.data import snapshot_archive
        monkeypatch.setattr(snapshot_archive, "snapshot_as_of", fake_snapshot_as_of)
        monkeypatch.setattr(squad_impact, "disk_cached_call",
                            lambda *a, **k: pytest.fail("kein Cache-Pfad erwartet"))

        impact = squad_impact.get_squad_impact("bl1", season=2026, as_of="2025-11-12")

        assert gesehen["kind"] == "squad"
        assert gesehen["cutoff"] == "2025-11-12"
        assert gesehen["key"] == "bl1_2026"
        # Schluessel werden auf Zahlen normalisiert wie im Live-Pfad.
        assert impact == {5: {"attack_modifier": 0.9}}

    def test_strength_pfad_reicht_den_stichtag_als_as_of_weiter(self, monkeypatch):
        gesehen = {}
        monkeypatch.setattr(squad_impact, "get_squad_impact",
                            lambda c, season=None, as_of=None: gesehen.update(
                                season=season, as_of=as_of) or {})
        monkeypatch.setattr(strength_provider, "load_available_seasons",
                            lambda api_code, seasons: [])

        strength_provider.get_league_strengths(
            league_key="bl1", standings_table=_standings(),
            current_season=2026, cutoff="2025-11-12")

        assert gesehen["as_of"] == "2025-11-12"
        assert gesehen["season"] == 2026

    def test_provenienz_nennt_die_quelle_der_kaderwirkung(self, monkeypatch):
        monkeypatch.setattr(strength_provider, "load_available_seasons",
                            lambda api_code, seasons: [])
        monkeypatch.setattr(squad_impact, "get_squad_impact",
                            lambda c, season=None, as_of=None: {})

        live = strength_provider.get_league_strengths(
            league_key="bl1", standings_table=_standings(), current_season=2026)
        historisch = strength_provider.get_league_strengths(
            league_key="bl1", standings_table=_standings(),
            current_season=2026, cutoff="2025-11-12")

        assert live["summary"]["provenance"]["squad_source"] == "live"
        assert live["summary"]["provenance"]["cutoff"] is None
        assert historisch["summary"]["provenance"]["squad_source"] == "snapshot"
