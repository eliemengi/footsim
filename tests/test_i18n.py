"""Focused contracts for the dependency-free FootSim DE/EN foundation."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.i18n import (
    DEFAULT_LOCALE,
    locale_from_browser_header,
    load_catalog,
    resolve_locale,
    translate,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _placeholders(value: str) -> set[str]:
    return set(re.findall(r"\{([A-Za-z0-9_]+)\}", value))


def test_catalogs_have_matching_keys_and_parameter_contracts():
    catalogs = {
        locale: json.loads((PROJECT_ROOT / "static" / "i18n" / f"{locale}.json").read_text(encoding="utf-8"))
        for locale in ("de", "en")
    }
    assert catalogs["de"].keys() == catalogs["en"].keys()
    for key in catalogs["de"]:
        assert _placeholders(catalogs["de"][key]) == _placeholders(catalogs["en"][key]), key


@pytest.mark.parametrize("language", ["de", "de-DE", "de-AT", "de-CH", "DE_de"])
def test_german_language_family_resolves_to_de(language):
    assert resolve_locale(browser_language=language) == "de"


@pytest.mark.parametrize("language", ["pt-BR", "fr-FR", "es", "", None])
def test_unsupported_or_missing_browser_language_falls_back_to_english(language):
    assert resolve_locale(browser_language=language) == DEFAULT_LOCALE


def test_explicit_choice_overrides_persisted_and_browser_language():
    assert resolve_locale(explicit="en", persisted="de", browser_language="de-DE") == "en"
    assert resolve_locale(persisted="de", browser_language="en-US") == "de"


def test_browser_header_uses_the_highest_priority_supported_locale():
    assert locale_from_browser_header("de-AT,de;q=0.9,en;q=0.8") == "de"
    assert locale_from_browser_header("fr-FR, de;q=0.9") == "de"
    assert locale_from_browser_header("de;q=0.4,en;q=0.9") == "en"
    assert locale_from_browser_header("de;q=0, en;q=0.8") == "en"


def test_missing_key_and_missing_parameter_are_safe():
    assert translate("missing.key", "de") == "missing.key"
    assert translate("availability.matchday", "en", matchday=3) == "Matchday 3 available"
    assert translate("availability.matchday", "en") == "Matchday {matchday} available"


def test_big_games_and_availability_copy_is_available_in_both_languages():
    assert "Freundschaftsspiele zählen nicht" in load_catalog("de")["player.scopeHint.big_games"]
    assert "Friendlies do not count" in load_catalog("en")["player.scopeHint.big_games"]
    for locale in ("de", "en"):
        assert "{matchday}" in load_catalog(locale)["availability.matchday"]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APISPORTS_KEY", "test-key")
    monkeypatch.setenv("FOOTBALL_DATA_KEY", "test-key")
    import app as app_module

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def test_server_renders_locale_metadata_and_persists_explicit_choice(client):
    response = client.get("/?lang=en", headers={"Accept-Language": "de-DE"})
    html = response.get_data(as_text=True)
    assert '<html lang="en">' in html
    assert "Football simulation and analysis" in html
    assert "footsim_lang=en" in response.headers.get("Set-Cookie", "")

    persisted = client.get("/")
    assert '<html lang="en">' in persisted.get_data(as_text=True)


def test_competition_availability_uses_the_request_locale(client, monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "is_current_season", lambda api_code, season: True)
    response = client.get("/api/competitions?lang=en")
    assert response.status_code == 200
    bundesliga = next(item for item in response.get_json() if item["code"] == "bl1")

    # Der Untertitel wird aus der Freischaltung gebildet. Frueher stand
    # hier "Matchday 1 available" fest verdrahtet - dieser Test fiel
    # dadurch um, sobald ein zweiter Spieltag freigeschaltet wurde,
    # obwohl an der Sprachauswahl nichts kaputt war. Die Erwartung kommt
    # deshalb aus derselben Konfiguration wie die Antwort; geprueft wird
    # weiterhin genau das, worum es hier geht: dass der ENGLISCHE
    # Katalog greift und nicht der deutsche.
    freigeschaltet = app_module.LEAGUE_CONFIG["bl1"]["unlocked_matchdays"]
    erwartet = (
        f"Matchday {freigeschaltet[0]} available"
        if len(freigeschaltet) == 1
        else f"Matchdays {min(freigeschaltet)} to {max(freigeschaltet)} available"
    )
    assert bundesliga["subtitle"] == erwartet
    assert bundesliga["country"] == "Germany"
    europa_league = next(item for item in response.get_json() if item["code"] == "el")
    assert europa_league["country"] == "Europe"
    assert europa_league["coming_soon_text"] == "The Europa League will be available later."


def test_matchday_and_champions_league_metadata_use_the_request_locale(client, monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "get_season_info", lambda _code: {"current_matchday": 1})
    monkeypatch.setattr(app_module, "is_current_season", lambda _code, _season: True)
    monkeypatch.setattr(app_module, "is_matchday_unlocked", lambda *_args: False)
    matchdays = client.get("/api/matchdays?competition=bl1&lang=en").get_json()
    assert matchdays[0]["label"] == "Matchday 1"
    assert matchdays[0]["message"] == "Not yet available"

    monkeypatch.setattr(
        app_module,
        "get_all_matches",
        lambda *_args, **_kwargs: [{"stage": "LAST_16"}],
    )
    stages = client.get("/api/cl-stages?lang=en").get_json()["stages"]
    assert stages == [{"stage": "LAST_16", "label": "Round of 16"}]


def test_localized_manifest_and_offline_page(client):
    manifest = client.get("/manifest.json?lang=de")
    assert manifest.status_code == 200
    assert manifest.get_json()["lang"] == "de"
    assert manifest.get_json()["description"] == "Fußballsimulation und Analyse"

    offline = client.get("/offline?lang=en")
    assert '<html lang="en">' in offline.get_data(as_text=True)
    assert "No connection" in offline.get_data(as_text=True)


def test_frontend_contract_contains_catalog_loader_switcher_and_i18n_markup():
    script = (PROJECT_ROOT / "static" / "script.js").read_text(encoding="utf-8")
    index = (PROJECT_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    service_worker = (PROJECT_ROOT / "static" / "sw.js").read_text(encoding="utf-8")

    assert 'I18N_STORAGE_KEY = "footsim_lang"' in script
    assert "async function initI18n()" in script
    assert "function selectLocale(locale)" in script
    assert "function activeIntlLocale()" in script
    assert "function visibleApiError(" in script
    assert "function localizedMetric(" in script
    assert "data-i18n-placeholder" in script
    assert 't("player.scopeHint.big_games")' in script
    assert 'data-i18n="tabs.season.full"' in index
    assert 'data-i18n="footer.note"' in index
    assert '"/static/i18n/de.json"' in service_worker
    assert '"/static/i18n/en.json"' in service_worker
    assert '"/manifest.json?lang=de"' in service_worker
    assert '"/manifest.json?lang=en"' in service_worker


def test_all_direct_frontend_translation_calls_have_catalog_entries():
    """A missing catalog entry must never leak its technical key into the UI."""

    script = (PROJECT_ROOT / "static" / "script.js").read_text(encoding="utf-8")
    direct_keys = set(re.findall(
        r'''(?<![A-Za-z0-9_$])t\(\s*["']([^"']+)["']''', script
    ))
    assert direct_keys

    for locale in ("de", "en"):
        assert direct_keys <= load_catalog(locale).keys()


def test_core_template_i18n_attributes_resolve_and_cover_active_views():
    index = (PROJECT_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    catalog = load_catalog("en")
    keys = set()
    for attribute in ("data-i18n", "data-i18n-aria", "data-i18n-title", "data-i18n-placeholder"):
        keys.update(re.findall(rf'{attribute}="([^"]+)"', index))

    assert keys <= catalog.keys(), sorted(keys - catalog.keys())
    assert {
        "scorers.title",
        "fixtures.emptyHeading",
        "seasonSimulation.heading",
        "compare.heading",
        "transfer.heading",
        "live.heading",
        "matchCenter.overview",
        "players.compareHeading",
        "plots.heading",
        "profile.loading",
        "team.loading",
    } <= keys
    # Visible shell labels must stay catalog-backed; comments may keep their
    # German implementation notes, but these former direct DOM labels may not
    # return as literal text nodes.
    for raw_label in (
        ">Torjägerliste<",
        ">Spiele heute<",
        ">Zwei Spieler direkt gegenüberstellen<",
        ">Wie möchtest du vergleichen?<",
        ">Noch keine Vergleichsdaten<",
        ">Vergleichen<",
    ):
        assert raw_label not in index
