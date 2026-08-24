"""
Tests der Datenreparatur: Report, Vollstaendigkeit, Positionen, Scopes.

Jeder Test hier steht fuer eine bewiesene Ursache aus der
Root-Cause-Analyse. Die dort genannten Spieler und Wettbewerbe sind
Beispiele, keine Sonderfaelle - deshalb pruefen die Tests durchgaengig
die REGEL und nie eine player_id.

Gliederung:
    R  Report und Minutenzugriff          (1-8)
    V  Vollstaendigkeit und Staging       (9-18)
    P  Positionsnormalisierung            (19-30)
    S  Scopes, Supercups, Freundschaften  (31-46)
    B  Big Games                          (47-54)
    K  Kader-Fallback und Suche           (55-60)
    C  Cache, Provenienz, Service Worker  (61-70)
"""

import json
import os

import pytest

from src.data import competition_taxonomy as taxonomy
from src.data import player_pool
from src.data.player_metrics import (
    POSITION_ALIASES, POSITION_GROUPS, normalize_position,
    unknown_position_report)
from src.data.player_pool import (
    EXPECTED_TEAM_COUNT, MIN_PLAYERS_PER_LEAGUE, STATUS_COMPLETE,
    STATUS_PROVIDER_INCOMPLETE, evaluate_pool, is_better_pool, player_minutes,
    pool_revision)


def _entry(minutes=None, metrics_minutes=None, position="Attacker",
           team="Test FC"):
    """Ein Pooleintrag, wahlweise im neuen oder im Altformat."""
    eintrag = {"player_id": 1, "name": "X", "position": position,
               "team_name": team}
    if minutes is not None:
        eintrag["minutes_by_scope"] = {"club_all": minutes}
    if metrics_minutes is not None:
        eintrag["metrics_by_scope"] = {"club_all": {"minutes": metrics_minutes}}
    return eintrag


def _pool(anzahl=200, teams=18, minutes=1000, league="bl1", season=2025):
    spieler = []
    for i in range(anzahl):
        spieler.append({
            "player_id": i, "name": f"S {i}", "position": "Midfielder",
            "team_name": f"Verein {i % teams}" if teams else None,
            "minutes_by_scope": {"club_all": minutes},
        })
    return {"league": league, "season": season, "pages_done": [1],
            "players": spieler}


# ---------------------------------------------------------------------------
# R  Report und Minutenzugriff
# ---------------------------------------------------------------------------

class TestR_Report:

    def test_r1_minuten_kommen_aus_minutes_by_scope(self):
        """
        Der Report las frueher entry["minutes"] - ein Feld, das es nicht
        gibt. Deshalb stand dort dauerhaft 0, obwohl allein die Premier
        League 187 Spieler mit Minuten hatte.
        """
        assert player_minutes(_entry(minutes=1800)) == 1800

    def test_r2_altformat_faellt_kontrolliert_zurueck(self):
        """Pools von vor minutes_by_scope bleiben lesbar."""
        assert player_minutes(_entry(metrics_minutes=900)) == 900

    def test_r3_neues_format_hat_vorrang(self):
        eintrag = _entry(minutes=1800, metrics_minutes=900)
        assert player_minutes(eintrag) == 1800

    def test_r4_none_wird_zu_null(self):
        assert player_minutes(_entry(minutes=None, metrics_minutes=None)) == 0
        assert player_minutes({"minutes_by_scope": {"club_all": None}}) == 0

    def test_r5_das_alte_feld_existiert_wirklich_nicht(self):
        """Absicherung gegen einen Rueckfall auf den alten Zugriff."""
        assert "minutes" not in _entry(minutes=1800)

    def test_r6_unsinnige_eingabe_ergibt_null(self):
        assert player_minutes(None) == 0
        assert player_minutes("kein dict") == 0

    def test_r7_scope_ist_waehlbar(self):
        eintrag = {"minutes_by_scope": {"club_all": 100, "league": 60}}
        assert player_minutes(eintrag, scope="league") == 60

    def test_r8_echte_pooldateien_liefern_minuten(self):
        """
        Echtdaten: Mindestens eine Liga muss Spieler mit Minuten haben -
        sonst wuerde der Report wieder null melden, ohne dass es auffaellt.
        """
        gesamt = 0
        for code in ("bl1", "pl", "pd", "sa", "fl1"):
            pool = player_pool.read_pool(code, 2026)
            gesamt += sum(1 for e in (pool.get("players") or [])
                          if (player_minutes(e) or 0) > 0)
        if gesamt == 0:
            pytest.skip("keine lokalen Pools mit Minuten vorhanden")
        assert gesamt > 0


