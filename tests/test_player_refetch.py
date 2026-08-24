"""
Der gezielte Einzelspielerrefresh.

WAS HIER BEWIESEN WIRD
----------------------
Um zwei Werte zu pruefen, kostete ein Refresh bisher rund 450 Anbieter-
abrufe - und der naheliegende Befehl existierte nicht:

    refresh_players.py --season 2026 --refetch-player 278
    error: unrecognized arguments: 278

Diese Datei belegt die Gegenzusicherungen: ein Request je Spieler, keine
Liga noetig, und - der wichtigste Teil - dass ein Ausfall oder eine
kaputte Antwort NIEMALS einen vorhandenen guten Stand zerstoert.

Kein Test hier spricht mit dem Anbieter. Der Abruf wird durchgereicht
(fetch=...), damit jeder Fall reproduzierbar ist, auch das Rate Limit.
"""

import json
import os

import pytest

from src.data import player_pool, player_refetch
from src.utils import disk_cache


# ---------------------------------------------------------------------------
# Bausteine
# ---------------------------------------------------------------------------

def make_raw(player_id, season, name="Testspieler", team="Testverein",
             team_id=999, minutes=90, appearances=1, league_id=140,
             position="Attacker"):
    """
    Eine Rohantwort in der Form, die /players?id=&season= liefert.

    league_id 140 ist die spanische Liga - hier nur, weil die Taxonomie
    eine echte Wettbewerbs-ID braucht, um den Block als Vereinspflicht-
    spiel einzuordnen. Kein Test haengt an diesem Verein.
    """
    return {
        "player": {"id": player_id, "name": name, "age": 25,
                   "firstname": "Test", "lastname": "Spieler"},
        "statistics": [{
            "team": {"id": team_id, "name": team},
            "league": {"id": league_id, "name": "La Liga", "country": "Spain",
                       "season": season, "type": "League"},
            "games": {"minutes": minutes, "appearences": appearances,
                      "position": position, "rating": "7.0", "lineups": 1},
            "goals": {"total": 5, "assists": 3, "conceded": 0, "saves": None},
            "shots": {"total": 20, "on": 10},
            "passes": {"total": 500, "key": 20, "accuracy": 80},
            "dribbles": {"attempts": 30, "success": 15},
            "duels": {"total": 100, "won": 55},
            "tackles": {"total": 10, "blocks": 2, "interceptions": 5},
            "fouls": {"drawn": 10, "committed": 8},
            "cards": {"yellow": 2, "red": 0},
        }],
    }


def make_national_only_raw(player_id, season, name="Neuzugang"):
    """
    Eine Antwort ganz ohne Vereinsblock - der Fall Lamine Yamal.

    Sein Profil wurde am 24.08.2026 frisch geholt und enthielt
    ausschliesslich Nationalmannschaftsbloecke. Das ist keine alte
    Cachedatei, sondern eine Anbieterluecke - und der Spieler darf
    deswegen nicht verschwinden.
    """
    return {
        "player": {"id": player_id, "name": name, "age": 19},
        "statistics": [{
            "team": {"id": 9, "name": "Spain"},
            "league": {"id": 1, "name": "World Cup", "country": "World",
                       "season": season, "type": "Cup"},
            "games": {"minutes": 615, "appearences": 8, "position": "Attacker"},
            "goals": {"total": 4, "assists": 2},
        }],
    }


@pytest.fixture(autouse=True)
def kein_netzwerk(monkeypatch):
    """
    Sperrt jeden Verbindungsaufbau fuer die gesamte Datei.

    WARUM DAS NOETIG IST: Beim Schreiben dieser Tests hat genau ein Fall
    unbemerkt den echten Anbieter befragt. _build_entry() laedt den
    Spieler ueber seine ID nach, und ein leerer Testcache fuehrte
    geradewegs in den echten Abruf. Der Fehler war am Ergebnis nicht zu
    erkennen - es sah aus wie gueltige Testdaten.

    Diese Sperre macht denselben Fehler ab jetzt sofort sichtbar: Statt
    still einen Request zu verbrauchen, faellt der Test mit einer
    eindeutigen Meldung um.
    """
    import socket

    def gesperrt(*args, **kwargs):
        raise AssertionError(
            "Ein Test hat eine Netzverbindung aufgebaut. Tests duerfen den "
            "Anbieter nicht befragen - den Abruf ueber fetch=... ersetzen."
        )

    monkeypatch.setattr(socket.socket, "connect", gesperrt)
    monkeypatch.setattr(socket, "create_connection", gesperrt)


