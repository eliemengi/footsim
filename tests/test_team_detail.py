"""
Tests fuer die Team-Detailseite (Block LIVE D2).

Abgedeckt:
  A) Normalisierung: Teamidentitaet, Standings-Zeilenauswahl, Spiele,
     Kader, Trainer - reine Logik, kein Netzwerk
  B) Cache: getrennte Kategorien, Standings-Sharing zwischen Teams
     derselben Liga/Saison
  C) HTTP-Route /api/team-detail
  D) Wiederverwendung / Architekturgrenzen (kein Crosswalk, kein
     teams/statistics)

Provider-Funktionen werden konsequent gemockt - kein Testlauf loest
einen echten API-Request aus. Disk-Cache-Tests isolieren CACHE_DIR in
ein temporaeres Verzeichnis, exakt wie in tests/test_live_block_b.py.
"""

import os

import pytest

from src.api import team_detail


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(PROJECT_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


PSG_ID = 85
ARSENAL_ID = 42
CL_LEAGUE_ID = 2
SEASON = 2025


# ---------------------------------------------------------------------------
# Testdaten, im Format der echten API-Football-Antworten (real geprueft)
# ---------------------------------------------------------------------------

def make_raw_team_info(team_id=PSG_ID, name="Paris Saint Germain",
                       logo="https://x/85.png", country="France",
                       founded=1970, venue_name="Parc des Princes",
                       venue_city="Paris", venue_address="24, rue du Commandant Guilbaud",
                       venue_capacity=47929, venue_surface="grass",
                       venue_image="https://x/venue671.png"):
    venue = {}
    if venue_name is not None:
        venue["name"] = venue_name
    if venue_city is not None:
        venue["city"] = venue_city
    if venue_address is not None:
        venue["address"] = venue_address
    if venue_capacity is not None:
        venue["capacity"] = venue_capacity
    if venue_surface is not None:
        venue["surface"] = venue_surface
    if venue_image is not None:
        venue["image"] = venue_image

    return [{
        "team": {"id": team_id, "name": name, "logo": logo,
                 "country": country, "founded": founded},
        "venue": venue,
    }]


def make_standings_row(team_id=PSG_ID, team_name="Paris Saint Germain",
                       rank=11, points=14, goals_diff=10, form="DLDWL",
                       description="Promotion - Champions League (Play Offs: 1/16-finals)"):
    return {
        "rank": rank,
        "team": {"id": team_id, "name": team_name, "logo": "https://x/t.png"},
        "points": points,
        "goalsDiff": goals_diff,
        "group": "UEFA Champions League",
        "form": form,
        "status": "same",
        "description": description,
        "all": {"played": 8, "win": 4, "draw": 2, "lose": 2,
                "goals": {"for": 21, "against": 11}},
        "home": {"played": 4, "win": 2, "draw": 1, "lose": 1,
                "goals": {"for": 11, "against": 6}},
        "away": {"played": 4, "win": 2, "draw": 1, "lose": 1,
                "goals": {"for": 10, "against": 5}},
        "update": "2026-06-02T00:00:00+00:00",
    }


def make_raw_standings(league_id=CL_LEAGUE_ID, season=SEASON, groups=None):
    """groups: Liste von Gruppen (Liste von Zeilen). Standard: eine Gruppe."""
    if groups is None:
        groups = [[make_standings_row()]]
    return [{
        "league": {
            "id": league_id, "name": "UEFA Champions League",
            "country": "World", "season": season,
            "standings": groups,
        },
    }]


def make_raw_fixture(fixture_id=1, home_id=PSG_ID, away_id=ARSENAL_ID,
                     home_name="Paris Saint Germain", away_name="Arsenal",
                     status="FT", home_goals=1, away_goals=1,
                     date="2026-08-11T18:00:00+02:00"):
    return {
        "fixture": {
            "id": fixture_id, "date": date,
            "status": {"long": "Match Finished", "short": status,
                      "elapsed": None, "extra": None},
        },
        "league": {"id": CL_LEAGUE_ID, "name": "UEFA Champions League",
                  "logo": "https://x/l2.png"},
        "teams": {
            "home": {"id": home_id, "name": home_name, "logo": "https://x/h.png"},
            "away": {"id": away_id, "name": away_name, "logo": "https://x/a.png"},
        },
        "goals": {"home": home_goals, "away": away_goals},
    }


def make_squad_player(player_id=1, name="Test Spieler", number=9,
                      position="Attacker", age=25, photo="https://x/p.png"):
    return {"id": player_id, "name": name, "age": age, "number": number,
           "position": position, "photo": photo}


def make_raw_squad(team_id=PSG_ID, players=None):
    return [{
        "team": {"id": team_id, "name": "Paris Saint Germain"},
        "players": players if players is not None else [make_squad_player()],
    }]


def make_raw_coach(coach_id=193, name="Luis Enrique", career=None,
                   nationality="Spain", age=55, photo="https://x/c.png"):
    return [{
        "id": coach_id, "name": name, "age": age,
        "birth": {"date": "1970-05-08", "place": "Gijon", "country": "Spain"},
        "nationality": nationality,
        "height": "180 cm", "weight": "73 kg", "photo": photo,
        "team": {"id": PSG_ID, "name": "PSG"},
        "career": career if career is not None else [
            {"team": {"id": PSG_ID, "name": "PSG"}, "start": "2023-07-01", "end": None},
            {"team": {"id": 9, "name": "Spain"}, "start": "2018-07-01", "end": "2022-12-01"},
        ],
    }]


# ===========================================================================
# A) Normalisierung
# ===========================================================================

class TestTeamInfo:
    def test_grundfelder(self):
        info = team_detail.normalize_team_info(make_raw_team_info())
        assert info["id"] == PSG_ID
        assert info["name"] == "Paris Saint Germain"
        assert info["logo"] == "https://x/85.png"
        assert info["country"] == "France"
        assert info["founded"] == 1970
        assert info["venue_name"] == "Parc des Princes"
        assert info["venue_city"] == "Paris"

    def test_unbekannte_team_id(self):
        assert team_detail.normalize_team_info([]) is None
        assert team_detail.normalize_team_info(None) is None

    def test_fehlendes_logo(self):
        info = team_detail.normalize_team_info(make_raw_team_info(logo=None))
        assert info["logo"] is None
        assert info["name"] == "Paris Saint Germain"

    def test_fehlendes_stadion(self):
        info = team_detail.normalize_team_info(
            make_raw_team_info(venue_name=None, venue_city=None))
        assert info["venue_name"] is None
        assert info["venue_city"] is None

    def test_kaputter_eintrag_wirft_nicht(self):
        assert team_detail.normalize_team_info([None]) is None
        assert team_detail.normalize_team_info(["kaputt"]) is None
        assert team_detail.normalize_team_info([{}]) is None

    # --- Club Facts (Block D2+) - alle Felder aus derselben teams?id=
    # Antwort, die die Grundfelder oben schon liefert. Kein eigener Test
    # fuer "kein zusaetzlicher Request", weil es dafuer schlicht keinen
    # zweiten Provider-Aufruf gibt, den man mocken koennte.

    def test_club_facts_vorhanden(self):
        info = team_detail.normalize_team_info(make_raw_team_info())
        assert info["venue_address"] == "24, rue du Commandant Guilbaud"
        assert info["venue_capacity"] == 47929
        assert info["venue_surface"] == "grass"
        assert info["venue_image"] == "https://x/venue671.png"

    def test_gruendungsjahr_fehlt(self):
        info = team_detail.normalize_team_info(make_raw_team_info(founded=None))
        assert info["founded"] is None

    def test_gruendungsjahr_null_gilt_als_fehlend(self):
        """
        Der Provider liefert founded=0 gelegentlich als Platzhalter fuer
        "unbekannt", nicht als echtes Jahr - 0 ist kein gueltiges
        Gruendungsjahr.
        """
        info = team_detail.normalize_team_info(make_raw_team_info(founded=0))
        assert info["founded"] is None

    def test_kapazitaet_fehlt(self):
        info = team_detail.normalize_team_info(make_raw_team_info(venue_capacity=None))
        assert info["venue_capacity"] is None

    def test_stadionbild_fehlt(self):
        info = team_detail.normalize_team_info(make_raw_team_info(venue_image=None))
        assert info["venue_image"] is None

    def test_oberflaeche_fehlt(self):
        info = team_detail.normalize_team_info(make_raw_team_info(venue_surface=None))
        assert info["venue_surface"] is None

    def test_alle_club_facts_fehlen_gleichzeitig(self):
        """Weder Gruendungsjahr noch Venue-Zusatzfelder - kein Absturz."""
        info = team_detail.normalize_team_info(make_raw_team_info(
            founded=None, venue_address=None, venue_capacity=None,
            venue_surface=None, venue_image=None))
        assert info["id"] == PSG_ID
        assert info["founded"] is None
        assert info["venue_address"] is None
        assert info["venue_capacity"] is None
        assert info["venue_surface"] is None
        assert info["venue_image"] is None


class TestStandings:
    def test_richtige_zeile_aus_mehreren_teams(self):
        rows = [
            make_standings_row(team_id=1, rank=1),
            make_standings_row(team_id=PSG_ID, rank=11),
            make_standings_row(team_id=3, rank=20),
        ]
        raw = make_raw_standings(groups=[rows])
        row = team_detail.find_standings_row(raw, PSG_ID)
        assert row["rank"] == 11

    def test_zeile_ueber_mehrere_gruppen_gefunden(self):
        """Klassisches Gruppenformat (mehrere Untertabellen) wird durchsucht."""
        raw = make_raw_standings(groups=[
            [make_standings_row(team_id=1, rank=1)],
            [make_standings_row(team_id=PSG_ID, rank=2)],
        ])
        row = team_detail.find_standings_row(raw, PSG_ID)
        assert row is not None
        assert row["rank"] == 2

    def test_fehlende_teamzeile(self):
        raw = make_raw_standings(groups=[[make_standings_row(team_id=999)]])
        assert team_detail.find_standings_row(raw, PSG_ID) is None

    def test_leere_standings_antwort(self):
        assert team_detail.find_standings_row([], PSG_ID) is None
        assert team_detail.find_standings_row(None, PSG_ID) is None

    def test_normalisierte_felder(self):
        row = make_standings_row()
        normalized = team_detail.normalize_standings_row(row)

        assert normalized["rank"] == 11
        assert normalized["points"] == 14
        assert normalized["goals_diff"] == 10
        assert normalized["form"] == "DLDWL"
        assert normalized["wins"] == 4
        assert normalized["draws"] == 2
        assert normalized["losses"] == 2
        assert normalized["goals_for"] == 21
        assert normalized["goals_against"] == 11

    def test_form_kommt_unveraendert_vom_provider(self):
        """Keine eigene Formberechnung - der String wird 1:1 durchgereicht."""
        row = make_standings_row(form="WWWLD")
        assert team_detail.normalize_standings_row(row)["form"] == "WWWLD"

    def test_cl_el_description_defensiv_durchgereicht(self):
        """
        Seit der Ligaphasen-Reform keine klassische Gruppenaussage mehr -
        wird unveraendert als Text behandelt, nicht interpretiert.
        """
        row = make_standings_row(
            description="Promotion - Champions League (Play Offs: 1/16-finals)")
        normalized = team_detail.normalize_standings_row(row)
        assert normalized["description"] == "Promotion - Champions League (Play Offs: 1/16-finals)"

    def test_none_row_ergibt_none(self):
        assert team_detail.normalize_standings_row(None) is None
        assert team_detail.normalize_standings_row({}) is None


class TestTeamFixtures:
    def test_heimspiel_aus_teamsicht(self):
        raw = make_raw_fixture(home_id=PSG_ID, away_id=ARSENAL_ID,
                               home_goals=2, away_goals=1)
        fixture = team_detail.normalize_team_fixture(raw, PSG_ID)

        assert fixture["is_home"] is True
        assert fixture["opponent_id"] == ARSENAL_ID
        assert fixture["opponent_name"] == "Arsenal"
        assert fixture["team_goals"] == 2
        assert fixture["opponent_goals"] == 1

    def test_auswaertsspiel_aus_teamsicht(self):
        raw = make_raw_fixture(home_id=ARSENAL_ID, away_id=PSG_ID,
                               home_goals=2, away_goals=1)
        fixture = team_detail.normalize_team_fixture(raw, PSG_ID)

        assert fixture["is_home"] is False
        assert fixture["opponent_id"] == ARSENAL_ID
        assert fixture["team_goals"] == 1
        assert fixture["opponent_goals"] == 2

    def test_statusuebersetzung_wiederverwendet(self):
        """Dieselbe Uebersetzung wie live_api.classify_status() - keine zweite."""
        raw = make_raw_fixture(status="NS")
        fixture = team_detail.normalize_team_fixture(raw, PSG_ID)
        assert fixture["phase"] == "scheduled"

        raw_live = make_raw_fixture(status="1H")
        assert team_detail.normalize_team_fixture(raw_live, PSG_ID)["phase"] == "live"

    def test_kommendes_spiel_ohne_ergebnis(self):
        raw = make_raw_fixture(status="NS", home_goals=None, away_goals=None)
        fixture = team_detail.normalize_team_fixture(raw, PSG_ID)
        assert fixture["team_goals"] is None
        assert fixture["opponent_goals"] is None

    def test_kaputter_eintrag_wird_uebersprungen(self):
        assert team_detail.normalize_team_fixture(None, PSG_ID) is None
        assert team_detail.normalize_team_fixture({}, PSG_ID) is None

    def test_liste_ueberspringt_kaputte_eintraege(self):
        raw = [make_raw_fixture(fixture_id=1), None, {}, make_raw_fixture(fixture_id=2)]
        fixtures = team_detail.normalize_team_fixtures(raw, PSG_ID)
        assert [f["fixture_id"] for f in fixtures] == [1, 2]

    def test_leere_liste(self):
        assert team_detail.normalize_team_fixtures([], PSG_ID) == []
        assert team_detail.normalize_team_fixtures(None, PSG_ID) == []


class TestSquad:
    def test_player_id_bleibt_erhalten(self):
        """Ohne die ID koennte kein D1-Spielerprofil geoeffnet werden."""
        squad = team_detail.normalize_squad(make_raw_squad(
            players=[make_squad_player(player_id=162453, name="L. Chevalier")]))
        assert squad[0]["id"] == 162453

    def test_grundfelder(self):
        squad = team_detail.normalize_squad(make_raw_squad(
            players=[make_squad_player(number=30, position="Goalkeeper", age=24)]))
        entry = squad[0]
        assert entry["number"] == 30
        assert entry["position"] == "Goalkeeper"
        assert entry["age"] == 24
        assert entry["photo"] == "https://x/p.png"

    def test_leerer_kader(self):
        assert team_detail.normalize_squad(make_raw_squad(players=[])) == []
        assert team_detail.normalize_squad([]) == []
        assert team_detail.normalize_squad(None) == []

    def test_eintrag_ohne_id_wird_uebersprungen(self):
        players = [make_squad_player(player_id=None), make_squad_player(player_id=1)]
        squad = team_detail.normalize_squad(make_raw_squad(players=players))
        assert len(squad) == 1
        assert squad[0]["id"] == 1

    def test_grosser_kader(self):
        players = [make_squad_player(player_id=i) for i in range(1, 33)]
        squad = team_detail.normalize_squad(make_raw_squad(players=players))
        assert len(squad) == 32


class TestCoach:
    def test_aktueller_trainer(self):
        coach = team_detail.normalize_coach(make_raw_coach())
        assert coach["name"] == "Luis Enrique"
        assert coach["nationality"] == "Spain"
        assert coach["age"] == 55
        assert coach["since"] == "2023-07-01"

    def test_aktueller_eintrag_nicht_ueber_index_angenommen(self):
        """
        end=None entscheidet, nicht career[0] - hier bewusst an Position 1
        platziert, um das zu erzwingen.
        """
        career = [
            {"team": {"id": 9, "name": "Spain"}, "start": "2018-07-01", "end": "2022-12-01"},
            {"team": {"id": PSG_ID, "name": "PSG"}, "start": "2023-07-01", "end": None},
        ]
        coach = team_detail.normalize_coach(make_raw_coach(career=career))
        assert coach["since"] == "2023-07-01"

    def test_kein_trainer(self):
        assert team_detail.normalize_coach([]) is None
        assert team_detail.normalize_coach(None) is None

    def test_karrierehistorie_wird_nicht_ausgeliefert(self):
        """Nur der aktuelle Verein/das Startdatum, keine volle career-Liste."""
        coach = team_detail.normalize_coach(make_raw_coach())
        assert "career" not in coach

    def test_kein_aktueller_eintrag_ergibt_kein_since(self):
        """Alle career-Eintraege abgeschlossen (end != None) - since bleibt None."""
        career = [{"team": {"id": 9}, "start": "2018-01-01", "end": "2020-01-01"}]
        coach = team_detail.normalize_coach(make_raw_coach(career=career))
        assert coach["since"] is None


# ===========================================================================
# B) Cache
# ===========================================================================

class TestCache:
    @pytest.fixture(autouse=True)
    def _isolierter_cache(self, tmp_path, monkeypatch):
        from src.utils import disk_cache
        monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path))
        self.tmp_path = tmp_path

    def _patch_all(self, monkeypatch, calls):
        monkeypatch.setattr(team_detail.apisports_api, "get_team_info",
                            lambda tid: calls.append(("info", tid)) or make_raw_team_info(team_id=tid))
        monkeypatch.setattr(team_detail.apisports_api, "get_standings_table",
                            lambda lid, season: calls.append(("standings", lid, season)) or
                            make_raw_standings(league_id=lid, season=season, groups=[[
                                make_standings_row(team_id=PSG_ID),
                                make_standings_row(team_id=ARSENAL_ID, rank=1),
                            ]]))
        monkeypatch.setattr(team_detail.apisports_api, "get_team_fixtures",
                            lambda tid, last=None, next=None: calls.append(("fixtures", tid, last, next)) or
                            [make_raw_fixture(home_id=tid, away_id=999)])
        monkeypatch.setattr(team_detail.apisports_api, "get_team_squad",
                            lambda tid: calls.append(("squad", tid)) or make_raw_squad(team_id=tid))
        monkeypatch.setattr(team_detail.apisports_api, "get_team_coach",
                            lambda tid: calls.append(("coach", tid)) or make_raw_coach())

    def test_teamidentitaet_gecacht(self, monkeypatch):
        calls = []
        monkeypatch.setattr(team_detail.apisports_api, "get_team_info",
                            lambda tid: calls.append(tid) or make_raw_team_info(team_id=tid))

        team_detail.get_team_identity(PSG_ID)
        team_detail.get_team_identity(PSG_ID)

        assert calls == [PSG_ID]

    def test_standings_pro_liga_und_saison_gecacht(self, monkeypatch):
        calls = []
        monkeypatch.setattr(team_detail.apisports_api, "get_standings_table",
                            lambda lid, season: calls.append((lid, season)) or
                            make_raw_standings(league_id=lid, season=season))

        team_detail.get_team_standings(CL_LEAGUE_ID, SEASON, PSG_ID)
        team_detail.get_team_standings(CL_LEAGUE_ID, SEASON, PSG_ID)

        assert calls == [(CL_LEAGUE_ID, SEASON)]

    def test_zwei_teams_derselben_liga_teilen_den_standings_cache(self, monkeypatch):
        calls = []
        monkeypatch.setattr(team_detail.apisports_api, "get_standings_table",
                            lambda lid, season: calls.append((lid, season)) or
                            make_raw_standings(league_id=lid, season=season, groups=[[
                                make_standings_row(team_id=PSG_ID, rank=11),
                                make_standings_row(team_id=ARSENAL_ID, rank=1),
                            ]]))

        psg_row = team_detail.get_team_standings(CL_LEAGUE_ID, SEASON, PSG_ID)
        arsenal_row = team_detail.get_team_standings(CL_LEAGUE_ID, SEASON, ARSENAL_ID)

        # Nur EIN Request fuer die komplette Tabelle, nicht einer je Team.
        assert calls == [(CL_LEAGUE_ID, SEASON)]
        assert psg_row["rank"] == 11
        assert arsenal_row["rank"] == 1

    def test_fixtures_getrennt_gecacht(self, monkeypatch):
        calls = []
        monkeypatch.setattr(team_detail.apisports_api, "get_team_fixtures",
                            lambda tid, last=None, next=None: calls.append((last, next)) or
                            [make_raw_fixture(home_id=tid, away_id=999)])

        team_detail.get_team_recent_fixtures(PSG_ID)
        team_detail.get_team_upcoming_fixtures(PSG_ID)

        assert (5, None) in calls
        assert (None, 5) in calls
        assert len(calls) == 2

    def test_kader_gecacht(self, monkeypatch):
        calls = []
        monkeypatch.setattr(team_detail.apisports_api, "get_team_squad",
                            lambda tid: calls.append(tid) or make_raw_squad(team_id=tid))

        team_detail.get_team_squad_list(PSG_ID)
        team_detail.get_team_squad_list(PSG_ID)

        assert calls == [PSG_ID]

    def test_trainer_gecacht(self, monkeypatch):
        calls = []
        monkeypatch.setattr(team_detail.apisports_api, "get_team_coach",
                            lambda tid: calls.append(tid) or make_raw_coach())

        team_detail.get_team_current_coach(PSG_ID)
        team_detail.get_team_current_coach(PSG_ID)

        assert calls == [PSG_ID]

    def test_zweiter_build_team_detail_aufruf_kostet_keine_requests(self, monkeypatch):
        calls = []
        self._patch_all(monkeypatch, calls)

        team_detail.build_team_detail(PSG_ID, league_id=CL_LEAGUE_ID, season=SEASON)
        first_call_count = len(calls)
        team_detail.build_team_detail(PSG_ID, league_id=CL_LEAGUE_ID, season=SEASON)

        assert first_call_count == 6   # info, standings, 2x fixtures, squad, coach
        assert len(calls) == 6         # zweiter Aufruf: keine weiteren

    def test_cache_liegt_auf_der_platte(self, monkeypatch):
        """Unter Gunicorn haette sonst jeder Worker seinen eigenen Stand."""
        calls = []
        self._patch_all(monkeypatch, calls)

        team_detail.build_team_detail(PSG_ID, league_id=CL_LEAGUE_ID, season=SEASON)

        files = list(self.tmp_path.glob("apisports__team_info__85*.json"))
        assert len(files) == 1

    def test_ein_ausfall_bei_nebenkategorie_blockiert_die_uebrigen_nicht(self, monkeypatch):
        """
        Squad-Ausfall (ohne Cache-Rest) darf Identitaet/Standings/
        Fixtures/Trainer nicht verhindern.
        """
        from src.api.apisports_api import ApisportsUnavailable

        monkeypatch.setattr(team_detail.apisports_api, "get_team_info",
                            lambda tid: make_raw_team_info(team_id=tid))
        monkeypatch.setattr(team_detail.apisports_api, "get_standings_table",
                            lambda lid, season: make_raw_standings(league_id=lid, season=season))
        monkeypatch.setattr(team_detail.apisports_api, "get_team_fixtures",
                            lambda tid, last=None, next=None: [make_raw_fixture(home_id=tid, away_id=999)])

        def boom(tid):
            raise ApisportsUnavailable("Kader nicht erreichbar")

        monkeypatch.setattr(team_detail.apisports_api, "get_team_squad", boom)
        monkeypatch.setattr(team_detail.apisports_api, "get_team_coach", lambda tid: make_raw_coach())

        detail = team_detail.build_team_detail(PSG_ID, league_id=CL_LEAGUE_ID, season=SEASON)

        assert detail is not None
        assert detail["team"]["name"] == "Paris Saint Germain"
        assert detail["standings"] is not None
        assert detail["squad"] == []
        assert detail["coach"]["name"] == "Luis Enrique"

    def test_ausfall_bei_der_identitaet_liefert_none(self, monkeypatch):
        """
        Ohne Identitaet gibt es nichts Sinnvolles anzuzeigen - das ist
        die einzige Kategorie, die NICHT weich abgefangen wird.
        """
        from src.api.apisports_api import ApisportsUnavailable

        def boom(tid):
            raise ApisportsUnavailable("weg")

        monkeypatch.setattr(team_detail.apisports_api, "get_team_info", boom)

        with pytest.raises(ApisportsUnavailable):
            team_detail.build_team_detail(PSG_ID)

    def test_ohne_league_season_bleibt_standings_none(self, monkeypatch):
        calls = []
        self._patch_all(monkeypatch, calls)

        detail = team_detail.build_team_detail(PSG_ID)

        assert detail["standings"] is None
        assert not any(c[0] == "standings" for c in calls)


