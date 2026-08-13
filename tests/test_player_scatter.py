"""
Tests fuer /api/player-scatter (Phase 3.2 Teil 2).

Zwei Ebenen:
    1. load_scatter_points()  - reine Poolabfrage, kein Netzwerk, kein Flask
    2. Route                  - Flask-Testclient, Pool ueber ein temporaeres
                                Verzeichnis isoliert (wie in test_player_pool.py)

Kein Test schickt einen echten API-Request. Der Scatter-Endpunkt liest
ausschliesslich den Player Pool - das ist die Kerngarantie dieses Features
und wird hier mehrfach geprueft.
"""

import pytest

from src.data import player_pool
from src.data.player_pool import (
    write_pool,
    update_pool_status,
    load_scatter_points,
    STATUS_COMPLETE,
)
from src.utils import disk_cache


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_pool(tmp_path, monkeypatch):
    """Legt Pool-Verzeichnis und Statusdatei in ein temporaeres Verzeichnis."""
    pool_dir = tmp_path / "player_pool"
    monkeypatch.setattr(player_pool, "POOL_DIR", str(pool_dir))
    monkeypatch.setattr(player_pool, "STATUS_PATH", str(pool_dir / "status.json"))
    monkeypatch.setattr(player_pool, "LOCK_PATH", str(pool_dir / "import.lock"))

    # Die Route cacht ihr Ergebnis ueber disk_cached_call() im globalen
    # Disk-Cache. Ohne eigene Isolation wuerden Tests sich gegenseitig
    # Cache-Treffer unterschieben, sobald derselbe Schluessel (Saison,
    # Ligen, Position, Achsen) mehrfach vorkommt.
    cache_dir = tmp_path / "disk_cache"
    monkeypatch.setattr(disk_cache, "CACHE_DIR", str(cache_dir))

    return pool_dir


def _seed_league(league_code, season, entries):
    """Schreibt einen vollstaendigen Pool fuer eine Liga."""
    write_pool({
        "league": league_code, "season": season,
        "pages_done": [1, 2, 3], "players": entries,
    })
    update_pool_status(
        league_code, season, status=STATUS_COMPLETE,
        loaded_pages=3, total_pages=3, player_count=len(entries),
    )


def _entry(player_id, position="Attacker", minutes=1200, league_code="bl1",
           x=0.5, y=0.3, age=24, team="Test FC", scope="club_all"):
    """
    Baut einen Pooleintrag im scope-bewussten Schema.

    Der Standard-scope ist club_all - dieselbe Kennzahlenmenge existiert
    NUR fuer diesen einen Scope, die anderen drei bleiben leer. Das reicht
    fuer Tests, die club_all abfragen; Tests fuer andere Scopes bauen ihre
    eigenen Eintraege mit dem jeweiligen scope-Parameter.
    """
    metrics_by_scope = {s: {} for s in ("club_all", "league", "national", "all")}
    minutes_by_scope = {s: None for s in ("club_all", "league", "national", "all")}
    metrics_by_scope[scope] = {"goals_per90": x, "assists_per90": y}
    minutes_by_scope[scope] = minutes

    return {
        "player_id": player_id, "name": f"Spieler {player_id}",
        "position": position, "league_code": league_code,
        "age": age, "team_name": team,
        "minutes_by_scope": minutes_by_scope,
        "metrics_by_scope": metrics_by_scope,
    }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APISPORTS_KEY", "test-key")
    monkeypatch.setenv("FOOTBALL_DATA_KEY", "test-key")
    import app as app_module
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# load_scatter_points() - reine Poolabfrage
# ---------------------------------------------------------------------------

def test_scatter_points_ohne_pool_ist_leer(isolated_pool):
    """Kein Import, kein Fehler - nur eine leere, ehrliche Antwort."""
    points, used = load_scatter_points(2025, ["bl1"], "", 0, "goals_per90", "assists_per90")
    assert points == []
    assert used == []


def test_scatter_points_liest_vollstaendige_liga(isolated_pool):
    _seed_league("bl1", 2025, [_entry(1), _entry(2), _entry(3)])
    points, used = load_scatter_points(2025, ["bl1"], "", 0, "goals_per90", "assists_per90")
    assert len(points) == 3
    assert used == ["bl1"]