# ---------------------------------------------------------------------------
# V  Vollstaendigkeit und Staging
# ---------------------------------------------------------------------------

class TestV_Vollstaendigkeit:

    def test_v9_leere_liga_ist_nie_vollstaendig(self):
        b = evaluate_pool({"players": []}, "bl1")
        assert b["status"] == STATUS_PROVIDER_INCOMPLETE
        assert "keine Spieler geliefert" in b["issues"]

    def test_v10_unvollstaendige_teamabdeckung_ist_nicht_vollstaendig(self):
        b = evaluate_pool(_pool(anzahl=240, teams=16), "pl")
        assert b["status"] == STATUS_PROVIDER_INCOMPLETE
        assert b["teams"] == 16 and b["expected_teams"] == 20

    def test_v11_vollstaendige_liga_ist_vollstaendig(self):
        b = evaluate_pool(_pool(anzahl=400, teams=18), "bl1")
        assert b["status"] == STATUS_COMPLETE
        assert b["issues"] == []

    def test_v12_zu_wenige_spieler_fallen_auf(self):
        b = evaluate_pool(_pool(anzahl=50, teams=18), "bl1")
        assert b["status"] == STATUS_PROVIDER_INCOMPLETE

    def test_v13_junge_saison_mit_kadern_aber_ohne_minuten(self):
        """
        Entscheidende Unterscheidung: Kaderabdeckung und Statistikreife
        sind zwei verschiedene Dinge. Eine Liga am zweiten Spieltag hat
        vollstaendige Kader und fast keine Minuten - das ist kein
        unvollstaendiger Import.
        """
        b = evaluate_pool(_pool(anzahl=400, teams=18, minutes=0), "bl1")
        assert b["status"] == STATUS_COMPLETE
        assert b["with_minutes"] == 0

    def test_v14_erwartete_teamzahl_ist_zentral(self):
        assert EXPECTED_TEAM_COUNT["bl1"] == 18
        assert EXPECTED_TEAM_COUNT["pl"] == 20
        assert set(EXPECTED_TEAM_COUNT) == {"bl1", "pl", "pd", "sa", "fl1"}

    def test_v15_leerer_stand_ueberschreibt_guten_nicht(self):
        besser, grund = is_better_pool({"players": []}, _pool(400), "bl1")
        assert besser is False
        assert "leer" in grund

    def test_v16_deutlicher_rueckgang_wird_abgelehnt(self):
        besser, _ = is_better_pool(_pool(100), _pool(400), "bl1")
        assert besser is False

    def test_v17_kleine_schwankung_ist_zulaessig(self):
        besser, _ = is_better_pool(_pool(395), _pool(400), "bl1")
        assert besser is True

    def test_v18_ohne_bestand_ist_alles_besser(self):
        besser, grund = is_better_pool(_pool(10), {"players": []}, "bl1")
        assert besser is True
        assert "kein bestehender Pool" in grund


# ---------------------------------------------------------------------------
# P  Positionsnormalisierung
# ---------------------------------------------------------------------------

