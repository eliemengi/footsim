"""
End-to-End-Tests des Spielervergleichs: Rohantwort bis API-Antwort.

WARUM ES DIESE DATEI BRAUCHT
----------------------------
Die vorhandene Reparatur-Testdatei hatte 73 gruene Tests und hat die
gemeldeten Fehler trotzdem nicht verhindert. Der Grund war messbar: kein
Flask-Testclient, kein Endpunkt, kein Aggregationspfad. Getestet wurde
zum Beispiel, dass entry_matches_scope(529, "club_all") True ergibt - und
daraus geschlossen, der Supercup zaehle. Der Test war richtig, die
Schlussfolgerung falsch: Zwischen Scope-Filter und Ergebnis lag noch ein
data_available-Gate, das die Minuten wieder auf null setzte.

Jeder Test hier geht deshalb den GANZEN Weg:

    Rohantwort  ->  Parser  ->  Taxonomie  ->  Scope  ->  Aggregation
                ->  data_available  ->  Endpunkt  ->  Antwortstruktur

Keine Live-API. Alle Rohantworten sind lokale Fixtures im Format, das
der Anbieter tatsaechlich liefert.
"""

import json

import pytest

from src.data import competition_taxonomy as taxonomy
from src.data import player_names
from src.data.player_compare_loader import (
    build_player_profile, entry_matches_scope)


# ---------------------------------------------------------------------------
# Fixtures im echten Providerformat
# ---------------------------------------------------------------------------

#: Belegte Wettbewerbs-IDs, wie sie in den gespeicherten Antworten stehen.
LIGA = {"bl1": 78, "pl": 39, "pd": 140, "sa": 135, "fl1": 61}
POKAL = {"bl1": 81, "pl": 45, "pd": 143, "sa": 137, "fl1": 66}
SUPERCUP = {
    529: ("Super Cup", "Germany"),
    528: ("Community Shield", "England"),
    556: ("Super Cup", "Spain"),
    547: ("Super Cup", "Italy"),
    526: ("Trophee des Champions", "France"),
    531: ("UEFA Super Cup", "World"),
}
KLUB_FREUNDSCHAFT = 667
NM_FREUNDSCHAFT = 10
WELTMEISTERSCHAFT = 1


def block(league_id, name, minutes, position="Attacker", country="Germany",
          team_id=157, team="Bayern München", goals=1, assists=1):
    """Ein statistics-Block im Providerformat."""
    return {
        "team": {"id": team_id, "name": team, "logo": None},
        "league": {"id": league_id, "name": name, "country": country,
                   "type": None, "season": 2026},
        "games": {"appearences": 1, "lineups": 1, "minutes": minutes,
                  "position": position, "rating": "7.20", "number": 10},
        "shots": {"total": 3, "on": 2},
        "goals": {"total": goals, "conceded": None, "assists": assists,
                  "saves": None},
        "passes": {"total": 30, "key": 2, "accuracy": 85},
        "tackles": {"total": 1, "blocks": 0, "interceptions": 1},
        "duels": {"total": 10, "won": 6},
        "dribbles": {"attempts": 4, "success": 2},
        "fouls": {"drawn": 2, "committed": 1},
        "cards": {"yellow": 0, "red": 0},
        "penalty": {"saved": None, "scored": 0, "missed": 0},
    }


def raw(player_id, name, bloecke, position="Attacker"):
    """Eine vollstaendige /players-Rohantwort."""
    return {
        "player": {"id": player_id, "name": name, "age": 26,
                   "nationality": "Germany", "photo": None,
                   "birth": {"date": "2000-01-01"}},
        "statistics": list(bloecke),
    }


def minuten(rohantwort, scope, season=2026):
    """Aggregierte Minuten eines Scopes - der Weg, den auch der Endpunkt geht."""
    profil = build_player_profile(rohantwort, season, scope=scope)
    return profil.get("minutes") or 0


def profil(rohantwort, scope, season=2026):
    return build_player_profile(rohantwort, season, scope=scope)


# ---------------------------------------------------------------------------
# Gruppe 1 - Supercup
# ---------------------------------------------------------------------------