@pytest.fixture
def umgebung(tmp_path, monkeypatch):
    """Cache und Pool in einem Wegwerfverzeichnis, kein Netzwerk."""
    cache_dir = tmp_path / "cache"
    pool_dir = tmp_path / "pool"
    cache_dir.mkdir()
    pool_dir.mkdir()

    monkeypatch.setattr(disk_cache, "CACHE_DIR", str(cache_dir))
    monkeypatch.setattr(player_pool, "POOL_DIR", str(pool_dir))
    monkeypatch.setattr(player_pool, "STATUS_PATH", str(pool_dir / "status.json"))

    # Kein Kaderindex - die Tests, die ihn brauchen, legen ihn selbst an.
    disk_cache.bypass_prefixes()

    yield {"cache": cache_dir, "pool": pool_dir, "tmp": tmp_path}

    disk_cache.bypass_prefixes()


def zaehlender_abruf(antwort_je_id):
    """
    Ein Ersatzabruf, der mitzaehlt, wie oft er gerufen wurde.

    antwort_je_id: dict id -> Antwort, Ausnahme, oder callable.
    """
    aufrufe = []

    def fetch(player_id, season, throttle_seconds=0.0):
        aufrufe.append((player_id, season))
        antwort = antwort_je_id.get(player_id)
        if isinstance(antwort, Exception):
            raise antwort
        if callable(antwort):
            return antwort(player_id, season)
        return antwort

    fetch.aufrufe = aufrufe
    return fetch


def dateizustand(verzeichnis):
    """Inhalt aller Dateien unterhalb eines Verzeichnisses."""
    zustand = {}
    for wurzel, _, dateien in os.walk(verzeichnis):
        for name in dateien:
            pfad = os.path.join(wurzel, name)
            with open(pfad, "rb") as f:
                zustand[os.path.relpath(pfad, verzeichnis)] = f.read()
    return zustand


# ---------------------------------------------------------------------------
# Eingaben
# ---------------------------------------------------------------------------

class TestIdsPruefen:

    def test_mehrere_ids_bleiben_erhalten(self):
        ids, _ = player_refetch.normalize_ids([278, 762])
        assert ids == [278, 762]

    def test_doppelte_id_wird_entfernt(self):
        ids, _ = player_refetch.normalize_ids([278, 762, 278])
        assert ids == [278, 762]

    def test_reihenfolge_der_eingabe_bleibt(self):
        ids, _ = player_refetch.normalize_ids([762, 278])
        assert ids == [762, 278]

    def test_ungueltige_id_wird_abgewiesen_nicht_geraten(self):
        ids, abgewiesen = player_refetch.normalize_ids(["abc"])
        assert ids == []
        assert abgewiesen and "keine ganze Zahl" in abgewiesen[0][1]

    def test_negative_id_wird_abgewiesen(self):
        ids, abgewiesen = player_refetch.normalize_ids([-5, 0])
        assert ids == []
        assert len(abgewiesen) == 2

    def test_zeichenkette_mit_zahl_ist_gueltig(self):
        """argparse liefert int, aber die Funktion wird auch direkt genutzt."""
        ids, _ = player_refetch.normalize_ids(["278"])
        assert ids == [278]


# ---------------------------------------------------------------------------
# Antworten pruefen
# ---------------------------------------------------------------------------