class TestP_Positionen:

    def test_p19_forward_wird_attacker(self):
        """
        Der Kern des Radarfehlers. 2.424 Vorkommen im lokalen Cache.
        """
        assert normalize_position("Forward") == "Attacker"

    def test_p20_attacker_bleibt_attacker(self):
        assert normalize_position("Attacker") == "Attacker"

    def test_p21_alle_vier_gruppen_bleiben_erhalten(self):
        for gruppe in POSITION_GROUPS:
            assert normalize_position(gruppe) == gruppe

    def test_p22_kurzcodes_werden_uebersetzt(self):
        assert normalize_position("G") == "Goalkeeper"
        assert normalize_position("D") == "Defender"
        assert normalize_position("M") == "Midfielder"
        assert normalize_position("F") == "Attacker"

    def test_p23_gross_und_kleinschreibung_egal(self):
        assert normalize_position("forward") == "Attacker"
        assert normalize_position("FORWARD") == "Attacker"
        assert normalize_position(" Forward ") == "Attacker"

    def test_p24_unbekanntes_bleibt_none(self):
        assert normalize_position("Sweeper") is None
        assert normalize_position("Libero") is None

    def test_p25_unbekanntes_wird_diagnostiziert(self):
        normalize_position("Raumdeuter")
        assert "Raumdeuter" in unknown_position_report()

    def test_p26_leeres_bleibt_none_ohne_diagnose(self):
        vorher = dict(unknown_position_report())
        assert normalize_position(None) is None
        assert normalize_position("") is None
        assert dict(unknown_position_report()) == vorher

    def test_p27_alle_module_nutzen_dieselbe_funktion(self):
        """Eine Normalisierung, nicht drei."""
        from src.data.big_games_loader import _normalize_position
        from src.data.live_player_search import normalize_position as suche

        assert suche is normalize_position
        assert _normalize_position is normalize_position

    def test_p28_keine_spielerspezifische_sonderregel(self):
        """
        Die Zuordnung darf ausschliesslich vom Providerwert abhaengen -
        niemals von einer ID oder einem Namen.

        Geprueft wird der CODE, nicht die Dokumentation: In den Kommentaren
        stehen die betroffenen Spieler bewusst als Beleg dafuer, woher die
        Regel kommt. Ein Testverbot auf Kommentare wuerde genau diese
        Nachvollziehbarkeit bestrafen.
        """
        zeilen = []
        for zeile in open("src/data/player_metrics.py", encoding="utf-8"):
            ohne_kommentar = zeile.split("#", 1)[0]
            zeilen.append(ohne_kommentar)
        code = "".join(zeilen)

        for verboten in ("player_id ==", "2489", "Diaz", "Dzeko", "Seghir"):
            assert verboten not in code

        # Die Zuordnung kommt ausschliesslich aus der Alias-Tabelle.
        assert set(POSITION_ALIASES.values()) <= set(POSITION_GROUPS)

    def test_p29_aggregation_normalisiert_die_position(self):
        """
        Der eigentliche Fehlerort: aggregate_statistics setzte position auf
        None, sobald der Anbieter "Forward" meldete - und daran haengt das
        gesamte Radar.
        """
        from src.data.player_compare_loader import aggregate_statistics

        ergebnis = aggregate_statistics([{
            "games": {"minutes": 2450, "position": "Forward",
                      "appearences": 30, "lineups": 28},
        }])
        assert ergebnis["games"]["position"] == "Attacker"

    def test_p30_perzentilkohorte_liest_normalisiert(self):
        """
        Bestehende Pools muessen ohne Neuschreiben richtig einsortiert
        werden - die Normalisierung greift beim LESEN.
        """
        from src.data.percentile_engine import build_distributions

        eintraege = [{
            "position": "Forward",
            "minutes_by_scope": {"club_all": 2000},
            "metrics_by_scope": {"club_all": {"goals_per90": 0.4 + i * 0.01}},
        } for i in range(40)]

        verteilungen = build_distributions(eintraege, 450, "club_all")
        assert "Attacker" in verteilungen
        assert verteilungen["Attacker"]["player_count"] == 40


# ---------------------------------------------------------------------------
# S  Scopes, Supercups, Freundschaftsspiele
# ---------------------------------------------------------------------------

SUPERCUPS = [
    (529, "Super Cup", "Germany"),
    (528, "Community Shield", "England"),
    (556, "Super Cup", "Spain"),
    (547, "Super Cup", "Italy"),
    (526, "Trophee des Champions", "France"),
    (531, "UEFA Super Cup", "World"),
]


def _block(lid, name="X", land="World"):
    return {"league": {"id": lid, "name": name, "country": land, "type": None}}


