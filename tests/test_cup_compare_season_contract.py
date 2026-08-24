"""
Saisonvertrag des Champions-League-Ligavergleichs.

HINTERGRUND
Live reproduziert: Saison 2026/27 ausgewaehlt, Ergebnis trug die
Ueberschrift "CHAMPIONS LEAGUE 2025/26" und wertete auch die Spiele
jener Saison aus. Drei zusammenhaengende Ursachen:

  1. Das Frontend sendete fuer den CL-Vergleich gar keinen
     Saisonparameter (withSeason statt withExplicitSeason).
  2. get_cup_matches() pruefte nicht, ob die Provider-Antwort
     tatsaechlich zur angefragten Saison gehoert. football-data.org
     liefert bei einer noch nicht gestarteten Saison still die
     laufende zurueck.
  3. api_cup_compare() gab denselben Wert None an zwei Loader weiter,
     die ihn unterschiedlich aufloesen - CL-Spiele landeten bei 2025,
     die Ligakader bei 2026.

Der Vertrag, den diese Tests festhalten: die angefragte Saison ist die
einzige, die verwendet, ausgewertet und ausgegeben wird. Gibt es fuer
sie keine Daten, sagt FootSim das - und weicht nicht aus.
"""

import json
import os
import re

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _clear_memory_cache():
    """cached_call() ist prozessweit - sonst faerben Tests aufeinander ab."""
    from src.utils import cache
    cache.clear_all()
    yield
    cache.clear_all()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APISPORTS_KEY", "test-key")
    monkeypatch.setenv("FOOTBALL_DATA_KEY", "test-key")
    import app as app_module
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Testdaten
# ---------------------------------------------------------------------------

def _raw_match(match_id, season_start, home_id, away_id, stage="LEAGUE_STAGE"):
    """Rohformat von football-data.org, wie _get_json es liefert."""
    return {
        "id": match_id,
        "stage": stage,
        "group": None,
        "matchday": 1,
        "utcDate": f"{season_start}-09-17T19:00:00Z",
        "season": {"startDate": f"{season_start}-09-16"},
        "homeTeam": {"id": home_id, "name": f"Team {home_id}", "shortName": f"T{home_id}"},
        "awayTeam": {"id": away_id, "name": f"Team {away_id}", "shortName": f"T{away_id}"},
        "score": {
            "fullTime": {"home": 2, "away": 1},
            "winner": "HOME_TEAM",
            "duration": "REGULAR",
            "penalties": {},
        },
    }


def _cooked_match(match_id, home_id, away_id, stage="LEAGUE_STAGE"):
    """Aufbereitetes Format, wie get_cup_matches es zurueckgibt."""
    return {
        "id": match_id,
        "stage": stage,
        "group": None,
        "matchday": 1,
        "utc_date": "2026-09-17T19:00:00Z",
        "home_id": home_id,
        "away_id": away_id,
        "home_team": f"T{home_id}",
        "away_team": f"T{away_id}",
        "home_goals": 2,
        "away_goals": 1,
        "winner": "HOME_TEAM",
        "duration": "REGULAR",
        "penalties_home": None,
        "penalties_away": None,
    }


def _teams(*ids):
    return {i: {"id": i, "name": f"Team {i}", "country": "X"} for i in ids}


# ===========================================================================
# A2 - Provider-Fallback auf Ebene des Loaders abwehren
# ===========================================================================

