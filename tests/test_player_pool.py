"""
Tests fuer Perzentil-Engine und Spielerpool (Phase 3, Etappe 2).

Alle Tests laufen ohne Netzwerk. Der Importablauf wird mit einem
eingespeisten Fake-Seitenabruf getestet, inklusive Abbruch und
Wiederaufnahme.

Dateizugriffe laufen ueber tmp_path, damit keine echten Projektdaten
beruehrt werden.
"""

import json
import os

import pytest

from src.data.percentile_engine import (
    build_quantiles,
    percentile_of,
    apply_direction,
    build_snapshot,
    is_snapshot_complete,
    describe_pool,
    percentiles_for_player,
    relevant_metric_keys,
    MIN_POOL_SIZE,
    QUANTILE_STEPS,
    DEFAULT_MIN_MINUTES,
)

from src.data import player_pool
from src.data.player_pool import (
    import_league,
    build_pool_entry,
    STATUS_COMPLETE,
    STATUS_PROVIDER_INCOMPLETE,
    STATUS_ERROR,
    STATUS_IN_PROGRESS,
)

from src.data.player_compare_loader import build_player_profile, build_comparison
from src.data.player_metrics import POSITION_ATT, POSITION_DEF, POSITION_GK


# ---------------------------------------------------------------------------
# Quantile
# ---------------------------------------------------------------------------

def test_quantile_liefert_101_stuetzstellen():
    values = list(range(100))
    quantiles = build_quantiles(values)
    assert len(quantiles) == QUANTILE_STEPS


def test_quantile_ist_aufsteigend_sortiert():
    values = [5, 1, 9, 3, 7] * 20
    quantiles = build_quantiles(values)
    assert quantiles == sorted(quantiles)


def test_quantile_raender_sind_min_und_max():
    values = list(range(50, 150))
    quantiles = build_quantiles(values)
    assert quantiles[0] == 50
    assert quantiles[-1] == 149


def test_zu_kleine_stichprobe_liefert_keine_verteilung():
    """Bei winzigen Gruppen waere ein Perzentil reines Rauschen."""
    values = list(range(MIN_POOL_SIZE - 1))
    assert build_quantiles(values) is None


def test_none_werte_werden_ignoriert():
    values = [None] * 10 + list(range(MIN_POOL_SIZE))
    quantiles = build_quantiles(values)
    assert quantiles is not None
    assert quantiles[0] == 0


# ---------------------------------------------------------------------------
# Einordnung
# ---------------------------------------------------------------------------

def test_perzentil_minimum_ist_null():
    quantiles = build_quantiles(list(range(100)))
    assert percentile_of(0, quantiles) == 0


def test_perzentil_maximum_ist_hundert():
    quantiles = build_quantiles(list(range(100)))
    assert percentile_of(99, quantiles) == 100


def test_perzentil_mitte_liegt_in_der_mitte():
    quantiles = build_quantiles(list(range(101)))
    result = percentile_of(50, quantiles)
    assert 45 <= result <= 55


def test_perzentil_ueber_maximum_bleibt_bei_hundert():
    quantiles = build_quantiles(list(range(100)))
    assert percentile_of(9999, quantiles) == 100


def test_perzentil_ohne_wert_ist_none():
    quantiles = build_quantiles(list(range(100)))
    assert percentile_of(None, quantiles) is None


def test_perzentil_ohne_verteilung_ist_none():
    assert percentile_of(5, None) is None
    assert percentile_of(5, []) is None


def test_haeufung_bei_null_wird_fair_eingeordnet():
    """
    Viele Kennzahlen haben eine grosse Haeufung bei 0, etwa Blocks pro 90
    bei Offensivspielern. Der Mid-Rank verhindert, dass derselbe Wert
    einmal das 0. und einmal das 40. Perzentil ergibt.
    """
    values = [0.0] * 60 + [float(i) for i in range(1, 41)]
    quantiles = build_quantiles(values)
    result = percentile_of(0.0, quantiles)
    assert 0 < result < 60


# ---------------------------------------------------------------------------
# Richtung
# ---------------------------------------------------------------------------

def test_hoeher_ist_besser_bleibt_unveraendert():
    assert apply_direction(80, "goals_per90") == 80