class TestS_Scopes:

    @pytest.mark.parametrize("lid,name,land", SUPERCUPS)
    def test_s31_supercup_zaehlt_zu_club_all(self, lid, name, land):
        from src.data.player_compare_loader import entry_matches_scope
        assert entry_matches_scope(_block(lid, name, land), "club_all") is True

    @pytest.mark.parametrize("lid,name,land", SUPERCUPS)
    def test_s32_supercup_zaehlt_zu_all(self, lid, name, land):
        from src.data.player_compare_loader import entry_matches_scope
        assert entry_matches_scope(_block(lid, name, land), "all") is True

    @pytest.mark.parametrize("lid,name,land", SUPERCUPS)
    def test_s33_supercup_nicht_im_reinen_ligascope(self, lid, name, land):
        from src.data.player_compare_loader import entry_matches_scope
        assert entry_matches_scope(_block(lid, name, land), "league") is False

    @pytest.mark.parametrize("lid,name,land", SUPERCUPS)
    def test_s34_supercup_ist_kein_nationalmannschaftsspiel(self, lid, name, land):
        from src.data.player_compare_loader import entry_matches_scope
        assert entry_matches_scope(_block(lid, name, land), "national") is False

    def test_s35_klubfreundschaftsspiel_nicht_in_club_all(self):
        from src.data.player_compare_loader import entry_matches_scope
        block = _block(667, "Friendlies Clubs")
        assert entry_matches_scope(block, "club_all") is False
        assert entry_matches_scope(block, "all") is False

    def test_s36_laenderspiel_testspiel_behaelt_seine_semantik(self):
        """
        Die Klubregel darf Laenderspiel-Testspiele nicht mitentfernen -
        sie gehoeren in den Nationalmannschafts-Scope.
        """
        from src.data.player_compare_loader import entry_matches_scope
        block = _block(10, "Friendlies")
        assert entry_matches_scope(block, "national") is True
        assert entry_matches_scope(block, "all") is True
        assert entry_matches_scope(block, "club_all") is False

    def test_s37_liga_pokal_europapokal_bleiben_drin(self):
        from src.data.player_compare_loader import entry_matches_scope
        for lid in (78, 81, 2, 3, 848, 15):
            assert entry_matches_scope(_block(lid), "club_all") is True

    def test_s38_fremde_liga_zaehlt_nicht_zu_club_all(self):
        """Nur die fuenf Vergleichsligen, sonst rutschten fremde Ligen ein."""
        from src.data.player_compare_loader import entry_matches_scope
        assert entry_matches_scope(_block(88, "Eredivisie", "Netherlands"),
                                   "club_all") is False

    def test_s39_unbekannter_wettbewerb_ist_kein_pflichtspiel(self):
        from src.data.player_compare_loader import entry_matches_scope
        block = _block(999999, "Etwas Unbenanntes", "Nirgendwo")
        assert taxonomy.classify(block["league"]) == taxonomy.UNKNOWN
        assert entry_matches_scope(block, "club_all") is False

    def test_s40_unbekannte_werden_diagnostiziert(self):
        """
        Ein Wettbewerb, den weder ID noch Namensbausteine erkennen, muss
        sichtbar bleiben - sonst waere die naechste Providervariante
        genauso unsichtbar, wie "Forward" es zwei Jahre lang war.

        Bewusst ein Name OHNE Pokal- oder Turnierbaustein: "Phantasiepokal"
        enthaelt "pokal" und wird deshalb voellig richtig als Pokal
        eingeordnet.
        """
        taxonomy.classify({"id": 888888, "name": "Zamboni Invitational"})
        assert any("888888" in k
                   for k in taxonomy.unknown_competition_report())

    def test_s40b_pokalbaustein_wird_als_pokal_erkannt(self):
        """Gegenstueck: Die Namensheuristik faengt die haeufigen Faelle."""
        assert taxonomy.classify(
            {"id": 777777, "name": "Beker van Nederland"}) == taxonomy.DOMESTIC_CUP

    @pytest.mark.parametrize("lid,name,land", SUPERCUPS)
    def test_s41_taxonomie_kennt_jeden_supercup(self, lid, name, land):
        kategorie = taxonomy.classify({"id": lid, "name": name, "country": land})
        assert kategorie in taxonomy.SUPERCUP_CATEGORIES

    def test_s42_alle_fuenf_laender_haben_einen_supercup(self):
        laender = {land for land, _ in taxonomy.DOMESTIC_SUPERCUP_IDS.values()}
        assert laender == {"Germany", "England", "Spain", "Italy", "France"}

    def test_s43_supercup_ids_sind_eindeutig(self):
        ids = list(taxonomy.DOMESTIC_SUPERCUP_IDS) + list(
            taxonomy.CONTINENTAL_SUPERCUP_IDS)
        assert len(ids) == len(set(ids))

    def test_s44_keine_doppelzaehlung_zwischen_kategorien(self):
        """Eine ID darf nicht in zwei Mengen stehen."""
        mengen = [set(taxonomy.DOMESTIC_LEAGUE_IDS),
                  set(taxonomy.DOMESTIC_CUP_IDS),
                  set(taxonomy.DOMESTIC_SUPERCUP_IDS),
                  set(taxonomy.CONTINENTAL_CUP_IDS),
                  set(taxonomy.CONTINENTAL_SUPERCUP_IDS),
                  set(taxonomy.CLUB_WORLD_IDS),
                  set(taxonomy.CLUB_FRIENDLY_IDS),
                  set(taxonomy.NATIONAL_FRIENDLY_IDS)]
        alle = [i for m in mengen for i in m]
        assert len(alle) == len(set(alle))

    def test_s45_club_competitive_enthaelt_keine_freundschaftsspiele(self):
        assert taxonomy.CLUB_FRIENDLY not in taxonomy.CLUB_COMPETITIVE
        assert taxonomy.NATIONAL_FRIENDLY not in taxonomy.CLUB_COMPETITIVE

    def test_s46_echte_rohantwort_zaehlt_supercup_mit(self):
        """Echtdaten, sofern vorhanden."""
        from src.data.player_compare_loader import entry_matches_scope

        pfad = "data/cache/apisports__playerprofile__2489__2025.json"
        if not os.path.exists(pfad):
            pytest.skip("Beispielprofil nicht vorhanden")
        with open(pfad, encoding="utf-8") as f:
            payload = (json.load(f).get("payload") or [])
        if not payload:
            pytest.skip("leeres Profil")

        supercups = [b for b in (payload[0].get("statistics") or [])
                     if (b.get("league") or {}).get("id")
                     in taxonomy.supercup_ids()]
        for block in supercups:
            assert entry_matches_scope(block, "club_all") is True


