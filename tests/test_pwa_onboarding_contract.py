"""
Statische Vertraege des PWA-Erststarts.

Diese Datei prueft ausschliesslich Dinge, die sich am Quelltext
wirklich entscheiden lassen: Markup-Struktur, Tokenaufloesung,
Eindeutigkeit der Verdrahtung. Sie ersetzt KEINE Laufzeitpruefung -
die frueheren Substring-Tests waren gruen, waehrend der Flow im
Browser kaputt war, weil sie genau das verwechselt haben. Das
Verhalten selbst deckt tests/test_onboarding_e2e.py ab.
"""

import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def index_html():
    return (PROJECT_ROOT / "templates" / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def script_js():
    return (PROJECT_ROOT / "static" / "script.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def style_css():
    return (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Markup
# ---------------------------------------------------------------------------

def test_every_wizard_state_has_a_step_container(index_html):
    """Ein Zustand ohne Container koennte nie sichtbar werden."""
    for state in ("language", "access", "login", "register", "verify", "personalize"):
        assert f'id="onboarding-step-{state}"' in index_html, state


def test_only_the_first_step_is_visible_in_markup(index_html):
    """Ohne JavaScript darf hoechstens Tor 1 offen sein."""
    steps = re.findall(r'<section id="onboarding-step-([a-z]+)" class="([^"]+)"', index_html)
    assert steps, "Wizard-Schritte nicht gefunden"

    visible = [name for name, classes in steps if "hidden" not in classes.split()]
    assert visible == ["language"], visible


def test_step_order_follows_the_flow(index_html):
    positions = [
        index_html.find(f'id="onboarding-step-{state}"')
        for state in ("language", "access", "login", "register", "verify", "personalize")
    ]
    assert positions == sorted(positions)
    assert index_html.find('id="onboarding-overlay"') < positions[0]


def test_no_hardcoded_club_list_anywhere(index_html, script_js):
    """
    Die Vereinsauswahl kommt aus /api/standings. Eine gepflegte Liste im
    Markup oder im Skript waere ein Rueckfall in den alten Zustand.
    """
    for club in ("Bayern M", "Borussia Dortmund", "Real Madrid", "FC Barcelona",
                 "Manchester City", "Liverpool FC", "Inter Milan", "Paris SG"):
        assert club not in index_html, f"{club} steht wieder fest im Markup"
        assert club not in script_js, f"{club} steht wieder fest im Skript"

    assert 'id="account-onboarding-team-select"' not in index_html
    assert 'id="settings-team-select"' not in index_html


def test_personalization_is_rendered_not_written_out(index_html):
    """Der Picker-Container ist leer; gefuellt wird er zur Laufzeit."""
    assert 'id="onboarding-picker-host"' in index_html
    assert 'id="account-favorite-picker"' in index_html
    host = re.search(r'<div id="onboarding-picker-host"[^>]*>(.*?)</div>', index_html, re.S)
    assert host is not None
    assert host.group(1).strip() == ""


def test_no_select_element_in_the_onboarding_flow(index_html):
    start = index_html.index('id="onboarding-overlay"')
    end = index_html.index("</body>")
    assert "<select" not in index_html[start:end]


# ---------------------------------------------------------------------------
# CSS-Tokens
# ---------------------------------------------------------------------------

def test_every_css_variable_resolves(index_html, script_js, style_css):
    """
    Eine var()-Referenz auf ein undefiniertes Token macht die gesamte
    Deklaration ungueltig - die Regel faellt still aus. Genau daran sah
    das Onboarding vorher unfertig aus.
    """
    defined = set(re.findall(r'(--[A-Za-z0-9_-]+)\s*:', style_css))
    pattern = re.compile(r'var\(\s*(--[A-Za-z0-9_-]+)\s*\)')

    for name, source in (("index.html", index_html),
                         ("script.js", script_js),
                         ("style.css", style_css)):
        used = set(pattern.findall(source))
        assert used <= defined, f"{name}: {sorted(used - defined)}"


def test_onboarding_uses_component_classes_instead_of_inline_styles(index_html):
    start = index_html.index('id="onboarding-overlay"')
    end = index_html.index("</body>")
    block = index_html[start:end]
    assert 'style="' not in block, "Onboarding-Markup enthaelt wieder Inline-Styles"
    assert "fs-btn" in block and "fs-ob-step" in block


def test_app_is_hidden_by_class_not_by_inline_display(script_js, style_css):
    """
    Frueher stritten .hidden (display:none !important) und inline
    gesetzte display-Werte gegeneinander. Die Sperre laeuft jetzt
    ausschliesslich ueber eine Klasse.
    """
    assert "body.onboarding-lock" in style_css
    assert "classList.add(\"onboarding-lock\")" in script_js
    assert ".app').style.display" not in script_js
    assert '.app").style.display' not in script_js


# ---------------------------------------------------------------------------
# Verdrahtung
# ---------------------------------------------------------------------------

def test_onboarding_controller_exists_exactly_once(script_js):
    """
    Der Tor-3-Block lag zusaetzlich im Escape-Handler des Player
    Comparison Scatter. Genau ein Controller, an genau einer Stelle.
    """
    assert script_js.count("async function initOnboarding()") == 1
    assert script_js.count("function createTeamPicker(") == 1
    assert script_js.count("document.addEventListener('DOMContentLoaded'") \
        + script_js.count('document.addEventListener("DOMContentLoaded"') == 1


def test_player_comparison_escape_handler_is_clean(script_js):
    """Escape schliesst die Detailkarte - und tut sonst nichts."""
    marker = "// Escape schliesst die Detailkarte"
    start = script_js.index(marker)
    end = script_js.index("// Klick ausserhalb schliesst ebenfalls", start)
    handler = script_js[start:end]

    assert "pcScatterHideDetail();" in handler
    # Genau eine Registrierung: die des Handlers selbst. Der eingefuegte
    # Block haengte weitere Listener bei jedem Escape-Druck an.
    assert handler.count("addEventListener") == 1
    for forbidden in ("/api/auth/favorite", "onboarding", "favorite", "safeAuthFetch"):
        assert forbidden not in handler, f"{forbidden!r} gehoert nicht in den Escape-Handler"


def test_access_step_never_completes_onboarding_or_opens_the_drawer(script_js):
    """
    Login und Register sind Zustaende IM Wizard. Frueher gaben sie die
    App frei, setzten onboarding_completed und oeffneten den Drawer.
    """
    start = script_js.index("function wizardBindAccess()")
    end = script_js.index("function wizardBindLogin()")
    block = script_js[start:end]

    assert 'wizardGoto("login")' in block
    assert 'wizardGoto("register")' in block
    assert "openAuthDrawer" not in block
    assert "onboarding_completed" not in block
    # Gast ist der einzige Zweig, der hier direkt fertig ist.
    assert block.count("wizardComplete()") == 1


def test_drawer_cannot_open_while_the_wizard_runs(script_js):
    start = script_js.index("function openAuthDrawer()")
    end = script_js.index("function closeAuthDrawer()")
    assert "if (wizardActive) return;" in script_js[start:end]


def test_language_transition_does_not_depend_on_a_reload(script_js):
    """
    selectLocale() bricht bei bereits aktiver Sprache ab. Der Wizard
    muss trotzdem weiterschalten, sonst ist genau ein Sprachknopf tot.
    """
    start = script_js.index("function wizardBindLanguage()")
    end = script_js.index("function wizardBindAccess()")
    block = script_js[start:end]

    assert "normalizeLocale(locale) === activeLocale" in block
    assert 'wizardGoto("access")' in block
    assert 'writeWizardState("access")' in block


def test_onboarding_state_is_one_versioned_key(script_js):
    assert 'ONBOARDING_KEY = "footsim_onboarding"' in script_js
    assert "ONBOARDING_VERSION" in script_js
    # Die alten Einzelschluessel duerfen nur noch in der Migration vorkommen.
    start = script_js.index("function migrateLegacyOnboardingState()")
    end = script_js.index("function lockAppForOnboarding()")
    migration = script_js[start:end]
    for legacy in ("onboarding_completed", "pwa_onboarding_step", "guest_favorite_team"):
        assert script_js.count(f'"{legacy}"') == migration.count(f'"{legacy}"'), legacy


def test_no_silent_error_swallowing_in_the_onboarding_flow(script_js):
    start = script_js.index("   18. PWA ONBOARDING")
    block = script_js[start:]
    assert "catch (err) {}" not in block
    assert "catch(err) {}" not in block


def test_auth_core_is_presentation_free(script_js):
    """
    Drawer und Wizard teilen die Requests, nicht die Reaktion. Ein
    Reload oder ein Drawer-Aufruf im Kern wuerde den Wizard zerstoeren.
    """
    start = script_js.index("async function authLogin(")
    end = script_js.index("let wizardActive = false;")
    core = script_js[start:end]

    for forbidden in ("openAuthDrawer", "window.location.reload", "wizardGoto", "show(", "hide("):
        assert forbidden not in core, f"{forbidden!r} gehoert nicht in den Auth-Kern"


def test_csrf_recovery_lives_in_the_shared_core_not_per_caller(script_js):
    """
    A stale CSRF token can hit login, register, or any other mutating
    auth call - drawer or wizard. The recovery (refresh the token,
    retry once) belongs in safeAuthFetch() itself, exactly once, so
    every caller gets it automatically instead of each needing its own
    copy of the same retry logic.
    """
    assert script_js.count("async function refreshCsrfToken()") == 1
    assert script_js.count("function setCsrfToken(") == 1

    start = script_js.index("async function safeAuthFetch(")
    end = script_js.index("/* ---------- Auth-Kern")
    core = script_js[start:end]

    assert "refreshCsrfToken" in core
    assert "auth.csrfError" in core
    # Genau ein Retry-Aufruf, und er ist als solcher markiert (dritter
    # Parameter), damit ein zweiter Fehlschlag nicht erneut auslöst.
    assert core.count("safeAuthFetch(url, options, true)") == 1

    # Weder Wizard- noch Drawer-Handler duplizieren diese Logik.
    for forbidden in ("refreshCsrfToken", "auth.csrfError"):
        assert script_js.count(forbidden) == 2, (
            f"{forbidden!r} sollte nur in safeAuthFetch (Definition + Aufruf) "
            f"vorkommen, nicht in einzelnen Aufrufstellen"
        )


def test_drawer_and_wizard_call_the_same_auth_functions(script_js):
    """Beide Praesentationen nutzen authLogin()/authRegister(), nicht eigene Requests."""
    drawer_start = script_js.index("if (loginForm) {")
    drawer_end = script_js.index("if (registerForm) {")
    drawer_register_end = script_js.index("// Handler for the resend button")
    drawer = script_js[drawer_start:drawer_end] + script_js[drawer_end:drawer_register_end]

    assert "authLogin(" in drawer
    assert "authRegister(" in drawer
    assert "fetch('/api/auth/login'" not in drawer
    assert "fetch('/api/auth/register'" not in drawer

    wizard_start = script_js.index("function wizardBindLogin()")
    wizard_end = script_js.index("function wizardBindVerify()")
    wizard = script_js[wizard_start:wizard_end]

    assert "authLogin(" in wizard
    assert "authRegister(" in wizard


def test_drawer_forms_cannot_fall_through_to_native_submission(index_html):
    """
    Falls das JS aus irgendeinem Grund nie bindet, darf das Formular
    trotzdem nicht mit GET und Zugangsdaten in der URL abschicken.
    """
    for form_id in ("login-form", "register-form"):
        match = re.search(rf'<form id="{form_id}"[^>]*>', index_html)
        assert match is not None, form_id
        assert 'onsubmit="return false;"' in match.group(0)


def test_header_groups_brand_left_and_controls_right(index_html, style_css):
    """
    Account/Zahnrad gehoeren in die rechte Gruppe. Frueher richtete nur
    .desktop-nav { margin-left:auto } sie als Nebenwirkung aus; auf
    Mobil ist die Navigation ausgeblendet und die Ersatzregel zielte
    auf .app-bar > .icon-btn - die Knoepfe sind aber Enkel, nicht
    Kinder, also traf sie nichts und die Knoepfe rutschten nach links.
    """
    # Die Gruppe selbst richtet sich aus, nicht ein Nachbarelement.
    block = re.search(r'\.app-bar-actions\s*\{([^}]+)\}', style_css)
    assert block is not None, ".app-bar-actions hat keine eigene Regel"
    assert "margin-left: auto" in block.group(1)

    # Der tote Selektor darf nicht zurueckkommen.
    assert ".app-bar > .icon-btn {" not in style_css

    # Markenblock links, Bedienknoepfe rechts - in dieser Reihenfolge.
    brand = index_html.index('class="app-bar-brand"')
    actions = index_html.index('class="app-bar-actions"')
    assert brand < actions


def test_header_favorite_crest_is_dynamic_and_accessible(index_html, script_js):
    """Wappen aus dem Serverzustand, niemals ein fest verdrahteter Verein."""
    assert 'id="app-bar-favorite"' in index_html
    assert 'id="app-bar-favorite-crest"' in index_html

    # Der Knopf startet versteckt und wird nur mit aufloesbarem Team gezeigt.
    button = re.search(r'<button[^>]*id="app-bar-favorite"[^>]*>', index_html)
    assert button is not None
    assert "hidden" in button.group(0)

    assert "function renderHeaderFavorite()" in script_js
    # Beschriftung aus dem echten Vereinsnamen, kein blosses "Bild".
    assert 't("header.favoriteTeamLabel", { team: teamName })' in script_js
    # Das bestehende Teamprofil wird wiederverwendet.
    assert "function openFavoriteTeamProfile()" in script_js
    assert "tdOpen(window.favoriteTeamId" in script_js


def test_no_team_is_hardcoded_in_personalization(index_html, script_js):
    """Kein Verein und keine Vereins-ID steht fest im Code."""
    for team in ("Bayern", "Dortmund", "Real Madrid", "Barcelona", "Liverpool"):
        assert team not in index_html, f"{team} steht fest im Markup"
        assert team not in script_js, f"{team} steht fest im Skript"


def test_favorite_selection_uses_the_canonical_id_namespace(script_js):
    """
    Die Auswahl muss aus demselben Namensraum stammen wie Teamprofil
    und Live, sonst ist das gewaehlte Team weder anklickbar noch in
    Live erkennbar.
    """
    start = script_js.index("async function pickerLoadTeams(")
    end = script_js.index("function pickerGroupByCountry(")
    picker = script_js[start:end]

    assert "/api/personalization/teams?competition=" in picker
    # Die football-data-Quelle darf fuer die AUSWAHL nicht zurueckkehren.
    # (Die Ligatabelle selbst nutzt /api/standings weiterhin - anderer
    # Zweck, anderer Namensraum, bleibt unangetastet.)
    assert "/api/standings" not in picker
    assert 'source: "apisports"' in script_js


def test_account_overview_hides_details_behind_subviews(index_html):
    """
    Die Uebersicht ist Navigation. E-Mail und Passwortfelder liegen
    eine Ebene tiefer und duerfen nicht beim Oeffnen sichtbar sein.
    """
    for panel in ("account-root", "account-profile", "account-security"):
        assert f'id="{panel}"' in index_html, panel

    # Nur die Uebersicht ist offen.
    for panel in ("account-profile", "account-security"):
        node = re.search(rf'<div id="{panel}" class="([^"]*)"', index_html)
        assert node is not None, panel
        assert "hidden" in node.group(1).split(), f"{panel} ist nicht versteckt"

    root_start = index_html.index('id="account-root"')
    root_end = index_html.index('id="account-profile"')
    root = index_html[root_start:root_end]

    # Die sensiblen Felder gehoeren NICHT in die Uebersicht.
    for field in ("profile-email", "change-current-password", "change-new-password",
                  "account-favorite-picker"):
        assert field not in root, f"{field} liegt noch in der Uebersicht"

    # Aber Logout und der Einstieg in die Unterebenen schon.
    for control in ("logout-btn", "account-open-profile", "account-open-security"):
        assert control in root, control


def test_account_subviews_are_reachable_and_reversible(index_html, script_js):
    assert "function showAccountPanel(" in script_js
    assert "function bindAccountNavigation(" in script_js
    assert script_js.count("bindAccountNavigation();") == 1
    # Jede Unterebene hat einen Zurueck-Weg.
    assert index_html.count("data-account-back") == 2
    # Der Drawer oeffnet immer auf der Uebersicht.
    assert "showAccountPanel('account-root')" in script_js


def test_delete_account_stays_separated_and_confirmed(index_html):
    """Loeschen darf nie wie ein gewoehnlicher Knopf aussehen."""
    assert 'class="acc-danger"' in index_html
    assert 'id="delete-account-confirmation"' in index_html
    confirm = re.search(r'<div id="delete-account-confirmation" class="([^"]*)"', index_html)
    assert confirm is not None and "hidden" in confirm.group(1).split()
    # Passwortbestaetigung bleibt erhalten.
    assert 'id="delete-current-password"' in index_html
    # Kein Durchrutschen zu nativem GET-Submit.
    form = re.search(r'<form id="delete-account-form"[^>]*>', index_html)
    assert form is not None and 'onsubmit="return false;"' in form.group(0)


def test_live_prioritizes_favorite_without_touching_match_data(script_js):
    """
    Nur Gruppen werden umsortiert - keine Spieldaten, keine Zeiten,
    keine Duplikate, kein fest verdrahteter Wettbewerb.
    """
    assert script_js.count("function liveOrderGroupsForFavorite(") == 1
    assert script_js.count("function liveGroupHasFavorite(") == 1

    start = script_js.index("function liveOrderGroupsForFavorite(")
    end = script_js.index("function liveApplyRememberedOrder(")
    block = script_js[start:end]

    # Stabil: unbeteiligte Gruppen behalten ihre Serverreihenfolge.
    assert "a.index - b.index" in block
    # Ohne Lieblingsteam bleibt alles unveraendert.
    assert "if (!window.favoriteTeamId" in block

    # Der Wettbewerb spielt keine Rolle - nur Team-IDs.
    detector_start = script_js.index("function liveGroupHasFavorite(")
    detector = script_js[detector_start:start]
    assert 'isFavoriteTeamId(match.home_id, "apisports")' in detector
    assert "league_id ===" not in detector
    assert "competition_code ===" not in detector


def test_live_background_refresh_does_not_reshuffle(script_js):
    """
    Hintergrund-Ticks aktualisieren Ergebnisse, sortieren die Liste
    aber nicht neu - sonst springt der Inhalt unter dem Finger.
    """
    assert "function liveApplyRememberedOrder(" in script_js
    assert "favoriteOrder" in script_js

    start = script_js.index("function liveRender(data, options)")
    end = script_js.index("* Laedt die Spiele des gewaehlten Tages.")
    block = script_js[start:end]
    assert "background && sameDay" in block
    assert "liveApplyRememberedOrder(" in block
    # Der Aufrufer reicht den Hintergrund-Modus tatsaechlich durch.
    assert "liveRender(data, { background })" in script_js


def test_favorite_team_ids_are_only_compared_within_their_source(script_js):
    """
    Zwei Anbieter, zwei ID-Raeume, kein Mapping. Verglichen wird nur
    innerhalb der Quelle, aus der die gespeicherte ID stammt.
    """
    assert "function isFavoriteTeamId(teamId, namespace)" in script_js
    assert 'isFavoriteTeamId(a.home_id, "football-data")' in script_js
    assert 'isFavoriteTeamId(a.home_id, "apisports")' in script_js
    # Kein direkter Vergleich mehr an den Aufrufstellen.
    assert "String(a.home_id) === String(window.favoriteTeamId)" not in script_js


# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------

def test_onboarding_markup_has_no_untranslated_prose(index_html):
    """
    Frueher stand "Willkommen" hart im Markup und blieb auch auf der
    englischen Seite stehen.
    """
    start = index_html.index('id="onboarding-overlay"')
    end = index_html.index("</body>")
    block = index_html[start:end]

    for tag in ("h1", "p", "button", "span"):
        for attrs, text in re.findall(rf"<{tag}([^>]*)>([^<]+)</{tag}>", block):
            if not text.strip():
                continue
            # Eigennamen und Endonyme brauchen keine Uebersetzung.
            if text.strip() in ("FootSim", "Deutsch", "English"):
                continue
            assert "data-i18n" in attrs, f"Unuebersetzt: {text.strip()!r}"


def test_onboarding_keys_exist_in_both_catalogs():
    catalogs = {
        locale: json.loads(
            (PROJECT_ROOT / "static" / "i18n" / f"{locale}.json").read_text(encoding="utf-8")
        )
        for locale in ("de", "en")
    }
    assert catalogs["de"].keys() == catalogs["en"].keys()

    required = {
        "onboarding.welcomeTitle", "onboarding.back", "onboarding.loginTitle",
        "onboarding.registerTitle", "onboarding.verifyTitle", "onboarding.verifyRecheck",
        "onboarding.chooseCountry", "onboarding.chooseCompetition", "onboarding.chooseTeam",
        "onboarding.pickerError", "onboarding.saveFailed", "onboarding.networkError",
        "account.favoriteNone", "account.favoriteCurrent",
    }
    for locale, catalog in catalogs.items():
        assert required <= catalog.keys(), sorted(required - catalog.keys())