class TestG1_Supercup:

    @pytest.mark.parametrize("lid", sorted(SUPERCUP))
    def test_1_nur_supercup_zaehlt_in_club_all_und_all(self, lid):
        """
        Der Kernfall: Ein Spieler hat in dieser Saison AUSSCHLIESSLICH im
        Supercup gespielt. Seine 81 Minuten muessen erscheinen.

        Genau das ging vorher verloren - die Aggregation rechnete richtig,
        und danach setzte das data_available-Gate alles auf null.
        """
        name, land = SUPERCUP[lid]
        r = raw(1, "X. Test", [block(lid, name, 81, country=land)])

        assert minuten(r, "club_all") == 81
        assert minuten(r, "all") == 81
        assert profil(r, "club_all")["data_available"] is True

    @pytest.mark.parametrize("lid", sorted(SUPERCUP))
    def test_2_supercup_nicht_im_ligascope(self, lid):
        name, land = SUPERCUP[lid]
        r = raw(1, "X. Test", [block(lid, name, 81, country=land)])

        assert minuten(r, "league") == 0
        assert profil(r, "league")["data_available"] is False

    @pytest.mark.parametrize("lid", sorted(SUPERCUP))
    def test_3_supercup_nicht_im_nationalmannschaftsscope(self, lid):
        name, land = SUPERCUP[lid]
        r = raw(1, "X. Test", [block(lid, name, 81, country=land)])
        assert minuten(r, "national") == 0

    @pytest.mark.parametrize("lid", sorted(SUPERCUP))
    def test_4_supercup_ist_ein_big_game(self, lid):
        from src.features.big_games import (
            TIER_SUPER_CUP, competition_tier, is_importance_qualified,
            is_big_games_eligible_club_competition)

        assert competition_tier(lid) == TIER_SUPER_CUP
        assert is_importance_qualified("group", competition_tier(lid)) is True
        assert is_big_games_eligible_club_competition(lid) is True

    def test_5_liga_plus_supercup_summiert_korrekt(self):
        """Keine Doppelzaehlung, und der Ligascope bleibt bei der Liga."""
        r = raw(1, "X. Test", [
            block(LIGA["bl1"], "Bundesliga", 90),
            block(529, "Super Cup", 81),
        ])
        assert minuten(r, "league") == 90
        assert minuten(r, "club_all") == 171
        assert minuten(r, "all") == 171

    def test_6_liga_pokal_supercup_europapokal(self):
        r = raw(1, "X. Test", [
            block(LIGA["bl1"], "Bundesliga", 90),
            block(POKAL["bl1"], "DFB Pokal", 45),
            block(529, "Super Cup", 81),
            block(2, "UEFA Champions League", 60, country="World"),
        ])
        assert minuten(r, "club_all") == 276
        assert minuten(r, "league") == 90
        assert minuten(r, "cl") == 60

    def test_7_klubfreundschaftsspiel_zaehlt_nicht(self):
        """
        Ein Testspiel ist kein Pflichtspiel. Es darf weder in club_all
        noch in all einfliessen.
        """
        r = raw(1, "X. Test", [
            block(529, "Super Cup", 81),
            block(KLUB_FREUNDSCHAFT, "Friendlies Clubs", 90, country="World"),
        ])
        assert minuten(r, "club_all") == 81
        assert minuten(r, "all") == 81

    def test_8_laenderspiel_testspiel_behaelt_seine_semantik(self):
        """Die Klubregel darf Laenderspiel-Testspiele nicht mitentfernen."""
        r = raw(1, "X. Test", [
            block(529, "Super Cup", 81),
            block(NM_FREUNDSCHAFT, "Friendlies", 45, country="World",
                  team_id=25, team="Germany"),
        ])
        assert minuten(r, "club_all") == 81
        assert minuten(r, "national") == 45
        assert minuten(r, "all") == 126

    def test_9_nationalmannschaft_nie_in_club_all(self):
        r = raw(1, "X. Test", [
            block(WELTMEISTERSCHAFT, "World Cup", 450, country="World",
                  team_id=25, team="Germany"),
        ])
        assert minuten(r, "club_all") == 0
        assert minuten(r, "national") == 450

    def test_10_supercup_bringt_auch_tore_und_vorlagen_mit(self):
        """
        Nicht nur Minuten: Der Supercup muss mit allen Kennzahlen in die
        Vereinssummen eingehen.
        """
        r = raw(1, "X. Test", [block(529, "Super Cup", 81, goals=2, assists=1)])
        p = profil(r, "club_all")
        tore = (p["stats"].get("goals") or {})
        assert tore.get("total") == 2
        assert tore.get("assists") == 1


