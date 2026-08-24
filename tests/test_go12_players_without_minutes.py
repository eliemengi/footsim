"""
GO 1.2: Spieler ohne aktuelle Einsatzminuten.

WELCHEN FEHLER DIESE TESTS FESTHALTEN
-------------------------------------
Zu Saisonbeginn fuehrt API-Football fuer viele Spieler noch keinen
Statistikdatensatz. Michael Olise und Lamine Yamal waren in 2026/27
dadurch schlicht nicht auffindbar:

    search_players_in_pool()  -> braucht einen Pool-Eintrag
    live_player_search()      -> braucht einen Statistiksatz beim Anbieter

Beide Ebenen setzen voraus, dass der Spieler bereits gespielt hat. Die
in GO 1.1 gebaute Stabilisierung konnte deshalb gar nicht greifen - sie
braucht einen Spieler, den man ueberhaupt erst findet.

Die Loesung darf NICHT sein, den Vorjahresspieler als aktuellen
auszugeben: er koennte den Verein gewechselt oder die Liga verlassen
haben. Belegt wird ueber /players/squads?player=.

Kein Test loest einen echten Provider-Request aus.
"""

import pytest

from src.data import current_squads, player_compare_loader as pcl


# ---------------------------------------------------------------------------
# Testdaten
# ---------------------------------------------------------------------------

BAYERN = 157
BARCELONA = 529
FRANCE = 2
CRYSTAL_PALACE_U23 = 14652

#: Nachgebaut aus der echten Antwort vom 2026-08-22.
SQUADS = {
    19617: [(CRYSTAL_PALACE_U23, "Crystal Palace U23"), (FRANCE, "France"),
            (16621, "France U23"), (BAYERN, "Bayern München")],
    386828: [(9, "Spain"), (BARCELONA, "Barcelona")],
    438123: [(1234, "Oviedo")],          # nicht in einer Top-5-Liga
    999999: [],                           # unbekannt
}

TEAMS_2026 = {
    BAYERN: {"name": "Bayern München", "league_key": "bl1"},
    BARCELONA: {"name": "Barcelona", "league_key": "pd"},
}


@pytest.fixture
def kein_netz(monkeypatch):
    """Alle Provider-Zugriffe durch Fixtures ersetzen."""
    monkeypatch.setattr(current_squads, "all_verified_teams",
                        lambda season=None: dict(TEAMS_2026))
    monkeypatch.setattr(current_squads, "player_squad_team_ids",
                        lambda pid: list(SQUADS.get(int(pid), [])))


def _pool_entry(pid, name, team, league, position="Attacker", minutes=None):
    return {
        "player_id": pid, "name": name, "team_name": team,
        "league_code": league, "position": position, "age": 22,
        "minutes_by_scope": {"club_all": minutes},
    }


# ===========================================================================
# A1 - Verifikation der aktuellen Zugehoerigkeit
# ===========================================================================

class TestTeamVerifikation:

    def test_olise_wird_bayern_zugeordnet(self, kein_netz):
        beleg = current_squads.verify_current_team(19617, 2026)
        assert beleg["team_id"] == BAYERN
        assert beleg["league_key"] == "bl1"
        assert beleg["verified"] is True
        assert beleg["source"] == "apisports_squad"

    def test_yamal_wird_barcelona_zugeordnet(self, kein_netz):
        beleg = current_squads.verify_current_team(386828, 2026)
        assert beleg["team_id"] == BARCELONA
        assert beleg["league_key"] == "pd"

    def test_nationalmannschaft_belegt_keinen_verein(self, kein_netz):
        """
        /players/squads liefert auch Nationalteams und Jugendmannschaften.
        Sie belegen keine Vereinszugehoerigkeit in einer FootSim-Liga.
        """
        beleg = current_squads.verify_current_team(19617, 2026)
        assert beleg["team_id"] not in (FRANCE, CRYSTAL_PALACE_U23)

    def test_spieler_ausserhalb_der_top5_ist_nicht_belegbar(self, kein_netz):
        """Der Kern der konservativen Regel: lieber kein Treffer als ein falscher."""
        assert current_squads.verify_current_team(438123, 2026) is None

    def test_unbekannter_spieler_ist_nicht_belegbar(self, kein_netz):
        assert current_squads.verify_current_team(999999, 2026) is None
        assert current_squads.verify_current_team(None, 2026) is None

    def test_ohne_teamliste_wird_nichts_behauptet(self, monkeypatch):
        """Faellt die Teamliste aus, darf keine Zugehoerigkeit entstehen."""
        monkeypatch.setattr(current_squads, "all_verified_teams", lambda season=None: {})
        monkeypatch.setattr(current_squads, "player_squad_team_ids",
                            lambda pid: [(BAYERN, "Bayern München")])
        assert current_squads.verify_current_team(19617, 2026) is None


