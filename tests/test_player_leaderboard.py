"""
Spieler-Bestenliste aus dem Pool und die Route /api/player-leaderboard (C24).

Synthetische Welt: eigene Ligapools, eigener Plattencache mit
Profilantworten, eigener NM-Import. Kein Anbieterabruf - jede
Anbieterfunktion scheitert sofort, wenn sie doch erreicht wird.
"""

import json

import pytest

from src.data import national_import
from src.data import player_pool
from src.data import uefa_coefficients as uc
from src.data.player_compare_loader import COMPETITION_SCOPES
from src.features import player_leaderboard as lb
from src.utils import cache, disk_cache

SEASON = 2025


def block(league_id=78, league_name="Bundesliga", team_id=157, team="FC Bayern München",
          minutes=900, apps=10, goals=2, assists=1, shots_on=5, key=6, tackles=4,
          interceptions=3, saves=None, conceded=None, rating="7.10", position="Attacker"):
    return {
        "team": {"id": team_id, "name": team,
                 "logo": f"https://media.api-sports.io/football/teams/{team_id}.png"},
        "league": {"id": league_id, "name": league_name, "type": "League", "season": SEASON},
        "games": {"appearences": apps, "lineups": apps, "minutes": minutes,
                  "position": position, "rating": rating},
        "goals": {"total": goals, "assists": assists, "saves": saves, "conceded": conceded},
        "shots": {"total": None if shots_on is None else shots_on + 3, "on": shots_on},
        "passes": {"total": 300, "key": key, "accuracy": 80},
        "tackles": {"total": tackles, "blocks": 1, "interceptions": interceptions},
        "duels": {"total": 50, "won": 25},
        "dribbles": {"attempts": 10, "success": 5},
        "fouls": {"drawn": 5, "committed": 5},
        "cards": {"yellow": 1, "red": 0},
        "penalty": {"saved": None},
    }


def raw(pid, name, *blocks):
    return [{"player": {"id": pid, "name": name}, "statistics": list(blocks)}]


def pool_entry(pid, name, position, league="bl1", minutes=900):
    return {"player_id": pid, "name": name, "position": position, "league_code": league,
            "team_name": "Alt", "team_id": 1,
            "minutes_by_scope": {"club_all": minutes, "league": minutes},
            "metrics_by_scope": {"club_all": {"goals_per90": 9.9}}}


@pytest.fixture
def welt(tmp_path, monkeypatch):
    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()
    monkeypatch.setattr(player_pool, "POOL_DIR", str(pool_dir))
    monkeypatch.setattr(player_pool, "STATUS_PATH", str(pool_dir / "status.json"))
    monkeypatch.setattr(player_pool, "MIN_PLAYERS_PER_LEAGUE", 1)
    monkeypatch.setattr(player_pool, "EXPECTED_TEAM_COUNT",
                        {"bl1": 1, "pl": 1, "pd": 1, "sa": 1, "fl1": 1})
    monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(national_import, "NATIONAL_DIR", str(tmp_path / "national"))
    national_import.clear_runtime_cache()
    cache.clear_all()

    # Big Games prueft den Zeitraum gegen die UEFA-Snapshots. Die echten
    # liegen gitignoriert unter data/big_games/ und fehlen auf einem
    # frischen Checkout (CI). Ohne eigenen Snapshot hinge jeder
    # Big-Games-Aufruf hier an privaten Dateien des Entwicklerrechners:
    # lokal gruen, in CI 400 statt 200.
    coeff_dir = tmp_path / "coeff"
    coeff_dir.mkdir()
    (coeff_dir / f"uefa_coefficients_{SEASON}_{str(SEASON + 1)[-2:]}.json").write_text(
        json.dumps({"season": uc.season_label(SEASON), "status": "complete",
                    "clubs": [{"rank": 1, "total_coefficient": 100.0,
                               "apisports_team_id": 157}]}),
        encoding="utf-8")
    monkeypatch.setattr(uc, "COEFFICIENT_DIR", str(coeff_dir))
    uc.clear_cache()

    netz = []

    def verboten(*args, **kwargs):
        netz.append(args)
        raise AssertionError("Anbieterabruf in der Bestenliste")

    from src.api import apisports_api
    from src.data import player_compare_loader as pcl
    monkeypatch.setattr(pcl, "_get", verboten)
    monkeypatch.setattr(apisports_api, "get_team_season_fixtures", verboten)
    monkeypatch.setattr(apisports_api, "get_fixture_players", verboten)

    def pool(league, entries, status="complete", season=SEASON):
        player_pool.write_pool({"league": league, "season": season,
                                "pages_done": [1], "players": entries})
        player_pool.update_pool_status(league, season, status=status)

    def profil(pid, name, *blocks, season=SEASON):
        disk_cache.write_entry(f"apisports:playerprofile:{pid}:{season}",
                               raw(pid, name, *blocks), 3600)

    yield {"pool": pool, "profil": profil, "netz": netz}
    cache.clear_all()
    national_import.clear_runtime_cache()
    uc.clear_cache()