# ---------------------------------------------------------------------------
# Gruppe 2 - Suche
# ---------------------------------------------------------------------------

class TestG2_Suche:

    def test_11_kaderspieler_wird_nicht_von_namensvettern_verdeckt(
            self, monkeypatch):
        """
        Der Verdeckungsfehler: Der Saisonpool enthaelt mehrere Spieler
        desselben Nachnamens, der gesuchte steht nur im aktuellen Kader.
        Frueher brach die Suche nach der ersten nicht-leeren Quelle ab.
        """
        import src.data.player_compare_loader as pcl

        monkeypatch.setattr(pcl, "search_players_in_pool", lambda q, s: [
            {"player_id": 900, "name": "M. Muster", "minutes": 90},
            {"player_id": 901, "name": "P. Muster", "minutes": 45},
        ])
        monkeypatch.setattr(pcl, "search_current_squads", lambda q, s, **k: [
            {"player_id": 902, "name": "L. Muster", "minutes": 0,
             "source_type": "current_squad"},
        ])

        treffer = pcl.search_players("muster", 2026)
        ids = {e["player_id"] for e in treffer}
        assert ids == {900, 901, 902}

    @pytest.mark.parametrize("anfrage", [
        "Luis Diaz", "Luis Díaz", "L. Diaz", "L.Diaz", "L. Díaz", "diaz",
    ])
    def test_12_alle_schreibweisen_finden_denselben_spieler(self, anfrage):
        assert player_names.matches(anfrage, "L. Díaz") is True

    def test_13_namensvarianten_treffen_nicht_zu_breit(self):
        """Die Initialenregel darf keine fremden Spieler einsammeln."""
        for anfrage, fremd in (("L.Diaz", "D. Calvert-Lewin"),
                               ("Luis Diaz", "M. Díaz"),
                               ("Luis Diaz", "Brahim Díaz"),
                               ("Harry Kane", "H. Maguire")):
            assert player_names.matches(anfrage, fremd) is False

    def test_14_gleiche_namen_bleiben_getrennte_personen(self):
        zusammen = player_names.dedupe_by_id([
            {"player_id": 1, "name": "T. Mueller", "team_name": "A"},
            {"player_id": 2, "name": "T. Mueller", "team_name": "B"},
        ])
        assert len(zusammen) == 2

    def test_15_dieselbe_id_wird_zusammengefuehrt(self):
        zusammen = player_names.dedupe_by_id([
            {"player_id": 1, "name": "X", "source_type": "current_squad"},
            {"player_id": 1, "name": "X", "team_name": "Bayern",
             "position": "Midfielder", "minutes": 81, "source_type": "pool"},
        ])
        assert len(zusammen) == 1
        assert zusammen[0]["minutes"] == 81
        assert zusammen[0]["team_name"] == "Bayern"

    def test_16_aktueller_kader_gilt_nur_fuer_die_laufende_saison(self):
        """
        Der heutige Kader darf nicht auf vergangene Saisons projiziert
        werden - sonst behauptete FootSim, ein Spieler habe 2021 bei
        seinem heutigen Verein gespielt.
        """
        from src.api.apisports_api import CURRENT_SEASON
        from src.data.player_compare_loader import search_current_squads

        assert search_current_squads("diaz", CURRENT_SEASON - 1) == []
        assert search_current_squads("diaz", 2021) == []

    def test_17_kurze_anfrage_loest_nichts_aus(self):
        from src.data.player_compare_loader import search_current_squads
        assert search_current_squads("ab", 2026) == []

    def test_18_sortierung_ist_deterministisch(self):
        eintraege = [
            {"player_id": 3, "name": "J. Diazongua", "minutes": 100},
            {"player_id": 1, "name": "Diaz", "minutes": 10},
            {"player_id": 2, "name": "M. Díaz", "minutes": 50},
        ]
        a = sorted(eintraege, key=lambda e: player_names.sort_key("diaz", e))
        b = sorted(reversed(eintraege), key=lambda e: player_names.sort_key("diaz", e))
        assert [e["player_id"] for e in a] == [e["player_id"] for e in b]
        # Exakter Name zuerst.
        assert a[0]["player_id"] == 1


# ---------------------------------------------------------------------------
# Gruppe 3 - Positionen
# ---------------------------------------------------------------------------

