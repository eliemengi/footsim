import pytest
import os
from unittest.mock import patch, MagicMock
from flask import url_for
from src.models import db, User
from src.api.auth import get_serializer
import app as main_app

@pytest.fixture(scope='function')
def app(postgres_db):
    main_app.app.config["TESTING"] = True
    main_app.app.config["WTF_CSRF_ENABLED"] = False
    yield main_app.app

@pytest.fixture(scope='function')
def client(app):
    with app.test_client() as client:
        with app.app_context():
            yield client

#: Deutlich als Test erkennbarer Platzhalter.
#:
#: Er steht ausschliesslich hier und wird je Test gesetzt und wieder
#: entfernt. In die allgemeine Konfiguration gehoert er nicht: Ein
#: Dummy-Schluessel in app.py oder .env.example wuerde in der Produktion
#: den Zustand "Schluessel vorhanden" vortaeuschen und die Warnung
#: unterdruecken, die genau davor schuetzt.
TEST_RESEND_KEY = "re_test_dummy_key_not_a_real_credential"


@pytest.fixture
def kein_echter_http_verkehr():
    """
    Sperrt jeden echten HTTP-Aufruf ueber requests.

    Bewusst NICHT auf Socket-Ebene: PostgreSQL verbindet sich ebenfalls
    ueber einen Socket, eine pauschale Sperre wuerde die Datenbank
    mitreissen. Der Adapter ist die schmalste Stelle, an der jeder Weg
    durch requests vorbeikommt - auch Session().post(), das ein Patch auf
    requests.post nicht erfasst.
    """
    def gesperrt(*args, **kwargs):
        raise AssertionError(
            "Es wurde ein echter HTTP-Aufruf versucht. Der Mailversand "
            "muss vollstaendig ersetzt sein."
        )

    with patch("requests.adapters.HTTPAdapter.send", gesperrt):
        yield


@pytest.fixture
def mock_requests_post(app, kein_echter_http_verkehr):
    """
    Ersetzt den Resend-Aufruf und schafft die Voraussetzungen dafuer.

    WARUM DIE FIXTURE MEHR TUT ALS ZU PATCHEN
    -----------------------------------------
    Der Patch auf requests.post allein reichte nicht - und das fiel erst
    in der CI auf. src/utils/mail._send_email prueft VOR dem Netzaufruf:

        resend_key = current_app.config.get("RESEND_API_KEY")
        if not resend_key:
            return False        # <- hier war Schluss

    Lokal fuellt die ignorierte .env diesen Wert, weil app.py beim Import
    load_dotenv() ruft. Im frischen Checkout gibt es keine .env und kein
    Secret: Die Funktion kehrte vor dem gemockten Aufruf zurueck, die
    Registrierung meldete "email_failed", und der Mock wurde nie
    aufgerufen. Der Test haing damit an einer Datei, die absichtlich
    nicht im Repository liegt.

    Deshalb setzt die Fixture den Schluessel selbst - als klar
    erkennbaren Platzhalter, nur fuer die Dauer des Tests und
    ausdruecklich zurueckgesetzt.

    DER HINTERGRUNDVERSAND
    ----------------------
    /api/auth/resend-verification versendet ueber send_in_background(),
    also in einem Thread. assert_called_once() unmittelbar nach der
    Antwort war deshalb ein Wettlauf: Lokal gewann der Thread meist,
    garantiert war es nie.

    Ersetzt wird die Funktion an der Stelle, an der die Route sie
    aufruft - src.api.auth importiert sie in den eigenen Namensraum.
    Der Versand laeuft dadurch synchron; send_verification_email und
    _send_email selbst bleiben echt.
    """
    vorheriger_schluessel = app.config.get("RESEND_API_KEY")
    app.config["RESEND_API_KEY"] = TEST_RESEND_KEY

    def sofort(send_callable, *args, **kwargs):
        return send_callable(*args, **kwargs)

    try:
        with patch("src.utils.mail.requests.post") as mock_post:
            with patch("src.api.auth.send_in_background", sofort):
                with patch.dict(os.environ, {"MAIL_MOCK": "false"}):
                    # Default mock returns a successful response
                    mock_response = MagicMock()
                    mock_response.status_code = 200
                    mock_response.raise_for_status.return_value = None
                    mock_post.return_value = mock_response
                    yield mock_post
    finally:
        if vorheriger_schluessel is None:
            app.config.pop("RESEND_API_KEY", None)
        else:
            app.config["RESEND_API_KEY"] = vorheriger_schluessel