def test_niedriger_ist_besser_wird_gedreht():
    """Wenige Gegentore muessen ein HOHES Perzentil ergeben."""
    assert apply_direction(20, "conceded_per90") == 80
    assert apply_direction(10, "fouls_committed_per90") == 90


def test_richtung_bei_none_bleibt_none():
    assert apply_direction(None, "conceded_per90") is None


def test_unbekannte_metrik_wird_nicht_gedreht():
    assert apply_direction(30, "gibt_es_nicht") == 30


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

def _pool_player(position, minutes, goals_per90=0.5, scope="club_all", **extra):
    # Bewusst Kennzahlen aus mehreren Profilen, damit der Helfer fuer
    # jede Positionsgruppe brauchbare Werte liefert. Eine Verteilung
    # entsteht nur fuer Kennzahlen, die zur Gruppe gehoeren.
    #
    # Scope-bewusstes Schema: Kennzahlen und Minuten liegen unter dem
    # angegebenen Scope (Standard club_all), die anderen drei Scopes
    # bleiben leer - fuer die Snapshot-Tests hier ausreichend, da sie
    # ausschliesslich club_all abfragen.
    metrics = {
        "goals_per90": goals_per90,
        "tackles_per90": goals_per90,
        "saves_per90": goals_per90,
        "passes_per90": goals_per90 * 10,
    }
    metrics.update(extra)

    all_scopes = ("club_all", "league", "national", "all")
    return {
        "player_id": id(metrics),
        "position": position,
        "minutes_by_scope": {s: (minutes if s == scope else None) for s in all_scopes},
        "metrics_by_scope": {s: (dict(metrics) if s == scope else {}) for s in all_scopes},
    }


def _many_players(position, count, minutes=1000):
    return [
        _pool_player(position, minutes, goals_per90=i / 100.0)
        for i in range(count)
    ]


def test_snapshot_enthaelt_positionsgruppen():
    players = _many_players(POSITION_ATT, 60) + _many_players(POSITION_DEF, 60)
    snapshot = build_snapshot(players, 2024, ["bl1", "pl", "pd", "sa", "fl1"])
    assert POSITION_ATT in snapshot["distributions"]
    assert POSITION_DEF in snapshot["distributions"]


def test_snapshot_filtert_nach_mindestminuten():
    """Spieler unter der Grenze duerfen die Verteilung nicht verzerren."""
    players = _many_players(POSITION_ATT, 60, minutes=1000)
    players += _many_players(POSITION_ATT, 40, minutes=90)
    snapshot = build_snapshot(players, 2024, ["bl1"], min_minutes=450)
    assert snapshot["distributions"][POSITION_ATT]["player_count"] == 60


def test_snapshot_speichert_konfiguration():
    players = _many_players(POSITION_ATT, 60)
    snapshot = build_snapshot(players, 2024, ["bl1", "pl"], min_minutes=500)
    assert snapshot["season"] == 2024
    assert snapshot["min_minutes"] == 500
    assert snapshot["leagues"] == ["bl1", "pl"]
    assert snapshot["created_at"]


def test_snapshot_ohne_genug_spieler_bleibt_leer():
    players = _many_players(POSITION_ATT, 5)
    snapshot = build_snapshot(players, 2024, ["bl1"])
    assert snapshot["distributions"] == {}


def test_vollstaendigkeit_erfordert_alle_fuenf_ligen():
    complete = build_snapshot(_many_players(POSITION_ATT, 60), 2024,
                              ["bl1", "pl", "pd", "sa", "fl1"])
    partial = build_snapshot(_many_players(POSITION_ATT, 60), 2024,
                             ["bl1", "pl"])
    assert is_snapshot_complete(complete) is True
    assert is_snapshot_complete(partial) is False
    assert is_snapshot_complete(None) is False


def test_relevante_metriken_enthalten_radar_und_allgemein():
    keys = relevant_metric_keys(POSITION_ATT)
    assert "goals_per90" in keys
    # Ab Phase 3.1 besteht das General-Profil aus Per-90-Werten und Quoten
    # statt aus absoluten Saisonsummen. "minutes" ist deshalb keine
    # Radar-Achse mehr, "rating" schon.
    assert "rating" in keys
    assert "duels_won_pct" in keys
    assert len(keys) == len(set(keys)), "keine Duplikate"


