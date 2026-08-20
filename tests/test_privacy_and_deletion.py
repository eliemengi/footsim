"""
Datenschutzseite, oeffentliche Loeschseite und Account-Loeschung.

Hintergrund
-----------
Die Datenschutzerklaerung behauptete woertlich "Es gibt keine
Benutzerkonten und keine Registrierung" - seit dem Accountsystem
objektiv falsch. Ein Test haelt diese Aussage jetzt dauerhaft fern.

Die oeffentliche Loeschseite ist eine Google-Play-Pflichtangabe fuer
Apps mit Kontoerstellung: der Loeschweg muss auch AUSSERHALB der App
erreichbar dokumentiert sein.

Alle Tests laufen gegen die isolierte Testdatenbank (postgres_db) und
loeschen ausschliesslich selbst angelegte Konten.
"""

import pytest

from src.models import db, User, FavoriteTeam
import app as main_app


PASSWORD = "delete_me_password_123"


@pytest.fixture(scope="function")
def client(postgres_db):
    """
    Bewusst OHNE umschliessenden app_context.

    _request_locale() merkt sich die aufgeloeste Sprache in ``g``. ``g``
    haengt am Application Context - ein gemeinsamer Kontext ueber
    mehrere Requests hinweg wuerde die Sprache des ERSTEN Requests
    einfrieren und ?lang= danach wirkungslos machen. Im echten Betrieb
    bekommt jeder Request seinen eigenen Kontext; der Test muss das
    nachbilden, sonst prueft er etwas anderes als die Produktion tut.

    Die Helfer unten oeffnen ihren Kontext jeweils selbst.
    """
    main_app.app.config["TESTING"] = True
    main_app.app.config["WTF_CSRF_ENABLED"] = False
    with main_app.app.test_client() as client:
        yield client


@pytest.fixture(scope="function")
def csrf_client(postgres_db):
    """Wie oben, aber mit aktivem CSRF-Schutz."""
    main_app.app.config["TESTING"] = True
    main_app.app.config["WTF_CSRF_ENABLED"] = True
    with main_app.app.test_client() as client:
        yield client
    main_app.app.config["WTF_CSRF_ENABLED"] = False


def _make_user(email, with_favorite=True):
    with main_app.app.app_context():
        existing = db.session.execute(
            db.select(User).filter_by(email=email)
        ).scalar_one_or_none()
        if existing is not None:
            db.session.delete(existing)
            db.session.commit()

        user = User(email=email, first_name="Delete", last_name="Test")
        user.set_password(PASSWORD)
        user.is_verified = True
        db.session.add(user)
        db.session.commit()

        if with_favorite:
            db.session.add(FavoriteTeam(
                user_id=user.id, team_id=157, source="apisports",
                team_name="Bayern", crest_url="https://media.api-sports.io/football/teams/157.png",
            ))
            db.session.commit()
        return str(user.id)


def _login(client, email):
    return client.post("/api/auth/login", json={"email": email, "password": PASSWORD})


def _page(client, path):
    """
    Holt eine Seite.

    WICHTIG fuer Aufrufer: _request_locale() merkt sich die aufgeloeste
    Sprache in ``g``, das am Application Context haengt. Die Fixture
    postgres_db (conftest.py) yielded innerhalb eines app_context, der
    ueber den ganzen Test bestehen bleibt. Deshalb darf ein Test NUR
    EINE Sprache abfragen - sonst gewinnt die des ersten Requests.
    Zwei Sprachen = zwei Tests.
    """
    return client.get(path).get_data(as_text=True)


# ---------------------------------------------------------------------------
# Datenschutzseite
# ---------------------------------------------------------------------------

def test_privacy_page_is_public(client):
    """Ohne Login erreichbar - Pflicht fuer beide Stores."""
    response = client.get("/datenschutz")
    assert response.status_code == 200


def test_privacy_page_no_longer_claims_there_are_no_accounts_de(client):
    """Die konkrete Falschaussage darf nicht zurueckkehren."""
    body = _page(client, "/datenschutz?lang=de")
    assert "keine Benutzerkonten" not in body
    assert "keine Registrierung" not in body


