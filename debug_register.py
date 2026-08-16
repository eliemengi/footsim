from app import app
from src.models import db

with app.test_client() as client:
    with app.app_context():
        response = client.post("/api/auth/register", json={
            "email": "test@example.com",
            "password": "securepassword",
            "first_name": "Test",
            "last_name": "User"
        })
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.get_data(as_text=True)}")