def test_scatter_points_ignoriert_unvollstaendige_liga(isolated_pool):
    """
    Eine halb importierte Liga darf im Scatter nicht auftauchen - das waere
    eine verzerrte, unvollstaendige Stichprobe ohne erkennbaren Grund.
    """
    write_pool({"league": "pl", "season": 2025, "pages_done": [1],
                "players": [_entry(1, league_code="pl")]})
    # Kein update_pool_status auf COMPLETE -> bleibt "pending"

    points, used = load_scatter_points(2025, ["pl"], "", 0, "goals_per90", "assists_per90")
    assert points == []
    assert used == []


def test_scatter_points_filtert_position(isolated_pool):
    _seed_league("bl1", 2025, [
        _entry(1, position="Attacker"),
        _entry(2, position="Defender"),
        _entry(3, position="Attacker"),
    ])
    points, _ = load_scatter_points(2025, ["bl1"], "Attacker", 0, "goals_per90", "assists_per90")
    assert len(points) == 2
    assert all(p["position"] == "Attacker" for p in points)


def test_scatter_points_leere_position_zeigt_alle(isolated_pool):
    _seed_league("bl1", 2025, [
        _entry(1, position="Attacker"), _entry(2, position="Goalkeeper"),
    ])
    points, _ = load_scatter_points(2025, ["bl1"], "", 0, "goals_per90", "assists_per90")
    assert len(points) == 2


def test_scatter_points_filtert_mindestminuten(isolated_pool):
    _seed_league("bl1", 2025, [
        _entry(1, minutes=200), _entry(2, minutes=800), _entry(3, minutes=2000),
    ])
    points, _ = load_scatter_points(2025, ["bl1"], "", 450, "goals_per90", "assists_per90")
    assert len(points) == 2
    assert all(p["minutes"] >= 450 for p in points)


def test_scatter_points_ohne_metrikwert_wird_ausgeschlossen(isolated_pool):
    """
    Ein Spieler ohne beide Achsenwerte kann nicht geplottet werden. Er wird
    stillschweigend ausgelassen statt mit einem erfundenen Wert (z. B. 0)
    an einer irrefuehrenden Stelle zu erscheinen.
    """
    entry_ohne_assists = _entry(1)
    del entry_ohne_assists["metrics_by_scope"]["club_all"]["assists_per90"]
    _seed_league("bl1", 2025, [entry_ohne_assists, _entry(2)])

    points, _ = load_scatter_points(2025, ["bl1"], "", 0, "goals_per90", "assists_per90")
    assert len(points) == 1
    assert points[0]["id"] == 2


def test_scatter_points_sammelt_mehrere_ligen(isolated_pool):
    _seed_league("bl1", 2025, [_entry(1, league_code="bl1")])
    _seed_league("pl", 2025, [_entry(2, league_code="pl")])
    points, used = load_scatter_points(2025, ["bl1", "pl"], "", 0, "goals_per90", "assists_per90")
    assert len(points) == 2
    assert sorted(used) == ["bl1", "pl"]


def test_scatter_points_enthaelt_alle_anzeigefelder(isolated_pool):
    _seed_league("bl1", 2025, [_entry(1, age=19, team="RB Leipzig")])
    points, _ = load_scatter_points(2025, ["bl1"], "", 0, "goals_per90", "assists_per90")
    point = points[0]
    for field in ("id", "name", "team", "league", "position", "age", "minutes", "x", "y"):
        assert field in point
    assert point["age"] == 19
    assert point["team"] == "RB Leipzig"


# ---------------------------------------------------------------------------
# Route: /api/player-scatter
# ---------------------------------------------------------------------------

def test_route_liefert_punkte_und_metadaten_in_einer_antwort(client, isolated_pool):
    """
    Kernanforderung: kein separater -meta-Endpunkt. Eine Antwort enthaelt
    sowohl die Punkte als auch alles, was das Frontend zum Rendern braucht.
    """
    _seed_league("bl1", 2025, [_entry(1), _entry(2)])

    response = client.get("/api/player-scatter?season=2025")
    assert response.status_code == 200
    data = response.get_json()

    assert "points" in data
    assert "axes" in data
    assert "leagues" in data
    assert "positions" in data
    assert "pool_complete" in data
    assert "used_leagues" in data
    assert "missing_leagues" in data