def test_registration_with_mocked_email(client, app, mock_requests_post):
    """Test registration triggers the mocked email sending with the correct payload."""
    with app.app_context():
        # Clear users
        db.session.query(User).delete()
        db.session.commit()
    
    response = client.post("/api/auth/register", json={
        "first_name": "Test",
        "last_name": "User",
        "email": "test@footsim.de",
        "password": "securepassword123"
    })
    
    assert response.status_code == 201
    data = response.get_json()
    assert data["status"] == "success"
    
    # Check that requests.post was called once
    mock_requests_post.assert_called_once()
    
    # Verify the payload sent to Resend
    call_args, call_kwargs = mock_requests_post.call_args
    assert call_args[0] == "https://api.resend.com/emails"
    assert "Authorization" in call_kwargs["headers"]
    expected_key = app.config.get("RESEND_API_KEY")
    assert f"Bearer {expected_key}" in call_kwargs["headers"]["Authorization"]
    
    payload = call_kwargs["json"]
    assert payload["to"] == ["test@footsim.de"]
    assert payload["from"] == "FootSim <noreply@footsim.de>"
    assert "api/auth/verify?token=" in payload["html"]
    
    # Check user state in DB
    with app.app_context():
        user = db.session.query(User).filter_by(email="test@footsim.de").first()
        assert user is not None
        assert user.is_verified is False
        assert user.verified_at is None

def test_registration_with_email_failure(client, app, mock_requests_post):
    """Test registration behavior when Resend API fails."""
    import requests
    
    # Mock a network failure or 500
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.raise_for_status.side_effect = requests.RequestException("API Error", response=mock_response)
    mock_requests_post.return_value = mock_response
    
    with app.app_context():
        db.session.query(User).delete()
        db.session.commit()
        
    response = client.post("/api/auth/register", json={
        "first_name": "Fail",
        "last_name": "User",
        "email": "fail@footsim.de",
        "password": "securepassword123"
    })
    
    # Should still return 201, but indicate email failure
    assert response.status_code == 201
    data = response.get_json()
    assert data["status"] == "email_failed"
    
    # Check user is still created in DB
    with app.app_context():
        user = db.session.query(User).filter_by(email="fail@footsim.de").first()
        assert user is not None
        assert user.is_verified is False

def test_verify_endpoint_success(client, app):
    """Test valid verification token redirect."""
    with app.app_context():
        db.session.query(User).delete()
        user = User(first_name="Verify", last_name="User", email="verify@footsim.de")
        user.set_password("securepassword123")
        db.session.add(user)
        db.session.commit()
        
        s = get_serializer()
        token = s.dumps(str(user.id), salt='email-verify')
        
    # The verify endpoint uses GET now
    response = client.get(f"/api/auth/verify?token={token}")
    
    # Should be a 302 redirect
    assert response.status_code == 302
    assert "/?verified=1" in response.location
    
    with app.app_context():
        user = db.session.query(User).filter_by(email="verify@footsim.de").first()
        assert user.is_verified is True
        assert user.verified_at is not None

def test_verify_endpoint_already_verified(client, app):
    """Test already verified token redirect."""
    with app.app_context():
        db.session.query(User).delete()
        user = User(first_name="Verify", last_name="User", email="verify@footsim.de")
        user.set_password("securepassword123")
        user.is_verified = True
        db.session.add(user)
        db.session.commit()
        
        s = get_serializer()
        token = s.dumps(str(user.id), salt='email-verify')
        
    response = client.get(f"/api/auth/verify?token={token}")
    assert response.status_code == 302
    assert "/?verified=already" in response.location

def test_verify_endpoint_invalid_token(client, app):
    response = client.get(f"/api/auth/verify?token=invalid_token")
    assert response.status_code == 302
    assert "/?verify_error=invalid" in response.location