class TestProviderFallbackAbgewehrt:

    def test_antwort_einer_anderen_saison_wird_verworfen(self, monkeypatch):
        """
        Angefragt 2026, geliefert 2025 - das darf nicht als Ergebnis
        der angefragten Saison durchgehen.
        """
        from src.api import league_api

        monkeypatch.setattr(
            league_api, "_get_json",
            lambda path, params=None, retries=3: {
                "matches": [_raw_match(1, 2025, 10, 20)]
            },
        )

        result = league_api.get_cup_matches("CL", season=2026)
        assert result == [], (
            "Provider lieferte 2025/26-Spiele auf eine 2026/27-Anfrage - "
            "sie wurden faelschlich akzeptiert"
        )

    def test_antwort_der_angefragten_saison_wird_akzeptiert(self, monkeypatch):
        from src.api import league_api

        monkeypatch.setattr(
            league_api, "_get_json",
            lambda path, params=None, retries=3: {
                "matches": [_raw_match(1, 2025, 10, 20)]
            },
        )

        result = league_api.get_cup_matches("CL", season=2025)
        assert len(result) == 1
        assert result[0]["home_id"] == 10

    def test_domestic_wettbewerbe_bleiben_unangetastet(self, monkeypatch):
        """
        Die Validierung gilt bewusst nur fuer CL. Domestic-Ligen haben
        das Problem nicht und duerfen nicht mit abgewiesen werden.
        """
        from src.api import league_api

        monkeypatch.setattr(
            league_api, "_get_json",
            lambda path, params=None, retries=3: {
                "matches": [_raw_match(1, 2025, 10, 20)]
            },
        )

        result = league_api.get_cup_matches("BL1", season=2026)
        assert len(result) == 1

    def test_cache_key_unterscheidet_die_saisons(self, monkeypatch):
        """
        Ohne saisonabhaengigen Key wuerde die zweite Saison die Antwort
        der ersten erben.
        """
        from src.api import league_api

        calls = []

        def fake(path, params=None, retries=3):
            calls.append(params.get("season"))
            year = params.get("season")
            return {"matches": [_raw_match(1, year, 10, 20)]}

        monkeypatch.setattr(league_api, "_get_json", fake)

        league_api.get_cup_matches("CL", season=2025)
        league_api.get_cup_matches("CL", season=2024)
        assert calls == [2025, 2024]


# ===========================================================================
# A3 - Genau eine Saison je Request
# ===========================================================================

class TestEineSaisonProRequest:

    def test_spiele_und_kader_verwenden_dieselbe_saison(self, client, monkeypatch):
        """
        Der Kernfehler: get_cup_matches("CL", None) ergab 2025,
        get_competition_teams("FL1", None) ergab 2026. Beide Loader
        muessen denselben, explizit aufgeloesten Wert bekommen.
        """
        import app as app_module

        seen = {}

        def fake_cup(api_code, season=None):
            seen["matches"] = season
            return [_cooked_match(1, 10, 20)]

        def fake_teams(api_code, season=None):
            seen.setdefault("teams", []).append(season)
            return _teams(10) if api_code == "FL1" else _teams(20)

        monkeypatch.setattr(app_module, "get_cup_matches", fake_cup)
        monkeypatch.setattr(app_module, "get_competition_teams", fake_teams)

        client.get("/api/cup-compare?leagues=fl1,sa&season=2026&cup=cl")

        assert seen["matches"] == 2026
        assert seen["teams"] == [2026, 2026], (
            f"Kader wurden mit {seen['teams']} statt 2026 geladen"
        )

    def test_ohne_parameter_wird_die_saison_trotzdem_einmal_festgelegt(
            self, client, monkeypatch):
        """
        Auch ohne season= darf sich nicht jeder Loader seine eigene
        Saison auto-erkennen. Es muss genau ein Wert entstehen.
        """
        import app as app_module

        seen = {}

        def fake_cup(api_code, season=None):
            seen["matches"] = season
            return [_cooked_match(1, 10, 20)]

        def fake_teams(api_code, season=None):
            seen.setdefault("teams", []).append(season)
            return _teams(10) if api_code == "FL1" else _teams(20)

        monkeypatch.setattr(app_module, "get_cup_matches", fake_cup)
        monkeypatch.setattr(app_module, "get_competition_teams", fake_teams)
        monkeypatch.setattr(app_module, "get_current_season", lambda code: 2026)

        client.get("/api/cup-compare?leagues=fl1,sa&cup=cl")

        assert seen["matches"] is not None, "Saison wurde nicht aufgeloest"
        assert set(seen["teams"]) == {seen["matches"]}, (
            "Spiele und Kader wurden mit verschiedenen Saisons geladen"
        )

    def test_response_saison_ist_die_angefragte(self, client, monkeypatch):
        import app as app_module

        monkeypatch.setattr(app_module, "get_cup_matches",
                            lambda api_code, season=None: [_cooked_match(1, 10, 20)])
        monkeypatch.setattr(app_module, "get_competition_teams",
                            lambda api_code, season=None: (
                                _teams(10) if api_code == "FL1" else _teams(20)))

        response = client.get("/api/cup-compare?leagues=fl1,sa&season=2025&cup=cl")
        assert response.status_code == 200
        assert response.get_json()["season"] == 2025