def test_route_meldet_fehlende_ligen_ehrlich(client, isolated_pool):
    _seed_league("bl1", 2025, [_entry(1)])
    response = client.get("/api/player-scatter?season=2025&leagues=bl1,pl")
    data = response.get_json()
    assert data["missing_leagues"] == ["pl"]
    assert data["pool_complete"] is False


def test_route_ohne_pool_liefert_leere_liste_kein_fehler(client, isolated_pool):
    """Kein Import vorhanden: leere Punktliste, kein 500er, kein API-Call."""
    response = client.get("/api/player-scatter?season=2025")
    assert response.status_code == 200
    data = response.get_json()
    assert data["points"] == []
    assert data["pool_complete"] is False


def test_route_x_gleich_y_wird_abgelehnt(client, isolated_pool):
    response = client.get("/api/player-scatter?x=goals_per90&y=goals_per90")
    assert response.status_code == 400


def test_route_unbekannte_achse_wird_abgelehnt(client, isolated_pool):
    response = client.get("/api/player-scatter?x=quatsch")
    assert response.status_code == 400


def test_route_unbekannte_position_wird_abgelehnt(client, isolated_pool):
    response = client.get("/api/player-scatter?position=Sweeper")
    assert response.status_code == 400


def test_route_unbekannte_liga_wird_abgelehnt(client, isolated_pool):
    response = client.get("/api/player-scatter?leagues=bl1,xx")
    assert response.status_code == 400


def test_route_negative_mindestminuten_wird_abgelehnt(client, isolated_pool):
    response = client.get("/api/player-scatter?min_minutes=-10")
    assert response.status_code == 400


def test_route_ungueltige_saison_wird_abgelehnt(client, isolated_pool):
    response = client.get("/api/player-scatter?season=1800")
    assert response.status_code == 400


def test_route_filtert_position_ueber_http(client, isolated_pool):
    _seed_league("bl1", 2025, [
        _entry(1, position="Attacker"), _entry(2, position="Defender"),
    ])
    response = client.get("/api/player-scatter?season=2025&position=Attacker")
    data = response.get_json()
    assert data["point_count"] == 1
    assert data["points"][0]["position"] == "Attacker"
    assert data["position_label"] == "Angriff"


def test_route_ohne_position_zeigt_alle_positionen_label(client, isolated_pool):
    response = client.get("/api/player-scatter?season=2025")
    data = response.get_json()
    assert data["position"] is None
    assert data["position_label"] == "Alle Positionen"


def test_route_liefert_29_minus_2_achsen(client, isolated_pool):
    """appearances und lineups sind bewusst keine Scatter-Achsen."""
    response = client.get("/api/player-scatter?season=2025")
    data = response.get_json()
    keys = [a["key"] for a in data["axes"]]
    assert "appearances" not in keys
    assert "lineups" not in keys
    assert "goals_per90" in keys


def test_route_default_achsen_sind_tore_und_assists(client, isolated_pool):
    response = client.get("/api/player-scatter?season=2025")
    data = response.get_json()
    assert data["x"]["key"] == "goals_per90"
    assert data["y"]["key"] == "assists_per90"


def test_route_liefert_fuenf_ligen(client, isolated_pool):
    response = client.get("/api/player-scatter?season=2025")
    data = response.get_json()
    assert len(data["leagues"]) == 5


def test_route_liefert_vier_positionen(client, isolated_pool):
    response = client.get("/api/player-scatter?season=2025")
    data = response.get_json()
    assert len(data["positions"]) == 4


def test_route_macht_keinen_zweiten_request_bei_wiederholung(client, isolated_pool, monkeypatch):
    """
    Zwei identische Anfragen duerfen den Pool nur einmal lesen - der
    Ergebnis-Cache muss beim zweiten Aufruf greifen.
    """
    _seed_league("bl1", 2025, [_entry(1)])

    call_count = {"n": 0}
    original = player_pool.load_scatter_points

    def _counting(*args, **kwargs):
        call_count["n"] += 1
        return original(*args, **kwargs)

    import app as app_module
    monkeypatch.setattr(app_module, "load_scatter_points", _counting)

    client.get("/api/player-scatter?season=2025&position=Attacker")
    client.get("/api/player-scatter?season=2025&position=Attacker")

    assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# Wettbewerbsumfang im Scatter