def test_pool_beschreibung_nennt_vergleichsgruppe():
    """Ein Perzentil ohne Angabe der Vergleichsgruppe ist wertlos."""
    snapshot = build_snapshot(_many_players(POSITION_ATT, 60), 2024,
                              ["bl1", "pl", "pd", "sa", "fl1"])
    pool = describe_pool(snapshot, POSITION_ATT)
    assert pool["season_label"] == "2024/25"
    assert pool["min_minutes"] == DEFAULT_MIN_MINUTES
    assert pool["player_count"] == 60
    assert pool["complete"] is True


def test_pool_beschreibung_fuer_unbekannte_position_ist_none():
    snapshot = build_snapshot(_many_players(POSITION_ATT, 60), 2024, ["bl1"])
    assert describe_pool(snapshot, POSITION_GK) is None
    assert describe_pool(None, POSITION_ATT) is None


# ---------------------------------------------------------------------------
# Perzentile eines Spielers
# ---------------------------------------------------------------------------

def test_spieler_perzentile_werden_berechnet():
    snapshot = build_snapshot(_many_players(POSITION_ATT, 100), 2024, ["bl1"])
    result = percentiles_for_player(snapshot, POSITION_ATT, {"goals_per90": 0.99})
    assert result["goals_per90"] >= 90


def test_spieler_perzentile_ohne_snapshot_sind_none():
    result = percentiles_for_player(None, POSITION_ATT, {"goals_per90": 0.5})
    assert result["goals_per90"] is None


def test_spieler_perzentile_bei_fehlendem_rohwert_sind_none():
    snapshot = build_snapshot(_many_players(POSITION_ATT, 100), 2024, ["bl1"])
    result = percentiles_for_player(snapshot, POSITION_ATT, {"goals_per90": None})
    assert result["goals_per90"] is None


def test_spieler_perzentile_fuer_unbekannte_metrik_sind_none():
    snapshot = build_snapshot(_many_players(POSITION_ATT, 100), 2024, ["bl1"])
    result = percentiles_for_player(snapshot, POSITION_ATT, {"saves_per90": 3.0})
    assert result["saves_per90"] is None


# ---------------------------------------------------------------------------
# Pool-Dateien und Import
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_pool(tmp_path, monkeypatch):
    """Legt Pool-Verzeichnis und Statusdatei in ein temporaeres Verzeichnis."""
    pool_dir = tmp_path / "player_pool"
    monkeypatch.setattr(player_pool, "POOL_DIR", str(pool_dir))
    monkeypatch.setattr(player_pool, "STATUS_PATH", str(pool_dir / "status.json"))
    monkeypatch.setattr(player_pool, "LOCK_PATH", str(pool_dir / "import.lock"))
    return pool_dir


def _fake_api_player(player_id, position="Attacker", minutes=1000, goals=10,
                    team_count=1):
    """
    Ein Spieler im Providerformat.

    team_count verteilt die Spieler auf mehrere Vereine. Vorher lagen alle
    in "Test FC" - damit liess sich die Ligaabdeckung, die seit der
    Datenreparatur ueber die Vollstaendigkeit entscheidet, gar nicht
    abbilden.
    """
    team_nr = (player_id % team_count) + 1 if team_count > 1 else 1
    return {
        "player": {"id": player_id, "name": f"Spieler {player_id}", "age": 25},
        "statistics": [{
            "league": {"id": 78},
            "team": {"id": team_nr, "name": f"Test FC {team_nr}"},
            "games": {"appearences": 20, "lineups": 18, "minutes": minutes,
                      "position": position, "rating": "7.00"},
            "shots": {"total": 40, "on": 15},
            "goals": {"total": goals, "conceded": None, "assists": 5, "saves": None},
            "passes": {"total": 600, "key": 20, "accuracy": 82},
            "tackles": {"total": 15, "blocks": 2, "interceptions": 8},
            "duels": {"total": 150, "won": 80},
            "dribbles": {"attempts": 50, "success": 30},
            "fouls": {"drawn": 20, "committed": 15},
            "cards": {"yellow": 2, "red": 0},
            "penalty": {"saved": None, "scored": 1, "missed": 0},
        }],
    }


