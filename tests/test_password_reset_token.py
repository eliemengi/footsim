"""
Passwort-Reset-Tokens muessen nach Gebrauch wertlos sein.

Der Befund
----------
Frueher enthielt die signierte Nutzlast ausschliesslich die User-ID:

    s.dumps(str(user.id), salt='password-reset')

Damit war ein Reset-Link die volle Stunde lang beliebig oft einloesbar.
Wer ihn danach noch irgendwo fand - weitergeleitete Mail, Browser-
Verlauf, Proxy-Log - konnte das Passwort ein zweites Mal setzen und das
Konto uebernehmen, ohne das aktuelle Passwort zu kennen.

Die Loesung bindet den Token an sessions_valid_after. Dieses Feld wird
bei jedem erfolgreichen set_password() neu gesetzt, wodurch sich der
Link selbst entwertet - ohne neue Spalte und ohne Token-Tabelle.

Es werden keine echten E-Mails versendet: die Tests erzeugen den Token
direkt ueber build_password_reset_token().
"""

import time

import pytest

from src.models import db, User
from src.api.auth import build_password_reset_token, load_password_reset_token
import app as main_app


NEW_PASSWORD = "brand_new_password_123"
OTHER_PASSWORD = "another_password_456"


@pytest.fixture(scope="function")
def client(postgres_db):
    main_app.app.config["TESTING"] = True
    main_app.app.config["WTF_CSRF_ENABLED"] = False
    with main_app.app.test_client() as client:
        with main_app.app.app_context():
            yield client


def _make_user(email, password="original_password_123"):
    with main_app.app.app_context():
        existing = db.session.execute(
            db.select(User).filter_by(email=email)
        ).scalar_one_or_none()
        if existing is not None:
            db.session.delete(existing)
            db.session.commit()

        user = User(email=email, first_name="Reset", last_name="Test")
        user.set_password(password)
        user.is_verified = True
        db.session.add(user)
        db.session.commit()
        return str(user.id)


def _token_for(email):
    with main_app.app.app_context():
        user = db.session.execute(db.select(User).filter_by(email=email)).scalar_one()
        return build_password_reset_token(user)


# ---------------------------------------------------------------------------
# Der eigentliche Regressionstest
# ---------------------------------------------------------------------------

def test_reset_token_cannot_be_used_twice(client):
    _make_user("reset_once@example.com")
    token = _token_for("reset_once@example.com")

    first = client.post("/api/auth/reset-password", json={
        "token": token, "new_password": NEW_PASSWORD,
    })
    assert first.status_code == 200

    # Exakt derselbe Token, unveraendert, innerhalb der Gueltigkeit.
    second = client.post("/api/auth/reset-password", json={
        "token": token, "new_password": OTHER_PASSWORD,
    })
    assert second.status_code == 400
    assert second.get_json()["error_key"] == "auth.resetInvalid"

    # Und der zweite Versuch hat das Passwort NICHT geaendert.
    login_new = client.post("/api/auth/login", json={
        "email": "reset_once@example.com", "password": NEW_PASSWORD,
    })
    assert login_new.status_code == 200

    login_other = client.post("/api/auth/login", json={
        "email": "reset_once@example.com", "password": OTHER_PASSWORD,
    })
    assert login_other.status_code == 401


def test_all_tokens_issued_before_a_reset_become_invalid(client):
    """
    Mehrere vor dem Reset angeforderte Links duerfen bis zum ersten
    erfolgreichen Reset funktionieren - danach keiner mehr.
    """
    _make_user("reset_multi@example.com")
    token_a = _token_for("reset_multi@example.com")
    token_b = _token_for("reset_multi@example.com")

    # Beide sind vor dem ersten Reset gueltig.
    with main_app.app.app_context():
        assert load_password_reset_token(token_a)[0] is not None
        assert load_password_reset_token(token_b)[0] is not None

    assert client.post("/api/auth/reset-password", json={
        "token": token_a, "new_password": NEW_PASSWORD,
    }).status_code == 200

    # Der zweite, nie benutzte Link ist jetzt ebenfalls wertlos.
    assert client.post("/api/auth/reset-password", json={
        "token": token_b, "new_password": OTHER_PASSWORD,
    }).status_code == 400