def test_privacy_page_no_longer_claims_there_are_no_accounts_en(client):
    body = _page(client, "/datenschutz?lang=en")
    assert "keine Benutzerkonten" not in body
    assert "keine Registrierung" not in body


def test_privacy_page_has_german_content(client):
    body = _page(client, "/datenschutz?lang=de")
    for needle in ("Verantwortlicher", "Benutzerkonto", "Cookies",
                   "Lieblingsverein", "Resend", "Deine Rechte"):
        assert needle in body, needle


def test_privacy_page_has_english_content(client):
    body = _page(client, "/datenschutz?lang=en")
    for needle in ("Controller", "User account", "Cookies",
                   "Favourite club", "Resend", "Your rights"):
        assert needle in body, needle


def test_privacy_page_documents_the_real_storage(client):
    """
    Die Seite muss die tatsaechlich verwendeten Speicher benennen -
    sonst waere sie wieder unvollstaendig.
    """
    body = _page(client, "/datenschutz?lang=de")
    for key in ("session", "footsim_lang", "theme",
                "footsim_onboarding", "unverified_email"):
        assert key in body, key
    # Der einzige automatische Drittanbieter-Abruf.
    assert "crests.football-data.org" in body
    assert "media.api-sports.io" in body


def test_privacy_page_links_to_deletion(client):
    body = _page(client, "/datenschutz?lang=de")
    assert "/account-loeschen" in body


def test_privacy_page_uses_real_contact_details(client):
    body = _page(client, "/datenschutz?lang=de")
    assert "eliebusiness0@gmail.com" in body
    assert "Elie Mengi" in body


# ---------------------------------------------------------------------------
# Oeffentliche Loeschseite
# ---------------------------------------------------------------------------

def test_public_deletion_page_is_reachable_without_login(client):
    assert client.get("/account-loeschen").status_code == 200
    # Englischsprachiges Alias fuer das Store-Formular.
    assert client.get("/delete-account").status_code == 200


def test_public_deletion_page_explains_both_paths_de(client):
    de = _page(client, "/account-loeschen?lang=de")
    assert "Account löschen" in de
    assert "eliebusiness0@gmail.com" in de
    # Weg 1 (in der App) und Weg 2 (ohne Kontozugriff)
    assert "Weg 1" in de and "Weg 2" in de


def test_public_deletion_page_explains_both_paths_en(client):
    en = _page(client, "/account-loeschen?lang=en")
    assert "Option 1" in en and "Option 2" in en
    assert "eliebusiness0@gmail.com" in en


def test_public_deletion_page_has_no_anonymous_delete_form(client):
    """
    Eine Loeschung allein anhand einer eingetippten E-Mail waere ohne
    Identitaetsnachweis UND eine Kontoauskunft. Es darf deshalb kein
    absendendes Formular auf der oeffentlichen Seite geben.
    """
    body = _page(client, "/account-loeschen")
    assert "<form" not in body.lower()


def test_deletion_page_linked_from_account_area(client):
    body = _page(client, "/")
    assert "/account-loeschen" in body


# ---------------------------------------------------------------------------
# Account-Loeschung: Schutzmechanismen
# ---------------------------------------------------------------------------

def test_deletion_requires_authentication(client):
    response = client.post("/api/auth/delete-account",
                           json={"current_password": PASSWORD})
    assert response.status_code == 401


def test_deletion_requires_csrf(csrf_client):
    """Ohne CSRF-Token darf nichts geloescht werden."""
    _make_user("del_csrf@example.com")
    response = csrf_client.post("/api/auth/delete-account",
                                json={"current_password": PASSWORD})
    assert response.status_code == 400
    assert response.get_json()["error_key"] == "auth.csrfError"

    with main_app.app.app_context():
        assert db.session.execute(
            db.select(User).filter_by(email="del_csrf@example.com")
        ).scalar_one_or_none() is not None


