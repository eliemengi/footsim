"""
Laufzeitpruefung des PWA-Erststarts in einem echten Browser.

Warum es diese Datei gibt: die frueheren Onboarding-Tests waren
Substring-Suchen im Quelltext. Sie waren gruen, waehrend im Browser
genau ein Sprachknopf tot war, Tor 2 den Account-Drawer oeffnete und
die Personalisierung ohne gebundene Listener erschien. Keiner dieser
Fehler ist am Text erkennbar - sie brauchen ein DOM, einen
JavaScript-Kontext und eine echte Session.

Ausfuehren:

    pip install pytest-playwright
    playwright install chromium
    pytest tests/test_onboarding_e2e.py

Ohne Playwright ueberspringt sich die Datei geschlossen, statt eine
falsche Sicherheit zu erzeugen.
"""

import os
import socket
import threading

import pytest

pytest.importorskip(
    "playwright.sync_api",
    reason="Playwright ist nicht installiert - siehe Modulkopf.",
)

from playwright.sync_api import expect, sync_playwright  # noqa: E402


PASSWORD = "e2e_password_123"


# ---------------------------------------------------------------------------
# Server unter Test
# ---------------------------------------------------------------------------

def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def live_server():
    """
    Startet die echte Flask-App gegen die Test-Datenbank des Projekts.

    Bewusst dieselbe Konvention wie tests/conftest.py: ohne lokales
    PostgreSQL wird uebersprungen statt auf ein anderes Backend
    auszuweichen - sonst testet man nicht mehr das, was laeuft.
    """
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url or "footsim_db" not in db_url:
        pytest.skip("Kein lokales PostgreSQL in DATABASE_URL konfiguriert")

    os.environ["DATABASE_URL"] = db_url.replace("footsim_db", "footsim_test_db")
    os.environ["TESTING"] = "1"
    os.environ["MAIL_MOCK"] = "true"

    import importlib
    import app as main_app
    importlib.reload(main_app)

    from werkzeug.serving import make_server

    with main_app.app.app_context():
        from flask_migrate import upgrade
        main_app.db.drop_all()
        main_app.db.session.execute(main_app.db.text("DROP TABLE IF EXISTS alembic_version CASCADE"))
        main_app.db.session.commit()
        upgrade()

    port = _free_port()
    server = make_server("127.0.0.1", port, main_app.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield {"url": f"http://127.0.0.1:{port}", "app": main_app}

    server.shutdown()
    thread.join(timeout=5)
    with main_app.app.app_context():
        main_app.db.session.remove()
        main_app.db.drop_all()
        main_app.db.session.execute(main_app.db.text("DROP TABLE IF EXISTS alembic_version CASCADE"))
        main_app.db.session.commit()


@pytest.fixture(scope="module")
def playwright_browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


def _make_page(browser, locale):
    """Eigener Kontext je Test: leerer LocalStorage, gesetzte Sprache."""
    context = browser.new_context(
        locale=locale,
        extra_http_headers={"Accept-Language": locale},
    )
    return context, context.new_page()


def _create_user(live_server, email, verified, onboarding_done):
    main_app = live_server["app"]
    from src.models import User

    with main_app.app.app_context():
        existing = main_app.db.session.execute(
            main_app.db.select(User).filter_by(email=email)
        ).scalar_one_or_none()
        if existing is not None:
            main_app.db.session.delete(existing)
            main_app.db.session.commit()

        user = User(email=email, first_name="E2E", last_name="Tester")
        user.set_password(PASSWORD)
        user.is_verified = verified
        user.profile_onboarding_completed = onboarding_done
        main_app.db.session.add(user)
        main_app.db.session.commit()
    return email


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------

def _console_errors(page):
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    return errors


def _step(page, name):
    return page.locator(f"#onboarding-step-{name}")


def _app_visible(page):
    return page.locator(".app").is_visible()


def _drawer_open(page):
    return page.locator("#auth-drawer").is_visible()


def _login_through_wizard(page, base_url, email):
    page.goto(f"{base_url}/?source=pwa")
    page.locator("#onboarding-lang-en").click()
    expect(_step(page, "access")).to_be_visible()
    page.locator("#onboarding-login-btn").click()
    expect(_step(page, "login")).to_be_visible()
    page.fill("#onboarding-login-email", email)
    page.fill("#onboarding-login-password", PASSWORD)
    page.locator("#onboarding-login-submit").click()


# ---------------------------------------------------------------------------
# 1-2: Website vs. App
# ---------------------------------------------------------------------------

def test_normal_website_never_shows_the_wizard(live_server, playwright_browser):
    context, page = _make_page(playwright_browser, "de-DE")
    page.goto(live_server["url"] + "/")
    expect(page.locator("#onboarding-overlay")).to_be_hidden()
    assert _app_visible(page)
    context.close()


def test_pwa_source_shows_the_language_gate(live_server, playwright_browser):
    context, page = _make_page(playwright_browser, "de-DE")
    page.goto(live_server["url"] + "/?source=pwa")
    expect(_step(page, "language")).to_be_visible()
    assert not _app_visible(page)
    context.close()


# ---------------------------------------------------------------------------
# 3-6: Sprache, beide Richtungen, beide Browsersprachen
#
# Der eigentliche Regressionstest. selectLocale() bricht bei bereits
# aktiver Sprache ab; frueher blieb der zugehoerige Knopf deshalb tot.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("browser_locale", ["de-DE", "en-US"])
@pytest.mark.parametrize("choice", ["de", "en"])
def test_every_language_button_reaches_the_access_step(
    live_server, playwright_browser, browser_locale, choice
):
    context, page = _make_page(playwright_browser, browser_locale)
    errors = _console_errors(page)

    page.goto(live_server["url"] + "/?source=pwa")
    expect(_step(page, "language")).to_be_visible()
    page.locator(f"#onboarding-lang-{choice}").click()

    expect(_step(page, "access")).to_be_visible()
    expect(_step(page, "language")).to_be_hidden()
    assert not _app_visible(page)
    assert errors == []
    context.close()


# ---------------------------------------------------------------------------
# 7: Gast
# ---------------------------------------------------------------------------

def test_guest_enters_the_app_without_the_drawer(live_server, playwright_browser):
    context, page = _make_page(playwright_browser, "en-US")
    page.goto(live_server["url"] + "/?source=pwa")
    page.locator("#onboarding-lang-en").click()
    expect(_step(page, "access")).to_be_visible()

    page.locator("#onboarding-guest-btn").click()

    expect(page.locator("#onboarding-overlay")).to_be_hidden()
    assert _app_visible(page)
    assert not _drawer_open(page)
    context.close()


# ---------------------------------------------------------------------------
# 8-9: Login und Registrierung bleiben im Wizard
# ---------------------------------------------------------------------------

def test_login_stays_fullscreen(live_server, playwright_browser):
    context, page = _make_page(playwright_browser, "en-US")
    page.goto(live_server["url"] + "/?source=pwa")
    page.locator("#onboarding-lang-en").click()
    page.locator("#onboarding-login-btn").click()

    expect(_step(page, "login")).to_be_visible()
    expect(page.locator("#onboarding-overlay")).to_be_visible()
    assert not _app_visible(page)
    assert not _drawer_open(page)
    context.close()


def test_register_stays_fullscreen(live_server, playwright_browser):
    context, page = _make_page(playwright_browser, "en-US")
    page.goto(live_server["url"] + "/?source=pwa")
    page.locator("#onboarding-lang-en").click()
    page.locator("#onboarding-register-btn").click()

    expect(_step(page, "register")).to_be_visible()
    expect(page.locator("#onboarding-overlay")).to_be_visible()
    assert not _app_visible(page)
    assert not _drawer_open(page)
    context.close()


def test_back_returns_to_the_access_step(live_server, playwright_browser):
    context, page = _make_page(playwright_browser, "en-US")
    page.goto(live_server["url"] + "/?source=pwa")
    page.locator("#onboarding-lang-en").click()
    page.locator("#onboarding-register-btn").click()
    expect(_step(page, "register")).to_be_visible()

    page.locator("#onboarding-register-back").click()
    expect(_step(page, "access")).to_be_visible()
    context.close()


# ---------------------------------------------------------------------------
# 10-11: Verifikation und Personalisierung
# ---------------------------------------------------------------------------

def test_unverified_login_lands_in_the_verify_step(live_server, playwright_browser):
    email = _create_user(live_server, "e2e_unverified@example.com",
                         verified=False, onboarding_done=False)
    context, page = _make_page(playwright_browser, "en-US")

    _login_through_wizard(page, live_server["url"], email)

    expect(_step(page, "verify")).to_be_visible()
    expect(page.locator("#onboarding-verify-email")).to_have_text(email)
    assert not _app_visible(page)
    context.close()


def test_verified_but_unpersonalized_login_lands_in_personalization(
    live_server, playwright_browser
):
    email = _create_user(live_server, "e2e_verified@example.com",
                         verified=True, onboarding_done=False)
    context, page = _make_page(playwright_browser, "en-US")

    _login_through_wizard(page, live_server["url"], email)

    expect(_step(page, "personalize")).to_be_visible()
    # Land -> Wettbewerb -> Verein wird zur Laufzeit gerendert.
    expect(page.locator("#onboarding-picker-host .fs-pick-tile").first).to_be_visible()
    assert not _app_visible(page)
    context.close()


def test_completed_account_goes_straight_into_the_app(live_server, playwright_browser):
    email = _create_user(live_server, "e2e_done@example.com",
                         verified=True, onboarding_done=True)
    context, page = _make_page(playwright_browser, "en-US")

    _login_through_wizard(page, live_server["url"], email)

    expect(page.locator("#onboarding-overlay")).to_be_hidden()
    assert _app_visible(page)
    assert not _drawer_open(page)
    context.close()


# ---------------------------------------------------------------------------
# 12-13: Skip und Speichern
# ---------------------------------------------------------------------------

def test_skip_completes_onboarding(live_server, playwright_browser):
    email = _create_user(live_server, "e2e_skip@example.com",
                         verified=True, onboarding_done=False)
    context, page = _make_page(playwright_browser, "en-US")

    _login_through_wizard(page, live_server["url"], email)
    expect(_step(page, "personalize")).to_be_visible()

    page.locator("#onboarding-personalize-skip").click()

    expect(page.locator("#onboarding-overlay")).to_be_hidden()
    assert _app_visible(page)
    context.close()


def test_saving_a_favorite_completes_onboarding_and_persists(
    live_server, playwright_browser
):
    email = _create_user(live_server, "e2e_save@example.com",
                         verified=True, onboarding_done=False)
    context, page = _make_page(playwright_browser, "en-US")

    _login_through_wizard(page, live_server["url"], email)
    expect(_step(page, "personalize")).to_be_visible()

    # Land -> Wettbewerb -> Verein, jeweils die erste Kachel.
    page.locator("#onboarding-picker-host .fs-pick-tile").first.click()
    page.locator("#onboarding-picker-host .fs-pick-tile").first.click()
    page.locator("#onboarding-picker-host .fs-pick-tile").first.click()

    expect(page.locator("#onboarding-overlay")).to_be_hidden()
    assert _app_visible(page)

    main_app = live_server["app"]
    from src.models import User, FavoriteTeam
    with main_app.app.app_context():
        user = main_app.db.session.execute(
            main_app.db.select(User).filter_by(email=email)
        ).scalar_one()
        favorite = main_app.db.session.execute(
            main_app.db.select(FavoriteTeam).filter_by(user_id=user.id)
        ).scalar_one()
        assert favorite.team_id > 0
        # Die Herkunft wird gespeichert, nicht erraten.
        assert favorite.source == "football-data"
        assert user.profile_onboarding_completed is True
    context.close()


# ---------------------------------------------------------------------------
# 14: Reload / Resume
# ---------------------------------------------------------------------------

def test_reload_resumes_the_current_step(live_server, playwright_browser):
    context, page = _make_page(playwright_browser, "de-DE")

    page.goto(live_server["url"] + "/?source=pwa")
    page.locator("#onboarding-lang-de").click()
    expect(_step(page, "access")).to_be_visible()

    page.reload()
    expect(_step(page, "access")).to_be_visible()
    expect(_step(page, "language")).to_be_hidden()

    page.locator("#onboarding-register-btn").click()
    expect(_step(page, "register")).to_be_visible()

    page.reload()
    expect(_step(page, "register")).to_be_visible()
    context.close()


def test_reload_after_guest_completion_goes_to_the_app(live_server, playwright_browser):
    context, page = _make_page(playwright_browser, "en-US")

    page.goto(live_server["url"] + "/?source=pwa")
    page.locator("#onboarding-lang-en").click()
    page.locator("#onboarding-guest-btn").click()
    expect(page.locator("#onboarding-overlay")).to_be_hidden()

    page.reload()
    expect(page.locator("#onboarding-overlay")).to_be_hidden()
    assert _app_visible(page)
    context.close()


def test_server_state_beats_local_state(live_server, playwright_browser):
    """
    Lokal "fertig", serverseitig offene Personalisierung: der Server
    gewinnt, sonst koennte ein Browser den Schritt dauerhaft umgehen.
    """
    email = _create_user(live_server, "e2e_conflict@example.com",
                         verified=True, onboarding_done=False)
    context, page = _make_page(playwright_browser, "en-US")

    page.goto(live_server["url"] + "/?source=pwa")
    page.locator("#onboarding-lang-en").click()
    page.locator("#onboarding-guest-btn").click()
    expect(page.locator("#onboarding-overlay")).to_be_hidden()

    # Anmeldung ueber den normalen Drawer, danach neu laden.
    page.evaluate(
        """async ({email, password}) => {
            const token = document.querySelector('meta[name="csrf-token"]').content;
            await fetch('/api/auth/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': token},
                body: JSON.stringify({email, password}),
            });
        }""",
        {"email": email, "password": PASSWORD},
    )
    page.goto(live_server["url"] + "/?source=pwa")

    expect(_step(page, "personalize")).to_be_visible()
    context.close()


# ---------------------------------------------------------------------------
# 15-16: Normale Website
# ---------------------------------------------------------------------------

def test_account_drawer_still_works_on_the_website(live_server, playwright_browser):
    context, page = _make_page(playwright_browser, "de-DE")
    page.goto(live_server["url"] + "/")

    page.locator("#auth-btn").click()
    expect(page.locator("#auth-drawer")).to_be_visible()
    expect(page.locator("#auth-logged-out-view")).to_be_visible()

    page.locator("#auth-close").click()
    expect(page.locator("#auth-drawer")).to_be_hidden()
    context.close()


def test_website_never_gets_a_personalization_takeover(live_server, playwright_browser):
    """
    Ein verifizierter Account mit offener Personalisierung darf die
    normale Website nicht blockieren - dort ist der Drawer zustaendig.
    """
    email = _create_user(live_server, "e2e_website@example.com",
                         verified=True, onboarding_done=False)
    context, page = _make_page(playwright_browser, "de-DE")

    page.goto(live_server["url"] + "/")
    page.evaluate(
        """async ({email, password}) => {
            const token = document.querySelector('meta[name="csrf-token"]').content;
            await fetch('/api/auth/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': token},
                body: JSON.stringify({email, password}),
            });
        }""",
        {"email": email, "password": PASSWORD},
    )
    page.goto(live_server["url"] + "/")

    expect(page.locator("#onboarding-overlay")).to_be_hidden()
    assert _app_visible(page)
    expect(page.locator("#account-favorite-section")).to_be_attached()
    context.close()


def test_no_console_errors_during_the_happy_path(live_server, playwright_browser):
    context, page = _make_page(playwright_browser, "de-DE")
    errors = _console_errors(page)

    page.goto(live_server["url"] + "/?source=pwa")
    page.locator("#onboarding-lang-de").click()
    expect(_step(page, "access")).to_be_visible()
    page.locator("#onboarding-login-btn").click()
    expect(_step(page, "login")).to_be_visible()
    page.locator("#onboarding-login-back").click()
    page.locator("#onboarding-guest-btn").click()
    expect(page.locator("#onboarding-overlay")).to_be_hidden()

    assert errors == [], errors
    context.close()


# ---------------------------------------------------------------------------
# 20: Player Comparison bleibt unberuehrt
# ---------------------------------------------------------------------------

def test_escape_in_player_comparison_has_no_onboarding_side_effects(
    live_server, playwright_browser
):
    context, page = _make_page(playwright_browser, "de-DE")
    requests = []
    page.on("request", lambda request: requests.append(request.url))

    page.goto(live_server["url"] + "/")
    for _ in range(5):
        page.keyboard.press("Escape")

    assert not any("/api/auth/favorite" in url for url in requests)
    expect(page.locator("#onboarding-overlay")).to_be_hidden()
    assert _app_visible(page)
    context.close()