# ===========================================================================
# A4 - Ehrliche Antwort ohne Daten
# ===========================================================================

class TestKeineDatenFuerDieSaison:

    def test_leere_spieleliste_ergibt_pending_und_kein_503(self, client, monkeypatch):
        import app as app_module

        monkeypatch.setattr(app_module, "get_cup_matches",
                            lambda api_code, season=None: [])

        response = client.get("/api/cup-compare?leagues=fl1,sa&season=2026&cup=cl")

        assert response.status_code == 404, (
            "503 bedeutet Stoerung. Eine noch nicht gestartete Saison ist "
            "keine Stoerung."
        )

        data = response.get_json()
        assert data["code"] == app_module.COMPETITION_DATA_PENDING
        assert data["success"] is False
        assert data["season"] == 2026
        assert data["season_label"] == "2026/27"
        assert data["competition"] == "cl"
        assert data["error_key"] == app_module.CUP_COMPARE_PENDING_TITLE_KEY
        assert data["error_text_key"] == app_module.CUP_COMPARE_PENDING_TEXT_KEY
        assert data["error_params"]["season"] == "2026/27"

    def test_provider_404_wird_zum_pending_zustand(self, client, monkeypatch):
        """
        Der eigentliche Livefehler: football-data antwortet fuer eine noch
        nicht existierende Saison mit 404. Die Exception lief bis in
        api_cup_compare und wurde dort zu HTTP 503 mit dem rohen
        Anbietertext - der Nutzer sah einen Serverfehler.
        """
        from src.api import league_api
        import app as app_module

        def not_found(path, params=None, retries=3):
            raise league_api.ApiUnavailable(
                "Daten fuer diesen Wettbewerb nicht gefunden", status_code=404)

        monkeypatch.setattr(league_api, "_get_json", not_found)
        monkeypatch.setattr(app_module, "get_competition_teams",
                            lambda api_code, season=None: _teams(10))

        response = client.get("/api/cup-compare?leagues=fl1,sa&season=2026&cup=cl")

        assert response.status_code == 404
        assert response.get_json()["code"] == app_module.COMPETITION_DATA_PENDING

    def test_spiele_ohne_jede_kaderzuordnung_sind_ebenfalls_pending(
            self, client, monkeypatch):
        """
        Teilverfuegbarkeit: Spiele da, aber keine Liga hat einen Kader.
        Ohne Zuordnung waere der Vergleich eine Tabelle aus Nullen.
        """
        import app as app_module

        monkeypatch.setattr(app_module, "get_cup_matches",
                            lambda api_code, season=None: [_cooked_match(1, 10, 20)])
        monkeypatch.setattr(app_module, "get_competition_teams",
                            lambda api_code, season=None: {})

        response = client.get("/api/cup-compare?leagues=fl1,sa&season=2026&cup=cl")
        assert response.status_code == 404
        assert response.get_json()["code"] == app_module.COMPETITION_DATA_PENDING

    def test_keine_2025er_daten_in_einer_2026er_antwort(self, client, monkeypatch):
        """
        Der zentrale Akzeptanztest: nirgends im Response darf 2025
        auftauchen, wenn 2026 angefragt wurde.
        """
        from src.api import league_api
        import app as app_module

        # Provider antwortet stur mit 2025/26 - der reale Fall.
        monkeypatch.setattr(
            league_api, "_get_json",
            lambda path, params=None, retries=3: {
                "matches": [_raw_match(1, 2025, 10, 20)]
            },
        )
        monkeypatch.setattr(app_module, "get_competition_teams",
                            lambda api_code, season=None: (
                                _teams(10) if api_code == "FL1" else _teams(20)))

        response = client.get("/api/cup-compare?leagues=fl1,sa&season=2026&cup=cl")

        assert response.status_code == 404
        body = response.get_data(as_text=True)
        assert "2025" not in body, f"2025 taucht in der 2026er-Antwort auf: {body[:200]}"