def test_verify_endpoint_expired_token(client, app):
    with app.app_context():
        db.session.query(User).delete()
        user = User(first_name="Verify", last_name="User", email="verify@footsim.de")
        user.set_password("securepassword123")
        db.session.add(user)
        db.session.commit()
        
        # Manually create an expired token by overriding the serializer's time
        from itsdangerous import URLSafeTimedSerializer
        import time
        s = URLSafeTimedSerializer(app.config["SECRET_KEY"])
        # A token generated 2 days ago
        token = s.dumps(str(user.id), salt='email-verify')
        
    # To properly mock expiration without changing the real token generation,
    # we can use patch on s.loads but it's cleaner to mock the time during load or just use patch
    with patch('src.api.auth.URLSafeTimedSerializer.loads') as mock_loads:
        from itsdangerous import SignatureExpired
        mock_loads.side_effect = SignatureExpired("Token expired")
        response = client.get(f"/api/auth/verify?token={token}")
        
    assert response.status_code == 302
    assert "/?verify_error=expired" in response.location

def test_resend_verification_success(client, app, mock_requests_post):
    with app.app_context():
        db.session.query(User).delete()
        user = User(first_name="Resend", last_name="User", email="resend@footsim.de")
        user.set_password("secure")
        db.session.add(user)
        db.session.commit()
        
    response = client.post("/api/auth/resend-verification", json={"email": "resend@footsim.de"})
    assert response.status_code == 200
    mock_requests_post.assert_called_once()
    
def test_resend_verification_failure_stays_generic(client, app, mock_requests_post):
    """
    Ein fehlgeschlagener Versand darf sich NICHT in der Antwort zeigen.

    Frueher lieferte diese Route bei einem Providerfehler 503 mit
    status="email_failed". Dieser Zweig war per Definition nur
    erreichbar, wenn das Konto existierte UND unbestaetigt war - der
    Statuscode allein verriet damit die Existenz der Adresse. Das ist
    ein staerkeres Enumerationssignal als der zusaetzlich vorhandene
    Timing-Unterschied und wiegt schwerer als die verlorene Rueckmeldung
    ueber den Providerausfall (der steht im Serverlog).

    Der Test prueft deshalb jetzt das korrigierte Verhalten: immer
    dieselbe generische Antwort.
    """
    import requests
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.raise_for_status.side_effect = requests.RequestException("API Error", response=mock_response)
    mock_requests_post.return_value = mock_response

    with app.app_context():
        db.session.query(User).delete()
        user = User(first_name="Resend", last_name="User", email="resend@footsim.de")
        user.set_password("secure")
        db.session.add(user)
        db.session.commit()

    response = client.post("/api/auth/resend-verification", json={"email": "resend@footsim.de"})
    assert response.status_code == 200
    data = response.get_json()
    assert "status" not in data
    assert data["message"].startswith("If your email is registered")


def test_resend_verification_is_indistinguishable_for_unknown_email(client, app, mock_requests_post):
    """
    Bekanntes und unbekanntes Konto muessen dieselbe Antwort liefern -
    gleicher Statuscode, gleicher Text.
    """
    with app.app_context():
        db.session.query(User).delete()
        user = User(first_name="Resend", last_name="User", email="known@footsim.de")
        user.set_password("secure")
        db.session.add(user)
        db.session.commit()

    known = client.post("/api/auth/resend-verification", json={"email": "known@footsim.de"})
    unknown = client.post("/api/auth/resend-verification", json={"email": "nobody@footsim.de"})

    assert known.status_code == unknown.status_code == 200
    assert known.get_json() == unknown.get_json()


# ===========================================================================
# Regressionsschutz: der Versandpfad darf nicht an einer .env haengen
# ===========================================================================
#
# Am 24.08.2026 fielen test_registration_with_mocked_email und
# test_resend_verification_success ausschliesslich in der GitHub-CI. Der
# Grund war keine Anwendungsaenderung, sondern eine unsichtbare
# Voraussetzung: _send_email prueft RESEND_API_KEY, BEVOR es requests.post
# aufruft. Lokal fuellte die ignorierte .env den Wert, im frischen
# Checkout gab es ihn nicht - die Funktion kehrte vorher zurueck, der
# Mock wurde nie erreicht, und die Registrierung meldete "email_failed".
#
# Die Tests unten halten beide Richtungen fest, damit dieselbe
# Voraussetzung nicht wieder unbemerkt einwandert.