def test_wrong_password_deletes_nothing(client):
    _make_user("del_wrongpw@example.com")
    _login(client, "del_wrongpw@example.com")

    response = client.post("/api/auth/delete-account",
                           json={"current_password": "definitely_wrong_pw"})
    assert response.status_code == 401

    with main_app.app.app_context():
        user = db.session.execute(
            db.select(User).filter_by(email="del_wrongpw@example.com")
        ).scalar_one_or_none()
        assert user is not None, "Konto darf bei falschem Passwort bestehen bleiben"
        # Auch der Favorit bleibt - keine Teil-Loeschung.
        assert db.session.execute(
            db.select(FavoriteTeam).filter_by(user_id=user.id)
        ).scalars().all()


def test_missing_password_deletes_nothing(client):
    _make_user("del_nopw@example.com")
    _login(client, "del_nopw@example.com")

    response = client.post("/api/auth/delete-account", json={})
    assert response.status_code == 400

    with main_app.app.app_context():
        assert db.session.execute(
            db.select(User).filter_by(email="del_nopw@example.com")
        ).scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Account-Loeschung: Erfolgsfall
# ---------------------------------------------------------------------------

def test_successful_deletion_removes_user_and_favorites(client):
    user_id = _make_user("del_ok@example.com")
    _login(client, "del_ok@example.com")

    response = client.post("/api/auth/delete-account",
                           json={"current_password": PASSWORD})
    assert response.status_code == 200

    with main_app.app.app_context():
        assert db.session.execute(
            db.select(User).filter_by(email="del_ok@example.com")
        ).scalar_one_or_none() is None
        # Cascade: keine verwaisten Favoriten.
        assert db.session.execute(
            db.select(FavoriteTeam).filter_by(user_id=user_id)
        ).scalars().all() == []


def test_successful_deletion_invalidates_the_session(client):
    _make_user("del_session@example.com")
    _login(client, "del_session@example.com")
    assert client.get("/api/auth/me").get_json()["authenticated"] is True

    assert client.post("/api/auth/delete-account",
                       json={"current_password": PASSWORD}).status_code == 200

    assert client.get("/api/auth/me").get_json()["authenticated"] is False


def test_deletion_response_leaks_no_personal_data(client):
    _make_user("del_leak@example.com")
    _login(client, "del_leak@example.com")

    body = client.post("/api/auth/delete-account",
                       json={"current_password": PASSWORD}).get_data(as_text=True)
    assert "del_leak@example.com" not in body
    assert "Delete" not in body or "deleted" in body.lower()


def test_deletion_does_not_touch_other_accounts(client):
    """Sicherstellen, dass nur das eigene Konto verschwindet."""
    _make_user("del_target@example.com")
    _make_user("del_bystander@example.com")

    _login(client, "del_target@example.com")
    assert client.post("/api/auth/delete-account",
                       json={"current_password": PASSWORD}).status_code == 200

    with main_app.app.app_context():
        assert db.session.execute(
            db.select(User).filter_by(email="del_bystander@example.com")
        ).scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Kein Consent-Banner ohne optionales Tracking
# ---------------------------------------------------------------------------

def test_no_cookie_banner_and_no_tracking(client):
    """
    Solange nur notwendige Cookies und selbst gewaehlte Einstellungen
    gespeichert werden, waere ein Consent-Banner ueberfluessig - und
    ein Tracker wuerde ihn noetig machen. Beides hier abgesichert.
    """
    from pathlib import Path
    root = Path(__file__).parent.parent

    script = (root / "static" / "script.js").read_text(encoding="utf-8")
    index = (root / "templates" / "index.html").read_text(encoding="utf-8")

    for tracker in ("google-analytics", "googletagmanager", "gtag(",
                    "matomo", "plausible", "fbq(", "hotjar", "mixpanel"):
        assert tracker not in script.lower(), tracker
        assert tracker not in index.lower(), tracker

    for banner in ("cookie-banner", "cookieBanner", "cookie-consent", "cookieConsent"):
        assert banner not in script, banner
        assert banner not in index, banner