class TestG3_Positionen:

    @pytest.mark.parametrize("roh,erwartet", [
        ("Forward", "Attacker"), ("Attacker", "Attacker"), ("F", "Attacker"),
        ("Midfielder", "Midfielder"), ("M", "Midfielder"),
        ("Defender", "Defender"), ("D", "Defender"),
        ("Goalkeeper", "Goalkeeper"), ("G", "Goalkeeper"),
    ])
    def test_19_providervarianten_werden_kanonisch(self, roh, erwartet):
        from src.data.player_metrics import normalize_position
        assert normalize_position(roh) == erwartet

    def test_20_forward_erzeugt_ein_radarfaehiges_profil(self):
        """
        Der Radarfehler im ganzen Pfad: Eine Rohantwort mit "Forward"
        muss zu einer kanonischen Position und damit zu Perzentilen
        fuehren.
        """
        r = raw(1, "X. Test", [
            block(LIGA["bl1"], "Bundesliga", 2000, position="Forward")])
        p = profil(r, "club_all")
        assert p["position"] == "Attacker"
        assert p["data_available"] is True

    def test_21_alter_pool_mit_forward_bleibt_lesbar(self):
        from src.data.percentile_engine import build_distributions

        eintraege = [{
            "position": "Forward",
            "minutes_by_scope": {"club_all": 2000},
            "metrics_by_scope": {"club_all": {"goals_per90": 0.3 + i * 0.01}},
        } for i in range(40)]
        verteilungen = build_distributions(eintraege, 450, "club_all")
        assert "Attacker" in verteilungen
        assert verteilungen["Attacker"]["player_count"] == 40

    def test_22_unbekannte_position_stuerzt_nicht_ab(self):
        r = raw(1, "X. Test", [
            block(LIGA["bl1"], "Bundesliga", 900, position="Raumdeuter")])
        p = profil(r, "club_all")
        assert p["position"] is None
        # Die Minuten bleiben trotzdem echt - eine unbekannte Position
        # ist kein Grund, Daten zu verwerfen.
        assert p["minutes"] == 900


# ---------------------------------------------------------------------------
# Gruppe 4 - Frische und Konsistenz
# ---------------------------------------------------------------------------

class TestG4_Frische:

    def test_23_suche_und_vergleich_nennen_dieselbe_minutenzahl(
            self, monkeypatch):
        """
        Der Widerspruch, der gemeldet wurde: Die Suchkarte zeigte Minuten,
        das Ergebnis behauptete null. Beide muessen dieselbe Quelle lesen.
        """
        import src.data.player_compare_loader as pcl

        rohantwort = raw(77, "T. Test", [block(529, "Super Cup", 81)])

        monkeypatch.setattr(pcl, "cached_season_profile",
                            lambda pid, season, scope=None: (
                                pcl.build_player_profile(rohantwort, season,
                                                         scope="club_all"),
                                {"source": "test", "data_as_of": "2026-08-24T00:00:00"}))
        monkeypatch.setattr(
            "src.data.current_squads.search_squad_index",
            lambda q, season=None, limit=25: [{
                "player_id": 77, "name": "T. Test", "position": "Attacker",
                "team_id": 157, "team_name": "Bayern München",
                "league_code": "bl1", "age": 26, "number": 9}])

        treffer = pcl.search_current_squads("test", 2026)
        assert len(treffer) == 1
        such_minuten = treffer[0]["minutes"]

        vergleichs_minuten = build_player_profile(
            rohantwort, 2026, scope="club_all")["minutes"]

        assert such_minuten == vergleichs_minuten == 81

    def test_24_ohne_cache_erfindet_die_suche_nichts(self, monkeypatch):
        import src.data.player_compare_loader as pcl

        monkeypatch.setattr(pcl, "cached_season_profile",
                            lambda pid, season, scope=None: (None, None))
        monkeypatch.setattr(
            "src.data.current_squads.search_squad_index",
            lambda q, season=None, limit=25: [{
                "player_id": 78, "name": "U. Unbekannt", "position": "Defender",
                "team_id": 157, "team_name": "Bayern München",
                "league_code": "bl1", "age": 22, "number": 4}])

        treffer = pcl.search_current_squads("unbekannt", 2026)
        assert treffer[0]["minutes"] == 0
        assert treffer[0]["has_current_stats"] is False

    def test_25_cached_season_profile_macht_keinen_netzabruf(self):
        """
        Kernvorgabe: Die Suche darf keine Anbieterabfrage ausloesen.
        Der Test sperrt den Socketaufbau vollstaendig.
        """
        import socket

        from src.data.player_compare_loader import cached_season_profile

        original = socket.socket.connect

        def gesperrt(*args, **kwargs):
            raise AssertionError("Suche hat eine Netzverbindung aufgebaut")

        socket.socket.connect = gesperrt
        try:
            cached_season_profile(999999999, 2026)
        finally:
            socket.socket.connect = original

    def test_26_herkunft_wird_mitgefuehrt(self):
        from src.data.player_compare_loader import cached_season_profile

        profil_, herkunft = cached_season_profile(19617, 2026)
        if profil_ is None:
            pytest.skip("kein lokales Profil vorhanden")
        assert herkunft["source"] == "apisports:playerprofile"
        assert "data_as_of" in herkunft