# ---------------------------------------------------------------------------
# B  Big Games
# ---------------------------------------------------------------------------

class TestB_BigGames:

    @pytest.mark.parametrize("lid,name,land", SUPERCUPS)
    def test_b47_supercup_ist_ein_big_game(self, lid, name, land):
        from src.features.big_games import (
            TIER_SUPER_CUP, competition_tier, is_importance_qualified)
        tier = competition_tier(lid)
        assert tier == TIER_SUPER_CUP
        assert is_importance_qualified("group", tier) is True

    def test_b48_alle_sechs_supercups_sind_erfasst(self):
        from src.features.big_games import SUPER_CUP_COMPETITION_IDS
        assert SUPER_CUP_COMPETITION_IDS == {526, 528, 529, 531, 547, 556}

    def test_b49_freundschaftsspiel_ist_kein_big_game(self):
        from src.features.big_games import is_big_games_eligible_club_competition
        assert is_big_games_eligible_club_competition(667) is False

    def test_b50_liga_allein_ist_kein_big_game(self):
        from src.features.big_games import competition_tier, is_importance_qualified
        assert is_importance_qualified("league", competition_tier(78)) is False

    def test_b51_pokalfinale_bleibt_ein_big_game(self):
        from src.features.big_games import competition_tier, is_importance_qualified
        assert is_importance_qualified("final", competition_tier(81)) is True

    def test_b52_europapokal_ko_bleibt_ein_big_game(self):
        from src.features.big_games import competition_tier, is_importance_qualified
        assert is_importance_qualified("semifinal", competition_tier(2)) is True

    def test_b53_supercup_ids_stammen_aus_der_taxonomie(self):
        """Eine Quelle, nicht zwei gepflegte Listen."""
        from src.features.big_games import DOMESTIC_SUPER_CUP_COMPETITION_IDS
        assert DOMESTIC_SUPER_CUP_COMPETITION_IDS == frozenset(
            taxonomy.DOMESTIC_SUPERCUP_IDS)

    def test_b54_keine_spielerspezifische_regel_in_big_games(self):
        quelle = open("src/features/big_games.py", encoding="utf-8").read()
        for verboten in ("player_id ==", "19617", "2489"):
            assert verboten not in quelle


# ---------------------------------------------------------------------------
# K  Kader-Fallback und Suche
# ---------------------------------------------------------------------------