def test_password_change_also_invalidates_open_reset_links(client):
    """
    Wer sein Passwort regulaer aendert, entwertet damit auch einen
    zwischenzeitlich angeforderten Reset-Link.
    """
    _make_user("reset_change@example.com")
    token = _token_for("reset_change@example.com")

    client.post("/api/auth/login", json={
        "email": "reset_change@example.com", "password": "original_password_123",
    })
    assert client.post("/api/auth/change-password", json={
        "current_password": "original_password_123",
        "new_password": NEW_PASSWORD,
    }).status_code == 200

    assert client.post("/api/auth/reset-password", json={
        "token": token, "new_password": OTHER_PASSWORD,
    }).status_code == 400


# ---------------------------------------------------------------------------
# Token-Integritaet
# ---------------------------------------------------------------------------

def test_valid_token_works_once(client):
    _make_user("reset_valid@example.com")
    token = _token_for("reset_valid@example.com")

    assert client.post("/api/auth/reset-password", json={
        "token": token, "new_password": NEW_PASSWORD,
    }).status_code == 200


def test_tampered_token_is_rejected(client):
    _make_user("reset_tampered@example.com")
    token = _token_for("reset_tampered@example.com")

    tampered = token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb")
    response = client.post("/api/auth/reset-password", json={
        "token": tampered, "new_password": NEW_PASSWORD,
    })
    assert response.status_code == 400
    assert response.get_json()["error_key"] == "auth.resetInvalid"


def test_wrong_salt_is_rejected(client):
    """Ein Verifikations-Token darf kein Passwort zuruecksetzen."""
    _make_user("reset_salt@example.com")
    with main_app.app.app_context():
        from src.api.auth import get_serializer
        user = db.session.execute(
            db.select(User).filter_by(email="reset_salt@example.com")
        ).scalar_one()
        verify_token = get_serializer().dumps(str(user.id), salt="email-verify")

    assert client.post("/api/auth/reset-password", json={
        "token": verify_token, "new_password": NEW_PASSWORD,
    }).status_code == 400


def test_legacy_v1_token_format_is_rejected(client):
    """
    Das alte Format (reiner User-ID-String) war genau das mehrfach
    verwendbare - es darf nicht weiter akzeptiert werden.
    """
    user_id = _make_user("reset_legacy@example.com")
    with main_app.app.app_context():
        from src.api.auth import get_serializer
        legacy = get_serializer().dumps(user_id, salt="password-reset")

    assert client.post("/api/auth/reset-password", json={
        "token": legacy, "new_password": NEW_PASSWORD,
    }).status_code == 400


def test_expired_token_reports_expiry(client, monkeypatch):
    _make_user("reset_expired@example.com")
    token = _token_for("reset_expired@example.com")

    # Ablauf deterministisch erzwingen, statt eine Stunde zu warten.
    monkeypatch.setattr("src.api.auth.PASSWORD_RESET_MAX_AGE", -1)
    time.sleep(0.01)

    response = client.post("/api/auth/reset-password", json={
        "token": token, "new_password": NEW_PASSWORD,
    })
    assert response.status_code == 400
    assert response.get_json()["error_key"] == "auth.resetExpired"


def test_unknown_user_gets_the_generic_error(client):
    """
    Frueher antwortete ein Token fuer einen geloeschten Nutzer mit 404
    "User not found." - eine unnoetige Kontoauskunft.
    """
    _make_user("reset_gone@example.com")
    token = _token_for("reset_gone@example.com")

    with main_app.app.app_context():
        user = db.session.execute(
            db.select(User).filter_by(email="reset_gone@example.com")
        ).scalar_one()
        db.session.delete(user)
        db.session.commit()

    response = client.post("/api/auth/reset-password", json={
        "token": token, "new_password": NEW_PASSWORD,
    })
    assert response.status_code == 400
    assert response.get_json()["error_key"] == "auth.resetInvalid"


def test_reset_invalidates_existing_sessions(client):
    """Ein Reset wirft offene Sessions raus (sessions_valid_after)."""
    _make_user("reset_session@example.com")

    client.post("/api/auth/login", json={
        "email": "reset_session@example.com", "password": "original_password_123",
    })
    assert client.get("/api/auth/me").get_json()["authenticated"] is True

    token = _token_for("reset_session@example.com")
    assert client.post("/api/auth/reset-password", json={
        "token": token, "new_password": NEW_PASSWORD,
    }).status_code == 200

    assert client.get("/api/auth/me").get_json()["authenticated"] is False