def _fake_fetcher(total_pages, per_page=20, fail_on_page=None, team_count=1):
    """Baut einen Seitenabruf, der optional bei einer Seite scheitert."""
    def fetch(page):
        if fail_on_page is not None and page == fail_on_page:
            raise RuntimeError("simulierter Netzwerkfehler")
        start = (page - 1) * per_page
        return {
            "response": [_fake_api_player(start + i, team_count=team_count)
                         for i in range(per_page)],
            "paging": {"current": page, "total": total_pages},
        }
    return fetch


def _realistic_fetcher(total_pages=25, team_count=18):
    """
    Ein Import, der einer echten Liga entspricht: genug Spieler, genug
    Vereine. Notwendig, seit die Vollstaendigkeit inhaltlich geprueft wird.
    """
    return _fake_fetcher(total_pages=total_pages, team_count=team_count)


def _entry_builder(raw):
    """
    Baut fuer Tests einen Pooleintrag im scope-bewussten Schema, aber nur
    mit club_all befuellt (die anderen drei Scopes bleiben leer). Das
    genuegt fuer alle Tests hier, die sich auf die Standard-Kennzahl
    goals_per90 unter club_all beziehen.
    """
    profile = build_player_profile(raw, 2024, scope="club_all")
    if not profile.get("data_available") or profile.get("position") is None:
        return None

    empty_profile = build_player_profile({}, 2024, scope="club_all")
    profile_by_scope = {
        "club_all": profile, "league": empty_profile,
        "national": empty_profile, "all": empty_profile,
    }
    metrics_by_scope = {
        "club_all": {"goals_per90": 0.5},
        "league": {}, "national": {}, "all": {},
    }
    return build_pool_entry(profile_by_scope, metrics_by_scope)


def test_import_laedt_alle_seiten(isolated_pool):
    status = import_league(
        "bl1", 2024,
        fetch_page=_realistic_fetcher(total_pages=3, team_count=18),
        build_entry=_entry_builder,
        throttle_seconds=0,
    )
    # Die Paginierung ist der Gegenstand dieses Tests und funktioniert.
    assert status["total_pages"] == 3
    assert status["loaded_pages"] == 3
    assert status["player_count"] == 60
    # Inhaltlich sind 60 Spieler zu wenig fuer eine Liga - seit der
    # Datenreparatur sagt der Status das auch. Frueher stand hier
    # "complete", und genau diese Nachsicht liess die Bundesliga mit null
    # Spielern als vollstaendig durchgehen.
    assert status["status"] == STATUS_PROVIDER_INCOMPLETE


def test_realistischer_import_wird_complete(isolated_pool):
    """Gegenstueck: Ein Import in Ligagroesse besteht die Pruefung."""
    status = import_league(
        "bl1", 2024,
        fetch_page=_realistic_fetcher(total_pages=25, team_count=18),
        build_entry=_entry_builder,
        throttle_seconds=0,
    )
    assert status["status"] == STATUS_COMPLETE
    assert status["player_count"] == 500
    assert status["team_count"] == 18
    assert status["issues"] == []


def test_import_speichert_pooldatei(isolated_pool):
    import_league("bl1", 2024, _fake_fetcher(2), _entry_builder, throttle_seconds=0)
    pool = player_pool.read_pool("bl1", 2024)
    assert len(pool["players"]) == 40
    assert pool["pages_done"] == [1, 2]


def test_import_bricht_ab_und_behaelt_fortschritt(isolated_pool):
    """Ein Abbruch darf die bereits geladenen Seiten nicht vernichten."""
    with pytest.raises(RuntimeError):
        import_league(
            "bl1", 2024,
            fetch_page=_fake_fetcher(total_pages=5, fail_on_page=3),
            build_entry=_entry_builder,
            throttle_seconds=0,
        )

    status = player_pool.get_pool_status("bl1", 2024)
    assert status["status"] == STATUS_ERROR
    assert status["loaded_pages"] == 2

    pool = player_pool.read_pool("bl1", 2024)
    assert pool["pages_done"] == [1, 2]
    assert len(pool["players"]) == 40