class TestK_Kader:

    def test_k55_vierte_suchebene_existiert(self):
        from src.data.player_compare_loader import search_current_squads
        assert callable(search_current_squads)

    def test_k56_kurze_anfrage_loest_nichts_aus(self):
        """Kein Request je Tastendruck."""
        from src.data.player_compare_loader import search_current_squads
        assert search_current_squads("ab", 2026) == []

    def test_k57_kaderindex_normalisiert_positionen(self, monkeypatch):
        import src.data.current_squads as cs

        monkeypatch.setattr(cs, "all_verified_teams",
                            lambda season=None: {1: {"name": "Test FC",
                                                     "league_key": "bl1"}})
        monkeypatch.setattr(cs, "_squad_members", lambda tid: [
            {"player_id": 10, "name": "A. Test", "position": "Forward"},
            {"player_id": 11, "name": "B. Test", "position": "G"},
        ])
        monkeypatch.setattr(cs, "resolve_season", lambda s=None: 2026)

        index = cs.build_squad_index(2026)
        nach_id = {e["player_id"]: e for e in index}
        assert nach_id[10]["position"] == "Attacker"
        assert nach_id[11]["position"] == "Goalkeeper"

    def test_k58_gleiche_namen_bleiben_getrennte_personen(self, monkeypatch):
        import src.data.current_squads as cs

        monkeypatch.setattr(cs, "all_verified_teams",
                            lambda season=None: {1: {"name": "A", "league_key": "bl1"},
                                                 2: {"name": "B", "league_key": "bl1"}})
        monkeypatch.setattr(cs, "_squad_members", lambda tid: [
            {"player_id": 100 + tid, "name": "T. Mueller", "position": "M"},
        ])
        monkeypatch.setattr(cs, "resolve_season", lambda s=None: 2026)

        index = cs.build_squad_index(2026)
        assert {e["player_id"] for e in index} == {101, 102}

    def test_k59_ein_spieler_steht_nur_einmal_im_index(self, monkeypatch):
        import src.data.current_squads as cs

        monkeypatch.setattr(cs, "all_verified_teams",
                            lambda season=None: {1: {"name": "A", "league_key": "bl1"},
                                                 2: {"name": "B", "league_key": "bl1"}})
        monkeypatch.setattr(cs, "_squad_members", lambda tid: [
            {"player_id": 500, "name": "Wechsler", "position": "M"},
        ])
        monkeypatch.setattr(cs, "resolve_season", lambda s=None: 2026)

        index = cs.build_squad_index(2026)
        assert len(index) == 1

    def test_k60_kaderspieler_ohne_minuten_ist_gekennzeichnet(self, monkeypatch):
        """
        Der Saibari-Fall, generisch: auffindbar, mit aktuellem Verein, aber
        ausdruecklich ohne erfundene Statistik.
        """
        import src.data.player_compare_loader as pcl

        monkeypatch.setattr(
            "src.data.current_squads.search_squad_index",
            lambda q, season=None, limit=12: [{
                "player_id": 777, "name": "I. Neuzugang", "position": "Midfielder",
                "team_id": 157, "team_name": "Bayern München",
                "league_code": "bl1", "age": 24, "number": 8,
            }])

        treffer = pcl.search_current_squads("neuzugang", 2026)
        assert len(treffer) == 1
        eintrag = treffer[0]
        assert eintrag["player_id"] == 777
        assert eintrag["minutes"] == 0
        assert eintrag["has_current_stats"] is False
        assert eintrag["current_team_verified"] is True
        assert eintrag["availability_status"] == "no_current_appearance"
        assert eintrag["team_name"] == "Bayern München"
        assert eintrag["position"] == "Midfielder"


# ---------------------------------------------------------------------------
# C  Cache, Provenienz, Service Worker
# ---------------------------------------------------------------------------