# ---------------------------------------------------------------------------

def _entry_multi_scope(player_id, league_code="bl1"):
    """
    Pooleintrag mit unterschiedlichen Werten je Wettbewerbsumfang.

    Bildet den realen Fall ab: ein Spieler hat in der Liga andere Per-90-Werte
    als wenn man Pokal und Europapokal mitzaehlt.
    """
    return {
        "player_id": player_id, "name": f"Spieler {player_id}",
        "position": "Midfielder", "league_code": league_code,
        "age": 24, "team_name": "Test FC",
        "minutes_by_scope": {
            "league": 2700, "club_all": 3240, "national": 480, "all": 3720,
        },
        "metrics_by_scope": {
            "league":   {"goals_per90": 0.40, "assists_per90": 0.30},
            "club_all": {"goals_per90": 0.42, "assists_per90": 0.31},
            "national": {"goals_per90": 0.38, "assists_per90": 0.19},
            "all":      {"goals_per90": 0.41, "assists_per90": 0.29},
        },
    }


def test_scatter_scope_waehlt_die_richtigen_werte(isolated_pool):
    """Jeder Scope muss seine eigenen Achsenwerte liefern."""
    _seed_league("bl1", 2025, [_entry_multi_scope(1)])

    erwartet = {"league": 0.40, "club_all": 0.42, "national": 0.38, "all": 0.41}
    for scope, x_wert in erwartet.items():
        points, _ = load_scatter_points(
            2025, ["bl1"], "", 0, "goals_per90", "assists_per90", scope=scope,
        )
        assert points[0]["x"] == x_wert, f"{scope} liefert falschen X-Wert"


def test_scatter_scope_standard_ist_club_all(isolated_pool):
    """Ohne Angabe gilt derselbe Standard wie im Radar."""
    _seed_league("bl1", 2025, [_entry_multi_scope(1)])
    points, _ = load_scatter_points(2025, ["bl1"], "", 0, "goals_per90", "assists_per90")
    assert points[0]["x"] == 0.42


def test_scatter_mindestminuten_gelten_je_scope(isolated_pool):
    """
    Ein Spieler kann 3240 Vereinsminuten haben, aber nur 480 fuer sein Land.
    Die Mindestminuten muessen sich auf den GEWAEHLTEN Umfang beziehen,
    sonst erschiene er im Nationalmannschafts-Plot mit zu kleiner Stichprobe.
    """
    _seed_league("bl1", 2025, [_entry_multi_scope(1)])

    club, _ = load_scatter_points(
        2025, ["bl1"], "", 1000, "goals_per90", "assists_per90", scope="club_all")
    national, _ = load_scatter_points(
        2025, ["bl1"], "", 1000, "goals_per90", "assists_per90", scope="national")

    assert len(club) == 1        # 3240 Minuten reichen
    assert len(national) == 0    # 480 Minuten reichen nicht


def test_route_reicht_scope_durch(client, isolated_pool):
    _seed_league("bl1", 2025, [_entry_multi_scope(1)])
    response = client.get("/api/player-scatter?season=2025&leagues=bl1&scope=league")
    data = response.get_json()
    assert data["scope"] == "league"
    assert data["points"][0]["x"] == 0.40


def test_route_unbekannter_scope_faellt_auf_standard(client, isolated_pool):
    """Ein veralteter Link darf die Ansicht nicht unbrauchbar machen."""
    _seed_league("bl1", 2025, [_entry_multi_scope(1)])
    response = client.get("/api/player-scatter?season=2025&leagues=bl1&scope=quatsch")
    assert response.status_code == 200
    assert response.get_json()["scope"] == "club_all"


