"""
Absicherung der Haertungsmassnahmen aus dem Security-Auftrag.

Deckt ab:
  - Wappen-URL-Allowlist (Trackingschutz)
  - Basis-Security-Header
  - keine E-Mail in User.__repr__
  - zentrale Betriebsmodus-Ermittlung
"""

import pytest

from src.models import db, User
from src.api.auth import normalize_crest_url, ALLOWED_CREST_HOSTS
import app as main_app


@pytest.fixture(scope="function")
def client(postgres_db):
    main_app.app.config["TESTING"] = True
    main_app.app.config["WTF_CSRF_ENABLED"] = False
    with main_app.app.test_client() as client:
        with main_app.app.app_context():
            yield client


def _login(client, email):
    with main_app.app.app_context():
        existing = db.session.execute(
            db.select(User).filter_by(email=email)
        ).scalar_one_or_none()
        if existing is None:
            user = User(email=email, first_name="Sec", last_name="Test")
            user.set_password("secure_password123")
            user.is_verified = True
            db.session.add(user)
            db.session.commit()
    client.post("/api/auth/login", json={
        "email": email, "password": "secure_password123",
    })


# ---------------------------------------------------------------------------
# Wappen-URL
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://crests.football-data.org/5.png",
    "https://media.api-sports.io/football/teams/157.png",
])
def test_known_crest_hosts_are_accepted(url):
    value, error = normalize_crest_url(url)
    assert error is None
    assert value == url


@pytest.mark.parametrize("url,reason", [
    ("http://media.api-sports.io/x.png",              "kein HTTPS"),
    ("javascript:alert(1)",                            "javascript-Schema"),
    ("data:image/png;base64,AAAA",                     "data-URI"),
    ("file:///etc/passwd",                             "file-Schema"),
    ("https://evil.example/x.png",                     "fremder Host"),
    ("https://media.api-sports.io.evil.example/x.png", "Suffix-Trick"),
    ("https://evil-media.api-sports.io/x.png",         "Praefix-Trick"),
    ("https://user@evil.example/x.png",                "Userinfo-Trick"),
    ("https://media.api-sports.io:8080/x.png",         "Nicht-Standardport"),
    ("https://127.0.0.1/x.png",                        "localhost"),
    ("https://192.168.1.10/x.png",                     "private IP"),
])
def test_dangerous_crest_urls_are_rejected(url, reason):
    value, error = normalize_crest_url(url)
    assert value is None, reason
    assert error is not None, reason


def test_missing_crest_url_stays_allowed():
    """Ein Favorit ohne Wappen ist ein gueltiger Zustand."""
    assert normalize_crest_url(None) == (None, None)
    assert normalize_crest_url("") == (None, None)
    assert normalize_crest_url("   ") == (None, None)


def test_overlong_crest_url_is_rejected():
    value, error = normalize_crest_url("https://media.api-sports.io/" + "a" * 600)
    assert value is None and error is not None


def test_favorite_endpoint_rejects_foreign_crest_host(client):
    _login(client, "crest_reject@example.com")

    response = client.post("/api/auth/favorite", json={
        "team_id": 157,
        "team_name": "Bayern",
        "crest_url": "https://tracker.example/pixel.png",
    })
    assert response.status_code == 400
    assert response.get_json()["error_key"] == "account.invalidCrestUrl"

    # Nichts gespeichert - der manipulierte Wert darf nicht durchrutschen.
    assert client.get("/api/auth/me").get_json()["favorite_team_crest"] is None


def test_favorite_endpoint_accepts_allowed_crest_host(client):
    _login(client, "crest_accept@example.com")

    response = client.post("/api/auth/favorite", json={
        "team_id": 157,
        "team_name": "Bayern",
        "crest_url": "https://media.api-sports.io/football/teams/157.png",
    })
    assert response.status_code == 200
    assert client.get("/api/auth/me").get_json()["favorite_team_crest"].endswith("157.png")


def test_allowlist_is_not_accidentally_empty():
    assert ALLOWED_CREST_HOSTS
    assert "media.api-sports.io" in ALLOWED_CREST_HOSTS


# ---------------------------------------------------------------------------
# Security-Header
# ---------------------------------------------------------------------------

def test_baseline_security_headers_present(client):
    response = client.get("/")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert "geolocation=()" in response.headers.get("Permissions-Policy", "")


def test_no_hsts_and_no_enforcing_csp_from_flask(client):
    """
    Beide gehoeren an den TLS-terminierenden nginx bzw. hinter eine
    Report-Only-Phase - nicht blind aus der App.
    """
    response = client.get("/")
    assert "Strict-Transport-Security" not in response.headers
    assert "Content-Security-Policy" not in response.headers


def test_auth_responses_are_not_cacheable(client):
    response = client.get("/api/auth/me")
    assert response.headers.get("Cache-Control") == "no-store"


# ---------------------------------------------------------------------------
# Datenminimierung und Betriebsmodus
# ---------------------------------------------------------------------------

def test_user_repr_contains_no_personal_data():
    user = User(email="repr@example.com", first_name="Repr", last_name="Test")
    text = repr(user)
    assert "repr@example.com" not in text
    assert "Repr" not in text
    assert "User" in text


def test_environment_resolution_rejects_unknown_values(monkeypatch):
    """Ein Tippfehler darf nicht stillschweigend 'development' bedeuten."""
    monkeypatch.setenv("FOOTSIM_ENV", "produktion")
    with pytest.raises(RuntimeError):
        main_app._resolve_environment()


@pytest.mark.parametrize("value,expected", [
    ("production", "production"),
    ("development", "development"),
    ("testing", "testing"),
    ("PRODUCTION", "production"),
    ("", "development"),
])
def test_environment_resolution_accepts_known_values(monkeypatch, value, expected):
    monkeypatch.setenv("FOOTSIM_ENV", value)
    monkeypatch.delenv("FLASK_ENV", raising=False)
    assert main_app._resolve_environment() == expected


def test_secure_cookie_is_bound_to_production_flag():
    assert main_app.app.config["SESSION_COOKIE_SECURE"] == main_app.app.config["IS_PRODUCTION"]
    assert main_app.app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert main_app.app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