# ===========================================================================
# Fehlervertrag und Phasen
# ===========================================================================

class TestFehlervertragUndPhasen:

    def test_echter_ausfall_bleibt_ein_technischer_fehler(self, client, monkeypatch):
        """
        Ein WIRKLICHER Ausfall - Timeout, Netzwerk, Rate Limit - darf
        weiterhin 503 sein. Er muss sich aber klar vom Pending-Zustand
        unterscheiden und dem Nutzer trotzdem einen freundlichen,
        uebersetzten Text zeigen statt eines Statuscodes.
        """
        import app as app_module
        from src.api.league_api import ApiUnavailable

        def boom(api_code, season=None):
            raise ApiUnavailable("Netzwerkfehler: connection reset")

        monkeypatch.setattr(app_module, "get_cup_matches", boom)

        response = client.get("/api/cup-compare?leagues=fl1,sa&season=2025&cup=cl")
        data = response.get_json()

        assert response.status_code == 503
        assert data["code"] == "EXTERNAL_API_UNAVAILABLE"
        assert data["code"] != app_module.COMPETITION_DATA_PENDING
        assert data["error_key"] == app_module.EXTERNAL_API_ERROR_KEY, (
            "Ohne error_key faellt das Frontend auf 'Request failed ({status})' zurueck"
        )

    def test_ungueltige_anfragen_bleiben_getrennt(self, client):
        """
        Fehlerhafte Parameter sind weder Pending noch Ausfall - sie
        muessen ueber die bestehende Validierung mit 400 laufen.
        """
        import app as app_module

        zu_wenige = client.get("/api/cup-compare?leagues=fl1&season=2025&cup=cl")
        assert zu_wenige.status_code == 400
        assert zu_wenige.get_json().get("code") != app_module.COMPETITION_DATA_PENDING

        unbekannt = client.get("/api/cup-compare?leagues=fl1,sa&season=2025&cup=xyz")
        assert unbekannt.status_code == 400
        assert unbekannt.get_json().get("code") != app_module.COMPETITION_DATA_PENDING

    @pytest.mark.parametrize("phase", ["all", "league", "knockout"])
    def test_alle_phasenfilter_bleiben_bedienbar(self, client, monkeypatch, phase):
        import app as app_module

        monkeypatch.setattr(app_module, "get_cup_matches",
                            lambda api_code, season=None: [
                                _cooked_match(1, 10, 20, "LEAGUE_STAGE"),
                                _cooked_match(2, 10, 20, "FINAL"),
                            ])
        monkeypatch.setattr(app_module, "get_competition_teams",
                            lambda api_code, season=None: (
                                _teams(10) if api_code == "FL1" else _teams(20)))

        response = client.get(
            f"/api/cup-compare?leagues=fl1,sa&season=2025&cup=cl&phase={phase}")
        assert response.status_code == 200
        assert response.get_json()["season"] == 2025


# ===========================================================================
# A1 / A5 - Frontend-Vertrag
# ===========================================================================