class TestVersandIstHermetisch:

    def test_der_erfolgsfall_braucht_keine_env_datei(self, client, app,
                                                     mock_requests_post):
        """
        Der Kern der Regression. Die echten Umgebungsvariablen werden
        zusaetzlich geleert - selbst ein vorhandenes lokales .env darf
        keinen falschen Erfolg erzeugen.
        """
        with patch.dict(os.environ, {}, clear=False):
            for schluessel in ("RESEND_API_KEY", "MAIL_DEFAULT_SENDER"):
                os.environ.pop(schluessel, None)

            with app.app_context():
                db.session.query(User).delete()
                db.session.commit()

            antwort = client.post("/api/auth/register", json={
                "first_name": "Hermetisch", "last_name": "Test",
                "email": "hermetisch@footsim.de",
                "password": "securepassword123",
            })

        assert antwort.status_code == 201
        assert antwort.get_json()["status"] == "success"
        mock_requests_post.assert_called_once()

    def test_die_mailfunktion_wird_genau_einmal_aufgerufen(self, client, app,
                                                          mock_requests_post):
        """
        Genau einmal - nicht null (der CI-Fehler) und nicht zweimal (ein
        doppelter Versand waere Spam und ein Kostenfaktor).
        """
        with app.app_context():
            db.session.query(User).delete()
            db.session.commit()

        client.post("/api/auth/register", json={
            "first_name": "Einmal", "last_name": "Test",
            "email": "einmal@footsim.de", "password": "securepassword123",
        })

        assert mock_requests_post.call_count == 1

    def test_ohne_konfigurierten_schluessel_wird_nicht_versendet(
            self, client, app, mock_requests_post):
        """
        Die Voraussetzung, an der die CI scheiterte - hier ausdruecklich
        als erwartetes Verhalten festgehalten statt als Ueberraschung.

        Ohne Schluessel darf KEIN Netzaufruf entstehen, und die Route muss
        das ehrlich melden. Das ist kein Fehler der Anwendung, sondern
        ihre richtige Antwort auf eine fehlende Konfiguration.
        """
        app.config["RESEND_API_KEY"] = None

        with app.app_context():
            db.session.query(User).delete()
            db.session.commit()

        antwort = client.post("/api/auth/register", json={
            "first_name": "Ohne", "last_name": "Schluessel",
            "email": "ohne@footsim.de", "password": "securepassword123",
        })

        assert antwort.status_code == 201
        assert antwort.get_json()["status"] == "email_failed"
        mock_requests_post.assert_not_called()

    def test_ein_providerfehler_bleibt_ein_fehler(self, client, app,
                                                  mock_requests_post):
        """
        Die Gegenprobe zur Reparatur: Der Erfolgsfall wurde reparabel
        gemacht, ohne den Fehlerfall zu beschoenigen.
        """
        import requests as requests_modul

        antwort_mock = MagicMock()
        antwort_mock.status_code = 500
        antwort_mock.raise_for_status.side_effect = requests_modul.RequestException(
            "API Error", response=antwort_mock)
        mock_requests_post.return_value = antwort_mock

        with app.app_context():
            db.session.query(User).delete()
            db.session.commit()

        antwort = client.post("/api/auth/register", json={
            "first_name": "Fehler", "last_name": "Test",
            "email": "fehler@footsim.de", "password": "securepassword123",
        })

        assert antwort.status_code == 201
        assert antwort.get_json()["status"] == "email_failed"
        mock_requests_post.assert_called_once()

    def test_der_testschluessel_ist_als_solcher_erkennbar(self, app,
                                                          mock_requests_post):
        """
        Ein Platzhalter, der wie ein echter Schluessel aussieht, landet
        irgendwann versehentlich in einer Konfiguration.
        """
        assert app.config["RESEND_API_KEY"] == TEST_RESEND_KEY
        assert "test" in TEST_RESEND_KEY and "dummy" in TEST_RESEND_KEY

    def test_der_schluessel_verschwindet_nach_dem_test(self, app):
        """
        Ohne mock_requests_post darf der Platzhalter nicht mehr stehen -
        sonst wuerde er in andere Tests lecken und dort einen Versand
        vortaeuschen.
        """
        assert app.config.get("RESEND_API_KEY") != TEST_RESEND_KEY

    def test_ein_umgangener_mock_faellt_sofort_auf(self, app,
                                                   mock_requests_post):
        """
        Belegt, dass die HTTP-Sperre wirkt. Ohne sie wuerde ein Aufruf,
        der am Mock vorbeigeht - etwa ueber Session().post() - still ins
        Netz gehen und in der CI einen unerklaerlichen Fehler erzeugen.
        """
        import requests as requests_modul

        with pytest.raises(AssertionError, match="echter HTTP-Aufruf"):
            requests_modul.Session().post("https://api.resend.com/emails",
                                          json={}, timeout=1)