class TestAntwortPruefen:

    def test_gueltige_antwort_wird_angenommen(self):
        ok, grund = player_refetch.validate_profile(
            make_raw(278, 2026), 278, 2026)
        assert ok, grund

    def test_leere_antwort_wird_abgewiesen(self):
        ok, grund = player_refetch.validate_profile(None, 278, 2026)
        assert not ok and "leer" in grund

    def test_falsche_spieler_id_wird_abgewiesen(self):
        """
        Der gefaehrlichste Fall: Eine formal gueltige Antwort ueber den
        FALSCHEN Spieler wuerde sonst dessen Werte in einen fremden
        Pooleintrag schreiben.
        """
        ok, grund = player_refetch.validate_profile(
            make_raw(999, 2026), 278, 2026)
        assert not ok
        assert "falsche Spieler-ID" in grund

    def test_fehlendes_statistics_feld_wird_abgewiesen(self):
        roh = make_raw(278, 2026)
        del roh["statistics"]
        ok, grund = player_refetch.validate_profile(roh, 278, 2026)
        assert not ok and "statistics" in grund

    def test_statistics_als_liste_erwartet(self):
        roh = make_raw(278, 2026)
        roh["statistics"] = {"nicht": "eine Liste"}
        ok, _ = player_refetch.validate_profile(roh, 278, 2026)
        assert not ok

    def test_falsche_saison_wird_abgewiesen(self):
        ok, grund = player_refetch.validate_profile(
            make_raw(278, 2025), 278, 2026)
        assert not ok and "Saison" in grund

    def test_fehlende_saisonangabe_wird_nicht_bemaengelt(self):
        """Der Anbieter laesst das Feld gelegentlich weg."""
        roh = make_raw(278, 2026)
        roh["statistics"][0]["league"].pop("season")
        ok, _ = player_refetch.validate_profile(roh, 278, 2026)
        assert ok

    def test_leere_statistikliste_ist_gueltig(self):
        """
        Keine Bloecke ist eine Aussage ("noch nichts gespielt"), kein
        Formfehler. Ob damit etwas anzufangen ist, entscheidet die
        Qualitaetseinstufung - nicht die Formpruefung.
        """
        roh = make_raw(278, 2026)
        roh["statistics"] = []
        ok, _ = player_refetch.validate_profile(roh, 278, 2026)
        assert ok


# ---------------------------------------------------------------------------
# Der Abruf selbst
# ---------------------------------------------------------------------------

class TestEinRequestJeSpieler:

    def test_zwei_spieler_kosten_zwei_requests(self, umgebung):
        """Die Kernzusicherung: 2 statt rund 450."""
        fetch = zaehlender_abruf({
            278: make_raw(278, 2026),
            762: make_raw(762, 2026),
        })
        ergebnisse, zus = player_refetch.refetch_many(
            [278, 762], 2026, fetch=fetch)

        assert len(fetch.aufrufe) == 2
        assert zus["requests"] == 2
        assert zus["erfolgreich"] == 2

    def test_ein_spieler_kostet_genau_einen_request(self, umgebung):
        fetch = zaehlender_abruf({278: make_raw(278, 2026)})
        player_refetch.refetch_player(278, 2026, fetch=fetch)
        assert len(fetch.aufrufe) == 1

    def test_es_wird_keine_ganze_liga_geladen(self, umgebung):
        """Nur die genannten IDs, keine weiteren."""
        fetch = zaehlender_abruf({278: make_raw(278, 2026)})
        player_refetch.refetch_many([278], 2026, fetch=fetch)
        assert [a[0] for a in fetch.aufrufe] == [278]


class TestCacheUmgehung:

    def test_nur_der_genannte_schluessel_wird_umgangen(self):
        """
        Ein vollstaendiger Schluessel ist sein eigener Praefix. Wichtig ist,
        dass er nicht versehentlich Nachbarn mittrifft.
        """
        with disk_cache.bypass("apisports:playerprofile:278:2026"):
            assert disk_cache.is_bypassed("apisports:playerprofile:278:2026")
            assert not disk_cache.is_bypassed("apisports:playerprofile:762:2026")

    def test_kurzere_id_trifft_nicht_die_laengere(self):
        """27 darf nicht 278 umgehen - die Saison am Ende grenzt sauber ab."""
        with disk_cache.bypass("apisports:playerprofile:27:2026"):
            assert not disk_cache.is_bypassed("apisports:playerprofile:278:2026")

    def test_umgehung_wird_danach_zurueckgesetzt(self):
        disk_cache.bypass_prefixes("vorher:")
        try:
            with disk_cache.bypass("apisports:playerprofile:278:2026"):
                assert not disk_cache.is_bypassed("vorher:x")
            assert disk_cache.is_bypassed("vorher:x")
        finally:
            disk_cache.bypass_prefixes()

    def test_umgehung_wird_auch_nach_ausnahme_zurueckgesetzt(self):
        with pytest.raises(RuntimeError):
            with disk_cache.bypass("a:"):
                raise RuntimeError("absichtlich")
        assert disk_cache.current_bypass_prefixes() == []


