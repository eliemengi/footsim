import pytest
from sqlalchemy import text
from src.models import db, User
import app as main_app

def test_migration_schema_matches_models(postgres_db):
    """
    Ensures that the PostgreSQL database created via Alembic upgrade()
    contains all columns defined in the SQLAlchemy models.
    This prevents false positives where tests pass using db.create_all()
    while the real database lacks migrations for new columns.
    """
    with main_app.app.app_context():
        # Check if verified_at exists in the actual postgres schema
        result = db.session.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='users' AND column_name='verified_at'"
        )).scalar()
        assert result == 'verified_at', "Migration drift detected: verified_at missing from PostgreSQL users table"
        
        # Check if sessions_valid_after exists
        result = db.session.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='users' AND column_name='sessions_valid_after'"
        )).scalar()
        assert result == 'sessions_valid_after', "Migration drift detected: sessions_valid_after missing from PostgreSQL users table"
        
        # Finally, verify an actual insert works
        user = User(
            email="drift_test@example.com",
            first_name="Drift",
            last_name="Test"
        )
        user.set_password("securepassword")
        db.session.add(user)
        db.session.commit()
        
        assert user.id is not None
