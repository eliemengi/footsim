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
    assert response.status_code == 302
    assert "/?verified=1" in response.location
    
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


def test_account_onboarding_flow(client):
    # 1. Register
    response = client.post("/api/auth/register", json={
        "email": "onboarding_test@example.com",
        "password": "secure_password123",
        "first_name": "Onboard",
        "last_name": "Test",
        "favorite_team_id": 5 # Should be ignored now
    })
    assert response.status_code == 201
    
    # Verify user
    with main_app.app.app_context():
        user = db.session.execute(db.select(User).filter_by(email="onboarding_test@example.com")).scalar_one()
        user.is_verified = True
        user_id = user.id
        db.session.commit()
        
    # Login
    response = client.post("/api/auth/login", json={
        "email": "onboarding_test@example.com",
        "password": "secure_password123"
    })
    assert response.status_code == 200
    
    # 2. Check /me for profile_onboarding_completed
    response = client.get("/api/auth/me")
    data = response.get_json()
    assert data["user"]["profile_onboarding_completed"] is False
    assert data["favorite_team_id"] is None
    
    # 3. Unauthorized skip
    client.post("/api/auth/logout")
    response = client.post("/api/auth/favorite/skip")
    assert response.status_code == 401
    
    # Relogin
    client.post("/api/auth/login", json={
        "email": "onboarding_test@example.com",
        "password": "secure_password123"
    })
    
    # 4. Skip onboarding
    response = client.post("/api/auth/favorite/skip")
    assert response.status_code == 200
    
    response = client.get("/api/auth/me")
    assert response.get_json()["user"]["profile_onboarding_completed"] is True
    
    # 5. Set favorite
    response = client.post("/api/auth/favorite", json={"team_id": 4})
    assert response.status_code == 200
    
    response = client.get("/api/auth/me")
    assert response.get_json()["favorite_team_id"] == 4
    assert response.get_json()["user"]["profile_onboarding_completed"] is True
    
    # 6. Delete favorite
    response = client.delete("/api/auth/favorite")
    assert response.status_code == 200
    
    response = client.get("/api/auth/me")
    assert response.get_json()["favorite_team_id"] is None
    # Still true!
    assert response.get_json()["user"]["profile_onboarding_completed"] is True


def test_favorite_team_records_its_id_source(client):
    """
    FootSim spricht zwei Anbieter mit getrennten Team-ID-Raeumen an.
    Ohne festgehaltene Herkunft ist eine gespeicherte Zahl nicht
    deutbar - deshalb wird sie mitgeschrieben statt erraten.
    """
    client.post("/api/auth/register", json={
        "email": "favorite_source@example.com",
        "password": "secure_password123",
        "first_name": "Source",
        "last_name": "Test",
    })
    with main_app.app.app_context():
        user = db.session.execute(
            db.select(User).filter_by(email="favorite_source@example.com")
        ).scalar_one()
        user.is_verified = True
        db.session.commit()

    client.post("/api/auth/login", json={
        "email": "favorite_source@example.com",
        "password": "secure_password123",
    })

    # Ohne Angabe gilt die Quelle der Teamauswahl (/api/standings).
    response = client.post("/api/auth/favorite", json={"team_id": 5})
    assert response.status_code == 200
    assert response.get_json()["source"] == "football-data"

    response = client.get("/api/auth/me")
    assert response.get_json()["favorite_team_source"] == "football-data"

    # Eine ausdrueckliche, bekannte Quelle wird uebernommen.
    response = client.post("/api/auth/favorite", json={"team_id": 157, "source": "apisports"})
    assert response.status_code == 200
    assert client.get("/api/auth/me").get_json()["favorite_team_source"] == "apisports"

    # Alles andere wird abgelehnt, statt still als Standard zu gelten.
    response = client.post("/api/auth/favorite", json={"team_id": 5, "source": "transfermarkt"})
    assert response.status_code == 400

    # Ohne Favorit gibt es auch keine Herkunft.
    client.delete("/api/auth/favorite")
    assert client.get("/api/auth/me").get_json()["favorite_team_source"] is None