class TestAlteDatenBleibenErhalten:
    """
    Der wichtigste Abschnitt. Ein Refresh, der bei einem Ausfall Daten
    zerstoert, ist schlimmer als gar kein Refresh: Der alte Stand laesst
    sich nicht zurueckholen, ein ausgefallener Abruf jederzeit wiederholen.
    """

    def _mit_bestand(self, umgebung, minutes=90):
        """Einen gueltigen Cachestand anlegen."""
        disk_cache.write_entry(
            player_refetch.profile_cache_key(278, 2026),
            [make_raw(278, 2026, minutes=minutes)],
            ttl_seconds=86400, source="test")

    def test_rate_limit_laesst_den_cache_unveraendert(self, umgebung):
        from src.api.apisports_api import ApisportsRateLimit

        self._mit_bestand(umgebung)
        vorher = dateizustand(umgebung["cache"])

        fetch = zaehlender_abruf({278: ApisportsRateLimit("Limit erreicht")})
        ergebnis = player_refetch.refetch_player(278, 2026, fetch=fetch)

        assert not ergebnis["ok"]
        assert "Rate Limit" in ergebnis["error"]
        assert dateizustand(umgebung["cache"]) == vorher

    def test_providerausfall_laesst_den_cache_unveraendert(self, umgebung):
        from src.api.apisports_api import ApisportsUnavailable

        self._mit_bestand(umgebung)
        vorher = dateizustand(umgebung["cache"])

        fetch = zaehlender_abruf({278: ApisportsUnavailable("kaputt")})
        ergebnis = player_refetch.refetch_player(278, 2026, fetch=fetch)

        assert not ergebnis["ok"]
        assert dateizustand(umgebung["cache"]) == vorher

    def test_ungueltige_antwort_ueberschreibt_keinen_guten_stand(self, umgebung):
        """
        disk_cached_call hat die Antwort zwar bereits geschrieben - die
        Pruefung greift danach. Entscheidend ist deshalb, dass der POOL
        unveraendert bleibt und der Fall als Fehler gemeldet wird.
        """
        self._mit_bestand(umgebung)
        pool_vorher = dateizustand(umgebung["pool"])

        # Antwort ueber einen ganz anderen Spieler.
        fetch = zaehlender_abruf({278: make_raw(999, 2026)})
        ergebnis = player_refetch.refetch_player(278, 2026, fetch=fetch)

        assert not ergebnis["ok"]
        assert "falsche Spieler-ID" in ergebnis["error"]
        assert ergebnis["pool_updated"] is False
        assert dateizustand(umgebung["pool"]) == pool_vorher

    def test_leere_antwort_meldet_rueckfall_statt_erfolg(self, umgebung):
        self._mit_bestand(umgebung)
        fetch = zaehlender_abruf({278: None})
        ergebnis = player_refetch.refetch_player(278, 2026, fetch=fetch)

        assert not ergebnis["ok"]
        assert ergebnis["quality"] == "stale_fallback"

    def test_ohne_bestand_meldet_der_ausfall_einen_providerfehler(self, umgebung):
        from src.api.apisports_api import ApisportsUnavailable

        fetch = zaehlender_abruf({278: ApisportsUnavailable("kaputt")})
        ergebnis = player_refetch.refetch_player(278, 2026, fetch=fetch)
        assert ergebnis["quality"] == "provider_error"


