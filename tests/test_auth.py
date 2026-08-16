import pytest
from src.models import db, User
from src.api.auth import get_serializer
import app as main_app

@pytest.fixture(scope='function')
def client(postgres_db):
    main_app.app.config["TESTING"] = True
    # Disable CSRF for testing auth endpoints via raw client
    main_app.app.config["WTF_CSRF_ENABLED"] = False
    with main_app.app.test_client() as client:
        with main_app.app.app_context():
            yield client

def test_register_login_flow(client):
    # 1. Register
    response = client.post("/api/auth/register", json={
        "email": "auth_test@example.com",
        "password": "secure_password123",
        "first_name": "Auth",
        "last_name": "Test"
    })
    assert response.status_code == 201
    assert "check your email" in response.get_json()["message"]
    
    # User should exist in DB but not be verified
    with main_app.app.app_context():
        user = db.session.execute(db.select(User).filter_by(email="auth_test@example.com")).scalar_one()
        assert not user.is_verified
        assert user.password_hash != "secure_password123"
        user_id = user.id
        
    # 2. Login unverified
    response = client.post("/api/auth/login", json={
        "email": "auth_test@example.com",
        "password": "secure_password123"
    })
    assert response.status_code == 200
    assert response.get_json()["user"]["is_verified"] is False
    
    # 3. Check me endpoint
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    data = response.get_json()
    assert data["authenticated"] is True
    assert data["user"]["email"] == "auth_test@example.com"
    
    # 4. Verify email
    with main_app.app.app_context():
        s = get_serializer()
        token = s.dumps(str(user_id), salt='email-verify')
        
    response = client.get(f"/api/auth/verify?token={token}")
    assert response.status_code == 200
    
    with main_app.app.app_context():
        user = db.session.execute(db.select(User).filter_by(email="auth_test@example.com")).scalar_one()
        assert user.is_verified
        assert user.verified_at is not None

    # 5. Logout
    response = client.post("/api/auth/logout")
    assert response.status_code == 200
    
    # 6. Check me endpoint after logout
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.get_json()["authenticated"] is False
    
    # 7. Change password without auth
    response = client.post("/api/auth/change-password", json={
        "current_password": "secure_password123",
        "new_password": "new_password123"
    })
    assert response.status_code == 401