@pytest.fixture
def standard(welt):
    """Fuenf Ligen, davon eine ohne Daten; ein Wechselspieler in zwei Pools."""
    welt["pool"]("bl1", [
        pool_entry(1, "Anton Angreifer", "Attacker"),
        pool_entry(2, "Bernd Blitz", "Attacker"),
        pool_entry(3, "Carl Kurz", "Attacker", minutes=200),
        pool_entry(4, "Dieter Dopp", "Attacker", minutes=1000),
        pool_entry(5, "Emil Ohneschuss", "Attacker"),
        pool_entry(6, "Tom Torwart", "Goalkeeper"),
        pool_entry(7, "Tim Torwart", "Goalkeeper"),
        pool_entry(8, "Zoe Gleich", "Attacker"),
        pool_entry(9, "Ada Gleich", "Attacker"),
    ])
    welt["pool"]("pl", [pool_entry(4, "Dieter Dopp", "Attacker", league="pl", minutes=300)])
    welt["pool"]("pd", [pool_entry(20, "Unvollstaendig", "Midfielder", league="pd")],
                 status="provider_incomplete")
    welt["pool"]("sa", [pool_entry(30, "Serie Mann", "Defender", league="sa")])
    # fl1 fehlt vollstaendig.

    p = welt["profil"]
    p(1, "Anton Angreifer", block(minutes=900, goals=5, assists=4))           # 0.9 G+A / 90
    p(2, "Bernd Blitz", block(minutes=1800, goals=6, assists=3))              # 0.45
    p(3, "Carl Kurz", block(minutes=200, goals=5))                            # unter 450
    # Wechselspieler: EIN Profil mit zwei Vereinsbloecken - nie doppelt gezaehlt.
    p(4, "Dieter Dopp",
      block(minutes=600, goals=2, assists=1),
      block(league_id=39, league_name="Premier League", team_id=50, team="Manchester City",
            minutes=300, goals=1, assists=0))                                  # 4 / 900 * 90 = 0.4
    p(5, "Emil Ohneschuss", block(minutes=900, goals=0, assists=0, shots_on=None))
    p(6, "Tom Torwart", block(minutes=900, goals=0, assists=0, saves=30, conceded=9,
                              position="Goalkeeper"))                          # 1.0 / 90
    p(7, "Tim Torwart", block(minutes=900, goals=0, assists=0, saves=20, conceded=4,
                              position="Goalkeeper"))                          # 0.4 / 90
    p(8, "Zoe Gleich", block(minutes=900, goals=1, assists=0))                # 0.1, gleiche Minuten
    p(9, "Ada Gleich", block(minutes=900, goals=1, assists=0))                # 0.1
    p(30, "Serie Mann", block(league_id=135, league_name="Serie A", team_id=489, team="AC Milan",
                              minutes=900, position="Defender"))
    # Spieler 20 hat kein lokales Profil.
    return welt


def run(season=SEASON, scope="club_all", position="Attacker",
        metric="goal_contributions_per90", limit=10):
    return lb.pool_leaderboard(season, scope, position, metric, limit, current_season=2026)