# ===========================================================================
# A2 - Echte Nullwerte statt falscher Daten
# ===========================================================================

class TestNullwerte:

    def test_zaehlbare_werte_werden_null(self, kein_netz):
        profil = pcl.apply_no_current_stats(
            {"stats": {}, "data_available": False}, 19617, 2026)

        stats = profil["stats"]
        assert stats["games"]["appearences"] == 0
        assert stats["games"]["minutes"] == 0
        assert stats["goals"]["total"] == 0
        assert stats["goals"]["assists"] == 0
        assert stats["cards"]["yellow"] == 0
        assert profil["minutes"] == 0

    def test_verein_kommt_aus_dem_beleg(self, kein_netz):
        profil = pcl.apply_no_current_stats(
            {"stats": {}, "data_available": False}, 19617, 2026)
        assert profil["team_name"] == "Bayern München"
        assert profil["team_id"] == BAYERN
        assert profil["league_code"] == "bl1"

    def test_status_und_herkunft_sind_gesetzt(self, kein_netz):
        profil = pcl.apply_no_current_stats(
            {"stats": {}, "data_available": False}, 19617, 2026)
        assert profil["availability_status"] == "no_current_appearance"
        assert profil["has_current_stats"] is False
        assert profil["current_team_verified"] is True
        assert profil["source_type"] == "verified_squad"

    def test_ohne_beleg_bleibt_alles_leer(self, kein_netz):
        """Kein Beleg -> keine Nullen, keine Vereinsangabe, keine Aussage."""
        profil = pcl.apply_no_current_stats(
            {"stats": {}, "data_available": False}, 438123, 2026)

        assert profil["availability_status"] == "unavailable"
        assert profil["current_team_verified"] is False
        assert profil.get("team_name") is None
        assert profil.get("minutes") is None

    def test_vorjahreswerte_werden_nicht_kopiert(self, kein_netz):
        """
        Der gefaehrlichste denkbare Fehler: 2025er Tore als 2026er Tore
        auszugeben. Hier wird nichts uebernommen - nur genullt.
        """
        profil = pcl.apply_no_current_stats(
            {"stats": {}, "data_available": False}, 19617, 2026)

        assert profil["stats"]["goals"]["total"] == 0
        assert profil["minutes"] == 0
        assert "previous_season" not in profil

    def test_vorhandene_werte_werden_nicht_ueberschrieben(self, kein_netz):
        """Nur fehlende Felder werden genullt, echte Werte bleiben."""
        profil = pcl.apply_no_current_stats(
            {"stats": {"goals": {"total": 3}}, "data_available": False}, 19617, 2026)
        assert profil["stats"]["goals"]["total"] == 3


# ===========================================================================
# A3/A5 - Vertrag und Stabilisierung
# ===========================================================================

class TestVertrag:

    def test_null_minuten_ergeben_gewicht_null(self):
        from src.data.percentile_engine import current_weight
        assert current_weight(0) == 0.0

    def test_status_wird_aus_den_minuten_abgeleitet(self):
        ableiten = pcl._availability_status
        assert ableiten({"data_available": True, "minutes": 900}) == "current"
        assert ableiten({"data_available": True, "minutes": 55}) == "provisional"
        assert ableiten({"data_available": True, "minutes": 0}) == "no_current_appearance"
        assert ableiten({"data_available": False}) == "unavailable"

    def test_vorgegebener_status_gewinnt(self):
        profil = {"data_available": False,
                  "availability_status": "no_current_appearance"}
        assert pcl._availability_status(profil) == "no_current_appearance"

    def test_alle_statuswerte_sind_dokumentiert(self):
        assert set(pcl.AVAILABILITY_STATES) == {
            "current", "provisional", "no_current_appearance", "unavailable"}

    def test_vergleich_traegt_die_neuen_felder(self, kein_netz):
        a = pcl.apply_no_current_stats({"stats": {}, "data_available": False,
                                        "position": "Attacker"}, 19617, 2026)
        b = {"stats": {}, "data_available": True, "minutes": 1200,
             "position": "Attacker", "season": 2026}

        vergleich = pcl.build_comparison(a, b)

        assert vergleich["availability_status_a"] == "no_current_appearance"
        assert vergleich["availability_status_b"] == "current"
        assert vergleich["has_current_stats_a"] is False
        assert vergleich["has_current_stats_b"] is True
        assert vergleich["current_team_verified_a"] is True
        assert vergleich["source_type_a"] == "verified_squad"
        assert vergleich["minutes_a"] == 0
        assert vergleich["current_weight_a"] == 0.0


# ===========================================================================
# A4 - Identitaet und Deduplizierung
# ===========================================================================