def test_route_liefert_alle_scopes_als_metadaten(client, isolated_pool):
    """
    Das Frontend muss die Auswahl ohne zweiten Request aufbauen koennen.

    Frueher pruefte dieser Test die feste Liste
    ["club_all", "league", "national", "all"]. Inzwischen sind bewusst
    weitere, wettbewerbsscharfe Scopes dazugekommen (cl, euro, world_cup).
    Die feste Liste war nie die Kernaussage, sondern nur der damalige Stand.

    Geprueft wird deshalb der eigentliche Invariant: die vier
    urspruenglichen Scopes sind vollstaendig vorhanden und stehen weiterhin
    in derselben relativen Reihenfolge (als Teilfolge), und jeder Scope
    liefert Label und Hinweis mit. Neue Scopes duerfen dazwischen liegen,
    ohne dass dieser Test erneut angefasst werden muss.
    """
    response = client.get("/api/player-scatter?season=2025")
    data = response.get_json()
    keys = [s["key"] for s in data["scopes"]]

    original = ["club_all", "league", "national", "all"]

    # Vollstaendig vorhanden ...
    for scope in original:
        assert scope in keys, f"bestehender Scope {scope} fehlt"

    # ... und in unveraenderter relativer Reihenfolge.
    assert [k for k in keys if k in original] == original

    assert all(s["label"] and s["hint"] for s in data["scopes"])


def test_route_scope_ist_teil_des_cache_schluessels(client, isolated_pool):
    """
    Zwei Scopes duerfen sich nicht gegenseitig aus dem Cache bedienen -
    sonst zeigte ein Wechsel die Werte des vorherigen Umfangs.
    """
    _seed_league("bl1", 2025, [_entry_multi_scope(1)])

    a = client.get("/api/player-scatter?season=2025&leagues=bl1&scope=league").get_json()
    b = client.get("/api/player-scatter?season=2025&leagues=bl1&scope=national").get_json()

    assert a["points"][0]["x"] == 0.40
    assert b["points"][0]["x"] == 0.38


# ---------------------------------------------------------------------------
# Frontend-Konsistenz: Startbutton, Detailkarte, Dirty-State
#
# Diese Tests pruefen HTML/JS/CSS gegeneinander. Sie fangen genau die
# Fehlerklasse ab, die zur Laufzeit still bleibt: eine ID im JavaScript,
# die im HTML nicht existiert - das Element ist dann einfach null.
# ---------------------------------------------------------------------------