# ===========================================================================
# C) HTTP-Route
# ===========================================================================

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APISPORTS_KEY", "test-key")
    monkeypatch.setenv("FOOTBALL_DATA_KEY", "test-key")

    import app as app_module
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def _patch_build(monkeypatch, result):
    import app as app_module
    monkeypatch.setattr(app_module.team_detail, "build_team_detail",
                        lambda team_id, league_id=None, season=None: result)


class TestRoute:
    def test_fehlende_team_id(self, client):
        assert client.get("/api/team-detail").status_code == 400

    def test_ungueltige_team_id(self, client):
        assert client.get("/api/team-detail?team_id=abc").status_code == 400

    def test_negative_team_id(self, client):
        assert client.get("/api/team-detail?team_id=-5").status_code == 400
        assert client.get("/api/team-detail?team_id=0").status_code == 400

    def test_unbekannte_team_id(self, client, monkeypatch):
        _patch_build(monkeypatch, None)
        response = client.get("/api/team-detail?team_id=999999")
        assert response.status_code == 404

    def test_gueltige_anfrage_ohne_liga_saison(self, client, monkeypatch):
        result = {
            "team": {"id": PSG_ID, "name": "Paris Saint Germain"},
            "standings": None, "recent_fixtures": [], "upcoming_fixtures": [],
            "squad": [], "coach": None,
        }
        _patch_build(monkeypatch, result)

        response = client.get(f"/api/team-detail?team_id={PSG_ID}")
        assert response.status_code == 200
        assert response.get_json()["team"]["name"] == "Paris Saint Germain"

    def test_league_id_und_season_werden_durchgereicht(self, client, monkeypatch):
        import app as app_module
        captured = {}

        def fake(team_id, league_id=None, season=None):
            captured["team_id"] = team_id
            captured["league_id"] = league_id
            captured["season"] = season
            return {"team": {"id": team_id, "name": "X"}, "standings": None,
                   "recent_fixtures": [], "upcoming_fixtures": [], "squad": [], "coach": None}

        monkeypatch.setattr(app_module.team_detail, "build_team_detail", fake)

        client.get(f"/api/team-detail?team_id={PSG_ID}&league_id={CL_LEAGUE_ID}&season={SEASON}")
        assert captured == {"team_id": PSG_ID, "league_id": CL_LEAGUE_ID, "season": SEASON}

    def test_garbled_league_id_faellt_auf_none_zurueck(self, client, monkeypatch):
        import app as app_module
        captured = {}

        def fake(team_id, league_id=None, season=None):
            captured["league_id"] = league_id
            return {"team": {"id": team_id, "name": "X"}, "standings": None,
                   "recent_fixtures": [], "upcoming_fixtures": [], "squad": [], "coach": None}

        monkeypatch.setattr(app_module.team_detail, "build_team_detail", fake)

        response = client.get(f"/api/team-detail?team_id={PSG_ID}&league_id=abc")
        assert response.status_code == 200
        assert captured["league_id"] is None

    def test_rate_limit(self, client, monkeypatch):
        import app as app_module
        from src.api.live_api import ApisportsRateLimit

        def boom(team_id, league_id=None, season=None):
            raise ApisportsRateLimit("Limit")

        monkeypatch.setattr(app_module.team_detail, "build_team_detail", boom)
        assert client.get(f"/api/team-detail?team_id={PSG_ID}").status_code == 429

    def test_provider_ausfall(self, client, monkeypatch):
        import app as app_module
        from src.api.live_api import ApisportsUnavailable

        def boom(team_id, league_id=None, season=None):
            raise ApisportsUnavailable("weg")

        monkeypatch.setattr(app_module.team_detail, "build_team_detail", boom)
        assert client.get(f"/api/team-detail?team_id={PSG_ID}").status_code == 503

    def test_antwort_verraet_keinen_schluessel(self, client, monkeypatch):
        result = {
            "team": {"id": PSG_ID, "name": "Paris Saint Germain"},
            "standings": None, "recent_fixtures": [], "upcoming_fixtures": [],
            "squad": [], "coach": None,
        }
        _patch_build(monkeypatch, result)

        body = client.get(f"/api/team-detail?team_id={PSG_ID}").get_data(as_text=True).lower()
        for verboten in ["x-rapidapi", "apisports_key", "v3.football.api-sports.io"]:
            assert verboten not in body