class TestDryRunSchreibtNichts:

    def test_kein_einziges_byte_aendert_sich(self, umgebung):
        """
        Die harte Zusicherung des Diagnosemodus: Er darf den Anbieter
        fragen, aber danach muss jede Datei bitgleich sein.
        """
        disk_cache.write_entry(
            player_refetch.profile_cache_key(278, 2026),
            [make_raw(278, 2026, minutes=38)],
            ttl_seconds=86400, source="test")

        vorher = dateizustand(umgebung["tmp"])

        fetch = zaehlender_abruf({278: make_raw(278, 2026, minutes=90)})
        ergebnis = player_refetch.refetch_player(
            278, 2026, dry_run=True, fetch=fetch)

        assert ergebnis["ok"]
        assert dateizustand(umgebung["tmp"]) == vorher, (
            "--dry-run hat Dateien veraendert"
        )

    def test_der_anbieter_wird_trotzdem_gefragt(self, umgebung):
        fetch = zaehlender_abruf({278: make_raw(278, 2026)})
        player_refetch.refetch_player(278, 2026, dry_run=True, fetch=fetch)
        assert len(fetch.aufrufe) == 1

    def test_die_differenz_wird_sichtbar(self, umgebung):
        """Genau dafuer gibt es den Modus: vergleichen ohne festzuschreiben."""
        disk_cache.write_entry(
            player_refetch.profile_cache_key(278, 2026),
            [make_raw(278, 2026, minutes=38)],
            ttl_seconds=86400, source="test")

        fetch = zaehlender_abruf({278: make_raw(278, 2026, minutes=90)})
        ergebnis = player_refetch.refetch_player(
            278, 2026, dry_run=True, fetch=fetch)

        assert ergebnis["old_minutes"]["club_all"] == 38
        assert ergebnis["new_minutes"]["club_all"] == 90
        assert ergebnis["changed"] is True

    def test_pool_wird_nicht_angefasst(self, umgebung):
        fetch = zaehlender_abruf({278: make_raw(278, 2026)})
        ergebnis = player_refetch.refetch_player(
            278, 2026, dry_run=True, fetch=fetch)
        assert ergebnis["pool_updated"] is False
        assert ergebnis["persisted"] is False

    def test_die_sperre_wirkt_auch_auf_direkte_schreibversuche(self, umgebung):
        """
        Die Sperre sitzt in write_entry, nicht beim Aufrufer. Deshalb kann
        auch kein anderer Codepfad waehrenddessen etwas festschreiben.
        """
        with disk_cache.no_persist():
            eintrag = disk_cache.write_entry("test:key", [1], 60, source="t")
            assert eintrag["meta"]["persisted"] is False
        assert disk_cache.read_entry("test:key") is None

    def test_die_sperre_wird_danach_aufgehoben(self, umgebung):
        with disk_cache.no_persist():
            pass
        disk_cache.write_entry("test:key2", [1], 60, source="t")
        assert disk_cache.read_entry("test:key2") is not None


# ---------------------------------------------------------------------------
# Pool
# ---------------------------------------------------------------------------