import os
import re

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(PROJECT_ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def test_startbutton_existiert_im_html():
    html = _read("templates", "index.html")
    assert 'id="pc-scatter-run"' in html
    assert "Plot erstellen" in html


def test_startbutton_ist_im_javascript_verdrahtet():
    """Ohne Listener waere der Button sichtbar, aber wirkungslos."""
    js = _read("static", "script.js")
    assert 'el("pc-scatter-run")' in js
    assert "pcScatterRunBtn.addEventListener" in js


def test_kein_filter_laedt_automatisch():
    """
    Der initiale Plot entsteht ausschliesslich ueber den Button.
    Filter duerfen nur den Dirty-Zustand setzen.
    """
    js = _read("static", "script.js")
    scatter_block = js[js.index("16i. Plots (Scatter)"):]

    # pcScatterLoad darf nur an drei Stellen stehen: Definition,
    # Button-Listener und der Guard darin.
    aufrufe = re.findall(r"pcScatterLoad\(\)", scatter_block)
    assert len(aufrufe) <= 3, f"pcScatterLoad wird zu oft aufgerufen: {len(aufrufe)}"
    assert "pcScatterMarkDirty" in scatter_block


def test_button_beschriftung_wechselt():
    js = _read("static", "script.js")
    assert "scatterCreate:" in js
    assert "scatterUpdate:" in js
    assert "hasPlot ? PC_TEXT.scatterUpdate() : PC_TEXT.scatterCreate()" in js


def test_doppelklickschutz_vorhanden():
    js = _read("static", "script.js")
    assert "if (pcState.scatter.busy) return;" in js
    assert 'setAttribute("aria-busy"' in js


def test_detailkarte_zeigt_alle_pflichtfelder():
    """
    Name, Verein, Liga, Position, Alter, Minuten, beide Achsen und der
    Wettbewerbsumfang muessen in der Karte vorkommen.
    """
    js = _read("static", "script.js")
    block = js[js.index("function pcScatterShowDetail"):js.index("function pcScatterHideDetail")]

    assert "point.name" in block
    assert "point.team" in block
    assert "COMPARE_LEAGUE_LABELS_FRONTEND[point.league]" in block
    assert "translatedPosition(point.position, point.position)" in block
    assert "point.age" in block
    assert "point.minutes" in block
    assert "meta.label" in block
    assert "pcScatterLastScopeLabel" in block


def test_detailkarte_schliesst_ueber_escape_und_ausserhalb():
    js = _read("static", "script.js")
    assert 'event.key === "Escape"' in js
    assert "pcScatterHideDetail" in js


def test_detailkarte_wird_bei_neuzeichnen_geschlossen():
    """Eine offene Karte gehoert zu den alten Punkten und waere danach falsch."""
    js = _read("static", "script.js")
    render = js[js.index("function pcScatterRenderResult"):]
    assert "pcScatterHideDetail()" in render[:render.index("function pcScatterSetEmptyText")]


def test_punkte_sind_klickbar_und_tastaturbedienbar():
    js = _read("static", "script.js")
    block = js[js.index("function renderScatterPoints"):js.index("function pcScatterShowDetail")]
    assert 'circle.addEventListener("click"' in block
    assert 'circle.addEventListener("touchstart"' in block
    assert 'circle.addEventListener("keydown"' in block
    assert 'tabindex: "0"' in block


def test_raster_skalen_und_trendlinie_werden_gezeichnet():
    js = _read("static", "script.js")
    block = js[js.index("function renderScatterPoints"):js.index("function pcScatterShowDetail")]
    assert "pc-scatter-grid" in block
    assert "pc-scatter-tick" in block
    assert "pc-scatter-trend" in block
    assert "pc-scatter-axis-label" in block


def test_trendlinie_erst_ab_acht_punkten():
    """Unter acht Punkten waere eine Trendlinie statistisch bedeutungslos."""
    js = _read("static", "script.js")
    assert "points.length >= 8" in js


def test_radar_spieler_werden_hervorgehoben():
    js = _read("static", "script.js")
    block = js[js.index("function renderScatterPoints"):js.index("function pcScatterShowDetail")]
    assert "pcState.a.player" in block
    assert "pcState.b.player" in block
    assert "pc-scatter-point-highlight" in block


def test_hervorhebung_nicht_nur_ueber_farbe():
    """Groesse und Kontur muessen zusaetzlich zur Farbe unterscheiden."""
    css = _read("static", "style.css")
    block = css[css.index(".pc-scatter-point-highlight"):]
    assert "stroke" in block[:200]


def test_suche_erzeugt_keinen_request():
    """Die optionale Suche markiert nur, sie laedt nicht neu."""
    js = _read("static", "script.js")
    block = js[js.index("if (pcScatterSearchInput)"):js.index("/* ---------- 17. START")]
    assert "pcScatterFetch" not in block
    assert "renderScatterPoints" in block


def test_alle_scatter_ids_existieren_im_html():
    html = _read("templates", "index.html")
    js = _read("static", "script.js")

    html_ids = set(re.findall(r'id="([^"]+)"', html))
    scatter_ids = {i for i in re.findall(r'el\("(pc-scatter-[^"]+)"\)', js)}

    fehlend = sorted(scatter_ids - html_ids)
    assert not fehlend, f"Im JS erwartet, im HTML nicht vorhanden: {fehlend}"


def test_alle_scatter_css_klassen_existieren():
    """
    Jede per make() oder classList gesetzte pc-scatter-Klasse braucht eine
    CSS-Regel - sonst ist das Element im DOM, aber unsichtbar oder ungestylt.

    IDs (ueber el(...)) sind hier bewusst ausgenommen: sie werden im HTML
    vergeben und von test_alle_scatter_ids_existieren_im_html geprueft.
    """
    js = _read("static", "script.js")
    css = _read("static", "style.css")

    genutzt = set()
    genutzt |= set(re.findall(r'make\("[a-z]+",\s*"(pc-scatter-[a-z-]+)"', js))
    genutzt |= set(re.findall(r'classList\.(?:add|toggle)\("(pc-scatter-[a-z-]+)"', js))
    genutzt |= set(re.findall(r'"(pc-scatter-(?:point|grid|tick|trend|axis)[a-z-]*)"', js))

    fehlend = sorted(c for c in genutzt if f".{c}" not in css)
    assert not fehlend, f"Klassen ohne CSS-Regel: {fehlend}"


def test_mindestminuten_loest_keinen_request_beim_tippen_aus():
    js = _read("static", "script.js")
    block = js[js.index("if (pcScatterMinMinutesInput)"):js.index("if (pcScatterRunBtn)")]
    assert "pcScatterLoad" not in block
    assert "pcScatterMarkDirty" in block
