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

@pytest.fixture
def mock_requests_post():
    with patch("src.utils.mail.requests.post") as mock_post:
        with patch.dict(os.environ, {"MAIL_MOCK": "false"}):
            # Default mock returns a successful response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.raise_for_status.return_value = None
            mock_post.return_value = mock_response
            yield mock_post

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
    
def test_resend_verification_failure(client, app, mock_requests_post):
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
    assert response.status_code == 503
    data = response.get_json()
    assert data["status"] == "email_failed"
