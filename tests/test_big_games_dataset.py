"""
Big-Games-Datensatz, Sammler und Bestenliste (Block C24).

Alle Tests arbeiten in einer synthetischen Welt: eigener Plattencache,
eigener UEFA-Snapshot, eigenes Datensatzverzeichnis. Jede Anbieterfunktion
ist durch einen Zaehler ersetzt, der bei einem unerwarteten Aufruf sofort
scheitert. Es gibt keinen Netzzugriff.

Zentral: Bestenliste und Einzelvergleich muessen fuer denselben Spieler
ueber dieselben Spiele dieselben Werte liefern.
"""

import json
import os
import time

import pytest

from src.api.apisports_api import ApisportsRateLimit, ApisportsUnavailable
from src.data import big_games_collector as collector
from src.data import big_games_dataset as dataset
from src.data import big_games_loader as bgl
from src.data import fifa_rankings
from src.data import national_big_games_loader as nbgl
from src.data import uefa_coefficients as uc
from src.features import big_games as bg
from src.utils import disk_cache

SEASON = 2021
TEAM = 33
LEAGUE = 39
ELITE = 40          # Rang 2
TOP = 157           # Rang 1
RANK30 = 168        # Rang 30, gerade noch zugelassen
RANK31 = 487        # Rang 31, nicht zugelassen

STAR = 874          # Stuermer, drei Big Games
DEF = 875           # Verteidiger, nur zwei Big Games
NOSHOTS = 876       # Stuermer ohne Schussdaten
NORATE = 877        # Stuermer mit drei Big Games, aber ohne jede Bewertung


# ---------------------------------------------------------------------------
# Synthetische Welt
# ---------------------------------------------------------------------------

def _fifa_snapshot(jahr):
    """Gueltiger synthetischer FIFA-Top-20-Snapshot (Aufbau wie in
    tests/test_fifa_rankings.py, dort gegen den Parser geprueft)."""
    return {
        "year": jahr,
        "snapshot_date": f"{jahr}-12-22",
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
            {"rank": rang, "team_name": f"Team {rang}", "team_name_en": f"Team {rang}",
             "points": 2000.0 - rang, "apisports_team_id": 1000 + rang,
             "apisports_resolution_confidence": "high",
             "apisports_resolution_method": "exact test identity"}
            for rang in range(1, 21)
        ],
    }