class TestPoolAenderung:

    def _pool_mit(self, eintraege, league="pd", season=2026):
        player_pool.write_pool({
            "league": league, "season": season,
            "pages_done": [1], "players": eintraege,
        })

    def _pool_eintrag(self, pid, name, minutes):
        """Ein Pooleintrag in der Form, die build_pool_entry erzeugt."""
        return {
            "player_id": pid, "name": name, "team_name": "Testverein",
            "team_id": 999, "position": "ATT", "age": 25,
            "league_code": "pd",
            "minutes_by_scope": {"club_all": minutes, "league": minutes},
            "metrics_by_scope": {"club_all": {}, "league": {}},
        }

    def test_nur_der_genannte_spieler_aendert_sich(self, umgebung):
        """
        Die Nachbarn muessen byte-fuer-byte dieselben bleiben. Ein
        gezielter Refresh darf keine Nebenwirkung auf Spieler haben, nach
        denen niemand gefragt hat.
        """
        nachbar = self._pool_eintrag(762, "Nachbar", 500)
        self._pool_mit([self._pool_eintrag(278, "Ziel", 38), nachbar])

        fetch = zaehlender_abruf({278: make_raw(278, 2026, minutes=90)})
        ergebnis = player_refetch.refetch_player(278, 2026, fetch=fetch)

        assert ergebnis["pool_updated"] is True
        pool = player_pool.read_pool("pd", 2026)
        nach_id = {p["player_id"]: p for p in pool["players"]}

        assert nach_id[762] == nachbar, "ein unbeteiligter Spieler wurde veraendert"
        assert nach_id[278]["minutes_by_scope"]["club_all"] == 90

    def test_die_spieleranzahl_bleibt_gleich(self, umgebung):
        self._pool_mit([self._pool_eintrag(278, "Ziel", 38),
                        self._pool_eintrag(762, "Nachbar", 500)])

        fetch = zaehlender_abruf({278: make_raw(278, 2026)})
        player_refetch.refetch_player(278, 2026, fetch=fetch)

        assert len(player_pool.read_pool("pd", 2026)["players"]) == 2

    def test_ein_neuer_spieler_wird_ergaenzt_nicht_ersetzt(self, umgebung):
        self._pool_mit([self._pool_eintrag(762, "Nachbar", 500)])

        # 278 ist im Pool unbekannt, aber im Kaderindex.
        disk_cache.write_entry(
            "apisports:squad_index:2026",
            [{"player_id": 278, "name": "Neu", "team_id": 999,
              "team_name": "Testverein", "league_code": "pd",
              "position": "ATT"}],
            ttl_seconds=86400, source="test")

        fetch = zaehlender_abruf({278: make_raw(278, 2026)})
        ergebnis = player_refetch.refetch_player(278, 2026, fetch=fetch)

        assert ergebnis["pool_updated"] is True
        pool = player_pool.read_pool("pd", 2026)
        assert {p["player_id"] for p in pool["players"]} == {278, 762}

    def test_der_qualitaetsvermerk_landet_im_pooleintrag(self, umgebung):
        self._pool_mit([self._pool_eintrag(278, "Ziel", 38)])

        fetch = zaehlender_abruf({278: make_raw(278, 2026, minutes=38)})
        player_refetch.refetch_player(278, 2026, fetch=fetch)

        pool = player_pool.read_pool("pd", 2026)
        eintrag = pool["players"][0]
        assert eintrag["data_quality"]["cache_quality"] == "low_sample"
        assert eintrag["data_quality"]["provisional"] is True

    def test_ohne_vereinsblock_bleibt_der_pooleintrag_stehen(self, umgebung):
        """
        Der Fall Lamine Yamal. Eine Anbieterluecke darf nicht zu einem
        Datenverlust werden - der bisherige Eintrag bleibt, wo er ist.
        """
        bestand = self._pool_eintrag(386828, "Neuzugang", 3828)
        self._pool_mit([bestand])

        fetch = zaehlender_abruf({386828: make_national_only_raw(386828, 2026)})
        ergebnis = player_refetch.refetch_player(386828, 2026, fetch=fetch)

        assert ergebnis["ok"] is True
        assert ergebnis["quality"] == "provider_incomplete"
        assert ergebnis["pool_updated"] is False

        pool = player_pool.read_pool("pd", 2026)
        assert pool["players"] == [bestand], "der Eintrag wurde angetastet"

    def test_der_status_wird_nicht_auf_complete_gesetzt(self, umgebung):
        """
        Ein einzelner erneuerter Spieler macht aus einem unvollstaendigen
        Pool keinen vollstaendigen.
        """
        self._pool_mit([self._pool_eintrag(278, "Ziel", 38)])
        player_pool.update_pool_status("pd", 2026,
                                       status=player_pool.STATUS_IN_PROGRESS)

        fetch = zaehlender_abruf({278: make_raw(278, 2026)})
        player_refetch.refetch_player(278, 2026, fetch=fetch)

        eintrag = player_pool.get_pool_status("pd", 2026)
        assert eintrag["status"] == player_pool.STATUS_IN_PROGRESS

    def test_ohne_aufloesbare_liga_wird_nichts_geschrieben(self, umgebung):
        """Ein voellig unbekannter Spieler laesst sich nicht einsortieren."""
        fetch = zaehlender_abruf({111222: make_raw(111222, 2026)})
        ergebnis = player_refetch.refetch_player(111222, 2026, fetch=fetch)

        assert ergebnis["ok"] is True
        assert ergebnis["pool_updated"] is False
        assert "keine Liga" in ergebnis["quality_reason"]