def test_import_setzt_nach_abbruch_fort(isolated_pool):
    """Nach einem Fehler soll ein neuer Lauf nicht von vorn beginnen."""
    with pytest.raises(RuntimeError):
        import_league("bl1", 2024,
                      _fake_fetcher(25, fail_on_page=3, team_count=18),
                      _entry_builder, throttle_seconds=0)

    calls = []
    base = _realistic_fetcher(total_pages=25, team_count=18)

    def counting_fetch(page):
        calls.append(page)
        return base(page)

    status = import_league("bl1", 2024, counting_fetch, _entry_builder,
                           throttle_seconds=0, resume=True)

    assert status["status"] == STATUS_COMPLETE
    # Seite 1 wird zum Auslesen der Seitenzahl immer geholt,
    # Seite 2 aber nicht erneut.
    assert 2 not in calls[1:]


def test_force_laedt_alles_neu(isolated_pool):
    import_league("bl1", 2024, _fake_fetcher(3), _entry_builder, throttle_seconds=0)

    calls = []
    base = _fake_fetcher(3)

    def counting_fetch(page):
        calls.append(page)
        return base(page)

    import_league("bl1", 2024, counting_fetch, _entry_builder,
                  throttle_seconds=0, resume=False)

    assert sorted(set(calls)) == [1, 2, 3]


def test_import_dedupliziert_spieler(isolated_pool):
    """Derselbe Spieler auf zwei Seiten darf nur einmal im Pool landen."""
    def duplicate_fetch(page):
        return {
            "response": [_fake_api_player(1), _fake_api_player(2)],
            "paging": {"current": page, "total": 2},
        }

    status = import_league("bl1", 2024, duplicate_fetch, _entry_builder,
                           throttle_seconds=0)
    assert status["player_count"] == 2


def test_unvollstaendige_liga_zaehlt_nicht_zum_pool(isolated_pool):
    with pytest.raises(RuntimeError):
        import_league("bl1", 2024, _fake_fetcher(5, fail_on_page=2),
                      _entry_builder, throttle_seconds=0)

    players, used = player_pool.load_all_players(2024, ["bl1", "pl"])
    assert players == []
    assert used == []


def test_vollstaendige_liga_zaehlt_zum_pool(isolated_pool):
    # Ligagroesse noetig: load_all_players zaehlt nur Ligen, die die
    # inhaltliche Vollstaendigkeitspruefung bestanden haben.
    import_league("bl1", 2024, _realistic_fetcher(total_pages=25, team_count=18),
                  _entry_builder, throttle_seconds=0)
    players, used = player_pool.load_all_players(2024, ["bl1", "pl"])
    assert len(players) == 500
    assert used == ["bl1"]


def test_teilweise_gelieferte_liga_zaehlt_trotzdem_mit(isolated_pool):
    """
    Eine Liga, die der Anbieter nur teilweise liefert, traegt ihre echten
    Spieler weiterhin bei.

    Sonst verschwaenden zum Saisonstart drei von fuenf Ligen aus Plots und
    Kohorte, obwohl dort hunderte Spieler mit echten Werten liegen. Der
    unvollstaendige Zustand wird ueber den STATUS gemeldet, nicht durch
    Verstecken der Daten.
    """
    status = import_league("bl1", 2024, _fake_fetcher(2), _entry_builder,
                           throttle_seconds=0)
    assert status["status"] == STATUS_PROVIDER_INCOMPLETE

    players, used = player_pool.load_all_players(2024, ["bl1", "pl"])
    assert len(players) == 40
    assert used == ["bl1"]


def test_strenge_auswahl_nimmt_nur_vollstaendige_ligen(isolated_pool):
    """require_complete=True ist fuer Aufrufer, die eine gepruefte
    Grundlage brauchen."""
    import_league("bl1", 2024, _fake_fetcher(2), _entry_builder,
                  throttle_seconds=0)
    players, used = player_pool.load_all_players(
        2024, ["bl1", "pl"], require_complete=True)
    assert players == []
    assert used == []


def test_leere_liga_zaehlt_nie_zum_pool(isolated_pool):
    """
    Eine Liga ohne einen einzigen Spieler bleibt draussen - genau der
    Fall der Bundesliga 2026/27.
    """
    def leerer_abruf(page):
        return {"response": [], "paging": {"current": 1, "total": 1}}

    status = import_league("bl1", 2024, leerer_abruf, _entry_builder,
                           throttle_seconds=0)
    assert status["status"] == STATUS_PROVIDER_INCOMPLETE

    players, used = player_pool.load_all_players(2024, ["bl1"])
    assert players == []
    assert used == []