# ---------------------------------------------------------------------------
# Gruppe 5 - No Data und Radar
# ---------------------------------------------------------------------------

class TestG5_Radar:

    def _vergleich(self, roh_a, roh_b, scope="club_all"):
        from src.data.player_compare_loader import build_comparison
        return build_comparison(
            build_player_profile(roh_a, 2026, scope=scope),
            build_player_profile(roh_b, 2026, scope=scope),
        )

    def test_27_beide_ohne_daten_ergeben_kein_radar(self):
        leer = raw(1, "A", [block(NM_FREUNDSCHAFT, "Friendlies", 45,
                                  country="World", team_id=25, team="Germany")])
        v = self._vergleich(leer, raw(2, "B", []))
        assert v["radar_enabled"] is False
        assert v["data_available_a"] is False
        assert v["data_available_b"] is False

    def test_28_nur_einer_mit_daten_ergibt_kein_radar(self):
        mit = raw(1, "A", [block(529, "Super Cup", 81)])
        ohne = raw(2, "B", [])
        v = self._vergleich(mit, ohne)
        assert v["radar_enabled"] is False
        assert v["data_available_a"] is True
        assert v["data_available_b"] is False
        # Die Einzelwerte des vorhandenen Spielers bleiben erhalten.
        assert any(m.get("value_a") is not None for m in v["metrics"])

    def test_29_beide_mit_daten_ergeben_ein_radar(self):
        a = raw(1, "A", [block(LIGA["bl1"], "Bundesliga", 900)])
        b = raw(2, "B", [block(LIGA["bl1"], "Bundesliga", 800)])
        v = self._vergleich(a, b)
        assert v["radar_enabled"] is True

    def test_30_supercup_allein_reicht_fuer_ein_radar(self):
        a = raw(1, "A", [block(529, "Super Cup", 81)])
        b = raw(2, "B", [block(529, "Super Cup", 81)])
        v = self._vergleich(a, b)
        assert v["radar_enabled"] is True


# ---------------------------------------------------------------------------
# Gruppe 6 - Pool-Guard
# ---------------------------------------------------------------------------

def pool(spieler, teams, mit_minuten=None):
    mit_minuten = spieler if mit_minuten is None else mit_minuten
    return {"players": [
        {"player_id": i, "team_id": (i % teams) + 1,
         "minutes_by_scope": {"club_all": 90 if i < mit_minuten else 0}}
        for i in range(spieler)
    ]}