# ---------------------------------------------------------------------------
# Katalog
# ---------------------------------------------------------------------------

class TestKatalog:

    def test_kennzahlen_stammen_aus_dem_zentralen_katalog(self):
        from src.data.player_metrics import METRICS

        for position, keys in lb.LEADERBOARD_METRICS.items():
            assert keys, position
            for key in keys:
                assert key in METRICS, key

    def test_alle_positionen_nur_mit_anbieterbewertung(self):
        assert lb.LEADERBOARD_METRICS["all"] == ("rating",)
        assert lb.metric_meta("rating")["label"] == "Anbieterbewertung (API-Football)"

    def test_standardkennzahl_ist_die_erste(self):
        assert lb.default_metric("Attacker") == "goal_contributions_per90"
        assert lb.default_metric("Goalkeeper") == "saves_per90"
        assert lb.metric_meta("conceded_per90")["direction"] == "lower_better"

    def test_listenlaengen(self):
        assert lb.LEADERBOARD_LIMITS == (5, 10, 15, 20, 30)
        assert lb.DEFAULT_LIMIT == 10


# ---------------------------------------------------------------------------
# Pool-Bestenliste
# ---------------------------------------------------------------------------

class TestPool:

    def test_reihenfolge_und_werte_aus_dem_profil(self, standard):
        ergebnis = run()
        assert ergebnis["available"] is True
        namen = [r["name"] for r in ergebnis["rows"]]
        assert namen[:3] == ["Anton Angreifer", "Bernd Blitz", "Dieter Dopp"]
        # Werte kommen aus dem Profil, nicht aus dem Pool (dort stehen 9.9).
        assert ergebnis["rows"][0]["value"] == 0.9
        assert ergebnis["rows"][0]["team_name"] == "FC Bayern München"

    def test_wechselspieler_einmal_und_nicht_addiert(self, standard):
        ergebnis = run()
        dopp = [r for r in ergebnis["rows"] if r["player_id"] == 4]
        assert len(dopp) == 1
        assert dopp[0]["minutes"] == 900             # 600 + 300 aus EINEM Profil
        assert dopp[0]["value"] == 0.4
        assert ergebnis["coverage"]["duplicates_removed"] == 1

    def test_mindestminuten(self, standard):
        ergebnis = run()
        assert 3 not in [r["player_id"] for r in ergebnis["rows"]]
        assert ergebnis["coverage"]["excluded_min_minutes"] == 1
        assert ergebnis["eligibility"]["min_minutes"] == 450

    def test_fehlender_wert_ist_nicht_null(self, standard):
        mit = run(metric="shots_on_per90")
        assert 5 not in [r["player_id"] for r in mit["rows"]]
        assert mit["coverage"]["missing_metric"] == 1
        # Dieselbe Person mit echter Null bei G+A bleibt drin.
        ga = run()
        emil = [r for r in ga["rows"] if r["player_id"] == 5]
        assert emil and emil[0]["value"] == 0.0

    def test_gleichstand_deterministisch(self, standard):
        zeilen = [r for r in run()["rows"] if r["value"] == 0.1]
        # Gleicher Wert, gleiche Minuten: Name entscheidet (ohne Akzente).
        assert [r["name"] for r in zeilen] == ["Ada Gleich", "Zoe Gleich"]

    def test_gleichstand_vierte_stufe_player_id(self):
        zeilen = [{"player_id": 9, "name": "Gleich", "minutes": 900, "value": 1.0},
                  {"player_id": 3, "name": "Gleich", "minutes": 900, "value": 1.0},
                  {"player_id": 5, "name": "Gleich", "minutes": 1200, "value": 1.0}]
        geordnet = lb.rank_rows(zeilen, "higher_better", 10)
        assert [r["player_id"] for r in geordnet] == [5, 3, 9]
        assert [r["rank"] for r in geordnet] == [1, 2, 3]

    def test_niedriger_ist_besser(self, standard):
        ergebnis = run(position="Goalkeeper", metric="conceded_per90")
        assert [r["name"] for r in ergebnis["rows"]] == ["Tim Torwart", "Tom Torwart"]
        saves = run(position="Goalkeeper", metric="saves_per90")
        assert [r["name"] for r in saves["rows"]] == ["Tom Torwart", "Tim Torwart"]

    @pytest.mark.parametrize("limit", [5, 10, 15, 20, 30])
    def test_limit(self, standard, limit):
        ergebnis = run(position="all", metric="rating", limit=limit)
        assert len(ergebnis["rows"]) == min(limit, ergebnis["coverage"]["eligible"])

    def test_limit_schneidet_ab(self, standard):
        ergebnis = run(position="all", metric="rating", limit=5)
        assert len(ergebnis["rows"]) == 5
        assert ergebnis["coverage"]["eligible"] > 5

    def test_abdeckung_unvollstaendig_und_fehlend(self, standard):
        ergebnis = run()
        c = ergebnis["coverage"]
        assert c["missing_leagues"] == ["fl1"]
        assert set(c["incomplete_leagues"]) == {"pd", "fl1"}
        assert c["profile_not_cached"] == 1          # Spieler 20
        assert ergebnis["incomplete"] is True

    def test_vollstaendiger_pool(self, welt):
        for nummer, liga in enumerate(("bl1", "pl", "pd", "sa", "fl1"), start=100):
            welt["pool"](liga, [pool_entry(nummer, f"Spieler {liga}", "Attacker", league=liga)])
            welt["profil"](nummer, f"Spieler {liga}", block())
        ergebnis = run()
        assert ergebnis["incomplete"] is False
        assert ergebnis["coverage"]["missing_leagues"] == []
        assert ergebnis["coverage"]["duplicates_removed"] == 0
        assert ergebnis["coverage"]["eligible"] == 5

    def test_ohne_pool_nicht_verfuegbar(self, welt):
        ergebnis = run()
        assert (ergebnis["available"], ergebnis["reason"]) == (False, "no_pool_data")

    def test_laufende_saison_ist_vorlaeufig(self, welt):
        welt["pool"]("bl1", [pool_entry(1, "A", "Attacker")], season=2026)
        welt["profil"](1, "A", block(), season=2026)
        ergebnis = run(season=2026)
        assert ergebnis["provisional"] is True

    def test_kein_anbieterabruf(self, standard):
        for scope in COMPETITION_SCOPES:
            run(scope=scope, position="all", metric="rating")
        assert standard["netz"] == []


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@pytest.fixture
def client(standard):
    import app as app_module

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as verbindung:
        yield verbindung