class TestIdentitaet:

    @pytest.fixture
    def suche(self, monkeypatch, kein_netz):
        """Suche mit leerem aktuellem Pool und gefuellter Vorsaison."""
        vorsaison = [
            _pool_entry(19617, "M. Olise", "Bayern München", "bl1", "Midfielder"),
            _pool_entry(386828, "Lamine Yamal", "Barcelona", "pd", "Midfielder"),
            _pool_entry(438123, "Lamine Gueye", "Oviedo", "pd", "Attacker"),
        ]

        def fake_load(season, codes):
            return (vorsaison, list(codes)) if season == 2025 else ([], [])

        monkeypatch.setattr("src.data.player_pool.load_all_players", fake_load)
        monkeypatch.setattr("src.data.percentile_engine.load_usable_snapshot",
                            lambda season, **kw: ({"season": 2025}, 2025))
        return pcl.search_verified_without_stats

    def test_suche_nach_olise_findet_den_null_minuten_spieler(self, suche):
        treffer = suche("Olise", 2026)
        assert len(treffer) == 1
        assert treffer[0]["player_id"] == 19617
        assert treffer[0]["minutes"] == 0
        assert treffer[0]["team_name"] == "Bayern München"
        assert treffer[0]["availability_status"] == "no_current_appearance"

    def test_suche_nach_lamine_trennt_gleichnamige(self, suche):
        """
        "Lamine" trifft zwei Spieler. Nur der belegbare darf erscheinen -
        Namensaehnlichkeit allein fuehrt nie zu einer Zusammenfuehrung.
        """
        treffer = suche("Lamine", 2026)
        ids = {t["player_id"] for t in treffer}

        assert 386828 in ids, "Yamal fehlt"
        assert 438123 not in ids, "Gueye ist nicht belegbar und darf nicht erscheinen"

    def test_keine_duplikate_bei_gleicher_id(self, suche, monkeypatch):
        doppelt = [
            _pool_entry(19617, "M. Olise", "Bayern München", "bl1"),
            _pool_entry(19617, "Michael Olise", "Bayern München", "bl1"),
        ]
        monkeypatch.setattr("src.data.player_pool.load_all_players",
                            lambda season, codes: (doppelt, list(codes)))

        treffer = suche("Olise", 2026)
        assert len(treffer) == 1

    def test_akzente_bleiben_in_der_anzeige_erhalten(self, suche):
        treffer = suche("Olise", 2026)
        assert "ü" in treffer[0]["team_name"], "Umlaut ging verloren"

    def test_zu_kurze_eingabe_loest_keine_pruefung_aus(self, suche, monkeypatch):
        gerufen = []
        monkeypatch.setattr(current_squads, "verify_current_team",
                            lambda pid, season=None: gerufen.append(pid))
        assert suche("Ol", 2026) == []
        assert not gerufen, "kurze Eingabe hat Requests ausgeloest"

    def test_pruefung_ist_begrenzt(self, suche, monkeypatch):
        """Jede Pruefung kostet einen Request - eine breite Suche darf nicht eskalieren."""
        viele = [_pool_entry(1000 + i, f"Mario {i}", "X", "bl1") for i in range(50)]
        monkeypatch.setattr("src.data.player_pool.load_all_players",
                            lambda season, codes: (viele, list(codes)))

        gerufen = []

        def zaehlend(pid, season=None):
            gerufen.append(pid)
            return None

        monkeypatch.setattr(current_squads, "verify_current_team", zaehlend)
        suche("Mario", 2026, max_candidates=5)
        assert len(gerufen) == 5


# ===========================================================================
# A7 - Automatischer Uebergang
# ===========================================================================

class TestAutomatischerUebergang:

    def test_echte_daten_gewinnen_ohne_zutun(self, kein_netz):
        """
        Sobald der Anbieter Werte liefert, greift die Bruecke nicht mehr.
        Kein manueller Cache-Eingriff, kein Loeschen.
        """
        mit_daten = {"stats": {"goals": {"total": 2}}, "data_available": True,
                     "minutes": 180}

        assert pcl._availability_status(mit_daten) == "provisional"
        assert mit_daten.get("source_type") is None

    def test_pool_treffer_hat_vorrang_vor_der_bruecke(self, monkeypatch, kein_netz):
        """Ist der Spieler im aktuellen Pool, wird gar nicht erst geprueft."""
        monkeypatch.setattr(pcl, "search_players_in_pool",
                            lambda q, s: [{"player_id": 19617, "minutes": 300}])
        gerufen = []
        monkeypatch.setattr(pcl, "search_verified_without_stats",
                            lambda *a, **k: gerufen.append(1) or [])

        treffer = pcl.search_players("Olise", 2026)
        assert treffer[0]["minutes"] == 300
        assert not gerufen, "Bruecke lief trotz Pool-Treffer"
