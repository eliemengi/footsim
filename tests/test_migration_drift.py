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
        
        # Onboarding-Spalten. Sie sind der eigentliche Grund, warum es
        # diesen Test gibt: db.create_all() haette sie in jedem Fall
        # angelegt, die Migration aber moeglicherweise nicht.
        for table, column in (
            ("users", "profile_onboarding_completed"),
            ("favorite_teams", "source"),
            ("favorite_teams", "team_name"),
            ("favorite_teams", "crest_url"),
        ):
            result = db.session.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name=:table AND column_name=:column"
            ), {"table": table, "column": column}).scalar()
            assert result == column, (
                f"Migration drift detected: {table}.{column} missing from PostgreSQL"
            )

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
        # Beide Spalten muessen ohne explizite Angabe einen Wert haben,
        # sonst waere die Migration nicht rueckwaertsvertraeglich.
        assert user.profile_onboarding_completed is False


def test_existing_favorites_get_a_default_source(postgres_db):
    """
    Die Herkunftsspalte wurde nachtraeglich eingefuehrt. Zeilen ohne
    explizite Angabe muessen den dokumentierten Standard tragen, sonst
    waere eine gespeicherte Team-ID nicht mehr deutbar.
    """
    from src.models import FavoriteTeam

    with main_app.app.app_context():
        user = User(
            email="favorite_default@example.com",
            first_name="Favorite",
            last_name="Default"
        )
        user.set_password("securepassword")
        db.session.add(user)
        db.session.commit()

        db.session.execute(text(
            "INSERT INTO favorite_teams (user_id, team_id, created_at) "
            "VALUES (:user_id, 5, NOW())"
        ), {"user_id": user.id})
        db.session.commit()

        stored = db.session.execute(
            db.select(FavoriteTeam).filter_by(user_id=user.id)
        ).scalar_one()
        assert stored.source == "football-data"