@pytest.fixture
def welt(tmp_path, monkeypatch):
    monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(dataset, "DATASET_DIR", str(tmp_path / "leaderboard"))

    coeff_dir = tmp_path / "coeff"
    coeff_dir.mkdir()
    (coeff_dir / "uefa_coefficients_2021_22.json").write_text(json.dumps({
        "season": "2021/22", "status": "complete",
        "clubs": [
            {"rank": 1, "total_coefficient": 138.0, "apisports_team_id": TOP},
            {"rank": 2, "total_coefficient": 134.0, "apisports_team_id": ELITE},
            {"rank": 30, "total_coefficient": 53.0, "apisports_team_id": RANK30},
            {"rank": 31, "total_coefficient": 53.0, "apisports_team_id": RANK31},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(uc, "COEFFICIENT_DIR", str(coeff_dir))
    uc.clear_cache()

    # Ein Nationalspiel bindet den FIFA-Snapshot seines Spieljahres. Die
    # echten liegen wie die UEFA-Snapshots gitignoriert unter
    # data/big_games/ und fehlen auf einem frischen Checkout (CI); der
    # Datensatz faellt dann zu Recht fail-closed aus. Die Welt bringt
    # deshalb eigene mit - fuer beide Kalenderjahre der Saison.
    fifa_dir = tmp_path / "fifa"
    fifa_dir.mkdir()
    for jahr in (SEASON, SEASON + 1):
        (fifa_dir / f"fifa_rankings_{jahr}.json").write_text(
            json.dumps(_fifa_snapshot(jahr)), encoding="utf-8")
    monkeypatch.setattr(fifa_rankings, "FIFA_RANKING_DIR", str(fifa_dir))
    fifa_rankings.clear_cache()

    # Nationalspiele nur dort, wo ein Test sie ausdruecklich will.
    monkeypatch.setattr(nbgl, "national_targets_for_footsim_season", lambda season: [])

    calls = {"fixtures": [], "players": [], "profile": [], "team": []}

    def verboten(name):
        def _stub(*args, **kwargs):
            calls[name].append(args)
            raise AssertionError(f"unerwarteter Anbieterabruf: {name} {args}")
        return _stub

    monkeypatch.setattr(bgl.apisports_api, "get_team_season_fixtures", verboten("fixtures"))
    monkeypatch.setattr(bgl.apisports_api, "get_fixture_players", verboten("players"))
    monkeypatch.setattr(bgl.apisports_api, "get_team_info", verboten("team"))
    from src.data import player_compare_loader as pcl
    monkeypatch.setattr(pcl, "_get", verboten("profile"))

    population = {
        STAR: {"player_id": STAR, "name": "Star Stürmer", "position": "Attacker",
               "league_code": "pl", "team_name": "Eigenes Team", "team_id": TEAM},
        DEF: {"player_id": DEF, "name": "Abwehr Mann", "position": "Defender",
              "league_code": "pl", "team_name": "Eigenes Team", "team_id": TEAM},
        NOSHOTS: {"player_id": NOSHOTS, "name": "Ohne Schuss", "position": "Attacker",
                  "league_code": "pl", "team_name": "Eigenes Team", "team_id": TEAM},
        NORATE: {"player_id": NORATE, "name": "Ohne Note", "position": "Attacker",
                 "league_code": "pl", "team_name": "Eigenes Team", "team_id": TEAM},
    }
    monkeypatch.setattr(collector, "season_population",
                        lambda season, league_codes=None: (dict(population), ["pl"], 0))
    yield {"calls": calls, "population": population, "tmp": tmp_path}
    uc.clear_cache()
    fifa_rankings.clear_cache()


def fixture(fid, opponent, league=LEAGUE, date=None, round_name="Regular Season - 1"):
    return {
        "fixture": {"id": fid, "date": date or f"2021-10-{10 + fid % 20:02d}T15:00:00+00:00",
                    "status": {"short": "FT"}},
        "league": {"id": league, "name": "Premier League", "round": round_name, "season": SEASON},
        "teams": {"home": {"id": TEAM, "name": "Eigenes Team",
                           "logo": "https://media.api-sports.io/football/teams/33.png"},
                  "away": {"id": opponent, "name": f"Gegner {opponent}"}},
    }


def line(pid, minutes=90, goals=0, assists=0, shots_on=1, key=1, tackles=1,
         rating="7.0", position="F"):
    return {"player": {"id": pid},
            "statistics": [{"games": {"minutes": minutes, "rating": rating, "position": position},
                            "goals": {"total": goals, "assists": assists,
                                      "saves": None, "conceded": None},
                            "shots": {"total": None if shots_on is None else shots_on + 1,
                                      "on": shots_on},
                            "passes": {"total": 30, "key": key},
                            "tackles": {"total": tackles, "interceptions": 1},
                            "duels": {"total": 10, "won": 6},
                            "dribbles": {"attempts": 2, "success": 1}}]}


def profil(pid, extra_blocks=()):
    return [{"player": {"id": pid, "name": f"Spieler {pid}"},
             "statistics": [{"team": {"id": TEAM, "name": "Eigenes Team",
                                      "logo": "https://media.api-sports.io/football/teams/33.png"},
                             "league": {"id": LEAGUE, "name": "Premier League"},
                             "games": {"minutes": 2000}}, *extra_blocks]}]


def befuellen(fixture_players=True, skip_players=()):
    """Alles, was der Einzelvergleich braucht, liegt lokal im Cache."""
    ttl = 3600 * 24
    friendly_block = {"team": {"id": TEAM, "name": "Eigenes Team"},
                      "league": {"id": 667, "name": "Friendlies Clubs"},
                      "games": {"minutes": 90}}
    for pid in (STAR, DEF, NOSHOTS, NORATE):
        disk_cache.write_entry(f"apisports:playerprofile:{pid}:{SEASON}",
                               profil(pid, [friendly_block]), ttl)
    disk_cache.write_entry(
        f"apisports:team_season_fixtures:{TEAM}:{LEAGUE}:{SEASON}",
        [fixture(1, ELITE), fixture(2, RANK30), fixture(3, TOP), fixture(4, RANK31)], ttl)
    # Noten bewusst so, dass Durchschnittsnote und Big-Game-Score
    # UNTERSCHIEDLICH ordnen: STAR spielt gegen die starken Gegner (1, 3)
    # gut und gegen den schwachen (2) schwach, NOSHOTS umgekehrt.
    spieler = {
        1: [line(STAR, goals=1, assists=1, rating="8.0"), line(DEF, position="D"),
            line(NOSHOTS, shots_on=None, rating="6.0"), line(NORATE, rating=None)],
        2: [line(STAR, goals=1, rating="5.0"), line(DEF, position="D"),
            line(NOSHOTS, shots_on=None, rating="9.0"), line(NORATE, rating=None)],
        3: [line(STAR, minutes=45, assists=1, rating="8.0"),
            line(NOSHOTS, shots_on=None, rating="6.0"), line(NORATE, rating=None)],
        4: [line(STAR, goals=3)],   # Rang 31: kein Big Game, darf nie zaehlen
    }
    if fixture_players:
        for fid, lines in spieler.items():
            if fid in skip_players:
                continue
            disk_cache.write_entry(f"apisports:fixture_players:{fid}",
                                   [{"team": {"id": TEAM}, "players": lines}], ttl)


# ---------------------------------------------------------------------------
# Sammler: Trockenlauf, Budget, Checkpoint, Lock
# ---------------------------------------------------------------------------

class TestTrockenlauf:

    def test_ohne_netz_und_ohne_schreiben(self, welt):
        befuellen(skip_players=(3,))
        bericht = collector.run(SEASON)
        assert bericht["mode"] == "dry_run"
        assert bericht["network_requests_allowed"] is False
        assert bericht["requests_used"] == 0
        assert all(not v for v in welt["calls"].values())
        m = bericht["measured"]
        # Spiel 3 ist ein Big Game des Vereins. Ob ein Spieler dabei war,
        # zeigen erst dessen Einzelspielerwerte - alle drei Spieler brauchen
        # sie also. Geplant ist trotzdem genau EIN Abruf (Deduplizierung).
        assert m["missing_keys_by_kind"] == {"club_fixture_players": 1}
        assert m["players_complete_from_local_data"] == 0
        assert m["players_needing_data"] == 4
        assert not os.path.exists(dataset.DATASET_DIR)

    def test_friendlies_loesen_keine_spielplansuche_aus(self, welt):
        befuellen()
        bericht = collector.run(SEASON)
        zugriffe = bericht["measured"]["cache_by_kind"]["club_team_fixtures"]
        assert zugriffe["accessed"] == 1        # nur Liga 39, nie Liga 667
        assert bericht["measured"]["missing_keys_total"] == 0

    def test_abgelaufene_eintraege_werden_benutzt_nicht_neu_geladen(self, welt, monkeypatch):
        befuellen()
        # Alles als abgelaufen markieren: Die Werte einer abgeschlossenen
        # Saison aendern sich nicht mehr, ein Neuladen kostete nur Budget.
        monkeypatch.setattr(disk_cache, "is_fresh", lambda entry: False)
        bericht = collector.run(SEASON, execute=True, max_provider_requests=5)
        assert bericht["requests_used"] == 0
        assert bericht["measured"]["stale_entries_used"] > 0
        assert bericht["dataset_written"] is True
        assert all(not v for v in welt["calls"].values())


class TestAusfuehrungsschutz:

    @pytest.mark.parametrize("budget", [None, 0, -1, 501, True, "10"])
    def test_ausfuehrung_ohne_gueltiges_budget_bricht_vor_jedem_abruf_ab(self, welt, budget):
        with pytest.raises(collector.CollectorError):
            collector.run(SEASON, execute=True, max_provider_requests=budget)
        assert all(not v for v in welt["calls"].values())
        assert not os.path.exists(dataset.lock_path())

    def test_harte_obergrenze(self):
        assert collector.MAX_REQUESTS_PER_RUN == 500

    def test_takt_bleibt_unter_dem_minutenlimit_des_anbieters(self):
        """
        Der Anbieter nennt sein Minutenlimit im Antwortkopf (300 im
        Pro-Tarif). Ohne Taktung feuerte ein 500er-Lauf gemessen rund 400
        Abrufe je Minute und bekam 176 davon als HTTP 429 zurueck.
        """
        assert collector.MAX_REQUESTS_PER_MINUTE < 300

        jetzt = [0.0]
        geschlafen = []

        def uhr():
            return jetzt[0]

        def schlafen(dauer):
            geschlafen.append(dauer)
            jetzt[0] += dauer

        anzahl = collector.MAX_REQUESTS_PER_MINUTE + 25
        tor = collector.RequestGate(execute=True, max_requests=anzahl,
                                    sleep=schlafen, clock=uhr)
        starts = []

        def abruf():
            starts.append(jetzt[0])     # Zeitpunkt des tatsaechlichen Abrufs
            jetzt[0] += 0.05            # ein Abruf dauert 50 ms
            return True

        for nummer in range(anzahl):
            tor(f"apisports:playerprofile:{nummer}", "test", False, abruf)()

        assert geschlafen, "ohne Wartezeit wird das Minutenlimit gerissen"
        assert len(starts) == anzahl
        # In keinem Zeitfenster von 60 s starten mehr Abrufe als erlaubt.
        # Dieselbe Klammerung wie im Takt selbst, damit die Pruefung nicht
        # an einem Rundungsrest scheitert statt an einem echten Verstoss.
        for index, start in enumerate(starts):
            im_fenster = sum(1 for anderer in starts
                             if anderer <= start
                             and start - anderer < collector.RATE_WINDOW_SECONDS)
            assert im_fenster <= collector.MAX_REQUESTS_PER_MINUTE, index

    def test_taktung_nur_fuer_echte_abrufe(self):
        """Vorhandene Cacheeintraege kosten keine Wartezeit."""
        geschlafen = []
        tor = collector.RequestGate(execute=True, max_requests=5,
                                    sleep=lambda d: geschlafen.append(d))
        for nummer in range(50):
            with pytest.raises(collector._CachedEntryPreferred):
                tor(f"apisports:playerprofile:{nummer}", "test", True, lambda: None)
        assert geschlafen == []
        assert tor.used == 0

    def test_minutenlimit_beendet_den_lauf_und_erhaelt_den_checkpoint(
            self, welt, monkeypatch):
        """HTTP 429 wird nicht nachgesetzt: Der Lauf endet sofort sauber."""
        befuellen(skip_players=(1, 2, 3))
        versuche = []

        def limit(fid):
            versuche.append(fid)
            raise ApisportsRateLimit("API-Sports Rate Limit erreicht (HTTP 429)")

        monkeypatch.setattr(bgl.apisports_api, "get_fixture_players", limit)
        bericht = collector.run(SEASON, execute=True, max_provider_requests=50)

        assert bericht["rate_limited"] is True
        assert bericht["measured"]["requests_rate_limited"] == 1
        assert len(versuche) == 1, "nach dem Limit wird nichts mehr abgerufen"
        assert bericht["requests_used"] == 1
        assert bericht["dataset_written"] is False
        punkt = dataset.read_json(dataset.checkpoint_path(SEASON))
        assert punkt["status"] == dataset.STATUS_INCOMPLETE
        assert not os.path.exists(dataset.dataset_path(SEASON))
        assert not os.path.exists(dataset.lock_path())

        # Fortsetzen nach dem Limit: Der naechste Lauf holt dieselbe Fixture.
        geholt = []

        def wieder_da(fid):
            geholt.append(fid)
            return [{"team": {"id": TEAM},
                     "players": [line(STAR), line(DEF, position="D"),
                                 line(NOSHOTS, shots_on=None)]}]

        monkeypatch.setattr(bgl.apisports_api, "get_fixture_players", wieder_da)
        bericht = collector.run(SEASON, execute=True, max_provider_requests=50)
        assert bericht["rate_limited"] is False
        assert sorted(geholt) == [1, 2, 3]
        assert bericht["dataset_written"] is True

    def test_budget_wird_eingehalten_und_checkpoint_gespeichert(self, welt, monkeypatch):
        befuellen(skip_players=(1, 2, 3))
        geholt = []

        def players(fid):
            geholt.append(fid)
            return [{"team": {"id": TEAM}, "players": [line(STAR), line(DEF, position="D"),
                                                         line(NOSHOTS, shots_on=None)]}]

        monkeypatch.setattr(bgl.apisports_api, "get_fixture_players", players)
        bericht = collector.run(SEASON, execute=True, max_provider_requests=1)
        assert bericht["requests_used"] == 1 and len(geholt) == 1
        assert bericht["budget_exhausted"] is True
        assert bericht["dataset_written"] is False
        punkt = dataset.read_json(dataset.checkpoint_path(SEASON))
        assert punkt["status"] == dataset.STATUS_INCOMPLETE
        assert punkt["requests_used_total"] == 1
        assert not os.path.exists(dataset.dataset_path(SEASON))

        # Fortsetzen: Das bereits geholte Spiel wird nicht erneut geladen.
        bericht = collector.run(SEASON, execute=True, max_provider_requests=10)
        assert sorted(geholt) == [1, 2, 3]
        assert len(geholt) == len(set(geholt))
        assert bericht["dataset_written"] is True
        punkt = dataset.read_json(dataset.checkpoint_path(SEASON))
        assert punkt["status"] == dataset.STATUS_COMPLETE
        assert punkt["requests_used_total"] == 3

    def test_fehlerhafte_antwort_ist_nicht_vollstaendig(self, welt, monkeypatch):
        befuellen(skip_players=(3,))

        def kaputt(fid):
            raise ApisportsUnavailable("Timeout")

        monkeypatch.setattr(bgl.apisports_api, "get_fixture_players", kaputt)
        bericht = collector.run(SEASON, execute=True, max_provider_requests=10)
        assert bericht["measured"]["requests_failed"] == 1
        assert bericht["requests_used"] == 1          # derselbe Fehler nicht dreimal
        assert bericht["dataset_written"] is False
        punkt = dataset.read_json(dataset.checkpoint_path(SEASON))
        # Spiel 3 ist ein Big Game des Vereins aller drei Spieler: Ohne
        # seine Einzelspielerwerte ist keiner von ihnen vollstaendig.
        assert punkt["players_done"] == {}
        assert punkt["status"] == dataset.STATUS_INCOMPLETE

        # Der Anbieter antwortet wieder: Der naechste Lauf holt nur Spiel 3.
        geholt = []

        def wieder_da(fid):
            geholt.append(fid)
            return [{"team": {"id": TEAM}, "players": [line(STAR), line(NOSHOTS, shots_on=None)]}]

        monkeypatch.setattr(bgl.apisports_api, "get_fixture_players", wieder_da)
        bericht = collector.run(SEASON, execute=True, max_provider_requests=10)
        assert geholt == [3]
        assert bericht["dataset_written"] is True

    def test_lock_verhindert_parallele_sammler(self, welt):
        os.makedirs(dataset.DATASET_DIR, exist_ok=True)
        with open(dataset.lock_path(), "w", encoding="utf-8") as handle:
            json.dump({"pid": 1, "created_ts": time.time()}, handle)
        with pytest.raises(collector.CollectorLocked):
            collector.run(SEASON, execute=True, max_provider_requests=5)
        assert all(not v for v in welt["calls"].values())

    def test_verwaister_lock_wird_uebernommen(self, welt):
        befuellen()
        os.makedirs(dataset.DATASET_DIR, exist_ok=True)
        with open(dataset.lock_path(), "w", encoding="utf-8") as handle:
            json.dump({"pid": 1, "created_ts": time.time() - collector.LOCK_STALE_SECONDS - 5},
                      handle)
        bericht = collector.run(SEASON, execute=True, max_provider_requests=5)
        assert bericht["dataset_written"] is True
        assert not os.path.exists(dataset.lock_path())


# ---------------------------------------------------------------------------
# Datensatz und Bestenliste
# ---------------------------------------------------------------------------

@pytest.fixture
def fertig(welt):
    befuellen()
    bericht = collector.run(SEASON, execute=True, max_provider_requests=5)
    assert bericht["dataset_written"] is True and bericht["requests_used"] == 0
    return dataset.read_json(dataset.dataset_path(SEASON))


def _zeile(document, pid):
    return next(r for r in document["players"] if r["player_id"] == pid)


class TestDatensatz:

    def test_schema(self, fertig):
        for feld in ("schema_version", "contract_version", "season", "status",
                     "provisional", "created_at", "eligibility", "snapshots",
                     "population", "collector", "players"):
            assert feld in fertig, feld
        assert fertig["status"] == dataset.STATUS_COMPLETE
        assert fertig["eligibility"] == {"min_matches": bg.MIN_BIG_GAMES,
                                         "min_minutes": bg.MIN_BIG_GAME_MINUTES}
        star = _zeile(fertig, STAR)
        for feld in ("player_id", "name", "position", "team_name", "fixture_ids",
                     "big_games", "minutes", "raw_totals", "metrics", "rating",
                     "missing", "sufficient_sample", "matches"):
            assert feld in star, feld

    def test_historischer_snapshot_und_rang_31(self, fertig):
        star = _zeile(fertig, STAR)
        assert star["fixture_ids"] == [1, 2, 3]       # Spiel 4 (Rang 31) fehlt zu Recht
        assert star["big_games"] == 3 and star["minutes"] == 225

    def test_keine_privaten_rangdaten_im_datensatz(self, fertig):
        text = json.dumps(fertig)
        for verboten in ("opponent_rank", "opponent_coefficient", "total_coefficient"):
            assert verboten not in text
        assert len(fertig["snapshots"]["uefa"]) == 16

    def test_fehlendes_bleibt_fehlend(self, fertig):
        ohne = _zeile(fertig, NOSHOTS)
        assert ohne["raw_totals"]["shots_on"] is None
        assert ohne["metrics"]["shots_on_per90"] is None
        assert ohne["missing"]["shots_on"] == 3

    def test_unvollstaendiger_datensatz_ist_nicht_verfuegbar(self, welt):
        dataset.write_json_atomic(dataset.dataset_path(SEASON), {
            "schema_version": dataset.DATASET_SCHEMA_VERSION,
            "contract_version": dataset.DATASET_CONTRACT_VERSION,
            "season": SEASON, "status": dataset.STATUS_INCOMPLETE, "players": []})
        ergebnis = dataset.big_games_leaderboard(SEASON, SEASON, "all", 10)
        assert ergebnis["available"] is False
        assert ergebnis["reason"] == dataset.REASON_DATASET_INCOMPLETE
        assert ergebnis["rows"] == []
        with pytest.raises(ValueError):
            dataset.write_dataset({"season": SEASON, "status": dataset.STATUS_INCOMPLETE})

    def test_ohne_datensatz_keine_liste(self, welt):
        befuellen()
        collector.run(SEASON)                         # nur Trockenlauf
        ergebnis = dataset.big_games_leaderboard(SEASON, SEASON, "all", 10)
        assert (ergebnis["available"], ergebnis["reason"]) == (False, "dataset_missing")
        assert ergebnis["coverage"]["seasons"][0]["dataset_status"] == "missing"

    def test_zeile_traegt_den_bestehenden_score(self, fertig):
        star = _zeile(fertig, STAR)
        profil_ = bgl.build_big_games_profile(STAR, SEASON, SEASON)
        assert star["big_game_score"] == profil_["summary"]["big_game_score"]
        assert _zeile(fertig, DEF)["big_game_score"] is None       # zu wenige Spiele
        assert _zeile(fertig, NORATE)["big_game_score"] is None    # keine Bewertung


class TestBestenliste:

    def test_rangfolge_ist_der_big_game_score(self, fertig):
        ergebnis = dataset.big_games_leaderboard(SEASON, SEASON, "all", 10)
        assert ergebnis["ranking_key"] == "big_game_score"
        zeilen = {r["player_id"]: r for r in ergebnis["rows"]}
        star, ohne = _zeile(fertig, STAR), _zeile(fertig, NOSHOTS)
        # Durchschnittsnote und Score ordnen hier bewusst verschieden.
        assert ohne["rating"] > star["rating"]
        assert star["big_game_score"] > ohne["big_game_score"]
        assert [r["player_id"] for r in ergebnis["rows"]] == [STAR, NOSHOTS]
        assert zeilen[STAR]["value"] == star["big_game_score"]
        assert zeilen[STAR]["value"] != star["rating"]

    def test_score_stammt_aus_aggregate_big_games(self, fertig, monkeypatch):
        """Keine eigene Formel: Die Liste liest den Score der Aggregation."""
        echt = bg.aggregate_big_games
        aufrufe = []

        def markiert(entries):
            ergebnis = echt(entries)
            aufrufe.append(1)
            if ergebnis["big_game_score"] is not None:
                ergebnis["big_game_score"] = 111.11
            return ergebnis

        monkeypatch.setattr(bg, "aggregate_big_games", markiert)
        ergebnis = dataset.big_games_leaderboard(SEASON, SEASON, "all", 10)
        assert aufrufe
        assert {r["value"] for r in ergebnis["rows"]} == {111.11}

    def test_mindestmenge_ist_der_bestehende_vertrag(self, fertig):
        assert (bg.MIN_BIG_GAMES, bg.MIN_BIG_GAME_MINUTES) == (3, 180)
        ergebnis = dataset.big_games_leaderboard(SEASON, SEASON, "all", 10)
        ids = [r["player_id"] for r in ergebnis["rows"]]
        assert DEF not in ids                         # zwei Big Games: kein Score
        assert ergebnis["coverage"]["excluded_min_sample"] == 1
        assert ergebnis["eligibility"]["min_matches"] == 3
        assert ergebnis["eligibility"]["min_minutes"] == 180

    def test_fehlender_score_wird_nicht_zu_null(self, fertig):
        ergebnis = dataset.big_games_leaderboard(SEASON, SEASON, "Attacker", 10)
        assert NORATE not in [r["player_id"] for r in ergebnis["rows"]]
        assert ergebnis["coverage"]["without_score"] == 1

    def test_position_filtert_nur_die_population(self, fertig):
        alle = dataset.big_games_leaderboard(SEASON, SEASON, "all", 10)
        sturm = dataset.big_games_leaderboard(SEASON, SEASON, "Attacker", 10)
        abwehr = dataset.big_games_leaderboard(SEASON, SEASON, "Defender", 10)
        assert [r["value"] for r in sturm["rows"]] == [r["value"] for r in alle["rows"]]
        assert abwehr["available"] is False and abwehr["reason"] == "no_eligible_players"

    def test_keine_privaten_rangdaten_in_der_antwort(self, fertig):
        ergebnis = dataset.big_games_leaderboard(SEASON, SEASON, "all", 10)
        text = json.dumps(ergebnis)
        for verboten in ("opponent_rank", "coefficient", "weight", "strength",
                         '"matches":', '"raw_totals"', '"fixture_ids"', "snapshots"):
            assert verboten not in text, verboten

    def test_liste_gleich_einzelvergleich(self, fertig):
        """Das zentrale C24-Gate: dieselben Spiele, derselbe Big-Game-Score."""
        profil_ = bgl.build_big_games_profile(STAR, SEASON, SEASON)
        summary = profil_["summary"]
        zeile = _zeile(fertig, STAR)

        assert sorted(m["fixture_id"] for m in profil_["matches"]) == zeile["fixture_ids"]
        assert zeile["raw_totals"] == summary["raw"]
        assert zeile["rating"] == summary["avg_rating"]
        assert zeile["sufficient_sample"] == summary["sufficient_sample"]
        assert zeile["position"] == profil_["position"]

        liste = dataset.big_games_leaderboard(SEASON, SEASON, "Attacker", 10)
        eintrag = next(r for r in liste["rows"] if r["player_id"] == STAR)
        assert eintrag["value"] == summary["big_game_score"]
        assert eintrag["minutes"] == summary["raw"]["minutes"]
        assert eintrag["appearances"] == summary["raw"]["matches"]

    def test_club_und_national_ueber_dieselbe_deduplizierung(self, welt, monkeypatch):
        """Ein Nationalspiel zaehlt mit; eine doppelte Fixture nur einmal."""
        befuellen()

        def national(player_id, season):
            if player_id != STAR:
                return {"season": season, "available": True, "reason": None,
                        "provisional": False, "matches": [],
                        "unavailable_targets": [], "unavailable_ranking_years": []}
            nationalspiel = {"fixture_id": 900, "date": "2021-11-12T19:45:00+00:00",
                             "source": "national", "minutes": 90, "rating": 8.0,
                             "goals": 2, "assists": 0, "weight": 1.08, "strength": 1.08,
                             "position": "Attacker"}
            doppelt = {"fixture_id": 1, "date": "2021-10-11T15:00:00+00:00",
                       "source": "national", "minutes": 90, "rating": 1.0, "goals": 9}
            return {"season": season, "available": True, "reason": None,
                    "provisional": False, "matches": [nationalspiel, doppelt],
                    "unavailable_targets": [], "unavailable_ranking_years": []}

        monkeypatch.setattr(nbgl, "_season_result", national)
        collector.run(SEASON, execute=True, max_provider_requests=5)
        document = dataset.read_json(dataset.dataset_path(SEASON))
        zeile = _zeile(document, STAR)
        assert zeile["fixture_ids"] == [1, 2, 3, 900]
        assert zeile["big_games"] == 4

        profil_ = bgl.build_big_games_profile(STAR, SEASON, SEASON)
        assert zeile["raw_totals"] == profil_["summary"]["raw"]
        liste = dataset.big_games_leaderboard(SEASON, SEASON, "all", 10)
        eintrag = next(r for r in liste["rows"] if r["player_id"] == STAR)
        assert eintrag["value"] == profil_["summary"]["big_game_score"]

    def test_deterministische_reihenfolge_und_limit(self, fertig):
        a = dataset.big_games_leaderboard(SEASON, SEASON, "all", 5)
        b = dataset.big_games_leaderboard(SEASON, SEASON, "all", 5)
        assert a["rows"] == b["rows"]
        assert [r["rank"] for r in a["rows"]] == list(range(1, len(a["rows"]) + 1))
        eins = dataset.big_games_leaderboard(SEASON, SEASON, "all", 1)
        assert len(eins["rows"]) == 1

    def test_zeitraum_ueber_zwei_saisons_braucht_beide(self, fertig):
        ergebnis = dataset.big_games_leaderboard(SEASON, SEASON + 1, "all", 10)
        assert ergebnis["available"] is False
        assert ergebnis["reason"] == dataset.REASON_DATASET_MISSING


# ---------------------------------------------------------------------------
# Historische Snapshots sind die einzige Rangquelle
# ---------------------------------------------------------------------------

class TestSnapshots:

    def test_verein_nutzt_den_uefa_snapshot_genau_dieser_saison(self, welt, monkeypatch):
        befuellen()
        saisons = []
        echt_lookup, echt_load = uc.lookup_team, uc.load_snapshot
        monkeypatch.setattr(uc, "lookup_team",
                            lambda season, tid: saisons.append(season) or echt_lookup(season, tid))
        monkeypatch.setattr(uc, "load_snapshot",
                            lambda season: saisons.append(season) or echt_load(season))
        collector.run(SEASON, execute=True, max_provider_requests=5)
        assert saisons and set(saisons) == {SEASON}

    def test_national_nutzt_den_fifa_snapshot_des_spieljahres(self, monkeypatch):
        from src.data import fifa_rankings

        jahre = []
        monkeypatch.setattr(fifa_rankings, "lookup_team",
                            lambda year, tid: jahre.append(("lookup", year)) or None)
        monkeypatch.setattr(fifa_rankings, "load_snapshot",
                            lambda year: jahre.append(("load", year)) or {"available": False})
        roh = {"fixture": {"id": 5, "date": "2022-11-20T16:00:00+00:00",
                           "status": {"short": "FT"}},
               "league": {"id": 1, "name": "World Cup", "round": "Group Stage - 1"},
               "teams": {"home": {"id": 10, "name": "Eigenes Land"},
                         "away": {"id": 20, "name": "Gegner"}}}
        nbgl._classify_fixture(roh, {"team_id": 10, "league_id": 1, "api_season": 2022},
                               {"id": 10, "national": True}, {"id": 20, "national": True})
        assert ("lookup", 2022) in jahre and ("load", 2022) in jahre
        assert {j for _art, j in jahre} == {2022}

    def test_neue_aktuelle_rangliste_aendert_die_historische_liste_nicht(
            self, fertig, welt, monkeypatch):
        vorher = dataset.big_games_leaderboard(SEASON, SEASON, "all", 10)
        # Eine neue, aktuelle Rangliste (2026/27), in der die Gegner fehlen.
        coeff_dir = welt["tmp"] / "coeff"
        (coeff_dir / "uefa_coefficients_2026_27.json").write_text(json.dumps({
            "season": "2026/27", "status": "complete",
            "clubs": [{"rank": 1, "total_coefficient": 99.0, "apisports_team_id": 999}],
        }), encoding="utf-8")
        uc.clear_cache()
        nachher = dataset.big_games_leaderboard(SEASON, SEASON, "all", 10)
        assert nachher["available"] is True
        assert nachher["rows"] == vorher["rows"]
        neu = bgl.compute_player_big_games_uncached(STAR, SEASON, SEASON)
        assert neu["summary"]["big_game_score"] == _zeile(fertig, STAR)["big_game_score"]

    def test_ersetzter_historischer_snapshot_schliesst_die_liste(self, fertig, welt):
        pfad = welt["tmp"] / "coeff" / "uefa_coefficients_2021_22.json"
        daten = json.loads(pfad.read_text(encoding="utf-8"))
        daten["clubs"][0]["total_coefficient"] = 140.0
        pfad.write_text(json.dumps(daten), encoding="utf-8")
        uc.clear_cache()
        ergebnis = dataset.big_games_leaderboard(SEASON, SEASON, "all", 10)
        assert (ergebnis["available"], ergebnis["reason"]) == (False, "snapshot_changed")
        assert ergebnis["rows"] == []

    def test_fehlender_snapshot_schliesst_die_liste(self, fertig, welt):
        (welt["tmp"] / "coeff" / "uefa_coefficients_2021_22.json").unlink()
        uc.clear_cache()
        ergebnis = dataset.big_games_leaderboard(SEASON, SEASON, "all", 10)
        assert (ergebnis["available"], ergebnis["reason"]) == (False, "snapshot_missing")

    def test_fehlender_snapshot_beim_sammeln_ist_unvollstaendig(self, welt):
        befuellen()
        (welt["tmp"] / "coeff" / "uefa_coefficients_2021_22.json").unlink()
        uc.clear_cache()
        bericht = collector.run(SEASON, execute=True, max_provider_requests=5)
        assert bericht["dataset_written"] is False
        assert bericht["measured"]["players_with_source_problems"] == {"uefa_snapshot_missing": 4}
        punkt = dataset.read_json(dataset.checkpoint_path(SEASON))
        assert punkt["players_done"] == {}
        with pytest.raises(ValueError):
            dataset.build_dataset(SEASON, [], {}, {})

    def test_keine_eigene_rangliste_und_kein_rangabruf(self, welt, monkeypatch):
        """Nur der Snapshot wird gelesen - nie sortiert, nie geschrieben, nie geholt."""
        import socket

        befuellen()
        genutzt = set()
        for name in dir(uc):
            funktion = getattr(uc, name)
            if callable(funktion) and not name.startswith("_") and name not in ("json", "os", "threading"):
                def spion(*a, _n=name, _f=funktion, **k):
                    genutzt.add(_n)
                    return _f(*a, **k)
                monkeypatch.setattr(uc, name, spion)
        verbindungen = []
        monkeypatch.setattr(socket.socket, "connect",
                            lambda *a, **k: verbindungen.append(a) or (_ for _ in ()).throw(OSError()))
        dateien_vorher = {p.name: p.read_bytes() for p in (welt["tmp"] / "coeff").iterdir()}

        collector.run(SEASON, execute=True, max_provider_requests=5)
        dataset.big_games_leaderboard(SEASON, SEASON, "all", 10)

        # Erlaubt ist ausschliesslich das Lesen des gespeicherten Snapshots
        # (snapshot_path ist dessen Dateipfad, load_snapshot sein Parser).
        assert genutzt <= {"load_snapshot", "lookup_team", "season_label", "snapshot_path"}
        assert "load_snapshot" in genutzt and "lookup_team" in genutzt
        assert verbindungen == []
        assert all(not v for v in welt["calls"].values())
        dateien_nachher = {p.name: p.read_bytes() for p in (welt["tmp"] / "coeff").iterdir()}
        assert dateien_nachher == dateien_vorher


class TestKeineSammlungUeberDieRoute:

    def test_get_liest_nur_den_datensatz(self, fertig, welt, monkeypatch):
        import app as app_module

        gerechnet = []
        monkeypatch.setattr(bgl, "compute_player_big_games_uncached",
                            lambda *a, **k: gerechnet.append(a))
        monkeypatch.setattr(bgl, "_season_result", lambda *a, **k: gerechnet.append(a))
        monkeypatch.setattr(collector, "run", lambda *a, **k: gerechnet.append(a))
        dateien_vorher = sorted(os.listdir(dataset.DATASET_DIR))

        app_module.app.config["TESTING"] = True
        with app_module.app.test_client() as client:
            antwort = client.get("/api/player-leaderboard?scope=big_games&position=all"
                                 "&season_from=2021&season_to=2021&limit=30")
        daten = antwort.get_json()
        assert antwort.status_code == 200
        assert daten["available"] is True
        assert daten["metric"]["key"] == "big_game_score"
        assert daten["metric"]["label"] == "Big-Game-Score"
        assert len(daten["rows"]) <= 30
        assert gerechnet == []
        assert all(not v for v in welt["calls"].values())
        assert sorted(os.listdir(dataset.DATASET_DIR)) == dateien_vorher
        text = json.dumps(daten)
        for verboten in ("total_coefficient", "apisports_team_id", "coefficient",
                         "opponent_rank", "snapshots", "Anbieterbewertung"):
            assert verboten not in text, verboten


class TestCacheTor:
    """Die zentrale Aenderung in disk_cache: ohne Tor alles wie vorher."""

    def test_ohne_tor_unveraendert(self, tmp_path, monkeypatch):
        monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path / "c"))
        aufrufe = []
        wert = disk_cache.disk_cached_call("k:1", 60, lambda: aufrufe.append(1) or {"a": 1})
        assert wert == {"a": 1} and aufrufe == [1]
        assert disk_cache.disk_cached_call("k:1", 60, lambda: aufrufe.append(2)) == {"a": 1}
        assert aufrufe == [1]

    def test_tor_weist_fehlenden_eintrag_vor_dem_loader_ab(self, tmp_path, monkeypatch):
        monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path / "c"))
        tor = collector.RequestGate(execute=False, max_requests=0)
        geladen = []
        with disk_cache.request_gate(tor):
            with pytest.raises(collector.ProviderRequestBlocked):
                disk_cache.disk_cached_call("k:fehlt", 60, lambda: geladen.append(1))
        assert geladen == [] and tor.missing_keys == {"k:fehlt"}
        assert not os.path.exists(disk_cache._path_for("k:fehlt"))

    def test_tor_nutzt_abgelaufenen_eintrag(self, tmp_path, monkeypatch):
        monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path / "c"))
        disk_cache.write_entry("k:alt", {"v": 1}, ttl_seconds=-10)
        tor = collector.RequestGate(execute=True, max_requests=5)
        with disk_cache.request_gate(tor):
            wert = disk_cache.disk_cached_call("k:alt", 60, lambda: {"v": 2})
        assert wert == {"v": 1} and tor.used == 0 and tor.stale_keys == {"k:alt"}

    def test_tor_ist_nach_dem_block_wieder_weg(self, tmp_path, monkeypatch):
        monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path / "c"))
        with disk_cache.request_gate(collector.RequestGate(False, 0)):
            pass
        assert disk_cache.disk_cached_call("k:frei", 60, lambda: 7) == 7

    def test_lesespeicher(self, tmp_path, monkeypatch):
        monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path / "c"))
        disk_cache.write_entry("k:da", {"v": 1}, ttl_seconds=60)
        with disk_cache.read_memo() as memo:
            a = disk_cache.read_entry("k:da")
            b = disk_cache.read_entry("k:da")
            assert disk_cache.read_entry("k:nicht") is None
            disk_cache.write_entry("k:neu", {"v": 3}, ttl_seconds=60)
        assert a is b
        assert memo["k:nicht"] is None and memo["k:neu"]["payload"] == {"v": 3}
        assert disk_cache._READ_MEMO is None


class TestKennzahlen:

    def test_kennzahlen_aus_den_rohsummen(self):
        summary = {"raw": {"minutes": 180, "goal_assists": 3, "shots_on": None,
                           "passes_key": 4, "tackles": 0, "interceptions": 2,
                           "duels_won": 6, "duels_total": 10, "saves": None,
                           "goals_conceded": 1},
                   "avg_rating": 7.25}
        werte = dataset.big_games_metrics(summary)
        assert werte["goal_contributions_per90"] == 1.5
        assert werte["shots_on_per90"] is None
        assert werte["tackles_per90"] == 0.0        # echte Null bleibt Null
        assert werte["duels_won_pct"] == 60.0
        assert werte["rating"] == 7.25

    def test_gleiche_schluessel_wie_der_poolkatalog(self):
        from src.features.player_leaderboard import ALL_LEADERBOARD_METRIC_KEYS

        assert set(dataset.big_games_metrics({"raw": {}})) == set(ALL_LEADERBOARD_METRIC_KEYS)