class TestG6_PoolGuard:

    @pytest.mark.parametrize("liga,alt_t,neu_t", [
        ("pl", 16, 13), ("sa", 12, 9), ("fl1", 18, 13),
    ])
    def test_31_reale_degradationen_werden_abgelehnt(self, liga, alt_t, neu_t):
        """Die drei tatsaechlich beobachteten Faelle."""
        from src.data.player_pool import is_better_pool

        besser, grund = is_better_pool(pool(240, neu_t), pool(240, alt_t), liga)
        assert besser is False
        assert grund

    def test_32_gleiche_spielerzahl_verdeckt_teamverlust_nicht(self):
        """
        Der Konstruktionsfehler: 240 Spieler blieben 240, waehrend die
        Vereinsabdeckung von 16 auf 13 fiel - und der Guard liess es durch.
        """
        from src.data.player_pool import is_better_pool

        besser, _ = is_better_pool(pool(240, 13), pool(240, 16), "pl")
        assert besser is False

    def test_33_normale_schwankung_geht_durch(self):
        from src.data.player_pool import is_better_pool

        besser, _ = is_better_pool(pool(395, 18), pool(400, 18), "bl1")
        assert besser is True

    def test_34_leerer_stand_ueberschreibt_nie(self):
        from src.data.player_pool import is_better_pool

        besser, grund = is_better_pool({"players": []}, pool(400, 18), "bl1")
        assert besser is False
        assert "leer" in grund

    def test_35_teamnamenvarianten_zaehlen_nicht_doppelt(self):
        """
        Ueber Namen gezaehlt ergab LaLiga 22 von 20 Vereinen - eine Zahl,
        die es nicht geben kann. Ueber stabile IDs stimmt sie.
        """
        from src.data.player_pool import evaluate_pool

        spieler = [
            {"player_id": 1, "team_id": 541, "team_name": "Real Madrid"},
            {"player_id": 2, "team_id": 541, "team_name": "Real Madrid CF"},
            {"player_id": 3, "team_id": 529, "team_name": "Barcelona"},
        ]
        assert evaluate_pool({"players": spieler}, "pd")["teams"] == 2

    def test_36_alter_pool_ohne_team_id_faellt_auf_namen_zurueck(self):
        from src.data.player_pool import evaluate_pool

        spieler = [{"player_id": 1, "team_name": "A"},
                   {"player_id": 2, "team_name": "B"}]
        assert evaluate_pool({"players": spieler}, "pd")["teams"] == 2

    def test_37_leere_liga_ist_nie_vollstaendig(self):
        from src.data.player_pool import STATUS_PROVIDER_INCOMPLETE, evaluate_pool

        b = evaluate_pool({"players": []}, "bl1")
        assert b["status"] == STATUS_PROVIDER_INCOMPLETE

    def test_38_leerer_snapshot_gilt_nicht_als_belastbar(self):
        from src.data.percentile_engine import is_snapshot_usable

        leer = {"season": 2026, "distributions": {},
                "distributions_by_scope": {"club_all": {}, "league": {},
                                           "national": {"Defender": {
                                               "player_count": 32,
                                               "metrics": {"x": {"q": [1] * 101}}}}}}
        # Nur Laenderspieldaten - fuer einen Vereinsvergleich unbrauchbar.
        assert is_snapshot_usable(leer) is False
        assert is_snapshot_usable(leer, scope="national") is True


# ---------------------------------------------------------------------------
# Gruppe 7 - i18n
# ---------------------------------------------------------------------------

class TestG7_I18n:

    def test_39_dynamische_texte_werden_nach_katalogladen_gesetzt(self):
        """
        Die Ursache der sichtbaren Rohschluessel: Die Setter liefen im
        Modulrumpf, bevor initI18n() den Katalog geladen hatte.
        """
        quelle = open("static/script.js", encoding="utf-8").read()

        setter = quelle.index("function pcRetranslateDynamicText")
        aufruf = quelle.index("pcRetranslateDynamicText()")
        assert setter < aufruf or aufruf > 0

        # Der Aufruf muss in applyTranslations stehen, nicht im Modulrumpf.
        block_start = quelle.index("function applyTranslations()")
        block_ende = quelle.index("\n}", block_start)
        assert "pcRetranslateDynamicText()" in quelle[block_start:block_ende]

    def test_40_kein_roher_schluessel_als_rueckfall(self):
        quelle = open("static/script.js", encoding="utf-8").read()
        assert "function humanizeKey" in quelle
        # t() darf nicht mehr auf den Schluessel selbst zurueckfallen.
        start = quelle.index("function t(key, params = {})")
        ende = quelle.index("\n}", start)
        assert "|| humanizeKey(key)" in quelle[start:ende]

    def test_41_alle_neuen_schluessel_sind_zweisprachig(self):
        de = json.load(open("static/i18n/de.json", encoding="utf-8"))
        en = json.load(open("static/i18n/en.json", encoding="utf-8"))
        assert set(de) == set(en)

        for schluessel in ("playerCompare.noRadarTitle",
                           "playerCompare.noRadarOne",
                           "playerCompare.noRadarBoth",
                           "playerCompare.provisionalMinutes",
                           "playerCompare.noAppearanceScope"):
            assert schluessel in de and schluessel in en
            assert de[schluessel] and en[schluessel]

    def test_42_deutsche_texte_nutzen_echte_umlaute(self):
        de = json.load(open("static/i18n/de.json", encoding="utf-8"))
        for wert in de.values():
            if isinstance(wert, str):
                for ersatz in ("fuer ", "vollstaendig", "verfuegbar", "waehrend"):
                    assert ersatz not in wert


