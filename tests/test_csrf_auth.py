"""
CSRF-enabled coverage for the auth endpoints.

tests/test_auth.py deliberately sets WTF_CSRF_ENABLED=False so it can
test route logic in isolation - that's a legitimate choice for testing
validation and business rules, but it means the CSRF layer itself has
never been exercised by any automated test. That gap is exactly why a
real browser could get HTTP 400 on every login/register while every
existing test stayed green.

This file runs with CSRF fully enabled (the default) and proves:
  - a missing, invalid, or expired token produces a structured JSON
    400 with a stable error_key, never Flask's default HTML page
  - a valid token still reaches the real route and its real logic
  - ordinary auth failures (bad credentials) are not confused with a
    CSRF failure
"""

import re

import pytest

from src.models import db, User
import app as main_app


@pytest.fixture(scope='function')
def csrf_client(postgres_db):
    """
    Same database fixture as tests/test_auth.py, but CSRF protection
    is left at its default (enabled) - the whole point of this file.
    """
    main_app.app.config["TESTING"] = True
    with main_app.app.test_client() as client:
        with main_app.app.app_context():
            yield client


def _csrf_token(client):
    """
    Mirrors what a real page load does: GET a page that renders the
    <meta name="csrf-token"> tag, and read the token out of it - the
    same value the browser's meta tag would carry.
    """
    response = client.get('/')
    match = re.search(r'name="csrf-token" content="([^"]+)"', response.get_data(as_text=True))
    assert match, "csrf-token meta tag not found in rendered page"
    return match.group(1)


def _register_verified_user(email):
    """
    Creates a user directly, bypassing the mail-sending registration
    endpoint - login() does not require verification today (unchanged
    by this fix), so this only needs a real row to authenticate against.
    """
    with main_app.app.app_context():
        existing = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
        if existing is not None:
            return
        user = User(email=email, first_name="CSRF", last_name="Test")
        user.set_password("secure_password123")
        db.session.add(user)
        db.session.commit()


# ---------------------------------------------------------------------------
# A) login without CSRF
# ---------------------------------------------------------------------------

def test_login_without_csrf_token_returns_structured_json_400(csrf_client):
    response = csrf_client.post("/api/auth/login", json={
        "email": "nobody@example.com",
        "password": "whatever123",
    })

    assert response.status_code == 400
    assert response.content_type.startswith("application/json")
    data = response.get_json()
    assert data["error_key"] == "auth.csrfError"
    assert isinstance(data["error"], str) and data["error"]


# ---------------------------------------------------------------------------
# B) register without CSRF
# ---------------------------------------------------------------------------

def test_register_without_csrf_token_returns_structured_json_400(csrf_client):
    response = csrf_client.post("/api/auth/register", json={
        "email": "nobody2@example.com",
        "password": "whatever123",
        "first_name": "A",
        "last_name": "B",
    })

    assert response.status_code == 400
    assert response.content_type.startswith("application/json")
    data = response.get_json()
    assert data["error_key"] == "auth.csrfError"


# ---------------------------------------------------------------------------
# C) valid CSRF + invalid credentials -> reaches the route, ordinary 401
# ---------------------------------------------------------------------------

def test_valid_csrf_with_bad_credentials_reaches_the_route(csrf_client):
    token = _csrf_token(csrf_client)

    response = csrf_client.post(
        "/api/auth/login",
        json={"email": "nobody3@example.com", "password": "whatever123"},
        headers={"X-CSRFToken": token},
    )

    # Reached login()'s own logic, not the CSRF gate: a 401 with the
    # route's own message, not a 400 with error_key "auth.csrfError".
    assert response.status_code == 401
    data = response.get_json()
    assert data.get("error_key") != "auth.csrfError"
    assert data["error"] == "Invalid email or password"


# ---------------------------------------------------------------------------
# D) valid CSRF + valid credentials -> normal auth logic, real session
# ---------------------------------------------------------------------------

def test_valid_csrf_with_valid_credentials_logs_in(csrf_client):
    _register_verified_user("csrf_login@example.com")
    token = _csrf_token(csrf_client)

    response = csrf_client.post(
        "/api/auth/login",
        json={"email": "csrf_login@example.com", "password": "secure_password123"},
        headers={"X-CSRFToken": token},
    )

    assert response.status_code == 200
    assert response.get_json()["message"] == "Login successful"

    # The session must persist on a subsequent request (a plain GET,
    # not protected by CSRF at all).
    me = csrf_client.get("/api/auth/me")
    assert me.get_json()["authenticated"] is True
    assert me.get_json()["user"]["email"] == "csrf_login@example.com"