class TestFrontendVertrag:

    @pytest.fixture
    def script_js(self):
        path = os.path.join(PROJECT_ROOT, "static", "script.js")
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def test_cl_vergleich_sendet_die_saison_explizit(self, script_js):
        start = script_js.index("async function runComparison(")
        end = script_js.index("}", script_js.index("compareBtn.textContent = t(\"compare.run\")", start))
        block = script_js[start:end]

        assert "cup-compare" in block
        cup_line = next(line for line in block.splitlines() if "cup-compare" in line)
        assert "withExplicitSeason(" in cup_line, (
            "Der CL-Vergleich muss die sichtbare Saison explizit senden - "
            f"gefunden: {cup_line.strip()}"
        )

    def test_kein_cl_request_faellt_auf_withSeason_zurueck(self, script_js):
        """
        withSeason() laesst den Parameter bei der laufenden Saison weg.
        Fuer CL ist das falsch, weil dessen Provider-Saison nachlaeuft.
        """
        offenders = []
        for number, line in enumerate(script_js.splitlines(), start=1):
            if "withSeason(" in line and "function withSeason" not in line:
                if "/api/cl-" in line or "cup-compare" in line or "competition=cl" in line:
                    offenders.append(f"{number}: {line.strip()}")
        assert not offenders, "CL-Requests mit withSeason():\n" + "\n".join(offenders)

    def test_phasenwechsel_leert_ein_altes_ergebnis(self, script_js):
        start = script_js.index('document.querySelectorAll(".phase-btn")')
        end = script_js.index("function renderCompareLeagues", start)
        block = script_js[start:end]

        assert "compareResult.innerHTML" in block, (
            "Beim Phasenwechsel bleibt ein Ergebnis der vorherigen Phase stehen"
        )

    def test_keine_hardcodierte_saison_in_der_ergebnisueberschrift(self, script_js):
        start = script_js.index("function renderCupComparison(")
        end = script_js.index("\n}", start)
        block = script_js[start:end]

        assert "data.season" in block
        assert not re.search(r"\b20\d\d\b", block), (
            "Die Ueberschrift darf keine feste Jahreszahl enthalten"
        )


# ===========================================================================
# i18n
# ===========================================================================

class TestUebersetzungen:

    @pytest.fixture
    def catalogs(self):
        base = os.path.join(PROJECT_ROOT, "static", "i18n")
        with open(os.path.join(base, "de.json"), encoding="utf-8") as handle:
            de = json.load(handle)
        with open(os.path.join(base, "en.json"), encoding="utf-8") as handle:
            en = json.load(handle)
        return de, en

    def test_pending_schluessel_existieren_in_beiden_katalogen(self, catalogs):
        de, en = catalogs
        import app as app_module

        for key in (app_module.CUP_COMPARE_PENDING_TITLE_KEY,
                    app_module.CUP_COMPARE_PENDING_TEXT_KEY,
                    app_module.EXTERNAL_API_ERROR_KEY):
            assert key in de, f"{key} fehlt im deutschen Katalog"
            assert key in en, f"{key} fehlt im englischen Katalog"

    def test_titel_traegt_die_saison_als_platzhalter(self, catalogs):
        de, en = catalogs
        import app as app_module

        key = app_module.CUP_COMPARE_PENDING_TITLE_KEY
        assert "{season}" in de[key], "Die deutsche Meldung nennt die Saison nicht"
        assert "{season}" in en[key], "Die englische Meldung nennt die Saison nicht"
        # Keine feste Jahreszahl im Katalog - sonst braeuchte jede neue
        # Saison eine Uebersetzungsaenderung.
        assert not re.search(r"\b20\d\d\b", de[key])
        assert not re.search(r"\b20\d\d\b", en[key])

    def test_deutsche_texte_verwenden_echte_umlaute(self, catalogs):
        """
        Der Livefehler zeigte "Daten fuer diesen Wettbewerb nicht
        gefunden" - ein ASCII-Ersatztext aus dem Backend, der ueber den
        Legacy-Pfad direkt in die Oberflaeche durchschlug.
        """
        de, _ = catalogs
        import app as app_module

        for key in (app_module.CUP_COMPARE_PENDING_TITLE_KEY,
                    app_module.CUP_COMPARE_PENDING_TEXT_KEY,
                    app_module.EXTERNAL_API_ERROR_KEY):
            value = de[key]
            for ascii_ersatz in ("fuer", "ueber", "verfuegbar", "benoetigt",
                                 "vollstaendig", "koennen", "waehrend"):
                assert ascii_ersatz not in value, f"{ascii_ersatz} in {key}"

        titel = de[app_module.CUP_COMPARE_PENDING_TITLE_KEY]
        assert "für" in titel and "verfügbar" in titel

    def test_texte_bleiben_in_ihrer_sprache(self, catalogs):
        """Kein deutscher Text im englischen Katalog und umgekehrt."""
        de, en = catalogs
        import app as app_module

        key = app_module.CUP_COMPARE_PENDING_TEXT_KEY
        assert "Champions League data" in en[key]
        assert "Datenquelle" in de[key]
        assert "Datenquelle" not in en[key]

    def test_kataloge_bleiben_symmetrisch(self, catalogs):
        de, en = catalogs
        assert set(de) == set(en)