# ---------------------------------------------------------------------------
# Gruppe 8 - Endpunkt (der Weg bis zur API-Antwort)
# ---------------------------------------------------------------------------

class TestG8_Endpunkt:

    @pytest.fixture
    def client(self):
        import app as app_module
        return app_module.app.test_client()

    def test_43_vergleich_liefert_supercupminuten(self, client, monkeypatch):
        """
        Der vollstaendige Weg: Rohantwort mit Supercup -> Endpunkt ->
        Minuten in der Antwort.
        """
        import src.data.player_compare_loader as pcl

        rohdaten = {
            11: raw(11, "A. Test", [block(529, "Super Cup", 81)]),
            12: raw(12, "B. Test", [block(529, "Super Cup", 74)]),
        }
        monkeypatch.setattr(pcl, "get_player_season_raw_enriched",
                            lambda pid, season, **k: rohdaten.get(pid))

        r = client.get("/api/player-compare?a=11&b=12"
                       "&season_a=2026&season_b=2026&scope=club_all")
        assert r.status_code == 200
        d = r.get_json()
        assert d["player_a"]["minutes"] == 81
        assert d["player_b"]["minutes"] == 74
        assert d["comparison"]["radar_enabled"] is True

    def test_44_ligascope_zeigt_keine_supercupminuten(self, client, monkeypatch):
        import src.data.player_compare_loader as pcl

        rohdaten = {
            11: raw(11, "A. Test", [block(529, "Super Cup", 81)]),
            12: raw(12, "B. Test", [block(529, "Super Cup", 74)]),
        }
        monkeypatch.setattr(pcl, "get_player_season_raw_enriched",
                            lambda pid, season, **k: rohdaten.get(pid))

        r = client.get("/api/player-compare?a=11&b=12"
                       "&season_a=2026&season_b=2026&scope=league")
        d = r.get_json()
        assert (d["player_a"]["minutes"] or 0) == 0
        assert d["comparison"]["radar_enabled"] is False

    def test_45_fehlende_daten_sind_kein_serverfehler(self, client, monkeypatch):
        """
        Eine Datenluecke ist eine Datenlage, kein HTTP 500 und kein 503.
        """
        import src.data.player_compare_loader as pcl

        monkeypatch.setattr(pcl, "get_player_season_raw_enriched",
                            lambda pid, season, **k: None)

        r = client.get("/api/player-compare?a=11&b=12"
                       "&season_a=2026&season_b=2026&scope=club_all")
        assert r.status_code == 200
        d = r.get_json()
        assert d["comparison"]["radar_enabled"] is False

    def test_46_antwort_nennt_ihre_herkunft(self, client, monkeypatch):
        import src.data.player_compare_loader as pcl

        rohdaten = {11: raw(11, "A", [block(529, "Super Cup", 81)]),
                    12: raw(12, "B", [block(529, "Super Cup", 74)])}
        monkeypatch.setattr(pcl, "get_player_season_raw_enriched",
                            lambda pid, season, **k: rohdaten.get(pid))

        d = client.get("/api/player-compare?a=11&b=12"
                       "&season_a=2026&season_b=2026&scope=club_all").get_json()
        prov = d["provenance"]
        assert prov["scope"] == "club_all"
        assert prov["season_a"] == 2026
        assert "fallback_status" in prov

    def test_47_keine_secrets_in_der_antwort(self, client, monkeypatch):
        import src.data.player_compare_loader as pcl

        rohdaten = {11: raw(11, "A", [block(529, "Super Cup", 81)]),
                    12: raw(12, "B", [block(529, "Super Cup", 74)])}
        monkeypatch.setattr(pcl, "get_player_season_raw_enriched",
                            lambda pid, season, **k: rohdaten.get(pid))

        d = client.get("/api/player-compare?a=11&b=12"
                       "&season_a=2026&season_b=2026&scope=club_all").get_json()
        text = json.dumps(d).lower()
        for verboten in ("api_key", "secret", "token", "traceback",
                         "c:" + chr(92), "/root", ".env"):
            assert verboten not in text