# ---------------------------------------------------------------------------
# E) invalid/garbage CSRF token
# ---------------------------------------------------------------------------

def test_garbage_csrf_token_returns_structured_json_400(csrf_client):
    _csrf_token(csrf_client)  # establishes a real session first

    response = csrf_client.post(
        "/api/auth/login",
        json={"email": "nobody4@example.com", "password": "whatever123"},
        headers={"X-CSRFToken": "not-a-real-token-at-all"},
    )

    assert response.status_code == 400
    data = response.get_json()
    assert data["error_key"] == "auth.csrfError"


# ---------------------------------------------------------------------------
# F) expired token, deterministic (no sleeping in a test suite)
# ---------------------------------------------------------------------------

def test_expired_csrf_token_returns_structured_json_400(csrf_client, monkeypatch):
    token = _csrf_token(csrf_client)

    # validate_csrf() reads WTF_CSRF_TIME_LIMIT from the live app config
    # at request time. A negative limit makes any token - even one
    # issued a moment ago - look expired, without waiting out the real
    # default of one hour.
    monkeypatch.setitem(main_app.app.config, "WTF_CSRF_TIME_LIMIT", -1)

    response = csrf_client.post(
        "/api/auth/login",
        json={"email": "nobody5@example.com", "password": "whatever123"},
        headers={"X-CSRFToken": token},
    )

    assert response.status_code == 400
    data = response.get_json()
    assert data["error_key"] == "auth.csrfError"


# ---------------------------------------------------------------------------
# Recovery endpoint itself
# ---------------------------------------------------------------------------

def test_csrf_token_endpoint_issues_a_token_that_a_retry_can_use(csrf_client):
    """
    This is what the frontend's one-shot retry calls after a CSRF
    rejection. It must work with no prior token (a bare GET) and the
    token it returns must actually be accepted afterwards.
    """
    response = csrf_client.get("/api/auth/csrf-token")
    assert response.status_code == 200
    fresh_token = response.get_json()["csrf_token"]
    assert isinstance(fresh_token, str) and fresh_token

    _register_verified_user("csrf_recovery@example.com")
    login = csrf_client.post(
        "/api/auth/login",
        json={"email": "csrf_recovery@example.com", "password": "secure_password123"},
        headers={"X-CSRFToken": fresh_token},
    )
    assert login.status_code == 200


def test_csrf_token_endpoint_recovers_after_an_expired_token(csrf_client, monkeypatch):
    """
    The exact sequence safeAuthFetch() performs: a request fails with
    an expired token, GET /api/auth/csrf-token, retry once with the
    fresh token - and this time it succeeds.
    """
    stale_token = _csrf_token(csrf_client)
    _register_verified_user("csrf_expired_retry@example.com")

    monkeypatch.setitem(main_app.app.config, "WTF_CSRF_TIME_LIMIT", -1)
    first_attempt = csrf_client.post(
        "/api/auth/login",
        json={"email": "csrf_expired_retry@example.com", "password": "secure_password123"},
        headers={"X-CSRFToken": stale_token},
    )
    assert first_attempt.status_code == 400
    assert first_attempt.get_json()["error_key"] == "auth.csrfError"

    monkeypatch.undo()  # simulate time no longer being frozen for the retry
    fresh_token = csrf_client.get("/api/auth/csrf-token").get_json()["csrf_token"]

    retry = csrf_client.post(
        "/api/auth/login",
        json={"email": "csrf_expired_retry@example.com", "password": "secure_password123"},
        headers={"X-CSRFToken": fresh_token},
    )
    assert retry.status_code == 200


# ---------------------------------------------------------------------------
# CSRF stays enforced - no accidental exemption
# ---------------------------------------------------------------------------

def test_csrf_protection_is_not_disabled_or_exempted_anywhere():
    assert main_app.app.config["WTF_CSRF_ENABLED"] is not False
    assert "auth" not in {bp.name for bp in main_app.csrf._exempt_blueprints}
    assert not any(
        "auth" in str(view) for view in main_app.csrf._exempt_views
    )