def _read(relative):
    with open(os.path.join(PROJECT_ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


# ===========================================================================
# Negativer Cache: spaeter verfuegbare Daten muessen durchkommen
# ===========================================================================

def _spy_cached_call(recorder):
    """Ersatz fuer cached_call, der die WIRKSAME TTL festhaelt."""
    def fake(key, ttl_seconds, loader, empty_ttl_seconds=None):
        value = loader()
        wirksam = ttl_seconds
        if empty_ttl_seconds is not None and not value:
            wirksam = empty_ttl_seconds
        recorder[key] = wirksam
        return value
    return fake


class TestSpaetereVerfuegbarkeit:

    def test_leeres_ergebnis_wird_nur_kurz_gehalten(self, monkeypatch):
        """
        Kern der Anforderung "keine dauerhafte Sperre".

        get_cup_matches cacht zwei Stunden. Ein leeres Ergebnis heisst
        aber nur "Saison noch nicht gestartet" - mit voller TTL bliebe
        der Wettbewerb nach dem ersten Abruf zwei Stunden leer, obwohl
        die Auslosung inzwischen vorliegen kann.
        """
        from src.api import league_api
        from src.utils import cache

        gesehen = {}
        monkeypatch.setattr(league_api, "cached_call", _spy_cached_call(gesehen))
        monkeypatch.setattr(
            league_api, "_get_json",
            lambda path, params=None, retries=3: {"matches": []})

        league_api.get_cup_matches("CL", season=2026)

        ttl = gesehen["cup_matches:CL:2026"]
        assert ttl == cache.TTL_EMPTY_RESULT, (
            f"Leeres Ergebnis wird {ttl}s gehalten statt {cache.TTL_EMPTY_RESULT}s"
        )
        assert ttl < cache.TTL_CUP_MATCHES

    def test_volles_ergebnis_behaelt_die_lange_ttl(self, monkeypatch):
        """Gegenprobe: echte Daten duerfen weiterhin lange gecacht werden."""
        from src.api import league_api
        from src.utils import cache

        gesehen = {}
        monkeypatch.setattr(league_api, "cached_call", _spy_cached_call(gesehen))
        monkeypatch.setattr(
            league_api, "_get_json",
            lambda path, params=None, retries=3: {
                "matches": [_raw_match(1, 2025, 10, 20)]})

        league_api.get_cup_matches("CL", season=2025)
        assert gesehen["cup_matches:CL:2025"] == cache.TTL_CUP_MATCHES

    def test_spaeter_verfuegbare_daten_kommen_durch(self, monkeypatch):
        """
        Zeitverlauf: erst liefert die Quelle nichts, danach echte Daten
        derselben Saison. Nach Ablauf der kurzen TTL muss der zweite
        Abruf sie liefern - ohne Code- oder Konfigurationsaenderung.
        """
        from src.api import league_api
        from src.utils import cache

        antworten = [{"matches": []},
                     {"matches": [_raw_match(1, 2026, 10, 20)]}]

        def fake(path, params=None, retries=3):
            return antworten.pop(0) if antworten else {"matches": []}

        monkeypatch.setattr(league_api, "_get_json", fake)

        assert league_api.get_cup_matches("CL", season=2026) == []

        # Kurze TTL abgelaufen - im Test durch Verwerfen des Eintrags,
        # im Betrieb nach TTL_EMPTY_RESULT.
        cache.invalidate("cup_matches:CL:2026")

        danach = league_api.get_cup_matches("CL", season=2026)
        assert len(danach) == 1, "spaeter verfuegbare Daten kommen nicht durch"
        assert danach[0]["home_id"] == 10

    def test_keine_feste_sperrliste_fuer_saisons(self):
        """
        Es darf keine hartkodierte Jahresliste geben, die eine Saison
        grundsaetzlich ausschliesst - sonst braeuchte die Freischaltung
        eine Codeaenderung statt neuer Daten.
        """
        for relative in ("app.py", os.path.join("src", "api", "league_api.py")):
            code = "\n".join(
                line for line in _read(relative).splitlines()
                if not line.strip().startswith("#")
            )
            for verboten in ("season == 2026", "season != 2026", "2026 not in",
                             "BLOCKED_SEASONS", "UNAVAILABLE_SEASONS"):
                assert verboten not in code, f"{verboten} in {relative}"


# ===========================================================================
# Frontend: ruhiger Leerzustand statt technischer Fehlermeldung
# ===========================================================================

class TestFrontendLeerzustand:

    @pytest.fixture
    def script_js(self):
        return _read(os.path.join("static", "script.js"))

    @pytest.fixture
    def pending_block(self, script_js):
        start = script_js.index("function renderComparePending(")
        end = script_js.index("\n}", script_js.index("compareStatus.textContent", start))
        return script_js[start:end]

    def test_pending_wird_eigens_behandelt(self, script_js):
        import app as app_module

        assert f'"{app_module.COMPETITION_DATA_PENDING}"' in script_js
        assert "function renderComparePending(" in script_js

        start = script_js.index("async function runComparison(")
        end = script_js.index("function renderComparePending(")
        assert "COMPETITION_DATA_PENDING" in script_js[start:end], (
            "runComparison unterscheidet den fachlichen Zustand nicht"
        )

    def test_fetchJson_reicht_den_strukturierten_fehler_weiter(self, script_js):
        """
        Ohne error.data haette der Aufrufer nur den fertigen Text und
        koennte Pending nicht von einem echten Fehler unterscheiden.
        """
        start = script_js.index("async function fetchJson(")
        end = script_js.index("function withSeason(", start)
        block = script_js[start:end]

        assert "error.data = data" in block
        assert "error.status = response.status" in block

    def test_leerzustand_nutzt_die_vorhandene_komponente(self, pending_block):
        # Bestehende Klasse, kein neues Design.
        assert 'make("div", "empty-state")' in pending_block
        # Titel und Beschreibung kommen aus dem Katalog.
        assert "error_key" in pending_block
        assert "error_text_key" in pending_block
        # Alte Ergebnisse verschwinden.
        assert 'compareResult.innerHTML = ""' in pending_block
        # Genau eine Live-Region.
        assert pending_block.count('setAttribute("role", "status")') == 1

    def test_kein_technischer_text_im_leerzustand(self, pending_block):
        assert "error.message" not in pending_block
        assert "Request failed" not in pending_block
        assert "error.requestFailed" not in pending_block

    def test_kein_hardcodierter_sichtbarer_text(self, pending_block):
        """Alle sichtbaren Zeichenketten laufen ueber t()."""
        assert "Champions" not in pending_block
        assert "available" not in pending_block
        assert not re.search(r"\b20\d\d\b", pending_block)

    def test_alte_zustaende_verschwinden_bei_jedem_wechsel(self, script_js):
        """
        Saison-, Phasen- und Moduswechsel muessen den Ergebnisbereich
        leeren - dort lebt seit dieser Aenderung auch der Leerzustand.
        """
        # Saisonwechsel
        start = script_js.index("function resetCompareView(")
        end = script_js.index("\n}", start)
        assert 'compareResult.innerHTML = ""' in script_js[start:end]

        # Phasenwechsel
        start = script_js.index('document.querySelectorAll(".phase-btn")')
        end = script_js.index("function renderCompareLeagues", start)
        assert "compareResult.innerHTML" in script_js[start:end]

        # Moduswechsel
        start = script_js.index('state.compareMode = button.dataset.cmode')
        end = script_js.index('document.querySelectorAll(".phase-btn")', start)
        assert "compareResult.innerHTML" in script_js[start:end]
