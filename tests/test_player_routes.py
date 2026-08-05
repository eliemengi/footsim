"""
Tests fuer die Spielervergleich-Schnittstelle (Phase 3, Etappen 3 bis 7).

Abgedeckt werden drei Ebenen:

    1. Suchergebnis-Aufbereitung   (reine Logik, kein Netzwerk)
    2. HTTP-Routen                 (Flask-Testclient, API gemockt)
    3. Frontend-Konsistenz         (HTML, JS und CSS passen zusammen)

Die dritte Ebene ist ungewoehnlich fuer Python-Tests, faengt aber genau die
Fehlerklasse ab, die in diesem Projekt schon zweimal aufgetreten ist: eine
ID im JavaScript, die im HTML nicht existiert, oder umgekehrt. Solche Fehler
sind zur Laufzeit still - das Element ist einfach null.
"""

import json
import os
import re

import pytest

from src.data.player_compare_loader import (
    _search_result_from_entry,
    build_player_profile,
)


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BUNDESLIGA_ID = 78
CHAMPIONS_LEAGUE_ID = 2


# ---------------------------------------------------------------------------
# Testdaten
# ---------------------------------------------------------------------------

def _api_entry(player_id=1, name="Test Spieler", position="Attacker",
               minutes=1800, league_id=BUNDESLIGA_ID, team="Test FC"):
    """Ein /players-Eintrag in der Form, die API-Sports liefert."""
    return {
        "player": {
            "id": player_id,
            "name": name,
            "firstname": "Test",
            "lastname": "Spieler",
            "photo": f"https://media.example/{player_id}.png",
            "age": 25,
            "nationality": "Germany",
            "height": "182 cm",
            "weight": "76 kg",
            "birth": {"date": "2001-03-01"},
        },
        "statistics": [{
            "league": {"id": league_id, "name": "Liga"},
            "team": {"id": 10, "name": team, "logo": "logo.png"},
            "games": {
                "appearences": 28, "lineups": 25, "minutes": minutes,
                "position": position, "rating": "7.30",
            },
            "shots": {"total": 60, "on": 26},
            "goals": {"total": 14, "conceded": None, "assists": 6, "saves": None},
            "passes": {"total": 700, "key": 34, "accuracy": 81},
            "tackles": {"total": 18, "blocks": 2, "interceptions": 9},
            "duels": {"total": 240, "won": 118},
            "dribbles": {"attempts": 70, "success": 33},
            "fouls": {"drawn": 30, "committed": 18},
            "cards": {"yellow": 4, "red": 0},
            "penalty": {"saved": None, "scored": 2, "missed": 1},
        }],
    }


# ---------------------------------------------------------------------------
# 1. Suchergebnis-Aufbereitung
# ---------------------------------------------------------------------------

def test_suchtreffer_enthaelt_alle_anzeigefelder():
    """
    Die Trefferliste muss ohne zweiten API-Aufruf darstellbar sein.
    Fehlt hier ein Feld, waere ein Zusatzrequest pro Treffer noetig.
    """
    result = _search_result_from_entry(_api_entry(), 2024)

    for field in ("player_id", "name", "photo", "age", "nationality", "season",
                  "team_name", "team_logo", "league_code", "league_label",
                  "position", "position_label", "minutes", "comparable"):
        assert field in result, f"Feld {field} fehlt im Suchtreffer"


def test_suchtreffer_uebersetzt_position():
    result = _search_result_from_entry(_api_entry(position="Goalkeeper"), 2024)
    assert result["position"] == "Goalkeeper"
    assert result["position_label"] == "Torhüter"


def test_spieler_ausserhalb_der_top5_ist_nicht_vergleichbar():
    """
    Wer nur in der Champions League gespielt hat, kann nicht eingeordnet
    werden. Er wird trotzdem angezeigt, aber als nicht auswaehlbar - ihn
    wegzulassen waere fuer den Nutzer verwirrend.
    """
    result = _search_result_from_entry(
        _api_entry(league_id=CHAMPIONS_LEAGUE_ID), 2024
    )
    assert result["comparable"] is False
    assert result["league_code"] is None


def test_vergleichbarer_spieler_ist_markiert():
    result = _search_result_from_entry(_api_entry(league_id=BUNDESLIGA_ID), 2024)
    assert result["comparable"] is True
    assert result["league_code"] == "bl1"
    assert result["league_label"] == "Bundesliga"


def test_saison_steht_im_treffer():
    """
    Derselbe Spieler hat je Saison einen eigenen Datensatz. Ohne Saison im
    Treffer koennte das Frontend zwei Eintraege nicht unterscheiden.
    """
    a = _search_result_from_entry(_api_entry(player_id=7), 2023)
    b = _search_result_from_entry(_api_entry(player_id=7), 2024)
    assert a["season"] == 2023
    assert b["season"] == 2024
    assert a["player_id"] == b["player_id"]