class TestHerkunftAufloesen:

    def test_pool_ist_die_erste_quelle(self, umgebung):
        player_pool.write_pool({
            "league": "pd", "season": 2026, "pages_done": [1],
            "players": [{"player_id": 278, "name": "Aus dem Pool",
                         "team_name": "Verein A", "team_id": 1}],
        })
        herkunft = player_refetch.resolve_player(278, 2026)
        assert herkunft["source"] == "pool"
        assert herkunft["league_code"] == "pd"
        assert herkunft["name"] == "Aus dem Pool"

    def test_kaderindex_ist_die_zweite_quelle(self, umgebung):
        disk_cache.write_entry(
            "apisports:squad_index:2026",
            [{"player_id": 278, "name": "Aus dem Kader", "team_id": 5,
              "team_name": "Verein B", "league_code": "sa"}],
            ttl_seconds=86400, source="test")

        herkunft = player_refetch.resolve_player(278, 2026)
        assert herkunft["source"] == "squad_index"
        assert herkunft["league_code"] == "sa"

    def test_vorsaison_liefert_nur_die_liga_nicht_den_verein(self, umgebung):
        """Der Verein kann inzwischen ein anderer sein - ihn zu uebernehmen
        waere eine Behauptung."""
        player_pool.write_pool({
            "league": "bl1", "season": 2025, "pages_done": [1],
            "players": [{"player_id": 278, "name": "Vorjahr",
                         "team_name": "Alter Verein", "team_id": 7}],
        })
        herkunft = player_refetch.resolve_player(278, 2026)
        assert herkunft["league_code"] == "bl1"
        assert herkunft["team_name"] is None

    def test_unbekannter_spieler_ist_kein_fehler(self, umgebung):
        herkunft = player_refetch.resolve_player(999999, 2026)
        assert herkunft["source"] is None
        assert herkunft["league_code"] is None

    def test_der_kaderindex_wird_niemals_gebaut(self, umgebung, monkeypatch):
        """
        Ein Aufbau kostet rund hundert Abrufe. Fuer einen gezielten
        Refresh von zwei Spielern waere das das Gegenteil des Zwecks.
        """
        from src.data import current_squads

        def darf_nicht(*args, **kwargs):
            raise AssertionError("der Kaderindex wurde gebaut")

        monkeypatch.setattr(current_squads, "build_squad_index", darf_nicht)
        assert player_refetch.cached_squad_index(2026) == []
        player_refetch.resolve_player(278, 2026)


class TestTeamAufloesung:

    def test_kaderindex_liefert_die_mitglieder(self, umgebung):
        disk_cache.write_entry(
            "apisports:squad_index:2026",
            [{"player_id": 1, "team_id": 541, "team_name": "Verein",
              "league_code": "pd"},
             {"player_id": 2, "team_id": 541, "team_name": "Verein",
              "league_code": "pd"},
             {"player_id": 3, "team_id": 999, "team_name": "Anderer",
              "league_code": "pd"}],
            ttl_seconds=86400, source="test")

        ids, name = player_refetch.team_player_ids(541, 2026)
        assert ids == [1, 2]
        assert name == "Verein"

    def test_ohne_index_bleibt_es_ehrlich_leer(self, umgebung):
        ids, name = player_refetch.team_player_ids(541, 2026)
        assert ids == [] and name is None


# ---------------------------------------------------------------------------
# Teilfehler
# ---------------------------------------------------------------------------

class TestTeilfehler:

    def test_ein_ausfall_stoppt_die_uebrigen_nicht(self, umgebung):
        from src.api.apisports_api import ApisportsUnavailable

        fetch = zaehlender_abruf({
            278: ApisportsUnavailable("kaputt"),
            762: make_raw(762, 2026),
        })
        ergebnisse, zus = player_refetch.refetch_many(
            [278, 762], 2026, fetch=fetch)

        assert zus["bearbeitet"] == 2
        assert zus["erfolgreich"] == 1
        assert zus["fehlgeschlagen"] == 1

    def test_rate_limit_bricht_dagegen_ab(self, umgebung):
        """
        Nach einer Ablehnung waeren weitere Anfragen zwecklos und wuerden
        das Limit weiter belasten.
        """
        from src.api.apisports_api import ApisportsRateLimit

        fetch = zaehlender_abruf({
            278: ApisportsRateLimit("Limit"),
            762: make_raw(762, 2026),
        })
        ergebnisse, zus = player_refetch.refetch_many(
            [278, 762], 2026, fetch=fetch)

        assert zus["abgebrochen"] is True
        assert zus["bearbeitet"] == 1
        assert len(fetch.aufrufe) == 1, "nach dem Limit wurde weiter gefragt"

    def test_die_zusammenfassung_zaehlt_ehrlich(self, umgebung):
        fetch = zaehlender_abruf({
            278: make_raw(278, 2026),
            762: make_raw(999, 2026),      # falsche ID -> abgewiesen
        })
        _, zus = player_refetch.refetch_many([278, 762], 2026, fetch=fetch)

        assert zus["erfolgreich"] == 1
        assert zus["fehlgeschlagen"] == 1
        assert zus["requests"] == 2