# ===========================================================================
# D) Architekturgrenzen
# ===========================================================================

class TestArchitektur:
    def test_kein_zweites_team_id_system(self):
        """
        Ausschliesslich API-Football-IDs. Kein Import von football_api.py
        oder league_api.py (beide football-data.org-basiert) - siehe auch
        TestKeinScopeUeberschuss.test_kein_team_statistics_und_kein_crosswalk
        in tests/test_live_block_c.py fuer die Crosswalk-Grenze im Detail.
        """
        source = _read("src", "api", "team_detail.py")
        import_lines = [
            line.strip() for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        for line in import_lines:
            assert "football_api" not in line
            assert "league_api" not in line

    def test_apisports_provider_funktionen_ohne_eigenen_cache(self):
        """
        Die rohen Endpunkt-Wrapper in apisports_api.py bleiben duenn -
        das Caching gehoert komplett in team_detail.py, wie beim
        bestehenden Match-Center-Muster (get_fixture_* dort ist ebenfalls
        ungecacht).
        """
        source = _read("src", "api", "apisports_api.py")
        start = source.index("def get_team_info(")
        end = source.index("def get_top_scorers(")
        block = source[start:end]

        assert "disk_cached_call" not in block
        assert "cached_call" not in block

    def test_standings_ttl_wiederverwendet(self):
        """TTL_STANDINGS existierte bereits (ungenutzt) in apisports_api.py."""
        source_api = _read("src", "api", "apisports_api.py")
        assert "TTL_STANDINGS = 60 * 60 * 2" in source_api

        source_team = _read("src", "api", "team_detail.py")
        assert "TTL_STANDINGS" in source_team
        # Keine zweite, womoeglich abweichende Standings-TTL.
        assert "TTL_TEAM_STANDINGS" not in source_team

    def test_getrennte_cache_kategorien_nicht_ein_kombinierter_eintrag(self):
        """
        Anders als get_match_center() (ein Eintrag fuer vier Endpunkte):
        hier bekommt jede Kategorie ihren eigenen disk_cached_call()-
        Aufruf. Gezaehlt werden nur echte Aufrufstellen ("= disk_cached_
        call("), nicht die Erwaehnungen in der Moduldoku.
        """
        source = _read("src", "api", "team_detail.py")
        assert source.count("= disk_cached_call(") == 6  # info, standings, 2x fixtures, squad, coach