# ---------------------------------------------------------------------------
# 2. HTTP-Routen
# ---------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    """
    Flask-Testclient mit gemockter API.

    Ohne den Mock wuerde jeder Testlauf echte Requests ausloesen und das
    Tageskontingent verbrauchen.
    """
    monkeypatch.setenv("APISPORTS_KEY", "test-key")
    monkeypatch.setenv("FOOTBALL_DATA_KEY", "test-key")

    import app as app_module

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def test_player_seasons_liefert_saisonliste(client):
    response = client.get("/api/player-seasons")
    assert response.status_code == 200

    data = response.get_json()
    assert data["seasons"]
    assert data["min_query_length"] >= 3
    assert len(data["leagues"]) == 5

    for season in data["seasons"]:
        assert "season" in season
        assert "label" in season
        assert "percentiles_available" in season


def test_player_seasons_kennzeichnet_verfuegbare_perzentile(client):
    """
    Das Frontend muss vorab wissen, fuer welche Saison Perzentile existieren,
    statt es erst nach dem Vergleich zu erfahren.
    """
    data = client.get("/api/player-seasons").get_json()
    assert all(isinstance(s["percentiles_available"], bool) for s in data["seasons"])


def test_suche_lehnt_zu_kurze_eingabe_ab(client):
    response = client.get("/api/player-search?q=ka&season=2024")
    assert response.status_code == 400
    assert response.get_json()["results"] == []


def test_suche_lehnt_fehlende_saison_ab(client):
    response = client.get("/api/player-search?q=kane")
    assert response.status_code == 400


def test_suche_lehnt_unmoegliche_saison_ab(client):
    response = client.get("/api/player-search?q=kane&season=1990")
    assert response.status_code == 400


def test_suche_liefert_treffer(client, monkeypatch):
    import app as app_module

    monkeypatch.setattr(
        app_module, "player_search_players",
        lambda query, season: [_search_result_from_entry(_api_entry(), season)],
    )

    response = client.get("/api/player-search?q=test&season=2024")
    assert response.status_code == 200

    data = response.get_json()
    assert data["query"] == "test"
    assert data["season"] == 2024
    assert len(data["results"]) == 1
    assert data["comparable_count"] == 1


def test_suche_meldet_rate_limit_verstaendlich(client, monkeypatch):
    """
    Ein aufgebrauchtes Kontingent darf keinen 500er erzeugen. Der Nutzer
    soll erfahren, was los ist.
    """
    import app as app_module
    from src.api.apisports_api import ApisportsRateLimit

    def _raise(query, season):
        raise ApisportsRateLimit("Limit erreicht")

    monkeypatch.setattr(app_module, "player_search_players", _raise)

    response = client.get("/api/player-search?q=test&season=2024")
    assert response.status_code == 429
    assert "error" in response.get_json()


def test_suche_meldet_ausfall_verstaendlich(client, monkeypatch):
    import app as app_module
    from src.api.apisports_api import ApisportsUnavailable

    def _raise(query, season):
        raise ApisportsUnavailable("keine Verbindung")

    monkeypatch.setattr(app_module, "player_search_players", _raise)

    response = client.get("/api/player-search?q=test&season=2024")
    assert response.status_code == 503


def test_vergleich_braucht_zwei_ids(client):
    assert client.get("/api/player-compare?a=1").status_code == 400
    assert client.get("/api/player-compare").status_code == 400


def test_vergleich_lehnt_identische_spieler_ab(client):
    """Ein Spieler mit sich selbst verglichen ergibt keinen Erkenntnisgewinn."""
    response = client.get("/api/player-compare?a=5&b=5&season_a=2024")
    assert response.status_code == 400
    assert "unterschiedliche" in response.get_json()["error"].lower()


def test_vergleich_liefert_beide_spieler(client, monkeypatch):
    import app as app_module

    def _profile(player_id, season, scope=None):
        return build_player_profile(_api_entry(player_id=player_id), season, scope=scope)

    monkeypatch.setattr(app_module, "get_player_season_profile", _profile)
    monkeypatch.setattr(app_module, "load_percentile_snapshot", lambda season: None)

    response = client.get("/api/player-compare?a=1&b=2&season_a=2024")
    assert response.status_code == 200

    data = response.get_json()
    assert data["player_a"]["player_id"] == 1
    assert data["player_b"]["player_id"] == 2
    assert data["comparison"]["mode"] in ("position", "general")
    assert "min_minutes" in data


def test_vergleich_erlaubt_unterschiedliche_saisons(client, monkeypatch):
    """
    "Musiala 2023/24 gegen Musiala 2025/26" ist ein sinnvoller Vergleich.
    Beide Spieler duerfen aus verschiedenen Jahrgaengen stammen.
    """
    import app as app_module

    seen = []

    def _profile(player_id, season, scope=None):
        seen.append((player_id, season))
        return build_player_profile(_api_entry(player_id=player_id), season, scope=scope)

    monkeypatch.setattr(app_module, "get_player_season_profile", _profile)
    monkeypatch.setattr(app_module, "load_percentile_snapshot", lambda season: None)

    response = client.get(
        "/api/player-compare?a=1&b=2&season_a=2023&season_b=2024"
    )
    assert response.status_code == 200
    assert (1, 2023) in seen
    assert (2, 2024) in seen


def test_vergleich_ohne_snapshot_liefert_rohwerte(client, monkeypatch):
    """
    Ohne Referenzpool gibt es keine Perzentile - die Rohwerte muessen aber
    trotzdem ankommen. Ein leerer Vergleich waere die schlechtere Antwort.
    """
    import app as app_module

    monkeypatch.setattr(
        app_module, "get_player_season_profile",
        lambda pid, season, scope=None: build_player_profile(
            _api_entry(player_id=pid), season, scope=scope),
    )
    monkeypatch.setattr(app_module, "load_percentile_snapshot", lambda season: None)

    data = client.get("/api/player-compare?a=1&b=2&season_a=2024").get_json()
    comparison = data["comparison"]

    assert comparison["percentiles_available"] is False
    assert comparison["metrics"]
    assert any(m["value_a"] is not None for m in comparison["metrics"])


def test_bestehende_routen_funktionieren_weiter(client):
    """Regressionsschutz: Phase 3 darf Phase 1 und 2 nicht beschaedigen."""
    for path in ("/", "/impressum", "/datenschutz", "/kontakt", "/feedback"):
        assert client.get(path).status_code == 200, f"{path} kaputt"


# ---------------------------------------------------------------------------
# 3. Frontend-Konsistenz
# ---------------------------------------------------------------------------

def _read(*parts):
    with open(os.path.join(PROJECT_ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def test_alle_pc_ids_aus_dem_javascript_existieren_im_html():
    """
    Fehlerklasse, die zur Laufzeit still bleibt: el("pc-xyz") liefert null,
    das Skript bricht erst spaeter an unerwarteter Stelle ab.
    """
    html = _read("templates", "index.html")
    js = _read("static", "script.js")

    html_ids = set(re.findall(r'id="([^"]+)"', html))
    used_ids = set(re.findall(r'el\("(pc-[^"]+)"\)', js))

    missing = sorted(used_ids - html_ids)
    assert not missing, f"IDs im JS ohne Entsprechung im HTML: {missing}"


def test_spielerbereich_hat_kein_platzhalter_mehr():
    """Der Bereich ist jetzt echt und darf nicht mehr als Platzhalter erscheinen."""
    html = _read("templates", "index.html")
    players_section = html[html.find('id="mode-players"'):]
    players_section = players_section[:players_section.find("</main>")]

    assert "placeholder-panel" not in players_section
    assert "pc-search-a" in players_section
    assert "pc-search-b" in players_section


def test_suchfelder_sind_barrierefrei():
    """
    Ein Autocomplete ohne ARIA ist fuer Screenreader unbedienbar.
    Beide Felder brauchen dieselbe Auszeichnung.
    """
    html = _read("templates", "index.html")

    for slot in ("a", "b"):
        block = html[html.find(f'id="pc-search-{slot}"'):]
        block = block[:700]
        assert 'role="combobox"' in block, f"Slot {slot}: role fehlt"
        assert "aria-autocomplete" in block, f"Slot {slot}: aria-autocomplete fehlt"
        assert "aria-expanded" in block, f"Slot {slot}: aria-expanded fehlt"
        assert "aria-controls" in block, f"Slot {slot}: aria-controls fehlt"


def test_suchfelder_haben_labels():
    html = _read("templates", "index.html")
    for slot in ("a", "b"):
        assert f'for="pc-search-{slot}"' in html, f"Label fuer Slot {slot} fehlt"


def test_javascript_ist_syntaktisch_ausgewogen():
    """Grobe Klammerpruefung, faengt abgeschnittene Dateien ab."""
    js = _read("static", "script.js")
    assert js.count("{") == js.count("}"), "Geschweifte Klammern unausgewogen"
    assert js.count("(") == js.count(")"), "Runde Klammern unausgewogen"


def test_debouncing_ist_implementiert():
    """
    Ohne Entprellung feuert jede Tastatureingabe einen API-Request.
    Bei einem Tageskontingent ist das nicht tragbar.
    """
    js = _read("static", "script.js")

    # Entprellung besteht aus drei Teilen: alten Timer abbrechen,
    # neuen setzen, mit definierter Verzoegerung.
    assert "clearTimeout" in js, "Alter Timer wird nicht abgebrochen"
    assert "setTimeout" in js, "Kein verzoegerter Aufruf"
    assert "PC_SEARCH_DELAY" in js, "Keine definierte Entprellungsdauer"


def test_veraltete_suchantworten_werden_verworfen():
    """
    Race Condition: tippt jemand schnell, koennen Antworten in falscher
    Reihenfolge eintreffen. Eine alte Antwort darf eine neue nicht
    ueberschreiben.
    """
    js = _read("static", "script.js")
    assert "requestId" in js or "requestToken" in js or "latestRequest" in js, \
        "Kein Schutz gegen veraltete Suchantworten erkennbar"


def test_radar_wird_als_svg_gebaut():
    js = _read("static", "script.js")
    assert "createElementNS" in js, "Radar braucht echtes SVG, kein innerHTML"
    assert "http://www.w3.org/2000/svg" in js


def test_service_worker_version_wurde_erhoeht():
    """
    Ohne neue Cache-Version bekommen installierte PWAs die neuen Dateien
    nicht. Das ist in diesem Projekt schon einmal passiert.
    """
    sw = _read("static", "sw.js")
    match = re.search(r'CACHE_NAME\s*=\s*"footsim-v(\d+)"', sw)
    assert match, "CACHE_NAME nicht gefunden"
    assert int(match.group(1)) >= 9, "Cache-Version muss fuer Phase 3 erhoeht sein"


def test_css_enthaelt_die_neuen_komponenten():
    css = _read("static", "style.css")
    for selector in (".pc-search-input", ".pc-results", ".pc-radar",
                     ".pc-metric-row", ".pc-player-card"):
        assert selector in css, f"CSS fehlt fuer {selector}"


def test_keine_browser_speicher_apis_im_frontend():
    """
    localStorage wird in diesem Projekt bewusst nicht verwendet: die App
    laeuft auch als installierte PWA und soll ohne Speicherzugriff starten.
    """
    js = _read("static", "script.js")
    code_only = re.sub(r"//.*", "", js)
    assert "localStorage" not in code_only
    assert "sessionStorage" not in code_only


# ---------------------------------------------------------------------------
# Phase 3.2: Wettbewerbsumfang
# ---------------------------------------------------------------------------

def test_vergleich_reicht_scope_durch(client, monkeypatch):
    """Der scope-Parameter muss beim Profilaufbau ankommen."""
    import app as app_module

    seen = []

    def _profile(player_id, season, scope=None):
        seen.append(scope)
        return build_player_profile(_api_entry(player_id=player_id), season, scope=scope)

    monkeypatch.setattr(app_module, "get_player_season_profile", _profile)
    monkeypatch.setattr(app_module, "load_percentile_snapshot", lambda season: None)

    client.get("/api/player-compare?a=1&b=2&season_a=2024&scope=league")
    assert seen == ["league", "league"]


def test_unbekannter_scope_faellt_auf_standard(client, monkeypatch):
    """
    Ein ungueltiger Wert darf keinen Fehler erzeugen, sondern faellt auf
    den Standard zurueck. Sonst koennte ein veralteter Link die Seite
    unbrauchbar machen.
    """
    import app as app_module

    seen = []

    def _profile(player_id, season, scope=None):
        seen.append(scope)
        return build_player_profile(_api_entry(player_id=player_id), season, scope=scope)

    monkeypatch.setattr(app_module, "get_player_season_profile", _profile)
    monkeypatch.setattr(app_module, "load_percentile_snapshot", lambda season: None)

    response = client.get("/api/player-compare?a=1&b=2&season_a=2024&scope=quatsch")
    assert response.status_code == 200
    assert seen == ["club_all", "club_all"]


def test_fehlender_scope_ist_club_all(client, monkeypatch):
    """Ohne Parameter gilt der Standard: alle Vereinswettbewerbe."""
    import app as app_module

    seen = []

    def _profile(player_id, season, scope=None):
        seen.append(scope)
        return build_player_profile(_api_entry(player_id=player_id), season, scope=scope)

    monkeypatch.setattr(app_module, "get_player_season_profile", _profile)
    monkeypatch.setattr(app_module, "load_percentile_snapshot", lambda season: None)

    client.get("/api/player-compare?a=1&b=2&season_a=2024")
    assert seen == ["club_all", "club_all"]