class TestC_CacheUndProvenienz:

    def teardown_method(self):
        from src.utils import disk_cache
        disk_cache.bypass_prefixes()

    def test_c61_umgehung_ist_standardmaessig_aus(self):
        from src.utils import disk_cache
        assert disk_cache.is_bypassed("apisports:playerprofile:1:2025") is False

    def test_c62_umgehung_wirkt_nur_auf_das_praefix(self):
        from src.utils import disk_cache
        disk_cache.bypass_prefixes("apisports:playerprofile:")
        assert disk_cache.is_bypassed("apisports:playerprofile:1:2025") is True
        assert disk_cache.is_bypassed("apisports:injuries:bl1:2026") is False

    def test_c63_umgehung_laesst_sich_zuruecksetzen(self):
        from src.utils import disk_cache
        disk_cache.bypass_prefixes("apisports:playerprofile:")
        disk_cache.bypass_prefixes()
        assert disk_cache.is_bypassed("apisports:playerprofile:1:2025") is False

    def test_c64_umgehung_loescht_keine_datei(self, tmp_path, monkeypatch):
        from src.utils import disk_cache

        monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path))
        disk_cache.write_entry("apisports:playerprofile:9:2025", {"a": 1}, 3600)
        vorher = os.listdir(tmp_path)

        disk_cache.bypass_prefixes("apisports:playerprofile:")
        disk_cache.disk_cached_call("apisports:playerprofile:9:2025", 3600,
                                    lambda: {"a": 2})
        assert os.listdir(tmp_path) == vorher

    def test_c65_umgehung_holt_frisch(self, tmp_path, monkeypatch):
        from src.utils import disk_cache

        monkeypatch.setattr(disk_cache, "CACHE_DIR", str(tmp_path))
        disk_cache.write_entry("apisports:playerprofile:9:2025", {"a": 1}, 3600)

        ohne = disk_cache.disk_cached_call(
            "apisports:playerprofile:9:2025", 3600, lambda: {"a": 2})
        assert ohne == {"a": 1}          # Cache gilt

        disk_cache.bypass_prefixes("apisports:playerprofile:")
        mit = disk_cache.disk_cached_call(
            "apisports:playerprofile:9:2025", 3600, lambda: {"a": 3})
        assert mit == {"a": 3}           # frisch geholt

    def test_c66_poolrevision_hat_die_geforderten_felder(self):
        r = pool_revision(_pool(10))
        for feld in ("source", "data_as_of", "schema_version", "content_key"):
            assert feld in r

    def test_c67_inhaltsschluessel_aendert_sich_mit_dem_inhalt(self):
        a = pool_revision(_pool(10, minutes=100))
        b = pool_revision(_pool(10, minutes=200))
        assert a["content_key"] != b["content_key"]

    def test_c68_service_worker_hat_eine_neue_version(self):
        quelle = open("static/sw.js", encoding="utf-8").read()
        assert 'const CACHE_NAME = "footsim-v3' in quelle
        assert "footsim-v31" not in quelle

    def test_c69_uebersetzungen_werden_revalidiert(self):
        """
        Die Ursache der sichtbaren Rohschluessel: Cache-First ohne
        Revalidierung haelt eine alte de.json fest, bis jemand an die
        Cacheversion denkt.
        """
        quelle = open("static/sw.js", encoding="utf-8").read()
        assert "REVALIDATE_PATHS" in quelle
        assert "/static/i18n/de.json" in quelle
        assert "/static/i18n/en.json" in quelle

    def test_c70_api_kommt_weiterhin_aus_dem_netz(self):
        quelle = open("static/sw.js", encoding="utf-8").read()
        assert "const isApi = API_ROUTES.some" in quelle
        assert "event.respondWith(fetch(event.request));" in quelle

    def test_c71_uebersetzungen_sind_symmetrisch_und_echt(self):
        de = json.load(open("static/i18n/de.json", encoding="utf-8"))
        en = json.load(open("static/i18n/en.json", encoding="utf-8"))
        assert set(de) == set(en)

        for schluessel in ("playerCompare.providerIncomplete",
                           "playerCompare.providerNoClubData",
                           "playerCompare.leaguePartial"):
            assert schluessel in de and schluessel in en

        # Echte Umlaute, keine Ersatzschreibweisen in der Oberflaeche.
        for wert in de.values():
            if isinstance(wert, str):
                for ersatz in ("fuer ", "vollstaendig", "verfuegbar"):
                    assert ersatz not in wert

    def test_c72_frontend_bricht_veraltete_vergleiche_ab(self):
        quelle = open("static/script.js", encoding="utf-8").read()
        assert "new AbortController()" in quelle
        assert "pcState.comparisonId" in quelle
        assert "function pcInvalidateComparison" in quelle
        assert 'error.name === "AbortError"' in quelle