# ---------------------------------------------------------------------------
# Sperre
# ---------------------------------------------------------------------------

def test_lock_verhindert_zweiten_import(isolated_pool):
    acquired, _ = player_pool.acquire_lock()
    assert acquired is True

    again, info = player_pool.acquire_lock()
    assert again is False
    assert info["pid"] == os.getpid()

    player_pool.release_lock()


def test_lock_wird_freigegeben(isolated_pool):
    player_pool.acquire_lock()
    player_pool.release_lock()
    acquired, _ = player_pool.acquire_lock()
    assert acquired is True
    player_pool.release_lock()


def test_verwaister_lock_wird_uebernommen(isolated_pool):
    """Ein Absturz darf den Import nicht dauerhaft blockieren."""
    # Lock mit altem Zeitstempel simuliert einen Absturz.
    # _lock_is_stale() erkennt den Lock als veraltet (> 2 Stunden)
    # ohne einen Prozess-Check zu benoetigen.
    player_pool._write_json_atomic(player_pool.LOCK_PATH, {
        "pid": 999999999,
        "started_at": "2020-01-01T00:00:00+00:00",
    })
    acquired, _ = player_pool.acquire_lock()
    assert acquired is True
    player_pool.release_lock()


# ---------------------------------------------------------------------------
# Zusammenspiel mit dem Vergleich
# ---------------------------------------------------------------------------

def _profile(position, minutes=1000, goals=10):
    return build_player_profile(
        _fake_api_player(1, position=position, minutes=minutes, goals=goals),
        2024,
    )


def test_vergleich_ohne_snapshot_bleibt_ehrlich():
    result = build_comparison(_profile("Attacker"), _profile("Attacker"))
    assert result["percentiles_available"] is False
    assert result["percentile_pool_complete"] is False
    for metric in result["metrics"]:
        assert metric["percentile_a"] is None
        assert metric["percentile_b"] is None


def _cwrap(position, minutes, metrics):
    """
    Baut fuer diesen Testblock einen Pooleintrag im scope-bewussten Schema,
    ausschliesslich unter club_all - dem Standard-Scope von Radar UND
    Scatter seit dieser Ueberarbeitung.
    """
    empty = {"club_all": {}, "league": {}, "national": {}, "all": {}}
    return {
        "player_id": id(metrics) if not isinstance(metrics, dict) or "player_id" not in metrics else metrics["player_id"],
        "position": position,
        "minutes_by_scope": {**{s: None for s in empty}, "club_all": minutes},
        "metrics_by_scope": {**empty, "club_all": metrics},
    }


def test_vergleich_mit_snapshot_liefert_perzentile():
    pool = [
        _cwrap(POSITION_ATT, 1000, {"goals_per90": i / 100.0})
        for i in range(100)
    ]
    snapshot = build_snapshot(pool, 2024, ["bl1", "pl", "pd", "sa", "fl1"])

    result = build_comparison(_profile("Attacker"), _profile("Attacker"), snapshot)
    assert result["percentiles_available"] is True
    assert result["percentile_pool_complete"] is True
    assert result["pool_a"]["complete"] is True