def get(client, query):
    antwort = client.get("/api/player-leaderboard?" + query)
    return antwort.status_code, antwort.get_json()


class TestRoute:

    def test_gueltige_anfrage(self, client):
        status, daten = get(client, "scope=club_all&position=Attacker&season=2025&limit=5")
        assert status == 200
        for feld in ("available", "source", "position", "scope", "season", "metric",
                     "direction", "limit", "rows", "eligibility", "coverage",
                     "provisional", "incomplete", "allowed_metrics", "allowed_limits"):
            assert feld in daten, feld
        assert daten["source"] == "player_pool"
        assert daten["metric"]["key"] == "goal_contributions_per90"
        assert len(daten["rows"]) == 5
        assert daten["allowed_limits"] == [5, 10, 15, 20, 30]

    @pytest.mark.parametrize("scope", list(COMPETITION_SCOPES))
    def test_alle_vorhandenen_datenbasen(self, client, scope):
        status, daten = get(client, f"scope={scope}&season=2025")
        assert status == 200
        assert daten["scope"] == scope

    @pytest.mark.parametrize("query,schluessel", [
        ("scope=bogus&season=2025", "leaderboard.error.unknownScope"),
        ("scope=club_all&season=2025&position=Sturm", "leaderboard.error.unknownPosition"),
        ("scope=club_all&season=2025&position=Attacker&metric=saves_per90",
         "leaderboard.error.unknownMetric"),
        ("scope=club_all&season=2025&metric=erfunden", "leaderboard.error.unknownMetric"),
        ("scope=club_all&season=2025&limit=7", "leaderboard.error.invalidLimit"),
        ("scope=club_all&season=2025&limit=0", "leaderboard.error.invalidLimit"),
        ("scope=club_all&season=2025&limit=31", "leaderboard.error.invalidLimit"),
        ("scope=club_all&season=2025&limit=10.0", "leaderboard.error.invalidLimit"),
        ("scope=club_all&season=2025&limit=", "leaderboard.error.invalidLimit"),
        ("scope=club_all&season=2019", "leaderboard.error.invalidSeason"),
        ("scope=club_all&season=2999", "leaderboard.error.invalidSeason"),
        ("scope=club_all&season=abc", "leaderboard.error.invalidSeason"),
        ("scope=club_all", "leaderboard.error.invalidSeason"),
        ("scope=club_all&season=2025&foo=1", "leaderboard.error.unknownParameter"),
        ("scope=club_all&season=2025&season=2024", "leaderboard.error.duplicateParameter"),
        ("scope=club_all&season=2025&limit=5&limit=10", "leaderboard.error.duplicateParameter"),
        ("scope=club_all&season=2025&season_from=2025&season_to=2025",
         "leaderboard.error.invalidCombination"),
        ("scope=big_games&season=2025", "leaderboard.error.invalidCombination"),
        ("scope=big_games&season_from=2025", "leaderboard.error.invalidSeason"),
        ("scope=big_games&season_from=2026&season_to=2025", "leaderboard.error.invalidSeason"),
        ("scope=big_games&season_from=2010&season_to=2011", "leaderboard.error.invalidSeason"),
    ])
    def test_ungueltiges_wird_nicht_korrigiert(self, client, query, schluessel):
        status, daten = get(client, query)
        assert status == 400
        assert daten["error_key"] == schluessel

    def test_big_games_ohne_datensatz(self, client, tmp_path, monkeypatch):
        """
        Ohne jede Datengrundlage bleibt die Liste zu.

        GEAENDERT MIT V2: Es gibt zwei Quellen - den privaten, gesammelten
        Datensatz und das mitgelieferte oeffentliche Artefakt. "Kein
        Datensatz" heisst deshalb: BEIDE fehlen. Wird nur die erste
        Quelle weggenommen, uebernimmt zu Recht die zweite.
        """
        from src.data import big_games_dataset
        from src.data import big_games_public
        monkeypatch.setattr(big_games_dataset, "DATASET_DIR", str(tmp_path / "leer"))
        monkeypatch.setattr(big_games_public, "PUBLIC_DIR", str(tmp_path / "leer"))
        status, daten = get(client, "scope=big_games&position=Attacker&season_from=2025&season_to=2025")
        assert status == 200
        assert daten["available"] is False
        assert daten["reason"] == "dataset_missing"
        assert daten["rows"] == []
        assert daten["source"] == "big_games_dataset"

    def test_big_games_erzwingt_den_big_game_score(self, client, tmp_path, monkeypatch):
        from src.data import big_games_dataset
        monkeypatch.setattr(big_games_dataset, "DATASET_DIR", str(tmp_path / "leer"))
        status, daten = get(client, "scope=big_games&position=all&season_from=2025&season_to=2025")
        assert status == 200
        assert daten["metric"]["key"] == "big_game_score"
        assert daten["metric"]["label"] == "Big-Game-Score"
        assert [m["key"] for m in daten["allowed_metrics"]] == ["big_game_score"]
        assert "Anbieterbewertung" not in json.dumps(daten)

        status, _ = get(client, "scope=big_games&position=all&season_from=2025"
                                "&season_to=2025&metric=big_game_score")
        assert status == 200

    @pytest.mark.parametrize("metric", ["rating", "goal_contributions_per90", "saves_per90"])
    def test_big_games_nimmt_keine_normale_kennzahl(self, client, metric):
        status, daten = get(client, "scope=big_games&position=all&season_from=2025"
                                    f"&season_to=2025&metric={metric}")
        assert status == 400
        assert daten["error_key"] == "leaderboard.error.unknownMetric"
        assert daten["allowed_metrics"] == ["big_game_score"]

    def test_normale_datenbasis_kennt_keinen_big_game_score(self, client):
        status, daten = get(client, "scope=club_all&season=2025&metric=big_game_score")
        assert status == 400
        assert daten["error_key"] == "leaderboard.error.unknownMetric"

    def test_auswahlkatalog(self, client):
        antwort = client.get("/api/player-leaderboard-options")
        daten = antwort.get_json()
        assert antwort.status_code == 200
        assert daten["limits"] == [5, 10, 15, 20, 30] and daten["default_limit"] == 10
        assert [m["key"] for m in daten["positions"]["Attacker"]] == list(
            lb.LEADERBOARD_METRICS["Attacker"])
        assert daten["big_games"]["metric"]["key"] == "big_game_score"
        assert client.get("/api/player-leaderboard-options?x=1").status_code == 400

    def test_keine_internen_pfade_und_keine_rohdaten(self, client):
        status, daten = get(client, "scope=club_all&position=all&season=2025&limit=30")
        text = json.dumps(daten)
        assert status == 200
        # "player_pool" ist der Name der Quelle; als Pfad taucht er nie auf.
        for verboten in ("C:\\\\", "/data/", "\\\\data", "data/player_pool",
                         "\"statistics\"", "metrics_by_scope", "api_key", "secret",
                         "model_id", "registry", "clm-", "bundle"):
            assert verboten not in text, verboten

    def test_population_einmal_je_saison_und_nach_neustart_aus_der_platte(
            self, client, monkeypatch):
        from src.data import player_compare_loader as pcl

        durchlaeufe = []
        echt = lb.pool_populations
        monkeypatch.setattr(lb, "pool_populations",
                            lambda season, league_codes=None: durchlaeufe.append(season)
                            or echt(season, league_codes))
        gelesen = []
        echt_raw = pcl.cached_season_raw_enriched
        monkeypatch.setattr(pcl, "cached_season_raw_enriched",
                            lambda pid, season: gelesen.append(pid) or echt_raw(pid, season))

        for scope in ("club_all", "league", "cl", "all"):
            assert get(client, f"scope={scope}&season=2025")[0] == 200
        assert durchlaeufe == [2025]                  # alle Datenbasen in einem Lauf
        assert len(gelesen) == len(set(gelesen))      # jedes Profil genau einmal

        cache.clear_all()                             # wie ein Neustart
        assert get(client, "scope=club_all&season=2025&limit=5")[0] == 200
        assert durchlaeufe == [2025]                  # aus dem Plattencache

    def test_route_macht_keinen_anbieterabruf(self, client, standard):
        get(client, "scope=club_all&position=all&season=2025")
        get(client, "scope=cl&position=all&season=2025")
        assert standard["netz"] == []

    def test_vorlaeufig_und_unvollstaendig_in_der_antwort(self, client, standard):
        standard["pool"]("bl1", [pool_entry(1, "A", "Attacker")], season=2026)
        standard["profil"](1, "A", block(), season=2026)
        status, daten = get(client, "scope=club_all&season=2026")
        assert status == 200
        assert daten["provisional"] is True and daten["incomplete"] is True


class TestEinzelvergleichGleich:

    def test_listenwert_gleich_vergleichswert(self, standard):
        """Dieselbe Rechnung wie im Einzelvergleich (bei gleichem Rohdatenstand)."""
        from src.data.player_compare_loader import get_player_season_profile
        from src.data.player_metrics import compute_metric

        ergebnis = run()
        for zeile in ergebnis["rows"]:
            profil = get_player_season_profile(zeile["player_id"], SEASON, scope="club_all")
            assert zeile["minutes"] == profil["minutes"]
            assert zeile["value"] == compute_metric(
                "goal_contributions_per90", profil["stats"], profil["minutes"])
        assert standard["netz"] == []