# ---------------------------------------------------------------------------
# Qualitaetseinstufung
# ---------------------------------------------------------------------------

class TestQualitaet:

    def test_38_minuten_gelten_als_duenne_stichprobe(self, umgebung):
        """
        Und NICHT als "keine Daten". Der Spieler bleibt sichtbar und
        vergleichbar - nur die Einordnung ist duenn.
        """
        from src.data.player_data_quality import classify_profile_quality

        zustand, _ = classify_profile_quality(make_raw(278, 2026, minutes=38))
        assert zustand == "low_sample"

    def test_volle_saison_gilt_als_belastbar(self):
        from src.data.player_data_quality import classify_profile_quality

        zustand, _ = classify_profile_quality(
            make_raw(278, 2026, minutes=2500, appearances=30))
        assert zustand == "current_final_or_latest"

    def test_ohne_vereinsblock_heisst_anbieterluecke(self):
        from src.data.player_data_quality import classify_profile_quality

        zustand, _ = classify_profile_quality(
            make_national_only_raw(386828, 2026))
        assert zustand == "provider_incomplete"

    def test_im_kader_ohne_einsatz_ist_eine_aussage(self):
        from src.data.player_data_quality import classify_profile_quality

        zustand, _ = classify_profile_quality(
            make_raw(278, 2026, minutes=0, appearances=0))
        assert zustand == "no_current_appearance"

    def test_freundschaftsspiele_zaehlen_nicht_als_vereinsdaten(self):
        """667 ist der Freundschaftsspielwettbewerb der Vereine."""
        from src.data.player_data_quality import club_minutes

        roh = make_raw(278, 2026, minutes=120, league_id=667)
        assert club_minutes(roh) == 0

    def test_supercupminuten_zaehlen_als_vereinsdaten(self):
        """556 ist der spanische Supercup - ein Pflichtspiel."""
        from src.data.player_data_quality import club_minutes

        roh = make_raw(278, 2026, minutes=31, league_id=556)
        assert club_minutes(roh) == 31

    def test_gleiche_minuten_im_team_sind_ein_hinweis(self):
        """
        Elf Spieler mit exakt 38 Minuten, Torwart eingeschlossen. Das
        Muster ist auffaellig - aber es beweist nichts, denn es entsteht
        auch bei einem abgebrochenen Spiel.
        """
        from src.data.player_data_quality import detect_uniform_minutes

        verdacht, wert, anzahl = detect_uniform_minutes([38] * 11 + [None] * 12)
        assert verdacht is True
        assert wert == 38 and anzahl == 11

    def test_eine_mannschaft_mit_90_minuten_ist_normal(self):
        from src.data.player_data_quality import detect_uniform_minutes

        verdacht, _, _ = detect_uniform_minutes([90] * 11)
        assert verdacht is False

    def test_alter_eintrag_ohne_vermerk_bleibt_lesbar(self):
        from src.data.player_data_quality import read_quality

        block = read_quality({"player_id": 1})
        assert block["cache_quality"] is None
        assert "nicht vermerkt" in block["provisional_reason"]


# ---------------------------------------------------------------------------
# Gemeinsamer Aufbauweg
# ---------------------------------------------------------------------------

class TestGleicherEintragWieBeimImport:

    def test_import_und_refresh_bauen_denselben_eintrag(self, umgebung,
                                                        monkeypatch):
        """
        Zwei getrennte Aufbauwege waeren eine sichere Quelle fuer
        Abweichungen zwischen "frisch importiert" und "gezielt erneuert" -
        und die faende niemand, weil beide fuer sich plausibel aussehen.

        _build_entry() laedt den Spieler ueber seine ID nach. Dieser Abruf
        wird hier ersetzt, sonst spraeche der Test mit dem Anbieter - und
        genau das darf ein Test nie tun.
        """
        import refresh_players

        roh = make_raw(278, 2026)
        monkeypatch.setattr(refresh_players, "get_player_season_raw",
                            lambda pid, season, throttle_seconds=0.0: roh)

        ueber_refetch = player_refetch.build_entry_from_raw(roh, 2026, "pd")
        ueber_import = refresh_players._build_entry(roh, 2026, "pd")

        assert ueber_refetch == ueber_import