def test_zu_wenig_minuten_wird_stabilisiert_statt_gesperrt():
    """
    Ein Spieler mit 120 Minuten waere selbst nicht im Referenzpool.

    Frueher bekam er deshalb GAR KEIN Perzentil. Am ersten Spieltag war
    damit niemand vergleichbar - genau dann, wenn das Interesse am
    groessten ist.

    Seit GO 1.1 wird er eingeordnet, sein Wert dabei aber zur Referenz
    gezogen (minutes/(minutes+k)). Die urspruengliche Sorge - eine
    Belastbarkeit vortaeuschen, die die Stichprobe nicht hergibt - bleibt
    damit adressiert: nicht durch Aussperren, sondern durch Daempfung und
    einen sichtbaren "provisional"-Hinweis.
    """
    pool = [
        _cwrap(POSITION_ATT, 1000, {"goals_per90": i / 100.0})
        for i in range(100)
    ]
    snapshot = build_snapshot(pool, 2024, ["bl1"], min_minutes=450)

    result = build_comparison(
        _profile("Attacker", minutes=120),
        _profile("Attacker", minutes=1000),
        snapshot,
    )
    assert result["percentile_blocked_a"] == "provisional"
    assert result["percentile_blocked_b"] is None
    assert result["provisional_a"] is True
    assert result["provisional_b"] is False

    # Entscheidend: er wird ueberhaupt eingeordnet. Frueher war hier
    # jedes Perzentil None. Wie stark die Daempfung wirkt, pruefen die
    # gezielten Tests in test_go11_go2_data_foundation.py - hier haette
    # eine Perzentilgrenze keine Aussagekraft, weil der Testpool bei
    # 0.99 endet und jeder gedaempfte Wert darueber liegt.
    eingeordnet = [m for m in result["metrics"] if m["percentile_a"] is not None]
    assert eingeordnet, "der Spieler wurde weiterhin komplett ausgesperrt"


def test_allgemeiner_vergleich_misst_jeden_an_seiner_gruppe():
    """
    Torwart gegen Stuermer: beide bekommen Perzentile, aber jeder gegen
    seine eigene Positionsgruppe. Beide gegen dieselbe zu messen waere unfair.
    """
    # Der Pool muss Kennzahlen des General-Profils enthalten, sonst entsteht
    # gar keine Verteilung. Seit Phase 3.1 sind das Per-90-Werte und Quoten.
    pool = []
    for position in (POSITION_ATT, POSITION_GK):
        pool += [
            _cwrap(position, 1000, {
                "goals_per90": i * 0.01,
                "assists_per90": i * 0.008,
                "passes_per90": 30 + i,
                "pass_accuracy_pct": 60 + i * 0.3,
                "duels_won_pct": 40 + i * 0.2,
                "rating": 6.0 + i * 0.02,
            })
            for i in range(100)
        ]
    snapshot = build_snapshot(pool, 2024, ["bl1", "pl", "pd", "sa", "fl1"])

    result = build_comparison(_profile("Goalkeeper"), _profile("Attacker"), snapshot)

    assert result["mode"] == "general"
    # Ab Phase 3.1: Radar bleibt sichtbar, nur mit General-Achsen
    assert result["radar_enabled"] is True
    assert result["pool_a"] is not None
    assert result["pool_b"] is not None


# ---------------------------------------------------------------------------
# Pfadaufloesung
# ---------------------------------------------------------------------------

def test_datenverzeichnisse_sind_absolut():
    """
    Regressionsschutz.

    POOL_DIR und PERCENTILE_DIR waren zunaechst relativ ("data/player_pool").
    Das ist ein stiller Fehler: Der Importjob laeuft per Cron aus einem
    beliebigen Arbeitsverzeichnis, Gunicorn aus einem anderen. Beide haetten
    dann in verschiedene Verzeichnisse geschrieben beziehungsweise gelesen,
    ohne dass irgendwo ein Fehler auftaucht - der Pool waere einfach
    dauerhaft "nicht vorhanden".

    Die uebrigen Datenmodule (disk_cache, historical_loader) loesen ihre
    Pfade ueber _PROJECT_ROOT auf. Diese beiden jetzt auch.
    """
    import os
    from src.data.player_pool import POOL_DIR
    from src.data.percentile_engine import PERCENTILE_DIR

    assert os.path.isabs(POOL_DIR), "POOL_DIR muss ein absoluter Pfad sein"
    assert os.path.isabs(PERCENTILE_DIR), "PERCENTILE_DIR muss ein absoluter Pfad sein"


def test_datenverzeichnisse_liegen_im_projekt():
    """Beide Verzeichnisse muessen unterhalb von data/ im Projekt liegen."""
    import os
    from src.data.player_pool import POOL_DIR
    from src.data.percentile_engine import PERCENTILE_DIR
    from src.utils.disk_cache import CACHE_DIR

    project_data = os.path.dirname(CACHE_DIR)   # .../data

    assert POOL_DIR.startswith(project_data)
    assert PERCENTILE_DIR.startswith(project_data)
